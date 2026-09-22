import uuid
import json
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)

def run_scenario(name, messages):
    print(f"\n{'='*80}\nSCENARIO: {name}\n{'='*80}")
    session_id = str(uuid.uuid4())
    for msg in messages:
        payload = {
            "session_id": session_id,
            "message": msg.get("text", ""),
            "language": msg.get("language", "en")
        }
        if "structured_fields" in msg:
            payload["structured_fields"] = msg["structured_fields"]
            
        print(f"\nUser: {msg.get('text', '<action>')}")
        
        response = client.post("/api/v1/ai/rag/query", json=payload)
        if response.status_code == 200:
            data = response.json().get("data", {})
            print(f"Bot:  {data.get('answer', '')}")
            print(f"      [mode={data.get('mode')}, intent={data.get('intent')}, state={data.get('workflow_state')}]")
        else:
            print(f"ERROR: {response.status_code} - {response.text}")

if __name__ == "__main__":
    # Test 1: Spelling mistake in generic intent
    run_scenario("Typos in Intent", [
        {"text": "i wand now cnnectn"}
    ])

    # Test 2: Address with "no" and typos
    run_scenario("Complex Address", [
        {"text": "I need a new connection"},
        {"text": "flt no 402, ght titania, hyderabad, 500084"}
    ])

    # Test 3: Changing mind midway
    run_scenario("Changing Mind", [
        {"text": "I want to order a new connection"},
        {"text": "500084"},
        {"text": "wait nevermind cancel that"}
    ])

    # Test 4: Existing Customer Flow
    run_scenario("Existing Customer Flow", [
        {"text": "I already have a connection"},
        {"text": "9876543210"},
        {"text": "i want to upgrade my plan"}
    ])

    # Test 5: Pincode with spaces
    run_scenario("Pincode with spaces", [
        {"text": "I need a new connection"},
        {"text": "my pin is 500 084"}
    ])
    
    # Test 6: Non-English + English STT
    run_scenario("Hindi to English", [
        {"text": "mujhe naya broadband chahiye"},
        {"text": "mera address hai plot no 12, ameerpet, 500038"}
    ])
