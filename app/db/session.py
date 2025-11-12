from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal = None


def init_engine_and_create_tables() -> None:
    global engine, SessionLocal
    if engine is None:
        engine = create_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
        )
        from app.models import parking_records  
        from app.models import user  

        Base.metadata.create_all(bind=engine)
    # Ensure SessionLocal is created even if engine already existed
    if SessionLocal is None and engine is not None:
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    if SessionLocal is None:
        init_engine_and_create_tables()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


