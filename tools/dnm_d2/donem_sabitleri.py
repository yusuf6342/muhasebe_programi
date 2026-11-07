"""DNM ikinci dönem (D2) sabitleri — Word 06.11.2026 şartname.

Kullanıcı kararı (2026-11-07): dönem 01.09.2026–07.11.2026 dahil.
D2_HARIC_UST_SINIR = 2026-11-08T00:00:00+03:00 (hariç).

Tarih sabitleme ≠ aktarım kabulü. K05/K06 ve mali yazım ayrı kalır.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo("Europe/Istanbul")

KAYNAK_FIRMA_ADI = "DNM – RAY MOBİLYA AKSESUARLAR ETÜD"
KAYNAK_FIRMA_NO = "42178"

# Kabul edilmiş D1 kapanışı → D2 açılışı
D1_KAPANIS = date(2026, 8, 31)
D2_ACILIS_YEREL = datetime(2026, 9, 1, 0, 0, 0, tzinfo=ISTANBUL)
D2_ACILIS_UTC = datetime(2026, 8, 31, 21, 0, 0, tzinfo=timezone.utc)

# Kullanıcı kararı — kesin
D2_BITIS_DAHIL: date = date(2026, 11, 7)
D2_HARIC_UST_SINIR: datetime = datetime(2026, 11, 8, 0, 0, 0, tzinfo=ISTANBUL)
D2_HARIC_UST_SINIR_UTC: datetime = datetime(2026, 11, 7, 21, 0, 0, tzinfo=timezone.utc)
D2_BITIS_KARAR = {
    "kaynak": "kullanici",
    "karar_tarihi_yerel": "2026-11-07",
    "baslangic": "2026-09-01T00:00:00+03:00",
    "D2_BITIS_DAHIL": "2026-11-07",
    "D2_HARIC_UST_SINIR": "2026-11-08T00:00:00+03:00",
    "saat_dilimi": "Europe/Istanbul",
    "aktarim_kabulu_degil": True,
}

ONERILEN_SISTEM_DB = "cin_sistem_dnm_d2_20260901"
ONERILEN_FIRMA_DB = "cin_firma_dnm_d2_20260901"
PROFIL_ADI = "DNM İKİNCİ DÖNEM DENEME"

KORUNAN_HEDEFLER = frozenset(
    {
        "RAY001",
        "cin_sistem",
        "cin_firma_ray",
        "cin_sistem_deneme",
        "cin_firma_deneme",
        "cin_sistem_kabul_20261105",
        "cin_firma_kabul_20261105",
        "cin_sistem_restore_20261105",
        "cin_firma_restore_20261105",
        # D1 ayrı — temizleme / D2’ye dönüştürme / üzerine restore yok
        "cin_sistem_dnm_d1_20260831",
        "cin_firma_dnm_d1_20260831",
    }
)

CALISMA_KOK = "kurulum/dnm_d2_20260901"
D1_CALISMA_KOK = "kurulum/dnm_d1_20260831"

# Kullanıcı kararı: D2 sonrasında D1 devam; D1 çalışma kökü/DB korunur
D2_SONRASI_D1_DEVAM = True
D1_UZERINE_YAZMA_YOK = True
D1_DEVAM_NOTU = f"{D1_CALISMA_KOK}/DEVIR1_DEVAM_NOTU.json"

TALIMAT_DOCX = (
    "Cin_Muhasebe_DNM_D2_Aktarim_Talimati_2026-11-06.docx"
)
TALIMAT_SHA256_BEKLENEN = None

RAPOR_ONEKI_KAYNAK = "D2_20260901_KAYNAK_"
RAPOR_ONEKI_ACILIS = "D2_20260901_ACILIS_"
RAPOR_ONEKI_CIN = "D2_20260901_CIN_"

CALISMA_MODU = "HAZIRLIK"  # GERCEK_AKTARIM değil; tarih sabiti kabul sayılmaz


def bitis_secili_mi() -> bool:
    return D2_BITIS_DAHIL is not None and D2_HARIC_UST_SINIR is not None


def etki_d2_hareket_mi(d: date | datetime | None) -> bool | None:
    """Doğrulanmış mali/stok etki tarihine göre D2 kapsamı.

    datetime: [D2_ACILIS_YEREL, D2_HARIC_UST_SINIR) — saat dilimli.
    date (saat yok): 01.09.2026 … D2_BITIS_DAHIL dahil.
    Alma/görüntü zamanı bu fonksiyona verilmez.
    """
    if d is None:
        return None
    if isinstance(d, datetime):
        if d.tzinfo is None:
            d = d.replace(tzinfo=ISTANBUL)
        if d < D2_ACILIS_YEREL:
            return False
        if D2_HARIC_UST_SINIR is None:
            return None
        return d < D2_HARIC_UST_SINIR
    if d < date(2026, 9, 1):
        return False
    if D2_BITIS_DAHIL is None:
        return None
    return d <= D2_BITIS_DAHIL


def tarih_yalniz_d2_dahil_mi(d: date | None) -> bool | None:
    """Saat tutmayan kayıt: tarih ∈ [2026-09-01, D2_BITIS_DAHIL]."""
    if d is None:
        return None
    if D2_BITIS_DAHIL is None:
        return None
    return date(2026, 9, 1) <= d <= D2_BITIS_DAHIL


def kapsama_karari(
    *,
    etki_tarihi: date | datetime | None,
    alma_zamani: datetime | None = None,
) -> dict:
    """Döneme alma ölçütü etki tarihinden; alma zamanı ayrı kaydedilir."""
    return {
        "etki_d2": etki_d2_hareket_mi(etki_tarihi),
        "etki_tarihi": (
            etki_tarihi.isoformat() if isinstance(etki_tarihi, (date, datetime)) else None
        ),
        "alma_zamani": alma_zamani.isoformat() if alma_zamani else None,
        "alma_zamani_kapsam_olcutu_degil": True,
        "D2_BITIS_DAHIL": D2_BITIS_DAHIL.isoformat() if D2_BITIS_DAHIL else None,
        "D2_HARIC_UST_SINIR": D2_HARIC_UST_SINIR.isoformat() if D2_HARIC_UST_SINIR else None,
    }
