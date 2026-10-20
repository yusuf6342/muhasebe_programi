"""Cari kartları talimatı (15.10.2026): genel risk, vade bağlantısı, grup silme, son kodlar,
liste bakiyeleri, yetkili alanları ve fotoğraflar — hesap ve kayıt denetimleri.

Yalnız geçici test veritabanı kullanılır; gerçek firma verisine dokunulmaz.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from database import cari_risk_service as crs
from database.cari_service import CariService
from database.database import get_session
from database.models.cari import Cari, CariYetkili, CariYetkiliDepartman, CariYetkiliGorev
from database.turkce_normalize import turkce_normalize
from tests import test_tahsilat_makbuzu as _servis_testi
from tests.test_cari_risk_vade_tahsilat import Temel, _evrak, _kalem

D = Decimal


class GenelRiskHesapTest(unittest.TestCase):
    HAMLAR = {
        crs.BILESEN_ACIK: D("100000"),
        crs.BILESEN_CIRO_CEK: D("40000"),
        crs.BILESEN_DIGER_CEK: D("60000"),
        crs.BILESEN_SENET: D("20000"),
    }

    def test_talimat_ornegi(self):
        oranlar = {crs.BILESEN_CIRO_CEK: D("25"), crs.BILESEN_DIGER_CEK: D("100"), crs.BILESEN_SENET: D("50")}
        sonuc = crs.genel_risk_hesapla(self.HAMLAR, oranlar)
        self.assertEqual(sonuc["brut"], D("220000.00"))
        self.assertEqual(sonuc["genel_risk"], D("180000.00"))
        risk = {b["bilesen"]: b["risk"] for b in sonuc["bilesenler"]}
        self.assertEqual(risk[crs.BILESEN_ACIK], D("100000.00"))
        self.assertEqual(risk[crs.BILESEN_CIRO_CEK], D("10000.00"))
        self.assertEqual(risk[crs.BILESEN_DIGER_CEK], D("60000.00"))
        self.assertEqual(risk[crs.BILESEN_SENET], D("10000.00"))

    def test_tum_oranlar_yuz_ise_brut_ile_ayni(self):
        sonuc = crs.genel_risk_hesapla(self.HAMLAR, {b: D("100") for b in crs.RISK_ORANI_ALANI})
        self.assertEqual(sonuc["genel_risk"], D("220000.00"))
        self.assertEqual(sonuc["brut"], sonuc["genel_risk"])

    def test_sifir_oran_acik_hesap_tam_kalir(self):
        sonuc = crs.genel_risk_hesapla(self.HAMLAR, {b: D("0") for b in crs.RISK_ORANI_ALANI})
        self.assertEqual(sonuc["genel_risk"], D("100000.00"))
        self.assertEqual(sonuc["brut"], D("220000.00"))

    def test_kurusa_yuvarlama(self):
        sonuc = crs.genel_risk_hesapla({crs.BILESEN_SENET: D("333.33")}, {crs.BILESEN_SENET: D("33.33")})
        self.assertEqual(sonuc["genel_risk"], D("111.10"))


class RiskOraniDogrulamaTest(unittest.TestCase):
    def test_gecerli_degerler(self):
        self.assertEqual(crs.risk_orani_dogrula("0"), D("0.00"))
        self.assertEqual(crs.risk_orani_dogrula("100"), D("100.00"))
        self.assertEqual(crs.risk_orani_dogrula("25,5"), D("25.50"))
        self.assertEqual(crs.risk_orani_dogrula("%12,34"), D("12.34"))

    def test_gecersiz_degerler(self):
        for ham in ("", "  ", None, "-1", "100,01", "12,345", "abc"):
            with self.subTest(ham=ham), self.assertRaises(ValueError):
                crs.risk_orani_dogrula(ham)


class VadeOranBaglantiTest(unittest.TestCase):
    def test_talimat_ornekleri(self):
        self.assertEqual(crs.vade_oran_bagla(crs.DONEM_AYLIK, "3"), (D("3"), D("36")))
        aylik, yillik = crs.vade_oran_bagla(crs.DONEM_YILLIK, "24")
        self.assertEqual((aylik, yillik), (D("2"), D("24")))
        self.assertEqual(crs.vade_oran_bagla(crs.DONEM_AYLIK, "0"), (D("0"), D("0")))
        self.assertEqual(crs.vade_oran_bagla(crs.DONEM_YILLIK, "0,00"), (D("0"), D("0.00")))

    def test_bos_ve_sifir_ayridir(self):
        self.assertEqual(crs.vade_oran_bagla(crs.DONEM_AYLIK, ""), (None, None))
        self.assertEqual(crs.vade_oran_metni(None), "")
        self.assertEqual(crs.vade_oran_metni(D("0")), "0,0000")

    def test_gecersiz_giris(self):
        for ham in ("-1", "abc"):
            with self.subTest(ham=ham), self.assertRaises(ValueError):
                crs.vade_oran_bagla(crs.DONEM_AYLIK, ham)

    def test_tekrarlanan_degisim_suruklemez(self):
        aylik, yillik = crs.vade_oran_bagla(crs.DONEM_YILLIK, "25")
        self.assertEqual(yillik, D("25"), "ana alan geri yazılmaz")
        self.assertEqual(crs.vade_oran_metni(aylik), "2,0833")
        gorulen = []
        for _ in range(6):
            aylik, yillik = crs.vade_oran_bagla(crs.DONEM_AYLIK, crs.vade_oran_metni(aylik))
            aylik, yillik = crs.vade_oran_bagla(crs.DONEM_YILLIK, crs.vade_oran_metni(yillik))
            gorulen.append((crs.vade_oran_metni(aylik), crs.vade_oran_metni(yillik)))
        self.assertEqual(len(set(gorulen)), 1, f"değerler her turda kaymamalı: {gorulen}")
        aylik, yillik = crs.vade_oran_bagla(crs.DONEM_AYLIK, "3")
        for _ in range(6):
            aylik, yillik = crs.vade_oran_bagla(crs.DONEM_YILLIK, crs.vade_oran_metni(yillik))
            aylik, yillik = crs.vade_oran_bagla(crs.DONEM_AYLIK, crs.vade_oran_metni(aylik))
        self.assertEqual((crs.vade_oran_metni(aylik), crs.vade_oran_metni(yillik)), ("3,0000", "36,0000"))

    def test_tutarlilik(self):
        self.assertTrue(crs.vade_oranlari_tutarli(D("2.0833"), D("25")))
        self.assertTrue(crs.vade_oranlari_tutarli(None, D("25")))
        self.assertFalse(crs.vade_oranlari_tutarli(D("2"), D("30")))


class CariKartVeriTest(Temel):
    # —— Genel risk: kaynak evraklardan ——
    def test_genel_risk_kaynaktan_ve_kart_oranlariyla(self):
        with get_session() as s:
            _kalem(s, self.cid, "FTR-1", date(2026, 1, 1), "100000")
            _evrak(s, self.cid, "C1", "MUSTERI_CEKI", "40000", "CIRO_EDILDI")
            _evrak(s, self.cid, "C2", "MUSTERI_CEKI", "60000", "PORTFOYDE")
            _evrak(s, self.cid, "S1", "MUSTERI_SENEDI", "20000", "CIRO_EDILDI")
        genel = crs.risk_ozeti(self.cid)["genel"]
        self.assertEqual(genel["brut"], D("220000.00"))
        self.assertEqual(genel["genel_risk"], D("220000.00"), "varsayılan oranlar %100")
        ham = {b["bilesen"]: b["ham"] for b in genel["bilesenler"]}
        self.assertEqual(ham[crs.BILESEN_SENET], D("20000.00"), "ciro senet yalnız senetlerde")
        self.assertEqual(ham[crs.BILESEN_CIRO_CEK], D("40000.00"))

        CariService.guncelle(self.cid, {"risk_orani_ciro_cek": "25", "risk_orani_diger_cek": "100",
                                        "risk_orani_senet": "50"})
        genel = crs.risk_ozeti(self.cid)["genel"]
        self.assertEqual(genel["genel_risk"], D("180000.00"))
        self.assertEqual(genel["brut"], D("220000.00"))
        kaynaklar = [k for k in genel["detay"] if k["bilesen"] != crs.BILESEN_ACIK]
        self.assertEqual(len(kaynaklar), 3, "her evrak bir kez")

    def test_bos_risk_orani_kaydedilmez(self):
        with self.assertRaises(ValueError):
            CariService.guncelle(self.cid, {"risk_orani_senet": ""})
        with get_session() as s:
            self.assertEqual(D(str(s.get(Cari, self.cid).risk_orani_senet)), D("100"))

    # —— Grup silme ——
    def test_grup_sil_tasima_tek_islem(self):
        CariService.grup_ekle("TOPTAN")
        CariService.grup_ekle("BAYİ")
        CariService.guncelle(self.cid, {"musteri_grubu": "TOPTAN"})
        bilgi = CariService.grup_kullanimi("TOPTAN")
        self.assertEqual(bilgi["cari_sayisi"], 1)
        self.assertIn("BAYİ", bilgi["hedefler"])
        self.assertNotIn("TOPTAN", bilgi["hedefler"])
        with self.assertRaises(ValueError):
            CariService.grup_sil("TOPTAN")
        with self.assertRaises(ValueError):
            CariService.grup_sil("TOPTAN", "TOPTAN")
        with self.assertRaises(ValueError):
            CariService.grup_sil("TOPTAN", "OLMAYAN GRUP")
        self.assertEqual(CariService.getir(self.cid).musteri_grubu, "TOPTAN", "hata kart grubunu değiştirmez")
        sonuc = CariService.grup_sil("TOPTAN", "BAYİ")
        self.assertEqual(sonuc["tasinan"], 1)
        self.assertEqual(CariService.getir(self.cid).musteri_grubu, "BAYİ")
        self.assertNotIn("TOPTAN", CariService.gruplari_listele())

    def test_kullanilmayan_grup_dogrudan_silinir(self):
        CariService.grup_ekle("GEÇİCİ")
        self.assertEqual(CariService.grup_sil("GEÇİCİ")["tasinan"], 0)
        self.assertNotIn("GEÇİCİ", CariService.gruplari_listele())

    def _grup_garanti(self, ad):
        if ad not in CariService.gruplari_listele():
            CariService.grup_ekle(ad)

    def test_perakende_grubu_tasinarak_silinir_rol_ayari_tasinir(self):
        from database.models.cari import MusteriGrubu
        from hizli_satis_musteri import varsayilan_cari_bul

        self._grup_garanti("PERAKENDE MÜŞTERİ")
        self._grup_garanti("DİĞER")
        with get_session() as s:
            s.add(Cari(cari_kodu="PX1", unvan="Perakende Rol Kartı", cari_turu="Müşteri",
                       musteri_grubu="PERAKENDE MÜŞTERİ", aktif=True))
        bilgi = CariService.grup_kullanimi("PERAKENDE MÜŞTERİ")
        self.assertTrue(bilgi["roller"], "perakende rolü görünür")
        with self.assertRaises(ValueError):
            CariService.grup_sil("PERAKENDE MÜŞTERİ")
        sonuc = CariService.grup_sil("PERAKENDE MÜŞTERİ", "DİĞER")
        self.assertGreaterEqual(sonuc["tasinan"], 1)
        self.assertEqual(CariService.rol_grubu("PERAKENDE_MUSTERI"), "DİĞER")
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(Cari.id)).where(Cari.musteri_grubu == "PERAKENDE MÜŞTERİ")), 0)
            self.assertIsNone(s.scalar(select(MusteriGrubu).where(MusteriGrubu.ad == "PERAKENDE MÜŞTERİ")))
            bulunan = varsayilan_cari_bul(s)
            self.assertIsNotNone(bulunan)
            self.assertEqual(bulunan.musteri_grubu, "DİĞER")

    def test_aday_grubu_kullanilmasa_da_hedef_ister(self):
        self._grup_garanti("ADAY MÜŞTERİ")
        self._grup_garanti("NALBUR")
        with self.assertRaises(ValueError):
            CariService.grup_sil("ADAY MÜŞTERİ")
        CariService.grup_sil("ADAY MÜŞTERİ", "NALBUR")
        self.assertEqual(CariService.rol_grubu("ADAY_MUSTERI"), "NALBUR")
        self.assertEqual(CariService.aday_musteri_grubunu_garanti(), "NALBUR")
        self.assertNotIn("ADAY MÜŞTERİ", CariService.gruplari_listele(), "silinen grup geri oluşturulmaz")

    def test_hata_olursa_tasima_ve_silme_geri_alinir(self):
        from unittest.mock import patch

        self._grup_garanti("PERAKENDE MÜŞTERİ")
        self._grup_garanti("NALBUR")
        CariService.guncelle(self.cid, {"musteri_grubu": "PERAKENDE MÜŞTERİ"})
        with patch.object(CariService, "_rol_tablosu_hazirla", side_effect=RuntimeError("disk")):
            with self.assertRaises(RuntimeError):
                CariService.grup_sil("PERAKENDE MÜŞTERİ", "NALBUR")
        self.assertEqual(CariService.getir(self.cid).musteri_grubu, "PERAKENDE MÜŞTERİ")
        self.assertIn("PERAKENDE MÜŞTERİ", CariService.gruplari_listele())
        self.assertEqual(CariService.rol_grubu("PERAKENDE_MUSTERI"), "PERAKENDE MÜŞTERİ")

    def test_buyuk_kucuk_harf_farkli_gruplar_birlestirilir(self):
        from database.models.cari import MusteriGrubu

        with get_session() as s:
            for ad in ("DİĞER", "diğer"):
                if s.scalar(select(MusteriGrubu).where(MusteriGrubu.ad == ad)) is None:
                    s.add(MusteriGrubu(ad=ad))
            for i in range(4):
                s.add(Cari(cari_kodu=f"BU{i}", unvan=f"Büyük {i}", cari_turu="Müşteri", musteri_grubu="DİĞER"))
                s.add(Cari(cari_kodu=f"KU{i}", unvan=f"Küçük {i}", cari_turu="Müşteri", musteri_grubu="diğer"))
        with get_session() as s:
            toplam_once = s.scalar(select(func.count(Cari.id)))
        bilgi = CariService.grup_kullanimi("diğer")
        self.assertEqual(bilgi["cari_sayisi"], 4, "yalnız birebir aynı adlı kartlar")
        self.assertIn("DİĞER", bilgi["hedefler"])
        sonuc = CariService.grup_sil("diğer", "DİĞER")
        self.assertEqual((sonuc["tasinan"], sonuc["hedef"]), (4, "DİĞER"))
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(Cari.id)).where(Cari.musteri_grubu == "DİĞER")), 8)
            self.assertEqual(s.scalar(select(func.count(Cari.id))), toplam_once)
        self.assertNotIn("diğer", CariService.gruplari_listele())

    def test_grup_adi_turkce_harf_ve_bosluk_duyarsiz_tekil(self):
        self._grup_garanti("DİĞER")
        CariService.grup_ekle("IŞIK")
        CariService.grup_ekle("Mobilya Atölyesi")
        for ad in ("  diğer ", "Diğer", "ışık", "Işık", "MOBİLYA   ATÖLYESİ"):
            with self.assertRaises(ValueError, msg=ad):
                CariService.grup_ekle(ad)

    # —— Genel Risk ile limit ——
    def _genel_risk_ornegi(self, limit="200000"):
        with get_session() as s:
            _kalem(s, self.cid, "FTR-1", date(2026, 1, 1), "100000")
            _evrak(s, self.cid, "C1", "MUSTERI_CEKI", "40000", "CIRO_EDILDI")
            _evrak(s, self.cid, "C2", "MUSTERI_CEKI", "60000", "PORTFOYDE")
            _evrak(s, self.cid, "S1", "MUSTERI_SENEDI", "20000", "CIRO_EDILDI")
        CariService.guncelle(self.cid, {"risk_orani_ciro_cek": "25", "risk_orani_diger_cek": "100",
                                        "risk_orani_senet": "50", "toplam_risk_limiti": limit,
                                        "toplam_limit_uygula": True})

    def test_limit_genel_risk_ile_karsilastirilir(self):
        self._genel_risk_ornegi()
        ozet = crs.risk_ozeti(self.cid)
        toplam = ozet["satirlar"][crs.TUR_TOPLAM]
        self.assertEqual((toplam["risk"], toplam["brut"]), (D("180000.00"), D("220000.00")))
        self.assertEqual((toplam["kalan"], toplam["asim"], toplam["durum"]),
                         (D("20000.00"), D("0.00"), crs.DURUM_UYGUN), "brüt toplam aşım uyarısı vermez")
        self.assertEqual(crs.islem_kontrolu(self.cid, D("20000"))["asimlar"], [])

    def test_riski_artiran_islem_genel_risk_uzerinden_asim(self):
        self._genel_risk_ornegi()
        k = crs.islem_kontrolu(self.cid, D("25000"))
        asim = {a["tur"]: a for a in k["asimlar"]}
        self.assertEqual((asim[crs.TUR_TOPLAM]["yeni"], asim[crs.TUR_TOPLAM]["asim"]),
                         (D("205000.00"), D("5000.00")))

    def test_kayitli_belge_duzenlemesinde_eski_etki_cikarilir(self):
        self._genel_risk_ornegi()
        k = crs.islem_kontrolu(self.cid, D("125000"), belge_no="FTR-1")
        self.assertEqual((k["eski_etki"], k["etki"]), (D("100000.00"), D("25000.00")))
        asim = {a["tur"]: a for a in k["asimlar"]}
        self.assertEqual(asim[crs.TUR_TOPLAM]["asim"], D("5000.00"), "belge riske ikinci kez katılmaz")
        self.assertEqual(crs.islem_kontrolu(self.cid, D("90000"), belge_no="FTR-1")["asimlar"], [],
                         "riski azaltan düzenleme denetlenmez")

    def test_tum_oranlar_yuz_iken_eski_sonuc_korunur(self):
        self._genel_risk_ornegi()
        CariService.guncelle(self.cid, {"risk_orani_ciro_cek": "100", "risk_orani_senet": "100"})
        toplam = crs.risk_ozeti(self.cid)["satirlar"][crs.TUR_TOPLAM]
        self.assertEqual(toplam["risk"], toplam["brut"])
        self.assertEqual((toplam["risk"], toplam["asim"]), (D("220000.00"), D("20000.00")))

    def test_sifir_limit_sinirsiz_sayilmaz(self):
        self._genel_risk_ornegi(limit="0")
        toplam = crs.risk_ozeti(self.cid)["satirlar"][crs.TUR_TOPLAM]
        self.assertEqual((toplam["durum"], toplam["kalan"]), (crs.DURUM_ASILDI, D("-180000.00")))
        CariService.guncelle(self.cid, {"toplam_limit_uygula": False})
        self.assertEqual(crs.risk_ozeti(self.cid)["satirlar"][crs.TUR_TOPLAM]["durum"], crs.DURUM_TANIMSIZ)

    def test_oran_degisikligi_bakiye_ve_hareket_degistirmez(self):
        from database.cari_bakiye_service import net_bakiye
        from database.models.cari import CariIslem, SatisHareketi

        self._genel_risk_ornegi()
        with get_session() as s:
            once = (net_bakiye(self.cid, session=s)["bakiye"],
                    s.scalar(select(func.count(SatisHareketi.id))), s.scalar(select(func.count(CariIslem.id))))
        CariService.guncelle(self.cid, {"risk_orani_ciro_cek": "0", "risk_orani_senet": "10"})
        with get_session() as s:
            sonra = (net_bakiye(self.cid, session=s)["bakiye"],
                     s.scalar(select(func.count(SatisHareketi.id))), s.scalar(select(func.count(CariIslem.id))))
        self.assertEqual(once, sonra)

    # —— Son kodlar / bakiyeler ——
    def test_son_kodlar_dogal_sira_ve_bakiye(self):
        with get_session() as s:
            for kod in ("M9", "M10", "M2"):
                s.add(Cari(cari_kodu=kod, unvan=f"SIRA {kod}", cari_turu="Müşteri"))
        with get_session() as s:
            _kalem(s, self.cid, "FTR-9", date(2026, 1, 1), "1500")
        kodlar = [k["cari_kodu"] for k in CariService.son_kodlar("Müşteri")]
        self.assertLessEqual(len(kodlar), 10)
        self.assertLess(kodlar.index("M10"), kodlar.index("M9"))
        self.assertLess(kodlar.index("M9"), kodlar.index("M2"))
        self.assertEqual(kodlar[0], "M700")
        satir = next(k for k in CariService.son_kodlar("Müşteri") if k["id"] == self.cid)
        self.assertEqual((satir["tutar"], satir["yon"], satir["para_birimi"]), (D("1500.00"), "Borçlu", "TL"))

    def test_liste_bakiyeleri_tekil_bakiyeyle_ayni(self):
        from database.cari_bakiye_service import liste_bakiyeleri, net_bakiye

        with get_session() as s:
            _kalem(s, self.cid, "FTR-2", date(2026, 2, 1), "750.25")
        _servis_testi.TahsilatMakbuzuTest._nakit(self, "100")
        with get_session() as s:
            ids = list(s.scalars(select(Cari.id)).all())
        toplu = liste_bakiyeleri(ids)
        for cid in ids:
            self.assertEqual(D(str(toplu.get(cid, 0))), D(str(net_bakiye(cid)["bakiye"])), cid)

    # —— Yetkili ——
    def test_yetkili_dogum_gunu_yilsiz_ve_tanim_kimligi(self):
        from database.cari_yetkili_service import CariYetkiliService, dogum_gunu_metni

        a = CariYetkiliService.ekle(self.cid, {"ad": "Ayşe", "soyad": "Demir", "dogum_gun": "29",
                                               "dogum_ay": "2", "departman": "Satış", "gorev": "Uzman"})
        self.assertIsNone(a["dogum_tarihi"], "yıl yoksa sahte tarih üretilmez")
        self.assertEqual((a["dogum_gun"], a["dogum_ay"], a["dogum_yili"]), (29, 2, None))
        self.assertEqual(dogum_gunu_metni(a), "29.02")
        b = CariYetkiliService.ekle(self.cid, {"ad": "Can", "soyad": "Öz", "departman": "SATIŞ",
                                               "dogum_gun": "5", "dogum_ay": "6", "dogum_yili": "1990"})
        self.assertEqual(b["departman_id"], a["departman_id"], "aynı ad yeni tanım oluşturmaz")
        self.assertEqual(str(b["dogum_tarihi"]), "1990-06-05")
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(CariYetkiliDepartman.id))), 1)
        self.assertEqual([d["ad"] for d in CariYetkiliService.departmanlar("satış")], ["Satış"])
        with self.assertRaises(ValueError):
            CariYetkiliService.ekle(self.cid, {"ad": "X", "soyad": "Y", "dogum_gun": "5"})

    def test_yetkili_tekrar_kaydet_mukerrer_olusturmaz(self):
        from database.cari_yetkili_service import CariYetkiliService

        a = CariYetkiliService.ekle(self.cid, {"ad": "Ali", "soyad": "Kaya", "email": "ali@firma.com"})
        CariYetkiliService.guncelle(a["id"], {"ad": "Ali", "soyad": "Kaya", "email": "ali2@firma.com"})
        CariYetkiliService.guncelle(a["id"], {"ad": "Ali", "soyad": "Kaya", "email": "ali2@firma.com"})
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(CariYetkili.id)).where(CariYetkili.cari_id == self.cid)), 1)
        self.assertEqual(CariYetkiliService.listele(self.cid)[0]["email"], "ali2@firma.com")
        with self.assertRaises(ValueError):
            CariYetkiliService.guncelle(a["id"], {"ad": "Ali", "soyad": "Kaya", "email": "gecersiz"})

    def test_gorev_departmana_bagliysa_uyumsuz_secim_reddedilir(self):
        from database.cari_yetkili_service import CariYetkiliService

        with get_session() as s:
            muh = CariYetkiliDepartman(ad="Muhasebe", ad_norm=turkce_normalize("Muhasebe"), aktif=True)
            sat = CariYetkiliDepartman(ad="Satış", ad_norm=turkce_normalize("Satış"), aktif=True)
            s.add_all([muh, sat])
            s.flush()
            gorev = CariYetkiliGorev(ad="Mali Müşavir", ad_norm=turkce_normalize("Mali Müşavir"),
                                     departman_id=muh.id, aktif=True)
            s.add(gorev)
            s.flush()
            muh_id, sat_id, gorev_id = muh.id, sat.id, gorev.id
        self.assertEqual([g["id"] for g in CariYetkiliService.gorevler(sat_id)], [])
        self.assertEqual([g["id"] for g in CariYetkiliService.gorevler(muh_id)], [gorev_id])
        with self.assertRaises(ValueError):
            CariYetkiliService.ekle(self.cid, {"ad": "Z", "soyad": "Q", "departman_id": sat_id,
                                               "gorev_id": gorev_id})
        k = CariYetkiliService.ekle(self.cid, {"ad": "Z", "soyad": "Q", "departman_id": muh_id,
                                               "gorev_id": gorev_id})
        self.assertEqual((k["departman"], k["gorev"]), ("Muhasebe", "Mali Müşavir"))

    # —— Fotoğraf ——
    def _resim(self, renk="red", bicim="PNG", boyut=(1200, 600)) -> Path:
        from PIL import Image

        klasor = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(klasor, ignore_errors=True))
        yol = klasor / f"r.{bicim.lower()}"
        Image.new("RGB", boyut, renk).save(yol, format=bicim)
        return yol

    def test_cari_ve_yetkili_fotografi_ayri_ve_kucultulmus(self):
        from PIL import Image

        from database.cari_foto_service import CariFotoService
        from database.cari_yetkili_service import CariYetkiliService

        y = CariYetkiliService.ekle(self.cid, {"ad": "Foto", "soyad": "Kişi"})
        CariFotoService.kaydet("CARI", self.cid, self._resim("red"))
        CariFotoService.kaydet("YETKILI", y["id"], self._resim("blue", "JPEG", (300, 300)))
        cari_foto = CariFotoService.getir("CARI", self.cid, buyuk=True)
        with Image.open(io.BytesIO(cari_foto)) as img:
            self.assertEqual(max(img.size), 800)
            self.assertEqual(img.size, (800, 400), "en boy oranı korunur")
        with Image.open(io.BytesIO(CariFotoService.getir("CARI", self.cid))) as img:
            self.assertLessEqual(max(img.size), 256)
        self.assertNotEqual(CariFotoService.getir("YETKILI", y["id"]), CariFotoService.getir("CARI", self.cid))
        self.assertIsNone(CariFotoService.getir("YETKILI", y["id"], cari_id=self.musteri_id),
                          "başka cariye ait görüntü dönmez")
        self.assertTrue(CariYetkiliService.listele(self.cid)[0]["foto_var"])
        self.assertTrue(CariFotoService.kaldir("CARI", self.cid))
        self.assertIsNone(CariFotoService.getir("CARI", self.cid))
        self.assertIsNotNone(CariFotoService.getir("YETKILI", y["id"]), "cari fotoğrafı kaldırmak yetkiliyi etkilemez")

    def test_bozuk_dosya_reddedilir_mevcut_korunur(self):
        from database.cari_foto_service import CariFotoService

        CariFotoService.kaydet("CARI", self.cid, self._resim("green"))
        once = CariFotoService.getir("CARI", self.cid)
        bozuk = Path(tempfile.mkdtemp()) / "bozuk.jpg"
        bozuk.write_bytes(b"\xff\xd8\xff\xe0 bu bir resim degil")
        with self.assertRaises(ValueError):
            CariFotoService.kaydet("CARI", self.cid, bozuk)
        self.assertEqual(CariFotoService.getir("CARI", self.cid), once)


if __name__ == "__main__":
    unittest.main()
