"""Kesinleşmiş muhasebe fişi iptali tutarı yalnız bir kez ters çevirir.

Hesap planı bakiyeleri (borç/alacak toplamları) ile mizan aynı sonucu verir; satış, alış,
hizmet faturası ve gider fişi iptalinde ilgili hesaplar başlangıç değerine döner, tekrar iptal
ikinci etki üretmez.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sqlalchemy import func, select  # noqa: E402

import database.models.sube  # noqa: E402,F401
import test_masraf_dagitim as tmd  # noqa: E402
import test_masraf_dagitim_baglanti as tmb  # noqa: E402
from database.database import get_session  # noqa: E402


def _gercek_hook(fn_name, *args, **kwargs):
    from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

    return getattr(MuhasebeEntegrasyonService, fn_name)(*args, **kwargs)


class MuhasebeFisIptalTest(unittest.TestCase):
    setUp = tmd.MasrafDagitimTest.setUp
    tearDown = tmd.MasrafDagitimTest.tearDown
    _alis = tmd.MasrafDagitimTest._alis
    _gider = tmd.MasrafDagitimTest._gider
    _sat = tmd.MasrafDagitimTest._sat
    _kasa = tmb.MasrafBaglantiTest._kasa
    _gider_fisi = tmb.MasrafBaglantiTest._gider_fisi

    def _gercek(self):
        return patch("database.muhasebe_entegrasyon.muhasebe_hook", _gercek_hook)

    def _bakiyeler(self) -> dict[str, Decimal]:
        """Hesap planındaki borç - alacak (sıfır olmayanlar)."""
        from database.models.genel_muhasebe import HesapPlani

        with get_session() as s:
            sonuc = {h.hesap_kodu: Decimal(str(h.borc_toplam)) - Decimal(str(h.alacak_toplam))
                     for h in s.scalars(select(HesapPlani)).all()}
        return {k: v for k, v in sonuc.items() if v != 0}

    def _mizan(self) -> dict[str, Decimal]:
        from database.muhasebe_service import MuhasebeRaporService

        m = MuhasebeRaporService.mizan(date(2000, 1, 1), date(2099, 12, 31))
        sonuc = {s["hesap_kodu"]: s["borc_bakiyesi"] - s["alacak_bakiyesi"] for s in m["satirlar"]}
        self.assertTrue(m["dengeli"])
        return {k: v for k, v in sonuc.items() if v != 0}

    def _tutarli(self) -> dict[str, Decimal]:
        """Hesap bakiyesi ve mizan aynı kaynağı farklı yoldan okur; ikisi eşit olmalı."""
        b = self._bakiyeler()
        self.assertEqual(b, self._mizan())
        return b

    def _fis_id(self, kaynak_turu, kaynak_id):
        from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

        return MuhasebeEntegrasyonService.mevcut_fis_id(kaynak_turu, kaynak_id)

    # ----------------------------------------------------------------- testler
    def test_manuel_fis_iptali_tek_ters_kayit_ve_tekrar_iptal(self):
        from database.models.genel_muhasebe import HesapPlani, MuhasebeFisi
        from database.muhasebe_service import MuhasebeFisService, MuhasebeRaporService

        with get_session() as s:
            gider = s.scalar(select(HesapPlani.id).where(HesapPlani.hesap_kodu == "770.01.0001"))
            kasa = s.scalar(select(HesapPlani.id).where(HesapPlani.hesap_kodu == "100.01.0001"))
        fis_id = MuhasebeFisService.kaydet(
            {"fis_tarihi": date(2026, 6, 15), "fis_turu": "Tediye Fişi", "durum": "Kesinleşmiş",
             "satirlar": [{"hesap_id": gider, "borc": "500"}, {"hesap_id": kasa, "alacak": "500"}]},
            otomatik=True,
        )
        self.assertEqual(self._tutarli(), {"770.01.0001": Decimal("500"), "100.01.0001": Decimal("-500")})
        gelir0 = MuhasebeRaporService.gelir_tablosu(date(2026, 1, 1), date(2026, 12, 31))["net_kar"]
        self.assertEqual(gelir0, Decimal("-500"))

        ters_id = MuhasebeFisService.iptal(fis_id, "yanlış kayıt", otomatik=True)
        self.assertIsNotNone(ters_id)
        self.assertEqual(self._tutarli(), {})
        self.assertEqual(MuhasebeRaporService.gelir_tablosu(date(2026, 1, 1), date(2099, 12, 31))["net_kar"],
                         Decimal("0"))
        with get_session() as s:
            asil = s.get(MuhasebeFisi, fis_id)
            self.assertEqual((asil.durum, asil.ters_fis_id), ("İptal", ters_id))

        with self.assertRaises(ValueError):
            MuhasebeFisService.iptal(fis_id, "tekrar", otomatik=True)
        self.assertEqual(self._tutarli(), {})
        with get_session() as s:
            self.assertEqual(len(s.scalars(select(MuhasebeFisi)).all()), 2)

    def test_alis_faturasi_kayit_duzenleme_ve_iptal(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.muhasebe_service import MuhasebeFisService

        with self._gercek():
            fid, _satir = self._alis("U001", "100", "100", "LOT-A")
        self.assertEqual(self._tutarli(), {"153.01.0001": Decimal("10000"), "191.01.0001": Decimal("2000"),
                                           "320.01.0001": Decimal("-12000")})
        # Düzenleme eski fişi iptal edip yenisini yazar: yalnız yeni tutar kalmalı
        f = AlisFaturasiService.getir(fid)
        with self._gercek():
            AlisFaturasiService.kaydet(
                {"fatura_tarihi": f.fatura_tarihi, "vade_tarihi": f.vade_tarihi, "cari_id": f.cari_id,
                 "depo": "ANA DEPO", "odeme_tutari": Decimal("0")},
                [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": Decimal("90"), "birim": "Adet",
                  "birim_fiyat": Decimal("100"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20"),
                  "lot_no": "LOT-A"}],
                fatura_id=fid,
            )
        self.assertEqual(self._tutarli(), {"153.01.0001": Decimal("9000"), "191.01.0001": Decimal("1800"),
                                           "320.01.0001": Decimal("-10800")})
        fis_id = self._fis_id("alis_faturasi", fid)
        with self._gercek():
            AlisFaturasiService.iptal_et(fid)
        self.assertEqual(self._tutarli(), {})
        with self._gercek():
            AlisFaturasiService.iptal_et(fid)  # belge zaten iptal: etkisiz
        with self.assertRaises(ValueError):
            MuhasebeFisService.iptal(fis_id, "tekrar", otomatik=True)
        self.assertEqual(self._tutarli(), {})

    def test_satis_faturasi_iptali_satis_kdv_cari_ve_maliyet_geri_doner(self):
        from database.muhasebe_service import MuhasebeFisService
        from database.satis_faturasi_service import SatisFaturasiService

        with self._gercek():
            self._alis("U001", "100", "100", "LOT-A")
        baslangic = self._tutarli()
        with self._gercek():
            sid = self._sat("40")
        sonra = self._tutarli()
        self.assertEqual(sonra["600.01.0001"], Decimal("-8000"))
        self.assertEqual(sonra["391.01.0001"], Decimal("-1600"))
        self.assertEqual(sonra["120.01.0001"], Decimal("9600"))
        self.assertEqual(sonra["621.01.0001"], Decimal("4000"))
        self.assertEqual(sonra["153.01.0001"], Decimal("6000"))
        fis_id = self._fis_id("satis_faturasi", sid)

        with self._gercek():
            SatisFaturasiService.iptal_et(sid, "test iptali")
        self.assertEqual(self._tutarli(), baslangic)
        with self._gercek():
            SatisFaturasiService.iptal_et(sid, "tekrar")
        with self.assertRaises(ValueError):
            MuhasebeFisService.iptal(fis_id, "tekrar", otomatik=True)
        self.assertEqual(self._tutarli(), baslangic)

    def test_hizmet_faturasi_ve_gider_fisi_iptali(self):
        from database.finans_service import FinansService
        from database.hizmet_faturasi_service import HizmetFaturasiService

        with self._gercek():
            kaynak_id, _ks = self._gider("1000")
        self.assertEqual(self._tutarli(), {"770.01.0001": Decimal("1000"), "191.01.0001": Decimal("200"),
                                           "320.01.0001": Decimal("-1200")})
        with self._gercek():
            HizmetFaturasiService.iptal_et(kaynak_id)
        self.assertEqual(self._tutarli(), {})
        with self._gercek():
            HizmetFaturasiService.iptal_et(kaynak_id)
        self.assertEqual(self._tutarli(), {})

        with self._gercek():
            fis_id = self._gider_fisi("750")
        self.assertEqual(self._tutarli(), {"770.01.0001": Decimal("750"), "100.01.0001": Decimal("-750")})
        with self._gercek():
            FinansService.gider_fisi_iptal(fis_id)
        self.assertEqual(self._tutarli(), {})
        with self.assertRaises(ValueError):
            with self._gercek():
                FinansService.gider_fisi_iptal(fis_id)
        self.assertEqual(self._tutarli(), {})

    def test_masraf_dagitimi_geri_alma_bakiyeleri_tutarli(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        with self._gercek():
            _fid, satir = self._alis("U001", "100", "100", "LOT-A")
            kaynak_id, ks = self._gider("1000")
        once = self._tutarli()
        veri = tmd.MasrafDagitimTest._veri(self, kaynak_id, ks, [satir])
        did = MasrafDagitimService.taslak_kaydet(veri)
        MasrafDagitimService.onayla(did)
        sonra = self._tutarli()
        self.assertEqual(sonra.get("770.01.0001", Decimal("0")), Decimal("0"))
        self.assertEqual(sonra["153.01.0001"], once["153.01.0001"] + Decimal("1000"))
        self.assertTrue(MasrafDagitimService.geri_al(did, "test"))
        self.assertEqual(self._tutarli(), once)
        self.assertFalse(MasrafDagitimService.geri_al(did, "tekrar"))
        self.assertEqual(self._tutarli(), once)

    def _kayit_sayilari(self) -> tuple[int, int, int]:
        from database.models.genel_muhasebe import MuhasebeFisi, MuhasebeFisiSatiri, MuhasebeIslemGecmisi

        with get_session() as s:
            return tuple(
                s.scalar(select(func.count()).select_from(m))
                for m in (MuhasebeFisi, MuhasebeFisiSatiri, MuhasebeIslemGecmisi)
            )

    def test_ters_fis_iptal_edilemez_kayit_ve_bakiye_degismez(self):
        from database.masraf_dagitim_service import MasrafDagitimService
        from database.models.genel_muhasebe import MuhasebeFisi
        from database.muhasebe_service import MuhasebeFisService
        from database.satis_faturasi_service import SatisFaturasiService

        with self._gercek():
            _fid, satir = self._alis("U001", "100", "100", "LOT-A")
            sid = self._sat("40")
        fis_id = self._fis_id("satis_faturasi", sid)
        with self._gercek():
            SatisFaturasiService.iptal_et(sid, "test iptali")
        with get_session() as s:
            ters_id = s.get(MuhasebeFisi, fis_id).ters_fis_id
        self.assertIsNotNone(ters_id)
        once, sayilar = self._tutarli(), self._kayit_sayilari()
        for _ in range(2):
            with self.subTest("satış ters fişi"), self.assertRaisesRegex(ValueError, "ters kaydıdır"):
                MuhasebeFisService.iptal(ters_id, "ters fişi geri al", otomatik=True)
            self.assertEqual(self._tutarli(), once)
            self.assertEqual(self._kayit_sayilari(), sayilar)
        with get_session() as s:
            self.assertEqual(s.get(MuhasebeFisi, ters_id).durum, "Kesinleşmiş")

        with self._gercek():
            kaynak_id, ks = self._gider("1000")
        veri = tmd.MasrafDagitimTest._veri(self, kaynak_id, ks, [satir])
        did = MasrafDagitimService.taslak_kaydet(veri)
        MasrafDagitimService.onayla(did)
        self.assertTrue(MasrafDagitimService.geri_al(did, "test"))
        d = MasrafDagitimService.getir(did)
        once, sayilar = self._tutarli(), self._kayit_sayilari()
        with self.subTest("masraf geri alma fişi"), self.assertRaisesRegex(ValueError, "ters kaydıdır"):
            MuhasebeFisService.iptal(d["ters_fis_id"], "geri almayı geri al", otomatik=True)
        with self.subTest("masraf asıl fişi"), self.assertRaisesRegex(ValueError, "ters kaydı zaten var"):
            MuhasebeFisService.iptal(d["fis_id"], "asılı iptal", otomatik=True)
        self.assertEqual(self._tutarli(), once)
        self.assertEqual(self._kayit_sayilari(), sayilar)

    def test_bakiyeleri_yeniden_hesapla_kuru_ve_secili_hesaplar(self):
        from database.models.genel_muhasebe import HesapPlani, MuhasebeFisi, MuhasebeIslemGecmisi
        from database.muhasebe_service import HesapPlanService, MuhasebeFisService

        with get_session() as s:
            gider = s.scalar(select(HesapPlani.id).where(HesapPlani.hesap_kodu == "770.01.0001"))
            kasa = s.scalar(select(HesapPlani.id).where(HesapPlani.hesap_kodu == "100.01.0001"))
        for tutar in ("500", "300"):
            fis_id = MuhasebeFisService.kaydet(
                {"fis_tarihi": date(2026, 6, 15), "fis_turu": "Tediye Fişi", "durum": "Kesinleşmiş",
                 "satirlar": [{"hesap_id": gider, "borc": tutar}, {"hesap_id": kasa, "alacak": tutar}]},
                otomatik=True,
            )
        MuhasebeFisService.iptal(fis_id, "yanlış", otomatik=True)
        self.assertEqual(self._tutarli(), {"770.01.0001": Decimal("500"), "100.01.0001": Decimal("-500")})
        self.assertEqual(HesapPlanService.bakiyeleri_yeniden_hesapla(), [])

        # Eski çift ters çevirme hatasının bıraktığı sapma: iptal edilen tutar bir kez daha düşülmüş
        with get_session() as s:
            for hid, alan in ((gider, "borc_toplam"), (kasa, "alacak_toplam")):
                h = s.get(HesapPlani, hid)
                setattr(h, alan, Decimal(str(getattr(h, alan))) - Decimal("300"))
        fisler_once = self._kayit_sayilari()[:2]
        with get_session() as s:
            gecmis_once = s.scalar(select(func.count()).select_from(MuhasebeIslemGecmisi))

        kuru = HesapPlanService.bakiyeleri_yeniden_hesapla()
        self.assertEqual(
            [(f["hesap_kodu"], f["eski_bakiye"], f["yeni_bakiye"]) for f in kuru],
            [("100.01.0001", Decimal("-200"), Decimal("-500")), ("770.01.0001", Decimal("200"), Decimal("500"))],
        )
        self.assertEqual(self._bakiyeler(), {"770.01.0001": Decimal("200"), "100.01.0001": Decimal("-200")})

        with self.assertRaisesRegex(ValueError, "Hesap bulunamadı: 999"):
            HesapPlanService.bakiyeleri_yeniden_hesapla(["770.01.0001", "999"], kuru=False)
        self.assertEqual(self._bakiyeler()["770.01.0001"], Decimal("200"))

        duzelen = HesapPlanService.bakiyeleri_yeniden_hesapla(["770.01.0001"], kuru=False)
        self.assertEqual([f["hesap_kodu"] for f in duzelen], ["770.01.0001"])
        self.assertEqual(self._bakiyeler(), {"770.01.0001": Decimal("500"), "100.01.0001": Decimal("-200")})
        self.assertEqual(HesapPlanService.bakiyeleri_yeniden_hesapla(["770.01.0001"], kuru=False), [])
        with get_session() as s:
            kayitlar = s.scalars(
                select(MuhasebeIslemGecmisi).where(MuhasebeIslemGecmisi.islem == "bakiye_yeniden_hesapla")
            ).all()
            self.assertEqual([(k.kayit_turu, k.kayit_id) for k in kayitlar], [("hesap", gider)])
            self.assertIn("770.01.0001", kayitlar[0].detay)
            self.assertEqual(s.scalar(select(func.count()).select_from(MuhasebeIslemGecmisi)), gecmis_once + 1)

        HesapPlanService.bakiyeleri_yeniden_hesapla(kuru=False)
        self.assertEqual(self._tutarli(), {"770.01.0001": Decimal("500"), "100.01.0001": Decimal("-500")})
        self.assertEqual(self._kayit_sayilari()[:2], fisler_once)
        with get_session() as s:
            self.assertEqual(s.get(MuhasebeFisi, fis_id).durum, "İptal")


if __name__ == "__main__":
    unittest.main()
