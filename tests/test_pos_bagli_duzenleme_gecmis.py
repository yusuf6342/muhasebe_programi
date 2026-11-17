"""Aktarılmış POS fiş düzenleme, PVA belge, değişiklik geçmişi, manuel/otomatik."""

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
from database.models.cari import Cari, CariIslem
from database.models.donem import Donem
from database.models.finans import (
    BankaKarti,
    FinansHareketi,
    FinansHesabi,
    PosValorDegisiklik,
    PosValorKaydi,
)
from database.models.firma import Firma
from database.models.sube import Sube
from database.session_manager import oturum


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class PosBagliDuzenlemeTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "pos_bagli.db"
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
            firma = Firma(firma_kodu="POSB", unvan="POS Bagli", aktif=True)
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
                banka_adi="TEST POS BANK",
                kk_komisyon_orani=Decimal("2"),
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
                        hesap_adi=f"TEST POS BANK — {alt}",
                        hesap_turu="BANKA",
                        banka_karti_id=banka.id,
                        alt_hesap_turu=alt,
                        acilis_bakiyesi=Decimal("0"),
                    )
                )
            s.commit()
            self.banka_id = banka.id
            self.musteri_id = musteri.id
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
            firma_kodu="POSB",
            firma_unvan="POS Bagli",
            firma_uid="posb",
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

    def test_aktarilmis_fis_duzenle_cari_ve_pva_tutarli(self):
        r = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 5),
            "1000",
            cari_id=self.musteri_id,
            komisyon_orani="2",
        )
        kid = r["kayit_id"]
        akt = FinansService.pos_bankaya_aktar([kid], aktarim_tarihi=date(2026, 11, 6))
        pva = akt[0]["aktarim_belge_no"]
        # Brüt artırılsın, komisyon değişsin — net 1078; PVA tek kayıt → güncellenir
        r2 = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 5),
            "1100",
            cari_id=self.musteri_id,
            komisyon_orani="2",
            belge_no=r["belge_no"],
        )
        self.assertTrue(r2.get("bagli_guncelleme"))
        self.assertEqual(r2["brut"], Decimal("1100.00"))
        self.assertEqual(r2["net"], Decimal("1078.00"))
        with get_session() as s:
            pv = s.get(PosValorKaydi, kid)
            self.assertEqual(pv.brut_tutar, Decimal("1100.00"))
            self.assertEqual(pv.durum, "AKTARILDI")
            self.assertEqual(Decimal(str(pv.gercek_yatis_tutari)), Decimal("1078.00"))
            # Tek POS tahsilat cari satırı (mükerrer yok)
            cari_satir = list(
                s.scalars(select(CariIslem).where(CariIslem.belge_no == r["belge_no"])).all()
            )
            self.assertEqual(len(cari_satir), 1)
            self.assertEqual(Decimal(str(cari_satir[0].alacak)), Decimal("1100.00"))
            # PVA tutarları yeni net
            pva_h = list(
                s.scalars(select(FinansHareketi).where(FinansHareketi.belge_no == pva)).all()
            )
            self.assertEqual(len(pva_h), 2)
            self.assertTrue(all(Decimal(str(h.tutar)) == Decimal("1078.00") for h in pva_h))
            # İkinci PVA belgesi yok
            pva_adet = len(
                {
                    h.belge_no
                    for h in s.scalars(
                        select(FinansHareketi).where(
                            FinansHareketi.hareket_turu.like("POS VALÖR%")
                        )
                    ).all()
                }
            )
            self.assertEqual(pva_adet, 1)

    def test_aktarilmis_net_aktarilanin_altina_inemez(self):
        r = FinansService.pos_tahsilat(
            self.banka_id, date(2026, 11, 5), "1000", cari_id=self.musteri_id, komisyon_orani="0"
        )
        FinansService.pos_bankaya_aktar([r["kayit_id"]], aktarim_tarihi=date(2026, 11, 6))
        with self.assertRaises(ValueError):
            FinansService.pos_tahsilat(
                self.banka_id,
                date(2026, 11, 5),
                "500",
                cari_id=self.musteri_id,
                komisyon_orani="0",
                belge_no=r["belge_no"],
            )

    def test_degisiklik_gecmisi_eski_yeni_kullanici(self):
        r = FinansService.pos_tahsilat(
            self.banka_id, date(2026, 11, 5), "800", cari_id=self.musteri_id, komisyon_orani="1"
        )
        FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 5),
            "900",
            cari_id=self.musteri_id,
            komisyon_orani="3",
            belge_no=r["belge_no"],
        )
        gecmis = FinansService.pos_degisiklik_gecmisi(r["belge_no"])
        self.assertTrue(gecmis)
        alanlar = {g["alan"] for g in gecmis}
        self.assertIn("brut", alanlar)
        self.assertTrue(any(g["kullanici"] for g in gecmis))
        self.assertTrue(any(g["zaman"] for g in gecmis))
        brut_satir = next(g for g in gecmis if g["alan"] == "brut")
        self.assertEqual(brut_satir["eski"], "800.00")
        self.assertEqual(brut_satir["yeni"], "900.00")

    def test_pva_belge_getir(self):
        r = FinansService.pos_tahsilat(
            self.banka_id, date(2026, 11, 5), "200", cari_id=self.musteri_id, komisyon_orani="0"
        )
        son = FinansService.pos_bankaya_aktar([r["kayit_id"]], aktarim_tarihi=date(2026, 11, 6))
        detay = FinansService.pos_aktarim_belge_getir(son[0]["aktarim_belge_no"])
        self.assertEqual(len(detay["hareketler"]), 2)
        self.assertEqual(len(detay["pos_kayitlari"]), 1)
        self.assertEqual(detay["pos_kayitlari"][0]["belge_no"], r["belge_no"])

    def test_manuel_kartta_otomatik_aktarmaz(self):
        r = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 1),
            "100",
            cari_id=self.musteri_id,
            komisyon_orani="0",
            valor_tarihi=date(2026, 10, 1),
        )
        with get_session() as s:
            kart = s.get(BankaKarti, self.banka_id)
            kart.pos_aktarim_yontemi = "MANUEL"
            kart.pos_otomatik_mahsup = False
            s.commit()
        son = FinansService.pos_valor_vadesi_gelenleri_aktar(sadece_otomatik=True)
        self.assertEqual([x for x in son if x.get("aktarildi")], [])
        with get_session() as s:
            self.assertEqual(s.get(PosValorKaydi, r["kayit_id"]).durum, "BEKLIYOR")

    def test_otomatik_kartta_tek_aktarim_teyit_bekler(self):
        with get_session() as s:
            kart = s.get(BankaKarti, self.banka_id)
            kart.pos_aktarim_yontemi = "OTOMATIK"
            kart.pos_otomatik_mahsup = True
            kart.pos_otomatik_baslangic = date(2026, 1, 1)
            s.commit()
        r = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 1),
            "150",
            cari_id=self.musteri_id,
            komisyon_orani="0",
            valor_tarihi=date(2026, 10, 1),
        )
        son = FinansService.pos_valor_vadesi_gelenleri_aktar(sadece_otomatik=True)
        ok = [x for x in son if x.get("aktarildi")]
        self.assertEqual(len(ok), 1)
        with get_session() as s:
            pv = s.get(PosValorKaydi, r["kayit_id"])
            self.assertEqual(pv.durum, "AKTARILDI")
            self.assertEqual((pv.aktarim_yontemi or "").upper(), "OTOMATIK")
            self.assertFalse(bool(pv.banka_teyidi))
        # Mükerrer otomatik
        son2 = FinansService.pos_valor_vadesi_gelenleri_aktar(sadece_otomatik=True)
        self.assertEqual([x for x in son2 if x.get("aktarildi")], [])

    def test_ayar_degisikligi_gecmisi_yeniden_islemez(self):
        r = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 10, 15),
            "50",
            cari_id=self.musteri_id,
            komisyon_orani="0",
            valor_tarihi=date(2026, 10, 1),
        )
        with get_session() as s:
            kart = s.get(BankaKarti, self.banka_id)
            kart.pos_aktarim_yontemi = "OTOMATIK"
            kart.pos_otomatik_mahsup = True
            # Başlangıç tahsilattan sonra → eski işlem otomatik tarama dışı
            kart.pos_otomatik_baslangic = date(2026, 11, 1)
            s.commit()
        son = FinansService.pos_valor_vadesi_gelenleri_aktar(sadece_otomatik=True)
        self.assertEqual([x for x in son if x.get("aktarildi")], [])
        with get_session() as s:
            self.assertEqual(s.get(PosValorKaydi, r["kayit_id"]).durum, "BEKLIYOR")

    def test_ortak_pva_komisyon_degisince_toplam_yenilenir(self):
        """İki POS aynı PVA’da; birinin neti artınca PVA = Σ gercek_yatis (diğeri korunur)."""
        a = FinansService.pos_tahsilat(
            self.banka_id, date(2026, 11, 5), "1000", cari_id=self.musteri_id, komisyon_orani="2"
        )
        b = FinansService.pos_tahsilat(
            self.banka_id, date(2026, 11, 5), "500", cari_id=self.musteri_id, komisyon_orani="0"
        )
        akt = FinansService.pos_bankaya_aktar(
            [a["kayit_id"], b["kayit_id"]], aktarim_tarihi=date(2026, 11, 6)
        )
        pva = akt[0]["aktarim_belge_no"]
        self.assertEqual(akt[0]["aktarim_belge_no"], akt[1]["aktarim_belge_no"])
        # A: komisyon %2→0, net 980→1000; B 500 korunur → PVA 1500
        FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 5),
            "1000",
            cari_id=self.musteri_id,
            komisyon_orani="0",
            belge_no=a["belge_no"],
        )
        with get_session() as s:
            pa = s.get(PosValorKaydi, a["kayit_id"])
            pb = s.get(PosValorKaydi, b["kayit_id"])
            self.assertEqual(Decimal(str(pa.net_tutar)), Decimal("1000.00"))
            self.assertEqual(Decimal(str(pb.net_tutar)), Decimal("500.00"))
            self.assertEqual(Decimal(str(pa.gercek_yatis_tutari)), Decimal("1000.00"))
            self.assertEqual(Decimal(str(pb.gercek_yatis_tutari)), Decimal("500.00"))
            pva_h = list(
                s.scalars(select(FinansHareketi).where(FinansHareketi.belge_no == pva)).all()
            )
            self.assertEqual(len(pva_h), 2)
            self.assertTrue(all(Decimal(str(h.tutar)) == Decimal("1500.00") for h in pva_h))
            pva_adet = len(
                {
                    h.belge_no
                    for h in s.scalars(
                        select(FinansHareketi).where(
                            FinansHareketi.hareket_turu.like("POS VALÖR%")
                        )
                    ).all()
                }
            )
            self.assertEqual(pva_adet, 1)

    def test_manuel_aktarim_teyit_ayri_islev(self):
        r = FinansService.pos_tahsilat(
            self.banka_id, date(2026, 11, 5), "200", cari_id=self.musteri_id, komisyon_orani="0"
        )
        akt = FinansService.pos_bankaya_aktar([r["kayit_id"]], aktarim_tarihi=date(2026, 11, 6))
        with get_session() as s:
            pv = s.get(PosValorKaydi, r["kayit_id"])
            self.assertEqual(pv.durum, "AKTARILDI")
            self.assertFalse(bool(pv.banka_teyidi))
        son = FinansService.pos_banka_teyidi_ayarla(
            [r["kayit_id"]], teyit=True, notu="Ekstre 06.11 satır 12"
        )
        self.assertTrue(son[0]["banka_teyidi"])
        self.assertIn("Ekstre", son[0]["banka_teyidi_notu"])
        detay = FinansService.pos_aktarim_belge_getir(akt[0]["aktarim_belge_no"])
        self.assertTrue(detay["pos_kayitlari"][0]["banka_teyidi"])
        self.assertEqual(detay["pos_kayitlari"][0]["banka_teyidi_notu"], "Ekstre 06.11 satır 12")
        FinansService.pos_banka_teyidi_ayarla([r["kayit_id"]], teyit=False)
        with get_session() as s:
            self.assertFalse(bool(s.get(PosValorKaydi, r["kayit_id"]).banka_teyidi))


if __name__ == "__main__":
    unittest.main()
