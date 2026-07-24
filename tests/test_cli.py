import unittest
from io import StringIO
from unittest.mock import patch

from agent import Agent
from evaluation import EvaluationClient
from main import build_agent, run_cli


class CliTests(unittest.TestCase):
    def test_cli_agent_uses_the_http_api_client_by_default(self):
        client = EvaluationClient()
        with patch("main.ApiClient", return_value=client) as api_constructor:
            agent = build_agent()
            response = agent.next("ACC1002")

        api_constructor.assert_called_once_with()
        self.assertIn("full name", response["message"])
        self.assertEqual(client.lookup_calls, ["ACC1002"])

    def test_cli_runs_a_conversation_without_network_or_secret_echo(self):
        input_stream = StringIO(
            "ACC1001\n"
            "Nithin Jain\n"
            "DOB 1990-05-14\n"
            "pay the outstanding balance\n"
            "Nithin Jain, 4532 0151 1283 0366, 123, 12/2027\n"
            ":quit\n"
        )
        output_stream = StringIO()

        result = run_cli(
            Agent(EvaluationClient()),
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
