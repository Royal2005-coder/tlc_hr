"""TLC People page /tlc/team (controller in tlc_hr.portal.pages)."""

from tlc_hr.portal.pages import team

no_cache = 1


def get_context(context):
    team(context)
