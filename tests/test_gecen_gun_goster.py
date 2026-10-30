"""Müşteri listesi — Valör gün görüntüsü (birim + boş/sıfır ayrımı)."""

from cari_liste_ui import gecen_gun_goster, gecen_gun_sayi


def test_gecen_gun_tam_sayi():
    assert gecen_gun_goster(38) == "38 gün"
    assert gecen_gun_goster(0) == "0 gün"
    assert gecen_gun_goster(-5) == "-5 gün"


def test_gecen_gun_ondalik():
    assert gecen_gun_goster(38.2) == "38,2 gün"
    assert gecen_gun_goster(33.49) == "33,5 gün"
    assert gecen_gun_goster("18,70") == "18,7 gün"


def test_gecen_gun_bos_null():
    """Hesaplanamayan / boş → sahte 0 gün üretilmez."""
    assert gecen_gun_goster(None) == ""
    assert gecen_gun_goster("") == ""
    assert gecen_gun_goster("  ") == ""
    assert gecen_gun_sayi(None) is None


def test_gecen_gun_ham_deger_korunur():
    """Sıralama için sayısal ham değer; görüntü birimli metin."""
    assert gecen_gun_sayi(33.49) == 33.49
    assert gecen_gun_sayi("33,50") == 33.5
    assert gecen_gun_sayi("38 gün") == 38.0
    assert "gün" in gecen_gun_goster(33.49)
