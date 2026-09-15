"""Hızlı Satış Aşama 5–9 — sepet→fatura servis testleri (geçici SQLite).

Talimat §23 senaryolarının otomasyonu (GUI yok).
Çalıştırma: python test_hizli_satis_service.py
"""

from __future__ import annotations

import sys
import tempfile
import traceback
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
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.finans import FinansHesabi
from database.models.firma import Firma
from database.models.satis_faturasi import SatisFaturasi
from database.models.stok import Depo, StokKarti, StokLotu
from database.session_manager import oturum
from hizli_satis_sepet import HizliSatisSepet


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class HizliSatisServiceTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_hs.db"
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
        import database.models.hizli_satis  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)

        with Session() as s:
            firma = Firma(firma_kodu="HST", unvan="HS Test", aktif=True)
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
            s.add(FinansHesabi(hesap_adi="ANA KASA", hesap_turu="KASA", aktif=True))
            cari = Cari(
                cari_kodu="PRK001",
                unvan="PERAKENDE MÜŞTERİ",
                cari_turu="MÜŞTERİ",
                aktif=True,
                acik_hesap_risk_limiti=Decimal("10000"),
            )
            s.add(cari)
            stok = StokKarti(stok_kodu="HS001", stok_adi="Test Ürün", birim="Adet", aktif=True)
            s.add(stok)
            s.flush()
            depo = s.scalar(select(Depo).where(Depo.ad == "ANA DEPO"))
            s.add(
                StokLotu(
                    stok_id=stok.id,
                    depo_id=depo.id,
                    lot_no="L1",
                    giris_tarihi=date.today(),
                    kalan_miktar=Decimal("100"),
                    birim_maliyet=Decimal("5"),
                )
            )
            s.commit()
            self.cari_id = int(cari.id)
            self.stok_id = int(stok.id)

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        company_db._company_id = 99
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
            company_id=99,
            firma_kodu="HST",
            firma_unvan="HS Test",
            firma_uid="hs-test",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            if d:
                oturum.set_period(d.id, d.donem_adi)

        from database import hizli_satis_service as mod

        with mod._token_kilidi:
            mod._kullanilan_tokenler.clear()

    def tearDown(self):
        try:
            company_db.close()
        except Exception:
            pass
        oturum.clear()
        self._tmpdir.cleanup()

    def _sepet(self, miktar="1", fiyat="10") -> HizliSatisSepet:
        sepet = HizliSatisSepet()
        sepet.ekle(
            stok_id=self.stok_id,
            stok_kodu="HS001",
            stok_adi="Test Ürün",
            miktar=miktar,
            birim_fiyat=fiyat,
            kdv_orani=20,
        )
        return sepet

    def test_nakit_satis_onayli_fatura(self):
        sepet = self._sepet("2", "10")  # 20 + KDV%20 = 24
        token = HizliSatisService.yeni_idempotency_token()
        sonuc = HizliSatisService.satisi_tamamla(
            sepet=sepet,
            cari_id=self.cari_id,
            tahsilatlar=[
                {
                    "odeme_sekli": "NAKİT / KASA",
                    "hesap": "ANA KASA",
                    "tutar": Decimal("24.00"),
                }
            ],
            idempotency_token=token,
        )
        self.assertTrue(sonuc["onaylandi"])
        self.assertEqual(sonuc["durum"], "KAPALI")
        self.assertEqual(sonuc["genel_toplam"], Decimal("24.00"))
        self.assertEqual(sonuc["tahsilat_tutari"], Decimal("24.00"))
        with get_session() as s:
            f = s.get(SatisFaturasi, sonuc["fatura_id"])
            self.assertIsNotNone(f)
            self.assertTrue(f.onaylandi)
            self.assertEqual(f.durum, "KAPALI")

    def test_cift_gonderim_reddedilir(self):
        sepet = self._sepet("1", "10")  # 12.00
        token = HizliSatisService.yeni_idempotency_token()
        HizliSatisService.satisi_tamamla(
            sepet=sepet,
            cari_id=self.cari_id,
            tahsilatlar=[
                {"odeme_sekli": "NAKİT / KASA", "hesap": "ANA KASA", "tutar": Decimal("12.00")}
            ],
            idempotency_token=token,
        )
        sepet2 = self._sepet("1", "10")
        with self.assertRaises(ValueError) as ctx:
            HizliSatisService.satisi_tamamla(
                sepet=sepet2,
                cari_id=self.cari_id,
                tahsilatlar=[
                    {"odeme_sekli": "NAKİT / KASA", "hesap": "ANA KASA", "tutar": Decimal("12.00")}
                ],
                idempotency_token=token,
            )
        self.assertIn("çift", str(ctx.exception).casefold())

    def test_yetersiz_stok_reddedilir(self):
        sepet = self._sepet("500", "10")  # lot'ta 100 var
        token = HizliSatisService.yeni_idempotency_token()
        with self.assertRaises(ValueError) as ctx:
            HizliSatisService.satisi_tamamla(
                sepet=sepet,
                cari_id=self.cari_id,
                tahsilatlar=[
                    {
                        "odeme_sekli": "NAKİT / KASA",
                        "hesap": "ANA KASA",
                        "tutar": Decimal("6000.00"),
                    }
                ],
                idempotency_token=token,
            )
        mesaj = str(ctx.exception).casefold()
        self.assertTrue("stok" in mesaj or "yetersiz" in mesaj, mesaj)
        with get_session() as s:
            sayi = len(list(s.scalars(select(SatisFaturasi)).all()))
            self.assertEqual(sayi, 0)

    def _lot_miktar(self) -> Decimal:
        with get_session() as s:
            lot = s.scalar(select(StokLotu).where(StokLotu.stok_id == self.stok_id))
            return Decimal(str(lot.kalan_miktar))

    def test_beklet_stok_dusmez_ve_geri_cagir(self):
        from database.models.hizli_satis import DURUM_BEKLIYOR, DURUM_CAGIRILDI, HizliSatisBekleyen

        HizliSatisService.schema_hazirla()
        once = self._lot_miktar()
        sepet = self._sepet("3", "10")
        sonuc = HizliSatisService.save_hold(
            sepet,
            cari_id=self.cari_id,
            cari_kodu="PRK001",
            cari_unvan="PERAKENDE MÜŞTERİ",
            etiket="Masa-1",
        )
        self.assertGreater(sonuc["id"], 0)
        self.assertEqual(sonuc["satir_sayisi"], 1)
        self.assertEqual(self._lot_miktar(), once, "Beklet stok düşürmemeli")

        liste = HizliSatisService.list_holds()
        self.assertTrue(any(h["id"] == sonuc["id"] for h in liste))

        yuklenen = HizliSatisService.load_hold(sonuc["id"], cagirildi_isaretle=True)
        self.assertEqual(len(yuklenen["satirlar"]), 1)
        self.assertEqual(Decimal(str(yuklenen["satirlar"][0]["miktar"])), Decimal("3"))
        self.assertEqual(Decimal(str(yuklenen["satirlar"][0]["birim_fiyat"])), Decimal("10"))
        self.assertEqual(self._lot_miktar(), once, "Geri çağır stok düşürmemeli")

        liste2 = HizliSatisService.list_holds()
        self.assertFalse(any(h["id"] == sonuc["id"] for h in liste2))

        with get_session() as s:
            b = s.get(HizliSatisBekleyen, sonuc["id"])
            self.assertEqual(b.durum, DURUM_CAGIRILDI)
            self.assertNotEqual(b.durum, DURUM_BEKLIYOR)

        sepet2 = HizliSatisSepet()
        for sat in yuklenen["satirlar"]:
            sepet2.ekle(
                stok_id=sat["stok_id"],
                stok_kodu=sat["stok_kodu"],
                stok_adi=sat["stok_adi"],
                miktar=sat["miktar"],
                birim_fiyat=sat["birim_fiyat"],
                iskonto_orani=sat["iskonto_orani"],
                kdv_orani=sat["kdv_orani"],
                birlestir=False,
            )
        self.assertEqual(len(sepet2), 1)
        self.assertEqual(sepet2.toplamlar()["genel_toplam"], Decimal("36.00"))

    def test_beklet_sil_stok_dokunulmaz(self):
        HizliSatisService.schema_hazirla()
        once = self._lot_miktar()
        sepet = self._sepet("1", "10")
        sonuc = HizliSatisService.save_hold(sepet, cari_id=self.cari_id, etiket="sil")
        HizliSatisService.delete_hold(sonuc["id"])
        self.assertEqual(self._lot_miktar(), once)
        liste = HizliSatisService.list_holds()
        self.assertFalse(any(h["id"] == sonuc["id"] for h in liste))

    def _nakit_satis(self, miktar="2", fiyat="10") -> dict:
        sepet = self._sepet(miktar, fiyat)
        genel = sepet.toplamlar()["genel_toplam"]
        return HizliSatisService.satisi_tamamla(
            sepet=sepet,
            cari_id=self.cari_id,
            tahsilatlar=[
                {
                    "odeme_sekli": "NAKİT / KASA",
                    "hesap": "ANA KASA",
                    "tutar": genel,
                }
            ],
            idempotency_token=HizliSatisService.yeni_idempotency_token(),
            aciklama="Hızlı Satış",
        )

    def test_tam_iptal_stok_geri_alir(self):
        once = self._lot_miktar()
        sonuc = self._nakit_satis("3", "10")  # stok -3
        self.assertEqual(self._lot_miktar(), once - Decimal("3"))

        iptal = HizliSatisService.satisi_iptal(
            sonuc["fatura_id"], neden="Test iptal"
        )
        self.assertEqual(iptal["durum"], "İPTAL")
        self.assertEqual(self._lot_miktar(), once, "İptal stoku geri almalı")

        with get_session() as s:
            f = s.get(SatisFaturasi, sonuc["fatura_id"])
            self.assertEqual(f.durum, "İPTAL")
            self.assertFalse(f.onaylandi)

    def test_kismi_iade_stok_geri_alir(self):
        once = self._lot_miktar()
        sonuc = self._nakit_satis("4", "10")  # -4
        self.assertEqual(self._lot_miktar(), once - Decimal("4"))

        ozet = HizliSatisService.fatura_iade_ozeti(sonuc["fatura_id"])
        self.assertTrue(ozet["tam_iptal_uygun"])
        satir = ozet["satirlar"][0]
        self.assertEqual(satir["kalan_iadeye_uygun"], Decimal("4"))

        iade = HizliSatisService.satisi_iade(
            sonuc["fatura_id"],
            satirlar=[{"satir_id": satir["satir_id"], "miktar": Decimal("1")}],
            neden="Kısmi iade test",
        )
        self.assertEqual(iade["mod"], "iade")
        self.assertEqual(self._lot_miktar(), once - Decimal("3"))

        ozet2 = HizliSatisService.fatura_iade_ozeti(sonuc["fatura_id"])
        self.assertFalse(ozet2["tam_iptal_uygun"])
        self.assertEqual(ozet2["satirlar"][0]["kalan_iadeye_uygun"], Decimal("3"))

        with self.assertRaises(ValueError):
            HizliSatisService.satisi_iptal(sonuc["fatura_id"], neden="olmamalı")

    def test_iptal_yetkisiz_reddedilir(self):
        sonuc = self._nakit_satis("1", "10")
        oturum.set_user(
            user_id=2,
            kullanici_adi="kasiyer",
            ad_soyad="Kasiyer",
            role_kod="SATIS",
            role_ad="Satış",
            permissions={"satis_duzenleme", "yeni_kayit", "iptal"},
        )
        with self.assertRaises(Exception) as ctx:
            HizliSatisService.satisi_iptal(sonuc["fatura_id"], neden="Yetkisiz deneme")
        mesaj = str(ctx.exception).casefold()
        self.assertTrue(
            "yetki" in mesaj or "hizli_satis_iptal" in mesaj,
            mesaj,
        )

    def test_iptal_neden_zorunlu(self):
        sonuc = self._nakit_satis("1", "10")
        with self.assertRaises(ValueError) as ctx:
            HizliSatisService.satisi_iptal(sonuc["fatura_id"], neden="  ")
        self.assertIn("neden", str(ctx.exception).casefold())

    def test_list_recent_hizli_satislar(self):
        sonuc = self._nakit_satis("1", "10")
        liste = HizliSatisService.list_recent_hizli_satislar(sadece_bugun=True)
        self.assertTrue(any(x["fatura_id"] == sonuc["fatura_id"] for x in liste))

    # —— Aşama 9 / talimat §23 ——

    def test_s23_ondalikli_miktar_satis(self):
        """Adetli + ondalıklı miktar (0,5) stok düşümü."""
        once = self._lot_miktar()
        sepet = self._sepet("0.5", "20")  # 10 + KDV%20 = 12
        genel = sepet.toplamlar()["genel_toplam"]
        self.assertEqual(genel, Decimal("12.00"))
        sonuc = HizliSatisService.satisi_tamamla(
            sepet=sepet,
            cari_id=self.cari_id,
            tahsilatlar=[
                {
                    "odeme_sekli": "NAKİT / KASA",
                    "hesap": "ANA KASA",
                    "tutar": genel,
                }
            ],
            idempotency_token=HizliSatisService.yeni_idempotency_token(),
            aciklama="Hızlı Satış",
        )
        self.assertTrue(sonuc["onaylandi"])
        self.assertEqual(self._lot_miktar(), once - Decimal("0.5"))

    def test_s23_parcali_odeme_nakit_ve_acik(self):
        """Parçalı: kısmi nakit + kalan açık hesap."""
        sepet = self._sepet("2", "10")  # 24.00
        sonuc = HizliSatisService.satisi_tamamla(
            sepet=sepet,
            cari_id=self.cari_id,
            tahsilatlar=[
                {
                    "odeme_sekli": "NAKİT / KASA",
                    "hesap": "ANA KASA",
                    "tutar": Decimal("10.00"),
                }
            ],
            idempotency_token=HizliSatisService.yeni_idempotency_token(),
            aciklama="Hızlı Satış",
        )
        self.assertEqual(sonuc["genel_toplam"], Decimal("24.00"))
        self.assertEqual(sonuc["tahsilat_tutari"], Decimal("10.00"))
        self.assertEqual(sonuc["kalan"], Decimal("14.00"))
        self.assertEqual(sonuc["durum"], "AÇIK")

    def test_s23_acik_hesap_yetkisiz_reddedilir(self):
        """Açık hesap / kısmi tahsilat yetki kapısı (servis)."""
        from database.access import AccessError
        from hizli_satis_musteri import IZIN_ACIK_HESAP

        sepet = self._sepet("1", "10")  # 12.00
        oturum.set_user(
            user_id=2,
            kullanici_adi="kasiyer",
            ad_soyad="Kasiyer",
            role_kod="SATIS",
            role_ad="Satış",
            permissions={"satis_duzenleme", "yeni_kayit"},
        )
        self.assertFalse(IZIN_ACIK_HESAP in oturum.permissions)
        with self.assertRaises(AccessError) as ctx:
            HizliSatisService.satisi_tamamla(
                sepet=sepet,
                cari_id=self.cari_id,
                tahsilatlar=[],  # tamamı açık hesap
                idempotency_token=HizliSatisService.yeni_idempotency_token(),
                aciklama="Hızlı Satış",
            )
        mesaj = str(ctx.exception).casefold()
        self.assertTrue("açık hesap" in mesaj or "acik" in mesaj or "yetki" in mesaj, mesaj)
        with get_session() as s:
            self.assertEqual(len(list(s.scalars(select(SatisFaturasi)).all())), 0)

    def test_s23_tam_acik_hesap_yetkili(self):
        sepet = self._sepet("1", "10")  # 12.00
        sonuc = HizliSatisService.satisi_tamamla(
            sepet=sepet,
            cari_id=self.cari_id,
            tahsilatlar=[],
            idempotency_token=HizliSatisService.yeni_idempotency_token(),
            aciklama="Hızlı Satış",
        )
        self.assertEqual(sonuc["tahsilat_tutari"], Decimal("0.00"))
        self.assertEqual(sonuc["kalan"], Decimal("12.00"))
        self.assertEqual(sonuc["durum"], "AÇIK")

    def test_s23_kredi_karti_satis(self):
        with get_session() as s:
            s.add(
                FinansHesabi(
                    hesap_adi="TEST POS",
                    hesap_turu="BANKA",
                    alt_hesap_turu="POS",
                    aktif=True,
                )
            )
            s.commit()
        sepet = self._sepet("1", "10")
        genel = sepet.toplamlar()["genel_toplam"]
        sonuc = HizliSatisService.satisi_tamamla(
            sepet=sepet,
            cari_id=self.cari_id,
            tahsilatlar=[
                {
                    "odeme_sekli": "KREDİ KARTIYLA TAHSİLAT",
                    "hesap": "TEST POS",
                    "tutar": genel,
                }
            ],
            idempotency_token=HizliSatisService.yeni_idempotency_token(),
            aciklama="Hızlı Satış",
        )
        self.assertTrue(sonuc["onaylandi"])
        self.assertEqual(sonuc["durum"], "KAPALI")
        with get_session() as s:
            f = s.get(SatisFaturasi, sonuc["fatura_id"])
            self.assertEqual(f.tahsilat_sekli, "KREDİ KARTIYLA TAHSİLAT")

    def test_s23_tahsilat_asimi_reddedilir(self):
        """Servis fazla tahsilatı reddeder (para üstü UI'da kırpılır)."""
        sepet = self._sepet("1", "10")  # 12.00
        with self.assertRaises(ValueError) as ctx:
            HizliSatisService.satisi_tamamla(
                sepet=sepet,
                cari_id=self.cari_id,
                tahsilatlar=[
                    {
                        "odeme_sekli": "NAKİT / KASA",
                        "hesap": "ANA KASA",
                        "tutar": Decimal("50.00"),
                    }
                ],
                idempotency_token=HizliSatisService.yeni_idempotency_token(),
            )
        self.assertIn("aşamaz", str(ctx.exception).casefold())

    def test_s23_beklet_kalicilik_yeniden_okuma(self):
        """Bekleyen satış DB'de kalır (program kapanıp açılmış gibi yeni oturum)."""
        from sqlalchemy.orm import sessionmaker as sm

        HizliSatisService.schema_hazirla()
        sepet = self._sepet("2", "15")
        kayit = HizliSatisService.save_hold(
            sepet,
            cari_id=self.cari_id,
            cari_kodu="PRK001",
            etiket="Kalicilik-9",
            not_="aşama9",
        )
        hold_id = kayit["id"]

        # Aynı dosyaya yeni session factory — yeniden açılışı simüle
        company_db._session_factory = sm(
            bind=company_db._engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        liste = HizliSatisService.list_holds()
        self.assertTrue(any(h["id"] == hold_id for h in liste), liste)
        yuklenen = HizliSatisService.load_hold(hold_id, cagirildi_isaretle=False)
        self.assertEqual(yuklenen["etiket"], "Kalicilik-9")
        self.assertEqual(len(yuklenen["satirlar"]), 1)
        self.assertEqual(Decimal(str(yuklenen["satirlar"][0]["miktar"])), Decimal("2"))

    def test_s23_gun_sonu_tamamlanan_satislarla_tutarli(self):
        """Gün sonu özeti tamamlanan hızlı satışlarla tutarlı."""
        s1 = self._nakit_satis("2", "10")  # 24.00 nakit
        sepet2 = self._sepet("1", "10")  # 12.00
        s2 = HizliSatisService.satisi_tamamla(
            sepet=sepet2,
            cari_id=self.cari_id,
            tahsilatlar=[
                {
                    "odeme_sekli": "NAKİT / KASA",
                    "hesap": "ANA KASA",
                    "tutar": Decimal("5.00"),
                }
            ],
            idempotency_token=HizliSatisService.yeni_idempotency_token(),
            aciklama="Hızlı Satış",
        )
        ozet = HizliSatisService.gun_sonu_ozeti(date.today())
        self.assertGreaterEqual(ozet["satis_adedi"], 2)
        ids = {s1["fatura_id"], s2["fatura_id"]}
        # Toplamlar en az bu iki satışı kapsar
        self.assertGreaterEqual(ozet["satis_toplami"], Decimal("36.00"))
        self.assertGreaterEqual(ozet["odeme_turleri"]["nakit"], Decimal("29.00"))  # 24+5
        self.assertGreaterEqual(ozet["acik_hesap"], Decimal("7.00"))  # 12-5
        self.assertGreaterEqual(ozet["tahsilat_toplami"], Decimal("29.00"))
        # İptal edilen satış gün sonu aktif listeden düşer
        HizliSatisService.satisi_iptal(s1["fatura_id"], neden="gün sonu test iptal")
        ozet2 = HizliSatisService.gun_sonu_ozeti(date.today())
        self.assertGreaterEqual(ozet2["iptal_adedi"], 1)
        self.assertGreaterEqual(ozet2["satis_adedi"], 1)
        # Kalan aktif satış s2 (s1 iptal)
        self.assertIn(s2["fatura_id"], ids)
        self.assertGreaterEqual(ozet2["satis_toplami"], Decimal("12.00"))

    def test_s23_yazici_hatasi_satisi_geri_almaz(self):
        """Yazıcı/çıktı hatası satış kaydını geri almaz."""
        from unittest.mock import patch

        import hizli_satis_cikti_ui as cikti

        sonuc = self._nakit_satis("1", "10")
        fid = sonuc["fatura_id"]
        with patch.object(
            HizliSatisService,
            "fatura_cikti_verisi",
            side_effect=RuntimeError("yazıcı yok"),
        ), patch.object(cikti, "messagebox") as mb, patch(
            "hizli_satis_cikti_ui.islem_yaz"
        ) as log_mock:
            ok = cikti.fis_yazdir(None, fid)
        self.assertFalse(ok)
        mb.showerror.assert_called()
        log_mock.assert_called()
        with get_session() as s:
            f = s.get(SatisFaturasi, fid)
            self.assertIsNotNone(f)
            self.assertTrue(f.onaylandi)
            self.assertEqual(f.durum, "KAPALI")


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HizliSatisServiceTest)
    sonuc = unittest.TextTestRunner(verbosity=2).run(suite)
    ok = sonuc.wasSuccessful()
    print(
        f"\n{'OK' if ok else 'FAIL'} — test_hizli_satis_service: "
        f"{sonuc.testsRun} test, "
        f"hata={len(sonuc.failures) + len(sonuc.errors)}"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
