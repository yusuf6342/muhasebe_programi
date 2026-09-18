"""Stok birleştirme — hareket/lot aktarımı ve soft-delete testleri.

Kabul:
1) Hedef 100 + kaynak net 50 → hedef 150
2) Kaynak hareketleri hedef stock_id altında
3) Lot bakiyesi hareketlerle tutarlı
4) Aynı stok / tekrar birleştirme reddedilir
5) Belge snapshot (urun_kodu) değişmez
6) Hard-delete yok (delete-orphan lot kaybı yok)

Çalıştırma: python tests/test_stok_birlestir.py
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

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, DepoTransferFisi, DepoTransferFisiSatiri, StokHareketi, StokKarti, StokLotu
from database.session_manager import oturum
from database.stok_service import StokService


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class StokBirlestirTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_birlestir.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.deleted_record  # noqa: F401
        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.hizli_satis  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)

        with Session() as s:
            firma = Firma(firma_kodu="BRL", unvan="Birlestir Test", aktif=True)
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
            d1 = Depo(ad="Merkez", aktif=True)
            d2 = Depo(ad="Şube", aktif=True)
            s.add_all([d1, d2])
            s.flush()

            hedef = StokKarti(
                stok_kodu="H100",
                stok_adi="Hedef Ürün",
                birim="Adet",
                aktif=True,
                is_deleted=False,
            )
            kaynak = StokKarti(
                stok_kodu="K050",
                stok_adi="Kaynak Ürün",
                birim="Adet",
                aktif=True,
                is_deleted=False,
            )
            s.add_all([hedef, kaynak])
            s.flush()

            # Hedef: 100 adet (tek lot)
            s.add(
                StokLotu(
                    stok_id=hedef.id,
                    depo_id=d1.id,
                    lot_no="H-L1",
                    giris_tarihi=date(2026, 1, 1),
                    kalan_miktar=Decimal("100"),
                    birim_maliyet=Decimal("10"),
                )
            )
            s.add(
                StokHareketi(
                    stok_id=hedef.id,
                    depo_id=d1.id,
                    miktar=Decimal("100"),
                    birim_maliyet=Decimal("10"),
                    hareket_turu="GİRİŞ",
                    belge_no="H-G1",
                    tarih=date(2026, 1, 1),
                )
            )

            # Kaynak: 80 giriş / 30 çıkış → net 50 (iki depo)
            s.add(
                StokLotu(
                    stok_id=kaynak.id,
                    depo_id=d1.id,
                    lot_no="K-L1",
                    giris_tarihi=date(2026, 2, 1),
                    kalan_miktar=Decimal("30"),
                    birim_maliyet=Decimal("8"),
                )
            )
            s.add(
                StokLotu(
                    stok_id=kaynak.id,
                    depo_id=d2.id,
                    lot_no="K-L2",
                    giris_tarihi=date(2026, 2, 2),
                    kalan_miktar=Decimal("20"),
                    birim_maliyet=Decimal("9"),
                )
            )
            s.add(
                StokHareketi(
                    stok_id=kaynak.id,
                    depo_id=d1.id,
                    miktar=Decimal("50"),
                    birim_maliyet=Decimal("8"),
                    hareket_turu="GİRİŞ",
                    belge_no="K-G1",
                    tarih=date(2026, 2, 1),
                )
            )
            s.add(
                StokHareketi(
                    stok_id=kaynak.id,
                    depo_id=d2.id,
                    miktar=Decimal("30"),
                    birim_maliyet=Decimal("9"),
                    hareket_turu="GİRİŞ",
                    belge_no="K-G2",
                    tarih=date(2026, 2, 2),
                )
            )
            s.add(
                StokHareketi(
                    stok_id=kaynak.id,
                    depo_id=d1.id,
                    miktar=Decimal("20"),
                    birim_maliyet=Decimal("8"),
                    hareket_turu="ÇIKIŞ",
                    belge_no="K-C1",
                    tarih=date(2026, 2, 10),
                )
            )
            s.add(
                StokHareketi(
                    stok_id=kaynak.id,
                    depo_id=d2.id,
                    miktar=Decimal("10"),
                    birim_maliyet=Decimal("9"),
                    hareket_turu="ÇIKIŞ",
                    belge_no="K-C2",
                    tarih=date(2026, 2, 11),
                )
            )

            # Geçmiş belge satırı — snapshot korunmalı
            fis = DepoTransferFisi(
                fis_no="TRF-TEST-1",
                fis_tarihi=date(2026, 2, 5),
                cikis_depo="Merkez",
                giris_depo="Şube",
                genel_toplam=Decimal("1"),
            )
            s.add(fis)
            s.flush()
            s.add(
                DepoTransferFisiSatiri(
                    fis_id=fis.id,
                    urun_kodu="K050",
                    urun_adi="Kaynak Ürün Eski Ad",
                    birim="Koli",
                    miktar=Decimal("1"),
                    birim_fiyat=Decimal("100"),
                    tutar=Decimal("100"),
                )
            )
            s.commit()
            self.hedef_id = int(hedef.id)
            self.kaynak_id = int(kaynak.id)
            self.depo1_id = int(d1.id)
            self.depo2_id = int(d2.id)

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
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
            firma_kodu="BRL",
            firma_unvan="Birlestir Test",
            firma_uid="brl-test",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)

        self._audit_patch = patch(
            "database.deleted_record_service.safe_log_cancel_snapshot",
            return_value=None,
        )
        self._audit_patch.start()

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

    def test_01_onizleme_beklenen_miktar(self):
        o = StokService.stok_birlestir_onizleme(self.kaynak_id, self.hedef_id)
        self.assertEqual(o["kaynak_toplam_giris"], Decimal("80"))
        self.assertEqual(o["kaynak_toplam_cikis"], Decimal("30"))
        self.assertEqual(o["kaynak_net"], Decimal("50"))
        self.assertEqual(o["hedef_mevcut"], Decimal("100"))
        self.assertEqual(o["beklenen_hedef_miktar"], Decimal("150"))
        self.assertEqual(o["hareket_adet"], 4)
        self.assertGreaterEqual(o["belge_satir_adet"], 1)
        self.assertEqual(o["depo_adet"], 2)

    def test_02_birlestirme_miktar_ve_hareket(self):
        sonuc = StokService.stok_birlestir(
            self.kaynak_id, self.hedef_id, gerekce="Test birleştirme"
        )
        self.assertEqual(sonuc["hedef_miktar_once"], Decimal("100"))
        self.assertEqual(sonuc["hedef_miktar_sonra"], Decimal("150"))
        self.assertEqual(sonuc["aktarilan_giris"], Decimal("80"))
        self.assertEqual(sonuc["aktarilan_cikis"], Decimal("30"))
        self.assertEqual(sonuc["hareket"], 4)
        self.assertEqual(sonuc["kaynak_durum"], "pasif_soft_delete")

        with get_session() as s:
            kaynak = s.get(StokKarti, self.kaynak_id)
            self.assertIsNotNone(kaynak)
            self.assertTrue(kaynak.is_deleted)
            self.assertFalse(kaynak.aktif)
            self.assertEqual(kaynak.birlestirildi_hedef_id, self.hedef_id)

            kalan_kaynak_h = s.scalar(
                select(StokHareketi).where(StokHareketi.stok_id == self.kaynak_id).limit(1)
            )
            self.assertIsNone(kalan_kaynak_h)

            hedef_hareketler = list(
                s.scalars(select(StokHareketi).where(StokHareketi.stok_id == self.hedef_id)).all()
            )
            self.assertEqual(len(hedef_hareketler), 5)  # 1 hedef + 4 kaynak

            lot_toplam = sum(
                (l.kalan_miktar for l in s.scalars(
                    select(StokLotu).where(StokLotu.stok_id == self.hedef_id)
                ).all()),
                Decimal("0"),
            )
            self.assertEqual(lot_toplam, Decimal("150"))

            # Depo bazlı
            d1 = sum(
                (
                    l.kalan_miktar
                    for l in s.scalars(
                        select(StokLotu).where(
                            StokLotu.stok_id == self.hedef_id,
                            StokLotu.depo_id == self.depo1_id,
                        )
                    ).all()
                ),
                Decimal("0"),
            )
            d2 = sum(
                (
                    l.kalan_miktar
                    for l in s.scalars(
                        select(StokLotu).where(
                            StokLotu.stok_id == self.hedef_id,
                            StokLotu.depo_id == self.depo2_id,
                        )
                    ).all()
                ),
                Decimal("0"),
            )
            self.assertEqual(d1, Decimal("130"))  # 100 + 30
            self.assertEqual(d2, Decimal("20"))

            # Belge snapshot bozulmamalı
            satir = s.scalar(
                select(DepoTransferFisiSatiri).where(DepoTransferFisiSatiri.urun_kodu == "K050")
            )
            self.assertIsNotNone(satir)
            self.assertEqual(satir.urun_adi, "Kaynak Ürün Eski Ad")
            self.assertEqual(satir.birim, "Koli")

        ozet = StokService.stok_ozeti(self.hedef_id)
        self.assertEqual(ozet["kalan"], Decimal("150"))
        self.assertEqual(ozet["toplam_giris"], Decimal("180"))
        self.assertEqual(ozet["toplam_cikis"], Decimal("30"))

    def test_03_ayni_stok_ve_idempotent(self):
        with self.assertRaises(ValueError):
            StokService.stok_birlestir(self.hedef_id, self.hedef_id)

        StokService.stok_birlestir(self.kaynak_id, self.hedef_id)
        with self.assertRaises(ValueError):
            StokService.stok_birlestir(self.kaynak_id, self.hedef_id)

        # İkinci çağrı miktarı bozmamalı
        ozet = StokService.stok_ozeti(self.hedef_id)
        self.assertEqual(ozet["kalan"], Decimal("150"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
