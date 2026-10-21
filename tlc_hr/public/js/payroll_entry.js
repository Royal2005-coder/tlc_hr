// Bảng lương: the headline sums up the month (people, gross, net, PIT, overtime, employer contributions) and says what the reader is
// asked to do, so the CEO signs and the accountant pays from the form itself.
frappe.ui.form.on("Payroll Entry", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.workflow_state || frm.doc.workflow_state === "Nháp") return;
		frappe.call("tlc_hr.interface.payroll.payroll_summary", { name: frm.doc.name }).then(({ message: s }) => {
			if (!s) return;
			const money = (v) => format_currency(v, "VND", 0);
			const ask = {
				"Đã tính lương": __("HR kiểm tra phiếu lương rồi Gửi ký."),
				"Chờ giám đốc ký": __("CEO: Hành động → Ký duyệt để ghi sổ và công bố phiếu lương, hoặc Trả lại (ghi lý do)."),
				"Đã ký": __("Kế toán: chuyển khoản, nhập Số chứng từ ngân hàng và Ngày chi, rồi Hành động → Xác nhận đã chi."),
				"Đã chi": __("Đã chi, chứng từ {0}.", [frm.doc.tlc_bank_reference]),
			}[frm.doc.workflow_state] || "";
			const pending = s.draft ? " · " + __("{0} phiếu chưa ghi sổ", [s.draft]) : "";
			frm.dashboard.set_headline_alert(
				__("{0} phiếu lương · tổng thu nhập {1} · thực lĩnh {2} · thuế TNCN {3} · tăng ca {4} · công ty đóng BH {5}",
					[s.slips, money(s.gross), money(s.net), money(s.pit), money(s.overtime), money(s.employer)]) + pending + (ask ? " · " + ask : ""),
				frm.doc.workflow_state === "Đã chi" ? "green" : "blue"
			);
		});
	},
});
