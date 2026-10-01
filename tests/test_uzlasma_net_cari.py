"""Uzlaşmayla değiştirilen satış faturası Net'i: kayıt, yeniden açma, tahsilat makbuzu, cari borç,
açık kalem, ekstre, tekrar kaydetme ve geçmiş kayıt düzeltmesi.

Örnek: 1 adet × 12.000 TL + %20 KDV = Brüt 14.400 TL; uzlaşılan Net 13.000 TL (1.400 TL indirim).
Yalnız geçici test veritabanı kullanır (TahsilatMakbuzuTest kurulumu).
"""

from __future__ import annotations

import sys
import tempfile
import tkinter as tk
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from database.database import get_session
from database.finans_service import FinansService
from database.models.cari import CariIslem, SatisHareketi
from database.models.finans import FinansHareketi, KasaMakbuzu, SatisFaturaMakbuzBagi
from database.models.stok import Depo, StokKarti
from database.satis_faturasi_service import SatisFaturasiService
from tests import test_tahsilat_makbuzu as _servis_testi

BRUT = Decimal("14400.00")
NET = Decimal("13000.00")
ACILIS = Decimal("1000")  # TahsilatMakbuzuTest müşteri açılış borcu


def _kurulum(test):
    _servis_testi.TahsilatMakbuzuTest.setUp(test)
    with get_session() as s:
        s.add(Depo(ad="ANA DEPO", aktif=True))
        s.add(StokKarti(stok_kodu="U001", stok_adi="Masa", birim="Adet", aktif=True, is_deleted=False))
    test._yamalar = [
        patch("database.muhasebe_entegrasyon.muhasebe_hook", lambda *_a, **_k: None),
        patch("database.satis_personeli.secimi_dogrula", return_value=(1, "Test Admin")),
    ]
    for y in test._yamalar:
        y.start()
    from database.alis_faturasi_service import AlisFaturasiService

    AlisFaturasiService.kaydet(
        {"fatura_tarihi": date(2026, 1, 5), "vade_tarihi": date(2026, 1, 5), "cari_id": test.tedarikci_id,
         "depo": "ANA DEPO", "odeme_tutari": Decimal("0")},
        [{"urun_kodu": "U001", "urun_adi": "Masa", "miktar": Decimal("10"), "birim": "Adet",
          "birim_fiyat": Decimal("5000"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20"),
          "lot_no": "LOT-1"}],
    )


def _sokum(test):
    for y in reversed(test._yamalar):
        y.stop()
    _servis_testi.TahsilatMakbuzuTest.tearDown(test)


def _veriler(test, fatura=None, net=NET):
    """Satış faturası ekranının uzlaşmada gönderdiği alanlar (satır fiyatları değişmez)."""
    fark = BRUT - net
    v = {
        "fatura_tarihi": date(2026, 6, 1), "vade_tarihi": date(2026, 6, 1), "cari_id": test.musteri_id,
        "depo": "ANA DEPO", "sales_person_id": 1,
        "tl_brut_toplam": BRUT, "tl_genel_toplam": net,
        "genel_islem_turu": ("INDIRIM" if fark > 0 else "MASRAF") if fark else None,
        "genel_islem_tutari": abs(fark),
        "genel_islem_orani": (abs(fark) / BRUT * 100).quantize(Decimal("0.0001")),
        "invoice_rounding_adjustment": Decimal("0"),
    }
    if fatura is not None:
        v["fatura_no"] = fatura.fatura_no
        v["row_version"] = fatura.row_version
    return v


SATIR = [{"urun_kodu": "U001", "urun_adi": "Masa", "miktar": Decimal("1"), "birim": "Adet",
          "birim_fiyat": Decimal("12000"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20")}]


def _uzlasmali_fatura(test, *, onayla=True):
    f = SatisFaturasiService.kaydet(_veriler(test), SATIR)
    if onayla:
        SatisFaturasiService.onayla(f.id)
    return int(f.id)


def _hareketler(fatura_id):
    with get_session() as s:
        no = SatisFaturasiService.getir(fatura_id).fatura_no
        return [(Decimal(str(h.satis_tutari)), Decimal(str(h.kalan_acik_tutar)))
                for h in s.scalars(select(SatisHareketi).where(SatisHareketi.belge_no == no)).all()]


def _makbuz(test, fatura_id, tutar):
    return FinansService.kasa_tahsilat_makbuzu_kaydet({
        "tarih": date.today(), "cari_id": test.musteri_id, "makbuz_no_otomatik": True,
        "fatura_id": fatura_id,
        "satirlar": [{"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": test.kasa_id, "tutar": tutar}],
    })


def _sayilar():
    with get_session() as s:
        return tuple(
            s.scalar(select(func.count()).select_from(m))
            for m in (CariIslem, FinansHareketi, KasaMakbuzu, SatisFaturaMakbuzBagi, SatisHareketi)
        )


class UzlasmaNetCariTest(unittest.TestCase):
    def setUp(self):
        _kurulum(self)

    def tearDown(self):
        _sokum(self)

    def test_kayit_ve_yeniden_acmada_net_korunur(self):
        fid = _uzlasmali_fatura(self, onayla=False)
        f = SatisFaturasiService.getir(fid)
        self.assertEqual((Decimal(str(f.tl_brut_toplam)), Decimal(str(f.tl_genel_toplam))), (BRUT, NET))
        self.assertEqual(f.genel_islem_turu, "INDIRIM")
        self.assertEqual(SatisFaturasiService.net_toplam(f), NET)
        oz = FinansService.fatura_tahsilat_ozeti(fid)
        self.assertEqual((oz["genel_toplam"], oz["kalan"], oz["brut_toplam"]), (NET, NET, BRUT))

    def test_onay_cari_borcu_net_yazar_tum_ekranlar_ayni_net(self):
        from database.acik_kalem_service import AcikKalemService
        from database.cari_bakiye_service import fatura_eski_yeni_bakiye, net_bakiye
        from database.rapor_service import RaporService

        fid = _uzlasmali_fatura(self)
        self.assertEqual(_hareketler(fid), [(NET, NET)])
        oz = FinansService.fatura_tahsilat_ozeti(fid)
        self.assertEqual((oz["genel_toplam"], oz["tahsil_edilen"], oz["kalan"]), (NET, Decimal("0"), NET))
        self.assertEqual(FinansService.cari_bakiye_ozeti(self.musteri_id)["bakiye"], ACILIS + NET)
        self.assertEqual(net_bakiye(self.musteri_id)["bakiye"], ACILIS + NET)
        no = SatisFaturasiService.getir(fid).fatura_no
        eski_yeni = fatura_eski_yeni_bakiye(self.musteri_id, exclude_belge_no=no, belge_etkisi=NET)
        self.assertEqual((eski_yeni["eski_bakiye"], eski_yeni["yeni_bakiye"]), (ACILIS, ACILIS + NET))
        with get_session() as s:
            kalem = next(k for k in AcikKalemService.secim_listesi(s, self.musteri_id) if k["evrak_no"] == no)
        self.assertEqual((kalem["ilk_tutar"], kalem["kalan"]), (NET, NET))
        ekstre = RaporService.stok_detayli_ekstre(self.musteri_id)
        satir = next(b for b in ekstre["belgeler"] if b["belge_no"] == no)
        self.assertEqual(satir["borc"], NET)

    def test_kismi_ve_tam_tahsilat_net_uzerinden_kapanir(self):
        fid = _uzlasmali_fatura(self)
        _makbuz(self, fid, "3000")
        self.assertEqual(_hareketler(fid), [(NET, Decimal("10000.00"))])
        oz = FinansService.fatura_tahsilat_ozeti(fid)
        self.assertEqual((oz["tahsil_edilen"], oz["kalan"]), (Decimal("3000.00"), Decimal("10000.00")))
        self.assertEqual(FinansService.cari_bakiye_ozeti(self.musteri_id)["bakiye"], ACILIS + NET - 3000)
        _makbuz(self, fid, "10000")
        self.assertEqual(_hareketler(fid), [(NET, Decimal("0.00"))])
        oz = FinansService.fatura_tahsilat_ozeti(fid)
        self.assertEqual((oz["tahsil_edilen"], oz["kalan"]), (NET, Decimal("0.00")))
        self.assertEqual(FinansService.cari_bakiye_ozeti(self.musteri_id)["bakiye"], ACILIS)

    def test_onaysiz_faturada_makbuz_net_kalani_onerir(self):
        fid = _uzlasmali_fatura(self, onayla=False)
        _makbuz(self, fid, "3000")
        oz = FinansService.fatura_tahsilat_ozeti(fid)
        self.assertEqual((oz["genel_toplam"], oz["kalan"]), (NET, Decimal("10000.00")))

    def test_tekrar_kaydetme_ve_onay_mukerrer_hareket_olusturmaz(self):
        fid = _uzlasmali_fatura(self)
        _makbuz(self, fid, "3000")
        SatisFaturasiService.onay_kaldir(fid)
        f = SatisFaturasiService.getir(fid)
        SatisFaturasiService.kaydet(_veriler(self, f), SATIR, fatura_id=fid)
        SatisFaturasiService.onayla(fid)
        self.assertEqual(_hareketler(fid), [(NET, Decimal("10000.00"))])
        self.assertEqual(FinansService.fatura_tahsilat_ozeti(fid)["kalan"], Decimal("10000.00"))
        self.assertEqual(FinansService.cari_bakiye_ozeti(self.musteri_id)["bakiye"], ACILIS + NET - 3000)

    def test_uzlasma_net_degisince_borc_guncellenir(self):
        fid = _uzlasmali_fatura(self)
        SatisFaturasiService.onay_kaldir(fid)
        f = SatisFaturasiService.getir(fid)
        SatisFaturasiService.kaydet(_veriler(self, f, net=Decimal("12500.00")), SATIR, fatura_id=fid)
        SatisFaturasiService.onayla(fid)
        self.assertEqual(_hareketler(fid), [(Decimal("12500.00"), Decimal("12500.00"))])

    def test_uzlasmasiz_fatura_satir_toplamini_kullanir(self):
        f = SatisFaturasiService.kaydet(_veriler(self, net=BRUT), SATIR)
        SatisFaturasiService.onayla(f.id)
        self.assertEqual(_hareketler(int(f.id)), [(BRUT, BRUT)])

    def test_makbuz_ozeti_hareket_olusturmaz(self):
        fid = _uzlasmali_fatura(self)
        once = _sayilar()
        for _ in range(3):
            FinansService.fatura_tahsilat_ozeti(fid)
        self.assertEqual(_sayilar(), once)


class UzlasmaGmFisTest(unittest.TestCase):
    def setUp(self):
        _kurulum(self)

    def tearDown(self):
        _sokum(self)

    def test_satis_fisi_dengeli_musteri_borcu_net(self):
        from database.models.genel_muhasebe import (
            HesapPlani,
            MuhasebeFisi,
            MuhasebeFisiSatiri,
            MuhasebeHesapEsleme,
        )
        from database.models.firma import Firma
        from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

        fid = _uzlasmali_fatura(self)
        with get_session() as s:
            firma_id = s.scalar(select(Firma.id).limit(1))
            for anahtar, kod, tur in (("musteriler", "120.01.0001", "Aktif"),
                                      ("yurtici_satislar", "600.01.0001", "Gelir"),
                                      ("hesaplanan_kdv", "391.01.0001", "Pasif")):
                h = HesapPlani(firma_id=firma_id, hesap_kodu=kod, hesap_adi=anahtar, hesap_seviyesi=3,
                               hesap_turu=tur, borc_toplam=0, alacak_toplam=0, aktif=True)
                s.add(h)
                s.flush()
                s.add(MuhasebeHesapEsleme(firma_id=firma_id, anahtar=anahtar, aciklama=anahtar,
                                          hesap_id=h.id, aktif=True))
        fis_id = MuhasebeEntegrasyonService.satis_faturasi_fisi(fid)
        self.assertIsNotNone(fis_id)
        with get_session() as s:
            satirlar = s.scalars(select(MuhasebeFisiSatiri).where(MuhasebeFisiSatiri.fis_id == fis_id)).all()
            borc = sum((Decimal(str(x.borc)) for x in satirlar), Decimal("0"))
            alacak = sum((Decimal(str(x.alacak)) for x in satirlar), Decimal("0"))
            self.assertIsNotNone(s.get(MuhasebeFisi, fis_id))
        self.assertEqual((borc, alacak), (NET, NET))


class UzlasmaServisSistemTest(unittest.TestCase):
    def setUp(self):
        _kurulum(self)

    def tearDown(self):
        _sokum(self)

    def test_tarayici_uyusmaz_saymaz_onarim_neti_korur(self):
        from database.servis_sistem.repair_service import RepairService
        from database.servis_sistem.scanners.fatura import scan_fatura
        from database.servis_sistem.system_health_service import CheckReport

        fid = _uzlasmali_fatura(self)
        rapor = CheckReport(baslik="test", baslangic="")
        scan_fatura(rapor, yon="satis")
        self.assertNotIn("FATURA_TOPLAM_UYUSMAZ", [m.hata_kodu for m in rapor.maddeler])
        RepairService._do_recalc_fatura_header({"record_id": str(fid), "module_name": "satis"})
        f = SatisFaturasiService.getir(fid)
        self.assertEqual((Decimal(str(f.tl_brut_toplam)), Decimal(str(f.tl_genel_toplam))), (BRUT, NET))


class UzlasmaGecmisDuzeltmeTest(unittest.TestCase):
    def setUp(self):
        _kurulum(self)

    def tearDown(self):
        _sokum(self)

    def _eski_surum_gibi_brut_yaz(self, fid, tahsil):
        """Hatalı eski onayın bıraktığı durum: borç Brüt, kalan Brüt − tahsil edilen."""
        no = SatisFaturasiService.getir(fid).fatura_no
        with get_session() as s:
            h = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == no))
            h.satis_tutari = BRUT
            h.kalan_acik_tutar = BRUT - Decimal(tahsil)

    def test_kuru_calisma_uygula_tekrar_calistirma(self):
        from database import uzlasma_net_duzeltme as d

        fid = _uzlasmali_fatura(self)
        _makbuz(self, fid, "3000")
        self._eski_surum_gibi_brut_yaz(fid, "3000")
        makbuz_once = _sayilar()[:4]
        with tempfile.TemporaryDirectory() as yedek:
            ozet = d.tam_duzeltme(self.db_path, yedek)
            self.assertTrue(any(Path(yedek).glob("*_gecis_oncesi_*.db")))
        self.assertEqual(ozet["uygulanan_sayisi"], 1)
        k = ozet["uygulanan"][0]
        self.assertEqual((k["eski_borc"], k["eski_kalan"], k["kapanan"]), (BRUT, Decimal("11400.00"), Decimal("3000.00")))
        self.assertEqual(ozet["kalan_duzeltilecek"], 0)
        self.assertEqual(_hareketler(fid), [(NET, Decimal("10000.00"))])
        self.assertEqual(FinansService.fatura_tahsilat_ozeti(fid)["kalan"], Decimal("10000.00"))
        self.assertEqual(_sayilar()[:4], makbuz_once)
        with get_session() as s:
            self.assertEqual(d.kuru_calisma(s)["kalemler"], [])

    def test_fazla_tahsilat_manuel_incelemeye_kalir(self):
        from database import uzlasma_net_duzeltme as d

        fid = _uzlasmali_fatura(self)
        self._eski_surum_gibi_brut_yaz(fid, "14000")
        with get_session() as s:
            rapor = d.kuru_calisma(s)
            self.assertEqual((rapor["duzeltilecek"], rapor["manuel"]), (0, 1))
            self.assertEqual(d.uygula(s, rapor), [])
        self.assertEqual(_hareketler(fid), [(BRUT, Decimal("400.00"))])


class UzlasmaMakbuzEkranTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as hata:
            raise unittest.SkipTest(f"Tk yok: {hata}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        _kurulum(self)
        self._ui_yamalar = [patch("cari_kart_ui.cari_uyari_goster", return_value=None)]
        for y in self._ui_yamalar:
            y.start()

    def tearDown(self):
        for y in self._ui_yamalar:
            y.stop()
        for w in list(self.root.winfo_children()):
            w.destroy()
        _sokum(self)

    def _dialog(self, fid):
        from kasa_makbuz_ui import KasaMakbuzDialog

        d = KasaMakbuzDialog(self.root, "TAHSILAT", fatura_id=fid)
        d.update_idletasks()
        return d

    def test_makbuz_net_ve_kalan_onerir_acilis_hareket_olusturmaz(self):
        fid = _uzlasmali_fatura(self)
        once = _sayilar()
        d = self._dialog(fid)
        self.assertEqual(d.tutar_var.get(), "13.000,00")
        bilgi = d.fatura_bilgi_metni()
        self.assertIn("net toplamı 13.000,00", bilgi)
        self.assertIn("Brüt 14.400,00", bilgi)
        d.kapat()
        self.assertEqual(_sayilar(), once)
        _makbuz(self, fid, "3000")
        d = self._dialog(fid)
        self.assertEqual(d.tutar_var.get(), "10.000,00")
        d.kapat()


if __name__ == "__main__":
    unittest.main()
