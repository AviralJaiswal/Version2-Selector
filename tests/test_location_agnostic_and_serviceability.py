import unittest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.address import Address
from app.models.plan import Plan
from app.assistant.service import (
    handle_message,
    initialize_session,
    _is_order_intent_trigger,
)
from app.services.address_service import qualify
from app.chat.session import session_store


class LocationAgnosticAndServiceabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(cls.engine)
        cls.SessionLocal = sessionmaker(bind=cls.engine)

    def setUp(self):
        session_store._data.clear()
        self.db = self.SessionLocal()
        # Seed test addresses
        self.db.add(Address(
            pincode="110001",
            city="New Delhi",
            state="Delhi",
            region_type="metro",
            serviceable=True,
            max_speed_available_mbps=1000,
            fdh_id="FDH-DEL-01",
            mst_id="MST-DEL-01",
            olt_id="OLT-DEL-01"
        ))
        self.db.add(Address(
            pincode="110006",
            city="New Delhi",
            state="Delhi",
            region_type="metro",
            serviceable=False,
            max_speed_available_mbps=0,
            fdh_id="FDH-DEL-02",
            mst_id="MST-DEL-02",
            olt_id="OLT-DEL-02"
        ))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_general_plan_queries_stay_in_rag_without_asking_for_pincode(self):
        queries = [
            "What broadband plans do you have?",
            "Tell me about your 300 Mbps plan",
            "What router is included with the connection?",
            "How long does installation take?",
            "Which plan is best for 4K streaming?",
            "What is the price of 100 Mbps fiber?"
        ]
        for idx, q in enumerate(queries):
            session_id = f"rag-test-{idx}"
            initialize_session(session_id)
            res = handle_message(session_id, q, db=self.db)
            self.assertEqual(res["mode"], "RAG", f"Query '{q}' should remain in RAG mode")
            self.assertNotIn("Please provide your complete street address", res["response"])

    def test_explicit_purchase_intent_transitions_to_order_flow(self):
        order_intents = [
            "I want to get a new connection",
            "Book a connection for me",
            "I want to buy the 300 Mbps plan",
            "Check coverage for pincode 110001",
            "110001"
        ]
        for idx, intent in enumerate(order_intents):
            session_id = f"order-intent-{idx}"
            initialize_session(session_id)
            res = handle_message(session_id, intent, db=self.db)
            self.assertEqual(res["mode"], "ORDER_FLOW", f"Intent '{intent}' should trigger ORDER_FLOW")

    def test_distinguish_available_unavailable_unknown(self):
        # 1. Available in DB (110001)
        res_available = qualify(self.db, "110001")
        self.assertTrue(res_available["serviceable"])
        self.assertEqual(res_available["serviceability_status"], "AVAILABLE")

        # 2. Explicitly Unavailable in DB (110006)
        res_unavailable = qualify(self.db, "110006")
        self.assertFalse(res_unavailable["serviceable"])
        self.assertEqual(res_unavailable["serviceability_status"], "UNAVAILABLE")
        self.assertIn("currently unavailable", res_unavailable["message"])

        # 3. Unknown / Valid pincode not in DB (e.g. 560001)
        res_unknown = qualify(self.db, "560001")
        self.assertTrue(res_unknown["serviceable"], "Valid pincodes not in DB must NOT be auto-rejected as unserviceable")
        self.assertEqual(res_unknown["serviceability_status"], "UNKNOWN")

    def test_no_address_loop_when_asking_questions_in_order_flow(self):
        session_id = "loop-test-1"
        initialize_session(session_id)
        # Transition to order flow
        handle_message(session_id, "I want a new connection", db=self.db)
        
        # User asks a FAQ question while in ORDER_FLOW awaiting address
        res = handle_message(session_id, "What router do you provide?", db=self.db)
        self.assertIn("router", res["response"].lower())
        self.assertIn("whenever you're ready", res["response"].lower())

    def test_escape_intent_resets_order_state(self):
        session_id = "escape-test-1"
        initialize_session(session_id)
        handle_message(session_id, "Check pincode 110001", db=self.db)
        self.assertEqual(session_store.get(session_id)["mode"], "ORDER_FLOW")

        res = handle_message(session_id, "start over", db=self.db)
        self.assertEqual(res["mode"], "RAG")
        self.assertIsNone(session_store.get(session_id).get("pincode"))


    def test_discover_plans_for_pincode_prompts_for_complete_address(self):
        session_id = "discover-plans-test"
        initialize_session(session_id)
        res = handle_message(session_id, "I want to discover plans for my pincode 201012", db=self.db)
        self.assertEqual(res["mode"], "ORDER_FLOW")
        self.assertIn("complete street address", res["response"].lower())
        self.assertNotIn("Discover Plans", res["response"])


if __name__ == "__main__":
    unittest.main()
