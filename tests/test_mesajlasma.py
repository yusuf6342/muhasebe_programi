"""Firma içi mesajlaşma — servis kabul testleri (GUI/EXE yok).

Çalıştırma: python -m pytest tests/test_mesajlasma.py -q
"""

from __future__ import annotations

import os
import tempfile
import unittest
import uuid
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

# Test: geçici system SQLite
os.environ.setdefault("MUHASEBE_DB_DIR", tempfile.mkdtemp(prefix="cin_msg_"))


class MesajlasmaServisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="cin_msg_sys_")
        cls.sys_db = Path(cls._tmpdir.name) / "system.db"
        from database.system.models import (
            Company,
            Mesaj,
            MesajKonusma,
            MesajKonusmaUye,
            Role,
            SystemBase,
            User,
            UserCompany,
        )
        from database.system.password import hash_parola
        import database.database as db
        from database.session_manager import oturum

        eng = create_engine(f"sqlite:///{cls.sys_db.as_posix()}", future=True)
        SystemBase.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        db.system_engine = eng
        db.SystemSessionLocal = Session

        with Session() as s:
            rol = Role(kod="YONETICI", ad="Yönetici", sistem=True)
            s.add(rol)
            s.flush()
            c = Company(
                firma_uid="test-uid",
                firma_kodu="TST001",
                unvan="Test Firma",
                db_path=":memory:",
                aktif=True,
            )
            s.add(c)
            s.flush()
            u1 = User(
                kullanici_kodu="U1",
                ad_soyad="Ali Test",
                kullanici_adi="ali",
                parola_hash=hash_parola("x"),
                role_id=rol.id,
                aktif=True,
            )
            u2 = User(
                kullanici_kodu="U2",
                ad_soyad="Veli Test",
                kullanici_adi="veli",
                parola_hash=hash_parola("x"),
                role_id=rol.id,
                aktif=True,
            )
            u3 = User(
                kullanici_kodu="U3",
                ad_soyad="Yabancı",
                kullanici_adi="yabanci",
                parola_hash=hash_parola("x"),
                role_id=rol.id,
                aktif=True,
            )
            s.add_all([u1, u2, u3])
            s.flush()
            s.add(UserCompany(user_id=u1.id, company_id=c.id))
            s.add(UserCompany(user_id=u2.id, company_id=c.id))
            # u3 firmaya bağlı değil
            s.commit()
            cls.cid = int(c.id)
            cls.uid1 = int(u1.id)
            cls.uid2 = int(u2.id)
            cls.uid3 = int(u3.id)

        cls.oturum = oturum
        cls.Session = Session
        cls.Mesaj = Mesaj
        cls.MesajKonusma = MesajKonusma
        cls.MesajKonusmaUye = MesajKonusmaUye

    @classmethod
    def tearDownClass(cls):
        cls.oturum.clear()
        try:
            import database.database as db

            if db.system_engine is not None:
                db.system_engine.dispose()
            db.SystemSessionLocal = None
            db.system_engine = None
        except Exception:
            pass
        try:
            cls._tmpdir.cleanup()
        except Exception:
            pass

    def setUp(self):
        self.oturum.clear()
        self.oturum.set_user(
            user_id=self.uid1,
            kullanici_adi="ali",
            ad_soyad="Ali Test",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        self.oturum.set_company(
            company_id=self.cid,
            firma_kodu="TST001",
            firma_unvan="Test Firma",
            firma_uid="test-uid",
            db_path=":memory:",
        )

    def test_karsilikli_mesaj_ve_okundu(self):
        from database.mesajlasma_service import MesajlasmaService

        k = MesajlasmaService.dm_ac_veya_bul(self.uid2)
        kid = int(k["id"])
        cid1 = str(uuid.uuid4())
        m1 = MesajlasmaService.mesaj_gonder(kid, "Merhaba Veli", client_msg_id=cid1)
        self.assertEqual(m1["icerik"], "Merhaba Veli")
        self.assertEqual(m1["durum"], "gonderildi")  # Veli henüz okumadı

        # Mükerrer client_msg_id çoğaltmaz
        m1b = MesajlasmaService.mesaj_gonder(kid, "Merhaba Veli", client_msg_id=cid1)
        self.assertEqual(m1b["id"], m1["id"])

        # Veli oturumu — okunmamış
        self.oturum.set_user(
            user_id=self.uid2,
            kullanici_adi="veli",
            ad_soyad="Veli Test",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        self.assertGreaterEqual(MesajlasmaService.okunmamis_toplam(), 1)
        # Program açık ama konuşma açılmadan okunmuş sayılmaz
        self.assertGreaterEqual(MesajlasmaService.okunmamis_toplam(), 1)

        liste = MesajlasmaService.mesajlari_listele(kid)
        self.assertEqual(len(liste), 1)
        MesajlasmaService.konusmayi_okundu_isaretle(kid, liste[-1]["id"])
        self.assertEqual(MesajlasmaService.okunmamis_toplam(), 0)

        # Ali tarafında durum okundu
        self.oturum.set_user(
            user_id=self.uid1,
            kullanici_adi="ali",
            ad_soyad="Ali Test",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        liste2 = MesajlasmaService.mesajlari_listele(kid)
        self.assertEqual(liste2[0]["durum"], "okundu")

        # Veli yanıt
        self.oturum.set_user(
            user_id=self.uid2,
            kullanici_adi="veli",
            ad_soyad="Veli Test",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        MesajlasmaService.mesaj_gonder(kid, "Selam Ali")

        self.oturum.set_user(
            user_id=self.uid1,
            kullanici_adi="ali",
            ad_soyad="Ali Test",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        self.assertGreaterEqual(MesajlasmaService.okunmamis_toplam(), 1)
        poll = MesajlasmaService.poll(0)
        self.assertGreaterEqual(poll["okunmamis"], 1)

    def test_yetkisiz_konusma_ve_firma_disi(self):
        from database.mesajlasma_service import MesajlasmaError, MesajlasmaService

        with self.assertRaises(MesajlasmaError):
            MesajlasmaService.dm_ac_veya_bul(self.uid3)

        k = MesajlasmaService.dm_ac_veya_bul(self.uid2)
        kid = int(k["id"])
        # Yabancı kullanıcı
        self.oturum.set_user(
            user_id=self.uid3,
            kullanici_adi="yabanci",
            ad_soyad="Yabancı",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        with self.assertRaises(MesajlasmaError):
            MesajlasmaService.mesajlari_listele(kid)
        with self.assertRaises(MesajlasmaError):
            MesajlasmaService.mesaj_gonder(kid, "hack")

    def test_bos_mesaj_red(self):
        from database.mesajlasma_service import MesajlasmaError, MesajlasmaService

        k = MesajlasmaService.dm_ac_veya_bul(self.uid2)
        with self.assertRaises(MesajlasmaError):
            MesajlasmaService.mesaj_gonder(int(k["id"]), "   ")

    def test_firma_kullanici_listesi(self):
        from database.mesajlasma_service import MesajlasmaService

        liste = MesajlasmaService.firma_kullanicilari()
        idler = {u["id"] for u in liste}
        self.assertIn(self.uid2, idler)
        self.assertNotIn(self.uid1, idler)
        self.assertNotIn(self.uid3, idler)


class MesajlasmaUiSmokeTest(unittest.TestCase):
    def test_dugme_ve_rozet(self):
        import tkinter as tk
        from unittest.mock import patch

        root = tk.Tk()
        root.withdraw()
        try:
            with patch("mesajlasma_ui.MesajlasmaService.poll", return_value={"okunmamis": 2, "yeni": [], "max_mesaj_id": 0}):
                with patch("mesajlasma_ui.MesajlasmaService.okunmamis_toplam", return_value=2):
                    from mesajlasma_ui import MesajlasmaYoneticisi, mesajlar_dugmesi_ekle

                    MesajlasmaYoneticisi._ornek = None
                    yon = MesajlasmaYoneticisi.ornek(root)
                    refs = mesajlar_dugmesi_ekle(root, bg="#fff", root=root)
                    self.assertIn("cerceve", refs)
                    yon._rozet_hemen(3)
                    root.update_idletasks()
                    yon.durdur()
                    MesajlasmaYoneticisi._ornek = None
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main(verbosity=2)
