"""Business transactions.

Each function validates its input, updates the operational records (invoice,
purchase order, payroll event, inventory) and posts the matching journal entry
inside a single database transaction, so the subledgers and the general ledger
can never drift apart.
"""
from datetime import date, timedelta

from . import db, ledger, payroll_tax
from .money import fmt, round_cents
from decimal import Decimal

TERMS_DAYS = 30


class BusinessError(ValueError):
    """A transaction was rejected by a business rule; nothing was posted."""


# --- simulation clock --------------------------------------------------------
def today(conn) -> date:
    return date.fromisoformat(db.get_setting(conn, "current_date"))


def _next_number(conn, table: str, prefix: str) -> str:
    row = conn.execute(f"SELECT COALESCE(MAX(id), 0) + 1 AS n FROM {table}").fetchone()
    return f"{prefix}-{row['n']:04d}"


def _require_cash(conn, amount_cents: int, purpose: str) -> None:
    cash = ledger.balance(conn, ledger.CASH)
    if amount_cents > cash:
        raise BusinessError(f"Insufficient cash for {purpose}: need {fmt(amount_cents)}, have {fmt(cash)}.")


def _take_from_stock(qty_on_hand: int, value_cents: int, qty: int) -> int:
    """Cost of removing `qty` units at weighted-average cost (exact when emptying the bin)."""
    if qty == qty_on_hand:
        return value_cents
    return round_cents(Decimal(value_cents) * qty / qty_on_hand)


# --- master data -------------------------------------------------------------
_EMPLOYEE_FIELDS = ("first_name", "last_name", "address1", "address2", "city", "state", "zip",
                    "ssn_last4", "filing_status", "dependents", "annual_salary_cents", "pay_periods", "active")
_CUSTOMER_FIELDS = ("company", "first_name", "last_name", "address1", "address2", "city", "state", "zip",
                    "price_cents")
_VENDOR_FIELDS = ("company", "part_id", "price_cents", "address1", "address2", "city", "state", "zip")


def _insert(conn, table, allowed, data) -> int:
    fields = [f for f in allowed if f in data]
    sql = f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})"
    with db.transaction(conn):
        return conn.execute(sql, [data[f] for f in fields]).lastrowid


def _update(conn, table, allowed, row_id, data) -> None:
    fields = [f for f in allowed if f in data]
    if not fields:
        return
    sql = f"UPDATE {table} SET {', '.join(f + ' = ?' for f in fields)} WHERE id = ?"
    with db.transaction(conn):
        conn.execute(sql, [data[f] for f in fields] + [row_id])


def _clean(data: dict, required: tuple) -> dict:
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in data.items()}
    for field in required:
        if field in data and data[field] in ("", None):
            raise BusinessError(f"{field.replace('_', ' ').title()} is required.")
    return data


def _check_employee(data):
    if "annual_salary_cents" in data and data["annual_salary_cents"] <= 0:
        raise BusinessError("Annual salary must be greater than zero.")
    if "pay_periods" in data and data["pay_periods"] not in (12, 24, 26, 52):
        raise BusinessError("Pay periods per year must be 12, 24, 26 or 52.")
    if data.get("ssn_last4") and not (data["ssn_last4"].isdigit() and len(data["ssn_last4"]) == 4):
        raise BusinessError("SSN (last 4) must be exactly four digits.")


def add_employee(conn, **data) -> int:
    for field in ("first_name", "last_name", "annual_salary_cents"):
        if field not in data:
            raise BusinessError(f"{field.replace('_', ' ').title()} is required.")
    data = _clean(data, ("first_name", "last_name"))
    _check_employee(data)
    return _insert(conn, "employees", _EMPLOYEE_FIELDS, data)


def update_employee(conn, employee_id, **data) -> None:
    data = _clean(data, ("first_name", "last_name"))
    _check_employee(data)
    _update(conn, "employees", _EMPLOYEE_FIELDS, employee_id, data)


def _check_unique(conn, table, company, exclude_id=None):
    row = conn.execute(f"SELECT id FROM {table} WHERE company = ? COLLATE NOCASE", (company,)).fetchone()
    if row and row["id"] != exclude_id:
        raise BusinessError(f"'{company}' already exists.")


def add_customer(conn, **data) -> int:
    if "company" not in data or "price_cents" not in data:
        raise BusinessError("Company name and price are required.")
    data = _clean(data, ("company",))
    if data["price_cents"] <= 0:
        raise BusinessError("Price per unit must be greater than zero.")
    _check_unique(conn, "customers", data["company"])
    return _insert(conn, "customers", _CUSTOMER_FIELDS, data)


def update_customer(conn, customer_id, **data) -> None:
    data = _clean(data, ("company",))
    if "price_cents" in data and data["price_cents"] <= 0:
        raise BusinessError("Price per unit must be greater than zero.")
    if "company" in data:
        _check_unique(conn, "customers", data["company"], customer_id)
    _update(conn, "customers", _CUSTOMER_FIELDS, customer_id, data)


def add_part(conn, name: str, qty_per_unit: int = 0, reorder_point: int = 0) -> int:
    name = name.strip()
    if not name:
        raise BusinessError("Part name is required.")
    if conn.execute("SELECT 1 FROM parts WHERE name = ? COLLATE NOCASE", (name,)).fetchone():
        raise BusinessError(f"Part '{name}' already exists.")
    with db.transaction(conn):
        return conn.execute(
            "INSERT INTO parts(name, qty_per_unit, reorder_point) VALUES (?, ?, ?)",
            (name, qty_per_unit, reorder_point),
        ).lastrowid


def add_vendor(conn, **data) -> int:
    for field in ("company", "part_id", "price_cents"):
        if field not in data:
            raise BusinessError("Company name, part and price are required.")
    data = _clean(data, ("company",))
    if data["price_cents"] <= 0:
        raise BusinessError("Price per unit must be greater than zero.")
    _check_unique(conn, "vendors", data["company"])
    return _insert(conn, "vendors", _VENDOR_FIELDS, data)


def update_vendor(conn, vendor_id, **data) -> None:
    data = _clean(data, ("company",))
    if "price_cents" in data and data["price_cents"] <= 0:
        raise BusinessError("Price per unit must be greater than zero.")
    if "company" in data:
        _check_unique(conn, "vendors", data["company"], vendor_id)
    _update(conn, "vendors", _VENDOR_FIELDS, vendor_id, data)


# --- sales -------------------------------------------------------------------
def create_invoice(conn, customer_id: int, quantity: int, idempotency_key=None) -> dict:
    """Sell finished units on Net 30 terms.

    Dr Accounts Receivable / Cr Sales            (invoice total)
    Dr Cost of Goods Sold  / Cr Finished Goods   (weighted-average cost)
    """
    if quantity <= 0:
        raise BusinessError("Quantity must be greater than zero.")
    with db.transaction(conn):
        customer = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        if customer is None:
            raise BusinessError("Select a customer.")
        stock = conn.execute("SELECT * FROM product_stock WHERE stage = 'finished'").fetchone()
        if quantity > stock["qty"]:
            raise BusinessError(
                f"Only {stock['qty']:,} completed units in stock; cannot invoice {quantity:,}."
            )
        total = quantity * customer["price_cents"]
        cogs = _take_from_stock(stock["qty"], stock["value_cents"], quantity)
        invoice_date = today(conn)
        due = invoice_date + timedelta(days=TERMS_DAYS)
        number = _next_number(conn, "invoices", "INV")

        ledger.post(
            conn, invoice_date, f"Invoice {number} - {customer['company']} ({quantity:,} units)", "SALE",
            [
                (ledger.AR, total, 0),
                (ledger.SALES, 0, total),
                (ledger.COGS, cogs, 0),
                (ledger.FINISHED_GOODS, 0, cogs),
            ],
            reference=number, idempotency_key=idempotency_key,
        )
        conn.execute(
            "UPDATE product_stock SET qty = qty - ?, value_cents = value_cents - ? WHERE stage = 'finished'",
            (quantity, cogs),
        )
        conn.execute(
            "INSERT INTO invoices(number, invoice_date, due_date, customer_id, quantity, unit_price_cents, "
            "total_cents, cogs_cents) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (number, str(invoice_date), str(due), customer_id, quantity, customer["price_cents"], total, cogs),
        )
    return {"number": number, "total_cents": total, "cogs_cents": cogs, "due_date": due}


def receive_payment(conn, invoice_id: int, pay_date=None) -> dict:
    """Customer pays an open invoice: Dr Cash / Cr Accounts Receivable."""
    with db.transaction(conn):
        inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if inv is None or inv["status"] != "OPEN":
            raise BusinessError("Invoice is not open.")
        pay_date = pay_date or today(conn)
        ledger.post(
            conn, pay_date, f"Customer payment received for {inv['number']}", "CUSTOMER_PAYMENT",
            [(ledger.CASH, inv["total_cents"], 0), (ledger.AR, 0, inv["total_cents"])],
            reference=inv["number"],
        )
        conn.execute("UPDATE invoices SET status = 'PAID', paid_date = ? WHERE id = ?", (str(pay_date), invoice_id))
    return {"number": inv["number"], "total_cents": inv["total_cents"]}


# --- purchasing --------------------------------------------------------------
def create_po(conn, vendor_id: int, quantity: int, receive_now: bool = True,
              qty_received=None, billed_cents=None, idempotency_key=None) -> dict:
    """Order one part from its vendor. Nothing hits the ledger until goods are received."""
    if quantity <= 0:
        raise BusinessError("Quantity must be greater than zero.")
    with db.transaction(conn):
        vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if vendor is None:
            raise BusinessError("Select a vendor.")
        number = _next_number(conn, "purchase_orders", "PO")
        po_id = conn.execute(
            "INSERT INTO purchase_orders(number, po_date, vendor_id, part_id, qty_ordered, unit_price_cents) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (number, str(today(conn)), vendor_id, vendor["part_id"], quantity, vendor["price_cents"]),
        ).lastrowid
        result = {"id": po_id, "number": number, "ordered_cents": quantity * vendor["price_cents"]}
        if receive_now:
            result.update(receive_po(conn, po_id, qty_received, billed_cents, idempotency_key))
    return result


def receive_po(conn, po_id: int, qty_received=None, billed_cents=None, idempotency_key=None) -> dict:
    """Goods arrive with the vendor's bill, payable Net 30.

    Dr Inventory - Raw Materials / Cr Accounts Payable   (amount billed)
    The quantity received and amount billed may differ from what was ordered.
    """
    with db.transaction(conn):
        po = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
        if po is None or po["status"] != "ORDERED":
            raise BusinessError("Purchase order is not awaiting receipt.")
        qty = po["qty_ordered"] if qty_received is None else qty_received
        if qty <= 0:
            raise BusinessError("Quantity received must be greater than zero.")
        billed = qty * po["unit_price_cents"] if billed_cents is None else billed_cents
        if billed <= 0:
            raise BusinessError("Amount billed must be greater than zero.")
        received = today(conn)
        due = received + timedelta(days=TERMS_DAYS)
        part = conn.execute("SELECT name FROM parts WHERE id = ?", (po["part_id"],)).fetchone()

        ledger.post(
            conn, received, f"{po['number']} received - {qty:,} x {part['name']}", "PURCHASE",
            [(ledger.RAW_MATERIALS, billed, 0), (ledger.AP, 0, billed)],
            reference=po["number"], idempotency_key=idempotency_key,
        )
        conn.execute(
            "UPDATE parts SET qty_on_hand = qty_on_hand + ?, value_cents = value_cents + ? WHERE id = ?",
            (qty, billed, po["part_id"]),
        )
        conn.execute(
            "UPDATE purchase_orders SET status = 'RECEIVED', qty_received = ?, billed_cents = ?, "
            "received_date = ?, due_date = ? WHERE id = ?",
            (qty, billed, str(received), str(due), po_id),
        )
    return {"number": po["number"], "qty_received": qty, "billed_cents": billed, "due_date": due}


def pay_po(conn, po_id: int, pay_date=None) -> dict:
    """Pay a vendor bill: Dr Accounts Payable / Cr Cash."""
    with db.transaction(conn):
        po = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
        if po is None or po["status"] != "RECEIVED":
            raise BusinessError("Purchase order has no unpaid bill.")
        _require_cash(conn, po["billed_cents"], f"paying {po['number']}")
        pay_date = pay_date or today(conn)
        ledger.post(
            conn, pay_date, f"Vendor payment for {po['number']}", "VENDOR_PAYMENT",
            [(ledger.AP, po["billed_cents"], 0), (ledger.CASH, 0, po["billed_cents"])],
            reference=po["number"],
        )
        conn.execute("UPDATE purchase_orders SET status = 'PAID', paid_date = ? WHERE id = ?", (str(pay_date), po_id))
    return {"number": po["number"], "billed_cents": po["billed_cents"]}


# --- payroll -----------------------------------------------------------------
def preview_paycheck(conn, employee_id: int, bonus_cents: int = 0) -> dict:
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if emp is None:
        raise BusinessError("Select an employee.")
    year = today(conn).year
    ytd = conn.execute(
        "SELECT COALESCE(SUM(salary_cents + bonus_cents), 0) AS g FROM payroll_events "
        "WHERE employee_id = ? AND substr(pay_date, 1, 4) = ?",
        (employee_id, str(year)),
    ).fetchone()["g"]
    return payroll_tax.compute_paycheck(
        emp["annual_salary_cents"], emp["pay_periods"], emp["filing_status"], bonus_cents, ytd
    )


def pay_employee(conn, employee_id: int, bonus_cents: int = 0, idempotency_key=None) -> dict:
    """Run one payroll period for one employee.

    Dr Payroll (net pay)            / Cr Cash       (paid to the employee)
    Dr Payroll Withholding (taxes)  / Cr Accruals   (owed to tax agencies until remitted)
    """
    if bonus_cents < 0:
        raise BusinessError("Bonus cannot be negative.")
    with db.transaction(conn):
        emp = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
        if emp is None:
            raise BusinessError("Select an employee.")
        if not emp["active"]:
            raise BusinessError("Employee is inactive.")
        pay_date = today(conn)
        period = pay_date.strftime("%Y-%m")
        name = f"{emp['first_name']} {emp['last_name']}"
        if emp["pay_periods"] == 12 and conn.execute(
            "SELECT 1 FROM payroll_events WHERE employee_id = ? AND period = ?", (employee_id, period)
        ).fetchone():
            raise BusinessError(f"{name} has already been paid for {period}.")
        if emp["pay_periods"] != 12:
            # more than one period per month: label each period by its sequence number
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM payroll_events WHERE employee_id = ? AND substr(pay_date,1,4) = ?",
                (employee_id, str(pay_date.year)),
            ).fetchone()["n"]
            period = f"{pay_date.year}-P{n + 1:02d}"

        check = preview_paycheck(conn, employee_id, bonus_cents)
        _require_cash(conn, check["net_cents"], "payroll")
        ledger.post(
            conn, pay_date, f"Payroll {period} - {name}", "PAYROLL",
            [
                (ledger.PAYROLL, check["net_cents"], 0),
                (ledger.PAYROLL_WITHHOLDING, check["withholding_cents"], 0),
                (ledger.CASH, 0, check["net_cents"]),
                (ledger.ACCRUALS, 0, check["withholding_cents"]),
            ],
            reference=f"PAY-{period}-{employee_id}", idempotency_key=idempotency_key,
        )
        conn.execute(
            "INSERT INTO payroll_events(pay_date, period, employee_id, salary_cents, bonus_cents, federal_cents, "
            "state_cents, social_sec_cents, medicare_cents, withholding_cents, net_cents) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(pay_date), period, employee_id, check["salary_cents"], check["bonus_cents"],
             check["federal_cents"], check["state_cents"], check["social_sec_cents"], check["medicare_cents"],
             check["withholding_cents"], check["net_cents"]),
        )
    return {"employee": name, "period": period, **check}


def withholding_due_date(pay_date: date) -> date:
    """Withheld payroll taxes are deposited by the 15th of the following month."""
    year, month = (pay_date.year + 1, 1) if pay_date.month == 12 else (pay_date.year, pay_date.month + 1)
    return date(year, month, 15)


def remit_payroll_taxes(conn, pay_date=None, due_through=None) -> int:
    """Send withheld taxes to the agencies: Dr Accruals / Cr Cash. Returns cents remitted."""
    with db.transaction(conn):
        rows = conn.execute("SELECT * FROM payroll_events WHERE remitted_date IS NULL ORDER BY id").fetchall()
        if due_through is not None:
            rows = [r for r in rows if withholding_due_date(date.fromisoformat(r["pay_date"])) <= due_through]
        amount = sum(r["withholding_cents"] for r in rows)
        if not amount:
            return 0
        _require_cash(conn, amount, "remitting payroll taxes")
        pay_date = pay_date or today(conn)
        ledger.post(
            conn, pay_date, "Remit withheld payroll taxes", "PAYROLL_TAX_REMIT",
            [(ledger.ACCRUALS, amount, 0), (ledger.CASH, 0, amount)],
        )
        conn.executemany(
            "UPDATE payroll_events SET remitted_date = ? WHERE id = ?", [(str(pay_date), r["id"]) for r in rows]
        )
    return amount


# --- operating expenses & income tax ----------------------------------------
def monthly_bill_cents(annual_budget_cents: int) -> int:
    return round_cents(Decimal(annual_budget_cents) / 12)


def pay_expense(conn, expense_account_id: int, amount_cents=None, idempotency_key=None) -> dict:
    """Pay a monthly bill: Dr <expense account> / Cr Cash."""
    with db.transaction(conn):
        acct = conn.execute("SELECT * FROM expense_accounts WHERE id = ?", (expense_account_id,)).fetchone()
        if acct is None:
            raise BusinessError("Select an expense account.")
        amount = monthly_bill_cents(acct["annual_budget_cents"]) if amount_cents is None else amount_cents
        if amount <= 0:
            raise BusinessError("Amount must be greater than zero.")
        _require_cash(conn, amount, f"paying {acct['name']}")
        pay_date = today(conn)
        ledger.post(
            conn, pay_date, f"Bill paid - {acct['name']}", "EXPENSE",
            [(acct["account_code"], amount, 0), (ledger.CASH, 0, amount)],
            idempotency_key=idempotency_key,
        )
        conn.execute(
            "INSERT INTO expense_payments(pay_date, expense_account_id, description, amount_cents) VALUES (?, ?, ?, ?)",
            (str(pay_date), expense_account_id, acct["name"], amount),
        )
    return {"name": acct["name"], "amount_cents": amount}


def pay_income_tax(conn, amount_cents: int, idempotency_key=None) -> dict:
    """Record an income tax payment in its own account: Dr Income Taxes / Cr Cash."""
    if amount_cents <= 0:
        raise BusinessError("Amount must be greater than zero.")
    with db.transaction(conn):
        _require_cash(conn, amount_cents, "income taxes")
        pay_date = today(conn)
        ledger.post(
            conn, pay_date, "Income tax payment", "INCOME_TAX",
            [(ledger.INCOME_TAX, amount_cents, 0), (ledger.CASH, 0, amount_cents)],
            idempotency_key=idempotency_key,
        )
        conn.execute(
            "INSERT INTO expense_payments(pay_date, expense_account_id, description, amount_cents) "
            "VALUES (?, NULL, 'Income Taxes', ?)",
            (str(pay_date), amount_cents),
        )
    return {"amount_cents": amount_cents}


# --- manufacturing -----------------------------------------------------------
def buildable_units(conn) -> int:
    rows = conn.execute("SELECT qty_on_hand, qty_per_unit FROM parts WHERE qty_per_unit > 0").fetchall()
    return min((r["qty_on_hand"] // r["qty_per_unit"] for r in rows), default=0)


def start_build(conn, units: int) -> dict:
    """Issue BOM parts to the line: Dr Work in Process / Cr Raw Materials (a transfer, not an expense)."""
    if units <= 0:
        raise BusinessError("Units must be greater than zero.")
    with db.transaction(conn):
        parts = conn.execute("SELECT * FROM parts WHERE qty_per_unit > 0 ORDER BY id").fetchall()
        if not parts:
            raise BusinessError("No bill of materials is defined.")
        short = [
            f"{p['name']} (need {p['qty_per_unit'] * units:,}, have {p['qty_on_hand']:,})"
            for p in parts if p["qty_per_unit"] * units > p["qty_on_hand"]
        ]
        if short:
            raise BusinessError("Not enough parts to build %s units: %s." % (f"{units:,}", "; ".join(short)))
        cost = 0
        for p in parts:
            need = p["qty_per_unit"] * units
            part_cost = _take_from_stock(p["qty_on_hand"], p["value_cents"], need)
            cost += part_cost
            conn.execute(
                "UPDATE parts SET qty_on_hand = qty_on_hand - ?, value_cents = value_cents - ? WHERE id = ?",
                (need, part_cost, p["id"]),
            )
        build_date = today(conn)
        ledger.post(
            conn, build_date, f"Start production of {units:,} units", "BUILD",
            [(ledger.WIP, cost, 0), (ledger.RAW_MATERIALS, 0, cost)],
        )
        conn.execute("UPDATE product_stock SET qty = qty + ?, value_cents = value_cents + ? WHERE stage = 'wip'",
                     (units, cost))
        conn.execute("INSERT INTO build_events(build_date, action, units, cost_cents) VALUES (?, 'START', ?, ?)",
                     (str(build_date), units, cost))
    return {"units": units, "cost_cents": cost}


def complete_build(conn, units: int) -> dict:
    """Finish units under construction: Dr Finished Goods / Cr Work in Process."""
    if units <= 0:
        raise BusinessError("Units must be greater than zero.")
    with db.transaction(conn):
        wip = conn.execute("SELECT * FROM product_stock WHERE stage = 'wip'").fetchone()
        if units > wip["qty"]:
            raise BusinessError(f"Only {wip['qty']:,} units are under construction.")
        cost = _take_from_stock(wip["qty"], wip["value_cents"], units)
        build_date = today(conn)
        ledger.post(
            conn, build_date, f"Complete production of {units:,} units", "BUILD",
            [(ledger.FINISHED_GOODS, cost, 0), (ledger.WIP, 0, cost)],
        )
        conn.execute("UPDATE product_stock SET qty = qty - ?, value_cents = value_cents - ? WHERE stage = 'wip'",
                     (units, cost))
        conn.execute("UPDATE product_stock SET qty = qty + ?, value_cents = value_cents + ? WHERE stage = 'finished'",
                     (units, cost))
        conn.execute("INSERT INTO build_events(build_date, action, units, cost_cents) VALUES (?, 'COMPLETE', ?, ?)",
                     (str(build_date), units, cost))
    return {"units": units, "cost_cents": cost}


def build_units(conn, units: int) -> dict:
    """Build straight through to finished goods."""
    with db.transaction(conn):
        start_build(conn, units)
        return complete_build(conn, units)


# --- Net 30 settlement -------------------------------------------------------
def advance_date(conn, days: int) -> list:
    """Move the simulation clock forward and settle everything that falls due.

    Receivables are collected and payables paid on their due dates, in date
    order (collections first on the same day). Returns a log of what happened.
    """
    if days <= 0:
        raise BusinessError("Days must be greater than zero.")
    log = []
    with db.transaction(conn):
        new_date = today(conn) + timedelta(days=days)
        events = []
        for inv in conn.execute(
            "SELECT * FROM invoices WHERE status = 'OPEN' AND due_date <= ?", (str(new_date),)
        ).fetchall():
            events.append((inv["due_date"], 0, inv["id"], "invoice", inv))
        for po in conn.execute(
            "SELECT * FROM purchase_orders WHERE status = 'RECEIVED' AND due_date <= ?", (str(new_date),)
        ).fetchall():
            events.append((po["due_date"], 1, po["id"], "po", po))
        tax_dates = sorted({
            withholding_due_date(date.fromisoformat(r["pay_date"]))
            for r in conn.execute("SELECT pay_date FROM payroll_events WHERE remitted_date IS NULL").fetchall()
        })
        for due in tax_dates:
            if due <= new_date:
                events.append((str(due), 2, 0, "tax", due))

        for due, _, _, kind, item in sorted(events, key=lambda e: e[:3]):
            due_date = date.fromisoformat(due)
            try:
                if kind == "invoice":
                    receive_payment(conn, item["id"], due_date)
                    log.append(f"{due}: collected {fmt(item['total_cents'])} for {item['number']}")
                elif kind == "po":
                    pay_po(conn, item["id"], due_date)
                    log.append(f"{due}: paid {fmt(item['billed_cents'])} for {item['number']}")
                else:
                    amount = remit_payroll_taxes(conn, due_date, due_through=due_date)
                    log.append(f"{due}: remitted {fmt(amount)} of withheld payroll taxes")
            except BusinessError as exc:
                log.append(f"{due}: NOT settled - {exc}")
        db.set_setting(conn, "current_date", str(new_date))
    log.insert(0, f"Date advanced to {new_date}.")
    return log


def month_end_settlement(conn) -> list:
    """The guide's month-end rule: post all receivables to cash and pay all bills now,
    even if 30 days have not elapsed. Withheld payroll taxes are remitted too."""
    log = []
    with db.transaction(conn):
        for inv in conn.execute("SELECT * FROM invoices WHERE status = 'OPEN' ORDER BY id").fetchall():
            receive_payment(conn, inv["id"])
            log.append(f"Collected {fmt(inv['total_cents'])} for {inv['number']}")
        for po in conn.execute("SELECT * FROM purchase_orders WHERE status = 'RECEIVED' ORDER BY id").fetchall():
            pay_po(conn, po["id"])
            log.append(f"Paid {fmt(po['billed_cents'])} for {po['number']}")
        amount = remit_payroll_taxes(conn)
        if amount:
            log.append(f"Remitted {fmt(amount)} of withheld payroll taxes")
    return log or ["Nothing to settle."]
