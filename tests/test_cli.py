import unittest
from io import StringIO

from main import build_agent, run_cli


class CliTests(unittest.TestCase):
    def test_demo_cli_runs_a_conversation_without_network_or_secret_echo(self):
        input_stream = StringIO(
            "ACC1001\n"
            "Nithin Jain\n"
            "DOB 1990-05-14\n"
            "pay the outstanding balance\n"
            "cardholder name: Demo Cardholder, card number: "
            "4532 0151 1283 0366, CVV: 123, expiry: 12/2027\n"
            ":quit\n"
        )
        output_stream = StringIO()

        result = run_cli(
            build_agent(),
            input_stream=input_stream,
            output_stream=output_stream,
            show_banner=False,
        )

        output = output_stream.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("Payment successful", output)
        self.assertIn("demo-txn-001", output)
        for secret in ("1990-05-14", "4321", "400001", "123", "4532015112830366"):
            self.assertNotIn(secret, output)


if __name__ == "__main__":
    unittest.main()
