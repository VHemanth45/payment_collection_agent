"""Schema-bound, optional extraction support for the conversation agent.

The extractor is deliberately only an input-normalization seam.  It returns
structured candidates and never decides whether identity, an amount, or a
payment is valid.  The agent still performs all merging, validation, state
transitions, and user-facing messaging deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol


class ExtractionGroup(str, Enum):
    """The only logical field groups an extractor may be asked to produce."""

    IDENTITY = "identity"
    PAYMENT = "payment"
    CARD = "card"

    @property
    def tool_name(self) -> str:
        return f"extract_{self.value}"


# These are intentionally small schemas.  Every property is required at the
# tool boundary, but nullable: a missing value must be returned as null rather
# than inferred from unrelated text.
EXTRACTION_SCHEMAS: dict[ExtractionGroup, dict[str, Any]] = {
    ExtractionGroup.IDENTITY: {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": ["string", "null"]},
            "dob": {"type": ["string", "null"]},
            "aadhaar_last4": {"type": ["string", "null"]},
            "pincode": {"type": ["string", "null"]},
        },
        "required": ["name", "dob", "aadhaar_last4", "pincode"],
    },
    ExtractionGroup.PAYMENT: {
        "type": "object",
        "additionalProperties": False,
        "properties": {"amount": {"type": ["number", "string", "null"]}},
        "required": ["amount"],
    },
    ExtractionGroup.CARD: {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "card_number": {"type": ["string", "null"]},
            "cvv": {"type": ["string", "null"]},
            "expiry_month": {"type": ["integer", "null"]},
            "expiry_year": {"type": ["integer", "null"]},
            "cardholder_name": {"type": ["string", "null"]},
        },
        "required": [
            "card_number",
            "cvv",
            "expiry_month",
            "expiry_year",
            "cardholder_name",
        ],
    },
}

# Named aliases keep the three public logical schemas easy to discover for
# clients and contract tests without introducing a second schema definition.
IDENTITY_SCHEMA = EXTRACTION_SCHEMAS[ExtractionGroup.IDENTITY]
PAYMENT_SCHEMA = EXTRACTION_SCHEMAS[ExtractionGroup.PAYMENT]
CARD_SCHEMA = EXTRACTION_SCHEMAS[ExtractionGroup.CARD]


@dataclass(frozen=True)
class ExtractionRequest:
    """The complete forced-tool request passed to an extractor client."""

    user_input: str
    group: ExtractionGroup
    schema: Mapping[str, Any]
    tool_choice: Mapping[str, Any]

    @property
    def tool_name(self) -> str:
        return self.group.tool_name


class Extractor(Protocol):
    """Minimal injectable extractor protocol used by :class:`agent.Agent`."""

    def extract(self, request: ExtractionRequest) -> Any:
        """Return a mapping or structured object for one requested group."""


def extraction_request(user_input: str, group: ExtractionGroup) -> ExtractionRequest:
    """Build a schema-bound request with a forced function/tool choice."""

    return ExtractionRequest(
        user_input=user_input,
        group=group,
        schema=EXTRACTION_SCHEMAS[group],
        tool_choice={
            "type": "function",
            "function": {"name": group.tool_name},
        },
    )


def structured_fields(group: ExtractionGroup, raw: Any) -> dict[str, Any]:
    """Return only known structured fields, with missing fields as ``None``.

    Free-form response text is intentionally not parsed.  This keeps model
    prose out of deterministic business logic and makes malformed extractor
    responses equivalent to an all-null result.
    """

    field_names = tuple(EXTRACTION_SCHEMAS[group]["properties"])
    fields = {name: None for name in field_names}
    if isinstance(raw, ExtractionRequest):
        return fields

    if isinstance(raw, Mapping):
        source: Mapping[str, Any] = raw
    else:
        # Permit simple typed test doubles/dataclasses without accepting their
        # repr or arbitrary response text as an extraction result.
        source = {
            name: getattr(raw, name)
            for name in field_names
            if hasattr(raw, name)
        }
    for name in field_names:
        if name in source:
            fields[name] = source[name]
    return fields


class NullExtractor:
    """Safe no-op extractor useful as an explicit dependency."""

    def extract(self, request: ExtractionRequest) -> dict[str, None]:
        return structured_fields(request.group, None)
