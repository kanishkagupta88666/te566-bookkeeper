"""Income Statement, Balance Sheet and Cash Flow — always computed from the ledger."""
import streamlit as st

import ui
from bookkeeper import db, pdf, reports

conn = ui.conn()
company = db.get_setting(conn, "company_name")
as_of = db.get_setting(conn, "current_date")
start = db.get_setting(conn, "start_date")

st.title("Financial Statements")
st.caption(f"{company} · as of {as_of}")

left, right = st.columns(2, gap="large")
with left:
    ui.statement(reports.income_statement(conn), f"{start} to {as_of}")
with right:
    ui.statement(reports.balance_sheet(conn), f"as of {as_of}")

st.divider()
left, right = st.columns(2, gap="large")
with left:
    ui.statement(reports.cash_flow(conn), f"{start} to {as_of}")
with right:
    st.subheader("Print")
    st.write("Download a printable copy of the income statement, balance sheet, cash flow and inventory.")
    st.download_button(
        "Download printable statements (PDF)", data=pdf.financial_statements_pdf(conn),
        file_name=f"financial-statements-{as_of}.pdf", mime="application/pdf", type="primary",
    )
    checks = reports.integrity_checks(conn)
    if all(ok for _, ok, _ in checks):
        st.success(f"Books reconcile: all {len(checks)} ledger checks pass.")
    else:
        st.error("Books do not reconcile — see General Ledger & Audit.")
