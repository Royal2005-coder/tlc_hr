// TonomyX six-step hiring pipeline: the AI proposes and shows its work, a person decides, every step leaves a trace.
frappe.ui.form.on("Job Applicant", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.tlc_step) return;
		const STEPS = [
			"1. Tiếp nhận hồ sơ",
			"2. Đối chiếu tiêu chí",
			"3. Quyết định mời phỏng vấn",
			"4. Thư mời và lịch hẹn",
			"5. Phỏng vấn và quyết định offer",
			"6. Kết quả và lưu vết",
		];
		const AI = __("Trợ lý tuyển dụng");
		const LETTERS = __("Thư từ ứng viên");
		const step = frm.doc.tlc_step;
		const call = (method, args, message, then) =>
			frappe.call({
				method: `tlc_hr.interface.recruitment_pipeline.${method}`,
				type: "POST",
				args,
				freeze: true,
				freeze_message: message,
				callback: (r) => {
					if (then) then(r.message);
					frm.reload_doc();
				},
			});
		const ai_call = (method, args, message, then) =>
			frappe.call({
				method: `tlc_hr.interface.recruitment_ai.${method}`,
				type: "POST",
				args,
				freeze: true,
				freeze_message: message,
				callback: (r) => {
					if (then) then(r.message);
					frm.reload_doc();
				},
			});
		const dialog = (title, fields, action) => {
			const d = new frappe.ui.Dialog({
				title,
				fields,
				primary_action_label: __("Xác nhận"),
				primary_action(values) {
					d.hide();
					call("advance", { name: frm.doc.name, action, payload: JSON.stringify(values) }, __("Đang ghi nhận quyết định"));
				},
			});
			d.show();
		};
		const inStep = (...steps) => steps.includes(step);

		frm.dashboard.set_headline_alert(
			__(
				"Bước {0} · AI {1}/100 ({2}) · khớp JD {3}% · {4} · Người quyết định: {5}",
				[
					step,
					frm.doc.tlc_ai_status === "Đã chấm" ? frm.doc.tlc_ai_score || 0 : "—",
					frm.doc.tlc_ai_verdict || __(frm.doc.tlc_ai_status || "chưa chấm"),
					frm.doc.tlc_ai_match || 0,
					frm.doc.tlc_ai_missing ? __("còn thiếu tiêu chí bắt buộc") : __("đủ tiêu chí bắt buộc"),
					frm.doc.tlc_decision_by || __("chưa có"),
				]
			),
			step === "Từ chối" ? "red" : step === STEPS[5] ? "green" : "blue"
		);

		// The screening picture and the activity ledger are drawn by the server, then dropped into the HTML blocks.
		frappe.call({
			method: "tlc_hr.interface.recruitment_ai.panel",
			args: { name: frm.doc.name },
			callback(r) {
				if (!r.message) return;
				["screening", "ledger"].forEach((key) => {
					const field = key === "screening" ? "tlc_screening_html" : "tlc_trace_html";
					const control = frm.fields_dict[field];
					if (!control) return;
					control.df.options = r.message[key];
					control.$wrapper.html(r.message[key]);
				});
			},
		});

		frm.add_custom_button(__("AI chấm CV"), () => call("screen", { name: frm.doc.name }, __("Đang đối chiếu CV với JD")), AI);
		frm.add_custom_button(__("Mở Kanban 6 bước"), () =>
			window.open("/desk/job-applicant/view/kanban/TLC%20Tuy%E1%BB%83n%20d%E1%BB%A5ng%206%20b%C6%B0%E1%BB%9Bc", "_blank"), AI);
		frm.add_custom_button(__("Xem nhật ký AI"), () =>
			frappe.set_route("List", "TLC AI Trace Log", { candidate: frm.doc.name }), AI);
		if (inStep(STEPS[4], STEPS[5])) {
			frm.add_custom_button(__("Tổng hợp phỏng vấn theo tiêu chí"), () =>
				ai_call("interview_summary", { name: frm.doc.name }, __("Trợ lý đang đối chiếu biên bản với tiêu chí JD")), AI);
		}

		// Letters: the approved HTML template, the assistant's paragraph, then HR verifies and presses Gửi.
		const open_letter = (kind) =>
			ai_call(
				"compose",
				{ name: frm.doc.name, kind },
				__("Trợ lý đang soạn thư theo mẫu"),
				(m) => {
					if (!m) return;
					new frappe.views.CommunicationComposer({
						frm,
						doc: frm.doc,
						reference_doctype: "Job Applicant",
						reference_name: frm.doc.name,
						recipients: m.recipients,
						subject: m.subject,
						message: m.message,
						title: __("{0} · mẫu {1}", [m.title, m.template]),
						btn_submit_label: __("Gửi thư"),
					});
				}
			);
		const letters = [
			["invitation", __("Thư mời phỏng vấn"), () => inStep(STEPS[2], STEPS[3])],
			["confirmation", __("Thư xác nhận lịch hẹn"), () => inStep(STEPS[3], STEPS[4])],
			["result", __("Thư thông báo kết quả"), () => inStep(STEPS[4], STEPS[5])],
			["offer", __("Thư mời nhận việc"), () => inStep(STEPS[4], STEPS[5]) && !!frm.doc.tlc_job_offer],
			["rejection", __("Thư cảm ơn và giữ liên lạc"), () => inStep("Từ chối", "Talent Pool")],
		];
		letters.forEach(([kind, label, show]) => {
			if (show()) frm.add_custom_button(label, () => open_letter(kind), LETTERS);
		});

		if (inStep(STEPS[1], STEPS[2])) {
			frm.add_custom_button(__("Mời phỏng vấn"), () => dialog(__("Quyết định mời phỏng vấn (bước 3)"), [
				{ fieldname: "interviewer", label: __("Người phỏng vấn"), fieldtype: "Link", options: "Employee", reqd: 1 },
				{ fieldname: "interview_at", label: __("Thời gian phỏng vấn"), fieldtype: "Datetime", reqd: 1 },
				{ fieldname: "reason", label: __("Lý do quyết định"), fieldtype: "Small Text", reqd: 1,
					description: __("Đối chiếu điểm AI và tiêu chí JD; đây là quyết định của người, không phải của AI.") },
			], "invite"), AI);
		}
		if (inStep(STEPS[3])) {
			frm.add_custom_button(__("Ghi nhận phỏng vấn"), () => dialog(__("Biên bản phỏng vấn (bước 5)"), [
				{ fieldname: "interview_notes", label: __("Biên bản / đánh giá"), fieldtype: "Small Text", reqd: 1 },
				{ fieldname: "interview_result", label: __("Kết quả"), fieldtype: "Select", options: "Pass\nFail\nHold", reqd: 1 },
				{ fieldname: "reason", label: __("Lý do"), fieldtype: "Small Text" },
			], "interview"), AI);
		}
		if (inStep(STEPS[4]) && frappe.user.has_role(["TLC Director", "System Manager"])) {
			frm.add_custom_button(__("Quyết định offer"), () => {
				ai_call("offer_recommendation", { name: frm.doc.name }, __("Trợ lý đang tính khoảng lương đề xuất"), (advice) => {
					const mid = advice && advice.high ? Math.round((advice.low + advice.high) / 2 / 1000) * 1000 : 0;
					dialog(__("Giám đốc quyết định offer"), [
						{ fieldname: "salary", label: __("Lương chính thức (VND)"), fieldtype: "Currency", reqd: 1, default: mid },
						{ fieldname: "joining_date", label: __("Ngày vào làm"), fieldtype: "Date", reqd: 1 },
						{ fieldname: "designation", label: __("Chức danh"), fieldtype: "Link", options: "Designation" },
						{ fieldname: "department", label: __("Bộ phận"), fieldtype: "Link", options: "Department" },
						{ fieldname: "reason", label: __("Căn cứ quyết định"), fieldtype: "Small Text" },
						{ fieldname: "advice_html", fieldtype: "HTML",
							options: advice && advice.text
								? `<div style="font-size:12px"><b>${__("Khuyến nghị của trợ lý")}:</b> ${advice.text}<br>` +
								  `${__("Khoảng đề xuất")}: ${format_money(advice.low)} – ${format_money(advice.high)} VND</div>`
								: "" },
					], "offer");
				});
			}, AI);
		}
		if (inStep(STEPS[5])) {
			frm.add_custom_button(__("Hoàn tất và bàn giao onboarding"), () => dialog(__("Kết quả và lưu vết (bước 6)"), [
				{ fieldname: "confirm", label: __("Tạo Employee Onboarding từ Job Offer và việc bàn giao cho HR"), fieldtype: "Check", default: 1, reqd: 1 },
			], "complete"), AI);
		}
		if (!inStep("Từ chối", "Talent Pool", STEPS[5])) {
			frm.add_custom_button(__("Từ chối"), () => dialog(__("Kết thúc hồ sơ"), [
				{ fieldname: "reason", label: __("Lý do"), fieldtype: "Small Text", reqd: 1 },
			], "reject"), AI);
		}
		frm.add_custom_button(__("Chuyển talent pool"), () => dialog(__("Lưu vào talent pool"), [
			{ fieldname: "reason", label: __("Lý do"), fieldtype: "Small Text", reqd: 1 },
		], "talent"), AI);
	},
});

function format_money(value) {
	return Math.round(value || 0).toLocaleString("vi-VN");
}
