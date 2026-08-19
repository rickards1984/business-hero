"""
Invoice numbering — spec Item 1.

Replaces `COUNT(*) + 1` over a table that also holds provider-synced invoices.

HMRC and IRS both require unique sequential numbering. The old scheme could
reuse a number after a delete, could hand two concurrent requests the same
number, and shared a namespace with Xero — whose default format (INV-0001) is
character-identical to the app's. New Body already holds a Xero INV-0001.

COUNTER CONTRACT: `quote_settings.next_invoice_number` holds the NEXT number
to ISSUE, exactly like `next_quote_number` beside it. So a business seeded at
2 issues INV-0002 next.
"""
import logging
import re

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger("invoice_numbering")

DEFAULT_PREFIX = "INV-"
PAD = 4

# ONE atomic statement. Postgres executes a single UPDATE indivisibly under a
# row lock, so two concurrent callers cannot read the same value. A SELECT
# followed by a separate UPDATE gives no such guarantee — that is the race
# this replaces. RETURNING gives back the pre-increment value, which is the
# number being issued.
_ALLOCATE = text("""
    UPDATE quote_settings
       SET next_invoice_number = next_invoice_number + 1
     WHERE business_id = :bid
 RETURNING next_invoice_number - 1 AS next_invoice_number, invoice_prefix
""")

# Created with next_invoice_number = 1 so the UPDATE above immediately issues
# 1 and leaves 2 behind. ON CONFLICT makes two concurrent creators safe.
_CREATE_SETTINGS = text("""
    INSERT INTO quote_settings (business_id, next_invoice_number, invoice_prefix)
    VALUES (:bid, 1, 'INV-')
    ON CONFLICT (business_id) DO NOTHING
""")

# Seeds from app-generated rows ONLY. Seeding from max(invoice_number) across
# all rows would set New Body's counter to 1004 off three legacy CSV invoices
# it never issued, and would let Xero's independent series steer the app's.
_SEED = text(r"""
    SELECT max((regexp_replace(invoice_number, '\D', '', 'g'))::bigint) AS max_suffix
      FROM invoices
     WHERE business_id = :bid
       AND source = 'quote'
       AND external_source IS NULL
       AND invoice_number ~ '[0-9]'
""")

_READ_PREFIX = text("""
    SELECT invoice_prefix FROM quote_settings WHERE business_id = :bid
""")

_READ_NAME = text("""
    SELECT name FROM businesses WHERE id = :bid
""")

# Words that carry no identity — a suggestion of "L-" for "Ltd" helps nobody.
_NOISE_WORDS = {
    "ltd", "limited", "llc", "llp", "inc", "incorporated", "plc", "co",
    "company", "group", "holdings", "services", "solutions", "the", "and",
    "of", "for", "&",
}


def format_number(prefix, number):
    """Zero-pad to 4, but never truncate — 10000 stays INV-10000."""
    return f"{prefix or DEFAULT_PREFIX}{int(number):0{PAD}d}"


def next_invoice_number(session, business_id):
    """Allocate the next number for a business, atomically.

    Businesses with no settings row get one created on demand.
    """
    row = session.execute(_ALLOCATE, {"bid": business_id}).fetchone()
    if row is None:
        session.execute(_CREATE_SETTINGS, {"bid": business_id})
        row = session.execute(_ALLOCATE, {"bid": business_id}).fetchone()
    if row is None:
        # The row exists but the UPDATE still matched nothing. Rather than
        # invent a number that might collide, refuse.
        raise RuntimeError(
            f"could not allocate an invoice number for business {business_id}"
        )
    return format_number(row[1], row[0])


def allocate(session, business_id, insert_fn, max_retries=5):
    """Allocate a number, insert with it, and retry the NEXT number on a clash.

    A unique violation means someone else took the number between our
    allocation and our insert. Taking the next one is correct and invisible to
    the user; a 500 is neither.

    Anything that is not an IntegrityError is not a numbering problem — it is
    re-raised immediately rather than retried, because retrying burns invoice
    numbers and leaves permanent gaps in a sequence that has to be sequential.
    """
    last_error = None
    for attempt in range(max_retries):
        number = next_invoice_number(session, business_id)
        try:
            insert_fn(number)
            return number
        except IntegrityError as exc:
            last_error = exc
            logger.warning(
                "invoice number %s collided for business %s (attempt %d/%d)",
                number, business_id, attempt + 1, max_retries,
            )
    raise last_error


def seed_value_for_business(session, business_id):
    """The migration seed: max app-generated suffix + 1, or 1 if there are none."""
    row = session.execute(_SEED, {"bid": business_id}).fetchone()
    highest = row[0] if row is not None else None
    return int(highest) + 1 if highest is not None else 1


def _initials_prefix(business_name):
    """Derive a prefix from the business's OWN name — never Business Hero's.

    The invoice series belongs to the customer and appears on documents their
    clients read. Suggesting our initials would put our branding on their
    paperwork, which is not ours to do.

    "Multi Skilled Contractors LTD" -> "MSC-"
    "New Body Gym"                  -> "NBG-"
    "Hendersons"                    -> "HEN-"
    """
    if not isinstance(business_name, str):
        return None
    words = [w for w in re.split(r"[^A-Za-z0-9]+", business_name) if w]
    meaningful = [w for w in words if w.lower() not in _NOISE_WORDS] or words
    if not meaningful:
        return None
    if len(meaningful) == 1:
        stem = "".join(ch for ch in meaningful[0] if ch.isalnum())[:3]
    else:
        stem = "".join(w[0] for w in meaningful[:3])
    stem = stem.upper()
    return f"{stem}-" if stem else None


def _bump(current):
    """Fallback: append or increment a digit on the existing prefix.

    "INV-" -> "INV2-", "INV2-" -> "INV3-". Always different from the input, so
    the caller always has something to offer.
    """
    base = (current or DEFAULT_PREFIX).rstrip("-")
    match = re.match(r"^(.*?)(\d+)$", base)
    if match:
        stem, digits = match.group(1), int(match.group(2))
        return f"{stem}{digits + 1}-"
    return f"{base}2-"


def _suggest_prefix(business_name, current):
    """Prefer the business's own initials; fall back to bumping what they have."""
    candidate = _initials_prefix(business_name)
    if candidate and candidate.upper() != (current or "").strip().upper():
        return candidate
    return _bump(current)


def detect_prefix_collision(session, business_id, provider_invoice_numbers):
    """Warn when a provider's numbering shares the business's prefix.

    WARNS. NEVER CHANGES ANYTHING. An invoice series is the customer's own
    record and silently renumbering it is the one thing that would be
    unforgivable — so this issues SELECTs only and returns a suggestion the
    user has to accept.
    """
    numbers = [n for n in (provider_invoice_numbers or []) if isinstance(n, str)]
    if not numbers:
        return None

    row = session.execute(_READ_PREFIX, {"bid": business_id}).fetchone()
    prefix = (row[0] if row is not None else None) or DEFAULT_PREFIX

    pattern = re.compile("^" + re.escape(prefix), re.IGNORECASE)
    clashing = [n for n in numbers if pattern.match(n)]
    if not clashing:
        return None

    name_row = session.execute(_READ_NAME, {"bid": business_id}).fetchone()
    business_name = name_row[0] if name_row is not None else None

    return {
        "collision": True,
        "current_prefix": prefix,
        "suggested_prefix": _suggest_prefix(business_name, prefix),
        "examples": clashing[:5],
        "message": (
            f"This provider already issues invoices starting with '{prefix}', "
            f"the same prefix your invoices use (for example {clashing[0]}). "
            f"Both series will keep working, but your records will be easier "
            f"to tell apart if you change your prefix. Nothing has been "
            f"changed — this is your invoice series to decide about."
        ),
    }
