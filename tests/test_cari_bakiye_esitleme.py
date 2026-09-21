"""Müşteri listesi ve fatura Eski/Yeni bakiye eşitleme testleri."""

from decimal import Decimal
from datetime import date, timedelta

from database.cari_bakiye_service import fatura_eski_yeni_bakiye, net_bakiye


def test_net_bakiye_sifir_musteri_yoksa():
    """Hareketi olmayan / var olmayan id → 0 (DB boş olabilir)."""
    # Çok büyük id — hareket yok varsayımı
    ozet = net_bakiye(999_999_999)
    assert ozet["bakiye"] == Decimal("0.00")
    assert ozet["eski_bakiye"] == Decimal("0.00")
    assert ozet["yeni_bakiye"] == Decimal("0.00")
    assert ozet["hareket_sayisi"] == 0


def test_yeni_bakiye_eski_arti_etki():
    ozet = fatura_eski_yeni_bakiye(
        999_999_999,
        fatura_tarihi=date.today(),
        belge_etkisi=Decimal("150.50"),
    )
    assert ozet["eski_bakiye"] == Decimal("0.00")
    assert ozet["yeni_bakiye"] == Decimal("150.50")
    assert ozet["eklenecek"] == Decimal("150.50")


def test_gecmis_tarih_strict_before():
    """Geçmiş tarihli faturada as_of strict_before True olmalı."""
    ozet = fatura_eski_yeni_bakiye(
        999_999_999,
        fatura_tarihi=date.today() - timedelta(days=30),
        belge_etkisi=Decimal("10"),
    )
    assert ozet["strict_before"] is True
    assert ozet["as_of"] == date.today() - timedelta(days=30)
    assert ozet["yeni_bakiye"] == ozet["eski_bakiye"] + Decimal("10.00")


def test_bugun_liste_ile_ayni_kaynak():
    """Bugünkü taslak: as_of None → liste bakiyesi formülü."""
    ozet = fatura_eski_yeni_bakiye(
        999_999_999,
        fatura_tarihi=date.today(),
        belge_etkisi=Decimal("0"),
    )
    assert ozet["strict_before"] is False
    assert ozet["as_of"] is None
    liste = net_bakiye(999_999_999)
    assert ozet["eski_bakiye"] == liste["bakiye"]


def test_satis_bakiye_ozeti_merkezi_servis():
    from database.satis_faturasi_service import SatisFaturasiService

    o = SatisFaturasiService.bakiye_ozeti(999_999_999, Decimal("25.00"), date.today(), None)
    assert o["eski_bakiye"] == Decimal("0.00")
    assert o["bakiye"] == Decimal("25.00")
