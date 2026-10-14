"""The audit trail: every journal entry, the trial balance and ledger-to-subledger reconciliations."""
import streamlit as st

import ui
from bookkeeper import ledger, reports
from bookkeeper.money import fmt

conn = ui.conn()
st.title("General Ledger & Audit")

st.subheader("Reconciliation checks")
checks = reports.integrity_checks(conn)
ui.table(["Check", "Result", "Detail"],
         [(name, "PASS" if ok else "FAIL", detail) for name, ok, detail in checks],
         classes={(r, 1): "ok" if ok else "warn" for r, (_, ok, _) in enumerate(checks)})

st.subheader("Trial Balance")
tb = ledger.trial_balance(conn)
ui.table(["Account", "Name", "Type", "Debit", "Credit"],
         [(code, name, kind.title(), fmt(dr) if dr else "", fmt(cr) if cr else "") for code, name, kind, dr, cr in tb]
         + [("", "Total", "", fmt(sum(r[3] for r in tb)), fmt(sum(r[4] for r in tb)))],
         numeric={3, 4})

st.subheader("Journal (newest first)")
rows, last = [], None
for line in ledger.journal(conn):
    first = line["id"] != last
    last = line["id"]
    rows.append((
        line["id"] if first else "", line["entry_date"] if first else "",
        line["txn_type"].replace("_", " ").title() if first else "", line["description"] if first else "",
        f"{line['account_code']} {line['account_name']}",
        fmt(line["debit_cents"]) if line["debit_cents"] else "", fmt(line["credit_cents"]) if line["credit_cents"] else "",
    ))
ui.table(["Entry", "Date", "Type", "Description", "Account", "Debit", "Credit"], rows, numeric={5, 6})
