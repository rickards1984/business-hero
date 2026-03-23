"""AI Assistant chat endpoint handler."""

import os
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Optional, Tuple
from openai import OpenAI
from sqlalchemy import create_engine, text

from supabase_auth import verify_supabase_token, SupabaseUser
from assistant_tools import TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger(__name__)


async def _execute_tool_async(tool_name: str, arguments: dict, business_id: str, timezone: str = "Europe/London") -> dict:
    """Wrapper that handles async booking tools, delegating everything else to the sync execute_tool."""
    if tool_name == "check_calendar_availability":
        from assistant_tools import check_calendar_availability
        from db import get_session_context
        from sqlalchemy import text as sql_text
        import json as _json

        date_str = arguments.get("date")
        duration = arguments.get("duration_minutes", 60)
        calendar_id = arguments.get("calendar_id", "primary")
        start_hour, end_hour = 9, 17

        try:
            with get_session_context() as session:
                settings_row = session.execute(
                    sql_text("SELECT * FROM booking_settings WHERE business_id = :bid"),
                    {"bid": business_id},
                ).fetchone()

            if settings_row and settings_row.enabled:
                import datetime as _dt
                day_name = _dt.datetime.fromisoformat(date_str).strftime("%A").lower()
                business_hours = (
                    settings_row.business_hours
                    if isinstance(settings_row.business_hours, list)
                    else _json.loads(settings_row.business_hours or "[]")
                )
                day_config = next((d for d in business_hours if d.get("day") == day_name), None)
                if day_config and day_config.get("enabled"):
                    start_hour = int(day_config["start"].split(":")[0])
                    end_hour = int(day_config["end"].split(":")[0])
                if calendar_id == "primary" and getattr(settings_row, "calendar_id", None):
                    calendar_id = settings_row.calendar_id
        except Exception as e:
            logger.warning(f"Failed to load booking settings: {e}")

        return await check_calendar_availability(
            business_id=business_id,
            date=date_str,
            duration_minutes=duration,
            start_hour=start_hour,
            end_hour=end_hour,
            calendar_id=calendar_id,
        )

    elif tool_name == "create_calendar_event":
        from assistant_tools import create_calendar_event
        from db import get_session_context
        from sqlalchemy import text as sql_text

        calendar_id = arguments.get("calendar_id", "primary")
        try:
            with get_session_context() as session:
                settings_row = session.execute(
                    sql_text("SELECT calendar_id FROM booking_settings WHERE business_id = :bid"),
                    {"bid": business_id},
                ).fetchone()
            if settings_row and calendar_id == "primary" and getattr(settings_row, "calendar_id", None):
                calendar_id = settings_row.calendar_id
        except Exception:
            pass

        return await create_calendar_event(
            business_id=business_id,
            title=arguments.get("title", "Appointment"),
            start_time=arguments.get("start_time"),
            end_time=arguments.get("end_time"),
            description=arguments.get("description", ""),
            attendee_email=arguments.get("attendee_email"),
            attendee_name=arguments.get("attendee_name"),
            location=arguments.get("location"),
            timezone=timezone,
            calendar_id=calendar_id,
        )

    elif tool_name == "list_google_calendars":
        import httpx
        from assistant_tools import _get_google_calendar_token, _get_engine, _refresh_google_token

        engine = _get_engine()
        access_token, account_id, refresh_ciphertext = _get_google_calendar_token(engine, business_id)
        if not access_token:
            return {"error": "Google Calendar not connected"}

        async def _fetch(token: str):
            async with httpx.AsyncClient(timeout=30) as client:
                return await client.get(
                    "https://www.googleapis.com/calendar/v3/users/me/calendarList",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"minAccessRole": "writer"},
                )

        resp = await _fetch(access_token)
        if resp.status_code == 401 and refresh_ciphertext:
            try:
                access_token = _refresh_google_token(engine, account_id, refresh_ciphertext)
                resp = await _fetch(access_token)
            except Exception:
                return {"error": "Calendar token expired — please reconnect Google"}

        if resp.status_code != 200:
            return {"error": f"Failed to fetch calendars: {resp.status_code}"}

        return {
            "calendars": [
                {"id": c.get("id"), "name": c.get("summary", "Unnamed"), "primary": c.get("primary", False)}
                for c in resp.json().get("items", [])
            ]
        }

    elif tool_name == "generate_ai_quote":
        import httpx as _httpx

        description = arguments.get("description", "")
        if not description:
            return {"error": "Job description is required"}

        openai_key = os.getenv("OPENAI_API_KEY")
        system_prompt = """You are an expert quantity surveyor and pricing specialist for UK trades.
Given a job description, break it down into a detailed itemised quote with realistic UK pricing.
Respond with ONLY a JSON object with: job_title, groups (each with name and items array), estimated_duration, notes.
Each item needs: description, quantity, unit, unit_cost, category (labour/materials/equipment/subcontractor/other)."""

        try:
            async with _httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                    json={
                        "model": "gpt-4o",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": description},
                        ],
                        "temperature": 0.3,
                        "response_format": {"type": "json_object"},
                    },
                )

            if resp.status_code != 200:
                return {"error": "Failed to generate quote. Please try again."}

            ai_data = resp.json()
            content = ai_data["choices"][0]["message"]["content"]
            quote_data = json.loads(content)

            total = 0
            summary_lines = []
            for group in quote_data.get("groups", []):
                group_total = sum(
                    float(i.get("quantity", 1)) * float(i.get("unit_cost", 0))
                    for i in group.get("items", [])
                )
                total += group_total
                summary_lines.append(f"  {group['name']}: £{group_total:,.2f}")

            return {
                "job_title": quote_data.get("job_title", ""),
                "subtotal": round(total, 2),
                "vat_20_percent": round(total * 0.2, 2),
                "total_inc_vat": round(total * 1.2, 2),
                "groups_summary": "\n".join(summary_lines),
                "estimated_duration": quote_data.get("estimated_duration", ""),
                "notes": quote_data.get("notes", ""),
                "message": f"I've priced up the job at £{total:,.2f} + VAT (£{total*1.2:,.2f} inc VAT). Would you like me to save this as a quote?",
            }
        except Exception as e:
            return {"error": f"Quote generation failed: {str(e)}"}

    else:
        return execute_tool(tool_name, arguments, business_id, timezone)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_DATABASE_URL = os.getenv("SUPABASE_DATABASE_URL")

if SUPABASE_DATABASE_URL and SUPABASE_DATABASE_URL.startswith("postgres://"):
    SUPABASE_DATABASE_URL = SUPABASE_DATABASE_URL.replace("postgres://", "postgresql://", 1)


@dataclass
class BusinessContext:
    """Business context for the AI assistant."""
    id: str
    name: str
    timezone: str
    logo_url: Optional[str] = None


def build_system_prompt(business: BusinessContext, voice_mode: bool = False, user_name: Optional[str] = None, user_email: Optional[str] = None) -> str:
    """Build the system prompt with business context."""
    base_prompt = f"""You are a friendly, professional AI executive assistant for {business.name}. Think of yourself as a trusted colleague who happens to have instant access to emails, calendar, calls, and tasks.

## Personality & Communication Style

### Voice Conversation Guidelines:
- You are often speaking out loud via text-to-speech, so write responses that sound natural when spoken
- Keep responses concise and conversational - avoid bullet points or markdown formatting
- Don't state obvious context the user already knows (e.g., don't mention the timezone - they know where they are)
- Use natural time references: "this morning", "about an hour ago", "earlier today" instead of exact timestamps unless asked
- When you need to fetch data (emails, calendar, calls), briefly acknowledge it naturally like:
  - "Let me check your emails..." 
  - "One moment, I'll pull up your calendar..."
  - "Let me see what calls came in today..."
- After fetching, summarize naturally: "You've got 5 emails this morning. The important ones are..." rather than listing mechanically
- Use conversational transitions: "Also...", "Oh, and...", "One more thing..."
- Match the user's energy - if they're casual, be casual. If formal, be professional.
- Never say "Here is a summary" or "Here are your emails" - just tell them naturally
- Round numbers naturally: "about 20 emails" not "exactly 23 emails"
- Prioritize what matters: lead with important/urgent items

### Response Format:
- Short sentences that flow well when spoken
- Minimal bullet points or numbered lists
- No emojis
- Natural, conversational language

### Examples of Good Responses:
Bad: "You have received 3 emails today. Email 1: From John Smith at 09:42..."
Good: "You've got 3 emails this morning. John Smith sent one about the project deadline - looks like he needs a response by tomorrow."

Bad: "Here is a summary of your tasks. Task 1: Follow up call with client."  
Good: "You've got a few things on your plate today. The main one is following up with that client from yesterday's call."

Bad: "I will now retrieve your calendar events. Please wait."
Good: "Let me check your calendar... Okay, you've got a quiet morning but there's a team meeting at 2."

## Business Context
- Business Name: {business.name}
- Timezone: {business.timezone}
- When interpreting "today", "this week", or any relative dates, use the {business.timezone} timezone.

## Available Tools
- list_tasks: View open, completed, or all tasks
- create_task: Create new tasks with title, description, and optional due date
- list_calls: View recent phone call records
- get_today_briefing: Get a summary of today's tasks and recent activity
- delete_task: Soft delete a task when the user confirms it's a duplicate
- list_emails: View recent emails (use detailed=true for full content, false for quick scan)
- get_email_detail: Read a specific email in full by its ID
- send_email: Send an email on behalf of the user (requires to, subject, and body)
- list_calendar_events: View upcoming calendar events and appointments
- get_calendar_briefing: Get today's schedule, upcoming meetings, and tomorrow's events
- check_calendar_availability: Find free appointment slots on a specific date
- create_calendar_event: Book an appointment or add an event to Google Calendar
- list_google_calendars: Show which Google Calendars the user has
- get_accounting_summary: Get financial summary (income, expenses, profit/loss) for a period
- list_transactions: List and search accounting transactions
- analyze_spending: Analyze spending patterns by category
- generate_ai_quote: Generate a detailed itemised quote from a job description
- list_quotes: View recent quotes and estimates

When using tools, always briefly acknowledge to the user that you're checking before making the call. This prevents awkward silences during data fetching.

When creating tasks, confirm what was created conversationally.
Only delete tasks when the user explicitly asks or confirms a duplicate; prefer deleting the newer duplicate.

### Email Briefings
When checking emails:
1. For quick checks or counting emails, use list_emails with detailed=false (default)
2. For thorough briefings, important decisions, or when the user asks for detail, use detailed=true
3. When using detailed=true, briefly acknowledge it: "Let me read through your emails in detail..."
4. In detailed mode, you have access to the full email body - use this to provide accurate summaries
5. Prioritize important emails: invoices, payments, client requests, urgent matters
6. Don't miss emails just because the subject line is vague - in detailed mode, read the content
7. Use get_email_detail when the user asks about a specific email's content

Examples of when to use which mode:
- "Any emails today?" → Quick scan, detailed=false
- "Give me a thorough briefing of my emails" → detailed=true
- "Are there any important emails I need to act on?" → detailed=true
- "How many unread emails do I have?" → detailed=false
- "What did John say in his email?" → detailed=true with query, or get_email_detail for specific email

### Calendar
When asked about the user's schedule, appointments, or meetings:
1. Use get_calendar_briefing for a daily overview of today and tomorrow
2. Use list_calendar_events to look further ahead (specify days parameter)
3. Mention meeting times naturally (e.g., "You have a call with John at 2pm")
4. Highlight any conflicts or busy periods
5. Include meeting links (Zoom/Teams/Meet) if available
6. Mention attendees when relevant

### Booking Appointments
You can also help manage the calendar and book appointments:
- Use check_calendar_availability to find free slots on a specific date
- Use create_calendar_event to book appointments or add events
- Use list_google_calendars to show which calendars the user has

When booking an appointment:
1. Confirm the date, time, and title with the user
2. Check availability first if unsure about conflicts
3. If the user mentions a specific calendar (e.g., "Induction calendar"), use list_google_calendars to find the right calendar ID, then use that ID when creating the event
4. Create the event and confirm the details

### Sending Emails
When the user asks to send an email:
1. You MUST have the recipient's actual email address (with @ symbol), not just their name
2. If you only have a name, look up their email from list_emails or ask the user
3. WRONG: send_email(to="Robert Morris", ...) - this will FAIL
4. RIGHT: send_email(to="robert.morris@company.com", ...)
5. After sending, confirm briefly: "Done — email sent to [name] at [address]." Do NOT repeat the confirmation.
6. If the send fails, tell the user the error honestly.
7. When the user confirms "yes send it" or "go ahead", call send_email IMMEDIATELY with the to, subject, and body from the conversation. Do NOT call list_emails again.
8. NEVER say you're sending an email without actually calling the send_email tool. If you can't call it, say so.

### Critical Rules
- NEVER pretend to perform an action. If a tool call is needed, make the tool call. Never describe performing an action in text that requires a tool.
- Keep confirmations brief — one sentence is enough. Do not repeat yourself.
- After any action completes (sending email, creating task, etc.), give ONE brief confirmation and move on.
- If a tool fails, explain briefly and offer an alternative. Do NOT retry endlessly.

### Accounting & Finances
You have access to the business's accounting data. You can:
1. Get financial summaries (income, expenses, profit/loss) using get_accounting_summary
2. List and search transactions using list_transactions
3. Analyze spending patterns by category using analyze_spending
4. Help identify cost-saving opportunities based on spending analysis

When asked about finances, money, profit, or business performance:
- Use get_accounting_summary for overall financial health
- Use list_transactions to find specific payments or show recent activity
- Use analyze_spending to identify where money is going
- Present financial data clearly with pound amounts (£)
- Offer insights and suggestions based on the data

### Quoting
You can help generate and manage quotes/estimates for jobs:
1. Use generate_ai_quote when the user describes a job they need priced up
2. Use list_quotes to show recent quotes or check quote statuses
3. When generating a quote, present a clear cost breakdown with group totals, subtotal, and VAT
4. Offer to save the generated quote if the user is happy with it
5. Use UK pricing and trade terminology

## CRITICAL RULES - NEVER VIOLATE THESE:

1. **ONLY report information that tools actually return.** Never make up names, emails, or details.
   - If list_emails returns 5 emails, only mention those 5 emails with their actual senders
   - If a person's name isn't in the tool result, don't invent one
   - Use the exact names and subjects from the data

2. **For email addresses:** The send_email tool requires an actual email address like "name@example.com"
   - Look at the "from_email" field in list_emails results to get email addresses
   - Never pass a person's name as the "to" field - it must be an email address

3. **Report tool errors honestly.** If send_email returns an error, tell the user it failed. Never claim success.

4. **Be specific and accurate.** Only mention senders/subjects that actually appear in tool results."""

    # Add user context
    if user_name or user_email:
        base_prompt += "\n\n## User Information"
        if user_name:
            base_prompt += f"\nThe user's name is {user_name}."
        if user_email:
            base_prompt += f" Their email is {user_email}."
    
    # Email signature instructions
    base_prompt += """

### Email Signatures
When sending emails on behalf of the user:
- If you know the user's name, sign emails appropriately: "Best regards,\\n[User's Name]"
- Never leave placeholders like "[Your Name]" - use the actual name or ask for it
- Keep signatures professional and simple"""

    if voice_mode:
        base_prompt += """

IMPORTANT: The user is in voice conversation mode. Keep responses extra concise and conversational. No formatting, no lists, just natural speech that sounds good when spoken aloud. Short sentences. Get to the point quickly."""

    return base_prompt


_engine = None


def _get_engine():
    """Get cached SQLAlchemy engine for Supabase."""
    global _engine
    if _engine is None:
        if not SUPABASE_DATABASE_URL:
            raise RuntimeError("SUPABASE_DATABASE_URL not configured")
        _engine = create_engine(SUPABASE_DATABASE_URL, pool_pre_ping=True, pool_size=5)
    return _engine


def get_user_display_name(user_id: str) -> Optional[str]:
    """Get user's display name from profiles table or business_members."""
    engine = _get_engine()
    with engine.connect() as conn:
        # Try to get from profiles table if it exists
        try:
            result = conn.execute(text("""
                SELECT full_name, display_name 
                FROM profiles 
                WHERE id = :user_id
                LIMIT 1
            """), {"user_id": user_id})
            row = result.fetchone()
            if row and (row[0] or row[1]):
                return row[1] or row[0]  # Prefer display_name over full_name
        except Exception:
            pass  # Table might not exist
        
        # Try business_members for at least the role
        try:
            result = conn.execute(text("""
                SELECT role FROM business_members 
                WHERE user_id = :user_id
                ORDER BY created_at ASC
                LIMIT 1
            """), {"user_id": user_id})
            row = result.fetchone()
            if row and row[0]:
                # Capitalize role for display
                return row[0].title()
        except Exception:
            pass
    
    return None


def is_platform_admin(user_id: str) -> bool:
    """Check if user is a platform admin."""
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT 1 FROM platform_admins WHERE user_id = :user_id LIMIT 1
        """), {"user_id": user_id})
        return result.fetchone() is not None


def get_business_by_id(business_id: str) -> Optional[BusinessContext]:
    """Fetch business by ID."""
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, name, timezone, logo_url FROM businesses WHERE id = :business_id LIMIT 1
        """), {"business_id": business_id})
        row = result.fetchone()
        if row:
            return BusinessContext(id=str(row[0]), name=row[1], timezone=row[2], logo_url=row[3])
        return None


def get_business_for_user(user_id: str, requested_business_id: Optional[str] = None) -> BusinessContext:
    """Get business context for a user.
    
    Args:
        user_id: The authenticated user's UUID
        requested_business_id: Optional specific business ID if user has multiple
        
    Returns:
        BusinessContext with id, name, and timezone
        
    Raises:
        ValueError: If no business found, access denied, or business not found
    """
    engine = _get_engine()
    is_admin = is_platform_admin(user_id)
    
    if requested_business_id:
        if is_admin:
            business = get_business_by_id(requested_business_id)
            if not business:
                raise ValueError("NOT_FOUND", f"Business {requested_business_id} not found")
            logger.info(f"Platform admin {user_id} accessing business {business.name} ({business.id})")
            return business
        
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT b.id, b.name, b.timezone, b.logo_url
                FROM business_members bm
                JOIN businesses b ON b.id = bm.business_id
                WHERE bm.user_id = :user_id 
                  AND bm.business_id = :business_id 
                  AND bm.is_active = true
                LIMIT 1
            """), {"user_id": user_id, "business_id": requested_business_id})
            row = result.fetchone()
        
        if not row:
            raise ValueError("FORBIDDEN", f"Access denied to business {requested_business_id}")
        
        return BusinessContext(id=str(row[0]), name=row[1], timezone=row[2], logo_url=row[3])
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT bm.business_id, b.name, b.timezone, b.logo_url, bm.role, bm.created_at
            FROM business_members bm
            JOIN businesses b ON b.id = bm.business_id
            WHERE bm.user_id = :user_id AND bm.is_active = true
            ORDER BY bm.created_at ASC
        """), {"user_id": user_id})
        
        memberships = result.fetchall()
    
    if not memberships:
        raise ValueError("NO_BUSINESS", "No business assigned to this user")
    
    if len(memberships) == 1:
        m = memberships[0]
        return BusinessContext(id=str(m[0]), name=m[1], timezone=m[2], logo_url=m[3])
    
    for m in memberships:
        if m[4] == 'owner':  # role is now at index 4
            return BusinessContext(id=str(m[0]), name=m[1], timezone=m[2], logo_url=m[3])
    
    m = memberships[0]
    return BusinessContext(id=str(m[0]), name=m[1], timezone=m[2], logo_url=m[3])


@dataclass
class ConversationContext:
    """Conversation context for continuity."""
    id: str
    user_id: str
    business_id: str


def is_valid_uuid(value: str) -> bool:
    """Check if a string is a valid UUID."""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError):
        return False


def get_conversation(conversation_id: str) -> Optional[ConversationContext]:
    """Fetch conversation by ID."""
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, user_id, business_id 
            FROM assistant_conversations 
            WHERE id = :conversation_id 
            LIMIT 1
        """), {"conversation_id": conversation_id})
        row = result.fetchone()
        if row:
            return ConversationContext(id=str(row[0]), user_id=str(row[1]), business_id=str(row[2]))
        return None


def create_conversation(user_id: str, business_id: str) -> str:
    """Create a new conversation and return its ID."""
    engine = _get_engine()
    new_id = str(uuid.uuid4())
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO assistant_conversations (id, user_id, business_id, created_at, updated_at)
            VALUES (:id, :user_id, :business_id, NOW(), NOW())
        """), {"id": new_id, "user_id": user_id, "business_id": business_id})
        conn.commit()
    logger.info(f"[DEBUG] Created new conversation: conversation_id={new_id}, user_id={user_id}, business_id={business_id}")
    return new_id


def save_message(conversation_id: str, business_id: str, user_id: str, role: str, content: str) -> str:
    """Save a message to assistant_messages table."""
    engine = _get_engine()
    msg_id = str(uuid.uuid4())
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO assistant_messages (id, conversation_id, business_id, user_id, role, content, created_at)
            VALUES (:id, :conversation_id, :business_id, :user_id, :role, :content, NOW())
        """), {
            "id": msg_id,
            "conversation_id": conversation_id,
            "business_id": business_id,
            "user_id": user_id,
            "role": role,
            "content": content
        })
        conn.commit()
    return msg_id


def load_conversation_history(conversation_id: str, user_id: str, is_admin: bool, limit: int = 20) -> list:
    """Load recent messages for a conversation.
    
    Args:
        conversation_id: The conversation UUID
        user_id: The authenticated user's UUID
        is_admin: Whether user is a platform admin
        limit: Max messages to load (default 20)
        
    Returns:
        List of dicts with role and content, ordered oldest first
    """
    engine = _get_engine()
    with engine.connect() as conn:
        if is_admin:
            result = conn.execute(text("""
                SELECT role, content FROM assistant_messages
                WHERE conversation_id = :conversation_id
                ORDER BY created_at DESC
                LIMIT :limit
            """), {"conversation_id": conversation_id, "limit": limit})
        else:
            result = conn.execute(text("""
                SELECT role, content FROM assistant_messages
                WHERE conversation_id = :conversation_id AND user_id = :user_id
                ORDER BY created_at DESC
                LIMIT :limit
            """), {"conversation_id": conversation_id, "user_id": user_id, "limit": limit})
        
        rows = result.fetchall()
    
    messages = [{"role": row[0], "content": row[1]} for row in reversed(rows)]
    logger.info(f"[DEBUG] Loaded {len(messages)} messages for conversation {conversation_id}")
    return messages


def resolve_conversation(
    user_id: str, 
    conversation_id: Optional[str], 
    requested_business_id: Optional[str],
    is_admin: bool
) -> Tuple[str, str]:
    """Resolve conversation and business context.
    
    Args:
        user_id: Authenticated user's UUID
        conversation_id: Optional existing conversation ID
        requested_business_id: Optional business ID from request
        is_admin: Whether user is a platform admin
        
    Returns:
        Tuple of (conversation_id, business_id)
        
    Raises:
        ValueError: With (error_type, message) for various error conditions
    """
    if conversation_id:
        # Validate UUID format
        if not is_valid_uuid(conversation_id):
            raise ValueError("INVALID_UUID", "conversation_id must be a valid UUID")
        
        # Look up existing conversation
        conversation = get_conversation(conversation_id)
        if not conversation:
            raise ValueError("NOT_FOUND", f"Conversation {conversation_id} not found")
        
        # Verify ownership (unless platform admin)
        if conversation.user_id != user_id and not is_admin:
            raise ValueError("FORBIDDEN", "You do not have access to this conversation")
        
        # If business_id provided, verify it matches
        if requested_business_id and requested_business_id != conversation.business_id:
            raise ValueError("BUSINESS_MISMATCH", "conversation_id does not match business_id")
        
        logger.info(f"[DEBUG] Using existing conversation: conversation_id={conversation_id}, business_id={conversation.business_id}")
        return conversation_id, conversation.business_id
    
    # No conversation_id - will create new one after business resolution
    return None, requested_business_id


async def process_chat_message(
    user: SupabaseUser,
    message: str,
    conversation_id: Optional[str] = None,
    business_id: Optional[str] = None,
    voice_mode: bool = False
) -> dict:
    """Process a chat message and return the assistant response.
    
    Args:
        user: Authenticated Supabase user
        message: User's message
        conversation_id: Optional conversation ID for continuity
        business_id: Optional business ID if user has multiple businesses
        voice_mode: Whether the user is in voice conversation mode (more concise responses)
        
    Returns:
        dict with response and metadata including business object and conversation_id
    """
    logger.info(f"[DEBUG] process_chat_message called: user_id={user.id}, conversation_id={conversation_id}, requested_business_id={business_id}")
    
    is_admin = is_platform_admin(user.id)
    
    # Step 1: Resolve conversation if provided
    try:
        resolved_conv_id, conv_business_id = resolve_conversation(
            user.id, conversation_id, business_id, is_admin
        )
    except ValueError as e:
        error_type = e.args[0] if e.args else "UNKNOWN"
        error_msg = e.args[1] if len(e.args) > 1 else str(e)
        logger.error(f"[DEBUG] Conversation resolution failed: error_type={error_type}, error_msg={error_msg}")
        
        if error_type == "INVALID_UUID":
            return {"error": error_msg, "error_code": "INVALID_UUID", "status": 400}
        elif error_type == "NOT_FOUND":
            return {"error": error_msg, "error_code": "NOT_FOUND", "status": 404}
        elif error_type == "FORBIDDEN":
            return {"error": error_msg, "error_code": "FORBIDDEN", "status": 403}
        elif error_type == "BUSINESS_MISMATCH":
            return {"error": error_msg, "error_code": "BUSINESS_MISMATCH", "status": 400}
        else:
            return {"error": error_msg, "error_code": "CONVERSATION_ERROR", "status": 400}
    
    # Use business_id from conversation if available, otherwise from request
    effective_business_id = conv_business_id or business_id
    
    # Step 2: Resolve business context
    try:
        business = get_business_for_user(user.id, effective_business_id)
    except ValueError as e:
        error_type = e.args[0] if e.args else "UNKNOWN"
        error_msg = e.args[1] if len(e.args) > 1 else str(e)
        logger.error(f"[DEBUG] Business resolution failed: error_type={error_type}, error_msg={error_msg}")
        
        if error_type == "NO_BUSINESS":
            return {"error": error_msg, "error_code": "NO_BUSINESS", "status": 403}
        elif error_type == "FORBIDDEN":
            return {"error": error_msg, "error_code": "FORBIDDEN", "status": 403}
        elif error_type == "NOT_FOUND":
            return {"error": error_msg, "error_code": "NOT_FOUND", "status": 404}
        else:
            return {"error": error_msg, "error_code": "INVALID_BUSINESS", "status": 400}
    
    # Step 3: Create conversation if not provided
    if not resolved_conv_id:
        resolved_conv_id = create_conversation(user.id, business.id)
    
    logger.info(f"[DEBUG] Context resolved: user_id={user.id}, conversation_id={resolved_conv_id}, business_id={business.id}, business_name={business.name}, timezone={business.timezone}")
    
    if not OPENAI_API_KEY:
        return {"error": "OpenAI API key not configured", "status": 500}
    
    # Step 4: Load conversation history BEFORE saving new message
    history = load_conversation_history(resolved_conv_id, user.id, is_admin, limit=20)
    
    # Step 5: Save user message to DB
    save_message(resolved_conv_id, business.id, user.id, "user", message)
    logger.info(f"[DEBUG] Saved user message to conversation {resolved_conv_id}")
    
    # Step 6: Build messages array with system prompt + history + current message
    user_name = get_user_display_name(user.id)
    user_email = user.email if hasattr(user, 'email') else None
    system_prompt = build_system_prompt(business, voice_mode=voice_mode, user_name=user_name, user_email=user_email)
    logger.info(f"[DEBUG] System prompt built for {business.name} (voice_mode={voice_mode}, user_name={user_name}). History has {len(history)} messages.")
    
    client = OpenAI(api_key=OPENAI_API_KEY)
    
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})
    
    MAX_TOOL_ROUNDS = 5
    assistant_reply = None
    tool_round = 0

    while tool_round < MAX_TOOL_ROUNDS:
        try:
            response = client.chat.completions.create(
                model="gpt-5",
                messages=messages,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                timeout=120
            )
        except Exception as e:
            logger.error(f"OpenAI API error on round {tool_round}: {e}")
            return {"error": f"AI service error: {str(e)}", "status": 500}

        assistant_message = response.choices[0].message

        if not assistant_message.tool_calls:
            assistant_reply = assistant_message.content or ""
            break

        assistant_msg_dict = {
            "role": "assistant",
            "content": assistant_message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                }
                for tc in assistant_message.tool_calls
            ]
        }
        messages.append(assistant_msg_dict)

        for tool_call in assistant_message.tool_calls:
            tool_name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}

            logger.info(f"Executing tool (round {tool_round}): {tool_name} with args: {arguments}")

            try:
                tool_result = await _execute_tool_async(tool_name, arguments, business.id, business.timezone)
            except Exception as e:
                logger.error(f"Tool execution error: {e}")
                tool_result = {"success": False, "error": str(e)}

            result_str = json.dumps(tool_result)
            logger.info(f"Tool {tool_name} result: {result_str[:500]}{'...' if len(result_str) > 500 else ''}")

            if "error" in tool_result:
                tool_content = f"ERROR: {tool_result['error']}"
            else:
                tool_content = json.dumps(tool_result)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": tool_content
            })

        tool_round += 1

    if assistant_reply is None:
        try:
            final_response = client.chat.completions.create(
                model="gpt-5",
                messages=messages,
                timeout=120
            )
            assistant_reply = final_response.choices[0].message.content or "I've completed the requested actions."
        except Exception as e:
            logger.error(f"OpenAI API error on final response: {e}")
            assistant_reply = "I encountered an error generating a response. Please try again."
    
    # Step 7: Save assistant reply to DB
    save_message(resolved_conv_id, business.id, user.id, "assistant", assistant_reply or "")
    logger.info(f"[DEBUG] Saved assistant reply to conversation {resolved_conv_id}")
    
    return {
        "reply": assistant_reply,
        "business_id": business.id,
        "business": {
            "id": business.id,
            "name": business.name,
            "timezone": business.timezone
        },
        "conversation_id": resolved_conv_id
    }
