// TLC additions to the standard Leave Application form (hooks.doctype_js): what helps the approver decide, (the reason dialog is in tlc_workflow.js).
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
});
