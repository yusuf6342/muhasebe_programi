"""Proje Takip MVP — kod, hedef kâr, belge bağlama idempotent."""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.database import Base
from database.models.proje import Proje, ProjeAyar, ProjeBelgeBaglanti, ProjeCari
import database.proje_service as proje_mod
from database.proje_service import ProjeService


@pytest.fixture()
def proje_db(monkeypatch):
    import database.models.proje  # noqa: F401

    tmp = tempfile.TemporaryDirectory(prefix="proje_mvp_")
    db_path = Path(tmp.name) / "p.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[Proje.__table__, ProjeCari.__table__, ProjeBelgeBaglanti.__table__, ProjeAyar.__table__],
    )
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    class _CM:
        def __enter__(self):
            self.s = Session()
            return self.s

        def __exit__(self, *a):
            try:
                self.s.commit()
            except Exception:
                self.s.rollback()
                raise
            finally:
                self.s.close()

    monkeypatch.setattr(proje_mod, "get_session", lambda: _CM())
    monkeypatch.setattr(proje_mod._db, "engine", engine)
    from database.session_manager import oturum

    oturum.company_id = 1
    oturum.role_kod = "YONETICI"
    oturum.kullanici_adi = "t"
    yield engine
    engine.dispose()
    tmp.cleanup()


def test_proje_olustur_ve_kar(proje_db):
    p = ProjeService.olustur("Mağaza X", hedef_gelir=1000, hedef_maliyet=700, tur="Mağaza")
    assert p["kod"].startswith("PRJ-")
    g = ProjeService.getir(p["id"])
    assert Decimal(g["hedef_kar"]) == Decimal("300")
    assert float(g["hedef_marj"]) == 30.0


def test_belge_bagla_idempotent(proje_db):
    p = ProjeService.olustur("İç")
    a = ProjeService.belge_bagla(p["id"], kaynak_tip="satis_fatura", kaynak_id="1", kaynak_no="SF-1", tutar_pay=50)
    b = ProjeService.belge_bagla(p["id"], kaynak_tip="satis_fatura", kaynak_id="1", kaynak_no="SF-1", tutar_pay=50)
    assert a["yeni"] is True
    assert b["yeni"] is False
    o = ProjeService.finansal_ozet(p["id"])
    assert o["bagli_belge"] == 1
