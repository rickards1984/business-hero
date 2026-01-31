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
            "description": "List recent phone calls/call events for the business.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of calls to return (default 10, max 50)"
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
            "description": "List recent emails from the user's connected email account (Gmail or Microsoft).",
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
    
    with engine.connect() as conn:
        query = text("""
            SELECT id, caller_number, caller_name, started_at, ended_at, summary, intent, created_at
            FROM calls
            WHERE business_id = :business_id
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
                "created_at": row[7].isoformat() if row[7] else None
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
        return _fetch_gmail_emails(engine, str(account_id), access_token, refresh_token_ciphertext, email_address, limit, query)
    elif provider == "microsoft":
        return _fetch_microsoft_emails(engine, str(account_id), access_token, refresh_token_ciphertext, email_address, limit, query)
    else:
        return {"error": f"Unsupported email provider: {provider}"}


def _fetch_gmail_emails(engine, account_id: str, access_token: str, refresh_token_ciphertext: Optional[str], email_address: str, limit: int, query: str) -> dict:
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
            return {"emails": [], "count": 0, "account": email_address}
        
        # Fetch single email details
        def fetch_single_email(msg_id: str) -> Optional[dict]:
            try:
                msg_response = httpx.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
                    headers={"Authorization": f"Bearer {current_token}"},
                    params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
                    timeout=8
                )
                
                if msg_response.status_code == 200:
                    msg_data = msg_response.json()
                    headers_list = msg_data.get("payload", {}).get("headers", [])
                    
                    email_info = {
                        "id": msg_id,
                        "snippet": msg_data.get("snippet", "")[:150],  # Shorter for speed
                        "from": "",
                        "from_email": "",  # Just the email address for easy access
                        "subject": "",
                        "date": ""
                    }
                    
                    for h in headers_list:
                        if h["name"] == "From":
                            email_info["from"] = h["value"]
                            email_info["from_email"] = extract_email_address(h["value"])
                        elif h["name"] == "Subject":
                            email_info["subject"] = h["value"]
                        elif h["name"] == "Date":
                            email_info["date"] = h["value"]
                    
                    return email_info
            except:
                pass
            return None
        
        # Fetch messages IN PARALLEL (much faster!)
        ids_to_fetch = message_ids[:min(limit, 10)]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(fetch_single_email, ids_to_fetch))
            emails = [r for r in results if r is not None]
        
        return {"emails": emails, "count": len(emails), "account": email_address}
    
    except httpx.TimeoutException:
        return {"error": "Gmail API timeout. Please try again."}
    except Exception as e:
        return {"error": f"Failed to fetch emails: {str(e)}"}


def _fetch_microsoft_emails(engine, account_id: str, access_token: str, refresh_token_ciphertext: Optional[str], email_address: str, limit: int, query: str) -> dict:
    """Fetch emails from Microsoft Graph API with automatic token refresh."""
    
    def make_request(token: str):
        headers = {"Authorization": f"Bearer {token}"}
        params = {"$top": limit, "$orderby": "receivedDateTime desc", "$select": "id,subject,from,receivedDateTime,bodyPreview"}
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
        for msg in data.get("value", [])[:min(limit, 10)]:
            from_info = msg.get("from", {}).get("emailAddress", {})
            from_email = from_info.get("address", "")
            from_name = from_info.get("name", "")
            # Microsoft Graph already gives us just the email address
            emails.append({
                "id": msg.get("id"),
                "subject": msg.get("subject", ""),
                "from": f"{from_name} <{from_email}>" if from_name else from_email,
                "from_email": from_email,  # Just the email address for easy access
                "date": msg.get("receivedDateTime", ""),
                "snippet": msg.get("bodyPreview", "")[:150] if msg.get("bodyPreview") else ""
            })
        
        return {"emails": emails, "count": len(emails), "account": email_address}
    
    except httpx.TimeoutException:
        return {"error": "Microsoft Graph API timeout. Please try again."}
    except Exception as e:
        return {"error": f"Failed to fetch emails: {str(e)}"}


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
