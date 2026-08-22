from __future__ import annotations

import unittest
from unittest.mock import patch

from llm.practical_agent import PracticalAgent, SafeCalculator


class PracticalAgentTests(unittest.TestCase):
    def test_safe_calculator_accepts_arithmetic(self):
        self.assertEqual(SafeCalculator.evaluate("18 * 7 + 4"), 130.0)

    def test_safe_calculator_rejects_code(self):
        with self.assertRaises(ValueError):
            SafeCalculator.evaluate("__import__('os').system('whoami')")

    def test_whitelist_rejects_unknown_tool(self):
        with self.assertRaises(ValueError):
            PracticalAgent._execute("run_shell", {}, [])

    def test_tool_call_loop(self):
        agent = PracticalAgent()
        agent.base_url, agent.api_key, agent.model = "https://example.invalid/v1", "key", "test-model"
        responses = [
            {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "calculate", "arguments": '{"expression":"18*7"}'}}]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "计算结果为 126。"}}]},
        ]
        with patch.object(agent, "_complete", side_effect=responses):
            result = agent.run({"question": "计算"}, "计算18乘7", [])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["actions"][0]["output"]["value"], 126.0)


if __name__ == "__main__":
    unittest.main()
