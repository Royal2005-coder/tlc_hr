"""PIT of 2026 for TLC: the 5-bracket table gives the same tax as computing each band separately (hand-checked cases)."""

import unittest

from tlc_hr.vn.statutory import PIT_BRACKETS_2026, patch_pit_table


def progressive(income):
    """Tax computed band by band: the reference the quick-deduction table must match."""
    bands = [(10_000_000, 0.05), (30_000_000, 0.10), (60_000_000, 0.20), (100_000_000, 0.30), (float("inf"), 0.35)]
    tax, lower = 0.0, 0.0
    for upper, rate in bands:
        if income > lower:
            tax += (min(income, upper) - lower) * rate
        lower = upper
    return round(tax)


class TestPit2026(unittest.TestCase):
    def test_quick_deduction_matches_band_by_band(self):
        for income in (1, 9_999_999, 10_000_000, 10_000_001, 25_000_000, 30_000_000, 45_000_000, 60_000_000, 99_000_000, 100_000_000, 250_000_000):
            for upper, rate, quick in PIT_BRACKETS_2026:
                if income <= upper:
                    self.assertEqual(round(income * rate - quick), progressive(income), income)
                    break

    def test_hand_computed_cases(self):
        # 20,000,000 taxable: 10M × 5% + 10M × 10% = 1,500,000
        self.assertEqual(progressive(20_000_000), 1_500_000)
        # 80,000,000 taxable: 500,000 + 2,000,000 + 6,000,000 + 20M × 30% = 14,500,000
        self.assertEqual(progressive(80_000_000), 14_500_000)

    def test_erpnextvn_uses_the_2026_table(self):
        try:
            from erpnextvn.payroll import pit_calculator
        except ImportError:
            self.skipTest("erpnextvn not installed")
        self.assertTrue(patch_pit_table())
        # gross 40,000,000, insurance 4,200,000, no dependent: taxable 40M − 4.2M − 15.5M = 20.3M → 500,000 + 10.3M × 10% = 1,530,000
        result = pit_calculator.calculate_pit(40_000_000, insurance_deduction=4_200_000, num_dependents=0, personal_deduction=15_500_000, dependent_deduction=6_200_000)
        self.assertEqual(result.tax_amount, 1_530_000)
        self.assertEqual(result.bracket, 2)


if __name__ == "__main__":
    unittest.main()
