"""Tedarikçi defter gösterimi: alış → Alacak (+); ödeme → Borç (+); net değişmez."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.cari_service import CariService
from database.models.cari import Cari, CariIslem, SatisHareketi
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.alis_faturasi import AlisFaturasi
from database.session_manager import oturum


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class CariDefterTedarikciGosterimTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        path = Path(self._tmpdir.name) / "defter.db"
        eng = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
        event.listen(eng, "connect", _pragma)
        import importlib
        import pkgutil
        import database.models as modeller

        for bilgi in pkgutil.iter_modules(modeller.__path__):
            importlib.import_module(f"database.models.{bilgi.name}")
        Base.metadata.create_all(eng)
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        company_db._company_id = 1
        company_db._db_path = str(path)
        with get_session() as s:
            firma = Firma(firma_kodu="DFT", unvan="Defter Test", aktif=True)
            s.add(firma)
            s.flush()
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
            ted = Cari(cari_kodu="T0048", unvan="DENGE", cari_turu="Tedarikçi")
            s.add(ted)
            s.flush()
            # Evo tarzı negatif SH (DB işareti korunur)
            s.add(
                SatisHareketi(
                    cari_id=ted.id,
                    satis_tarihi=date(2026, 10, 1),
                    belge_no="EVB-AF-15261",
                    satis_tutari=Decimal("-1400"),
                    kalan_acik_tutar=Decimal("-1400"),
                )
            )
            s.add(
                SatisHareketi(
                    cari_id=ted.id,
                    satis_tarihi=date(2026, 10, 2),
                    belge_no="EVB-AF-14977",
                    satis_tutari=Decimal("-15750"),
                    kalan_acik_tutar=Decimal("-15750"),
                )
            )
            # Kaynak alış faturaları
            for no, tut in (("EVB-AF-15261", "1400"), ("EVB-AF-14977", "15750")):
                s.add(
                    AlisFaturasi(
                        fatura_no=no,
                        cari_id=ted.id,
                        fatura_tarihi=date(2026, 10, 1),
                        vade_tarihi=date(2026, 10, 1),
                        tl_genel_toplam=Decimal(tut),
                        durum="ONAYLI",
                    )
                )
            # Gerçek satış (tedarikçiye) — dönüştürülmemeli
            s.add(
                SatisHareketi(
                    cari_id=ted.id,
                    satis_tarihi=date(2026, 10, 3),
                    belge_no="SAF05912",
                    satis_tutari=Decimal("8600"),
                    kalan_acik_tutar=Decimal("8600"),
                )
            )
            s.add(
                CariIslem(
                    cari_id=ted.id,
                    tarih=date(2026, 11, 11),
                    islem_turu="Ödeme",
                    belge_no="OMK-2026-0080",
                    borc=Decimal("50000"),
                    alacak=Decimal("0"),
                )
            )
            s.commit()
            self.ted_id = ted.id
        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Test",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=1, firma_kodu="DFT", firma_unvan="Defter", firma_uid="dft", db_path=str(path)
        )

    def tearDown(self):
        oturum.clear()
        try:
            company_db.close()
        except Exception:
            pass
        self._tmpdir.cleanup()

    def test_alis_pozitif_alacak_satirinda_satis_etiketi_degil(self):
        with get_session() as s:
            defter = CariService._defter(s, self.ted_id)
        by_bn = {d["belge_no"]: d for d in defter}
        a1 = by_bn["EVB-AF-15261"]
        self.assertEqual(a1["tur"], "Alış")
        self.assertEqual(a1["borc"], Decimal("0"))
        self.assertEqual(a1["alacak"], Decimal("1400.00"))
        a2 = by_bn["EVB-AF-14977"]
        self.assertEqual(a2["tur"], "Alış")
        self.assertEqual(a2["alacak"], Decimal("15750.00"))
        self.assertGreaterEqual(a2["borc"], Decimal("0"))

    def test_gercek_satis_alisa_donusmez(self):
        with get_session() as s:
            defter = CariService._defter(s, self.ted_id)
        sat = next(d for d in defter if d["belge_no"] == "SAF05912")
        self.assertEqual(sat["tur"], "Satış")
        self.assertEqual(sat["borc"], Decimal("8600.00"))

    def test_odeme_borc_pozitif_net_tutarli(self):
        with get_session() as s:
            defter = CariService._defter(s, self.ted_id)
        od = next(d for d in defter if d["belge_no"] == "OMK-2026-0080")
        self.assertEqual(od["tur"], "Ödeme")
        self.assertEqual(od["borc"], Decimal("50000.00"))
        self.assertEqual(od["alacak"], Decimal("0.00"))
        # Net = borc - alacak (görünür satırlardan)
        tb = sum((Decimal(str(d["borc"] or 0)) for d in defter), Decimal("0"))
        ta = sum((Decimal(str(d["alacak"] or 0)) for d in defter), Decimal("0"))
        # 50000 + 8600 - (1400+15750) = 41450
        self.assertEqual(tb - ta, Decimal("41450.00"))
        # Negatif sütun yok
        for d in defter:
            self.assertGreaterEqual(Decimal(str(d["borc"] or 0)), Decimal("0"))
            self.assertGreaterEqual(Decimal(str(d["alacak"] or 0)), Decimal("0"))


if __name__ == "__main__":
    unittest.main()
