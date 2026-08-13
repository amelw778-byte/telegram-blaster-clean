import os
from pathlib import Path

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import (
    GOOGLE_AUTH_CONFIGURED,
    get_current_user,
    oauth,
    upsert_google_user,
    verify_csrf,
)
from app.database import get_db
from app.models import User


router = APIRouter()
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


def _safe_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return "/dashboard"


@router.get("/login", name="login_page")
def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=303)
    return templates.TemplateResponse(request, "login.html", {
        "request": request,
        "google_auth_configured": GOOGLE_AUTH_CONFIGURED,
        "error": request.query_params.get("error"),
    })


@router.get("/auth/google/login", name="google_login")
async def google_login(request: Request):
    if not GOOGLE_AUTH_CONFIGURED:
        return RedirectResponse("/login?error=oauth_not_configured", status_code=303)
    request.session["post_login_next"] = _safe_next(request.query_params.get("next"))
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "").strip() or str(
        request.url_for("google_callback")
    )
    google = oauth.create_client("google")
    return await google.authorize_redirect(request, redirect_uri, prompt="select_account")


@router.get("/auth/google/callback", name="google_callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    if not GOOGLE_AUTH_CONFIGURED:
        return RedirectResponse("/login?error=oauth_not_configured", status_code=303)
    try:
        google = oauth.create_client("google")
        token = await google.authorize_access_token(request)
        userinfo = dict(token.get("userinfo") or {})
        user = upsert_google_user(db, userinfo)
    except OAuthError:
        return RedirectResponse("/login?error=google_login_failed", status_code=303)

    destination = _safe_next(request.session.get("post_login_next"))
    request.session.clear()
    request.session["user_id"] = user.id
    return RedirectResponse(destination, status_code=303)


@router.post("/logout")
def logout(
    request: Request,
    _user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
