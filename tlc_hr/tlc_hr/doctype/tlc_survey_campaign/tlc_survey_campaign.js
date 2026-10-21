frappe.ui.form.on("TLC Survey Campaign", {
  refresh(frm) {
    if (frm.is_new()) return;
    if (frm.doc.status === "Open") {
      frm.add_custom_button(__("Trả lời ẩn danh"), () => {
        const qs = frm.doc.questions.filter(q => !q.hidden);
        const fields = [{fieldtype: "HTML", options: "<p>Ẩn danh thật. Chỉ lưu tổng theo bộ phận, không lưu từng phiếu. Không nhập dữ liệu nhận dạng.</p>"},
          ...qs.map((q, i) => ({fieldname: "q" + i, fieldtype: "Select", label: q.label, options: "\n" + q.options, reqd: 1}))];
        const dialog = new frappe.ui.Dialog({title: __("Phản hồi ẩn danh"), fields,
          primary_action_label: __("Gửi phản hồi"),
          primary_action(values) {
            const answers = Object.fromEntries(qs.map((q, i) => [q.question_key, values["q" + i]]));
            frappe.call({method: "tlc_hr.interface.survey.submit_anonymous", type: "POST", args: {campaign: frm.doc.name, answers},
              freeze: true, callback(r) {if (r.message?.submitted) {dialog.hide(); frappe.msgprint(__("Đã ghi nhận phản hồi ẩn danh"));}}});
          }});
        dialog.show();
      });
    }
    const isHR = ["TLC HR Lead", "TLC HR Officer", "System Manager"].some(r => frappe.user_roles.includes(r));
    if (isHR && frm.doc.status !== "Draft") {
      frm.add_custom_button(__("Tạo phiên bản mới"), () => frappe.call({method: "tlc_hr.interface.survey.new_version", type: "POST", args: {campaign: frm.doc.name},
        callback(r) {if (r.message) frappe.set_route("Form", "TLC Survey Campaign", r.message);}}));
    }
    if (["Closed", "Archived"].includes(frm.doc.status) && (isHR || frappe.user_roles.includes("TLC Line Manager"))) {
      frm.add_custom_button(__("Kết quả theo bộ phận"), () => {
        frappe.prompt([{fieldname: "department", fieldtype: "Link", options: "Department", label: __("Bộ phận"), reqd: 1}], values => {
          frappe.call({method: "tlc_hr.interface.survey.results", args: {campaign: frm.doc.name, department: values.department}, callback(r) {
            if (!r.message) return;
            const result = r.message;
            if (result.suppressed) {frappe.msgprint(__("Chưa đủ ngưỡng công bố; không hiển thị số người hoặc câu trả lời.")); return;}
            const html = result.questions.map(q => `<h5>${frappe.utils.escape_html(q.label)}</h5><ul>` +
              Object.entries(q.counts).map(([o,n]) => `<li>${frappe.utils.escape_html(o)}: ${n}</li>`).join("") + "</ul>").join("");
            frappe.msgprint({title: __("Kết quả phiên bản ") + result.version, message: html, wide: true});
          }});
        }, __("Chọn bộ phận"));
      });
    }
  }
});
