"""Use cases over small persistence ports."""
from datetime import date
from typing import Protocol
from tlc_hr.domain.people_ops import reminder_band, training_due


class PeopleOpsRepository(Protocol):
    def mandatory_training(self): ...
    def matching_employees(self, requirement): ...
    def latest_completion(self, employee, program): ...
    def ensure_training(self, employee, requirement): ...
    def certificates(self): ...
    def remind(self, doctype, name, employee, message, band): ...
    def pending_acknowledgments(self): ...
    def pending_health(self): ...


class PeopleOpsService:
    def __init__(self, repository: PeopleOpsRepository):
        self.repository = repository

    def daily(self, today: date):
        repo = self.repository
        for requirement in repo.mandatory_training():
            for employee in repo.matching_employees(requirement):
                completed = repo.latest_completion(employee, requirement.training_program)
                if training_due(completed, requirement.recurrence_days, today):
                    name = repo.ensure_training(employee, requirement)
                    repo.remind("TLC People Ops Certificate", name, employee, "Đào tạo bắt buộc chưa hoàn thành", today.isoformat())
        for certificate in repo.certificates():
            band = reminder_band(certificate.expires_on, today)
            if band:
                repo.remind("TLC People Ops Certificate", certificate.name, certificate.employee, "Chứng chỉ sắp/đã hết hạn: " + band, band)
        for ack in repo.pending_acknowledgments():
            repo.remind("TLC People Ops Acknowledgment", ack.name, ack.employee, "Chính sách cần xác nhận đã đọc", today.isoformat())
        for appointment in repo.pending_health():
            repo.remind("TLC People Ops Health Appointment", appointment.name, appointment.employee, "Nhắc lịch khám sức khỏe", today.isoformat())
