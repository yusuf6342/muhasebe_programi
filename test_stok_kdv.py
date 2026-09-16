"""Stok kartı KDV oranı — kayıt/okuma ve güvenli şema migrasyonu.

Çalıştırma: python test_stok_kdv.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, cari_kart_schemasini_guncelle, company_db
from database.models.stok import VARSAYILAN_KDV_ORANI, StokKarti
from database.session_manager import oturum
from database.stok_service import StokService


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class StokKdvTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_stok_kdv.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        from database.models.firma import Firma
        from database.models.donem import Donem
        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.hizmet  # noqa: F401
        import database.models.hizmet_faturasi  # noqa: F401
        import database.models.kk_cekimi  # noqa: F401
        import database.models.deleted_record  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="KDV", unvan="KDV Test", aktif=True)
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
            s.commit()

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        company_db._company_id = 7
        company_db._db_path = self.db_path

        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Test Admin",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=7,
            firma_kodu="KDV",
            firma_unvan="KDV Test",
            firma_uid="kdv-uid",
            db_path=str(self.db_path),
        )

    def tearDown(self):
        try:
            company_db.close()
        except Exception:
            pass
        oturum.clear()
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def test_stok_kdv_kaydet_oku(self):
        stok = StokService.stok_kaydi(
            {
                "stok_kodu": "KDV-001",
                "stok_adi": "KDV Ürün",
                "birim": "Adet",
                "kart_turu": "Ticari Mal",
                "kdv_orani": "8",
            },
            fiyatlar=[("SATIŞ FİYATI 1", "100")],
        )
        self.assertEqual(Decimal(stok.kdv_orani), Decimal("8"))

        tekrar = StokService.stok_getir(stok.id)
        self.assertIsNotNone(tekrar)
        self.assertEqual(Decimal(tekrar.kdv_orani), Decimal("8"))

        StokService.stok_kaydi(
            {
                "stok_id": stok.id,
                "stok_kodu": "KDV-001",
                "stok_adi": "KDV Ürün",
                "birim": "Adet",
                "kdv_orani": "20",
            },
            fiyatlar=[("SATIŞ FİYATI 1", "100")],
        )
        guncel = StokService.stok_getir(stok.id)
        self.assertEqual(Decimal(guncel.kdv_orani), Decimal("20"))

    def test_varsayilan_kdv_20(self):
        stok = StokService.stok_kaydi(
            {
                "stok_kodu": "KDV-DEF",
                "stok_adi": "Varsayılan KDV",
                "birim": "Adet",
            },
            fiyatlar=[],
        )
        self.assertEqual(Decimal(stok.kdv_orani), VARSAYILAN_KDV_ORANI)

        d = StokService._hizli_satis_urun_dict(stok)
        self.assertEqual(Decimal(d["kdv_orani"]), VARSAYILAN_KDV_ORANI)

    def test_migration_alter_veri_korur(self):
        """Eski şemada kdv_orani yokken ALTER ekler; satırlar silinmez."""
        eng = company_db._engine
        with eng.begin() as conn:
            # Simüle: kolonu düşürüp eski tabloyu yeniden kur
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            conn.execute(text("ALTER TABLE stok_kartlari RENAME TO stok_kartlari_eski"))
            conn.execute(
                text(
                    """
                    CREATE TABLE stok_kartlari (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stok_kodu VARCHAR(50) NOT NULL UNIQUE,
                        stok_adi VARCHAR(200) NOT NULL,
                        barkod VARCHAR(100),
                        birim VARCHAR(20) NOT NULL DEFAULT 'Adet',
                        kart_turu VARCHAR(50) NOT NULL DEFAULT 'Ticari Mal',
                        aktif BOOLEAN NOT NULL DEFAULT 1,
                        is_deleted BOOLEAN NOT NULL DEFAULT 0
                    )
                    """
                )
            )
            conn.execute(
                text(
                    "INSERT INTO stok_kartlari (stok_kodu, stok_adi, birim) "
                    "VALUES ('ESKI-1', 'Eski Ürün', 'Adet')"
                )
            )
            conn.execute(text("DROP TABLE stok_kartlari_eski"))
            conn.execute(text("PRAGMA foreign_keys=ON"))

        sutunlar = {c["name"] for c in inspect(eng).get_columns("stok_kartlari")}
        self.assertNotIn("kdv_orani", sutunlar)

        cari_kart_schemasini_guncelle()

        sutunlar2 = {c["name"] for c in inspect(eng).get_columns("stok_kartlari")}
        self.assertIn("kdv_orani", sutunlar2)

        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT stok_kodu, stok_adi, kdv_orani FROM stok_kartlari WHERE stok_kodu='ESKI-1'")
            ).mappings().first()
        self.assertIsNotNone(row)
        self.assertEqual(row["stok_adi"], "Eski Ürün")
        self.assertEqual(Decimal(str(row["kdv_orani"])), Decimal("20"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
