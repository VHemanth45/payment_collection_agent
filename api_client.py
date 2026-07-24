"""HTTP API client and injectable results for the payment service."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from decimal import Decimal
from typing import Any, Callable, Mapping, Protocol


BASE_URL = "https://se-payment-verification-api.service.external.usea2.aws.prodigaltech.com/"


class LookupStatus(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    MALFORMED_RESPONSE = "malformed_response"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class AccountLookupResult:
    """Normalized result returned by an account lookup client."""

    status: LookupStatus
    account: Mapping[str, Any] | None = None

    @classmethod
    def found(cls, account: Mapping[str, Any]) -> "AccountLookupResult":
        return cls(LookupStatus.FOUND, account)

    @classmethod
    def not_found(cls) -> "AccountLookupResult":
        return cls(LookupStatus.NOT_FOUND)

    @classmethod
    def timeout(cls) -> "AccountLookupResult":
        return cls(LookupStatus.TIMEOUT)

    @classmethod
    def connection_error(cls) -> "AccountLookupResult":
        return cls(LookupStatus.CONNECTION_ERROR)

    @classmethod
    def malformed(cls) -> "AccountLookupResult":
        return cls(LookupStatus.MALFORMED_RESPONSE)


class AccountLookupClient(Protocol):
    def lookup_account(self, account_id: str) -> Any:
        """Look up one canonical account ID."""


class PaymentStatus(str, Enum):
    SUCCESS = "success"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    INVALID_AMOUNT = "invalid_amount"
    INVALID_CARD = "invalid_card"
    INVALID_CVV = "invalid_cvv"
    INVALID_EXPIRY = "invalid_expiry"
    MALFORMED_RESPONSE = "malformed_response"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"


@dataclass(frozen=True)
class PaymentResult:
    """Normalized result returned by the payment endpoint."""

    status: PaymentStatus
    transaction_id: str | None = None


class ApiClient:
    """Small stdlib HTTP adapter for the documented payment API."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        *,
        timeout: float = 10.0,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout = timeout
        self._opener = opener

    def lookup_account(self, account_id: str) -> AccountLookupResult:
        """Fetch one account and map transport/API outcomes to a result."""

        response = self._post("api/lookup-account", {"account_id": account_id})
        if isinstance(response, LookupStatus):
            return AccountLookupResult(response)
        if response is None:
            return AccountLookupResult.malformed()

        status_code, payload = response
        if status_code == 404:
            if isinstance(payload, Mapping) and payload.get("error_code") == (
                "account_not_found"
            ):
                return AccountLookupResult.not_found()
            return AccountLookupResult.not_found()
        if status_code != 200 or not isinstance(payload, Mapping):
            return AccountLookupResult.malformed()
        return AccountLookupResult.found(payload)

    def process_payment(
        self,
        account_id: str,
        amount: Decimal | float | int,
        card: Mapping[str, Any],
    ) -> PaymentResult:
        """Submit a card payment using the documented request shape."""

        payload = {
            "account_id": account_id,
            "amount": float(amount),
            "payment_method": {"type": "card", "card": dict(card)},
        }
        response = self._post("api/process-payment", payload)
        if response is LookupStatus.TIMEOUT:
            return PaymentResult(PaymentStatus.TIMEOUT)
        if response is LookupStatus.CONNECTION_ERROR:
            return PaymentResult(PaymentStatus.CONNECTION_ERROR)
        if response is None:
            return PaymentResult(PaymentStatus.MALFORMED_RESPONSE)

        status_code, body = response
        if status_code == 200 and isinstance(body, Mapping):
            if body.get("success") is True and isinstance(
                body.get("transaction_id"), str
            ):
                return PaymentResult(
                    PaymentStatus.SUCCESS, body["transaction_id"]
                )
            return PaymentResult(PaymentStatus.MALFORMED_RESPONSE)

        if status_code == 422 and isinstance(body, Mapping):
            error_code = body.get("error_code")
            status = {
                "insufficient_balance": PaymentStatus.INSUFFICIENT_BALANCE,
                "invalid_amount": PaymentStatus.INVALID_AMOUNT,
                "invalid_card": PaymentStatus.INVALID_CARD,
                "invalid_cvv": PaymentStatus.INVALID_CVV,
                "invalid_expiry": PaymentStatus.INVALID_EXPIRY,
            }.get(error_code, PaymentStatus.MALFORMED_RESPONSE)
            return PaymentResult(status)
        return PaymentResult(PaymentStatus.MALFORMED_RESPONSE)

    def _post(
        self, path: str, payload: Mapping[str, Any]
    ) -> tuple[int, Any] | LookupStatus | None:
        request = urllib.request.Request(
            self._base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = self._opener(request, timeout=self._timeout)
            try:
                status_code = getattr(response, "status", None)
                if status_code is None:
                    status_code = response.getcode()
                body = response.read()
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
        except urllib.error.HTTPError as error:
            status_code = error.code
            try:
                body = error.read()
            except Exception:
                body = b""
        except (TimeoutError, socket.timeout):
            return LookupStatus.TIMEOUT
        except urllib.error.URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                return LookupStatus.TIMEOUT
            return LookupStatus.CONNECTION_ERROR
        except (ConnectionError, OSError):
            return LookupStatus.CONNECTION_ERROR

        try:
            decoded = json.loads(body.decode("utf-8"))
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
            return (status_code, None)
        return (status_code, decoded)


class UnavailableLookupClient:
    """Explicit safe fallback retained for callers that need no network."""

    def lookup_account(self, account_id: str) -> AccountLookupResult:
        del account_id
        return AccountLookupResult(LookupStatus.UNAVAILABLE)
