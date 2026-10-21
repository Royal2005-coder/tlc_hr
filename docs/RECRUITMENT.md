# Recruitment: native HRMS with TLC rules

## Ownership and installation

The `recruitment.py` modules add rules to native Job Requisition, Job Opening, Job Applicant, Interview Type and Job Offer. No HRMS source is modified. Domain rules import no Frappe. Application commands are strict Pydantic models; the repository owns native persistence in the caller's transaction, without commits.

Apply `customizing/recruitment*.yaml` through the existing configuration engine. **Dependency:** the three `DocType` records in `recruitment_00_records.yaml` must exist before Custom Fields refer to `TLC Recruitment Position` or `TLC Recruitment Candidate`. They must also precede permissions/workflows. A filename alone does not establish engine ordering. The parent engine integration must provision these metadata records first; do not apply an old fields-first engine to an empty site.

Required parent `doc_events` integrations (`tlc_hr.interface.recruitment` prefix):

| Native doctype | Event | Adapter |
|---|---|---|
| Job Requisition | validate | validate_requisition_doc |
| Job Requisition | on_update | requisition_updated |
| Job Opening | validate | validate_opening |
| Job Opening | on_update | opening_updated |
| Job Applicant | validate | validate_applicant |
| Job Offer | validate | validate_offer |
| Job Offer | before_update_after_submit | validate_offer |
| Job Offer | on_update | offer_updated |
| Job Offer | on_update_after_submit | offer_updated |
| Job Offer | before_cancel | before_cancel_offer |
| Job Offer | before_print | before_print_offer |
| Communication | before_insert | validate_offer_communication |

These are additions, not replacements for existing hooks. Native accepted offers are updated after submission, so both update-after-submit hooks are necessary. Keep native `JobOffer.validate_duplicate_job_offer`: it prohibits concurrent active offers for the same applicant email, even for distinct vacancies. Multiple applications remain supported; concurrent offers for that same email remain a native restriction.

Seed entry: `tlc_hr.seed.recruitment.run(data=None)`, called after base people seed and configuration. It creates sources, a skill, final Interview Type, a two-seat standalone vacancy, two applications with the same normalized phone/identity and one submitted Cleared final interview. It does not approve a requisition or offer. Returns `opening`, `cleared_application`, `uncleared_application`. Names: `recruitment.candidate@demo.example`, `recruitment.alias@demo.example`; candidate display `Ứng viên tuyển dụng TLC Demo`. Demo dates are relative. No password or personal production data is included.

## Desk operation

1. Manager creates Job Requisition with type, JD file, expected-by date and native budget/reason fields. Replacement requires an employee. Optional Recruitment Positions rows define multiple designations/headcounts/departments/locations; otherwise the native primary designation/headcount creates one vacancy. HR Lead **Review Recruitment**, Director **Approve Recruitment**. Approved commercial content is immutable. Retrying approval updates does not duplicate vacancy keys.
2. HR manages Job Applicant per application. Canonical Candidate is derived, not chosen. Email is case-folded and trimmed; Vietnamese phone `0`, `84` and `0084` forms normalize together; identity removes spaces/dots/hyphens and uppercases. Any matching identifier links the same candidate. A bridging submission merges identifier ownership and applicant links; superseded canonical rows remain with `merged_into`, preserving audit/profile evidence. Existing applications, interviews and offers are never deleted or combined. Conflicting nonempty profile values stay on the original rows; the survivor takes only missing values. Original aliases remain indexed. This intentionally does not auto-correct mistyped shared contact information.
3. Use native Interview Type/Interview/Interview Feedback. Mark the real final Interview Type `TLC Final Round`. A submitted Cleared Interview for the exact Job Applicant is mandatory at every offer save; another application belonging to the same candidate cannot satisfy it. A native Interview `Accepted` applicant status is not an accepted offer and never consumes capacity.
4. Create native Job Offer. Fields cover role/department/grade/manager/location/hours/mode/start/probation/salaries/allowances/bonus/benefits/contract/exception file; native Terms supports notes. Department and start date are required. **Submit Offer → Review Offer (HR Lead) → Approve Offer (Director)**. CEO review freezes the HR-reviewed compensation until returned to Draft. CEO approval submits the document. Submitted material fields, native terms and offer-term rows cannot change.
5. Before acceptance, a compensation change uses HR Lead **Cancel For Amendment**, then native **Amend**. The new document must start Draft and repeat both approvals; old compensation remains on the cancelled document. Accepted offers cannot be cancelled or have their response reversed by this slice; coordinate a separately authorized onboarding cancellation process. Do not directly set native status Cancelled.
6. On a submitted approved offer, set Offer Stage **Sent** and save, then use native email/print. Email requires configured native outgoing mail. `before_print` and reference-linked Communication block preapproval delivery; this is not an email-system-wide DLP policy and cannot prevent manually copying text into unrelated email. Offer Stage supports Negotiating and Expired; expiry is a manual HR action, not a timer. Set native Status **Accepted** or **Rejected** to record response. Rejected requires the catalog reason. No candidate email-link response endpoint is supplied.
7. Accepted offer locks vacancy capacity in the same transaction, recomputes accepted/remaining/progress and creates one native **Employee Onboarding draft** with job_offer, job_applicant, company, employee_name, department, designation, employee_grade, date_of_joining and boarding_begins_on. The parent onboarding module enriches templates/evidence/activities. HR must supply a holiday list and review tasks before submitting onboarding; native task creation needs it. No employee is prematurely created here.

Candidate matching serializes on the `TLC Recruitment Candidate` DocType metadata row, holding a database row lock to commit. Identifier document names are SHA-256 of type plus normalized value; this is a deterministic unique key, **not encryption of personal data**. HR Lead can read aliases; other employee roles cannot. Canonical records are HR-only, not a candidate portal. Backfill preexisting Job Applicants by saving them through normal document validation in a controlled migration owned by operations; configuration/seed does not silently migrate historical data. No production migration runs in this change.

Vacancy due date is `tlc_needed_by`, not native `closes_on`: native HRMS auto-closes expired openings, which would violate the closure rule. New TLC saves reject `closes_on`. Existing legacy openings with a populated native closes_on need operations review before scheduler use. Underfilled closures require the Director to record their own user in Cancellation Approved By. Counts use submitted native Accepted offers only; filled openings close automatically. Native requisition Filled is recalculated across all linked openings, not the first closed position. Automatic closing uses transactional database updates to avoid native single-opening completion behavior.

Talent Pool lives on canonical candidates, independent of vacancy lifetime. Moving an application to Talent Pool sets that candidate flag. HR classifies specialty/seniority/quality and uses native Job Applicant Duplicate/new application with copied profile fields for a new vacancy; canonical matching reuses the identity. Pipeline Select values can be changed through managed customization; there is no arbitrary pipeline designer or transition matrix enforcement.

## Catalog mapping: HR-TD-01 through HR-TD-40

`implemented` identifies TLC code, including explicitly bounded partial coverage; `default` identifies inspected native HRMS behavior, not new code; `external` means no complete implementation is delivered. None of these labels claims runtime verification. A partial facet never implies its entire requirement is supported.

| ID | Classification | Delivered behavior and unsupported facets |
|---|---|---|
| HR-TD-01 | implemented | Native requisition identifiers/date/department/designation/quantity/budget/reason plus TLC type/replacement/JD/location; JD and needed-by gate on submission. Multi-position child rows share parent JD/budget/date; per-position separate JD/budget is not modeled. |
| HR-TD-02 | implemented | Manager request → HR Lead review → Director approval workflow. |
| HR-TD-03 | implemented | Approved request creates one vacancy per position row, or one native primary position; inherits common content and row department/location. |
| HR-TD-04 | implemented | Accepted offer counts, remaining and percent; capacity lock; filled auto-close or Director-approved underfill closure. Native legacy auto-expiry caveat above. |
| HR-TD-05 | external | Needed-by and native list filtering available; no near-due/overdue/no-applicant alert engine delivered. |
| HR-TD-06 | default | Native Job Opening publish/website route and Job Applicant web application support. No external job-board publisher delivered; website behavior is not browser-verified here. |
| HR-TD-07 | external | No internal-first configurable interval, internal application notification or current-manager integration. |
| HR-TD-08 | implemented | Native name/email/phone/CV/source and TLC birth/gender/address/education/experience/portfolio/received date, linked to canonical profile. Education/experience are text, not structured degree/employment tables. |
| HR-TD-09 | implemented | Canonical dedup across normalized email/phone/identity, bridge merges, retained aliases/profiles and multiple distinct native applications. Existing data requires controlled resave/backfill. |
| HR-TD-10 | implemented | Default complete pipeline and terminal states as configurable Select; application history stays native. No arbitrary stage-transition engine or historical conversion event ledger. |
| HR-TD-11 | implemented | Rejected/Withdrawn reason catalogs, including native Rejected path; Other is available, no additional mandatory free-text detail. |
| HR-TD-12 | implemented | Dedicated seed creates LinkedIn/VietnamWorks/TopCV/Facebook/Internal Referral/Headhunter/Other; source-level cost field. Not an accounting expense ledger. |
| HR-TD-13 | external | No inbound CV email/folder/job-board ingestion or parsing. Native website application is not claimed as these connectors. |
| HR-TD-14 | default | Native Employee Referral link/status update retained. No TLC post-probation reward calculation or payroll posting. |
| HR-TD-15 | implemented | Native date/time/type/interviewers plus TLC mode and manually recorded candidate confirmation. Native interview notification/reschedule mechanisms require mail config; automated invitation/RSVP confirmation flow is not supplied or claimed. |
| HR-TD-16 | default | Native Interview Type expected skills/rating/designation and feedback assessments. No per-criterion weights/maxima/floor scorecard engine. |
| HR-TD-17 | default | Native multiple interviewer feedback, arithmetic ratings and comments. No separate strengths/improvements or Offer/Talent Pool recommendation fields/weighted totals. |
| HR-TD-18 | external | No assigned-only candidate ACL or blind-score release policy added. Do not treat native broad HR/interviewer permissions as meeting this requirement. |
| HR-TD-19 | external | No Director dossier approval substitute for final interview; final gate intentionally still requires native submitted Cleared Interview. |
| HR-TD-20 | implemented | Persistent canonical Talent Pool flag independent of vacancy, supports direct HR entry and keeping declined/potential candidates manually. No automatic eligibility classifier. |
| HR-TD-21 | implemented | Specialty/seniority/quality catalogs on native Desk canonical form. One value per dimension, not multi-tag taxonomy. |
| HR-TD-22 | external | Native list filters only. No cross-interview multi-condition search across skills/language/score/reviewer/salary/time. |
| HR-TD-23 | implemented | Native Duplicate/new Job Applicant retaining profile and new vacancy reuses canonical identity on save; no bulk reactivation wizard. |
| HR-TD-24 | external | No consent capture, retention clock, erasure proposal or anonymization. Canonical data remains personal data subject to operational policy. |
| HR-TD-25 | implemented | Exact-application final submitted Cleared gate; native offer plus TLC specified employment/compensation fields. Conditional exception authorization validity is not adjudicated. |
| HR-TD-26 | implemented | HR→Director workflow, submission freeze including terms, native cancel/amend reapproval. Accepted-offer reversal is intentionally unavailable. |
| HR-TD-27 | default | Native offer term template/terms/print/email surfaces retained and approval-gated. No TLC branded mail-merge PDF template or automatic sending job supplied. |
| HR-TD-28 | implemented | Draft/Pending Approval/Approved/Sent/Negotiating/Accepted/Rejected/Expired progression, rejection reasons. HR records responses and expiry manually. |
| HR-TD-29 | external | No signed candidate email-link accept/reject endpoint or identity verification. |
| HR-TD-30 | implemented | Submitted Accepted native offer updates vacancy and idempotently creates native onboarding draft; atomic capacity enforcement. |
| HR-TD-31 | default | Native Job Applicant/Offer/Employee Onboarding employee mapper entry points retained. Parent onboarding owns employee creation; full CV/degree/interview attachment migration is not implemented here. |
| HR-TD-32 | implemented | Number cards for open vacancies and remaining headcount; native company/department/location list filters. No complete waiting/filled/overdue dashboard or linked cross-card filters. Parent workspaces must place resources. |
| HR-TD-33 | implemented | Current pipeline group-by chart only; no historical stage conversion rates or event-time funnel. |
| HR-TD-34 | external | Sources and one cost field exist; no aggregate CV/interview/offer/join/cost effectiveness report. |
| HR-TD-35 | default | Native requisition time-to-fill and applicant/offer dates retained; no complete Time-to-Hire/Cost-to-Hire report or dimensional joined metrics. Native time-to-fill is not represented as meeting the requested joining-date formula. |
| HR-TD-36 | implemented | HR/CEO pending and Accepted cards plus offer-stage chart. No acceptance percentage or reason-distribution chart in this slice; native acceptance-rate method remains available. |
| HR-TD-37 | external | No CV/JD AI matching; no automated rejection. |
| HR-TD-38 | external | No AI ranking or inferred match score. |
| HR-TD-39 | external | No AI Talent Pool recommendation. |
| HR-TD-40 | external | No AI multi-interviewer summary. |

## Maintenance and evidence

Keep salary/benefit additions in `COMPENSATION_FIELDS` as well as YAML, and extend freeze tests. Preserve applicant-level final gates when changing canonical matching. Never remove aliases or merge Job Applicant records to deduplicate people. A candidate can have more than one application but a single application's final interview cannot authorize another application's offer.

Unit source: `tests/unit/test_recruitment.py` covers normalization, invalid identity, bridge matching orchestration, requisition gates, reason catalogs, final-round isolation, freeze, stage ordering and capacity. It does not claim database concurrency or permission coverage. `uat/journeys/recruitment.py` exports `JOURNEYS` and uses Session/case/login with native Desk browser controls for canonical linkage, negative final gate, HR/CEO offer approval, salary lock and acceptance/onboarding. `uat/stories/recruitment.yaml` maps those cases; requisition and amendment stories have no automated case yet and are not presented as exercised evidence.

No tests, builds, linters, site configuration writes, migrations or UAT runs were executed for this slice. Parent verification should include unit/architecture/customization schema checks, fresh-site metadata dependency order, real role permissions, mail/print preapproval denial, two concurrent last-seat acceptances, native cancel/amend and the declared Desk journey. Database locking and cross-module onboarding are source implementations awaiting site verification, not observed results.
