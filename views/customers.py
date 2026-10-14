"""View, add and edit customers; each customer has their own selling price."""
import streamlit as st

import ui
from bookkeeper import services
from bookkeeper.money import fmt

conn = ui.conn()
st.title("Customers")

FIELDS = [
    ("company", "Company name", "text", None),
    ("price_cents", "Price per unit ($)", "money", None),
    ("first_name", "Contact first name", "text", None),
    ("last_name", "Contact last name", "text", None),
    ("address1", "Address 1", "text", None),
    ("address2", "Address 2", "text", None),
    ("city", "City", "text", None),
    ("state", "State", "text", None),
    ("zip", "ZIP code", "text", None),
]

rows = conn.execute(
    "SELECT c.*, "
    "(SELECT COUNT(*) FROM invoices i WHERE i.customer_id = c.id) AS invoice_count, "
    "(SELECT COALESCE(SUM(total_cents), 0) FROM invoices i WHERE i.customer_id = c.id AND i.status = 'OPEN') AS owed "
    "FROM customers c ORDER BY c.id"
).fetchall()
ui.table(
    ["ID", "Company Name", "Last Name", "First Name", "Address 1", "Address 2", "City", "State", "ZIP", "Price",
     "Invoices", "Outstanding"],
    [(r["id"], r["company"], r["last_name"], r["first_name"], r["address1"], r["address2"], r["city"], r["state"],
      r["zip"], fmt(r["price_cents"]), r["invoice_count"], fmt(r["owed"])) for r in rows],
    numeric={9, 10, 11},
)

add_tab, edit_tab = st.tabs(["Add Customer", "Edit Customer"])
with add_tab:
    data = ui.record_form("add_customer", FIELDS, submit_label="Add Customer")
    if data:
        ui.run(lambda: services.add_customer(conn, **data), f"Added customer {data['company']}.")
with edit_tab:
    by_label = {f"{r['id']} — {r['company']}": r for r in rows}
    current = by_label[st.selectbox("Customer to edit", list(by_label))]
    data = ui.record_form(f"edit_customer_{current['id']}", FIELDS, initial=dict(current), submit_label="Save Changes")
    if data:
        ui.run(lambda: services.update_customer(conn, current["id"], **data), "Customer updated.")
