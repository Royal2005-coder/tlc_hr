"""Organization rules; administrative hierarchy never implies approval authority."""
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from tlc_hr.domain.shared import DomainError


@dataclass(frozen=True)
class Period:
    start: date
    end: date | None = None

    def validate(self):
        if self.end and self.end < self.start:
            raise DomainError("org.period", "Ngày kết thúc phải từ ngày bắt đầu trở đi.")

    def contains(self, day):
        return self.start <= day and (self.end is None or day <= self.end)

    def overlaps(self, other):
        return self.start <= (other.end or date.max) and other.start <= (self.end or date.max)


@dataclass(frozen=True)
class Assignment:
    name: str
    employee: str
    department: str
    position: str
    period: Period
    primary: bool


def validate_assignment(candidate, existing):
    candidate.period.validate()
    for row in existing:
        if row.name == candidate.name or row.employee != candidate.employee or not row.period.overlaps(candidate.period):
            continue
        if row.position == candidate.position or (row.primary and candidate.primary):
            raise DomainError("org.assignment_overlap", "Trùng thời gian cùng vị trí hoặc hai phân công chính.")


def validate_tree(parents):
    complete = set()
    for node in parents:
        path = set()
        current = node
        while current and current not in complete:
            if current in path:
                raise DomainError("org.cycle", "Cơ cấu hoặc tuyến báo cáo có vòng lặp.")
            path.add(current)
            current = parents.get(current)
        complete.update(path)


def validate_reporting(edges):
    graph = {}
    for employee, leader in edges:
        graph.setdefault(employee, set()).add(leader)
    visiting, complete = set(), set()

    def visit(node):
        if node in visiting:
            raise DomainError("org.reporting_cycle", "Tuyến báo cáo không được tự duyệt hoặc có vòng lặp.")
        if node in complete:
            return
        visiting.add(node)
        for leader in graph.get(node, ()):
            visit(leader)
        visiting.remove(node)
        complete.add(node)

    for node in graph:
        visit(node)


def headcount(capacity, employees):
    if capacity < 0:
        raise DomainError("org.capacity", "Định biên không được âm.")
    used = len(set(employees))
    return used, max(capacity - used, 0), max(used - capacity, 0)


def mismatch(primary_department, allowed_departments, recorded_department):
    return bool(recorded_department and recorded_department not in ({primary_department} | set(allowed_departments)))


class OrganizationRepository(Protocol):
    def assignments(self, employee: str) -> list[Assignment]: ...
    def active_employees(self, position: str, day: date) -> list[str]: ...
    def approval_users(self, employee: str, department: str, day: date) -> list[str]: ...


def validate_change_shape(kind, rows):
    if not rows:
        raise DomainError("org.change_rows", "Quyết định phải có đơn vị nguồn và đích.")
    sources = {r.source_department for r in rows}
    targets = {r.target_department for r in rows}
    if kind not in {"Rename", "Reparent", "Split", "Merge"}:
        raise DomainError("org.change_kind", "Loại thay đổi cơ cấu không hợp lệ.")
    if kind != "Merge" and len(targets) != len(rows):
        raise DomainError("org.duplicate_target", "Mỗi đơn vị đích chỉ được cập nhật một lần trong quyết định.")
    if kind == "Merge" and len({(r.new_parent, r.new_title) for r in rows}) != 1:
        raise DomainError("org.merge_target", "Các dòng gộp phải có cùng đơn vị cha và tên đích.")
    if kind == "Split" and (len(sources) != 1 or len(targets) < 2):
        raise DomainError("org.split", "Tách đơn vị cần một nguồn và ít nhất hai đích.")
    if kind == "Merge" and (len(sources) < 2 or len(targets) != 1 or len(sources) != len(rows)):
        raise DomainError("org.merge", "Gộp đơn vị cần ít nhất hai nguồn khác nhau và một đích.")
