from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import (User, Portfolio, PortfolioCard, PasswordResetToken,
                        EmailVerificationToken, OAuthAccount, utcnow)
from app.services import mailer, oauth
from app.services.oauth import OAuthError, OAuthIdentity
from app.services.admin_access import is_admin
from app.services.rate_limit import rate_limit
import hashlib
import html
import logging
import os
import re
import secrets
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ----- Configuration ---------------------------------------------------------

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

# Where password-reset / email-verification links point (the frontend's origin)
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
RESET_TOKEN_TTL_MINUTES = 30
VERIFY_TOKEN_TTL_HOURS = 24
TOKEN_TTL_DAYS = 7  # JWT lifetime


# ----- Global state ----------------------------------------------------------

pwd_context = CryptContext(schemes=["bcrypt"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
router = APIRouter(prefix="/auth")


# ----- Request models --------------------------------------------------------

class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str
    accepted_terms: bool = False


class UpdateProfileRequest(BaseModel):
    # Both optional — the profile page may change either field on its own
    email: str | None = None
    username: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class VerifyEmailRequest(BaseModel):
    token: str


# ----- Helpers ----------------------------------------------------------------

def mint_token(user: User) -> str:
    # The login token. Carries the user's current token_version as "tv" so a
    # later bump (sign-out-all, password change/reset) invalidates it.
    return jwt.encode(
        {"sub": str(user.id),
         "tv": user.token_version,
         "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_TTL_DAYS)},
        SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    # Revocation check: a token minted before a token_version bump is now stale.
    # A legacy token predating this claim has no "tv" and reads as 0 (the column
    # default), so existing sessions survive the deploy until the first bump.
    if payload.get("tv", 0) != user.token_version:
        raise HTTPException(status_code=401, detail="Session expired")
    return user


def password_error(password: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not re.search(r"[A-Za-z]", password):
        return "Password must contain at least one letter"
    if not re.search(r"\d", password):
        return "Password must contain at least one number"
    return None


def hash_token(raw: str) -> str:
    # Reset tokens are stored hashed — a DB leak must not yield working links
    return hashlib.sha256(raw.encode()).hexdigest()


def valid_email(email: str) -> bool:
    # Light sanity check, matching how lenient registration is — we only reject
    # obviously-malformed addresses (no "@", or no dot in the domain)
    return "@" in email and "." in email.split("@")[-1]


def user_info(user: User) -> dict:
    # The account fields the profile page reads — never the password hash.
    # is_admin lets the frontend show the admin-dashboard link to admins only.
    # has_password is False for social-only accounts (the Profile page swaps the
    # change-password form for a "set one via reset" note); oauth_providers lists
    # the linked social identities so Profile can show "Connected accounts".
    return {
        "email": user.email,
        "username": user.username,
        "created_at": user.created_at,
        "accepted_terms_at": user.accepted_terms_at,
        "email_verified": user.email_verified_at is not None,
        "is_admin": is_admin(user),
        "has_password": user.hashed_password is not None,
        "oauth_providers": sorted({a.provider for a in user.oauth_accounts}),
    }


# ----- Social sign-in (OAuth/OIDC) -------------------------------------------

def _generate_username(db: Session, identity: OAuthIdentity) -> str:
    # Derive a unique username for a brand-new social account from the provider
    # name, falling back to the email local part, then "user"; dedupe with a
    # numeric suffix. (The user can rename it later from Profile.)
    for source in (identity.name, (identity.email or "").split("@")[0]):
        base = re.sub(r"[^a-zA-Z0-9]+", "", source or "").lower()[:20]
        if base:
            break
    else:
        base = "user"
    base = base or "user"
    candidate, n = base, 0
    while db.query(User).filter(User.username == candidate).first():
        n += 1
        candidate = f"{base}{n}"
    return candidate


def _link_oauth_account(db: Session, user: User, identity: OAuthIdentity) -> None:
    db.add(OAuthAccount(
        user_id=user.id,
        provider=identity.provider,
        provider_account_id=identity.sub,
        email=identity.email,
    ))


def _create_oauth_user(db: Session, identity: OAuthIdentity, *, email_verified: bool) -> User:
    user = User(
        email=identity.email,
        username=_generate_username(db, identity),
        hashed_password=None,  # social-only until a password is set via reset
        # Clicking "Continue with <provider>" accepts the Terms — the button
        # carries the "By continuing you agree…" line (see the frontend).
        accepted_terms_at=utcnow(),
        email_verified_at=utcnow() if email_verified else None,
    )
    db.add(user)
    db.flush()  # populate user.id for the FK on the linked account
    _link_oauth_account(db, user, identity)
    db.commit()
    return user


def resolve_oauth_user(db: Session, identity: OAuthIdentity) -> tuple[User, bool]:
    """Turn a verified provider identity into a Mintly user, returning
    (user, is_new). Precedence:

    1. This exact provider identity is already linked -> that user (login).
    2. Provider-VERIFIED email matches an existing account -> link the provider
       to it and log in (the requested account MERGE — no duplicate).
    3. Provider-verified email, no existing account -> create a new account.
    4. Unverified email colliding with an existing account -> refuse (we can't
       prove the caller owns the address, so we won't hand over its data).
    5. Otherwise -> create a new (unverified) account.
    """
    link = db.query(OAuthAccount).filter(
        OAuthAccount.provider == identity.provider,
        OAuthAccount.provider_account_id == identity.sub,
    ).first()
    if link:
        user = db.get(User, link.user_id)
        if user is not None:
            if identity.email:
                link.email = identity.email
            # If the linked account's own email is now provider-confirmed, stamp it
            if (identity.email_verified and user.email_verified_at is None
                    and user.email == identity.email):
                user.email_verified_at = utcnow()
            db.commit()
            return user, False
        db.delete(link)  # orphaned link — drop it and treat as a fresh sign-in
        db.commit()

    if identity.email and identity.email_verified:
        existing = db.query(User).filter(User.email == identity.email).first()
        if existing:
            _link_oauth_account(db, existing, identity)
            if existing.email_verified_at is None:
                existing.email_verified_at = utcnow()
            db.commit()
            return existing, False
        return _create_oauth_user(db, identity, email_verified=True), True

    if identity.email:
        clash = db.query(User).filter(User.email == identity.email).first()
        if clash:
            raise OAuthError(
                "email_unverified",
                f"{identity.provider} did not verify ownership of {identity.email}")
    return _create_oauth_user(db, identity, email_verified=False), True


def _oauth_error_redirect(code: str) -> RedirectResponse:
    # Bounce back to the login page with a code the frontend maps to a message.
    return RedirectResponse(f"{FRONTEND_BASE_URL}/login?oauth_error={code}", status_code=302)


# ----- Routes ----------------------------------------------------------------

@router.post("/register",
             dependencies=[Depends(rate_limit("register", times=10, seconds=3600,
                                              what="signup attempts"))])
def register(body: RegisterRequest, db=Depends(get_db)):
    if not body.accepted_terms:
        raise HTTPException(status_code=400, detail="You must agree to the Terms of Service")
    error = password_error(body.password)
    if error:
        raise HTTPException(status_code=400, detail=error)
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="Username already taken")
    user = User(email=body.email,
                username=body.username,
                hashed_password=pwd_context.hash(body.password),
                accepted_terms_at=utcnow())
    db.add(user); db.commit()
    # Send the verification email best-effort — a mail hiccup must not block
    # signup (verification is soft; the user can resend from Profile later).
    try:
        send_verification_email(user, db)
    except Exception:
        logger.warning("verification email (register) failed", exc_info=True)
    return {
        "message": "Account created"
        }

# Counts every attempt (success or failure) per IP — the cap is what matters
# for credential stuffing; 10 per 5 min never touches a real user logging in
@router.post("/login",
             dependencies=[Depends(rate_limit("login", times=10, seconds=300,
                                              what="login attempts"))])
def login(form: OAuth2PasswordRequestForm = Depends(), db=Depends(get_db)):
    user = db.query(User).filter(
        (User.email == form.username) | (User.username == form.username)
    ).first()
    # A social-only account has no password hash — never let verify() run on None
    if not user or not user.hashed_password or not pwd_context.verify(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {
        "access_token": mint_token(user),
        "token_type": "bearer"
        }


@router.get("/oauth/providers")
def oauth_providers():
    # Only providers with credentials configured — the frontend renders a button
    # per entry, so an unconfigured provider never appears (config-gated).
    return {"providers": oauth.enabled_providers()}


@router.get("/oauth/{provider}/start",
            dependencies=[Depends(rate_limit("oauth", times=30, seconds=300,
                                             what="sign-in attempts"))])
def oauth_start(provider: str):
    # Redirect the browser to the provider's consent screen. An unknown or
    # unconfigured provider 404s (nothing to reveal about what's available).
    try:
        url = oauth.start_login(provider)
    except OAuthError:
        raise HTTPException(status_code=404, detail="Not found")
    return RedirectResponse(url, status_code=302)


@router.get("/oauth/{provider}/callback")
def oauth_callback(provider: str, code: str | None = None, state: str | None = None,
                   error: str | None = None, db: Session = Depends(get_db)):
    # Where the provider sends the user back. We validate `state` (CSRF), trade
    # the code for a verified identity, resolve/merge the account, and hand the
    # browser our own JWT via the frontend callback route. Every failure bounces
    # to /login with a code the frontend turns into a friendly message.
    if error or not code or not state:
        return _oauth_error_redirect("cancelled" if error == "access_denied" else "provider_error")
    pending = oauth.take_pending(state)
    if not pending or pending["provider"] != provider:
        return _oauth_error_redirect("expired")
    try:
        identity = oauth.complete_login(
            provider, code, pending["code_verifier"], pending["nonce"])
        user, _ = resolve_oauth_user(db, identity)
    except OAuthError as exc:
        return _oauth_error_redirect(exc.code)
    # The token rides in the URL fragment (never sent to a server, kept out of
    # logs/Referer); the frontend /auth/callback route stores it and scrubs it.
    return RedirectResponse(
        f"{FRONTEND_BASE_URL}/auth/callback#token={mint_token(user)}",
        status_code=302)


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user)):
    return user_info(current_user)


@router.patch("/me")
def update_me(body: UpdateProfileRequest,
              current_user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    # Only the fields the request actually sends are touched; each is checked
    # for uniqueness against *other* users (re-saving your own value is fine)
    if body.username is not None:
        username = body.username.strip()
        if not username:
            raise HTTPException(status_code=400, detail="Username can't be empty")
        if username != current_user.username:
            taken = db.query(User).filter(User.username == username,
                                          User.id != current_user.id).first()
            if taken:
                raise HTTPException(status_code=409, detail="Username already taken")
            current_user.username = username
    email_changed = False
    if body.email is not None:
        email = body.email.strip()
        if not valid_email(email):
            raise HTTPException(status_code=400, detail="Enter a valid email address")
        if email != current_user.email:
            taken = db.query(User).filter(User.email == email,
                                          User.id != current_user.id).first()
            if taken:
                raise HTTPException(status_code=409, detail="Email already registered")
            current_user.email = email
            # The new address is unverified until confirmed — otherwise a user
            # could verify one address then swap in an unowned one
            current_user.email_verified_at = None
            email_changed = True
    db.commit()
    if email_changed:
        # Best-effort — a mail hiccup shouldn't fail the profile update
        try:
            send_verification_email(current_user, db)
        except Exception:
            logger.warning("verification email (email change) failed", exc_info=True)
    return user_info(current_user)


# Rate-limited even though it needs a valid session: caps password-guessing if a
# token is ever compromised, and it's cheap defense in depth
@router.post("/me/password",
             dependencies=[Depends(rate_limit("password", times=10, seconds=300,
                                              what="password changes"))])
def change_password(body: ChangePasswordRequest,
                    current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if current_user.hashed_password is None:
        # Social-only account: there's no current password to verify against.
        # The forgot-password flow (they have a verified email) sets the first one.
        raise HTTPException(
            status_code=400,
            detail='Your account uses social sign-in. Use the "Forgot password" '
                   'link on the login page to set a password first.')
    if not pwd_context.verify(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    error = password_error(body.new_password)
    if error:
        raise HTTPException(status_code=400, detail=error)
    current_user.hashed_password = pwd_context.hash(body.new_password)
    # Invalidate every other outstanding session, then re-issue a token for THIS
    # device so the user isn't logged out of the tab they just changed it in.
    current_user.token_version += 1
    db.commit()
    return {"message": "Password updated",
            "access_token": mint_token(current_user),
            "token_type": "bearer"}


@router.post("/me/sign-out-others")
def sign_out_others(current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    # Bump token_version so every outstanding JWT — including any leaked one — is
    # rejected on its next request, then hand this session a fresh token so the
    # caller stays signed in here. This is the on-demand kill switch for a
    # compromised token (logout is otherwise client-side only).
    current_user.token_version += 1
    db.commit()
    return {"message": "Signed out of all other devices",
            "access_token": mint_token(current_user),
            "token_type": "bearer"}


def verify_email_html(username: str, link: str) -> str:
    # HTML alternative for the verification email — same dark-palette table
    # layout as the reset email (index.css tokens inlined; no images).
    # Username is user-controlled — escape it.
    name = html.escape(username)
    return f"""\
<div style="margin:0;padding:0;background-color:#0a0a0b;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background-color:#0a0a0b;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="max-width:440px;background-color:#1e1e21;border:1px solid #303037;border-radius:18px;">
        <tr><td style="padding:36px 36px 32px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
          <p style="margin:0 0 24px;font-size:18px;font-weight:700;letter-spacing:-0.02em;color:#f2eee3;">
            <span style="color:#56cf9e;">&#9679;</span>&nbsp;Mintly
          </p>
          <h1 style="margin:0 0 10px;font-size:23px;font-weight:700;letter-spacing:-0.02em;color:#f2f2ef;">
            Verify your email
          </h1>
          <p style="margin:0 0 26px;font-size:14px;line-height:1.6;color:#9c9ca4;">
            Hi {name}, confirm this email address to finish setting up your
            Mintly account. The link works for {VERIFY_TOKEN_TTL_HOURS} hours.
          </p>
          <table role="presentation" cellpadding="0" cellspacing="0"><tr>
            <td style="background-color:#f2eee3;border-radius:999px;">
              <a href="{link}"
                 style="display:inline-block;padding:12px 28px;font-family:inherit;font-size:14px;font-weight:600;color:#0a0a0b;text-decoration:none;border-radius:999px;">
                Verify email
              </a>
            </td>
          </tr></table>
          <p style="margin:26px 0 0;font-size:12px;line-height:1.6;color:#9c9ca4;">
            If you didn't create a Mintly account, you can ignore this email.
          </p>
          <p style="margin:14px 0 0;font-size:12px;line-height:1.6;color:#9c9ca4;">
            Button not working? Copy this link:<br>
            <a href="{link}" style="color:#56cf9e;word-break:break-all;">{link}</a>
          </p>
        </td></tr>
      </table>
      <p style="margin:18px 0 0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:11px;color:#9c9ca4;">
        Mintly - Pok&eacute;mon TCG portfolio tracker
      </p>
    </td></tr>
  </table>
</div>
"""


def send_verification_email(user: User, db: Session) -> None:
    # One live verification link per account: a new send supersedes any
    # outstanding one (same rule as password reset). Raises on a real send
    # failure — callers decide whether that's fatal (register: no; resend: yes).
    db.query(EmailVerificationToken).filter(
        EmailVerificationToken.user_id == user.id
    ).delete(synchronize_session=False)
    raw = secrets.token_urlsafe(32)
    db.add(EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_token(raw),
        expires_at=utcnow() + timedelta(hours=VERIFY_TOKEN_TTL_HOURS),
    ))
    db.commit()
    link = f"{FRONTEND_BASE_URL}/verify-email?token={raw}"
    mailer.send_email(
        to=user.email,
        subject="Verify your Mintly email",
        body=(
            f"Hi {user.username},\n\n"
            f"Confirm your email address to finish setting up your Mintly account. "
            f"Open this link within {VERIFY_TOKEN_TTL_HOURS} hours:\n\n"
            f"{link}\n\n"
            f"If you didn't create a Mintly account, you can ignore this email.\n"
        ),
        html=verify_email_html(user.username, link),
    )


def reset_email_html(username: str, link: str) -> str:
    # The HTML alternative for the reset email, styled to the app's dark
    # palette (index.css tokens, inlined — email clients strip <style>).
    # Table layout + no images: renders everywhere, nothing to block.
    # Username is user-controlled — escape it.
    name = html.escape(username)
    return f"""\
<div style="margin:0;padding:0;background-color:#0a0a0b;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background-color:#0a0a0b;padding:32px 16px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="max-width:440px;background-color:#1e1e21;border:1px solid #303037;border-radius:18px;">
        <tr><td style="padding:36px 36px 32px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
          <p style="margin:0 0 24px;font-size:18px;font-weight:700;letter-spacing:-0.02em;color:#f2eee3;">
            <span style="color:#56cf9e;">&#9679;</span>&nbsp;Mintly
          </p>
          <h1 style="margin:0 0 10px;font-size:23px;font-weight:700;letter-spacing:-0.02em;color:#f2f2ef;">
            Reset your password
          </h1>
          <p style="margin:0 0 26px;font-size:14px;line-height:1.6;color:#9c9ca4;">
            Hi {name}, someone asked to reset the password for your Mintly
            account. If that was you, choose a new password below. The
            link works for {RESET_TOKEN_TTL_MINUTES} minutes.
          </p>
          <table role="presentation" cellpadding="0" cellspacing="0"><tr>
            <td style="background-color:#f2eee3;border-radius:999px;">
              <a href="{link}"
                 style="display:inline-block;padding:12px 28px;font-family:inherit;font-size:14px;font-weight:600;color:#0a0a0b;text-decoration:none;border-radius:999px;">
                Choose a new password
              </a>
            </td>
          </tr></table>
          <p style="margin:26px 0 0;font-size:12px;line-height:1.6;color:#9c9ca4;">
            If you didn't ask for this, you can ignore this email; your
            password is unchanged.
          </p>
          <p style="margin:14px 0 0;font-size:12px;line-height:1.6;color:#9c9ca4;">
            Button not working? Copy this link:<br>
            <a href="{link}" style="color:#56cf9e;word-break:break-all;">{link}</a>
          </p>
        </td></tr>
      </table>
      <p style="margin:18px 0 0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:11px;color:#9c9ca4;">
        Mintly - Pok&eacute;mon TCG portfolio tracker
      </p>
    </td></tr>
  </table>
</div>
"""


# The response is identical whether or not the email has an account — only the
# inbox learns the difference (account enumeration). Rate-limited tighter than
# login because every valid hit sends an email (inbox-bombing vector).
@router.post("/forgot-password",
             dependencies=[Depends(rate_limit("forgot", times=5, seconds=3600,
                                              what="password reset requests"))])
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email.strip()).first()
    if user:
        # One live link per account: a new request supersedes any outstanding one
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id
        ).delete(synchronize_session=False)
        raw = secrets.token_urlsafe(32)
        db.add(PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=utcnow() + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
        ))
        db.commit()
        link = f"{FRONTEND_BASE_URL}/reset-password?token={raw}"
        try:
            mailer.send_email(
                to=user.email,
                subject="Reset your Mintly password",
                body=(
                    f"Hi {user.username},\n\n"
                    f"Someone asked to reset the password for your Mintly account. "
                    f"If that was you, open this link within {RESET_TOKEN_TTL_MINUTES} minutes "
                    f"to choose a new password:\n\n"
                    f"{link}\n\n"
                    f"If you didn't ask for this, you can ignore this email; "
                    f"your password is unchanged.\n"
                ),
                html=reset_email_html(user.username, link),
            )
        except Exception:
            # A send failure must not change the response (that would leak
            # whether the address exists); the user can simply request again
            logger.warning("password reset email failed", exc_info=True)
    return {"message": "If that email has an account, a reset link is on its way."}


# Shares the "password" budget with the authed change-password route — both are
# password-setting attempts. Token guessing is hopeless anyway (256-bit values).
@router.post("/reset-password",
             dependencies=[Depends(rate_limit("password", times=10, seconds=300,
                                              what="password changes"))])
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    invalid = HTTPException(
        status_code=400,
        detail="This reset link is invalid or has expired. Request a new one")
    token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == hash_token(body.token)
    ).first()
    if not token or token.used_at is not None or token.expires_at < utcnow():
        raise invalid
    error = password_error(body.new_password)
    if error:
        # The token stays live — a typo'd new password shouldn't burn the link
        raise HTTPException(status_code=400, detail=error)
    user = db.get(User, token.user_id)
    if not user:
        raise invalid
    user.hashed_password = pwd_context.hash(body.new_password)
    # A reset kills every existing session — if someone else set this password,
    # any session they had is now dead; the real owner logs in fresh.
    user.token_version += 1
    token.used_at = utcnow()
    db.commit()
    return {"message": "Password updated"}


@router.post("/verify-email/send",
             dependencies=[Depends(rate_limit("verify", times=5, seconds=3600,
                                              what="verification emails"))])
def resend_verification(current_user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    if current_user.email_verified_at is not None:
        return {"message": "Your email is already verified."}
    try:
        send_verification_email(current_user, db)
    except Exception:
        logger.warning("verification email (resend) failed", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="We couldn't send the verification email. Please try again shortly.")
    return {"message": "Verification email sent. Check your inbox."}


# Unauthed on purpose — the link from the email works whether or not the browser
# that opens it is logged in. Single-use token, 24h expiry (same handling as the
# reset flow); one uniform message for a missing/used/expired token.
@router.post("/verify-email")
def verify_email(body: VerifyEmailRequest, db: Session = Depends(get_db)):
    invalid = HTTPException(
        status_code=400,
        detail="This verification link is invalid or has expired. Request a new one from your profile.")
    token = db.query(EmailVerificationToken).filter(
        EmailVerificationToken.token_hash == hash_token(body.token)
    ).first()
    if not token or token.used_at is not None or token.expires_at < utcnow():
        raise invalid
    user = db.get(User, token.user_id)
    if not user:
        raise invalid
    token.used_at = utcnow()
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
    db.commit()
    return {"message": "Email verified"}


@router.delete("/me")
def delete_account(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Remove the user's portfolio lots, their portfolios, and any pending reset
    # tokens first — none of these FKs has an ON DELETE cascade, so Postgres
    # would reject deleting a parent row they still reference. Lots reference
    # portfolios, so lots go before portfolios. The shared per-card price
    # snapshots aren't tied to a user (Privacy §5), so they stay.
    db.query(PortfolioCard).filter(PortfolioCard.user_id == current_user.id).delete(
        synchronize_session=False
    )
    db.query(Portfolio).filter(Portfolio.user_id == current_user.id).delete(
        synchronize_session=False
    )
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == current_user.id
    ).delete(synchronize_session=False)
    db.query(EmailVerificationToken).filter(
        EmailVerificationToken.user_id == current_user.id
    ).delete(synchronize_session=False)
    db.query(OAuthAccount).filter(
        OAuthAccount.user_id == current_user.id
    ).delete(synchronize_session=False)
    db.delete(current_user)
    db.commit()
    return {"message": "Account deleted"}
