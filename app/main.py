from pathlib import Path
import os
import sys
import types
from urllib.parse import quote

# Compatibility mode: when Railway's Root Directory is set to ``app``,
# Uvicorn imports this file as top-level ``main``. Register the current
# directory as the ``app`` package so existing absolute imports still work.
if __package__ in (None, ""):
    package = types.ModuleType("app")
    package.__path__ = [str(Path(__file__).resolve().parent)]
    package.__package__ = "app"
    sys.modules.setdefault("app", package)


from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from sqlalchemy import text

from app.auth import AuthenticationRequired, session_secret_for_middleware
from app.database import SessionLocal, engine
from app.migrations import initialize_database
from app.models import BlastJob, BlastRecipient, TelegramAccount, User  # noqa: F401
from app.services.blast_manager import blast_manager

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

initialize_database()

app = FastAPI(title="PorsLabs Telegram Blaster")
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret_for_middleware(),
    session_cookie="porslabs_session",
    max_age=60 * 60 * 24 * 7,
    same_site="lax",
    https_only=bool(os.getenv("RAILWAY_ENVIRONMENT")),
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.exception_handler(AuthenticationRequired)
async def authentication_required(request: Request, _exc: AuthenticationRequired):
    if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
        next_path = quote(request.url.path, safe="/")
        return RedirectResponse(f"/login?next={next_path}", status_code=303)
    return JSONResponse({"detail": "Authentication required"}, status_code=401)


from app.routers import auth, dashboard, scraper, telegram

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(telegram.router)
app.include_router(scraper.router)


@app.on_event("startup")
async def resume_jobs_after_restart():
    # Semua akun yang memiliki session valid dapat dipilih per job/tab.
    with SessionLocal() as db:
        db.query(TelegramAccount).filter(TelegramAccount.session_str.isnot(None)).update(
            {TelegramAccount.is_active: 1}, synchronize_session=False
        )
        db.commit()
    await blast_manager.resume_incomplete_jobs()


@app.get("/")
def root_redirect(request: Request):
    destination = "/dashboard" if request.session.get("user_id") else "/login"
    return RedirectResponse(url=destination)


@app.get("/health", include_in_schema=False)
def healthcheck():
    """Readiness probe used by Railway before switching live traffic."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}
