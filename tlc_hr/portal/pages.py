"""Controllers of the TLC People pages (www/tlc/*.py import their get_context from here)."""

import frappe
from frappe.utils import getdate

from tlc_hr.portal import data
from tlc_hr.portal.common import base_context


def deny(context):
    """A page the role may not open: back to the home page."""
    frappe.local.flags.redirect_location = "/tlc"
    raise frappe.Redirect


def home(context):
    base_context(context, "home", "/tlc")
    person, f, roles = context.person, context.f, context.roles
    inbox = data.approvals_inbox(roles, person) if f.is_approver else []
    context.update({
        "inbox": data.decision_support(inbox[:3]), "inbox_total": len(inbox),
        "balances": data.balances(person.name) if person else [],
        "mine": [r for r in data.requests_of(person.name, 8) if r.upcoming] if person else [],
        "whos_out": data.whos_out(person, f), "celebrations": data.celebrations(person, f), "holidays": data.holidays(3),
        "company": data.company_report() if f.sees_company else None,
        "team_size": len(data.descendants(person.name)) if person and f.is_manager else 0,
    })


def leave(context):
    base_context(context, "leave", "/tlc/leave")
    person = context.person
    context.update({
        "balances": data.balances(person.name) if person else [],
        "requests": data.requests_of(person.name, 30) if person else [],
        "holidays": data.holidays(8),
    })


def me(context):
    base_context(context, "me", "/tlc/me")
    person = context.person
    if not person:
        return
    person.years = round((getdate(context.today) - getdate(person.date_of_joining)).days / 365.0, 1) if person.date_of_joining else 0
    context.update({"balances": data.balances(person.name), "requests": data.requests_of(person.name, 5),
                    "pay": data.pay_estimate(person.name)})


def people(context):
    base_context(context, "people", "/tlc/people")
    rows, sites = data.directory()
    context.update({"people": rows, "sites": sites, "tree": data.org_tree(rows)})


def team(context):
    base_context(context, "team", "/tlc/team")
    f = context.f
    if not (f.is_manager or f.sees_company):
        deny(context)
    department = frappe.form_dict.get("dept") if f.sees_company else None
    members = data.team_rows(data.team_members(context.person, f, department))
    context.update({
        "members": members, "calendar": data.team_calendar(members, frappe.form_dict.get("start")),
        "departments": sorted(frappe.get_all("Department", filters={"company": data.COMPANY}, pluck="name")) if f.sees_company else [],
        "dept": department or "", "away_today": sum(1 for m in members if m.away_today),
        "pending_total": sum(m.pending for m in members),
    })


def approvals(context):
    base_context(context, "approvals", "/tlc/approvals")
    if not context.f.is_approver:
        deny(context)
    context.inbox = data.decision_support(data.approvals_inbox(context.roles, context.person))


def reports(context):
    base_context(context, "reports", "/tlc/reports")
    if not context.f.sees_company:
        deny(context)
    context.r = data.company_report()
