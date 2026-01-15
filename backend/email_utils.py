import os
from cryptography.fernet import Fernet, InvalidToken


_EMAIL_ENCRYPTION_KEY = os.getenv("EMAIL_ENCRYPTION_KEY")


def _get_fernet() -> Fernet:
    if not _EMAIL_ENCRYPTION_KEY:
        raise ValueError("EMAIL_ENCRYPTION_KEY is not configured")
    return Fernet(_EMAIL_ENCRYPTION_KEY.encode("utf-8"))


def encrypt_secret(plain: str) -> str:
    """Encrypt a plaintext secret string."""
    fernet = _get_fernet()
    token = fernet.encrypt(plain.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(enc: str) -> str:
    """Decrypt an encrypted secret string."""
    fernet = _get_fernet()
    try:
        plain = fernet.decrypt(enc.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("Invalid encrypted secret") from exc
    return plain.decode("utf-8")
{
  "cells": [],
  "metadata": {
    "language_info": {
      "name": "python"
    }
  },
  "nbformat": 4,
  "nbformat_minor": 2
}