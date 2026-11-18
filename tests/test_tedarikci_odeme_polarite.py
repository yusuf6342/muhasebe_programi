"""Tedarikçi ödeme polaritesi — izole test DB (canlı PG yok).

Önemli: ``TahsilatMakbuzuTest`` modül düzeyinde import edilmez; aksi halde
unittest keşfi o sınıftaki tüm testleri de bu modülle birlikte çalıştırır
(uzun süren / yarıda kesilen koşuların kök nedeni).
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from database.database import get_session
from database.finans_service import FinansService
from database.models.cari import CariIslem
from database.models.finans import FinansHareketi, FinansHesabi, KrediKartiOdeme


class TedarikciOdemePolariteTest(unittest.TestCase):
    """TahsilatMakbuzuTest fixture'ını kullanır; onun testlerini tekrar çalıştırmaz."""

    def setUp(self):
        # Geç import: keşif sırasında TestCase alt sınıfı olarak görünmesin.
        from tests.test_tahsilat_makbuzu import TahsilatMakbuzuTest

        self._fx = TahsilatMakbuzuTest("setUp")
        self._fx.setUp()
        self.tedarikci_id = self._fx.tedarikci_id
        self.kasa_id = self._fx.kasa_id
        self.kk_id = self._fx.kk_id
        self.kk_hesap_id = self._fx.kk_hesap_id
        self.mevduat_adi = self._fx.mevduat_adi

    def tearDown(self):
        self._fx.tearDown()

    def _bakiye(self, cari_id):
        return self._fx._bakiye(cari_id)

    def test_senaryo_kismi_odeme_borc_yazar(self):
        # Fixture açılış: 5.000 alacak (tedarikçi borcu)
        m = FinansService.kasa_odeme_makbuzu_kaydet(
            {
                "tarih": date.today(),
                "cari_id": self.tedarikci_id,
                "satirlar": [
                    {"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": "2500"}
                ],
            }
        )
        with get_session() as s:
            ci = s.scalar(select(CariIslem).where(CariIslem.belge_no == m.belge_no))
            self.assertEqual((ci.borc, ci.alacak), (Decimal("2500.00"), Decimal("0.00")))
        ozet = self._bakiye(self.tedarikci_id)
        self.assertEqual((ozet["tutar"], ozet["yon"]), (Decimal("2500.00"), "Alacaklı"))

    def test_tam_odeme_sifir(self):
        FinansService.kasa_odeme_makbuzu_kaydet(
            {
                "tarih": date.today(),
                "cari_id": self.tedarikci_id,
                "satirlar": [
                    {"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": "5000"}
                ],
            }
        )
        ozet = self._bakiye(self.tedarikci_id)
        self.assertEqual((ozet["tutar"], ozet["yon"]), (Decimal("0.00"), "Kapalı"))

    def test_fazla_odeme_avans(self):
        FinansService.kasa_odeme_makbuzu_kaydet(
            {
                "tarih": date.today(),
                "cari_id": self.tedarikci_id,
                "satirlar": [
                    {"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": "6000"}
                ],
            }
        )
        ozet = self._bakiye(self.tedarikci_id)
        self.assertEqual((ozet["tutar"], ozet["yon"]), (Decimal("1000.00"), "Borçlu"))

    def test_firma_kk_tek_karsi_hesap(self):
        m = self._fx._kk_odeme(tutar="2000", taksit=1)
        with get_session() as s:
            ci = s.scalar(select(CariIslem).where(CariIslem.belge_no == m.belge_no))
            self.assertEqual((ci.borc, ci.alacak), (Decimal("2000.00"), Decimal("0.00")))
            ko = s.scalar(select(KrediKartiOdeme).where(KrediKartiOdeme.belge_no.like(f"{m.belge_no}-%")))
            self.assertEqual(ko.tutar, Decimal("2000.00"))
            # Kart hareketi taksit belge no ile yazılır: {odeme}-T1
            fh = list(
                s.scalars(
                    select(FinansHareketi).where(
                        FinansHareketi.belge_no == f"{ko.belge_no}-T1"
                    )
                ).all()
            )
            self.assertEqual(len(fh), 1)
            self.assertEqual(fh[0].hesap_id, self.kk_hesap_id)
            self.assertEqual(fh[0].hareket_turu, "KK ÖDEME")
            self.assertEqual(fh[0].tutar, Decimal("2000.00"))
        self.assertEqual(self._bakiye(self.tedarikci_id)["tutar"], Decimal("3000.00"))

    def test_havale_mevduat_karsi(self):
        m = FinansService.kasa_odeme_makbuzu_kaydet(
            {
                "tarih": date.today(),
                "cari_id": self.tedarikci_id,
                "satirlar": [
                    {"odeme_sekli": "GÖNDERİLEN HAVALE", "hesap": self.mevduat_adi, "tutar": "2500"}
                ],
            }
        )
        with get_session() as s:
            ci = s.scalar(select(CariIslem).where(CariIslem.belge_no == m.belge_no))
            self.assertEqual(ci.borc, Decimal("2500.00"))
            fh = s.scalar(select(FinansHareketi).where(FinansHareketi.belge_no == m.belge_no))
            hesap = s.get(FinansHesabi, fh.hesap_id)
            self.assertEqual(hesap.alt_hesap_turu, "MEVDUAT")
        self.assertEqual(self._bakiye(self.tedarikci_id)["tutar"], Decimal("2500.00"))

    def test_duzenle_iptal_mukerrer_yok(self):
        m = FinansService.kasa_odeme_makbuzu_kaydet(
            {
                "tarih": date.today(),
                "cari_id": self.tedarikci_id,
                "satirlar": [
                    {"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": "2500"}
                ],
            }
        )
        FinansService.kasa_makbuz_guncelle(
            m.id,
            {
                "tarih": date.today(),
                "cari_id": self.tedarikci_id,
                "makbuz_no": m.makbuz_no,
                "satirlar": [
                    {"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": "2000"}
                ],
            },
        )
        with get_session() as s:
            islemler = list(s.scalars(select(CariIslem).where(CariIslem.belge_no == m.belge_no)).all())
            self.assertEqual(len(islemler), 1)
            self.assertEqual(islemler[0].borc, Decimal("2000.00"))
        self.assertEqual(self._bakiye(self.tedarikci_id)["tutar"], Decimal("3000.00"))
        FinansService.kasa_makbuz_iptal(m.id)
        self.assertEqual(self._bakiye(self.tedarikci_id)["tutar"], Decimal("5000.00"))

if __name__ == "__main__":
    unittest.main()
