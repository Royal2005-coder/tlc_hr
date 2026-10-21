"""Install and migrate hooks of tlc_hr: the customizing declared in tlc_hr/customizing is applied by the engine
(infrastructure/customizing); see docs/CONFIGURATION.md."""

import frappe

# States shared by the TLC approval workflows (the YAML workflows use these names).
DRAFT, TO_MANAGER, TO_HR, APPROVED, REJECTED, CANCELLED = (
    "Nháp", "Chờ quản lý duyệt", "Chờ nhân sự duyệt", "Đã duyệt", "Từ chối", "Đã hủy")


def after_migrate():
    from tlc_hr.infrastructure.customizing import engine

    engine.apply()
    frappe.db.commit()
