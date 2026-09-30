"""Satış irsaliyesi uçtan uca akış testleri (izole geçici SQLite).

Kayıt/yeniden açma, tek stok çıkışı (temel birim), sevk geri alma, silme/iptal,
siparişten kısmi aktarım kalanları, fatura bağı kilitleri ve liste filtreleri.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from database.database import get_session
from database.models.satis_irsaliyesi import SatisIrsaliyesi, SatisIrsaliyesiSatiri
from database.models.satis_siparisi import SatisSiparisiSatiri
from database.models.stok import StokHareketi, StokLotu
from database.satis_irsaliyesi_service import SatisIrsaliyesiService
from tests.test_fatura_miktar_birim import FaturaStokEntegrasyonTest

TARIH = date(2026, 3, 10)


class SatisIrsaliyesiAkisTest(unittest.TestCase):
    setUp = FaturaStokEntegrasyonTest.setUp
    tearDown = FaturaStokEntegrasyonTest.tearDown

    # ---- yardımcılar -------------------------------------------------
    def _veri(self, **ek):
        veri = {"irsaliye_tarihi": TARIH, "cari_id": self.cari_id, "depo": "ANA DEPO"}
        veri.update(ek)
        return veri

    @staticmethod
    def _satir(miktar, birim="Adet", **ek):
        satir = {
            "urun_kodu": "MB001",
            "urun_adi": "Birim Ürün",
            "miktar": Decimal(str(miktar)),
            "birim": birim,
            "birim_fiyat": Decimal("1"),
            "kdv_orani": Decimal("20"),
        }
        satir.update(ek)
        return satir

    def _hareket_toplam(self, tur: str, belge_no: str | None = None) -> Decimal:
        with get_session() as session:
            q = select(func.coalesce(func.sum(StokHareketi.miktar), 0)).where(
                StokHareketi.hareket_turu == tur
            )
            if belge_no:
                q = q.where(StokHareketi.belge_no == belge_no)
            return Decimal(str(session.scalar(q) or 0))

    def _lot_kalan(self) -> Decimal:
        with get_session() as session:
            return Decimal(
                str(session.scalar(select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0))) or 0)
            )

    def _siparis(self, miktar=10, birim="Paket", onayla=True, cari_id=None):
        from database.satis_siparisi_service import SatisSiparisiService

        return SatisSiparisiService.kaydet(
            {
                "siparis_tarihi": date(2026, 3, 1),
                "termin_tarihi": date(2026, 3, 20),
                "cari_id": cari_id or self.cari_id,
                "onayla": onayla,
            },
            [
                {
                    "urun_kodu": "MB001",
                    "urun_adi": "Birim Ürün",
                    "miktar": Decimal(str(miktar)),
                    "birim": birim,
                    "birim_satis_fiyati": Decimal("100"),
                    "kdv_orani": Decimal("20"),
                }
            ],
            [],
        )

    def _sevk_miktari(self, siparis_satiri_id) -> Decimal:
        with get_session() as session:
            return Decimal(
                str(session.get(SatisSiparisiSatiri, siparis_satiri_id).irsaliyelenen_miktar or 0)
            )

    def _fatura_kaydet(self, irsaliye, miktar):
        from database.satis_faturasi_service import SatisFaturasiService

        satir = irsaliye.satirlar[0]
        return SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": TARIH,
                "vade_tarihi": TARIH,
                "cari_id": self.cari_id,
                "depo": "ANA DEPO",
                "irsaliye_id": irsaliye.id,
                "odeme_tutari": Decimal("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": satir.urun_kodu,
                    "urun_adi": satir.urun_adi,
                    "miktar": Decimal(str(miktar)),
                    "birim": satir.birim,
                    "birim_fiyat": Decimal("2400"),
                    "iskonto_orani": Decimal("0"),
                    "kdv_orani": Decimal("20"),
                    "irsaliye_satiri_id": satir.id,
                    "siparis_satiri_id": satir.siparis_satiri_id,
                }
            ],
        )

    # ---- kayıt / doğrulama -------------------------------------------
    def test_eksik_alan_mesajlari(self):
        with self.assertRaisesRegex(ValueError, "Müşteri"):
            SatisIrsaliyesiService.kaydet(self._veri(cari_id=None), [self._satir(1)])
        with self.assertRaisesRegex(ValueError, "satır"):
            SatisIrsaliyesiService.kaydet(self._veri(), [])
        with self.assertRaisesRegex(ValueError, "1. satır"):
            SatisIrsaliyesiService.kaydet(self._veri(), [self._satir(0)])
        with self.assertRaisesRegex(ValueError, "gelecek"):
            SatisIrsaliyesiService.kaydet(
                self._veri(irsaliye_tarihi=date.today() + timedelta(days=3)), [self._satir(1)]
            )
        with self.assertRaisesRegex(ValueError, "tarih"):
            SatisIrsaliyesiService.kaydet(self._veri(irsaliye_tarihi=None), [self._satir(1)])
        with get_session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SatisIrsaliyesi)), 0)

    def test_kaydet_yeniden_ac_ayni_ve_mukerrer_yok(self):
        irs = SatisIrsaliyesiService.kaydet(
            self._veri(aciklama="Test açıklama", sevk_adresi="Depo kapısı 3"),
            [self._satir(2, "Koli"), self._satir(5, "Paket")],
        )
        self.assertEqual(irs.durum, "TASLAK")
        self.assertEqual(self._hareket_toplam("İRSALİYE ÇIKIŞ"), 0)
        acilan = SatisIrsaliyesiService.getir(irs.id)
        self.assertEqual(acilan.aciklama, "Test açıklama")
        self.assertEqual(acilan.sevk_adresi, "Depo kapısı 3")
        self.assertEqual(
            [(s.birim, s.miktar) for s in acilan.satirlar],
            [("Koli", Decimal("2")), ("Paket", Decimal("5"))],
        )
        ilk_idler = [s.id for s in acilan.satirlar]
        # aynı kaydı tekrar kaydet (satır id'leri ile) — mükerrer satır/belge oluşmaz
        satirlar = [
            self._satir(s.miktar, s.birim, irsaliye_satiri_id=s.id) for s in acilan.satirlar
        ]
        satirlar[1]["miktar"] = Decimal("7")
        ikinci = SatisIrsaliyesiService.kaydet(self._veri(), satirlar, irsaliye_id=irs.id)
        self.assertEqual([s.id for s in ikinci.satirlar], ilk_idler)
        self.assertEqual(ikinci.satirlar[1].miktar, Decimal("7"))
        with get_session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SatisIrsaliyesi)), 1)
            self.assertEqual(
                session.scalar(select(func.count()).select_from(SatisIrsaliyesiSatiri)), 2
            )

    def test_ayni_irsaliye_no_ikinci_kez_kaydedilemez(self):
        SatisIrsaliyesiService.kaydet(self._veri(irsaliye_no="IRS-X1"), [self._satir(1)])
        with self.assertRaisesRegex(ValueError, "IRS-X1"):
            SatisIrsaliyesiService.kaydet(self._veri(irsaliye_no="IRS-X1"), [self._satir(1)])

    # ---- stok --------------------------------------------------------
    def test_sevk_tek_cikis_temel_birim_ve_geri_al(self):
        irs = SatisIrsaliyesiService.kaydet(self._veri(), [self._satir(2, "Koli")])
        SatisIrsaliyesiService.sevk_et(irs.id)
        self.assertEqual(self._hareket_toplam("İRSALİYE ÇIKIŞ", irs.irsaliye_no), Decimal("4800"))
        self.assertEqual(self._lot_kalan(), Decimal("200"))
        with self.assertRaises(ValueError):
            SatisIrsaliyesiService.sevk_et(irs.id)
        self.assertEqual(self._hareket_toplam("İRSALİYE ÇIKIŞ"), Decimal("4800"))
        # sevkli belge düzenlenemez
        with self.assertRaisesRegex(ValueError, "Sevki Geri Al"):
            SatisIrsaliyesiService.kaydet(self._veri(), [self._satir(1, "Koli")], irsaliye_id=irs.id)
        geri = SatisIrsaliyesiService.sevk_geri_al(irs.id)
        self.assertEqual(geri.durum, "TASLAK")
        self.assertFalse(geri.stok_cikis_yapildi)
        self.assertEqual(self._hareket_toplam("İRSALİYE ÇIKIŞ"), 0)
        self.assertEqual(self._lot_kalan(), Decimal("5000"))
        duz = SatisIrsaliyesiService.kaydet(
            self._veri(),
            [self._satir(1, "Koli", irsaliye_satiri_id=geri.satirlar[0].id)],
            irsaliye_id=irs.id,
        )
        SatisIrsaliyesiService.sevk_et(duz.id)
        self.assertEqual(self._lot_kalan(), Decimal("2600"))

    def test_yetersiz_stokta_sevk_atomik(self):
        irs = SatisIrsaliyesiService.kaydet(
            self._veri(), [self._satir(1000, "Adet"), self._satir(3, "Koli")]
        )
        with self.assertRaisesRegex(ValueError, "Sevk yapılamadı"):
            SatisIrsaliyesiService.sevk_et(irs.id)
        self.assertEqual(self._hareket_toplam("İRSALİYE ÇIKIŞ"), 0)
        self.assertEqual(self._lot_kalan(), Decimal("5000"))
        self.assertFalse(SatisIrsaliyesiService.getir(irs.id).stok_cikis_yapildi)

    def test_iptal_ve_sil_stogu_geri_verir(self):
        a = SatisIrsaliyesiService.kaydet(self._veri(), [self._satir(10, "Paket")])
        SatisIrsaliyesiService.sevk_et(a.id)
        self.assertEqual(self._lot_kalan(), Decimal("4000"))
        with self.assertRaisesRegex(ValueError, "nedeni"):
            SatisIrsaliyesiService.iptal_et(a.id, "")
        SatisIrsaliyesiService.iptal_et(a.id, "Müşteri vazgeçti")
        self.assertEqual(self._lot_kalan(), Decimal("5000"))
        self.assertEqual(SatisIrsaliyesiService.getir(a.id).durum, "İPTAL")

        b = SatisIrsaliyesiService.kaydet(self._veri(), [self._satir(5, "Paket")])
        SatisIrsaliyesiService.sevk_et(b.id)
        no = SatisIrsaliyesiService.sil(b.id, "Yanlış kayıt")
        self.assertEqual(no, b.irsaliye_no)
        self.assertIsNone(SatisIrsaliyesiService.getir(b.id))
        self.assertEqual(self._lot_kalan(), Decimal("5000"))
        self.assertEqual(self._hareket_toplam("İRSALİYE ÇIKIŞ"), 0)
        with get_session() as session:
            self.assertEqual(
                session.scalar(
                    select(func.count())
                    .select_from(SatisIrsaliyesiSatiri)
                    .where(SatisIrsaliyesiSatiri.irsaliye_id == b.id)
                ),
                0,
            )

    # ---- siparişten aktarım ------------------------------------------
    def test_siparisten_kismi_aktarim_kalanlar(self):
        siparis = self._siparis(10, "Paket")
        ssid = siparis.satirlar[0].id
        irs = SatisIrsaliyesiService.kaydet(
            self._veri(siparis_id=siparis.id), [self._satir(4, "Paket", siparis_satiri_id=ssid)]
        )
        self.assertEqual(self._sevk_miktari(ssid), Decimal("4"))
        # düzenlemede artırma — kendi payı kalan sayılır
        irs = SatisIrsaliyesiService.kaydet(
            self._veri(),
            [self._satir(6, "Paket", siparis_satiri_id=ssid, irsaliye_satiri_id=irs.satirlar[0].id)],
            irsaliye_id=irs.id,
        )
        self.assertEqual(self._sevk_miktari(ssid), Decimal("6"))
        # fazla sevk engeli (hem aynı belgede hem ikinci belgede)
        with self.assertRaisesRegex(ValueError, "kalan sevk"):
            SatisIrsaliyesiService.kaydet(
                self._veri(),
                [self._satir(11, "Paket", siparis_satiri_id=ssid, irsaliye_satiri_id=irs.satirlar[0].id)],
                irsaliye_id=irs.id,
            )
        with self.assertRaisesRegex(ValueError, "kalan sevk"):
            SatisIrsaliyesiService.kaydet(self._veri(), [self._satir(5, "Paket", siparis_satiri_id=ssid)])
        self.assertEqual(self._sevk_miktari(ssid), Decimal("6"))
        # farklı birim engeli
        with self.assertRaisesRegex(ValueError, "birim"):
            SatisIrsaliyesiService.kaydet(self._veri(), [self._satir(1, "Adet", siparis_satiri_id=ssid)])
        # sipariş satırını irsaliyeden çıkar → kalan geri açılır
        irs = SatisIrsaliyesiService.kaydet(
            self._veri(), [self._satir(3, "Adet")], irsaliye_id=irs.id
        )
        self.assertEqual(self._sevk_miktari(ssid), Decimal("0"))
        # kalan kadar ikinci irsaliye, sonra iptal ve silme sayaçları geri alır
        ikinci = SatisIrsaliyesiService.kaydet(
            self._veri(), [self._satir(10, "Paket", siparis_satiri_id=ssid)]
        )
        self.assertEqual(self._sevk_miktari(ssid), Decimal("10"))
        SatisIrsaliyesiService.iptal_et(ikinci.id, "test")
        self.assertEqual(self._sevk_miktari(ssid), Decimal("0"))
        ucuncu = SatisIrsaliyesiService.kaydet(
            self._veri(), [self._satir(2, "Paket", siparis_satiri_id=ssid)]
        )
        SatisIrsaliyesiService.sil(ucuncu.id)
        self.assertEqual(self._sevk_miktari(ssid), Decimal("0"))
        # iptal edilmiş belge silinirse sayaç ikinci kez düşmez
        dorduncu = SatisIrsaliyesiService.kaydet(
            self._veri(), [self._satir(4, "Paket", siparis_satiri_id=ssid)]
        )
        SatisIrsaliyesiService.iptal_et(ikinci.id, "tekrar")  # zaten iptal: etkisiz
        SatisIrsaliyesiService.sil(ikinci.id)
        self.assertEqual(self._sevk_miktari(ssid), Decimal("4"))
        SatisIrsaliyesiService.sil(dorduncu.id)

    def test_taslak_ve_baska_musteri_siparisi_aktarilamaz(self):
        taslak = self._siparis(5, "Paket", onayla=False)
        with self.assertRaisesRegex(ValueError, "TASLAK"):
            SatisIrsaliyesiService.kaydet(
                self._veri(), [self._satir(1, "Paket", siparis_satiri_id=taslak.satirlar[0].id)]
            )
        from database.models.cari import Cari

        with get_session() as session:
            diger = Cari(cari_kodu="M002", unvan="Diğer Müşteri", cari_turu="Müşteri", aktif=True)
            session.add(diger)
            session.flush()
            diger_id = diger.id
        onayli_diger = self._siparis(5, "Paket", cari_id=diger_id)
        with self.assertRaisesRegex(ValueError, "başka müşteri"):
            SatisIrsaliyesiService.kaydet(
                self._veri(), [self._satir(1, "Paket", siparis_satiri_id=onayli_diger.satirlar[0].id)]
            )
        adaylar = SatisIrsaliyesiService.siparis_aktarim_adaylari(self.cari_id)
        self.assertEqual(adaylar, [])
        onayli = self._siparis(8, "Paket")
        adaylar = SatisIrsaliyesiService.siparis_aktarim_adaylari(self.cari_id)
        self.assertEqual([a["siparis_id"] for a in adaylar], [onayli.id])
        self.assertEqual(adaylar[0]["kalan_miktar"], Decimal("8"))

    def test_aktarim_secim_kalani_form_ve_kayit_payi(self):
        from database.kalan_belge_service import siparis_irsaliye_secim_satirlari
        from database.satis_siparisi_service import SatisSiparisiService

        siparis = self._siparis(10, "Paket")
        ssid = siparis.satirlar[0].id
        irs = SatisIrsaliyesiService.kaydet(
            self._veri(), [self._satir(4, "Paket", siparis_satiri_id=ssid)]
        )
        adaylar = SatisIrsaliyesiService.siparis_aktarim_adaylari(self.cari_id, irsaliye_id=irs.id)
        self.assertEqual(adaylar[0]["kalan_miktar"], Decimal("10"))
        guncel = SatisSiparisiService.getir(siparis.id)
        # formda hâlâ 4 duruyor → yalnız 6 aktarılabilir
        secim = siparis_irsaliye_secim_satirlari(
            guncel,
            form_satirlar=[{"siparis_satiri_id": ssid, "miktar": Decimal("4")}],
            bu_irsaliye_db_satirlar=irs.satirlar,
        )
        self.assertEqual(secim[0]["kalan_miktar"], Decimal("6"))
        # formdan silinmiş (henüz kaydedilmemiş) → 10 aktarılabilir
        secim = siparis_irsaliye_secim_satirlari(
            guncel, form_satirlar=[], bu_irsaliye_db_satirlar=irs.satirlar
        )
        self.assertEqual(secim[0]["kalan_miktar"], Decimal("10"))
        # yeni (kaydedilmemiş) irsaliye formu: kayıtlı pay yok
        secim = siparis_irsaliye_secim_satirlari(guncel, form_satirlar=[])
        self.assertEqual(secim[0]["kalan_miktar"], Decimal("6"))

    # ---- fatura bağı -------------------------------------------------
    def test_faturali_irsaliye_kilitli_ve_ikinci_stok_cikisi_yok(self):
        from database.satis_faturasi_service import SatisFaturasiService

        irs = SatisIrsaliyesiService.kaydet(self._veri(), [self._satir(2, "Koli")])
        SatisIrsaliyesiService.sevk_et(irs.id)
        irs = SatisIrsaliyesiService.getir(irs.id)
        fatura = self._fatura_kaydet(irs, 1)
        self.assertEqual(SatisIrsaliyesiService.getir(irs.id).durum, "KISMİ FATURALANDI")
        SatisFaturasiService.onayla(fatura.id)
        self.assertEqual(self._hareket_toplam("FATURA ÇIKIŞ"), 0)
        self.assertEqual(self._hareket_toplam("İRSALİYE ÇIKIŞ"), Decimal("4800"))
        # kalan 1 Koli'den fazlası faturalanamaz
        with self.assertRaisesRegex(ValueError, "kalan"):
            self._fatura_kaydet(irs, 2)
        for islem, beklenen in (
            (lambda: SatisIrsaliyesiService.sil(irs.id), "silinemez"),
            (lambda: SatisIrsaliyesiService.iptal_et(irs.id, "x"), "iptal edilemez"),
            (lambda: SatisIrsaliyesiService.sevk_geri_al(irs.id), "geri alınamaz"),
            (
                lambda: SatisIrsaliyesiService.kaydet(self._veri(), [self._satir(1, "Koli")], irsaliye_id=irs.id),
                "Sevki Geri Al|değiştirilemez",
            ),
        ):
            with self.assertRaisesRegex(ValueError, beklenen) as ctx:
                islem()
            if beklenen != "Sevki Geri Al|değiştirilemez":
                self.assertIn(fatura.fatura_no, str(ctx.exception))
        bagli = SatisIrsaliyesiService.bagli_faturalar(irs.id)
        self.assertEqual([b["fatura_no"] for b in bagli], [fatura.fatura_no])
        liste = SatisIrsaliyesiService.listele(evrak_no=irs.irsaliye_no)
        self.assertEqual(liste[0]["faturalama_durumu"], "Kısmen faturalandı")
        self.assertEqual(liste[0]["fatura_nolari"], [fatura.fatura_no])
        # fatura iptal → irsaliye sevk durumuna döner, stok irsaliyede kalır
        SatisFaturasiService.iptal_et(fatura.id, "test iptal")
        geri = SatisIrsaliyesiService.getir(irs.id)
        self.assertEqual(geri.durum, "SEVK EDİLDİ")
        self.assertEqual(geri.satirlar[0].faturalanan_miktar, 0)
        self.assertEqual(self._lot_kalan(), Decimal("200"))
        # iptal faturası satıra hâlâ bağlı: silme engelli, iptal serbest
        with self.assertRaisesRegex(ValueError, "silinemez"):
            SatisIrsaliyesiService.sil(irs.id)
        SatisIrsaliyesiService.iptal_et(irs.id, "fatura iptal sonrası")
        self.assertEqual(self._lot_kalan(), Decimal("5000"))

    def test_sevksiz_faturalanan_irsaliye_ikinci_kez_stok_dusmez(self):
        from database.satis_faturasi_service import SatisFaturasiService

        irs = SatisIrsaliyesiService.kaydet(self._veri(), [self._satir(1, "Koli")])
        irs = SatisIrsaliyesiService.getir(irs.id)
        fatura = self._fatura_kaydet(irs, 1)
        SatisFaturasiService.onayla(fatura.id)
        self.assertEqual(self._hareket_toplam("FATURA ÇIKIŞ"), Decimal("2400"))
        with self.assertRaisesRegex(ValueError, fatura.fatura_no):
            SatisIrsaliyesiService.sevk_et(irs.id)
        self.assertEqual(self._hareket_toplam("İRSALİYE ÇIKIŞ"), 0)
        self.assertEqual(self._lot_kalan(), Decimal("2600"))
        self.assertEqual(SatisIrsaliyesiService.getir(irs.id).durum, "FATURALANDI")

    # ---- liste -------------------------------------------------------
    def test_liste_filtreleri(self):
        a = SatisIrsaliyesiService.kaydet(self._veri(irsaliye_no="IRS-A1"), [self._satir(1)])
        b = SatisIrsaliyesiService.kaydet(
            self._veri(irsaliye_no="IRS-B2", irsaliye_tarihi=date(2026, 4, 5)), [self._satir(2)]
        )
        SatisIrsaliyesiService.sevk_et(b.id)
        self.assertEqual(len(SatisIrsaliyesiService.listele()), 2)
        self.assertEqual(
            [r["irsaliye"].irsaliye_no for r in SatisIrsaliyesiService.listele(evrak_no="b2")],
            ["IRS-B2"],
        )
        self.assertEqual(
            [r["irsaliye"].id for r in SatisIrsaliyesiService.listele(baslangic=date(2026, 4, 1))],
            [b.id],
        )
        self.assertEqual(
            [r["irsaliye"].id for r in SatisIrsaliyesiService.listele(bitis=date(2026, 3, 31))],
            [a.id],
        )
        self.assertEqual(
            [r["irsaliye"].id for r in SatisIrsaliyesiService.listele(durum="SEVK EDİLDİ")],
            [b.id],
        )
        self.assertEqual(len(SatisIrsaliyesiService.listele(musteri="m001")), 2)
        self.assertEqual(SatisIrsaliyesiService.listele(musteri="yok-böyle"), [])
        satir = SatisIrsaliyesiService.listele(evrak_no="IRS-A1")[0]
        self.assertEqual(satir["musteri_kodu"], "M001")
        self.assertEqual(satir["depo"], "ANA DEPO")
        self.assertEqual(satir["faturalama_durumu"], "Faturalanmadı")


class SatisIrsaliyesiEkranTest(SatisIrsaliyesiAkisTest):
    """Tk ekranı (gizli kök): boş açılış, kayıt/yeniden açma, kilit, değişiklik izi, çıktı."""

    def setUp(self):
        super().setUp()
        import tkinter as tk
        from unittest.mock import patch

        self.root = tk.Tk()
        self.root.withdraw()
        self._yamalar = [
            patch(f"tkinter.messagebox.{ad}", return_value=None)
            for ad in ("showinfo", "showwarning", "showerror")
        ] + [
            patch("tkinter.messagebox.askyesno", return_value=True),
            patch("tkinter.messagebox.askyesnocancel", return_value=False),
        ]
        self.mesajlar = [p.start() for p in self._yamalar]

    def tearDown(self):
        for p in self._yamalar:
            p.stop()
        try:
            self.root.destroy()
        except Exception:
            pass
        super().tearDown()

    def _dialog(self, **ek):
        from satis_irsaliyesi_ui import SatisIrsaliyesiDialog

        d = SatisIrsaliyesiDialog(self.root, **ek)
        d.withdraw()
        return d

    def _cari(self):
        from database.cari_service import CariService

        return CariService.getir(self.cari_id)

    def _urun_ekle(self, d, miktar="2", birim="Koli"):
        d.urun_secildi(("MB001", "Birim Ürün", "Adet", "", "1"))
        d.satir_girdileri["miktar"].delete(0, "end")
        d.satir_girdileri["miktar"].insert(0, miktar)
        d.satir_girdileri["birim"].set(birim)
        d.satir_ekle()

    def test_menu_yeni_irsaliye_her_seferinde_bos(self):
        d = self._dialog()
        d._musteri_ata(self._cari())
        self._urun_ekle(d)
        self.assertTrue(d.kaydet(sessiz=True))
        d.destroy()
        yeni = self._dialog()
        self.assertIsNone(yeni.irsaliye)
        self.assertIsNone(yeni.cari)
        self.assertEqual(yeni.satirlar, [])
        self.assertEqual(yeni._musteri_var.get(), "")
        self.assertEqual(yeni.girdiler["irsaliye_tarihi"].get(), date.today().strftime("%d.%m.%Y"))
        self.assertFalse(yeni.degisiklik_var())
        yeni.destroy()

    def test_birim_secenekleri_stok_kartindan(self):
        d = self._dialog()
        d.urun_secildi(("MB001", "Birim Ürün", "Adet", "", "1"))
        self.assertEqual(list(d.satir_girdileri["birim"].cget("values")), ["Adet", "Paket", "Koli"])
        d.destroy()

    def test_eksik_alanda_kaydetmez_ve_kayitli_gibi_davranmaz(self):
        d = self._dialog()
        self._urun_ekle(d)
        self.assertFalse(d.kaydet(sessiz=True))
        self.assertIsNone(d.irsaliye)
        self.assertIn("Müşteri", str(self.mesajlar[1].call_args))
        d._musteri_ata(self._cari())
        d.girdiler["irsaliye_tarihi"].delete(0, "end")
        d.girdiler["irsaliye_tarihi"].insert(0, "31.31.2026")
        self.assertFalse(d.kaydet(sessiz=True))
        self.assertIn("geçersiz", str(self.mesajlar[1].call_args))
        with get_session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SatisIrsaliyesi)), 0)
        d.destroy()

    def test_kaydet_yeniden_ac_ayni_kilit_ve_degisiklik_izi(self):
        d = self._dialog()
        d._musteri_ata(self._cari())
        d.girdiler["sevk_adresi"].delete(0, "end")
        d.girdiler["sevk_adresi"].insert(0, "Teslimat Sok. 5")
        d.girdiler["aciklama"].insert(0, "Ekran testi")
        self._urun_ekle(d, "1", "Koli")
        self._urun_ekle(d, "3", "Paket")
        self.assertTrue(d.degisiklik_var())
        self.assertTrue(d.kaydet(sessiz=True))
        self.assertFalse(d.degisiklik_var())
        self.assertTrue(d.kaydet(sessiz=True))  # tekrar kaydet: mükerrer yok
        iid = d.irsaliye.id
        d.destroy()
        with get_session() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(SatisIrsaliyesi)), 1)
            self.assertEqual(session.scalar(select(func.count()).select_from(SatisIrsaliyesiSatiri)), 2)
        acik = self._dialog(irsaliye=SatisIrsaliyesiService.getir(iid))
        self.assertEqual(acik.girdiler["sevk_adresi"].get(), "Teslimat Sok. 5")
        self.assertEqual(acik.girdiler["aciklama"].get(), "Ekran testi")
        self.assertEqual(
            [(s["birim"], s["miktar"]) for s in acik.satirlar],
            [("Koli", Decimal("1")), ("Paket", Decimal("3"))],
        )
        self.assertTrue(all(s["irsaliye_satiri_id"] for s in acik.satirlar))
        self.assertFalse(acik.degisiklik_var())
        acik.girdiler["aciklama"].insert("end", " değişti")
        self.assertTrue(acik.degisiklik_var())
        acik.sevk_et()  # değişiklik önce kaydedilir, sonra sevk
        self.assertEqual(self._hareket_toplam("İRSALİYE ÇIKIŞ"), Decimal("2700"))
        self.assertEqual(SatisIrsaliyesiService.getir(iid).aciklama, "Ekran testi değişti")
        self.assertEqual(str(acik.btn["kaydet"].cget("state")), "disabled")
        self.assertEqual(str(acik.btn["sevk"].cget("state")), "disabled")
        self.assertEqual(str(acik.btn["sevk_geri"].cget("state")), "normal")
        self.assertEqual(str(acik.satir_girdileri["miktar"].cget("state")), "disabled")
        self.assertFalse(acik.degisiklik_var())
        acik.sevk_geri_al()
        self.assertEqual(self._hareket_toplam("İRSALİYE ÇIKIŞ"), 0)
        self.assertEqual(str(acik.btn["kaydet"].cget("state")), "normal")
        acik.destroy()

    def test_siparis_satiri_birimi_kilitli_ve_liste_siparis_no(self):
        siparis = self._siparis(10, "Paket")
        ssid = siparis.satirlar[0].id
        irs = SatisIrsaliyesiService.kaydet(
            self._veri(siparis_id=siparis.id), [self._satir(4, "Paket", siparis_satiri_id=ssid)]
        )
        d = self._dialog(irsaliye=irs)
        self.assertEqual(d.satirlar[0]["siparis_no"], siparis.siparis_no)
        self.assertEqual(d._siparis_var.get(), siparis.siparis_no)
        d.satir_tablosu.selection_set("0")
        d.satir_duzenle()
        self.assertEqual(list(d.satir_girdileri["birim"].cget("values")), ["Paket"])
        d.satir_girdileri["miktar"].delete(0, "end")
        d.satir_girdileri["miktar"].insert(0, "6")
        d.satir_ekle()
        self.assertTrue(d.kaydet(sessiz=True))
        self.assertEqual(self._sevk_miktari(ssid), Decimal("6"))
        d.destroy()

    def test_cikti_html_toplam_miktar_ve_sayfa_kurallari(self):
        from database.irsaliye_customer_view import (
            build_customer_dispatch_from_dialog,
            render_customer_dispatch_html,
        )

        d = self._dialog()
        d._musteri_ata(self._cari())
        d.girdiler["sevk_adresi"].delete(0, "end")
        d.girdiler["sevk_adresi"].insert(0, "Depo Kapısı 7")
        for _ in range(40):
            self._urun_ekle(d, "1", "Paket")
        self._urun_ekle(d, "2", "Koli")
        html = render_customer_dispatch_html(build_customer_dispatch_from_dialog(d))
        self.assertIn("Test Müşteri", html)
        self.assertIn("Depo Kapısı 7", html)
        self.assertIn("Toplam Miktar: 40 Paket · 2 Koli", html)
        self.assertIn("<td class='r'>2</td><td class='c'>Koli</td>", html)
        from database.irsaliye_customer_view import miktar_metni

        self.assertEqual(miktar_metni(Decimal("10")), "10")
        self.assertEqual(miktar_metni(Decimal("2.5000")), "2,5")
        self.assertIn("display:table-header-group", html)
        self.assertIn("page-break-inside:avoid", html)
        self.assertIn("#102A43", html)
        self.assertIn("#F4C542", html)
        d.destroy()

    def test_pdf_gercek_dosya_uretir(self):
        import re
        import tempfile

        from invoice_print.pdf_service import _chrome_edge_paths

        if not _chrome_edge_paths():
            self.skipTest("Edge/Chrome yok")
        d = self._dialog()
        d._musteri_ata(self._cari())
        for _ in range(60):
            self._urun_ekle(d, "1", "Adet")
        hedef = Path(tempfile.mkdtemp()) / "irsaliye.pdf"
        with patch("satis_irsaliyesi_ui.filedialog.asksaveasfilename", return_value=str(hedef)):
            d.pdf_kaydet()
        self.assertTrue(hedef.is_file())
        icerik = hedef.read_bytes()
        self.assertTrue(icerik.startswith(b"%PDF"))
        self.assertGreaterEqual(len(re.findall(rb"/Type\s*/Page[^s]", icerik)), 2)
        d.destroy()


if __name__ == "__main__":
    unittest.main()
