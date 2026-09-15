import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.assistant.service as service


def test_existing_followups_do_not_fall_back_to_static_prompts(monkeypatch):
    session = {
        "current_plan": {"name": "Fiber 100", "speed_mbps": 100, "price_inr": 799},
        "shown_existing_suggestions": [],
    }

    def fake_generate_json(*args, **kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(service, "generate_json", fake_generate_json)

    suggestions = service._generate_existing_followups(
        session,
        "I need more speed for my home office",
        "I can help with plans and add-ons for your connection.",
    )

    assert suggestions == []


def test_irrelevant_existing_message_avoids_hardcoded_guardrail_text(monkeypatch):
    session = {
        "existing_customer_verified": True,
        "customer": {"customer_id": "C001", "name": "Dev", "phone": "9876543210"},
        "current_plan": {"name": "Fiber 100", "speed_mbps": 100, "price_inr": 799},
        "conversation_history": [],
    }

    monkeypatch.setattr(service, "_is_existing_query_relevant", lambda text: False)

    def fake_generate(*args, **kwargs):
        return None

    monkeypatch.setattr(service, "generate", fake_generate)

    response = service._handle_existing_customer_message(
        session_id="sess-1",
        message="Can you help me plan my gym workout?",
        db=None,
        session=session,
        structured_fields=None,
        conversation_id="conv-1",
    )

    assert "Sorry, that's outside what I can help with" not in response["response"]
    assert "connection" in response["response"].lower()
    assert "support" in response["response"].lower()
