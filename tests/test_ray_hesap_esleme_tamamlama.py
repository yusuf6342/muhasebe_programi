"""Ray Mobilya eşleştirme tamamlama (tools/ray_hesap_esleme_tamamla.py) — yalıtılmış geçici veritabanı.

Ray'e benzer hesap planı kurulur (TDHP ana hesaplar, eşleştirmeler ana hesaplara bağlı, 100.01 / 101.01 /
153.01 alt hesapları, ana hesaplarda geçmiş fiş). Script'in hesap açma / bağlama mantığı, tekrar
çalıştırmada mükerrer olmaması, ana hesaba fiş engeli ve tamamlanan hesaplarla fiş üretimi (satış, alış,
tahsilat, ödeme, KMH, POS, şirket kartı, banka kredisi, çek/senet aşamaları), borç = alacak, iptalde ters
kayıt, ikinci muhasebeleştirmede mükerrer fiş olmaması ve hesap planı-mizan tutarlılığı doğrulanır.

Script'in bilerek bağlamadığı (kasa, banka, KMH, POS valör, şirket kartı) eşleştirmeler fiş akışı
testlerinde "kullanıcı kararı" olarak test içinde bağlanır.
"""

from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools"))

from sqlalchemy import delete, func, select, update  # noqa: E402

import ray_hesap_esleme_tamamla as rht  # noqa: E402
import test_muhasebelestirme_finans_ayarlari as tfa  # noqa: E402
from database.database import get_session  # noqa: E402
from database.models.genel_muhasebe import (  # noqa: E402
    BELGE_IPTAL,
    BELGE_MUHASEBELESTIRILDI,
    ESLEME_ANAHTARLARI,
    HesapPlani,
    MuhasebeFisi,
    MuhasebeFisiSatiri,
    MuhasebeHesapEsleme,
    MuhasebeIslemGecmisi,
)

TARIH = tfa.TARIH
D = Decimal

# Ray'deki 10 bağlı eşleştirme (hepsi ana hesap) + 13 boş eşleştirme; finans ayar anahtarları yok
RAY_BAGLI = {"musteriler": "120", "tedarikciler": "320", "kasa": "100", "banka": "102", "yurtici_satislar": "600",
             "satilan_mal_maliyeti": "621", "ticari_mallar": "153", "hesaplanan_kdv": "391",
             "indirilecek_kdv": "191", "giderler": "770"}
RAY_ANAHTAR_SAYISI = 23
BEKLENEN_BAGLANAN = {a for a, *_ in rht.HEDEFLER}
BEKLENEN_KARAR = {"kasa", "banka", "kmh_hesabi", "pos_valor_alacagi", "sirket_kart_borcu", "kredi_ara_hesap"}
# Script'in bağlamadığı eşleştirmeler için test içi kullanıcı kararı: (anahtar, tali grup, yaprak, ad)
KARARLAR = {
    "kasa": (None, "100.01.0001", None),
    "banka": ("102.01", "102.01.0001", "AKBANK MEVDUAT"),
    "kmh_hesabi": ("300.02", "300.02.0001", "AKBANK KMH"),
    "pos_valor_alacagi": ("108.01", "108.01.0001", "AKBANK POS VALÖR ALACAĞI"),
    "sirket_kart_borcu": ("309.01", "309.01.0001", "AKBANK ŞİRKET KREDİ KARTI"),
}


class _Ray(tfa._Temel):
    def setUp(self):
        super().setUp()
        self._ray_plani_kur()

    # ------------------------------------------------------------ Ray'e benzer başlangıç
    def _ray_plani_kur(self):
        from database.muhasebe_service import MuhasebeService

        with get_session() as s:
            s.execute(delete(MuhasebeHesapEsleme))
            s.execute(update(HesapPlani).values(ust_hesap_id=None))
            s.execute(delete(HesapPlani))
        MuhasebeService.ana_hesaplari_doldur()
        with get_session() as s:
            kod = {h.hesap_kodu: h for h in s.scalars(select(HesapPlani)).all()}

            def ekle(k, ad, ust, seviye):
                h = HesapPlani(firma_id=self.firma_id, hesap_kodu=k, hesap_adi=ad,
                               ust_hesap_id=kod[ust].id if ust else None, hesap_seviyesi=seviye,
                               hesap_turu="Aktif", aktif=True, borc_toplam=0, alacak_toplam=0)
                s.add(h)
                s.flush()
                kod[k] = h

            # Ray'deki gibi (100.01 / 100.01.0001 üst bağı boş)
            ekle("100.01", "KASA TALİ HESABI", None, 2)
            ekle("100.01.0001", "NAKİT TL KASA", None, 3)
            ekle("100.01.0002", "MERKEZ KASA", "100.01", 3)
            ekle("101.01", "MÜŞTERİ ÇEKLERİ TALİ HESABI", "101", 4)
            ekle("101.01.0001", "MÜŞTERİ ÇEKLERİ ALT HESABI", "101.01", 5)
            ekle("153.01", "TİCARİ MALLAR TALİ HESABI", "153", 4)
            ekle("153.01.0001", "TİCARİ MALLAR ALT HESABI", "153.01", 5)
            adlar = dict(ESLEME_ANAHTARLARI)
            for anahtar, _ad in ESLEME_ANAHTARLARI[:RAY_ANAHTAR_SAYISI]:
                ana = RAY_BAGLI.get(anahtar)
                s.add(MuhasebeHesapEsleme(firma_id=self.firma_id, anahtar=anahtar, aciklama=adlar[anahtar],
                                          hesap_id=kod[ana].id if ana else None, aktif=True))
            # Ana hesaplara yazılmış geçmiş fiş (eski sürüm): bakiyesi korunmalı, iptali çalışmalı
            fis = MuhasebeFisi(firma_id=self.firma_id, mali_yil=2026, fis_no="ESKI-1", fis_tarihi=TARIH,
                               fis_turu="Mahsup Fişi", durum="Kesinleşmiş", toplam_borc=D("1200"),
                               toplam_alacak=D("1200"))
            s.add(fis)
            s.flush()
            for sira, (k, b, a) in enumerate((("120", "1200", "0"), ("600", "0", "1000"), ("391", "0", "200")), 1):
                h = kod[k]
                s.add(MuhasebeFisiSatiri(fis_id=fis.id, firma_id=self.firma_id, sira_no=sira, hesap_id=h.id,
                                         hesap_kodu=k, hesap_adi=h.hesap_adi, borc=D(b), alacak=D(a)))
                h.borc_toplam, h.alacak_toplam = D(b), D(a)
            self.eski_fis_id = int(fis.id)

    # ------------------------------------------------------------ yardımcılar
    def _script(self) -> dict:
        with get_session() as s:
            plan = rht.planla(s, self.firma_id)
            plan["sonuc"] = rht.uygula(s, self.firma_id, plan, islem_yapan="test")
        return plan

    def _hesap(self, kod) -> HesapPlani | None:
        with get_session() as s:
            return s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == kod))

    def _esleme_kodu(self, anahtar) -> str | None:
        with get_session() as s:
            e = s.scalar(select(MuhasebeHesapEsleme).where(MuhasebeHesapEsleme.anahtar == anahtar))
            if e is None or not e.hesap_id:
                return None
            return s.get(HesapPlani, e.hesap_id).hesap_kodu

    def _kararlari_bagla(self, *anahtarlar):
        """Script'in bağlamadığı eşleştirmeler: kullanıcı kararı simülasyonu (uygulama servisiyle)."""
        from database.muhasebe_entegrasyon import HesapEslemeService

        for anahtar in anahtarlar or KARARLAR:
            grup, yaprak, ad = KARARLAR[anahtar]
            with get_session() as s:
                h = s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == yaprak))
                if h is None:
                    ana = s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == grup.split(".")[0]))
                    g = HesapPlani(firma_id=self.firma_id, hesap_kodu=grup, hesap_adi=f"{ad} TALİ",
                                   ust_hesap_id=ana.id, hesap_seviyesi=ana.hesap_seviyesi + 1,
                                   hesap_turu=ana.hesap_turu, aktif=True, borc_toplam=0, alacak_toplam=0)
                    s.add(g)
                    s.flush()
                    h = HesapPlani(firma_id=self.firma_id, hesap_kodu=yaprak, hesap_adi=ad, ust_hesap_id=g.id,
                                   hesap_seviyesi=g.hesap_seviyesi + 1, hesap_turu=ana.hesap_turu, aktif=True,
                                   borc_toplam=0, alacak_toplam=0)
                    s.add(h)
                    s.flush()
                hid = int(h.id)
            HesapEslemeService.kaydet(anahtar, hid)

    def _fisler_dengeli(self):
        with get_session() as s:
            for f in s.scalars(select(MuhasebeFisi)).all():
                b, a = s.execute(select(func.coalesce(func.sum(MuhasebeFisiSatiri.borc), 0),
                                        func.coalesce(func.sum(MuhasebeFisiSatiri.alacak), 0))
                                 .where(MuhasebeFisiSatiri.fis_id == f.id)).one()
                self.assertEqual(D(str(b)), D(str(a)), f"fiş {f.fis_no} satırları dengesiz")
                self.assertEqual(D(str(f.toplam_borc)), D(str(f.toplam_alacak)), f"fiş {f.fis_no} toplamı dengesiz")
                for st in s.scalars(select(MuhasebeFisiSatiri).where(MuhasebeFisiSatiri.fis_id == f.id)):
                    if f.fis_no != "ESKI-1" and not (f.aciklama or "").startswith("Ters kayıt: ESKI-1"):
                        self.assertRegex(st.hesap_kodu, r"^\d{3}\.\d{2}\.\d{4}$", "yeni fiş ana hesaba yazıldı")

    def _kaynak_fis_sayisi(self, kaynak_turu, kaynak_id) -> int:
        with get_session() as s:
            return int(s.scalar(select(func.count()).select_from(MuhasebeFisi).where(
                MuhasebeFisi.kaynak_turu == kaynak_turu, MuhasebeFisi.kaynak_id == int(kaynak_id))))

    def tearDown(self):
        try:
            if not getattr(self, "_atla_son_kontrol", False):
                self._fisler_dengeli()
                self._tutarli()
        finally:
            super().tearDown()


# ====================================================================== script mantığı
class ScriptMantigiTest(_Ray):
    def test_ray_benzeri_planda_hesap_acma_ve_baglama(self):
        once = self._tutarli()
        plan = self._script()

        self.assertEqual({b["anahtar"] for b in plan["bagla"]}, BEKLENEN_BAGLANAN)
        self.assertEqual({k["anahtar"] for k in plan["kullanici_karari"]}, BEKLENEN_KARAR)
        self.assertEqual(plan["korunan"], [])
        acilan = {h["kod"] for h in plan["hesap_ekle"]}
        self.assertEqual(len(acilan), 47)
        self.assertNotIn("153.01.0001", acilan, "mevcut tek uygun hesap kullanılır")
        self.assertNotIn("101.01.0001", acilan)
        self.assertNotIn("101.01", acilan)
        self.assertEqual(set(plan["esleme_satiri_ekle"]),
                         {a for a, _ in ESLEME_ANAHTARLARI[RAY_ANAHTAR_SAYISI:]})
        bagla = {b["anahtar"]: b for b in plan["bagla"]}
        self.assertEqual(bagla["musteriler"]["onceki"], "120")
        self.assertEqual(bagla["musteriler"]["hesap"], "120.01.0001")
        self.assertEqual(bagla["ticari_mallar"]["hesap"], "153.01.0001")
        self.assertEqual(bagla["cek_portfoy"]["hesap"], "101.01.0001")

        from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService, hesap_uygunluk_sorunu

        with get_session() as s:
            for anahtar in BEKLENEN_BAGLANAN:
                self.assertIsNone(MuhasebeEntegrasyonService.esleme_sorunu(anahtar, session=s), anahtar)
            for h in plan["hesap_ekle"]:
                yeni = s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == h["kod"]))
                self.assertEqual((D(str(yeni.borc_toplam)), D(str(yeni.alacak_toplam))), (D("0"), D("0")))
                ust = s.get(HesapPlani, yeni.ust_hesap_id)
                self.assertEqual(ust.hesap_kodu, h["ust"])
                self.assertEqual(yeni.hesap_seviyesi, ust.hesap_seviyesi + 1)
                sorun = hesap_uygunluk_sorunu(s, yeni, self.firma_id)
                if h["fise_acik"]:
                    self.assertIsNone(sorun, h["kod"])
                else:
                    self.assertIn("ana/üst hesap", sorun, "tali grup fişe kapalı")
        # Belirsiz eşleştirmeler değişmedi (tahmin edilmedi)
        self.assertEqual(self._esleme_kodu("kasa"), "100")
        self.assertEqual(self._esleme_kodu("banka"), "102")
        self.assertIsNone(self._esleme_kodu("kmh_hesabi"))
        # Geçmiş fiş ve bakiyeler değişmedi
        self.assertEqual(self._tutarli(), once)
        self.assertEqual(once, {"120": D("1200"), "600": D("-1000"), "391": D("-200")})

    def test_tekrar_calistirmada_mukerrer_hesap_ve_baglama_yok(self):
        self._script()
        with get_session() as s:
            hesap_sayisi = s.scalar(select(func.count()).select_from(HesapPlani))
            gecmis_sayisi = s.scalar(select(func.count()).select_from(MuhasebeIslemGecmisi))
        plan2 = self._script()
        self.assertEqual(plan2["hesap_ekle"], [])
        self.assertEqual(plan2["bagla"], [])
        self.assertEqual(plan2["esleme_satiri_ekle"], [])
        self.assertEqual({k["anahtar"] for k in plan2["korunan"]}, BEKLENEN_BAGLANAN)
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(HesapPlani)), hesap_sayisi)
            self.assertEqual(s.scalar(select(func.count()).select_from(MuhasebeIslemGecmisi)), gecmis_sayisi)

    def test_kullanici_secimi_korunur_ve_ayni_amacli_hesap_varsa_mukerrer_acilmaz(self):
        with get_session() as s:
            ana = s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == "320"))
            s.add(HesapPlani(firma_id=self.firma_id, hesap_kodu="320.05.0001", hesap_adi="YURTİÇİ SATICILAR",
                             ust_hesap_id=ana.id, hesap_seviyesi=4, hesap_turu="Pasif", aktif=True,
                             borc_toplam=0, alacak_toplam=0))
        self._kararlari_bagla("kasa")
        plan = self._script()
        karar = {k["anahtar"]: k["neden"] for k in plan["kullanici_karari"]}
        self.assertIn("320.05.0001", karar["tedarikciler"])
        self.assertFalse([h for h in plan["hesap_ekle"] if h["kod"].startswith("320.")])
        self.assertEqual(self._esleme_kodu("tedarikciler"), "320", "belirsizken değiştirilmez")
        self.assertIn({"anahtar": "kasa", "hesap": "100.01.0001", "ad": "NAKİT TL KASA"}, plan["korunan"])
        self.assertEqual(self._esleme_kodu("kasa"), "100.01.0001")


# ====================================================================== ana hesaba fiş engeli
class AnaHesapFisEngeliTest(_Ray):
    def _fis(self, borc_kod, alacak_kod, tutar="100"):
        from database.muhasebe_service import MuhasebeFisService

        ids = {k: self._hesap(k).id for k in (borc_kod, alacak_kod)}
        return MuhasebeFisService.kaydet({
            "fis_turu": "Mahsup Fişi", "fis_tarihi": TARIH, "durum": "Kesinleşmiş",
            "satirlar": [{"hesap_id": ids[borc_kod], "borc": D(tutar)},
                         {"hesap_id": ids[alacak_kod], "alacak": D(tutar)}]})

    def test_ana_tali_ve_alti_dolu_hesaba_fis_yazilamaz_gecmis_fis_iptali_calisir(self):
        from database.muhasebe_service import MuhasebeFisService

        self._script()
        once = self._tutarli()
        for ana in ("120", "120.01"):
            with self.assertRaisesRegex(ValueError, "fiş yazılamaz"):
                self._fis(ana, "600.01.0001")
        # Biçimi uygun ama altında hesap olan hesap
        with get_session() as s:
            ust = s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == "770.01"))
            dolu = HesapPlani(firma_id=self.firma_id, hesap_kodu="770.01.0099", hesap_adi="DOLU", ust_hesap_id=ust.id,
                              hesap_seviyesi=5, hesap_turu="Gider", aktif=True, borc_toplam=0, alacak_toplam=0)
            s.add(dolu)
            s.flush()
            s.add(HesapPlani(firma_id=self.firma_id, hesap_kodu="770.01.0099.01", hesap_adi="ALT", ust_hesap_id=dolu.id,
                             hesap_seviyesi=6, hesap_turu="Gider", aktif=True, borc_toplam=0, alacak_toplam=0))
            yanlis_ust = s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == "391.01"))
            s.add(HesapPlani(firma_id=self.firma_id, hesap_kodu="191.09.0001", hesap_adi="UYUMSUZ",
                             ust_hesap_id=yanlis_ust.id, hesap_seviyesi=5, hesap_turu="Aktif", aktif=True,
                             borc_toplam=0, alacak_toplam=0))
        with self.assertRaisesRegex(ValueError, "altında alt hesap var"):
            self._fis("770.01.0099", "100.01.0001")
        with self.assertRaisesRegex(ValueError, "uyumsuz"):
            self._fis("191.09.0001", "320.01.0001")
        self.assertEqual(self._tutarli(), once, "reddedilen fiş iz bırakmaz")

        # Yaprak alt hesaplara fiş yazılır
        fid = self._fis("120.01.0001", "600.01.0001", "50")
        self.assertEqual(self._fark(once), {"120.01.0001": D("50"), "600.01.0001": D("-50")})
        MuhasebeFisService.iptal(fid, "test", otomatik=True)
        self.assertEqual(self._fark(once), {})

        # Ana hesaplara yazılmış geçmiş fiş: ters kayıtla iptal edilebilir, bakiyeler sıfırlanır
        MuhasebeFisService.iptal(self.eski_fis_id, "eski fiş iptali", otomatik=True)
        self.assertEqual(self._tutarli(), {})


# ====================================================================== fiş üretimi
class FisUretimiTest(_Ray):
    def setUp(self):
        super().setUp()
        self.plan = self._script()
        self._kararlari_bagla()
        self._ayar("otomatik")

    def test_satis_alis_tahsilat_odeme_gider_iptal_tekrar(self):
        from database.finans_service import FinansService
        from database.models.finans import FinansEvrakKimligi
        from database.satis_faturasi_service import SatisFaturasiService

        once = self._tutarli()
        alis_id, _ = self._alis()
        satis_id = self._sat("40")
        alis_satis = {"153.01.0001": D("6000"), "191.01.0001": D("2000"), "320.01.0001": D("-12000"),
                      "120.01.0001": D("9600"), "600.01.0001": D("-8000"), "391.01.0001": D("-1600"),
                      "621.01.0001": D("4000")}
        self.assertEqual(self._fark(once), alis_satis)

        banka = self._banka()
        no_t = FinansService.alinan_havale(banka, TARIH, D("9600"), cari_id=self.musteri_id)
        no_o = FinansService.gonderilen_havale(banka, TARIH, D("12000"), cari_id=self.tedarikci_id)
        self._gider_fisi("1000")
        beklenen = dict(alis_satis)
        beklenen.update({"120.01.0001": D("0"), "320.01.0001": D("0"), "102.01.0001": D("-2400"),
                         "770.01.0001": D("1000"), "100.01.0001": D("-1000")})
        beklenen = {k: v for k, v in beklenen.items() if v}
        self.assertEqual(self._fark(once), beklenen)
        with get_session() as s:
            kid_t = int(s.scalar(select(FinansEvrakKimligi.id).where(FinansEvrakKimligi.belge_no == no_t)))
        self.assertTrue(no_o)

        # Tekrar muhasebeleştirme mükerrer fiş üretmez
        for evrak, kid, kaynak in (("satis_faturasi", satis_id, "satis_faturasi"),
                                   ("alis_faturasi", alis_id, "alis_faturasi"),
                                   ("banka_havale", kid_t, "banka_havale")):
            self.assertEqual(self._durum(evrak, kid)["durum"], BELGE_MUHASEBELESTIRILDI, evrak)
            self._servis().muhasebelestir([self._durum_id(evrak, kid)])
            self.assertEqual(self._kaynak_fis_sayisi(kaynak, kid), 1, evrak)
        self.assertEqual(self._fark(once), beklenen)

        # Satış iptali: ters kayıt; ikinci iptal yeni ters kayıt üretmez
        SatisFaturasiService.iptal_et(satis_id, "test")
        SatisFaturasiService.iptal_et(satis_id, "tekrar")
        satis_etkisi = {"120.01.0001": D("9600"), "600.01.0001": D("-8000"), "391.01.0001": D("-1600"),
                        "621.01.0001": D("4000"), "153.01.0001": D("-4000")}
        sonra = {k: beklenen.get(k, D("0")) - satis_etkisi.get(k, D("0")) for k in set(beklenen) | set(satis_etkisi)}
        self.assertEqual(self._fark(once), {k: v for k, v in sonra.items() if v})
        self.assertEqual(self._durum("satis_faturasi", satis_id)["durum"], BELGE_IPTAL)

    def test_kmh_pos_sirket_karti(self):
        from database.finans_service import FinansService
        from database.models.finans import KrediKartiOdeme, KrediKartiTanimi

        kart = self._banka_karti()
        once = self._tutarli()
        FinansService.alinan_havale(kart["KMH"], TARIH, D("250"), cari_id=self.musteri_id)
        self.assertEqual(self._fark(once), {"300.02.0001": D("250"), "120.01.0001": D("-250")})

        r = FinansService.pos_tahsilat(kart["kart"], TARIH, D("1000"), cari_id=self.musteri_id)
        pid = int(r["kayit_id"])
        self.assertEqual(self._fark(once), {"300.02.0001": D("250"), "108.01.0001": D("980"),
                                            "653.01.0001": D("20"), "120.01.0001": D("-1250")})
        self._servis().muhasebelestir([self._durum_id("pos_tahsilat", pid)])
        self.assertEqual(self._kaynak_fis_sayisi("pos_tahsilat", pid), 1)
        FinansService.pos_valor_aktar(pid)
        self.assertEqual(self._durum("pos_valor_aktarimi", pid)["durum"], BELGE_MUHASEBELESTIRILDI)
        self.assertEqual(self._fark(once), {"300.02.0001": D("1230"), "653.01.0001": D("20"),
                                            "120.01.0001": D("-1250")})

        with get_session() as s:
            kk = KrediKartiTanimi(banka_karti_id=kart["kart"], kart_adi="Şirket Kartı", kart_limiti=D("50000"),
                                  aktif=True)
            s.add(kk)
            s.flush()
            kk_id = int(kk.id)
        r = FinansService.kredi_karti_odeme(kart["kart"], kk_id, self.tedarikci_id, TARIH, D("700"))
        with get_session() as s:
            ko_id = int(s.scalar(select(KrediKartiOdeme.id).where(KrediKartiOdeme.belge_no == r["belge_no"])))
        self._servis().muhasebelestir([self._durum_id("kart_odeme", ko_id)])
        self.assertEqual(self._kaynak_fis_sayisi("kart_odeme", ko_id), 1)
        self.assertEqual(self._fark(once), {"300.02.0001": D("1230"), "653.01.0001": D("20"),
                                            "120.01.0001": D("-1250"), "320.01.0001": D("700"),
                                            "309.01.0001": D("-700")})

    def test_banka_kredisi_kullandirim_taksit_iptal(self):
        from database.banka_kredi_service import BankaKrediService
        from database.models.finans import BankaKrediOdeme, BankaKrediTaksit, FinansHesabi

        self._finans_ayar(kredi__fis_zamani="kullandirim_ve_taksit", kredi__vade_ayrimi="oniki_ay")
        kart = self._banka_karti()
        with get_session() as s:
            s.get(FinansHesabi, kart["MEVDUAT"]).acilis_bakiyesi = D("50000")
        once = self._tutarli()
        kid = tfa.BankaKrediTest._kredi(self, kart)
        kullandirim = {"102.01.0001": D("10000"), "300.01.0001": D("-6000"), "400.01.0001": D("-4000")}
        self.assertEqual(self._fark(once), kullandirim)
        self._servis().muhasebelestir([self._durum_id("banka_kredi_kullandirim", kid)])
        self.assertEqual(self._kaynak_fis_sayisi("banka_kredi_kullandirim", kid), 1)

        with get_session() as s:
            t1 = s.scalars(select(BankaKrediTaksit).where(BankaKrediTaksit.kredi_id == kid)
                           .order_by(BankaKrediTaksit.taksit_no)).first()
            t1.faiz, t1.bsmv, t1.kkdf = D("300"), D("15"), D("45")
            t1_id = int(t1.id)
        ara = self._tutarli()
        r = BankaKrediService.taksit_ode(taksit_id=t1_id, odeme_tarihi=TARIH + timedelta(days=30),
                                         banka_hesap_id=kart["MEVDUAT"])
        with get_session() as s:
            oid = int(s.scalar(select(BankaKrediOdeme.id).where(BankaKrediOdeme.odeme_belge_no == r["odeme_belge_no"])))
        self.assertEqual(self._fark(ara), {"300.01.0001": D("6000"), "780.01.0001": D("300"),
                                           "780.01.0002": D("15"), "780.01.0003": D("45"),
                                           "102.01.0001": D("-6360")})
        self._servis().muhasebelestir([self._durum_id("banka_kredi_odeme", oid)])
        self.assertEqual(self._kaynak_fis_sayisi("banka_kredi_odeme", oid), 1)
        BankaKrediService.odeme_iptal(odeme_id=oid, neden="Yanlış dekont")
        self.assertEqual(self._fark(ara), {})
        self.assertEqual(self._fark(once), kullandirim)

    def test_cek_senet_asamalari(self):
        from database.cek_senet_service import CekSenetService
        from database.models.cek_senet import CekSenetEvrak

        from database.muhasebe_finans_ayarlari import CEK_SENET_ASAMALARI

        self._finans_ayar(**{f"cek_senet__{k}": "evet" for k, _a, _b in CEK_SENET_ASAMALARI})
        banka = self._banka()

        def evrak(yon, tur, no, tutar, cari):
            CekSenetService.olustur({"islem_yonu": yon, "basit_tur": tur, "evrak_no": no, "duzenleme_tarihi": TARIH,
                                     "vade_tarihi": TARIH + timedelta(days=60), "tutar": tutar, "cari_id": cari})
            with get_session() as s:
                return int(s.scalar(select(CekSenetEvrak.id).where(CekSenetEvrak.evrak_no == no)))

        once = self._tutarli()
        c1 = evrak("ALINAN", "CEK", "R-C1", "1000", self.musteri_id)
        self.assertEqual(self._fark(once), {"101.01.0001": D("1000"), "120.01.0001": D("-1000")})
        CekSenetService.bankaya_ver(c1, tur="TAHSILE", banka_hesabi_id=banka, tarih=TARIH)
        self.assertEqual(self._fark(once), {"101.02.0001": D("1000"), "120.01.0001": D("-1000")})
        CekSenetService.tahsil_et(c1, finans_hesap_id=banka, tarih=TARIH)
        self.assertEqual(self._fark(once), {"102.01.0001": D("1000"), "120.01.0001": D("-1000")})

        c2 = evrak("ALINAN", "CEK", "R-C2", "500", self.musteri_id)
        CekSenetService.bankaya_ver(c2, tur="TEMINATA", banka_hesabi_id=banka, tarih=TARIH)
        s1 = evrak("ALINAN", "SENET", "R-S1", "300", self.musteri_id)
        CekSenetService.bankaya_ver(s1, tur="TAHSILE", banka_hesabi_id=banka, tarih=TARIH)
        s2 = evrak("ALINAN", "SENET", "R-S2", "200", self.musteri_id)
        CekSenetService.bankaya_ver(s2, tur="TEMINATA", banka_hesabi_id=banka, tarih=TARIH)
        evrak("ALINAN", "SENET", "R-S3", "100", self.musteri_id)
        v1 = evrak("VERILEN", "CEK", "R-V1", "700", self.tedarikci_id)
        evrak("VERILEN", "SENET", "R-V2", "400", self.tedarikci_id)
        ara = {"102.01.0001": D("1000"), "101.03.0001": D("500"), "121.02.0001": D("300"),
               "121.03.0001": D("200"), "121.01.0001": D("100"), "120.01.0001": D("-2100"),
               "320.01.0001": D("1100"), "103.01.0001": D("-700"), "321.01.0001": D("-400")}
        self.assertEqual(self._fark(once), ara)
        CekSenetService.ode(v1, finans_hesap_id=banka, tarih=TARIH)
        ara.update({"103.01.0001": D("0"), "102.01.0001": D("300")})
        self.assertEqual(self._fark(once), {k: v for k, v in ara.items() if v})

        # Tekrar muhasebeleştirme mükerrer fiş üretmez; evrak iptali ters kayıt
        from database.models.cek_senet import CekSenetHareket

        with get_session() as s:
            hareketler = [int(h) for h in s.scalars(select(CekSenetHareket.id).where(
                CekSenetHareket.muhasebe_fisi_id.is_not(None) | CekSenetHareket.id.is_not(None)))]
        for hid in hareketler:
            d = self._durum("cek_senet", hid)
            if d and d.get("durum") == BELGE_MUHASEBELESTIRILDI:
                self._servis().muhasebelestir([self._durum_id("cek_senet", hid)])
                self.assertEqual(self._kaynak_fis_sayisi("cek_senet_hareketi", hid), 1)
        self.assertEqual(self._fark(once), {k: v for k, v in ara.items() if v})
        c3 = evrak("ALINAN", "CEK", "R-C3", "250", self.musteri_id)
        ara2 = self._tutarli()
        CekSenetService.iptal(c3, aciklama="Yanlış giriş")
        self.assertEqual(self._fark(ara2), {"101.01.0001": D("-250"), "120.01.0001": D("250")})


if __name__ == "__main__":
    unittest.main()
