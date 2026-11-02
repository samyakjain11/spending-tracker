# Spending tracker

Turns a month's card and bank statements into a one-page report: what came in,
rent, everyday spending by category, one-offs, and how much was saved, each
compared with the months before.

**No personal data lives in this repo.** Statements, personal rules and the
generated reports stay outside it (see `.gitignore`). Tests use made-up data.

## Monthly routine

Around the **22nd of each month**, once all three statements for the previous
month have closed, upload:

| Account | What to upload | Closes |
|---|---|---|
| Apple Card | Wallet → Apple Card → Card Balance → last month's statement → **Export Transactions** (CSV) | last day of the month |
| Chase United Club | The PDF statement that closed on the **14th** of this month | 14th |
| Bank of America | The checking + savings eStmt PDF that closed around the **20th** | ~20th |

For example, the October report needs Apple's October CSV, the Chase statement
for Oct 15 to Nov 14 and the BofA statement ending around Nov 20.

Then run:

```sh
python -m spending --inputs path/to/statements --rules path/to/personal-rules.toml --out path/to/reports
```

It picks the latest month that every account fully covers (or pass
`--month 2026-10`) and writes:

- `report-YYYY-MM.html`: the visual report
- `summary.json`: month-by-month totals, no raw transactions
- `exports/monthly.csv`, `exports/category_by_month.csv`, `exports/balances.csv`: aggregate tables for other charts

Re-uploading a statement, or a full-year CSV next to a monthly one, is fine:
duplicates are dropped. Each PDF is checked against its own opening and closing
balance, and the run warns if any lines were missed.

## How things are counted

- **Bank of America checking is the hub.** It receives pay and pays the cards,
  so card payments from checking are never counted (the card purchases are).
- **Investing and transfers between your own accounts are ignored** in both
  directions (Wealthfront, Robinhood, checking ↔ savings).
- **Rent is counted from checking only.**
- **One-offs** (flights, a move, other rules you mark `one_off = true`) are
  shown separately and kept out of everyday spending and the savings figure, so
  months compare fairly.
- **Returns** count against the same category in the month they arrive, unless
  a rule drops both sides.
- **Saved** = money in − rent − everyday spending.
- A month is **complete** only when every account listed in `[settings]
  accounts` covers all of it; partial months are labelled.

## Rules

`rules/default.toml` has generic merchant patterns (Chipotle → Fast food, Uber
trips → Rideshare, airlines → Flights, and so on). A personal rules file is
checked first and holds anything specific to you: landlord, cards you don't
upload, one-off purchases by date and amount, returns. See
`examples/personal-rules.example.toml` for the format.

Anything that matches no rule lands in **"Not sure what these are"** at the
bottom of the report. Add a rule for it and the next run sorts it.

## Development

Needs Python 3.11+ and `pdftotext` (poppler-utils). No other dependencies.

```sh
python -m unittest discover -s tests -t .
```
