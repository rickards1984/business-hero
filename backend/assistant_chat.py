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


def build_system_prompt(business: BusinessContext) -> str:
    """Build the system prompt with business context."""
    return f"""You are an AI Admin Assistant for {business.name}. You help manage tasks, track phone calls, and provide daily briefings.

Business Context:
- Business Name: {business.name}
- Timezone: {business.timezone}
- When interpreting "today", "this week", or any relative dates, use the {business.timezone} timezone.

You have access to the following tools:
- list_tasks: View open, completed, or all tasks
- create_task: Create new tasks with title, description, and optional due date
- list_calls: View recent phone call records
- get_today_briefing: Get a summary of today's tasks and recent activity
- delete_task: Soft delete a task when the user confirms it's a duplicate

Be helpful, concise, and professional. When asked about tasks or calls, use the appropriate tools to fetch real data.
When creating tasks, confirm what was created. For briefings, summarize the key points clearly.
Only delete tasks when the user explicitly asks or confirms a duplicate; prefer deleting the newer duplicate."""


_engine = None


def _get_engine():
    """Get cached SQLAlchemy engine for Supabase."""
    global _engine
    if _engine is None:
        if not SUPABASE_DATABASE_URL:
            raise RuntimeError("SUPABASE_DATABASE_URL not configured")
        _engine = create_engine(SUPABASE_DATABASE_URL, pool_pre_ping=True, pool_size=5)
    return _engine


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
            SELECT id, name, timezone FROM businesses WHERE id = :business_id LIMIT 1
        """), {"business_id": business_id})
        row = result.fetchone()
        if row:
            return BusinessContext(id=str(row[0]), name=row[1], timezone=row[2])
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
                SELECT b.id, b.name, b.timezone
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
        
        return BusinessContext(id=str(row[0]), name=row[1], timezone=row[2])
    
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT bm.business_id, b.name, b.timezone, bm.role, bm.created_at
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
        return BusinessContext(id=str(m[0]), name=m[1], timezone=m[2])
    
    for m in memberships:
        if m[3] == 'owner':
            return BusinessContext(id=str(m[0]), name=m[1], timezone=m[2])
    
    m = memberships[0]
    return BusinessContext(id=str(m[0]), name=m[1], timezone=m[2])


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
    business_id: Optional[str] = None
) -> dict:
    """Process a chat message and return the assistant response.
    
    Args:
        user: Authenticated Supabase user
        message: User's message
        conversation_id: Optional conversation ID for continuity
        business_id: Optional business ID if user has multiple businesses
        
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
    system_prompt = build_system_prompt(business)
    logger.info(f"[DEBUG] System prompt built for {business.name}. History has {len(history)} messages.")
    
    client = OpenAI(api_key=OPENAI_API_KEY)
    
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": message})
    
    try:
        response = client.chat.completions.create(
            model="gpt-5",
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto"
        )
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return {"error": f"AI service error: {str(e)}", "status": 500}
    
    assistant_message = response.choices[0].message
    
    if assistant_message.tool_calls:
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
            
            logger.info(f"Executing tool: {tool_name} with args: {arguments}")
            
            try:
                tool_result = execute_tool(tool_name, arguments, business.id, business.timezone)
            except Exception as e:
                logger.error(f"Tool execution error: {e}")
                tool_result = {"error": str(e)}
            
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(tool_result)
            })
        
        try:
            final_response = client.chat.completions.create(
                model="gpt-5",
                messages=messages
            )
            assistant_reply = final_response.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI API error on final response: {e}")
            return {"error": f"AI service error: {str(e)}", "status": 500}
    else:
        assistant_reply = assistant_message.content
    
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
