"""Tests for the Frappe identity bridge (app/frappe_auth.py). These are the
security-critical properties from the integration architecture doc's
security-analysis section: identity/role/site claims are trusted only from
a signature-verified token, standalone (no-secret-configured) mode is
completely unaffected, and every tamper/expiry/malformed case fails
closed."""
import time

import jwt
import pytest

from app import frappe_auth


def _mint(secret, **overrides):
    payload = {
        "site": "hospital.local",
        "user": "doctor@a2bhospital.com",
        "user_name": "Dr. Test",
        "roles": ["Physician"],
        "allowed_tables": ["tabDoctor", "tabAppointment"],
        "row_filters": {"tabDoctor": {"department": ["Cardiology"]}},
        "exp": int(time.time()) + 900,
    }
    payload.update(overrides)
    return jwt.encode(payload, secret, algorithm="HS256")


@pytest.fixture
def secret(monkeypatch):
    s = "test-secret-at-least-32-bytes-long!!"
    monkeypatch.setattr(frappe_auth, "QUICKINSIGHTS_SIGNING_SECRETS", [s])
    return s


def test_valid_token_round_trips(secret):
    token = _mint(secret)
    identity = frappe_auth.verify_token(token)
    assert identity.site == "hospital.local"
    assert identity.user == "doctor@a2bhospital.com"
    assert identity.allowed_tables == ["tabDoctor", "tabAppointment"]
    assert identity.row_filters == {"tabDoctor": {"department": ["Cardiology"]}}


def test_expired_token_rejected(secret):
    token = _mint(secret, exp=int(time.time()) - 10)
    with pytest.raises(jwt.ExpiredSignatureError):
        frappe_auth.verify_token(token)


def test_tampered_signature_rejected(secret):
    token = jwt.encode(
        {"site": "x", "user": "y", "user_name": "y", "exp": int(time.time()) + 900},
        "a-different-attacker-controlled-secret",
        algorithm="HS256",
    )
    with pytest.raises(jwt.PyJWTError):
        frappe_auth.verify_token(token)


def test_missing_required_claim_rejected(secret):
    token = jwt.encode({"user": "y", "exp": int(time.time()) + 900}, secret, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        frappe_auth.verify_token(token)


def test_secret_rotation_accepts_old_and_new(monkeypatch):
    old_secret = "old-secret-at-least-32-bytes-long!!"
    new_secret = "new-secret-at-least-32-bytes-long!!"
    monkeypatch.setattr(frappe_auth, "QUICKINSIGHTS_SIGNING_SECRETS", [old_secret, new_secret])
    token_old = _mint(old_secret)
    token_new = _mint(new_secret)
    assert frappe_auth.verify_token(token_old).user == "doctor@a2bhospital.com"
    assert frappe_auth.verify_token(token_new).user == "doctor@a2bhospital.com"


def test_get_identity_returns_none_with_no_header(secret):
    assert frappe_auth.get_identity(None) is None


def test_get_identity_returns_none_when_no_secret_configured_at_all(monkeypatch):
    monkeypatch.setattr(frappe_auth, "QUICKINSIGHTS_SIGNING_SECRETS", [])
    # Standalone QuickInsights: even a present Authorization header must be
    # ignored entirely when this deployment has no signing secret configured
    # -- this is what keeps standalone mode from ever accidentally requiring
    # a token.
    assert frappe_auth.get_identity("Bearer whatever") is None


def test_get_identity_rejects_present_but_invalid_token(secret):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        frappe_auth.get_identity("Bearer not-a-real-token")
    assert exc_info.value.status_code == 401


def test_get_identity_rejects_expired_token_with_401(secret):
    from fastapi import HTTPException

    token = _mint(secret, exp=int(time.time()) - 10)
    with pytest.raises(HTTPException) as exc_info:
        frappe_auth.get_identity(f"Bearer {token}")
    assert exc_info.value.status_code == 401


def test_get_identity_accepts_valid_token(secret):
    token = _mint(secret)
    identity = frappe_auth.get_identity(f"Bearer {token}")
    assert identity is not None
    assert identity.user == "doctor@a2bhospital.com"
