"""TLC People page /tlc/reports (controller in tlc_hr.portal.pages)."""

from tlc_hr.portal.pages import reports

no_cache = 1


def get_context(context):
    reports(context)
