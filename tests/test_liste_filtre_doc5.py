"""DOC5: kayıtlı görünüm + istatistik + grup ağacı yardımcıları."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import liste_filtre_ui as lfu


def test_kayitli_gorunum_save_load_sil(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    rapor = "test_rapor_doc5"
    durum = {
        "filtreler": {"arama": "abc", "bas": "01.01.2026"},
        "kolon_filtre": {"satirlar": {"cari": {"A", "B"}}},
        "siralama": {"satirlar": ["tarih", False]},
        "kolon_genislik": {"satirlar": {"cari": 120}},
    }
    lfu.kayitli_gorunum_kaydet(rapor, "Benim görünüm", durum)
    yol: Path = lfu.kayitli_gorunum_dosyasi(rapor)
    assert yol.exists()
    ham = json.loads(yol.read_text(encoding="utf-8"))
    assert ham["rapor"] == rapor
    assert "gorunumler" in ham
    # Firma sızıntısı yok: dosya adı firma+kullanıcı içerir
    assert "_f" in yol.name and "_u" in yol.name

    yuklenen = lfu.kayitli_gorunum_yukle(rapor, "Benim görünüm")
    assert yuklenen is not None
    assert yuklenen["filtreler"]["arama"] == "abc"
    assert yuklenen["kolon_filtre"]["satirlar"]["cari"] == {"A", "B"}

    assert "Benim görünüm" in lfu.kayitli_gorunum_listele(rapor)
    assert lfu.kayitli_gorunum_sil(rapor, "Benim görünüm") is True
    assert lfu.kayitli_gorunum_yukle(rapor, "Benim görünüm") is None
    assert lfu.kayitli_gorunum_listele(rapor) == []


def test_kayitli_gorunum_firma_ayri(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    class _O:
        company_id = 11
        user_id = 22
        firma_kodu = None
        kullanici_adi = None

    monkeypatch.setattr(lfu, "_ayar_kimlik", lambda: ("11", "22"))
    lfu.kayitli_gorunum_kaydet("r1", "v1", {"filtreler": {"x": 1}})
    yol_a = lfu.kayitli_gorunum_dosyasi("r1")

    monkeypatch.setattr(lfu, "_ayar_kimlik", lambda: ("99", "22"))
    yol_b = lfu.kayitli_gorunum_dosyasi("r1")
    assert yol_a != yol_b
    assert lfu.kayitli_gorunum_listele("r1") == []  # farklı firma dosyası boş


def test_istatistik_hesapla_ve_bakiye_haric():
    degerler = [Decimal("100"), Decimal("50"), Decimal("25"), None, ""]
    assert lfu.istatistik_hesapla(degerler, lfu.IST_TOPLAM) == Decimal("175")
    assert lfu.istatistik_hesapla(degerler, lfu.IST_MAKS) == Decimal("100")
    assert lfu.istatistik_hesapla(degerler, lfu.IST_MIN) == Decimal("25")
    assert lfu.istatistik_hesapla(degerler, lfu.IST_ORTALAMA) == Decimal("175") / Decimal("3")
    assert lfu.istatistik_hesapla(degerler, lfu.IST_SATIR, satir_sayisi=5) == 5
    assert lfu.istatistik_hesapla([], lfu.IST_TOPLAM) == Decimal("0")
    assert lfu.istatistik_hesapla([], lfu.IST_MAKS) is None
    assert lfu.istatistik_metni(None, lfu.IST_ORTALAMA) == "Veri yok"

    assert lfu.kolon_istatistik_uygun_mu("bakiye", tip="para") is False
    assert lfu.kolon_istatistik_uygun_mu("tl_bakiye", tip="para") is False
    assert lfu.kolon_istatistik_uygun_mu("fifo_kalan", tip="miktar") is False
    assert lfu.kolon_istatistik_uygun_mu("borc", tip="para") is True
    assert lfu.kolon_varsayilan_istatistik("borc", "para") == lfu.IST_TOPLAM
    assert lfu.kolon_varsayilan_istatistik("birim_fiyat", "fiyat") is None


def test_grup_alt_idler_parent_includes_children():
    agac = [
        {
            "id": 1,
            "ad": "Ana",
            "cocuklar": [
                {
                    "id": 2,
                    "ad": "Tali",
                    "cocuklar": [{"id": 3, "ad": "Alt", "cocuklar": []}],
                }
            ],
        },
        {"id": 10, "ad": "Diğer", "cocuklar": []},
    ]
    assert lfu.grup_alt_idler(agac, {1}) == {1, 2, 3}
    assert lfu.grup_alt_idler(agac, {2}) == {2, 3}
    assert lfu.grup_alt_idler(agac, {3}) == {3}
    assert lfu.grup_alt_idler(agac, {1, 10}) == {1, 2, 3, 10}
    assert lfu.grup_alt_idler(agac, set()) == set()


def test_kimlik_kolonlari_sec():
    kolonlar = ["kod", "ad", "miktar", "tutar", "bakiye"]
    tip = {"kod": "metin", "ad": "metin", "miktar": "miktar", "tutar": "para", "bakiye": "para"}
    assert lfu.kimlik_kolonlari_sec(kolonlar, tip_map=tip, en_fazla=2) == ["kod", "ad"]


def test_grafik_verisi_filtrelenmis_istatistik_ile_eslesir():
    """Grafik çubuk değerleri = istatistik_hesapla(filtrelenmiş satırlar); bakiye hariç."""
    ham = [
        {"borc": Decimal("100"), "alacak": Decimal("10"), "bakiye": Decimal("500"), "_sabit": False},
        {"borc": Decimal("50"), "alacak": Decimal("40"), "bakiye": Decimal("510"), "_sabit": False},
        {"borc": Decimal("25"), "alacak": Decimal("5"), "bakiye": Decimal("530"), "_sabit": False},
        {"borc": Decimal("999"), "alacak": Decimal("999"), "bakiye": Decimal("0"), "_sabit": True},
    ]
    # Filtre: yalnız borc >= 50 (görünür küme)
    filtreli = [r for r in ham if not r.get("_sabit") and r["borc"] >= Decimal("50")]
    assert len(filtreli) == 2

    secimler = {
        "borc": lfu.IST_TOPLAM,
        "alacak": lfu.IST_MAKS,
        "bakiye": lfu.IST_TOPLAM,  # yürüyen — grafiğe girmemeli
    }
    seriler = lfu.grafik_verisi_hazirla(
        filtreli,
        secimler,
        basliklar={"borc": "Borç", "alacak": "Alacak", "bakiye": "Bakiye"},
        kolon_tip={"borc": "para", "alacak": "para", "bakiye": "para"},
    )
    # Alias
    assert lfu.grafik_verisi_olustur is lfu.grafik_verisi_hazirla

    anahtarlar = {s["kolon"] for s in seriler}
    assert "bakiye" not in anahtarlar
    assert anahtarlar == {"borc", "alacak"}

    by_kolon = {s["kolon"]: s for s in seriler}
    borc_degerler = [r["borc"] for r in filtreli]
    alacak_degerler = [r["alacak"] for r in filtreli]
    assert by_kolon["borc"]["deger"] == lfu.istatistik_hesapla(
        borc_degerler, lfu.IST_TOPLAM, satir_sayisi=len(filtreli)
    )
    assert by_kolon["alacak"]["deger"] == lfu.istatistik_hesapla(
        alacak_degerler, lfu.IST_MAKS, satir_sayisi=len(filtreli)
    )
    # Ham (filtresiz) toplam ile karışmamalı
    assert by_kolon["borc"]["deger"] != lfu.istatistik_hesapla(
        [r["borc"] for r in ham if not r.get("_sabit")], lfu.IST_TOPLAM
    )


def test_grafik_verisi_satir_ve_bos():
    satirlar = [{"miktar": Decimal("2")}, {"miktar": Decimal("8")}]
    seriler = lfu.grafik_verisi_hazirla(
        satirlar,
        {"miktar": lfu.IST_SATIR, "oran": lfu.IST_ORTALAMA},
        basliklar={"miktar": "Miktar", "oran": "Oran"},
        kolon_tip={"miktar": "miktar", "oran": "oran"},
    )
    assert len(seriler) == 1
    assert seriler[0]["tur"] == lfu.IST_SATIR
    assert seriler[0]["deger"] == 2

    assert lfu.grafik_verisi_hazirla([], {"borc": lfu.IST_MAKS}) == []
    assert lfu.grafik_verisi_hazirla(
        [{"borc": Decimal("1")}], {"borc": None}
    ) == []


def test_grafik_verisi_filtrelenmis_istatistikle_ayni():
    satirlar = [
        {"borc": Decimal("100"), "bakiye": Decimal("500")},
        {"borc": Decimal("50"), "bakiye": Decimal("450")},
        {"borc": Decimal("25"), "bakiye": Decimal("425")},
    ]
    # Bakiye seçilse bile yürüyen kolon grafiğe girmez
    seriler = lfu.grafik_verisi_hazirla(
        satirlar,
        {"borc": lfu.IST_TOPLAM, "bakiye": lfu.IST_TOPLAM},
        basliklar={"borc": "Borç", "bakiye": "Bakiye"},
    )
    assert len(seriler) == 1
    assert seriler[0]["kolon"] == "borc"
    assert seriler[0]["deger"] == Decimal("175")
    assert seriler[0]["deger"] == lfu.istatistik_hesapla(
        [s["borc"] for s in satirlar], lfu.IST_TOPLAM
    )


def test_satir_gruplari_olustur_iki_duzey_ve_sabit():
    satirlar = [
        {"cari": "A", "urun": "X", "tutar": 10},
        {"cari": "A", "urun": "Y", "tutar": 20},
        {"cari": "B", "urun": "X", "tutar": 30},
        {"cari": "TOPLAM", "tutar": 60, "_sabit": True},
    ]
    g0 = lfu.satir_gruplari_olustur(satirlar, [])
    assert len(g0) == 4
    assert not any(r.get("_grup") for r in g0)

    g1 = lfu.satir_gruplari_olustur(satirlar, ["cari"])
    gruplar = [r for r in g1 if r.get("_grup")]
    assert len(gruplar) == 2
    assert {r["_grup_deger"] for r in gruplar} == {"A", "B"}
    assert gruplar[0]["_grup_adet"] == 2
    assert g1[-1].get("_sabit") and not g1[-1].get("_grup")

    g2 = lfu.satir_gruplari_olustur(satirlar, ["cari", "urun", "fazla"])
    # en fazla 2 düzey
    seviye = {r.get("_grup_seviye") for r in g2 if r.get("_grup")}
    assert seviye == {0, 1}
    assert sum(1 for r in g2 if not r.get("_grup") and not r.get("_sabit")) == 3
