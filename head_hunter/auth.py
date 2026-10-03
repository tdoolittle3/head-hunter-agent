"""Who is calling: checking a Firebase sign-in token.

This is the one place an identity is decided. Everything downstream -- the
session, the profile in Firestore -- trusts the id returned here, so the check
is plain Python with no model involved (AGENTS.md rule 4) and it fails closed:
anything short of a fully valid token for the right project and the right
sign-in method is an :class:`AuthError`.

The signature check itself is ``google.auth``'s: it fetches Google's published
signing keys and verifies the token against them. Passing ``audience`` makes it
also check the token was minted for *our* project; the issuer check, which it
does not do, is ours.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

SIGN_IN_PROVIDER = "google.com"
"""The only sign-in method accepted.

Firebase will also mint tokens for anonymous, email/password and other
providers if someone switches them on in the console. Pinning the provider here
means doing so cannot quietly widen who gets in.
"""

TokenVerifier = Callable[[str, str], Mapping[str, Any]]
"""``(token, project_id) -> claims``; raises on any invalid token."""


class AuthError(Exception):
    """The caller could not be identified. The message is safe to show them."""


@dataclass(frozen=True)
class VerifiedUser:
    """A caller whose token checked out."""

    uid: str
    email: str | None
    name: str | None


def google_verifier(token: str, project_id: str) -> Mapping[str, Any]:
    """Verify signature, expiry and audience against Google's published keys."""
    return id_token.verify_firebase_token(
        token, google_requests.Request(), audience=project_id
    )


def bearer_token(authorization: str | None) -> str:
    """Pull the token out of an ``Authorization: Bearer <token>`` header."""
    if not authorization:
        raise AuthError("Sign in first: no Authorization header was sent.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("Authorization must be 'Bearer <token>'.")
    return token.strip()


def verify_user(
    authorization: str | None,
    project_id: str,
    verifier: TokenVerifier = google_verifier,
) -> VerifiedUser:
    """Return the verified caller, or raise :class:`AuthError`.

    Args:
        authorization: The raw ``Authorization`` header, or None.
        project_id: The Firebase project the token must have been issued for.
        verifier: Checks the signature. Injected so tests need no network.
    """
    token = bearer_token(authorization)
    try:
        claims = verifier(token, project_id)
    except (GoogleAuthError, ValueError) as exc:
        raise AuthError("That sign-in token is invalid or has expired.") from exc

    if claims.get("aud") != project_id:
        raise AuthError("That token was issued for a different project.")
    if claims.get("iss") != f"https://securetoken.google.com/{project_id}":
        raise AuthError("That token was not issued by Firebase for this project.")

    provider = (claims.get("firebase") or {}).get("sign_in_provider")
    if provider != SIGN_IN_PROVIDER:
        raise AuthError("Only Google sign-in is accepted.")
    if claims.get("email_verified") is not True:
        raise AuthError("Your Google account's email is not verified.")

    uid = claims.get("sub")
    if not isinstance(uid, str) or not uid:
        raise AuthError("That token does not say who you are.")

    return VerifiedUser(uid=uid, email=claims.get("email"), name=claims.get("name"))
