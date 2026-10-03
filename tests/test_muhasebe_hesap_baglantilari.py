"""Muhasebe hesap bağlantıları: kur farkı, kart bazında kasa/banka hesabı, kredi masraf hesapları (780.01.0004-0008),
senet aşamaları, çek/senet iadesi, finans ↔ muhasebe bakiye karşılaştırması, ana hesap engeli ve eşleme geçmişi.

Her akışta: borç = alacak, doğru hesap, kaynak belge bağlantısı, iptal/tekrarda mükerrer fiş yok.
Yalıtılmış geçici veritabanında çalışır.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sqlalchemy import select  # noqa: E402

import database.models.doviz  # noqa: E402,F401
import test_muhasebelestirme_finans_akislari as tak  # noqa: E402
import test_muhasebelestirme_finans_ayarlari as tfa  # noqa: E402
from database.database import get_session  # noqa: E402
from database.models.genel_muhasebe import (  # noqa: E402
    BELGE_BEKLIYOR,
    BELGE_INCELEME,
    BELGE_IPTAL,
    BELGE_MUHASEBELESTIRILDI,
)

TARIH = tfa.TARIH
D = Decimal

for _anahtar, _hesap in {
    "kur_farki_geliri": ("646.01.0001", "Kambiyo Karları", "Gelir"),
    "kur_farki_gideri": ("656.01.0001", "Kambiyo Zararları", "Gider"),
    "kredi_komisyon_gideri": ("780.01.0004", "Kredi Komisyon Giderleri", "Gider"),
    "kredi_sigorta_gideri": ("780.01.0005", "Kredi Sigorta Giderleri", "Gider"),
    "kredi_dosya_masrafi": ("780.01.0006", "Kredi Dosya Masrafları", "Gider"),
    "kredi_gecikme_faizi": ("780.01.0007", "Kredi Gecikme Faizleri", "Gider"),
    "kredi_diger_finansman": ("780.01.0008", "Diğer Finansman Giderleri", "Gider"),
    "senet_portfoy": ("121.01.0001", "Portföydeki Senetler", "Aktif"),
    "senet_tahsilde": ("121.02.0001", "Tahsile Verilen Senetler", "Aktif"),
    "borc_senetleri": ("321.01.0001", "Borç Senetleri", "Pasif"),
}.items():
    tfa.EK_HESAPLAR.setdefault(_anahtar, _hesap)


class _Temel(tak._Akis):
    def _hesap_ac(self, kod, ad, tur="Aktif") -> int:
        from database.models.genel_muhasebe import HesapPlani

        with get_session() as s:
            h = s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == kod))
            if h is None:
                h = HesapPlani(firma_id=self.firma_id, hesap_kodu=kod, hesap_adi=ad, hesap_seviyesi=3,
                               hesap_turu=tur, borc_toplam=0, alacak_toplam=0, aktif=True)
                s.add(h)
                s.flush()
            return int(h.id)

    @staticmethod
    def _gecmis(kayit_turu) -> list:
        from database.models.genel_muhasebe import MuhasebeIslemGecmisi

        with get_session() as s:
            return list(s.scalars(select(MuhasebeIslemGecmisi).where(
                MuhasebeIslemGecmisi.kayit_turu == kayit_turu).order_by(MuhasebeIslemGecmisi.id)).all())

    def _kaynak_fisi(self, fis_id) -> tuple[str, int]:
        k = self._servis().fis_kaynagi(fis_id)
        return k["evrak_turu"], int(k["kaynak_id"])


# ====================================================================== kur farkı
class KurFarkiTest(_Temel):
    def _kur(self, gun: date, deger: str):
        from database.doviz_service import DovizService

        DovizService.kur_kaydet(gun, "USD", D(deger), D(deger), D(deger), D(deger), "MANUEL")

    def _satis(self, tahsilatlar: list[tuple[str, date]], kur="30") -> int:
        """USD, döviz sabit, 10 × 200 TL + %20 KDV = 2.400 TL (80 USD @30); fatura içi TL tahsilatlar."""
        from database.satis_faturasi_service import SatisFaturasiService

        self._kasa()
        f = SatisFaturasiService.kaydet(
            {"fatura_tarihi": TARIH, "vade_tarihi": TARIH, "cari_id": self.musteri_id,
             "depo": "ANA DEPO", "odeme_tutari": D("0"), "sales_person_id": 1, "para_birimi": "USD",
             "kur": D(kur), "kur_tarihi": TARIH, "borc_esasi": "DOVIZ_SABIT", "doviz_ara_toplam": D("66.67")},
            [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": D("10"), "birim": "Adet",
              "birim_fiyat": D("200"), "iskonto_orani": D("0"), "kdv_orani": D("20")}],
            tahsilat_verileri=[{"tutar": D(t), "odeme_sekli": "NAKİT / KASA", "hesap": "Merkez Kasa",
                                "tahsilat_tarihi": g} for t, g in tahsilatlar],
        )
        SatisFaturasiService.onayla(int(f.id))
        return int(f.id)

    @staticmethod
    def _kayitlar(fatura_id, etkin=True):
        from database.kur_farki_service import KurFarkiService

        with get_session() as s:
            return KurFarkiService.kaynak_kayitlari(s, "satis_faturasi", fatura_id, etkin=etkin)

    def _hazir(self, yontem="otomatik"):
        self._ayar(yontem)
        self._alis("U001", "100", "100", "LOT-A")
        self._hesap_bagla("kur_farki_geliri", "kur_farki_gideri")

    def test_kismi_tahsilat_gelir_iki_kayit_tek_fis_tekrar_yok_iptal_ters(self):
        from database.satis_faturasi_service import SatisFaturasiService

        self._hazir()
        self._kur(TARIH, "32")
        self._kur(TARIH + timedelta(days=5), "33")
        once = self._tutarli()
        fid = self._satis([("960", TARIH), ("660", TARIH + timedelta(days=5))])
        kayitlar = self._kayitlar(fid)
        self.assertEqual(len(kayitlar), 2)
        k1, k2 = kayitlar
        # 960 TL / 32 = 30 USD; kaynak 30 × 30 = 900 → +60 ; 660 / 33 = 20 USD; kaynak 600 → +60
        self.assertEqual((D(str(k1.doviz_tutar)), D(str(k1.kaynak_tl)), D(str(k1.odeme_tl)), D(str(k1.kur_farki))),
                         (D("30.00"), D("900.00"), D("960.00"), D("60.00")))
        self.assertEqual(D(str(k2.kur_farki)), D("60.00"))
        self.assertEqual((k1.kaynak_evrak, k1.kaynak_id, k1.kapatma_turu), ("satis_faturasi", fid,
                                                                            "SATIS_FATURA_TAHSILATI"))
        for k in kayitlar:
            d = self._durum("kur_farki", k.id)
            self.assertEqual(d["durum"], BELGE_MUHASEBELESTIRILDI, d)
            self.assertEqual(self._kaynak_fisi(d["fis_id"]), ("kur_farki", int(k.id)))
            self._tek_fis("kur_farki", k.id, self._durum_id("kur_farki", k.id))
        fark = self._fark(once)
        self.assertEqual(fark["646.01.0001"], D("-120"))
        self.assertNotIn("656.01.0001", fark)
        # Tahsilat kaydına da yazılır; eski hizmet hareketi tutarı aynı
        with get_session() as s:
            from database.models.satis_faturasi import SatisFaturasiTahsilati

            ths = s.scalars(select(SatisFaturasiTahsilati).where(SatisFaturasiTahsilati.fatura_id == fid)
                            .order_by(SatisFaturasiTahsilati.id)).all()
            self.assertEqual([D(str(t.kur_farki)) for t in ths], [D("60.00"), D("60.00")])

        # Aynı kapatma tekrar işlenirse yeni kayıt/fiş yok
        from database.kur_farki_service import KurFarkiService
        from database.models.satis_faturasi import SatisFaturasi

        fis_sayisi = self._fis_sayisi("kur_farki")
        with get_session() as s:
            f = s.get(SatisFaturasi, fid)
            KurFarkiService.satis_fatura_tahsilati(s, f, f.tahsilatlar[0], D("32"))
        self.assertEqual(len(self._kayitlar(fid)), 2)
        self.assertEqual(self._fis_sayisi("kur_farki"), fis_sayisi)

        # Fatura iptali: kur farkı kayıtları iptal, fişler ters kayıtla kapanır
        SatisFaturasiService.iptal_et(fid, "Test iptal")
        self.assertEqual(self._kayitlar(fid), [])
        for k in kayitlar:
            self.assertEqual(self._durum("kur_farki", k.id)["durum"], BELGE_IPTAL)
        self.assertEqual(self._fis_sayisi("kur_farki"), 0, "iptal edilen fişin kaynağı serbest kalır")
        self.assertGreaterEqual(self._fis_sayisi(None, "İptal"), 2)
        self.assertNotIn("646.01.0001", self._fark(once))
        from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

        toplam = self._fis_sayisi()
        MuhasebeEntegrasyonService.kur_farki_iptal(int(k1.id), "tekrar")
        self.assertEqual(self._fis_sayisi(), toplam, "ikinci iptal ters kayıt üretmez")

    def test_gider_yonu_ve_sonradan_bekler_sonra_tek_fis(self):
        self._hazir("sonradan")
        self._kur(TARIH, "25")
        once = self._tutarli()
        fid = self._satis([("960", TARIH)])
        (k,) = self._kayitlar(fid)
        # 960 / 25 = 38.40 USD; kaynak 38.40 × 30 = 1.152 → −192 (gider)
        self.assertEqual(D(str(k.kur_farki)), D("-192.00"))
        self.assertEqual(self._durum("kur_farki", k.id)["durum"], BELGE_BEKLIYOR)
        self.assertEqual(self._fis_sayisi("kur_farki"), 0)
        did = self._durum_id("kur_farki", k.id)
        self.assertEqual(self._servis().muhasebelestir([did])["basarili"], 1)
        self._tek_fis("kur_farki", k.id, did)
        fark = self._fark(once)
        self.assertEqual(fark.get("656.01.0001"), D("192"))
        self.assertNotIn("646.01.0001", fark)

    def test_kur_yoksa_inceleme_fatura_kesinlesir_fark_tahmin_edilmez(self):
        self._hazir()
        once = self._tutarli()
        fid = self._satis([("960", TARIH)])
        (k,) = self._kayitlar(fid)
        self.assertEqual(k.durum, "INCELEME")
        self.assertEqual(D(str(k.kur_farki)), D("0"))
        d = self._durum_kaydi("kur_farki", k.id)
        self.assertEqual(d.durum, BELGE_INCELEME)
        self.assertIn("kur", d.aciklama.lower())
        self.assertEqual(self._fis_sayisi("kur_farki"), 0)
        self.assertEqual(self._durum("satis_faturasi", fid)["durum"], BELGE_MUHASEBELESTIRILDI)
        self.assertNotIn("646.01.0001", self._fark(once))

    def test_eslesme_eksik_inceleme_baglaninca_tek_fis(self):
        from database.models.genel_muhasebe import MuhasebeHesapEsleme

        self._hazir()
        with get_session() as s:
            for e in s.scalars(select(MuhasebeHesapEsleme).where(
                    MuhasebeHesapEsleme.anahtar == "kur_farki_geliri")).all():
                s.delete(e)
        self._kur(TARIH, "32")
        fid = self._satis([("960", TARIH)])
        (k,) = self._kayitlar(fid)
        d = self._durum_kaydi("kur_farki", k.id)
        self.assertEqual(d.durum, BELGE_INCELEME)
        self.assertIn("kur_farki_geliri", d.aciklama)
        self._hesap_bagla("kur_farki_geliri")
        self.assertEqual(self._servis().muhasebelestir([d.id])["basarili"], 1)
        self._tek_fis("kur_farki", k.id, d.id)

    def test_alis_yonu_servis_kismi_kapatma_asim_inceleme_iptal_ters(self):
        from database.kur_farki_service import YON_ALIS, KurFarkiService

        self._hazir()
        once = self._tutarli()

        def kapat(kid, doviz, kur):
            with get_session() as s:
                return int(KurFarkiService.kaydet(
                    s, yon=YON_ALIS, cari_id=self.tedarikci_id, kaynak_evrak="alis_faturasi", kaynak_id=1,
                    kaynak_belge_no="AF-USD-1", kapatma_turu="TEST_ODEME", kapatma_id=kid,
                    kapatma_belge_no=f"AF-USD-1/O{kid}", tarih=TARIH, para_birimi="USD", doviz_tutar=doviz,
                    kaynak_kur="30", odeme_kuru=kur, doviz_borc="100").id)

        k1 = kapat(1, "60", "32")   # borç 1.800 TL, ödenen 1.920 → −120 gider
        k2 = kapat(2, "30", "29")   # borç 900, ödenen 870 → +30 gelir
        self.assertEqual(self._fark(once), {"656.01.0001": D("120"), "646.01.0001": D("-30"),
                                            "320.01.0001": D("-90")})
        k3 = kapat(3, "20", "30")   # toplam 110 USD > 100 → inceleme
        d3 = self._durum_kaydi("kur_farki", k3)
        self.assertEqual(d3.durum, BELGE_INCELEME)
        self.assertIn("aşıyor", d3.aciklama)
        with get_session() as s:
            KurFarkiService.kapatma_iptal(s, "TEST_ODEME", 1, "ödeme iptal")
        self.assertEqual(self._durum("kur_farki", k1)["durum"], BELGE_IPTAL)
        self.assertEqual(self._fark(once), {"646.01.0001": D("-30"), "320.01.0001": D("30")})
        self._tek_fis("kur_farki", k2, self._durum_id("kur_farki", k2))

    def test_kur_farki_baska_fiste_varsa_ikinci_kez_kaydedilmez(self):
        from database.kur_farki_service import YON_SATIS, KurFarkiService
        from database.muhasebe_service import MuhasebeFisService

        self._hazir()
        h120, h646 = self._hesap_ac("120.01.0001", "Alıcılar"), self._hesap_ac("646.01.0001", "Kambiyo", "Gelir")
        MuhasebeFisService.kaydet({"fis_turu": "Mahsup Fişi", "fis_tarihi": TARIH, "durum": "Kesinleşmiş",
                                   "belge_no": "SF-ELLE", "aciklama": "Elle kur farkı",
                                   "satirlar": [{"hesap_id": h120, "borc": "50", "belge_no": "SF-ELLE"},
                                                {"hesap_id": h646, "alacak": "50", "belge_no": "SF-ELLE"}]})
        once = self._tutarli()
        with get_session() as s:
            kid = int(KurFarkiService.kaydet(
                s, yon=YON_SATIS, cari_id=self.musteri_id, kaynak_evrak="satis_faturasi", kaynak_id=1,
                kaynak_belge_no="SF-ELLE", kapatma_turu="TEST_TAHSILAT", kapatma_id=1,
                kapatma_belge_no="SF-ELLE/T1", tarih=TARIH, para_birimi="USD", doviz_tutar="10",
                kaynak_kur="30", odeme_kuru="35").id)
        d = self._durum_kaydi("kur_farki", kid)
        self.assertEqual(d.durum, BELGE_INCELEME)
        self.assertIn("SF-ELLE", d.aciklama)
        self.assertEqual(self._fis_sayisi("kur_farki"), 0)
        self.assertEqual(self._fark(once), {})


# ====================================================================== kredi masraf hesapları
class KrediMasrafHesaplariTest(_Temel):
    _kredi_hazirla = tak.KrediOdemeAkisTest._kredi_hazirla
    _odeme_id = staticmethod(tak.KrediOdemeAkisTest._odeme_id)

    MASRAF = {"komisyon": "10", "sigorta": "20", "dosya_masrafi": "30", "gecikme_faizi": "40",
              "diger_masraflar": "50"}
    ETKI = {"300.01.0002": D("6000"), "400.01.0001": D("4000"), "780.01.0004": D("10"), "780.01.0005": D("20"),
            "780.01.0006": D("30"), "780.01.0007": D("40"), "780.01.0008": D("50"), "102.01.0001": D("-10150")}

    def test_erken_kapama_bes_masraf_kalemi_kendi_hesabina_tek_fis_iptal_ters(self):
        from database.banka_kredi_service import BankaKrediService

        self._hesap_bagla("kredi_komisyon_gideri", "kredi_sigorta_gideri", "kredi_dosya_masrafi",
                          "kredi_gecikme_faizi", "kredi_diger_finansman")
        kart, kid, _ = self._kredi_hazirla()
        once = self._tutarli()
        r = BankaKrediService.erken_kapat(kid, odeme_tarihi=TARIH + timedelta(days=20),
                                          banka_hesap_id=kart["MEVDUAT"], masraflar=self.MASRAF)
        oid = self._odeme_id(r["odeme_belge_no"])
        d = self._durum("banka_kredi_odeme", oid)
        self.assertEqual(d["durum"], BELGE_MUHASEBELESTIRILDI, d)
        self.assertEqual(self._kaynak_fisi(d["fis_id"]), ("banka_kredi_odeme", oid))
        self.assertEqual(self._fark(once), self.ETKI)
        self._tek_fis("banka_kredi_odeme", oid, self._durum_id("banka_kredi_odeme", oid))
        toplam = self._fis_sayisi()
        BankaKrediService.odeme_iptal(odeme_id=oid, neden="Yanlış dekont")
        self.assertEqual(self._fark(once), {})
        self.assertEqual(self._fis_sayisi(), toplam + 1)

    def test_eksik_masraf_hesabi_inceleme_baglaninca_tek_fis(self):
        from database.banka_kredi_service import BankaKrediService

        self._hesap_bagla("kredi_komisyon_gideri", "kredi_sigorta_gideri", "kredi_dosya_masrafi",
                          "kredi_gecikme_faizi")
        kart, kid, _ = self._kredi_hazirla()
        once = self._tutarli()
        r = BankaKrediService.erken_kapat(kid, odeme_tarihi=TARIH + timedelta(days=20),
                                          banka_hesap_id=kart["MEVDUAT"], masraflar=self.MASRAF)
        d = self._durum_kaydi("banka_kredi_odeme", self._odeme_id(r["odeme_belge_no"]))
        self.assertEqual(d.durum, BELGE_INCELEME)
        self.assertIn("kredi_diger_finansman", d.aciklama)
        self.assertEqual(self._fark(once), {})
        self._hesap_bagla("kredi_diger_finansman")
        self.assertEqual(self._servis().muhasebelestir([d.id])["basarili"], 1)
        self._servis().muhasebelestir([d.id])
        self.assertEqual(self._fark(once), self.ETKI)


# ====================================================================== senet aşamaları + iade
class SenetVeIadeTest(_Temel):
    _cek = tfa.CekSenetTest._cek
    _hareket = tfa.CekSenetTest._hareket

    def _senet(self, no, yon="ALINAN", tutar="1000") -> int:
        from database.cek_senet_service import CekSenetService
        from database.models.cek_senet import CekSenetEvrak

        CekSenetService.olustur({"islem_yonu": yon, "basit_tur": "SENET", "evrak_no": no,
                                 "duzenleme_tarihi": TARIH, "vade_tarihi": TARIH + timedelta(days=30),
                                 "tutar": tutar,
                                 "cari_id": self.musteri_id if yon == "ALINAN" else self.tedarikci_id})
        with get_session() as s:
            return int(s.scalar(select(CekSenetEvrak.id).where(CekSenetEvrak.evrak_no == no)))

    def _asama_tek_fis(self, eid, tur):
        h = self._hareket(eid, tur)
        d = self._durum("cek_senet", h)
        self.assertEqual(d["durum"], BELGE_MUHASEBELESTIRILDI, (tur, d))
        self.assertEqual(self._kaynak_fisi(d["fis_id"]), ("cek_senet", h))
        self._tek_fis("cek_senet_hareketi", h, self._durum_id("cek_senet", h))
        return h

    def test_alinan_senet_portfoy_tahsile_tahsil_her_asama_tek_fis(self):
        from database.cek_senet_service import CekSenetService

        self._ayar("otomatik")
        self._finans_ayar(cek_senet__KAYIT_ALINAN="evet", cek_senet__BANKAYA_TAHSILE="evet",
                          cek_senet__TAHSIL="evet")
        self._hesap_bagla("senet_portfoy", "senet_tahsilde")
        banka = self._banka()
        once = self._tutarli()
        e = self._senet("S-1")
        self._asama_tek_fis(e, "KAYIT")
        self.assertEqual(self._fark(once), {"121.01.0001": D("1000"), "120.01.0001": D("-1000")})
        CekSenetService.bankaya_ver(e, tur="TAHSILE", banka_hesabi_id=banka, tarih=TARIH)
        self._asama_tek_fis(e, "BANKAYA_TAHSILE")
        self.assertEqual(self._fark(once), {"121.02.0001": D("1000"), "120.01.0001": D("-1000")})
        CekSenetService.tahsil_et(e, finans_hesap_id=banka, tarih=TARIH + timedelta(days=30))
        self._asama_tek_fis(e, "TAHSIL")
        self.assertEqual(self._fark(once), {"102.01.0001": D("1000"), "120.01.0001": D("-1000")})

    def test_verilen_senet_kayit_odeme_tek_fis(self):
        from database.cek_senet_service import CekSenetService

        self._ayar("otomatik")
        self._finans_ayar(cek_senet__KAYIT_VERILEN="evet", cek_senet__ODEME="evet")
        self._hesap_bagla("borc_senetleri")
        kasa = self._kasa()
        once = self._tutarli()
        e = self._senet("VS-1", "VERILEN", "700")
        self._asama_tek_fis(e, "KAYIT")
        self.assertEqual(self._fark(once), {"320.01.0001": D("700"), "321.01.0001": D("-700")})
        CekSenetService.ode(e, finans_hesap_id=kasa, tarih=TARIH + timedelta(days=30))
        self._asama_tek_fis(e, "ODEME")
        self.assertEqual(self._fark(once), {"320.01.0001": D("700"), "100.01.0001": D("-700")})

    def test_iade_asamasi_alinan_cek_ve_verilen_senet_secenek_yoksa_inceleme(self):
        from database.cek_senet_service import CekSenetService
        from database.muhasebe_finans_ayarlari import AYAR_YERI

        self._ayar("otomatik")
        self._finans_ayar(cek_senet__KAYIT_ALINAN="evet", cek_senet__KAYIT_VERILEN="evet")
        self._hesap_bagla("cek_portfoy", "borc_senetleri")
        once = self._tutarli()
        e1, _ = self._cek("C-IADE", "1000")
        e2 = self._senet("VS-IADE", "VERILEN", "400")
        CekSenetService.iade_et(e1, tarih=TARIH)
        h1 = self._hareket(e1, "IADE")
        d1 = self._durum_kaydi("cek_senet", h1)
        self.assertEqual(d1.durum, BELGE_INCELEME)
        self.assertIn("İade", d1.aciklama)
        self.assertIn(AYAR_YERI, d1.aciklama)

        self._finans_ayar(cek_senet__IADE="evet")
        self.assertEqual(self._servis().muhasebelestir([d1.id])["basarili"], 1)
        self._tek_fis("cek_senet_hareketi", h1, d1.id)
        CekSenetService.iade_et(e2, tarih=TARIH)
        self._asama_tek_fis(e2, "IADE")
        # İade sonrası çek ve senet hesapları kapanır; cari bakiyeler eski hâline döner
        self.assertEqual(self._fark(once), {})


# ====================================================================== kart bazında kasa / banka hesabı
class KartHesabiTest(_Temel):
    def _sube_kasa(self) -> int:
        from database.models.finans import FinansHesabi

        with get_session() as s:
            h = FinansHesabi(hesap_adi="Şube Kasa", hesap_turu="KASA", acilis_bakiyesi=D("1000"), aktif=True)
            s.add(h)
            s.flush()
            return int(h.id)

    def test_kasa_karti_hesabi_fise_yansir_digeri_firma_varsayilani_gecmis_yazilir(self):
        from database import muhasebe_finans_ayarlari as fa
        from database.finans_service import FinansService
        from database.models.hizmet import HizmetKarti

        self._ayar("otomatik")
        sube = self._sube_kasa()
        h2 = self._hesap_ac("100.01.0002", "Şube Kasası")
        fa.kart_hesabi_kaydet(sube, h2)
        with self.assertRaises(ValueError):
            fa.kart_hesabi_kaydet(sube, self._hesap_ac("600.01.0001", "Yurtiçi Satışlar", "Gelir"))
        once = self._tutarli()
        with get_session() as s:
            hizmet_id = s.scalar(select(HizmetKarti.id).where(HizmetKarti.hizmet_kodu == "NAKLIYE"))
        g1 = FinansService.gider_fisi_kaydet({"tarih": TARIH, "finans_hesap_id": sube, "hizmet_id": hizmet_id,
                                              "tutar": D("300"), "aciklama": "Şube nakliye"})
        g2 = FinansService.gider_fisi_kaydet({"tarih": TARIH, "finans_hesap_id": self._kasa(),
                                              "hizmet_id": hizmet_id, "tutar": D("200"), "aciklama": "Merkez"})
        fark = self._fark(once)
        self.assertEqual(fark["100.01.0002"], D("-300"))
        self.assertEqual(fark["100.01.0001"], D("-200"))
        for g in (g1, g2):
            self._tek_fis("gider_fisi", int(g.id), self._durum_id("gider_fisi", int(g.id)))

        satirlar = {k["hesap_adi"]: k for k in fa.kart_hesaplari()}
        self.assertEqual(satirlar["Şube Kasa"]["durum"], "Kart hesabı")
        self.assertTrue(satirlar["Merkez Kasa"]["durum"].startswith("Firma varsayılanı"))
        gecmis = self._gecmis("finans_kart_hesabi")
        self.assertEqual(len(gecmis), 1)
        self.assertIn("100.01.0002", gecmis[0].detay)
        self.assertEqual(gecmis[0].kullanici_adi, "admin")

    def test_banka_karti_hesabi_yoksa_ve_varsayilan_yoksa_inceleme_secilince_tek_fis(self):
        from database import muhasebe_finans_ayarlari as fa
        from database.finans_service import FinansService
        from database.models.finans import FinansEvrakKimligi
        from database.models.genel_muhasebe import MuhasebeHesapEsleme
        from database.muhasebe_entegrasyon import KART_HESAP_YERI

        self._ayar("otomatik")
        with get_session() as s:
            for e in s.scalars(select(MuhasebeHesapEsleme).where(MuhasebeHesapEsleme.anahtar == "banka")).all():
                s.delete(e)
        akbank = self._banka_karti("Akbank")
        garanti = self._banka_karti("Garanti")
        h_ak = self._hesap_ac("102.01.0002", "Akbank TL Vadesiz")
        fa.kart_hesabi_kaydet(akbank["MEVDUAT"], h_ak)
        once = self._tutarli()

        def havale(hesap, tutar):
            no = FinansService.alinan_havale(hesap, TARIH, D(tutar), cari_id=self.musteri_id)
            with get_session() as s:
                return int(s.scalar(select(FinansEvrakKimligi.id).where(FinansEvrakKimligi.belge_no == no)))

        k1 = havale(akbank["MEVDUAT"], "250")
        self.assertEqual(self._durum("banka_havale", k1)["durum"], BELGE_MUHASEBELESTIRILDI)
        self.assertEqual(self._fark(once), {"102.01.0002": D("250"), "120.01.0001": D("-250")})

        k2 = havale(garanti["MEVDUAT"], "100")
        d2 = self._durum_kaydi("banka_havale", k2)
        self.assertEqual(d2.durum, BELGE_INCELEME)
        self.assertIn("muhasebe hesabı seçilmemiş", d2.aciklama)
        self.assertIn(KART_HESAP_YERI, d2.aciklama)
        satir = next(k for k in fa.kart_hesaplari(banka_karti_id=garanti["kart"]) if k["alt_tur"] == "MEVDUAT")
        self.assertEqual(satir["durum"], "İnceleme gerekiyor")

        fa.kart_hesabi_kaydet(garanti["MEVDUAT"], self._hesap_ac("102.01.0003", "Garanti TL Vadesiz"))
        self.assertEqual(self._servis().muhasebelestir([d2.id])["basarili"], 1)
        self._tek_fis("banka_havale", k2, d2.id)
        self.assertEqual(self._fark(once), {"102.01.0002": D("250"), "102.01.0003": D("100"),
                                            "120.01.0001": D("-350")})

    def test_pos_karti_valor_ve_komisyon_hesabi_karttan(self):
        from database import muhasebe_finans_ayarlari as fa
        from database.finans_service import FinansService

        self._ayar("otomatik")
        kart = self._banka_karti()
        h_valor = self._hesap_ac("108.01.0002", "Akbank POS Valör")
        h_kom = self._hesap_ac("653.01.0002", "Akbank POS Komisyon", "Gider")
        fa.kart_hesabi_kaydet(kart["POS"], h_valor, komisyon_hesap_id=h_kom)
        once = self._tutarli()
        r = FinansService.pos_tahsilat(kart["kart"], TARIH, D("1000"), cari_id=self.musteri_id)
        self.assertEqual(self._durum("pos_tahsilat", r["kayit_id"])["durum"], BELGE_MUHASEBELESTIRILDI)
        self.assertEqual(self._fark(once), {"108.01.0002": D("980"), "653.01.0002": D("20"),
                                            "120.01.0001": D("-1000")})


# ====================================================================== mutabakat, ana hesap engeli, geçmiş
class MutabakatVeEngelTest(_Temel):
    def test_finans_bakiyesi_muhasebe_bakiyesi_karsilastirmasi(self):
        from database import muhasebe_finans_ayarlari as fa
        from database.finans_service import FinansService

        self._ayar("otomatik")
        kart = self._banka_karti()
        fa.kart_hesabi_kaydet(kart["MEVDUAT"], self._hesap_ac("102.01.0002", "Akbank TL Vadesiz"))
        FinansService.alinan_havale(kart["MEVDUAT"], TARIH, D("400"), cari_id=self.musteri_id)
        self._gider_fisi("150")
        satirlar = {r["hesap_kodu"]: r for r in fa.finans_muhasebe_mutabakati()}
        banka = satirlar["102.01.0002"]
        self.assertEqual((banka["finans_bakiye"], banka["muhasebe_bakiye"], banka["fark"]),
                         (D("400"), D("400"), D("0")))
        self.assertEqual(banka["kartlar"], ["Akbank MEVDUAT"])
        # Merkez Kasa açılış bakiyesi (100.000) muhasebede yok: fark açılış kadar, kendiliğinden düzeltilmez
        kasa = satirlar["100.01.0001"]
        self.assertEqual(kasa["muhasebe_bakiye"], D("-150"))
        self.assertEqual(kasa["fark"], D("100000"))

    def test_ana_hesaba_fis_esleme_ve_kart_hesabi_engellenir(self):
        from database import muhasebe_finans_ayarlari as fa
        from database.muhasebe_entegrasyon import HesapEslemeService
        from database.muhasebe_service import MuhasebeFisService

        self._ayar("otomatik")
        ana = self._hesap_ac("100", "KASA")
        alt = self._hesap_ac("120.01.0001", "Alıcılar")
        with self.assertRaises(ValueError) as cm:
            MuhasebeFisService.kaydet({"fis_turu": "Mahsup Fişi", "fis_tarihi": TARIH, "durum": "Kesinleşmiş",
                                       "satirlar": [{"hesap_id": ana, "borc": "10"},
                                                    {"hesap_id": alt, "alacak": "10"}]})
        self.assertIn("Bu hesaba fiş yazılamaz", str(cm.exception))
        with self.assertRaises(ValueError):
            HesapEslemeService.kaydet("kasa", ana)
        with self.assertRaises(ValueError):
            fa.kart_hesabi_kaydet(self._kasa(), ana)
        self.assertEqual(self._gecmis("finans_kart_hesabi"), [])

    def test_eslesme_degisikligi_gecmise_onceki_ve_yeni_ile_yazilir(self):
        from database.muhasebe_entegrasyon import HesapEslemeService

        self._ayar("otomatik")
        yeni = self._hesap_ac("100.01.0002", "Merkez Kasa 2")
        once = len(self._gecmis("esleme"))
        HesapEslemeService.kaydet("kasa", yeni)
        HesapEslemeService.kaydet("kasa", yeni)  # değişiklik yok: kayıt yok
        gecmis = self._gecmis("esleme")[once:]
        self.assertEqual(len(gecmis), 1)
        self.assertIn("100.01.0001", gecmis[0].detay)
        self.assertIn("100.01.0002", gecmis[0].detay)
        self.assertEqual(gecmis[0].kullanici_adi, "admin")
        self.assertIsNotNone(gecmis[0].tarih)


if __name__ == "__main__":
    import unittest

    unittest.main()
