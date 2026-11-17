"""Geçmiş POS yatış eşleştirme / kullanıcı bildirimi kapanışı — banka bakiyesi 0 etki."""

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
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.database import (
    Base,
    _aktif_engine_bagla,
    company_db,
    finans_hesap_schemasini_guncelle,
    get_session,
)
from database.finans_service import FinansService
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.finans import (
    BankaKarti,
    FinansHareketi,
    FinansHesabi,
    PosValorKaydi,
)
from database.models.firma import Firma
from database.models.sube import Sube
from database.session_manager import oturum


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class PosGecmisYatisKapanisTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "pos_gecmis.db"
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
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="PGEC", unvan="POS Gecmis", aktif=True)
            s.add(firma)
            s.flush()
            s.add(Sube(firma_id=firma.id, sube_kodu="MERKEZ", sube_adi="Merkez", merkez=True, aktif=True))
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
                banka_adi="TEST GECMIS BANK",
                kk_komisyon_orani=Decimal("0"),
                pos_valor_gun=0,
                pos_hedef_hesap_turu="MEVDUAT",
                pos_valor_is_gunu=False,
                pos_otomatik_mahsup=False,
                pos_aktarim_yontemi="MANUEL",
            )
            s.add(banka)
            s.flush()
            for alt in ("MEVDUAT", "KMH", "POS"):
                s.add(
                    FinansHesabi(
                        hesap_adi=f"TEST GECMIS — {alt}",
                        hesap_turu="BANKA",
                        banka_karti_id=banka.id,
                        alt_hesap_turu=alt,
                        acilis_bakiyesi=Decimal("0"),
                    )
                )
            s.commit()
            self.banka_id = banka.id
            self.musteri_id = musteri.id
            self.mevduat_id = next(
                h.id for h in s.scalars(select(FinansHesabi)).all() if h.alt_hesap_turu == "MEVDUAT"
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
            firma_kodu="PGEC",
            firma_unvan="POS Gecmis",
            firma_uid="pgec",
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

    def _mevduat_bakiye(self) -> Decimal:
        with get_session() as s:
            h = s.get(FinansHesabi, self.mevduat_id)
            return Decimal(str(FinansService.bakiye(h))).quantize(Decimal("0.01"))

    def test_senaryo_9800_gecmis_2000_acik_banka_50000(self):
        """İzole örnek: 9800 geçmiş kapanır, 2000 açık kalır, banka 50000 değişmez."""
        with get_session() as s:
            s.add(
                FinansHareketi(
                    hesap_id=self.mevduat_id,
                    tarih=date(2026, 10, 1),
                    hareket_turu="BANKA GİRİŞ",
                    belge_no="ACILIS-MEV",
                    tutar=Decimal("50000.00"),
                    aciklama="Açılış",
                )
            )
            s.commit()
        self.assertEqual(self._mevduat_bakiye(), Decimal("50000.00"))

        eski = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 9, 1),
            "9800",
            cari_id=self.musteri_id,
            komisyon_orani="0",
            valor_tarihi=date(2026, 9, 2),
        )
        yeni = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 10),
            "2000",
            cari_id=self.musteri_id,
            komisyon_orani="0",
            valor_tarihi=date(2026, 11, 11),
        )
        once = FinansService.pos_aktif_alacak_ozeti(banka_karti_id=self.banka_id)
        self.assertEqual(once["net"], Decimal("11800.00"))

        son = FinansService.pos_gecmis_yatis_kapat(
            [eski["kayit_id"]],
            dayanak="Kullanıcı bildirimi: geçmiş tahsilat bankaya yatmış (test).",
            kapanis_turu="KULLANICI_BILDIRIMI",
            kullanici="test",
        )
        self.assertTrue(son[0]["kapatildi"])
        self.assertEqual(son[0]["durum"], "GECMIS_KAPANDI")

        aktif = FinansService.pos_aktif_alacak_ozeti(banka_karti_id=self.banka_id)
        self.assertEqual(aktif["net"], Decimal("2000.00"))
        self.assertEqual(aktif["adet"], 1)
        self.assertEqual(int(aktif["kayitlar"][0].id), int(yeni["kayit_id"]))
        self.assertEqual(self._mevduat_bakiye(), Decimal("50000.00"))

        # Bankaya Aktar ikinci giriş üretmesin
        with self.assertRaises(ValueError):
            FinansService.pos_bankaya_aktar([eski["kayit_id"]], aktarim_tarihi=date(2026, 11, 11))

        # Tekrar çalıştırma — idempotent; açık POS ve banka değişmez
        son2 = FinansService.pos_gecmis_yatis_kapat(
            [eski["kayit_id"]],
            dayanak="Kullanıcı bildirimi: tekrar.",
            kapanis_turu="KULLANICI_BILDIRIMI",
        )
        self.assertTrue(son2[0].get("atlandi"))
        self.assertEqual(FinansService.pos_aktif_alacak_ozeti(banka_karti_id=self.banka_id)["net"], Decimal("2000.00"))
        self.assertEqual(self._mevduat_bakiye(), Decimal("50000.00"))

        # Otomatik tarama geçmiş kapanışı yeniden işlemez (yeni kayıt valörü ileri — yalnız eskiyi dener)
        with get_session() as s:
            s.get(PosValorKaydi, yeni["kayit_id"]).valor_tarihi = date(2026, 12, 31)
            kart = s.get(BankaKarti, self.banka_id)
            kart.pos_otomatik_mahsup = True
            kart.pos_aktarim_yontemi = "OTOMATIK"
            kart.pos_otomatik_baslangic = date(2026, 1, 1)
            s.commit()
        oto = FinansService.pos_valor_vadesi_gelenleri_aktar(sadece_otomatik=True)
        self.assertEqual(
            [x for x in oto if x.get("aktarildi") and int(x.get("kayit_id") or 0) == int(eski["kayit_id"])],
            [],
        )
        with get_session() as s:
            self.assertEqual(s.get(PosValorKaydi, eski["kayit_id"]).durum, "GECMIS_KAPANDI")
        self.assertEqual(FinansService.pos_aktif_alacak_ozeti(banka_karti_id=self.banka_id)["net"], Decimal("2000.00"))
        self.assertEqual(self._mevduat_bakiye(), Decimal("50000.00"))

        # PVA / ikinci banka girişi yok
        with get_session() as s:
            pva = list(
                s.scalars(
                    select(FinansHareketi).where(FinansHareketi.hareket_turu.like("POS VALÖR%"))
                ).all()
            )
            self.assertEqual(pva, [])

    def test_banka_eslesme_mevcut_hareket_pva_yok(self):
        with get_session() as s:
            s.add(
                FinansHareketi(
                    hesap_id=self.mevduat_id,
                    tarih=date(2026, 10, 5),
                    hareket_turu="BANKA GİRİŞ",
                    belge_no="EKSTRE-1",
                    tutar=Decimal("1500.00"),
                    aciklama="POS toplu yatış",
                )
            )
            s.commit()
            hid = s.scalars(select(FinansHareketi).where(FinansHareketi.belge_no == "EKSTRE-1")).one().id
        once_b = self._mevduat_bakiye()
        a = FinansService.pos_tahsilat(
            self.banka_id, date(2026, 10, 1), "1000", cari_id=self.musteri_id, komisyon_orani="0"
        )
        b = FinansService.pos_tahsilat(
            self.banka_id, date(2026, 10, 1), "500", cari_id=self.musteri_id, komisyon_orani="0"
        )
        FinansService.pos_gecmis_yatis_kapat(
            [a["kayit_id"], b["kayit_id"]],
            dayanak="Ekstre satırı EKSTRE-1 ile eşleşti.",
            kapanis_turu="BANKA_ESLESME",
            eslesen_banka_hareket_idler=[hid],
            kullanici="test",
        )
        self.assertEqual(FinansService.pos_aktif_alacak_ozeti(banka_karti_id=self.banka_id)["net"], Decimal("0"))
        self.assertEqual(self._mevduat_bakiye(), once_b)
        with get_session() as s:
            pa = s.get(PosValorKaydi, a["kayit_id"])
            self.assertEqual(pa.durum, "AKTARILDI")
            self.assertEqual(pa.gercek_yatis_tarihi, date(2026, 10, 5))
            self.assertIn(str(hid), pa.eslesen_banka_hareket_idler or "")
            pva = list(
                s.scalars(
                    select(FinansHareketi).where(FinansHareketi.hareket_turu.like("POS VALÖR%"))
                ).all()
            )
            self.assertEqual(pva, [])

    def test_ana_kart_varlik_pos_operasyonel_ledger_degil(self):
        """Ana kart / varlık özeti ledger toplamını değil açık POS alacağını gösterir."""
        with get_session() as s:
            s.add(
                FinansHareketi(
                    hesap_id=self.mevduat_id,
                    tarih=date(2026, 10, 1),
                    hareket_turu="BANKA GİRİŞ",
                    belge_no="ACILIS-2",
                    tutar=Decimal("50000.00"),
                    aciklama="Açılış",
                )
            )
            s.commit()
        eski = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 9, 1),
            "9800",
            cari_id=self.musteri_id,
            komisyon_orani="0",
            valor_tarihi=date(2026, 9, 2),
        )
        FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 10),
            "2000",
            cari_id=self.musteri_id,
            komisyon_orani="0",
            valor_tarihi=date(2026, 11, 20),
        )
        FinansService.pos_gecmis_yatis_kapat(
            [eski["kayit_id"]],
            dayanak="Kullanıcı bildirimi: test ana kart.",
            kapanis_turu="KULLANICI_BILDIRIMI",
            kullanici="test",
        )
        with get_session() as s:
            kart = s.get(BankaKarti, self.banka_id)
            pos = next(h for h in kart.alt_hesaplar if h.alt_hesap_turu == "POS")
            ledger = FinansService.bakiye(pos)
            self.assertEqual(ledger, Decimal("11800.00"))  # 9800+2000 hareket hâlâ durur
            ham = FinansService.banka_bakiyeler(kart)
            self.assertEqual(ham["POS"], Decimal("11800.00"))
            varlik = FinansService.banka_bakiyeler_varlik(kart)
            self.assertEqual(varlik["POS"], Decimal("2000.00"))
            self.assertEqual(FinansService.pos_hesap_gosterim_bakiyesi(pos), Decimal("2000.00"))
            self.assertEqual(FinansService.bakiye(s.get(FinansHesabi, self.mevduat_id)), Decimal("50000.00"))


if __name__ == "__main__":
    unittest.main()
