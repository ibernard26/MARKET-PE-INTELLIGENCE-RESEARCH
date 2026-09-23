"""Merger arbitrage: spread, annualized return, and break-adjusted expected value.

For an announced deal the arb is the gap between the offer and the current price.
The catch is that the gap is only worth capturing if the deal closes — so the
expected value must be adjusted by the model's break probability:

    upside   = offer_price - current_price          (captured if it closes)
    downside = current_price - unaffected_price     (lost if it breaks)
    EV/share = (1 - p_break)*upside - p_break*downside

Deals are ranked by break-adjusted EV, annualized over the days to expected close.

Point-in-time (Invariant): only deals still `pending` as-of the date are ranked,
and days-to-close is measured from that date. p_break is the score fixed at
announce — never revised with hindsight.

Honesty (Invariant): current_price is a live equity quote that FRED does not
carry. A deal without a stored quote is reported `awaiting_quote`, never
fabricated. The quotes in the seed are illustrative and flagged as such until a
real quote feed is wired in.
"""
from datetime import date

from ..db import connect


# ------------------------------------------------------------- pure math
def gross_spread(offer_price: float, current_price: float) -> float:
    """(offer - current) / current."""
    return (offer_price - current_price) / current_price


def days_to_close(expected_close: str, as_of: str) -> int:
    """Calendar days from as_of to expected close (floored at 1 to stay finite)."""
    d0 = date.fromisoformat(as_of)
    d1 = date.fromisoformat(expected_close)
    return max((d1 - d0).days, 1)


def annualize(period_return: float, days: int) -> float:
    """Simple annualization of a period return over `days`."""
    return period_return * (365.0 / max(days, 1))


def break_adjusted_ev(offer_price: float, current_price: float,
                      p_break: float, unaffected_price: float) -> dict:
    """Break-adjusted expected value, in $/share and as a % of current price."""
    upside = offer_price - current_price
    downside = current_price - unaffected_price
    ev_share = (1.0 - p_break) * upside - p_break * downside
    return {
        "upside": upside,
        "downside": downside,
        "ev_per_share": ev_share,
        "ev_pct": ev_share / current_price,
    }


def evaluate_deal(offer_price: float, current_price: float, p_break: float,
                  unaffected_price: float, expected_close: str, as_of: str) -> dict:
    """All merger-arb metrics for one deal as-of a date."""
    n = days_to_close(expected_close, as_of)
    gs = gross_spread(offer_price, current_price)
    ev = break_adjusted_ev(offer_price, current_price, p_break, unaffected_price)
    return {
        "days_to_close": n,
        "gross_spread": gs,
        "annualized_gross": annualize(gs, n),
        "ev_per_share": ev["ev_per_share"],
        "ev_pct": ev["ev_pct"],
        "annualized_be_ev": annualize(ev["ev_pct"], n),
    }


# ------------------------------------------------------- DB-backed ranker
def rank_live_deals(as_of: str = None, conn=None) -> dict:
    """Rank pending deals by break-adjusted annualized EV, as-of a date.

    Returns {'ranked': [...], 'awaiting_quote': [...]}. A pending deal with a
    full quote set (offer, current, unaffected, expected_close) is scored and
    ranked; one missing any of those is listed under awaiting_quote, not guessed.
    """
    as_of = as_of or date.today().isoformat()
    sql = """
        SELECT deal_id, target, acquirer, sector, p_break,
               offer_price, current_price, unaffected_price, expected_close_date
        FROM deals
        WHERE status = 'pending' AND announce_date <= ?
        ORDER BY deal_id
    """

    def _run(c):
        return list(c.execute(sql, (as_of,)))

    rows = _run(conn) if conn is not None else _run_with_conn(sql, as_of)

    ranked, awaiting = [], []
    for r in rows:
        have_quote = (r["offer_price"] is not None and r["current_price"] is not None
                      and r["unaffected_price"] is not None
                      and r["expected_close_date"] is not None
                      and r["p_break"] is not None)
        base = {"deal_id": r["deal_id"], "target": r["target"],
                "acquirer": r["acquirer"], "sector": r["sector"]}
        if not have_quote:
            awaiting.append({**base, "reason": "no stored live quote / inputs"})
            continue
        m = evaluate_deal(r["offer_price"], r["current_price"], r["p_break"],
                          r["unaffected_price"], r["expected_close_date"], as_of)
        ranked.append({**base, "p_break": r["p_break"], **m})

    ranked.sort(key=lambda d: d["annualized_be_ev"], reverse=True)
    return {"as_of": as_of, "ranked": ranked, "awaiting_quote": awaiting}


def _run_with_conn(sql, as_of):
    with connect() as c:
        return list(c.execute(sql, (as_of,)))
