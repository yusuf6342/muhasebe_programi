"""DNM birinci dönem (D1) sabitleri — 31.08.2026 kapanışı.

Talimat: Cin_Muhasebe_DNM_D1_Bakiye_Mutabakat_Talimati_2026-11-06.xlsx
Boş sayısal hücre sıfır değildir. EXE/paket bütün işler bitene kadar yok.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo("Europe/Istanbul")

KAYNAK_FIRMA_ADI = "DNM – RAY MOBİLYA AKSESUARLAR ETÜD"
KAYNAK_FIRMA_NO = "42178"  # oturum UID değil; girişte yeniden doğrulanacak

DONEM_SONU = date(2026, 8, 31)  # dahil
HARIC_UST_SINIR_YEREL = datetime(2026, 9, 1, 0, 0, 0, tzinfo=ISTANBUL)
HARIC_UST_SINIR_UTC = datetime(2026, 8, 31, 21, 0, 0, tzinfo=timezone.utc)

ONERILEN_SISTEM_DB = "cin_sistem_dnm_d1_20260831"
ONERILEN_FIRMA_DB = "cin_firma_dnm_d1_20260831"

# Üzerine yazılmayacak kurulumlar (D2 hedefleri dahil — D1↔D2 karışmaz)
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
        # D2 ayrı — D1 araçları temizlemez / dönüştürmez / üzerine restore etmez
        "cin_sistem_dnm_d2_20260901",
        "cin_firma_dnm_d2_20260901",
        "cin_sistem_dnm_d2_restore_test",
        "cin_firma_dnm_d2_restore_test",
    }
)

# D2 sonrası D1 devam; D2 öncesi zorunlu D1 işleri öncelikli
D2_SONRASI_D1_DEVAM = True
D1_D2_KARISIM_YASAK = True

CALISMA_KOK = "kurulum/dnm_d1_20260831"
TALIMAT_DOSYA = (
    "kurulum/dnm_d1_20260831/"
    "Cin_Muhasebe_DNM_D1_Bakiye_Mutabakat_Talimati_2026-11-06.xlsx"
)
TALIMAT_SHA256 = "0ACC53AB9AFB6D2BE2C27DED678CD64A9AC152CB5DF3F8074F6FF0C42E3637E5"

RAPOR_ONEKI_KAYNAK = "D1_20260831_KAYNAK_"
RAPOR_ONEKI_CIN = "D1_20260831_CIN_"


def etki_tarihi_dahil_mi(d: date | datetime | None) -> bool:
    """Gerçek mali/stok etki tarihi birinci dönem kapsamında mı?"""
    if d is None:
        return False
    if isinstance(d, datetime):
        if d.tzinfo is None:
            # Yerel varsayım yapma; çağıran timezone bilgisini sağlamalı
            d = d.replace(tzinfo=ISTANBUL)
        return d < HARIC_UST_SINIR_YEREL
    return d <= DONEM_SONU


def tarih_yalniz_dahil_mi(d: date | None) -> bool:
    """Saat tutmayan kayıtlar: tarih <= 31.08.2026."""
    if d is None:
        return False
    return d <= DONEM_SONU
