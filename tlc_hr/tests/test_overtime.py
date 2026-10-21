"""Overtime (TLC Tăng ca) on the seeded demo: the head proposes, the worker consents, the director approves; Labour Code limits;
the Overtime Slip pays only approved hours. Ported from the seed scenario overtime_consent_and_limit."""

import datetime as dt

import frappe
from frappe.model.workflow import apply_workflow
from frappe.tests import IntegrationTestCase

from tlc_hr.domain import overtime as labour
from tlc_hr.interface.overtime import cap_overtime_slip

WORKER, OTHER_WORKER, HEAD, OTHER_HEAD, DIRECTOR = (
    "binh@demo.example", "tai@demo.example", "hung@demo.example", "nm2@demo.example", "thanh@demo.example")


def weekday_in(month_offset, nth=0, weekday=0):
    """The nth given weekday (0 = Monday) of a month after this one: far from today's data, inside the holiday lists."""
    first = (dt.date.today().replace(day=1) + dt.timedelta(days=32 * month_offset)).replace(day=1)
    day = first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * nth)
    return day


class TestOvertimeRequest(IntegrationTestCase):
    def setUp(self):
        self.worker = frappe.db.get_value("Employee", {"user_id": WORKER})
        if not self.worker or not frappe.db.exists("Workflow", "TLC Tăng ca"):
            self.skipTest("TLC demo seed not loaded")
        self.day = weekday_in(1, 1)

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.rollback()

    def propose(self, day=None, start="18:00:00", end="21:00:00", user=HEAD, employee=None, send=True):
        frappe.set_user(user)
        doc = frappe.get_doc({"doctype": "TLC Overtime Request", "employee": employee or self.worker, "ot_date": day or self.day,
                              "from_time": start, "to_time": end, "reason": "Kiểm kê kho cuối quý"}).insert()
        if send:
            apply_workflow(doc, "Đề nghị")
            doc.reload()
        return doc

    def act(self, doc, action, user, reason=None):
        frappe.set_user(user)
        doc = frappe.get_doc(doc.doctype, doc.name)
        if reason:
            doc.db_set("tlc_reject_reason", reason)
        apply_workflow(doc, action)
        doc.reload()
        return doc

    def test_consent_then_director(self):
        doc = self.propose()
        self.assertEqual((doc.workflow_state, doc.hours, doc.day_type), ("Chờ người lao động đồng ý", 3, labour.WORKING_DAY))
        self.assertTrue(frappe.db.exists("Notification Log", {"for_user": WORKER, "document_name": doc.name}))
        with self.assertRaises(frappe.ValidationError):
            self.act(doc, "Đồng ý", HEAD)  # the head cannot consent for the worker
        with self.assertRaises(frappe.ValidationError):
            self.act(doc, "Duyệt", DIRECTOR)  # the director waits for the worker
        doc = self.act(doc, "Đồng ý", WORKER)
        self.assertEqual(doc.workflow_state, "Chờ giám đốc duyệt")
        self.assertTrue(doc.consent_at)
        doc = self.act(doc, "Duyệt", DIRECTOR)
        self.assertEqual((doc.workflow_state, doc.docstatus), ("Đã duyệt", 1))

    def test_worker_refuses_with_reason(self):
        doc = self.propose()
        with self.assertRaises(frappe.ValidationError):
            self.act(doc, "Từ chối", WORKER)
        frappe.db.rollback()
        doc = self.propose()
        doc = self.act(doc, "Từ chối", WORKER, reason="Tối đó tôi có việc gia đình")
        self.assertEqual((doc.workflow_state, doc.tlc_rejected_stage, doc.docstatus), ("Từ chối", "Chờ người lao động đồng ý", 0))

    def test_only_own_people(self):
        with self.assertRaises(frappe.PermissionError):
            self.propose(user=OTHER_HEAD)
        frappe.set_user(OTHER_HEAD)
        self.assertFalse(frappe.get_list("TLC Overtime Request", filters={"employee": self.worker}))

    def test_sent_request_is_fixed(self):
        doc = self.propose()
        frappe.set_user(WORKER)
        doc = frappe.get_doc(doc.doctype, doc.name)
        doc.to_time = "20:00:00"
        with self.assertRaises(frappe.ValidationError):
            doc.save()

    def test_daily_cap(self):
        with self.assertRaises(frappe.ValidationError):
            self.propose(start="17:00:00", end="21:30:00", send=False)  # 4.5 h on a working day
        sunday = weekday_in(1, 1, weekday=6)
        doc = self.propose(day=sunday, start="07:00:00", end="19:00:00", send=False)
        self.assertEqual((doc.day_type, doc.hours), (labour.REST_DAY, 12))
        self.propose(start="17:00:00", end="19:00:00", send=False)
        with self.assertRaises(frappe.ValidationError):
            self.propose(start="19:00:00", end="21:30:00", send=False)  # 2 + 2.5 h on the same working day

    def test_month_cap_counts_pending_requests(self):
        for week in range(2):
            for weekday in range(5):
                self.propose(day=weekday_in(2, week, weekday), start="17:00:00", end="21:00:00", send=False)  # 10 x 4 h = 40 h
        with self.assertRaises(frappe.ValidationError) as caught:
            self.propose(day=weekday_in(2, 2, 0), start="17:00:00", end="18:00:00", send=False)
        self.assertIn("40", str(caught.exception))
        other = frappe.db.get_value("Employee", {"user_id": OTHER_WORKER})
        self.propose(day=weekday_in(2, 2, 0), start="17:00:00", end="18:00:00", employee=other, send=False)  # per worker

    def test_overtime_slip_pays_approved_hours_only(self):
        doc = self.act(self.act(self.propose(), "Đồng ý", WORKER), "Duyệt", DIRECTOR)
        frappe.set_user("Administrator")
        unapproved = self.day + dt.timedelta(days=1)
        slip = frappe.new_doc("Overtime Slip")
        slip.update({"employee": self.worker, "start_date": self.day.replace(day=1), "end_date": self.day + dt.timedelta(days=5)})
        for day, hours in ((self.day, 4.5), (unapproved, 2)):
            slip.append("overtime_details", {"date": day, "overtime_type": "TLC Tăng ca", "overtime_duration": hours, "standard_working_hours": 8})
        cap_overtime_slip(slip)
        self.assertEqual([(str(r.date), r.overtime_duration) for r in slip.overtime_details], [(str(self.day), doc.hours)])
        self.assertEqual(slip.total_overtime_duration, 3)
