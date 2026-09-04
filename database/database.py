from pathlib import Path
from contextlib import contextmanager
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


# Proje ana klasörü
BASE_DIR = Path(__file__).resolve().parent.parent

# Veritabanı klasörü
DB_DIR = BASE_DIR / "data"
DB_DIR.mkdir(exist_ok=True)

# SQLite veritabanı
DATABASE_URL = f"sqlite:///{DB_DIR / 'muhasebe.db'}"


# Veritabanı bağlantısı
engine = create_engine(
    DATABASE_URL,
    echo=False
)


# Tüm veritabanı modellerimizin temel sınıfı
class Base(DeclarativeBase):
    pass


# Veritabanı oturumu
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False
)


@contextmanager
def get_session() -> Generator:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
