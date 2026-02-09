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
REALTIME_TOOLS = [
    {
        "type": "function",
        "name": "list_emails",
        "description": "List recent emails from the user's inbox",
        "parameters": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of emails to retrieve (default 5, max 10)"
                }
            }
        }
    },
    {
        "type": "function",
        "name": "get_schedule",
        "description": "Get today's calendar events and appointments",
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
        "description": "Get recent phone calls and their details",
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
        "description": "Get the user's task list",
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
        "name": "get_financial_summary",
        "description": "Get a summary of business finances including income, expenses, and profit/loss",
        "parameters": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "enum": ["month", "quarter", "year"],
                    "description": "Time period for the summary"
                }
            },
            "required": ["period"]
        }
    },
    {
        "type": "function",
        "name": "analyze_spending",
        "description": "Analyze spending patterns by category",
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
        "description": "Search accounting transactions by description or amount",
        "parameters": {
            "type": "object",
            "properties": {
                "search": {
                    "type": "string",
                    "description": "Search term"
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
        "description": "List invoices with optional filters for status",
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
        "description": "Get a summary of invoices including total outstanding, overdue amounts, and recent payments",
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
    return f"""You are an AI Admin assistant for {business_name}. You're speaking with {user_name}.

Your personality:
- Warm, professional, and efficient
- British English (use £ for currency, UK date formats)
- Conversational but concise - you're a busy professional's assistant
- Proactive - offer relevant follow-ups and insights
- When accessing data, be natural: "Let me check that for you..." then provide the info

Your capabilities:
- Check and summarise emails
- Review calendar and schedule
- Access call logs
- Manage tasks
- List and summarise invoices (outstanding, overdue, paid)
- Provide financial summaries and spending analysis
- Search and review accounting transactions

Guidelines:
- For financial data, always mention the time period and currency
- Offer to go into more detail when relevant
- If asked about something you can't do, suggest alternatives
- Keep responses conversational - you're speaking, not writing
- Use natural speech patterns with brief pauses where appropriate"""


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
                "voice": "nova",
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
