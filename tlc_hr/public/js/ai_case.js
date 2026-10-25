// A controlled action the assistant asked for lands here as a case: a second person releases it, and only then does
// the pipeline run. The buttons live on the case because custom doctypes get no doctype_js of their own.
frappe.ui.form.on("TLC AI Case", {
	refresh(frm) {
		if (frm.is_new()) return;
		const waiting = frm.doc.state === "Chờ duyệt";
		const mine = frm.doc.requester === frappe.session.user;
		const tone = frm.doc.state === "Đã thực hiện" ? "green" : frm.doc.state === "Từ chối" ? "red" : waiting ? "orange" : "blue";
		frm.dashboard.set_headline_alert(
			__("{0} · {1} · người đề xuất {2} · {3}", [
				frm.doc.state,
				frm.doc.tool_title || frm.doc.tool,
				frm.doc.requester,
				frm.doc.decision_by ? __("người duyệt {0}", [frm.doc.decision_by]) : __("chưa có người duyệt"),
			]),
			tone
		);

		const call = (action, reason) =>
			frappe.call({
				method: "tlc_hr.interface.agent_gateway.decide",
				type: "POST",
				args: { case: frm.doc.name, action, reason },
				freeze: true,
				freeze_message: action === "approve" ? __("Đang thực hiện yêu cầu") : __("Đang ghi lý do từ chối"),
				callback: (r) => {
					const state = r.message && r.message.state;
					frappe.show_alert({ message: __("Case {0}: {1}", [frm.doc.name, state || ""]), indicator: "green" });
					frm.reload_doc();
				},
			});

		if (waiting && !mine) {
			frm.add_custom_button(__("Phê duyệt và thực hiện"), () => {
				frappe.confirm(
					__("Thực hiện “{0}” cho {1}? Yêu cầu sẽ chạy theo đúng quy trình và ghi vào nhật ký.", [
						frm.doc.tool_title || frm.doc.tool,
						frm.doc.requester,
					]),
					() => call("approve", "")
				);
			}).addClass("btn-primary");
			frm.add_custom_button(__("Từ chối"), () => {
				frappe.prompt(
					{ fieldname: "reason", fieldtype: "Small Text", label: __("Lý do từ chối"), reqd: 1 },
					(values) => call("refuse", values.reason),
					__("Từ chối yêu cầu"),
					__("Ghi lý do")
				);
			});
		}
		if (waiting && mine) {
			frm.dashboard.set_headline_alert(
				__("{0} · {1} · đang chờ người duyệt, bạn chưa thể tự duyệt", [frm.doc.state, frm.doc.tool_title || frm.doc.tool]),
				"orange"
			);
		}
		if (frm.doc.state === "Đã thực hiện" && frm.doc.document_type && frm.doc.document_id) {
			frm.add_custom_button(__("Mở chứng từ"), () =>
				frappe.set_route("Form", frm.doc.document_type, frm.doc.document_id));
		}
		if (frm.doc.state === "Lỗi") {
			frm.add_custom_button(__("Xem lỗi"), () =>
				frappe.msgprint({ title: __("Lỗi thực hiện"), indicator: "red", message: frappe.utils.escape_html(frm.doc.result || "") }));
		}
	},
});
