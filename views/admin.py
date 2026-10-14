"""Simulation clock (Net 30 testing), month-end settlement and demo reset."""
import streamlit as st

import ui
from bookkeeper import db, seed, services
from bookkeeper.money import fmt

conn = ui.conn()
st.title("Date & Reset Demo")
st.caption(f"Current simulation date: {db.get_setting(conn, 'current_date')}")

left, right = st.columns(2, gap="large")
with left:
    st.subheader("Advance the date")
    st.write("Moves the clock forward. Invoices are collected and vendor bills are paid on their Net 30 due "
             "dates; withheld payroll taxes are remitted on the 15th of the following month.")
    days = st.number_input("Days to advance", min_value=1, step=1, value=30)
    if st.button("Advance Date", type="primary"):
        ui.run(lambda: services.advance_date(conn, int(days)), lambda log: "  \n".join(log))
with right:
    st.subheader("Month-end settlement")
    st.write("The guide's monthly rule: post all receivables to cash and pay all bills now, even if 30 days "
             "have not elapsed. Withheld payroll taxes are remitted as well.")
    if st.button("Settle Everything Now"):
        ui.run(lambda: services.month_end_settlement(conn), lambda log: "  \n".join(log))

st.divider()
st.subheader("Reset Demo / Initialize Business")
st.write(ui.plain(
    f"Erases all records and restores the starting position on {seed.START_DATE}: "
    f"{fmt(seed.INITIAL_CASH_CENTS)} cash invested by the owner, plus owner-contributed opening inventory "
    f"({seed.OPENING_FINISHED_UNITS:,} finished trucks and a starting stock of parts), 10 customers, 8 vendors, "
    "1 employee and 10 expense accounts."
))
confirm = st.checkbox("I understand this deletes all transactions")
if st.button("Reset Demo", disabled=not confirm):
    ui.run(lambda: seed.reset_demo(conn), "Demo reset to initial conditions.")
