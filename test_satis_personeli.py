"""Satış personeli — migration, zorunlu seçim, audit smoke testleri."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db
from database.models.cari import Cari, MusteriGrubu
from database.models.donem import Donem
from database.models.finans import FinansHesabi
from database.models.firma import Firma
from database.models.stok import Depo, StokKarti
from database.session_manager import oturum
from database.user_audit import belge_kullanici_schema_guncelle


def _sqlite_pragma(dbapi_conn, _connection_record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class SatisPersoneliTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "sp.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.doviz  # noqa: F401

        Base.metadata.create_all(eng)
        belge_kullanici_schema_guncelle(eng)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        with Session() as s:
            firma = Firma(firma_kodu="SPT", unvan="SP Test", aktif=True)
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
            s.add(FinansHesabi(hesap_adi="ANA KASA", hesap_turu="KASA", aktif=True))
            s.add(MusteriGrubu(ad="Genel"))
            s.add(Depo(ad="ANA DEPO", aktif=True))
            cari = Cari(
                cari_kodu="M3001",
                unvan="SP Müşteri",
                cari_turu="Müşteri",
                aktif=True,
            )
            s.add(cari)
            stok = StokKarti(
                stok_kodu="U3001",
                stok_adi="SP Ürün",
                birim="Adet",
                aktif=True,
                kdv_orani=Decimal("20"),
            )
            s.add(stok)
            s.commit()
            self.cari_id = int(cari.id)

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = self.db_path

        oturum.clear()
        oturum.set_user(
            user_id=42,
            kullanici_adi="testuser",
            ad_soyad="Test Kullanıcı",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions={
                "satis_duzenleme",
                "yeni_kayit",
                "satis_personeli_degistirme",
                "goruntuleme",
            },
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="SPT",
            firma_unvan="SP Test",
            firma_uid="sp-test",
            db_path=str(self.db_path),
        )
        oturum.set_period(1, "2026")

    def tearDown(self):
        oturum.clear()
        try:
            company_db.close()
        except Exception:
            pass
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def test_migration_kolonlari(self):
        eng = company_db.engine
        cols = {c["name"] for c in inspect(eng).get_columns("satis_faturalari")}
        self.assertIn("sales_person_id", cols)
        self.assertIn("sales_person_full_name", cols)

    def test_kaydet_personel_zorunlu(self):
        from database.satis_faturasi_service import SatisFaturasiService

        veriler = {
            "fatura_tarihi": date.today(),
            "vade_tarihi": date.today(),
            "cari_id": self.cari_id,
            "depo": "ANA DEPO",
            "sales_person_id": None,
        }
        satirlar = [
            {
                "urun_kodu": "U3001",
                "urun_adi": "SP Ürün",
                "miktar": 1,
                "birim": "Adet",
                "birim_fiyat": 100,
                "iskonto_orani": 0,
                "kdv_orani": 20,
            }
        ]
        with self.assertRaises(ValueError) as ctx:
            SatisFaturasiService.kaydet(veriler, satirlar)
        self.assertIn("Satış personeli", str(ctx.exception))

    @patch("database.satis_personeli.aktif_satis_personelleri")
    def test_kaydet_ve_listele(self, mock_aktif):
        mock_aktif.return_value = [
            {
                "id": 42,
                "ad_soyad": "Test Kullanıcı",
                "kullanici_kodu": "TK01",
                "etiket": "Test Kullanıcı (TK01)",
                "aktif": True,
            }
        ]
        from database.satis_faturasi_service import SatisFaturasiService

        veriler = {
            "fatura_tarihi": date.today(),
            "vade_tarihi": date.today(),
            "cari_id": self.cari_id,
            "depo": "ANA DEPO",
            "sales_person_id": 42,
            "para_birimi": "TRY",
            "kur": 1,
        }
        satirlar = [
            {
                "urun_kodu": "U3001",
                "urun_adi": "SP Ürün",
                "miktar": 2,
                "birim": "Adet",
                "birim_fiyat": 50,
                "iskonto_orani": 0,
                "kdv_orani": 20,
            }
        ]
        fatura = SatisFaturasiService.kaydet(veriler, satirlar)
        self.assertEqual(fatura.sales_person_id, 42)
        self.assertEqual(fatura.sales_person_full_name, "Test Kullanıcı")
        self.assertIsNotNone(fatura.created_by_user_id)

        ozet = SatisFaturasiService.listele_ozet()
        self.assertTrue(any(o.get("sales_person_id") == 42 for o in ozet))

        # Yeniden aç
        tekrar = SatisFaturasiService.getir(fatura.id)
        self.assertEqual(tekrar.sales_person_full_name, "Test Kullanıcı")


if __name__ == "__main__":
    unittest.main()
