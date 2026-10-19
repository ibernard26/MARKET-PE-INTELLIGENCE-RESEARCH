"""Isolated geopolitical-intelligence RESEARCH module (staging only).

Status: RESEARCH STAGING. Nothing in this package is a model feature.

  schema        controlled vocabularies, timestamp parsing, EvidenceRecord
  verification  derives VERIFIED_PRIMARY … RETRACTED from evidence (as of T)
  store         append-only evidence ledger (JSONL), dedup, revision chains
  pit           bitemporal gate: valid_time <= T AND known_at <= T
  exposure      event -> deal research links (confirmed vs sector hypothesis)
  reporting     read-only chart data / report from existing repo data

Isolation contract (enforced by tests/test_geo_intel_isolation.py):
  * src/model and src/research never import this package;
  * this package never imports the model fitting / validation code;
  * fs_v1 (14 features), break_logit_v1, first_walkforward_v1/protocol.json
    and the event_driven_v1 strategy constants are untouched;
  * it never writes to the canonical SQLite store (pe_tracker.db).

Grok / X briefs are UNTRUSTED secondary intelligence. They can open an
evidence cluster but can never verify or corroborate it.
"""

MODULE_STATUS = "RESEARCH_STAGING_NOT_A_MODEL_FEATURE"
MODEL_EXECUTION_STATUS = (
    "NON-EXECUTABLE FOR LIVE TRADING AND UNVALIDATED FOR EMPIRICAL PREDICTION")
