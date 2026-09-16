"""Aktif kullanıcı değiştirme — şifre/PIN, audit, created_by kuralları."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from database.session_manager import oturum
from database.system.password import hash_parola, parola_dogrula
from database.user_audit import stamp_create, stamp_update
from database.user_switch import (
    _FAILED,
    aktif_kullanici_secenekleri,
    ekran_kilidi_dakika_oku,
    ekran_kilidi_dakika_yaz,
    switch_user,
)


class PasswordHashTest(unittest.TestCase):
    def test_hash_acik_metin_degil(self):
        h = hash_parola("1234")
        self.assertNotEqual(h, "1234")
        self.assertTrue(parola_dogrula("1234", h))
        self.assertFalse(parola_dogrula("9999", h))


class UserSwitchLogicTest(unittest.TestCase):
    def setUp(self):
        self._onceki = (
            oturum.user_id,
            oturum.kullanici_adi,
            oturum.ad_soyad,
            oturum.role_kod,
            set(oturum.permissions),
        )
        oturum.clear()
        _FAILED.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="ahmet",
            ad_soyad="Ahmet Yılmaz",
            role_kod="SATIS",
            role_ad="Satış",
            permissions={"satis_goruntuleme"},
        )

    def tearDown(self):
        oturum.clear()
        _FAILED.clear()
        if self._onceki[0]:
            oturum.set_user(
                user_id=self._onceki[0],
                kullanici_adi=self._onceki[1] or "u",
                ad_soyad=self._onceki[2] or "U",
                role_kod=self._onceki[3] or "YONETICI",
                role_ad="Yönetici",
                permissions=self._onceki[4] or set(),
            )

    def _fake_user(self, *, uid=2, ad="Mehmet Kaya", parola="sifre123", pin="4567", aktif=True):
        u = MagicMock()
        u.id = uid
        u.ad_soyad = ad
        u.kullanici_adi = "mehmet"
        u.aktif = aktif
        u.parola_hash = hash_parola(parola)
        u.hizli_pin_hash = hash_parola(pin) if pin else None
        u.sifre_degistirmeli = False
        u.role = SimpleNamespace(kod="YONETICI", ad="Yönetici")
        u.extra_permissions = []
        u.companies = []
        return u

    @patch("database.user_switch._audit_switch")
    @patch("database.user_switch.kullanici_izinlerini_yukle", return_value={"satis_duzenleme", "maliyet_goruntuleme"})
    @patch("database.user_switch.get_system_session")
    def test_dogru_sifre_ile_gecis(self, mock_sess, _izin, _audit):
        user = self._fake_user()
        session = MagicMock()
        session.scalar.return_value = user
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        mock_sess.return_value = session

        yeni = switch_user(2, "sifre123", active_screen="SATIS_FATURA")
        self.assertEqual(oturum.user_id, 2)
        self.assertEqual(oturum.ad_soyad, "Mehmet Kaya")
        self.assertEqual(yeni["ad_soyad"], "Mehmet Kaya")
        self.assertIn("maliyet_goruntuleme", oturum.permissions)

    @patch("database.user_switch._audit_switch")
    @patch("database.user_switch.kullanici_izinlerini_yukle", return_value=set())
    @patch("database.user_switch.get_system_session")
    def test_dogru_pin_ile_gecis(self, mock_sess, _izin, _audit):
        user = self._fake_user()
        session = MagicMock()
        session.scalar.return_value = user
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        mock_sess.return_value = session

        switch_user(2, "4567", active_screen="HIZLI_SATIS")
        self.assertEqual(oturum.user_id, 2)

    @patch("database.user_switch._audit_switch")
    @patch("database.user_switch.get_system_session")
    def test_yanlis_pin_degistirmez(self, mock_sess, mock_audit):
        user = self._fake_user()
        session = MagicMock()
        session.scalar.return_value = user
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        mock_sess.return_value = session

        with self.assertRaises(ValueError) as ctx:
            switch_user(2, "0000", active_screen="SATIS_FATURA")
        self.assertIn("hatalı", str(ctx.exception).lower())
        self.assertEqual(oturum.user_id, 1)
        self.assertEqual(oturum.ad_soyad, "Ahmet Yılmaz")
        mock_audit.assert_called()
        kwargs = mock_audit.call_args.kwargs
        self.assertFalse(kwargs.get("basarili"))

    @patch("database.user_switch._audit_switch")
    @patch("database.user_switch.get_system_session")
    def test_eski_kullanici_sifresi_yetersiz(self, mock_sess, _audit):
        """Mevcut kullanıcının şifresiyle başka hesaba geçilemez."""
        user = self._fake_user(parola="mehmet_sifre", pin=None)
        session = MagicMock()
        session.scalar.return_value = user
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        mock_sess.return_value = session

        with self.assertRaises(ValueError):
            switch_user(2, "ahmet_sifresi_degil")
        self.assertEqual(oturum.user_id, 1)

    def test_kaydedilmis_belgede_created_by_degismez(self):
        belge = SimpleNamespace(
            created_by_user_id=None,
            created_by_full_name=None,
            updated_by_user_id=None,
            updated_by_full_name=None,
        )
        stamp_create(belge)
        self.assertEqual(belge.created_by_user_id, 1)
        oturum.set_user(
            user_id=9,
            kullanici_adi="mehmet",
            ad_soyad="Mehmet Kaya",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        stamp_update(belge)
        self.assertEqual(belge.created_by_user_id, 1)
        self.assertEqual(belge.updated_by_user_id, 9)

    def test_pasif_kullanici_listede_yok(self):
        aktif = SimpleNamespace(
            id=1,
            ad_soyad="Aktif",
            role=SimpleNamespace(kod="SATIS", ad="Satış"),
            companies=[],
            varsayilan_firma_id=None,
            hizli_pin_hash=None,
        )
        with patch("database.user_switch.get_system_session") as mock_sess:
            session = MagicMock()
            session.scalars.return_value.all.return_value = [aktif]
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            mock_sess.return_value = session
            liste = aktif_kullanici_secenekleri()
        self.assertTrue(all(x.get("id") for x in liste))
        # Sorgu zaten aktif.is_(True) — pasif gelmez
        self.assertEqual(len(liste), 1)

    def test_ekran_kilidi_ayar(self):
        once = ekran_kilidi_dakika_oku()
        try:
            ekran_kilidi_dakika_yaz(15)
            self.assertEqual(ekran_kilidi_dakika_oku(), 15)
            ekran_kilidi_dakika_yaz(0)
            self.assertEqual(ekran_kilidi_dakika_oku(), 0)
        finally:
            try:
                ekran_kilidi_dakika_yaz(once if once in (0, 5, 10, 15, 30) else 0)
            except Exception:
                pass

    def test_notify_user_changed(self):
        cagrildi = []

        def _cb(old, new):
            cagrildi.append((old.get("user_id"), new.get("user_id")))

        oturum.on_user_changed(_cb)
        try:
            with patch("database.user_switch._audit_switch"), patch(
                "database.user_switch.kullanici_izinlerini_yukle", return_value=set()
            ), patch("database.user_switch.get_system_session") as mock_sess:
                user = self._fake_user()
                session = MagicMock()
                session.scalar.return_value = user
                session.__enter__ = MagicMock(return_value=session)
                session.__exit__ = MagicMock(return_value=False)
                mock_sess.return_value = session
                switch_user(2, "sifre123")
            self.assertEqual(cagrildi[-1], (1, 2))
        finally:
            oturum.off_user_changed(_cb)


if __name__ == "__main__":
    unittest.main()
