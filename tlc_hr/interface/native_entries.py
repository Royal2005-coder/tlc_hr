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


# The sidebar link cannot carry a view or a board, so the six-step board stays a shortcut of the workspace (and of
# the TLC AI menu on the top bar); the sidebar carries the screens a person opens by name.
LINKS = (
    ("Recruitment", "TLC Ứng viên & chấm CV", "DocType", "Job Applicant"),
    ("Recruitment", "TLC Nhật ký AI", "DocType", "TLC AI Trace Log"),
    ("Recruitment", "TLC Trợ lý AI (Chat)", "Page", "tro-ly-ai"),
    ("Recruitment", "TLC Mẫu thư tuyển dụng", "DocType", "Email Template"),
    ("HR Setup", "TLC Trợ lý AI (Chat)", "Page", "tro-ly-ai"),
    ("HR Setup", "TLC Nhật ký AI", "DocType", "TLC AI Trace Log"),
)


def _link_values(parent, label, link_type, target):
    return {"parenttype": "Workspace", "parentfield": "links", "parent": parent, "type": "Link", "label": label,
            "link_type": link_type, "link_to": target, "is_query_report": 0, "hidden": 0, "onboard": 0}


def ensure_links():
    """The card in the sidebar of the native workspace: the links table is what the desk renders as the left menu."""
    touched = 0
    for parent in ("Recruitment", "HR Setup"):
        if not frappe.db.exists("Workspace", parent):
            continue
        card = frappe.get_all("Workspace Link", filters={"parent": parent, "type": "Card Break", "label": "TLC AI"},
                              pluck="name")
        if not card:
            frappe.get_doc({"doctype": "Workspace Link", "parenttype": "Workspace", "parentfield": "links",
                            "parent": parent, "type": "Card Break", "label": "TLC AI", "link_count": 5,
                            "hidden": 0}).insert(ignore_permissions=True)
            touched += 1
        for label, link_type, target in ((row[1], row[2], row[3]) for row in LINKS if row[0] == parent):
            values = _link_values(parent, label, link_type, target)
            names = frappe.get_all("Workspace Link", filters={"parent": parent, "type": "Link", "label": label},
                                   pluck="name", order_by="idx asc")
            if names:
                frappe.db.set_value("Workspace Link", names[0], values, update_modified=False)
                for extra in names[1:]:
                    frappe.delete_doc("Workspace Link", extra, force=1, ignore_permissions=True)
            else:
                frappe.get_doc({"doctype": "Workspace Link", **values}).insert(ignore_permissions=True)
            touched += 1
        count = frappe.db.count("Workspace Link", {"parent": parent, "type": "Link"})
        for name in frappe.get_all("Workspace Link", filters={"parent": parent, "type": "Card Break", "label": "TLC AI"},
                                   pluck="name"):
            frappe.db.set_value("Workspace Link", name, "link_count", len([row for row in LINKS if row[0] == parent]))
    frappe.db.commit()
    return touched


def sync_content():
    """Put the shortcuts into the workspace layout itself.

    The desk renders a workspace from the saved `content` blocks, not from the shortcut table, so a row added here is
    invisible until a block names it — which is why HR Setup looked empty. Adding the block is what the "customise
    workspace" screen does for a person, and it stays idempotent: a label already on the page is left alone.
    """
    import json
    import random
    import string

    changed = 0
    for parent in sorted({row[0] for row in ENTRIES}):
        if not frappe.db.exists("Workspace", parent):
            continue
        raw = frappe.db.get_value("Workspace", parent, "content") or "[]"
        try:
            blocks = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(blocks, list):
            continue
        present = {block.get("data", {}).get("shortcut_name") for block in blocks if block.get("type") == "shortcut"}
        for label in (row[1] for row in ENTRIES if row[0] == parent):
            if label in present:
                continue
            blocks.append({"id": "".join(random.choices(string.ascii_letters + string.digits, k=10)),
                           "type": "shortcut", "data": {"shortcut_name": label, "col": 3}})
            changed += 1
        frappe.db.set_value("Workspace", parent, "content", json.dumps(blocks), update_modified=False)
    return changed


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
    links = ensure_links()
    blocks = sync_content()
    frappe.db.commit()
    frappe.clear_cache(doctype="Workspace")
    return {"created": created, "duplicates_removed": repaired, "links": links, "blocks": blocks,
            "workspaces": sorted(touched)}
