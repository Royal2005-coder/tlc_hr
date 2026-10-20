"""Accounting set-up that payroll, employee advances and expense claims need on the TT200 chart (idempotent).

ERPNext refuses a payroll payable account that is not of type Payable and an employee advance account that is not Receivable;
the TT200 chart of erpnextvn creates the accounts without these types, so they are set here by account number.
"""

import frappe

# account number -> account type
ACCOUNT_TYPES = {
    "141": "Receivable",    # Tạm ứng (employee advances, party Employee)
    "3341": "Payable",      # Phải trả công nhân viên (payroll payable)
    "3348": "Payable",      # Phải trả người lao động khác (expense claims payable)
    "1111": "Cash",
    "1121": "Bank",
    "622": "Expense Account",
    "6271": "Expense Account",
    "6421": "Expense Account",
}

# company field -> account number
COMPANY_DEFAULTS = {
    "default_payroll_payable_account": "3341",
    "default_employee_advance_account": "141",
    "default_expense_claim_payable_account": "3348",
    "default_cash_account": "1111",
    "default_bank_account": "1121",
}


def account_of(company, number):
    return frappe.db.get_value("Account", {"company": company, "account_number": number, "is_group": 0})


def ensure_accounts(company):
    """Types and company defaults; skipped while the company does not exist yet (fresh install before the setup wizard)."""
    if not company or not frappe.db.exists("Company", company):
        return
    for number, account_type in ACCOUNT_TYPES.items():
        name = account_of(company, number)
        if name and frappe.db.get_value("Account", name, "account_type") != account_type:
            frappe.db.set_value("Account", name, "account_type", account_type)
    values = {field: account_of(company, number) for field, number in COMPANY_DEFAULTS.items()}
    current = frappe.db.get_value("Company", company, list(values), as_dict=True)
    changed = {field: name for field, name in values.items() if name and current.get(field) != name}
    if changed:
        frappe.db.set_value("Company", company, changed)
