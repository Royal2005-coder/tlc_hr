"""Exports and statutory reports for TLC Payroll.

Supports:
- Bank payment batch export (declared format; not certified bank-ready).
- Accounting payroll cost reconciliation with native general ledger.
- PIT report (monthly/quarterly/annualized).
- BHXH D02-LT labor change register and VNPT BHXH exchange file.
- Sổ quản lý lao động (Labor Register per Decree 145/2020/ND-CP).
- Headcount breakdown and movement report (HR-LG-23).
- Role-private cost report (HR-LG-24).
- Salary budget simulation (HR-LG-14).
- Payroll anomaly insights (HR-LG-26).
"""
import csv
import io
import json
from datetime import date
from decimal import Decimal

import frappe
from frappe.utils import flt, getdate

from tlc_hr.domain.payroll_compliance import safe_csv_cell

PAYROLL_ROLES = {"TLC Payroll", "TLC HR Lead", "TLC Director", "Accounts User", "System Manager"}


def check_payroll_permission():
    if frappe.session.user != "Administrator" and not set(frappe.get_roles()) & PAYROLL_ROLES:
        frappe.throw("Không có quyền truy cập báo cáo/chi phí lương.", frappe.PermissionError)


def export_bank_payment_batch(payroll_entry_name, bank_code="VCB"):
    """Export payment batch CSV for bank disbursement.

    DISCLAIMER: Declared configurable export format. Missing bank-certified API integration;
    file must be reviewed before transmission to bank.
    """
    check_payroll_permission()
    entry = frappe.get_doc("Payroll Entry", payroll_entry_name)
    entry.check_permission("read")

    slips = frappe.get_all(
        "Salary Slip",
        filters={"payroll_entry": payroll_entry_name, "docstatus": 1},
        fields=["name", "employee", "employee_name", "net_pay", "bank_name", "bank_account_no"],
        order_by="employee_name asc"
    )
    if not slips:
        frappe.throw("Chưa có phiếu lương đã ghi sổ để xuất file ngân hàng.")

    output = io.StringIO()
    writer = csv.writer(output)

    # Header with transparent disclaimer
    writer.writerow([
        "# FORMAT", f"TLC Bank Batch Export ({bank_code}) - UNVERIFIED BANK TEMPLATE",
        "DATE", str(date.today()),
        "PAYROLL_ENTRY", entry.name
    ])
    writer.writerow([
        "STT", "Mã nhân viên", "Họ và tên", "Số tài khoản",
        "Tên ngân hàng", "Chi nhánh", "Số tiền (VND)",
        "Nội dung chuyển khoản", "CCCD/Định danh"
    ])

    for idx, slip in enumerate(slips, start=1):
        emp_doc = frappe.db.get_value(
            "Employee", slip["employee"],
            ["bank_ac_no", "bank_name", "passport_number"],
            as_dict=True
        ) or {}
        ac_no = slip.get("bank_account_no") or emp_doc.get("bank_ac_no") or ""
        bank = slip.get("bank_name") or emp_doc.get("bank_name") or bank_code
        cccd = emp_doc.get("passport_number") or emp_doc.get("passport_number") or ""
        remark = f"Thanh toan luong {entry.name} - {slip['employee']}"

        writer.writerow([
            idx,
            safe_csv_cell(slip["employee"]),
            safe_csv_cell(slip["employee_name"]),
            safe_csv_cell(ac_no),
            safe_csv_cell(bank),
            "",
            int(round(flt(slip["net_pay"]))),
            safe_csv_cell(remark),
            safe_csv_cell(cccd)
        ])

    return {
        "filename": f"bank_batch_{entry.name}_{bank_code}.csv",
        "content": output.getvalue(),
        "certified": False,
        "note": "Declared export format. Not certified by recipient bank partner."
    }


def export_accounting_reconciliation(payroll_entry_name):
    """Reconcile payroll component breakdown with GL Journal Entries."""
    check_payroll_permission()
    entry = frappe.get_doc("Payroll Entry", payroll_entry_name)
    entry.check_permission("read")

    slips = frappe.get_all(
        "Salary Slip",
        filters={"payroll_entry": payroll_entry_name, "docstatus": 1},
        fields=["name", "gross_pay", "total_deduction", "net_pay"]
    )
    names = [s.name for s in slips] or [""]

    component_totals = {}
    details = frappe.get_all(
        "Salary Detail",
        filters={"parent": ["in", names], "parenttype": "Salary Slip"},
        fields=["salary_component", "abbr", "amount", "parent"]
    )
    for d in details:
        component_totals[d.salary_component] = component_totals.get(d.salary_component, 0.0) + flt(d.amount)

    gl_entries = frappe.get_all(
        "GL Entry",
        filters={"voucher_type": "Journal Entry", "against_voucher": entry.name},
        fields=["account", "debit", "credit", "voucher_no"]
    )
    if not gl_entries:
        # Check by journal entry reference if cheque_no matches
        if entry.tlc_bank_reference:
            gl_entries = frappe.get_all(
                "GL Entry",
                filters={"voucher_no": ["in", frappe.get_all("Journal Entry", {"cheque_no": entry.tlc_bank_reference}, pluck="name")]},
                fields=["account", "debit", "credit", "voucher_no"]
            )

    return {
        "payroll_entry": entry.name,
        "company": entry.company,
        "start_date": str(entry.start_date),
        "end_date": str(entry.end_date),
        "total_slips": len(slips),
        "gross_pay": sum(flt(s.gross_pay) for s in slips),
        "total_deduction": sum(flt(s.total_deduction) for s in slips),
        "net_pay": sum(flt(s.net_pay) for s in slips),
        "components": component_totals,
        "gl_reconciliation": gl_entries
    }


def export_pit_report(company, from_date, to_date):
    """Statutory PIT summary per employee across the date range."""
    check_payroll_permission()
    slips = frappe.get_all(
        "Salary Slip",
        filters={
            "company": company,
            "docstatus": 1,
            "start_date": [">=", from_date],
            "end_date": ["<=", to_date]
        },
        fields=["name", "employee", "employee_name", "gross_pay", "tlc_effective_dependents"],
        order_by="employee asc, start_date asc"
    )
    slip_names = [s.name for s in slips] or [""]
    details = frappe.get_all(
        "Salary Detail",
        filters={"parent": ["in", slip_names]},
        fields=["parent", "salary_component", "abbr", "amount"]
    )
    by_slip = {}
    for d in details:
        by_slip.setdefault(d.parent, {})[d.abbr] = flt(d.amount)

    employees = {}
    for s in slips:
        emp = s.employee
        vn_tax_code = frappe.db.get_value("Employee", emp, "vn_tax_code") or ""
        rec = employees.setdefault(emp, {
            "employee": emp,
            "employee_name": s.employee_name,
            "vn_tax_code": vn_tax_code,
            "slip_count": 0,
            "gross_income": 0.0,
            "taxable_income": 0.0,
            "bhxh_deductions": 0.0,
            "pit_deducted": 0.0,
            "dependents": s.tlc_effective_dependents or 0
        })
        rec["slip_count"] += 1
        rec["gross_income"] += flt(s.gross_pay)
        slip_map = by_slip.get(s.name, {})
        rec["pit_deducted"] += slip_map.get("TNCN", 0.0)
        rec["bhxh_deductions"] += (
            slip_map.get("BHXH_NLD", 0.0) +
            slip_map.get("BHYT_NLD", 0.0) +
            slip_map.get("BHTN_NLD", 0.0)
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Mã nhân viên", "Họ và tên", "Mã số thuế", "Số kỳ lương",
        "Tổng thu nhập chịu thuế", "Các khoản giảm trừ BHXH",
        "Số người phụ thuộc (kỳ cuối)", "Thuế TNCN đã khấu trừ"
    ])
    for emp_id, rec in employees.items():
        writer.writerow([
            safe_csv_cell(rec["employee"]),
            safe_csv_cell(rec["employee_name"]),
            safe_csv_cell(rec["vn_tax_code"]),
            rec["slip_count"],
            int(round(rec["gross_income"])),
            int(round(rec["bhxh_deductions"])),
            rec["dependents"],
            int(round(rec["pit_deducted"]))
        ])

    return {
        "company": company,
        "from_date": str(from_date),
        "to_date": str(to_date),
        "records": list(employees.values()),
        "csv": output.getvalue()
    }


def export_bhxh_d02lt(company, month_str):
    """Labor change reporting for Social Insurance per template D02-LT.

    Includes tracked additions, separations, and base adjustments from TLC Insurance Change.
    """
    check_payroll_permission()
    first_day = f"{month_str}-01"
    last_day = frappe.utils.get_last_day(first_day)

    changes = frappe.get_all(
        "TLC Insurance Change",
        filters={
            "docstatus": 1,
            "effective_on": ["between", [first_day, last_day]]
        },
        fields=[
            "name", "employee", "insurance_number", "change_type",
            "effective_on", "contribution_base", "status", "filing_reference", "reason"
        ]
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "# BHXH D02-LT", f"Kỳ báo cáo {month_str}", f"Công ty {company}"
    ])
    writer.writerow([
        "STT", "Mã nhân viên", "Họ và tên", "Mã số BHXH",
        "Loại biến động", "Ngày hiệu lực", "Mức lương đóng BHXH",
        "Trạng thái hồ sơ", "Mã hồ sơ gửi", "Ghi chú/Lý do"
    ])

    results = []
    for idx, chg in enumerate(changes, start=1):
        emp_name = frappe.db.get_value("Employee", chg["employee"], "employee_name") or ""
        row = [
            idx,
            safe_csv_cell(chg["employee"]),
            safe_csv_cell(emp_name),
            safe_csv_cell(chg["insurance_number"]),
            safe_csv_cell(chg["change_type"]),
            str(chg["effective_on"]),
            int(round(flt(chg["contribution_base"]))),
            safe_csv_cell(chg["status"]),
            safe_csv_cell(chg["filing_reference"] or ""),
            safe_csv_cell(chg["reason"] or "")
        ]
        writer.writerow(row)
        results.append({
            "employee": chg["employee"],
            "employee_name": emp_name,
            "insurance_number": chg["insurance_number"],
            "change_type": chg["change_type"],
            "effective_on": str(chg["effective_on"]),
            "contribution_base": flt(chg["contribution_base"]),
            "status": chg["status"],
            "filing_reference": chg["filing_reference"]
        })

    return {
        "month": month_str,
        "company": company,
        "records": results,
        "csv": output.getvalue(),
        "certified_api": False,
        "note": "VNPT BHXH electronic format. Direct API transmission gateway not certified."
    }


def export_labor_register(company, as_of_date=None):
    """Labor Management Register (Sổ quản lý lao động - Decree 145/2020/ND-CP)."""
    check_payroll_permission()
    as_of = getdate(as_of_date) if as_of_date else date.today()

    employees = frappe.get_all(
        "Employee",
        filters={"company": company},
        fields=[
            "name", "employee_name", "gender", "date_of_birth", "department",
            "designation", "date_of_joining", "relieving_date", "status",
            "passport_number", "vn_tax_code"
        ],
        order_by="date_of_joining asc"
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "# SỔ QUẢN LÝ LAO ĐỘNG", f"Thời điểm {as_of}", f"Doanh nghiệp {company}"
    ])
    writer.writerow([
        "STT", "Mã nhân viên", "Họ và tên", "Giới tính", "Ngày sinh",
        "CCCD/Định danh", "Mã số thuế", "Phòng ban", "Chức vụ",
        "Ngày vào làm", "Ngày nghỉ việc", "Trạng thái", "Lương cơ bản hiện hành"
    ])

    rows = []
    for idx, emp in enumerate(employees, start=1):
        base = frappe.db.get_value(
            "Salary Structure Assignment",
            {"employee": emp["name"], "docstatus": 1, "from_date": ["<=", as_of]},
            "base",
            order_by="from_date desc"
        ) or 0.0
        row = [
            idx,
            safe_csv_cell(emp["name"]),
            safe_csv_cell(emp["employee_name"]),
            safe_csv_cell(emp["gender"]),
            str(emp["date_of_birth"] or ""),
            safe_csv_cell(emp["passport_number"] or ""),
            safe_csv_cell(emp["vn_tax_code"] or ""),
            safe_csv_cell(emp["department"]),
            safe_csv_cell(emp["designation"]),
            str(emp["date_of_joining"] or ""),
            str(emp["relieving_date"] or ""),
            safe_csv_cell(emp["status"]),
            int(round(flt(base)))
        ]
        writer.writerow(row)
        rows.append({
            "employee": emp["name"],
            "employee_name": emp["employee_name"],
            "department": emp["department"],
            "date_of_joining": str(emp["date_of_joining"]),
            "status": emp["status"],
            "base_salary": flt(base)
        })

    return {
        "company": company,
        "as_of": str(as_of),
        "total_employees": len(employees),
        "records": rows,
        "csv": output.getvalue()
    }


def simulate_salary_budget(company, percent_increase, base_date=None, department=None):
    """Simulate payroll budget impact of a percentage salary adjustment (HR-LG-14)."""
    check_payroll_permission()
    as_of = getdate(base_date) if base_date else date.today()
    pct = Decimal(str(percent_increase))

    filters = {"company": company, "status": "Active"}
    if department:
        filters["department"] = department

    active_employees = frappe.get_all("Employee", filters=filters, fields=["name", "employee_name", "department"])

    current_total_base = Decimal("0")
    for emp in active_employees:
        base = frappe.db.get_value(
            "Salary Structure Assignment",
            {"employee": emp["name"], "docstatus": 1, "from_date": ["<=", as_of]},
            "base",
            order_by="from_date desc"
        )
        if base:
            current_total_base += Decimal(str(base))

    new_total_base = current_total_base * (Decimal("1") + pct / Decimal("100"))
    base_delta = new_total_base - current_total_base

    # Statutory employer contribution estimation: 17.5% BHXH + 3% BHYT + 1% BHTN + 2% KPCD = 23.5%
    employer_rate = Decimal("0.235")
    current_employer_contrib = current_total_base * employer_rate
    new_employer_contrib = new_total_base * employer_rate
    employer_delta = base_delta * employer_rate

    total_current_cost = current_total_base + current_employer_contrib
    total_new_cost = new_total_base + new_employer_contrib
    total_delta = total_new_cost - total_current_cost

    return {
        "company": company,
        "department": department or "All",
        "as_of": str(as_of),
        "active_employee_count": len(active_employees),
        "percent_increase": float(pct),
        "current_monthly_base": float(current_total_base),
        "simulated_monthly_base": float(new_total_base),
        "monthly_base_delta": float(base_delta),
        "current_employer_contributions": float(current_employer_contrib),
        "simulated_employer_contributions": float(new_employer_contrib),
        "employer_contribution_delta": float(employer_delta),
        "current_total_employment_cost": float(total_current_cost),
        "simulated_total_employment_cost": float(total_new_cost),
        "monthly_cost_delta": float(total_delta),
        "annualized_cost_delta": float(total_delta * 12)
    }


def get_role_private_cost_report(company, start_date, end_date, group_by="department"):
    """Comprehensive role-private labor cost report (HR-LG-24)."""
    check_payroll_permission()

    slips = frappe.get_all(
        "Salary Slip",
        filters={
            "company": company,
            "docstatus": 1,
            "start_date": [">=", start_date],
            "end_date": ["<=", end_date]
        },
        fields=["name", "employee", "employee_name", "department", "gross_pay", "total_deduction", "net_pay"]
    )
    names = [s.name for s in slips] or [""]

    details = frappe.get_all(
        "Salary Detail",
        filters={"parent": ["in", names]},
        fields=["parent", "salary_component", "abbr", "amount"]
    )
    by_slip = {}
    for d in details:
        by_slip.setdefault(d.parent, {})[d.abbr] = flt(d.amount)

    groups = {}
    for slip in slips:
        key = slip.get(group_by) or "Chưa phân bổ"
        rec = groups.setdefault(key, {
            "group": key,
            "headcount": 0,
            "gross_pay": 0.0,
            "net_pay": 0.0,
            "overtime_pay": 0.0,
            "employer_insurance": 0.0,
            "pit_tax": 0.0,
            "total_company_cost": 0.0
        })
        rec["headcount"] += 1
        rec["gross_pay"] += flt(slip.gross_pay)
        rec["net_pay"] += flt(slip.net_pay)

        s_details = by_slip.get(slip.name, {})
        ot = s_details.get("OT", 0.0) + s_details.get("OTP", 0.0)
        pit = s_details.get("TNCN", 0.0)
        employer_ins = (
            s_details.get("BHXH_DN_TLC", 0.0) +
            s_details.get("BHYT_DN_TLC", 0.0) +
            s_details.get("BHTN_DN_TLC", 0.0) +
            s_details.get("KPCD_DN_TLC", 0.0)
        )
        rec["overtime_pay"] += ot
        rec["pit_tax"] += pit
        rec["employer_insurance"] += employer_ins
        rec["total_company_cost"] += (flt(slip.gross_pay) + employer_ins)

    return {
        "company": company,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "total_slips": len(slips),
        "groups": list(groups.values()),
        "summary": {
            "total_gross": sum(g["gross_pay"] for g in groups.values()),
            "total_net": sum(g["net_pay"] for g in groups.values()),
            "total_employer_insurance": sum(g["employer_insurance"] for g in groups.values()),
            "total_cost": sum(g["total_company_cost"] for g in groups.values()),
            "average_cost_per_employee": (
                sum(g["total_company_cost"] for g in groups.values()) / len(slips)
            ) if slips else 0.0
        }
    }


def get_headcount_movement_report(company, from_date, to_date):
    """Headcount breakdown and movement report (HR-LG-23)."""
    check_payroll_permission()
    from_d = getdate(from_date)
    to_d = getdate(to_date)

    # Active headcount at period end
    active = frappe.get_all(
        "Employee",
        filters={
            "company": company,
            "date_of_joining": ["<=", to_d],
            "status": ["!=", "Left"]
        },
        fields=["name", "department", "designation", "employment_type"]
    )

    by_dept = {}
    for emp in active:
        dept = emp.department or "Chưa phân bổ"
        by_dept[dept] = by_dept.get(dept, 0) + 1

    # New hires in period
    new_hires = frappe.get_all(
        "Employee",
        filters={
            "company": company,
            "date_of_joining": ["between", [from_d, to_d]]
        },
        fields=["name", "employee_name", "department", "date_of_joining"]
    )

    # Exits in period
    separations = frappe.get_all(
        "Employee",
        filters={
            "company": company,
            "relieving_date": ["between", [from_d, to_d]]
        },
        fields=["name", "employee_name", "department", "relieving_date"]
    )

    # Internal transfers/promotions in period
    assignments = frappe.get_all(
        "Salary Structure Assignment",
        filters={
            "company": company,
            "docstatus": 1,
            "from_date": ["between", [from_d, to_d]],
            "tlc_decision_reason": ["in", ["Promotion", "Special", "Periodic"]]
        },
        fields=["name", "employee", "from_date", "base", "tlc_decision_reason"]
    )

    return {
        "company": company,
        "from_date": str(from_d),
        "to_date": str(to_d),
        "active_headcount": len(active),
        "by_department": by_dept,
        "new_hires": new_hires,
        "separations": separations,
        "promotions_adjustments": assignments
    }


def check_payroll_anomalies(payroll_entry_name):
    """AI / Automated review for payroll irregularities (HR-LG-26)."""
    check_payroll_permission()
    entry = frappe.get_doc("Payroll Entry", payroll_entry_name)
    slips = frappe.get_all(
        "Salary Slip",
        filters={"payroll_entry": payroll_entry_name, "docstatus": ["!=", 2]},
        fields=["name", "employee", "employee_name", "gross_pay", "net_pay", "start_date", "end_date"]
    )

    anomalies = []
    for slip in slips:
        emp = slip.employee

        # 1. Salary change without approved SSA decision
        ssas = frappe.get_all(
            "Salary Structure Assignment",
            filters={"employee": emp, "docstatus": 1, "from_date": ["between", [slip.start_date, slip.end_date]]},
            fields=["name", "base", "tlc_decision_reason", "tlc_decision_approved_by"]
        )
        for s in ssas:
            if not s.tlc_decision_approved_by:
                anomalies.append({
                    "type": "Unapproved Salary Change",
                    "employee": emp,
                    "employee_name": slip.employee_name,
                    "details": f"Salary Structure Assignment {s.name} changed without approved decision."
                })

        # 2. Overtime > 50% of base
        details = frappe.get_all(
            "Salary Detail",
            filters={"parent": slip.name},
            fields=["abbr", "amount"]
        )
        d_map = {d.abbr: flt(d.amount) for d in details}
        base_amt = d_map.get("LCB", 0.0)
        ot_amt = d_map.get("OT", 0.0) + d_map.get("OTP", 0.0)
        if base_amt > 0 and (ot_amt / base_amt) > 0.5:
            anomalies.append({
                "type": "Spike Overtime",
                "employee": emp,
                "employee_name": slip.employee_name,
                "details": f"Overtime pay {ot_amt:,.0f} VND exceeds 50% of base salary {base_amt:,.0f} VND."
            })

        # 3. Taxable income without tax ID
        pit = d_map.get("TNCN", 0.0)
        vn_tax_code = frappe.db.get_value("Employee", emp, "vn_tax_code")
        if pit > 0 and not vn_tax_code:
            anomalies.append({
                "type": "Missing Tax ID",
                "employee": emp,
                "employee_name": slip.employee_name,
                "details": f"Employee has PIT deduction {pit:,.0f} VND but missing Tax ID in profile."
            })

    return {
        "payroll_entry": payroll_entry_name,
        "total_anomalies": len(anomalies),
        "anomalies": anomalies
    }
