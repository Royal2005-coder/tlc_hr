"""The rules of domain/payroll.py written in the formula language of HRMS salary components.

HRMS evaluates a formula with the Employee, Salary Structure Assignment and Salary Slip fields in scope and min, max, round,
getdate. A structure row of customizing/payroll.yaml either holds a plain expression ("base") or a reference rendered here:
"@contribution" (the insurance of its abbreviation), "@pit", "@lunch". tests/unit/test_payroll.py evaluates the rendered
formulas and checks them against domain.payroll.payslip, so the site computes what the rules say.
"""

from tlc_hr.domain import payroll as rules
from tlc_hr.vn.statutory import BASE_SALARY_HISTORY, MIN_WAGE_2026

INSURED = "(vn_insurance_salary or base)"


def base_salary() -> str:
    """Base salary in force on the first day of the payslip (HRMS passes start_date as text: getdate on both sides)."""
    rows = sorted(BASE_SALARY_HISTORY)
    expression = str(rows[0][1])
    for start, amount in rows[1:]:
        expression = f'({amount} if getdate(start_date) >= getdate("{start}") else {expression})'
    return expression


def min_wage() -> str:
    expression = str(MIN_WAGE_2026["I"])
    for region in ("IV", "III", "II"):
        expression = f'({MIN_WAGE_2026[region]} if tlc_wage_region == "{region}" else {expression})'
    return expression


def contribution(abbr: str) -> str:
    kind, rate = {**rules.EMPLOYEE_RATES, **rules.EMPLOYER_RATES}[abbr]
    cap = base_salary() if kind == "si" else min_wage()
    return f"round(min({INSURED}, {rules.CEILING} * {cap}) * {rate} / 100)"


def pit() -> str:
    taxed = " + ".join(rules.TAXED_EARNINGS)
    insurance = " + ".join(rules.EMPLOYEE_RATES)
    dependents = "(tlc_effective_dependents if tlc_effective_dependents is not None else (vn_number_of_dependents or 0))"
    income = (f"max(0, {taxed} - ({insurance}) - {rules.S['personal_deduction']} - {rules.S['dependent_deduction']}"
              f" * {dependents})")
    lines = ", ".join(f"{rate} * {income} - {quick}" for _upper, rate, quick in rules.PIT_BRACKETS_2026)
    return f"round(max(0, {lines}))"


REFERENCES = {"@pit": lambda abbr: pit(), "@contribution": contribution, "@lunch": lambda abbr: str(rules.LUNCH_ALLOWANCE)}


def render(abbr: str, formula: str) -> str:
    return REFERENCES[formula](abbr) if formula in REFERENCES else formula
