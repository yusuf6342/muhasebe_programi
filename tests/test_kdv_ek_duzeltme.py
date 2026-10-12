"""KDV ek düzeltme: EVO başlık KDV'si 0, gerçek %0, eksik KDV, iade kaynağı, özel KDV bilgisi,
hatalı fiş listesi / önizleme / kontrollü düzeltme (izole DB; gerçek firma verisine dokunulmaz)."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select, update  # noqa: E402

from database import belge_kdv  # noqa: E402
from database import kdv_fis_duzeltme_service as dz  # noqa: E402
from database import kdv_rapor_service as srv  # noqa: E402
from database.access import AccessError  # noqa: E402
from database.database import get_session  # noqa: E402
from tests.test_kdv_raporu import EYLUL, _satir, _Taban  # noqa: E402

HESAPLAR = (
    ("musteriler", "120.01.0001", "Aktif"), ("yurtici_satislar", "600.01.0001", "Gelir"),
    ("hesaplanan_kdv", "391.01.0001", "Pasif"), ("satistan_iadeler", "610.01.0001", "Gelir"),
    ("tedarikciler", "320.01.0001", "Pasif"), ("indirilecek_kdv", "191.01.0001", "Aktif"),
    ("ticari_mallar", "153.01.0001", "Aktif"), ("giderler", "770.01.0001", "Gider"),
)


class _EkTaban(_Taban):
    def setUp(self):
        super().setUp()
        self.alis(date(2026, 9, 1), [_satir(50, 50), _satir(50, 40, kod="U002")])

    def esleme(self) -> dict[str, int]:
        from database.models.genel_muhasebe import HesapPlani, MuhasebeHesapEsleme
        from database.muhasebe_service import MuhasebeService

        idler = {}
        with get_session() as s:
            fid = MuhasebeService.yerel_firma_id(s)
            for anahtar, kod, tur in HESAPLAR:
                h = s.scalar(select(HesapPlani).where(HesapPlani.hesap_kodu == kod))
                if h is None:
                    h = HesapPlani(firma_id=fid, hesap_kodu=kod, hesap_adi=kod, hesap_seviyesi=3, hesap_turu=tur,
                                   borc_toplam=0, alacak_toplam=0, aktif=True)
                    s.add(h)
                    s.flush()
                s.add(MuhasebeHesapEsleme(firma_id=fid, anahtar=anahtar, aciklama=anahtar, hesap_id=h.id, aktif=True))
                idler[kod] = h.id
        return idler

    def evo_yap(self, f, **ek):
        from database.models.satis_faturasi import SatisFaturasi

        with get_session() as s:
            s.execute(update(SatisFaturasi).where(SatisFaturasi.id == f.id).values(tl_matrah=0, tl_kdv=0, **ek))

    def belge(self, r, no):
        return next(x for x in r["belgeler"] if x["no"] == no)

    def eski_hatali_fis(self, f, idler, cari=None, satis_tutar=None):
        """Önceki sürümün EVO faturasında yazdığı fiş: KDV 0, matrah = genel toplam."""
        from database.muhasebe_service import MuhasebeFisService

        genel = D(str(f.tl_genel_toplam))
        return MuhasebeFisService.kaydet({
            "fis_tarihi": f.fatura_tarihi, "fis_turu": "Mahsup Fişi", "aciklama": "eski", "belge_no": f.fatura_no,
            "durum": "Kesinleşmiş", "kaynak_turu": "satis_faturasi", "kaynak_id": f.id,
            "satirlar": [{"hesap_id": idler["120.01.0001"], "borc": cari or genel, "alacak": D("0")},
                         {"hesap_id": idler["600.01.0001"], "borc": D("0"), "alacak": satis_tutar or cari or genel}],
        }, otomatik=True)

    def fis_sayisi(self, kaynak):
        from database.models.genel_muhasebe import MuhasebeFisi

        with get_session() as s:
            return int(s.scalar(select(func.count(MuhasebeFisi.id)).where(MuhasebeFisi.kaynak_turu == kaynak)) or 0)


class BelgeKdvKaynagi(_EkTaban):
    def test_evo_baslik_sifir_satirda_kdv_cok_oran_iskonto_yuvarlama(self):
        f = self.satis(date(2026, 9, 5), [_satir(2, "33.33", iskonto_orani=D("10")),
                                          _satir(1, 100, kdv="10", kod="U002")])
        beklenen_kdv = D(str(f.tl_kdv))
        self.evo_yap(f)
        b = self.belge(srv.rapor(*EYLUL), f.fatura_no)
        self.assertEqual(b["kdv"], beklenen_kdv)
        self.assertEqual(b["kdv_durum"], belge_kdv.DURUM_ADI[belge_kdv.SATIRDAN])
        self.assertEqual(b["sorun"], "")
        self.assertIn("satırlardan", belge_kdv.kdv_baslik_eki("satis_faturasi", f.id))

        idler = self.esleme()
        from database.models.genel_muhasebe import MuhasebeFisiSatiri
        from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

        fis_id = MuhasebeEntegrasyonService.satis_faturasi_fisi(f.id)
        with get_session() as s:
            kdv = sum((D(str(x.alacak)) for x in s.scalars(select(MuhasebeFisiSatiri).where(
                MuhasebeFisiSatiri.fis_id == fis_id, MuhasebeFisiSatiri.hesap_id == idler["391.01.0001"]))), D("0"))
        self.assertEqual(kdv, beklenen_kdv)

    def test_satirlar_toplami_tutmazsa_eksik_tahmin_yok_fis_bekler(self):
        from database.muhasebe_entegrasyon import AyarEksik, MuhasebeEntegrasyonService

        f = self.satis(date(2026, 9, 5), [_satir(2, 150)])
        self.evo_yap(f, tl_genel_toplam=D("500.00"))
        r = srv.rapor(*EYLUL)
        b = self.belge(r, f.fatura_no)
        self.assertEqual((b["kdv"], b["toplam"]), (D("0"), D("500.00")))
        self.assertEqual(b["kdv_durum"], belge_kdv.DURUM_ADI[belge_kdv.EKSIK])
        self.assertIn(srv.S_KDV_YOK, b["sinif"])
        self.assertEqual(r["toplamlar"]["belirsiz_brut"], D("500.00"))
        self.assertEqual(r["toplamlar"]["SATIS_kdv"], D("0"))
        self.assertTrue(any(x["sinif"] == srv.S_KDV_YOK and x["belge"] == 1 for x in r["siniflar"]))
        self.assertIn("belirlenemedi", belge_kdv.kdv_baslik_eki("satis_faturasi", f.id))
        self.esleme()
        with self.assertRaises(AyarEksik):
            MuhasebeEntegrasyonService.satis_faturasi_fisi(f.id)
        self.assertIn("tahmin edilmedi", MuhasebeEntegrasyonService.karar_bekleyen_neden("satis_faturasi", f.id))
        aylik = srv.rapor(*EYLUL)["aylik"][0]
        self.assertEqual(aylik["durum"], srv.EKSIK_ON_HESAP)
        self.assertGreaterEqual(aylik["etkilenen"], 1)

    def test_gercek_yuzde_sifir_istisna_sayilmaz(self):
        f = self.satis(date(2026, 9, 5), [_satir(1, 100, kdv="0")])
        r = srv.rapor(*EYLUL)
        b = self.belge(r, f.fatura_no)
        self.assertEqual((b["kdv"], b["sorun"]), (D("0.00"), ""))
        self.assertIn(b["kdv_durum"], (belge_kdv.DURUM_ADI[belge_kdv.KAYITLI],
                                        belge_kdv.DURUM_ADI[belge_kdv.SIFIR_KDV]))
        self.assertEqual(b["islem"], srv.INDIRILEBILIRLIK_YOK)
        self.assertEqual(r["toplamlar"]["h_istisna_matrah"], D("0"))
        self.evo_yap(f)
        b = self.belge(srv.rapor(*EYLUL), f.fatura_no)
        self.assertEqual(b["kdv_durum"], belge_kdv.DURUM_ADI[belge_kdv.SIFIR_KDV])
        self.assertEqual(b["sorun"], "")


class IadeKaynagi(_EkTaban):
    def test_kaynaksiz_iade_bagla_ve_kaynak_yok_bir_kez_sayilir(self):
        from database import kdv_belge_bilgi_service as kb
        from database.satis_iade_faturasi_service import SatisIadeFaturasiService

        f = self.satis(date(2026, 9, 5), [_satir(3, 150)])
        veri = {"cari_id": self.o.mus_id, "depo": "ANA DEPO", "aciklama": None, "iade_odeme_tutari": 0}
        i1 = SatisIadeFaturasiService.kaydet({"iade_tarihi": date(2026, 9, 10), **veri}, [_satir(1, 150)])
        i2 = SatisIadeFaturasiService.kaydet({"iade_tarihi": date(2026, 9, 11), **veri}, [_satir(1, 150)])
        r = srv.rapor(*EYLUL)
        for i in (i1, i2):
            self.assertIn(srv.S_KAYNAK, self.belge(r, i.iade_no)["sinif"])
        self.assertEqual(r["toplamlar"]["SATIS_IADE_kdv"], D("60.00"))

        adaylar = kb.kaynak_adaylari(srv.SATIS_IADE, i1.id)
        self.assertEqual([a["id"] for a in adaylar], [f.id])
        s = kb.kaynak_bagla(srv.SATIS_IADE, i1.id, f.id)
        self.assertEqual(s["satir_baglandi"], 1)
        kb.kaynak_yok_kaydet(srv.SATIS_IADE, i2.id, "Devir öncesi satış")
        with self.assertRaises(ValueError):
            kb.kaynak_yok_kaydet(srv.SATIS_IADE, i1.id, "bağlı iade")
        r = srv.rapor(*EYLUL)
        self.assertEqual(self.belge(r, i1.iade_no)["sorun"], "")
        self.assertEqual(self.belge(r, i2.iade_no)["sorun"], "")
        self.assertTrue(self.belge(r, i2.iade_no)["not"])
        self.assertEqual(r["toplamlar"]["SATIS_IADE_kdv"], D("60.00"))
        self.assertEqual(r["toplamlar"]["SATIS_kdv"], D("90.00"))
        self.assertEqual(self.belge(r, i1.iade_no)["toplam"], D("180.00"))


class OzelKdvBilgisi(_EkTaban):
    def test_indirilebilirlik_tevkifat_istisna_ve_desteklenmeyen(self):
        from database import kdv_belge_bilgi_service as kb

        a_ind = self.alis(date(2026, 9, 2), [_satir(1, 100)])
        a_kkeg = self.alis(date(2026, 9, 2), [_satir(1, 200)])
        a_tev = self.alis(date(2026, 9, 2), [_satir(1, 1000)])
        s_tev = self.satis(date(2026, 9, 3), [_satir(1, 500)])
        s_ist = self.satis(date(2026, 9, 3), [_satir(1, 100)])
        s_oz = self.satis(date(2026, 9, 3), [_satir(1, 50)])
        once = srv.rapor(*EYLUL)["toplamlar"]
        self.assertEqual(once["net_kesin_indirilecek"], D("0"))
        self.assertEqual(once["net_belirsiz"], once["net_alis_kdv"])

        kb.bilgi_kaydet(srv.ALIS, a_ind.id, indirilebilirlik="INDIRILECEK")
        kb.bilgi_kaydet(srv.ALIS, a_kkeg.id, indirilebilirlik="KKEG")
        kb.bilgi_kaydet(srv.ALIS, a_tev.id, indirilebilirlik="INDIRILECEK", islem_turu="TEVKIFAT",
                        tevkifat_pay=5, tevkifat_payda=10)
        kb.bilgi_kaydet(srv.SATIS, s_tev.id, islem_turu="TEVKIFAT", tevkifat_pay=5, tevkifat_payda=10)
        kb.bilgi_kaydet(srv.SATIS, s_ist.id, islem_turu="ISTISNA", istisna_kodu="301")
        kb.bilgi_kaydet(srv.SATIS, s_oz.id, islem_turu="OZEL_MATRAH")
        with self.assertRaises(ValueError):
            kb.bilgi_kaydet(srv.SATIS, s_tev.id, indirilebilirlik="INDIRILECEK")
        with self.assertRaises(ValueError):
            kb.bilgi_kaydet(srv.SATIS, s_tev.id, islem_turu="TEVKIFAT", tevkifat_pay=11, tevkifat_payda=10)

        r = srv.rapor(*EYLUL)
        t = r["toplamlar"]
        # Alıcı tevkifatta KDV'nin tamamını indirir; tevkif edilen kısım KDV-2'de beyan edilir
        self.assertEqual(t["net_kesin_indirilecek"], D("20.00") + D("200.00"))
        self.assertEqual(t["kdv2"], D("100.00"))
        self.assertEqual(t["net_indirilemez"], D("40.00"))
        self.assertEqual(t["tevkifat_satis"], D("50.00"))
        self.assertEqual(t["desteklenmeyen_hesaplanan"], D("10.00"))
        self.assertEqual(t["h_istisna_matrah"], D("100.00"))
        self.assertIn(srv.S_OZEL, self.belge(r, s_ist.fatura_no)["sinif"])       # istisnada KDV var
        self.assertIn(srv.S_OZEL, self.belge(r, s_oz.fatura_no)["sinif"])
        self.assertEqual(self.belge(r, a_kkeg.fatura_no)["indirilebilirlik"], "İndirilemez — KKEG")

    def test_yetkisiz_kullanici_kdv_bilgisi_ve_duzeltme_yapamaz(self):
        from database import kdv_belge_bilgi_service as kb
        from database.session_manager import oturum

        f = self.satis(date(2026, 9, 5), [_satir(1, 100)])
        oturum.set_user(user_id=3, kullanici_adi="izleyici", ad_soyad="İzleyici", role_kod="GORUNTULEME",
                        role_ad="Görüntüleme", permissions={srv.GORUNTULEME_YETKISI})
        with self.assertRaises(AccessError):
            kb.bilgi_kaydet(srv.SATIS, f.id, islem_turu="NORMAL")
        with self.assertRaises(AccessError):
            dz.duzelt([(srv.SATIS, f.id)], "deneme")
        self.assertFalse(dz.hatali_fisler(*EYLUL)["aktif"])


class HataliFisDuzeltme(_EkTaban):
    def test_liste_onizleme_duzeltme_tekrar_mukerrer_yok_ve_yeniden_muhasebe(self):
        from database.models.genel_muhasebe import MuhasebeFisi, MuhasebeFisiSatiri
        from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService

        idler = self.esleme()
        f = self.satis(date(2026, 9, 5), [_satir(2, 150), _satir(1, 100, kdv="10", kod="U002")])
        self.evo_yap(f)
        self.eski_hatali_fis(f, idler)
        self.gm_ac()
        cari_once = self._hareket_sayilari()

        liste = dz.hatali_fisler(*EYLUL)
        row = next(x for x in liste["satirlar"] if x["no"] == f.fatura_no)
        self.assertEqual((row["fis_kdv"], row["beklenen_kdv"], row["fark"]), (D("0"), D("70.00"), D("70.00")))
        self.assertTrue(row["duzeltilebilir"])
        o = dz.duzeltme_onizleme(srv.SATIS, f.id)
        self.assertTrue(o["duzeltilebilir"], o["neden"])
        self.assertEqual([(x["hesap_kodu"], x["borc"], x["alacak"]) for x in o["satirlar"]],
                         [("600.01.0001", D("70.00"), D("0")), ("391.01.0001", D("0"), D("70.00"))])
        self.assertEqual(self.fis_sayisi("kdv_duz_satis_faturasi"), 0)   # önizleme yazmaz

        s1 = dz.duzelt([(srv.SATIS, f.id)], "EVO aktarımı KDV düzeltmesi")
        self.assertEqual(len(s1["yazilan"]), 1, s1)
        s2 = dz.duzelt([(srv.SATIS, f.id)], "tekrar")
        self.assertEqual((len(s2["yazilan"]), len(s2["zaten_dogru"])), (0, 1))
        self.assertEqual(self.fis_sayisi("kdv_duz_satis_faturasi"), 1)
        self.assertFalse([x for x in dz.hatali_fisler(*EYLUL)["satirlar"] if x["no"] == f.fatura_no])
        with get_session() as s:
            duz = s.scalar(select(MuhasebeFisi).where(MuhasebeFisi.kaynak_turu == "kdv_duz_satis_faturasi"))
            self.assertEqual(duz.fis_tarihi, f.fatura_tarihi)
            kdv_toplam = sum((D(str(x.alacak)) - D(str(x.borc)) for x in s.scalars(select(MuhasebeFisiSatiri).where(
                MuhasebeFisiSatiri.hesap_id == idler["391.01.0001"]))), D("0"))
        self.assertEqual(kdv_toplam, D("70.00"))
        self.assertEqual(self._hareket_sayilari(), cari_once)
        gm = srv.rapor(*EYLUL)["gm"]
        self.assertFalse([g for g in gm if f.fatura_no in (g.get("belge") or "")
                          and g["kategori"] in ("Tutar / dönem farkı", "Belge dışı muhasebe hareketi")])
        if s1["yedek"]:
            self.assertTrue(Path(s1["yedek"]).is_file())

        MuhasebeEntegrasyonService.satis_faturasi_fisi(f.id, yeniden=True)
        with get_session() as s:
            self.assertEqual(s.get(MuhasebeFisi, duz.id).durum, "İptal")
        self.assertFalse([x for x in dz.hatali_fisler(*EYLUL)["satirlar"] if x["no"] == f.fatura_no])

    def test_kapali_donem_cari_farki_ve_eksik_kdv_duzeltilmez(self):
        idler = self.esleme()
        f1 = self.satis(date(2026, 9, 5), [_satir(1, 100)])
        self.evo_yap(f1)
        self.eski_hatali_fis(f1, idler)
        f2 = self.satis(date(2026, 9, 6), [_satir(1, 200)])
        self.evo_yap(f2)
        self.eski_hatali_fis(f2, idler, cari=D("200.00"))
        f3 = self.satis(date(2026, 9, 7), [_satir(1, 300)])
        self.evo_yap(f3, tl_genel_toplam=D("500.00"))
        self.eski_hatali_fis(f3, idler)
        self.gm_ac()

        with patch("database.muhasebe_service.kapali_donem_mi", return_value=True):
            o = dz.duzeltme_onizleme(srv.SATIS, f1.id)
            self.assertFalse(o["duzeltilebilir"])
            self.assertTrue(o["kilitli"])
            s = dz.duzelt([(srv.SATIS, f1.id)], "kilitli")
            self.assertEqual(len(s["yazilan"]), 0)
        o2 = dz.duzeltme_onizleme(srv.SATIS, f2.id)
        self.assertFalse(o2["duzeltilebilir"])
        self.assertIn("cari tutarı", o2["neden"])
        rows = {x["no"]: x for x in dz.hatali_fisler(*EYLUL)["satirlar"]}
        self.assertEqual(rows[f3.fatura_no]["durum"], "KDV belirlenemedi")
        self.assertFalse(rows[f3.fatura_no]["duzeltilebilir"])
        self.assertFalse(dz.duzeltme_onizleme(srv.SATIS, f3.id)["duzeltilebilir"])
        self.assertEqual(self.fis_sayisi("kdv_duz_satis_faturasi"), 0)

    def _hareket_sayilari(self):
        from database.models.cari import CariIslem
        from database.models.stok import StokHareketi

        with get_session() as s:
            return tuple(int(s.scalar(select(func.count(m.id))) or 0) for m in (CariIslem, StokHareketi))


class EkranIslemleri(_EkTaban):
    def test_ekran_yeni_sekmeler_ve_pencereler(self):
        import tkinter as tk

        import kdv_raporu_islem_ui as islem
        import kdv_raporu_ui

        a = self.alis(date(2026, 9, 2), [_satir(1, 100)])
        try:
            kok = tk.Tk()
        except tk.TclError:
            self.skipTest("Tk yok")
        kok.withdraw()
        kok.icerik = tk.Frame(kok)
        kok.icerik.pack()
        kok._icerigi_temizle = lambda: [w.destroy() for w in kok.icerik.winfo_children()]
        try:
            ekran = kdv_raporu_ui.kdv_raporu_goster(kok, otomatik=False)
            ekran.girdiler["yil"].set("2026")
            ekran.girdiler["ay"].set("Eylül")
            ekran.raporla(senkron=True)
            self.assertIn("siniflar", [t.anahtar for t in ekran.tablolar_tanim])
            r = next(x for x in ekran.sonuc["belgeler"] if x.get("id") == a.id and x["tur"] == srv.ALIS)
            p = islem.kdv_bilgisi_penceresi(kok, [r], ekran)
            p.alanlar["indirilebilirlik"].set("İndirilecek KDV")
            with patch.object(ekran, "raporla"), patch("kdv_raporu_islem_ui.messagebox"):
                p.kaydet()
            from database import kdv_belge_bilgi_service as kb

            self.assertEqual(kb.belge_bilgisi(srv.ALIS, a.id)["indirilebilirlik"], "INDIRILECEK")
            h = islem.hatali_fis_penceresi(kok, *EYLUL, ekran)
            self.assertEqual(h.satirlar, [])
            h.destroy()
        finally:
            kok.destroy()


if __name__ == "__main__":
    unittest.main()
