"""Monthly attendance closing: the names the code shares with customizing/workflows/attendance_period.yaml.

Annual leave of a year may be used until 30 March of the next year (BRD HR-CP-12): the Leave Type declares a carried part that
uses 89 days as the non-leap-year default in customizing/records.yaml. The Leave Ledger Entry adapter enforces 30 March
in every year, including leap years; the fixed HRMS setting alone is insufficient.
"""

WORKFLOW = "TLC Chốt công"
TO_HEAD, TO_HR, TO_CEO, LOCKED, REOPENED = "Chờ quản lý xác nhận", "Chờ nhân sự đối soát", "Chờ giám đốc ký", "Đã khoá", "Đã mở lại"
ANNUAL_LEAVE, CARRY_FORWARD_DAYS = "Phép năm", 89
