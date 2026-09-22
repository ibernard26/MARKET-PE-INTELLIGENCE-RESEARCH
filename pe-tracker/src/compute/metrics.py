"""Deal-break evaluation metrics.

The rare positive class is the deal BREAKING (y=1 <=> status='broken').
Every function takes an `as_of` cut and sees only deals with
resolution_date <= as_of — pending deals are censored, never negatives,
and nothing resolved after the cut can leak in (point-in-time discipline).

Why both AUCs:
- ROC AUC conditions on the actual class (TPR, FPR), so it is
  prevalence-invariant: it will NOT move as the break rate π changes.
- PR AUC conditions on the predicted class (precision), so it inherits π.
  It is only readable NEXT TO π.
"""
from dataclasses import dataclass

from ..config import COST_FN, COST_FP, COST_RATIO_GRID
from ..db import connect


# ---------------------------------------------------------------- loading
def resolved_deals(as_of: str, conn=None):
    """(deal_id, p_break, y) for deals resolved on or before as_of.

    Censoring is enforced HERE, in the loader — no metric below ever sees
    a pending deal or a post-cut resolution.
    """
    sql = """
        SELECT deal_id, p_break, CASE status WHEN 'broken' THEN 1 ELSE 0 END AS y
        FROM deals
        WHERE status IN ('closed','broken')
          AND resolution_date IS NOT NULL
          AND resolution_date <= ?
          AND p_break IS NOT NULL
        ORDER BY deal_id
    """
    if conn is not None:
        return [(r["deal_id"], r["p_break"], r["y"]) for r in conn.execute(sql, (as_of,))]
    with connect() as c:
        return [(r["deal_id"], r["p_break"], r["y"]) for r in c.execute(sql, (as_of,))]


# ------------------------------------------------------- confusion matrix
@dataclass
class Confusion:
    tp: int; fp: int; fn: int; tn: int

    @property
    def tpr(self):        # P(flag | broke) — conditions on actual class
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else None

    @property
    def fpr(self):        # P(flag | closed) — conditions on actual class
        return self.fp / (self.fp + self.tn) if (self.fp + self.tn) else None

    @property
    def precision(self):  # P(broke | flag) — conditions on prediction => π-dependent
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else None

    recall = tpr


def confusion_at(pairs, t: float) -> Confusion:
    """Flag 'at-risk' when p_break >= t."""
    tp = sum(1 for _, p, y in pairs if p >= t and y == 1)
    fp = sum(1 for _, p, y in pairs if p >= t and y == 0)
    fn = sum(1 for _, p, y in pairs if p < t and y == 1)
    tn = sum(1 for _, p, y in pairs if p < t and y == 0)
    return Confusion(tp, fp, fn, tn)


# ------------------------------------------------------------------- AUCs
def roc_auc_rank(pairs) -> float | None:
    """Mann–Whitney form with AVERAGED tied ranks — expressible in SQL.

    AUC = (Σ rank(positives) − n_pos(n_pos+1)/2) / (n_pos · n_neg)
    """
    scores = sorted((p, y) for _, p, y in pairs)
    n = len(scores)
    n_pos = sum(y for _, y in scores)
    n_neg = n - n_pos
    if not n_pos or not n_neg:
        return None
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and scores[j + 1][0] == scores[i][0]:
            j += 1
        avg = (i + j) / 2 + 1          # ranks are 1-based
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    rank_sum_pos = sum(r for r, (_, y) in zip(ranks, scores) if y == 1)
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def aucs(pairs) -> dict:
    """Rank-based ROC AUC cross-checked against sklearn, plus PR AUC vs π."""
    y = [yy for _, _, yy in pairs]
    p = [pp for _, pp, _ in pairs]
    pi = sum(y) / len(y) if y else None
    ours = roc_auc_rank(pairs)
    out = {"n": len(y), "pi": pi, "roc_auc": ours,
           "pr_auc": None, "pr_baseline": pi, "roc_auc_sklearn": None}
    if ours is not None:
        from sklearn.metrics import average_precision_score, roc_auc_score
        sk = float(roc_auc_score(y, p))
        assert abs(sk - ours) < 1e-9, f"rank AUC {ours} != sklearn {sk}"
        out["roc_auc_sklearn"] = sk
        out["pr_auc"] = float(average_precision_score(y, p))
    return out


# ------------------------------------------------ cost-based operating point
def optimal_threshold(pairs, cost_fp: float = COST_FP, cost_fn: float = COST_FN):
    """t* = argmin over candidate thresholds of FP·cost_fp + FN·cost_fn.

    With breaks rare AND expensive, t* sits far below 0.5 — defaulting to 0.5
    is the classic error.
    """
    if not pairs:
        return None
    candidates = sorted({p for _, p, _ in pairs} | {0.0, 1.0})
    best = None
    for t in candidates:
        c = confusion_at(pairs, t)
        cost = c.fp * cost_fp + c.fn * cost_fn
        if best is None or cost < best[1]:
            best = (t, cost, c)
    t, cost, c = best
    return {"t_star": t, "expected_cost": cost, "cost_fp": cost_fp,
            "cost_fn": cost_fn, "confusion": c}


def threshold_cost_curve(pairs, ratios=COST_RATIO_GRID):
    """How t* migrates as the FN:FP cost ratio changes."""
    return {r: optimal_threshold(pairs, cost_fp=1.0, cost_fn=float(r))
            for r in ratios}


# ------------------------------------------------------------ scorecard
def model_scorecard(as_of: str, group_by: str = "quarter", conn=None) -> list[dict]:
    """One row per cohort: n, π, ROC AUC, PR AUC (vs π), t*, confusion at t*."""
    key_sql = {
        "quarter": "substr(announce_date,1,4) || '-Q' || ((cast(substr(announce_date,6,2) as int)+2)/3)",
        "geography": "COALESCE(geography,'?')",
        "deal_type": "COALESCE(deal_type,'?')",
        "all": "'all'",
    }[group_by]
    sql = f"""
        SELECT {key_sql} AS cohort, deal_id, p_break,
               CASE status WHEN 'broken' THEN 1 ELSE 0 END AS y
        FROM deals
        WHERE status IN ('closed','broken')
          AND resolution_date IS NOT NULL AND resolution_date <= ?
          AND p_break IS NOT NULL
        ORDER BY cohort, deal_id
    """
    rows = {}
    def run(c):
        for r in c.execute(sql, (as_of,)):
            rows.setdefault(r["cohort"], []).append((r["deal_id"], r["p_break"], r["y"]))
    if conn is not None:
        run(conn)
    else:
        with connect() as c:
            run(c)

    cards = []
    for cohort, pairs in sorted(rows.items()):
        a = aucs(pairs)
        opt = optimal_threshold(pairs)
        card = {"as_of": as_of, "cohort": cohort, **{k: a[k] for k in
                ("n", "pi", "roc_auc", "pr_auc", "pr_baseline")}}
        if opt:
            card.update({"t_star": opt["t_star"],
                         "tp": opt["confusion"].tp, "fp": opt["confusion"].fp,
                         "fn": opt["confusion"].fn, "tn": opt["confusion"].tn})
        cards.append(card)
    if not cards:
        cards.append({"as_of": as_of, "cohort": "all", "n": 0, "pi": None,
                      "roc_auc": None, "pr_auc": None, "pr_baseline": None,
                      "note": "no resolved, scored deals as of this date — "
                              "book is 100% pending (censored); metrics "
                              "activate at first resolution"})
    return cards
