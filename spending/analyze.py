"""Load statements, apply rules and roll everything up by calendar month."""
from __future__ import annotations

import calendar
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .parsers import Statement, Txn, read_statement
from .rules import DEFAULT_RULES, categorize, load_rules

RENT = "Rent"


@dataclass
class Dataset:
    txns: list[Txn]
    coverage: dict[str, list[tuple[date, date]]]
    files: list[str]
    skipped_files: list[str]
    warnings: list[str] = field(default_factory=list)
    expected_accounts: list[str] = field(default_factory=list)
    # (statement end date, {account: closing balance}) for bank statements.
    balances: list[tuple[date, dict[str, float]]] = field(default_factory=list)
    settings: dict = field(default_factory=dict)


def _merge(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1] + timedelta(days=1):
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def load(inputs: list[Path], personal_rules: Path | None = None) -> Dataset:
    files = []
    for p in inputs:
        files.extend(sorted(x for x in p.rglob("*") if x.is_file()) if p.is_dir() else [p])

    statements: list[Statement] = []
    skipped = []
    warnings = []
    for f in files:
        st = read_statement(f)
        if st is None:
            skipped.append(str(f))
            continue
        for acct, expected in st.expected_net.items():
            got = round(sum(t.amount for t in st.txns if t.account == acct), 2)
            if abs(got - expected) > 0.01:
                warnings.append(
                    f"{f.name}: {acct} transactions add up to {got:,.2f} but the statement "
                    f"balance changed by {expected:,.2f}. Some lines may not have been read.")
        statements.append(st)

    # The same transaction can arrive twice (a full-year CSV plus a monthly one, or
    # a statement uploaded again). For each account keep, per identical transaction,
    # the largest number of copies any single file has.
    best: dict[str, Counter] = defaultdict(Counter)
    sample: dict[tuple, Txn] = {}
    for st in statements:
        per_file: dict[str, Counter] = defaultdict(Counter)
        for t in st.txns:
            key = (t.date, round(t.amount, 2), t.description)
            per_file[t.account][key] += 1
            sample.setdefault((t.account, key), t)
        for acct, c in per_file.items():
            for key, n in c.items():
                best[acct][key] = max(best[acct][key], n)
    txns = []
    for acct, c in best.items():
        for key, n in c.items():
            proto = sample[(acct, key)]
            for _ in range(n):
                txns.append(Txn(**{k: getattr(proto, k) for k in proto.__dataclass_fields__}))
    txns.sort(key=lambda t: (t.date, t.account, t.description))

    coverage: dict[str, list] = defaultdict(list)
    for st in statements:
        for acct in st.account_kinds:
            coverage[acct].append((st.start, st.end))
    coverage = {a: _merge(iv) for a, iv in coverage.items()}

    rules = []
    expected_accounts: list[str] = []
    settings: dict = {}
    if personal_rules and personal_rules.exists():
        rules += load_rules(personal_rules)
        settings = tomllib.loads(personal_rules.read_text()).get("settings", {})
        expected_accounts = list(settings.get("accounts", []))
    rules += load_rules(DEFAULT_RULES)
    categorize(txns, rules)

    balances = sorted({st.end: st.end_balance for st in statements if st.end_balance}.items())
    return Dataset(txns, coverage, [str(f) for f in files], skipped, warnings,
                   expected_accounts or sorted(coverage), balances, settings)


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_bounds(key: str) -> tuple[date, date]:
    y, m = (int(x) for x in key.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _covered(coverage, acct, start, end) -> bool:
    return any(s <= start and e >= end for s, e in coverage.get(acct, []))


def summarize(ds: Dataset) -> dict:
    by_month: dict[str, list[Txn]] = defaultdict(list)
    for t in ds.txns:
        by_month[t.count_in or month_key(t.date)].append(t)

    # Savings that never reach checking, such as 401(k) contributions taken out
    # of each paycheck. Added to "saved" in any month with a paycheck.
    retire = float(ds.settings.get("retirement_monthly", 0) or 0)
    retire_label = ds.settings.get("retirement_label", "Retirement")
    # Exact amounts for particular months (e.g. a bonus that went straight in).
    retire_by_month = {k: float(v) for k, v in ds.settings.get("retirement_by_month", {}).items()}
    retire_estimate = bool(ds.settings.get("retirement_estimate", False))
    months = {}
    for key in sorted(by_month):
        start, end = month_bounds(key)
        missing = [a for a in ds.expected_accounts if not _covered(ds.coverage, a, start, end)]
        income, income_one_off = Counter(), Counter()
        everyday, one_offs = Counter(), Counter()
        rent = 0.0
        merchants: dict[str, list] = defaultdict(lambda: [0.0, 0])
        counts = Counter()
        big, one_off_items, unknown = [], [], []
        for t in by_month[key]:
            if t.kind == "skip":
                continue
            if t.kind == "income":
                (income_one_off if t.one_off else income)[t.category] += -t.amount
                if t.one_off:
                    one_off_items.append(_item(t, money_in=True))
                continue
            if t.category == RENT:
                rent += t.amount
            elif t.one_off:
                one_offs[t.category] += t.amount
                one_off_items.append(_item(t))
            else:
                everyday[t.category] += t.amount
                if t.amount > 0:
                    m = merchants[t.merchant]
                    m[0] += t.amount
                    m[1] += 1
                    counts[t.category] += 1
                if t.amount >= 150:
                    big.append(_item(t))
                if t.category == "Uncategorized":
                    unknown.append(_item(t))
        income_total = sum(income.values())
        everyday_total = sum(everyday.values())
        one_off_total = sum(one_offs.values())
        saved = income_total - rent - everyday_total
        if key in retire_by_month:
            retirement = retire_by_month[key]
        else:
            retirement = retire if income.get("Paychecks", 0) > 0 else 0.0
        saved_total = saved + retirement
        gross_ish = income_total + retirement
        months[key] = {
            "complete": not missing,
            "missing_accounts": missing,
            "income": _r(income),
            "income_total": round(income_total, 2),
            "income_one_off": _r(income_one_off),
            "rent": round(rent, 2),
            "everyday": _r(everyday),
            "everyday_total": round(everyday_total, 2),
            "one_offs": _r(one_offs),
            "one_off_total": round(one_off_total, 2),
            "saved": round(saved, 2),
            "saved_after_one_offs": round(saved - one_off_total + sum(income_one_off.values()), 2),
            "retirement": round(retirement, 2),
            "saved_total": round(saved_total, 2),
            # Share of pay saved, counting retirement contributions as both pay and savings.
            "savings_rate": round(saved_total / gross_ish, 4) if gross_ish > 0 else None,
            "cash_savings_rate": round(saved / income_total, 4) if income_total > 0 else None,
            "counts": dict(counts),
            "top_places": sorted(([n, round(v[0], 2), v[1]] for n, v in merchants.items()),
                                 key=lambda x: -x[1])[:10],
            "big_purchases": sorted(big, key=lambda x: -x["amount"]),
            "one_off_items": one_off_items,
            "uncategorized": unknown,
        }
    return {
        "retirement_label": retire_label,
        "retirement_estimate": retire_estimate and not retire_by_month,
        "pay_changes": [dict(p) for p in ds.settings.get("pay_change", [])],
        "coverage": {a: [[s.isoformat(), e.isoformat()] for s, e in iv] for a, iv in ds.coverage.items()},
        "accounts": ds.expected_accounts,
        "months": months,
        "warnings": ds.warnings,
        "skipped_files": ds.skipped_files,
    }


def _r(c: Counter) -> dict:
    return {k: round(v, 2) for k, v in sorted(c.items(), key=lambda kv: -kv[1]) if abs(v) >= 0.005}


def _item(t: Txn, money_in: bool = False) -> dict:
    return {"date": t.date.isoformat(), "account": t.account, "merchant": t.merchant,
            "category": t.category, "amount": round(-t.amount if money_in else t.amount, 2),
            "note": t.note}


def latest_complete_month(summary: dict) -> str | None:
    done = [k for k, m in summary["months"].items() if m["complete"]]
    return done[-1] if done else None
