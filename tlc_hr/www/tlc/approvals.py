"""TLC People page /tlc/approvals (controller in tlc_hr.portal.pages)."""

from tlc_hr.portal.pages import approvals

no_cache = 1


def get_context(context):
    approvals(context)
