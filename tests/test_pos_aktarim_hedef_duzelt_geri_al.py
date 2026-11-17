"""POS aktarım hedef düzeltme + geri alma + kart varsayılan hesap id."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import selectinload, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.database import (
    Base,
    _aktif_engine_bagla,
    company_db,
    finans_hesap_schemasini_guncelle,
    get_session,
    pos_sozlesme_schemasini_guncelle,
)
from database.finans_service import FinansService
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.finans import BankaKarti, FinansHesabi, PosValorKaydi
from database.models.firma import Firma
from database.models.sube import Sube
from database.session_manager import oturum


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class PosAktarimHedefDuzeltGeriAlTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "pos_hedef.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        import database.models as modeller

        for bilgi in pkgutil.iter_modules(modeller.__path__):
            importlib.import_module(f"database.models.{bilgi.name}")
        Base.metadata.create_all(eng)
        finans_hesap_schemasini_guncelle(eng)
        pos_sozlesme_schemasini_guncelle(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="POSH", unvan="POS Hedef", aktif=True)
            s.add(firma)
            s.flush()
            s.add(
                Sube(
                    firma_id=firma.id,
                    sube_kodu="MERKEZ",
                    sube_adi="Merkez",
                    merkez=True,
                    aktif=True,
                )
            )
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="2026",
                    baslangic_tarihi=date(2000, 1, 1),
                    bitis_tarihi=date(2099, 12, 31),
                    aktif=True,
                    kapali=False,
                    varsayilan=True,
                )
            )
            musteri = Cari(cari_kodu="M001", unvan="POS Müşteri", cari_turu="Müşteri")
            s.add(musteri)
            banka = BankaKarti(
                banka_adi="TEST HEDEF BANK",
                kk_komisyon_orani=Decimal("0"),
                pos_valor_gun=0,
                pos_hedef_hesap_turu="MEVDUAT",
                pos_valor_is_gunu=False,
                pos_otomatik_mahsup=False,
                pos_aktarim_yontemi="MANUEL",
                kmh_limiti=Decimal("10000"),
            )
            s.add(banka)
            s.flush()
            for alt in ("MEVDUAT", "KMH", "POS"):
                s.add(
                    FinansHesabi(
                        hesap_adi=f"TEST HEDEF BANK — {alt}",
                        hesap_turu="BANKA",
                        banka_karti_id=banka.id,
                        alt_hesap_turu=alt,
                        acilis_bakiyesi=Decimal("0"),
                        aktif=True,
                    )
                )
            s.commit()
            self.banka_id = int(banka.id)
            self.musteri_id = int(musteri.id)
            self.mevduat_id = int(
                s.scalar(
                    select(FinansHesabi.id).where(
                        FinansHesabi.banka_karti_id == banka.id,
                        FinansHesabi.alt_hesap_turu == "MEVDUAT",
                    )
                )
            )
            self.kmh_id = int(
                s.scalar(
                    select(FinansHesabi.id).where(
                        FinansHesabi.banka_karti_id == banka.id,
                        FinansHesabi.alt_hesap_turu == "KMH",
                    )
                )
            )

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = self.db_path
        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="t",
            ad_soyad="Test User",
            role_kod="YONETICI",
            role_ad="Y",
            permissions=set(),
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="POSH",
            firma_unvan="POS Hedef",
            firma_uid="posh",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            oturum.set_period(d.id, d.donem_adi)
        self._audit = patch("database.user_audit.audit_document", return_value=None)
        self._audit.start()
        self._muh = patch("database.muhasebe_entegrasyon.muhasebe_hook", return_value=None)
        self._muh.start()

    def tearDown(self):
        self._muh.stop()
        self._audit.stop()
        try:
            company_db.close()
        except Exception:
            pass
        self._tmpdir.cleanup()

    def _tahsil_ve_aktar(self, brut="1000", hedef=None):
        son = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 1),
            brut,
            cari_id=self.musteri_id,
            komisyon_orani="0",
            hedef_hesap_id=hedef or self.mevduat_id,
        )
        kid = int(son["kayit_id"])
        FinansService.pos_bankaya_aktar(
            [kid],
            hedef_hesap_id=hedef or self.mevduat_id,
            aktarim_tarihi=date(2026, 11, 2),
            valor_kontrol=False,
        )
        return kid

    def _bakiye(self, hesap_id):
        with get_session() as s:
            h = s.scalar(
                select(FinansHesabi)
                .where(FinansHesabi.id == int(hesap_id))
                .options(selectinload(FinansHesabi.hareketler))
            )
            return FinansService.bakiye(h)

    def test_kart_aktarim_hesap_id_oncelikli(self):
        FinansService.banka_karti_kaydet(
            {
                "kart_id": self.banka_id,
                "banka_adi": "TEST HEDEF BANK",
                "pos_aktarim_hesap_id": self.kmh_id,
                "pos_valor_gun": 0,
                "pos_aktarim_yontemi": "MANUEL",
                "kk_komisyon_orani": 0,
                "banka_karti_komisyon_orani": 0,
                "kmh_limiti": 10000,
            }
        )
        kart = FinansService.banka_karti_getir(self.banka_id)
        self.assertEqual(int(kart.pos_aktarim_hesap_id), self.kmh_id)
        self.assertEqual((kart.pos_hedef_hesap_turu or "").upper(), "KMH")
        hedef = FinansService._pos_hedef_hesap(kart)
        self.assertEqual(int(hedef.id), self.kmh_id)

    def test_hedef_duzelt_mevduattan_kmh(self):
        kid = self._tahsil_ve_aktar("2190")
        once_m = self._bakiye(self.mevduat_id)
        once_k = self._bakiye(self.kmh_id)
        self.assertEqual(once_m, Decimal("2190.00"))
        sonuc = FinansService.pos_aktarim_hedef_duzelt(kid, self.kmh_id, gerekce="test düzeltme")
        self.assertTrue(sonuc["degisti"])
        sonuc2 = FinansService.pos_aktarim_hedef_duzelt(kid, self.kmh_id)
        self.assertFalse(sonuc2["degisti"])
        self.assertEqual(self._bakiye(self.mevduat_id), once_m - Decimal("2190.00"))
        self.assertEqual(self._bakiye(self.kmh_id), once_k + Decimal("2190.00"))
        with get_session() as s:
            k = s.get(PosValorKaydi, kid)
            self.assertEqual(k.durum, "AKTARILDI")
            self.assertEqual(Decimal(str(k.gercek_yatis_tutari)), Decimal("2190.00"))
            self.assertEqual(int(k.hedef_hesap_id), self.kmh_id)
            self.assertEqual(FinansService.pos_aktarim_kalan_net(k), Decimal("0"))

    def test_geri_al_ve_otomatik_engel(self):
        kid = self._tahsil_ve_aktar("500")
        FinansService.pos_aktarim_hedef_duzelt(kid, self.kmh_id)
        FinansService.banka_karti_kaydet(
            {
                "kart_id": self.banka_id,
                "banka_adi": "TEST HEDEF BANK",
                "pos_aktarim_hesap_id": self.kmh_id,
                "pos_valor_gun": 0,
                "pos_aktarim_yontemi": "OTOMATIK",
                "pos_otomatik_baslangic": "01.01.2020",
                "kk_komisyon_orani": 0,
                "banka_karti_komisyon_orani": 0,
                "kmh_limiti": 10000,
            }
        )
        once_k = self._bakiye(self.kmh_id)
        FinansService.pos_aktarim_geri_al(kid, gerekce="test geri")
        self.assertEqual(self._bakiye(self.kmh_id), once_k - Decimal("500.00"))
        with get_session() as s:
            k = s.get(PosValorKaydi, kid)
            self.assertEqual(k.durum, "BEKLIYOR")
            self.assertTrue(bool(k.otomatik_aktarim_engel))
            self.assertEqual(Decimal(str(k.gercek_yatis_tutari or 0)), Decimal("0"))
        son = FinansService.pos_valor_vadesi_gelenleri_aktar(
            banka_karti_id=self.banka_id, sadece_otomatik=True
        )
        aktarilan = [x for x in son if x.get("aktarildi")]
        self.assertEqual(aktarilan, [])
        with get_session() as s:
            k = s.get(PosValorKaydi, kid)
            self.assertEqual(k.durum, "BEKLIYOR")
        FinansService.pos_bankaya_aktar(
            [kid],
            hedef_hesap_id=self.kmh_id,
            aktarim_tarihi=date(2026, 11, 3),
            valor_kontrol=False,
        )
        with get_session() as s:
            k = s.get(PosValorKaydi, kid)
            self.assertEqual(k.durum, "AKTARILDI")
            self.assertFalse(bool(k.otomatik_aktarim_engel))

    def test_ortak_pva_tek_pay(self):
        a = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 1),
            "100",
            cari_id=self.musteri_id,
            komisyon_orani="0",
            hedef_hesap_id=self.mevduat_id,
        )
        b = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 1),
            "200",
            cari_id=self.musteri_id,
            komisyon_orani="0",
            hedef_hesap_id=self.mevduat_id,
        )
        ida, idb = int(a["kayit_id"]), int(b["kayit_id"])
        FinansService.pos_bankaya_aktar(
            [ida, idb],
            hedef_hesap_id=self.mevduat_id,
            aktarim_tarihi=date(2026, 11, 2),
            valor_kontrol=False,
        )
        FinansService.pos_aktarim_hedef_duzelt(ida, self.kmh_id)
        self.assertEqual(self._bakiye(self.mevduat_id), Decimal("200.00"))
        self.assertEqual(self._bakiye(self.kmh_id), Decimal("100.00"))
        with get_session() as s:
            ka = s.get(PosValorKaydi, ida)
            kb = s.get(PosValorKaydi, idb)
            self.assertEqual(ka.durum, "AKTARILDI")
            self.assertEqual(kb.durum, "AKTARILDI")
            self.assertEqual(int(ka.hedef_hesap_id), self.kmh_id)
            self.assertEqual(int(kb.hedef_hesap_id), self.mevduat_id)


if __name__ == "__main__":
    unittest.main()
