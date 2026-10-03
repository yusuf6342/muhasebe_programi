"""Masraf dağıtımı kalan eksikler.

1. Alış / kaynak belge iptalinde bağlı taslaklar aynı transaction'da geçersizleşir.
2. Eski Fatura Masrafları ile Masraf Dağıtımı aynı masrafı iki kez maliyete yükleyemez.
3. Gider fişi ve dağıtımın genel muhasebe etkisi: gider → stok/SMM, ters kayıt, eksik eşleştirme engeli.
"""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from sqlalchemy import func, select  # noqa: E402

import database.models.sube  # noqa: E402,F401
import test_masraf_dagitim as tmd  # noqa: E402
import test_masraf_dagitim_baglanti as tmb  # noqa: E402
from database.database import get_session  # noqa: E402

GIDER_FISI = "GIDER_FISI"


def _gercek_hook(fn_name, *args, **kwargs):
    from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

    return getattr(MuhasebeEntegrasyonService, fn_name)(*args, **kwargs)


class MasrafDagitimTamamlamaTest(unittest.TestCase):
    setUp = tmd.MasrafDagitimTest.setUp
    tearDown = tmd.MasrafDagitimTest.tearDown
    _alis = tmd.MasrafDagitimTest._alis
    _gider = tmd.MasrafDagitimTest._gider
    _sat = tmd.MasrafDagitimTest._sat
    _lot = tmd.MasrafDagitimTest._lot
    _veri = tmd.MasrafDagitimTest._veri
    _gm_kur = tmd.MasrafDagitimTest._gm_kur
    _kasa = tmb.MasrafBaglantiTest._kasa
    _gider_fisi = tmb.MasrafBaglantiTest._gider_fisi
    _fis_veri = tmb.MasrafBaglantiTest._fis_veri
    _tablo_sayilari = tmb.MasrafBaglantiTest._tablo_sayilari

    # ------------------------------------------------------------ yardımcı
    def _durum_ve_gecmis(self, did):
        """Lazy temizliği tetiklemeden doğrudan veritabanından okur."""
        from database.models.masraf_dagitim import MasrafDagitim, MasrafDagitimGecmisi

        with get_session() as s:
            d = s.get(MasrafDagitim, did)
            islemler = s.scalars(
                select(MasrafDagitimGecmisi.islem).where(MasrafDagitimGecmisi.dagitim_id == did)
                .order_by(MasrafDagitimGecmisi.id)
            ).all()
            return d.durum, d.geri_alma_nedeni, list(islemler)

    def _bakiye(self, kod) -> Decimal:
        """Hesabın borç - alacak bakiyesi."""
        from database.models.genel_muhasebe import HesapPlani

        with get_session() as s:
            h = s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == kod))
            return Decimal(str(h.borc_toplam)) - Decimal(str(h.alacak_toplam))

    def _fis_sayisi(self, kaynak_turu=None) -> int:
        from database.models.genel_muhasebe import MuhasebeFisi

        with get_session() as s:
            q = select(func.count()).select_from(MuhasebeFisi)
            if kaynak_turu:
                q = q.where(MuhasebeFisi.kaynak_turu == kaynak_turu)
            return int(s.scalar(q))

    def _operasyon_sayilari(self) -> dict[str, int]:
        return {k: v for k, v in self._tablo_sayilari().items() if not k.startswith("muhasebe_")}

    # ------------------------------------------- 1. iptalde aynı transaction
    def test_alis_iptali_taslaklari_ayni_transactionda_iptal_eder(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.masraf_dagitim_service import MasrafDagitimService

        fid, alis_satir = self._alis()
        kaynak_id, ks = self._gider("1000")
        did = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir], tutar="300"))

        # İptal transaction'ı yarıda kalırsa taslak da değişmez (aynı transaction)
        with patch.object(AlisFaturasiService, "_durumlari_guncelle", side_effect=RuntimeError("kesinti")):
            with self.assertRaises(RuntimeError):
                AlisFaturasiService.iptal_et(fid)
        self.assertEqual(self._durum_ve_gecmis(did)[0], "TASLAK")
        with get_session() as s:
            from database.models.alis_faturasi import AlisFaturasi

            self.assertNotEqual(s.get(AlisFaturasi, fid).durum, "İPTAL")

        # Lazy temizlik devre dışıyken bile iptal anında taslak kapanır, geçmiş korunur
        with patch.object(MasrafDagitimService, "sahipsiz_taslaklari_kapat", return_value=0):
            AlisFaturasiService.iptal_et(fid)
        durum, neden, islemler = self._durum_ve_gecmis(did)
        self.assertEqual(durum, "İPTAL EDİLDİ")
        self.assertIn("iptal edildi", neden)
        self.assertEqual(islemler, ["TASLAK OLUŞTUR", "OTOMATİK İPTAL"])

    def test_onayli_dagitimli_alis_iptali_engelli_kalir(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.masraf_dagitim_service import MasrafDagitimService

        fid, alis_satir = self._alis()
        kaynak_id, ks = self._gider("1000")
        onayli = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir], tutar="400"))
        MasrafDagitimService.onayla(onayli)
        taslak = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir], tutar="100"))
        with self.assertRaises(ValueError) as ctx:
            AlisFaturasiService.iptal_et(fid)
        self.assertIn("onaylı masraf dağıtımına bağlı", str(ctx.exception))
        self.assertEqual(self._durum_ve_gecmis(onayli)[0], "ONAYLANDI")
        self.assertEqual(self._durum_ve_gecmis(taslak)[0], "TASLAK")  # iptal gerçekleşmedi, taslak etkilenmez

    def test_kaynak_iptali_ve_alis_duzenlemesi_taslaklari_kapatir(self):
        from database.alis_faturasi_service import AlisFaturasiService
        from database.finans_service import FinansService
        from database.hizmet_faturasi_service import HizmetFaturasiService
        from database.masraf_dagitim_service import MasrafDagitimService

        fid, alis_satir = self._alis()
        fis_id = self._gider_fisi("500")
        kaynak_id, ks = self._gider("800")
        d_fis = MasrafDagitimService.taslak_kaydet(self._fis_veri(fis_id, [alis_satir], tutar="500"))
        d_hiz = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir], tutar="800"))
        with patch.object(MasrafDagitimService, "sahipsiz_taslaklari_kapat", return_value=0):
            FinansService.gider_fisi_iptal(fis_id)
            self.assertEqual(self._durum_ve_gecmis(d_fis)[0], "İPTAL EDİLDİ")
            self.assertEqual(self._durum_ve_gecmis(d_hiz)[0], "TASLAK")
            HizmetFaturasiService.iptal_et(kaynak_id)
            self.assertEqual(self._durum_ve_gecmis(d_hiz)[0], "İPTAL EDİLDİ")

            kaynak2, ks2 = self._gider("200")
            d_alis = MasrafDagitimService.taslak_kaydet(self._veri(kaynak2, ks2, [alis_satir], tutar="200"))
            f = AlisFaturasiService.getir(fid)
            AlisFaturasiService.kaydet(
                {"fatura_tarihi": f.fatura_tarihi, "vade_tarihi": f.vade_tarihi, "cari_id": f.cari_id,
                 "depo": "ANA DEPO", "odeme_tutari": Decimal("0")},
                [{"urun_kodu": "U001", "urun_adi": "U001", "miktar": Decimal("90"), "birim": "Adet",
                  "birim_fiyat": Decimal("100"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20"),
                  "lot_no": "LOT-A"}],
                fatura_id=fid,
            )
            durum, neden, islemler = self._durum_ve_gecmis(d_alis)
        self.assertEqual(durum, "İPTAL EDİLDİ")
        self.assertIn("düzenlendi", neden)
        self.assertEqual(islemler[-1], "OTOMATİK İPTAL")

    # ------------------------------------------- 2. mükerrer maliyet
    def test_eski_masraf_kaynakli_ise_kesin_kaynaksiz_ise_inceleme_gerekli(self):
        from database.alis_masraf_service import AlisMasrafService
        from database.masraf_dagitim_service import KAYNAK_HIZMET, MasrafDagitimService
        from database.models.alis_masraf import AlisMasraf
        from database.models.masraf_dagitim import MasrafDagitim

        fid, alis_satir = self._alis()
        kaynak_id, ks = self._gider("1000")
        diger_id, diger_ks = self._gider("300")
        AlisMasrafService.kaydet_ve_dagit(fid, "NAKLİYE", "500", kaynak_turu=KAYNAK_HIZMET, kaynak_id=kaynak_id)
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("105"))

        # Aynı kaynak belge kimliği → kesin engel
        oniz = MasrafDagitimService.onizle(self._veri(kaynak_id, ks, [alis_satir]))
        self.assertTrue(any("Mükerrer maliyet" in e and "aynı kaynak belge" in e for e in oniz["engeller"]))
        self.assertEqual(oniz["mukerrer_inceleme"], [])
        with self.assertRaises(ValueError) as ctx:
            MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir]))
        self.assertIn("iki kez maliyete yüklenemez", str(ctx.exception))
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(MasrafDagitim)), 0)
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("105"))  # mevcut kayıt korunur

        # Aynı tür (nakliye) ama farklı kaynak belge kimliği → ne engel ne inceleme
        oniz = MasrafDagitimService.onizle(self._veri(diger_id, diger_ks, [alis_satir], tutar="300"))
        self.assertEqual((oniz["engeller"], oniz["mukerrer_inceleme"]), ([], []))

        # Kaynaksız eski masraf: yalnız "inceleme gerekli", otomatik eşleştirme yok
        fid2, satir2 = self._alis("U001", "10", "100", "LOT-B")
        AlisMasrafService.kaydet_ve_dagit(fid2, "NAKLİYE", "20")
        veri = self._veri(diger_id, diger_ks, [satir2], tutar="100")
        oniz = MasrafDagitimService.onizle(veri)
        self.assertEqual(oniz["engeller"], [])
        self.assertEqual(len(oniz["mukerrer_inceleme"]), 1)
        self.assertIn("İnceleme gerekli", oniz["mukerrer_inceleme"][0])
        self.assertIn(oniz["mukerrer_inceleme"][0], oniz["uyarilar"])
        with self.assertRaisesRegex(ValueError, "İnceleme gerekli"):
            MasrafDagitimService.taslak_kaydet(veri)
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(MasrafDagitim)), 0)
        did = MasrafDagitimService.taslak_kaydet(dict(veri, mukerrer_inceleme_onay=True))
        self.assertEqual(MasrafDagitimService.getir(did)["durum"], "TASLAK")
        with get_session() as s:  # mevcut kayıtlar değişmedi
            self.assertEqual([(m.kaynak_turu, m.kaynak_id) for m in s.scalars(select(AlisMasraf).order_by(AlisMasraf.id))],
                             [(KAYNAK_HIZMET, kaynak_id), (None, None)])

        # Farklı türde kaynaksız eski masraf (banka) benzerlik üretmez
        fid3, satir3 = self._alis("U001", "10", "100", "LOT-C")
        AlisMasrafService.kaydet_ve_dagit(fid3, "BANKA", "20")
        oniz = MasrafDagitimService.onizle(self._veri(kaynak_id, ks, [satir3], tutar="100"))
        self.assertEqual((oniz["engeller"], oniz["mukerrer_inceleme"]), ([], []))

    def test_masraf_dagitimi_varken_eski_masraf_kimlikle_kesin_kimliksiz_inceleme(self):
        from database.alis_masraf_service import AlisMasrafService
        from database.masraf_dagitim_service import KAYNAK_HIZMET, MasrafDagitimService
        from database.models.alis_masraf import AlisMasraf

        fid, alis_satir = self._alis()
        kaynak_id, ks = self._gider("1000")
        diger_id, _dks = self._gider("300")
        did = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir], tutar="400"))
        ayni_kaynak = {"kaynak_turu": KAYNAK_HIZMET, "kaynak_id": kaynak_id}
        with self.assertRaises(ValueError) as ctx:  # taslak da yeterli
            AlisMasrafService.kaydet_ve_dagit(fid, "DİĞER", "400", **ayni_kaynak)
        self.assertIn("iki kez maliyete yüklenemez", str(ctx.exception))
        self.assertIn("aynı kaynak belge", str(ctx.exception))
        MasrafDagitimService.onayla(did)
        no = MasrafDagitimService.getir(did)["kaynak_no"]
        for tur, aciklama in (("NAKLİYE", None), ("DİĞER", f"{no} faturası")):
            with self.subTest(tur=tur), self.assertRaisesRegex(ValueError, "İnceleme gerekli"):
                AlisMasrafService.kaydet_ve_dagit(fid, tur, "400", aciklama=aciklama)
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(AlisMasraf)), 0)
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("104"))

        # Ön kontrol kayıt yapmadan aynı sınıflamayı verir
        self.assertEqual(AlisMasrafService.mukerrer_on_kontrol(fid, "DİĞER", **ayni_kaynak)["inceleme"], [])
        self.assertEqual(len(AlisMasrafService.mukerrer_on_kontrol(fid, "DİĞER", **ayni_kaynak)["kesin"]), 1)
        on = AlisMasrafService.mukerrer_on_kontrol(fid, "NAKLİYE")
        self.assertEqual((on["kesin"], len(on["inceleme"])), ([], 1))

        # Farklı kaynak belge kimliği → serbest; kimliksiz ama onaylı → kaydedilir
        AlisMasrafService.kaydet_ve_dagit(fid, "NAKLİYE", "100", kaynak_turu=KAYNAK_HIZMET, kaynak_id=diger_id)
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("105"))
        AlisMasrafService.kaydet_ve_dagit(fid, "NAKLİYE", "100", inceleme_onaylandi=True)
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("106"))
        AlisMasrafService.kaydet_ve_dagit(fid, "NAKLİYE", "50", maliyete_dahil=False)
        with get_session() as s:
            self.assertEqual([(m.kaynak_turu, m.kaynak_id) for m in s.scalars(select(AlisMasraf).order_by(AlisMasraf.id))],
                             [(KAYNAK_HIZMET, diger_id), (None, None), (None, None)])
        self.assertEqual(AlisMasrafService.masraflari(fid)[0]["kaynak_id"], diger_id)

        # Eksik / geçersiz kaynak bilgisi kayıt üretmez
        for hatali, mesaj in (({"kaynak_turu": KAYNAK_HIZMET}, "birlikte"),
                              ({"kaynak_turu": KAYNAK_HIZMET, "kaynak_id": 999999}, "bulunamadı"),
                              ({"kaynak_turu": "YOK", "kaynak_id": kaynak_id}, "birlikte")):
            with self.subTest(hatali=hatali), self.assertRaisesRegex(ValueError, mesaj):
                AlisMasrafService.kaydet_ve_dagit(fid, "NAKLİYE", "10", **hatali)
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(AlisMasraf)), 3)

        # Dağıtım geri alınınca aynı kaynakla eski yol kullanılabilir
        self.assertTrue(MasrafDagitimService.geri_al(did, "eski sisteme taşındı"))
        AlisMasrafService.kaydet_ve_dagit(fid, "NAKLİYE", "400", **ayni_kaynak)
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("106"))

    def test_mukerrer_raporu_mevcut_cakismalari_duzeltmeden_listeler(self):
        from database.masraf_dagitim_service import MasrafDagitimService
        from database.models.alis_masraf import AlisMasraf, AlisMasrafDagitim

        fid, alis_satir = self._alis()
        kaynak_id, ks = self._gider("1000")
        did = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir]))
        MasrafDagitimService.onayla(did)
        self.assertEqual(MasrafDagitimService.mukerrer_masraf_raporu(), [])
        idler = {}
        with get_session() as s:  # eski sürümden kalmış çakışan kayıtlar (kontrol öncesi)
            for ad, tur, k_tur, k_id in (("kaynaksiz", "NAKLİYE", None, None),
                                         ("ayni", "DİĞER", "HIZMET_FATURASI", kaynak_id),
                                         ("farkli", "NAKLİYE", "HIZMET_FATURASI", kaynak_id + 1000)):
                m = AlisMasraf(fatura_id=fid, masraf_turu=tur, tutar=Decimal("1000"), dagitim_yontemi="TUTAR",
                               maliyete_dahil=True, kaynak_turu=k_tur, kaynak_id=k_id)
                m.dagitimlar.append(AlisMasrafDagitim(fatura_satiri_id=alis_satir, tutar=Decimal("1000"), oran=1))
                s.add(m)
                s.flush()
                idler[ad] = m.id
        once = self._tablo_sayilari()
        lot_once = Decimal(str(self._lot().birim_maliyet))
        rapor = MasrafDagitimService.mukerrer_masraf_raporu()
        self.assertEqual(sorted((r["eski_masraf_id"], r["durum"]) for r in rapor),
                         sorted([(idler["kaynaksiz"], "inceleme gerekli"), (idler["ayni"], "kesin")]))
        for r in rapor:
            self.assertEqual(r["alis_fatura_id"], fid)
            self.assertIn("MD000001", r["mesaj"])
            self.assertIn("İnceleme gerekli" if r["durum"] != "kesin" else "Mükerrer maliyet", r["mesaj"])
        self.assertEqual(self._tablo_sayilari(), once)
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), lot_once)
        self.assertEqual(MasrafDagitimService.getir(did)["durum"], "ONAYLANDI")

    def test_eski_tabloya_kaynak_kolonlari_eklenir_kayitlar_degismez(self):
        import tempfile

        from sqlalchemy import create_engine, inspect, text

        from database.alis_masraf_service import kaynak_kolonlarini_hazirla

        with tempfile.TemporaryDirectory() as klasor:
            eng = create_engine(f"sqlite:///{Path(klasor).as_posix()}/eski.db")
            with eng.begin() as b:
                b.execute(text("CREATE TABLE alis_masraflari (id INTEGER PRIMARY KEY, fatura_id INTEGER NOT NULL, "
                               "masraf_turu VARCHAR(50) NOT NULL, tutar NUMERIC(18,2) NOT NULL, "
                               "dagitim_yontemi VARCHAR(20) NOT NULL, maliyete_dahil BOOLEAN NOT NULL, "
                               "aciklama TEXT, olusturma_tarihi DATETIME NOT NULL)"))
                b.execute(text("INSERT INTO alis_masraflari VALUES (1, 7, 'NAKLİYE', 250, 'TUTAR', 1, 'eski', "
                               "'2026-01-01 00:00:00')"))
            for _ in range(2):  # tekrar çalıştırma güvenli
                kaynak_kolonlarini_hazirla(eng)
            kolonlar = {k["name"] for k in inspect(eng).get_columns("alis_masraflari")}
            self.assertTrue({"kaynak_turu", "kaynak_id"} <= kolonlar)
            with eng.connect() as b:
                self.assertEqual(
                    tuple(b.execute(text("SELECT id, fatura_id, masraf_turu, tutar, aciklama, kaynak_turu, kaynak_id "
                                         "FROM alis_masraflari")).one()),
                    (1, 7, "NAKLİYE", 250, "eski", None, None),
                )
            eng.dispose()

    # ------------------------------------------- 3. genel muhasebe
    def test_gider_fisi_gm_kaydi_dagitim_ve_geri_alma_bakiyeleri(self):
        from database.finans_service import FinansService
        from database.masraf_dagitim_service import MasrafDagitimService, ZatenIslendi

        self._gm_kur()
        _fid, alis_satir = self._alis()
        self._sat("40")
        with patch("database.muhasebe_entegrasyon.muhasebe_hook", _gercek_hook):
            fis_id = self._gider_fisi("1000")
        self.assertEqual(self._fis_sayisi("gider_fisi"), 1)
        self.assertEqual(self._bakiye("770.01.0001"), Decimal("1000"))
        self.assertEqual(self._bakiye("100.01.0001"), Decimal("-1000"))

        oniz = MasrafDagitimService.onizle(self._fis_veri(fis_id, [alis_satir]))
        self.assertEqual(oniz["engeller"], [])
        did = MasrafDagitimService.taslak_kaydet(self._fis_veri(fis_id, [alis_satir]))
        once = self._operasyon_sayilari()
        fis_once = self._fis_sayisi()
        sonuc = MasrafDagitimService.onayla(did)
        self.assertIsNotNone(sonuc["fis_id"])
        self.assertEqual(self._fis_sayisi(), fis_once + 1)  # yalnız dağıtım fişi; gider fişi tekrar yazılmaz
        self.assertEqual(self._operasyon_sayilari(), once)  # kasa/cari/KDV/hizmet hareketi yok
        # Gider tamamen stok/SMM'ye aktarıldı: kâr iki kez azalmaz
        self.assertEqual(self._bakiye("770.01.0001"), Decimal("0"))
        self.assertEqual(self._bakiye("153.01.0001"), Decimal("600"))
        self.assertEqual(self._bakiye("621.01.0001"), Decimal("400"))
        self.assertEqual(self._bakiye("100.01.0001"), Decimal("-1000"))

        with self.assertRaises(ZatenIslendi):
            MasrafDagitimService.onayla(did)
        self.assertEqual(self._fis_sayisi(), fis_once + 1)

        self.assertTrue(MasrafDagitimService.geri_al(did, "test"))
        self.assertFalse(MasrafDagitimService.geri_al(did, "tekrar"))
        self.assertEqual(self._fis_sayisi("masraf_dagitimi_geri"), 1)
        self.assertEqual(self._bakiye("770.01.0001"), Decimal("1000"))
        self.assertEqual(self._bakiye("153.01.0001"), Decimal("0"))
        self.assertEqual(self._bakiye("621.01.0001"), Decimal("0"))

        from database.models.genel_muhasebe import MuhasebeFisi

        with get_session() as s:
            gider_gm_id = s.scalar(select(MuhasebeFisi.id).where(MuhasebeFisi.kaynak_turu == "gider_fisi"))
        with patch("database.muhasebe_entegrasyon.muhasebe_hook", _gercek_hook):
            FinansService.gider_fisi_iptal(fis_id)
        with get_session() as s:
            gider_gm = s.get(MuhasebeFisi, gider_gm_id)
            self.assertEqual(gider_gm.durum, "İptal")
            self.assertIsNotNone(gider_gm.ters_fis_id)
        self.assertEqual(self._fis_sayisi("gider_fisi"), 0)
        self.assertEqual(self._bakiye("770.01.0001"), Decimal("0"))
        self.assertEqual(self._bakiye("100.01.0001"), Decimal("0"))

    def test_gm_kaydi_olmayan_gider_fisi_onayda_bir_kez_tamamlanir(self):
        from database.masraf_dagitim_service import MasrafDagitimService
        from database.models.finans import FinansHareketi

        self._gm_kur()
        _fid, alis_satir = self._alis()
        fis_id = self._gider_fisi("1000")  # eski kayıt gibi: GM fişi yok
        self.assertEqual(self._fis_sayisi("gider_fisi"), 0)
        oniz = MasrafDagitimService.onizle(self._fis_veri(fis_id, [alis_satir], tutar="400"))
        self.assertEqual(oniz["engeller"], [])
        self.assertTrue(any("muhasebeye kayıtlı değil" in u for u in oniz["uyarilar"]))

        with get_session() as s:
            kasa_hareket = s.scalar(select(func.count()).select_from(FinansHareketi))
        d1 = MasrafDagitimService.taslak_kaydet(self._fis_veri(fis_id, [alis_satir], tutar="400"))
        MasrafDagitimService.onayla(d1)
        d2 = MasrafDagitimService.taslak_kaydet(self._fis_veri(fis_id, [alis_satir], tutar="600"))
        MasrafDagitimService.onayla(d2)
        self.assertEqual(self._fis_sayisi("gider_fisi"), 1)
        with get_session() as s:
            mevcut = MasrafDagitimService._kaynak_gm_fis_id(s, GIDER_FISI, fis_id)
        self.assertEqual(MasrafDagitimService.kaynak_gm_fisi_tamamla(GIDER_FISI, fis_id), mevcut)
        self.assertEqual(self._fis_sayisi("gider_fisi"), 1)
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count()).select_from(FinansHareketi)), kasa_hareket)
        self.assertEqual(self._bakiye("770.01.0001"), Decimal("0"))
        self.assertEqual(self._bakiye("153.01.0001"), Decimal("1000"))
        self.assertEqual(self._bakiye("100.01.0001"), Decimal("-1000"))

    def test_hizmet_faturasi_gm_kaydi_onayda_tamamlanir(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        self._gm_kur()
        _fid, alis_satir = self._alis()
        kaynak_id, ks = self._gider("1000")
        did = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir]))
        MasrafDagitimService.onayla(did)
        self.assertEqual(self._fis_sayisi("hizmet_faturasi"), 1)
        self.assertEqual(self._bakiye("191.01.0001"), Decimal("200"))  # KDV maliyete eklenmez
        self.assertEqual(self._bakiye("320.01.0001"), Decimal("-1200"))
        self.assertEqual(self._bakiye("770.01.0001"), Decimal("0"))
        self.assertEqual(self._bakiye("153.01.0001"), Decimal("1000"))

    def test_eksik_esleme_onizleme_ve_onayda_hangi_hesap_oldugunu_soyler(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        for eksik, beklenen in ((("kasa",), "Kasa hesabı (kasa)"),
                                (("ticari_mallar",), "Ticari mallar / stok hesabı (ticari_mallar)")):
            with self.subTest(eksik=eksik):
                self.tearDown()
                self.setUp()
                self._gm_kur(eksik=eksik)
                _fid, alis_satir = self._alis()
                fis_id = self._gider_fisi("1000")
                oniz = MasrafDagitimService.onizle(self._fis_veri(fis_id, [alis_satir]))
                self.assertTrue(any(beklenen in e for e in oniz["engeller"]), oniz["engeller"])
                did = MasrafDagitimService.taslak_kaydet(self._fis_veri(fis_id, [alis_satir]))
                fis_once = self._fis_sayisi()
                with self.assertRaises(ValueError) as ctx:
                    MasrafDagitimService.onayla(did)
                self.assertIn("Onay engellendi", str(ctx.exception))
                self.assertIn(beklenen, str(ctx.exception))
                self.assertIn("Hesap Eşleştirmeleri", str(ctx.exception))
                self.assertEqual(self._fis_sayisi(), fis_once)  # kaynak fişi de yazılmadı
                self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("100"))
                self.assertEqual(MasrafDagitimService.getir(did)["durum"], "TASLAK")

    def test_hic_esleme_olmayan_firmada_onay_engelli_belgeler_kaydedilir(self):
        from database.finans_service import FinansService
        from database.masraf_dagitim_service import MasrafDagitimService
        from database.models.genel_muhasebe import MuhasebeHesapEsleme

        with get_session() as s:
            for e in s.scalars(select(MuhasebeHesapEsleme)).all():
                s.delete(e)
        # Muhasebe kullanılmayan firmada belgeler kaydedilmeye devam eder (entegrasyon fişsiz geçer)
        with patch("database.muhasebe_entegrasyon.muhasebe_hook", _gercek_hook_guvenli):
            _fid, alis_satir = self._alis()
            self._sat("40")
            kaynak_id, ks = self._gider("1000")
            fis_id = self._gider_fisi("500")
        self.assertEqual(self._fis_sayisi(), 0)

        for veri, beklenenler in (
            (self._veri(kaynak_id, ks, [alis_satir]),
             ("(giderler)", "(ticari_mallar)", "(satilan_mal_maliyeti)", "(tedarikciler)", "(indirilecek_kdv)")),
            (self._fis_veri(fis_id, [alis_satir], tutar="500"), ("(giderler)", "(kasa)")),
        ):
            oniz = MasrafDagitimService.onizle(veri)
            metin = "\n".join(oniz["engeller"])
            for anahtar in beklenenler:
                self.assertIn(anahtar, metin)
            self.assertIn("Genel Muhasebe > Hesap Eşleştirmeleri", metin)
            did = MasrafDagitimService.taslak_kaydet(veri)  # taslak serbest, onay engelli
            with self.assertRaises(ValueError) as ctx:
                MasrafDagitimService.onayla(did)
            self.assertIn("Onay engellendi", str(ctx.exception))
            self.assertEqual(MasrafDagitimService.getir(did)["durum"], "TASLAK")
        self.assertEqual(self._fis_sayisi(), 0)
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("100"))
        FinansService.gider_fisi_iptal(fis_id)

    def test_kaydi_olmayan_kaynak_belge_fisi_bir_kez_olusur_hata_olursa_hic_kalmaz(self):
        from database.masraf_dagitim_service import MasrafDagitimService, ZatenIslendi
        from database.models.genel_muhasebe import MuhasebeFisiSatiri, MuhasebeIslemGecmisi

        _fid, alis_satir = self._alis()
        fis_id = self._gider_fisi("1000")  # GDF-2026-0001 gibi: GM kaydı yok
        kaynak_id, ks = self._gider("1000")  # HAG000002 gibi: GM kaydı yok
        self.assertEqual(self._fis_sayisi(), 0)
        durumlar = (
            ("gider_fisi", lambda tutar: self._fis_veri(fis_id, [alis_satir], tutar=tutar)),
            ("hizmet_faturasi", lambda tutar: self._veri(kaynak_id, ks, [alis_satir], tutar=tutar)),
        )
        iz_once = 0

        def _yarim_kayit_yok():
            self.assertEqual(self._fis_sayisi(), 0)
            with get_session() as s:
                self.assertEqual(s.scalar(select(func.count()).select_from(MuhasebeFisiSatiri)), 0)
                self.assertEqual(s.scalar(select(func.count()).select_from(MuhasebeIslemGecmisi)), iz_once)
            self.assertEqual({k: v for k, v in self._bakiyeler().items() if v}, {})
            self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("100"))

        for gm_tur, veri in durumlar:
            with self.subTest(kaynak=gm_tur):
                with get_session() as s:  # açılış geçişinin kendi izi dışında yeni iz olmamalı
                    iz_once = s.scalar(select(func.count()).select_from(MuhasebeIslemGecmisi))
                # a) Araya enjekte edilmiş hata: kaynak fişi yazıldıktan sonra dağıtım fişinde patlar
                did = MasrafDagitimService.taslak_kaydet(veri("1000"))
                with patch.object(MasrafDagitimService, "_gm_fisi_yaz", side_effect=RuntimeError("kesinti")):
                    with self.assertRaises(RuntimeError):
                        MasrafDagitimService.onayla(did)
                _yarim_kayit_yok()
                self.assertEqual(MasrafDagitimService.getir(did)["durum"], "TASLAK")

                # b) Eşleştirme eksik
                self._gm_kur(eksik=("satilan_mal_maliyeti", "ticari_mallar"))
                with self.assertRaises(ValueError):
                    MasrafDagitimService.onayla(did)
                _yarim_kayit_yok()
                self._gm_kur()

                # c) Kalan tutar aşımı: iki taslak aynı tutarı ister; ilki onaylanınca ikincisi reddedilir
                d2 = MasrafDagitimService.taslak_kaydet(veri("600"))
                MasrafDagitimService.onayla(did)
                self.assertEqual(self._fis_sayisi(gm_tur), 1)
                fis_once = self._fis_sayisi()
                with self.assertRaises(ValueError) as ctx:
                    MasrafDagitimService.onayla(d2)
                self.assertIn("aşamaz", str(ctx.exception))
                self.assertEqual(self._fis_sayisi(), fis_once)

                # d) Tekrar onay / geri alma / yeniden dağıtım kaynak fişini tekrar yazmaz
                with self.assertRaises(ZatenIslendi):
                    MasrafDagitimService.onayla(did)
                self.assertTrue(MasrafDagitimService.geri_al(did, "test"))
                d3 = MasrafDagitimService.taslak_kaydet(veri("1000"))
                MasrafDagitimService.onayla(d3)
                self.assertEqual(self._fis_sayisi(gm_tur), 1)
                self.assertEqual(self._fis_sayisi("masraf_dagitimi"), 2)
                self.assertTrue(MasrafDagitimService.geri_al(d3, "temizlik"))
                MasrafDagitimService.iptal_et(d2, "temizlik")
                self._fis_temizle()

    # ------------------------------------------------------------ yardımcı
    def _bakiyeler(self) -> dict[str, Decimal]:
        from database.models.genel_muhasebe import HesapPlani

        with get_session() as s:
            return {h.hesap_kodu: Decimal(str(h.borc_toplam)) - Decimal(str(h.alacak_toplam))
                    for h in s.scalars(select(HesapPlani)).all()}

    def _fis_temizle(self):
        """Alt senaryolar arası GM tablolarını sıfırlar (yalnız izole test veritabanı)."""
        from database.models.genel_muhasebe import (
            HesapPlani,
            MuhasebeBelgeDurumu,
            MuhasebeFisi,
            MuhasebeFisiSatiri,
            MuhasebeIslemGecmisi,
        )

        with get_session() as s:
            for model in (MuhasebeFisiSatiri, MuhasebeIslemGecmisi, MuhasebeBelgeDurumu):
                for r in s.scalars(select(model)).all():
                    s.delete(r)
            s.flush()
            fisler = s.scalars(select(MuhasebeFisi)).all()
            for f in fisler:
                f.ters_fis_id = None
            s.flush()
            for f in fisler:
                s.delete(f)
            for h in s.scalars(select(HesapPlani)).all():
                h.borc_toplam = 0
                h.alacak_toplam = 0


def _gercek_hook_guvenli(fn_name, *args, **kwargs):
    """Uygulamadaki muhasebe_hook gibi: eşleştirme eksikse fiş yazmadan sessizce geçer."""
    from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

    fn = getattr(MuhasebeEntegrasyonService, fn_name)
    return MuhasebeEntegrasyonService._guvenli(fn, *args, **kwargs)


if __name__ == "__main__":
    unittest.main()
