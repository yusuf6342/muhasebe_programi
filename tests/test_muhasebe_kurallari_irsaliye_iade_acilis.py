"""Muhasebe kuralları (05.10.2026 kullanıcı kararları).

1. İrsaliyeli satış: stok irsaliyede bir kez çıkar; SMM (621/153) fatura tarihli fişte bir kez yazılır.
2. Satış iadesi: tutar 610 borç; maliyet ilk satıştaki maliyetle geri alınır (153 B / 621 A), kısmi
   iadede yalnız iade miktarı. Satış maliyeti bulunamazsa tahmin yok: evrak 'İnceleme gerekiyor'.
3. Tedarikçi açılışı: borcumuz → açık borç kalemi (320 ALACAK), gerçek avans → 159 BORÇ (onaylıysa);
   "alacak" kelimesi tek başına avans sayılmaz.

Her test yalıtılmış geçici veritabanında çalışır.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sqlalchemy import func, select  # noqa: E402

import database.models.sube  # noqa: E402,F401
import test_masraf_dagitim as tmd  # noqa: E402
import test_muhasebelestirme_ayarlari as tma  # noqa: E402
from database.database import get_session  # noqa: E402

TARIH_IRS = date(2026, 6, 3)
TARIH_FAT = date(2026, 6, 5)
TARIH_IADE = date(2026, 6, 8)


class MuhasebeKurallariTest(unittest.TestCase):
    setUp_temel = tma.MuhasebelestirmeAyarlariTest.setUp
    tearDown = tma.MuhasebelestirmeAyarlariTest.tearDown
    _alis = tmd.MasrafDagitimTest._alis
    _sat = tmd.MasrafDagitimTest._sat
    _gm_kur = tmd.MasrafDagitimTest._gm_kur
    _servis = staticmethod(tma.MuhasebelestirmeAyarlariTest._servis)
    _fis_sayisi = tma.MuhasebelestirmeAyarlariTest._fis_sayisi
    _durum = tma.MuhasebelestirmeAyarlariTest._durum
    _bakiyeler = tma.MuhasebelestirmeAyarlariTest._bakiyeler
    _tutarli = tma.MuhasebelestirmeAyarlariTest._tutarli

    def setUp(self):
        self.setUp_temel()
        self._hesap_ekle("satistan_iadeler", "610.01.0001", "Satıştan İadeler", "Gelir")
        self._hesap_ekle("verilen_siparis_avanslari", "159.01.0001", "Verilen Sipariş Avansları", "Aktif")
        self._servis().ayar_kaydet(gm_kullan=True, varsayilan="otomatik",
                                   turler={"satis_iade": "otomatik"})

    # ------------------------------------------------------------ yardımcılar
    def _hesap_ekle(self, anahtar, kod, ad, tur):
        from database.models.genel_muhasebe import HesapPlani, MuhasebeHesapEsleme

        with get_session() as s:
            h = s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == kod))
            if h is None:
                h = HesapPlani(firma_id=self.firma_id, hesap_kodu=kod, hesap_adi=ad, hesap_seviyesi=3,
                               hesap_turu=tur, borc_toplam=0, alacak_toplam=0, aktif=True)
                s.add(h)
                s.flush()
            e = s.scalar(select(MuhasebeHesapEsleme).where(MuhasebeHesapEsleme.anahtar == anahtar))
            if e is None:
                s.add(MuhasebeHesapEsleme(firma_id=self.firma_id, anahtar=anahtar, aciklama=ad,
                                          hesap_id=h.id, aktif=True))
            else:
                e.hesap_id, e.aktif = h.id, True

    def _esleme_kaldir(self, anahtar):
        from database.models.genel_muhasebe import MuhasebeHesapEsleme

        with get_session() as s:
            e = s.scalar(select(MuhasebeHesapEsleme).where(MuhasebeHesapEsleme.anahtar == anahtar))
            e.hesap_id = None

    def _fis_satirlari(self, kaynak_turu, kaynak_id) -> tuple[date, dict[str, tuple[Decimal, Decimal]]]:
        from database.models.genel_muhasebe import HesapPlani, MuhasebeFisi, MuhasebeFisiSatiri

        with get_session() as s:
            fis = s.scalar(select(MuhasebeFisi).where(
                MuhasebeFisi.kaynak_turu == kaynak_turu, MuhasebeFisi.kaynak_id == int(kaynak_id),
                MuhasebeFisi.durum != "İptal"))
            self.assertIsNotNone(fis, f"{kaynak_turu} fişi yok")
            satirlar: dict[str, tuple[Decimal, Decimal]] = {}
            for st in s.scalars(select(MuhasebeFisiSatiri).where(MuhasebeFisiSatiri.fis_id == fis.id)):
                kod = s.get(HesapPlani, st.hesap_id).hesap_kodu
                b, a = satirlar.get(kod, (Decimal("0"), Decimal("0")))
                satirlar[kod] = (b + Decimal(str(st.borc)), a + Decimal(str(st.alacak)))
            return fis.fis_tarihi, satirlar

    def _hareket(self, tur, belge_no=None) -> Decimal:
        from database.models.stok import StokHareketi

        with get_session() as s:
            q = select(func.coalesce(func.sum(StokHareketi.miktar), 0)).where(StokHareketi.hareket_turu == tur)
            if belge_no:
                q = q.where(StokHareketi.belge_no == belge_no)
            return Decimal(str(s.scalar(q) or 0))

    def _irsaliye(self, miktar):
        from database.satis_irsaliyesi_service import SatisIrsaliyesiService

        irs = SatisIrsaliyesiService.kaydet(
            {"irsaliye_tarihi": TARIH_IRS, "cari_id": self.musteri_id, "depo": "ANA DEPO"},
            [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": Decimal(miktar), "birim": "Adet",
              "birim_fiyat": Decimal("200"), "kdv_orani": Decimal("20")}],
        )
        SatisIrsaliyesiService.sevk_et(irs.id)
        return SatisIrsaliyesiService.getir(irs.id)

    def _irsaliyeden_fatura(self, irs, miktar):
        from database.satis_faturasi_service import SatisFaturasiService

        satir = irs.satirlar[0]
        f = SatisFaturasiService.kaydet(
            {"fatura_tarihi": TARIH_FAT, "vade_tarihi": TARIH_FAT, "cari_id": self.musteri_id,
             "depo": "ANA DEPO", "irsaliye_id": irs.id, "odeme_tutari": Decimal("0"), "sales_person_id": 1},
            [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": Decimal(miktar), "birim": "Adet",
              "birim_fiyat": Decimal("200"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20"),
              "irsaliye_satiri_id": satir.id}],
        )
        SatisFaturasiService.onayla(f.id)
        return int(f.id)

    def _fatura_satiri(self, fatura_id) -> int:
        from database.models.satis_faturasi import SatisFaturasiSatiri

        with get_session() as s:
            return int(s.scalar(select(SatisFaturasiSatiri.id).where(SatisFaturasiSatiri.fatura_id == fatura_id)))

    def _iade(self, fatura_id, miktar, *, kaynakli=True):
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        satir = {"urun_kodu": "U001", "urun_adi": "U001", "miktar": Decimal(miktar), "birim": "Adet",
                 "birim_fiyat": Decimal("200"), "kdv_orani": Decimal("20")}
        if kaynakli:
            satir["kaynak_fatura_satiri_id"] = self._fatura_satiri(fatura_id)
        else:
            satir.update(kaynak_yok_onay=True, kaynak_yok_gerekce="Test: kayıtlı satış yok")
        iade = SatisIadeFaturasiService.kaydet(
            {"iade_tarihi": TARIH_IADE, "cari_id": self.musteri_id, "depo": "ANA DEPO",
             "kaynak_fatura_id": fatura_id if kaynakli else None},
            [satir],
        )
        return int(iade.id)

    # ------------------------------------------------------------ 1. irsaliyeli satış
    def test_irsaliyeli_satis_smm_fatura_tarihinde_bir_kez_stok_tekrar_cikmaz(self):
        from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService as H

        self._alis("U001", "100", "100", "LOT-A")
        irs = self._irsaliye("10")
        self.assertEqual(self._hareket("İRSALİYE ÇIKIŞ", irs.irsaliye_no), Decimal("10"))
        fid = self._irsaliyeden_fatura(irs, "10")
        self.assertEqual(self._hareket("FATURA ÇIKIŞ"), Decimal("0"), "faturada stok tekrar çıkmamalı")
        self.assertEqual(self._hareket("İRSALİYE ÇIKIŞ"), Decimal("10"))
        tarih, satirlar = self._fis_satirlari("satis_faturasi", fid)
        self.assertEqual(tarih, TARIH_FAT, "maliyet fatura tarihinde")
        self.assertEqual(satirlar["621.01.0001"], (Decimal("1000.00"), Decimal("0")))
        self.assertEqual(satirlar["153.01.0001"], (Decimal("0"), Decimal("1000.00")))
        # Tekrar çalıştırma: aynı fiş, ikinci maliyet yok
        ilk = self._fis_sayisi("satis_faturasi")
        self.assertEqual(H.satis_faturasi_fisi(fid, yeniden=False), H.mevcut_fis_id("satis_faturasi", fid))
        self.assertEqual(self._fis_sayisi("satis_faturasi"), ilk)
        self.assertEqual(self._bakiyeler()["621.01.0001"], Decimal("1000.00"))
        self._tutarli()

    def test_kismi_faturalanan_irsaliye_maliyeti_toplamda_bir_kez(self):
        self._alis("U001", "100", "100", "LOT-A")
        irs = self._irsaliye("10")
        self._irsaliyeden_fatura(irs, "4")
        from database.satis_irsaliyesi_service import SatisIrsaliyesiService

        self._irsaliyeden_fatura(SatisIrsaliyesiService.getir(irs.id), "6")
        self.assertEqual(self._hareket("İRSALİYE ÇIKIŞ"), Decimal("10"))
        self.assertEqual(self._hareket("FATURA ÇIKIŞ"), Decimal("0"))
        b = self._bakiyeler()
        self.assertEqual(b["621.01.0001"], Decimal("1000.00"))
        self.assertEqual(b["153.01.0001"], Decimal("10000.00") - Decimal("1000.00"))
        self._tutarli()

    # ------------------------------------------------------------ 2. satış iadesi
    def test_kismi_satis_iadesi_610_ve_ilk_satis_maliyetiyle_geri_alinir(self):
        self._alis("U001", "100", "100", "LOT-A")
        fid = self._sat("10")
        iid = self._iade(fid, "3")
        _tarih, satirlar = self._fis_satirlari("satis_iade", iid)
        self.assertEqual(satirlar["610.01.0001"], (Decimal("600.00"), Decimal("0")))
        self.assertEqual(satirlar["391.01.0001"], (Decimal("120.00"), Decimal("0")))
        self.assertEqual(satirlar["120.01.0001"], (Decimal("0"), Decimal("720.00")))
        self.assertEqual(satirlar["153.01.0001"], (Decimal("300.00"), Decimal("0")))
        self.assertEqual(satirlar["621.01.0001"], (Decimal("0"), Decimal("300.00")))
        self.assertNotIn("600.01.0001", satirlar)
        self.assertEqual(self._hareket("İADE GİRİŞ"), Decimal("3"))
        self.assertEqual(self._durum("satis_iade", iid)["durum"], "Muhasebeleştirildi")
        b = self._tutarli()
        self.assertEqual(b["621.01.0001"], Decimal("700.00"), "net SMM: 1000 − 300")

    def test_irsaliyeli_satisin_iadesi_irsaliye_maliyetini_kullanir(self):
        self._alis("U001", "100", "100", "LOT-A")
        fid = self._irsaliyeden_fatura(self._irsaliye("10"), "10")
        iid = self._iade(fid, "2")
        _tarih, satirlar = self._fis_satirlari("satis_iade", iid)
        self.assertEqual(satirlar["153.01.0001"], (Decimal("200.00"), Decimal("0")))
        self.assertEqual(satirlar["621.01.0001"], (Decimal("0"), Decimal("200.00")))
        from database.models.stok import StokLotu

        with get_session() as s:
            maliyetler = {Decimal(str(l.birim_maliyet)) for l in s.scalars(select(StokLotu)).all()}
        self.assertNotIn(Decimal("0"), maliyetler, "iade lotu 0 maliyetle girmemeli")

    def test_kaynaksiz_satis_iadesi_maliyet_tahmin_edilmez_inceleme_gerekiyor(self):
        self._alis("U001", "100", "100", "LOT-A")
        self._sat("10")
        once = self._fis_sayisi("satis_iade")
        iid = self._iade(None, "1", kaynakli=False)
        self.assertEqual(self._fis_sayisi("satis_iade"), once, "fiş tahminle yazılmamalı")
        d = self._durum("satis_iade", iid)
        self.assertEqual(d["durum"], "İnceleme gerekiyor")
        self.assertIn("ilk satış maliyeti bulunamadı", d["aciklama"])
        self.assertEqual(self._hareket("İADE GİRİŞ"), Decimal("1"), "evrak ve stok girişi kaydedilir")

    def test_610_eslemesi_yoksa_evrak_kaydedilir_inceleme_gerekiyor(self):
        self._alis("U001", "100", "100", "LOT-A")
        fid = self._sat("10")
        self._esleme_kaldir("satistan_iadeler")
        iid = self._iade(fid, "1")
        self.assertEqual(self._fis_sayisi("satis_iade"), 0)
        d = self._durum("satis_iade", iid)
        self.assertEqual(d["durum"], "İnceleme gerekiyor")
        self.assertIn("satistan_iadeler", d["aciklama"])

    # ------------------------------------------------------------ 3. tedarikçi açılışı
    def test_tedarikci_borc_acilisi_acik_borc_olur_odeme_kapatir_muhasebe_tutarli(self):
        from database.acik_kalem_service import AcikKalemService
        from database.cari_service import CariService

        _islem, anlam = CariService.acilis_bakiyesi_ekle(
            self.tedarikci_id, date(2026, 1, 1), tutar=Decimal("8000"), yon="A", belge_no="ACL-T001")
        self.assertEqual((anlam.hesap_kodu, anlam.muhasebe_yonu, anlam.durum), ("320", "ALACAK", "Belirli"))
        kasa = self._kasa_id()
        CariService.odeme_yap(self.tedarikci_id, date(2026, 6, 1), Decimal("5000"), "NAKİT / KASA", kasa)
        with get_session() as s:
            borc = AcikKalemService.acik_kalemler(s, self.tedarikci_id, yon="BORC")
            avans = AcikKalemService.acik_kalemler(s, self.tedarikci_id, yon="AVANS")
            self.assertEqual([(h.belge_no, Decimal(str(h.kalan_acik_tutar))) for h in borc],
                             [("ACL-T001", Decimal("3000.00"))])
            self.assertEqual(avans, [], "tedarikçi borç açılışı avans sayılmamalı")
            defter = CariService._defter(s, self.tedarikci_id)
        cari_bakiye = sum((Decimal(str(k["borc"] or 0)) - Decimal(str(k["alacak"] or 0)) for k in defter),
                          Decimal("0"))
        self.assertEqual(cari_bakiye, Decimal("3000.00"), "kalan borcumuz 3.000")
        # Muhasebe: açılış 320 A 8.000 (açılış fişi kapsam dışı) + ödeme 320 B 5.000 → 320 net A 3.000
        self.assertEqual(self._bakiyeler().get("320.01.0001"), Decimal("5000.00"))
        self.assertEqual(Decimal("8000.00") - self._bakiyeler()["320.01.0001"], cari_bakiye)
        onizleme = CariService.acilis_muhasebe_onizleme(self.tedarikci_id)
        self.assertEqual([(o["hesap_kodu"], o["muhasebe_yonu"], o["durum"]) for o in onizleme],
                         [("320", "ALACAK", "Belirli")])

    def test_tedarikci_avans_acilisi_yalniz_onayliysa_159_aksi_inceleme(self):
        from database.acik_kalem_service import AcikKalemService
        from database.cari_service import CariService

        _i, belirsiz = CariService.acilis_bakiyesi_ekle(
            self.tedarikci_id, date(2026, 1, 1), tutar=Decimal("1500"), yon="B", belge_no="ACL-T-B1")
        self.assertEqual(belirsiz.durum, "İnceleme gerekiyor")
        _i, avans = CariService.acilis_bakiyesi_ekle(
            self.nakliyeci_id, date(2026, 1, 1), tutar=Decimal("2000"), yon="B", belge_no="ACL-N-AV",
            avans_onayli=True)
        self.assertEqual((avans.hesap_kodu, avans.muhasebe_yonu), ("159", "BORÇ"))
        with get_session() as s:
            kalem = AcikKalemService.acik_kalemler(s, self.nakliyeci_id, yon="AVANS")
            self.assertEqual([Decimal(str(h.kalan_acik_tutar)) for h in kalem], [Decimal("-2000.00")])
        onizleme = {o["belge_no"]: o for o in CariService.acilis_muhasebe_onizleme()}
        self.assertEqual(onizleme["ACL-T-B1"]["durum"], "İnceleme gerekiyor")
        self.assertEqual((onizleme["ACL-N-AV"]["hesap_kodu"], onizleme["ACL-N-AV"]["durum"]), ("159", "Belirli"))
        self.assertEqual(self._fis_sayisi(), 0, "açılıştan otomatik fiş üretilmez")

    def test_evobulut_acilis_tedarikci_A_borc_musteri_A_inceleme_tekrar_mukerrer_yok(self):
        from database.acik_kalem_service import AcikKalemService
        from database.models.cari import CariIslem
        from entegrasyon.cari_acilis_import import aktar_satirlari, onizle_satirlari

        satirlar = [
            {"R.a_id": "71", "R.a_kod": "T001", "text": "Test Tedarikçi ---- Bakiye : 8,000.00 (A)"},
            {"R.a_id": "72", "R.a_kod": "M001", "text": "Test Müşteri ---- Bakiye : 250.00 (A)"},
        ]
        onizleme = {k["cari_kodu"]: k for k in onizle_satirlari(satirlar)}
        self.assertEqual((onizleme["T001"]["durum"], onizleme["T001"]["muhasebe"]), ("Belirli", "320 ALACAK"))
        self.assertEqual(onizleme["T001"]["yerel_kalem"], "açık kalem")
        self.assertEqual(onizleme["M001"]["durum"], "İnceleme gerekiyor")
        ilk = aktar_satirlari(satirlar, tarih=date(2026, 1, 1))
        self.assertEqual((ilk.olusturulan, len(ilk.inceleme)), (2, 1))
        ikinci = aktar_satirlari(satirlar, tarih=date(2026, 1, 1))
        self.assertEqual((ikinci.olusturulan, ikinci.atlanan), (0, 2), "tekrar çalıştırmada mükerrer yok")
        self.assertTrue(all(k["durum"] == "Aktarılmaz" for k in onizle_satirlari(satirlar)))
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(CariIslem).where(
                CariIslem.belge_no.like("EVB-ACL-%"))), 2)
            borc = AcikKalemService.acik_kalemler(s, self.tedarikci_id, yon="BORC")
            self.assertEqual([Decimal(str(h.kalan_acik_tutar)) for h in borc], [Decimal("8000.00")])
            self.assertEqual(AcikKalemService.acik_kalemler(s, self.tedarikci_id, yon="AVANS"), [])

    def _kasa_id(self):
        from database.models.finans import FinansHesabi

        with get_session() as s:
            h = s.scalar(select(FinansHesabi).where(FinansHesabi.hesap_turu == "KASA"))
            if h is None:
                h = FinansHesabi(hesap_adi="ANA KASA", hesap_turu="KASA", acilis_bakiyesi=Decimal("10000"),
                                 aktif=True)
                s.add(h)
                s.flush()
            return h.hesap_adi


if __name__ == "__main__":
    unittest.main()
