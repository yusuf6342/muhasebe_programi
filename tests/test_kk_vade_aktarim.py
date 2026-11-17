"""KK vade aktarım — tarih ayrımı, FIFO ödeme köprüsü, kart hesabı."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from database.kk_vade_aktarim_service import KkVadeAktarimService, ODEME_ISTEK, _tarih
from tests.stok_test_ortami import StokOrtami


class TarihCozumTest(unittest.TestCase):
    def test_gun_ay_yil_kaymaz(self):
        self.assertEqual(_tarih("25.11.2026"), date(2026, 11, 25))
        self.assertEqual(_tarih("25.11.2026 00:00:00"), date(2026, 11, 25))
        self.assertEqual(_tarih("29.02.2024"), date(2024, 2, 29))
        self.assertEqual(_tarih("31.04.2026"), None)  # geçersiz


class AcilisAdayTest(unittest.TestCase):
    def test_gelecek_taksit_kalan_sifir_yine_alinir(self):
        kaynak = [
            {
                "evo_a_id": "1",
                "tarih": date(2026, 7, 1),
                "vtarih": date(2026, 10, 1),
                "cikan": Decimal("3000.00"),
                "giren": Decimal("0"),
                "taksit": 3,
                "taksit_no": 1,
                "aciklama": "",
                "kalan": Decimal("0"),
                "kapatilan": Decimal("3000.00"),
                "tur": "",
            },
            {
                "evo_a_id": "2",
                "tarih": date(2026, 7, 1),
                "vtarih": date(2026, 11, 1),
                "cikan": Decimal("3000.00"),
                "giren": Decimal("0"),
                "taksit": 3,
                "taksit_no": 2,
                "aciklama": "",
                "kalan": Decimal("0"),
                "kapatilan": Decimal("3000.00"),
                "tur": "",
            },
            {
                "evo_a_id": "3",
                "tarih": date(2026, 7, 1),
                "vtarih": date(2026, 12, 1),
                "cikan": Decimal("3000.00"),
                "giren": Decimal("0"),
                "taksit": 3,
                "taksit_no": 3,
                "aciklama": "",
                "kalan": Decimal("0"),
                "kapatilan": Decimal("3000.00"),
                "tur": "",
            },
        ]
        sec = KkVadeAktarimService._acilis_plan_adaylari(
            kaynak,
            cin_bn_idler=set(),
            acilis_borc=Decimal("9000.00"),
            donem_baslangic=date(2026, 9, 1),
        )
        # Üç gelecek taksit + kalan yok
        self.assertEqual(len([x for x in sec if not x.get("vade_eksik")]), 3)
        self.assertEqual(sum((x["plan_tutar"] for x in sec if not x.get("vade_eksik")), Decimal(0)), Decimal("9000.00"))

    def test_vadesiz_kalan_uydurulmaz(self):
        sec = KkVadeAktarimService._acilis_plan_adaylari(
            [],
            cin_bn_idler=set(),
            acilis_borc=Decimal("100.00"),
            donem_baslangic=date(2026, 9, 1),
        )
        self.assertEqual(len(sec), 1)
        self.assertTrue(sec[0].get("vade_eksik"))
        self.assertIsNone(sec[0].get("vtarih"))


class OdemeKopruFifoTest(unittest.TestCase):
    """Ödeme köprüsü boş ödeme-günü dönemine değil, açık FIFO dönemlerine bağlanır."""

    def setUp(self):
        from database.database import get_session
        from database.models.finans import BankaKarti, FinansHesabi, KrediKartiTanimi

        self.ort = StokOrtami("kk_fifo_kopru")
        with get_session() as s:
            banka = BankaKarti(banka_adi="Test Banka", aktif=True)
            s.add(banka)
            s.flush()
            paylasilan = FinansHesabi(
                hesap_adi="Banka KK ortak",
                hesap_turu="KREDİ KARTI",
                alt_hesap_turu="KREDI_KARTI",
                banka_karti_id=banka.id,
                acilis_bakiyesi=Decimal("0"),
                aktif=True,
            )
            bagli = FinansHesabi(
                hesap_adi="Kart bağlı KK",
                hesap_turu="KREDİ KARTI",
                alt_hesap_turu="KREDI_KARTI",
                banka_karti_id=banka.id,
                acilis_bakiyesi=Decimal("0"),
                aktif=True,
            )
            s.add_all([paylasilan, bagli])
            s.flush()
            kart = KrediKartiTanimi(
                banka_karti_id=banka.id,
                kart_adi="Test Kart",
                hesap_kesim_gunu=10,
                son_odeme_gunu=15,
                bagli_hesap_id=bagli.id,
                aktif=True,
            )
            s.add(kart)
            s.flush()
            self.kart_id = int(kart.id)
            self.bagli_id = int(bagli.id)

    def tearDown(self):
        self.ort.kapat()

    def test_kart_hesabi_bagli_oncesi(self):
        from database.database import get_session
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService
        from database.models.finans import KrediKartiTanimi

        with get_session() as s:
            kart = s.get(KrediKartiTanimi, self.kart_id)
            h = KrediKartiEkstreService.kart_hesabi(s, kart)
            self.assertEqual(int(h.id), self.bagli_id)

    def test_plan_odeme_bagla_fifo_acik_doneme(self):
        from database.database import get_session
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService
        from database.models.finans import KrediKartiEkstreOdeme, KrediKartiTanimi
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        with get_session() as s:
            kart = s.get(KrediKartiTanimi, self.kart_id)
            KkVadeAktarimService._plan_odeme_yaz(
                s,
                kart=kart,
                belge_no="EVB-BN-9001",
                tarih=date(2026, 9, 5),
                tutar=Decimal("1000.00"),
                vtarih=date(2026, 9, 15),
                taksit_sayisi=1,
                taksit_no=1,
                aciklama="harcama",
                kaynak_turu="EVO",
                referans_no=None,
            )
            r = KkVadeAktarimService._plan_odeme_bagla(
                s,
                kart=kart,
                belge_no="KKE-EVO-9002",
                tarih=date(2026, 10, 12),
                tutar=Decimal("1000.00"),
                aciklama="ödeme",
                finans_belge_no="EVB-BN-9002",
            )
            self.assertEqual(r, "yazildi")
            od = s.scalar(
                select(KrediKartiEkstreOdeme)
                .where(KrediKartiEkstreOdeme.istek_anahtari == f"{ODEME_ISTEK}EVB-BN-9002")
                .options(selectinload(KrediKartiEkstreOdeme.ekstre))
            )
            self.assertIsNotNone(od)
            self.assertEqual(od.ekstre.kesim_tarihi, date(2026, 9, 10))
            r2 = KkVadeAktarimService._plan_odeme_bagla(
                s,
                kart=kart,
                belge_no="KKE-EVO-9002",
                tarih=date(2026, 10, 12),
                tutar=Decimal("1000.00"),
                aciklama="ödeme",
                finans_belge_no="EVB-BN-9002",
            )
            self.assertEqual(r2, "zaten_var")
            donem = KrediKartiEkstreService.donem_borclari(s, kart_ids=[self.kart_id])[
                self.kart_id
            ]
            g = donem["donemler"][date(2026, 9, 10)]
            self.assertEqual(g["kalan"], Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
