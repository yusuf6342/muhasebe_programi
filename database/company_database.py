"""Firma operasyon veritabanı yöneticisi — dağınık SQLite bağlantısı açılmaz."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def _sqlite_pragma(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def _engine_olustur(db_path: Path) -> Engine:
    url = f"sqlite:///{db_path.resolve().as_posix()}"
    eng = create_engine(
        url,
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    event.listen(eng, "connect", _sqlite_pragma)
    return eng


class CompanyDatabase:
    """Aktif firma DB bağlantısı — aç/kapat/değiştir/transaction."""

    def __init__(self, companies_dir: Path):
        self.companies_dir = Path(companies_dir)
        self.companies_dir.mkdir(parents=True, exist_ok=True)
        self._engine: Engine | None = None
        self._session_factory: sessionmaker | None = None
        self._company_id: int | None = None
        self._db_path: Path | None = None

    @property
    def engine(self) -> Engine | None:
        return self._engine

    @property
    def db_path(self) -> Path | None:
        return self._db_path

    @property
    def company_id(self) -> int | None:
        return self._company_id

    @property
    def acik(self) -> bool:
        return self._engine is not None

    def open(self, company_id: int, db_path: str | Path) -> Engine:
        yol = Path(db_path).resolve()
        if self._engine is not None and self._db_path == yol and self._company_id == company_id:
            return self._engine
        self.close()
        yol.parent.mkdir(parents=True, exist_ok=True)
        self._engine = _engine_olustur(yol)
        self._session_factory = sessionmaker(
            bind=self._engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self._company_id = company_id
        self._db_path = yol
        return self._engine

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
        self._engine = None
        self._session_factory = None
        self._company_id = None
        self._db_path = None

    def yeni_firma_db_yolu(self, firma_uid: str | None = None) -> Path:
        """Ünvan değil, benzersiz kimlik ile dosya adı."""
        uid = firma_uid or str(uuid.uuid4())
        return self.companies_dir / f"company_{uid}.db"

    def firma_db_olustur(
        self,
        base_metadata,
        firma_uid: str | None = None,
        hedef_yol: Path | None = None,
    ) -> Path:
        """Boş firma DB + tablolar. Başarısızsa dosyayı silmeye çalışır."""
        yol = Path(hedef_yol) if hedef_yol is not None else self.yeni_firma_db_yolu(firma_uid)
        yol.parent.mkdir(parents=True, exist_ok=True)
        eng = None
        try:
            eng = _engine_olustur(yol)
            base_metadata.create_all(eng)
            return yol
        except Exception:
            if eng is not None:
                eng.dispose()
            if yol.exists():
                try:
                    yol.unlink()
                except OSError:
                    pass
            raise
        finally:
            if eng is not None:
                eng.dispose()

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        if self._session_factory is None:
            raise RuntimeError("Aktif firma veritabanı seçilmedi.")
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


# Modül düzeyinde tek örnek — database.py bağlar
company_db: CompanyDatabase | None = None
