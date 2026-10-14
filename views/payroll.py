"""Pay Employee and Payroll History."""
import streamlit as st

import ui
from bookkeeper import payroll_tax, services
from bookkeeper.money import fmt, to_cents

conn = ui.conn()
st.title("Pay Employee")

employees = conn.execute("SELECT * FROM employees WHERE active = 1 ORDER BY last_name, first_name").fetchall()
if not employees:
    st.warning("Add an employee first.")
    st.stop()
by_label = {f"{e['last_name']}, {e['first_name']} — {fmt(e['annual_salary_cents'])}/yr": e for e in employees}

left, right = st.columns([1, 1], gap="large")
with left:
    employee = by_label[st.selectbox("Employee", list(by_label))]
    bonus = st.number_input("Bonus ($, optional)", min_value=0.0, step=100.0, format="%.2f", value=0.0)
    if st.button("Pay Employee", type="primary"):
        ui.run(
            lambda: services.pay_employee(conn, employee["id"], to_cents(bonus), ui.form_token("payroll")),
            lambda r: (f"Paid {r['employee']} for {r['period']}: net pay {fmt(r['net_cents'])}, "
                       f"withholding {fmt(r['withholding_cents'])}."),
            token="payroll",
        )
with right:
    check = services.preview_paycheck(conn, employee["id"], to_cents(bonus))
    st.markdown(f"**Paycheck preview** — 1 of {employee['pay_periods']} pay periods, tax year {payroll_tax.TAX_YEAR}")
    ui.table(["Item", "Amount"], [
        ("Salary", fmt(check["salary_cents"])),
        ("Bonus", fmt(check["bonus_cents"])),
        ("Federal Tax Withheld", fmt(check["federal_cents"])),
        (f"State Tax Withheld ({payroll_tax.STATE_RATE:.2%})", fmt(check["state_cents"])),
        (f"Social Security ({payroll_tax.SOCIAL_SECURITY_RATE:.2%})", fmt(check["social_sec_cents"])),
        (f"Medicare ({payroll_tax.MEDICARE_RATE:.2%})", fmt(check["medicare_cents"])),
        ("Total Withholding", fmt(check["withholding_cents"])),
        ("Amount Paid (Net Pay)", fmt(check["net_cents"])),
    ], numeric={1})

st.subheader("Payroll History")
rows = conn.execute(
    "SELECT p.*, e.first_name, e.last_name FROM payroll_events p JOIN employees e ON e.id = p.employee_id "
    "ORDER BY p.id DESC"
).fetchall()
ui.table(
    ["Date Paid", "Period", "Employee", "Salary", "Bonus", "Federal", "State", "Social Security", "Medicare",
     "Withholding", "Disbursement", "Taxes Remitted"],
    [(r["pay_date"], r["period"], f"{r['first_name']} {r['last_name']}", fmt(r["salary_cents"]), fmt(r["bonus_cents"]),
      fmt(r["federal_cents"]), fmt(r["state_cents"]), fmt(r["social_sec_cents"]), fmt(r["medicare_cents"]),
      fmt(r["withholding_cents"]), fmt(r["net_cents"]), r["remitted_date"] or "Accrued") for r in rows],
    numeric=set(range(3, 11)), empty="No payroll events yet.",
)
if rows:
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Disbursement", fmt(sum(r["net_cents"] for r in rows)))
    c2.metric("Total Withholding", fmt(sum(r["withholding_cents"] for r in rows)))
    owed = sum(r["withholding_cents"] for r in rows if not r["remitted_date"])
    c3.metric("Withholding not yet remitted", fmt(owed))
    if owed and st.button("Remit withheld taxes now"):
        ui.run(lambda: services.remit_payroll_taxes(conn), lambda amount: f"Remitted {fmt(amount)} to tax agencies.")
