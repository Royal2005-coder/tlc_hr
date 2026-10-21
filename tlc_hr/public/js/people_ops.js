/* Standard Frappe forms remain the record and workflow surface. */
(() => {
  const call = (frm, method) => frappe.call({
    method: `tlc_hr.interface.people_ops.${method}`,
    type: "POST", args: {name: frm.doc.name}, freeze: true,
    callback: () => frm.reload_doc()
  });
  frappe.ui.form.on("Asset Movement", {
    refresh(frm) {
      if (!frm.is_new() && frm.doc.docstatus === 0) {
        frm.add_custom_button(__("Xác nhận bàn giao"), () => call(frm, "receipt"));
      }
    }
  });
  frappe.ui.form.on("TLC People Ops Acknowledgment", {
    refresh(frm) {
      if (!frm.is_new() && !frm.doc.acknowledged_at) {
        frm.add_custom_button(__("Tôi đã đọc đúng phiên bản"), () => call(frm, "acknowledge"));
      }
    }
  });
})();
