# Copyright (c) 2026, TechunisonSoftware and contributors
# For license information, please see license.txt

import secrets

import frappe
from frappe.model.document import Document


class QuickInsightsSettings(Document):
	"""Single doctype holding this site's QuickInsights integration config.
	Only System Manager can read/write it (see the doctype's permissions) --
	`signing_secret` in particular must never reach the browser: it's a
	Password fieldtype (masked in the Desk UI and excluded from ordinary
	API reads by Frappe itself), and the only code that ever calls
	`get_password("signing_secret")` is quickinsights.api.get_identity_token,
	running server-side.
	"""

	def validate(self):
		# A blank secret would silently make every identity token
		# unverifiable (or, worse, tempt someone into typing something
		# memorable/guessable) -- generate a strong one automatically
		# instead of erroring, the first time this is saved.
		if not self.get_password("signing_secret", raise_exception=False):
			self.signing_secret = secrets.token_urlsafe(32)

		if self.fastapi_base_url:
			self.fastapi_base_url = self.fastapi_base_url.rstrip("/")
