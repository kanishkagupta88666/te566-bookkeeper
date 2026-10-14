"""View, add and edit vendors; each vendor supplies one part at a set price."""
import streamlit as st

import ui
from bookkeeper import db, services
from bookkeeper.money import fmt

conn = ui.conn()
st.title("Vendors")

parts = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM parts ORDER BY id").fetchall()}
ADDRESS = [
    ("address1", "Address 1", "text", None),
    ("address2", "Address 2", "text", None),
    ("city", "City", "text", None),
    ("state", "State", "text", None),
    ("zip", "ZIP code", "text", None),
]
EDIT_FIELDS = [
    ("company", "Company name", "text", None),
    ("part_id", "Part supplied", "select", parts),
    ("price_cents", "Price per unit ($)", "money", None),
] + ADDRESS
NEW_PART = "(new part - enter name below)"
ADD_FIELDS = [
    ("company", "Company name", "text", None),
    ("part_id", "Part supplied", "select", {**parts, NEW_PART: None}),
    ("new_part", "New part name (only if adding a new part)", "text", None),
    ("price_cents", "Price per unit ($)", "money", None),
] + ADDRESS

rows = conn.execute(
    "SELECT v.*, p.name AS part, "
    "(SELECT COALESCE(SUM(billed_cents), 0) FROM purchase_orders po WHERE po.vendor_id = v.id "
    " AND po.status = 'RECEIVED') AS owed "
    "FROM vendors v JOIN parts p ON p.id = v.part_id ORDER BY v.id"
).fetchall()
ui.table(
    ["ID", "Company Name", "Part", "Price/Unit", "Address 1", "Address 2", "City", "State", "ZIP", "Outstanding"],
    [(r["id"], r["company"], r["part"], fmt(r["price_cents"]), r["address1"], r["address2"], r["city"], r["state"],
      r["zip"], fmt(r["owed"])) for r in rows],
    numeric={3, 9},
)


def add_vendor(data):
    """Create the vendor, and the part it supplies if that part is new, as one unit of work."""
    data = dict(data)
    new_part = data.pop("new_part", "").strip()
    with db.transaction(conn):
        if data["part_id"] is None:
            data["part_id"] = services.add_part(conn, new_part)
        return services.add_vendor(conn, **data)


add_tab, edit_tab = st.tabs(["Add Vendor", "Edit Vendor"])
with add_tab:
    data = ui.record_form("add_vendor", ADD_FIELDS, submit_label="Add Vendor")
    if data:
        ui.run(lambda: add_vendor(data), f"Added vendor {data['company']}.")
with edit_tab:
    by_label = {f"{r['id']} — {r['company']}": r for r in rows}
    current = by_label[st.selectbox("Vendor to edit", list(by_label))]
    data = ui.record_form(f"edit_vendor_{current['id']}", EDIT_FIELDS, initial=dict(current), submit_label="Save Changes")
    if data:
        ui.run(lambda: services.update_vendor(conn, current["id"], **data), "Vendor updated.")
