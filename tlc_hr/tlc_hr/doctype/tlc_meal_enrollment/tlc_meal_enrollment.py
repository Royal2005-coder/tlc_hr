from frappe.model.document import Document
from tlc_hr.interface import services, survey


class TLCMealEnrollment(Document):
    def validate(self):
        services.validate(self)

    def on_update(self):
        services.on_update(self)
