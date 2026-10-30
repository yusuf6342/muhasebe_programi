"""Yıllık Devir Aşama 1–2: şema, iş kimliği, eşleştirme idempotent, ayarlar."""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database.database import Base
from database.models.devir import (
    SCHEMA_SURUM,
    DevirAyar,
    DevirDenetim,
    DevirEslesme,
    DevirIs,
)
from database.models.donem import Donem
from database.models.firma import Firma
import database.devir_service as devir_mod
from database.devir_service import DevirService, MIMARI_HARITA


@pytest.fixture()
def devir_db(monkeypatch):
    import database.models.devir  # noqa: F401
    import database.models.donem  # noqa: F401
    import database.models.firma  # noqa: F401

    tmp = tempfile.TemporaryDirectory(prefix="devir_asama2_")
    db_path = Path(tmp.name) / "devir.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            Firma.__table__,
            Donem.__table__,
            DevirAyar.__table__,
            DevirIs.__table__,
            DevirEslesme.__table__,
            DevirDenetim.__table__,
        ],
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

    monkeypatch.setattr(devir_mod, "get_session", lambda: _CM())
    monkeypatch.setattr(devir_mod._db, "engine", engine)
    DevirService._schema_hazir = False

    from database.session_manager import oturum

    oturum.company_id = 1
    oturum.firma_kodu = "T"
    oturum.firma_unvan = "Test"
    oturum.user_id = 1
    oturum.kullanici_adi = "test"
    oturum.role_kod = "YONETICI"

    with _CM() as s:
        f = Firma(firma_kodu="T", unvan="Test", aktif=True)
        s.add(f)
        s.flush()
        d1 = Donem(
            firma_id=f.id,
            donem_adi="2026",
            baslangic_tarihi=date(2026, 1, 1),
            bitis_tarihi=date(2026, 12, 31),
            aktif=True,
            kapali=False,
            varsayilan=True,
        )
        d2 = Donem(
            firma_id=f.id,
            donem_adi="2027",
            baslangic_tarihi=date(2027, 1, 1),
            bitis_tarihi=date(2027, 12, 31),
            aktif=True,
            kapali=False,
            varsayilan=False,
        )
        s.add_all([d1, d2])
        s.flush()
        ids = (d1.id, d2.id)

    yield {"engine": engine, "donem_ids": ids, "tmp": tmp}
    engine.dispose()
    tmp.cleanup()


def test_mimari_harita_asama1():
    h = DevirService.mimari_harita()
    assert "donem" in h and "cari_kapatma" in h
    assert str(SCHEMA_SURUM) in h["devir_sema"]
    assert MIMARI_HARITA["firma"]


def test_schema_ve_is_olustur(devir_db):
    d1, d2 = devir_db["donem_ids"]
    DevirService.ensure_schema(devir_db["engine"])
    is_ = DevirService.is_olustur(
        kaynak_donem_id=d1,
        hedef_donem_id=d2,
        kesim_tarihi=date(2026, 12, 31),
        acilis_tarihi=date(2027, 1, 1),
        devir_turu="ON_DEVIR",
    )
    assert is_["is_no"].startswith("DEV-2026-")
    assert is_["schema_surum"] == SCHEMA_SURUM
    assert is_["onizleme_gecerli"] is False
    assert is_["ayarlar_surum"] >= 1

    # Aynı çiftte ikinci açık iş engellenir
    with pytest.raises(ValueError, match="açık iş"):
        DevirService.is_olustur(
            kaynak_donem_id=d1,
            hedef_donem_id=d2,
            kesim_tarihi=date(2026, 12, 31),
            acilis_tarihi=date(2027, 1, 1),
        )


def test_eslesme_idempotent(devir_db):
    d1, d2 = devir_db["donem_ids"]
    is_ = DevirService.is_olustur(
        kaynak_donem_id=d1,
        hedef_donem_id=d2,
        kesim_tarihi=date(2026, 12, 31),
        acilis_tarihi=date(2027, 1, 1),
    )
    a = DevirService.eslesme_kaydet(
        is_["id"],
        modul="CARI",
        kaynak_tip="cari_acik",
        kaynak_id="42",
        benzersizlik_anahtar=f"1:{d1}:{d2}:CARI:42",
        hedef_id="A1",
        tutar=100,
        para_birimi="TRY",
    )
    b = DevirService.eslesme_kaydet(
        is_["id"],
        modul="CARI",
        kaynak_tip="cari_acik",
        kaynak_id="42",
        benzersizlik_anahtar=f"1:{d1}:{d2}:CARI:42",
        hedef_id="A2",
        tutar=100,
        para_birimi="TRY",
    )
    assert a["yeni"] is True
    assert b["yeni"] is False
    assert b["hedef_id"] == "A1"


def test_ayar_surum(devir_db):
    p1 = DevirService.ayarlari_kaydet({"stok_maliyet": "FIFO"})
    assert p1["ayarlar"]["stok_maliyet"] == "FIFO"
    p2 = DevirService.ayarlari_kaydet({"stok_maliyet": "AO"})
    assert p2["surum"] == p1["surum"] + 1


def test_kaynak_hedef_ayni_red(devir_db):
    d1, _ = devir_db["donem_ids"]
    with pytest.raises(ValueError, match="aynı"):
        DevirService.is_olustur(
            kaynak_donem_id=d1,
            hedef_donem_id=d1,
            kesim_tarihi=date(2026, 12, 31),
            acilis_tarihi=date(2027, 1, 1),
        )


def test_kesim_cari_sonrasi_kapatma_geri_eklenir(devir_db):
    """Kesim sonrası tahsilat, 2026 kapanış açığını azaltmamalı."""
    from decimal import Decimal

    from sqlalchemy import text

    engine = devir_db["engine"]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS cari_kartlar (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cari_kodu VARCHAR(20) NOT NULL,
                    unvan VARCHAR(200) NOT NULL,
                    cari_turu VARCHAR(20) NOT NULL,
                    aktif BOOLEAN NOT NULL DEFAULT 1,
                    is_deleted BOOLEAN NOT NULL DEFAULT 0
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS cari_satis_hareketleri (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cari_id INTEGER NOT NULL,
                    satis_tarihi DATE NOT NULL,
                    belge_no VARCHAR(50) NOT NULL,
                    satis_tutari NUMERIC(18,2) NOT NULL,
                    kalan_acik_tutar NUMERIC(18,2) NOT NULL,
                    para_birimi VARCHAR(3) NOT NULL DEFAULT 'TRY',
                    doviz_tutari NUMERIC(18,2) NOT NULL DEFAULT 0,
                    kur NUMERIC(18,6) NOT NULL DEFAULT 1,
                    borc_esasi VARCHAR(20) NOT NULL DEFAULT 'TL_SABIT'
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS cari_kapatmalar (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    islem_kimligi VARCHAR(36) NOT NULL,
                    cari_id INTEGER NOT NULL,
                    kaynak_belge_no VARCHAR(50) NOT NULL,
                    kaynak_tur VARCHAR(30) NOT NULL,
                    kaynak_hareket_id INTEGER,
                    hedef_hareket_id INTEGER NOT NULL,
                    hedef_belge_no VARCHAR(50) NOT NULL,
                    tutar NUMERIC(18,2) NOT NULL,
                    para_birimi VARCHAR(3) NOT NULL DEFAULT 'TRY',
                    tarih DATE NOT NULL,
                    yontem VARCHAR(10) NOT NULL DEFAULT 'FIFO',
                    kullanici_id INTEGER,
                    iptal BOOLEAN NOT NULL DEFAULT 0
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO cari_kartlar (cari_kodu, unvan, cari_turu) VALUES ('C1','Test','Müşteri')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO cari_satis_hareketleri
                (cari_id, satis_tarihi, belge_no, satis_tutari, kalan_acik_tutar)
                VALUES (1, '2026-11-01', 'SF-1', 60000, 30000)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO cari_kapatmalar
                (islem_kimligi, cari_id, kaynak_belge_no, kaynak_tur, hedef_hareket_id,
                 hedef_belge_no, tutar, tarih, iptal)
                VALUES
                ('t1', 1, 'THS-1', 'TAHSILAT', 1, 'SF-1', 30000, '2026-12-15', 0),
                ('t2', 1, 'THS-2', 'TAHSILAT', 1, 'SF-1', 10000, '2027-01-05', 0)
                """
            )
        )

    paket = DevirService.kesim_cari(date(2026, 12, 31))
    assert paket["kalem_sayisi"] == 1
    assert Decimal(str(paket["satirlar"][0]["kalan"])) == Decimal("40000")


def test_uygula_idempotent_eslesme(devir_db, monkeypatch):
    """Uygulama ikinci kez çalışınca eşleşme çoğalmaz."""
    from decimal import Decimal

    from sqlalchemy import text

    engine = devir_db["engine"]
    d1, d2 = devir_db["donem_ids"]
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS cari_kartlar (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cari_kodu VARCHAR(20) NOT NULL,
                    unvan VARCHAR(200) NOT NULL,
                    cari_turu VARCHAR(20) NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS cari_satis_hareketleri (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cari_id INTEGER NOT NULL,
                    satis_tarihi DATE NOT NULL,
                    belge_no VARCHAR(50) NOT NULL,
                    satis_tutari NUMERIC(18,2) NOT NULL,
                    kalan_acik_tutar NUMERIC(18,2) NOT NULL,
                    para_birimi VARCHAR(3) NOT NULL DEFAULT 'TRY',
                    doviz_tutari NUMERIC(18,2) NOT NULL DEFAULT 0,
                    kur NUMERIC(18,6) NOT NULL DEFAULT 1,
                    borc_esasi VARCHAR(20) NOT NULL DEFAULT 'TL_SABIT'
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS cari_kapatmalar (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    islem_kimligi VARCHAR(36) NOT NULL,
                    cari_id INTEGER NOT NULL,
                    kaynak_belge_no VARCHAR(50) NOT NULL,
                    kaynak_tur VARCHAR(30) NOT NULL,
                    hedef_hareket_id INTEGER NOT NULL,
                    hedef_belge_no VARCHAR(50) NOT NULL,
                    tutar NUMERIC(18,2) NOT NULL,
                    para_birimi VARCHAR(3) NOT NULL DEFAULT 'TRY',
                    tarih DATE NOT NULL,
                    yontem VARCHAR(10) NOT NULL DEFAULT 'FIFO',
                    iptal BOOLEAN NOT NULL DEFAULT 0
                )
                """
            )
        )
        conn.execute(text("INSERT INTO cari_kartlar VALUES (1,'C1','T','Müşteri')"))
        conn.execute(
            text(
                "INSERT INTO cari_satis_hareketleri "
                "(cari_id,satis_tarihi,belge_no,satis_tutari,kalan_acik_tutar) "
                "VALUES (1,'2026-06-01','SF-X',100,100)"
            )
        )

    # Stok kesimini boş bırak
    class _BosStok:
        @staticmethod
        def fifo_envanter_degerleri(session, tarih=None):
            return {}

    monkeypatch.setattr(
        "database.stok_service.StokService",
        _BosStok,
        raising=False,
    )
    import database.devir_service as dm

    monkeypatch.setattr(
        dm.DevirService,
        "kesim_stok",
        classmethod(lambda cls, kesim_tarihi: {
            "satir_sayisi": 0,
            "deger_bilinen": "0",
            "negatif_satir": 0,
            "sifir_maliyet_miktar": "0",
            "ornek_satirlar": [],
            "not": "",
        }),
    )

    is_ = DevirService.is_olustur(
        kaynak_donem_id=d1,
        hedef_donem_id=d2,
        kesim_tarihi=date(2026, 12, 31),
        acilis_tarihi=date(2027, 1, 1),
        kapsam=["CARI"],
    )
    DevirService.onizleme_hesapla(is_["id"])
    a = DevirService.uygula(is_["id"], yedek_zorunlu=False)
    assert a["yeni_eslesme"] >= 1
    # Tamamlanmış işe tekrar uygula
    b = DevirService.uygula(is_["id"], yedek_zorunlu=False)
    assert b["yeni_eslesme"] == 0
