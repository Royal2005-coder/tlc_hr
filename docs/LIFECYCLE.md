# W4 employment lifecycle

This module extends native HRMS Employee Onboarding, Employee Separation, Employee Promotion, Employee Transfer and Full and Final Statement. It does not replace or patch HRMS source. Organization and recruiting are documented in ORGANIZATION.md and RECRUITMENT.md.

## Operator path

1. Apply customizing after custom DocType records are available, then native custom fields and workflows. Run `tlc_hr.seed.lifecycle.run(data=None)` after the main employee seed and recruitment seed. The helper creates only draft HR records and native boarding templates. Its private text attachment is explicitly marked demo evidence, not a legal document.
2. Use standard Desk forms. Contracts, dependents, documents, change requests and employment episodes have HR workflows. Change requests require a reason, effective date and evidence. Due approved changes are applied by the daily scheduler; old values and the original request remain in history. An applied request cannot be cancelled; corrections require another request.
3. Native Promotion/Transfer requires an attached decision and reason. TLC forbids the native create-new-employee-ID transfer option. Submission captures dated employment snapshots; the native controller remains responsible for updating Employee and its native work history. These snapshots are not payroll salary assignments. Native HRMS disallows submission before the effective date.
4. Record probation category and actual dates in TLC Probation Review. Limits are inclusive 180/60/30 calendar days or six actual working days, using the employee holiday calendar. Another non-cancelled review for the same employee/job is rejected. Review sections are writable only by their author at their workflow step. Official/End decisions require a linked same-employee contract/separation. Those result documents are not automatically generated or approved by this module.
5. Employee Separation uses separate filing/last-working/effective dates. Ordinary resignation computes the earliest compliant last day and warns, rather than silently adjusting or forbidding the employee's requested day. Special legal facts require a controlled exception category, attached basis and HR's own signed-in attestation; the system does not decide whether those facts satisfy a statutory exception. Settlement is due after 14 actual working days, or 30 calendar days only with evidenced legal attestation.
6. Inboarding/offboarding evidence rows carry category, required flag, status, attachment, actual confirmer and timestamp. Native activities remain assigned Tasks. The **Hoàn tất có kiểm tra** native Desk action checks these rows, native Task completion, and—for separation—asset/account blockers from People Operations, decision, handover, exit interview, rehire decision and a submitted Paid same-employee Full and Final Statement. HR cannot mark Employee Left through its native form without the same gates. Completion disables the employee's Frappe user and clears sessions. External IT accounts are represented by People Operations evidence; this does not call an external directory provider.
7. Rehire uses a submitted TLC Employment Episode (`event=Rehired`) on the existing Employee code, with a due start date. The previous separation retains its rehire conclusion. Re-enabling the Frappe User and any external accounts is a separate authorized provisioning action, never an automatic restoration of old access.

## Integration owned by the app

Register `interface.lifecycle.validate` on validate for TLC lifecycle doctypes, Employee Onboarding, Employee Separation, Employee, Task and Project. Also register `interface.lifecycle_guards.validate` for Employee, TLC Probation Review and TLC Employee Dependent. Use `interface.lifecycle.before_submit` and `on_submit` for the applicable TLC records and native promotion/transfer. Register `interface.lifecycle_guards.prevent_cancel_applied` before cancellation of applied changes/promotion/transfer. Add `interface.lifecycle.provisioning` after native Employee Onboarding submission. Add `public/js/lifecycle_boarding.js` for both native boarding forms. Schedule `infrastructure.frappe.lifecycle.remind_expiries` daily (it also applies due changes).

`infrastructure.frappe.lifecycle.verified_dependents(employee, as_of)` returns only submitted, Verified, effective dependents for Payroll/PIT. Payroll must consume this function explicitly; storing a dependent is not a claim that tax calculation already uses it. Salary Structure Assignment remains payroll's source for effective salary and proration. `application.lifecycle.LifecycleService` accepts a calendar/evidence repository, and the pure domain rules import no Frappe.

Native HRMS `mark_onboarding_as_completed` bulk-updates Tasks and boarding status; native Project/Task updates also set boarding status with direct DB writes. TLC validates evidence on the native document save and final Task/Project completion, and provides the explicit audited completion action. Direct database writes by an administrator are not an authorization path.

## Catalog mapping

Statuses describe source implementation, not exercised runtime acceptance: **implemented** = TLC implementation for the stated full requirement; **default** = inspected native behavior; **external** = at least one named facet is outside this module. External rows identify the implemented portions without claiming the missing facets. No runtime tests or UI runs were performed in this change.

| BRD | Status | Implementation or explicit external boundary |
|---|---|---|
| HR-OB-01 | external | Recruitment creates native onboarding draft on accepted offer; no projected Employee code or complete preboarding state transition. |
| HR-OB-02 | default | Native onboarding templates carry department/designation/grade and editable activity rows; TLC seeds office/factory examples. Location-specific automatic template selection is external. |
| HR-OB-03 | external | Native boarding creates Tasks, dates and role/user assignments; TLC evidence adds confirmation/files. Full requested per-item Vietnamese status set is not a native claim. |
| HR-OB-04 | external | Native activity date offsets exist; configurable pre-arrival preparation deadline/escalation is external. |
| HR-OB-05 | external | Dedicated candidate preboarding portal/welcome automation is not implemented. |
| HR-OB-06 | implemented | Required evidence rows model Received/Pending/Not Applicable with attachments and confirmation; HR must configure the applicable document checklist. |
| HR-OB-07 | external | Explicit Asset/license IDs provision People Operations requests after onboarding submission when an Employee exists. Automatic pre-employee allocation and asset-record visibility depend on People Operations. |
| HR-OB-08 | external | Native assigned training Tasks/templates exist; automatic training-history enrollment is outside lifecycle. |
| HR-OB-09 | external | Buddy assignment and scheduled reminders not implemented. |
| HR-OB-10 | external | End-date notifications exist; configurable intermediate milestone reviews and outcome dashboard not implemented. |
| HR-OB-11 | external | Sequential self/manager/HR/director review and end-date reminders implemented; structured weighted criteria are external. |
| HR-OB-12 | implemented | Four legal duration categories, actual-working-day calendar and once-per-employee/job validation. |
| HR-OB-13 | external | Official state and confirmation date update implemented; new contract, benefit/insurance update and leave allocation are not automatic. End outcome requires an existing separation. |
| HR-OB-14 | implemented | Mandatory evidence plus asset/account confirmation blocks completion. |
| HR-OB-15 | external | Native list/filter views available; dedicated department checklist dashboard not supplied. |
| HR-OB-16 | external | Native review list/filter views available; pass/extension ratio dashboard not supplied. |
| HR-OB-17 | external | 30/90-day survey dispatch belongs to Internal Services; no lifecycle dispatch implemented. |
| HR-OB-18 | external | Assistant integration, not an autonomous lifecycle decision engine. |
| HR-HS-01 | external | Employee stays native; this module does not claim all country-specific identity/bank/insurance fields exist in the installed schema. |
| HR-HS-02 | external | Multiple emergency contacts are not added by lifecycle. |
| HR-HS-03 | external | Native Employee remains source; no claim of complete inspected custom location/cost-center configuration. |
| HR-HS-04 | external | Read-only TLC lifecycle state and dated episode records exist; automatic transitions for every leave/suspension event are not implemented. |
| HR-HS-05 | external | Native Promotion/Transfer work history plus immutable dated snapshots implemented; arbitrary manager/location edits are not automatically converted to decisions. |
| HR-HS-06 | external | Native Salary Structure Assignment/Payroll owns salary history; snapshots are not a salary ledger. |
| HR-HS-07 | implemented | Unique-number contracts and linked amendments, signature/effective/expiry dates, signer and required attachments, submitted history. |
| HR-HS-08 | external | HR/manager expiry notices and fixed-term repeat gate implemented; legal successor-contract recommendation is not automated. |
| HR-HS-09 | external | Electronic-signature provider integration not implemented. |
| HR-HS-10 | external | Full dependent record, dates, verification, evidence, overlapping-identity guard and PIT query implemented; payroll adoption must be integrated separately. |
| HR-HS-11 | implemented | Electronic employee document register with controlled type, number, issue/expiry, status and evidence. |
| HR-HS-12 | implemented | Native Notification Logs at 60/30 days for HR and direct manager. |
| HR-HS-13 | external | People Operations owns custody/training visibility; no consolidated lifecycle employee form panel. |
| HR-HS-14 | external | Native leave balances plus library/vehicle ownership outside lifecycle; no claim of a consolidated panel. |
| HR-HS-15 | external | Native per-document timeline and dated snapshots exist; a cross-domain aggregate employee timeline is not implemented. |
| HR-HS-16 | external | Existing native self-service permissions remain; multiple-emergency-contact editing is not added. |
| HR-HS-17 | external | Evidence-backed dated HR-reviewed field requests and dependent review exist. Allowlisted insurance/tax custom fields must exist; other identity fields require explicit schema extension. |
| HR-HS-18 | external | Promotion/Transfer workflow and dated snapshots; approved contracts/change requests supported. Cross-module benefits/salary authority propagation remains external. |
| HR-HS-19 | external | Native autogenerated decision IDs and evidence attachment; generated editable PDF decision templates not supplied here. |
| HR-HS-20 | external | Native promotion/transfer updates Employee reports_to/work data; payroll allocation/access/assets do not automatically propagate. |
| HR-HS-21 | external | Permission-aware natural-language search belongs to Assistant Integration. |
| HR-HS-22 | external | Native document/dependent filters available; whole-workforce missing-record report not supplied. |
| HR-HS-23 | external | AI profile summary not supplied. |
| HR-HS-24 | external | OCR extraction and HR-confirmed suggestions not supplied. |
| HR-HS-25 | external | Contract/probation date reminders exist; consolidated missing-file/overdue-decision risk report not supplied. |
| HR-HS-26 | external | Human HR verification and effective dependent query exist; AI explanation is outside lifecycle. |
| HR-NV-01 | implemented | Native separation plus controlled cause, filing/last/effective dates, reason and employee context. |
| HR-NV-02 | implemented | 45/30 calendar/3 actual working-day warning and earliest-day suggestion; controlled legal-exception evidence and HR attestation. |
| HR-NV-03 | external | Manager/HR/director workflow exists for HR-created native separation; employee self-creation and dynamic shared routing adoption are external. |
| HR-NV-04 | external | Decision evidence required; automatic decision PDF and all stakeholder notifications are not supplied. |
| HR-NV-05 | external | Native editable separation templates, assigned Tasks and confirmation evidence exist; position-specific automatic template selection remains external. |
| HR-NV-06 | external | Native Full and Final asset list plus People Operations blockers; lost/damaged reimbursement is reconciled there, not automatically computed here. |
| HR-NV-07 | external | People Operations account grants block closing; external provider revocation and automatic end-of-last-day scheduling are not performed here. |
| HR-NV-08 | external | Native Full and Final computes asset/advance/payable totals and requires settlement; TLC computes legal deadline/reminders. Automatic unpaid OT/leave/training-debt extraction is not claimed. |
| HR-NV-09 | external | Native exit summary and controlled rehire conclusion required; structured multi-question survey belongs to Internal Services. |
| HR-NV-10 | implemented | Assets/accounts/Tasks, final Paid submitted statement, decision, handover and interview/rehire conclusion all gate completion. |
| HR-NV-11 | external | Completion sets Left, relieving date, disables ESS user and clears sessions; transaction stopping relies on each native module's active-employee checks, not a universal write firewall. |
| HR-NV-12 | implemented | Submitted due rehire episode restores existing Employee code and retains prior separation/history; access must be reauthorized. |
| HR-NV-13 | external | Native separation lists/filters exist; cohort turnover dashboard not supplied. |
| HR-NV-14 | external | AI turnover/interview summary belongs to Assistant Integration. |

## Maintenance and evidence

Keep legal categories in `domain/lifecycle.py`, strict commands in `contracts/lifecycle.py`, orchestration in `application/lifecycle.py` and Frappe access in `infrastructure/frappe/lifecycle.py`. Never infer a weekend calendar for factory employees. Adding an exception category does not establish its legal applicability; retain evidenced HR/Legal policy sign-off from catalog POL-OB-01/POL-EXIT-01/POL-EXIT-02.

Unit boundaries live in `tests/unit/test_lifecycle.py`. Desktop contract happy/error/permission evidence lives in platform `uat/journeys/lifecycle.py`; boundary stories explicitly identify pure unit evidence rather than claiming browser execution. Main integration must exercise hooks/config dependency ordering, native completion shortcuts, permissions, and the People Operations resource port before marking runtime acceptance.
