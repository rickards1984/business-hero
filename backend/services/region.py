"""
Region and locale resolver — spec Item 5.

One place that answers "what does money, dates and tax look like for this
business". Everything else reads from here rather than hardcoding en-GB.

This module is the seam, not the rollout. Wiring the PDFs and the frontend to
it is separate work; what matters now is that there is exactly one definition
of each regional default, so adding a third region later is an edit here and
nowhere else.
"""
from decimal import Decimal

UK = "UK"
US = "US"
DEFAULT_REGION = UK

# UK term -> US term. ONE map. No ternaries scattered through the codebase.
TERMS = {
    "Quote": "Estimate",
    "VAT": "Sales Tax",
    "VAT Number": "Tax ID",
    "Labour": "Labor",
    "Postcode": "ZIP Code",
    "Organisation": "Organization",
    "Cheque": "Check",
    "Turnover": "Revenue",
    "inc. VAT": "incl. tax",
    "Sole trader": "Sole proprietor",
}

# The single source of the regional defaults. Both profiles MUST carry the
# same keys — a caller reading a key that only one region defines is a
# KeyError waiting for the first US signup.
_PROFILES = {
    UK: {
        "region": UK,
        "currency": "GBP",
        "locale": "en-GB",
        "date_format": "DD/MM/YYYY",
        "tax_label": "VAT",
        "default_tax_rate": Decimal("20"),
        "quote_noun": "Quote",
    },
    US: {
        "region": US,
        "currency": "USD",
        "locale": "en-US",
        "date_format": "MM/DD/YYYY",
        "tax_label": "Sales Tax",
        # 0 is a real answer here, not "unset". US sales tax is entered per
        # job by the contractor; Business Hero never determines taxability.
        "default_tax_rate": Decimal("0"),
        "quote_noun": "Estimate",
    },
}


def normalise(region):
    """Map anything a caller might hold to a known region code.

    Existing businesses have no region set, so None must land on UK — no
    behaviour change for anyone already using the product.
    """
    if not isinstance(region, str):
        return DEFAULT_REGION
    candidate = region.strip().upper()
    return candidate if candidate in _PROFILES else DEFAULT_REGION


def resolve(region):
    """Return the full profile for a region. Always a complete profile."""
    # A copy, so a caller mutating what it gets back cannot poison the next
    # caller's currency.
    return dict(_PROFILES[normalise(region)])


def term(word, region):
    """Translate one UK term for the given region. Unmapped words pass through."""
    if normalise(region) == US:
        return TERMS.get(word, word)
    return word
