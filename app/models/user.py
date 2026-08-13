from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    google_sub = Column(String(255), nullable=False, unique=True, index=True)
    email = Column(String(320), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=True)
    picture_url = Column(Text, nullable=True)
    role = Column(String(20), nullable=False, default="user")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)
