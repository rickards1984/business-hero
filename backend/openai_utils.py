"""Optional OpenAI utilities for call summarization."""

import os
from typing import Optional


def is_openai_available() -> bool:
    """Check if OpenAI API key is configured."""
    return bool(os.getenv("OPENAI_API_KEY"))


async def generate_call_summary(transcript: str) -> Optional[str]:
    """
    Generate a 5-bullet summary of a call transcript using OpenAI.
    Returns None if OpenAI is not configured or if there's an error.
    """
    from services import ai_chat
    if not ai_chat.available("call_summary"):     # AI-1d: a key for any model chosen for it
        return None
    
    if not transcript or not transcript.strip():
        return None
    # PROFIT-1: a summary of a call already finished is non-essential (the live
    # call is what's essential): at the kill switch, no summary (Codex review 3).
    from services import profit_guard
    if not profit_guard.permits("call_summary"):
        return None
    
    try:
        from services.ai_text import acomplete   # AI-1d: off the event loop, any provider
        
        from services import profit_guard   # PROFIT-1
        with profit_guard.attributed(None, "call_summary"):
            reply = await acomplete(
                "call_summary", max_tokens=500, temperature=0.3,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that summarizes phone call transcripts. Create a concise summary with exactly 5 bullet points highlighting the key points, action items, and outcomes from the call."
                    },
                    {
                        "role": "user",
                        "content": f"Please summarize this call transcript in 5 bullet points:\n\n{transcript}"
                    }
                ],
            )
        
        return reply.content
    
    except Exception as e:
        print(f"AI summarization failed (non-critical): {type(e).__name__}")
        return None
