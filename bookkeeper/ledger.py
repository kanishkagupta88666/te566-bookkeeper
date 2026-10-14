"""Double-entry general ledger.

Every business event becomes one balanced journal entry. Financial statements
are derived exclusively from journal lines — no report total is stored anywhere.
"""
from . import db

# Chart of accounts ---------------------------------------------------------
CASH = "1000"
AR = "1100"
RAW_MATERIALS = "1200"
WIP = "1210"
FINISHED_GOODS = "1220"
LAND_BUILDINGS = "1500"
EQUIPMENT = "1510"
FURNITURE = "1520"
AP = "2000"
NOTES_PAYABLE = "2100"
ACCRUALS = "2200"
MORTGAGE = "2500"
OWNER_CAPITAL = "3000"
SALES = "4000"
OTHER_INCOME = "4900"
COGS = "5000"
PAYROLL = "6000"
PAYROLL_WITHHOLDING = "6010"
INCOME_TAX = "7000"

CHART = [
    (CASH, "Cash", "asset"),
    (AR, "Accounts Receivable", "asset"),
    (RAW_MATERIALS, "Inventory - Raw Materials", "asset"),
    (WIP, "Inventory - Work in Process", "asset"),
    (FINISHED_GOODS, "Inventory - Finished Goods", "asset"),
    (LAND_BUILDINGS, "Land/Buildings", "asset"),
    (EQUIPMENT, "Equipment", "asset"),
    (FURNITURE, "Furniture and Fixtures", "asset"),
    (AP, "Accounts Payable", "liability"),
    (NOTES_PAYABLE, "Notes Payable", "liability"),
    (ACCRUALS, "Accruals (Payroll Taxes Withheld)", "liability"),
    (MORTGAGE, "Mortgage", "liability"),
    (OWNER_CAPITAL, "Owner's Capital", "equity"),
    (SALES, "Sales", "revenue"),
    (OTHER_INCOME, "Other Income", "revenue"),
    (COGS, "Cost of Goods Sold", "expense"),
    (PAYROLL, "Payroll (Net Pay)", "expense"),
    (PAYROLL_WITHHOLDING, "Payroll Withholding", "expense"),
    (INCOME_TAX, "Income Taxes", "expense"),
]

DEBIT_NORMAL = {"asset", "expense"}


class LedgerError(ValueError):
    """Raised when an entry would violate double-entry rules."""


class DuplicatePosting(LedgerError):
    """Raised when the same form submission is posted twice."""


def post(conn, entry_date, description, txn_type, lines, reference=None, idempotency_key=None) -> int:
    """Post one balanced journal entry.

    `lines` is a list of (account_code, debit_cents, credit_cents). Zero-amount
    lines are dropped; the remaining debits must equal the remaining credits.
    """
    clean = [(code, int(dr), int(cr)) for code, dr, cr in lines if dr or cr]
    if not clean:
        raise LedgerError("Journal entry has no amounts.")
    for code, dr, cr in clean:
        if dr < 0 or cr < 0 or (dr and cr):
            raise LedgerError(f"Invalid line for account {code}.")
    debits = sum(dr for _, dr, _ in clean)
    credits = sum(cr for _, _, cr in clean)
    if debits != credits:
        raise LedgerError(f"Entry does not balance: debits {debits} != credits {credits}.")

    with db.transaction(conn):
        if idempotency_key is not None:
            dup = conn.execute(
                "SELECT 1 FROM journal_entries WHERE idempotency_key = ?", (idempotency_key,)
            ).fetchone()
            if dup:
                raise DuplicatePosting("This transaction was already posted.")
        cur = conn.execute(
            "INSERT INTO journal_entries(entry_date, description, txn_type, reference, idempotency_key) "
            "VALUES (?, ?, ?, ?, ?)",
            (str(entry_date), description, txn_type, reference, idempotency_key),
        )
        entry_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO journal_lines(entry_id, account_code, debit_cents, credit_cents) VALUES (?, ?, ?, ?)",
            [(entry_id, code, dr, cr) for code, dr, cr in clean],
        )
    return entry_id


def balance(conn, code: str) -> int:
    """Balance of one account in cents, signed to its normal side."""
    row = conn.execute(
        "SELECT a.type, COALESCE(SUM(l.debit_cents), 0) AS dr, COALESCE(SUM(l.credit_cents), 0) AS cr "
        "FROM accounts a LEFT JOIN journal_lines l ON l.account_code = a.code WHERE a.code = ?",
        (code,),
    ).fetchone()
    if row is None or row["type"] is None:
        raise LedgerError(f"Unknown account {code}.")
    return row["dr"] - row["cr"] if row["type"] in DEBIT_NORMAL else row["cr"] - row["dr"]


def balances(conn) -> dict:
    """{code: balance_cents} for every account, signed to its normal side."""
    rows = conn.execute(
        "SELECT a.code, a.type, COALESCE(SUM(l.debit_cents), 0) AS dr, COALESCE(SUM(l.credit_cents), 0) AS cr "
        "FROM accounts a LEFT JOIN journal_lines l ON l.account_code = a.code GROUP BY a.code"
    ).fetchall()
    return {
        r["code"]: (r["dr"] - r["cr"] if r["type"] in DEBIT_NORMAL else r["cr"] - r["dr"]) for r in rows
    }


def trial_balance(conn) -> list:
    """Rows of (code, name, type, debit_cents, credit_cents) for accounts with activity."""
    rows = conn.execute(
        "SELECT a.code, a.name, a.type, COALESCE(SUM(l.debit_cents), 0) AS dr, "
        "COALESCE(SUM(l.credit_cents), 0) AS cr "
        "FROM accounts a LEFT JOIN journal_lines l ON l.account_code = a.code "
        "GROUP BY a.code ORDER BY a.code"
    ).fetchall()
    out = []
    for r in rows:
        net = r["dr"] - r["cr"]
        if net:
            out.append((r["code"], r["name"], r["type"], max(net, 0), max(-net, 0)))
    return out


def journal(conn, limit=None) -> list:
    """Journal lines, newest entry first."""
    sql = (
        "SELECT e.id, e.entry_date, e.txn_type, e.reference, e.description, "
        "l.account_code, a.name AS account_name, l.debit_cents, l.credit_cents "
        "FROM journal_entries e JOIN journal_lines l ON l.entry_id = e.id "
        "JOIN accounts a ON a.code = l.account_code "
    )
    if limit:
        sql += f"WHERE e.id IN (SELECT id FROM journal_entries ORDER BY id DESC LIMIT {int(limit)}) "
    sql += "ORDER BY e.id DESC, l.id"
    return conn.execute(sql).fetchall()
