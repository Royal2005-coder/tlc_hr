from frappe.model.document import Document
from tlc_hr.interface import services, survey


class TLCSurveyCampaign(Document):
    def validate(self):
        survey.validate(self)

    def on_update(self):
        survey.on_update(self)
