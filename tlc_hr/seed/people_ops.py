"""Explicit demo fixtures for W5 People Operations Desk UAT; never invoked by imports or migrations."""
import frappe
from frappe.utils import add_days, getdate, now_datetime, today
from frappe.utils.file_manager import save_file


def _insert(doctype, filters, values):
    existing = frappe.db.get_value(doctype, filters, "name")
    if existing:
        return existing
    doc = frappe.get_doc({"doctype": doctype, **values})
    doc.insert(ignore_permissions=True)
    return doc.name


def run(data=None):
    """Run after config apply and main employee seed. Leaves approval fixtures in testable draft states."""
    employee = frappe.db.get_value("Employee", {"user_id": "an@demo.example"}, "name")
    if not employee:
        frappe.throw("Seed people_ops cần nhân viên an@demo.example từ seed chính.")
    company = frappe.db.get_value("Employee", employee, "company") or "TLC"
    hr_user = frappe.db.get_value("User", {"email": "hoa@demo.example"}, "name") or "Administrator"
    officer_user = frappe.db.get_value("User", {"email": "lan@demo.example"}, "name") or hr_user

    evidence_file = frappe.db.get_value("File", {"file_name": "tlc-people-ops-evidence.txt", "is_private": 1}, "file_url")
    if not evidence_file:
        evidence_file = save_file(
            "tlc-people-ops-evidence.txt",
            "TLC W5 DEMO EVIDENCE ONLY. Hồ sơ minh chứng thử nghiệm người lao động và tài sản; không có giá trị pháp lý thực tế.\n",
            "Employee",
            employee,
            is_private=1,
        ).file_url

    start = getdate(today())

    # 1. Native Asset Item & Asset (ERPNext Assets)
    item_group = frappe.db.get_value("Item Group", {"item_group_name": "All Item Groups"}, "name") or "All Item Groups"
    category = frappe.db.get_value("Asset Category", {}, "name")
    if not category:
        fixed = frappe.db.get_value("Account", {"company": company, "account_type": "Fixed Asset", "is_group": 0}, "name")
        accumulated = frappe.db.get_value("Account", {"company": company, "account_type": "Accumulated Depreciation", "is_group": 0}, "name")
        depreciation = frappe.db.get_value("Account", {"company": company, "account_type": "Depreciation", "is_group": 0}, "name")
        if not (fixed and accumulated and depreciation):
            frappe.throw("Cần tài khoản TSCĐ, hao mòn và chi phí khấu hao để tạo nhóm tài sản demo.")
        category = frappe.get_doc({"doctype": "Asset Category", "asset_category_name": "TLC IT Equipment",
            "accounts": [{"company_name": company, "fixed_asset_account": fixed,
                          "accumulated_depreciation_account": accumulated, "depreciation_expense_account": depreciation}]
            }).insert(ignore_permissions=True).name
    item = _insert("Item", {"item_code": "IT-LAPTOP-TLC"}, {
        "item_code": "IT-LAPTOP-TLC",
        "item_name": "Laptop Lenovo ThinkPad T14",
        "item_group": item_group,
        "asset_category": category,
        "is_stock_item": 0,
        "is_fixed_asset": 1,
        "auto_create_assets": 0,
    })
    if not frappe.db.get_value("Item", item, "asset_category"):
        frappe.db.set_value("Item", item, "asset_category", category)
    location = frappe.db.get_value("Location", {}, "name")
    if not location:
        location = frappe.get_doc({"doctype": "Location", "location_name": "TLC Văn phòng SG"}).insert(
            ignore_permissions=True).name
    asset = _insert("Asset", {"asset_name": "ThinkPad T14 - AN"}, {
        "asset_name": "ThinkPad T14 - AN",
        "item_code": item,
        "asset_category": category,
        "location": location,
        "company": company,
        "gross_purchase_amount": 25000000,
        "net_purchase_amount": 25000000,
        "purchase_date": add_days(start, -30),
        "available_for_use_date": add_days(start, -30),
        "is_existing_asset": 1,
    })

    # Draft Asset Movement awaiting dual receipt
    movement_name = frappe.db.sql(
        "select m.name from `tabAsset Movement` m join `tabAsset Movement Item` i on i.parent=m.name where i.asset=%s and m.docstatus=0",
        (asset,),
    )
    if movement_name:
        movement = movement_name[0][0]
    else:
        m_doc = frappe.get_doc({
            "doctype": "Asset Movement",
            "company": company,
            "purpose": "Issue",
            "transaction_date": now_datetime(),
            "tlc_ops_staff": hr_user,
            "tlc_ops_condition": "Máy mới 100%, đủ phụ kiện sạc và chuột",
            "tlc_ops_evidence": evidence_file,
            "assets": [{
                "asset": asset,
                "to_employee": employee,
            }],
        })
        m_doc.insert(ignore_permissions=True)
        movement = m_doc.name

    # 2. IT Licenses & Accounts
    license_doc = _insert("TLC People Ops License", {"system_name": "Google Workspace Enterprise"}, {
        "system_name": "Google Workspace Enterprise",
        "seats": 50,
        "expires_on": add_days(start, 365),
        "evidence": evidence_file,
    })
    account = _insert("TLC People Ops Account", {"employee": employee, "license": license_doc}, {
        "employee": employee,
        "license": license_doc,
        "account_identifier": "an@demo.example",
        "status": "Requested",
        "evidence": evidence_file,
        "reason": "Cấp tài khoản demo cho nhân viên văn phòng.",
    })
    account_doc = frappe.get_doc("TLC People Ops Account", account)
    if account_doc.status == "Requested":
        account_doc.status = "Active"
        account_doc.save(ignore_permissions=True)

    # 3. Mandatory Training & Expiring Certificate
    program = _insert("Training Program", {"training_program": "ATVSLĐ & PCCC Định Kỳ"}, {
        "training_program": "ATVSLĐ & PCCC Định Kỳ",
        "company": company,
        "description": "Chương trình huấn luyện an toàn vệ sinh lao động và phòng cháy chữa cháy.",
    })
    req = _insert("TLC People Ops Training Requirement", {"training_program": program}, {
        "training_program": program,
        "recurrence_days": 365,
        "due_days": 30,
        "enabled": 1,
    })
    cert = _insert("TLC People Ops Certificate", {"employee": employee, "training_program": program}, {
        "employee": employee,
        "training_program": program,
        "requirement": req,
        "status": "Completed",
        "completed_on": add_days(start, -340),
        "issued_on": add_days(start, -340),
        "expires_on": add_days(start, 25),  # within 30 days reminder band
        "issuer": "TLC Safety Committee",
        "score": 95,
        "hours": 8,
        "cost": 500000,
        "certificate": evidence_file,
    })

    # 4. Benefits Hiếu Hỷ & Health Appointments
    benefit_policy = _insert("TLC People Ops Benefit Policy", {"event": "Marriage"}, {
        "event": "Marriage",
        "effective_from": add_days(start, -180),
        "effective_to": add_days(start, 180),
        "amount": 3000000,
        "policy_file": evidence_file,
    })
    benefit_claim = _insert("TLC People Ops Benefit Claim", {"employee": employee, "policy": benefit_policy}, {
        "employee": employee,
        "policy": benefit_policy,
        "event_date": start,
        "evidence": evidence_file,
        "amount": 3000000,
        "status": "Draft",
    })
    health = _insert("TLC People Ops Health Appointment", {"employee": employee, "provider": "Bệnh viện Đa khoa Tâm Anh"}, {
        "employee": employee,
        "scheduled_at": now_datetime(),
        "provider": "Bệnh viện Đa khoa Tâm Anh",
        "responsible_hr": officer_user,
        "status": "Scheduled",
    })

    # 5. Policy Version & Acknowledgment
    policy_ver = _insert("TLC People Ops Policy Version", {"policy_code": "POL-TLC-2026", "version": 1}, {
        "policy_code": "POL-TLC-2026",
        "version": 1,
        "effective_from": start,
        "body": "Nội quy lao động và quy tắc ứng xử TLC 2026: Tuân thủ bảo mật và chuẩn mực văn hóa doanh nghiệp.",
        "policy_file": evidence_file,
        "status": "Published",
    })
    ack = _insert("TLC People Ops Acknowledgment", {"employee": employee, "policy_version": policy_ver}, {
        "employee": employee,
        "policy_version": policy_ver,
        "policy_snapshot": "Nội quy lao động và quy tắc ứng xử TLC 2026: Tuân thủ bảo mật và chuẩn mực văn hóa doanh nghiệp.",
    })

    # 6. Discipline & Grievance
    discipline = _insert("TLC People Ops Discipline", {"employee": employee, "reason": "TLC W5 Demo: Đi muộn 3 lần không phép"}, {
        "employee": employee,
        "status": "Proposal",
        "reason": "TLC W5 Demo: Đi muộn 3 lần không phép",
        "proposed_by": "quang@demo.example",
    })
    g_type = _insert("Grievance Type", {"name": "Cơ sở vật chất"}, {"name": "Cơ sở vật chất"})
    grievance = _insert("Employee Grievance", {"raised_by": employee, "subject": "Đề xuất cải thiện nhiệt độ phòng làm việc"}, {
        "raised_by": employee,
        "subject": "Đề xuất cải thiện nhiệt độ phòng làm việc",
        "grievance_type": g_type,
        "grievance_against_party": "Company",
        "grievance_against": company,
        "date": start,
        "status": "Open",
        "description": "Khu vực bàn làm việc đối diện cửa gió điều hòa, nhiệt độ quá lạnh ảnh hưởng sức khỏe.",
    })

    # 7. Native Appraisal Cycle, Goal & Appraisal
    cycle = _insert("Appraisal Cycle", {"cycle_name": "TLC 2026 Annual Performance Cycle"}, {
        "cycle_name": "TLC 2026 Annual Performance Cycle",
        "company": company,
        "start_date": start,
        "end_date": add_days(start, 365),
    })
    goal = _insert("Goal", {"employee": employee, "goal_name": "Hoàn thành kế hoạch kinh doanh Q4"}, {
        "employee": employee,
        "goal_name": "Hoàn thành kế hoạch kinh doanh Q4",
        "appraisal_cycle": cycle,
        "start_date": start,
        "end_date": add_days(start, 90),
        "tlc_ops_weight": 100,
        "description": "Đạt chỉ tiêu doanh thu và phát triển tối thiểu 5 khách hàng chiến lược mới.",
    })
    appraisal = _insert("Appraisal", {"employee": employee, "appraisal_cycle": cycle}, {
        "employee": employee,
        "company": company,
        "appraisal_cycle": cycle,
        "start_date": start,
        "end_date": add_days(start, 365),
        "tlc_ops_stage": "Self Review",
    })

    return {
        "employee": employee,
        "asset": asset,
        "movement": movement,
        "license": license_doc,
        "account": account,
        "training_requirement": req,
        "certificate": cert,
        "benefit_claim": benefit_claim,
        "health_appointment": health,
        "policy_version": policy_ver,
        "acknowledgment": ack,
        "discipline": discipline,
        "grievance": grievance,
        "goal": goal,
        "appraisal": appraisal,
    }
