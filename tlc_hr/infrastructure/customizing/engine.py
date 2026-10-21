"""Run the appliers in dependency order: roles before the permissions and workflows that name them, records (shifts, overtime
type) before the cards that count them, cards and charts before the workspaces that show them."""

import frappe

from tlc_hr.infrastructure.customizing.loader import load_bundle


def appliers():
    from tlc_hr.infrastructure.customizing.dashboards import ChartApplier, NumberCardApplier, WorkspaceApplier
    from tlc_hr.infrastructure.customizing.metadata import (CustomFieldApplier, EmailTemplateApplier, PermissionApplier, RoleApplier,
                                                          WorkflowApplier, WorkflowMasterApplier)
    from tlc_hr.infrastructure.customizing.payroll import SalaryComponentApplier, SalaryStructureApplier
    from tlc_hr.infrastructure.customizing.records import AccountApplier, DocTypeApplier, RecordApplier

    return [RoleApplier(), DocTypeApplier(), CustomFieldApplier(), PermissionApplier(), WorkflowMasterApplier(), WorkflowApplier(), EmailTemplateApplier(),
            AccountApplier(), SalaryComponentApplier(), RecordApplier(), SalaryStructureApplier(), NumberCardApplier(), ChartApplier(),
            WorkspaceApplier()]


def plan(bundle=None):
    bundle = bundle or load_bundle()
    return [change for applier in appliers() for change in applier.plan(bundle)]


def apply(bundle=None):
    bundle = bundle or load_bundle()
    # The caller owns commit (CLI or migrate). Never leave earlier data writes pending
    # after a later resource fails. MariaDB schema DDL is not rollbackable; see OPERATIONS.
    try:
        changes = [change for applier in appliers() for change in applier.apply(bundle)]
    except Exception:
        frappe.db.rollback()
        raise
    if changes:
        frappe.logger("tlc_hr.customizing").info({"applied": [str(c) for c in changes]})
    return changes
