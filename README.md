# Telegram Blaster

FastAPI control panel for consent-based Telegram messaging, Telegram contact
exports, and WhatsApp account utilities. The application intentionally runs as
one Uvicorn worker because its per-account queues and locks live in-process.

## Railway

The repository includes a multi-stage Docker build and a `/health` readiness
endpoint. `railway.json` configures Railway to wait for that endpoint before
switching traffic to a new deployment.

Attach a Railway volume at `/data`. The app automatically detects
`RAILWAY_VOLUME_MOUNT_PATH` and stores `blaster.db` plus queued image uploads on
that volume. `BLASTER_DB_PATH` and `BLASTER_UPLOAD_DIR` can override those
locations when needed.

Recommended variables:

```text
APP_USERNAME=admin
APP_PASSWORD=<strong-random-password>
MAX_RECIPIENTS_PER_JOB=200
```

`APP_PASSWORD` enables HTTP Basic authentication for every control-panel route;
`/health` remains available to Railway. Never commit Telegram, WhatsApp, or
Railway credentials to this repository.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd wa_service && npm ci && cd ..
uvicorn main:app --host 127.0.0.1 --port 8080 --workers 1
```
