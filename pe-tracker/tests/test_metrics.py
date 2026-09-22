"""Guardrails for the deal-break evaluation layer.

Fixtures build an in-memory deals table so tests never touch the real DB.
"""
import sqlite3
from pathlib import Path

import pytest

from src.compute.metrics import (aucs, confusion_at, model_scorecard,
                                 optimal_threshold, resolved_deals,
                                 roc_auc_rank)

SCHEMA = (Path(__file__).resolve().parents[1] / "schema.sql").read_text()


def db_with(deals):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executemany(
        """INSERT INTO deals (deal_id, announce_date, status,
                              resolution_date, p_break)
           VALUES (?,?,?,?,?)""", deals)
    return conn


BOOK = [
    ("D1", "2026-01-05", "closed", "2026-03-01", 0.10),
    ("D2", "2026-01-12", "closed", "2026-04-01", 0.20),
    ("D3", "2026-02-02", "broken", "2026-05-01", 0.80),
    ("D4", "2026-02-20", "closed", "2026-06-01", 0.30),
    ("D5", "2026-03-03", "broken", "2026-07-01", 0.60),
    ("D6", "2026-03-15", "pending", None, 0.50),
]


def test_as_of_cut_excludes_future_resolutions():
    conn = db_with(BOOK)
    early = resolved_deals("2026-05-15", conn)          # D1, D2, D3 resolved
    assert [d for d, _, _ in early] == ["D1", "D2", "D3"]
    conn.execute("""INSERT INTO deals (deal_id, announce_date, status,
                    resolution_date, p_break)
                    VALUES ('LATE','2026-04-01','broken','2026-12-31',0.99)""")
    assert resolved_deals("2026-05-15", conn) == early
    assert aucs(early) == aucs(resolved_deals("2026-05-15", conn))


def test_pending_deals_are_censored_not_negatives():
    conn = db_with(BOOK)
    pairs = resolved_deals("2026-12-31", conn)
    assert "D6" not in [d for d, _, _ in pairs]
    assert len(pairs) == 5


def test_confusion_and_conditional_rates():
    conn = db_with(BOOK)
    pairs = resolved_deals("2026-12-31", conn)           # y: 0,0,1,0,1
    c = confusion_at(pairs, t=0.55)                      # flags D3(.8), D5(.6)
    assert (c.tp, c.fp, c.fn, c.tn) == (2, 0, 0, 3)
    assert c.tpr == 1.0
    assert c.fpr == 0.0
    assert c.precision == 1.0


def test_rank_auc_matches_sklearn_perfect_separation():
    conn = db_with(BOOK)
    out = aucs(resolved_deals("2026-12-31", conn))
    assert out["roc_auc"] == 1.0
    assert out["roc_auc_sklearn"] == pytest.approx(1.0)
    assert out["pi"] == pytest.approx(2 / 5)
    assert out["pr_baseline"] == out["pi"]


def test_tied_scores_use_averaged_ranks():
    pairs = [("a", 0.5, 1), ("b", 0.5, 0), ("c", 0.2, 0), ("d", 0.9, 1)]
    ours = roc_auc_rank(pairs)
    from sklearn.metrics import roc_auc_score
    sk = roc_auc_score([y for _, _, y in pairs], [p for _, p, _ in pairs])
    assert ours == pytest.approx(sk)
    assert ours == pytest.approx(0.875)


def test_expensive_fn_pushes_threshold_down():
    conn = db_with(BOOK)
    pairs = resolved_deals("2026-12-31", conn)
    cheap_fn = optimal_threshold(pairs, cost_fp=1, cost_fn=1)
    dear_fn = optimal_threshold(pairs, cost_fp=1, cost_fn=20)
    assert dear_fn["t_star"] <= cheap_fn["t_star"] <= 0.9
    assert dear_fn["confusion"].fn == 0


def test_scorecard_reports_censored_book_honestly():
    conn = db_with([("P1", "2026-06-01", "pending", None, 0.4)])
    cards = model_scorecard("2026-12-31", "all", conn)
    assert cards[0]["n"] == 0 and "pending" in cards[0]["note"]


def test_real_db_has_no_derived_or_fabricated_prices():
    from src.db import connect, init_db, migrate_schema
    init_db()
    migrate_schema()
    with connect() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(prices)")]
        assert "is_derived" in cols
        n_derived = conn.execute(
            "SELECT COUNT(*) FROM prices WHERE is_derived = 1").fetchone()[0]
        assert n_derived == 0
        n_phantom = conn.execute("""
            SELECT COUNT(*) FROM prices p
            JOIN market_calendar c ON c.obs_date = p.obs_date
            WHERE c.is_trading = 0 AND p.close IS NOT NULL""").fetchone()[0]
        assert n_phantom == 0


def test_generated_workbook_passes_python_formula_gate():
    import generate_workbook as gw
    out = Path(gw.OUT)
    if not out.exists():
        pytest.skip("workbook not generated in this checkout")
    gate = gw.verify_formulas(out)
    assert gate["failures"] == 0 and gate["formulas_checked"] > 0
