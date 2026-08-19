app_name = "quickinsights"
app_title = "QuickInsights"
app_publisher = "TechunisonSoftware"
app_description = "AI-powered chat-with-your-data assistant, integrating the existing QuickInsights FastAPI/RAG backend into Frappe"
app_email = "Aswin@techunison.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page. This is
# the direct "Frappe Desktop -> QuickInsights -> full-screen React app"
# entry point: route points straight at the website page below, not at any
# Desk page/workspace, so clicking this tile never goes through Desk's
# header/sidebar/breadcrumb chrome at all.
add_to_apps_screen = [
	{
		"name": "quickinsights",
		"logo": None,
		"title": "QuickInsights",
		"route": "/quickinsights",
	}
]

# Includes in <head>
# ------------------

# Loaded on every Desk page. Deliberately just the tiny bootstrap script,
# NOT the widget bundle itself -- the bootstrap decides (via
# quickinsights.api.widget_status) whether to lazy-load the real widget at
# all, so a site/user with nothing usable never pays for that JS/CSS. See
# public/js/widget_bootstrap.js.
app_include_js = "/assets/quickinsights/js/widget_bootstrap.js"

# after_install / before_uninstall
# ------------------
after_install = "quickinsights.install.after_install"
before_uninstall = "quickinsights.install.before_uninstall"

# The "QuickInsights" landing Workspace lives at
# quickinsights/workspace/quickinsights/quickinsights.json -- Workspace is a
# standard module-scoped entity (synced the same way as Page/DocType/Report
# on every `bench migrate`), NOT a fixture. A fixtures-based Workspace was
# tried first and got deleted by Frappe's own remove_orphan_entities() on
# the very next migrate -- that cleanup step only recognizes public
# workspaces that exist as a file under a "workspace/" module folder,
# exactly like this one now does. Its shortcuts, and the apps-screen tile
# above, all point at the website page below -- not at any Desk Page -- so
# every entry point lands on the full-viewport React app.

# The React app itself owns everything under /quickinsights, including its
# own client-side sub-routes (/quickinsights/chat, /quickinsights/reports,
# ...) -- a full browser navigation/reload to any of those has to hit this
# same controller (www/quickinsights.py) for the SPA to mount correctly, so
# this mirrors the exact mechanism Frappe uses for its own Desk routes (see
# frappe/hooks.py: {"from_route": "/app/<path:app_path>", "to_route": "app"}
# on v15, "/desk/<path:app_path>" -> "desk" on v16).
website_route_rules = [
	{"from_route": "/quickinsights/<path:app_path>", "to_route": "quickinsights"},
]

# include js, css files in header of web template
# web_include_css = "/assets/quickinsights/css/quickinsights.css"
# web_include_js = "/assets/quickinsights/js/quickinsights.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "quickinsights/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "quickinsights/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "quickinsights.utils.jinja_methods",
# 	"filters": "quickinsights.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "quickinsights.install.before_install"
# after_install = "quickinsights.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "quickinsights.uninstall.before_uninstall"
# after_uninstall = "quickinsights.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "quickinsights.utils.before_app_install"
# after_app_install = "quickinsights.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "quickinsights.utils.before_app_uninstall"
# after_app_uninstall = "quickinsights.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "quickinsights.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"quickinsights.tasks.all"
# 	],
# 	"daily": [
# 		"quickinsights.tasks.daily"
# 	],
# 	"hourly": [
# 		"quickinsights.tasks.hourly"
# 	],
# 	"weekly": [
# 		"quickinsights.tasks.weekly"
# 	],
# 	"monthly": [
# 		"quickinsights.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "quickinsights.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "quickinsights.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "quickinsights.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["quickinsights.utils.before_request"]
# after_request = ["quickinsights.utils.after_request"]

# Job Events
# ----------
# before_job = ["quickinsights.utils.before_job"]
# after_job = ["quickinsights.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"quickinsights.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

