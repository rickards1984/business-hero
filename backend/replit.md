# AI Admin Assistant API

## Overview
A multi-tenant backend API for AI Admin Assistant built with FastAPI and PostgreSQL (Supabase). Designed for:
- Awaz AI webhooks (call events)
- Custom GPT Actions (OpenAPI schema)
- AI Assistant chat with tool calling
- Future web dashboard / mobile app

## Project Structure
```
├── main.py             # FastAPI application with all endpoints
├── models.py           # SQLModel database models (Business, Task, Call)
├── schemas.py          # Pydantic request/response schemas
├── db.py               # Database configuration and session management
├── auth.py             # Authentication dependencies (x-api-key, x-master-key)
├── supabase_auth.py    # Supabase token verification for frontend users
├── assistant_chat.py   # AI Assistant chat handler with OpenAI
├── assistant_tools.py  # Tool definitions and execution for AI Assistant
├── openai_utils.py     # Optional OpenAI call summarization
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
├── README.md           # API documentation with curl examples
```

## Recent Changes
- 2024-12-24: Full conversation memory for AI Assistant
  - Messages persisted to assistant_messages table (role, content, timestamps)
  - Last 20 messages loaded and sent to OpenAI for context
  - User message saved before OpenAI call, assistant reply saved after
  - Business isolation enforced on message queries
- 2024-12-24: Conversation continuity for AI Assistant
  - Added assistant_conversations table support
  - New conversation created automatically if none provided
  - Existing conversation_id validated (UUID format, ownership, business match)
  - Response always includes conversation_id for continuity
  - Platform admins can access any conversation
- 2024-12-24: Enhanced AI Assistant chat endpoint
  - Added platform_admins support for cross-tenant access
  - Business name and timezone now injected into system prompt
  - Response includes full business object (id, name, timezone)
  - Multi-business resolution prefers role='owner' then earliest membership
  - Proper HTTP status codes: 401 (auth), 403 (forbidden), 404 (not found)
  - ChatRequest accepts both business_id and businessId via alias
  - Swagger UI persists authorization between requests
- 2024-12-23: Added AI Assistant chat endpoint
  - POST /v1/assistant/chat with Supabase JWT auth
  - Tool calling: list_tasks, create_task, list_calls, get_today_briefing
  - Business context via business_members table lookup
  - Uses OpenAI gpt-5 model with function calling
- 2024-12-17: Migrated from SQLite to PostgreSQL (Supabase)
  - Updated db.py to use SUPABASE_DATABASE_URL environment variable
  - Added psycopg2-binary driver for PostgreSQL
  - Tables persist across restarts/redeploys (no DROP on startup)
- 2024-12-14: Initial implementation of MVP backend
  - Multi-tenant authentication with API keys
  - Business, Task, and Call models
  - All CRUD endpoints for tasks and calls
  - Daily briefing endpoint with timezone support
  - Optional OpenAI summarization for call transcripts

## Key Decisions
- Using PostgreSQL (Supabase) for production database via SUPABASE_DATABASE_URL
- CORS enabled for all origins (development mode)
- Server runs on port 3000
- AI Assistant uses Supabase JWT auth (not API keys)

## Authentication
Three methods supported depending on endpoint:
- **Custom headers**: `x-master-key` / `x-api-key` headers (admin/business API)
- **Bearer auth with API key**: `Authorization: Bearer <api_key>` (GPT Actions compatible)
- **Bearer auth with Supabase JWT**: `Authorization: Bearer <access_token>` (Assistant chat)

## AI Assistant Chat
- Endpoint: `POST /v1/assistant/chat`
- Auth: Supabase access token (from frontend auth)
- Requires `business_members` table linking users to businesses
- Tools: list_tasks, create_task, list_calls, get_today_briefing
- Model: OpenAI gpt-5 with function calling

## ChatGPT GPT Actions
- Schema endpoint: `/openapi-action.json`
- Excludes admin endpoints for security
- Uses Bearer auth security scheme
- All operations marked as non-consequential

## Environment Variables
| Variable | Required | Description |
|----------|----------|-------------|
| SUPABASE_DATABASE_URL | Yes | PostgreSQL connection string (Supabase) |
| SUPABASE_URL | Yes | Supabase project URL |
| SUPABASE_ANON_KEY | Yes | Supabase anon/public key |
| SUPABASE_SERVICE_ROLE_KEY | Yes | Supabase service role key |
| MASTER_ADMIN_KEY | Yes | Master key for admin endpoints |
| OPENAI_API_KEY | Yes | OpenAI API key for AI features |

## Running
```bash
uvicorn main:app --host 0.0.0.0 --port 3000
```

Access Swagger UI at: http://localhost:3000/docs
