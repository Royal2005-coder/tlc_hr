"""Vietnamese payroll of TLC as plain rules: social insurance with dated ceilings, progressive PIT, overtime pay and its PIT-free
premium, and the precondition of a payroll month (every attendance period locked).

- BHXH 8 % / BHYT 1.5 % (employee) and 17.5 % / 3 % (employer) on the insured salary up to 20 × base salary in force on the first
  day of the month; BHTN 1 % / 1 % up to 20 × the regional minimum wage; trade-union fee (KPCĐ) 2 % paid by the employer.
- PIT on salary minus employee insurance, personal and dependent deductions, in the 5 brackets of 2026 (Luật 109/2025/QH15).
- Lunch allowance up to 730,000 a month is free of PIT; overtime is taxed on its 100 % part only, the premium is free
  (Luật Thuế TNCN điều 4).
Rounding follows HRMS formulas (Python round), so a payslip computed here and on the site match to the đồng.
"""

from dataclasses import dataclass
from datetime import date

from tlc_hr.domain.overtime import MULTIPLIER
from tlc_hr.domain.shared import DomainError
from tlc_hr.vn.statutory import BASE_SALARY_HISTORY, MIN_WAGE_2026, PIT_BRACKETS_2026, SETTINGS_2026

S = SETTINGS_2026
CEILING = S["si_hi_ceiling_multiplier"]
LUNCH_ALLOWANCE = 730_000
EMPLOYEE_RATES = {"BHXH_NLD": ("si", S["si_employee_rate"]), "BHYT_NLD": ("si", S["hi_employee_rate"]), "BHTN_NLD": ("ui", S["ui_employee_rate"])}
EMPLOYER_RATES = {"BHXH_DN_TLC": ("si", S["si_employer_rate"]), "BHYT_DN_TLC": ("si", S["hi_employer_rate"]), "BHTN_DN_TLC": ("ui", S["ui_employer_rate"]),
                  "KPCD_DN_TLC": ("si", 2)}
TAXED_EARNINGS = ("LCB", "TH", "PCTN", "PCDT", "PCXX", "OT")  # the lunch allowance PCAT and the overtime premium OTP are not taxed


def base_salary_on(day: date) -> int:
    value = None
    for start, amount in BASE_SALARY_HISTORY:
        if day >= date.fromisoformat(start):
            value = amount
    if value is None:
        raise ValueError(f"no base salary in force on {day}")
    return value


def min_wage(region: str | None) -> int:
    return MIN_WAGE_2026.get(region or "I", MIN_WAGE_2026["I"])


def contributions(insured: float, region: str | None, month_start: date) -> dict[str, int]:
    """Employee and employer insurance of one month, by component abbreviation."""
    bases = {"si": min(insured, CEILING * base_salary_on(month_start)), "ui": min(insured, CEILING * min_wage(region))}
    return {abbr: round(bases[kind] * rate / 100) for abbr, (kind, rate) in {**EMPLOYEE_RATES, **EMPLOYER_RATES}.items()}


def taxable_income(taxed: float, employee_insurance: float, dependents: int) -> float:
    return max(0, taxed - employee_insurance - S["personal_deduction"] - S["dependent_deduction"] * (dependents or 0))


def pit(income: float) -> int:
    """Largest of rate × income − quick deduction over the brackets: the same as the progressive table."""
    return round(max(0, *(rate * income - quick for _upper, rate, quick in PIT_BRACKETS_2026)))


@dataclass(frozen=True)
class Payslip:
    earnings: dict
    deductions: dict
    employer: dict

    @property
    def gross(self):
        return sum(self.earnings.values())

    @property
    def net(self):
        return self.gross - sum(self.deductions.values())


def payslip(base: float, month_start: date, *, paid_ratio: float = 1.0, factory: bool = False, insured: float | None = None,
            region: str | None = "I", dependents: int = 0, overtime: float = 0, premium: float = 0) -> Payslip:
    """The payslip the structure "TLC Lương" computes (earnings follow the days paid; insurance and tax the contract salary)."""
    earnings = {"LCB": round(base * paid_ratio)}
    if factory:
        earnings["PCAT"] = round(LUNCH_ALLOWANCE * paid_ratio)
    if overtime:
        earnings["OT"], earnings["OTP"] = round(overtime), round(premium)
    insurance = contributions(insured or base, region, month_start)
    employee = {k: insurance[k] for k in EMPLOYEE_RATES}
    taxed = sum(v for k, v in earnings.items() if k in TAXED_EARNINGS)
    deductions = {**employee, "TNCN": pit(taxable_income(taxed, sum(employee.values()), dependents))}
    return Payslip(earnings={k: v for k, v in earnings.items() if v}, deductions={k: v for k, v in deductions.items() if v},
                   employer={k: insurance[k] for k in EMPLOYER_RATES})


def overtime_pay(base: float, working_days: int, shift_hours: float, hours_by_day_type: dict[str, float]) -> tuple[int, int]:
    """(OT, OTP): the 100 % part of approved overtime (taxed) and its premium (free of PIT); hourly rate = base / working days /
    hours of the shift."""
    hourly = base / max(working_days, 1) / (shift_hours or 8)
    hours = sum(hours_by_day_type.values())
    premium = sum(h * (MULTIPLIER.get(kind, 1.5) - 1) for kind, h in hours_by_day_type.items())
    return round(hours * hourly), round(premium * hourly)


def check_periods_locked(month: str, scopes: set[str], locked: set[str]) -> None:
    missing = sorted(scopes - locked)
    if missing:
        raise DomainError("payroll.period_open", f"Kỳ công tháng {month} chưa khoá cho: {', '.join(missing)}. "
                                                 "Chốt và khoá kỳ công trước khi tính lương.", "Chưa khoá kỳ công")


def check_payment(reference: str | None, paid_on: date | None, draft_slips: int) -> None:
    """The accountant confirms a payment with its bank proof, after every payslip is posted (payment is not approval)."""
    if not ((reference or "").strip() and paid_on):
        raise DomainError("payroll.proof_required", "Nhập số chứng từ ngân hàng và ngày chi trước khi xác nhận đã chi.", "Thiếu chứng từ chi")
    if draft_slips:
        raise DomainError("payroll.slips_pending", "Phiếu lương chưa ghi sổ xong; chờ vài phút rồi xác nhận lại.")


def check_return(reason: str | None) -> None:
    if not (reason or "").strip():
        raise DomainError("payroll.reason_required", "Nhập lý do trước khi trả lại bảng lương.", "Thiếu lý do")
