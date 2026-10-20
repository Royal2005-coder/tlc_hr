"""TLC People page /tlc/people (controller in tlc_hr.portal.pages)."""

from tlc_hr.portal.pages import people

no_cache = 1


def get_context(context):
    people(context)
