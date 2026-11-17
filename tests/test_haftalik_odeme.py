"""Haftalık ödeme — sabit 9 taksit + FDS KULP beklenenleri.

Çalıştırma: python -m unittest tests.test_haftalik_odeme -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.haftalik_odeme_service import (
    TAKSIT_ADET,
    HaftalikOdemeService,
    dokuz_taksit_tutarlari,
    ilk_cuma,
    n_taksit_tutarlari,
    odemeleri_fifo_mahsup,
    plan_belge,
    taksit_adet_dogrula,
)
from database.models.cari import Cari, CariIslem, SatisHareketi
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.haftalik_odeme import CariHaftalikOdemeTaksit
from database.session_manager import oturum


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class DokuzTaksitMatematikTest(unittest.TestCase):
    def test_ilk_cuma(self):
        self.assertEqual(ilk_cuma(date(2026, 11, 13)), date(2026, 11, 13))
        self.assertEqual(ilk_cuma(date(2026, 11, 4)), date(2026, 11, 6))

    def test_dokuz_taksit_toplam(self):
        t = dokuz_taksit_tutarlari(Decimal("61675.40"))
        self.assertEqual(len(t), 9)
        self.assertEqual(sum(t, Decimal("0")), Decimal("61675.40"))
        self.assertEqual(t[0], Decimal("6852.82"))
        self.assertEqual(t[8], Decimal("6852.84"))

    def test_cuma_fatura_ilk_taksit_ayni_hafta(self):
        plan = plan_belge(date(2026, 11, 13), Decimal("9000"))
        self.assertEqual(plan["taksitler"][0]["vade_tarihi"], date(2026, 11, 13))
        self.assertEqual(plan["taksit_adet"], TAKSIT_ADET)

    def test_cuma_10000_sekiz_ve_on_taksit(self):
        p8 = plan_belge(date(2026, 11, 13), Decimal("10000"), taksit_adet=8)
        p10 = plan_belge(date(2026, 11, 13), Decimal("10000"), taksit_adet=10)
        self.assertEqual(p8["taksitler"][0]["planlanan_tutar"], Decimal("1250.00"))
        self.assertEqual(p10["taksitler"][0]["planlanan_tutar"], Decimal("1000.00"))
        self.assertEqual(sum(n_taksit_tutarlari(Decimal("10000"), 8), Decimal("0")), Decimal("10000.00"))
        self.assertEqual(sum(n_taksit_tutarlari(Decimal("10000"), 10), Decimal("0")), Decimal("10000.00"))

    def test_taksit_adet_dogrula(self):
        self.assertEqual(taksit_adet_dogrula("9"), 9)
        with self.assertRaises(ValueError):
            taksit_adet_dogrula("0")
        with self.assertRaises(ValueError):
            taksit_adet_dogrula("abc")
        with self.assertRaises(ValueError):
            taksit_adet_dogrula("-1")


class FdsKulpSenaryoTest(unittest.TestCase):
    """Excel CariHareket_T00134 beklenenleri (13.11.2026)."""

    BELGELER = [
        ("EVB-AK-1875-DEVIREN", date(2026, 8, 31), "61675.40", "CI"),
        ("1486", date(2026, 9, 10), "6859", "SH"),
        ("1523", date(2026, 9, 10), "6117", "SH"),
        ("EVB-AF-12953", date(2026, 9, 14), "4337.5", "SH"),
        ("EVB-AF-13303", date(2026, 9, 23), "1323", "SH"),
        ("EVB-AF-13304", date(2026, 9, 23), "2208", "SH"),
        ("EVB-AF-13305", date(2026, 9, 23), "3315.5", "SH"),
        ("EVB-AF-13563", date(2026, 9, 30), "13628", "SH"),
        ("EVB-AF-14145", date(2026, 10, 12), "12823.5", "SH"),
        ("EVB-AF-14593", date(2026, 10, 19), "9185", "SH"),
        ("EVB-AF-15177", date(2026, 11, 4), "31219", "SH"),
    ]
    ODEMELER = [
        (date(2026, 9, 4), "8000"),
        (date(2026, 9, 14), "7000"),
        (date(2026, 9, 25), "10000"),
        (date(2026, 10, 3), "8000"),
        (date(2026, 10, 13), "10000"),
        (date(2026, 10, 23), "15000"),
        (date(2026, 11, 3), "10000"),
    ]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "haftalik.db"
        eng = create_engine(f"sqlite:///{self.db_path}", future=True)
        event.listen(eng, "connect", _sqlite_pragma)
        self.engine = eng

        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_masraf  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.cari  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.haftalik_odeme  # noqa: F401
        import database.models.kart_turu  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.stok  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        self.Session = Session
        with Session() as s:
            firma = Firma(firma_kodu="HAF", unvan="Haftalik Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="2026",
                    baslangic_tarihi=date(2026, 1, 1),
                    bitis_tarihi=date(2026, 12, 31),
                    aktif=True,
                    kapali=False,
                    varsayilan=True,
                )
            )
            cari = Cari(
                cari_kodu="T00134",
                unvan="FDS KULP",
                cari_turu="Tedarikçi",
                aktif=True,
            )
            s.add(cari)
            s.flush()
            self.cari_id = int(cari.id)
            oid = 1
            for belge, tarih, tutar, tur in self.BELGELER:
                if tur == "CI":
                    s.add(
                        CariIslem(
                            cari_id=self.cari_id,
                            tarih=tarih,
                            islem_turu="Açılış",
                            belge_no=belge,
                            aciklama="Evo Devreden",
                            borc=Decimal("0"),
                            alacak=Decimal(tutar),
                        )
                    )
                else:
                    s.add(
                        SatisHareketi(
                            cari_id=self.cari_id,
                            satis_tarihi=tarih,
                            belge_no=belge,
                            satis_tutari=-Decimal(tutar),
                            kalan_acik_tutar=-Decimal(tutar),
                        )
                    )
            for tarih, tutar in self.ODEMELER:
                oid += 1
                s.add(
                    CariIslem(
                        cari_id=self.cari_id,
                        tarih=tarih,
                        islem_turu="Ödeme",
                        belge_no=f"ODM-{oid}",
                        aciklama="Havale",
                        borc=Decimal(tutar),
                        alacak=Decimal("0"),
                    )
                )
            s.commit()

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = self.db_path

        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Admin",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="HAF",
            firma_unvan="Haftalik",
            firma_uid="haf",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)

        HaftalikOdemeService._hazir_motor = None
        HaftalikOdemeService.schema_hazirla(eng)

    def tearDown(self):
        oturum.clear()
        HaftalikOdemeService._hazir_motor = None
        try:
            self.engine.dispose()
        finally:
            self.tmp.cleanup()

    def test_hafta_09_15_beklenenler(self):
        with self.Session() as s:
            HaftalikOdemeService.planlari_yeniden_kur(s, self.cari_id)
            s.commit()

        rapor = HaftalikOdemeService.haftalik_rapor(
            self.cari_id, referans=date(2026, 11, 13), otomatik_plan=False
        )
        self.assertEqual(rapor["onceki_haftalardan_kalan"], Decimal("37147.06"))
        self.assertEqual(rapor["bu_hafta_acik_taksitler"], Decimal("8671.09"))
        self.assertEqual(rapor["bu_hafta_acik_adet"], 8)
        self.assertEqual(rapor["toplam_odenecek"], Decimal("45818.15"))
        self.assertEqual(rapor["gelecek_haftalara_kalan"], Decimal("38872.75"))
        self.assertEqual(rapor["cari_acik_bakiye"], Decimal("84690.90"))

    def test_hafta_02_08_beklenenler(self):
        with self.Session() as s:
            HaftalikOdemeService.planlari_yeniden_kur(s, self.cari_id)
            s.commit()

        rapor = HaftalikOdemeService.haftalik_rapor(
            self.cari_id, referans=date(2026, 11, 8), otomatik_plan=False
        )
        self.assertEqual(rapor["vadesi_gelen"], Decimal("10112.81"))
        self.assertEqual(rapor["hafta_odeme_toplam"], Decimal("10000.00"))
        self.assertEqual(rapor["hafta_sonu_kalan"], Decimal("37147.06"))

    def test_yenile_mukerrer_yok(self):
        with self.Session() as s:
            HaftalikOdemeService.planlari_yeniden_kur(s, self.cari_id)
            s.commit()
            HaftalikOdemeService.planlari_yeniden_kur(s, self.cari_id)
            s.commit()
            adet = s.scalars(
                select(CariHaftalikOdemeTaksit).where(
                    CariHaftalikOdemeTaksit.cari_id == self.cari_id
                )
            ).all()
        self.assertEqual(len(adet), 11 * 9)

    def test_taksit_sayisi_degistir_geri_9(self):
        """8'e geçip tekrar 9'a dönünce FDS tutarları aynı; mükerrer yok."""
        with self.Session() as s:
            HaftalikOdemeService.planlari_yeniden_kur(s, self.cari_id, taksit_adet=9)
            s.commit()
        r9a = HaftalikOdemeService.haftalik_rapor(
            self.cari_id, referans=date(2026, 11, 13), otomatik_plan=False, taksit_adet=9
        )
        r8 = HaftalikOdemeService.haftalik_rapor(
            self.cari_id, referans=date(2026, 11, 13), otomatik_plan=False, taksit_adet=8
        )
        self.assertNotEqual(r8["toplam_odenecek"], r9a["toplam_odenecek"])
        r9b = HaftalikOdemeService.haftalik_rapor(
            self.cari_id, referans=date(2026, 11, 13), otomatik_plan=False, taksit_adet=9
        )
        self.assertEqual(r9b["onceki_haftalardan_kalan"], Decimal("37147.06"))
        self.assertEqual(r9b["bu_hafta_acik_taksitler"], Decimal("8671.09"))
        self.assertEqual(r9b["toplam_odenecek"], Decimal("45818.15"))
        with self.Session() as s:
            adet = len(
                s.scalars(
                    select(CariHaftalikOdemeTaksit).where(
                        CariHaftalikOdemeTaksit.cari_id == self.cari_id
                    )
                ).all()
            )
        self.assertEqual(adet, 11 * 9)

    def test_kismi_odeme_kalani_azaltir(self):
        taksitler = [
            {
                "kaynak_id": 1,
                "taksit_no": 1,
                "vade_tarihi": date(2026, 11, 6),
                "fatura_tarihi": date(2026, 11, 4),
                "planlanan_tutar": Decimal("1000.00"),
                "odenen_tutar": Decimal("0"),
                "kalan": Decimal("1000.00"),
            }
        ]
        odemeleri_fifo_mahsup(
            taksitler,
            [{"id": 1, "tarih": date(2026, 11, 6), "tutar": Decimal("400"), "belge_no": "X"}],
        )
        self.assertEqual(taksitler[0]["kalan"], Decimal("600.00"))


class AcilisBorcMahsupTest(unittest.TestCase):
    """T00073 tipi: DEVIREN alacak + açılış BORÇ ödemeleri plana mahsup edilir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "haftalik_acilis.db"
        eng = create_engine(f"sqlite:///{self.db_path}", future=True)
        event.listen(eng, "connect", _sqlite_pragma)
        self.engine = eng

        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_masraf  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.cari  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.haftalik_odeme  # noqa: F401
        import database.models.kart_turu  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.stok  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        self.Session = Session
        with Session() as s:
            firma = Firma(firma_kodu="ACM", unvan="Acilis Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="2026",
                    baslangic_tarihi=date(2026, 1, 1),
                    bitis_tarihi=date(2026, 12, 31),
                    aktif=True,
                    kapali=False,
                    varsayilan=True,
                )
            )
            cari = Cari(
                cari_kodu="T00073X",
                unvan="SEVAL TEST",
                cari_turu="Tedarikçi",
                aktif=True,
            )
            s.add(cari)
            s.flush()
            self.cari_id = int(cari.id)
            # Brüt açılış alacağı
            s.add(
                CariIslem(
                    cari_id=self.cari_id,
                    tarih=date(2026, 8, 31),
                    islem_turu="AÇILIŞ",
                    belge_no="EVB-AK-1944-DEVIREN",
                    borc=Decimal("0"),
                    alacak=Decimal("50751.86"),
                )
            )
            # Dönem öncesi ödemeler (açılış BORÇ) — cari bakiyeyi düşürür
            for belge, tarih, tutar in (
                ("EVB-AK-1944-58112", date(2026, 6, 16), "3040.07"),
                ("EVB-AK-1944-57807", date(2026, 6, 23), "3000.00"),
                ("EVB-AK-1944-54405", date(2026, 8, 4), "32000.00"),
            ):
                s.add(
                    CariIslem(
                        cari_id=self.cari_id,
                        tarih=tarih,
                        islem_turu="Açılış",
                        belge_no=belge,
                        borc=Decimal(tutar),
                        alacak=Decimal("0"),
                    )
                )
            # Dönem içi alış + OMK
            s.add(
                SatisHareketi(
                    cari_id=self.cari_id,
                    satis_tarihi=date(2026, 9, 25),
                    belge_no="EVB-AF-1",
                    satis_tutari=Decimal("-9000"),
                    kalan_acik_tutar=Decimal("-9000"),
                )
            )
            s.add(
                CariIslem(
                    cari_id=self.cari_id,
                    tarih=date(2026, 9, 1),
                    islem_turu="Ödeme",
                    belge_no="OMK-2026-0001",
                    borc=Decimal("4000"),
                    alacak=Decimal("0"),
                )
            )
            s.commit()

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = self.db_path
        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Admin",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="ACM",
            firma_unvan="Acilis",
            firma_uid="acm",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)
        HaftalikOdemeService._hazir_motor = None
        HaftalikOdemeService.schema_hazirla(eng)

    def tearDown(self):
        oturum.clear()
        HaftalikOdemeService._hazir_motor = None
        try:
            self.engine.dispose()
        finally:
            self.tmp.cleanup()

    def test_acilis_borc_odeme_olarak_mahsup(self):
        with self.Session() as s:
            od = HaftalikOdemeService._tedarikci_odemeler(s, self.cari_id)
            belgeler = HaftalikOdemeService._tedarikci_belgeler(s, self.cari_id)
        od_nos = {o["belge_no"] for o in od}
        self.assertIn("EVB-AK-1944-58112", od_nos)
        self.assertIn("OMK-2026-0001", od_nos)
        self.assertNotIn("EVB-AK-1944-DEVIREN", od_nos)
        top_od = sum((o["tutar"] for o in od), Decimal("0"))
        self.assertEqual(top_od, Decimal("42040.07"))  # 38040.07 + 4000
        top_belge = sum((b["tutar"] for b in belgeler), Decimal("0"))
        self.assertEqual(top_belge, Decimal("59751.86"))  # 50751.86 + 9000
        with self.Session() as s:
            HaftalikOdemeService.planlari_yeniden_kur(s, self.cari_id, taksit_adet=9)
            s.commit()
        rapor = HaftalikOdemeService.haftalik_rapor(
            self.cari_id, referans=date(2026, 11, 17), otomatik_plan=False, taksit_adet=9
        )
        # Plan açık = belge − ödeme = 59751.86 − 42040.07 = 17711.79
        self.assertEqual(rapor["cari_acik_bakiye"], Decimal("17711.79"))
        from database.cari_bakiye_service import net_bakiye

        nb = net_bakiye(self.cari_id)
        self.assertEqual(abs(Decimal(str(nb["bakiye"]))), Decimal("17711.79"))
        self.assertEqual(abs(Decimal(str(rapor.get("plan_cari_fark") or 0))), Decimal("0.00"))

    def test_mukerrer_omk_satirlari_toplami(self):
        """Aynı OMK belge_no ile iki Ödeme satırı cari gibi toplanır (T00008 tipi)."""
        with self.Session() as s:
            s.add(
                CariIslem(
                    cari_id=self.cari_id,
                    tarih=date(2026, 11, 13),
                    islem_turu="Ödeme",
                    belge_no="OMK-DUP-1",
                    borc=Decimal("5000"),
                    alacak=Decimal("0"),
                )
            )
            s.add(
                CariIslem(
                    cari_id=self.cari_id,
                    tarih=date(2026, 11, 13),
                    islem_turu="Ödeme",
                    belge_no="OMK-DUP-1",
                    borc=Decimal("5000"),
                    alacak=Decimal("0"),
                )
            )
            s.commit()
            od = HaftalikOdemeService._tedarikci_odemeler(s, self.cari_id)
        dup = [o for o in od if o["belge_no"] == "OMK-DUP-1"]
        self.assertEqual(len(dup), 2)
        self.assertEqual(sum((o["tutar"] for o in dup), Decimal("0")), Decimal("10000.00"))


class HaftalikOdemeYapTest(unittest.TestCase):
    """Ödeme Yap: nakit / havale / kart + kısmi mahsup + idempotent."""

    def setUp(self):
        from unittest.mock import patch

        from database.models.finans import (
            BankaKarti,
            FinansHesabi,
            KrediKartiTanimi,
        )
        from database.models.sube import Sube

        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "haftalik_odeme_yap.db"
        eng = create_engine(f"sqlite:///{self.db_path}", future=True)
        event.listen(eng, "connect", _sqlite_pragma)
        self.engine = eng

        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_masraf  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.cari  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.haftalik_odeme  # noqa: F401
        import database.models.kart_turu  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.sube  # noqa: F401

        Base.metadata.create_all(eng)
        from database.database import kasa_makbuz_schemasini_guncelle

        kasa_makbuz_schemasini_guncelle(eng)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        self.Session = Session
        with Session() as s:
            firma = Firma(firma_kodu="HOY", unvan="Haftalik Odeme Yap", aktif=True)
            s.add(firma)
            s.flush()
            s.add(Sube(firma_id=firma.id, sube_kodu="MERKEZ", sube_adi="Merkez", merkez=True, aktif=True))
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="2026",
                    baslangic_tarihi=date(2026, 1, 1),
                    bitis_tarihi=date(2026, 12, 31),
                    aktif=True,
                    kapali=False,
                    varsayilan=True,
                )
            )
            cari = Cari(
                cari_kodu="T-HOY",
                unvan="Haftalik Tedarikçi",
                cari_turu="Tedarikçi",
                aktif=True,
            )
            s.add(cari)
            s.flush()
            self.cari_id = int(cari.id)
            # Tek fatura: 9.000 → 9×1.000 Cuma taksiti (13.11.2026 Cuma)
            s.add(
                SatisHareketi(
                    cari_id=self.cari_id,
                    satis_tarihi=date(2026, 11, 13),
                    belge_no="AF-9000",
                    satis_tutari=Decimal("-9000"),
                    kalan_acik_tutar=Decimal("-9000"),
                )
            )
            kasa = FinansHesabi(
                hesap_adi="HOY KASA", hesap_turu="KASA", acilis_bakiyesi=Decimal("100000")
            )
            s.add(kasa)
            banka = BankaKarti(banka_adi="HOY BANK")
            s.add(banka)
            s.flush()
            mev = FinansHesabi(
                hesap_adi="HOY MEVDUAT",
                hesap_turu="BANKA",
                alt_hesap_turu="MEVDUAT",
                banka_karti_id=banka.id,
                acilis_bakiyesi=Decimal("100000"),
            )
            kk_h = FinansHesabi(
                hesap_adi="HOY KK",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDI_KARTI",
                banka_karti_id=banka.id,
            )
            s.add_all([mev, kk_h])
            s.flush()
            kk = KrediKartiTanimi(
                banka_karti_id=banka.id,
                kart_adi="HOY KART",
                kart_limiti=Decimal("50000"),
                bagli_hesap_id=kk_h.id,
                aktif=True,
            )
            s.add(kk)
            s.commit()
            self.kasa_id = int(kasa.id)
            self.mev_id = int(mev.id)
            self.kk_id = int(kk.id)
            self.kk_hesap_id = int(kk_h.id)

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = self.db_path
        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Admin",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="HOY",
            firma_unvan="Haftalik",
            firma_uid="hoy",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)
        HaftalikOdemeService._hazir_motor = None
        HaftalikOdemeService.schema_hazirla(eng)
        self._audit = patch("database.user_audit.audit_document", return_value=None)
        self._audit.start()

    def tearDown(self):
        self._audit.stop()
        oturum.clear()
        HaftalikOdemeService._hazir_motor = None
        try:
            self.engine.dispose()
        finally:
            self.tmp.cleanup()

    def test_onizleme_en_eski_vadeye(self):
        with self.Session() as s:
            HaftalikOdemeService.planlari_yeniden_kur(s, self.cari_id, taksit_adet=9)
            s.commit()
        on = HaftalikOdemeService.odeme_dagitim_onizle(
            self.cari_id,
            Decimal("4000"),
            date(2026, 11, 13),
            taksit_adet=9,
            referans=date(2026, 11, 13),
        )
        self.assertEqual(on["odeme_tutari"], Decimal("4000.00"))
        self.assertEqual(on["avans"], Decimal("0.00"))
        self.assertGreaterEqual(len(on["dagitim"]), 4)
        self.assertEqual(on["dagitim"][0]["vade_tarihi"], date(2026, 11, 13))
        self.assertEqual(on["dagitim"][0]["mahsup"], Decimal("1000.00"))
        self.assertEqual(sum((d["mahsup"] for d in on["dagitim"]), Decimal("0")), Decimal("4000.00"))

    def test_nakit_kismi_odeme_yenile(self):
        with self.Session() as s:
            HaftalikOdemeService.planlari_yeniden_kur(s, self.cari_id, taksit_adet=9)
            s.commit()
        once = HaftalikOdemeService.haftalik_rapor(
            self.cari_id, referans=date(2026, 11, 13), otomatik_plan=False, taksit_adet=9
        )
        self.assertEqual(once["toplam_odenecek"], Decimal("1000.00"))  # yalnız 1. Cuma bu hafta
        sonuc = HaftalikOdemeService.odeme_yap(
            cari_id=self.cari_id,
            tutar=Decimal("400"),
            odeme_tarihi=date(2026, 11, 13),
            yontem="NAKIT",
            finans_hesap_id=self.kasa_id,
            istek_anahtari="hoy-nakit-400",
            taksit_adet=9,
            referans=date(2026, 11, 13),
        )
        self.assertTrue(str(sonuc["belge_no"]).startswith("OMK-"))
        rapor = sonuc["rapor"]
        self.assertEqual(rapor["toplam_odenecek"], Decimal("600.00"))
        self.assertEqual(rapor["hafta_odeme_toplam"], Decimal("400.00"))
        from database.models.finans import FinansHareketi, KasaMakbuzu

        with get_session() as s:
            m = s.get(KasaMakbuzu, sonuc["makbuz_id"])
            self.assertEqual(m.istek_anahtari, "hoy-nakit-400")
            fh = list(s.scalars(select(FinansHareketi).where(FinansHareketi.belge_no == m.belge_no)))
            self.assertEqual(len(fh), 1)
            self.assertEqual(int(fh[0].hesap_id), self.kasa_id)
            ci = s.scalar(select(CariIslem).where(CariIslem.belge_no == m.belge_no))
            self.assertEqual(ci.borc, Decimal("400.00"))

    def test_havale_ve_idempotent(self):
        with self.Session() as s:
            HaftalikOdemeService.planlari_yeniden_kur(s, self.cari_id, taksit_adet=9)
            s.commit()
        a = HaftalikOdemeService.odeme_yap(
            cari_id=self.cari_id,
            tutar=Decimal("1000"),
            odeme_tarihi=date(2026, 11, 13),
            yontem="HAVALE",
            finans_hesap_id=self.mev_id,
            istek_anahtari="hoy-havale-1",
            taksit_adet=9,
            referans=date(2026, 11, 13),
        )
        b = HaftalikOdemeService.odeme_yap(
            cari_id=self.cari_id,
            tutar=Decimal("1000"),
            odeme_tarihi=date(2026, 11, 13),
            yontem="HAVALE",
            finans_hesap_id=self.mev_id,
            istek_anahtari="hoy-havale-1",
            taksit_adet=9,
            referans=date(2026, 11, 13),
        )
        self.assertEqual(a["makbuz_id"], b["makbuz_id"])
        self.assertEqual(a["belge_no"], b["belge_no"])
        from database.models.finans import KasaMakbuzu

        with get_session() as s:
            adet = s.scalars(
                select(KasaMakbuzu).where(KasaMakbuzu.istek_anahtari == "hoy-havale-1")
            ).all()
            self.assertEqual(len(adet), 1)

    def test_kart_taksitli_tek_cari_mahsup(self):
        from database.models.finans import FinansHareketi, KrediKartiOdeme

        with self.Session() as s:
            HaftalikOdemeService.planlari_yeniden_kur(s, self.cari_id, taksit_adet=9)
            s.commit()
        sonuc = HaftalikOdemeService.odeme_yap(
            cari_id=self.cari_id,
            tutar=Decimal("3000"),
            odeme_tarihi=date(2026, 11, 13),
            yontem="KART",
            kredi_karti_id=self.kk_id,
            taksit_sayisi=3,
            istek_anahtari="hoy-kart-3",
            taksit_adet=9,
            referans=date(2026, 11, 13),
        )
        with get_session() as s:
            ci = list(s.scalars(select(CariIslem).where(CariIslem.belge_no == sonuc["belge_no"])))
            self.assertEqual(len(ci), 1)
            self.assertEqual(ci[0].borc, Decimal("3000.00"))
            fh = list(
                s.scalars(select(FinansHareketi).where(FinansHareketi.belge_no == sonuc["belge_no"]))
            )
            self.assertEqual(len(fh), 1)
            self.assertEqual(int(fh[0].hesap_id), self.kk_hesap_id)
            ko = s.scalar(
                select(KrediKartiOdeme).where(KrediKartiOdeme.belge_no.like(f"{sonuc['belge_no']}%"))
            )
            self.assertIsNotNone(ko)
            self.assertEqual(int(ko.taksit_sayisi), 3)
            self.assertEqual(len(ko.taksitler), 3)
        # 3000 → ilk 3 Cuma taksiti kapanır; bu hafta kalan 0
        self.assertEqual(sonuc["rapor"]["bu_hafta_acik_taksitler"], Decimal("0.00"))

    def test_fazla_odeme_avans_onizleme(self):
        with self.Session() as s:
            HaftalikOdemeService.planlari_yeniden_kur(s, self.cari_id, taksit_adet=9)
            s.commit()
        on = HaftalikOdemeService.odeme_dagitim_onizle(
            self.cari_id,
            Decimal("10000"),
            date(2026, 11, 13),
            taksit_adet=9,
            referans=date(2026, 11, 13),
        )
        self.assertEqual(on["mahsup_toplam"], Decimal("9000.00"))
        self.assertEqual(on["avans"], Decimal("1000.00"))


if __name__ == "__main__":
    unittest.main()
