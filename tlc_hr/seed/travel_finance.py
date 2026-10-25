"""Idempotent demo finance master data; never creates a payment, bank proof or approval."""
import frappe


COMPONENTS = (("Hoàn tạm ứng", "HTU", "Deduction", "141"),
              ("Điều chỉnh công sau chốt", "DCCSC", "Earning", "6421"),
              ("Khấu trừ công sau chốt", "KTCSC", "Deduction", "6421"))


def run(data=None):
    company = "TLC Demo"
    if not frappe.db.exists("Company", company):
        frappe.throw("Chạy dữ liệu tổ chức và hệ thống tài khoản trước dữ liệu tài chính.")
    accounts = {}
    for number in ("141", "3348", "1121", "6421"):
        account = frappe.db.get_value("Account", {"company": company, "account_number": number, "is_group": 0}, "name")
        if not account:
            frappe.throw(f"Thiếu tài khoản chi tiết TT200 {number} tại {company}.")
        accounts[number] = account
    for field, number in (("default_employee_advance_account", "141"), ("default_expense_claim_payable_account", "3348"),
                          ("default_bank_account", "1121")):
        if not frappe.db.get_value("Company", company, field):
            frappe.db.set_value("Company", company, field, accounts[number])
    for name in ("TLC Vé công tác", "TLC Lưu trú", "TLC Ăn công tác", "TLC Đi lại", "TLC Non-trade khác"):
        if not frappe.db.exists("Expense Claim Type", name):
            frappe.get_doc({"doctype": "Expense Claim Type", "expense_type": name, "tlc_non_trade": 1,
                "accounts": [{"company": company, "default_account": accounts["6421"]}]}).insert(ignore_permissions=True)
    if not frappe.db.exists("Purpose of Travel", "TLC Công tác"):
        frappe.get_doc({"doctype": "Purpose of Travel", "purpose_of_travel": "TLC Công tác"}).insert(ignore_permissions=True)
    for name, abbr, kind, number in COMPONENTS:
        if not frappe.db.exists("Salary Component", name):
            frappe.get_doc({"doctype": "Salary Component", "salary_component": name, "salary_component_abbr": abbr, "type": kind,
                "depends_on_payment_days": 0, "is_tax_applicable": int(kind == "Earning"),
                "accounts": [{"company": company, "account": accounts[number]}]}).insert(ignore_permissions=True)
    if not frappe.db.exists("Mode of Payment", "TLC Chuyển khoản"):
        frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": "TLC Chuyển khoản", "type": "Bank",
            "accounts": [{"company": company, "default_account": accounts["1121"]}]}).insert(ignore_permissions=True)
    # Native HRMS Expense Claim scope requires Expense Approver even when a TLC workflow is active.
    users = frappe.get_all("Has Role", filters={"role": ["in", ["TLC Line Manager", "TLC Director", "Accounts User"]],
                                               "parenttype": "User"}, pluck="parent")
    for user in set(users):
        frappe.get_doc("User", user).add_roles("Expense Approver")
    # Synthetic demo account identifiers are master data, not evidence of a transfer.
    for row in frappe.get_all("Employee", filters={"company": company, "status": "Active"}, fields=["name", "bank_ac_no"]):
        if not row.bank_ac_no:
            frappe.db.set_value("Employee", row.name, "bank_ac_no", "TLC-DEMO-" + row.name)
    # Payroll recovery remains OFF: consent alone must not enable a company policy.

def _drop(doctype, names):
    for name in names:
        doc = frappe.get_doc(doctype, name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc(doctype, name, force=1, ignore_permissions=True)


def reset():
    """Demo and UAT only: remove the travel/finance records a UAT run creates."""
    if not frappe.conf.get("allow_tests") and not frappe.flags.in_test:
        frappe.throw("reset_travel_finance runs only on a test site (site config allow_tests)")
    company = "TLC Demo"
    frappe.flags.tlc_demo_reset = True  # the reset may delete the snapshots the demo itself created
    refund_entries = [row.tlc_refund_entry for row in frappe.get_all(
        "Expense Claim", filters={"company": company, "tlc_refund_entry": ["is", "set"]}, fields=["tlc_refund_entry"])]
    refund_entries += [row[0] for row in frappe.db.sql(
        """select distinct je.name from `tabJournal Entry` je join `tabJournal Entry Account` a on a.parent=je.name
           where je.company=%s and a.reference_type='Employee Advance' and je.docstatus<2""", (company,))]
    # Break the travel <-> advance/claim links before deleting either side.
    for doctype, fields in (("Travel Request", {"tlc_employee_advance": None, "tlc_expense_claim": None}),
                            ("Employee Advance", {"tlc_travel_request": None, "tlc_payment_entry": None}),
                            ("Expense Claim", {"tlc_travel_request": None, "tlc_payment_entry": None, "tlc_refund_entry": None})):
        for name in frappe.get_all(doctype, filters={"company": company}, pluck="name"):
            frappe.db.set_value(doctype, name, fields)
    # Claims first: their advance rows hold dynamic links to the paying vouchers.
    _drop("Expense Claim", frappe.get_all("Expense Claim", filters={"company": company}, pluck="name"))
    # The refund is a Journal Entry credited to the advance; cancel it before the advance payment,
    # otherwise HRMS recalculates a positive return against a zero paid amount.
    _drop("Journal Entry", list(dict.fromkeys(name for name in refund_entries if name)))
    payments = [row.name for row in frappe.get_all("Payment Entry", filters={"company": company, "party_type": "Employee"},
                                                    fields=["name"])]
    _drop("Payment Entry", payments)
    _drop("Employee Advance", frappe.get_all("Employee Advance", filters={"company": company}, pluck="name"))
    # The On Duty attendance a trip produced may carry no company, so the link is the filter that always holds.
    _drop("Attendance Request", frappe.get_all("Attendance Request", filters={"tlc_travel_request": ["is", "set"]},
                                 pluck="name"))
    _drop("Attendance", frappe.get_all("Attendance", filters={"tlc_travel_request": ["is", "set"]}, pluck="name"))
    _drop("Travel Request", frappe.get_all("Travel Request", filters={"company": company}, pluck="name"))
    _drop("Leave Application", frappe.get_all("Leave Application", filters={"company": company, "docstatus": 0,
        "description": ["like", "%trùng công tác (UAT)%"]}, pluck="name"))
    frappe.flags.tlc_demo_reset = False
    print("reset: travel and finance records deleted")

