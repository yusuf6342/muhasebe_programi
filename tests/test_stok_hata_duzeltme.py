"""Stok İnceleme Raporu hataları (STK-001…009) — önce hatayı gösteren senaryo, sonra düzeltmenin kabulü.

Her test kendi geçici firma veritabanında çalışır (tests/stok_test_ortami.py).
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402

from database.database import get_session  # noqa: E402
from database.models.stok import Depo, StokBirim, StokHareketi, StokKarti, StokLotu  # noqa: E402
from tests.stok_test_ortami import StokOrtami  # noqa: E402

D = date


class _Taban(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:20])

    def tearDown(self):
        self.o.kapat()

    def assertLotHareketEsit(self, depo=None, kod="U001"):
        self.assertEqual(self.o.lot_toplam(depo, kod), self.o.hareket_bakiye(depo, kod))


class FifoVeEnvanterTest(_Taban):
    def test_s01_fifo_cikis_maliyeti_ve_kalan(self):
        self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        self.o.alis(10, 120, D(2026, 3, 2), lot="L2")
        self.o.satis(12, 200, D(2026, 3, 3))
        with get_session() as s:
            cik = s.scalars(select(StokHareketi).where(StokHareketi.hareket_turu == "FATURA ÇIKIŞ")).all()
            cikis = sum((h.miktar * h.birim_maliyet for h in cik), Decimal("0"))
        self.assertEqual(cikis, Decimal("1240"))
        self.assertEqual(self.o.lot_toplam(), Decimal("8"))
        self.assertEqual(self.o.lot_deger(), Decimal("960"))

    def test_s02_envanter_fifo_degeri_lot_toplami(self):
        """STK-004: en eski lot maliyeti × tüm miktar (2.000) değil, Σ lot (2.200)."""
        from database.rapor_service import RaporService

        self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        self.o.alis(10, 120, D(2026, 3, 2), lot="L2")
        r = RaporService.stok_envanter(tarih=D(2026, 3, 5), maliyet_yontemi="FIFO")
        self.assertEqual(Decimal(str(r["toplam_tutar"])), Decimal("2200"))
        bugun = RaporService.stok_envanter(maliyet_yontemi="FIFO")
        self.assertEqual(Decimal(str(bugun["toplam_tutar"])), self.o.lot_deger())

    def test_s02b_bilanco_ozeti_ayni_fifo_degeri(self):
        from database.rapor_service import RaporService

        self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        self.o.alis(10, 120, D(2026, 3, 2), lot="L2")
        self.o.satis(12, 200, D(2026, 3, 3))
        env = RaporService.stok_envanter(maliyet_yontemi="FIFO", sadece_pozitif=True)
        self.assertEqual(Decimal(str(env["toplam_tutar"])), Decimal("960"))

    def test_s03_gecmis_tarihli_envanter_sonraki_alisi_kullanmaz(self):
        """STK-007: 1 Mart envanteri yalnız L1 (10×100); sonraki alış (150) geçmişi değiştirmez."""
        from database.rapor_service import RaporService

        self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        self.o.satis(10, 200, D(2026, 3, 2))
        self.o.alis(10, 150, D(2026, 3, 3), lot="L2")
        r = RaporService.stok_envanter(tarih=D(2026, 3, 1), maliyet_yontemi="FIFO")
        self.assertEqual(Decimal(str(r["toplam_tutar"])), Decimal("1000"))
        r2 = RaporService.stok_envanter(tarih=D(2026, 3, 2), maliyet_yontemi="FIFO", sadece_pozitif=False)
        self.assertEqual(Decimal(str(r2["toplam_tutar"])), Decimal("0"))
        r3 = RaporService.stok_envanter(tarih=D(2026, 3, 3), maliyet_yontemi="FIFO")
        self.assertEqual(Decimal(str(r3["toplam_tutar"])), Decimal("1500"))

    def test_depo_ayrimi_envanter(self):
        from database.rapor_service import RaporService

        self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        self.o.alis(5, 200, D(2026, 3, 1), lot="L9", depo="DEPO 2")
        ana = RaporService.stok_envanter(maliyet_yontemi="FIFO", depo_adi="ANA DEPO")
        d2 = RaporService.stok_envanter(maliyet_yontemi="FIFO", depo_adi="DEPO 2")
        self.assertEqual(Decimal(str(ana["toplam_tutar"])), Decimal("1000"))
        self.assertEqual(Decimal(str(d2["toplam_tutar"])), Decimal("1000"))
        self.assertEqual(Decimal(str(d2["toplam_miktar"])), Decimal("5"))


class BirimDonusumTest(_Taban):
    def test_s04_alis_koli_temel_birime_cevrilir(self):
        """STK-001: 2 Koli (×12) alış → +24 Adet; lot maliyeti 1.200/12 = 100."""
        f = self.o.alis(2, 1200, D(2026, 3, 1), lot="LK", birim="Koli")
        with get_session() as s:
            lot = s.scalar(select(StokLotu))
            self.assertEqual(Decimal(str(lot.kalan_miktar)), Decimal("24"))
            self.assertEqual(Decimal(str(lot.birim_maliyet)), Decimal("100"))
        satir = f.satirlar[0]
        self.assertEqual(Decimal(str(satir.birim_carpani)), Decimal("12"))
        self.assertEqual(Decimal(str(satir.miktar)), Decimal("2"))
        self.assertLotHareketEsit()
        self.assertEqual(self.o.lot_deger(), Decimal("2400"))

    def test_s05_koli_satis_ve_kar_zarar_maliyeti(self):
        """STK-005: 1 Koli satış stoktan 12 düşer; kâr/zarar maliyeti 12×100 = 1.200."""
        from database.rapor_service import RaporService

        self.o.alis(2, 1200, D(2026, 3, 1), lot="L1", birim="Koli")
        f = self.o.satis(1, 2000, D(2026, 3, 2), birim="Koli")
        self.assertEqual(self.o.lot_toplam(), Decimal("12"))
        self.assertLotHareketEsit()
        r = RaporService.stok_kar_zarar()
        self.assertEqual(Decimal(str(r["toplam_maliyet"])), Decimal("1200"))
        from database.satis_faturasi_service import SatisFaturasiService

        kayit = SatisFaturasiService.getir(f.id)
        self.assertEqual(Decimal(str(kayit.satirlar[0].birim_carpani)), Decimal("12"))

    def test_kart_katsayisi_sonradan_degisince_eski_belge_degismez(self):
        from database.rapor_service import RaporService

        self.o.alis(24, 100, D(2026, 3, 1), lot="L1")
        self.o.satis(1, 2000, D(2026, 3, 2), birim="Koli")
        with get_session() as s:
            b = s.scalar(select(StokBirim).where(StokBirim.birim_adi == "Koli"))
            b.carpan = Decimal("10")
        r = RaporService.stok_kar_zarar()
        self.assertEqual(Decimal(str(r["toplam_maliyet"])), Decimal("1200"))

    def test_tanimsiz_birim_alista_sessizce_1_sayilmaz(self):
        """STK-011: kartta tanımsız 'Paket' birimi → ürün adıyla hata, stok değişmez."""
        from database.stok_service import BirimDonusumHatasi

        with self.assertRaises(BirimDonusumHatasi) as ctx:
            self.o.alis(2, 100, D(2026, 3, 1), birim="Paket")
        self.assertIn("U001", str(ctx.exception))
        self.assertIn("Paket", str(ctx.exception))
        self.assertEqual(self.o.lot_toplam(), Decimal("0"))
        self.assertEqual(self.o.hareket_sayisi(), 0)

    def test_tanimsiz_birim_satis_onayinda_hata(self):
        self.o.alis(10, 100, D(2026, 3, 1))
        with self.assertRaises(ValueError) as ctx:
            self.o.satis(2, 200, D(2026, 3, 2), birim="Paket")
        self.assertIn("Paket", str(ctx.exception))
        self.assertEqual(self.o.lot_toplam(), Decimal("10"))

    def test_buyuk_kucuk_harf_farki_kart_birimi_sayilir(self):
        self.o.alis(3, 100, D(2026, 3, 1), birim="ADET")
        self.assertEqual(self.o.lot_toplam(), Decimal("3"))

    def test_satis_iadesi_koli_temel_birime_doner(self):
        from database.satis_faturasi_service import SatisFaturasiService
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        self.o.alis(24, 100, D(2026, 3, 1), lot="L1")
        f = self.o.satis(1, 2000, D(2026, 3, 2), birim="Koli")
        kaynak = SatisFaturasiService.getir(f.id).satirlar[0]
        SatisIadeFaturasiService.kaydet(
            {"iade_tarihi": D(2026, 3, 3), "cari_id": self.o.mus_id, "depo": "ANA DEPO",
             "kaynak_fatura_id": f.id, "iade_odeme_tutari": Decimal("0")},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("1"), "birim": "Koli",
              "birim_fiyat": Decimal("2000"), "kdv_orani": Decimal("20"),
              "kaynak_fatura_satiri_id": kaynak.id}],
        )
        self.assertEqual(self.o.lot_toplam(), Decimal("24"))
        self.assertLotHareketEsit()
        self.assertEqual(self.o.lot_deger(), Decimal("2400"))


class SatilmisAlisKorumaTest(_Taban):
    def test_s06_kismen_satilmis_alis_duzenlenemez(self):
        """STK-002: 10 alış, 4 satış; stok/maliyet etkili düzenleme engellenir, stok 6 kalır."""
        from database.stok_service import BagliAlisHatasi

        f = self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        sf = self.o.satis(4, 200, D(2026, 3, 2))
        with self.assertRaises(BagliAlisHatasi) as ctx:
            self.o.alis(10, 110, D(2026, 3, 1), lot="L1", fatura_id=f.id, rv=f.row_version)
        mesaj = str(ctx.exception)
        self.assertIn(sf.fatura_no, mesaj)
        self.assertIn("Birim fiyat", mesaj)
        self.assertTrue(ctx.exception.bagli_belgeler)
        self.assertEqual(self.o.lot_toplam(), Decimal("6"))
        self.assertLotHareketEsit()
        self.assertEqual(self.o.lot_deger(), Decimal("600"))

    def test_kismen_satilmis_alista_yalniz_aciklama_degisebilir(self):
        from database.alis_faturasi_service import AlisFaturasiService

        f = self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        self.o.satis(4, 200, D(2026, 3, 2))
        hareket_once = self.o.hareket_sayisi()
        yeni = self.o.alis(10, 100, D(2026, 3, 1), lot="L1", fatura_id=f.id, rv=f.row_version,
                           aciklama="Düzeltilmiş açıklama")
        self.assertEqual(yeni.aciklama, "Düzeltilmiş açıklama")
        self.assertEqual(self.o.hareket_sayisi(), hareket_once)
        self.assertEqual(self.o.lot_toplam(), Decimal("6"))
        self.assertEqual(AlisFaturasiService.getir(f.id).row_version, f.row_version + 1)

    def test_s07_kismen_satilmis_alis_iptal_edilemez(self):
        """STK-003: iptal engellenir; satış iptal edildikten sonra iptal tutarlı ve tekrar etkisiz."""
        from database.alis_faturasi_service import AlisFaturasiService
        from database.satis_faturasi_service import SatisFaturasiService
        from database.stok_service import BagliAlisHatasi

        f = self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        sf = self.o.satis(4, 200, D(2026, 3, 2))
        with self.assertRaises(BagliAlisHatasi) as ctx:
            AlisFaturasiService.iptal_et(f.id)
        self.assertIn("iptal edilemez", str(ctx.exception))
        self.assertEqual(AlisFaturasiService.getir(f.id).durum, "AÇIK")
        self.assertEqual(self.o.lot_toplam(), Decimal("6"))
        self.assertLotHareketEsit()

        SatisFaturasiService.iptal_et(sf.id, "test")
        AlisFaturasiService.iptal_et(f.id)
        self.assertEqual(self.o.lot_toplam(), Decimal("0"))
        self.assertLotHareketEsit()
        sayi = self.o.hareket_sayisi()
        AlisFaturasiService.iptal_et(f.id)
        self.assertEqual(self.o.hareket_sayisi(), sayi)

    def test_transfer_edilmis_alis_da_korunur(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.stok_service import BagliAlisHatasi, StokService

        f = self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        StokService.depo_transfer_kaydet(
            {"cikis_depo": "ANA DEPO", "giris_depo": "DEPO 2", "fis_tarihi": D(2026, 3, 2)},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("3")}],
        )
        with self.assertRaises(BagliAlisHatasi):
            AlisFaturasiService.iptal_et(f.id)

    def test_baglantisiz_alis_duzenlemesi_tek_ve_tutarli_hareket(self):
        f = self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        f2 = self.o.alis(8, 110, D(2026, 3, 1), lot="L1", fatura_id=f.id, rv=f.row_version)
        self.assertEqual(self.o.lot_toplam(), Decimal("8"))
        self.assertEqual(self.o.lot_deger(), Decimal("880"))
        self.assertEqual(self.o.hareket_sayisi("FATURA GİRİŞ"), 1)
        self.assertLotHareketEsit()
        self.o.alis(8, 110, D(2026, 3, 1), lot="L1", fatura_id=f.id, rv=f2.row_version)
        self.assertEqual(self.o.hareket_sayisi("FATURA GİRİŞ"), 1)
        self.assertEqual(self.o.lot_toplam(), Decimal("8"))

    def test_eski_surum_ile_tekrar_kayit_reddedilir(self):
        f = self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        self.o.alis(9, 100, D(2026, 3, 1), lot="L1", fatura_id=f.id, rv=f.row_version)
        with self.assertRaises(ValueError):
            self.o.alis(7, 100, D(2026, 3, 1), lot="L1", fatura_id=f.id, rv=f.row_version)
        self.assertEqual(self.o.lot_toplam(), Decimal("9"))


class TransferTest(_Taban):
    def test_s08_transfer_toplam_degeri_korur(self):
        """STK-006: 10×100 + 10×120; 5 adet transfer FIFO 5×100 taşır, toplam 2.200 değişmez."""
        from database.stok_service import StokService

        self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        self.o.alis(10, 120, D(2026, 3, 2), lot="L2")
        once = self.o.lot_deger()
        agirlikli = StokService.maliyetler("U001", "ANA DEPO")["agirlikli"]
        StokService.depo_transfer_kaydet(
            {"cikis_depo": "ANA DEPO", "giris_depo": "DEPO 2", "fis_tarihi": D(2026, 3, 3)},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("5"), "birim_fiyat": agirlikli}],
        )
        self.assertEqual(self.o.lot_deger(), once)
        self.assertEqual(self.o.lot_deger("DEPO 2"), Decimal("500"))
        self.assertEqual(self.o.lot_toplam("ANA DEPO"), Decimal("15"))
        self.assertEqual(self.o.lot_toplam("DEPO 2"), Decimal("5"))
        self.assertLotHareketEsit("ANA DEPO")
        self.assertLotHareketEsit("DEPO 2")

    def test_transfer_satis_veya_kar_uretmez_ve_lot_bolunur(self):
        from database.rapor_service import RaporService
        from database.stok_service import StokService

        self.o.alis(3, 100, D(2026, 3, 1), lot="L1")
        self.o.alis(10, 120, D(2026, 3, 2), lot="L2")
        StokService.depo_transfer_kaydet(
            {"cikis_depo": "ANA DEPO", "giris_depo": "DEPO 2", "fis_tarihi": D(2026, 3, 3)},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("5")}],
        )
        self.assertEqual(self.o.lot_deger("DEPO 2"), Decimal("540"))
        self.assertEqual(RaporService.stok_kar_zarar()["toplam_maliyet"], Decimal("0"))
        devir = RaporService.stok_devir_hizi(D(2026, 3, 1), D(2026, 3, 31))
        self.assertEqual(sum((s["cogs"] for s in devir["satirlar"]), Decimal("0")), Decimal("0"))
        # Hedef depodan satış, taşınan FIFO maliyetiyle çıkar
        self.o.satis(4, 300, D(2026, 3, 4), depo="DEPO 2")
        with get_session() as s:
            cik = s.scalars(select(StokHareketi).where(StokHareketi.hareket_turu == "FATURA ÇIKIŞ")).all()
            self.assertEqual(sum((h.miktar * h.birim_maliyet for h in cik), Decimal("0")), Decimal("420"))


class SayimTest(_Taban):
    def _ids(self):
        with get_session() as s:
            return (s.scalar(select(Depo.id).where(Depo.ad == "ANA DEPO")),
                    s.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == "U001")))

    def test_s12_sayim_ekran_miktari_bayatsa_ayni_satis_iki_kez_dusmez(self):
        """STK-008: ekran 10 gösterirken 4 satış oldu; 6 sayıldı → stok 6 (2 değil)."""
        from database.stok_sayim_service import StokSayimService

        self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        depo_id, stok_id = self._ids()
        self.o.satis(4, 200, D(2026, 3, 2))
        StokSayimService.kaydet_ve_onayla(depo_id, D(2026, 3, 3), [
            {"stok_id": stok_id, "sistem_miktar": Decimal("10"), "sayilan_miktar": Decimal("6")}])
        self.assertEqual(self.o.lot_toplam(), Decimal("6"))
        self.assertLotHareketEsit()

    def test_sayim_referans_zamanindan_sonraki_satis_korunur(self):
        from database.stok_sayim_service import StokSayimService

        self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        depo_id, stok_id = self._ids()
        sayim_ani = datetime.now()
        # Sayım anında 10 sayıldı; ardından (kayıttan önce) 4 satış yapıldı
        import time

        time.sleep(0.01)
        self.o.satis(4, 200, D(2026, 3, 2))
        StokSayimService.kaydet_ve_onayla(depo_id, D(2026, 3, 3), [
            {"stok_id": stok_id, "sistem_miktar": Decimal("10"), "sayilan_miktar": Decimal("10")}],
            sayim_zamani=sayim_ani)
        self.assertEqual(self.o.lot_toplam(), Decimal("6"))
        self.assertEqual(self.o.hareket_sayisi("SAYIM ÇIKIŞ"), 0)
        self.assertEqual(self.o.hareket_sayisi("SAYIM GİRİŞ"), 0)


class AlisIadesiRaporTest(_Taban):
    def _alis_iadesi(self, miktar):
        from database.alis_iade_faturasi_service import AlisIadeFaturasiService

        return AlisIadeFaturasiService.kaydet_ve_onayla(
            {"iade_tarihi": D(2026, 3, 2), "cari_id": self.o.ted_id, "depo": "ANA DEPO",
             "iade_odeme_tutari": Decimal("0")},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal(str(miktar)), "birim": "Adet",
              "birim_fiyat": Decimal("100"), "kdv_orani": Decimal("20")}],
            kaynaksiz_gerekce="Test: kaynak bağlantısız iade",
        )

    def test_s13_alis_iadesi_devir_hizi_smm_sayilmaz(self):
        """STK-009: alış iadesi devir hızı SMM'sine ve son satış tarihine girmez."""
        from database.rapor_service import RaporService

        self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        self._alis_iadesi(3)
        self.assertEqual(self.o.lot_toplam(), Decimal("7"))
        r = RaporService.stok_devir_hizi(D(2026, 3, 1), D(2026, 3, 31))
        self.assertEqual(sum((s["cogs"] for s in r["satirlar"]), Decimal("0")), Decimal("0"))
        sat = RaporService.satilmayan_urunler(min_gun=0)
        u = next(s for s in sat["satirlar"] if s["stok_kodu"] == "U001")
        self.assertTrue(u["hic_satilmadi"])

    def test_alis_iadesi_ve_satis_birlikte(self):
        from database.rapor_service import RaporService

        self.o.alis(10, 100, D(2026, 3, 1), lot="L1")
        self._alis_iadesi(2)
        self.o.satis(3, 200, D(2026, 3, 3))
        r = RaporService.stok_devir_hizi(D(2026, 3, 1), D(2026, 3, 31))
        self.assertEqual(sum((s["cogs"] for s in r["satirlar"]), Decimal("0")), Decimal("300"))


if __name__ == "__main__":
    unittest.main()
