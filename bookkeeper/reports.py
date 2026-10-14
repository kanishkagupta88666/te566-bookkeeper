"""Financial statements and inventory reports, all derived from persisted data.

A statement is returned as {"title", "rows", "values"}:
  rows   - [(label, cents | None, kind)] with kind in section / line / subtotal / total
  values - {key: cents} for programmatic use (tests, dashboard, PDF captions)
"""
from . import ledger
from .services import buildable_units, monthly_bill_cents


def _expense_codes(conn) -> list:
    return [r["account_code"] for r in conn.execute("SELECT account_code FROM expense_accounts").fetchall()]


def income_statement(conn) -> dict:
    b = ledger.balances(conn)
    sales = b[ledger.SALES]
    cogs = b[ledger.COGS]
    gross = sales - cogs
    payroll = b[ledger.PAYROLL]
    withholding = b[ledger.PAYROLL_WITHHOLDING]
    bills = sum(b[c] for c in _expense_codes(conn))
    total_expenses = payroll + withholding + bills
    other = b[ledger.OTHER_INCOME]
    operating = gross - total_expenses + other
    taxes = b[ledger.INCOME_TAX]
    net = operating - taxes
    rows = [
        ("Sales", None, "section"),
        ("Sales", sales, "line"),
        ("COGS", cogs, "line"),
        ("Gross Profit", gross, "subtotal"),
        ("Expenses", None, "section"),
        ("Payroll", payroll, "line"),
        ("Payroll Withholding", withholding, "line"),
        ("Bills (Operating Expenses)", bills, "line"),
        ("Total Expenses", total_expenses, "subtotal"),
        ("Results", None, "section"),
        ("Other Income", other, "line"),
        ("Operating Income", operating, "subtotal"),
        ("Income Taxes", taxes, "line"),
        ("Net Income", net, "total"),
    ]
    values = dict(sales=sales, cogs=cogs, gross_profit=gross, payroll=payroll, payroll_withholding=withholding,
                  bills=bills, total_expenses=total_expenses, other_income=other, operating_income=operating,
                  income_taxes=taxes, net_income=net)
    return {"title": "Income Statement", "rows": rows, "values": values}


def balance_sheet(conn) -> dict:
    b = ledger.balances(conn)
    cash, ar = b[ledger.CASH], b[ledger.AR]
    raw, wip, finished = b[ledger.RAW_MATERIALS], b[ledger.WIP], b[ledger.FINISHED_GOODS]
    inventory = raw + wip + finished
    current_assets = cash + ar + inventory
    land, equipment, furniture = b[ledger.LAND_BUILDINGS], b[ledger.EQUIPMENT], b[ledger.FURNITURE]
    fixed = land + equipment + furniture
    total_assets = current_assets + fixed

    ap, notes, accruals = b[ledger.AP], b[ledger.NOTES_PAYABLE], b[ledger.ACCRUALS]
    current_liabilities = ap + notes + accruals
    mortgage = b[ledger.MORTGAGE]
    total_liabilities = current_liabilities + mortgage

    capital = b[ledger.OWNER_CAPITAL]
    retained = income_statement(conn)["values"]["net_income"]
    net_worth = capital + retained

    rows = [
        ("Assets", None, "section"),
        ("Cash", cash, "line"),
        ("Accounts Receivable", ar, "line"),
        ("Inventory", inventory, "line"),
        ("Total Current Assets", current_assets, "subtotal"),
        ("Land/Buildings", land, "line"),
        ("Equipment", equipment, "line"),
        ("Furniture and Fixtures", furniture, "line"),
        ("Total Fixed Assets", fixed, "subtotal"),
        ("Total Assets", total_assets, "total"),
        ("Liabilities", None, "section"),
        ("Accounts Payable", ap, "line"),
        ("Notes Payable", notes, "line"),
        ("Accruals", accruals, "line"),
        ("Total Current Liabilities", current_liabilities, "subtotal"),
        ("Mortgage", mortgage, "line"),
        ("Total Long Term Debt", mortgage, "subtotal"),
        ("Total Liabilities", total_liabilities, "total"),
        ("Net Worth", None, "section"),
        ("Owner's Capital", capital, "line"),
        ("Retained Earnings (Net Income to Date)", retained, "line"),
        ("Net Worth", net_worth, "total"),
        ("Total Liabilities & Net Worth", total_liabilities + net_worth, "total"),
    ]
    values = dict(cash=cash, accounts_receivable=ar, inventory=inventory, raw_materials=raw, wip=wip,
                  finished_goods=finished, total_current_assets=current_assets, total_fixed_assets=fixed,
                  total_assets=total_assets, accounts_payable=ap, notes_payable=notes, accruals=accruals,
                  total_current_liabilities=current_liabilities, mortgage=mortgage,
                  total_liabilities=total_liabilities, owner_capital=capital, retained_earnings=retained,
                  net_worth=net_worth, total_liabilities_and_net_worth=total_liabilities + net_worth)
    return {"title": "Balance Sheet", "rows": rows, "values": values}


_CASH_FLOW_LINES = [
    ("operating", "CUSTOMER_PAYMENT", "Cash received from customers"),
    ("operating", "VENDOR_PAYMENT", "Cash paid to vendors for inventory"),
    ("operating", "PAYROLL", "Cash paid to employees (net pay)"),
    ("operating", "PAYROLL_TAX_REMIT", "Payroll taxes remitted"),
    ("operating", "EXPENSE", "Cash paid for operating expenses"),
    ("operating", "INCOME_TAX", "Income taxes paid"),
    ("financing", "OPENING", "Owner's cash investment"),
]


def cash_flow(conn) -> dict:
    """Direct-method statement of cash flows: every movement of the Cash account by cause."""
    by_type = {
        r["txn_type"]: r["net"]
        for r in conn.execute(
            "SELECT e.txn_type, SUM(l.debit_cents) - SUM(l.credit_cents) AS net "
            "FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id "
            "WHERE l.account_code = ? GROUP BY e.txn_type",
            (ledger.CASH,),
        ).fetchall()
    }
    rows, totals = [], {"operating": 0, "financing": 0}
    for section, label in (("operating", "Operating Activities"), ("financing", "Financing Activities")):
        rows.append((label, None, "section"))
        for sec, txn_type, line_label in _CASH_FLOW_LINES:
            if sec == section:
                amount = by_type.pop(txn_type, 0)
                totals[section] += amount
                rows.append((line_label, amount, "line"))
        rows.append((f"Net Cash from {label}", totals[section], "subtotal"))
    other = sum(by_type.values())  # anything unclassified is still shown, never hidden
    if other:
        rows.append(("Other cash movements", other, "line"))
    net_change = totals["operating"] + totals["financing"] + other
    rows += [
        ("Cash Position", None, "section"),
        ("Beginning Cash", 0, "line"),
        ("Net Change in Cash", net_change, "subtotal"),
        ("Ending Cash", net_change, "total"),
    ]
    values = dict(operating=totals["operating"], financing=totals["financing"], net_change=net_change,
                  ending_cash=net_change)
    return {"title": "Cash Flow Statement", "rows": rows, "values": values}


def inventory_report(conn) -> dict:
    parts = []
    cost_per_unit = 0
    for p in conn.execute(
        "SELECT p.*, (SELECT company FROM vendors v WHERE v.part_id = p.id ORDER BY v.id LIMIT 1) AS vendor, "
        "(SELECT price_cents FROM vendors v WHERE v.part_id = p.id ORDER BY v.id LIMIT 1) AS vendor_price "
        "FROM parts p ORDER BY p.id"
    ).fetchall():
        # unit cost: weighted average of stock on hand; fall back to the vendor's price when the bin is empty
        avg = p["value_cents"] / p["qty_on_hand"] if p["qty_on_hand"] else (p["vendor_price"] or 0)
        cost_per_unit += avg * p["qty_per_unit"]
        parts.append({
            "id": p["id"], "name": p["name"], "vendor": p["vendor"] or "", "qty_per_unit": p["qty_per_unit"],
            "unit_cost_cents": avg, "qty": p["qty_on_hand"], "value_cents": p["value_cents"],
            "reorder_point": p["reorder_point"], "reorder": p["qty_on_hand"] <= p["reorder_point"],
        })
    stock = {r["stage"]: r for r in conn.execute("SELECT * FROM product_stock").fetchall()}
    raw_value = sum(p["value_cents"] for p in parts)
    wip, finished = stock["wip"], stock["finished"]
    return {
        "parts": parts,
        "raw_value_cents": raw_value,
        "cog_per_unit_cents": cost_per_unit,
        "buildable_units": buildable_units(conn),
        "wip_qty": wip["qty"], "wip_value_cents": wip["value_cents"],
        "finished_qty": finished["qty"], "finished_value_cents": finished["value_cents"],
        "finished_unit_cost_cents": finished["value_cents"] / finished["qty"] if finished["qty"] else 0,
        "total_value_cents": raw_value + wip["value_cents"] + finished["value_cents"],
        "low_stock": [p["name"] for p in parts if p["reorder"]],
    }


def expense_summary(conn) -> list:
    b = ledger.balances(conn)
    return [
        {"id": r["id"], "name": r["name"], "annual_budget_cents": r["annual_budget_cents"],
         "monthly_cents": monthly_bill_cents(r["annual_budget_cents"]), "paid_cents": b[r["account_code"]]}
        for r in conn.execute("SELECT * FROM expense_accounts ORDER BY id").fetchall()
    ]


def integrity_checks(conn) -> list:
    """Reconciliations between the general ledger and the subledgers: [(name, ok, detail)]."""
    from .money import fmt

    b = ledger.balances(conn)
    bs = balance_sheet(conn)["values"]
    totals = conn.execute("SELECT COALESCE(SUM(debit_cents),0) dr, COALESCE(SUM(credit_cents),0) cr FROM journal_lines").fetchone()
    unbalanced = conn.execute(
        "SELECT COUNT(*) n FROM (SELECT entry_id FROM journal_lines GROUP BY entry_id "
        "HAVING SUM(debit_cents) <> SUM(credit_cents))"
    ).fetchone()["n"]

    def one(sql):
        return conn.execute(sql).fetchone()[0]

    open_ar = one("SELECT COALESCE(SUM(total_cents),0) FROM invoices WHERE status = 'OPEN'")
    open_ap = one("SELECT COALESCE(SUM(billed_cents),0) FROM purchase_orders WHERE status = 'RECEIVED'")
    raw = one("SELECT COALESCE(SUM(value_cents),0) FROM parts")
    wip = one("SELECT value_cents FROM product_stock WHERE stage = 'wip'")
    finished = one("SELECT value_cents FROM product_stock WHERE stage = 'finished'")
    unremitted = one("SELECT COALESCE(SUM(withholding_cents),0) FROM payroll_events WHERE remitted_date IS NULL")

    def check(name, left, right):
        return (name, left == right, f"{fmt(left)} vs {fmt(right)}")

    return [
        check("Total debits = total credits", totals["dr"], totals["cr"]),
        ("Every journal entry balances", unbalanced == 0, f"{unbalanced} unbalanced entries"),
        check("Total assets = liabilities + net worth", bs["total_assets"], bs["total_liabilities_and_net_worth"]),
        check("Accounts Receivable = open invoices", b[ledger.AR], open_ar),
        check("Accounts Payable = unpaid vendor bills", b[ledger.AP], open_ap),
        check("Raw materials GL = parts on hand", b[ledger.RAW_MATERIALS], raw),
        check("Work in process GL = units under construction", b[ledger.WIP], wip),
        check("Finished goods GL = completed units", b[ledger.FINISHED_GOODS], finished),
        check("Accruals = unremitted payroll withholding", b[ledger.ACCRUALS], unremitted),
        check("Cash flow ending cash = Cash on balance sheet", cash_flow(conn)["values"]["ending_cash"], bs["cash"]),
        ("Cash is not negative", bs["cash"] >= 0, fmt(bs["cash"])),
    ]
