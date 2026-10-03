"""Otomatik / sonradan muhasebeleştirme ayarları.

- Otomatik: fiş evrak kesinleşirken aynı transaction'da, tek kez; hata varsa evrak kesinleşmez.
- Sonradan: ön muhasebe hareketleri oluşur, fiş oluşmaz; evrak "Bekliyor" listesine düşer ve
  sonradan tek tek / toplu muhasebeleştirilir (ön muhasebe kayıtları yeniden üretilmez).
- Ayar değişikliği geçmiş evrakı işlemez; geçiş eski kayıtları evrak no ile eşleştirmez.
"""

from __future__ import annotations

import sys
import threading
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sqlalchemy import func, inspect, select, text  # noqa: E402

import database.models.sube  # noqa: E402,F401
import test_masraf_dagitim as tmd  # noqa: E402
import test_masraf_dagitim_baglanti as tmb  # noqa: E402
from database import muhasebe_entegrasyon as _me  # noqa: E402
from database.database import get_session  # noqa: E402

_GERCEK_HOOK = _me.muhasebe_hook


class MuhasebelestirmeAyarlariTest(unittest.TestCase):
    _alis = tmd.MasrafDagitimTest._alis
    _gider = tmd.MasrafDagitimTest._gider
    _sat = tmd.MasrafDagitimTest._sat
    _gm_kur = tmd.MasrafDagitimTest._gm_kur
    _kasa = tmb.MasrafBaglantiTest._kasa
    _gider_fisi = tmb.MasrafBaglantiTest._gider_fisi

    def setUp(self):
        tmd.MasrafDagitimTest.setUp(self)
        # Evrak servisleri gerçek muhasebe kancasını (ayar + durum) kullanır
        self._muhasebe_patch.stop()
        self._muhasebe_patch = patch("database.muhasebe_entegrasyon.muhasebe_hook", _GERCEK_HOOK)
        self._muhasebe_patch.start()

    def tearDown(self):
        tmd.MasrafDagitimTest.tearDown(self)

    # ------------------------------------------------------------ yardımcı
    @staticmethod
    def _servis():
        from database.muhasebelestirme_service import MuhasebelestirmeService

        return MuhasebelestirmeService

    def _ayar(self, varsayilan="otomatik", gm=True, **turler):
        return self._servis().ayar_kaydet(gm_kullan=gm, varsayilan=varsayilan, turler=turler)

    def _fis_sayisi(self, kaynak_turu=None, durum=None) -> int:
        from database.models.genel_muhasebe import MuhasebeFisi

        with get_session() as s:
            q = select(func.count()).select_from(MuhasebeFisi)
            if kaynak_turu:
                q = q.where(MuhasebeFisi.kaynak_turu == kaynak_turu)
            if durum:
                q = q.where(MuhasebeFisi.durum == durum)
            return int(s.scalar(q))

    def _durum(self, evrak, kaynak_id) -> dict:
        return self._servis().belge_durumu(evrak, kaynak_id)

    def _durum_id(self, evrak, kaynak_id) -> int:
        from database.models.genel_muhasebe import MuhasebeBelgeDurumu

        with get_session() as s:
            return int(s.scalar(select(MuhasebeBelgeDurumu.id).where(
                MuhasebeBelgeDurumu.evrak_turu == evrak, MuhasebeBelgeDurumu.kaynak_id == int(kaynak_id))))

    def _operasyon_sayilari(self) -> dict[str, int]:
        """Muhasebe dışı tüm tabloların satır sayıları (ön muhasebe kayıtları)."""
        from database.database import company_db

        motor = company_db.engine
        with motor.connect() as c:
            return {
                t: c.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
                for t in inspect(motor).get_table_names() if not t.startswith("muhasebe_")
            }

    def _bakiyeler(self) -> dict[str, Decimal]:
        from database.models.genel_muhasebe import HesapPlani

        with get_session() as s:
            sonuc = {h.hesap_kodu: Decimal(str(h.borc_toplam)) - Decimal(str(h.alacak_toplam))
                     for h in s.scalars(select(HesapPlani)).all()}
        return {k: v for k, v in sonuc.items() if v != 0}

    def _tutarli(self) -> dict[str, Decimal]:
        from database.muhasebe_service import MuhasebeRaporService

        m = MuhasebeRaporService.mizan(date(2000, 1, 1), date(2099, 12, 31))
        self.assertTrue(m["dengeli"])
        mizan = {s["hesap_kodu"]: s["borc_bakiyesi"] - s["alacak_bakiyesi"] for s in m["satirlar"]}
        b = self._bakiyeler()
        self.assertEqual(b, {k: v for k, v in mizan.items() if v != 0})
        return b

    def _taslak_satis(self, miktar="10"):
        from database.satis_faturasi_service import SatisFaturasiService

        f = SatisFaturasiService.kaydet(
            {"fatura_tarihi": tmd.TARIH_SATIS, "vade_tarihi": tmd.TARIH_SATIS, "cari_id": self.musteri_id,
             "depo": "ANA DEPO", "odeme_tutari": Decimal("0"), "sales_person_id": 1},
            [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": Decimal(miktar), "birim": "Adet",
              "birim_fiyat": Decimal("200"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20")}],
        )
        return int(f.id)

    # ------------------------------------------------------------ testler
    def test_gecis_eslesmeli_firma_otomatik_kalir(self):
        a = self._servis().ayarlar()
        self.assertTrue(a["gm_kullan"])
        self.assertEqual(a["varsayilan"], "otomatik")
        self.assertEqual({t["evrak_turu"]: t["etkin"] for t in a["turler"]},
                         {e: "otomatik" for e in _me.EVRAKLAR})
        self.assertTrue(a["desteklenmeyen"])

    def test_otomatik_kesinlesmede_tek_fis_taslakta_fis_yok(self):
        self._alis("U001", "100", "100", "LOT-A")
        self.assertEqual(self._fis_sayisi("alis_faturasi"), 1)
        taslak = self._taslak_satis()
        self.assertEqual(self._fis_sayisi("satis_faturasi"), 0)
        self.assertEqual(self._durum("satis_faturasi", taslak)["durum"], "Kayıt yok")

        from database.satis_faturasi_service import SatisFaturasiService

        SatisFaturasiService.onayla(taslak)
        self.assertEqual(self._fis_sayisi("satis_faturasi"), 1)
        d = self._durum("satis_faturasi", taslak)
        self.assertEqual(d["durum"], "Muhasebeleştirildi")
        self.assertIsNotNone(d["fis_id"])
        kaynak = self._servis().fis_kaynagi(d["fis_id"])
        self.assertEqual((kaynak["evrak_turu"], kaynak["kaynak_id"]), ("satis_faturasi", taslak))
        self._tutarli()

    def test_otomatik_eslesme_eksik_veya_ara_hata_evrak_kesinlesmez(self):
        from database.models.cari import CariIslem
        from database.models.satis_faturasi import SatisFaturasi
        from database.satis_faturasi_service import SatisFaturasiService

        self._alis("U001", "100", "100", "LOT-A")
        sid = self._taslak_satis()
        once = self._operasyon_sayilari()
        fis_once = self._fis_sayisi()

        self._gm_kur(eksik=("hesaplanan_kdv",))
        with self.assertRaisesRegex(ValueError, "kesinleştirilmedi"):
            SatisFaturasiService.onayla(sid)
        self._gm_kur()
        with patch.object(_me.MuhasebeEntegrasyonService, "_olustur", side_effect=RuntimeError("kesinti")):
            with self.assertRaises(RuntimeError):
                SatisFaturasiService.onayla(sid)

        with get_session() as s:
            self.assertFalse(s.get(SatisFaturasi, sid).onaylandi)
            self.assertEqual(s.scalar(select(func.count()).select_from(CariIslem)), once["cari_islemleri"])
        self.assertEqual(self._operasyon_sayilari(), once)
        self.assertEqual(self._fis_sayisi(), fis_once)
        self.assertEqual(self._durum("satis_faturasi", sid)["durum"], "Kayıt yok")

        SatisFaturasiService.onayla(sid)  # düzeltildikten sonra normal kesinleşir
        self.assertEqual(self._fis_sayisi("satis_faturasi"), 1)

    def test_sonradan_hareketler_olusur_fis_sonra_bir_kez_yeniden_uretim_yok(self):
        self._ayar("sonradan")
        fid, _ = self._alis("U001", "100", "100", "LOT-A")
        sid = self._sat("40")
        self.assertEqual(self._fis_sayisi(), 0)
        for evrak, kid in (("alis_faturasi", fid), ("satis_faturasi", sid)):
            self.assertEqual(self._durum(evrak, kid)["durum"], "Bekliyor")
        bekleyen = self._servis().listele(durumlar=("Bekliyor", "Hatalı"))
        self.assertEqual({(b["evrak_turu"], b["kaynak_id"]) for b in bekleyen},
                         {("alis_faturasi", fid), ("satis_faturasi", sid)})
        b = next(x for x in bekleyen if x["evrak_turu"] == "satis_faturasi")
        self.assertEqual((b["tutar"], b["para_birimi"], b["cari_adi"]), (Decimal("9600.00"), "TRY", "Test Müşteri"))

        once = self._operasyon_sayilari()
        kontrol = self._servis().on_kontrol([x["id"] for x in bekleyen])
        self.assertEqual((kontrol["secili"], kontrol["islenebilir"], kontrol["sorunlar"]), (2, 2, []))
        sonuc = self._servis().muhasebelestir([x["id"] for x in bekleyen])
        self.assertEqual((sonuc["basarili"], sonuc["basarisiz"], sonuc["atlanan"]), (2, 0, 0))
        self.assertEqual(self._operasyon_sayilari(), once)  # stok/cari/kasa yeniden üretilmez
        self.assertEqual(self._fis_sayisi("alis_faturasi"), 1)
        self.assertEqual(self._fis_sayisi("satis_faturasi"), 1)
        from database.models.genel_muhasebe import MuhasebeFisi

        with get_session() as s:
            fis = s.scalar(select(MuhasebeFisi).where(MuhasebeFisi.kaynak_turu == "satis_faturasi"))
            self.assertEqual(fis.fis_tarihi, tmd.TARIH_SATIS)  # fiş tarihi = evrak tarihi
        self.assertEqual(self._durum("satis_faturasi", sid)["durum"], "Muhasebeleştirildi")

        tekrar = self._servis().muhasebelestir([x["id"] for x in bekleyen])
        self.assertEqual((tekrar["basarili"], tekrar["atlanan"]), (0, 2))
        self.assertEqual(self._fis_sayisi(), 2)
        self._tutarli()

    def test_firma_varsayilani_ve_tur_ayari_bagimsiz(self):
        self._ayar("otomatik", alis_faturasi="sonradan")
        fid, _ = self._alis("U001", "100", "100", "LOT-A")
        self.assertEqual(self._fis_sayisi("alis_faturasi"), 0)
        self.assertEqual(self._durum("alis_faturasi", fid)["durum"], "Bekliyor")
        sid = self._sat("10")
        self.assertEqual(self._fis_sayisi("satis_faturasi"), 1)
        self.assertEqual(self._durum("satis_faturasi", sid)["durum"], "Muhasebeleştirildi")
        a = {t["evrak_turu"]: (t["secim"], t["etkin"]) for t in self._servis().ayarlar()["turler"]}
        self.assertEqual(a["alis_faturasi"], ("sonradan", "sonradan"))
        self.assertEqual(a["satis_faturasi"], ("varsayilan", "otomatik"))

    def test_ayar_degisikligi_gecmisi_islemez_ve_denetim_izi(self):
        from database.models.genel_muhasebe import MuhasebeIslemGecmisi

        self._ayar("sonradan")
        fid, _ = self._alis("U001", "100", "100", "LOT-A")
        self._ayar("otomatik")
        self.assertEqual(self._fis_sayisi(), 0)
        self.assertEqual(self._durum("alis_faturasi", fid)["durum"], "Bekliyor")
        self._ayar("otomatik", gm=False)
        self._ayar("otomatik", gm=True)
        self.assertEqual(self._fis_sayisi(), 0)
        self.assertEqual(self._durum("alis_faturasi", fid)["durum"], "Bekliyor")
        with get_session() as s:
            izler = s.scalars(select(MuhasebeIslemGecmisi).where(
                MuhasebeIslemGecmisi.islem == "ayar_degistir")).all()
        self.assertEqual(len(izler), 4)
        self.assertTrue(all(i.kullanici_adi == "admin" for i in izler))

    def test_genel_muhasebe_kapali_fis_ve_durum_yok(self):
        self._ayar("otomatik", gm=False)
        fid, _ = self._alis("U001", "100", "100", "LOT-A")
        self.assertEqual(self._fis_sayisi(), 0)
        self.assertEqual(self._durum("alis_faturasi", fid)["durum"], "Genel muhasebe kapalı")

    def test_cift_tiklama_eszamanli_ve_yeniden_deneme(self):
        from database.models.genel_muhasebe import MuhasebeBelgeDurumu

        self._ayar("sonradan")
        fid, _ = self._alis("U001", "100", "100", "LOT-A")
        did = self._durum_id("alis_faturasi", fid)
        with get_session() as s:
            eski_surum = s.get(MuhasebeBelgeDurumu, did).row_version

        # Eş zamanlı iki istek (ör. iki kullanıcı): yalnız biri fiş üretir
        sonuclar = []
        engel = threading.Barrier(2)

        def calis():
            engel.wait()
            sonuclar.append(self._servis()._tek(did, None))

        ipler = [threading.Thread(target=calis) for _ in range(2)]
        for t in ipler:
            t.start()
        for t in ipler:
            t.join(60)
        self.assertEqual(sorted(r[0] for r in sonuclar).count("basarili"), 1)
        self.assertEqual(self._fis_sayisi("alis_faturasi"), 1)

        # Eski listeden (bayat sürüm) ikinci tık: atlanır
        tekrar = self._servis().muhasebelestir([(did, eski_surum)])
        self.assertEqual(tekrar["atlanan"], 1)
        self.assertEqual(self._fis_sayisi("alis_faturasi"), 1)

        # Toplu işlem çalışırken ikinci başlatma engellenir
        from database.muhasebelestirme_service import ZatenCalisiyor

        self._servis()._toplu_kilit.acquire()
        try:
            with self.assertRaises(ZatenCalisiyor):
                self._servis().muhasebelestir([did])
        finally:
            self._servis()._toplu_kilit.release()

        # Hata → Hatalı (neden + deneme sayısı); düzeltince yalnız başarısızlar yeniden denenir
        fid2, _ = self._alis("U001", "50", "100", "LOT-B")
        did2 = self._durum_id("alis_faturasi", fid2)
        self._gm_kur(eksik=("indirilecek_kdv",))
        sonuc = self._servis().muhasebelestir([did2])
        self.assertEqual(sonuc["basarisiz"], 1)
        hatali = self._servis().listele(durumlar=("Hatalı",))
        self.assertEqual([h["id"] for h in hatali], [did2])
        self.assertIn("indirilecek_kdv", hatali[0]["sorun"])
        self.assertEqual(hatali[0]["deneme_sayisi"], 1)
        self.assertEqual(self._fis_sayisi(), 1)
        self._gm_kur()
        sonuc = self._servis().muhasebelestir([h["id"] for h in self._servis().listele(durumlar=("Hatalı",))])
        self.assertEqual(sonuc["basarili"], 1)
        self.assertEqual(self._fis_sayisi("alis_faturasi"), 2)
        self._tutarli()

    def test_toplu_raporlama_kapali_donem_ve_ara_hata(self):
        from database.models.donem import Donem
        from database.models.genel_muhasebe import MuhasebeFisi

        self._ayar("sonradan")
        f1, _ = self._alis("U001", "10", "100", "LOT-A")
        f2, _ = self._alis("U001", "20", "100", "LOT-B")
        f3, _ = self._alis("U001", "30", "100", "LOT-C")
        sid = self._sat("5")
        self._servis().muhasebelestir([self._durum_id("satis_faturasi", sid)])
        # f2 kapalı döneme düşsün: aynı aralığı kapsayan kilitli dönem
        with get_session() as s:
            s.add(Donem(firma_id=self.firma_id, donem_adi="Haziran kilit", baslangic_tarihi=date(2026, 6, 1),
                        bitis_tarihi=date(2026, 6, 1), aktif=False, kapali=True, varsayilan=False))
            from database.models.alis_faturasi import AlisFaturasi

            s.get(AlisFaturasi, f1).fatura_tarihi = date(2026, 6, 3)
            s.get(AlisFaturasi, f3).fatura_tarihi = date(2026, 6, 4)
        ids = [self._durum_id("alis_faturasi", f) for f in (f1, f2, f3)] + [self._durum_id("satis_faturasi", sid)]
        kontrol = self._servis().on_kontrol(ids)
        self.assertEqual((kontrol["secili"], kontrol["islenebilir"]), (4, 3))
        self.assertTrue(any("kapalı" in m for m in kontrol["sorunlar"]))

        gercek = _me.MuhasebeEntegrasyonService.alis_faturasi_fisi

        def bozuk(fatura_id, **kw):
            if int(fatura_id) == f3:
                gercek(fatura_id, **kw)
                raise RuntimeError("yazım sırasında kesinti")
            return gercek(fatura_id, **kw)

        ilerleme = []
        with patch.object(_me.MuhasebeEntegrasyonService, "alis_faturasi_fisi", side_effect=bozuk):
            sonuc = self._servis().muhasebelestir(ids, ilerleme=lambda i, n, _s: ilerleme.append((i, n)))
        self.assertEqual((sonuc["basarili"], sonuc["basarisiz"], sonuc["atlanan"]), (1, 2, 1))
        self.assertEqual(ilerleme, [(1, 4), (2, 4), (3, 4), (4, 4)])
        mesajlar = {r["id"]: r["mesaj"] for r in sonuc["sonuclar"]}
        self.assertIn("kapalı", mesajlar[ids[1]])
        self.assertIn("kesinti", mesajlar[ids[2]])
        with get_session() as s:
            fis = s.scalar(select(MuhasebeFisi).where(MuhasebeFisi.kaynak_turu == "alis_faturasi",
                                                      MuhasebeFisi.kaynak_id == f1))
            self.assertEqual(fis.fis_tarihi, date(2026, 6, 3))
        self.assertEqual(self._fis_sayisi("alis_faturasi"), 1)  # yarım kalan f3 fişi geri alındı
        self.assertEqual(self._durum("alis_faturasi", f2)["durum"], "Hatalı")
        self.assertEqual(self._durum("alis_faturasi", f3)["durum"], "Hatalı")

        # Kaldığı yerden: yalnız başarısızlar, mükerrer fiş olmadan
        sonuc = self._servis().muhasebelestir([h["id"] for h in self._servis().listele(durumlar=("Hatalı",))])
        self.assertEqual((sonuc["basarili"], sonuc["basarisiz"]), (1, 1))
        self.assertEqual(self._fis_sayisi("alis_faturasi"), 2)
        self._tutarli()

    def test_iptal_bir_kez_ve_bekleyen_iptal_listeden_cikar(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.satis_faturasi_service import SatisFaturasiService

        from database.models.genel_muhasebe import MuhasebeFisi

        self._alis("U001", "100", "100", "LOT-A")
        once = self._tutarli()
        sid = self._sat("10")
        fis_id = self._durum("satis_faturasi", sid)["fis_id"]
        toplam = self._fis_sayisi()
        SatisFaturasiService.iptal_et(sid, "test")
        SatisFaturasiService.iptal_et(sid, "tekrar")
        self.assertEqual(self._fis_sayisi(), toplam + 1)  # yalnız bir ters fiş
        d = self._durum("satis_faturasi", sid)
        self.assertEqual((d["durum"], d["fis_id"]), ("İptal edildi", fis_id))
        with get_session() as s:
            self.assertEqual(s.get(MuhasebeFisi, fis_id).durum, "İptal")
        self.assertEqual(self._servis().fis_kaynagi(fis_id)["kaynak_id"], sid)
        self.assertEqual(self._tutarli(), once)

        self._ayar("sonradan")
        fid, _ = self._alis("U001", "10", "100", "LOT-B")
        fis_once = self._fis_sayisi()
        AlisFaturasiService.iptal_et(fid)
        self.assertEqual(self._fis_sayisi(), fis_once)
        self.assertEqual(self._durum("alis_faturasi", fid)["durum"], "İptal edildi")
        self.assertNotIn(fid, [b["kaynak_id"] for b in self._servis().listele(durumlar=("Bekliyor", "Hatalı"))])

    def test_onay_kaldirma_ve_tekrar_onay_tek_etkin_fis(self):
        from database.satis_faturasi_service import SatisFaturasiService

        self._alis("U001", "100", "100", "LOT-A")
        sid = self._sat("10")
        SatisFaturasiService.onay_kaldir(sid)
        self.assertEqual(self._durum("satis_faturasi", sid)["durum"], "İptal edildi")
        SatisFaturasiService.onayla(sid)
        self.assertEqual(self._fis_sayisi("satis_faturasi", "Kesinleşmiş"), 1)
        self.assertEqual(self._durum("satis_faturasi", sid)["durum"], "Muhasebeleştirildi")

    def test_sonradan_degisen_evrak_eski_fisi_ters_kayitla_kapatir(self):
        from database.alis_faturasi_service import AlisFaturasiService

        self._ayar("sonradan")
        fid, _ = self._alis("U001", "100", "100", "LOT-A")
        self._servis().muhasebelestir([self._durum_id("alis_faturasi", fid)])
        f = AlisFaturasiService.getir(fid)
        AlisFaturasiService.kaydet(
            {"fatura_tarihi": f.fatura_tarihi, "vade_tarihi": f.vade_tarihi, "cari_id": f.cari_id,
             "depo": "ANA DEPO", "odeme_tutari": Decimal("0")},
            [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": Decimal("90"), "birim": "Adet",
              "birim_fiyat": Decimal("100"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20"),
              "lot_no": "LOT-A"}],
            fatura_id=fid,
        )
        self.assertEqual(self._durum("alis_faturasi", fid)["durum"], "Bekliyor")
        self.assertEqual(self._tutarli(), {})
        self._servis().muhasebelestir([self._durum_id("alis_faturasi", fid)])
        self.assertEqual(self._tutarli(), {"153.01.0001": Decimal("9000"), "191.01.0001": Decimal("1800"),
                                           "320.01.0001": Decimal("-10800")})

    def test_cari_tahsilat_ve_gider_fisi_sonradan(self):
        from database.cari_service import CariService

        self._ayar("sonradan")
        self._kasa()
        islem = CariService.tahsilat_yap(self.musteri_id, date(2026, 6, 5), Decimal("500"), "Nakit",
                                         "Merkez Kasa")
        gfis = self._gider_fisi("250")
        self.assertEqual(self._fis_sayisi(), 0)
        kimlik = CariService.tahsilat_odeme_evraki(islem.id)
        self.assertEqual(kimlik["evrak_turu"], "cari_tahsilat")
        ids = [self._durum_id("cari_tahsilat", kimlik["kaynak_id"]), self._durum_id("gider_fisi", gfis)]
        sonuc = self._servis().muhasebelestir(ids)
        self.assertEqual(sonuc["basarili"], 2)
        self.assertEqual(self._tutarli(), {"100.01.0001": Decimal("250"), "120.01.0001": Decimal("-500"),
                                           "770.01.0001": Decimal("250")})

    def test_masraf_dagitimi_sonradan_kaynak_bir_kez_muhasebelesir(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        self._ayar("otomatik", hizmet_faturasi="sonradan")
        _fid, satir = self._alis("U001", "100", "100", "LOT-A")
        kaynak_id, ks = self._gider("1000")
        self.assertEqual(self._durum("hizmet_faturasi", kaynak_id)["durum"], "Bekliyor")
        veri = tmd.MasrafDagitimTest._veri(self, kaynak_id, ks, [satir])
        oniz = MasrafDagitimService.onizle(veri)
        self.assertEqual(oniz["engeller"], [])
        self.assertTrue(any("sonradan muhasebeleştirme" in u for u in oniz["uyarilar"]))
        did = MasrafDagitimService.taslak_kaydet(veri)
        MasrafDagitimService.onayla(did)
        self.assertEqual(self._fis_sayisi("hizmet_faturasi"), 1)
        self.assertEqual(self._durum("hizmet_faturasi", kaynak_id)["durum"], "Muhasebeleştirildi")
        sonuc = self._servis().muhasebelestir([self._durum_id("hizmet_faturasi", kaynak_id)])
        self.assertEqual(sonuc["atlanan"], 1)
        self.assertEqual(self._fis_sayisi("hizmet_faturasi"), 1)
        self._tutarli()

    def test_firma_ayrimi_ve_yetki(self):
        from database.access import AccessError
        from database.models.firma import Firma
        from database.models.genel_muhasebe import MuhasebeBelgeDurumu
        from database.session_manager import oturum

        self._ayar("sonradan")
        fid, _ = self._alis("U001", "100", "100", "LOT-A")
        with get_session() as s:
            diger = Firma(firma_kodu="DGR", unvan="Diğer Firma", aktif=True)
            s.add(diger)
            s.flush()
            yabanci = MuhasebeBelgeDurumu(firma_id=diger.id, evrak_turu="alis_faturasi",
                                          kaynak_id=fid, durum="Bekliyor", row_version=1, deneme_sayisi=0)
            s.add(yabanci)
            s.flush()
            yabanci_id = yabanci.id
        self.assertEqual(len(self._servis().listele()), 1)
        sonuc = self._servis().muhasebelestir([yabanci_id])
        self.assertEqual(sonuc["atlanan"], 1)
        self.assertEqual(self._fis_sayisi(), 0)

        oturum.set_user(user_id=2, kullanici_adi="satis", ad_soyad="Satış", role_kod="SATIS",
                        role_ad="Satış", permissions={"satis_goruntuleme"})
        with self.assertRaises(AccessError):
            self._ayar("otomatik")
        with self.assertRaises(AccessError):
            self._servis().muhasebelestir([self._durum_id("alis_faturasi", fid)])
        self.assertEqual(self._fis_sayisi(), 0)

    def test_gecis_yedekli_idempotent_belirsiz_kayit_eslestirilmez(self):
        from database.models.genel_muhasebe import (
            HesapPlani,
            MuhasebeBelgeDurumu,
            MuhasebeFisi,
            MuhasebeIslemGecmisi,
            MuhasebelestirmeAyari,
        )
        from database.muhasebe_service import MuhasebeFisService

        # Özellik öncesi gibi: kanca yok, evraklar fişsiz; biri bağlı fişli, biri aynı numaralı bağsız fişli
        self._muhasebe_patch.stop()
        self._muhasebe_patch = patch("database.muhasebe_entegrasyon.muhasebe_hook", lambda *_a, **_k: None)
        self._muhasebe_patch.start()
        bagli, _ = self._alis("U001", "100", "100", "LOT-A")
        belirsiz, _ = self._alis("U001", "10", "100", "LOT-B")
        _me.MuhasebeEntegrasyonService.alis_faturasi_fisi(bagli)
        from database.alis_faturasi_service import AlisFaturasiService

        no = AlisFaturasiService.getir(belirsiz).fatura_no
        with get_session() as s:
            ids = {k: s.scalar(select(HesapPlani.id).where(HesapPlani.hesap_kodu == k))
                   for k in ("770.01.0001", "100.01.0001")}
        MuhasebeFisService.kaydet(
            {"fis_tarihi": tmd.TARIH_ALIS, "fis_turu": "Mahsup Fişi", "durum": "Kesinleşmiş", "belge_no": no,
             "aciklama": f"Elle: {no}",
             "satirlar": [{"hesap_id": ids["770.01.0001"], "borc": "10"},
                          {"hesap_id": ids["100.01.0001"], "alacak": "10"}]},
            otomatik=True,
        )
        with get_session() as s:
            for m in (MuhasebeBelgeDurumu, MuhasebelestirmeAyari):
                s.execute(m.__table__.delete())
        fis_once, bakiye_once = self._fis_sayisi(), self._bakiyeler()

        yedek = self._servis().schema_hazirla()
        self.assertIsNotNone(yedek)
        self.assertTrue(Path(yedek).is_file())
        dogrulama = (Path(yedek).parent / "DOGRULAMA.txt").read_text(encoding="utf-8")
        self.assertIn("integrity_check ok, satır sayıları eşit", dogrulama)
        self.assertEqual(self._durum("alis_faturasi", bagli)["durum"], "Muhasebeleştirildi")
        self.assertEqual(self._durum("alis_faturasi", belirsiz)["durum"], "İnceleme gerekiyor")
        self.assertEqual(self._fis_sayisi(), fis_once)
        self.assertEqual(self._bakiyeler(), bakiye_once)

        with get_session() as s:
            durum_sayisi = s.scalar(select(func.count()).select_from(MuhasebeBelgeDurumu))
            gecmis_sayisi = s.scalar(select(func.count()).select_from(MuhasebeIslemGecmisi))
        self.assertIsNone(self._servis().schema_hazirla())  # ikinci açılış: yedek/geçiş yok
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(MuhasebeBelgeDurumu)), durum_sayisi)
            self.assertEqual(s.scalar(select(func.count()).select_from(MuhasebeIslemGecmisi)), gecmis_sayisi)
            self.assertEqual(s.scalar(select(func.count()).select_from(MuhasebeFisi)), fis_once)

        # İnceleme gerekiyor: kullanıcı muhasebe dışı bırakabilir; listeden çıkar, fiş oluşmaz
        did = self._durum_id("alis_faturasi", belirsiz)
        self.assertEqual(self._servis().muhasebe_disi_birak([did], "Elle fişlenmiş"), 1)
        self.assertEqual(self._durum("alis_faturasi", belirsiz)["durum"], "Muhasebe dışı")
        self.assertEqual(self._fis_sayisi(), fis_once)

    def test_gecis_eslesmesiz_ve_yeni_firma_sonradan_kapali(self):
        from database.models.genel_muhasebe import MuhasebeHesapEsleme, MuhasebelestirmeAyari

        with get_session() as s:
            s.execute(MuhasebelestirmeAyari.__table__.delete())
            s.execute(MuhasebeHesapEsleme.__table__.delete())
        self._servis().schema_hazirla()
        a = self._servis().ayarlar()
        self.assertEqual((a["gm_kullan"], a["varsayilan"]), (False, "sonradan"))

        with get_session() as s:
            s.execute(MuhasebelestirmeAyari.__table__.delete())
        self._gm_kur()
        self._servis().schema_hazirla(yeni_firma=True)
        a = self._servis().ayarlar()
        self.assertEqual((a["gm_kullan"], a["varsayilan"], a["kaynak"]), (False, "sonradan", "yeni_firma"))


if __name__ == "__main__":
    unittest.main()
