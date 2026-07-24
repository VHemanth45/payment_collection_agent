"""Deterministic fast-path parsers used by the conversation agent."""

from __future__ import annotations

import re


_ACCOUNT_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])A\s*C\s*C\s*[- ]?\s*\d{4}(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def normalize_account_id(value: str) -> str | None:
    """Return the canonical ``ACC####`` form, or ``None`` if invalid."""

    if not isinstance(value, str):
        return None

    compact = re.sub(r"[\s-]", "", value).upper()
    if re.fullmatch(r"ACC\d{4}", compact) is None:
        return None
    return compact


def extract_account_ids(user_input: str) -> tuple[str, ...]:
    """Extract distinct canonical account IDs from one user turn."""

    if not isinstance(user_input, str):
        return ()

    candidates: list[str] = []
    for match in _ACCOUNT_ID_PATTERN.finditer(user_input):
        account_id = normalize_account_id(match.group(0))
        if account_id is not None and account_id not in candidates:
            candidates.append(account_id)
    return tuple(candidates)


def contains_account_reference(user_input: str) -> bool:
    """Identify text that appears to be attempting to provide an account ID."""

    if not isinstance(user_input, str):
        return False

    return re.search(
        r"\b(?:account|account\s+(?:id|number)|acc(?:ount)?|a\s*c\s*c)\b",
        user_input,
        re.IGNORECASE,
    ) is not None
