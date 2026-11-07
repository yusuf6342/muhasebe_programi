"""DNM D1 dönem sınırı ve kaynak kapısı birim testleri."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from tools.dnm_d1.donem_sabitleri import (
    DONEM_SONU,
    HARIC_UST_SINIR_YEREL,
    ONERILEN_FIRMA_DB,
    ONERILEN_SISTEM_DB,
    etki_tarihi_dahil_mi,
    tarih_yalniz_dahil_mi,
)
from tools.dnm_d1.kaynak_kapisi import mali_yazim_izinli_mi


IST = ZoneInfo("Europe/Istanbul")


def test_donem_sonu_dahil():
    assert DONEM_SONU == date(2026, 8, 31)
    assert tarih_yalniz_dahil_mi(date(2026, 8, 31)) is True
    assert tarih_yalniz_dahil_mi(date(2026, 9, 1)) is False


def test_haric_ust_sinir_saniye_alti():
    # 31.08.2026 23:59:59.999 Istanbul dahil
    son = datetime(2026, 8, 31, 23, 59, 59, 999999, tzinfo=IST)
    assert etki_tarihi_dahil_mi(son) is True
    # 01.09.2026 00:00:00 Istanbul hariç
    assert etki_tarihi_dahil_mi(HARIC_UST_SINIR_YEREL) is False
    assert etki_tarihi_dahil_mi(datetime(2026, 9, 1, 0, 0, 0, tzinfo=IST)) is False


def test_onerilen_db_adlari_korunanlardan_ayri():
    assert "dnm_d1" in ONERILEN_SISTEM_DB
    assert "20260831" in ONERILEN_FIRMA_DB
    assert ONERILEN_SISTEM_DB != ONERILEN_FIRMA_DB


def test_mali_yazim_baslangicta_engelli():
    ok, engeller = mali_yazim_izinli_mi()
    assert ok is False
    assert engeller  # en az bir engel
