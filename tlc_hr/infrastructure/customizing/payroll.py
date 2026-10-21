"""Applier of customizing/payroll.yaml: salary components with their accounts per company, and the salary structure.

A salary structure is frozen once a submitted payslip uses it: then a change of the rendered formulas is refused and asks for a
new structure name in payroll.yaml (a new version, like a new law). Before any payslip, the formulas are corrected in place.
"""

import frappe

from tlc_hr.infrastructure.customizing.base import ResourceApplier, differing, same
from tlc_hr.infrastructure.customizing.loader import CustomizingError
from tlc_hr.infrastructure.customizing.payroll_formulas import render


def account_of(company, number):
    return frappe.db.get_value("Account", {"company": company, "account_number": number, "is_group": 0}) if number else None


class SalaryComponentApplier(ResourceApplier):
    kind = "salary component"

    def items(self, bundle):
        if not bundle.payroll:
            return []
        return [(company, c) for company in frappe.get_all("Company", pluck="name") for c in bundle.payroll.components
                if account_of(company, c.account)]

    def name_of(self, spec):
        return f"{spec[1].abbr} {spec[1].name} ({spec[0]})"

    @staticmethod
    def find(component):
        return frappe.db.get_value("Salary Component", {"salary_component_abbr": component.abbr})

    def diff(self, spec):
        company, component = spec
        name = self.find(component)
        if not name:
            return ()
        doc = frappe.get_doc("Salary Component", name)
        found = list(differing(doc.as_dict(), {"type": component.type, "depends_on_payment_days": component.depends_on_payment_days,
                                               "remove_if_zero_valued": 1}) or ())
        row = next((r for r in doc.accounts if r.company == company), None)
        if not row or not same(row.account, account_of(company, component.account)) or (
                component.liability_account and not same(row.liability_account, account_of(company, component.liability_account))):
            found.append("accounts")
        return tuple(found) or None

    def write(self, spec):
        company, component = spec
        name = self.find(component)
        doc = frappe.get_doc("Salary Component", name) if name else frappe.get_doc({
            "doctype": "Salary Component", "salary_component": component.name, "salary_component_abbr": component.abbr, "type": component.type})
        if doc.type != component.type and frappe.db.exists("Salary Detail", {"salary_component": doc.name, "docstatus": 1,
                                                                            "parenttype": "Salary Slip"}):
            raise CustomizingError(f"{doc.name}: đã có phiếu lương dùng loại {doc.type}, không đổi sang {component.type}")
        doc.update({"type": component.type, "depends_on_payment_days": int(component.depends_on_payment_days),
                    "remove_if_zero_valued": 1, "statistical_component": 0, "do_not_include_in_total": 0})
        row = next((r for r in doc.accounts if r.company == company), None) or doc.append("accounts", {"company": company})
        row.account = account_of(company, component.account)
        if component.liability_account:
            row.liability_account = account_of(company, component.liability_account)
        doc.flags.ignore_permissions = True
        doc.save() if not doc.is_new() else doc.insert()


class SalaryStructureApplier(ResourceApplier):
    kind = "salary structure"

    def items(self, bundle):
        if not bundle.payroll:
            return []
        return [(company, bundle.payroll) for company in frappe.get_all("Company", pluck="name")
                if account_of(company, bundle.payroll.components[0].account)]

    def name_of(self, spec):
        return f"{spec[1].structure.name} ({spec[0]})"

    @staticmethod
    def rows(payroll):
        return {
            table: [(r.abbr, render(r.abbr, r.formula), r.condition or "") for r in getattr(payroll.structure, table)]
            for table in ("earnings", "deductions", "employer_contributions")
        }

    def diff(self, spec):
        _company, payroll = spec
        if not frappe.db.exists("Salary Structure", payroll.structure.name):
            return ()
        doc = frappe.get_doc("Salary Structure", payroll.structure.name)
        current = {
            table: [(r.abbr, r.formula or "", r.condition or "") for r in doc.get(table)]
            for table in ("earnings", "deductions", "employer_contributions")
        }
        return None if current == self.rows(payroll) else ("formulas",)

    def write(self, spec):
        company, payroll = spec
        if frappe.db.exists("Salary Structure", payroll.structure.name):
            self.correct(payroll)
            return
        component = {c.abbr: c.name for c in payroll.components}

        def row(spec_row):
            return {"salary_component": frappe.db.get_value("Salary Component", {"salary_component_abbr": spec_row.abbr}) or component[spec_row.abbr],
                    "abbr": spec_row.abbr, "amount_based_on_formula": 1, "formula": render(spec_row.abbr, spec_row.formula),
                    "condition": spec_row.condition or "", "statistical_component": 0, "do_not_include_in_total": 0}

        doc = frappe.get_doc({"doctype": "Salary Structure", "__newname": payroll.structure.name, "company": company,
                              "payroll_frequency": payroll.structure.payroll_frequency, "is_active": "Yes",
                              "currency": frappe.db.get_value("Company", company, "default_currency"),
                              "earnings": [row(r) for r in payroll.structure.earnings],
                              "deductions": [row(r) for r in payroll.structure.deductions],
                              "employer_contributions": [row(r) for r in payroll.structure.employer_contributions]})
        doc.insert(ignore_permissions=True)
        doc.submit()

    def correct(self, payroll):
        name = payroll.structure.name
        if frappe.db.exists("Salary Slip", {"salary_structure": name, "docstatus": 1}):
            raise CustomizingError(f"Cấu trúc lương {name} đã có phiếu lương: đặt tên mới trong payroll.yaml để tạo phiên bản mới")
        doc = frappe.get_doc("Salary Structure", name)
        wanted = self.rows(payroll)
        for table, desired in wanted.items():
            if [r.abbr for r in doc.get(table)] != [w[0] for w in desired]:
                raise CustomizingError(f"Cấu trúc lương {name}: thêm hay bớt dòng cần tên cấu trúc mới trong payroll.yaml")
        for table, desired in wanted.items():
            for row, (_abbr, formula, condition) in zip(doc.get(table), desired):
                frappe.db.set_value("Salary Detail", row.name, {"formula": formula, "condition": condition,
                                                               "statistical_component": 0, "do_not_include_in_total": 0})
        doc.add_comment("Info", "Công thức được cập nhật theo customizing/payroll.yaml (chưa có phiếu lương nào dùng cấu trúc này).")
