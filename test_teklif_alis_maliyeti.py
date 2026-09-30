"""Teklif iç ekranı: birim dönüşümlü alış maliyeti, genel maliyet özeti ve müşteri görünümü.

Yalnız geçici test veritabanı kullanılır; gerçek firma verisine dokunulmaz.
"""

from __future__ import annotations

import re
import sys
import tkinter as tk
import unittest
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from database.teklif_customer_view import (
    YASAK_MUSTERI_ALANLARI,
    assert_customer_output_safe,
    eksik_satis_fiyati_satirlari,
    musteri_gorunumu_metni,
)
from database.teklif_pricing_service import (
    QuotePricingService,
    alis_maliyet_ozeti,
    dagitimli_hesapla,
    ic_maliyet_ozeti,
    satir_alis_maliyeti,
)

D = Decimal


def _satir(kod, base, miktar, carpan=1, birim="Adet", fiyat=None, isk=0, kdv=20, **ek):
    s = {
        "urun_kodu": kod,
        "urun_adi": f"{kod} ürün",
        "miktar": D(str(miktar)),
        "birim": birim,
        "birim_carpani": D(str(carpan)),
        "purchase_unit_price_base": D(str(base)),
        "birim_maliyet": D(str(base)),
        "teklif_fiyati": None if fiyat is None else D(str(fiyat)),
        "iskonto_orani": D(str(isk)),
        "iskonto_orani_2": 0,
        "iskonto_orani_3": 0,
        "kdv_orani": D(str(kdv)),
        "net_birim_fiyat": None,
        "opsiyonel": False,
        "toplama_dahil": True,
    }
    s.update(ek)
    return s


class SatirAlisMaliyetiTest(unittest.TestCase):
    def test_koli_adet_fiyatiyla_dogrudan_carpilmaz(self):
        m = satir_alis_maliyeti(_satir("VIDA", "10.00", 2, carpan=12, birim="Koli"))
        self.assertEqual(m.birim_fiyat, D("120.0000"))
        self.assertEqual(m.toplam, D("240.00"))

    def test_kurus_yalniz_satir_toplaminda_yuvarlanir(self):
        self.assertEqual(satir_alis_maliyeti(_satir("A", "0.3333", 3)).toplam, D("1.00"))
        self.assertEqual(satir_alis_maliyeti(_satir("B", "1.005", 1)).toplam, D("1.01"))
        # 0,0833 × 12 = 0,9996 → × 7 = 6,9972 → 7,00 (ara yuvarlama yok)
        self.assertEqual(
            satir_alis_maliyeti(_satir("C", "0.0833", 7, carpan=12)).toplam, D("7.00")
        )

    def test_eksik_alis_fiyati_sifir_sayilmaz(self):
        m = satir_alis_maliyeti(_satir("CIVI", 0, 5))
        self.assertTrue(m.eksik)
        self.assertIsNone(m.toplam)
        self.assertIsNone(m.birim_fiyat)

    def test_carpan_yoksa_bir(self):
        s = _satir("X", "4", 3)
        del s["birim_carpani"]
        self.assertEqual(satir_alis_maliyeti(s).toplam, D("12.00"))


class GenelMaliyetOzetiTest(unittest.TestCase):
    def _satirlar(self):
        return [
            _satir("VIDA", "10", 2, carpan=12, birim="Koli", fiyat=150, isk=10),
            _satir("MENTESE", "4", 5, fiyat=6),
            _satir("KULP", "2.345", 3, carpan=6, birim="Paket", fiyat=20, kdv=10),
        ]

    def test_satir_toplamlari_genel_ile_eslesir(self):
        satirlar = self._satirlar()
        ozet = alis_maliyet_ozeti(satirlar)
        satir_toplam = sum(satir_alis_maliyeti(s).toplam for s in satirlar)
        # 240,00 + 20,00 + (2,345 × 6 × 3 = 42,21)
        self.assertEqual(satir_toplam, D("302.21"))
        self.assertEqual(ozet["genel_alis_maliyeti"], satir_toplam)
        self.assertFalse(ozet["eksik_var"])
        self.assertEqual(
            QuotePricingService.satir_toplamlari(satirlar)["toplam_maliyet"], satir_toplam
        )

    def test_miktar_birim_fiyat_degisimi_ve_satir_silme(self):
        satirlar = self._satirlar()
        satirlar[0]["miktar"] = D("3")
        self.assertEqual(alis_maliyet_ozeti(satirlar)["genel_alis_maliyeti"], D("422.21"))
        satirlar[0]["purchase_unit_price_base"] = D("11")
        self.assertEqual(alis_maliyet_ozeti(satirlar)["genel_alis_maliyeti"], D("458.21"))
        satirlar[0]["birim"], satirlar[0]["birim_carpani"] = "Adet", D("1")
        self.assertEqual(alis_maliyet_ozeti(satirlar)["genel_alis_maliyeti"], D("95.21"))
        del satirlar[1]
        self.assertEqual(alis_maliyet_ozeti(satirlar)["genel_alis_maliyeti"], D("75.21"))

    def test_eksik_maliyet_belirtilir_ve_toplama_katilmaz(self):
        satirlar = self._satirlar() + [_satir("CIVI", 0, 5, fiyat=1)]
        ozet = alis_maliyet_ozeti(satirlar)
        self.assertTrue(ozet["eksik_var"])
        self.assertEqual(ozet["genel_alis_maliyeti"], D("302.21"))
        self.assertEqual(len(ozet["eksik_satirlar"]), 1)
        self.assertIn("4. CIVI", ozet["eksik_satirlar"][0])
        self.assertEqual(QuotePricingService.satir_toplamlari(satirlar)["eksik_maliyet_satir"], 1)

    def test_opsiyonel_toplam_disi_satir_sayilmaz(self):
        satirlar = self._satirlar()
        satirlar.append(_satir("OPS", "100", 1, opsiyonel=True, toplama_dahil=False))
        self.assertEqual(alis_maliyet_ozeti(satirlar)["genel_alis_maliyeti"], D("302.21"))

    def test_iskonto_kdv_masraf_kar_marj(self):
        ozet = ic_maliyet_ozeti(self._satirlar(), D("10"), D("5"))
        # Satış (KDV hariç): 2×150×0,90=270 + 5×6=30 + 3×20=60 → 360
        self.assertEqual(ozet["satis_toplami"], D("360.00"))
        self.assertEqual(ozet["genel_alis_maliyeti"], D("302.21"))
        self.assertEqual(ozet["kar_tutari"], D("42.79"))  # 360 − 302,21 − 10 − 5
        self.assertEqual(ozet["kar_marji"], D("11.89"))
        tot = QuotePricingService.satir_toplamlari(self._satirlar())
        self.assertEqual(tot["kdv_toplam"], D("66.00"))  # 54 + 6 + 6; kâra girmez
        self.assertEqual(tot["iskonto_toplam"], D("30.00"))

    def test_satis_yoksa_marj_bos(self):
        ozet = ic_maliyet_ozeti([_satir("A", "5", 1)])
        self.assertIsNone(ozet["kar_marji"])

    def test_fiyat_hesapla_birim_carpanini_kullanir(self):
        satirlar = [_satir("VIDA", "10", 2, carpan=12, birim="Koli"), _satir("M", "4", 5)]
        sonuc = dagitimli_hesapla(satirlar, profit_rate=20)
        self.assertEqual(sonuc.total_purchase_cost, D("260.00"))
        vida = sonuc.satirlar[0]
        # 240 alış, %20 satış marjı → 300 → Koli başına 150
        self.assertEqual(D(str(vida["teklif_fiyati"])), D("150.00"))


class EksikSatisFiyatiTest(unittest.TestCase):
    def test_bos_ve_hesaplanmamis_satirlar_listelenir(self):
        satirlar = [
            _satir("A", 1, 1, fiyat=10, fiyat_hesaplandi=True),
            _satir("B", 1, 1),
            _satir("C", 1, 1, fiyat=0, fiyat_hesaplandi=False),
            _satir("D", 1, 1, fiyat=12),  # kayıtlı eski teklif
        ]
        eksik = eksik_satis_fiyati_satirlari(satirlar)
        self.assertEqual(len(eksik), 2)
        self.assertTrue(eksik[0].startswith("2. B"))
        self.assertTrue(eksik[1].startswith("3. C"))


# ---------------------------------------------------------------------------
# Arayüz akışı — geçici firma DB + ekran dışı Tk
# ---------------------------------------------------------------------------

_MALIYET_METINLERI = ("120,00", "240,00", "47,25", "287,25", "33,33")


def _metin_icerir(metin: str, deger: str) -> bool:
    return re.search(rf"(?<![\d.,]){re.escape(deger)}(?![\d])", metin) is not None


class TeklifEkraniAkisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"Tk yok: {exc}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:
            pass

    def setUp(self):
        from tests import test_tahsilat_makbuzu as kurulum
        from database.database import get_session
        from database.models.stok import StokBirim, StokKarti

        self._kurulum = kurulum.TahsilatMakbuzuTest()
        self._kurulum.setUp()
        with get_session() as s:
            vida = StokKarti(stok_kodu="VIDA", stok_adi="Sunta Vidası", birim="Adet")
            vida.birimler.append(StokBirim(birim_adi="Koli", carpan=D("12")))
            s.add(vida)
            s.add(StokKarti(stok_kodu="CIVI", stok_adi="Çivi", birim="Adet"))
        self._yamalar = [
            patch("ui_pencere.belge_penceresini_hazirla", lambda win, **_k: (win.withdraw(), {})[1]),
            patch("teklif_ui.messagebox"),
            patch("invoice_print.branding.load_company_branding",
                  return_value={"unvan": "Ray Test Firma", "ibanlar": []}),
            patch("invoice_print.branding.logo_data_uri", return_value=None),
            patch("belge_kullanici_ui.aktif_kullanici_adi", return_value="Test Admin"),
        ]
        mocks = [p.start() for p in self._yamalar]
        self.mb = mocks[1]
        self.mb.askyesnocancel.return_value = True
        self.mb.askyesno.return_value = True
        self._pencereler: list[tk.Misc] = []

    def tearDown(self):
        for w in reversed(self._pencereler):
            try:
                w.destroy()
            except tk.TclError:
                pass
        for p in reversed(self._yamalar):
            p.stop()
        self._kurulum.tearDown()

    # —— yardımcılar ——
    def _dialog(self, teklif_id=None):
        from teklif_ui import TeklifDialog

        dlg = TeklifDialog(self.root, teklif_id=teklif_id)
        dlg.withdraw()
        self._pencereler.append(dlg)
        return dlg

    @staticmethod
    def _giris(entry, deger):
        entry.delete(0, "end")
        if deger:
            entry.insert(0, deger)

    def _ekle(self, dlg, kod, miktar, birim, maliyet="", ad=None, manuel=False):
        dlg.add_product_to_quote(
            quantity=D(str(miktar)), unit_id=birim, urun_kodu=kod, urun_adi=ad, manuel=manuel,
            maliyet=D(maliyet.replace(",", ".")) if maliyet else None,
        )

    @staticmethod
    def _hucre(dlg, idx, kolon):
        return dlg.satir_tablo.set(dlg.satir_tablo.get_children()[idx], kolon)

    @staticmethod
    def _panel(dlg, anahtar):
        return dlg.ic_maliyet_degerleri[anahtar].cget("text")

    def _satiri_duzenle(self, dlg, idx, miktar=None, birim=None, maliyet=None):
        """Satır içi hücre düzenleme; maliyet ana birim alış fiyatıdır (hücrede seçili birime çevrilir)."""
        if miktar is not None:
            dlg.teklif_hucre_uygula(idx, "miktar", str(miktar))
        if birim is not None:
            dlg.teklif_hucre_uygula(idx, "birim", birim)
        if maliyet is not None:
            carpan = D(str(dlg.satirlar[idx].get("birim_carpani") or 1))
            dlg.teklif_hucre_uygula(idx, "alis", str(D(maliyet.replace(",", ".")) * carpan))

    # —— senaryo ——
    def test_ic_ekran_maliyet_kaydet_yeniden_ac_ve_musteri_gorunumu(self):
        from database.database import get_session
        from database.models.satis_teklifi import SatisTeklifi
        from sqlalchemy import func, select

        dlg = self._dialog()
        self.assertNotIn("kaynak", dlg.satir_tablo["columns"])
        self.assertEqual(dlg.satir_tablo.heading("alis_toplam", "text"), "Alış Maliyeti")

        self._ekle(dlg, "VIDA", 2, "Koli", maliyet="10")
        self._ekle(dlg, "CIVI", 5, "Adet")
        self._ekle(dlg, "MANUEL", 1, "Adet", maliyet="47,25", ad="Özel Montaj", manuel=True)
        self.assertEqual(len(dlg.satirlar), 3)
        self.assertEqual(dlg.satirlar[0]["birim_carpani"], D("12"))

        # Satır maliyetleri (birim dönüşümlü) ve eksik maliyet
        self.assertEqual(self._hucre(dlg, 0, "alis"), "120,00")
        self.assertEqual(self._hucre(dlg, 0, "alis_toplam"), "240,00")
        self.assertEqual(self._hucre(dlg, 1, "alis"), "EKSİK")
        self.assertEqual(self._hucre(dlg, 1, "alis_toplam"), "EKSİK")
        self.assertIn("maliyet_yok", dlg.satir_tablo.item(dlg.satir_tablo.get_children()[1], "tags"))
        self.assertEqual(self._hucre(dlg, 2, "alis_toplam"), "47,25")
        self.assertEqual(self._panel(dlg, "genel_alis_maliyeti"), "287,25 *")
        uyari = dlg.lbl_ic_maliyet_uyari.cget("text")
        self.assertIn("EKSİK", uyari)
        self.assertIn("CIVI", uyari)

        # Boş satış fiyatı → müşteri PDF'si engellenir, satırlar listelenir
        self.assertEqual(len(dlg._hesaplanmamis_satis_satirlari()), 3)
        with patch("teklif_print.musteri_teklif_pdf_uret") as pdf_uret:
            self.assertIsNone(dlg._pdf_onizleme())
            pdf_uret.assert_not_called()
        mesaj = self.mb.showwarning.call_args[0][1]
        self.assertIn("1. VIDA", mesaj)
        self.assertIn("2. CIVI", mesaj)

        # Miktar / birim / alış fiyatı değişimi → satır ve genel toplam anında
        self._satiri_duzenle(dlg, 0, miktar=3)
        self.assertEqual(self._hucre(dlg, 0, "alis_toplam"), "360,00")
        self.assertEqual(self._panel(dlg, "genel_alis_maliyeti"), "407,25 *")
        self._satiri_duzenle(dlg, 0, birim="Adet")
        self.assertEqual(dlg.satirlar[0]["birim_carpani"], D("1"))
        self.assertEqual(self._hucre(dlg, 0, "alis_toplam"), "30,00")
        self._satiri_duzenle(dlg, 0, miktar=2, birim="Koli", maliyet="11")
        self.assertEqual(self._hucre(dlg, 0, "alis_toplam"), "264,00")
        self._satiri_duzenle(dlg, 0, maliyet="10")
        self.assertEqual(self._hucre(dlg, 0, "alis_toplam"), "240,00")

        # Satır silme → eksik maliyet uyarısı kalkar
        dlg.satir_tablo.selection_set(dlg.satir_tablo.get_children()[1])
        dlg._satir_sil()
        self.assertEqual(len(dlg.satirlar), 2)
        self.assertEqual(self._panel(dlg, "genel_alis_maliyeti"), "287,25")
        self.assertEqual(dlg.lbl_ic_maliyet_uyari.cget("text"), "")

        # Mevcut «Fiyatları Hesapla» (%20 marj) birim dönüşümüne göre fiyatlar
        self._giris(dlg.fiyat_girdiler["profit_rate"], "20")
        dlg._fiyatlari_hesapla()
        self.assertEqual(D(str(dlg.satirlar[0]["teklif_fiyati"])), D("150.00"))
        self.assertEqual(dlg._hesaplanmamis_satis_satirlari(), [])
        manuel_fiyat = D(str(dlg.satirlar[1]["teklif_fiyati"]))
        self.assertEqual(manuel_fiyat, D("59.06"))

        # İskonto + iç masraf → satış / kâr ayrı ve açık
        dlg.satirlar[0]["iskonto_orani"] = D("10")
        dlg.satirlar[0]["net_birim_fiyat"] = None
        dlg._satir_tutar_yenile(dlg.satirlar[0])
        self._giris(dlg.fiyat_girdiler["internal_expense_amount"], "33,33")
        dlg._satir_tablo_yenile()
        dlg._toplam_guncelle()
        self.assertEqual(self._panel(dlg, "satis_toplami"), "329,06")  # 270 + 59,06
        self.assertEqual(self._panel(dlg, "ic_masraf"), "33,33")
        self.assertEqual(self._panel(dlg, "kar_tutari"), "8,48")  # 329,06 − 287,25 − 33,33
        self.assertEqual(self._panel(dlg, "kar_marji"), "%2,58")
        satir_toplam = sum(satir_alis_maliyeti(s).toplam for s in dlg.satirlar)
        self.assertEqual(satir_toplam, dlg._ic_maliyet_ozeti_hesapla()["genel_alis_maliyeti"])

        # Kaydet → yeniden aç
        dlg.girdiler["aday_musteri_adi"].set("Deneme Müşteri A.Ş.")
        dlg.kaydet()
        self.assertIsNotNone(dlg.teklif, self.mb.showerror.call_args)
        tid = dlg.teklif.id
        dlg2 = self._dialog(tid)
        self.assertEqual(len(dlg2.satirlar), 2)
        self.assertEqual(D(str(dlg2.satirlar[0]["birim_carpani"])), D("12"))
        self.assertEqual(self._hucre(dlg2, 0, "alis"), "120,00")
        self.assertEqual(self._hucre(dlg2, 0, "alis_toplam"), "240,00")
        self.assertEqual(self._hucre(dlg2, 1, "alis_toplam"), "47,25")
        self.assertEqual(self._panel(dlg2, "genel_alis_maliyeti"), "287,25")
        self.assertEqual(self._panel(dlg2, "satis_toplami"), "329,06")
        self.assertEqual(self._panel(dlg2, "kar_tutari"), "8,48")

        # Müşteri görünümü: aynı kayıttan, maliyet/kâr yok
        dlg2._musteri_gorunumu()
        cv = dlg2._musteri_gorunumu_dlg
        self._pencereler.insert(0, cv)
        cv.withdraw()
        hucreler = [cv.tablo.item(i, "values") for i in cv.tablo.get_children()]
        self.assertEqual(len(hucreler), 2)
        self.assertEqual(hucreler[0][4], "150,00")
        self.assertEqual(hucreler[0][5], "%10,00")
        self.assertEqual(hucreler[0][7], "270,00")
        gorunen = " | ".join(
            [" ".join(map(str, h)) for h in hucreler]
            + [w.cget("text") for w in (cv.lbl_firma, cv.lbl_teklif, cv.lbl_musteri,
                                        cv.lbl_toplam, cv.lbl_sartlar, cv.lbl_eksik)]
        )
        self.assertIn(cv.vm.teklif_no, gorunen)
        self.assertIn("Deneme Müşteri", gorunen)
        for deger in _MALIYET_METINLERI + ("8,48", "2,58"):
            self.assertFalse(_metin_icerir(gorunen, deger), deger)
        assert_customer_output_safe(gorunen)

        vm_dict = asdict(cv.vm)
        anahtarlar = set(vm_dict) | set(vm_dict["satirlar"][0])
        self.assertFalse(anahtarlar & YASAK_MUSTERI_ALANLARI)
        vm_metin = str(vm_dict)
        for deger in ("287.25", "47.25", "33.33", "8.48", "120.0000"):
            self.assertNotIn(deger, vm_metin)

        metin = musteri_gorunumu_metni(cv.vm)
        for deger in _MALIYET_METINLERI + ("8,48",):
            self.assertFalse(_metin_icerir(metin, deger), deger)
        self.assertIn("GENEL TOPLAM", metin)

        from teklif_print import musteri_teklif_html_uret

        _, html = musteri_teklif_html_uret(dlg2)
        assert_customer_output_safe(html)
        self.assertIn(cv.vm.teklif_no, html)
        self.assertIn("Oluşturulma:", html)
        for deger in _MALIYET_METINLERI:
            self.assertFalse(_metin_icerir(html, deger), deger)

        # İç ekranda miktar değişince müşteri görünümü güncel kaydı gösterir
        self._satiri_duzenle(dlg2, 0, miktar=4)
        self.assertIsNotNone(cv._bekleyen)
        cv.yenile()
        self.assertEqual(cv.tablo.item(cv.tablo.get_children()[0], "values")[7], "540,00")

        # PDF Önizleme: aynı teklif, ikinci kayıt yok
        with patch("teklif_print.musteri_teklif_pdf_uret", return_value=Path("x.pdf")) as uret, \
                patch("teklif_print.pdf_ac") as ac:
            self.assertEqual(dlg2._pdf_onizleme(), Path("x.pdf"))
            uret.assert_called_once_with(dlg2)
            ac.assert_called_once()
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(SatisTeklifi.id))), 1)

    def test_musteri_pdf_gercek_uretim(self):
        from teklif_print import _chrome_paths, musteri_teklif_pdf_uret

        if not any(p.exists() for p in _chrome_paths()):
            self.skipTest("Chrome/Edge yok")
        dlg = self._dialog()
        self._ekle(dlg, "VIDA", 2, "Koli", maliyet="10")
        self._giris(dlg.fiyat_girdiler["profit_rate"], "20")
        dlg._fiyatlari_hesapla()
        dlg.girdiler["aday_musteri_adi"].set("PDF Müşteri")
        dlg.kaydet()
        hedef = Path(self._kurulum._tmpdir.name) / "teklif.pdf"
        pdf = musteri_teklif_pdf_uret(dlg, hedef)
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
