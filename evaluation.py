"""Project-level, deterministic evaluation notes for the public agent seam."""

from __future__ import annotations

from datetime import date
from typing import Any

from agent import Agent
from api_client import PaymentResult, PaymentStatus
from main import DemoApiClient
from messages import AMOUNT_PROMPT
from redaction import redact_for_report


CARD_TURN = (
    "cardholder name: Demo Cardholder, card number: 4532-0151-1283-0366, "
    "CVV: 123, expiry: 12/{year}"
)


class EvaluationClient(DemoApiClient):
    """Demo service with observable, test-only call traces and result overrides."""

    def __init__(self, payment_results: list[Any] | None = None) -> None:
        self.lookup_calls: list[str] = []
        self.payment_calls: list[dict[str, Any]] = []
        self.payment_results = list(payment_results or [])

    def lookup_account(self, account_id: str) -> dict[str, Any] | None:
        self.lookup_calls.append(account_id)
        return super().lookup_account(account_id)

    def process_payment(self, payload: dict[str, Any]) -> Any:
        self.payment_calls.append(payload)
        if self.payment_results:
            return self.payment_results.pop(0)
        return super().process_payment(payload)


def _complete_verified_agent(client: EvaluationClient) -> Agent:
    agent = Agent(client)
    agent.next("account id ACC1001")
    agent.next("Nithin Jain")
    agent.next("DOB 1990-05-14")
    return agent


def run_evaluation() -> dict[str, Any]:
    """Run representative project-level checks and return safe aggregate notes."""

    future_year = date.today().year + 1
    card_turn = CARD_TURN.format(year=future_year)

    happy_client = EvaluationClient()
    happy_agent = _complete_verified_agent(happy_client)
    happy_messages = [
        happy_agent.next("pay the outstanding balance")["message"],
        happy_agent.next(card_turn)["message"],
    ]

    lockout_client = EvaluationClient()
    lockout_agent = Agent(lockout_client)
    lockout_agent.next("ACC1001")
    lockout_messages: list[str] = []
    for index in range(3):
        lockout_agent.next(f"Wrong Name {index}")
        lockout_messages.append(lockout_agent.next("pincode 999999")["message"])
    lookup_count_after_lockout = len(lockout_client.lookup_calls)

    retry_client = EvaluationClient(
        [
            PaymentResult(status=PaymentStatus.INVALID_CVV),
            PaymentResult(status=PaymentStatus.INVALID_CVV),
            PaymentResult(status=PaymentStatus.INVALID_CVV),
        ]
    )
    retry_agent = _complete_verified_agent(retry_client)
    retry_agent.next("500")
    retry_messages = [retry_agent.next(card_turn)["message"] for _ in range(3)]

    partial_client = EvaluationClient()
    partial_agent = Agent(partial_client)
    partial_messages = [
        partial_agent.next("ACC1001")["message"],
        partial_agent.next("Nithin Jain")["message"],
        partial_agent.next("I want to pay ₹500")["message"],
        partial_agent.next("DOB 1990-05-14")["message"],
    ]

    safe_trace = redact_for_report(
        {"messages": happy_messages, "payload": happy_client.payment_calls[0]}
    )
    safe_text = str(safe_trace)

    return {
        "happy_path_success": "Payment successful." in happy_messages[-1],
        "strict_verification_rejection": len(lockout_messages) == 3
        and "conversation is now closed" in lockout_messages[-1],
        "api_call_correctness": len(happy_client.lookup_calls) == 1
        and len(happy_client.payment_calls) == 1
        and happy_client.payment_calls[0]["account_id"] == "ACC1001",
        "retry_limit_enforcement": len(retry_client.payment_calls) == 3
        and "conversation is now closed" in retry_messages[-1],
        "sensitive_data_leakage_count": sum(
            secret in safe_text
            for secret in ("1990-05-14", "4321", "400001", "123", "4532015112830366")
        ),
        "unnecessary_amount_reprompts": sum(
            message == AMOUNT_PROMPT for message in partial_messages[2:]
        ),
        "no_post_lockout_lookup": lookup_count_after_lockout == 1,
    }


def main(argv: list[str] | None = None) -> int:
    del argv
    report = run_evaluation()
    print("Payment collection agent evaluation")
    for name, value in report.items():
        label = name.replace("_", " ").capitalize()
        print(f"- {label}: {value}")
    return 0 if all(
        value == 0 if name.endswith("count") or name.endswith("reprompts") else value
        for name, value in report.items()
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
