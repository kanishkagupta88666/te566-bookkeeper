# ENG/TE 566 Computer Program — Small-Business Bookkeeper

A bookkeeping program for a toy-truck manufacturer. Every business transaction posts a balanced
double-entry journal entry, and the income statement, balance sheet, cash flow statement and
inventory are always computed from that ledger.

Python 3.11 · Streamlit (screens) · SQLite (persistent storage) · ReportLab (printable PDFs)

## Run it

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

The browser opens on the main menu. Data is stored in `data/bookkeeper.db` and survives restarts.
The first launch seeds the initial conditions; **Date & Reset Demo → Reset Demo** restores them at any time.

## The three assignment transactions

| # | Assignment | Screen | Entry |
|---|---|---|---|
| 1 | Sale for $50,000 | Create Invoice / History | Smith Toy Co., 20,000 units (× $2.50) |
| 2 | Purchase $20,000 of inventory | Create PO / History | Cab — Diecast Cab Castings, quantity 200,000 (× $0.10) |
| 3 | Pay an employee, 1 period | Pay Employee / Payroll | Jordan Smith → Pay Employee |

View the result under **Financial Statements**. To see Net 30 settle, use **Date & Reset Demo → Advance Date** (30 days).

To regenerate the submission PDF (drives the app in Google Chrome, takes the screenshots, builds the PDF and code zip):

```bash
.venv/bin/python scripts/make_submission.py     # writes submission/
```

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

23 accounting tests (`tests/test_bookkeeper.py`) cover the three assignment transactions, Net 30 settlement, payroll tax math, inventory
costing, rollback on failure, duplicate-submission protection, and ledger/subledger reconciliation.
4 more (`tests/test_hosted_sessions.py`) cover the hosted demo's per-visitor workspaces.

## Live demo (Streamlit Community Cloud)

The same code runs hosted. Two things differ from a local run:

- **Each visitor gets private books.** A hosted app is one server shared by everyone who opens the
  link, so on Community Cloud every browser session works in its own SQLite file. One visitor's
  transactions or Reset Demo never affect another's. The workspace id is kept in the URL (`?s=...`),
  so refreshing the page keeps your books.
- **Hosted data is temporary.** Community Cloud has no permanent disk: workspaces disappear when the
  app restarts or goes to sleep, and are deleted after 24 hours. Run the program locally for
  storage that persists.

Isolation switches on automatically on Community Cloud. Set `BOOKKEEPER_ISOLATE_SESSIONS=1` (or `0`)
to force it on or off elsewhere.

Deploy: push this repository to GitHub, then at share.streamlit.io choose **Create app**, pick the
repository, branch `main`, main file `app.py`, and Python 3.11 under Advanced settings. No secrets
are needed. Check a deployment with:

```bash
.venv/bin/python scripts/verify_deployment.py https://<your-app>.streamlit.app
```

## Initial conditions

- Start date 2026-10-01; owner invests **$200,000** cash.
- Owner also contributes opening inventory at cost (**$39,300**): 60,000 finished trucks ($34,200) and
  a starting stock of parts ($5,100). It is posted as a balanced entry to Owner's Capital, so cash
  stays at $200,000 and opening net worth is $239,300.
- 10 customers, 8 vendors (one per part), 1 employee at $150,000/yr paid monthly, 10 expense accounts
  budgeted at $200,000/yr, and a separate Income Taxes account. No long-term assets or debt.
- The $1,000,000 annual sales and $200,000 annual expenses in the guide are planning figures; nothing
  is posted until a transaction is entered.

## Accounting rules

| Event | Debit | Credit |
|---|---|---|
| Invoice (sale, Net 30) | Accounts Receivable; COGS | Sales; Finished Goods |
| Customer pays | Cash | Accounts Receivable |
| PO received (Net 30) | Raw Materials | Accounts Payable |
| Vendor paid | Accounts Payable | Cash |
| Payroll | Payroll (net pay); Payroll Withholding | Cash; Accruals |
| Withholding remitted | Accruals | Cash |
| Bill paid | Expense account | Cash |
| Income tax paid | Income Taxes | Cash |
| Build units | Work in Process → Finished Goods | Raw Materials → Work in Process |

- **Inventory** is carried at weighted-average cost in units and dollars. Buying parts is not an
  expense; cost reaches the income statement as COGS when trucks are sold. A truck costs $0.57 from
  the guide's bill of materials.
- **Purchase orders** record quantity ordered separately from quantity received and amount billed;
  an order can be received later. Nothing is posted until goods arrive.
- **Net 30**: advancing the date collects invoices and pays vendor bills on their due dates. The
  guide's month-end rule (settle everything now) is a separate button.
- **Payroll** withholds federal, state, Social Security and Medicare (2026 rates, in
  `bookkeeper/payroll_tax.py`). Withheld tax sits in Accruals until remitted on the 15th of the next month.

## Simplifications

- Federal withholding is an annualized-bracket estimate (standard deduction, 2026 brackets), not the
  full IRS Pub. 15-T worksheet. State tax is the Illinois flat 4.95% on gross pay.
- Employer-side payroll taxes (the matching FICA share) are not modelled, matching the course sample.
- One finished product; each vendor supplies one part; prices are whole cents.
- The income statement is cumulative from the start date (no period closing).
- Only the last four digits of an SSN are stored.

## Layout

```
app.py                 Streamlit entry point and navigation
ui.py                  shared screen helpers
views/                 one file per screen
bookkeeper/            engine, no UI code
  db.py                schema, connection, atomic transactions
  ledger.py            chart of accounts, journal posting, balances
  services.py          invoices, POs, payroll, expenses, builds, Net 30 settlement
  payroll_tax.py       2026 withholding rates and paycheck math
  reports.py           statements, inventory report, reconciliation checks
  pdf.py               printable statements
  seed.py              initial conditions / reset
tests/                 pytest suite
scripts/make_submission.py   end-to-end demo → screenshots → PDF
scripts/verify_deployment.py browser check of a running deployment
```
