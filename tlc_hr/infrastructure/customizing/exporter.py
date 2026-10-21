"""Export the managed A0 resources, never arbitrary site data or credentials."""

import datetime
import json
from decimal import Decimal

import frappe

from tlc_hr.contracts.customizing import RIGHTS, CustomizingFile

KINDS = ("roles", "custom_fields", "permissions", "workflow", "email_templates", "dashboards", "workspaces", "records", "accounts")


def scalar(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        seconds = int(value.total_seconds())
        return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return value


def fields(doc, spec, mapping=None):
    """Only fields represented by the contract, converting Frappe Check/Int values explicitly."""
    mapping = mapping or {}
    result = {}
    current = doc.as_dict()
    for key, original in spec.model_dump().items():
        field = mapping.get(key, key)
        value = current.get(field)
        if field not in current:
            result[key] = original
        elif value is None:
            result[key] = None
        elif isinstance(original, bool):
            result[key] = bool(value)
        elif isinstance(original, int):
            result[key] = int(value)
        else:
            result[key] = scalar(value)
    return result


def workflow(name):
    doc = frappe.get_doc("Workflow", name)
    transitions = {}
    for row in doc.transitions:
        key = (row.state, row.action, row.next_state, row.condition or None, bool(row.allow_self_approval))
        transitions.setdefault(key, []).append(row.allowed)
    return {
        "name": doc.name, "doctype": doc.document_type, "send_email_alert": bool(doc.send_email_alert),
        "states": [{"state": r.state, "doc_status": int(r.doc_status), "allow_edit": r.allow_edit,
                    "style": frappe.db.get_value("Workflow State", r.state, "style") or "",
                    "update_field": r.update_field or None, "update_value": r.update_value or None} for r in doc.states],
        "transitions": [{"from": start, "action": action, "to": end, "allowed": roles, "condition": condition,
                         "allow_self_approval": self_approval}
                        for (start, action, end, condition, self_approval), roles in transitions.items()],
    }


def export_file(kind, bundle, name=None):
    """Return one schema-valid YAML document. Workflow can select an unmanaged name explicitly.

    Other kinds export only identities and record fields already declared in the bundle. New site resources must first be
    declared in YAML; this allowlist avoids accidentally exporting personal data or secrets from generic records.
    """
    if kind not in KINDS:
        raise ValueError(f"unsupported export kind: {kind}")
    if kind != "workflow" and name:
        raise ValueError("name is only accepted for workflow")
    output = {"version": 1, "kind": kind}
    if kind == "workflow":
        if not name:
            raise ValueError("workflow export requires a name")
        output["workflow"] = workflow(name)
    elif kind == "roles":
        output["roles"] = [fields(frappe.get_doc("Role", s.name), s) for s in bundle.roles]
    elif kind == "custom_fields":
        output["custom_fields"] = []
        for group in bundle.custom_fields:
            rows = []
            for spec in group.fields:
                record = frappe.db.get_value("Custom Field", {"dt": group.doctype, "fieldname": spec.fieldname})
                if not record:
                    raise ValueError(f"missing custom field: {group.doctype}.{spec.fieldname}")
                # Unset fields must stay unset: the applier deliberately manages only declared properties.
                row = fields(frappe.get_doc("Custom Field", record), spec)
                rows.append({k: v for k, v in row.items() if k in spec.model_fields_set})
            output["custom_fields"].append({"doctype": group.doctype, "fields": rows})
    elif kind == "permissions":
        output["permissions"] = []
        for spec in bundle.permissions:
            record = frappe.db.get_value("Custom DocPerm", {"parent": spec.doctype, "role": spec.role, "permlevel": spec.permlevel})
            if not record:
                raise ValueError(f"missing custom permission: {spec.doctype}/{spec.role}/{spec.permlevel}")
            doc = frappe.get_doc("Custom DocPerm", record)
            output["permissions"].append({**spec.model_dump(), "rights": "".join(k for k, field in RIGHTS.items() if doc.get(field))})
    elif kind == "email_templates":
        output["email_templates"] = [fields(frappe.get_doc("Email Template", s.name), s, {"html": "response_html"})
                                     for s in bundle.email_templates]
    elif kind == "dashboards":
        output["number_cards"], output["charts"] = [], []
        for spec in bundle.number_cards:
            doc = frappe.get_doc("Number Card", spec.name)
            row = fields(doc, spec, {"doctype": "document_type", "field": "aggregate_function_based_on"})
            row["filters"] = json.loads(doc.filters_json or "[]")
            row["dynamic_filters"] = json.loads(doc.dynamic_filters_json or "[]")
            output["number_cards"].append(row)
        for spec in bundle.charts:
            doc = frappe.get_doc("Dashboard Chart", spec.name)
            row = fields(doc, spec)
            row["filters"] = json.loads(doc.filters_json or "[]")
            output["charts"].append(row)
    elif kind == "workspaces":
        output["workspaces"], shortcuts = [], {}
        for spec in bundle.workspaces:
            doc = frappe.get_doc("Workspace", spec.title)
            row = fields(doc, spec, {"sequence": "sequence_id"})
            row.update({"roles": [r.role for r in doc.roles], "cards": [r.number_card_name for r in doc.number_cards],
                        "charts": [r.chart_name for r in doc.charts], "shortcuts": [r.label for r in doc.shortcuts], "quick_list": None})
            if len(doc.quick_lists) > 1:
                raise ValueError(f"workspace {spec.title}: the contract supports one quick list")
            if doc.quick_lists:
                quick = doc.quick_lists[0]
                row["quick_list"] = {"doctype": quick.document_type, "label": quick.label,
                                     "filters": json.loads(quick.quick_list_filter or "[]")}
            for shortcut in doc.shortcuts:
                current = {"label": shortcut.label, "type": shortcut.type, "link_to": shortcut.link_to or None,
                           "url": shortcut.url or None, "doc_view": shortcut.doc_view or "", "color": shortcut.color or "Grey",
                           "stats_filter": json.loads(shortcut.stats_filter) if shortcut.stats_filter else None,
                           "format": shortcut.format or None}
                if shortcut.label in shortcuts and shortcuts[shortcut.label] != current:
                    raise ValueError(f"shortcut {shortcut.label}: differs between workspaces")
                shortcuts[shortcut.label] = current
            output["workspaces"].append(row)
        output["shortcuts"] = list(shortcuts.values())
    elif kind == "records":
        output["records"] = []
        for spec in bundle.records:
            doc = frappe.get_doc(spec.doctype, spec.name or spec.doctype)
            output["records"].append({"doctype": spec.doctype, "name": spec.name, "on_create": spec.on_create,
                                      "values": {k: scalar(doc.get(k)) for k in spec.values},
                                      "tables": {table: [{k: scalar(row.get(k)) for k in set().union(*(r.keys() for r in template))}
                                                         for row in doc.get(table)] for table, template in spec.tables.items()}})
    elif kind == "accounts":
        if not bundle.accounts:
            raise ValueError("no managed accounts declared")
        types, defaults = {}, {}
        for company in frappe.get_all("Company", pluck="name"):
            for number in bundle.accounts.account_types:
                value = frappe.db.get_value("Account", {"company": company, "account_number": number, "is_group": 0}, "account_type")
                if value is None:
                    raise ValueError(f"company {company}: missing account {number}")
                if number in types and types[number] != value:
                    raise ValueError(f"account {number}: company-specific types cannot be represented by this contract")
                types[number] = value
            for field in bundle.accounts.company_defaults:
                account = frappe.db.get_value("Company", company, field)
                number = frappe.db.get_value("Account", account, "account_number") if account else None
                if not number or (field in defaults and defaults[field] != number):
                    raise ValueError(f"company default {field}: missing or company-specific account number")
                defaults[field] = number
        output["accounts"] = {"account_types": types, "company_defaults": defaults}
    return CustomizingFile.model_validate(output).model_dump(mode="json", by_alias=True, exclude_unset=True)
