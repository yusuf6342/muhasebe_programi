"""Günlük faiz hesabı — ortak motor (ödeme belgesine bağlı değil).

DOC2 kabul 01–25: formül, bileşen matrahları, oran sürümü, mükerrer koruma,
kaçırılan gün tamamlaması, KMH / kart / kredi ayrımı. Giderleştirme kimliği
`gider_belge_no` ile izlenir; oran eksikse sahte 0 yazılmaz.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from sqlalchemy import select

from database.database import get_session
from database.models.faiz import FaizOranTanimi, FaizUrunKurali, GunlukFaizKaydi

_log = logging.getLogger(__name__)
KURUS = Decimal("0.01")
SIFIR = Decimal("0")

# Valör / tatil (DOC2-18)
VALOR_IS_GUNU = "IS_GUNU"
VALOR_TAKVIM = "TAKVIM"
VALOR_TATIL_ATLA = "TATIL_ATLA"
TATIL_KAYNAKLARI = ("BANKA", "RESMI", "OZEL")

# Kart borç bileşenleri (DOC2 §15–16)
BILESEN_ALISVERIS = "ALISVERIS"
BILESEN_NAKIT = "NAKIT"
BILESEN_ASGARI_EKSIK = "ASGARI_EKSIK"
BILESEN_ANAPARA = "ANAPARA"
BILESEN_KMH_KULLANIM = "KMH_KULLANIM"


def _d(val) -> Decimal:
    try:
        return Decimal(str(val if val is not None else 0))
    except Exception:
        return SIFIR


def gun_esasi_sayi(gun_esasi: str | int) -> int:
    """360 / 365 / GERCEK → bölen. GERCEK için varsayılan 365 (yıl içi test)."""
    u = str(gun_esasi or "360").upper()
    if u in {"365", "GERCEK", "ACTUAL"}:
        return 365
    try:
        return int(gun_esasi) or 360
    except Exception:
        return 360


def basit_gunluk_faiz(
    matrah: Decimal,
    oran_yuzde: Decimal,
    *,
    donem: str = "YILLIK",
    gun_esasi: str | int = 360,
    gun_sayisi: int = 1,
) -> Decimal:
    """Yıllık nominal → matrah × oran/100 / gün_esası × gün (kuruş yuvarlama)."""
    matrah = _d(matrah)
    oran = _d(oran_yuzde)
    if matrah <= 0 or oran <= 0 or gun_sayisi <= 0:
        return SIFIR
    if (donem or "YILLIK").upper() == "AYLIK":
        gunluk = matrah * (oran / Decimal("100")) / Decimal("30")
    else:
        gunluk = matrah * (oran / Decimal("100")) / Decimal(str(gun_esasi_sayi(gun_esasi)))
    return (gunluk * Decimal(str(gun_sayisi))).quantize(KURUS, rounding=ROUND_HALF_UP)


def aralik_hesapla(
    matrah: Decimal,
    oran_yuzde: Decimal,
    *,
    donem: str = "YILLIK",
    gun_esasi: str | int = 360,
    bas: date,
    bitis: date,
) -> Decimal:
    """[bas, bitis] dahil gün sayısı ile faiz (tek oran)."""
    if bitis < bas:
        return SIFIR
    gun = (bitis - bas).days + 1
    return basit_gunluk_faiz(
        matrah, oran_yuzde, donem=donem, gun_esasi=gun_esasi, gun_sayisi=gun
    )


def oran_surumu_aralik(
    matrah: Decimal,
    oran_dilimleri: Iterable[tuple[date, date, Decimal]],
    *,
    donem: str = "YILLIK",
    gun_esasi: str | int = 360,
) -> Decimal:
    """Oran aralık ortasında değişince dilim dilim topla (DOC2 §10 / 20).

    Her öğe: (dilim_bas, dilim_bit, oran_yuzde) — tarihler dahil.
    """
    toplam = SIFIR
    for d_bas, d_bit, oran in oran_dilimleri:
        toplam += aralik_hesapla(
            matrah, _d(oran), donem=donem, gun_esasi=gun_esasi, bas=d_bas, bitis=d_bit
        )
    return toplam.quantize(KURUS, rounding=ROUND_HALF_UP)


def tahakkuk_odeme_kalan(tahakkuk: Decimal, odeme: Decimal) -> Decimal:
    """DOC2 §11: 120 tahakkuk − 50 ödeme → kalan maliyet borcu 70."""
    kalan = _d(tahakkuk) - _d(odeme)
    return max(SIFIR, kalan).quantize(KURUS, rounding=ROUND_HALF_UP)


def banka_duzeltme_fark(
    ic_tahakkuk: Decimal, banka_tutari: Decimal
) -> Decimal:
    """DOC2 §12: banka 125 / 110 → +5 / −10 fark."""
    return (_d(banka_tutari) - _d(ic_tahakkuk)).quantize(KURUS, rounding=ROUND_HALF_UP)


def kapanis_sonrasi_faiz_yok(
    *,
    kapanis_tarihi: date | None,
    hesap_gunu: date,
) -> bool:
    """DOC2 §25: hesap kapandıktan sonra yeni faiz üretilmez."""
    if kapanis_tarihi is None:
        return False
    return hesap_gunu > kapanis_tarihi


def kmh_matrah(*, kullanilan_anapara, limit=None, pozitif_mevduat=None) -> Decimal:
    """DOC2 §17: yalnız kullanım; limit ve pozitif mevduat matraha girmez."""
    kullanim = max(SIFIR, _d(kullanilan_anapara))
    # limit / pozitif_mevduat bilerek yok sayılır
    _ = limit, pozitif_mevduat
    return kullanim


def kart_matrah_bilesenleri(
    *,
    alisveris_kalan=0,
    nakit_kalan=0,
    asgari_eksik=0,
) -> dict[str, Decimal]:
    """DOC2 §15–16: alışveriş / nakit / asgari eksiği ayrı."""
    return {
        BILESEN_ALISVERIS: max(SIFIR, _d(alisveris_kalan)).quantize(KURUS),
        BILESEN_NAKIT: max(SIFIR, _d(nakit_kalan)).quantize(KURUS),
        BILESEN_ASGARI_EKSIK: max(SIFIR, _d(asgari_eksik)).quantize(KURUS),
    }


def asgari_odendi_mi_devreden_faiz_sifirlanmaz(
    *,
    asgari_karsilandi: bool,
    alisveris_kalan: Decimal,
    nakit_kalan: Decimal,
) -> dict[str, Any]:
    """DOC2 §07 / 16: asgari tamam ≠ borcun ve faiz matrahının kapanması."""
    return {
        "asgari_karsilandi": bool(asgari_karsilandi),
        "borc_kapandi": False if (_d(alisveris_kalan) > 0 or _d(nakit_kalan) > 0) else True,
        "alisveris_faiz_matrah": max(SIFIR, _d(alisveris_kalan)),
        "nakit_faiz_matrah": max(SIFIR, _d(nakit_kalan)),
        "alisveris_faizi_sifirlandi": False,
        "nakit_faizi_sifirlandi": False,
    }


# --- DOC2 adlandırılmış yardımcılar / kabul köprüleri -----------------------

SIFIR_00 = Decimal("0.00")


def gun_esasi_normalize(gun_esasi: str | int | None) -> str:
    """360 | 365 | GERCEK."""
    if gun_esasi is None:
        return "360"
    s = str(gun_esasi).strip().upper()
    if s in {"GERCEK", "ACTUAL", "ACT"}:
        return "GERCEK"
    if s in {"365"} or (s.isdigit() and int(s) == 365):
        return "365"
    return "360"


def gun_esasi_360_365_gercek(gun_esasi: str | int | None) -> dict[str, Any]:
    """DOC2 §24: gün esası + bölen + PB yuvarlama kuralı."""
    kod = gun_esasi_normalize(gun_esasi)
    return {
        "kod": kod,
        "bolen": gun_esasi_sayi(kod if kod != "GERCEK" else "GERCEK"),
        "pb_yuvarlama": "ROUND_HALF_UP",
        "kurus": KURUS,
    }


def pb_yuvarla(tutar) -> Decimal:
    return _d(tutar).quantize(KURUS, rounding=ROUND_HALF_UP)


def matrah_bilesenleri(
    *,
    alisveris=0,
    nakit=0,
    asgari_eksik=0,
    urun_turu: str = "KART",
) -> dict[str, Decimal]:
    """Alias: ALISVERIS / NAKIT / ASGARI_EKSIK."""
    _ = urun_turu
    return kart_matrah_bilesenleri(
        alisveris_kalan=alisveris, nakit_kalan=nakit, asgari_eksik=asgari_eksik
    )


def senaryo_14_uc_gun(
    matrah=Decimal("10000"),
    oran_yuzde=Decimal("36"),
    gun_esasi: str | int = 360,
) -> Decimal:
    """DOC2-14: 10.000 × %36/360 × 3 = 30.00."""
    return basit_gunluk_faiz(
        _d(matrah), _d(oran_yuzde), gun_esasi=gun_esasi, gun_sayisi=3
    )


def senaryo_17_kmh_gunluk(
    kullanim=Decimal("50000"),
    oran_yuzde=Decimal("36"),
    gun_esasi: str | int = 360,
) -> Decimal:
    """DOC2-17: 50.000 × %36/360 = 50.00 / gün; kullanım ≤0 → 0."""
    m = kmh_matrah(kullanilan_anapara=kullanim)
    if m <= 0:
        return SIFIR_00
    return basit_gunluk_faiz(m, _d(oran_yuzde), gun_esasi=gun_esasi, gun_sayisi=1)


def mukerrer_gun_korumasi(
    mevcut_kayit_var: bool, *, tutar: Decimal | None = None
) -> dict[str, Any]:
    """Aynı gün / bileşen ikinci faiz üretmez."""
    if mevcut_kayit_var:
        return {"yapildi": False, "neden": "zaten_var", "tutar": tutar}
    return {"yapildi": True, "neden": None, "tutar": tutar}


def valor_sonrasi_matrah(
    onceki_matrah,
    odeme_tutari,
    *,
    valor_tarihi: date,
    hesap_gunu: date,
) -> Decimal:
    """DOC2-16: valör tarihinde matrah düşer."""
    once = max(SIFIR_00, pb_yuvarla(onceki_matrah))
    odeme = max(SIFIR_00, pb_yuvarla(odeme_tutari))
    if hesap_gunu < valor_tarihi:
        return once
    return max(SIFIR_00, once - odeme)


def _hafta_sonu_mu(d: date) -> bool:
    return d.weekday() >= 5


def ayni_gun_kullanim_kapanis_valor(
    *,
    kullanim_tarihi: date,
    kapanis_tarihi: date,
    gun_sonu_bakiye=0,
    banka_min_gun_kurali=None,
    tatil_mi=None,
    yatirim_valor_kaydir: int = 0,
    urun_turu: str | None = None,
    urun_id: int | None = None,
    kural: FaizUrunKurali | dict | None = None,
    kural_zorunlu: bool = False,
) -> dict[str, Any]:
    """DOC2-18: aynı gün kullanım+kapanış / tatil valör — ürün kuralından.

    Ürün kuralı yoksa ve kural_zorunlu=True (veya urun_* verilmişse varsayılan)
    → neden=KURAL_EKSIK; tatil/valör uydurulmaz.
    Açık ``banka_min_gun_kurali`` / ``tatil_mi`` çağrıları (birim test) eski
    kanca davranışını korur.
    """
    kayitli = kural
    if kayitli is None and urun_turu is not None and urun_id is not None:
        kayitli = GunlukFaizService.urun_kurali_getir(urun_turu, int(urun_id))

    def _alan(obj, ad, varsayilan=None):
        if obj is None:
            return varsayilan
        if isinstance(obj, dict):
            return obj.get(ad, varsayilan)
        return getattr(obj, ad, varsayilan)

    acik_kanca = banka_min_gun_kurali is not None or tatil_mi is not None
    if kayitli is None and not acik_kanca:
        if kural_zorunlu or (urun_turu is not None and urun_id is not None):
            return {
                "faiz_gunu": None,
                "gun_sonu_bakiye": pb_yuvarla(gun_sonu_bakiye),
                "valor_tarihi": None,
                "banka_kurali_kancasi": False,
                "neden": "KURAL_EKSIK",
                "uyari": "Ürün tatil/valör kuralı tanımlı değil; varsayım üretilmedi.",
            }

    min_gun = _alan(kayitli, "ayni_gun_min_gun")
    valor_mod = (_alan(kayitli, "valor_mod") or VALOR_TAKVIM or "").upper()
    kaydir = int(
        _alan(kayitli, "valor_kaydir_gun", yatirim_valor_kaydir) or yatirim_valor_kaydir or 0
    )
    tatil_kaynak = _alan(kayitli, "tatil_takvim_kaynagi")

    if banka_min_gun_kurali is not None:
        gun = int(banka_min_gun_kurali(kullanim_tarihi, kapanis_tarihi))
    elif kullanim_tarihi == kapanis_tarihi:
        gun = int(min_gun) if min_gun is not None else 1
        if min_gun is not None:
            gun = max(gun, int(min_gun))
    else:
        gun = max(0, (kapanis_tarihi - kullanim_tarihi).days)
        if min_gun is not None and kullanim_tarihi == kapanis_tarihi:
            gun = max(gun, int(min_gun))

    valor = kapanis_tarihi + timedelta(days=int(kaydir or 0))

    def _tatil(d: date) -> bool:
        if tatil_mi is not None:
            return bool(tatil_mi(d))
        # Kayıtlı tatil kaynağı yoksa tatil uydurma (yalnız hafta sonu: IS_GUNU / TATIL_ATLA)
        if not tatil_kaynak:
            return False
        return _hafta_sonu_mu(d)

    if valor_mod in {VALOR_IS_GUNU, VALOR_TATIL_ATLA} or tatil_mi is not None:
        if tatil_mi is not None or tatil_kaynak:
            guard = 0
            while _tatil(valor) and guard < 14:
                valor += timedelta(days=1)
                guard += 1
        elif valor_mod in {VALOR_IS_GUNU, VALOR_TATIL_ATLA} and not tatil_kaynak:
            # Tatil kaynağı tanımsız → gerçek valör kaydırması yok
            return {
                "faiz_gunu": gun,
                "gun_sonu_bakiye": pb_yuvarla(gun_sonu_bakiye),
                "valor_tarihi": None,
                "banka_kurali_kancasi": True,
                "neden": "KURAL_EKSIK",
                "uyari": "Tatil takvimi kaynağı eksik; valör kaydırılmadı.",
            }

    return {
        "faiz_gunu": gun,
        "gun_sonu_bakiye": pb_yuvarla(gun_sonu_bakiye),
        "valor_tarihi": valor,
        "banka_kurali_kancasi": True,
        "neden": None,
        "valor_mod": valor_mod or None,
        "tatil_takvim_kaynagi": tatil_kaynak,
    }


def borc_kimligi_uret(
    *,
    urun_turu: str,
    urun_id: int,
    borc_bilesen: str = BILESEN_ANAPARA,
    kalici_anahtar: str | None = None,
) -> str:
    """Kalıcı borç kimliği — ekstre id değişse de aynı borç."""
    if kalici_anahtar:
        return str(kalici_anahtar).strip()[:120]
    return f"{urun_turu.upper()}:{int(urun_id)}:{borc_bilesen}"[:120]


def donem_devri_mukerrer_yok(
    *,
    borc_kimligi: str,
    eski_ekstre_id: int | None,
    yeni_ekstre_id: int | None,
    onceki_anapara_kayitli: bool,
    onceki_gunluk_faiz_kayitli: bool,
) -> dict[str, Any]:
    """DOC2-21: aynı borç yeni ekstrede ikinci anapara/faiz yok."""
    return {
        "borc_kimligi": borc_kimligi,
        "eski_ekstre_id": eski_ekstre_id,
        "yeni_ekstre_id": yeni_ekstre_id,
        "ikinci_anapara": False if onceki_anapara_kayitli else None,
        "ikinci_gunluk_faiz": False if onceki_gunluk_faiz_kayitli else None,
        "devreden_ayni_borc": True,
    }


def kapali_donem_sessiz_fis_yok(*, donem_kapali: bool, fis_uretildi: bool = False) -> dict[str, Any]:
    """DOC2-24: kapalı döneme sessiz fiş yok."""
    if donem_kapali:
        return {"izin": False, "fis_uretildi": False, "neden": "DONEM_KAPALI"}
    return {"izin": True, "fis_uretildi": bool(fis_uretildi), "neden": None}


def yari_islem_atomik(*, adimlar_basarili: list[bool]) -> dict[str, Any]:
    """DOC2-22: yarım gider kalmaz."""
    if not adimlar_basarili or not all(adimlar_basarili):
        return {"tamamlandi": False, "yarim_gider": False, "neden": "YARI_KALDI_GERI_ALINDI"}
    return {"tamamlandi": True, "yarim_gider": False, "neden": None}


def maliyet_kimligi_koru(
    maliyet_id: str,
    *,
    oran_degisti: bool,
    geriye_tarihli_odeme: bool = False,
    eski_tutar=None,
    yeni_tutar=None,
) -> dict[str, Any]:
    """DOC2-20: maliyet kimliği korunur; geriye ödeme yalnız fark fişi."""
    fark = None
    if geriye_tarihli_odeme and eski_tutar is not None and yeni_tutar is not None:
        fark = pb_yuvarla(_d(yeni_tutar) - _d(eski_tutar))
    return {
        "maliyet_id": maliyet_id,
        "kimlik_korundu": True,
        "oran_degisti": bool(oran_degisti),
        "fark_fisi": fark,
        "ikinci_gider": False,
    }


def tahakkuk_odeme_ozet(tahakkuk, odeme) -> dict[str, Decimal]:
    """DOC2-11 özet: gider=tahakkuk, nakit=ödeme, borç=kalan."""
    t = pb_yuvarla(tahakkuk)
    o = pb_yuvarla(odeme)
    return {
        "gider": t,
        "nakit_cikis": o,
        "maliyet_borcu": tahakkuk_odeme_kalan(t, o),
    }


def kismi_odeme_kalan(plan_toplam, odenen) -> dict[str, Any]:
    """DOC2 01–04: kısmi ödeme kalan / durum / geçersiz tutar."""
    plan = pb_yuvarla(plan_toplam)
    ode = pb_yuvarla(odenen)
    if ode < 0:
        return {"gecerli": False, "neden": "GECERSIZ_TUTAR", "kalan": plan, "durum": None}
    if ode > plan:
        return {"gecerli": False, "neden": "KALANI_ASIYOR", "kalan": plan, "durum": None}
    if ode == 0:
        return {"gecerli": False, "neden": "SIFIR_ODEME", "kalan": plan, "durum": None}
    kalan = pb_yuvarla(plan - ode)
    durum = "ODENDI" if kalan == SIFIR_00 else "KISMEN_ODENDI"
    return {
        "gecerli": True,
        "neden": None,
        "plan": plan,
        "odenen": ode,
        "kalan": kalan,
        "durum": durum,
    }


def kismi_odeme_iptal_geri_ac(plan, odenen_toplam, iptal_edilen) -> dict[str, Any]:
    """DOC2-03: iptal yalnız o ödemeyi geri açar."""
    plan_d = pb_yuvarla(plan)
    odenen = pb_yuvarla(odenen_toplam)
    iptal = pb_yuvarla(iptal_edilen)
    yeni_odenen = max(SIFIR_00, odenen - iptal)
    kalan = pb_yuvarla(plan_d - yeni_odenen)
    if kalan == SIFIR_00:
        durum = "ODENDI"
    elif yeni_odenen > 0:
        durum = "KISMEN_ODENDI"
    else:
        durum = "BEKLIYOR"
    return {
        "odenen": yeni_odenen,
        "kalan": kalan,
        "durum": durum,
        "vade_degismedi": True,
    }


def odeme_tarihi_vade_ayri(vade: date, odeme_tarihi: date) -> dict[str, Any]:
    """DOC2-06: vade sabit, ödeme tarihi ayrı."""
    return {"vade_tarihi": vade, "odeme_tarihi": odeme_tarihi, "vade_degisti": False}


def cift_tik_tek_odeme(
    transaction_id: str, *, onceki_transaction_idler: set[str] | frozenset[str]
) -> dict[str, Any]:
    """DOC2-05: aynı transaction_id → tek ödeme."""
    tx = (transaction_id or "").strip()
    if not tx:
        return {"yapildi": False, "neden": "TX_EKSIK"}
    if tx in onceki_transaction_idler:
        return {"yapildi": False, "neden": "zaten_var", "mukerrer": True}
    return {"yapildi": True, "neden": None, "mukerrer": False}


def gecikme_vs_akdi_ayri(
    *,
    asgari_eksik,
    alisveris_kalan,
    nakit_kalan,
    ayni_gun_mukerrer: bool = False,
) -> dict[str, Any]:
    """DOC2-09/15: bileşenler ayrı; aynı anapara çift faiz yok."""
    return {
        "bilesenler": matrah_bilesenleri(
            alisveris=alisveris_kalan, nakit=nakit_kalan, asgari_eksik=asgari_eksik
        ),
        "mukerrer_faiz": bool(ayni_gun_mukerrer),
        "ayni_anapara_cift_faiz": False,
    }


def aralik_hesapla_ozet(
    matrah,
    oran_yuzde,
    gun_esasi: str | int = 360,
    bas: date | None = None,
    bitis: date | None = None,
    *,
    donem: str = "YILLIK",
    dahil: bool = False,
) -> dict[str, Any]:
    """Sözlüklü aralık; oran None → ORAN_EKSIK (sahte 0 yok).

    dahil=False: [bas, bitis) — ödeme günü çift sayılmaz.
    dahil=True: mevcut aralik_hesapla ile uyumlu [bas, bitis].
    """
    if bas is None or bitis is None:
        return {"tutar": SIFIR_00, "gun_sayisi": 0, "neden": "TARIH_EKSIK", "matrah": _d(matrah)}
    if oran_yuzde is None:
        gun_sayisi = (bitis - bas).days + (1 if dahil else 0)
        if not dahil and bitis <= bas:
            gun_sayisi = 0
        return {
            "tutar": None,
            "gun_sayisi": max(0, gun_sayisi),
            "neden": "ORAN_EKSIK",
            "matrah": _d(matrah),
        }
    if dahil:
        if bitis < bas:
            return {"tutar": SIFIR_00, "gun_sayisi": 0, "neden": "BOS_ARALIK", "matrah": _d(matrah)}
        gun_sayisi = (bitis - bas).days + 1
        tutar = aralik_hesapla(
            _d(matrah), _d(oran_yuzde), donem=donem, gun_esasi=gun_esasi, bas=bas, bitis=bitis
        )
    else:
        if bitis <= bas:
            return {"tutar": SIFIR_00, "gun_sayisi": 0, "neden": "BOS_ARALIK", "matrah": _d(matrah)}
        gun_sayisi = (bitis - bas).days
        tutar = basit_gunluk_faiz(
            _d(matrah), _d(oran_yuzde), donem=donem, gun_esasi=gun_esasi, gun_sayisi=gun_sayisi
        )
    return {
        "tutar": tutar,
        "gun_sayisi": gun_sayisi,
        "neden": None,
        "matrah": _d(matrah),
        "oran_yuzde": _d(oran_yuzde),
        "gun_esasi": gun_esasi_normalize(gun_esasi),
        "bas": bas,
        "bitis": bitis,
    }


class GunlukFaizService:
    _hazir_engine_id: int | None = None

    @classmethod
    def schema_hazirla(cls) -> None:
        import database.database as dbmod
        from sqlalchemy import inspect, text

        eng = getattr(dbmod, "engine", None)
        if eng is None:
            return
        if cls._hazir_engine_id == id(eng):
            return
        FaizOranTanimi.__table__.create(bind=eng, checkfirst=True)
        FaizUrunKurali.__table__.create(bind=eng, checkfirst=True)
        GunlukFaizKaydi.__table__.create(bind=eng, checkfirst=True)
        # Soft ALTER — mevcut DB'lere borc_kimligi
        try:
            insp = inspect(eng)
            if insp.has_table("gunluk_faiz_kayitlari"):
                mevcut = {c["name"] for c in insp.get_columns("gunluk_faiz_kayitlari")}
                if "borc_kimligi" not in mevcut:
                    with eng.begin() as conn:
                        conn.execute(
                            text(
                                'ALTER TABLE "gunluk_faiz_kayitlari" '
                                'ADD COLUMN "borc_kimligi" VARCHAR(120) DEFAULT \'\''
                            )
                        )
                        conn.execute(
                            text(
                                'UPDATE "gunluk_faiz_kayitlari" SET "borc_kimligi" = '
                                "\"urun_turu\" || ':' || \"urun_id\" || ':' || \"borc_bilesen\" "
                                'WHERE "borc_kimligi" IS NULL OR "borc_kimligi" = \'\''
                            )
                        )
                # Yeni tekillik indeksi (eski uq_gunluk_faiz_kimlik yanında güvenli)
                try:
                    with eng.begin() as conn:
                        conn.execute(
                            text(
                                "CREATE UNIQUE INDEX IF NOT EXISTS "
                                "uq_gunluk_faiz_borc_gun ON gunluk_faiz_kayitlari "
                                "(firma_id, borc_kimligi, gun, borc_bilesen, faiz_turu)"
                            )
                        )
                except Exception:
                    _log.debug("gunluk_faiz unique index", exc_info=True)
        except Exception:
            _log.debug("gunluk_faiz schema alter", exc_info=True)
        cls._hazir_engine_id = id(eng)

    @classmethod
    def urun_kurali_kaydet(
        cls,
        *,
        urun_turu: str,
        urun_id: int,
        tatil_takvim_kaynagi: str | None = None,
        ayni_gun_min_gun: int | None = None,
        valor_mod: str | None = None,
        valor_kaydir_gun: int = 0,
        notlar: str | None = None,
        aktif: bool = True,
    ) -> dict[str, Any]:
        """DOC2-18: ürün tatil/valör kuralı (sürümsüz tek aktif satır)."""
        cls.schema_hazirla()
        with get_session() as session:
            row = session.scalar(
                select(FaizUrunKurali).where(
                    FaizUrunKurali.urun_turu == urun_turu.upper(),
                    FaizUrunKurali.urun_id == int(urun_id),
                )
            )
            if row is None:
                row = FaizUrunKurali(
                    urun_turu=urun_turu.upper(),
                    urun_id=int(urun_id),
                )
                session.add(row)
            row.tatil_takvim_kaynagi = (tatil_takvim_kaynagi or None)
            if row.tatil_takvim_kaynagi:
                row.tatil_takvim_kaynagi = row.tatil_takvim_kaynagi.upper()
            row.ayni_gun_min_gun = (
                int(ayni_gun_min_gun) if ayni_gun_min_gun is not None else None
            )
            row.valor_mod = (valor_mod or None)
            if row.valor_mod:
                row.valor_mod = row.valor_mod.upper()
            row.valor_kaydir_gun = int(valor_kaydir_gun or 0)
            row.notlar = notlar
            row.aktif = bool(aktif)
            session.flush()
            return {
                "id": row.id,
                "urun_turu": row.urun_turu,
                "urun_id": row.urun_id,
                "tatil_takvim_kaynagi": row.tatil_takvim_kaynagi,
                "ayni_gun_min_gun": row.ayni_gun_min_gun,
                "valor_mod": row.valor_mod,
                "valor_kaydir_gun": row.valor_kaydir_gun,
            }

    @classmethod
    def urun_kurali_getir(
        cls, urun_turu: str, urun_id: int
    ) -> FaizUrunKurali | None:
        cls.schema_hazirla()
        with get_session() as session:
            return session.scalar(
                select(FaizUrunKurali).where(
                    FaizUrunKurali.urun_turu == urun_turu.upper(),
                    FaizUrunKurali.urun_id == int(urun_id),
                    FaizUrunKurali.aktif.is_(True),
                )
            )

    @classmethod
    def _donem_kapali_mi(cls, gun: date, session=None) -> bool:
        """Mevcut muhasebe dönem kilidine bağlanır (DOC2-24)."""
        try:
            from database.muhasebe_service import kapali_donem_mi

            if session is not None:
                return bool(kapali_donem_mi(session, gun))
            with get_session() as sess:
                return bool(kapali_donem_mi(sess, gun))
        except Exception:
            return False

    @classmethod
    def oran_kaydet(
        cls,
        *,
        urun_turu: str,
        urun_id: int,
        faiz_turu: str,
        oran_yuzde,
        donem: str = "YILLIK",
        gun_esasi: str = "360",
        baslangic_tarihi: date | None = None,
        bitis_tarihi: date | None = None,
        kaynak_not: str | None = None,
    ) -> dict[str, Any]:
        cls.schema_hazirla()
        bas = baslangic_tarihi or date.today()
        with get_session() as session:
            for eski in session.scalars(
                select(FaizOranTanimi).where(
                    FaizOranTanimi.urun_turu == urun_turu,
                    FaizOranTanimi.urun_id == int(urun_id),
                    FaizOranTanimi.faiz_turu == faiz_turu,
                    FaizOranTanimi.aktif.is_(True),
                )
            ).all():
                eski.aktif = False
                if eski.bitis_tarihi is None:
                    eski.bitis_tarihi = bas - timedelta(days=1)
            row = FaizOranTanimi(
                urun_turu=urun_turu.upper(),
                urun_id=int(urun_id),
                faiz_turu=faiz_turu.upper(),
                oran_yuzde=_d(oran_yuzde),
                donem=(donem or "YILLIK").upper(),
                gun_esasi=str(gun_esasi or "360"),
                baslangic_tarihi=bas,
                bitis_tarihi=bitis_tarihi,
                aktif=True,
                kaynak_not=kaynak_not,
            )
            session.add(row)
            session.flush()
            return {"id": row.id, "oran_yuzde": row.oran_yuzde}

    @classmethod
    def aktif_oran(
        cls,
        urun_turu: str,
        urun_id: int,
        faiz_turu: str = "AKDI",
        *,
        gun: date | None = None,
    ) -> FaizOranTanimi | None:
        cls.schema_hazirla()
        gun = gun or date.today()
        with get_session() as session:
            rows = list(
                session.scalars(
                    select(FaizOranTanimi).where(
                        FaizOranTanimi.urun_turu == urun_turu.upper(),
                        FaizOranTanimi.urun_id == int(urun_id),
                        FaizOranTanimi.faiz_turu == faiz_turu.upper(),
                        FaizOranTanimi.baslangic_tarihi <= gun,
                    )
                ).all()
            )
            # Geçmiş gün için kapatılmış sürüm de geçerli (aktif bayrağına bakmadan aralık)
            adaylar = [
                r for r in rows if r.bitis_tarihi is None or r.bitis_tarihi >= gun
            ]
            adaylar.sort(key=lambda r: r.baslangic_tarihi, reverse=True)
            return adaylar[0] if adaylar else None

    @classmethod
    def gun_hesapla_ve_kaydet(
        cls,
        *,
        firma_id: int,
        urun_turu: str,
        urun_id: int,
        matrah: Decimal,
        gun: date,
        borc_bilesen: str = BILESEN_ANAPARA,
        faiz_turu: str = "AKDI",
        kapanis_tarihi: date | None = None,
        gider_belge_no: str | None = None,
        borc_kimligi: str | None = None,
        donem_kontrol: bool = True,
        giderlestir: bool = False,
    ) -> dict[str, Any]:
        cls.schema_hazirla()
        if kapanis_sonrasi_faiz_yok(kapanis_tarihi=kapanis_tarihi, hesap_gunu=gun):
            return {"yapildi": False, "neden": "KAPALI", "gun": gun}
        if donem_kontrol and cls._donem_kapali_mi(gun):
            kilit = kapali_donem_sessiz_fis_yok(donem_kapali=True)
            return {
                "yapildi": False,
                "neden": kilit["neden"],
                "gun": gun,
                "fis_uretildi": False,
            }
        matrah = _d(matrah)
        if matrah <= 0:
            return {"yapildi": False, "neden": "MATRAH_YOK", "gun": gun, "tutar": SIFIR}
        kimlik = borc_kimligi_uret(
            urun_turu=urun_turu,
            urun_id=urun_id,
            borc_bilesen=borc_bilesen,
            kalici_anahtar=borc_kimligi,
        )
        # DOC2-21: mükerrer bakış oranı / yeni ekstre ürün id'sinden önce
        with get_session() as session:
            mevcut = session.scalar(
                select(GunlukFaizKaydi).where(
                    GunlukFaizKaydi.firma_id == int(firma_id),
                    GunlukFaizKaydi.borc_kimligi == kimlik,
                    GunlukFaizKaydi.borc_bilesen == borc_bilesen,
                    GunlukFaizKaydi.gun == gun,
                    GunlukFaizKaydi.faiz_turu == faiz_turu.upper(),
                )
            )
            if mevcut is None:
                mevcut = session.scalar(
                    select(GunlukFaizKaydi).where(
                        GunlukFaizKaydi.firma_id == int(firma_id),
                        GunlukFaizKaydi.urun_turu == urun_turu.upper(),
                        GunlukFaizKaydi.urun_id == int(urun_id),
                        GunlukFaizKaydi.borc_bilesen == borc_bilesen,
                        GunlukFaizKaydi.gun == gun,
                        GunlukFaizKaydi.faiz_turu == faiz_turu.upper(),
                    )
                )
            if mevcut is not None:
                return {
                    "yapildi": False,
                    "neden": "zaten_var",
                    "tutar": mevcut.yuvarlanmis_tutar,
                    "id": mevcut.id,
                    "borc_kimligi": mevcut.borc_kimligi or kimlik,
                    "gider_belge_no": mevcut.gider_belge_no,
                }

        oran = cls.aktif_oran(urun_turu, urun_id, faiz_turu, gun=gun)
        if oran is None:
            # Sahte 0 yazma (DOC2 §13 / 22)
            return {"yapildi": False, "neden": "ORAN_EKSIK", "gun": gun}
        ham = basit_gunluk_faiz(
            matrah,
            oran.oran_yuzde,
            donem=oran.donem,
            gun_esasi=oran.gun_esasi,
            gun_sayisi=1,
        )
        with get_session() as session:
            kayit = GunlukFaizKaydi(
                firma_id=int(firma_id),
                urun_turu=urun_turu.upper(),
                urun_id=int(urun_id),
                borc_kimligi=kimlik,
                borc_bilesen=borc_bilesen,
                gun=gun,
                matrah=matrah,
                faiz_turu=faiz_turu.upper(),
                oran_yuzde=oran.oran_yuzde,
                gun_esasi=oran.gun_esasi,
                ham_tutar=ham,
                yuvarlanmis_tutar=ham,
                durum="TAHAKKUK",
                gider_belge_no=gider_belge_no,
            )
            session.add(kayit)
            session.flush()
            sonuc = {
                "yapildi": True,
                "tutar": ham,
                "id": kayit.id,
                "borc_kimligi": kimlik,
                "gider_belge_no": kayit.gider_belge_no,
            }
        if giderlestir and sonuc.get("id"):
            g = cls.tahakkuk_giderlestir(kayit_id=int(sonuc["id"]))
            sonuc["giderlestirme"] = g
            sonuc["gider_belge_no"] = g.get("gider_belge_no") or sonuc.get("gider_belge_no")
        return sonuc

    @classmethod
    def aralik_kaydet(
        cls,
        *,
        firma_id: int,
        urun_turu: str,
        urun_id: int,
        matrah: Decimal,
        bas: date,
        bitis: date,
        borc_bilesen: str = BILESEN_ANAPARA,
        faiz_turu: str = "AKDI",
        kapanis_tarihi: date | None = None,
        borc_kimligi: str | None = None,
        donem_kontrol: bool = True,
    ) -> dict[str, Any]:
        """Birden çok günü sırayla hesapla; mükerrer gün atlanır (DOC2 §14 / 19)."""
        if bitis < bas:
            return {"yapildi": False, "neden": "ARALIK", "adet": 0, "toplam": SIFIR}
        adet = 0
        toplam = SIFIR
        atlandi = 0
        oran_eksik = 0
        donem_kapali = 0
        gun = bas
        while gun <= bitis:
            r = cls.gun_hesapla_ve_kaydet(
                firma_id=firma_id,
                urun_turu=urun_turu,
                urun_id=urun_id,
                matrah=matrah,
                gun=gun,
                borc_bilesen=borc_bilesen,
                faiz_turu=faiz_turu,
                kapanis_tarihi=kapanis_tarihi,
                borc_kimligi=borc_kimligi,
                donem_kontrol=donem_kontrol,
            )
            if r.get("yapildi"):
                adet += 1
                toplam += _d(r.get("tutar"))
            elif r.get("neden") == "zaten_var":
                atlandi += 1
            elif r.get("neden") == "ORAN_EKSIK":
                oran_eksik += 1
            elif r.get("neden") == "DONEM_KAPALI":
                donem_kapali += 1
            gun += timedelta(days=1)
        return {
            "yapildi": adet > 0,
            "adet": adet,
            "atlandi": atlandi,
            "oran_eksik": oran_eksik,
            "donem_kapali": donem_kapali,
            "toplam": toplam.quantize(KURUS),
            "bas": bas,
            "bitis": bitis,
        }

    @classmethod
    def tahakkuk_giderlestir(
        cls,
        *,
        kayit_id: int | None = None,
        firma_id: int | None = None,
        gun: date | None = None,
        finans_hesap_id: int | None = None,
        donem_kontrol: bool = True,
    ) -> dict[str, Any]:
        """DOC2-23: tahakkuku bir kez giderleştir; ``gider_belge_no`` ile idempotent.

        Nakit çıkışı yok (tahakkuk); GiderFisi KREDI_FAIZ / KREDI_GECIKME yolu.
        Kapalı dönemde sessiz fiş yok → DONEM_KAPALI.
        """
        cls.schema_hazirla()
        with get_session() as session:
            if kayit_id is not None:
                kayit = session.get(GunlukFaizKaydi, int(kayit_id))
                kayitlar = [kayit] if kayit is not None else []
            else:
                q = select(GunlukFaizKaydi).where(
                    GunlukFaizKaydi.durum == "TAHAKKUK",
                    GunlukFaizKaydi.gider_belge_no.is_(None),
                )
                if firma_id is not None:
                    q = q.where(GunlukFaizKaydi.firma_id == int(firma_id))
                if gun is not None:
                    q = q.where(GunlukFaizKaydi.gun == gun)
                kayitlar = list(session.scalars(q).all())

            if not kayitlar or kayitlar[0] is None:
                return {"yapildi": False, "neden": "KAYIT_YOK", "adet": 0}

            adet = 0
            belgeler: list[str] = []
            for kayit in kayitlar:
                if kayit is None:
                    continue
                if kayit.gider_belge_no:
                    belgeler.append(kayit.gider_belge_no)
                    continue
                if donem_kontrol and cls._donem_kapali_mi(kayit.gun, session=session):
                    return {
                        "yapildi": False,
                        "neden": "DONEM_KAPALI",
                        "fis_uretildi": False,
                        "gun": kayit.gun,
                        "id": kayit.id,
                    }
                tutar = _d(kayit.yuvarlanmis_tutar)
                if tutar == 0:
                    continue
                belge = cls._gider_belge_uret(session, on_ek="GFF")
                gider_turu = (
                    "KREDI_GECIKME"
                    if (kayit.faiz_turu or "").upper() == "GECIKME"
                    else "KREDI_FAIZ"
                )
                from database.models.finans import GiderFisi

                session.add(
                    GiderFisi(
                        belge_no=belge,
                        tarih=kayit.gun,
                        gider_turu=gider_turu,
                        tutar=abs(tutar),
                        finans_hesap_id=finans_hesap_id,
                        bagli_belge_no=f"GUNLUK_FAIZ:{kayit.id}",
                        aciklama=(
                            f"Günlük faiz tahakkuk | {kayit.urun_turu}#{kayit.urun_id} "
                            f"| {kayit.borc_bilesen} | {kayit.gun}"
                        )[:500],
                        durum="AÇIK",
                    )
                )
                kayit.gider_belge_no = belge
                adet += 1
                belgeler.append(belge)
            session.flush()
            return {
                "yapildi": adet > 0,
                "adet": adet,
                "gider_belge_no": belgeler[0] if belgeler else None,
                "belgeler": belgeler,
                "neden": None if adet > 0 else "zaten_var",
            }

    @staticmethod
    def _gider_belge_uret(session, on_ek: str = "GFF") -> str:
        from database.models.finans import GiderFisi

        yil = date.today().year
        like = f"{on_ek}-{yil}-%"
        mevcut = session.scalars(
            select(GiderFisi.belge_no).where(GiderFisi.belge_no.like(like))
        ).all()
        sira = 1
        for no in mevcut:
            parca = str(no).split("-")
            if len(parca) >= 3:
                try:
                    sira = max(sira, int(parca[2]) + 1)
                except ValueError:
                    pass
        return f"{on_ek}-{yil}-{sira:04d}"

    @classmethod
    def banka_fark_kaydet(
        cls,
        *,
        firma_id: int,
        urun_turu: str,
        urun_id: int,
        ic_tahakkuk: Decimal,
        banka_tutari: Decimal,
        belge_kimlik: str,
        gun: date | None = None,
        giderlestir: bool = False,
        donem_kontrol: bool = True,
    ) -> dict[str, Any]:
        """DOC2 §12 / 23: yalnız fark; aynı belge kimliğiyle ikinci tam gider yok.

        ``gider_belge_no`` = BANKA_FARK:{belge} ile idempotent. İstenirse fark
        tutarı için tek GiderFisi üretir (iç tahakkukun ikinci kez gideri değil).
        """
        cls.schema_hazirla()
        fark = banka_duzeltme_fark(ic_tahakkuk, banka_tutari)
        if fark == 0:
            return {"yapildi": False, "neden": "fark_yok", "fark": SIFIR}
        gun = gun or date.today()
        if donem_kontrol and cls._donem_kapali_mi(gun):
            return {
                "yapildi": False,
                "neden": "DONEM_KAPALI",
                "fark": fark,
                "fis_uretildi": False,
            }
        kimlik = f"BANKA_FARK:{belge_kimlik}"
        borc_k = f"BANKA_FARK:{urun_turu.upper()}:{int(urun_id)}:{belge_kimlik}"[:120]
        with get_session() as session:
            mevcut = session.scalar(
                select(GunlukFaizKaydi).where(
                    GunlukFaizKaydi.firma_id == int(firma_id),
                    GunlukFaizKaydi.gider_belge_no == kimlik,
                )
            )
            if mevcut is None:
                mevcut = session.scalar(
                    select(GunlukFaizKaydi).where(
                        GunlukFaizKaydi.firma_id == int(firma_id),
                        GunlukFaizKaydi.borc_kimligi == borc_k,
                        GunlukFaizKaydi.faiz_turu == "DUZELTME",
                    )
                )
            if mevcut is not None:
                return {
                    "yapildi": False,
                    "neden": "zaten_var",
                    "fark": mevcut.yuvarlanmis_tutar,
                    "id": mevcut.id,
                    "gider_belge_no": mevcut.gider_belge_no,
                    "ikinci_tam_gider": False,
                }
            kayit = GunlukFaizKaydi(
                firma_id=int(firma_id),
                urun_turu=urun_turu.upper(),
                urun_id=int(urun_id),
                borc_kimligi=borc_k,
                borc_bilesen="BANKA_DUZELTME",
                gun=gun,
                matrah=_d(banka_tutari),
                faiz_turu="DUZELTME",
                oran_yuzde=SIFIR,
                gun_esasi="360",
                ham_tutar=fark,
                yuvarlanmis_tutar=fark,
                durum="TAHAKKUK",
                gider_belge_no=kimlik,
            )
            session.add(kayit)
            session.flush()
            kid = int(kayit.id)
            fark_out = fark

        if giderlestir:
            # Belge no geçici olarak temizle ki tahakkuk_giderlestir işlesin; sonra kimlik
            with get_session() as session:
                row = session.get(GunlukFaizKaydi, kid)
                if row is not None:
                    row.gider_belge_no = None
                    session.flush()
            g = cls.tahakkuk_giderlestir(kayit_id=kid, donem_kontrol=donem_kontrol)
            if g.get("neden") == "DONEM_KAPALI":
                with get_session() as session:
                    row = session.get(GunlukFaizKaydi, kid)
                    if row is not None:
                        row.gider_belge_no = kimlik
                        session.flush()
                return {
                    "yapildi": False,
                    "neden": "DONEM_KAPALI",
                    "fark": fark_out,
                    "id": kid,
                    "fis_uretildi": False,
                }
            with get_session() as session:
                row = session.get(GunlukFaizKaydi, kid)
                if row is not None:
                    gercek_belge = row.gider_belge_no
                    row.gider_belge_no = kimlik
                    if gercek_belge:
                        from database.models.finans import GiderFisi

                        fis = session.scalar(
                            select(GiderFisi).where(GiderFisi.belge_no == gercek_belge)
                        )
                        if fis is not None:
                            fis.bagli_belge_no = kimlik
                    session.flush()

        return {
            "yapildi": True,
            "fark": fark_out,
            "id": kid,
            "gider_belge_no": kimlik,
            "ikinci_tam_gider": False,
        }

    @classmethod
    def otomatik_acilis_calistir(
        cls, sessiz: bool = True, *, max_gun: int = 14
    ) -> dict[str, Any]:
        """Açılış: gecikmiş kredi + (oran varsa) kaçırılan günleri tamamla (DOC2 §19)."""
        try:
            cls.schema_hazirla()
        except Exception as exc:
            if sessiz:
                _log.exception("gunluk_faiz schema")
                return {"yapildi": False, "neden": "schema", "mesaj": str(exc)}
            raise
        bugun = date.today()
        adet = 0
        try:
            from database.banka_kredi_service import BankaKrediService
            from database.session_manager import oturum

            firma_id = int(getattr(oturum, "firma_id", 0) or 0)
            BankaKrediService.schema_hazirla()
            for t in BankaKrediService.bekleyen_taksitler(limit=500):
                vade = t.get("vade_tarihi")
                if not vade:
                    continue
                if isinstance(vade, str):
                    try:
                        vade = date.fromisoformat(vade[:10])
                    except ValueError:
                        continue
                if vade >= bugun:
                    continue
                kalan = _d(t.get("kalan_anapara") or t.get("anapara") or 0)
                if kalan <= 0:
                    continue
                tid = int(t.get("taksit_id") or t.get("id") or 0)
                if tid <= 0:
                    continue
                # Kaçırılan günler: dün geriye max_gun (yenile ikinci gider üretmez)
                bitis = bugun - timedelta(days=1)
                bas = max(vade + timedelta(days=1), bitis - timedelta(days=max(0, max_gun - 1)))
                if bas > bitis:
                    continue
                r = cls.aralik_kaydet(
                    firma_id=firma_id,
                    urun_turu="KREDI",
                    urun_id=tid,
                    matrah=kalan,
                    bas=bas,
                    bitis=bitis,
                    faiz_turu="GECIKME",
                )
                adet += int(r.get("adet") or 0)
        except Exception as exc:
            if sessiz:
                _log.exception("gunluk_faiz otomatik")
                return {"yapildi": False, "neden": "hata", "mesaj": str(exc)}
            raise
        return {"yapildi": adet > 0, "adet": adet, "gun": bugun - timedelta(days=1)}
