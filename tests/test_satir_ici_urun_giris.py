"""Satır içi ürün girişi: ortak bileşen + alış kartları ve teklif (izole SQLite, gizli Tk)."""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from database.database import get_session
from database.models.stok import StokFiyati, StokKarti
from satir_ici_urun_giris import (
    YENI_SATIR_IID,
    SatirIciUrunGirisi,
    alis_birim_fiyati,
    birlesecek_satir,
    iskonto_metni,
    iskonto_metni_coz,
    urun_ara,
    urun_degerleri,
    veri_iidleri,
)
from tests.test_satis_irsaliyesi_akis import _EkranTemel


class SatirIciYardimciTest(unittest.TestCase):
    def test_iskonto_metni_ve_cozumu(self):
        self.assertEqual(iskonto_metni({"iskonto_orani": 10, "iskonto_orani_2": 5}), "10+5")
        self.assertEqual(iskonto_metni({}), "")
        self.assertEqual(iskonto_metni_coz("10+5"), (Decimal("10"), Decimal("5"), Decimal("0")))
        self.assertEqual(iskonto_metni_coz(""), (Decimal("0"), Decimal("0"), Decimal("0")))
        with self.assertRaises(ValueError):
            iskonto_metni_coz("1+2+3+4")
        with self.assertRaises(ValueError):
            iskonto_metni_coz("abc")

    def test_birlesme_kaynak_bagli_ve_manuel_satiri_atlar(self):
        yeni = {"urun_kodu": "A", "birim": "Adet", "birim_fiyat": "5"}
        satirlar = [
            {"urun_kodu": "A", "birim": "Adet", "birim_fiyat": "5", "siparis_satiri_id": 7},
            {"urun_kodu": "A", "birim": "Adet", "birim_fiyat": "5", "is_manual_item": True},
            {"urun_kodu": "A", "birim": "Koli", "birim_fiyat": "5"},
            {"urun_kodu": "A", "birim": "Adet", "birim_fiyat": "6"},
        ]
        self.assertIsNone(birlesecek_satir(satirlar, yeni, fiyat_alani="birim_fiyat", ek_alanlar=()))
        satirlar.append({"urun_kodu": "A", "birim": "adet", "birim_fiyat": "5.0000"})
        self.assertEqual(birlesecek_satir(satirlar, yeni, fiyat_alani="birim_fiyat", ek_alanlar=()), 4)


class _GirisTemel(_EkranTemel):
    def setUp(self):
        super().setUp()
        with get_session() as s:
            stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "MB001"))
            stok.barkod = "8690000000017"
            s.add(StokFiyati(stok_id=stok.id, fiyat_adi="ALIŞ FİYATI", tutar=Decimal("0.4")))
            s.commit()


class SatirIciBilesenTest(_GirisTemel):
    def _kur(self, kilitli=lambda: False):
        import tkinter as tk
        from tkinter import ttk

        pen = tk.Toplevel(self.root)
        pen.withdraw()
        tablo = ttk.Treeview(pen, columns=("kod", "ad", "miktar"), show="headings")
        tablo.pack()
        pen.satirlar = []
        eklenen: list[tuple] = []

        def ekle(degerler, konum):
            eklenen.append((degerler[0], konum, getattr(pen, "_satir_toplu_ekleme", False)))
            pen.satirlar.append({"urun_kodu": degerler[0]})
            return len(pen.satirlar) - 1

        yenilenen: list[int] = []
        pen._satir_toplu_yenile = lambda: yenilenen.append(1)
        giris = SatirIciUrunGirisi(pen, tablo, urun_ekle=ekle, kolonlar={"kod": "kod", "ad": "ad"}, kilitli=kilitli)
        giris.tabloya_ekle()
        return pen, tablo, giris, eklenen, yenilenen

    def test_giris_satiri_sonda_kilitte_yok(self):
        kilit = {"v": False}
        pen, tablo, giris, *_ = self._kur(kilitli=lambda: kilit["v"])
        tablo.insert("", "end", iid="0", values=("A", "a", "1"))
        giris.tabloya_ekle()
        self.assertEqual(tablo.get_children()[-1], YENI_SATIR_IID)
        self.assertEqual(veri_iidleri(tablo), ["0"])
        kilit["v"] = True
        giris.tabloya_ekle()
        self.assertFalse(tablo.exists(YENI_SATIR_IID))
        pen.destroy()

    def test_liste_secimi_eski_sonuc_yok_sayilir_ve_bekleyen_metin_atilir(self):
        pen, _tablo, giris, eklenen, _ = self._kur()
        giris.ac("ad", "birim")
        sonuc = urun_ara("ürün birim")
        self.assertEqual([u["kod"] for u in sonuc["urunler"]], ["MB001"])
        giris._seq = 5
        giris._sonuc_uygula(4, "birim", sonuc)  # eski sorgu
        self.assertEqual(giris._sonuclar, [])
        giris._sonuc_uygula(5, "birim", sonuc)
        self.assertEqual(len(giris._sonuclar), 1)
        giris._enter()
        self.assertEqual([e[0] for e in eklenen], ["MB001"])
        giris.ac("ad", "yarım kalan")
        giris.bekleyeni_uygula()
        self.assertEqual(giris._var.get(), "")
        self.assertEqual(len(eklenen), 1)
        pen.destroy()

    def test_barkod_dogrudan_ekler_bulunamayan_mesaj_verir(self):
        pen, _tablo, giris, eklenen, _ = self._kur()
        giris.ac("kod", "8690000000017")
        giris._enter()
        self.assertEqual([e[0] for e in eklenen], ["MB001"])
        self.assertEqual(giris.son_islem, "secim")
        giris.ac("kod", "0000000000000")
        with patch.object(giris, "_durum_yaz") as durum:
            giris._barkod("0000000000000")
        self.assertEqual(len(eklenen), 1)
        self.assertIn("0000000000000", str(durum.call_args))
        pen.destroy()

    def test_coklu_secim_sirasiyla_ve_tek_yenileme(self):
        pen, _tablo, giris, eklenen, yenilenen = self._kur()
        ozet = {"kod": "X", "ad": "x", "birim": "Adet"}
        liste = [urun_degerleri({**ozet, "kod": k}) for k in ("C", "A", "B")]
        giris.toplu_ekle(liste)
        self.assertEqual([e[0] for e in eklenen], ["C", "A", "B"])
        self.assertTrue(all(e[2] for e in eklenen))
        self.assertEqual(yenilenen, [1])
        self.assertFalse(pen._satir_toplu_ekleme)
        pen.destroy()

    def test_alis_fiyati_birime_cevrilir(self):
        self.assertEqual(alis_birim_fiyati("MB001", "Adet"), Decimal("0.4"))
        self.assertEqual(alis_birim_fiyati("MB001", "Paket"), Decimal("40.0000"))


class AlisKartSatirGirisiTest(_GirisTemel):
    def test_alis_siparisi_alis_fiyati_kullanir_hucre_ve_barkod(self):
        from alis_ui import AlisSiparisiDialog

        d = AlisSiparisiDialog(self.root)
        d.withdraw()
        self.assertEqual(d.satir_tablosu.get_children(), (YENI_SATIR_IID,))
        idx = d._alis_urun_ekle(("MB001", "Birim Ürün", "Adet", "0", "1", "Stok Kartı", "20", None), None)
        self.assertEqual(d.satirlar[idx]["birim_alis_fiyati"], Decimal("0.4"))
        d.alis_hucre_uygula(idx, "birim", "Paket")
        self.assertEqual(d.satirlar[idx]["birim_alis_fiyati"], Decimal("40.0000"))
        d.alis_hucre_uygula(idx, "miktar", "3")
        d.alis_hucre_uygula(idx, "isk", "10")
        with self.assertRaises(ValueError):
            d.alis_hucre_uygula(idx, "miktar", "0")
        self.assertEqual(d.satirlar[idx]["miktar"], Decimal("3"))
        d._satir_ici_giris.son_islem = "barkod"
        d._alis_urun_ekle(("MB001", "Birim Ürün", "Adet", "0", "1", "Barkod", "20", None), None)
        d._alis_urun_ekle(("MB001", "Birim Ürün", "Adet", "0", "1", "Barkod", "20", None), None)
        d._satir_ici_giris.son_islem = "secim"
        self.assertEqual(len(d.satirlar), 2)
        self.assertEqual(d.satirlar[1]["miktar"], Decimal("2"))
        self.assertEqual(d.satir_tablosu.get_children()[-1], YENI_SATIR_IID)
        d.destroy()

    def test_alis_irsaliyesi_siparis_bagli_satir_kilitli(self):
        from alis_ui import AlisIrsaliyesiDialog

        d = AlisIrsaliyesiDialog(self.root)
        d.withdraw()
        d.satirlar.append({
            "siparis_satiri_id": 9, "urun_kodu": "MB001", "urun_adi": "Birim Ürün", "aciklama": "",
            "miktar": Decimal("5"), "birim": "Paket", "birim_fiyat": Decimal("40"),
            "iskonto_orani": 0, "kdv_orani": 20,
        })
        d._yenile()
        self.assertEqual(d._alis_birimleri(0), ["Paket"])
        with self.assertRaises(ValueError):
            d.alis_hucre_uygula(0, "birim", "Adet")
        self.assertFalse(d._alis_urun_degistir(0, ("MB001", "Birim Ürün", "Adet")))
        d.alis_hucre_uygula(0, "miktar", "4")
        self.assertEqual(d.satirlar[0]["miktar"], Decimal("4"))
        idx = d._alis_urun_ekle(("MB001", "Birim Ürün", "Adet"), 0)
        self.assertEqual(idx, 0)
        self.assertEqual(d.satirlar[0]["birim_fiyat"], Decimal("0.4"))
        self.assertEqual(d.satirlar[1]["siparis_satiri_id"], 9)
        d.destroy()

    def test_alis_faturasi_satir_ici_ekleme_hucre_ve_bekleyen_metin(self):
        from alis_ui import AlisFaturasiDialog

        d = AlisFaturasiDialog(self.root)
        d.withdraw()
        self.assertFalse(hasattr(d, "satir_girdileri"))
        self.assertEqual(d.satir_tablosu.get_children(), (YENI_SATIR_IID,))
        idx = d._alis_fatura_urun_ekle(("MB001", "Birim Ürün", "Adet", "0", "1", "Stok Kartı", "20", None), None)
        s = d.satirlar[idx]
        self.assertEqual(Decimal(s["birim_fiyat"]), Decimal("0.4"))
        self.assertEqual(s["barkod"], "8690000000017")
        self.assertTrue(s["lot_no"])
        d.alis_fatura_hucre_uygula(idx, "birim", "Paket")
        self.assertEqual(Decimal(d.satirlar[idx]["birim_alis_fiyati"]), Decimal("40"))
        d.alis_fatura_hucre_uygula(idx, "iskonto", "10+5")
        self.assertEqual(Decimal(d.satirlar[idx]["iskonto_orani_2"]), Decimal("5"))
        with self.assertRaises(ValueError):
            d.alis_fatura_hucre_uygula(idx, "iskonto", "1+2+3+4")
        d.satirlar[idx]["irsaliye_satiri_id"] = 3
        with self.assertRaises(ValueError):
            d.alis_fatura_hucre_uygula(idx, "birim", "Adet")
        self.assertFalse(d._alis_fatura_urun_degistir(idx, ("MB001", "Birim Ürün", "Adet")))
        d._satir_ici_giris.ac("kod", "yarım")
        d._alis_editorleri_uygula()
        self.assertEqual(len(d.satirlar), 1)
        self.assertEqual(d.satir_tablosu.get_children()[-1], YENI_SATIR_IID)
        d.destroy()

    def test_alis_iade_kaynak_satiri_kilitli_miktar_duzenlenir(self):
        from alis_ui import AlisIadeFaturasiDialog

        d = AlisIadeFaturasiDialog(self.root)
        d.withdraw()
        d.satirlar.append({
            "kaynak_fatura_satiri_id": 4, "urun_kodu": "MB001", "urun_adi": "Birim Ürün",
            "miktar": Decimal("5"), "birim": "Adet", "birim_fiyat": Decimal("1"),
            "iskonto_orani": 0, "kdv_orani": 20,
        })
        d._satirlari_yenile()
        d.alis_hucre_uygula(0, "miktar", "2")
        self.assertEqual(d.satirlar[0]["miktar"], Decimal("2"))
        with self.assertRaises(ValueError):
            d.alis_hucre_uygula(0, "birim", "Paket")
        self.assertEqual(d.satir_tablosu.get_children()[-1], YENI_SATIR_IID)
        d.destroy()


class TeklifSatirGirisiTest(_GirisTemel):
    def test_teklif_satir_ici_ekleme_barkod_hucre_ve_kilit(self):
        from types import SimpleNamespace

        from teklif_ui import TeklifDialog

        with patch("ui_pencere.belge_penceresini_hazirla", lambda win, **_k: (win.withdraw(), {})[1]):
            d = TeklifDialog(self.root)
        d.withdraw()
        self.assertFalse(hasattr(d, "urun_kod"))
        self.assertEqual(d.satir_tablo.get_children(), (YENI_SATIR_IID,))
        deg = ("MB001", "Birim Ürün", "Adet", "0", "1", "Stok Kartı", "20", None)
        idx = d._teklif_urun_ekle(deg, None)
        self.assertIsNone(d.satirlar[idx]["teklif_fiyati"])
        self.assertTrue(d.satirlar[idx]["yeniden_hesaplanmali"])
        d._teklif_urun_ekle(deg, None)
        self.assertEqual(len(d.satirlar), 2)
        d._satir_ici_giris.son_islem = "barkod"
        d._teklif_urun_ekle(deg, None)
        d._satir_ici_giris.son_islem = "secim"
        self.assertEqual(len(d.satirlar), 2)
        self.assertEqual(d.satirlar[0]["miktar"], Decimal("2"))

        d.teklif_hucre_uygula(1, "birim", "Paket")
        self.assertEqual(Decimal(d.satirlar[1]["birim_carpani"]), Decimal("100"))
        d.teklif_hucre_uygula(1, "fiyat", "50")
        d.teklif_hucre_uygula(1, "isk", "10")
        self.assertEqual(Decimal(d.satirlar[1]["net_birim_fiyat"]), Decimal("45"))
        self.assertTrue(d.satirlar[1]["is_manual_price"])
        with self.assertRaises(ValueError):
            d.teklif_hucre_uygula(1, "miktar", "0")
        self.assertEqual(d.satirlar[1]["miktar"], Decimal("1"))

        self.assertEqual(d._teklif_urun_ekle(deg, 0), 0)
        self.assertEqual(len(d.satirlar), 3)
        d._satir_ici_giris.ac("ad", "yarım")
        self.assertTrue(d._teklif_bekleyenleri_uygula())
        self.assertEqual(len(d.satirlar), 3)
        self.assertEqual(d.satir_tablo.get_children()[-1], YENI_SATIR_IID)

        d.teklif = SimpleNamespace(durum="İPTAL", siparis_id=None)
        d._buton_durumlari()
        self.assertFalse(d.satir_tablo.exists(YENI_SATIR_IID))
        self.assertIsNone(d._teklif_urun_ekle(deg, None))
        d.destroy()


class CiktiGirisSatiriTest(_GirisTemel):
    def test_giris_satiri_ciktiya_ve_musteri_gorunumune_girmez(self):
        from invoice_print.service import InvoicePrintService
        from teklif_print import musteri_teklif_html_uret
        from teklif_ui import TeklifDialog

        with patch("ui_pencere.belge_penceresini_hazirla", lambda win, **_k: (win.withdraw(), {})[1]):
            t = TeklifDialog(self.root)
        t.withdraw()
        t._teklif_urun_ekle(("MB001", "Birim Ürün", "Adet", "0", "1", "Stok Kartı", "20", None), None)
        t.teklif_hucre_uygula(0, "fiyat", "5")
        t._satir_ici_giris.ac("ad", "yazılıp seçilmedi")
        self.assertTrue(t.satir_tablo.exists(YENI_SATIR_IID))
        with patch("invoice_print.branding.logo_data_uri", return_value=None):
            _, html = musteri_teklif_html_uret(t)
        self.assertIn("Birim Ürün", html)
        for metin in ("Ürün ekle", "yazılıp seçilmedi", "F10"):
            self.assertNotIn(metin, html)
        t.destroy()

        import app

        f = app.SatisFaturasiDialog(self.root, cari=self._cari())
        f.withdraw()
        f._satir_ici_giris.urun_ekle_fn(("MB001", "Birim Ürün", "Adet", "0", "1", "Stok Kartı", "20", None), None)
        self.assertTrue(f.satir_tablosu.exists(YENI_SATIR_IID))
        vm = InvoicePrintService.build_from_kart(f)
        self.assertEqual(len(vm.satirlar), 1)
        self.assertNotIn("Ürün ekle", str(vm))
        f.destroy()


class SatinAlmaSatirGirisiTest(_GirisTemel):
    DEG = ("MB001", "Birim Ürün", "Adet", "0", "1", "Stok Kartı", "20", None)

    def test_talep_satir_ici_ekleme_hucre_ve_kayit(self):
        from database.satin_alma_talep_service import SatinAlmaTalepService
        from satin_alma_ui import SatinAlmaTalepDialog

        d = SatinAlmaTalepDialog(self.root)
        d.withdraw()
        self.assertFalse(hasattr(d, "kod"))
        self.assertEqual(d.satir_tablosu.get_children(), (YENI_SATIR_IID,))
        d._urun_ekle(self.DEG, None)
        d._satir_ici_giris.son_islem = "barkod"
        d._urun_ekle(self.DEG, None)
        d._satir_ici_giris.son_islem = "secim"
        self.assertEqual(len(d.satirlar), 1)
        self.assertEqual(d.satirlar[0]["miktar"], Decimal("2"))
        d.hucre_uygula(0, "birim", "Paket")
        d.hucre_uygula(0, "aciklama", "acil")
        with self.assertRaises(ValueError):
            d.hucre_uygula(0, "miktar", "-1")
        d._satir_ici_giris.ac("ad", "yarım")
        no = d.no.get()
        d._kaydet()
        talep = next(t for t in SatinAlmaTalepService.listele() if t["talep_no"] == no)
        self.assertEqual(talep["satir_adet"], 1)
        satir = SatinAlmaTalepService.getir(talep["id"]).satirlar[0]
        self.assertEqual((satir.urun_kodu, satir.birim, satir.aciklama), ("MB001", "Paket", "acil"))
        self.assertEqual(satir.miktar, Decimal("2"))

    def test_tedarikci_teklifi_tedarikci_zorunlu_alis_fiyati(self):
        from types import SimpleNamespace

        from satin_alma_ui import TedarikciTeklifDialog

        d = TedarikciTeklifDialog(self.root)
        d.withdraw()
        self.assertIsNone(d._urun_ekle(self.DEG, None))
        self.assertEqual(d.satirlar, [])
        d.eslesme = {"T1 — Tedarikçi": SimpleNamespace(id=77)}
        d.cari.set("T1 — Tedarikçi")
        idx = d._urun_ekle(self.DEG, None)
        s = d.satirlar[idx]
        self.assertEqual((s["cari_id"], s["birim_fiyat"], s["termin_gun"]), (77, Decimal("0.4"), 7))
        d.hucre_uygula(idx, "birim", "Paket")
        self.assertEqual(d.satirlar[idx]["birim_fiyat"], Decimal("40.0000"))
        d.hucre_uygula(idx, "fiyat", "38,5")
        d.hucre_uygula(idx, "vade", "30")
        self.assertEqual((d.satirlar[idx]["birim_fiyat"], d.satirlar[idx]["vade_gun"]), (Decimal("38.5"), 30))
        with self.assertRaises(ValueError):
            d.hucre_uygula(idx, "termin", "2,5")
        self.assertEqual(d.satir_tablosu.set(d.satir_tablosu.get_children()[0], "tedarikci"), "T1 — Tedarikçi")
        self.assertEqual(d.satir_tablosu.get_children()[-1], YENI_SATIR_IID)
        d.destroy()


if __name__ == "__main__":
    unittest.main()
