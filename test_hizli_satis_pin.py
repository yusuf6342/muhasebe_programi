"""Hızlı Satış — ÜRÜN EKLE pin + stok grubu (rapor_grubu) testleri.

Çalıştırma: python test_hizli_satis_pin.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.hizli_satis_service import HizliSatisService
from database.models.firma import Firma
from database.models.donem import Donem
from database.models.stok import Depo, StokFiyati, StokKarti, StokLotu, StokSecenek
from database.session_manager import oturum
from database.stok_service import StokService
from hizli_satis_sepet import HizliSatisSepet, VARSAYILAN_KDV
from hizli_satis_urun_panel_ui import _kart_metinleri


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class HizliSatisPinTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_pin.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.hizli_satis  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)

        with Session() as s:
            firma = Firma(firma_kodu="PIN", unvan="Pin Test", aktif=True)
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
            s.add(Depo(ad="Merkez", aktif=True))
            s1 = StokKarti(
                stok_kodu="P001",
                stok_adi="Pin Ürün 1",
                birim="Adet",
                rapor_grubu="ELEKTRONIK",
                aktif=True,
                is_deleted=False,
            )
            s2 = StokKarti(
                stok_kodu="P002",
                stok_adi="Grupsuz Ürün",
                birim="Adet",
                rapor_grubu=None,
                aktif=True,
                is_deleted=False,
            )
            s3 = StokKarti(
                stok_kodu="P003",
                stok_adi="Pin Ürün 3",
                birim="Adet",
                rapor_grubu="ELEKTRONIK",
                barkod="869000111",
                aktif=True,
                is_deleted=False,
            )
            s.add_all([s1, s2, s3])
            s.flush()
            s.add(StokSecenek(tur="rapor_grubu", ad="ELEKTRONIK"))
            s.add(StokSecenek(tur="rapor_grubu", ad="GIDA"))
            s.add(StokFiyati(stok_id=s1.id, fiyat_adi="SATIŞ FİYATI 1", tutar=Decimal("25.50")))
            s.add(StokFiyati(stok_id=s3.id, fiyat_adi="SATIŞ FİYATI 1", tutar=Decimal("10")))
            depo = s.scalar(select(Depo).where(Depo.ad == "Merkez"))
            s.add(
                StokLotu(
                    stok_id=s1.id,
                    depo_id=depo.id,
                    lot_no="L1",
                    giris_tarihi=date(2026, 1, 1),
                    kalan_miktar=Decimal("5"),
                    birim_maliyet=Decimal("1"),
                )
            )
            s.commit()
            self.stok1_id = int(s1.id)
            self.stok2_id = int(s2.id)
            self.stok3_id = int(s3.id)

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
            firma_kodu="PIN",
            firma_unvan="Pin Test",
            firma_uid="pin-test",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)

        HizliSatisService.schema_hazirla()

    def tearDown(self):
        try:
            company_db.close()
        except Exception:
            pass
        oturum.clear()
        self._tmpdir.cleanup()

    def test_01_gruplu_urun_pin(self):
        g = HizliSatisService.hizli_grup_olustur("ELEKTRONIK")
        pin = HizliSatisService.pin_ekle(
            self.stok1_id,
            hizli_satis_grubu_id=g["id"],
            kisa_ad="Pin1",
            varsayilan_miktar=2,
        )
        self.assertTrue(pin["id"])
        urunler = HizliSatisService.pinli_urunleri(grup_kod=g["kod"])["urunler"]
        self.assertEqual(len(urunler), 1)
        self.assertEqual(urunler[0]["kisa_ad"], "Pin1")
        self.assertEqual(Decimal(str(urunler[0]["miktar"])), Decimal("2"))
        self.assertEqual(Decimal(str(urunler[0]["birim_fiyat"])), Decimal("25.50"))

    def test_02_grupsuz_pin_engeli(self):
        g = HizliSatisService.hizli_grup_olustur("TEST")
        with self.assertRaises(ValueError) as ctx:
            HizliSatisService.pin_ekle(self.stok2_id, hizli_satis_grubu_id=g["id"])
        self.assertIn("stok grubuna bağlı değildir", str(ctx.exception))

    def test_03_stok_grubu_ata_sonra_pin(self):
        StokService.stok_rapor_grubu_ata(self.stok2_id, "GIDA")
        with get_session() as session:
            stok = session.get(StokKarti, self.stok2_id)
            self.assertEqual(stok.rapor_grubu, "GIDA")
            sec = session.scalar(
                select(StokSecenek).where(
                    StokSecenek.tur == "rapor_grubu", StokSecenek.ad == "GIDA"
                )
            )
            self.assertIsNotNone(sec)
        g = HizliSatisService.hizli_grup_olustur("GIDA")
        pin = HizliSatisService.pin_ekle(self.stok2_id, hizli_satis_grubu_id=g["id"])
        self.assertTrue(pin["id"])

    def test_04_yeni_stok_grubu_secenek(self):
        ad = StokService.secenek_ekle("rapor_grubu", "YENİGRUP")
        self.assertEqual(ad, "YENİGRUP")
        liste = StokService.secenekleri_listele("rapor_grubu")
        self.assertIn("YENİGRUP", liste)

    def test_05_unique_pin(self):
        g = HizliSatisService.hizli_grup_olustur("ELEKTRONIK")
        HizliSatisService.pin_ekle(self.stok1_id, hizli_satis_grubu_id=g["id"])
        with self.assertRaises(ValueError):
            HizliSatisService.pin_ekle(self.stok1_id, hizli_satis_grubu_id=g["id"])

    def test_06_ayri_hizli_gruplara_ayni_urun(self):
        g1 = HizliSatisService.hizli_grup_olustur("Vitrin A")
        g2 = HizliSatisService.hizli_grup_olustur("Vitrin B")
        HizliSatisService.pin_ekle(self.stok1_id, hizli_satis_grubu_id=g1["id"])
        HizliSatisService.pin_ekle(self.stok1_id, hizli_satis_grubu_id=g2["id"])
        self.assertEqual(
            len(HizliSatisService.pinli_urunleri(grup_kod=g1["kod"])["urunler"]), 1
        )
        self.assertEqual(
            len(HizliSatisService.pinli_urunleri(grup_kod=g2["kod"])["urunler"]), 1
        )

    def test_07_kaldir_stok_silmez(self):
        g = HizliSatisService.hizli_grup_olustur("ELEKTRONIK")
        pin = HizliSatisService.pin_ekle(self.stok1_id, hizli_satis_grubu_id=g["id"])
        sonuc = HizliSatisService.pin_kaldir(pin["id"])
        self.assertTrue(sonuc["stok_var"])
        with get_session() as session:
            stok = session.get(StokKarti, self.stok1_id)
            self.assertIsNotNone(stok)
            self.assertFalse(stok.is_deleted)
            self.assertEqual(stok.stok_kodu, "P001")

    def test_08_toplu_pin_ozet(self):
        g = HizliSatisService.hizli_grup_olustur("ELEKTRONIK")
        HizliSatisService.pin_ekle(self.stok1_id, hizli_satis_grubu_id=g["id"])
        ozet = HizliSatisService.pin_toplu_ekle(
            [self.stok1_id, self.stok3_id, self.stok2_id],
            hizli_satis_grubu_id=g["id"],
        )
        self.assertEqual(ozet["eklenen"], 1)
        self.assertEqual(ozet["atlanan"], 1)
        self.assertEqual(ozet["basarisiz"], 1)

    def test_09_toplu_stok_grubu_ata(self):
        ozet = StokService.stok_rapor_grubu_toplu_ata(
            [self.stok2_id, self.stok3_id], "GIDA"
        )
        self.assertEqual(ozet["guncellenen"], 2)
        with get_session() as session:
            self.assertEqual(session.get(StokKarti, self.stok2_id).rapor_grubu, "GIDA")
            self.assertEqual(session.get(StokKarti, self.stok3_id).rapor_grubu, "GIDA")

    def test_10_fiyat_canli(self):
        g = HizliSatisService.hizli_grup_olustur("ELEKTRONIK")
        HizliSatisService.pin_ekle(self.stok1_id, hizli_satis_grubu_id=g["id"])
        with get_session() as session:
            f = session.scalar(
                select(StokFiyati).where(
                    StokFiyati.stok_id == self.stok1_id,
                    StokFiyati.fiyat_adi == "SATIŞ FİYATI 1",
                )
            )
            f.tutar = Decimal("99.00")
        urun = HizliSatisService.pinli_urunleri(grup_kod=g["kod"])["urunler"][0]
        self.assertEqual(Decimal(str(urun["birim_fiyat"])), Decimal("99.00"))

    def test_11_sepet_merge_varsayilan_miktar(self):
        sepet = HizliSatisSepet()
        sepet.ekle(
            stok_id=self.stok1_id,
            stok_kodu="P001",
            stok_adi="Pin Ürün 1",
            miktar=2,
            birim_fiyat="25.50",
        )
        sepet.ekle(
            stok_id=self.stok1_id,
            stok_kodu="P001",
            stok_adi="Pin Ürün 1",
            miktar=3,
            birim_fiyat="25.50",
        )
        self.assertEqual(len(sepet), 1)
        self.assertEqual(sepet.satirlar[0].miktar, Decimal("5"))
        self.assertEqual(VARSAYILAN_KDV, Decimal("0"))

    def test_12_filtre_grupsuz(self):
        sonuc = StokService.hizli_satis_urun_ara(sadece_grupsuz=True)
        kodlar = {u["stok_kodu"] for u in sonuc["urunler"]}
        self.assertIn("P002", kodlar)
        self.assertNotIn("P001", kodlar)

    def test_13_barkod_hala_calisir(self):
        bulunan = StokService.barkod_ile_bul("869000111")
        self.assertIsNotNone(bulunan)
        self.assertEqual(bulunan["stok_kodu"], "P003")

    def test_14_kart_stok_yok_metni(self):
        metin = _kart_metinleri(
            {
                "stok_kodu": "X",
                "stok_adi": "Boş",
                "birim": "Adet",
                "birim_fiyat": 1,
                "mevcut_stok": 0,
            }
        )
        self.assertEqual(metin["depo"], "STOK YOK")

    def test_15_hizli_grup_stok_grubu_bagimsiz(self):
        g = HizliSatisService.hizli_grup_olustur("Kampanya Rafı")
        pin = HizliSatisService.pin_ekle(self.stok1_id, hizli_satis_grubu_id=g["id"])
        with get_session() as session:
            stok = session.get(StokKarti, self.stok1_id)
            self.assertEqual(stok.rapor_grubu, "ELEKTRONIK")
        self.assertEqual(pin["hizli_satis_grubu"], "Kampanya Rafı")

    def test_16_master_grup_guncellemesi(self):
        StokService.stok_rapor_grubu_ata(self.stok1_id, "GIDA")
        with get_session() as session:
            self.assertEqual(session.get(StokKarti, self.stok1_id).rapor_grubu, "GIDA")

    def test_17_grup_olustur_onaysiz_hata(self):
        with self.assertRaises(ValueError) as ctx:
            HizliSatisService.pin_ekle(
                self.stok1_id,
                grup_adi="YokGrupXYZ",
                grup_olustur_onayli=False,
            )
        self.assertIn("onay", str(ctx.exception).casefold())


def test_smoke_import():
    import hizli_satis_ui  # noqa: F401
    import hizli_satis_urun_ekle_ui  # noqa: F401
    import hizli_satis_urun_panel_ui  # noqa: F401
    from database.models.hizli_satis import HizliSatisGrubu, HizliSatisHizliUrun

    assert HizliSatisGrubu.__tablename__ == "hizli_satis_gruplari"
    assert HizliSatisHizliUrun.__tablename__ == "hizli_satis_hizli_urunler"


if __name__ == "__main__":
    test_smoke_import()
    unittest.main(verbosity=2)
