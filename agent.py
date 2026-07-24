"""Public conversation contract for the payment collection agent."""

from __future__ import annotations

from enum import Enum, auto
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable, Mapping

from pydantic import ValidationError

from api_client import (
    AccountLookupResult,
    ApiClient,
    LookupStatus,
)
from models import AccountRecord, ValidatedPaymentAmount
from parsers import (
    contains_account_reference,
    extract_account_ids,
    parse_amount_input,
    parse_identity_input,
)


class _ConversationState(Enum):
    """Internal state names; these must never be shown to callers."""

    NEED_ACCOUNT = auto()
    NEED_FULL_NAME = auto()
    VERIFIED_NEED_AMOUNT = auto()
    AMOUNT_COLLECTED = auto()
    CLOSED_FAILURE = auto()


class Agent:
    """Process one user turn at a time for a payment conversation."""

    _ACCOUNT_PROMPT = "Please provide your account ID to get started."
    _ACCOUNT_CORRECTION_PROMPT = (
        "Please provide one valid account ID in the format ACC####, "
        "for example, ACC1001."
    )
    _AMBIGUOUS_ACCOUNT_PROMPT = (
        "I found more than one possible account ID. Please send one account ID "
        "in the format ACC####."
    )
    _FULL_NAME_PROMPT = "Thanks. Please provide your full name for verification."
    _SECONDARY_FACTOR_PROMPT = (
        "Please provide one verification detail: your date of birth, "
        "Aadhaar last four digits, or six-digit pincode."
    )
    _INVALID_SECONDARY_FACTOR_PROMPT = (
        "Please provide a valid date of birth with a four-digit year, "
        "exactly four Aadhaar last-four digits, or a six-digit pincode."
    )
    _VERIFIED_MESSAGE = "Your identity has been verified."
    _AMOUNT_PROMPT = "Please provide the amount you would like to pay."
    _AMOUNT_CORRECTION_PROMPT = (
        "Please provide a payment amount greater than ₹0.00, no more than the "
        "outstanding balance, and with no more than two decimal places."
    )
    _AMOUNT_ACCEPTED_MESSAGE = "Your payment amount has been recorded."
    _ZERO_BALANCE_MESSAGE = (
        "Your outstanding balance is ₹0.00. There is no payment amount to collect."
    )
    _BALANCE_UNAVAILABLE_MESSAGE = (
        "Your identity has been verified, but I couldn't retrieve a valid "
        "outstanding balance. Please try again later."
    )
    _VERIFICATION_FAILURE_MESSAGE = (
        "Those details did not match our records. Please provide your full "
        "name and one verification detail again."
    )
    _VERIFICATION_LOCKED_MESSAGE = (
        "I couldn't verify your identity after three attempts. "
        "This conversation is now closed."
    )
    _UNKNOWN_ACCOUNT_MESSAGE = (
        "I couldn't find that account ID. Please check it and send it again."
    )
    _TIMEOUT_MESSAGE = (
        "I couldn't retrieve that account right now. Please try again later."
    )
    _CONNECTION_MESSAGE = (
        "I couldn't connect to the account service. Please try again later."
    )
    _MALFORMED_RESPONSE_MESSAGE = (
        "The account service returned an unexpected response. Please try again later."
    )
    _UNAVAILABLE_MESSAGE = (
        "Account lookup is temporarily unavailable. Please try again later."
    )

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
    ) -> None:
        if lookup_client is not None and api_client is not None:
            raise ValueError("Provide lookup_client or api_client, not both.")

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
        self._lookup_client = (
            lookup_client
            if lookup_client is not None
            else api_client if api_client is not None else ApiClient()
        )

    def next(self, user_input: str) -> dict[str, str]:
        """Process one user turn and return a deterministic message.

        Account IDs are parsed before state-specific handling so a different
        account can replace a pending one before verification. Non-string
        values are treated as unusable input so the response contract remains
        stable at runtime.
        """

        if self._state is _ConversationState.CLOSED_FAILURE:
            return {"message": self._VERIFICATION_LOCKED_MESSAGE}

        if not isinstance(user_input, str) or not user_input.strip():
            if self._state is _ConversationState.NEED_ACCOUNT:
                return {"message": self._ACCOUNT_PROMPT}
            if self._state is _ConversationState.VERIFIED_NEED_AMOUNT:
                return {"message": self._amount_collection_message()}
            if self._state is _ConversationState.AMOUNT_COLLECTED:
                return {"message": self._AMOUNT_ACCEPTED_MESSAGE}
            return {"message": self._FULL_NAME_PROMPT}

        account_ids = extract_account_ids(user_input)
        if len(account_ids) > 1:
            return {"message": self._AMBIGUOUS_ACCOUNT_PROMPT}

        if self._state is _ConversationState.NEED_ACCOUNT:
            if len(account_ids) == 0:
                return {"message": self._ACCOUNT_CORRECTION_PROMPT}
            response = self._handle_account_id(account_ids[0])
            if self._state is _ConversationState.NEED_FULL_NAME:
                self._capture_amount_input(user_input)
            if self._state is _ConversationState.NEED_FULL_NAME and self._has_identity_input(
                user_input
            ):
                return self._handle_identity_turn(user_input)
            return response

        if self._state is _ConversationState.VERIFIED_NEED_AMOUNT:
            self._capture_amount_input(user_input, allow_plain_number=True)
            return self._handle_amount_turn()

        if self._state is _ConversationState.AMOUNT_COLLECTED:
            return {"message": self._AMOUNT_ACCEPTED_MESSAGE}

        if len(account_ids) == 1:
            account_id = account_ids[0]
            if account_id != self._account_id:
                response = self._handle_account_id(account_id)
                if self._state is _ConversationState.NEED_FULL_NAME:
                    self._capture_amount_input(user_input)
                if self._state is _ConversationState.NEED_FULL_NAME and self._has_identity_input(
                    user_input
                ):
                    return self._handle_identity_turn(user_input)
                return response
            if self._has_identity_input(user_input):
                self._capture_amount_input(user_input)
                return self._handle_identity_turn(user_input)
            return {"message": self._FULL_NAME_PROMPT}

        if contains_account_reference(user_input):
            return {"message": self._ACCOUNT_CORRECTION_PROMPT}
        self._capture_amount_input(user_input)
        return self._handle_identity_turn(user_input)

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
        self._state = _ConversationState.NEED_FULL_NAME
        return {"message": self._FULL_NAME_PROMPT}

    def _handle_identity_turn(self, user_input: str) -> dict[str, str]:
        candidates = parse_identity_input(user_input)
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
        display = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"₹{display:.2f}"

    def _amount_collection_message(self) -> str:
        balance = self._balance()
        if balance is None:
            # Older injectable lookup clients may provide identity-only
            # records. Keep verification behavior stable for those clients;
            # amount validation still requires a real balance.
            return self._VERIFIED_MESSAGE
        formatted_balance = self._format_amount(balance)
        if balance == 0:
            return self._ZERO_BALANCE_MESSAGE
        pending_amount = self._resolve_pending_amount()
        if pending_amount is not None and self._is_valid_amount(
            pending_amount, balance
        ):
            self._state = _ConversationState.AMOUNT_COLLECTED
            return (
                f"{self._VERIFIED_MESSAGE} Your outstanding balance is "
                f"{formatted_balance}. {self._AMOUNT_ACCEPTED_MESSAGE}"
            )
        if self._invalid_amount_pending or pending_amount is not None:
            return (
                f"{self._VERIFIED_MESSAGE} Your outstanding balance is "
                f"{formatted_balance}. {self._AMOUNT_CORRECTION_PROMPT}"
            )
        return (
            f"{self._VERIFIED_MESSAGE} Your outstanding balance is "
            f"{formatted_balance}. {self._AMOUNT_PROMPT}"
        )

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
