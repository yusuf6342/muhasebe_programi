"""Fatura açılış performansı — lazy müşteri/stok arama.

.venv\\Scripts\\python.exe -m unittest tests.test_fatura_acilis_perf -v
"""

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

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla
from database.models.cari import Cari, MusteriGrubu
from database.models.donem import Donem
from database.models.finans import FinansHesabi
from database.models.firma import Firma
from database.models.stok import Depo, StokKarti
from database.session_manager import oturum


def _pragma(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class FaturaAcilisPerfTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        path = Path(self._tmpdir.name) / "perf.db"
        eng = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.doviz  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        self._Session = Session
        with Session() as s:
            firma = Firma(firma_kodu="PRF", unvan="Perf", aktif=True)
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
            s.add(FinansHesabi(hesap_adi="KASA", hesap_turu="KASA", aktif=True))
            s.add(MusteriGrubu(ad="Genel"))
            s.add(Depo(ad="ANA DEPO", aktif=True))
            for i in range(80):
                s.add(
                    Cari(
                        cari_kodu=f"M{i:04d}",
                        unvan=f"Müşteri Test {i:04d}",
                        cari_turu="Müşteri",
                        aktif=True,
                    )
                )
            for i in range(40):
                s.add(
                    StokKarti(
                        stok_kodu=f"U{i:04d}",
                        stok_adi=f"Ürün {i:04d}",
                        birim="Adet",
                        aktif=True,
                        barkod=f"869{i:10d}"[:13],
                    )
                )
            s.commit()
        _aktif_engine_bagla(eng)
        oturum.set_company(company_id=1, firma_kodu="PRF", firma_unvan="Perf", firma_uid="x", db_path=str(path))

    def tearDown(self):
        try:
            from database.database import engine

            if engine is not None:
                engine.dispose()
        except Exception:
            pass
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def test_musteri_ara_limit(self):
        from database.cari_service import CariService

        sonuc = CariService.musteri_ara_hizli("Test", limit=20)
        self.assertLessEqual(len(sonuc), 20)
        self.assertTrue(all("cari" in x for x in sonuc))

    def test_stok_ara_limit(self):
        from database.stok_service import StokService

        sonuc = StokService.stoklari_ara("Ürün", limit=15)
        self.assertLessEqual(len(sonuc), 15)

    def test_fatura_dialog_yuklemez_tum_carileri(self):
        import tkinter as tk
        from app import SatisFaturasiDialog
        from database import satis_siparisi_service as sss
        from database import cari_service as cs

        calls = {"musteri": 0, "listele": 0}
        real_m = sss.SatisSiparisiService.aktif_musterileri
        real_l = cs.CariService.listele

        def wm():
            calls["musteri"] += 1
            return real_m()

        def wl(*a, **k):
            calls["listele"] += 1
            return real_l(*a, **k)

        sss.SatisSiparisiService.aktif_musterileri = staticmethod(wm)
        cs.CariService.listele = staticmethod(wl)
        root = tk.Tk()
        root.withdraw()
        try:
            with patch("satis_personeli_ui.aktif_satis_personelleri", return_value=[]), patch(
                "satis_personeli_ui.satis_personeli_degistirme_yetkisi", return_value=True
            ), patch(
                "fatura_acilis_cache.satis_personelleri", return_value=[]
            ):
                dlg = SatisFaturasiDialog(root)
                self.assertEqual(calls["musteri"], 0)
                self.assertEqual(calls["listele"], 0)
                self.assertEqual(len(dlg.musteriler), 0)
                dlg.destroy()
        finally:
            sss.SatisSiparisiService.aktif_musterileri = real_m
            cs.CariService.listele = real_l
            root.destroy()

    def test_cache_ttl(self):
        import fatura_acilis_cache as c

        c.invalidate()
        n = {"x": 0}

        def uret():
            n["x"] += 1
            return ["A"]

        a = c.get("t", uret, ttl=60)
        b = c.get("t", uret, ttl=60)
        self.assertEqual(a, b)
        self.assertEqual(n["x"], 1)
        c.invalidate("t")
        c.get("t", uret, ttl=60)
        self.assertEqual(n["x"], 2)


if __name__ == "__main__":
    unittest.main()
