"""P1 evidence fixes: confidence units, per-source quotes, fallback
handling, confidence-after-filtering, and the no-results trace.

Importing app.py tolerates missing keys with warnings; set the temp
H-MEM paths before import, as in test_quote_validation.py.
"""

import os
import tempfile
import unittest
import uuid
import warnings

warnings.filterwarnings("ignore")

_TMP = tempfile.mkdtemp(prefix="receipts-p1-test-")
os.environ.setdefault("RECEIPTS_MEMORY_DB", os.path.join(_TMP, "memory.db"))
os.environ.setdefault("RECEIPTS_AUDIT_LOG", os.path.join(_TMP, "logs", "memory-audit.jsonl"))

from app import is_complete_quote, normalize_confidence, validate_claims
from memory_engine import MemoryStoreService


SOURCE_A = "A 2023 review found standing desks reduced sedentary time by 1.2 hours per workday."
SOURCE_B = "Sit-stand desks probably reduce sitting time at work in the short term."
GOOD_A = SOURCE_A


class TestConfidenceUnits(unittest.TestCase):
    def test_int_scores_unchanged(self):
        self.assertEqual(normalize_confidence(85), 85)
        self.assertEqual(normalize_confidence(1), 1)
        self.assertEqual(normalize_confidence(0), 0)

    def test_float_fraction_rescaled(self):
        # A model returning 0.85 on the 0..1 scale used to truncate to 0.
        self.assertEqual(normalize_confidence(0.85), 85)
        self.assertEqual(normalize_confidence(0.5), 50)

    def test_out_of_range_clamped(self):
        self.assertEqual(normalize_confidence(150), 100)
        self.assertEqual(normalize_confidence(-5), 0)
        self.assertEqual(normalize_confidence("bad"), 50)


class TestPerSourceValidation(unittest.TestCase):
    def _claim(self, url, snippet):
        return [{
            "claim_text": "Standing desks help.",
            "confidence": 90,
            "citations": [{"source_title": "T", "source_url": url, "snippet": snippet}],
        }]

    def test_quote_from_other_source_does_not_pass(self):
        # Pooled validation passed this: GOOD_A is complete in A, but
        # the citation points at B. Per-source validation must drop it.
        by_url = {
            "https://example.com/a": SOURCE_A,
            "https://example.com/b": SOURCE_B,
        }
        kept, dropped_cites, dropped_claims = validate_claims(
            self._claim("https://example.com/b", GOOD_A), source_by_url=by_url)
        self.assertEqual(kept, [])
        self.assertEqual((dropped_cites, dropped_claims), (1, 1))

    def test_quote_from_own_source_passes(self):
        by_url = {
            "https://example.com/a": SOURCE_A,
            "https://example.com/b": SOURCE_B,
        }
        kept, dropped_cites, _ = validate_claims(
            self._claim("https://example.com/a", GOOD_A), source_by_url=by_url)
        self.assertEqual(len(kept), 1)
        self.assertEqual(dropped_cites, 0)

    def test_unknown_url_fails_closed(self):
        kept, _, _ = validate_claims(
            self._claim("https://example.com/invented", GOOD_A),
            source_by_url={"https://example.com/a": SOURCE_A})
        self.assertEqual(kept, [])

    def test_pooled_path_still_works_for_old_callers(self):
        # No map given: the legacy pooled behaviour is preserved.
        self.assertTrue(is_complete_quote(GOOD_A, [SOURCE_A, SOURCE_B]))


class TestFallbackAndFiltering(unittest.TestCase):
    def test_confidence_preserved_after_filtering(self):
        # Deliberate, documented behaviour: filtering drops citations,
        # it does not rescale the model's pre-filter score. The test
        # pins that choice so a future rescale is a conscious change.
        claims = [{
            "claim_text": "Standing desks help.",
            "confidence": 90,
            "citations": [
                {"source_title": "A", "source_url": "https://example.com/a", "snippet": GOOD_A},
                {"source_title": "B", "source_url": "https://example.com/b",
                 "snippet": "When done under supervision, intermittent fasting can be"},
            ],
        }]
        kept, dropped_cites, _ = validate_claims(
            claims,
            source_by_url={
                "https://example.com/a": SOURCE_A,
                "https://example.com/b": SOURCE_B,
            })
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(kept[0]["citations"]), 1)
        self.assertEqual(kept[0]["confidence"], 90)
        self.assertEqual(dropped_cites, 1)

    def test_memory_store_skips_uncited_claims(self):
        store = MemoryStoreService(
            db_path=os.path.join(tempfile.mkdtemp(prefix="hmem-p1-"), "m.db"),
            audit_path=os.path.join(tempfile.mkdtemp(prefix="hmem-p1-"), "audit.jsonl"),
        )
        stored = store.store_run("Q?", [
            {"claim_text": "No verifiable atomic claims could be derived.",
             "confidence": 0, "citations": []},
            {"claim_text": "Standing desks reduced sedentary time.",
             "confidence": 85,
             "citations": [{"source_title": "A", "source_url": "https://example.com/a",
                           "snippet": GOOD_A}]},
        ], run_id="run-p1")
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].content, "Standing desks reduced sedentary time.")
        self.assertEqual(len(store.all()), 1)


# ---------------------------------------------------------------------------
# No-search-results trace, end to end through /ask with fakes
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


async def _empty_search(query, timeout_sec=12.0):
    return []


async def _fake_model(prompt, timeout_sec=25.0):
    if "research planner" in prompt:
        return {"sub_questions": ["sq one", "sq two", "sq three"]}
    raise AssertionError("model must not be called on the no-results branch")


class TestNoResultsTrace(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as receipts_app
        from memory_engine import MemoryRetrievalService
        cls.app_module = receipts_app
        receipts_app.supabase = FakeSupabase()
        receipts_app.search_subquestion = _empty_search
        receipts_app.run_gemini_json = _fake_model
        tmp = tempfile.mkdtemp(prefix="receipts-p1-memory-")
        receipts_app.memory_store = MemoryStoreService(
            db_path=os.path.join(tmp, "m.db"),
            audit_path=os.path.join(tmp, "audit.jsonl"))
        receipts_app.memory_retrieval = MemoryRetrievalService(receipts_app.memory_store)
        from fastapi.testclient import TestClient
        cls.client = TestClient(receipts_app.app)

    def test_no_results_trace_matches_db_steps(self):
        r = self.client.post("/ask", json={"question": "A question with no web results?"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        actions = [t["action"] for t in d["trace_steps"]]
        self.assertEqual(actions, ["init", "memory", "planner", "searcher", "composer"])
        self.assertEqual([t["step_order"] for t in d["trace_steps"]], [1, 2, 3, 4, 5])
        # Planner detail comes from the DB trace, not a hardcoded copy.
        planner = [t for t in d["trace_steps"] if t["action"] == "planner"][0]
        self.assertIn("sq one", planner["detail"])
        self.assertEqual(len(d["claims"]), 1)
        self.assertEqual(d["claims"][0]["confidence"], 0)
        self.assertEqual(d["claims"][0]["citations"], [])
        self.assertEqual(d["claims"][0]["evidence_status"], "insufficient_evidence")
        self.assertIn("insufficient", d["answer"].lower())


if __name__ == "__main__":
    unittest.main()
