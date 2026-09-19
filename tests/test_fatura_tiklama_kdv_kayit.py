"""Fatura tıklama / KDV canlı hesap / kaydet-yeniden aç düzeltmeleri."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.iskonto_hesap_service import satir_iskonto_hesapla
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokFiyati, StokKarti
from database.satis_faturasi_service import SatisFaturasiService
from database.session_manager import oturum


def _sqlite_pragma(dbapi_conn, _connection_record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class FaturaKayitYuklemeTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, expire_on_commit=False)

        with Session() as s:
            firma = Firma(firma_kodu="FTK", unvan="Fatura Tiklama Test", aktif=True)
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
            for kod, ad in (("U1", "Ürün Bir"), ("U2", "Ürün İki")):
                st = StokKarti(
                    stok_kodu=kod,
                    stok_adi=ad,
                    birim="Adet",
                    aktif=True,
                    is_deleted=False,
                    minimum_stok=Decimal("0"),
                )
                s.add(st)
                s.flush()
                s.add(
                    StokFiyati(
                        stok_id=st.id, fiyat_adi="SATIŞ FİYATI 1", tutar=Decimal("100")
                    )
                )
            cari = Cari(
                cari_kodu="C1",
                unvan="Test Cari",
                cari_turu="Müşteri",
                aktif=True,
                is_deleted=False,
            )
            s.add(cari)
            s.commit()
            self.cari_id = cari.id

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = self.db_path

        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Admin",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="FTK",
            firma_unvan="Test",
            firma_uid="ftk-test",
            db_path=str(self.db_path),
        )
        oturum.set_period(1, "2026")

        self._yaz = patch(
            "database.satis_faturasi_service.yazma_zorunlu", return_value=None
        )
        self._yaz.start()
        self._sp = patch(
            "database.satis_personeli.secimi_dogrula",
            return_value=(1, "Test"),
        )
        self._sp.start()

    def tearDown(self):
        self._sp.stop()
        self._yaz.stop()
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

    def _ust(self, **extra):
        d = {
            "fatura_tarihi": date(2026, 3, 10),
            "vade_tarihi": date(2026, 3, 20),
            "cari_id": self.cari_id,
            "depo": "ANA DEPO",
            "aciklama": "Test fatura",
            "sales_person_id": 1,
            "para_birimi": "TRY",
            "kur": 1,
        }
        d.update(extra)
        return d

    def _satir(self, kod, ad, miktar, fiyat, kdv=20, isk1=0, isk2=0, isk3=0):
        return {
            "urun_kodu": kod,
            "urun_adi": ad,
            "barkod": "",
            "miktar": Decimal(str(miktar)),
            "birim": "Adet",
            "birim_fiyat": Decimal(str(fiyat)),
            "iskonto_orani": Decimal(str(isk1)),
            "iskonto_orani_2": Decimal(str(isk2)),
            "iskonto_orani_3": Decimal(str(isk3)),
            "kdv_orani": Decimal(str(kdv)),
            "aciklama": "",
        }

    def test_1_kaydet_kapat_ac_iki_satir(self):
        fatura = SatisFaturasiService.kaydet(
            self._ust(),
            [
                self._satir("U1", "Ürün Bir", 2, 100, 20),
                self._satir("U2", "Ürün İki", 1, 50, 10),
            ],
        )
        yuklenen = SatisFaturasiService.getir(fatura.id)
        self.assertIsNotNone(yuklenen)
        self.assertEqual(yuklenen.cari_id, self.cari_id)
        self.assertEqual(yuklenen.aciklama, "Test fatura")
        self.assertEqual(len(yuklenen.satirlar), 2)
        kodlar = sorted(s.urun_kodu for s in yuklenen.satirlar)
        self.assertEqual(kodlar, ["U1", "U2"])

    def test_2_duzenle_miktar_kdv_korunur(self):
        fatura = SatisFaturasiService.kaydet(
            self._ust(),
            [self._satir("U1", "Ürün Bir", 1, 100, 20)],
        )
        SatisFaturasiService.kaydet(
            self._ust(aciklama="Güncellendi"),
            [self._satir("U1", "Ürün Bir", 5, 100, 10)],
            fatura_id=fatura.id,
        )
        yuklenen = SatisFaturasiService.getir(fatura.id)
        self.assertEqual(yuklenen.aciklama, "Güncellendi")
        self.assertEqual(len(yuklenen.satirlar), 1)
        s = yuklenen.satirlar[0]
        self.assertEqual(Decimal(str(s.miktar)), Decimal("5"))
        self.assertEqual(Decimal(str(s.kdv_orani)), Decimal("10"))

    def test_3_kdv_oranlari_aninda_hesap(self):
        for oran, beklenen_kdv in (
            (0, Decimal("0.00")),
            (1, Decimal("10.00")),
            (10, Decimal("100.00")),
            (20, Decimal("200.00")),
        ):
            h = satir_iskonto_hesapla(
                miktar=1,
                brut_birim_fiyat=Decimal("1000"),
                iskonto1=0,
                iskonto2=0,
                iskonto3=0,
                kdv_orani=oran,
            )
            self.assertEqual(h["kdv_tutari"], beklenen_kdv, msg=f"KDV %{oran}")

    def test_4_uclu_iskonto_kdv_ornek(self):
        h = satir_iskonto_hesapla(
            miktar=1,
            brut_birim_fiyat=Decimal("1000"),
            iskonto1=10,
            iskonto2=5,
            iskonto3=2,
            kdv_orani=20,
        )
        self.assertEqual(h["iskonto_sonrasi_birim_fiyat"], Decimal("837.90"))
        self.assertEqual(h["kdv_tutari"], Decimal("167.58"))
        self.assertEqual(h["net_tutar"], Decimal("1005.48"))

    def test_6_satir_hatasinda_rollback(self):
        with get_session() as s:
            onceki = int(s.scalar(text("SELECT COUNT(*) FROM satis_faturalari")) or 0)
        with self.assertRaises(ValueError):
            SatisFaturasiService.kaydet(
                self._ust(),
                [
                    self._satir("U1", "Ürün Bir", 1, 100, 20),
                    self._satir("U2", "Ürün İki", -1, 50, 20),
                ],
            )
        with get_session() as s:
            sonra = int(s.scalar(text("SELECT COUNT(*) FROM satis_faturalari")) or 0)
        self.assertEqual(sonra, onceki)

    def test_faturayi_doldur_metodu_var(self):
        from app import SatisFaturasiDialog

        self.assertTrue(callable(getattr(SatisFaturasiDialog, "_faturayi_doldur", None)))
        self.assertTrue(callable(getattr(SatisFaturasiDialog, "_irsaliyeyi_doldur", None)))

    def test_excel_overlay_ve_merge_bug_yok(self):
        metin = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        metin = metin.replace("\r\n", "\n")
        self.assertIn("def _faturayi_doldur", metin)
        self.assertIn("def _tree_excel_cizgileri_temizle", metin)
        # Eski birleşik hata: _irsaliyeyi_doldur satırları doldurduktan sonra
        # clear + fatura yükleme (layout-wire merge)
        irs_bas = metin.find("def _irsaliyeyi_doldur")
        fat_bas = metin.find("def _faturayi_doldur")
        self.assertGreater(irs_bas, -1)
        self.assertGreater(fat_bas, irs_bas)
        self.assertNotIn("fatura = self.fatura", metin[irs_bas:fat_bas])


class FaturaHucreTiklamaTest(unittest.TestCase):
    def test_tek_tik_bind_ve_kdv_yenile(self):
        from fatura_satir_hucre_edit import DUZENLENEBILIR_KOLONLAR

        self.assertIn("kdv", DUZENLENEBILIR_KOLONLAR)
        src = (
            Path(__file__).resolve().parents[1] / "fatura_satir_hucre_edit.py"
        ).read_text(encoding="utf-8")
        self.assertIn("<Button-1>", src)
        self.assertIn("_satir_hucre_etkilesim_kurulu", src)
        self.assertIn("_genel_toplam_duzenleniyor = False", src)

    def test_coklu_iskonto_dugme(self):
        src = (
            Path(__file__).resolve().parents[1] / "fatura_satir_araclar.py"
        ).read_text(encoding="utf-8")
        self.assertIn("Çoklu İskonto", src)


if __name__ == "__main__":
    unittest.main()
