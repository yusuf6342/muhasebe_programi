"""Satır içi ürün adı listesi: yazınca açılır, Kalan gösterir, seçim ve «Yeni Kayıt Ekle»."""

from __future__ import annotations

import sys
import time
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import satir_ici_urun_giris as sig
from database.stok_service import StokService
from tests import test_satir_ici_urun_giris as _giris_testleri
from tests.test_satir_ici_urun_giris import _GirisTemel


def _senkron(_w, is_fn, on_ok=None, on_err=None):
    try:
        sonuc = is_fn()
    except Exception as exc:  # noqa: BLE001
        if on_err is not None:
            on_err(exc)
        return
    if on_ok is not None:
        on_ok(sonuc)


class SatirUrunListesiTest(_GirisTemel):
    _kur = _giris_testleri.SatirIciBilesenTest._kur

    def setUp(self):
        super().setUp()
        self._ek_yamalar = [
            patch("ui_bg.arka_planda", side_effect=_senkron),
            patch.object(sig, "DEBOUNCE_MS", 1),
        ]
        for p in self._ek_yamalar:
            p.start()

    def tearDown(self):
        for p in self._ek_yamalar:
            p.stop()
        super().tearDown()

    def _bekle(self, pen, kosul, sure=2.0):
        son = time.monotonic() + sure
        while time.monotonic() < son:
            pen.update()
            if kosul():
                return True
            time.sleep(0.01)
        return kosul()

    def _yaz(self, pen, giris, metin, rol="ad"):
        giris.ac(rol, "")
        giris._var.set(metin)
        giris._tus_birakildi()
        self.assertTrue(self._bekle(pen, lambda: giris._popup is not None), "liste açılmadı")

    def _satirlar(self, giris):
        tree = giris._pop_tree
        return [(iid, tree.set(iid), tree.item(iid, "tags")) for iid in tree.get_children()]

    def test_yazinca_liste_acilir_kalan_ve_yeni_kayit_gosterir(self):
        pen, _tablo, giris, eklenen, _ = self._kur()
        self._yaz(pen, giris, "birim")
        self.assertEqual(giris._pop_tree.heading("stok", "text"), "Kalan")
        satirlar = self._satirlar(giris)
        self.assertEqual(satirlar[0][1]["kod"], "MB001")
        beklenen = sig.sayi_metni(sig.urun_ara("birim")["urunler"][0]["stok"])
        self.assertEqual(satirlar[0][1]["stok"], beklenen)
        _iid, son, etiket = satirlar[-1]
        self.assertIn("yeni_kayit", etiket)
        self.assertIn("Yeni Kayıt Ekle", son["kod"])
        self.assertIn("«birim»", son["ad"])
        self.assertEqual(eklenen, [])
        pen.destroy()

    def test_ok_tuslari_ve_enter_satira_yazar(self):
        pen, _tablo, giris, eklenen, _ = self._kur()
        self._yaz(pen, giris, "birim")
        giris._asagi()  # «Yeni Kayıt Ekle» satırına iner
        self.assertEqual(giris._secili, len(giris._sonuclar))
        giris._yukari()
        self.assertEqual(giris._secili, 0)
        giris._enter()
        self.assertEqual([e[0] for e in eklenen], ["MB001"])
        self.assertIsNone(giris._popup)
        pen.destroy()

    def test_tek_tik_satira_yazar(self):
        pen, _tablo, giris, eklenen, _ = self._kur()
        self._yaz(pen, giris, "birim")
        tree = giris._pop_tree
        with patch.object(tree, "identify_region", return_value="cell"), patch.object(
            tree, "identify_row", return_value="0"
        ):
            giris._pop_tik(SimpleNamespace(x=5, y=5))
        self.assertEqual([e[0] for e in eklenen], ["MB001"])
        pen.destroy()

    def test_bos_alanda_ilk_urunler_listelenir(self):
        pen, _tablo, giris, eklenen, _ = self._kur()
        giris.ac("ad", "")
        giris.liste_ac()
        self.assertTrue(self._bekle(pen, lambda: giris._popup is not None))
        kodlar = [s[1]["kod"] for s in self._satirlar(giris)]
        self.assertIn("MB001", kodlar)
        self.assertIn("İlk", giris._pop_durum.cget("text"))
        pen.destroy()

    def test_barkod_kutusunda_harf_yazilinca_ad_aramasina_gecer(self):
        pen, _tablo, giris, _eklenen, _ = self._kur()
        self._yaz(pen, giris, "birim", rol="barkod")
        self.assertEqual(giris._rol, "ad")
        giris.kapat()
        giris.ac("barkod", "")
        giris._var.set("869000")
        giris._tus_birakildi()
        self.assertIsNone(giris._after, "rakamlı barkod okutması listeye dönmemeli")
        self.assertEqual(giris._rol, "barkod")
        pen.destroy()

    def _yeni_stok(self, ad: str):
        stok = StokService.stok_kaydi(
            {
                "stok_kodu": "YD001",
                "stok_adi": ad,
                "birim": "Adet",
                "kdv_orani": Decimal("20"),
                "kart_turu": "Ticari Mal",
            },
            [("SATIŞ FİYATI 1", "12")],
            birimler=None,
            barkodlar=None,
        )
        return StokService.stok_getir(stok.id) or stok

    def test_yeni_kayit_ekle_yazilan_adla_hizli_kart_ve_satira_ekler(self):
        pen, _tablo, giris, eklenen, _ = self._kur()
        ad = "Zeytinyağlı Deneme Kalemi"
        self._yaz(pen, giris, ad)
        self.assertEqual(giris._sonuclar, [])
        self.assertEqual(giris._secili, 0, "sonuç yokken «Yeni Kayıt Ekle» seçili gelmeli")
        cagri = {}

        def _kart(dialog, *, barkod=None, urun_adi=None, **_k):
            cagri.update(barkod=barkod, urun_adi=urun_adi)
            return self._yeni_stok(urun_adi)

        with patch("hizli_stok_karti_ui.hizli_stok_karti_ac", side_effect=_kart):
            giris._enter()
        self.assertEqual(cagri, {"barkod": None, "urun_adi": ad})
        self.assertEqual([e[0] for e in eklenen], ["YD001"])
        pen.destroy()

    def test_kart_kendisi_eklediyse_ikinci_kez_eklenmez(self):
        pen, _tablo, giris, eklenen, _ = self._kur()
        ad = "Zeytinyağlı Deneme Kalemi"
        self._yaz(pen, giris, ad)

        def _kart(dialog, *, barkod=None, urun_adi=None, **_k):
            stok = self._yeni_stok(urun_adi)
            giris.stoktan_ekle(stok)  # «Kaydet ve Faturaya Ekle»
            return stok

        with patch("hizli_stok_karti_ui.hizli_stok_karti_ac", side_effect=_kart):
            giris.yeni_kayit_ekle()
        self.assertEqual([e[0] for e in eklenen], ["YD001"])
        pen.destroy()


if __name__ == "__main__":
    unittest.main()
