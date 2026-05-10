"""
AI-powered briefing generator.
Uses GPT to produce strategic business analysis from raw data.
"""

import os
import json
import logging
from typing import Dict, Any, List, Tuple

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


def _serialize_for_json(obj: Any) -> Any:
    """Convert dates etc for JSON serialization."""
    from datetime import date, datetime
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


async def generate_weekly_briefing(
    business_name: str,
    owner_name: str,
    data: Dict[str, Any],
    detail_level: str = "standard",
) -> Tuple[str, List[Dict], Dict]:
    """
    Generate a weekly CEO briefing using GPT.

    Returns:
        (briefing_text, action_options, ai_analysis)
    """
    client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

    system_prompt = f"""You are the AI business intelligence analyst for "{business_name}". You produce a concise, actionable weekly CEO briefing for {owner_name or 'the owner'}.

RULES:
- Use British English throughout
- Be concise — this goes to WhatsApp, so format matters
- Use emoji sparingly but effectively for visual scanning (📊 💰 📞 📧 ✅ ⚠️ 💡)
- Use ━━━ as section dividers
- Lead with what matters most — if there's a problem, lead with it
- Include specific numbers, percentages, and comparisons to last period
- Calculate percentage changes (↑12% or ↓5%)
- NEVER give financial advice — you observe data and suggest operational actions
- Always caveat suggestions with "Based on the data..." or "You might consider..."
- End with 3-5 numbered quick-action options
- Keep total message under 3500 characters

TONE: Professional but warm. Like a trusted business partner giving a Monday morning debrief over coffee. Not corporate-speak. Use "you" and "your" — make it personal.

DETAIL LEVEL: {detail_level}
- brief: Key numbers only, 1500 chars max
- standard: Numbers + observations + suggestions, 2500 chars max
- detailed: Full analysis with trends, 3500 chars max

FORMAT:
📊 Weekly CEO Briefing — {business_name}
Week of [date range]

━━━ SECTION NAME ━━━
Content...

━━━ SECTION NAME ━━━
Content...

━━━━━━━━━━━━━━━━━━━━━━━━━━
Reply with a number:
1️⃣ Action one
2️⃣ Action two
...
"""

    user_prompt = f"""Generate a weekly CEO briefing based on this business data:

{json.dumps(data, indent=2, default=_serialize_for_json)}

Also return a JSON block at the end (after the briefing text) with this structure — put it AFTER the main message, separated by ===JSON===:
{{
  "observations": [
    {{"category": "financial|calls|emails|tasks|invoices", "type": "positive|negative|neutral", "text": "observation"}},
  ],
  "suggestions": [
    {{"priority": "high|medium|low", "text": "suggestion", "action_type": "optional action type"}}
  ],
  "action_options": [
    {{"number": 1, "label": "Action label", "type": "action_type", "config": {{}}}}
  ]
}}
"""

    if client:
        try:
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.4,
                max_tokens=2000,
            )
            full_response = response.choices[0].message.content.strip()

            if "===JSON===" in full_response:
                parts = full_response.split("===JSON===")
                briefing_text = parts[0].strip()
                try:
                    json_text = parts[1].strip()
                    json_text = json_text.replace("```json", "").replace("```", "").strip()
                    ai_analysis = json.loads(json_text)
                except (json.JSONDecodeError, IndexError):
                    ai_analysis = {"observations": [], "suggestions": [], "action_options": []}
            else:
                briefing_text = full_response
                ai_analysis = {"observations": [], "suggestions": [], "action_options": []}

            action_options = ai_analysis.get("action_options", [])
            return briefing_text, action_options, ai_analysis
        except Exception as e:
            logger.error(f"[Briefing Generator] Failed to generate weekly briefing: {e}")

    return generate_fallback_briefing(business_name, data), [], {}


async def generate_daily_pulse(
    business_name: str,
    owner_name: str,
    data: Dict[str, Any],
) -> str:
    """Generate a short daily morning pulse."""
    client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

    if client:
        try:
            owner_part = f", {owner_name}" if owner_name else ""
            system_prompt = f"""You produce a very short daily business pulse for {owner_part} at "{business_name}".

RULES:
- Maximum 800 characters — this is a quick morning update, not a report
- Use British English
- Start with "🌅 Good morning{owner_part}! Here's your daily pulse:"
- List only the most important 4-5 data points from yesterday/today
- End with "Anything you'd like me to handle?"
- Use emoji for visual scanning
- Only mention things that need attention or are noteworthy
"""
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": f"Generate a daily pulse from this data:\n{json.dumps(data, indent=2, default=_serialize_for_json)}",
                    },
                ],
                temperature=0.3,
                max_tokens=400,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"[Briefing Generator] Failed to generate daily pulse: {e}")

    return generate_fallback_pulse(business_name, data)


def generate_alert_message(
    alert_type: str,
    business_name: str,
    alert_data: Dict[str, Any],
) -> str:
    """Generate a contextual alert message.

    NOTE: This produces only the {{2}} alert content for the WhatsApp
    `alert` template. The {{3}} action options block (e.g. "Reply 1 to
    chase…") is built separately by the caller from
    `alert_data["action_option"]` so it doesn't render twice.
    """
    templates = {
        "call_transferred": (
            "📞 Call transferred from your AI receptionist\n\n"
            "Caller: {caller_name} ({caller_number})\n"
            "Reason: {reason}\n"
            "Time: {time}\n\n"
            "The caller has been informed someone will call back. "
            "A task has been created in your dashboard."
        ),
        "payment_received": (
            "💰 Payment received!\n\n"
            "{contact_name} paid £{amount:.2f}\n"
            "Invoice: {invoice_number}\n\n"
            "Remaining balance: £{remaining:.2f}"
        ),
        "low_balance": (
            "⚠️ Bank balance alert\n\n"
            "Your balance has dropped to £{balance:.2f}\n"
            "This is below your alert threshold of £{threshold:.2f}\n\n"
            "You might want to review recent expenses or follow up on unpaid invoices."
        ),
        "invoice_overdue": (
            "📋 Invoice now overdue\n\n"
            "{contact_name} — £{amount:.2f}\n"
            "Invoice: {invoice_number}\n"
            "Due date: {due_date} ({days_overdue} days ago)"
        ),
        "urgent_email": (
            "📧 Urgent email received\n\n"
            "From: {sender}\n"
            "Subject: {subject}\n"
            "Category: {category}"
        ),
        "kb_gap": (
            "🤖 Knowledge base gap detected\n\n"
            "Your AI receptionist has been asked about a topic {count} times "
            "this week that isn't covered in the knowledge base.\n\n"
            "Common query: \"{topic}\""
        ),
    }

    template = templates.get(
        alert_type, "ℹ️ Business Hero notification\n\n{message}"
    )
    try:
        return template.format(**alert_data)
    except KeyError as e:
        logger.warning(f"[Alert] Missing key in alert data: {e}")
        return f"ℹ️ Business Hero alert: {alert_type}\n\n{json.dumps(alert_data, default=_serialize_for_json)}"


def generate_fallback_briefing(business_name: str, data: Dict) -> str:
    """Simple fallback if GPT fails."""
    calls = data.get("calls", {})
    emails = data.get("emails", {})
    tasks = data.get("tasks", {})
    invoices = data.get("invoices", {})
    financial = data.get("financial", {})

    return (
        f"📊 Weekly Briefing — {business_name}\n\n"
        f"📞 Calls: {calls.get('total', 0)} (AI handled: {calls.get('handled_by_ai', 0)})\n"
        f"📧 Emails needing action: {emails.get('action_required', 0)}\n"
        f"✅ Open tasks: {tasks.get('open_total', 0)} ({tasks.get('open_high_priority', 0)} high priority)\n"
        f"💳 Unpaid invoices: £{invoices.get('unpaid_total', 0):.2f} ({invoices.get('overdue_count', 0)} overdue)\n"
        f"💰 Revenue: £{financial.get('revenue', 0):.2f} | Expenses: £{financial.get('expenses', 0):.2f}\n\n"
        "View details in your Business Hero dashboard."
    )


def generate_fallback_pulse(business_name: str, data: Dict) -> str:
    """Simple fallback for daily pulse."""
    calls = data.get("calls", {})
    emails = data.get("emails", {})
    tasks = data.get("tasks", {})

    return (
        "🌅 Good morning! Here's your daily pulse:\n\n"
        f"📞 Yesterday: {calls.get('total', 0)} calls\n"
        f"📧 {emails.get('action_required', 0)} emails need attention\n"
        f"✅ {tasks.get('open_total', 0)} open tasks ({tasks.get('open_high_priority', 0)} high priority)\n\n"
        "Anything you'd like me to handle?"
    )
