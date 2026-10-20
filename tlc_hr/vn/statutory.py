"""Vietnamese payroll parameters of 2026 for TLC, applied on top of erpnextvn.

erpnextvn ships the PIT table in 7 brackets and a base salary of 2,340,000. TLC pays under the law in force in 2026:
- PIT in 5 brackets from 2026-01-01 (Luật Thuế TNCN 109/2025/QH15 điều 9);
- personal and dependent deductions 15,500,000 and 6,200,000 (same law, điều 10; erpnextvn already has them);
- base salary 2,530,000 from 2026-07-01 (Nghị định 161/2026/NĐ-CP điều 3), so the BHXH/BHYT ceiling is 20 × 2,530,000;
- regional minimum wages from 2026-01-01 (Nghị định 293/2025/NĐ-CP điều 3): the BHTN ceiling is 20 × the minimum of the region.
Source of the numbers: the TLC spec hr_vn_compensation.yaml, the same values the Odoo stage uses.
"""

# (upper limit of monthly taxable income, rate, quick deduction): tax = income × rate − quick deduction inside the bracket.
PIT_BRACKETS_2026 = [
    (10_000_000, 0.05, 0),
    (30_000_000, 0.10, 500_000),
    (60_000_000, 0.20, 3_500_000),
    (100_000_000, 0.30, 9_500_000),
    (float("inf"), 0.35, 14_500_000),
]

# Regional minimum monthly wage from 2026-01-01 (Nghị định 293/2025/NĐ-CP điều 3).
MIN_WAGE_2026 = {"I": 5_310_000, "II": 4_730_000, "III": 4_140_000, "IV": 3_700_000}

# Base salary (lương cơ sở) by effective date: the BHXH/BHYT ceiling of a payroll month uses the value in force on its first day.
BASE_SALARY_HISTORY = [("2024-07-01", 2_340_000), ("2026-07-01", 2_530_000)]


def base_salary_on(day):
    """Base salary in force on a date (raises for a date before the first known value)."""
    from datetime import date

    day = day if isinstance(day, date) else date.fromisoformat(str(day))
    value = None
    for start, amount in BASE_SALARY_HISTORY:
        if day >= date.fromisoformat(start):
            value = amount
    if value is None:
        raise ValueError(f"no base salary in force on {day}")
    return value


SETTINGS_2026 = {
    "base_salary": 2_530_000,
    "personal_deduction": 15_500_000,
    "dependent_deduction": 6_200_000,
    "si_employee_rate": 8,
    "hi_employee_rate": 1.5,
    "ui_employee_rate": 1,
    "si_employer_rate": 17.5,
    "hi_employer_rate": 3,
    "ui_employer_rate": 1,
    "si_hi_ceiling_multiplier": 20,
    "ui_ceiling_multiplier": 20,
    "min_wage_region_1": MIN_WAGE_2026["I"],
    "min_wage_region_2": MIN_WAGE_2026["II"],
    "min_wage_region_3": MIN_WAGE_2026["III"],
    "min_wage_region_4": MIN_WAGE_2026["IV"],
    "effective_date": "2026-07-01",
}


def patch_pit_table():
    """Make erpnextvn compute PIT with the 2026 table. Called when tlc_hr is imported, so every web and worker process uses it."""
    try:
        from erpnextvn.payroll import pit_calculator
    except ImportError:  # erpnextvn not installed in this environment
        return False
    pit_calculator.TAX_BRACKETS = list(PIT_BRACKETS_2026)
    return True


def apply_settings():
    """Write the 2026 values into the single doctype VN Payroll Settings (after install and after every migration)."""
    import frappe

    if not frappe.db.exists("DocType", "VN Payroll Settings"):
        return
    settings = frappe.get_single("VN Payroll Settings")
    changed = {key: value for key, value in SETTINGS_2026.items() if str(settings.get(key) or "") != str(value)}
    if changed:
        settings.update(changed)
        settings.flags.ignore_permissions = True
        settings.save()
        frappe.db.commit()
