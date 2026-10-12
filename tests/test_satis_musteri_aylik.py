"""Müşteri bazında yıllık/aylık satış raporu (izole test firması)."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from database.database import get_session
from tests.test_satis_yonetici_raporlari import _satir, _Taban

D = Decimal
BUGUN = date(2026, 3, 15)
YIL = ("2026", date(2026, 1, 1), date(2026, 12, 31))


class MusteriAylikTest(_Taban):
    def _tarih_tasi(self, fatura, tarih):
        from database.models.satis_faturasi import SatisFaturasi

        with get_session() as s:
            s.get(SatisFaturasi, fatura.id).fatura_tarihi = tarih

    def test_aylar_yillik_ve_karlilik_raporuyla_eslesir(self):
        from database import satis_yonetici_rapor_service as srv

        self.senaryo()
        r = srv.musteri_aylik_satis(2026, bugun=BUGUN)
        satirlar = [x for x in r["satirlar"] if not x.get("_sabit")]
        genel = r["satirlar"][-1]
        self.assertTrue(genel["_sabit"])
        m1 = next(x for x in satirlar if x["cari_id"] == self.o.mus_id)
        # Ocak: 256,50 satış − 128,25 iade (kendi tarihinde) + 30 eksik maliyetli; taslak sayılmaz
        self.assertEqual(m1["ay_1"], D("158.25"))
        self.assertEqual(m1["ay_2"], D("0"))
        self.assertEqual(m1["ay_3"], D("0"))  # gerçekleşmiş sıfır (ay devam ediyor)
        self.assertEqual(m1["ay_4"], srv.HENUZ_GELMEDI)
        self.assertEqual(m1["ay_12"], srv.HENUZ_GELMEDI)
        self.assertIn("Mart ayı tamamlanmadı", " ".join(r["notlar"]))

        kar = srv.karlilik_raporu("musteri", [YIL])
        for x in satirlar:
            aylik = sum((x[f"ay_{i}"] for i in range(1, 13) if not isinstance(x[f"ay_{i}"], str)), D("0"))
            self.assertEqual(aylik, x["toplam"])
            k = next(y for y in kar["satirlar"] if y["cari_id"] == x["cari_id"])
            self.assertEqual(x["toplam"], k["net"])
        self.assertEqual(genel["toplam"], kar["toplam"]["net"])
        for i in (1, 2, 3):
            self.assertEqual(genel[f"ay_{i}"], sum((x[f"ay_{i}"] for x in satirlar), D("0")))

        kr = srv.musteri_aylik_satis(2026, gosterge="kar", bugun=BUGUN)
        self.assertEqual(kr["satirlar"][-1]["toplam"], kar["toplam"]["kar"])
        self.assertIn("Kısmi: Oca", next(x for x in kr["satirlar"] if x["cari_id"] == self.o.mus_id)
                      ["maliyet_durumu"])
        mj = srv.musteri_aylik_satis(2026, gosterge="marj", bugun=BUGUN)
        g = mj["satirlar"][-1]
        self.assertEqual(g["toplam"], kar["toplam"]["marj"])  # toplam kâr / toplam maliyetli net
        aylik_marjlar = [g[f"ay_{i}"] for i in (1, 2) if g[f"ay_{i}"] is not None]
        self.assertNotEqual(g["toplam"], sum(aylik_marjlar) / len(aylik_marjlar))  # basit ortalama değil

        fat = srv.musteri_aylik_satis(2026, gosterge="fatura", bugun=BUGUN)
        f1 = next(x for x in fat["satirlar"] if x["cari_id"] == self.o.mus_id)
        self.assertEqual((f1["ay_1"], f1["toplam"]), (2, 2))  # taslak ve iade belgesi sayılmaz
        self.assertEqual(fat["satirlar"][-1]["toplam"], 3)

    def test_gecmis_yil_karsilastirma_ve_ayni_tarihe_kadar(self):
        from database import satis_yonetici_rapor_service as srv

        self.fatura(date(2026, 1, 10), [_satir(2, 100)])
        self._tarih_tasi(self.fatura(date(2026, 1, 11), [_satir(1, 100)]), date(2025, 1, 11))
        self._tarih_tasi(self.fatura(date(2026, 1, 12), [_satir(1, 50)]), date(2025, 3, 20))
        self._tarih_tasi(self.fatura(date(2026, 1, 13), [_satir(1, 70)]), date(2025, 6, 1))

        r = srv.musteri_aylik_satis(2026, karsilastirma=[2025], bugun=BUGUN)
        m = next(x for x in r["satirlar"] if x["cari_id"] == self.o.mus_id)
        self.assertEqual((m["toplam"], m["toplam_2025"], m["fark_2025"]), (D("200.00"), D("220.00"), D("-20.00")))
        self.assertEqual(m["yuzde_2025"], D("-9.09"))
        k = [x for x in r["karsilastirma"] if x["cari_id"] == self.o.mus_id]
        self.assertEqual([x["satir"] for x in k], ["2026", "2025", "Fark (2026 − 2025)", "Değişim %"])
        self.assertEqual((k[1]["ay_1"], k[1]["ay_6"]), (D("100.00"), D("70.00")))
        self.assertEqual((k[2]["ay_1"], k[3]["ay_1"]), (D("100.00"), "%100,00"))
        self.assertIsNone(k[2]["ay_6"])  # 2026 Haziran henüz gelmedi: fark yok

        a = srv.musteri_aylik_satis(2026, karsilastirma=[2025], ayni_tarihe_kadar=True, bugun=BUGUN)
        m = next(x for x in a["satirlar"] if x["cari_id"] == self.o.mus_id)
        self.assertEqual(m["toplam_2025"], D("100.00"))  # 20.03 ve 01.06 satışları 15.03 sonrası
        k = [x for x in a["karsilastirma"] if x["cari_id"] == self.o.mus_id]
        self.assertEqual((k[1]["ay_3"], k[1]["ay_4"]), (D("0"), srv.KAPSAM_DISI))
        self.assertTrue(any("15.03" in n for n in a["notlar"]))

        tam = srv.musteri_aylik_satis(2025, bugun=BUGUN)  # geçmiş yıl: gelecek ay yok
        self.assertFalse(any(isinstance(v, str) for kk, v in tam["satirlar"][-1].items() if kk.startswith("ay_")))

    def test_unvan_degisikligi_satissiz_musteri_siralama_ve_doviz(self):
        from database import satis_yonetici_rapor_service as srv
        from database.models.cari import Cari

        self.fatura(date(2026, 1, 10), [_satir(1, 100)])
        with get_session() as s:
            s.get(Cari, self.o.mus_id).unvan = "Yeni Unvan A.Ş."
        self.fatura(date(2026, 2, 10), [_satir(1, 40)])
        with patch("database.doviz_service.DovizService.kur_degeri", return_value=D("48")):
            self.fatura(date(2026, 2, 16), [dict(_satir(1, 480), tl_esas=True)], cari_id=self.m2,
                        para_birimi="USD", kur=D("48"), kur_tarihi=date(2026, 2, 16), kur_sabitlendi=True,
                        kur_kaynagi="TCMB")
        r = srv.musteri_aylik_satis(2026, bugun=BUGUN)
        satir = [x for x in r["satirlar"] if x["cari_id"] == self.o.mus_id]
        self.assertEqual(len(satir), 1)
        self.assertEqual((satir[0]["ay_1"], satir[0]["ay_2"]), (D("100.00"), D("40.00")))
        self.assertEqual([x["cari_id"] for x in r["satirlar"][:-1]], [self.m2, self.o.mus_id])  # toplam büyükten
        ay = srv.musteri_aylik_satis(2026, siralama="ay", siralama_ay=1, bugun=BUGUN)
        self.assertEqual(ay["satirlar"][0]["cari_id"], self.o.mus_id)

        usd = srv.musteri_aylik_satis(2026, para_birimi="USD", bugun=BUGUN)
        self.assertEqual([(x["cari_id"], x["toplam"]) for x in usd["satirlar"][:-1]], [(self.m2, D("10.00"))])
        self.assertEqual(usd["birim"], "USD")
        tl = srv.musteri_aylik_satis(2026, para_birimi="TRY", bugun=BUGUN)
        self.assertEqual([x["cari_id"] for x in tl["satirlar"][:-1]], [self.o.mus_id])

        with get_session() as s:
            c = Cari(cari_kodu="M009", unvan="Hareketsiz Müşteri", cari_turu="Müşteri", aktif=True)
            s.add(c)
            s.flush()
            bos_id = int(c.id)
        gizli = srv.musteri_aylik_satis(2026, bugun=BUGUN)
        self.assertNotIn(bos_id, [x["cari_id"] for x in gizli["satirlar"]])
        acik = srv.musteri_aylik_satis(2026, satissizlar=True, bugun=BUGUN)
        bos = next(x for x in acik["satirlar"] if x["cari_id"] == bos_id)
        self.assertEqual((bos["ay_1"], bos["toplam"], bos["ay_5"]), (D("0"), D("0"), srv.HENUZ_GELMEDI))

    def test_yetkisiz_kar_gostergesi_reddedilir(self):
        from database import satis_yonetici_rapor_service as srv
        from database.session_manager import oturum

        oturum.set_user(user_id=2, kullanici_adi="satis", ad_soyad="Satış", role_kod="SATIS", role_ad="Satış",
                        permissions={"satis_goruntuleme"})
        with self.assertRaises(ValueError):
            srv.musteri_aylik_satis(2026, gosterge="kar", bugun=BUGUN)
        self.assertEqual(srv.musteri_aylik_satis(2026, bugun=BUGUN)["satirlar"][-1]["unvan"], "GENEL TOPLAM")

    def test_ekran_hucre_ayrintisi_sabit_toplam_ve_yatay_cikti(self):
        import tkinter as tk

        import satis_yonetici_rapor_ui as ui
        from satis_ui import RAPOR_KARTLARI

        self.assertIn("musteri_aylik", [k[2] for k in RAPOR_KARTLARI])
        self.senaryo()
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
            ekran.girdiler["k1"].set(True)
            ekran.raporla(senkron=True)
            tablo_tanim = ekran.tablolar_tanim[0]
            self.assertEqual(ekran._satirlar["satirlar"][-1]["unvan"], "GENEL TOPLAM")
            ekran._sirala_tikla(tablo_tanim, "unvan")
            ekran._sirala_tikla(tablo_tanim, "unvan")
            self.assertEqual(ekran._satirlar["satirlar"][-1]["unvan"], "GENEL TOPLAM")
            self.assertIn("Henüz gelmedi", ekran.html_metni())
            self.assertIn("landscape", ekran.html_metni())
            yol = os.path.join(tempfile.mkdtemp(), "a.xlsx")
            ekran.excel_yaz(yol)
            from openpyxl import load_workbook

            self.assertEqual(load_workbook(yol).worksheets[0].page_setup.orientation, "landscape")

            cagri = []
            m1 = next(r for r in ekran._satirlar["satirlar"] if r.get("cari_id") == self.o.mus_id)
            with patch.object(ui, "karlilik_detay_goster", lambda *a, **k: cagri.append(a)):
                ekran.son_kolon = "ay_1"
                tablo_tanim.cift_tik(m1)
                ekran.son_kolon = "ay_12"
                tablo_tanim.cift_tik(m1)  # gelecek ay: ayrıntı açılmaz
            self.assertEqual(len(cagri), 1)
            self.assertEqual((cagri[0][2], cagri[0][4], cagri[0][5]),
                             (self.o.mus_id, date(2026, 1, 1), date(2026, 1, 31)))
            self.assertEqual(ekran.filtre_degerleri()["yil"], "2026")  # rapor filtreleri korunur
        finally:
            kok.destroy()


if __name__ == "__main__":
    unittest.main()
