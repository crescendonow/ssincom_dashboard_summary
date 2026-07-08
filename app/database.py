# app/database.py
# คัดจาก ssincom_bill/app/database.py — normalize DATABASE_URL + engine + SessionLocal + Base
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base


def _normalize_db_url(url: str) -> str:
    if not url:
        return url
    # รองรับรูปแบบ postgres:// -> postgresql:// (SQLAlchemy ต้องการ postgresql://)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)

    # ถ้าเป็น public host (เช่น *.railway.app / proxy.rlwy.net) และยังไม่ใส่ sslmode → เติมให้
    host_is_internal = ".railway.internal" in url
    already_has_ssl = "sslmode=" in url
    if (not host_is_internal) and (not already_has_ssl):
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return url


DATABASE_URL = _normalize_db_url(os.getenv("DATABASE_URL", ""))

# pool_pre_ping กัน connection ตาย + future=True
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()
