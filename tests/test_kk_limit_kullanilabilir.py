"""Firma KK kullanılan / kullanılabilir limit — ara talimat senaryoları."""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal as D
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from tests.stok_test_ortami import StokOrtami
from tests.test_gider_kart_odeme import bugun

from database.database import get_session
from database.finans_service import FinansService
from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E
from database.kk_limit_service import limit_kullanimi
from database.models.finans import (
    BankaKarti,
    FinansHareketi,
    FinansHesabi,
    KrediKartiTanimi,
)

BUGUN = date(2026, 11, 13)


class KkLimitKullanilabilirTest(unittest.TestCase):
    def setUp(self):
        self.ort = StokOrtami("kk_limit")
        with get_session() as s:
            banka = BankaKarti(banka_adi="Enpara", sube="Şirketim", aktif=True)
            s.add(banka)
            s.flush()
            mev = FinansHesabi(
                hesap_adi="Enpara Mevduat",
                hesap_turu="BANKA",
                alt_hesap_turu="MEVDUAT",
                banka_karti_id=banka.id,
                acilis_bakiyesi=D("1000000"),
                aktif=True,
            )
            kk = FinansHesabi(
                hesap_adi="Enpara Kredi Kartı",
                hesap_turu="BANKA",
                alt_hesap_turu="KREDI_KARTI",
                banka_karti_id=banka.id,
                acilis_bakiyesi=D("0"),
                aktif=True,
            )
            s.add_all([mev, kk])
            s.flush()
            kart = KrediKartiTanimi(
                banka_karti_id=banka.id,
                kart_adi="Enpara Şirketim",
                hesap_kesim_gunu=7,
                son_odeme_gunu=12,
                kart_limiti=D("524100.00"),
                bagli_hesap_id=kk.id,
                aktif=True,
            )
            s.add(kart)
            s.flush()
            self.banka_id = banka.id
            self.mev_id = mev.id
            self.kk_hesap_id = kk.id
            self.kart_id = kart.id

    def tearDown(self):
        self.ort.kapat()

    def _ledger_borc(self, tutar: D, tur: str = "KK ÖDEME", bel: str = "ACILIS-1"):
        with get_session() as s:
            s.add(
                FinansHareketi(
                    hesap_id=self.kk_hesap_id,
                    tarih=date(2026, 10, 1),
                    hareket_turu=tur,
                    belge_no=bel,
                    tutar=tutar,
                    aciklama="Ledger borç",
                )
            )

    def test_enpara_ornek_524100_391794(self):
        """Plan yok, bağlı hesap borcu var → kullanılan ledger'dan; 132.305,93 kullanılabilir."""
        self._ledger_borc(D("391794.07"))
        oz = E.kart_borc_ozeti(self.kart_id)
        self.assertEqual(oz["kullanilan"], D("391794.07"))
        self.assertEqual(oz["limit"], D("524100.00"))
        self.assertEqual(oz["kullanilabilir"], D("132305.93"))
        self.assertEqual(oz["limit_kaynak"], "bagli_hesap")

    def test_pesin_harcama_limiti_dusurur(self):
        with bugun(BUGUN):
            FinansService.kredi_karti_odeme(
                self.banka_id,
                self.kart_id,
                self.ort.ted_id,
                date(2026, 11, 1),
                "10000",
                cekim_turu="TEK_CEKIM",
            )
        oz = E.kart_borc_ozeti(self.kart_id)
        self.assertEqual(oz["kullanilan"], D("10000.00"))
        self.assertEqual(oz["kullanilabilir"], D("514100.00"))

    def test_taksitli_12000_toplam_tuketir(self):
        with get_session() as s:
            s.get(KrediKartiTanimi, self.kart_id).kart_limiti = D("100000")
        with bugun(BUGUN):
            FinansService.kredi_karti_odeme(
                self.banka_id,
                self.kart_id,
                self.ort.ted_id,
                date(2026, 11, 1),
                "12000",
                cekim_turu="TAKSITLI",
                taksit_sayisi=6,
            )
        oz = E.kart_borc_ozeti(self.kart_id)
        self.assertEqual(oz["kullanilan"], D("12000.00"))
        self.assertEqual(oz["kullanilabilir"], D("88000.00"))

    def test_kismi_odeme_limiti_acar(self):
        with get_session() as s:
            s.get(KrediKartiTanimi, self.kart_id).kart_limiti = D("100000")
        with bugun(BUGUN):
            FinansService.kredi_karti_odeme(
                self.banka_id,
                self.kart_id,
                self.ort.ted_id,
                date(2026, 10, 20),
                "12000",
                cekim_turu="TAKSITLI",
                taksit_sayisi=6,
            )
            ekstre = next(
                h
                for h in E.ekstreleri_hesapla(bugun=BUGUN, kredi_karti_id=self.kart_id)
                if h.get("kalan", 0) > 0
            )
            E.odeme_yap(
                ekstre_id=int(ekstre["ekstre_id"]),
                tutar="2000",
                tarih=BUGUN,
                finans_hesap_id=self.mev_id,
                istek_anahtari="lim-odeme-1",
            )
        oz = E.kart_borc_ozeti(self.kart_id)
        self.assertEqual(oz["kullanilan"], D("10000.00"))
        self.assertEqual(oz["kullanilabilir"], D("90000.00"))

    def test_plan_yeniden_dagitim_limiti_degistirmez(self):
        with get_session() as s:
            s.get(KrediKartiTanimi, self.kart_id).kart_limiti = D("100000")
        with bugun(BUGUN):
            r = FinansService.kredi_karti_odeme(
                self.banka_id,
                self.kart_id,
                self.ort.ted_id,
                date(2026, 11, 1),
                "6000",
                cekim_turu="TAKSITLI",
                taksit_sayisi=6,
            )
        once = E.kart_borc_ozeti(self.kart_id)["kullanilan"]
        from database.kk_plan_service import plani_duzenle

        with patch("database.access.yazma_zorunlu"):
            plani_duzenle(
                int(r["odeme_id"]),
                yeni_kalan_taksit_sayisi=3,
                yeni_baslangic_vade=date(2026, 12, 1),
                aciklama="İç plan test",
            )
        sonra = E.kart_borc_ozeti(self.kart_id)["kullanilan"]
        self.assertEqual(once, sonra)
        self.assertEqual(sonra, D("6000.00"))

    def test_limit_asimi_ve_tanimsiz(self):
        with get_session() as s:
            s.get(KrediKartiTanimi, self.kart_id).kart_limiti = D("5000")
        self._ledger_borc(D("8000"))
        oz = E.kart_borc_ozeti(self.kart_id)
        self.assertEqual(oz["kullanilan"], D("8000.00"))
        self.assertEqual(oz["kullanilabilir"], D("-3000.00"))
        self.assertEqual(oz["limit_asimi"], D("3000.00"))

        with get_session() as s:
            s.get(KrediKartiTanimi, self.kart_id).kart_limiti = D("0")
        oz2 = E.kart_borc_ozeti(self.kart_id)
        self.assertFalse(oz2["limit_tanimli"])
        self.assertIsNone(oz2["kullanilabilir"])
        self.assertEqual(oz2["etiket_kullanilabilir"], "Limit tanımlanmamış")

    def test_tarih_filtresi_guncel_limiti_bozmaz(self):
        """Hareket listesi tarih filtresi ayrı; güncel limit tam durumdan."""
        self._ledger_borc(D("391794.07"))
        lim = limit_kullanimi(self.kart_id)
        # tarih parametresi planı keser ama bağlı hesap güncel kalır
        lim2 = limit_kullanimi(self.kart_id, tarih=date(2020, 1, 1))
        self.assertEqual(lim["kullanilan"], D("391794.07"))
        self.assertEqual(lim2["hesap_borc"], D("391794.07"))
        self.assertTrue(lim.get("tarih_filtre_etkisiz"))

    def test_iki_kart_banka_toplami_tek_karta_yuklenmez(self):
        with get_session() as s:
            banka = s.get(BankaKarti, self.banka_id)
            s.add(
                KrediKartiTanimi(
                    banka_karti_id=banka.id,
                    kart_adi="İkinci Kart",
                    kart_limiti=D("100000"),
                    aktif=True,
                )
            )
            # Ortak hesaba borç — birinci karta bağlı
            s.add(
                FinansHareketi(
                    hesap_id=self.kk_hesap_id,
                    tarih=date(2026, 10, 1),
                    hareket_turu="KK ÖDEME",
                    belge_no="ORTAK-1",
                    tutar=D("50000"),
                )
            )
        oz1 = E.kart_borc_ozeti(self.kart_id)
        self.assertEqual(oz1["kullanilan"], D("50000.00"))
        # İkinci kartın bagli_hesap'ı yok ve bankada 2 kart var → plan=0, banka toplamı yüklenmez
        with get_session() as s:
            k2 = s.scalar(
                select(KrediKartiTanimi).where(KrediKartiTanimi.kart_adi == "İkinci Kart")
            )
            kid2 = int(k2.id)
        oz2 = E.kart_borc_ozeti(kid2)
        self.assertEqual(oz2["kullanilan"], D("0.00"))
        self.assertEqual(oz2["limit_kaynak"], "plan")


if __name__ == "__main__":
    unittest.main()
