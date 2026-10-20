"""TLC People page /tlc/me (controller in tlc_hr.portal.pages)."""

from tlc_hr.portal.pages import me

no_cache = 1


def get_context(context):
    me(context)
