"""Otomatik fiyat önceliği ve geçmiş alış fiyatları (izole firma DB)."""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from tests.stok_test_ortami import StokOrtami

from database.database import get_session
from database.models.cari import Cari
from database.models.stok import StokFiyati, StokKarti
from sqlalchemy import select


class FiyatKaynagiTest(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami("fiyat")
        with get_session() as s:
            s.add(Cari(cari_kodu="T002", unvan="İkinci Tedarikçi", cari_turu="Tedarikçi", aktif=True))
            s.commit()
            self.ted2 = s.scalar(select(Cari.id).where(Cari.cari_kodu == "T002"))

    def tearDown(self):
        self.o.kapat()

    def _alis(self, cari_id, tarih, fiyat, *, birim="Adet", isk=(0, 0, 0), saat="10:00", pb="TRY", kur=1,
              doviz=None, kod="U001"):
        from database.alis_faturasi_service import AlisFaturasiService

        veriler = {"fatura_tarihi": tarih, "vade_tarihi": tarih, "cari_id": cari_id, "depo": "ANA DEPO",
                   "odeme_tutari": Decimal("0"), "islem_saati": saat, "para_birimi": pb, "kur": Decimal(str(kur))}
        satir = {"urun_kodu": kod, "urun_adi": "Test Ürün", "miktar": Decimal("1"), "birim": birim,
                 "birim_fiyat": Decimal(str(fiyat)), "iskonto_orani": Decimal(str(isk[0])),
                 "iskonto_orani_2": Decimal(str(isk[1])), "iskonto_orani_3": Decimal(str(isk[2])),
                 "kdv_orani": Decimal("20"), "lot_no": ""}
        if doviz is not None:
            satir["birim_fiyat_doviz"] = Decimal(str(doviz))
        return AlisFaturasiService.kaydet(veriler, [satir])

    def _kart_alis(self, tutar, pb="TL", kdv="HARIC", kod="U001"):
        with get_session() as s:
            stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod))
            for f in list(stok.fiyatlar):
                if f.fiyat_adi == "ALIŞ FİYATI":
                    s.delete(f)
            s.flush()
            s.add(StokFiyati(stok_id=stok.id, fiyat_adi="ALIŞ FİYATI", tutar=Decimal(str(tutar)),
                             para_birimi=pb, kdv_durumu=kdv))
            s.commit()

    def _getir(self, **k):
        from database.fiyat_kaynagi_service import son_alis_fiyati_getir

        k.setdefault("belge_tarihi", date(2026, 6, 30))
        return son_alis_fiyati_getir("U001", k.pop("birim", "Adet"), **k)

    # --- öncelik ---
    def test_ayni_tedarikci_daha_yeni_baska_tedarikciden_once_gelir(self):
        self._alis(self.o.ted_id, date(2026, 3, 1), 10)
        self._alis(self.ted2, date(2026, 5, 1), 15)
        r = self._getir(cari_id=self.o.ted_id)
        self.assertEqual(r.fiyat, Decimal("10.0000"))
        self.assertFalse(r.baska_tedarikci)
        self.assertIn("01.03.2026", r.aciklama)

    def test_tedarikciden_alis_yoksa_baska_tedarikci_isaretli(self):
        self._alis(self.ted2, date(2026, 5, 1), 15)
        r = self._getir(cari_id=self.o.ted_id)
        self.assertEqual(r.fiyat, Decimal("15.0000"))
        self.assertTrue(r.baska_tedarikci)
        self.assertIn("başka tedarikçi", r.aciklama)

    def test_belge_tarihinden_sonraki_alis_kullanilmaz(self):
        self._alis(self.o.ted_id, date(2026, 3, 1), 10)
        self._alis(self.o.ted_id, date(2026, 7, 10), 99)
        self.assertEqual(self._getir(cari_id=self.o.ted_id).fiyat, Decimal("10.0000"))

    def test_ayni_gun_saat_sonra_kayit_sirasi(self):
        self._alis(self.o.ted_id, date(2026, 3, 1), 10, saat="15:00")
        self._alis(self.o.ted_id, date(2026, 3, 1), 11, saat="09:00")
        self.assertEqual(self._getir(cari_id=self.o.ted_id).fiyat, Decimal("10.0000"))
        self._alis(self.o.ted_id, date(2026, 3, 1), 12, saat="15:00")
        self.assertEqual(self._getir(cari_id=self.o.ted_id).fiyat, Decimal("12.0000"))

    def test_iptal_fatura_haric(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.models.alis_faturasi import AlisFaturasi

        self._alis(self.o.ted_id, date(2026, 3, 1), 10)
        f = self._alis(self.o.ted_id, date(2026, 4, 1), 20)
        with get_session() as s:
            s.get(AlisFaturasi, f.id).durum = "İPTAL"
            s.commit()
        self.assertEqual(self._getir(cari_id=self.o.ted_id).fiyat, Decimal("10.0000"))
        self.assertTrue(AlisFaturasiService)

    def test_uc_iskonto_bir_kez_uygulanir(self):
        self._alis(self.o.ted_id, date(2026, 3, 1), 100, isk=(10, 5, 0))
        self.assertEqual(self._getir(cari_id=self.o.ted_id).fiyat, Decimal("85.5000"))

    def test_koli_alisi_adet_fiyatina_cevrilir(self):
        self._alis(self.o.ted_id, date(2026, 3, 1), 120, birim="Koli")
        self.assertEqual(self._getir(cari_id=self.o.ted_id, birim="Adet").fiyat, Decimal("10.0000"))
        self.assertEqual(self._getir(cari_id=self.o.ted_id, birim="Koli").fiyat, Decimal("120.0000"))

    def test_tanimsiz_birimde_tahmin_yok(self):
        self._alis(self.o.ted_id, date(2026, 3, 1), 10)
        r = self._getir(cari_id=self.o.ted_id, birim="Paket")
        self.assertIsNone(r.fiyat)
        self.assertIn("Paket", r.uyari or "")

    def test_dovizli_alis_tl_ve_usd_belgede(self):
        self._alis(self.o.ted_id, date(2026, 3, 1), 0, pb="USD", kur=40, doviz=2)
        self.assertEqual(self._getir(cari_id=self.o.ted_id).fiyat, Decimal("80.0000"))
        self.assertEqual(self._getir(cari_id=self.o.ted_id, belge_pb="USD", belge_kur=Decimal("40")).fiyat,
                         Decimal("2.0000"))
        r = self._getir(cari_id=self.o.ted_id, belge_pb="EUR", belge_kur=Decimal("50"))
        self.assertEqual(r.fiyat, Decimal("1.6000"))

    def test_kur_yoksa_fiyat_bos_ve_uyari(self):
        self._alis(self.o.ted_id, date(2026, 3, 1), 80)
        r = self._getir(cari_id=self.o.ted_id, belge_pb="USD", belge_kur=None)
        self.assertIsNone(r.fiyat)
        self.assertIn("kur", (r.uyari or "").lower())

    def test_kart_alis_fiyati_yedek_ve_kdv_dahil(self):
        self._kart_alis(120, kdv="DAHIL")
        r = self._getir(cari_id=self.o.ted_id, kdv_orani=Decimal("20"))
        self.assertEqual(r.kaynak, "KART_ALIS")
        self.assertEqual(r.fiyat, Decimal("100.0000"))
        r = self._getir(cari_id=self.o.ted_id, birim="Koli", kdv_orani=Decimal("20"))
        self.assertEqual(r.fiyat, Decimal("1200.0000"))

    def test_hic_fiyat_yoksa_bos(self):
        r = self._getir(cari_id=self.o.ted_id)
        self.assertIsNone(r.fiyat)
        self.assertEqual(r.kaynak, "YOK")

    def test_duzenlenen_faturanin_kendisi_kaynak_olmaz(self):
        self._alis(self.o.ted_id, date(2026, 3, 1), 10)
        f = self._alis(self.o.ted_id, date(2026, 4, 1), 20)
        self.assertEqual(self._getir(cari_id=self.o.ted_id, haric_fatura_id=f.id).fiyat, Decimal("10.0000"))

    # --- geçmiş penceresi verisi ---
    def test_gecmis_tedarikci_filtre_sayfalama(self):
        from database.fiyat_kaynagi_service import alis_fiyat_gecmisi

        for gun in range(1, 6):
            self._alis(self.o.ted_id, date(2026, 3, gun), 10 + gun)
        self._alis(self.ted2, date(2026, 3, 10), 50)
        sadece = alis_fiyat_gecmisi("U001", cari_id=self.o.ted_id, limit=3)
        self.assertEqual(sadece["toplam"], 5)
        self.assertTrue(sadece["daha_var"])
        self.assertEqual([k["brut_fiyat"] for k in sadece["kayitlar"]],
                         [Decimal("15"), Decimal("14"), Decimal("13")])
        sonraki = alis_fiyat_gecmisi("U001", cari_id=self.o.ted_id, limit=3, offset=3)
        self.assertEqual(len(sonraki["kayitlar"]), 2)
        self.assertFalse(sonraki["daha_var"])
        tumu = alis_fiyat_gecmisi("U001", limit=50)
        self.assertEqual(tumu["toplam"], 6)
        self.assertEqual(tumu["kayitlar"][0]["tedarikci"], "İkinci Tedarikçi")
        aralik = alis_fiyat_gecmisi("U001", tarih_bas=date(2026, 3, 2), tarih_bit=date(2026, 3, 3))
        self.assertEqual(aralik["toplam"], 2)

    def test_gecmis_birim_ve_doviz_kaydedildigi_gibi(self):
        from database.fiyat_kaynagi_service import alis_fiyat_gecmisi

        self._alis(self.o.ted_id, date(2026, 3, 1), 120, birim="Koli", isk=(10, 0, 0))
        self._alis(self.o.ted_id, date(2026, 3, 2), 0, pb="USD", kur=40, doviz=3)
        k = alis_fiyat_gecmisi("U001")["kayitlar"]
        self.assertEqual((k[0]["para_birimi"], k[0]["brut_fiyat"], k[0]["birim"]), ("USD", Decimal("3"), "Adet"))
        self.assertEqual((k[1]["para_birimi"], k[1]["birim"], k[1]["net_fiyat"]),
                         ("TRY", "Koli", Decimal("108.0000")))

    def test_gecmis_okuma_veri_yazmaz(self):
        from database.fiyat_kaynagi_service import alis_fiyat_gecmisi
        from database.models.alis_faturasi import AlisFaturasi

        self._alis(self.o.ted_id, date(2026, 3, 1), 10)
        with get_session() as s:
            once = s.query(AlisFaturasi).count()
        alis_fiyat_gecmisi("U001", iade_dahil=True)
        self._getir(cari_id=self.o.ted_id)
        with get_session() as s:
            self.assertEqual(s.query(AlisFaturasi).count(), once)

    # --- satış ---
    def test_satis_kdv_dahil_liste_fiyati_hariçe(self):
        from database.fiyat_kaynagi_service import satis_kdv_haric

        with get_session() as s:
            stok = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "U001"))
            s.add(StokFiyati(stok_id=stok.id, fiyat_adi="SATIŞ FİYATI 1", tutar=Decimal("120"),
                             para_birimi="TL", kdv_durumu="DAHIL"))
            s.commit()
        fiyat, notu = satis_kdv_haric("U001", Decimal("120"), Decimal("20"))
        self.assertEqual(fiyat, Decimal("100.00") if fiyat.as_tuple().exponent == -2 else Decimal("100.0000"))
        self.assertTrue(notu)
        with get_session() as s:
            f = s.scalar(select(StokFiyati).where(StokFiyati.fiyat_adi == "SATIŞ FİYATI 1"))
            f.kdv_durumu = "HARIC"
            s.commit()
        self.assertEqual(satis_kdv_haric("U001", Decimal("120"), Decimal("20"))[0], Decimal("120"))


if __name__ == "__main__":
    unittest.main()
