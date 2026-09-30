"""Alış faturası penceresi açılmalı; TOPLAMLAR sabit alt bantta görünmeli."""

from __future__ import annotations

import sys
import tempfile
import tkinter as tk
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import importlib
import pkgutil

import database.models

for _m in pkgutil.iter_modules(database.models.__path__):
    importlib.import_module(f"database.models.{_m.name}")

from database.database import Base, _aktif_engine_bagla
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.finans import FinansHesabi
from database.models.firma import Firma
from database.models.stok import Depo
from database.session_manager import oturum


class AlisFaturasiAcilisTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        path = Path(self._tmpdir.name) / "alis.db"
        eng = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(eng)
        with sessionmaker(bind=eng, expire_on_commit=False)() as s:
            firma = Firma(firma_kodu="ALS", unvan="Alış Test", aktif=True)
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
            s.add(Depo(ad="ANA DEPO", aktif=True))
            s.add(Cari(cari_kodu="T0001", unvan="Tedarikçi Test", cari_turu="Tedarikçi", aktif=True))
            s.commit()
        _aktif_engine_bagla(eng)
        oturum.set_company(company_id=1, firma_kodu="ALS", firma_unvan="Alış Test", firma_uid="x", db_path=str(path))
        self._eng = eng

    def tearDown(self):
        try:
            from database.database import engine

            if engine is not None:
                engine.dispose()
        except Exception:
            pass
        self._eng.dispose()
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def test_pencere_acilir_toplamlar_alt_bantta(self):
        from alis_ui import AlisFaturasiDialog

        root = tk.Tk()
        root.withdraw()
        try:
            dlg = AlisFaturasiDialog(root)
            dlg.update_idletasks()
            toplam = dlg._alis_toplam_cerceve
            self.assertEqual(toplam.winfo_manager(), "pack")
            alt = dlg.nametowidget(toplam.pack_info()["in"])
            self.assertEqual(alt.winfo_manager(), "pack")
            self.assertEqual(alt.pack_info()["side"], "bottom")
            self.assertTrue(dlg.winfo_exists())
            dlg.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
