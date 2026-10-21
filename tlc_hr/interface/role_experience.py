"""Frappe permission hook entry points for the native W8 workforce surfaces."""

from tlc_hr.infrastructure.frappe import role_experience as scope


def query_conditions(user=None, doctype=None):
    return scope.query_conditions(user=user, doctype=doctype)


def has_permission(doc, user=None, permission_type=None, ptype=None):
    return scope.has_permission(doc, user=user, permission_type=permission_type, ptype=ptype)


def employee_query(user=None):
    return scope.query_conditions(user=user, doctype="Employee")


def attendance_query(user=None):
    return scope.query_conditions(user=user, doctype="Attendance")


def shift_assignment_query(user=None):
    return scope.query_conditions(user=user, doctype="Shift Assignment")


def checkin_query(user=None):
    return scope.query_conditions(user=user, doctype="Employee Checkin")


def attendance_request_query(user=None):
    return scope.query_conditions(user=user, doctype="Attendance Request")


def leave_query(user=None):
    return scope.query_conditions(user=user, doctype="Leave Application")
