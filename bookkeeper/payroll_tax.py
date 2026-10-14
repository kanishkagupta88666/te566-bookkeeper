"""Payroll withholding for tax year 2026.

Rates are kept in one table so they can be re-checked each year, as the
instructional guide requires.

Simplifications (documented in the README):
  * Federal income tax uses the annualized percentage method: annual wages
    less the standard deduction, run through the 2026 brackets, divided by the
    number of pay periods. It is an estimate of IRS Pub. 15-T withholding, not
    a certified payroll calculation.
  * State tax is the Illinois flat rate applied to gross wages (no exemption
    allowance).
  * Only the employee's share of FICA is withheld; the employer's matching
    share is out of scope, matching the course sample.
"""
from decimal import Decimal

from .money import round_cents

TAX_YEAR = 2026

SOCIAL_SECURITY_RATE = Decimal("0.062")
SOCIAL_SECURITY_WAGE_BASE_CENTS = 184_500_00
MEDICARE_RATE = Decimal("0.0145")
STATE_RATE = Decimal("0.0495")  # Illinois flat income tax

STANDARD_DEDUCTION_CENTS = {"single": 16_100_00, "married": 32_200_00}

# (upper bound of bracket in cents, marginal rate); None = no upper bound
FEDERAL_BRACKETS = {
    "single": [
        (12_400_00, Decimal("0.10")),
        (50_400_00, Decimal("0.12")),
        (105_700_00, Decimal("0.22")),
        (201_775_00, Decimal("0.24")),
        (256_225_00, Decimal("0.32")),
        (640_600_00, Decimal("0.35")),
        (None, Decimal("0.37")),
    ],
    "married": [
        (24_800_00, Decimal("0.10")),
        (100_800_00, Decimal("0.12")),
        (211_400_00, Decimal("0.22")),
        (403_550_00, Decimal("0.24")),
        (512_450_00, Decimal("0.32")),
        (768_700_00, Decimal("0.35")),
        (None, Decimal("0.37")),
    ],
}


def annual_federal_tax_cents(annual_wages_cents: int, filing_status: str = "single") -> int:
    status = filing_status if filing_status in FEDERAL_BRACKETS else "single"
    taxable = max(annual_wages_cents - STANDARD_DEDUCTION_CENTS[status], 0)
    tax = Decimal(0)
    lower = 0
    for upper, rate in FEDERAL_BRACKETS[status]:
        top = taxable if upper is None else min(taxable, upper)
        if top > lower:
            tax += Decimal(top - lower) * rate
        if upper is None or taxable <= upper:
            break
        lower = upper
    return round_cents(tax)


def compute_paycheck(annual_salary_cents: int, pay_periods: int, filing_status: str = "single",
                     bonus_cents: int = 0, ytd_gross_cents: int = 0) -> dict:
    """Break one pay period's gross pay into withholdings and net pay (all integer cents)."""
    salary = round_cents(Decimal(annual_salary_cents) / pay_periods)
    gross = salary + bonus_cents

    federal = round_cents(Decimal(annual_federal_tax_cents(annual_salary_cents, filing_status)) / pay_periods)
    if bonus_cents:  # supplemental wages: flat 22% federal rate
        federal += round_cents(Decimal(bonus_cents) * Decimal("0.22"))

    ss_taxable = max(min(gross, SOCIAL_SECURITY_WAGE_BASE_CENTS - ytd_gross_cents), 0)
    social_security = round_cents(Decimal(ss_taxable) * SOCIAL_SECURITY_RATE)
    medicare = round_cents(Decimal(gross) * MEDICARE_RATE)
    state = round_cents(Decimal(gross) * STATE_RATE)

    withholding = federal + state + social_security + medicare
    return {
        "salary_cents": salary,
        "bonus_cents": bonus_cents,
        "gross_cents": gross,
        "federal_cents": federal,
        "state_cents": state,
        "social_sec_cents": social_security,
        "medicare_cents": medicare,
        "withholding_cents": withholding,
        "net_cents": gross - withholding,
    }
