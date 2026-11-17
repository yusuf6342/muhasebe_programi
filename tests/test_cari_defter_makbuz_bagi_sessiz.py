"""Fatura-makbuz bağı varken sessiz alacak (çift sayım) üretilmez."""

from decimal import Decimal

from database.cari_bakiye_service import _satis_hareketi_borc_alacak


def test_bagli_makbuz_defterde_kapanan_sessiz_yok():
    """TMK CariIslem + bag.fatura_kapanan ≡ defterde_kapanan → fatura yalnız borç."""
    borc, alacak = _satis_hareketi_borc_alacak(
        Decimal("3670.00"),
        Decimal("0"),
        defterde_kapanan=Decimal("3670.00"),
    )
    assert borc == Decimal("3670.00")
    assert alacak == Decimal("0")


def test_kismi_bagli_makbuz_sessiz_kalan():
    borc, alacak = _satis_hareketi_borc_alacak(
        Decimal("1000.00"),
        Decimal("400.00"),
        defterde_kapanan=Decimal("600.00"),
    )
    assert borc == Decimal("1000.00")
    assert alacak == Decimal("0")
