"""Apply categorization rules to transactions."""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .parsers import Txn

DEFAULT_RULES = Path(__file__).resolve().parent.parent / "rules" / "default.toml"


@dataclass
class Rule:
    category: str
    kind: str = "spend"
    one_off: bool = False
    match: re.Pattern | None = None
    accounts: tuple[str, ...] = ()
    type: str | None = None
    source_category: re.Pattern | None = None
    date: date | None = None
    amount: float | None = None
    merchant: str = ""
    note: str = ""
    count_in: str = ""

    def applies(self, t: Txn) -> bool:
        if self.accounts and t.account not in self.accounts:
            return False
        if self.type and t.source_type.lower() != self.type.lower():
            return False
        if self.source_category and not self.source_category.fullmatch(t.source_category or ""):
            return False
        if self.date and t.date != self.date:
            return False
        if self.amount is not None and abs(abs(t.amount) - self.amount) > 0.005:
            return False
        if self.match and not self.match.search(f"{t.description} {t.merchant}".strip()):
            return False
        return True


def load_rules(path: Path) -> list[Rule]:
    data = tomllib.loads(path.read_text())
    rules = []
    for i, r in enumerate(data.get("rule", [])):
        if "category" not in r:
            raise ValueError(f"{path}: rule #{i + 1} has no category")
        if r.get("kind", "spend") not in ("spend", "income", "skip"):
            raise ValueError(f"{path}: rule #{i + 1} has unknown kind {r['kind']!r}")
        acc = r.get("account", ())
        rules.append(Rule(
            category=r["category"],
            kind=r.get("kind", "spend"),
            one_off=bool(r.get("one_off", False)),
            match=re.compile(r["match"], re.I) if "match" in r else None,
            accounts=(acc,) if isinstance(acc, str) else tuple(acc),
            type=r.get("type"),
            source_category=re.compile(r["source_category"], re.I) if "source_category" in r else None,
            date=date.fromisoformat(r["date"]) if "date" in r else None,
            amount=float(r["amount"]) if "amount" in r else None,
            merchant=r.get("merchant", ""),
            note=r.get("note", ""),
            count_in=r.get("count_in", ""),
        ))
    return rules


def categorize(txns: list[Txn], rules: list[Rule]) -> None:
    for t in txns:
        for rule in rules:
            if rule.applies(t):
                t.category, t.kind, t.one_off = rule.category, rule.kind, rule.one_off
                t.note = rule.note
                t.count_in = rule.count_in
                if rule.merchant:
                    t.merchant = rule.merchant
                break
        else:
            # Unmatched money coming in is shown as income so nothing disappears silently.
            t.kind = "income" if t.amount < 0 and t.account in ("checking", "savings") else "spend"
            t.category = "Other money in" if t.kind == "income" else "Uncategorized"
        if not t.merchant:
            t.merchant = display_merchant(t.description)


_NOISE = re.compile(r"^(TST\*|SQ \*|DD \*|SP \*|LSU |EB \*|PY \*)", re.I)


def display_merchant(desc: str) -> str:
    """Turn a raw statement description into a short, groupable name."""
    d = _NOISE.sub("", desc.strip())
    d = re.split(r"\s+DES:|\s{2,}|\s+\d{3}-\d{3,}|\*|#|\s+\d{3,}", d)[0]
    d = re.sub(r"\s+(NEW YORK|BROOKLYN|NY|CA|WA|GA|TX|USA)(\s.*)?$", "", d, flags=re.I)
    return d.strip().title()[:32] or desc[:32]
