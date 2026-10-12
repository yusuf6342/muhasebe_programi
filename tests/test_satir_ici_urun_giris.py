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


_TIK_ZAMANI = [1_000_000]


def cift_tik(w, x: int, y: int) -> None:
    """event generate <Double-1> kabul etmez; aynı noktada iki hızlı tık üretilir."""
    _TIK_ZAMANI[0] += 10_000
    t = _TIK_ZAMANI[0]
    for i in range(2):
        w.event_generate("<ButtonPress-1>", x=x, y=y, time=t + i * 80)
        w.event_generate("<ButtonRelease-1>", x=x, y=y, time=t + i * 80 + 20)


def _odak(pencere):
    """Penceredeki son odak (paralel koşuda uygulama arka planda kalsa da focus_set sonucunu verir)."""
    yol = str(pencere.tk.call("focus", "-lastfor", str(pencere)))
    try:
        return pencere.nametowidget(yol)
    except KeyError:
        return None


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
        giris.ac("barkod", "8690000000017")
        giris._enter()
        self.assertEqual([e[0] for e in eklenen], ["MB001"])
        self.assertEqual(giris.son_islem, "secim")
        giris.ac("barkod", "0000000000000")
        with patch.object(giris, "_durum_yaz") as durum:
            giris._barkod("0000000000000")
        self.assertEqual(len(eklenen), 1)
        self.assertIn("0000000000000", str(durum.call_args))
        pen.destroy()

    def test_yalniz_barkod_ve_ad_kutusu_kod_bilgi_amacli(self):
        pen, tablo, giris, eklenen, _ = self._kur()
        self.assertEqual(giris._roller(), ["barkod", "ad"])
        self.assertEqual(giris.kolonlar, {"barkod": "kod", "ad": "ad"})
        self.assertEqual(tablo.set(YENI_SATIR_IID, "kod"), "▦ Barkod okutun")
        self.assertIn("Ürün adı", tablo.set(YENI_SATIR_IID, "ad"))
        giris.ac("kod", "")
        self.assertEqual(giris._rol, "ad")
        giris.ac("ad", "MB001")
        giris._enter()
        self.assertEqual([e[0] for e in eklenen], ["MB001"])
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

    def test_alis_faturasi_birim_listesinde_yalniz_stok_kartinin_birimleri(self):
        from alis_ui import AlisFaturasiDialog
        from birim_secim_ui import GENEL_BIRIMLER
        from database.stok_service import StokService
        from fatura_satir_birim_service import stok_aktif_birimleri

        d = AlisFaturasiDialog(self.root)
        d.withdraw()
        idx = d._alis_fatura_urun_ekle(("MB001", "Birim Ürün", "Adet", "0", "1", "Stok Kartı", "20", None), None)
        kart = stok_aktif_birimleri("MB001")
        self.assertEqual(d._alis_fatura_birimleri(idx), kart)
        disari = [b for b in GENEL_BIRIMLER if b.casefold() not in {k.casefold() for k in kart}]
        self.assertTrue(disari)
        for b in disari:
            self.assertNotIn(b, d._alis_fatura_birimleri(idx))

        with patch("database.access.yazma_zorunlu"):
            StokService.kart_birimi_ekle("MB001", "Bidon", "5")
        self.assertEqual(d._alis_fatura_birimleri(idx), kart + ["Bidon"])

        d.satirlar.append({"urun_kodu": "", "urun_adi": "Serbest", "birim": "Adet"})
        kartsiz = d._alis_fatura_birimleri(len(d.satirlar) - 1)
        for b in ("Adet", "Kg", "Koli", "Metre"):
            self.assertIn(b, kartsiz)
        d.destroy()

    def test_alis_faturasi_satirda_sag_sol_ok_ile_gezinme_ve_yazma(self):
        import time

        from alis_ui import AlisFaturasiDialog

        self.root.geometry("+-3000+-3000")
        self.root.deiconify()
        d = AlisFaturasiDialog(self.root)
        d.geometry("1500x800+-3000+-3000")
        idx = d._alis_fatura_urun_ekle(("MB001", "Birim Ürün", "Adet", "0", "1", "Stok Kartı", "20", None), None)

        def pompala(sure=0.15):
            bitis = time.time() + sure
            while time.time() < bitis:
                d.update()

        def hedef():
            kutular = getattr(d._hucre.editor, "kutular", None)
            if not kutular:
                return d._hucre.editor
            odak = _odak(d)
            return odak if odak in kutular else kutular[0]

        def tus(t):
            w = hedef()
            w.focus_force()
            pompala(0.05)
            w.event_generate(t)
            pompala()

        pompala(0.3)
        hucre = d._hucre
        sira = [k for k in hucre.sira if hucre.duzenlenebilir_mi(idx, k) is True]
        for kolon in ("aciklama", "miktar", "birim", "fiyat", "iskonto", "kdv"):
            self.assertIn(kolon, sira)
        hucre.duzenle(idx, sira[0])
        pompala()
        hucre.editor.delete(0, "end")
        hucre.editor.insert(0, "Hasarlı koli")
        for kolon in sira[1:]:
            tus("<Right>")
            self.assertIsNotNone(hucre.editor, f"{kolon} hücresine geçilmedi")
            self.assertEqual(hucre._konum[1], kolon)
            if kolon == "iskonto":
                # üç ardışık iskonto kutusu: 1 → 2 → 3, sonra sonraki kolon
                kutular = hucre.editor.kutular
                self.assertEqual(len(kutular), 3)
                for i, deger in enumerate(("10", "5")):
                    self.assertIs(hedef(), kutular[i])
                    kutular[i].delete(0, "end")
                    kutular[i].insert(0, deger)
                    tus("<Right>")
                self.assertIs(hedef(), kutular[2])
                self.assertEqual(hucre._konum[1], "iskonto")
        for kolon in reversed(sira[:-1]):
            tus("<Left>")
            self.assertEqual(hucre._konum[1], kolon)
            if kolon == "iskonto":
                kutular = hucre.editor.kutular
                self.assertIs(hedef(), kutular[2], "geri gelişte son iskonto kutusu")
                tus("<Left>")
                tus("<Left>")
                self.assertIs(hedef(), kutular[0])
        hucre.kapat()
        s = d.satirlar[idx]
        self.assertEqual(s["aciklama"], "Hasarlı koli")
        self.assertEqual(Decimal(s["iskonto_orani"]), Decimal("10"))
        self.assertEqual(Decimal(s["iskonto_orani_2"]), Decimal("5"))
        # Editör kapalıyken seçili satırda sağ ok ilk, sol ok son hücreyi açar
        d.satir_tablosu.selection_set(d.satir_tablosu.get_children()[idx])
        d.satir_tablosu.focus_force()
        pompala(0.05)
        d.satir_tablosu.event_generate("<Right>")
        pompala()
        self.assertEqual(hucre._konum[1], sira[0])
        hucre.kapat()
        d.satir_tablosu.focus_force()
        pompala(0.05)
        d.satir_tablosu.event_generate("<Left>")
        pompala()
        self.assertEqual(hucre._konum[1], sira[-1])
        hucre.kapat()
        d.destroy()

    def test_alis_iade_kaynak_satiri_kilitli_miktar_duzenlenir(self):
        """Alış iadesi ayrı ekranda: satır düzenleme diyaloğu; kaynak bağlantısı korunur."""
        from alis_ui import AlisIadeFaturasiDialog

        d = AlisIadeFaturasiDialog(self.root)
        d.withdraw()
        d.satirlar.append({
            "kaynak_fatura_satiri_id": 4, "urun_kodu": "MB001", "urun_adi": "Birim Ürün",
            "miktar": Decimal("5"), "birim": "Adet", "birim_fiyat": Decimal("1"),
            "iskonto_orani": 0, "kdv_orani": 20,
        })
        d._satirlari_ciz()

        class _Duzenle:
            def __init__(self, *_a, **_k):
                self.result = {"miktar": Decimal("2"), "birim": "Adet", "birim_fiyat": Decimal("1"),
                               "iskonto_orani": Decimal("0"), "iskonto_orani_2": Decimal("0"),
                               "iskonto_orani_3": Decimal("0"), "kdv_orani": Decimal("20")}

        d.tablo.selection_set("0")
        with patch("alis_iade_ui.SatirDuzenleDialog", _Duzenle), patch.object(d, "wait_window"), \
                patch("alis_iade_ui.messagebox"):
            d.satir_duzenle()
        self.assertEqual(d.satirlar[0]["miktar"], Decimal("2"))
        self.assertEqual(d.satirlar[0]["kaynak_fatura_satiri_id"], 4)
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


class EvrakUrunAramaAlanlariTest(_GirisTemel):
    """Her evrakta yalnız barkod + ürün adı kutusu; barkod okutma, birleşme ve ad araması."""

    BARKOD = "8690000000017"

    def _kartlar(self):
        import app
        from alis_ui import AlisFaturasiDialog, AlisIrsaliyesiDialog, AlisSiparisiDialog
        from satin_alma_ui import SatinAlmaTalepDialog
        from satis_irsaliyesi_ui import SatisIrsaliyesiDialog
        from satis_siparisi_ui import SatisSiparisiKarti
        from teklif_ui import TeklifDialog

        return [
            ("Satış faturası", lambda: app.SatisFaturasiDialog(self.root, cari=self._cari()), "barkod"),
            ("Satıştan iade", lambda: app.SatisIadeFaturasiDialog(self.root, cari=self._cari()), "barkod"),
            ("Alış faturası", lambda: AlisFaturasiDialog(self.root), "barkod"),
            ("Alış siparişi", lambda: AlisSiparisiDialog(self.root), "kod"),
            ("Alış irsaliyesi", lambda: AlisIrsaliyesiDialog(self.root), "kod"),
            ("Satış irsaliyesi", lambda: SatisIrsaliyesiDialog(self.root), "kod"),
            ("Alınan sipariş", lambda: SatisSiparisiKarti(self.root, cari=self._cari()), "kod"),
            ("Teklif", lambda: TeklifDialog(self.root), "kod"),
            ("Satın alma talebi", lambda: SatinAlmaTalepDialog(self.root), "kod"),
        ]

    def test_her_evrakta_barkod_ve_ad_aramasi(self):
        with patch("ui_pencere.belge_penceresini_hazirla", lambda win, **_k: (win.withdraw(), {})[1]), \
                patch("tkinter.messagebox.showinfo"), patch("tkinter.messagebox.showwarning"), \
                patch("tkinter.messagebox.showerror"), patch("tkinter.messagebox.askyesno", return_value=True):
            for ad, yap, barkod_kolonu in self._kartlar():
                with self.subTest(evrak=ad):
                    d = yap()
                    d.withdraw()
                    g = d._satir_ici_giris
                    self.assertEqual(sorted(g.kolonlar), ["ad", "barkod"])
                    self.assertEqual(g.kolonlar["barkod"], barkod_kolonu)
                    self.assertNotIn("kod", g._roller())
                    for kolon, rol in g.kolon_rol.items():
                        self.assertIn(rol, ("barkod", "ad"), kolon)
                    if "iade" in ad.casefold():
                        d.destroy()
                        continue

                    satirlar = d.satirlar
                    # İki bilinçli okutma: çift tetikleme penceresinin dışında (bkz. SatisFaturasiBarkodCiftTetiklemeTest)
                    saat = _SahteSaat()
                    with patch("fatura_barkod_ui.time", saat):
                        g.ac("barkod", self.BARKOD)
                        g._enter()
                        saat.ileri_ms(1000)
                        g.ac("barkod", self.BARKOD)
                        g._enter()
                    self.assertEqual(len(satirlar), 1, "aynı barkod yeni satır açmamalı")
                    self.assertEqual(Decimal(str(satirlar[0]["miktar"])), Decimal("2"))

                    with patch.object(g, "miktara_git", None), patch.object(g, "sadece_stokta_ad", False):
                        g.ac("ad", "birim ürün")
                        g._enter()
                    toplam = sum(Decimal(str(s["miktar"])) for s in satirlar if s.get("urun_kodu") == "MB001")
                    self.assertEqual(toplam, Decimal("3"), "ürün adıyla seçilen ürün evraka aktarılmalı")
                    self.assertEqual(d.satir_tablosu.get_children()[-1] if hasattr(d, "satir_tablosu")
                                     else d.satir_tablo.get_children()[-1], YENI_SATIR_IID)
                    d.destroy()


class _SahteSaat:
    """``fatura_barkod_ui.time`` yerine: ``time()`` saniye döner, test elle ilerletir."""

    def __init__(self, baslangic_sn: float = 1000.0):
        self.sn = baslangic_sn

    def time(self) -> float:
        return self.sn

    def ileri_ms(self, ms: float) -> None:
        self.sn += ms / 1000.0


class SatisFaturasiBarkodCiftTetiklemeTest(_GirisTemel):
    """Aynı barkod: ``fatura_barkod_ui._DEBOUNCE_MS`` (90 ms) içinde ikinci okuma çift tetiklemedir.

    Kural ``(simdi - son_ms) < _DEBOUNCE_MS``: 0–89 ms arası yok sayılır, tam 90 ms ve sonrası
    ayrı okumadır. Saat sahte olduğu için sonuç makine hızına bağlı değildir.
    """

    BARKOD = EvrakUrunAramaAlanlariTest.BARKOD

    def _iki_okuma(self, arada_ms: float):
        import app
        import fatura_barkod_ui

        self.assertEqual(fatura_barkod_ui._DEBOUNCE_MS, 90)
        saat = _SahteSaat()
        with patch("ui_pencere.belge_penceresini_hazirla", lambda win, **_k: (win.withdraw(), {})[1]), \
                patch("fatura_barkod_ui.time", saat):
            d = app.SatisFaturasiDialog(self.root, cari=self._cari())
            d.withdraw()
            g = d._satir_ici_giris
            g.ac("barkod", self.BARKOD)
            g._enter()
            saat.ileri_ms(arada_ms)
            g.ac("barkod", self.BARKOD)
            g._enter()
            satirlar = [dict(s) for s in d.satirlar]
            d.destroy()
        return satirlar

    def test_90ms_icinde_ikinci_okuma_cift_tetiklemedir_miktar_1(self):
        for arada in (0, 40, 89):
            with self.subTest(arada_ms=arada):
                satirlar = self._iki_okuma(arada)
                self.assertEqual(len(satirlar), 1)
                self.assertEqual(Decimal(str(satirlar[0]["miktar"])), Decimal("1"))

    def test_90ms_ve_sonrasi_iki_ayri_okumadir_ayni_satirda_miktar_2(self):
        for arada in (90, 91, 500):
            with self.subTest(arada_ms=arada):
                satirlar = self._iki_okuma(arada)
                self.assertEqual(len(satirlar), 1, "aynı barkod yeni satır açmamalı")
                self.assertEqual(Decimal(str(satirlar[0]["miktar"])), Decimal("2"))


class EvrakKlavyeOrtakTest(_GirisTemel):
    """Muadil evraklar: stok kartı (çift tık / F2), ↑↓ satır gezinme, üçlü iskonto, üst alan Enter / ok."""

    DEG = ("MB001", "Birim Ürün", "Adet", "0", "1", "Stok Kartı", "20", None)

    def _pompala(self, d, sure=0.15):
        import time

        bitis = time.time() + sure
        while time.time() < bitis:
            d.update()

    def _ac(self, yap):
        self.root.geometry("1x1+-3000+-3000")
        self.root.deiconify()
        with patch("ui_pencere.belge_penceresini_hazirla", lambda win, **_k: {}):
            d = yap()
        d.geometry("1500x850+-3000+-3000")
        d.deiconify()
        self._pompala(d, 0.4)
        return d

    def _kartlar(self):
        from alis_ui import AlisFaturasiDialog, AlisIrsaliyesiDialog, AlisSiparisiDialog
        from satis_irsaliyesi_ui import SatisIrsaliyesiDialog
        from satis_siparisi_ui import SatisSiparisiKarti
        from teklif_ui import TeklifDialog

        return [
            ("Alış faturası", lambda: AlisFaturasiDialog(self.root), lambda d: d._alis_fatura_urun_ekle(self.DEG, None)),
            ("Alış siparişi", lambda: AlisSiparisiDialog(self.root), lambda d: d._alis_urun_ekle(self.DEG, None)),
            ("Alış irsaliyesi", lambda: AlisIrsaliyesiDialog(self.root), lambda d: d._alis_urun_ekle(self.DEG, None)),
            ("Satış irsaliyesi", lambda: SatisIrsaliyesiDialog(self.root),
             lambda d: d._satir_ici_giris.urun_ekle_fn(self.DEG, None)),
            ("Alınan sipariş", lambda: SatisSiparisiKarti(self.root, cari=self._cari()),
             lambda d: d._satir_ici_giris.urun_ekle_fn(self.DEG, None)),
            ("Teklif", lambda: TeklifDialog(self.root), lambda d: d._teklif_urun_ekle(self.DEG, None)),
        ]

    @staticmethod
    def _tablo(d):
        return getattr(d, "satir_tablosu", None) or d.satir_tablo

    def test_her_evrakta_f2_stok_karti_ve_ust_alan_gezinme(self):
        from evrak_baslik_gezinme import baslik_alanlari

        with patch("tkinter.messagebox.showinfo"), patch("tkinter.messagebox.showwarning"), \
                patch("tkinter.messagebox.showerror"), patch("tkinter.messagebox.askyesno", return_value=True):
            for ad, yap, ekle in self._kartlar():
                with self.subTest(evrak=ad):
                    d = self._ac(yap)
                    try:
                        ekle(d)
                        self._pompala(d)
                        tablo = self._tablo(d)
                        tablo.selection_set(veri_iidleri(tablo)[0])
                        tablo.focus_force()
                        self._pompala(d)
                        with patch("stok_ui.StokKartiDialog") as kart, patch.object(d, "kaydet") as kayit:
                            tablo.event_generate("<F2>")
                            self._pompala(d)
                        kart.assert_called_once()
                        self.assertEqual(kart.call_args.args[1].stok_kodu, "MB001")
                        kayit.assert_not_called()

                        alanlar = baslik_alanlari(d)
                        self.assertGreaterEqual(len(alanlar), 2, alanlar)
                        ilk, ikinci = alanlar[0], alanlar[1]
                        ilk.focus_force()
                        self._pompala(d, 0.05)
                        ilk.event_generate("<Down>")
                        self._pompala(d)
                        self.assertIs(_odak(d), ikinci)
                        ikinci.event_generate("<Up>")
                        self._pompala(d)
                        self.assertIs(_odak(d), ilk)
                        son = alanlar[-1]
                        son.focus_force()
                        self._pompala(d, 0.05)
                        son.event_generate("<Return>")
                        self._pompala(d, 0.3)
                        odak = _odak(d)
                        self.assertTrue(str(odak).startswith(str(tablo)), f"{ad}: son alandan sonra odak {odak}")
                    finally:
                        d.destroy()

    def test_alis_faturasi_ok_satir_gezinme_uclu_iskonto_ve_cift_tik(self):
        from alis_ui import AlisFaturasiDialog

        d = self._ac(lambda: AlisFaturasiDialog(self.root))
        try:
            i0 = d._alis_fatura_urun_ekle(self.DEG, None)
            d._satir_ici_giris.son_islem = "secim"
            d.satirlar.append(dict(d.satirlar[i0], miktar=Decimal("4")))
            d._satir_listesini_yenile()
            self._pompala(d, 0.3)
            hucre = d._hucre
            hucre.duzenle(0, "miktar")
            self._pompala(d)
            hucre.editor.delete(0, "end")
            hucre.editor.insert(0, "3")
            hucre.editor.focus_force()
            self._pompala(d, 0.05)
            hucre.editor.event_generate("<Down>")
            self._pompala(d)
            self.assertEqual(Decimal(d.satirlar[0]["miktar"]), Decimal("3"))
            self.assertEqual(hucre._konum, (1, "miktar"))
            hucre.editor.focus_force()
            self._pompala(d, 0.05)
            hucre.editor.event_generate("<Up>")
            self._pompala(d)
            self.assertEqual(hucre._konum, (0, "miktar"))
            # Üçlü iskonto: Enter ile 1 → 2 → 3, toplam yeniden hesaplanır
            hucre.duzenle(0, "iskonto")
            self._pompala(d)
            kutular = hucre.editor.kutular
            for kutu, deger in zip(kutular, ("10", "5", "2")):
                kutu.delete(0, "end")
                kutu.insert(0, deger)
                kutu.focus_force()
                self._pompala(d, 0.05)
                kutu.event_generate("<Return>")
                self._pompala(d)
            s = d.satirlar[0]
            self.assertEqual(
                (Decimal(s["iskonto_orani"]), Decimal(s["iskonto_orani_2"]), Decimal(s["iskonto_orani_3"])),
                (Decimal("10"), Decimal("5"), Decimal("2")),
            )
            self.assertNotEqual(hucre._konum[1] if hucre.editor else None, "iskonto")
            hucre.kapat()
            # Ürün adı hücresine çift tık stok kartını açar
            tablo = d.satir_tablosu
            bb = tablo.bbox(veri_iidleri(tablo)[0], "ad")
            self.assertTrue(bb)
            with patch("stok_ui.StokKartiDialog") as kart:
                cift_tik(tablo, bb[0] + bb[2] // 2, bb[1] + bb[3] // 2)
                self._pompala(d)
            kart.assert_called_once()
        finally:
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
