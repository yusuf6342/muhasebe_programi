"""Satış faturası kartı UI smoke — geçici DB, dialog aç/kapat, taslak kaydet."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db
from database.models.cari import Cari, MusteriGrubu
from database.models.donem import Donem
from database.models.finans import FinansHesabi
from database.models.firma import Firma
from database.models.stok import Depo, StokKarti
from database.session_manager import oturum


def _sqlite_pragma(dbapi_conn, _connection_record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class SatisFaturaKartSmokeTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "fatura_kart.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.doviz  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        with Session() as s:
            firma = Firma(firma_kodu="SFT", unvan="Satış Fatura Test", aktif=True)
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
            s.add(FinansHesabi(hesap_adi="ANA KASA", hesap_turu="KASA", aktif=True))
            s.add(MusteriGrubu(ad="Genel"))
            s.add(Depo(ad="ANA DEPO", aktif=True))
            cari = Cari(
                cari_kodu="M2001",
                unvan="Fatura Smoke Müşteri",
                cari_turu="Müşteri",
                aktif=True,
            )
            s.add(cari)
            stok = StokKarti(
                stok_kodu="U2001",
                stok_adi="Smoke Ürün",
                birim="Adet",
                aktif=True,
                kdv_orani=Decimal("20"),
            )
            s.add(stok)
            s.commit()
            self.cari_id = int(cari.id)

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = self.db_path

        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Test Admin",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="SFT",
            firma_unvan="Satış Fatura Test",
            firma_uid="sft-test",
            db_path=str(self.db_path),
        )
        oturum.set_period(1, "2026")

    def tearDown(self):
        oturum.clear()
        try:
            company_db.close()
        except Exception:
            pass
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def test_dialog_acilis_ve_toolbar(self):
        import tkinter as tk
        from database.cari_service import CariService
        from app import SatisFaturasiDialog

        root = tk.Tk()
        root.withdraw()
        cari = CariService.getir(self.cari_id)
        dlg = SatisFaturasiDialog(root, cari=cari)
        try:
            self.assertTrue(hasattr(dlg, "_fatura_toolbar"))
            self.assertTrue(hasattr(dlg, "_fatura_alt_ozet"))
            self.assertEqual(dlg.title(), "Satış Faturası")
            self.assertIsNotNone(getattr(dlg, "kaydet_btn", None))
            self.assertIsNotNone(getattr(dlg, "kaydet_onay_btn", None))
            # Durum rozeti TASLAK
            rozet = dlg._fatura_toolbar.get("rozet")
            self.assertEqual(rozet.cget("text"), "TASLAK")
            # Alt özet GENEL TOPLAM (salt okunur etiket)
            genel = dlg.fatura_toplam_degerleri.get("genel")
            self.assertIsNotNone(genel)
            # Kısayol bağları
            self.assertTrue(bool(dlg.bind("<Escape>")))
            self.assertTrue(bool(dlg.bind("<F4>")))
        finally:
            try:
                dlg.destroy()
            except tk.TclError:
                pass
            root.destroy()

    def test_taslak_kaydet_servis(self):
        from database.satis_faturasi_service import SatisFaturasiService

        veriler = {
            "fatura_no": SatisFaturasiService.fatura_no(),
            "fatura_tarihi": date.today(),
            "islem_saati": "12:00",
            "vade_tarihi": date.today(),
            "cari_id": self.cari_id,
            "depo": "ANA DEPO",
            "tahsilat_tutari": Decimal("0"),
            "aciklama": "smoke",
        }
        satirlar = [
            {
                "urun_kodu": "U2001",
                "urun_adi": "Smoke Ürün",
                "miktar": Decimal("2"),
                "birim": "Adet",
                "birim_fiyat": Decimal("100"),
                "iskonto_orani": Decimal("0"),
                "kdv_orani": Decimal("20"),
            }
        ]
        f = SatisFaturasiService.kaydet(veriler, satirlar)
        self.assertIsNotNone(f.id)
        self.assertFalse(getattr(f, "onaylandi", False))
        getir = SatisFaturasiService.getir(f.id)
        self.assertEqual(getir.fatura_no, veriler["fatura_no"])


if __name__ == "__main__":
    unittest.main()
