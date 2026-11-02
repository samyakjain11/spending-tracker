"""Read statements into a common list of transactions.

Sign convention for every parser: ``amount`` is positive when money leaves you
(a purchase, a bill, a transfer out) and negative when money comes in (a
refund, a paycheck, a card payment credited to the card).

Supported inputs:
  * Apple Card CSV export (from Wallet, monthly or a longer range)
  * Chase credit card PDF statements
  * Bank of America combined checking + savings PDF statements ("eStmt")
"""
from __future__ import annotations

import csv
import io
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path


@dataclass
class Txn:
    date: date
    amount: float
    description: str
    account: str  # apple | chase | checking | savings
    merchant: str = ""
    source_category: str = ""
    source_type: str = ""
    # Filled in by the rules engine.
    category: str = ""
    kind: str = ""  # spend | income | skip
    one_off: bool = False
    note: str = ""
    count_in: str = ""  # YYYY-MM to report it in a different month


@dataclass
class Statement:
    path: Path
    account_kinds: list[str]
    start: date
    end: date
    txns: list[Txn] = field(default_factory=list)
    # Expected net change per account from the statement's own summary, if any.
    expected_net: dict[str, float] = field(default_factory=dict)
    # Closing balance per account, when the statement prints one.
    end_balance: dict[str, float] = field(default_factory=dict)


def _money(s: str) -> float:
    return float(s.replace("$", "").replace(",", ""))


def pdf_text(path: Path) -> str:
    return subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        check=True, capture_output=True, text=True,
    ).stdout


# --------------------------------------------------------------------------- Apple
APPLE_HEADER = "Transaction Date,Clearing Date,Description,Merchant,Category,Type,Amount (USD)"


def looks_like_apple_csv(head: str) -> bool:
    return head.startswith(APPLE_HEADER)


def parse_apple_csv(path: Path, text: str) -> Statement:
    rows = list(csv.DictReader(io.StringIO(text)))
    txns = []
    for r in rows:
        d = datetime.strptime(r["Transaction Date"], "%m/%d/%Y").date()
        txns.append(Txn(
            date=d,
            amount=_money(r["Amount (USD)"]),
            description=r["Description"].strip(),
            merchant=r["Merchant"].strip(),
            source_category=r["Category"].strip(),
            source_type=r["Type"].strip(),
            account="apple",
        ))
    dates = [t.date for t in txns]
    return Statement(path, ["apple"], min(dates), max(dates), txns)


# --------------------------------------------------------------------------- Chase
CHASE_PERIOD = re.compile(r"Opening/Closing Date\s+(\d\d/\d\d/\d\d)\s*-\s*(\d\d/\d\d/\d\d)")
CHASE_LINE = re.compile(r"^\s{0,6}(\d\d/\d\d)\s{2,}(\S.*?)\s{2,}(-?[\d,]*\.\d\d)\s*$")


def looks_like_chase(text: str) -> bool:
    return "chase.com" in text.lower() and bool(CHASE_PERIOD.search(text))


def parse_chase_pdf(path: Path, text: str) -> Statement:
    m = CHASE_PERIOD.search(text)
    start = datetime.strptime(m.group(1), "%m/%d/%y").date()
    end = datetime.strptime(m.group(2), "%m/%d/%y").date()
    prev = re.search(r"Previous Balance\s+\$?(-?[\d,]+\.\d\d)", text)
    new = re.search(r"New Balance\s+\$?(-?[\d,]+\.\d\d)", text)

    txns = []
    in_activity = False
    for line in text.splitlines():
        if "ACCOUNT ACTIVITY" in line:
            in_activity = True
            continue
        if in_activity and ("Totals Year-to-Date" in line or "INTEREST CHARGES" in line):
            in_activity = False
            continue
        if not in_activity:
            continue
        lm = CHASE_LINE.match(line)
        if not lm:
            continue
        mm, dd = (int(x) for x in lm.group(1).split("/"))
        # Statements only print month/day. Pick the year that lands inside the period.
        year = end.year if mm <= end.month else start.year
        d = date(year, mm, dd)
        txns.append(Txn(date=d, amount=_money(lm.group(3)),
                        description=re.sub(r"\s+", " ", lm.group(2)).strip(),
                        account="chase"))
    st = Statement(path, ["chase"], start, end, txns)
    if prev and new:
        st.expected_net["chase"] = round(_money(new.group(1)) - _money(prev.group(1)), 2)
    return st


# --------------------------------------------------------------------------- Bank of America
BOFA_PERIOD = re.compile(r"for ([A-Z][a-z]+ \d{1,2}, \d{4}) to ([A-Z][a-z]+ \d{1,2}, \d{4})")
BOFA_LINE = re.compile(r"^(\d\d/\d\d/\d\d)\s+(\S.*?)\s{2,}(-?[\d,]*\.\d\d)\s*$")
BOFA_ACCT = re.compile(r"Account (?:number:|#)\s*([\d ]{8,})")


def looks_like_bofa(text: str) -> bool:
    return "bankofamerica.com" in text.lower() and bool(BOFA_PERIOD.search(text))


def parse_bofa_pdf(path: Path, text: str) -> Statement:
    m = BOFA_PERIOD.search(text)
    start = datetime.strptime(m.group(1), "%B %d, %Y").date()
    end = datetime.strptime(m.group(2), "%B %d, %Y").date()

    kinds: dict[str, str] = {}   # account number -> checking | savings
    current = None               # account number for the page we're on
    pending_number = None
    txns = []
    begin_bal: dict[str, float] = {}
    end_bal: dict[str, float] = {}
    in_txn_table = False
    for line in text.splitlines():
        am = BOFA_ACCT.search(line)
        if am:
            current = am.group(1).replace(" ", "")
            pending_number = current
            continue
        if pending_number and line.strip().startswith("Your "):
            kinds[pending_number] = "savings" if "Savings" in line else "checking"
            pending_number = None
            continue
        kind = kinds.get(current or "")
        if kind:
            bm = re.match(r"\s*Beginning balance on .*?\$?(-?[\d,]+\.\d\d)\s*$", line)
            if bm:
                begin_bal[kind] = _money(bm.group(1))
            em = re.match(r"\s*Ending balance on .*?\$?(-?[\d,]+\.\d\d)\s*$", line)
            if em:
                end_bal[kind] = _money(em.group(1))
        if re.match(r"\s*Date\s+(Transaction )?[Dd]escription", line):
            in_txn_table = True
            continue
        if re.match(r"\s*(Total |Daily ledger|continued on the next page)", line):
            in_txn_table = False
            continue
        if not (in_txn_table and kind):
            continue
        lm = BOFA_LINE.match(line)
        if lm:
            d = datetime.strptime(lm.group(1), "%m/%d/%y").date()
            txns.append(Txn(date=d, amount=-_money(lm.group(3)),
                            description=re.sub(r"\s+", " ", lm.group(2)).strip(),
                            account=kind))
    st = Statement(path, sorted(set(kinds.values())), start, end, txns, end_balance=dict(end_bal))
    for k in begin_bal:
        if k in end_bal:
            # Money out is positive in our convention, so the balance change is -sum.
            st.expected_net[k] = round(begin_bal[k] - end_bal[k], 2)
    return st


# --------------------------------------------------------------------------- dispatch
def read_statement(path: Path) -> Statement | None:
    raw = path.read_bytes()
    if raw[:5] == b"%PDF-":
        text = pdf_text(path)
        if looks_like_chase(text):
            return parse_chase_pdf(path, text)
        if looks_like_bofa(text):
            return parse_bofa_pdf(path, text)
        return None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    if looks_like_apple_csv(text):
        return parse_apple_csv(path, text)
    return None
