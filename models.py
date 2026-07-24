"""Pydantic v2 schemas shared by parsing, orchestration, and API transport."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AccountId(BaseModel):
    """Canonical account identifier accepted by the conversation."""

    model_config = ConfigDict(frozen=True)

    value: str

    @field_validator("value", mode="before")
    @classmethod
    def normalize(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("account ID must be text")
        return value.replace(" ", "").replace("-", "").upper()

    @field_validator("value")
    @classmethod
    def validate_format(cls, value: str) -> str:
        if len(value) != 7 or value[:3] != "ACC" or not value[3:].isdigit():
            raise ValueError("account ID must use the ACC#### format")
        return value


class IdentityDate(BaseModel):
    """Validated date used for DOB canonicalization."""

    model_config = ConfigDict(frozen=True)

    value: date


class AadhaarLast4(BaseModel):
    """Exactly four Aadhaar suffix digits."""

    model_config = ConfigDict(frozen=True)

    value: str

    @field_validator("value", mode="before")
    @classmethod
    def normalize_digits(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("Aadhaar suffix must be text")
        return "".join(character for character in value if character.isdigit())

    @field_validator("value")
    @classmethod
    def validate_length(cls, value: str) -> str:
        if len(value) != 4:
            raise ValueError("Aadhaar suffix must contain exactly four digits")
        return value


class Pincode(BaseModel):
    """Exactly six pincode digits."""

    model_config = ConfigDict(frozen=True)

    value: str

    @field_validator("value", mode="before")
    @classmethod
    def normalize_digits(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("pincode must be text")
        return "".join(character for character in value if character.isdigit())

    @field_validator("value")
    @classmethod
    def validate_length(cls, value: str) -> str:
        if len(value) != 6:
            raise ValueError("pincode must contain exactly six digits")
        return value


class IdentityCandidates(BaseModel):
    """Fields recovered from one identity turn."""

    model_config = ConfigDict(frozen=True)

    name: str | None = None
    dob: str | None = None
    aadhaar_last4: str | None = None
    pincode: str | None = None
    invalid_dob: bool = False
    invalid_aadhaar: bool = False
    invalid_pincode: bool = False


class AmountCandidates(BaseModel):
    """Amount data recovered from one user turn."""

    model_config = ConfigDict(frozen=True)

    amount: Decimal | None = None
    full_balance: bool = False
    invalid: bool = False


class CardCandidates(BaseModel):
    """Card fields recovered from one payment-details turn.

    A missing value is deliberately different from an invalid value.  The
    agent uses the latter to ask for a correction while retaining any other
    valid fields already collected.
    """

    model_config = ConfigDict(frozen=True)

    cardholder_name: str | None = None
    card_number: str | None = None
    cvv: str | None = None
    expiry_month: int | None = None
    expiry_year: int | None = None
    invalid_cardholder_name: bool = False
    invalid_card_number: bool = False
    invalid_cvv: bool = False
    invalid_expiry: bool = False


class NumericAmount(BaseModel):
    """A syntactically valid positive or negative amount with cent precision."""

    model_config = ConfigDict(frozen=True)

    value: Decimal

    @field_validator("value")
    @classmethod
    def validate_precision(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or abs(value.as_tuple().exponent) > 2:
            raise ValueError("amount must have no more than two decimal places")
        return value


class ValidatedPaymentAmount(BaseModel):
    """A positive amount that does not exceed the current account balance."""

    model_config = ConfigDict(frozen=True)

    amount: Decimal
    balance: Decimal = Field(ge=Decimal("0"))

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0:
            raise ValueError("amount must be greater than zero")
        if abs(value.as_tuple().exponent) > 2:
            raise ValueError("amount must have no more than two decimal places")
        return value

    @model_validator(mode="after")
    def validate_against_balance(self) -> "ValidatedPaymentAmount":
        if self.amount > self.balance:
            raise ValueError("amount cannot exceed the outstanding balance")
        return self


class AccountRecord(BaseModel):
    """Account response schema returned by the lookup API."""

    model_config = ConfigDict(extra="allow")

    account_id: str | None = None
    full_name: str | None = None
    dob: str | None = None
    aadhaar_last4: str | None = None
    pincode: str | None = None
    balance: Decimal | None = Field(default=None, ge=Decimal("0"))
    outstanding_balance: Decimal | None = Field(default=None, ge=Decimal("0"))

    @field_validator("account_id")
    @classmethod
    def validate_account_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return AccountId(value=value).value

    @field_validator("dob")
    @classmethod
    def validate_dob(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return IdentityDate(value=date.fromisoformat(value)).value.isoformat()
        except (TypeError, ValueError) as error:
            raise ValueError("DOB must be a valid ISO date") from error

    @field_validator("aadhaar_last4")
    @classmethod
    def validate_aadhaar(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return AadhaarLast4(value=value).value
        except ValueError as error:
            raise ValueError("Aadhaar suffix must contain exactly four digits") from error

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return Pincode(value=value).value
        except ValueError as error:
            raise ValueError("pincode must contain exactly six digits") from error

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_keys(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        aliases = {
            "id": "account_id",
            "name": "full_name",
            "date_of_birth": "dob",
        }
        for source, target in aliases.items():
            if target not in data and source in data:
                data[target] = data[source]
        if "balance" not in data and "outstanding_balance" in data:
            data["balance"] = data["outstanding_balance"]
        return data


class PaymentCard(BaseModel):
    """Card payload shape accepted by the payment API."""

    model_config = ConfigDict(extra="forbid")

    cardholder_name: str
    card_number: str
    cvv: str
    expiry_month: int = Field(ge=1, le=12)
    expiry_year: int = Field(ge=2000)

    @field_validator("cardholder_name")
    @classmethod
    def validate_cardholder_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("cardholder name is required")
        return value.strip()

    @field_validator("card_number")
    @classmethod
    def normalize_card_number(cls, value: str) -> str:
        normalized = value.replace(" ", "").replace("-", "")
        if not normalized.isdigit() or not 12 <= len(normalized) <= 19:
            raise ValueError("card number must contain 12 to 19 digits")
        checksum = 0
        doubled = False
        for digit in reversed(normalized):
            value_digit = int(digit)
            if doubled:
                value_digit *= 2
                if value_digit > 9:
                    value_digit -= 9
            checksum += value_digit
            doubled = not doubled
        if checksum % 10:
            raise ValueError("card number failed checksum validation")
        return normalized

    @field_validator("cvv")
    @classmethod
    def validate_cvv(cls, value: str) -> str:
        if not value.isdigit() or len(value) not in {3, 4}:
            raise ValueError("CVV must contain three or four digits")
        return value


class PaymentMethod(BaseModel):
    """Card payment method wrapper from the documented API contract."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["card"]
    card: PaymentCard


class PaymentRequest(BaseModel):
    """Documented process-payment request payload."""

    model_config = ConfigDict(extra="forbid")

    account_id: str
    amount: Decimal
    payment_method: PaymentMethod

    @field_validator("account_id")
    @classmethod
    def validate_account_id(cls, value: str) -> str:
        return AccountId(value=value).value

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0:
            raise ValueError("amount must be greater than zero")
        if abs(value.as_tuple().exponent) > 2:
            raise ValueError("amount must have no more than two decimal places")
        return value
