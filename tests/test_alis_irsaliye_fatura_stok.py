"""İrsaliye → fatura: stok yalnızca faturada artar; çift hareket olmaz.

Kabul:
1) İrsaliye kaydı StokHareketi üretmez
2) İrsaliyeden faturaya çevirince tek FATURA GİRİŞ oluşur
3) Aynı fatura yeniden kaydedilince (iptal/yeniden) miktar ikiye katlanmaz

Çalıştırma: python tests/test_alis_irsaliye_fatura_stok.py
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

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.session_manager import oturum


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class AlisIrsaliyeFaturaStokTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_alis_stok.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.alis_masraf  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.hizli_satis  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)

        with Session() as s:
            firma = Firma(firma_kodu="ALS", unvan="Alis Stok Test", aktif=True)
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
            s.add(Depo(ad="ANA DEPO", aktif=True))
            s.add(
                StokKarti(
                    stok_kodu="U001",
                    stok_adi="Test Ürün",
                    birim="Adet",
                    aktif=True,
                    is_deleted=False,
                    minimum_stok=Decimal("10"),
                )
            )
            s.add(
                Cari(
                    cari_kodu="T001",
                    unvan="Test Tedarikçi",
                    cari_turu="Tedarikçi",
                    aktif=True,
                )
            )
            s.commit()

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 99
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
            company_id=99,
            firma_kodu="ALS",
            firma_unvan="Alis Stok Test",
            firma_uid="als-test",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)
            self.cari_id = s.scalar(select(Cari.id).where(Cari.cari_kodu == "T001"))

        self._muhasebe_patch = patch(
            "database.muhasebe_entegrasyon.muhasebe_hook",
            lambda *_a, **_k: None,
        )
        self._muhasebe_patch.start()

    def tearDown(self):
        self._muhasebe_patch.stop()
        try:
            company_db.close()
        except Exception:
            pass
        if company_db._engine is not None:
            try:
                company_db._engine.dispose()
            except Exception:
                pass
        company_db._engine = None
        company_db._session_factory = None
        oturum.clear()
        self._tmpdir.cleanup()

    def _hareket_sayisi(self, tur: str | None = None) -> int:
        with get_session() as session:
            q = select(func.count()).select_from(StokHareketi)
            if tur:
                q = q.where(StokHareketi.hareket_turu == tur)
            return int(session.scalar(q) or 0)

    def _lot_miktar(self) -> Decimal:
        with get_session() as session:
            toplam = session.scalar(
                select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0))
            )
            return Decimal(str(toplam or 0))

    def test_irsaliye_stok_artirmaz_fatura_tek_hareket(self):
        from database.alis_irsaliyesi_service import AlisIrsaliyesiService
        from database.alis_faturasi_service import AlisFaturasiService

        irs = AlisIrsaliyesiService.kaydet(
            {
                "irsaliye_tarihi": date(2026, 3, 1),
                "cari_id": self.cari_id,
                "aciklama": None,
            },
            [
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Test Ürün",
                    "miktar": Decimal("5"),
                    "birim": "Adet",
                    "birim_fiyat": Decimal("100"),
                    "iskonto_orani": Decimal("0"),
                    "kdv_orani": Decimal("20"),
                }
            ],
        )
        self.assertEqual(self._hareket_sayisi(), 0)
        self.assertEqual(self._lot_miktar(), Decimal("0"))

        irs_id = int(irs.id)
        irs_yeniden = AlisIrsaliyesiService.getir(irs_id)
        self.assertIsNotNone(irs_yeniden)
        satir = irs_yeniden.satirlar[0]

        fatura = AlisFaturasiService.kaydet(
            {
                "fatura_tarihi": date(2026, 3, 2),
                "vade_tarihi": date(2026, 3, 2),
                "cari_id": self.cari_id,
                "irsaliye_id": irs_id,
                "depo": "ANA DEPO",
                "odeme_tutari": Decimal("0"),
            },
            [
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Test Ürün",
                    "miktar": Decimal("5"),
                    "birim": "Adet",
                    "birim_fiyat": Decimal("100"),
                    "iskonto_orani": Decimal("0"),
                    "kdv_orani": Decimal("20"),
                    "irsaliye_satiri_id": satir.id,
                    "lot_no": "LOT-TEST",
                }
            ],
        )
        self.assertEqual(self._hareket_sayisi("FATURA GİRİŞ"), 1)
        self.assertEqual(self._lot_miktar(), Decimal("5"))

        # Aynı faturayı yeniden kaydet (stok geri al + yeniden gir) → hâlâ tek lot miktarı 5
        AlisFaturasiService.kaydet(
            {
                "fatura_tarihi": date(2026, 3, 2),
                "vade_tarihi": date(2026, 3, 2),
                "cari_id": self.cari_id,
                "irsaliye_id": irs_id,
                "depo": "ANA DEPO",
                "odeme_tutari": Decimal("0"),
                "row_version": int(getattr(fatura, "row_version", 1) or 1),
            },
            [
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Test Ürün",
                    "miktar": Decimal("5"),
                    "birim": "Adet",
                    "birim_fiyat": Decimal("100"),
                    "iskonto_orani": Decimal("0"),
                    "kdv_orani": Decimal("20"),
                    "irsaliye_satiri_id": satir.id,
                    "lot_no": "LOT-TEST",
                }
            ],
            fatura_id=fatura.id,
        )
        self.assertEqual(self._hareket_sayisi("FATURA GİRİŞ"), 1)
        self.assertEqual(self._lot_miktar(), Decimal("5"))

    def test_masraf_fifo_lot_maliyetine_yansir(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.alis_masraf_service import AlisMasrafService

        fatura = AlisFaturasiService.kaydet(
            {
                "fatura_tarihi": date(2026, 4, 1),
                "vade_tarihi": date(2026, 4, 1),
                "cari_id": self.cari_id,
                "depo": "ANA DEPO",
                "odeme_tutari": Decimal("0"),
            },
            [
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Test Ürün",
                    "miktar": Decimal("10"),
                    "birim": "Adet",
                    "birim_fiyat": Decimal("50"),
                    "iskonto_orani": Decimal("0"),
                    "kdv_orani": Decimal("20"),
                    "lot_no": "LOT-M",
                }
            ],
        )
        with get_session() as session:
            lot = session.scalar(select(StokLotu).where(StokLotu.lot_no.like("LOT-M%")))
            self.assertIsNotNone(lot)
            onceki = Decimal(str(lot.birim_maliyet))

        AlisMasrafService.kaydet_ve_dagit(
            fatura.id,
            "NAKLİYE",
            Decimal("100"),
            yontem="MIKTAR",
            maliyete_dahil=True,
        )
        with get_session() as session:
            lot = session.scalar(select(StokLotu).where(StokLotu.lot_no.like("LOT-M%")))
            # 100 / 10 = 10 ek birim maliyet
            self.assertEqual(Decimal(str(lot.birim_maliyet)), onceki + Decimal("10"))

    def test_optimistic_locking_siparis(self):
        from database.alis_siparisi_service import AlisSiparisiService

        siparis = AlisSiparisiService.kaydet(
            {
                "siparis_tarihi": date(2026, 5, 1),
                "termin_tarihi": date(2026, 5, 10),
                "cari_id": self.cari_id,
            },
            [
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Test Ürün",
                    "miktar": Decimal("2"),
                    "birim": "Adet",
                    "birim_alis_fiyati": Decimal("10"),
                    "iskonto_orani": Decimal("0"),
                    "kdv_orani": Decimal("20"),
                }
            ],
            [],
        )
        # Eşzamanlı eski versiyonla kaydet → hata
        with self.assertRaises(ValueError) as ctx:
            AlisSiparisiService.kaydet(
                {
                    "siparis_tarihi": date(2026, 5, 1),
                    "termin_tarihi": date(2026, 5, 10),
                    "cari_id": self.cari_id,
                    "row_version": 0,  # eski
                },
                [
                    {
                        "urun_kodu": "U001",
                        "urun_adi": "Test Ürün",
                        "miktar": Decimal("3"),
                        "birim": "Adet",
                        "birim_alis_fiyati": Decimal("10"),
                        "iskonto_orani": Decimal("0"),
                        "kdv_orani": Decimal("20"),
                    }
                ],
                [],
                siparis_id=siparis.id,
            )
        self.assertIn("değiştirilmiş", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
