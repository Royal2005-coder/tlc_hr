"""Accounts by number (types and company defaults are declared in customizing/accounts.yaml)."""

import frappe


def account_of(company, number):
    return frappe.db.get_value("Account", {"company": company, "account_number": number, "is_group": 0})
