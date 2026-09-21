"""Firma varsayılan KDV + satır KDV belirleme testleri."""

from decimal import Decimal
from unittest.mock import patch

from database.fatura_kdv_service import (
    FIRMA_VARSAYILAN_KDV_SECENEKLERI,
    kdv_oran_metni,
    kdv_orani_dogrula,
    satir_kdv_belirle,
)


def test_kdv_oran_metni_tam():
    assert kdv_oran_metni(20) == "%20"
    assert kdv_oran_metni(Decimal("20.000")) == "%20"
    assert kdv_oran_metni(Decimal("10")) == "%10"
    assert kdv_oran_metni(0) == "%0"
    assert kdv_oran_metni("1") == "%1"
    # Klasik rstrip('0') tuzağı: 20 → 2 olmamalı
    from database.fatura_kdv_service import satir_kdv_metin_sayisal

    assert satir_kdv_metin_sayisal(Decimal("20.0")) == "20"


def test_kdv_dogrula_izinli():
    assert kdv_orani_dogrula("%20", izinli=FIRMA_VARSAYILAN_KDV_SECENEKLERI) == Decimal("20")
    assert kdv_orani_dogrula(10, izinli=FIRMA_VARSAYILAN_KDV_SECENEKLERI) == Decimal("10")


def test_kdv_dogrula_hatali():
    try:
        kdv_orani_dogrula(8, izinli=FIRMA_VARSAYILAN_KDV_SECENEKLERI)
        assert False, "8 firma varsayılan seçeneklerinde olmamalı"
    except ValueError as e:
        assert "İzin verilen" in str(e)


def test_satir_kdv_stok_onceligi():
    with patch(
        "database.fatura_kdv_service.firma_varsayilan_kdv_orani",
        return_value=Decimal("20"),
    ):
        assert satir_kdv_belirle(stok_kdv=Decimal("10")) == Decimal("10")
        assert satir_kdv_belirle(stok_kdv=None) == Decimal("20")
        assert satir_kdv_belirle(kaynak_kdv=1, stok_kdv=10) == Decimal("1")


def test_satir_kdv_manuel_firma():
    with patch(
        "database.fatura_kdv_service.firma_varsayilan_kdv_orani",
        return_value=Decimal("10"),
    ):
        assert satir_kdv_belirle() == Decimal("10")


def test_kolon_min_genislik():
    from fatura_satir_kolon_prefs import EKRAN_SATIS, kolon_tanim_map

    meta = kolon_tanim_map(EKRAN_SATIS)["kdv"]
    assert meta["min_width"] >= 72
    assert meta["genislik"] >= 72
