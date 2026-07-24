"""Deterministic fast-path parsers used by the conversation agent."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation


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


@dataclass(frozen=True)
class AmountCandidates:
    """Amount data recovered from one user turn.

    ``amount`` is only populated for a syntactically valid numeric amount.
    ``full_balance`` represents a request for the looked-up balance and is
    resolved by the agent because the balance is not known to the parser.
    """

    amount: Decimal | None = None
    full_balance: bool = False
    invalid: bool = False


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

_AMOUNT_CONTEXT_PATTERN = re.compile(
    r"\b(?:amount|pay|paying|payment|send|settle|remit|clear)\b|₹|\b(?:rs\.?|inr)\b",
    re.IGNORECASE,
)
_FULL_BALANCE_PATTERN = re.compile(
    r"\b(?:full|entire|total)\b[^.;,\n]{0,40}\b(?:amount|balance)\b|"
    r"\b(?:outstanding|remaining)\s+balance\b|"
    r"\b(?:clear|pay)\s+everything\b",
    re.IGNORECASE,
)
_NUMERIC_AMOUNT_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?P<value>[+-]?(?:(?:\d{1,3}(?:,\d{3})+)|\d+)(?:\.\d+)?|\.\d+)(?![A-Za-z0-9])"
)
_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_NUMBER_WORD_PATTERN = re.compile(
    r"\b(?:a|an|and|zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"hundred|thousand|lakh|million)(?:[ -]+(?:a|an|and|zero|one|two|three|"
    r"four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety|hundred|thousand|lakh|million))*\b",
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
                and not _looks_like_amount_input(user_input)
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


def _decimal_amount(value: str) -> Decimal | None:
    """Parse a numeric amount while preserving the user's precision."""

    if "," in value and re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", value) is None:
        return None
    try:
        amount = Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None
    if not amount.is_finite() or abs(amount.as_tuple().exponent) > 2:
        return None
    return amount


def _number_words_to_int(words: str) -> int | None:
    """Convert a small, unambiguous English number phrase to an integer."""

    tokens = re.findall(r"[a-z]+", words.lower())
    if not tokens:
        return None

    total = 0
    group = 0
    saw_number = False
    scales = {"thousand": 1_000, "lakh": 100_000, "million": 1_000_000}
    for token in tokens:
        if token in {"a", "an", "and"}:
            continue
        if token in _NUMBER_WORDS:
            group += _NUMBER_WORDS[token]
            saw_number = True
        elif token == "hundred":
            if group == 0:
                group = 1
            group *= 100
        elif token in scales:
            if group == 0:
                group = 1
            saw_number = True
            total += group * scales[token]
            group = 0
        else:
            return None
    if not saw_number:
        return None
    return total + group


def _looks_like_amount_input(value: str) -> bool:
    """Keep payment turns from being mistaken for a customer's name."""

    if _FULL_BALANCE_PATTERN.search(value):
        return True
    if not _AMOUNT_CONTEXT_PATTERN.search(value) and not re.search(
        r"\brupees?\b|\brs\.?\b|\binr\b", value, re.IGNORECASE
    ):
        return False
    return bool(
        _NUMERIC_AMOUNT_PATTERN.search(value)
        or _NUMBER_WORD_PATTERN.search(value)
    )


def parse_amount_input(
    user_input: str, *, allow_plain_number: bool = False
) -> AmountCandidates:
    """Extract a payment amount without interpreting unrelated identity digits.

    Plain numbers are accepted only while the agent is explicitly collecting
    an amount. Before that point, a number needs payment context such as
    ``pay``, ``amount``, a currency symbol, or ``rupees``.
    """

    if not isinstance(user_input, str) or not user_input.strip():
        return AmountCandidates()

    value = user_input.strip()
    if _FULL_BALANCE_PATTERN.search(value):
        return AmountCandidates(full_balance=True)

    has_context = bool(_AMOUNT_CONTEXT_PATTERN.search(value)) or bool(
        re.search(r"\brupees?\b|\brs\.?\b|\binr\b", value, re.IGNORECASE)
    )
    if not has_context and not allow_plain_number:
        return AmountCandidates()

    numeric_matches = list(_NUMERIC_AMOUNT_PATTERN.finditer(value))
    date_spans = [
        (match.start(), match.end()) for match in _DATE_PATTERN.finditer(value)
    ]
    # Digits that belong to a date or a labeled identity factor are not
    # payment amounts.
    numeric_matches = [
        match
        for match in numeric_matches
        if not any(
            match.start() >= start and match.end() <= end
            for start, end in date_spans
        )
        and not re.search(
            r"(?:aadhaar|aadhar|pin\s*code|pincode|postal\s+code)\b"
            r"\s*(?:(?:is|:)\s*)?$",
            value[max(0, match.start() - 30) : match.start()],
            re.IGNORECASE,
        )
    ]
    if len(numeric_matches) > 1:
        return AmountCandidates(invalid=True)
    if numeric_matches:
        amount = _decimal_amount(numeric_matches[0].group("value"))
        if amount is None:
            return AmountCandidates(invalid=True)
        return AmountCandidates(amount=amount)

    word_match = _NUMBER_WORD_PATTERN.search(value)
    if word_match and has_context:
        amount = _number_words_to_int(word_match.group(0))
        if amount is not None:
            return AmountCandidates(amount=Decimal(amount))

    if has_context:
        return AmountCandidates(invalid=True)
    return AmountCandidates()
