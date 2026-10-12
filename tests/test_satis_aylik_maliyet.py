"""Müşteri yıllık/aylık raporu — maliyet yöntemleri, brüt satış kârı ve marj (izole test firması)."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from database.database import get_session
from tests.test_satis_yonetici_raporlari import _satir, _Taban

D = Decimal
BUGUN = date(2026, 3, 15)


class AylikMaliyetTest(_Taban):
    def _kontrol_urunu(self):
        """Giriş 10×100 sonra 10×150; 12 adet 2.400 TL net satış."""
        self.o.urun_ekle("K001", "Kontrol Ürün")
        self.o.alis(10, 100, date(2026, 1, 3), kod="K001")
        self.o.alis(10, 150, date(2026, 1, 5), kod="K001")
        return self.fatura(date(2026, 1, 10), [_satir(12, 200, kod="K001")])

    def _hucre(self, sonuc, cari_id=None):
        cari_id = cari_id or self.o.mus_id
        return next(x for x in sonuc["satirlar"] if x.get("cari_id") == cari_id)

    def _tarih_geri_al(self, kod: str, yeni: date):
        """Önceki yıl devri: ürünün tüm giriş hareketleri ve lotları ``yeni`` tarihine taşınır (test verisi)."""
        from database.models.stok import StokHareketi, StokKarti, StokLotu

        with get_session() as s:
            sid = s.query(StokKarti.id).filter(StokKarti.stok_kodu == kod).scalar()
            for h in s.query(StokHareketi).filter(StokHareketi.stok_id == sid).all():
                h.tarih = yeni
            for lot in s.query(StokLotu).filter(StokLotu.stok_id == sid).all():
                lot.giris_tarihi = yeni

    def test_kontrol_ornegi_fifo_ve_hareketli_ortalama(self):
        from database import satis_yonetici_rapor_service as srv
        from database.satis_maliyet_motoru import DONEMSEL, HAREKETLI, SON_ALIS

        self._kontrol_urunu()
        b = srv.musteri_aylik_satis(2026, gosterge="birlikte", bugun=BUGUN)
        m = self._hucre(b)
        self.assertEqual((m["ay_1_net"], m["ay_1_maliyet"], m["ay_1_kar"], m["ay_1_marj"]),
                         (D("2400.00"), D("1300.00"), D("1100.00"), D("45.83")))
        self.assertEqual((m["toplam_net"], m["toplam_kar"], m["toplam_marj"]),
                         (D("2400.00"), D("1100.00"), D("45.83")))
        self.assertEqual(b["maliyet_yontemi"], "FIFO")

        h = self._hucre(srv.musteri_aylik_satis(2026, gosterge="birlikte", filtre={"maliyet_yontemi": HAREKETLI},
                                                bugun=BUGUN))
        self.assertEqual((h["ay_1_maliyet"], h["ay_1_kar"], h["ay_1_marj"]), (D("1500.00"), D("900.00"),
                                                                               D("37.50")))
        d = self._hucre(srv.musteri_aylik_satis(2026, gosterge="maliyet", filtre={"maliyet_yontemi": DONEMSEL},
                                                bugun=BUGUN))
        self.assertEqual(d["ay_1"], D("1500.00"))  # (1000 + 1500) / 20 × 12
        s = srv.musteri_aylik_satis(2026, gosterge="maliyet", filtre={"maliyet_yontemi": SON_ALIS}, bugun=BUGUN)
        self.assertEqual(self._hucre(s)["ay_1"], D("1800.00"))
        self.assertIn("KARŞILAŞTIRMA AMAÇLI", " ".join(s["notlar"]))

        # Yöntem yalnız raporu değiştirir: kaydedilen satır maliyeti ve lot kalanları aynı kalır
        from database.models.satis_faturasi import SatisFaturasiSatiri

        with get_session() as ses:
            kayitli = [D(str(x.fifo_birim_maliyeti)) for x in ses.query(SatisFaturasiSatiri).all()
                       if x.urun_kodu == "K001"]
        self.assertEqual(kayitli, [D("108.3333")])
        self.assertEqual(self.o.lot_toplam(kod="K001"), D("8"))

        # Satış kârlılık raporu ile aynı filtre ve yöntemde aynı toplam
        kar = srv.karlilik_raporu("musteri", [("2026", date(2026, 1, 1), date(2026, 12, 31))],
                                  filtre={"maliyet_yontemi": HAREKETLI})
        hb = srv.musteri_aylik_satis(2026, gosterge="birlikte", filtre={"maliyet_yontemi": HAREKETLI},
                                     bugun=BUGUN)
        self.assertEqual(hb["genel"]["toplam_kar"], kar["toplam"]["kar"])
        self.assertEqual(hb["genel"]["toplam_net"], kar["toplam"]["net"])
        satirlar = [x for x in hb["satirlar"] if not x.get("_sabit")]
        self.assertEqual(sum((x["toplam_kar"] for x in satirlar), D("0")), hb["genel"]["toplam_kar"])
        self.assertEqual(sum((x["ay_1_kar"] for x in satirlar), D("0")), hb["genel"]["ay_1_kar"])

    def test_devir_stok_sonraki_alis_ve_farkli_aydaki_bagli_iade(self):
        from database import satis_yonetici_rapor_service as srv
        from database.satis_maliyet_motoru import DONEMSEL, HAREKETLI

        self.o.urun_ekle("K002", "Devir Ürün")
        self.o.alis(10, 100, date(2026, 1, 1), kod="K002")
        self._tarih_geri_al("K002", date(2025, 12, 20))  # önceki yıldan devreden katman
        self.o.alis(10, 200, date(2026, 1, 5), kod="K002")
        f = self.fatura(date(2026, 1, 10), [_satir(5, 300, kod="K002")])
        self.o.alis(10, 1000, date(2026, 2, 1), kod="K002")  # satıştan sonra: geçmiş maliyeti etkilemez
        self.iade(date(2026, 2, 3), [dict(_satir(1, 300, kod="K002"), kaynak_fatura_satiri_id=f.satirlar[0].id)],
                  kaynak_fatura_id=f.id)

        fifo = self._hucre(srv.musteri_aylik_satis(2026, gosterge="birlikte", bugun=BUGUN))
        self.assertEqual((fifo["ay_1_maliyet"], fifo["ay_2_maliyet"]), (D("500.00"), D("-100.00")))
        self.assertEqual((fifo["ay_2_net"], fifo["ay_2_kar"]), (D("-300.00"), D("-200.00")))
        self.assertEqual(fifo["ay_2_marj"], srv.MARJ_YOK)  # net ≤ 0: marj yok, kâr tutarı gösterilir
        self.assertEqual(fifo["toplam_marj"], D("66.67"))  # 800 / 1200: aylık yüzdeler ortalanmaz

        har = self._hucre(srv.musteri_aylik_satis(2026, gosterge="birlikte", filtre={"maliyet_yontemi": HAREKETLI},
                                                  bugun=BUGUN))
        self.assertEqual((har["ay_1_maliyet"], har["ay_2_maliyet"]), (D("750.00"), D("-150.00")))
        don = self._hucre(srv.musteri_aylik_satis(2026, gosterge="maliyet", filtre={"maliyet_yontemi": DONEMSEL},
                                                  bugun=BUGUN))
        self.assertEqual(don["ay_1"], D("750.00"))  # Ocak: devir 10×100 + giriş 10×200

        # Önceki yıl karşılaştırması aynı yöntemle (önceki yıl satışı yok → 0)
        k = srv.musteri_aylik_satis(2026, gosterge="kar", karsilastirma=[2025],
                                    filtre={"maliyet_yontemi": HAREKETLI}, bugun=BUGUN)
        self.assertEqual(self._hucre(k)["toplam_2025"], D("0"))

        # FIFO katman ayrıntısı: devir katmanından tüketilen miktar
        from database.models.satis_faturasi import SatisFaturasiSatiri

        with get_session() as s:
            sid = s.query(SatisFaturasiSatiri.id).filter(SatisFaturasiSatiri.fatura_id == f.id).scalar()
        a = srv.satir_maliyet_ayrintisi("SATIS", f.id, sid)
        self.assertEqual([(x["giris_tarihi"], x["miktar"], x["birim_maliyet"]) for x in a["katmanlar"]],
                         [(date(2025, 12, 20), D("5"), D("100"))])

    def test_eksik_ve_kismi_maliyet_standart_maliyet_ve_liste(self):
        from database import satis_maliyet_motoru as motor
        from database import satis_yonetici_rapor_service as srv
        from database.satis_maliyet_motoru import STANDART

        self._kontrol_urunu()
        self.fatura(date(2026, 1, 20), [_satir(1, 50)])  # U001
        st = {"maliyet_yontemi": STANDART}
        e = srv.musteri_aylik_satis(2026, gosterge="birlikte", filtre=st, bugun=BUGUN)
        m = self._hucre(e)
        self.assertEqual((m["ay_1_maliyet"], m["ay_1_kar"], m["ay_1_marj"]), (srv.EKSIK_MALIYET,) * 3)
        self.assertEqual(m["ay_1_net"], D("2450.00"))  # satış görünür, sıfır maliyet atanmaz
        self.assertIn("Eksik maliyet: Oca", m["maliyet_durumu"])
        self.assertEqual(len(e["eksik"]), 2)
        self.assertTrue(all("standart maliyet" in x["eksik_nedeni"] for x in e["eksik"]))

        motor.standart_maliyet_kaydet("K001", date(2026, 1, 1), "90")
        motor.standart_maliyet_kaydet("K001", date(2026, 2, 1), "500")  # satış tarihinden sonra: kullanılmaz
        k = self._hucre(srv.musteri_aylik_satis(2026, gosterge="birlikte", filtre=st, bugun=BUGUN))
        self.assertEqual((k["ay_1_maliyet"], k["ay_1_kar"]), (D("1080.00"), D("1320.00")))
        self.assertEqual(k["ay_1_marj"], D("55.00"))  # Kısmi: maliyeti bilinen net satış üzerinden
        self.assertIn("Kısmi: Oca", k["maliyet_durumu"])
        self.assertEqual(len(motor.standart_maliyetler("K001")), 2)

    def test_fatura_irsaliye_maliyeti_bir_kez_sayilir(self):
        from database import satis_yonetici_rapor_service as srv
        from database.satis_faturasi_service import SatisFaturasiService
        from database.satis_irsaliyesi_service import SatisIrsaliyesiService
        from database.satis_maliyet_motoru import HAREKETLI

        self.o.urun_ekle("K003", "İrsaliyeli Ürün")
        self.o.alis(10, 100, date(2026, 1, 3), kod="K003")
        irs = SatisIrsaliyesiService.kaydet(
            {"irsaliye_tarihi": date(2026, 1, 8), "cari_id": self.o.mus_id, "depo": "ANA DEPO"},
            [dict(_satir(4, 250, kod="K003"))])
        SatisIrsaliyesiService.sevk_et(irs.id)
        irs = SatisIrsaliyesiService.getir(irs.id)
        satir = irs.satirlar[0]
        f = SatisFaturasiService.kaydet(
            {"fatura_tarihi": date(2026, 1, 9), "vade_tarihi": date(2026, 1, 9), "cari_id": self.o.mus_id,
             "depo": "ANA DEPO", "irsaliye_id": irs.id, "odeme_tutari": D("0"), "sales_person_id": 1},
            [dict(_satir(4, 250, kod="K003"), irsaliye_satiri_id=satir.id)])
        SatisFaturasiService.onayla(f.id)
        self.assertEqual(self.o.lot_toplam(kod="K003"), D("6"))  # tek stok çıkışı

        for yontem in ("FIFO", HAREKETLI):
            m = self._hucre(srv.musteri_aylik_satis(2026, gosterge="birlikte", filtre={"maliyet_yontemi": yontem},
                                                    bugun=BUGUN))
            self.assertEqual((m["ay_1_net"], m["ay_1_maliyet"], m["ay_1_kar"]),
                             (D("1000.00"), D("400.00"), D("600.00")), yontem)

    def test_bagli_iade_orijinal_satis_maliyeti_kismi_ve_havuz(self):
        from database import satis_yonetici_rapor_service as srv
        from database.satis_maliyet_motoru import HAREKETLI

        self.o.urun_ekle("K004", "İade Ürün")
        self.o.alis(10, 100, date(2026, 1, 3), kod="K004")
        f = self.fatura(date(2026, 1, 10), [_satir(4, 300, kod="K004")])  # ortalama 100
        self.o.alis(10, 300, date(2026, 1, 20), kod="K004")  # satış sonrası ortalama 225
        self.iade(date(2026, 2, 5), [dict(_satir(1, 300, kod="K004"), kaynak_fatura_satiri_id=f.satirlar[0].id)],
                  kaynak_fatura_id=f.id)  # kısmi, farklı ay
        self.fatura(date(2026, 2, 10), [_satir(2, 300, kod="K004")])
        self.iade(date(2026, 2, 12), [_satir(1, 300, kod="K004")])  # bağlantısız

        satirlar = srv.satirlari_getir(date(2026, 1, 1), date(2026, 12, 31), {"maliyet_yontemi": HAREKETLI})
        k = [s for s in satirlar if s.urun_kodu == "K004"]
        bagli = next(s for s in k if s.belge_turu == "IADE" and s.kaynak_bagli)
        self.assertEqual(bagli.toplam_maliyet, D("-100.00"))  # güncel 225 değil, orijinal satışın 100'ü
        self.assertEqual(bagli.tarih, date(2026, 2, 5))
        self.assertIn("ters çevrildi", bagli.maliyet_kaynagi)
        # Havuz bağlı iadeyle 100'den güncellenir: (6×100 + 10×300 + 1×100) / 17
        sat2 = next(s for s in k if s.belge_turu == "SATIS" and s.tarih == date(2026, 2, 10))
        self.assertEqual(sat2.toplam_maliyet, D("435.29"))
        bagsiz = next(s for s in k if s.belge_turu == "IADE" and not s.kaynak_bagli)
        self.assertTrue(bagsiz.maliyet_kaynagi.startswith("kaynaksız iade"))
        self.assertEqual(bagsiz.toplam_maliyet, D("-217.65"))
        ay = self._hucre(srv.musteri_aylik_satis(2026, gosterge="birlikte", filtre={"maliyet_yontemi": HAREKETLI},
                                                 bugun=BUGUN))
        self.assertEqual(ay["ay_2_maliyet"], D("-100.00") + D("435.29") - D("217.65"))
        # Kayıtlı stok hareketleri değişmez
        self.assertEqual(self.o.lot_toplam(kod="K004"), D("16"))

    def test_fifo_katmanlari_fatura_satiri_bazinda(self):
        from database import satis_yonetici_rapor_service as srv

        self.o.urun_ekle("K005", "Çok Satırlı Ürün")
        self.o.alis(5, 100, date(2026, 1, 3), kod="K005")
        self.o.alis(5, 200, date(2026, 1, 4), kod="K005")
        f = self.fatura(date(2026, 1, 10), [_satir(3, 300, kod="K005"), _satir(4, 300, kod="K005")])
        satirlar = srv.fatura_fifo_ayrintisi(f.id)
        self.assertEqual([s["fifo_maliyet"] for s in satirlar], [D("300.00"), D("600.00")])
        self.assertEqual([[(k["miktar"], k["birim_maliyet"]) for k in s["katmanlar"]] for s in satirlar],
                         [[(D("3"), D("100"))], [(D("2"), D("100")), (D("2"), D("200"))]])
        self.assertTrue(all(k["giris_belge_no"] and k["giris_tarihi"] for s in satirlar for k in s["katmanlar"]))
        a = srv.satir_maliyet_ayrintisi("SATIS", f.id, satirlar[1]["satir_id"])
        self.assertEqual(sum((k["tutar"] for k in a["katmanlar"]), D("0")), D("600.00"))
        m = self._hucre(srv.musteri_aylik_satis(2026, gosterge="birlikte", bugun=BUGUN))
        self.assertEqual(m["ay_1_maliyet"], D("900.00"))  # satır toplamları = aylık rapor
        self.assertEqual(m["ay_1_kar"], D("2100.00") - D("900.00"))

    def test_birlikte_yil_karsilastirmasi_dort_olcu(self):
        from database import satis_yonetici_rapor_service as srv
        from database.models.satis_faturasi import SatisFaturasi

        self.o.urun_ekle("K006", "Karşılaştırma Ürün")
        self.o.alis(10, 100, date(2026, 1, 3), kod="K006")
        eski = self.fatura(date(2026, 1, 5), [_satir(2, 200, kod="K006")])
        with get_session() as s:
            s.get(SatisFaturasi, eski.id).fatura_tarihi = date(2025, 1, 5)
        self.fatura(date(2026, 1, 10), [_satir(2, 250, kod="K006")])
        r = srv.musteri_aylik_satis(2026, gosterge="birlikte", karsilastirma=[2025], bugun=BUGUN)
        k = [x for x in r["karsilastirma"] if x["cari_id"] == self.o.mus_id]
        olculer = [x["olcu"] for x in k if x["satir"] == "2026"]
        self.assertEqual(olculer, ["Net", "Maliyet", "Kâr", "Marj %"])

        def satir(olcu, ad):
            return next(x for x in k if x["olcu"] == olcu and x["satir"].startswith(ad))

        self.assertEqual((satir("Net", "2026")["ay_1"], satir("Net", "2025")["ay_1"]), (D("500.00"), D("400.00")))
        self.assertEqual((satir("Net", "Fark")["ay_1"], satir("Net", "Değişim")["ay_1"]), (D("100.00"), "%25,00"))
        self.assertEqual(satir("Net", "Değişim")["ay_2"], srv.MARJ_YOK)  # önceki dönem 0 → yüzde yok
        self.assertEqual(satir("Maliyet", "Fark")["toplam"], D("0.00"))
        self.assertEqual(satir("Kâr", "Fark")["toplam"], D("100.00"))
        self.assertEqual(satir("Marj %", "Fark")["ay_1"], "+10,00 yüzde puan")  # %50 → %60
        self.assertFalse(any(x["olcu"] == "Marj %" and x["satir"] == "Değişim %" for x in k))
        self.assertEqual(satir("Net", "2026")["kapsam"], "01.01.2026–15.03.2026 (devam ediyor)")
        self.assertEqual(satir("Net", "2025")["kapsam"], "01.01.2025–31.12.2025")
        self.assertTrue(any(n.startswith("Kapsanan tarih aralıkları") for n in r["notlar"]))

    def test_yetkisiz_kullanici_maliyet_goremez_ve_ekran(self):
        import tkinter as tk

        import satis_yonetici_rapor_ui as ui
        from database import satis_yonetici_rapor_service as srv
        from database.session_manager import oturum

        self._kontrol_urunu()
        try:
            kok = tk.Tk()
        except tk.TclError:
            self.skipTest("Tk yok")
        kok.withdraw()
        kok.icerik = tk.Frame(kok)
        kok.icerik.pack()
        kok._icerigi_temizle = lambda: [w.destroy() for w in kok.icerik.winfo_children()]
        try:
            with patch("satis_ui._menu_isaretle", lambda _a: None):
                ekran = ui.musteri_aylik_satis_goster(kok, otomatik=False)
            ekran.girdiler["gosterge"].set("Satış + maliyet + kâr + marj")
            ekran.raporla(senkron=True)
            kolonlar = [k.anahtar for k in ekran.tablolar_tanim[0].kolonlar]
            self.assertIn("ay_1_kar", kolonlar)
            self.assertIn("toplam_marj", kolonlar)
            self.assertIn("FIFO", ekran.baslik)
            self.assertIn("Maliyet yöntemi: FIFO", ekran.html_metni())
            # Sütun gizleme: ekranda ve çıktıda gizlenir
            ekran.kolonlari_gizle("satirlar", [f"ay_{i}_maliyet" for i in range(1, 13)])
            self.assertNotIn("Oca Maliyet", ekran.html_metni())
            self.assertIn("Oca Kâr", ekran.html_metni())
            cagri = []
            m = next(r for r in ekran._satirlar["satirlar"] if r.get("cari_id") == self.o.mus_id)
            with patch.object(ui, "karlilik_detay_goster", lambda *a, **k: cagri.append(a)):
                ekran.son_kolon = "ay_1_kar"
                ekran.tablolar_tanim[0].cift_tik(m)
            self.assertEqual((cagri[0][4], cagri[0][5]), (date(2026, 1, 1), date(2026, 1, 31)))
            # Ayrıntı penceresi ve FIFO katmanları
            detay = ui.karlilik_detay_goster(kok, "musteri", self.o.mus_id, "test", date(2026, 1, 1),
                                             date(2026, 1, 31), {"maliyet_yontemi": "FIFO"})
            satir = detay.ekran._satirlar["satirlar"][0]
            self.assertIn("satir_id", satir)
            kp = ui.maliyet_katmanlari_goster(detay, satir)
            self.assertEqual([x["miktar"] for x in kp.ayrinti["katmanlar"]], [D("10"), D("2")])
        finally:
            kok.destroy()

        oturum.set_user(user_id=2, kullanici_adi="satis", ad_soyad="Satış", role_kod="SATIS", role_ad="Satış",
                        permissions={"satis_goruntuleme"})
        for g in ("maliyet", "kar", "marj", "birlikte"):
            with self.assertRaises(ValueError):
                srv.musteri_aylik_satis(2026, gosterge=g, bugun=BUGUN)
        n = srv.musteri_aylik_satis(2026, bugun=BUGUN)
        self.assertEqual(n["eksik"], [])
        self.assertFalse(any(v not in (None, "") for r in n["satirlar"] for k, v in r.items()
                             if k.startswith(("maliyet", "kar_", "marj_"))))
        with self.assertRaises(Exception):
            srv.satir_maliyet_ayrintisi("SATIS", 1, 1)


if __name__ == "__main__":
    unittest.main()
