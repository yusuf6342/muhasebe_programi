"""Hızlı Satış sonuç raporu açıkları (07.10.2026): normal fatura ekranında Genel/Yeni Toplam,
cari/tahsilat/KDV/baskı tutarlılığı, fiyat KDV anlamı, irsaliye iadesi ve dönem filtresi.

Çalıştırma: .venv\\Scripts\\python.exe -m pytest tests/test_hizli_satis_acik_kapatma.py -q
"""

from __future__ import annotations

import sys
import time
import tkinter as tk
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hizli_satis_sepet import HizliSatisSepet  # noqa: E402
from tests.test_hizli_satis_talimat_satir import _DbTabani  # noqa: E402


def _toplam_satirlar(satirlar, dialog) -> Decimal:
    return sum((dialog._uzlasilan_satir_genel(v) for v in satirlar), Decimal("0"))


class _FaturaEkraniTabani(_DbTabani):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"Tk yok: {exc}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except tk.TclError:
            pass

    def setUp(self):
        super().setUp()
        self.mesajlar: list[tuple] = []
        self._ui_yamalari = [
            patch(f"app.messagebox.{ad}", lambda *a, _ad=ad, **k: self.mesajlar.append((_ad, a)))
            for ad in ("showerror", "showwarning", "showinfo")
        ] + [
            patch("satis_personeli_ui.aktif_satis_personelleri", return_value=[]),
            patch("satis_personeli_ui.satis_personeli_degistirme_yetkisi", return_value=True),
            patch("fatura_acilis_cache.satis_personelleri", return_value=[]),
        ]
        for p in self._ui_yamalari:
            p.start()
        self._acik: list = []

    def tearDown(self):
        for d in self._acik:
            try:
                d.destroy()
            except tk.TclError:
                pass
        for p in reversed(self._ui_yamalari):
            p.stop()
        super().tearDown()

    def _ac(self, fatura_id):
        from app import SatisFaturasiDialog
        from database.satis_faturasi_service import SatisFaturasiService

        d = SatisFaturasiDialog(self.root, fatura=SatisFaturasiService.getir(fatura_id))
        self._acik.append(d)
        bitis = time.monotonic() + 3
        while getattr(d, "_fatura_yukleniyor", False) and time.monotonic() < bitis:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(getattr(d, "_fatura_yukleniyor", False), "fatura yüklemesi bitmedi")
        return d

    def _sepet_1000(self, hedef="900") -> HizliSatisSepet:
        """KDV'li + KDV'siz iki satır: Genel Toplam 1000 (600 + 400)."""
        sepet = HizliSatisSepet()
        sepet.ekle(stok_id=self.stok_id, stok_kodu="U001", stok_adi="Test Ürün", miktar=1,
                   birim_fiyat="500", kdv_orani=20)
        sepet.ekle(stok_id=self.stok_id, stok_kodu="U001", stok_adi="Test Ürün", birim="Koli",
                   miktar=4, birim_fiyat="100", kdv_orani=0, birlestir=False)
        self.assertEqual(sepet.referans_toplam(), Decimal("1000.00"))
        if hedef is not None:
            sepet.hedef_toplam_uygula(hedef)
        return sepet

    def _hareketler(self, fatura_no):
        from database.database import get_session
        from database.models.cari import SatisHareketi
        from sqlalchemy import select

        with get_session() as s:
            return list(s.scalars(select(SatisHareketi).where(SatisHareketi.belge_no == fatura_no)).all())

    def _stok_hareket_sayisi(self, belge_no) -> int:
        from database.database import get_session
        from database.models.stok import StokHareketi
        from sqlalchemy import func, select

        with get_session() as s:
            return int(s.scalar(select(func.count(StokHareketi.id)).where(StokHareketi.belge_no == belge_no)))


class NormalFaturaRoundtripTest(_FaturaEkraniTabani):
    def _kaydet_onayla(self, d, fatura_id):
        from database.satis_faturasi_service import SatisFaturasiService

        veriler, satirlar = d._fatura_kayit_verilerini_topla()
        SatisFaturasiService.kaydet(veriler, satirlar, fatura_id, tahsilat_verileri=d.tahsilatlar)
        SatisFaturasiService.onayla(fatura_id)

    def _uzlasilan(self, d, tutar):
        d._uzlasilan_tutar_yaz(None if tutar is None else Decimal(tutar))
        d._uzlasilan_tutar_degisti()

    def test_hizli_satis_kaydet_normal_ekranda_duzenle_kaydet_yeniden_ac(self):
        from database.satis_faturasi_service import SatisFaturasiService
        from invoice_print.builder import build_invoice_print_model

        sonuc = self._sat(self._sepet_1000("900"))
        fid, fno = sonuc["fatura_id"], sonuc["fatura_no"]
        f = SatisFaturasiService.getir(fid)
        self.assertEqual(Decimal(str(f.tl_brut_toplam)), Decimal("1000.00"))
        self.assertEqual(Decimal(str(f.tl_genel_toplam)), Decimal("900.00"))
        self.assertEqual(f.genel_islem_turu, "INDIRIM")
        self.assertEqual(Decimal(str(f.tl_matrah)) + Decimal(str(f.tl_kdv)), Decimal("900.00"))
        self.assertEqual(build_invoice_print_model(fid).genel_toplam, Decimal("900.00"))
        stok_hareket_once = self._stok_hareket_sayisi(fno)
        self.assertEqual(len(self._hareketler(fno)), 1)

        # Normal ekranda aç: Brüt (Genel Toplam) 1000, Net (Yeni Toplam) 900; tahsilata Net gider
        d = self._ac(fid)
        self.assertTrue(d._referans_fiyat_aktif())
        self.assertEqual(d._referans_brut_toplam(), Decimal("1000.00"))
        self.assertEqual(d._uzlasilan_tutar, Decimal("900.00"))
        self.assertEqual(d._fatura_genel_toplam(), Decimal("900.00"))
        d.destroy()

        SatisFaturasiService.onay_kaldir(fid)
        d = self._ac(fid)
        referanslar = [Decimal(str(v["referans_birim_fiyat"])) for v in d.satirlar]
        self.assertEqual(referanslar, [Decimal("500"), Decimal("100")])
        # 900 → 800 → 1000: Genel Toplam sabit, fiyatlar hep referanstan
        self._uzlasilan(d, "800")
        self.assertEqual(_toplam_satirlar(d.satirlar, d), Decimal("800.00"))
        self.assertEqual(d._referans_brut_toplam(), Decimal("1000.00"))
        fiyat_800 = [Decimal(str(v["birim_satis_fiyati"])) for v in d.satirlar]
        self._uzlasilan(d, "900")
        self._uzlasilan(d, "800")
        self.assertEqual([Decimal(str(v["birim_satis_fiyati"])) for v in d.satirlar], fiyat_800,
                         "aynı hedef tekrarında indirim üst üste binmemeli")
        self._uzlasilan(d, "1000")
        self.assertEqual([Decimal(str(v["birim_satis_fiyati"])) for v in d.satirlar], referanslar)
        self.assertEqual(d._referans_brut_toplam(), Decimal("1000.00"))

        # 850 ile kaydet + onayla: tek cari hareket, tutar = Yeni Toplam
        self._uzlasilan(d, "850")
        self._kaydet_onayla(d, fid)
        hareketler = self._hareketler(fno)
        self.assertEqual(len(hareketler), 1, "yeniden kayıt ikinci borç yazmamalı")
        self.assertEqual(Decimal(str(hareketler[0].satis_tutari)), Decimal("850.00"))
        self.assertEqual(self._stok_hareket_sayisi(fno), stok_hareket_once, "stok hareketi çoğalmamalı")
        f = SatisFaturasiService.getir(fid)
        self.assertEqual(Decimal(str(f.tl_brut_toplam)), Decimal("1000.00"))
        self.assertEqual(Decimal(str(f.tl_genel_toplam)), Decimal("850.00"))
        self.assertEqual(Decimal(str(f.tl_matrah)) + Decimal(str(f.tl_kdv)), Decimal("850.00"))
        self.assertEqual(
            sorted(Decimal(str(s.referans_birim_fiyat)) for s in f.satirlar), [Decimal("100"), Decimal("500")]
        )
        self.assertEqual(build_invoice_print_model(fid).genel_toplam, Decimal("850.00"))
        d.destroy()

        # Yeniden aç: Genel 1000 / Yeni 850 korunur
        d = self._ac(fid)
        self.assertEqual(d._referans_brut_toplam(), Decimal("1000.00"))
        self.assertEqual(d._fatura_genel_toplam(), Decimal("850.00"))

    def test_miktar_degisimi_referans_fiyata_doner_ve_referans_guncellenir(self):
        from database.satis_faturasi_service import SatisFaturasiService
        from fatura_satir_hucre_edit import acik_editor, miktar_hucre_duzenle

        sonuc = self._sat(self._sepet_1000("900"))
        SatisFaturasiService.onay_kaldir(sonuc["fatura_id"])
        d = self._ac(sonuc["fatura_id"])
        miktar_hucre_duzenle(d, idx=1)
        editor = acik_editor(d)
        self.assertIsNotNone(editor)
        editor.delete(0, "end")
        editor.insert(0, "5")
        editor._uygula_fn()
        # Dağıtım kalktı: satırlar orijinal fiyatlarla, Genel Toplam yeni miktardan
        self.assertFalse(d._referans_fiyat_aktif())
        self.assertIsNone(d._uzlasilan_tutar)
        self.assertEqual([Decimal(str(v["birim_satis_fiyati"])) for v in d.satirlar],
                         [Decimal("500"), Decimal("100")])
        self.assertEqual(_toplam_satirlar(d.satirlar, d), Decimal("1100.00"))
        # Yeni Toplam yine orijinal fiyatlardan dağıtılır
        d._uzlasilan_tutar = Decimal("1000")
        d._uzlasilan_fiyatlara_dagit()
        self.assertEqual(d._referans_brut_toplam(), Decimal("1100.00"))
        self.assertEqual(_toplam_satirlar(d.satirlar, d), Decimal("1000.00"))

    def test_kaydedilmeyen_degisiklik_ve_iptal_cari_hareket_olusturmaz(self):
        from database.satis_faturasi_service import SatisFaturasiService

        sonuc = self._sat(self._sepet_1000("900"))
        SatisFaturasiService.onay_kaldir(sonuc["fatura_id"])
        self.assertEqual(self._hareketler(sonuc["fatura_no"]), [])
        d = self._ac(sonuc["fatura_id"])
        self._uzlasilan(d, "700")
        d.destroy()
        self.assertEqual(self._hareketler(sonuc["fatura_no"]), [])
        f = SatisFaturasiService.getir(sonuc["fatura_id"])
        self.assertEqual(Decimal(str(f.tl_genel_toplam)), Decimal("900.00"))
        # Hiç kaydedilmeyen Hızlı Satış sepeti
        from database.database import get_session
        from database.models.cari import SatisHareketi
        from sqlalchemy import func, select

        with get_session() as s:
            once = s.scalar(select(func.count(SatisHareketi.id)))
        self._sepet_1000("750")
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(SatisHareketi.id))), once)

    def test_tahsilatsiz_ve_tam_tahsilat(self):
        from database.database import get_session
        from database.models.finans import FinansHareketi
        from sqlalchemy import func, select

        sonuc = self._sat(self._sepet_1000("900"))
        h = self._hareketler(sonuc["fatura_no"])[0]
        self.assertEqual((Decimal(str(h.satis_tutari)), Decimal(str(h.kalan_acik_tutar)).quantize(Decimal("0.01"))),
                         (Decimal("900.00"), Decimal("900.00")))
        th = [{"odeme_sekli": "NAKİT / KASA", "tutar": "900", "hesap": "ANA KASA"}]
        sonuc = self._sat(self._sepet_1000("900"), tahsilat=th)
        h = self._hareketler(sonuc["fatura_no"])[0]
        self.assertEqual(Decimal(str(h.satis_tutari)), Decimal("900.00"))
        self.assertEqual(Decimal(str(h.kalan_acik_tutar)).quantize(Decimal("0.01")), Decimal("0.00"))
        with get_session() as s:
            tahsil = s.scalar(select(func.coalesce(func.sum(FinansHareketi.tutar), 0)).where(
                FinansHareketi.belge_no == sonuc["fatura_no"]))
        self.assertEqual(Decimal(str(tahsil)), Decimal("900"))

    def test_eski_fatura_referanssiz_davranis_degismez(self):
        f = self.ortam.satis(2, 50, date.today())  # 2 × 50 + %20 = 120
        d = self._ac(f.id)
        self.assertFalse(d._referans_fiyat_aktif())
        self.assertEqual(d._fatura_genel_toplam(), Decimal("120.00"))
        # Kilitli (onaylı) — Uzlaşılan girişi fiyatları değiştirmez
        once = [v["birim_satis_fiyati"] for v in d.satirlar]
        self._uzlasilan(d, "100")
        self.assertEqual([v["birim_satis_fiyati"] for v in d.satirlar], once)


class ServisTaramaTest(_FaturaEkraniTabani):
    def test_dagitilmis_fatura_uyusmaz_sayilmaz(self):
        from database.servis_sistem.scanners.fatura import scan_fatura
        from database.servis_sistem.system_health_service import CheckReport

        self._sat(self._sepet_1000("900"))
        rapor = CheckReport(baslik="test", baslangic="")
        scan_fatura(rapor, yon="satis")
        self.assertNotIn("FATURA_TOPLAM_UYUSMAZ", [m.hata_kodu for m in rapor.maddeler])


class FiyatKdvAnlamiTest(_DbTabani):
    def _kdv_yaz(self, fiyat_adi, durum):
        from database.database import get_session
        from database.models.stok import StokFiyati
        from sqlalchemy import select

        with get_session() as s:
            f = s.scalar(select(StokFiyati).where(StokFiyati.stok_id == self.stok_id,
                                                  StokFiyati.fiyat_adi == fiyat_adi))
            f.kdv_durumu = durum
            s.commit()

    def _secenek(self, fiyat_adi, birim="Adet", kdv=None):
        from database.hizli_satis_satir_service import fiyat_secenekleri

        return next(s for s in fiyat_secenekleri("U001", birim, fiyat_degistirme_izni=True, maliyet_izni=True,
                                                 satir_kdv_orani=kdv) if s["fiyat_adi"] == fiyat_adi)

    def test_belirtilmemis_varsayim_yapmaz(self):
        s = self._secenek("SATIŞ FİYATI 2", kdv=Decimal("20"))
        self.assertEqual(s["kdv"], "KDV durumu belirtilmemiş")
        self.assertTrue(s["kdv_onay_gerekli"])
        self.assertEqual(s["uygulanacak"], Decimal("12"))

    def test_hariç_ve_dahil_farkli_birim_kdv(self):
        self._kdv_yaz("SATIŞ FİYATI 2", "HARIC")
        s = self._secenek("SATIŞ FİYATI 2", "Koli", kdv=Decimal("20"))
        self.assertEqual((s["kdv"], s["kdv_onay_gerekli"], s["uygulanacak"]), ("KDV hariç", False, Decimal("120")))
        self._kdv_yaz("SATIŞ FİYATI 2", "DAHIL")
        s = self._secenek("SATIŞ FİYATI 2", "Koli", kdv=Decimal("20"))
        self.assertEqual(s["kdv"], "KDV dahil")
        self.assertEqual(s["uygulanacak"], Decimal("100.0000"))  # 120 / 1,20
        s10 = self._secenek("SATIŞ FİYATI 2", "Adet", kdv=Decimal("10"))
        self.assertEqual(s10["uygulanacak"], Decimal("10.9091"))  # 12 / 1,10
        bos = self._secenek("SATIŞ FİYATI 2", "Adet", kdv=None)
        self.assertFalse(bos["kullanilabilir"])

    def test_doviz_dahil_fiyat_tl_ve_net(self):
        from database.database import get_session
        from database.models.stok import StokFiyati

        with get_session() as s:
            s.add(StokFiyati(stok_id=self.stok_id, fiyat_adi="SATIŞ FİYATI 4", tutar=Decimal("3"),
                             para_birimi="USD", kdv_durumu="DAHIL"))
            s.commit()
        with patch("database.doviz_service.DovizService.kur_degeri", return_value=Decimal("40")):
            s = self._secenek("SATIŞ FİYATI 4", kdv=Decimal("20"))
        self.assertEqual(s["para_birimi"], "USD")
        self.assertEqual(s["uygulanacak"], Decimal("100.0000"))  # 3 USD × 40 = 120 TL dahil → 100 net

    def test_alis_fiyati_hariç_yazilir_kart_kaydi_korur(self):
        from database.database import get_session
        from database.models.stok import StokFiyati
        from database.stok_service import StokService
        from sqlalchemy import select

        with get_session() as s:
            StokService.alis_fiyatini_guncelle(s, "U001", Decimal("6"))
            s.commit()
        with get_session() as s:
            alis = s.scalar(select(StokFiyati).where(StokFiyati.stok_id == self.stok_id,
                                                     StokFiyati.fiyat_adi == "ALIŞ FİYATI"))
            self.assertEqual((alis.kdv_durumu, Decimal(str(alis.tutar))), ("HARIC", Decimal("6")))
        self.assertEqual(self._secenek("ALIŞ FİYATI")["kdv"], "KDV hariç")
        # Stok kartı kaydı fiyatları yeniden yazarken KDV anlamını korur
        self._kdv_yaz("SATIŞ FİYATI 2", "DAHIL")
        StokService.stok_kaydi(
            {"stok_id": self.stok_id, "stok_kodu": "U001", "stok_adi": "Test Ürün", "birim": "Adet"},
            [("SATIŞ FİYATI 1", "10"), ("SATIŞ FİYATI 2", "13"), ("ALIŞ FİYATI", "6")],
        )
        with get_session() as s:
            durumlar = {f.fiyat_adi: (f.kdv_durumu, Decimal(str(f.tutar))) for f in s.scalars(
                select(StokFiyati).where(StokFiyati.stok_id == self.stok_id))}
        self.assertEqual(durumlar["SATIŞ FİYATI 2"], ("DAHIL", Decimal("13")))
        self.assertEqual(durumlar["ALIŞ FİYATI"][0], "HARIC")
        self.assertIsNone(durumlar["SATIŞ FİYATI 1"][0])

    def test_kdv_dahilden_net(self):
        from database.hizli_satis_satir_service import kdv_dahilden_net, kdv_durumu_normalle

        self.assertEqual(kdv_dahilden_net(Decimal("118"), Decimal("18")), Decimal("100.0000"))
        self.assertEqual(kdv_dahilden_net(Decimal("50"), Decimal("0")), Decimal("50.0000"))
        self.assertEqual(kdv_durumu_normalle(" dahil "), "DAHIL")
        self.assertEqual(kdv_durumu_normalle("Hariç"), "HARIC")
        self.assertIsNone(kdv_durumu_normalle("??"))
        self.assertIsNone(kdv_durumu_normalle(None))


class KdvKolonGocuTest(unittest.TestCase):
    def test_stok_fiyatlarina_kdv_durumu_eklenir_veri_korunur(self):
        import tempfile

        from sqlalchemy import create_engine, inspect, text

        from database.database import _aktif_engine_bagla, company_db, doviz_schema_guncelle

        with tempfile.TemporaryDirectory() as tmp:
            eng = create_engine(f"sqlite:///{Path(tmp, 'eski.db').as_posix()}")
            with eng.begin() as c:
                c.execute(text("CREATE TABLE stok_fiyatlari (id INTEGER PRIMARY KEY, stok_id INTEGER, "
                               "fiyat_adi VARCHAR(50), tutar NUMERIC(18,4), para_birimi VARCHAR(10))"))
                c.execute(text("INSERT INTO stok_fiyatlari VALUES (1, 1, 'SATIŞ FİYATI 1', 10, 'TL')"))
            onceki = company_db._engine
            _aktif_engine_bagla(eng)
            company_db._engine = eng
            try:
                doviz_schema_guncelle()
                self.assertIn("kdv_durumu", {k["name"] for k in inspect(eng).get_columns("stok_fiyatlari")})
                with eng.connect() as c:
                    satir = c.execute(text("SELECT tutar, kdv_durumu FROM stok_fiyatlari")).one()
                self.assertEqual((Decimal(str(satir[0])), satir[1]), (Decimal("10"), None))
            finally:
                company_db._engine = onceki
                eng.dispose()


class IrsaliyeIadeHareketTest(_DbTabani):
    def _irsaliye(self, cari_id, miktar="3"):
        from database.satis_irsaliyesi_service import SatisIrsaliyesiService

        irs = SatisIrsaliyesiService.kaydet(
            {"irsaliye_tarihi": date.today(), "cari_id": cari_id, "depo": "ANA DEPO"},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal(miktar), "birim": "Adet",
              "birim_fiyat": Decimal("10"), "kdv_orani": Decimal("20")}],
        )
        return SatisIrsaliyesiService.sevk_et(irs.id)

    def test_iade_kaynak_belgenin_carisine_baglanir(self):
        from database.hizli_satis_satir_service import stok_hareketleri
        from database.satis_irsaliyesi_service import SatisIrsaliyesiService

        irs_a = self._irsaliye(self.ortam.mus_id)
        iade_a = SatisIrsaliyesiService.iade_olustur(irs_a.id)
        irs_b = self._irsaliye(self.m2_id, "2")
        a = stok_hareketleri(self.stok_id, cari_id=self.ortam.mus_id)
        belgeler = {r["belge_no"]: r for r in a["satirlar"]}
        self.assertIn(irs_a.irsaliye_no, belgeler)
        self.assertIn(iade_a.irsaliye_no, belgeler)
        self.assertNotIn(irs_b.irsaliye_no, belgeler)
        iade = belgeler[iade_a.irsaliye_no]
        self.assertEqual((iade["belge_turu"], iade["yon"], iade["cari_id"]),
                         ("İrsaliye İadesi", "giris", self.ortam.mus_id))
        self.assertEqual(belgeler[irs_a.irsaliye_no]["belge_turu"], "Satış İrsaliyesi")
        b = stok_hareketleri(self.stok_id, cari_id=self.m2_id)
        self.assertEqual([r["belge_no"] for r in b["satirlar"]], [irs_b.irsaliye_no])
        tumu = [r["belge_no"] for r in stok_hareketleri(self.stok_id, cari_id=None)["satirlar"]]
        self.assertTrue({irs_a.irsaliye_no, iade_a.irsaliye_no, irs_b.irsaliye_no} <= set(tumu))

    def test_baglanti_belirsiz_hareket_musteriye_gitmez(self):
        from database.database import get_session
        from database.hizli_satis_satir_service import stok_hareketleri
        from database.models.stok import StokHareketi
        from sqlalchemy import select

        irs = self._irsaliye(self.ortam.mus_id)
        with get_session() as s:
            h = s.scalar(select(StokHareketi).where(StokHareketi.belge_no == irs.irsaliye_no))
            h.belge_no = "BILINMEYEN-1"
            s.commit()
        a = stok_hareketleri(self.stok_id, cari_id=self.ortam.mus_id)
        self.assertNotIn("BILINMEYEN-1", [r["belge_no"] for r in a["satirlar"]])
        self.assertIn("BILINMEYEN-1",
                      [r["belge_no"] for r in stok_hareketleri(self.stok_id, cari_id=None)["satirlar"]])

    def test_onceki_donem_tarih_araligi(self):
        from database.database import get_session
        from database.hizli_satis_satir_service import hareket_donem_secenekleri, stok_hareketleri
        from database.models.stok import StokHareketi
        from sqlalchemy import select

        eski = self._sat(self._sepet(miktar="1"))
        yeni = self._sat(self._sepet(miktar="2"))
        with get_session() as s:
            for h in s.scalars(select(StokHareketi).where(StokHareketi.belge_no == eski["fatura_no"])):
                h.tarih = date(2025, 5, 1)
            s.commit()
        varsayilan = [r["belge_no"] for r in stok_hareketleri(self.stok_id, cari_id=self.ortam.mus_id)["satirlar"]]
        self.assertEqual(varsayilan, [yeni["fatura_no"]])
        onceki = stok_hareketleri(self.stok_id, cari_id=self.ortam.mus_id,
                                  baslangic=date(2025, 1, 1), bitis=date(2025, 12, 31))
        self.assertEqual([r["belge_no"] for r in onceki["satirlar"]], [eski["fatura_no"]])
        secenekler = hareket_donem_secenekleri()
        self.assertTrue(secenekler[0]["etiket"].startswith("Aktif dönem"))
        self.assertEqual(secenekler[-1]["etiket"], "Tüm tarihler")
        tum = stok_hareketleri(self.stok_id, cari_id=self.ortam.mus_id,
                               baslangic=secenekler[-1]["baslangic"], bitis=secenekler[-1]["bitis"])
        self.assertEqual([r["belge_no"] for r in tum["satirlar"]], [yeni["fatura_no"], eski["fatura_no"]])
        with self.assertRaises(ValueError):
            stok_hareketleri(self.stok_id, cari_id=None, baslangic=date(2026, 5, 1), bitis=date(2026, 1, 1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
