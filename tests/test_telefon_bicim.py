"""Telefon şablonu: (532) 311 55 33 — baştaki 0 yok."""

from telefon_bicim import telefon_bicimle, telefon_kayit, telefon_rakamlari


def test_ornek_sablon():
    assert telefon_bicimle("5323115533") == "(532) 311 55 33"
    assert telefon_bicimle("05323115533") == "(532) 311 55 33"
    assert telefon_bicimle("(532) 311 55 33") == "(532) 311 55 33"


def test_bastaki_sifir_atilir():
    assert telefon_rakamlari("0532") == "532"
    assert telefon_rakamlari("000532") == "532"
    assert telefon_rakamlari("0") == ""


def test_kismi_yazim():
    assert telefon_bicimle("5") == "(5"
    assert telefon_bicimle("53") == "(53"
    assert telefon_bicimle("532") == "(532)"
    assert telefon_bicimle("5323") == "(532) 3"
    assert telefon_bicimle("532311") == "(532) 311"
    assert telefon_bicimle("53231155") == "(532) 311 55"


def test_azami_on_rakam():
    assert telefon_rakamlari("5323115533999") == "5323115533"
    assert telefon_bicimle("5323115533999") == "(532) 311 55 33"


def test_kayit_bos_none():
    assert telefon_kayit("") is None
    assert telefon_kayit("0") is None
    assert telefon_kayit("5323115533") == "(532) 311 55 33"
