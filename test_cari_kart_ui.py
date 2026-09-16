"""Geçici DB ile cari kart özet / kayıt / UI smoke testleri."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db
from database.models.cari import Cari, MusteriGrubu
from database.models.donem import Donem
from database.models.finans import FinansHesabi
from database.models.firma import Firma
from database.session_manager import oturum


def _sqlite_pragma(dbapi_conn, _connection_record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class CariKartSmokeTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "cari_kart.db"
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

        Base.metadata.create_all(eng)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        with Session() as s:
            firma = Firma(firma_kodu="CKT", unvan="Cari Kart Test", aktif=True)
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
            cari = Cari(
                cari_kodu="M1001",
                unvan="Smoke Müşteri",
                cari_turu="Müşteri",
                aktif=True,
                acik_hesap_risk_limiti=Decimal("10000"),
                telefon="05321234567",
            )
            s.add(cari)
            s.commit()
            self.cari_id = int(cari.id)

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
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
            company_id=1,
            firma_kodu="CKT",
            firma_unvan="Cari Kart Test",
            firma_uid="ckt-test",
            db_path=str(self.db_path),
        )
        oturum.set_period(1, "2026")

    def tearDown(self):
        oturum.clear()
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def test_guncelle_ve_kart_ozet(self):
        from database.cari_service import CariService

        c = CariService.guncelle(
            self.cari_id, {"unvan": "Smoke Müşteri Güncel", "email": "a@b.com"}
        )
        self.assertEqual(c.unvan, "Smoke Müşteri Güncel")
        m = CariService.kart_ozet_metrikleri(self.cari_id)
        self.assertIsNotNone(m)
        self.assertEqual(m["bakiye"], Decimal("0"))
        self.assertEqual(Decimal(str(m["kullanilabilir_risk"])), Decimal("10000"))
        self.assertEqual(m["vadesi_gecmis"], Decimal("0"))
        self.assertIsInstance(m["hareketler"], list)

    def test_ui_open_dirty_kaydet(self):
        import tkinter as tk

        from cari_kart_ui import CariDialog
        from database.cari_service import CariService

        cari = CariService.getir(self.cari_id)
        root = tk.Tk()
        root.withdraw()
        try:
            dlg = CariDialog(root, cari=cari)
            root.update_idletasks()
            self.assertTrue(dlg.winfo_exists())
            self.assertFalse(dlg._kirli_mi())
            dlg.degerler["unvan"].delete(0, "end")
            dlg.degerler["unvan"].insert(0, "UI Kayit")
            self.assertTrue(dlg._kirli_mi())
            self.assertTrue(dlg.kaydet(kapat=False))
            self.assertEqual(dlg.cari.unvan, "UI Kayit")
            dlg.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
