"""Test kurulumu gerçek veri klasörüne (%LOCALAPPDATA%\\MuhasebeProgrami\\data) düşmemeli.

Çalıştırma: python -m pytest tests/test_veri_konumu_guvenlik.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("MUHASEBE_DB_DIR", tempfile.mkdtemp(prefix="cin_veri_konumu_"))

from database import database as db  # noqa: E402


class VeriKonumuGuvenlikTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cin_vk_"))
        self.local = self.tmp / "Local"
        self.gercek = self.local / "MuhasebeProgrami" / "data"
        self.test_veri = self.local / "CinMuhasebeTest" / "data"

    def _sec(self, exe_klasoru: Path, frozen: bool = True):
        exe_klasoru.mkdir(parents=True, exist_ok=True)
        env = {"LOCALAPPDATA": str(self.local), "MUHASEBE_DB_DIR": ""}
        with patch.dict(os.environ, env), patch.object(
            sys, "frozen", frozen, create=True
        ), patch.object(sys, "executable", str(exe_klasoru / "CinMuhasebe.exe")):
            return db._db_dir_sec()

    def test_kurulu_test_exe_veri_konumu_yoksa_test_klasoru(self) -> None:
        yol, kaynak = self._sec(self.local / "Programs" / "CinMuhasebe")
        self.assertEqual(kaynak, "test_kurulumu")
        self.assertEqual(yol, self.test_veri)

    def test_isaret_dosyasi_ozel_kurulum_klasorunde(self) -> None:
        klasor = self.tmp / "OzelKlasor"
        klasor.mkdir(parents=True)
        (klasor / db.TEST_KURULUMU_ISARET_DOSYASI).write_text("x", encoding="utf-8")
        yol, kaynak = self._sec(klasor)
        self.assertEqual((yol, kaynak), (self.test_veri, "test_kurulumu"))

    def test_veri_konumu_txt_oncelikli(self) -> None:
        klasor = self.local / "Programs" / "CinMuhasebe"
        klasor.mkdir(parents=True)
        hedef = self.tmp / "baska"
        (klasor / "veri_konumu.txt").write_text(f"# yorum\n{hedef}\n", encoding="utf-8")
        yol, kaynak = self._sec(klasor)
        self.assertEqual((yol, kaynak), (hedef, "veri_konumu.txt"))

    def test_gelistirme_exe_varsayilan_gercek_klasor(self) -> None:
        yol, kaynak = self._sec(self.tmp / "CinMuhasebeBuild4" / "dist" / "CinMuhasebe")
        self.assertEqual((yol, kaynak), (self.gercek, "varsayilan"))

    def test_kaynak_koddan_varsayilan_degismez(self) -> None:
        yol, kaynak = self._sec(self.tmp / "py", frozen=False)
        self.assertEqual((yol, kaynak), (self.gercek, "varsayilan"))

    def test_firma_yolu_test_klasorunden_gercek_db_acilmaz(self) -> None:
        self.gercek.mkdir(parents=True)
        (self.gercek / "muhasebe.db").write_bytes(b"")
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.local)}), patch.object(
            db, "DB_DIR", self.test_veri
        ), patch.object(db, "COMPANIES_DIR", self.test_veri / "companies"):
            cozulen = db.firma_db_yolu_coz(str(self.gercek / "muhasebe.db"))
            self.assertEqual(cozulen, self.test_veri / "muhasebe.db")
            sirket = db.firma_db_yolu_coz(str(self.gercek / "companies" / "company_x.db"))
            self.assertEqual(sirket, self.test_veri / "companies" / "company_x.db")

    def test_firma_yolu_gercek_klasorde_degismez(self) -> None:
        kayitli = self.gercek / "muhasebe.db"
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.local)}), patch.object(
            db, "DB_DIR", self.gercek
        ), patch.object(db, "COMPANIES_DIR", self.gercek / "companies"):
            self.assertEqual(db.firma_db_yolu_coz(str(kayitli)), kayitli)


if __name__ == "__main__":
    unittest.main()
