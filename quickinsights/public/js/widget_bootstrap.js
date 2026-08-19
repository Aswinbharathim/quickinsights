/**
 * Loaded on every Desk page via hooks.py's app_include_js. Deliberately
 * tiny (no React, no widget UI logic here at all) -- its only job is:
 *   1. Ask Frappe whether the widget should exist at all for this
 *      user/site right now (quickinsights.api.widget_status).
 *   2. If yes, lazy-load the actual widget bundle -- so a site with
 *      QuickInsights disabled, or a user with nothing usable yet, never
 *      pays for the widget's JS/CSS at all.
 *   3. Mint the signed identity token (quickinsights.api.get_identity_token)
 *      and hand it + a refresh function to the widget bundle via a small
 *      global -- this file never touches chat UI, and the widget bundle
 *      never talks to Frappe directly except through this bridge.
 *
 * Never interferes with Desk's own navigation: this only ever adds one
 * fixed-position DOM node once, it doesn't hook into routing at all.
 */
(function () {
	"use strict";

	if (window.__quickinsightsWidgetBootstrapped) return;
	window.__quickinsightsWidgetBootstrapped = true;

	function whenFrappeReady(cb) {
		if (window.frappe && frappe.call && frappe.session && frappe.session.user) {
			cb();
		} else {
			setTimeout(function () {
				whenFrappeReady(cb);
			}, 150);
		}
	}

	function loadScript(src) {
		return new Promise(function (resolve, reject) {
			var s = document.createElement("script");
			s.src = src;
			s.onload = resolve;
			s.onerror = reject;
			document.head.appendChild(s);
		});
	}

	// The full dashboard now lives at the plain website route /quickinsights
	// (see quickinsights/www/quickinsights.py) instead of a Desk page, so
	// this is no longer sensitive to Frappe's Desk URL prefix (/app/... on
	// v15, /desk/... on v16) at all -- one constant works on both.
	function resolveDashboardBasePath() {
		return "/quickinsights";
	}

	function loadStyle(href) {
		var l = document.createElement("link");
		l.rel = "stylesheet";
		l.href = href;
		document.head.appendChild(l);
	}

	// Cached in closure, not on window -- only this bootstrap and the
	// function it hands to the widget bundle ever see a raw token.
	var cachedToken = null;
	var cachedExpiryMs = 0;

	function fetchIdentity() {
		return new Promise(function (resolve, reject) {
			frappe.call({
				method: "quickinsights.api.get_identity_token",
				callback: function (r) {
					if (r && r.message && r.message.token) {
						cachedToken = r.message.token;
						cachedExpiryMs = Date.now() + r.message.expires_in * 1000;
						resolve(r.message);
					} else {
						reject(new Error("No token in response"));
					}
				},
				error: reject,
			});
		});
	}

	// The widget bundle calls this before every FastAPI request instead of
	// holding a token itself -- refreshes automatically once within 60s of
	// expiry, so a long-open widget session never silently starts sending
	// an expired token.
	function getToken() {
		if (cachedToken && Date.now() < cachedExpiryMs - 60000) {
			return Promise.resolve(cachedToken);
		}
		return fetchIdentity().then(function (identity) {
			return identity.token;
		});
	}

	whenFrappeReady(function () {
		if (frappe.session.user === "Guest") return;

		frappe.call({
			method: "quickinsights.api.widget_status",
			callback: function (r) {
				if (!r || !r.message || !r.message.usable) return;

				fetchIdentity()
					.then(function (identity) {
						// Exact shape frontend/src/lib/runtime-config.ts reads --
						// this must be set BEFORE widget.js's own module graph
						// evaluates (which reads it once, at import time), which
						// is guaranteed here since we only insert that <script>
						// tag after this assignment completes.
						window.__QUICKINSIGHTS_CONFIG__ = {
							getToken: getToken,
							fastApiBaseUrl: identity.fastapi_base_url,
							basePath: resolveDashboardBasePath(),
						};
						loadStyle("/assets/quickinsights/dist-widget/widget.css");
						return loadScript("/assets/quickinsights/dist-widget/widget.js");
					})
					.catch(function (e) {
						console.error("[QuickInsights] widget failed to load", e);
					});
			},
			error: function (e) {
				console.error("[QuickInsights] widget status check failed", e);
			},
		});
	});
})();
