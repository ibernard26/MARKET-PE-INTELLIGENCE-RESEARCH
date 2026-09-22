"""Seed the price store from the cleaned Phase-0 workbook.

The workbook is an INPUT here exactly once, to bootstrap history that predates
the FRED pull. Every value is calendar-gated (a non-session date is never
written) and lands with provenance 'workbook_v3'. Non-numeric cells
('CLOSED', 'n/d', '-', blank) are treated as no observation and counted, not
fabricated. FRED later supersedes these rows where it has authoritative data.
"""
import re
from datetime import date
from pathlib import Path

import openpyxl

from ..db import connect, upsert_prices

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug",
     "Sep", "Oct", "Nov", "Dec"], 1)}


def _parse_date(cell):
    if cell is None:
        return None
    if isinstance(cell, date):
        return cell.isoformat()
    m = re.match(r"([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{4}))?$", str(cell).strip())
    if not m:
        return None
    return date(int(m.group(3) or 2026), MONTHS[m.group(1)], int(m.group(2))).isoformat()


def _num(v):
    return float(v) if isinstance(v, (int, float)) else None


def _header_map(ws, header_row=4):
    return {str(ws.cell(row=header_row, column=c).value).strip().lower(): c
            for c in range(1, ws.max_column + 1)
            if ws.cell(row=header_row, column=c).value}


def migrate(xlsx_path) -> dict:
    """Read the workbook and upsert prices for the four tracked series.

    Returns {'rows_written': int, 'dates_with_no_data': int}.
    """
    wb = openpyxl.load_workbook(Path(xlsx_path), data_only=True)
    with connect() as _c:
        trading = {r["obs_date"] for r in
                   _c.execute("SELECT obs_date FROM market_calendar WHERE is_trading=1")}

    rows = []
    no_data = 0

    def col(ws, *names):
        hm = _header_map(ws)
        for n in names:
            for key, idx in hm.items():
                if n in key:
                    return idx
        return None

    # Master Log -> SP500, NASDAQCOM
    if "Master Log MI_PE" in wb.sheetnames:
        ws = wb["Master Log MI_PE"]
        c_sp = col(ws, "s&p 500", "s&p")
        c_nq = col(ws, "nasdaq")
        for r in range(5, ws.max_row + 1):
            iso = _parse_date(ws.cell(row=r, column=1).value)
            if not iso or iso not in trading:
                continue
            for sid, ci in (("SP500", c_sp), ("NASDAQCOM", c_nq)):
                if ci is None:
                    continue
                v = _num(ws.cell(row=r, column=ci).value)
                if v is None:
                    no_data += 1
                else:
                    rows.append((sid, iso, v, "workbook_v3"))

    # Oil Tracker -> DCOILWTICO, DCOILBRENTEU
    if "Oil Tracker" in wb.sheetnames:
        ws = wb["Oil Tracker"]
        c_w = col(ws, "wti")
        c_b = col(ws, "brent")
        for r in range(5, ws.max_row + 1):
            iso = _parse_date(ws.cell(row=r, column=1).value)
            if not iso or iso not in trading:
                continue
            for sid, ci in (("DCOILWTICO", c_w), ("DCOILBRENTEU", c_b)):
                if ci is None:
                    continue
                v = _num(ws.cell(row=r, column=ci).value)
                if v is None:
                    no_data += 1
                else:
                    rows.append((sid, iso, v, "workbook_v3"))

    upsert_prices(rows)
    return {"rows_written": len(rows), "dates_with_no_data": no_data}
