"""
Offline tests for the Meterless H-MEM memory engine, the Nightshift
provider layer, and their wiring into the Receipts /ask flow.

Run with:  venv/bin/python -m unittest test_memory_engine -v

Everything is offline: search and the model are faked, Nightshift HTTP
is served by httpx.MockTransport, and the memory DB/audit log live in a
temporary directory.
"""

import asyncio
import json
import os
import tempfile
import unittest
import uuid
import warnings
from unittest import mock

warnings.filterwarnings("ignore")

# Point the H-MEM engine at temp storage BEFORE importing the app.
_TMP = tempfile.mkdtemp(prefix="receipts-memory-test-")
os.environ["RECEIPTS_MEMORY_DB"] = os.path.join(_TMP, "memory.db")
os.environ["RECEIPTS_AUDIT_LOG"] = os.path.join(_TMP, "logs", "memory-audit.jsonl")
os.environ.pop("METERLESS_BASE_URL", None)

import httpx

import llm_provider
from memory_engine import Memory, MemoryStoreService, MemoryRetrievalService


# ---------------------------------------------------------------------------
# H-MEM store + retrieval
# ---------------------------------------------------------------------------

# Snippets are complete verbatim sentences from the fake search bodies
# below, as quote validation now requires. The previous fragments were
# test-only shortcuts, not real search output.
DESK_CLAIMS = [
    {
        "claim_text": "Standing desks reduced sedentary time by 1.2 hours per workday in a 2023 review.",
        "confidence": 85,
        "citations": [{
            "source_title": "Standing desks: health benefits review",
            "source_url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/",
            "snippet": "A 2023 review found standing desks reduced sedentary time by 1.2 hours per workday.",
        }],
    },
    {
        "claim_text": "Sit-stand desks showed no significant effect on productivity measures.",
        "confidence": 70,
        "citations": [{
            "source_title": "Cochrane review: sit-stand desks",
            "source_url": "https://www.cochranelibrary.com/cdsr/doi/10.1002/full",
            "snippet": "Sit-stand desks probably reduce sitting time at work in the short term.",
        }],
    },
]


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="hmem-")
        self.store = MemoryStoreService(
            db_path=os.path.join(self.dir, "m.db"),
            audit_path=os.path.join(self.dir, "logs", "audit.jsonl"),
        )
        self.retrieval = MemoryRetrievalService(self.store)


class TestMemoryRecordContract(StoreTestCase):
    def test_record_without_source_is_rejected(self):
        with self.assertRaises(ValueError):
            Memory(content="orphan fact", source="", confidence=0.5)

    def test_store_run_record_shape(self):
        stored = self.store.store_run(
            "Do standing desks actually improve productivity?",
            DESK_CLAIMS,
            run_id="run-shape",
        )
        self.assertEqual(len(stored), 2)
        rec = stored[0].to_dict()
        # Field names follow the guide's Python dataclass shape (snake_case).
        for key in (
            "id", "content", "type", "layer", "timestamp", "last_accessed",
            "access_count", "tags", "confidence", "source", "entities",
            "related_to", "derived_from", "provenance",
        ):
            self.assertIn(key, rec)
        self.assertEqual(rec["type"], "factual")
        self.assertEqual(rec["layer"], "long_term")
        self.assertAlmostEqual(rec["confidence"], 0.85)
        self.assertEqual(rec["source"], "receipts:run:run-shape")
        self.assertEqual(rec["provenance"]["origin"], "tool")
        self.assertEqual(len(rec["citations"]), 1)

    def test_persistence_across_instances(self):
        self.store.store_run("Q?", DESK_CLAIMS, run_id="run-persist")
        fresh = MemoryStoreService(
            db_path=self.store.db_path, audit_path=self.store.audit_path
        )
        self.assertEqual(len(fresh.all()), 2)


class TestRetrieval(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.store.store_run(
            "Do standing desks actually improve productivity?",
            DESK_CLAIMS,
            run_id="run-1",
        )

    def test_related_question_returns_claims(self):
        results, trace = self.retrieval.query(
            "Do standing desks reduce sitting time at work?"
        )
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(trace["matched"], len(results))
        self.assertIn("sedentary", results[0]["content"])
        self.assertIn("score_breakdown", results[0])
        self.assertEqual(len(results[0]["citations"]), 1)

    def test_unrelated_question_returns_none(self):
        results, _ = self.retrieval.query("How do I bake sourdough bread at home?")
        self.assertEqual(results, [])

    def test_retrieval_bumps_access_count(self):
        before = {m.id: m.access_count for m in self.store.all()}
        self.retrieval.query("Are standing desks good for productivity?")
        after = {m.id: m.access_count for m in self.store.all()}
        self.assertTrue(any(after[k] > before[k] for k in after))

    def test_audit_log_has_store_and_retrieve_events(self):
        self.retrieval.query("Are standing desks good for productivity?")
        with open(self.store.audit_path, encoding="utf-8") as fh:
            events = [json.loads(line)["event"] for line in fh if line.strip()]
        self.assertIn("store_run", events)
        self.assertIn("retrieve", events)


class TestTestIsolation(unittest.TestCase):
    def test_no_arg_store_resolves_env_at_construction_time(self):
        # Regression test for the old import-order flaw: even if
        # memory_engine was imported before this env change (as happens
        # when test_pipeline runs first), a no-arg store must use the
        # env paths set now, never the real data/memory.db.
        tmp = tempfile.mkdtemp(prefix="hmem-isolation-")
        db_path = os.path.join(tmp, "isolated.db")
        audit_path = os.path.join(tmp, "logs", "audit.jsonl")
        with mock.patch.dict(
            os.environ,
            {
                "RECEIPTS_MEMORY_DB": db_path,
                "RECEIPTS_AUDIT_LOG": audit_path,
            },
        ):
            store = MemoryStoreService()
            self.assertEqual(store.db_path, db_path)
            self.assertEqual(store.audit_path, audit_path)
            self.assertNotIn("receipts-frontend", db_path)
            stored = store.store_run(
                "Isolation check question?",
                DESK_CLAIMS,
                run_id="run-isolation",
            )
            self.assertEqual(len(stored), 2)
            self.assertEqual(len(store.all()), 2)


# ---------------------------------------------------------------------------
# Nightshift provider layer (mocked HTTP)
# ---------------------------------------------------------------------------

def _ok_handler(captured):
    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = (
            json.loads(request.content.decode()) if request.content else {}
        )
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "meterless/auto"}]})
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"answer": "from nightshift"}'}}]
        })
    return handler


class TestNightshiftProvider(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            "METERLESS_BASE_URL": "http://127.0.0.1:8088/v1",
            "METERLESS_RUNTIME_TOKEN": "test-token-123",
            "METERLESS_MODEL": "meterless/auto",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_chat_completion_request_shape(self):
        captured = {}
        transport = httpx.MockTransport(_ok_handler(captured))
        out = llm_provider.meterless_generate_json(
            "Say hi", transport=transport
        )
        self.assertEqual(out, {"answer": "from nightshift"})
        self.assertEqual(captured["url"], "http://127.0.0.1:8088/v1/chat/completions")
        self.assertEqual(
            captured["headers"].get("authorization"), "Bearer test-token-123"
        )
        self.assertEqual(captured["headers"].get("meterless-app"), "receipts")
        self.assertEqual(captured["payload"]["model"], "meterless/auto")
        self.assertEqual(
            captured["payload"]["messages"], [{"role": "user", "content": "Say hi"}]
        )
        self.assertEqual(
            captured["payload"]["response_format"], {"type": "json_object"}
        )

    def test_discover_models(self):
        captured = {}
        transport = httpx.MockTransport(_ok_handler(captured))
        models = llm_provider.discover_models(transport=transport)
        self.assertEqual(models, ["meterless/auto"])
        self.assertTrue(captured["url"].endswith("/v1/models"))

    def test_fallback_to_gemini_on_http_error(self):
        def err_handler(request):
            return httpx.Response(500, json={"error": "boom"})

        async def fake_gemini(prompt, timeout_sec):
            return {"answer": "from gemini"}

        out = asyncio.run(llm_provider.generate_json(
            "prompt", fake_gemini, transport=httpx.MockTransport(err_handler)
        ))
        self.assertEqual(out, {"answer": "from gemini"})

    def test_provider_used_when_configured(self):
        captured = {}

        async def fake_gemini(prompt, timeout_sec):
            raise AssertionError("Gemini must not be called when Nightshift works")

        out = asyncio.run(llm_provider.generate_json(
            "prompt", fake_gemini,
            transport=httpx.MockTransport(_ok_handler(captured)),
        ))
        self.assertEqual(out, {"answer": "from nightshift"})


class TestProviderUnconfigured(unittest.TestCase):
    def test_gemini_used_directly_when_base_url_unset(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("METERLESS_BASE_URL", None)

            async def fake_gemini(prompt, timeout_sec):
                return {"answer": "gemini only"}

            out = asyncio.run(llm_provider.generate_json("prompt", fake_gemini))
            self.assertEqual(out, {"answer": "gemini only"})


# ---------------------------------------------------------------------------
# End to end: /ask flow with memory (faked search + model + Supabase)
# ---------------------------------------------------------------------------

class FakeTable:
    def __init__(self, store):
        self.store = store

    def insert(self, data):
        row = dict(data)
        row.setdefault("id", str(uuid.uuid4()))
        self.store.append(row)

        class R:
            data = [row]

        class Exe:
            def execute(self):
                return R()
        return Exe()

    def update(self, data):
        store = self.store

        class U:
            def eq(self, col, val):
                for r in store:
                    if str(r.get(col)) == str(val):
                        r.update(data)

                class R2:
                    def execute(self):
                        return self
                    data = []
                return R2()
        return U()

    def eq(self, col, val):
        store = self.store

        class R:
            data = [r for r in store if str(r.get(col)) == str(val)]

            def execute(self):
                return self

            def order(self, col, desc=False):
                self.data = sorted(self.data, key=lambda r: r.get(col, 0), reverse=desc)
                return self
        return R()

    def in_(self, col, vals):
        vset = set(str(v) for v in vals)
        store = self.store

        class R:
            data = [r for r in store if str(r.get(col)) in vset]

            def execute(self):
                return self
        return R()


class FakeSupabase:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return FakeTable(self.tables.setdefault(name, []))


async def _fake_search(query, timeout_sec=12.0):
    return [
        {"title": "Standing desks: health benefits review",
         "href": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/",
         "body": "A 2023 review found standing desks reduced sedentary time by 1.2 hours per workday."},
        {"title": "Cochrane review: sit-stand desks",
         "href": "https://www.cochranelibrary.com/cdsr/doi/10.1002/full",
         "body": "Sit-stand desks probably reduce sitting time at work in the short term."},
    ]


async def _fake_model(prompt, timeout_sec=25.0):
    if "research planner" in prompt:
        return {"sub_questions": ["sq one", "sq two", "sq three"]}
    if "evidence analyst" in prompt:
        return {"claims": DESK_CLAIMS}
    if "final synthesizer" in prompt:
        return {"answer": "Standing desks reduce sedentary time but may not raise productivity."}
    raise AssertionError("unexpected prompt")


class TestAskFlowWithMemory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as receipts_app
        cls.app_module = receipts_app
        receipts_app.supabase = FakeSupabase()
        receipts_app.search_subquestion = _fake_search
        receipts_app.run_gemini_json = _fake_model
        # Fresh memory engine on the temp paths set above.
        receipts_app.memory_store = MemoryStoreService()
        receipts_app.memory_retrieval = MemoryRetrievalService(
            receipts_app.memory_store
        )
        from fastapi.testclient import TestClient
        cls.client = TestClient(receipts_app.app)

    def test_first_ask_has_no_memory_second_related_ask_does(self):
        r1 = self.client.post(
            "/ask", json={"question": "Do standing desks actually improve productivity?"}
        )
        self.assertEqual(r1.status_code, 200)
        d1 = r1.json()
        self.assertEqual(d1["memory_claims"], [])
        self.assertEqual(len(d1["claims"]), 2)

        r2 = self.client.post(
            "/ask", json={"question": "Do standing desks reduce sitting time at work?"}
        )
        self.assertEqual(r2.status_code, 200)
        d2 = r2.json()
        self.assertGreaterEqual(len(d2["memory_claims"]), 1)
        self.assertIn("sedentary", d2["memory_claims"][0]["claim_text"])
        self.assertEqual(len(d2["memory_claims"][0]["citations"]), 1)
        memory_steps = [t for t in d2["trace_steps"] if t["action"] == "memory"]
        self.assertEqual(len(memory_steps), 1)
        self.assertIn("prior claims found", memory_steps[0]["detail"])

    def test_unrelated_ask_gets_no_memory(self):
        resp = self.client.post(
            "/ask", json={"question": "How do I bake sourdough bread at home?"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["memory_claims"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
