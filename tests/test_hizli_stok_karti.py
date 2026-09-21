"""Hızlı stok kartı — mükerrer kontrol ve miktar güvenliği."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

from fatura_satir_birim_service import miktar_metnini_coz
from hizli_stok_karti_ui import mukerrer_kontrol


def test_miktar_barkod_red():
    try:
        miktar_metnini_coz("2601031109304")
        assert False
    except ValueError:
        pass


def test_mukerrer_bos():
    with patch("hizli_stok_karti_ui.StokService") as S:
        S.stoklari_ara.return_value = []
        S.barkod_ile_bul.return_value = None
        r = mukerrer_kontrol(stok_kodu="X1", barkod="", stok_adi="abc")
        assert r["kod_cakisma"] is None
        assert r["barkod_cakisma"] is None


def test_mukerrer_kod():
    stok = MagicMock()
    stok.stok_kodu = "ABC"
    stok.stok_adi = "Test"
    with patch("hizli_stok_karti_ui.StokService") as S:
        S.stoklari_ara.return_value = [stok]
        S.barkod_ile_bul.return_value = None
        r = mukerrer_kontrol(stok_kodu="ABC", barkod="", stok_adi="")
        assert r["kod_cakisma"] is stok
