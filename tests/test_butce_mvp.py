"""Bütçe MVP — eşit aylık dağıtım, idempotent kayıt, gerçekleşen sıfır uydurmaz."""

from __future__ import annotations

import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Column,
    create_engine,
    select,
    text,
)
from sqlalchemy.orm import sessionmaker

from database.database import Base
from database.butce_service import ButceService, dagit_yillik_esit
from database.models.butce import ButcePlan, ButceSatir, OLCU_SATIS
import database.butce_service as butce_mod


@pytest.fixture()
def butce_db(monkeypatch):
    """İzole temp SQLite — canlı firma DB'sine dokunmaz."""
    import database.models.butce  # noqa: F401

    tmp = tempfile.TemporaryDirectory(prefix="butce_mvp_")
    db_path = Path(tmp.name) / "butce.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[ButcePlan.__table__, ButceSatir.__table__],
    )
    # Minimal satış faturası tablosu (ORM FK zinciri olmadan; gerçekleşen sorgusu için)
    meta = MetaData()
    Table(
        "satis_faturalari",
        meta,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("fatura_no", String(30), nullable=False),
        Column("fatura_tarihi", Date, nullable=False),
        Column("vade_gunu", Integer, nullable=False, default=0),
        Column("vade_tarihi", Date, nullable=False),
        Column("cari_id", Integer, nullable=False, default=1),
        Column("durum", String(20), nullable=False, default="TASLAK"),
        Column("onaylandi", Boolean, nullable=False, default=False),
        Column("depo", String(100), nullable=False, default="ANA DEPO"),
        Column("tahsilat_tutari", Numeric(18, 2), nullable=False, default=0),
        Column("para_birimi", String(3), nullable=False, default="TRY"),
        Column("kur", Numeric(18, 6), nullable=False, default=1),
        Column("kur_turu", String(30), nullable=False, default="forex_selling"),
        Column("kur_kaynagi", String(20), nullable=False, default="TCMB"),
        Column("kur_sabitlendi", Boolean, nullable=False, default=False),
        Column("borc_esasi", String(20), nullable=False, default="TL_SABIT"),
        Column("doviz_ara_toplam", Numeric(18, 2), nullable=False, default=0),
        Column("tl_matrah", Numeric(18, 2), nullable=False, default=0),
        Column("tl_kdv", Numeric(18, 2), nullable=False, default=0),
        Column("tl_genel_toplam", Numeric(18, 2), nullable=False, default=0),
        Column("tl_brut_toplam", Numeric(18, 2), nullable=False, default=0),
        Column("genel_islem_orani", Numeric(12, 6), nullable=False, default=0),
        Column("genel_islem_tutari", Numeric(18, 2), nullable=False, default=0),
        Column("fon_ek_bedel_tutari", Numeric(18, 2), nullable=False, default=0),
        Column("fon_ek_bedel_kdv", Numeric(18, 2), nullable=False, default=0),
        Column("rounding_applied", Boolean, nullable=False, default=False),
        Column("rounding_version", Integer, nullable=False, default=0),
        Column("invoice_rounding_adjustment", Numeric(18, 2), nullable=False, default=0),
        Column("row_version", Integer, nullable=False, default=1),
        Column("olusturma_tarihi", DateTime, nullable=False, default=datetime.now),
        Column("is_deleted", Boolean, nullable=False, default=False),
        Column("cancelled_at", DateTime, nullable=True),
    ).create(bind=engine, checkfirst=True)

    Session = sessionmaker(bind=engine, future=True, expire_on_commit=False)

    class _Ctx:
        def __init__(self, sess):
            self.sess = sess

        def __enter__(self):
            return self.sess

        def __exit__(self, exc_type, exc, tb):
            if exc_type:
                self.sess.rollback()
            else:
                self.sess.commit()
            self.sess.close()
            return False

    def fake_get_session():
        return _Ctx(Session())

    monkeypatch.setattr(butce_mod, "get_session", fake_get_session)
    monkeypatch.setattr(butce_mod, "engine", engine)
    ButceService._schema_hazir = False
    ButceService.ensure_schema(engine)
    yield {"Session": Session, "engine": engine}
    ButceService._schema_hazir = False
    try:
        engine.dispose()
    except Exception:
        pass
    try:
        tmp.cleanup()
    except PermissionError:
        pass


def test_esit_aylik_dagitim_toplami_yillik():
    """Kuruş artığı son aya; 12 ay toplamı yıllık tutara eşit."""
    for yillik in (
        Decimal("12000.00"),
        Decimal("10000.00"),
        Decimal("100.01"),
        Decimal("1.00"),
        Decimal("0.10"),
    ):
        aylar = dagit_yillik_esit(yillik, 12)
        assert len(aylar) == 12
        assert sum(aylar, Decimal("0")) == yillik
        assert len(set(aylar[:11])) == 1
        assert aylar[11] == yillik - aylar[0] * 11


def test_yillik_dagit_kaydet_ve_idempotent(butce_db):
    plan = ButceService.plan_olustur("Test Plan", 2026, firma_id=1)
    assert plan["kod"].startswith("BTC-2026-")
    satirlar1 = ButceService.yillik_dagit_ve_kaydet(
        plan["id"], Decimal("12000.00"), olcu_turu=OLCU_SATIS, firma_id=1
    )
    assert len(satirlar1) == 12
    assert sum((s["tutar"] for s in satirlar1), Decimal("0")) == Decimal("12000.00")

    ButceService.yillik_dagit_ve_kaydet(
        plan["id"], Decimal("12000.00"), olcu_turu=OLCU_SATIS, firma_id=1
    )
    Session = butce_db["Session"]
    with Session() as s:
        n = len(
            list(
                s.scalars(
                    select(ButceSatir).where(
                        ButceSatir.plan_id == plan["id"],
                        ButceSatir.olcu_turu == OLCU_SATIS,
                    )
                ).all()
            )
        )
    assert n == 12

    satirlar2 = ButceService.yillik_dagit_ve_kaydet(
        plan["id"], Decimal("100.01"), olcu_turu=OLCU_SATIS, firma_id=1
    )
    assert sum((s["tutar"] for s in satirlar2), Decimal("0")) == Decimal("100.01")
    with Session() as s:
        n2 = len(
            list(s.scalars(select(ButceSatir).where(ButceSatir.plan_id == plan["id"])).all())
        )
    assert n2 == 12


def test_gerceklesen_eksik_ay_sifir_uydurmaz(butce_db):
    """Belgesi olmayan aylar aylar dict'ine 0 olarak eklenmez; bos_aylar'da listelenir."""
    Session = butce_db["Session"]
    with Session() as s:
        s.execute(
            text(
                """
                INSERT INTO satis_faturalari (
                    fatura_no, fatura_tarihi, vade_gunu, vade_tarihi, cari_id,
                    durum, onaylandi, depo, tahsilat_tutari, para_birimi, kur,
                    kur_turu, kur_kaynagi, kur_sabitlendi, borc_esasi,
                    doviz_ara_toplam, tl_matrah, tl_kdv, tl_genel_toplam,
                    tl_brut_toplam, genel_islem_orani, genel_islem_tutari,
                    fon_ek_bedel_tutari, fon_ek_bedel_kdv, rounding_applied,
                    rounding_version, invoice_rounding_adjustment, row_version,
                    olusturma_tarihi, is_deleted
                ) VALUES
                ('SF-BUTCE-1', '2026-03-15', 0, '2026-03-15', 1,
                 'AÇIK', 1, 'ANA DEPO', 0, 'TRY', 1,
                 'forex_selling', 'TCMB', 0, 'TL_SABIT',
                 0, 2500.00, 500.00, 3000.00,
                 0, 0, 0, 0, 0, 0, 0, 0, 1, '2026-03-15 10:00:00', 0),
                ('SF-BUTCE-TASLAK', '2026-04-01', 0, '2026-04-01', 1,
                 'TASLAK', 0, 'ANA DEPO', 0, 'TRY', 1,
                 'forex_selling', 'TCMB', 0, 'TL_SABIT',
                 0, 9999.00, 0, 9999.00,
                 0, 0, 0, 0, 0, 0, 0, 0, 1, '2026-04-01 10:00:00', 0)
                """
            )
        )
        s.commit()

    ger = ButceService.gerceklesen_on_muhasebe(2026, olcu_turu=OLCU_SATIS, firma_id=1)
    assert ger["kaynak"] == "ON_MUHASEBE"
    assert ger["kaynak_etiket"] == "Ön Muhasebe"
    # Mapper hâlâ kendi Table nesnesini kullanır; SQLite'da aynı isimli tablo okunur.
    assert ger["aylar"].get(3) == Decimal("2500.00")
    assert 4 not in ger["aylar"]
    assert 1 in ger["bos_aylar"] and 2 in ger["bos_aylar"]
    assert ger["durum"] == "OK"
    assert ger["belge_sayisi"] == 1

    ger_bos = ButceService.gerceklesen_on_muhasebe(2025, olcu_turu=OLCU_SATIS, firma_id=1)
    assert ger_bos["aylar"] == {}
    assert ger_bos["durum"] == "VERI_YOK"
    assert ger_bos["bos_aylar"] == list(range(1, 13))
    assert ger_bos["belge_sayisi"] == 0
