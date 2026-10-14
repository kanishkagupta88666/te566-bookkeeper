"""Check a running deployment in a real browser.

Opens two independent visitors, runs the three assignment transactions as visitor A through the
app's own screens, and confirms that (1) A's statements show the expected figures, (2) a page
refresh keeps A's books, (3) visitor B's books are untouched, and (4) Reset Demo restores A.

Usage:  python scripts/verify_deployment.py https://<your-app>.streamlit.app
        python scripts/verify_deployment.py http://localhost:8501
"""
import sys

from playwright.sync_api import sync_playwright

TIMEOUT = 90_000


def app_frame(page):
    """Streamlit Community Cloud serves the app inside an iframe; locally it is the page itself."""
    page.wait_for_load_state("domcontentloaded")
    for _ in range(int(TIMEOUT / 1000)):
        wake = page.get_by_role("button", name="Yes, get this app back up!")
        if wake.count():
            wake.first.click()
        for frame in page.frames:
            try:
                if frame.locator('[data-testid="stSidebar"]').count():
                    return frame
            except Exception:
                pass
        page.wait_for_timeout(1000)
    raise RuntimeError("The Streamlit app did not load (is the URL right, or is a login required?).")


def settle(frame):
    frame.page.wait_for_timeout(500)
    frame.wait_for_function(
        "() => !document.querySelector('[data-testid=\"stStatusWidget\"]') && "
        "!document.querySelector('[data-stale=\"true\"]')", timeout=TIMEOUT)
    frame.page.wait_for_timeout(400)


def go(frame, link, heading):
    frame.locator('[data-testid="stSidebar"]').get_by_role("link", name=link, exact=True).click()
    frame.get_by_role("heading", name=heading, exact=True).first.wait_for(timeout=TIMEOUT)
    settle(frame)


def choose(frame, label, option):
    box = frame.locator('[data-testid="stSelectbox"]').filter(has_text=label).first
    box.get_by_role("button", name="Open").click()
    frame.locator('[role="option"]').filter(has_text=option).first.click()
    settle(frame)


def fill(frame, label, value):
    field = frame.get_by_label(label, exact=True)
    field.fill(str(value))
    field.press("Enter")
    settle(frame)


def statement_values(frame):
    """{line label: amount text} read from the two statement tables on screen."""
    go(frame, "Financial Statements", "Financial Statements")
    rows = frame.locator("table.stmt tr").evaluate_all(
        "rs => rs.map(r => [...r.querySelectorAll('td')].map(td => td.innerText.trim()))")
    return {r[0]: r[1] for r in rows if len(r) == 2}


def expect(results, name, actual, wanted):
    ok = actual == wanted
    results.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: {actual}" + ("" if ok else f"  (expected {wanted})"))


def main(base):
    results = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        page_a = browser.new_context(viewport={"width": 1280, "height": 1000}).new_page()
        page_b = browser.new_context(viewport={"width": 1280, "height": 1000}).new_page()
        page_a.goto(base, timeout=TIMEOUT)
        page_b.goto(base, timeout=TIMEOUT)
        a, b = app_frame(page_a), app_frame(page_b)
        settle(a), settle(b)
        print(f"Loaded {base}")

        print("Visitor A: start from initial conditions")
        go(a, "Date & Reset Demo", "Date & Reset Demo")
        a.get_by_text("I understand this deletes all transactions").click()
        settle(a)
        a.get_by_role("button", name="Reset Demo").click()
        a.get_by_text("Demo reset to initial conditions.").wait_for(timeout=TIMEOUT)
        v = statement_values(a)
        expect(results, "Cash at start", v["Cash"], "$200,000.00")
        expect(results, "Sales at start", v["Sales"], "$0.00")

        print("Visitor A: 1) sale for $50,000")
        go(a, "Create Invoice / History", "Create Invoice")
        choose(a, "Customer", "Smith Toy Co.")
        fill(a, "Units to invoice", 20000)
        a.get_by_role("button", name="Create Invoice").click()
        a.get_by_text("Invoice INV-0001 posted").wait_for(timeout=TIMEOUT)
        v = statement_values(a)
        expect(results, "Sales", v["Sales"], "$50,000.00")
        expect(results, "Accounts Receivable", v["Accounts Receivable"], "$50,000.00")

        print("Visitor A: 2) purchase $20,000 of inventory")
        go(a, "Create PO / History", "Create PO")
        choose(a, "Part / Vendor", "Diecast Cab Castings")
        fill(a, "Quantity", 200000)
        a.get_by_role("button", name="Create PO").click()
        a.get_by_text("PO-0001 received").wait_for(timeout=TIMEOUT)
        v = statement_values(a)
        expect(results, "Accounts Payable", v["Accounts Payable"], "$20,000.00")
        expect(results, "Inventory", v["Inventory"], "$47,900.00")

        print("Visitor A: 3) pay employee for one period")
        go(a, "Pay Employee / Payroll", "Pay Employee")
        a.get_by_role("button", name="Pay Employee").click()
        a.get_by_text("Paid Jordan Smith").wait_for(timeout=TIMEOUT)
        v = statement_values(a)
        expect(results, "Total Expenses", v["Total Expenses"], "$12,500.00")
        expect(results, "Net Income", v["Net Income"], "$26,100.00")
        expect(results, "Balance sheet balances", v["Total Assets"], v["Total Liabilities & Net Worth"])

        print("Visitor A: refresh the browser")
        page_a.reload(timeout=TIMEOUT)
        a = app_frame(page_a)
        settle(a)
        expect(results, "Net Income after refresh", statement_values(a)["Net Income"], "$26,100.00")

        print("Visitor B: books must be untouched by visitor A")
        v = statement_values(b)
        expect(results, "Visitor B sales", v["Sales"], "$0.00")
        expect(results, "Visitor B cash", v["Cash"], "$200,000.00")

        print("Visitor A: Reset Demo")
        go(a, "Date & Reset Demo", "Date & Reset Demo")
        a.get_by_text("I understand this deletes all transactions").click()
        settle(a)
        a.get_by_role("button", name="Reset Demo").click()
        a.get_by_text("Demo reset to initial conditions.").wait_for(timeout=TIMEOUT)
        expect(results, "Sales after reset", statement_values(a)["Sales"], "$0.00")
        browser.close()

    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1].rstrip("/")))
