"""`bench tlc ...`: the maintenance commands of TLC HRM (like SAP transactions: check, compare, transport the customizing).

    bench --site <site> tlc config validate      the YAML matches the contracts (no site write)
    bench --site <site> tlc config plan          what apply would change on the site (exit code 2 when something differs)
    bench --site <site> tlc config apply         write the declared customizing (idempotent)
    bench --site <site> tlc config export <kind> [name]   a workflow edited on the desk, as YAML for tlc_hr/customizing
    bench --site <site> tlc doctor               operational checks: shifts, sites, approvers, accounts, closing
    bench --site <site> tlc seed run|reset-leave|reset-overtime|reset-periods|reset-payroll   demo data (test sites only)
    bench --site <site> tlc ai channels      make the Raven assistant and its channels visible to every demo person
"""

import click
import json
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
        frappe.db.rollback()
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
    except Exception:
        frappe.db.rollback()
        raise
    finally:
        frappe.destroy()
    for change in changes:
        click.echo(str(change))
    click.echo(f"Đã ghi {len(changes)} thay đổi" if changes else "Không có thay đổi")


@config.command("export")
@click.argument("kind", type=click.Choice(["roles", "custom_fields", "permissions", "workflow", "email_templates",
                                            "dashboards", "workspaces", "records", "accounts"]))
@click.argument("name", required=False)
@pass_context
def export(context, kind, name):
    """Print managed site configuration as schema-valid YAML; workflow requires NAME."""
    import yaml

    from tlc_hr.infrastructure.customizing.exporter import export_file
    from tlc_hr.infrastructure.customizing.loader import load_bundle

    connect(context)
    try:
        output = export_file(kind, load_bundle(), name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    finally:
        frappe.db.rollback()
        frappe.destroy()
    click.echo(yaml.safe_dump(output, allow_unicode=True, sort_keys=False, width=140))


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


@tlc.group("ai")
def ai():
    """Raven assistant and chat provisioning (demo site operator only)."""


@ai.command("agents")
@pass_context
def ai_agents(context):
    """Register @Leo, its closed tool surface and the assistant policy."""
    from tlc_hr.interface.agent_gateway import provision

    connect(context)
    try:
        click.echo(json.dumps(provision(), ensure_ascii=False))
    finally:
        frappe.destroy()


@ai.command("channels")
@pass_context
def ai_channels(context):
    """Give every demo person a Raven workspace membership, the shared channel and a bot DM."""
    from tlc_hr.interface.assistant_setup import provision_channels

    connect(context)
    try:
        click.echo(json.dumps(provision_channels(), ensure_ascii=False, indent=1))
    finally:
        frappe.destroy()


@tlc.command("seed")
@click.argument("step", type=click.Choice(["run", "reset-leave", "reset-overtime", "reset-periods", "reset-payroll", "salary", "reset-travel", "organization",
                                          "recruitment", "reset-recruitment", "lifecycle", "reset-lifecycle", "people-ops",
                                          "payroll-compliance", "travel-finance", "services", "reset-services"]))
@pass_context
def seed(context, step):
    """Demo data of TLC (made-up people); resets only on a site with allow_tests."""
    from importlib import import_module

    from tlc_hr import seed as demo

    connect(context)
    try:
        steps = {"run": demo.run, "reset-leave": demo.reset_leave_requests, "reset-overtime": demo.reset_overtime_requests,
                 "reset-periods": demo.reset_attendance_periods, "reset-payroll": demo.reset_payroll,
                 "salary": lambda: demo.salary_assignments(demo.load())}
        if step == "reset-travel":
            from tlc_hr.seed.travel_finance import reset as reset_travel
            steps[step] = reset_travel
        if step == "reset-recruitment":
            from tlc_hr.seed.recruitment import reset as reset_recruitment
            steps[step] = reset_recruitment
        if step == "reset-lifecycle":
            from tlc_hr.seed.lifecycle import reset as reset_lifecycle
            steps[step] = reset_lifecycle
        if step == "reset-services":
            from tlc_hr.seed.services import reset as reset_services
            steps[step] = reset_services
        if step in ("organization", "recruitment", "lifecycle", "people-ops", "payroll-compliance", "travel-finance", "services"):
            module = {"people-ops": "people_ops", "payroll-compliance": "payroll_compliance", "travel-finance": "travel_finance"}.get(step, step)
            steps[step] = import_module(f"tlc_hr.seed.{module}").run
        steps[step]()
        frappe.db.commit()
    finally:
        frappe.destroy()


commands = [tlc]
