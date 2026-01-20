"""Stripe billing configuration helpers."""

import os
from typing import Dict, List, Tuple


def _get_env(name: str, fallback: List[str] | None = None) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    if fallback:
        for key in fallback:
            value = os.getenv(key)
            if value:
                return value
    return None


def _mask_value(value: str | None) -> str | None:
    if not value:
        return None
    prefix = value.split("_")[0]
    return f"{prefix}_***"


def get_stripe_config() -> Dict[str, str | Dict[str, str | None]]:
    return {
        "stripe_secret_key": _get_env("STRIPE_SECRET_KEY"),
        "stripe_webhook_secret": _get_env("STRIPE_WEBHOOK_SECRET"),
        "app_base_url": _get_env("APP_BASE_URL", ["FRONTEND_URL", "PUBLIC_BASE_URL"]),
        "prices": {
            "starter": _get_env("STRIPE_PRICE_STARTER", ["PRICE_ID_STARTER"]),
            "pro": _get_env("STRIPE_PRICE_PRO", ["PRICE_ID_PRO"]),
            "elite": _get_env("STRIPE_PRICE_ELITE", ["PRICE_ID_PREMIUM"]),
        },
    }


def validate_stripe_config() -> Tuple[bool, List[str]]:
    config = get_stripe_config()
    missing = []

    if not config.get("stripe_secret_key"):
        missing.append("STRIPE_SECRET_KEY")
    if not config.get("stripe_webhook_secret"):
        missing.append("STRIPE_WEBHOOK_SECRET")
    if not config.get("app_base_url"):
        missing.append("APP_BASE_URL")
    prices = config.get("prices", {})
    if not prices.get("starter"):
        missing.append("STRIPE_PRICE_STARTER")
    if not prices.get("pro"):
        missing.append("STRIPE_PRICE_PRO")
    if not prices.get("elite"):
        missing.append("STRIPE_PRICE_ELITE")

    return (len(missing) == 0), missing


def masked_stripe_config() -> Dict[str, str | Dict[str, str | None]]:
    config = get_stripe_config()
    return {
        "stripe_secret_key": _mask_value(config.get("stripe_secret_key")),
        "stripe_webhook_secret": _mask_value(config.get("stripe_webhook_secret")),
        "app_base_url": config.get("app_base_url"),
        "prices": config.get("prices", {}),
    }
