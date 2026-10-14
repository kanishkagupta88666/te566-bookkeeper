# Small-Business Accounting & Bookkeeping System

**ENG/TE 566 — Computer Program Final Project**

A bookkeeping program for a small toy-truck manufacturer. You enter business transactions (a sale,
a purchase, a payroll run) and the program keeps the books: every transaction posts a balanced
double-entry journal entry, and the income statement, balance sheet, cash flow statement and
inventory are recomputed from that ledger every time they are shown.

## Contents

- [Project Overview](#project-overview)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [Repository Structure](#repository-structure)
- [Application Architecture](#application-architecture)
- [Installation and Local Setup](#installation-and-local-setup)
- [How to Use the Application](#how-to-use-the-application)
- [ENG/TE 566 Required Demonstration](#engte-566-required-demonstration)
- [Net 30 Accounting](#net-30-accounting)
- [Financial Reports](#financial-reports)
- [Payroll Tax Assumptions](#payroll-tax-assumptions)
- [Running Automated Tests](#running-automated-tests)
- [Streamlit Deployment](#streamlit-deployment)
- [Limitations and Scope](#limitations-and-scope)
- [Course and Author Information](#course-and-author-information)

## Project Overview

This is a Python accounting application with a browser interface. It manages:

- Customer invoices
- Vendor purchase orders
- Inventory (parts, units under construction, finished units)
- Employee payroll
- Financial statements (income statement, balance sheet, cash flow)
- Accounts Receivable and Accounts Payable
- Net 30 payment terms for both sales and purchases
- Transaction histories (invoices, purchase orders, payroll, paid expenses, the full journal)

The user never edits an account balance directly. Each business transaction updates its own
record (an invoice, a purchase order, a payroll event, stock on hand) and posts the matching
entry to a double-entry general ledger in the same database transaction. Reports are derived
from the ledger, so they always agree with the transaction history.

The demo company, its customers, vendors and employee are fictional.

## Key Features

"Required" and "Optional" follow the course's instructional guide. "Extra" marks features added
beyond the guide.

| Module | Functionality | Main accounting impact | Scope |
|---|---|---|---|
| Dashboard | Main menu; cash, receivables, payables, inventory, sales and net income at a glance; outstanding invoices and bills; low-stock alert; recent transactions | Read-only | Required (main menu) |
| Customers | List, add and edit customers; each customer has their own price per unit | None (master data) | Required |
| Vendors | List, add and edit vendors; each vendor supplies one part at a set price | None (master data) | Required |
| Employees | List, add and edit employees: salary, pay frequency, filing status | None (master data) | Required |
| Inventory | Parts in units and dollars, reorder points and low-stock flags, units buildable from parts, units under construction, finished units | Read-only view of the three inventory accounts | Required |
| Inventory — Build Units | Turn parts into finished trucks using the bill of materials | Raw Materials → Work in Process → Finished Goods; no income effect | Optional |
| Sales | Create an invoice for a customer; invoice history; receive a payment | Accounts Receivable and Sales increase; Finished Goods decreases and Cost of Goods Sold increases | Required |
| Purchasing | Create a purchase order; receive it now or later, with a different quantity or bill if needed; PO history; pay a bill | Raw Materials and Accounts Payable increase on receipt | Required |
| Payroll | Pay an employee for one period with federal, state, Social Security and Medicare withholding; payroll history; remit withheld taxes | Payroll expense; cash decreases by net pay; withholding held in Accruals | Required |
| Expenses & Bills | Ten expense accounts, pay a monthly bill, paid-expense history, separate income tax account | Expense increases, cash decreases | Optional |
| Accounting Reports | Income statement, balance sheet, cash flow statement; printable PDF | Read-only, computed from the ledger | Required |
| Transaction History | General ledger journal, trial balance and eleven reconciliation checks | Read-only audit trail | Extra |
| Date & Month-end | Advance the simulated date to settle Net 30 items; settle everything at month-end | Cash moves against Accounts Receivable, Accounts Payable and Accruals | Required (Net 30) |
| Demo Reset | Erase all records and restore the initial conditions | Rebuilds the opening entries | Required (initial conditions) |

## Technology Stack

| Technology | Version | Used for |
|---|---|---|
| Python | 3.10 or newer (developed and tested on 3.11) | Everything |
| Streamlit | 1.65.0 | Browser user interface and navigation |
| SQLite | bundled with Python (`sqlite3`) | Persistent storage |
| ReportLab | 5.0.1 | Printable PDF statements |
| `decimal` (standard library) | — | Money parsing and tax arithmetic; amounts are stored as integer cents |
| pytest | 9.1.1 | Automated tests (development only) |
| Playwright + Pillow | 1.63.0 / 12.3.0 | Browser automation and screenshots for the evidence scripts (development only) |

Running the application needs only Streamlit and ReportLab. No ORM, web framework, cloud
service or API key is used.

## Repository Structure

```text
te566-bookkeeper/
├── bookkeeping_app.py            # application entry point
├── ui.py                         # shared screen helpers
├── README.md
├── requirements.txt              # runtime dependencies
├── requirements-dev.txt          # test and automation dependencies
├── .gitignore
├── .streamlit/
│   └── config.toml
├── bookkeeper/                   # accounting engine (no user-interface code)
│   ├── __init__.py
│   ├── db.py
│   ├── ledger.py
│   ├── money.py
│   ├── payroll_tax.py
│   ├── pdf.py
│   ├── reports.py
│   ├── seed.py
│   └── services.py
├── views/                        # one file per screen
│   ├── dashboard.py
│   ├── statements.py
│   ├── inventory.py
│   ├── general_ledger.py
│   ├── invoices.py
│   ├── purchase_orders.py
│   ├── payroll.py
│   ├── expenses.py
│   ├── employees.py
│   ├── customers.py
│   ├── vendors.py
│   └── admin.py
├── scripts/
│   ├── make_submission.py
│   └── verify_deployment.py
└── tests/
    ├── test_bookkeeper.py
    └── test_hosted_sessions.py
```

Created at runtime and deliberately not in the repository: `data/bookkeeper.db` (the local
database), `submission/` (generated PDF, code ZIP and screenshots) and `.venv/`.

### File and Folder Explanation

| File / Folder | Purpose | Main Responsibility |
|---|---|---|
| `bookkeeping_app.py` | Application entry point | Configures the page, registers the 12 screens in the sidebar navigation, shows the company name and simulated date, and runs the selected screen. Start the program with `streamlit run bookkeeping_app.py`. |
| `ui.py` | Shared user-interface helpers | Opens the database for the current visitor (one local database, or a private one per visitor when hosted), shows success and error messages, renders HTML tables and statements, builds add/edit forms, and issues the one-time tokens that stop a form from posting twice. |
| `bookkeeper/` | Accounting engine | All business rules and accounting. It has no Streamlit code, so it can be tested without a browser. |
| `bookkeeper/db.py` | Database layer | Defines the SQLite schema (accounts, journal, customers, vendors, parts, invoices, purchase orders, payroll events, expenses, builds), opens connections, and provides the all-or-nothing `transaction()` block that rolls back on any error. |
| `bookkeeper/ledger.py` | General ledger | Holds the chart of accounts and `post()`, which accepts a journal entry only if debits equal credits. Also computes account balances, the trial balance and the journal listing. |
| `bookkeeper/services.py` | Business transactions | One function per business event: create invoice, receive payment, create and receive purchase order, pay vendor, pay employee, remit payroll taxes, pay a bill, pay income tax, build units, advance the date, month-end settlement. Each validates its input, updates the operational record and inventory, and posts the journal entry together. Also holds add/edit rules for employees, customers, vendors and parts. |
| `bookkeeper/payroll_tax.py` | Payroll calculations | Tax-year 2026 rate table and `compute_paycheck()`, which splits gross pay into federal, state, Social Security and Medicare withholding and net pay. |
| `bookkeeper/reports.py` | Reporting | Builds the income statement, balance sheet, cash flow statement, inventory report and expense summary from ledger balances, and runs the reconciliation checks between the ledger and the transaction records. |
| `bookkeeper/pdf.py` | Printable reports | Lays out the three statements and the inventory report as a PDF for the "Download printable statements" button. |
| `bookkeeper/seed.py` | Initial conditions | Defines the demo business (company, bill of materials, 8 vendors, 10 customers, 1 employee, 10 expense accounts, opening balances) and `reset_demo()`, which erases everything and rebuilds that starting point. |
| `bookkeeper/money.py` | Money helpers | Converts user input to integer cents with half-up rounding and formats cents as dollars. Keeps floating-point values out of the ledger. |
| `views/` | Screens | One file per screen. Each collects input, calls a function in `bookkeeper/services.py`, and displays results from `bookkeeper/reports.py` or history queries. |
| `views/dashboard.py` | Dashboard | Main menu, key figures, outstanding invoices and bills, low-stock alert, recent transactions. |
| `views/statements.py` | Financial Statements | Income statement and balance sheet side by side, cash flow statement, PDF download, reconciliation status. |
| `views/inventory.py` | Inventory | Parts table with reorder flags, inventory by stage, and the Build Units actions. |
| `views/general_ledger.py` | General Ledger & Audit | Reconciliation checks, trial balance and the complete journal. |
| `views/invoices.py` | Create Invoice / History | Invoice form with live total and stock check, invoice history, receive a customer payment. |
| `views/purchase_orders.py` | Create PO / History | Purchase order form, receipt of open orders, PO history, pay a vendor bill. |
| `views/payroll.py` | Pay Employee / Payroll | Paycheck preview, Pay Employee action, payroll history and totals, remit withheld taxes. |
| `views/expenses.py` | Expenses & Bills | Expense accounts, pay a monthly bill, pay income tax, paid-expense history. |
| `views/employees.py`, `views/customers.py`, `views/vendors.py` | Records | List, add and edit employees, customers and vendors. |
| `views/admin.py` | Date & Reset Demo | Advance the simulated date, month-end settlement, Reset Demo. |
| `scripts/make_submission.py` | Evidence generator | Starts the program, drives it in Google Chrome through the three required transactions, takes screenshots, and assembles the submission PDF and source-code ZIP in `submission/`. |
| `scripts/verify_deployment.py` | Deployment check | Opens a running copy of the program (local or hosted) as two separate visitors, performs the three required transactions, and checks the resulting figures, refresh behaviour, visitor isolation and Reset Demo. |
| `tests/test_bookkeeper.py` | Accounting tests | 23 tests of the engine: opening balances, each transaction type, Net 30 settlement, payroll arithmetic, inventory costing, rollback, duplicate protection and reconciliation. |
| `tests/test_hosted_sessions.py` | Hosted-mode tests | 4 tests that visitors get separate books when hosted, a refresh returns to the same books, malformed workspace ids are rejected, and local mode still uses one persistent database. |
| `requirements.txt` | Runtime dependencies | The two packages needed to run the program. This is the file Streamlit Community Cloud installs. |
| `requirements-dev.txt` | Development dependencies | Adds pytest, Playwright and Pillow for the tests and scripts. |
| `.streamlit/config.toml` | Streamlit settings | Light theme, accent colour, no usage statistics, headless server. |
| `.gitignore` | Repository hygiene | Keeps databases, virtual environments, caches, secrets, generated submission files and course handouts out of the repository. |

## Application Architecture

```text
Streamlit UI          views/*.py, ui.py, bookkeeping_app.py
     │  calls
     ▼
Business logic        bookkeeper/services.py   (validation, invoices, POs, payroll, inventory)
     │  posts balanced entries through
     ▼
Double-entry ledger   bookkeeper/ledger.py     (debits must equal credits)
     │  stored in
     ▼
SQLite database       bookkeeper/db.py         (journal + operational records, one atomic transaction)
     │  read by
     ▼
Financial reports     bookkeeper/reports.py → shown by views/statements.py, printed by bookkeeper/pdf.py
```

A transaction flows like this. The Create Invoice screen calls `services.create_invoice()`. Inside
one database transaction that function checks stock, works out the total and the cost of the
units sold, calls `ledger.post()` with four lines (debit Accounts Receivable, credit Sales, debit
Cost of Goods Sold, credit Finished Goods), reduces finished-goods stock and saves the invoice.
If any step fails, everything is rolled back, so the ledger and the invoice list cannot disagree.

Reports work in the other direction. `reports.income_statement()` and `reports.balance_sheet()`
ask the ledger for the balance of each account and add them into statement lines. No statement
total is stored anywhere.

Screens post transactions only through `bookkeeper/services.py`. For display, they also run
read-only queries for history tables and drop-down lists.

## Installation and Local Setup

Requires Python 3.10 or newer and Git.

**macOS / Linux**

```bash
git clone https://github.com/kanishkagupta88666/te566-bookkeeper.git
cd te566-bookkeeper
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run bookkeeping_app.py
```

**Windows (PowerShell)**

```powershell
git clone https://github.com/kanishkagupta88666/te566-bookkeeper.git
cd te566-bookkeeper
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run bookkeeping_app.py
```

The program opens in the browser at `http://localhost:8501`. The first launch creates
`data/bookkeeper.db` and loads the initial conditions. Data persists between runs.

## How to Use the Application

The sidebar lists every screen, grouped as Main Menu, Reports, Transactions, Records and Setup.
The sidebar also shows the company name and the simulated date.

| Task | Where | Steps |
|---|---|---|
| Initialize or reset the demo business | Date & Reset Demo | Tick "I understand this deletes all transactions", then **Reset Demo**. |
| Create a sale | Create Invoice / History | Choose a customer, enter units, **Create Invoice**. The total and units in stock are shown before posting. |
| Purchase inventory | Create PO / History | Choose a part and vendor, enter a quantity, **Create PO**. Untick "Goods received now" to receive it later with the actual quantity and bill. |
| Pay an employee | Pay Employee / Payroll | Choose the employee, review the paycheck preview, **Pay Employee**. |
| View the Income Statement and Balance Sheet | Financial Statements | Both are shown side by side, with the cash flow statement and a PDF download below. |
| Review transaction history | Each transaction screen; General Ledger & Audit | Invoice, PO, payroll and paid-expense histories sit under their forms. The General Ledger screen lists every journal entry. |
| Settle Net 30 items | Date & Reset Demo | **Advance Date** by a number of days, or **Settle Everything Now**. |

## ENG/TE 566 Required Demonstration

The assignment: start with initial conditions, then make a $50,000 sale, purchase $20,000 of
inventory, and pay an employee for one payroll period, showing the income statement and balance
sheet before and after each. The figures below are asserted by the automated tests.

### Initial Conditions

Set by **Reset Demo**; the simulated date starts at 2026-10-01.

| Item | Amount |
|---|---|
| Owner's cash investment | $200,000.00 |
| Opening inventory contributed by the owner, at cost | $39,300.00 |
| — 60,000 finished trucks at $0.57 | $34,200.00 |
| — starting stock of parts | $5,100.00 |
| Opening net worth | $239,300.00 |

The business needs finished trucks before it can make a sale. They are recorded as a second
owner contribution (debit inventory, credit Owner's Capital) so that cash stays at $200,000.
The $0.57 cost per truck comes from the guide's bill of materials. Also seeded: 10 customers,
8 vendors (one per part), 1 employee at $150,000 per year, and 10 expense accounts budgeted at
$200,000 per year.

### Transaction 1 — Customer Sale ($50,000)

Create Invoice / History → Smith Toy Co. → 20,000 units → **Create Invoice**.

| Effect | Amount |
|---|---|
| 20,000 trucks × $2.50 | $50,000.00 |
| Sales | + $50,000.00 |
| Accounts Receivable | + $50,000.00 |
| Cost of Goods Sold (20,000 × $0.57) | + $11,400.00 |
| Inventory (finished goods) | − $11,400.00 |
| Cash | unchanged |

### Transaction 2 — Inventory Purchase ($20,000)

Create PO / History → Cab — Diecast Cab Castings → quantity 200,000 → **Create PO**.

| Effect | Amount |
|---|---|
| 200,000 cabs × $0.10 | $20,000.00 |
| Inventory (raw materials) | + $20,000.00 |
| Accounts Payable | + $20,000.00 |
| Cash | unchanged |
| Income statement | unchanged |

### Transaction 3 — Employee Payroll (one period)

Pay Employee / Payroll → Jordan Smith → **Pay Employee**. Period: October 2026.

| Effect | Amount |
|---|---|
| Gross salary ($150,000 ÷ 12) | $12,500.00 |
| Federal income tax withheld | $2,061.17 |
| State income tax withheld | $618.75 |
| Social Security | $775.00 |
| Medicare | $181.25 |
| Total withholding (held in Accruals) | $3,636.17 |
| Net payment (cash decreases) | $8,863.83 |

### Result After All Three

| Line | Amount |
|---|---|
| Sales | $50,000.00 |
| Cost of Goods Sold | $11,400.00 |
| Gross Profit | $38,600.00 |
| Total Expenses (payroll) | $12,500.00 |
| **Net Income** | **$26,100.00** |
| Cash | $191,136.17 |
| Accounts Receivable | $50,000.00 |
| Inventory | $47,900.00 |
| **Total Assets** | **$289,036.17** |
| Accounts Payable | $20,000.00 |
| Accruals | $3,636.17 |
| Net Worth ($239,300 + $26,100) | $265,400.00 |
| **Total Liabilities & Net Worth** | **$289,036.17** |

### Why Assets = Liabilities + Equity

Every journal entry has equal debits and credits, and `ledger.post()` rejects one that does not.
An entry therefore changes the two sides of the equation by the same amount: the sale adds
$38,600 to assets (receivable up $50,000, inventory down $11,400) and $38,600 to equity through
net income. Because each entry keeps the equation true, the balance sheet built from all of
them must balance. The General Ledger & Audit screen checks this after every transaction, and
the tests assert it.

## Net 30 Accounting

Both customers and vendors are on Net 30 terms: payment is due 30 days after the invoice or
goods receipt.

- **A sale creates a receivable.** The revenue is earned when the trucks are invoiced, but the
  customer has 30 days to pay. The program records Accounts Receivable, not cash.
- **A purchase creates a payable.** The parts are owned once received, but the vendor's bill is
  not due for 30 days. The program records Accounts Payable, and cash is unchanged.
- **Settlement.** Collecting an invoice debits Cash and credits Accounts Receivable. Paying a
  bill debits Accounts Payable and credits Cash. Neither affects income, which was recognised
  when the sale or purchase happened.
- **Simulated date.** The program has its own calendar, shown in the sidebar. **Advance Date**
  moves it forward and settles each open invoice and bill on its due date, in date order.
  Withheld payroll taxes are remitted on the 15th of the following month. A bill is left open,
  and reported, if cash is insufficient.
- **Month-end rule.** The guide also asks that receivables and bills can be settled at month-end
  even if 30 days have not passed. **Settle Everything Now** does that.
- Individual invoices and bills can also be settled by hand from their history screens.

In the required demonstration, advancing 30 days to 2026-10-31 collects the $50,000 and pays
the $20,000, taking cash from $191,136.17 to $221,136.17 with net income unchanged.

## Financial Reports

All three statements are calculated on request from ledger balances in `bookkeeper/reports.py`.

| Report | Contents | How it is calculated |
|---|---|---|
| Income Statement | Sales, COGS, Gross Profit; Payroll, Payroll Withholding, Bills, Total Expenses; Other Income, Operating Income, Income Taxes, Net Income | Each line is the balance of one revenue or expense account (Bills sums the ten expense accounts). Subtotals are computed from those lines. Cumulative from the start date. |
| Balance Sheet | Cash, Accounts Receivable, Inventory, fixed assets, Total Assets; Accounts Payable, Notes Payable, Accruals, Mortgage, Total Liabilities; Owner's Capital, Retained Earnings, Net Worth | Each line is an asset, liability or equity account balance. Inventory sums raw materials, work in process and finished goods. Retained Earnings is the income statement's net income. |
| Cash Flow Statement | Operating activities (customers, vendors, employees, payroll taxes, expenses, income taxes), financing activities (owner's investment), ending cash | Direct method: every movement of the Cash account, grouped by the type of transaction that caused it. Ending cash must equal Cash on the balance sheet. |

The Inventory screen reports quantities and values per part, reorder flags, cost per unit,
buildable units, and units in process and finished. Inventory is valued at weighted-average cost.

## Payroll Tax Assumptions

Payroll withholding is a simplified estimate for teaching purposes. It is not a payroll service
and should not be used to pay real employees.

| Tax | Method used |
|---|---|
| Federal income tax | Annual salary less the standard deduction, taxed through the single or married bracket table, divided by the number of pay periods. Bonuses are withheld at a flat 22%. |
| State income tax | Illinois flat rate of 4.95% on gross pay, with no exemption allowance. |
| Social Security | 6.2% of gross pay up to the annual wage base. |
| Medicare | 1.45% of gross pay. |

- All rates, brackets, the standard deduction and the wage base are in one table in
  `bookkeeper/payroll_tax.py`, labelled tax year 2026.
- **These figures have not been checked against official IRS or Illinois publications.** Verify
  them before relying on any calculated amount.
- The federal calculation approximates, and does not reproduce, the IRS Publication 15-T
  withholding method. Form W-4 adjustments and dependents are not applied.
- Employer-side payroll taxes (the matching Social Security and Medicare share, unemployment
  taxes) are not modelled. Gross salary equals net pay plus employee withholding, as in the
  course sample.

## Running Automated Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests
```

Expected result: **27 passed**.

- `tests/test_bookkeeper.py` (23 tests) — accounting engine.
- `tests/test_hosted_sessions.py` (4 tests) — hosted-mode workspaces.

Neither test file needs a browser. The two scripts in `scripts/` do: they use Playwright with
an installed copy of Google Chrome.

```bash
# check a running copy (local or hosted) end to end, as two separate visitors
python scripts/verify_deployment.py http://localhost:8501

# regenerate the submission PDF and code ZIP (overwrites the files in submission/)
python scripts/make_submission.py
```

`verify_deployment.py` uses Reset Demo. Against a local copy it will erase the local database
unless the program was started with `BOOKKEEPER_ISOLATE_SESSIONS=1`.

## Streamlit Deployment

The program can be hosted on Streamlit Community Cloud with no code changes and no secrets.

| Setting | Value |
|---|---|
| Repository | `kanishkagupta88666/te566-bookkeeper` |
| Branch | `main` |
| Main file path | `bookkeeping_app.py` |
| Dependencies | `requirements.txt` (installed automatically) |
| Python version | 3.11 recommended (Advanced settings); 3.10 or newer required |
| Secrets | None |

Steps: sign in at share.streamlit.io with GitHub, choose **Create app**, and enter the settings
above. An app that was deployed while the entry point was still named `app.py` must be pointed
at `bookkeeping_app.py`; if the main file cannot be edited in the app's settings, delete the app
and deploy it again.

**Per-visitor workspaces.** A hosted app is one server shared by everyone who opens the link.
To stop visitors from changing or resetting each other's books, each browser session gets its
own SQLite database when hosted. The workspace id is kept in the URL (`?s=...`), so refreshing
the page returns to the same books. This turns on automatically on Community Cloud;
`BOOKKEEPER_ISOLATE_SESSIONS=1` or `0` forces it on or off elsewhere.

**Hosted data is temporary.** Community Cloud has no permanent disk. Workspaces are lost when
the app restarts or goes to sleep, and are deleted after 24 hours. Run the program locally for
storage that persists.

After deploying, check the public URL with:

```bash
python scripts/verify_deployment.py https://<your-app>.streamlit.app
```

## Limitations and Scope

- **Academic demonstration.** Built for a course project. It makes no claim of accounting, audit
  or tax compliance and is not intended for real business records.
- **Payroll taxes are simplified estimates**, as described above, and unverified against official
  sources.
- **Hosted workspaces are temporary**; only a local run persists data.
- **No user accounts or access control.** Anyone who can open the program can post transactions
  and reset the data. A hosted workspace is private only in that its URL id is hard to guess.
- **One product and one part per vendor.** The model is a single finished product built from a
  fixed bill of materials. Prices and costs are whole cents.
- **No period closing.** The income statement is cumulative from the start date; there are no
  monthly or yearly closing entries.
- **No corrections.** Posted transactions cannot be edited, voided or reversed. Reset Demo is the
  only way to undo.
- **Limited scope of accounts.** No sales tax, discounts, partial payments, returns, depreciation,
  loans or interest. Fixed-asset and long-term debt lines appear on the balance sheet but no
  screen posts to them.
- **Single currency, single company.**

## Course and Author Information

| | |
|---|---|
| Course | ENG/TE 566 |
| Project | Computer Program Final Project |
| Author | Kanishka Gupta |
