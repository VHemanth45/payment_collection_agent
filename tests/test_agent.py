import unittest
import socket
import urllib.error

from api_client import AccountLookupResult, ApiClient, LookupStatus, PaymentStatus
from agent import Agent


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
            first, {"message": "Please provide your account ID to get started."}
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
