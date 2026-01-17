# AI Admin Assistant API

A multi-tenant backend for AI Admin Assistant - integrates with Awaz AI webhooks and Custom GPT Actions.

## Features

- **Multi-tenant architecture**: Each business has its own API key
- **Task management**: Create, list, complete, and snooze tasks
- **Call tracking**: Log calls from Awaz AI webhooks with optional AI summarization
- **Daily briefing**: Get a summary of today's tasks and recent calls
- **OpenAPI compliant**: Interactive Swagger UI at `/docs`

## Quick Start

### 1. Set Environment Variables

```bash
# Required: Master admin key for creating businesses
export MASTER_ADMIN_KEY="your-secure-master-key"

# Optional: OpenAI key for automatic call summarization
export OPENAI_API_KEY="sk-..."
```

### 2. Run the Server

The server runs on port 3000 by default:

```bash
uvicorn main:app --host 0.0.0.0 --port 3000
```

### 3. Access the API

- **Swagger UI**: http://localhost:3000/docs
- **OpenAPI JSON**: http://localhost:3000/openapi.json
- **GPT Actions Schema**: http://localhost:3000/openapi-action.json
- **Health Check**: http://localhost:3000/health

## Authentication

The API supports two authentication methods for flexibility:

### Option 1: Custom Headers (Original)
- **Admin endpoints**: `x-master-key: <MASTER_ADMIN_KEY>`
- **Business endpoints**: `x-api-key: <business_api_key>`

### Option 2: Authorization Header (GPT Actions Compatible)
- **Admin endpoints**: `Authorization: Bearer <MASTER_ADMIN_KEY>`
- **Business endpoints**: `Authorization: Bearer <business_api_key>`

Both methods work interchangeably. Use Option 2 for ChatGPT GPT Actions integration.

## Using with ChatGPT Actions

This API is designed to work seamlessly with ChatGPT Custom GPT Actions.

### Setup Instructions

1. **Get your API base URL**: After deploying, your base URL will be something like `https://your-app.replit.app`

2. **Import the schema**: In your Custom GPT configuration, import the OpenAPI schema from:
   ```
   https://your-app.replit.app/openapi-action.json
   ```

3. **Configure authentication**:
   - Authentication type: **API Key**
   - Auth Type: **Bearer**
   - API Key: Your business API key (obtained when creating a business via admin endpoint)

4. **Available actions for GPT**:
   - Get business profile (`/v1/me`)
   - Create and list tasks (`/v1/tasks`)
   - Complete and snooze tasks
   - Log and list calls (`/v1/calls`)
   - Get daily briefing (`/v1/briefing/today`)

### Notes
- Admin endpoints (`/v1/admin/*`) are excluded from the GPT Actions schema for security
- All endpoints are marked as non-consequential for smooth UX (no confirmation prompts)
- The `/health` endpoint is public and requires no authentication

## API Usage Examples

### Create a Business (Admin)

```bash
curl -X POST "http://localhost:3000/v1/admin/businesses" \
  -H "x-master-key: your-master-key" \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp", "timezone": "Europe/London"}'
```

Response:
```json
{
  "id": "uuid-here",
  "name": "Acme Corp",
  "timezone": "Europe/London",
  "api_key": "sk_abc123..."
}
```

**Save the `api_key` - it's only shown once!**

### List Businesses (Admin)

```bash
curl -X GET "http://localhost:3000/v1/admin/businesses" \
  -H "x-master-key: your-master-key"
```

### Get Business Profile

```bash
curl -X GET "http://localhost:3000/v1/me" \
  -H "x-api-key: sk_abc123..."
```

### Create a Task

```bash
curl -X POST "http://localhost:3000/v1/tasks" \
  -H "x-api-key: sk_abc123..." \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Call back John",
    "description": "Discuss proposal",
    "due_at": "2024-12-15T10:00:00Z",
    "recurrence": "none",
    "source": "manual"
  }'
```

### List Tasks

```bash
# All tasks
curl -X GET "http://localhost:3000/v1/tasks" \
  -H "x-api-key: sk_abc123..."

# Filter by status
curl -X GET "http://localhost:3000/v1/tasks?status=open" \
  -H "x-api-key: sk_abc123..."

# Filter by due date
curl -X GET "http://localhost:3000/v1/tasks?due_before=2024-12-31T23:59:59Z" \
  -H "x-api-key: sk_abc123..."
```

### Complete a Task

```bash
curl -X POST "http://localhost:3000/v1/tasks/{task_id}/complete" \
  -H "x-api-key: sk_abc123..."
```

### Snooze a Task

```bash
# Snooze for 60 minutes
curl -X POST "http://localhost:3000/v1/tasks/{task_id}/snooze" \
  -H "x-api-key: sk_abc123..." \
  -H "Content-Type: application/json" \
  -d '{"minutes": 60}'

# Snooze until specific time
curl -X POST "http://localhost:3000/v1/tasks/{task_id}/snooze" \
  -H "x-api-key: sk_abc123..." \
  -H "Content-Type: application/json" \
  -d '{"until": "2024-12-16T09:00:00Z"}'
```

### Log a Call (Awaz Webhook)

```bash
curl -X POST "http://localhost:3000/v1/calls" \
  -H "x-api-key: sk_abc123..." \
  -H "Content-Type: application/json" \
  -d '{
    "caller_number": "+44123456789",
    "caller_name": "John Smith",
    "started_at": "2024-12-14T14:30:00Z",
    "ended_at": "2024-12-14T14:35:00Z",
    "transcript": "Hi, I am interested in your services...",
    "intent": "new_lead",
    "create_follow_up_task": true
  }'
```

If `create_follow_up_task` is `true` OR `intent` is `"new_lead"`, a follow-up task is automatically created.

If `OPENAI_API_KEY` is configured and no summary is provided, one will be auto-generated.

### Awaz Webhook

```bash
curl -X POST "http://localhost:3000/v1/webhooks/awaz/calls" \
  -H "x-api-key: sk_abc123..." \
  -H "Content-Type: application/json" \
  -d '{
    "caller_number": "+44123456789",
    "caller_name": "John Smith",
    "started_at": "2024-12-14T14:30:00Z",
    "ended_at": "2024-12-14T14:35:00Z",
    "transcript": "Hi, I am interested in your services...",
    "intent": "new_lead",
    "create_follow_up_task": true
  }'
```

### List Calls

```bash
curl -X GET "http://localhost:3000/v1/calls?limit=50" \
  -H "x-api-key: sk_abc123..."
```

### Get Daily Briefing

```bash
curl -X GET "http://localhost:3000/v1/briefing/today" \
  -H "x-api-key: sk_abc123..."
```

Returns:
- `tasks_due_today`: Open tasks due today (in business timezone)
- `overdue_tasks`: Open tasks past due
- `open_tasks`: Next 10 open tasks
- `recent_calls`: Last 5 calls with summaries
- `generated_at`: Timestamp

## Testing via Swagger UI

1. Go to http://localhost:3000/docs
2. Click "Authorize" button
3. Enter your `x-master-key` for admin endpoints
4. Enter your `x-api-key` for business endpoints
5. Try out the endpoints!

## Data Models

### Business
- `id`: UUID
- `name`: Business name
- `timezone`: Timezone (default: Europe/London)
- `api_key`: Unique API key (shown only on creation)
- `created_at`: Creation timestamp

### Task
- `id`: UUID
- `business_id`: Owner business
- `title`: Task title
- `description`: Optional description
- `due_at`: Optional due date
- `recurrence`: none/daily/weekly/monthly
- `status`: open/done/snoozed
- `source`: manual/awaz/email/calendar
- `created_at`, `updated_at`: Timestamps

### CallEvent
- `id`: UUID
- `business_id`: Owner business
- `source`: Source system (default: awaz)
- `caller_number`, `caller_name`: Caller info
- `started_at`, `ended_at`: Call timing
- `transcript`: Full transcript
- `summary`: AI-generated or provided summary
- `intent`: new_lead/existing_customer/supplier
- `raw_payload`: Original JSON payload
- `created_at`: Timestamp

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MASTER_ADMIN_KEY` | Yes | Master key for admin endpoints |
| `OPENAI_API_KEY` | No | Enables AI call summarization |
| `PORT` | No | Server port (default: 3000) |
| `DATABASE_URL` | No | Database URL (default: sqlite:///./data.db) |

## License

MIT
