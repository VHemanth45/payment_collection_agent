import unittest
from datetime import date

from agent import Agent
from extractor import ExtractionGroup, EXTRACTION_SCHEMAS


class LookupAndPaymentClient:
    def __init__(self):
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
        return {"success": True, "transaction_id": "txn_extractor"}


class RecordingExtractor:
    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def extract(self, request):
        self.calls.append(request)
        return self.responses.get(request.group, {})


class HybridExtractionTests(unittest.TestCase):
    def test_only_missing_current_group_is_extracted_with_forced_tool_choice(self):
        client = LookupAndPaymentClient()
        extractor = RecordingExtractor(
            {
                ExtractionGroup.IDENTITY: {
                    "name": None,
                    "dob": None,
                    "aadhaar_last4": None,
                    "pincode": None,
                },
                ExtractionGroup.PAYMENT: {"amount": None},
                ExtractionGroup.CARD: {
                    "cardholder_name": None,
                    "card_number": None,
                    "cvv": None,
                    "expiry_month": None,
                    "expiry_year": None,
                },
            }
        )
        agent = Agent(client, extractor=extractor)

        agent.next("ACC1001")
        self.assertEqual([call.group for call in extractor.calls], [ExtractionGroup.IDENTITY])
        request = extractor.calls[0]
        self.assertEqual(request.schema, EXTRACTION_SCHEMAS[ExtractionGroup.IDENTITY])
        self.assertEqual(
            request.tool_choice,
            {"type": "function", "function": {"name": "extract_identity"}},
        )

        # Regex already has all identity fields, so no second identity call.
        agent.next("Nithin Jain, DOB 1990-05-14")
        self.assertEqual(len(extractor.calls), 1)

        # The amount turn is complete on the regex fast path; card extraction
        # is not allowed to run until the card state is reached.
        agent.next("500")
        self.assertEqual(len(extractor.calls), 1)

        agent.next("cardholder name: Someone Else, card number 4532-0151-1283-0366")
        self.assertEqual([call.group for call in extractor.calls], [
            ExtractionGroup.IDENTITY,
            ExtractionGroup.CARD,
        ])

    def test_missing_extractor_fields_are_null_and_do_not_change_state(self):
        client = LookupAndPaymentClient()
        extractor = RecordingExtractor(
            {ExtractionGroup.IDENTITY: {"name": None, "dob": None}}
        )
        agent = Agent(client, extractor=extractor)

        response = agent.next("ACC1001")

        self.assertEqual(response, {"message": Agent._FULL_NAME_PROMPT})
        self.assertIsNone(agent._name_candidate)
        self.assertIsNone(agent._dob_candidate)
        self.assertEqual(extractor.calls[0].group, ExtractionGroup.IDENTITY)

    def test_extractor_cannot_override_better_regex_values_or_use_response_text(self):
        client = LookupAndPaymentClient()
        extractor = RecordingExtractor(
            {
                ExtractionGroup.IDENTITY: {
                    "name": "Wrong Person",
                    "dob": "1990-05-14",
                    "aadhaar_last4": None,
                    "pincode": None,
                }
            }
        )
        agent = Agent(client, extractor=extractor)
        agent.next("ACC1001")

        # The regex name wins over extractor output, while the structured DOB
        # fills the missing secondary factor and deterministically verifies.
        response = agent.next("full name: Nithin Jain")

        self.assertIn("1250.75", response["message"])
        self.assertNotIn("Wrong Person", response["message"])
        self.assertEqual(len(extractor.calls), 2)

        # A free-form string is not interpreted as structured extractor data.
        extractor.responses[ExtractionGroup.PAYMENT] = "pay five hundred"
        agent.next("500")
        self.assertEqual(len(client.payment_calls), 0)

    def test_out_of_order_regex_card_fields_are_retained_without_skipping_phases(self):
        client = LookupAndPaymentClient()
        extractor = RecordingExtractor(
            {
                ExtractionGroup.IDENTITY: {"name": None, "dob": None},
                ExtractionGroup.CARD: {
                    "cardholder_name": None,
                    "card_number": None,
                    "cvv": None,
                    "expiry_month": None,
                    "expiry_year": None,
                },
            }
        )
        agent = Agent(client, extractor=extractor)

        # Card data arrives before account and verification.  It is retained,
        # but no payment is attempted until the normal phases complete.
        agent.next("cardholder name: Someone Else, card number: 4532-0151-1283-0366")
        agent.next("ACC1001")
        agent.next("Nithin Jain")
        agent.next("DOB 1990-05-14")
        agent.next("500")
        response = agent.next(f"CVV 123, expiry 12/{date.today().year + 1}")

        self.assertIn("txn_extractor", response["message"])
        self.assertEqual(len(client.payment_calls), 1)
        self.assertEqual(
            client.payment_calls[0]["payment_method"]["card"]["card_number"],
            "4532015112830366",
        )


if __name__ == "__main__":
    unittest.main()

