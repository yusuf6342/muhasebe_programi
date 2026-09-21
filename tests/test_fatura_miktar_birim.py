"""Satış faturası satır — miktar/birim düzenleme (15 senaryo).

Çalıştırma: .venv\\Scripts\\python.exe -m pytest tests/test_fatura_miktar_birim.py -q
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokBirim, StokFiyati, StokHareketi, StokKarti, StokLotu
from database.session_manager import oturum
from database.stok_service import StokService
from fatura_satir_birim_service import (
    birim_degistir,
    birim_satis_fiyati,
    miktar_metnini_coz,
    satir_hesap_ozeti,
    stok_aktif_birimleri,
    temel_miktar,
)


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def _fake_stok(*, ana="Adet", birimler=None, fiyatlar=None):
    birim_ns = []
    for b in birimler or []:
        birim_ns.append(SimpleNamespace(**b))
    fiyat_ns = []
    for f in fiyatlar or []:
        fiyat_ns.append(SimpleNamespace(fiyat_adi=f["adi"], tutar=Decimal(str(f["tutar"]))))
    return SimpleNamespace(
        stok_kodu="X001",
        birim=ana,
        birimler=birim_ns,
        fiyatlar=fiyat_ns,
    )


# 1 Koli = 24 Paket, 1 Paket = 100 Adet → 2 Koli = 4800 Adet
_KOLİ_BIRIMLER = [
    {
        "birim_adi": "Paket",
        "carpan": Decimal("100"),
        "aktif": True,
        "fiyat_modu": "oto",
        "satis_1": None,
        "alis_fiyati": None,
    },
    {
        "birim_adi": "Koli",
        "carpan": Decimal("2400"),
        "aktif": True,
        "fiyat_modu": "oto",
        "satis_1": None,
        "alis_fiyati": None,
    },
]


class MiktarParseTest(unittest.TestCase):
    def test_01_tam_sayi(self):
        self.assertEqual(miktar_metnini_coz("5"), Decimal("5.000000"))

    def test_02_ondalik_tr(self):
        self.assertEqual(miktar_metnini_coz("1,5"), Decimal("1.500000"))
        self.assertEqual(miktar_metnini_coz("10,25"), Decimal("10.250000"))

    def test_03_sifir_negatif_harf(self):
        for metin in ("0", "-1", "abc", "", "  "):
            with self.assertRaises(ValueError):
                miktar_metnini_coz(metin)


class BirimDonusumTest(unittest.TestCase):
    def setUp(self):
        self.stok = _fake_stok(
            birimler=_KOLİ_BIRIMLER,
            fiyatlar=[{"adi": "SATIŞ FİYATI 1", "tutar": "1"}],
        )
        self.patcher = patch(
            "fatura_satir_birim_service._stok_yukle",
            return_value=self.stok,
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_04_ana_dan_alternatife(self):
        satir = {
            "urun_kodu": "X001",
            "miktar": "2400",
            "birim": "Adet",
            "birim_satis_fiyati": "1",
            "manuel_fiyat": False,
        }
        g = birim_degistir(satir, "Koli", manuel_fiyat_modu="yeniden")
        self.assertEqual(Decimal(g["miktar"]), Decimal("1.000000"))
        self.assertEqual(g["birim"], "Koli")
        self.assertEqual(Decimal(g["temel_miktar"]), Decimal("2400.000000"))

    def test_05_alternatiften_anaya(self):
        satir = {
            "urun_kodu": "X001",
            "miktar": "2",
            "birim": "Koli",
            "birim_satis_fiyati": "2400",
            "manuel_fiyat": False,
        }
        g = birim_degistir(satir, "Adet", manuel_fiyat_modu="yeniden")
        self.assertEqual(Decimal(g["miktar"]), Decimal("4800.000000"))
        self.assertEqual(g["birim"], "Adet")
        self.assertEqual(Decimal(g["temel_miktar"]), Decimal("4800.000000"))

    def test_06_cok_seviyeli_koli_paket_adet(self):
        # 2 Koli → temel 4800 Adet; Paket cinsinden 48
        self.assertEqual(temel_miktar(2, "Koli", "X001"), Decimal("4800.000000"))
        self.assertEqual(temel_miktar(48, "Paket", "X001"), Decimal("4800.000000"))
        oniz = StokService.birim_donusum_onizleme(2, "Koli", "Paket", self.stok, "Adet")
        self.assertEqual(oniz["hedef_miktar"], Decimal("48.000000"))
        self.assertEqual(oniz["temel_miktar"], Decimal("4800.000000"))


class BirimFiyatTest(unittest.TestCase):
    def test_07_manuel_birim_fiyatlari(self):
        stok = _fake_stok(
            birimler=[
                {
                    "birim_adi": "Paket",
                    "carpan": Decimal("100"),
                    "aktif": True,
                    "fiyat_modu": "manuel",
                    "satis_1": Decimal("150"),
                    "alis_fiyati": None,
                },
                {
                    "birim_adi": "Koli",
                    "carpan": Decimal("2400"),
                    "aktif": True,
                    "fiyat_modu": "manuel",
                    "satis_1": Decimal("3000"),
                    "alis_fiyati": None,
                },
            ],
            fiyatlar=[{"adi": "SATIŞ FİYATI 1", "tutar": "2"}],
        )
        with patch("fatura_satir_birim_service._stok_yukle", return_value=stok):
            self.assertEqual(birim_satis_fiyati("X001", "Adet"), Decimal("2"))
            self.assertEqual(birim_satis_fiyati("X001", "Paket"), Decimal("150"))
            self.assertEqual(birim_satis_fiyati("X001", "Koli"), Decimal("3000"))

    def test_08_oto_fiyat_carpani(self):
        stok = _fake_stok(
            birimler=[
                {
                    "birim_adi": "Paket",
                    "carpan": Decimal("100"),
                    "aktif": True,
                    "fiyat_modu": "oto",
                    "satis_1": None,
                    "alis_fiyati": None,
                },
            ],
            fiyatlar=[{"adi": "SATIŞ FİYATI 1", "tutar": "1.5"}],
        )
        with patch("fatura_satir_birim_service._stok_yukle", return_value=stok):
            # birim_fiyati_getir oto → 1.5 * 100
            self.assertEqual(birim_satis_fiyati("X001", "Paket"), Decimal("150.0000"))

    def test_09_manuel_fiyat_koru_yeniden(self):
        stok = _fake_stok(
            birimler=_KOLİ_BIRIMLER,
            fiyatlar=[{"adi": "SATIŞ FİYATI 1", "tutar": "1"}],
        )
        satir = {
            "urun_kodu": "X001",
            "miktar": "1",
            "birim": "Paket",
            "birim_satis_fiyati": "99.99",
            "manuel_fiyat": True,
        }
        with patch("fatura_satir_birim_service._stok_yukle", return_value=stok):
            koru = birim_degistir(satir, "Koli", manuel_fiyat_modu="koru")
            self.assertEqual(Decimal(koru["birim_satis_fiyati"]), Decimal("99.99"))
            self.assertTrue(koru["manuel_fiyat"])
            self.assertEqual(koru["manuel_fiyat_birim"], "Koli")
            self.assertEqual(koru["birim"], "Koli")

            yeniden = birim_degistir(satir, "Koli", manuel_fiyat_modu="yeniden")
            self.assertFalse(yeniden["manuel_fiyat"])
            # oto: 1 * 2400
            self.assertEqual(Decimal(yeniden["birim_satis_fiyati"]), Decimal("2400.0000"))

            iptal = birim_degistir(satir, "Koli", manuel_fiyat_modu="iptal")
            self.assertIsNone(iptal)


class BarkodBirimTest(unittest.TestCase):
    def test_10_ayni_birim_birlestir(self):
        from fatura_barkod_ui import _satir_birlestirilebilir

        a = {
            "urun_kodu": "X001",
            "birim": "Paket",
            "birim_satis_fiyati": "10",
            "iskonto_orani": "0",
            "iskonto_orani_2": "0",
            "iskonto_orani_3": "0",
            "kdv_orani": "20",
            "aciklama": "",
            "depo": "ANA DEPO",
            "manuel_fiyat": False,
        }
        b = dict(a)
        self.assertTrue(_satir_birlestirilebilir(a, b, depo="ANA DEPO"))

    def test_11_farkli_birim_ayri_satir(self):
        from fatura_barkod_ui import _satir_birlestirilebilir

        a = {
            "urun_kodu": "X001",
            "birim": "Paket",
            "birim_satis_fiyati": "10",
            "iskonto_orani": "0",
            "iskonto_orani_2": "0",
            "iskonto_orani_3": "0",
            "kdv_orani": "20",
            "aciklama": "",
            "depo": "ANA DEPO",
            "manuel_fiyat": False,
        }
        b = dict(a)
        b["birim"] = "Koli"
        self.assertFalse(_satir_birlestirilebilir(a, b, depo="ANA DEPO"))


class IskontoKdvTest(unittest.TestCase):
    def test_13_iskonto_kdv_yeniden(self):
        stok = _fake_stok(birimler=_KOLİ_BIRIMLER, fiyatlar=[{"adi": "SATIŞ FİYATI 1", "tutar": "1"}])
        satir = {
            "urun_kodu": "X001",
            "miktar": "10",
            "birim": "Adet",
            "birim_satis_fiyati": "100",
            "iskonto_orani": "10",
            "iskonto_orani_2": "0",
            "iskonto_orani_3": "0",
            "kdv_orani": "20",
            "manuel_fiyat": False,
        }
        with patch("fatura_satir_birim_service._stok_yukle", return_value=stok):
            once = satir_hesap_ozeti(satir)
            self.assertEqual(once["brut"], Decimal("1000"))
            self.assertEqual(once["iskonto"], Decimal("100"))
            self.assertEqual(once["matrah"], Decimal("900"))
            self.assertEqual(once["kdv"], Decimal("180.0000"))

            g = birim_degistir(satir, "Paket", manuel_fiyat_modu="yeniden")
            g["iskonto_orani"] = "10"
            g["kdv_orani"] = "20"
            sonra = satir_hesap_ozeti(g)
            # 10 Adet = 0.1 Paket; fiyat oto 100 → brut 10
            self.assertEqual(Decimal(g["miktar"]), Decimal("0.100000"))
            self.assertEqual(sonra["brut"], Decimal("10.00000"))
            self.assertEqual(sonra["matrah"], Decimal("9.00000"))


class StokAktifBirimTest(unittest.TestCase):
    def test_aktif_birim_listesi(self):
        stok = _fake_stok(
            birimler=[
                {
                    "birim_adi": "Paket",
                    "carpan": Decimal("10"),
                    "aktif": True,
                    "fiyat_modu": "oto",
                    "satis_1": None,
                    "alis_fiyati": None,
                },
                {
                    "birim_adi": "Eski",
                    "carpan": Decimal("5"),
                    "aktif": False,
                    "fiyat_modu": "oto",
                    "satis_1": None,
                    "alis_fiyati": None,
                },
            ]
        )
        with patch("fatura_satir_birim_service._stok_yukle", return_value=stok):
            self.assertEqual(stok_aktif_birimleri("X001"), ["Adet", "Paket"])


class FaturaStokEntegrasyonTest(unittest.TestCase):
    """12, 14, 15 — yetersiz stok, tek düşüm, yeniden açma."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_miktar_birim.db"
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
            firma = Firma(firma_kodu="MBR", unvan="Miktar Birim Test", aktif=True)
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
            depo = Depo(ad="ANA DEPO", aktif=True)
            s.add(depo)
            s.flush()
            stok = StokKarti(
                stok_kodu="MB001",
                stok_adi="Birim Ürün",
                birim="Adet",
                aktif=True,
                is_deleted=False,
                minimum_stok=Decimal("0"),
            )
            s.add(stok)
            s.flush()
            s.add(
                StokFiyati(
                    stok_id=stok.id,
                    fiyat_adi="SATIŞ FİYATI 1",
                    tutar=Decimal("1"),
                )
            )
            s.add(
                StokBirim(
                    stok_id=stok.id,
                    birim_adi="Paket",
                    carpan=Decimal("100"),
                    fiyat_modu="oto",
                    aktif=True,
                )
            )
            s.add(
                StokBirim(
                    stok_id=stok.id,
                    birim_adi="Koli",
                    carpan=Decimal("2400"),
                    fiyat_modu="oto",
                    aktif=True,
                )
            )
            s.add(
                StokLotu(
                    stok_id=stok.id,
                    depo_id=depo.id,
                    lot_no="LOT-MB",
                    giris_tarihi=date(2026, 1, 1),
                    kalan_miktar=Decimal("5000"),
                    birim_maliyet=Decimal("0.5"),
                )
            )
            s.add(
                Cari(
                    cari_kodu="M001",
                    unvan="Test Müşteri",
                    cari_turu="Müşteri",
                    aktif=True,
                )
            )
            s.commit()

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
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
            firma_kodu="MBR",
            firma_unvan="Miktar Birim Test",
            firma_uid="mbr-test",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)
            self.cari_id = s.scalar(select(Cari.id).where(Cari.cari_kodu == "M001"))

        self._muhasebe_patch = patch(
            "database.muhasebe_entegrasyon.muhasebe_hook",
            lambda *_a, **_k: None,
        )
        self._muhasebe_patch.start()
        self._sp_patch = patch(
            "database.satis_personeli.secimi_dogrula",
            return_value=(1, "Test Admin"),
        )
        self._sp_patch.start()

    def tearDown(self):
        self._sp_patch.stop()
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

    def _cikis_toplam(self, belge_no: str | None = None) -> Decimal:
        with get_session() as session:
            q = select(func.coalesce(func.sum(StokHareketi.miktar), 0)).where(
                StokHareketi.hareket_turu == "FATURA ÇIKIŞ"
            )
            if belge_no:
                q = q.where(StokHareketi.belge_no == belge_no)
            return Decimal(str(session.scalar(q) or 0))

    def _hareket_sayisi(self) -> int:
        with get_session() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(StokHareketi)
                    .where(StokHareketi.hareket_turu == "FATURA ÇIKIŞ")
                )
                or 0
            )

    def test_12_yetersiz_stok_temel_birim(self):
        # 3 Koli = 7200 Adet > 5000 mevcut
        talep = temel_miktar(3, "Koli", "MB001")
        self.assertEqual(talep, Decimal("7200.000000"))
        with get_session() as session:
            mevcut = session.scalar(
                select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0))
            )
            mevcut = Decimal(str(mevcut or 0))
        self.assertLess(mevcut, talep)
        from database.satis_faturasi_service import SatisFaturasiService

        fatura = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": date(2026, 3, 1),
                "vade_tarihi": date(2026, 3, 1),
                "cari_id": self.cari_id,
                "depo": "ANA DEPO",
                "odeme_tutari": Decimal("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": "MB001",
                    "urun_adi": "Birim Ürün",
                    "miktar": Decimal("3"),
                    "birim": "Koli",
                    "birim_fiyat": Decimal("2400"),
                    "iskonto_orani": Decimal("0"),
                    "kdv_orani": Decimal("20"),
                }
            ],
        )
        self.assertEqual(self._hareket_sayisi(), 0)  # taslak
        with self.assertRaises(ValueError) as ctx:
            SatisFaturasiService.onayla(fatura.id)
        mesaj = str(ctx.exception).casefold()
        self.assertTrue(
            "stok yetersiz" in mesaj or "eksi stoka" in mesaj,
            mesaj,
        )

    def test_14_onayda_tek_dusum_temel(self):
        from database.satis_faturasi_service import SatisFaturasiService

        # 2 Koli = 4800 Adet
        fatura = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": date(2026, 3, 2),
                "vade_tarihi": date(2026, 3, 2),
                "cari_id": self.cari_id,
                "depo": "ANA DEPO",
                "odeme_tutari": Decimal("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": "MB001",
                    "urun_adi": "Birim Ürün",
                    "miktar": Decimal("2"),
                    "birim": "Koli",
                    "birim_fiyat": Decimal("2400"),
                    "iskonto_orani": Decimal("0"),
                    "kdv_orani": Decimal("20"),
                }
            ],
        )
        self.assertEqual(self._hareket_sayisi(), 0)
        SatisFaturasiService.onayla(fatura.id)
        self.assertEqual(self._cikis_toplam(fatura.fatura_no), Decimal("4800"))
        # İkinci onay reddedilmeli
        with self.assertRaises(ValueError):
            SatisFaturasiService.onayla(fatura.id)
        self.assertEqual(self._cikis_toplam(fatura.fatura_no), Decimal("4800"))

    def test_15_kayitli_fatura_yeniden_ac_duzenle(self):
        from database.satis_faturasi_service import SatisFaturasiService

        fatura = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": date(2026, 3, 3),
                "vade_tarihi": date(2026, 3, 3),
                "cari_id": self.cari_id,
                "depo": "ANA DEPO",
                "odeme_tutari": Decimal("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": "MB001",
                    "urun_adi": "Birim Ürün",
                    "miktar": Decimal("1"),
                    "birim": "Paket",
                    "birim_fiyat": Decimal("100"),
                    "iskonto_orani": Decimal("0"),
                    "kdv_orani": Decimal("20"),
                }
            ],
        )
        fid = fatura.id
        # Yeniden aç: miktarı 2 Paket yap (henüz onay yok → stok düşmez)
        SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": date(2026, 3, 3),
                "vade_tarihi": date(2026, 3, 3),
                "cari_id": self.cari_id,
                "depo": "ANA DEPO",
                "odeme_tutari": Decimal("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": "MB001",
                    "urun_adi": "Birim Ürün",
                    "miktar": Decimal("2"),
                    "birim": "Paket",
                    "birim_fiyat": Decimal("100"),
                    "iskonto_orani": Decimal("0"),
                    "kdv_orani": Decimal("20"),
                }
            ],
            fatura_id=fid,
        )
        self.assertEqual(self._hareket_sayisi(), 0)
        getir = SatisFaturasiService.getir(fid)
        self.assertEqual(Decimal(str(getir.satirlar[0].miktar)), Decimal("2"))
        self.assertEqual(getir.satirlar[0].birim, "Paket")
        SatisFaturasiService.onayla(fid)
        self.assertEqual(self._cikis_toplam(getir.fatura_no), Decimal("200"))


if __name__ == "__main__":
    unittest.main()
