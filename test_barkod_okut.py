"""Barkod okutma — temizleme, birleştirme anahtarı, arama smoke testleri."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from database.barkod_okut_service import (
    barkod_gecerli_mi,
    barkod_ile_ara,
    barkod_indeksleri_guncelle,
    barkod_temizle,
)
from database.database import Base, _aktif_engine_bagla, company_db
from database.models.cari import Cari, MusteriGrubu
from database.models.donem import Donem
from database.models.finans import FinansHesabi
from database.models.firma import Firma
from database.models.stok import Depo, StokBarkod, StokKarti
from database.session_manager import oturum
from fatura_barkod_ui import _satir_birlestirilebilir


def _sqlite_pragma(dbapi_conn, _connection_record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class BarkodOkutTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "barkod.db"
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
        barkod_indeksleri_guncelle(eng)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        with Session() as s:
            firma = Firma(firma_kodu="BRK", unvan="Barkod Test", aktif=True)
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
            s.add(
                Cari(
                    cari_kodu="M4001",
                    unvan="Barkod Müşteri",
                    cari_turu="Müşteri",
                    aktif=True,
                )
            )
            stok = StokKarti(
                stok_kodu="U4001",
                stok_adi="Barkod Ürün A",
                birim="Adet",
                barkod="8690000000001",
                aktif=True,
                kdv_orani=Decimal("20"),
            )
            s.add(stok)
            s.flush()
            s.add(
                StokBarkod(
                    stok_id=stok.id,
                    barkod="8690000000099",
                    birim="Adet",
                    fiyat=Decimal("0"),
                )
            )
            pasif = StokKarti(
                stok_kodu="U4002",
                stok_adi="Pasif Ürün",
                birim="Adet",
                barkod="8690000000002",
                aktif=False,
                kdv_orani=Decimal("20"),
            )
            s.add(pasif)
            s.commit()

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = self.db_path
        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Test",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="BRK",
            firma_unvan="Barkod Test",
            firma_uid="brk",
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

    def test_temizle(self):
        self.assertEqual(barkod_temizle("  8691\x00  "), "8691")
        self.assertTrue(barkod_gecerli_mi("8691"))
        self.assertFalse(barkod_gecerli_mi("   "))

    def test_ana_barkod(self):
        r = barkod_ile_ara("8690000000001")
        self.assertEqual(r["durum"], "ok")
        self.assertEqual(r["kayit"]["stok_kodu"], "U4001")

    def test_ek_barkod(self):
        r = barkod_ile_ara("8690000000099")
        self.assertEqual(r["durum"], "ok")
        self.assertEqual(r["kayit"]["stok_kodu"], "U4001")

    def test_pasif(self):
        r = barkod_ile_ara("8690000000002")
        self.assertEqual(r["durum"], "pasif")

    def test_bulunamadi(self):
        r = barkod_ile_ara("9999999999999")
        self.assertEqual(r["durum"], "bulunamadi")

    def test_birlestirme_kosulu(self):
        a = {
            "urun_kodu": "U1",
            "birim": "Adet",
            "birim_satis_fiyati": "10",
            "iskonto_orani": "0",
            "iskonto_orani_2": "0",
            "iskonto_orani_3": "0",
            "kdv_orani": "20",
            "aciklama": "",
            "depo": "ANA DEPO",
            "satir_para_birimi": "TRY",
        }
        b = dict(a)
        self.assertTrue(_satir_birlestirilebilir(a, b, depo="ANA DEPO"))
        b2 = dict(a)
        b2["birim_satis_fiyati"] = "12"
        self.assertFalse(_satir_birlestirilebilir(a, b2, depo="ANA DEPO"))
        b3 = dict(a)
        b3["aciklama"] = "özel"
        self.assertFalse(_satir_birlestirilebilir(a, b3, depo="ANA DEPO"))


if __name__ == "__main__":
    unittest.main()
