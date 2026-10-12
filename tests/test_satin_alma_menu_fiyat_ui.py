"""Satın Alma menüsü (hub bölümleri, sol menü alt öğeleri, Listeye Git), geçmiş alış fiyatları
penceresi ve kısa yeni ürün paneli — izole test firması."""
from __future__ import annotations

import time
import tkinter as tk
import unittest
from datetime import date
from decimal import Decimal
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import func, select

import tests.test_satin_alma_menu_acilis as menu_acilis
from tests.stok_test_ortami import StokOrtami

from database.database import get_session
from database.models.cari import Cari
from database.models.stok import StokKarti


def _alis(cari_id, tarih, fiyat, kod="U001"):
    from database.alis_faturasi_service import AlisFaturasiService

    veriler = {"fatura_tarihi": tarih, "vade_tarihi": tarih, "cari_id": cari_id, "depo": "ANA DEPO",
               "odeme_tutari": Decimal("0"), "islem_saati": "10:00", "para_birimi": "TRY", "kur": Decimal("1")}
    satir = {"urun_kodu": kod, "urun_adi": "Test Ürün", "miktar": Decimal("2"), "birim": "Adet",
             "birim_fiyat": Decimal(str(fiyat)), "iskonto_orani": Decimal("0"), "iskonto_orani_2": Decimal("0"),
             "iskonto_orani_3": Decimal("0"), "kdv_orani": Decimal("20"), "lot_no": ""}
    return AlisFaturasiService.kaydet(veriler, [satir])


class _TkOrtam(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami("sa_ui")
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.o.kapat()
            self.skipTest(f"Tk yok: {exc}")
        self.root.withdraw()
        self.dialog = tk.Toplevel(self.root)
        self.dialog.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        self.o.kapat()


class GecmisAlisFiyatlariPenceresiTest(_TkOrtam):
    def setUp(self):
        super().setUp()
        with get_session() as s:
            s.add(Cari(cari_kodu="T002", unvan="İkinci Tedarikçi", cari_turu="Tedarikçi", aktif=True))
            s.commit()
            self.ted2 = s.scalar(select(Cari.id).where(Cari.cari_kodu == "T002"))
        _alis(self.o.ted_id, date(2026, 3, 1), 10)
        _alis(self.ted2, date(2026, 5, 1), 15)

    def _satirlar(self, pen):
        return [pen.tablo.item(i, "values") for i in pen.tablo.get_children()]

    def test_varsayilan_bu_tedarikci_secenekle_tum_tedarikciler(self):
        from alis_fiyat_gecmisi_ui import fiyat_gecmisi_ac

        pen = fiyat_gecmisi_ac(self.dialog, "U001", "Test Ürün", SimpleNamespace(id=self.o.ted_id, unvan="T1"))
        satirlar = self._satirlar(pen)
        self.assertEqual(len(satirlar), 1)
        self.assertEqual(satirlar[0][0], "01.03.2026")
        self.assertEqual(satirlar[0][5], "10,00")
        pen.kapsam.set("tumu")
        pen.yenile()
        satirlar = self._satirlar(pen)
        self.assertEqual([s[0] for s in satirlar], ["01.05.2026", "01.03.2026"], "en yeni üstte")
        self.assertIs(fiyat_gecmisi_ac(self.dialog, "U001", "", None), pen, "tek pencere yeniden kullanılır")

    def test_tedarikci_yoksa_genel_gorunum_ve_bilgi(self):
        from alis_fiyat_gecmisi_ui import fiyat_gecmisi_ac

        pen = fiyat_gecmisi_ac(self.dialog, "U001", "Test Ürün", None)
        self.assertEqual(pen.kapsam.get(), "tumu")
        self.assertIn("disabled", pen.rb_tedarikci.state())
        self.assertIn("tedarikçi seçilmedi", pen.tedarikci_lbl.cget("text"))
        self.assertEqual(len(self._satirlar(pen)), 2)

    def test_urun_secilmeden_uyari_ve_kayit_yoksa_bilgi(self):
        import alis_fiyat_gecmisi_ui as m

        with patch.object(m.messagebox, "showinfo") as bilgi:
            self.assertIsNone(m.fiyat_gecmisi_ac(self.dialog, "", "", None))
        self.assertIn("Ürün seçiniz", bilgi.call_args.args[1])
        self.o.urun_ekle("U777", "Hiç Alınmamış")
        pen = m.fiyat_gecmisi_ac(self.dialog, "U777", "Hiç Alınmamış", None)
        self.assertEqual(self._satirlar(pen), [])
        self.assertEqual(pen.durum_lbl.cget("text"), "Kayıt bulunamadı.")


class KisaUrunPaneliTest(_TkOrtam):
    def _kart_sayisi(self):
        with get_session() as s:
            return s.scalar(select(func.count(StokKarti.id)))

    def test_metin_turu_on_doldurma(self):
        from kisa_urun_paneli import metin_turu, on_doldurma

        self.assertEqual(metin_turu("8690000000017"), "barkod")
        self.assertEqual(metin_turu("VDA-120"), "kod")
        self.assertEqual(metin_turu("Ahşap vida"), "ad")
        self.assertEqual(on_doldurma("8690000000017")["barkod"], "8690000000017")

    def test_kaydet_kart_olusturur_stok_hareketi_yok(self):
        from kisa_urun_paneli import KisaUrunPaneli

        once_hareket = self.o.hareket_sayisi()
        once = self._kart_sayisi()
        p = KisaUrunPaneli(self.dialog, "Ahşap vida 4x40")
        self.assertEqual(p.ad.get(), "Ahşap vida 4x40")
        self.assertTrue(p.kod.get(), "stok kodu otomatik üretilmeli")
        self.assertEqual(p.birim.get(), "Adet")
        p.kaydet()
        self.assertIsNotNone(p.result)
        self.assertEqual(p.result.stok_adi, "Ahşap vida 4x40")
        self.assertEqual(self._kart_sayisi(), once + 1)
        self.assertEqual(self.o.hareket_sayisi(), once_hareket, "açılış stoku / hareket oluşmamalı")

    def test_vazgec_kart_olusturmaz(self):
        from kisa_urun_paneli import KisaUrunPaneli

        once = self._kart_sayisi()
        p = KisaUrunPaneli(self.dialog, "Vazgeçilen ürün")
        p.vazgec()
        self.assertIsNone(p.result)
        self.assertEqual(self._kart_sayisi(), once)

    def test_ayni_barkod_mevcut_karti_onerir_ikinci_kart_acmaz(self):
        import kisa_urun_paneli as m

        p = m.KisaUrunPaneli(self.dialog, "8690000000017")
        p.ad.insert(0, "Barkodlu Ürün")
        p.kaydet()
        ilk = p.result
        once = self._kart_sayisi()
        p2 = m.KisaUrunPaneli(self.dialog, "8690000000017")
        p2.ad.insert(0, "Başka Ad")
        with patch.object(m.messagebox, "askyesno", return_value=True) as sor:
            p2.kaydet()
        self.assertTrue(sor.called)
        self.assertEqual(p2.result.stok_kodu, ilk.stok_kodu)
        self.assertEqual(self._kart_sayisi(), once)

    def test_barkod_ad_olarak_kaydedilmez(self):
        from kisa_urun_paneli import KisaUrunPaneli

        once = self._kart_sayisi()
        p = KisaUrunPaneli(self.dialog, "")
        p.ad.insert(0, "8690000000024")
        p.kaydet()
        self.assertIn("Barkod", p.hata_lbl.cget("text"))
        self.assertEqual(self._kart_sayisi(), once)
        p.vazgec()


class SatinAlmaSolMenuTest(unittest.TestCase):
    """Gerçek ana panel kabuğu; kurulum Satın Alma menü açılış testiyle ortak."""

    _K = menu_acilis.SatinAlmaMenuAcilisTest
    setUp = _K.setUp
    tearDown = _K.tearDown
    _alis = _K._alis
    _gider = _K._gider
    _pompala = _K._pompala
    _kartlar = _K._kartlar
    _kart_tikla = _K._kart_tikla
    _gorunen_basliklar = _K._gorunen_basliklar
    _yeni_pencereler = _K._yeni_pencereler
    _tum_widgetlar = _K._tum_widgetlar
    _dugme = _K._dugme

    def _metinler(self):
        return [str(w.cget("text")) for w in self._tum_widgetlar() if isinstance(w, (tk.Label, ttk.Label))]

    def test_hub_bolumleri_ve_kart_sirasi(self):
        import satin_alma_ui as sa

        metinler = self._metinler()
        for baslik in ("Satın Alma İşlemleri", "Raporlar"):
            self.assertIn(baslik, metinler)
        self.assertNotIn("Kartlar, Tanımlar ve Aktarımlar", metinler)
        kartlar = list(self._kartlar())
        islem = [b for b, *_ in sa.ISLEM_KARTLARI + sa.TANIM_KARTLARI]
        rapor = [b for b, *_ in sa.LISTE_KARTLARI + sa.RAPOR_KARTLARI]
        self.assertEqual(kartlar, islem + rapor)
        self.assertNotIn("TEDARİKÇİ TEKLİFLERİ", kartlar)

    def test_gruplar_kapali_acilir_kapanir_yeniden_acilista_kapali(self):
        gruplar = self.app.satin_alma_menu_gruplari
        gorunen = self._gorunen_basliklar()
        self.assertIn("Satın Alma İşlemleri", gorunen)
        self.assertIn("Raporlar", gorunen)
        self.assertFalse(any(g.acik for g in gruplar.values()))
        self.assertNotIn("ALIŞ FATURASI", gorunen)
        self.assertNotIn("KDV RAPORU", gorunen)

        cocuk = list(self.app.icerik.winfo_children())
        gruplar["islem"].etiket.event_generate("<Button-1>")
        self._pompala(0.2)
        self.assertTrue(gruplar["islem"].acik)
        self.assertEqual(list(self.app.icerik.winfo_children()), cocuk, "başlık ayrı ekran açmamalı")
        self.assertEqual(self._yeni_pencereler(), [])
        gorunen = self._gorunen_basliklar()
        self.assertIn("ALIŞ FATURASI", gorunen)
        self.assertIn("EXCEL VERİ AKTARIM", gorunen)
        self.assertNotIn("KDV RAPORU", gorunen)
        alt_y = gruplar["islem"].alt.winfo_rooty()
        self.assertLess(gruplar["islem"].baslik.winfo_rooty(), alt_y)
        self.assertLess(alt_y, gruplar["rapor"].baslik.winfo_rooty(), "alt menü başlığın hemen altında")

        gruplar["rapor"].degistir()
        self._pompala(0.2)
        self.assertIn("KDV RAPORU", self._gorunen_basliklar())
        gruplar["islem"].degistir()
        self._pompala(0.2)
        self.assertNotIn("ALIŞ FATURASI", self._gorunen_basliklar())

        eski = gruplar["rapor"]
        self.assertTrue(self.app._ekran_yoneticisi.kapat("satin_alma", sor=False))
        self._pompala(0.3)
        self.app.sayfa_goster("satin_alma", ust_duzey=True)
        bitis = time.monotonic() + 10
        while self.app.satin_alma_menu_gruplari.get("rapor") is eski and time.monotonic() < bitis:
            self._pompala(0.1)
        gruplar = self.app.satin_alma_menu_gruplari
        self.assertIsNot(gruplar["rapor"], eski)
        self.assertFalse(any(g.acik for g in gruplar.values()))
        self.assertNotIn("KDV RAPORU", self._gorunen_basliklar())

    def test_alt_secenekler_dogru_ekrani_acar(self):
        import satin_alma_rapor_ui as r

        gruplar = self.app.satin_alma_menu_gruplari
        gruplar["rapor"].degistir()
        self._pompala(0.2)
        with patch.object(r, "alis_iade_ozeti_goster") as ozet:
            self._kart_tikla("ALIŞ VE İADE ÖZETİ")
        ozet.assert_called_once_with(self.app)
        gruplar = self.app.satin_alma_menu_gruplari
        gruplar["islem"].degistir()
        self._kart_tikla("ALIŞ SİPARİŞİ")
        pencereler = self._yeni_pencereler()
        self.assertEqual([p.title() for p in pencereler], ["ALIŞ SİPARİŞİ"])
        pencereler[0].destroy()

    def test_sol_menu_baslik_tiklamasi_acar_kapatir(self):
        grup = self.app.menu_gruplari["satin_alma"]
        stoklar = self.app.menu_dugmeleri["stoklar"]
        self.assertEqual(list(grup.alt_dugmeler),
                         ["alis_faturasi_yeni", "alis_siparisi_yeni", "satin_alma_talebi_yeni"])
        self.assertFalse(grup.alt_cerceve.winfo_manager(), "grup varsayılan kapalı")
        self.assertFalse(any(d.winfo_ismapped() for d in grup.alt_dugmeler.values()))
        self.assertEqual(grup.lbl_ok.cget("text"), "▸")
        kapali_y = stoklar.winfo_y()
        self.assertLess(kapali_y - (grup.winfo_y() + grup.winfo_height()), 5, "Stoklar hemen altta")

        for _ in range(3):
            grup.lbl_text.event_generate("<Button-1>")
            self._pompala(0.2)
            self.assertTrue(grup.acik)
            self.assertTrue(all(d.winfo_ismapped() for d in grup.alt_dugmeler.values()))
            self.assertEqual(grup.lbl_ok.cget("text"), "▾")
            self.assertLessEqual(abs(grup.alt_cerceve.winfo_y() - (grup.winfo_y() + grup.winfo_height())), 2,
                                 "alt öğeler başlığın hemen altında")
            self.assertGreater(stoklar.winfo_y(), kapali_y)
            self.assertEqual(self.app._ekran_yoneticisi.aktif_anahtar(), "satin_alma")

            grup.inner.event_generate("<Button-1>")
            self._pompala(0.2)
            self.assertFalse(grup.acik)
            self.assertFalse(any(d.winfo_ismapped() for d in grup.alt_dugmeler.values()))
            self.assertEqual(grup.lbl_ok.cget("text"), "▸")
            self.assertEqual(stoklar.winfo_y(), kapali_y, "kapanınca boşluk kalmamalı")

        grup.lbl_ok.event_generate("<Button-1>")
        self._pompala(0.2)
        self.assertTrue(grup.acik, "ok da aynı şekilde açar")
        grup.lbl_ok.event_generate("<Button-1>")
        self._pompala(0.2)
        self.assertFalse(grup.acik)

    def test_ekran_acilisi_sol_menuyu_kendiliginden_acmaz(self):
        grup = self.app.menu_gruplari["satin_alma"]
        self.app.sayfa_goster("stoklar", ust_duzey=True)
        self._pompala(0.6)
        self.app.sayfa_goster("satin_alma", ust_duzey=True)
        self._pompala(0.6)
        self._kart_tikla("ALIŞ TEKLİFLERİ LİSTESİ")
        self._dugme("← Satın Alma").invoke()
        self._pompala(0.4)
        self.assertFalse(grup.acik)
        self.assertFalse(grup.alt_cerceve.winfo_manager())

    def test_sol_menu_alt_secenekler_dogru_belgeyi_acar(self):
        grup = self.app.menu_gruplari["satin_alma"]
        beklenen = {"alis_faturasi_yeni": "ALIŞ FATURASI", "alis_siparisi_yeni": "ALIŞ SİPARİŞİ",
                    "satin_alma_talebi_yeni": "SATIN ALMA TALEBİ"}
        for anahtar, baslik in beklenen.items():
            grup.lbl_text.event_generate("<Button-1>")
            self._pompala(0.2)
            dugme = grup.alt_dugmeler[anahtar]
            self.assertTrue(dugme.winfo_ismapped())
            dugme.lbl_text.event_generate("<Button-1>")
            self._pompala()
            pencereler = self._yeni_pencereler()
            self.assertEqual(len(pencereler), 1, anahtar)
            self.assertIn(baslik, pencereler[0].title().upper())
            pencereler[0].destroy()
            self._pompala(0.2)
            self.assertTrue(grup.acik, "alt öğe tıklaması grubu kapatmaz")
            grup.lbl_text.event_generate("<Button-1>")
            self._pompala(0.2)
            self.assertFalse(grup.acik)

    def test_alt_oge_bos_belge_acar_kayit_olusturmaz_listeye_git(self):
        from database.alis_siparisi_service import AlisSiparisiService

        grup = self.app.menu_gruplari["satin_alma"]
        grup.alt_dugmeler["alis_siparisi_yeni"]._on_click()
        self._pompala()
        pencereler = self._yeni_pencereler()
        self.assertEqual(len(pencereler), 1)
        d = pencereler[0]
        self.assertEqual(d.title(), "ALIŞ SİPARİŞİ")
        self.assertEqual(d.satirlar, [])
        self.assertTrue(grup.alt_dugmeler["alis_siparisi_yeni"]._aktif, "seçili alt öğe vurgulanır")
        self.assertEqual(AlisSiparisiService.listele(), [])
        d.listeye_git()
        self._pompala(0.5)
        self.assertFalse(d.winfo_exists())
        self.assertIn("ALIŞ SİPARİŞLERİ LİSTESİ", self._metinler())
        self.assertIn("Kayıtlı alış siparişi yok. Yeni Sipariş ile ilk siparişi girin.", self._metinler())

    def test_yetkiye_gore_alt_ogeler(self):
        from database.session_manager import oturum

        grup = self.app.menu_gruplari["satin_alma"]
        grup.ac_kapat(True)
        oturum.set_user(user_id=5, kullanici_adi="alim", ad_soyad="Alım", role_kod="ALIM", role_ad="Alım",
                        permissions={"alis_goruntuleme", "alis_fatura_duzenleme"})
        self.app._sistem_menu_gorunurluk_guncelle()
        gorunen = [k for k, d in grup.alt_dugmeler.items() if d.winfo_manager()]
        self.assertEqual(gorunen, ["alis_faturasi_yeni"])
        self.assertTrue(grup.winfo_manager())
        self.assertTrue(grup.alt_cerceve.winfo_manager())

    def test_teklif_listesi_bos_bilgi(self):
        self._kart_tikla("ALIŞ TEKLİFLERİ LİSTESİ")
        self.assertEqual(self.geri_cagri_hatalari, [])
        metinler = self._metinler()
        self.assertIn("ALIŞ TEKLİFLERİ LİSTESİ", metinler)
        self.assertTrue(any(m.startswith("Kayıtlı alış teklifi yok.") for m in metinler))


if __name__ == "__main__":
    unittest.main()
