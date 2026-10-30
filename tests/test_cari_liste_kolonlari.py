"""Cari liste kolon kataloğu ve satır haritası."""

from decimal import Decimal
from types import SimpleNamespace

from cari_liste_ui import (
    CARI_LISTE_KOLONLARI,
    CARI_LISTE_ZORUNLU,
    cari_liste_varsayilan_ayarlari,
    gorunur_kolonlar,
    satir_deger_haritasi,
)


def test_kolon_katalogu_zorunlu_ve_varsayilan():
    anahtarlar = [k for k, _, _, _ in CARI_LISTE_KOLONLARI]
    assert "kod" in anahtarlar and "unvan" in anahtarlar
    assert CARI_LISTE_ZORUNLU <= set(anahtarlar)
    ayar = cari_liste_varsayilan_ayarlari()
    assert set(ayar["sira"]) == set(anahtarlar)
    gorunen = gorunur_kolonlar(ayar)
    assert "kod" in gorunen and "unvan" in gorunen
    assert "bakiye" in gorunen
    # Kart alanları katalogda var; varsayılan çoğu gizli
    assert "vergi_numarasi" in anahtarlar
    assert "vergi_numarasi" not in gorunen
    assert "muhasebe_borclu_kodu" in anahtarlar


def test_satir_deger_haritasi_tum_kolonlar():
    cari = SimpleNamespace(
        cari_kodu="M001",
        unvan="Örnek A.Ş.",
        cari_turu="Müşteri",
        ana_kart_turu_id=1,
        musteri_alt_tur_id=2,
        tedarikci_alt_tur_id=None,
        vergi_dairesi="Kadıköy",
        vergi_numarasi="123",
        tc_kimlik=None,
        telefon="555",
        telefon2=None,
        telefon3=None,
        email="a@b.c",
        musteri_grubu="",
        adres_tipi="Fatura",
        adres="Uzun adres " * 20,
        il="İstanbul",
        ilce="Kadıköy",
        adres_tipi2=None,
        adres2=None,
        il2=None,
        ilce2=None,
        adres_tipi3=None,
        adres3=None,
        il3=None,
        ilce3=None,
        satis_fiyat_listesi="Liste1",
        alis_fiyat_listesi=None,
        satis_vade_gunu=30,
        alis_vade_gunu=None,
        acik_hesap_risk_limiti=Decimal("1000"),
        acik_hesap_limit_uygula=True,
        cek_risk_limiti=None,
        cek_limit_uygula=False,
        senet_risk_limiti=None,
        senet_limit_uygula=False,
        toplam_risk_limiti=None,
        toplam_limit_uygula=False,
        risk_orani_ciro_cek=Decimal("100"),
        risk_orani_diger_cek=Decimal("100"),
        risk_orani_senet=Decimal("100"),
        vade_farki_aylik_oran=None,
        vade_farki_yillik_oran=None,
        vade_farki_donem=None,
        vade_farki_aciklama=None,
        muhasebe_borclu_kodu="120",
        muhasebe_alacakli_kodu=None,
        muhasebe_satis_kodu=None,
        muhasebe_alis_kodu=None,
        muhasebe_kdv_satis_kodu=None,
        muhasebe_kdv_alis_kodu=None,
        ozel_notlar="not",
        uyari_notu=None,
        aktif=True,
    )
    ozet = {
        "cari": cari,
        "bakiye": Decimal("250.5"),
        "toplam_borc": Decimal("250.5"),
        "toplam_alacak": Decimal("0"),
        "agirlikli_ortalama_gun": 12,
        "odenen_ortalama_valor_gun": None,
        "ana_yetkili": "Ali",
        "yetkili_telefon": "532",
        "yaklasan_dogum": "",
    }
    harita = satir_deger_haritasi(
        ozet,
        ana_tur_adlari={1: "Perakende"},
        alt_tur_adlari={2: "Bayi"},
    )
    for anahtar, _, _, _ in CARI_LISTE_KOLONLARI:
        assert anahtar in harita, anahtar
    assert harita["kod"] == "M001"
    assert harita["ana_tur"] == "Perakende"
    assert harita["musteri_alt_tur"] == "Bayi"
    assert harita["grup"] == "Grup Atanmamış"
    assert harita["acik_hesap_limit_uygula"] == "Evet"
    assert harita["agirlikli"] == "12 gün"
    assert harita["kapatilan_gun"] == ""
    assert "…" in harita["adres"] or len(harita["adres"]) <= 100
