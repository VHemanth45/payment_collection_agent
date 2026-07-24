"""Deterministic user-facing message templates.

Only values explicitly permitted in the conversation contract are interpolated
into dynamic messages: account ID, outstanding/payment amount, and the API
transaction ID.  Identity and card fields are never template inputs.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from redaction import redact_text


ACCOUNT_PROMPT = "Please provide your account ID to get started."
ACCOUNT_CORRECTION_PROMPT = (
    "Please provide one valid account ID in the format ACC####, "
    "for example, ACC1001."
)
AMBIGUOUS_ACCOUNT_PROMPT = (
    "I found more than one possible account ID. Please send one account ID "
    "in the format ACC####."
)
FULL_NAME_PROMPT = "Thanks. Please provide your full name for verification."
SECONDARY_FACTOR_PROMPT = (
    "Please provide one verification detail: your date of birth, "
    "Aadhaar last four digits, or six-digit pincode."
)
INVALID_SECONDARY_FACTOR_PROMPT = (
    "Please provide a valid date of birth with a four-digit year, "
    "exactly four Aadhaar last-four digits, or a six-digit pincode."
)
VERIFIED_MESSAGE = "Your identity has been verified."
AMOUNT_PROMPT = "Please provide the amount you would like to pay."
AMOUNT_CORRECTION_PROMPT = (
    "Please provide a payment amount greater than ₹0.00, no more than the "
    "outstanding balance, and with no more than two decimal places."
)
AMOUNT_ACCEPTED_MESSAGE = "Your payment amount has been recorded."
CARD_DETAILS_PROMPT = (
    "Please provide your cardholder name, card number, CVV, and expiry date."
)
CARD_DETAILS_ACCEPTED_MESSAGE = "Your card details have been recorded."
PAYMENT_FAILURE_MESSAGE = "I couldn't complete the payment. Please try again later."
PAYMENT_UNCONFIRMED_MESSAGE = (
    "I couldn't confirm the payment status. Please contact support before "
    "trying again."
)
PAYMENT_RETRY_LIMIT_MESSAGE = (
    "I couldn't complete the payment after three attempts. "
    "This conversation is now closed."
)
INSUFFICIENT_BALANCE_MESSAGE = (
    "That amount is not available against the account balance. "
    "Please provide a smaller payment amount."
)
INVALID_CARD_PAYMENT_MESSAGE = (
    "The card number was not accepted. Please provide a different card "
    "number and the card details again."
)
INVALID_CVV_PAYMENT_MESSAGE = (
    "The CVV was not accepted. Please provide the card details again with "
    "a valid CVV."
)
INVALID_EXPIRY_PAYMENT_MESSAGE = (
    "The expiry date was not accepted. Please provide the card details "
    "again with a valid expiry date."
)
ZERO_BALANCE_MESSAGE = (
    "Your outstanding balance is ₹0.00. There is no payment amount to collect."
)
BALANCE_UNAVAILABLE_MESSAGE = (
    "Your identity has been verified, but I couldn't retrieve a valid "
    "outstanding balance. Please try again later."
)
VERIFICATION_FAILURE_MESSAGE = (
    "Those details did not match our records. Please provide your full "
    "name and one verification detail again."
)
VERIFICATION_LOCKED_MESSAGE = (
    "I couldn't verify your identity after three attempts. "
    "This conversation is now closed."
)
UNKNOWN_ACCOUNT_MESSAGE = (
    "I couldn't find that account ID. Please check it and send it again."
)
TIMEOUT_MESSAGE = "I couldn't retrieve that account right now. Please try again later."
CONNECTION_MESSAGE = "I couldn't connect to the account service. Please try again later."
MALFORMED_RESPONSE_MESSAGE = (
    "The account service returned an unexpected response. Please try again later."
)
UNAVAILABLE_MESSAGE = "Account lookup is temporarily unavailable. Please try again later."


def format_amount(amount: Decimal) -> str:
    """Format a permitted monetary value for a user-facing message."""

    display = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"₹{display:.2f}"


def balance_message(balance: Decimal, suffix: str) -> str:
    """Build the fixed balance disclosure and one fixed next-step message."""

    return (
        f"{VERIFIED_MESSAGE} Your outstanding balance is "
        f"{format_amount(balance)}. {suffix}"
    )


def payment_success(transaction_id: str, account_id: str, amount: Decimal) -> str:
    """Build the fixed, secret-free successful-payment recap."""

    safe_transaction_id = redact_text(transaction_id)
    return (
        f"Payment successful. Transaction ID: {safe_transaction_id}. "
        f"Account ID: {account_id}. Amount: {format_amount(amount)}. "
        "Status: successful."
    )


def local_card_failure_message(
    fields: list[str], *, fallback: str | None = None
) -> str:
    """Build the fixed correction message from safe field labels only."""

    safe_fields = list(fields)
    if not safe_fields and fallback == "card":
        safe_fields = ["card number"]
    if not safe_fields:
        return CARD_DETAILS_PROMPT
    if len(safe_fields) == 1:
        return f"Please provide a valid {safe_fields[0]} and the card details again."
    requested = ", ".join(safe_fields[:-1]) + f", and {safe_fields[-1]}"
    return f"Please correct {requested}, then provide the card details again."
