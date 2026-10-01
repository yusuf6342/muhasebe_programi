"""TL cari hareketlerin işlem tarihindeki USD karşılığı: kur seçimi, eksik kur, manuel kur,
tarih değişimi, yeniden açma, tarih aralığı devri ve tarihsel USD karşılık farkı.

Yalnız geçici test veritabanı kullanır (TahsilatMakbuzuTest kurulumu); internete çıkılmaz.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from database import cari_usd_karsilik_service as usd
from database.database import get_session
from database.models.cari import Cari, CariIslem, CariUsdKarsilik, SatisHareketi
from database.models.doviz import DovizKuru
from tests import test_tahsilat_makbuzu as _servis_testi


def _kur(tarih, satis, alis=None, kaynak="TCMB"):
    with get_session() as s:
        s.add(DovizKuru(
            rate_date=tarih, currency_code="USD",
            forex_buying=Decimal(str(alis if alis is not None else Decimal(str(satis)) - Decimal("0.1"))),
            forex_selling=Decimal(str(satis)), effective_buying=0, effective_selling=0, source=kaynak,
        ))


def _islem(cari_id, tarih, borc=0, alacak=0, belge="T-1", tur="Tahsilat"):
    with get_session() as s:
        i = CariIslem(cari_id=cari_id, tarih=tarih, islem_turu=tur, belge_no=belge,
                      borc=Decimal(str(borc)), alacak=Decimal(str(alacak)))
        s.add(i)
        s.flush()
        return int(i.id)


def _karsilik(kaynak_id, kaynak=usd.KAYNAK_ISLEM):
    with get_session() as s:
        return s.scalar(select(CariUsdKarsilik).where(
            CariUsdKarsilik.kaynak == kaynak, CariUsdKarsilik.kaynak_id == kaynak_id))


def _internet_yok(*_a, **_k):
    raise ValueError("TCMB kurları alınamadı. İnternet bağlantınızı kontrol edip tekrar deneyin.")


class CariUsdKarsilikTest(unittest.TestCase):
    def setUp(self):
        _servis_testi.TahsilatMakbuzuTest.setUp(self)
        with get_session() as s:
            c = Cari(cari_kodu="U001", unvan="USD TEST MÜŞTERİ", cari_turu="Müşteri")
            s.add(c)
            s.flush()
            self.cari_id = int(c.id)
        self._ag = patch("database.doviz_service.DovizService._tcmb_xml_indir", side_effect=_internet_yok)
        self.ag_mock = self._ag.start()

    def tearDown(self):
        self._ag.stop()
        _servis_testi.TahsilatMakbuzuTest.tearDown(self)

    # —— kur seçimi ——
    def test_islem_tarihindeki_kur_saklanir(self):
        _kur(date(2026, 3, 2), "50")
        iid = _islem(self.cari_id, date(2026, 3, 2), borc="1000")
        k = _karsilik(iid)
        self.assertEqual(k.durum, "TAMAM")
        self.assertEqual(Decimal(str(k.usd_kur)), Decimal("50"))
        self.assertEqual(k.kur_tarihi, date(2026, 3, 2))
        self.assertEqual(k.islem_tarihi, date(2026, 3, 2))
        self.assertEqual(k.kur_turu, "forex_selling")
        self.assertEqual(k.kur_kaynagi, "TCMB")
        self.assertEqual(Decimal(str(k.tl_borc)), Decimal("1000.00"))
        self.assertEqual(Decimal(str(k.usd_borc)), Decimal("20.00"))

    def test_tatilde_onceki_kur_sonraki_asla(self):
        _kur(date(2026, 3, 6), "40")   # Cuma
        _kur(date(2026, 3, 9), "45")   # Pazartesi (sonraki gün; kullanılmamalı)
        iid = _islem(self.cari_id, date(2026, 3, 8), borc="400")  # Pazar
        k = _karsilik(iid)
        self.assertEqual(Decimal(str(k.usd_kur)), Decimal("40"))
        self.assertEqual(k.kur_tarihi, date(2026, 3, 6))
        self.assertEqual(k.islem_tarihi, date(2026, 3, 8))
        r = usd.cari_usd_raporu(self.cari_id)
        self.assertTrue(r["satirlar"][0]["onceki_gun_kuru"])

    def test_hedefe_kopyalanmis_tcmb_kurunda_gercek_kur_tarihi(self):
        _kur(date(2026, 3, 6), "40", alis="39.9")
        _kur(date(2026, 3, 8), "40", alis="39.9")  # tcmb_kurlari_cek(hedefe_kopyala=True) kopyası
        iid = _islem(self.cari_id, date(2026, 3, 8), borc="400")
        self.assertEqual(_karsilik(iid).kur_tarihi, date(2026, 3, 6))

    def test_kur_yoksa_eksik_bugun_kuru_veya_1_kullanilmaz(self):
        _kur(date.today(), "99")
        iid = _islem(self.cari_id, date(2025, 1, 15), borc="1000")
        k = _karsilik(iid)
        self.assertEqual(k.durum, "EKSIK")
        self.assertIsNone(k.usd_kur)
        self.assertIsNone(k.usd_borc)
        r = usd.cari_usd_raporu(self.cari_id)
        self.assertFalse(r["tam"])
        self.assertEqual(r["eksik_sayisi"], 1)
        self.assertEqual(r["toplam"]["usd_borc"], Decimal("0.00"))
        self.assertEqual(r["tl_bakiye"], Decimal("1000.00"))

    def test_sifir_kur_kullanilmaz(self):
        _kur(date(2026, 3, 2), "0", alis="0")
        iid = _islem(self.cari_id, date(2026, 3, 2), borc="1000")
        self.assertEqual(_karsilik(iid).durum, "EKSIK")

    # —— bağlantı yok / manuel kur ——
    def test_baglanti_yokken_kayitli_kur_kullanilir_yoksa_bildirilir(self):
        with get_session() as s:
            s.execute(CariUsdKarsilik.__table__.delete())
        _kur(date(2026, 4, 1), "38")
        _islem(self.cari_id, date(2026, 4, 2), borc="380", belge="A-1")
        _islem(self.cari_id, date(2025, 2, 2), borc="100", belge="A-2")
        with get_session() as s:
            s.execute(CariUsdKarsilik.__table__.delete())
        o = usd.eksik_kur_onizleme(self.cari_id, internetten=True)
        self.assertTrue(self.ag_mock.called)
        oneriler = {r["belge_no"]: r["oneri"] for r in o["satirlar"]}
        self.assertEqual(oneriler["A-1"]["kur"], Decimal("38"))
        self.assertEqual(oneriler["A-1"]["kur_tarihi"], date(2026, 4, 1))
        self.assertIsNone(oneriler["A-2"])
        self.assertIn(date(2025, 2, 2), o["hatalar"])
        self.assertIn("İnternet", o["hatalar"][date(2025, 2, 2)])
        self.assertIn(date(2025, 2, 2), o["kur_bulunamayan_tarihler"])

    def test_manuel_kur_sifir_negatif_reddedilir_gecerli_kaydedilir(self):
        iid = _islem(self.cari_id, date(2025, 2, 2), borc="425")
        o = usd.eksik_kur_onizleme(self.cari_id)
        with self.assertRaises(ValueError):
            usd.eksik_kurlari_uygula(o["satirlar"], {date(2025, 2, 2): "0"})
        with self.assertRaises(ValueError):
            usd.eksik_kurlari_uygula(o["satirlar"], {date(2025, 2, 2): "-5"})
        self.assertEqual(_karsilik(iid).durum, "EKSIK")
        sonuc = usd.eksik_kurlari_uygula(o["satirlar"], {date(2025, 2, 2): "42,5"})
        self.assertGreaterEqual(sonuc["manuel"], 1)
        k = _karsilik(iid)
        self.assertEqual(k.durum, "TAMAM")
        self.assertEqual(k.kur_kaynagi, "MANUEL")
        self.assertEqual(k.kur_tarihi, date(2025, 2, 2))
        self.assertEqual(Decimal(str(k.usd_borc)), Decimal("10.00"))
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(DovizKuru.id))), 0, "manuel kur kur tablosuna yazılmaz")

    def test_tamam_kayit_tamamlamada_degismez(self):
        _kur(date(2026, 3, 2), "50")
        iid = _islem(self.cari_id, date(2026, 3, 2), borc="1000")
        satirlar = [{"kaynak": usd.KAYNAK_ISLEM, "kaynak_id": iid}]
        sonuc = usd.eksik_kurlari_uygula(satirlar, {date(2026, 3, 2): "60"})
        self.assertEqual(sonuc["yazilan"], 0)
        self.assertEqual(Decimal(str(_karsilik(iid).usd_kur)), Decimal("50"))

    # —— tarih / tutar değişimi, yeniden açma ——
    def test_tarih_degisince_kur_yeniden_bulunur_tutar_degisince_korunur(self):
        _kur(date(2026, 3, 2), "50")
        _kur(date(2026, 5, 4), "40")
        iid = _islem(self.cari_id, date(2026, 3, 2), borc="1000")
        with get_session() as s:
            s.get(CariIslem, iid).borc = Decimal("2000")
        k = _karsilik(iid)
        self.assertEqual(Decimal(str(k.usd_kur)), Decimal("50"))
        self.assertEqual(Decimal(str(k.usd_borc)), Decimal("40.00"))
        with get_session() as s:
            s.get(CariIslem, iid).tarih = date(2026, 5, 4)
        k = _karsilik(iid)
        self.assertEqual(Decimal(str(k.usd_kur)), Decimal("40"))
        self.assertEqual(k.kur_tarihi, date(2026, 5, 4))
        self.assertEqual(Decimal(str(k.usd_borc)), Decimal("50.00"))

    def test_kayit_yeniden_acilinca_saklanan_kur_kullanilir_internete_cikilmaz(self):
        _kur(date(2026, 3, 2), "50")
        _islem(self.cari_id, date(2026, 3, 2), borc="1000")
        with get_session() as s:
            s.scalar(select(DovizKuru)).forex_selling = Decimal("70")
        self.ag_mock.reset_mock()
        r = usd.cari_usd_raporu(self.cari_id)
        self.assertFalse(self.ag_mock.called)
        self.assertEqual(r["satirlar"][0]["usd_kur"], Decimal("50"))
        self.assertEqual(r["satirlar"][0]["usd_borc"], Decimal("20.00"))

    def test_silinen_hareketin_karsiligi_silinir(self):
        _kur(date(2026, 3, 2), "50")
        iid = _islem(self.cari_id, date(2026, 3, 2), borc="1000")
        with get_session() as s:
            s.delete(s.get(CariIslem, iid))
        self.assertIsNone(_karsilik(iid))

    def test_toplu_guncellemede_uyusmaz_isaretlenir(self):
        _kur(date(2026, 3, 2), "50")
        iid = _islem(self.cari_id, date(2026, 3, 2), borc="1000")
        with get_session() as s:
            s.execute(CariIslem.__table__.update().where(CariIslem.id == iid).values(borc=Decimal("1500")))
        r = usd.cari_usd_raporu(self.cari_id)
        self.assertEqual(r["satirlar"][0]["durum"], "UYUSMAZ")
        self.assertFalse(r["tam"])
        o = usd.eksik_kur_onizleme(self.cari_id)
        usd.eksik_kurlari_uygula(o["satirlar"])
        k = _karsilik(iid)
        self.assertEqual(Decimal(str(k.usd_borc)), Decimal("30.00"))
        self.assertEqual(Decimal(str(k.usd_kur)), Decimal("50"))

    # —— tarih aralığı devri ——
    def test_tarih_araligi_devir_tl_ve_usd(self):
        _kur(date(2026, 1, 5), "40")
        _kur(date(2026, 2, 5), "50")
        _kur(date(2026, 3, 5), "25")
        _islem(self.cari_id, date(2026, 1, 5), borc="4000", belge="D-1", tur="Açılış")
        _islem(self.cari_id, date(2026, 2, 5), alacak="1000", belge="D-2")
        _islem(self.cari_id, date(2026, 3, 5), borc="500", belge="D-3")
        r = usd.cari_usd_raporu(self.cari_id, baslangic=date(2026, 3, 1), bitis=date(2026, 3, 31))
        self.assertEqual(r["devir"]["tl"], Decimal("3000.00"))
        self.assertEqual(r["devir"]["usd"], Decimal("80.00"))  # 100 − 20
        self.assertEqual(len(r["satirlar"]), 1)
        self.assertEqual(r["satirlar"][0]["usd_bakiye"], Decimal("100.00"))  # 80 + 20
        self.assertEqual(r["tl_bakiye"], Decimal("3500.00"))
        self.assertTrue(r["tam"])

    def test_devirde_eksik_kur_toplami_eksik_isaretler(self):
        _kur(date(2026, 3, 5), "25")
        _islem(self.cari_id, date(2025, 1, 5), borc="4000", belge="D-1")
        _islem(self.cari_id, date(2026, 3, 5), borc="500", belge="D-3")
        r = usd.cari_usd_raporu(self.cari_id, baslangic=date(2026, 3, 1))
        self.assertEqual(r["devir_eksik"], 1)
        self.assertFalse(r["tam"])

    # —— kapanmış TL fatura: tarihsel USD karşılık farkı ——
    def test_farkli_kurla_kapanan_tl_fatura_tl_sifir_usd_fark(self):
        _kur(date(2026, 6, 1), "40")
        _kur(date(2026, 6, 10), "50")
        with get_session() as s:
            s.add(SatisHareketi(cari_id=self.cari_id, satis_tarihi=date(2026, 6, 1), belge_no="SF-90001",
                                satis_tutari=Decimal("50000"), kalan_acik_tutar=Decimal("50000")))
        with get_session() as s:
            onceki_islem = s.scalar(select(func.count(CariIslem.id)))
        from database.finans_service import FinansService

        FinansService.kasa_tahsilat_makbuzu_kaydet({
            "tarih": date(2026, 6, 10), "cari_id": self.cari_id, "makbuz_no_otomatik": True,
            "satirlar": [{"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id,
                          "tutar": Decimal("50000")}],
        })
        r = usd.cari_usd_raporu(self.cari_id)
        self.assertEqual(r["tl_bakiye"], Decimal("0.00"))
        self.assertEqual(r["toplam"]["usd_borc"], Decimal("1250.00"))
        self.assertEqual(r["toplam"]["usd_alacak"], Decimal("1000.00"))
        self.assertEqual(r["usd_bakiye"], Decimal("250.00"))
        self.assertTrue(r["tam"])
        self.assertIn("Tarihsel USD karşılık farkı", r["fark_notu"])
        self.assertIn("Gerçek bir USD borç veya alacak değildir", r["fark_notu"])
        with get_session() as s:
            # Yalnız makbuzun kendi cari hareketi eklenir; kur farkı evrakı / borç / alacak yok
            self.assertEqual(s.scalar(select(func.count(CariIslem.id))), onceki_islem + 1)
            self.assertEqual(
                s.scalar(select(func.count(CariIslem.id)).where(CariIslem.belge_no.like("DVF-%"))), 0
            )
            sh = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == "SF-90001"))
            self.assertEqual(Decimal(str(sh.satis_tutari)), Decimal("50000.00"))
        from database.cari_bakiye_service import net_bakiye

        self.assertEqual(Decimal(str(net_bakiye(self.cari_id)["bakiye"])), Decimal("0.00"))


class SatisFaturasiUsdKarsilikTest(unittest.TestCase):
    """Onaylanan TL satış faturasının cari hareketi USD karşılığını alır (uzlaşmalı net)."""

    def setUp(self):
        from tests import test_uzlasma_net_cari as uz

        self.uz = uz
        uz._kurulum(self)

    def tearDown(self):
        self.uz._sokum(self)

    def test_onaylanan_fatura_net_tutarin_usd_karsiligi(self):
        _kur(date(2026, 5, 29), "40")  # Cuma; 01.06.2026 Pazartesi için kur yok → önceki yayın
        fid = self.uz._uzlasmali_fatura(self)
        from database.satis_faturasi_service import SatisFaturasiService

        no = SatisFaturasiService.getir(fid).fatura_no
        with get_session() as s:
            h = s.scalar(select(SatisHareketi).where(SatisHareketi.belge_no == no))
            hid = int(h.id)
        k = _karsilik(hid, usd.KAYNAK_HAREKET)
        self.assertEqual(k.durum, "TAMAM")
        self.assertEqual(Decimal(str(k.tl_borc)), Decimal("13000.00"))
        self.assertEqual(Decimal(str(k.usd_borc)), Decimal("325.00"))
        self.assertEqual(k.kur_tarihi, date(2026, 5, 29))
        self.assertEqual(k.islem_tarihi, date(2026, 6, 1))
        r = usd.cari_usd_raporu(self.musteri_id, baslangic=date(2026, 6, 1))
        satir = next(x for x in r["satirlar"] if x["belge_no"] == no)
        self.assertTrue(satir["onceki_gun_kuru"])


class SatisFaturasiTlEsasTest(unittest.TestCase):
    """Dövizli satış faturası satırları: birim fiyat, net, alt toplam tek esas (TL)."""

    def test_tl_esas_kayitta_ekrandaki_tl_fiyat_korunur(self):
        from database.satis_faturasi_service import SatisFaturasiService

        sonuc = SatisFaturasiService._satir_doviz_alanlari(
            {"miktar": "2", "birim_fiyat": "4000", "birim_fiyat_doviz": "90", "tl_esas": True},
            Decimal("40"), "USD",
        )
        self.assertEqual(sonuc["tl_birim_fiyat"], Decimal("4000"))
        self.assertEqual(sonuc["birim_fiyat_doviz"], Decimal("100.0000"))
        self.assertEqual(sonuc["tl_tutar"], Decimal("8000.00"))

    def test_eski_cagri_doviz_fiyattan_tl_uretir(self):
        from database.satis_faturasi_service import SatisFaturasiService

        sonuc = SatisFaturasiService._satir_doviz_alanlari(
            {"miktar": "1", "birim_fiyat": "0", "birim_fiyat_doviz": "100"}, Decimal("40"), "USD",
        )
        self.assertEqual(sonuc["tl_birim_fiyat"], Decimal("4000.0000"))

    def _kart(self, pb, kur, satirlar):
        import tkinter as tk

        from doviz_fatura_panel import doviz_satirlari_tl_cevir

        class _Var:
            def __init__(self, v):
                self.v = v

            def get(self):
                return self.v

        class _Kart:
            pass

        k = _Kart()
        k._doviz_para_birimi = _Var(pb)
        k._doviz_kur = _Var(kur)
        k.satirlar = satirlar
        return k, doviz_satirlari_tl_cevir

    def test_kur_degisince_doviz_fiyat_korunur_tl_yeniden_hesaplanir(self):
        satir = {"birim_satis_fiyati": Decimal("4000"), "birim_fiyat_doviz": Decimal("90"),
                 "satir_para_birimi": "USD", "para_birimi": "USD", "kur": "40"}
        kart, cevir = self._kart("USD", "50", [satir])
        cevir(kart)
        # Saklı (eski) döviz alanı değil, satırın TL fiyatı / satır kuru esas alınır: 4000/40 = 100 USD
        self.assertEqual(Decimal(str(satir["birim_satis_fiyati"])), Decimal("5000.0000"))
        self.assertEqual(Decimal(str(satir["birim_fiyat_doviz"])), Decimal("100.0000"))
        self.assertEqual(satir["satir_para_birimi"], "USD")
        self.assertEqual(satir["kur"], "50")

    def test_ayni_kurda_tl_fiyat_degismez(self):
        satir = {"birim_satis_fiyati": Decimal("4012.3456"), "satir_para_birimi": "USD",
                 "para_birimi": "USD", "kur": "40"}
        kart, cevir = self._kart("USD", "40", [satir])
        cevir(kart)
        self.assertEqual(Decimal(str(satir["birim_satis_fiyati"])), Decimal("4012.3456"))

    def test_hucre_yardimcilari_tl_esas(self):
        from fatura_satir_hucre_edit import _baslik_doviz_pb, _tl_fiyat

        self.assertEqual(_tl_fiyat("100", {"satir_para_birimi": "USD", "kur": "40"}), Decimal("4000.0000"))
        self.assertEqual(_tl_fiyat("100", {"satir_para_birimi": "TRY", "kur": "40"}), Decimal("100.0000"))

        class _V:
            def get(self):
                return "USD"

        class _D:
            _doviz_para_birimi = _V()

        self.assertEqual(_baslik_doviz_pb(_D()), "USD")


class CariUsdRaporArayuzTest(unittest.TestCase):
    def setUp(self):
        import tkinter as tk

        _servis_testi.TahsilatMakbuzuTest.setUp(self)
        self._ag = patch("database.doviz_service.DovizService._tcmb_xml_indir", side_effect=_internet_yok)
        self._ag.start()
        try:
            self.root = tk.Tk()
        except tk.TclError as hata:
            self._ag.stop()
            _servis_testi.TahsilatMakbuzuTest.tearDown(self)
            self.skipTest(f"Tk yok: {hata}")
        self.root.geometry("+20+20")
        self.root.attributes("-alpha", 0.0)

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass
        self._ag.stop()
        _servis_testi.TahsilatMakbuzuTest.tearDown(self)

    def test_cerceve_eksik_satiri_ve_devri_gosterir(self):
        from cari_usd_rapor_ui import CariUsdRaporCercevesi

        _kur(date(2026, 3, 5), "25")
        _islem(self.musteri_id, date(2026, 3, 5), borc="500", belge="R-1")
        c = CariUsdRaporCercevesi(self.root)
        c.pack()
        r = c.yukle(self.musteri_id, baslangic=date(2026, 3, 1))
        ogeler = c.tablo.get_children()
        self.assertEqual(c.tablo.item(ogeler[0], "values")[1], "DEVİR")
        self.assertIn("devir", c.tablo.item(ogeler[0], "tags"))
        self.assertFalse(r["tam"], "açılış (02.01.2026) kurunun yokluğu devri eksik yapar")
        self.assertIn("EKSİKTİR", c.uyari_etiketi.cget("text"))
        self.assertIn("(eksik)", c.tablo.item(ogeler[-1], "values")[11])

    def test_eksik_kur_dialogu_manuel_kurla_tamamlar(self):
        from cari_usd_rapor_ui import EksikKurDialog

        d = EksikKurDialog(self.root, self.musteri_id)
        self.assertEqual(len(d.onizleme["satirlar"]), 1)
        self.assertIn("yok", d.tablo.item("0", "tags"))
        d.manuel[date(2026, 1, 2)] = Decimal("25")
        with patch("cari_usd_rapor_ui.messagebox.askyesno", return_value=True), \
                patch("cari_usd_rapor_ui.messagebox.showinfo"):
            d.uygula()
        r = usd.cari_usd_raporu(self.musteri_id)
        self.assertTrue(r["tam"])
        self.assertEqual(r["usd_bakiye"], Decimal("40.00"))


if __name__ == "__main__":
    unittest.main()
