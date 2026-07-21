from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User, PortfolioCard, utcnow
from app.services.rate_limit import rate_limit
import os
import re
from dotenv import load_dotenv

load_dotenv()


# ----- Configuration ---------------------------------------------------------

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"


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


def valid_email(email: str) -> bool:
    # Light sanity check, matching how lenient registration is — we only reject
    # obviously-malformed addresses (no "@", or no dot in the domain)
    return "@" in email and "." in email.split("@")[-1]


def user_info(user: User) -> dict:
    # The account fields the profile page reads — never the password hash
    return {
        "email": user.email,
        "username": user.username,
        "created_at": user.created_at,
        "accepted_terms_at": user.accepted_terms_at,
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


@router.delete("/me")
def delete_account(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Remove the user's portfolio lots first — the FK has no ON DELETE cascade,
    # so Postgres would reject deleting a user who still holds cards. The shared
    # per-card price snapshots aren't tied to a user (Privacy §5), so they stay.
    db.query(PortfolioCard).filter(PortfolioCard.user_id == current_user.id).delete(
        synchronize_session=False
    )
    db.delete(current_user)
    db.commit()
    return {"message": "Account deleted"}
