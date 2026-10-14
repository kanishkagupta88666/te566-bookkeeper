"""Inventory in units and dollars: parts, units under construction, completed units, reorder flags."""
import streamlit as st

import ui
from bookkeeper import reports, services
from bookkeeper.money import fmt

conn = ui.conn()
st.title("Inventory")
inv = reports.inventory_report(conn)

if inv["low_stock"]:
    st.warning("Low stock — reorder needed: " + ", ".join(inv["low_stock"]))

c = st.columns([1.4, 1, 1, 1, 1])
c[0].metric("Total Inventory Value", fmt(inv["total_value_cents"]))
c[1].metric("COG / Unit", ui.unit_cost(inv["cog_per_unit_cents"]))
c[2].metric("Buildable from parts", ui.units(inv["buildable_units"]))
c[3].metric("Under construction", ui.units(inv["wip_qty"]))
c[4].metric("Complete units", ui.units(inv["finished_qty"]))

st.subheader("Parts (raw materials)")
classes = {(r, 7): "warn" if p["reorder"] else "ok" for r, p in enumerate(inv["parts"])}
ui.table(
    ["Part", "Vendor", "Per Truck", "Price/Unit", "Quantity", "Value", "Reorder Point", "Re-order"],
    [(p["name"], p["vendor"], p["qty_per_unit"], ui.unit_cost(p["unit_cost_cents"]), ui.units(p["qty"]),
      fmt(p["value_cents"]), ui.units(p["reorder_point"]), "REORDER" if p["reorder"] else "OK") for p in inv["parts"]],
    numeric={2, 3, 4, 5, 6}, classes=classes,
)

st.subheader("Inventory by stage")
ui.table(["Stage", "Units", "Value"], [
    ("Raw materials (parts)", "—", fmt(inv["raw_value_cents"])),
    ("Work in process (units under construction)", ui.units(inv["wip_qty"]), fmt(inv["wip_value_cents"])),
    ("Finished goods (complete units ready for sale)", ui.units(inv["finished_qty"]), fmt(inv["finished_value_cents"])),
    ("Total inventory", "", fmt(inv["total_value_cents"])),
], numeric={1, 2})

st.subheader("Build Units")
st.caption("Building moves cost from parts to work in process to finished goods. It is a transfer between "
           "inventory accounts — no revenue or expense is recognised until the units are sold.")
left, right = st.columns(2, gap="large")
with left:
    n_start = st.number_input("Units to start building", min_value=0, step=100, value=0)
    b1, b2 = st.columns(2)
    if b1.button("Start Production (to WIP)"):
        ui.run(lambda: services.start_build(conn, int(n_start)),
               lambda r: f"Started {ui.units(r['units'])} units; {fmt(r['cost_cents'])} of parts moved to work in process.")
    if b2.button("Build Complete Units", type="primary"):
        ui.run(lambda: services.build_units(conn, int(n_start)),
               lambda r: f"Built {ui.units(r['units'])} complete units at a cost of {fmt(r['cost_cents'])}.")
with right:
    n_done = st.number_input("Units under construction to complete", min_value=0, step=100, value=inv["wip_qty"])
    if st.button("Complete Production (WIP to finished)"):
        ui.run(lambda: services.complete_build(conn, int(n_done)),
               lambda r: f"Completed {ui.units(r['units'])} units; {fmt(r['cost_cents'])} moved to finished goods.")

builds = conn.execute("SELECT * FROM build_events ORDER BY id DESC").fetchall()
if builds:
    st.subheader("Build History")
    ui.table(["Date", "Action", "Units", "Cost"],
             [(b["build_date"], b["action"].title(), ui.units(b["units"]), fmt(b["cost_cents"])) for b in builds],
             numeric={2, 3})
