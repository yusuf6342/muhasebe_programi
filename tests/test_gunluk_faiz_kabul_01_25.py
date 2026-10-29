"""DOC2 günlük faiz kabul senaryoları 01–25 — sentetik / birim seviye.

UI-bağımlı akışlar (takvim penceresi, font +1) burada yok; servis yardımcıları
ve faiz motoru Decimal ile doğrulanır. KK/kredi ödeme UI bozulmadan kalır.
"""

from __future__ import annotations

import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database.database import Base
from database.banka_kredi_service import BankaKrediService
from database.gunluk_faiz_service import (
    aralik_hesapla,
    aralik_hesapla_ozet,
    asgari_odendi_mi_devreden_faiz_sifirlanmaz,
    ayni_gun_kullanim_kapanis_valor,
    banka_duzeltme_fark,
    basit_gunluk_faiz,
    borc_kimligi_uret,
    cift_tik_tek_odeme,
    donem_devri_mukerrer_yok,
    gecikme_vs_akdi_ayri,
    gun_esasi_360_365_gercek,
    gun_esasi_normalize,
    gun_esasi_sayi,
    kapali_donem_sessiz_fis_yok,
    kapanis_sonrasi_faiz_yok,
    kismi_odeme_iptal_geri_ac,
    kismi_odeme_kalan,
    kmh_matrah,
    maliyet_kimligi_koru,
    matrah_bilesenleri,
    mukerrer_gun_korumasi,
    odeme_tarihi_vade_ayri,
    oran_surumu_aralik,
    pb_yuvarla,
    senaryo_14_uc_gun,
    senaryo_17_kmh_gunluk,
    tahakkuk_odeme_kalan,
    tahakkuk_odeme_ozet,
    valor_sonrasi_matrah,
    yari_islem_atomik,
    GunlukFaizService,
)
from database.models.faiz import FaizOranTanimi, GunlukFaizKaydi
import database.gunluk_faiz_service as gfs


# ---------------------------------------------------------------------------
# 01–06 Kısmi kredi taksit ödemesi (servis yardımcıları)
# ---------------------------------------------------------------------------


def test_01_kismi_4000_kalan_6000_kismen_odendi():
    """01: 4k of 10k → 6k kalan, KISMEN_ODENDI."""
    r = kismi_odeme_kalan(Decimal("10000"), Decimal("4000"))
    assert r["gecerli"] is True
    assert r["kalan"] == Decimal("6000.00")
    assert r["durum"] == "KISMEN_ODENDI"
    assert (
        BankaKrediService.taksit_durum_hesapla(
            date.today() + timedelta(days=10),
            Decimal("4000"),
            Decimal("10000"),
        )
        == "KISMEN_ODENDI"
    )


def test_02_ikinci_odeme_kapatir():
    """02: ikinci ödeme kalanı kapatır → ODENDI."""
    ilk = kismi_odeme_kalan(Decimal("10000"), Decimal("4000"))
    assert ilk["kalan"] == Decimal("6000.00")
    ikinci = kismi_odeme_kalan(Decimal("10000"), Decimal("10000"))
    assert ikinci["kalan"] == Decimal("0.00")
    assert ikinci["durum"] == "ODENDI"
    assert (
        BankaKrediService.taksit_durum_hesapla(
            date.today(), Decimal("10000"), Decimal("10000")
        )
        == "ODENDI"
    )


def test_03_ilk_odeme_iptal_geri_acilir():
    """03: ilk kısmi iptal → kalan 10k / BEKLIYOR."""
    r = kismi_odeme_iptal_geri_ac(
        Decimal("10000"), Decimal("4000"), Decimal("4000")
    )
    assert r["odenen"] == Decimal("0.00")
    assert r["kalan"] == Decimal("10000.00")
    assert r["durum"] == "BEKLIYOR"
    assert r["vade_degismedi"] is True
    r2 = kismi_odeme_iptal_geri_ac(
        Decimal("10000"), Decimal("0"), Decimal("4000")
    )
    assert r2["odenen"] == Decimal("0.00")
    assert r2["kalan"] == Decimal("10000.00")


def test_04_gecersiz_tutar_reddedilir():
    """04: 0, negatif, kalanı aşan tutar reddedilir."""
    assert kismi_odeme_kalan(Decimal("10000"), Decimal("0"))["neden"] == "SIFIR_ODEME"
    assert kismi_odeme_kalan(Decimal("10000"), Decimal("-1"))["neden"] == "GECERSIZ_TUTAR"
    assert kismi_odeme_kalan(Decimal("10000"), Decimal("10001"))["neden"] == "KALANI_ASIYOR"


def test_05_cift_tik_tek_odeme():
    """05: aynı transaction_id çift tık → tek ödeme."""
    onceki: set[str] = set()
    a = cift_tik_tek_odeme("tx-abc", onceki_transaction_idler=onceki)
    assert a["yapildi"] is True
    onceki.add("tx-abc")
    b = cift_tik_tek_odeme("tx-abc", onceki_transaction_idler=onceki)
    assert b["yapildi"] is False
    assert b["mukerrer"] is True


def test_06_vade_sabit_odeme_tarihi_ayri():
    """06: vade sabit; ödeme tarihi ayrı."""
    vade = date(2026, 11, 10)
    odeme = date(2026, 10, 20)
    r = odeme_tarihi_vade_ayri(vade, odeme)
    assert r["vade_tarihi"] == vade
    assert r["odeme_tarihi"] == odeme
    assert r["vade_degisti"] is False


# ---------------------------------------------------------------------------
# 07–13 Kart / oran / tahakkuk
# ---------------------------------------------------------------------------


def test_07_asgari_odendi_alisveris_faizi_surer():
    """07: asgari karşılandı → alışveriş faizi sıfırlanmaz."""
    r = asgari_odendi_mi_devreden_faiz_sifirlanmaz(
        asgari_karsilandi=True,
        alisveris_kalan=Decimal("12000"),
        nakit_kalan=Decimal("3000"),
    )
    assert r["asgari_karsilandi"] is True
    assert r["alisveris_faiz_matrah"] == Decimal("12000")
    assert r["borc_kapandi"] is False
    assert r["alisveris_faizi_sifirlandi"] is False
    assert r["nakit_faizi_sifirlandi"] is False


def test_08_alisveris_nakit_ayri_oran():
    """08: alışveriş ve nakit ayrı matrah/oran; alışveriş ödemesi nakiti sıfırlamaz."""
    b = matrah_bilesenleri(alisveris=Decimal("10000"), nakit=Decimal("5000"), asgari_eksik=0)
    assert b["ALISVERIS"] == Decimal("10000.00")
    assert b["NAKIT"] == Decimal("5000.00")
    b2 = matrah_bilesenleri(alisveris=0, nakit=Decimal("5000"), asgari_eksik=0)
    assert b2["ALISVERIS"] == Decimal("0.00")
    assert b2["NAKIT"] == Decimal("5000.00")
    f_av = basit_gunluk_faiz(b2["ALISVERIS"], Decimal("36"), gun_esasi=360)
    f_nak = basit_gunluk_faiz(b2["NAKIT"], Decimal("48"), gun_esasi=360)
    assert f_av == Decimal("0.00")
    assert f_nak == Decimal("6.67")


def test_09_gecikme_mukerrer_yok():
    """09: gecikmiş matrah ayrı; aynı anapara/gün çift faiz yok."""
    r = gecikme_vs_akdi_ayri(
        asgari_eksik=Decimal("2000"),
        alisveris_kalan=Decimal("8000"),
        nakit_kalan=Decimal("1000"),
    )
    assert r["ayni_anapara_cift_faiz"] is False
    assert r["mukerrer_faiz"] is False
    assert set(r["bilesenler"].keys()) == {"ALISVERIS", "NAKIT", "ASGARI_EKSIK"}


def test_10_oran_ortasi_degisim_ve_180_ornek():
    """10: oran dilimi + 180 TL sentetik (10k×10 + 8k×10 @ %36/360)."""
    a = basit_gunluk_faiz(Decimal("10000"), Decimal("36"), gun_esasi=360, gun_sayisi=10)
    b = basit_gunluk_faiz(Decimal("8000"), Decimal("36"), gun_esasi=360, gun_sayisi=10)
    assert a + b == Decimal("180.00")
    r1 = aralik_hesapla_ozet(
        Decimal("10000"), Decimal("36"), 360, date(2026, 1, 1), date(2026, 1, 11)
    )
    r2 = aralik_hesapla_ozet(
        Decimal("8000"), Decimal("36"), 360, date(2026, 1, 11), date(2026, 1, 21)
    )
    assert r1["tutar"] + r2["tutar"] == Decimal("180.00")
    # Oran ortası değişim (dahil aralıklar)
    toplam = oran_surumu_aralik(
        Decimal("10000"),
        [
            (date(2026, 1, 1), date(2026, 1, 10), Decimal("36")),
            (date(2026, 1, 11), date(2026, 1, 20), Decimal("48")),
        ],
    )
    assert toplam == Decimal("100.00") + Decimal("133.33")


def test_11_tahakkuk_120_odeme_50_borc_70():
    """11: 120 tahakkuk / 50 ödeme → borç 70; gider 120."""
    assert tahakkuk_odeme_kalan(Decimal("120"), Decimal("50")) == Decimal("70.00")
    r = tahakkuk_odeme_ozet(Decimal("120"), Decimal("50"))
    assert r["gider"] == Decimal("120.00")
    assert r["nakit_cikis"] == Decimal("50.00")
    assert r["maliyet_borcu"] == Decimal("70.00")
    assert tahakkuk_odeme_ozet(Decimal("120"), Decimal("50")) == r


def test_12_banka_duzeltme_artı5_eksi10_idempotent(faiz_db):
    """12: +5 / -10 düzeltme; aynı belge tekrar → yeni gider yok."""
    assert banka_duzeltme_fark(Decimal("120"), Decimal("125")) == Decimal("5.00")
    assert banka_duzeltme_fark(Decimal("120"), Decimal("110")) == Decimal("-10.00")
    a = GunlukFaizService.banka_fark_kaydet(
        firma_id=1,
        urun_turu="KREDI",
        urun_id=12,
        ic_tahakkuk=Decimal("120"),
        banka_tutari=Decimal("125"),
        belge_kimlik="BNK-125",
        gun=date(2026, 1, 1),
    )
    assert a["yapildi"] is True
    assert a["fark"] == Decimal("5.00")
    a2 = GunlukFaizService.banka_fark_kaydet(
        firma_id=1,
        urun_turu="KREDI",
        urun_id=12,
        ic_tahakkuk=Decimal("120"),
        banka_tutari=Decimal("125"),
        belge_kimlik="BNK-125",
        gun=date(2026, 1, 1),
    )
    assert a2["yapildi"] is False
    assert a2["neden"] == "zaten_var"

    b = GunlukFaizService.banka_fark_kaydet(
        firma_id=1,
        urun_turu="KREDI",
        urun_id=12,
        ic_tahakkuk=Decimal("120"),
        banka_tutari=Decimal("110"),
        belge_kimlik="BNK-110",
        gun=date(2026, 1, 2),
    )
    assert b["yapildi"] is True
    assert b["fark"] == Decimal("-10.00")


def test_13_oran_eksik_sahte_sifir_yok():
    """13: oran eksik → ORAN_EKSIK; sahte 0 yazılmaz."""
    r = aralik_hesapla_ozet(
        Decimal("10000"),
        None,
        360,
        date(2026, 1, 1),
        date(2026, 1, 4),
    )
    assert r["neden"] == "ORAN_EKSIK"
    assert r["tutar"] is None


# ---------------------------------------------------------------------------
# 14–18 kredi / kart / KMH
# ---------------------------------------------------------------------------


def test_14_uc_gun_30_tl():
    """14: matrah 10000, %36/360, 3 gün = 30 TL."""
    assert senaryo_14_uc_gun() == Decimal("30.00")
    # dahil: 1–3 = 3 gün
    assert aralik_hesapla(
        Decimal("10000"),
        Decimal("36"),
        gun_esasi=360,
        bas=date(2026, 1, 1),
        bitis=date(2026, 1, 3),
    ) == Decimal("30.00")
    r = aralik_hesapla_ozet(
        Decimal("10000"), Decimal("36"), 360, date(2026, 1, 1), date(2026, 1, 4)
    )
    assert r["tutar"] == Decimal("30.00")
    assert r["gun_sayisi"] == 3


def test_15_kart_bilesen_ayri_mukerrer_yok():
    """15: asgari/alışveriş/nakit ayrı; çift faiz yok."""
    b = matrah_bilesenleri(
        alisveris=Decimal("15000"),
        nakit=Decimal("2000"),
        asgari_eksik=Decimal("8000"),
    )
    assert b["ASGARI_EKSIK"] == Decimal("8000.00")
    r = gecikme_vs_akdi_ayri(
        asgari_eksik=b["ASGARI_EKSIK"],
        alisveris_kalan=b["ALISVERIS"],
        nakit_kalan=b["NAKIT"],
    )
    assert r["ayni_anapara_cift_faiz"] is False
    m = mukerrer_gun_korumasi(True, tutar=Decimal("10.00"))
    assert m["neden"] == "zaten_var"


def test_16_valor_matrah_azalir_asgari_sifirlamaz():
    """16: valörde matrah azalır; asgari tamam → revolving faiz sıfırlanmaz."""
    valor = date(2026, 2, 10)
    once = Decimal("10000")
    assert valor_sonrasi_matrah(
        once, Decimal("2000"), valor_tarihi=valor, hesap_gunu=date(2026, 2, 9)
    ) == Decimal("10000.00")
    assert valor_sonrasi_matrah(
        once, Decimal("2000"), valor_tarihi=valor, hesap_gunu=valor
    ) == Decimal("8000.00")
    r = asgari_odendi_mi_devreden_faiz_sifirlanmaz(
        asgari_karsilandi=True,
        alisveris_kalan=Decimal("8000"),
        nakit_kalan=Decimal("2000"),
    )
    assert r["alisveris_faizi_sifirlandi"] is False


def test_17_kmh_50_tl_gun_ve_sifir_kullanim():
    """17: 50000 × %36/360 = 50 TL/gün; kullanım 0 → 0; limit matrahta değil."""
    assert senaryo_17_kmh_gunluk() == Decimal("50.00")
    assert senaryo_17_kmh_gunluk(kullanim=0) == Decimal("0.00")
    m = kmh_matrah(
        kullanilan_anapara=Decimal("50000"),
        limit=Decimal("100000"),
        pozitif_mevduat=Decimal("3000"),
    )
    assert m == Decimal("50000")


def test_18_ayni_gun_kullanim_tatil_valor_kancasi(faiz_db):
    """18: aynı gün kullanım+kapanış; kayıtlı kural; eksikte KURAL_EKSIK."""
    g = date(2026, 3, 1)
    r = ayni_gun_kullanim_kapanis_valor(
        kullanim_tarihi=g, kapanis_tarihi=g, gun_sonu_bakiye=0
    )
    assert r["faiz_gunu"] == 1
    assert r["banka_kurali_kancasi"] is True

    def tatil(d: date) -> bool:
        return d.weekday() >= 5

    cumartesi = date(2026, 3, 7)
    r2 = ayni_gun_kullanim_kapanis_valor(
        kullanim_tarihi=cumartesi,
        kapanis_tarihi=cumartesi,
        tatil_mi=tatil,
    )
    assert r2["valor_tarihi"].weekday() < 5
    r3 = ayni_gun_kullanim_kapanis_valor(
        kullanim_tarihi=g,
        kapanis_tarihi=g + timedelta(days=2),
        banka_min_gun_kurali=lambda a, b: 2,
    )
    assert r3["faiz_gunu"] == 2

    # Kayıtlı ürün kuralı yok → KURAL_EKSIK (varsayım yok)
    eksik = ayni_gun_kullanim_kapanis_valor(
        kullanim_tarihi=g,
        kapanis_tarihi=g,
        urun_turu="KMH",
        urun_id=9001,
    )
    assert eksik["neden"] == "KURAL_EKSIK"
    assert eksik["valor_tarihi"] is None

    GunlukFaizService.urun_kurali_kaydet(
        urun_turu="KMH",
        urun_id=9001,
        tatil_takvim_kaynagi="BANKA",
        ayni_gun_min_gun=1,
        valor_mod="TATIL_ATLA",
        valor_kaydir_gun=0,
    )
    ok = ayni_gun_kullanim_kapanis_valor(
        kullanim_tarihi=g,
        kapanis_tarihi=g,
        urun_turu="KMH",
        urun_id=9001,
        tatil_mi=tatil,
    )
    assert ok["neden"] is None
    assert ok["faiz_gunu"] == 1
    assert ok["banka_kurali_kancasi"] is True


# ---------------------------------------------------------------------------
# 19–25 arka plan / dönem / banka / kapanış
# ---------------------------------------------------------------------------


@pytest.fixture()
def faiz_db(monkeypatch):
    """İzole SQLite + get_session monkeypatch."""
    # FK hedefleri metadata'da olsun (stok_kartlari → kart_ana_turleri)
    import database.models.kart_turu  # noqa: F401 — create_all öncesi zorunlu
    import database.models.faiz  # noqa: F401
    import database.models.stok  # noqa: F401
    from database.models.finans import GiderFisi  # noqa: F401

    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "faiz.db"
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    # Giderleştirme testleri — FK hedefi olmadan tablo (SQLite)
    GiderFisi.__table__.create(bind=engine, checkfirst=True)
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

    monkeypatch.setattr(gfs, "get_session", fake_get_session)
    import database.database as dbmod

    monkeypatch.setattr(dbmod, "engine", engine)
    GunlukFaizService._hazir_engine_id = None
    GunlukFaizService.schema_hazirla()
    yield Session
    GunlukFaizService._hazir_engine_id = None
    try:
        engine.dispose()
    except Exception:
        pass
    try:
        tmp.cleanup()
    except PermissionError:
        pass


def test_19_uc_gun_gap_fill_yenile_mukerrer_yok(faiz_db):
    """19: 3 gün gap fill; Yenile ikinci gider üretmez."""
    Session = faiz_db
    with Session() as s:
        s.add(
            FaizOranTanimi(
                urun_turu="KREDI",
                urun_id=99,
                faiz_turu="GECIKME",
                oran_yuzde=Decimal("36"),
                donem="YILLIK",
                gun_esasi="360",
                baslangic_tarihi=date(2026, 1, 1),
                aktif=True,
            )
        )
        s.commit()

    r = GunlukFaizService.aralik_kaydet(
        firma_id=1,
        urun_turu="KREDI",
        urun_id=99,
        matrah=Decimal("10000"),
        bas=date(2026, 1, 7),
        bitis=date(2026, 1, 9),
        faiz_turu="GECIKME",
    )
    assert r["adet"] == 3
    assert r["toplam"] == Decimal("30.00")
    r2 = GunlukFaizService.aralik_kaydet(
        firma_id=1,
        urun_turu="KREDI",
        urun_id=99,
        matrah=Decimal("10000"),
        bas=date(2026, 1, 7),
        bitis=date(2026, 1, 9),
        faiz_turu="GECIKME",
    )
    assert r2["adet"] == 0
    assert r2["atlandi"] == 3
    with Session() as s:
        n = len(
            list(
                s.scalars(
                    select(GunlukFaizKaydi).where(
                        GunlukFaizKaydi.urun_id == 99,
                        GunlukFaizKaydi.urun_turu == "KREDI",
                    )
                ).all()
            )
        )
    assert n == 3


def test_20_oran_degisim_kimlik_ve_fark_fisi():
    """20: maliyet kimliği korunur; geriye ödeme yalnız fark fişi."""
    r = maliyet_kimligi_koru(
        "MAL-001",
        oran_degisti=True,
        geriye_tarihli_odeme=True,
        eski_tutar=Decimal("100"),
        yeni_tutar=Decimal("80"),
    )
    assert r["kimlik_korundu"] is True
    assert r["fark_fisi"] == Decimal("-20.00")
    assert r["ikinci_gider"] is False


def test_21_donem_devri_ikinci_anapara_yok(faiz_db):
    """21: yeni ekstre aynı borçta ikinci anapara/faiz yok (borc_kimligi tekillik)."""
    r = donem_devri_mukerrer_yok(
        borc_kimligi="BORC-42",
        eski_ekstre_id=1,
        yeni_ekstre_id=2,
        onceki_anapara_kayitli=True,
        onceki_gunluk_faiz_kayitli=True,
    )
    assert r["ikinci_anapara"] is False
    assert r["ikinci_gunluk_faiz"] is False

    Session = faiz_db
    with Session() as s:
        s.add(
            FaizOranTanimi(
                urun_turu="KK",
                urun_id=10,
                faiz_turu="AKDI",
                oran_yuzde=Decimal("36"),
                donem="YILLIK",
                gun_esasi="360",
                baslangic_tarihi=date(2026, 1, 1),
                aktif=True,
            )
        )
        s.commit()

    kimlik = borc_kimligi_uret(
        urun_turu="KK", urun_id=10, borc_bilesen="ALISVERIS", kalici_anahtar="BORC-42"
    )
    g = date(2026, 2, 1)
    a = GunlukFaizService.gun_hesapla_ve_kaydet(
        firma_id=1,
        urun_turu="KK",
        urun_id=10,  # eski ekstre ürün satırı
        matrah=Decimal("10000"),
        gun=g,
        borc_bilesen="ALISVERIS",
        faiz_turu="AKDI",
        borc_kimligi=kimlik,
        donem_kontrol=False,
    )
    assert a["yapildi"] is True
    assert a["borc_kimligi"] == "BORC-42"
    # Yeni ekstre / farklı urun_id — aynı borc_kimligi → mükerrer yok
    b = GunlukFaizService.gun_hesapla_ve_kaydet(
        firma_id=1,
        urun_turu="KK",
        urun_id=99,
        matrah=Decimal("10000"),
        gun=g,
        borc_bilesen="ALISVERIS",
        faiz_turu="AKDI",
        borc_kimligi=kimlik,
        donem_kontrol=False,
    )
    assert b["yapildi"] is False
    assert b["neden"] == "zaten_var"
    with Session() as s:
        n = len(
            list(
                s.scalars(
                    select(GunlukFaizKaydi).where(GunlukFaizKaydi.borc_kimligi == "BORC-42")
                ).all()
            )
        )
    assert n == 1


def test_22_yari_islem_ve_oran_eksik_gorunur(faiz_db):
    """22: yarım gider yok; oran eksik görünür, sahte 0 yok."""
    assert yari_islem_atomik(adimlar_basarili=[True, False, True])["yarim_gider"] is False
    assert yari_islem_atomik(adimlar_basarili=[True, True])["tamamlandi"] is True
    r = GunlukFaizService.gun_hesapla_ve_kaydet(
        firma_id=1,
        urun_turu="KREDI",
        urun_id=777,
        matrah=Decimal("10000"),
        gun=date(2026, 1, 5),
        faiz_turu="GECIKME",
    )
    assert r["yapildi"] is False
    assert r["neden"] == "ORAN_EKSIK"
    assert "tutar" not in r or r.get("tutar") is None


def test_23_banka_eslesme_yalniz_fark(faiz_db):
    """23: iç tahakkuk = banka → fark_yok; aynı belge mükerrer yok; tahakkuk_giderlestir bir kez."""
    assert banka_duzeltme_fark(Decimal("50"), Decimal("50")) == Decimal("0.00")
    r = GunlukFaizService.banka_fark_kaydet(
        firma_id=1,
        urun_turu="KMH",
        urun_id=1,
        ic_tahakkuk=Decimal("50"),
        banka_tutari=Decimal("50"),
        belge_kimlik="BNK-EQ",
        donem_kontrol=False,
    )
    assert r["yapildi"] is False
    assert r["neden"] == "fark_yok"
    # Farklı belge ile fark, sonra tekrar
    a = GunlukFaizService.banka_fark_kaydet(
        firma_id=1,
        urun_turu="KMH",
        urun_id=1,
        ic_tahakkuk=Decimal("50"),
        banka_tutari=Decimal("55"),
        belge_kimlik="BNK-55",
        gun=date(2026, 1, 3),
        donem_kontrol=False,
    )
    assert a["yapildi"] is True
    assert a["ikinci_tam_gider"] is False
    a2 = GunlukFaizService.banka_fark_kaydet(
        firma_id=1,
        urun_turu="KMH",
        urun_id=1,
        ic_tahakkuk=Decimal("50"),
        banka_tutari=Decimal("55"),
        belge_kimlik="BNK-55",
        gun=date(2026, 1, 3),
        donem_kontrol=False,
    )
    assert a2["yapildi"] is False
    assert a2["neden"] == "zaten_var"

    Session = faiz_db
    with Session() as s:
        s.add(
            FaizOranTanimi(
                urun_turu="KREDI",
                urun_id=23,
                faiz_turu="AKDI",
                oran_yuzde=Decimal("36"),
                donem="YILLIK",
                gun_esasi="360",
                baslangic_tarihi=date(2026, 1, 1),
                aktif=True,
            )
        )
        s.commit()
    kayit = GunlukFaizService.gun_hesapla_ve_kaydet(
        firma_id=1,
        urun_turu="KREDI",
        urun_id=23,
        matrah=Decimal("10000"),
        gun=date(2026, 1, 10),
        faiz_turu="AKDI",
        donem_kontrol=False,
    )
    assert kayit["yapildi"] is True
    g1 = GunlukFaizService.tahakkuk_giderlestir(
        kayit_id=int(kayit["id"]), donem_kontrol=False
    )
    assert g1["yapildi"] is True
    assert g1["gider_belge_no"]
    g2 = GunlukFaizService.tahakkuk_giderlestir(
        kayit_id=int(kayit["id"]), donem_kontrol=False
    )
    assert g2["yapildi"] is False
    assert g2["neden"] == "zaten_var"
    from database.models.finans import GiderFisi

    with Session() as s:
        fisler = list(
            s.scalars(
                select(GiderFisi).where(GiderFisi.bagli_belge_no == f"GUNLUK_FAIZ:{kayit['id']}")
            ).all()
        )
    assert len(fisler) == 1


def test_24_kapali_donem_ve_gun_esasi_yuvarlama(faiz_db, monkeypatch):
    """24: kapalı dönem sessiz fiş yok; 360/365/GERCEK + PB yuvarlama."""
    assert kapali_donem_sessiz_fis_yok(donem_kapali=True)["izin"] is False
    assert kapali_donem_sessiz_fis_yok(donem_kapali=False, fis_uretildi=True)["izin"] is True
    assert gun_esasi_normalize(360) == "360"
    assert gun_esasi_normalize(365) == "365"
    assert gun_esasi_normalize("GERCEK") == "GERCEK"
    assert gun_esasi_sayi("GERCEK") == 365
    assert gun_esasi_360_365_gercek(360)["bolen"] == 360
    a360 = basit_gunluk_faiz(Decimal("10000"), Decimal("36"), gun_esasi=360, gun_sayisi=1)
    a365 = basit_gunluk_faiz(Decimal("10000"), Decimal("36"), gun_esasi=365, gun_sayisi=1)
    assert a360 == Decimal("10.00")
    assert a365 == Decimal("9.86")
    assert pb_yuvarla(Decimal("1.005")) == Decimal("1.01")
    assert pb_yuvarla(Decimal("1.004")) == Decimal("1.00")

    Session = faiz_db
    with Session() as s:
        s.add(
            FaizOranTanimi(
                urun_turu="KREDI",
                urun_id=24,
                faiz_turu="GECIKME",
                oran_yuzde=Decimal("36"),
                donem="YILLIK",
                gun_esasi="360",
                baslangic_tarihi=date(2026, 1, 1),
                aktif=True,
            )
        )
        s.commit()

    monkeypatch.setattr(
        GunlukFaizService, "_donem_kapali_mi", classmethod(lambda cls, gun, session=None: True)
    )
    kapali = GunlukFaizService.gun_hesapla_ve_kaydet(
        firma_id=1,
        urun_turu="KREDI",
        urun_id=24,
        matrah=Decimal("10000"),
        gun=date(2026, 1, 15),
        faiz_turu="GECIKME",
        donem_kontrol=True,
    )
    assert kapali["yapildi"] is False
    assert kapali["neden"] == "DONEM_KAPALI"
    assert kapali.get("fis_uretildi") is False

    monkeypatch.setattr(
        GunlukFaizService, "_donem_kapali_mi", classmethod(lambda cls, gun, session=None: False)
    )
    acik = GunlukFaizService.gun_hesapla_ve_kaydet(
        firma_id=1,
        urun_turu="KREDI",
        urun_id=24,
        matrah=Decimal("10000"),
        gun=date(2026, 1, 15),
        faiz_turu="GECIKME",
        donem_kontrol=True,
    )
    assert acik["yapildi"] is True


def test_25_kapanis_sonrasi_faiz_yok_acik_maliyet_korunur(faiz_db):
    """25: kapalı hesapta faiz durur; işlemiş açık maliyet korunur."""
    kapanis = date(2026, 4, 1)
    assert kapanis_sonrasi_faiz_yok(kapanis_tarihi=kapanis, hesap_gunu=date(2026, 4, 2)) is True
    assert kapanis_sonrasi_faiz_yok(kapanis_tarihi=kapanis, hesap_gunu=kapanis) is False

    Session = faiz_db
    with Session() as s:
        s.add(
            FaizOranTanimi(
                urun_turu="KREDI",
                urun_id=25,
                faiz_turu="GECIKME",
                oran_yuzde=Decimal("36"),
                donem="YILLIK",
                gun_esasi="360",
                baslangic_tarihi=date(2026, 1, 1),
                aktif=True,
            )
        )
        s.commit()
    # Kapanış öncesi bir gün
    once = GunlukFaizService.gun_hesapla_ve_kaydet(
        firma_id=1,
        urun_turu="KREDI",
        urun_id=25,
        matrah=Decimal("10000"),
        gun=date(2026, 3, 31),
        faiz_turu="GECIKME",
        kapanis_tarihi=kapanis,
    )
    assert once["yapildi"] is True
    assert once["tutar"] == Decimal("10.00")
    # Kapanış sonrası
    sonra = GunlukFaizService.gun_hesapla_ve_kaydet(
        firma_id=1,
        urun_turu="KREDI",
        urun_id=25,
        matrah=Decimal("10000"),
        gun=date(2026, 4, 2),
        faiz_turu="GECIKME",
        kapanis_tarihi=kapanis,
    )
    assert sonra["yapildi"] is False
    assert sonra["neden"] == "KAPALI"
    # İşlemiş kayıt duruyor
    with Session() as s:
        n = len(
            list(
                s.scalars(
                    select(GunlukFaizKaydi).where(GunlukFaizKaydi.urun_id == 25)
                ).all()
            )
        )
    assert n == 1


def test_mukerrer_gun_hesapla_ve_kaydet(faiz_db):
    """gun_hesapla_ve_kaydet idempotent (mukerrer_gun_korumasi)."""
    Session = faiz_db
    with Session() as s:
        s.add(
            FaizOranTanimi(
                urun_turu="KREDI",
                urun_id=1,
                faiz_turu="GECIKME",
                oran_yuzde=Decimal("36"),
                donem="YILLIK",
                gun_esasi="360",
                baslangic_tarihi=date(2026, 1, 1),
                aktif=True,
            )
        )
        s.commit()
    g = date(2026, 1, 5)
    r1 = GunlukFaizService.gun_hesapla_ve_kaydet(
        firma_id=1,
        urun_turu="KREDI",
        urun_id=1,
        matrah=Decimal("10000"),
        gun=g,
        faiz_turu="GECIKME",
    )
    assert r1["yapildi"] is True
    assert r1["tutar"] == Decimal("10.00")
    r2 = GunlukFaizService.gun_hesapla_ve_kaydet(
        firma_id=1,
        urun_turu="KREDI",
        urun_id=1,
        matrah=Decimal("10000"),
        gun=g,
        faiz_turu="GECIKME",
    )
    assert r2["yapildi"] is False
    assert r2["neden"] == "zaten_var"
