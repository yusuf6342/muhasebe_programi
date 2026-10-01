"""Satış faturası Notlar alanı: çok satırlı kutu, «Notu büyüt», kayıt/yeniden açma, onay kilidi, yerleşim."""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.database import get_session
from tests import test_uzlasma_net_cari as _uz

KISA_NOT = "Teslimat cuma günü yapılacak."
UZUN_NOT = "\n".join(
    f"{i:02d}. satır — Müşteri ile görüşüldü; ödeme vadesi, teslim adresi ve ambalaj ayrıntıları "
    f"bu satırda uzun bir açıklama olarak yer alır ve kutuya sığmayıp otomatik satıra geçmelidir."
    for i in range(1, 31)
) + "\n\n  Son paragraf (baştaki boşluklar korunur)."


def _satir():
    return {
        "urun_kodu": "U001", "urun_adi": "Masa", "miktar": "1", "birim": "Adet",
        "birim_satis_fiyati": "100", "kdv_orani": "20", "iskonto_orani": "0",
        "iskonto_orani_2": "0", "iskonto_orani_3": "0", "satir_para_birimi": "TRY", "kur": "1",
    }


class FaturaNotAlaniTest(unittest.TestCase):
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

    def _ac(self, fatura=None, boyut="1400x800"):
        from app import CariService, SatisFaturasiDialog

        if self.dlg is not None:
            try:
                self.dlg.destroy()
            except Exception:
                pass
        if fatura is not None:
            self.dlg = SatisFaturasiDialog(self.root, fatura=fatura)
        else:
            self.dlg = SatisFaturasiDialog(self.root, cari=CariService.getir(self.musteri_id))
            self.dlg.satirlar = [_satir()]
            self.dlg._satir_listesini_yenile()
            self.dlg._toplamlari_guncelle()
        self.dlg.attributes("-alpha", 0.0)
        self.dlg.geometry(f"{boyut}+20+20")
        self._pompala()
        return self.dlg

    def _pompala(self, tur=10):
        for _ in range(tur):
            self.dlg.update_idletasks()
            self.dlg.update()

    def _not(self):
        return self.dlg._fatura_not_alani()

    def _yaz_ve_kaydet(self, metin):
        from database.satis_faturasi_service import SatisFaturasiService

        n = self._not()
        n.delete("1.0", "end")
        n.insert("1.0", metin)
        n.event_generate("<KeyRelease>")
        self._pompala()
        veriler, satirlar = self.dlg._fatura_kayit_verilerini_topla()
        fid = self.dlg.fatura.id if self.dlg.fatura else None
        f = SatisFaturasiService.kaydet(veriler, satirlar, fid)
        return SatisFaturasiService.getir(f.id)

    # —— alan yapısı ——
    def test_cok_satirli_kutu_genislige_yayilir_ve_buyut_dugmesi_var(self):
        self._ac()
        n = self._not()
        self.assertIsInstance(n, tk.Text)
        self.assertEqual(str(n.cget("wrap")), "word")
        self.assertGreaterEqual(int(n.cget("height")), 5)
        self.assertEqual(n.not_buyut_btn.cget("text"), "Notu büyüt")
        satir_px = n.tk.call("font", "metrics", n.cget("font"), "-linespace")
        self.assertGreaterEqual(n.winfo_height(), 4 * int(satir_px), "en az 4 satır okunur olmalı")
        kart = self.dlg._fatura_alt_ozet["kart"]
        sag = self.dlg._fatura_alt_ozet["sag"]
        bos = kart.winfo_width() - sag.winfo_width()
        self.assertGreater(n.master.winfo_width(), bos * 0.8, "Notlar kullanılabilir genişliğe yayılmalı")

    def test_kisa_notta_kaydirma_yok_uzun_notta_var(self):
        self._ac()
        n = self._not()
        n.insert("1.0", KISA_NOT)
        self._pompala()
        self.assertEqual(n.not_kaydirma.winfo_manager(), "")
        n.delete("1.0", "end")
        n.insert("1.0", UZUN_NOT)
        self._pompala()
        self.assertEqual(n.not_kaydirma.winfo_manager(), "pack")

    # —— kayıt / yeniden açma ——
    def test_kisa_ve_uzun_not_kaydedilip_yeniden_acilinca_eksiksiz(self):
        for metin in (KISA_NOT, UZUN_NOT):
            with self.subTest(uzunluk=len(metin)):
                self._ac()
                kayit = self._yaz_ve_kaydet(metin)
                self.assertEqual(kayit.aciklama, metin)
                self._ac(fatura=kayit)
                self.assertEqual(self._not().get("1.0", "end-1c"), metin)
                # Yeniden açılan faturada not değiştirilip güncellenir
                kayit2 = self._yaz_ve_kaydet(metin + "\nEk satır")
                self.assertEqual(kayit2.id, kayit.id)
                self.assertEqual(kayit2.aciklama, metin + "\nEk satır")

    def test_notu_buyut_uygula_fatura_notuna_aktarir(self):
        from fatura_not_alani import notu_buyut

        self._ac()
        self._not().insert("1.0", KISA_NOT)
        dlg = notu_buyut(self.dlg, self._not(), degisti=self.dlg._fatura_alt_not_senkron, bekle=False)
        self.assertFalse(dlg.salt_okunur)
        self.assertEqual(dlg.text.get("1.0", "end-1c"), KISA_NOT)
        dlg.text.insert("end", "\n" + UZUN_NOT)
        dlg.uygula()
        beklenen = KISA_NOT + "\n" + UZUN_NOT
        self.assertEqual(self._not().get("1.0", "end-1c"), beklenen)
        self.assertEqual(self.dlg.girdiler["aciklama"].get(), beklenen)
        veriler, _ = self.dlg._fatura_kayit_verilerini_topla()
        self.assertEqual(veriler["aciklama"], beklenen)

    def test_notu_buyut_vazgec_degistirmez(self):
        from fatura_not_alani import notu_buyut

        self._ac()
        self._not().insert("1.0", KISA_NOT)
        dlg = notu_buyut(self.dlg, self._not(), bekle=False)
        dlg.text.insert("end", " DEĞİŞTİ")
        dlg.vazgec()
        self.assertEqual(self._not().get("1.0", "end-1c"), KISA_NOT)

    # —— onay kilidi ——
    def test_onayli_faturada_not_salt_okunur(self):
        from database.models.satis_faturasi import SatisFaturasi
        from database.satis_faturasi_service import SatisFaturasiService
        from fatura_not_alani import notu_buyut

        self._ac()
        kayit = self._yaz_ve_kaydet(UZUN_NOT)
        with get_session() as s:
            f = s.get(SatisFaturasi, kayit.id)
            f.onaylandi = True
            f.durum = "ONAYLANDI"
        self._ac(fatura=SatisFaturasiService.getir(kayit.id))
        n = self._not()
        self.assertTrue(self.dlg._fatura_kilitli)
        self.assertEqual(str(n.cget("state")), "disabled")
        self.assertEqual(n.get("1.0", "end-1c"), UZUN_NOT)
        n.insert("end", "X")  # disabled: yok sayılır
        self.assertEqual(n.get("1.0", "end-1c"), UZUN_NOT)
        dlg = notu_buyut(self.dlg, n, bekle=False)
        self.assertTrue(dlg.salt_okunur)
        self.assertEqual(dlg.text.get("1.0", "end-1c"), UZUN_NOT)
        dlg.text.insert("end", "Y")
        dlg.uygula()
        self.assertEqual(n.get("1.0", "end-1c"), UZUN_NOT)

    # —— yerleşim ——
    def test_farkli_pencere_boyutlarinda_yerlesim(self):
        ekran_g, ekran_y = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        boyutlar = [(1024, 640), (1280, 720), (1366, 768), (1600, 900), (1920, 1040)]
        self._ac()
        self._not().insert("1.0", UZUN_NOT)
        for g, y in boyutlar:
            g, y = min(g, ekran_g), min(y, ekran_y - 40)
            with self.subTest(boyut=f"{g}x{y}"):
                self.dlg.geometry(f"{g}x{y}+0+0")
                self._pompala(14)
                alt = self.dlg.winfo_rooty() + self.dlg.winfo_height()
                sag_kenar = self.dlg.winfo_rootx() + self.dlg.winfo_width()
                n = self._not()
                genel = self.dlg._fatura_alt_ozet["degerler"]["genel"]
                for ad, w in (("not", n), ("net toplam", genel), ("Notu büyüt", n.not_buyut_btn)):
                    self.assertTrue(w.winfo_ismapped(), f"{ad} görünmüyor")
                    self.assertLessEqual(w.winfo_rooty() + w.winfo_height(), alt + 1, f"{ad} alttan taşıyor")
                    self.assertLessEqual(w.winfo_rootx() + w.winfo_width(), sag_kenar + 1, f"{ad} sağdan taşıyor")
                satir_px = int(n.tk.call("font", "metrics", n.cget("font"), "-linespace"))
                self.assertGreaterEqual(n.winfo_height(), 4 * satir_px)
                self.assertGreater(self.dlg.satir_tablosu.winfo_height(), 40, "ürün satırları görünür kalmalı")
                kaydet = getattr(self.dlg, "_btn_kaydet", None)
                if kaydet is not None:
                    self.assertTrue(kaydet.winfo_ismapped(), "Kaydet düğmesi görünmüyor")
                    self.assertLessEqual(kaydet.winfo_rootx() + kaydet.winfo_width(), sag_kenar + 1)


if __name__ == "__main__":
    unittest.main()
