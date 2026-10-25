// TonomyX six-step hiring pipeline: the AI proposes, a person decides, every step leaves a trace.
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
		const GROUP = __("Trợ lý tuyển dụng");
		const step = frm.doc.tlc_step;
		const call = (method, args, message) =>
			frappe.call({
				method: `tlc_hr.interface.recruitment_pipeline.${method}`,
				type: "POST",
				args,
				freeze: true,
				freeze_message: message,
				callback: () => frm.reload_doc(),
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
		const score = frm.doc.tlc_ai_status === "Đã chấm"
			? `${frm.doc.tlc_ai_score || 0}/100 · ${frm.doc.tlc_ai_verdict || ""}`
			: frm.doc.tlc_ai_status || __("Chưa chấm");
		frm.dashboard.set_headline_alert(
			__("Bước {0} · AI: {1} · Người quyết định: {2}", [step, score, frm.doc.tlc_decision_by || __("chưa có")]),
			step === "Từ chối" ? "red" : step === STEPS[5] ? "green" : "blue"
		);
		frm.add_custom_button(__("AI chấm CV"), () => call("screen", { name: frm.doc.name }, __("Đang chấm CV bằng AI")), GROUP);
		frm.add_custom_button(__("Mở Kanban 6 bước"), () =>
			window.open("/desk/job-applicant/view/kanban/TLC%20Tuy%E1%BB%83n%20d%E1%BB%A5ng%206%20b%C6%B0%E1%BB%9Bc", "_blank"), GROUP);
		frm.add_custom_button(__("Xem nhật ký AI"), () =>
			frappe.set_route("List", "TLC Recruitment AI Log", { applicant: frm.doc.name }), GROUP);
		const inStep = (...steps) => steps.includes(step);
		if (inStep(STEPS[1], STEPS[2])) {
			frm.add_custom_button(__("Mời phỏng vấn"), () => dialog(__("Quyết định mời phỏng vấn (bước 3)"), [
				{ fieldname: "interviewer", label: __("Người phỏng vấn"), fieldtype: "Link", options: "Employee", reqd: 1 },
				{ fieldname: "interview_at", label: __("Thời gian phỏng vấn"), fieldtype: "Datetime", reqd: 1 },
				{ fieldname: "reason", label: __("Lý do quyết định"), fieldtype: "Small Text", reqd: 1,
					description: __("Đối chiếu điểm AI và tiêu chí JD; đây là quyết định của người, không phải của AI.") },
			], "invite"), GROUP);
		}
		if (inStep(STEPS[2])) {
			frm.add_custom_button(__("Gửi thư mời"), () => dialog(__("Gửi thư mời và chốt lịch"), [
				{ fieldname: "confirm", label: __("Xác nhận gửi thư mời tới email ứng viên"), fieldtype: "Check", default: 1, reqd: 1 },
			], "invitation"), GROUP);
		}
		if (inStep(STEPS[3])) {
			frm.add_custom_button(__("Ghi nhận phỏng vấn"), () => dialog(__("Biên bản phỏng vấn (bước 5)"), [
				{ fieldname: "interview_notes", label: __("Biên bản / đánh giá"), fieldtype: "Small Text", reqd: 1 },
				{ fieldname: "interview_result", label: __("Kết quả"), fieldtype: "Select", options: "Pass\nFail\nHold", reqd: 1 },
				{ fieldname: "reason", label: __("Lý do"), fieldtype: "Small Text" },
			], "interview"), GROUP);
		}
		if (inStep(STEPS[4]) && frappe.user.has_role(["TLC Director", "System Manager"])) {
			frm.add_custom_button(__("Quyết định offer"), () => dialog(__("Giám đốc quyết định offer"), [
				{ fieldname: "salary", label: __("Lương chính thức (VND)"), fieldtype: "Currency", reqd: 1 },
				{ fieldname: "joining_date", label: __("Ngày vào làm"), fieldtype: "Date", reqd: 1 },
				{ fieldname: "designation", label: __("Chức danh"), fieldtype: "Link", options: "Designation" },
				{ fieldname: "department", label: __("Bộ phận"), fieldtype: "Link", options: "Department" },
				{ fieldname: "reason", label: __("Căn cứ quyết định"), fieldtype: "Small Text" },
			], "offer"), GROUP);
		}
		if (inStep(STEPS[5])) {
			frm.add_custom_button(__("Hoàn tất và bàn giao onboarding"), () => dialog(__("Kết quả và lưu vết (bước 6)"), [
				{ fieldname: "confirm", label: __("Tạo việc bàn giao Employee Onboarding cho HR"), fieldtype: "Check", default: 1, reqd: 1 },
			], "complete"), GROUP);
		}
		if (!inStep("Từ chối", "Talent Pool", "6. Kết quả và lưu vết")) {
			frm.add_custom_button(__("Từ chối"), () => dialog(__("Kết thúc hồ sơ"), [
				{ fieldname: "reason", label: __("Lý do"), fieldtype: "Small Text", reqd: 1 },
			], "reject"), GROUP);
		}
		frm.add_custom_button(__("Chuyển talent pool"), () => dialog(__("Lưu vào talent pool"), [
			{ fieldname: "reason", label: __("Lý do"), fieldtype: "Small Text", reqd: 1 },
		], "talent"), GROUP);
	},
});
