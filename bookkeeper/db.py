"""SQLite persistence: connection handling, schema, atomic transactions."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "bookkeeper.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    code   TEXT PRIMARY KEY,
    name   TEXT NOT NULL,
    type   TEXT NOT NULL CHECK (type IN ('asset','liability','equity','revenue','expense'))
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date      TEXT NOT NULL,
    description     TEXT NOT NULL,
    txn_type        TEXT NOT NULL,
    reference       TEXT,
    idempotency_key TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS journal_lines (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id     INTEGER NOT NULL REFERENCES journal_entries(id),
    account_code TEXT NOT NULL REFERENCES accounts(code),
    debit_cents  INTEGER NOT NULL DEFAULT 0 CHECK (debit_cents >= 0),
    credit_cents INTEGER NOT NULL DEFAULT 0 CHECK (credit_cents >= 0),
    CHECK ((debit_cents = 0) <> (credit_cents = 0))
);
CREATE INDEX IF NOT EXISTS idx_lines_account ON journal_lines(account_code);

CREATE TABLE IF NOT EXISTS employees (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    first_name          TEXT NOT NULL,
    last_name           TEXT NOT NULL,
    address1            TEXT NOT NULL DEFAULT '',
    address2            TEXT NOT NULL DEFAULT '',
    city                TEXT NOT NULL DEFAULT '',
    state               TEXT NOT NULL DEFAULT '',
    zip                 TEXT NOT NULL DEFAULT '',
    ssn_last4           TEXT NOT NULL DEFAULT '',
    filing_status       TEXT NOT NULL DEFAULT 'single',
    dependents          INTEGER NOT NULL DEFAULT 0,
    annual_salary_cents INTEGER NOT NULL CHECK (annual_salary_cents > 0),
    pay_periods         INTEGER NOT NULL DEFAULT 12 CHECK (pay_periods > 0),
    active              INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS customers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company     TEXT NOT NULL UNIQUE,
    first_name  TEXT NOT NULL DEFAULT '',
    last_name   TEXT NOT NULL DEFAULT '',
    address1    TEXT NOT NULL DEFAULT '',
    address2    TEXT NOT NULL DEFAULT '',
    city        TEXT NOT NULL DEFAULT '',
    state       TEXT NOT NULL DEFAULT '',
    zip         TEXT NOT NULL DEFAULT '',
    price_cents INTEGER NOT NULL CHECK (price_cents > 0)
);

CREATE TABLE IF NOT EXISTS parts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    qty_per_unit  INTEGER NOT NULL DEFAULT 0 CHECK (qty_per_unit >= 0),
    qty_on_hand   INTEGER NOT NULL DEFAULT 0 CHECK (qty_on_hand >= 0),
    value_cents   INTEGER NOT NULL DEFAULT 0 CHECK (value_cents >= 0),
    reorder_point INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS vendors (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company     TEXT NOT NULL UNIQUE,
    part_id     INTEGER NOT NULL REFERENCES parts(id),
    price_cents INTEGER NOT NULL CHECK (price_cents > 0),
    address1    TEXT NOT NULL DEFAULT '',
    address2    TEXT NOT NULL DEFAULT '',
    city        TEXT NOT NULL DEFAULT '',
    state       TEXT NOT NULL DEFAULT '',
    zip         TEXT NOT NULL DEFAULT ''
);

-- One row per stage of the single finished product: 'wip' and 'finished'.
CREATE TABLE IF NOT EXISTS product_stock (
    stage       TEXT PRIMARY KEY CHECK (stage IN ('wip','finished')),
    qty         INTEGER NOT NULL DEFAULT 0 CHECK (qty >= 0),
    value_cents INTEGER NOT NULL DEFAULT 0 CHECK (value_cents >= 0)
);

CREATE TABLE IF NOT EXISTS invoices (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    number           TEXT NOT NULL UNIQUE,
    invoice_date     TEXT NOT NULL,
    due_date         TEXT NOT NULL,
    customer_id      INTEGER NOT NULL REFERENCES customers(id),
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL,
    total_cents      INTEGER NOT NULL,
    cogs_cents       INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','PAID')),
    paid_date        TEXT
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    number           TEXT NOT NULL UNIQUE,
    po_date          TEXT NOT NULL,
    vendor_id        INTEGER NOT NULL REFERENCES vendors(id),
    part_id          INTEGER NOT NULL REFERENCES parts(id),
    qty_ordered      INTEGER NOT NULL CHECK (qty_ordered > 0),
    unit_price_cents INTEGER NOT NULL,
    qty_received     INTEGER NOT NULL DEFAULT 0,
    billed_cents     INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'ORDERED' CHECK (status IN ('ORDERED','RECEIVED','PAID')),
    received_date    TEXT,
    due_date         TEXT,
    paid_date        TEXT
);

CREATE TABLE IF NOT EXISTS payroll_events (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    pay_date          TEXT NOT NULL,
    period            TEXT NOT NULL,
    employee_id       INTEGER NOT NULL REFERENCES employees(id),
    salary_cents      INTEGER NOT NULL,
    bonus_cents       INTEGER NOT NULL DEFAULT 0,
    federal_cents     INTEGER NOT NULL,
    state_cents       INTEGER NOT NULL,
    social_sec_cents  INTEGER NOT NULL,
    medicare_cents    INTEGER NOT NULL,
    withholding_cents INTEGER NOT NULL,
    net_cents         INTEGER NOT NULL,
    remitted_date     TEXT,
    UNIQUE (employee_id, period)
);

CREATE TABLE IF NOT EXISTS expense_accounts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL UNIQUE,
    account_code        TEXT NOT NULL REFERENCES accounts(code),
    annual_budget_cents INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS expense_payments (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    pay_date           TEXT NOT NULL,
    expense_account_id INTEGER REFERENCES expense_accounts(id),
    description        TEXT NOT NULL,
    amount_cents       INTEGER NOT NULL CHECK (amount_cents > 0)
);

CREATE TABLE IF NOT EXISTS build_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    build_date TEXT NOT NULL,
    action     TEXT NOT NULL CHECK (action IN ('START','COMPLETE')),
    units      INTEGER NOT NULL CHECK (units > 0),
    cost_cents INTEGER NOT NULL
);
"""

TABLES = [
    "journal_lines", "journal_entries", "build_events", "expense_payments", "expense_accounts",
    "payroll_events", "purchase_orders", "invoices", "product_stock", "vendors", "parts",
    "customers", "employees", "accounts", "settings",
]


def db_path() -> Path:
    return Path(os.environ.get("BOOKKEEPER_DB", DEFAULT_DB))


def connect(path=None) -> sqlite3.Connection:
    """Open a connection in autocommit mode; writes go through `transaction()`."""
    target = str(path) if path is not None else str(db_path())
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, isolation_level=None, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    """All-or-nothing unit of work. Any exception rolls back every statement inside."""
    if conn.in_transaction:  # nested call: join the outer transaction
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def get_setting(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
