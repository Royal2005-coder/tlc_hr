"""Shifts and GPS check-in on the seeded TLC demo: inside the work site accepted, outside refused, outside any shift refused."""

import datetime as dt

import frappe
from frappe.tests import IntegrationTestCase

from tlc_hr.setup.attendance import sites

WORKER = "binh@demo.example"  # night shift 22:00-06:00 at Nhà máy 1


def next_weekday_at(hour, minute=5):
    day = dt.date.today() + dt.timedelta(days=21)
    while day.weekday() >= 5:
        day += dt.timedelta(days=1)
    return dt.datetime.combine(day, dt.time(hour, minute))


class TestCheckin(IntegrationTestCase):
    def setUp(self):
        self.employee = frappe.db.get_value("Employee", {"user_id": WORKER})
        if not self.employee or not frappe.db.exists("Shift Type", "TLC Ca đêm"):
            self.skipTest("TLC demo seed with shifts not loaded")
        self.lat, self.lon, _ = sites()["Nhà máy 1"]

    def tearDown(self):
        frappe.db.rollback()

    def checkin(self, when, lat, lon):
        return frappe.get_doc({"doctype": "Employee Checkin", "employee": self.employee, "log_type": "IN", "time": when,
                               "latitude": lat, "longitude": lon}).insert()

    def test_inside_the_factory_in_the_night_shift(self):
        doc = self.checkin(next_weekday_at(21, 55), self.lat + 0.0003, self.lon)  # about 33 m from the gate
        self.assertEqual(doc.shift, "TLC Ca đêm")

    def test_far_from_the_factory_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self.checkin(next_weekday_at(21, 55), self.lat + 0.05, self.lon)  # about 5.5 km away

    def test_outside_any_shift_is_refused(self):
        with self.assertRaises(frappe.ValidationError):
            self.checkin(next_weekday_at(13, 0), self.lat, self.lon)

    def test_duplicate_punch_is_rejected_by_native_hrms_controller(self):
        at = next_weekday_at(21, 55)
        self.checkin(at, self.lat, self.lon)
        with self.assertRaises(frappe.ValidationError):
            self.checkin(at, self.lat, self.lon)

    def test_every_active_employee_has_a_located_shift(self):
        missing = frappe.db.sql("""select e.name from `tabEmployee` e where e.status = 'Active' and not exists (
            select 1 from `tabShift Assignment` s where s.employee = e.name and s.docstatus = 1 and s.status = 'Active'
            and ifnull(s.shift_location, '') != '')""")
        self.assertEqual(missing, ())
