"""Bütçe: nakit dönem sonu, iç virman, Excel roundtrip, GM vs Ön toplanmaz.

Geçici SQLite — canlı firma DB'sine dokunmaz.
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    create_engine,
    select,
    text,
)
from sqlalchemy.orm import sessionmaker

from database.database import Base
from database.butce_service import ButceService, KAYNAK_YAN_YANA
from database.models.butce import OLCU_GIDER, OLCU_SATIS, ButcePlan, ButceSatir
import database.butce_service as butce_mod


@pytest.fixture()
def butce_db(monkeypatch):
    """İzole temp SQLite."""
    import database.models.butce  # noqa: F401

    tmp = tempfile.TemporaryDirectory(prefix="butce_nxt_")
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

    Table(
        "muhasebe_fisleri",
        meta,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("firma_id", Integer, nullable=False, default=1),
        Column("mali_yil", Integer, nullable=False),
        Column("fis_no", String(40), nullable=False),
        Column("fis_tarihi", Date, nullable=False),
        Column("fis_turu", String(40), nullable=False, default="Mahsup Fişi"),
        Column("durum", String(20), nullable=False, default="Kesinleşmiş"),
        Column("ters_fis_id", Integer, nullable=True),
        Column("toplam_borc", Numeric(18, 2), nullable=False, default=0),
        Column("toplam_alacak", Numeric(18, 2), nullable=False, default=0),
    ).create(bind=engine, checkfirst=True)
    Table(
        "muhasebe_fis_satirlari",
        meta,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("fis_id", Integer, nullable=False),
        Column("firma_id", Integer, nullable=False, default=1),
        Column("sira_no", Integer, nullable=False, default=1),
        Column("hesap_id", Integer, nullable=False, default=1),
        Column("hesap_kodu", String(30), nullable=False),
        Column("hesap_adi", String(200), nullable=False, default=""),
        Column("borc", Numeric(18, 2), nullable=False, default=0),
        Column("alacak", Numeric(18, 2), nullable=False, default=0),
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
    yield {"Session": Session, "engine": engine, "tmp": tmp}
    ButceService._schema_hazir = False
    try:
        engine.dispose()
    except Exception:
        pass
    try:
        tmp.cleanup()
    except PermissionError:
        pass


def test_nakit_donem_sonu_ornek_ve_virman():
    """20.000 + 30.000 − 25.000 = 25.000; iç virman firma nakdini değiştirmez."""
    ozet = ButceService.nakit_donem_hesapla(
        Decimal("20000.00"),
        Decimal("30000.00"),
        Decimal("25000.00"),
        ic_virman_giris=Decimal("4000.00"),
        ic_virman_cikis=Decimal("4000.00"),
    )
    assert ozet["donem_sonu"] == Decimal("25000.00")
    assert ozet["baslangic_kullanilabilir"] == Decimal("20000.00")
    assert ozet["gercek_giris"] == Decimal("30000.00")
    assert ozet["gercek_cikis"] == Decimal("25000.00")
    assert ozet["ic_virman_giris"] == Decimal("4000.00")
    assert ozet["ic_virman_cikis"] == Decimal("4000.00")
    assert ozet["donem_sonu"] == Decimal("20000.00") + Decimal("30000.00") - Decimal(
        "25000.00"
    )

    ozet2 = ButceService.nakit_donem_hesapla(
        Decimal("20000"),
        Decimal("30000"),
        Decimal("25000"),
        ic_virman_giris=Decimal("4000"),
        ic_virman_cikis=Decimal("0"),
    )
    assert ozet2["donem_sonu"] == Decimal("25000.00")
    assert ozet2["ic_virman_net"] == Decimal("4000.00")


def test_ic_virman_tespiti():
    assert ButceService.ic_virman_mi("VIRMAN GİRİŞ") is True
    assert ButceService.ic_virman_mi("BANKA VİRMAN ÇIKIŞ") is True
    assert ButceService.ic_virman_mi("KASADAN BANKAYA YATAN") is True
    assert ButceService.ic_virman_mi("FATURA TAHSİLATI") is False
    assert ButceService.ic_virman_mi("BANKA VİRMAN MASRAF") is False


def test_nakit_butcesi_override_temp_db(butce_db):
    veri = ButceService.nakit_butcesi(
        2026,
        ay=3,
        baslangic_override=Decimal("20000.00"),
        firma_id=1,
    )
    assert veri["baslangic_kullanilabilir"] == Decimal("20000.00")
    assert veri["gercek_giris"] == Decimal("0.00")
    assert veri["gercek_cikis"] == Decimal("0.00")
    assert veri["donem_sonu"] == Decimal("20000.00")
    assert veri["bakiye_kaynak"] == "OVERRIDE"
    assert veri["hareket_sayisi"] == 0


def test_excel_roundtrip_ve_idempotent(butce_db):
    tmp = Path(butce_db["tmp"].name)
    plan = ButceService.plan_olustur("Excel Plan", 2026, firma_id=1)
    sablon = tmp / "sablon.xlsx"
    ButceService.excel_sablon_olustur(sablon)

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["kategori", "olcu_turu", "para_birimi", "ay", "tutar"])
    for ay in range(1, 13):
        ws.append(["GENEL", "SATIS", "TRY", ay, 1000])
    yol = tmp / "aktar.xlsx"
    wb.save(yol)

    oniz = ButceService.excel_onizle(yol, plan_id=plan["id"], firma_id=1)
    assert oniz["gecerli"] is True
    assert oniz["satir_sayisi"] == 12
    assert oniz["yeni_sayisi"] == 12
    assert oniz["cakisma_sayisi"] == 0
    assert all(s["cakisma_durum"] == "yeni" for s in oniz["satirlar"])

    r1 = ButceService.excel_aktar(plan["id"], yol, firma_id=1, cakisma="guncelle")
    assert r1["eklenen"] == 12
    assert r1["guncellenen"] == 0

    oniz2 = ButceService.excel_onizle(yol, plan_id=plan["id"], firma_id=1)
    assert oniz2["cakisma_sayisi"] == 12
    assert oniz2["yeni_sayisi"] == 0
    assert all(s["cakisma_durum"] == "guncellenecek" for s in oniz2["satirlar"])

    r2 = ButceService.excel_aktar(plan["id"], yol, firma_id=1, cakisma="guncelle")
    assert r2["eklenen"] == 0
    assert r2["guncellenen"] == 12

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

    r3 = ButceService.excel_aktar(plan["id"], yol, firma_id=1, cakisma="atla")
    assert r3["atlanan"] == 12
    assert r3["guncellenen"] == 0


def test_excel_hata_yarim_aktarim_yok(butce_db):
    tmp = Path(butce_db["tmp"].name)
    plan = ButceService.plan_olustur("Hata Plan", 2026, firma_id=1)
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["kategori", "olcu_turu", "para_birimi", "ay", "tutar"])
    ws.append(["GENEL", "SATIS", "TRY", 1, 500])
    ws.append(["GENEL", "SATIS", "TRY", 99, 500])
    yol = tmp / "hatali.xlsx"
    wb.save(yol)

    oniz = ButceService.excel_onizle(yol, plan_id=plan["id"], firma_id=1)
    assert oniz["gecerli"] is False

    with pytest.raises(ValueError, match="doğrulama"):
        ButceService.excel_aktar(plan["id"], yol, firma_id=1)

    Session = butce_db["Session"]
    with Session() as s:
        n = len(
            list(s.scalars(select(ButceSatir).where(ButceSatir.plan_id == plan["id"])).all())
        )
    assert n == 0


def test_gm_ve_on_toplanmaz_yan_yana(butce_db):
    """Aynı satış Ön'de 10.000, GM'de 10.000 → yan yana toplam 20.000 olmamalı; fark 0."""
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
                ('SF-YY-1', '2026-05-10', 0, '2026-05-10', 1,
                 'AÇIK', 1, 'ANA DEPO', 0, 'TRY', 1,
                 'forex_selling', 'TCMB', 0, 'TL_SABIT',
                 0, 10000.00, 2000.00, 12000.00,
                 0, 0, 0, 0, 0, 0, 0, 0, 1, '2026-05-10 10:00:00', 0)
                """
            )
        )
        s.execute(
            text(
                """
                INSERT INTO muhasebe_fisleri
                    (id, firma_id, mali_yil, fis_no, fis_tarihi, fis_turu, durum,
                     ters_fis_id, toplam_borc, toplam_alacak)
                VALUES
                    (1, 1, 2026, 'MF-2026-00001', '2026-05-10', 'Mahsup Fişi',
                     'Kesinleşmiş', NULL, 10000, 10000)
                """
            )
        )
        s.execute(
            text(
                """
                INSERT INTO muhasebe_fis_satirlari
                    (fis_id, firma_id, sira_no, hesap_id, hesap_kodu, hesap_adi, borc, alacak)
                VALUES
                    (1, 1, 1, 10, '600.01', 'Yurtiçi Satışlar', 0, 10000.00),
                    (1, 1, 2, 11, '120.01', 'Alıcılar', 10000.00, 0)
                """
            )
        )
        s.execute(
            text(
                """
                INSERT INTO muhasebe_fisleri
                    (id, firma_id, mali_yil, fis_no, fis_tarihi, fis_turu, durum,
                     ters_fis_id, toplam_borc, toplam_alacak)
                VALUES
                    (2, 1, 2026, 'MF-2026-00002', '2026-05-15', 'Mahsup Fişi',
                     'Kesinleşmiş', NULL, 300, 300)
                """
            )
        )
        s.execute(
            text(
                """
                INSERT INTO muhasebe_fis_satirlari
                    (fis_id, firma_id, sira_no, hesap_id, hesap_kodu, hesap_adi, borc, alacak)
                VALUES
                    (2, 1, 1, 20, '770.01', 'Genel Yönetim Giderleri', 300.00, 0),
                    (2, 1, 2, 21, '100.01', 'Kasa', 0, 300.00)
                """
            )
        )
        s.commit()

    plan = ButceService.plan_olustur("YY Plan", 2026, firma_id=1)
    ButceService.yillik_dagit_ve_kaydet(
        plan["id"], Decimal("12000.00"), olcu_turu=OLCU_SATIS, firma_id=1
    )

    on = ButceService.gerceklesen_on_muhasebe(2026, olcu_turu=OLCU_SATIS, firma_id=1)
    gm = ButceService.gerceklesen_genel_muhasebe(2026, olcu_turu=OLCU_SATIS, firma_id=1)
    assert on["kaynak_etiket"] == "Ön Muhasebe"
    assert gm["kaynak_etiket"] == "Genel Muhasebe"
    assert on["aylar"].get(5) == Decimal("10000.00")
    assert gm["aylar"].get(5) == Decimal("10000.00")
    assert on["toplam"] == Decimal("10000.00")
    assert gm["toplam"] == Decimal("10000.00")

    yy = ButceService.karsilastirma(
        plan["id"], olcu_turu=OLCU_SATIS, firma_id=1, kaynak=KAYNAK_YAN_YANA
    )
    assert yy["kaynak"] == KAYNAK_YAN_YANA
    mayis = next(s for s in yy["satirlar"] if s["ay"] == 5)
    assert mayis["on_muhasebe"] == Decimal("10000.00")
    assert mayis["genel_muhasebe"] == Decimal("10000.00")
    assert mayis["kaynak_farki"] == Decimal("0.00")
    assert yy["on_muhasebe_toplam"] == Decimal("10000.00")
    assert yy["genel_muhasebe_toplam"] == Decimal("10000.00")
    assert yy["kaynak_farki_toplam"] == Decimal("0.00")

    gm_g = ButceService.gerceklesen_genel_muhasebe(2026, olcu_turu=OLCU_GIDER, firma_id=1)
    on_g = ButceService.gerceklesen_on_muhasebe(2026, olcu_turu=OLCU_GIDER, firma_id=1)
    assert gm_g["aylar"].get(5) == Decimal("300.00")
    assert 5 not in (on_g.get("aylar") or {})


def test_gm_paket_yok_sifir_uydurmaz(butce_db):
    eng = butce_db["engine"]
    with eng.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS muhasebe_fis_satirlari"))
        conn.execute(text("DROP TABLE IF EXISTS muhasebe_fisleri"))

    ger = ButceService.gerceklesen_genel_muhasebe(2026, olcu_turu=OLCU_SATIS, firma_id=1)
    assert ger["durum"] == "PAKET_YOK"
    assert ger["aylar"] == {}
    assert ger["toplam"] is None
    assert ger["kaynak_etiket"] == "Genel Muhasebe"
