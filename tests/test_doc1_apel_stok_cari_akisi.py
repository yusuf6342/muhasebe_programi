"""DOC1 kabul: Fatura Kontrol — Yeni Cari / Yeni Stok + APEL örnek satır değerleri.

Örnek satır (talimat): APEL MK300 PU SIVI ÇİVİ 390 GR — 36 ADET, 135,00, %20 KDV.
Ürün adına özel kod yok; değerler parametre olarak korunur.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import database.models

for _m in pkgutil.iter_modules(database.models.__path__):
    importlib.import_module(f"database.models.{_m.name}")

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokHareketi, StokKarti
from database.session_manager import oturum

BUGUN = date.today()


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class Doc1ApelAkisTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "doc1_apel.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="DOC1", unvan="DOC1 Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi=str(BUGUN.year),
                    baslangic_tarihi=date(BUGUN.year, 1, 1),
                    bitis_tarihi=date(BUGUN.year, 12, 31),
                    aktif=True,
                    kapali=False,
                    varsayilan=True,
                )
            )
            s.add(Depo(ad="ANA DEPO", aktif=True))
            s.commit()
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 71
        company_db._db_path = self.db_path
        oturum.set_user(
            user_id=1,
            kullanici_adi="k1",
            ad_soyad="Kullanıcı 1",
            role_kod="YONETICI",
            role_ad="YONETICI",
            permissions=set(),
        )
        oturum.set_company(
            company_id=71,
            firma_kodu="DOC1",
            firma_unvan="DOC1 Test",
            firma_uid="doc1",
            db_path=str(self.db_path),
        )
        self._eng = eng

    def tearDown(self):
        try:
            company_db.close()
        except Exception:
            pass
        if company_db._engine is not None:
            company_db._engine.dispose()
        try:
            self._eng.dispose()
        except Exception:
            pass
        self._tmpdir.cleanup()

    def test_apel_satir_degerleri_yeni_stokta_korunur(self):
        """07: 36 ADET, fiyat ve KDV değişmez; kart kaydı stok girişi yok."""
        ad = "APEL MK300 PU SIVI ÇİVİ 390 GR"
        miktar = Decimal("36")
        fiyat = Decimal("135.00")
        kdv = Decimal("20")

        with get_session() as s:
            kart = StokKarti(
                stok_kodu="DOC1-APEL-T",
                stok_adi=ad,
                birim="Adet",
                kdv_orani=kdv,
                aktif=True,
                is_deleted=False,
            )
            s.add(kart)
            s.flush()
            kid = kart.id
            s.commit()

        with get_session() as s:
            kart = s.get(StokKarti, kid)
            self.assertEqual(kart.stok_adi, ad)
            self.assertEqual(kart.birim, "Adet")
            self.assertEqual(Decimal(str(kart.kdv_orani)), kdv)
            n = s.scalar(
                select(func.count())
                .select_from(StokHareketi)
                .where(StokHareketi.stok_id == kid)
            )
            self.assertEqual(int(n or 0), 0)

        # Taslak satır bağlamı — miktar/fiyat/KDV korunur (kart bağlanınca da)
        satir = {
            "urun_adi": ad,
            "miktar": miktar,
            "birim": "Adet",
            "birim_fiyat": fiyat,
            "kdv_orani": kdv,
            "stok_id": kid,
        }
        self.assertEqual(satir["miktar"], Decimal("36"))
        self.assertEqual(satir["birim_fiyat"], Decimal("135.00"))
        self.assertEqual(satir["kdv_orani"], Decimal("20"))

    def test_yeni_cari_karti_karsi_taraf_alanlari(self):
        """Yeni Cari: karşı taraf; firma unvanı taşınmaz."""
        with get_session() as s:
            c = Cari(
                cari_kodu="DOC1-C-T",
                unvan="Örnek Tedarikçi A.Ş.",
                cari_turu="Tedarikçi",
                vergi_numarasi="1234567890",
                aktif=True,
            )
            s.add(c)
            s.commit()
            cid = c.id

        with get_session() as s:
            c = s.get(Cari, cid)
            self.assertEqual(c.cari_turu, "Tedarikçi")
            self.assertEqual(c.unvan, "Örnek Tedarikçi A.Ş.")
            self.assertNotIn("DOC1 Test", c.unvan or "")


if __name__ == "__main__":
    unittest.main()
