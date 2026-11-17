"""KK alt hesap ↔ kart tanımı eşlemesi; işlem ekranı bakiyesi ana kartla aynı."""

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
from database.models.finans import BankaKarti, FinansHareketi, FinansHesabi, KrediKartiTanimi
from database.models.firma import Firma
from database.models.sube import Sube
from database.session_manager import oturum


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class KkEslemeGorunumTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "kk_esleme.db"
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
            firma = Firma(firma_kodu="KKES", unvan="KK Esleme", aktif=True)
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
            ana = BankaKarti(banka_adi="Akbank", aktif=True)
            kabuk = BankaKarti(banka_adi="02 AKBANK AXESS", aktif=False)
            s.add_all([ana, kabuk])
            s.flush()
            yer = FinansHesabi(
                hesap_adi="Akbank — Kredi Kartı Hesabı",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDI_KARTI",
                banka_karti_id=ana.id,
                aktif=False,
                acilis_bakiyesi=Decimal("0"),
            )
            gercek = FinansHesabi(
                hesap_adi="Akbank Axess Şahsi Kredi Kartı",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDI_KARTI",
                banka_karti_id=ana.id,
                aktif=True,
                acilis_bakiyesi=Decimal("-1500.00"),
            )
            s.add_all([yer, gercek])
            s.flush()
            s.add(
                FinansHareketi(
                    hesap_id=gercek.id,
                    tarih=date(2026, 1, 15),
                    hareket_turu="AÇILIŞ",
                    belge_no="EVB-KK-1",
                    tutar=Decimal("0.00"),
                    aciklama="Devir satırı (görünürlük)",
                )
            )
            s.add(
                KrediKartiTanimi(
                    banka_karti_id=kabuk.id,
                    kart_adi="02  AKBANK AXESS ŞAHSİ KREDİ KARTI",
                    kart_limiti=Decimal("0"),
                    aktif=True,
                    son_dort_hane="9999",
                )
            )
            s.commit()
            self.ana_id = int(ana.id)
            self.gercek_id = int(gercek.id)
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
            firma_kodu="KKES",
            firma_unvan="KK Esleme",
            firma_uid="kkes",
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

    def test_esleme_ve_ekran_bakiyesi(self):
        with get_session() as s:
            kart = s.get(BankaKarti, self.ana_id)
            ham = FinansService.banka_bakiyeler(kart)["KREDI_KARTI"]
            self.assertEqual(ham, Decimal("-1500.00"))
            alt0 = FinansService.banka_alt_hesap(kart, "KREDI_KARTI")
            self.assertEqual(int(alt0.id), self.gercek_id)

        rapor = FinansService.kredi_kartlari_eslestir(yaz=True)
        self.assertEqual(len(rapor["eslesen"]), 1)
        self.assertEqual(rapor["eslesen"][0]["hesap_id"], self.gercek_id)

        with get_session() as s:
            kart = s.get(BankaKarti, self.ana_id)
            varlik = FinansService.banka_bakiyeler_varlik(kart)["KREDI_KARTI"]
            # Evo/devir: ham borç − → işletme de − (körleme çeviri yok)
            self.assertEqual(varlik, Decimal("-1500.00"))

        kartlar = FinansService.kredi_kartlari(banka_karti_id=self.ana_id, aktif_only=False)
        self.assertEqual(len(kartlar), 1)
        self.assertEqual(int(kartlar[0].bagli_hesap_id), self.gercek_id)
        self.assertEqual(int(kartlar[0].banka_karti_id), self.ana_id)

        har = FinansService.kredi_karti_hesap_hareketleri(self.ana_id)
        self.assertGreaterEqual(len(har), 1)
        self.assertFalse(har[0]["esleme_bekliyor"])

        rapor2 = FinansService.kredi_kartlari_eslestir(yaz=True)
        self.assertEqual(rapor2["olusturulan"], [])
        self.assertEqual(
            len(FinansService.kredi_kartlari(banka_karti_id=self.ana_id, aktif_only=False)),
            1,
        )
        with get_session() as s:
            self.assertEqual(
                FinansService.bakiye(s.get(FinansHesabi, self.gercek_id)),
                Decimal("-1500.00"),
            )

    def test_kart_id_filtre_baska_karta_dusmez(self):
        """İki kart / iki hesap: seçilen kart yalnız kendi hareketini görür."""
        with get_session() as s:
            ana = s.get(BankaKarti, self.ana_id)
            business = FinansHesabi(
                hesap_adi="Akbank Business",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDI_KARTI",
                banka_karti_id=ana.id,
                aktif=True,
                acilis_bakiyesi=Decimal("-900.00"),
            )
            s.add(business)
            s.flush()
            s.add(
                FinansHareketi(
                    hesap_id=business.id,
                    tarih=date(2026, 2, 1),
                    hareket_turu="BANKA ÇIKIŞ",
                    belge_no="EVB-KK-BIZ",
                    tutar=Decimal("100.00"),
                    aciklama="Business hareket",
                )
            )
            s.add(
                KrediKartiTanimi(
                    banka_karti_id=ana.id,
                    kart_adi="Akbank Business",
                    kart_limiti=Decimal("0"),
                    aktif=True,
                    son_dort_hane="1111",
                    bagli_hesap_id=business.id,
                )
            )
            s.commit()
            business_id = int(business.id)

        FinansService.kredi_kartlari_eslestir(yaz=True)
        kartlar = FinansService.kredi_kartlari(banka_karti_id=self.ana_id, aktif_only=False)
        self.assertEqual(len(kartlar), 2)
        axess = next(k for k in kartlar if int(k.bagli_hesap_id) == self.gercek_id)
        biz = next(k for k in kartlar if int(k.bagli_hesap_id) == business_id)

        ax_har = FinansService.kredi_karti_hesap_hareketleri(
            self.ana_id, kredi_karti_id=int(axess.id)
        )
        self.assertTrue(ax_har)
        self.assertTrue(all(int(h["hesap_id"]) == self.gercek_id for h in ax_har))
        self.assertTrue(all(int(h["kredi_karti_id"]) == int(axess.id) for h in ax_har))
        self.assertFalse(any(h.get("belge_no") == "EVB-KK-BIZ" for h in ax_har))

        biz_har = FinansService.kredi_karti_hesap_hareketleri(
            self.ana_id, kredi_karti_id=int(biz.id)
        )
        self.assertTrue(biz_har)
        self.assertTrue(all(int(h["hesap_id"]) == business_id for h in biz_har))
        self.assertTrue(any(h.get("belge_no") == "EVB-KK-BIZ" for h in biz_har))
        self.assertFalse(any(int(h["hesap_id"]) == self.gercek_id for h in biz_har))

        # Bağlı hesabı olmayan tanım → boş (başka karta düşmez)
        with get_session() as s:
            s.add(
                KrediKartiTanimi(
                    banka_karti_id=self.ana_id,
                    kart_adi="Boş kart",
                    kart_limiti=Decimal("0"),
                    aktif=True,
                    son_dort_hane="0000",
                )
            )
            s.commit()
            bos = s.scalar(
                select(KrediKartiTanimi).where(KrediKartiTanimi.kart_adi == "Boş kart")
            )
            bos_id = int(bos.id)
        self.assertEqual(
            FinansService.kredi_karti_hesap_hareketleri(
                self.ana_id, kredi_karti_id=bos_id
            ),
            [],
        )

        oz = FinansService.kredi_karti_isletme_bakiyesi(int(axess.id))
        self.assertEqual(oz["bakiye"], Decimal("-1500.00"))
        self.assertEqual(FinansService.bakiye_renk_kodu(oz["bakiye"]), "#B91C1C")


if __name__ == "__main__":
    unittest.main()
