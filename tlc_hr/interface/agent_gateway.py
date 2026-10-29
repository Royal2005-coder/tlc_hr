"""Agentic HRM gateway: one front agent (@Leo) whose skills hold tools, and every write waits for a person.

The design follows the Apollo governance plane used on the Odoo side: a tool declares its risk class and a closed
argument contract, the gateway plans (model) and executes (deterministic code), and nothing that commits the company
runs without a second person approving the case. Reads answer immediately; drafts are created but never sent; a
controlled action becomes a TLC AI Case in "Chờ duyệt" with the requester's own arguments frozen in it.
"""

import hashlib
import json
import os
import re

import frappe
from frappe.utils import flt, get_url, getdate, now_datetime

from tlc_hr.contracts.assistant import AssistantQuery, LeaveDraft
from tlc_hr.interface import llm

READ, DRAFT, APPROVAL, FORBIDDEN = "read", "draft", "approval", "forbidden"
STATE_PROPOSED, STATE_WAITING, STATE_DONE, STATE_REFUSED, STATE_FAILED = (
    "Đề xuất", "Chờ duyệt", "Đã thực hiện", "Từ chối", "Lỗi")

# Tools that work on the caller's own records: their employee identity comes from the login, not from the model.
SELF_TOOLS = ("hrm.draft_leave", "hrm.draft_travel", "hrm.draft_attendance_correction", "hrm.draft_overtime",
              "hrm.submit_leave", "hrm.my_records", "hrm.my_to_decide", "hrm.document_link")

# The closed tool surface. `service` is the only thing that touches documents, and it is chosen here, never by the model.
TOOLS = {
    "hrm.my_records": {
        "title": "Hồ sơ, công, phép, phiếu lương của chính tôi", "risk": READ, "contract": None,
        "description": "Đọc dữ liệu của người đang nói chuyện: hồ sơ, số dư phép, đơn đang chờ ai, phiếu lương đã ghi sổ.",
    },
    "hrm.my_to_decide": {
        "title": "Việc tôi cần duyệt", "risk": READ, "contract": None,
        "description": "Danh sách hồ sơ đang chờ chính người đang nói chuyện duyệt.",
    },
    "hrm.policy_search": {
        "title": "Tra chính sách đã duyệt", "risk": READ, "contract": None,
        "description": "Chỉ trả lời từ chính sách đã duyệt và hiển thị với vai trò của người hỏi.",
    },
    "hrm.document_link": {
        "title": "Đường dẫn mở hồ sơ của chính tôi", "risk": READ, "contract": None,
        "description": "Cho đường dẫn mở một hồ sơ của chính người đang nói chuyện khi họ nêu mã (HR-LAP-, HR-TRQ-, TLC-OT-).",
    },
    "hrm.draft_leave": {
        "title": "Soạn nháp đơn nghỉ phép", "risk": DRAFT, "contract": LeaveDraft,
        "description": "Tạo bản NHÁP đơn nghỉ phép của chính mình; không gửi duyệt.",
    },
    "hrm.draft_travel": {
        "title": "Soạn nháp đề nghị công tác", "risk": DRAFT, "contract": None,
        "description": "Tạo bản NHÁP Travel Request của chính mình; không gửi duyệt.",
    },
    "hrm.draft_attendance_correction": {
        "title": "Soạn nháp giải trình công", "risk": DRAFT, "contract": None,
        "description": "Tạo bản NHÁP Attendance Request cho ngày quên chấm công của chính mình.",
    },
    "hrm.draft_overtime": {
        "title": "Soạn nháp đề nghị tăng ca", "risk": DRAFT, "contract": None,
        "description": "Tạo bản NHÁP TLC Overtime Request; người lao động và Giám đốc vẫn phải duyệt.",
    },
    "hrm.screen_cv": {
        "title": "AI chấm CV theo JD", "risk": DRAFT, "contract": None,
        "description": "Chạy đối chiếu CV với JD cho một hồ sơ tuyển dụng (chỉ HR).",
    },
    "hrm.submit_leave": {
        "title": "Gửi duyệt đơn nghỉ phép", "risk": APPROVAL, "contract": None,
        "description": "Gửi một nháp đơn phép của chính mình để quản lý duyệt; cần người duyệt case.",
    },
    "hrm.approve_document": {
        "title": "Duyệt/từ chối hồ sơ", "risk": FORBIDDEN, "contract": None,
        "description": "Phê duyệt nghiệp vụ luôn do người bấm trên form Desk theo workflow; chat không được duyệt.",
    },
    "hrm.run_payroll": {
        "title": "Tính lương, ký bảng lương, thanh toán", "risk": FORBIDDEN, "contract": None,
        "description": "Chạy lương, ký và thanh toán không nằm trong bộ công cụ của trợ lý.",
    },
    "hrm.change_role_or_data": {
        "title": "Đổi quyền, sửa/xóa dữ liệu đã ghi sổ", "risk": FORBIDDEN, "contract": None,
        "description": "Không đổi vai trò, không sửa hoặc xóa hồ sơ đã ghi sổ.",
    },
}

GREETING = re.compile(r"^\s*(hi|hello|hey|helo|alo|chào|chao|xin chào)", re.I)
HELP = ("Tôi có thể: đọc mã nhân viên, số dư phép, đơn đang chờ; cho đường dẫn mở một hồ sơ của bạn; "
        "soạn nháp đơn nghỉ phép, công tác, giải trình công, tăng ca; chấm CV (HR). "
        "Gửi duyệt và phê duyệt vẫn là việc của người.")

PERSONA = (
    "Bạn là @Leo, nhân viên AI của phòng Nhân sự TLC, làm việc trong chat Frappe HR.\n"
    "Bạn chỉ dùng đúng bộ công cụ được liệt kê. Bạn không tự quyết định nghiệp vụ: hồ sơ bạn tạo chỉ là bản nháp,"
    " mọi hành động ghi sổ phải qua một người duyệt.\n"
    "Chỉ đọc dữ liệu của chính người đang nói chuyện, trừ công cụ của HR đã được cấp quyền.\n"
    "Không bịa số liệu. Khi từ chối, nói rõ quy định nào chặn.\n"
    "Trả lời bằng tiếng Việt, ngắn, có mã hồ sơ để người dùng tự kiểm tra."
)


def _chat(messages, max_tokens=700):
    """The planner's model call; an out-of-quota provider is reported, not hidden behind "tôi chưa hiểu"."""
    try:
        return llm.chat(messages, max_tokens=max_tokens), ""
    except Exception as exc:
        return None, str(exc)[:200]


def _json_object(text):
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        try:
            return json.loads(match.group(0)) if match else None
        except json.JSONDecodeError:
            return None


def _fingerprint(tool, args):
    return hashlib.sha256(json.dumps([tool, args], sort_keys=True, default=str).encode()).hexdigest()[:24]


def _require(roles):
    if frappe.session.user == "Administrator":
        return True
    return bool(set(frappe.get_roles()) & set(roles))


def employee_of(user=None):
    return frappe.db.get_value("Employee", {"user_id": user or frappe.session.user}, "name")


def _clock():
    """The model owns no calendar: without today it turns "30 và 31 tháng này" into a year that never happened."""
    today = getdate()
    month = f"{today.year}-{today.month:02d}"
    return (f"Hôm nay là {today.isoformat()} (năm {today.year}). \"tháng này\" là {month}, \"ngày 30\" là {month}-30, "
            f"\"ngày 31 tháng này\" là {month}-31. Không dùng năm nào khác {today.year} trừ khi người dùng nêu rõ.")


def _arguments(contract):
    """The fields the gateway will demand, in the shape it will accept them."""
    properties = contract.model_json_schema().get("properties", {})
    hints = {}
    for name, spec in properties.items():
        hint = spec.get("description") or spec.get("pattern") or spec.get("type") or ""
        hints[name] = str(hint)[:60]
    return hints


def leave_type_names():
    return ", ".join(frappe.get_all("Leave Type", pluck="name", limit=20, order_by="name asc"))


# --------------------------------------------------------------------------------- planning (model) + routing

@frappe.whitelist()
def plan(message, channel=None):
    """Choose a tool and its arguments. The model proposes; the gateway decides and executes."""
    user = frappe.session.user
    skills = [{"code": code, "title": tool["title"], "risk": tool["risk"], "description": tool["description"],
               **({"args": _arguments(tool["contract"])} if tool["contract"] else {})}
              for code, tool in TOOLS.items()]
    messages = [
        {"role": "system", "content": PERSONA + "\n" + _clock()
                                       + "\nVới mỗi tool có args, điền đủ mọi khóa theo đúng định dạng đã nêu."
                                         " Nếu người dùng không cho đủ, trả tool=null thay vì chọn tool để rồi bỏ trống args."
                                       + "\nXin đường dẫn/link tới một hồ sơ đã có mã (HR-LAP-, HR-TRQ-, TLC-OT-) là"
                                       + " hrm.document_link; lời chào thì trả tool=null và để hệ thống chào lại."
                                       + "\nCâu hỏi về hồ sơ, mã nhân viên, phép hay phiếu lương của chính người"
                                         " hỏi là hrm.my_records — trả lời bằng số liệu thật, không hỏi lại."
                                       + "\nChỉ trả JSON: {\"tool\": code hoặc null, \"args\": {...},"
                                         " \"say\": \"một câu trả lời ngắn\"}"},
        {"role": "user", "content": f"Người dùng: {user}\nBộ công cụ: {json.dumps(skills, ensure_ascii=False)}\n"
                                    f"Loại nghỉ có sẵn: {leave_type_names()}. \"bệnh\", \"ốm\" là loại nghỉ ốm;"
                                    f" \"phép năm\" là loại hằng năm — tự chọn đúng loại, đừng hỏi lại tên loại nghỉ.\n"
                                    f"Tin nhắn: {message[:2000]}"},
    ]
    answer, failure = _chat(messages)
    proposal = _json_object(answer) or {}
    tool = proposal.get("tool") if proposal.get("tool") in TOOLS else None
    arguments = proposal.get("args") or {}
    if tool and TOOLS[tool]["contract"] is not None and not arguments:
        # naming the tool and dropping its arguments is a half answer, not a refusal: ask once, pointing at the gap
        retry, failure = _chat(messages + [{"role": "assistant", "content": (answer or "")[:600]},
                                           {"role": "user", "content": f"Bạn vừa chọn {tool} nhưng để trống args."
                                                                       " Hãy điền đủ args cho tool đó theo đúng các"
                                                                       " khóa đã nêu; nếu người dùng thực sự chưa cho đủ"
                                                                       " thì trả {\"tool\": null}. Chỉ trả JSON."}])
        again = _json_object(retry) or {}
        if again.get("tool") == tool and again.get("args"):
            proposal, arguments, answer = again, again["args"], retry
    return {"tool": tool, "args": arguments, "say": proposal.get("say") or "",
            "planner": "model" if tool else "none", "error": failure}


# -------------------------------------------------------------------------------------------------- the gateway

LABELS = {"leave_type": "loại nghỉ", "from_date": "ngày bắt đầu", "to_date": "ngày kết thúc",
          "reason": "lý do", "description": "lý do", "travel_type": "loại công tác", "purpose": "mục đích",
          "destination": "nơi đến", "ot_date": "ngày tăng ca", "attendance_date": "ngày cần điều chỉnh",
          "from_time": "từ giờ", "to_time": "đến giờ", "budget": "dự toán", "requested_advance": "tạm ứng"}


def _what_is_missing(exc):
    """A chat reply a person can act on: name the missing fields instead of showing the validator's own text."""
    errors = getattr(exc, "errors", lambda: [])() or []
    missing = [str(err.get("loc", ("?",))[0]) for err in errors if err.get("type") == "missing"]
    wrong = [str(err.get("loc", ("?",))[0]) for err in errors if err.get("type") not in ("missing", None)]
    if missing:
        return "Cần thêm " + ", ".join(LABELS.get(field, field) for field in missing) + ". Bạn nói rõ giúp tôi nhé."
    if wrong:
        return "Chưa đọc được " + ", ".join(LABELS.get(field, field) for field in wrong) + ". Bạn nói lại giúp tôi nhé."
    return f"Tham số chưa hợp lệ: {str(exc)[:160]}"


def _guard(tool_code, args, requester):
    """Closed contract, scope narrowing and role checks, before anything touches a document."""
    tool = TOOLS.get(tool_code)
    if not tool:
        return "Trợ lý không có công cụ đó."
    if tool["contract"] is not None:
        try:
            args = tool["contract"].model_validate(args).model_dump()
        except Exception as exc:
            return _what_is_missing(exc)
    if tool_code in SELF_TOOLS:
        if not employee_of(requester):
            return "Tài khoản này chưa gắn hồ sơ nhân viên nên không có dữ liệu để làm việc."
    if tool_code == "hrm.screen_cv" and not _require({"TLC HR Lead", "TLC HR Officer", "System Manager"}):
        return "Chỉ HR được chạy chấm CV."
    return None


@frappe.whitelist(methods=["POST"])
def act(message, tool=None, args=None, case=None):
    """The chat entry point: reads answer now, drafts create unsubmitted records, controlled actions open a case."""
    requester = frappe.session.user
    # only plan when the caller did not name the tool: a Raven custom tool already knows what it wants
    planned = plan(message) if (message and not tool) else {"tool": None, "error": ""}
    tool = tool or planned.get("tool")
    if not tool:
        if planned.get("error"):
            return {"state": "answered", "reply": f"Trợ lý đang không gọi được mô hình ({planned['error'][:120]}),"
                                                  " nên chưa đọc được yêu cầu của bạn."}
        return {"state": "answered", "reply": "Tôi chưa hiểu yêu cầu. " + HELP}
    spec = TOOLS[tool]
    arguments = args or planned.get("args") or {}
    if isinstance(arguments, str):
        arguments = json.loads(arguments or "{}")
    # a model fills an optional field with "" as readily as with null; the domain must not read that as another person
    arguments = {key: value for key, value in arguments.items() if value not in ("", None)}
    blocked = _guard(tool, arguments, requester)
    if blocked:
        return {"state": "refused", "tool": tool, "reply": blocked}
    if spec["risk"] == FORBIDDEN:
        return {"state": "refused", "tool": tool,
                "reply": f"{spec['title']}: {spec['description']}"}
    if tool in SELF_TOOLS:
        # a model that copies the login into `employee` must not turn a request about myself into one about someone else
        arguments["employee"] = employee_of(requester)
    key = case or f"{requester.split('@')[0]}-{_fingerprint(tool, arguments)}-{getdate().isoformat()}"
    existing = frappe.db.get_value("TLC AI Case", {"case_key": key})
    if existing:
        doc = frappe.get_doc("TLC AI Case", existing)
        if spec["risk"] == READ:
            # A read changes nothing, so asking it twice must answer twice: handing back "the earlier request is in
            # state ..." turns every repeated question about one's own code or balance into a non-answer.
            return _run(doc, spec)
        if spec["risk"] == DRAFT and doc.state == STATE_FAILED:
            # a draft that was never built leaves nothing behind; refusing to try again only hides the reason
            return _run(doc, spec)
        # the same request already ran: hand back the record it produced, so a follow-up tool call can continue from it
        return {"state": doc.state, "case": doc.name, "reply": f"Yêu cầu trước đó đang ở trạng thái {doc.state} (case {doc.name}).",
                "document_type": doc.document_type or "", "document_id": doc.document_id or ""}
    record = frappe.get_doc({"doctype": "TLC AI Case", "case_key": key, "tool": tool, "tool_title": spec["title"],
                             "risk_class": spec["risk"], "requester": requester, "arguments": json.dumps(arguments, default=str),
                             "message": (message or "")[:2000], "fingerprint": _fingerprint(tool, arguments),
                             "state": STATE_PROPOSED}).insert(ignore_permissions=True)
    if spec["risk"] in (READ, DRAFT):
        return _run(record, spec)
    record.db_set({"state": STATE_WAITING, "approver_roles": "TLC HR Lead,TLC Director,System Manager"})
    frappe.get_doc({"doctype": "TLC AI Case Event", "parent": record.name, "parentfield": "events",
                    "parenttype": "TLC AI Case", "actor": requester, "detail": "Tạo case chờ người duyệt"}).insert(ignore_permissions=True)
    _assign_approvers(record)
    frappe.db.commit()
    return {"state": STATE_WAITING, "case": record.name,
            "reply": (f"Tôi đã ghi yêu cầu '{spec['title']}' vào case {record.name} và **chưa thực hiện**."
                      f" Người duyệt (TLC HR Lead / Giám đốc) mở Desk → AI Case → bấm Phê duyệt và thực hiện.")}


def _assign_approvers(record):
    """The case appears as work in the approver's Desk queue, with the requester's arguments frozen in it."""
    users = sorted({row.parent for row in frappe.get_all(
        "Has Role", filters={"role": ["in", list(_approver_roles())], "parenttype": "User"},
        fields=["parent"], limit=200)
        if row.parent != record.requester and frappe.db.get_value("User", row.parent, "enabled")})
    for user in users[:10]:
        frappe.get_doc({"doctype": "ToDo", "allocated_to": user, "status": "Open", "priority": "Medium",
                        "date": getdate().isoformat(), "reference_type": "TLC AI Case", "reference_name": record.name,
                        "description": f"@Leo đề xuất '{record.tool_title}' của {record.requester} — duyệt hoặc từ chối trong Desk."}).insert(ignore_permissions=True)


def _approver_roles():
    return {"TLC HR Lead", "TLC Director", "System Manager"}


def _run(record, spec):
    """Execute a planned action and write the result into the case. Deterministic wording, never model-authored."""
    try:
        result = SERVICES[record.tool](record)
    except Exception as exc:
        record.db_set({"state": STATE_FAILED, "result": str(exc)[:2000]})
        frappe.db.commit()
        return {"state": STATE_FAILED, "case": record.name, "reply": f"Không thực hiện được: {str(exc)[:300]}"}
    document = result.get("document_id") if isinstance(result, dict) else None
    if isinstance(document, dict):  # a service may hand back the desk payload of the record it created
        document = document.get("document_id") or document.get("name")
        result = {**result, "document_id": document, "document_type": result.get("document_type") or result.get("doctype")}
    record.db_set({"state": STATE_DONE, "result": json.dumps(result, ensure_ascii=False, default=str)[:4000],
                   "document_type": (result.get("document_type") or result.get("doctype") or ""), "document_id": document or "",
                   "executed_on": now_datetime(), "executed_by": frappe.session.user})
    frappe.get_doc({"doctype": "TLC AI Case Event", "parent": record.name, "parentfield": "events",
                    "parenttype": "TLC AI Case", "actor": frappe.session.user,
                    "detail": result.get("note") or "Đã thực hiện"}).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"state": STATE_DONE, "case": record.name, "reply": result.get("reply", "Xong."), **result}


# ------------------------------------------------------------------------------------------------------ services

def _my_records(record):
    profile = frappe.call("tlc_hr.interface.assistant.query", topic="profile") or {}
    leaves = frappe.call("tlc_hr.interface.assistant.query", topic="leave") or {}
    person = (profile.get("records") or [{}])[0]
    code = person.get("name") or profile.get("employee") or "chưa có mã"
    waiting = [row for row in (leaves.get("records") or []) if not row.get("docstatus")]
    reply = (f"Mã nhân viên của bạn là {code}"
             + (f" — {person.get('employee_name')}, {person.get('department') or 'chưa có phòng ban'}."
                if person.get("employee_name") else "."))
    reply += (f" Đang có {len(waiting)} đơn phép nháp hoặc chờ duyệt."
              if waiting else " Không có đơn phép nào đang chờ.")
    return {"document_type": "Employee", "document_id": profile.get("employee"), "reply": reply,
            "profile": profile, "leave": leaves}


def _my_to_decide(record):
    rows = frappe.get_all("Leave Application", filters={"leave_approver": record.requester, "docstatus": 0,
                                                        "workflow_state": ["in", ["Chờ quản lý duyệt", "Chờ nhân sự duyệt"]]},
                          fields=["name", "employee_name", "workflow_state", "from_date"], limit=20)
    return {"document_type": "Leave Application", "document_id": rows[0]["name"] if rows else "",
            "reply": ("Cần bạn duyệt: " + "; ".join(f"{r['name']} ({r['employee_name']}, {r['workflow_state']})" for r in rows))
                     if rows else "Không có hồ sơ nào chờ bạn duyệt.", "rows": rows}


def _policy_search(record):
    question = (record.message or "").lower()
    rows = frappe.get_all("TLC AI Policy", filters={"state": "Đã duyệt"}, fields=["policy_code", "title", "content"])
    hits = [r for r in rows if any(word in (r.title or "").lower() or word in (r.content or "").lower()
                                   for word in re.findall(r"[\wàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵ]{3,}", question))]
    if not hits:
        return {"reply": "Không có chính sách đã duyệt nào khớp câu hỏi; tôi không tự đặt ra quy định.", "sources": []}
    return {"reply": "; ".join(f"{h.title} ({h.policy_code})" for h in hits[:3]),
            "sources": [{"code": h.policy_code, "title": h.title} for h in hits[:3]]}


def _draft_leave(record):
    args = json.loads(record.arguments or "{}")
    created = frappe.call("tlc_hr.interface.assistant.draft_leave", **args)
    # the assistant service answers with the desk payload of the new draft; the case stores only its name
    name = created.get("document_id") if isinstance(created, dict) else created
    used = frappe.db.get_value("Leave Application", name, "leave_type") or args.get("leave_type") or "nghỉ phép"
    return {"document_type": "Leave Application", "document_id": name,
            "reply": (f"Đã tạo NHÁP đơn {used} {name}."
                      " Chưa gửi duyệt — bạn kiểm tra rồi bấm Gửi trên form.")}


def _draft_by_doctype(record, doctype, builder):
    args = json.loads(record.arguments or "{}")
    doc = frappe.get_doc({"doctype": doctype, **builder(args, record)})
    doc.insert(ignore_permissions=True)
    return {"document_type": doctype, "document_id": doc.name,
            "reply": f"Đã tạo NHÁP {doctype} {doc.name}. Chưa gửi duyệt."}


def _draft_travel(record):
    def build(args, rec):
        return {"employee": employee_of(rec.requester), "company": "TLC Demo", "travel_type": "Domestic",
                "purpose_of_travel": args.get("purpose") or "Công tác", "tlc_destination": args.get("destination") or "",
                "description": args.get("reason") or "Đề nghị do @Leo soạn từ chat",
                "tlc_from_date": args.get("from_date"), "tlc_to_date": args.get("to_date") or args.get("from_date"),
                "tlc_funded": 0}
    return _draft_by_doctype(record, "Travel Request", build)


def _draft_attendance_correction(record):
    def build(args, rec):
        return {"employee": employee_of(rec.requester), "company": "TLC Demo", "employee_name": rec.requester,
                "from_date": args.get("from_date"), "to_date": args.get("to_date") or args.get("from_date"),
                "explanation": args.get("reason") or "Quên chấm công — @Leo soạn nháp từ chat",
                "attendance_type": "Absent"}
    return _draft_by_doctype(record, "Attendance Request", build)


def _draft_overtime(record):
    def build(args, rec):
        return {"employee": employee_of(rec.requester), "ot_date": args.get("from_date"),
                "from_time": args.get("from_time") or "17:30:00", "to_time": args.get("to_time") or "20:30:00",
                "reason": args.get("reason") or "Đề nghị tăng ca do @Leo soạn nháp"}
    return _draft_by_doctype(record, "TLC Overtime Request", build)


def _screen_cv(record):
    args = json.loads(record.arguments or "{}")
    applicant = args.get("applicant")
    if not applicant:
        raise frappe.ValidationError("Cần mã hồ sơ ứng viên (applicant).")
    out = frappe.call("tlc_hr.interface.recruitment_pipeline.screen", name=applicant)
    return {"document_type": "Job Applicant", "document_id": applicant,
            "reply": f"AI chấm {applicant}: {out['score']}/100 ({out['verdict']}) → {out['step']}. Người vẫn quyết định bước sau."}


def _submit_leave(record):
    """Send the requester's own draft through the same workflow a person uses, with the approver's case as the consent."""
    from frappe.model.workflow import apply_workflow, get_transitions

    args = json.loads(record.arguments or "{}")
    name = args.get("name") or record.document_id
    if not name:  # the person said "send the draft I just made" without naming it
        drafts = frappe.get_all("Leave Application", filters={"employee": employee_of(record.requester), "docstatus": 0},
                                pluck="name", order_by="creation desc", limit=1)
        name = drafts[0] if drafts else None
    if not name:
        raise frappe.ValidationError("Chưa có đơn nháp nào của bạn để gửi duyệt.")
    doc = frappe.get_doc("Leave Application", name)
    if doc.docstatus != 0 or doc.employee != employee_of(record.requester):
        raise frappe.PermissionError("Chỉ gửi đơn phép nháp của chính mình.")
    actor = frappe.session.user
    try:
        frappe.set_user(record.requester)
        actions = [row.action for row in get_transitions(doc)]
        action = next((item for item in actions if item == "Gửi duyệt"), actions[0] if actions else None)
        if not action:
            raise frappe.ValidationError(f"Đơn {name} không còn bước gửi duyệt ({', '.join(actions) or 'không có hành động'}).")
        apply_workflow(frappe.get_doc("Leave Application", name), action)
    finally:
        frappe.set_user(actor)
    doc.reload()
    return {"document_type": "Leave Application", "document_id": name,
            "reply": f"Đã gửi duyệt đơn {name} (trạng thái {doc.get('workflow_state') or 'đã gửi'})."}


LINKABLE = (
    ("Leave Application", re.compile(r"HR-LAP-\d{4}-\d+", re.I)),
    ("Travel Request", re.compile(r"HR-TRQ-\d{4}-\d+", re.I)),
    ("TLC Overtime Request", re.compile(r"TLC-OT-\d{4}-\d+", re.I)),
)


def _document_link(record):
    """A link to a record the person already owns, taken from the code they typed rather than from the model."""
    mine = employee_of(record.requester)
    for doctype, pattern in LINKABLE:
        found = pattern.search(record.message or "")
        if not found:
            continue
        name = found.group(0).upper()
        if not frappe.db.exists(doctype, name):
            return {"reply": f"Không tìm thấy hồ sơ {name} trong hệ thống."}
        if frappe.db.get_value(doctype, name, "employee") != mine:
            return {"reply": f"Hồ sơ {name} không thuộc về bạn, nên tôi không mở được."}
        url = get_url(f"/desk/{frappe.scrub(doctype).replace('_', '-')}/{name}")
        return {"document_type": doctype, "document_id": name, "reply": f"Đây là đường dẫn mở {name}: {url}"}
    return {"reply": "Bạn gửi giúp tôi mã hồ sơ (ví dụ HR-LAP-2026-00370) để tôi đưa đúng đường dẫn mở hồ sơ đó."}


SERVICES = {"hrm.my_records": _my_records, "hrm.my_to_decide": _my_to_decide, "hrm.policy_search": _policy_search,
            "hrm.document_link": _document_link,
            "hrm.draft_leave": _draft_leave, "hrm.draft_travel": _draft_travel,
            "hrm.draft_attendance_correction": _draft_attendance_correction, "hrm.draft_overtime": _draft_overtime,
            "hrm.screen_cv": _screen_cv, "hrm.submit_leave": _submit_leave}


# ------------------------------------------------------------------------------------------------ human decision

@frappe.whitelist(methods=["POST"])
def decide(case, action, reason=""):
    """A second person releases (or refuses) a waiting case; the requester cannot approve their own."""
    doc = frappe.get_doc("TLC AI Case", case)
    doc.check_permission("read")
    if doc.state != STATE_WAITING:
        frappe.throw(f"Case {case} đang ở trạng thái {doc.state}, không còn chờ duyệt.")
    if doc.requester == frappe.session.user:
        frappe.throw("Người đề xuất không tự duyệt case của mình.", frappe.PermissionError)
    roles = set(frappe.get_roles())
    needed = {r.strip() for r in (doc.approver_roles or "").split(",") if r.strip()}
    if not (roles & needed):
        frappe.throw("Bạn không thuộc nhóm được duyệt loại yêu cầu này.", frappe.PermissionError)
    for todo in frappe.get_all("ToDo", filters={"reference_type": "TLC AI Case", "reference_name": doc.name, "status": "Open"},
                               pluck="name"):
        frappe.db.set_value("ToDo", todo, {"status": "Closed", "allocated_to": frappe.session.user}, update_modified=False)
    if action != "approve":
        if not reason:
            frappe.throw("Từ chối phải có lý do.")
        doc.db_set({"state": STATE_REFUSED, "decision_by": frappe.session.user, "decision_on": now_datetime(),
                    "decision_reason": reason[:2000]})
    else:
        doc.db_set({"decision_by": frappe.session.user, "decision_on": now_datetime(),
                    "decision_reason": (reason or "Duyệt trong Desk")[:2000]})
        return _run(doc, TOOLS[doc.tool])
    frappe.db.commit()
    doc.reload()
    return {"state": doc.state, "case": doc.name}


def provision():
    """Register the gateway as Raven AI functions and seed the agent/tools/policy records."""
    if frappe.session.user != "Administrator":
        frappe.throw("Chỉ operator dựng được trợ lý.", frappe.PermissionError)
    if not frappe.db.exists("TLC AI Agent", "leo"):
        frappe.get_doc({"doctype": "TLC AI Agent", "agent_code": "leo", "agent_name": "@Leo (HR)", "is_front": 1,
                        "model": llm.describe(), "enabled": 1, "persona": PERSONA}).insert(ignore_permissions=True)
    for code, spec in TOOLS.items():
        row = frappe.get_doc("TLC AI Tool", code) if frappe.db.exists("TLC AI Tool", code) else frappe.new_doc("TLC AI Tool")
        row.update({"tool_code": code, "title": spec["title"], "risk_class": spec["risk"], "enabled": 1,
                    "description": spec["description"], "agent": "leo",
                    "contract": json.dumps(spec["contract"].model_json_schema()) if spec["contract"] else ""})
        row.save(ignore_permissions=True)
    function = "tlc_hr_agent"
    data = {"function_name": function, "type": "Custom Function", "function_path": "tlc_hr.interface.agent_gateway.act",
            "description": ("Run an HR workflow request for the person who is speaking: read their own records and "
                            "approval queue, search approved policy, draft leave/travel/attendance/overtime, or open a "
                            "case for a controlled action. Never approves or pays anything."),
            "requires_write_permissions": 1, "pass_parameters_as_json": 0, "strict": 0,
            "params": json.dumps({"type": "object", "properties": {"message": {"type": "string",
                          "description": "Nguyên văn yêu cầu của người dùng"}}, "required": ["message"],
                          "additionalProperties": False})}
    doc = frappe.get_doc("Raven AI Function", function) if frappe.db.exists("Raven AI Function", function) else frappe.new_doc("Raven AI Function")
    doc.update(data)
    doc.save(ignore_permissions=True)
    bot = frappe.get_doc("Raven Bot", "TLC Demo HR Assistant") if frappe.db.exists("Raven Bot", "TLC Demo HR Assistant") else None
    if bot and not any(row.function == function for row in bot.bot_functions):
        bot.append("bot_functions", {"function": function})
        bot.save(ignore_permissions=True)
    if not frappe.db.exists("TLC AI Policy", "TLC-AI-0001"):
        frappe.get_doc({"doctype": "TLC AI Policy", "policy_code": "TLC-AI-0001",
                        "title": "Phạm vi hành động của trợ lý HR", "state": "Đã duyệt", "effective_from": "2026-01-01",
                        "content": ("Trợ lý chỉ tạo bản nháp và đọc dữ liệu của chính người hỏi. Gửi duyệt, phê duyệt, "
                                    "tính lương, thanh toán, đổi quyền, sửa/xóa hồ sơ đã ghi sổ luôn do người thực hiện "
                                    "trên form theo workflow. Người duyệt case phải khác người đề xuất.")}).insert(ignore_permissions=True)
    frappe.db.commit()
    return {"agent": "leo", "tools": len(TOOLS)}
