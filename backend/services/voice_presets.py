"""
Receptionist voice presets.

A voice preset is a (base_voice, accent) tuple plus display metadata. The
receptionist's `voice_preset_id` column resolves to one of these. We never
store base_voice + accent as separate user-facing fields — the preset is
the unit users pick and we store.

VERIFIED column:
- `verified=True`  → voice has been observed working on gpt-realtime-2 in
   production. Safe to recommend.
- `verified=False` → newer voice (Marin, Cedar) advertised by OpenAI but not
   yet validated end-to-end on our path. We log a warning if selected; the
   call may or may not work depending on OpenAI's current support.

DEFAULT for new UK businesses: `shimmer_british` (preserves the existing
female-default gender expectation; users can switch to echo_british with
one click).
"""
from __future__ import annotations

from typing import Dict, List, Optional

# Voices that we have confirmed working on the realtime API path. Used as
# the safety net when a preset references an experimental voice.
KNOWN_STABLE_REALTIME_VOICES = {
    "shimmer", "alloy", "echo", "ash", "ballad", "coral", "sage", "verse", "nova",
}

DEFAULT_PRESET_ID = "shimmer_british"
DEFAULT_FALLBACK_VOICE = "echo"


VOICE_PRESETS: List[Dict] = [
    # ---- British (Standard) — the default family for UK businesses ----
    {
        "id": "shimmer_british",
        "label": "Shimmer \u2014 British (Female)",
        "description": "Warm, clear, friendly. The most popular voice for UK businesses.",
        "base_voice": "shimmer",
        "accent": "british_standard",
        "gender": "female",
        "accent_group": "British",
        "verified": True,
        "default_for_uk": True,
        "recommended": True,
    },
    {
        "id": "echo_british",
        "label": "Echo \u2014 British (Male)",
        "description": "Smooth, calm, measured. Excellent for professional services.",
        "base_voice": "echo",
        "accent": "british_standard",
        "gender": "male",
        "accent_group": "British",
        "verified": True,
        "recommended": True,
    },
    {
        "id": "sage_british",
        "label": "Sage \u2014 British (Female, calm)",
        "description": "Calm and authoritative. Great for legal, finance, estate agents.",
        "base_voice": "sage",
        "accent": "british_standard",
        "gender": "female",
        "accent_group": "British",
        "verified": True,
    },
    {
        "id": "verse_british",
        "label": "Verse \u2014 British (Male, friendly)",
        "description": "Dynamic and engaging. Great for fitness, hospitality, events.",
        "base_voice": "verse",
        "accent": "british_standard",
        "gender": "male",
        "accent_group": "British",
        "verified": True,
    },
    {
        "id": "ballad_british",
        "label": "Ballad \u2014 British (Female, warm)",
        "description": "Warm and expressive with a natural storytelling quality.",
        "base_voice": "ballad",
        "accent": "british_standard",
        "gender": "female",
        "accent_group": "British",
        "verified": True,
    },
    {
        "id": "coral_british",
        "label": "Coral \u2014 British (Female, bright)",
        "description": "Bright, energetic, personable. Excellent for retail and hospitality.",
        "base_voice": "coral",
        "accent": "british_standard",
        "gender": "female",
        "accent_group": "British",
        "verified": True,
    },
    {
        "id": "ash_british",
        "label": "Ash \u2014 British (Male, soft)",
        "description": "Soft-spoken and thoughtful. Great for advisory or consultancy.",
        "base_voice": "ash",
        "accent": "british_standard",
        "gender": "male",
        "accent_group": "British",
        "verified": True,
    },
    {
        "id": "alloy_british",
        "label": "Alloy \u2014 British (Neutral)",
        "description": "Balanced and versatile with a smooth delivery.",
        "base_voice": "alloy",
        "accent": "british_standard",
        "gender": "neutral",
        "accent_group": "British",
        "verified": True,
    },

    # ---- British (RP) — premium / formal ----
    {
        "id": "verse_rp",
        "label": "Verse \u2014 British RP (Premium)",
        "description": "Refined Received Pronunciation. Premium and polished.",
        "base_voice": "verse",
        "accent": "british_rp",
        "gender": "male",
        "accent_group": "British RP",
        "verified": True,
    },
    {
        "id": "sage_rp",
        "label": "Sage \u2014 British RP (Premium)",
        "description": "Refined RP, calm authority. Ideal for premium professional services.",
        "base_voice": "sage",
        "accent": "british_rp",
        "gender": "female",
        "accent_group": "British RP",
        "verified": True,
    },

    # ---- American ----
    {
        "id": "echo_american",
        "label": "Echo \u2014 American (Male)",
        "description": "Smooth, calm, measured American voice.",
        "base_voice": "echo",
        "accent": "american",
        "gender": "male",
        "accent_group": "American",
        "verified": True,
    },
    {
        "id": "shimmer_american",
        "label": "Shimmer \u2014 American (Female)",
        "description": "Warm and clear, American.",
        "base_voice": "shimmer",
        "accent": "american",
        "gender": "female",
        "accent_group": "American",
        "verified": True,
    },
    {
        "id": "nova_american",
        "label": "Nova \u2014 American (Female)",
        "description": "Bright, modern American voice.",
        "base_voice": "nova",
        "accent": "american",
        "gender": "female",
        "accent_group": "American",
        "verified": True,
    },
    {
        "id": "alloy_american",
        "label": "Alloy \u2014 American (Neutral)",
        "description": "Balanced and versatile, American.",
        "base_voice": "alloy",
        "accent": "american",
        "gender": "neutral",
        "accent_group": "American",
        "verified": True,
    },

    # ---- Premium new voices (Marin, Cedar) — not yet end-to-end verified ----
    {
        "id": "cedar_british",
        "label": "Cedar \u2014 British (Premium, new)",
        "description": "Newer premium voice from OpenAI. Experimental — please report any issues.",
        "base_voice": "cedar",
        "accent": "british_standard",
        "gender": "male",
        "accent_group": "British",
        "verified": False,
    },
    {
        "id": "marin_british",
        "label": "Marin \u2014 British (Premium, new)",
        "description": "Newer premium voice from OpenAI. Experimental — please report any issues.",
        "base_voice": "marin",
        "accent": "british_standard",
        "gender": "female",
        "accent_group": "British",
        "verified": False,
    },
]


def get_preset_by_id(preset_id: Optional[str]) -> Optional[Dict]:
    """Look up a preset by id. Returns None if unknown."""
    if not preset_id:
        return None
    for p in VOICE_PRESETS:
        if p["id"] == preset_id:
            return p
    return None


def resolve_preset(
    preset_id: Optional[str],
    legacy_voice: Optional[str] = None,
) -> Dict:
    """
    Resolve the active preset for a receptionist.

    Resolution order:
      1. If `preset_id` is given and valid → use it.
      2. If `legacy_voice` is given, map "<voice>" → "<voice>_british" if such
         a preset exists.
      3. Otherwise, return the global default (`shimmer_british`).
    """
    p = get_preset_by_id(preset_id)
    if p:
        return p
    if legacy_voice:
        mapped = get_preset_by_id(f"{legacy_voice}_british")
        if mapped:
            return mapped
    fallback = get_preset_by_id(DEFAULT_PRESET_ID)
    if fallback:
        return fallback
    # Hardcoded last resort — should never hit
    return {
        "id": DEFAULT_PRESET_ID,
        "label": "Shimmer \u2014 British (Female)",
        "base_voice": "shimmer",
        "accent": "british_standard",
        "verified": True,
    }


def safe_realtime_voice(preset: Dict) -> str:
    """
    Return a base_voice that's known to work on the realtime API path.
    Used as a defensive fallback when a preset references an experimental
    voice (Marin, Cedar) and the call handler wants safety.

    Note: this is currently used for LOGGING ONLY — we still pass the
    preset's base_voice through to OpenAI. If OpenAI rejects it, the call
    will fail and Railway logs will show why. Once Marin/Cedar are
    confirmed working on gpt-realtime-2 we'll set verified=True for them.
    """
    base = preset.get("base_voice", DEFAULT_FALLBACK_VOICE)
    if base in KNOWN_STABLE_REALTIME_VOICES:
        return base
    return DEFAULT_FALLBACK_VOICE
