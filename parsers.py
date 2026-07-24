"""Deterministic fast-path parsers used by the conversation agent."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import ValidationError

from models import (
    AadhaarLast4,
    AccountId,
    AmountCandidates,
    CardCandidates,
    IdentityCandidates,
    IdentityDate,
    NumericAmount,
    Pincode,
)

_ACCOUNT_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])A\s*C\s*C\s*[- ]?\s*\d{4}(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def normalize_account_id(value: str) -> str | None:
    """Return the canonical ``ACC####`` form, or ``None`` if invalid."""

    try:
        return AccountId(value=value).value
    except ValidationError:
        return None


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
        return IdentityDate(value=date(year, month, day)).value.isoformat()
    except (ValueError, ValidationError):
        return None


def _extract_dob(user_input: str) -> tuple[str | None, bool]:
    match = _DATE_PATTERN.search(user_input)
    if match:
        # Card expiry dates are structurally date-like but are not identity
        # data.  This matters when the hybrid pipeline runs all fast-path
        # parsers on every turn.
        prefix = user_input[: match.start()]
        if re.search(
            r"\b(?:exp(?:iry|iration)?|expires?|valid\s*(?:thru|through))\b"
            r"\s*(?:is|:|-)?\s*$",
            prefix,
            re.IGNORECASE,
        ):
            return None, False
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
    try:
        if expected_length == 4:
            return AadhaarLast4(value=digits).value, False
        if expected_length == 6:
            return Pincode(value=digits).value, False
    except ValidationError:
        return None, True
    return None, True


def parse_identity_input(
    user_input: str, *, allow_unlabeled_factors: bool = False
) -> IdentityCandidates:
    """Extract identity candidates, optionally using the current prompt context.

    Bare four- or six-digit values are only accepted when the caller has
    explicitly established that the conversation is collecting a verification
    factor.  This keeps general turns from guessing what an unlabeled number
    means while making the guided CLI natural to use.
    """

    if not isinstance(user_input, str):
        return IdentityCandidates()

    name_match = _NAME_LABEL_PATTERN.search(user_input)
    if name_match and re.search(
        r"\b(?:cardholder|name\s+on\s+card)\s*$",
        user_input[: name_match.start()],
        re.IGNORECASE,
    ):
        name_match = None
    name_match = name_match or _I_AM_NAME_PATTERN.search(user_input)
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
            if re.search(
                r"\b(?:exp(?:iry|iration)?|expires?|valid\s*(?:thru|through))\b\s*$",
                prefix,
                re.IGNORECASE,
            ):
                prefix = ""
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
                and not re.search(
                    r"\b(?:cardholder|card\s*(?:number|no\.?|#)|number\s+on\s+card|"
                    r"cvv|cvc|security\s+code|exp(?:iry|iration)?|expires?|"
                    r"valid\s*(?:thru|through))\b",
                    user_input,
                    re.IGNORECASE,
                )
                and re.search(r"[A-Za-z]", user_input)
                and not (
                    extract_account_ids(user_input)
                    or contains_account_reference(user_input)
                )
                and not _looks_like_amount_input(user_input)
                and user_input.strip()
            ):
                name = clean_name(user_input)

    if allow_unlabeled_factors and re.fullmatch(r"\s*\d+\s*", user_input):
        digits = user_input.strip()
        if len(digits) == 4:
            aadhaar = digits
            invalid_aadhaar = False
        elif len(digits) == 6:
            pincode = digits
            invalid_pincode = False
        else:
            invalid_aadhaar = True

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
        return NumericAmount(value=value.replace(",", "")).value
    except (InvalidOperation, ValidationError):
        return None


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


# Card parsing is intentionally label-aware.  This prevents account IDs,
# dates, pincodes, and amounts in an earlier turn from being mistaken for
# payment credentials while still allowing a complete card turn in prose.
_CARD_NUMBER_LABEL_PATTERN = re.compile(
    r"\b(?:card\s*(?:number|no\.?|#)|number\s+on\s+card)\b\s*"
    r"(?:is|:|-)?\s*(?P<value>[0-9][0-9\s-]*)",
    re.IGNORECASE,
)
_RAW_CARD_NUMBER_PATTERN = re.compile(
    r"(?<!\d)(?:\d[\s-]*){12,19}(?!\d)"
)
_CARDHOLDER_LABEL_PATTERN = re.compile(
    r"\b(?:cardholder(?:\s+name)?|name\s+on\s+card)\b\s*"
    r"(?:is|:|-)?\s*(?P<value>.*?)"
    r"(?=\s*(?:[,;]|\b(?:card\s*(?:number|no\.?|#)|number\s+on\s+card|"
    r"cvv|cvc|security\s+code|exp(?:iry|iration)?|expires?|valid\s*"
    r"(?:thru|through))\b)|$)",
    re.IGNORECASE,
)
_CARD_FIELD_LABEL_PATTERN = re.compile(
    r"\b(?:card\s*(?:number|no\.?|#)|number\s+on\s+card|"
    r"cardholder(?:\s+name)?|name\s+on\s+card|cvv|cvc|security\s+code|"
    r"exp(?:iry|iration)?|expires?|valid\s*(?:thru|through))\b",
    re.IGNORECASE,
)
_CVV_LABEL_PATTERN = re.compile(
    r"\b(?:cvv|cvc|security\s+code)\b\s*(?:is|:|-)?\s*(?P<value>.*?)"
    r"(?=\s*(?:[,;]|\b(?:card\s*(?:number|no\.?|#)|number\s+on\s+card|"
    r"cardholder(?:\s+name)?|name\s+on\s+card|exp(?:iry|iration)?|expires?|"
    r"valid\s*(?:thru|through))\b)|$)",
    re.IGNORECASE,
)
_EXPIRY_LABEL_PATTERN = re.compile(
    r"\b(?:exp(?:iry|iration)?|expires?|valid\s*(?:thru|through))\b",
    re.IGNORECASE,
)
_EXPIRY_EXPRESSION_PATTERN = re.compile(
    r"(?:"
    r"\d{1,4}\s*[/\-]\s*\d{1,4}|"
    r"\d{1,2}\s+\d{4}|"
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+\d{2,4}"
    r")",
    re.IGNORECASE,
)
_EXPIRY_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_DIGIT_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}


def normalize_card_number(value: str) -> str | None:
    """Normalize and Luhn-validate a card number, or return ``None``."""

    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[\s-]", "", value)
    if not normalized.isdigit() or not 12 <= len(normalized) <= 19:
        return None
    checksum = 0
    doubled = False
    for digit in reversed(normalized):
        number = int(digit)
        if doubled:
            number *= 2
            if number > 9:
                number -= 9
        checksum += number
        doubled = not doubled
    return normalized if checksum % 10 == 0 else None


def _parse_spoken_cvv(value: str) -> str | None:
    compact = value.strip().lower()
    if re.fullmatch(r"[0-9](?:[\s-]*[0-9])*", compact):
        digits = re.sub(r"\D", "", compact)
    else:
        words = re.findall(r"[a-z]+", compact)
        if not words or any(word not in _DIGIT_WORDS for word in words):
            return None
        digits = "".join(_DIGIT_WORDS[word] for word in words)
    return digits if len(digits) in {3, 4} else None


def _parse_expiry_expression(expression: str) -> tuple[int, int] | None:
    value = re.sub(r"\s+", " ", expression.strip().lower())
    month: int
    year: int
    named = re.fullmatch(
        r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
        r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
        r"nov(?:ember)?|dec(?:ember)?)\s+(\d{2,4})",
        value,
    )
    if named:
        month = _EXPIRY_MONTHS[named.group(1)]
        year = int(named.group(2))
    else:
        numeric = re.fullmatch(r"(\d{1,4})\s*[/\-]\s*(\d{1,4})", value)
        if not numeric:
            numeric = re.fullmatch(r"(\d{1,2})\s+(\d{4})", value)
        if not numeric:
            return None
        first, second = (int(part) for part in numeric.groups())
        if first >= 1000:
            year, month = first, second
        else:
            month, year = first, second

    if year < 100:
        year += 2000
    if month not in range(1, 13) or year < 2000:
        return None
    today = date.today()
    if (year, month) < (today.year, today.month):
        return None
    return month, year


def parse_card_input(user_input: str) -> CardCandidates:
    """Extract card fields and mark malformed supplied fields as invalid."""

    if not isinstance(user_input, str) or not user_input.strip():
        return CardCandidates()

    value = user_input.strip()
    card_number: str | None = None
    invalid_card_number = False
    card_match = _CARD_NUMBER_LABEL_PATTERN.search(value)
    if card_match:
        raw_card_number = card_match.group("value").strip()
        # A label can be followed by another label with no value.
        raw_card_number = _CARD_FIELD_LABEL_PATTERN.split(raw_card_number, 1)[0]
        card_number = normalize_card_number(raw_card_number)
        invalid_card_number = card_number is None
    else:
        raw_card_match = _RAW_CARD_NUMBER_PATTERN.search(value)
        if raw_card_match:
            raw_card_number = raw_card_match.group(0)
            card_number = normalize_card_number(raw_card_number)
            invalid_card_number = card_number is None
    if card_match is None and re.search(
        r"\b(?:card\s*(?:number|no\.?|#)|number\s+on\s+card)\b",
        value,
        re.IGNORECASE,
    ):
        invalid_card_number = True

    cardholder_name: str | None = None
    invalid_cardholder_name = False
    cardholder_match = _CARDHOLDER_LABEL_PATTERN.search(value)
    if cardholder_match:
        candidate = clean_name(cardholder_match.group("value"))
        if candidate and re.search(r"[A-Za-z]", candidate):
            cardholder_name = candidate
        else:
            invalid_cardholder_name = True
    elif not card_match and not _EXPIRY_LABEL_PATTERN.search(value) and not re.search(
        r"\b(?:cvv|cvc|security\s+code)\b", value, re.IGNORECASE
    ) and not _RAW_CARD_NUMBER_PATTERN.search(value) and _parse_spoken_cvv(value) is None:
        # A plain name is useful when the agent asks for only the cardholder
        # name.  It must contain letters and must not be another field value.
        candidate = clean_name(value)
        if re.search(r"[A-Za-z]", candidate):
            cardholder_name = candidate

    cvv: str | None = None
    invalid_cvv = False
    cvv_match = _CVV_LABEL_PATTERN.search(value)
    if cvv_match:
        cvv = _parse_spoken_cvv(cvv_match.group("value"))
        invalid_cvv = cvv is None
    elif re.fullmatch(r"\s*(?:[0-9](?:[\s-]*[0-9])*)\s*", value):
        cvv = _parse_spoken_cvv(value)
    elif re.fullmatch(
        r"\s*(?:[a-z]+(?:[\s-]+[a-z]+){2,3})\s*", value, re.IGNORECASE
    ):
        cvv = _parse_spoken_cvv(value)

    expiry_month: int | None = None
    expiry_year: int | None = None
    invalid_expiry = False
    expiry_label = _EXPIRY_LABEL_PATTERN.search(value)
    expiry_match = None
    if expiry_label:
        expiry_match = _EXPIRY_EXPRESSION_PATTERN.search(value, expiry_label.end())
    else:
        # An unlabelled month/year is allowed, but hyphenated card-number
        # groups (for example 4532-0151) are not expiry expressions.
        card_spans = [
            (match.start(), match.end())
            for match in _RAW_CARD_NUMBER_PATTERN.finditer(value)
        ]
        for match in _EXPIRY_EXPRESSION_PATTERN.finditer(value):
            if not any(
                match.start() < end and match.end() > start
                for start, end in card_spans
            ):
                expiry_match = match
                break
    if expiry_match:
        parsed_expiry = _parse_expiry_expression(expiry_match.group(0))
        if parsed_expiry is None:
            invalid_expiry = True
        else:
            expiry_month, expiry_year = parsed_expiry
    elif expiry_label:
        invalid_expiry = True

    return CardCandidates(
        cardholder_name=cardholder_name,
        card_number=card_number,
        cvv=cvv,
        expiry_month=expiry_month,
        expiry_year=expiry_year,
        invalid_cardholder_name=invalid_cardholder_name,
        invalid_card_number=invalid_card_number,
        invalid_cvv=invalid_cvv,
        invalid_expiry=invalid_expiry,
    )
