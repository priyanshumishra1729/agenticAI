from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base()


def init_db() -> None:
    import app.models  # noqa: F401  (registers tables)

    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
