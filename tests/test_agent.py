import unittest
import socket
import urllib.error
from datetime import date
from decimal import Decimal

from api_client import (
    AccountLookupResult,
    ApiClient,
    LookupStatus,
    PaymentResult,
    PaymentStatus,
)
from agent import Agent
from models import PaymentCard
from pydantic import ValidationError


class AgentConversationTests(unittest.TestCase):
    def test_new_conversation_requests_account_id(self) -> None:
        response = Agent().next("hello")

        self.assertEqual(set(response), {"message"})
        self.assertIsInstance(response["message"], str)
        self.assertIn("account ID", response["message"])
        self.assertNotIn("NEED_ACCOUNT", response["message"])


    def test_blank_input_returns_a_deterministic_actionable_prompt(self) -> None:
        agent = Agent()

        first = agent.next("")
        second = agent.next("   \n\t")

        self.assertEqual(first, second)
        self.assertEqual(
            first, {"message": Agent._ACCOUNT_PROMPT}
        )


    def test_irrelevant_input_keeps_requesting_the_account_id(self) -> None:
        agent = Agent()

        response = agent.next("What is the weather today?")

        self.assertEqual(response, {"message": Agent._ACCOUNT_CORRECTION_PROMPT})


    def test_conversation_state_is_local_to_each_agent_instance(self) -> None:
        first_agent = Agent()
        second_agent = Agent()

        first_agent.next("some input")
        first_response = first_agent.next("")
        second_response = second_agent.next("")

        self.assertEqual(first_response, second_response)


class FakeLookupClient:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.payment_calls = []

    def lookup_account(self, account_id):
        self.calls.append(account_id)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response

    def process_payment(self, payload):
        self.payment_calls.append(payload)
        return {"success": True, "transaction_id": "txn_test"}


class AccountLookupTests(unittest.TestCase):
    def test_account_id_is_normalized_and_looked_up_once(self) -> None:
        client = FakeLookupClient({"account_id": "ACC1001", "full_name": "Nithin Jain"})
        agent = Agent(lookup_client=client)

        response = agent.next("My account is acc 1001")
        repeated = agent.next("ACC1001")

        self.assertEqual(client.calls, ["ACC1001"])
        self.assertEqual(client.payment_calls, [])
        self.assertIn("full name", response["message"])


    def test_malformed_or_ambiguous_account_is_rejected_without_lookup(self) -> None:
        client = FakeLookupClient({"account_id": "ACC1001"})
        agent = Agent(lookup_client=client)

        malformed = agent.next("account number is 1001")
        ambiguous = agent.next("ACC1001 or ACC1002")

        self.assertIn("ACC####", malformed["message"])
        self.assertIn("one account ID", ambiguous["message"])
        self.assertEqual(client.calls, [])
        self.assertEqual(client.payment_calls, [])


class PaymentCardSchemaTests(unittest.TestCase):
    def test_card_number_validation_enforces_luhn_and_normalizes_spacing(self) -> None:
        card = PaymentCard(
            cardholder_name="Hemanth",
            card_number="4532 0151 1283 0366",
            cvv="123",
            expiry_month=12,
            expiry_year=2027,
        )

        self.assertEqual(card.card_number, "4532015112830366")

    def test_card_number_rejects_non_digits_and_wrong_length(self) -> None:
        with self.assertRaises(ValidationError):
            PaymentCard(
                cardholder_name="Hemanth",
                card_number="4532 0151 12",
                cvv="123",
                expiry_month=12,
                expiry_year=2027,
            )

    def test_unknown_account_can_be_resubmitted(self) -> None:
        client = FakeLookupClient(None)
        agent = Agent(lookup_client=client)

        response = agent.next("ACC1002")

        self.assertEqual(response["message"], Agent._UNKNOWN_ACCOUNT_MESSAGE)
        self.assertEqual(client.calls, ["ACC1002"])
        self.assertEqual(client.payment_calls, [])

    def test_lookup_timeout_connection_and_malformed_response_are_safe(self) -> None:
        cases = [
            (TimeoutError(), Agent._TIMEOUT_MESSAGE),
            (ConnectionError(), Agent._CONNECTION_MESSAGE),
            ("not a response", Agent._MALFORMED_RESPONSE_MESSAGE),
        ]

        for failure, expected_message in cases:
            with self.subTest(failure=type(failure).__name__):
                client = FakeLookupClient(failure)
                agent = Agent(lookup_client=client)

                response = agent.next("ACC1001")

                self.assertEqual(response["message"], expected_message)
                self.assertEqual(client.calls, ["ACC1001"])
                self.assertEqual(client.payment_calls, [])

    def test_different_account_replaces_pending_account(self) -> None:
        client = FakeLookupClient(
            {"account_id": "ACC1001", "full_name": "Nithin Jain"}
        )
        agent = Agent(lookup_client=client)

        agent.next("ACC1001")
        client.response = {"account_id": "ACC1002", "full_name": "Other Person"}
        response = agent.next("account id: acc 1002")

        self.assertEqual(client.calls, ["ACC1001", "ACC1002"])
        self.assertEqual(client.payment_calls, [])
        self.assertIn("full name", response["message"])

    def test_typed_lookup_outcomes_are_supported(self) -> None:
        client = FakeLookupClient(
            AccountLookupResult.found({"account_id": "ACC1001"})
        )

        response = Agent(client).next("ACC1001")

        self.assertIn("full name", response["message"])


class IdentityVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeLookupClient(
            {
                "account_id": "ACC1001",
                "full_name": "Nithin Jain",
                "dob": "1990-05-14",
                "aadhaar_last4": "4321",
                "pincode": "400001",
                "balance": 1250.75,
            }
        )
        self.agent = Agent(self.client)
        self.agent.next("ACC1001")

    def test_exact_name_and_one_secondary_factor_discloses_only_balance(
        self,
    ) -> None:
        name_response = self.agent.next("Nithin   Jain")
        verified_response = self.agent.next("Date of birth: 14th May 1990")

        self.assertIn("verification detail", name_response["message"])
        self.assertIn("1250.75", verified_response["message"])
        self.assertNotIn("1990-05-14", verified_response["message"])
        self.assertNotIn("4321", verified_response["message"])
        self.assertNotIn("400001", verified_response["message"])

    def test_secondary_factor_can_arrive_before_name(self) -> None:
        name_prompt = self.agent.next("DOB 1990-05-14")
        verified_response = self.agent.next("full name: Nithin Jain")

        self.assertEqual(name_prompt, {"message": Agent._FULL_NAME_PROMPT})
        self.assertIn("1250.75", verified_response["message"])

    def test_invalid_factor_before_name_remains_a_non_counting_correction(self) -> None:
        name_prompt = self.agent.next("DOB 1990-02-30")
        correction = self.agent.next("Nithin Jain")
        verified_response = self.agent.next("DOB 1990-05-14")

        self.assertEqual(name_prompt, {"message": Agent._FULL_NAME_PROMPT})
        self.assertEqual(
            correction, {"message": Agent._INVALID_SECONDARY_FACTOR_PROMPT}
        )
        self.assertIn("1250.75", verified_response["message"])

    def test_identity_fields_supplied_with_account_are_retained(self) -> None:
        client = FakeLookupClient(self.client.response)
        agent = Agent(client)

        response = agent.next(
            "account id ACC1001, my full name is Nithin Jain, "
            "and my DOB is 1990-05-14"
        )

        self.assertIn("1250.75", response["message"])
        self.assertEqual(client.calls, ["ACC1001"])

    def test_name_comparison_is_case_sensitive_and_failure_is_generic(self) -> None:
        self.agent.next("nithin jain")
        response = self.agent.next("pincode is 400001")

        self.assertEqual(response["message"], Agent._VERIFICATION_FAILURE_MESSAGE)
        self.assertNotIn("Nithin Jain", response["message"])
        self.assertNotIn("1990-05-14", response["message"])
        self.assertNotIn("4321", response["message"])
        self.assertNotIn("400001", response["message"])

    def test_invalid_and_ambiguous_dobs_are_rejected_without_a_failed_attempt(self) -> None:
        self.agent.next("Nithin Jain")

        impossible = self.agent.next("DOB 1990-02-30")
        ambiguous = self.agent.next("DOB May 14, 90")
        verified = self.agent.next("DOB 1990-05-14")

        self.assertEqual(
            impossible, {"message": Agent._INVALID_SECONDARY_FACTOR_PROMPT}
        )
        self.assertEqual(
            ambiguous, {"message": Agent._INVALID_SECONDARY_FACTOR_PROMPT}
        )
        self.assertIn("1250.75", verified["message"])

    def test_aadhaar_and_pincode_require_their_exact_lengths(self) -> None:
        self.agent.next("Nithin Jain")

        invalid = self.agent.next("Aadhaar last four is 123")
        valid = self.agent.next("Aadhaar last four is 4321")

        self.assertEqual(invalid, {"message": Agent._INVALID_SECONDARY_FACTOR_PROMPT})
        self.assertIn("1250.75", valid["message"])

    def test_three_complete_failures_lock_conversation_and_block_later_calls(self) -> None:
        for attempt in range(3):
            self.agent.next(f"Wrong Name {attempt}")
            response = self.agent.next("pincode 999999")

        self.assertEqual(response, {"message": Agent._VERIFICATION_LOCKED_MESSAGE})
        self.assertEqual(self.client.calls, ["ACC1001"])
        self.assertEqual(self.client.payment_calls, [])
        self.assertEqual(
            self.agent.next("ACC1002"),
            {"message": Agent._VERIFICATION_LOCKED_MESSAGE},
        )
        self.assertEqual(self.client.calls, ["ACC1001"])


class AmountCollectionTests(unittest.TestCase):
    def _verified_agent(self, balance=1250.75):
        client = FakeLookupClient(
            {
                "account_id": "ACC1001",
                "full_name": "Nithin Jain",
                "dob": "1990-05-14",
                "aadhaar_last4": "4321",
                "pincode": "400001",
                "balance": balance,
            }
        )
        agent = Agent(client)
        agent.next("ACC1001")
        agent.next("Nithin Jain")
        agent.next("DOB 1990-05-14")
        return agent, client

    def test_amount_is_not_disclosed_before_verification(self) -> None:
        client = FakeLookupClient(
            {
                "account_id": "ACC1001",
                "full_name": "Nithin Jain",
                "dob": "1990-05-14",
                "balance": 1250.75,
            }
        )
        agent = Agent(client)

        lookup = agent.next("ACC1001")
        name = agent.next("Nithin Jain")

        self.assertNotIn("1250.75", lookup["message"])
        self.assertNotIn("1250.75", name["message"])

    def test_numeric_currency_comma_and_worded_amounts_are_accepted(self) -> None:
        for value in ("500", "1,000", "₹500.00", "a thousand rupees"):
            with self.subTest(value=value):
                agent, client = self._verified_agent()
                response = agent.next(value)

                self.assertEqual(response, {"message": Agent._AMOUNT_ACCEPTED_MESSAGE})
                self.assertEqual(client.payment_calls, [])

    def test_full_balance_request_uses_the_looked_up_balance(self) -> None:
        agent, client = self._verified_agent()

        response = agent.next("Please pay the outstanding balance")

        self.assertEqual(response, {"message": Agent._AMOUNT_ACCEPTED_MESSAGE})
        self.assertEqual(agent._amount, 1250.75)
        self.assertEqual(client.payment_calls, [])


    def test_invalid_zero_negative_precision_and_over_balance_amounts_are_local(self) -> None:
        for value in ("0", "-1", "500.123", "1250.76"):
            with self.subTest(value=value):
                agent, client = self._verified_agent()

                response = agent.next(value)

                self.assertEqual(response, {"message": Agent._AMOUNT_CORRECTION_PROMPT})
                self.assertEqual(client.payment_calls, [])

    def test_valid_amount_supplied_before_amount_prompt_is_retained(self) -> None:
        agent, client = self._verified_agent()

        # The amount is supplied while identity verification is still pending.
        agent = Agent(client)
        agent.next("ACC1001")
        agent.next("Nithin Jain")
        agent.next("I want to pay ₹500")
        response = agent.next("DOB 1990-05-14")

        self.assertIn(Agent._AMOUNT_ACCEPTED_MESSAGE, response["message"])
        self.assertEqual(agent._amount, 500)
        self.assertEqual(client.payment_calls, [])

    def test_zero_balance_discloses_zero_and_does_not_accept_payment_amount(self) -> None:
        agent, client = self._verified_agent(balance=0)

        self.assertIn("₹0.00", agent._amount_collection_message())
        response = agent.next("100")

        self.assertEqual(response, {"message": Agent._AMOUNT_CORRECTION_PROMPT})
        self.assertEqual(client.payment_calls, [])


class CardCollectionTests(unittest.TestCase):
    def _amount_collected_agent(self):
        client = FakeLookupClient(
            {
                "account_id": "ACC1001",
                "full_name": "Nithin Jain",
                "dob": "1990-05-14",
                "balance": 1250.75,
            }
        )
        agent = Agent(client)
        for turn in ("ACC1001", "Nithin Jain", "DOB 1990-05-14", "500"):
            agent.next(turn)
        return agent, client

    def test_complete_card_can_be_collected_in_one_turn(self) -> None:
        agent, client = self._amount_collected_agent()
        future_year = date.today().year + 1

        response = agent.next(
            f"cardholder name: Someone Else, card number: 4532 0151 1283 0366, "
            f"CVV: one two three, expiry: December {future_year}"
        )

        self.assertIn("txn_test", response["message"])
        self.assertIn("ACC1001", response["message"])
        self.assertIn("₹500.00", response["message"])
        payload = client.payment_calls[0]
        self.assertEqual(payload["account_id"], "ACC1001")
        self.assertEqual(payload["amount"].quantize(Decimal("0.01")), Decimal("500.00"))
        self.assertEqual(
            payload["payment_method"]["card"]["card_number"],
            "4532015112830366",
        )
        self.assertIsNone(agent._cardholder_name)
        self.assertIsNone(agent._card_number)
        self.assertIsNone(agent._cvv)
        self.assertIsNone(agent._expiry_month)
        self.assertIsNone(agent._expiry_year)
        self.assertEqual(len(client.payment_calls), 1)

    def test_partial_card_fields_are_retained_and_only_missing_fields_are_requested(
        self,
    ) -> None:
        agent, client = self._amount_collected_agent()

        first = agent.next(
            "cardholder name: Someone Else; card number 4532-0151-1283-0366"
        )
        self.assertIn("CVV", first["message"])
        self.assertNotIn("expiry date", first["message"])
        self.assertNotIn("cardholder", first["message"])
        self.assertNotIn("card number", first["message"])

        second = agent.next("expiry 12/27")
        self.assertEqual(
            second, {"message": "What is the CVV? Enter 3 or 4 digits."}
        )

        response = agent.next("one two three")
        self.assertIn("txn_test", response["message"])
        self.assertEqual(len(client.payment_calls), 1)
        repeat = agent.next("please pay again")
        self.assertEqual(repeat, response)
        self.assertEqual(len(client.payment_calls), 1)

    def test_invalid_card_data_is_rejected_locally_without_echoing_secrets(self) -> None:
        agent, client = self._amount_collected_agent()

        response = agent.next(
            "cardholder name: Someone Else, card number: 4111 1111 1111 1112, "
            "CVV: 12, expiry: 01/25"
        )

        self.assertIn("card number", response["message"])
        self.assertNotIn("CVV", response["message"])
        self.assertNotIn("expiry date", response["message"])
        self.assertNotIn("4111111111111112", response["message"])
        self.assertNotIn("12", response["message"])
        self.assertEqual(client.payment_calls, [])


class PaymentCompletionTests(unittest.TestCase):
    def _amount_collected_agent(self, client):
        agent = Agent(client)
        for turn in ("ACC1001", "Nithin Jain", "DOB 1990-05-14", "500"):
            agent.next(turn)
        return agent

    def test_three_argument_payment_client_receives_normalized_payload(self) -> None:
        class ThreeArgumentClient:
            def __init__(self):
                self.lookup_calls = []
                self.payment_calls = []

            def lookup_account(self, account_id):
                self.lookup_calls.append(account_id)
                return {
                    "account_id": "ACC1001",
                    "full_name": "Nithin Jain",
                    "dob": "1990-05-14",
                    "balance": 1250.75,
                }

            def process_payment(self, account_id, amount, card):
                self.payment_calls.append((account_id, amount, card))
                return {"success": True, "transaction_id": "txn_3arg"}

        client = ThreeArgumentClient()
        agent = self._amount_collected_agent(client)

        response = agent.next(
            "cardholder name: Someone Else, card number: 4532-0151-1283-0366, "
            "CVV: 123, expiry: 12/27"
        )

        self.assertIn("txn_3arg", response["message"])
        self.assertEqual(len(client.payment_calls), 1)
        account_id, amount, card = client.payment_calls[0]
        self.assertEqual(account_id, "ACC1001")
        self.assertEqual(amount, Decimal("500.00"))
        self.assertEqual(card["card_number"], "4532015112830366")
        self.assertEqual(card["expiry_month"], 12)
        self.assertEqual(card["expiry_year"], 2027)

    def test_card_fields_are_cleared_when_payment_client_raises(self) -> None:
        class RaisingClient(FakeLookupClient):
            def process_payment(self, payload):
                self.payment_calls.append(payload)
                raise RuntimeError("transport failed")

        client = RaisingClient(
            {
                "account_id": "ACC1001",
                "full_name": "Nithin Jain",
                "dob": "1990-05-14",
                "balance": 1250.75,
            }
        )
        agent = self._amount_collected_agent(client)

        response = agent.next(
            "cardholder name: Someone Else, card number: 4532-0151-1283-0366, "
            "CVV: 123, expiry: 12/27"
        )

        self.assertEqual(response, {"message": Agent._PAYMENT_FAILURE_MESSAGE})
        self.assertEqual(len(client.payment_calls), 1)
        self.assertIsNone(agent._cardholder_name)
        self.assertIsNone(agent._card_number)
        self.assertIsNone(agent._cvv)
        self.assertIsNone(agent._expiry_month)
        self.assertIsNone(agent._expiry_year)


class PaymentFailureTests(unittest.TestCase):
    class SequencedClient:
        def __init__(self, results):
            self.results = list(results)
            self.payment_calls = []

        def lookup_account(self, account_id):
            return {
                "account_id": account_id,
                "full_name": "Nithin Jain",
                "dob": "1990-05-14",
                "balance": 1250.75,
            }

        def process_payment(self, payload):
            self.payment_calls.append(payload)
            return self.results.pop(0)

    @staticmethod
    def _card_turn():
        return (
            "cardholder name: Someone Else, card number: 4532-0151-1283-0366, "
            "CVV: 123, expiry: 12/27"
        )

    def _amount_collected_agent(self, results):
        client = self.SequencedClient(results)
        agent = Agent(client)
        for turn in ("ACC1001", "Nithin Jain", "DOB 1990-05-14", "500"):
            agent.next(turn)
        return agent, client

    def test_insufficient_balance_preserves_verified_flow_for_smaller_amount(self) -> None:
        agent, client = self._amount_collected_agent(
            [
                PaymentResult(status=PaymentStatus.INSUFFICIENT_BALANCE),
                {"success": True, "transaction_id": "txn_smaller"},
            ]
        )

        response = agent.next(self._card_turn())
        self.assertIn("smaller", response["message"])
        self.assertEqual(agent._state.name, "VERIFIED_NEED_AMOUNT")
        self.assertIsNone(agent._cardholder_name)
        self.assertIsNone(agent._card_number)
        self.assertIsNone(agent._cvv)
        self.assertIsNone(agent._expiry_month)
        self.assertIsNone(agent._expiry_year)

        self.assertEqual(agent.next("400"), {"message": Agent._AMOUNT_ACCEPTED_MESSAGE})
        success = agent.next(self._card_turn())
        self.assertIn("txn_smaller", success["message"])
        self.assertEqual(len(client.payment_calls), 2)

    def test_api_invalid_card_requests_correction_without_echoing_card_data(self) -> None:
        agent, client = self._amount_collected_agent(
            [
                PaymentResult(status=PaymentStatus.INVALID_CARD),
                {"success": True, "transaction_id": "txn_corrected"},
            ]
        )

        response = agent.next(self._card_turn())
        self.assertIn("card number", response["message"])
        self.assertNotIn("4532015112830366", response["message"])
        self.assertNotIn("123", response["message"])
        self.assertIsNone(agent._cardholder_name)
        self.assertIsNone(agent._card_number)
        self.assertIsNone(agent._cvv)
        self.assertIsNone(agent._expiry_month)
        self.assertIsNone(agent._expiry_year)

        success = agent.next(self._card_turn())
        self.assertIn("txn_corrected", success["message"])
        self.assertEqual(len(client.payment_calls), 2)

    def test_api_invalid_cvv_clears_card_context_before_retry(self) -> None:
        agent, client = self._amount_collected_agent(
            [
                PaymentResult(status=PaymentStatus.INVALID_CVV),
                {"success": True, "transaction_id": "txn_cvv_corrected"},
            ]
        )

        response = agent.next(self._card_turn())
        self.assertIn("CVV", response["message"])
        self.assertIsNone(agent._cardholder_name)
        self.assertIsNone(agent._card_number)
        self.assertIsNone(agent._cvv)
        self.assertIsNone(agent._expiry_month)
        self.assertIsNone(agent._expiry_year)

        success = agent.next(
            "cardholder name: Someone Else, card number: 4532-0151-1283-0366, "
            "CVV: 654, expiry: 12/2027"
        )
        self.assertIn("txn_cvv_corrected", success["message"])
        self.assertEqual(len(client.payment_calls), 2)

    def test_api_invalid_expiry_clears_card_context_before_retry(self) -> None:
        agent, client = self._amount_collected_agent(
            [
                PaymentResult(status=PaymentStatus.INVALID_EXPIRY),
                {"success": True, "transaction_id": "txn_expiry_corrected"},
            ]
        )

        response = agent.next(
            "cardholder name: Someone Else, card number: 4532-0151-1283-0366, "
            "CVV: 123, expiry: 12/2027"
        )
        self.assertIn("expiry", response["message"])
        self.assertIsNone(agent._cardholder_name)
        self.assertIsNone(agent._card_number)
        self.assertIsNone(agent._cvv)
        self.assertIsNone(agent._expiry_month)
        self.assertIsNone(agent._expiry_year)

        success = agent.next(
            "cardholder name: Someone Else, card number: 4532-0151-1283-0366, "
            "CVV: 123, expiry: 12/2028"
        )
        self.assertIn("txn_expiry_corrected", success["message"])
        self.assertEqual(len(client.payment_calls), 2)

    def test_three_retryable_failures_close_and_block_later_payment_calls(self) -> None:
        agent, client = self._amount_collected_agent(
            [
                PaymentResult(status=PaymentStatus.INVALID_CVV),
                PaymentResult(status=PaymentStatus.INVALID_CVV),
                PaymentResult(status=PaymentStatus.INVALID_CVV),
            ]
        )

        for attempt in range(3):
            response = agent.next(self._card_turn())
            if attempt < 2:
                self.assertIn("CVV", response["message"])
            else:
                self.assertEqual(
                    response, {"message": Agent._PAYMENT_RETRY_LIMIT_MESSAGE}
                )

        self.assertEqual(len(client.payment_calls), 3)
        self.assertEqual(
            agent.next(self._card_turn()),
            {"message": Agent._PAYMENT_RETRY_LIMIT_MESSAGE},
        )
        self.assertEqual(len(client.payment_calls), 3)

    def test_timeout_is_terminal_and_is_not_retried(self) -> None:
        agent, client = self._amount_collected_agent(
            [PaymentResult(status=PaymentStatus.TIMEOUT)]
        )

        response = agent.next(self._card_turn())
        self.assertEqual(response, {"message": Agent._PAYMENT_UNCONFIRMED_MESSAGE})
        self.assertIsNone(agent._card_number)
        self.assertEqual(
            agent.next(self._card_turn()),
            {"message": Agent._PAYMENT_FAILURE_MESSAGE},
        )
        self.assertEqual(len(client.payment_calls), 1)

    def test_complete_local_card_failure_counts_but_does_not_call_payment_api(self) -> None:
        agent, client = self._amount_collected_agent(
            [{"success": True, "transaction_id": "txn_after_correction"}]
        )

        invalid = agent.next(
            "cardholder name: Someone Else, card number: 4111 1111 1111 1112, "
            "CVV: 12, expiry: 01/25"
        )
        self.assertIn("card number", invalid["message"])
        self.assertEqual(agent._payment_retry_attempts, 1)
        self.assertEqual(client.payment_calls, [])
        self.assertIsNone(agent._card_number)

        success = agent.next(self._card_turn())
        self.assertIn("txn_after_correction", success["message"])
        self.assertEqual(len(client.payment_calls), 1)


class ApiClientTests(unittest.TestCase):
    class Response:
        def __init__(self, status, body):
            self.status = status
            self.body = body

        def read(self):
            return self.body

        def close(self):
            pass

    def test_lookup_posts_documented_payload_to_documented_endpoint(self) -> None:
        requests = []

        def opener(request, timeout):
            requests.append((request, timeout))
            return self.Response(
                200,
                b'{"account_id":"ACC1001","full_name":"Nithin Jain",'
                b'"dob":"1990-05-14","aadhaar_last4":"4321",'
                b'"pincode":"400001","balance":1250.75}',
            )

        result = ApiClient(opener=opener).lookup_account("ACC1001")

        self.assertEqual(result.status, LookupStatus.FOUND)
        request, timeout = requests[0]
        self.assertEqual(
            request.full_url,
            "https://se-payment-verification-api.service.external.usea2.aws.prodigaltech.com/api/lookup-account",
        )
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.headers["Content-type"], "application/json")
        self.assertEqual(request.data, b'{"account_id": "ACC1001"}')
        self.assertEqual(timeout, 10.0)

    def test_lookup_maps_documented_404_and_transport_failures(self) -> None:
        def not_found_opener(request, timeout):
            return self.Response(
                404,
                b'{"error_code":"account_not_found",'
                b'"message":"No account found"}',
            )

        def timeout_opener(request, timeout):
            raise TimeoutError

        def wrapped_timeout_opener(request, timeout):
            raise urllib.error.URLError(socket.timeout())

        self.assertEqual(
            ApiClient(opener=not_found_opener).lookup_account("ACC9999").status,
            LookupStatus.NOT_FOUND,
        )
        self.assertEqual(
            ApiClient(opener=timeout_opener).lookup_account("ACC1001").status,
            LookupStatus.TIMEOUT,
        )
        self.assertEqual(
            ApiClient(opener=wrapped_timeout_opener)
            .lookup_account("ACC1001")
            .status,
            LookupStatus.TIMEOUT,
        )

    def test_payment_uses_documented_payload_and_maps_success(self) -> None:
        requests = []

        def opener(request, timeout):
            requests.append(request)
            return self.Response(200, b'{"success":true,"transaction_id":"txn_1"}')

        result = ApiClient(opener=opener).process_payment(
            "ACC1001",
            500,
            {
                "cardholder_name": "Nithin Jain",
                "card_number": "4532015112830366",
                "cvv": "123",
                "expiry_month": 12,
                "expiry_year": 2027,
            },
        )

        self.assertEqual(result.status, PaymentStatus.SUCCESS)
        self.assertEqual(result.transaction_id, "txn_1")
        self.assertEqual(
            requests[0].full_url,
            "https://se-payment-verification-api.service.external.usea2.aws.prodigaltech.com/api/process-payment",
        )
