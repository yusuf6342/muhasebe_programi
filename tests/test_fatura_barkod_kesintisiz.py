"""Kesintisiz fatura barkod okutma — tanımsız satır, sıra, birleştirme yok, denetim."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from database.barkod_okut_service import barkod_temizle
from fatura_barkod_ui import (
    _cozulmemis_satir_ekle,
    _satira_uygula,
    barkod_nesil_artir,
    cozulmemis_satirlari_denetle,
    fatura_barkod_isle,
    satir_cozulmemis_mi,
)


def _mock_dialog(satirlar=None, depo="ANA DEPO"):
    d = MagicMock()
    d.satirlar = list(satirlar or [])
    d.depo = SimpleNamespace(get=lambda: depo)
    d._doviz_para_birimi = SimpleNamespace(get=lambda: "TRY")
    d._fatura_satirlari_hazir = False
    d._duzenlenen_satir = None
    d.satir_tablosu = None
    d.barkod_okut_entry = MagicMock()
    d.barkod_okut_entry.get.return_value = ""
    d.satir_girdileri = {}
    d._satir_listesini_yenile = MagicMock()
    d._toplamlari_guncelle = MagicMock()
    d.after = MagicMock()
    d.after_idle = MagicMock()
    d.focus_get = MagicMock(return_value=None)
    d._fatura_kilitli = False
    d._barkod_isleniyor = False
    d._barkod_son_okuma = ("", 0.0)
    d._barkod_sira = 0
    d._barkod_nesil = 0
    d._barkod_odak_serit = True
    from collections import deque

    d._barkod_kuyruk = deque()
    return d


def test_barkod_temizle_sifir_ve_alfa_korunur():
    assert barkod_temizle("0001234567890") == "0001234567890"
    assert barkod_temizle(" AB12-34\r\n") == "AB12-34"
    assert barkod_temizle("") == ""


def test_tanimsiz_barkod_bos_ad_miktar_1():
    dialog = _mock_dialog()
    idx = _cozulmemis_satir_ekle(dialog, "0001234567890", neden="Eşleşme yok")
    assert idx == 0
    assert len(dialog.satirlar) == 1
    s = dialog.satirlar[0]
    assert s["barkod"] == "0001234567890"
    assert s["urun_kodu"] == "0001234567890"
    assert s["urun_adi"] == ""
    assert str(s["miktar"]) == "1"
    assert satir_cozulmemis_mi(s)
    assert "Bulunamadı" not in (s["urun_adi"] or "")
    assert s.get("stok_id") is None


def test_ayni_barkod_uc_okuma_uc_satir():
    dialog = _mock_dialog()
    kayit = {
        "stok_kodu": "X1",
        "stok_adi": "Test Ürün",
        "birim": "Adet",
        "birim_fiyat": Decimal("10"),
        "kdv_orani": Decimal("20"),
        "barkod": "1031109304",
        "carpan": Decimal("1"),
        "stok_id": 7,
    }
    with patch("fatura_barkod_ui._musteri_fiyat", return_value=Decimal("10")), patch(
        "fatura_barkod_ui.StokService.stoklari_ara", return_value=[]
    ), patch(
        "fatura_barkod_ui.StokService.maliyetler", return_value={}
    ), patch(
        "fatura_satir_birim_service.temel_miktar", side_effect=lambda m, b, k: Decimal(str(m))
    ):
        for _ in range(3):
            _satira_uygula(dialog, kayit, okutulan_barkod="1031109304", birlestir=False)
    assert len(dialog.satirlar) == 3
    assert all(str(s["miktar"]) == "1" for s in dialog.satirlar)


def test_tanimsiz_tekrar_ayri_satir():
    dialog = _mock_dialog()
    _cozulmemis_satir_ekle(dialog, "XYZ999")
    _cozulmemis_satir_ekle(dialog, "XYZ999")
    assert len(dialog.satirlar) == 2
    assert all(s["urun_adi"] == "" for s in dialog.satirlar)


def test_bos_enter_satir_uretmez():
    dialog = _mock_dialog()
    dialog.barkod_okut_entry.get.return_value = "   "
    assert fatura_barkod_isle(dialog) == "break"
    assert dialog.satirlar == []


def test_karisik_okuma_sirasi_ve_adet():
    """Tanımlı → tanımsız → tanımlı: 3 satır, sıra korunur."""
    dialog = _mock_dialog()

    def _ara(kod):
        if kod == "A111":
            return {
                "durum": "ok",
                "kayit": {
                    "stok_kodu": "SA",
                    "stok_adi": "Ürün A",
                    "birim": "Adet",
                    "birim_fiyat": Decimal("5"),
                    "kdv_orani": Decimal("20"),
                    "barkod": "A111",
                    "carpan": Decimal("1"),
                    "stok_id": 1,
                },
                "liste": [],
                "mesaj": "",
            }
        if kod == "B222":
            return {
                "durum": "ok",
                "kayit": {
                    "stok_kodu": "SB",
                    "stok_adi": "Ürün B",
                    "birim": "Adet",
                    "birim_fiyat": Decimal("8"),
                    "kdv_orani": Decimal("20"),
                    "barkod": "B222",
                    "carpan": Decimal("1"),
                    "stok_id": 2,
                },
                "liste": [],
                "mesaj": "",
            }
        return {"durum": "bulunamadi", "kayit": None, "liste": [], "mesaj": "yok"}

    def _tanim(*, product_id=None, stok_kodu="", okutulan_barkod=""):
        if stok_kodu == "SA":
            return (okutulan_barkod or "A111", "SA", "Ürün A")
        if stok_kodu == "SB":
            return (okutulan_barkod or "B222", "SB", "Ürün B")
        return (okutulan_barkod, stok_kodu, "")

    with patch("fatura_barkod_ui.barkod_ile_ara", side_effect=_ara), patch(
        "fatura_barkod_ui._musteri_fiyat", side_effect=lambda d, k, f: f
    ), patch(
        "fatura_barkod_ui.StokService.stoklari_ara", return_value=[]
    ), patch(
        "fatura_barkod_ui.StokService.maliyetler", return_value={}
    ), patch(
        "fatura_urun_aktar_service.urun_kartindan_tanimlayicilar", side_effect=_tanim
    ), patch(
        "fatura_urun_aktar_service.urun_secim_seridini_doldur"
    ), patch(
        "fatura_satir_birim_service.temel_miktar", side_effect=lambda m, b, k: Decimal(str(m))
    ), patch(
        "fatura_barkod_ui._ses_basari"
    ), patch(
        "fatura_barkod_ui._ses_hata"
    ), patch(
        "fatura_barkod_ui._odak_sonrasi"
    ):
        for kod in ("A111", "0009998887776", "B222"):
            dialog.barkod_okut_entry.get.return_value = kod
            fatura_barkod_isle(dialog)

    assert len(dialog.satirlar) == 3
    assert dialog.satirlar[0]["urun_adi"] == "Ürün A"
    assert dialog.satirlar[1]["urun_adi"] == ""
    assert dialog.satirlar[1]["barkod"] == "0009998887776"
    assert dialog.satirlar[2]["urun_adi"] == "Ürün B"


def test_yuz_okuma_sirasi_kaybolmaz():
    dialog = _mock_dialog()
    sayac = {"n": 0}

    def _ara(kod):
        sayac["n"] += 1
        if kod.startswith("OK"):
            return {
                "durum": "ok",
                "kayit": {
                    "stok_kodu": f"S{kod}",
                    "stok_adi": f"Ad {kod}",
                    "birim": "Adet",
                    "birim_fiyat": Decimal("1"),
                    "kdv_orani": Decimal("20"),
                    "barkod": kod,
                    "carpan": Decimal("1"),
                    "stok_id": sayac["n"],
                },
                "liste": [],
                "mesaj": "",
            }
        return {"durum": "bulunamadi", "kayit": None, "liste": [], "mesaj": "yok"}

    beklenen = []
    for i in range(100):
        if i % 3 == 0:
            beklenen.append(("OK%04d" % i, True))
        else:
            beklenen.append(("NO%04d" % i, False))

    def _tanim(*, product_id=None, stok_kodu="", okutulan_barkod=""):
        return (okutulan_barkod or stok_kodu, stok_kodu, f"Ad {okutulan_barkod or stok_kodu}")

    with patch("fatura_barkod_ui.barkod_ile_ara", side_effect=_ara), patch(
        "fatura_barkod_ui._musteri_fiyat", side_effect=lambda d, k, f: f
    ), patch(
        "fatura_barkod_ui.StokService.stoklari_ara", return_value=[]
    ), patch(
        "fatura_barkod_ui.StokService.maliyetler", return_value={}
    ), patch(
        "fatura_urun_aktar_service.urun_kartindan_tanimlayicilar", side_effect=_tanim
    ), patch(
        "fatura_urun_aktar_service.urun_secim_seridini_doldur"
    ), patch(
        "fatura_satir_birim_service.temel_miktar", side_effect=lambda m, b, k: Decimal(str(m))
    ), patch(
        "fatura_barkod_ui._ses_basari"
    ), patch(
        "fatura_barkod_ui._ses_hata"
    ), patch(
        "fatura_barkod_ui._odak_sonrasi"
    ), patch(
        "fatura_barkod_ui._DEBOUNCE_MS", 0
    ):
        import time

        # Debounce aynı kodu engellemesin diye zamanı ilerlet
        base = time.time() * 1000.0
        for i, (kod, _) in enumerate(beklenen):
            dialog._barkod_son_okuma = ("", 0.0)
            dialog.barkod_okut_entry.get.return_value = kod
            with patch("fatura_barkod_ui.time.time", return_value=(base + i * 200) / 1000.0):
                fatura_barkod_isle(dialog)

    assert len(dialog.satirlar) == 100
    for i, (kod, tanimli) in enumerate(beklenen):
        s = dialog.satirlar[i]
        assert s["barkod"] == kod or s["urun_kodu"] == kod
        if tanimli:
            assert s["urun_adi"] == f"Ad {kod}"
            assert not satir_cozulmemis_mi(s)
        else:
            assert s["urun_adi"] == ""
            assert satir_cozulmemis_mi(s)


def test_coklu_eslesme_dialog_acmaz_bos_ad():
    dialog = _mock_dialog()
    with patch(
        "fatura_barkod_ui.barkod_ile_ara",
        return_value={
            "durum": "coklu",
            "kayit": None,
            "liste": [{"stok_kodu": "A"}, {"stok_kodu": "B"}],
            "mesaj": "çoklu",
        },
    ), patch("fatura_barkod_ui._coklu_sec") as sec, patch(
        "fatura_barkod_ui._ses_hata"
    ), patch(
        "fatura_barkod_ui._odak_sonrasi"
    ):
        dialog.barkod_okut_entry.get.return_value = "MULTI1"
        fatura_barkod_isle(dialog)
        sec.assert_not_called()
    assert len(dialog.satirlar) == 1
    assert dialog.satirlar[0]["urun_adi"] == ""
    assert "Birden fazla" in (dialog.satirlar[0].get("cozulmemis_neden") or "")


def test_denetim_cozulmemis_engeller():
    dialog = _mock_dialog()
    _cozulmemis_satir_ekle(dialog, "ZZZ1")
    mesaj = cozulmemis_satirlari_denetle(dialog)
    assert mesaj is not None
    assert "ZZZ1" in mesaj


def test_nesil_eski_kuyruk_uygulanmaz():
    dialog = _mock_dialog()
    dialog._barkod_nesil = 0
    from collections import deque

    dialog._barkod_kuyruk = deque(
        [{"sira_id": 1, "barkod": "ESKI", "nesil": 0, "t0": 0.0, "odak_serit": False}]
    )
    barkod_nesil_artir(dialog)
    assert dialog._barkod_nesil == 1
    assert len(dialog._barkod_kuyruk) == 0


def test_cift_olay_debounce_tek_satir():
    dialog = _mock_dialog()
    with patch(
        "fatura_barkod_ui.barkod_ile_ara",
        return_value={"durum": "bulunamadi", "kayit": None, "liste": [], "mesaj": "yok"},
    ), patch("fatura_barkod_ui._ses_hata"), patch("fatura_barkod_ui._odak_sonrasi"):
        dialog.barkod_okut_entry.get.return_value = "DUP1"
        fatura_barkod_isle(dialog)
        dialog.barkod_okut_entry.get.return_value = "DUP1"
        fatura_barkod_isle(dialog)  # aynı ms penceresi
    assert len(dialog.satirlar) == 1
