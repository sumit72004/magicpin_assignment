"""
Comprehensive test suite for Vera Message Engine.
Tests all 5 endpoints, context versioning, composer logic, and replay scenarios.
"""

import unittest
from fastapi.testclient import TestClient
from bot import app, compose
from engine.store import global_store


class TestVeraEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        dataset_path = Path(__file__).parent / "dataset"
        global_store.preload_from_dataset(dataset_path)
        cls.client = TestClient(app)

    def test_healthz(self):
        resp = self.client.get("/v1/healthz")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("uptime_seconds", data)
        self.assertIn("contexts_loaded", data)
        counts = data["contexts_loaded"]
        self.assertGreater(counts.get("category", 0), 0)

    def test_metadata(self):
        resp = self.client.get("/v1/metadata")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("team_name", data)
        self.assertIn("model", data)
        self.assertIn("approach", data)
        self.assertIn("version", data)

    def test_context_push_and_versioning(self):
        # 1. Valid push v1
        payload = {"slug": "test_cat", "name": "Test Category"}
        resp = self.client.post("/v1/context", json={
            "scope": "category",
            "context_id": "test_cat_001",
            "version": 1,
            "payload": payload,
            "delivered_at": "2026-04-26T10:00:00Z"
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["accepted"])

        # 2. Idempotent re-push of same v1 -> 200 accepted (no-op)
        resp2 = self.client.post("/v1/context", json={
            "scope": "category",
            "context_id": "test_cat_001",
            "version": 1,
            "payload": payload,
            "delivered_at": "2026-04-26T10:00:00Z"
        })
        self.assertEqual(resp2.status_code, 200)
        self.assertTrue(resp2.json()["accepted"])

        # 3. Higher version v2 -> 200 accepted
        resp3 = self.client.post("/v1/context", json={
            "scope": "category",
            "context_id": "test_cat_001",
            "version": 2,
            "payload": {"slug": "test_cat", "name": "Updated Category"},
            "delivered_at": "2026-04-26T10:05:00Z"
        })
        self.assertEqual(resp3.status_code, 200)
        self.assertTrue(resp3.json()["accepted"])

        # 4. Stale version conflict (pushing v1 when current is v2) -> 409 Conflict
        resp_stale = self.client.post("/v1/context", json={
            "scope": "category",
            "context_id": "test_cat_001",
            "version": 1,
            "payload": payload,
            "delivered_at": "2026-04-26T10:06:00Z"
        })
        self.assertEqual(resp_stale.status_code, 409)
        self.assertFalse(resp_stale.json()["accepted"])
        self.assertEqual(resp_stale.json()["reason"], "stale_version")

        # 4. Invalid scope -> 400 Bad Request
        resp4 = self.client.post("/v1/context", json={
            "scope": "invalid_scope",
            "context_id": "test_cat_001",
            "version": 3,
            "payload": {},
            "delivered_at": "2026-04-26T10:05:00Z"
        })
        self.assertEqual(resp4.status_code, 400)
        self.assertFalse(resp4.json()["accepted"])

    def test_tick_and_suppression(self):
        # Check tick with a trigger
        trg_id = "trg_001_research_digest_dentists"
        resp = self.client.post("/v1/tick", json={
            "now": "2026-04-26T10:30:00Z",
            "available_triggers": [trg_id]
        })
        self.assertEqual(resp.status_code, 200)
        actions = resp.json()["actions"]
        self.assertIsInstance(actions, list)
        if actions:
            act = actions[0]
            self.assertIn("conversation_id", act)
            self.assertIn("merchant_id", act)
            self.assertEqual(act["send_as"], "vera")
            self.assertIn("body", act)
            self.assertIn("cta", act)
            self.assertIn("suppression_key", act)
            self.assertIn("rationale", act)
            # Verify no raw URLs
            self.assertNotIn("http://", act["body"])
            self.assertNotIn("https://", act["body"])

    def test_reply_auto_reply_detection(self):
        resp = self.client.post("/v1/reply", json={
            "conversation_id": "conv_test_auto_reply",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "from_role": "merchant",
            "message": "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly.",
            "turn_number": 2
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn(data["action"], ["end", "wait"])

    def test_reply_hostile_handling(self):
        resp = self.client.post("/v1/reply", json={
            "conversation_id": "conv_test_hostile",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "from_role": "merchant",
            "message": "Stop messaging me. This is useless spam.",
            "turn_number": 2
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["action"], "end")

    def test_reply_intent_transition(self):
        resp = self.client.post("/v1/reply", json={
            "conversation_id": "conv_test_intent",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "from_role": "merchant",
            "message": "Ok lets do it. Whats next?",
            "turn_number": 2
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["action"], "send")
        body = data["body"].lower()
        # Must contain action words
        action_words = ["done", "sending", "draft", "here", "confirm", "proceed", "next"]
        self.assertTrue(any(w in body for w in action_words), f"Action words missing in: {body}")
        # Must NOT contain qualifying words
        qualifying_words = ["would you", "do you", "can you tell", "what if", "how about"]
        self.assertFalse(any(w in body for w in qualifying_words), f"Qualifying words found in: {body}")

    def test_reply_curveball_handling(self):
        resp = self.client.post("/v1/reply", json={
            "conversation_id": "conv_test_curveball",
            "merchant_id": "m_001_drmeera_dentist_delhi",
            "from_role": "merchant",
            "message": "Btw can you also help me with my GST filing this month?",
            "turn_number": 2
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["action"], "send")
        self.assertIn("ca", data["body"].lower())

    def test_standalone_compose(self):
        cat = global_store.get_category("dentists") or {}
        merch = global_store.get_merchant("m_001_drmeera_dentist_delhi") or {}
        trg = global_store.get_trigger("trg_001_research_digest_dentists") or {}
        res = compose(cat, merch, trg, None)
        self.assertIn("body", res)
        self.assertIn("Dr. Meera", res["body"])
        self.assertIn("JIDA", res["body"])
        self.assertEqual(res["send_as"], "vera")
        self.assertNotIn("http://", res["body"])


if __name__ == "__main__":
    unittest.main()
