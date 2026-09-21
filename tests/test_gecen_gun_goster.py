"""Müşteri kartları listesi — Geçen Gün görüntü yuvarlaması."""

from cari_liste_ui import gecen_gun_goster, gecen_gun_sayi


def test_gecen_gun_sinir_degerleri():
    assert gecen_gun_goster(33.49) == "33"
    assert gecen_gun_goster(33.50) == "34"
    assert gecen_gun_goster(33.51) == "34"


def test_gecen_gun_ornekler():
    assert gecen_gun_goster(33.50) == "34"
    assert gecen_gun_goster(33.30) == "33"
    assert gecen_gun_goster(18.70) == "19"
    assert gecen_gun_goster(18.49) == "18"
    assert gecen_gun_goster(0.50) == "1"
    assert gecen_gun_goster(0) == "0"
    assert gecen_gun_goster(0.49) == "0"


def test_gecen_gun_virgullu_metin():
    assert gecen_gun_goster("33,50") == "34"
    assert gecen_gun_goster("33,49") == "33"
    assert gecen_gun_goster("18,70") == "19"


def test_gecen_gun_bos_null():
    assert gecen_gun_goster(None) == "0"
    assert gecen_gun_goster("") == "0"
    assert gecen_gun_goster("  ") == "0"
    assert gecen_gun_sayi(None) == 0.0


def test_gecen_gun_ham_deger_korunur():
    """Sıralama için küsuratlı ham değer ayrı tutulur."""
    assert gecen_gun_sayi(33.49) == 33.49
    assert gecen_gun_sayi("33,50") == 33.5
    assert gecen_gun_goster(33.49) == "33"  # görüntü farklı
