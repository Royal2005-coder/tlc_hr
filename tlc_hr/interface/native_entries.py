"""Entry points for the TLC screens inside the native Desk workspaces.

People open Frappe HR > Recruitment (or HR Setup) and expect the hiring board, the AI ledger and the assistant to be
one click away, not hidden behind a workspace name they have to remember. These rows are shortcut records of those
native workspaces, so nothing of their own content is replaced. The sync is idempotent: one row per label, extras
removed, and the workspace cache is dropped so the sidebar shows the change on the next load.
"""

import frappe

KANBAN = ("/desk/job-applicant/view/kanban/TLC%20Tuy%E1%BB%83n%20d%E1%BB%A5ng%206%20b%C6%B0%E1%BB%9Bc")
ENTRIES = (
    ("Recruitment", "TLC Kanban 6 bước", "URL", KANBAN, "Blue"),
    ("Recruitment", "TLC Ứng viên & chấm CV", "DocType", "Job Applicant", "Cyan"),
    ("Recruitment", "TLC Nhật ký AI", "DocType", "TLC AI Trace Log", "Purple"),
    ("Recruitment", "TLC Trợ lý AI (Chat)", "Page", "tro-ly-ai", "Green"),
    ("Recruitment", "TLC Mẫu thư tuyển dụng", "DocType", "Email Template", "Orange"),
    ("HR Setup", "TLC Trợ lý AI (Chat)", "Page", "tro-ly-ai", "Green"),
    ("HR Setup", "TLC Tuyển dụng 6 bước", "URL", KANBAN, "Blue"),
    ("HR Setup", "TLC Nhật ký AI", "DocType", "TLC AI Trace Log", "Purple"),
    ("Home", "TLC Trợ lý AI (Chat)", "Page", "tro-ly-ai", "Green"),
    ("Home", "TLC Tuyển dụng 6 bước", "URL", KANBAN, "Blue"),
)


def _values(parent, label, kind, target, color):
    return {"parenttype": "Workspace", "parentfield": "shortcuts", "parent": parent, "label": label, "type": kind,
            "color": color,
            "link_to": None if kind == "URL" else target,
            "url": target if kind == "URL" else None,
            "doc_view": "List" if kind == "DocType" else None}


def ensure():
    """Create or repair the shortcut rows of the native workspaces; safe to run on every migrate."""
    touched, created, repaired = set(), 0, 0
    for parent, label, kind, target, color in ENTRIES:
        if not frappe.db.exists("Workspace", parent):
            continue
        values = _values(parent, label, kind, target, color)
        names = frappe.get_all("Workspace Shortcut", filters={"parent": parent, "label": label},
                               pluck="name", order_by="idx asc")
        if names:
            frappe.db.set_value("Workspace Shortcut", names[0], values, update_modified=False)
            for extra in names[1:]:
                frappe.delete_doc("Workspace Shortcut", extra, force=1, ignore_permissions=True)
                repaired += 1
        else:
            frappe.get_doc({"doctype": "Workspace Shortcut", **values}).insert(ignore_permissions=True)
            created += 1
        touched.add(parent)
    frappe.db.commit()
    for parent in touched:
        frappe.clear_cache(doctype="Workspace")
    return {"created": created, "duplicates_removed": repaired, "workspaces": sorted(touched)}
