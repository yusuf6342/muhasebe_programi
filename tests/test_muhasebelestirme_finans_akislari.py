"""Finans İşlem Ayarları — test_muhasebelestirme_finans_ayarlari'nda kapsanmayan akışlar.

Banka kredisi taksit ödemesi / erken kapama / ara ödeme, çek ciro-tahsil-karşılıksız ve verilen çek
ödemesi, kasa makbuzu içindeki POS satırı. Her akışta: tek fiş, borç = alacak, doğru hesaplar, mükerrer
fiş yok, iptalde ters kayıt, eksik ayarda açıklayıcı neden. Yalıtılmış geçici veritabanında çalışır.
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

from sqlalchemy import select  # noqa: E402

import test_muhasebelestirme_finans_ayarlari as tfa  # noqa: E402
from database.database import get_session  # noqa: E402
from database.models.genel_muhasebe import (  # noqa: E402
    BELGE_INCELEME,
    BELGE_IPTAL,
    BELGE_MUHASEBE_DISI,
    BELGE_MUHASEBELESTIRILDI,
)

TARIH = tfa.TARIH

for _anahtar, _hesap in {
    "kredi_faiz_gideri": ("660.01.0001", "Kredi Faiz Gideri", "Gider"),
    "kredi_bsmv_gideri": ("780.01.0002", "Kredi BSMV Gideri", "Gider"),
    "kredi_kkdf_gideri": ("780.01.0003", "Kredi KKDF Gideri", "Gider"),
    "verilen_cekler": ("103.01.0001", "Verilen Çekler", "Aktif"),
}.items():
    tfa.EK_HESAPLAR.setdefault(_anahtar, _hesap)


class _Akis(tfa._Temel):
    def _fisler(self, kaynak_turu: str, kaynak_id: int) -> list[dict]:
        from database.models.genel_muhasebe import MuhasebeFisi, MuhasebeFisiSatiri

        with get_session() as s:
            sonuc = []
            for f in s.scalars(select(MuhasebeFisi).where(
                    MuhasebeFisi.kaynak_turu == kaynak_turu, MuhasebeFisi.kaynak_id == int(kaynak_id))
                    .order_by(MuhasebeFisi.id)).all():
                satirlar = s.scalars(select(MuhasebeFisiSatiri).where(MuhasebeFisiSatiri.fis_id == f.id)).all()
                borc = sum((Decimal(str(r.borc or 0)) for r in satirlar), Decimal("0"))
                alacak = sum((Decimal(str(r.alacak or 0)) for r in satirlar), Decimal("0"))
                self.assertEqual(borc, alacak, f"fiş {f.id} dengesiz")
                sonuc.append({"id": f.id, "durum": f.durum, "toplam": borc})
            return sonuc

    def _tek_fis(self, kaynak_turu: str, kaynak_id: int, durum_id: int | None = None) -> dict:
        fisler = self._fisler(kaynak_turu, kaynak_id)
        self.assertEqual(len(fisler), 1, fisler)
        if durum_id is not None:
            self._servis().muhasebelestir([durum_id])
            self.assertEqual(len(self._fisler(kaynak_turu, kaynak_id)), 1, "ikinci kez fiş oluşmamalı")
        return fisler[0]


# ====================================================================== banka kredisi
class KrediOdemeAkisTest(_Akis):
    def _kredi_hazirla(self, *, vade="oniki_ay", zaman="kullandirim_ve_taksit"):
        from database.models.finans import BankaKrediTaksit, FinansHesabi

        self._ayar("otomatik")
        self._finans_ayar(kredi__fis_zamani=zaman, kredi__vade_ayrimi=vade)
        kart = self._banka_karti()
        with get_session() as s:
            s.get(FinansHesabi, kart["MEVDUAT"]).acilis_bakiyesi = Decimal("50000")
        self._hesap_bagla("kredi_kisa_vadeli", "kredi_uzun_vadeli")
        kid = tfa.BankaKrediTest._kredi(self, kart)
        with get_session() as s:
            taksitler = s.scalars(select(BankaKrediTaksit).where(BankaKrediTaksit.kredi_id == kid)
                                  .order_by(BankaKrediTaksit.taksit_no)).all()
            t1 = taksitler[0]
            t1.faiz, t1.bsmv, t1.kkdf = Decimal("300"), Decimal("15"), Decimal("45")
            ids = [int(t.id) for t in taksitler]
        return kart, kid, ids

    @staticmethod
    def _odeme_id(belge_no: str) -> int:
        from database.models.finans import BankaKrediOdeme

        with get_session() as s:
            return int(s.scalar(select(BankaKrediOdeme.id).where(BankaKrediOdeme.odeme_belge_no == belge_no)))

    def test_taksit_ve_erken_kapama_oniki_ay_ayrimi_kalem_hesaplari_tek_fis_iptal_ters(self):
        from database.banka_kredi_service import BankaKrediService

        self._hesap_bagla("kredi_faiz_gideri", "kredi_bsmv_gideri", "kredi_kkdf_gideri")
        kart, kid, (t1, _t2) = self._kredi_hazirla()
        once = self._tutarli()

        r1 = BankaKrediService.taksit_ode(taksit_id=t1, odeme_tarihi=TARIH + timedelta(days=30),
                                          banka_hesap_id=kart["MEVDUAT"])
        o1 = self._odeme_id(r1["odeme_belge_no"])
        self.assertEqual(self._durum("banka_kredi_odeme", o1)["durum"], BELGE_MUHASEBELESTIRILDI)
        taksit_etkisi = {"300.01.0002": Decimal("6000"), "660.01.0001": Decimal("300"),
                         "780.01.0002": Decimal("15"), "780.01.0003": Decimal("45"), "102.01.0001": Decimal("-6360")}
        self.assertEqual(self._fark(once), taksit_etkisi)
        self.assertEqual(self._tek_fis("banka_kredi_odeme", o1, self._durum_id("banka_kredi_odeme", o1))["toplam"],
                         Decimal("6360"))

        # Erken kapama: kalan taksit vadesi kullandırımdan 12 ay sonra → uzun vadeli krediden düşer
        r2 = BankaKrediService.erken_kapat(kid, odeme_tarihi=TARIH + timedelta(days=60),
                                           banka_hesap_id=kart["MEVDUAT"], faiz="100", masraflar={"bsmv": "5"})
        o2 = self._odeme_id(r2["odeme_belge_no"])
        self.assertTrue(r2["kredi_kapandi"])
        kapama_etkisi = {"400.01.0001": Decimal("4000"), "660.01.0001": Decimal("100"),
                         "780.01.0002": Decimal("5"), "102.01.0001": Decimal("-4105")}
        beklenen = {k: taksit_etkisi.get(k, Decimal("0")) + kapama_etkisi.get(k, Decimal("0"))
                    for k in set(taksit_etkisi) | set(kapama_etkisi)}
        self.assertEqual(self._fark(once), beklenen)
        self._tek_fis("banka_kredi_odeme", o2, self._durum_id("banka_kredi_odeme", o2))
        # Kredi kullandırım + iki ödeme sonrası kısa ve uzun vadeli kredi hesapları kapanmış olmalı
        bakiyeler = self._tutarli()
        self.assertNotIn("300.01.0002", bakiyeler)
        self.assertNotIn("400.01.0001", bakiyeler)

        # İptal: erken kapama fişi ters kayıtla kapanır, ikinci iptal yeni ters kayıt üretmez
        toplam_fis = self._fis_sayisi()
        BankaKrediService.odeme_iptal(odeme_id=o2, neden="Yanlış dekont")
        self.assertEqual(self._fark(once), taksit_etkisi)
        self.assertEqual(self._durum("banka_kredi_odeme", o2)["durum"], BELGE_IPTAL)
        self.assertEqual(self._fis_sayisi(), toplam_fis + 1, "tek ters fiş")
        from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

        MuhasebeEntegrasyonService.banka_kredi_odeme_iptal(o2, "tekrar")
        self.assertEqual(self._fis_sayisi(), toplam_fis + 1, "ikinci iptal ters kayıt üretmez")
        self.assertEqual(self._fark(once), taksit_etkisi)

        BankaKrediService.odeme_iptal(odeme_id=o1, neden="Yanlış taksit")
        self.assertEqual(self._fark(once), {})

    def test_eksik_kalem_hesabi_inceleme_baglaninca_tek_fis_tumu_kisa(self):
        from database.banka_kredi_service import BankaKrediService
        from database.muhasebe_finans_ayarlari import AYAR_YERI

        self._hesap_bagla("kredi_faiz_gideri", "kredi_kkdf_gideri")  # BSMV hesabı bağlı değil
        kart, _kid, (t1, _t2) = self._kredi_hazirla(vade="tumu_kisa")
        once = self._tutarli()
        r = BankaKrediService.taksit_ode(taksit_id=t1, odeme_tarihi=TARIH + timedelta(days=30),
                                         banka_hesap_id=kart["MEVDUAT"])
        oid = self._odeme_id(r["odeme_belge_no"])
        d = self._durum_kaydi("banka_kredi_odeme", oid)
        self.assertEqual(d.durum, BELGE_INCELEME, "eksik hesap: ödeme kaydedilir, fiş tahmin edilmez")
        self.assertIn("kredi_bsmv_gideri", d.aciklama)
        self.assertIn(AYAR_YERI, d.aciklama)
        self.assertEqual(self._fisler("banka_kredi_odeme", oid), [])
        self.assertEqual(self._fark(once), {})

        self._hesap_bagla("kredi_bsmv_gideri")
        self.assertEqual(self._servis().muhasebelestir([d.id])["basarili"], 1)
        self._tek_fis("banka_kredi_odeme", oid, d.id)
        self.assertEqual(self._fark(once), {"300.01.0002": Decimal("6000"), "660.01.0001": Decimal("300"),
                                            "780.01.0002": Decimal("15"), "780.01.0003": Decimal("45"),
                                            "102.01.0001": Decimal("-6360")})

    def test_secenek_tanimsizken_ve_oniki_ayda_ara_odemede_inceleme_nedeni(self):
        from database.banka_kredi_service import BankaKrediService

        self._hesap_bagla("kredi_faiz_gideri", "kredi_bsmv_gideri", "kredi_kkdf_gideri")
        kart, kid, (t1, _t2) = self._kredi_hazirla()
        from database import muhasebe_finans_ayarlari as fa

        fa.kaydet({fa.KREDI_FIS_ZAMANI: None, fa.KREDI_VADE_AYRIMI: None})
        once = self._tutarli()
        r = BankaKrediService.taksit_ode(taksit_id=t1, odeme_tarihi=TARIH + timedelta(days=30),
                                         banka_hesap_id=kart["MEVDUAT"])
        d = self._durum_kaydi("banka_kredi_odeme", self._odeme_id(r["odeme_belge_no"]))
        self.assertEqual(d.durum, BELGE_INCELEME)
        self.assertIn("Banka kredisi fiş zamanı", d.aciklama)

        self._finans_ayar(kredi__fis_zamani="kullandirim_ve_taksit", kredi__vade_ayrimi="oniki_ay")
        r2 = BankaKrediService.ara_ode(kid, "1000", odeme_tarihi=TARIH + timedelta(days=40),
                                       banka_hesap_id=kart["MEVDUAT"])
        o2 = self._odeme_id(r2["odeme_belge_no"])
        d2 = self._durum_kaydi("banka_kredi_odeme", o2)
        self.assertEqual(d2.durum, BELGE_INCELEME)
        self.assertIn("ara ödemede", d2.aciklama)
        self.assertEqual(self._fisler("banka_kredi_odeme", o2), [])
        # Bekleyen taksit ödemesi seçenek tanımlanınca tek fişle muhasebeleşir
        self.assertEqual(self._servis().muhasebelestir([d.id])["basarili"], 1)
        self.assertEqual(self._fark(once), {"300.01.0002": Decimal("6000"), "660.01.0001": Decimal("300"),
                                            "780.01.0002": Decimal("15"), "780.01.0003": Decimal("45"),
                                            "102.01.0001": Decimal("-6360")})


# ====================================================================== çek / senet
class CekAkisTest(_Akis):
    _cek = tfa.CekSenetTest._cek
    _hareket = tfa.CekSenetTest._hareket

    def _verilen_cek(self, no="V-1", tutar="700") -> tuple[int, int]:
        from database.cek_senet_service import CekSenetService
        from database.models.cek_senet import CekSenetEvrak

        CekSenetService.olustur({"islem_yonu": "VERILEN", "basit_tur": "CEK", "evrak_no": no,
                                 "duzenleme_tarihi": TARIH, "vade_tarihi": TARIH + timedelta(days=30),
                                 "tutar": tutar, "cari_id": self.tedarikci_id})
        with get_session() as s:
            eid = int(s.scalar(select(CekSenetEvrak.id).where(CekSenetEvrak.evrak_no == no)))
        return eid, self._hareket(eid, "KAYIT")

    def test_ciro_tek_fis_karsiliksiz_secenek_yoksa_inceleme_ciro_ters_kayit(self):
        from database.cek_senet_service import CekSenetService

        self._ayar("otomatik")
        self._finans_ayar(cek_senet__KAYIT_ALINAN="evet", cek_senet__CIRO="evet")
        self._hesap_bagla("cek_portfoy")
        once = self._tutarli()
        e1, _h1 = self._cek("C-10", "1000")
        self.assertEqual(self._fark(once), {"101.01.0001": Decimal("1000"), "120.01.0001": Decimal("-1000")})

        CekSenetService.ciro_et(e1, hedef_cari_id=self.tedarikci_id, tarih=TARIH)
        ciro = self._hareket(e1, "CIRO")
        self.assertEqual(self._durum("cek_senet", ciro)["durum"], BELGE_MUHASEBELESTIRILDI)
        self._tek_fis("cek_senet_hareketi", ciro, self._durum_id("cek_senet", ciro))
        self.assertEqual(self._fark(once), {"320.01.0001": Decimal("1000"), "120.01.0001": Decimal("-1000")})

        # Karşılıksız: seçenek tanımsız → inceleme; ciro fişi yine de ters kayıtla kapanır
        CekSenetService.karsiliksiz_protesto(e1, tarih=TARIH)
        kh = self._hareket(e1, "KARSILIKSIZ")
        dk = self._durum_kaydi("cek_senet", kh)
        self.assertEqual(dk.durum, BELGE_INCELEME)
        self.assertIn("Karşılıksız", dk.aciklama)
        self.assertEqual(self._durum("cek_senet", ciro)["durum"], BELGE_IPTAL)
        self.assertEqual(self._fark(once), {"101.01.0001": Decimal("1000"), "120.01.0001": Decimal("-1000")},
                         "ciro ters kayıtla kalktı; evrak portföy hesabında")

        self._finans_ayar(cek_senet__KARSILIKSIZ="evet")
        self.assertEqual(self._servis().muhasebelestir([dk.id])["basarili"], 1)
        self._tek_fis("cek_senet_hareketi", kh, dk.id)
        self.assertEqual(self._fark(once), {}, "müşteri yeniden borçlandı, portföy kapandı")

    def test_bankaya_tahsile_tahsil_kismi_ve_fis_uretmesin_secenegi(self):
        from database.cek_senet_service import CekSenetService

        self._ayar("otomatik")
        self._finans_ayar(cek_senet__KAYIT_ALINAN="evet", cek_senet__BANKAYA_TAHSILE="evet",
                          cek_senet__TAHSIL="evet")
        self._hesap_bagla("cek_portfoy", "cek_tahsilde")
        banka = self._banka()
        once = self._tutarli()
        e2, _ = self._cek("C-11", "400")
        CekSenetService.bankaya_ver(e2, tur="TAHSILE", banka_hesabi_id=banka, tarih=TARIH)
        self.assertEqual(self._fark(once), {"101.01.0002": Decimal("400"), "120.01.0001": Decimal("-400")})

        CekSenetService.tahsil_et(e2, tutar="150", finans_hesap_id=banka, tarih=TARIH)
        k1 = self._hareket(e2, "KISMI_TAHSIL")
        self._tek_fis("cek_senet_hareketi", k1, self._durum_id("cek_senet", k1))
        CekSenetService.tahsil_et(e2, finans_hesap_id=banka, tarih=TARIH)
        t2 = self._hareket(e2, "TAHSIL")
        self._tek_fis("cek_senet_hareketi", t2, self._durum_id("cek_senet", t2))
        self.assertEqual(self._fark(once), {"102.01.0001": Decimal("400"), "120.01.0001": Decimal("-400")})

        # Tahsil aşaması 'fiş üretmesin': muhasebe dışı, fiş yok
        self._finans_ayar(cek_senet__TAHSIL="hayir")
        e3, _ = self._cek("C-12", "300")
        ara = self._tutarli()
        CekSenetService.tahsil_et(e3, finans_hesap_id=banka, tarih=TARIH)
        t3 = self._hareket(e3, "TAHSIL")
        self.assertEqual(self._durum("cek_senet", t3)["durum"], BELGE_MUHASEBE_DISI)
        self.assertEqual(self._fisler("cek_senet_hareketi", t3), [])
        self.assertEqual(self._fark(ara), {})

    def test_verilen_cek_kayit_ve_odeme_tek_fis_secenek_yoksa_inceleme_iptal_ters(self):
        from database.cek_senet_service import CekSenetService

        self._ayar("otomatik")
        self._finans_ayar(cek_senet__KAYIT_VERILEN="evet")
        self._hesap_bagla("verilen_cekler")
        banka = self._banka()
        once = self._tutarli()
        e1, h1 = self._verilen_cek("V-1", "700")
        self._tek_fis("cek_senet_hareketi", h1, self._durum_id("cek_senet", h1))
        self.assertEqual(self._fark(once), {"320.01.0001": Decimal("700"), "103.01.0001": Decimal("-700")})

        CekSenetService.ode(e1, finans_hesap_id=banka, tarih=TARIH)
        oh = self._hareket(e1, "ODEME")
        d = self._durum_kaydi("cek_senet", oh)
        self.assertEqual(d.durum, BELGE_INCELEME)
        self.assertIn("ödemesi", d.aciklama)
        self.assertEqual(self._fisler("cek_senet_hareketi", oh), [])

        self._finans_ayar(cek_senet__ODEME="evet")
        self.assertEqual(self._servis().muhasebelestir([d.id])["basarili"], 1)
        self._tek_fis("cek_senet_hareketi", oh, d.id)
        self.assertEqual(self._fark(once), {"320.01.0001": Decimal("700"), "102.01.0001": Decimal("-700")})

        # Ödenmemiş verilen çekin iptali: kayıt fişi ters kayıtla kapanır
        ara = self._tutarli()
        e2, h2 = self._verilen_cek("V-2", "250")
        self.assertEqual(self._fark(ara), {"320.01.0001": Decimal("250"), "103.01.0001": Decimal("-250")})
        CekSenetService.iptal(e2, aciklama="Yanlış çek")
        self.assertEqual(self._durum("cek_senet", h2)["durum"], BELGE_IPTAL)
        self.assertEqual(self._fark(ara), {})


# ====================================================================== kasa makbuzu POS satırı
class MakbuzPosAkisTest(_Akis):
    def _makbuz_veri(self, kart, pos_tutar="1000", nakit="200"):
        return {"tarih": TARIH, "cari_id": self.musteri_id, "makbuz_no_otomatik": True,
                "satirlar": [
                    {"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self._kasa(), "tutar": nakit},
                    {"odeme_sekli": "KREDİ KARTIYLA TAHSİLAT", "finans_hesap_id": kart["POS"], "tutar": pos_tutar,
                     "kart_tipi": "KREDI_KARTI", "taksit_sayisi": 1},
                ]}

    def test_pos_satiri_eksik_ayar_inceleme_tek_fis_guncelleme_valor_iptal_ters(self):
        from database.finans_service import FinansService
        from database.models.finans import KasaMakbuzu
        from database.muhasebe_finans_ayarlari import AYAR_YERI

        self._ayar("otomatik")
        kart = self._banka_karti()
        once = self._tutarli()
        m = FinansService.kasa_tahsilat_makbuzu_kaydet(self._makbuz_veri(kart))
        d = self._durum_kaydi("kasa_makbuzu", m.id)
        self.assertEqual(d.durum, BELGE_INCELEME)
        self.assertIn("Makbuz satırı 2 (POS)", d.aciklama)
        self.assertIn("pos_valor_alacagi", d.aciklama)
        self.assertIn(AYAR_YERI, d.aciklama)
        self.assertEqual(self._fisler("kasa_makbuzu", m.id), [])
        self.assertEqual(self._fark(once), {})

        self._hesap_bagla("pos_valor_alacagi", "pos_komisyon_gideri")
        self.assertEqual(self._servis().muhasebelestir([d.id])["basarili"], 1)
        self._tek_fis("kasa_makbuzu", m.id, d.id)
        self.assertEqual(self._fark(once), {"100.01.0001": Decimal("200"), "108.01.0001": Decimal("980"),
                                            "780.01.0001": Decimal("20"), "120.01.0001": Decimal("-1200")})
        self.assertEqual(self._fis_sayisi("pos_tahsilat"), 0, "makbuz POS satırı ayrı POS fişi üretmez")

        # Güncelleme: eski fiş ters kayıt, yeni tutarla tek etkin fiş
        FinansService.kasa_makbuz_guncelle(m.id, self._makbuz_veri(kart, pos_tutar="500"))
        self.assertEqual(self._fark(once), {"100.01.0001": Decimal("200"), "108.01.0001": Decimal("490"),
                                            "780.01.0001": Decimal("10"), "120.01.0001": Decimal("-700")})
        self.assertEqual(self._durum("kasa_makbuzu", m.id)["durum"], BELGE_MUHASEBELESTIRILDI)
        self.assertEqual(len(self._fisler("kasa_makbuzu", m.id)), 1, "güncellemede tek etkin fiş")

        # Valör aktarımı: KMH bağlı değilse inceleme; bağlanınca KMH / POS valör alacağı
        with get_session() as s:
            pv_id = int(s.get(KasaMakbuzu, m.id).satirlar[1].pos_valor_id)
        ara = self._tutarli()
        FinansService.pos_valor_aktar(pv_id)
        dv = self._durum_kaydi("pos_valor_aktarimi", pv_id)
        self.assertEqual(dv.durum, BELGE_INCELEME)
        self.assertIn("kmh_hesabi", dv.aciklama)
        self._hesap_bagla("kmh_hesabi")
        self.assertEqual(self._servis().muhasebelestir([dv.id])["basarili"], 1)
        self._tek_fis("pos_valor_aktarimi", pv_id, dv.id)
        self.assertEqual(self._fark(ara), {"300.01.0001": Decimal("490"), "108.01.0001": Decimal("-490")})

    def test_pos_makbuzu_iptal_ters_kayit(self):
        from database.finans_service import FinansService

        self._ayar("otomatik")
        self._hesap_bagla("pos_valor_alacagi", "pos_komisyon_gideri")
        kart = self._banka_karti()
        once = self._tutarli()
        m = FinansService.kasa_tahsilat_makbuzu_kaydet(self._makbuz_veri(kart))
        self._tek_fis("kasa_makbuzu", m.id, self._durum_id("kasa_makbuzu", m.id))
        self.assertNotEqual(self._fark(once), {})
        toplam_fis = self._fis_sayisi()
        FinansService.kasa_makbuz_iptal(m.id)
        self.assertEqual(self._fark(once), {})
        self.assertEqual(self._durum("kasa_makbuzu", m.id)["durum"], BELGE_IPTAL)
        self.assertEqual(self._fis_sayisi(), toplam_fis + 1, "asıl fiş defterde kalır, tek ters fiş eklenir")
        with self.assertRaises(ValueError):
            FinansService.kasa_makbuz_iptal(m.id)
        self.assertEqual(self._fis_sayisi(), toplam_fis + 1)


if __name__ == "__main__":
    unittest.main()
