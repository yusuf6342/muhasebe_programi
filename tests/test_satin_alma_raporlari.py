"""Satın Alma → Raporlar hesapları (izole test firması)."""
from __future__ import annotations

import unittest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import func, select

from database import satin_alma_rapor_service as srv
from database.database import get_session
from database.models.cari import Cari, CariIslem, SatisHareketi
from tests.stok_test_ortami import StokOrtami

D = Decimal
BUGUN = date(2026, 6, 15)


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

    def alis_kaydet(self, cari_id, tarih, satirlar, durum=None, **baslik):
        from database.alis_faturasi_service import AlisFaturasiService

        veriler = {"fatura_tarihi": tarih, "vade_tarihi": baslik.pop("vade", tarih), "cari_id": cari_id,
                   "depo": "ANA DEPO", "odeme_tutari": D("0"), **baslik}
        f = AlisFaturasiService.kaydet(veriler, [
            {"urun_kodu": s.get("kod", "U001"), "urun_adi": "Test Ürün", "miktar": D(str(s["miktar"])),
             "birim": s.get("birim", "Adet"), "birim_fiyat": D(str(s["fiyat"])),
             "iskonto_orani": D(str(s.get("isk", 0))), "kdv_orani": D("20"), "lot_no": ""}
            for s in satirlar])
        if durum:
            from database.models.alis_faturasi import AlisFaturasi

            with get_session() as s:
                s.get(AlisFaturasi, f.id).durum = durum
        return f


class FiyatDegisimTest(_Taban):
    def test_ayni_tedarikci_ve_tum_tedarikciler(self):
        t2 = self.tedarikci_ekle()
        self.alis_kaydet(self.o.ted_id, date(2026, 1, 10), [{"miktar": 10, "fiyat": 100}])
        self.alis_kaydet(self.o.ted_id, date(2026, 2, 10), [{"miktar": 10, "fiyat": 110}])
        self.alis_kaydet(t2, date(2026, 3, 1), [{"miktar": 5, "fiyat": 99}])

        ayni = srv.fiyat_degisim(kapsam="tedarikci")["satirlar"]
        t1 = next(r for r in ayni if r["tedarikci"] == "Test Tedarikçi")
        self.assertEqual(t1["onceki_fiyat"], D("100.0000"))
        self.assertEqual(t1["son_fiyat"], D("110.0000"))
        self.assertEqual(t1["fark"], D("10.0000"))
        self.assertEqual(t1["yuzde"], D("10.00"))
        t2r = next(r for r in ayni if r["tedarikci"] == "İkinci Tedarikçi")
        self.assertIsNone(t2r["yuzde"])
        self.assertIn("Önceki alış yok", t2r["aciklama"])

        tumu = srv.fiyat_degisim(kapsam="tumu")["satirlar"]
        self.assertEqual(len(tumu), 1)
        self.assertEqual(tumu[0]["onceki_tedarikci"], "Test Tedarikçi")
        self.assertEqual(tumu[0]["yuzde"], D("-10.00"))

    def test_iptal_ve_iskonto_ve_birim_cevrimi(self):
        self.alis_kaydet(self.o.ted_id, date(2026, 1, 10), [{"miktar": 10, "fiyat": 100, "isk": 10}])
        self.alis_kaydet(self.o.ted_id, date(2026, 1, 20), [{"miktar": 10, "fiyat": 500}], durum="İPTAL")
        self.alis_kaydet(self.o.ted_id, date(2026, 2, 10), [{"miktar": 1, "fiyat": 1080, "birim": "Koli"}])
        r = srv.fiyat_degisim()["satirlar"][0]
        self.assertEqual(r["birim"], "Koli")
        self.assertEqual(r["onceki_fiyat"], D("1080.0000"))
        self.assertEqual(r["fark"], D("0.0000"))
        self.assertIn("çevrildi", r["aciklama"])

    def test_onceki_sifir_yuzde_yok(self):
        self.assertIsNone(srv._yuzde(D("0"), D("10")))
        self.assertIsNone(srv._yuzde(None, D("10")))
        self.assertEqual(srv._yuzde(D("8"), D("10")), D("25.00"))


class TedarikciKarsilastirmaTest(_Taban):
    def test_ayni_birim_siralanir_farkli_birim_cevrimle(self):
        t2 = self.tedarikci_ekle()
        self.alis_kaydet(self.o.ted_id, date(2026, 1, 10), [{"miktar": 10, "fiyat": 100}])
        self.alis_kaydet(t2, date(2026, 2, 10), [{"miktar": 10, "fiyat": 90}])
        r = srv.tedarikci_karsilastirma("U001", bugun=BUGUN)
        self.assertTrue(r["siralanabilir"])
        self.assertEqual([x["tedarikci"] for x in r["ozet"]], ["İkinci Tedarikçi", "Test Tedarikçi"])
        self.assertEqual(r["ozet"][0]["gun"], (BUGUN - date(2026, 2, 10)).days)

        self.alis_kaydet(t2, date(2026, 3, 1), [{"miktar": 1, "fiyat": 1200, "birim": "Koli"}])
        r = srv.tedarikci_karsilastirma("U001", bugun=BUGUN)
        self.assertFalse(r["siralanabilir"])
        self.assertTrue(all("sira" not in x for x in r["ozet"]))
        r = srv.tedarikci_karsilastirma("U001", cevir=True, bugun=BUGUN)
        self.assertTrue(r["siralanabilir"])
        koli = next(x for x in r["ozet"] if x["birim"] == "Koli")
        self.assertEqual(koli["cevrilmis_fiyat"], D("100.0000"))
        self.assertIn("Adet", koli["cevrim_notu"])
        self.assertEqual(len(r["gecmis"]), 3)

    def test_teklifler_ayri(self):
        from database.models.tedarikci_teklif import TedarikciTeklif, TedarikciTeklifSatiri
        from database.tedarikci_teklif_service import TedarikciTeklifService

        TedarikciTeklifService.schema_hazirla()
        self.alis_kaydet(self.o.ted_id, date(2026, 1, 10), [{"miktar": 10, "fiyat": 100}])
        with get_session() as s:
            t = TedarikciTeklif(teklif_no="TKL-1", teklif_tarihi=date(2026, 6, 1), durum="TASLAK")
            s.add(t)
            s.flush()
            s.add(TedarikciTeklifSatiri(teklif_id=t.id, cari_id=self.o.ted_id, urun_kodu="U001",
                                        urun_adi="Test Ürün", miktar=D("5"), birim_fiyat=D("80")))
        r = srv.tedarikci_karsilastirma("U001", bugun=BUGUN)
        self.assertEqual(r["teklifler"], [])
        r = srv.tedarikci_karsilastirma("U001", teklif_dahil=True, bugun=BUGUN)
        self.assertEqual(len(r["teklifler"]), 1)
        self.assertEqual(r["teklifler"][0]["kaynak"], "TEKLİF")
        self.assertEqual(r["ozet"][0]["net_fiyat"], D("100.0000"))


class SiparisIrsaliyeTest(_Taban):
    def _siparis(self, durum="AÇIK", termin=date(2026, 6, 1), miktar=10):
        from database.models.alis_siparisi import AlisSiparisi, AlisSiparisiSatiri

        with get_session() as s:
            sp = AlisSiparisi(siparis_no=f"SP-{durum}-{miktar}", siparis_tarihi=date(2026, 5, 1),
                              termin_tarihi=termin, cari_id=self.o.ted_id, durum=durum)
            s.add(sp)
            s.flush()
            st = AlisSiparisiSatiri(siparis_id=sp.id, urun_kodu="U001", urun_adi="Test Ürün", miktar=D(miktar),
                                    birim="Adet", birim_alis_fiyati=D("50"), iskonto_orani=D("10"))
            s.add(st)
            s.flush()
            return int(sp.id), int(st.id)

    def _irsaliye(self, no, satirlar, durum="AÇIK", tarih=date(2026, 5, 10)):
        from database.models.alis_irsaliyesi import AlisIrsaliyesi, AlisIrsaliyesiSatiri

        with get_session() as s:
            irs = AlisIrsaliyesi(irsaliye_no=no, irsaliye_tarihi=tarih, cari_id=self.o.ted_id, durum=durum)
            s.add(irs)
            s.flush()
            idler = []
            for x in satirlar:
                st = AlisIrsaliyesiSatiri(irsaliye_id=irs.id, urun_kodu="U001", urun_adi="Test Ürün",
                                          miktar=D(x["miktar"]), birim="Adet", birim_fiyat=D(x.get("fiyat", 0)),
                                          siparis_satiri_id=x.get("siparis_satiri_id"))
                s.add(st)
                s.flush()
                idler.append(int(st.id))
            return int(irs.id), idler

    def _fatura(self, no, satirlar, durum="AÇIK"):
        from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri

        with get_session() as s:
            f = AlisFaturasi(fatura_no=no, fatura_tarihi=date(2026, 5, 20), vade_tarihi=date(2026, 5, 20),
                             cari_id=self.o.ted_id, durum=durum)
            s.add(f)
            s.flush()
            for x in satirlar:
                s.add(AlisFaturasiSatiri(fatura_id=f.id, urun_kodu="U001", urun_adi="Test Ürün",
                                         miktar=D(x["miktar"]), birim="Adet", birim_fiyat=D("50"),
                                         siparis_satiri_id=x.get("siparis_satiri_id"),
                                         irsaliye_satiri_id=x.get("irsaliye_satiri_id")))

    def test_bekleyen_siparis_mukerrersiz_teslim(self):
        _sp, st = self._siparis()
        self._siparis(durum="TASLAK", miktar=7)
        self._siparis(durum="İPTAL", miktar=8)
        _i, (irs_st,) = self._irsaliye("IRS-1", [{"miktar": 4, "siparis_satiri_id": st}])
        self._irsaliye("IRS-IPT", [{"miktar": 5, "siparis_satiri_id": st}], durum="İPTAL")
        self._fatura("AF-1", [{"miktar": 3, "siparis_satiri_id": st, "irsaliye_satiri_id": irs_st},
                              {"miktar": 2, "siparis_satiri_id": st}])
        self._fatura("AF-IPT", [{"miktar": 9, "siparis_satiri_id": st}], durum="İPTAL")
        r = srv.bekleyen_siparisler(bugun=BUGUN)
        self.assertEqual(len(r["satirlar"]), 1)
        x = r["satirlar"][0]
        self.assertEqual(x["gelen"], D("6"))
        self.assertEqual(x["kalan"], D("4"))
        self.assertEqual(x["gecikme"], 14)
        self.assertEqual(x["kalan_tutar"], D("180.00"))
        self.assertEqual(srv.bekleyen_siparisler(bugun=date(2026, 5, 15))["satirlar"][0]["gecikme"], 0)
        self.assertEqual(srv.bekleyen_siparisler(bugun=date(2026, 5, 15), sadece_geciken=True)["satirlar"], [])

    def test_faturasi_gelmeyen_irsaliye(self):
        with get_session() as s:
            once = (s.scalar(select(func.count(SatisHareketi.id))), s.scalar(select(func.count(CariIslem.id))))
        _i, (fiyatli, fiyatsiz) = self._irsaliye("IRS-2", [{"miktar": 10, "fiyat": 50}, {"miktar": 3}])
        self._irsaliye("IRS-IPT2", [{"miktar": 99, "fiyat": 1}], durum="İPTAL")
        self._fatura("AF-2", [{"miktar": 4, "irsaliye_satiri_id": fiyatli}])
        self._fatura("AF-2I", [{"miktar": 6, "irsaliye_satiri_id": fiyatli}], durum="İPTAL")
        r = srv.faturasi_gelmeyen_irsaliyeler(bugun=BUGUN)
        self.assertEqual(len(r["satirlar"]), 2)
        a = next(x for x in r["satirlar"] if x["teslim"] == D("10"))
        self.assertEqual(a["faturalanan"], D("4"))
        self.assertEqual(a["faturalanmamis"], D("6"))
        self.assertEqual(a["tahmini_tutar"], D("300.00"))
        self.assertEqual(a["bekleme_gun"], (BUGUN - date(2026, 5, 10)).days)
        b = next(x for x in r["satirlar"] if x["teslim"] == D("3"))
        self.assertIsNone(b["tahmini_tutar"])
        self.assertIn("Fiyat yok", b["aciklama"])
        self.assertEqual(r["toplam_tahmini"], D("300.00"))
        self.assertEqual(r["fiyatsiz_satir"], 1)
        with get_session() as s:
            sonra = (s.scalar(select(func.count(SatisHareketi.id))), s.scalar(select(func.count(CariIslem.id))))
        self.assertEqual(once, sonra)


class YenidenSiparisTest(_Taban):
    def test_oneri_ve_taslak_mukerrer_onleme(self):
        from database.models.stok import StokKarti

        with get_session() as s:
            s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "U001")).minimum_stok = D("10")
        yakin = date.today() - timedelta(days=5)
        self.o.alis(5, 100, yakin - timedelta(days=1))
        self.o.satis(5, 150, yakin)
        r = srv.yeniden_siparis_onerisi(donem_gun=90, hedef_gun=30)
        x = next(s for s in r["satirlar"] if s["stok_kodu"] == "U001")
        self.assertEqual(x["kullanilabilir"], D("0"))
        self.assertEqual(x["hedef"], D("10.0000"))
        self.assertEqual(x["oneri"], D("10"))
        self.assertEqual(x["son_tedarikci"], "Test Tedarikçi")

        kisa = srv.yeniden_siparis_onerisi(donem_gun=10, hedef_gun=30)
        y = next(s for s in kisa["satirlar"] if s["stok_kodu"] == "U001")
        self.assertEqual(y["hedef"], D("15.0000"))
        self.assertEqual(y["oneri"], D("15"))

        srv.taslak_siparis_olustur([x])
        r2 = srv.yeniden_siparis_onerisi(donem_gun=90, hedef_gun=30)
        x2 = next(s for s in r2["satirlar"] if s["stok_kodu"] == "U001")
        self.assertEqual(x2["taslak_siparis"], D("10"))
        self.assertEqual(x2["oneri"], D("0"))
        with self.assertRaises(ValueError):
            srv.taslak_siparis_olustur([x2])


class BorcVadeTest(_Taban):
    def test_vade_dagilimi_ve_soz_borcu_azaltmaz(self):
        self.alis_kaydet(self.o.ted_id, date(2026, 5, 1), [{"miktar": 1, "fiyat": 100}], vade=date(2026, 5, 31))
        self.alis_kaydet(self.o.ted_id, date(2026, 6, 1), [{"miktar": 1, "fiyat": 100}], vade=BUGUN)
        self.alis_kaydet(self.o.ted_id, date(2026, 6, 10), [{"miktar": 1, "fiyat": 100}], vade=date(2026, 7, 10))
        with get_session() as s:
            s.add(CariIslem(cari_id=self.o.ted_id, tarih=date(2026, 6, 5), islem_turu="Ödeme",
                            belge_no="OD-1", borc=D("0"), alacak=D("50"), aciklama="test"))
        soz = [{"cari_id": self.o.ted_id, "kalan": D("70"), "tutar": D("70"), "vade_tarihi": date(2026, 6, 20)}]
        with patch("database.odeme_sozu_service.OdemeSozuService.liste", return_value=soz):
            r = srv.tedarikci_borc_vade(bugun=BUGUN)
        x = r["satirlar"][0]
        self.assertEqual(x["toplam_borc"], D("360.00"))
        self.assertEqual(x["kapanan"], D("50.00"))
        self.assertEqual(x["acik"], D("310.00"))
        self.assertEqual(x["vadesi_gecmis"], D("70.00"))
        self.assertEqual(x["bugun"], D("120.00"))
        self.assertEqual(x["ileri_vade"], D("120.00"))
        self.assertEqual(x["soz_tutari"], D("70.00"))
        self.assertEqual(x["bakiye"], D("310.00"))
        self.assertEqual(x["fark"], D("0.00"))

        d = srv.tedarikci_borc_detay(self.o.ted_id, bugun=BUGUN)
        self.assertEqual(len(d["kalemler"]), 3)
        self.assertEqual(d["kalemler"][0]["durum"], "Vadesi geçmiş")


class MaliyetVeOzetTest(_Taban):
    def test_gercek_maliyet_masraf_ve_gecici(self):
        from database.masraf_dagitim_service import MasrafDagitimService
        from database.models.alis_faturasi import AlisFaturasiSatiri
        from database.models.alis_masraf import AlisMasraf, AlisMasrafDagitim
        from database.models.masraf_dagitim import MasrafDagitim, MasrafDagitimSatiri

        MasrafDagitimService.schema_hazirla()
        f = self.alis_kaydet(self.o.ted_id, date(2026, 3, 1), [{"miktar": 10, "fiyat": 100, "isk": 10}])
        with get_session() as s:
            satir_id = s.scalar(select(AlisFaturasiSatiri.id).where(AlisFaturasiSatiri.fatura_id == f.id))
            m = AlisMasraf(fatura_id=f.id, masraf_turu="Nakliye", tutar=D("50"), maliyete_dahil=True)
            s.add(m)
            s.flush()
            s.add(AlisMasrafDagitim(masraf_id=m.id, fatura_satiri_id=satir_id, tutar=D("50"), oran=D("1")))
        r = srv.gercek_alis_maliyeti()["satirlar"][0]
        self.assertEqual(r["net_alis"], D("900.00"))
        self.assertEqual(r["nakliye"], D("50.00"))
        self.assertEqual(r["toplam_maliyet"], D("950.00"))
        self.assertEqual(r["birim_maliyet"], D("95.0000"))
        self.assertFalse(r["eksik"])

        with get_session() as s:
            md = MasrafDagitim(dagitim_no="MD-1", dagitim_tarihi=date(2026, 3, 2), kaynak_turu="HIZMET_FATURASI",
                               kaynak_id=1, kaynak_no="HF-1", durum="TASLAK", tutar=D("30"))
            s.add(md)
            s.flush()
            s.add(MasrafDagitimSatiri(dagitim_id=md.id, alis_fatura_id=f.id, alis_fatura_satiri_id=satir_id,
                                      alis_fatura_no=f.fatura_no, urun_kodu="U001", urun_adi="Test Ürün", pay=D("30")))
        r = srv.gercek_alis_maliyeti()["satirlar"][0]
        self.assertEqual(r["toplam_maliyet"], D("950.00"))
        self.assertTrue(r["eksik"])
        self.assertIn("Geçici", r["durum"])

    def test_alis_iade_ozeti(self):
        from database.models.alis_iade_faturasi import AlisIadeFaturasi, AlisIadeFaturasiSatiri

        self.alis_kaydet(self.o.ted_id, date(2026, 3, 1), [{"miktar": 10, "fiyat": 100}])
        self.alis_kaydet(self.o.ted_id, date(2026, 3, 2), [{"miktar": 1, "fiyat": 1200, "birim": "Koli"}])
        with get_session() as s:
            for no, durum, miktar in (("AI-1", "AÇIK", 2), ("AI-T", "TASLAK", 5), ("AI-X", "İPTAL", 5)):
                i = AlisIadeFaturasi(iade_no=no, iade_tarihi=date(2026, 3, 5), cari_id=self.o.ted_id, durum=durum)
                s.add(i)
                s.flush()
                s.add(AlisIadeFaturasiSatiri(iade_id=i.id, urun_kodu="U001", urun_adi="Test Ürün",
                                             miktar=D(miktar), birim="Adet", birim_fiyat=D("100"), kdv_orani=D("20")))
        r = srv.alis_iade_ozeti()
        x = r["satirlar"][0]
        self.assertEqual(x["alis_miktar"], D("22"))
        self.assertEqual(x["alis_haric"], D("2200.00"))
        self.assertEqual(x["alis_kdv"], D("440.00"))
        self.assertEqual(x["iade_miktar"], D("2"))
        self.assertEqual(x["iade_haric"], D("200.00"))
        self.assertEqual(x["net_haric"], D("2000.00"))
        self.assertEqual(x["net_kdv"], D("400.00"))
        self.assertEqual(x["net_dahil"], D("2400.00"))
        g = srv.alis_iade_ozeti(gruplama="tedarikci")["satirlar"][0]
        self.assertEqual(g["anahtar"], "Test Tedarikçi")
        self.assertIsNone(g["alis_miktar"])


class RaporEkranlariTest(_Taban):
    def test_ekranlar_acilir_ve_hub_kartlari(self):
        import tkinter as tk

        import satin_alma_rapor_ui as ui
        from satin_alma_ui import RAPOR_KARTLARI, _rapor_komutlar

        self.alis_kaydet(self.o.ted_id, date(2026, 1, 10), [{"miktar": 10, "fiyat": 100}])
        try:
            kok = tk.Tk()
        except tk.TclError:
            self.skipTest("Tk yok")
        kok.withdraw()
        kok.icerik = tk.Frame(kok)
        kok.icerik.pack()
        kok._icerigi_temizle = lambda: [w.destroy() for w in kok.icerik.winfo_children()]
        kok.rapor_tedarikci_bakiye_durum = kok.rapor_tedarikci_ekstresi = lambda: None
        kok.rapor_stok_detayli_tedarikci_ekstre = kok.rapor_tahsilat_odeme = lambda: None
        try:
            komutlar = _rapor_komutlar(kok)
            basliklar = [k[0] for k in RAPOR_KARTLARI]
            self.assertNotIn("SATIN ALMA ÖZETİ", basliklar)
            self.assertNotIn("STOK YENİLEME ÖNERİSİ", basliklar)
            for _b, _a, anahtar in RAPOR_KARTLARI:
                if anahtar != "aylik":
                    self.assertIn(anahtar, komutlar)
            for fn in (ui.fiyat_degisim_raporu_goster, ui.bekleyen_alis_siparisleri_goster,
                       ui.faturasi_gelmeyen_irsaliyeler_goster, ui.tedarikci_borc_vade_goster,
                       ui.gercek_alis_maliyeti_goster, ui.alis_iade_ozeti_goster):
                ekran = fn(kok, otomatik=False)
                ekran.raporla(senkron=True)
                self.assertIn("notlar", ekran.sonuc)
            ekran = ui.tedarikci_fiyat_karsilastirma_goster(kok, urun_kodu="U001", otomatik=False)
            ekran.raporla(senkron=True)
            self.assertEqual(len(ekran.tablolar["ozet"].get_children()), 1)
            self.assertIn("Test Tedarikçi", ekran.html_metni())
            import tempfile, os
            yol = os.path.join(tempfile.mkdtemp(), "r.xlsx")
            ekran.excel_yaz(yol)
            self.assertTrue(os.path.getsize(yol) > 0)
        finally:
            kok.destroy()


if __name__ == "__main__":
    unittest.main()
