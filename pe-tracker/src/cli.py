"""Command line entry point.

    python -m src.cli init
    python -m src.cli migrate <path-to-xlsx>
    python -m src.cli pull [--start 2026-04-20]
    python -m src.cli gaps [--series SP500]
    python -m src.cli signals [--series SP500]
    python -m src.cli sweep [--series SP500]
    python -m src.cli scorecard [--as-of DATE] [--group-by all|quarter|geography|deal_type]
    python -m src.cli backtest [--series SP500]
"""
import argparse
import json
from datetime import date

from .config import SERIES, START_DATE
from .db import coverage_report, init_db, migrate_schema, missing_dates
from .ingest.market_calendar import build_calendar


def cmd_init(args):
    path = init_db()
    migrate_schema()
    n = build_calendar(START_DATE, args.end or date.today().isoformat())
    print(f"database: {path}")
    print(f"calendar: {n} trading days through {args.end or date.today().isoformat()}")


def cmd_migrate(args):
    from .ingest.migrate_xlsx import migrate
    print(json.dumps(migrate(args.xlsx), indent=2))


def cmd_pull(args):
    from .ingest.fred import ingest_all
    print(json.dumps(ingest_all(start=args.start, end=args.end), indent=2))


def cmd_gaps(args):
    for row in coverage_report():
        pct = row["missing"] / row["trading_days"] if row["trading_days"] else 0
        print(f"{row['series_id']:<14} {row['missing']:>3}/{row['trading_days']:<3} missing ({pct:.0%})")
    if args.series:
        print(f"\nmissing dates for {args.series}:")
        for d in missing_dates(args.series):
            print(" ", d)


def cmd_signals(args):
    from .compute.signals import run
    df = run(args.series)
    cols = ["obs_date", "close", "daily_pct", "ma", "window_complete", "mtd_pct", "signal"]
    print(df[cols].tail(args.tail).to_string(index=False))
    print("\ndistribution:", df["signal"].value_counts().to_dict())


def cmd_sweep(args):
    from .compute.sweep import report, sweep
    df = sweep(args.series, min_n=args.min_n)
    print(report(df, top=args.top))


def cmd_scorecard(args):
    from .compute.metrics import model_scorecard
    print(json.dumps(model_scorecard(args.as_of or date.today().isoformat(),
                                     args.group_by), indent=2))


def cmd_backtest(args):
    from .compute.signals import backtest, run
    print(json.dumps(backtest(run(args.series, persist_result=False)), indent=2))


def main():
    p = argparse.ArgumentParser(prog="pe-tracker")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("init");     a.add_argument("--end"); a.set_defaults(fn=cmd_init)
    a = sub.add_parser("migrate");  a.add_argument("xlsx");  a.set_defaults(fn=cmd_migrate)
    a = sub.add_parser("pull")
    a.add_argument("--start", default=START_DATE); a.add_argument("--end")
    a.set_defaults(fn=cmd_pull)
    a = sub.add_parser("gaps");     a.add_argument("--series", choices=list(SERIES))
    a.set_defaults(fn=cmd_gaps)
    a = sub.add_parser("signals")
    a.add_argument("--series", default="SP500", choices=list(SERIES))
    a.add_argument("--tail", type=int, default=15)
    a.set_defaults(fn=cmd_signals)
    a = sub.add_parser("sweep")
    a.add_argument("--series", default="SP500", choices=list(SERIES))
    a.add_argument("--min-n", type=int, default=20)
    a.add_argument("--top", type=int, default=10)
    a.set_defaults(fn=cmd_sweep)
    a = sub.add_parser("scorecard")
    a.add_argument("--as-of", dest="as_of")
    a.add_argument("--group-by", dest="group_by", default="all",
                   choices=["all", "quarter", "geography", "deal_type"])
    a.set_defaults(fn=cmd_scorecard)
    a = sub.add_parser("backtest")
    a.add_argument("--series", default="SP500", choices=list(SERIES))
    a.set_defaults(fn=cmd_backtest)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
