# tlc_hr

TLC HRM on Frappe HR v16. Everything TLC-specific lives here; frappe, erpnext, hrms and erpnextvn keep their standard interface.

- Interface: the standard one. Employees and factory workers use the Frappe HR app (`/hrms`, role TLC Self Service lands there);
  line managers, HR and the director use the desk, each in a role workspace (TLC Quản lý, TLC Nhân sự, TLC Điều hành) built from
  standard number cards, dashboard charts, quick lists and shortcuts (`setup/workspaces.py`, rebuilt after every migration).
- Workflow TLC Nghỉ phép: employee → line manager → HR (lead or officer); nobody decides their own request; a rejection needs a
  reason (asked in a dialog on the standard form, stored at permlevel 1: employees read it, approvers write it).
- Leave Application form (`public/js/leave_application.js`): what helps the approver decide (balance after approval, colleagues of
  the same department away on those days).
- Roles and data scope per TLC level; Vietnamese e-mail templates for the HRMS leave notifications; Vietnamese strings of the
  Frappe HR app (`translations/vi.csv`).
- Vietnamese rules over erpnextvn: PIT in 5 brackets (Luật 109/2025), base salary and deductions of 2026.
- The TLC demo seed (`bench execute tlc_hr.seed.run`): company, sites, departments, 60 people, users, leave, demo mail account.

License: GPL-3.0 (same as Frappe HR).
