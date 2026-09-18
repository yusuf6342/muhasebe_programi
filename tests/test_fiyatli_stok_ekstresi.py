"""Fiyatlı Stok Ekstresi — devir, cari, fiyat/maliyet ayrımı.

Çalıştırma: python tests/test_fiyatli_stok_ekstresi.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.fiyatli_stok_ekstresi_service import FiyatliStokEkstreService
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokHareketi, StokKarti, StokLotu
from database.session_manager import oturum


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class FiyatliStokEkstreTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_fiyatli_ekstre.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_masraf  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.cari  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.hizli_satis  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.stok_sayim  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)

        with Session() as s:
            firma = Firma(firma_kodu="FSE", unvan="Fiyatlı Ekstre Test", aktif=True)
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
        company_db._company_id = 91
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
            company_id=91,
            firma_kodu="FSE",
            firma_unvan="Fiyatlı Ekstre Test",
            firma_uid="fse-test",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)

        self._audit = patch("database.user_audit.audit_document", return_value=None)
        self._audit.start()

        with get_session() as s:
            depo = Depo(kod="ANA", ad="ANA DEPO", aktif=True, varsayilan=True)
            s.add(depo)
            ted = Cari(
                cari_kodu="T001",
                unvan="Tedarikçi A.Ş.",
                cari_turu="TEDARİKÇİ",
                aktif=True,
            )
            mus = Cari(
                cari_kodu="M001",
                unvan="Müşteri Ltd.",
                cari_turu="MÜŞTERİ",
                aktif=True,
            )
            s.add_all([ted, mus])
            st = StokKarti(stok_kodu="URUN1", stok_adi="Test Ürün", birim="Adet", aktif=True)
            s.add(st)
            s.flush()
            self.stok_id = int(st.id)
            self.depo_id = int(depo.id)
            self.ted_id = int(ted.id)
            self.mus_id = int(mus.id)

            # Devir öncesi: 100 adet @ 10 TL
            lot = StokLotu(
                stok_id=st.id,
                depo_id=depo.id,
                lot_no="L1",
                giris_tarihi=date(2025, 12, 1),
                kalan_miktar=Decimal("70"),
                birim_maliyet=Decimal("10"),
            )
            s.add(lot)
            s.flush()
            s.add(
                StokHareketi(
                    tarih=date(2025, 12, 1),
                    hareket_turu="FATURA GİRİŞ",
                    belge_no="AF-2025-1",
                    stok_id=st.id,
                    depo_id=depo.id,
                    lot_id=lot.id,
                    miktar=Decimal("100"),
                    birim_maliyet=Decimal("10"),
                    olusturma_tarihi=datetime(2025, 12, 1, 10, 0, 0),
                )
            )
            # Dönem içi satış çıkışı 30 @ maliyet 10, satış fiyatı belgeden
            s.add(
                StokHareketi(
                    tarih=date(2026, 2, 10),
                    hareket_turu="FATURA ÇIKIŞ",
                    belge_no="SF-2026-1",
                    stok_id=st.id,
                    depo_id=depo.id,
                    lot_id=lot.id,
                    miktar=Decimal("30"),
                    birim_maliyet=Decimal("10"),
                    olusturma_tarihi=datetime(2026, 2, 10, 11, 0, 0),
                )
            )
            # Alış girişi 20 @ 12
            s.add(
                StokHareketi(
                    tarih=date(2026, 3, 5),
                    hareket_turu="FATURA GİRİŞ",
                    belge_no="AF-2026-1",
                    stok_id=st.id,
                    depo_id=depo.id,
                    miktar=Decimal("20"),
                    birim_maliyet=Decimal("12"),
                    olusturma_tarihi=datetime(2026, 3, 5, 9, 0, 0),
                )
            )
            # Transfer çıkış/giriş aynı maliyet
            s.add(
                StokHareketi(
                    tarih=date(2026, 4, 1),
                    hareket_turu="TRANSFER ÇIKIŞ",
                    belge_no="TR-1",
                    stok_id=st.id,
                    depo_id=depo.id,
                    miktar=Decimal("5"),
                    birim_maliyet=Decimal("10"),
                    olusturma_tarihi=datetime(2026, 4, 1, 8, 0, 0),
                )
            )
            # Sayım giriş
            s.add(
                StokHareketi(
                    tarih=date(2026, 5, 1),
                    hareket_turu="SAYIM GİRİŞ",
                    belge_no="SY-1",
                    stok_id=st.id,
                    depo_id=depo.id,
                    miktar=Decimal("2"),
                    birim_maliyet=Decimal("10"),
                    olusturma_tarihi=datetime(2026, 5, 1, 8, 0, 0),
                )
            )

        # Faturalar + cari bağlantısı
        from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
        from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri

        with get_session() as s:
            af = AlisFaturasi(
                fatura_no="AF-2026-1",
                fatura_tarihi=date(2026, 3, 5),
                vade_tarihi=date(2026, 4, 5),
                cari_id=self.ted_id,
                durum="AÇIK",
                depo="ANA DEPO",
            )
            s.add(af)
            s.flush()
            s.add(
                AlisFaturasiSatiri(
                    fatura_id=af.id,
                    urun_kodu="URUN1",
                    urun_adi="Test Ürün",
                    miktar=Decimal("20"),
                    birim="Adet",
                    birim_fiyat=Decimal("12"),
                    tl_birim_fiyat=Decimal("12"),
                    fifo_birim_maliyeti=Decimal("12"),
                )
            )
            # Eski alış (devir)
            af0 = AlisFaturasi(
                fatura_no="AF-2025-1",
                fatura_tarihi=date(2025, 12, 1),
                vade_tarihi=date(2026, 1, 1),
                cari_id=self.ted_id,
                durum="AÇIK",
                depo="ANA DEPO",
            )
            s.add(af0)
            s.flush()
            s.add(
                AlisFaturasiSatiri(
                    fatura_id=af0.id,
                    urun_kodu="URUN1",
                    urun_adi="Test Ürün",
                    miktar=Decimal("100"),
                    birim="Adet",
                    birim_fiyat=Decimal("10"),
                    tl_birim_fiyat=Decimal("10"),
                    fifo_birim_maliyeti=Decimal("10"),
                )
            )
            sf = SatisFaturasi(
                fatura_no="SF-2026-1",
                fatura_tarihi=date(2026, 2, 10),
                vade_tarihi=date(2026, 3, 10),
                cari_id=self.mus_id,
                durum="AÇIK",
                onaylandi=True,
                depo="ANA DEPO",
            )
            s.add(sf)
            s.flush()
            s.add(
                SatisFaturasiSatiri(
                    fatura_id=sf.id,
                    urun_kodu="URUN1",
                    urun_adi="Test Ürün",
                    miktar=Decimal("30"),
                    birim="Adet",
                    birim_fiyat=Decimal("25"),
                    tl_birim_fiyat=Decimal("25"),
                    fifo_birim_maliyeti=Decimal("10"),
                )
            )

    def tearDown(self):
        self._audit.stop()
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

    def test_01_devir_ve_yuruyen_kalan(self):
        r = FiyatliStokEkstreService.ekstre(
            self.stok_id,
            baslangic=date(2026, 1, 1),
            bitis=date(2026, 12, 31),
        )
        o = r["ozet"]
        # Devir: 100
        self.assertEqual(o["devir_miktar"], Decimal("100"))
        # Giren dönem: 20 alış + 2 sayım = 22 (transfer çıkış çıkan)
        self.assertEqual(o["giren_miktar"], Decimal("22"))
        self.assertEqual(o["cikan_miktar"], Decimal("35"))  # 30 satış + 5 transfer
        # Kalan: 100 + 22 - 35 = 87
        self.assertEqual(o["kalan_miktar"], Decimal("87"))
        # Devir + giren - çıkan = kalan
        self.assertEqual(
            o["devir_miktar"] + o["giren_miktar"] - o["cikan_miktar"],
            o["kalan_miktar"],
        )
        # İlk satır DEVRİ
        self.assertEqual(r["satirlar"][0]["hareket_turu"], "DEVRİ")
        self.assertEqual(r["satirlar"][0]["kalan"], Decimal("100"))

    def test_02_devir_deger_ve_kalan_deger(self):
        r = FiyatliStokEkstreService.ekstre(
            self.stok_id,
            baslangic=date(2026, 1, 1),
            bitis=date(2026, 12, 31),
        )
        o = r["ozet"]
        # Devir değeri 100*10=1000
        self.assertEqual(o["devir_degeri"], Decimal("1000"))
        # Giriş maliyeti: 20*12 + 2*10 = 260
        self.assertEqual(o["giris_tutari"], Decimal("260"))
        # Çıkış maliyeti: 30*10 + 5*10 = 350
        self.assertEqual(o["cikis_maliyeti"], Decimal("350"))
        # Kalan değer: 1000 + 260 - 350 = 910
        self.assertEqual(o["kalan_stok_degeri"], Decimal("910"))
        self.assertEqual(
            o["devir_degeri"] + o["giris_tutari"] - o["cikis_maliyeti"],
            o["kalan_stok_degeri"],
        )

    def test_03_cari_alis_satis(self):
        r = FiyatliStokEkstreService.ekstre(
            self.stok_id,
            baslangic=date(2026, 1, 1),
            bitis=date(2026, 12, 31),
        )
        satis = next(s for s in r["satirlar"] if s["belge_no"] == "SF-2026-1")
        self.assertEqual(satis["cari_kodu"], "M001")
        self.assertEqual(satis["cari_adi"], "Müşteri Ltd.")
        self.assertEqual(satis["cikis_satis_fiyat"], Decimal("25"))
        self.assertEqual(satis["cikis_maliyet_fiyat"], Decimal("10"))
        alis = next(s for s in r["satirlar"] if s["belge_no"] == "AF-2026-1")
        self.assertEqual(alis["cari_kodu"], "T001")
        self.assertIn("Tedarikçi", alis["cari_adi"])

    def test_04_transfer_cari_bos_sistem(self):
        r = FiyatliStokEkstreService.ekstre(
            self.stok_id,
            baslangic=date(2026, 1, 1),
            bitis=date(2026, 12, 31),
        )
        tr = next(s for s in r["satirlar"] if s["belge_no"] == "TR-1")
        self.assertEqual(tr["cari_kodu"], "")
        self.assertIn("transfer", tr["cari_adi"].lower())

    def test_05_sayim_etiket(self):
        r = FiyatliStokEkstreService.ekstre(
            self.stok_id,
            baslangic=date(2026, 1, 1),
            bitis=date(2026, 12, 31),
        )
        sy = next(s for s in r["satirlar"] if s["belge_no"] == "SY-1")
        self.assertEqual(sy["etiket"], "Sayım")
        self.assertEqual(sy["yon"], "giris")

    def test_06_maliyet_yetkisi_gizle(self):
        with patch.object(FiyatliStokEkstreService, "maliyet_gorunsun_mu", return_value=False):
            r = FiyatliStokEkstreService.ekstre(
                self.stok_id,
                baslangic=date(2026, 1, 1),
                bitis=date(2026, 12, 31),
            )
        self.assertFalse(r["maliyet_gorunur"])
        self.assertIsNone(r["ozet"]["cikis_maliyeti"])
        self.assertIsNone(r["ozet"]["kalan_stok_degeri"])
        satis = next(s for s in r["satirlar"] if s["belge_no"] == "SF-2026-1")
        self.assertIsNone(satis["cikis_maliyet_fiyat"])
        # Ticari satış fiyatı görünür kalmalı
        self.assertEqual(satis["cikis_satis_fiyat"], Decimal("25"))

    def test_07_excel_pdf(self):
        r = FiyatliStokEkstreService.ekstre(
            self.stok_id,
            baslangic=date(2026, 1, 1),
            bitis=date(2026, 12, 31),
        )
        xlsx = Path(self._tmpdir.name) / "ekstre.xlsx"
        pdf = Path(self._tmpdir.name) / "ekstre.pdf"
        FiyatliStokEkstreService.excel_aktar(r, str(xlsx))
        FiyatliStokEkstreService.pdf_aktar(r, str(pdf))
        self.assertTrue(xlsx.exists() and xlsx.stat().st_size > 0)
        self.assertTrue(pdf.exists() and pdf.stat().st_size > 0)

    def test_08_hareket_degismedi_regresyon(self):
        once = None
        with get_session() as s:
            once = s.scalar(select(StokHareketi).where(StokHareketi.belge_no == "SF-2026-1"))
            mid, mm, mc = once.id, once.miktar, once.birim_maliyet
        FiyatliStokEkstreService.ekstre(
            self.stok_id, baslangic=date(2026, 1, 1), bitis=date(2026, 12, 31)
        )
        with get_session() as s:
            sonra = s.get(StokHareketi, mid)
            self.assertEqual(sonra.miktar, mm)
            self.assertEqual(sonra.birim_maliyet, mc)

    def test_09_ui_import(self):
        from fiyatli_stok_ekstresi_ui import FiyatliStokEkstreDialog, fiyatli_stok_ekstresi_goster

        self.assertTrue(callable(FiyatliStokEkstreDialog))
        self.assertTrue(callable(fiyatli_stok_ekstresi_goster))


if __name__ == "__main__":
    unittest.main(verbosity=2)
