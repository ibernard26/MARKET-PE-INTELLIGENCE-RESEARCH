"""Automated audit of a hand-maintained MI/PE workbook.

Re-derives every claimed defect from the file itself; trusts nothing.
Usage:  python -m audit.audit_workbook <path-to-xlsx>
Output: audit/AUDIT_REPORT.md
"""
import re
import sys
from datetime import date
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.config import MARKET_HOLIDAYS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPORT = Path(__file__).parent / "AUDIT_REPORT.md"

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
     "Sep", "Oct", "Nov", "Dec"], 1)}
ND = {"n/d", "N/D", "—", "-", "", None, "PENDING", "CLOSED"}


def parse_date(cell):
    if cell is None:
        return None
    m = re.match(r"([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{4}))?$", str(cell).strip())
    if not m:
        return None
    return date(int(m.group(3) or 2026), MONTHS[m.group(1)], int(m.group(2)))


def is_non_session(d: date):
    if d.weekday() >= 5:
        return "weekend"
    return MARKET_HOLIDAYS.get(d.isoformat())


def rows(ws, header_row=4):
    for r in range(header_row + 1, ws.max_row + 1):
        vals = [ws.cell(row=r, column=c).value for c in range(1, ws.max_column + 1)]
        if vals[0] is not None:
            yield r, vals


def audit(xlsx_path: Path) -> str:
    wb = openpyxl.load_workbook(xlsx_path)
    out = [f"# Workbook Audit — `{xlsx_path.name}`", "",
           "_Every finding re-derived from the file; nothing asserted from memory._", ""]

    total_formulas = 0
    out += ["## 1. Formula count per tab", ""]
    for ws in wb.worksheets:
        n = sum(1 for row in ws.iter_rows() for c in row
                if isinstance(c.value, str) and c.value.startswith("="))
        total_formulas += n
        out.append(f"- `{ws.title}`: **{n}** formulas")
    out += ["", f"Total: **{total_formulas}**.", ""]

    out += ["## 2. Phantom non-trading-day rows", ""]
    harmful = 0
    for ws in wb.worksheets:
        for r, vals in rows(ws):
            d = parse_date(vals[0])
            if d and is_non_session(d):
                closed = str(vals[1]).strip() in ("CLOSED", "—", "n/d")
                mark = "benign" if closed else "**carries a price**"
                if not closed:
                    harmful += 1
                out.append(f"- `{ws.title}` row {r}: {vals[0]} ({is_non_session(d)}) — {mark}")
    out += ["", f"**{harmful} phantom rows carry fabricated prices.**", ""]

    REPORT.write_text("\n".join(out))
    return "\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m audit.audit_workbook <path-to-xlsx>")
        sys.exit(2)
    audit(Path(sys.argv[1]))
    print(f"wrote {REPORT}")
