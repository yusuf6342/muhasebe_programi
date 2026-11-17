"""Cari virman düzenle / sil: bakiye, belge no ve iptal."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.cari_service import CariService
from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.cari import Cari, CariIslem, SatisHareketi
from database.models.donem import Donem
from database.models.firma import Firma
from database.session_manager import oturum

TARIH = date(2026, 6, 5)


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class CariVirmanDuzenleSilTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_cari_virman.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_masraf  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.cari  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.kart_turu  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.stok  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="VRM", unvan="Virman Test", aktif=True)
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
            m = Cari(cari_kodu="M001", unvan="Musteri A", cari_turu="Müşteri", aktif=True)
            t = Cari(cari_kodu="T001", unvan="Tedarikci B", cari_turu="Tedarikçi", aktif=True)
            c = Cari(cari_kodu="M002", unvan="Musteri C", cari_turu="Müşteri", aktif=True)
            s.add_all([m, t, c])
            s.commit()
            self.musteri_id = int(m.id)
            self.tedarikci_id = int(t.id)
            self.hedef_c_id = int(c.id)

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
            firma_kodu="VRM",
            firma_unvan="Virman",
            firma_uid="vrm",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            oturum.set_period(d.id, d.donem_adi)

        self._muhasebe_patch = patch(
            "database.muhasebe_entegrasyon.muhasebe_hook", lambda *_a, **_k: None
        )
        self._muhasebe_patch.start()
        self._donem_patch = patch(
            "database.donem_service.DonemService.kayit_izinli_mi", return_value=True
        )
        self._donem_patch.start()

    def tearDown(self):
        self._donem_patch.stop()
        self._muhasebe_patch.stop()
        try:
            company_db.close()
        except Exception:
            pass
        if company_db._engine is not None:
            try:
                company_db._engine.dispose()
            except Exception:
                pass
        company_db._engine = None
        company_db._session_factory = None
        oturum.clear()
        self._tmpdir.cleanup()

    def _bakiye(self, cari_id: int) -> Decimal:
        with get_session() as session:
            islemler = session.scalars(
                select(CariIslem).where(CariIslem.cari_id == cari_id)
            ).all()
            return sum(
                (Decimal(str(i.borc or 0)) - Decimal(str(i.alacak or 0)) for i in islemler),
                Decimal("0"),
            )

    def test_virman_guncelle_tutar_ve_cari_degistir(self):
        kaynak_a, hedef_b, hedef_c = self.musteri_id, self.tedarikci_id, self.hedef_c_id
        k, h = CariService.virman_yap(kaynak_a, hedef_b, TARIH, Decimal("150.00"), "deneme")
        belge_no = k.belge_no
        once_a = self._bakiye(kaynak_a)
        once_b = self._bakiye(hedef_b)
        once_c = self._bakiye(hedef_c)

        k2, h2 = CariService.virman_guncelle(
            belge_no,
            kaynak_a,
            hedef_c,
            TARIH,
            Decimal("200.00"),
            "guncellendi",
        )
        self.assertEqual(k2.belge_no, belge_no)
        self.assertEqual(int(k2.id), int(k.id))
        self.assertEqual(int(h2.id), int(h.id))
        self.assertEqual(Decimal(str(k2.alacak)), Decimal("200.00"))
        self.assertEqual(int(h2.cari_id), hedef_c)

        getir = CariService.virman_getir(belge_no)
        self.assertEqual(getir["belge_no"], belge_no)
        self.assertEqual(getir["hedef_id"], hedef_c)
        self.assertEqual(Decimal(str(getir["tutar"])), Decimal("200.00"))

        self.assertEqual(self._bakiye(hedef_b), once_b - Decimal("150.00"))
        self.assertEqual(self._bakiye(hedef_c), once_c + Decimal("200.00"))
        self.assertEqual(self._bakiye(kaynak_a), once_a - Decimal("50.00"))

        with get_session() as session:
            eski = session.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == belge_no,
                    SatisHareketi.cari_id == hedef_b,
                )
            )
            self.assertIsNone(eski)
            yeni = session.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == belge_no,
                    SatisHareketi.cari_id == hedef_c,
                )
            )
            self.assertIsNotNone(yeni)
            self.assertEqual(Decimal(str(yeni.satis_tutari)), Decimal("200.00"))

    def test_virman_iptal_bakiyeyi_geri_alir(self):
        k, _h = CariService.virman_yap(
            self.musteri_id, self.tedarikci_id, TARIH, Decimal("75.50"), "silinecek"
        )
        belge_no = k.belge_no
        once_m = self._bakiye(self.musteri_id)
        once_t = self._bakiye(self.tedarikci_id)
        CariService.virman_iptal(belge_no)
        self.assertEqual(self._bakiye(self.musteri_id), once_m + Decimal("75.50"))
        self.assertEqual(self._bakiye(self.tedarikci_id), once_t - Decimal("75.50"))
        with self.assertRaises(ValueError):
            CariService.virman_getir(belge_no)


if __name__ == "__main__":
    unittest.main()
