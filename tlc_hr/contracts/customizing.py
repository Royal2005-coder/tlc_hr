"""Data contracts of the TLC customizing: what each YAML file under tlc_hr/customizing may declare.

Every model is strict (no silent type coercion), forbids unknown keys (a typo in YAML is an error, not a silent no-op) and is
frozen. The models describe *what* the site must contain; infrastructure/customizing writes it into Frappe.
No Frappe import here: the contracts are validated in plain Python, in CI and with `bench tlc config validate`.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Scalar = str | int | float | bool | None
Filter = list[Scalar | list[Scalar]]
RIGHTS = {"r": "read", "w": "write", "c": "create", "d": "delete", "s": "submit", "x": "cancel", "a": "amend"}


class Spec(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, populate_by_name=True)


class RoleSpec(Spec):
    name: str
    desk_access: bool = True
    home_page: str | None = None


class CustomFieldSpec(Spec):
    fieldname: str
    fieldtype: str
    label: str | None = None
    insert_after: str | None = None
    options: str | None = None
    default: str | None = None
    description: str | None = None
    depends_on: str | None = None
    fetch_from: str | None = None
    permlevel: int = 0
    reqd: bool = False
    read_only: bool = False
    hidden: bool = False
    allow_on_submit: bool = False
    no_copy: bool = False
    unique: bool = False
    collapsible: bool = False


class CustomFieldGroup(Spec):
    doctype: str
    fields: list[CustomFieldSpec]


class PermissionSpec(Spec):
    """Role rights on a doctype at a permission level; rights are letters of RIGHTS ("rw" = read and write)."""

    doctype: str
    role: str
    permlevel: int = 0
    rights: str

    @model_validator(mode="after")
    def known_rights(self):
        unknown = set(self.rights) - set(RIGHTS)
        if unknown:
            raise ValueError(f"unknown rights {sorted(unknown)} (use {''.join(RIGHTS)})")
        return self


class StateSpec(Spec):
    state: str
    doc_status: Literal[0, 1, 2]
    allow_edit: str
    style: str = ""
    update_field: str | None = None
    update_value: str | None = None


class TransitionSpec(Spec):
    from_state: str = Field(alias="from")
    action: str
    to: str
    allowed: list[str]
    condition: str | None = None
    allow_self_approval: bool = False


class WorkflowSpec(Spec):
    name: str
    doctype: str
    send_email_alert: bool = False
    states: list[StateSpec]
    transitions: list[TransitionSpec]

    @model_validator(mode="after")
    def transitions_use_declared_states(self):
        declared = {s.state for s in self.states}
        for t in self.transitions:
            missing = {t.from_state, t.to} - declared
            if missing:
                raise ValueError(f"workflow {self.name}: transition {t.action} uses undeclared states {sorted(missing)}")
        return self


class EmailTemplateSpec(Spec):
    name: str
    subject: str
    html: str
    hr_setting: str | None = None  # HR Settings field that must point to this template


class NumberCardSpec(Spec):
    name: str
    doctype: str
    color: str
    function: Literal["Count", "Sum", "Average", "Minimum", "Maximum"] = "Count"
    field: str | None = None  # aggregated field when the function is not Count
    filters: list[Filter] = []
    dynamic_filters: list[Filter] = []


class ChartSpec(Spec):
    name: str
    chart_type: Literal["Count", "Sum", "Average", "Group By"]
    document_type: str
    type: Literal["Bar", "Line", "Donut", "Pie", "Percentage", "Heatmap"]
    filters: list[Filter] = []
    color: str = "#2f8a3c"
    group_by_type: str | None = None
    group_by_based_on: str | None = None
    aggregate_function_based_on: str | None = None
    number_of_groups: int | None = None
    based_on: str | None = None
    value_based_on: str | None = None
    timeseries: bool = False
    timespan: str | None = None
    time_interval: str | None = None


class ShortcutSpec(Spec):
    label: str
    type: Literal["DocType", "Page", "URL", "Report"]
    link_to: str | None = None
    url: str | None = None  # may use {year}: replaced by the current year when applied
    doc_view: str = ""
    color: str = "Grey"
    stats_filter: list[Filter] | None = None
    format: str | None = None


class QuickListSpec(Spec):
    doctype: str
    label: str
    filters: list[Filter] = []


class WorkspaceSpec(Spec):
    title: str
    roles: list[str]
    icon: str
    sequence: int
    cards: list[str] = []
    charts: list[str] = []
    shortcuts: list[str] = []
    quick_list: QuickListSpec | None = None


class RecordSpec(Spec):
    """A Frappe record that must have these values (a single doctype when name is None).

    values are written on every apply; on_create only when the record is created; tables replace whole child tables."""

    doctype: str
    name: str | None = None
    values: dict[str, Scalar] = {}
    on_create: dict[str, Scalar] = {}
    tables: dict[str, list[dict[str, Scalar]]] = {}


class AccountsSpec(Spec):
    """Account types and company defaults by account number (the chart of accounts names differ per company)."""

    account_types: dict[str, str]
    company_defaults: dict[str, str]


Kind = Literal["roles", "custom_fields", "permissions", "workflow", "email_templates", "dashboards", "workspaces", "records",
               "accounts"]


class CustomizingFile(Spec):
    """One YAML file: a version, a kind and the items of that kind."""

    version: Literal[1]
    kind: Kind
    description: str = ""
    roles: list[RoleSpec] = []
    custom_fields: list[CustomFieldGroup] = []
    permissions: list[PermissionSpec] = []
    workflow: WorkflowSpec | None = None
    email_templates: list[EmailTemplateSpec] = []
    number_cards: list[NumberCardSpec] = []
    charts: list[ChartSpec] = []
    shortcuts: list[ShortcutSpec] = []
    workspaces: list[WorkspaceSpec] = []
    records: list[RecordSpec] = []
    accounts: AccountsSpec | None = None


class Bundle(Spec):
    """Everything declared under tlc_hr/customizing, checked across files."""

    roles: list[RoleSpec] = []
    custom_fields: list[CustomFieldGroup] = []
    permissions: list[PermissionSpec] = []
    workflows: list[WorkflowSpec] = []
    email_templates: list[EmailTemplateSpec] = []
    number_cards: list[NumberCardSpec] = []
    charts: list[ChartSpec] = []
    shortcuts: list[ShortcutSpec] = []
    workspaces: list[WorkspaceSpec] = []
    records: list[RecordSpec] = []
    accounts: AccountsSpec | None = None

    @model_validator(mode="after")
    def references_resolve(self):
        cards, charts, shortcuts = ({c.name for c in self.number_cards}, {c.name for c in self.charts},
                                    {s.label for s in self.shortcuts})
        for ws in self.workspaces:
            for kind, wanted, have in (("card", ws.cards, cards), ("chart", ws.charts, charts), ("shortcut", ws.shortcuts, shortcuts)):
                missing = sorted(set(wanted) - have)
                if missing:
                    raise ValueError(f"workspace {ws.title}: unknown {kind}s {missing}")
        for kind, items, key in (("workflow", self.workflows, "name"), ("number card", self.number_cards, "name"),
                                 ("chart", self.charts, "name"), ("workspace", self.workspaces, "title"), ("role", self.roles, "name")):
            names = [getattr(i, key) for i in items]
            duplicated = sorted({n for n in names if names.count(n) > 1})
            if duplicated:
                raise ValueError(f"{kind} declared twice: {duplicated}")
        return self
