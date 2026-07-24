import unittest

from agent import Agent
from api_client import PaymentResult, PaymentStatus
from redaction import redact_call_trace, redact_for_report, redact_payload


CARD_TURN = (
    "cardholder name: Someone Else, card number: 4532-0151-1283-0366, "
    "CVV: 123, expiry: 12/27"
)


class SecurityClient:
    def __init__(self, payment_result):
        self.payment_result = payment_result
        self.payment_calls = []

    def lookup_account(self, account_id):
        return {
            "account_id": account_id,
            "full_name": "Nithin Jain",
            "dob": "1990-05-14",
            "aadhaar_last4": "4321",
            "pincode": "400001",
            "balance": 1250.75,
        }

    def process_payment(self, payload):
        self.payment_calls.append(payload)
        if isinstance(self.payment_result, BaseException):
            raise self.payment_result
        return self.payment_result


def amount_collected_agent(payment_result):
    client = SecurityClient(payment_result)
    agent = Agent(client)
    for turn in ("ACC1001", "Nithin Jain", "DOB 1990-05-14", "500"):
        agent.next(turn)
    return agent, client


class SensitiveDataTests(unittest.TestCase):
    def test_report_redaction_masks_card_numbers_and_omits_cvv(self):
        trace = {
            "payload": {
                "card_number": "4532015112830366",
                "cvv": "123",
                "expiry_month": 12,
                "dob": "1990-05-14",
            },
            "message": "card 4532 0151 1283 0366",
        }

        redacted = redact_for_report(trace)

        self.assertEqual(redacted["payload"]["card_number"], "****0366")
        self.assertNotIn("cvv", redacted["payload"])
        self.assertNotIn("123", str(redacted))
        self.assertNotIn("4532015112830366", str(redacted))
        self.assertNotIn("1990-05-14", str(redacted))
        self.assertEqual(redact_payload(trace), redacted)
        self.assertEqual(redact_call_trace(trace), redacted)

    def test_success_clears_card_and_account_identity_context(self):
        agent, client = amount_collected_agent(
            {"success": True, "transaction_id": "txn_safe"}
        )

        response = agent.next(CARD_TURN)

        self.assertIn("txn_safe", response["message"])
        self.assertIsNone(agent._account)
        self.assertIsNone(agent._name_candidate)
        self.assertIsNone(agent._dob_candidate)
        self.assertIsNone(agent._aadhaar_candidate)
        self.assertIsNone(agent._pincode_candidate)
        self.assertIsNone(agent._card_number)
        self.assertIsNone(agent._cvv)
        self.assertEqual(len(client.payment_calls), 1)

    def test_recoverable_payment_failure_keeps_card_context_for_retry(self):
        agent, _ = amount_collected_agent(
            PaymentResult(status=PaymentStatus.INVALID_CVV)
        )

        agent.next(CARD_TURN)

        self.assertIsNotNone(agent._account)
        self.assertIsNotNone(agent._cardholder_name)
        self.assertIsNotNone(agent._card_number)
        self.assertIsNotNone(agent._cvv)
        self.assertIsNotNone(agent._expiry_month)
        self.assertIsNotNone(agent._expiry_year)

    def test_terminal_failure_and_exception_clear_sensitive_context(self):
        for result in (
            PaymentResult(status=PaymentStatus.TIMEOUT),
            RuntimeError("transport failed"),
        ):
            with self.subTest(result=type(result).__name__):
                agent, client = amount_collected_agent(result)
                agent.next(CARD_TURN)

                self.assertIsNone(agent._account)
                self.assertIsNone(agent._name_candidate)
                self.assertIsNone(agent._dob_candidate)
                self.assertIsNone(agent._card_number)
                self.assertIsNone(agent._cvv)
                self.assertEqual(len(client.payment_calls), 1)

    def test_verification_lockout_clears_stored_account_identity(self):
        client = SecurityClient({"success": True, "transaction_id": "unused"})
        agent = Agent(client)
        agent.next("ACC1001")

        for attempt in range(3):
            agent.next(f"Wrong Name {attempt}")
            response = agent.next("pincode 999999")

        self.assertEqual(response, {"message": Agent._VERIFICATION_LOCKED_MESSAGE})
        self.assertIsNone(agent._account)
        self.assertIsNone(agent._dob_candidate)
        self.assertEqual(client.payment_calls, [])


if __name__ == "__main__":
    unittest.main()
