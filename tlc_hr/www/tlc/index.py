"""TLC People page /tlc (controller in tlc_hr.portal.pages)."""

from tlc_hr.portal.pages import home

no_cache = 1


def get_context(context):
    home(context)
