"""Run the appliers in dependency order: roles before the permissions and workflows that name them, records (shifts, overtime
type) before the cards that count them, cards and charts before the workspaces that show them."""

import frappe

from tlc_hr.infrastructure.customizing.dashboards import ChartApplier, NumberCardApplier, WorkspaceApplier
from tlc_hr.infrastructure.customizing.loader import load_bundle
from tlc_hr.infrastructure.customizing.metadata import (CustomFieldApplier, EmailTemplateApplier, PermissionApplier, RoleApplier,
                                                        WorkflowApplier, WorkflowMasterApplier)
from tlc_hr.infrastructure.customizing.records import AccountApplier, RecordApplier


def appliers():
    return [RoleApplier(), CustomFieldApplier(), PermissionApplier(), WorkflowMasterApplier(), WorkflowApplier(), EmailTemplateApplier(),
            RecordApplier(), AccountApplier(), NumberCardApplier(), ChartApplier(), WorkspaceApplier()]


def plan(bundle=None):
    bundle = bundle or load_bundle()
    return [change for applier in appliers() for change in applier.plan(bundle)]


def apply(bundle=None):
    bundle = bundle or load_bundle()
    changes = [change for applier in appliers() for change in applier.apply(bundle)]
    if changes:
        frappe.logger("tlc_hr.customizing").info({"applied": [str(c) for c in changes]})
    return changes
