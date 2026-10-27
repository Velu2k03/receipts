"""
Receipts evidence memory: a local implementation of the Meterless H-MEM
engine contract (MemoryStoreService + MemoryRetrievalService).

Design notes
------------
The H-MEM canonical record shape is followed field for field (see
engines/hmem/HOW_TO_USE_H-MEM.md in the Meterless repo): id, content, type,
layer, timestamp, lastAccessed, accessCount, tags, domain, namespace,
embedding, score, confidence, source, entities, relatedTo, supersedes,
supersededBy, derivedFrom, provenance. ``confidence`` and ``source`` are
mandatory; a record without a source is rejected by construction.

Extensions for Receipts are additive keys only: ``question`` (the question
the claim answered), ``run_id`` and ``citations`` (the exact source quotes
behind the claim), so a retrieved memory can be shown with its receipts.

Persistence is SQLite (standard library) under ``data/`` so the engine runs
with zero external services. Every mutation and retrieval is appended as a
JSON line to ``logs/memory-audit.jsonl``; that append-only file plays the
role of the H-MEM trust ledger for this implementation.

Retrieval uses the documented eight-signal hybrid ranker with one honest
substitution: there is no neural embedder here, so the embedding is a
bag-of-words token vector and the cosine term is lexical. The final score
is clamp01(raw) * confidence, exactly as specified, and the score
breakdown is returned in the trace so the ranking is fully transparent.
"""

import json
import math
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Paths (overridable for tests and for sample mode)
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Fallback paths, kept for backwards compatibility. Do NOT read these
# at construction time: the live paths are resolved lazily below, so a
# test that sets RECEIPTS_MEMORY_DB after this module is already
# imported still gets its own isolated store instead of the real DB.
# That import-order bug is what used to pollute data/memory.db with
# test fixtures when test_pipeline ran before test_memory_engine.
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "data", "memory.db")
DEFAULT_AUDIT_PATH = os.path.join(BASE_DIR, "logs", "memory-audit.jsonl")


def default_db_path() -> str:
    return os.environ.get("RECEIPTS_MEMORY_DB", DEFAULT_DB_PATH)


def default_audit_path() -> str:
    return os.environ.get("RECEIPTS_AUDIT_LOG", DEFAULT_AUDIT_PATH)

# H-MEM defaults (HOW_TO_USE_H-MEM.md, operational checklist). The spec
# default threshold is 0.35; it is tuned to 0.30 here because Receipts
# multiplies by claim confidence (evidence strength 0..1), which runs
# lower than chat-memory confidence. The guide explicitly says to tune
# the threshold per domain.
DEFAULT_TOP_N = 5
DEFAULT_THRESHOLD = 0.30
ENTITY_CAP = 10

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "do", "does", "did",
    "what", "which", "who", "whom", "when", "where", "why", "how",
    "can", "could", "should", "would", "will", "shall", "may", "might",
    "of", "on", "in", "at", "to", "for", "with", "by", "from", "as",
    "and", "or", "but", "if", "then", "than", "that", "this", "these",
    "those", "it", "its", "be", "been", "being", "have", "has", "had",
    "you", "your", "we", "our", "they", "their", "i", "me", "my",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _stem(word: str) -> str:
    """Tiny suffix stemmer so 'reduced' and 'reduce' share a token."""
    for suffix in ("ingly", "edly", "ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    if word.endswith("e") and len(word) >= 5:
        return word[:-1]
    return word


def tokenize(text: str) -> List[str]:
    """Lowercase word tokens, lightly stemmed, stopwords removed."""
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [_stem(w) for w in words if w not in STOPWORDS and len(w) > 1]


def _bow(tokens: List[str]) -> Dict[str, int]:
    vec: Dict[str, int] = {}
    for t in tokens:
        vec[t] = vec.get(t, 0) + 1
    return vec


def _cosine(a: Dict[str, int], b: Dict[str, int]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[t] * b.get(t, 0) for t in a)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
# Canonical H-MEM memory record
# ---------------------------------------------------------------------------

@dataclass
class Memory:
    content: str
    source: str
    confidence: float  # 0..1, mandatory in H-MEM
    type: str = "factual"
    layer: str = "long_term"
    id: str = field(default_factory=lambda: "mem_" + uuid.uuid4().hex[:16])
    timestamp: int = field(default_factory=_now_ms)
    last_accessed: int = field(default_factory=_now_ms)
    access_count: int = 0
    tags: List[str] = field(default_factory=list)
    domain: Optional[str] = None
    namespace: Optional[str] = None
    embedding: Optional[List[float]] = None
    score: Optional[float] = None
    entities: List[Dict[str, str]] = field(default_factory=list)
    related_to: List[str] = field(default_factory=list)
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    derived_from: List[str] = field(default_factory=list)
    provenance: Optional[Dict[str, Any]] = None
    # Receipts extensions (additive)
    question: str = ""
    run_id: Optional[str] = None
    citations: List[Dict[str, str]] = field(default_factory=list)

    def __post_init__(self):
        # H-MEM contract: a record without a source is rejected.
        if not self.source:
            raise ValueError("Memory record requires a non-empty 'source'.")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("Memory 'confidence' must be within [0, 1].")
        if self.provenance is None:
            self.provenance = {
                "origin": "tool",
                "learnedAt": self.timestamp,
                "label": f"stored from {self.source}",
                "refs": {},
            }

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Memory":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def _entities_for(text: str) -> List[Dict[str, str]]:
    seen: List[str] = []
    for tok in tokenize(text):
        if tok not in seen:
            seen.append(tok)
        if len(seen) >= ENTITY_CAP:
            break
    return [{"name": t, "type": "keyword"} for t in seen]


# ---------------------------------------------------------------------------
# MemoryStoreService
# ---------------------------------------------------------------------------

class MemoryStoreService:
    """Durable store for verified Receipts claims, H-MEM style.

    Hydrates an in-memory cache from SQLite at startup; every write goes
    to SQLite and to the append-only JSONL audit log.
    """

    def __init__(self, db_path: str = None, audit_path: str = None):
        # Resolve from the environment at construction time, not at
        # import time, so test isolation survives any import order.
        self.db_path = db_path if db_path is not None else default_db_path()
        self.audit_path = audit_path if audit_path is not None else default_audit_path()
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        os.makedirs(os.path.dirname(self.audit_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS memories ("
            " id TEXT PRIMARY KEY, layer TEXT, record TEXT)"
        )
        self._conn.commit()
        self._cache: Dict[str, Memory] = {}
        self.hydrate()

    # -- H-MEM: hydrate -------------------------------------------------
    def hydrate(self) -> List[Memory]:
        rows = self._conn.execute("SELECT record FROM memories").fetchall()
        self._cache = {}
        for (blob,) in rows:
            mem = Memory.from_dict(json.loads(blob))
            self._cache[mem.id] = mem
        return list(self._cache.values())

    # -- audit ledger (append-only) -------------------------------------
    def _audit(self, event: str, payload: Dict[str, Any]) -> None:
        line = {"ts": _now_ms(), "event": event, **payload}
        try:
            with open(self.audit_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(line) + "\n")
        except Exception as exc:  # audit must never break the pipeline
            print(f"[Memory Audit Error] {exc}")

    # -- writes -----------------------------------------------------------
    def add(self, memory: Memory) -> Memory:
        self._cache[memory.id] = memory
        self._conn.execute(
            "INSERT OR REPLACE INTO memories (id, layer, record) VALUES (?, ?, ?)",
            (memory.id, memory.layer, json.dumps(memory.to_dict())),
        )
        self._conn.commit()
        self._audit("add", {"memory_id": memory.id, "source": memory.source})
        return memory

    def update(self, memory: Memory) -> Memory:
        return self.add(memory)

    def get(self, memory_id: str) -> Optional[Memory]:
        return self._cache.get(memory_id)

    def all(self) -> List[Memory]:
        return list(self._cache.values())

    def store_run(
        self,
        question: str,
        claims: List[Dict[str, Any]],
        run_id: Optional[str] = None,
        created_at_ms: Optional[int] = None,
    ) -> List[Memory]:
        """Store every verified claim of a completed run as a memory.

        ``claims`` items follow the pipeline shape: claim_text, confidence
        (0..100), citations [{source_title, source_url, snippet}].
        Returns the stored Memory records. Defense in depth for the
        pipeline filter: a claim with no citations is skipped here
        too, so an uncited fallback can never be stored as a verified
        memory even if a caller forgets to filter.
        """
        ts = created_at_ms or _now_ms()
        stored: List[Memory] = []
        skipped_uncited = 0
        q_tokens = tokenize(question)
        for claim in claims:
            text = (claim.get("claim_text") or "").strip()
            if not text:
                continue
            if not claim.get("citations"):
                skipped_uncited += 1
                continue
            confidence = _clamp01(float(claim.get("confidence", 0)) / 100.0)
            citations = [
                {
                    "source_title": c.get("source_title", ""),
                    "source_url": c.get("source_url", ""),
                    "snippet": c.get("snippet", ""),
                }
                for c in claim.get("citations", [])
            ]
            first_url = citations[0]["source_url"] if citations else ""
            mem = Memory(
                content=text,
                type="factual",
                layer="long_term",
                timestamp=ts,
                last_accessed=ts,
                confidence=confidence,
                source=f"receipts:run:{run_id}" if run_id else "receipts:run:unknown",
                tags=list(dict.fromkeys(q_tokens)),
                domain="receipts/evidence",
                entities=_entities_for(question + " " + text),
                provenance={
                    "origin": "tool",
                    "learnedAt": ts,
                    "label": f"verified claim from Receipts run {run_id}",
                    "refs": {"sourceUrl": first_url},
                },
                question=question,
                run_id=run_id,
                citations=citations,
            )
            stored.append(self.add(mem))
        self._audit(
            "store_run",
            {
                "run_id": run_id,
                "question": question,
                "stored": len(stored),
                "skipped_uncited": skipped_uncited,
                "memory_ids": [m.id for m in stored],
            },
        )
        return stored

    def mark_accessed(self, memory: Memory) -> None:
        memory.access_count += 1
        memory.last_accessed = _now_ms()
        self._conn.execute(
            "INSERT OR REPLACE INTO memories (id, layer, record) VALUES (?, ?, ?)",
            (memory.id, memory.layer, json.dumps(memory.to_dict())),
        )
        self._conn.commit()


# ---------------------------------------------------------------------------
# MemoryRetrievalService
# ---------------------------------------------------------------------------

class MemoryRetrievalService:
    """Hybrid-ranked retrieval over the store, per the H-MEM ranker.

    Signals and weights follow HOW_TO_USE_H-MEM.md section 6. The
    embedding is a bag-of-words vector, so the cosine signal is lexical;
    every other signal is computed exactly as documented. The final
    score is clamp01(raw) * confidence.
    """

    LAYER_WEIGHTS = {"long_term": 1.0, "working": 0.8, "short_term": 0.6}
    RECENCY_TAU_MS = 14 * 86400 * 1000  # ~14 day time constant

    def __init__(self, store: MemoryStoreService):
        self.store = store

    def _score(self, query_tokens: List[str], mem: Memory) -> Tuple[float, Dict[str, float]]:
        doc_tokens = tokenize(mem.question + " " + mem.content)
        q_bow = _bow(query_tokens)
        d_bow = _bow(doc_tokens)
        cosine = _cosine(q_bow, d_bow)

        top_q = set(query_tokens[:8])
        keyword_overlap = _jaccard(top_q, set(tokenize(mem.content)))
        tag_overlap = _jaccard(set(query_tokens), set(mem.tags))

        q_entities = {t for t in query_tokens}
        m_entities = {e["name"] for e in mem.entities}
        entity_overlap = _jaccard(q_entities, m_entities)

        layer_w = self.LAYER_WEIGHTS.get(mem.layer, 0.6)
        age = max(0, _now_ms() - mem.last_accessed)
        recency = math.exp(-age / self.RECENCY_TAU_MS)

        raw = (
            0.35 * cosine
            + 0.20 * keyword_overlap
            + 0.10 * tag_overlap
            + 0.15 * entity_overlap
            + 0.05 * layer_w
            + 0.05 * recency
            - 0.20 * (1.0 if mem.superseded_by else 0.0)
        )
        final = _clamp01(raw) * mem.confidence
        breakdown = {
            "cosine": round(cosine, 4),
            "keyword_overlap": round(keyword_overlap, 4),
            "tag_overlap": round(tag_overlap, 4),
            "entity_overlap": round(entity_overlap, 4),
            "layer_weight": layer_w,
            "recency": round(recency, 4),
            "raw": round(raw, 4),
            "confidence": mem.confidence,
            "final": round(final, 4),
        }
        return final, breakdown

    def query(
        self,
        text: str,
        top_n: int = DEFAULT_TOP_N,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Return (memories, trace). Memories are record dicts plus score."""
        query_tokens = tokenize(text)
        scored: List[Tuple[float, Memory, Dict[str, float]]] = []
        for mem in self.store.all():
            final, breakdown = self._score(query_tokens, mem)
            if final >= threshold:
                scored.append((final, mem, breakdown))
        scored.sort(key=lambda item: item[0], reverse=True)
        scored = scored[:top_n]

        results: List[Dict[str, Any]] = []
        for final, mem, breakdown in scored:
            self.store.mark_accessed(mem)
            record = mem.to_dict()
            record["score"] = round(final, 4)
            record["score_breakdown"] = breakdown
            results.append(record)

        trace = {
            "query": text,
            "strategy": "lexical-hybrid (H-MEM eight-signal ranker, BoW cosine)",
            "threshold": threshold,
            "top_n": top_n,
            "candidates": len(self.store.all()),
            "matched": len(results),
        }
        self.store._audit("retrieve", {**trace, "memory_ids": [r["id"] for r in results]})
        return results, trace
