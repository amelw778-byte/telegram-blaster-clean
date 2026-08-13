from pathlib import Path
import base64
import binascii
import hmac
import os
import sys
import types

# Compatibility mode: when Railway's Root Directory is set to ``app``,
# Uvicorn imports this file as top-level ``main``. Register the current
# directory as the ``app`` package so existing absolute imports still work.
if __package__ in (None, ""):
    package = types.ModuleType("app")
    package.__path__ = [str(Path(__file__).resolve().parent)]
    package.__package__ = "app"
    sys.modules.setdefault("app", package)


from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from sqlalchemy import text

from app.database import Base, SessionLocal, engine
from app.models import BlastJob, BlastRecipient, TelegramAccount  # noqa: F401
from app.services.blast_manager import blast_manager

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

Base.metadata.create_all(bind=engine)

# Migrasi kolom baru ke DB yang sudah ada (aman dijalankan berkali-kali)
with engine.connect() as _conn:
    try:
        _conn.execute(text("ALTER TABLE blast_jobs ADD COLUMN delay_max_seconds REAL"))
        _conn.commit()
    except Exception:
        pass  # Kolom sudah ada, tidak masalah

app = FastAPI(title="Telegram Blaster - miawjugabisa.com")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

APP_USERNAME = os.getenv("APP_USERNAME", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD")


@app.middleware("http")
async def optional_basic_auth(request, call_next):
    """Protect the control panel when APP_PASSWORD is configured in Railway."""
    if not APP_PASSWORD or request.url.path == "/health":
        return await call_next(request)

    authorization = request.headers.get("authorization", "")
    try:
        scheme, encoded = authorization.split(" ", 1)
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        scheme = username = password = ""

    if (
        scheme.casefold() != "basic"
        or not hmac.compare_digest(username, APP_USERNAME)
        or not hmac.compare_digest(password, APP_PASSWORD)
    ):
        return JSONResponse(
            {"detail": "Authentication required"},
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Telegram Blaster"'},
        )
    return await call_next(request)

from app.routers import dashboard, telegram, scraper, wa

app.include_router(dashboard.router)
app.include_router(telegram.router)
app.include_router(scraper.router)
app.include_router(wa.router)


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
def root_redirect():
    return RedirectResponse(url="/dashboard")


@app.get("/health", include_in_schema=False)
def healthcheck():
    """Readiness probe used by Railway before switching live traffic."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}
