from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, PortfolioCard, PasswordResetToken, utcnow
from app.services import mailer
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

# Where password-reset links point (the deployed frontend's origin)
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
RESET_TOKEN_TTL_MINUTES = 30


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


# ----- Helpers ----------------------------------------------------------------

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
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
    return {
        "email": user.email,
        "username": user.username,
        "created_at": user.created_at,
        "accepted_terms_at": user.accepted_terms_at,
        "is_admin": is_admin(user),
    }


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
    if not user or not pwd_context.verify(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = jwt.encode({"sub": str(user.id),
                        "exp": datetime.now(timezone.utc) + timedelta(days=7)},
                       SECRET_KEY, algorithm=ALGORITHM)
    return {
        "access_token": token,
        "token_type": "bearer"
        }


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
    db.commit()
    return user_info(current_user)


# Rate-limited even though it needs a valid session: caps password-guessing if a
# token is ever compromised, and it's cheap defense in depth
@router.post("/me/password",
             dependencies=[Depends(rate_limit("password", times=10, seconds=300,
                                              what="password changes"))])
def change_password(body: ChangePasswordRequest,
                    current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not pwd_context.verify(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    error = password_error(body.new_password)
    if error:
        raise HTTPException(status_code=400, detail=error)
    current_user.hashed_password = pwd_context.hash(body.new_password)
    db.commit()
    return {"message": "Password updated"}


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
            account. If that was you, choose a new password below &mdash; the
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
            If you didn't ask for this, you can ignore this email &mdash; your
            password is unchanged.
          </p>
          <p style="margin:14px 0 0;font-size:12px;line-height:1.6;color:#9c9ca4;">
            Button not working? Copy this link:<br>
            <a href="{link}" style="color:#56cf9e;word-break:break-all;">{link}</a>
          </p>
        </td></tr>
      </table>
      <p style="margin:18px 0 0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:11px;color:#9c9ca4;">
        Mintly &mdash; Pok&eacute;mon TCG portfolio tracker
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
                    f"If you didn't ask for this, you can ignore this email — "
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
        detail="This reset link is invalid or has expired — request a new one")
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
    token.used_at = utcnow()
    db.commit()
    return {"message": "Password updated"}


@router.delete("/me")
def delete_account(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Remove the user's portfolio lots and any pending reset tokens first —
    # neither FK has an ON DELETE cascade, so Postgres would reject deleting a
    # parent row they still reference. The shared per-card price snapshots
    # aren't tied to a user (Privacy §5), so they stay.
    db.query(PortfolioCard).filter(PortfolioCard.user_id == current_user.id).delete(
        synchronize_session=False
    )
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == current_user.id
    ).delete(synchronize_session=False)
    db.delete(current_user)
    db.commit()
    return {"message": "Account deleted"}
