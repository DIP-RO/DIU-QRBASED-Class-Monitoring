import os
import time
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from backend.config import get_settings

settings = get_settings()
if settings.database_url.startswith("sqlite"):
    path = settings.database_url.replace("sqlite:///", "", 1)
    if path != ":memory:": os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False, "timeout": 5})

@event.listens_for(engine, "connect")
def sqlite_pragmas(dbapi, _):
    cur = dbapi.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=FULL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()

class Base(DeclarativeBase): pass
SessionLocal = sessionmaker(engine, expire_on_commit=False)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

def commit_with_retry(db, attempts=4):
    for idx in range(attempts):
        try: db.commit(); return
        except OperationalError as exc:
            db.rollback()
            if "locked" not in str(exc).lower() or idx == attempts - 1: raise
            time.sleep(0.04 * (2 ** idx))

