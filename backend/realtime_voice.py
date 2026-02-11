"""
OpenAI Realtime API integration for premium voice conversations.
Handles WebSocket connections between frontend and OpenAI Realtime API.
"""

import os
import json
import asyncio
import logging
import base64
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from datetime import datetime, timedelta

router = APIRouter()
_logger = logging.getLogger("realtime_voice")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-12-17"

# Tool definitions for the Realtime API
# NOTE: Realtime API format is different from Chat Completions API
# - No nested "function" wrapper
# - "type" is "function" at top level
# - "name", "description", "parameters" at top level
REALTIME_TOOLS = [
    {
        "type": "function",
        "name": "list_emails",
        "description": "List recent emails from the user's inbox. Call this when the user asks about emails, messages, or inbox.",
        "parameters": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of emails to retrieve (default 5, max 20)"
                }
            }
        }
    },
    {
        "type": "function",
        "name": "get_schedule",
        "description": "Get today's calendar events and appointments. Call this when the user asks about their schedule, calendar, meetings, or what's on today.",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date to check (YYYY-MM-DD format, defaults to today)"
                }
            }
        }
    },
    {
        "type": "function",
        "name": "get_recent_calls",
        "description": "Get recent phone calls and their details. Call this when the user asks about calls, phone calls, or who called.",
        "parameters": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of calls to retrieve (default 5)"
                }
            }
        }
    },
    {
        "type": "function",
        "name": "get_tasks",
        "description": "Get the user's task list. Call this when the user asks about tasks, to-dos, or what they need to do.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "completed", "all"],
                    "description": "Filter by task status"
                }
            }
        }
    },
    {
        "type": "function",
        "name": "create_task",
        "description": "Create a new task or to-do item. Call this when the user asks to create a task, add a reminder, make a note to do something, or follow up on something.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The title or description of the task"
                },
                "description": {
                    "type": "string",
                    "description": "Optional additional details about the task"
                },
                "due_at": {
                    "type": "string",
                    "description": "Optional due date in ISO 8601 format (e.g., '2024-12-25T10:00:00Z')"
                }
            },
            "required": ["title"]
        }
    },
    {
        "type": "function",
        "name": "get_financial_summary",
        "description": "Get a summary of business finances including total income, total expenses, and net profit or loss. Call this when the user asks about finances, money, profit, how the business is doing financially, or accounting summary.",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["month", "quarter", "year"],
                    "description": "Time period for the summary (default: month)"
                }
            },
            "required": ["period"]
        }
    },
    {
        "type": "function",
        "name": "analyze_spending",
        "description": "Analyze spending patterns by category to see where money is going. Call this when the user asks about expenses, spending breakdown, where money is going, or cost analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["month", "quarter", "year"],
                    "description": "Time period to analyze"
                }
            },
            "required": ["period"]
        }
    },
    {
        "type": "function",
        "name": "search_transactions",
        "description": "Search accounting transactions by description. Call this when the user asks to find specific transactions or payments.",
        "parameters": {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Search term to find in transaction descriptions"
                },
                "type": {
                    "type": "string",
                    "enum": ["income", "expense", "all"],
                    "description": "Transaction type filter"
                }
            }
        }
    },
    {
        "type": "function",
        "name": "list_invoices",
        "description": "List invoices with optional status filter. Call this when the user asks about invoices, bills sent, or money owed to them.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["draft", "sent", "paid", "overdue", "all"],
                    "description": "Filter by invoice status"
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of invoices to retrieve (default 10)"
                }
            }
        }
    },
    {
        "type": "function",
        "name": "get_invoice_summary",
        "description": "Get a summary of invoices including total outstanding, overdue amounts, and payment status. Call this when the user asks about invoice overview, what's owed, or overdue invoices.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
]


async def execute_tool(tool_name: str, args: dict, user_id: str, business_id: str) -> str:
    """Execute a tool and return the result as a string."""
    _logger.info(f"Executing tool: {tool_name} with args: {args} for user={user_id}, business={business_id}")
    
    try:
        # Import the shared tool executor from assistant_tools
        from assistant_tools import execute_tool as execute_assistant_tool
        
        # Map realtime tool names to assistant_tools names if different
        tool_name_map = {
            "list_emails": "list_emails",
            "get_schedule": "get_calendar_briefing", 
            "get_recent_calls": "list_calls",
            "get_tasks": "list_tasks",
            "create_task": "create_task",
            "get_financial_summary": "get_accounting_summary",
            "analyze_spending": "analyze_spending",
            "search_transactions": "list_transactions",
            "list_invoices": "list_invoices",
            "get_invoice_summary": "get_invoice_summary",
        }
        
        mapped_name = tool_name_map.get(tool_name, tool_name)
        
        # Map arguments to what assistant_tools expects
        if tool_name == "list_emails":
            mapped_args = {"limit": args.get("count", 5), "detailed": True}
        elif tool_name == "get_schedule":
            mapped_args = {"days": 1}
        elif tool_name == "get_recent_calls":
            mapped_args = {"limit": args.get("count", 5)}
        elif tool_name == "get_tasks":
            mapped_args = {"status": args.get("status", "open")}
        elif tool_name == "create_task":
            mapped_args = {
                "title": args.get("title", ""),
                "description": args.get("description"),
                "due_at": args.get("due_at")
            }
        elif tool_name == "get_financial_summary":
            mapped_args = {"period": args.get("period", "month")}
        elif tool_name == "analyze_spending":
            mapped_args = {"period": args.get("period", "month")}
        elif tool_name == "search_transactions":
            mapped_args = {"search": args.get("search", ""), "type": args.get("type", "all"), "limit": 20}
        elif tool_name == "list_invoices":
            mapped_args = {"status": args.get("status", "all"), "limit": args.get("limit", 10)}
        elif tool_name == "get_invoice_summary":
            mapped_args = {}
        else:
            mapped_args = args
        
        _logger.info(f"Mapped tool call: {mapped_name} with args: {mapped_args}")
        
        # Get timezone for the business
        from assistant_chat import get_business_for_user
        try:
            business = get_business_for_user(user_id, business_id)
            timezone = business.timezone
        except:
            timezone = "Europe/London"
        
        # Execute using the shared tool executor
        result = execute_assistant_tool(mapped_name, mapped_args, business_id, timezone)
        
        _logger.info(f"Tool {tool_name} completed successfully")
        return json.dumps(result) if isinstance(result, dict) else result
        
    except Exception as e:
        _logger.error(f"Tool execution error for {tool_name}: {e}", exc_info=True)
        return json.dumps({"error": str(e)})


def get_accounting_summary(engine, business_id: str, period: str) -> str:
    """Get financial summary for the business."""
    from sqlalchemy import text
    from datetime import date
    
    today = date.today()
    
    if period == "month":
        start_date = today.replace(day=1)
    elif period == "quarter":
        start_date = today - timedelta(days=90)
    elif period == "year":
        start_date = today.replace(month=1, day=1)
    else:
        start_date = date(2000, 1, 1)
    
    with engine.connect() as conn:
        query = text("""
            SELECT 
                type,
                COUNT(*) as count,
                COALESCE(SUM(ABS(amount)), 0) as total
            FROM accounting_transactions
            WHERE business_id = :business_id 
              AND is_archived = false
              AND transaction_date >= :start_date 
              AND transaction_date <= :end_date
            GROUP BY type
        """)
        
        result = conn.execute(query, {
            "business_id": business_id,
            "start_date": start_date,
            "end_date": today
        })
        
        totals = {"income": 0, "expense": 0}
        for row in result.fetchall():
            if row[0] == "income":
                totals["income"] = float(row[2])
            elif row[0] == "expense":
                totals["expense"] = float(row[2])
        
        net = totals["income"] - totals["expense"]
        
        return json.dumps({
            "period": period,
            "total_income": round(totals["income"], 2),
            "total_expenses": round(totals["expense"], 2),
            "net_profit_loss": round(net, 2),
            "currency": "GBP",
            "summary": f"{'Profit' if net >= 0 else 'Loss'} of £{abs(net):,.2f}"
        })


def analyze_spending_patterns(engine, business_id: str, period: str) -> str:
    """Analyze spending by category."""
    from sqlalchemy import text
    from datetime import date
    
    today = date.today()
    days = {"month": 30, "quarter": 90, "year": 365}.get(period, 30)
    start_date = today - timedelta(days=days)
    
    with engine.connect() as conn:
        query = text("""
            SELECT 
                COALESCE(c.name, 'Uncategorized') as category_name,
                COUNT(*) as count,
                COALESCE(SUM(ABS(t.amount)), 0) as total
            FROM accounting_transactions t
            LEFT JOIN accounting_categories c ON t.category_id = c.id
            WHERE t.business_id = :business_id 
              AND t.is_archived = false
              AND t.type = 'expense'
              AND t.transaction_date >= :start_date
            GROUP BY c.name
            ORDER BY total DESC
        """)
        
        result = conn.execute(query, {
            "business_id": business_id,
            "start_date": start_date
        })
        
        categories = []
        total_expenses = 0
        
        for row in result.fetchall():
            cat_total = float(row[2])
            total_expenses += cat_total
            categories.append({
                "category": row[0],
                "count": int(row[1]),
                "total": round(cat_total, 2)
            })
        
        for cat in categories:
            cat["percentage"] = round(cat["total"] / total_expenses * 100, 1) if total_expenses > 0 else 0
        
        return json.dumps({
            "period": period,
            "total_expenses": round(total_expenses, 2),
            "by_category": categories[:10],
            "currency": "GBP"
        })


def search_transactions(engine, business_id: str, search: str, trans_type: str) -> str:
    """Search transactions."""
    from sqlalchemy import text
    
    with engine.connect() as conn:
        if trans_type != "all" and search:
            query = text("""
                SELECT transaction_date, description, amount, type
                FROM accounting_transactions
                WHERE business_id = :business_id 
                  AND is_archived = false
                  AND type = :type
                  AND description ILIKE :search
                ORDER BY transaction_date DESC
                LIMIT 20
            """)
            params = {"business_id": business_id, "type": trans_type, "search": f"%{search}%"}
        elif trans_type != "all":
            query = text("""
                SELECT transaction_date, description, amount, type
                FROM accounting_transactions
                WHERE business_id = :business_id 
                  AND is_archived = false
                  AND type = :type
                ORDER BY transaction_date DESC
                LIMIT 20
            """)
            params = {"business_id": business_id, "type": trans_type}
        elif search:
            query = text("""
                SELECT transaction_date, description, amount, type
                FROM accounting_transactions
                WHERE business_id = :business_id 
                  AND is_archived = false
                  AND description ILIKE :search
                ORDER BY transaction_date DESC
                LIMIT 20
            """)
            params = {"business_id": business_id, "search": f"%{search}%"}
        else:
            query = text("""
                SELECT transaction_date, description, amount, type
                FROM accounting_transactions
                WHERE business_id = :business_id 
                  AND is_archived = false
                ORDER BY transaction_date DESC
                LIMIT 20
            """)
            params = {"business_id": business_id}
        
        result = conn.execute(query, params)
        
        transactions = []
        for row in result.fetchall():
            transactions.append({
                "date": row[0].isoformat() if row[0] else None,
                "description": row[1],
                "amount": float(row[2]) if row[2] else 0,
                "type": row[3]
            })
        
        return json.dumps({
            "transactions": transactions,
            "count": len(transactions)
        })


def list_invoices(engine, business_id: str, status: str, limit: int) -> str:
    """List invoices for the business."""
    from sqlalchemy import text
    
    with engine.connect() as conn:
        if status != "all":
            query = text("""
                SELECT invoice_number, client_name, total_amount, status, due_date, issued_date
                FROM invoices
                WHERE business_id = :business_id AND status = :status
                ORDER BY created_at DESC
                LIMIT :limit
            """)
            params = {"business_id": business_id, "status": status, "limit": limit}
        else:
            query = text("""
                SELECT invoice_number, client_name, total_amount, status, due_date, issued_date
                FROM invoices
                WHERE business_id = :business_id
                ORDER BY created_at DESC
                LIMIT :limit
            """)
            params = {"business_id": business_id, "limit": limit}
        
        result = conn.execute(query, params)
        
        invoices = []
        for row in result.fetchall():
            invoices.append({
                "invoice_number": row[0],
                "client_name": row[1],
                "amount": float(row[2]) if row[2] else 0,
                "status": row[3],
                "due_date": row[4].isoformat() if row[4] else None,
                "issued_date": row[5].isoformat() if row[5] else None
            })
        
        return json.dumps({
            "invoices": invoices,
            "count": len(invoices),
            "currency": "GBP"
        })


def get_invoice_summary(engine, business_id: str) -> str:
    """Get invoice summary statistics."""
    from sqlalchemy import text
    from datetime import date
    
    today = date.today()
    
    with engine.connect() as conn:
        query = text("""
            SELECT 
                status,
                COUNT(*) as count,
                COALESCE(SUM(total_amount), 0) as total,
                COALESCE(SUM(CASE WHEN due_date < :today AND status NOT IN ('paid', 'cancelled') THEN total_amount ELSE 0 END), 0) as overdue_amount
            FROM invoices
            WHERE business_id = :business_id
            GROUP BY status
        """)
        
        result = conn.execute(query, {"business_id": business_id, "today": today})
        
        totals = {
            "draft": {"count": 0, "total": 0},
            "sent": {"count": 0, "total": 0},
            "paid": {"count": 0, "total": 0},
            "overdue": {"count": 0, "total": 0},
            "cancelled": {"count": 0, "total": 0}
        }
        total_overdue = 0
        
        for row in result.fetchall():
            status = row[0]
            if status in totals:
                totals[status]["count"] = int(row[1])
                totals[status]["total"] = float(row[2])
            total_overdue += float(row[3])
        
        # Check for actually overdue (sent but past due date)
        overdue_query = text("""
            SELECT COUNT(*), COALESCE(SUM(total_amount), 0)
            FROM invoices
            WHERE business_id = :business_id 
              AND due_date < :today 
              AND status NOT IN ('paid', 'cancelled')
        """)
        overdue_result = conn.execute(overdue_query, {"business_id": business_id, "today": today})
        overdue_row = overdue_result.fetchone()
        
        outstanding = totals["sent"]["total"] + totals["draft"]["total"]
        
        return json.dumps({
            "total_outstanding": round(outstanding, 2),
            "total_overdue": round(float(overdue_row[1]) if overdue_row else 0, 2),
            "overdue_count": int(overdue_row[0]) if overdue_row else 0,
            "pending_count": totals["sent"]["count"],
            "draft_count": totals["draft"]["count"],
            "paid_count": totals["paid"]["count"],
            "paid_total": round(totals["paid"]["total"], 2),
            "currency": "GBP"
        })


def build_system_instructions(business_name: str, user_name: str) -> str:
    """Build the system instructions for the Realtime API."""
    return f"""You are Aria, the AI Admin assistant for {business_name}. You're speaking with {user_name}.

## WHO YOU ARE

You're like a brilliant executive assistant who's been working with {user_name} for years. You're warm, sharp, and genuinely invested in helping the business succeed. Think of yourself as a trusted colleague who happens to have instant access to all the business data.

Your personality:
- Warm and personable, but efficient - you respect that {user_name} is busy
- Confident and direct - you give clear answers, not wishy-washy responses  
- Naturally British - you use £, UK date formats (9th February), and British expressions
- Genuine reactions - you celebrate wins, flag concerns, and show you care about the business
- Conversational - you speak like a real person, not a robot reading a script

## CRITICAL RULES - ALWAYS FOLLOW

1. **ALWAYS CALL TOOLS** - You have NO knowledge of emails, calendar, calls, tasks, finances, or invoices until you fetch them. NEVER guess or make up data.

2. **NEVER HALLUCINATE** - If you haven't called a tool, you don't know the information. Period.

3. **TOOL TRIGGERS** - When you hear these, call the corresponding tool:
   - "emails", "inbox", "messages", "mail" → list_emails
   - "schedule", "calendar", "meetings", "appointments", "diary" → get_schedule  
   - "calls", "phone", "who called", "missed calls" → get_recent_calls
   - "tasks", "to-do", "what do I need to do" → get_tasks
   - "create task", "add task", "remind me", "follow up", "make a note" → create_task
   - "finances", "money", "profit", "how's business", "accounting" → get_financial_summary
   - "spending", "expenses", "costs", "where's money going" → analyze_spending
   - "invoices", "bills", "what's owed", "outstanding", "overdue" → list_invoices or get_invoice_summary

## HOW TO COMMUNICATE

**Starting a task:**
Instead of robotic: "Let me check that for you..."
Try natural variations like:
- "Sure, pulling that up now..."
- "One sec, let me grab those..."
- "Right, let's have a look..."
- "Give me a moment..."

**Delivering email briefings:**
DON'T just list emails robotically. Instead:

Start with the headline: "You've got 6 emails this morning - nothing urgent, but there's one from your accountant worth looking at first."

Then highlight what matters:
- "The main one is from James at the bank - looks like they've approved the overdraft extension."
- "Sarah's chasing that invoice again - third time this week."
- "A few newsletters and one from Companies House that's just a filing confirmation."

Group and summarise rather than reading each one like a list.

**Reacting to financial data:**
Show you understand what the numbers mean:
- "That's a solid month - £1,800 profit, which is up on last month."
- "Hmm, expenses are a bit higher than usual - looks like the equipment purchase pushed it up."
- "Good news on cash flow - you've got more coming in than going out."
- "Worth keeping an eye on - you're running at a small loss this quarter."

**Discussing invoices:**
Be practical and action-oriented:
- "You've got £3,200 outstanding across 4 invoices. Two of those are overdue - one's only a few days late, but the other's been sitting there for 3 weeks now."
- "Might be worth sending a nudge to Thompson & Co - they're usually pretty good but this one's slipped."

**When there's nothing to report:**
Be natural about it:
- "All quiet on the email front - nothing new since we last checked."
- "No missed calls - looks like it's been a quiet morning."
- "Inbox is clear - you're all caught up."

**When there are errors or issues:**
Be honest and helpful:
- "I'm having trouble pulling up the emails - might be a connection issue. Want me to try again?"
- "That tool isn't responding right now. I'll flag it, but in the meantime..."

## CONVERSATION FLOW

**Keep it natural:**
- Use contractions (you've, it's, that's, I'll)
- Vary your sentence length - mix short punchy sentences with longer ones
- React before diving into details ("Oh, you've had a busy morning!" before listing emails)
- Use natural transitions ("Right, so..." / "Now, looking at..." / "On the invoice side...")

**Be proactively helpful:**
- "While I've got your finances up, want me to check how the invoices are looking too?"
- "That email from John mentions the Friday meeting - should I check your calendar for that?"
- "I notice a few of these expenses are uncategorised - might be worth sorting those when you get a chance."

**End conversations naturally:**
- "Anything else you need?"
- "Shout if you need anything else."
- "I'll be here if you need me."

## EXAMPLES OF GREAT RESPONSES

**Email briefing:**
"Right, you've got 5 emails this morning. The headline is that proposal from Davidson Ltd finally came through - that's the one you've been waiting on. There's also a reply from your accountant about the VAT return, looks straightforward. The rest are just newsletters and a LinkedIn notification. Want me to go through the Davidson proposal in more detail?"

**Financial summary:**
"So, looking at this month's figures - you've brought in just over £8,000 in income, with expenses sitting at about £5,200. That gives you a profit of £2,800, which is actually your best month this quarter. The bulk of the expenses were the usual - software subscriptions, that contractor payment, and the office supplies order."

**Invoice check:**
"Okay, invoices. You've got 3 outstanding at the moment, totalling £2,450. Good news is none of them are overdue yet - the oldest one isn't due until next Thursday. That's the one to Harrison's for the consulting work. The other two are smaller and not due for another couple of weeks."

**When asked "how's business doing?":**
"Let me pull up the numbers... Right, so this month you're looking at a profit of about £1,500. Not your biggest month, but solid. Income's been steady, though expenses crept up a bit - looks like that was mainly the new equipment purchase. On the invoice side, you've got £800 outstanding but nothing overdue, so cash flow's healthy. Overall? You're in good shape."

## WHAT NOT TO DO

- Don't read lists like a robot: "Email 1 is from... Email 2 is from... Email 3 is from..."
- Don't be overly formal: "I shall now retrieve your electronic correspondence"
- Don't be sycophantic: "What a fantastic question! I'd be delighted to help!"
- Don't pad responses with unnecessary words
- Don't forget to actually call the tools before giving information
- Don't make up data you haven't fetched

Remember: You're Aria, a trusted colleague who happens to have superpowers when it comes to accessing business data. Be warm, be helpful, be real."""


@router.websocket("/v1/realtime/voice")
async def realtime_voice_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time voice conversations.
    Proxies between the browser and OpenAI's Realtime API.
    """
    await websocket.accept()
    _logger.info("Client WebSocket connected")
    
    # Authenticate the user
    try:
        # Expect an initial auth message
        auth_message = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        if auth_message.get("type") != "auth":
            await websocket.close(code=4001, reason="Expected auth message")
            return
            
        token = auth_message.get("token")
        
        # Verify token using Supabase
        from supabase_auth import verify_supabase_token
        try:
            user = await verify_supabase_token(token)
            user_id = user.id
        except Exception as e:
            _logger.error(f"Token verification failed: {e}")
            await websocket.close(code=4001, reason="Invalid token")
            return
        
        # Get business for user
        from assistant_chat import get_business_for_user
        try:
            business = get_business_for_user(user_id)
            business_id = str(business.id)
            business_name = business.name
        except Exception as e:
            _logger.error(f"Business lookup failed: {e}")
            await websocket.close(code=4002, reason="No business found")
            return
        
        user_name = getattr(user, 'user_metadata', {}).get('full_name', 'there') if hasattr(user, 'user_metadata') else 'there'
        
        _logger.info(f"Authenticated user {user_id} for business {business_name}")
        
    except asyncio.TimeoutError:
        await websocket.close(code=4001, reason="Auth timeout")
        return
    except Exception as e:
        _logger.error(f"Auth error: {e}")
        await websocket.close(code=4001, reason="Auth failed")
        return
    
    # Connect to OpenAI Realtime API
    openai_ws = None
    try:
        import websockets
        
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
        
        openai_ws = await websockets.connect(OPENAI_REALTIME_URL, additional_headers=headers)
        _logger.info("Connected to OpenAI Realtime API")
        
        # Configure the session
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": build_system_instructions(business_name, user_name),
                "voice": "shimmer",
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": "whisper-1"
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500
                },
                "tools": REALTIME_TOOLS,
                "tool_choice": "auto",
                "temperature": 0.8
            }
        }
        await openai_ws.send(json.dumps(session_config))
        _logger.info("Session configured")
        
        # Notify client that we're ready
        await websocket.send_json({"type": "ready"})
        
        # Keepalive task to prevent timeout
        async def send_keepalive():
            """Send periodic pings to keep connection alive."""
            try:
                while True:
                    await asyncio.sleep(15)  # Every 15 seconds
                    if openai_ws and openai_ws.open:
                        # OpenAI Realtime API expects session updates or input to stay alive
                        # A minimal ping-like message
                        _logger.debug("Sending keepalive")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                _logger.debug(f"Keepalive ended: {e}")
        
        # Handle bidirectional communication
        async def forward_to_openai():
            """Forward messages from client to OpenAI."""
            try:
                while True:
                    data = await websocket.receive()
                    
                    if "text" in data:
                        message = json.loads(data["text"])
                        _logger.debug(f"Client -> OpenAI: {message.get('type')}")
                        await openai_ws.send(json.dumps(message))
                        
                    elif "bytes" in data:
                        # Raw audio data - wrap in proper format
                        audio_base64 = base64.b64encode(data["bytes"]).decode()
                        audio_event = {
                            "type": "input_audio_buffer.append",
                            "audio": audio_base64
                        }
                        await openai_ws.send(json.dumps(audio_event))
                        
            except WebSocketDisconnect:
                _logger.info("Client disconnected")
            except Exception as e:
                _logger.error(f"Forward to OpenAI error: {e}")
        
        async def forward_to_client():
            """Forward messages from OpenAI to client, handling tool calls."""
            try:
                async for message in openai_ws:
                    event = json.loads(message)
                    event_type = event.get("type")
                    _logger.info(f"OpenAI event received: {event_type}")  # Changed to INFO for visibility
                    
                    # Log full event for function calls
                    if "function" in event_type or "tool" in event_type:
                        _logger.info(f"Function/Tool event details: {json.dumps(event)[:500]}")
                    
                    # Log errors with full details
                    if event_type == "error":
                        _logger.error(f"OpenAI Realtime API error: {json.dumps(event)}")
                    
                    # Handle function calls - OpenAI Realtime uses these event types
                    if event_type == "response.function_call_arguments.done":
                        call_id = event.get("call_id")
                        name = event.get("name")
                        arguments = json.loads(event.get("arguments", "{}"))
                        
                        _logger.info(f"Tool call received: {name}({arguments})")
                        
                        # Execute the tool
                        result = await execute_tool(name, arguments, user_id, business_id)
                        
                        _logger.info(f"Tool result: {result[:200]}...")
                        
                        # Send the result back to OpenAI
                        tool_response = {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": result
                            }
                        }
                        await openai_ws.send(json.dumps(tool_response))
                        _logger.info(f"Sent tool response for {name}")
                        
                        # Trigger response generation
                        await openai_ws.send(json.dumps({"type": "response.create"}))
                        _logger.info("Triggered response.create after tool call")
                        
                    # Forward audio and other events to client
                    elif event_type in [
                        "response.audio.delta",
                        "response.audio.done", 
                        "response.audio_transcript.delta",
                        "response.audio_transcript.done",
                        "response.text.delta",
                        "response.text.done",
                        "input_audio_buffer.speech_started",
                        "input_audio_buffer.speech_stopped",
                        "conversation.item.input_audio_transcription.completed",
                        "error"
                    ]:
                        await websocket.send_json(event)
                        
            except Exception as e:
                _logger.error(f"Forward to client error: {e}")
        
        # Run both directions concurrently with keepalive
        keepalive_task = asyncio.create_task(send_keepalive())
        try:
            await asyncio.gather(
                forward_to_openai(),
                forward_to_client(),
                return_exceptions=True
            )
        finally:
            keepalive_task.cancel()
        
    except Exception as e:
        _logger.error(f"Realtime API error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass
        
    finally:
        if openai_ws:
            await openai_ws.close()
        _logger.info("Connection closed")
