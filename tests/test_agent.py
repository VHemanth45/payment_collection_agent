import unittest

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

        self.assertEqual(
            response,
            {
                "message": (
                    "I still need your account ID to continue. "
                    "Please provide it, for example, ACC1001."
                )
            },
        )


    def test_conversation_state_is_local_to_each_agent_instance(self) -> None:
        first_agent = Agent()
        second_agent = Agent()

        first_agent.next("some input")
        first_response = first_agent.next("")
        second_response = second_agent.next("")

        self.assertEqual(first_response, second_response)
