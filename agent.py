"""Public conversation contract for the payment collection agent."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from decimal import Decimal, InvalidOperation
import inspect
import re
from typing import Any, Callable, Mapping

from pydantic import ValidationError

from api_client import (
    AccountLookupResult,
    ApiClient,
    LookupStatus,
    PaymentResult,
    PaymentStatus,
)
import messages as _messages
from models import AccountRecord, PaymentCard, ValidatedPaymentAmount
from extractor import (
    EXTRACTION_SCHEMAS,
    ExtractionGroup,
    extraction_request,
    structured_fields,
)
from parsers import (
    contains_account_reference,
    extract_account_ids,
    normalize_card_number,
    parse_amount_input,
    parse_card_input,
    parse_identity_input,
)


class _ConversationState(Enum):
    """Internal state names; these must never be shown to callers."""

    NEED_ACCOUNT = auto()
    NEED_FULL_NAME = auto()
    VERIFIED_NEED_AMOUNT = auto()
    AMOUNT_COLLECTED = auto()
    CARD_DETAILS_COLLECTED = auto()
    PAYMENT_COMPLETE = auto()
    PAYMENT_FAILED = auto()
    CLOSED_FAILURE = auto()


@dataclass(frozen=True)
class _RegexTurn:
    """All deterministic fast-path candidates found in one user turn."""

    account_ids: tuple[str, ...]
    identity: Any
    amount: Any
    card: Any
    card_relevant: bool


class Agent:
    """Process one user turn at a time for a payment conversation."""

    _ACCOUNT_PROMPT = _messages.ACCOUNT_PROMPT
    _ACCOUNT_CORRECTION_PROMPT = _messages.ACCOUNT_CORRECTION_PROMPT
    _AMBIGUOUS_ACCOUNT_PROMPT = _messages.AMBIGUOUS_ACCOUNT_PROMPT
    _FULL_NAME_PROMPT = _messages.FULL_NAME_PROMPT
    _SECONDARY_FACTOR_PROMPT = _messages.SECONDARY_FACTOR_PROMPT
    _INVALID_SECONDARY_FACTOR_PROMPT = _messages.INVALID_SECONDARY_FACTOR_PROMPT
    _VERIFIED_MESSAGE = _messages.VERIFIED_MESSAGE
    _AMOUNT_PROMPT = _messages.AMOUNT_PROMPT
    _AMOUNT_CORRECTION_PROMPT = _messages.AMOUNT_CORRECTION_PROMPT
    _AMOUNT_ACCEPTED_MESSAGE = _messages.AMOUNT_ACCEPTED_MESSAGE
    _CARD_DETAILS_PROMPT = _messages.CARD_DETAILS_PROMPT
    _CARD_DETAILS_ACCEPTED_MESSAGE = _messages.CARD_DETAILS_ACCEPTED_MESSAGE
    _PAYMENT_FAILURE_MESSAGE = _messages.PAYMENT_FAILURE_MESSAGE
    _PAYMENT_UNCONFIRMED_MESSAGE = _messages.PAYMENT_UNCONFIRMED_MESSAGE
    _PAYMENT_RETRY_LIMIT_MESSAGE = _messages.PAYMENT_RETRY_LIMIT_MESSAGE
    _INSUFFICIENT_BALANCE_MESSAGE = _messages.INSUFFICIENT_BALANCE_MESSAGE
    _INVALID_CARD_PAYMENT_MESSAGE = _messages.INVALID_CARD_PAYMENT_MESSAGE
    _INVALID_CVV_PAYMENT_MESSAGE = _messages.INVALID_CVV_PAYMENT_MESSAGE
    _INVALID_EXPIRY_PAYMENT_MESSAGE = _messages.INVALID_EXPIRY_PAYMENT_MESSAGE
    _ZERO_BALANCE_MESSAGE = _messages.ZERO_BALANCE_MESSAGE
    _BALANCE_UNAVAILABLE_MESSAGE = _messages.BALANCE_UNAVAILABLE_MESSAGE
    _VERIFICATION_FAILURE_MESSAGE = _messages.VERIFICATION_FAILURE_MESSAGE
    _VERIFICATION_LOCKED_MESSAGE = _messages.VERIFICATION_LOCKED_MESSAGE
    _UNKNOWN_ACCOUNT_MESSAGE = _messages.UNKNOWN_ACCOUNT_MESSAGE
    _TIMEOUT_MESSAGE = _messages.TIMEOUT_MESSAGE
    _CONNECTION_MESSAGE = _messages.CONNECTION_MESSAGE
    _MALFORMED_RESPONSE_MESSAGE = _messages.MALFORMED_RESPONSE_MESSAGE
    _UNAVAILABLE_MESSAGE = _messages.UNAVAILABLE_MESSAGE

    _ACCOUNT_KEYS = frozenset(
        {
            "account_id",
            "id",
            "full_name",
            "name",
            "dob",
            "date_of_birth",
            "aadhaar_last4",
            "pincode",
            "outstanding_balance",
            "balance",
        }
    )

    def __init__(
        self,
        lookup_client: Any | Callable[[str], Any] | None = None,
        *,
        api_client: Any | None = None,
        extractor: Any | Callable[..., Any] | None = None,
        extractor_client: Any | Callable[..., Any] | None = None,
    ) -> None:
        if lookup_client is not None and api_client is not None:
            raise ValueError("Provide lookup_client or api_client, not both.")
        if extractor is not None and extractor_client is not None:
            raise ValueError("Provide extractor or extractor_client, not both.")

        self._state = _ConversationState.NEED_ACCOUNT
        self._account_id: str | None = None
        self._account: AccountRecord | None = None
        self._verification_attempts = 0
        self._name_candidate: str | None = None
        self._dob_candidate: str | None = None
        self._aadhaar_candidate: str | None = None
        self._pincode_candidate: str | None = None
        self._invalid_dob_pending = False
        self._invalid_aadhaar_pending = False
        self._invalid_pincode_pending = False
        self._amount: Decimal | None = None
        self._full_balance_pending = False
        self._invalid_amount_pending = False
        self._cardholder_name: str | None = None
        self._card_number: str | None = None
        self._cvv: str | None = None
        self._expiry_month: int | None = None
        self._expiry_year: int | None = None
        self._invalid_cardholder_name = False
        self._invalid_card_number = False
        self._invalid_cvv = False
        self._invalid_expiry = False
        self._payment_transaction_id: str | None = None
        self._payment_result: PaymentStatus | None = None
        self._payment_retry_attempts = 0
        self._payment_retry_exhausted = False
        self._extractor = (
            extractor if extractor is not None else extractor_client
        )
        self._lookup_client = (
            lookup_client
            if lookup_client is not None
            else api_client if api_client is not None else ApiClient()
        )

    def next(self, user_input: str) -> dict[str, str]:
        """Process one user turn and return a deterministic message.

        Every turn first passes through all deterministic fast-path parsers.
        The optional schema-bound extractor is invoked only after those values
        have been merged and only for the field group required by the current
        state.  Non-string values are treated as unusable input so the
        response contract remains stable at runtime.
        """

        regex_turn = self._parse_regex_turn(user_input)

        if self._state is _ConversationState.CLOSED_FAILURE:
            return {"message": self._VERIFICATION_LOCKED_MESSAGE}
        if self._state is _ConversationState.PAYMENT_COMPLETE:
            return {"message": self._payment_success_message()}
        if self._state is _ConversationState.PAYMENT_FAILED:
            if self._payment_retry_exhausted:
                return {"message": self._PAYMENT_RETRY_LIMIT_MESSAGE}
            return {"message": self._PAYMENT_FAILURE_MESSAGE}

        if not isinstance(user_input, str) or not user_input.strip():
            if self._state is _ConversationState.NEED_ACCOUNT:
                return {"message": self._ACCOUNT_PROMPT}
            if self._state is _ConversationState.VERIFIED_NEED_AMOUNT:
                return {"message": self._amount_collection_message()}
            if self._state is _ConversationState.AMOUNT_COLLECTED:
                return {"message": self._card_collection_message()}
            if self._state is _ConversationState.CARD_DETAILS_COLLECTED:
                return {"message": self._CARD_DETAILS_ACCEPTED_MESSAGE}
            return {"message": self._FULL_NAME_PROMPT}

        account_ids = regex_turn.account_ids
        if len(account_ids) > 1:
            return {"message": self._AMBIGUOUS_ACCOUNT_PROMPT}

        if self._state is _ConversationState.NEED_ACCOUNT:
            # Preserve structured out-of-order values while waiting for the
            # account ID.  _handle_account_id retains these on a successful
            # first lookup and clears them on a failed lookup.
            self._merge_regex_turn(regex_turn)
            if len(account_ids) == 0:
                return {"message": self._ACCOUNT_CORRECTION_PROMPT}
            response = self._handle_account_id(account_ids[0])
            if self._state is _ConversationState.NEED_FULL_NAME:
                self._maybe_extract(ExtractionGroup.IDENTITY, user_input)
                if self._identity_input_available():
                    return self._handle_identity_turn(user_input)
            return response

        if self._state is _ConversationState.VERIFIED_NEED_AMOUNT:
            self._merge_regex_turn(regex_turn)
            self._maybe_extract(ExtractionGroup.PAYMENT, user_input)
            return self._handle_amount_turn()

        if self._state is _ConversationState.AMOUNT_COLLECTED:
            self._merge_regex_turn(regex_turn)
            self._maybe_extract(ExtractionGroup.CARD, user_input)
            return self._handle_card_turn(user_input)

        if self._state is _ConversationState.CARD_DETAILS_COLLECTED:
            return self._submit_payment()

        if len(account_ids) == 1:
            account_id = account_ids[0]
            if account_id != self._account_id:
                response = self._handle_account_id(account_id)
                if self._state is _ConversationState.NEED_FULL_NAME:
                    self._merge_regex_turn(regex_turn)
                    self._maybe_extract(ExtractionGroup.IDENTITY, user_input)
                    if self._identity_input_available():
                        return self._handle_identity_turn(user_input)
                return response
            self._merge_regex_turn(regex_turn)
            self._maybe_extract(ExtractionGroup.IDENTITY, user_input)
            if self._identity_input_available():
                return self._handle_identity_turn(user_input)
            return {"message": self._FULL_NAME_PROMPT}

        if contains_account_reference(user_input):
            self._merge_regex_turn(regex_turn)
            return {"message": self._ACCOUNT_CORRECTION_PROMPT}
        self._merge_regex_turn(regex_turn)
        self._maybe_extract(ExtractionGroup.IDENTITY, user_input)
        return self._handle_identity_turn(user_input)

    def _parse_regex_turn(self, user_input: str) -> _RegexTurn:
        """Run every deterministic parser before any optional extraction."""

        if not isinstance(user_input, str):
            return _RegexTurn(
                (),
                parse_identity_input(""),
                parse_amount_input(""),
                parse_card_input(""),
                False,
            )
        card_relevant = self._state in {
            _ConversationState.AMOUNT_COLLECTED,
            _ConversationState.CARD_DETAILS_COLLECTED,
        } or re.search(
            r"\b(?:card|cvv|cvc|security\s+code|exp(?:iry|iration)?|"
            r"expires?|valid\s*(?:thru|through))\b",
            user_input,
            re.IGNORECASE,
        ) is not None or re.search(
            r"(?<!\d)(?:\d[\s-]*){12,19}(?!\d)", user_input
        ) is not None
        return _RegexTurn(
            extract_account_ids(user_input),
            parse_identity_input(
                user_input,
                allow_unlabeled_factors=self._state is _ConversationState.NEED_FULL_NAME,
            ),
            parse_amount_input(
                user_input,
                allow_plain_number=self._state is _ConversationState.VERIFIED_NEED_AMOUNT,
            ),
            parse_card_input(user_input),
            card_relevant,
        )

    def _merge_regex_turn(self, regex_turn: _RegexTurn) -> None:
        """Merge fast-path values into conversation-local context."""

        identity = regex_turn.identity
        if identity.name is not None:
            self._name_candidate = identity.name
        if identity.dob is not None:
            self._dob_candidate = identity.dob
            self._invalid_dob_pending = False
        elif identity.invalid_dob:
            self._invalid_dob_pending = True
        if identity.aadhaar_last4 is not None:
            self._aadhaar_candidate = identity.aadhaar_last4
            self._invalid_aadhaar_pending = False
        elif identity.invalid_aadhaar:
            self._invalid_aadhaar_pending = True
        if identity.pincode is not None:
            self._pincode_candidate = identity.pincode
            self._invalid_pincode_pending = False
        elif identity.invalid_pincode:
            self._invalid_pincode_pending = True

        amount = regex_turn.amount
        if amount.full_balance:
            self._full_balance_pending = True
            self._amount = None
            self._invalid_amount_pending = False
        elif amount.amount is not None:
            self._amount = amount.amount
            self._full_balance_pending = False
            self._invalid_amount_pending = False
        elif amount.invalid:
            self._invalid_amount_pending = True

        if not regex_turn.card_relevant:
            return
        card = regex_turn.card
        if card.cardholder_name is not None:
            self._cardholder_name = card.cardholder_name
            self._invalid_cardholder_name = False
        elif card.invalid_cardholder_name:
            self._cardholder_name = None
            self._invalid_cardholder_name = True
        if card.card_number is not None:
            self._card_number = card.card_number
            self._invalid_card_number = False
        elif card.invalid_card_number:
            self._card_number = None
            self._invalid_card_number = True
        if card.cvv is not None:
            self._cvv = card.cvv
            self._invalid_cvv = False
        elif card.invalid_cvv:
            self._cvv = None
            self._invalid_cvv = True
        if card.expiry_month is not None and card.expiry_year is not None:
            self._expiry_month = card.expiry_month
            self._expiry_year = card.expiry_year
            self._invalid_expiry = False
        elif card.invalid_expiry:
            self._expiry_month = None
            self._expiry_year = None
            self._invalid_expiry = True

    def _identity_input_available(self) -> bool:
        return any(
            (
                self._name_candidate is not None,
                self._dob_candidate is not None,
                self._aadhaar_candidate is not None,
                self._pincode_candidate is not None,
                self._invalid_dob_pending,
                self._invalid_aadhaar_pending,
                self._invalid_pincode_pending,
            )
        )

    def _missing_extraction_fields(self, group: ExtractionGroup) -> bool:
        if group is ExtractionGroup.IDENTITY:
            has_secondary = any(
                (
                    self._dob_candidate is not None,
                    self._aadhaar_candidate is not None,
                    self._pincode_candidate is not None,
                )
            )
            return self._name_candidate is None or (
                not has_secondary
                and not any(
                    (
                        self._invalid_dob_pending,
                        self._invalid_aadhaar_pending,
                        self._invalid_pincode_pending,
                    )
                )
            )
        if group is ExtractionGroup.PAYMENT:
            return (
                self._amount is None
                and not self._full_balance_pending
                and not self._invalid_amount_pending
            )
        return any(
            (
                self._cardholder_name is None and not self._invalid_cardholder_name,
                self._card_number is None and not self._invalid_card_number,
                self._cvv is None and not self._invalid_cvv,
                (
                    (self._expiry_month is None or self._expiry_year is None)
                    and not self._invalid_expiry
                ),
            )
        )

    def _maybe_extract(self, group: ExtractionGroup, user_input: str) -> None:
        """Invoke the optional extractor only for still-missing fields."""

        if self._extractor is None or not self._missing_extraction_fields(group):
            return
        raw = self._call_extractor(group, user_input)
        self._merge_extractor_fields(group, structured_fields(group, raw))

    def _call_extractor(self, group: ExtractionGroup, user_input: str) -> Any:
        """Call an injected extractor once, with a forced group/tool choice.

        The small signature adapter makes the seam convenient for production
        clients and lightweight tests while ensuring that no retry can cause a
        duplicate external extraction call.
        """

        request = extraction_request(user_input, group)
        method = getattr(self._extractor, "extract", None)
        if not callable(method):
            method = getattr(self._extractor, group.tool_name, None)
        if not callable(method) and callable(self._extractor):
            method = self._extractor
        if not callable(method):
            return None

        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            try:
                return method(request)
            except Exception:
                return None

        parameters = list(signature.parameters.values())
        required = [
            parameter
            for parameter in parameters
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if len(required) == 1 and required[0].name in {
            "request",
            "extraction_request",
            "request_obj",
        }:
            try:
                return method(request)
            except Exception:
                return None

        values = {
            "user_input": user_input,
            "text": user_input,
            "prompt": user_input,
            "group": group,
            "group_name": group.value,
            "schema_name": group.tool_name,
            "schema": EXTRACTION_SCHEMAS[group],
            "tool_choice": request.tool_choice,
            "request": request,
        }
        positional: list[Any] = []
        keyword: dict[str, Any] = {}
        has_var_keyword = any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        for parameter in parameters:
            if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
                continue
            if parameter.kind is inspect.Parameter.VAR_KEYWORD:
                continue
            if parameter.name not in values:
                continue
            value = values[parameter.name]
            if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
                positional.append(value)
            else:
                keyword[parameter.name] = value
        if has_var_keyword:
            for name in ("group", "schema", "tool_choice"):
                keyword.setdefault(name, values[name])
        try:
            return method(*positional, **keyword)
        except Exception:
            return None

    def _merge_extractor_fields(
        self, group: ExtractionGroup, fields: Mapping[str, Any]
    ) -> None:
        """Merge only validated, previously missing extractor candidates."""

        if group is ExtractionGroup.IDENTITY:
            name = fields.get("name")
            if self._name_candidate is None and isinstance(name, str) and name.strip():
                self._name_candidate = self._normalize_name(name)

            dob = fields.get("dob")
            if self._dob_candidate is None and not self._invalid_dob_pending:
                candidate = parse_identity_input(f"DOB {dob}") if dob is not None else None
                if candidate is not None and candidate.dob is not None:
                    self._dob_candidate = candidate.dob

            aadhaar = fields.get("aadhaar_last4")
            if self._aadhaar_candidate is None and not self._invalid_aadhaar_pending:
                candidate = (
                    parse_identity_input(f"Aadhaar last four {aadhaar}")
                    if aadhaar is not None
                    else None
                )
                if candidate is not None and candidate.aadhaar_last4 is not None:
                    self._aadhaar_candidate = candidate.aadhaar_last4

            pincode = fields.get("pincode")
            if self._pincode_candidate is None and not self._invalid_pincode_pending:
                candidate = (
                    parse_identity_input(f"pincode {pincode}")
                    if pincode is not None
                    else None
                )
                if candidate is not None and candidate.pincode is not None:
                    self._pincode_candidate = candidate.pincode
            return

        if group is ExtractionGroup.PAYMENT:
            if self._amount is None and not self._full_balance_pending and not self._invalid_amount_pending:
                raw_amount = fields.get("amount")
                if raw_amount is not None:
                    candidate = parse_amount_input(str(raw_amount), allow_plain_number=True)
                    if candidate.amount is not None:
                        self._amount = candidate.amount
            return

        if self._cardholder_name is None and not self._invalid_cardholder_name:
            value = fields.get("cardholder_name")
            if isinstance(value, str) and value.strip():
                self._cardholder_name = self._normalize_name(value)
        if self._card_number is None and not self._invalid_card_number:
            value = fields.get("card_number")
            if isinstance(value, str):
                self._card_number = normalize_card_number(value)
        if self._cvv is None and not self._invalid_cvv:
            value = fields.get("cvv")
            if value is not None:
                candidate = parse_card_input(f"CVV: {value}")
                if candidate.cvv is not None:
                    self._cvv = candidate.cvv
        if (
            self._expiry_month is None or self._expiry_year is None
        ) and not self._invalid_expiry:
            month = fields.get("expiry_month")
            year = fields.get("expiry_year")
            if month is not None and year is not None:
                candidate = parse_card_input(f"expiry: {month}/{year}")
                if candidate.expiry_month is not None and candidate.expiry_year is not None:
                    self._expiry_month = candidate.expiry_month
                    self._expiry_year = candidate.expiry_year

    @staticmethod
    def _has_identity_input(user_input: str) -> bool:
        candidates = parse_identity_input(user_input)
        return any(
            (
                candidates.name is not None,
                candidates.dob is not None,
                candidates.aadhaar_last4 is not None,
                candidates.pincode is not None,
                candidates.invalid_dob,
                candidates.invalid_aadhaar,
                candidates.invalid_pincode,
            )
        )

    def _handle_account_id(self, account_id: str) -> dict[str, str]:
        pending_input = None
        if self._state is _ConversationState.NEED_ACCOUNT:
            pending_input = (
                self._name_candidate,
                self._dob_candidate,
                self._aadhaar_candidate,
                self._pincode_candidate,
                self._invalid_dob_pending,
                self._invalid_aadhaar_pending,
                self._invalid_pincode_pending,
                self._amount,
                self._full_balance_pending,
                self._invalid_amount_pending,
                self._cardholder_name,
                self._card_number,
                self._cvv,
                self._expiry_month,
                self._expiry_year,
                self._invalid_cardholder_name,
                self._invalid_card_number,
                self._invalid_cvv,
                self._invalid_expiry,
            )
        result = self._perform_lookup(account_id)
        if result.status is not LookupStatus.FOUND:
            self._account_id = None
            self._account = None
            self._reset_verification_context()
            self._reset_amount_context()
            self._state = _ConversationState.NEED_ACCOUNT
            return {"message": self._lookup_failure_message(result.status)}

        self._account_id = account_id
        self._account = result.account
        self._reset_verification_context()
        self._reset_amount_context()
        if pending_input is not None:
            (
                self._name_candidate,
                self._dob_candidate,
                self._aadhaar_candidate,
                self._pincode_candidate,
                self._invalid_dob_pending,
                self._invalid_aadhaar_pending,
                self._invalid_pincode_pending,
                self._amount,
                self._full_balance_pending,
                self._invalid_amount_pending,
                self._cardholder_name,
                self._card_number,
                self._cvv,
                self._expiry_month,
                self._expiry_year,
                self._invalid_cardholder_name,
                self._invalid_card_number,
                self._invalid_cvv,
                self._invalid_expiry,
            ) = pending_input
        self._state = _ConversationState.NEED_FULL_NAME
        return {"message": self._FULL_NAME_PROMPT}

    def _handle_identity_turn(self, user_input: str) -> dict[str, str]:
        candidates = parse_identity_input(
            user_input, allow_unlabeled_factors=True
        )
        if candidates.name is not None:
            self._name_candidate = candidates.name
        if candidates.dob is not None:
            self._dob_candidate = candidates.dob
            self._invalid_dob_pending = False
        elif candidates.invalid_dob:
            self._invalid_dob_pending = True
        if candidates.aadhaar_last4 is not None:
            self._aadhaar_candidate = candidates.aadhaar_last4
            self._invalid_aadhaar_pending = False
        elif candidates.invalid_aadhaar:
            self._invalid_aadhaar_pending = True
        if candidates.pincode is not None:
            self._pincode_candidate = candidates.pincode
            self._invalid_pincode_pending = False
        elif candidates.invalid_pincode:
            self._invalid_pincode_pending = True

        if self._name_candidate is None:
            return {"message": self._FULL_NAME_PROMPT}

        has_secondary = any(
            candidate is not None
            for candidate in (
                self._dob_candidate,
                self._aadhaar_candidate,
                self._pincode_candidate,
            )
        )
        if not has_secondary:
            if (
                candidates.invalid_dob
                or candidates.invalid_aadhaar
                or candidates.invalid_pincode
                or self._invalid_dob_pending
                or self._invalid_aadhaar_pending
                or self._invalid_pincode_pending
            ):
                return {"message": self._INVALID_SECONDARY_FACTOR_PROMPT}
            return {"message": self._SECONDARY_FACTOR_PROMPT}

        if self._identity_matches_account():
            self._state = _ConversationState.VERIFIED_NEED_AMOUNT
            return {"message": self._amount_collection_message()}

        return self._record_verification_failure()

    def _identity_matches_account(self) -> bool:
        if not isinstance(self._account, AccountRecord):
            return False

        expected_name = self._account.full_name
        if not isinstance(expected_name, str):
            return False
        if self._normalize_name(expected_name) != self._normalize_name(
            self._name_candidate
        ):
            return False

        return any(
            (
                self._dob_candidate is not None
                and self._dob_candidate == self._canonical_stored_value("dob"),
                self._aadhaar_candidate is not None
                and self._aadhaar_candidate
                == self._canonical_stored_value("aadhaar_last4"),
                self._pincode_candidate is not None
                and self._pincode_candidate
                == self._canonical_stored_value("pincode"),
            )
        )

    def _canonical_stored_value(self, field: str) -> str | None:
        if not isinstance(self._account, AccountRecord):
            return None
        value = getattr(self._account, field, None)
        if value is None:
            return None
        return str(value).strip()

    @staticmethod
    def _normalize_name(value: str | None) -> str:
        if not isinstance(value, str):
            return ""
        return " ".join(value.strip().split())

    def _record_verification_failure(self) -> dict[str, str]:
        self._verification_attempts += 1
        self._reset_verification_candidates()
        if self._verification_attempts >= 3:
            self._state = _ConversationState.CLOSED_FAILURE
            self._clear_account_secrets()
            return {"message": self._VERIFICATION_LOCKED_MESSAGE}
        return {"message": self._VERIFICATION_FAILURE_MESSAGE}

    def _reset_verification_candidates(self) -> None:
        self._name_candidate = None
        self._dob_candidate = None
        self._aadhaar_candidate = None
        self._pincode_candidate = None
        self._invalid_dob_pending = False
        self._invalid_aadhaar_pending = False
        self._invalid_pincode_pending = False

    def _reset_verification_context(self) -> None:
        self._verification_attempts = 0
        self._reset_verification_candidates()

    def _reset_amount_context(self) -> None:
        self._amount = None
        self._full_balance_pending = False
        self._invalid_amount_pending = False
        self._reset_card_context()
        self._payment_transaction_id = None
        self._payment_result = None
        self._payment_retry_attempts = 0
        self._payment_retry_exhausted = False

    def _reset_card_context(self) -> None:
        self._cardholder_name = None
        self._card_number = None
        self._cvv = None
        self._expiry_month = None
        self._expiry_year = None
        self._invalid_cardholder_name = False
        self._invalid_card_number = False
        self._invalid_cvv = False
        self._invalid_expiry = False

    def _clear_account_secrets(self) -> None:
        """Drop stored identity/account data after a terminal conversation."""

        self._account = None
        self._reset_verification_candidates()

    def _close_payment_conversation(self) -> None:
        """Clear sensitive context while retaining safe terminal recap data."""

        self._clear_account_secrets()
        self._reset_card_context()

    def _capture_amount_input(
        self, user_input: str, *, allow_plain_number: bool = False
    ) -> None:
        candidates = parse_amount_input(
            user_input, allow_plain_number=allow_plain_number
        )
        if candidates.full_balance:
            self._full_balance_pending = True
            self._amount = None
            self._invalid_amount_pending = False
        elif candidates.amount is not None:
            self._amount = candidates.amount
            self._full_balance_pending = False
            self._invalid_amount_pending = False
        elif candidates.invalid:
            self._invalid_amount_pending = True

    def _balance(self) -> Decimal | None:
        if not isinstance(self._account, AccountRecord):
            return None
        raw_balance = self._account.balance
        if raw_balance is None:
            raw_balance = self._account.outstanding_balance
        if raw_balance is None:
            return None
        try:
            balance = Decimal(str(raw_balance))
        except (InvalidOperation, ValueError):
            return None
        if not balance.is_finite() or balance < 0:
            return None
        return balance

    @staticmethod
    def _format_amount(amount: Decimal) -> str:
        return _messages.format_amount(amount)

    def _amount_collection_message(self) -> str:
        balance = self._balance()
        if balance is None:
            # Older injectable lookup clients may provide identity-only
            # records. Keep verification behavior stable for those clients;
            # amount validation still requires a real balance.
            return self._VERIFIED_MESSAGE
        if balance == 0:
            return self._ZERO_BALANCE_MESSAGE
        pending_amount = self._resolve_pending_amount()
        if pending_amount is not None and self._is_valid_amount(
            pending_amount, balance
        ):
            self._state = _ConversationState.AMOUNT_COLLECTED
            return _messages.balance_message(
                balance, self._AMOUNT_ACCEPTED_MESSAGE
            )
        if self._invalid_amount_pending or pending_amount is not None:
            return _messages.balance_message(
                balance, self._AMOUNT_CORRECTION_PROMPT
            )
        return _messages.balance_message(balance, self._AMOUNT_PROMPT)

    def _resolve_pending_amount(self) -> Decimal | None:
        if self._full_balance_pending:
            return self._balance()
        return self._amount

    @staticmethod
    def _is_valid_amount(amount: Decimal, balance: Decimal) -> bool:
        try:
            ValidatedPaymentAmount(amount=amount, balance=balance)
        except ValidationError:
            return False
        return True

    def _handle_amount_turn(self) -> dict[str, str]:
        balance = self._balance()
        amount = self._resolve_pending_amount()
        if balance is None:
            return {"message": self._BALANCE_UNAVAILABLE_MESSAGE}
        if amount is None:
            return {"message": self._AMOUNT_CORRECTION_PROMPT}
        if not self._is_valid_amount(amount, balance):
            return {"message": self._AMOUNT_CORRECTION_PROMPT}

        self._amount = amount
        self._full_balance_pending = False
        self._invalid_amount_pending = False
        self._state = _ConversationState.AMOUNT_COLLECTED
        return {"message": self._AMOUNT_ACCEPTED_MESSAGE}

    def _handle_card_turn(self, user_input: str) -> dict[str, str]:
        """Merge card fields from this turn and advance only when complete."""

        candidates = parse_card_input(user_input)
        complete_attempt = self._card_attempt_is_complete(candidates)
        if candidates.cardholder_name is not None:
            self._cardholder_name = candidates.cardholder_name
            self._invalid_cardholder_name = False
        elif candidates.invalid_cardholder_name:
            self._cardholder_name = None
            self._invalid_cardholder_name = True

        if candidates.card_number is not None:
            self._card_number = candidates.card_number
            self._invalid_card_number = False
        elif candidates.invalid_card_number:
            self._card_number = None
            self._invalid_card_number = True

        if candidates.cvv is not None:
            self._cvv = candidates.cvv
            self._invalid_cvv = False
        elif candidates.invalid_cvv:
            self._cvv = None
            self._invalid_cvv = True

        if candidates.expiry_month is not None and candidates.expiry_year is not None:
            self._expiry_month = candidates.expiry_month
            self._expiry_year = candidates.expiry_year
            self._invalid_expiry = False
        elif candidates.invalid_expiry:
            self._expiry_month = None
            self._expiry_year = None
            self._invalid_expiry = True

        has_local_error = any(
            (
                candidates.invalid_cardholder_name,
                candidates.invalid_card_number,
                candidates.invalid_cvv,
                candidates.invalid_expiry,
            )
        )
        if not self._card_fields_complete():
            if complete_attempt and has_local_error:
                return self._record_local_card_failure(candidates)
            return {"message": self._card_collection_message()}

        # Keep malformed values out of the eventual payment stage without
        # exposing validation details to the caller.
        try:
            PaymentCard(
                cardholder_name=self._cardholder_name,
                card_number=self._card_number,
                cvv=self._cvv,
                expiry_month=self._expiry_month,
                expiry_year=self._expiry_year,
            )
        except ValidationError:
            return self._record_local_card_failure(candidates, fallback="card")

        return self._submit_payment()

    def _card_attempt_is_complete(self, candidates: Any) -> bool:
        """Return whether this turn supplies every card field, valid or not."""

        return all(
            (
                self._cardholder_name is not None
                or candidates.cardholder_name is not None
                or candidates.invalid_cardholder_name,
                self._card_number is not None
                or candidates.card_number is not None
                or candidates.invalid_card_number,
                self._cvv is not None
                or candidates.cvv is not None
                or candidates.invalid_cvv,
                self._expiry_month is not None
                or candidates.expiry_month is not None
                or candidates.invalid_expiry,
            )
        )

    def _record_local_card_failure(
        self, candidates: Any, *, fallback: str | None = None
    ) -> dict[str, str]:
        self._payment_retry_attempts += 1
        message = self._local_card_failure_message(candidates, fallback=fallback)
        self._reset_card_context()
        if self._payment_retry_attempts >= 3:
            self._payment_retry_exhausted = True
            self._state = _ConversationState.PAYMENT_FAILED
            self._close_payment_conversation()
            return {"message": self._PAYMENT_RETRY_LIMIT_MESSAGE}
        self._state = _ConversationState.AMOUNT_COLLECTED
        return {"message": message}

    def _local_card_failure_message(
        self, candidates: Any, *, fallback: str | None = None
    ) -> str:
        fields: list[str] = []
        if candidates.invalid_card_number or fallback == "card":
            fields.append("card number")
        if candidates.invalid_expiry:
            fields.append("expiry date")
        if candidates.invalid_cvv:
            fields.append("CVV")
        if candidates.invalid_cardholder_name:
            fields.append("cardholder name")
        if not fields:
            return self._CARD_DETAILS_PROMPT
        return _messages.local_card_failure_message(fields, fallback=fallback)

    def _submit_payment(self) -> dict[str, str]:
        """Submit one validated payment and make the result idempotent."""

        try:
            payment_result = self._perform_payment()
            if (
                payment_result.status is PaymentStatus.SUCCESS
                and isinstance(payment_result.transaction_id, str)
                and payment_result.transaction_id.strip()
            ):
                self._payment_transaction_id = payment_result.transaction_id.strip()
                self._payment_result = PaymentStatus.SUCCESS
                self._state = _ConversationState.PAYMENT_COMPLETE
                message = self._payment_success_message()
                self._close_payment_conversation()
                return {"message": message}

            self._payment_result = payment_result.status
            if payment_result.status in {
                PaymentStatus.INSUFFICIENT_BALANCE,
                PaymentStatus.INVALID_AMOUNT,
                PaymentStatus.INVALID_CARD,
                PaymentStatus.INVALID_CVV,
                PaymentStatus.INVALID_EXPIRY,
            }:
                return self._handle_retryable_payment_failure(payment_result.status)
            self._state = _ConversationState.PAYMENT_FAILED
            if payment_result.status in {
                PaymentStatus.TIMEOUT,
                PaymentStatus.CONNECTION_ERROR,
            }:
                message = self._PAYMENT_UNCONFIRMED_MESSAGE
            else:
                message = self._PAYMENT_FAILURE_MESSAGE
            self._close_payment_conversation()
            return {"message": message}
        except Exception:
            self._payment_result = PaymentStatus.MALFORMED_RESPONSE
            self._state = _ConversationState.PAYMENT_FAILED
            self._close_payment_conversation()
            return {"message": self._PAYMENT_FAILURE_MESSAGE}
        finally:
            # Raw card data must not survive the payment attempt, regardless
            # of the transport or response outcome.
            self._reset_card_context()

    def _handle_retryable_payment_failure(
        self, status: PaymentStatus
    ) -> dict[str, str]:
        self._payment_retry_attempts += 1
        if self._payment_retry_attempts >= 3:
            self._payment_retry_exhausted = True
            self._state = _ConversationState.PAYMENT_FAILED
            self._close_payment_conversation()
            return {"message": self._PAYMENT_RETRY_LIMIT_MESSAGE}

        if status in {
            PaymentStatus.INSUFFICIENT_BALANCE,
            PaymentStatus.INVALID_AMOUNT,
        }:
            self._amount = None
            self._full_balance_pending = False
            self._invalid_amount_pending = True
            self._state = _ConversationState.VERIFIED_NEED_AMOUNT
            if status is PaymentStatus.INSUFFICIENT_BALANCE:
                return {"message": self._INSUFFICIENT_BALANCE_MESSAGE}
            return {"message": self._AMOUNT_CORRECTION_PROMPT}

        self._state = _ConversationState.AMOUNT_COLLECTED
        if status is PaymentStatus.INVALID_CARD:
            return {"message": self._INVALID_CARD_PAYMENT_MESSAGE}
        if status is PaymentStatus.INVALID_CVV:
            return {"message": self._INVALID_CVV_PAYMENT_MESSAGE}
        return {"message": self._INVALID_EXPIRY_PAYMENT_MESSAGE}

    def _perform_payment(self) -> PaymentResult:
        """Call an injected payment client using the documented card payload."""

        if not isinstance(self._account_id, str) or self._amount is None:
            return PaymentResult(status=PaymentStatus.MALFORMED_RESPONSE)

        amount = self._amount.quantize(Decimal("0.01"))
        card = {
            "cardholder_name": self._cardholder_name,
            "card_number": self._card_number,
            "cvv": self._cvv,
            "expiry_month": self._expiry_month,
            "expiry_year": self._expiry_year,
        }
        request_payload = {
            "account_id": self._account_id,
            "amount": amount,
            "payment_method": {"type": "card", "card": card},
        }

        payment = getattr(self._lookup_client, "process_payment", None)
        if not callable(payment):
            return PaymentResult(status=PaymentStatus.MALFORMED_RESPONSE)

        try:
            # ApiClient exposes (account_id, amount, card), while lightweight
            # injected test clients often accept the complete request payload.
            # Inspecting the signature avoids retrying a charge after a
            # TypeError from an already-invoked payment method.
            try:
                signature = inspect.signature(payment)
                signature.bind(self._account_id, amount, card)
            except (TypeError, ValueError):
                raw_result = payment(request_payload)
            else:
                raw_result = payment(self._account_id, amount, card)
        except Exception:
            return PaymentResult(status=PaymentStatus.MALFORMED_RESPONSE)

        return self._normalize_payment_result(raw_result)

    @staticmethod
    def _normalize_payment_result(raw_result: Any) -> PaymentResult:
        if isinstance(raw_result, PaymentResult):
            return raw_result
        if isinstance(raw_result, PaymentStatus):
            return PaymentResult(status=raw_result)
        if isinstance(raw_result, Mapping):
            transaction_id = raw_result.get("transaction_id")
            if raw_result.get("success") is True:
                return PaymentResult(
                    status=PaymentStatus.SUCCESS,
                    transaction_id=transaction_id
                    if isinstance(transaction_id, str)
                    else None,
                )
            status_value = (
                raw_result.get("status")
                or raw_result.get("outcome")
                or raw_result.get("error_code")
                or raw_result.get("code")
                or raw_result.get("error")
            )
            if isinstance(status_value, PaymentStatus):
                return PaymentResult(status=status_value)
            if isinstance(status_value, str):
                try:
                    normalized = status_value.strip().lower().replace("-", "_")
                    return PaymentResult(status=PaymentStatus(normalized))
                except ValueError:
                    pass
        return PaymentResult(status=PaymentStatus.MALFORMED_RESPONSE)

    def _payment_success_message(self) -> str:
        transaction_id = self._payment_transaction_id or ""
        account_id = self._account_id or ""
        amount = self._amount or Decimal("0")
        return _messages.payment_success(transaction_id, account_id, amount)

    def _card_fields_complete(self) -> bool:
        return (
            self._cardholder_name is not None
            and self._card_number is not None
            and self._cvv is not None
            and self._expiry_month is not None
            and self._expiry_year is not None
            and not any(
                (
                    self._invalid_cardholder_name,
                    self._invalid_card_number,
                    self._invalid_cvv,
                    self._invalid_expiry,
                )
            )
        )

    def _card_collection_message(self) -> str:
        missing: list[str] = []
        if self._cardholder_name is None or self._invalid_cardholder_name:
            missing.append("cardholder name")
        if self._card_number is None or self._invalid_card_number:
            missing.append("card number")
        if self._cvv is None or self._invalid_cvv:
            missing.append("CVV")
        if (
            self._expiry_month is None
            or self._expiry_year is None
            or self._invalid_expiry
        ):
            missing.append("expiry date")
        if not missing:
            return self._CARD_DETAILS_ACCEPTED_MESSAGE
        invalid_fields = {
            "cardholder name": self._invalid_cardholder_name,
            "card number": self._invalid_card_number,
            "CVV": self._invalid_cvv,
            "expiry date": self._invalid_expiry,
        }
        if invalid_fields[missing[0]]:
            return f"Please provide a valid {missing[0]}."
        return _messages.card_field_prompt(missing[0])

    def _perform_lookup(self, account_id: str) -> AccountLookupResult:
        try:
            lookup = getattr(self._lookup_client, "lookup_account", None)
            if not callable(lookup):
                lookup = getattr(self._lookup_client, "lookup", None)
            if callable(lookup):
                raw_result = lookup(account_id)
            elif callable(self._lookup_client):
                raw_result = self._lookup_client(account_id)
            else:
                return AccountLookupResult.malformed()
        except TimeoutError:
            return AccountLookupResult.timeout()
        except ConnectionError:
            return AccountLookupResult.connection_error()
        except Exception:
            return AccountLookupResult.malformed()

        return self._normalize_lookup_result(raw_result, account_id)

    @classmethod
    def _normalize_lookup_result(
        cls, raw_result: Any, requested_id: str
    ) -> AccountLookupResult:
        if isinstance(raw_result, AccountLookupResult):
            if raw_result.status is not LookupStatus.FOUND:
                return raw_result
            if cls._valid_account_payload(raw_result.account, requested_id):
                return raw_result
            return AccountLookupResult.malformed()

        if raw_result is None:
            return AccountLookupResult.not_found()
        if not isinstance(raw_result, Mapping):
            return AccountLookupResult.malformed()

        status_value = raw_result.get("status") or raw_result.get("outcome")
        error_value = raw_result.get("error") or raw_result.get("code")
        status = cls._status_from_value(status_value or error_value)
        if status is not None and status is not LookupStatus.FOUND:
            return AccountLookupResult(status)

        if raw_result.get("success") is False or raw_result.get("found") is False:
            return AccountLookupResult.not_found()

        payload: Any = raw_result
        for key in ("account", "data", "result"):
            if key in raw_result:
                payload = raw_result[key]
                break

        if payload is None:
            return AccountLookupResult.not_found()
        if not isinstance(payload, (Mapping, AccountRecord)):
            return AccountLookupResult.malformed()
        if not cls._valid_account_payload(payload, requested_id):
            return AccountLookupResult.malformed()
        return AccountLookupResult.found(payload)

    @classmethod
    def _valid_account_payload(
        cls, payload: Mapping[str, Any] | None, requested_id: str
    ) -> bool:
        if not isinstance(payload, (Mapping, AccountRecord)):
            return False
        if isinstance(payload, AccountRecord):
            record = payload
            supplied_keys = set(payload.model_fields_set)
        else:
            if not cls._ACCOUNT_KEYS.intersection(payload):
                return False
            try:
                record = AccountRecord.model_validate(payload)
            except ValidationError:
                return False
            supplied_keys = set(payload)
        if not cls._ACCOUNT_KEYS.intersection(supplied_keys):
            return False

        returned_id = record.account_id
        if returned_id is None:
            return True
        return returned_id == requested_id

    @staticmethod
    def _status_from_value(value: Any) -> LookupStatus | None:
        if not isinstance(value, str):
            return None

        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "found": LookupStatus.FOUND,
            "ok": LookupStatus.FOUND,
            "success": LookupStatus.FOUND,
            "not_found": LookupStatus.NOT_FOUND,
            "unknown": LookupStatus.NOT_FOUND,
            "account_not_found": LookupStatus.NOT_FOUND,
            "404": LookupStatus.NOT_FOUND,
            "timeout": LookupStatus.TIMEOUT,
            "timed_out": LookupStatus.TIMEOUT,
            "connection": LookupStatus.CONNECTION_ERROR,
            "connection_error": LookupStatus.CONNECTION_ERROR,
            "network_error": LookupStatus.CONNECTION_ERROR,
            "malformed": LookupStatus.MALFORMED_RESPONSE,
            "malformed_response": LookupStatus.MALFORMED_RESPONSE,
            "invalid_response": LookupStatus.MALFORMED_RESPONSE,
            "unavailable": LookupStatus.UNAVAILABLE,
        }
        return aliases.get(normalized)

    @classmethod
    def _lookup_failure_message(cls, status: LookupStatus) -> str:
        messages = {
            LookupStatus.NOT_FOUND: cls._UNKNOWN_ACCOUNT_MESSAGE,
            LookupStatus.TIMEOUT: cls._TIMEOUT_MESSAGE,
            LookupStatus.CONNECTION_ERROR: cls._CONNECTION_MESSAGE,
            LookupStatus.MALFORMED_RESPONSE: cls._MALFORMED_RESPONSE_MESSAGE,
            LookupStatus.UNAVAILABLE: cls._UNAVAILABLE_MESSAGE,
        }
        return messages.get(status, cls._MALFORMED_RESPONSE_MESSAGE)
