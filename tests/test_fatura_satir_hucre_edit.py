"""Satış faturası satır içi miktar / fiyat düzenleme regresyonu.

.venv\\Scripts\\python.exe -m unittest tests.test_fatura_satir_hucre_edit -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla
from database.models.cari import Cari, MusteriGrubu
from database.models.donem import Donem
from database.models.finans import FinansHesabi
from database.models.firma import Firma
from database.models.stok import Depo, StokKarti
from database.session_manager import oturum


def _pragma(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class FaturaSatirHucreEditTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        path = Path(self._tmpdir.name) / "hucre.db"
        eng = create_engine(
            f"sqlite:///{path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.doviz  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="HCR", unvan="Hucre", aktif=True)
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
            s.add(MusteriGrubu(ad="Genel"))
            s.add(Depo(ad="ANA DEPO", aktif=True))
            s.add(Cari(cari_kodu="M001", unvan="Test Müşteri", cari_turu="Müşteri", aktif=True))
            s.add(StokKarti(stok_kodu="U001", stok_adi="Test Ürün", birim="Adet", aktif=True))
            s.commit()
        _aktif_engine_bagla(eng)
        oturum.set_company(
            company_id=1, firma_kodu="HCR", firma_unvan="Hucre", firma_uid="x", db_path=str(path)
        )

        import tkinter as tk
        from app import SatisFaturasiDialog

        self.root = tk.Tk()
        self.root.withdraw()
        self._yamalar = [
            patch("satis_personeli_ui.aktif_satis_personelleri", return_value=[]),
            patch("satis_personeli_ui.satis_personeli_degistirme_yetkisi", return_value=True),
            patch("fatura_acilis_cache.satis_personelleri", return_value=[]),
            patch("fatura_manuel_fiyat_ui.fiyat_degistirme_yetkisi", return_value=True),
            patch("fatura_manuel_fiyat_ui.maliyet_alti_kontrol", return_value=True),
        ]
        for y in self._yamalar:
            y.start()
        self.dlg = SatisFaturasiDialog(self.root)
        self.dlg.geometry("1400x800+-3000+-3000")
        self.dlg.satirlar = [
            {
                "urun_kodu": "U001",
                "urun_adi": "Test Ürün",
                "miktar": "2",
                "birim": "Adet",
                "birim_satis_fiyati": "10",
                "kdv_orani": "20",
                "iskonto_orani": "0",
                "iskonto_orani_2": "0",
                "iskonto_orani_3": "0",
                "satir_para_birimi": "TRY",
                "kur": "1",
            }
        ]
        self.dlg._satir_listesini_yenile()
        self._pompala()

    def tearDown(self):
        try:
            self.dlg.destroy()
        except Exception:
            pass
        for y in self._yamalar:
            y.stop()
        try:
            self.root.destroy()
        except Exception:
            pass
        try:
            from database.database import engine

            if engine is not None:
                engine.dispose()
        except Exception:
            pass
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def _pompala(self, tur: int = 6):
        for _ in range(tur):
            self.dlg.update_idletasks()
            self.dlg.update()

    def _editor_ac_ve_yaz(self, fonk, deger: str):
        fonk(self.dlg, idx=0)
        self._pompala()
        editor = getattr(self.dlg, "_satir_hucre_editor", None)
        self.assertIsNotNone(editor, "Hücre editörü açıldıktan hemen sonra kapandı")
        self.assertTrue(editor.winfo_exists())
        editor.delete(0, "end")
        editor.insert(0, deger)
        editor.event_generate("<Return>")
        self._pompala()

    def test_miktar_guncellenir(self):
        from fatura_satir_hucre_edit import miktar_hucre_duzenle

        self._editor_ac_ve_yaz(miktar_hucre_duzenle, "5")
        self.assertEqual(Decimal(self.dlg.satirlar[0]["miktar"]), Decimal("5"))
        self.assertEqual(self.dlg.satir_tablosu.set("0", "miktar").strip(), "5")

    def test_fiyat_guncellenir_ve_toplam_degisir(self):
        from fatura_satir_hucre_edit import fiyat_hucre_duzenle

        self._editor_ac_ve_yaz(fiyat_hucre_duzenle, "12,50")
        self.assertEqual(Decimal(self.dlg.satirlar[0]["birim_satis_fiyati"]), Decimal("12.50"))
        # 2 x 12,50 = 25,00 + %20 KDV = 30,00
        self.assertEqual(self.dlg._hesaplanan_genel, Decimal("30.00"))

    def test_miktar_editoru_yeniden_cizimde_kapanmaz(self):
        from fatura_satir_hucre_edit import miktar_hucre_duzenle

        miktar_hucre_duzenle(self.dlg, idx=0)
        self._pompala()
        self.dlg._fatura_satir_vurgulu_overlay_ciz()
        self._pompala()
        editor = getattr(self.dlg, "_satir_hucre_editor", None)
        self.assertIsNotNone(editor)
        self.assertTrue(editor.winfo_exists())
        self.assertTrue(editor.winfo_ismapped())

    def test_vurgulu_miktar_etiketine_tek_tik_editor_acar(self):
        import time

        self.dlg._fatura_satir_vurgulu_overlay_ciz()
        self._pompala()
        bb = self.dlg.satir_tablosu.bbox("0", "miktar")
        self.assertTrue(bb)
        etiket = next(
            (
                w
                for w in self.dlg._vurgulu_overlayler
                if int(w.place_info().get("x", -1)) == bb[0]
            ),
            None,
        )
        self.assertIsNotNone(etiket)
        etiket.event_generate("<Button-1>", x=2, y=2)
        bitis = time.time() + 1.0
        while time.time() < bitis and getattr(self.dlg, "_satir_hucre_editor", None) is None:
            self._pompala(1)
        self._pompala()
        editor = getattr(self.dlg, "_satir_hucre_editor", None)
        self.assertIsNotNone(editor)
        editor.delete(0, "end")
        editor.insert(0, "7")
        editor.event_generate("<Return>")
        self._pompala()
        self.assertEqual(Decimal(self.dlg.satirlar[0]["miktar"]), Decimal("7"))


if __name__ == "__main__":
    unittest.main()
