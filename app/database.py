import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

def _resolve_db_path() -> Path:
    explicit_path = os.getenv("BLASTER_DB_PATH")
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()

    # Railway exposes this automatically when a volume is attached. Keeping
    # the SQLite database inside that mount makes sessions and job history
    # survive deploys without requiring a second environment variable.
    volume_path = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    base_dir = Path(volume_path) if volume_path else Path.cwd()
    return (base_dir / "blaster.db").expanduser().resolve()


DB_PATH = _resolve_db_path()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA cache_size=-20000")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
