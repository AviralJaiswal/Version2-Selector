import unittest
from unittest.mock import patch

from app.assistant.plan_recommendation import recommend_plan_conversational


SAMPLE_PLANS = [
    {"plan_id": "PLN-CHN-100", "name": "Singara Chennai 100M", "speed_mbps": 100, "price_inr": 499, "type": "Fiber", "description": "Budget plan"},
    {"plan_id": "PLN-CHN-300", "name": "Marina Fiber Speed 300M", "speed_mbps": 300, "price_inr": 799, "type": "Fiber", "description": "High speed WFH plan"},
    {"plan_id": "PLN-CHN-1G", "name": "Chennai Giga Super 1G", "speed_mbps": 1000, "price_inr": 1499, "type": "Fiber", "description": "Ultimate gaming plan"},
]


class PlanRecommendationTests(unittest.TestCase):
    @patch("app.assistant.plan_recommendation.generate", return_value='{"recommended_plan_name": "Marina Fiber Speed 300M", "short_intro": "Based on your requirements, here is the best recommended plan for you:"}')
    def test_llm_conversational_recommendation(self, mock_generate):
        intro, rec_plan = recommend_plan_conversational(SAMPLE_PLANS, "I work from home, which is best?")
        self.assertIn("recommended plan for you", intro)
        self.assertIsNotNone(rec_plan)
        self.assertEqual(rec_plan["plan_id"], "PLN-CHN-300")

    @patch("app.assistant.plan_recommendation.generate", side_effect=Exception("LLM Timeout"))
    def test_fallback_recommendation_gaming(self, mock_generate):
        intro, rec_plan = recommend_plan_conversational(SAMPLE_PLANS, "Best plan for low ping gaming?")
        self.assertIn("recommended for you", intro)
        self.assertIsNotNone(rec_plan)

    @patch("app.assistant.plan_recommendation.generate", side_effect=Exception("LLM Timeout"))
    def test_fallback_recommendation_budget(self, mock_generate):
        intro, rec_plan = recommend_plan_conversational(SAMPLE_PLANS, "What is the cheap budget option?")
        self.assertIn("recommended for you", intro)
        self.assertIsNotNone(rec_plan)


if __name__ == "__main__":
    unittest.main()

