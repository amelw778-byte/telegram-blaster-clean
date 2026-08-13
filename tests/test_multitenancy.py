import base64
import hashlib
import json
import os
from pathlib import Path
import re
import time
import unittest
from datetime import datetime, timedelta

from itsdangerous import TimestampSigner


TEST_DB = Path("/tmp/porslabs-multitenancy-test.db")
TEST_CSRF = "test-csrf-token"
TEST_DB.unlink(missing_ok=True)
os.environ["BLASTER_DB_PATH"] = str(TEST_DB)
os.environ["SESSION_SECRET"] = "test-session-secret-for-porslabs"
os.environ["BOOTSTRAP_OWNER_EMAIL"] = "owner@example.com"
os.environ.pop("APP_PASSWORD", None)
os.environ.pop("GOOGLE_CLIENT_ID", None)
os.environ.pop("GOOGLE_CLIENT_SECRET", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import hash_password, upsert_google_user, verify_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import BlastJob, TelegramAccount, User  # noqa: E402
from app.routers import scraper  # noqa: E402


def _session_cookie(user_id: int) -> str:
    payload = base64.b64encode(
        json.dumps({
            "user_id": user_id,
            "csrf_token": TEST_CSRF,
            "expires_at": int(time.time()) + 3600,
        }).encode("utf-8")
    )
    return TimestampSigner(os.environ["SESSION_SECRET"]).sign(payload).decode("utf-8")


def _csrf_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    if not match:
        raise AssertionError("CSRF token not found")
    return match.group(1)


class TenantIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with SessionLocal() as db:
            cls.owner = db.query(User).filter(User.email == "owner@example.com").one()
            cls.other = User(
                google_sub="google-other-user",
                email="other@example.com",
                name="Other User",
            )
            db.add(cls.other)
            db.flush()

            cls.owner_account = TelegramAccount(
                user_id=cls.owner.id,
                label="Owner Account",
                phone="+620000000001",
                session_str="owner-session",
                api_id=1,
                api_hash="owner-hash",
                is_active=1,
            )
            cls.other_account = TelegramAccount(
                user_id=cls.other.id,
                label="Other Secret Account",
                phone="+620000000002",
                session_str="other-session",
                api_id=2,
                api_hash="other-hash",
                is_active=1,
            )
            db.add_all([cls.owner_account, cls.other_account])
            db.flush()

            cls.owner_job = BlastJob(
                user_id=cls.owner.id,
                status="completed",
                message="owner job",
                accounts_json="[]",
                consent_confirmed=True,
            )
            cls.other_job = BlastJob(
                user_id=cls.other.id,
                status="completed",
                message="other secret job",
                accounts_json="[]",
                consent_confirmed=True,
            )
            db.add_all([cls.owner_job, cls.other_job])
            db.commit()
            for item in (cls.owner, cls.other, cls.owner_account, cls.other_account, cls.owner_job, cls.other_job):
                db.refresh(item)
            cls.owner_id = cls.owner.id
            cls.other_id = cls.other.id
            cls.owner_account_id = cls.owner_account.id
            cls.other_account_id = cls.other_account.id
            cls.other_job_id = cls.other_job.id

    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.set("porslabs_session", _session_cookie(self.owner_id))

    def test_dashboard_only_renders_current_users_data(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Owner Account", response.text)
        self.assertNotIn("Other Secret Account", response.text)
        self.assertNotIn("other secret job", response.text)

    def test_other_users_job_is_not_addressable(self):
        response = self.client.get(f"/api/jobs/{self.other_job_id}")
        self.assertEqual(response.status_code, 404)

    def test_other_users_account_cannot_be_deleted(self):
        response = self.client.post(
            f"/delete-account/{self.other_account_id}",
            data={"csrf_token": TEST_CSRF},
        )
        self.assertEqual(response.status_code, 404)
        with SessionLocal() as db:
            self.assertIsNotNone(db.get(TelegramAccount, self.other_account_id))

    def test_scraper_poll_is_scoped_to_its_owner(self):
        scraper._jobs["other-job"] = {
            "user_id": self.other_id,
            "status": "done",
            "contacts": {"@secret"},
            "log": ["secret"],
            "total": 1,
        }
        response = self.client.get("/api/scraper/other-job")
        self.assertEqual(response.status_code, 404)

    def test_whatsapp_routes_are_removed(self):
        response = self.client.get("/wa")
        self.assertEqual(response.status_code, 404)

    def test_new_google_user_is_created_active(self):
        with SessionLocal() as db:
            user = upsert_google_user(db, {
                "sub": "new-google-sub",
                "email": "new-google@example.com",
                "email_verified": True,
                "name": "New Google User",
            })
            self.assertTrue(user.is_active)
            self.assertEqual(user.role, "user")

    def test_bootstrap_owner_is_claimed_without_losing_existing_data(self):
        with SessionLocal() as db:
            owner = upsert_google_user(db, {
                "sub": "owner-real-google-sub",
                "email": "owner@example.com",
                "email_verified": True,
                "name": "Owner From Google",
            })
            account = db.get(TelegramAccount, self.owner_account_id)
            self.assertEqual(account.user_id, owner.id)
            self.assertEqual(owner.google_sub, "owner-real-google-sub")

    def test_unauthenticated_browser_is_sent_to_login(self):
        client = TestClient(app, follow_redirects=False)
        response = client.get("/dashboard", headers={"Accept": "text/html"})
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login"))

    def test_basic_auth_is_not_accepted(self):
        client = TestClient(app, follow_redirects=False)
        credentials = base64.b64encode(b"admin:removed").decode("ascii")
        response = client.get(
            "/dashboard",
            headers={
                "Accept": "text/html",
                "Authorization": f"Basic {credentials}",
            },
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login"))
        self.assertNotIn("www-authenticate", response.headers)

    def test_login_uses_scheme_independent_static_assets(self):
        client = TestClient(app)
        response = client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/static/css/porslabs-app.css"', response.text)
        self.assertIn('src="/static/js/porslabs-app.js"', response.text)
        self.assertNotIn("http://testserver/static/", response.text)

    def test_local_registration_and_password_login(self):
        client = TestClient(app, follow_redirects=False)
        register_page = client.get("/register")
        response = client.post(
            "/register",
            data={
                "csrf_token": _csrf_from(register_page.text),
                "username": "new.member",
                "email": "local-member@example.com",
                "password": "SafePassword123!",
                "password_confirmation": "SafePassword123!",
            },
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/dashboard")

        with SessionLocal() as db:
            user = db.query(User).filter(User.username == "new.member").one()
            self.assertNotIn("SafePassword123!", user.password_hash)
            self.assertTrue(verify_password("SafePassword123!", user.password_hash))
            self.assertTrue(user.google_sub.startswith("local:"))

        second_client = TestClient(app, follow_redirects=False)
        login_page = second_client.get("/login")
        login = second_client.post(
            "/login",
            data={
                "csrf_token": _csrf_from(login_page.text),
                "identity": "new.member",
                "password": "SafePassword123!",
                "remember_me": "1",
                "next_path": "/dashboard",
            },
        )
        self.assertEqual(login.status_code, 303)
        self.assertEqual(login.headers["location"], "/dashboard")
        dashboard = second_client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)

    def test_wrong_local_password_is_rejected(self):
        with SessionLocal() as db:
            user = User(
                google_sub="local:wrong-password-test",
                username="wrongpass",
                email="wrong-password@example.com",
                password_hash=hash_password("CorrectPassword123!"),
                name="Wrong Password Test",
            )
            db.add(user)
            db.commit()

        client = TestClient(app, follow_redirects=False)
        login_page = client.get("/login")
        response = client.post(
            "/login",
            data={
                "csrf_token": _csrf_from(login_page.text),
                "identity": "wrongpass",
                "password": "not-the-password",
                "next_path": "/dashboard",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Username atau password tidak sesuai", response.text)

    def test_password_reset_token_is_single_use(self):
        token = "single-use-password-reset-token"
        with SessionLocal() as db:
            user = User(
                google_sub="local:password-reset-test",
                username="resetmember",
                email="reset-member@example.com",
                password_hash=hash_password("OldPassword123!"),
                password_reset_token_hash=hashlib.sha256(token.encode()).hexdigest(),
                password_reset_expires_at=datetime.utcnow() + timedelta(minutes=30),
                name="Reset Member",
            )
            db.add(user)
            db.commit()
            user_id = user.id

        client = TestClient(app, follow_redirects=False)
        reset_page = client.get(f"/reset-password?token={token}")
        self.assertEqual(reset_page.status_code, 200)
        response = client.post(
            "/reset-password",
            data={
                "csrf_token": _csrf_from(reset_page.text),
                "token": token,
                "password": "NewPassword123!",
                "password_confirmation": "NewPassword123!",
            },
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?notice=password_reset")

        with SessionLocal() as db:
            user = db.get(User, user_id)
            self.assertTrue(verify_password("NewPassword123!", user.password_hash))
            self.assertIsNone(user.password_reset_token_hash)

        reused = client.get(f"/reset-password?token={token}")
        self.assertIn("tidak valid atau sudah kedaluwarsa", reused.text)

    def test_forgot_password_is_honest_when_email_is_not_configured(self):
        client = TestClient(app)
        response = client.get("/forgot-password")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Layanan email pemulihan belum diaktifkan", response.text)
        self.assertIn("disabled", response.text)


if __name__ == "__main__":
    unittest.main()
