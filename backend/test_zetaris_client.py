"""
Offline tests for the Zetaris data layer: CSV export, Lightning SQL
generation, the REST proxy client (mocked HTTP) and the
/evidence/insights endpoint on both the local and Zetaris engines.

Run with:  venv/bin/python -m unittest test_zetaris_client -v

Everything is offline: Zetaris HTTP is served by httpx.MockTransport
or by a patched run_query, and all storage lives in temp directories.
"""

import csv
import json
import os
import tempfile
import unittest
import warnings
from unittest import mock

warnings.filterwarnings("ignore")

# Point the H-MEM engine at temp storage BEFORE importing the app.
_TMP = tempfile.mkdtemp(prefix="receipts-zetaris-test-")
os.environ["RECEIPTS_MEMORY_DB"] = os.path.join(_TMP, "memory.db")
os.environ["RECEIPTS_AUDIT_LOG"] = os.path.join(_TMP, "logs", "memory-audit.jsonl")
for _var in ("ZETARIS_BASE_URL", "ZETARIS_API_KEY", "ZETARIS_ORG_ID"):
    os.environ.pop(_var, None)

import httpx

import zetaris_client
from memory_engine import MemoryStoreService


# ---------------------------------------------------------------------------
# Seed data: two runs, four claims, five citations, two domains
# ---------------------------------------------------------------------------

PMC_DESK_URL = "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/"
COCHRANE_URL = "https://www.cochranelibrary.com/cdsr/doi/10.1002/full"
PMC_CAFFEINE_URL = "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9999999/"

SEED = [
    (
        "Do standing desks actually improve productivity?",
        "run-a",
        1000,
        [
            {
                "claim_text": "Standing desks reduced sedentary time by 1.2 hours per workday.",
                "confidence": 85,
                "citations": [{
                    "source_title": "Standing desks review",
                    "source_url": PMC_DESK_URL,
                    "snippet": "reduced sedentary time by 1.2 hours",
                }],
            },
            {
                "claim_text": "Sit-stand desks showed no significant effect on productivity.",
                "confidence": 70,
                "citations": [{
                    "source_title": "Cochrane review",
                    "source_url": COCHRANE_URL,
                    "snippet": "effects on productivity remain uncertain",
                }],
            },
        ],
    ),
    (
        "Does caffeine improve focus?",
        "run-b",
        2000,
        [
            {
                "claim_text": "Caffeine improves alertness in sleep deprived adults.",
                "confidence": 95,
                "citations": [
                    {
                        "source_title": "Caffeine and cognition",
                        "source_url": PMC_CAFFEINE_URL,
                        "snippet": "improves alertness",
                    },
                    {
                        "source_title": "Cochrane review",
                        "source_url": COCHRANE_URL,
                        "snippet": "alertness improved",
                    },
                ],
            },
            {
                "claim_text": "Moderate caffeine intake is safe for most adults.",
                "confidence": 90,
                "citations": [{
                    "source_title": "Standing desks review",
                    "source_url": PMC_DESK_URL,
                    "snippet": "safe for most adults",
                }],
            },
        ],
    ),
]


def seed_store(directory):
    store = MemoryStoreService(
        db_path=os.path.join(directory, "m.db"),
        audit_path=os.path.join(directory, "logs", "audit.jsonl"),
    )
    for question, run_id, ts, claims in SEED:
        store.store_run(question, claims, run_id=run_id, created_at_ms=ts)
    return store


def expected_insights(store):
    """The canonical aggregates for the seed, with real claim ids."""
    by_content = {m.content: m.id for m in store.all()}
    return {
        "totals": {"runs": 2, "claims": 4, "citations": 5},
        "top_sources": [
            {"source_url": COCHRANE_URL, "source_title": "Cochrane review", "claim_count": 2},
            {"source_url": PMC_DESK_URL, "source_title": "Standing desks review", "claim_count": 2},
            {"source_url": PMC_CAFFEINE_URL, "source_title": "Caffeine and cognition", "claim_count": 1},
        ],
        "avg_confidence_by_domain": [
            {"domain": "www.ncbi.nlm.nih.gov", "avg_confidence": 90.0, "claim_count": 3},
            {"domain": "www.cochranelibrary.com", "avg_confidence": 82.5, "claim_count": 2},
        ],
        "claims_per_run": [
            {"run_id": "run-a", "claim_count": 2, "avg_confidence": 77.5},
            {"run_id": "run-b", "claim_count": 2, "avg_confidence": 92.5},
        ],
        "high_confidence_claims": [
            {
                "claim_id": by_content["Caffeine improves alertness in sleep deprived adults."],
                "claim_text": "Caffeine improves alertness in sleep deprived adults.",
                "confidence": 95,
                "run_id": "run-b",
            },
            {
                "claim_id": by_content["Moderate caffeine intake is safe for most adults."],
                "claim_text": "Moderate caffeine intake is safe for most adults.",
                "confidence": 90,
                "run_id": "run-b",
            },
        ],
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class TestExport(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="zetaris-export-")
        self.store = seed_store(self.dir)
        self.records = [m.to_dict() for m in self.store.all()]

    def test_export_writes_three_csvs_with_headers_and_rows(self):
        out = os.path.join(self.dir, "zetaris")
        result = zetaris_client.export_evidence_csvs(self.records, out_dir=out)
        self.assertEqual(result["counts"], {"runs": 2, "claims": 4, "sources": 5})

        def read(name):
            with open(os.path.join(out, name), encoding="utf-8", newline="") as fh:
                return list(csv.reader(fh))

        runs = read("runs.csv")
        self.assertEqual(runs[0], zetaris_client.CSV_HEADERS["runs"])
        self.assertEqual(len(runs), 3)  # header + 2 runs
        run_a = [r for r in runs[1:] if r[0] == "run-a"][0]
        self.assertEqual(run_a[2], "2")   # claim_count
        self.assertEqual(run_a[3], "2")   # citation_count
        self.assertEqual(run_a[4], "1000")
        run_b = [r for r in runs[1:] if r[0] == "run-b"][0]
        self.assertEqual(run_b[3], "3")   # citation_count

        claims = read("claims.csv")
        self.assertEqual(claims[0], zetaris_client.CSV_HEADERS["claims"])
        self.assertEqual(len(claims), 5)
        self.assertEqual(
            sorted(int(r[4]) for r in claims[1:]), [70, 85, 90, 95]
        )
        b1 = [r for r in claims[1:] if "alertness" in r[3]][0]
        self.assertEqual(b1[5], "2")      # source_count

        sources = read("sources.csv")
        self.assertEqual(sources[0], zetaris_client.CSV_HEADERS["sources"])
        self.assertEqual(len(sources), 6)
        self.assertEqual(
            {r[5] for r in sources[1:]},
            {"www.ncbi.nlm.nih.gov", "www.cochranelibrary.com"},
        )

    def test_local_insights_match_expected(self):
        rows = zetaris_client.build_evidence_rows(self.records)
        got = zetaris_client.local_insights(rows, limit=5)
        self.assertEqual(got, expected_insights(self.store))


# ---------------------------------------------------------------------------
# SQL generation
# ---------------------------------------------------------------------------

class TestRegistrationSql(unittest.TestCase):
    PATHS = {
        "runs": "/data/z/runs.csv",
        "claims": "/data/z/claims.csv",
        "sources": "/data/z/sources.csv",
    }

    def test_file_source_statements_match_documented_syntax(self):
        stmts = zetaris_client.registration_sql(self.PATHS)
        self.assertEqual(len(stmts), 4)
        self.assertEqual(
            stmts[0],
            'CREATE LIGHTNING DATABASE receipts_evidence '
            'DESCRIBE BY "Receipts evidence store"',
        )
        self.assertEqual(
            stmts[1],
            'CREATE LIGHTNING FILESTORE TABLE runs FROM receipts_evidence '
            'FORMAT CSV OPTIONS (path "/data/z/runs.csv", header "true", '
            'delimiter ",")',
        )
        self.assertEqual(
            stmts[2],
            'CREATE LIGHTNING FILESTORE TABLE claims FROM receipts_evidence '
            'FORMAT CSV OPTIONS (path "/data/z/claims.csv", header "true", '
            'delimiter ",")',
        )
        self.assertEqual(
            stmts[3],
            'CREATE LIGHTNING FILESTORE TABLE sources FROM receipts_evidence '
            'FORMAT CSV OPTIONS (path "/data/z/sources.csv", header "true", '
            'delimiter ",")',
        )

    def test_shipped_sql_file_matches_generator(self):
        sql_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "scripts", "register_zetaris_sources.sql",
        )
        with open(sql_path, encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh]
        creates = [
            ln.rstrip(";").replace("<RECEIPTS_EXPORT_DIR>", "/data/z")
            for ln in lines if ln.startswith("CREATE")
        ]
        self.assertEqual(creates, zetaris_client.registration_sql(self.PATHS))

    def test_create_datasource_sql_matches_documented_syntax(self):
        stmt = zetaris_client.create_datasource_sql(
            "receipts_pg", "jdbc:postgresql://db.internal:5432/receipts", "u", "p"
        )
        self.assertTrue(stmt.startswith(
            'CREATE DATASOURCE receipts_pg DESCRIBE BY "PostgreSQL" OPTIONS ('
            'jdbcdriver "org.postgresql.Driver", '
            'jdbcurl "jdbc:postgresql://db.internal:5432/receipts", '
            'username "u", password "p", fetchsize "1000")'
        ))

    def test_insight_sql_targets_registered_tables(self):
        self.assertIn("FROM receipts_evidence.sources", zetaris_client.top_sources_sql(5))
        self.assertIn("JOIN receipts_evidence.claims", zetaris_client.avg_confidence_by_domain_sql())
        self.assertIn("FROM receipts_evidence.claims", zetaris_client.claims_per_run_sql())
        self.assertIn("confidence >= 90", zetaris_client.high_confidence_claims_sql(5))


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

class TestParseRows(unittest.TestCase):
    def test_data_envelope_with_string_numbers(self):
        rows = zetaris_client.parse_rows({"data": [{"claim_count": "3"}]})
        self.assertEqual(rows, [{"claim_count": 3}])

    def test_columns_rows_shape_and_exponent_floats(self):
        rows = zetaris_client.parse_rows(
            {"columns": ["a", "b"], "rows": [["1", "2.5"], ["9.0E1", "x"]]}
        )
        self.assertEqual(rows, [{"a": 1, "b": 2.5}, {"a": 90.0, "b": "x"}])

    def test_bare_list_and_empty(self):
        self.assertEqual(zetaris_client.parse_rows([{"n": "2"}]), [{"n": 2}])
        self.assertEqual(zetaris_client.parse_rows(None), [])


# ---------------------------------------------------------------------------
# HTTP client (mocked transport)
# ---------------------------------------------------------------------------

ZETARIS_ENV = {
    "ZETARIS_BASE_URL": "http://localhost:3000",
    "ZETARIS_API_KEY": "test-key-123",
    "ZETARIS_ORG_ID": "1",
}


class TestClientHttp(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ZETARIS_ENV)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_query_request_shape_and_parsing(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"data": [{"n": "2"}]})

        rows = zetaris_client.query(
            "SELECT COUNT(*) AS n FROM receipts_evidence.runs",
            transport=httpx.MockTransport(handler),
        )
        self.assertEqual(rows, [{"n": 2}])
        self.assertEqual(
            captured["url"],
            "http://localhost:3000/api/proxy/sql-editor/sqls/run-query",
        )
        self.assertEqual(captured["headers"].get("authorization"), "Bearer test-key-123")
        self.assertEqual(captured["headers"].get("x-org-id"), "1")
        self.assertTrue(captured["headers"].get("x-request-id"))
        self.assertEqual(captured["body"]["sql"], "SELECT COUNT(*) AS n FROM receipts_evidence.runs")
        self.assertEqual(captured["body"]["limit"], 1000)

    def test_register_sources_sends_each_statement_once(self):
        bodies = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content.decode()))
            return httpx.Response(200, json={"status": "ok"})

        paths = {
            "runs": "/data/z/runs.csv",
            "claims": "/data/z/claims.csv",
            "sources": "/data/z/sources.csv",
        }
        results = zetaris_client.register_sources(
            paths, transport=httpx.MockTransport(handler)
        )
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r["ok"] for r in results))
        self.assertEqual(
            [b["sql"] for b in bodies], zetaris_client.registration_sql(paths)
        )

    def test_register_sources_reports_failures(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        results = zetaris_client.register_sources(
            transport=httpx.MockTransport(handler)
        )
        self.assertEqual(len(results), 4)
        self.assertTrue(all(not r["ok"] for r in results))
        self.assertIn("500", results[0]["error"])


class TestClientUnconfigured(unittest.TestCase):
    def test_not_configured_without_base_url_and_key(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ZETARIS_BASE_URL", None)
            os.environ.pop("ZETARIS_API_KEY", None)
            self.assertFalse(zetaris_client.zetaris_configured())
            with self.assertRaises(RuntimeError):
                zetaris_client.run_query("SELECT 1")


# ---------------------------------------------------------------------------
# /evidence/insights endpoint: local engine, Zetaris engine, fallback
# ---------------------------------------------------------------------------

def _fake_zetaris_run_query(expected):
    """A run_query stand-in that answers the insight SQL like a live
    instance would: values as strings, inside a data envelope."""
    high = expected["high_confidence_claims"]

    def fake(sql, limit=1000, timeout_sec=30.0, transport=None):
        if "GROUP BY source_url" in sql:
            return {"data": [
                {**r, "claim_count": str(r["claim_count"])}
                for r in expected["top_sources"]
            ]}
        if "GROUP BY s.domain" in sql:
            return {"data": [
                {
                    "domain": r["domain"],
                    "avg_confidence": str(r["avg_confidence"]),
                    "claim_count": str(r["claim_count"]),
                }
                for r in expected["avg_confidence_by_domain"]
            ]}
        if "GROUP BY run_id" in sql:
            return {"data": [
                {
                    "run_id": r["run_id"],
                    "claim_count": str(r["claim_count"]),
                    "avg_confidence": str(r["avg_confidence"]),
                }
                for r in expected["claims_per_run"]
            ]}
        if "confidence >= 90" in sql:
            return {"data": [
                {**r, "confidence": str(r["confidence"])} for r in high
            ]}
        if "FROM receipts_evidence.runs" in sql:
            return {"data": [{"n": str(expected["totals"]["runs"])}]}
        if "FROM receipts_evidence.claims" in sql:
            return {"data": [{"n": str(expected["totals"]["claims"])}]}
        if "FROM receipts_evidence.sources" in sql:
            return {"data": [{"n": str(expected["totals"]["citations"])}]}
        raise AssertionError(f"unexpected SQL: {sql}")

    return fake


class TestInsightsEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as receipts_app
        cls.app_module = receipts_app
        cls.dir = tempfile.mkdtemp(prefix="zetaris-endpoint-")
        cls.store = seed_store(cls.dir)
        receipts_app.memory_store = cls.store
        cls.expected = expected_insights(cls.store)
        from fastapi.testclient import TestClient
        cls.client = TestClient(receipts_app.app)

    def setUp(self):
        self._patches = [
            mock.patch.object(
                zetaris_client, "DEFAULT_EXPORT_DIR",
                os.path.join(self.dir, "zetaris-export"),
            ),
            mock.patch.object(
                zetaris_client, "DEFAULT_ZETARIS_AUDIT_PATH",
                os.path.join(self.dir, "logs", "zetaris-audit.jsonl"),
            ),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _sections(self, body):
        return {k: body[k] for k in (
            "totals", "top_sources", "avg_confidence_by_domain",
            "claims_per_run", "high_confidence_claims",
        )}

    def test_local_engine_when_unconfigured(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ZETARIS_BASE_URL", None)
            os.environ.pop("ZETARIS_API_KEY", None)
            resp = self.client.get("/evidence/insights")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["engine"], "local")
        self.assertFalse(body["zetaris_configured"])
        self.assertEqual(self._sections(body), self.expected)
        # The endpoint refreshed the export files.
        export_dir = os.path.join(self.dir, "zetaris-export")
        for name in ("runs.csv", "claims.csv", "sources.csv"):
            self.assertTrue(os.path.exists(os.path.join(export_dir, name)))

    def test_zetaris_engine_matches_local_aggregates(self):
        fake = _fake_zetaris_run_query(self.expected)
        with mock.patch.dict(os.environ, ZETARIS_ENV):
            with mock.patch.object(zetaris_client, "run_query", fake):
                resp = self.client.get("/evidence/insights")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["engine"], "zetaris")
        self.assertTrue(body["zetaris_configured"])
        self.assertEqual(self._sections(body), self.expected)
        # Serving through Zetaris left an audit line.
        audit = os.path.join(self.dir, "logs", "zetaris-audit.jsonl")
        with open(audit, encoding="utf-8") as fh:
            events = [json.loads(ln) for ln in fh if ln.strip()]
        self.assertTrue(any(
            e["event"] == "insights" and e["engine"] == "zetaris" for e in events
        ))

    def test_zetaris_failure_falls_back_to_local(self):
        def boom(sql, limit=1000, timeout_sec=30.0, transport=None):
            raise RuntimeError("instance unreachable")

        with mock.patch.dict(os.environ, ZETARIS_ENV):
            with mock.patch.object(zetaris_client, "run_query", boom):
                resp = self.client.get("/evidence/insights")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["engine"], "local")
        self.assertIn("unreachable", body["fallback_reason"])
        self.assertEqual(self._sections(body), self.expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
