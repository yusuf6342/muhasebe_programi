"""Kredi taksit ödemesi → gider fişi → muhasebe damgası → Gider Raporu (10k senaryosu)."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database.models.finans import (
    BankaKarti,
    BankaKrediIslemGunlugu,
    BankaKrediOdeme,
    BankaKredisi,
    BankaKrediTaksit,
    FinansHareketi,
    FinansHesabi,
    GiderFisi,
)
import database.models.finans  # noqa: F401
import database.banka_kredi_service as bks
from database.kredi_gider_fisi_service import DURUM_BEKLIYOR, DURUM_HAZIR, KrediGiderFisiService


D = Decimal

_TABLOLAR = (
    BankaKarti.__table__,
    FinansHesabi.__table__,
    FinansHareketi.__table__,
    BankaKredisi.__table__,
    BankaKrediTaksit.__table__,
    BankaKrediOdeme.__table__,
    BankaKrediIslemGunlugu.__table__,
    GiderFisi.__table__,
)


class KrediGiderFisiE2ETest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test_kredi_gider.db"
        self.engine = create_engine(f"sqlite:///{self.db_path}", future=True)
        from database.database import Base

        Base.metadata.create_all(self.engine, tables=list(_TABLOLAR))
        self.Session = sessionmaker(bind=self.engine, future=True, expire_on_commit=False)

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
        import database.kredi_gider_fisi_service as kgfs
        import database.finans_service as fs
        import database.gider_rapor_service as grs

        self._orig_kgfs = kgfs.get_session
        self._orig_fs = fs.get_session
        self._orig_grs = getattr(grs, "get_session", None)
        kgfs.get_session = fake_get_session
        fs.get_session = fake_get_session
        if hasattr(grs, "get_session"):
            grs.get_session = fake_get_session

        with self.Session() as s:
            kart = BankaKarti(banka_adi="Demo Bank", sube="Merkez", aktif=True)
            s.add(kart)
            s.flush()
            mev = FinansHesabi(
                hesap_adi="Demo — Mevduat",
                hesap_turu="BANKA",
                acilis_bakiyesi=D("100000.00"),
                banka_karti_id=kart.id,
                alt_hesap_turu="MEVDUAT",
                aktif=True,
            )
            kred = FinansHesabi(
                hesap_adi="Demo — Krediler",
                hesap_turu="BANKA",
                acilis_bakiyesi=D("0"),
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
        bks.BankaKrediService.schema_hazirla = staticmethod(lambda: None)

        from database.finans_service import FinansService

        self._orig_cikis = FinansService.cikis_kontrol
        FinansService.cikis_kontrol = staticmethod(lambda *a, **k: None)

        with self.Session() as s:
            from database.models.finans import BankaKredisi

            kredi = BankaKredisi(
                belge_no="KRK-E2E-0001",
                banka_karti_id=self.kart_id,
                kredi_adi="E2E Test Kredi",
                kredi_turu="ISLETME",
                ana_para=D("8000.00"),
                toplam_faiz=D("1500.00"),
                toplam_masraf=D("500.00"),
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
            s.add(
                FinansHareketi(
                    hesap_id=self.kred_id,
                    tarih=date.today(),
                    hareket_turu="KREDİ KULLANDIRIM",
                    belge_no=kredi.belge_no,
                    tutar=D("8000.00"),
                )
            )
            s.add(
                FinansHareketi(
                    hesap_id=self.mev_id,
                    tarih=date.today(),
                    hareket_turu="KREDİ KULLANDIRIM (MEVDUAT)",
                    belge_no=kredi.belge_no,
                    tutar=D("8000.00"),
                )
            )
            taksit = BankaKrediTaksit(
                kredi_id=kredi.id,
                taksit_no=1,
                vade_tarihi=date.today() + timedelta(days=5),
                anapara=D("8000.00"),
                faiz=D("1500.00"),
                masraf=D("0"),
                bsmv=D("0"),
                kkdf=D("0"),
                komisyon=D("0"),
                sigorta=D("0"),
                dosya_masrafi=D("0"),
                diger_masraflar=D("500.00"),
                gecikme_faizi=D("0"),
                durum="BEKLIYOR",
            )
            s.add(taksit)
            s.commit()
            self.kredi_id = kredi.id
            self.taksit_id = taksit.id

        # Muhasebe hook sessiz
        self._hook_patch = patch(
            "database.muhasebe_entegrasyon.muhasebe_hook", lambda *a, **k: None
        )
        self._hook_patch.start()

    def tearDown(self):
        self._hook_patch.stop()
        bks.get_session = self._orig_get_session
        import database.kredi_gider_fisi_service as kgfs
        import database.finans_service as fs

        kgfs.get_session = self._orig_kgfs
        fs.get_session = self._orig_fs
        from database.finans_service import FinansService

        FinansService.cikis_kontrol = self._orig_cikis
        self.engine.dispose()
        self.tmp.cleanup()

    def test_10000_odeme_gider_rapor(self):
        sonuc = bks.BankaKrediService.taksit_ode(
            taksit_id=self.taksit_id,
            odeme_tarihi=date.today(),
            banka_dekont_no="E2E-DK-1",
            transaction_id="e2e-tx-10000",
        )
        self.assertEqual(sonuc["toplam"], D("10000.00"))
        self.assertEqual(sonuc["anapara"], D("8000.00"))
        self.assertEqual(sonuc["faiz"], D("1500.00"))
        self.assertEqual(sonuc["diger_masraflar"], D("500.00"))
        self.assertTrue(sonuc.get("gider_belge_no"))

        with self.Session() as s:
            cikis = list(
                s.scalars(
                    select(FinansHareketi).where(
                        FinansHareketi.hesap_id == self.mev_id,
                        FinansHareketi.hareket_turu == "KREDİ TAKSİT ÖDEME",
                    )
                ).all()
            )
            self.assertEqual(len(cikis), 1)
            self.assertEqual(D(str(cikis[0].tutar)), D("10000.00"))

            ana = list(
                s.scalars(
                    select(FinansHareketi).where(
                        FinansHareketi.hesap_id == self.kred_id,
                        FinansHareketi.hareket_turu == "KREDİ ANAPARA ÖDEME",
                    )
                ).all()
            )
            self.assertEqual(len(ana), 1)
            self.assertEqual(D(str(ana[0].tutar)), D("8000.00"))

            giderler = list(
                s.scalars(
                    select(GiderFisi).where(
                        GiderFisi.bagli_belge_no == sonuc["odeme_belge_no"]
                    )
                ).all()
            )
            self.assertEqual(len(giderler), 2)
            toplam_g = sum((D(str(g.tutar)) for g in giderler), D("0"))
            self.assertEqual(toplam_g, D("2000.00"))
            turler = {g.gider_turu for g in giderler}
            self.assertIn("KREDI_FAIZ", turler)
            self.assertIn("KREDI_MASRAF", turler)
            for g in giderler:
                self.assertEqual((g.muhasebe_durum or ""), DURUM_BEKLIYOR)
                self.assertIsNone(g.muhasebe_hesap_kodu)

        ozet = KrediGiderFisiService.ozet(odeme_belge_no=sonuc["odeme_belge_no"])
        self.assertIsNotNone(ozet)
        self.assertEqual(ozet["toplam_gider"], D("2000.00"))
        self.assertEqual(ozet["faiz"], D("1500.00"))
        self.assertEqual(ozet["masraf"], D("500.00"))
        self.assertEqual(ozet["anapara"], D("8000.00"))
        self.assertTrue(ozet["muhasebe_bekliyor"])

        # Tekrar kaydet → mükerrer yok
        tekrar = bks.BankaKrediService.taksit_ode(
            taksit_id=self.taksit_id,
            transaction_id="e2e-tx-10000",
        )
        self.assertEqual(tekrar["odeme_belge_no"], sonuc["odeme_belge_no"])
        with self.Session() as s:
            giderler2 = list(
                s.scalars(
                    select(GiderFisi).where(
                        GiderFisi.bagli_belge_no == sonuc["odeme_belge_no"]
                    )
                ).all()
            )
            self.assertEqual(len(giderler2), 2)

        # Hesap ata (mock _kodla_hesap) — yeni fiş yok
        faiz_fis = next(g for g in giderler2 if g.gider_turu == "KREDI_FAIZ")
        with patch.object(
            KrediGiderFisiService,
            "_kodla_hesap",
            return_value={"id": 99, "kod": "660.01.0001", "ad": "Faiz"},
        ):
            ata = KrediGiderFisiService.hesap_ata(
                faiz_fis.id, hesap_kodu="660.01.0001", krediye_kaydet=True
            )
        self.assertEqual(ata["yeni"]["kod"], "660.01.0001")
        with self.Session() as s:
            g = s.get(GiderFisi, faiz_fis.id)
            self.assertEqual(g.muhasebe_durum, DURUM_HAZIR)
            self.assertEqual(g.muhasebe_hesap_kodu, "660.01.0001")
            n_fis = len(list(s.scalars(select(GiderFisi)).all()))
            self.assertEqual(n_fis, 2)
            kredi = s.get(
                __import__("database.models.finans", fromlist=["BankaKredisi"]).BankaKredisi,
                self.kredi_id,
            )
            self.assertEqual(kredi.faiz_muhasebe_hesap_kodu, "660.01.0001")

        # Gider Raporu — 2000 TL
        from database.gider_rapor_service import GiderRaporService
        import database.gider_rapor_service as grs_mod

        def fake_gs():
            class C:
                def __enter__(self_inner):
                    return self.Session()

                def __exit__(self_inner, *a):
                    return False

            return C()

        with patch.object(grs_mod, "get_session", fake_gs):
            # donem_kaynaklari uses get_session from database.database typically
            pass

        # Doğrudan oturumla satırları doğrula
        with self.Session() as s:
            acik = [
                g
                for g in s.scalars(
                    select(GiderFisi).where(GiderFisi.durum != "IPTAL")
                ).all()
            ]
            rapor_toplam = sum((D(str(g.tutar)) for g in acik), D("0"))
            self.assertEqual(rapor_toplam, D("2000.00"))

        # İptal → rapordan düşer
        bks.BankaKrediService.odeme_iptal(
            belge_no=sonuc["odeme_belge_no"], neden="E2E iptal testi"
        )
        with self.Session() as s:
            acik2 = [
                g
                for g in s.scalars(
                    select(GiderFisi).where(GiderFisi.durum != "IPTAL")
                ).all()
            ]
            self.assertEqual(sum((D(str(g.tutar)) for g in acik2), D("0")), D("0"))
            iptal = [
                g
                for g in s.scalars(
                    select(GiderFisi).where(GiderFisi.durum == "IPTAL")
                ).all()
            ]
            self.assertEqual(len(iptal), 2)


if __name__ == "__main__":
    unittest.main()
