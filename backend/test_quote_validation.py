"""Regression tests for quote-completeness validation (Oct 27 defect).

A snippet ending mid-sentence must be dropped, never completed.
Importing app.py tolerates missing keys with warnings; set the temp
H-MEM paths before import, as in test_pipeline.py.
"""

import os
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="receipts-quote-test-")
os.environ.setdefault("RECEIPTS_MEMORY_DB", os.path.join(_TMP, "memory.db"))
os.environ.setdefault("RECEIPTS_AUDIT_LOG", os.path.join(_TMP, "logs", "memory-audit.jsonl"))

from app import is_complete_quote, validate_claims


GOOD = "Intermittent fasting was safe and effective in this trial."
TRUNCATED = "When done under supervision, intermittent fasting can be"
SOURCE = (
    "When done under supervision, intermittent fasting can be safe. "
    "Intermittent fasting was safe and effective in this trial."
)


class TestQuoteValidation(unittest.TestCase):
    def test_truncated_snippet_is_dropped(self):
        self.assertFalse(is_complete_quote(TRUNCATED, [SOURCE]))

    def test_complete_sentence_is_kept(self):
        self.assertTrue(is_complete_quote(GOOD, [SOURCE]))

    def test_sentence_minus_final_period_is_kept(self):
        # Search snippets often omit the final period. The source ends
        # right after the snippet, so it is not cut mid-sentence.
        snippet = "Intermittent fasting was safe and effective in this trial"
        self.assertTrue(is_complete_quote(snippet, [SOURCE]))

    def test_ellipsis_is_rejected(self):
        self.assertFalse(is_complete_quote("Intermittent fasting was safe...", [SOURCE]))

    def test_claim_with_one_good_and_one_truncated_keeps_only_good(self):
        claims = [{
            "claim_text": "Fasting can be safe.",
            "confidence": 90,
            "citations": [
                {"source_title": "A", "source_url": "https://example.com/a", "snippet": GOOD},
                {"source_title": "B", "source_url": "https://example.com/b", "snippet": TRUNCATED},
            ],
        }]
        kept, dropped_cites, dropped_claims = validate_claims(claims, [SOURCE])
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(kept[0]["citations"]), 1)
        self.assertEqual(kept[0]["citations"][0]["snippet"], GOOD)
        self.assertEqual((dropped_cites, dropped_claims), (1, 0))

    def test_claim_with_only_truncated_citations_is_not_stored(self):
        claims = [{
            "claim_text": "Fasting can be safe.",
            "confidence": 90,
            "citations": [
                {"source_title": "B", "source_url": "https://example.com/b", "snippet": TRUNCATED},
            ],
        }]
        kept, dropped_cites, dropped_claims = validate_claims(claims, [SOURCE])
        self.assertEqual(kept, [])
        self.assertEqual((dropped_cites, dropped_claims), (1, 1))

    def test_complete_sentence_not_in_source_is_dropped(self):
        self.assertFalse(
            is_complete_quote("A completely different sentence here.", [SOURCE]))

    def test_validator_never_completes_a_truncated_snippet(self):
        self.assertFalse(is_complete_quote(TRUNCATED, [SOURCE]))
        kept, _, _ = validate_claims([{
            "claim_text": "X", "confidence": 50,
            "citations": [{"source_title": "B", "source_url": "https://example.com/b", "snippet": TRUNCATED}],
        }], [SOURCE])
        self.assertEqual(kept, [])


if __name__ == "__main__":
    unittest.main()
