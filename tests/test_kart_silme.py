"""Kullanılmamış banka kartı ve firma kredi kartı — kalıcı silme."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from database.access import AccessError
from database.database import _aktif_engine_bagla, company_db, get_session
from database.models.finans import (
    BankAccountMatchRule,
    BankaKarti,
    BankaKaynakEngel,
    BankaKredisi,
    FinansHareketi,
    FinansHesabi,
    KrediKartiEkstre,
    KrediKartiEkstreOdeme,
    KrediKartiOdeme,
    KrediKartiTanimi,
    PosTaksitKomisyon,
    PosValorKaydi,
)
from database.session_manager import oturum


def _pragma(dbapi_connection, _rec):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class KartSilmeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="kart_silme_")
        cls.db_path = Path(cls._tmpdir.name) / "firma.db"
        eng = create_engine(
            f"sqlite:///{cls.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        with eng.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS subeler (id INTEGER PRIMARY KEY)")
        for tablo in (
            BankaKarti.__table__,
            FinansHesabi.__table__,
            FinansHareketi.__table__,
            BankAccountMatchRule.__table__,
            KrediKartiTanimi.__table__,
            KrediKartiOdeme.__table__,
            KrediKartiEkstre.__table__,
            KrediKartiEkstreOdeme.__table__,
            PosTaksitKomisyon.__table__,
            PosValorKaydi.__table__,
            BankaKredisi.__table__,
            BankaKaynakEngel.__table__,
        ):
            tablo.create(bind=eng, checkfirst=True)
        Session = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 77
        company_db._db_path = cls.db_path
        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="test",
            ad_soyad="Test",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=77,
            firma_kodu="KRT",
            firma_unvan="Kart Silme Test",
            firma_uid="kart-silme-test",
            db_path=str(cls.db_path),
        )
        cls._donem = patch(
            "database.donem_service.DonemService.kayit_izinli_mi", return_value=True
        )
        cls._donem.start()
        from database.kart_silme import schema_hazirla

        schema_hazirla(eng)
        cls._engine = eng

    @classmethod
    def tearDownClass(cls):
        cls._donem.stop()
        try:
            company_db.close()
        except Exception:
            pass
        company_db._engine = None
        company_db._session_factory = None
        oturum.clear()
        try:
            cls._engine.dispose()
        except Exception:
            pass
        try:
            cls._tmpdir.cleanup()
        except Exception:
            pass

    def setUp(self):
        oturum.set_user(
            user_id=1,
            kullanici_adi="test",
            ad_soyad="Test",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )

    def _banka(self, ad: str) -> int:
        from database.finans_service import FinansService

        kart = FinansService.banka_karti_kaydet({"banka_adi": ad})
        return int(kart.id)

    def _mevduat_id(self, banka_id: int) -> int:
        with get_session() as s:
            hesap = s.scalar(
                select(FinansHesabi).where(
                    FinansHesabi.banka_karti_id == banka_id,
                    FinansHesabi.alt_hesap_turu == "MEVDUAT",
                )
            )
            self.assertIsNotNone(hesap)
            return int(hesap.id)

    def test_bos_banka_karti_silinir(self):
        from database.finans_service import FinansService

        kid = self._banka("Bos Banka")
        ozet = FinansService.banka_karti_kullanim_ozeti(kid)
        self.assertTrue(ozet["silinebilir"])
        self.assertEqual(ozet["tur_etiket"], "Banka Kartı")
        self.assertIn("Bos Banka", ozet["ad"])
        FinansService.banka_karti_sil(kid, onaylandi=True)
        self.assertIsNone(FinansService.banka_karti_getir(kid))
        with get_session() as s:
            kalan = s.scalar(
                select(func.count()).select_from(FinansHesabi).where(FinansHesabi.banka_karti_id == kid)
            )
            self.assertEqual(int(kalan or 0), 0)
            yer = s.scalar(
                select(func.count())
                .select_from(FinansHesabi)
                .where(FinansHesabi.hesap_adi.like("%Bos Banka%Kredi Kartı%"))
            )
            self.assertEqual(int(yer or 0), 0)

    def test_bos_firma_kk_silinir_ve_yeniden_acilmaz(self):
        from database.finans_service import FinansService
        from database.kart_silme import banka_kaynak_engelli_mi

        kid = self._banka("KK Banka")
        with get_session() as s:
            hesap = FinansHesabi(
                hesap_adi="Ticari Axess KK Banka",
                hesap_turu="KREDİ KARTI",
                alt_hesap_turu="KREDI_KARTI",
                banka_karti_id=kid,
                acilis_bakiyesi=Decimal("0"),
                aktif=True,
            )
            s.add(hesap)
            s.flush()
            tanim = KrediKartiTanimi(
                banka_karti_id=kid,
                kart_adi="Ticari Axess",
                son_dort_hane="4242",
                bagli_hesap_id=hesap.id,
                kart_limiti=Decimal("0"),
                aktif=True,
            )
            s.add(tanim)
            s.flush()
            tid = int(tanim.id)
            hid = int(hesap.id)
        ozet = FinansService.kredi_karti_kullanim_ozeti(tid)
        self.assertTrue(ozet["silinebilir"])
        self.assertEqual(ozet["tur_etiket"], "Firma Kredi Kartı")
        self.assertEqual(ozet["kod"], "4242")
        FinansService.kredi_karti_sil(tid, onaylandi=True)
        self.assertIsNone(FinansService.kredi_karti_getir(tid))
        self.assertIsNotNone(FinansService.banka_karti_getir(kid))
        self.assertTrue(banka_kaynak_engelli_mi("KREDI_KARTI", f"HESAP:{hid}"))
        rapor = FinansService.kredi_kartlari_eslestir(yaz=True)
        self.assertTrue(rapor.get("engelli"))
        self.assertTrue(any("eşleştirme" in (x.get("mesaj") or "") for x in rapor["engelli"]))
        with get_session() as s:
            yeniden = s.scalar(select(KrediKartiTanimi).where(KrediKartiTanimi.bagli_hesap_id == hid))
            self.assertIsNone(yeniden)

    def test_teknik_eslestirme_silinir_aktarim_yeniden_acmaz(self):
        from database.finans_service import FinansService
        from database.kart_silme import banka_kaynak_engelli_mi
        from entegrasyon.banka_kart_import import aktar_satirlari
        from entegrasyon.kasa_banka_import import _banka_hesap_id_esle

        kid = self._banka("Teknik Banka")
        mev = self._mevduat_id(kid)
        with get_session() as s:
            s.add(
                BankAccountMatchRule(
                    evo_banka_id="9001",
                    evo_banka_adi="Teknik Banka TL",
                    banka_karti_id=kid,
                    finans_hesap_id=mev,
                    alt_hesap_turu="MEVDUAT",
                    aktif=True,
                )
            )
        ozet = FinansService.banka_karti_kullanim_ozeti(kid)
        self.assertTrue(ozet["silinebilir"])
        self.assertEqual(ozet["teknik_eslestirme"], 1)
        FinansService.banka_karti_sil(kid, onaylandi=True)
        self.assertIsNone(FinansService.banka_karti_getir(kid))
        self.assertTrue(banka_kaynak_engelli_mi("EVOBULUT", "9001"))
        with get_session() as s:
            kural = s.scalar(
                select(BankAccountMatchRule).where(BankAccountMatchRule.evo_banka_id == "9001")
            )
            self.assertIsNone(kural)
            engel = s.scalar(
                select(BankaKaynakEngel).where(
                    BankaKaynakEngel.kaynak_sistem == "EVOBULUT",
                    BankaKaynakEngel.kaynak_kimlik == "9001",
                )
            )
            self.assertIsNotNone(engel)
            self.assertIn("teknik", (engel.neden or "").lower())
            self.assertEqual(engel.eski_kart_id, kid)
        sonuc = aktar_satirlari(
            [{"id": "9001", "text": "Teknik Banka TL", "DOV_Kodu": "TL", "a_posmu": "0", "a_posgun": "1"}]
        )
        self.assertTrue(any("eşleştirme" in h for h in sonuc.hatalar))
        with get_session() as s:
            adet = s.scalar(
                select(func.count()).select_from(BankaKarti).where(BankaKarti.banka_adi.like("%Teknik Banka%"))
            )
            self.assertEqual(int(adet or 0), 0)
        with self.assertRaises(ValueError) as ctx:
            _banka_hesap_id_esle({"a_banka_id": "9001", "BANKA": "Teknik Banka TL"}, {})
        self.assertIn("eşleştirme", str(ctx.exception).lower())

    def test_sifir_bakiye_gecmis_silinemez_eslestirme_kalir(self):
        from database.finans_service import FinansService

        kid = self._banka("Dolu Banka")
        mev = self._mevduat_id(kid)
        with get_session() as s:
            kk = KrediKartiTanimi(
                banka_karti_id=kid,
                kart_adi="Dolu Kart",
                son_dort_hane="1111",
                aktif=True,
            )
            s.add(kk)
            s.flush()
            for i, tur in enumerate(("KK ÖDEME", "KK ÖDEME", "KK ÖDEME", "KK EKSTRE ÖDEME"), start=1):
                s.add(
                    FinansHareketi(
                        hesap_id=mev,
                        tarih=date.today(),
                        hareket_turu=tur,
                        belge_no=f"SIFIR-{i}",
                        tutar=Decimal("0"),
                    )
                )
            s.add(
                KrediKartiOdeme(
                    belge_no="KK-IPTAL-1",
                    tarih=date.today(),
                    vade_tarihi=date.today(),
                    banka_karti_id=kid,
                    kredi_karti_id=kk.id,
                    cari_id=0,
                    cekim_turu="TEK_CEKIM",
                    taksit_sayisi=1,
                    tutar=Decimal("0"),
                    durum="İPTAL",
                )
            )
            s.add(
                BankAccountMatchRule(
                    evo_banka_id="555",
                    evo_banka_adi="Dolu",
                    banka_karti_id=kid,
                    finans_hesap_id=mev,
                    alt_hesap_turu="MEVDUAT",
                    aktif=True,
                )
            )
        ozet = FinansService.banka_karti_kullanim_ozeti(kid)
        self.assertFalse(ozet["silinebilir"])
        self.assertEqual(ozet["harcama"], 3)
        self.assertEqual(ozet["odeme"], 1)
        self.assertIn("3 harcama ve 1 ödeme hareketi var; silinemez", ozet["engel_mesaji"])
        self.assertIn("iptal", ozet["engel_mesaji"].lower())
        with self.assertRaises(ValueError) as ctx:
            FinansService.banka_karti_sil(kid, onaylandi=True)
        self.assertIn("silinemez", str(ctx.exception).lower())
        self.assertIsNotNone(FinansService.banka_karti_getir(kid))
        with get_session() as s:
            kural = s.scalar(
                select(BankAccountMatchRule).where(BankAccountMatchRule.evo_banka_id == "555")
            )
            self.assertIsNotNone(kural)
            engel = s.scalar(
                select(BankaKaynakEngel).where(BankaKaynakEngel.kaynak_kimlik == "555")
            )
            self.assertIsNone(engel)
        FinansService.banka_karti_pasif_yap(kid)
        self.assertFalse(FinansService.banka_karti_getir(kid).aktif)

    def test_onaysiz_ve_ayni_islemde_yeniden_kontrol(self):
        from database.finans_service import FinansService

        kid = self._banka("Yarış Banka")
        mev = self._mevduat_id(kid)
        with self.assertRaises(ValueError) as ctx:
            FinansService.banka_karti_sil(kid, onaylandi=False)
        self.assertIn("onay", str(ctx.exception).lower())
        self.assertIsNotNone(FinansService.banka_karti_getir(kid))

        oturum.set_user(
            user_id=2,
            kullanici_adi="kisitli",
            ad_soyad="Kısıtlı",
            role_kod="PERSONEL",
            role_ad="Personel",
            permissions=set(),
        )
        try:
            with self.assertRaises(AccessError) as yetki:
                FinansService.banka_karti_sil(kid, onaylandi=True)
            self.assertIn("yetki", str(yetki.exception).lower())
        finally:
            oturum.set_user(
                user_id=1,
                kullanici_adi="test",
                ad_soyad="Test",
                role_kod="YONETICI",
                role_ad="Yönetici",
                permissions=set(),
            )
        self.assertIsNotNone(FinansService.banka_karti_getir(kid))

        with get_session() as s:
            s.add(
                FinansHareketi(
                    hesap_id=mev,
                    tarih=date.today(),
                    hareket_turu="DEVİR",
                    belge_no="DY-0",
                    tutar=Decimal("0"),
                )
            )
            s.flush()
            with self.assertRaises(ValueError) as ayni:
                FinansService.banka_karti_sil(kid, onaylandi=True, session=s)
            self.assertIn("silinemez", str(ayni.exception).lower())
            self.assertIsNotNone(s.get(BankaKarti, kid))


if __name__ == "__main__":
    unittest.main()
