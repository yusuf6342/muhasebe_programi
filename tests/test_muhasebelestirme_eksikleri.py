"""Muhasebeleştirme eksikleri: yedekli geçiş, öneri, finans evrakları, geçmiş önizleme, tahsilat iptali.

Her test yalıtılmış geçici veritabanında çalışır (gerçek firma verisine dokunulmaz).
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sqlalchemy import delete, func, select, update  # noqa: E402

import database.models.sube  # noqa: E402,F401
import test_masraf_dagitim as tmd  # noqa: E402
import test_masraf_dagitim_baglanti as tmb  # noqa: E402
import test_muhasebelestirme_ayarlari as tma  # noqa: E402
from database import gecis_guvenligi as gg  # noqa: E402
from database.database import get_session  # noqa: E402

TARIH = date(2026, 6, 5)


# ====================================================================== yedekli geçiş (dosya düzeyi)
class GecisGuvenligiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "firma.db"
        c = sqlite3.connect(self.db)
        c.execute("create table cari (id integer primary key, ad text unique)")
        c.executemany("insert into cari(ad) values (?)", [("A",), ("B",), ("C",)])
        c.commit()
        c.close()

    def tearDown(self):
        gg.onayi_dus(self.db)
        self._tmp.cleanup()

    def _sema_ve_sayilar(self):
        c = sqlite3.connect(self.db)
        try:
            sema = sorted(r[0] for r in c.execute("select sql from sqlite_master where sql is not null"))
        finally:
            c.close()
        return sema, gg.tablo_sayilari(self.db)

    def _gecis(self, hata=False):
        def adimlar():
            c = sqlite3.connect(self.db)
            try:
                kolonlar = {r[1] for r in c.execute("pragma table_info(cari)")}
                if "kod" not in kolonlar:
                    c.execute("alter table cari add column kod text")
                c.execute("create table if not exists ayar (anahtar text primary key, deger text)")
                c.execute("insert or ignore into ayar values ('surum', '2')")
                c.commit()
                if hata:
                    raise RuntimeError("adım 2 bozuk")
            finally:
                c.close()
            return "tamam"

        return gg.guvenli_gecis(self.db, adimlar, gerekli=True, etiket="deneme")

    def test_disk_yazma_hatasinda_gecis_baslamaz(self):
        once = self._sema_ve_sayilar()
        with patch.object(gg, "_yedek_dosyasi_al", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(gg.GecisYedekHatasi) as ctx:
                self._gecis()
        self.assertIn("yedek dosyası yazılamadı", str(ctx.exception))
        self.assertIn("tekrar deneyin", str(ctx.exception))
        self.assertEqual(self._sema_ve_sayilar(), once)
        self.assertEqual(list((self.db.parent / "yedekler").iterdir()), [])
        self.assertIsNone(gg.yedek_onayi(self.db))

    def test_dogrulama_hatasinda_gecis_baslamaz_yedek_gecersiz_isaretlenir(self):
        once = self._sema_ve_sayilar()
        with patch.object(gg, "_dogrula", return_value=("tablo satır sayıları kaynakla eşleşmiyor (cari)", {})):
            with self.assertRaises(gg.GecisYedekHatasi) as ctx:
                self._gecis()
        self.assertIn("doğrulanamadı", str(ctx.exception))
        self.assertEqual(self._sema_ve_sayilar(), once)
        klasorler = list((self.db.parent / "yedekler").iterdir())
        self.assertEqual(len(klasorler), 1)
        self.assertTrue(klasorler[0].name.endswith("_GECERSIZ"))
        self.assertIn("GEÇERSİZ", (klasorler[0] / "DOGRULAMA.txt").read_text(encoding="utf-8"))
        self.assertIsNone(gg.yedek_onayi(self.db))

    def test_gecis_ortasinda_hata_geri_yuklenir_tekrar_denemede_cift_kayit_yok(self):
        once = self._sema_ve_sayilar()
        with self.assertRaises(gg.GecisHatasi) as ctx:
            self._gecis(hata=True)
        self.assertTrue(ctx.exception.geri_yuklendi)
        self.assertEqual(self._sema_ve_sayilar(), once, "yarım geçiş kalmamalı")
        sonuc, yedek = self._gecis()
        self.assertEqual(sonuc, "tamam")
        self.assertTrue(yedek.yol.is_file())
        self.assertIn("doğrulandı", (yedek.yol.parent / "DOGRULAMA.txt").read_text(encoding="utf-8"))
        self._gecis()
        sayilar = gg.tablo_sayilari(self.db)
        self.assertEqual((sayilar["cari"], sayilar["ayar"]), (3, 1))

    def test_eski_baska_db_veya_silinmis_yedek_onay_sayilmaz(self):
        yedek = gg.dogrulanmis_yedek(self.db, "deneme")
        self.assertIsNotNone(gg.yedek_onayi(self.db))
        baska = Path(self._tmp.name) / "baska.db"
        sqlite3.connect(baska).close()
        self.assertIsNone(gg.yedek_onayi(baska))
        with patch.object(gg, "ONAY_SURESI_SN", -1):
            self.assertIsNone(gg.yedek_onayi(self.db), "süresi geçmiş yedek")
        gg.dogrulanmis_yedek(self.db, "deneme")
        y2 = gg.yedek_onayi(self.db)
        y2.yol.unlink()
        self.assertIsNone(gg.yedek_onayi(self.db), "dosyası silinmiş yedek")
        self.assertTrue(yedek.yol.is_file())

    def test_yeni_bos_veritabani_yedeksiz_olusur(self):
        bos = Path(self._tmp.name) / "yeni" / "firma.db"
        bos.parent.mkdir()
        sqlite3.connect(bos).close()
        sonuc, yedek = gg.guvenli_gecis(bos, lambda: "olustu", gerekli=True)
        self.assertEqual((sonuc, yedek), ("olustu", None))
        self.assertFalse((bos.parent / "yedekler").exists())


# ====================================================================== servis düzeyi
class MuhasebelestirmeEksikleriTest(unittest.TestCase):
    setUp = tma.MuhasebelestirmeAyarlariTest.setUp
    tearDown = tma.MuhasebelestirmeAyarlariTest.tearDown
    _servis = staticmethod(tma.MuhasebelestirmeAyarlariTest._servis)
    _ayar = tma.MuhasebelestirmeAyarlariTest._ayar
    _fis_sayisi = tma.MuhasebelestirmeAyarlariTest._fis_sayisi
    _durum = tma.MuhasebelestirmeAyarlariTest._durum
    _durum_id = tma.MuhasebelestirmeAyarlariTest._durum_id
    _bakiyeler = tma.MuhasebelestirmeAyarlariTest._bakiyeler
    _tutarli = tma.MuhasebelestirmeAyarlariTest._tutarli
    _alis = tmd.MasrafDagitimTest._alis
    _sat = tmd.MasrafDagitimTest._sat
    _gm_kur = tmd.MasrafDagitimTest._gm_kur
    _kasa = tmb.MasrafBaglantiTest._kasa

    # ------------------------------------------------------------ yardımcılar
    def _banka(self, ad="Ziraat Mevduat", alt="MEVDUAT") -> int:
        from database.models.finans import FinansHesabi

        with get_session() as s:
            h = s.scalar(select(FinansHesabi).where(FinansHesabi.hesap_adi == ad))
            if h is None:
                h = FinansHesabi(hesap_adi=ad, hesap_turu="BANKA", alt_hesap_turu=alt,
                                 acilis_bakiyesi=Decimal("50000"), aktif=True)
                s.add(h)
                s.flush()
            return int(h.id)

    def _durum_kaydi(self, evrak, kaynak_id):
        from database.models.genel_muhasebe import MuhasebeBelgeDurumu

        with get_session() as s:
            return s.scalar(select(MuhasebeBelgeDurumu).where(
                MuhasebeBelgeDurumu.evrak_turu == evrak, MuhasebeBelgeDurumu.kaynak_id == int(kaynak_id)))

    def _kimlik(self, evrak, belge_no) -> int:
        from database.models.finans import FinansEvrakKimligi

        with get_session() as s:
            return int(s.scalar(select(FinansEvrakKimligi.id).where(
                FinansEvrakKimligi.evrak_turu == evrak, FinansEvrakKimligi.belge_no == belge_no)))

    def _hareket_sayisi(self, belge_no) -> int:
        from database.models.finans import FinansHareketi

        with get_session() as s:
            return int(s.scalar(select(func.count()).select_from(FinansHareketi)
                                .where(FinansHareketi.belge_no == belge_no)))

    # Her yeni tür: (oluştur → (evrak_turu, kaynak_id, belge_no), beklenen hesap bakiyeleri)
    def _evrak_olustur(self, tur):
        from database.cari_service import CariService
        from database.cari_virman_makbuz_service import CariVirmanMakbuzService
        from database.finans_service import FinansService

        kasa = self._kasa()
        if tur == "kasa_makbuzu":
            m = FinansService.kasa_tahsilat_makbuzu_kaydet({
                "tarih": TARIH, "cari_id": self.musteri_id, "makbuz_no_otomatik": True,
                "satirlar": [{"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": kasa, "tutar": "300"}]})
            return "kasa_makbuzu", int(m.id), m.belge_no, {"100.01.0001": Decimal("300"),
                                                          "120.01.0001": Decimal("-300")}
        if tur == "kasa_banka_virman":
            no = FinansService.kasadan_bankaya_yatan(kasa, self._banka(), TARIH, Decimal("1000"))
            return tur, self._kimlik(tur, no), no, {"102.01.0001": Decimal("1000"),
                                                     "100.01.0001": Decimal("-1000")}
        if tur == "banka_havale":
            no = FinansService.alinan_havale(self._banka(), TARIH, Decimal("500"), cari_id=self.musteri_id)
            return tur, self._kimlik(tur, no), no, {"102.01.0001": Decimal("500"),
                                                     "120.01.0001": Decimal("-500")}
        if tur == "cari_virman":
            k, _h = CariService.virman_yap(self.musteri_id, self.tedarikci_id, TARIH, Decimal("200"))
            return tur, self._kimlik(tur, k.belge_no), k.belge_no, {"120.01.0001": Decimal("-200"),
                                                                     "320.01.0001": Decimal("200")}
        if tur == "cari_virman_makbuzu":
            k = CariVirmanMakbuzService.kaydet({"tarih": TARIH, "musteri_id": self.musteri_id,
                                                "tedarikci_id": self.tedarikci_id, "tutar": "400",
                                                "makbuz_no_otomatik": True})
            return tur, int(k.id), k.belge_no, {"320.01.0001": Decimal("400"), "120.01.0001": Decimal("-400")}
        if tur == "cari_odeme":
            i = CariService.odeme_yap(self.tedarikci_id, TARIH, Decimal("700"), "Nakit", "Merkez Kasa")
            return tur, self._kimlik(tur, i.belge_no), i.belge_no, {"320.01.0001": Decimal("700"),
                                                                     "100.01.0001": Decimal("-700")}
        if tur == "cari_tahsilat":
            i = CariService.tahsilat_yap(self.musteri_id, TARIH, Decimal("600"), "Nakit", "Merkez Kasa")
            return tur, self._kimlik(tur, i.belge_no), i.belge_no, {"100.01.0001": Decimal("600"),
                                                                     "120.01.0001": Decimal("-600")}
        raise AssertionError(tur)

    YENI_TURLER = ("kasa_makbuzu", "kasa_banka_virman", "banka_havale", "cari_virman", "cari_virman_makbuzu",
                   "cari_odeme", "cari_tahsilat")

    def _temizle(self):
        """Alt testler arasında muhasebe tarafını sıfırlar (ön muhasebe evrakı kalır, bakiye farkı ölçülür)."""
        from database.models.genel_muhasebe import (
            HesapPlani,
            MuhasebeBelgeDurumu,
            MuhasebeFisi,
            MuhasebeFisiSatiri,
            MuhasebeIslemGecmisi,
        )

        with get_session() as s:
            for model in (MuhasebeFisiSatiri, MuhasebeIslemGecmisi, MuhasebeBelgeDurumu):
                s.execute(delete(model))
            s.execute(update(MuhasebeFisi).values(ters_fis_id=None))
            s.execute(delete(MuhasebeFisi))
            for h in s.scalars(select(HesapPlani)):
                h.borc_toplam = 0
                h.alacak_toplam = 0

    # ------------------------------------------------------------ 1) geçiş yedeği (uygulama servisi)
    def test_muhasebelestirme_gecisi_yedeksiz_calismaz_ara_hata_geri_yuklenir(self):
        from database.models.genel_muhasebe import MuhasebeBelgeDurumu, MuhasebelestirmeAyari

        servis = self._servis()
        self._alis("U001", "100", "100", "LOT-A")
        with get_session() as s:  # özellik öncesi veritabanı: ayar ve durum kaydı yok, fiş var
            s.execute(delete(MuhasebeBelgeDurumu))
            s.execute(delete(MuhasebelestirmeAyari))
        servis._hazir_motorlar.clear()

        def sayilar():
            with get_session() as s:
                return (s.scalar(select(func.count()).select_from(MuhasebelestirmeAyari)),
                        s.scalar(select(func.count()).select_from(MuhasebeBelgeDurumu)))

        # Sıcak yol (evrak kaydı / ekran) yedeksiz geçiş yapmaz
        with self.assertRaises(gg.GecisYedekHatasi):
            servis.ayarlar()
        self.assertEqual(sayilar(), (0, 0))

        with patch.object(gg, "_yedek_dosyasi_al", side_effect=OSError(13, "Permission denied")):
            with self.assertRaises(gg.GecisYedekHatasi):
                servis.schema_hazirla()
        self.assertEqual(sayilar(), (0, 0))

        with patch.object(gg, "_dogrula", return_value=("yedek bütünlük denetimi başarısız (x)", {})):
            with self.assertRaises(gg.GecisYedekHatasi):
                servis.schema_hazirla()
        self.assertEqual(sayilar(), (0, 0))

        orijinal = servis._gecis

        def yarim(session, firma_id, *, yeni_firma):
            orijinal(session, firma_id, yeni_firma=yeni_firma)
            session.flush()
            raise RuntimeError("geçiş ortasında hata")

        with patch.object(servis, "_gecis", side_effect=yarim):
            with self.assertRaises(gg.GecisHatasi) as ctx:
                servis.schema_hazirla()
        self.assertTrue(ctx.exception.geri_yuklendi)
        self.assertEqual(sayilar(), (0, 0))

        yol = servis.schema_hazirla()
        self.assertIsNotNone(yol)
        self.assertTrue(Path(yol).is_file())
        ilk = sayilar()
        self.assertEqual(ilk[1], 1)
        self.assertIsNone(servis.schema_hazirla(), "geçiş tamamlandıysa yeniden yedek/geçiş yok")
        self.assertEqual(sayilar(), ilk)

    # ------------------------------------------------------------ 2) öneri
    def test_oneri_ana_hesabi_baglamaz_coklu_adayda_secim_ister(self):
        from database.models.genel_muhasebe import HesapPlani, MuhasebeHesapEsleme
        from database.muhasebe_entegrasyon import HesapEslemeService

        with get_session() as s:
            s.add(HesapPlani(firma_id=self.firma_id, hesap_kodu="100.01.0002", hesap_adi="Kasa 2",
                             hesap_seviyesi=3, hesap_turu="Aktif", borc_toplam=0, alacak_toplam=0, aktif=True))
            for e in s.scalars(select(MuhasebeHesapEsleme).where(MuhasebeHesapEsleme.anahtar.in_(("kasa", "banka")))):
                e.hesap_id = None
        rapor = HesapEslemeService.oneri_hesaplari_olustur()
        with get_session() as s:
            esleme = {e.anahtar: e.hesap_id for e in s.scalars(select(MuhasebeHesapEsleme))}
            ana_770 = s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == "770"))
            kodlar = {h.id: h.hesap_kodu for h in s.scalars(select(HesapPlani))}
        self.assertIsNotNone(ana_770, "ana hesaplar yüklenir")
        self.assertIsNone(esleme["kasa"], "iki uygun alt hesap: seçim kullanıcıya kalır")
        self.assertIn(("kasa", ["100.01.0001", "100.01.0002"]), rapor["secim_gerekli"])
        self.assertEqual(kodlar[esleme["banka"]], "102.01.0001")
        self.assertIn(("banka", "102.01.0001"), rapor["baglanan"])
        for anahtar, hid in esleme.items():
            if hid:
                self.assertRegex(kodlar[hid], r"^\d{3}\.\d{2}\.\d{4}$", anahtar)
        self.assertTrue(any(a == "giderler" for a, _k in rapor["korunan"]))

        # Ana hesap eşleştirilemez; mevcut uygunsuz eşleştirme raporlanır, değiştirilmez
        with self.assertRaises(ValueError):
            HesapEslemeService.kaydet("giderler", ana_770.id)
        with get_session() as s:
            e = s.scalar(select(MuhasebeHesapEsleme).where(MuhasebeHesapEsleme.anahtar == "giderler"))
            e.hesap_id = ana_770.id
        rapor = HesapEslemeService.oneri_hesaplari_olustur()
        self.assertTrue(any(a == "giderler" and k == "770" for a, k, _n, _ad in rapor["uygunsuz_mevcut"]))
        durumlar = {r["anahtar"]: r for r in HesapEslemeService.uygunluk_raporu()}
        self.assertEqual(durumlar["giderler"]["durum"], "uygunsuz")
        self.assertIn("770.01.0001", durumlar["giderler"]["adaylar"])
        self.assertEqual(durumlar["kasa"]["durum"], "eksik")
        with get_session() as s:
            self.assertEqual(s.scalar(select(MuhasebeHesapEsleme.hesap_id)
                                      .where(MuhasebeHesapEsleme.anahtar == "giderler")), ana_770.id)

    # ------------------------------------------------------------ 3/7) yeni türler otomatik + sonradan
    def test_yeni_turler_otomatik_tek_fis_sonradan_bekler(self):
        for tur in self.YENI_TURLER:
            with self.subTest(tur=tur, yontem="otomatik"):
                self._ayar("otomatik")
                once = self._bakiyeler()
                evrak, kid, no, beklenen = self._evrak_olustur(tur)
                d = self._durum(evrak, kid)
                self.assertEqual(d["durum"], "Muhasebeleştirildi", d)
                self.assertIsNotNone(d["fis_id"])
                fark = {k: v - once.get(k, Decimal("0")) for k, v in self._tutarli().items()}
                self.assertEqual({k: v for k, v in fark.items() if v}, beklenen)
                kaynak = self._servis().fis_kaynagi(d["fis_id"])
                self.assertEqual((kaynak["evrak_turu"], kaynak["kaynak_id"], kaynak["belge_no"]), (evrak, kid, no))
                self._temizle()
            with self.subTest(tur=tur, yontem="sonradan"):
                self._ayar("sonradan")
                evrak, kid, no, beklenen = self._evrak_olustur(tur)
                self.assertEqual(self._fis_sayisi(), 0)
                self.assertEqual(self._durum(evrak, kid)["durum"], "Bekliyor")
                sonuc = self._servis().muhasebelestir([self._durum_id(evrak, kid)])
                self.assertEqual(sonuc["basarili"], 1, sonuc)
                self.assertEqual(self._fis_sayisi(), 1)
                self.assertEqual(self._tutarli(), beklenen)
                sonuc = self._servis().muhasebelestir([self._durum_id(evrak, kid)])
                self.assertEqual(self._fis_sayisi(), 1, "ikinci kez fiş oluşmaz")
                self._temizle()

    def test_karar_bekleyen_kalem_incelemeye_duser_fis_tahmin_edilmez(self):
        from database.finans_service import FinansService

        self._ayar("otomatik")
        kmh = self._banka("Ziraat KMH", "KMH")
        no = FinansService.alinan_havale(kmh, TARIH, Decimal("250"), cari_id=self.musteri_id)
        kid = self._kimlik("banka_havale", no)
        d = self._durum_kaydi("banka_havale", kid)
        self.assertEqual(d.durum, "İnceleme gerekiyor")
        self.assertIn("Karar bekliyor", d.aciklama)
        self.assertEqual(self._fis_sayisi(), 0)
        self.assertEqual(self._hareket_sayisi(no), 1, "evrak kaydedilir")
        sonuc = self._servis().muhasebelestir([d.id])
        self.assertEqual(self._fis_sayisi(), 0, sonuc)

    def test_eslesme_eksikse_otomatikte_evrak_kaydedilmez_sonradanda_bekler(self):
        from database.finans_service import FinansService
        from database.muhasebe_entegrasyon import HesapEslemeService

        HesapEslemeService.kaydet("banka", None)
        self._ayar("otomatik")
        banka = self._banka()
        # Banka hesabı kart bazında seçilir: kartta da firma varsayılanında da hesap yoksa evrak kaydedilir,
        # fiş tahmin edilmez, 'İnceleme gerekiyor' olur (KMH / POS ile aynı kural).
        no1 = FinansService.alinan_havale(banka, TARIH, Decimal("500"), cari_id=self.musteri_id)
        d1 = self._durum_kaydi("banka_havale", self._kimlik("banka_havale", no1))
        self.assertEqual(d1.durum, "İnceleme gerekiyor")
        self.assertIn("muhasebe hesabı seçilmemiş", d1.aciklama)
        self.assertEqual(self._fis_sayisi(), 0)
        self._ayar("sonradan")
        no = FinansService.alinan_havale(banka, TARIH, Decimal("500"), cari_id=self.musteri_id)
        kid = self._kimlik("banka_havale", no)
        sonuc = self._servis().muhasebelestir([self._durum_id("banka_havale", kid)])
        self.assertEqual(sonuc["basarili"], 0)
        self.assertEqual(self._fis_sayisi(), 0)

    def test_evrak_iptali_muhasebelesmisse_bir_kez_ters_kayit(self):
        from database.cari_service import CariService
        from database.cari_virman_makbuz_service import CariVirmanMakbuzService
        from database.finans_service import FinansService

        self._ayar("otomatik")
        once = self._bakiyeler()
        _e, mid, _no, _b = self._evrak_olustur("kasa_makbuzu")
        FinansService.kasa_makbuz_iptal(mid)
        with self.assertRaises(ValueError):
            FinansService.kasa_makbuz_iptal(mid)
        self.assertEqual(self._durum("kasa_makbuzu", mid)["durum"], "İptal edildi")
        _e, vid, _no, _b = self._evrak_olustur("cari_virman_makbuzu")
        CariVirmanMakbuzService.iptal(vid)
        _e, kid, vno, _b = self._evrak_olustur("cari_virman")
        CariService.virman_iptal(vno)
        self.assertEqual(self._durum("cari_virman", kid)["durum"], "İptal edildi")
        self.assertEqual(self._tutarli(), once)
        # Sonradan: muhasebeleşmemiş evrak iptalinde ters fiş oluşmaz
        self._ayar("sonradan")
        _e, mid, _no, _b = self._evrak_olustur("kasa_makbuzu")
        fis = self._fis_sayisi()
        FinansService.kasa_makbuz_iptal(mid)
        self.assertEqual(self._fis_sayisi(), fis)
        self.assertEqual(self._durum("kasa_makbuzu", mid)["durum"], "İptal edildi")

    # ------------------------------------------------------------ 5) tahsilat/ödeme iptali
    def _acik_toplam(self, cari_id) -> Decimal:
        from database.models.cari import SatisHareketi

        with get_session() as s:
            return Decimal(str(s.scalar(select(func.coalesce(func.sum(SatisHareketi.kalan_acik_tutar), 0))
                                        .where(SatisHareketi.cari_id == cari_id))))

    def test_tahsilat_iptali_bakiye_kasa_kapatma_ve_ters_fis(self):
        from database.cari_service import CariService
        from database.finans_service import FinansService
        from database.models.cari import CariIslem
        from database.models.genel_muhasebe import MuhasebeFisi

        self._ayar("otomatik")
        self._alis("U001", "100", "100", "LOT-A")
        self._sat("10")
        acik_once = self._acik_toplam(self.musteri_id)
        bakiye_once = FinansService.cari_bakiye_ozeti(self.musteri_id)["bakiye"]
        gm_once = self._bakiyeler()
        self._kasa()
        islem = CariService.tahsilat_yap(self.musteri_id, TARIH, Decimal("1000"), "Nakit", "Merkez Kasa")
        self.assertEqual(self._acik_toplam(self.musteri_id), acik_once - Decimal("1000"))
        kimlik = CariService.tahsilat_odeme_evraki(islem.id)
        self.assertEqual(self._durum("cari_tahsilat", kimlik["kaynak_id"])["durum"], "Muhasebeleştirildi")
        with self.assertRaises(ValueError):
            CariService.tahsilat_odeme_iptal(islem.id, "  ")
        CariService.tahsilat_odeme_iptal(islem.id, "Yanlış cari")
        self.assertEqual(self._acik_toplam(self.musteri_id), acik_once, "kapatılan borç yeniden açılır")
        self.assertEqual(FinansService.cari_bakiye_ozeti(self.musteri_id)["bakiye"], bakiye_once)
        self.assertEqual(self._hareket_sayisi(islem.belge_no), 0)
        self.assertEqual(self._tutarli(), gm_once, "fiş ters kayıtla kapandı")
        self.assertEqual(self._durum("cari_tahsilat", kimlik["kaynak_id"])["durum"], "İptal edildi")
        with get_session() as s:
            self.assertIsNone(s.get(CariIslem, islem.id))
            ters = s.scalar(select(func.count()).select_from(MuhasebeFisi)
                            .where(MuhasebeFisi.belge_no == islem.belge_no))
        with self.assertRaises(ValueError):
            CariService.tahsilat_odeme_iptal(islem.id, "Tekrar")
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(MuhasebeFisi)
                                      .where(MuhasebeFisi.belge_no == islem.belge_no)), ters, "ikinci iptal etkisiz")
        from database.models.deleted_record import DeletedRecordLog

        with get_session() as s:
            log = s.scalar(select(DeletedRecordLog).where(DeletedRecordLog.record_code == islem.belge_no))
        self.assertIsNotNone(log, "iptal günlüğü")

    def test_odeme_iptali_sonradan_ters_fis_yok_eszamanli_tek_etki(self):
        from database.cari_service import CariService
        from database.models.genel_muhasebe import MuhasebeFisi

        self._ayar("sonradan")
        self._kasa()
        islem = CariService.odeme_yap(self.tedarikci_id, TARIH, Decimal("700"), "Nakit", "Merkez Kasa")
        kid = CariService.tahsilat_odeme_evraki(islem.id)["kaynak_id"]
        sonuclar, hatalar = [], []
        engel = threading.Barrier(2)

        def iptal():
            engel.wait()
            try:
                CariService.tahsilat_odeme_iptal(islem.id, "Çift tıklama")
                sonuclar.append(1)
            except ValueError as h:
                hatalar.append(str(h))

        is_parcaciklari = [threading.Thread(target=iptal) for _ in range(2)]
        for t in is_parcaciklari:
            t.start()
        for t in is_parcaciklari:
            t.join(60)
        self.assertEqual(len(sonuclar), 1, hatalar)
        self.assertEqual(len(hatalar), 1)
        self.assertEqual(self._hareket_sayisi(islem.belge_no), 0)
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(MuhasebeFisi)), 0, "ters fiş yok")
        self.assertEqual(self._durum("cari_odeme", kid)["durum"], "İptal edildi")
        self.assertEqual(self._servis().listele(durumlar=("Bekliyor",)), [], "bekleyen listeden çıkar")

    def test_tahsilat_iptali_donem_kilidi_ve_yetki(self):
        from database.access import AccessError
        from database.cari_service import CariService
        from database.models.donem import Donem
        from database.session_manager import oturum

        self._ayar("otomatik")
        self._kasa()
        islem = CariService.tahsilat_yap(self.musteri_id, TARIH, Decimal("300"), "Nakit", "Merkez Kasa")
        with get_session() as s:
            for d in s.scalars(select(Donem)):
                d.kapali = True
        with self.assertRaises(ValueError):
            CariService.tahsilat_odeme_iptal(islem.id, "Dönem kapalı")
        self.assertEqual(self._hareket_sayisi(islem.belge_no), 1)
        with get_session() as s:
            for d in s.scalars(select(Donem)):
                d.kapali = False
        oturum.set_user(user_id=2, kullanici_adi="satis", ad_soyad="Satış", role_kod="SATIS",
                        role_ad="Satış", permissions={"satis_goruntuleme"})
        with self.assertRaises(AccessError):
            CariService.tahsilat_odeme_iptal(islem.id, "Yetkisiz")
        self.assertEqual(self._hareket_sayisi(islem.belge_no), 1)

    def test_aktarim_hareketi_tahsilat_evraki_gibi_iptal_edilmez(self):
        from database.cari_service import CariService
        from database.models.cari import CariIslem

        with get_session() as s:
            i = CariIslem(cari_id=self.musteri_id, tarih=TARIH, islem_turu="Tahsilat", belge_no="EVB-0001",
                          borc=Decimal("0"), alacak=Decimal("90"), aciklama="Excel aktarımı")
            s.add(i)
            s.flush()
            iid = i.id
        with self.assertRaises(ValueError):
            CariService.tahsilat_odeme_iptal(iid, "Deneme")
        with get_session() as s:
            self.assertIsNotNone(s.get(CariIslem, iid))

    # ------------------------------------------------------------ 4) geçmiş kayıt önizleme
    def test_gecmis_finans_onizleme_kesin_belirsiz_muhasebelesmis_secimle_eklenir(self):
        from database.cari_service import CariService
        from database.finans_service import FinansService
        from database.models.cari import CariIslem
        from database.muhasebe_entegrasyon import ESKI_KAYNAK_CARI_TAHSILAT, MuhasebeEntegrasyonService

        self._kasa()
        self._ayar("otomatik", gm=False)
        yeni = CariService.tahsilat_yap(self.musteri_id, TARIH, Decimal("100"), "Nakit", "Merkez Kasa")
        makbuz_e, makbuz_id, _n, _b = self._evrak_olustur("kasa_makbuzu")
        with get_session() as s:
            # Kalıcı kimlik öncesi cari kartı tahsilatı (yapısı kesin)
            eski = CariIslem(cari_id=self.musteri_id, tarih=TARIH, islem_turu="Tahsilat", belge_no="THS-2025-0090",
                             borc=Decimal("0"), alacak=Decimal("80"), hesap_adi="Merkez Kasa")
            s.add(eski)
            FinansService.hareket_ekle(s, "THS-2025-0090", TARIH, Decimal("80"), "CARİ TAHSİLAT", "Merkez Kasa", "Nakit")
            # Eski sürüm fişi bağlı tahsilat
            bagli = CariIslem(cari_id=self.musteri_id, tarih=TARIH, islem_turu="Tahsilat", belge_no="THS-2025-0091",
                              borc=Decimal("0"), alacak=Decimal("70"), hesap_adi="Merkez Kasa")
            s.add(bagli)
            FinansService.hareket_ekle(s, "THS-2025-0091", TARIH, Decimal("70"), "CARİ TAHSİLAT", "Merkez Kasa", "Nakit")
            # Excel aktarımı ve kasa hareketi eksik THS
            s.add(CariIslem(cari_id=self.musteri_id, tarih=TARIH, islem_turu="Tahsilat", belge_no="EVB-0005",
                            borc=Decimal("0"), alacak=Decimal("60")))
            s.add(CariIslem(cari_id=self.musteri_id, tarih=TARIH, islem_turu="Tahsilat", belge_no="THS-2025-0092",
                            borc=Decimal("0"), alacak=Decimal("50")))
            s.flush()
            bagli_id = bagli.id
        self._ayar("sonradan")
        with get_session() as s:
            fh = MuhasebeEntegrasyonService._hesap("kasa", session=s)
            ch = MuhasebeEntegrasyonService._hesap("musteriler", session=s)
            MuhasebeEntegrasyonService._olustur(
                kaynak_turu=ESKI_KAYNAK_CARI_TAHSILAT, kaynak_id=bagli_id, fis_tarihi=TARIH,
                fis_turu="Tahsil Fişi", aciklama="Eski sürüm", belge_no="THS-2025-0091",
                satirlar=[MuhasebeEntegrasyonService._satir(fh, borc=Decimal("70")),
                          MuhasebeEntegrasyonService._satir(ch, alacak=Decimal("70"))],
                yeniden=False, session=s)
        fis_once = self._fis_sayisi()

        oniz = self._servis().gecmis_finans_onizle()
        tahsilat = {k: {r["anahtar"] for r in v} for k, v in oniz["cari_tahsilat"].items()}
        self.assertEqual(tahsilat["kesin"], {yeni.belge_no, "THS-2025-0090"})
        self.assertEqual(tahsilat["belirsiz"], {"EVB-0005", "THS-2025-0092"})
        self.assertEqual(tahsilat["muhasebelestirilmis"], {"THS-2025-0091"})
        self.assertEqual({r["anahtar"] for r in oniz["kasa_makbuzu"]["kesin"]}, {makbuz_id})
        self.assertEqual(self._fis_sayisi(), fis_once, "önizleme yazmaz")
        self.assertEqual(self._servis().listele(durumlar=("Bekliyor",)), [], "kendiliğinden listeye alınmaz")

        sonuc = self._servis().gecmis_finans_ekle([
            ("cari_tahsilat", yeni.belge_no), ("cari_tahsilat", "THS-2025-0090"), ("kasa_makbuzu", makbuz_id),
            ("cari_tahsilat", "EVB-0005"), ("cari_tahsilat", "THS-2025-0091"),
        ])
        self.assertEqual(len(sonuc["eklenen"]), 3, sonuc)
        self.assertEqual({r["anahtar"] for r in sonuc["reddedilen"]}, {"EVB-0005", "THS-2025-0091"})
        self.assertEqual(self._fis_sayisi(), fis_once, "listeye alma fiş üretmez")
        tekrar = self._servis().gecmis_finans_ekle([("cari_tahsilat", yeni.belge_no)])
        self.assertEqual(tekrar["eklenen"], [])
        ids = [d["id"] for d in self._servis().listele(durumlar=("Bekliyor",))]
        self.assertEqual(len(ids), 3)
        self.assertEqual(self._servis().muhasebelestir(ids)["basarili"], 3)
        self.assertEqual(self._fis_sayisi(), fis_once + 3)
        oniz = self._servis().gecmis_finans_onizle()
        self.assertEqual({r["anahtar"] for r in oniz["cari_tahsilat"]["listede"]}, {yeni.belge_no, "THS-2025-0090"})
        self._tutarli()

        # Eski kimliksiz tahsilat iptali: kimlik oluşur, eski sürüm fişi bir kez ters kayıtla kapanır
        bakiye_once = self._bakiyeler()
        CariService.tahsilat_odeme_iptal(bagli_id, "Eski kayıt iptal")
        fark = {k: v - bakiye_once.get(k, Decimal("0")) for k, v in self._bakiyeler().items()}
        self.assertEqual({k: v for k, v in fark.items() if v},
                         {"100.01.0001": Decimal("-70"), "120.01.0001": Decimal("70")})

    def test_gecmis_finans_ekrani_yalniz_kesin_kaydi_listeye_alir(self):
        import tkinter as tk

        from muhasebelestirme_ui import GecmisFinansDialog

        self._kasa()
        self._ayar("otomatik", gm=False)
        _e, makbuz_id, makbuz_no, _b = self._evrak_olustur("kasa_makbuzu")
        self._ayar("sonradan")
        kok = tk.Tk()
        kok.withdraw()
        try:
            with patch("muhasebelestirme_ui.messagebox.askyesno", return_value=True), \
                    patch("muhasebelestirme_ui.messagebox.showinfo") as bilgi:
                d = GecmisFinansDialog(kok)
                satirlar = d.tablo.get_children()
                self.assertEqual([d.tablo.set(i, "belge") for i in satirlar], [makbuz_no])
                d.tablo.selection_set(satirlar)
                d._ekle()
            self.assertIn("Bekleyenlere alınan: 1", bilgi.call_args.args[1])
            self.assertEqual(self._durum("kasa_makbuzu", makbuz_id)["durum"], "Bekliyor")
            self.assertEqual(d.tablo.get_children(), ())
            d.destroy()
        finally:
            kok.destroy()

    def test_gecmis_finans_ekle_yetki_ister(self):
        from database.access import AccessError
        from database.session_manager import oturum

        oturum.set_user(user_id=2, kullanici_adi="satis", ad_soyad="Satış", role_kod="SATIS",
                        role_ad="Satış", permissions={"satis_goruntuleme"})
        with self.assertRaises(AccessError):
            self._servis().gecmis_finans_ekle([("cari_tahsilat", "THS-1")])


if __name__ == "__main__":
    unittest.main()
