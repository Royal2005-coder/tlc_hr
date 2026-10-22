// Bảng lương: the headline sums up the month (people, gross, net, PIT, overtime, employer contributions) and says what the reader is
// asked to do, so the CEO signs and the accountant pays from the form itself.
frappe.ui.form.on("Payroll Entry", {
	refresh(frm) {
		tlc_payroll_tools(frm);
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

function tlc_payroll_tools(frm) {
	if (frm.is_new() || !frappe.user.has_role(["TLC Payroll", "TLC HR Lead", "TLC Director", "Accounts User", "System Manager"])) return;
	const api = "tlc_hr.interface.payroll_compliance.";
	const approved = ["Đã ký", "Đã chi"].includes(frm.doc.workflow_state);
	const hr = frappe.user.has_role(["TLC Payroll", "TLC HR Lead", "System Manager"]);
	const escape = frappe.utils.escape_html;
	const download = (filename, content, type) => {
		const url = URL.createObjectURL(new Blob([content], { type }));
		const link = document.createElement("a");
		link.href = url;
		link.download = filename.replace(/[\\/:*?"<>|]/g, "_");
		link.click();
		setTimeout(() => URL.revokeObjectURL(url), 1000);
	};
	const show_result = (title, result) => {
		const csv = result.content !== undefined ? result.content : result.csv;
		const content = csv !== undefined ? csv : JSON.stringify(result, null, 2);
		const filename = result.filename || `${title}-${frm.doc.name}.${csv !== undefined ? "csv" : "json"}`;
		const note = result.note ? `<p>${escape(result.note)}</p>` : "";
		const dialog = new frappe.ui.Dialog({
			title: __(title),
			size: "extra-large",
			fields: [{ fieldname: "result", fieldtype: "HTML", options: `${note}<pre style="white-space:pre-wrap;max-height:60vh;overflow:auto">${escape(content)}</pre>` }],
			primary_action_label: __("Tải xuống"),
			primary_action: () => download(filename, csv !== undefined ? "\ufeff" + content : content, csv !== undefined ? "text/csv;charset=utf-8" : "application/json"),
		});
		dialog.show();
	};
	const run = (method, args, title) => frappe.call({
		method: api + method, args, freeze: true,
		callback: ({ message }) => { if (message !== undefined && message !== null) show_result(title, message); },
	});
	const prompt = (label, fields, action, method, args = {}) => {
		frm.add_custom_button(__(label), () => {
			const dialog = new frappe.ui.Dialog({
				title: __(label), fields, primary_action_label: __(action),
				primary_action(values) {
					dialog.hide();
					run(method, { ...args, ...values }, label);
				},
			});
			dialog.show();
		}, __("Dữ liệu lương"));
	};
	const date = (fieldname, label, value) => ({ fieldname, label: __(label), fieldtype: "Date", reqd: 1, default: value });
	const period = () => [date("from_date", "Từ ngày", frm.doc.start_date), date("to_date", "Đến ngày", frm.doc.end_date)];
	const company = { company: frm.doc.company };
	if (approved) {
		prompt("Xuất chuyển khoản", [{ fieldname: "bank_code", label: __("Mã ngân hàng"), fieldtype: "Data", reqd: 1, default: "VCB", description: __("Định dạng khai báo, chưa được ngân hàng chứng nhận. Tải tệp không chuyển tiền.") }], "Xuất tệp", "export_bank_batch", { name: frm.doc.name });
		frm.add_custom_button(__("Xuất đối chiếu kế toán"), () => run("export_accounting", { name: frm.doc.name }, "Xuất đối chiếu kế toán"), __("Dữ liệu lương"));
	}
	prompt("Xuất thuế TNCN", period(), "Xuất tệp", "export_pit", company);
	prompt("Xuất BHXH D02-LT", [{ fieldname: "month", label: __("Tháng (YYYY-MM)"), fieldtype: "Data", reqd: 1, default: (frm.doc.start_date || "").slice(0, 7), description: __("Tệp báo cáo để rà soát; không tự gửi hồ sơ BHXH.") }], "Xuất tệp", "export_bhxh_d02lt", company);
	prompt("Xuất sổ lao động", [date("as_of", "Tại ngày", frm.doc.end_date)], "Xuất tệp", "export_labor_register", company);
	prompt("Mô phỏng tăng lương", [
		{ fieldname: "percent_increase", label: __("Tỷ lệ tăng (%)"), fieldtype: "Float", reqd: 1, description: __("Ước tính ngân sách, không thay đổi lương thực tế. Đóng góp công ty dùng tỷ lệ 23,5% của mô hình.") },
		date("base_date", "Ngày lương hiệu lực", frm.doc.end_date),
		{ fieldname: "department", label: __("Bộ phận"), fieldtype: "Link", options: "Department", get_query: () => ({ filters: { company: frm.doc.company } }) },
	], "Mô phỏng", "simulate_salary", company);
	prompt("Báo cáo chi phí", [
		date("start_date", "Từ ngày", frm.doc.start_date), date("end_date", "Đến ngày", frm.doc.end_date),
		{ fieldname: "group_by", label: __("Nhóm theo"), fieldtype: "Select", options: "department\nemployee\nemployee_name", default: "department", reqd: 1 },
	], "Xem báo cáo", "cost_report", company);
	prompt("Biến động nhân sự", period(), "Xuất tệp", "headcount_report", company);
	frm.add_custom_button(__("Kiểm tra bất thường"), () => run("payroll_anomalies", { name: frm.doc.name }, "Kiểm tra bất thường"), __("Dữ liệu lương"));
	frm.add_custom_button(__("Rà soát sai lệch"), () => {
		frappe.call({
			method: api + "inspect_reviews", args: { name: frm.doc.name }, freeze: true,
			callback({ message: issues }) {
				const can_create = hr && !approved && frappe.model.can_create("TLC Payroll Review");
				const rows = (issues || []).map((row, index) => `<tr><td>${escape(row.employee)}</td><td>${escape(row.issue)}</td><td>${escape(row.details)}</td><td>${can_create && row.issue === "Variance" ? `<button class="btn btn-primary btn-sm" data-review-index="${index}">${__("Tạo phiếu rà soát")}</button>` : ""}</td></tr>`).join("");
				const dialog = new frappe.ui.Dialog({
					title: __("Rà soát sai lệch"), size: "extra-large",
					fields: [{ fieldname: "issues", fieldtype: "HTML", options: rows ? `<table class="table table-bordered"><thead><tr><th>${__("Nhân viên")}</th><th>${__("Vấn đề")}</th><th>${__("Chi tiết")}</th><th></th></tr></thead><tbody>${rows}</tbody></table><p>${__("Phiếu rà soát cần lý do và chứng từ riêng tư; dữ liệu thay đổi phải tạo lại phiếu. Quyết định lương thiếu phê duyệt phải được Giám đốc duyệt riêng.")}</p>` : `<p>${__("Không có sai lệch cần giải trình tại thời điểm kiểm tra.")}</p>` }],
				});
				dialog.fields_dict.issues.$wrapper.on("click", "[data-review-index]", function () {
					const row = issues[Number(this.dataset.reviewIndex)];
					frappe.call({
						method: api + "new_review", type: "POST",
						args: { name: frm.doc.name, employee: row.employee, issue: row.issue }, freeze: true,
						callback({ message }) {
							if (!message) return;
							const doc = frappe.model.get_new_doc("TLC Payroll Review");
							const name = doc.name;
							Object.assign(doc, message, { name, __islocal: 1, __unsaved: 1 });
							dialog.hide();
							frappe.set_route("Form", doc.doctype, doc.name);
						},
					});
				});
				dialog.show();
			},
		});
	});
	if (approved && (hr || frappe.user.has_role("Accounts User"))) {
		frm.add_custom_button(__("Phát hành phiếu lương qua email"), () => {
			frappe.confirm(__("Xếp hàng gửi PDF phiếu lương mã hóa tới email ưu tiên của nhân viên? Cần Payroll Settings và Email Account gửi thư thực. Xếp hàng không đồng nghĩa đã gửi."), () => {
				frappe.call({
					method: api + "deliver_payslips", type: "POST", args: { name: frm.doc.name }, freeze: true,
					async callback({ message }) {
						if (!message) return;
						await frm.reload_doc();
						frappe.msgprint({ title: __("Đã xếp hàng phiếu lương"), indicator: "blue", message: __("{0} phiếu đã xếp hàng. {1}", [message.queued, message.delivery_status]) });
					},
				});
			});
		});
	}
}
