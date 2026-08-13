import base64
import binascii
import hmac
import os
import secrets
from datetime import datetime

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, Form, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User


GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
GOOGLE_ALLOWED_EMAILS = {
    item.strip().casefold()
    for item in os.getenv("GOOGLE_ALLOWED_EMAILS", "").split(",")
    if item.strip()
}

APP_USERNAME = os.getenv("APP_USERNAME", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD")
GOOGLE_AUTH_CONFIGURED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and SESSION_SECRET)
LEGACY_BASIC_ENABLED = bool(APP_PASSWORD) and (
    os.getenv("ALLOW_LEGACY_BASIC_AUTH", "").strip().casefold() in {"1", "true", "yes"}
    or not GOOGLE_AUTH_CONFIGURED
)

oauth = OAuth()
if GOOGLE_AUTH_CONFIGURED:
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


class AuthenticationRequired(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Silakan masuk untuk melanjutkan.",
        )


def session_secret_for_middleware() -> str:
    # APP_PASSWORD keeps legacy deployments stable until SESSION_SECRET is set.
    # The random fallback is local-only and intentionally invalidates cookies on restart.
    return SESSION_SECRET or APP_PASSWORD or secrets.token_urlsafe(32)


def _basic_credentials(request: Request) -> tuple[str, str] | None:
    authorization = request.headers.get("authorization", "")
    try:
        scheme, encoded = authorization.split(" ", 1)
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return None
    if scheme.casefold() != "basic":
        return None
    return username, password


def _legacy_user(request: Request, db: Session) -> User | None:
    if not LEGACY_BASIC_ENABLED or not APP_PASSWORD:
        return None
    credentials = _basic_credentials(request)
    if not credentials:
        return None
    username, password = credentials
    if not (
        hmac.compare_digest(username, APP_USERNAME)
        and hmac.compare_digest(password, APP_PASSWORD)
    ):
        return None
    email = os.getenv("BOOTSTRAP_OWNER_EMAIL", "amelw778@gmail.com").strip().casefold()
    return db.query(User).filter(User.email == email, User.is_active.is_(True)).first()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = None
    user_id = request.session.get("user_id")
    if user_id:
        user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
        if not user:
            request.session.clear()

    if not user:
        user = _legacy_user(request, db)

    if not user:
        raise AuthenticationRequired()

    request.state.current_user = user
    request.session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return user


def verify_csrf(request: Request, csrf_token: str = Form(...)) -> None:
    expected = request.session.get("csrf_token", "")
    if not expected or not hmac.compare_digest(expected, csrf_token):
        raise HTTPException(status_code=403, detail="Form keamanan kedaluwarsa. Muat ulang halaman.")


def upsert_google_user(db: Session, userinfo: dict) -> User:
    google_sub = str(userinfo.get("sub", "")).strip()
    email = str(userinfo.get("email", "")).strip().casefold()
    if not google_sub or not email or not userinfo.get("email_verified"):
        raise HTTPException(status_code=403, detail="Akun Google tidak memiliki email terverifikasi.")
    if GOOGLE_ALLOWED_EMAILS and email not in GOOGLE_ALLOWED_EMAILS:
        raise HTTPException(status_code=403, detail="Email ini belum diizinkan menggunakan aplikasi.")

    user = db.query(User).filter(User.google_sub == google_sub).first()
    if not user:
        bootstrap_user = db.query(User).filter(User.email == email).first()
        if bootstrap_user and bootstrap_user.google_sub.startswith("bootstrap:"):
            user = bootstrap_user
            user.google_sub = google_sub
        elif bootstrap_user:
            raise HTTPException(status_code=409, detail="Email sudah terhubung ke identitas lain.")
        else:
            user = User(
                google_sub=google_sub,
                email=email,
                role="user",
                is_active=True,
            )
            db.add(user)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Akun pengguna sedang dinonaktifkan.")

    user.email = email
    user.name = str(userinfo.get("name") or email.split("@", 1)[0])[:255]
    user.picture_url = str(userinfo.get("picture") or "") or None
    user.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user
