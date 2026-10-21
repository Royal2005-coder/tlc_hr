from frappe.model.document import Document
from tlc_hr.interface.people_ops import validate_gap, after_gap_save


class TLCPeopleOpsCertificate(Document):
    def validate(self):
        validate_gap(self)

    def on_update(self):
        after_gap_save(self)
