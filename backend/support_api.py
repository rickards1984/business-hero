"""
Support Ticket System — Backend API

AI-first support: users chat with an AI agent that references a knowledge base.
If the AI can't help, the conversation escalates to a human-managed ticket.
Admin endpoints for ticket management and knowledge base CRUD.
"""

import logging
import os
import re
from datetime import datetime
from typing import Optional, List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from rate_limiting import limiter, LIMIT_AI_CHAT
from pydantic import BaseModel
from sqlmodel import Session
from sqlalchemy import text

from db import get_session
from auth import get_user_business_context, get_platform_admin_context

_logger = logging.getLogger("support")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/v1/support", tags=["Support"])
admin_router = APIRouter(prefix="/v1/admin/support", tags=["Admin Support"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class SupportMessageCreate(BaseModel):
    content: str
    conversation_id: Optional[str] = None


class SupportArticleCreate(BaseModel):
    title: str
    content: str
    summary: Optional[str] = None
    category: str = "general"
    tags: Optional[List[str]] = None
    is_published: bool = True


class SupportArticleUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    is_published: Optional[bool] = None


class AdminReplyCreate(BaseModel):
    content: str
    is_internal: bool = False


class TicketStatusUpdate(BaseModel):
    status: str
    priority: Optional[str] = None
    admin_notes: Optional[str] = None


class EscalateRequest(BaseModel):
    conversation_id: str


# ---------------------------------------------------------------------------
# AI support agent
# ---------------------------------------------------------------------------

async def _get_ai_support_response(
    user_message: str,
    conversation_history: List[dict],
    business_name: str,
    kb_articles: List[dict],
    user_name: Optional[str] = None,
) -> Tuple[str, bool, Optional[str], float]:
    """
    Returns (response_text, should_escalate, category, confidence).
    """
    kb_text = ""
    if kb_articles:
        sections = []
        for a in kb_articles:
            sections.append(f"### {a['title']}\nCategory: {a['category']}\n{a['content']}")
        kb_text = "\n---\n".join(sections)

    system_prompt = f"""You are the support assistant for Business Hero, a business management platform. You are helping a user from "{business_name}".

YOUR ROLE:
- Help users with questions about Business Hero features and functionality
- Troubleshoot common issues using the knowledge base provided
- Be friendly, concise, and professional
- Use British English

KNOWLEDGE BASE:
{kb_text if kb_text else "(No articles available yet.)"}

RULES:
1. ONLY answer questions about Business Hero and its features. If someone asks about something completely unrelated, politely redirect them.
2. Reference the knowledge base to give accurate answers. If the answer is in the knowledge base, use it.
3. If you cannot confidently answer from the knowledge base, be honest: "I'm not sure about that specific question. Would you like me to create a support ticket so our team can help you directly?"
4. NEVER make up features or capabilities that aren't mentioned in the knowledge base.
5. Keep responses concise — this is a chat, not an essay. Use short paragraphs and bullet points where helpful.
6. If the user is frustrated, acknowledge their frustration and offer to escalate.
7. If the user asks to speak to a human, a real person, or to raise a ticket, ALWAYS agree and escalate.

ESCALATION:
When you believe the conversation should be escalated to a human (either because you can't help or the user requests it), end your message with the exact tag: [ESCALATE]
Also include [ESCALATE] if:
- The user reports a bug or error you can't troubleshoot from the knowledge base
- The user is asking about billing, payments, or account changes
- The user has asked the same question twice and your answer didn't help
- The user explicitly asks for human help

CATEGORISATION:
At the end of EVERY response, add a classification tag on a new line in this format:
[CATEGORY: how-to] [CONFIDENCE: 0.9]

Categories: bug, feature-request, how-to, billing, integration, account, general
Confidence: 0.0 to 1.0 (how confident you are that you've fully resolved their question)

{f"The user's name is {user_name}." if user_name else ""}"""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_history:
        role = "assistant" if msg.get("sender_type") in ("ai", "admin") else "user"
        messages.append({"role": role, "content": msg.get("content", "")})
    messages.append({"role": "user", "content": user_message})

    try:
        import openai
        client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=30.0, max_retries=1)

        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.3,
            max_tokens=800,
        )

        ai_text = resp.choices[0].message.content.strip()

        should_escalate = "[ESCALATE]" in ai_text
        ai_text = ai_text.replace("[ESCALATE]", "").strip()

        category = "general"
        confidence = 0.5
        cat_match = re.search(r"\[CATEGORY:\s*(\S+?)\]", ai_text)
        conf_match = re.search(r"\[CONFIDENCE:\s*([\d.]+)\]", ai_text)
        if cat_match:
            category = cat_match.group(1)
        if conf_match:
            try:
                confidence = float(conf_match.group(1))
            except ValueError:
                pass

        ai_text = re.sub(r"\[CATEGORY:\s*\S+?\]", "", ai_text)
        ai_text = re.sub(r"\[CONFIDENCE:\s*[\d.]+\]", "", ai_text)
        ai_text = ai_text.strip()

        return ai_text, should_escalate, category, confidence

    except Exception as exc:
        _logger.error("[Support AI] OpenAI error: %s", exc)
        return (
            "I'm having trouble connecting right now. Let me create a support ticket so our team can help you directly.",
            True,
            "general",
            0.0,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict:
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


def _rows_to_list(rows) -> list:
    return [_row_to_dict(r) for r in rows]


def _fetch_kb_articles(session: Session) -> List[dict]:
    rows = session.execute(
        text("SELECT id, title, content, summary, category, tags FROM support_articles WHERE is_published = TRUE ORDER BY sort_order")
    ).fetchall()
    return _rows_to_list(rows)


# ---------------------------------------------------------------------------
# User-facing endpoints
# ---------------------------------------------------------------------------

@router.post("/chat")
@limiter.limit(LIMIT_AI_CHAT)
async def support_chat(
    request: Request,
    message: SupportMessageCreate,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Send a support message. AI responds automatically unless escalated."""
    business_id = str(auth_ctx["business_id"])
    user_id = str(auth_ctx["user_id"])
    now = datetime.utcnow().isoformat()

    biz_row = session.execute(
        text("SELECT name FROM businesses WHERE id = :bid"),
        {"bid": business_id},
    ).fetchone()
    business_name = biz_row.name if biz_row else "Your business"

    user_row = session.execute(
        text("SELECT raw_user_meta_data->>'full_name' AS name, email FROM auth.users WHERE id = :uid"),
        {"uid": user_id},
    ).fetchone()
    user_name = (user_row.name if user_row and user_row.name else
                 (user_row.email if user_row else "User"))

    conversation_id = message.conversation_id

    if not conversation_id:
        row = session.execute(
            text("""
                INSERT INTO support_conversations (business_id, user_id, status, priority)
                VALUES (:bid, :uid, 'ai_chat', 'normal')
                RETURNING id
            """),
            {"bid": business_id, "uid": user_id},
        ).fetchone()
        session.commit()
        conversation_id = str(row.id)
    else:
        convo = session.execute(
            text("SELECT id, status FROM support_conversations WHERE id = :cid AND business_id = :bid"),
            {"cid": conversation_id, "bid": business_id},
        ).fetchone()
        if not convo:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if convo.status in ("resolved", "closed"):
            session.execute(
                text("UPDATE support_conversations SET status = 'ai_chat', updated_at = :now WHERE id = :cid"),
                {"cid": conversation_id, "now": now},
            )
            session.commit()

    user_msg_row = session.execute(
        text("""
            INSERT INTO support_messages (conversation_id, sender_type, sender_id, sender_name, content)
            VALUES (:cid, 'user', :uid, :uname, :content)
            RETURNING id, conversation_id, sender_type, sender_name, content, is_internal, created_at
        """),
        {"cid": conversation_id, "uid": user_id, "uname": user_name, "content": message.content},
    ).fetchone()
    session.commit()
    user_msg = _row_to_dict(user_msg_row)

    current_status_row = session.execute(
        text("SELECT status FROM support_conversations WHERE id = :cid"),
        {"cid": conversation_id},
    ).fetchone()
    current_status = current_status_row.status if current_status_row else "ai_chat"

    if current_status in ("in_progress", "awaiting_reply"):
        session.execute(
            text("UPDATE support_conversations SET status = 'in_progress', last_message_at = :now, updated_at = :now WHERE id = :cid"),
            {"cid": conversation_id, "now": now},
        )
        session.commit()
        return {
            "conversation_id": conversation_id,
            "user_message": user_msg,
            "ai_response": None,
            "status": current_status,
            "escalated": True,
        }

    history_rows = session.execute(
        text("SELECT sender_type, content FROM support_messages WHERE conversation_id = :cid ORDER BY created_at"),
        {"cid": conversation_id},
    ).fetchall()
    history = _rows_to_list(history_rows)

    kb_articles = _fetch_kb_articles(session)

    ai_text, should_escalate, category, confidence = await _get_ai_support_response(
        user_message=message.content,
        conversation_history=history[:-1],
        business_name=business_name,
        kb_articles=kb_articles,
        user_name=user_name,
    )

    ai_msg_row = session.execute(
        text("""
            INSERT INTO support_messages (conversation_id, sender_type, sender_name, content)
            VALUES (:cid, 'ai', 'Business Hero Support', :content)
            RETURNING id, conversation_id, sender_type, sender_name, content, is_internal, created_at
        """),
        {"cid": conversation_id, "content": ai_text},
    ).fetchone()
    session.commit()
    ai_msg = _row_to_dict(ai_msg_row)

    if not message.conversation_id:
        subject = message.content[:100] + ("..." if len(message.content) > 100 else "")
        session.execute(
            text("UPDATE support_conversations SET subject = :subj, category = :cat WHERE id = :cid"),
            {"subj": subject, "cat": category, "cid": conversation_id},
        )
        session.commit()

    if should_escalate:
        session.execute(
            text("""
                UPDATE support_conversations
                SET status = 'escalated', escalated_at = :now, escalation_reason = :reason,
                    category = :cat, ai_confidence = :conf, last_message_at = :now, updated_at = :now
                WHERE id = :cid
            """),
            {
                "cid": conversation_id,
                "now": now,
                "reason": "AI escalated" if confidence < 0.5 else "User requested human support",
                "cat": category,
                "conf": confidence,
            },
        )
    else:
        ai_resolved = confidence >= 0.85
        session.execute(
            text("""
                UPDATE support_conversations
                SET category = :cat, ai_confidence = :conf, ai_resolved = :resolved,
                    last_message_at = :now, updated_at = :now
                WHERE id = :cid
            """),
            {"cat": category, "conf": confidence, "resolved": ai_resolved, "now": now, "cid": conversation_id},
        )
    session.commit()

    return {
        "conversation_id": conversation_id,
        "user_message": user_msg,
        "ai_response": ai_msg,
        "status": "escalated" if should_escalate else "ai_chat",
        "escalated": should_escalate,
    }


@router.post("/escalate")
async def escalate_conversation(
    body: EscalateRequest,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """User explicitly requests human support."""
    business_id = str(auth_ctx["business_id"])
    now = datetime.utcnow().isoformat()

    convo = session.execute(
        text("SELECT id, status FROM support_conversations WHERE id = :cid AND business_id = :bid"),
        {"cid": body.conversation_id, "bid": business_id},
    ).fetchone()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    session.execute(
        text("""
            UPDATE support_conversations
            SET status = 'escalated', escalated_at = :now, escalation_reason = 'User requested human support', updated_at = :now
            WHERE id = :cid
        """),
        {"cid": body.conversation_id, "now": now},
    )

    session.execute(
        text("""
            INSERT INTO support_messages (conversation_id, sender_type, sender_name, content)
            VALUES (:cid, 'ai', 'Business Hero Support',
                    'I''ve escalated this to our support team. They''ll get back to you as soon as possible. Your conversation history has been shared so you won''t need to repeat anything.')
        """),
        {"cid": body.conversation_id},
    )
    session.commit()

    return {"status": "escalated", "conversation_id": body.conversation_id}


@router.get("/conversations")
async def list_support_conversations(
    conv_status: Optional[str] = Query(default=None, alias="status"),
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """List user's support conversations."""
    business_id = str(auth_ctx["business_id"])
    if conv_status:
        rows = session.execute(
            text("SELECT * FROM support_conversations WHERE business_id = :bid AND status = :st ORDER BY updated_at DESC LIMIT 50"),
            {"bid": business_id, "st": conv_status},
        ).fetchall()
    else:
        rows = session.execute(
            text("SELECT * FROM support_conversations WHERE business_id = :bid ORDER BY updated_at DESC LIMIT 50"),
            {"bid": business_id},
        ).fetchall()
    return _rows_to_list(rows)


@router.get("/conversations/{conversation_id}")
async def get_support_conversation(
    conversation_id: str,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Get a conversation with all messages (excluding internal notes)."""
    business_id = str(auth_ctx["business_id"])
    convo = session.execute(
        text("SELECT * FROM support_conversations WHERE id = :cid AND business_id = :bid"),
        {"cid": conversation_id, "bid": business_id},
    ).fetchone()
    if not convo:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msgs = session.execute(
        text("SELECT * FROM support_messages WHERE conversation_id = :cid AND is_internal = FALSE ORDER BY created_at"),
        {"cid": conversation_id},
    ).fetchall()

    result = _row_to_dict(convo)
    result["messages"] = _rows_to_list(msgs)
    return result


@router.get("/articles")
async def list_support_articles(
    category: Optional[str] = None,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """List published support articles."""
    if category:
        rows = session.execute(
            text("SELECT id, title, summary, category, tags FROM support_articles WHERE is_published = TRUE AND category = :cat ORDER BY sort_order"),
            {"cat": category},
        ).fetchall()
    else:
        rows = session.execute(
            text("SELECT id, title, summary, category, tags FROM support_articles WHERE is_published = TRUE ORDER BY sort_order"),
        ).fetchall()
    return _rows_to_list(rows)


@router.get("/articles/{article_id}")
async def get_support_article(
    article_id: str,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Get full article content."""
    row = session.execute(
        text("SELECT * FROM support_articles WHERE id = :aid AND is_published = TRUE"),
        {"aid": article_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Article not found")
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------

@admin_router.get("/tickets")
async def admin_list_tickets(
    ticket_status: Optional[str] = Query(default=None, alias="status"),
    priority: Optional[str] = None,
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: list all support tickets."""
    base = """
        SELECT sc.*, b.name AS business_name
        FROM support_conversations sc
        LEFT JOIN businesses b ON b.id = sc.business_id
    """
    params: dict = {}
    clauses: list = []

    if ticket_status:
        clauses.append("sc.status = :st")
        params["st"] = ticket_status
    else:
        clauses.append("sc.status != 'closed'")

    if priority:
        clauses.append("sc.priority = :pr")
        params["pr"] = priority

    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    query = base + where + " ORDER BY sc.updated_at DESC LIMIT 100"

    rows = session.execute(text(query), params).fetchall()
    return _rows_to_list(rows)


@admin_router.get("/tickets/{conversation_id}")
async def admin_get_ticket(
    conversation_id: str,
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: get ticket with all messages including internal notes."""
    convo = session.execute(
        text("""
            SELECT sc.*, b.name AS business_name
            FROM support_conversations sc
            LEFT JOIN businesses b ON b.id = sc.business_id
            WHERE sc.id = :cid
        """),
        {"cid": conversation_id},
    ).fetchone()
    if not convo:
        raise HTTPException(status_code=404, detail="Ticket not found")

    msgs = session.execute(
        text("SELECT * FROM support_messages WHERE conversation_id = :cid ORDER BY created_at"),
        {"cid": conversation_id},
    ).fetchall()

    result = _row_to_dict(convo)
    result["messages"] = _rows_to_list(msgs)
    return result


@admin_router.post("/tickets/{conversation_id}/reply")
async def admin_reply_ticket(
    conversation_id: str,
    reply: AdminReplyCreate,
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: reply to a support ticket."""
    admin_id = str(auth_ctx["user_id"])
    now = datetime.utcnow().isoformat()

    msg_row = session.execute(
        text("""
            INSERT INTO support_messages (conversation_id, sender_type, sender_id, sender_name, content, is_internal)
            VALUES (:cid, 'admin', :aid, 'Business Hero Support', :content, :internal)
            RETURNING id, conversation_id, sender_type, sender_name, content, is_internal, created_at
        """),
        {"cid": conversation_id, "aid": admin_id, "content": reply.content, "internal": reply.is_internal},
    ).fetchone()

    if not reply.is_internal:
        session.execute(
            text("""
                UPDATE support_conversations
                SET status = 'awaiting_reply', last_message_at = :now, last_admin_reply_at = :now, updated_at = :now
                WHERE id = :cid
            """),
            {"cid": conversation_id, "now": now},
        )
    else:
        session.execute(
            text("UPDATE support_conversations SET updated_at = :now WHERE id = :cid"),
            {"cid": conversation_id, "now": now},
        )
    session.commit()

    return _row_to_dict(msg_row) if msg_row else {"status": "sent"}


@admin_router.put("/tickets/{conversation_id}/status")
async def admin_update_ticket_status(
    conversation_id: str,
    update: TicketStatusUpdate,
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: update ticket status and priority."""
    now = datetime.utcnow().isoformat()
    sets = ["status = :status", "updated_at = :now"]
    params: dict = {"cid": conversation_id, "status": update.status, "now": now}

    if update.priority:
        sets.append("priority = :priority")
        params["priority"] = update.priority
    if update.admin_notes:
        sets.append("admin_notes = :notes")
        params["notes"] = update.admin_notes
    if update.status == "resolved":
        sets.append("resolved_at = :now")
    elif update.status == "closed":
        sets.append("closed_at = :now")
    elif update.status == "in_progress":
        sets.append("assigned_to = :admin_id")
        params["admin_id"] = str(auth_ctx["user_id"])

    query = f"UPDATE support_conversations SET {', '.join(sets)} WHERE id = :cid"
    session.execute(text(query), params)
    session.commit()

    return {"status": update.status}


@admin_router.post("/tickets/{conversation_id}/ai-draft")
async def admin_ai_draft_response(
    conversation_id: str,
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: get an AI-drafted response suggestion."""
    msgs = session.execute(
        text("SELECT sender_type, content FROM support_messages WHERE conversation_id = :cid ORDER BY created_at"),
        {"cid": conversation_id},
    ).fetchall()
    history = _rows_to_list(msgs)
    if not history:
        return {"draft": "No conversation history to draft from."}

    convo = session.execute(
        text("""
            SELECT sc.category, sc.subject, b.name AS business_name
            FROM support_conversations sc
            LEFT JOIN businesses b ON b.id = sc.business_id
            WHERE sc.id = :cid
        """),
        {"cid": conversation_id},
    ).fetchone()
    business_name = convo.business_name if convo and convo.business_name else "the business"

    kb_articles = _fetch_kb_articles(session)
    kb_text = "\n---\n".join(f"### {a['title']}\n{a['content']}" for a in kb_articles)

    conversation_text = "\n".join(
        f"{'User' if m['sender_type'] == 'user' else 'Support'}: {m['content']}"
        for m in history
    )

    try:
        import openai
        client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY, timeout=30.0, max_retries=1)

        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": f"""You are drafting a support response for Business Hero's admin team.
The business is "{business_name}".
Write a helpful, professional reply in British English. Be concise and actionable.
Reference the knowledge base where relevant.

KNOWLEDGE BASE:
{kb_text}

CONVERSATION SO FAR:
{conversation_text}

Draft a response that the admin can review, edit, and send. Start the response directly — don't include "Dear" or "Hi" unless appropriate.""",
                },
                {"role": "user", "content": "Draft a response to this support conversation."},
            ],
            temperature=0.4,
            max_tokens=500,
        )

        draft = resp.choices[0].message.content.strip()
        return {"draft": draft}

    except Exception as exc:
        _logger.error("[Support AI] Draft error: %s", exc)
        return {"draft": "Unable to generate draft. Please write a manual response."}


@admin_router.get("/stats")
async def admin_support_stats(
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: get support statistics."""
    rows = session.execute(
        text("SELECT status, ai_resolved, created_at, resolved_at FROM support_conversations")
    ).fetchall()
    data = _rows_to_list(rows)
    today = datetime.utcnow().strftime("%Y-%m-%d")

    return {
        "open_tickets": sum(1 for c in data if c["status"] not in ("resolved", "closed")),
        "awaiting_admin": sum(1 for c in data if c["status"] == "escalated"),
        "in_progress": sum(1 for c in data if c["status"] == "in_progress"),
        "awaiting_reply": sum(1 for c in data if c["status"] == "awaiting_reply"),
        "resolved_total": sum(1 for c in data if c["status"] in ("resolved", "closed")),
        "ai_resolved_total": sum(1 for c in data if c.get("ai_resolved")),
        "created_today": sum(
            1 for c in data
            if c.get("created_at") and str(c["created_at"])[:10] == today
        ),
    }


# ---------------------------------------------------------------------------
# Admin knowledge base CRUD
# ---------------------------------------------------------------------------

@admin_router.get("/articles")
async def admin_list_articles(
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: list all articles (including unpublished)."""
    rows = session.execute(
        text("SELECT * FROM support_articles ORDER BY sort_order")
    ).fetchall()
    return _rows_to_list(rows)


@admin_router.post("/articles", status_code=201)
async def admin_create_article(
    article: SupportArticleCreate,
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: create a knowledge base article."""
    import json
    tags_json = json.dumps(article.tags or [])
    row = session.execute(
        text("""
            INSERT INTO support_articles (title, content, summary, category, tags, is_published)
            VALUES (:title, :content, :summary, :category, :tags::jsonb, :published)
            RETURNING *
        """),
        {
            "title": article.title,
            "content": article.content,
            "summary": article.summary,
            "category": article.category,
            "tags": tags_json,
            "published": article.is_published,
        },
    ).fetchone()
    session.commit()
    return _row_to_dict(row) if row else {"status": "created"}


@admin_router.put("/articles/{article_id}")
async def admin_update_article(
    article_id: str,
    article: SupportArticleUpdate,
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: update an article."""
    import json
    update_fields = article.model_dump(exclude_none=True)
    if not update_fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    sets = ["updated_at = :now"]
    params: dict = {"aid": article_id, "now": datetime.utcnow().isoformat()}

    for key, val in update_fields.items():
        if key == "tags":
            sets.append(f"{key} = :{key}::jsonb")
            params[key] = json.dumps(val)
        else:
            sets.append(f"{key} = :{key}")
            params[key] = val

    query = f"UPDATE support_articles SET {', '.join(sets)} WHERE id = :aid RETURNING *"
    row = session.execute(text(query), params).fetchone()
    session.commit()
    return _row_to_dict(row) if row else {"status": "updated"}


@admin_router.delete("/articles/{article_id}")
async def admin_delete_article(
    article_id: str,
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: delete an article."""
    session.execute(
        text("DELETE FROM support_articles WHERE id = :aid"),
        {"aid": article_id},
    )
    session.commit()
    return {"status": "deleted"}
