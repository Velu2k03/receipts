# Sample inputs and outputs

Three samples, each labelled for what it actually is. No sample here
is presented as a live run unless it says so.

## Sample 1: live hosted run, Oct 27, 2026

Input:

```
Is intermittent fasting safe for people with type 2 diabetes?
```

Observed output, from a fresh browser run of
https://receipts-livid.vercel.app, answered in under 45 seconds:

- 5 claims, 10 claim-source pairings across 8 distinct URLs
- Confidence scores: 95, 98, 95, 90, 90
- Every claim had 2 sources
- Trace, 6 steps: init, planner, searcher, extractor_scorer,
  storage, composer, with 20 distinct sources collected across
  3 sub-questions
- Looks right / Flag controls present on every expanded claim

Known defect in that run, which caused the quote fix: one claim
citation quote ended mid-sentence at "can be". The repo fix drops
such citations instead of storing them. The live site is not fixed
until the Supabase Edge Function is redeployed; see
`docs/DEMO-VIDEO-NOTE.md` and the deploy note in the hackathon goal
folder.

Claim texts and quotes from that run are not reproduced here,
because they were not captured verbatim in the QA record.

## Sample 2: Python pipeline test fixture, offline

This is test data from `backend/test_memory_engine.py`, not a live
answer and not medical evidence. It shows the H-MEM flow: a first
question stores claims, a related second question retrieves them.

First input:

```
Do standing desks actually improve productivity?
```

Result: 200, 2 claims, no prior memory claims.

Stored fixture claims, verbatim from the test:

- "Standing desks reduced sedentary time by 1.2 hours per workday
  in a 2023 review." Confidence 85. Citation: "A 2023 review found
  standing desks reduced sedentary time by 1.2 hours per workday."
- "Sit-stand desks showed no significant effect on productivity
  measures." Confidence 70.

Second input:

```
Do standing desks reduce sitting time at work?
```

Result: 200, at least 1 memory claim returned, containing
"sedentary", with 1 citation, and exactly 1 trace step with action
"memory" and detail containing "prior claims found".

Unrelated input:

```
How do I bake sourdough bread at home?
```

Result: 200, no memory claims returned.

## Sample 3: evidence insights response shape

`GET /evidence/insights` always names its serving engine. With no
Zetaris instance configured, the response is:

```json
{
  "engine": "local",
  "database": "receipts_evidence",
  "zetaris_configured": false,
  "totals": {"runs": 0, "claims": 0, "citations": 0},
  "top_sources": [],
  "avg_confidence_by_domain": [],
  "claims_per_run": [],
  "high_confidence_claims": []
}
```

Totals and lists are filled from the exported evidence rows when a
store exists. With a Zetaris instance configured and answering,
`"engine"` is `"zetaris"` and `"zetaris_configured"` is true; on a
Zetaris failure the response falls back to `"local"` and includes
`"fallback_reason"`. High-confidence means confidence 90 or above.
