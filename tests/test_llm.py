import json
import unittest
from unittest.mock import MagicMock, patch

import requests

from app.assistant.llm import LLMError, chat, classify_conversation_route, generate_json, llm_available


class LLMAdapterTests(unittest.TestCase):
    def test_llm_available_requires_openrouter_key(self):
        with patch("app.assistant.llm.get_settings") as settings:
            settings.return_value.llm_provider = "openrouter"
            settings.return_value.gemini_api_key = None
            settings.return_value.openai_api_key = None
            settings.return_value.openrouter_api_key = "test-key"
            self.assertTrue(llm_available())
            settings.return_value.openrouter_api_key = None
            self.assertFalse(llm_available())

    @patch("app.assistant.llm.requests.post")
    @patch("app.assistant.llm.llm_available", return_value=True)
    @patch("app.assistant.llm.get_settings")
    def test_valid_openrouter_call(self, settings, _available, post):
        settings.return_value.gemini_api_key = None
        settings.return_value.openai_api_key = None
        settings.return_value.llm_provider = "openrouter"
        settings.return_value.openrouter_api_key = "test-key"
        settings.return_value.openrouter_base_url = "https://openrouter.ai/api/v1"
        settings.return_value.llm_model = "openai/gpt-5"
        settings.return_value.llm_max_tokens = 1000
        settings.return_value.api_base_url = "http://localhost:8000"
        settings.return_value.app_name = "Signal Selector"
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"choices": [{"message": {"content": "Hello there"}}]}
        post.return_value = response

        result = chat([{"role": "user", "content": "Hi"}])
        self.assertEqual(result, "Hello there")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["max_tokens"], 1000)

    @patch("app.assistant.llm._call_gemini_rest", return_value=None)
    @patch("app.assistant.llm.requests.post")
    @patch("app.assistant.llm.llm_available", return_value=True)
    @patch("app.assistant.llm.get_settings")
    def test_invalid_model_404(self, settings, _available, post, _gemini):
        settings.return_value.gemini_api_key = None
        settings.return_value.openai_api_key = None
        settings.return_value.openrouter_api_key = "test-key"
        settings.return_value.openrouter_base_url = "https://openrouter.ai/api/v1"
        settings.return_value.llm_model = "invalid/model"
        settings.return_value.llm_max_tokens = 1000
        settings.return_value.api_base_url = "http://localhost:8000"
        settings.return_value.app_name = "Signal Selector"
        response = MagicMock()
        response.status_code = 404
        response.reason = "Not Found"
        response.text = '{"error":"model not found"}'
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
        post.return_value = response

        with self.assertRaises(LLMError) as ctx:
            chat([{"role": "user", "content": "Hi"}], raise_on_error=True)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("invalid/model", ctx.exception.model or "")

    @patch("app.assistant.llm._call_gemini_rest", return_value=None)
    @patch("app.assistant.llm.requests.post")
    @patch("app.assistant.llm.llm_available", return_value=True)
    @patch("app.assistant.llm.get_settings")
    def test_402_credit_error(self, settings, _available, post, _gemini):
        settings.return_value.gemini_api_key = None
        settings.return_value.openai_api_key = None
        settings.return_value.openrouter_api_key = "test-key"
        settings.return_value.openrouter_base_url = "https://openrouter.ai/api/v1"
        settings.return_value.llm_model = "openai/gpt-5"
        settings.return_value.llm_max_tokens = 1000
        settings.return_value.api_base_url = "http://localhost:8000"
        settings.return_value.app_name = "Signal Selector"
        response = MagicMock()
        response.status_code = 402
        response.reason = "Payment Required"
        response.text = '{"error":"insufficient credits"}'
        post.return_value = response

        with self.assertRaises(LLMError) as ctx:
            chat([{"role": "user", "content": "Hi"}], raise_on_error=True)
        self.assertEqual(ctx.exception.status_code, 402)
        self.assertIn("credit", ctx.exception.user_message().lower())

    @patch("app.assistant.llm.requests.post")
    @patch("app.assistant.llm.llm_available", return_value=True)
    @patch("app.assistant.llm.get_settings")
    def test_timeout(self, settings, _available, post):
        settings.return_value.openrouter_api_key = "test-key"
        settings.return_value.openrouter_base_url = "https://openrouter.ai/api/v1"
        settings.return_value.llm_model = "openai/gpt-5"
        settings.return_value.llm_max_tokens = 1000
        settings.return_value.api_base_url = "http://localhost:8000"
        settings.return_value.app_name = "Signal Selector"
        post.side_effect = requests.Timeout("timed out")

        with self.assertRaises(LLMError):
            chat([{"role": "user", "content": "Hi"}], raise_on_error=True)

    @patch("app.assistant.llm.requests.post")
    @patch("app.assistant.llm.llm_available", return_value=True)
    @patch("app.assistant.llm.get_settings")
    def test_malformed_json_response(self, settings, _available, post):
        settings.return_value.openrouter_api_key = "test-key"
        settings.return_value.openrouter_base_url = "https://openrouter.ai/api/v1"
        settings.return_value.llm_model = "openai/gpt-5"
        settings.return_value.llm_max_tokens = 1000
        settings.return_value.api_base_url = "http://localhost:8000"
        settings.return_value.app_name = "Signal Selector"
        response = MagicMock()
        response.status_code = 200
        response.text = "not-json"
        response.json.side_effect = ValueError("invalid json")
        post.return_value = response

        with self.assertRaises(LLMError):
            chat([{"role": "user", "content": "Hi"}], raise_on_error=True)

    @patch("app.assistant.llm.requests.post")
    @patch("app.assistant.llm.llm_available", return_value=True)
    @patch("app.assistant.llm.get_settings")
    def test_missing_choices(self, settings, _available, post):
        settings.return_value.openrouter_api_key = "test-key"
        settings.return_value.openrouter_base_url = "https://openrouter.ai/api/v1"
        settings.return_value.llm_model = "openai/gpt-5"
        settings.return_value.llm_max_tokens = 1000
        settings.return_value.api_base_url = "http://localhost:8000"
        settings.return_value.app_name = "Signal Selector"
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"choices": []}
        post.return_value = response

        with self.assertRaises(LLMError):
            chat([{"role": "user", "content": "Hi"}], raise_on_error=True)

    @patch("app.assistant.llm.generate_json")
    def test_router_transaction(self, generate_json):
        generate_json.return_value = {"route": "TRANSACTION"}
        route = classify_conversation_route("I want a new broadband connection", {"mode": "WELCOME"})
        self.assertEqual(route, "TRANSACTION")

    @patch("app.assistant.llm.generate_json")
    def test_router_knowledge(self, generate_json):
        generate_json.return_value = {"route": "KNOWLEDGE"}
        route = classify_conversation_route("What is fiber broadband?", {"mode": "WELCOME"})
        self.assertEqual(route, "KNOWLEDGE")


if __name__ == "__main__":
    unittest.main()
