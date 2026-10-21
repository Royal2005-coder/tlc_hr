frappe.ui.form.on("TLC Room Reservation", {
  refresh(frm) {
    frm.add_custom_button(__("Kiểm tra lịch phòng"), () => {
      if (!frm.doc.room || !frm.doc.starts_at || !frm.doc.ends_at) {frappe.msgprint(__("Chọn phòng và khoảng giờ trước")); return;}
      frappe.call({method: "tlc_hr.interface.services.room_availability", args: {room: frm.doc.room, starts_at: frm.doc.starts_at, ends_at: frm.doc.ends_at}, callback(r) {
        if (!r.message) return;
        frappe.msgprint(r.message.busy.length ? __("Đã có lịch phòng trong khoảng này") : __("Hiện chưa có lịch trùng. Hệ thống kiểm tra lại khi lưu."));
      }});
    });
    if (!frm.is_new()) frm.add_custom_button(__("Xuất iCalendar (không đồng bộ Outlook)"), () => {
      window.open("/api/method/tlc_hr.interface.services.export_calendar?name=" + encodeURIComponent(frm.doc.name));
    });
  }
});
