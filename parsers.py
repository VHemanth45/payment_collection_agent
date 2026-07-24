"""Deterministic fast-path parsers used by the conversation agent."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date


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


@dataclass(frozen=True)
class IdentityCandidates:
    """Fields deterministically recovered from one identity turn."""

    name: str | None = None
    dob: str | None = None
    aadhaar_last4: str | None = None
    pincode: str | None = None
    invalid_dob: bool = False
    invalid_aadhaar: bool = False
    invalid_pincode: bool = False


_DOB_LABEL_PATTERN = re.compile(
    r"\b(?:my\s+)?(?:date\s+of\s+birth|dob)\b", re.IGNORECASE
)
_DATE_PATTERN = re.compile(
    r"(?:"
    r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|"
    r"\b\d{1,2}(?:st|nd|rd|th)?[-/]\d{1,2}[-/]\d{2,4}\b|"
    r"\b\d{1,2}(?:st|nd|rd|th)?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{2,4}\b|"
    r"\b(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+\d{2,4}\b"
    r")",
    re.IGNORECASE,
)
_MONTHS = {
    month.lower(): number
    for number, month in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}
_NAME_LABEL_PATTERN = re.compile(
    r"\b(?:my\s+)?(?:full\s+)?name\s*(?:is|:)\s*"
    r"(?P<value>[^,;]+?)(?=\s*,?\s*(?:and\s+)?(?:my\s+)?(?:date\s+of\s+birth|dob|"
    r"aadhaar|aadhar|pin\s*code|pincode)\b|$)",
    re.IGNORECASE,
)
_I_AM_NAME_PATTERN = re.compile(
    r"\bI\s+am\s+(?P<value>[^,;]+?)(?=\s*,?\s*(?:and\s+)?(?:my\s+)?(?:date\s+of\s+birth|"
    r"dob|aadhaar|aadhar|pin\s*code|pincode)\b|$)",
    re.IGNORECASE,
)
_AADHAAR_PATTERN = re.compile(
    r"\b(?:aadhaar|aadhar)\b[^,;]*?(?P<digits>\d(?:[\s-]*\d){0,15})",
    re.IGNORECASE,
)
_PINCODE_PATTERN = re.compile(
    r"\b(?:pin\s*code|pincode|postal\s+code)\b[^,;]*?(?P<digits>\d(?:[\s-]*\d){0,15})",
    re.IGNORECASE,
)


def clean_name(value: str) -> str:
    """Apply harmless name-input cleanup without changing letter case."""

    return " ".join(value.strip(" \t\r\n,;:.\"'").split())


def _parse_date_expression(expression: str) -> str | None:
    value = expression.strip().replace(",", "")
    value = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value, flags=re.IGNORECASE)

    match = re.fullmatch(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value)
    if match:
        year, month, day = (int(part) for part in match.groups())
    else:
        match = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})", value)
        if match:
            day, month, year = (int(part) for part in match.groups())
        else:
            match = re.fullmatch(
                r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{2,4})", value
            )
            if match:
                day, month_name, year = match.groups()
                month = _MONTHS.get(month_name.lower(), 0)
                day, year = int(day), int(year)
            else:
                match = re.fullmatch(
                    r"([A-Za-z]+)\s+(\d{1,2})\s+(\d{2,4})", value
                )
                if not match:
                    return None
                month_name, day, year = match.groups()
                month = _MONTHS.get(month_name.lower(), 0)
                day, year = int(day), int(year)

    if year < 100 or month not in range(1, 13):
        return None
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _extract_dob(user_input: str) -> tuple[str | None, bool]:
    match = _DATE_PATTERN.search(user_input)
    if match:
        expression = match.group(0)
        canonical = _parse_date_expression(expression)
        return canonical, canonical is None
    return None, bool(_DOB_LABEL_PATTERN.search(user_input))


def _extract_digit_factor(
    pattern: re.Pattern[str], user_input: str, expected_length: int
) -> tuple[str | None, bool]:
    match = pattern.search(user_input)
    if not match:
        return None, False
    digits = re.sub(r"\D", "", match.group("digits"))
    if len(digits) != expected_length:
        return None, True
    return digits, False


def parse_identity_input(user_input: str) -> IdentityCandidates:
    """Extract identity candidates without guessing unlabeled digit factors."""

    if not isinstance(user_input, str):
        return IdentityCandidates()

    name_match = _NAME_LABEL_PATTERN.search(user_input) or _I_AM_NAME_PATTERN.search(
        user_input
    )
    name = clean_name(name_match.group("value")) if name_match else None

    dob, invalid_dob = _extract_dob(user_input)
    aadhaar, invalid_aadhaar = _extract_digit_factor(
        _AADHAAR_PATTERN, user_input, 4
    )
    pincode, invalid_pincode = _extract_digit_factor(
        _PINCODE_PATTERN, user_input, 6
    )

    if name is None:
        date_match = _DATE_PATTERN.search(user_input)
        if date_match:
            prefix = user_input[: date_match.start()].strip(" \t,;:-")
            prefix = re.sub(
                r"(?:,|\band\s+)?\s*(?:my\s+)?(?:date\s+of\s+birth|dob)\s*(?:is|:)?\s*$",
                "",
                prefix,
                flags=re.IGNORECASE,
            ).strip(" \t,;:-")
            if prefix and not re.fullmatch(
                r"(?:date\s+of\s+birth|dob)\s*(?:is|:)?",
                prefix.strip(),
                re.IGNORECASE,
            ):
                name = clean_name(re.sub(r"\band\s*$", "", prefix, flags=re.I))
        else:
            factor_match = re.search(
                r"\b(?:aadhaar|aadhar|pin\s*code|pincode|postal\s+code)\b",
                user_input,
                re.IGNORECASE,
            )
            if factor_match:
                prefix = user_input[: factor_match.start()].strip(" \t,;:-")
                if prefix and not re.fullmatch(r"(?:my|the)", prefix, re.IGNORECASE):
                    name = clean_name(
                        re.sub(r"\band\s*$", "", prefix, flags=re.I)
                    )
            if (
                name is None
                and not factor_match
                and re.search(r"[A-Za-z]", user_input)
                and not (
                    extract_account_ids(user_input)
                    or contains_account_reference(user_input)
                )
                and user_input.strip()
            ):
                name = clean_name(user_input)

    return IdentityCandidates(
        name=name or None,
        dob=dob,
        aadhaar_last4=aadhaar,
        pincode=pincode,
        invalid_dob=invalid_dob,
        invalid_aadhaar=invalid_aadhaar,
        invalid_pincode=invalid_pincode,
    )
