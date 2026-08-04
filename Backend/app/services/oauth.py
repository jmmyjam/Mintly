"""OpenID Connect social sign-in (Google, Microsoft), provider-agnostic.

The flow is the standard server-side Authorization Code flow with PKCE — no
third-party JavaScript runs on the page (better for privacy and CSP), and the
same code path serves every provider:

    /auth/oauth/{provider}/start     -> 302 to the provider's consent screen
    provider redirects back to
    /auth/oauth/{provider}/callback  -> we exchange the code, verify the ID
                                        token, resolve/merge the account, mint
                                        our own JWT, and 302 to the frontend

Each provider is CONFIG-GATED: it is offered only when both its client id and
secret are set (mailer-style, via env). Credentials live in the server `.env`,
never in the repo. Nothing is hard-wired on — an unconfigured provider is
invisible (`enabled_providers()` drops it, `/start` 404s).

State is in-memory and per-process like the app's other caches (rate limiter,
price cache) — the right weight for the single-worker deploy. A login in flight
during a restart simply fails and is retried; nothing durable is lost.
"""

import base64
import hashlib
import os
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests
from jose import jwt
from jose.exceptions import JWTError

# ----- Provider registry ------------------------------------------------------
# Static, public OIDC endpoints per provider. The per-install secrets (client id
# + secret) are read from env at call time so tests can set them and so the
# feature can be toggled purely by configuration.

PROVIDERS: dict[str, dict] = {
    "google": {
        "label": "Google",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "jwks_url": "https://www.googleapis.com/oauth2/v3/certs",
        "scope": "openid email profile",
        "client_id_env": "GOOGLE_OAUTH_CLIENT_ID",
        "client_secret_env": "GOOGLE_OAUTH_CLIENT_SECRET",
        # Google's ID-token issuer is one of these exact strings
        "issuers": ("https://accounts.google.com", "accounts.google.com"),
    },
    "microsoft": {
        "label": "Microsoft",
        # /common accepts both work/school and personal accounts
        "authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "jwks_url": "https://login.microsoftonline.com/common/discovery/v2.0/keys",
        "scope": "openid email profile",
        "client_id_env": "MICROSOFT_OAUTH_CLIENT_ID",
        "client_secret_env": "MICROSOFT_OAUTH_CLIENT_SECRET",
        # Issuer is tenant-specific (https://login.microsoftonline.com/{tid}/v2.0)
        # so it's validated per-token against the token's own `tid`, not a list.
        "issuers": None,
    },
}

# Where the provider redirects back to — the PUBLIC base URL at which this API's
# /auth/oauth/* routes are reachable. Must EXACTLY match the redirect URI
# registered in the provider console. Dev: http://localhost:8000. Prod (behind
# Caddy, which strips the /api prefix): https://mintlytcg.com/api
_CALLBACK_BASE = os.getenv("OAUTH_CALLBACK_BASE", "http://localhost:8000").rstrip("/")

_HTTP_TIMEOUT = (5, 10)  # (connect, read) seconds
_PENDING_TTL = 600       # seconds a started login may sit before its callback
_JWKS_TTL = 3600         # seconds a provider's signing keys are cached


class OAuthError(Exception):
    """A recoverable sign-in failure. `code` maps to a user-facing message on
    the frontend's /login page (see the OAUTH_ERRORS map there)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


@dataclass
class OAuthIdentity:
    provider: str
    sub: str                # the provider's stable subject id
    email: str | None
    email_verified: bool
    name: str | None


# ----- Configuration helpers --------------------------------------------------

def _creds(provider: str) -> tuple[str, str] | None:
    cfg = PROVIDERS.get(provider)
    if not cfg:
        return None
    client_id = os.getenv(cfg["client_id_env"], "").strip()
    client_secret = os.getenv(cfg["client_secret_env"], "").strip()
    if not client_id or not client_secret:
        return None
    return client_id, client_secret


def is_enabled(provider: str) -> bool:
    return _creds(provider) is not None


def enabled_providers() -> list[str]:
    """Configured providers, in registry order — the frontend renders a button
    per entry, so an unconfigured provider never appears."""
    return [name for name in PROVIDERS if is_enabled(name)]


def redirect_uri(provider: str) -> str:
    return f"{_CALLBACK_BASE}/auth/oauth/{provider}/callback"


# ----- PKCE + pending-login store ---------------------------------------------

_pending_lock = threading.Lock()
_pending: dict[str, dict] = {}  # state -> {provider, code_verifier, nonce, created_at}


def _prune_pending(now: float) -> None:
    for state in list(_pending):
        if now - _pending[state]["created_at"] >= _PENDING_TTL:
            del _pending[state]


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def start_login(provider: str) -> str:
    """Register a pending login and return the provider's authorize URL. The
    opaque `state` (CSRF guard) + PKCE verifier + nonce are held in-memory keyed
    by state, to be validated when the callback comes back."""
    creds = _creds(provider)
    if creds is None:
        raise OAuthError("unavailable", f"{provider} sign-in is not configured")
    client_id, _ = creds
    cfg = PROVIDERS[provider]

    state = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(24)
    now = time.time()
    with _pending_lock:
        _prune_pending(now)
        _pending[state] = {
            "provider": provider,
            "code_verifier": code_verifier,
            "nonce": nonce,
            "created_at": now,
        }

    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": cfg["scope"],
        "redirect_uri": redirect_uri(provider),
        "state": state,
        "nonce": nonce,
        "code_challenge": _code_challenge(code_verifier),
        "code_challenge_method": "S256",
        # Let the user pick which provider account to use (helps land on the
        # right identity when merging with an existing Mintly account).
        "prompt": "select_account",
    }
    return f"{cfg['authorize_url']}?{urlencode(params)}"


def take_pending(state: str) -> dict | None:
    """Consume a pending login by state (single-use). None if unknown/expired."""
    now = time.time()
    with _pending_lock:
        _prune_pending(now)
        return _pending.pop(state, None)


# ----- Token exchange + verification ------------------------------------------

def exchange_code(provider: str, code: str, code_verifier: str) -> str:
    """Trade the authorization code for tokens; return the raw id_token JWT."""
    creds = _creds(provider)
    if creds is None:
        raise OAuthError("unavailable")
    client_id, client_secret = creds
    cfg = PROVIDERS[provider]
    try:
        resp = requests.post(
            cfg["token_url"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri(provider),
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise OAuthError("provider_error", f"token endpoint unreachable: {exc}")
    if resp.status_code != 200:
        raise OAuthError("provider_error",
                         f"token endpoint {resp.status_code}: {resp.text[:200]}")
    id_token = resp.json().get("id_token")
    if not id_token:
        raise OAuthError("provider_error", "no id_token in token response")
    return id_token


_jwks_lock = threading.Lock()
_jwks_cache: dict[str, tuple[dict, float]] = {}  # provider -> (jwks, fetched_at)


def _get_jwks(provider: str, force: bool = False) -> dict:
    now = time.time()
    with _jwks_lock:
        cached = _jwks_cache.get(provider)
        if cached and not force and now - cached[1] < _JWKS_TTL:
            return cached[0]
    try:
        resp = requests.get(PROVIDERS[provider]["jwks_url"], timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        jwks = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise OAuthError("provider_error", f"jwks fetch failed: {exc}")
    with _jwks_lock:
        _jwks_cache[provider] = (jwks, now)
    return jwks


def _validate_issuer(provider: str, claims: dict) -> None:
    cfg = PROVIDERS[provider]
    iss = claims.get("iss", "")
    if cfg["issuers"] is not None:
        if iss not in cfg["issuers"]:
            raise OAuthError("provider_error", f"unexpected issuer {iss!r}")
        return
    # Microsoft: issuer is tenant-specific — it must match the token's own tid.
    tid = claims.get("tid")
    if not tid or iss != f"https://login.microsoftonline.com/{tid}/v2.0":
        raise OAuthError("provider_error", f"unexpected issuer {iss!r}")


def verify_id_token(provider: str, id_token: str, nonce: str) -> dict:
    """Verify the ID token's signature (against the provider's JWKS), audience,
    expiry, issuer, and nonce; return its claims. Raises OAuthError on any
    failure."""
    creds = _creds(provider)
    if creds is None:
        raise OAuthError("unavailable")
    client_id, _ = creds

    def _decode(jwks: dict) -> dict:
        return jwt.decode(
            id_token,
            jwks,
            algorithms=["RS256"],
            audience=client_id,
            # at_hash checks the access token, which we don't use for identity;
            # signature + aud + exp + our nonce/issuer checks are what matter.
            options={"verify_at_hash": False},
        )

    try:
        claims = _decode(_get_jwks(provider))
    except JWTError:
        # Signing keys rotate — refetch once before giving up.
        try:
            claims = _decode(_get_jwks(provider, force=True))
        except JWTError as exc:
            raise OAuthError("provider_error", f"id_token verification failed: {exc}")

    _validate_issuer(provider, claims)
    if nonce and claims.get("nonce") != nonce:
        raise OAuthError("provider_error", "nonce mismatch")
    return claims


def _as_bool(value) -> bool:
    # Providers may send booleans as JSON true/false or as the strings
    # "true"/"false" (Microsoft's xms_edov has been seen both ways).
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def extract_identity(provider: str, claims: dict) -> OAuthIdentity:
    sub = claims.get("sub")
    if not sub:
        raise OAuthError("provider_error", "id_token has no subject")

    email = claims.get("email")
    if provider == "google":
        verified = _as_bool(claims.get("email_verified"))
    elif provider == "microsoft":
        # Microsoft v2.0 tokens carry no email_verified. `xms_edov` ("email
        # domain owner verified") is the equivalent, but only when configured as
        # an optional claim on the app registration; email may also live in
        # `preferred_username`. Without xms_edov we treat the email as
        # unverified, which blocks an unsafe auto-merge (see resolve_oauth_user).
        if not email:
            pu = claims.get("preferred_username", "")
            email = pu if "@" in pu else None
        verified = _as_bool(claims.get("xms_edov"))
    else:
        verified = _as_bool(claims.get("email_verified"))

    email = email.strip().lower() if email else None
    return OAuthIdentity(
        provider=provider,
        sub=str(sub),
        email=email,
        email_verified=bool(email and verified),
        name=(claims.get("name") or "").strip() or None,
    )


def complete_login(provider: str, code: str, code_verifier: str, nonce: str) -> OAuthIdentity:
    """The full callback path: code -> id_token -> verified claims -> identity.
    Kept as one seam so tests can monkeypatch it (and the two calls it wraps) to
    exercise the router without real provider HTTP."""
    id_token = exchange_code(provider, code, code_verifier)
    claims = verify_id_token(provider, id_token, nonce)
    return extract_identity(provider, claims)
