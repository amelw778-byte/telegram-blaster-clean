import os

from sqlalchemy import inspect, text

from app.database import Base, SessionLocal, engine
from app.models import User


def _bootstrap_email() -> str:
    return os.getenv("BOOTSTRAP_OWNER_EMAIL", "amelw778@gmail.com").strip().casefold()


def initialize_database() -> None:
    """Create new tables and idempotently bring the existing SQLite DB forward."""
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    if "users" in table_names:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        with engine.begin() as connection:
            if "username" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(32)"))
            if "password_hash" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN password_hash TEXT"))
            if "password_reset_token_hash" not in user_columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN password_reset_token_hash VARCHAR(64)")
                )
            if "password_reset_expires_at" not in user_columns:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN password_reset_expires_at DATETIME")
                )
            connection.execute(
                text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)")
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_password_reset_token_hash "
                    "ON users (password_reset_token_hash)"
                )
            )

    with SessionLocal() as db:
        email = _bootstrap_email()
        owner = db.query(User).filter(User.email == email).first()
        if not owner:
            owner = User(
                google_sub=f"bootstrap:{email}",
                email=email,
                name="PorsLabs Admin",
                role="admin",
            )
            db.add(owner)
            db.commit()
            db.refresh(owner)
        owner_id = owner.id

    with engine.begin() as connection:
        if "blast_jobs" in table_names:
            blast_columns = {column["name"] for column in inspect(engine).get_columns("blast_jobs")}
            if "delay_max_seconds" not in blast_columns:
                connection.execute(text("ALTER TABLE blast_jobs ADD COLUMN delay_max_seconds REAL"))
            if "user_id" not in blast_columns:
                connection.execute(text("ALTER TABLE blast_jobs ADD COLUMN user_id INTEGER REFERENCES users(id)"))
            connection.execute(
                text("UPDATE blast_jobs SET user_id = :owner_id WHERE user_id IS NULL"),
                {"owner_id": owner_id},
            )
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_blast_jobs_user_id ON blast_jobs (user_id)"))

        if "telegram_accounts" in table_names:
            account_columns = {
                column["name"] for column in inspect(engine).get_columns("telegram_accounts")
            }
            if "user_id" not in account_columns:
                connection.execute(
                    text("ALTER TABLE telegram_accounts ADD COLUMN user_id INTEGER REFERENCES users(id)")
                )
            connection.execute(
                text("UPDATE telegram_accounts SET user_id = :owner_id WHERE user_id IS NULL"),
                {"owner_id": owner_id},
            )
            connection.execute(
                text("CREATE INDEX IF NOT EXISTS ix_telegram_accounts_user_id ON telegram_accounts (user_id)")
            )
