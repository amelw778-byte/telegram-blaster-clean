from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from datetime import datetime
from app.database import Base
from app.security import EncryptedText

class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label       = Column(String, nullable=True)          # nama/label akun
    phone       = Column(String, unique=True, nullable=False)
    session_str = Column(EncryptedText, nullable=True)   # encrypted session Telethon
    api_id      = Column(Integer, nullable=False)
    api_hash    = Column(EncryptedText, nullable=False)
    is_active   = Column(Integer, default=0)             # 1 = akun yang sedang dipakai
    created_at  = Column(DateTime, default=datetime.utcnow)
