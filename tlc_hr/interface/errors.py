"""Domain errors at the edge: a broken rule becomes the Frappe error the desk and the API show."""

from contextlib import contextmanager
import re

import frappe
from pydantic import ValidationError as ContractValidationError

from tlc_hr.domain.shared import DomainError, NotAllowed


@contextmanager
def domain_errors():
    try:
        yield
    except ContractValidationError as exc:
        # Custom validator messages and inputs may contain private values; expose locations and stable error types only.
        details = []
        for error in exc.errors(include_url=False, include_context=False, include_input=False)[:20]:
            location = ".".join(str(part) if isinstance(part, int) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", str(part))
                                else "?" for part in error["loc"]) or "command"
            kind = re.sub(r"[^a-z0-9_]", "", error["type"])[:64]
            details.append(f"{location}: {kind}")
        frappe.throw("Dữ liệu đầu vào không hợp lệ: " + "; ".join(details), frappe.ValidationError)
    except NotAllowed as exc:
        frappe.throw(exc.message, frappe.PermissionError, title=exc.title or None)
    except DomainError as exc:
        frappe.throw(exc.message, title=exc.title or None)
