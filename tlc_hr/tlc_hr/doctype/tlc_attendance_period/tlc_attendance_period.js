// Kỳ công: the headline sums up the month and says what the reader is asked to do; HR rebuilds the summary while it is a draft.
frappe.ui.form.on("TLC Attendance Period", {
	onload(frm) {
		if (frm.is_new() && !frm.doc.company) frm.set_value("company", frappe.defaults.get_user_default("Company"));
		if (frm.is_new() && !frm.doc.period_month) {
			const last = frappe.datetime.add_months(frappe.datetime.get_today(), -1);
			frm.set_value("period_month", last.slice(0, 7));
		}
	},
	refresh(frm) {
		if (!frm.is_new() && ["Nháp", undefined, null, ""].includes(frm.doc.workflow_state) && frm.has_perm("write")) {
			frm.add_custom_button(__("Làm mới tổng hợp"), () =>
				frappe.call("tlc_hr.interface.attendance.refresh_period", { name: frm.doc.name })
					.then(() => frm.reload_doc()));
		}
		if (frm.is_new()) return;
		const ask = {
			"Nháp": __("HR kiểm tra bảng công rồi gửi."),
			"Chờ quản lý xác nhận": frm.doc.manager_user === frappe.session.user
				? __("Kiểm tra công của nhà máy bạn: Hành động → Xác nhận, hoặc Trả lại (ghi lý do).") : __("Chờ trưởng nhà máy xác nhận."),
			"Chờ nhân sự đối soát": __("HR đối soát với nghỉ phép, tăng ca, công tác."),
			"Chờ giám đốc ký": __("CEO ký để khoá kỳ; sau khi khoá chỉ sửa được bằng điều chỉnh sau chốt."),
			"Đã khoá": __("Đã khoá lúc {0}.", [frappe.datetime.str_to_user(frm.doc.locked_at)]),
		}[frm.doc.workflow_state] || "";
		const numbers = __("{0} người · có mặt {1} ngày · vắng {2} · nghỉ phép {3} · đi muộn {4} lượt · tăng ca {5} giờ",
			[frm.doc.employee_count, frm.doc.present_days, frm.doc.absent_days, frm.doc.leave_days, frm.doc.late_count, frm.doc.ot_hours]);
		const open = frm.doc.open_count ? " · " + __("Còn {0} việc chưa xử lý", [frm.doc.open_count]) : "";
		frm.dashboard.set_headline_alert(`${numbers}${open}${ask ? " · " + ask : ""}`,
			frm.doc.open_count ? "red" : frm.doc.docstatus === 1 ? "green" : "blue");
	},
});
