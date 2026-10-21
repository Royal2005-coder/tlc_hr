// TLC approval workflows on the standard desk forms (hooks.app_include_js): "Từ chối" asks for the reason first.
// The desk freezes the page before before_workflow_action runs: unfreeze while the dialog is open, freeze again to continue.
// apply_workflow reloads the document from the database, so the reason is stored first, then the decision runs.
(() => {
	const DOCTYPES = ["Leave Application", "Attendance Request", "TLC Overtime Request", "Travel Request", "Employee Advance",
		"Expense Claim", "Employee Separation", "TLC Attendance Period", "Payroll Entry", "TLC Employment Contract",
		"TLC Employee Dependent", "TLC Employee Document", "TLC Employee Change Request", "TLC Probation Review",
		"TLC Employment Episode", "Employee Promotion", "Employee Transfer", "Job Requisition", "Job Offer"];
	// actions that need a reason: refusing a request, returning a period to HR, reopening a locked period
	const REASON_ACTIONS = ["Từ chối", "Trả lại", "Mở lại kỳ"];

	function ask_reason(frm) {
		if (!REASON_ACTIONS.includes(frm.selected_workflow_action) || (frm.doc.tlc_reject_reason || "").trim()) {
			return;
		}
		frappe.dom.unfreeze();
		return new Promise((resolve, reject) => {
			let confirmed = false;
			const dialog = frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Lý do"), reqd: 1 },
				({ reason }) => {
					confirmed = true;
					frappe.dom.freeze();
					frappe
						.xcall("frappe.client.set_value", { doctype: frm.doctype, name: frm.docname, fieldname: "tlc_reject_reason", value: reason })
						.then((doc) => {
							frappe.model.sync(doc);
							resolve();
						}, (error) => {
							frappe.dom.unfreeze();
							reject(error);
						});
				},
				__(frm.selected_workflow_action),
				__(frm.selected_workflow_action)
			);
			// frappe.prompt hides the dialog before it calls the action: decide on the next tick whether it was a cancel.
			dialog.onhide = () => setTimeout(() => {
				if (!confirmed) reject(new Error(__("Đã huỷ từ chối")));
			});
		});
	}

	DOCTYPES.forEach((doctype) => frappe.ui.form.on(doctype, { before_workflow_action: ask_reason }));
})();
