"""Initial conditions for the demo business (deterministic)."""
from . import db, ledger

COMPANY_NAME = "Prairie Toy Truck Co."
START_DATE = "2026-10-01"

INITIAL_CASH_CENTS = 200_000_00
OPENING_FINISHED_UNITS = 60_000

# Bill of materials from the instructional guide:
# (part, quantity per truck, unit cost in cents, opening quantity, reorder point)
PARTS = [
    ("Wheels", 8, 1, 80_000, 40_000),
    ("Windshield Glass", 1, 5, 10_000, 5_000),
    ("Interior", 1, 5, 10_000, 5_000),
    ("Tank", 1, 10, 10_000, 5_000),
    ("Axles", 4, 1, 40_000, 20_000),
    ("Cab", 1, 10, 4_000, 5_000),  # opens below its reorder point
    ("Body", 1, 10, 10_000, 5_000),
    ("Box / Packaging", 1, 5, 10_000, 5_000),
]

# Eight unique vendors, one per component: (company, part, address1, city, state, zip)
VENDORS = [
    ("Roundhouse Wheel Works", "Wheels", "410 Foundry Rd", "Peoria", "IL", "61602"),
    ("ClearView Plastics", "Windshield Glass", "88 Polymer Way", "Rockford", "IL", "61101"),
    ("Cozy Cab Interiors", "Interior", "1500 Trim St", "Decatur", "IL", "62521"),
    ("Midwest Tank & Mold", "Tank", "27 Injection Dr", "Joliet", "IL", "60431"),
    ("Straight Line Axle Co.", "Axles", "902 Rod Ave", "Springfield", "IL", "62701"),
    ("Diecast Cab Castings", "Cab", "3300 Alloy Blvd", "Aurora", "IL", "60502"),
    ("Heartland Body Castings", "Body", "76 Press Ln", "Bloomington", "IL", "61701"),
    ("BoxRight Packaging", "Box / Packaging", "5 Carton Ct", "Champaign", "IL", "61820"),
]

# Ten customers: (company, first, last, address1, city, state, zip, price per truck in cents)
CUSTOMERS = [
    ("Smith Toy Co.", "Alex", "Smith", "12 Main St", "Urbana", "IL", "61801", 250),
    ("Big Wheel Toys", "Priya", "Raman", "400 Market St", "Chicago", "IL", "60601", 250),
    ("Online Hobby Depot", "Sam", "Okafor", "9 Web Way", "Naperville", "IL", "60540", 250),
    ("Tower Hobby Supply", "Dana", "Lopez", "2904 Research Rd", "Champaign", "IL", "61822", 250),
    ("HobbyTronics", "Lee", "Chen", "77 Circuit Ave", "Evanston", "IL", "60201", 250),
    ("ValueMart Stores", "Morgan", "Bailey", "1 Retail Plaza", "Indianapolis", "IN", "46204", 240),
    ("Corner Five & Dime", "Riley", "Nguyen", "53 Elm St", "Madison", "WI", "53703", 260),
    ("Bullseye Department Stores", "Jamie", "Patel", "800 Mall Dr", "Minneapolis", "MN", "55403", 240),
    ("Hobby Junction", "Casey", "Brown", "311 Depot St", "St. Louis", "MO", "63101", 275),
    ("Little Engine Toy Shop", "Taylor", "Kim", "18 Station Sq", "Iowa City", "IA", "52240", 275),
]

# Ten expense accounts (excluding salary and taxes) totalling $200,000 per year: (name, annual budget cents)
EXPENSE_ACCOUNTS = [
    ("Rent", 60_000_00),
    ("Shipping & Freight", 36_000_00),
    ("Marketing", 24_000_00),
    ("Insurance", 18_000_00),
    ("Utilities", 12_000_00),
    ("Professional Fees", 12_000_00),
    ("Equipment Maintenance", 12_000_00),
    ("Travel", 12_000_00),
    ("Software Subscriptions", 8_000_00),
    ("Office Supplies", 6_000_00),
]

EMPLOYEE = dict(
    first_name="Jordan", last_name="Smith", address1="601 E John St", address2="Apt 2",
    city="Champaign", state="IL", zip="61820", ssn_last4="4821", filing_status="single",
    dependents=0, annual_salary_cents=150_000_00, pay_periods=12,
)


def is_initialized(conn) -> bool:
    return db.get_setting(conn, "current_date") is not None


def reset_demo(conn) -> None:
    """Erase everything and rebuild the documented starting position."""
    with db.transaction(conn):
        for table in db.TABLES:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM sqlite_sequence")

        db.set_setting(conn, "company_name", COMPANY_NAME)
        db.set_setting(conn, "current_date", START_DATE)
        db.set_setting(conn, "start_date", START_DATE)

        conn.executemany("INSERT INTO accounts(code, name, type) VALUES (?, ?, ?)", ledger.CHART)

        for i, (name, budget) in enumerate(EXPENSE_ACCOUNTS):
            code = str(6100 + 10 * i)
            conn.execute("INSERT INTO accounts(code, name, type) VALUES (?, ?, 'expense')", (code, name))
            conn.execute(
                "INSERT INTO expense_accounts(name, account_code, annual_budget_cents) VALUES (?, ?, ?)",
                (name, code, budget),
            )

        part_ids, unit_costs = {}, {}
        raw_value = 0
        cost_per_truck = 0
        for name, per_unit, cost, qty, reorder in PARTS:
            value = qty * cost
            raw_value += value
            cost_per_truck += per_unit * cost
            unit_costs[name] = cost
            part_ids[name] = conn.execute(
                "INSERT INTO parts(name, qty_per_unit, qty_on_hand, value_cents, reorder_point) VALUES (?, ?, ?, ?, ?)",
                (name, per_unit, qty, value, reorder),
            ).lastrowid

        for company, part, addr, city, state, zip_code in VENDORS:
            conn.execute(
                "INSERT INTO vendors(company, part_id, price_cents, address1, city, state, zip) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (company, part_ids[part], unit_costs[part], addr, city, state, zip_code),
            )

        conn.executemany(
            "INSERT INTO customers(company, first_name, last_name, address1, city, state, zip, price_cents) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            CUSTOMERS,
        )

        cols = ", ".join(EMPLOYEE)
        conn.execute(
            f"INSERT INTO employees({cols}) VALUES ({', '.join('?' for _ in EMPLOYEE)})", list(EMPLOYEE.values())
        )

        finished_value = OPENING_FINISHED_UNITS * cost_per_truck
        conn.execute("INSERT INTO product_stock(stage, qty, value_cents) VALUES ('wip', 0, 0)")
        conn.execute(
            "INSERT INTO product_stock(stage, qty, value_cents) VALUES ('finished', ?, ?)",
            (OPENING_FINISHED_UNITS, finished_value),
        )

        # Opening balances — two balanced entries, both funded by the owner.
        ledger.post(
            conn, START_DATE, "Owner's initial cash investment", "OPENING",
            [(ledger.CASH, INITIAL_CASH_CENTS, 0), (ledger.OWNER_CAPITAL, 0, INITIAL_CASH_CENTS)],
            reference="OPEN-1",
        )
        ledger.post(
            conn, START_DATE, "Owner contributes opening inventory (parts and finished trucks) at cost", "OPENING",
            [
                (ledger.RAW_MATERIALS, raw_value, 0),
                (ledger.FINISHED_GOODS, finished_value, 0),
                (ledger.OWNER_CAPITAL, 0, raw_value + finished_value),
            ],
            reference="OPEN-2",
        )


def ensure_initialized(conn) -> None:
    if not is_initialized(conn):
        reset_demo(conn)
