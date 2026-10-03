"""Stok uyarıları ve sipariş ihtiyacı — talimat bölüm 14 senaryoları (izole veritabanı)."""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from database.database import get_session  # noqa: E402
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu  # noqa: E402
from database.models.stok_uyari import StokIhtiyac, StokIhtiyacGecmisi  # noqa: E402
from database.stok_uyari_service import (  # noqa: E402
    DURUM_KISMEN,
    DURUM_SIPARIS_VERILDI,
    DURUM_TASLAK_VAR,
    NEDEN_KRITIK,
    NEDEN_TUKENDI,
    StokUyariService,
)
from tests.stok_test_ortami import StokOrtami  # noqa: E402

D = date
BUGUN = date.today()
T1, T2, T3 = BUGUN - timedelta(days=5), BUGUN - timedelta(days=4), BUGUN - timedelta(days=3)


class _Taban(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:20])
        with get_session() as s:
            self.stok_id = s.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == "U001"))
            self.ana = s.scalar(select(Depo.id).where(Depo.ad == "ANA DEPO"))
            self.d2 = s.scalar(select(Depo.id).where(Depo.ad == "DEPO 2"))

    def tearDown(self):
        self.o.kapat()

    def aktifler(self, stok_id=None, depo_id=None):
        with get_session() as s:
            q = select(StokIhtiyac).where(StokIhtiyac.aktif.is_(True),
                                          StokIhtiyac.stok_id == (stok_id or self.stok_id))
            if depo_id:
                q = q.where(StokIhtiyac.depo_id == depo_id)
            return list(s.scalars(q).all())

    def tum(self):
        with get_session() as s:
            return list(s.scalars(select(StokIhtiyac).where(StokIhtiyac.stok_id == self.stok_id)
                                  .order_by(StokIhtiyac.id)).all())

    def satir(self, ihtiyac_id=None):
        sat = StokUyariService.listele({"ertelenenler": True})["satirlar"]
        return next(s for s in sat if ihtiyac_id is None or s["id"] == ihtiyac_id)


class TukenmeTest(_Taban):
    def test_1den_0a_kayit_olusur_0dan_eksiye_ayni_satir(self):
        self.o.alis(1, 100, T1, lot="L1")
        self.assertEqual(self.aktifler(), [])
        self.o.satis(1, 150, T2)
        aktif = self.aktifler(depo_id=self.ana)
        self.assertEqual(len(aktif), 1)
        ilk = aktif[0]
        self.assertIn(NEDEN_TUKENDI, ilk.nedenler)
        self.assertEqual(Decimal(str(ilk.fiziksel)), Decimal("0"))
        # 0 → −1 (negatif stok): aynı etkin satır güncellenir, çoğalmaz
        with get_session() as s:
            lot = s.scalar(select(StokLotu).where(StokLotu.stok_id == self.stok_id))
            lot.kalan_miktar = Decimal("-1")
            s.add(StokHareketi(tarih=T3, hareket_turu="ÇIKIŞ", belge_no="NEG-1", stok_id=self.stok_id,
                               depo_id=self.ana, lot_id=lot.id, miktar=Decimal("1"), birim_maliyet=Decimal("100")))
        aktif = self.aktifler(depo_id=self.ana)
        self.assertEqual([k.id for k in aktif], [ilk.id])
        self.assertEqual(Decimal(str(aktif[0].fiziksel)), Decimal("-1"))

    def test_negatif_stok_kirpilmaz_ham_ihtiyac(self):
        ham, alim, temel = StokUyariService.oneri_hesapla(Decimal("20"), Decimal("-5"), Decimal("0"),
                                                          Decimal("1"), None)
        self.assertEqual(ham, Decimal("25"))
        self.assertEqual(temel, Decimal("25"))

    def test_iade_ile_kapanir_ve_yeni_olay_ayri_kayit(self):
        from database.satis_faturasi_service import SatisFaturasiService
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        self.o.alis(2, 100, T1, lot="L1")
        f = self.o.satis(2, 150, T2)
        ilk = self.aktifler()[0]
        kaynak = SatisFaturasiService.getir(f.id).satirlar[0]
        SatisIadeFaturasiService.kaydet(
            {"iade_tarihi": T3, "cari_id": self.o.mus_id, "depo": "ANA DEPO", "kaynak_fatura_id": f.id,
             "iade_odeme_tutari": Decimal("0")},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("1"), "birim": "Adet",
              "birim_fiyat": Decimal("150"), "kdv_orani": Decimal("20"), "kaynak_fatura_satiri_id": kaynak.id}],
        )
        self.assertEqual(self.aktifler(), [])
        with get_session() as s:
            kapanan = s.get(StokIhtiyac, ilk.id)
            self.assertFalse(kapanan.aktif)
            self.assertEqual(kapanan.kapanma_nedeni, "Stok yeterli")
        onceki = self.tum()
        self.o.satis(1, 150, BUGUN)
        tum = self.tum()
        self.assertEqual(len(tum), len(onceki) + 1)
        self.assertIn(ilk.id, [k.id for k in tum[:-1]])
        self.assertEqual(tum[-1].olay_no, onceki[-1].olay_no + 1)
        self.assertTrue(tum[-1].aktif)
        self.assertEqual(sum(1 for k in tum if k.aktif), 1)

    def test_veritabani_tek_aktif_kaydi_garanti_eder(self):
        self.o.alis(1, 100, T1)
        self.o.satis(1, 150, T2)
        with self.assertRaises(IntegrityError):
            with get_session() as s:
                s.info["_stok_uyari_calisiyor"] = True
                s.add(StokIhtiyac(stok_id=self.stok_id, depo_id=self.ana, aktif=True, nedenler=NEDEN_TUKENDI))
                s.flush()

    def test_taslak_satis_uyari_uretmez(self):
        self.o.alis(1, 100, T1)
        self.o.satis(1, 150, T2, onayla=False)
        self.assertEqual(self.aktifler(), [])

    def test_satis_iptali_yeniden_degerlendirir(self):
        from database.satis_faturasi_service import SatisFaturasiService

        self.o.alis(1, 100, T1)
        f = self.o.satis(1, 150, T2)
        self.assertEqual(len(self.aktifler()), 1)
        SatisFaturasiService.iptal_et(f.id, "test")
        self.assertEqual(self.aktifler(), [])

    def test_transfer_kaynak_depoyu_tuketir_hedefi_kapatir(self):
        from database.stok_service import StokService

        self.o.alis(3, 100, T1)
        StokService.depo_transfer_kaydet(
            {"cikis_depo": "ANA DEPO", "giris_depo": "DEPO 2", "fis_tarihi": T2},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("3")}],
        )
        self.assertEqual(len(self.aktifler(depo_id=self.ana)), 1)
        self.assertEqual(self.aktifler(depo_id=self.d2), [])
        k = self.aktifler(depo_id=self.ana)[0]
        self.assertEqual(Decimal(str(k.diger_depo_stok)), Decimal("3"))


class EsikTest(_Taban):
    def test_minimum_20_stok_20_kritik_21_kapanir(self):
        StokUyariService.ayar_kaydet(self.stok_id, None, {"minimum": "20"})
        self.o.alis(20, 10, T1)
        aktif = self.aktifler()
        self.assertEqual(len(aktif), 1)
        self.assertIn(NEDEN_KRITIK, aktif[0].nedenler)
        self.o.alis(1, 10, T2)
        self.assertEqual(self.aktifler(), [])

    def test_hedefsiz_tukenmis_listede_miktar_kullanicida(self):
        self.o.alis(1, 100, T1)
        self.o.satis(1, 150, T2)
        s = self.satir()
        self.assertIsNone(s["oneri_alim"])
        self.assertEqual(s["oneri_metni"], "Kullanıcı belirleyecek")

    def test_ayar_dogrulama(self):
        with self.assertRaises(ValueError):
            StokUyariService.ayar_kaydet(self.stok_id, None, {"minimum": "-1"})
        with self.assertRaises(ValueError):
            StokUyariService.ayar_kaydet(self.stok_id, None, {"minimum": "10", "hedef": "5"})

    def test_depo_esigi_urun_varsayilanini_ezer(self):
        StokUyariService.ayar_kaydet(self.stok_id, None, {"minimum": "5"})
        StokUyariService.ayar_kaydet(self.stok_id, self.d2, {"minimum": "50"})
        self.o.alis(10, 10, T1)
        self.o.alis(10, 10, T1, depo="DEPO 2")
        self.assertEqual(self.aktifler(depo_id=self.ana), [])
        self.assertEqual(len(self.aktifler(depo_id=self.d2)), 1)
        etkin = StokUyariService.ayar_getir(self.stok_id, self.d2)["etkin"]
        self.assertEqual(etkin["kaynak"]["minimum"], "Depo")

    def test_takip_kapali_ve_pasif_urun_dislanir(self):
        self.o.alis(1, 100, T1)
        self.o.satis(1, 150, T2)
        StokUyariService.takibi_kapat(self.stok_id)
        self.assertEqual(self.aktifler(), [])
        stok2 = self.o.urun_ekle("P002", "Pasif Ürün")
        with get_session() as s:
            s.get(StokKarti, stok2).aktif = False
        StokUyariService.toplu_degerlendir()
        self.assertEqual(self.aktifler(stok_id=stok2), [])


class OneriVeSiparisTest(_Taban):
    def _hazirla(self, stok=5):
        StokUyariService.ayar_kaydet(self.stok_id, None,
                                     {"minimum": "10", "hedef": "50", "alim_birimi": "Koli"})
        self.o.alis(stok, 10, T1)
        return self.aktifler()[0]

    def test_formul_hedef50_satilabilir5_beklenen20_koli12(self):
        ham, alim, temel = StokUyariService.oneri_hesapla(Decimal("50"), Decimal("5"), Decimal("20"),
                                                          Decimal("12"), None)
        self.assertEqual((ham, alim, temel), (Decimal("25"), Decimal("3"), Decimal("36")))
        _, alim2, temel2 = StokUyariService.oneri_hesapla(Decimal("50"), Decimal("5"), Decimal("20"),
                                                          Decimal("12"), Decimal("2"))
        self.assertEqual((alim2, temel2), (Decimal("4"), Decimal("48")))

    def test_oneri_ve_tahmini_bedel_alim_birimine_gore(self):
        k = self._hazirla()
        self.assertEqual(Decimal(str(k.oneri_alim)), Decimal("4"))  # (50−5)/12 → 4 koli
        s = self.satir(k.id)
        self.assertEqual(s["tahmini_fiyat"]["fiyat"], Decimal("120.0000"))
        self.assertEqual(s["tahmini_bedel"], Decimal("480.00"))
        self.assertEqual(s["tedarikci_kaynak"], "Son alış")

    def test_taslak_beklenene_girmez_kesinlesen_girer_kismi_teslim_tek_sayilir(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.alis_siparisi_service import AlisSiparisiService

        k = self._hazirla()
        sip = StokUyariService.siparis_hazirla([{
            "ihtiyac_id": k.id, "row_version": k.row_version, "tedarikci_id": self.o.ted_id,
            "miktar": "3", "birim": "Koli", "fiyat": "120"}])
        self.assertEqual(len(sip), 1)
        self.assertEqual(self.o.lot_toplam(), Decimal("5"))
        k1 = self.aktifler()[0]
        self.assertEqual(Decimal(str(k1.beklenen)), Decimal("0"))
        self.assertEqual(self.satir(k.id)["durum"], DURUM_TASLAK_VAR)

        AlisSiparisiService.kesinlestir(sip[0]["siparis_id"])
        k2 = self.aktifler()[0]
        self.assertEqual(Decimal(str(k2.beklenen)), Decimal("36"))
        self.assertEqual(Decimal(str(k2.oneri_alim)), Decimal("1"))  # 50−5−36 = 9 → 1 koli
        self.assertEqual(self.satir(k.id)["durum"], DURUM_SIPARIS_VERILDI)

        siparis = AlisSiparisiService.getir(sip[0]["siparis_id"])
        ss = siparis.satirlar[0]
        fatura = AlisFaturasiService.kaydet(
            {"fatura_tarihi": BUGUN, "vade_tarihi": BUGUN, "cari_id": self.o.ted_id, "depo": "ANA DEPO",
             "odeme_tutari": Decimal("0"), "siparis_id": siparis.id},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("1"), "birim": "Koli",
              "birim_fiyat": Decimal("120"), "kdv_orani": Decimal("20"), "siparis_satiri_id": ss.id}],
        )
        self.assertEqual(self.o.lot_toplam(), Decimal("17"))
        k3 = self.aktifler()
        self.assertEqual(len(k3), 0, "17 > minimum 10: kritik uyarı kapanır")
        with get_session() as s:
            son = s.scalars(select(StokIhtiyac).where(StokIhtiyac.stok_id == self.stok_id)).all()[-1]
            self.assertEqual(Decimal(str(son.beklenen)), Decimal("24"))
        # Teslim (fatura) iptali → stok geri, beklenen yeniden 36
        AlisFaturasiService.iptal_et(fatura.id)
        k4 = self.aktifler()[0]
        self.assertEqual(Decimal(str(k4.fiziksel)), Decimal("5"))
        self.assertEqual(Decimal(str(k4.beklenen)), Decimal("36"))

    def test_kismi_teslim_durumu(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.alis_siparisi_service import AlisSiparisiService

        StokUyariService.ayar_kaydet(self.stok_id, None, {"minimum": "30", "hedef": "50", "alim_birimi": "Koli"})
        self.o.alis(5, 10, T1)
        k = self.aktifler()[0]
        sip = StokUyariService.siparis_hazirla([{
            "ihtiyac_id": k.id, "row_version": k.row_version, "tedarikci_id": self.o.ted_id,
            "miktar": "4", "birim": "Koli", "fiyat": "120"}])
        AlisSiparisiService.kesinlestir(sip[0]["siparis_id"])
        ss = AlisSiparisiService.getir(sip[0]["siparis_id"]).satirlar[0]
        AlisFaturasiService.kaydet(
            {"fatura_tarihi": BUGUN, "vade_tarihi": BUGUN, "cari_id": self.o.ted_id, "depo": "ANA DEPO",
             "odeme_tutari": Decimal("0"), "siparis_id": ss.siparis_id},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("1"), "birim": "Koli",
              "birim_fiyat": Decimal("120"), "kdv_orani": Decimal("20"), "siparis_satiri_id": ss.id}],
        )
        s = self.satir(k.id)
        self.assertEqual(s["durum"], DURUM_KISMEN)
        self.assertEqual(s["bag"]["teslim"], Decimal("12"))
        self.assertEqual(s["beklenen"], Decimal("36"))

    def test_irsaliye_fatura_donusumu_teslimi_iki_kez_saymaz(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.alis_irsaliyesi_service import AlisIrsaliyesiService
        from database.alis_siparisi_service import AlisSiparisiService

        k = self._hazirla()
        sip = StokUyariService.siparis_hazirla([{
            "ihtiyac_id": k.id, "row_version": k.row_version, "tedarikci_id": self.o.ted_id,
            "miktar": "3", "birim": "Koli", "fiyat": "120"}])
        AlisSiparisiService.kesinlestir(sip[0]["siparis_id"])
        ss = AlisSiparisiService.getir(sip[0]["siparis_id"]).satirlar[0]
        irs = AlisIrsaliyesiService.kaydet(
            {"irsaliye_tarihi": BUGUN, "cari_id": self.o.ted_id, "siparis_id": ss.siparis_id},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("1"), "birim": "Koli",
              "birim_fiyat": Decimal("120"), "siparis_satiri_id": ss.id}],
        )
        h = None
        with get_session() as s:
            kart = s.get(StokKarti, self.stok_id)
            depo = s.get(Depo, self.ana)
            h = StokUyariService.hesapla(s, kart, depo)
        self.assertEqual(h["beklenen"], Decimal("36"))
        self.assertEqual(h["irsaliyeli_faturasiz"], Decimal("12"))
        self.assertEqual(h["fiziksel"], Decimal("5"))
        irs_satir = irs.satirlar[0]
        AlisFaturasiService.kaydet(
            {"fatura_tarihi": BUGUN, "vade_tarihi": BUGUN, "cari_id": self.o.ted_id, "depo": "ANA DEPO",
             "odeme_tutari": Decimal("0"), "irsaliye_id": irs.id},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("1"), "birim": "Koli",
              "birim_fiyat": Decimal("120"), "kdv_orani": Decimal("20"), "irsaliye_satiri_id": irs_satir.id}],
        )
        with get_session() as s:
            h = StokUyariService.hesapla(s, s.get(StokKarti, self.stok_id), s.get(Depo, self.ana))
        self.assertEqual(h["fiziksel"], Decimal("17"))
        self.assertEqual(h["beklenen"], Decimal("24"))
        self.assertEqual(h["fiziksel"] + h["beklenen"], Decimal("41"))

    def test_taslak_siparis_faturaya_cevrilemez(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.alis_siparisi_service import AlisSiparisiService

        k = self._hazirla()
        sip = StokUyariService.siparis_hazirla([{
            "ihtiyac_id": k.id, "row_version": k.row_version, "tedarikci_id": self.o.ted_id,
            "miktar": "1", "birim": "Koli", "fiyat": "120"}])
        ss = AlisSiparisiService.getir(sip[0]["siparis_id"]).satirlar[0]
        with self.assertRaises(ValueError):
            AlisFaturasiService.kaydet(
                {"fatura_tarihi": BUGUN, "vade_tarihi": BUGUN, "cari_id": self.o.ted_id, "depo": "ANA DEPO",
                 "odeme_tutari": Decimal("0")},
                [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("1"), "birim": "Koli",
                  "birim_fiyat": Decimal("120"), "kdv_orani": Decimal("20"), "siparis_satiri_id": ss.id}],
            )
        self.assertEqual(self.o.lot_toplam(), Decimal("5"))

    def test_siparis_iptali_ve_miktar_degisimi(self):
        from database.alis_siparisi_service import AlisSiparisiService

        k = self._hazirla()
        sip = StokUyariService.siparis_hazirla([{
            "ihtiyac_id": k.id, "row_version": k.row_version, "tedarikci_id": self.o.ted_id,
            "miktar": "3", "birim": "Koli", "fiyat": "120"}])
        sid = sip[0]["siparis_id"]
        AlisSiparisiService.kesinlestir(sid)
        self.assertEqual(Decimal(str(self.aktifler()[0].beklenen)), Decimal("36"))
        siparis = AlisSiparisiService.getir(sid)
        satirlar = [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("2"), "birim": "Koli",
                     "birim_alis_fiyati": Decimal("120"), "kdv_orani": Decimal("20")}]
        AlisSiparisiService.kaydet(
            {"siparis_tarihi": siparis.siparis_tarihi, "termin_tarihi": siparis.termin_tarihi,
             "cari_id": self.o.ted_id, "row_version": siparis.row_version}, satirlar, [], sid)
        self.assertEqual(Decimal(str(self.aktifler()[0].beklenen)), Decimal("24"))
        AlisSiparisiService.iptal_et(sid)
        self.assertEqual(Decimal(str(self.aktifler()[0].beklenen)), Decimal("0"))

    def test_iki_kullanici_ayni_ihtiyactan_siparis_hazirlayamaz(self):
        from database.models.alis_siparisi import AlisSiparisi

        k = self._hazirla()
        secim = {"ihtiyac_id": k.id, "row_version": k.row_version, "tedarikci_id": self.o.ted_id,
                 "miktar": "1", "birim": "Koli", "fiyat": "120"}
        StokUyariService.siparis_hazirla([dict(secim)])
        with self.assertRaises(ValueError):
            StokUyariService.siparis_hazirla([dict(secim)])
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(AlisSiparisi.id))), 1)

    def test_tedarikci_secilmeden_siparis_olmaz(self):
        k = self._hazirla()
        with self.assertRaises(ValueError):
            StokUyariService.siparis_hazirla([{"ihtiyac_id": k.id, "row_version": k.row_version,
                                               "tedarikci_id": None, "miktar": "1"}])


class TaramaVeGecmisTest(_Taban):
    def test_ilk_tarama_mevcut_sifir_stoklari_bulur_ve_tekrar_mukerrer_olusturmaz(self):
        biten = self.o.urun_ekle("B001", "Biten Ürün")
        hareketsiz = self.o.urun_ekle("H001", "Hareketsiz Ürün")
        hareketsiz_min = self.o.urun_ekle("H002", "Hareketsiz Minimumlu", minimum_stok=Decimal("5"))
        self.o.alis(3, 10, T1)
        self.o.alis(2, 10, T1, kod="B001")
        self.o.satis(2, 15, T2, kod="B001")
        with get_session() as s:
            s.info["_stok_uyari_calisiyor"] = True
            s.execute(StokIhtiyacGecmisi.__table__.delete())
            s.execute(StokIhtiyac.__table__.delete())
        sonuc = StokUyariService.toplu_degerlendir(ilk_tarama=True)
        self.assertGreaterEqual(sonuc["cift"], 4)
        self.assertEqual(len(self.aktifler(stok_id=biten, depo_id=self.ana)), 1)
        # Hareketi olmayan aktif ürüne de kart takip ayarı uygulanır (talimat bölüm 3)
        # Hiç stok girişi olmayan kart "Tükendi" değil, ayrı "Stok girişi yok" (karar 4)
        self.assertEqual([k.nedenler for k in self.aktifler(stok_id=hareketsiz, depo_id=self.ana)], ["GIRIS_YOK"])
        self.assertEqual(len(self.aktifler(stok_id=hareketsiz_min, depo_id=self.ana)), 1)
        self.assertEqual(self.aktifler(), [])
        StokUyariService.toplu_degerlendir()
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(StokIhtiyac.id)).where(StokIhtiyac.stok_id == biten)), 1)
        self.assertFalse(StokUyariService.ilk_tarama_gerekli())

    def test_erteleme_gizler_suresi_bitince_gorunur(self):
        self.o.alis(1, 100, T1)
        self.o.satis(1, 150, T2)
        k = self.aktifler()[0]
        with self.assertRaises(ValueError):
            StokUyariService.ertele(k.id, BUGUN + timedelta(days=3), "")
        StokUyariService.ertele(k.id, BUGUN + timedelta(days=3), "Tedarikçi tatilde")
        self.assertEqual([s for s in StokUyariService.listele()["satirlar"] if s["id"] == k.id], [])
        self.assertEqual(self.satir(k.id)["durum"], "Ertelendi")
        self.assertEqual(self.o.lot_toplam(), Decimal("0"))
        with get_session() as s:
            s.get(StokIhtiyac, k.id).erteleme_bitis = BUGUN - timedelta(days=1)
        self.assertTrue(any(s["id"] == k.id for s in StokUyariService.listele()["satirlar"]))

    def test_son_alis_satis_iptal_ve_taslak_haric(self):
        from database.alis_faturasi_service import AlisFaturasiService

        self.o.alis(10, 100, T1)
        iptal = self.o.alis(5, 999, T2)
        AlisFaturasiService.iptal_et(iptal.id)
        self.o.satis(10, 150, T3)
        self.o.satis(1, 777, BUGUN, onayla=False)
        s = self.satir()
        self.assertEqual(s["son_alis"]["net_fiyat"], Decimal("100.0000"))
        self.assertEqual(s["son_satis"]["net_fiyat"], Decimal("150.0000"))
        self.assertEqual(s["donem_alis"], Decimal("10"))
        self.assertEqual(s["donem_satis"], Decimal("10"))

    def test_donem_iadeler_ayri_net_formul_ve_birim_cevirisi(self):
        from database.satis_faturasi_service import SatisFaturasiService
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        self.o.alis(2, 1200, T1, birim="Koli")
        f = self.o.satis(1, 2000, T2, birim="Koli")
        self.o.satis(12, 200, T3)
        kaynak = SatisFaturasiService.getir(f.id).satirlar[0]
        SatisIadeFaturasiService.kaydet(
            {"iade_tarihi": BUGUN, "cari_id": self.o.mus_id, "depo": "ANA DEPO", "kaynak_fatura_id": f.id,
             "iade_odeme_tutari": Decimal("0")},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("1"), "birim": "Koli",
              "birim_fiyat": Decimal("2000"), "kdv_orani": Decimal("20"), "kaynak_fatura_satiri_id": kaynak.id}],
        )
        self.o.satis(12, 200, BUGUN)
        s = self.satir()
        self.assertEqual(s["donem_alis"], Decimal("24"))
        self.assertEqual(s["donem_satis"], Decimal("36"))
        self.assertEqual(s["donem_satis_iade"], Decimal("12"))
        self.assertEqual(s["donem_net_satis"], Decimal("24"))

    def test_farkli_doviz_tutarlari_birlestirilmez(self):
        stok2 = self.o.urun_ekle("USD1", "Dövizli Ürün")
        from database.alis_faturasi_service import AlisFaturasiService

        AlisFaturasiService.kaydet(
            {"fatura_tarihi": T1, "vade_tarihi": T1, "cari_id": self.o.ted_id, "depo": "ANA DEPO",
             "odeme_tutari": Decimal("0"), "para_birimi": "USD", "kur": Decimal("40")},
            [{"urun_kodu": "USD1", "urun_adi": "Dövizli Ürün", "miktar": Decimal("1"), "birim": "Adet",
              "birim_fiyat": Decimal("0"), "birim_fiyat_doviz": Decimal("10"), "kdv_orani": Decimal("20")}],
        )
        self.o.alis(1, 100, T1)
        StokUyariService.ayar_kaydet(stok2, None, {"hedef": "5"})
        StokUyariService.ayar_kaydet(self.stok_id, None, {"hedef": "5"})
        self.o.satis(1, 150, T2)
        self.o.satis(1, 900, T2, kod="USD1")
        sonuc = StokUyariService.listele()
        usd = next(s for s in sonuc["satirlar"] if s["stok_kodu"] == "USD1")
        self.assertEqual(usd["tahmini_fiyat"]["para_birimi"], "USD")
        self.assertEqual(usd["tahmini_fiyat"]["fiyat"], Decimal("10.0000"))
        self.assertEqual(sonuc["toplam_bedel"]["USD"], Decimal("50.00"))
        self.assertEqual(sonuc["toplam_bedel"]["TRY"], Decimal("500.00"))

    def test_tercih_edilen_tedarikci_ve_filtre_sonrasi_kimlik(self):
        from database.models.cari import Cari

        with get_session() as s:
            c = Cari(cari_kodu="T002", unvan="İkinci Tedarikçi", cari_turu="Tedarikçi", aktif=True)
            s.add(c)
            s.flush()
            t2 = c.id
        StokUyariService.ayar_kaydet(self.stok_id, None, {"tercih_tedarikci_id": t2})
        self.o.alis(1, 100, T1)
        self.o.satis(1, 150, T2)
        stok2 = self.o.urun_ekle("Z001", "Zeta Ürün", minimum_stok=Decimal("3"))
        StokUyariService.toplu_degerlendir()
        sat = StokUyariService.listele({"tedarikci": "ikinci"})["satirlar"]
        self.assertEqual([s["stok_id"] for s in sat], [self.stok_id])
        self.assertEqual(sat[0]["tedarikci_id"], t2)
        self.assertEqual(sat[0]["tedarikci_kaynak"], "Tercih edilen")
        z = next(s for s in StokUyariService.listele({"arama": "zeta"})["satirlar"])
        self.assertEqual(z["stok_id"], stok2)
        self.assertEqual(z["tedarikci"], "Tedarikçi seçilecek")

    def test_gecmis_korunur(self):
        # Kurulumda stoksuz açılan kart da takipte: ilk olay kart oluşturulunca açılır, alışla kapanır.
        self.o.alis(1, 100, T1)
        self.o.satis(1, 150, T2)
        self.o.alis(1, 100, T3)
        with get_session() as s:
            gecmis = s.scalars(select(StokIhtiyacGecmisi).order_by(StokIhtiyacGecmisi.id)).all()
            islemler = [g.islem for g in gecmis]
            kayitlar = [g.ihtiyac_id for g in gecmis]
        self.assertEqual(islemler, ["OLUŞTU", "KAPANDI", "OLUŞTU", "KAPANDI"])
        self.assertEqual(len(set(kayitlar)), 2)
        self.assertEqual(len(self.tum()), 2)

    def test_rezervasyon_destegi_yok_satilabilir_fiziksele_esit(self):
        self.o.alis(1, 100, T1)
        self.o.satis(1, 150, T2)
        s = StokUyariService.listele()
        self.assertEqual(s["satirlar"][0]["rezerve"], Decimal("0"))
        self.assertIn("rezervasyon", s["not"].lower())

    def test_hook_hatasi_kuyruga_yazilir_ve_islem_kaybolmaz(self):
        from unittest.mock import patch

        self.o.alis(1, 100, T1)
        with patch.object(StokUyariService, "yeniden_degerlendir", side_effect=RuntimeError("deneme")):
            self.o.satis(1, 150, T2)
        self.assertEqual(self.o.lot_toplam(), Decimal("0"))
        self.assertEqual(self.aktifler(), [])
        self.assertEqual(StokUyariService.bekleyenleri_isle(), 1)
        self.assertEqual(len(self.aktifler()), 1)


if __name__ == "__main__":
    unittest.main()
