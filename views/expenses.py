"""Expense accounts, paying monthly bills, paid-expense history and the separate income tax account."""
import streamlit as st

import ui
from bookkeeper import reports, services
from bookkeeper.money import fmt, to_cents

conn = ui.conn()
st.title("Expenses & Bills")

summary = reports.expense_summary(conn)
st.subheader("Expense Accounts")
ui.table(
    ["Expense Account", "Annual Budget", "Monthly Bill", "Paid to Date"],
    [(e["name"], fmt(e["annual_budget_cents"]), fmt(e["monthly_cents"]), fmt(e["paid_cents"])) for e in summary]
    + [("Total", fmt(sum(e["annual_budget_cents"] for e in summary)), fmt(sum(e["monthly_cents"] for e in summary)),
        fmt(sum(e["paid_cents"] for e in summary)))],
    numeric={1, 2, 3},
)

left, right = st.columns(2, gap="large")
with left:
    st.subheader("Pay a Monthly Bill")
    by_label = {f"{e['name']} — {fmt(e['monthly_cents'])}": e for e in summary}
    account = by_label[st.selectbox("Expense account", list(by_label))]
    amount = st.number_input("Amount ($)", min_value=0.0, step=0.01, format="%.2f",
                             value=account["monthly_cents"] / 100, key=f"bill_{account['id']}")
    if st.button("Pay Bill", type="primary"):
        ui.run(lambda: services.pay_expense(conn, account["id"], to_cents(amount), ui.form_token("bill")),
               lambda r: f"Paid {fmt(r['amount_cents'])} for {r['name']}.", token="bill")
with right:
    st.subheader("Pay Income Taxes")
    st.caption("Income taxes are tracked in their own account, separate from operating expenses.")
    tax = st.number_input("Income tax payment ($)", min_value=0.0, step=100.0, format="%.2f", value=0.0)
    if st.button("Pay Income Tax"):
        ui.run(lambda: services.pay_income_tax(conn, to_cents(tax), ui.form_token("tax")),
               lambda r: f"Paid {fmt(r['amount_cents'])} of income taxes.", token="tax")

st.subheader("Paid Expenses")
rows = conn.execute("SELECT * FROM expense_payments ORDER BY id DESC").fetchall()
ui.table(["Date Paid", "Expense", "Amount"], [(r["pay_date"], r["description"], fmt(r["amount_cents"])) for r in rows],
         numeric={2}, empty="No expenses paid yet.")
