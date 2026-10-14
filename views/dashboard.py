"""Main menu and at-a-glance position of the business."""
import streamlit as st

import ui
from bookkeeper import db, ledger, reports
from bookkeeper.money import fmt

conn = ui.conn()
bs = reports.balance_sheet(conn)["values"]
inc = reports.income_statement(conn)["values"]
inv = reports.inventory_report(conn)

st.title("ENG/TE 566 Computer Program")
st.caption(f"{db.get_setting(conn, 'company_name')} · simulation date {db.get_setting(conn, 'current_date')}")

for col, (label, value) in zip(st.columns(3) + st.columns(3), [
    ("Cash", bs["cash"]), ("Accounts Receivable", bs["accounts_receivable"]),
    ("Accounts Payable", bs["accounts_payable"]), ("Inventory", bs["inventory"]),
    ("Sales", inc["sales"]), ("Net Income", inc["net_income"]),
]):
    col.metric(label, fmt(value))

st.subheader("Main Menu")
MENU = [
    [("views/employees.py", "List / Add Employees"), ("views/payroll.py", "Pay Employee / Payroll History")],
    [("views/customers.py", "List / Add Customers"), ("views/invoices.py", "Create Invoice / Invoice History")],
    [("views/vendors.py", "List / Add Vendors"), ("views/purchase_orders.py", "Create PO / PO History")],
    [("views/inventory.py", "Inventory / Build Units"), ("views/expenses.py", "Expenses & Bills")],
    [("views/statements.py", "Balance Sheet / Income Statement"), ("views/general_ledger.py", "General Ledger & Audit")],
]
for col, links in zip(st.columns(5), MENU):
    for target, label in links:
        col.page_link(target, label=label, icon=":material/arrow_forward:")

if inv["low_stock"]:
    st.warning("Low stock — reorder: " + ", ".join(inv["low_stock"]))

left, right = st.columns(2, gap="large")
with left:
    st.subheader("Outstanding customer invoices")
    rows = conn.execute(
        "SELECT i.number, c.company, i.due_date, i.total_cents FROM invoices i "
        "JOIN customers c ON c.id = i.customer_id WHERE i.status = 'OPEN' ORDER BY i.due_date, i.id"
    ).fetchall()
    ui.table(["Invoice", "Customer", "Due", "Amount"],
             [(r["number"], r["company"], r["due_date"], fmt(r["total_cents"])) for r in rows],
             numeric={3}, empty="No outstanding invoices.")
with right:
    st.subheader("Outstanding vendor bills")
    rows = conn.execute(
        "SELECT p.number, v.company, p.due_date, p.billed_cents FROM purchase_orders p "
        "JOIN vendors v ON v.id = p.vendor_id WHERE p.status = 'RECEIVED' ORDER BY p.due_date, p.id"
    ).fetchall()
    ui.table(["PO", "Vendor", "Due", "Amount"],
             [(r["number"], r["company"], r["due_date"], fmt(r["billed_cents"])) for r in rows],
             numeric={3}, empty="No outstanding bills.")

st.subheader("Recent transactions")
entries = conn.execute(
    "SELECT e.id, e.entry_date, e.txn_type, e.description, SUM(l.debit_cents) AS amount "
    "FROM journal_entries e JOIN journal_lines l ON l.entry_id = e.id GROUP BY e.id ORDER BY e.id DESC LIMIT 8"
).fetchall()
ui.table(["#", "Date", "Type", "Description", "Amount"],
         [(r["id"], r["entry_date"], r["txn_type"].replace("_", " ").title(), r["description"], fmt(r["amount"]))
          for r in entries], numeric={4})
