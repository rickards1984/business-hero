"""OpenAI assistant tools for AI Admin Assistant."""

import os
from datetime import datetime, timedelta
from typing import Optional, List, Any
from uuid import UUID
import pytz
from sqlalchemy import create_engine, text


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
    }
]


def _get_engine():
    """Get SQLAlchemy engine for Supabase."""
    if not SUPABASE_DATABASE_URL:
        raise RuntimeError("SUPABASE_DATABASE_URL not configured")
    return create_engine(SUPABASE_DATABASE_URL, pool_pre_ping=True)


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
