"""Ev/test kurulumu: boş test firması, örnek veri ve ilk giriş ipucu."""
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

import database.models  # noqa: F401  (tüm tablolar metadata'ya kayıtlı olsun)
from database import database as db
from database import ornek_veri
from database.models.cari import Cari
from database.models.stok import StokKarti
from database.system.bootstrap import RAY_UNVAN, sistem_baslat
from database.system.models import Company


def _bellek_oturumu():
    engine = create_engine("sqlite://")
    db.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def get_session():
        s = Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    return get_session


class OrnekVeriTest(unittest.TestCase):
    def test_idempotent_ve_hepsi_etiketli(self):
        import database.stok_service as stok_service
        from database.models.stok import Depo, StokLotu

        get_session = _bellek_oturumu()
        with get_session() as s:
            s.add(Depo(kod="ANA", ad="ANA DEPO", aktif=True, varsayilan=True))
        # Açılışta oturum yokken çalışır: yetki denetimi yamalanmaz
        with mock.patch.object(db, "get_session", get_session), mock.patch.object(
            stok_service, "get_session", get_session
        ):
            self.assertFalse(ornek_veri.ornek_veri_var_mi())
            ilk = ornek_veri.ornek_veri_ekle()
            self.assertEqual(ilk, {"cari": len(ornek_veri.ORNEK_CARILER), "stok": len(ornek_veri.ORNEK_URUNLER)})
            self.assertTrue(ornek_veri.ornek_veri_var_mi())
            self.assertEqual(ornek_veri.ornek_veri_ekle(), {"cari": 0, "stok": 0})

            with get_session() as s:
                cariler = s.scalars(select(Cari)).all()
                stoklar = s.scalars(select(StokKarti)).all()
                self.assertEqual(len(cariler), len(ornek_veri.ORNEK_CARILER))
                self.assertEqual(len(stoklar), len(ornek_veri.ORNEK_URUNLER))
                for c in cariler:
                    self.assertTrue(c.unvan.startswith("ÖRNEK VERİ"), c.unvan)
                    self.assertTrue(c.cari_kodu.startswith("ORN-"))
                    self.assertIn("ÖRNEK VERİ", c.ozel_notlar)
                for k in stoklar:
                    self.assertTrue(k.stok_adi.startswith("ÖRNEK VERİ"), k.stok_adi)
                    self.assertTrue(k.stok_kodu.startswith("ORN-"))
                    self.assertEqual(
                        {f.fiyat_adi for f in k.fiyatlar}, {"ALIŞ FİYATI", "SATIŞ FİYATI 1"}
                    )
                lotlar = s.scalars(select(StokLotu)).all()
                self.assertEqual(len(lotlar), len(ornek_veri.ORNEK_URUNLER))
                self.assertTrue(all(l.kalan_miktar == ornek_veri.ORNEK_ACILIS_MIKTARI for l in lotlar))


class TestFirmasiBootstrapTest(unittest.TestCase):
    BILGI = {"unvan": "TEST FİRMASI (Deneme)", "kisa_ad": "Test Firması"}

    def _firmalar(self, system_db):
        eng = create_engine(f"sqlite:///{system_db}")
        try:
            with sessionmaker(bind=eng)() as s:
                return [(f.firma_kodu, f.unvan) for f in s.scalars(select(Company)).all()]
        finally:
            eng.dispose()

    def test_yeni_kurulumda_test_firmasi_olusur(self):
        with tempfile.TemporaryDirectory() as d:
            system_db = Path(d) / "system.db"
            sistem_baslat(system_db, Path(d) / "muhasebe.db", yeni_firma_bilgisi=self.BILGI)
            self.assertEqual(self._firmalar(system_db), [("RAY001", "TEST FİRMASI (Deneme)")])

    def test_mevcut_firma_yeniden_adlandirilmaz(self):
        with tempfile.TemporaryDirectory() as d:
            system_db = Path(d) / "system.db"
            sistem_baslat(system_db, Path(d) / "muhasebe.db")
            sistem_baslat(system_db, Path(d) / "muhasebe.db", yeni_firma_bilgisi=self.BILGI)
            self.assertEqual(self._firmalar(system_db), [("RAY001", RAY_UNVAN)])


class IlkParolaKopyalamaTest(unittest.TestCase):
    PAROLA = "Xy7-kopya-42"

    # Marka görselleri ilk Tk köküne önbelleklenir; testler tek kökü paylaşır
    @classmethod
    def setUpClass(cls):
        import tkinter as tk

        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_giris_ekraninda_parola_kopyalanir_ve_alana_yazilir(self):
        import auth_ui

        with mock.patch.object(auth_ui, "ilk_kurulum_parolasi", return_value=self.PAROLA):
            dlg = auth_ui.GirisDialog(self.root)
        try:
            self.assertEqual(dlg.sifre.get(), self.PAROLA)
            self.assertEqual(dlg.kullanici.get(), "admin")
            self.assertEqual(dlg.ilk_parola_alani.get(), self.PAROLA)
            self.assertEqual(str(dlg.ilk_parola_alani.cget("state")), "readonly")
            dlg.sifre.delete(0, "end")
            dlg._ilk_parolayi_kopyala()
            self.assertEqual(self.root.clipboard_get(), self.PAROLA)
            dlg._ilk_parolayi_yaz()
            self.assertEqual(dlg.sifre.get(), self.PAROLA)
        finally:
            dlg.grab_release()
            dlg.destroy()

    def test_ilk_parola_yokken_alan_yok_otomatik_doldurma_yok(self):
        import auth_ui

        with mock.patch.object(auth_ui, "ilk_kurulum_parolasi", return_value=""):
            dlg = auth_ui.GirisDialog(self.root)
        try:
            self.assertFalse(hasattr(dlg, "ilk_parola_alani"))
            self.assertEqual(dlg.sifre.get(), "")
        finally:
            dlg.grab_release()
            dlg.destroy()

    def test_zorunlu_degisiklikte_mevcut_sifre_hazir_gelir(self):
        import auth_ui

        dlg = auth_ui.SifreDegistirDialog(self.root, zorunlu=True, mevcut_sifre=self.PAROLA)
        try:
            self.assertEqual(dlg.eski.get(), self.PAROLA)
            self.assertEqual(dlg.yeni.get(), "")
        finally:
            dlg.grab_release()
            dlg.destroy()


class IlkKurulumParolasiTest(unittest.TestCase):
    """Gerçek ilk kurulum (sistem_baslat) parolası: göster/doldur yalnız zorunlu değişiklik sürerken."""

    def setUp(self):
        import auth_ui
        from database.session_manager import oturum

        self._tmp = tempfile.TemporaryDirectory()
        d = Path(self._tmp.name)
        self.dosya = d / "ILK_YONETICI_SIFRE.txt"
        sistem_baslat(d / "system.db", d / "muhasebe.db", sifre_dosyasi=self.dosya)
        self.engine = create_engine(f"sqlite:///{d / 'system.db'}")
        Session = sessionmaker(bind=self.engine, expire_on_commit=False)

        @contextmanager
        def get_system_session():
            s = Session()
            try:
                yield s
                s.commit()
            except Exception:
                s.rollback()
                raise
            finally:
                s.close()

        self.oturum_ac = get_system_session
        self._yamalar = [mock.patch.object(auth_ui, "get_system_session", get_system_session),
                         mock.patch.object(db, "DB_DIR", d)]
        for y in self._yamalar:
            y.start()
        self.parola = next(s.split(":", 1)[1].strip() for s in self.dosya.read_text(encoding="utf-8").splitlines()
                           if s.startswith("Parola:"))
        oturum.clear()

    def tearDown(self):
        from database.session_manager import oturum

        for y in self._yamalar:
            y.stop()
        oturum.clear()
        self.engine.dispose()
        self._tmp.cleanup()

    def _giris(self, parola):
        from database.system.auth_service import AuthService

        with self.oturum_ac() as s:
            return AuthService.giris(s, "admin", parola).id

    def test_ilk_giriste_parola_doner_ve_zorunlu_degisiklik_aktif(self):
        import auth_ui
        from database.session_manager import oturum

        self.assertEqual(auth_ui.ilk_kurulum_parolasi(), self.parola)
        self._giris(self.parola)
        self.assertTrue(oturum.sifre_degistirmeli)
        self.assertFalse(auth_ui.ilk_parola_dosyasini_temizle())
        self.assertTrue(self.dosya.exists())

    def test_degistirdikten_sonra_doldurma_yok_eski_parola_gecersiz_dosya_silinir(self):
        import auth_ui
        from database.system.auth_service import AuthService

        uid = self._giris(self.parola)
        with self.oturum_ac() as s:
            AuthService.sifre_degistir(s, uid, self.parola, "Yeni-Parola-2026")
        self.assertEqual(auth_ui.ilk_kurulum_parolasi(), "")
        with self.assertRaises(ValueError):
            self._giris(self.parola)
        self.assertTrue(auth_ui.ilk_parola_dosyasini_temizle())
        self.assertFalse(self.dosya.exists())
        self._giris("Yeni-Parola-2026")

    def test_yonetici_sifresi_sifirlaninca_eski_dosya_parolasi_gosterilmez(self):
        import auth_ui
        from database.system.models import User
        from database.system.password import hash_parola

        with self.oturum_ac() as s:
            admin = s.scalar(select(User).where(User.kullanici_adi == "admin"))
            admin.parola_hash = hash_parola("Sifirlanan-99")
            admin.sifre_degistirmeli = True
        self.assertEqual(auth_ui.ilk_kurulum_parolasi(), "")
        self.assertFalse(auth_ui.ilk_parola_dosyasini_temizle())

    def test_giris_ekrani_yalniz_ilk_kurulumda_otomatik_doldurur(self):
        import tkinter as tk

        import auth_ui
        from database.system.auth_service import AuthService

        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk yok: {exc}")
        root.withdraw()
        gorsel = mock.patch("branding.get_brand_image", return_value=None)
        gorsel.start()
        self.addCleanup(gorsel.stop)
        try:
            dlg = auth_ui.GirisDialog(root)
            self.assertEqual(dlg.sifre.get(), self.parola)
            self.assertEqual(dlg.ilk_parola_alani.get(), self.parola)
            dlg.grab_release()
            dlg.destroy()

            uid = self._giris(self.parola)
            with self.oturum_ac() as s:
                AuthService.sifre_degistir(s, uid, self.parola, "Yeni-Parola-2026")
            dlg = auth_ui.GirisDialog(root)
            self.assertEqual(dlg.sifre.get(), "")
            self.assertFalse(hasattr(dlg, "ilk_parola_alani"))
            dlg.grab_release()
            dlg.destroy()
        finally:
            root.destroy()


class TestKurulumuBayraklariTest(unittest.TestCase):
    def test_giris_ipucu_test_kurulumu_disinda_bos(self):
        import auth_ui

        with mock.patch.object(db, "TEST_KURULUMU", False):
            self.assertEqual(auth_ui.test_kurulumu_giris_ipucu(), "")

    def test_ilk_test_acilisinda_bos_veri_uyarisi_yok(self):
        with mock.patch.multiple(
            db, TEST_KURULUMU=True, SYSTEM_DB_ONCEDEN_VAR=False, MUHASEBE_DB_ONCEDEN_VAR=False
        ):
            self.assertIsNone(db.baslangic_veri_uyarisi())
        with mock.patch.multiple(
            db, TEST_KURULUMU=False, SYSTEM_DB_ONCEDEN_VAR=False, MUHASEBE_DB_ONCEDEN_VAR=False
        ):
            self.assertIsNotNone(db.baslangic_veri_uyarisi())


if __name__ == "__main__":
    unittest.main()
