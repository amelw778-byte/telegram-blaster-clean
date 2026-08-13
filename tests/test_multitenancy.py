import base64
import json
import os
from pathlib import Path
import unittest

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

from app.auth import upsert_google_user  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import BlastJob, TelegramAccount, User  # noqa: E402
from app.routers import scraper  # noqa: E402


def _session_cookie(user_id: int) -> str:
    payload = base64.b64encode(
        json.dumps({"user_id": user_id, "csrf_token": TEST_CSRF}).encode("utf-8")
    )
    return TimestampSigner(os.environ["SESSION_SECRET"]).sign(payload).decode("utf-8")


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


if __name__ == "__main__":
    unittest.main()
