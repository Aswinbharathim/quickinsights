# Copyright (c) 2026, TechunisonSoftware and contributors
# For license information, please see license.txt
"""Install/uninstall hooks. Deliberately minimal: the only Frappe-side state
this app owns is the single QuickInsights Settings doctype -- everything
else (connections, reports, chat history, training data) lives entirely
inside the FastAPI deployment's own metadata database, governed by its own
Alembic migrations, and is intentionally never touched from here. See the
integration architecture doc's migration/install/uninstall section for why
that boundary matters: an uninstall on one Frappe site must never be able
to reach across into a FastAPI backend that may be shared, or simply
outlive this app's install/uninstall lifecycle on this particular site.
"""
import secrets

import frappe


def after_install():
	"""Pre-generate a strong signing secret so the very first token this
	site would ever mint is already secure, without forcing an admin to
	fill in every field before `bench install-app` can finish. Deliberately
	bypasses the `fastapi_base_url` mandatory check here (ignore_mandatory)
	-- that field genuinely can't have a sane default, and is meant to be
	filled in by a System Manager right after install."""
	settings = frappe.get_single("QuickInsights Settings")
	if not settings.get_password("signing_secret", raise_exception=False):
		settings.signing_secret = secrets.token_urlsafe(32)
	settings.flags.ignore_mandatory = True
	settings.save(ignore_permissions=True)
	frappe.db.commit()


def before_uninstall():
	"""Intentionally does nothing beyond what Frappe's own uninstall
	machinery already does (deleting this app's one doctype's data and its
	hook registrations). Nothing here ever deletes anything in FastAPI's
	metadata database or a connected user database -- that data isn't
	owned by this Frappe site and this hook must never be able to reach it.
	"""
	pass
