"""
Zetaris data layer for Receipts.

Receipts' evidence store (the verified claims kept by the H-MEM memory
engine) is exposed to Zetaris as a virtual data layer:

1. The store is exported to portable CSV files under ``data/zetaris/``
   (``runs.csv``, ``claims.csv``, ``sources.csv``).
2. ``registration_sql`` generates the Lightning SQL that registers those
   files in a Zetaris instance, following the official command reference
   (zetaris/getting-started, docs/guides/zetaris-lightning-sql-commands.md):
   file sources are registered with ``CREATE LIGHTNING DATABASE`` plus
   ``CREATE LIGHTNING FILESTORE TABLE`` (section 5). ``CREATE DATASOURCE``
   (section 4) is the separate JDBC path and is generated here only as an
   optional helper for pointing Zetaris at a Postgres evidence database.
3. ``run_query`` executes one Lightning SQL statement per call through
   the platform UI proxy route used by the official helper scripts
   (scripts/query_zetaris.py and scripts/zetaris_api.py in the same repo):
   ``POST {ZETARIS_BASE_URL}/api/proxy/sql-editor/sqls/run-query`` with a
   bearer API key, ``X-Org-ID`` and ``X-Request-ID`` headers and a JSON
   body of ``{"sql": ..., "limit": ...}``.
4. The insights queries (top sources, average confidence per domain,
   claims per run, high confidence claims) run through Zetaris when it
   is configured and are computed from the same exported rows locally
   when it is not, so the feature degrades gracefully with no instance.

Configuration (environment):

    ZETARIS_BASE_URL   Web UI origin of a running instance, for example
                       http://localhost:3000 (no path after the origin).
                       The integration is active only when this and
                       ZETARIS_API_KEY are both set.
    ZETARIS_API_KEY    API key created in the Zetaris GUI
                       (Management, API Tokens).
    ZETARIS_ORG_ID     Numeric organisation ID (Management,
                       Organisation). Sent as the X-Org-ID header, which
                       the official proxy helpers require.
    ZETARIS_JDBC_URL   Optional, documented for JDBC clients:
                       jdbc:zetaris:lightning@<host>:10000 with driver
                       class com.zetaris.lightning.jdbc.LightningDriver.
                       Receipts itself talks REST, not JDBC.

Honest limits: the SQL syntax, the proxy route, the headers and the
request body above are confirmed from the official getting-started
repo. The exact JSON envelope of a run-query response is not shown in
those docs, so ``parse_rows`` accepts the common shapes (a bare list of
row objects, a ``data``/``rows``/``result`` list, or a
``columns`` + ``rows`` pair). Per the client setup doc, REST returns
values as strings and decimals may use exponent format, so row values
are coerced to int/float where they parse cleanly.
"""

import csv
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Read at call time (not bound as parameter defaults) so tests and
# deployments can point the export and audit locations elsewhere.
DEFAULT_EXPORT_DIR = os.environ.get(
    "RECEIPTS_ZETARIS_EXPORT_DIR", os.path.join(BASE_DIR, "data", "zetaris")
)
DEFAULT_ZETARIS_AUDIT_PATH = os.environ.get(
    "RECEIPTS_ZETARIS_AUDIT_LOG", os.path.join(BASE_DIR, "logs", "zetaris-audit.jsonl")
)

DATABASE_NAME = "receipts_evidence"
DATABASE_DESCRIPTION = "Receipts evidence store"
TABLES = ("runs", "claims", "sources")
RUN_QUERY_PATH = "/api/proxy/sql-editor/sqls/run-query"
HIGH_CONFIDENCE_THRESHOLD = 90
DEFAULT_QUERY_LIMIT = 1000

CSV_HEADERS: Dict[str, List[str]] = {
    "runs": ["run_id", "question", "claim_count", "citation_count", "first_seen_ms"],
    "claims": [
        "claim_id", "run_id", "question", "claim_text", "confidence",
        "source_count", "timestamp_ms",
    ],
    "sources": [
        "source_id", "claim_id", "run_id", "source_title", "source_url",
        "domain", "snippet",
    ],
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def zetaris_base_url() -> Optional[str]:
    """Return the configured Zetaris UI origin, or None if unset."""
    url = os.environ.get("ZETARIS_BASE_URL", "").strip()
    return url.rstrip("/") if url else None


def zetaris_api_key() -> Optional[str]:
    key = os.environ.get("ZETARIS_API_KEY", "").strip()
    return key or None


def zetaris_org_id() -> Optional[str]:
    org = os.environ.get("ZETARIS_ORG_ID", "").strip()
    return org or None


def zetaris_jdbc_url() -> Optional[str]:
    """Documented JDBC URL for Java clients; Receipts does not use it."""
    url = os.environ.get("ZETARIS_JDBC_URL", "").strip()
    return url or None


def zetaris_configured() -> bool:
    """True only when a base URL and an API key are both configured."""
    return zetaris_base_url() is not None and zetaris_api_key() is not None


# ---------------------------------------------------------------------------
# Evidence rows + CSV export
# ---------------------------------------------------------------------------

def _clean_text(value: Any) -> str:
    """Flatten a value for CSV export.

    Newlines are replaced with spaces because the Spark CSV reader used
    by Lightning file tables does not read multiline fields by default.
    """
    text = "" if value is None else str(value)
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())


def _domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def build_evidence_rows(records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Shape H-MEM memory record dicts into runs/claims/sources rows.

    ``records`` are Memory.to_dict() dicts: one per verified claim, with
    ``citations`` carrying the sources behind the claim. The same row
    sets feed the CSV export and the local insights computation, which
    is what keeps the local and Zetaris answers identical.
    """
    runs: Dict[str, Dict[str, Any]] = {}
    claims: List[Dict[str, Any]] = []
    sources: List[Dict[str, Any]] = []

    for rec in records:
        claim_id = str(rec.get("id", ""))
        run_id = str(rec.get("run_id") or "")
        question = _clean_text(rec.get("question", ""))
        citations = rec.get("citations", []) or []
        ts = int(rec.get("timestamp") or 0)

        claims.append({
            "claim_id": claim_id,
            "run_id": run_id,
            "question": question,
            "claim_text": _clean_text(rec.get("content", "")),
            "confidence": int(round(float(rec.get("confidence", 0)) * 100)),
            "source_count": len(citations),
            "timestamp_ms": ts,
        })

        run = runs.setdefault(run_id, {
            "run_id": run_id,
            "question": question,
            "claim_count": 0,
            "citation_count": 0,
            "first_seen_ms": ts,
        })
        run["claim_count"] += 1
        run["citation_count"] += len(citations)
        if ts and (not run["first_seen_ms"] or ts < run["first_seen_ms"]):
            run["first_seen_ms"] = ts
        if not run["question"]:
            run["question"] = question

        for idx, cite in enumerate(citations):
            url = cite.get("source_url", "") or ""
            sources.append({
                "source_id": f"src_{claim_id}_{idx}",
                "claim_id": claim_id,
                "run_id": run_id,
                "source_title": _clean_text(cite.get("source_title", "")),
                "source_url": url,
                "domain": _domain_of(url),
                "snippet": _clean_text(cite.get("snippet", "")),
            })

    return {
        "runs": [runs[k] for k in sorted(runs)],
        "claims": claims,
        "sources": sources,
    }


def export_evidence_csvs(
    records: List[Dict[str, Any]],
    out_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Write runs.csv, claims.csv and sources.csv for Zetaris to read.

    Returns the output directory, the per-table file paths and the row
    counts, so callers can register or report exactly what was written.
    """
    target = out_dir or DEFAULT_EXPORT_DIR
    os.makedirs(target, exist_ok=True)
    rows = build_evidence_rows(records)
    files: Dict[str, str] = {}
    counts: Dict[str, int] = {}
    for table in TABLES:
        path = os.path.join(target, f"{table}.csv")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_HEADERS[table])
            writer.writeheader()
            for row in rows[table]:
                writer.writerow({k: row.get(k, "") for k in CSV_HEADERS[table]})
        files[table] = path
        counts[table] = len(rows[table])
    return {"dir": target, "files": files, "counts": counts}


# ---------------------------------------------------------------------------
# Lightning SQL generation (official command reference, sections 4 and 5)
# ---------------------------------------------------------------------------

def create_database_sql(database: str = DATABASE_NAME) -> str:
    return (
        f'CREATE LIGHTNING DATABASE {database} '
        f'DESCRIBE BY "{DATABASE_DESCRIPTION}"'
    )


def create_filestore_table_sql(
    table: str,
    file_path: str,
    database: str = DATABASE_NAME,
) -> str:
    return (
        f"CREATE LIGHTNING FILESTORE TABLE {table} FROM {database} "
        f'FORMAT CSV OPTIONS (path "{file_path}", header "true", delimiter ",")'
    )


def registration_sql(
    file_paths: Dict[str, str],
    database: str = DATABASE_NAME,
) -> List[str]:
    """Statements that register the exported CSVs as file sources.

    One statement per entry: the SQL Workspace and the proxy route both
    take a single statement per execution. Run the database statement
    once on a fresh instance; if the database already exists, skip it
    and run only the table statements.
    """
    statements = [create_database_sql(database)]
    for table in TABLES:
        statements.append(
            create_filestore_table_sql(table, file_paths[table], database)
        )
    return statements


def create_datasource_sql(
    name: str,
    jdbc_url: str,
    username: str,
    password: str,
    driver: str = "org.postgresql.Driver",
    fetchsize: int = 1000,
) -> str:
    """The section 4 CREATE DATASOURCE statement for a JDBC database.

    This is the optional path for pointing Zetaris straight at a
    Postgres evidence database instead of the exported CSV files.
    Tables of a datasource become queryable only after a separate
    REGISTER DATASOURCE TABLES statement, per the same reference.
    """
    return (
        f'CREATE DATASOURCE {name} DESCRIBE BY "PostgreSQL" OPTIONS ('
        f'jdbcdriver "{driver}", jdbcurl "{jdbc_url}", '
        f'username "{username}", password "{password}", '
        f'fetchsize "{fetchsize}")'
    )


# ---------------------------------------------------------------------------
# REST transport (UI proxy route, per the official helper scripts)
# ---------------------------------------------------------------------------

def _headers() -> Dict[str, str]:
    headers = {
        "Authorization": f"Bearer {zetaris_api_key() or ''}",
        "X-Request-ID": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    org = zetaris_org_id()
    if org:
        headers["X-Org-ID"] = org
    return headers


def run_query(
    sql: str,
    limit: int = DEFAULT_QUERY_LIMIT,
    timeout_sec: float = 30.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> Any:
    """Execute ONE Lightning SQL statement via the UI proxy route.

    Returns the decoded JSON body. Raises RuntimeError when Zetaris is
    not configured and propagates HTTP errors, so callers can fall
    back. ``transport`` is injectable for offline unit tests.
    """
    base = zetaris_base_url()
    if not base or not zetaris_api_key():
        raise RuntimeError("Zetaris is not configured (ZETARIS_BASE_URL / ZETARIS_API_KEY unset).")
    body: Dict[str, Any] = {"sql": sql, "limit": limit}
    engine_id = os.environ.get("ZETARIS_ENGINE_ID", "").strip()
    if engine_id:
        body["engineId"] = engine_id
    with httpx.Client(timeout=timeout_sec, transport=transport) as client:
        resp = client.post(f"{base}{RUN_QUERY_PATH}", headers=_headers(), json=body)
        resp.raise_for_status()
        return resp.json()


def _coerce(value: Any) -> Any:
    """Coerce REST string values to numbers where they parse cleanly."""
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            try:
                return int(text)
            except ValueError:
                return value
        try:
            return float(text)
        except ValueError:
            return value
    return value


def parse_rows(payload: Any) -> List[Dict[str, Any]]:
    """Normalize a run-query response into a list of row dicts.

    The response envelope is not shown in the official docs, so the
    shapes the platform commonly returns are all accepted: a bare list
    of row objects, a dict wrapping the rows under data/rows/result/
    results/records, or a columns + rows pair. Keys are lowercased and
    string numbers are coerced (REST returns values as strings).
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        rows: List[Dict[str, Any]] = []
        for item in payload:
            if isinstance(item, dict):
                rows.append({str(k).lower(): _coerce(v) for k, v in item.items()})
            else:
                rows.append({"value": _coerce(item)})
        return rows
    if isinstance(payload, dict):
        columns = payload.get("columns")
        raw_rows = payload.get("rows")
        if isinstance(columns, list) and isinstance(raw_rows, list):
            out: List[Dict[str, Any]] = []
            for raw in raw_rows:
                if isinstance(raw, dict):
                    out.append({str(k).lower(): _coerce(v) for k, v in raw.items()})
                elif isinstance(raw, (list, tuple)):
                    out.append({
                        str(col).lower(): _coerce(val)
                        for col, val in zip(columns, raw)
                    })
            return out
        for key in ("data", "rows", "result", "results", "records"):
            if key in payload:
                return parse_rows(payload[key])
        return [{str(k).lower(): _coerce(v) for k, v in payload.items()}]
    return [{"value": _coerce(payload)}]


def query(
    sql: str,
    limit: int = DEFAULT_QUERY_LIMIT,
    timeout_sec: float = 30.0,
    transport: Optional[httpx.BaseTransport] = None,
) -> List[Dict[str, Any]]:
    """Run one statement and return its rows as dicts."""
    return parse_rows(run_query(sql, limit=limit, timeout_sec=timeout_sec, transport=transport))


def register_sources(
    file_paths: Optional[Dict[str, str]] = None,
    database: str = DATABASE_NAME,
    transport: Optional[httpx.BaseTransport] = None,
) -> List[Dict[str, Any]]:
    """Register the exported CSVs in a running Zetaris instance.

    Sends the registration statements one per call and reports the
    outcome of each; a failed statement is reported, never hidden.
    With no explicit paths, the default export directory is used.
    """
    if file_paths is None:
        base_dir = DEFAULT_EXPORT_DIR
        file_paths = {t: os.path.join(base_dir, f"{t}.csv") for t in TABLES}
    results: List[Dict[str, Any]] = []
    for stmt in registration_sql(file_paths, database):
        try:
            raw = run_query(stmt, transport=transport)
            results.append({"sql": stmt, "ok": True, "response": raw})
        except Exception as exc:
            results.append({"sql": stmt, "ok": False, "error": str(exc)})
    return results


# ---------------------------------------------------------------------------
# Insights: identical aggregates via Zetaris SQL or the local rows
# ---------------------------------------------------------------------------

def totals_sqls(database: str = DATABASE_NAME) -> Dict[str, str]:
    return {
        "runs": f"SELECT COUNT(*) AS n FROM {database}.runs",
        "claims": f"SELECT COUNT(*) AS n FROM {database}.claims",
        "citations": f"SELECT COUNT(*) AS n FROM {database}.sources",
    }


def top_sources_sql(limit: int, database: str = DATABASE_NAME) -> str:
    return (
        "SELECT source_url, MAX(source_title) AS source_title, "
        "COUNT(DISTINCT claim_id) AS claim_count "
        f"FROM {database}.sources "
        "GROUP BY source_url "
        "ORDER BY claim_count DESC, source_url ASC "
        f"LIMIT {int(limit)}"
    )


def avg_confidence_by_domain_sql(database: str = DATABASE_NAME) -> str:
    return (
        "SELECT s.domain AS domain, AVG(c.confidence) AS avg_confidence, "
        "COUNT(DISTINCT s.claim_id) AS claim_count "
        f"FROM {database}.sources s "
        f"JOIN {database}.claims c ON s.claim_id = c.claim_id "
        "GROUP BY s.domain "
        "ORDER BY avg_confidence DESC, domain ASC"
    )


def claims_per_run_sql(database: str = DATABASE_NAME) -> str:
    return (
        "SELECT run_id, COUNT(*) AS claim_count, AVG(confidence) AS avg_confidence "
        f"FROM {database}.claims "
        "GROUP BY run_id "
        "ORDER BY claim_count DESC, run_id ASC"
    )


def high_confidence_claims_sql(limit: int, database: str = DATABASE_NAME) -> str:
    return (
        "SELECT claim_id, claim_text, confidence, run_id "
        f"FROM {database}.claims "
        f"WHERE confidence >= {HIGH_CONFIDENCE_THRESHOLD} "
        "ORDER BY confidence DESC, claim_id ASC "
        f"LIMIT {int(limit)}"
    )


def _canon_top_sources(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{
        "source_url": str(r.get("source_url", "")),
        "source_title": str(r.get("source_title", "")),
        "claim_count": int(r.get("claim_count", 0)),
    } for r in rows]


def _canon_avg_by_domain(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{
        "domain": str(r.get("domain", "")),
        "avg_confidence": round(float(r.get("avg_confidence", 0)), 2),
        "claim_count": int(r.get("claim_count", 0)),
    } for r in rows]


def _canon_claims_per_run(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{
        "run_id": str(r.get("run_id", "")),
        "claim_count": int(r.get("claim_count", 0)),
        "avg_confidence": round(float(r.get("avg_confidence", 0)), 2),
    } for r in rows]


def _canon_high_confidence(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{
        "claim_id": str(r.get("claim_id", "")),
        "claim_text": str(r.get("claim_text", "")),
        "confidence": int(r.get("confidence", 0)),
        "run_id": str(r.get("run_id", "")),
    } for r in rows]


def local_insights(rows: Dict[str, List[Dict[str, Any]]], limit: int = 5) -> Dict[str, Any]:
    """Compute the insight aggregates from exported rows, in-process.

    Mirrors the SQL statements above exactly, including ordering, so
    the local answer and the Zetaris answer are directly comparable.
    """
    claims = rows["claims"]
    sources = rows["sources"]
    claims_by_id = {c["claim_id"]: c for c in claims}

    totals = {
        "runs": len(rows["runs"]),
        "claims": len(claims),
        "citations": len(sources),
    }

    by_url: Dict[str, Dict[str, Any]] = {}
    for s in sources:
        entry = by_url.setdefault(s["source_url"], {
            "source_url": s["source_url"],
            "source_title": s["source_title"],
            "claim_ids": set(),
        })
        entry["claim_ids"].add(s["claim_id"])
    top = [{
        "source_url": e["source_url"],
        "source_title": e["source_title"],
        "claim_count": len(e["claim_ids"]),
    } for e in by_url.values()]
    top.sort(key=lambda e: (-e["claim_count"], e["source_url"]))

    by_domain: Dict[str, Dict[str, Any]] = {}
    for s in sources:
        claim = claims_by_id.get(s["claim_id"])
        if claim is None:
            continue
        entry = by_domain.setdefault(s["domain"], {"conf": {}, })
        entry["conf"][s["claim_id"]] = claim["confidence"]
    domain_rows = [{
        "domain": domain,
        "avg_confidence": round(sum(e["conf"].values()) / len(e["conf"]), 2) if e["conf"] else 0.0,
        "claim_count": len(e["conf"]),
    } for domain, e in by_domain.items()]
    domain_rows.sort(key=lambda e: (-e["avg_confidence"], e["domain"]))

    by_run: Dict[str, List[int]] = {}
    for c in claims:
        by_run.setdefault(c["run_id"], []).append(c["confidence"])
    run_rows = [{
        "run_id": run_id,
        "claim_count": len(confs),
        "avg_confidence": round(sum(confs) / len(confs), 2) if confs else 0.0,
    } for run_id, confs in by_run.items()]
    run_rows.sort(key=lambda e: (-e["claim_count"], e["run_id"]))

    high = [c for c in claims if c["confidence"] >= HIGH_CONFIDENCE_THRESHOLD]
    high.sort(key=lambda c: (-c["confidence"], c["claim_id"]))
    high_rows = [{
        "claim_id": c["claim_id"],
        "claim_text": c["claim_text"],
        "confidence": c["confidence"],
        "run_id": c["run_id"],
    } for c in high]

    return {
        "totals": totals,
        "top_sources": _canon_top_sources(top[:limit]),
        "avg_confidence_by_domain": _canon_avg_by_domain(domain_rows),
        "claims_per_run": _canon_claims_per_run(run_rows),
        "high_confidence_claims": _canon_high_confidence(high_rows[:limit]),
    }


def zetaris_insights(
    limit: int = 5,
    database: str = DATABASE_NAME,
    transport: Optional[httpx.BaseTransport] = None,
) -> Dict[str, Any]:
    """Compute the insight aggregates through a live Zetaris instance.

    Runs the SQL statements above, one statement per call, against the
    registered receipts_evidence tables. Raises on any failure so the
    caller can fall back to the local computation.
    """
    totals: Dict[str, int] = {}
    for key, sql in totals_sqls(database).items():
        rows = query(sql, transport=transport)
        totals[key] = int(rows[0].get("n", 0)) if rows else 0

    return {
        "totals": totals,
        "top_sources": _canon_top_sources(
            query(top_sources_sql(limit, database), transport=transport)
        ),
        "avg_confidence_by_domain": _canon_avg_by_domain(
            query(avg_confidence_by_domain_sql(database), transport=transport)
        ),
        "claims_per_run": _canon_claims_per_run(
            query(claims_per_run_sql(database), transport=transport)
        ),
        "high_confidence_claims": _canon_high_confidence(
            query(high_confidence_claims_sql(limit, database), transport=transport)
        ),
    }


# ---------------------------------------------------------------------------
# Audit log (same append-only JSONL style as logs/memory-audit.jsonl)
# ---------------------------------------------------------------------------

def log_zetaris_event(event: str, payload: Dict[str, Any]) -> None:
    """Append one JSON line to the Zetaris audit log; never raises."""
    path = DEFAULT_ZETARIS_AUDIT_PATH
    line = {"ts": int(time.time() * 1000), "event": event, **payload}
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")
    except Exception as exc:  # the audit must never break a request
        print(f"[Zetaris Audit Error] {exc}")
