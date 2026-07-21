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
