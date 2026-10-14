"""View, add and edit employees."""
import streamlit as st

import ui
from bookkeeper import services
from bookkeeper.money import fmt
from bookkeeper.services import BusinessError

conn = ui.conn()
st.title("Employees")

FIELDS = [
    ("first_name", "First name", "text", None),
    ("last_name", "Last name", "text", None),
    ("address1", "Address 1", "text", None),
    ("address2", "Address 2", "text", None),
    ("city", "City", "text", None),
    ("state", "State", "text", None),
    ("zip", "ZIP code", "text", None),
    ("ssn_last4", "SSN (last 4 digits only)", "text", None),
    ("filing_status", "Federal filing status", "select", {"Single": "single", "Married filing jointly": "married"}),
    ("dependents", "Dependents (withholdings)", "int", None),
    ("annual_salary_cents", "Annual salary ($)", "money", None),
    ("pay_periods", "Pay periods per year", "select", {"12 (monthly)": 12, "24 (semi-monthly)": 24,
                                                       "26 (bi-weekly)": 26, "52 (weekly)": 52}),
    ("active", "Status", "select", {"Active": 1, "Inactive": 0}),
]

rows = conn.execute("SELECT * FROM employees ORDER BY id").fetchall()
ui.table(
    ["ID", "First Name", "Last Name", "Address 1", "Address 2", "City", "State", "ZIP", "SSN", "Filing", "Dependents",
     "Salary", "Pay Periods", "Status"],
    [(r["id"], r["first_name"], r["last_name"], r["address1"], r["address2"], r["city"], r["state"], r["zip"],
      f"***-**-{r['ssn_last4']}" if r["ssn_last4"] else "", r["filing_status"].title(), r["dependents"],
      fmt(r["annual_salary_cents"]), r["pay_periods"], "Active" if r["active"] else "Inactive") for r in rows],
    numeric={11},
)

add_tab, edit_tab = st.tabs(["Add Employee", "Edit Employee"])
with add_tab:
    data = ui.record_form("add_employee", FIELDS, submit_label="Add Employee")
    if data:
        ui.run(lambda: services.add_employee(conn, **data), f"Added employee {data['first_name']} {data['last_name']}.")
with edit_tab:
    if rows:
        by_label = {f"{r['id']} — {r['first_name']} {r['last_name']}": r for r in rows}
        current = by_label[st.selectbox("Employee to edit", list(by_label))]
        data = ui.record_form(f"edit_employee_{current['id']}", FIELDS, initial=dict(current),
                              submit_label="Save Changes")
        if data:
            ui.run(lambda: services.update_employee(conn, current["id"], **data), "Employee updated.")
