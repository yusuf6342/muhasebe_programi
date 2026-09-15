"""Hızlı Satış Aşama 4 — müşteri, fiyat grubu, risk ve yetki yardımcıları (saf mantık).

DB yazımı yalnızca seed (`perakende_cari_hazirla`) içindir; sepet hâlâ bellekte.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

# —— Sabitler ——

PERAKENDE_MUSTERI_UNVAN = "PERAKENDE MÜŞTERİ"
PERAKENDE_MUSTERI_GRUP = "PERAKENDE MÜŞTERİ"
PERAKENDE_MUSTERI_KOD = "PRK001"
VARSAYILAN_FIYAT_LISTESI = "SATIŞ FİYATI 1"

# Ödeme niyeti / kısa ad → stok satış fiyat listesi (stok_service ESKI_FIYAT_ESLEME ile uyumlu)
ODEME_FIYAT_ESLEME: dict[str, str] = {
    "PERAKENDE": "SATIŞ FİYATI 1",
    "NAKIT": "SATIŞ FİYATI 2",
    "NAKİT": "SATIŞ FİYATI 2",
    "ACIK HESAP": "SATIŞ FİYATI 3",
    "AÇIK HESAP": "SATIŞ FİYATI 3",
    "KK": "SATIŞ FİYATI 4",
    "KREDI KARTI": "SATIŞ FİYATI 4",
    "KREDİ KARTI": "SATIŞ FİYATI 4",
}

YUKSEK_ISKONTO_ESIGI = Decimal("10")  # % — üzeri için ayrı izin

IZIN_FIYAT_DEGISTIRME = "hizli_satis_fiyat_degistirme"
IZIN_YUKSEK_ISKONTO = "hizli_satis_yuksek_iskonto"
IZIN_ACIK_HESAP = "hizli_satis_acik_hesap"
IZIN_IPTAL = "hizli_satis_iptal"


def _d(deger, varsayilan: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(deger if deger is not None else varsayilan))
    except Exception:
        return Decimal(str(varsayilan))


def _norm_anahtar(metin: str | None) -> str:
    return (metin or "").strip().casefold().replace("ı", "i").replace("İ", "i")


def fiyat_listesi_coz(
    *,
    satis_fiyat_listesi: str | None = None,
    musteri_grubu: str | None = None,
    odeme_niyeti: str | None = None,
) -> str:
    """Müşteri kartı / grup / ödeme niyetinden stok fiyat listesi adını üretir."""
    niyet = (odeme_niyeti or "").strip()
    if niyet:
        for anahtar, liste in ODEME_FIYAT_ESLEME.items():
            if _norm_anahtar(anahtar) == _norm_anahtar(niyet):
                return liste
        # Doğrudan "SATIŞ FİYATI N" verilmiş olabilir
        if niyet.upper().startswith("SATIŞ FİYATI") or niyet.upper().startswith("SATIS FIYATI"):
            return niyet.strip()

    kart = (satis_fiyat_listesi or "").strip()
    if kart:
        return kart

    grup = (musteri_grubu or "").strip()
    if grup:
        # "PERAKENDE MÜŞTERİ" grubu → SF1
        if "perakende" in _norm_anahtar(grup):
            return VARSAYILAN_FIYAT_LISTESI
        for anahtar, liste in ODEME_FIYAT_ESLEME.items():
            if _norm_anahtar(anahtar) in _norm_anahtar(grup) or _norm_anahtar(grup) == _norm_anahtar(
                anahtar
            ):
                return liste

    return VARSAYILAN_FIYAT_LISTESI


def fiyat_degistirme_izinli(yetki_kontrol: Callable[..., bool] | None = None) -> bool:
    """Satır birim fiyatı değiştirme yetkisi."""
    if yetki_kontrol is None:
        from database.access import yetki_var

        yetki_kontrol = yetki_var
    return bool(yetki_kontrol(IZIN_FIYAT_DEGISTIRME, "satis_duzenleme"))


def iptal_iade_izinli(yetki_kontrol: Callable[..., bool] | None = None) -> bool:
    """Tamamlanmış hızlı satış iptal / iade yetkisi."""
    if yetki_kontrol is None:
        from database.access import yetki_var

        yetki_kontrol = yetki_var
    return bool(yetki_kontrol(IZIN_IPTAL))


def iskonto_degistirme_sonucu(
    yeni_oran,
    *,
    esik: Decimal = YUKSEK_ISKONTO_ESIGI,
    yetki_kontrol: Callable[..., bool] | None = None,
) -> dict[str, Any]:
    """İskonto oranı için UI kapısı.

    Dönüş: izinli (bool), yuksek (bool), mesaj (str)
    """
    if yetki_kontrol is None:
        from database.access import yetki_var

        yetki_kontrol = yetki_var

    oran = _d(yeni_oran)
    if oran < 0 or oran > 100:
        return {
            "izinli": False,
            "yuksek": False,
            "mesaj": "İskonto oranı 0–100 arasında olmalıdır.",
        }
    yuksek = oran > _d(esik)
    if yuksek and not yetki_kontrol(IZIN_YUKSEK_ISKONTO):
        return {
            "izinli": False,
            "yuksek": True,
            "mesaj": (
                f"%{esik:f}".rstrip("0").rstrip(".")
                + f" üzeri iskonto için «{IZIN_YUKSEK_ISKONTO}» yetkisi gerekir."
            ),
        }
    # Düşük iskonto: satış düzenleme veya fiyat değiştirme yeter
    if not yetki_kontrol(IZIN_FIYAT_DEGISTIRME, IZIN_YUKSEK_ISKONTO, "satis_duzenleme"):
        return {
            "izinli": False,
            "yuksek": yuksek,
            "mesaj": "İskonto değiştirme yetkiniz yok.",
        }
    return {"izinli": True, "yuksek": yuksek, "mesaj": ""}


def acik_hesap_risk_degerlendir(
    *,
    bakiye=0,
    risk_limiti=None,
    ek_tutar=0,
    acik_hesap_yetkisi: bool = False,
) -> dict[str, Any]:
    """Açık hesap / risk limiti UI + servis kontrolü.

    Dönüş alanları: durum (ok|uyari|engel), mesaj, yeni_bakiye, kalan_limit
    Servis (`HizliSatisService`) kalan > 0 iken yetkisiz satışı engeller.
    """
    bakiye_d = _d(bakiye)
    ek_d = _d(ek_tutar)
    yeni = bakiye_d + ek_d
    limit_ham = risk_limiti
    if limit_ham is None or str(limit_ham).strip() == "":
        kalan = None
        if ek_d > 0 and not acik_hesap_yetkisi:
            return {
                "durum": "uyari",
                "mesaj": (
                    "Açık hesap yetkisi yok; risk limiti tanımsız. "
                    "Tahsilatsız / kısmi satış için «hizli_satis_acik_hesap» gerekir."
                ),
                "yeni_bakiye": yeni,
                "kalan_limit": None,
            }
        return {
            "durum": "ok",
            "mesaj": "",
            "yeni_bakiye": yeni,
            "kalan_limit": None,
        }

    limit = _d(limit_ham)
    if limit <= 0:
        # 0 = açık hesap kapalı sayılır
        if ek_d > 0 or bakiye_d > 0:
            if acik_hesap_yetkisi:
                return {
                    "durum": "uyari",
                    "mesaj": "Bu caride açık hesap risk limiti 0 (kapalı). Yetki ile devam edilebilir.",
                    "yeni_bakiye": yeni,
                    "kalan_limit": Decimal("0"),
                }
            return {
                "durum": "engel",
                "mesaj": "Bu caride açık hesap kapalı (risk limiti 0). Açık hesap yetkisi gerekir.",
                "yeni_bakiye": yeni,
                "kalan_limit": Decimal("0"),
            }
        return {
            "durum": "ok",
            "mesaj": "",
            "yeni_bakiye": yeni,
            "kalan_limit": Decimal("0"),
        }

    kalan = limit - yeni
    if yeni > limit:
        if acik_hesap_yetkisi:
            return {
                "durum": "uyari",
                "mesaj": (
                    f"Risk limiti aşılıyor (limit {_para_metin(limit)}, "
                    f"yeni bakiye {_para_metin(yeni)}). Yetki ile devam edilebilir."
                ),
                "yeni_bakiye": yeni,
                "kalan_limit": kalan,
            }
        return {
            "durum": "engel",
            "mesaj": (
                f"Risk limiti aşıldı (limit {_para_metin(limit)}, "
                f"yeni bakiye {_para_metin(yeni)}). Açık hesap yetkisi gerekir."
            ),
            "yeni_bakiye": yeni,
            "kalan_limit": kalan,
        }

    return {
        "durum": "ok",
        "mesaj": "",
        "yeni_bakiye": yeni,
        "kalan_limit": kalan,
    }


def _para_metin(tutar: Decimal) -> str:
    return f"{float(tutar):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " TL"


class FiyatDegisiklikGunlugu:
    """Fiyat/iskonto değişim kaydı — bellek + dosya günlüğü (Aşama 8)."""

    def __init__(self) -> None:
        self.kayitlar: list[dict[str, Any]] = []

    def ekle(
        self,
        *,
        stok_kodu: str,
        alan: str,
        eski,
        yeni,
        kullanici: str | None = None,
        not_: str | None = None,
    ) -> None:
        kayit = {
            "stok_kodu": (stok_kodu or "").strip(),
            "alan": alan,
            "eski": str(eski),
            "yeni": str(yeni),
            "kullanici": kullanici,
            "not": not_,
        }
        self.kayitlar.append(kayit)
        try:
            from hizli_satis_log import islem_yaz

            islem_yaz(
                "FIYAT_DEGISIKLIK",
                f"{kayit['stok_kodu']} {alan}: {eski} → {yeni}",
                detay=kayit,
                kullanici=kullanici,
            )
        except Exception:
            pass

    def temizle(self) -> None:
        self.kayitlar.clear()

    def __len__(self) -> int:
        return len(self.kayitlar)


def cari_ozet_dict(cari, *, bakiye=None) -> dict[str, Any]:
    """UI / sepet için serileştirilebilir cari özeti."""
    if cari is None:
        return {}
    return {
        "id": int(getattr(cari, "id", 0) or 0),
        "cari_kodu": (getattr(cari, "cari_kodu", None) or "").strip(),
        "unvan": (getattr(cari, "unvan", None) or "").strip(),
        "musteri_grubu": (getattr(cari, "musteri_grubu", None) or "").strip() or None,
        "satis_fiyat_listesi": (getattr(cari, "satis_fiyat_listesi", None) or "").strip()
        or None,
        "acik_hesap_risk_limiti": getattr(cari, "acik_hesap_risk_limiti", None),
        "bakiye": _d(bakiye) if bakiye is not None else None,
        "uyari_notu": (getattr(cari, "uyari_notu", None) or "").strip() or None,
    }


def varsayilan_cari_bul(session) -> Any | None:
    """Oturum içinde PERAKENDE MÜŞTERİ cari kartını bul (soft-delete dışı, aktif)."""
    from sqlalchemy import or_, select

    from database.models.cari import Cari

    aktif = (
        Cari.aktif.is_(True),
        or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)),
        Cari.cari_turu == "Müşteri",
    )
    # 1) Kod
    cari = session.scalar(
        select(Cari).where(Cari.cari_kodu == PERAKENDE_MUSTERI_KOD, *aktif)
    )
    if cari is not None:
        return cari
    # 2) Ünvan
    cari = session.scalar(
        select(Cari).where(Cari.unvan == PERAKENDE_MUSTERI_UNVAN, *aktif)
    )
    if cari is not None:
        return cari
    # 3) Grup adı eşleşmesi (ilk aktif)
    return session.scalar(
        select(Cari)
        .where(Cari.musteri_grubu == PERAKENDE_MUSTERI_GRUP, *aktif)
        .order_by(Cari.id)
    )


def varsayilan_cari_coz() -> dict[str, Any] | None:
    """Firma DB'den varsayılan perakende cari özeti; yoksa None."""
    from database.database import get_session

    with get_session() as session:
        cari = varsayilan_cari_bul(session)
        if cari is None:
            return None
        bakiye = None
        try:
            from database.cari_service import CariService

            ozet = CariService._ozet(cari, session)
            bakiye = ozet.get("bakiye")
        except Exception:
            bakiye = None
        return cari_ozet_dict(cari, bakiye=bakiye)
