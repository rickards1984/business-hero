"""OpenAI assistant tools for AI Admin Assistant."""

import os
import re
import concurrent.futures
from datetime import datetime, timedelta
from typing import Optional, List, Any
from uuid import UUID
import pytz
import httpx
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text


def extract_email_address(from_header: str) -> str:
    """Extract email address from a From header like 'Name <email@example.com>'."""
    if not from_header:
        return ""
    match = re.search(r'<([^>]+)>', from_header)
    if match:
        return match.group(1)
    # If no angle brackets, the whole thing might be the email
    if '@' in from_header:
        return from_header.strip()
    return ""


SUPABASE_DATABASE_URL = os.getenv("SUPABASE_DATABASE_URL")
if SUPABASE_DATABASE_URL and SUPABASE_DATABASE_URL.startswith("postgres://"):
    SUPABASE_DATABASE_URL = SUPABASE_DATABASE_URL.replace("postgres://", "postgresql://", 1)


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "List tasks for the current business. Returns open tasks by default.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Filter by status: 'open', 'completed', or 'all'",
                        "enum": ["open", "completed", "all"]
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of tasks to return (default 10, max 50)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_task",
            "description": "Create a new task for the business.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title of the task"
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description of the task"
                    },
                    "due_at": {
                        "type": "string",
                        "description": "Optional due date in ISO 8601 format (e.g., '2024-12-25T10:00:00Z')"
                    }
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_calls",
            "description": "List recent phone calls/call events for the business. By default only shows non-archived calls.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of calls to return (default 10, max 50)"
                    },
                    "include_archived": {
                        "type": "boolean",
                        "description": "Whether to include archived calls (default false)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_today_briefing",
            "description": "Get today's briefing including tasks due today, overdue tasks, open tasks, and recent calls.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "delete_task",
            "description": "Soft delete a task by ID. Use when user confirms a task is a duplicate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "Task UUID to delete"
                    }
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_emails",
            "description": "List recent emails from the user's connected email account (Gmail or Microsoft). Use detailed=true when the user needs a thorough briefing or when you need to understand email content, not just subjects.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of emails to return (default 20)"
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional search query to filter emails (e.g., 'is:unread' or 'from:someone@example.com')"
                    },
                    "detailed": {
                        "type": "boolean",
                        "description": "If true, fetch full email body content for more accurate briefings. Takes slightly longer but provides complete context. Use for thorough briefings or when subject lines aren't enough."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email on behalf of the user. Use this when the user asks to send, reply to, or compose and send an email.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "Recipient email address"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line"
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body content (plain text)"
                    }
                },
                "required": ["to", "subject", "body"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_email_detail",
            "description": "Get the full content of a specific email by its ID. Use this when you need to read a particular email in full, or when a user asks about a specific email's content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {
                        "type": "string",
                        "description": "The email ID (from list_emails results)"
                    }
                },
                "required": ["email_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_calendar_events",
            "description": "List upcoming calendar events from the user's Google Calendar. Use this to check appointments, meetings, and scheduled events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Number of days ahead to look (default 7, max 30)"
                    },
                    "include_past": {
                        "type": "boolean",
                        "description": "Whether to include events from earlier today (default false)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_calendar_briefing",
            "description": "Get a calendar briefing including today's events, upcoming events, and tomorrow's schedule. Use this for daily briefings or when the user asks about their schedule.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_accounting_summary",
            "description": "Get financial summary including total income, expenses, and net profit/loss for a period. Use when user asks about finances, money, profit, or business performance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "enum": ["month", "quarter", "year", "all"],
                        "description": "Time period for the summary"
                    }
                },
                "required": ["period"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_transactions",
            "description": "List accounting transactions with optional filters. Use to show recent transactions, search for specific payments, or filter by income/expense.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["income", "expense", "all"],
                        "description": "Filter by transaction type"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of transactions to return (default 20)"
                    },
                    "search": {
                        "type": "string",
                        "description": "Search term to filter transactions by description"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_spending",
            "description": "Analyze spending patterns and provide insights on expenses by category. Use when user asks about where money is going, spending habits, or cost breakdown.",
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
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_invoices",
            "description": "List invoices with optional status filter. Use 'outstanding' to see all unpaid invoices, 'overdue' for past-due only, 'paid' for paid invoices, or 'all' for everything. Invoices may come from Xero sync or manual entry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["draft", "unpaid", "sent", "outstanding", "paid", "overdue", "all"],
                        "description": "Filter by status. 'outstanding' includes all unpaid/sent/overdue. Default: 'all'"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of invoices to return (default 10)"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_invoice_summary",
            "description": "Get a summary of invoice status including total outstanding, overdue amounts, and counts. Use when the user asks for an overview of invoices or what's owed.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_xero_financial_summary",
            "description": "Get live financial data from Xero: bank balance, monthly profit/loss, cash flow. Requires Xero connection.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_invoice_chase",
            "description": "Send a chase email for an unpaid invoice. Can specify stage 1-4 (1=friendly reminder, 2=firm follow-up, 3=urgent notice, 4=final demand). Use list_invoices first to get invoice IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice_id": {"type": "string", "description": "Invoice UUID (from list_invoices results)"},
                    "chase_stage": {"type": "integer", "description": "Chase stage 1-4. Default: next stage up from current."}
                },
                "required": ["invoice_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_overdue_invoices",
            "description": "Get all overdue invoices with details on how overdue they are and recommended chase actions.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "draft_email_reply",
            "description": "Generate a draft reply to an email. Returns 3 options: professional, friendly, and brief tones. Use list_emails first to get email IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "string", "description": "Email message ID (from list_emails results)"},
                    "tone": {"type": "string", "enum": ["professional", "friendly", "brief"], "description": "Preferred tone. If not specified, returns all 3 options."}
                },
                "required": ["email_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_business_overview",
            "description": "Get a comprehensive business overview: financial health, outstanding invoices, pending tasks, recent emails needing attention, upcoming calendar events. Perfect for morning briefings.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_cashflow_forecast",
            "description": "Get a simple cashflow forecast: current bank balance, expected income (from unpaid invoices), known upcoming expenses, and projected position.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {"type": "integer", "description": "How many days to forecast ahead (default 30, max 90)"}
                },
                "required": []
            }
        }
    }
]


def _get_engine():
    """Get SQLAlchemy engine for Supabase."""
    if not SUPABASE_DATABASE_URL:
        raise RuntimeError("SUPABASE_DATABASE_URL not configured")
    return create_engine(SUPABASE_DATABASE_URL, pool_pre_ping=True)


def _decrypt_token(ciphertext: str) -> str:
    """Decrypt an encrypted token."""
    key = os.getenv("EMAIL_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("EMAIL_ENCRYPTION_KEY not configured")
    f = Fernet(key.encode("utf-8"))
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def execute_tool(tool_name: str, arguments: dict, business_id: str, timezone: str = "Europe/London") -> dict:
    """Execute a tool and return the result.
    
    Args:
        tool_name: Name of the tool to execute
        arguments: Tool arguments
        business_id: UUID of the business context
        timezone: Business timezone for date calculations
        
    Returns:
        dict with tool result
    """
    engine = _get_engine()
    
    if tool_name == "list_tasks":
        return _list_tasks(engine, business_id, arguments)
    elif tool_name == "create_task":
        return _create_task(engine, business_id, arguments)
    elif tool_name == "list_calls":
        return _list_calls(engine, business_id, arguments)
    elif tool_name == "get_today_briefing":
        return _get_today_briefing(engine, business_id, timezone)
    elif tool_name == "delete_task":
        return _delete_task(engine, business_id, arguments)
    elif tool_name == "list_emails":
        return _list_emails(engine, business_id, arguments)
    elif tool_name == "send_email":
        return _send_email(engine, business_id, arguments)
    elif tool_name == "get_email_detail":
        return _get_email_detail(engine, business_id, arguments)
    elif tool_name == "list_calendar_events":
        return _list_calendar_events(engine, business_id, arguments)
    elif tool_name == "get_calendar_briefing":
        return _get_calendar_briefing(engine, business_id, arguments, timezone)
    elif tool_name == "get_accounting_summary":
        return _get_accounting_summary(engine, business_id, arguments)
    elif tool_name == "list_transactions":
        return _list_transactions(engine, business_id, arguments)
    elif tool_name == "analyze_spending":
        return _analyze_spending(engine, business_id, arguments)
    elif tool_name == "list_invoices":
        return _list_invoices(engine, business_id, arguments)
    elif tool_name == "get_invoice_summary":
        return _get_invoice_summary(engine, business_id, arguments)
    elif tool_name == "get_xero_financial_summary":
        return _get_xero_financial_summary(engine, business_id, arguments)
    elif tool_name == "send_invoice_chase":
        return _send_invoice_chase(engine, business_id, arguments)
    elif tool_name == "get_overdue_invoices":
        return _get_overdue_invoices(engine, business_id, arguments)
    elif tool_name == "draft_email_reply":
        return _draft_email_reply(engine, business_id, arguments)
    elif tool_name == "get_business_overview":
        return _get_business_overview(engine, business_id, arguments, timezone)
    elif tool_name == "get_cashflow_forecast":
        return _get_cashflow_forecast(engine, business_id, arguments)
    else:
        return {"error": f"Unknown tool: {tool_name}"}


def _list_tasks(engine, business_id: str, args: dict) -> dict:
    """List tasks for the business."""
    status_filter = args.get("status", "open")
    limit = min(args.get("limit", 10), 50)
    
    with engine.connect() as conn:
        if status_filter == "all":
            query = text("""
                SELECT id, title, description, due_at, status, source, created_at
                FROM tasks
                WHERE business_id = :business_id AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT :limit
            """)
        else:
            query = text("""
                SELECT id, title, description, due_at, status, source, created_at
                FROM tasks
                WHERE business_id = :business_id AND status = :status AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT :limit
            """)
        
        params = {"business_id": business_id, "limit": limit}
        if status_filter != "all":
            params["status"] = status_filter
            
        result = conn.execute(query, params)
        tasks = []
        for row in result:
            tasks.append({
                "id": str(row[0]),
                "title": row[1],
                "description": row[2],
                "due_at": row[3].isoformat() if row[3] else None,
                "status": row[4],
                "source": row[5],
                "created_at": row[6].isoformat() if row[6] else None
            })
        
        return {"tasks": tasks, "count": len(tasks)}


def _create_task(engine, business_id: str, args: dict) -> dict:
    """Create a new task."""
    title = args.get("title")
    if not title:
        return {"error": "Title is required"}
    
    description = args.get("description")
    due_at = args.get("due_at")
    
    with engine.connect() as conn:
        query = text("""
            INSERT INTO tasks (id, business_id, title, description, due_at, status, source, created_at, updated_at)
            VALUES (gen_random_uuid(), :business_id, :title, :description, :due_at, 'open', 'assistant', NOW(), NOW())
            RETURNING id, title, description, due_at, status, created_at
        """)
        
        result = conn.execute(query, {
            "business_id": business_id,
            "title": title,
            "description": description,
            "due_at": due_at
        })
        conn.commit()
        
        row = result.fetchone()
        return {
            "success": True,
            "task": {
                "id": str(row[0]),
                "title": row[1],
                "description": row[2],
                "due_at": row[3].isoformat() if row[3] else None,
                "status": row[4],
                "created_at": row[5].isoformat() if row[5] else None
            }
        }


def _list_calls(engine, business_id: str, args: dict) -> dict:
    """List recent calls."""
    limit = min(args.get("limit", 10), 50)
    include_archived = args.get("include_archived", False)
    
    with engine.connect() as conn:
        # Default: only show non-archived calls unless include_archived is True
        if include_archived:
            query = text("""
                SELECT id, caller_number, caller_name, started_at, ended_at, summary, intent, created_at, COALESCE(archived, false) as archived
                FROM calls
                WHERE business_id = :business_id
                ORDER BY created_at DESC
                LIMIT :limit
            """)
        else:
            query = text("""
                SELECT id, caller_number, caller_name, started_at, ended_at, summary, intent, created_at, COALESCE(archived, false) as archived
                FROM calls
                WHERE business_id = :business_id AND (archived IS NULL OR archived = false)
                ORDER BY created_at DESC
                LIMIT :limit
            """)
        
        result = conn.execute(query, {"business_id": business_id, "limit": limit})
        calls = []
        for row in result:
            calls.append({
                "id": str(row[0]),
                "caller_number": row[1],
                "caller_name": row[2],
                "started_at": row[3].isoformat() if row[3] else None,
                "ended_at": row[4].isoformat() if row[4] else None,
                "summary": row[5],
                "intent": row[6],
                "created_at": row[7].isoformat() if row[7] else None,
                "archived": bool(row[8]) if row[8] is not None else False
            })
        
        return {"calls": calls, "count": len(calls)}


def _get_today_briefing(engine, business_id: str, timezone: str) -> dict:
    """Get today's briefing."""
    try:
        tz = pytz.timezone(timezone)
    except pytz.UnknownTimeZoneError:
        tz = pytz.timezone("Europe/London")
    
    now = datetime.utcnow()
    now_local = pytz.utc.localize(now).astimezone(tz)
    
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    today_start_utc = today_start.astimezone(pytz.utc).replace(tzinfo=None)
    today_end_utc = today_end.astimezone(pytz.utc).replace(tzinfo=None)
    
    with engine.connect() as conn:
        tasks_due_today = conn.execute(text("""
            SELECT id, title, description, due_at, status
            FROM tasks
            WHERE business_id = :business_id AND status = 'open' AND deleted_at IS NULL
              AND due_at >= :today_start AND due_at < :today_end
            ORDER BY due_at
        """), {
            "business_id": business_id,
            "today_start": today_start_utc,
            "today_end": today_end_utc
        }).fetchall()
        
        overdue_tasks = conn.execute(text("""
            SELECT id, title, description, due_at, status
            FROM tasks
            WHERE business_id = :business_id AND status = 'open' AND deleted_at IS NULL AND due_at < :now
            ORDER BY due_at
        """), {"business_id": business_id, "now": now}).fetchall()
        
        open_tasks = conn.execute(text("""
            SELECT id, title, description, due_at, status
            FROM tasks
            WHERE business_id = :business_id AND status = 'open' AND deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT 10
        """), {"business_id": business_id}).fetchall()
        
        recent_calls = conn.execute(text("""
            SELECT id, caller_name, caller_number, summary, intent, created_at
            FROM calls
            WHERE business_id = :business_id
            ORDER BY created_at DESC
            LIMIT 5
        """), {"business_id": business_id}).fetchall()
    
    def format_task(row):
        return {
            "id": str(row[0]),
            "title": row[1],
            "description": row[2],
            "due_at": row[3].isoformat() if row[3] else None,
            "status": row[4]
        }
    
    def format_call(row):
        return {
            "id": str(row[0]),
            "caller_name": row[1],
            "caller_number": row[2],
            "summary": row[3],
            "intent": row[4],
            "created_at": row[5].isoformat() if row[5] else None
        }
    
    return {
        "date": now_local.strftime("%Y-%m-%d"),
        "timezone": timezone,
        "tasks_due_today": [format_task(t) for t in tasks_due_today],
        "tasks_due_today_count": len(tasks_due_today),
        "overdue_tasks": [format_task(t) for t in overdue_tasks],
        "overdue_count": len(overdue_tasks),
        "open_tasks": [format_task(t) for t in open_tasks],
        "open_tasks_count": len(open_tasks),
        "recent_calls": [format_call(c) for c in recent_calls],
        "recent_calls_count": len(recent_calls)
    }


def _delete_task(engine, business_id: str, args: dict) -> dict:
    """Soft delete a task by ID."""
    task_id = args.get("task_id")
    if not task_id:
        return {"error": "task_id is required"}

    with engine.connect() as conn:
        result = conn.execute(text("""
            UPDATE tasks
            SET deleted_at = NOW(), updated_at = NOW()
            WHERE id = :task_id AND business_id = :business_id AND deleted_at IS NULL
            RETURNING id, deleted_at
        """), {"task_id": task_id, "business_id": business_id})
        conn.commit()
        row = result.fetchone()
        if not row:
            return {"error": "Task not found"}
        return {
            "success": True,
            "task_id": str(row[0]),
            "deleted_at": row[1].isoformat() if row[1] else None,
        }


def _refresh_google_token(engine, account_id: str, refresh_token_ciphertext: str) -> str:
    """Refresh an expired Google access token and update the database."""
    try:
        refresh_token = _decrypt_token(refresh_token_ciphertext)
        
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token"
            },
            timeout=30
        )
        
        if response.status_code != 200:
            raise Exception(f"Token refresh failed: {response.status_code}")
        
        data = response.json()
        new_access_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)
        
        if not new_access_token:
            raise Exception("No access token in refresh response")
        
        # Encrypt and store the new token
        key = os.getenv("EMAIL_ENCRYPTION_KEY")
        f = Fernet(key.encode("utf-8"))
        new_token_ciphertext = f.encrypt(new_access_token.encode("utf-8")).decode("utf-8")
        
        new_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE email_accounts 
                SET token_ciphertext = :token, token_expires_at = :expires_at, updated_at = NOW()
                WHERE id = :account_id
            """), {
                "token": new_token_ciphertext,
                "expires_at": new_expires_at,
                "account_id": str(account_id)
            })
            conn.commit()
        
        return new_access_token
    except Exception as e:
        raise Exception(f"Failed to refresh token: {str(e)}")


def _refresh_microsoft_token(engine, account_id: str, refresh_token_ciphertext: str) -> str:
    """Refresh an expired Microsoft access token."""
    try:
        refresh_token = _decrypt_token(refresh_token_ciphertext)
        
        response = httpx.post(
            "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            data={
                "client_id": os.getenv("MICROSOFT_OAUTH_CLIENT_ID"),
                "client_secret": os.getenv("MICROSOFT_OAUTH_CLIENT_SECRET"),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
                "scope": "offline_access https://graph.microsoft.com/User.Read https://graph.microsoft.com/Mail.Read"
            },
            timeout=30
        )
        
        if response.status_code != 200:
            raise Exception(f"Token refresh failed: {response.status_code}")
        
        data = response.json()
        new_access_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)
        
        if not new_access_token:
            raise Exception("No access token in refresh response")
        
        key = os.getenv("EMAIL_ENCRYPTION_KEY")
        f = Fernet(key.encode("utf-8"))
        new_token_ciphertext = f.encrypt(new_access_token.encode("utf-8")).decode("utf-8")
        
        new_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE email_accounts 
                SET token_ciphertext = :token, token_expires_at = :expires_at, updated_at = NOW()
                WHERE id = :account_id
            """), {
                "token": new_token_ciphertext,
                "expires_at": new_expires_at,
                "account_id": str(account_id)
            })
            conn.commit()
        
        return new_access_token
    except Exception as e:
        raise Exception(f"Failed to refresh token: {str(e)}")


def _list_emails(engine, business_id: str, args: dict) -> dict:
    """List recent emails from connected email account."""
    limit = min(args.get("limit", 20), 50)  # Default 20, max 50
    query = args.get("query", "")
    detailed = args.get("detailed", False)  # Fetch full email content if true
    
    # Get the email account for this business
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, provider, email_address, token_ciphertext, refresh_token_ciphertext, token_expires_at
            FROM email_accounts
            WHERE business_id = :business_id AND provider IN ('google', 'microsoft')
            ORDER BY created_at DESC
            LIMIT 1
        """), {"business_id": business_id})
        row = result.fetchone()
    
    if not row:
        return {"error": "No email account connected. Please connect your Google or Microsoft account in Email Settings."}
    
    account_id, provider, email_address, token_ciphertext, refresh_token_ciphertext, token_expires_at = row
    
    if not token_ciphertext:
        return {"error": "Email account token not available. Please reconnect your email account in Email Settings."}
    
    # Decrypt the access token
    try:
        access_token = _decrypt_token(token_ciphertext)
    except Exception as e:
        return {"error": f"Failed to decrypt email token: {str(e)}"}
    
    if provider == "google":
        return _fetch_gmail_emails(engine, str(account_id), access_token, refresh_token_ciphertext, email_address, limit, query, detailed)
    elif provider == "microsoft":
        return _fetch_microsoft_emails(engine, str(account_id), access_token, refresh_token_ciphertext, email_address, limit, query, detailed)
    else:
        return {"error": f"Unsupported email provider: {provider}"}


def _extract_gmail_body(payload: dict) -> str:
    """Extract plain text body from Gmail message payload."""
    import base64
    
    def get_body_from_part(part: dict) -> str:
        """Recursively extract body from message parts."""
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        
        # If this part has data, decode it
        if body.get("data"):
            try:
                decoded = base64.urlsafe_b64decode(body["data"]).decode("utf-8", errors="ignore")
                decoded = decoded.replace("\r\n", "\n").strip()
                return decoded
            except Exception:
                pass
        
        # If multipart, look through parts
        parts = part.get("parts", [])
        
        plain_text = ""
        html_text = ""
        
        for p in parts:
            p_mime = p.get("mimeType", "")
            if p_mime == "text/plain":
                plain_text = get_body_from_part(p)
            elif p_mime == "text/html":
                html_text = get_body_from_part(p)
            elif p_mime.startswith("multipart/"):
                nested = get_body_from_part(p)
                if nested:
                    return nested
        
        # Prefer plain text, fall back to HTML (stripped of tags)
        if plain_text:
            return plain_text
        elif html_text:
            # Basic HTML tag stripping
            text = re.sub(r'<style[^>]*>.*?</style>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text)
            return text.strip()
        
        return ""
    
    return get_body_from_part(payload)


def _fetch_gmail_emails(engine, account_id: str, access_token: str, refresh_token_ciphertext: Optional[str], email_address: str, limit: int, query: str, detailed: bool = False) -> dict:
    """Fetch emails from Gmail API with automatic token refresh and parallel fetching."""
    
    def make_list_request(token: str):
        headers = {"Authorization": f"Bearer {token}"}
        params = {"maxResults": limit}
        if query:
            params["q"] = query
        
        response = httpx.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=headers,
            params=params,
            timeout=15
        )
        return response, token
    
    try:
        response, current_token = make_list_request(access_token)
        
        # If token expired, refresh and retry
        if response.status_code == 401 and refresh_token_ciphertext:
            try:
                new_token = _refresh_google_token(engine, account_id, refresh_token_ciphertext)
                current_token = new_token
                response, current_token = make_list_request(new_token)
            except Exception as refresh_error:
                return {"error": f"Email token expired and refresh failed: {str(refresh_error)}. Please reconnect your Google account."}
        
        if response.status_code == 401:
            return {"error": "Email access token expired. Please reconnect your Google account in Email Settings."}
        
        if response.status_code != 200:
            return {"error": f"Gmail API error: {response.status_code}"}
        
        data = response.json()
        message_ids = [m["id"] for m in data.get("messages", [])]
        
        if not message_ids:
            return {"emails": [], "count": 0, "account": email_address, "detailed": detailed}
        
        # Determine format based on detailed flag
        email_format = "full" if detailed else "metadata"
        
        # Fetch single email details
        def fetch_single_email(msg_id: str) -> Optional[dict]:
            try:
                params = {"format": email_format}
                if not detailed:
                    params["metadataHeaders"] = ["From", "Subject", "Date"]
                
                msg_response = httpx.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
                    headers={"Authorization": f"Bearer {current_token}"},
                    params=params,
                    timeout=15 if detailed else 8
                )
                
                if msg_response.status_code == 200:
                    msg_data = msg_response.json()
                    headers_list = msg_data.get("payload", {}).get("headers", [])
                    
                    snippet = msg_data.get("snippet", "")
                    max_snippet = 100 if limit > 10 else 200
                    if len(snippet) > max_snippet:
                        snippet = snippet[:max_snippet] + "..."
                    
                    email_info = {
                        "id": msg_id,
                        "snippet": snippet,
                        "from": "",
                        "from_email": "",
                        "subject": "",
                        "date": "",
                        "body": None
                    }
                    
                    for h in headers_list:
                        name = h.get("name", "").lower()
                        if name == "from":
                            email_info["from"] = h["value"]
                            email_info["from_email"] = extract_email_address(h["value"])
                        elif name == "subject":
                            email_info["subject"] = h["value"]
                        elif name == "date":
                            email_info["date"] = h["value"]
                    
                    # Extract body if detailed mode
                    if detailed:
                        body_text = _extract_gmail_body(msg_data.get("payload", {}))
                        if body_text:
                            email_info["body"] = body_text[:1500]
                            if len(body_text) > 1500:
                                email_info["body"] += "... [truncated]"
                    
                    return email_info
            except Exception as e:
                print(f"Error fetching email {msg_id}: {e}")
            return None
        
        # Fetch messages IN PARALLEL (much faster!)
        ids_to_fetch = message_ids[:min(limit, 20)]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(fetch_single_email, ids_to_fetch))
            emails = [r for r in results if r is not None]
        
        return {
            "emails": emails, 
            "count": len(emails), 
            "account": email_address,
            "detailed": detailed,
            "note": "Full email content included" if detailed else "Subject and preview only"
        }
    
    except httpx.TimeoutException:
        return {"error": "Gmail API timeout. Please try again."}
    except Exception as e:
        return {"error": f"Failed to fetch emails: {str(e)}"}


def _fetch_microsoft_emails(engine, account_id: str, access_token: str, refresh_token_ciphertext: Optional[str], email_address: str, limit: int, query: str, detailed: bool = False) -> dict:
    """Fetch emails from Microsoft Graph API with automatic token refresh."""
    
    def make_request(token: str):
        headers = {"Authorization": f"Bearer {token}"}
        
        # If detailed, include body content
        select_fields = "id,subject,from,receivedDateTime,bodyPreview"
        if detailed:
            select_fields = "id,subject,from,receivedDateTime,body"
        
        params = {
            "$top": limit, 
            "$orderby": "receivedDateTime desc", 
            "$select": select_fields
        }
        if query:
            params["$search"] = f'"{query}"'
        
        response = httpx.get(
            "https://graph.microsoft.com/v1.0/me/messages",
            headers=headers,
            params=params,
            timeout=30
        )
        return response
    
    try:
        response = make_request(access_token)
        
        # If token expired, refresh and retry
        if response.status_code == 401 and refresh_token_ciphertext:
            try:
                new_token = _refresh_microsoft_token(engine, account_id, refresh_token_ciphertext)
                response = make_request(new_token)
            except Exception as refresh_error:
                return {"error": f"Email token expired and refresh failed: {str(refresh_error)}. Please reconnect your Microsoft account."}
        
        if response.status_code == 401:
            return {"error": "Email access token expired. Please reconnect your Microsoft account in Email Settings."}
        
        if response.status_code != 200:
            return {"error": f"Microsoft Graph API error: {response.status_code}"}
        
        data = response.json()
        
        emails = []
        for msg in data.get("value", [])[:min(limit, 20)]:
            from_info = msg.get("from", {}).get("emailAddress", {})
            from_email = from_info.get("address", "")
            from_name = from_info.get("name", "")
            
            ms_snippet = msg.get("bodyPreview", "") or ""
            ms_max_snippet = 100 if limit > 10 else 200
            if len(ms_snippet) > ms_max_snippet:
                ms_snippet = ms_snippet[:ms_max_snippet] + "..."
            
            email_info = {
                "id": msg.get("id"),
                "subject": msg.get("subject", ""),
                "from": f"{from_name} <{from_email}>" if from_name else from_email,
                "from_email": from_email,
                "date": msg.get("receivedDateTime", ""),
                "snippet": ms_snippet,
                "body": None
            }
            
            if detailed and msg.get("body"):
                body_content = msg["body"].get("content", "")
                content_type = msg["body"].get("contentType", "text")
                
                # Strip HTML if needed
                if content_type.lower() == "html":
                    body_content = re.sub(r'<style[^>]*>.*?</style>', '', body_content, flags=re.DOTALL | re.IGNORECASE)
                    body_content = re.sub(r'<script[^>]*>.*?</script>', '', body_content, flags=re.DOTALL | re.IGNORECASE)
                    body_content = re.sub(r'<[^>]+>', ' ', body_content)
                    body_content = re.sub(r'\s+', ' ', body_content)
                
                # Truncate to reasonable length
                body_content = body_content.strip()[:1500]
                if len(body_content) == 1500:
                    body_content += "... [truncated]"
                
                email_info["body"] = body_content
            
            emails.append(email_info)
        
        return {
            "emails": emails, 
            "count": len(emails), 
            "account": email_address,
            "detailed": detailed,
            "note": "Full email content included" if detailed else "Subject and preview only"
        }
    
    except httpx.TimeoutException:
        return {"error": "Microsoft Graph API timeout. Please try again."}
    except Exception as e:
        return {"error": f"Failed to fetch emails: {str(e)}"}


# ============================================================================
# GET EMAIL DETAIL TOOL
# ============================================================================

def _get_email_detail(engine, business_id: str, args: dict) -> dict:
    """Get full details of a specific email by ID."""
    email_id = args.get("email_id")
    
    if not email_id:
        return {"error": "email_id is required"}
    
    # Get OAuth account
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, provider, email_address, token_ciphertext, refresh_token_ciphertext
            FROM email_accounts
            WHERE business_id = :business_id AND provider IN ('google', 'microsoft')
            ORDER BY created_at DESC
            LIMIT 1
        """), {"business_id": business_id})
        row = result.fetchone()
    
    if not row:
        return {"error": "No email account connected."}
    
    account_id, provider, email_address, token_ciphertext, refresh_token_ciphertext = row
    
    try:
        access_token = _decrypt_token(token_ciphertext)
    except Exception as e:
        return {"error": f"Failed to decrypt token: {str(e)}"}
    
    if provider == "google":
        return _fetch_gmail_single(engine, str(account_id), access_token, refresh_token_ciphertext, email_id)
    elif provider == "microsoft":
        return _fetch_microsoft_single(engine, str(account_id), access_token, refresh_token_ciphertext, email_id)
    else:
        return {"error": f"Unsupported provider: {provider}"}


def _fetch_gmail_single(engine, account_id: str, access_token: str, refresh_token_ciphertext: str, email_id: str) -> dict:
    """Fetch a single Gmail message in full."""
    import base64
    
    def make_request(token: str):
        return httpx.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{email_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"format": "full"},
            timeout=15
        )
    
    try:
        response = make_request(access_token)
        
        if response.status_code == 401 and refresh_token_ciphertext:
            new_token = _refresh_google_token(engine, account_id, refresh_token_ciphertext)
            response = make_request(new_token)
        
        if response.status_code != 200:
            return {"error": f"Failed to fetch email: {response.status_code}"}
        
        msg_data = response.json()
        headers_list = msg_data.get("payload", {}).get("headers", [])
        
        email_info = {
            "id": email_id,
            "from": "",
            "from_email": "",
            "to": "",
            "subject": "",
            "date": "",
            "body": ""
        }
        
        for h in headers_list:
            name = h.get("name", "").lower()
            if name == "from":
                email_info["from"] = h["value"]
                email_info["from_email"] = extract_email_address(h["value"])
            elif name == "to":
                email_info["to"] = h["value"]
            elif name == "subject":
                email_info["subject"] = h["value"]
            elif name == "date":
                email_info["date"] = h["value"]
        
        # Get full body
        body_text = _extract_gmail_body(msg_data.get("payload", {}))
        email_info["body"] = body_text[:3000] if body_text else ""
        if body_text and len(body_text) > 3000:
            email_info["body"] += "\n\n... [truncated - email continues]"
        
        return {"email": email_info}
        
    except Exception as e:
        return {"error": f"Failed to fetch email: {str(e)}"}


def _fetch_microsoft_single(engine, account_id: str, access_token: str, refresh_token_ciphertext: str, email_id: str) -> dict:
    """Fetch a single Microsoft email in full."""
    
    def make_request(token: str):
        return httpx.get(
            f"https://graph.microsoft.com/v1.0/me/messages/{email_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"$select": "id,subject,from,toRecipients,receivedDateTime,body"},
            timeout=15
        )
    
    try:
        response = make_request(access_token)
        
        if response.status_code == 401 and refresh_token_ciphertext:
            new_token = _refresh_microsoft_token(engine, account_id, refresh_token_ciphertext)
            response = make_request(new_token)
        
        if response.status_code != 200:
            return {"error": f"Failed to fetch email: {response.status_code}"}
        
        msg = response.json()
        
        body_content = ""
        if msg.get("body"):
            body_content = msg["body"].get("content", "")
            if msg["body"].get("contentType", "").lower() == "html":
                body_content = re.sub(r'<style[^>]*>.*?</style>', '', body_content, flags=re.DOTALL | re.IGNORECASE)
                body_content = re.sub(r'<script[^>]*>.*?</script>', '', body_content, flags=re.DOTALL | re.IGNORECASE)
                body_content = re.sub(r'<[^>]+>', ' ', body_content)
                body_content = re.sub(r'\s+', ' ', body_content).strip()
        
        email_info = {
            "id": email_id,
            "from": msg.get("from", {}).get("emailAddress", {}).get("name", ""),
            "from_email": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
            "to": ", ".join([r.get("emailAddress", {}).get("address", "") for r in msg.get("toRecipients", [])]),
            "subject": msg.get("subject", ""),
            "date": msg.get("receivedDateTime", ""),
            "body": body_content[:3000]
        }
        
        if len(body_content) > 3000:
            email_info["body"] += "\n\n... [truncated - email continues]"
        
        return {"email": email_info}
        
    except Exception as e:
        return {"error": f"Failed to fetch email: {str(e)}"}


# ============================================================================
# SEND EMAIL TOOL
# ============================================================================

def _send_email(engine, business_id: str, args: dict) -> dict:
    """Send an email using the connected OAuth account."""
    to_email = args.get("to", "").strip()
    subject = args.get("subject", "").strip()
    body = args.get("body", "").strip()
    
    # Clean up the body - replace literal \n with actual newlines if needed
    body = body.replace("\\n", "\n")
    
    if not to_email or not subject or not body:
        return {"success": False, "error": "Missing required fields: to, subject, and body are all required"}
    
    # Strict email validation - must be a real email address, not a name
    if "@" not in to_email:
        return {
            "success": False, 
            "error": f"Invalid recipient: '{to_email}' is not an email address. You must use an actual email address like 'name@example.com'. Look at the 'from_email' field in list_emails results to get email addresses, or ask the user for the email address."
        }
    
    if "." not in to_email.split("@")[-1]:
        return {
            "success": False,
            "error": f"Invalid email domain in '{to_email}'. The email address must have a valid domain like 'example.com'."
        }
    
    # Get OAuth account
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, provider, email_address, token_ciphertext, refresh_token_ciphertext
            FROM email_accounts
            WHERE business_id = :business_id AND provider IN ('google', 'microsoft')
            ORDER BY created_at DESC
            LIMIT 1
        """), {"business_id": business_id})
        row = result.fetchone()
    
    if not row:
        return {"success": False, "error": "No email account connected. Please connect Google or Microsoft in Email Settings."}
    
    account_id, provider, from_email, token_ciphertext, refresh_token_ciphertext = row
    
    if not token_ciphertext:
        return {"success": False, "error": "Email token missing. Please reconnect your email account."}
    
    try:
        access_token = _decrypt_token(token_ciphertext)
    except Exception as e:
        return {"success": False, "error": f"Token decryption failed: {str(e)}"}
    
    try:
        if provider == "google":
            api_result = _send_gmail_message(engine, str(account_id), access_token, refresh_token_ciphertext, to_email, subject, body)
            # Gmail returns the message ID on success
            if api_result and api_result.get("id"):
                return {
                    "success": True, 
                    "sent": True,
                    "message": f"Email successfully sent to {to_email}",
                    "from": from_email,
                    "to": to_email,
                    "subject": subject,
                    "gmail_message_id": api_result.get("id")
                }
            else:
                return {"success": False, "error": "Gmail API did not confirm send"}
                
        elif provider == "microsoft":
            api_result = _send_microsoft_message(engine, str(account_id), access_token, refresh_token_ciphertext, to_email, subject, body)
            # Microsoft returns 202 Accepted, api_result will be {"status": "sent"}
            return {
                "success": True,
                "sent": True, 
                "message": f"Email successfully sent to {to_email}",
                "from": from_email,
                "to": to_email,
                "subject": subject
            }
        else:
            return {"success": False, "error": f"Unknown email provider: {provider}"}
            
    except Exception as e:
        return {"success": False, "error": f"Send failed: {str(e)}"}


def _send_gmail_message(engine, account_id: str, access_token: str, refresh_token_ciphertext: str, to_email: str, subject: str, body: str) -> dict:
    """Send email via Gmail API with token refresh."""
    import base64
    from email.mime.text import MIMEText
    
    def attempt_send(token: str):
        message = MIMEText(body)
        message['to'] = to_email
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        response = httpx.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"raw": raw},
            timeout=30
        )
        return response
    
    response = attempt_send(access_token)
    
    # If 401, refresh token and retry
    if response.status_code == 401 and refresh_token_ciphertext:
        try:
            new_token = _refresh_google_token(engine, account_id, refresh_token_ciphertext)
            response = attempt_send(new_token)
        except Exception as refresh_error:
            raise Exception(f"Token expired and refresh failed: {str(refresh_error)}")
    
    if response.status_code not in [200, 202]:
        raise Exception(f"Gmail API error: {response.status_code} - {response.text}")
    
    return response.json()


def _send_microsoft_message(engine, account_id: str, access_token: str, refresh_token_ciphertext: str, to_email: str, subject: str, body: str) -> dict:
    """Send email via Microsoft Graph API with token refresh."""
    def attempt_send(token: str):
        response = httpx.post(
            "https://graph.microsoft.com/v1.0/me/sendMail",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": to_email}}]
                }
            },
            timeout=30
        )
        return response
    
    response = attempt_send(access_token)
    
    # If 401, refresh token and retry
    if response.status_code == 401 and refresh_token_ciphertext:
        try:
            new_token = _refresh_microsoft_token(engine, account_id, refresh_token_ciphertext)
            response = attempt_send(new_token)
        except Exception as refresh_error:
            raise Exception(f"Token expired and refresh failed: {str(refresh_error)}")
    
    if response.status_code not in [200, 202]:
        raise Exception(f"Microsoft Graph error: {response.status_code} - {response.text}")
    
    return {"status": "sent"}


# =============================================================================
# CALENDAR FUNCTIONS
# =============================================================================

def _list_calendar_events(engine, business_id: str, args: dict) -> dict:
    """List upcoming calendar events from connected Google Calendar."""
    days_ahead = min(args.get("days", 7), 30)  # Default 7 days, max 30
    include_past = args.get("include_past", False)
    
    # Get OAuth account
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, provider, email_address, token_ciphertext, refresh_token_ciphertext
            FROM email_accounts
            WHERE business_id = :business_id AND provider = 'google'
            ORDER BY created_at DESC
            LIMIT 1
        """), {"business_id": business_id})
        row = result.fetchone()
    
    if not row:
        return {"error": "No Google account connected. Please connect your Google account in Email Settings to access calendar."}
    
    account_id, provider, email_address, token_ciphertext, refresh_token_ciphertext = row
    
    if not token_ciphertext:
        return {"error": "Google account token not available. Please reconnect your Google account."}
    
    try:
        access_token = _decrypt_token(token_ciphertext)
    except Exception as e:
        return {"error": f"Failed to decrypt token: {str(e)}"}
    
    return _fetch_google_calendar_events(
        engine, 
        str(account_id), 
        access_token, 
        refresh_token_ciphertext, 
        email_address, 
        days_ahead,
        include_past
    )


def _fetch_google_calendar_events(
    engine, 
    account_id: str, 
    access_token: str, 
    refresh_token_ciphertext: Optional[str], 
    email_address: str, 
    days_ahead: int,
    include_past: bool = False
) -> dict:
    """Fetch events from Google Calendar API."""
    
    now = datetime.utcnow()
    
    if include_past:
        # Include events from start of today
        time_min = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        time_min = now
    
    time_max = now + timedelta(days=days_ahead)
    
    def make_request(token: str):
        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "timeMin": time_min.isoformat() + "Z",
            "timeMax": time_max.isoformat() + "Z",
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 50
        }
        
        response = httpx.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers=headers,
            params=params,
            timeout=30
        )
        return response
    
    try:
        response = make_request(access_token)
        
        # If token expired, refresh and retry
        if response.status_code == 401 and refresh_token_ciphertext:
            try:
                new_token = _refresh_google_token(engine, account_id, refresh_token_ciphertext)
                response = make_request(new_token)
            except Exception as refresh_error:
                return {"error": f"Calendar token expired and refresh failed: {str(refresh_error)}. Please reconnect your Google account."}
        
        if response.status_code == 403:
            return {"error": "Calendar access not authorized. Please reconnect your Google account and grant calendar permissions."}
        
        if response.status_code != 200:
            return {"error": f"Google Calendar API error: {response.status_code}"}
        
        data = response.json()
        
        events = []
        for event in data.get("items", []):
            # Parse start time
            start = event.get("start", {})
            start_time = start.get("dateTime") or start.get("date")
            
            # Parse end time
            end = event.get("end", {})
            end_time = end.get("dateTime") or end.get("date")
            
            # Determine if all-day event
            is_all_day = "date" in start and "dateTime" not in start
            
            events.append({
                "id": event.get("id"),
                "title": event.get("summary", "No title"),
                "description": event.get("description", "")[:200] if event.get("description") else None,
                "location": event.get("location"),
                "start": start_time,
                "end": end_time,
                "is_all_day": is_all_day,
                "status": event.get("status"),
                "attendees": [
                    {
                        "email": a.get("email"),
                        "name": a.get("displayName"),
                        "response": a.get("responseStatus")
                    }
                    for a in event.get("attendees", [])[:5]  # Limit to 5 attendees
                ],
                "meeting_link": event.get("hangoutLink") or _extract_meeting_link(event.get("description", "")),
                "organizer": event.get("organizer", {}).get("email")
            })
        
        return {
            "events": events,
            "count": len(events),
            "calendar": email_address,
            "period": f"Next {days_ahead} days" if not include_past else f"Today and next {days_ahead} days"
        }
    
    except httpx.TimeoutException:
        return {"error": "Google Calendar API timeout. Please try again."}
    except Exception as e:
        return {"error": f"Failed to fetch calendar events: {str(e)}"}


def _extract_meeting_link(text: str) -> Optional[str]:
    """Extract Zoom/Teams/Meet link from text."""
    if not text:
        return None
    
    patterns = [
        r'https://[a-zA-Z0-9.-]*zoom\.us/j/\S+',
        r'https://teams\.microsoft\.com/l/meetup-join/\S+',
        r'https://meet\.google\.com/\S+',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    
    return None


def _get_calendar_briefing(engine, business_id: str, args: dict, timezone: str = "Europe/London") -> dict:
    """Get a calendar briefing for today or a specific date."""
    
    # Get today's events
    today_result = _list_calendar_events(engine, business_id, {"days": 1, "include_past": True})
    
    if "error" in today_result:
        return today_result
    
    # Get this week's events for context
    week_result = _list_calendar_events(engine, business_id, {"days": 7, "include_past": False})
    
    try:
        tz = pytz.timezone(timezone)
    except Exception:
        tz = pytz.timezone("Europe/London")
    
    now = datetime.now(tz)
    today_str = now.strftime("%A, %d %B %Y")
    
    # Categorize today's events
    today_events = today_result.get("events", [])
    upcoming_today = []
    past_today = []
    
    for event in today_events:
        event_start = event.get("start")
        if event_start:
            try:
                if "T" in event_start:
                    event_time = datetime.fromisoformat(event_start.replace("Z", "+00:00"))
                    if event_time.tzinfo is None:
                        event_time = tz.localize(event_time)
                    else:
                        event_time = event_time.astimezone(tz)
                    
                    if event_time > now:
                        upcoming_today.append(event)
                    else:
                        past_today.append(event)
                else:
                    # All-day event
                    upcoming_today.append(event)
            except Exception:
                upcoming_today.append(event)
    
    # Get tomorrow's events
    tomorrow_events = [e for e in week_result.get("events", []) if _is_tomorrow(e.get("start"), tz)]
    
    return {
        "date": today_str,
        "timezone": timezone,
        "today": {
            "total": len(today_events),
            "upcoming": upcoming_today,
            "upcoming_count": len(upcoming_today),
            "completed": past_today,
            "completed_count": len(past_today)
        },
        "tomorrow": {
            "events": tomorrow_events,
            "count": len(tomorrow_events)
        },
        "week": {
            "total_events": week_result.get("count", 0)
        }
    }


def _is_tomorrow(date_str: str, tz) -> bool:
    """Check if a date string is tomorrow."""
    if not date_str:
        return False
    
    try:
        now = datetime.now(tz)
        tomorrow = (now + timedelta(days=1)).date()
        
        if "T" in date_str:
            event_date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
        else:
            event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        
        return event_date == tomorrow
    except Exception:
        return False


# =============================================================================
# CALENDAR WRITE FUNCTIONS (booking)
# =============================================================================

def _get_google_calendar_token(engine, business_id: str):
    """Return (access_token, account_id, refresh_token_ciphertext) or (None, …) if unavailable.

    Uses the same lookup as _list_calendar_events: query the google row
    from email_accounts, decrypt the token, and auto-refresh if expired.
    """
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT id, token_ciphertext, refresh_token_ciphertext
            FROM email_accounts
            WHERE business_id = :business_id AND provider = 'google'
            ORDER BY created_at DESC
            LIMIT 1
        """), {"business_id": business_id}).fetchone()

    if not row or not row[1]:
        return None, None, None

    account_id, token_ciphertext, refresh_ciphertext = str(row[0]), row[1], row[2]
    try:
        access_token = _decrypt_token(token_ciphertext)
    except Exception:
        return None, account_id, refresh_ciphertext

    return access_token, account_id, refresh_ciphertext


async def check_calendar_availability(
    business_id: str,
    date: str,
    duration_minutes: int = 60,
    start_hour: int = 9,
    end_hour: int = 17,
    calendar_id: str = "primary",
) -> dict:
    """Check available time slots on a given date using Google Calendar FreeBusy API."""
    from datetime import datetime as _dt, timedelta as _td

    engine = _get_engine()
    access_token, account_id, refresh_ciphertext = _get_google_calendar_token(engine, business_id)

    if not access_token:
        return {"error": "Google Calendar not connected", "slots": []}

    date_obj = _dt.fromisoformat(date)
    time_min = date_obj.replace(hour=start_hour, minute=0, second=0).isoformat() + "Z"
    time_max = date_obj.replace(hour=end_hour, minute=0, second=0).isoformat() + "Z"

    async def _freebusy(token: str):
        async with httpx.AsyncClient(timeout=30) as client:
            return await client.post(
                "https://www.googleapis.com/calendar/v3/freeBusy",
                headers={"Authorization": f"Bearer {token}"},
                json={"timeMin": time_min, "timeMax": time_max, "items": [{"id": calendar_id}]},
            )

    resp = await _freebusy(access_token)

    if resp.status_code == 401 and refresh_ciphertext:
        try:
            access_token = _refresh_google_token(engine, account_id, refresh_ciphertext)
            resp = await _freebusy(access_token)
        except Exception:
            return {"error": "Calendar token expired — please reconnect Google", "slots": []}

    if resp.status_code != 200:
        return {"error": f"Calendar API error: {resp.status_code}", "slots": []}

    busy_periods = resp.json().get("calendars", {}).get(calendar_id, {}).get("busy", [])

    available_slots = []
    current_time = date_obj.replace(hour=start_hour, minute=0, second=0)
    end_time = date_obj.replace(hour=end_hour, minute=0, second=0)
    slot_duration = _td(minutes=duration_minutes)

    while current_time + slot_duration <= end_time:
        slot_end = current_time + slot_duration
        is_busy = False
        for busy in busy_periods:
            busy_start = _dt.fromisoformat(busy["start"].replace("Z", "+00:00")).replace(tzinfo=None)
            busy_end = _dt.fromisoformat(busy["end"].replace("Z", "+00:00")).replace(tzinfo=None)
            if current_time < busy_end and slot_end > busy_start:
                is_busy = True
                break
        if not is_busy:
            available_slots.append({
                "start": current_time.strftime("%H:%M"),
                "end": slot_end.strftime("%H:%M"),
                "start_iso": current_time.isoformat(),
                "end_iso": slot_end.isoformat(),
            })
        current_time += _td(minutes=30)

    return {
        "date": date,
        "duration_minutes": duration_minutes,
        "business_hours": f"{start_hour:02d}:00 - {end_hour:02d}:00",
        "available_slots": available_slots,
        "total_available": len(available_slots),
    }


async def create_calendar_event(
    business_id: str,
    title: str,
    start_time: str,
    end_time: str,
    description: str = "",
    attendee_email: str = None,
    attendee_name: str = None,
    location: str = None,
    timezone: str = "Europe/London",
    calendar_id: str = "primary",
) -> dict:
    """Create a Google Calendar event (book an appointment)."""
    engine = _get_engine()
    access_token, account_id, refresh_ciphertext = _get_google_calendar_token(engine, business_id)

    if not access_token:
        return {"error": "Google Calendar not connected", "success": False}

    event_body: dict = {
        "summary": title,
        "description": description,
        "start": {
            "dateTime": start_time if "T" in start_time else f"{start_time}T00:00:00",
            "timeZone": timezone,
        },
        "end": {
            "dateTime": end_time if "T" in end_time else f"{end_time}T01:00:00",
            "timeZone": timezone,
        },
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": 30}],
        },
    }

    if location:
        event_body["location"] = location

    if attendee_email:
        attendee: dict = {"email": attendee_email}
        if attendee_name:
            attendee["displayName"] = attendee_name
        event_body["attendees"] = [attendee]

    async def _create(token: str):
        async with httpx.AsyncClient(timeout=30) as client:
            return await client.post(
                f"https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events",
                headers={"Authorization": f"Bearer {token}"},
                json=event_body,
                params={"sendUpdates": "all"},
            )

    resp = await _create(access_token)

    if resp.status_code == 401 and refresh_ciphertext:
        try:
            access_token = _refresh_google_token(engine, account_id, refresh_ciphertext)
            resp = await _create(access_token)
        except Exception:
            return {"error": "Calendar token expired — please reconnect Google", "success": False}

    if resp.status_code not in (200, 201):
        return {"error": f"Failed to create event: {resp.status_code} {resp.text}", "success": False}

    created = resp.json()
    return {
        "success": True,
        "event_id": created.get("id"),
        "title": created.get("summary"),
        "start": created.get("start", {}).get("dateTime"),
        "end": created.get("end", {}).get("dateTime"),
        "link": created.get("htmlLink"),
        "attendees": [a.get("email") for a in created.get("attendees", [])],
    }


# ============================================================================
# ACCOUNTING TOOLS
# ============================================================================

def _get_accounting_summary(engine, business_id: str, args: dict) -> dict:
    """Get financial summary for a period."""
    period = args.get("period", "month")
    
    from datetime import date
    today = date.today()
    
    # Determine date range
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
        
        totals = {"income": 0, "expense": 0, "income_count": 0, "expense_count": 0}
        for row in result.fetchall():
            if row[0] == "income":
                totals["income"] = float(row[2])
                totals["income_count"] = int(row[1])
            elif row[0] == "expense":
                totals["expense"] = float(row[2])
                totals["expense_count"] = int(row[1])
        
        net = totals["income"] - totals["expense"]
        
        return {
            "period": period,
            "start_date": start_date.isoformat(),
            "end_date": today.isoformat(),
            "total_income": round(totals["income"], 2),
            "total_expenses": round(totals["expense"], 2),
            "net_profit_loss": round(net, 2),
            "transaction_count": totals["income_count"] + totals["expense_count"],
            "summary": f"{'Profit' if net >= 0 else 'Loss'} of £{abs(net):,.2f} for {period}"
        }


def _list_transactions(engine, business_id: str, args: dict) -> dict:
    """List accounting transactions with optional filters."""
    trans_type = args.get("type", "all")
    limit = min(args.get("limit", 20), 50)
    search = args.get("search", "")
    
    with engine.connect() as conn:
        if trans_type != "all" and search:
            query = text("""
                SELECT id, transaction_date, description, amount, type, payee_payer, reference
                FROM accounting_transactions
                WHERE business_id = :business_id 
                  AND is_archived = false
                  AND type = :type
                  AND description ILIKE :search
                ORDER BY transaction_date DESC
                LIMIT :limit
            """)
            params = {"business_id": business_id, "type": trans_type, "search": f"%{search}%", "limit": limit}
        elif trans_type != "all":
            query = text("""
                SELECT id, transaction_date, description, amount, type, payee_payer, reference
                FROM accounting_transactions
                WHERE business_id = :business_id 
                  AND is_archived = false
                  AND type = :type
                ORDER BY transaction_date DESC
                LIMIT :limit
            """)
            params = {"business_id": business_id, "type": trans_type, "limit": limit}
        elif search:
            query = text("""
                SELECT id, transaction_date, description, amount, type, payee_payer, reference
                FROM accounting_transactions
                WHERE business_id = :business_id 
                  AND is_archived = false
                  AND description ILIKE :search
                ORDER BY transaction_date DESC
                LIMIT :limit
            """)
            params = {"business_id": business_id, "search": f"%{search}%", "limit": limit}
        else:
            query = text("""
                SELECT id, transaction_date, description, amount, type, payee_payer, reference
                FROM accounting_transactions
                WHERE business_id = :business_id 
                  AND is_archived = false
                ORDER BY transaction_date DESC
                LIMIT :limit
            """)
            params = {"business_id": business_id, "limit": limit}
        
        result = conn.execute(query, params)
        
        transactions = []
        for row in result.fetchall():
            transactions.append({
                "date": row[1].isoformat() if row[1] else None,
                "description": row[2],
                "amount": float(row[3]) if row[3] else 0,
                "type": row[4],
                "payee": row[5],
                "reference": row[6]
            })
        
        return {
            "transactions": transactions,
            "count": len(transactions),
            "filter_type": trans_type,
            "search_term": search if search else None
        }


def _analyze_spending(engine, business_id: str, args: dict) -> dict:
    """Analyze spending patterns by category."""
    period = args.get("period", "month")
    
    from datetime import date
    today = date.today()
    
    if period == "month":
        start_date = today - timedelta(days=30)
    elif period == "quarter":
        start_date = today - timedelta(days=90)
    else:
        start_date = today - timedelta(days=365)
    
    with engine.connect() as conn:
        # Get expenses grouped by category
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
        
        # Add percentages
        for cat in categories:
            cat["percentage"] = round(cat["total"] / total_expenses * 100, 1) if total_expenses > 0 else 0
        
        # Get top expense
        top_expense = categories[0] if categories else None
        
        return {
            "period": period,
            "start_date": start_date.isoformat(),
            "end_date": today.isoformat(),
            "total_expenses": round(total_expenses, 2),
            "by_category": categories[:10],
            "top_category": top_expense["category"] if top_expense else "None",
            "insight": f"Your biggest expense category is {top_expense['category']} at £{top_expense['total']:,.2f} ({top_expense['percentage']}% of total)" if top_expense else "No expenses found for this period"
        }


def _list_invoices(engine, business_id: str, args: dict) -> dict:
    """List invoices for the business."""
    from sqlalchemy import text
    
    status = args.get("status", "all")
    limit = min(args.get("limit", 10), 50)
    
    status_map = {
        "outstanding": ["unpaid", "sent", "overdue"],
        "unpaid": ["unpaid", "sent"],
        "overdue": ["overdue"],
        "paid": ["paid"],
        "draft": ["draft"],
        "cancelled": ["cancelled"],
    }
    
    with engine.connect() as conn:
        if status == "all":
            query = text("""
                SELECT id, invoice_number, customer_name, customer_email, amount, status,
                       due_date, issue_date, chase_stage, created_at
                FROM invoices
                WHERE business_id = :business_id AND (archived IS NULL OR archived = false)
                ORDER BY due_date DESC NULLS LAST, created_at DESC
                LIMIT :limit
            """)
            params = {"business_id": business_id, "limit": limit}
        elif status in status_map:
            statuses = status_map[status]
            placeholders = ", ".join([f":status_{i}" for i in range(len(statuses))])
            query = text(f"""
                SELECT id, invoice_number, customer_name, customer_email, amount, status,
                       due_date, issue_date, chase_stage, created_at
                FROM invoices
                WHERE business_id = :business_id
                  AND status IN ({placeholders})
                  AND (archived IS NULL OR archived = false)
                ORDER BY due_date DESC NULLS LAST, created_at DESC
                LIMIT :limit
            """)
            params = {"business_id": business_id, "limit": limit}
            for i, s in enumerate(statuses):
                params[f"status_{i}"] = s
        else:
            query = text("""
                SELECT id, invoice_number, customer_name, customer_email, amount, status,
                       due_date, issue_date, chase_stage, created_at
                FROM invoices
                WHERE business_id = :business_id AND status = :status
                  AND (archived IS NULL OR archived = false)
                ORDER BY due_date DESC NULLS LAST, created_at DESC
                LIMIT :limit
            """)
            params = {"business_id": business_id, "status": status, "limit": limit}
        
        result = conn.execute(query, params)
        
        invoices = []
        for row in result.fetchall():
            invoices.append({
                "id": str(row[0]),
                "invoice_number": row[1],
                "customer_name": row[2],
                "customer_email": row[3] or None,
                "amount": float(row[4]) if row[4] else 0,
                "status": row[5],
                "due_date": row[6].isoformat() if row[6] else None,
                "issue_date": row[7].isoformat() if row[7] else None,
                "chase_stage": row[8] if row[8] else 0,
            })
        
        return {
            "invoices": invoices,
            "count": len(invoices),
            "filter": status
        }


def _get_invoice_summary(engine, business_id: str, args: dict) -> dict:
    """Get invoice summary statistics."""
    from sqlalchemy import text
    from datetime import date
    
    today = date.today()
    
    with engine.connect() as conn:
        # Get counts and totals by status
        query = text("""
            SELECT 
                status,
                COUNT(*) as count,
                COALESCE(SUM(amount), 0) as total
            FROM invoices
            WHERE business_id = :business_id AND (archived IS NULL OR archived = false)
            GROUP BY status
        """)
        
        result = conn.execute(query, {"business_id": business_id})
        
        totals = {}
        for row in result.fetchall():
            totals[row[0]] = {"count": int(row[1]), "total": float(row[2])}
        
        # Get overdue invoices (sent but past due date)
        overdue_query = text("""
            SELECT COUNT(*), COALESCE(SUM(amount), 0)
            FROM invoices
            WHERE business_id = :business_id 
              AND due_date < :today 
              AND status NOT IN ('paid', 'cancelled', 'draft')
              AND (archived IS NULL OR archived = false)
        """)
        overdue_result = conn.execute(overdue_query, {"business_id": business_id, "today": today})
        overdue_row = overdue_result.fetchone()
        
        outstanding = (
            totals.get("sent", {}).get("total", 0) +
            totals.get("overdue", {}).get("total", 0) +
            totals.get("unpaid", {}).get("total", 0)
        )
        
        return {
            "total_outstanding": round(outstanding, 2),
            "total_overdue": round(float(overdue_row[1]) if overdue_row else 0, 2),
            "overdue_count": int(overdue_row[0]) if overdue_row else 0,
            "unpaid_count": totals.get("unpaid", {}).get("count", 0),
            "unpaid_total": round(totals.get("unpaid", {}).get("total", 0), 2),
            "sent_count": totals.get("sent", {}).get("count", 0),
            "sent_total": round(totals.get("sent", {}).get("total", 0), 2),
            "draft_count": totals.get("draft", {}).get("count", 0),
            "paid_count": totals.get("paid", {}).get("count", 0),
            "paid_total": round(totals.get("paid", {}).get("total", 0), 2),
            "currency": "GBP"
        }


# ============================================================================
# XERO FINANCIAL SUMMARY TOOL
# ============================================================================

def _get_xero_financial_summary(engine, business_id: str, args: dict) -> dict:
    """Get live financial data from Xero including bank balance and P&L."""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT xi.tenant_id, xi.access_token_ciphertext, xi.refresh_token_ciphertext,
                   xi.token_expires_at, xi.id, b.name as business_name
            FROM xero_integrations xi
            JOIN businesses b ON b.id = xi.business_id
            WHERE xi.business_id = :business_id AND xi.is_active = true
            LIMIT 1
        """), {"business_id": business_id})
        row = result.fetchone()

    if not row:
        local = _get_accounting_summary(engine, business_id, {"period": "month"})
        local["source"] = "local_only"
        local["note"] = "Xero not connected — showing local accounting data"
        return local

    tenant_id, access_token_cipher, refresh_token_cipher, token_expires_at, integration_id, business_name = row

    try:
        access_token = _decrypt_token(access_token_cipher)

        import asyncio
        from providers.xero import XeroProvider
        xero = XeroProvider(access_token=access_token, tenant_id=tenant_id)

        summary = {}

        loop = asyncio.new_event_loop()

        # Bank balance
        try:
            bank_data = loop.run_until_complete(xero.get_bank_summary())
            if bank_data and "Reports" in bank_data:
                report = bank_data["Reports"][0]
                total_balance = 0
                accounts = []
                for section in report.get("Rows", []):
                    for r in section.get("Rows", []):
                        cells = r.get("Cells", [])
                        if len(cells) >= 4:
                            account_name = cells[0].get("Value", "")
                            balance = cells[3].get("Value", "0")
                            try:
                                bal = float(balance.replace(",", ""))
                                total_balance += bal
                                accounts.append({"name": account_name, "balance": bal})
                            except (ValueError, AttributeError):
                                pass
                summary["bank_balance"] = round(total_balance, 2)
                summary["bank_accounts"] = accounts
        except Exception as e:
            summary["bank_balance_error"] = str(e)

        # Profit & Loss (current month)
        try:
            from datetime import date
            today = date.today()
            start = today.replace(day=1)
            pnl_data = loop.run_until_complete(
                xero.get_profit_and_loss(from_date=start.isoformat(), to_date=today.isoformat())
            )
            if pnl_data and "Reports" in pnl_data:
                report = pnl_data["Reports"][0]
                income = 0
                expenses = 0
                for section in report.get("Rows", []):
                    section_title = section.get("Title", "")
                    for r in section.get("Rows", []):
                        if r.get("RowType") == "SummaryRow":
                            cells = r.get("Cells", [])
                            if len(cells) >= 2:
                                try:
                                    val = float(cells[1].get("Value", "0").replace(",", ""))
                                    if "Income" in section_title:
                                        income = val
                                    elif "Expense" in section_title or "Operating" in section_title:
                                        expenses = abs(val)
                                except (ValueError, AttributeError):
                                    pass
                summary["monthly_income"] = round(income, 2)
                summary["monthly_expenses"] = round(expenses, 2)
                summary["monthly_net"] = round(income - expenses, 2)
                summary["monthly_status"] = "Profit" if income >= expenses else "Loss"
        except Exception as e:
            summary["pnl_error"] = str(e)
        finally:
            loop.close()

        summary["source"] = "xero_live"
        summary["business_name"] = business_name
        return summary

    except Exception as e:
        local = _get_accounting_summary(engine, business_id, {"period": "month"})
        local["xero_error"] = str(e)
        local["source"] = "local_fallback"
        return local


# ============================================================================
# SEND INVOICE CHASE TOOL
# ============================================================================

def _send_invoice_chase(engine, business_id: str, args: dict) -> dict:
    """Send a chase email for an invoice."""
    invoice_id = args.get("invoice_id", "")
    chase_stage = args.get("chase_stage")

    if not invoice_id:
        return {"success": False, "error": "invoice_id is required. Use list_invoices to find the invoice ID."}

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, invoice_number, customer_name, customer_email, amount, status,
                   chase_stage, due_date
            FROM invoices
            WHERE id = :invoice_id AND business_id = :business_id
              AND (archived IS NULL OR archived = false)
        """), {"invoice_id": invoice_id, "business_id": business_id})
        row = result.fetchone()

    if not row:
        return {"success": False, "error": f"Invoice {invoice_id} not found."}

    inv_id, inv_number, customer_name, customer_email, amount, status, current_stage, due_date = row

    if not customer_email:
        return {"success": False, "error": f"Invoice {inv_number} has no customer email address. Add an email in Xero or edit the invoice."}

    if status == "paid":
        return {"success": False, "error": f"Invoice {inv_number} is already paid. No chase needed."}

    stage = min(max(chase_stage, 1), 4) if chase_stage else min((current_stage or 0) + 1, 4)

    from email_templates import get_chase_email_template, get_stage_description

    invoice_dict = {
        "customer_name": customer_name,
        "invoice_number": inv_number,
        "amount": amount,
        "due_date": due_date.isoformat() if due_date else "N/A",
    }

    with engine.connect() as conn:
        biz_result = conn.execute(text("""
            SELECT id, name FROM businesses WHERE id = :business_id
        """), {"business_id": business_id})
        biz_row = biz_result.fetchone()

    if not biz_row:
        return {"success": False, "error": "Business not found."}

    template = get_chase_email_template(stage, invoice_dict, biz_row[1])

    with engine.connect() as conn:
        account_result = conn.execute(text("""
            SELECT id, provider, email_address, token_ciphertext, refresh_token_ciphertext
            FROM email_accounts
            WHERE business_id = :business_id AND provider IN ('google', 'microsoft')
            ORDER BY created_at DESC LIMIT 1
        """), {"business_id": business_id})
        account_row = account_result.fetchone()

    if not account_row:
        return {"success": False, "error": "No email account connected. Connect Gmail or Microsoft in Email Settings."}

    account_id, provider, from_email, token_ciphertext, refresh_token_ciphertext = account_row

    try:
        access_token = _decrypt_token(token_ciphertext)

        if provider == "google":
            send_result = _send_gmail_message(
                engine, str(account_id), access_token, refresh_token_ciphertext,
                customer_email, template["subject"], template["body"]
            )
        elif provider == "microsoft":
            send_result = _send_microsoft_message(
                engine, str(account_id), access_token, refresh_token_ciphertext,
                customer_email, template["subject"], template["body"]
            )
        else:
            return {"success": False, "error": f"Unsupported email provider: {provider}"}

        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE invoices SET chase_stage = :stage, last_chased_at = NOW(), updated_at = NOW()
                WHERE id = :invoice_id
            """), {"stage": stage, "invoice_id": invoice_id})
            conn.commit()

        stage_desc = get_stage_description(stage)
        return {
            "success": True,
            "message": f"Chase email sent to {customer_email} for invoice {inv_number}",
            "invoice_number": inv_number,
            "customer": customer_name,
            "amount": float(amount) if amount else 0,
            "chase_stage": stage,
            "stage_description": stage_desc,
            "sent_from": from_email,
            "sent_to": customer_email
        }

    except Exception as e:
        return {"success": False, "error": f"Failed to send chase email: {str(e)}"}


# ============================================================================
# GET OVERDUE INVOICES TOOL
# ============================================================================

def _get_overdue_invoices(engine, business_id: str, args: dict) -> dict:
    """Get all overdue invoices with actionable insights."""
    from datetime import date
    today = date.today()

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, invoice_number, customer_name, customer_email, amount,
                   due_date, chase_stage, last_chased_at, status
            FROM invoices
            WHERE business_id = :business_id
              AND status IN ('unpaid', 'sent', 'overdue')
              AND due_date < :today
              AND (archived IS NULL OR archived = false)
            ORDER BY due_date ASC
        """), {"business_id": business_id, "today": today})

        invoices = []
        total_overdue = 0
        for row in result.fetchall():
            days_overdue = (today - row[5]).days if row[5] else 0
            current_stage = row[6] or 0

            if current_stage == 0:
                recommended_action = "Send friendly reminder (Stage 1)"
            elif current_stage == 1:
                recommended_action = "Send firm follow-up (Stage 2)"
            elif current_stage == 2:
                recommended_action = "Send urgent notice (Stage 3)"
            elif current_stage == 3:
                recommended_action = "Send final demand (Stage 4)"
            else:
                recommended_action = "All chase stages sent — consider phone call or legal action"

            invoices.append({
                "id": str(row[0]),
                "invoice_number": row[1],
                "customer_name": row[2],
                "customer_email": row[3],
                "amount": float(row[4]) if row[4] else 0,
                "due_date": row[5].isoformat() if row[5] else None,
                "days_overdue": days_overdue,
                "chase_stage": current_stage,
                "last_chased": row[7].isoformat() if row[7] else "Never",
                "recommended_action": recommended_action,
                "has_email": bool(row[3])
            })
            total_overdue += float(row[4]) if row[4] else 0

        return {
            "overdue_invoices": invoices,
            "count": len(invoices),
            "total_overdue_amount": round(total_overdue, 2),
            "summary": f"{len(invoices)} overdue invoice(s) totalling £{total_overdue:,.2f}" if invoices else "No overdue invoices — all clear!"
        }


# ============================================================================
# DRAFT EMAIL REPLY TOOL
# ============================================================================

def _draft_email_reply(engine, business_id: str, args: dict) -> dict:
    """Generate draft reply options for an email."""
    import json as _json
    email_id = args.get("email_id", "")
    preferred_tone = args.get("tone")

    if not email_id:
        return {"error": "email_id is required. Use list_emails to find email IDs."}

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT id, from_email, from_name, subject, snippet, body_text, received_at
            FROM email_messages
            WHERE id = :email_id AND business_id = :business_id
        """), {"email_id": email_id, "business_id": business_id})
        row = result.fetchone()

    if not row:
        return {"error": f"Email {email_id} not found."}

    msg_id, from_email, from_name, subject, snippet, body_text, received_at = row

    with engine.connect() as conn:
        biz = conn.execute(text("SELECT name FROM businesses WHERE id = :id"), {"id": business_id}).fetchone()
    business_name = biz[0] if biz else "the business"

    email_content = body_text or snippet or "(no content)"

    try:
        import openai
        client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"Generate 3 reply drafts for a business email. Business: {business_name}.\n\n"
                        "Tones:\n"
                        '1. "professional" — Formal, polished corporate tone\n'
                        '2. "friendly" — Warm, conversational but business-appropriate\n'
                        '3. "brief" — Ultra-concise, 2-3 sentences max\n\n'
                        "Return ONLY a JSON array with 3 objects: tone, subject, body\n"
                        "No markdown, no backticks."
                    )
                },
                {
                    "role": "user",
                    "content": f"From: {from_name or from_email}\nSubject: {subject}\nContent: {email_content[:1000]}"
                }
            ],
            max_tokens=1000,
            temperature=0.4,
        )

        content = response.choices[0].message.content or ""
        content = content.strip().strip("`").strip()
        if content.startswith("json"):
            content = content[4:].strip()

        drafts = _json.loads(content)

        result_drafts = []
        for d in drafts:
            result_drafts.append({
                "tone": d.get("tone", ""),
                "subject": d.get("subject", f"Re: {subject}"),
                "body": d.get("body", ""),
            })

        if preferred_tone:
            result_drafts.sort(key=lambda x: 0 if x["tone"] == preferred_tone else 1)

        return {
            "email_id": email_id,
            "replying_to": from_email,
            "original_subject": subject,
            "drafts": result_drafts,
            "instruction": "Present these options to the user. They can pick one, and you can send it using send_email."
        }

    except Exception as e:
        return {
            "email_id": email_id,
            "replying_to": from_email,
            "drafts": [{
                "tone": "professional",
                "subject": f"Re: {subject}",
                "body": f"Hi {from_name or 'there'},\n\nThank you for your email. I will review and get back to you shortly.\n\nBest regards,\n{business_name}"
            }],
            "error": f"AI generation failed ({str(e)}), showing fallback draft"
        }


# ============================================================================
# BUSINESS OVERVIEW TOOL
# ============================================================================

def _get_business_overview(engine, business_id: str, args: dict, timezone: str = "Europe/London") -> dict:
    """Get comprehensive business overview — perfect for morning briefings."""
    overview = {}

    overview["financials"] = _get_accounting_summary(engine, business_id, {"period": "month"})
    overview["invoices"] = _get_invoice_summary(engine, business_id, {})
    overview["overdue"] = _get_overdue_invoices(engine, business_id, {})
    overview["tasks"] = _list_tasks(engine, business_id, {"status": "open", "limit": 5})

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT COUNT(*) FROM email_messages
            WHERE business_id = :business_id AND is_unread = true
        """), {"business_id": business_id})
        unread = result.fetchone()
        overview["unread_emails"] = int(unread[0]) if unread else 0

    try:
        overview["calendar"] = _get_calendar_briefing(engine, business_id, {}, timezone)
    except Exception:
        overview["calendar"] = {"events": [], "note": "Calendar not connected"}

    overview["briefing_generated_at"] = datetime.utcnow().isoformat()

    return overview


# ============================================================================
# CASHFLOW FORECAST TOOL
# ============================================================================

def _get_cashflow_forecast(engine, business_id: str, args: dict) -> dict:
    """Simple cashflow forecast based on current data."""
    from datetime import date
    days_ahead = min(args.get("days_ahead", 30), 90)
    today = date.today()

    with engine.connect() as conn:
        monthly = conn.execute(text("""
            SELECT type, COALESCE(SUM(ABS(amount)), 0)
            FROM accounting_transactions
            WHERE business_id = :business_id AND is_archived = false
              AND transaction_date >= :start AND transaction_date <= :end
            GROUP BY type
        """), {"business_id": business_id, "start": today.replace(day=1), "end": today})

        current_income = 0
        current_expenses = 0
        for row in monthly.fetchall():
            if row[0] == "income":
                current_income = float(row[1])
            elif row[0] == "expense":
                current_expenses = float(row[1])

        inv_result = conn.execute(text("""
            SELECT COALESCE(SUM(amount), 0), COUNT(*)
            FROM invoices
            WHERE business_id = :business_id
              AND status IN ('unpaid', 'sent', 'overdue')
              AND (archived IS NULL OR archived = false)
        """), {"business_id": business_id})
        inv_row = inv_result.fetchone()
        expected_income = float(inv_row[0]) if inv_row else 0
        outstanding_count = int(inv_row[1]) if inv_row else 0

    forecast = {
        "period": f"Next {days_ahead} days",
        "current_monthly_income": round(current_income, 2),
        "current_monthly_expenses": round(current_expenses, 2),
        "expected_income_from_invoices": round(expected_income, 2),
        "outstanding_invoice_count": outstanding_count,
        "projected_net": round(current_income + expected_income - current_expenses, 2),
        "note": "Simplified forecast based on current trends and outstanding invoices."
    }

    try:
        xero_data = _get_xero_financial_summary(engine, business_id, {})
        if "bank_balance" in xero_data:
            forecast["current_bank_balance"] = xero_data["bank_balance"]
            forecast["projected_bank_balance"] = round(
                xero_data["bank_balance"] + expected_income - current_expenses, 2
            )
    except Exception:
        pass

    return forecast
