"""Create Invoice and Invoice History. A sale becomes a Net 30 receivable."""
import streamlit as st

import ui
from bookkeeper import reports, services
from bookkeeper.money import fmt

conn = ui.conn()
st.title("Create Invoice")

inv = reports.inventory_report(conn)
customers = conn.execute("SELECT * FROM customers ORDER BY company").fetchall()
by_label = {f"{c['company']} — {fmt(c['price_cents'])}/unit": c for c in customers}

left, right = st.columns([1, 1], gap="large")
with left:
    choice = st.selectbox("Customer", list(by_label))
    quantity = st.number_input("Units to invoice", min_value=0, step=100, value=0)
    customer = by_label[choice]
    total = quantity * customer["price_cents"]
    st.markdown(f"**Complete units in stock:** {inv['finished_qty']:,}")
    st.markdown(f"**Invoice total:** {fmt(total)} · Terms: Net {services.TERMS_DAYS}")
    if st.button("Create Invoice", type="primary"):
        ui.run(
            lambda: services.create_invoice(conn, customer["id"], int(quantity), ui.form_token("invoice")),
            lambda r: f"Invoice {r['number']} posted: {fmt(r['total_cents'])} receivable, due {r['due_date']}.",
            token="invoice",
        )
with right:
    st.info(
        "Posting an invoice:\n"
        "- **Balance sheet** — Accounts Receivable increases by the invoice total; "
        "finished-goods inventory decreases at cost.\n"
        "- **Income statement** — Sales increases; COGS records the cost of the units sold.\n"
        "- **Net 30** — cash is collected when the invoice falls due (advance the date under *Date & Reset Demo*)."
    )

st.subheader("Invoice History")
rows = conn.execute(
    "SELECT i.*, c.company FROM invoices i JOIN customers c ON c.id = i.customer_id ORDER BY i.id DESC"
).fetchall()
ui.table(
    ["Invoice Number", "Date", "Customer", "Quantity", "Price/Part", "Total", "COGS", "Due", "Status"],
    [(r["number"], r["invoice_date"], r["company"], ui.units(r["quantity"]), fmt(r["unit_price_cents"]),
      fmt(r["total_cents"]), fmt(r["cogs_cents"]), r["due_date"],
      "Open" if r["status"] == "OPEN" else f"Paid {r['paid_date']}") for r in rows],
    numeric={3, 4, 5, 6},
)

open_invoices = [r for r in rows if r["status"] == "OPEN"]
if open_invoices:
    with st.expander("Receive a customer payment now"):
        labels = {f"{r['number']} — {r['company']} — {fmt(r['total_cents'])}": r["id"] for r in open_invoices}
        pick = st.selectbox("Open invoice", list(labels))
        if st.button("Receive Payment"):
            ui.run(lambda: services.receive_payment(conn, labels[pick]),
                   lambda r: f"Received {fmt(r['total_cents'])} for {r['number']}.")
