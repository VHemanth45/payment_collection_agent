import unittest
from datetime import date
from decimal import Decimal
from typing import Any

from agent import Agent
from api_client import PaymentResult, PaymentStatus
from evaluation import EvaluationClient
from redaction import redact_call_trace


CARD_NUMBER = "4532015112830366"


def card_turn(*, year: int | None = None, cvv: str = "123") -> str:
    expiry_year = year or date.today().year + 1
    return (
        "cardholder name: Demo Cardholder, card number: 4532-0151-1283-0366, "
        f"CVV: {cvv}, expiry: 12/{expiry_year}"
    )


class EndToEndTests(unittest.TestCase):
    def _verified(self, client: EvaluationClient) -> Agent:
        agent = Agent(client)
        agent.next("My account is acc 1001")
        agent.next("Nithin Jain")
        agent.next("Date of birth: 14th May 1990")
        return agent

    def _payment_ready(self, client: EvaluationClient, amount: str = "500") -> Agent:
        agent = self._verified(client)
        agent.next(amount)
        return agent

    def test_successful_full_balance_payment_has_correct_calls_and_safe_recap(self):
        client = EvaluationClient()
        agent = self._verified(client)

        balance = agent.next("Please pay the full outstanding balance")
        success = agent.next(card_turn())

        self.assertEqual(balance["message"], "Your payment amount has been recorded.")
        self.assertIn("Payment successful", success["message"])
        self.assertIn("₹1250.75", success["message"])
        self.assertIn("demo-txn-001", success["message"])
        self.assertEqual(client.lookup_calls, ["ACC1001"])
        self.assertEqual(len(client.payment_calls), 1)
        self.assertEqual(client.payment_calls[0]["amount"], Decimal("1250.75"))
        self.assertEqual(
            client.payment_calls[0]["payment_method"]["card"]["card_number"],
            CARD_NUMBER,
        )
        for secret in ("1990-05-14", "4321", "400001", "123", CARD_NUMBER):
            self.assertNotIn(secret, success["message"])

    def test_successful_partial_payment_reuses_amount_supplied_before_prompt(self):
        client = EvaluationClient()
        agent = Agent(client)
        responses = [
            agent.next("ACC1001")["message"],
            agent.next("Nithin Jain")["message"],
            agent.next("I want to pay ₹500")["message"],
            agent.next("DOB 1990-05-14")["message"],
            agent.next(card_turn())["message"],
        ]

        self.assertIn("₹1250.75", responses[3])
        self.assertNotIn("Please provide the amount", responses[3])
        self.assertIn("Payment successful", responses[-1])
        self.assertEqual(len(client.lookup_calls), 1)
        self.assertEqual(len(client.payment_calls), 1)
        self.assertEqual(client.payment_calls[0]["amount"], Decimal("500.00"))

    def test_three_failed_verification_attempts_lock_out_without_payment_or_lookup(self):
        client = EvaluationClient()
        agent = Agent(client)
        agent.next("ACC1001")
        final_message = ""
        for index in range(3):
            agent.next(f"Wrong Name {index}")
            final_message = agent.next("pincode 999999")["message"]

        self.assertIn("conversation is now closed", final_message)
        self.assertEqual(client.lookup_calls, ["ACC1001"])
        self.assertEqual(client.payment_calls, [])
        self.assertEqual(agent.next("ACC1002")["message"], final_message)
        self.assertEqual(client.lookup_calls, ["ACC1001"])

    def test_out_of_order_amount_and_card_input_wait_for_safe_phase_order(self):
        client = EvaluationClient()
        agent = Agent(client)
        early_amount = agent.next("I want to pay ₹500")
        early_card = agent.next(
            "Cardholder name: Demo Cardholder, card number: "
            "4532-0151-1283-0366, CVV: 123, expiry: 12/"
            f"{date.today().year + 1}"
        )
        account = agent.next("ACC1001")
        name = agent.next("Nithin Jain")
        verified = agent.next("DOB 1990-05-14")
        success = agent.next("CVV 123, expiry 12/" + str(date.today().year + 1))

        self.assertIn("account ID", early_amount["message"])
        self.assertIn("account ID", early_card["message"])
        self.assertIn("full name", account["message"])
        self.assertIn("verification detail", name["message"])
        self.assertIn("payment amount has been recorded", verified["message"])
        self.assertIn("Payment successful", success["message"])
        self.assertEqual(len(client.payment_calls), 1)

    def test_lookup_failures_never_progress_to_payment(self):
        failures: list[Any] = [
            None,
            TimeoutError(),
            ConnectionError(),
            "malformed response",
        ]
        expected_fragments = (
            "couldn't find",
            "couldn't retrieve",
            "couldn't connect",
            "unexpected response",
        )
        for failure, expected in zip(failures, expected_fragments):
            with self.subTest(failure=type(failure).__name__):
                class FailureClient(EvaluationClient):
                    def lookup_account(self, account_id: str):
                        self.lookup_calls.append(account_id)
                        if isinstance(failure, BaseException):
                            raise failure
                        return failure

                client = FailureClient()
                agent = Agent(client)
                response = agent.next("ACC1001")
                self.assertIn(expected, response["message"])
                self.assertEqual(client.lookup_calls, ["ACC1001"])
                self.assertEqual(client.payment_calls, [])

    def test_payment_failures_support_recovery_and_prevent_duplicate_ambiguous_charge(self):
        client = EvaluationClient(
            [
                PaymentResult(status=PaymentStatus.INSUFFICIENT_BALANCE),
                {"success": True, "transaction_id": "txn-smaller"},
            ]
        )
        agent = self._payment_ready(client)

        insufficient = agent.next(card_turn())
        agent.next("400")
        success = agent.next(card_turn())

        self.assertIn("smaller", insufficient["message"])
        self.assertIn("txn-smaller", success["message"])
        self.assertEqual(len(client.payment_calls), 2)

        timeout_client = EvaluationClient(
            [PaymentResult(status=PaymentStatus.TIMEOUT)]
        )
        timeout_agent = self._payment_ready(timeout_client)
        timeout = timeout_agent.next(card_turn())
        repeat = timeout_agent.next(card_turn())
        self.assertIn("couldn't confirm", timeout["message"])
        self.assertNotIn("Payment successful", repeat["message"])
        self.assertEqual(len(timeout_client.payment_calls), 1)

    def test_payment_retry_limit_closes_after_three_api_failures(self):
        client = EvaluationClient(
            [
                PaymentResult(status=PaymentStatus.INVALID_CVV),
                PaymentResult(status=PaymentStatus.INVALID_CVV),
                PaymentResult(status=PaymentStatus.INVALID_CVV),
            ]
        )
        agent = self._payment_ready(client)

        messages = [agent.next(card_turn())["message"] for _ in range(3)]
        fourth = agent.next(card_turn())["message"]

        self.assertIn("CVV", messages[0])
        self.assertIn("conversation is now closed", messages[-1])
        self.assertEqual(messages[-1], fourth)
        self.assertEqual(len(client.payment_calls), 3)

    def test_zero_balance_and_leap_day_dob_are_handled_without_unsafe_payment(self):
        zero_client = EvaluationClient()
        zero_agent = Agent(zero_client)
        zero_agent.next("ACC1003")
        zero_agent.next("Priya Agarwal")
        zero_response = zero_agent.next("DOB 1992-08-10")
        zero_follow_up = zero_agent.next("100")

        self.assertIn("₹0.00", zero_response["message"])
        self.assertIn("no payment amount", zero_response["message"])
        self.assertNotIn("Payment successful", zero_follow_up["message"])
        self.assertEqual(zero_client.payment_calls, [])

        leap_client = EvaluationClient()
        leap_agent = Agent(leap_client)
        leap_agent.next("ACC1004")
        leap_agent.next("Rahul Mehta")
        leap_response = leap_agent.next("DOB 1988-02-29")
        self.assertIn("₹3200.50", leap_response["message"])

    def test_repeated_completion_blank_noisy_and_ambiguous_inputs_are_deterministic(self):
        client = EvaluationClient()
        agent = Agent(client)
        self.assertIn("account ID", agent.next(" ")["message"])
        self.assertIn("ACC####", agent.next("What is the weather?")["message"])
        self.assertIn("one account ID", agent.next("ACC1001 or ACC1002")["message"])
        self.assertEqual(client.lookup_calls, [])

        agent = self._payment_ready(client)
        success = agent.next(card_turn())
        repeated = agent.next("please pay again")
        self.assertEqual(repeated, success)
        self.assertEqual(len(client.payment_calls), 1)

    def test_redacted_payload_reporting_contains_no_sensitive_values(self):
        client = EvaluationClient()
        agent = self._payment_ready(client)
        agent.next(card_turn(cvv="123"))
        report = redact_call_trace(
            {"calls": client.payment_calls, "message": "card 4532 0151 1283 0366"}
        )
        report_text = str(report)
        self.assertIn("****0366", report_text)
        for secret in (CARD_NUMBER, "123", "1990-05-14", "4321", "400001"):
            self.assertNotIn(secret, report_text)


if __name__ == "__main__":
    unittest.main()
