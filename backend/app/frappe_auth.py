"""Bridges a Frappe-issued identity token into a trusted FastAPI request
context.

This is the ONLY place a Frappe user/role/site claim is allowed to enter
FastAPI. Every field on `Identity` below comes from a JWT signed
server-side by the QuickInsights Frappe app's `get_identity_token`
whitelisted method (never by the browser) -- see the architecture doc's
identity-flow section. FastAPI only ever verifies the signature and
expiry here; it never re-derives roles/permissions itself, and it never
trusts a client-supplied user_id/site_id/roles/scope field from a request
body or query string.

If QUICKINSIGHTS_SIGNING_SECRETS is empty (the default), get_identity()
always returns None and every route behaves exactly as it does in
standalone QuickInsights today -- this module is purely additive.
"""
import logging
from typing import Optional

import jwt
from fastapi import Header, HTTPException
from pydantic import BaseModel

from app.config import QUICKINSIGHTS_SIGNING_SECRETS

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"


class Identity(BaseModel):
    """The trusted, verified context for a Frappe-authenticated request.
    Every field here is populated only by decoding a signature-verified
    token -- never from a request body, query string, or header other than
    the Authorization header carrying that token."""

    site: str
    user: str
    user_name: str
    roles: list[str] = []
    # None = unrestricted (e.g. a System Manager, resolved as "sees
    # everything" by Frappe at mint time -- FastAPI never makes that call
    # itself). An empty list means "no tables allowed" -- a materially
    # different, much more restrictive claim, so the two are never
    # conflated.
    allowed_tables: Optional[list[str]] = None
    # {table_name: {column_name: [allowed values]}}, resolved from the
    # user's real Frappe User Permissions at mint time.
    row_filters: dict[str, dict[str, list[str]]] = {}


def verify_token(token: str) -> Identity:
    """Raises a jwt.PyJWTError subclass (invalid signature, expired,
    malformed) if the token can't be trusted. Tries every configured secret
    in turn so a secret can be rotated without a hard cutover."""
    last_error: Exception = jwt.InvalidTokenError("No signing secret configured")
    for secret in QUICKINSIGHTS_SIGNING_SECRETS:
        try:
            payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        except jwt.PyJWTError as e:
            last_error = e
            continue
        try:
            return Identity(
                site=payload["site"],
                user=payload["user"],
                user_name=payload.get("user_name", payload["user"]),
                roles=payload.get("roles", []),
                allowed_tables=payload.get("allowed_tables"),
                row_filters=payload.get("row_filters", {}),
            )
        except KeyError as e:
            raise jwt.InvalidTokenError(f"Token missing required claim: {e}") from e
    raise last_error


def get_identity(authorization: Optional[str] = Header(None)) -> Optional[Identity]:
    """FastAPI dependency. Returns None (not an error) when no Authorization
    header is present, or when no signing secret is configured for this
    deployment at all -- that's what keeps standalone QuickInsights working
    completely unauthenticated, unchanged. Once a header IS present,
    though, it must verify: a present-but-invalid token is always a 401,
    never silently downgraded to "no identity."""
    if not QUICKINSIGHTS_SIGNING_SECRETS or not authorization:
        return None
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Expected 'Authorization: Bearer <token>'.")
    token = authorization[len("Bearer "):].strip()
    try:
        return verify_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Identity token expired -- please refresh the page.")
    except jwt.PyJWTError as e:
        logger.warning("Rejected invalid identity token: %s", e)
        raise HTTPException(status_code=401, detail="Invalid identity token.")
