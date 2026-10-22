// HR saves the proposal; the Director explicitly approves the persisted decision.
(() => {
	const doctypes = ["Salary Structure Assignment", "TLC Payroll Adjustment", "TLC Payroll Bonus", "TLC Salary Review"];
	for (const doctype of doctypes) {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				if (frm.is_new() || frm.is_dirty() || frm.doc.docstatus !== 0) return;
				if (!frappe.user.has_role(["TLC Director", "System Manager"])) return;
				if (frm.doc.owner === frappe.session.user || frm.doc.hr_reviewed_by === frappe.session.user) return;
				frappe.call({
					method: "tlc_hr.interface.payroll_compliance.decision_approval_context",
					args: { doctype, name: frm.doc.name },
					callback({ message }) {
						if (!message || !message.can_approve || frm.is_dirty() || frm.doc.docstatus !== 0) return;
						frm.add_custom_button(__("Phê duyệt quyết định lương"), () => {
							frappe.confirm(__("Phê duyệt bản đã lưu của {0}? Hãy kiểm tra nhân viên, mức lương, ngày hiệu lực và chứng từ trước khi xác nhận.", [frm.doc.name]), () => {
								frappe.call({
									method: "tlc_hr.interface.payroll_compliance.approve_decision",
									type: "POST",
									args: { doctype, name: frm.doc.name, modified: frm.doc.modified },
									freeze: true,
									freeze_message: __("Đang phê duyệt quyết định lương"),
									async callback({ message: result }) {
										if (!result || result.docstatus !== 1) return;
										await frm.reload_doc();
										frappe.msgprint({ title: __("Đã phê duyệt quyết định lương"), indicator: "green", message: __("{0} đã được phê duyệt bởi {1}.", [result.name, result.approved_by]) });
									},
								});
							});
						});
					},
				});
			},
		});
	}
})();
