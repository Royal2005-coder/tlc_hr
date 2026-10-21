# Organization & Staffing: Native HRMS with TLC Rules

## Ownership and installation

The `organization.py` slice implements organizational structure, multi-assignment staffing, position definitions, headcount tracking, effective organizational changes, and organizational consistency verification according to Clean Architecture standards. No native Frappe HR or ERPNext source is modified. Pure domain business rules are isolated in `tlc_hr.domain.organization`, data contracts in `tlc_hr.contracts.organization`, use cases in `tlc_hr.application.organization`, Frappe persistence in `tlc_hr.infrastructure.frappe.organization`, and Desk HTTP/hook adapters in `tlc_hr.interface.organization`.

Configuration files are declared in `tlc_hr/customizing/`:
- `organization_records.yaml`: Declares custom DocTypes (`TLC Organization Position`, `TLC Organization Assignment`, `TLC Organization Reporting Line`, `TLC Organization Headcount`, `TLC Organization Change`, `TLC Organization Change Item`) and Client Script. Requires DocType-before-record ordering.
- `organization_fields.yaml`: Declares additive custom fields on native `Department` (`tlc_organization_code`, `tlc_organization_level`) and `Shift Location` (`tlc_organization_holiday_list`, `tlc_organization_shift_type`).
- `organization_dashboards.yaml`: Declares Desk navigation shortcuts for administrative trees, charts, assignments, co-leaders, positions, headcount, and worksites.

### Required parent `doc_events` and scheduler hooks (`tlc_hr.interface.organization` prefix)

| DocType | Hook Event | Method | Behavior |
|---|---|---|---|
| `Department` | `validate` | `tlc_hr.interface.organization.validate` | Generates stable `tlc_organization_code` if empty; enforces company match with parent department. |
| `Shift Location` | `validate` | `tlc_hr.interface.organization.validate` | Requires holiday list calendar reference when shift rule is assigned. |
| `TLC Organization Position` | `validate` | `tlc_hr.interface.organization.validate` | Enforces company consistency and mandatory Job Description (JD). |
| `TLC Organization Assignment` | `validate` | `tlc_hr.interface.organization.validate` | Validates date ranges, prevents duplicate positions or multiple primary assignments; warns on department discrepancy. |
| `TLC Organization Reporting Line` | `validate` | `tlc_hr.interface.organization.validate` | Validates date ranges, ensures active leader user account, detects cycles in reporting graph. |
| `TLC Organization Headcount` | `validate` | `tlc_hr.interface.organization.validate` | Computes used, vacant, and excess headcount based on active assignments on given date. |
| `TLC Organization Change` | `validate` | `tlc_hr.interface.organization.validate` | Validates split/merge shape, prevents duplicate targets, checks future administrative tree topology for cycles. |
| `TLC Organization Change` | `on_submit` | `tlc_hr.interface.organization.on_submit` | Applies reorganization immediately if effective date <= today. |
| `TLC Organization Change` | `before_cancel` | `tlc_hr.interface.organization.before_cancel` | Prevents cancellation of already applied organizational changes. |
| `Attendance` | `validate` | `tlc_hr.interface.organization.warn_recorded_department` | Appends warning if recorded department mismatches primary and secondary assignments. |
| `Leave Application` | `validate` | `tlc_hr.interface.organization.warn_recorded_department` | Appends warning if recorded department mismatches primary and secondary assignments. |

### Scheduler integration

In `hooks.py`:
```python
scheduler_events = {
    "daily": [
        "tlc_hr.interface.organization.apply_due_changes",
        ...
    ]
}
```

### Seed entry

Entry point: `tlc_hr.seed.organization.run(data=None)`.
Executed after base company, people, and designation seed. Idempotently provisions demo positions, primary and concurrent assignments (An: Sales primary, HR secondary), co-leaders (Quang and Hoa for Sales), and initial headcount records.

---

## Architecture & Desk Operation

1. **Administrative Tree vs. Reporting/Approval Lines (HR-ORG-01, HR-ORG-02)**:
   - The native `Department` DocType represents the administrative structural tree (Company → Division → Department → Team). Nested set (`lft`/`rgt`) manages administrative containment.
   - Administrative hierarchy does **not** imply approval authority. Approval and operational reporting lines are managed through `TLC Organization Reporting Line`.
   - Multiple co-leaders can be assigned to the same department with equal approval authority (`employee` left blank applies to all department members).
   - Approval provider function `tlc_hr.interface.organization.approval_users(employee, department, day)` returns all valid leader user IDs. It does not arbitrarily pick a single winner or fall back silently to native `Employee.reports_to`.

2. **Positions, Grades, and Headcount (HR-ORG-03, HR-ORG-05)**:
   - `TLC Organization Position` binds an organizational department, a designation, a job grade (`Employee Grade`), and a detailed Job Description (JD).
   - `TLC Organization Headcount` evaluates position capacity against active employees from `TLC Organization Assignment` on a specific date (`as_on`), deriving `used`, `vacant`, and `excess`. Recalculation is available directly from the Desk form via whitelisted RPC `tlc_hr.interface.organization.assess_headcount`.

3. **Worksites & Calendars (HR-ORG-04)**:
   - Native `Shift Location` is augmented with `tlc_organization_holiday_list` and `tlc_organization_shift_type`.
   - These fields serve as informational and baseline configuration links. Actual employee shift rosters and automated attendance processing remain governed by native `Shift Assignment` and `Shift Type`.

4. **Organizational Chart & Visualization (HR-ORG-06)**:
   - Visual organization charting uses the native Desk page `/desk/organizational-chart`.
   - The native page renders hierarchical node cards from `Employee.reports_to` relationships and supports client-side PNG export via html2canvas.
   - It truthfully reflects the native reporting tree; it does not render complex matrix co-leaders, historical effective dates, or administrative Department trees.

5. **Effective Organizational Changes (HR-ORG-07)**:
   - `TLC Organization Change` tracks structural adjustments (`Rename`, `Reparent`, `Split`, `Merge`) with an `effective_date`, reasoning, and attachments.
   - Pre-validation ensures that post-change topology is acyclic and valid before submission.
   - Changes are applied atomically by updating native `Department` documents (preserving nested set trees) either upon submission (if effective today) or via the daily scheduler task `apply_due_changes`.

6. **Cross-Department Mismatch Checks (HR-ORG-08)**:
   - `tlc_hr.interface.organization.warn_recorded_department` checks attendance and leave records. If an employee is logged under a department that does not match their native profile and is not covered by any active assignment in `TLC Organization Assignment`, a non-blocking UI alert (`frappe.msgprint` with orange indicator) is shown.

---

## Catalog Traceability & Implementation Status (HR-ORG-01 .. HR-ORG-08)

The table below details the implementation status for all organization requirements from `catalog/brd_322_traceability.csv`:
- `implemented`: TLC custom models, rules, or adapters provide direct handling.
- `default`: Native ERPNext / Frappe HR capability fulfills the requirement without custom overrides.
- `external`: Downstream system integration, cross-module workflow consumer adoption, or external tooling required.

| ID | Title / Summary | Classification | Delivered Behavior & Boundaries |
|---|---|---|---|
| **HR-ORG-01** | Multi-level organizational tree with code and name | `implemented` | Native `Department` tree structure retained for Company → Division → Department → Team hierarchy; enhanced with unique `tlc_organization_code` and `tlc_organization_level`. Native tree view and import/export supported. |
| **HR-ORG-02** | Decouple administrative tree from reporting/approval lines, co-leaders, multiple assignments | `implemented` | Administrative hierarchy separated from approval authority. `TLC Organization Reporting Line` models multiple equal-authority co-leaders and dated reporting lines. `TLC Organization Assignment` models primary and concurrent (kiêm nhiệm) positions. Provider `approval_users()` resolves all co-leaders. Downstream workflow consumer migration (updating approval engines across all leave/expense/travel forms) is external. |
| **HR-ORG-03** | Job titles and positions catalog with department, grade, and JD | `implemented` | `TLC Organization Position` manages positions linked to department, designation, and employee grade. Mandatory Job Description (JD) text enforced on save. |
| **HR-ORG-04** | Work locations with working calendar and attendance rules | `implemented` | Custom reference fields `tlc_organization_holiday_list` and `tlc_organization_shift_type` added to native `Shift Location`. Operational shift scheduling remains with native `Shift Assignment`. |
| **HR-ORG-05** | Headcount planning by unit and position with used / vacant / excess | `implemented` | `TLC Organization Headcount` tracks planned capacity against distinct active employees on any designated date. Automatically derives `used`, `vacant`, and `excess`. Manual recalculation button on native Desk form. |
| **HR-ORG-06** | Automated organization chart display and export | `default` | Native Desk page `/desk/organizational-chart` renders visual tree based on `Employee.reports_to` and provides built-in image export (PNG). Does not render matrix co-leaders or administrative department trees. |
| **HR-ORG-07** | Effective organization changes history (split, merge, rename) | `implemented` | Submittable `TLC Organization Change` captures effective date, reason, attachment, and itemized department movements. Structural topology validation prevents cycles. Changes applied immediately or via daily background scheduler. |
| **HR-ORG-08** | Organizational data discrepancy warning (mismatched department) | `implemented` | Non-blocking warning (`msgprint` orange indicator) triggered on `Attendance` and `Leave Application` when recorded department differs from employee primary department and active concurrent assignments. |
