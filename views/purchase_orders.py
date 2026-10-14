"""Create PO and PO History. Received goods become inventory and a Net 30 payable."""
import streamlit as st

import ui
from bookkeeper import services
from bookkeeper.money import fmt, to_cents

conn = ui.conn()
st.title("Create PO")

vendors = conn.execute(
    "SELECT v.*, p.name AS part, p.qty_on_hand FROM vendors v JOIN parts p ON p.id = v.part_id ORDER BY p.id, v.id"
).fetchall()
by_label = {f"{v['part']} — {v['company']} — {fmt(v['price_cents'])}/unit": v for v in vendors}

left, right = st.columns([1, 1], gap="large")
with left:
    choice = st.selectbox("Part / Vendor", list(by_label))
    quantity = st.number_input("Quantity", min_value=0, step=1000, value=0)
    vendor = by_label[choice]
    total = quantity * vendor["price_cents"]
    st.markdown(f"**In stock now:** {vendor['qty_on_hand']:,} {vendor['part']}")
    st.markdown(f"**PO total:** {fmt(total)} · Terms: Net {services.TERMS_DAYS}")
    received_now = st.checkbox("Goods received now (full quantity, billed as ordered)", value=True)
    if st.button("Create PO", type="primary"):
        ui.run(
            lambda: services.create_po(conn, vendor["id"], int(quantity), receive_now=received_now,
                                       idempotency_key=ui.form_token("po")),
            lambda r: (f"{r['number']} received: {fmt(r['billed_cents'])} payable, due {r['due_date']}."
                       if "billed_cents" in r else f"{r['number']} ordered ({fmt(r['ordered_cents'])}); awaiting receipt."),
            token="po",
        )
with right:
    st.info(
        "Receiving a purchase order:\n"
        "- **Balance sheet** — Inventory increases and Accounts Payable increases by the amount billed.\n"
        "- **Income statement** — no change. Parts are an asset until the trucks built from them are sold (COGS).\n"
        "- **Net 30** — cash is paid when the bill falls due."
    )

rows = conn.execute(
    "SELECT po.*, v.company, p.name AS part FROM purchase_orders po JOIN vendors v ON v.id = po.vendor_id "
    "JOIN parts p ON p.id = po.part_id ORDER BY po.id DESC"
).fetchall()

awaiting = [r for r in rows if r["status"] == "ORDERED"]
if awaiting:
    with st.expander("Receive an open purchase order", expanded=True):
        labels = {f"{r['number']} — {ui.units(r['qty_ordered'])} x {r['part']}": r for r in awaiting}
        po = labels[st.selectbox("Purchase order", list(labels))]
        c1, c2 = st.columns(2)
        qty = c1.number_input("Quantity actually received", min_value=0, step=100, value=po["qty_ordered"],
                              key=f"rq_{po['id']}")
        billed = c2.number_input("Amount billed ($)", min_value=0.0, step=0.01, format="%.2f",
                                 value=po["qty_ordered"] * po["unit_price_cents"] / 100, key=f"rb_{po['id']}")
        if st.button("Receive Goods"):
            ui.run(lambda: services.receive_po(conn, po["id"], int(qty), to_cents(billed)),
                   lambda r: f"{r['number']} received: {ui.units(r['qty_received'])} units, {fmt(r['billed_cents'])} payable.")

st.subheader("PO History")
STATUS = {"ORDERED": "Ordered", "RECEIVED": "Received - unpaid", "PAID": "Paid"}
ui.table(
    ["PO Number", "Date", "Supplier", "Part", "Qty Ordered", "Qty Received", "Price/Part", "Total Billed", "Due",
     "Status"],
    [(r["number"], r["po_date"], r["company"], r["part"], ui.units(r["qty_ordered"]), ui.units(r["qty_received"]),
      fmt(r["unit_price_cents"]), fmt(r["billed_cents"]), r["due_date"] or "",
      STATUS[r["status"]] + (f" {r['paid_date']}" if r["paid_date"] else "")) for r in rows],
    numeric={4, 5, 6, 7},
)

unpaid = [r for r in rows if r["status"] == "RECEIVED"]
if unpaid:
    with st.expander("Pay a vendor bill now"):
        labels = {f"{r['number']} — {r['company']} — {fmt(r['billed_cents'])}": r["id"] for r in unpaid}
        pick = st.selectbox("Unpaid bill", list(labels))
        if st.button("Pay Bill"):
            ui.run(lambda: services.pay_po(conn, labels[pick]),
                   lambda r: f"Paid {fmt(r['billed_cents'])} for {r['number']}.")
