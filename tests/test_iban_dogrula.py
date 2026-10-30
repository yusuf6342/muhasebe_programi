"""Türkiye IBAN biçim ve MOD-97 doğrulaması."""

import unittest

from database.finans_service import iban_dogrula, iban_normalize


class IbanDogrulaTest(unittest.TestCase):
    # ISO örnek (geçerli MOD-97)
    GECERLI_TR = "TR330006100519786457841326"

    def test_bos_none(self):
        self.assertIsNone(iban_dogrula(None))
        self.assertIsNone(iban_dogrula(""))
        self.assertIsNone(iban_dogrula("   "))

    def test_normalize_bosluk(self):
        self.assertEqual(
            iban_normalize("TR33 0006 1005 1978 6457 8413 26"),
            self.GECERLI_TR,
        )

    def test_gecerli_tr(self):
        self.assertEqual(iban_dogrula(self.GECERLI_TR), self.GECERLI_TR)
        self.assertEqual(
            iban_dogrula("TR33 0006 1005 1978 6457 8413 26"),
            self.GECERLI_TR,
        )

    def test_tr_uzunluk(self):
        with self.assertRaisesRegex(ValueError, "26 karakter"):
            iban_dogrula("TR33000610051978645784132")

    def test_tr_kontrol_basamagi(self):
        bozuk = "TR990006100519786457841326"
        with self.assertRaisesRegex(ValueError, "kontrol basamağı"):
            iban_dogrula(bozuk)

    def test_zorunlu(self):
        with self.assertRaisesRegex(ValueError, "zorunlu"):
            iban_dogrula("", zorunlu=True)


if __name__ == "__main__":
    unittest.main()
