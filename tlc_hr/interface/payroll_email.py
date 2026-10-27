"""A salary slip that is issued even when its mail cannot be rendered.

Frappe HR emails every payslip inside the payroll submission and rolls the whole payroll back when the PDF or the
mail server fails (a transient 404 on a print asset is enough). The payslip itself is already computed and signed at
that point, so the failure is recorded and the mail can be sent again from the payroll workspace instead of
cancelling the signing.
"""

import frappe
from hrms.payroll.doctype.salary_slip.salary_slip import SalarySlip


class ResilientSalarySlip(SalarySlip):
    def email_salary_slip(self):
        try:
            return super().email_salary_slip()
        except Exception as exc:
            frappe.log_error(title=f"Salary Slip {self.name}: payslip mail deferred",
                             message=frappe.get_traceback()[-3000:])
            self.add_comment("Comment", text=f"Phiếu lương đã ghi sổ nhưng chưa gửi được thư: {str(exc)[:300]}")
            return None
