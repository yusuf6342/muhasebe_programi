"""Fatura satırı: ürün adı → stok kartı; + / F10 → liste; birim uyumu; kilit."""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class SatirStokKartiAcTest(unittest.TestCase):
    def test_product_id_ile_dogru_kart(self):
        from satir_klavye import satir_stok_karti_ac

        stok = SimpleNamespace(id=42, stok_kodu="U42", stok_adi="Test")
        dialog = SimpleNamespace(
            satirlar=[{"urun_kodu": "U42", "product_id": 42, "urun_adi": "Test"}],
        )
        with (
            patch("database.stok_service.StokService.stok_getir", return_value=stok) as getir,
            patch("stok_ui.StokKartiDialog") as dlg,
        ):
            self.assertTrue(satir_stok_karti_ac(dialog, 0))
            getir.assert_called_once_with(42)
            dlg.assert_called_once()

    def test_bos_satirda_bilgi_yeni_kart_acmaz(self):
        from satir_klavye import satir_stok_karti_ac

        dialog = SimpleNamespace(satirlar=[{"urun_kodu": "", "urun_adi": ""}])
        with (
            patch("satir_klavye.messagebox.showinfo") as info,
            patch("stok_ui.StokKartiDialog") as dlg,
        ):
            self.assertFalse(satir_stok_karti_ac(dialog, 0))
            info.assert_called_once()
            dlg.assert_not_called()


class UrunDegistirBirimTest(unittest.TestCase):
    def _dialog(self, satirlar):
        d = MagicMock()
        d.satirlar = satirlar
        d._fatura_kilitli = False
        d._duzenlenen_satir = None
        d._satir_listesini_yenile = MagicMock()
        d._toplamlari_guncelle = MagicMock()
        d._satir_ici_miktara_git = MagicMock()
        # SatisFaturasiDialog metodunu bağla
        from app import SatisFaturasiDialog

        d._satir_ici_urun_degistir = SatisFaturasiDialog._satir_ici_urun_degistir.__get__(d, type(d))
        return d

    def test_ayni_birimde_miktar_korunur_ve_uid(self):
        d = self._dialog(
            [
                {
                    "urun_kodu": "A",
                    "urun_adi": "Eski",
                    "birim": "Adet",
                    "miktar": "5",
                    "satir_uid": "uid-1",
                    "barkod": "",
                }
            ]
        )
        def _sab(**kwargs):
            return {
                "urun_kodu": kwargs.get("urun_kodu"),
                "urun_adi": kwargs.get("urun_adi"),
                "birim": kwargs.get("birim"),
                "miktar": str(kwargs.get("miktar") or 1),
                "barkod": "",
                "product_id": kwargs.get("product_id"),
            }

        with (
            patch("fatura_urun_aktar_service.stoktan_satir_sablonu", side_effect=lambda *a, **k: _sab(**k)) as sab,
            patch("fatura_barkod_ui.belge_kancasi", return_value=None),
            patch("fatura_satir_hucre_edit.uzlasma_etkisini_kaldir"),
            patch("fatura_barkod_ui._satir_uid_ver", return_value="uid-1"),
        ):
            ok = d._satir_ici_urun_degistir(
                0, ("B", "Yeni", "Adet", "0", "10", "Stok", "20", 9)
            )
        self.assertTrue(ok)
        self.assertEqual(sab.call_args.kwargs["miktar"], Decimal("5"))
        self.assertEqual(d.satirlar[0]["miktar"], "5")
        self.assertEqual(d.satirlar[0]["satir_uid"], "uid-1")

    def test_uyumsuz_birimde_miktar_1(self):
        d = self._dialog(
            [
                {
                    "urun_kodu": "A",
                    "urun_adi": "Eski",
                    "birim": "Koli",
                    "miktar": "3",
                    "satir_uid": "uid-2",
                }
            ]
        )
        sablon = {
            "urun_kodu": "B",
            "urun_adi": "Yeni",
            "birim": "Adet",
            "miktar": "1",
            "barkod": "",
        }
        with (
            patch("fatura_urun_aktar_service.stoktan_satir_sablonu", return_value=dict(sablon)) as sab,
            patch("fatura_barkod_ui.belge_kancasi", return_value=None),
            patch("fatura_satir_hucre_edit.uzlasma_etkisini_kaldir"),
            patch("fatura_barkod_ui._satir_uid_ver", return_value="uid-2"),
            patch("fatura_satir_birim_service.stok_aktif_birimleri", return_value=["Adet"]),
            patch("app.messagebox.showinfo"),
        ):
            ok = d._satir_ici_urun_degistir(
                0, ("B", "Yeni", "Adet", "0", "10", "Stok", "20", 9)
            )
        self.assertTrue(ok)
        # stoktan_satir_sablonu miktar=1 ile çağrıldı
        kwargs = sab.call_args.kwargs
        self.assertEqual(kwargs["miktar"], Decimal("1"))
        d._satir_ici_miktara_git.assert_called()

    def test_kilitli_faturada_degistirme_red(self):
        d = self._dialog([{"urun_kodu": "A", "birim": "Adet", "miktar": "1"}])
        d._fatura_kilitli = True
        with patch("app.messagebox.showwarning") as warn:
            self.assertFalse(
                d._satir_ici_urun_degistir(0, ("B", "Yeni", "Adet", "0", "1", "Stok", "20", 1))
            )
        warn.assert_called_once()


class ArtiButonHedefTest(unittest.TestCase):
    def test_satirdan_urun_sec_kilitli(self):
        from fatura_satir_yeni_urun import satirdan_urun_sec_ac

        d = SimpleNamespace(_fatura_kilitli=True, _satir_ici_giris=None)
        with patch("fatura_satir_yeni_urun.messagebox.showwarning") as w:
            satirdan_urun_sec_ac(d, 0)
        w.assert_called_once()

    def test_satirdan_urun_sec_hedef_idx(self):
        from fatura_satir_yeni_urun import satirdan_urun_sec_ac

        giris = MagicMock()
        d = SimpleNamespace(
            _fatura_kilitli=False,
            satirlar=[{"urun_kodu": "A"}, {"urun_kodu": "B"}],
            _satir_ici_giris=giris,
        )
        satirdan_urun_sec_ac(d, 1)
        giris.urun_listesi_ile_degistir.assert_called_once_with(1)

    def test_siparis_onayli_kilit(self):
        from fatura_satir_yeni_urun import belge_satir_kilitli

        class _Sip:
            def _onayli(self):
                return True

        self.assertTrue(belge_satir_kilitli(_Sip()))


if __name__ == "__main__":
    unittest.main()
