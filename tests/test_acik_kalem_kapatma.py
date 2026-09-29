"""Açık borç/alacak kapatma: FIFO, kısmi/tam, manuel seçim, pencere kapatılınca FIFO, aynı gün sırası,
fazla ödeme/avans, iptal (geri alma), eşzamanlı kapatma, devir, dekont, döviz ayrımı, mutabakat,
kasa makbuzu seçimi ve seçim penceresi.

Yalnız geçici test veritabanı kullanır (TahsilatMakbuzuTest kurulumu).
"""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text

from database.acik_kalem_service import AcikKalemDegisti, AcikKalemService
from database.cari_service import CariService
from database.database import get_session
from database.finans_service import FinansService
from database.models.cari import Cari, CariKapatma, SatisHareketi
from tests import test_tahsilat_makbuzu as _servis_testi

D = Decimal


def _kalem(s, cari_id, belge, tarih, tutar, **ek):
    h = SatisHareketi(cari_id=cari_id, satis_tarihi=tarih, belge_no=belge,
                      satis_tutari=D(tutar), kalan_acik_tutar=D(tutar), **ek)
    s.add(h)
    s.flush()
    return h.id


def _kalan(hid):
    with get_session() as s:
        return D(str(s.get(SatisHareketi, hid).kalan_acik_tutar))


def _avans(cari_id):
    with get_session() as s:
        return sum(
            (-D(str(h.kalan_acik_tutar)) for h in s.scalars(
                select(SatisHareketi).where(SatisHareketi.cari_id == cari_id, SatisHareketi.kalan_acik_tutar < 0)
            ).all()),
            D("0"),
        )


def _kayitlar(belge_no):
    with get_session() as s:
        return list(s.scalars(select(CariKapatma).where(CariKapatma.kaynak_belge_no == belge_no)
                              .order_by(CariKapatma.id)).all())


def _mutabakat(cari_id):
    with get_session() as s:
        return AcikKalemService.mutabakat(s, cari_id)


class AcikKalemTemel(unittest.TestCase):
    def setUp(self):
        _servis_testi.TahsilatMakbuzuTest.setUp(self)
        with get_session() as s:
            AcikKalemService.schema_hazirla(s.get_bind())
            c = Cari(cari_kodu="M900", unvan="KAPATMA TEST MÜŞTERİ", cari_turu="Müşteri")
            s.add(c)
            s.flush()
            self.cid = c.id
            self.a = _kalem(s, c.id, "SF-A", date(2026, 1, 10), "100")
            self.b = _kalem(s, c.id, "SF-B", date(2026, 2, 10), "200")

    def tearDown(self):
        _servis_testi.TahsilatMakbuzuTest.tearDown(self)

    def _tahsilat(self, tutar, **ek):
        return CariService.tahsilat_yap(self.cid, date.today(), tutar, "NAKİT", "TEST KASA", None, **ek)


class FifoVeKismiTest(AcikKalemTemel):
    def test_kismi_tahsilat_fifo_en_eskiden(self):
        islem = self._tahsilat("150")
        self.assertEqual((_kalan(self.a), _kalan(self.b)), (D("0.00"), D("150.00")))
        kayit = _kayitlar(islem.belge_no)
        self.assertEqual([(k.hedef_hareket_id, D(str(k.tutar)), k.yontem) for k in kayit],
                         [(self.a, D("100.00"), "FIFO"), (self.b, D("50.00"), "FIFO")])
        self.assertEqual(len({k.islem_kimligi for k in kayit}), 1)
        self.assertTrue(all(k.kullanici_adi for k in kayit))
        self.assertTrue(_mutabakat(self.cid)["uyumlu"])

    def test_tam_tahsilat_ve_fazla_avans(self):
        self._tahsilat("400")
        self.assertEqual((_kalan(self.a), _kalan(self.b)), (D("0.00"), D("0.00")))
        self.assertEqual(_avans(self.cid), D("100.00"))
        m = _mutabakat(self.cid)
        self.assertEqual((m["bakiye"], m["acik_net"], m["uyumlu"]), (D("-100.00"), D("-100.00"), True))

    def test_avans_sonraki_borca_uygulanir(self):
        self._tahsilat("400")
        with get_session() as s:
            yeni = _kalem(s, self.cid, "SF-C", date(2026, 3, 1), "60")
            AcikKalemService.avanslari_uygula(s, self.cid)
        self.assertEqual((_kalan(yeni), _avans(self.cid)), (D("0.00"), D("40.00")))
        self.assertTrue(_mutabakat(self.cid)["uyumlu"])

    def test_ayni_gun_evrak_no_sonra_id(self):
        with get_session() as s:
            ikinci = _kalem(s, self.cid, "SF-Z2", date(2025, 12, 1), "10")
            birinci = _kalem(s, self.cid, "SF-Z1", date(2025, 12, 1), "10")
            ayni_no_ilk = _kalem(s, self.cid, "SF-Z3", date(2025, 12, 1), "10")
            ayni_no_son = _kalem(s, self.cid, "SF-Z3", date(2025, 12, 1), "10")
        self._tahsilat("25")
        self.assertEqual(
            [_kalan(h) for h in (birinci, ikinci, ayni_no_ilk, ayni_no_son)],
            [D("0.00"), D("0.00"), D("5.00"), D("10.00")],
        )


class ManuelSecimTest(AcikKalemTemel):
    def test_manuel_secim_yalniz_secilen_kalan_avans(self):
        islem = self._tahsilat("80", dagitim=[(self.b, D("50"))], fazla="AVANS")
        self.assertEqual((_kalan(self.a), _kalan(self.b), _avans(self.cid)), (D("100.00"), D("150.00"), D("30.00")))
        kayit = _kayitlar(islem.belge_no)
        self.assertEqual([(k.hedef_hareket_id, k.yontem) for k in kayit], [(self.b, "MANUEL")])

    def test_manuel_secim_kalan_fifo(self):
        self._tahsilat("80", dagitim=[(self.b, D("50"))], fazla="FIFO")
        self.assertEqual((_kalan(self.a), _kalan(self.b), _avans(self.cid)), (D("70.00"), D("150.00"), D("0")))

    def test_pencere_kapatilinca_fifo(self):
        self._tahsilat("80")
        self.assertEqual((_kalan(self.a), _kalan(self.b)), (D("20.00"), D("200.00")))

    def test_fazla_tahsis_reddedilir(self):
        with self.assertRaises(ValueError):
            self._tahsilat("80", dagitim=[(self.b, D("90"))])
        with self.assertRaises(ValueError):
            self._tahsilat("300", dagitim=[(self.a, D("150"))])
        self.assertEqual((_kalan(self.a), _kalan(self.b)), (D("100.00"), D("200.00")))

    def test_baska_carinin_kalemi_secilemez(self):
        with get_session() as s:
            yabanci = _kalem(s, self.musteri_id, "SF-X", date(2026, 1, 1), "50")
        with self.assertRaises(ValueError):
            self._tahsilat("50", dagitim=[(yabanci, D("50"))])
        self.assertEqual(_kalan(yabanci), D("50.00"))


class IptalVeEszamanlilikTest(AcikKalemTemel):
    def test_iptal_kapatmalari_geri_alir_iz_kalir(self):
        islem = self._tahsilat("400")
        with get_session() as s:
            AcikKalemService.belge_geri_al(s, self.cid, islem.belge_no, neden="test iptal")
        self.assertEqual((_kalan(self.a), _kalan(self.b), _avans(self.cid)), (D("100.00"), D("200.00"), D("0")))
        kayit = _kayitlar(islem.belge_no)
        self.assertEqual(len(kayit), 2)
        self.assertTrue(all(k.iptal and k.iptal_nedeni == "test iptal" and k.iptal_zamani for k in kayit))

    def test_eszamanli_degisiklik_manuel_secimi_durdurur(self):
        with get_session() as s:
            eski = s.get(SatisHareketi, self.b)
            self.assertEqual(D(str(eski.kalan_acik_tutar)), D("200.00"))
            with self.eng.begin() as baglanti:
                baglanti.execute(text("UPDATE cari_satis_hareketleri SET kalan_acik_tutar = 20 WHERE id = :i"),
                                 {"i": self.b})
            with self.assertRaises(AcikKalemDegisti):
                AcikKalemService.kapat(s, self.cid, D("100"), belge_no="THS-EZ", kaynak_tur="TAHSILAT",
                                       tarih=date.today(), dagitim=[(self.b, D("100"))], fifo=False)
            s.rollback()
        self.assertEqual(_kalan(self.b), D("20.00"))

    def test_eszamanli_degisiklik_fifo_guncel_degerle(self):
        with get_session() as s:
            s.get(SatisHareketi, self.a)
            with self.eng.begin() as baglanti:
                baglanti.execute(text("UPDATE cari_satis_hareketleri SET kalan_acik_tutar = 30 WHERE id = :i"),
                                 {"i": self.a})
            sonuc = AcikKalemService.kapat(s, self.cid, D("50"), belge_no="THS-EZ2", kaynak_tur="TAHSILAT",
                                           tarih=date.today())
            self.assertEqual(sonuc.kapanan, D("50.00"))
        self.assertEqual((_kalan(self.a), _kalan(self.b)), (D("0.00"), D("180.00")))


class DevirDekontDovizTest(AcikKalemTemel):
    def test_devir_borc_acik_kalem_ve_alacak_devri_avans(self):
        with get_session() as s:
            c = Cari(cari_kodu="M901", unvan="DEVİR MÜŞTERİ", cari_turu="Müşteri")
            s.add(c)
            s.flush()
            cid = c.id
        CariService.acilis_fisi_ekle(cid, date(2026, 1, 1), borc="500", belge_no="DVR-1")
        CariService.tahsilat_yap(cid, date.today(), "200", "NAKİT", "TEST KASA")
        with get_session() as s:
            acik = AcikKalemService.acik_kalemler(s, cid)
            self.assertEqual([(h.belge_no, D(str(h.kalan_acik_tutar))) for h in acik], [("DVR-1", D("300.00"))])
        CariService.acilis_fisi_ekle(cid, date(2026, 1, 2), alacak="400", belge_no="DVR-2")
        self.assertEqual(_avans(cid), D("100.00"))
        self.assertTrue(_mutabakat(cid)["uyumlu"])

    def test_alinan_havale_dekontu_kapatir_ve_duzenlemede_geri_alir(self):
        belge = FinansService.alinan_havale(self.kmh_id, date.today(), D("120"), cari_id=self.cid,
                                            dekont_no="DK-1")
        self.assertEqual((_kalan(self.a), _kalan(self.b)), (D("0.00"), D("180.00")))
        FinansService.alinan_havale(self.kmh_id, date.today(), D("50"), cari_id=self.cid, belge_no=belge)
        self.assertEqual((_kalan(self.a), _kalan(self.b)), (D("50.00"), D("200.00")))
        self.assertTrue(_mutabakat(self.cid)["uyumlu"])

    def test_doviz_kalemi_tl_tahsilatla_kapanmaz(self):
        with get_session() as s:
            usd = _kalem(s, self.cid, "SF-USD", date(2025, 1, 1), "1000", para_birimi="USD",
                         doviz_tutari=D("30"), kur=D("33.33"), borc_esasi="DOVIZ_SABIT")
        self._tahsilat("350")
        self.assertEqual(_kalan(usd), D("1000.00"))
        self.assertEqual((_kalan(self.a), _kalan(self.b), _avans(self.cid)), (D("0.00"), D("0.00"), D("50.00")))


class RaporVeMakbuzTest(AcikKalemTemel):
    def test_acik_kalem_raporu_alanlari(self):
        self._tahsilat("30")
        with get_session() as s:
            rapor = AcikKalemService.acik_kalem_raporu(s, self.cid, bugun=date(2026, 3, 1))
        satir = next(r for r in rapor if r["evrak_no"] == "SF-A")
        for alan in ("cari_id", "evrak_turu", "evrak_no", "evrak_tarihi", "vade", "orijinal", "kapanan",
                     "acik", "para_birimi", "tahsisler", "gecikme_gunu"):
            self.assertIn(alan, satir)
        self.assertEqual((satir["orijinal"], satir["kapanan"], satir["acik"]), (D("100.00"), D("30.00"), D("70.00")))
        self.assertEqual(satir["gecikme_gunu"], 50)
        self.assertEqual(len(satir["tahsisler"]), 1)

    def test_kasa_makbuzu_secili_kalem(self):
        m = FinansService.kasa_tahsilat_makbuzu_kaydet({
            "tarih": date.today(), "cari_id": self.cid, "makbuz_no_otomatik": True,
            "satirlar": [{"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": "40"},
                         {"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": "30"}],
            "kapatma_dagitimi": [{"hareket_id": self.b, "tutar": "60"}],
            "kapatma_fazla": "AVANS",
        })
        self.assertTrue(m.makbuz_no)
        self.assertEqual((_kalan(self.a), _kalan(self.b), _avans(self.cid)), (D("100.00"), D("140.00"), D("10.00")))
        self.assertTrue(_mutabakat(self.cid)["uyumlu"])

    def test_gecis_kuru_calisma_ve_devir_farki(self):
        from database.acik_kalem_gecis import gecis_kuru_calisma, gecis_uygula

        with get_session() as s:
            s.execute(text("UPDATE cari_satis_hareketleri SET kalan_acik_tutar = 0 WHERE id = :i"), {"i": self.a})
        with get_session() as s:
            rapor = gecis_kuru_calisma(s)
            satir = next(c for c in rapor["cariler"] if c["cari_id"] == self.cid)
            self.assertEqual((satir["fark"], satir["oneri"]["islem"]), (D("100.00"), "DEVIR_FARKI"))
            self.assertEqual(_kalan(self.a), D("0.00"))
            uygulanan = gecis_uygula(s, rapor)
            self.assertTrue(any(u["cari_id"] == self.cid for u in uygulanan))
        self.assertTrue(_mutabakat(self.cid)["uyumlu"])


class TahsilatGirEkranTest(AcikKalemTemel):
    def setUp(self):
        super().setUp()
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()
        super().tearDown()

    def _dialog(self, tutar):
        import app

        cari = CariService.getir(self.cid)
        d = app.CariTahsilatOdemeDialog(self.root, cari, "tahsilat")
        d.girdiler["tutar"].delete(0, "end")
        d.girdiler["tutar"].insert(0, tutar)
        d.girdiler["hesap"].set("TEST KASA")
        return d

    def test_manuel_secim_ekrandan_servise(self):
        d = self._dialog("80")
        with patch("acik_kalem_secim_ui.kapatma_plani_sor",
                   return_value=(True, {"dagitim": [(self.b, D("50"))], "fazla": "AVANS"})):
            d.kaydet()
        self.assertEqual((_kalan(self.a), _kalan(self.b), _avans(self.cid)), (D("100.00"), D("150.00"), D("30.00")))

    def test_pencere_kapatilinca_ekrandan_fifo(self):
        d = self._dialog("80")
        with patch("acik_kalem_secim_ui.kapatma_plani_sor", return_value=(True, None)):
            d.kaydet()
        self.assertEqual((_kalan(self.a), _kalan(self.b)), (D("20.00"), D("200.00")))

    def test_tutar_degisirse_pencere_yeniden_sorulur(self):
        d = self._dialog("80")
        with patch("acik_kalem_secim_ui.kapatma_plani_sor", return_value=(True, None)) as sor:
            d._plani_sor()
            d._plani_sor()
            self.assertEqual(sor.call_count, 1)
            d.girdiler["tutar"].delete(0, "end")
            d.girdiler["tutar"].insert(0, "90")
            d.kaydet()
            self.assertEqual(sor.call_count, 2)


class SecimPenceresiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def _pencere(self, tutar="150"):
        from acik_kalem_secim_ui import AcikKalemSecimDialog

        kalemler = [
            {"hareket_id": 1, "tarih": date(2026, 1, 1), "tur": "Satış Faturası", "evrak_no": "SF-1",
             "ilk_tutar": D("100"), "kapanan": D("0"), "kalan": D("100"), "vade": date(2026, 1, 31)},
            {"hareket_id": 2, "tarih": date(2026, 2, 1), "tur": "Satış Faturası", "evrak_no": "SF-2",
             "ilk_tutar": D("200"), "kapanan": D("50"), "kalan": D("150"), "vade": None},
        ]
        return AcikKalemSecimDialog(self.root, 9, D(tutar), kalemler=kalemler)

    def test_kolonlar_ve_seçimsiz_kapatma_fifo(self):
        p = self._pencere()
        self.assertEqual(p.KOLONLAR[1:8], ("tarih", "tur", "evrak", "ilk", "kapanan", "kalan", "vade"))
        p.kapat()
        self.assertIsNone(p.sonuc)

    def test_coklu_secim_canli_toplam_ve_kalan_avans(self):
        p = self._pencere()
        p.tablo.selection_set(("2",))
        p.secimi_degistir()
        self.assertEqual(p.dagitim, {2: D("150.00")})
        p.kalem_tutar.delete(0, "end")
        p.kalem_tutar.insert(0, "60")
        p.kalem_tutari_uygula()
        p.tablo.selection_set(("1",))
        p.secimi_degistir()
        self.assertEqual(p.dagitim, {2: D("60.00"), 1: D("90.00")})
        self.assertIn("Dağıtılmayan: 0,00", p.toplam_lbl.cget("text"))
        p.kalem_tutar.delete(0, "end")
        p.kalem_tutar.insert(0, "40")
        p.kalem_tutari_uygula()
        with patch.object(p, "_fazla_yontemi_sor", return_value="AVANS"):
            p.uygula()
        self.assertEqual(p.sonuc, {"dagitim": [(1, D("40.00")), (2, D("60.00"))], "fazla": "AVANS"})

    def test_fazla_tahsis_engellenir(self):
        p = self._pencere("50")
        p.tablo.selection_set(("1",))
        p.secimi_degistir()
        p.kalem_tutar.delete(0, "end")
        p.kalem_tutar.insert(0, "80")
        with patch("acik_kalem_secim_ui.messagebox.showerror") as hata:
            p.kalem_tutari_uygula()
        hata.assert_called_once()
        self.assertEqual(p.dagitim, {1: D("50.00")})
        p.kapat()


if __name__ == "__main__":
    unittest.main()
