"""Sàng lọc CV có hình, nhật ký AI từng bước và thư từ theo mẫu cho pipeline tuyển dụng 6 bước.

Ba việc của module này, đều đọc được trên chính hồ sơ ứng viên:

1. Trích hồ sơ thành dữ liệu có cấu trúc (thông tin cá nhân, quá trình làm việc, học vấn, kỹ năng, ngoại ngữ).
2. Đối chiếu với JD thành bản đồ tiêu chí có trọng số kèm bằng chứng, rồi vẽ thành điểm, cột tiêu chí và biểu đồ
   radar. Điểm tính từ trọng số và mức đạt của từng tiêu chí chứ không để mô hình tự tuyên bố, nên biểu đồ và điểm
   luôn khớp nhau và người duyệt đọc được vì sao ra con số đó.
3. Ghi một dòng TLC AI Trace Log cho từng hành động (thư nhận, AI xếp hàng/chấm xong, người quyết định, thư đã gửi)
   và soạn thư từ Email Template có đoạn nội dung do AI viết, để HR chỉ cần kiểm tra rồi bấm Gửi.
"""

import json
import math
import re
from time import perf_counter

import frappe
from frappe.utils import cint, cstr, flt, format_datetime, get_url, now_datetime, strip_html


def html_escape(value):
    """Every piece of text the panel shows comes from a CV or the assistant, so it is escaped here."""
    return cstr(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


TRACE = "TLC AI Trace Log"
GROUPS = ("Chuyên môn", "Kinh nghiệm", "Kỹ năng", "Ngoại ngữ", "Học vấn", "Thái độ")
RATINGS = {"Đạt": 1.0, "Một phần": 0.5, "Thiếu": 0.0}
ACCENT = {"Đạt": "#16a34a", "Một phần": "#f59e0b", "Thiếu": "#ef4444"}


def model_name():
    """Name the provider that answered, so a ledger written under a stronger model never credits the old one."""
    from tlc_hr.interface import llm

    return llm.describe()
EMAIL_KINDS = {
    "invitation": {"template": "TLC Thư mời phỏng vấn", "label": "Thư mời phỏng vấn", "title": "Soạn thư mời phỏng vấn",
                   "hint": "Nêu lịch hẹn, người phỏng vấn và điều ứng viên nên chuẩn bị."},
    "confirmation": {"template": "TLC Xác nhận lịch phỏng vấn", "label": "Thư xác nhận lịch hẹn", "title": "Soạn thư xác nhận lịch hẹn",
                     "hint": "Xác nhận lại lịch hẹn và cách liên hệ khi cần đổi lịch."},
    "result": {"template": "TLC Thông báo kết quả phỏng vấn", "label": "Thông báo kết quả", "title": "Soạn thư thông báo kết quả",
               "hint": "Thông báo kết quả vòng phỏng vấn đã có và bước tiếp theo."},
    "offer": {"template": "TLC Thư mời nhận việc", "label": "Thư mời nhận việc", "title": "Soạn thư mời nhận việc",
              "hint": "Đây là thư mời nhận việc: xác nhận mức lương và ngày vào làm; không còn vòng phỏng vấn nào."},
    "rejection": {"template": "TLC Thư cảm ơn và giữ liên lạc", "label": "Thư cảm ơn", "title": "Soạn thư cảm ơn",
                  "hint": "Trân trọng cảm ơn, nêu lý do chưa phù hợp và giữ liên lạc cho cơ hội sau."},
}

PROFILE_SYSTEM = (
    "Bạn trích xuất thông tin từ CV tiếng Việt. Chỉ dùng dữ liệu có trong CV, không suy diễn, không bịa; để trống "
    "nếu CV không nêu. Trả về JSON đúng các khóa: full_name, email, phone, location, birth_date (YYYY-MM-DD hoặc "
    "rỗng), years_experience (số), current_role, current_company, expected_salary, availability, education (mảng "
    "{school, major, degree, year}), work (mảng {company, role, period, highlight}, mới nhất trước), skills (mảng "
    "chuỗi), languages (mảng {name, level}), certifications (mảng chuỗi)."
)
CRITERIA_SYSTEM = (
    f"Bạn đối chiếu CV với mô tả công việc. Rút 5-8 tiêu chí từ mô tả công việc; mỗi tiêu chí gồm name (ngắn), "
    f"group (một trong: {', '.join(GROUPS)}), weight (1-5, 5 là quan trọng nhất), must (1 nếu bắt buộc, ngược lại 0), "
    "rating (Đạt | Một phần | Thiếu), evidence (dẫn chứng từ CV, để trống nếu CV không có), note (một câu tiếng Việt). "
    "Ngoài ra trả summary (2-3 câu tiếng Việt), risks (mảng 2-4 điểm cần hỏi lại), questions (mảng 3-5 câu hỏi phỏng vấn). "
    'Trả về JSON đúng cấu hình {"criteria": [...], "summary": "...", "risks": [...], "questions": [...]}.'
)
NOTE_SYSTEM = (
    "Bạn viết thư tuyển dụng cho bộ phận nhân sự. Giản dị, lịch sự, đúng tiếng Việt. Chỉ dùng đúng thông tin được cho: "
    "không tự thêm số điện thoại, email, địa chỉ hay tên người nào không có trong dữ kiện. "
    'Trả về JSON đúng {"lines": [...]} với 2-4 câu, mỗi câu một phần tử.'
)
INTERVIEW_SYSTEM = (
    "Bạn tổng hợp biên bản phỏng vấn theo từng tiêu chí đã chấm, chỉ kết luận trong phạm vi biên bản, không bịa. "
    'Trả về JSON đúng {"verdict": "Pass|Fail|Hold", "per_criteria": [{"name": "...", "read": "..."}], '
    '"summary": "2-3 câu", "risks": ["..."]}.'
)
OFFER_SYSTEM = (
    "Bạn đề xuất gói mời nhận việc dựa trên kinh nghiệm, mức lương khảo sát và mặt bằng nội bộ, bằng tiếng Việt. "
    'Trả về JSON đúng {"low": số, "high": số, "text": "2-3 câu nêu căn cứ và rủi ro"}. '
    "Chỉ nêu khoảng lương trong phạm vi dữ kiện đã cho."
)


# ------------------------------------------------------------------------------------------------------------- llm

def _client():
    """The provider layer: the strong keyless gateway, with the demo's Mistral key as its fallback."""
    from tlc_hr.interface import llm

    return llm


def _first_json(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        match = re.search(r"\{.*\}", text or "", re.S)
        try:
            return json.loads(match.group(0)) if match else None
        except (ValueError, TypeError):
            return None


def chat_json(system, user, keys, max_tokens=1400):
    """One JSON answer through the provider layer; prose is asked again as an object."""
    from tlc_hr.interface import llm

    return llm.chat_json(system, user, keys, max_tokens=max_tokens)


# ------------------------------------------------------------------------------------------------------------ ledger

def trace(candidate, event, detail="", actor=None, model="", duration_ms=None, step=None, message_id="", status="done",
          created_on=None):
    """Append one line to the hiring story: who did what to this candidate, when, with which model."""
    step = step or frappe.db.get_value("Job Applicant", candidate, "tlc_step")
    frappe.get_doc({"doctype": TRACE, "candidate": candidate, "step": step, "event": event,
                    "actor": actor or (frappe.session.user if frappe.session else "Administrator"),
                    "detail": (detail or "")[:8000], "model": model, "duration_ms": cint(duration_ms or 0),
                    "message_id": message_id, "status": status, "created_on": created_on or now_datetime(),
                    }).insert(ignore_permissions=True)


def ledger(candidate, limit=80):
    return frappe.get_all(TRACE, filters={"candidate": candidate},
                          fields=["event", "actor", "detail", "model", "duration_ms", "created_on", "step", "status"],
                          order_by="creation asc", limit_page_length=limit)


def seen(message_id):
    """Intake dedupe: a Mailpit message is turned into a file once."""
    return bool(message_id) and frappe.db.exists(TRACE, {"event": "email.received", "message_id": message_id})


# ----------------------------------------------------------------------------------------------------- extraction

def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _as_list(value, key=None):
    if isinstance(value, dict):
        value = value.get(key) or []
    if isinstance(value, str):
        value = [part for part in re.split(r"[;,\n]", value) if part.strip()]
    return [item for item in (value or []) if _clean(item) or isinstance(item, dict)]


def _row(item, keys):
    if not isinstance(item, dict):
        return {keys[0]: _clean(item), **{key: "" for key in keys[1:]}}
    return {key: _clean(item.get(key)) for key in keys}


def extract_profile(doc, cv):
    """Structured portrait of the candidate: personal block, work timeline, education, skills, languages."""
    started = perf_counter()
    try:
        raw = chat_json(PROFILE_SYSTEM, f"CV cần trích xuất:\n{(cv or '')[:9000]}", ["full_name", "work", "skills"], max_tokens=1200)
        profile = {
            "full_name": _clean(raw.get("full_name")) or doc.applicant_name,
            "email": _clean(raw.get("email")) or doc.email_id,
            "phone": _clean(raw.get("phone")) or doc.phone_number,
            "location": _clean(raw.get("location")),
            "birth_date": _clean(raw.get("birth_date")) or _clean(doc.tlc_birth_date),
            "years_experience": flt(raw.get("years_experience")),
            "current_role": _clean(raw.get("current_role")),
            "current_company": _clean(raw.get("current_company")),
            "expected_salary": _clean(raw.get("expected_salary")),
            "availability": _clean(raw.get("availability")),
            "education": [_row(item, ("school", "major", "degree", "year")) for item in _as_list(raw.get("education"))][:5],
            "work": [_row(item, ("company", "role", "period", "highlight")) for item in _as_list(raw.get("work"))][:6],
            "skills": [_clean(skill) for skill in _as_list(raw.get("skills"))][:16],
            "languages": [_row(item, ("name", "level")) for item in _as_list(raw.get("languages"))][:6],
            "certifications": [_clean(item) for item in _as_list(raw.get("certifications"))][:8],
            "source": "ai",
        }
    except Exception:
        profile = heuristic_profile(doc, cv)
    profile["years_experience"] = max(0, min(60, flt(profile.get("years_experience"))))
    if not profile["education"] and doc.get("tlc_education"):
        profile["education"] = [_row({"school": _clean(doc.tlc_education)[:160]}, ("school", "major", "degree", "year"))]
    if not profile["work"] and doc.get("tlc_experience"):
        profile["work"] = [_row({"highlight": _clean(doc.tlc_experience)[:200]}, ("company", "role", "period", "highlight"))]
    return {"profile": profile, "duration_ms": int((perf_counter() - started) * 1000)}


def heuristic_profile(doc, cv):
    """Deterministic reading of the CV when the assistant is unreachable: still enough for HR to screen on."""
    cv = cv or ""
    phone = re.search(r"(?:\+84|84|0)\d{9}", re.sub(r"[ .-]", "", cv))
    years = re.search(r"(\d{1,2})\s*\+?\s*(?:n\u0103m kinh nghi\u1ec7m|years? of experience)", cv, re.I)
    skills = [word for word in ("Excel", "SAP", "Odoo", "Python", "SQL", "Power BI", "Photoshop", "Outlook",
                                "Google Analytics", "SAP B1") if re.search(rf"\b{re.escape(word)}\b", cv, re.I)]
    return {
        "full_name": doc.applicant_name, "email": doc.email_id,
        "phone": (phone.group(0) if phone else _clean(doc.phone_number)), "location": "",
        "birth_date": _clean(doc.tlc_birth_date), "years_experience": flt(years.group(1)) if years else 0,
        "current_role": _clean(doc.designation), "current_company": "",
        "expected_salary": _expected_salary(doc), "availability": "",
        "education": [_row({"school": _clean(doc.tlc_education)[:160]}, ("school", "major", "degree", "year"))]
        if doc.get("tlc_education") else [],
        "work": [_row({"highlight": _clean(doc.tlc_experience)[:200]}, ("company", "role", "period", "highlight"))]
        if doc.get("tlc_experience") else [],
        "skills": skills, "languages": [_row({"name": "Tiếng Việt", "level": "Bản ngữ"}, ("name", "level"))],
        "certifications": [], "source": "heuristic",
    }


def _expected_salary(doc):
    if doc.lower_range or doc.upper_range:
        low, high = flt(doc.lower_range), flt(doc.upper_range) or flt(doc.lower_range)
        return f"{low:,.0f} – {high:,.0f} {doc.currency or 'VND'}"
    return ""


def jd_text(doc):
    parts = []
    if doc.job_title:
        opening = frappe.db.get_value("Job Opening", doc.job_title, ["description", "designation", "department"], as_dict=True)
        if opening:
            parts.append(strip_html(opening.description or ""))
            for label, value in (("Chức danh", opening.designation), ("Bộ phận", opening.department)):
                if value:
                    parts.append(f"{label}: {value}")
    for field in ("tlc_education", "tlc_experience"):
        if doc.get(field):
            parts.append(str(doc.get(field)))
    return "\n".join(parts)[:8000]


def match_criteria(doc, cv):
    """Weighted map of the job description against the CV, every criterion carrying its evidence."""
    started = perf_counter()
    jd = jd_text(doc)
    brief = f"MÔ TẢ CÔNG VIỆC:\n{jd or '(chưa có mô tả công việc)'}\n\nHỒ SƠ:\n{(cv or '')[:7000]}"
    try:
        raw = chat_json(CRITERIA_SYSTEM, brief, ["criteria", "summary"])
        criteria = [_criterion(item) for item in _as_list(raw.get("criteria")) if isinstance(item, (dict, str))][:10]
        criteria = [c for c in criteria if c["name"]]
        if not criteria:
            raise frappe.ValidationError("empty criteria")
        summary, risks, questions = _clean(raw.get("summary")), _as_list(raw.get("risks")), _as_list(raw.get("questions"))
    except Exception:
        criteria = fallback_criteria(jd, cv)
        summary, risks, questions = "", ["Trợ lý không đối chiếu được; HR tự cho điểm và ghi lý do."], []
    if not criteria:
        frappe.throw("Mô tả công việc chưa đủ để rút tiêu chí; bổ sung mô tả công việc cho vị trí rồi chấm lại.")
    score, missing = weighted_score(criteria)
    return {"criteria": criteria, "summary": summary, "risks": risks[:6], "questions": questions[:6],
            "score": score, "missing": missing, "duration_ms": int((perf_counter() - started) * 1000)}


def _criterion(item):
    item = item if isinstance(item, dict) else {"name": _clean(item)}
    rating = item.get("rating")
    return {"name": _clean(item.get("name"))[:160],
            "group": item.get("group") if item.get("group") in GROUPS else "Chuyên môn",
            "weight": min(5, max(1, cint(item.get("weight") or 3))), "must": 1 if cint(item.get("must")) else 0,
            "rating": rating if rating in RATINGS else "Một phần",
            "evidence": _clean(item.get("evidence"))[:300], "note": _clean(item.get("note"))[:240]}


def fallback_criteria(jd, cv):
    """Keyword map straight out of the job description: keeps the chart honest when the assistant is down."""
    wanted = [("Kinh nghiệm theo yêu cầu", "Kinh nghiệm", 5, 1,
               re.search(r"(\d)\s*\+?\s*n\u0103m", jd or "", re.I))]
    for pattern, label, group in ((r"excel|tin h\u1ecdc", "Tin học văn phòng / Excel", "Kỹ năng"),
                                  (r"\bsap\b|erp|odoo", "ERP (SAP / Odoo)", "Kỹ năng"),
                                  (r"python|sql|power bi|powerbi", "Phân tích dữ liệu", "Chuyên môn"),
                                  (r"ti\u1ebfng anh|english|toeic", "Ngoại ngữ", "Ngoại ngữ"),
                                  (r"\u0111\u1ea1i h\u1ecdc|c\u1eed nh\u00e2n|b\u1e51ng", "Học vấn phù hợp", "Học vấn"),
                                  (r"\u0111\u1ed9i nh\u00f3m|giao ti\u1ebfp|communica", "Kỹ năng làm việc nhóm", "Thái độ")):
        if re.search(pattern, jd or "", re.I):
            wanted.append((label, group, 3, 0, pattern))
    criteria = []
    for label, group, weight, must, detector in wanted:
        needle = detector.group(0) if hasattr(detector, "group") else None
        hit = bool(re.search(needle or detector, cv or "", re.I)) if (needle or detector) else False
        criteria.append({"name": label, "group": group, "weight": weight, "must": must,
                         "rating": "Đạt" if hit else "Thiếu", "evidence": "Đọc được từ hồ sơ" if hit else "",
                         "note": "Đối chiếu tự động theo từ khóa mô tả công việc"})
    return criteria[:8]


def weighted_score(criteria):
    total = sum(c["weight"] for c in criteria) or 1
    score = flt(sum(c["weight"] * RATINGS[c["rating"]] for c in criteria) / total * 100, 1)
    return min(100, max(0, score)), [c["name"] for c in criteria if c["must"] and c["rating"] != "Đạt"]


def verdict_of(score, missing):
    if missing and score < 60:
        return "Không đạt"
    if score >= 75 and not missing:
        return "Đạt"
    if score >= 55:
        return "Cân nhắc"
    return "Không đạt"


# ------------------------------------------------------------------------------------------------------ screening

def run_screen(doc, cv, actor=None):
    """Steps 1-2 of the pipeline: read the CV, map it to the JD, and leave a ledger line for each move."""
    trace(doc.name, "ai.screening.queued", f"Trợ lý nhận việc đối chiếu hồ sơ với mô tả công việc ({model_name()})",
          actor=actor or frappe.session.user, model=model_name(), step=doc.tlc_step, status="queued")
    frappe.db.commit()
    trace(doc.name, "ai.screening.running", "Trích thông tin cá nhân và quá trình làm việc từ CV", actor="AI",
          model=model_name(), step=doc.tlc_step, status="running")
    frappe.db.commit()
    extracted = extract_profile(doc, cv)
    trace(doc.name, "ai.profile.extracted", profile_brief(extracted["profile"]), actor="AI", model=model_name(),
          duration_ms=extracted["duration_ms"], step=doc.tlc_step)
    frappe.db.commit()
    match = match_criteria(doc, cv)
    trace(doc.name, "ai.criteria.matched", criteria_brief(match["criteria"], match["score"], match["missing"]),
          actor="AI", model=model_name(), duration_ms=match["duration_ms"], step=doc.tlc_step)
    frappe.db.commit()
    verdict = verdict_of(match["score"], match["missing"])
    summary = match["summary"] or doc.tlc_ai_summary
    payload = {"profile": extracted["profile"], "criteria": match["criteria"], "score": match["score"],
               "verdict": verdict, "summary": summary, "risks": match["risks"], "questions": match["questions"],
               "missing": match["missing"], "model": model_name(), "checked_on": format_datetime(now_datetime(), "dd/MM/yyyy HH:mm")}
    fields = {"tlc_ai_status": "Đã chấm", "tlc_ai_score": match["score"], "tlc_ai_verdict": verdict,
              "tlc_ai_summary": (summary or "")[:2000], "tlc_ai_risks": lines(match["risks"])[:2000],
              "tlc_ai_questions": lines(match["questions"])[:4000], "tlc_ai_model": model_name(),
              "tlc_ai_checked_on": now_datetime(), "tlc_cv_profile": json.dumps(payload["profile"], ensure_ascii=False),
              "tlc_jd_criteria": json.dumps(match["criteria"], ensure_ascii=False),
              "tlc_ai_match": match["score"], "tlc_ai_missing": lines(match["missing"], dash=False)[:2000]}
    return payload, fields


def lines(values, dash=True):
    items = [value if isinstance(value, str) else json.dumps(value, ensure_ascii=False) for value in (values or [])]
    return chr(10).join(f"{'- ' if dash else ''}{_clean(item)}" for item in items if _clean(item))


def profile_brief(profile):
    parts = [profile.get("full_name") or "(không đọc được họ tên)",
             f"{flt(profile.get('years_experience')):.0f} năm kinh nghiệm",
             f"{len(profile.get('skills') or [])} kỹ năng", f"{len(profile.get('work') or [])} vị trí đã làm"]
    if profile.get("expected_salary"):
        parts.append(f"mong muốn {profile['expected_salary']}")
    return ", ".join(parts) + f" — nguồn {profile.get('source')}"


def criteria_brief(criteria, score, missing):
    hits = sum(1 for c in criteria if c["rating"] == "Đạt")
    return (f"{len(criteria)} tiêu chí: {hits} đạt, {len(criteria) - hits} chưa đạt · điểm trọng số {score}/100"
            + (f" · còn thiếu bắt buộc: {', '.join(missing)}" if missing else " · đủ tiêu chí bắt buộc"))


# ---------------------------------------------------------------------------------------------------------- visuals

CSS = """
.tlc-ai{color:var(--text-color,#1f2937)}
.tlc-ai h5{font-size:12px;font-weight:700;margin:0 0 10px;letter-spacing:.4px;text-transform:uppercase;color:var(--gray-700,#374151)}
.tlc-ai__head{display:flex;gap:18px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
.tlc-ai__stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:10px;flex:1;min-width:230px}
.tlc-ai__stat{background:var(--bg-light-gray,#f8f9fa);border:1px solid var(--border-color,#e5e7eb);border-radius:8px;padding:8px 10px}
.tlc-ai__stat b{display:block;font-size:16px;line-height:1.2}
.tlc-ai__stat span{font-size:11px;color:var(--gray-600,#6b7280)}
.tlc-chip{display:inline-block;border-radius:999px;padding:1px 9px;font-size:11px;font-weight:600;border:1px solid}
.tlc-chip--ok{color:#166534;border-color:#86efac;background:#dcfce7}
.tlc-chip--part{color:#854d0e;border-color:#fcd34d;background:#fef3c7}
.tlc-chip--bad{color:#991b1b;border-color:#fca5a5;background:#fee2e2}
.tlc-chip--must{color:#3730a3;border-color:#a5b4fc;background:#e0e7ff}
.tlc-ai__grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:14px;margin-top:14px}
.tlc-ai__card{border:1px solid var(--border-color,#e5e7eb);border-radius:10px;padding:12px 14px}
.tlc-ai__kv{display:grid;grid-template-columns:118px 1fr;gap:3px 10px;font-size:12px;margin:0}
.tlc-ai__kv dt{color:var(--gray-600,#6b7280)}
.tlc-ai__kv dd{margin:0;font-weight:600}
.tlc-ai__tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.tlc-ai__tag{border:1px solid var(--border-color,#d1d5db);border-radius:6px;padding:1px 8px;font-size:11px}
.tlc-crit{margin-bottom:11px}
.tlc-crit__top{display:flex;gap:8px;align-items:center;font-size:12px;font-weight:600}
.tlc-crit__w{margin-left:auto;font-size:11px;color:var(--gray-600,#6b7280);font-weight:500}
.tlc-bar{height:7px;border-radius:5px;background:var(--border-color,#e5e7eb);margin:4px 0 2px;overflow:hidden}
.tlc-bar i{display:block;height:100%;border-radius:5px}
.tlc-crit__ev{font-size:11px;color:var(--gray-700,#4b5563)}
.tlc-ai__warn,.tlc-ai__note{border-left:3px solid #2563eb;background:var(--bg-light-blue,#eff6ff);padding:8px 10px;border-radius:0 6px 6px 0;font-size:12px;margin:10px 0}
.tlc-ai__warn{border-left-color:#ef4444;background:#fef2f2}
.tlc-ai__list{margin:4px 0 0;padding-left:18px;font-size:12px}
.tlc-ledger{list-style:none;margin:0;padding:0}
.tlc-ledger__item{display:flex;gap:10px;padding:7px 0;border-bottom:1px dashed var(--border-color,#e5e7eb);font-size:12px}
.tlc-ledger__dot{width:9px;height:9px;border-radius:50%;margin-top:4px;flex:0 0 auto;background:#9ca3af}
.tlc-ledger__item--ai .tlc-ledger__dot{background:#2563eb}
.tlc-ledger__item--run .tlc-ledger__dot{background:#f59e0b}
.tlc-ledger__item--bad .tlc-ledger__dot{background:#ef4444}
.tlc-ledger__item--human .tlc-ledger__dot{background:#16a34a}
.tlc-ledger__ev{font-weight:600;font-family:var(--monospace,monospace)}
.tlc-ledger__meta{color:var(--gray-600,#6b7280);font-size:11px}
.tlc-ledger__time{margin-left:auto;white-space:nowrap;color:var(--gray-600,#6b7280);font-size:11px}
"""

LEDGER_LABEL = {
    "email.received": ("Thư ứng tuyển", "human"), "candidate.created": ("Tạo hồ sơ", "human"),
    "ai.screening.queued": ("AI xếp hàng chấm CV", "run"), "ai.screening.running": ("AI đang chấm", "run"),
    "ai.profile.extracted": ("Trích hồ sơ", "ai"), "ai.criteria.matched": ("Đối chiếu tiêu chí", "ai"),
    "ai.screening.done": ("AI chấm xong", "ai"), "ai.screening.error": ("AI lỗi", "bad"),
    "email.drafted": ("Soạn thư theo mẫu", "human"), "email.sent": ("Đã gửi thư", "human"),
    "decision.invite": ("Quyết định mời phỏng vấn", "human"), "step.advanced": ("Chuyển bước", "human"),
    "interview.recorded": ("Ghi nhận phỏng vấn", "human"), "ai.interview.summarised": ("Tổng hợp phỏng vấn", "ai"),
    "offer.decided": ("Quyết định offer", "human"), "ai.offer.recommended": ("Khuyến nghị offer", "ai"),
    "pipeline.completed": ("Bàn giao onboarding", "human"), "candidate.rejected": ("Từ chối", "bad"),
    "candidate.talent_pool": ("Lưu talent pool", "human"),
}


def render_screening(payload):
    """The screening as a picture: score ring, radar of criteria groups, weighted bars, candidate portrait."""
    criteria = payload.get("criteria") or []
    score = flt(payload.get("score"))
    profile = payload.get("profile") or {}
    missing = payload.get("missing") or []
    achieved = sum(1 for c in criteria if c["rating"] == "Đạt")
    html = [f"<style>{CSS}</style>", "<div class='tlc-ai'>", "<div class='tlc-ai__head'>",
            _ring(score), _radar(_axes(criteria)), "<div class='tlc-ai__stats'>",
            _stat(f"{score:.0f}/100", "Điểm trọng số theo JD"), _stat(f"{achieved}/{len(criteria)}", "Tiêu chí đạt"),
            _stat(f"{len(missing)}", "Bắt buộc còn thiếu"),
            _stat(f"{flt(profile.get('years_experience')):.0f} năm", "Kinh nghiệm đọc từ CV"),
            _stat(f"{len(profile.get('skills') or [])}", "Kỹ năng trích được"), "</div></div>"]
    html.append(f"<div>Kết luận của trợ lý: {chip(payload.get('verdict'))} <span style='font-size:11px;color:var(--gray-600)'>"
                f"· {html_escape(payload.get('model') or '')} · {html_escape(payload.get('checked_on') or '')}</span></div>")
    if payload.get("summary"):
        html.append(f"<div class='tlc-ai__note'>{html_escape(payload['summary'])}</div>")
    if missing:
        html.append("<div class='tlc-ai__warn'><b>Thiếu tiêu chí bắt buộc:</b> " + html_escape(", ".join(missing))
                    + " — người duyệt vẫn phải ghi lý do nếu muốn mời phỏng vấn.</div>")
    html.append("<div class='tlc-ai__grid'><div class='tlc-ai__card'><h5>Bản đồ tiêu chí JD</h5>"
                + chr(10).join(_criterion_row(c) for c in criteria) + "</div>" + _portrait(profile, payload) + "</div></div>")
    return chr(10).join(html)


def _stat(value, label):
    return f"<div class='tlc-ai__stat'><b>{html_escape(value)}</b><span>{html_escape(label)}</span></div>"


def _ring(score):
    radius, circumference = 52, 2 * math.pi * 52
    dash = max(0.0, min(circumference, circumference * flt(score) / 100))
    color = "#16a34a" if score >= 75 else ("#f59e0b" if score >= 55 else "#ef4444")
    return (f"<svg viewBox='0 0 120 120' width='118' height='118' role='img' aria-label='Điểm CV {score}'>"
            f"<circle cx='60' cy='60' r='{radius}' fill='none' stroke='var(--border-color,#e5e7eb)' stroke-width='10'/>"
            f"<circle cx='60' cy='60' r='{radius}' fill='none' stroke='{color}' stroke-width='10' stroke-linecap='round' "
            f"stroke-dasharray='{dash:.1f} {circumference - dash:.1f}' transform='rotate(-90 60 60)'/>"
            f"<text x='60' y='57' text-anchor='middle' font-size='25' font-weight='700' fill='var(--text-color,#111827)'>{score:.0f}</text>"
            f"<text x='60' y='75' text-anchor='middle' font-size='9' fill='var(--gray-600,#6b7280)'>ĐIỂM CV / 100</text></svg>")


def _axes(criteria):
    axes = []
    for group in GROUPS:
        rows = [c for c in criteria if c["group"] == group]
        if rows:
            axes.append((group, sum(RATINGS[c["rating"]] for c in rows) / len(rows)))
    if len(axes) < 3:
        axes.append(("Mức khớp chung", sum(RATINGS[c["rating"]] for c in criteria) / max(1, len(criteria))))
    return axes[:6]


def _radar(axes):
    """A radar of the criteria groups: the shape is what a reviewer reads first."""
    count, centre, radius = max(3, len(axes)), 115, 78

    def point(index, value):
        angle = -math.pi / 2 + index * 2 * math.pi / count
        return centre + radius * value * math.cos(angle), centre + radius * value * math.sin(angle)

    rings = "".join(f"<polygon points='{' '.join(f'{x:.1f},{y:.1f}' for x, y in (point(i, ratio) for i in range(count)))}'"
                    f" fill='none' stroke='var(--border-color,#e5e7eb)'/>" for ratio in (0.34, 0.67, 1))
    spokes, labels = "", ""
    for index, (label, value) in enumerate(axes):
        x, y = point(index, 1)
        lx, ly = point(index, 1.3)
        spokes += f"<line x1='{centre}' y1='{centre}' x2='{x:.1f}' y2='{y:.1f}' stroke='var(--border-color,#e5e7eb)'/>"
        anchor = "start" if lx - centre > 12 else ("end" if centre - lx > 12 else "middle")
        labels += f"<text x='{lx:.1f}' y='{ly + 3:.1f}' text-anchor='{anchor}' font-size='9' fill='var(--gray-700,#4b5563)'>" \
                  f"{html_escape(label)} · {value * 100:.0f}%</text>"
    shape = [point(index, max(0.06, value)) for index, (_, value) in enumerate(axes)]
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in shape)
    dots = "".join(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='2.6' fill='#2563eb'/>" for x, y in shape)
    return (f"<svg viewBox='0 0 230 230' width='228' height='228' role='img' aria-label='Biểu đồ mức đạt theo nhóm tiêu chí'>"
            f"{rings}{spokes}<polygon points='{points}' fill='rgba(37,99,235,.18)' stroke='#2563eb' stroke-width='2'/>{dots}{labels}</svg>")


def chip(value):
    tone = {"Đạt": "ok", "Một phần": "part", "Thiếu": "bad", "Không đạt": "bad", "Cân nhắc": "part"}.get(value, "part")
    return f"<span class='tlc-chip tlc-chip--{tone}'>{html_escape(value or '—')}</span>"


def _criterion_row(criterion):
    value = RATINGS[criterion["rating"]] * 100
    must = "<span class='tlc-chip tlc-chip--must'>bắt buộc</span>" if criterion["must"] else ""
    evidence = f"<div class='tlc-crit__ev'>{html_escape(criterion['evidence'])}</div>" if criterion["evidence"] else ""
    return (f"<div class='tlc-crit'><div class='tlc-crit__top'><span>{html_escape(criterion['name'])}</span>{must}"
            f"{chip(criterion['rating'])}<span class='tlc-crit__w'>trọng số {criterion['weight']}</span></div>"
            f"<div class='tlc-bar'><i style='width:{value:.0f}%;background:{ACCENT[criterion['rating']]}'></i></div>{evidence}</div>")


def _work_row(item):
    cells = [f"<li><b>{html_escape(item.get('role') or 'Vị trí')}</b>"]
    if item.get("company"):
        cells.append(f" · {html_escape(item['company'])}")
    if item.get("period"):
        cells.append(f" <span style='color:var(--gray-600)'>{html_escape(item['period'])}</span>")
    if item.get("highlight"):
        cells.append(f"<br>{html_escape(item['highlight'])}")
    return cells[0] + "".join(cells[1:]) + "</li>"


def tag_row(tags):
    return f"<div class='tlc-ai__tags'>{tags}</div>" if tags else ""


def _portrait(profile, payload):
    rows = [("Họ tên", profile.get("full_name")), ("Email", profile.get("email")), ("Điện thoại", profile.get("phone")),
            ("Nơi ở", profile.get("location")), ("Ngày sinh", profile.get("birth_date")),
            ("Vị trí gần nhất", ", ".join(x for x in (profile.get("current_role"), profile.get("current_company")) if x)),
            ("Kinh nghiệm", f"{flt(profile.get('years_experience')):.1f} năm" if profile.get("years_experience") else ""),
            ("Mức mong muốn", profile.get("expected_salary")), ("Sẵn sàng từ", profile.get("availability"))]
    definition = "".join(f"<dt>{html_escape(label)}</dt><dd>{html_escape(value)}</dd>"
                        for label, value in rows if _clean(value))
    skills = "".join(f"<span class='tlc-ai__tag'>{html_escape(skill)}</span>" for skill in (profile.get("skills") or []))
    languages = "".join(f"<span class='tlc-ai__tag'>{html_escape((item.get('name') or '') + ' ' + (item.get('level') or ''))}</span>"
                        for item in (profile.get("languages") or []))
    education = "".join(f"<li>{html_escape(', '.join(x for x in (item.get('degree'), item.get('school'), item.get('major'), item.get('year')) if x))}</li>"
                        for item in (profile.get("education") or []))
    certificates = "".join(f"<li>{html_escape(item)}</li>" for item in (profile.get("certifications") or []))
    work = "".join(_work_row(item) for item in (profile.get("work") or []))
    blocks = ["<div class='tlc-ai__card'><h5>Hồ sơ trích từ CV</h5>"
              f"<dl class='tlc-ai__kv'>{definition or '<dt>Chưa trích được thông tin nào</dt>'}</dl>"
              + tag_row(skills) + tag_row(languages) + "</div>"]
    if work:
        blocks.append(f"<div class='tlc-ai__card'><h5>Quá trình làm việc</h5><ul class='tlc-ai__list'>{work}</ul></div>")
    if education or certificates:
        blocks.append("<div class='tlc-ai__card'><h5>Học vấn và chứng chỉ</h5>"
                      f"<ul class='tlc-ai__list'>{education}{certificates}</ul></div>")
    if payload.get("questions"):
        blocks.append("<div class='tlc-ai__card'><h5>Câu hỏi gợi ý cho vòng phỏng vấn</h5><ul class='tlc-ai__list'>"
                      + "".join(f"<li>{html_escape(q)}</li>" for q in _as_list(payload["questions"])[:6]) + "</ul></div>")
    if payload.get("risks"):
        blocks.append("<div class='tlc-ai__card'><h5>Điểm cần hỏi lại</h5><ul class='tlc-ai__list'>"
                      + "".join(f"<li>{html_escape(r)}</li>" for r in _as_list(payload["risks"])[:6]) + "</ul></div>")
    return "".join(blocks)


def render_ledger(rows, applicant_name=""):
    """The story of the file: one line per action, AI and human alike, oldest first."""
    items = []
    for row in rows:
        label, tone = LEDGER_LABEL.get(row["event"], (row["event"], "ai" if str(row["event"]).startswith("ai.") else "human"))
        if row.get("status") in ("queued", "running"):
            tone = "run"
        elif row.get("status") in ("error", "failed"):
            tone = "bad"
        meta = [x for x in (row.get("actor"), row.get("model")) if x]
        if row.get("duration_ms"):
            meta.append(f"{flt(row['duration_ms']) / 1000:.1f}s")
        if row.get("step"):
            meta.append(str(row["step"]).split(". ")[-1])
        items.append(f"<li class='tlc-ledger__item tlc-ledger__item--{tone}'><span class='tlc-ledger__dot'></span><div>"
                     f"<div class='tlc-ledger__ev'>{html_escape(row['event'])} <span style='font-weight:400;color:var(--gray-600)'>"
                     f"— {html_escape(label)}</span></div>"
                     f"<div class='tlc-ledger__meta'>{html_escape(' · '.join(meta))}</div>"
                     f"<div>{html_escape(row.get('detail') or '')}</div></div>"
                     f"<div class='tlc-ledger__time'>{html_escape(format_datetime(row.get('created_on'), 'dd/MM HH:mm:ss'))}</div></li>")
    body = chr(10).join(items) or "<li class='tlc-ledger__item'><div class='tlc-ledger__meta'>Chưa có sự kiện nào cho hồ sơ này.</div></li>"
    return (f"<style>{CSS}</style><div class='tlc-ai'><h5>Nhật ký hoạt động{f' · {html_escape(applicant_name)}' if applicant_name else ''}"
            f" ({len(rows)} sự kiện)</h5><ol class='tlc-ledger'>{body}</ol></div>")


@frappe.whitelist()
def panel(name):
    """Both blocks of the AI section on the form: the screening picture and the ledger of the file."""
    doc = frappe.get_doc("Job Applicant", name)
    doc.check_permission("read")
    payload = load_payload(doc)
    screening = render_screening(payload) if payload else (
        "<div class='tlc-ai'><div class='tlc-ai__note'>Hồ sơ chưa được chấm. Bấm <b>AI chấm CV</b> để trợ lý đối chiếu "
        "với mô tả công việc; kết quả hiện thành điểm, biểu đồ radar, bản đồ tiêu chí và chân dung ứng viên.</div></div>")
    return {"screening": screening, "ledger": render_ledger(ledger(name), doc.applicant_name)}


def load_payload(doc):
    """Rebuild the picture from what the screening stored, so the panel costs no new assistant call."""
    if not doc.tlc_jd_criteria and not doc.tlc_cv_profile:
        return None
    try:
        profile = json.loads(doc.tlc_cv_profile or "{}")
        criteria = [_criterion(item) for item in json.loads(doc.tlc_jd_criteria or "[]") if isinstance(item, dict)]
    except (ValueError, TypeError):
        return None
    score, missing = weighted_score(criteria) if criteria else (flt(doc.tlc_ai_score), [])
    return {"profile": profile, "criteria": criteria or [], "score": score or flt(doc.tlc_ai_score),
            "verdict": doc.tlc_ai_verdict, "summary": doc.tlc_ai_summary,
            "risks": [line.strip("- ") for line in (doc.tlc_ai_risks or "").split(chr(10)) if line.strip()],
            "questions": [line.strip("- ") for line in (doc.tlc_ai_questions or "").split(chr(10)) if line.strip()],
            "missing": missing or [line.strip("- ") for line in (doc.tlc_ai_missing or "").split(chr(10)) if line.strip()],
            "model": doc.tlc_ai_model,
            "checked_on": format_datetime(doc.tlc_ai_checked_on, "dd/MM/yyyy HH:mm") if doc.tlc_ai_checked_on else ""}


# --------------------------------------------------------------------------------------------------------- letters

def _company(doc):
    return (frappe.db.get_value("Job Opening", doc.job_title, "company")
            or frappe.db.get_value("Company", None, "company_name") or "TLC")


def position_of(doc):
    """The vacancy as a person reads it: the job title of the opening, not its record number."""
    return (frappe.db.get_value("Job Opening", doc.job_title, "job_title") or doc.designation or doc.job_title or "").strip()


def email_context(doc, kind):
    """Everything an HTML letter template needs, plus the paragraph the assistant wrote for this candidate."""
    meta = EMAIL_KINDS[kind]
    when = format_datetime(doc.tlc_interview_at, "dd/MM/yyyy HH:mm") if doc.tlc_interview_at else ""
    user = frappe.db.get_value("User", frappe.session.user, ["full_name", "email"], as_dict=True) or {}
    offer = frappe.db.get_value("Job Offer", doc.tlc_job_offer, ["name", "tlc_salary", "tlc_joining_date", "status"], as_dict=True) \
        if doc.tlc_job_offer else None
    return {
        "doctype": "Job Applicant", "name": doc.name, "applicant_name": doc.applicant_name, "email_id": doc.email_id,
        "phone_number": doc.phone_number, "position": position_of(doc),
        "designation": doc.designation or "", "company": _company(doc), "kind": meta["label"], "when": when,
        "interviewer": frappe.db.get_value("Employee", doc.tlc_interviewer, "employee_name") if doc.tlc_interviewer else "",
        "interview_notes": doc.tlc_interview_notes or "", "interview_result": doc.tlc_interview_result or "",
        "interview_summary": doc.tlc_interview_summary or "", "decision_reason": doc.tlc_decision_reason or "",
        "step": doc.tlc_step or "", "ai_score": flt(doc.tlc_ai_score), "ai_verdict": doc.tlc_ai_verdict or "",
        "strengths": [c["name"] for c in json.loads(doc.tlc_jd_criteria or "[]") if c.get("rating") == "Đạt"][:4]
        if doc.tlc_jd_criteria else [],
        "hr_name": user.get("full_name") or user.get("email") or "Bộ phận Nhân sự",
        "hr_email": user.get("email") or "", "site": get_url(),
        "hr_phone": frappe.db.get_value("Employee", {"user_id": frappe.session.user}, "cell_number") or "",
        "offer": offer, "salary": f"{flt((offer or {}).get('tlc_salary')):,.0f}" if offer else "",
        "joining_date": format_datetime((offer or {}).get("tlc_joining_date"), "dd/MM/yyyy") if (offer or {}).get("tlc_joining_date") else "",
        "ai_lines": ai_lines(doc, kind, meta),
    }


def ai_lines(doc, kind, meta):
    """The assistant writes the personal paragraph; the letter itself still comes from the approved template.

    Only what a candidate may read goes into the prompt: the internal AI score, verdict and the missing
    must-have criteria stay in the desk.
    """
    facts = json.dumps(_letter_facts(doc, kind), ensure_ascii=False)[:1500]
    prompt = (f"Viết 2-4 câu tiếp theo cho thư '{meta['label']}' gửi ứng viên {doc.applicant_name} ứng tuyển vị trí "
              f"{position_of(doc)}. Không lặp lại lời chào, không ký tên, không tự thêm ngày giờ hay chức danh ngoài dữ kiện "
              f"đã cho. Không nêu điểm, xếp loại hay tiêu chí nội bộ của trợ lý. {meta['hint']} "
              f"Dữ kiện đã chốt: {facts}.")
    try:
        raw = chat_json(NOTE_SYSTEM, prompt, ["lines"], max_tokens=420)
        written = [plain(line) for line in _as_list(raw.get("lines")) if plain(line)][:4]
        if written:
            return written
    except Exception:
        pass
    return [f"Chào {doc.applicant_name}, Bộ phận Nhân sự {_company(doc)} đã xem hồ sơ ứng tuyển vị trí "
            f"{doc.job_title or doc.designation or ''} của bạn."]


def plain(line):
    """The assistant sometimes writes markdown; the letter is HTML and the greeting is already in the template."""
    text = _clean(line).replace("**", "").replace("__", "")
    return re.sub(r"^(ch(?:a|à)o|kính gửi)\s+[^,]{0,40},?\s*", "", text, flags=re.I).strip()


def _letter_facts(doc, kind):
    strengths = [c["name"] for c in json.loads(doc.tlc_jd_criteria or "[]") if c.get("rating") == "Đạt"][:3]         if doc.tlc_jd_criteria else []
    facts = {"vi_tri": position_of(doc), "diem_manh": strengths}
    if kind in ("invitation", "confirmation"):
        facts.update({"thoi_gian": format_datetime(doc.tlc_interview_at, "dd/MM/yyyy HH:mm") if doc.tlc_interview_at else "",
                      "nguoi_phong_van": frappe.db.get_value("Employee", doc.tlc_interviewer, "employee_name")
                      if doc.tlc_interviewer else ""})
    if kind == "result":
        facts.update({"ket_qua": doc.tlc_interview_result, "ly_do": doc.tlc_decision_reason,
                      "bien_ban": (doc.tlc_interview_notes or "")[:300]})
    if kind == "offer":
        offer = frappe.db.get_value("Job Offer", doc.tlc_job_offer, ["tlc_salary", "tlc_joining_date", "designation"],
                                    as_dict=True) if doc.tlc_job_offer else None
        facts.update({"luong": f"{flt((offer or {}).get('tlc_salary')):,.0f} VND" if offer else "",
                      "ngay_vao_lam": str((offer or {}).get("tlc_joining_date") or "") if offer else "",
                      "chuc_danh": (offer or {}).get("designation") if offer else doc.designation})
    if kind == "rejection":
        facts.update({"ly_do": doc.tlc_decision_reason or "chưa phù hợp với yêu cầu hiện tại của vị trí"})
    return facts


def _facts(doc):
    return {"score": doc.tlc_ai_score, "verdict": doc.tlc_ai_verdict,
            "strengths": [c["name"] for c in json.loads(doc.tlc_jd_criteria or "[]") if c.get("rating") == "Đạt"][:4]
            if doc.tlc_jd_criteria else [],
            "missing": [line.strip("- ") for line in (doc.tlc_ai_missing or "").split(chr(10)) if line.strip()],
            "interview_at": str(doc.tlc_interview_at or ""), "interviewer": (
                frappe.db.get_value("Employee", doc.tlc_interviewer, "employee_name") if doc.tlc_interviewer else ""),
            "result": doc.tlc_interview_result, "summary": (doc.tlc_ai_summary or "")[:280]}


@frappe.whitelist(methods=["POST"])
def compose(name, kind):
    """Render the approved HTML letter with the assistant's paragraph, so HR only verifies and presses Gửi."""
    from tlc_hr.interface.recruitment_pipeline import can_hr

    can_hr()
    doc = frappe.get_doc("Job Applicant", name)
    doc.check_permission("read")
    if kind not in EMAIL_KINDS:
        frappe.throw(f"Loại thư không hỗ trợ: {kind}")
    meta = EMAIL_KINDS[kind]
    if kind in ("invitation", "confirmation") and not doc.tlc_interview_at:
        frappe.throw("Chưa có lịch phỏng vấn: ghi nhận quyết định mời phỏng vấn (bước 3) trước khi soạn thư mời.")
    if kind in ("invitation", "confirmation", "offer") and not doc.email_id:
        frappe.throw("Hồ sơ thiếu email để gửi thư.")
    if not frappe.db.exists("Email Template", meta["template"]):
        frappe.throw(f"Chưa có mẫu thư “{meta['template']}”; chạy bench tlc config apply để dựng mẫu.")
    template = frappe.get_doc("Email Template", meta["template"])
    rendered = template.get_formatted_email(email_context(doc, kind))
    trace(doc.name, "email.drafted", f"Soạn “{meta['label']}” từ mẫu {template.name} · chủ đề: {rendered['subject']}",
          actor=frappe.session.user, step=doc.tlc_step)
    frappe.db.commit()
    return {"template": template.name, "kind": kind, "title": meta["title"], "label": meta["label"],
            "recipients": doc.email_id, "subject": rendered["subject"], "message": rendered["message"],
            "reference": {"doctype": "Job Applicant", "name": doc.name}}


def mail_recipients(doc):
    """The addresses a mail went to. A Communication keeps them as child rows, or as one comma string while the desk
    is still turning the Table MultiSelect into rows, so both shapes are read here."""
    rows = doc.get("recipients") or []
    if isinstance(rows, str):
        return [_clean(rows).lower()] if _clean(rows) else []
    found = []
    for row in rows:
        email = getattr(row, "email", None) or (row.get("email") if isinstance(row, dict) else row)
        if _clean(email):
            found.append(_clean(email).lower())
    return found


def communication_created(doc, method=None):
    """Every mail the desk sends from a candidate file lands in the ledger; the invitation also closes step 4."""
    if doc.reference_doctype != "Job Applicant" or not doc.reference_name:
        return
    if doc.communication_type and doc.communication_type != "Communication":
        return
    if not frappe.db.exists("Job Applicant", doc.reference_name):
        return
    applicant = frappe.db.get_value("Job Applicant", doc.reference_name, ["tlc_step", "email_id", "tlc_email_communication"], as_dict=True)
    if applicant.tlc_email_communication == doc.name:
        return
    recipients = mail_recipients(doc)
    detail = f"{doc.subject or '(không chủ đề)'} → {', '.join(recipients) or '(không người nhận)'}"
    frappe.db.set_value("Job Applicant", doc.reference_name, "tlc_email_communication", doc.name, update_modified=False)
    trace(doc.reference_name, "email.sent", detail, actor=doc.sender or frappe.session.user, step=applicant.tlc_step,
          message_id=doc.name)
    frappe.db.commit()
    # the pipeline sends a letter itself only when nobody opened the composer; that call closes the step on its own
    if frappe.flags.get("tlc_no_advance"):
        return
    if applicant.tlc_step == "3. Quyết định mời phỏng vấn" and applicant.email_id in recipients:
        from tlc_hr.interface.recruitment_pipeline import advance

        advance(doc.reference_name, "invitation", {"communication": doc.name, "reason": "Thư mời đã gửi từ hộp thư trên desk"})


# ------------------------------------------------------------------------------------ the later steps of the loop

@frappe.whitelist(methods=["POST"])
def interview_summary(name):
    """Step 5: turn the interview notes into a per-criterion read the offer decision can rest on."""
    from tlc_hr.interface.recruitment_pipeline import can_hr

    can_hr()
    doc = frappe.get_doc("Job Applicant", name)
    doc.check_permission("read")
    if not (doc.tlc_interview_notes or "").strip():
        frappe.throw("Chưa có biên bản phỏng vấn để tổng hợp.")
    criteria = json.loads(doc.tlc_jd_criteria or "[]")
    user = (f"Vị trí: {doc.job_title or doc.designation}\n"
            f"TIÊU CHÍ ĐÃ CHẤM: {json.dumps([{'name': c['name'], 'must': c['must'], 'cv': c['rating']} for c in criteria], ensure_ascii=False)[:2500]}\n"
            f"BIÊN BẢN PHỎNG VẤN: {(doc.tlc_interview_notes or '')[:3000]}\n"
            f"ĐIỂM CV: {doc.tlc_ai_score}/100 {doc.tlc_ai_verdict}")
    started = perf_counter()
    try:
        raw = chat_json(INTERVIEW_SYSTEM, user, ["summary", "per_criteria", "verdict"], max_tokens=800)
    except Exception as exc:
        trace(doc.name, "ai.interview.summarised", f"Không tổng hợp được: {str(exc)[:300]}", status="error")
        frappe.db.commit()
        raise
    rows = [_row(item, ("name", "read")) for item in _as_list(raw.get("per_criteria")) if isinstance(item, dict)]
    text = ((raw.get("summary") or "") + chr(10)
            + lines([f"{item['name']}: {item['read']}" for item in rows if item["name"] and item["read"]])).strip()
    doc.db_set({"tlc_interview_summary": text[:4000]}, commit=False)
    frappe.db.commit()
    trace(doc.name, "ai.interview.summarised", f"{(raw.get('verdict') or '').strip()} · {len(rows)} tiêu chí · {text[:400]}"[:1500],
          actor="AI", model=model_name(), duration_ms=int((perf_counter() - started) * 1000))
    frappe.db.commit()
    return {"verdict": (raw.get("verdict") or "").strip(), "summary": text, "criteria": rows}


@frappe.whitelist(methods=["POST"])
def offer_recommendation(name):
    """Step 5 advice: a band built from the JD range and the offers already made for the same designation."""
    from tlc_hr.interface.recruitment_pipeline import can_hr

    can_hr()
    doc = frappe.get_doc("Job Applicant", name)
    doc.check_permission("read")
    profile = json.loads(doc.tlc_cv_profile or "{}")
    comparable = frappe.get_all("Job Offer", filters={"designation": doc.designation, "docstatus": 1},
                               fields=["tlc_salary"], limit=20)
    marks = [flt(row.tlc_salary) for row in comparable if flt(row.tlc_salary)]
    low, high = flt(doc.lower_range), flt(doc.upper_range)
    band = {"low": low or (min(marks) if marks else 0), "high": high or (max(marks) if marks else 0),
            "median": sorted(marks)[len(marks) // 2] if marks else 0}
    prompt = (f"Đề xuất khoảng lương mời nhận việc cho {doc.applicant_name}.\n"
              f"Dữ kiện: JD {doc.job_title or doc.designation}, kinh nghiệm {flt(profile.get('years_experience'))} năm, "
              f"khoảng lương ứng viên mong muốn {low:,.0f}-{high:,.0f}, mặt bằng nội bộ cùng chức danh "
              f"{['{:,.0f}'.format(x) for x in marks] or 'chưa có'}, kết quả phỏng vấn {doc.tlc_interview_result}, "
              f"điểm CV {doc.tlc_ai_score}/100 {doc.tlc_ai_verdict}. Đơn vị VND.")
    started = perf_counter()
    advice = ""
    try:
        raw = chat_json(OFFER_SYSTEM, prompt, ["text"], max_tokens=500)
        advice = _clean(raw.get("text"))[:1200]
        if raw.get("low") and raw.get("high") and flt(raw["low"]) < flt(raw["high"]):
            band.update({"low": flt(raw["low"]), "high": flt(raw["high"])})
    except Exception as exc:
        trace(doc.name, "ai.offer.recommended", f"Không tạo được khuyến nghị: {str(exc)[:280]}", status="error")
        frappe.db.commit()
    doc.db_set({"tlc_offer_recommendation": advice[:2000]}, commit=False)
    frappe.db.commit()
    trace(doc.name, "ai.offer.recommended", f"Khuyến nghị {band['low']:,.0f}–{band['high']:,.0f} VND · {advice[:600]}",
          actor="AI", model=model_name(), duration_ms=int((perf_counter() - started) * 1000))
    frappe.db.commit()
    return {"low": band["low"], "high": band["high"], "median": band["median"], "text": advice}
