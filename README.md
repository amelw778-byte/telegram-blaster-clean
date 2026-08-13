# Telegram Blaster

PorsLabs FastAPI control panel for consent-based Telegram messaging and
Telegram contact exports. Each Google user owns an isolated set of Telegram
accounts, blast jobs, uploads, and scraper jobs. The application intentionally
runs as one Uvicorn worker because its per-account queues and locks live in-process.

## Railway

The repository includes a multi-stage Docker build and a `/health` readiness
endpoint. `railway.json` configures Railway to wait for that endpoint before
switching traffic to a new deployment.

Production uses PostgreSQL through `DATABASE_URL`. During the first PostgreSQL
boot, an existing `/data/blaster.db` is copied transactionally and retained as
a recovery archive. The Railway volume at `/data` remains attached for queued
image uploads and the legacy archive. Local development falls back to SQLite
when `DATABASE_URL` is absent.

Google sign-in variables:

```text
GOOGLE_CLIENT_ID=<google-oauth-web-client-id>
GOOGLE_CLIENT_SECRET=<google-oauth-web-client-secret>
SESSION_SECRET=<strong-random-secret>
GOOGLE_REDIRECT_URI=https://your-domain.example/auth/google/callback
BOOTSTRAP_OWNER_EMAIL=owner@example.com
# Optional, comma-separated invite-only access:
GOOGLE_ALLOWED_EMAILS=owner@example.com,team@example.com
MAX_RECIPIENTS_PER_JOB=200
# Optional, untuk fitur Lupa Password
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=mailer@example.com
SMTP_PASSWORD=change-me
SMTP_FROM_EMAIL=mailer@example.com
SMTP_USE_TLS=true
APP_BASE_URL=https://your-app.example.com
DATABASE_URL=postgresql://...
DATA_ENCRYPTION_KEY=<strong-random-secret>
# Only while rotating keys; remove after all encrypted rows have been rewritten:
DATA_ENCRYPTION_KEY_OLD=<previous-key>
```

Existing Telegram data is assigned to `BOOTSTRAP_OWNER_EMAIL` on the first
migration. `/health` remains public for Railway. Never commit Google, Telegram,
or Railway credentials to this repository.

Pengguna dapat mendaftar dan masuk menggunakan username/password. Password
disimpan sebagai hash scrypt dengan salt unik. Google OAuth tetap tersedia
sebagai opsi ketika kredensialnya dikonfigurasi. Fitur pemulihan password hanya
aktif setelah konfigurasi SMTP diisi.

`session_str` dan `api_hash` Telegram dienkripsi menggunakan Fernet sebelum
masuk database. Sesi web dicatat di tabel `device_sessions`, sehingga pengguna
dapat mencabut akses per browser melalui halaman **Keamanan**. PostgreSQL
production dilindungi oleh Railway PITR dan jadwal backup harian, mingguan,
serta bulanan. Prosedur operasional ada di `OPERATIONS.md`.

## Local run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8080 --workers 1
```
