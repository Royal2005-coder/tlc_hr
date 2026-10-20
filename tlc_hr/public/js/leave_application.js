// TLC additions to the standard Leave Application form (hooks.doctype_js): what helps the approver decide, and a reason to reject.
frappe.ui.form.on("Leave Application", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.docstatus !== 0 || !["Chờ quản lý duyệt", "Chờ nhân sự duyệt"].includes(frm.doc.workflow_state)) {
			return;
		}
		frappe.call("tlc_hr.api.leave_context", { name: frm.doc.name }).then(({ message: c }) => {
			if (!c) return;
			const others = c.overlap.length
				? __("{0}/{1} người ở {2} cũng nghỉ trong thời gian này: {3}", [
						c.overlap.length, c.team_size, c.site, c.overlap.map((o) => o.name + (o.pending ? " (" + __("chờ duyệt") + ")" : "")).join(", "),
				  ])
				: __("Không ai khác ở {0} nghỉ trong thời gian này.", [c.site]);
			const balance = __("Số dư {0} sau khi duyệt: {1} / {2} ngày.", [frm.doc.leave_type, c.balance_after, c.balance_now]);
			frm.dashboard.set_headline_alert(`${balance} ${others}`, c.balance_after < 0 ? "red" : c.overlap.length ? "orange" : "green");
		});
	},

	// "Từ chối" asks for the reason first; the employee sees it on their request.
	// The desk freezes the page before this hook runs: unfreeze while the dialog is open, freeze again to continue.
	before_workflow_action(frm) {
		if (frm.selected_workflow_action !== "Từ chối" || (frm.doc.tlc_reject_reason || "").trim()) {
			return;
		}
		frappe.dom.unfreeze();
		return new Promise((resolve, reject) => {
			let confirmed = false;
			const dialog = frappe.prompt(
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Lý do từ chối"), reqd: 1 },
				({ reason }) => {
					// apply_workflow reloads the document from the database: store the reason first, then let the decision run.
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
				__("Từ chối đơn"),
				__("Từ chối")
			);
			// frappe.prompt hides the dialog before it calls the action: decide on the next tick whether it was a cancel.
			dialog.onhide = () => setTimeout(() => {
				if (!confirmed) reject(new Error(__("Đã huỷ từ chối")));
			});
		});
	},
});
