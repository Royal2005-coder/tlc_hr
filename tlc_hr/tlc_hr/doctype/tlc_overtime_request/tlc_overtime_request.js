// Đề nghị tăng ca: the headline shows the Labour Code limits the request is counted against and what the reader is asked to do.
frappe.ui.form.on("TLC Overtime Request", {
	refresh(frm) {
		// once sent, what the worker consents to is fixed (the server refuses a change too)
		const sent = frm.doc.workflow_state && frm.doc.workflow_state !== "Nháp";
		["employee", "ot_date", "from_time", "to_time", "reason"].forEach((f) => frm.set_df_property(f, "read_only", sent ? 1 : 0));
		if (!frm.doc.hours) return;
		const near = frm.doc.month_hours > 32 || frm.doc.year_hours > 160;
		const ask = {
			"Chờ người lao động đồng ý": frm.doc.employee_user === frappe.session.user
				? __("Bạn được đề nghị tăng ca: chọn Hành động → Đồng ý hoặc Từ chối (ghi lý do).") : __("Đang chờ người lao động đồng ý."),
			"Chờ giám đốc duyệt": __("Người lao động đã đồng ý lúc {0}.", [frappe.datetime.str_to_user(frm.doc.consent_at)]),
		}[frm.doc.workflow_state] || "";
		frm.dashboard.set_headline_alert(
			`${__("{0} giờ ({1})", [frm.doc.hours, frm.doc.day_type])} · ${__("Tháng: {0}/40 giờ", [frm.doc.month_hours])} · ` +
				`${__("Năm: {0}/200 giờ", [frm.doc.year_hours])}${ask ? " · " + ask : ""}`,
			near ? "orange" : "blue"
		);
	},
});
