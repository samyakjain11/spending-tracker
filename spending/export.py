"""Aggregate CSV exports for charts elsewhere. No individual transactions."""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

from .analyze import Dataset
from .report import EAT_OUT


def write_exports(ds: Dataset, summary: dict, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []

    p = out / "category_by_month.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "category", "amount", "eat_out", "one_off", "complete"])
        for m, d in summary["months"].items():
            for c, v in d["everyday"].items():
                w.writerow([m, c, f"{v:.2f}", c in EAT_OUT, False, d["complete"]])
            for c, v in d["one_offs"].items():
                w.writerow([m, c, f"{v:.2f}", False, True, d["complete"]])
    written.append(p)

    p = out / "monthly.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "income", "rent", "other_spending", "one_offs", "saved", "retirement",
                    "saved_total", "savings_rate", "complete"])
        for m, d in summary["months"].items():
            w.writerow([m, f"{d['income_total']:.2f}", f"{d['rent']:.2f}", f"{d['everyday_total']:.2f}",
                        f"{d['one_off_total']:.2f}", f"{d['saved']:.2f}",
                        f"{d['retirement']:.2f}", f"{d['saved_total']:.2f}",
                        "" if d["savings_rate"] is None else f"{d['savings_rate']:.4f}", d["complete"]])
    written.append(p)

    # Cash on hand and net amount invested, at each bank statement close.
    # Investing flows are netted: money sent to a broker minus money it sent back.
    flows = defaultdict(list)
    for t in ds.txns:
        if t.category == "Investing" and t.account in ("checking", "savings"):
            name = re.search(r"WEALTHFRONT|ROBINHOOD|FIDELITY|VANGUARD|SCHWAB|BETTERMENT|COINBASE",
                             t.description, re.I)
            flows[(name.group(0).lower() if name else "other")].append((t.date, t.amount))
    brokers = sorted(flows)
    p = out / "balances.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "cash"] + [f"{b}_net_cumulative" for b in brokers])
        for end, bal in ds.balances:
            row = [end.isoformat(), f"{sum(bal.values()):.2f}"]
            for b in brokers:
                row.append(f"{sum(a for d, a in flows[b] if d <= end):.2f}")
            w.writerow(row)
    written.append(p)
    return written
