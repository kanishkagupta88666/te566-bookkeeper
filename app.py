"""ENG/TE 566 Computer Program — small-business bookkeeper.

Run with:  streamlit run app.py
"""
import streamlit as st

import ui
from bookkeeper import db

st.set_page_config(page_title="ENG/TE 566 Bookkeeper", page_icon=":material/local_shipping:", layout="wide")
ui.css()
conn = ui.conn()

PAGES = {
    "Main Menu": [
        st.Page("views/dashboard.py", title="Dashboard", url_path="dashboard", default=True),
    ],
    "Reports": [
        st.Page("views/statements.py", title="Financial Statements", url_path="statements"),
        st.Page("views/inventory.py", title="Inventory", url_path="inventory"),
        st.Page("views/general_ledger.py", title="General Ledger & Audit", url_path="ledger"),
    ],
    "Transactions": [
        st.Page("views/invoices.py", title="Create Invoice / History", url_path="invoices"),
        st.Page("views/purchase_orders.py", title="Create PO / History", url_path="purchase-orders"),
        st.Page("views/payroll.py", title="Pay Employee / Payroll", url_path="payroll"),
        st.Page("views/expenses.py", title="Expenses & Bills", url_path="expenses"),
    ],
    "Records": [
        st.Page("views/employees.py", title="Employees", url_path="employees"),
        st.Page("views/customers.py", title="Customers", url_path="customers"),
        st.Page("views/vendors.py", title="Vendors", url_path="vendors"),
    ],
    "Setup": [
        st.Page("views/admin.py", title="Date & Reset Demo", url_path="admin"),
    ],
}

page = st.navigation(PAGES)
with st.sidebar:
    st.markdown(f"**{db.get_setting(conn, 'company_name')}**")
    st.caption(f"Simulation date: {db.get_setting(conn, 'current_date')}")
    if ui.isolated_sessions():
        # keep the workspace id in the URL so a refresh (or a bookmarked link) reopens the same books
        st.query_params["s"] = ui.workspace_id()
        st.info("Live demo: this browser session has its own private set of books. "
                "Use Date & Reset Demo to start over.", icon=":material/lock:")
ui.show_flash()
page.run()
