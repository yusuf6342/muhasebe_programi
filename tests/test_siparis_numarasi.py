import unittest
from unittest.mock import patch

from database.satis_siparisi_service import SatisSiparisiService


class _Result:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Session:
    def __init__(self, values):
        self.values = values

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def scalars(self, _statement):
        return _Result(self.values)


class SiparisNumarasiTest(unittest.TestCase):
    def test_siparis_numarasi_bes_hane_ve_sirali(self):
        with patch(
            "database.satis_siparisi_service.get_session",
            return_value=_Session(["SIP-00001", "SIP-00007", "SIP-20260924180253"]),
        ):
            self.assertEqual(SatisSiparisiService.siparis_no(), "SIP-00008")

    def test_ilk_siparis_numarasi(self):
        with patch(
            "database.satis_siparisi_service.get_session",
            return_value=_Session([]),
        ):
            self.assertEqual(SatisSiparisiService.siparis_no(), "SIP-00001")


if __name__ == "__main__":
    unittest.main()
