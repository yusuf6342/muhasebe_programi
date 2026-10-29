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
