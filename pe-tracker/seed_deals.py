"""Seed the deals ledger with the resolvable transactions identified from the
source workbook. Idempotent (INSERT OR REPLACE).

All are 'pending' unless a sourced resolution is given (EA closed 2026-08-04).
Update statuses only from sourced, verified resolutions per STRATEGY.md.

Usage: python seed_deals.py
"""
from src.db import connect, init_db, migrate_schema

DEALS = [
    # deal_id, announce_date, acquirer, target, sponsor, value_usd_mm, sector,
    # geography, offer_premium, deal_type, resolution_date, status, p_break,
    # model_version, source_note
    ("EA-PIF-2026", "2026-06-17", "PIF/Silver Lake/Affinity", "Electronic Arts",
     "PIF/Silver Lake/Affinity", 55000, "Gaming/Tech", "US", None, "take_private",
     "2026-08-04", "closed", 0.28, "event_driven_v1",
     "Largest LBO on record; $210/sh; CFIUS cleared 2026-07-30, closed 2026-08-04"),
    ("EZJ-CASTLELAKE-2026", "2026-07-05", "Castlelake", "easyJet", "Castlelake",
     7300, "Airlines", "UK", None, "take_private", None, "pending", 0.22,
     "event_driven_v1", "690p/share cash; UK regulatory + shareholder vote"),
    ("ORGN-SUNP-2026", "2026-04-27", "Sun Pharma", "Organon", None,
     11750, "Healthcare", "US/IN", None, "strategic", None, "pending", 0.18,
     "event_driven_v1", "Generics antitrust"),
    ("CALIBER-NEE-2026", "2026-06-19", "NextEra Energy", "Caliber Resource Partners",
     "Quantum Capital", 1300, "Energy", "US", None, "JV", None, "pending", 0.15,
     "event_driven_v1", "Energy-infrastructure clearance"),
    ("FORVIA-APO-2026", "2026-04-27", "Apollo Global", "Forvia auto interiors", "Apollo",
     2100, "Industrials", "EU/US", None, "LBO", None, "pending", 0.20,
     "event_driven_v1", "Financing"),
    ("ANTH-TPU-FIN-2026", "2026-05-29", "Apollo/Blackstone", "Anthropic (TPU financing)",
     "Apollo/Blackstone", 36000, "AI", "US", None, "financing", None, "pending", 0.10,
     "event_driven_v1", "Private credit, not M&A arb — ledger completeness only"),
]

if __name__ == "__main__":
    init_db()
    migrate_schema()
    with connect() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO deals
               (deal_id, announce_date, acquirer, target, sponsor, value_usd_mm,
                sector, geography, offer_premium, deal_type, resolution_date,
                status, p_break, model_version, source_note)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", DEALS)
        n = conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0]
        pend = conn.execute("SELECT COUNT(*) FROM deals WHERE status='pending'").fetchone()[0]
    print(f"seeded {n} deals ({pend} pending/censored)")
