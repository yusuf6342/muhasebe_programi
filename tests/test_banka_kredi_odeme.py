"""Banka kredileri — tek ödeme / çoklu dağılım smoke testleri."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from database.database import Base
from database.models.finans import (
    BankaKarti,
    BankaKrediOdeme,
    BankaKrediTaksit,
    FinansHareketi,
    FinansHesabi,
    GiderFisi,
)
import database.models.finans  # noqa: F401
import database.banka_kredi_service as bks


class BankaKrediOdemeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_kredi.db"
        self.engine = create_engine(f"sqlite:///{self.db_path}", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True, expire_on_commit=False)

        # get_session monkeypatch
        self._orig_get_session = bks.get_session

        class _Ctx:
            def __init__(self, sess):
                self.sess = sess

            def __enter__(self):
                return self.sess

            def __exit__(self, exc_type, exc, tb):
                if exc_type:
                    self.sess.rollback()
                else:
                    self.sess.commit()
                self.sess.close()
                return False

        def fake_get_session():
            return _Ctx(self.Session())

        bks.get_session = fake_get_session

        # Minimal bank + accounts
        with self.Session() as s:
            kart = BankaKarti(banka_adi="Test Bank", sube="Merkez", aktif=True)
            s.add(kart)
            s.flush()
            mev = FinansHesabi(
                hesap_adi="Test Bank — Mevduat",
                hesap_turu="BANKA",
                acilis_bakiyesi=Decimal("100000.00"),
                banka_karti_id=kart.id,
                alt_hesap_turu="MEVDUAT",
                aktif=True,
            )
            kred = FinansHesabi(
                hesap_adi="Test Bank — Krediler",
                hesap_turu="BANKA",
                acilis_bakiyesi=Decimal("0"),
                banka_karti_id=kart.id,
                alt_hesap_turu="KREDILER",
                aktif=True,
            )
            s.add_all([mev, kred])
            s.commit()
            self.kart_id = kart.id
            self.mev_id = mev.id
            self.kred_id = kred.id

        bks.BankaKrediService._izin = staticmethod(lambda *a, **k: None)
        bks.BankaKrediService._iptal_izni = staticmethod(lambda: None)
        bks.BankaKrediService._muhasebe_fis_olustur = staticmethod(lambda *a, **k: None)
        bks.BankaKrediService.schema_hazirla = staticmethod(lambda: None)

        from database.finans_service import FinansService
        import database.finans_service as fs

        self._orig_cikis = FinansService.cikis_kontrol
        FinansService.cikis_kontrol = staticmethod(lambda *a, **k: None)
        self._orig_fs_session = fs.get_session
        fs.get_session = bks.get_session

        # Direct create credit + installment for isolation
        with self.Session() as s:
            from database.models.finans import BankaKredisi

            kredi = BankaKredisi(
                belge_no="KRK-2026-0001",
                banka_karti_id=self.kart_id,
                kredi_adi="Test TL Kredi",
                kredi_turu="ISLETME",
                ana_para=Decimal("10000.00"),
                toplam_faiz=Decimal("2000.00"),
                toplam_masraf=Decimal("150.00"),
                taksit_sayisi=1,
                kullandirim_tarihi=date.today(),
                ilk_taksit_tarihi=date.today(),
                odeme_hesap_turu="MEVDUAT",
                durum="KULLANDIRILDI",
                para_birimi="TRY",
                aktif=True,
            )
            s.add(kredi)
            s.flush()
            # Simulate drawdown liability
            s.add(
                FinansHareketi(
                    hesap_id=self.kred_id,
                    tarih=date.today(),
                    hareket_turu="KREDİ KULLANDIRIM",
                    belge_no=kredi.belge_no,
                    tutar=Decimal("10000.00"),
                )
            )
            s.add(
                FinansHareketi(
                    hesap_id=self.mev_id,
                    tarih=date.today(),
                    hareket_turu="KREDİ KULLANDIRIM (MEVDUAT)",
                    belge_no=kredi.belge_no,
                    tutar=Decimal("10000.00"),
                )
            )
            taksit = BankaKrediTaksit(
                kredi_id=kredi.id,
                taksit_no=1,
                vade_tarihi=date.today() + timedelta(days=5),
                anapara=Decimal("10000.00"),
                faiz=Decimal("2000.00"),
                masraf=Decimal("150.00"),
                bsmv=Decimal("100.00"),
                kkdf=Decimal("0"),
                komisyon=Decimal("50.00"),
                sigorta=Decimal("0"),
                dosya_masrafi=Decimal("0"),
                diger_masraflar=Decimal("0"),
                gecikme_faizi=Decimal("0"),
                durum="BEKLIYOR",
            )
            s.add(taksit)
            s.commit()
            self.kredi_id = kredi.id
            self.taksit_id = taksit.id

    def tearDown(self):
        bks.get_session = self._orig_get_session
        from database.finans_service import FinansService
        import database.finans_service as fs

        FinansService.cikis_kontrol = self._orig_cikis
        fs.get_session = self._orig_fs_session
        self.engine.dispose()
        self.tmp.cleanup()

    def test_tek_banka_cikis_ve_anapara_gider_degil(self):
        # Adjust remaining masraf: total should be ana+faiz+bsmv+komisyon = 12150
        # Current masraf=150 but bsmv+komisyon=150 — taksit_bilesenleri may double-count
        # Set masraf=0 so components are clean
        with self.Session() as s:
            t = s.get(BankaKrediTaksit, self.taksit_id)
            t.masraf = Decimal("0")
            s.commit()

        sonuc = bks.BankaKrediService.taksit_ode(
            taksit_id=self.taksit_id,
            odeme_tarihi=date.today(),
            banka_dekont_no="DK-001",
            bilesenler={
                "anapara": Decimal("10000.00"),
                "faiz": Decimal("2000.00"),
                "bsmv": Decimal("100.00"),
                "kkdf": Decimal("0"),
                "komisyon": Decimal("50.00"),
                "sigorta": Decimal("0"),
                "dosya_masrafi": Decimal("0"),
                "diger_masraflar": Decimal("0"),
                "gecikme_faizi": Decimal("0"),
            },
        )
        self.assertEqual(sonuc["toplam"], Decimal("12150.00"))

        with self.Session() as s:
            cikislar = list(
                s.scalars(
                    select(FinansHareketi).where(
                        FinansHareketi.hesap_id == self.mev_id,
                        FinansHareketi.hareket_turu == "KREDİ TAKSİT ÖDEME",
                    )
                ).all()
            )
            self.assertEqual(len(cikislar), 1)
            self.assertEqual(Decimal(str(cikislar[0].tutar)), Decimal("12150.00"))

            anapara_hareket = list(
                s.scalars(
                    select(FinansHareketi).where(
                        FinansHareketi.hesap_id == self.kred_id,
                        FinansHareketi.hareket_turu == "KREDİ ANAPARA ÖDEME",
                    )
                ).all()
            )
            self.assertEqual(len(anapara_hareket), 1)
            self.assertEqual(Decimal(str(anapara_hareket[0].tutar)), Decimal("10000.00"))

            giderler = list(
                s.scalars(
                    select(GiderFisi).where(GiderFisi.bagli_belge_no == sonuc["odeme_belge_no"])
                ).all()
            )
            self.assertTrue(giderler)
            gider_toplam = sum((Decimal(str(g.tutar)) for g in giderler), Decimal("0"))
            self.assertEqual(gider_toplam, Decimal("2150.00"))
            # Anapara asla gider fişinde olmamalı
            self.assertFalse(any(g.gider_turu == "KREDI_ANAPARA" for g in giderler))

            # Mükerrer ödeme engeli
            with self.assertRaises(ValueError):
                bks.BankaKrediService.taksit_ode(taksit_id=self.taksit_id)

            # Aynı dekont
            with self.Session() as s2:
                t2 = BankaKrediTaksit(
                    kredi_id=self.kredi_id,
                    taksit_no=2,
                    vade_tarihi=date.today() + timedelta(days=30),
                    anapara=Decimal("100.00"),
                    faiz=Decimal("10.00"),
                    masraf=Decimal("0"),
                    durum="BEKLIYOR",
                )
                # reopen credit if closed
                from database.models.finans import BankaKredisi

                k = s2.get(BankaKredisi, self.kredi_id)
                k.durum = "KULLANDIRILDI"
                s2.add(t2)
                s2.commit()
                tid2 = t2.id
            with self.assertRaises(ValueError):
                bks.BankaKrediService.taksit_ode(
                    taksit_id=tid2,
                    banka_dekont_no="DK-001",
                    bilesenler={"anapara": Decimal("100"), "faiz": Decimal("10")},
                )

    def test_bilesen_toplam_hesabi(self):
        veri = {
            "anapara": Decimal("10000"),
            "faiz": Decimal("2000"),
            "bsmv": Decimal("100"),
            "kkdf": Decimal("0"),
            "komisyon": Decimal("50"),
            "sigorta": Decimal("0"),
            "dosya_masrafi": Decimal("0"),
            "diger_masraflar": Decimal("0"),
            "gecikme_faizi": Decimal("0"),
        }
        self.assertEqual(bks.BankaKrediService.taksit_toplam(veri), Decimal("12150.00"))


if __name__ == "__main__":
    unittest.main()
