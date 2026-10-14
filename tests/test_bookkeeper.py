"""Accounting tests: every transaction type, the three assignment transactions, and reconciliation."""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bookkeeper import db, ledger, payroll_tax, reports, seed, services  # noqa: E402
from bookkeeper.money import fmt, to_cents  # noqa: E402
from bookkeeper.services import BusinessError  # noqa: E402


@pytest.fixture
def conn():
    c = db.connect(":memory:")
    seed.reset_demo(c)
    yield c
    c.close()


def bs(conn):
    return reports.balance_sheet(conn)["values"]


def inc(conn):
    return reports.income_statement(conn)["values"]


def assert_reconciled(conn):
    failed = [(name, detail) for name, ok, detail in reports.integrity_checks(conn) if not ok]
    assert not failed, failed


def customer_id(conn, price_cents=250):
    return conn.execute("SELECT id FROM customers WHERE price_cents = ? ORDER BY id", (price_cents,)).fetchone()["id"]


def vendor_id(conn, part):
    return conn.execute(
        "SELECT v.id FROM vendors v JOIN parts p ON p.id = v.part_id WHERE p.name = ?", (part,)
    ).fetchone()["id"]


# --- money -------------------------------------------------------------------
def test_money_helpers():
    assert to_cents("50000") == 5_000_000
    assert to_cents(0.1) + to_cents(0.2) == to_cents(0.3)
    assert to_cents("2.675") == 268  # half-up, not banker's or binary rounding
    assert fmt(123456789) == "$1,234,567.89"
    assert fmt(-500) == "($5.00)"
    with pytest.raises(ValueError):
        to_cents("abc")


# --- initial conditions ------------------------------------------------------
def test_initial_conditions(conn):
    b, i = bs(conn), inc(conn)
    assert b["cash"] == 200_000_00
    assert b["accounts_receivable"] == 0 and b["accounts_payable"] == 0
    assert b["finished_goods"] == 60_000 * 57
    assert b["raw_materials"] == 5_100_00
    assert b["net_worth"] == b["owner_capital"] == 200_000_00 + 34_200_00 + 5_100_00
    assert all(v == 0 for v in i.values())
    assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 10
    assert conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0] == 8
    assert conn.execute("SELECT COUNT(*) FROM expense_accounts").fetchone()[0] == 10
    assert conn.execute("SELECT SUM(annual_budget_cents) FROM expense_accounts").fetchone()[0] == 200_000_00
    assert_reconciled(conn)


def test_bom_cost_per_truck(conn):
    inv = reports.inventory_report(conn)
    assert inv["cog_per_unit_cents"] == 57  # $0.57 from the guide's bill of materials
    assert inv["buildable_units"] == 4_000  # limited by cabs
    assert inv["low_stock"] == ["Cab"]


def test_reset_is_deterministic(conn):
    first = (bs(conn), inc(conn), [tuple(r) for r in ledger.journal(conn)])
    services.create_invoice(conn, customer_id(conn), 100)
    seed.reset_demo(conn)
    assert (bs(conn), inc(conn), [tuple(r) for r in ledger.journal(conn)]) == first


# --- ledger rules ------------------------------------------------------------
def test_unbalanced_entry_rejected(conn):
    before = conn.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0]
    with pytest.raises(ledger.LedgerError):
        ledger.post(conn, "2026-10-01", "bad", "TEST", [(ledger.CASH, 100, 0), (ledger.SALES, 0, 99)])
    assert conn.execute("SELECT COUNT(*) FROM journal_entries").fetchone()[0] == before


def test_duplicate_submission_posts_once(conn):
    cid = customer_id(conn)
    services.create_invoice(conn, cid, 100, idempotency_key="form-1")
    with pytest.raises(ledger.DuplicatePosting):
        services.create_invoice(conn, cid, 100, idempotency_key="form-1")
    assert conn.execute("SELECT COUNT(*) FROM invoices").fetchone()[0] == 1
    assert inc(conn)["sales"] == 250_00
    assert_reconciled(conn)


def test_failed_transaction_rolls_back_everything(conn):
    before = (bs(conn), inc(conn), reports.inventory_report(conn))

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    real_execute = conn.execute
    # fail on the very last statement of create_invoice (the invoice insert)
    class Wrapper:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def execute(self, sql, *params):
            if sql.startswith("INSERT INTO invoices"):
                boom()
            return real_execute(sql, *params)

    with pytest.raises(RuntimeError):
        services.create_invoice(Wrapper(conn), customer_id(conn), 100)
    assert (bs(conn), inc(conn), reports.inventory_report(conn)) == before
    assert_reconciled(conn)


# --- assignment transaction 1: $50,000 sale ---------------------------------
def test_sale_of_50000(conn):
    b0 = bs(conn)
    result = services.create_invoice(conn, customer_id(conn), 20_000)  # 20,000 trucks x $2.50
    b1, i1 = bs(conn), inc(conn)
    assert result["total_cents"] == 50_000_00
    assert i1["sales"] == 50_000_00
    assert i1["cogs"] == 11_400_00
    assert i1["gross_profit"] == 38_600_00
    assert b1["accounts_receivable"] == 50_000_00  # Net 30: a receivable, not cash
    assert b1["cash"] == b0["cash"]
    assert b1["inventory"] == b0["inventory"] - 11_400_00
    assert b1["net_worth"] == b0["net_worth"] + 38_600_00
    assert reports.inventory_report(conn)["finished_qty"] == 40_000
    assert result["due_date"] == date(2026, 10, 31)
    assert_reconciled(conn)


def test_cannot_oversell(conn):
    with pytest.raises(BusinessError):
        services.create_invoice(conn, customer_id(conn), 60_001)
    with pytest.raises(BusinessError):
        services.create_invoice(conn, customer_id(conn), 0)
    assert inc(conn)["sales"] == 0


def test_customer_specific_price(conn):
    result = services.create_invoice(conn, customer_id(conn, 275), 1_000)
    assert result["total_cents"] == 2_750_00


# --- assignment transaction 2: $20,000 inventory purchase -------------------
def test_purchase_of_20000(conn):
    b0, i0 = bs(conn), inc(conn)
    result = services.create_po(conn, vendor_id(conn, "Cab"), 200_000)  # 200,000 cabs x $0.10
    b1 = bs(conn)
    assert result["billed_cents"] == 20_000_00
    assert b1["inventory"] == b0["inventory"] + 20_000_00
    assert b1["accounts_payable"] == 20_000_00  # Net 30: a payable, not cash
    assert b1["cash"] == b0["cash"]
    assert inc(conn) == i0  # buying inventory is not an expense
    assert b1["net_worth"] == b0["net_worth"]
    inv = reports.inventory_report(conn)
    assert next(p for p in inv["parts"] if p["name"] == "Cab")["qty"] == 204_000
    assert inv["low_stock"] == []
    assert_reconciled(conn)


def test_po_received_quantity_and_bill_can_differ(conn):
    po = services.create_po(conn, vendor_id(conn, "Body"), 10_000, receive_now=False)
    assert bs(conn)["accounts_payable"] == 0  # an order alone is not a liability
    services.receive_po(conn, po["id"], qty_received=9_500, billed_cents=to_cents("975.00"))
    row = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po["id"],)).fetchone()
    assert (row["qty_ordered"], row["qty_received"], row["billed_cents"]) == (10_000, 9_500, 975_00)
    assert bs(conn)["accounts_payable"] == 975_00
    with pytest.raises(BusinessError):
        services.receive_po(conn, po["id"])  # cannot receive twice
    assert_reconciled(conn)


# --- assignment transaction 3: one payroll period ---------------------------
def test_paycheck_math():
    check = payroll_tax.compute_paycheck(150_000_00, 12, "single")
    assert check["salary_cents"] == 12_500_00
    assert check["federal_cents"] == 2_061_17  # (24,734.00 annual) / 12
    assert check["social_sec_cents"] == 775_00
    assert check["medicare_cents"] == 181_25
    assert check["state_cents"] == 618_75
    assert check["withholding_cents"] == 3_636_17
    assert check["net_cents"] == 8_863_83
    assert check["net_cents"] + check["withholding_cents"] == check["gross_cents"]


def test_social_security_wage_base_cap():
    check = payroll_tax.compute_paycheck(240_000_00, 12, "single", ytd_gross_cents=180_000_00)
    assert check["social_sec_cents"] == round(4_500_00 * 0.062)  # only $4,500 left under the base


def test_pay_one_period(conn):
    b0 = bs(conn)
    emp = conn.execute("SELECT id FROM employees").fetchone()["id"]
    result = services.pay_employee(conn, emp)
    b1, i1 = bs(conn), inc(conn)
    assert i1["payroll"] == 8_863_83
    assert i1["payroll_withholding"] == 3_636_17
    assert i1["payroll"] + i1["payroll_withholding"] == 12_500_00
    assert b1["cash"] == b0["cash"] - 8_863_83
    assert b1["accruals"] == 3_636_17
    assert b1["net_worth"] == b0["net_worth"] - 12_500_00
    assert result["period"] == "2026-10"
    with pytest.raises(BusinessError):
        services.pay_employee(conn, emp)  # same period cannot be paid twice
    assert conn.execute("SELECT COUNT(*) FROM payroll_events").fetchone()[0] == 1
    assert_reconciled(conn)


# --- the full assignment sequence + Net 30 ----------------------------------
def test_assignment_sequence_then_net30(conn):
    services.create_invoice(conn, customer_id(conn), 20_000)
    services.create_po(conn, vendor_id(conn, "Cab"), 200_000)
    services.pay_employee(conn, conn.execute("SELECT id FROM employees").fetchone()["id"])
    b, i = bs(conn), inc(conn)
    assert i["net_income"] == 50_000_00 - 11_400_00 - 12_500_00
    assert b["cash"] == 200_000_00 - 8_863_83
    assert b["total_assets"] == b["total_liabilities_and_net_worth"]
    assert_reconciled(conn)

    services.advance_date(conn, 29)
    assert bs(conn)["accounts_receivable"] == 50_000_00  # not yet due
    services.advance_date(conn, 1)  # day 30
    b2 = bs(conn)
    assert b2["accounts_receivable"] == 0 and b2["accounts_payable"] == 0
    assert b2["cash"] == 200_000_00 - 8_863_83 + 50_000_00 - 20_000_00
    assert b2["accruals"] == 3_636_17  # withholding is due the 15th of next month
    assert inc(conn) == i  # settling receivables/payables does not touch income
    services.advance_date(conn, 15)  # 2026-11-15
    assert bs(conn)["accruals"] == 0
    cf = reports.cash_flow(conn)["values"]
    assert cf["ending_cash"] == bs(conn)["cash"] == 200_000_00 + 50_000_00 - 20_000_00 - 12_500_00
    assert_reconciled(conn)


def test_month_end_settlement_pays_early(conn):
    services.create_invoice(conn, customer_id(conn), 1_000)
    services.create_po(conn, vendor_id(conn, "Wheels"), 10_000)
    log = services.month_end_settlement(conn)
    assert len(log) == 2
    b = bs(conn)
    assert b["accounts_receivable"] == 0 and b["accounts_payable"] == 0
    assert b["cash"] == 200_000_00 + 2_500_00 - 100_00
    assert_reconciled(conn)


# --- expenses, taxes, manufacturing, guards ---------------------------------
def test_pay_monthly_bill_and_income_tax(conn):
    rent = conn.execute("SELECT id FROM expense_accounts WHERE name = 'Rent'").fetchone()["id"]
    services.pay_expense(conn, rent)
    services.pay_income_tax(conn, 1_000_00)
    i = inc(conn)
    assert i["bills"] == 5_000_00 and i["income_taxes"] == 1_000_00
    assert i["net_income"] == -6_000_00
    assert bs(conn)["cash"] == 194_000_00
    assert_reconciled(conn)


def test_build_units_moves_cost_without_income_effect(conn):
    i0, total0 = inc(conn), bs(conn)["inventory"]
    services.start_build(conn, 1_000)
    inv = reports.inventory_report(conn)
    assert inv["wip_qty"] == 1_000 and inv["wip_value_cents"] == 570_00
    assert next(p for p in inv["parts"] if p["name"] == "Wheels")["qty"] == 72_000
    services.complete_build(conn, 1_000)
    inv = reports.inventory_report(conn)
    assert inv["wip_qty"] == 0 and inv["finished_qty"] == 61_000
    assert inc(conn) == i0 and bs(conn)["inventory"] == total0
    with pytest.raises(BusinessError):
        services.build_units(conn, 3_001)  # only 3,000 cabs left
    assert_reconciled(conn)


def test_weighted_average_cost_keeps_subledger_exact(conn):
    vid = vendor_id(conn, "Cab")
    po = services.create_po(conn, vid, 1_000, receive_now=False)
    services.receive_po(conn, po["id"], qty_received=1_000, billed_cents=133_33)  # odd price
    services.build_units(conn, 4_999)
    services.create_invoice(conn, customer_id(conn), 64_999)
    assert_reconciled(conn)


def test_cannot_overdraw_cash(conn):
    with pytest.raises(BusinessError):
        services.pay_income_tax(conn, 200_000_01)
    assert bs(conn)["cash"] == 200_000_00


def test_master_data_validation(conn):
    with pytest.raises(BusinessError):
        services.add_customer(conn, company="Smith Toy Co.", price_cents=250)  # duplicate
    with pytest.raises(BusinessError):
        services.add_customer(conn, company="  ", price_cents=250)
    with pytest.raises(BusinessError):
        services.add_employee(conn, first_name="A", last_name="B", annual_salary_cents=0)
    new = services.add_customer(conn, company="New Toy Shop", price_cents=300)
    services.update_customer(conn, new, price_cents=310)
    assert conn.execute("SELECT price_cents FROM customers WHERE id = ?", (new,)).fetchone()[0] == 310
    part = services.add_part(conn, "Warning Labels", qty_per_unit=0, reorder_point=100)
    services.add_vendor(conn, company="Warning Labels 4 All", part_id=part, price_cents=2)
    assert conn.execute("SELECT COUNT(*) FROM vendors").fetchone()[0] == 9


def test_data_persists_across_connections(tmp_path):
    path = tmp_path / "books.db"
    c1 = db.connect(path)
    seed.reset_demo(c1)
    services.create_invoice(c1, customer_id(c1), 20_000)
    c1.close()
    c2 = db.connect(path)
    assert inc(c2)["sales"] == 50_000_00
    assert conn_count(c2, "invoices") == 1
    c2.close()


def conn_count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
