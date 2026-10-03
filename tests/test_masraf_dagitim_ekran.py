"""Masraf Dağıtımı ekranı: alt düğmeler + tablo başlıkları her boyut/ölçekte görünür; 1.500 TL uçtan uca akış.

MASRAF_EKRAN_KLASOR ortam değişkeni verilirse her boyut/ölçek için ekran görüntüsü kaydedilir.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_masraf_dagitim as md  # noqa: E402

BOYUTLAR = ((1024, 600), (1280, 720), (1920, 1080))
OLCEKLER = (1.0, 1.25, 1.5)
TEMEL_SCALING = 96 / 72


class MasrafDagitimEkranTest(md.MasrafDagitimTest):
    # Miras alınan servis testleri burada yeniden koşmasın
    locals().update({ad: None for ad in dir(md.MasrafDagitimTest) if ad.startswith("test_")})

    def _root(self):
        import tkinter as tk

        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("Tk yok")
        # Dialog transient olduğu için ana pencere gizlenirse dialog da gizlenir
        root.geometry("1x1+0+0")
        root.update()
        return root

    def _iki_alis_ve_kaynak(self):
        _f1, s1 = self._alis("U001", "100", "100", "LOT-A")
        _f2, s2 = self._alis("U002", "50", "100", "LOT-B", birim="Koli")
        kaynak_id, ks = self._gider("1500")
        return s1, s2, kaynak_id, ks

    def _maliyetler(self):
        return Decimal(str(self._lot("LOT-A").birim_maliyet)), Decimal(str(self._lot("LOT-B").birim_maliyet))

    @staticmethod
    def _gorunur_ve_icinde(pencere, w) -> str | None:
        if not (w.winfo_ismapped() and w.winfo_viewable()):
            return "görünmüyor"
        px, py = pencere.winfo_rootx(), pencere.winfo_rooty()
        pw, ph = pencere.winfo_width(), pencere.winfo_height()
        x, y = w.winfo_rootx(), w.winfo_rooty()
        if w.winfo_width() < 20 or w.winfo_height() < 15:
            return f"çok küçük ({w.winfo_width()}x{w.winfo_height()})"
        if x < px or y < py or x + w.winfo_width() > px + pw or y + w.winfo_height() > py + ph:
            return f"pencere dışında ({x},{y} {w.winfo_width()}x{w.winfo_height()} / {px},{py} {pw}x{ph})"
        return None

    @staticmethod
    def _gorunur_alt(w) -> int:
        """Ata çerçevelerin kırpması dahil, widget'ın ekranda görünen alt sınırı."""
        alt = w.winfo_rooty() + w.winfo_height()
        p = w.master
        while p is not None:
            alt = min(alt, p.winfo_rooty() + p.winfo_height())
            if p == w.winfo_toplevel():
                break
            p = p.master
        return alt

    def test_yerlesim_dugmeler_ve_basliklar_her_boyut_ve_olcekte_gorunur(self):
        from tkinter import ttk

        from database.masraf_dagitim_service import MasrafDagitimService
        from masraf_dagitim_ui import TABLO_STILI, MasrafDagitimDialog
        from satis_tema import BEYAZ, LACIVERT

        s1, s2, kaynak_id, ks = self._iki_alis_ve_kaynak()
        did = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [s1, s2], tutar="1500"))
        klasor = os.environ.get("MASRAF_EKRAN_KLASOR")
        root = self._root()
        hatalar: list[str] = []
        try:
            for olcek in OLCEKLER:
                root.tk.call("tk", "scaling", TEMEL_SCALING * olcek)
                for gen, yuk in BOYUTLAR:
                    etiket = f"{gen}x{yuk} %{int(olcek * 100)}"
                    with patch("masraf_dagitim_ui.messagebox"):
                        d = MasrafDagitimDialog(root, dagitim_id=did)
                    try:
                        d.geometry(f"{gen}x{yuk}+0+0")
                        d.lift()
                        d.update()
                        stil = ttk.Style(d)
                        self.assertNotEqual(str(stil.lookup(f"{TABLO_STILI}.Heading", "foreground")).lower(),
                                            BEYAZ.lower())
                        self.assertEqual(str(stil.lookup(f"{TABLO_STILI}.Heading", "foreground")).lower(),
                                         LACIVERT.lower())
                        for b, metin in ((d.onizle_btn, "Dağıtımı Hesapla"), (d.taslak_btn, "Taslağı Kaydet"),
                                         (d.onay_btn, "Onayla ve Uygula"), (d.kapat_btn, "Kapat"),
                                         (d.geri_btn, "Geri Al"), (d.iptal_btn, "Taslağı İptal Et"),
                                         (d.gecmis_btn, "Geçmiş")):
                            self.assertEqual(b.cget("text"), metin)
                            sorun = self._gorunur_ve_icinde(d, b)
                            if sorun:
                                hatalar.append(f"{etiket}: '{metin}' {sorun}")
                        for ad, tablo, ilk in (("kaynak", d.kaynak_tablo, "Seç"), ("alış", d.hedef_tablo, "Alış Faturası")):
                            self.assertEqual([str(x) for x in root.tk.splitlist(tablo.cget("show"))], ["headings"])
                            self.assertEqual(tablo.heading(tablo["columns"][0], "text"), ilk)
                            self.assertEqual(str(tablo.cget("style")), TABLO_STILI)
                            sorun = self._gorunur_ve_icinde(d, tablo)
                            if sorun:
                                hatalar.append(f"{etiket}: {ad} tablosu {sorun}")
                            elif tablo.identify_region(30, 5) != "heading":
                                hatalar.append(f"{etiket}: {ad} tablosunun başlık satırı çizilmiyor")
                            else:
                                kutu = tablo.bbox(tablo.get_children()[0])
                                alt_sinir = self._gorunur_alt(tablo)
                                if not kutu or alt_sinir < tablo.winfo_rooty() + kutu[1]:
                                    hatalar.append(f"{etiket}: {ad} tablosunun başlığı kırpılıyor")
                                elif alt_sinir < tablo.winfo_rooty() + kutu[1] + kutu[3]:
                                    hatalar.append(f"{etiket}: {ad} tablosunda ilk satır kırpılıyor")
                        self.assertEqual(len(d.hedef_tablo.get_children()), 2)
                        if klasor:
                            from PIL import ImageGrab

                            d.attributes("-topmost", True)
                            d.update()
                            time.sleep(0.4)
                            x, y = d.winfo_rootx(), d.winfo_rooty()
                            ImageGrab.grab(bbox=(x, y, x + d.winfo_width(), y + d.winfo_height())).save(
                                Path(klasor) / f"masraf_dagitim_{gen}x{yuk}_{int(olcek * 100)}.png"
                            )
                    finally:
                        d.destroy()
            # Varsayılan açılış boyutu ekrana sığar
            root.tk.call("tk", "scaling", TEMEL_SCALING)
            with patch("masraf_dagitim_ui.messagebox"):
                d = MasrafDagitimDialog(root, dagitim_id=did)
            try:
                d.update()
                self.assertLessEqual(d.winfo_width(), d.winfo_screenwidth())
                self.assertLessEqual(d.winfo_height(), d.winfo_screenheight())
                self.assertIsNone(self._gorunur_ve_icinde(d, d.onay_btn))
            finally:
                d.destroy()
        finally:
            root.destroy()
        self.assertEqual(hatalar, [], "\n".join(hatalar))

    def test_1500_tl_hesapla_taslak_tekrar_ac_onay_bir_kez(self):
        from database.masraf_dagitim_service import MasrafDagitimService, ZatenIslendi
        from masraf_dagitim_ui import MasrafDagitimDialog

        s1, s2, kaynak_id, ks = self._iki_alis_ve_kaynak()
        self.assertEqual(self._maliyetler(), (Decimal("100"), Decimal("100")))
        root = self._root()
        try:
            with patch("masraf_dagitim_ui.messagebox") as mb:
                mb.askyesno.return_value = True
                d = MasrafDagitimDialog(root)
                d.tarih.delete(0, "end")
                d.tarih.insert(0, md.TARIH_DAGITIM.strftime("%d.%m.%Y"))
                d.kaynak_ayarla(kaynak_id)
                self.assertEqual(d.tutar.get(), "1500")
                adaylar = {h["satir_id"]: h for h in MasrafDagitimService.hedef_satirlar()}
                d.hedef_ekle([adaylar[s1], adaylar[s2]])

                # Hesapla: yalnız önizleme
                self.assertTrue(d.onizle())
                paylar = {s["alis_fatura_satiri_id"]: s["pay"] for s in d.onizleme["satirlar"]}
                self.assertEqual(paylar, {s1: Decimal("1000.00"), s2: Decimal("500.00")})
                self.assertEqual(sum(paylar.values()), Decimal("1500.00"))
                self.assertEqual(d.hedef_tablo.item(str(s1), "values")[9], "1.000,00")
                self.assertEqual(d.hedef_tablo.item(str(s2), "values")[9], "500,00")
                self.assertIsNone(d.dagitim_id)
                self.assertEqual(self._maliyetler(), (Decimal("100"), Decimal("100")))

                # Taslak: maliyet değişmez
                self.assertTrue(d.taslak_kaydet())
                did = d.dagitim_id
                self.assertEqual(MasrafDagitimService.getir(did)["durum"], "TASLAK")
                self.assertEqual(self._maliyetler(), (Decimal("100"), Decimal("100")))
                self.assertEqual(MasrafDagitimService.kaynak_detay(kaynak_id)["dagitilan"], Decimal("0"))
                d.kapat()
                self.assertFalse(d.winfo_exists())

                # Tekrar aç: satırlar, kaynak seçimi ve paylar korunur
                d2 = MasrafDagitimDialog(root, dagitim_id=did)
                self.assertEqual(d2.durum, "TASLAK")
                self.assertEqual(d2.tutar.get(), "1500")
                self.assertEqual(d2.secili_kaynak, set(ks))
                self.assertEqual(set(d2.hedef_tablo.get_children()), {str(s1), str(s2)})
                self.assertEqual(d2.hedef_tablo.item(str(s1), "values")[9], "1.000,00")
                self.assertEqual(d2.hedef_tablo.item(str(s2), "values")[9], "500,00")
                self.assertIn("Kayıtlı taslak", d2.ozet_lbl.cget("text"))
                self.assertEqual(str(d2.onay_btn.cget("state")), "normal")

                # Onay: maliyetler bir kez artar, toplam 1.500 TL
                self.assertTrue(d2.onayla())
                self.assertEqual(d2.durum, "ONAYLANDI")
                self.assertEqual(self._maliyetler(), (Decimal("110"), Decimal("110")))
                artis = Decimal("100") * Decimal("10") + Decimal("50") * Decimal("10")
                self.assertEqual(artis, Decimal("1500"))
                self.assertEqual(MasrafDagitimService.kaynak_detay(kaynak_id)["dagitilan"], Decimal("1500.00"))
                self.assertEqual(str(d2.onay_btn.cget("state")), "disabled")
                self.assertEqual(str(d2.onizle_btn.cget("state")), "disabled")

                # İkinci onay etkisiz (ekran ve servis)
                self.assertFalse(d2.onayla())
                with self.assertRaises(ZatenIslendi):
                    MasrafDagitimService.onayla(did)
                self.assertEqual(self._maliyetler(), (Decimal("110"), Decimal("110")))
                self.assertEqual(MasrafDagitimService.kaynak_detay(kaynak_id)["dagitilan"], Decimal("1500.00"))
                d2.kapat()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
