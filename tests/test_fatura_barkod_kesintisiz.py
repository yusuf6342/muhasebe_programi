"""V2 barkod — aynı barkodda miktar artışı, tanımsız biriktirme, denetim."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
    d._barkod_hedef_map = {}
    from collections import deque

    d._barkod_kuyruk = deque()
    return d


def test_barkod_temizle_sifir_ve_alfa_korunur():
    assert barkod_temizle("0001234567890") == "0001234567890"
    assert barkod_temizle(" AB12-34\r\n") == "AB12-34"


def test_ayni_tanimli_barkod_uc_okuma_tek_satir_miktar_3():
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
            _satira_uygula(dialog, kayit, okutulan_barkod="1031109304", birlestir=True)
    assert len(dialog.satirlar) == 1
    assert Decimal(str(dialog.satirlar[0]["miktar"])) == Decimal("3")


def test_ayni_tanimsiz_barkod_uc_okuma_tek_satir():
    dialog = _mock_dialog()
    for _ in range(3):
        _cozulmemis_satir_ekle(dialog, "0001234567890")
    assert len(dialog.satirlar) == 1
    assert dialog.satirlar[0]["urun_adi"] == ""
    assert Decimal(str(dialog.satirlar[0]["miktar"])) == Decimal("3")
    assert satir_cozulmemis_mi(dialog.satirlar[0])


def test_a_b_a_iki_satir():
    dialog = _mock_dialog()
    a = {
        "stok_kodu": "A",
        "stok_adi": "Ürün A",
        "birim": "Adet",
        "birim_fiyat": Decimal("1"),
        "kdv_orani": Decimal("20"),
        "barkod": "111",
        "carpan": Decimal("1"),
        "stok_id": 1,
    }
    b = {
        "stok_kodu": "B",
        "stok_adi": "Ürün B",
        "birim": "Adet",
        "birim_fiyat": Decimal("2"),
        "kdv_orani": Decimal("20"),
        "barkod": "222",
        "carpan": Decimal("1"),
        "stok_id": 2,
    }
    with patch("fatura_barkod_ui._musteri_fiyat", side_effect=lambda d, k, f: f), patch(
        "fatura_barkod_ui.StokService.stoklari_ara", return_value=[]
    ), patch(
        "fatura_barkod_ui.StokService.maliyetler", return_value={}
    ), patch(
        "fatura_satir_birim_service.temel_miktar", side_effect=lambda m, b, k: Decimal(str(m))
    ):
        _satira_uygula(dialog, a, okutulan_barkod="111")
        _satira_uygula(dialog, b, okutulan_barkod="222")
        _satira_uygula(dialog, a, okutulan_barkod="111")
    assert len(dialog.satirlar) == 2
    assert Decimal(str(dialog.satirlar[0]["miktar"])) == Decimal("2")
    assert Decimal(str(dialog.satirlar[1]["miktar"])) == Decimal("1")


def test_farkli_tanimsiz_ayri_kalir():
    dialog = _mock_dialog()
    _cozulmemis_satir_ekle(dialog, "AAA1")
    _cozulmemis_satir_ekle(dialog, "BBB2")
    _cozulmemis_satir_ekle(dialog, "AAA1")
    assert len(dialog.satirlar) == 2
    assert Decimal(str(dialog.satirlar[0]["miktar"])) == Decimal("2")
    assert Decimal(str(dialog.satirlar[1]["miktar"])) == Decimal("1")


def test_yuz_hizli_ayni_barkod_tek_satir():
    dialog = _mock_dialog()

    def _ara(_kod):
        return {
            "durum": "ok",
            "kayit": {
                "stok_kodu": "S1",
                "stok_adi": "Hızlı",
                "birim": "Adet",
                "birim_fiyat": Decimal("1"),
                "kdv_orani": Decimal("20"),
                "barkod": "OK100",
                "carpan": Decimal("1"),
                "stok_id": 1,
            },
            "liste": [],
            "mesaj": "",
        }

    with patch("fatura_barkod_ui.barkod_ile_ara", side_effect=_ara), patch(
        "fatura_barkod_ui._musteri_fiyat", side_effect=lambda d, k, f: f
    ), patch(
        "fatura_barkod_ui.StokService.stoklari_ara", return_value=[]
    ), patch(
        "fatura_barkod_ui.StokService.maliyetler", return_value={}
    ), patch(
        "fatura_urun_aktar_service.urun_kartindan_tanimlayicilar",
        return_value=("OK100", "S1", "Hızlı"),
    ), patch(
        "fatura_urun_aktar_service.urun_secim_seridini_doldur"
    ), patch(
        "fatura_satir_birim_service.temel_miktar", side_effect=lambda m, b, k: Decimal(str(m))
    ), patch(
        "fatura_barkod_ui._ses_basari"
    ), patch(
        "fatura_barkod_ui._odak_sonrasi"
    ), patch(
        "fatura_barkod_ui._DEBOUNCE_MS", 0
    ):
        import time

        base = time.time() * 1000.0
        for i in range(100):
            dialog._barkod_son_okuma = ("", 0.0)
            dialog.barkod_okut_entry.get.return_value = "OK100"
            with patch("fatura_barkod_ui.time.time", return_value=(base + i * 200) / 1000.0):
                fatura_barkod_isle(dialog)
    assert len(dialog.satirlar) == 1
    assert Decimal(str(dialog.satirlar[0]["miktar"])) == Decimal("100")


def test_bos_enter_ve_cift_olay():
    dialog = _mock_dialog()
    dialog.barkod_okut_entry.get.return_value = "   "
    assert fatura_barkod_isle(dialog) == "break"
    assert dialog.satirlar == []

    with patch(
        "fatura_barkod_ui.barkod_ile_ara",
        return_value={"durum": "bulunamadi", "kayit": None, "liste": [], "mesaj": "yok"},
    ), patch("fatura_barkod_ui._ses_hata"), patch("fatura_barkod_ui._odak_sonrasi"):
        dialog.barkod_okut_entry.get.return_value = "DUP1"
        fatura_barkod_isle(dialog)
        dialog.barkod_okut_entry.get.return_value = "DUP1"
        fatura_barkod_isle(dialog)
    assert len(dialog.satirlar) == 1
    assert Decimal(str(dialog.satirlar[0]["miktar"])) == Decimal("1")


def test_stok_uygula_miktar_korunur():
    from fatura_satir_yeni_urun import _stok_kartini_satira_yaz

    dialog = _mock_dialog()
    _cozulmemis_satir_ekle(dialog, "ZZZ99")
    _cozulmemis_satir_ekle(dialog, "ZZZ99")
    _cozulmemis_satir_ekle(dialog, "ZZZ99")
    uid = dialog.satirlar[0]["satir_uid"]
    stok = SimpleNamespace(
        id=55, stok_kodu="YENI1", stok_adi="Yeni Ürün", birim="Adet", kdv_orani=Decimal("20")
    )
    with patch(
        "fatura_urun_aktar_service.stoktan_satir_sablonu",
        return_value={
            "urun_kodu": "YENI1",
            "urun_adi": "Yeni Ürün",
            "birim": "Adet",
            "miktar": "1",
            "birim_satis_fiyati": "45",
            "kdv_orani": "20",
            "barkod": "ZZZ99",
            "iskonto_orani": "0",
            "iskonto_orani_2": "0",
            "iskonto_orani_3": "0",
            "manuel_fiyat": False,
        },
    ), patch("fatura_barkod_ui._barkod_odak"), patch("fatura_barkod_ui._satiri_vurgula"):
        assert _stok_kartini_satira_yaz(
            dialog, hedef_uid=uid, stok=stok, belge_nesil=0, ham_barkod="ZZZ99"
        )
    assert len(dialog.satirlar) == 1
    assert dialog.satirlar[0]["urun_adi"] == "Yeni Ürün"
    assert Decimal(str(dialog.satirlar[0]["miktar"])) == Decimal("3")
    assert not satir_cozulmemis_mi(dialog.satirlar[0])


def test_denetim_ve_nesil():
    dialog = _mock_dialog()
    _cozulmemis_satir_ekle(dialog, "ZZZ1")
    assert cozulmemis_satirlari_denetle(dialog) is not None
    from collections import deque

    dialog._barkod_kuyruk = deque(
        [{"sira_id": 1, "barkod": "ESKI", "nesil": 0, "t0": 0.0, "odak_serit": False}]
    )
    barkod_nesil_artir(dialog)
    assert dialog._barkod_nesil == 1
    assert len(dialog._barkod_kuyruk) == 0
