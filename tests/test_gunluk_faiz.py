"""Günlük faiz — sentetik kabul (talimat örnek: %36 / 360)."""

from decimal import Decimal

from database.gunluk_faiz_service import basit_gunluk_faiz


def test_10_gun_10000_yuzde36():
    # 10.000 × 0,36 / 360 × 10 = 100
    assert basit_gunluk_faiz(
        Decimal("10000"), Decimal("36"), donem="YILLIK", gun_esasi=360, gun_sayisi=10
    ) == Decimal("100.00")


def test_odeme_sonrasi_8000_10_gun():
    # 8.000 × 0,36 / 360 × 10 = 80
    assert basit_gunluk_faiz(
        Decimal("8000"), Decimal("36"), donem="YILLIK", gun_esasi=360, gun_sayisi=10
    ) == Decimal("80.00")


def test_toplam_180():
    a = basit_gunluk_faiz(Decimal("10000"), Decimal("36"), gun_esasi=360, gun_sayisi=10)
    b = basit_gunluk_faiz(Decimal("8000"), Decimal("36"), gun_esasi=360, gun_sayisi=10)
    assert a + b == Decimal("180.00")
