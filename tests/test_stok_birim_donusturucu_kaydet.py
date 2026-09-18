"""Birim Dönüştürücü — Kaydet / F1 / doğrulama / transaction.

Çalıştırma: python tests/test_stok_birim_donusturucu_kaydet.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import StokBarkod, StokBirim, StokKarti
from database.session_manager import oturum
from database.stok_service import SATIS_FIYAT_ADLARI, StokService


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class BirimDonusturucuKaydetTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_birim_kaydet.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.cari  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.stok_sayim  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)

        with Session() as s:
            firma = Firma(firma_kodu="BIR", unvan="Birim Test", aktif=True)
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
            s.commit()

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        company_db._company_id = 88
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
            company_id=88,
            firma_kodu="BIR",
            firma_unvan="Birim Test",
            firma_uid="bir-test",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)

        self._audit_patch = patch("database.user_audit.audit_document", return_value=None)
        self._audit_patch.start()

        with get_session() as s:
            st = StokKarti(
                stok_kodu="BK1",
                stok_adi="Birim Kart",
                birim="Adet",
                aktif=True,
                barkod="8690000000001",
            )
            s.add(st)
            s.flush()
            self.stok_id = int(st.id)

    def tearDown(self):
        self._audit_patch.stop()
        try:
            company_db.close()
        except Exception:
            pass
        try:
            if company_db._engine is not None:
                company_db._engine.dispose()
        except Exception:
            pass
        oturum.clear()
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def _birim(
        self,
        ad,
        carpan,
        *,
        barkod="",
        alis="",
        satis=None,
        ref=None,
        ref_c=None,
    ):
        satis = satis or {}
        return {
            "birim_adi": ad,
            "carpan": str(carpan),
            "referans_birim": ref or "Adet",
            "referans_carpan": str(ref_c or carpan),
            "fiyat_modu": "manuel",
            "alis_fiyati": alis,
            "satis_fiyatlari": satis,
            "birim_barkod": barkod,
            "aktif": True,
            "alis_kullanilabilir": True,
            "satis_kullanilabilir": True,
        }

    def test_01_yeni_birim_kaydi(self):
        sonuc = StokService.stok_birimleri_kaydet(
            self.stok_id,
            [
                self._birim(
                    "Koli",
                    "24",
                    barkod="8691111111111",
                    alis="100,50",
                    satis={
                        "SATIŞ FİYATI 1": "150,00",
                        "SATIŞ FİYATI 2": "140",
                        "SATIŞ FİYATI 10": "99,99",
                    },
                )
            ],
        )
        self.assertEqual(sonuc["birim_adet"], 1)
        with get_session() as s:
            st = s.get(StokKarti, self.stok_id)
            self.assertEqual(len(st.birimler), 1)
            b = st.birimler[0]
            self.assertEqual(b.birim_adi, "Koli")
            self.assertEqual(b.carpan, Decimal("24"))
            self.assertEqual(b.birim_barkod, "8691111111111")
            self.assertEqual(b.alis_fiyati, Decimal("100.50"))
            self.assertEqual(b.satis_1, Decimal("150.00"))
            self.assertEqual(b.satis_2, Decimal("140"))
            self.assertEqual(b.satis_10, Decimal("99.99"))

    def test_02_mevcut_birim_guncelleme(self):
        StokService.stok_birimleri_kaydet(
            self.stok_id, [self._birim("Paket", "10", barkod="8692222222222")]
        )
        StokService.stok_birimleri_kaydet(
            self.stok_id,
            [
                self._birim(
                    "Paket",
                    "12",
                    barkod="8692222222222",
                    satis={"SATIŞ FİYATI 1": "55,5"},
                )
            ],
        )
        with get_session() as s:
            st = s.get(StokKarti, self.stok_id)
            self.assertEqual(len(st.birimler), 1)
            self.assertEqual(st.birimler[0].carpan, Decimal("12"))
            self.assertEqual(st.birimler[0].satis_1, Decimal("55.5"))

    def test_03_mukerrer_birim_engeli(self):
        with self.assertRaises(ValueError) as ctx:
            StokService.stok_birimleri_kaydet(
                self.stok_id,
                [
                    self._birim("Koli", "24"),
                    self._birim("koli", "48"),
                ],
            )
        self.assertIn("birden fazla", str(ctx.exception).lower())
        with get_session() as s:
            st = s.get(StokKarti, self.stok_id)
            self.assertEqual(len(st.birimler), 0)

    def test_04_mukerrer_barkod_baska_stok(self):
        with get_session() as s:
            s.add(
                StokKarti(
                    stok_kodu="BK2",
                    stok_adi="Diğer",
                    birim="Adet",
                    aktif=True,
                    barkod="8693333333333",
                )
            )
        with self.assertRaises(ValueError) as ctx:
            StokService.stok_birimleri_kaydet(
                self.stok_id,
                [self._birim("Koli", "24", barkod="8693333333333")],
            )
        self.assertIn("barkod", str(ctx.exception).lower())

    def test_05_mukerrer_barkod_ayni_stok_ana(self):
        with self.assertRaises(ValueError):
            StokService.stok_birimleri_kaydet(
                self.stok_id,
                [self._birim("Koli", "24", barkod="8690000000001")],
            )

    def test_06_ana_birim_katsayi_1(self):
        with self.assertRaises(ValueError) as ctx:
            StokService.stok_birimleri_kaydet(
                self.stok_id,
                [self._birim("Adet", "2")],
            )
        self.assertIn("1 olmalıdır", str(ctx.exception))

    def test_07_gecersiz_katsayi(self):
        with self.assertRaises(ValueError):
            StokService.stok_birimleri_kaydet(
                self.stok_id,
                [self._birim("Koli", "0")],
            )
        with self.assertRaises(ValueError):
            StokService.stok_birimleri_kaydet(
                self.stok_id,
                [self._birim("Koli", "-5")],
            )

    def test_08_negatif_satis_fiyati(self):
        with self.assertRaises(ValueError) as ctx:
            StokService.stok_birimleri_kaydet(
                self.stok_id,
                [
                    self._birim(
                        "Koli",
                        "24",
                        satis={"SATIŞ FİYATI 3": "-10"},
                    )
                ],
            )
        self.assertIn("negatif", str(ctx.exception).lower())

    def test_09_satis_fiyat_1_10_korunur(self):
        satis = {ad: str(i + 1) for i, ad in enumerate(SATIS_FIYAT_ADLARI)}
        StokService.stok_birimleri_kaydet(
            self.stok_id, [self._birim("Torba", "100", satis=satis)]
        )
        with get_session() as s:
            b = s.scalar(select(StokBirim).where(StokBirim.stok_id == self.stok_id))
            for i in range(1, 11):
                self.assertEqual(getattr(b, f"satis_{i}"), Decimal(str(i)))

    def test_10_transaction_geri_al(self):
        StokService.stok_birimleri_kaydet(
            self.stok_id, [self._birim("Paket", "10")]
        )
        with self.assertRaises(ValueError):
            StokService.stok_birimleri_kaydet(
                self.stok_id,
                [
                    self._birim("Paket", "10"),
                    self._birim("Koli", "-1"),
                ],
            )
        with get_session() as s:
            st = s.get(StokKarti, self.stok_id)
            self.assertEqual(len(st.birimler), 1)
            self.assertEqual(st.birimler[0].birim_adi, "Paket")

    def test_11_stok_id_zorunlu(self):
        with self.assertRaises(ValueError):
            StokService.stok_birimleri_kaydet(0, [self._birim("Koli", "24")])

    def test_12_silinmis_stok_engeli(self):
        with get_session() as s:
            st = s.get(StokKarti, self.stok_id)
            st.is_deleted = True
        with self.assertRaises(ValueError):
            StokService.stok_birimleri_kaydet(
                self.stok_id, [self._birim("Koli", "24")]
            )

    def test_13_turkce_ondalik(self):
        StokService.stok_birimleri_kaydet(
            self.stok_id,
            [self._birim("Kg", "1.250,5", alis="1.234,56")],
        )
        with get_session() as s:
            b = s.scalar(select(StokBirim).where(StokBirim.stok_id == self.stok_id))
            self.assertEqual(b.carpan, Decimal("1250.5"))
            self.assertEqual(b.alis_fiyati, Decimal("1234.56"))


class BirimDonusturucuUiTest(unittest.TestCase):
    """UI yardımcıları — Tk penceresi açmadan."""

    def test_f1_unbind_destroy(self):
        from stok_ui import StokBirimlerDialog

        self.assertTrue(callable(StokBirimlerDialog.destroy))
        self.assertTrue(callable(StokBirimlerDialog._f1_kaydet))
        self.assertTrue(callable(StokBirimlerDialog.kaydet))
        self.assertTrue(callable(StokBirimlerDialog._kapat_istegi))

    def test_kayit_kilit_mukerrer(self):
        """Art arda kayıt çağrısı ikinci kez işlem yapmaz."""
        dlg = MagicMock()
        dlg._kayit_devam = False
        dlg._f1_kilit = False
        dlg._kapatiliyor = False
        dlg.btn_kaydet = MagicMock()
        dlg.btn_kaydet.cget.return_value = "normal"

        from stok_ui import StokBirimlerDialog

        self.assertTrue(StokBirimlerDialog._kayit_aktif_mi(dlg))
        dlg._kayit_devam = True
        self.assertFalse(StokBirimlerDialog._kayit_aktif_mi(dlg))
        dlg._kayit_devam = False
        dlg._f1_kilit = True
        self.assertFalse(StokBirimlerDialog._kayit_aktif_mi(dlg))

    def test_diger_ekran_f1_metotlari_mevcut(self):
        """Diğer ekranların F1 bağları bozulmamış (metotlar duruyor)."""
        from alis_ui import AlisFaturasiDialog
        from cari_kart_ui import CariDialog
        from depo_transfer_ui import DepoTransferFisiDialog

        self.assertTrue(hasattr(AlisFaturasiDialog, "_f1_kaydet"))
        self.assertTrue(hasattr(CariDialog, "_f1_kaydet"))
        self.assertTrue(hasattr(DepoTransferFisiDialog, "_f1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
