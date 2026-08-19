# Copyright (c) 2026, TechunisonSoftware and contributors
# For license information, please see license.txt
"""Full-viewport entrypoint for QuickInsights inside Frappe.

Unlike the old Desk `Page` (frappe.ui.make_app_page), a website page like
this one renders its OWN bare HTML document -- see quickinsights.html --
instead of being laid out inside Desk's page/header/sidebar/breadcrumb
chrome. Frappe's job here is exactly "entry point + authentication": check
the session is real, mint the same signed identity token the old Desk page
minted, then hand the SAME unchanged standalone React build (frontend/dist,
copied verbatim into public/dist/ as quickinsights.js/.css) the entire
browser viewport. Nothing about the React UI, its routing, or the FastAPI
backend it talks to is touched by this file.

Nested React routes (e.g. /quickinsights/chat) are served by this exact
same controller via the `website_route_rules` catch-all in hooks.py -- the
identical mechanism Frappe itself uses to serve every Desk sub-route
through one controller (see frappe/hooks.py's own
`{"from_route": "/app/<path:app_path>", "to_route": "app"}`).
"""
import frappe
from frappe import _

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/quickinsights"
		raise frappe.Redirect

	from quickinsights.api import get_identity_token

	try:
		identity = get_identity_token()
		# frappe.as_json output is safe to drop into a <script> block as-is
		# except for a literal "</script>" inside a string value (e.g. a
		# role or user_name) breaking out of the tag early -- escape that
		# one sequence defensively even though nothing here is user-supplied
		# HTML today.
		context.qi_config = frappe.as_json(identity).replace("</", "<\\/")
		context.qi_error = None
	except Exception as e:
		context.qi_config = "null"
		context.qi_error = str(e)

	context.no_cache = 1
	return context
