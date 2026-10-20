"""TLC People page /tlc/leave (controller in tlc_hr.portal.pages)."""

from tlc_hr.portal.pages import leave

no_cache = 1


def get_context(context):
    leave(context)
