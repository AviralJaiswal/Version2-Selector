import unittest
from unittest.mock import patch, MagicMock

from app.assistant.service import (
    handle_message,
    initialize_session,
    _is_order_intent_trigger,
)
from app.chat.session import session_store


class AssistantServiceTests(unittest.TestCase):
    def setUp(self):
        session_store._data.clear()

    @patch("app.assistant.service.generate_dynamic_greeting", return_value="Dynamic Welcome!")
    def test_session_welcome_dynamic_greeting(self, mock_greeting):
        result = initialize_session("test-welcome")
        self.assertEqual(result["response"], "Dynamic Welcome!")
        self.assertEqual(result["mode"], "RAG")
        self.assertTrue(result["conversationId"].startswith("CONV-"))
        self.assertIsNotNone(session_store.get("test-welcome"))

    @patch("app.assistant.service.generate_dynamic_greeting", return_value="Custom existing welcome.")
    def test_existing_profile_welcome(self, mock_gen):
        result = initialize_session("existing-session", profile="existing")
        self.assertEqual(result["response"], "Custom existing welcome.")
        self.assertEqual(result["mode"], "ORDER_FLOW")

    def test_order_intent_trigger(self):
        self.assertTrue(_is_order_intent_trigger("600013"))
        self.assertTrue(_is_order_intent_trigger("I want a new fiber connection"))
        self.assertFalse(_is_order_intent_trigger("What is fiber broadband?"))

    @patch("app.assistant.service.query_faq_collection", return_value=["Fiber is optical connection."])
    @patch("app.assistant.service.generate_grounded_faq_answer", return_value="Fiber broadband is optical cable internet.")
    def test_knowledge_message_routes_to_rag(self, mock_answer, mock_query):
        initialize_session("rag-session")
        result = handle_message("rag-session", "What is fiber broadband?", db=MagicMock())
        self.assertEqual(result["mode"], "RAG")
        self.assertIn("Fiber", result["response"])

    @patch("app.assistant.service.qualify", return_value={"serviceable": True, "requires_full_address": True, "address_qualified": False, "city": "Chennai", "state": "Tamil Nadu"})
    def test_pincode_routes_to_order_flow(self, mock_qualify):
        initialize_session("order-session")
        result = handle_message("order-session", "600013", db=MagicMock())
        self.assertEqual(result["mode"], "ORDER_FLOW")
        self.assertEqual(session_store.get("order-session")["mode"], "ORDER_FLOW")

    @patch("app.assistant.service.qualify", return_value={"serviceable": True, "requires_full_address": True, "address_qualified": False, "city": "Chennai", "state": "Tamil Nadu"})
    @patch("app.assistant.service._generate_pincode_only_prompt", return_value="PIN code 600013 is serviceable! A PIN code alone is not sufficient, please provide your complete street address.")
    def test_pincode_only_calls_llm_for_complete_address(self, mock_llm_prompt, mock_qualify):
        initialize_session("pincode-only-session")
        result = handle_message("pincode-only-session", "600013", db=MagicMock())
        self.assertEqual(result["mode"], "ORDER_FLOW")
        self.assertIn("complete street address", result["response"])
        mock_llm_prompt.assert_called_once_with("600013", "Chennai", "Tamil Nadu")

    @patch("app.services.welcome_service.generate")
    def test_welcome_service_prompts_for_complete_address(self, mock_llm_gen):
        from app.services.welcome_service import generate_dynamic_greeting
        mock_llm_gen.return_value = "Hello! Welcome to Signal Selector. Please share your complete street address."
        greeting = generate_dynamic_greeting()
        self.assertIn("complete street address", greeting)
        call_args = mock_llm_gen.call_args[0][0]
        self.assertIn("complete street address", call_args)
        self.assertIn("Do NOT ask for just a 6-digit pincode", call_args)

    @patch("app.assistant.service.generate", return_value="Your address at Kisan Chowk, 201012 Ghaziabad, India is verified as serviceable.\nConfirming this allows us to proceed with showing the available fiber plans in your region.")
    def test_address_confirmation_prompt_enforces_question(self, mock_generate):
        from app.assistant.service import _generate_address_confirmation_prompt
        prompt_res = _generate_address_confirmation_prompt("Kisan Chowk, 201012 Ghaziabad, India")
        lines = prompt_res.split("\n")
        self.assertIn("?", lines[0])
        self.assertIn("Is this your correct address?", lines[0])
        self.assertIn("Confirming this allows us to proceed", lines[1])

    @patch("app.assistant.service.classify_conversation_route", return_value="TRANSACTION")
    @patch("app.assistant.service.recommend", return_value=[{"plan_id": "P100", "name": "Basic 100", "price_inr": 499}])
    @patch("app.assistant.service.qualify", return_value={"serviceable": True, "requires_full_address": False, "address_qualified": True, "formatted_address": "Kisan Chowk, 201012 Ghaziabad", "city": "Ghaziabad", "state": "Uttar Pradesh"})
    @patch("app.assistant.service._generate_address_confirmation_prompt", return_value="Your address at Kisan Chowk is verified. Is this your correct address?\nConfirming allows us to show plans.")
    @patch("app.assistant.service._generate_escape_reset_message", return_value="No problem! Please share your correct complete street address.")
    def test_deny_address_resets_state_and_hides_plans(self, mock_reset_prompt, mock_confirm_prompt, mock_qualify, mock_recommend, mock_classify_route):
        initialize_session("deny-session")

        # Step 1: Provide valid street address & pincode
        res1 = handle_message("deny-session", "Kisan Chowk 201012", db=MagicMock())
        self.assertEqual(res1["intent"], "CONFIRM_ADDRESS_PROMPT")
        self.assertTrue(session_store.get("deny-session")["awaiting_address_confirmation"])

        # Step 2: User responds with "No"
        res2 = handle_message("deny-session", "No", db=MagicMock())
        self.assertEqual(res2["intent"], "PROMPT_STREET_ADDRESS")
        self.assertIn("correct complete street address", res2["response"])
        self.assertEqual(res2["sources"], [])

        # Check updated state
        updated_state = res2["updatedState"]
        self.assertFalse(updated_state["address_qualified"])
        self.assertFalse(updated_state["address_confirmed"])
        self.assertFalse(updated_state["plans_shown"])
        self.assertEqual(updated_state["catalog_plans"], [])
        self.assertEqual(updated_state["recommended_plans"], [])

    def test_yes_response_triggers_recommendation_survey(self):
        from app.assistant.service import classify_plan_selection_intent
        self.assertEqual(classify_plan_selection_intent("yes"), "RECOMMENDATION_REQUEST")
        self.assertEqual(classify_plan_selection_intent("yes please"), "RECOMMENDATION_REQUEST")
        self.assertEqual(classify_plan_selection_intent("sure"), "RECOMMENDATION_REQUEST")
        self.assertEqual(classify_plan_selection_intent("recommendation"), "RECOMMENDATION_REQUEST")


if __name__ == "__main__":
    unittest.main()



