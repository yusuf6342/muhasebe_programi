"""Satın Alma → Raporlar 9–11: teslimat performansı, talep takibi, açık alış faturaları ve valör."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from database import satin_alma_rapor_service as srv
from database.database import get_session
from database.models.cari import Cari, CariIslem, SatisHareketi
from tests.stok_test_ortami import StokOrtami
from tests.test_satin_alma_talep import BUGUN as TALEP_BUGUN, _TalepTemel

D = Decimal
BUGUN = date(2026, 6, 15)


def _sayac():
    with get_session() as s:
        return (s.scalar(select(func.count(SatisHareketi.id))), s.scalar(select(func.count(CariIslem.id))))


def _tk_kok():
    import tkinter as tk

    kok = tk.Tk()
    kok.withdraw()
    kok.icerik = tk.Frame(kok)
    kok.icerik.pack()
    kok._icerigi_temizle = lambda: [w.destroy() for w in kok.icerik.winfo_children()]
    kok.rapor_tedarikci_bakiye_durum = kok.rapor_tedarikci_ekstresi = lambda: None
    kok.rapor_stok_detayli_tedarikci_ekstre = kok.rapor_tahsilat_odeme = lambda: None
    return kok


class _Taban(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self.__class__.__name__)

    def tearDown(self):
        self.o.kapat()

    def tedarikci_ekle(self, kod="T002", unvan="İkinci Tedarikçi") -> int:
        with get_session() as s:
            c = Cari(cari_kodu=kod, unvan=unvan, cari_turu="Tedarikçi", aktif=True)
            s.add(c)
            s.flush()
            return int(c.id)

    def alis_kaydet(self, cari_id, tarih, fiyat, vade, **baslik):
        from database.alis_faturasi_service import AlisFaturasiService

        veriler = {"fatura_tarihi": tarih, "vade_tarihi": vade, "cari_id": cari_id, "depo": "ANA DEPO",
                   "odeme_tutari": D("0"), **baslik}
        return AlisFaturasiService.kaydet(veriler, [
            {"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": D("1"), "birim": "Adet",
             "birim_fiyat": D(str(fiyat)), "iskonto_orani": D("0"), "kdv_orani": D("20"), "lot_no": ""}])

    def odeme(self, cari_id, tarih, tutar, no):
        with get_session() as s:
            s.add(CariIslem(cari_id=cari_id, tarih=tarih, islem_turu="Ödeme", belge_no=no, borc=D("0"),
                            alacak=D(str(tutar)), aciklama="test"))


class TeslimatPerformansiTest(_Taban):
    def _siparis(self, no, termin, miktar):
        from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri

        with get_session() as s:
            sp = AlisSiparisi(siparis_no=no, siparis_tarihi=date(2026, 5, 15), termin_tarihi=termin,
                              cari_id=self.o.ted_id, durum="AÇIK")
            s.add(sp)
            s.flush()
            st = AlisSiparisiSatiri(siparis_id=sp.id, urun_kodu="U001", urun_adi="Test Ürün", miktar=D(miktar),
                                    birim="Adet", birim_alis_fiyati=D("50"))
            s.add(st)
            s.flush()
            return int(st.id)

    def _irsaliye(self, no, tarih, miktar, sid, durum="AÇIK"):
        from database.models.alis_irsaliyesi import AlisIrsaliyesi, AlisIrsaliyesiSatiri

        with get_session() as s:
            irs = AlisIrsaliyesi(irsaliye_no=no, irsaliye_tarihi=tarih, cari_id=self.o.ted_id, durum=durum)
            s.add(irs)
            s.flush()
            st = AlisIrsaliyesiSatiri(irsaliye_id=irs.id, urun_kodu="U001", urun_adi="Test Ürün", miktar=D(miktar),
                                      birim="Adet", birim_fiyat=D("50"), siparis_satiri_id=sid)
            s.add(st)
            s.flush()
            return int(st.id)

    def _fatura(self, no, tarih, miktar, sid, irs_satir=None):
        from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri

        with get_session() as s:
            f = AlisFaturasi(fatura_no=no, fatura_tarihi=tarih, vade_tarihi=tarih, cari_id=self.o.ted_id,
                             durum="AÇIK")
            s.add(f)
            s.flush()
            s.add(AlisFaturasiSatiri(fatura_id=f.id, urun_kodu="U001", urun_adi="Test Ürün", miktar=D(miktar),
                                     birim="Adet", birim_fiyat=D("50"), siparis_satiri_id=sid,
                                     irsaliye_satiri_id=irs_satir))

    def test_kismi_teslimat_gecikme_ve_tarihsiz(self):
        once = _sayac()
        s1 = self._siparis("SP-1", date(2026, 6, 1), 10)
        irs1 = self._irsaliye("IRS-1", date(2026, 5, 25), 4, s1)
        self._fatura("AF-IRS", date(2026, 5, 26), 4, s1, irs1)  # irsaliyenin faturası: ikinci teslimat değil
        self._fatura("AF-DOG", date(2026, 6, 5), 6, s1)  # irsaliyesiz doğrudan fatura, 4 gün gecikme
        self._irsaliye("IRS-IPT", date(2026, 5, 20), 10, s1, durum="İPTAL")
        s2 = self._siparis("SP-2", date(2026, 6, 1), 5)
        self._irsaliye("IRS-2", date(2026, 5, 30), 5, s2)
        s4 = self._siparis("SP-4", date(2026, 6, 10), 8)
        self._irsaliye("IRS-4", date(2026, 6, 8), 3, s4)
        self._siparis("SP-5", date(2026, 7, 1), 3)

        r = srv.tedarikci_teslimat_performansi(bugun=BUGUN)
        sat = {x["siparis_no"]: x for x in r["satirlar"]}
        self.assertEqual((sat["SP-1"]["teslim"], sat["SP-1"]["kalan"]), (D("10"), D("0")))
        self.assertEqual(sat["SP-1"]["durum"], "Gecikmeli tam")
        self.assertEqual(sat["SP-1"]["gecikme"], 4)
        self.assertEqual(sat["SP-1"]["teslimat_sayisi"], 2)
        self.assertEqual(sat["SP-1"]["zamaninda_miktar"], D("4"))
        self.assertEqual(sat["SP-2"]["durum"], "Zamanında tam")
        self.assertEqual(sat["SP-4"]["durum"], "Gecikmede — kısmi teslim")
        self.assertEqual((sat["SP-4"]["gecikme"], sat["SP-4"]["kalan"]), (5, D("5")))
        self.assertEqual(sat["SP-5"]["durum"], "Süresi dolmadı")

        tes = [t for t in r["teslimatlar"] if t["siparis_no"] == "SP-1"]
        self.assertEqual([(t["teslimat_turu"], t["gecikme"], t["kismi"]) for t in tes],
                         [("İrsaliye", -7, "Kısmi"), ("Fatura", 4, "Kısmi")])
        self.assertEqual(len(r["teslimatlar"]), 4)

        o = r["tedarikciler"][0]
        self.assertEqual((o["degerlendirilen"], o["zamaninda"], o["gecikmeli"]), (3, 1, 2))
        self.assertEqual((o["acik_geciken"], o["tarihsiz"], o["suresi_dolmadi"]), (1, 0, 1))
        self.assertEqual(o["zamaninda_oran"], D("33.33"))
        self.assertEqual(o["miktar_oran"], D("52.17"))  # (4 + 5 + 3) / (10 + 5 + 8)
        self.assertEqual(o["ort_gecikme"], D("4.0"))
        self.assertEqual(o["kismi_satir"], 2)
        self.assertEqual(o["en_cok_gecikme"], 5)
        self.assertEqual(_sayac(), once)

    def test_tarih_ve_tedarikci_filtresi(self):
        s1 = self._siparis("SP-F", date(2026, 6, 1), 2)
        self._irsaliye("IRS-F", date(2026, 6, 1), 2, s1)
        self.assertEqual(len(srv.tedarikci_teslimat_performansi(bas=date(2026, 5, 16), bugun=BUGUN)["satirlar"]), 0)
        self.assertEqual(len(srv.tedarikci_teslimat_performansi(cari_id=self.tedarikci_ekle(),
                                                                bugun=BUGUN)["satirlar"]), 0)
        self.assertEqual(len(srv.tedarikci_teslimat_performansi(arama="SP-F", bugun=BUGUN)["satirlar"]), 1)


class AcikFaturaValorTest(_Taban):
    def _kur(self):
        """F1 kısmi ödemeli gecikmiş, F2 bugün vadeli, F3 ileri vadeli, DEVIR-1 vadesiz (fatura dışı)."""
        self.f1 = self.alis_kaydet(self.o.ted_id, date(2026, 5, 1), 100, date(2026, 5, 31))
        self.f2 = self.alis_kaydet(self.o.ted_id, date(2026, 6, 1), 100, BUGUN)
        self.f3 = self.alis_kaydet(self.o.ted_id, date(2026, 6, 10), 100, date(2026, 7, 10))
        with get_session() as s:
            s.add(SatisHareketi(cari_id=self.o.ted_id, satis_tarihi=date(2026, 6, 2), belge_no="DEVIR-1",
                                satis_tutari=D("100"), kalan_acik_tutar=D("100")))
        self.odeme(self.o.ted_id, date(2026, 6, 5), 50, "OD-1")
        self.odeme(self.o.ted_id, date(2026, 7, 1), 1000, "OD-SONRA")

    def test_kismi_odeme_eksik_vade_ve_agirlikli_valor(self):
        self._kur()
        once = _sayac()
        r = srv.acik_alis_faturalari_valor(rapor_tarihi=BUGUN)
        k = {x["fatura_no"]: x for x in r["kalemler"]}
        a = k[self.f1.fatura_no]
        self.assertEqual((a["fatura_tutari"], a["kapatilan"], a["acik"]), (D("120.00"), D("50.00"), D("70.00")))
        self.assertEqual((a["fatura_yasi"], a["vade_gunu"], a["valor"]), (45, 30, -15))
        self.assertEqual((a["durum"], a["yas_grubu"]), ("Vadesi geçmiş", "8–30"))
        self.assertEqual((k[self.f2.fatura_no]["valor"], k[self.f2.fatura_no]["durum"]), (0, "Bugün vadeli"))
        self.assertEqual((k[self.f3.fatura_no]["valor"], k[self.f3.fatura_no]["yas_grubu"]), (25, "8–30"))
        dv = k["DEVIR-1"]
        self.assertIsNone(dv["vade_tarihi"])
        self.assertIsNone(dv["valor"])
        self.assertEqual(dv["durum"], "Vade tanımlanmamış")

        o = r["tedarikciler"][0]
        self.assertEqual(o["para_birimi"], "TRY")
        self.assertEqual(o["acik"], D("410.00"))
        self.assertEqual((o["gecmis_tutar"], o["gecmis_gun"]), (D("70.00"), D("15.0")))
        self.assertEqual(o["bugun_tutar"], D("120.00"))
        self.assertEqual((o["gelmemis_tutar"], o["gelmemis_gun"]), (D("120.00"), D("25.0")))
        self.assertEqual(o["vadesiz_tutar"], D("100.00"))
        # (70 × −15 + 120 × 0 + 120 × 25) / 310 — vadesiz 100 ortalamaya girmez, kalan açık tutarla ağırlıklı
        self.assertEqual(o["valor"], D("6.3"))
        self.assertEqual((o["g_8"], o["i_8"], o["g_1"]), (D("70.00"), D("120.00"), D("0.00")))
        self.assertEqual(r["avanslar"], [])

        borc = srv.tedarikci_borc_vade(bugun=BUGUN)["satirlar"][0]
        self.assertEqual(borc["acik"], o["acik_tl"])
        self.assertEqual(len(srv.tedarikci_borc_detay(self.o.ted_id, bugun=BUGUN)["kalemler"]), len(r["kalemler"]))

        self.assertEqual([x["fatura_no"] for x in srv.acik_alis_faturalari_valor(
            rapor_tarihi=BUGUN, durum="vadesiz")["kalemler"]], ["DEVIR-1"])
        gecmis = srv.acik_alis_faturalari_valor(rapor_tarihi=BUGUN, durum="gecmis")
        self.assertEqual(len(gecmis["kalemler"]), 1)
        self.assertEqual(gecmis["tedarikciler"][0]["acik"], D("410.00"))  # özet filtreden bağımsız
        self.assertEqual(_sayac(), once)

    def test_gecmis_rapor_tarihi_sonraki_odemeyi_uygulamaz(self):
        self._kur()
        r = srv.acik_alis_faturalari_valor(rapor_tarihi=date(2026, 6, 3))
        k = {x["fatura_no"]: x for x in r["kalemler"]}
        self.assertNotIn(self.f3.fatura_no, k)  # rapor tarihinden sonraki fatura yok
        self.assertEqual(k[self.f1.fatura_no]["acik"], D("120.00"))  # 05.06 ödemesi henüz yok
        self.assertEqual((k[self.f1.fatura_no]["valor"], k[self.f1.fatura_no]["yas_grubu"]), (-3, "1–7"))
        self.assertEqual(r["tedarikciler"][0]["acik"], D("340.00"))
        self.assertEqual(srv.tedarikci_borc_vade(bugun=date(2026, 6, 3))["satirlar"][0]["acik"], D("340.00"))

        sonra = srv.acik_alis_faturalari_valor(rapor_tarihi=date(2026, 7, 5))
        self.assertEqual(sonra["kalemler"], [])
        self.assertEqual(sum(a["tutar"] for a in sonra["avanslar"]), D("590.00"))  # 1050 ödeme − 460 borç

    def test_avans_faturayi_kapatmaz_ve_vade_dilimleri(self):
        self.odeme(self.o.ted_id, date(2026, 1, 5), 30, "AVANS")
        f = self.alis_kaydet(self.o.ted_id, date(2026, 2, 1), 100, date(2026, 3, 1))
        self.alis_kaydet(self.o.ted_id, date(2026, 6, 14), 100, date(2026, 10, 1))
        r = srv.acik_alis_faturalari_valor(rapor_tarihi=BUGUN)
        k = {x["fatura_no"]: x for x in r["kalemler"]}
        self.assertEqual(k[f.fatura_no]["acik"], D("120.00"))
        self.assertEqual(k[f.fatura_no]["yas_grubu"], "90+")
        o = r["tedarikciler"][0]
        self.assertEqual((o["g_91"], o["i_91"]), (D("120.00"), D("120.00")))
        self.assertEqual([a["tutar"] for a in r["avanslar"]], [D("30.00")])

    def test_doviz_ayri_toplanir(self):
        t2 = self.tedarikci_ekle()
        self.alis_kaydet(self.o.ted_id, date(2026, 6, 1), 100, date(2026, 6, 10))
        usd = self.alis_kaydet(t2, date(2026, 6, 1), 10, date(2026, 6, 25), para_birimi="USD", kur=D("40"))
        self.odeme(t2, date(2026, 6, 5), 120, "OD-USD")
        r = srv.acik_alis_faturalari_valor(rapor_tarihi=BUGUN)
        k = {x["fatura_no"]: x for x in r["kalemler"]}[usd.fatura_no]
        self.assertEqual(k["para_birimi"], "USD")
        self.assertEqual((k["fatura_tutari"], k["acik"]), (D("480.00"), D("360.00")))
        self.assertEqual((k["fatura_tutari_doviz"], k["acik_doviz"]), (D("12.00"), D("9.00")))
        oz = {x["para_birimi"]: x for x in r["toplamlar"]}
        self.assertEqual(set(oz), {"TRY", "USD"})
        self.assertEqual((oz["USD"]["acik"], oz["USD"]["acik_tl"], oz["USD"]["gelmemis_gun"]),
                         (D("9.00"), D("360.00"), D("10.0")))
        self.assertEqual((oz["TRY"]["acik"], oz["TRY"]["gecmis_gun"]), (D("120.00"), D("5.0")))
        self.assertEqual({x["para_birimi"] for x in srv.acik_alis_faturalari_valor(
            rapor_tarihi=BUGUN, para_birimi="USD")["kalemler"]}, {"USD"})

    def test_ekranlar_ve_hub_kartlari(self):
        import tkinter as tk

        import satin_alma_rapor_ui as ui
        from satin_alma_ui import RAPOR_KARTLARI, _rapor_komutlar

        self.alis_kaydet(self.o.ted_id, date(2026, 5, 1), 100, date(2026, 5, 31))
        self.alis_kaydet(self.o.ted_id, date(2026, 6, 1), 100, date(2026, 6, 30))
        with get_session() as s:
            s.add(SatisHareketi(cari_id=self.o.ted_id, satis_tarihi=date(2026, 6, 2), belge_no="DEVIR-1",
                                satis_tutari=D("100"), kalan_acik_tutar=D("100")))
        try:
            kok = _tk_kok()
        except tk.TclError:
            self.skipTest("Tk yok")
        try:
            anahtarlar = {k[2] for k in RAPOR_KARTLARI}
            self.assertTrue({"teslimat_perf", "talep_takip", "acik_valor"} <= anahtarlar)
            self.assertTrue({"teslimat_perf", "talep_takip", "acik_valor"} <= set(_rapor_komutlar(kok)))
            ekran = ui.acik_alis_faturalari_valor_goster(kok, otomatik=False)
            ekran.raporla(senkron=True)
            self.assertEqual(len(ekran.tablolar["kalemler"].get_children()), 3)
            self.assertIn("Vade tanımlanmamış", ekran.html_metni())
            yol = os.path.join(tempfile.mkdtemp(), "v.xlsx")
            ekran.excel_yaz(yol)
            self.assertTrue(os.path.getsize(yol) > 0)
            ekran = ui.tedarikci_teslimat_performansi_goster(kok, otomatik=False)
            ekran.raporla(senkron=True)
            self.assertIn("notlar", ekran.sonuc)
        finally:
            kok.destroy()


class FaturaBaglantisiTest(_Taban):
    """Belirli faturaya bağlı ödeme önce o faturayı kapatır; bağlantısız ödeme FIFO; geçmiş tarih."""

    def _hareket_id(self, fatura_no):
        with get_session() as s:
            return s.scalar(select(SatisHareketi.id).where(SatisHareketi.belge_no == fatura_no))

    def _kapatma(self, odeme_no, fatura_no, tutar, tarih, yontem="MANUEL", **ek):
        from database.models.cari import CariKapatma

        with get_session() as s:
            k = CariKapatma(islem_kimligi=f"k-{odeme_no}-{fatura_no}", cari_id=self.o.ted_id, kaynak_belge_no=odeme_no,
                            kaynak_tur="ODEME", hedef_hareket_id=self._hareket_id(fatura_no), hedef_belge_no=fatura_no,
                            tutar=D(str(tutar)), tarih=tarih, yontem=yontem, **ek)
            s.add(k)
            s.flush()
            return int(k.id)

    def _durum(self):
        from database.models.cari import CariKapatma

        with get_session() as s:
            return (s.scalar(select(func.count(CariKapatma.id))),
                    tuple(s.scalars(select(SatisHareketi.kalan_acik_tutar).order_by(SatisHareketi.id))))

    def _kur(self):
        self.f1 = self.alis_kaydet(self.o.ted_id, date(2026, 5, 1), 100, date(2026, 5, 31))
        self.f2 = self.alis_kaydet(self.o.ted_id, date(2026, 5, 10), 100, date(2026, 6, 10))
        self.odeme(self.o.ted_id, date(2026, 6, 5), 100, "OD-BAGLI")
        self.bag = self._kapatma("OD-BAGLI", self.f2.fatura_no, 100, date(2026, 6, 5))
        self.odeme(self.o.ted_id, date(2026, 6, 6), 30, "OD-SERBEST")
        self._kapatma("OD-SERBEST", self.f1.fatura_no, 30, date(2026, 6, 6), yontem="FIFO")

    def _acik(self, tarih):
        r = srv.acik_alis_faturalari_valor(rapor_tarihi=tarih)
        return r, {k["fatura_no"]: k for k in r["kalemler"]}

    def test_bagli_kismi_odeme_ve_bagsiz_fifo(self):
        self._kur()
        once = self._durum()
        r, k = self._acik(BUGUN)
        # FIFO olsaydı 130 önce F1'i kapatırdı; bağlı 100 F2'ye, bağlantısız 30 F1'e düşer.
        self.assertEqual((k[self.f2.fatura_no]["acik"], k[self.f2.fatura_no]["kapatilan"]), (D("20.00"), D("100.00")))
        self.assertEqual(k[self.f2.fatura_no]["kapanis"], srv.YONTEM_BAGLI)
        self.assertEqual((k[self.f1.fatura_no]["acik"], k[self.f1.fatura_no]["kapanis"]), (D("90.00"), srv.YONTEM_FIFO))
        self.assertEqual(r["tedarikciler"][0]["acik"], D("110.00"))
        self.assertTrue(any("Faturaya bağlı" in n for n in r["notlar"]))

        borc = srv.tedarikci_borc_vade(bugun=BUGUN)["satirlar"][0]
        self.assertEqual((borc["acik"], borc["kapanan"]), (D("110.00"), D("130.00")))
        detay = {x["belge_no"]: x for x in srv.tedarikci_borc_detay(self.o.ted_id, bugun=BUGUN)["kalemler"]}
        self.assertEqual(detay[self.f2.fatura_no]["kapanis"], srv.YONTEM_BAGLI)
        self.assertEqual(self._durum(), once)  # rapor kayıtlı bağlantıları ve kalanları değiştirmez

    def test_gecmis_tarih_sonraki_islem_ve_baglanti_iptali(self):
        self._kur()
        _r, k = self._acik(date(2026, 6, 5))
        self.assertEqual(k[self.f1.fatura_no]["acik"], D("120.00"))  # 06.06 bağlantısız ödeme henüz yok
        self.assertEqual(k[self.f2.fatura_no]["acik"], D("20.00"))
        _r, k = self._acik(date(2026, 6, 4))
        self.assertEqual((k[self.f1.fatura_no]["acik"], k[self.f2.fatura_no]["acik"]), (D("120.00"), D("120.00")))

        from datetime import datetime

        from database.models.cari import CariKapatma

        with get_session() as s:
            kayit = s.get(CariKapatma, self.bag)
            kayit.iptal, kayit.iptal_zamani = True, datetime(2026, 6, 20, 10, 0)
        _r, k = self._acik(BUGUN)  # iptal rapor tarihinden sonra: bağlantı o tarihte geçerli
        self.assertEqual(k[self.f2.fatura_no]["acik"], D("20.00"))
        r, k = self._acik(date(2026, 6, 25))  # iptalden sonra ödemeler FIFO ile değerlendirilir
        self.assertNotIn(self.f1.fatura_no, k)
        self.assertEqual((k[self.f2.fatura_no]["acik"], k[self.f2.fatura_no]["kapanis"]), (D("110.00"), srv.YONTEM_FIFO))

    def test_sonradan_yapilan_baglanti_gecmise_uygulanmaz(self):
        f1 = self.alis_kaydet(self.o.ted_id, date(2026, 5, 1), 100, date(2026, 5, 31))
        f2 = self.alis_kaydet(self.o.ted_id, date(2026, 5, 10), 100, date(2026, 6, 10))
        self.odeme(self.o.ted_id, date(2026, 6, 5), 50, "OD-GEC")
        self._kapatma("OD-GEC", f2.fatura_no, 50, date(2026, 6, 20))
        _r, k = self._acik(BUGUN)
        self.assertEqual((k[f1.fatura_no]["acik"], k[f2.fatura_no]["acik"]), (D("70.00"), D("120.00")))
        _r, k = self._acik(date(2026, 6, 25))
        self.assertEqual((k[f1.fatura_no]["acik"], k[f2.fatura_no]["acik"]), (D("120.00"), D("70.00")))


class TalepTakibiTest(_TalepTemel):
    def test_talep_siparis_teslimat_baglantilari(self):
        from database.alis_irsaliyesi_service import AlisIrsaliyesiService
        from database.alis_siparisi_service import AlisSiparisiService
        from database.satin_alma_talep_service import SatinAlmaTalepService as S

        tid, sid = self._onayli_talep()
        sip = self._siparis(S.siparis_satirlari_hazirla({sid: "6"})["satirlar"])
        sip_satir = AlisSiparisiService.getir(sip.id).satirlar[0]
        AlisIrsaliyesiService.kaydet(
            {"irsaliye_tarihi": TALEP_BUGUN, "cari_id": self.cari_id, "siparis_id": sip.id},
            [{"urun_kodu": "U001", "urun_adi": "Vida", "miktar": Decimal("4"), "birim": "Adet",
              "birim_fiyat": Decimal("2"), "kdv_orani": Decimal("20"), "siparis_satiri_id": sip_satir.id}])
        bekleyen = self._talep()

        r = srv.satin_alma_talep_takibi()
        x = next(s for s in r["satirlar"] if s["talep_id"] == tid)
        self.assertEqual((x["talep"], x["onayli"], x["siparis"], x["karsilanan"], x["kalan"]),
                         (D("10"), D("10"), D("6"), D("4"), D("4")))
        self.assertEqual(x["siparisler"], sip.siparis_no)
        b = [z for z in r["baglantilar"] if z["talep_id"] == tid]
        self.assertEqual([z["seviye"].strip() for z in b], ["Sipariş", "└ Teslimat"])
        self.assertEqual((b[0]["belge_id"], b[1]["_tur"], b[1]["miktar"]), (sip.id, "İrsaliye", D("4")))

        tb = next(s for s in r["satirlar"] if s["talep_id"] == bekleyen)
        self.assertEqual((tb["onayli"], tb["siparis"]), (D("0"), D("0")))
        self.assertEqual({s["talep_id"] for s in srv.satin_alma_talep_takibi(gorunum="tamamlanan")["satirlar"]}, set())
        self.assertIn(tid, {s["talep_id"] for s in srv.satin_alma_talep_takibi(gorunum="acik")["satirlar"]})

        self._kullanici(5, "SATIS", izinler=("satis_goruntuleme",))
        with self.assertRaises(Exception):
            srv.satin_alma_talep_takibi()
        self._kullanici(6, "SATINALMA", izinler=("alis_talep_goruntuleme",))
        self.assertTrue(srv.satin_alma_talep_takibi()["satirlar"])

    def test_ekran_acilir(self):
        import tkinter as tk

        import satin_alma_rapor_ui as ui

        self._onayli_talep()
        try:
            kok = _tk_kok()
        except tk.TclError:
            self.skipTest("Tk yok")
        try:
            ekran = ui.satin_alma_talep_takibi_goster(kok, otomatik=False)
            ekran.raporla(senkron=True)
            self.assertEqual(len(ekran.tablolar["satirlar"].get_children()), 1)
        finally:
            kok.destroy()


if __name__ == "__main__":
    unittest.main()
