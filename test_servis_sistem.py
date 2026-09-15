"""Servis ve Sistem Kontrol Merkezi — Aşama 4–6 birim testleri.

Çalıştırma: python -m pytest test_servis_sistem.py -q
veya: python test_servis_sistem.py -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db
from database.session_manager import oturum


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class ServisSistemTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_servis.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.firma  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.hizmet  # noqa: F401
        import database.models.hizmet_faturasi  # noqa: F401
        import database.models.kk_cekimi  # noqa: F401
        import database.models.deleted_record  # noqa: F401
        import database.models.cek_senet  # noqa: F401
        import database.models.genel_muhasebe  # noqa: F401
        import database.servis_sistem.models  # noqa: F401

        Base.metadata.create_all(eng)
        _aktif_engine_bagla(eng)
        self.engine = eng
        self.Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )

        from database import database as dbmod

        dbmod.SessionLocal = self.Session

        company_db._engine = eng
        company_db._session_factory = self.Session
        company_db._company_id = 1
        company_db._db_path = self.db_path

        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="test",
            ad_soyad="Test",
            role_kod="YONETICI",
            role_ad="Yonetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="T001",
            firma_unvan="Test Firma",
            firma_uid="uid-test",
            db_path=str(self.db_path),
        )

    def tearDown(self):
        oturum.clear()
        try:
            company_db._engine = None
            company_db._session_factory = None
            company_db._company_id = None
            company_db._db_path = None
        except Exception:
            pass
        try:
            self.engine.dispose()
        except Exception:
            pass
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    def test_schema_hazirla_tablolari_olusturur(self):
        from database.servis_sistem.error_log_service import ErrorLogService

        ErrorLogService.schema_hazirla()
        insp = inspect(self.engine)
        self.assertTrue(insp.has_table("service_issues"))
        self.assertTrue(insp.has_table("service_repairs"))

    def test_quick_check_readonly_ve_rapor(self):
        from database.servis_sistem.system_health_service import SystemHealthService

        with self.engine.connect() as conn:
            before_tables = set(inspect(self.engine).get_table_names())
            cari_once = conn.execute(text('SELECT COUNT(*) FROM "cari_kartlar"')).scalar()

        rapor = SystemHealthService.run_quick_check(kaydet=False)
        self.assertFalse(rapor.get("mutasyon_yapildi"))
        self.assertIn("maddeler", rapor)
        kodlar = {m["hata_kodu"] for m in rapor["maddeler"]}
        self.assertIn("DB_BAGLANTI_OK", kodlar)

        after_tables = set(inspect(self.engine).get_table_names())
        self.assertEqual(before_tables, after_tables)
        with self.engine.connect() as conn:
            cari_sonra = conn.execute(text('SELECT COUNT(*) FROM "cari_kartlar"')).scalar()
        self.assertEqual(cari_once, cari_sonra)

    def test_db_readonly_integrity(self):
        from database.servis_sistem.database_integrity_service import DatabaseIntegrityService

        rapor = DatabaseIntegrityService.run_readonly_check(kaydet=False)
        self.assertFalse(rapor.get("mutasyon_yapildi"))
        kodlar = {m["hata_kodu"] for m in rapor["maddeler"]}
        self.assertIn("INTEGRITY_OK", kodlar)
        self.assertIn("FK_PRAGMA_ON", kodlar)

    def test_quick_check_kaydet_is_verisini_degistirmez(self):
        from database.servis_sistem.system_health_service import SystemHealthService

        with self.engine.connect() as conn:
            cari_once = conn.execute(text('SELECT COUNT(*) FROM "cari_kartlar"')).scalar()
            stok_once = conn.execute(text('SELECT COUNT(*) FROM "stok_kartlari"')).scalar()

        SystemHealthService.run_quick_check(kaydet=True)

        with self.engine.connect() as conn:
            cari_sonra = conn.execute(text('SELECT COUNT(*) FROM "cari_kartlar"')).scalar()
            stok_sonra = conn.execute(text('SELECT COUNT(*) FROM "stok_kartlari"')).scalar()
        self.assertEqual(cari_once, cari_sonra)
        self.assertEqual(stok_once, stok_sonra)

    def test_cari_scan_bos_unvan_tespit(self):
        from database.servis_sistem.module_diagnostic_service import ModuleDiagnosticService

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO cari_kartlar (cari_kodu, unvan, cari_turu, aktif, is_deleted)
                    VALUES ('C001', '   ', 'MÜŞTERİ', 1, 0)
                    """
                )
            )

        rapor = ModuleDiagnosticService.scan_module("cari", kaydet=False)
        self.assertFalse(rapor.get("mutasyon_yapildi"))
        kodlar = {m["hata_kodu"] for m in rapor["maddeler"]}
        self.assertIn("CARI_BOS_UNVAN", kodlar)
        self.assertNotIn("MODUL_YAKINDA", kodlar)

    def test_stok_scan_negatif_lot(self):
        from datetime import date
        from decimal import Decimal

        from database.models.stok import Depo, StokKarti, StokLotu
        from database.servis_sistem.module_diagnostic_service import ModuleDiagnosticService

        with self.Session() as session:
            depo = Depo(ad="Ana Depo", aktif=True)
            session.add(depo)
            session.flush()
            stok = StokKarti(
                stok_kodu="S001",
                stok_adi="Test Stok",
                birim="Adet",
                kart_turu="Ticari Mal",
                aktif=True,
                is_deleted=False,
                iskonto_1=Decimal("0"),
                iskonto_2=Decimal("0"),
                iskonto_3=Decimal("0"),
            )
            session.add(stok)
            session.flush()
            session.add(
                StokLotu(
                    stok_id=stok.id,
                    depo_id=depo.id,
                    lot_no="L1",
                    giris_tarihi=date(2026, 1, 1),
                    kalan_miktar=Decimal("-5"),
                    birim_maliyet=Decimal("0"),
                )
            )
            session.commit()

        rapor = ModuleDiagnosticService.scan_module("stok", kaydet=False)
        self.assertFalse(rapor.get("mutasyon_yapildi"))
        kodlar = {m["hata_kodu"] for m in rapor["maddeler"]}
        self.assertIn("STOK_NEGATIF_LOT", kodlar)

    def test_muhasebe_scan_dengesiz_fis(self):
        from datetime import date
        from decimal import Decimal

        from database.models.firma import Firma
        from database.models.genel_muhasebe import MuhasebeFisi
        from database.servis_sistem.module_diagnostic_service import ModuleDiagnosticService

        with self.Session() as session:
            firma = Firma(firma_kodu="T001", unvan="Test Firma", aktif=True)
            session.add(firma)
            session.flush()
            session.add(
                MuhasebeFisi(
                    firma_id=firma.id,
                    mali_yil=2026,
                    fis_no="F001",
                    fis_tarihi=date(2026, 1, 1),
                    fis_turu="Mahsup Fişi",
                    durum="Kesinleşmiş",
                    toplam_borc=Decimal("100"),
                    toplam_alacak=Decimal("50"),
                )
            )
            session.commit()

        rapor = ModuleDiagnosticService.scan_module("muhasebe", kaydet=False)
        self.assertFalse(rapor.get("mutasyon_yapildi"))
        kodlar = {m["hata_kodu"] for m in rapor["maddeler"]}
        self.assertIn("FIS_BORC_ALACAK", kodlar)

    def test_modul_scan_mutasyon_yok(self):
        from database.servis_sistem.module_diagnostic_service import ModuleDiagnosticService

        with self.engine.connect() as conn:
            before = {
                t: conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
                for t in ("cari_kartlar", "stok_kartlari", "satis_faturalari", "finans_hesaplari")
                if inspect(self.engine).has_table(t)
            }

        for kod in ("cari", "stok", "satis", "finans"):
            rapor = ModuleDiagnosticService.scan_module(kod, kaydet=False)
            self.assertFalse(rapor.get("mutasyon_yapildi"), msg=kod)
            self.assertTrue(rapor.get("maddeler"), msg=kod)

        with self.engine.connect() as conn:
            for t, n in before.items():
                sonra = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
                self.assertEqual(n, sonra, msg=t)

    def test_ui_import(self):
        import servis_sistem_ui

        self.assertTrue(callable(servis_sistem_ui.servis_sistem_goster))
        self.assertTrue(callable(servis_sistem_ui._onarim_yetkisi))
        self.assertTrue(callable(servis_sistem_ui._preview_dialog))

    def test_backup_gate_aborts_repair(self):
        """Yedek başarısızsa onarım uygulanmaz."""
        from unittest.mock import patch

        from database.servis_sistem.repair_service import RepairBackupError, RepairService

        with patch(
            "database.servis_sistem.backup_service.BackupService.servis_oncesi_yedek_al",
            side_effect=RuntimeError("yedek simüle hata"),
        ):
            with self.assertRaises(RepairBackupError):
                RepairService.apply_level1(
                    madde={
                        "hata_kodu": "KLASOR_TEMP_YOK",
                        "aciklama": "test",
                        "modul": "dosya_sistemi",
                        "repair_level": 1,
                    },
                    confirm=True,
                    yedek_klasor=self._tmpdir.name,
                )

    def test_level1_folder_repair(self):
        """Eksik klasör Seviye 1 ile oluşturulur; muhasebe sayıları değişmez."""
        from unittest.mock import patch

        from database.servis_sistem.error_log_service import ErrorLogService
        from database.servis_sistem.repair_service import RepairService

        hedef = Path(self._tmpdir.name) / "servis_logs_test"
        self.assertFalse(hedef.exists())

        with self.engine.connect() as conn:
            cari_once = conn.execute(text('SELECT COUNT(*) FROM "cari_kartlar"')).scalar()
            fis_once = (
                conn.execute(text('SELECT COUNT(*) FROM "muhasebe_fisleri"')).scalar()
                if inspect(self.engine).has_table("muhasebe_fisleri")
                else 0
            )

        ErrorLogService.schema_hazirla()
        iid = ErrorLogService.kaydet_sorun(
            module_name="dosya_sistemi",
            issue_code="KLASOR_LOG_YOK",
            severity="uyari",
            title="Log klasörü eksik (test)",
            user_message="test",
            technical_detail=str(hedef),
            auto_fixable=True,
            repair_level=1,
        )
        self.assertIsNotNone(iid)

        yedek_dosya = Path(self._tmpdir.name) / "CinMuhasebe_ServisOncesi_test.db"
        yedek_dosya.write_bytes(b"sqlite-fake-backup-ok")

        def _fake_yedek(_klasor=None):
            return yedek_dosya

        with patch(
            "database.servis_sistem.repair_service._hedef_klasorler",
            return_value={"logs": hedef},
        ), patch(
            "database.servis_sistem.backup_service.BackupService.servis_oncesi_yedek_al",
            side_effect=_fake_yedek,
        ):
            sonuc = RepairService.apply_level1(
                issue_id=int(iid),
                confirm=True,
                yedek_klasor=self._tmpdir.name,
            )

        self.assertTrue(sonuc.get("basarili"))
        self.assertTrue(sonuc.get("uygulandi"))
        self.assertTrue(hedef.is_dir())
        self.assertFalse(sonuc.get("mutasyon_muhasebe"))

        issue = ErrorLogService.get_issue(int(iid))
        self.assertEqual(issue["status"], "resolved")

        with self.engine.connect() as conn:
            cari_sonra = conn.execute(text('SELECT COUNT(*) FROM "cari_kartlar"')).scalar()
            fis_sonra = (
                conn.execute(text('SELECT COUNT(*) FROM "muhasebe_fisleri"')).scalar()
                if inspect(self.engine).has_table("muhasebe_fisleri")
                else 0
            )
        self.assertEqual(cari_once, cari_sonra)
        self.assertEqual(fis_once, fis_sonra)

    def test_level1_index_rollback_on_failure(self):
        """DB onarımında hata → rollback; muhasebe satır sayısı aynı."""
        from unittest.mock import patch

        from database.servis_sistem.repair_service import RepairService

        with self.engine.connect() as conn:
            cari_once = conn.execute(text('SELECT COUNT(*) FROM "cari_kartlar"')).scalar()

        yedek_dosya = Path(self._tmpdir.name) / "CinMuhasebe_ServisOncesi_rb.db"
        yedek_dosya.write_bytes(b"backup-ok")

        def _boom():
            raise RuntimeError("simüle index hatası")

        with patch(
            "database.servis_sistem.backup_service.BackupService.servis_oncesi_yedek_al",
            return_value=yedek_dosya,
        ), patch(
            "database.servis_sistem.repair_service.RepairService._do_create_indexes",
            side_effect=_boom,
        ):
            with self.assertRaises(RuntimeError):
                RepairService.apply_level1(
                    madde={
                        "hata_kodu": "INDEX_EKSIK",
                        "aciklama": "index test",
                        "modul": "veritabani",
                        "repair_level": 1,
                    },
                    confirm=True,
                    yedek_klasor=self._tmpdir.name,
                )

        with self.engine.connect() as conn:
            cari_sonra = conn.execute(text('SELECT COUNT(*) FROM "cari_kartlar"')).scalar()
        self.assertEqual(cari_once, cari_sonra)

    def test_repair_preview_level2_blocked(self):
        """Seviye 3 / dengesiz fiş (FIS_BORC_ALACAK) otomatik onarılamaz."""
        from database.servis_sistem.repair_service import RepairService

        oniz = RepairService.repair_preview(
            madde={
                "hata_kodu": "FIS_BORC_ALACAK",
                "aciklama": "dengesiz fiş",
                "modul": "muhasebe",
                "repair_level": 3,
            },
            take_backup=False,
        )
        self.assertFalse(oniz.get("uygulanabilir"))
        self.assertGreaterEqual(int(oniz.get("seviye") or 0), 3)
        mesaj = (oniz.get("mesaj") or "").lower()
        self.assertTrue(
            "seviye 3" in mesaj or "yasak" in mesaj or "manuel" in mesaj,
            msg=oniz.get("mesaj"),
        )

    def test_yedek_dogrula_bos_red(self):
        from database.servis_sistem.backup_service import BackupService

        bos = Path(self._tmpdir.name) / "bos.db"
        bos.write_bytes(b"")
        with self.assertRaises(ValueError):
            BackupService.dogrula_yedek(bos)

    def test_level2_preview_requires_confirm(self):
        """Seviye 2: confirm=False iken mutasyon yok."""
        from datetime import date
        from decimal import Decimal
        from unittest.mock import patch

        from database.models.cari import Cari
        from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
        from database.servis_sistem.repair_service import RepairService

        with self.Session() as session:
            cari = Cari(
                cari_kodu="C-L2",
                unvan="L2 Test",
                cari_turu="MÜŞTERİ",
                aktif=True,
                is_deleted=False,
            )
            session.add(cari)
            session.flush()
            fatura = SatisFaturasi(
                fatura_no="SF-L2-1",
                fatura_tarihi=date(2026, 3, 1),
                vade_gunu=0,
                vade_tarihi=date(2026, 3, 1),
                cari_id=cari.id,
                durum="AÇIK",
                tl_matrah=Decimal("100"),
                tl_kdv=Decimal("20"),
                tl_genel_toplam=Decimal("999"),  # bilerek bozuk
            )
            session.add(fatura)
            session.flush()
            session.add(
                SatisFaturasiSatiri(
                    fatura_id=fatura.id,
                    urun_kodu="U1",
                    urun_adi="Ürün",
                    miktar=Decimal("1"),
                    birim="Adet",
                    birim_fiyat=Decimal("100"),
                    iskonto_orani=Decimal("0"),
                    iskonto_orani_2=Decimal("0"),
                    iskonto_orani_3=Decimal("0"),
                    kdv_orani=Decimal("20"),
                    tl_tutar=Decimal("100"),
                )
            )
            session.commit()
            fid = fatura.id

        oniz = RepairService.apply_level2(
            madde={
                "hata_kodu": "FATURA_TOPLAM_UYUSMAZ",
                "modul": "satis",
                "record_id": str(fid),
                "aciklama": "test",
                "repair_level": 2,
            },
            confirm=False,
        )
        self.assertTrue(oniz.get("basarili"))
        self.assertFalse(oniz.get("uygulandi"))
        self.assertIn("onay", (oniz.get("mesaj") or "").lower())

        with self.Session() as session:
            f = session.get(SatisFaturasi, fid)
            self.assertEqual(Decimal(str(f.tl_genel_toplam)), Decimal("999"))

    def test_level2_backup_gate(self):
        """Yedek başarısızsa Seviye 2 onarım uygulanmaz."""
        from datetime import date
        from decimal import Decimal
        from unittest.mock import patch

        from database.models.cari import Cari
        from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
        from database.servis_sistem.repair_service import RepairBackupError, RepairService

        with self.Session() as session:
            cari = Cari(
                cari_kodu="C-BG",
                unvan="Backup Gate",
                cari_turu="MÜŞTERİ",
                aktif=True,
                is_deleted=False,
            )
            session.add(cari)
            session.flush()
            fatura = SatisFaturasi(
                fatura_no="SF-BG-1",
                fatura_tarihi=date(2026, 3, 2),
                vade_gunu=0,
                vade_tarihi=date(2026, 3, 2),
                cari_id=cari.id,
                durum="AÇIK",
                tl_matrah=Decimal("10"),
                tl_kdv=Decimal("1"),
                tl_genel_toplam=Decimal("99"),
            )
            session.add(fatura)
            session.flush()
            session.add(
                SatisFaturasiSatiri(
                    fatura_id=fatura.id,
                    urun_kodu="U1",
                    urun_adi="Ürün",
                    miktar=Decimal("1"),
                    birim="Adet",
                    birim_fiyat=Decimal("10"),
                    kdv_orani=Decimal("20"),
                    tl_tutar=Decimal("10"),
                )
            )
            session.commit()
            fid = fatura.id

        with patch(
            "database.servis_sistem.backup_service.BackupService.servis_oncesi_yedek_al",
            side_effect=RuntimeError("yedek simüle hata"),
        ):
            with self.assertRaises(RepairBackupError):
                RepairService.apply_level2(
                    madde={
                        "hata_kodu": "FATURA_TOPLAM_UYUSMAZ",
                        "modul": "satis",
                        "record_id": str(fid),
                        "repair_level": 2,
                        "aciklama": "test",
                    },
                    confirm=True,
                    yedek_klasor=self._tmpdir.name,
                )

        with self.Session() as session:
            f = session.get(SatisFaturasi, fid)
            self.assertEqual(Decimal(str(f.tl_genel_toplam)), Decimal("99"))

    def test_level2_fatura_header_recalc(self):
        from datetime import date
        from decimal import Decimal
        from unittest.mock import patch

        from database.models.cari import Cari
        from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
        from database.servis_sistem.error_log_service import ErrorLogService
        from database.servis_sistem.repair_service import RepairService

        with self.Session() as session:
            cari = Cari(
                cari_kodu="C-FAT",
                unvan="Fatura Test",
                cari_turu="MÜŞTERİ",
                aktif=True,
                is_deleted=False,
            )
            session.add(cari)
            session.flush()
            fatura = SatisFaturasi(
                fatura_no="SF-REC-1",
                fatura_tarihi=date(2026, 4, 1),
                vade_gunu=0,
                vade_tarihi=date(2026, 4, 1),
                cari_id=cari.id,
                durum="AÇIK",
                tl_matrah=Decimal("50"),
                tl_kdv=Decimal("5"),
                tl_genel_toplam=Decimal("10"),
            )
            session.add(fatura)
            session.flush()
            session.add(
                SatisFaturasiSatiri(
                    fatura_id=fatura.id,
                    urun_kodu="U1",
                    urun_adi="Ürün",
                    miktar=Decimal("2"),
                    birim="Adet",
                    birim_fiyat=Decimal("100"),
                    iskonto_orani=Decimal("0"),
                    iskonto_orani_2=Decimal("0"),
                    iskonto_orani_3=Decimal("0"),
                    kdv_orani=Decimal("20"),
                    tl_tutar=Decimal("200"),
                )
            )
            session.commit()
            fid = fatura.id

        ErrorLogService.schema_hazirla()
        iid = ErrorLogService.kaydet_sorun(
            module_name="satis",
            issue_code="FATURA_TOPLAM_UYUSMAZ",
            severity="uyari",
            title="Fatura toplam uyuşmaz",
            user_message="test",
            record_id=str(fid),
            document_number=f"SF-REC-1 / id={fid}",
            auto_fixable=True,
            repair_level=2,
        )

        yedek = Path(self._tmpdir.name) / "CinMuhasebe_ServisOncesi_fat.db"
        yedek.write_bytes(b"backup-ok")

        with patch(
            "database.servis_sistem.backup_service.BackupService.servis_oncesi_yedek_al",
            return_value=yedek,
        ):
            sonuc = RepairService.apply_level2(
                issue_id=int(iid),
                confirm=True,
                yedek_klasor=self._tmpdir.name,
            )

        self.assertTrue(sonuc.get("basarili"), msg=sonuc.get("mesaj"))
        self.assertTrue(sonuc.get("uygulandi"))
        with self.Session() as session:
            f = session.get(SatisFaturasi, fid)
            # 2*100 = 200 matrah, kdv %20 = 40, genel = 240
            self.assertEqual(Decimal(str(f.tl_matrah)), Decimal("200.00"))
            self.assertEqual(Decimal(str(f.tl_kdv)), Decimal("40.00"))
            self.assertEqual(Decimal(str(f.tl_genel_toplam)), Decimal("240.00"))
        issue = ErrorLogService.get_issue(int(iid))
        self.assertEqual(issue["status"], "resolved")

    def test_level2_muhasebe_header_recalc(self):
        from datetime import date
        from decimal import Decimal
        from unittest.mock import patch

        from database.models.firma import Firma
        from database.models.genel_muhasebe import HesapPlani, MuhasebeFisi, MuhasebeFisiSatiri
        from database.servis_sistem.repair_service import RepairService

        with self.Session() as session:
            firma = Firma(firma_kodu="T001", unvan="Test Firma", aktif=True)
            session.add(firma)
            session.flush()
            h1 = HesapPlani(
                firma_id=firma.id,
                hesap_kodu="100",
                hesap_adi="Kasa",
                hesap_seviyesi=1,
                hesap_turu="Aktif",
            )
            h2 = HesapPlani(
                firma_id=firma.id,
                hesap_kodu="120",
                hesap_adi="Alıcılar",
                hesap_seviyesi=1,
                hesap_turu="Aktif",
            )
            session.add_all([h1, h2])
            session.flush()
            fis = MuhasebeFisi(
                firma_id=firma.id,
                mali_yil=2026,
                fis_no="MH-HDR-1",
                fis_tarihi=date(2026, 5, 1),
                fis_turu="Mahsup Fişi",
                durum="Taslak",
                toplam_borc=Decimal("1"),
                toplam_alacak=Decimal("2"),
            )
            session.add(fis)
            session.flush()
            session.add_all(
                [
                    MuhasebeFisiSatiri(
                        fis_id=fis.id,
                        firma_id=firma.id,
                        sira_no=1,
                        hesap_id=h1.id,
                        hesap_kodu="100",
                        hesap_adi="Kasa",
                        borc=Decimal("100"),
                        alacak=Decimal("0"),
                    ),
                    MuhasebeFisiSatiri(
                        fis_id=fis.id,
                        firma_id=firma.id,
                        sira_no=2,
                        hesap_id=h2.id,
                        hesap_kodu="120",
                        hesap_adi="Alıcılar",
                        borc=Decimal("0"),
                        alacak=Decimal("100"),
                    ),
                ]
            )
            session.commit()
            fis_id = fis.id

        yedek = Path(self._tmpdir.name) / "CinMuhasebe_ServisOncesi_mh.db"
        yedek.write_bytes(b"backup-ok")

        with patch(
            "database.servis_sistem.backup_service.BackupService.servis_oncesi_yedek_al",
            return_value=yedek,
        ):
            sonuc = RepairService.apply_level2(
                madde={
                    "hata_kodu": "FIS_BASLIK_SATIR",
                    "modul": "muhasebe",
                    "record_id": str(fis_id),
                    "kayit_belge": f"MH-HDR-1 / id={fis_id}",
                    "repair_level": 2,
                    "aciklama": "başlık uyuşmaz",
                },
                confirm=True,
                yedek_klasor=self._tmpdir.name,
            )

        self.assertTrue(sonuc.get("basarili"), msg=sonuc.get("mesaj"))
        self.assertTrue(sonuc.get("uygulandi"))
        with self.Session() as session:
            f = session.get(MuhasebeFisi, fis_id)
            self.assertEqual(Decimal(str(f.toplam_borc)), Decimal("100.00"))
            self.assertEqual(Decimal(str(f.toplam_alacak)), Decimal("100.00"))

    def test_level2_muhasebe_unbalanced_lines_blocked(self):
        """Satır borç≠alacak → başlık onarımı reddedilir (hesap uydurma yok)."""
        from datetime import date
        from decimal import Decimal

        from database.models.firma import Firma
        from database.models.genel_muhasebe import HesapPlani, MuhasebeFisi, MuhasebeFisiSatiri
        from database.servis_sistem.repair_service import RepairService

        with self.Session() as session:
            firma = Firma(firma_kodu="T002", unvan="Test 2", aktif=True)
            session.add(firma)
            session.flush()
            h1 = HesapPlani(
                firma_id=firma.id,
                hesap_kodu="100",
                hesap_adi="Kasa",
                hesap_seviyesi=1,
                hesap_turu="Aktif",
            )
            session.add(h1)
            session.flush()
            fis = MuhasebeFisi(
                firma_id=firma.id,
                mali_yil=2026,
                fis_no="MH-UB-1",
                fis_tarihi=date(2026, 5, 2),
                fis_turu="Mahsup Fişi",
                durum="Taslak",
                toplam_borc=Decimal("50"),
                toplam_alacak=Decimal("0"),
            )
            session.add(fis)
            session.flush()
            session.add(
                MuhasebeFisiSatiri(
                    fis_id=fis.id,
                    firma_id=firma.id,
                    sira_no=1,
                    hesap_id=h1.id,
                    hesap_kodu="100",
                    hesap_adi="Kasa",
                    borc=Decimal("50"),
                    alacak=Decimal("0"),
                )
            )
            session.commit()
            fis_id = fis.id

        oniz = RepairService.repair_preview(
            madde={
                "hata_kodu": "FIS_BASLIK_SATIR",
                "modul": "muhasebe",
                "record_id": str(fis_id),
                "repair_level": 2,
            },
            take_backup=False,
        )
        self.assertFalse(oniz.get("uygulanabilir"))
        self.assertIn("dengesiz", (oniz.get("mesaj") or "").lower())

    def test_level2_rollback_on_failure(self):
        from datetime import date
        from decimal import Decimal
        from unittest.mock import patch

        from database.models.cari import Cari
        from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
        from database.servis_sistem.repair_service import RepairService

        with self.Session() as session:
            cari = Cari(
                cari_kodu="C-RB",
                unvan="Rollback",
                cari_turu="MÜŞTERİ",
                aktif=True,
                is_deleted=False,
            )
            session.add(cari)
            session.flush()
            fatura = SatisFaturasi(
                fatura_no="SF-RB-1",
                fatura_tarihi=date(2026, 6, 1),
                vade_gunu=0,
                vade_tarihi=date(2026, 6, 1),
                cari_id=cari.id,
                durum="AÇIK",
                tl_matrah=Decimal("1"),
                tl_kdv=Decimal("1"),
                tl_genel_toplam=Decimal("1"),
            )
            session.add(fatura)
            session.flush()
            session.add(
                SatisFaturasiSatiri(
                    fatura_id=fatura.id,
                    urun_kodu="U1",
                    urun_adi="Ürün",
                    miktar=Decimal("1"),
                    birim="Adet",
                    birim_fiyat=Decimal("10"),
                    kdv_orani=Decimal("20"),
                    tl_tutar=Decimal("10"),
                )
            )
            session.commit()
            fid = fatura.id

        yedek = Path(self._tmpdir.name) / "CinMuhasebe_ServisOncesi_rb2.db"
        yedek.write_bytes(b"backup-ok")

        with patch(
            "database.servis_sistem.backup_service.BackupService.servis_oncesi_yedek_al",
            return_value=yedek,
        ), patch(
            "database.servis_sistem.repair_service.RepairService._do_recalc_fatura_header",
            side_effect=RuntimeError("simüle L2 hata"),
        ):
            with self.assertRaises(RuntimeError):
                RepairService.apply_level2(
                    madde={
                        "hata_kodu": "FATURA_TOPLAM_UYUSMAZ",
                        "modul": "satis",
                        "record_id": str(fid),
                        "repair_level": 2,
                    },
                    confirm=True,
                    yedek_klasor=self._tmpdir.name,
                )

        with self.Session() as session:
            f = session.get(SatisFaturasi, fid)
            self.assertEqual(Decimal(str(f.tl_genel_toplam)), Decimal("1"))

    # --- Aşama 6: geniş paket / performans / kapılar ---------------------------------

    def test_level2_cek_kalan_recalc(self):
        """CEK_TUTAR_UYUSMAZ → kalan_tutar = tl − tahsil."""
        from datetime import date
        from decimal import Decimal
        from unittest.mock import patch

        from database.models.cari import Cari
        from database.models.cek_senet import (
            CekSenetEvrak,
            DURUM_PORTFOYDE,
            EVRAK_TURU_MUSTERI_CEKI,
            ISLEM_YONU_ALINAN,
        )
        from database.servis_sistem.repair_service import RepairService

        with self.Session() as session:
            cari = Cari(
                cari_kodu="C-CEK",
                unvan="Çek Cari",
                cari_turu="MÜŞTERİ",
                aktif=True,
                is_deleted=False,
            )
            session.add(cari)
            session.flush()
            evrak = CekSenetEvrak(
                cari_id=cari.id,
                evrak_turu=EVRAK_TURU_MUSTERI_CEKI,
                islem_yonu=ISLEM_YONU_ALINAN,
                evrak_no="CK-1",
                portfoy_no="PF-CEK-1",
                duzenleme_tarihi=date(2026, 7, 1),
                vade_tarihi=date(2026, 8, 1),
                tl_tutari=Decimal("1000"),
                tahsil_edilen_tutar=Decimal("250"),
                kalan_tutar=Decimal("999"),  # bozuk
                durum=DURUM_PORTFOYDE,
            )
            session.add(evrak)
            session.commit()
            eid = evrak.id

        yedek = Path(self._tmpdir.name) / "CinMuhasebe_ServisOncesi_cek.db"
        yedek.write_bytes(b"backup-ok")

        with patch(
            "database.servis_sistem.backup_service.BackupService.servis_oncesi_yedek_al",
            return_value=yedek,
        ):
            sonuc = RepairService.apply_level2(
                madde={
                    "hata_kodu": "CEK_TUTAR_UYUSMAZ",
                    "modul": "cek_senet",
                    "record_id": str(eid),
                    "kayit_belge": f"PF-CEK-1 / id={eid}",
                    "repair_level": 2,
                    "aciklama": "kalan bozuk",
                },
                confirm=True,
                yedek_klasor=self._tmpdir.name,
            )

        self.assertTrue(sonuc.get("basarili"), msg=sonuc.get("mesaj"))
        self.assertTrue(sonuc.get("uygulandi"))
        with self.Session() as session:
            e = session.get(CekSenetEvrak, eid)
            self.assertEqual(Decimal(str(e.kalan_tutar)), Decimal("750.00"))

    def test_level2_closed_period_blocked(self):
        """Kapalı dönem kaydında Seviye 2 önizleme uygulanamaz."""
        from datetime import date
        from decimal import Decimal

        from database.models.cari import Cari
        from database.models.donem import Donem
        from database.models.firma import Firma
        from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
        from database.servis_sistem.repair_service import RepairService

        with self.Session() as session:
            firma = Firma(firma_kodu="T001", unvan="Test Firma", aktif=True)
            session.add(firma)
            session.flush()
            session.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="Kapalı 2025",
                    baslangic_tarihi=date(2025, 1, 1),
                    bitis_tarihi=date(2025, 12, 31),
                    aktif=False,
                    kapali=True,
                )
            )
            cari = Cari(
                cari_kodu="C-KP",
                unvan="Kapalı Dönem",
                cari_turu="MÜŞTERİ",
                aktif=True,
                is_deleted=False,
            )
            session.add(cari)
            session.flush()
            fatura = SatisFaturasi(
                fatura_no="SF-KP-1",
                fatura_tarihi=date(2025, 6, 15),
                vade_gunu=0,
                vade_tarihi=date(2025, 6, 15),
                cari_id=cari.id,
                durum="AÇIK",
                tl_matrah=Decimal("10"),
                tl_kdv=Decimal("1"),
                tl_genel_toplam=Decimal("99"),
            )
            session.add(fatura)
            session.flush()
            session.add(
                SatisFaturasiSatiri(
                    fatura_id=fatura.id,
                    urun_kodu="U1",
                    urun_adi="Ürün",
                    miktar=Decimal("1"),
                    birim="Adet",
                    birim_fiyat=Decimal("10"),
                    kdv_orani=Decimal("20"),
                    tl_tutar=Decimal("10"),
                )
            )
            session.commit()
            fid = fatura.id

        oniz = RepairService.repair_preview(
            madde={
                "hata_kodu": "FATURA_TOPLAM_UYUSMAZ",
                "modul": "satis",
                "record_id": str(fid),
                "repair_level": 2,
            },
            take_backup=False,
        )
        self.assertFalse(oniz.get("uygulanabilir"))
        mesaj = (oniz.get("mesaj") or "").lower()
        self.assertTrue("kapalı" in mesaj or "kapali" in mesaj, msg=oniz.get("mesaj"))

    def test_repair_permission_denied(self):
        """servis_onarim yok + YONETICI değil → RepairPermissionError."""
        from database.servis_sistem.repair_service import (
            RepairPermissionError,
            RepairService,
        )

        oturum.set_user(
            user_id=2,
            kullanici_adi="personel",
            ad_soyad="Personel",
            role_kod="PERSONEL",
            role_ad="Personel",
            permissions={"servis_goruntuleme"},
        )
        with self.assertRaises(RepairPermissionError):
            RepairService.apply_level1(
                madde={
                    "hata_kodu": "KLASOR_TEMP_YOK",
                    "aciklama": "test",
                    "modul": "dosya_sistemi",
                    "repair_level": 1,
                },
                confirm=True,
                yedek_klasor=self._tmpdir.name,
            )

    def test_apply_repair_routes_level2(self):
        """apply_repair L2 kodunu apply_level2 yoluna alır (confirm=False → mutasyon yok)."""
        from datetime import date
        from decimal import Decimal

        from database.models.cari import Cari
        from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
        from database.servis_sistem.repair_service import RepairService

        with self.Session() as session:
            cari = Cari(
                cari_kodu="C-RT",
                unvan="Route",
                cari_turu="MÜŞTERİ",
                aktif=True,
                is_deleted=False,
            )
            session.add(cari)
            session.flush()
            fatura = SatisFaturasi(
                fatura_no="SF-RT-1",
                fatura_tarihi=date(2026, 9, 1),
                vade_gunu=0,
                vade_tarihi=date(2026, 9, 1),
                cari_id=cari.id,
                durum="AÇIK",
                tl_matrah=Decimal("1"),
                tl_kdv=Decimal("1"),
                tl_genel_toplam=Decimal("1"),
            )
            session.add(fatura)
            session.flush()
            session.add(
                SatisFaturasiSatiri(
                    fatura_id=fatura.id,
                    urun_kodu="U1",
                    urun_adi="Ürün",
                    miktar=Decimal("1"),
                    birim="Adet",
                    birim_fiyat=Decimal("50"),
                    kdv_orani=Decimal("20"),
                    tl_tutar=Decimal("50"),
                )
            )
            session.commit()
            fid = fatura.id

        sonuc = RepairService.apply_repair(
            madde={
                "hata_kodu": "FATURA_TOPLAM_UYUSMAZ",
                "modul": "satis",
                "record_id": str(fid),
                "repair_level": 2,
            },
            confirm=False,
        )
        self.assertTrue(sonuc.get("basarili"))
        self.assertFalse(sonuc.get("uygulandi"))
        self.assertIn("onay", (sonuc.get("mesaj") or "").lower())

    def test_apply_repair_level3_blocked(self):
        from database.servis_sistem.repair_service import RepairService

        sonuc = RepairService.apply_repair(
            madde={
                "hata_kodu": "FIS_BORC_ALACAK",
                "modul": "muhasebe",
                "repair_level": 3,
                "aciklama": "L3",
            },
            confirm=True,
        )
        self.assertFalse(sonuc.get("uygulandi"))
        self.assertFalse(sonuc.get("basarili") and sonuc.get("uygulandi"))

    def test_scan_all_modules_readonly_and_timing(self):
        """Ayrıntılı tarama salt okunur; sure_ms raporlanır."""
        from database.servis_sistem.module_diagnostic_service import ModuleDiagnosticService

        with self.engine.connect() as conn:
            cari_once = conn.execute(text('SELECT COUNT(*) FROM "cari_kartlar"')).scalar()

        rapor = ModuleDiagnosticService.scan_all_modules(kaydet=False, include_quick=True)
        self.assertFalse(rapor.get("mutasyon_yapildi"))
        self.assertIsNotNone(rapor.get("sure_ms"))
        self.assertGreaterEqual(int(rapor["sure_ms"]), 0)
        self.assertLess(int(rapor["sure_ms"]), 60_000)
        self.assertTrue(rapor.get("maddeler"))

        with self.engine.connect() as conn:
            cari_sonra = conn.execute(text('SELECT COUNT(*) FROM "cari_kartlar"')).scalar()
        self.assertEqual(cari_once, cari_sonra)

    def test_max_ornek_caps_cari_scan(self):
        """Büyük uyarı setinde tarama MAX_ORNEK ile sınırlanır."""
        from database.servis_sistem.module_diagnostic_service import ModuleDiagnosticService
        from database.servis_sistem.scanners.common import MAX_ORNEK

        n = MAX_ORNEK + 25
        with self.engine.begin() as conn:
            for i in range(n):
                conn.execute(
                    text(
                        """
                        INSERT INTO cari_kartlar (cari_kodu, unvan, cari_turu, aktif, is_deleted)
                        VALUES (:kod, '   ', 'MÜŞTERİ', 1, 0)
                        """
                    ),
                    {"kod": f"BOS{i:04d}"},
                )

        rapor = ModuleDiagnosticService.scan_module("cari", kaydet=False)
        bos = [m for m in rapor["maddeler"] if m.get("hata_kodu") == "CARI_BOS_UNVAN"]
        self.assertLessEqual(len(bos), MAX_ORNEK)
        self.assertGreater(len(bos), 0)

    def test_cek_senet_scan_detects_tutar(self):
        from datetime import date
        from decimal import Decimal

        from database.models.cari import Cari
        from database.models.cek_senet import (
            CekSenetEvrak,
            DURUM_PORTFOYDE,
            EVRAK_TURU_MUSTERI_CEKI,
            ISLEM_YONU_ALINAN,
        )
        from database.servis_sistem.module_diagnostic_service import ModuleDiagnosticService

        with self.Session() as session:
            cari = Cari(
                cari_kodu="C-SCN",
                unvan="Scan Cek",
                cari_turu="MÜŞTERİ",
                aktif=True,
                is_deleted=False,
            )
            session.add(cari)
            session.flush()
            session.add(
                CekSenetEvrak(
                    cari_id=cari.id,
                    evrak_turu=EVRAK_TURU_MUSTERI_CEKI,
                    islem_yonu=ISLEM_YONU_ALINAN,
                    evrak_no="CK-S",
                    portfoy_no="PF-SCAN-1",
                    duzenleme_tarihi=date(2026, 7, 1),
                    vade_tarihi=date(2026, 8, 1),
                    tl_tutari=Decimal("500"),
                    tahsil_edilen_tutar=Decimal("0"),
                    kalan_tutar=Decimal("100"),
                    durum=DURUM_PORTFOYDE,
                )
            )
            session.commit()

        rapor = ModuleDiagnosticService.scan_module("cek_senet", kaydet=False)
        self.assertFalse(rapor.get("mutasyon_yapildi"))
        kodlar = {m["hata_kodu"] for m in rapor["maddeler"]}
        self.assertIn("CEK_TUTAR_UYUSMAZ", kodlar)

    def test_persist_sets_level2_auto_fixable(self):
        from database.servis_sistem.error_log_service import ErrorLogService
        from database.servis_sistem.scanners.common import persist_rapor
        from database.servis_sistem.system_health_service import (
            SEVERITY_UYARI,
            CheckItem,
            CheckReport,
        )

        ErrorLogService.schema_hazirla()
        rapor = CheckReport(baslik="t", baslangic="x")
        rapor.ekle(
            CheckItem(
                durum=SEVERITY_UYARI,
                onem="Uyarı",
                modul="satis",
                hata_kodu="FATURA_TOPLAM_UYUSMAZ",
                aciklama="test persist",
                kayit_belge="SF / id=42",
                otomatik_duzeltme="Evet (Seviye 2)",
            )
        )
        persist_rapor(rapor)
        acik = ErrorLogService.acik_sorunlar(limit=50, status="open")
        aday = next(
            (s for s in acik if s.get("issue_code") == "FATURA_TOPLAM_UYUSMAZ"),
            None,
        )
        self.assertIsNotNone(aday)
        self.assertIn(str(aday.get("auto_fixable") or "").lower(), ("evet", "true", "1", "yes"))
        self.assertEqual(int(aday.get("repair_level") or 0), 2)

    def test_performance_medium_dataset_scan(self):
        """~150 cari + stok ile derin tarama makul sürede biter."""
        import time

        from database.models.stok import StokKarti
        from database.servis_sistem.module_diagnostic_service import ModuleDiagnosticService
        from decimal import Decimal

        with self.Session() as session:
            for i in range(150):
                session.add(
                    StokKarti(
                        stok_kodu=f"P{i:04d}",
                        stok_adi=f"Perf Stok {i}",
                        birim="Adet",
                        kart_turu="Ticari Mal",
                        aktif=True,
                        is_deleted=False,
                        iskonto_1=Decimal("0"),
                        iskonto_2=Decimal("0"),
                        iskonto_3=Decimal("0"),
                    )
                )
            session.commit()

        with self.engine.begin() as conn:
            for i in range(150):
                conn.execute(
                    text(
                        """
                        INSERT INTO cari_kartlar (cari_kodu, unvan, cari_turu, aktif, is_deleted)
                        VALUES (:kod, :unvan, 'MÜŞTERİ', 1, 0)
                        """
                    ),
                    {"kod": f"PERF{i:04d}", "unvan": f"Perf Cari {i}"},
                )

        t0 = time.monotonic()
        rapor = ModuleDiagnosticService.scan_all_modules(kaydet=False, include_quick=False)
        elapsed = time.monotonic() - t0
        self.assertFalse(rapor.get("mutasyon_yapildi"))
        self.assertLess(elapsed, 45.0, msg=f"tarama çok yavaş: {elapsed:.1f}s")
        self.assertIsNotNone(rapor.get("sure_ms"))


if __name__ == "__main__":
    unittest.main()
