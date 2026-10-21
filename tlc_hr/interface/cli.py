"""`bench tlc ...`: the maintenance commands of TLC HRM (like SAP transactions: check, compare, transport the customizing).

    bench --site <site> tlc config validate      the YAML matches the contracts (no site write)
    bench --site <site> tlc config plan          what apply would change on the site (exit code 2 when something differs)
    bench --site <site> tlc config apply         write the declared customizing (idempotent)
    bench --site <site> tlc config export-workflow <name>   a workflow edited on the desk, as YAML for tlc_hr/customizing
    bench --site <site> tlc doctor               operational checks: shifts, sites, approvers, accounts, closing
    bench --site <site> tlc seed run|reset-leave|reset-overtime|reset-periods   demo data (test sites only for resets)
"""

import click
import frappe
from frappe.commands import get_site, pass_context


def connect(context):
    site = get_site(context)
    frappe.init(site=site)
    frappe.connect()
    return site


@click.group("tlc")
def tlc():
    """TLC HRM: customizing, health checks and demo data."""


@tlc.group("config")
def config():
    """Declarative customizing in tlc_hr/customizing/*.yaml."""


@config.command("validate")
def validate():
    """Check every YAML file against the contracts and the references between files."""
    from tlc_hr.infrastructure.customizing.loader import load_bundle

    bundle = load_bundle()
    counts = {k: len(v) for k, v in bundle.model_dump().items() if isinstance(v, list)}
    click.echo("Hợp lệ: " + ", ".join(f"{k} {v}" for k, v in counts.items() if v))


@config.command("plan")
@pass_context
def plan(context):
    """Show what `apply` would create or change on the site."""
    from tlc_hr.infrastructure.customizing import engine

    connect(context)
    try:
        changes = engine.plan()
    finally:
        frappe.destroy()
    for change in changes:
        click.echo(str(change))
    click.echo(f"{len(changes)} thay đổi" if changes else "Không có thay đổi: site khớp YAML")
    if changes:
        raise SystemExit(2)


@config.command("apply")
@pass_context
def apply(context):
    """Write the customizing the YAML declares (only what differs)."""
    from tlc_hr.infrastructure.customizing import engine

    connect(context)
    try:
        changes = engine.apply()
        frappe.db.commit()
    finally:
        frappe.destroy()
    for change in changes:
        click.echo(str(change))
    click.echo(f"Đã ghi {len(changes)} thay đổi" if changes else "Không có thay đổi")


@config.command("export-workflow")
@click.argument("name")
@pass_context
def export_workflow(context, name):
    """Print a workflow of the site as customizing YAML (to bring a change made on the desk back into git)."""
    import yaml

    connect(context)
    try:
        wf = frappe.get_doc("Workflow", name)
        styles = {r.state: frappe.db.get_value("Workflow State", r.state, "style") or "" for r in wf.states}
        grouped = {}
        for t in wf.transitions:
            grouped.setdefault((t.state, t.action, t.next_state, t.condition or None, bool(t.allow_self_approval)), []).append(t.allowed)
    finally:
        frappe.destroy()
    doc = {"version": 1, "kind": "workflow", "workflow": {
        "name": wf.name, "doctype": wf.document_type,
        "states": [{k: v for k, v in {"state": r.state, "doc_status": int(r.doc_status), "allow_edit": r.allow_edit, "style": styles[r.state],
                                      "update_field": r.update_field, "update_value": r.update_value}.items() if v not in (None, "")}
                   for r in wf.states],
        "transitions": [{k: v for k, v in {"from": k0, "action": a, "to": to, "allowed": roles, "condition": cond,
                                           "allow_self_approval": selfok}.items() if v not in (None, False)}
                        for (k0, a, to, cond, selfok), roles in grouped.items()]}}
    click.echo(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=140))


@tlc.command("doctor")
@pass_context
def doctor(context):
    """Operational checks HR and IT run before a payroll month or after a change."""
    from tlc_hr.interface.doctor import run_checks

    connect(context)
    try:
        results = run_checks()
    finally:
        frappe.destroy()
    for ok, title, detail in results:
        click.echo(f"{'OK ' if ok else 'LỖI'} {title}" + (f": {detail}" if detail else ""))
    if not all(ok for ok, _t, _d in results):
        raise SystemExit(1)


@tlc.command("seed")
@click.argument("step", type=click.Choice(["run", "reset-leave", "reset-overtime", "reset-periods"]))
@pass_context
def seed(context, step):
    """Demo data of TLC (made-up people); resets only on a site with allow_tests."""
    from tlc_hr import seed as demo

    connect(context)
    try:
        {"run": demo.run, "reset-leave": demo.reset_leave_requests, "reset-overtime": demo.reset_overtime_requests,
         "reset-periods": demo.reset_attendance_periods}[step]()
        frappe.db.commit()
    finally:
        frappe.destroy()


commands = [tlc]
