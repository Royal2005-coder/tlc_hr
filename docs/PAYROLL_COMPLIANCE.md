# Payroll Compliance and Governance (HR-LG-01..26)

This module implements governance, evidence tracking, statutory reporting, and dated proration for Vietnamese payroll on native Frappe HRMS. Core statutory tax brackets, insurance ceilings, and overtime formulas remain in `tlc_hr.domain.payroll` and `tlc_hr.application.payroll`.

## Operator path

1. **Customizing & Metadata**: Apply `customizing/payroll_compliance_records.yaml` (DocTypes: `TLC Payroll Review`, `TLC Payroll Adjustment`, `TLC Payroll Bonus`, `TLC Insurance Change`, `TLC Insurance Benefit`, `TLC Salary Review`) and `customizing/payroll_compliance_fields.yaml`.
2. **Demo Fixtures**: Seed demo records via `tlc_hr.seed.payroll_compliance.run(data=None)`. All seeded items reference a private file attachment (`tlc-payroll-demo-evidence.txt`) explicitly marked as demo evidence, not certified legal documents.
3. **Mid-Period Salary Proration**: Salary Structure Assignment remains the source of truth for salary levels. When multiple assignments have active effective dates within a pay period, `prepare_slip` computes `tlc_effective_base` as the payment-day weighted average of each segment, utilizing native HRMS holiday and working-day calculations.
4. **Variance & Review Gate**: When preparing a payroll entry, moving from draft to `Chờ giám đốc ký` triggers `gate_review`. If any employee experiences a gross or net pay variance exceeding the company threshold (default 20%), or if a mid-period salary change lacks an approved decision, the transition is blocked. The HR Lead must submit a `TLC Payroll Review` record with attached private evidence.
5. **Approved Payroll Immutability**: Once signed by the CEO (`Đã ký`) or disbursed (`Đã chi`), the Payroll Entry and its Salary Slips cannot be modified, cancelled, or deleted. Any subsequent corrections must be processed via `TLC Payroll Adjustment` in a subsequent pay period.
6. **Encrypted Payslip Delivery**: Integrates native Frappe HRMS password-protected PDF email delivery (`Payroll Settings.encrypt_salary_slips_in_emails` and `password_policy`). Requires an active, configured `Email Account` with outgoing mail enabled. Calling `deliver_payslips` enqueues delivery via the native Email Queue; enqueuing does not imply delivery until processed by the mail worker.
7. **Bank Payment Batch Export**: Generates payment batch CSV files (`export_bank_batch`). **Disclaimer**: This is a declared configurable CSV export. It is **not** certified as bank-ready by Vietcombank, BIDV, Techcombank, or any banking partner. Files must be verified before transmission.
8. **Statutory Exports & Accounting**:
   - `export_accounting`: Reconciles salary component totals with GL Journal Entries.
   - `export_pit`: Generates monthly/quarterly/annual PIT summaries with effective dependent counts.
   - `export_bhxh_d02lt`: Labor change register for social insurance. Direct API exchange with VNPT BHXH is an uncertified declared export schema; external gateway credentials are not fabricated.
   - `export_labor_register`: Sổ quản lý lao động compliant with Decree 145/2020/ND-CP.
9. **Role-Private Cost Reports & Simulation**:
   - `get_role_private_cost_report`: Enforces strict access; only users with `PAYROLL_ROLES` (`TLC Payroll`, `TLC HR Lead`, `TLC Director`, `Accounts User`, `System Manager`) may view total labor costs. Non-authorized users (workers, managers) receive a `PermissionError`.
   - `simulate_salary_budget`: Forecasts the financial impact of a percentage salary adjustment, including a 23.5% employer contribution (17.5% BHXH + 3% BHYT + 1% BHTN + 2% KPCD).
   - `check_payroll_anomalies`: Rule-based scanning for unapproved salary changes, overtime spikes, and missing tax IDs.

## Integration contract for parent / app hooks

Parent registers the following hooks in `hooks.py`:

```python
doc_events = {
    "Salary Slip": {
        "before_validate": "tlc_hr.interface.payroll_compliance.prepare_slip",
        "before_cancel": "tlc_hr.interface.payroll_compliance.prohibit_approved_change",
        "on_trash": "tlc_hr.interface.payroll_compliance.prohibit_approved_change",
    },
    "Salary Structure Assignment": {
        "validate": "tlc_hr.interface.payroll_compliance.validate_assignment",
    },
    "Payroll Entry": {
        "before_save": "tlc_hr.interface.payroll_compliance.entry_guard",
        "before_submit": [
            "tlc_hr.interface.payroll.before_submit",
            "tlc_hr.interface.payroll_compliance.apply_awards",
        ],
        "on_cancel": [
            "tlc_hr.interface.payroll.on_cancel",
            "tlc_hr.interface.payroll_compliance.release_awards",
        ],
        "before_cancel": "tlc_hr.interface.payroll_compliance.prohibit_approved_change",
        "on_trash": "tlc_hr.interface.payroll_compliance.prohibit_approved_change",
    },
    "TLC Payroll Review": {
        "validate": "tlc_hr.interface.payroll_compliance.validate_review",
    },
    "TLC Payroll Adjustment": {
        "validate": "tlc_hr.interface.payroll_compliance.validate_award",
        "before_cancel": "tlc_hr.interface.payroll_compliance.guard_source_cancel",
    },
    "TLC Payroll Bonus": {
        "validate": "tlc_hr.interface.payroll_compliance.validate_award",
        "before_cancel": "tlc_hr.interface.payroll_compliance.guard_source_cancel",
    },
    "TLC Insurance Change": {
        "validate": "tlc_hr.interface.payroll_compliance.validate_insurance",
    },
    "TLC Insurance Benefit": {
        "validate": "tlc_hr.interface.payroll_compliance.validate_insurance",
    },
    "TLC Salary Review": {
        "validate": "tlc_hr.interface.payroll_compliance.validate_salary_review",
        "on_submit": "tlc_hr.interface.payroll_compliance.approve_salary_review",
    },
}

permission_query_conditions = {
    "TLC Salary Review": "tlc_hr.interface.payroll_compliance.salary_review_query",
}

has_permission = {
    "TLC Salary Review": "tlc_hr.interface.payroll_compliance.salary_review_permission",
}
```

Formula update:
`customizing/payroll_formulas.py` updated to evaluate `tlc_effective_dependents if tlc_effective_dependents is not None else (vn_number_of_dependents or 0)`.

## Catalog mapping

Statuses describe implementation reality: **implemented** = TLC implementation for the stated requirement; **default** = inspected native Frappe/HRMS behavior; **external** = at least one named facet requires external systems or uncertified templates.

| BRD | Status | Implementation or explicit external boundary |
|---|---|---|
| HR-LG-01 | default | Native Salary Component with Earning/Deduction/Employer Contribution types and account mappings. |
| HR-LG-02 | default | Salary Structure formulas evaluated in HRMS expression engine. |
| HR-LG-03 | default | Attendance period lock precondition before opening payroll calculation. |
| HR-LG-04 | implemented | Mid-period salary change proration (`effective_base`) based on verified dated SSA segments. |
| HR-LG-05 | default | 2026 statutory rates for SI/HI/UI and progressive PIT with dated thresholds. |
| HR-LG-06 | implemented | `review_issues` checks >20% variance and unapproved salary changes; requires submitted `TLC Payroll Review`. |
| HR-LG-07 | implemented | Approval gate blocks CEO sign when unreviewed variances exist. |
| HR-LG-08 | implemented | Approved payroll entries and salary slips are immutable; adjustments routed to next period via `TLC Payroll Adjustment`. |
| HR-LG-09 | default | Native HRMS password-protected PDF generation and email queuing via `Payroll Settings`. |
| HR-LG-10 | external | Bank payment batch CSV export implemented. Declared configurable format; not certified as bank-ready by partner banks. |
| HR-LG-11 | default | Salary cost accounting entry posted via native Journal Entry; reconciliation report provided. |
| HR-LG-12 | implemented | Monthly and yearly performance bonus calculation based on employment calendar service (`TLC Payroll Bonus`). |
| HR-LG-13 | implemented | Sourced adjustments carry unique reference links (`tlc_compliance_source`), preventing double-payment across payroll runs. |
| HR-LG-14 | implemented | Salary budget simulation endpoint forecasting base salary and employer contribution impact (+X%). |
| HR-LG-15 | implemented | Salary decisions require reason, private evidence attachment, and Director approval; updates dated SSA history. |
| HR-LG-16 | implemented | Annual department salary review (`TLC Salary Review`) enforcing department budget caps and HR review before Director submit. |
| HR-LG-17 | implemented | Tax ID tracked in Employee; verified dependents filtered by validity date via `verified_dependents`. |
| HR-LG-18 | implemented | Statutory PIT monthly/quarterly report and annual settlement data extraction. |
| HR-LG-19 | implemented | Social insurance management and labor change list (mẫu D02-LT) tracking enrollments, base changes, and stops. |
| HR-LG-20 | external | Electronic BHXH file export (VNPT BHXH format). Direct automated API integration is uncertified due to missing gateway credentials. |
| HR-LG-21 | implemented | Insurance benefit tracking (`TLC Insurance Benefit`) for sickness, maternity, and convalescence linked to approved leaves. |
| HR-LG-22 | implemented | Sổ quản lý lao động (Labor Register) according to Decree 145/2020/ND-CP. |
| HR-LG-23 | implemented | Headcount report by department, location, and contract type, including hires, separations, and internal adjustments. |
| HR-LG-24 | implemented | Role-private labor cost dashboard and reporting restricted to authorized payroll and finance roles. |
| HR-LG-25 | implemented | Role-based permission enforcement; workers and managers cannot view other employees' salary slips or aggregate cost reports. |
| HR-LG-26 | implemented | Automated payroll anomaly scanning detecting unapproved salary changes, overtime spikes (>50% base), and missing tax IDs. |
