"""Stok işi kalanları — tanımsız birim engeli, sayım fazlası maliyeti (STK-010), stok uyarı sınıfları,
rapor ekranlarının arka plan yüklemesi (STK-013). Her test kendi geçici firma veritabanında çalışır.
"""

from __future__ import annotations

import sys
import time
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402

from database.database import get_session  # noqa: E402
from database.models.stok import Depo, StokBirim, StokHareketi, StokKarti, StokLotu  # noqa: E402
from database.stok_service import BIRIM_TANIMLAMA_YOLU, BirimDonusumHatasi  # noqa: E402
from tests.stok_test_ortami import StokOrtami  # noqa: E402

D = date
BUGUN = date.today()
T1, T2 = BUGUN - timedelta(days=5), BUGUN - timedelta(days=4)


class _Taban(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami(self._testMethodName[:20])
        with get_session() as s:
            self.stok_id = s.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == "U001"))
            self.ana = s.scalar(select(Depo.id).where(Depo.ad == "ANA DEPO"))

    def tearDown(self):
        self.o.kapat()

    def say(self, model) -> int:
        with get_session() as s:
            return int(s.scalar(select(func.count()).select_from(model)) or 0)


def _satir(birim="Paket", miktar=2, **ek):
    return {"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal(str(miktar)), "birim": birim,
            "birim_fiyat": Decimal("100"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20"), **ek}


class TanimsizBirimEngeliTest(_Taban):
    def assertBirimHatasi(self, ctx):
        mesaj = str(ctx.exception)
        self.assertIn("Paket", mesaj)
        self.assertIn("U001", mesaj)
        self.assertIn(BIRIM_TANIMLAMA_YOLU, mesaj)

    def test_satis_faturasi_taslak_kaydi_engellenir(self):
        from database.models.satis_faturasi import SatisFaturasi
        from database.satis_faturasi_service import SatisFaturasiService

        with self.assertRaises(BirimDonusumHatasi) as ctx:
            SatisFaturasiService.kaydet(
                {"fatura_tarihi": T1, "vade_tarihi": T1, "cari_id": self.o.mus_id, "depo": "ANA DEPO",
                 "odeme_tutari": Decimal("0"), "sales_person_id": 1}, [_satir()])
        self.assertBirimHatasi(ctx)
        self.assertIn("Satış faturası", str(ctx.exception))
        self.assertEqual(self.say(SatisFaturasi), 0)

    def test_tanimli_alternatif_birim_kaydedilir(self):
        from database.satis_faturasi_service import SatisFaturasiService

        f = SatisFaturasiService.kaydet(
            {"fatura_tarihi": T1, "vade_tarihi": T1, "cari_id": self.o.mus_id, "depo": "ANA DEPO",
             "odeme_tutari": Decimal("0"), "sales_person_id": 1}, [_satir("Koli", 1), _satir("adet", 3)])
        self.assertEqual(len(f.satirlar), 2)

    def test_alis_faturasi_mesaji_tanimlama_yolunu_gosterir(self):
        with self.assertRaises(BirimDonusumHatasi) as ctx:
            self.o.alis(2, 100, T1, birim="Paket")
        self.assertBirimHatasi(ctx)
        self.assertEqual(self.o.lot_toplam(), Decimal("0"))

    def test_satis_irsaliyesi_kaydi_engellenir(self):
        from database.models.satis_irsaliyesi import SatisIrsaliyesi
        from database.satis_irsaliyesi_service import SatisIrsaliyesiService

        with self.assertRaises(BirimDonusumHatasi) as ctx:
            SatisIrsaliyesiService.kaydet(
                {"irsaliye_tarihi": T1, "cari_id": self.o.mus_id, "depo": "ANA DEPO"}, [_satir()])
        self.assertBirimHatasi(ctx)
        self.assertEqual(self.say(SatisIrsaliyesi), 0)

    def test_satis_irsaliyesi_sevkinde_sonradan_silinen_birim_1_sayilmaz(self):
        from database.satis_irsaliyesi_service import SatisIrsaliyesiService

        self.o.alis(50, 100, T1, lot="L1")
        irs = SatisIrsaliyesiService.kaydet(
            {"irsaliye_tarihi": T2, "cari_id": self.o.mus_id, "depo": "ANA DEPO"}, [_satir("Koli", 1)])
        with get_session() as s:
            s.query(StokBirim).filter(StokBirim.birim_adi == "Koli").delete()
        with self.assertRaises(ValueError) as ctx:
            SatisIrsaliyesiService.sevk_et(irs.id)
        self.assertIsInstance(ctx.exception.__cause__, BirimDonusumHatasi)
        self.assertIn(BIRIM_TANIMLAMA_YOLU, str(ctx.exception))
        self.assertEqual(self.o.lot_toplam(), Decimal("50"))

    def test_alis_irsaliyesi_kaydi_engellenir(self):
        from database.alis_irsaliyesi_service import AlisIrsaliyesiService
        from database.models.alis_irsaliyesi import AlisIrsaliyesi

        with self.assertRaises(BirimDonusumHatasi) as ctx:
            AlisIrsaliyesiService.kaydet({"irsaliye_tarihi": T1, "cari_id": self.o.ted_id}, [_satir()])
        self.assertBirimHatasi(ctx)
        self.assertEqual(self.say(AlisIrsaliyesi), 0)

    def test_siparisten_faturaya_aktarim_engellenir_siparis_sayaci_degismez(self):
        from database.models.satis_siparisi import SatisSiparisiSatiri
        from database.satis_faturasi_service import SatisFaturasiService
        from database.satis_siparisi_service import SatisSiparisiService

        sp = SatisSiparisiService.kaydet(
            {"siparis_tarihi": T1, "termin_tarihi": BUGUN, "cari_id": self.o.mus_id, "onayla": True},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("4"), "birim": "Koli",
              "birim_satis_fiyati": Decimal("100"), "kdv_orani": Decimal("20")}], [])
        ssid = sp.satirlar[0].id
        with get_session() as s:
            s.query(StokBirim).filter(StokBirim.birim_adi == "Koli").delete()
        with self.assertRaises(BirimDonusumHatasi) as ctx:
            SatisFaturasiService.kaydet(
                {"fatura_tarihi": T2, "vade_tarihi": T2, "cari_id": self.o.mus_id, "depo": "ANA DEPO",
                 "odeme_tutari": Decimal("0"), "sales_person_id": 1, "siparis_id": sp.id},
                [_satir("Koli", 4, siparis_satiri_id=ssid)])
        self.assertIn("Koli", str(ctx.exception))
        self.assertIn(BIRIM_TANIMLAMA_YOLU, str(ctx.exception))
        with get_session() as s:
            self.assertEqual(Decimal(str(s.get(SatisSiparisiSatiri, ssid).faturalanan_miktar or 0)), Decimal("0"))

    def test_satis_iadesi_engellenir(self):
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        self.o.alis(10, 100, T1, lot="L1")
        f = self.o.satis(2, 200, T2)
        with self.assertRaises(BirimDonusumHatasi):
            SatisIadeFaturasiService.kaydet(
                {"iade_tarihi": BUGUN, "cari_id": self.o.mus_id, "depo": "ANA DEPO", "kaynak_fatura_id": f.id,
                 "iade_odeme_tutari": Decimal("0")},
                [{**_satir("Paket", 1), "kaynak_fatura_satiri_id": f.satirlar[0].id}])
        self.assertEqual(self.o.lot_toplam(), Decimal("8"))

    def test_alis_iadesi_engellenir(self):
        from database.alis_iade_faturasi_service import AlisIadeFaturasiService

        self.o.alis(10, 100, T1, lot="L1")
        with self.assertRaises(BirimDonusumHatasi):
            AlisIadeFaturasiService.kaydet(
                {"iade_tarihi": T2, "cari_id": self.o.ted_id, "depo": "ANA DEPO", "iade_odeme_tutari": Decimal("0")},
                [_satir("Paket", 1)])
        self.assertEqual(self.o.lot_toplam(), Decimal("10"))

    def test_toplu_mesaj_tum_satirlari_listeler(self):
        from database.stok_service import StokService

        with get_session() as s:
            with self.assertRaises(BirimDonusumHatasi) as ctx:
                StokService.belge_birimlerini_dogrula(
                    s, [_satir("Paket"), _satir("Koli"), _satir("Top"), {"urun_kodu": "YOK-KART", "birim": "X"}],
                    "Deneme")
        self.assertEqual(ctx.exception.urun_kodlari, ["U001"])
        mesaj = str(ctx.exception)
        self.assertIn("1. satır", mesaj)
        self.assertIn("3. satır", mesaj)
        self.assertNotIn("2. satır", mesaj)
        self.assertNotIn("YOK-KART", mesaj)

    def test_alis_siparisi_kaydi_engellenir(self):
        from database.alis_siparisi_service import AlisSiparisiService
        from database.models.alis_siparisi import AlisSiparisi

        with self.assertRaises(BirimDonusumHatasi) as ctx:
            AlisSiparisiService.kaydet(
                {"siparis_tarihi": T1, "termin_tarihi": BUGUN, "cari_id": self.o.ted_id},
                [{**_satir(), "birim_alis_fiyati": Decimal("100")}], [])
        self.assertBirimHatasi(ctx)
        self.assertIn("Alış siparişi", str(ctx.exception))
        self.assertEqual(self.say(AlisSiparisi), 0)

    def test_alis_siparisi_taslak_uyariyla_kaydedilir_kesinlestirme_engellenir(self):
        from database.alis_siparisi_service import AlisSiparisiService
        from database.models.alis_siparisi import AlisSiparisi

        sp = AlisSiparisiService.kaydet(
            {"siparis_tarihi": T1, "termin_tarihi": BUGUN, "cari_id": self.o.ted_id, "durum": "TASLAK"},
            [{**_satir(), "birim_alis_fiyati": Decimal("100")}], [])
        self.assertIn("onaylanamaz", sp.birim_uyarisi)
        self.assertIn(BIRIM_TANIMLAMA_YOLU, sp.birim_uyarisi)
        with self.assertRaises(BirimDonusumHatasi) as ctx:
            AlisSiparisiService.kesinlestir(sp.id)
        self.assertBirimHatasi(ctx)
        with get_session() as s:
            self.assertEqual(s.get(AlisSiparisi, sp.id).durum, "TASLAK")

    def test_satis_siparisi_taslak_uyarili_onay_engellenir_duzenlemede_eski_satir_engellenmez(self):
        from database.models.satis_siparisi import SatisSiparisi
        from database.satis_siparisi_service import SatisSiparisiService

        satir = {"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("4"), "birim": "Paket",
                 "birim_satis_fiyati": Decimal("100"), "kdv_orani": Decimal("20")}
        veriler = {"siparis_tarihi": T1, "termin_tarihi": BUGUN, "cari_id": self.o.mus_id}
        with self.assertRaises(BirimDonusumHatasi) as ctx:
            SatisSiparisiService.kaydet({**veriler, "onayla": True}, [satir], [])
        self.assertBirimHatasi(ctx)
        self.assertIn("Satış siparişi", str(ctx.exception))
        self.assertEqual(self.say(SatisSiparisi), 0)

        taslak = SatisSiparisiService.kaydet(veriler, [satir], [])
        self.assertEqual(taslak.durum, "TASLAK")
        self.assertIn("onaylanamaz", taslak.birim_uyarisi)
        with self.assertRaises(BirimDonusumHatasi):
            SatisSiparisiService.onayla(taslak.id)
        with self.assertRaises(BirimDonusumHatasi):
            SatisSiparisiService.kaydet({**veriler, "onayla": True}, [satir], [], taslak.id)
        with get_session() as s:
            self.assertEqual(s.get(SatisSiparisi, taslak.id).durum, "TASLAK")

        sp = SatisSiparisiService.kaydet({**veriler, "onayla": True}, [{**satir, "birim": "Koli"}], [])
        self.assertIsNone(sp.birim_uyarisi)
        with get_session() as s:
            s.query(StokBirim).filter(StokBirim.birim_adi == "Koli").delete()
        sp2 = SatisSiparisiService.kaydet({**veriler, "aciklama": "düzenleme"}, [{**satir, "birim": "Koli"}], [],
                                          sp.id)
        self.assertEqual(sp2.id, sp.id)
        with self.assertRaises(BirimDonusumHatasi):
            SatisSiparisiService.kaydet(veriler, [{**satir, "birim": "Koli"}, satir], [], sp.id)

    def _paket_tanimla(self):
        with get_session() as s:
            s.add(StokBirim(stok_id=self.stok_id, birim_adi="paket", carpan=Decimal("6")))

    def test_satis_teklifi_taslak_uyarili_onay_ve_kabul_engellenir(self):
        from database.models.satis_teklifi import SatisTeklifi
        from database.teklif_service import QuoteService

        veriler = {"teklif_tarihi": T1, "gecerlilik_tarihi": BUGUN, "cari_id": self.o.mus_id}
        satir = {**_satir(), "birim_satis_fiyati": Decimal("100"), "teklif_fiyati": Decimal("100")}
        hareket = self.say(StokHareketi)
        with self.assertRaises(BirimDonusumHatasi) as ctx:
            QuoteService.kaydet({**veriler, "durum": "KABUL EDİLDİ"}, [satir])
        self.assertBirimHatasi(ctx)
        self.assertEqual(self.say(SatisTeklifi), 0)

        t = QuoteService.kaydet(veriler, [satir])
        self.assertEqual(t.durum, "TASLAK")
        self.assertIn("Satış teklifi onaylanamaz", t.birim_uyarisi)
        self.assertIn(BIRIM_TANIMLAMA_YOLU, t.birim_uyarisi)
        for hedef in ("MÜŞTERİYE GÖNDERİLDİ", "KABUL EDİLDİ"):
            with self.assertRaises(BirimDonusumHatasi) as ctx:
                QuoteService.durum_degistir(t.id, hedef)
            self.assertBirimHatasi(ctx)
        with get_session() as s:
            self.assertEqual(s.get(SatisTeklifi, t.id).durum, "TASLAK")
        self.assertEqual(self.say(StokHareketi), hareket)

        self._paket_tanimla()
        t2 = QuoteService.kaydet(veriler, [satir], teklif_id=t.id)
        self.assertIsNone(t2.birim_uyarisi)
        self.assertEqual(QuoteService.durum_degistir(t.id, "MÜŞTERİYE GÖNDERİLDİ").durum, "MÜŞTERİYE GÖNDERİLDİ")

    def test_satis_teklifi_siparise_aktarimda_birim_kontrolu(self):
        from database.models.satis_siparisi import SatisSiparisi
        from database.models.satis_teklifi import SatisTeklifi
        from database.teklif_conversion_service import QuoteConversionService
        from database.teklif_service import QuoteService

        t = QuoteService.kaydet(
            {"teklif_tarihi": T1, "gecerlilik_tarihi": BUGUN, "cari_id": self.o.mus_id, "durum": "KABUL EDİLDİ"},
            [{**_satir("Koli", 1), "birim_satis_fiyati": Decimal("100"), "teklif_fiyati": Decimal("100")}])
        self.assertIsNone(t.birim_uyarisi)
        with get_session() as s:
            s.query(StokBirim).filter(StokBirim.birim_adi == "Koli").delete()
        with self.assertRaises(BirimDonusumHatasi) as ctx:
            QuoteConversionService.convert_to_sales_order(t.id, sadece_kabul_edilen=False)
        self.assertIn("siparişe aktarılamaz", str(ctx.exception))
        self.assertIn(BIRIM_TANIMLAMA_YOLU, str(ctx.exception))
        self.assertEqual(self.say(SatisSiparisi), 0)
        with get_session() as s:
            self.assertEqual(s.get(SatisTeklifi, t.id).durum, "KABUL EDİLDİ")

    def test_tedarikci_teklifi_taslak_uyarili_aktarim_engellenir(self):
        from database.models.alis_siparisi import AlisSiparisi
        from database.models.tedarikci_teklif import TedarikciTeklif
        from database.tedarikci_teklif_service import TedarikciTeklifService

        tid = TedarikciTeklifService.kaydet(
            {"teklif_tarihi": T1},
            [{**_satir(), "cari_id": self.o.ted_id, "birim_fiyat": Decimal("100"), "secildi": True},
             {**_satir("Koli", 1), "cari_id": self.o.ted_id, "birim_fiyat": Decimal("100"), "secildi": True}])
        uyari = TedarikciTeklifService.son_birim_uyarisi
        self.assertIn("1. satır", uyari)
        self.assertNotIn("2. satır", uyari)
        self.assertIn(BIRIM_TANIMLAMA_YOLU, uyari)
        with self.assertRaises(BirimDonusumHatasi) as ctx:
            TedarikciTeklifService.secilenleri_siparise_aktar(tid)
        self.assertBirimHatasi(ctx)
        self.assertEqual(self.say(AlisSiparisi), 0)
        with get_session() as s:
            self.assertEqual(s.get(TedarikciTeklif, tid).durum, "TASLAK")

    def test_satin_alma_talebi_taslak_uyarili_onay_ve_aktarim_engellenir(self):
        from database.models.satin_alma_talep import SatinAlmaTalep
        from database.satin_alma_talep_service import SatinAlmaTalepService as S

        veriler = {"talep_tarihi": BUGUN, "ihtiyac_tarihi": BUGUN + timedelta(days=5), "depo": "ANA DEPO",
                   "oncelik": "NORMAL"}
        hareket = self.say(StokHareketi)
        tid = S.kaydet(veriler, [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "birim": "Paket", "miktar": "10"}])
        self.assertIn("Satın alma talebi onaylanamaz", S.son_birim_uyarisi)
        self.assertIn("Satın alma talebi", S.birim_uyarisi(tid))
        with self.assertRaises(BirimDonusumHatasi) as ctx:
            S.onaya_gonder(tid)
        self.assertBirimHatasi(ctx)
        with get_session() as s:
            self.assertEqual(s.get(SatinAlmaTalep, tid).durum, "TASLAK")
        self.assertEqual(self.say(StokHareketi), hareket)

        self._paket_tanimla()
        self.assertIsNone(S.birim_uyarisi(tid))
        S.onaya_gonder(tid)
        with get_session() as s:
            s.query(StokBirim).filter(StokBirim.birim_adi == "paket").delete()
        with self.assertRaises(BirimDonusumHatasi):
            S.onayla(tid)

        tid2 = S.kaydet(veriler, [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "birim": "Koli", "miktar": "2"}])
        self.assertIsNone(S.son_birim_uyarisi)
        S.onaya_gonder(tid2)
        S.onayla(tid2)
        with get_session() as s:
            ssid = s.get(SatinAlmaTalep, tid2).satirlar[0].id
            s.query(StokBirim).filter(StokBirim.birim_adi == "Koli").delete()
        with self.assertRaises(BirimDonusumHatasi) as ctx:
            S.siparis_satirlari_hazirla({ssid: Decimal("2")})
        self.assertIn("siparişe aktarılamaz", str(ctx.exception))

    def test_hizli_satis_engellenir(self):
        from database.hizli_satis_service import HizliSatisService
        from database.models.satis_faturasi import SatisFaturasi
        from hizli_satis_sepet import HizliSatisSepet

        self.o.alis(10, 100, T1, lot="L1")
        oncesi = self.say(SatisFaturasi)
        sepet = HizliSatisSepet()
        sepet.ekle(stok_id=self.stok_id, stok_kodu="U001", stok_adi="Test Ürün", miktar="1", birim="Paket",
                   birim_fiyat="100", kdv_orani=20)
        with self.assertRaises(BirimDonusumHatasi) as ctx:
            HizliSatisService.satisi_tamamla(sepet=sepet, cari_id=self.o.mus_id, tahsilatlar=[],
                                             idempotency_token=HizliSatisService.yeni_idempotency_token())
        self.assertBirimHatasi(ctx)
        self.assertIn("Hızlı satış", str(ctx.exception))
        self.assertEqual(self.say(SatisFaturasi), oncesi)
        self.assertEqual(self.o.lot_toplam(), Decimal("10"))


class BirimHatasiPenceresiTest(_Taban):
    """Mesaj kutusundaki 'Stok Kartını Aç' seçeneği kartı «Barkod & Birimler» sekmesinde açar."""

    def setUp(self):
        super().setUp()
        import tkinter as tk

        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk yok: {exc}")
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        finally:
            super().tearDown()

    def _hata(self):
        from database.stok_service import StokService

        with get_session() as s:
            try:
                StokService.belge_birimlerini_dogrula(s, [_satir()], "Deneme")
            except BirimDonusumHatasi as hata:
                try:
                    raise ValueError(str(hata)) from hata
                except ValueError as sarili:
                    return sarili
        self.fail("hata beklenirdi")

    def test_evet_karti_birimler_sekmesinde_acar(self):
        from unittest.mock import patch

        import birim_hatasi_ui as B
        from stok_ui import StokKartiDialog

        acilan = []
        orijinal = StokKartiDialog.__init__

        def _init(dlg, *a, **k):
            orijinal(dlg, *a, **k)
            acilan.append(dlg)

        with patch.object(B.messagebox, "askyesno", return_value=True) as soru, \
                patch.object(StokKartiDialog, "__init__", _init), \
                patch.object(StokKartiDialog, "_pencere_boyutunu_ayarla", lambda self: None):
            self.assertTrue(B.birim_hatasi_goster(self.root, self._hata()))
        self.assertIn("Barkod & Birimler", soru.call_args.args[1])
        self.assertEqual(len(acilan), 1)
        dlg = acilan[0]
        self.assertEqual(dlg.stok.stok_kodu, "U001")
        self.assertIn("Birimler", dlg.sekmeler.tab(dlg.sekmeler.select(), "text"))
        dlg.destroy()

    def test_hayir_kart_acmaz_birim_disi_hata_false(self):
        from unittest.mock import patch

        import birim_hatasi_ui as B

        with patch.object(B.messagebox, "askyesno", return_value=False), \
                patch.object(B, "stok_karti_birimler_ac") as ac:
            self.assertTrue(B.birim_hatasi_goster(self.root, self._hata()))
        ac.assert_not_called()
        self.assertFalse(B.birim_hatasi_goster(self.root, ValueError("başka hata")))


class SayimFazlasiMaliyetTest(_Taban):
    def _sayim(self, sayilan, sistem=None, **ek):
        from database.stok_sayim_service import StokSayimService

        sistem = self.o.lot_toplam() if sistem is None else sistem
        return StokSayimService.kaydet_ve_onayla(self.ana, BUGUN, [
            {"stok_id": self.stok_id, "sistem_miktar": sistem, "sayilan_miktar": Decimal(str(sayilan)), **ek}])

    def _sayim_kaydi(self):
        from database.models.stok_sayim import StokSayimSatiri

        with get_session() as s:
            satir = s.scalar(select(StokSayimSatiri).order_by(StokSayimSatiri.id.desc()))
            lot = s.scalar(select(StokLotu).where(StokLotu.tedarikci == "SAYIM").order_by(StokLotu.id.desc()))
            har = s.scalar(select(StokHareketi).where(StokHareketi.hareket_turu == "SAYIM GİRİŞ"))
            return satir, lot, har

    def test_fifo_son_lot_maliyeti_onerilir_ve_kaynagi_kaydedilir(self):
        from database.stok_sayim_service import MALIYET_FIFO_SON_LOT, StokSayimService

        self.o.alis(10, 100, T1, lot="L1")
        self.o.alis(5, 120, T2, lot="L2")
        oneri = StokSayimService.maliyet_onerisi(self.stok_id, self.ana)
        self.assertEqual((oneri["birim_maliyet"], oneri["kaynak"]), (Decimal("120"), MALIYET_FIFO_SON_LOT))
        self._sayim(17)
        satir, lot, har = self._sayim_kaydi()
        self.assertEqual(Decimal(str(lot.birim_maliyet)), Decimal("120"))
        self.assertEqual(Decimal(str(har.birim_maliyet)), Decimal("120"))
        self.assertEqual(satir.maliyet_kaynagi, MALIYET_FIFO_SON_LOT)
        self.assertEqual(self.o.lot_deger(), Decimal("1000") + Decimal("600") + Decimal("240"))

    def test_son_gecerli_alis_yedek_kaynak(self):
        from database.stok_sayim_service import MALIYET_SON_ALIS, StokSayimService

        self.o.alis(10, 100, T1, lot="L1")
        with get_session() as s:
            for l in s.scalars(select(StokLotu)).all():
                l.birim_maliyet = Decimal("0")
        oneri = StokSayimService.maliyet_onerisi(self.stok_id, self.ana)
        self.assertEqual((oneri["birim_maliyet"], oneri["kaynak"]), (Decimal("100"), MALIYET_SON_ALIS))

    def test_maliyet_yoksa_kullanici_girisi_zorunlu_sifir_reddedilir(self):
        from database.stok_sayim_service import MALIYET_KULLANICI, StokSayimService

        self.assertIsNone(StokSayimService.maliyet_onerisi(self.stok_id, self.ana))
        with self.assertRaisesRegex(ValueError, "maliyet bulunamadı"):
            self._sayim(3, Decimal("0"))
        with self.assertRaisesRegex(ValueError, "0 maliyetle"):
            self._sayim(3, Decimal("0"), birim_maliyet="0")
        self.assertEqual(self.o.lot_toplam(), Decimal("0"))
        self.assertEqual(self.o.hareket_sayisi("SAYIM GİRİŞ"), 0)
        self._sayim(3, Decimal("0"), birim_maliyet="45,5", maliyet_kaynagi="FIFO son lot")
        satir, lot, _har = self._sayim_kaydi()
        self.assertEqual(Decimal(str(lot.birim_maliyet)), Decimal("45.5"))
        self.assertEqual(satir.maliyet_kaynagi, MALIYET_KULLANICI)

    def test_oneriden_farkli_maliyet_kullanici_kaynakli_sayilir(self):
        from database.stok_sayim_service import MALIYET_KULLANICI

        self.o.alis(10, 100, T1, lot="L1")
        self._sayim(12, birim_maliyet="90", maliyet_kaynagi="FIFO son lot")
        satir, lot, _har = self._sayim_kaydi()
        self.assertEqual((Decimal(str(lot.birim_maliyet)), satir.maliyet_kaynagi), (Decimal("90"), MALIYET_KULLANICI))

    def test_sayim_eksigi_maliyet_istemez(self):
        self.o.alis(10, 100, T1, lot="L1")
        self._sayim(7)
        self.assertEqual(self.o.lot_toplam(), Decimal("7"))
        satir, _lot, _har = self._sayim_kaydi()
        self.assertIsNone(satir.birim_maliyet)

    def test_eski_semaya_kolonlar_eklenir(self):
        from sqlalchemy import inspect, text

        from database.database import company_db
        from database.stok_sayim_service import StokSayimService

        with company_db.engine.begin() as b:
            b.execute(text("DROP TABLE stok_sayim_satirlari"))
            b.execute(text("CREATE TABLE stok_sayim_satirlari (id INTEGER PRIMARY KEY, fis_id INTEGER NOT NULL, "
                           "stok_id INTEGER NOT NULL, sistem_miktar NUMERIC, sayilan_miktar NUMERIC, fark NUMERIC, "
                           "fark_nedeni VARCHAR(200))"))
        StokSayimService.schema_hazirla()
        kolonlar = {c["name"] for c in inspect(company_db.engine).get_columns("stok_sayim_satirlari")}
        self.assertTrue({"birim_maliyet", "maliyet_kaynagi"} <= kolonlar)


class StokUyariSiniflandirmaTest(_Taban):
    def aktif(self, stok_id):
        from database.models.stok_uyari import StokIhtiyac

        with get_session() as s:
            return list(s.scalars(select(StokIhtiyac).where(
                StokIhtiyac.aktif.is_(True), StokIhtiyac.stok_id == stok_id)).all())

    def test_hic_giris_olmayan_kart_stok_girisi_yok(self):
        from database.stok_uyari_service import NEDEN_GIRIS_YOK, StokUyariService

        yeni = self.o.urun_ekle("Y001", "Hiç Girmemiş")
        StokUyariService.toplu_degerlendir()
        self.assertEqual([k.nedenler for k in self.aktif(yeni)], [NEDEN_GIRIS_YOK])
        sayi = StokUyariService.aktif_sayisi()
        self.assertEqual(sayi["tukenen"], 0)
        self.assertGreaterEqual(sayi["giris_yok"], 1)
        self.assertEqual(sayi["rozet"], sayi["toplam"] - sayi["giris_yok"])
        satirlar = StokUyariService.listele({"neden": NEDEN_GIRIS_YOK})["satirlar"]
        self.assertIn("Y001", [s["stok_kodu"] for s in satirlar])
        y = next(s for s in satirlar if s["stok_kodu"] == "Y001")
        self.assertEqual((y["oncelik"], y["oncelik_neden"], y["neden_metni"]), (5, "Stok girişi yok", "Stok girişi yok"))
        self.assertNotIn("Y001", [s["stok_kodu"] for s in StokUyariService.listele({"neden": "TUKENDI"})["satirlar"]])

    def test_stok_bulunup_sifira_dusen_tukendi(self):
        from database.stok_uyari_service import NEDEN_TUKENDI

        self.o.alis(2, 100, T1, lot="L1")
        self.o.satis(2, 150, T2)
        self.assertEqual([k.nedenler for k in self.aktif(self.stok_id)], [NEDEN_TUKENDI])

    def test_minimumlu_kartta_siparis_ihtiyaci_kritik_ayrica(self):
        from database.stok_uyari_service import NEDEN_GIRIS_YOK, NEDEN_KRITIK, NEDEN_TUKENDI, StokUyariService

        hic = self.o.urun_ekle("M001", "Minimumlu Yeni", minimum_stok=Decimal("5"))
        StokUyariService.toplu_degerlendir()
        self.assertEqual([k.nedenler for k in self.aktif(hic)], [f"{NEDEN_GIRIS_YOK},{NEDEN_KRITIK}"])
        m = next(s for s in StokUyariService.listele({"neden": NEDEN_KRITIK})["satirlar"] if s["stok_kodu"] == "M001")
        self.assertEqual(m["oncelik_neden"], "Kritik seviye")
        with get_session() as s:
            s.get(StokKarti, self.stok_id).minimum_stok = Decimal("3")
        self.o.alis(2, 100, T1, lot="L1")
        self.o.satis(2, 150, T2)
        self.assertEqual([k.nedenler for k in self.aktif(self.stok_id)], [f"{NEDEN_TUKENDI},{NEDEN_KRITIK}"])

    def test_eski_siniflandirma_gecmisi_bozmadan_yenilenir_bildirim_yok(self):
        from database.models.stok_uyari import StokIhtiyac, StokIhtiyacGecmisi
        from database.stok_uyari_service import NEDEN_GIRIS_YOK, NEDEN_TUKENDI, StokUyariService

        yeni = self.o.urun_ekle("E001", "Eski Sınıflı")
        StokUyariService.toplu_degerlendir()
        with get_session() as s:
            s.info["_stok_uyari_calisiyor"] = True
            k = s.scalar(select(StokIhtiyac).where(StokIhtiyac.stok_id == yeni, StokIhtiyac.aktif.is_(True)))
            k.nedenler, k.goruldu = NEDEN_TUKENDI, True
            kayit_id = k.id
            StokUyariService._genel_yaz(s, "siniflandirma_surumu", "1")
        with get_session() as s:
            eski_gecmis = [(g.id, g.islem, g.detay) for g in s.scalars(
                select(StokIhtiyacGecmisi).where(StokIhtiyacGecmisi.ihtiyac_id == kayit_id)).all()]
        self.assertTrue(StokUyariService.ilk_tarama_gerekli())
        StokUyariService.olaylari_al()
        StokUyariService.toplu_degerlendir(ilk_tarama=True)
        with get_session() as s:
            k = s.get(StokIhtiyac, kayit_id)
            self.assertEqual((k.nedenler, k.goruldu, k.aktif), (NEDEN_GIRIS_YOK, True, True))
            gecmis = [(g.id, g.islem, g.detay) for g in s.scalars(
                select(StokIhtiyacGecmisi).where(StokIhtiyacGecmisi.ihtiyac_id == kayit_id)
                .order_by(StokIhtiyacGecmisi.id)).all()]
        self.assertEqual(gecmis[:len(eski_gecmis)], eski_gecmis)
        self.assertEqual(gecmis[-1][1], "YENİDEN SINIFLANDIRILDI")
        self.assertEqual(StokUyariService.olaylari_al(), [])
        self.assertFalse(StokUyariService.ilk_tarama_gerekli())

    def test_yeni_kart_stok_girisi_yok_bildirimi_uretmez(self):
        from database.stok_uyari_service import StokUyariService

        StokUyariService.olaylari_al()
        self.o.urun_ekle("B002", "Bildirimsiz")
        self.assertEqual([o for o in StokUyariService.olaylari_al() if o.get("stok_kodu") == "B002"], [])


class RaporArkaPlanTest(unittest.TestCase):
    """STK-013: ağır rapor sorgusu ana thread'i bloklamaz; sonuç after() ile ana thread'de yazılır."""

    def setUp(self):
        import tkinter as tk

        try:
            self.root = tk.Tk()
        except tk.TclError as hata:  # pragma: no cover - ekransız ortam
            self.skipTest(f"Tk yok: {hata}")
        self.root.withdraw()

    def tearDown(self):
        self.root.destroy()

    def _bekle(self, kosul, sure=10.0):
        bitis = time.perf_counter() + sure
        while not kosul() and time.perf_counter() < bitis:
            self.root.update()
            time.sleep(0.005)

    def test_yukleniyor_gostergesi_thread_ve_parcali_doldurma(self):
        import threading
        from tkinter import ttk

        from stok_rapor_ui import arka_plan_rapor, tabloyu_parcali_doldur

        ozet = ttk.Label(self.root)
        buton = ttk.Button(self.root)
        tablo = ttk.Treeview(self.root, columns=("a", "b"), show="headings")
        ana = threading.get_ident()
        durum: dict = {}

        def yukle():
            durum["is_thread"] = threading.get_ident()
            time.sleep(0.4)
            return {"satirlar": [{"a": i, "b": i * 2} for i in range(1500)]}

        def goster(r):
            durum["goster_thread"] = threading.get_ident()
            tabloyu_parcali_doldur(tablo, r["satirlar"], lambda s: (s["a"], s["b"]), parca=200,
                                   bitti=lambda: durum.update(bitti=True))

        t0 = time.perf_counter()
        arka_plan_rapor(self.root, ozet, buton, yukle, goster, "Test")
        self.assertLess(time.perf_counter() - t0, 0.2)
        self.assertTrue(ozet.cget("text").startswith("Yükleniyor"))
        self.assertIn("disabled", buton.state())
        self._bekle(lambda: durum.get("bitti"))
        self.assertNotEqual(durum["is_thread"], ana)
        self.assertEqual(durum["goster_thread"], ana)
        self.assertEqual(len(tablo.get_children()), 1500)
        self.assertNotIn("disabled", buton.state())

    def test_eski_istek_sonucu_yeni_istegi_ezmez_hata_mesaji(self):
        from tkinter import ttk
        from unittest.mock import patch

        from stok_rapor_ui import arka_plan_rapor

        ozet = ttk.Label(self.root)
        buton = ttk.Button(self.root)
        gelen: list = []
        arka_plan_rapor(self.root, ozet, buton, lambda: (time.sleep(0.3), "eski")[1], gelen.append, "T")
        arka_plan_rapor(self.root, ozet, buton, lambda: "yeni", gelen.append, "T")
        self._bekle(lambda: False, 0.6)
        self.assertEqual(gelen, ["yeni"])
        with patch("stok_rapor_ui.messagebox.showerror") as hata:
            arka_plan_rapor(self.root, ozet, buton, lambda: 1 / 0, gelen.append, "T")
            self._bekle(lambda: hata.called, 2)
        self.assertTrue(hata.called)
        self.assertEqual(ozet.cget("text"), "Rapor alınamadı.")


if __name__ == "__main__":
    unittest.main()
