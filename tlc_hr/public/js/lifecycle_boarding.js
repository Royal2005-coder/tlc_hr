/* Native Desk action; the server validates every completion gate again. */
for (const doctype of ["Employee Onboarding", "Employee Separation"]) {
  frappe.ui.form.on(doctype, {
    refresh(frm) {
      if (frm.doc.docstatus !== 1 || frm.doc.custom_tlc_completed_by) return;
      if (!frappe.user_roles.some(role => ["TLC HR Lead", "TLC HR Officer", "System Manager"].includes(role))) return;
      frm.add_custom_button(__("Hoàn tất có kiểm tra"), () => {
        frappe.call({
          method: "tlc_hr.interface.lifecycle.complete_boarding",
          args: {doctype: frm.doctype, name: frm.doc.name},
          freeze: true,
          callback: () => frm.reload_doc(),
        });
      });
    },
  });
}
