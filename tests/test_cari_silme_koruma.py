"""Hareketli cari silinemez; boş mükerrer Evo-id ile doğrulanır."""
from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from database.cari_silme_service import CariSilmeDurumu, evo_meta, silme_durumu
from database.models.cari import Cari


class EvoMetaTest(unittest.TestCase):
    def test_evo_id_parse(self):
        c = Cari(cari_kodu="X", unvan="T", ozel_notlar="Evo cari id 1214\nEvo kod ASKES")
        eid, ekod = evo_meta(c)
        self.assertEqual(eid, "1214")
        self.assertEqual(ekod, "ASKES")


class SilmeDurumuMockTest(unittest.TestCase):
    def test_hareketli_silinemez(self):
        cari = MagicMock()
        cari.id = 1009
        cari.cari_kodu = "ASKES"
        cari.unvan = "AS-KES"
        cari.is_deleted = False
        cari.ozel_notlar = "Evo cari id 1214"

        session = MagicMock()
        session.get.return_value = cari

        # _say / _tablo_say begin_nested context
        nested = MagicMock()
        nested.__enter__ = MagicMock(return_value=None)
        nested.__exit__ = MagicMock(return_value=False)
        session.begin_nested.return_value = nested

        # alt_cari=0, sonra CariIslem=5, diğerleri 0
        session.scalar.side_effect = [0, 5, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        session.execute.return_value.scalar.return_value = 0

        with patch("database.cari_silme_service._yukle_model", side_effect=Exception("skip")), patch(
            "database.cari_service.CariService._ozet",
            return_value={"bakiye": Decimal("0")},
        ):
            durum = silme_durumu(1009, session=session)
        self.assertFalse(durum.silinebilir)
        self.assertTrue(any("hareket" in n.lower() or "işlem" in n.lower() for n in durum.nedenler))

    def test_bos_kart_silinebilir_mock(self):
        cari = MagicMock()
        cari.id = 1112
        cari.cari_kodu = "BOS"
        cari.unvan = "BOŞ"
        cari.is_deleted = False
        cari.ozel_notlar = "Evo cari id 1214"

        session = MagicMock()
        session.get.return_value = cari
        nested = MagicMock()
        nested.__enter__ = MagicMock(return_value=None)
        nested.__exit__ = MagicMock(return_value=False)
        session.begin_nested.return_value = nested
        session.scalar.return_value = 0
        session.execute.return_value.scalar.return_value = 0

        with patch("database.cari_silme_service._yukle_model", side_effect=Exception("skip")), patch(
            "database.cari_service.CariService._ozet",
            return_value={"bakiye": Decimal("0")},
        ):
            durum = silme_durumu(1112, session=session)
        self.assertTrue(durum.silinebilir)
        self.assertEqual(durum.nedenler, [])


class SilmeDurumuDataclassTest(unittest.TestCase):
    def test_neden_metni(self):
        d = CariSilmeDurumu(cari_id=1, silinebilir=False, nedenler=["A", "B"])
        self.assertEqual(d.neden_metni, "A\nB")
        d2 = CariSilmeDurumu(cari_id=1, silinebilir=True)
        self.assertEqual(d2.neden_metni, "")


if __name__ == "__main__":
    unittest.main()
