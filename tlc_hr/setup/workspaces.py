"""Role workspaces of TLC on the standard Frappe desk: number cards, dashboard charts, quick lists and shortcuts.

Everything is a standard Frappe document (Workspace, Number Card, Dashboard Chart), rebuilt after every migration so the
definition here stays the single source. Counts and charts go through Frappe permissions, so a factory head sees the numbers
of their own people and HR or the director see the whole company.
"""

import json

import frappe

from tlc_hr.setup.install import TO_HR, TO_MANAGER

MODULE = "TLC HR"
LEAVE = "Leave Application"
TODAY = "frappe.datetime.get_today()"

NUMBER_CARDS = {
    # name: (doctype, static filters, dynamic filters, color)
    "TLC Nhân sự đang làm việc": ("Employee", [["Employee", "status", "=", "Active"]], [], "#2f8a3c"),
    "TLC Nhân sự khối Nhà máy": ("Employee", [["Employee", "status", "=", "Active"], ["Employee", "tlc_workforce", "=", "factory"]], [], "#b5541b"),
    "TLC Nhân sự khối Hội sở": ("Employee", [["Employee", "status", "=", "Active"], ["Employee", "tlc_workforce", "=", "head_office"]], [], "#1d5fa8"),
    "TLC Đơn chờ quản lý duyệt": (LEAVE, [[LEAVE, "workflow_state", "=", TO_MANAGER]], [], "#e2a400"),
    "TLC Đơn chờ nhân sự duyệt": (LEAVE, [[LEAVE, "workflow_state", "=", TO_HR]], [], "#e2a400"),
    "TLC Đơn chờ tôi duyệt": (LEAVE, [[LEAVE, "workflow_state", "=", TO_MANAGER]], [[LEAVE, "leave_approver", "=", "frappe.session.user"]], "#d9480f"),
    "TLC Chấm công hôm nay": ("Employee Checkin", [["Employee Checkin", "log_type", "=", "IN"]],
                              [["Employee Checkin", "time", ">=", TODAY]], "#0ca678"),
    "TLC Điều chỉnh công chờ duyệt": ("Attendance Request", [["Attendance Request", "workflow_state", "in", [TO_MANAGER, TO_HR]]],
                                     [], "#e2a400"),
    "TLC Đi muộn tháng này": ("Attendance", [["Attendance", "late_entry", "=", 1], ["Attendance", "docstatus", "=", 1],
                                            ["Attendance", "attendance_date", "Timespan", "this month"]], [], "#e8590c"),
    "TLC Nghỉ phép hôm nay": (LEAVE, [[LEAVE, "status", "=", "Approved"]],
                              [[LEAVE, "from_date", "<=", TODAY], [LEAVE, "to_date", ">=", TODAY]], "#7048e8"),
}

CHARTS = {
    "TLC Nhân sự theo phòng ban": {"chart_type": "Group By", "document_type": "Employee", "group_by_type": "Count",
                                   "group_by_based_on": "department", "number_of_groups": 12, "type": "Bar",
                                   "filters_json": json.dumps([["Employee", "status", "=", "Active"]])},
    "TLC Chấm công tháng này": {"chart_type": "Group By", "document_type": "Attendance", "group_by_type": "Count",
                                "group_by_based_on": "status", "type": "Donut",
                                "filters_json": json.dumps([["Attendance", "docstatus", "=", 1],
                                                            ["Attendance", "attendance_date", "Timespan", "this month"]])},
    "TLC Đơn nghỉ theo trạng thái": {"chart_type": "Group By", "document_type": LEAVE, "group_by_type": "Count",
                                     "group_by_based_on": "workflow_state", "type": "Donut", "filters_json": "[]"},
    "TLC Ngày nghỉ đã duyệt theo tháng": {"chart_type": "Sum", "document_type": LEAVE, "based_on": "from_date",
                                         "value_based_on": "total_leave_days", "timeseries": 1, "timespan": "Last Year",
                                         "time_interval": "Monthly", "type": "Bar",
                                         "filters_json": json.dumps([[LEAVE, "status", "=", "Approved"]])},
}

SHORTCUTS = {
    # label: (type, link_to or url, doc_view, color, stats filter)
    "Đơn chờ duyệt": ("DocType", LEAVE, "List", "Orange", [[LEAVE, "workflow_state", "in", [TO_MANAGER, TO_HR]]]),
    "Lịch nghỉ phép": ("DocType", LEAVE, "Calendar", "Green", None),
    "Nhân viên": ("DocType", "Employee", "List", "Blue", [["Employee", "status", "=", "Active"]]),
    "Sơ đồ tổ chức": ("Page", "organizational-chart", "", "Grey", None),
    "Chấm công": ("DocType", "Employee Checkin", "List", "Green", None),
    "Bảng công": ("DocType", "Attendance", "List", "Blue", None),
    "Điều chỉnh công": ("DocType", "Attendance Request", "List", "Orange",
                        [["Attendance Request", "workflow_state", "in", [TO_MANAGER, TO_HR]]]),
    "Phân ca": ("DocType", "Shift Assignment", "List", "Grey", None),
    # The report needs a period: the shortcut opens it on the current year (refreshed at every migration).
    "Số dư phép": ("URL", "/desk/query-report/Employee Leave Balance?from_date={year}-01-01&to_date={year}-12-31", "", "Grey", None),
    "Cấp phép năm": ("DocType", "Leave Allocation", "List", "Grey", None),
    "Lịch nghỉ lễ": ("DocType", "Holiday List", "List", "Grey", None),
    "Tham số lương Việt Nam": ("DocType", "VN Payroll Settings", "", "Grey", None),
    "Yêu cầu cần xử lý": ("DocType", "ToDo", "List", "Grey", [["ToDo", "status", "=", "Open"]]),
    "Ứng dụng Frappe HR": ("URL", "/hrms", "", "Green", None),
}

WORKSPACES = {
    "TLC Quản lý": {
        "roles": ["TLC Line Manager"], "icon": "users", "sequence": 1,
        "cards": ["TLC Đơn chờ tôi duyệt", "TLC Điều chỉnh công chờ duyệt", "TLC Nhân sự đang làm việc", "TLC Chấm công hôm nay",
                  "TLC Đi muộn tháng này",
                  "TLC Nghỉ phép hôm nay"],
        "charts": ["TLC Chấm công tháng này", "TLC Đơn nghỉ theo trạng thái"],
        "quick_list": (LEAVE, "Đơn chờ quản lý duyệt", [[LEAVE, "workflow_state", "=", TO_MANAGER]]),
        "shortcuts": ["Đơn chờ duyệt", "Điều chỉnh công", "Lịch nghỉ phép", "Chấm công", "Bảng công", "Nhân viên", "Sơ đồ tổ chức",
                      "Số dư phép",
                      "Ứng dụng Frappe HR"],
    },
    "TLC Nhân sự": {
        "roles": ["TLC HR Lead", "TLC HR Officer"], "icon": "hr", "sequence": 2,
        "cards": ["TLC Nhân sự đang làm việc", "TLC Nhân sự khối Hội sở", "TLC Nhân sự khối Nhà máy", "TLC Đơn chờ nhân sự duyệt",
                  "TLC Điều chỉnh công chờ duyệt", "TLC Chấm công hôm nay", "TLC Đi muộn tháng này", "TLC Nghỉ phép hôm nay"],
        "charts": ["TLC Chấm công tháng này", "TLC Nhân sự theo phòng ban", "TLC Ngày nghỉ đã duyệt theo tháng"],
        "quick_list": (LEAVE, "Đơn chờ nhân sự duyệt", [[LEAVE, "workflow_state", "=", TO_HR]]),
        "shortcuts": ["Đơn chờ duyệt", "Điều chỉnh công", "Lịch nghỉ phép", "Chấm công", "Bảng công", "Phân ca", "Nhân viên",
                      "Cấp phép năm", "Lịch nghỉ lễ",
                      "Tham số lương Việt Nam",
                      "Số dư phép", "Sơ đồ tổ chức", "Yêu cầu cần xử lý"],
    },
    "TLC Điều hành": {
        "roles": ["TLC Director"], "icon": "dashboard", "sequence": 3,
        "cards": ["TLC Nhân sự đang làm việc", "TLC Nhân sự khối Hội sở", "TLC Nhân sự khối Nhà máy", "TLC Đơn chờ tôi duyệt",
                  "TLC Đơn chờ quản lý duyệt", "TLC Đơn chờ nhân sự duyệt", "TLC Chấm công hôm nay", "TLC Nghỉ phép hôm nay"],
        "charts": ["TLC Chấm công tháng này", "TLC Nhân sự theo phòng ban", "TLC Ngày nghỉ đã duyệt theo tháng"],
        "quick_list": (LEAVE, "Đơn chờ tôi duyệt", [[LEAVE, "workflow_state", "=", TO_MANAGER]]),
        "shortcuts": ["Đơn chờ duyệt", "Lịch nghỉ phép", "Nhân viên", "Sơ đồ tổ chức", "Số dư phép"],
    },
}


def upsert(doctype, name, values):
    doc = frappe.get_doc(doctype, name) if frappe.db.exists(doctype, name) else frappe.new_doc(doctype)
    doc.update(values)
    doc.flags.ignore_permissions = True
    doc.flags.ignore_links = True
    doc.save() if not doc.is_new() else doc.insert()
    return doc


def ensure_number_cards():
    for label, (doctype, filters, dynamic, color) in NUMBER_CARDS.items():
        upsert("Number Card", label, {
            "label": label, "type": "Document Type", "document_type": doctype, "function": "Count", "is_public": 1,
            "module": MODULE, "color": color, "filters_json": json.dumps(filters), "dynamic_filters_json": json.dumps(dynamic),
            "show_percentage_stats": 0,
        })


def ensure_charts():
    for name, values in CHARTS.items():
        upsert("Dashboard Chart", name, {"chart_name": name, "is_public": 1, "module": MODULE, "color": "#2f8a3c", **values})


def block(kind, key, value, col):
    return {"id": frappe.generate_hash(length=10), "type": kind, "data": {key: value, "col": col}}


def ensure_workspaces():
    for title, spec in WORKSPACES.items():
        content = [{"id": frappe.generate_hash(length=10), "type": "header", "data": {"text": f'<span class="h4"><b>{title}</b></span>', "col": 12}}]
        content += [block("number_card", "number_card_name", c.replace("TLC ", ""), 3) for c in spec["cards"]]  # blocks name the row label
        content += [block("shortcut", "shortcut_name", s, 3) for s in spec["shortcuts"]]
        content += [block("quick_list", "quick_list_name", spec["quick_list"][1], 12)]
        content += [block("chart", "chart_name", c.replace("TLC ", ""), 6) for c in spec["charts"]]
        values = {
            "label": title, "title": title, "module": MODULE, "public": 1, "icon": spec["icon"], "sequence_id": spec["sequence"],
            "content": json.dumps(content), "roles": [{"role": r} for r in spec["roles"]],
            "number_cards": [{"number_card_name": c, "label": c.replace("TLC ", "")} for c in spec["cards"]],
            "charts": [{"chart_name": c, "label": c.replace("TLC ", "")} for c in spec["charts"]],
            "quick_lists": [{"document_type": spec["quick_list"][0], "label": spec["quick_list"][1],
                             "quick_list_filter": json.dumps(spec["quick_list"][2])}],
            "shortcuts": [],
        }
        if frappe.get_meta("Workspace").has_field("app"):
            values["app"] = "tlc_hr"
        doc = upsert("Workspace", title, values)
        doc.shortcuts = []
        for label in spec["shortcuts"]:
            kind, target, view, color, stats = SHORTCUTS[label]
            row = {"label": label, "type": kind, "color": color, "doc_view": view or ""}
            if kind == "URL":
                row["url"] = target.format(year=frappe.utils.getdate().year)
            else:
                row["link_to"] = target
            if stats:
                row["stats_filter"] = json.dumps(stats)
                row["format"] = "{} đơn" if target == LEAVE else "{}"
            doc.append("shortcuts", row)
        doc.save(ignore_permissions=True)


def ensure_all():
    ensure_number_cards()
    ensure_charts()
    ensure_workspaces()
