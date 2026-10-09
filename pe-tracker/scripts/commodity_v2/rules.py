"""Rule-based first-pass labeler for commodity-exposure v2 (prereg §1).

Pure functions over sentences; no I/O. Flags: producer, consumer, hedged.
Absence of evidence is `unknown`, never `no` (no-silent-zero rule).
"""
from __future__ import annotations

import re

FLAGS = ("producer", "consumer", "hedged")
FLAG_VALUES = {"producer": {"yes", "unknown"}, "consumer": {"yes", "unknown"},
               "hedged": {"yes", "no_disclosed", "unknown"}}
MAX_SENTENCE = 700

FP = re.compile(r"\b(we|our|us|the company)\b", re.I)

# --- exclusions shared by all flags (prereg §1, common requirements) --------
R_FACTOR_INTRO = re.compile(r"\b(factors|risks|uncertainties)\s+(include|including|such as)\b|"
                            r"\bincluding,?\s+(but|without)\s+(not\s+)?limit", re.I)


def is_factor_list(s: str) -> bool:
    if len(s) > MAX_SENTENCE:
        return True
    if s.count("•") >= 3 or s.count("·") >= 3 or s.count(";") >= 2:
        return True
    if R_FACTOR_INTRO.search(s):
        return True
    m = re.search(r"\b(such as|including)\b(.*)", s, re.I)
    return bool(m and m.group(2).count(",") >= 4)


# --- producer (prereg §1.1) ---------------------------------------------------
_P_COMMOD = (r"(crude oil|oil and (natural )?gas|oil, natural gas|natural gas liquids|natural gas|"
             r"ngls?|coal|metallurgical coal|copper|gold|silver|iron ore|aluminum|aluminium|zinc|"
             r"nickel|lithium|uranium|potash|phosphates?|ethanol|timber|lumber|grains?|corn|"
             r"soybeans?|wheat|oilseeds?|beef|pork|chicken|poultry|turkeys?|meat|cattle|hogs|"
             r"livestock|petrochemicals?|refined (petroleum )?products|oil)")
_P_PROC = r"(beef|pork|chicken|poultry|turkeys?|meat|grains?|corn|soybeans?|wheat|oilseeds?|cattle|hogs)"
R_PROD_VERB = re.compile(
    r"\b(we|the company)\b[^.;]{0,60}?\b(produc(e|es|ed|ing)|extract(s|ed|ing)?|mines?|mined|mining|"
    r"drill(s|ed|ing)? for|refin(e|es|ed|ing))\b[^.;]{0,60}?\b" + _P_COMMOD + r"\b", re.I)
R_PROD_PROC = re.compile(
    r"\b(we|the company)\b[^.;]{0,60}?\b(process(es|ed|ing)?|rais(e|es|ed|ing)|grow(s|n)?)\b"
    r"[^.;]{0,40}?\b" + _P_PROC + r"\b", re.I)
R_PROD_NOUN = re.compile(
    r"\b(we|the company)\b\s+(is|are|was|were|has been)\s+[^.;]{0,80}?\b(producers?|refiners?|"
    r"miners?|processors?)\s+(and [a-z]+ )?of\b[^.;]{0,60}?\b" + _P_COMMOD + r"\b", re.I)
R_PROD_OWN = re.compile(r"\bour\s+(total\s+|net\s+|daily\s+|average\s+)*(crude oil|oil|natural gas|"
                        r"oil and (natural )?gas|ngls?|coal|copper|gold|production)\s+"
                        r"(production|reserves|output)\b|\bour (estimated )?(total )?proved "
                        r"(developed )?(and undeveloped )?(oil|gas|natural gas|reserves)\b|"
                        r"\b(we|the company)\s+(have|has|had|own|owns|hold|holds)\s+[^.;]{0,40}?"
                        r"\bproved\s+(developed\s+)?reserves\b", re.I)
R_PROD_NOT = re.compile(r"\b(transport\w*|gather\w*|purchas\w*|buy(s|ing)?|suppliers?|"
                        r"raw materials?|hedg\w*|customers?|services? (to|for)|for (our )?clients|"
                        r"price of|prices of|cost of|costs of)\b", re.I)


def producer(s: str) -> bool:
    for rx in (R_PROD_VERB, R_PROD_PROC, R_PROD_NOUN, R_PROD_OWN):
        for m in rx.finditer(s):
            if not R_PROD_NOT.search(m.group(0)):
                return True
    return False


# --- consumer (prereg §1.2) ---------------------------------------------------
_C_INPUT = (r"(raw materials?|commodit(y|ies)|commodity[- ]based|jet fuel|fuel|diesel|gasoline|"
            r"natural gas|electricity|crude oil|steel|aluminum|aluminium|copper|nickel|zinc|tin|"
            r"platinum|palladium|resins?|plastics?|polyethylene|pulp|paperboard|packaging materials?|"
            r"corn|wheat|soybeans?|soybean meal|sugar|coffee|cocoa|cotton|dairy|milk|cheese|"
            r"butter|beef|pork|poultry|chicken|feed|grains?|flour)")
R_C_INPUT = re.compile(r"\b" + _C_INPUT + r"\b", re.I)
_C_COSTWORD = r"(costs?|prices?|pricing|expenses?|surcharges?)"
R_C_TIE = re.compile(
    r"\b(cost|costs|price|prices|pricing|availability\s+and\s+(cost|price)s?)\s+(of|for)\b"
    r"[^.;]{0,50}?\b" + _C_INPUT + r"\b"
    r"|\b" + _C_INPUT + r"\b[^.;]{0,25}?\b" + _C_COSTWORD + r"\b"
    r"|\b(purchases?\s+of|we\s+(purchase|buy|use|consume|source|procure))\b[^.;]{0,50}?\b"
    + _C_INPUT + r"\b"
    r"|\b" + _C_INPUT + r"\b[^.;]{0,30}?\b(used\s+(in|as)|we\s+use|that\s+we\s+(purchase|use))\b",
    re.I)
R_C_IMPACT = re.compile(r"\b(increas\w*|ris(e|es|en|ing)|fluctuat\w*|volatil\w*|higher|adverse\w*|"
                        r"impact\w*|affect\w*|"
                        r"inflation\w*|escalat\w*|spikes?|changes? in)\b", re.I)
R_C_SELLSIDE = re.compile(
    r"\b(prices?\s+(that\s+)?we\s+(receive|realize)|realized\s+prices?|price[s]?\s+for\s+our\s+"
    r"(oil|gas|natural gas|production|products|crude)|demand\s+for\s+(our|oil|natural gas)|"
    r"our\s+(oil|gas|natural gas|crude oil)\s+(production|revenues?|reserves|sales)|"
    r"(sales|selling)\s+prices?|revenues?\s+from|value\s+of\s+(our|its)\s+reserves|"
    r"reserves?|declin\w*\s+in\s+[^.;]{0,40}?prices?|prices?\s+(declin|fall|drop|decreas)\w*|"
    r"(oil|gas|energy|mining|coal)\s+(industry|sector|companies|exploration|producers?|properties|"
    r"wells)|low(er)?\s+(commodity\s+)?prices?|"
    r"price\s+environment|(we|that\s+we)\s+produce|our\s+production|for\s+our\s+production|"
    r"drilling)\b", re.I)
R_C_BUYSIDE = re.compile(r"\b(raw materials?|prices?\s+(that\s+)?we\s+pay|purchases?\s+of|"
                         r"we\s+(purchase|buy|use|consume)|input\s+costs?|feedstock)\b", re.I)
R_C_BUYSIDE_STRONG = re.compile(r"\b(raw[- ]materials?|prices?\s+(that\s+)?we\s+pay|purchases?\s+of|"
                                r"input\s+costs?|feedstocks?)\b", re.I)
R_C_OWNCOST = re.compile(
    r"\b(our|its|the\s+company[’']s)\s+([a-z\-]+\s+){0,3}(costs?|expenses?|margins?)\b|"
    r"\bcosts?\s+of\s+(goods\s+sold|sales|revenues?|products|producing|operating|operations|"
    r"manufactur\w+)\b|\b(we|the\s+company)\s+(purchase|buy|use|consume|pay|source|procure)\b|"
    r"\braw[- ]materials?\b|\binput\s+costs?\b|\b(operating|production|manufacturing)\s+costs?\b|"
    r"\b(higher|increased|rising|increases\s+in)\s+([a-z]+\s+){0,3}(costs?|expenses?)\b|"
    r"\bincrease[sd]?\s+(our|its)\s+costs?\b", re.I)
R_C_INVEST = re.compile(r"\b(portfolios?|investments?|securities|bonds?|loans?|borrowers?|"
                        r"credit\s+exposure|lending|underwrit\w*)\b", re.I)


def consumer(s: str) -> bool:
    if not (R_C_TIE.search(s) and R_C_IMPACT.search(s) and R_C_OWNCOST.search(s)):
        return False
    if R_C_SELLSIDE.search(s) and not R_C_BUYSIDE_STRONG.search(s):
        return False
    if R_C_INVEST.search(s):
        return False
    return True


# --- hedged (prereg §1.3) -----------------------------------------------------
_H_DERIV = (r"(hedg\w*|derivatives?|futures|forward\s+(contracts?|purchases?|purchase\s+contracts?|"
            r"sales?)|swaps?|collars?|commodity\s+options|call\s+options|put\s+options|"
            r"option\s+contracts?)")
_H_COMM = (r"(commodit(y|ies)|jet fuel|fuel|diesel|heating oil|gasoline|propane|natural gas|"
           r"crude( oil)?|oil|ngls?|electricity|power purchase|aluminum|aluminium|copper|steel|"
           r"nickel|zinc|metals?|resins?|corn|wheat|soybeans?|soybean meal|sugar|coffee|cocoa|"
           r"cotton|dairy|milk|cheese|grains?|hogs|cattle|livestock|lean hogs)")
R_H_NEAR = re.compile(r"\b" + _H_DERIV + r"\b.{0,160}?\b" + _H_COMM + r"\b|\b" + _H_COMM +
                      r"\b.{0,160}?\b" + _H_DERIV + r"\b", re.I)
R_H_NONQUAL = re.compile(r"\bno\s+(well[- ]established\s+)?(global\s+)?(liquid\s+)?market\s+for\s+"
                         r"hedg\w*|\bnot\s+(be\s+)?able\s+to\s+hedge\b|\bunable\s+to\s+hedge\b", re.I)
R_H_MAYONLY = re.compile(r"\b(may|might|could)\b[^.]{0,40}\b(hedge|enter\s+into|use|utilize)\b", re.I)
R_H_AFFIRM = re.compile(r"\b(we|the company)\s+(currently\s+|also\s+|have\s+|has\s+|had\s+|"
                        r"periodically\s+|routinely\s+|generally\s+|primarily\s+)*(use[sd]?|"
                        r"entered|enter(s)?\s+into|utiliz\w+|hedge[sd]?|hold|held|employ\w*|"
                        r"purchase[sd]?|manage[sd]?|mitigate[sd]?)\b|\bour\s+(commodity\s+)?"
                        r"(hedg\w*|derivative|futures|swap)\w*\b|\b(hedges?|derivatives?|futures|"
                        r"swaps?|contracts?)\s+(were|are|was|is)\s+(designated|outstanding|"
                        r"recorded|used)\b", re.I)
R_H_NEG = re.compile(r"\b(do|does|did)\s+not\s+(currently\s+)?(hedge|use|enter\s+into|utilize|"
                     r"engage\s+in|have)\b[^.]{0,80}\b(hedg\w*|derivatives?|futures|swaps?|"
                     r"commodit\w*|fuel|natural gas|exposure)\b|\bno\s+(commodity\s+)?"
                     r"(hedg\w*|derivatives?)\s+(were|are|was|is)\s+(outstanding|in place)\b", re.I)
R_H_SPEC = re.compile(r"(trading|speculative)\s+purposes", re.I)
R_H_NONCOMM = re.compile(r"\b(interest[- ]rate|currenc\w*|foreign exchange|equity|credit|"
                         r"convertible|note hedge)\b", re.I)


def hedged(s: str) -> str | None:
    m = R_H_NEAR.search(s)
    if not m:
        return None
    if R_H_NONQUAL.search(s):
        return None
    if R_H_NEG.search(s) and not R_H_SPEC.search(s):
        return "no_disclosed"
    if R_H_MAYONLY.search(s) and not R_H_AFFIRM.search(s):
        return None
    if not R_H_AFFIRM.search(s):
        return None
    return "yes"


# --- sentence classifier ------------------------------------------------------
def classify(sentence: str) -> dict:
    s = sentence.strip()
    if len(s) < 20 or is_factor_list(s) or not FP.search(s):
        return {}
    out = {}
    if producer(s):
        out["producer"] = "yes"
    if consumer(s):
        out["consumer"] = "yes"
    h = hedged(s)
    if h:
        out["hedged"] = h
    return out


def sentences(text: str):
    pos = 0
    for s in re.split(r"(?<=[.!?;])\s+(?=[A-Z(•])", text):
        yield pos, s
        pos += len(s) + 1


R_ITEM = re.compile(r"\bItem\s+(\d{1,2}[AB]?)\b\.?", re.I)


def item_at(text: str, off: int) -> str:
    last = None
    for m in R_ITEM.finditer(text, 0, off):
        last = m.group(1).upper()
    return f"Item {last}" if last else "pre-Item (cover/intro)"


def label_text_docs(docs) -> tuple[dict, dict]:
    """docs: iterable of (filing_meta, text). Returns (flags, evidence).

    Party-level guard (prereg §1.2, sales-price exposure excluded): when the party is a
    producer, a consumer sentence counts only if it carries an explicit buy-side marker
    (raw materials, purchases of, prices we pay, input costs, feedstock).
    """
    row = {f: "unknown" for f in FLAGS}
    ev, consumer_cands = {}, []
    for f, text in docs:
        for off, s in sentences(text):
            for flag, val in classify(s).items():
                rec = {**f, "item": item_at(text, off), "offset": off, "quote": s.strip()[:400]}
                if flag == "consumer":
                    consumer_cands.append((bool(R_C_BUYSIDE_STRONG.search(s)), rec))
                    continue
                cur = row[flag]
                if cur == "unknown" or (flag == "hedged" and cur == "no_disclosed" and val == "yes"):
                    row[flag] = val
                    ev[flag] = rec
    ok = [rec for buy, rec in consumer_cands if buy or row["producer"] != "yes"]
    if ok:
        row["consumer"] = "yes"
        ev["consumer"] = ok[0]
    return row, ev
