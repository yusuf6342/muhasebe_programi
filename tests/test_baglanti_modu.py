"""Bağlantı kipi: yerel SQLite varsayılan; LAN ayarı dosyaya yazılır."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.baglanti_modu import (
    BaglantiAyari,
    CalismaKipi,
    ayari_kaydet,
    ayari_yukle,
    baglanti_sina,
)
from database.dialect_utils import sqlite_mi
from database.engine_factory import sqlite_engine


class BaglantiModuTest(unittest.TestCase):
    def test_varsayilan_yerel_sqlite(self):
        with tempfile.TemporaryDirectory() as td:
            ayar = ayari_yukle(Path(td))
            self.assertEqual(ayar.kipi, CalismaKipi.YEREL_SQLITE.value)
            self.assertFalse(ayar.ag_mi)

    def test_kaydet_yukle_ag(self):
        with tempfile.TemporaryDirectory() as td:
            ayar = BaglantiAyari.from_dict(
                {
                    "kipi": CalismaKipi.YEREL_AG_POSTGRES.value,
                    "postgres": {
                        "host": "192.168.1.10",
                        "port": 5432,
                        "sistem_db": "cin_sistem",
                        "ortam": "DENEME",
                    },
                }
            )
            yol = ayari_kaydet(ayar, Path(td))
            self.assertTrue(yol.is_file())
            data = json.loads(yol.read_text(encoding="utf-8"))
            self.assertNotIn("password", json.dumps(data).lower())
            yuklenen = ayari_yukle(Path(td))
            self.assertTrue(yuklenen.ag_mi)
            self.assertEqual(yuklenen.postgres.host, "192.168.1.10")
            self.assertIn("DENEME", yuklenen.postgres.ozet())

    def test_sina_yerel_ok(self):
        ayar = BaglantiAyari()
        sonuc = baglanti_sina(ayar)
        self.assertTrue(sonuc["ok"])
        self.assertEqual(sonuc["kipi"], CalismaKipi.YEREL_SQLITE.value)

    def test_dialect_sqlite(self):
        with tempfile.TemporaryDirectory() as td:
            eng = sqlite_engine(Path(td) / "x.db")
            self.assertTrue(sqlite_mi(eng))
            eng.dispose()


if __name__ == "__main__":
    unittest.main()
