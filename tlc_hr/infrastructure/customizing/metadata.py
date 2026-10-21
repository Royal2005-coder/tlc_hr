"""Appliers of the security and process metadata: roles, custom fields, permissions, workflows, e-mail templates."""

import frappe

from tlc_hr.contracts.customizing import RIGHTS
from tlc_hr.infrastructure.customizing.base import ResourceApplier, differing, same

MODULE = "TLC HR"


class RoleApplier(ResourceApplier):
    kind = "role"

    def items(self, bundle):
        return bundle.roles

    def name_of(self, spec):
        return spec.name

    def diff(self, spec):
        if not frappe.db.exists("Role", spec.name):
            return ()
        current = frappe.db.get_value("Role", spec.name, ["desk_access", "home_page"], as_dict=True)
        return differing(current, {"desk_access": spec.desk_access, "home_page": spec.home_page})

    def write(self, spec):
        if frappe.db.exists("Role", spec.name):
            frappe.db.set_value("Role", spec.name, {"desk_access": int(spec.desk_access), "home_page": spec.home_page})
        else:
            frappe.get_doc({"doctype": "Role", "role_name": spec.name, "desk_access": int(spec.desk_access),
                            "home_page": spec.home_page}).insert(ignore_permissions=True)


class CustomFieldApplier(ResourceApplier):
    kind = "custom field"

    def items(self, bundle):
        return [(group.doctype, f) for group in bundle.custom_fields for f in group.fields]

    def name_of(self, spec):
        return f"{spec[0]}.{spec[1].fieldname}"

    @staticmethod
    def values(field):
        return {k: (int(v) if isinstance(v, bool) else v) for k, v in field.model_dump(exclude_unset=True).items()}

    def diff(self, spec):
        doctype, field = spec
        name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": field.fieldname})
        if not name:
            return ()
        wanted = {k: v for k, v in self.values(field).items() if k != "fieldname"}
        return differing(frappe.db.get_value("Custom Field", name, list(wanted), as_dict=True), wanted)

    def write(self, spec):
        from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

        doctype, field = spec
        create_custom_fields({doctype: [self.values(field)]}, update=True)


class PermissionApplier(ResourceApplier):
    kind = "permission"

    def items(self, bundle):
        return bundle.permissions

    def name_of(self, spec):
        return f"{spec.doctype} / {spec.role} / mức {spec.permlevel}: {spec.rights}"

    @staticmethod
    def wanted(spec):
        return {right: int(letter in spec.rights) for letter, right in RIGHTS.items()}

    def diff(self, spec):
        filters = {"parent": spec.doctype, "role": spec.role, "permlevel": spec.permlevel}
        if not frappe.db.exists("Custom DocPerm", filters):
            return ()
        wanted = self.wanted(spec)
        return differing(frappe.db.get_value("Custom DocPerm", filters, list(wanted), as_dict=True), wanted)

    def write(self, spec):
        from frappe.permissions import add_permission, update_permission_property

        if not frappe.db.exists("Custom DocPerm", {"parent": spec.doctype, "role": spec.role, "permlevel": spec.permlevel}):
            add_permission(spec.doctype, spec.role, spec.permlevel)
        for right, value in self.wanted(spec).items():
            update_permission_property(spec.doctype, spec.role, spec.permlevel, right, value, validate=False)


class WorkflowMasterApplier(ResourceApplier):
    """Workflow states (with their colour) and action names the workflows use."""

    kind = "workflow state/action"

    def items(self, bundle):
        states = {s.state: s.style for wf in bundle.workflows for s in wf.states}
        actions = {t.action for wf in bundle.workflows for t in wf.transitions}
        return [("Workflow State", name, style) for name, style in states.items()] + [("Workflow Action Master", a, None) for a in sorted(actions)]

    def name_of(self, spec):
        return f"{spec[0]}: {spec[1]}"

    def diff(self, spec):
        doctype, name, style = spec
        if not frappe.db.exists(doctype, name):
            return ()
        if doctype == "Workflow State" and not same(frappe.db.get_value(doctype, name, "style"), style):
            return ("style",)
        return None

    def write(self, spec):
        doctype, name, style = spec
        if frappe.db.exists(doctype, name):
            frappe.db.set_value(doctype, name, "style", style)
        elif doctype == "Workflow State":
            frappe.get_doc({"doctype": doctype, "workflow_state_name": name, "style": style}).insert(ignore_permissions=True)
        else:
            frappe.get_doc({"doctype": doctype, "workflow_action_name": name}).insert(ignore_permissions=True)


class WorkflowApplier(ResourceApplier):
    kind = "workflow"

    def items(self, bundle):
        return bundle.workflows

    def name_of(self, spec):
        return f"{spec.name} ({spec.doctype})"

    @staticmethod
    def states(rows):
        return sorted((r["state"], str(r["doc_status"]), r["allow_edit"], r.get("update_field") or "", r.get("update_value") or "") for r in rows)

    @staticmethod
    def transitions(rows):
        return sorted((r["state"], r["action"], r["next_state"], r["allowed"], r.get("condition") or "", int(r.get("allow_self_approval") or 0))
                      for r in rows)

    @staticmethod
    def rows(spec):
        states = [{"state": s.state, "doc_status": str(s.doc_status), "allow_edit": s.allow_edit, "update_field": s.update_field,
                   "update_value": s.update_value} for s in spec.states]
        transitions = [{"state": t.from_state, "action": t.action, "next_state": t.to, "allowed": role, "condition": t.condition,
                        "allow_self_approval": int(t.allow_self_approval)} for t in spec.transitions for role in t.allowed]
        return states, transitions

    def diff(self, spec):
        if not frappe.db.exists("Workflow", spec.name):
            return ()
        doc = frappe.get_doc("Workflow", spec.name)
        states, transitions = self.rows(spec)
        found = []
        if doc.document_type != spec.doctype or not doc.is_active or bool(doc.send_email_alert) != spec.send_email_alert:
            found.append("settings")
        if self.states([r.as_dict() for r in doc.states]) != self.states(states):
            found.append("states")
        if self.transitions([r.as_dict() for r in doc.transitions]) != self.transitions(transitions):
            found.append("transitions")
        return tuple(found) or None

    def write(self, spec):
        states, transitions = self.rows(spec)
        if frappe.db.exists("Workflow", spec.name):
            doc = frappe.get_doc("Workflow", spec.name)
            doc.states, doc.transitions = [], []
        else:
            doc = frappe.get_doc({"doctype": "Workflow", "workflow_name": spec.name, "document_type": spec.doctype})
        doc.update({"document_type": spec.doctype, "is_active": 1, "workflow_state_field": "workflow_state",
                    "send_email_alert": int(spec.send_email_alert), "override_status": 0})
        for row in states:
            doc.append("states", row)
        for row in transitions:
            doc.append("transitions", row)
        doc.save(ignore_permissions=True)


class EmailTemplateApplier(ResourceApplier):
    kind = "email template"

    def items(self, bundle):
        return bundle.email_templates

    def name_of(self, spec):
        return spec.name

    def diff(self, spec):
        if not frappe.db.exists("Email Template", spec.name):
            return ()
        current = frappe.db.get_value("Email Template", spec.name, ["subject", "response_html", "use_html"], as_dict=True)
        found = list(differing(current, {"subject": spec.subject, "response_html": spec.html, "use_html": 1}) or ())
        if spec.hr_setting and frappe.db.get_single_value("HR Settings", spec.hr_setting) != spec.name:
            found.append(f"HR Settings.{spec.hr_setting}")
        return tuple(found) or None

    def write(self, spec):
        exists = frappe.db.exists("Email Template", spec.name)
        doc = frappe.get_doc("Email Template", spec.name) if exists else frappe.new_doc("Email Template")
        doc.update({"name": spec.name, "subject": spec.subject, "use_html": 1, "response_html": spec.html, "response": spec.html})
        doc.save(ignore_permissions=True) if exists else doc.insert(ignore_permissions=True)
        if spec.hr_setting:
            frappe.db.set_single_value("HR Settings", spec.hr_setting, spec.name)
