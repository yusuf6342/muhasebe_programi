"""Alış (negatif SH) sessiz borc üretmez — ödeme CariIslem ile netlenir."""

from decimal import Decimal

from database.cari_bakiye_service import _satis_hareketi_borc_alacak


def test_alis_tam_acik_sessiz_yok():
    borc, alacak = _satis_hareketi_borc_alacak(Decimal("-12562.00"), Decimal("-12562.00"))
    assert borc == Decimal("0")
    assert alacak == Decimal("12562.00")


def test_alis_kalan_sifir_sessiz_yok_cift_sayim_engeli():
    """Kalan=0 (kapatma eksik/fazla düşülmüş) olsa da sessiz borc yok."""
    borc, alacak = _satis_hareketi_borc_alacak(
        Decimal("-12562.00"),
        Decimal("0"),
        defterde_kapanan=Decimal("4725.00"),
    )
    assert borc == Decimal("0")
    assert alacak == Decimal("12562.00")


def test_alis_kismi_acik_sessiz_yok():
    borc, alacak = _satis_hareketi_borc_alacak(Decimal("-5425.00"), Decimal("-1752.00"))
    assert borc == Decimal("0")
    assert alacak == Decimal("5425.00")


def test_satis_pozitif_sessiz_alacak_korunur():
    """Müşteri satışı: kapanan defterde yoksa sessiz alacak (eski davranış)."""
    borc, alacak = _satis_hareketi_borc_alacak(Decimal("250.32"), Decimal("0"))
    assert borc == Decimal("250.32")
    assert alacak == Decimal("250.32")


def test_satis_defterde_kapanan_sessiz_dusulur():
    borc, alacak = _satis_hareketi_borc_alacak(
        Decimal("250.32"),
        Decimal("0"),
        defterde_kapanan=Decimal("250.32"),
    )
    assert borc == Decimal("250.32")
    assert alacak == Decimal("0")
