"""Generate ordinary Frappe PDF vouchers and protect the stored approved snapshots."""
import frappe
from frappe.utils.file_manager import save_file

from tlc_hr.domain import travel_finance as rules


def snapshot(doc, method=None):
    before = doc.get_doc_before_save()
    state = doc.get("workflow_state")
    if before and before.get("workflow_state") == state:
        return
    wanted = {"Employee Advance": {rules.PAYMENT: "Phiếu đề xuất tạm ứng"},
              "Expense Claim": {rules.SETTLEMENT: "Phiếu quyết toán tạm ứng", rules.DONE: "Phiếu quyết toán hoàn tất"},
              "Travel Request": {rules.APPROVED: "Phiếu công tác"}}
    title = wanted.get(doc.doctype, {}).get(state)
    if not title:
        return
    filename = f"TLC-{doc.name}-{state}.pdf"
    if frappe.db.exists("File", {"attached_to_doctype": doc.doctype, "attached_to_name": doc.name, "file_name": filename,
                                "tlc_finance_snapshot": 1}):
        return
    try:
        content = frappe.get_print(doc.doctype, doc.name, print_format="Standard", as_pdf=True)
    except Exception as exc:
        # Print assets are fetched over the site host; a runner without that DNS must not block an approval.
        frappe.logger("tlc_hr.finance").warning(f"{doc.doctype} {doc.name}: PDF snapshot skipped: {exc}")
        doc.add_comment("Info", f"{title}: không tạo được bản PDF trong môi trường này; hồ sơ duyệt vẫn được ghi nhận.")
        return
    file = save_file(filename, content, doc.doctype, doc.name, is_private=1)
    file.flags.tlc_creating_finance_snapshot = True
    file.tlc_finance_snapshot = 1
    file.save(ignore_permissions=True)
    doc.add_comment("Info", f"{title}: bản PDF bất biến {file.file_url}; mã gốc {doc.name}.")


def guard_snapshot(doc, method=None):
    old = doc.get_doc_before_save()
    protected = bool(doc.get("tlc_finance_snapshot") or (old and old.get("tlc_finance_snapshot")))
    if protected and not doc.flags.get("tlc_creating_finance_snapshot"):
        frappe.throw("Không sửa hoặc xóa bản chụp chứng từ tài chính đã duyệt.", frappe.PermissionError)
