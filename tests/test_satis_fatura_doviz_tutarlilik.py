"""Satış faturası: satır para birimi/kur tutarlılığı, miktar-fiyat hücre düzenleme ve uzlaşma etkisi.

Gerçek SatisFaturasiDialog (görünmez pencere) + geçici test veritabanı.
"""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.database import get_session
from database.models.stok import StokFiyati, StokKarti
from tests import test_uzlasma_net_cari as _uz

GUNLUK_KUR = Decimal("48.8377")
BELGE_KUR = Decimal("49.0184")


class SatisFaturaDovizTutarlilikTest(unittest.TestCase):
    def setUp(self):
        _uz._kurulum(self)
        with get_session() as s:
            st = StokKarti(
                stok_kodu="USD1", stok_adi="Dolar Ürün", birim="Adet", barkod="8690000000099",
                aktif=True, is_deleted=False, kdv_orani=20,
            )
            s.add(st)
            s.flush()
            s.add(StokFiyati(stok_id=st.id, fiyat_adi="SATIŞ FİYATI 1", tutar=Decimal("120"), para_birimi="USD"))
            masa = s.query(StokKarti).filter_by(stok_kodu="U001").one()
            masa.barkod = "8690000000011"
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:
            _uz._sokum(self)
            self.skipTest(f"Tk yok: {hata}")
        self.root.attributes("-alpha", 0.0)
        kur_bilgisi = lambda pb, tarih, kur_turu="forex_selling", **_k: {  # noqa: E731
            "para_birimi": pb, "kur": GUNLUK_KUR, "kur_tarihi": tarih, "kur_turu": kur_turu,
            "kur_kaynagi": "TCMB", "kur_sabitlendi": False,
        }
        self._yamalar = [
            patch("satis_personeli_ui.aktif_satis_personelleri", return_value=[]),
            patch("satis_personeli_ui.satis_personeli_degistirme_yetkisi", return_value=True),
            patch("fatura_acilis_cache.satis_personelleri", return_value=[]),
            patch("fatura_manuel_fiyat_ui.fiyat_degistirme_yetkisi", return_value=True),
            patch("fatura_manuel_fiyat_ui.maliyet_alti_kontrol", return_value=True),
            patch("database.doviz_service.DovizService.kur_degeri", return_value=GUNLUK_KUR),
            patch("database.doviz_service.DovizService.fatura_kur_bilgisi", side_effect=kur_bilgisi),
        ]
        for y in self._yamalar:
            y.start()
        self.d = None

    def tearDown(self):
        try:
            if self.d is not None:
                self.d.destroy()
        except Exception:
            pass
        for y in reversed(self._yamalar):
            y.stop()
        try:
            self.root.destroy()
        except Exception:
            pass
        _uz._sokum(self)

    # —— yardımcılar ——
    def _ac(self, fatura_id=None):
        from app import CariService, SatisFaturasiDialog, SatisFaturasiService

        if fatura_id is None:
            self.d = SatisFaturasiDialog(self.root, cari=CariService.getir(self.musteri_id))
        else:
            self.d = SatisFaturasiDialog(self.root, fatura=SatisFaturasiService.getir(fatura_id))
        self.d.geometry("1500x850+0+0")
        self.d.attributes("-alpha", 0.0)
        self._pompala()
        return self.d

    def _pompala(self, tur=8):
        for _ in range(tur):
            self.d.update_idletasks()
            self.d.update()

    def _ekle(self, kod):
        from fatura_urun_aktar_service import urun_seciminden_aktar

        idx = urun_seciminden_aktar(self.d, (kod, "", "Adet", 0, "", "", None), merkezi_fiyat=True)
        self._pompala()
        return idx

    def _degerler(self, idx):
        t = self.d.satir_tablosu
        return dict(zip(t.cget("columns"), t.item(str(idx), "values")))

    def _usd_baslik(self):
        from doviz_fatura_panel import doviz_para_birimi_degisti

        self.d._doviz_para_birimi.set("USD")
        doviz_para_birimi_degisti(self.d)
        self._pompala()

    def _hucre(self, idx, kolon, deger):
        from fatura_satir_hucre_edit import hucre_duzenle

        hucre_duzenle(self.d, idx=idx, kolon=kolon)
        self._pompala()
        ed = self.d._satir_hucre_editor
        self.assertIsNotNone(ed, f"{kolon} hücresi düzenlemeye açılmadı")
        ed.delete(0, "end")
        ed.insert(0, deger)
        ed._uygula_fn()
        self._pompala()

    # —— para birimi ——
    def test_tl_faturada_usd_fiyatli_urun_bir_kez_tlye_cevrilir(self):
        self._ac()
        idx = self._ekle("USD1")
        satir = self.d.satirlar[idx]
        self.assertEqual(satir["satir_para_birimi"], "TRY")
        self.assertEqual(Decimal(str(satir["birim_satis_fiyati"])), (Decimal("120") * GUNLUK_KUR).quantize(Decimal("0.0001")))
        v = self._degerler(idx)
        self.assertEqual(v["fiyat"], "5.860,52 TL")
        self.assertEqual(v["para_birimi"], "TRY")
        self.assertEqual(v["net_birim"], v["toplam"])  # miktar 1 → net birim = net tutar

    def test_usd_faturada_birim_fiyat_satir_pbsinde_tutarlar_tl(self):
        self._ac()
        self._usd_baslik()
        idx = self._ekle("USD1")
        satir = self.d.satirlar[idx]
        self.assertEqual(satir["satir_para_birimi"], "USD")
        self.assertEqual(Decimal(str(satir["kur"])), GUNLUK_KUR)
        v = self._degerler(idx)
        self.assertEqual(v["fiyat"], "120,00 USD")
        self.assertEqual(v["kur"], "48,8377")
        net = (Decimal("120") * GUNLUK_KUR).quantize(Decimal("0.01"))
        beklenen = net + (net * Decimal("0.2")).quantize(Decimal("0.01"))
        self.assertEqual(v["net_birim"], v["toplam"])
        self.assertIn(f"{beklenen:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), v["toplam"])
        basliklar = {k: self.d.satir_tablosu.heading(k, "text") for k in ("net_birim", "toplam", "kdv_tutar")}
        self.assertTrue(all("(TL)" in b for b in basliklar.values()), basliklar)

    def test_belge_kuru_degisince_satir_kuru_guncellenir_doviz_fiyati_sabit(self):
        from doviz_fatura_panel import doviz_manuel_kur

        self._ac()
        self._usd_baslik()
        idx = self._ekle("USD1")
        self.d._doviz_kur.set(str(BELGE_KUR))
        doviz_manuel_kur(self.d)
        self._pompala()
        satir = self.d.satirlar[idx]
        self.assertEqual(Decimal(str(satir["kur"])), BELGE_KUR)
        self.assertEqual(Decimal(str(satir["birim_fiyat_doviz"])), Decimal("120.0000"))
        self.assertEqual(Decimal(str(satir["birim_satis_fiyati"])), (Decimal("120") * BELGE_KUR).quantize(Decimal("0.0001")))
        self.assertEqual(self._degerler(idx)["fiyat"], "120,00 USD")

    def test_tlden_usdye_geciste_tl_tutar_korunur_cift_donusum_yok(self):
        self._ac()
        idx = self._ekle("U001")
        self._hucre(idx, "fiyat", "12000")
        self._usd_baslik()
        satir = self.d.satirlar[idx]
        self.assertEqual(satir["satir_para_birimi"], "USD")
        self.assertEqual(Decimal(str(satir["birim_satis_fiyati"])), Decimal("12000"))
        self.assertEqual(
            Decimal(str(satir["birim_fiyat_doviz"])), (Decimal("12000") / GUNLUK_KUR).quantize(Decimal("0.0001"))
        )

    def test_kayitli_usd_fatura_acilista_kayitli_kuru_korur(self):
        from database.satis_faturasi_service import SatisFaturasiService

        veriler = _uz._veriler(self, net=_uz.BRUT)
        veriler.update({"para_birimi": "USD", "kur": BELGE_KUR, "kur_tarihi": date(2026, 6, 1),
                        "kur_sabitlendi": True, "kur_kaynagi": "TCMB"})
        satirlar = [dict(_uz.SATIR[0], birim_fiyat=Decimal("12000"), tl_esas=True)]
        f = SatisFaturasiService.kaydet(veriler, satirlar)
        self._ac(int(f.id))
        self.assertEqual(Decimal(self.d._doviz_kur.get()), BELGE_KUR)
        self.assertTrue(self.d._doviz_sabitlendi.get())
        satir = self.d.satirlar[0]
        self.assertEqual(Decimal(str(satir["kur"])), BELGE_KUR)
        self.assertEqual(Decimal(str(satir["birim_satis_fiyati"])), Decimal("12000"))

    def test_birim_degisiminde_kart_fiyati_tlye_cevrilir(self):
        from fatura_satir_birim_service import birim_satis_fiyati_tl, fiyat_cevir

        self.assertEqual(
            birim_satis_fiyati_tl("USD1", "Adet"), (Decimal("120") * GUNLUK_KUR).quantize(Decimal("0.0001"))
        )
        self.assertEqual(
            birim_satis_fiyati_tl("USD1", "Adet", kurlar={"USD": BELGE_KUR}),
            (Decimal("120") * BELGE_KUR).quantize(Decimal("0.0001")),
        )
        self.assertEqual(fiyat_cevir(Decimal("100"), "TL", "TRY"), Decimal("100"))

    # —— miktar / fiyat düzenleme ——
    def test_barkodla_eklenen_satirda_miktar_ve_fiyat_duzenlenir_toplam_guncellenir(self):
        from fatura_barkod_ui import fatura_barkod_isle

        self._ac()
        fatura_barkod_isle(self.d, "8690000000011")
        self._pompala()
        self.assertEqual(len(self.d.satirlar), 1)
        self._hucre(0, "miktar", "3")
        self._hucre(0, "fiyat", "150")
        satir = self.d.satirlar[0]
        self.assertEqual(Decimal(str(satir["miktar"])), Decimal("3"))
        self.assertEqual(Decimal(str(satir["birim_satis_fiyati"])), Decimal("150"))
        self.assertEqual(self.d._hesaplanan_genel, Decimal("540.00"))
        # Barkod tekrar okutulunca miktar artışı korunur
        fatura_barkod_isle(self.d, "8690000000011")
        self._pompala()
        self.assertEqual(Decimal(str(self.d.satirlar[0]["miktar"])), Decimal("4"))

    def test_kayitli_onaysiz_faturada_duzenleme_ve_uzlasma_kaldirilir(self):
        fid = _uz._uzlasmali_fatura(self, onayla=False)
        self._ac(fid)
        self.assertEqual(self.d._uzlasilan_tutar, _uz.NET)
        self.assertEqual(self.d._hesaplanan_genel, _uz.NET)
        self._hucre(0, "miktar", "2")
        self.assertIsNone(self.d._uzlasilan_tutar)
        self.assertEqual(self.d._uzlasilan_tutar_entry.get().strip(), "")
        self.assertEqual(self.d._hesaplanan_genel, _uz.BRUT * 2)

    def test_onayli_faturada_hucre_duzenlenemez(self):
        from fatura_satir_hucre_edit import hucre_duzenle, kolon_duzenlenebilir_mi

        fid = _uz._uzlasmali_fatura(self, onayla=True)
        self._ac(fid)
        self.assertTrue(self.d._fatura_kilitli)
        self.assertFalse(kolon_duzenlenebilir_mi(self.d, 0, "miktar"))
        with patch("fatura_satir_hucre_edit.messagebox.showwarning"):
            hucre_duzenle(self.d, idx=0, kolon="miktar")
        self.assertIsNone(getattr(self.d, "_satir_hucre_editor", None))


if __name__ == "__main__":
    unittest.main()
