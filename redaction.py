"""Redaction helpers for diagnostics, test reports, and call traces."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


_CARD_KEYS = frozenset({"card_number", "number_on_card", "pan", "cardnumber"})
_CVV_KEYS = frozenset({"cvv", "cvc", "security_code", "securitycode"})
_IDENTITY_KEYS = frozenset(
    {"dob", "date_of_birth", "aadhaar", "aadhaar_last4", "pincode", "pin_code"}
)
_CARD_DIGIT_PATTERN = re.compile(r"(?<!\d)(?:\d[\s-]*){12,19}(?!\d)")
_CVV_TEXT_PATTERN = re.compile(
    r"\b(?:cvv|cvc|security\s+code)\b\s*(?:is|:|-)?\s*"
    r"[A-Za-z0-9](?:[A-Za-z0-9 -]{0,20})",
    re.IGNORECASE,
)


def mask_card_number(value: Any) -> str:
    """Return a report-safe masked card representation."""

    digits = re.sub(r"\D", "", str(value))
    if len(digits) < 4:
        return "[REDACTED_CARD]"
    return f"****{digits[-4:]}"


def redact_text(value: Any, secrets: Sequence[Any] = ()) -> str:
    """Redact supplied secrets and card-number-shaped digit sequences."""

    text = str(value)
    for secret in secrets:
        if secret is None:
            continue
        secret_text = str(secret)
        if secret_text:
            text = text.replace(secret_text, "[REDACTED]")
    text = _CVV_TEXT_PATTERN.sub("[REDACTED]", text)
    return _CARD_DIGIT_PATTERN.sub(lambda match: mask_card_number(match.group(0)), text)


def redact_for_report(value: Any) -> Any:
    """Recursively redact sensitive mapping keys without mutating the input."""

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return redact_for_report(model_dump())
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower().replace("-", "_")
            if normalized_key in _CVV_KEYS:
                # Omit CVV entirely from diagnostics rather than retaining a
                # sensitive field name/value pair in a report.
                continue
            elif normalized_key in _CARD_KEYS:
                redacted[key] = mask_card_number(item)
            elif normalized_key in _IDENTITY_KEYS:
                redacted[key] = "[REDACTED_IDENTITY]"
            else:
                redacted[key] = redact_for_report(item)
        return redacted
    if isinstance(value, tuple):
        return tuple(redact_for_report(item) for item in value)
    if isinstance(value, list):
        return [redact_for_report(item) for item in value]
    if isinstance(value, set):
        return {redact_for_report(item) for item in value}
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_call_trace(trace: Any) -> Any:
    """Alias documenting the intended use for recorded API call reports."""

    return redact_for_report(trace)


redact_payload = redact_for_report
