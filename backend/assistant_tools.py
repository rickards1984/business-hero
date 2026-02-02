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
                        "description": "Maximum number of emails to return (default 10, max 20)"
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
    limit = min(args.get("limit", 5), 20)  # Default 5 for faster voice responses
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
                    
                    email_info = {
                        "id": msg_id,
                        "snippet": msg_data.get("snippet", "")[:200],
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
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
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
            
            email_info = {
                "id": msg.get("id"),
                "subject": msg.get("subject", ""),
                "from": f"{from_name} <{from_email}>" if from_name else from_email,
                "from_email": from_email,
                "date": msg.get("receivedDateTime", ""),
                "snippet": msg.get("bodyPreview", "")[:200] if msg.get("bodyPreview") else "",
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
