"""Issuer-name agreement used to validate ticker → security identity.

A provider's issuer name must agree with the SEC target name before any of its
prices are attributed to the deal. The rule is deliberately strict and fixed
ex-ante: after dropping legal-form/filler words, one name's significant tokens
must be a non-empty subset of the other's. No fuzzy scoring, no guessing —
disagreement defers the deal.
"""
from __future__ import annotations

import re
from typing import Optional

FILLER = frozenset("""
    the inc incorporated corp corporation co company companies ltd limited plc
    llc lp l p sa s a nv n v ag se holdings holding group trust the class cl
    common stock shares share ordinary new com de del delaware
""".split())


def significant_tokens(name: Optional[str]) -> frozenset[str]:
    s = (name or "").lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return frozenset(t for t in s.split() if t and t not in FILLER and t != "and")


def names_agree(a: Optional[str], b: Optional[str]) -> bool:
    ta, tb = significant_tokens(a), significant_tokens(b)
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta
