"""Appliers of the role dashboards: number cards, dashboard charts and desk workspaces (Frappe counts through permissions,
so one card shows a factory head the numbers of their factory and HR or the CEO the whole company)."""

import json

import frappe

from tlc_hr.infrastructure.customizing.base import ResourceApplier, differing

MODULE = "TLC HR"


def short(label):
    """Workspace widgets are looked up by their row label: the card name without the "TLC " prefix."""
    return label.replace("TLC ", "")


def upsert(doctype, name, values):
    doc = frappe.get_doc(doctype, name) if frappe.db.exists(doctype, name) else frappe.new_doc(doctype)
    doc.update(values)
    doc.flags.ignore_permissions = True
    doc.flags.ignore_links = True
    doc.save() if not doc.is_new() else doc.insert()
    return doc


class NumberCardApplier(ResourceApplier):
    kind = "number card"

    def items(self, bundle):
        return bundle.number_cards

    def name_of(self, spec):
        return spec.name

    @staticmethod
    def values(spec):
        return {"label": spec.name, "type": "Document Type", "document_type": spec.doctype, "function": spec.function,
                "aggregate_function_based_on": spec.field, "is_public": 1, "module": MODULE, "color": spec.color,
                "filters_json": json.dumps(spec.filters), "dynamic_filters_json": json.dumps(spec.dynamic_filters),
                "show_percentage_stats": 0}

    def diff(self, spec):
        if not frappe.db.exists("Number Card", spec.name):
            return ()
        wanted = self.values(spec)
        return differing(frappe.db.get_value("Number Card", spec.name, list(wanted), as_dict=True), wanted)

    def write(self, spec):
        upsert("Number Card", spec.name, self.values(spec))


class ChartApplier(ResourceApplier):
    kind = "chart"

    def items(self, bundle):
        return bundle.charts

    def name_of(self, spec):
        return spec.name

    @staticmethod
    def values(spec):
        values = {k: v for k, v in spec.model_dump(exclude={"name", "filters"}).items() if v is not None}
        values.update({"chart_name": spec.name, "is_public": 1, "module": MODULE, "filters_json": json.dumps(spec.filters),
                       "timeseries": int(spec.timeseries)})
        return values

    def diff(self, spec):
        if not frappe.db.exists("Dashboard Chart", spec.name):
            return ()
        wanted = self.values(spec)
        return differing(frappe.db.get_value("Dashboard Chart", spec.name, list(wanted), as_dict=True), wanted)

    def write(self, spec):
        upsert("Dashboard Chart", spec.name, self.values(spec))


class WorkspaceApplier(ResourceApplier):
    """The workspace record and its widgets; the page layout (content) puts the cards, shortcuts, quick list and charts in order."""

    kind = "workspace"

    def __init__(self):
        self._shortcuts = {}

    def items(self, bundle):
        self._shortcuts = {s.label: s for s in bundle.shortcuts}
        return bundle.workspaces

    def name_of(self, spec):
        return spec.title

    def shortcut_row(self, label):
        s = self._shortcuts[label]
        row = {"label": label, "type": s.type, "color": s.color, "doc_view": s.doc_view or ""}
        if s.type == "URL":
            row["url"] = (s.url or "").format(year=frappe.utils.getdate().year)
        else:
            row["link_to"] = s.link_to
        if s.stats_filter:
            row["stats_filter"] = json.dumps(s.stats_filter)
            row["format"] = s.format
        return row

    def layout(self, spec):
        """Content blocks without their random ids (what is compared)."""
        blocks = [("header", {"text": f'<span class="h4"><b>{spec.title}</b></span>', "col": 12})]
        blocks += [("number_card", {"number_card_name": short(c), "col": 3}) for c in spec.cards]
        blocks += [("shortcut", {"shortcut_name": s, "col": 3}) for s in spec.shortcuts]
        if spec.quick_list:
            blocks.append(("quick_list", {"quick_list_name": spec.quick_list.label, "col": 12}))
        blocks += [("chart", {"chart_name": short(c), "col": 6}) for c in spec.charts]
        return blocks

    def children(self, spec):
        quick = ([{"document_type": spec.quick_list.doctype, "label": spec.quick_list.label,
                   "quick_list_filter": json.dumps(spec.quick_list.filters)}] if spec.quick_list else [])
        return {"roles": [{"role": r} for r in spec.roles],
                "number_cards": [{"number_card_name": c, "label": short(c)} for c in spec.cards],
                "charts": [{"chart_name": c, "label": short(c)} for c in spec.charts],
                "quick_lists": quick, "shortcuts": [self.shortcut_row(s) for s in spec.shortcuts]}

    def diff(self, spec):
        if not frappe.db.exists("Workspace", spec.title):
            return ()
        doc = frappe.get_doc("Workspace", spec.title)
        found = list(differing(doc.as_dict(), {"label": spec.title, "title": spec.title, "module": MODULE, "public": 1, "icon": spec.icon,
                                               "sequence_id": spec.sequence}) or ())
        content = [(b.get("type"), {k: v for k, v in b.get("data", {}).items()}) for b in json.loads(doc.content or "[]")]
        if content != self.layout(spec):
            found.append("content")
        for table, rows in self.children(spec).items():
            current = [{k: r.get(k) for k in row} for r, row in zip(doc.get(table), rows)]
            if len(doc.get(table)) != len(rows) or any(differing(c, w) for c, w in zip(current, rows)):
                found.append(table)
        return tuple(found) or None

    def write(self, spec):
        content = [{"id": frappe.generate_hash(length=10), "type": kind, "data": data} for kind, data in self.layout(spec)]
        values = {"label": spec.title, "title": spec.title, "module": MODULE, "public": 1, "icon": spec.icon, "sequence_id": spec.sequence,
                  "content": json.dumps(content), **self.children(spec)}
        if frappe.get_meta("Workspace").has_field("app"):
            values["app"] = "tlc_hr"
        upsert("Workspace", spec.title, values)
