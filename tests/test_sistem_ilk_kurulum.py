"""Boş veri klasöründe ilk açılış: sistem kurulumu muhasebe.db yokken hata vermemeli."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from database.system.bootstrap import sistem_baslat


class SistemIlkKurulumTest(unittest.TestCase):
    def test_bos_klasorde_ilk_acilis_ve_sonraki_gecis(self):
        with tempfile.TemporaryDirectory() as d:
            klasor = Path(d)
            system_db = klasor / "system.db"
            muhasebe_db = klasor / "muhasebe.db"

            ilk = sistem_baslat(system_db, muhasebe_db)
            self.assertTrue(ilk["admin_olusturuldu"])
            self.assertFalse(ilk["gecis"]["yedek_alindi"])
            self.assertIn("Yeni kurulum", " ".join(ilk["gecis"]["mesajlar"]))
            self.assertFalse(muhasebe_db.exists())

            # Tablolar oluşturulduktan sonraki açılışta geçiş yedeği normal alınır
            sqlite3.connect(muhasebe_db).close()
            ikinci = sistem_baslat(system_db, muhasebe_db)
            self.assertFalse(ikinci["admin_olusturuldu"])
            self.assertTrue(ikinci["gecis"]["yedek_alindi"])
            self.assertTrue(Path(ikinci["gecis"]["yedek_yolu"]).exists())


if __name__ == "__main__":
    unittest.main()
