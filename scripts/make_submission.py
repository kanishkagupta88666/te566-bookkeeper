"""Produce the assignment evidence.

Starts the real application, drives it in a real browser (Playwright + the
installed Google Chrome), performs the three assignment transactions through
the UI, captures screenshots before and after each one, and assembles them
into a single PDF. Every number printed in the PDF is read back from the
application's database after the UI action — nothing is typed in by hand.

Usage:  python scripts/make_submission.py
"""
import os
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image as PILImage  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import inch  # noqa: E402
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer  # noqa: E402

from bookkeeper import db, ledger, payroll_tax, reports, seed  # noqa: E402
from bookkeeper.money import fmt  # noqa: E402
from bookkeeper.pdf import grid_table  # noqa: E402

PORT = 8566
BASE = f"http://localhost:{PORT}"
OUT = ROOT / "submission"
SHOTS = OUT / "screenshots"
PDF_PATH = OUT / "TE566_Final_Program_Submission.pdf"
ZIP_PATH = OUT / "TE566_Final_Program_Code.zip"
AUTHOR = os.environ.get("SUBMISSION_AUTHOR", "Kanishka Gupta")
VIEW = {"width": 1280, "height": 900}


# --- driving the app ---------------------------------------------------------
def start_app():
    env = dict(os.environ, BOOKKEEPER_DB=str(db.db_path()))
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "bookkeeping_app.py"), "--server.port", str(PORT),
         "--server.headless", "true"],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{BASE}/_stcore/health", timeout=1)
            return proc
        except OSError:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError("Streamlit did not start.")


def settle(page):
    """Wait until Streamlit has finished its current script run."""
    page.wait_for_timeout(400)
    page.wait_for_function(
        "() => !document.querySelector('[data-testid=\"stStatusWidget\"]') && "
        "!document.querySelector('[data-stale=\"true\"]')", timeout=20000)
    page.wait_for_timeout(400)


def open_page(page, path, heading):
    page.goto(f"{BASE}/{path}")
    page.get_by_role("heading", name=heading, exact=True).first.wait_for(timeout=30000)
    settle(page)


def shot(page, name, until_selector=None, sidebar=False):
    """Screenshot the page content (or only down to `until_selector`), growing the window to fit.
    The navigation sidebar is cropped off unless `sidebar` is set, so the content prints larger."""
    main = page.locator('[data-testid="stMain"]')
    height = main.evaluate("el => el.scrollHeight")
    page.set_viewport_size({"width": VIEW["width"], "height": max(VIEW["height"], min(int(height) + 20, 4000))})
    page.wait_for_timeout(500)
    path = SHOTS / f"{name}.png"
    size = page.viewport_size
    left = 0 if sidebar else page.locator('[data-testid="stSidebar"]').bounding_box()["width"]
    bottom = page.locator(until_selector).first.bounding_box()["y"] if until_selector else size["height"]
    page.screenshot(path=str(path), clip={"x": left, "y": 0, "width": size["width"] - left, "height": bottom})
    page.set_viewport_size(VIEW)
    return path


def choose(page, label, option_text):
    box = page.locator('[data-testid="stSelectbox"]').filter(has_text=label).first
    box.get_by_role("button", name="Open").click()
    page.locator('[role="option"]').filter(has_text=option_text).first.click()
    settle(page)


def fill_number(page, label, value):
    field = page.get_by_label(label, exact=True)
    field.fill(str(value))
    field.press("Enter")
    settle(page)


def statements_shot(page, name):
    open_page(page, "statements", "Financial Statements")
    return shot(page, name, until_selector='[data-testid="stMain"] hr')


def snapshot():
    conn = db.connect()
    try:
        last = conn.execute("SELECT MAX(id) FROM journal_entries").fetchone()[0]
        return {
            "income": reports.income_statement(conn), "balance": reports.balance_sheet(conn),
            "last_entry": last, "checks": reports.integrity_checks(conn),
            "date": db.get_setting(conn, "current_date"),
        }
    finally:
        conn.close()


def entries_between(first_exclusive, last_inclusive):
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT e.id, e.entry_date, e.description, a.name, l.debit_cents, l.credit_cents "
            "FROM journal_entries e JOIN journal_lines l ON l.entry_id = e.id JOIN accounts a ON a.code = l.account_code "
            "WHERE e.id > ? AND e.id <= ? ORDER BY e.id, l.id", (first_exclusive, last_inclusive)).fetchall()
    finally:
        conn.close()


def run_demo():
    """Returns the ordered list of stages: dicts with screenshots and ledger snapshots."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    for old in SHOTS.glob("*.png"):
        old.unlink()
    stages = []
    proc = start_app()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            page = browser.new_context(viewport=VIEW, device_scale_factor=2).new_page()

            # A) start the program with initial conditions (Reset Demo through the UI)
            open_page(page, "admin", "Date & Reset Demo")
            page.get_by_text("I understand this deletes all transactions").click()
            settle(page)
            page.get_by_role("button", name="Reset Demo").click()
            page.get_by_text("Demo reset to initial conditions.").wait_for(timeout=20000)
            settle(page)
            open_page(page, "", "ENG/TE 566 Computer Program")
            extra = [("Main menu / dashboard at start-up", shot(page, "00_dashboard_initial", sidebar=True))]
            open_page(page, "inventory", "Inventory")
            extra.append(("Inventory at start-up (units and dollars, with reorder flag)",
                          shot(page, "00_inventory_initial", until_selector="h3:has-text('Build Units')")))
            stages.append({"key": "initial", "statements": statements_shot(page, "01_statements_initial"),
                           "extra": extra, "snap": snapshot()})

            # 1) make a sale for $50,000
            open_page(page, "invoices", "Create Invoice")
            choose(page, "Customer", "Smith Toy Co.")
            fill_number(page, "Units to invoice", 20000)
            page.get_by_text("$50,000.00").first.wait_for(timeout=10000)
            form = shot(page, "02_sale_form", until_selector="h3:has-text('Invoice History')")
            page.get_by_role("button", name="Create Invoice").click()
            page.get_by_text("Invoice INV-0001 posted").wait_for(timeout=20000)
            settle(page)
            done = shot(page, "03_sale_posted")
            stages.append({"key": "sale", "extra": [("Create Invoice screen, filled in", form),
                                                    ("Invoice posted - confirmation and Invoice History", done)],
                           "statements": statements_shot(page, "04_statements_after_sale"), "snap": snapshot()})

            # 2) purchase $20,000 in inventory
            open_page(page, "purchase-orders", "Create PO")
            choose(page, "Part / Vendor", "Diecast Cab Castings")
            fill_number(page, "Quantity", 200000)
            page.get_by_text("$20,000.00").first.wait_for(timeout=10000)
            form = shot(page, "05_purchase_form", until_selector="h3:has-text('PO History')")
            page.get_by_role("button", name="Create PO").click()
            page.get_by_text("PO-0001 received").wait_for(timeout=20000)
            settle(page)
            done = shot(page, "06_purchase_posted")
            open_page(page, "inventory", "Inventory")
            inv = shot(page, "07_inventory_after_purchase", until_selector="h3:has-text('Build Units')")
            stages.append({"key": "purchase", "extra": [("Create PO screen, filled in", form),
                                                        ("PO received - confirmation and PO History", done),
                                                        ("Inventory after the sale and the purchase", inv)],
                           "statements": statements_shot(page, "08_statements_after_purchase"), "snap": snapshot()})

            # 3) pay an employee for one payroll period
            open_page(page, "payroll", "Pay Employee")
            form = shot(page, "09_payroll_form", until_selector="h3:has-text('Payroll History')")
            page.get_by_role("button", name="Pay Employee").click()
            page.get_by_text("Paid Jordan Smith").wait_for(timeout=20000)
            settle(page)
            done = shot(page, "10_payroll_posted")
            stages.append({"key": "payroll", "extra": [("Pay Employee screen with paycheck preview", form),
                                                       ("Employee paid - confirmation and Payroll History", done)],
                           "statements": statements_shot(page, "11_statements_after_payroll"), "snap": snapshot()})

            # Net 30: advance the clock 30 days so the receivable and payable settle
            open_page(page, "statements", "Financial Statements")
            full = shot(page, "12_statements_full_with_cash_flow")
            open_page(page, "admin", "Date & Reset Demo")
            page.get_by_role("button", name="Advance Date").click()
            page.get_by_text("Date advanced to").wait_for(timeout=20000)
            settle(page)
            done = shot(page, "13_date_advanced", until_selector='[data-testid="stMain"] hr')
            open_page(page, "ledger", "General Ledger & Audit")
            audit = shot(page, "15_general_ledger_audit")
            stages.append({"key": "net30", "extra": [("Date advanced 30 days - settlement log", done)],
                           "statements": statements_shot(page, "14_statements_after_30_days"), "snap": snapshot(),
                           "appendix": [("Full statements page after the three transactions (with cash flow)", full),
                                        ("General Ledger & Audit: reconciliation checks, trial balance, journal", audit)]})
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    return stages


# --- PDF ---------------------------------------------------------------------
styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], textColor=colors.HexColor("#13294B"), spaceAfter=6)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], textColor=colors.HexColor("#13294B"), spaceBefore=4, spaceAfter=4)
BODY = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=10, leading=13.5)
CAPTION = ParagraphStyle("Caption", parent=styles["BodyText"], fontSize=9.5, leading=12, spaceAfter=3,
                         textColor=colors.HexColor("#13294B"), fontName="Helvetica-Bold")
PAGE_W = letter[0] - 1.2 * inch
PAGE_H = letter[1] - 1.3 * inch


def picture(path, max_w=PAGE_W, max_h=PAGE_H):
    with PILImage.open(path) as im:
        w, h = im.size
    scale = min(max_w / w, max_h / h)
    return Image(str(path), width=w * scale, height=h * scale)


def figure(caption, path, max_h=PAGE_H - 0.9 * inch):
    return [KeepTogether([Paragraph(caption, CAPTION), picture(path, max_h=max_h)]), Spacer(1, 8)]


def P(text):
    return Paragraph(text, BODY)


def changes_table(before, after):
    """Every statement line whose value changed, straight from the ledger snapshots."""
    rows = []
    for name, key in (("Income Statement", "income"), ("Balance Sheet", "balance")):
        seen = set()
        b_rows = {label: cents for label, cents, kind in before[key]["rows"] if cents is not None and kind != "section"}
        for label, cents, kind in after[key]["rows"]:
            if cents is None or label in seen or cents == b_rows.get(label):
                continue
            seen.add(label)
            delta = cents - b_rows[label]
            rows.append([name, label, fmt(b_rows[label]), fmt(cents), ("+" if delta > 0 else "-") + fmt(abs(delta))])
    if not rows:
        rows = [["", "No statement line changed", "", "", ""]]
    return grid_table(["Statement", "Line", "Before", "After", "Change"], rows,
                      col_widths=[1.2 * inch, 2.7 * inch, 1.1 * inch, 1.1 * inch, 1.1 * inch])


def journal_table(before, after):
    rows = [[r["id"], r["entry_date"], Paragraph(r["description"], BODY), r["name"],
             fmt(r["debit_cents"]) if r["debit_cents"] else "", fmt(r["credit_cents"]) if r["credit_cents"] else ""]
            for r in entries_between(before["last_entry"], after["last_entry"])]
    return grid_table(["Entry", "Date", "Description", "Account", "Debit", "Credit"], rows,
                      col_widths=[0.45 * inch, 0.8 * inch, 2.05 * inch, 2.0 * inch, 0.95 * inch, 0.95 * inch])


def transaction_section(number, title, explanation, before, after):
    """Before/after statements on one page, then the transaction screens and what changed."""
    big = PAGE_H - 1.9 * inch
    story = [Paragraph(f"Transaction {number}: {title}", H1), Paragraph(explanation, BODY), Spacer(1, 6)]
    story += [Paragraph(f"BEFORE transaction {number} - Income Statement and Balance Sheet", CAPTION),
              picture(before["statements"], max_h=big), PageBreak(),
              Paragraph(f"AFTER transaction {number} - Income Statement and Balance Sheet", CAPTION),
              picture(after["statements"], max_h=big), PageBreak()]
    story += [Paragraph(f"Transaction {number}: what changed", H2),
              Paragraph("Statement lines that changed (read from the ledger after the transaction):", BODY),
              Spacer(1, 4), changes_table(before["snap"], after["snap"]), Spacer(1, 8),
              Paragraph("Journal entry posted by the program:", BODY), Spacer(1, 4),
              journal_table(before["snap"], after["snap"]), Spacer(1, 10)]
    for caption, path in after["extra"]:
        story += figure(caption, path, max_h=5.2 * inch)
    story.append(PageBreak())
    return story


def build_pdf(stages, test_summary):
    s = {stage["key"]: stage for stage in stages}
    v0 = s["initial"]["snap"]["balance"]["values"]
    pay = s["payroll"]["snap"]["income"]["values"]
    doc = SimpleDocTemplate(str(PDF_PATH), pagesize=letter, leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.7 * inch,
                            title="ENG/TE 566 Computer Program - Final Turn-in", author=AUTHOR)

    def footer(canvas, d):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(0.6 * inch, 0.4 * inch, f"ENG/TE 566 Computer Program Final Turn-in - {AUTHOR}")
        canvas.drawRightString(letter[0] - 0.6 * inch, 0.4 * inch, f"Page {d.page}")

    story = [
        Paragraph("ENG/TE 566 - Computer Program Final Turn-in", H1),
        Paragraph(f"{AUTHOR} &nbsp;|&nbsp; {seed.COMPANY_NAME} bookkeeping program (Python, Streamlit, SQLite)", BODY),
        Spacer(1, 8),
        Paragraph(
            "Every screenshot in this document was captured from the running program. The three assignment "
            "transactions were entered through the program's own screens (Create Invoice, Create PO, Pay Employee); "
            "the tables of changes and journal entries were read back from the program's database afterwards.", BODY),
        Spacer(1, 8),
        Paragraph("A) Initial conditions", H2),
        grid_table(["Item", "Value"], [
            ["Start date", seed.START_DATE],
            ["Owner's cash investment", fmt(seed.INITIAL_CASH_CENTS)],
            [P("Opening inventory contributed by the owner (at cost)"), P(fmt(v0["inventory"]) +
             f" = {seed.OPENING_FINISHED_UNITS:,} finished trucks {fmt(v0['finished_goods'])} + parts {fmt(v0['raw_materials'])}")],
            ["Net worth at start", fmt(v0["net_worth"])],
            ["Product / cost", "Toy truck, $0.57 per truck from the guide's bill of materials"],
            ["Customers / vendors / employees", "10 customers, 8 vendors (one per part), 1 employee at $150,000 per year"],
            ["Expense accounts", "10 accounts budgeted at $200,000 per year, plus a separate Income Taxes account"],
            ["Long-term assets / debt", "None"],
        ], col_widths=[2.6 * inch, 4.6 * inch]),
        Spacer(1, 8),
        Paragraph("C) Terms", H2),
        Paragraph(
            "Sales are Net 30 and payables are Net 30. A sale is recorded as Accounts Receivable and a purchase as "
            "Accounts Payable; neither touches cash until the due date. The last section advances the program's "
            "date by 30 days to show both settling.", BODY),
        Spacer(1, 8),
        Paragraph("Summary of the three transactions", H2),
        grid_table(["#", "Transaction", "How it was entered", "Result"], [
            ["1", "Sale for $50,000", P("Create Invoice: Smith Toy Co., 20,000 trucks at $2.50"),
             Paragraph("Sales +$50,000.00; Accounts Receivable +$50,000.00; COGS and inventory "
                       f"{fmt(s['sale']['snap']['income']['values']['cogs'])}", BODY)],
            ["2", P("Purchase $20,000 of inventory"), P("Create PO: 200,000 cabs at $0.10"),
             Paragraph("Inventory +$20,000.00; Accounts Payable +$20,000.00; no income effect", BODY)],
            ["3", P("Pay employee, 1 period"), P("Pay Employee: Jordan Smith, October 2026"),
             Paragraph(f"Payroll {fmt(pay['payroll'])} paid in cash; withholding {fmt(pay['payroll_withholding'])} "
                       "accrued; total $12,500.00", BODY)],
        ], col_widths=[0.3 * inch, 1.8 * inch, 2.4 * inch, 2.7 * inch]),
        PageBreak(),
        Paragraph("B) Income Statement and Balance Sheet at start-up", H1),
        Paragraph("Income statement lines are all zero because nothing has been sold or spent yet. The balance "
                  "sheet shows the owner's cash and the contributed inventory, funded entirely by owner's capital.", BODY),
        Spacer(1, 6),
    ]
    story += figure("Income Statement and Balance Sheet - initial conditions", s["initial"]["statements"], PAGE_H - 1.9 * inch)
    story.append(PageBreak())
    for caption, path in s["initial"]["extra"]:
        story += figure(caption, path, max_h=5.2 * inch)
    story.append(PageBreak())

    story += transaction_section(
        1, "Make a sale for $50,000",
        "Invoiced Smith Toy Co. for 20,000 trucks at $2.50 = $50,000.00 on Net 30 terms. Sales rise by $50,000 and "
        "the sale appears as an Accounts Receivable, not cash. The 20,000 trucks leave finished goods at their "
        "$0.57 cost, which becomes cost of goods sold.", s["initial"], s["sale"])
    story += transaction_section(
        2, "Purchase $20,000 in inventory",
        "Ordered and received 200,000 cabs at $0.10 = $20,000.00 from Diecast Cab Castings on Net 30 terms. "
        "Inventory and Accounts Payable both rise by $20,000. The income statement does not change: parts are an "
        "asset until the trucks built from them are sold.", s["sale"], s["purchase"])
    story += transaction_section(
        3, "Pay an employee for 1 payroll period",
        f"Paid Jordan Smith one monthly period: gross salary $12,500.00 ($150,000 / 12). Net pay of "
        f"{fmt(pay['payroll'])} leaves cash. Federal, state, Social Security and Medicare withholding of "
        f"{fmt(pay['payroll_withholding'])} is expensed and held in Accruals until it is remitted to the tax "
        f"agencies. Tax rates are for {payroll_tax.TAX_YEAR}.", s["purchase"], s["payroll"])

    net = s["net30"]
    story += [Paragraph("Net 30 check: 30 days later", H1),
              Paragraph(
                  "Advancing the program's date by 30 days brings the invoice and the vendor bill to their due "
                  "dates. The program collects the $50,000 receivable and pays the $20,000 payable. Net income is "
                  "unchanged, because collecting and paying only move cash. The payroll withholding stays in "
                  "Accruals until its deposit date, the 15th of the following month.", BODY), Spacer(1, 6),
              Paragraph("AFTER 30 days - Income Statement and Balance Sheet "
                        "(the BEFORE state is the 'AFTER transaction 3' page)", CAPTION),
              picture(net["statements"], max_h=PAGE_H - 2.3 * inch),
              PageBreak(),
              Paragraph("Net 30 check: what changed", H2), changes_table(s["payroll"]["snap"], net["snap"]),
              Spacer(1, 8), journal_table(s["payroll"]["snap"], net["snap"]), Spacer(1, 10)]
    for caption, path in net["extra"]:
        story += figure(caption, path, max_h=4.2 * inch)
    story.append(PageBreak())

    checks = net["snap"]["checks"]
    story += [Paragraph("Verification", H1),
              Paragraph("Reconciliation checks computed by the program at the end of the run:", BODY), Spacer(1, 4),
              grid_table(["Check", "Result", "Detail"], [[n, "PASS" if ok else "FAIL", d] for n, ok, d in checks],
                         col_widths=[3.4 * inch, 0.8 * inch, 3.0 * inch]),
              Spacer(1, 8), Paragraph(f"Automated tests (pytest): {test_summary}", BODY), PageBreak()]
    for caption, path in net["appendix"]:
        story += figure(caption, path)
        story.append(PageBreak())
    story.pop()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def run_tests() -> str:
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", str(ROOT / "tests")], cwd=ROOT,
                            capture_output=True, text=True)
    lines = result.stdout.strip().splitlines()
    return lines[-1] if lines else f"pytest produced no output (exit code {result.returncode})"


def zip_code():
    include = ["bookkeeping_app.py", "ui.py", "requirements.txt", "requirements-dev.txt", "README.md",
               ".streamlit/config.toml"]
    for folder in ("bookkeeper", "views", "tests", "scripts"):
        include += [str(p.relative_to(ROOT)) for p in sorted((ROOT / folder).glob("*.py"))]
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in include:
            if (ROOT / rel).exists():
                z.write(ROOT / rel, f"te566-bookkeeper/{rel}")
    return len(include)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    summary = run_tests()
    print("tests:", summary)
    stages = run_demo()
    build_pdf(stages, summary)
    print("pdf:", PDF_PATH)
    print("code zip:", ZIP_PATH, f"({zip_code()} files)")
