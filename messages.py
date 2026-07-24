"""Deterministic user-facing message templates.

Only values explicitly permitted in the conversation contract are interpolated
into dynamic messages: account ID, outstanding/payment amount, and the API
transaction ID.  Identity and card fields are never template inputs.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from redaction import redact_text


ACCOUNT_PROMPT = "Let's get started. What is your account ID? (Example: ACC1002)"
ACCOUNT_CORRECTION_PROMPT = (
    "I couldn't read that as one account ID. Please enter one in the ACC#### "
    "format, like ACC1002."
)
AMBIGUOUS_ACCOUNT_PROMPT = (
    "I found more than one possible account ID. Please send one account ID "
    "in the format ACC####."
)
FULL_NAME_PROMPT = (
    "Thanks. What is your full name exactly as it appears on the account?"
)
SECONDARY_FACTOR_PROMPT = (
    "To verify you, provide one verification detail: DOB (YYYY-MM-DD), "
    "Aadhaar last four digits, or your six-digit pincode. You can send just "
    "the digits."
)
INVALID_SECONDARY_FACTOR_PROMPT = (
    "That verification detail doesn't look right. Send DOB as YYYY-MM-DD, "
    "exactly four Aadhaar last-four digits, or exactly six pincode digits."
)
VERIFIED_MESSAGE = "Your identity has been verified."
AMOUNT_PROMPT = (
    "How much would you like to pay? Enter an amount such as ₹100, or say "
    "'pay the full balance'."
)
AMOUNT_CORRECTION_PROMPT = (
    "Please provide a payment amount greater than ₹0.00, no more than the "
    "outstanding balance, and with no more than two decimal places."
)
AMOUNT_ACCEPTED_MESSAGE = (
    "Got it — your payment amount is recorded. What name should appear on the card?"
)
CARD_DETAILS_PROMPT = (
    "What name should appear on the card?"
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
    "The card number was not accepted. Please enter a different card number."
)
INVALID_CVV_PAYMENT_MESSAGE = (
    "The CVV was not accepted. Please enter a valid CVV."
)
INVALID_EXPIRY_PAYMENT_MESSAGE = (
    "The expiry date was not accepted. Please enter a valid expiry date."
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
    return f"Please provide a valid {safe_fields[0]}."


def card_field_prompt(field: str) -> str:
    """Ask for exactly one missing card field."""

    prompts = {
        "cardholder name": "What name should appear on the card?",
        "card number": "What is the card number? Enter 12–19 digits.",
        "CVV": "What is the CVV? Enter 3 or 4 digits.",
        "expiry date": "What is the card expiry date? Use MM/YYYY.",
    }
    return prompts.get(field, CARD_DETAILS_PROMPT)
