"""Command line entry point.

    python -m spending --inputs STATEMENTS_DIR [--rules personal-rules.toml]
                       [--out OUT_DIR] [--month YYYY-MM]

Writes to OUT_DIR:
    summary.json            month-by-month totals (no raw transactions)
    report-YYYY-MM.html     the visual monthly report
    exports/*.csv           aggregate tables for other charts
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analyze import latest_complete_month, load, summarize
from .export import write_exports
from .report import build


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="spending", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--inputs", nargs="+", type=Path, required=True,
                    help="statement files or folders (Apple Card CSV, Chase PDF, Bank of America PDF)")
    ap.add_argument("--rules", type=Path, help="personal rules file, checked before the defaults")
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--month", help="YYYY-MM to report on (default: latest month every account covers)")
    a = ap.parse_args(argv)

    ds = load(a.inputs, a.rules)
    summary = summarize(ds)
    month = a.month or latest_complete_month(summary)
    if not month or month not in summary["months"]:
        print(f"No data for month {month!r}. Months found: {', '.join(summary['months'])}", file=sys.stderr)
        return 1

    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "summary.json").write_text(json.dumps(summary, indent=2))
    report = a.out / f"report-{month}.html"
    report.write_text(build(summary, month))
    write_exports(ds, summary, a.out / "exports")

    m = summary["months"][month]
    print(f"Report for {month}: {report}")
    print(f"  money in {m['income_total']:,.0f}  rent {m['rent']:,.0f}  everyday {m['everyday_total']:,.0f}  "
          f"one-offs {m['one_off_total']:,.0f}  saved {m['saved']:,.0f}")
    if not m["complete"]:
        print(f"  partial month: missing {', '.join(m['missing_accounts'])}")
    for w in summary["warnings"]:
        print(f"  warning: {w}")
    for f in summary["skipped_files"]:
        print(f"  skipped (not a recognized statement): {f}")
    if m["uncategorized"]:
        print(f"  {len(m['uncategorized'])} uncategorized transactions this month")
    return 0


if __name__ == "__main__":
    sys.exit(main())
