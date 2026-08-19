# Copyright (c) 2026, TechunisonSoftware and contributors
# For license information, please see license.txt
"""The identity bridge between a Frappe session and FastAPI's trust
boundary (see the QuickInsights <-> Frappe integration architecture doc).

Every function here that returns identity/permission data does so using
ONLY frappe.session.user -- the caller can never supply a user, a role, a
site, or a permission scope; those are always resolved server-side from the
real, already-authenticated session. FastAPI (app/frappe_auth.py) trusts
the signature on the resulting token, never a raw claim from the browser.
"""
import time

import frappe
from frappe import _


def _resolve_scope(user: str) -> tuple[list[str], list[str] | None, dict[str, dict[str, list[str]]]]:
	"""Returns (roles, allowed_tables, row_filters) for `user`, derived
	entirely from Frappe's own Role Permissions and User Permissions.

	allowed_tables is None for an unrestricted user (System Manager, or the
	Administrator account) -- matching how Frappe itself treats that role.
	Otherwise it's every DocType this user can read at all (DocPerm
	read=1), expressed as the actual `tab<DocType>` table names FastAPI's
	generated SQL references.

	row_filters maps `tab<DocType>` -> {link_fieldname: [allowed values]}
	for every doctype the user can read that has a Link field pointing at a
	doctype the user has an active User Permission on -- e.g. a User
	Permission restricting someone to Department "Cardiology" automatically
	restricts every readable table with a `department` Link field to that
	one department, the same way Frappe's own list views/reports already
	filter for that user.
	"""
	roles = frappe.get_roles(user)
	if user == "Administrator" or "System Manager" in roles:
		return roles, None, {}

	# NOTE (Frappe v15/v16 compatibility): v15's get_doctypes_with_read()
	# takes no arguments at all; v16 added an optional `user` kwarg but
	# still defaults to the current session user when omitted. Calling it
	# with zero arguments works correctly -- and identically -- on both,
	# and is the only shape that's actually safe here anyway: this must
	# always resolve frappe.session.user, never a user this function was
	# handed some other way.
	readable_doctypes = frappe.permissions.get_doctypes_with_read()
	allowed_tables = [f"tab{d}" for d in readable_doctypes]

	row_filters: dict[str, dict[str, list[str]]] = {}
	user_permissions = frappe.permissions.get_user_permissions(user)
	if user_permissions:
		restricted_doctypes = set(user_permissions.keys())
		for doctype in readable_doctypes:
			try:
				meta = frappe.get_meta(doctype)
			except Exception:
				continue  # a readable "doctype" that isn't a real table (e.g. a report) -- nothing to filter
			for link_field in meta.get_link_fields():
				if link_field.options not in restricted_doctypes:
					continue
				allowed_values = [
					entry.get("doc")
					for entry in user_permissions[link_field.options]
					if entry.get("doc")
				]
				if allowed_values:
					row_filters.setdefault(f"tab{doctype}", {})[link_field.fieldname] = allowed_values

	return roles, allowed_tables, row_filters


@frappe.whitelist()
def get_identity_token():
	"""The ONLY endpoint that bridges a Frappe session into FastAPI. Runs
	with the caller's real, already-authenticated session -- frappe.session
	.user is never a value the caller can set. See app/frappe_auth.py on
	the FastAPI side for how the resulting token is verified: by signature
	only, never by trusting any of these claims directly."""
	if frappe.session.user == "Guest":
		frappe.throw(_("You must be logged in to use QuickInsights."), frappe.AuthenticationError)

	settings = frappe.get_single("QuickInsights Settings")
	secret = settings.get_password("signing_secret", raise_exception=False)
	if not secret or not settings.fastapi_base_url:
		frappe.throw(_("QuickInsights is not configured for this site yet -- ask a System Manager to set it up."))

	user = frappe.session.user
	roles, allowed_tables, row_filters = _resolve_scope(user)
	ttl_minutes = settings.token_ttl_minutes or 15
	now = int(time.time())

	import jwt

	token = jwt.encode(
		{
			"site": frappe.local.site,
			"user": user,
			"user_name": frappe.utils.get_fullname(user),
			"roles": roles,
			"allowed_tables": allowed_tables,
			"row_filters": row_filters,
			"iat": now,
			"exp": now + ttl_minutes * 60,
		},
		secret,
		algorithm="HS256",
	)
	return {
		"token": token,
		"expires_in": ttl_minutes * 60,
		"fastapi_base_url": settings.fastapi_base_url,
	}


@frappe.whitelist()
def widget_status():
	"""Cheap, credential-free usability probe for the floating widget. Only
	ever returns a boolean -- never a connection, a credential, or anything
	else FastAPI holds. Fails closed (widget stays hidden) on any error
	reaching FastAPI or if QuickInsights isn't configured/enabled for this
	site, rather than surface a broken chat box."""
	if frappe.session.user == "Guest":
		return {"usable": False}

	settings = frappe.get_single("QuickInsights Settings")
	if not settings.widget_enabled or not settings.fastapi_base_url:
		return {"usable": False}

	try:
		import requests

		resp = requests.get(
			f"{settings.fastapi_base_url}/api/connections",
			timeout=settings.fastapi_timeout_seconds or 15,
		)
		resp.raise_for_status()
		connections = resp.json()
		return {"usable": any(c.get("trained_table_count", 0) > 0 for c in connections)}
	except Exception:
		frappe.log_error(title="QuickInsights widget_status check failed")
		return {"usable": False}
