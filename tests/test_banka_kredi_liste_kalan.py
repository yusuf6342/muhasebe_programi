"""Bankalar «Krediler» kolonu = −(Ana Kart kalan anapara toplamı); ortak kaynak."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.database import (
    Base,
    _aktif_engine_bagla,
    company_db,
    finans_hesap_schemasini_guncelle,
    get_session,
)
from database.finans_service import FinansService
from database.models.donem import Donem
from database.models.finans import (
    BankaKarti,
    BankaKredisi,
    BankaKrediTaksit,
    FinansHareketi,
    FinansHesabi,
)
from database.models.firma import Firma
from database.models.sube import Sube
from database.session_manager import oturum

D = Decimal


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class BankaKrediListeKalanTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "kredi_liste.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        import database.models as modeller

        for bilgi in pkgutil.iter_modules(modeller.__path__):
            importlib.import_module(f"database.models.{bilgi.name}")
        Base.metadata.create_all(eng)
        finans_hesap_schemasini_guncelle(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="BKRL", unvan="Banka Kredi Liste", aktif=True)
            s.add(firma)
            s.flush()
            s.add(
                Sube(
                    firma_id=firma.id,
                    sube_kodu="MERKEZ",
                    sube_adi="Merkez",
                    merkez=True,
                    aktif=True,
                )
            )
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="2026",
                    baslangic_tarihi=date(2000, 1, 1),
                    bitis_tarihi=date(2099, 12, 31),
                    aktif=True,
                    kapali=False,
                    varsayilan=True,
                )
            )
            halk = BankaKarti(banka_adi="Halkbank Test", aktif=True)
            diger = BankaKarti(banka_adi="Akbank Test", aktif=True)
            s.add_all([halk, diger])
            s.flush()
            # Ledger artığı (yanlış eski Krediler kolonu kaynağı)
            h_kredi = FinansHesabi(
                hesap_adi="Halkbank — Krediler Hesabı",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDILER",
                banka_karti_id=halk.id,
                aktif=True,
                acilis_bakiyesi=D("-18466.66"),
            )
            a_kredi = FinansHesabi(
                hesap_adi="Akbank — Krediler Hesabı",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDILER",
                banka_karti_id=diger.id,
                aktif=True,
                acilis_bakiyesi=D("0"),
            )
            s.add_all([h_kredi, a_kredi])
            s.flush()
            k1 = BankaKredisi(
                belge_no="EVB-KR-T147",
                banka_karti_id=halk.id,
                kredi_adi="1 Nolu Esnaf",
                kredi_turu="ESNAF",
                ana_para=D("210000.00"),
                toplam_faiz=D("0"),
                toplam_masraf=D("0"),
                taksit_sayisi=2,
                kullandirim_tarihi=date(2026, 1, 1),
                ilk_taksit_tarihi=date(2026, 2, 1),
                odeme_hesap_turu="MEVDUAT",
                durum="KULLANDIRILDI",
                bagli_hesap_id=h_kredi.id,
                aktif=True,
            )
            k2 = BankaKredisi(
                belge_no="EVB-KR-T142",
                banka_karti_id=halk.id,
                kredi_adi="2 Nolu Esnaf",
                kredi_turu="ESNAF",
                ana_para=D("83733.28"),
                toplam_faiz=D("0"),
                toplam_masraf=D("0"),
                taksit_sayisi=1,
                kullandirim_tarihi=date(2026, 1, 1),
                ilk_taksit_tarihi=date(2026, 2, 1),
                odeme_hesap_turu="MEVDUAT",
                durum="KULLANDIRILDI",
                bagli_hesap_id=h_kredi.id,
                aktif=True,
            )
            s.add_all([k1, k2])
            s.flush()
            s.add_all(
                [
                    BankaKrediTaksit(
                        kredi_id=k1.id,
                        taksit_no=1,
                        vade_tarihi=date(2026, 2, 1),
                        anapara=D("100000.00"),
                        faiz=D("5000"),
                        masraf=D("0"),
                        durum="BEKLIYOR",
                    ),
                    BankaKrediTaksit(
                        kredi_id=k1.id,
                        taksit_no=2,
                        vade_tarihi=date(2026, 3, 1),
                        anapara=D("110000.00"),
                        faiz=D("4000"),
                        masraf=D("0"),
                        durum="BEKLIYOR",
                    ),
                    BankaKrediTaksit(
                        kredi_id=k2.id,
                        taksit_no=1,
                        vade_tarihi=date(2026, 2, 1),
                        anapara=D("83733.28"),
                        faiz=D("1000"),
                        masraf=D("0"),
                        durum="BEKLIYOR",
                    ),
                ]
            )
            s.commit()
            self.halk_id = int(halk.id)
            self.diger_id = int(diger.id)
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = self.db_path
        self.engine = eng
        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="t",
            ad_soyad="Test",
            role_kod="YONETICI",
            role_ad="Y",
            permissions={"finans_duzenleme"},
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="BKRL",
            firma_unvan="Banka Kredi Liste",
            firma_uid="bkrl",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            oturum.set_period(d.id, d.donem_adi)
        self._audit = patch("database.user_audit.audit_document", return_value=None)
        self._audit.start()

    def tearDown(self):
        self._audit.stop()
        try:
            self.engine.dispose()
        finally:
            self._tmpdir.cleanup()

    def test_liste_krediler_plan_kalan_negatif_ana_kart_pozitif(self):
        """Ledger −18466,66 değil; plan 210000+83733,28 → liste −293733,28 / kart +."""
        kalan_h, olan = FinansService.banka_kredi_kalan_anapara_haritasi()
        self.assertIn(self.halk_id, olan)
        self.assertEqual(kalan_h[self.halk_id], D("293733.28"))

        paket = FinansService.bankalar_liste_satirlari(aktif_only=False)
        halk = next(s for s in paket["satirlar"] if s["id"] == self.halk_id)
        self.assertEqual(halk["KREDILER"], D("-293733.28"))

        # Faiz plan toplamına karışmamış
        det1 = FinansService.banka_kredi_getir(
            next(
                k.id
                for k in FinansService.banka_kredileri(banka_karti_id=self.halk_id)
                if k.belge_no == "EVB-KR-T147"
            )
        )
        self.assertEqual(det1["kalan_anapara"], D("210000.00"))

        with get_session() as s:
            kart = s.get(BankaKarti, self.halk_id)
            varlik = FinansService.banka_bakiyeler_varlik(kart)["KREDILER"]
        self.assertEqual(varlik, D("-293733.28"))

        # Kredi kaydı olmayan banka: ledger 0
        diger = next(s for s in paket["satirlar"] if s["id"] == self.diger_id)
        self.assertEqual(diger["KREDILER"], D("0.00"))

    def test_isaret_cift_cevirme_yok(self):
        g = FinansService.banka_kredi_borc_gosterim(self.halk_id)
        self.assertEqual(g, D("-293733.28"))
        # Kaynak haritadaki pozitif değer yeniden çevrilmez
        kalan_h, olan = FinansService.banka_kredi_kalan_anapara_haritasi()
        g2 = FinansService.banka_kredi_borc_gosterim(
            self.halk_id, kalan_harita=kalan_h, kredi_olan=olan
        )
        self.assertEqual(g2, D("-293733.28"))


if __name__ == "__main__":
    unittest.main()
