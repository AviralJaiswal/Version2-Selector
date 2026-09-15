import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from app.database import SessionLocal
from app.assistant.service import initialize_session, handle_message

db = SessionLocal()

print("=" * 70)
print("TEST 1: 'Hi' -> Natural Welcome & Dynamic Initial Suggestions")
print("=" * 70)
init_res = initialize_session()
sid = init_res["sessionId"]
greeting = init_res["response"]
suggs_turn0 = init_res.get("recommended_followups", [])
print("Session ID:", sid)
print("Initial Greeting:\n", greeting)
print("Turn 0 Suggestions:", suggs_turn0)
assert "thinking process" not in greeting.lower(), "Error: Thinking process in greeting!"
assert "<think>" not in greeting.lower(), "Error: <think> in greeting!"
assert len(greeting.strip()) > 10, "Greeting is empty!"
assert len(suggs_turn0) >= 2, "Expected at least 2 dynamic followups!"
print("[PASS] Natural initial greeting and dynamic suggestions.")

print("\n" + "=" * 70)
print("TEST 2: 'I want a gym plan' -> Understands Out-of-Scope Intent")
print("=" * 70)
res_gym = handle_message(sid, "I want a gym plan", db)
suggs_turn1 = res_gym.get("recommended_followups", [])
print("Mode:", res_gym.get("mode"), "| WorkflowState:", res_gym.get("workflowState"))
print("Gym Plan Response:\n", res_gym.get("response"))
print("Turn 1 Suggestions:", suggs_turn1)
assert res_gym.get("mode") == "RAG"
gym_resp_low = res_gym.get("response", "").lower()
# Must not dump broadband plans or assume broadband intent
assert "40 mbps" not in gym_resp_low and "1 gbps" not in gym_resp_low, "Incorrectly dumped broadband plans for gym plan!"
assert any(w in gym_resp_low for w in ("signal selector", "broadband", "fiber", "cannot", "unable", "specialize")), "Should politely explain scope limitation!"
print("[PASS] Handled unrelated gym query naturally without dumping broadband plans.")

print("\n" + "=" * 70)
print("TEST 3: 'I want a cricket plan' -> Ambiguous Query Handled Naturally (No Hardcoded Response)")
print("=" * 70)
res_cricket = handle_message(sid, "I want a cricket plan", db)
suggs_turn2 = res_cricket.get("recommended_followups", [])
print("Mode:", res_cricket.get("mode"), "| WorkflowState:", res_cricket.get("workflowState"))
print("Cricket Plan Response:\n", res_cricket.get("response"))
print("Turn 2 Suggestions:", suggs_turn2)
assert res_cricket.get("mode") == "RAG"
# Must not return the old hardcoded SIM recharge message
assert "While we do not offer standalone mobile SIM recharge packs" not in res_cricket.get("response", ""), "Found hardcoded response!"
print("[PASS] Ambiguous cricket query handled naturally without hardcoded messages.")

print("\n" + "=" * 70)
print("TEST 4: Follow-up Question -> Suggestions Change & Never Stale/Repeated")
print("=" * 70)
res_timeline = handle_message(sid, "How long does installation usually take?", db)
suggs_turn3 = res_timeline.get("recommended_followups", [])
print("Mode:", res_timeline.get("mode"), "| WorkflowState:", res_timeline.get("workflowState"))
print("Timeline Response:\n", res_timeline.get("response"))
print("Turn 3 Suggestions:", suggs_turn3)
assert res_timeline.get("mode") == "RAG"
assert "24" in res_timeline.get("response", "") or "48" in res_timeline.get("response", "") or "hours" in res_timeline.get("response", "")
# Crucial: Suggestions must change and not simply repeat previous turn
print("Turn 0 Suggestions:", suggs_turn0)
print("Turn 1 Suggestions:", suggs_turn1)
print("Turn 2 Suggestions:", suggs_turn2)
print("Turn 3 Suggestions:", suggs_turn3)
# Check that turn 3 is not identical to turn 2
assert set(suggs_turn3) != set(suggs_turn2), "Suggestions did not change across turns!"
print("[PASS] Suggestions changed dynamically based on conversation and did not repeat.")

print("\n" + "=" * 70)
print("TEST 5: Unrelated General Question -> Natural Response Without Looping")
print("=" * 70)
res_unrelated = handle_message(sid, "Can you recommend a good gym workout routine for beginners?", db)
print("Mode:", res_unrelated.get("mode"), "| WorkflowState:", res_unrelated.get("workflowState"))
print("General Question Response:\n", res_unrelated.get("response"))
assert res_unrelated.get("mode") == "RAG"
assert res_unrelated.get("workflowState") == "RAG_FAQ"
assert "Please share your complete street address" not in res_unrelated.get("response", "")
assert "PIN code is invalid" not in res_unrelated.get("response", "")
print("[PASS] Unrelated question handled naturally without forcing telecom workflows.")

print("\n" + "=" * 70)
print("TEST 6: Return to Telecom / New Connection Intent -> Starts Order Flow")
print("=" * 70)
res_order = handle_message(sid, "I want to get a new fiber connection for my home", db)
print("Mode:", res_order.get("mode"), "| WorkflowState:", res_order.get("workflowState"))
print("Order Flow Response:\n", res_order.get("response"))
assert res_order.get("mode") == "ORDER_FLOW"
assert res_order.get("workflowState") == "ADDRESS_QUALIFICATION"
assert "street address" in res_order.get("response", "").lower() or "address" in res_order.get("response", "").lower()
print("[PASS] Dynamic transition to ORDER_FLOW triggered only upon explicit ordering intent.")

print("\n" + "=" * 70)
print("TEST 7: Provide Full Address, Confirm Address, and Unlock Regional Plans")
print("=" * 70)
res_addr = handle_message(sid, "Flat 402, Sunshine Heights, 100 Feet Road, Indiranagar, Bengaluru, 560038", db)
print("Address Confirmation Response:\n", res_addr.get("response"))
assert res_addr.get("mode") == "ORDER_FLOW"
assert res_addr.get("workflowState") == "ADDRESS_CONFIRMATION"

res_conf = handle_message(sid, "Yes, that is my correct address", db)
print("Plans Discovered Response:\n", res_conf.get("response"))
assert res_conf.get("mode") == "ORDER_FLOW"
assert res_conf.get("workflowState") == "PLAN_SELECTION"
print("[PASS] Premise qualification and regional plan unlock completed.")

print("\n" + "=" * 70)
print("TEST 8: Voice Input Dynamic Flow Simulation")
print("=" * 70)
voice_sid = initialize_session()["sessionId"]
v_res1 = handle_message(voice_sid, "Do you have cricket plans?", db)
print("Voice RAG Mode:", v_res1.get("mode"))
assert v_res1.get("mode") == "RAG"

v_res2 = handle_message(voice_sid, "I want to book a new fiber connection", db)
print("Voice Order Mode:", v_res2.get("mode"))
assert v_res2.get("mode") == "ORDER_FLOW"
print("[PASS] Voice input follows identical intent-based dynamic routing.")

print("\n" + "*" * 70)
print("ALL 8 E2E WORKFLOW TESTS PASSED SUCCESSFULLY!")
print("*" * 70)
