"""Barkod okutma — stok yetersizken miktar artar; kontrol yalnızca onayda."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from fatura_satir_birim_service import miktar_metnini_coz


def test_miktar_barkod_benzeri_reddedilir():
    with pytest.raises(ValueError, match="barkod"):
        miktar_metnini_coz("1031109304")
    with pytest.raises(ValueError, match="barkod"):
        miktar_metnini_coz("12345678")


def test_miktar_kisa_sayi_kabul():
    assert miktar_metnini_coz("5") == Decimal("5.000000")
    assert miktar_metnini_coz("1,5") == Decimal("1.500000")
    assert miktar_metnini_coz("12.25") == Decimal("12.250000")


def _mock_dialog(satirlar=None, depo="ANA DEPO"):
    d = MagicMock()
    d.satirlar = list(satirlar or [])
    d.depo = SimpleNamespace(get=lambda: depo)
    d._doviz_para_birimi = SimpleNamespace(get=lambda: "TRY")
    d._fatura_satirlari_hazir = False
    d._duzenlenen_satir = None
    d.satir_tablosu = None
    d.barkod_okut_entry = MagicMock()
    d.satir_girdileri = {}
    d._satir_listesini_yenile = MagicMock()
    d._toplamlari_guncelle = MagicMock()
    d.after = MagicMock()
    return d


def test_barkod_stok_yetersiz_miktar_yinede_artar():
    """Stok 0 olsa bile 3 okutmada miktar 3; stok kontrolü çağrılmaz."""
    from fatura_barkod_ui import _satira_uygula

    dialog = _mock_dialog()
    kayit = {
        "stok_kodu": "X1",
        "stok_adi": "Test Ürün",
        "birim": "Adet",
        "birim_fiyat": Decimal("10"),
        "kdv_orani": Decimal("20"),
        "barkod": "1031109304",
        "carpan": Decimal("1"),
    }
    with patch("fatura_barkod_ui._eksi_stok_kontrol") as kontrol, patch(
        "fatura_barkod_ui._musteri_fiyat", return_value=Decimal("10")
    ), patch(
        "fatura_barkod_ui.StokService.stoklari_ara", return_value=[]
    ), patch(
        "fatura_barkod_ui.StokService.maliyetler", return_value={}
    ), patch(
        "fatura_barkod_ui._barkod_odak"
    ), patch(
        "fatura_satir_birim_service.temel_miktar", side_effect=lambda m, b, k: Decimal(str(m))
    ):
        for _ in range(3):
            _satira_uygula(dialog, kayit, okutulan_barkod="1031109304")
        kontrol.assert_not_called()
    assert len(dialog.satirlar) == 1
    assert Decimal(str(dialog.satirlar[0]["miktar"])) == Decimal("3")
    dialog._satir_listesini_yenile.assert_called()
    dialog._toplamlari_guncelle.assert_called()


def test_barkod_farkli_urun_iki_satir():
    from fatura_barkod_ui import _satira_uygula

    dialog = _mock_dialog()
    a = {
        "stok_kodu": "A",
        "stok_adi": "Ürün A",
        "birim": "Adet",
        "birim_fiyat": Decimal("1"),
        "kdv_orani": Decimal("20"),
        "barkod": "111",
        "carpan": Decimal("1"),
    }
    b = {
        "stok_kodu": "B",
        "stok_adi": "Ürün B",
        "birim": "Adet",
        "birim_fiyat": Decimal("2"),
        "kdv_orani": Decimal("20"),
        "barkod": "222",
        "carpan": Decimal("1"),
    }
    with patch("fatura_barkod_ui._musteri_fiyat", side_effect=lambda d, k, f: f), patch(
        "fatura_barkod_ui.StokService.stoklari_ara", return_value=[]
    ), patch(
        "fatura_barkod_ui.StokService.maliyetler", return_value={}
    ), patch(
        "fatura_barkod_ui._barkod_odak"
    ), patch(
        "fatura_satir_birim_service.temel_miktar", side_effect=lambda m, b, k: Decimal(str(m))
    ):
        _satira_uygula(dialog, a, okutulan_barkod="111")
        _satira_uygula(dialog, b, okutulan_barkod="222")
    assert len(dialog.satirlar) == 2


def test_hucre_stok_kontrol_her_zaman_izin():
    from fatura_satir_hucre_edit import _stok_kontrol

    assert _stok_kontrol(MagicMock(), 0, Decimal("999"), "X") is True


def test_onay_mesaj_format_toplu():
    """Aynı ürün iki satır → onayda toplam talep mesajı."""
    from database.satis_faturasi_service import SatisFaturasiService

    session = MagicMock()
    fatura = SimpleNamespace(
        depo="ANA DEPO",
        irsaliye_id=None,
        satirlar=[
            SimpleNamespace(
                urun_kodu="P1",
                urun_adi="2F Jumbo Ayak Beyaz 6 CM",
                miktar=Decimal("2"),
                birim="Adet",
                irsaliye_satiri_id=None,
            ),
            SimpleNamespace(
                urun_kodu="P1",
                urun_adi="2F Jumbo Ayak Beyaz 6 CM",
                miktar=Decimal("1"),
                birim="Adet",
                irsaliye_satiri_id=None,
            ),
        ],
    )
    depo = SimpleNamespace(id=1, ad="ANA DEPO")
    stok = SimpleNamespace(id=10, stok_kodu="P1", birim="Adet")

    def _scalar(stmt):
        # ilk çağrı Depo, sonra StokKarti, sonra sum
        sql = str(stmt)
        if "depolar" in sql.casefold() or "Depo" in type(stmt).__name__:
            pass
        return None

    # session.scalar sırası: Depo, StokKarti, sum(kalan)
    session.scalar = MagicMock(side_effect=[depo, stok, Decimal("1")])

    with patch(
        "fatura_satir_birim_service.temel_miktar",
        side_effect=lambda m, b, k: Decimal(str(m)),
    ), pytest.raises(ValueError) as ctx:
        SatisFaturasiService._onay_oncesi_stok_yeterlilik(session, fatura)

    mesaj = str(ctx.value)
    assert "stok yetersiz" in mesaj.casefold()
    assert "2F Jumbo Ayak Beyaz 6 CM" in mesaj
    assert "Mevcut: 1 Adet" in mesaj
    assert "Faturadaki toplam miktar: 3 Adet" in mesaj
    assert "Eksik: 2 Adet" in mesaj
