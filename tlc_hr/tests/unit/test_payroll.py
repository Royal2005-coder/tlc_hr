"""Vietnamese payroll without a site: golden payslips of 2026 (blueprint UAT-PAY-05) on the domain rules, and the formulas the site
runs (rendered from customizing/payroll.yaml) evaluated here and checked against the same rules."""

import unittest
from datetime import date

from tlc_hr.domain import payroll as rules
from tlc_hr.domain.overtime import HOLIDAY, REST_DAY, WORKING_DAY
from tlc_hr.domain.shared import DomainError
from tlc_hr.infrastructure.customizing.loader import load_bundle
from tlc_hr.infrastructure.customizing.payroll_formulas import render

SEPTEMBER, JUNE = date(2026, 9, 1), date(2026, 6, 1)
GLOBALS = {"min": min, "max": max, "round": round, "int": int, "float": float,
           "getdate": lambda v: v if isinstance(v, date) else date.fromisoformat(v)}


def site_payslip(base, start, factory=False, dependents=0, region="I", extra=None):
    """Evaluate the structure of customizing/payroll.yaml the way HRMS does: rows in order, each result in scope by abbreviation."""
    structure = load_bundle().payroll.structure
    data = {"base": base, "vn_insurance_salary": base, "vn_number_of_dependents": dependents, "tlc_wage_region": region,
            "tlc_effective_base": base, "tlc_effective_dependents": dependents,
            "tlc_workforce": "factory" if factory else "head_office", "start_date": start.isoformat(), **(extra or {})}  # text, as in HRMS
    for abbr in ("LCB", "PCAT", "TH", "PCTN", "PCDT", "PCXX", "OT", "OTP", *rules.EMPLOYEE_RATES, "TNCN", *rules.EMPLOYER_RATES):
        data.setdefault(abbr, 0)
    result = {}
    for row in structure.earnings + structure.deductions + structure.employer_contributions:
        if row.condition and not eval(row.condition, GLOBALS, data):  # noqa: S307 - our own formulas, as HRMS does
            continue
        data[row.abbr] = result[row.abbr] = eval(render(row.abbr, row.formula), GLOBALS, data)  # noqa: S307
    return result


class TestGoldenPayslips(unittest.TestCase):
    def test_office_employee_22_million(self):
        slip = rules.payslip(22_000_000, SEPTEMBER)
        self.assertEqual((sum(slip.deductions[k] for k in rules.EMPLOYEE_RATES), slip.deductions["TNCN"], slip.net),
                         (2_310_000, 209_500, 19_480_500))

    def test_two_dependents_and_the_ceiling(self):
        self.assertEqual(rules.payslip(52_000_000, SEPTEMBER, dependents=2).deductions["TNCN"], 1_377_300)

    def test_bhtn_ceiling_of_region_one(self):
        slip = rules.payslip(120_000_000, SEPTEMBER)
        self.assertEqual((slip.deductions["BHXH_NLD"], slip.deductions["BHTN_NLD"]), (4_048_000, 1_062_000))

    def test_base_salary_of_the_month(self):
        self.assertEqual(rules.payslip(120_000_000, JUNE).deductions["BHXH_NLD"], round(20 * 2_340_000 * 0.08))

    def test_factory_worker_lunch_free_of_tax(self):
        slip = rules.payslip(12_000_000, SEPTEMBER, factory=True)
        self.assertEqual((slip.earnings["PCAT"], slip.deductions.get("TNCN", 0)), (rules.LUNCH_ALLOWANCE, 0))

    def test_employer_contributions_stay_out_of_net_pay(self):
        slip = rules.payslip(22_000_000, SEPTEMBER)
        self.assertEqual((slip.employer["BHXH_DN_TLC"], slip.employer["KPCD_DN_TLC"], slip.net), (3_850_000, 440_000, 19_480_500))

    def test_overtime_premium_free_of_tax(self):
        ot, otp = rules.overtime_pay(22_000_000, 22, 8, {WORKING_DAY: 6, REST_DAY: 4, HOLIDAY: 2})
        hourly = 22_000_000 / 22 / 8
        self.assertEqual((ot, otp), (round(12 * hourly), round((3 + 4 + 4) * hourly)))
        with_ot = rules.payslip(22_000_000, SEPTEMBER, overtime=ot, premium=otp)
        self.assertEqual(with_ot.deductions["TNCN"], rules.pit(rules.taxable_income(22_000_000 + ot, 2_310_000, 0)))

    def test_pit_table(self):
        for income, tax in ((0, 0), (10_000_000, 500_000), (30_000_000, 2_500_000), (60_000_000, 8_500_000), (150_000_000, 38_000_000)):
            self.assertEqual(rules.pit(income), tax, income)


class TestSiteFormulas(unittest.TestCase):
    """The formulas the site runs give the payslips of the rules, case by case."""

    def check(self, base, start=SEPTEMBER, **options):
        site = site_payslip(base, start, factory=options.get("factory", False), dependents=options.get("dependents", 0),
                            region=options.get("region", "I"))
        expected = rules.payslip(base, start, **options)
        wanted = {**expected.earnings, **expected.deductions, **expected.employer}
        self.assertEqual({k: v for k, v in site.items() if v}, {k: v for k, v in wanted.items() if v})

    def test_cases(self):
        self.check(22_000_000)
        self.check(52_000_000, dependents=2)
        self.check(120_000_000)
        self.check(120_000_000, start=JUNE)
        self.check(12_000_000, factory=True)
        self.check(30_000_000, region="III")


class TestPreconditions(unittest.TestCase):
    def test_every_period_locked_before_payroll(self):
        with self.assertRaises(DomainError) as caught:
            rules.check_periods_locked("2026-09", {"Nhà máy 1", "Hội sở"}, {"Hội sở"})
        self.assertIn("Nhà máy 1", caught.exception.message)
        rules.check_periods_locked("2026-09", {"Nhà máy 1", "Hội sở"}, {"Nhà máy 1", "Hội sở"})

    def test_payment_needs_proof_and_posted_slips(self):
        with self.assertRaises(DomainError):
            rules.check_payment("", date(2026, 10, 5), 0)
        with self.assertRaises(DomainError):
            rules.check_payment("VCB-001", date(2026, 10, 5), 3)
        rules.check_payment("VCB-001", date(2026, 10, 5), 0)


if __name__ == "__main__":
    unittest.main()
