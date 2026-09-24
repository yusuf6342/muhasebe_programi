"""Fatura miktar gösterimi: tam sayı / 2 ondalık."""

from decimal import Decimal

from app import miktar_goster
from invoice_print.builder import _miktar


def test_tam_sayi_ondaliksiz():
    assert miktar_goster(Decimal("7")) == "7"
    assert miktar_goster(Decimal("7.000000")) == "7"
    assert miktar_goster(Decimal("1000.00")) == "1000"
    assert miktar_goster(7) == "7"
    assert miktar_goster("50.0000") == "50"


def test_ondalikli_iki_hane():
    assert miktar_goster(Decimal("12.5")) == "12,50"
    assert miktar_goster(Decimal("12.345")) == "12,35"
    assert miktar_goster(Decimal("0.1")) == "0,10"


def test_print_miktar_ayni_kural():
    assert _miktar(Decimal("7.000000")) == "7"
    assert _miktar(Decimal("1.5")) == "1,50"
