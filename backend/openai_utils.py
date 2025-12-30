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
    if not is_openai_available():
        return None
    
    if not transcript or not transcript.strip():
        return None
    
    try:
        from openai import OpenAI
        
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
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
            max_tokens=500,
            temperature=0.3
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        print(f"OpenAI summarization failed (non-critical): {type(e).__name__}")
        return None
