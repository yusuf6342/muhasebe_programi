"""İşlemi yapan kullanıcı — damga, oturum zorunluluğu, Eski Kayıt."""

from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from database.session_manager import SessionManager, oturum
from database.user_audit import (
    ESKI_KAYIT,
    OturumGerekli,
    display_user,
    require_user_session,
    stamp_approve,
    stamp_cancel,
    stamp_create,
    stamp_update,
)


class BelgeKullaniciDamgaTest(unittest.TestCase):
    def setUp(self):
        self._onceki = (
            oturum.user_id,
            oturum.kullanici_adi,
            oturum.ad_soyad,
            oturum.role_kod,
        )
        oturum.clear()

    def tearDown(self):
        oturum.clear()
        if self._onceki[0]:
            oturum.set_user(
                user_id=self._onceki[0],
                kullanici_adi=self._onceki[1] or "u",
                ad_soyad=self._onceki[2] or "U",
                role_kod=self._onceki[3] or "YONETICI",
                role_ad="Yönetici",
                permissions=set(),
            )

    def test_oturum_yoksa_hata(self):
        with self.assertRaises(OturumGerekli):
            require_user_session()

    def test_created_by_degismez_updated_degisir(self):
        oturum.set_user(
            user_id=1,
            kullanici_adi="a",
            ad_soyad="Ali A",
            role_kod="SATIS",
            role_ad="Satış",
            permissions=set(),
        )
        obj = SimpleNamespace(
            created_by_user_id=None,
            created_by_username=None,
            created_by_full_name=None,
            olusturma_tarihi=None,
            updated_by_user_id=None,
            updated_by_username=None,
            updated_by_full_name=None,
            updated_at=None,
            approved_by_user_id=None,
            approved_by_full_name=None,
            approved_at=None,
            cancelled_by_user_id=None,
            cancelled_by_full_name=None,
            cancelled_at=None,
            cancellation_reason=None,
        )
        stamp_create(obj)
        self.assertEqual(obj.created_by_user_id, 1)
        self.assertEqual(obj.created_by_full_name, "Ali A")

        oturum.set_user(
            user_id=2,
            kullanici_adi="b",
            ad_soyad="Ayşe B",
            role_kod="SATIS",
            role_ad="Satış",
            permissions=set(),
        )
        stamp_update(obj)
        self.assertEqual(obj.created_by_user_id, 1)
        self.assertEqual(obj.created_by_full_name, "Ali A")
        self.assertEqual(obj.updated_by_user_id, 2)
        self.assertEqual(obj.updated_by_full_name, "Ayşe B")

        stamp_approve(obj)
        self.assertEqual(obj.approved_by_user_id, 2)

        oturum.set_user(
            user_id=9,
            kullanici_adi="yon",
            ad_soyad="Yönetici",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        stamp_cancel(obj, "Müşteri vazgeçti")
        self.assertEqual(obj.cancelled_by_full_name, "Yönetici")
        self.assertEqual(obj.cancellation_reason, "Müşteri vazgeçti")
        self.assertEqual(obj.created_by_user_id, 1)

    def test_eski_kayit_gosterimi(self):
        self.assertEqual(display_user(None, None), ESKI_KAYIT)
        self.assertEqual(display_user("  ", None), ESKI_KAYIT)
        self.assertEqual(display_user("Eski Ad", 5), "Eski Ad")

    def test_session_manager_alias(self):
        oturum.set_user(
            user_id=3,
            kullanici_adi="c",
            ad_soyad="Cem C",
            role_kod="SATIS",
            role_ad="Satış",
            permissions=set(),
        )
        self.assertEqual(oturum.current_user_id, 3)
        self.assertEqual(oturum.current_user_full_name, "Cem C")
        self.assertIsNotNone(oturum.login_time)


if __name__ == "__main__":
    unittest.main()
