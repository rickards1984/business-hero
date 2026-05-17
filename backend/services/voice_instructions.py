"""
Accent instruction templates for OpenAI Realtime + TTS APIs.

Per OpenAI's gpt-realtime-2 prompting guide, accent instructions hold much
more reliably when structured as their own dedicated section at the top of
the system prompt rather than woven into the main instructions.

These same blocks are also passed to `gpt-4o-mini-tts` via its `instructions`
parameter so the voice preview the owner hears matches the accent the
receptionist will speak with on real calls.

Adding a new accent? Add it to `ACCENT_INSTRUCTIONS` and reference it from a
voice preset in `voice_presets.py`.
"""
from __future__ import annotations

from typing import Literal

AccentName = Literal["british_standard", "british_rp", "american", "auto"]

ACCENT_INSTRUCTIONS = {
    "british_standard": (
        "## Accent\n"
        "Speak English with a natural, friendly British accent (Southern English / "
        "Home Counties).\n"
        "- Keep the accent stable from the first word to the last word of every reply.\n"
        "- Use natural British vowel shaping (e.g. \"bath\" with a long 'a', "
        "\"schedule\" as \"shed-yool\", \"can't\" as \"cahnt\").\n"
        "- Speak \u00a3 as \"pounds\" and use UK date formats (e.g. \"9th February\").\n"
        "- Prefer British vocabulary: enquiry, mobile, post, lovely, brilliant, "
        "whilst, towards, fortnight, holiday.\n"
        "- Do not exaggerate the accent — keep it clear and professional.\n"
        "- Do not switch to an American accent if the caller has one — your accent "
        "must stay stable across the entire conversation."
    ),
    "british_rp": (
        "## Accent\n"
        "Speak English with a refined, Received Pronunciation (RP) British accent — "
        "the precise, polished accent associated with formal British broadcasting.\n"
        "- Keep the accent stable from the first word to the last word of every reply.\n"
        "- Crisp consonants and clear vowel distinction.\n"
        "- Speak \u00a3 as \"pounds\" and use UK date formats (e.g. \"9th February\").\n"
        "- Use refined British vocabulary throughout.\n"
        "- Do not exaggerate — sound polished, not theatrical.\n"
        "- Do not switch to an American accent if the caller has one."
    ),
    "american": (
        "## Accent\n"
        "Speak English with a natural, friendly American accent (General American).\n"
        "- Keep the accent stable across the entire conversation.\n"
        "- Use $ as \"dollars\" if currency comes up, but only if appropriate to the "
        "business; otherwise follow the business's own preference.\n"
        "- Use American vocabulary (vacation, cell phone, mail, schedule as "
        "\"sked-jool\").\n"
        "- Do not exaggerate — sound professional and approachable.\n"
        "- Do not switch to a British accent if the caller has one."
    ),
    # Empty string for "auto" — let the model use its default voice characteristics.
    "auto": "",
}


def get_accent_instructions(accent: str) -> str:
    """Get the accent instruction block for an accent name. Returns "" if unknown."""
    return ACCENT_INSTRUCTIONS.get(accent, "")


def build_full_instructions(base_instructions: str, accent: str) -> str:
    """
    Combine the receptionist's base system prompt with an accent block.

    The accent block goes at the very top so the model treats it as a high-level
    constraint that overrides any conflicting habits picked up from later
    instructions or the caller's own accent.

    If accent is unknown or "auto", returns the base instructions unchanged.
    """
    accent_block = get_accent_instructions(accent)
    if not accent_block:
        return base_instructions
    return f"{accent_block}\n\n{base_instructions}"
