"""Alış faturası penceresi açılmalı; TOPLAMLAR sabit alt bantta görünmeli."""

from __future__ import annotations

import sys
import tempfile
import tkinter as tk
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import importlib
import pkgutil

import database.models

for _m in pkgutil.iter_modules(database.models.__path__):
    importlib.import_module(f"database.models.{_m.name}")

from database.database import Base, _aktif_engine_bagla, company_db
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.finans import FinansHesabi
from database.models.firma import Firma
from database.models.stok import Depo
from database.session_manager import oturum


class AlisFaturasiAcilisTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        path = Path(self._tmpdir.name) / "alis.db"
        self.db_path = path
        Session = sessionmaker(bind=None, expire_on_commit=False)
        eng = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
        Session.configure(bind=eng)
        Base.metadata.create_all(eng)
        with Session() as s:
            firma = Firma(firma_kodu="ALS", unvan="Alış Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="2026",
                    baslangic_tarihi=date(2026, 1, 1),
                    bitis_tarihi=date(2026, 12, 31),
                    aktif=True,
                    kapali=False,
                    varsayilan=True,
                )
            )
            s.add(FinansHesabi(hesap_adi="KASA", hesap_turu="KASA", aktif=True))
            s.add(Depo(ad="ANA DEPO", aktif=True))
            s.add(Cari(cari_kodu="T0001", unvan="Tedarikçi Test", cari_turu="Tedarikçi", aktif=True))
            from database.models.stok import StokKarti

            s.add(StokKarti(stok_kodu="A", stok_adi="1", birim="Adet", aktif=True, is_deleted=False))
            s.commit()
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = str(path)
        oturum.set_user(
            user_id=1,
            kullanici_adi="test",
            ad_soyad="Test",
            role_kod="YONETICI",
            role_ad="YONETICI",
            permissions=set(),
        )
        oturum.set_company(company_id=1, firma_kodu="ALS", firma_unvan="Alış Test", firma_uid="x", db_path=str(path))
        with Session() as s:
            d = s.query(Donem).first()
            if d is not None:
                oturum.set_period(d.id, d.donem_adi)
        self._eng = eng
        self._Session = Session

    def tearDown(self):
        try:
            company_db.close()
        except Exception:
            pass
        company_db._engine = None
        company_db._session_factory = None
        try:
            oturum.clear()
        except Exception:
            pass
        try:
            self._eng.dispose()
        except Exception:
            pass
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def test_pencere_acilir_toplamlar_alt_bantta(self):
        from alis_ui import AlisFaturasiDialog
        from decimal import Decimal

        root = tk.Tk()
        root.withdraw()
        try:
            dlg = AlisFaturasiDialog(root)
            dlg.update_idletasks()
            toplam = dlg._alis_toplam_cerceve
            alt = dlg._alis_sticky_alt
            # Gerçek ebeveyn zinciri: toplam → sticky_alt → dialog (pack(in_=) yok)
            self.assertIs(toplam.master, alt)
            self.assertIs(alt.master, dlg)
            self.assertEqual(toplam.winfo_manager(), "pack")
            self.assertEqual(alt.winfo_manager(), "pack")
            self.assertEqual(alt.pack_info()["side"], "bottom")
            self.assertGreater(toplam.winfo_reqheight(), 0)
            self.assertGreater(alt.winfo_reqheight(), 0)
            # Canvas kaydırma kaldırıldı — orta alan doğrudan expand
            self.assertIsNone(getattr(dlg, "canvas", object()))
            # Örnek iki satır %20 KDV: Ara 73,50 / KDV 14,70 / Net 88,20
            dlg.satirlar = [
                {
                    "urun_kodu": "A", "urun_adi": "1", "miktar": "1", "birim": "Adet",
                    "birim_fiyat": "65", "iskonto_orani": "0", "iskonto_orani_2": "0",
                    "iskonto_orani_3": "0", "kdv_orani": "20",
                },
                {
                    "urun_kodu": "B", "urun_adi": "2", "miktar": "1", "birim": "Adet",
                    "birim_fiyat": "8.5", "iskonto_orani": "0", "iskonto_orani_2": "0",
                    "iskonto_orani_3": "0", "kdv_orani": "20",
                },
            ]
            dlg._toplamlari_guncelle()
            self.assertEqual(dlg._alis_satir_brut, Decimal("73.5"))
            self.assertEqual(dlg._alis_net_toplam, Decimal("88.2"))
            self.assertIn("88", dlg._alis_net_lbl.cget("text"))
            # Toplam yenileme formu kirli saymaz
            self.assertFalse(dlg._fatura_form_kirli)
            self.assertTrue(dlg.winfo_exists())
            dlg.destroy()
        finally:
            root.destroy()

    def test_kapat_evet_tek_soru_tek_kayit(self):
        """Evet → tek kayıt, tek çıkış; soru döngüsü yok."""
        from alis_ui import AlisFaturasiDialog, _tedarikci_ekle
        from database.alis_faturasi_service import AlisFaturasiService
        import tkinter.messagebox as mb

        root = tk.Tk()
        root.withdraw()
        ask_n = {"n": 0}
        kaydet_n = {"n": 0}
        eski_ask = mb.askyesnocancel
        eski_err = mb.showerror
        hatalar = []

        def _ask(*_a, **_k):
            ask_n["n"] += 1
            self.assertLessEqual(ask_n["n"], 1, "Kaydetme sorusu tekrarlandı")
            return True

        def _err(title, msg, **_k):
            hatalar.append((title, str(msg)))

        mb.askyesnocancel = _ask
        mb.showerror = _err
        try:
            dlg = AlisFaturasiDialog(root)
            for c in AlisFaturasiService.aktif_tedarikcileri():
                _tedarikci_ekle(dlg.tedarikci_map, c)
            tedarikciler = list(dlg.tedarikci_map.values())
            self.assertTrue(tedarikciler)
            dlg._tedarikci_sec(tedarikciler[0])
            dlg.satirlar = [
                {
                    "urun_kodu": "A", "urun_adi": "1", "miktar": "1", "birim": "Adet",
                    "birim_fiyat": "65", "birim_alis_fiyati": "65",
                    "iskonto_orani": "0", "iskonto_orani_2": "0", "iskonto_orani_3": "0",
                    "kdv_orani": "20",
                },
            ]
            dlg._satir_listesini_yenile()
            dlg._fatura_form_kirli = True
            orig = dlg._kaydet_kapatmadan

            def _kaydet(*, kapatirken=False):
                kaydet_n["n"] += 1
                return orig(kapatirken=kapatirken)

            dlg._kaydet_kapatmadan = _kaydet
            dlg.kapat_istegi()
            self.assertEqual(hatalar, [], msg=str(hatalar))
            self.assertEqual(ask_n["n"], 1)
            self.assertEqual(kaydet_n["n"], 1)
            self.assertFalse(dlg.winfo_exists())
            self.assertIsNotNone(dlg.result)
            self.assertIsNotNone(getattr(dlg.result, "id", None))
        finally:
            mb.askyesnocancel = eski_ask
            mb.showerror = eski_err
            try:
                root.destroy()
            except tk.TclError:
                pass


if __name__ == "__main__":
    unittest.main()
