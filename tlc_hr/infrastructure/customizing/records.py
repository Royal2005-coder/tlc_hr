"""Appliers of configuration records (shifts, sites, settings, leave and overtime types, statutory values) and accounts."""

import frappe

from tlc_hr.infrastructure.customizing.base import ResourceApplier, differing, same


class RecordApplier(ResourceApplier):
    kind = "record"

    def items(self, bundle):
        return [spec for spec in bundle.records if spec.doctype != "DocType"]

    def name_of(self, spec):
        return f"{spec.doctype}: {spec.name}" if spec.name else spec.doctype

    def current(self, spec):
        if spec.name is None:
            return {k: frappe.db.get_single_value(spec.doctype, k) for k in spec.values}
        return frappe.db.get_value(spec.doctype, spec.name, list(spec.values), as_dict=True) if spec.values else {}

    def diff(self, spec):
        if not frappe.db.exists("DocType", spec.doctype):
            return ()
        if spec.name is not None and not frappe.db.exists(spec.doctype, spec.name):
            return ()
        found = list(differing(self.current(spec), spec.values) or ())
        if spec.tables:
            doc = frappe.get_doc(spec.doctype, spec.name or spec.doctype)
            for table, rows in spec.tables.items():
                current = self.current_rows(doc, table, rows)
                if len(current) != len(rows) or any(not same(c.get(k), v) for c, r in zip(current, rows) for k, v in r.items()):
                    found.append(table)
        return tuple(found) or None

    def current_rows(self, doc, table, declared):
        return [r.as_dict() for r in doc.get(table)]

    def write(self, spec):
        if spec.name is None:
            doc = frappe.get_single(spec.doctype)
        elif frappe.db.exists(spec.doctype, spec.name):
            doc = frappe.get_doc(spec.doctype, spec.name)
        else:
            doc = frappe.new_doc(spec.doctype)
            doc.update(spec.on_create)
            doc.name = spec.name
        doc.update(spec.values)
        for table, rows in spec.tables.items():
            doc.set(table, [dict(r) for r in rows])
        doc.flags.ignore_permissions = True
        doc.save() if not doc.is_new() else doc.insert()


class DocTypeApplier(RecordApplier):
    """Create declared DDIC records before custom fields, permissions and workflows use them."""

    kind = "doctype"
    # fields Frappe adds by itself (amended_from on a submittable DocType): not part of the declaration
    SYSTEM_FIELDS = frozenset({"amended_from"})

    def current_rows(self, doc, table, declared):
        rows = [r.as_dict() for r in doc.get(table)]
        if table != "fields":
            return rows
        named = {r.get("fieldname") for r in declared}
        return [r for r in rows if r.get("fieldname") in named or r.get("fieldname") not in self.SYSTEM_FIELDS]

    def items(self, bundle):
        pending = {spec.name: spec for spec in bundle.records if spec.doctype == "DocType"}
        ordered = []
        while pending:
            ready = [name for name, spec in pending.items()
                     if not any(row.get("fieldtype") in ("Table", "Table MultiSelect") and row.get("options") in pending
                                for row in spec.tables.get("fields", []))]
            if not ready:
                raise ValueError(f"cyclic child DocType dependencies: {sorted(pending)}")
            for name in ready:
                ordered.append(pending.pop(name))
        return ordered


class AccountApplier(ResourceApplier):
    """Account types and company defaults, by account number, for every company that has the chart."""

    kind = "account"

    def items(self, bundle):
        if not bundle.accounts:
            return []
        companies = frappe.get_all("Company", pluck="name")
        return [(company, bundle.accounts) for company in companies]

    def name_of(self, spec):
        return spec[0]

    @staticmethod
    def account(company, number):
        return frappe.db.get_value("Account", {"company": company, "account_number": number, "is_group": 0})

    def wanted(self, spec):
        company, accounts = spec
        types = {name: kind for number, kind in accounts.account_types.items() if (name := self.account(company, number))}
        defaults = {field: name for field, number in accounts.company_defaults.items() if (name := self.account(company, number))}
        return types, defaults

    def diff(self, spec):
        company = spec[0]
        types, defaults = self.wanted(spec)
        found = [name for name, kind in types.items() if frappe.db.get_value("Account", name, "account_type") != kind]
        found += list(differing(frappe.db.get_value("Company", company, list(defaults), as_dict=True) if defaults else {}, defaults) or ())
        return tuple(found) or None

    def write(self, spec):
        company = spec[0]
        types, defaults = self.wanted(spec)
        for name, kind in types.items():
            frappe.db.set_value("Account", name, "account_type", kind)
        if defaults:
            frappe.db.set_value("Company", company, defaults)
