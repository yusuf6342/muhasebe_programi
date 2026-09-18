"""Birim dönüştürücü: zincir → temel miktar + Decimal."""

from decimal import Decimal

from database.stok_service import StokService, _birim_kayit_normalize


def test_temel_miktar_koli_paket_torba():
    ana = "Adet"
    birimler = [
        _birim_kayit_normalize(
            {"birim_adi": "Küçük Torba", "carpan": "100", "referans_birim": "Adet", "referans_carpan": "100"},
            ana,
        ),
        _birim_kayit_normalize(
            {
                "birim_adi": "Paket",
                "carpan": "1000",
                "referans_birim": "Küçük Torba",
                "referans_carpan": "10",
            },
            ana,
        ),
        _birim_kayit_normalize(
            {"birim_adi": "Koli", "carpan": "24000", "referans_birim": "Paket", "referans_carpan": "24"},
            ana,
        ),
    ]
    assert StokService.temel_miktara_cevir(2, "Koli", birimler, ana) == Decimal("48000.000000")
    assert StokService.temel_miktara_cevir(3, "Paket", birimler, ana) == Decimal("3000.000000")
    assert StokService.temel_miktara_cevir(5, "Küçük Torba", birimler, ana) == Decimal("500.000000")


def test_onizleme_hedef():
    birimler = [
        {"birim_adi": "Paket", "carpan": "1000"},
        {"birim_adi": "Koli", "carpan": "24000"},
    ]
    o = StokService.birim_donusum_onizleme(2, "Koli", "Paket", birimler, "Adet")
    assert o["temel_miktar"] == Decimal("48000.000000")
    assert o["hedef_miktar"] == Decimal("48.000000")


def test_eski_tuple_normalize():
    d = _birim_kayit_normalize(("Paket", "1000"), "Adet")
    assert d["birim_adi"] == "Paket"
    assert d["carpan"] == "1000"
