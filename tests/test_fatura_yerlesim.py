"""Satış faturası birleşik yerleşim: sabit üst bölüm, genişleyen ürün tablosu, sabit alt detay.

Boyutlar Windows %100 / %125 ölçeklemesinin mantıksal iç alanlarıdır:
1366×768 → 1366×705 (%100), 1093×560 (%125); 1920×1080 → 1920×1000 (%100), 1536×832 (%125).
"""

from __future__ import annotations

import datetime
import sys
import tkinter as tk
import unittest
from decimal import Decimal
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.database import get_session
from tests import test_uzlasma_net_cari as _uz

BOYUTLAR = ((1366, 705), (1093, 560), (1920, 1000), (1536, 832))
UZUN_NOT = "\n".join(f"{i:02d}. satır — teslimat ve ödeme koşulları hakkında uzun açıklama." for i in range(1, 25))


def _satir(i: int) -> dict:
    return {
        "urun_kodu": "U001", "urun_adi": f"Masa {i}", "miktar": "1", "birim": "Adet",
        "birim_satis_fiyati": "100", "kdv_orani": "20", "iskonto_orani": "0",
        "iskonto_orani_2": "0", "iskonto_orani_3": "0", "satir_para_birimi": "TRY", "kur": "1",
    }


def _tahsilat(i: int) -> dict:
    return {
        "tahsilat_tarihi": datetime.date(2026, 10, 1), "tutar": Decimal("100") * (i + 1),
        "odeme_sekli": "Nakit", "hesap": "Merkez Kasa", "aciklama": f"Tahsilat {i + 1}",
    }


def _metin(w) -> str:
    try:
        return str(w.cget("text"))
    except tk.TclError:
        return ""


def _menu_etiketleri(menu: tk.Menu) -> list[str]:
    son = menu.index("end")
    if son is None:
        return []
    return [menu.entrycget(i, "label") for i in range(son + 1) if menu.type(i) != "separator"]


class FaturaYerlesimTest(unittest.TestCase):
    def setUp(self):
        _uz._kurulum(self)
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:
            _uz._sokum(self)
            self.skipTest(f"Tk yok: {hata}")
        self.root.geometry("+20+20")
        self.root.attributes("-alpha", 0.0)
        self._yamalar = [
            patch("satis_personeli_ui.aktif_satis_personelleri", return_value=[]),
            patch("satis_personeli_ui.satis_personeli_degistirme_yetkisi", return_value=True),
            patch("fatura_acilis_cache.satis_personelleri", return_value=[]),
            patch("fatura_manuel_fiyat_ui.fiyat_degistirme_yetkisi", return_value=True),
            patch("fatura_manuel_fiyat_ui.maliyet_alti_kontrol", return_value=True),
        ]
        for y in self._yamalar:
            y.start()
        self.dlg = None

    def tearDown(self):
        try:
            if self.dlg is not None:
                self.dlg.destroy()
        except Exception:
            pass
        for y in reversed(self._yamalar):
            y.stop()
        try:
            self.root.destroy()
        except Exception:
            pass
        _uz._sokum(self)

    def _pompala(self, tur=12):
        for _ in range(tur):
            self.dlg.update_idletasks()
            self.dlg.update()

    def _ac(self, *, fatura=None, satir_sayisi=25, tahsilat_sayisi=0, notu=None, sinif=None):
        import app

        if self.dlg is not None:
            try:
                self.dlg.destroy()
            except Exception:
                pass
        if sinif is not None:
            self.dlg = sinif(self.root, cari=self.musteri_id)
        elif fatura is not None:
            self.dlg = app.SatisFaturasiDialog(self.root, fatura=fatura)
        else:
            self.dlg = app.SatisFaturasiDialog(self.root, cari=app.CariService.getir(self.musteri_id))
        if fatura is None:
            self.dlg.satirlar = [_satir(i) for i in range(1, satir_sayisi + 1)]
            self.dlg._satir_listesini_yenile()
        if tahsilat_sayisi:
            self.dlg.tahsilatlar = [_tahsilat(i) for i in range(tahsilat_sayisi)]
            self.dlg._tahsilat_listesini_yenile()
        self.dlg._toplamlari_guncelle()
        if notu is not None:
            self.dlg._fatura_notu_yaz(notu)
        self.dlg.attributes("-alpha", 0.0)
        self._pompala()
        return self.dlg

    def _boyutla(self, g, y):
        self.dlg.state("normal")
        self.dlg.geometry(f"{g}x{y}+0+0")
        self._pompala(16)

    def _icinde(self, w, ad):
        d = self.dlg
        self.assertTrue(w.winfo_ismapped(), f"{ad} görünmüyor")
        sag = d.winfo_rootx() + d.winfo_width()
        alt = d.winfo_rooty() + d.winfo_height()
        self.assertLessEqual(w.winfo_rootx() + w.winfo_width(), sag + 1, f"{ad} sağdan taşıyor")
        self.assertLessEqual(w.winfo_rooty() + w.winfo_height(), alt + 1, f"{ad} alttan taşıyor")
        if isinstance(w, (tk.Button, tk.Menubutton, tk.Label, ttk.Button, ttk.Label)):
            self.assertGreaterEqual(w.winfo_width(), w.winfo_reqwidth() - 2, f"{ad} kırpılmış")

    def _ana_dugmeler(self):
        d = self.dlg
        return {
            "Kaydet": d.kaydet_btn,
            "Onayla ve Yeni": d.kaydet_onay_btn,
            "Tahsilat Makbuzu": d._tahsilat_makbuzu_btn,
            "Yazdır / PDF": d._yazdir_mb,
            "Diğer İşlemler": d._diger_mb,
            "Kapat": next(
                w for w in d._fatura_toolbar["sag"].winfo_children() if _metin(w) == "Kapat (Esc)"
            ),
        }

    def _yerlesimi_dogrula(self, g, y, *, tahsilat=False):
        d = self.dlg
        self._boyutla(g, y)
        for ad, w in self._ana_dugmeler().items():
            self._icinde(w, ad)
        refs = d._fatura_alt_ozet
        self._icinde(refs["degerler"]["genel"], "Net Toplam")
        self._icinde(d._fatura_detay["nb"], "Notlar/Tahsilatlar")
        for anahtar, w in d._fatura_detay["ozet_etiketleri"].items():
            self._icinde(w, f"özet {anahtar}")
        n = refs["not_alani"]
        if not tahsilat:
            self._icinde(n, "Not kutusu")
            self._icinde(n.not_buyut_btn, "Notu büyüt")
            satir_px = int(n.tk.call("font", "metrics", n.cget("font"), "-linespace"))
            self.assertGreaterEqual(n.winfo_height(), 4 * satir_px, "not en az 4 satır göstermeli")
        # Ürün tablosu: başlık + en az bir satır görünür; form kaydırması yok
        tablo = d.satir_tablosu
        self._icinde(tablo, "Ürün tablosu")
        self.assertGreaterEqual(tablo.winfo_height(), 60, "ürün satırları görünür kalmalı")
        self.assertEqual(d.canvas.yview(), (0.0, 1.0), "ana form kaydırılmamalı")
        # Üst bilgi panellerindeki düğmeler kırpılmadan görünür
        for panel in d._fatura_ust_panel.winfo_children():
            if not isinstance(panel, ttk.LabelFrame) or not panel.winfo_ismapped():
                continue
            panel_sag = panel.winfo_rootx() + panel.winfo_width()
            yigin = list(panel.winfo_children())
            while yigin:
                w = yigin.pop()
                yigin.extend(w.winfo_children())
                if isinstance(w, ttk.Button) and w.winfo_ismapped():
                    self.assertLessEqual(
                        w.winfo_rootx() + w.winfo_width(), panel_sag + 1,
                        f"{_metin(w)} düğmesi panelden taşıyor",
                    )
                    self.assertGreaterEqual(w.winfo_width(), w.winfo_reqwidth() - 2,
                                            f"{_metin(w)} düğmesi kırpılmış")

    # —— yerleşim, farklı çözünürlük ve ölçekleme ——
    def test_yeni_fatura_cok_satir_uzun_not(self):
        self._ac(notu=UZUN_NOT)
        for g, y in BOYUTLAR:
            with self.subTest(boyut=f"{g}x{y}"):
                self._yerlesimi_dogrula(g, y)
        n = self.dlg._fatura_alt_ozet["not_alani"]
        self.assertEqual(n.not_kaydirma.winfo_manager(), "pack", "uzun not kendi içinde kaymalı")

    def test_coklu_tahsilat_sekmesi(self):
        self._ac(tahsilat_sayisi=4)
        d = self.dlg
        nb = d._fatura_detay["nb"]
        self.assertEqual(nb.tab(d._fatura_detay["tab_tahsilat"], "text"), "Tahsilatlar (4)")
        nb.select(d._fatura_detay["tab_tahsilat"])
        for g, y in BOYUTLAR:
            with self.subTest(boyut=f"{g}x{y}"):
                self._yerlesimi_dogrula(g, y, tahsilat=True)
                self._icinde(d.tahsilat_tablosu, "Tahsilat tablosu")
                self.assertFalse(d._fatura_alt_ozet["not_alani"].not_buyut_btn.winfo_ismapped())
        et = d._fatura_detay["ozet_etiketleri"]
        self.assertEqual(_metin(et["tahsil"]), "1.000,00 TL")
        self.assertEqual(_metin(et["kalan"]), "2.000,00 TL")
        self.assertEqual(_metin(et["durum"]), "Kısmi ödendi")
        self.assertEqual(len(d.tahsilat_tablosu.get_children()), 4)

    def test_kaydedilip_yeniden_acilan_ve_onayli_fatura(self):
        from database.models.satis_faturasi import SatisFaturasi
        from database.satis_faturasi_service import SatisFaturasiService

        self._ac(satir_sayisi=12, tahsilat_sayisi=2, notu=UZUN_NOT)
        veriler, satirlar = self.dlg._fatura_kayit_verilerini_topla()
        f = SatisFaturasiService.kaydet(veriler, satirlar, None)
        self._ac(fatura=SatisFaturasiService.getir(f.id))
        self.assertEqual(self.dlg._fatura_alt_ozet["not_alani"].get("1.0", "end-1c"), UZUN_NOT)
        self.assertEqual(len(self.dlg.satirlar), 12)
        for g, y in ((1366, 705), (1093, 560)):
            with self.subTest(durum="yeniden açılan", boyut=f"{g}x{y}"):
                self._yerlesimi_dogrula(g, y)
        with get_session() as s:
            kayit = s.get(SatisFaturasi, f.id)
            kayit.onaylandi = True
            kayit.durum = "ONAYLANDI"
        self._ac(fatura=SatisFaturasiService.getir(f.id))
        self.assertTrue(self.dlg._fatura_kilitli)
        self.assertEqual(str(self.dlg._fatura_alt_ozet["not_alani"].cget("state")), "disabled")
        for g, y in ((1366, 705), (1093, 560), (1920, 1000)):
            with self.subTest(durum="onaylı", boyut=f"{g}x{y}"):
                self._yerlesimi_dogrula(g, y)

    # —— ana işlemler ve menüler ——
    def test_yazdir_menusu_ve_kisayollar(self):
        self._ac(satir_sayisi=2)
        d = self.dlg
        etiketler = _menu_etiketleri(d._yazdir_menu)
        for beklenen in ("Önizleme", "Yazdır…", "PDF Kaydet…", "E-posta İçin PDF…", "Yazdırma Ayarları…"):
            self.assertIn(beklenen, etiketler)
        for kisayol in ("<Control-p>", "<Control-e>", "<Control-Shift-P>", "<F1>", "<F3>", "<F4>"):
            self.assertTrue(d.bind(kisayol), f"{kisayol} kısayolu bağlı değil")
        ust_metinler = [_metin(w) for w in d._fatura_toolbar["sag"].winfo_children()]
        for eski in ("Önizleme", "Yazdır", "PDF", "Siparişten Getir (Alt+S)"):
            self.assertNotIn(eski, ust_metinler)

    def test_sirit_ve_satir_islemleri(self):
        self._ac(satir_sayisi=3)
        d = self.dlg
        serit = []
        yigin = [d._urun_secim_serit]
        while yigin:
            w = yigin.pop()
            yigin.extend(w.winfo_children())
            serit.append(_metin(w))
        self.assertEqual(serit.count("Siparişten Getir (Alt+S)"), 1)
        self.assertEqual(serit.count("Satır Sil"), 1)
        self.assertNotIn("Vazgeç", serit)
        self.assertIsNone(getattr(d, "_satir_arac_cubugu", None), "alt işlev çubuğu kaldırıldı")
        menu = d._satir_islemleri_menu
        d.tk.eval(menu.cget("postcommand"))
        etiketler = _menu_etiketleri(menu)
        for beklenen in (
            "Satırı Düzenle (F2)", "Satırı Çoğalt (Ctrl+D)", "Üste Taşı (Alt+↑)", "Alta Taşı (Alt+↓)",
            "Fiyatı Stok Kartından Yenile", "Fiyatı Kilitle / Dağıtıma Kapalı",
            "Çoklu İskonto Düzenle", "İskontoyu Temizle", "Satır Açıklaması Gir",
            "Satır Sil (Del)", "Kolon Ayarları…",
        ):
            self.assertIn(beklenen, etiketler)
        baglam = _menu_etiketleri(d._satir_ctx)
        self.assertIn("Satır Sil (Del)", baglam)
        self.assertNotIn("Seçili Satırı Sil", baglam)
        self.assertEqual(_menu_etiketleri(d._satir_kolon_ctx), ["Kolon Ayarları…"])

    def test_mesaj_paneli_kompakt_hata_gelince_acilir(self):
        from fatura_mesaj_paneli import panel_mesaj_ekle

        self._ac(satir_sayisi=2)
        d = self.dlg
        self.assertTrue(d._mesaj_panel_dis.winfo_ismapped())
        self.assertFalse(d._mesaj_panel_ic.winfo_ismapped(), "boş mesaj paneli kapalı olmalı")
        self.assertLess(d._mesaj_panel_dis.winfo_height(), 32)
        with patch("fatura_barkod_ui._barkod_odak"):
            panel_mesaj_ekle(d, None, teknik_uyari="Test hatası: kayıt yazılamadı")
        self._pompala()
        self.assertTrue(d._mesaj_panel_ic.winfo_ismapped(), "hata gelince panel açılmalı")
        self.assertIn("(1)", _metin(d._mesaj_baslik_lbl))
        self.assertIn("Test hatası", _metin(d._mesaj_son_lbl))

    def test_iade_ekraninda_notlar_ve_toplamlar_kalir(self):
        import app

        self._ac(sinif=app.SatisIadeFaturasiDialog)
        d = self.dlg
        detay = d._fatura_detay
        self.assertEqual(str(detay["nb"].tab(detay["tab_tahsilat"], "state")), "hidden")
        self.assertFalse(detay["ozet"].winfo_ismapped())
        for g, y in ((1366, 705), (1920, 1000)):
            with self.subTest(boyut=f"{g}x{y}"):
                self._boyutla(g, y)
                self._icinde(d._fatura_alt_ozet["not_alani"], "Not kutusu")
                self._icinde(d._fatura_alt_ozet["degerler"]["genel"], "Net Toplam")
                self._icinde(d.kaydet_btn, "Kaydet")
                self.assertGreater(d.satir_tablosu.winfo_height(), 30)
        gizli = [
            w for w in d._fatura_alt_ozet["sag"].winfo_children()
            if _metin(w) in ("İndirim", "Masraf")
        ]
        self.assertTrue(gizli)
        self.assertFalse(any(w.winfo_ismapped() for w in gizli))


if __name__ == "__main__":
    unittest.main()
