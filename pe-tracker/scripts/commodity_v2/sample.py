"""Preregistered sample selection (prereg §4-§5)."""
from __future__ import annotations

import random

V1_SEED = 20261009
V2_SEED = 2026100902
N = 20

V2_SAMPLE_PREREG = [
    "DEAL-ANN-ASCENA-2015", "DEAL-APC-OXY-2019", "DEAL-BARRY-MRGB-2014", "DEAL-BLYTH-CARLYL-2015",
    "DEAL-CEC-APOLLO-2014", "DEAL-CERN-ORCL-2021", "DEAL-CPRI-TPR-2023", "DEAL-EA-PIFSLAFF-2025",
    "DEAL-EINSTE-JAB-2014", "DEAL-ENTROP-MAXLIN-2015", "DEAL-IMPRIV-THOMA-2016",
    "DEAL-INFORM-ITALIC-2015", "DEAL-LNKD-MSFT-2016", "DEAL-MKTG-AEGIS-2014", "DEAL-MXIM-ADI-2020",
    "DEAL-NUAN-MSFT-2021", "DEAL-ODP-SPLS-2015", "DEAL-ORBITZ-EXPEDI-2015",
    "DEAL-REYNOL-IMPERI-2014", "DEAL-STEINE-CATTER-2015"]


def v1_dev_sample(ids) -> list[str]:
    return sorted(random.Random(V1_SEED).sample(sorted(ids), N))


def v2_validation_sample(ids) -> list[str]:
    ids = sorted(ids)
    pool = sorted(set(ids) - set(v1_dev_sample(ids)))
    return sorted(random.Random(V2_SEED).sample(pool, N))
