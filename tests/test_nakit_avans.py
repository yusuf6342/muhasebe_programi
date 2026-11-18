"""Nakit avans — faiz valörü, yansıma sırası, kaydet+1. taksit, muhasebe."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from sqlalchemy import select

from database.database import get_session
from database.models.finans import (
    BankaKarti,
    FinansHareketi,
    FinansHesabi,
    GiderFisi,
    KrediKartiOdeme,
    KrediKartiOdemeTaksit,
    KrediKartiTanimi,
)
from database.nakit_avans_service import (
    DURUM_IPTAL,
    DURUM_KARTA,
    DURUM_PLAN,
    HAREKET_GIRIS,
    HAREKET_KART,
    HAREKET_KUL_UCRET,
    KAPSAM_TEK,
    KAPSAM_TUM,
    NakitAvansService,
    hedef_hesaplari_kart_bankasi,
    plan_hesapla,
    plan_ozeti,
    schema_hazirla,
    taksit_bilesenlerini_orantila,
)
from tests.stok_test_ortami import StokOrtami

D = Decimal
GUN = date(2026, 11, 10)
DENEME = date(2026, 11, 17)


class NakitAvansTest(unittest.TestCase):
    def setUp(self):
        self._ayar = tempfile.TemporaryDirectory(prefix="na_ayar_")
        self._env = patch.dict(os.environ, {"LOCALAPPDATA": self._ayar.name})
        self._env.start()
        self.o = StokOrtami("nakit_avans")
        with get_session() as s:
            bk = BankaKarti(banka_adi="TEST BANKASI NA")
            s.add(bk)
            s.flush()
            self.bk = int(bk.id)
            kasa = FinansHesabi(hesap_adi="NA KASA", hesap_turu="KASA", alt_hesap_turu=None)
            mev = FinansHesabi(
                hesap_adi="NA MEVDUAT", hesap_turu="BANKA", alt_hesap_turu="MEVDUAT", banka_karti_id=bk.id
            )
            kk_h = FinansHesabi(
                hesap_adi="NA KK HESAP", hesap_turu="BANKA", alt_hesap_turu="KREDI_KARTI", banka_karti_id=bk.id
            )
            s.add_all([kasa, mev, kk_h])
            s.flush()
            self.h_kasa = int(kasa.id)
            self.h_mev = int(mev.id)
            self.h_kk = int(kk_h.id)
            kart = KrediKartiTanimi(
                banka_karti_id=bk.id,
                kart_adi="NA Test Kart",
                kart_limiti=D("50000"),
                hesap_kesim_gunu=5,
                son_odeme_gunu=15,
                bagli_hesap_id=kk_h.id,
                aktif=True,
            )
            s.add(kart)
            s.flush()
            self.kk_id = int(kart.id)
        schema_hazirla()

    def tearDown(self):
        self.o.kapat()
        self._env.stop()
        self._ayar.cleanup()

    def test_plan_anuite_anapara_toplami(self):
        plan = plan_hesapla(
            anapara=D("1000"),
            aylik_faiz_orani=D("2"),
            taksit_sayisi=3,
            kullandirim_tarihi=GUN,
        )
        self.assertEqual(len(plan), 3)
        self.assertEqual(sum((p["anapara"] for p in plan), D("0")), D("1000.00"))
        self.assertTrue(all(p["toplam"] == p["anapara"] + p["faiz"] + p["masraf"] + p["vergi"] for p in plan))

    def test_plan_1711_uc_taksit_yansima_ve_valor(self):
        """17.11.2026 → yansıma +i−1 ay, faiz valörü +i ay."""
        plan = plan_hesapla(
            anapara=D("3000"),
            aylik_faiz_orani=D("2"),
            taksit_sayisi=3,
            kullandirim_tarihi=DENEME,
        )
        beklenen = [
            (date(2026, 11, 17), date(2026, 12, 17)),
            (date(2026, 12, 17), date(2027, 1, 17)),
            (date(2027, 1, 17), date(2027, 2, 17)),
        ]
        self.assertEqual(len(plan), 3)
        for i, (yan, valor) in enumerate(beklenen):
            self.assertEqual(plan[i]["yansima_tarihi"], yan, f"taksit {i + 1} yansıma")
            self.assertEqual(plan[i]["faiz_valor_tarihi"], valor, f"taksit {i + 1} faiz valör")
        self.assertEqual(sum((p["anapara"] for p in plan), D("0")), D("3000.00"))
        self.assertGreater(plan[0]["faiz"], 0)

    def test_kaydet_tum_taksitler_kendi_tarihiyle(self):
        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=DENEME,
            anapara=D("3000"),
            hedef_hesap_id=self.h_mev,
            aylik_faiz_orani=D("2"),
            taksit_sayisi=3,
            istek_anahtari="na-1711-3",
        )
        self.assertEqual(len(a["taksitler"]), 3)
        t1, t2, t3 = a["taksitler"]
        self.assertEqual(t1["durum"], DURUM_KARTA)
        self.assertEqual(t2["durum"], DURUM_KARTA)
        self.assertEqual(t3["durum"], DURUM_KARTA)
        self.assertEqual(t1["yansima_tarihi"], DENEME)
        self.assertEqual(t2["yansima_tarihi"], date(2026, 12, 17))
        self.assertEqual(t3["yansima_tarihi"], date(2027, 1, 17))
        # Karta işlendi ama ödenmedi → kalan = anapara
        self.assertEqual(a["kalan_anapara"], D("3000.00"))
        self.assertEqual(a["odenen_anapara"], D("0.00"))
        self.assertEqual(a["karta_aktarilan_anapara"], D("3000.00"))

        with get_session() as s:
            giris = s.scalars(select(FinansHareketi).where(
                FinansHareketi.hareket_turu == HAREKET_GIRIS,
                FinansHareketi.belge_no == a["belge_no"],
            )).all()
            self.assertEqual(len(giris), 1)
            self.assertEqual(giris[0].tarih, DENEME)
            for t in (t1, t2, t3):
                kart_h = s.scalars(select(FinansHareketi).where(
                    FinansHareketi.hareket_turu == HAREKET_KART,
                    FinansHareketi.belge_no == t["kk_hareket_belge_no"],
                )).all()
                self.assertEqual(len(kart_h), 1, t["taksit_no"])
                self.assertEqual(kart_h[0].tarih, t["yansima_tarihi"])
                self.assertEqual(D(str(kart_h[0].tutar)), t["toplam"])
                od = s.get(KrediKartiOdeme, int(t["kk_odeme_id"]))
                self.assertEqual(od.kaynak_turu, "NAKIT_AVANS")
                kids = [kt.durum for kt in (od.taksitler or [])]
                self.assertIn("BEKLIYOR", kids)

        # Idempotent yeniden işle / tamamla
        t1b = NakitAvansService.taksit_karta_isle(t1["id"], islem_anahtari=t1["islem_anahtari"])
        self.assertEqual(t1b["kk_hareket_belge_no"], t1["kk_hareket_belge_no"])
        tekrar = NakitAvansService.eksik_taksit_hareketlerini_tamamla(
            kredi_karti_id=self.kk_id
        )
        self.assertEqual(tekrar, [])
        with get_session() as s:
            nats = s.scalars(select(FinansHareketi).where(
                FinansHareketi.hareket_turu == HAREKET_KART,
            )).all()
            self.assertEqual(len(nats), 3)
            giris2 = s.scalars(select(FinansHareketi).where(
                FinansHareketi.hareket_turu == HAREKET_GIRIS,
                FinansHareketi.belge_no == a["belge_no"],
            )).all()
            self.assertEqual(len(giris2), 1)

    def test_tek_cekim_giris_ve_duzenle(self):
        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=GUN,
            anapara=D("1000"),
            hedef_hesap_id=self.h_mev,
            aylik_faiz_orani=0,
            taksit_sayisi=1,
            aciklama="tek çekim deneme",
            istek_anahtari="na-tek-1",
        )
        self.assertEqual(a["net_giris"], D("1000.00"))
        self.assertEqual(a["taksitler"][0]["durum"], DURUM_KARTA)
        tid = a["taksitler"][0]["id"]
        # Düzenle: geri al + yeniden işle (1.000 + 100 faiz + 25 masraf = 1.125)
        t = NakitAvansService.taksit_duzenle(
            tid, anapara=D("1000"), faiz=D("100"), masraf=D("25"), vergi=0
        )
        self.assertEqual(t["durum"], DURUM_KARTA)
        self.assertEqual(t["toplam"], D("1125.00"))
        with get_session() as s:
            kart_h = s.scalars(select(FinansHareketi).where(
                FinansHareketi.hareket_turu == HAREKET_KART,
                FinansHareketi.belge_no == t["kk_hareket_belge_no"],
            )).all()
            self.assertEqual(len(kart_h), 1)
            self.assertEqual(D(str(kart_h[0].tutar)), D("1125.00"))
            faiz_g = s.scalars(select(GiderFisi).where(GiderFisi.belge_no == t["faiz_gider_belge_no"])).all()
            self.assertEqual(len(faiz_g), 1)
            self.assertEqual(D(str(faiz_g[0].tutar)), D("100.00"))
            masraf_g = s.scalars(select(GiderFisi).where(GiderFisi.belge_no == t["masraf_gider_belge_no"])).all()
            self.assertEqual(D(str(masraf_g[0].tutar)), D("25.00"))

    def test_hedef_sadece_mevduat_kmh_ayni_banka(self):
        hedef = hedef_hesaplari_kart_bankasi(self.kk_id)
        self.assertTrue(any(h["id"] == self.h_mev for h in hedef))
        self.assertFalse(any(h["id"] == self.h_kasa for h in hedef))
        self.assertFalse(any(h["id"] == self.h_kk for h in hedef))
        with self.assertRaises(ValueError):
            NakitAvansService.kaydet(
                kredi_karti_id=self.kk_id,
                islem_tarihi=GUN,
                anapara=D("500"),
                hedef_hesap_id=self.h_kasa,
                taksit_sayisi=1,
                istek_anahtari="na-hedef-kasa",
            )

    def test_net_giris_ve_kullandirim_ucreti_ekstre(self):
        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=GUN,
            anapara=D("1000"),
            hedef_hesap_id=self.h_mev,
            taksit_sayisi=1,
            net_giris=D("1000"),
            kullandirim_masraf=D("50"),
            istek_anahtari="na-net-kul",
        )
        self.assertEqual(a["net_giris"], D("1000.00"))
        with get_session() as s:
            giris = s.scalars(select(FinansHareketi).where(
                FinansHareketi.hareket_turu == HAREKET_GIRIS,
                FinansHareketi.belge_no == a["belge_no"],
            )).all()
            self.assertEqual(len(giris), 1)
            self.assertEqual(D(str(giris[0].tutar)), D("1000.00"))
            kul = s.scalars(select(FinansHareketi).where(
                FinansHareketi.hareket_turu == HAREKET_KUL_UCRET,
            )).all()
            self.assertEqual(len(kul), 1)
            self.assertEqual(D(str(kul[0].tutar)), D("50.00"))

    def test_geri_odenecek_toplam_plan_ozeti(self):
        plan = plan_hesapla(
            anapara=D("100000"),
            aylik_faiz_orani=D("3.49"),
            taksit_sayisi=12,
            kullandirim_tarihi=GUN,
        )
        oz = plan_ozeti(plan, D("100000"))
        self.assertEqual(oz["geri_odenecek_toplam"], oz["toplam_taksit"])
        self.assertEqual(
            oz["geri_odenecek_toplam"],
            sum((p["toplam"] for p in plan), D("0")),
        )

    def test_taksitli_duzenle_sil(self):
        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=GUN,
            anapara=D("3000"),
            hedef_hesap_id=self.h_mev,
            aylik_faiz_orani=D("1.5"),
            taksit_sayisi=3,
            istek_anahtari="na-tak-1",
        )
        self.assertEqual(len(a["taksitler"]), 3)
        self.assertEqual(a["taksitler"][0]["durum"], DURUM_KARTA)
        self.assertEqual(a["kalan_anapara"], D("3000.00"))
        t1 = a["taksitler"][0]["id"]
        NakitAvansService.taksit_duzenle(t1, faiz=D("50"))
        t_yeni = NakitAvansService.getir(a["id"])["taksitler"][0]
        self.assertEqual(t_yeni["durum"], DURUM_KARTA)
        self.assertEqual(t_yeni["faiz"], D("50.00"))
        t2 = a["taksitler"][1]["id"]
        sil = NakitAvansService.taksit_sil(t2)
        self.assertEqual(sil["durum"], DURUM_IPTAL)

    def test_kaydet_sonrasi_ikinci_taksit_zaten_kartta(self):
        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=DENEME,
            anapara=D("1500"),
            hedef_hesap_id=self.h_mev,
            aylik_faiz_orani=0,
            taksit_sayisi=2,
            istek_anahtari="na-auto-2",
        )
        t1 = a["taksitler"][0]
        t2 = a["taksitler"][1]
        self.assertEqual(t1["durum"], DURUM_KARTA)
        self.assertEqual(t2["durum"], DURUM_KARTA)
        self.assertEqual(a["kalan_anapara"], D("1500.00"))
        with get_session() as s:
            od = s.scalar(
                select(KrediKartiOdeme).where(KrediKartiOdeme.nakit_avans_taksit_id == t1["id"])
            )
            self.assertIsNotNone(od)
            self.assertEqual(od.kaynak_turu, "NAKIT_AVANS")
            fh2 = s.scalars(select(FinansHareketi).where(
                FinansHareketi.belge_no == t2["kk_hareket_belge_no"],
                FinansHareketi.hareket_turu == HAREKET_KART,
            )).first()
            self.assertEqual(fh2.tarih, t2["yansima_tarihi"])
        # Onarım API mükerrer üretmez
        sonuc = NakitAvansService.vadesi_gelenleri_isle(kredi_karti_id=self.kk_id)
        self.assertEqual(sonuc, [])

    def test_muhasebe_hook_tanimli(self):
        from database import muhasebe_entegrasyon as me

        self.assertIn("nakit_avans_kullandirim", me.EVRAKLAR)
        self.assertIn("nakit_avans_taksit", me.EVRAKLAR)
        self.assertIn("nakit_avans_kullandirim", me.PLANLAR)
        self.assertTrue(hasattr(me.MuhasebeEntegrasyonService, "nakit_avans_kullandirim_fisi"))
        self.assertTrue(hasattr(me.MuhasebeEntegrasyonService, "nakit_avans_taksit_fisi"))

    def test_planlanan_bekleyen_ve_takvim(self):
        """Karta işlenmiş NA taksitleri bekleyen listede KK/NAKIT_AVANS olarak görünür."""
        from database.finans_service import FinansService

        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=DENEME,
            anapara=D("1600"),
            hedef_hesap_id=self.h_mev,
            aylik_faiz_orani=0,
            taksit_sayisi=2,
            istek_anahtari="na-bek-2",
        )
        t2 = a["taksitler"][1]
        self.assertEqual(t2["durum"], DURUM_KARTA)
        # PLANLANDI kaynağı boş (hepsi karta işlendi)
        self.assertEqual(
            NakitAvansService.planlanan_bekleyenler(kredi_karti_id=self.kk_id),
            [],
        )
        bek = FinansService.kredi_karti_bekleyen_taksitler(self.bk, kredi_karti_id=self.kk_id)
        # KK ödeme taksitleri üzerinden (kaynak NAKIT_AVANS)
        self.assertTrue(
            any(
                r.get("kaynak") == "NAKIT_AVANS"
                and D(str(r.get("tutar") or 0)) == t2["toplam"]
                for r in bek
            ),
            bek,
        )

    def test_aylara_gore_odeme_planlandi_bir_kez(self):
        """Karta işlenince PLANLANDI ödeme-durumu kaynağından çıkar; mükerrer yok."""
        from database.odeme_durumu_service import KAYNAK_NAKIT_AVANS, OdemeDurumuService

        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=DENEME,
            anapara=D("2400"),
            hedef_hesap_id=self.h_mev,
            aylik_faiz_orani=0,
            taksit_sayisi=3,
            istek_anahtari="na-aylar-3",
        )
        t1, t2, t3 = a["taksitler"]
        self.assertEqual(t1["durum"], DURUM_KARTA)
        self.assertEqual(t2["durum"], DURUM_KARTA)
        self.assertEqual(t3["durum"], DURUM_KARTA)
        satirlar = OdemeDurumuService._nakit_avans_satirlari(bugun=DENEME)
        ids = [s["source_id"] for s in satirlar if s["source_type"] == KAYNAK_NAKIT_AVANS]
        self.assertNotIn(t1["id"], ids)
        self.assertNotIn(t2["id"], ids)
        self.assertNotIn(t3["id"], ids)
        # Tarihler korundu
        self.assertEqual(t2["yansima_tarihi"], date(2026, 12, 17))
        self.assertEqual(t3["yansima_tarihi"], date(2027, 1, 17))


    def test_bilesen_orantila_kurus_tam_esit(self):
        """10454,61 gibi kuruşlu tutarda bileşen toplamı tam oturur (sabit kod yok)."""
        yeni = D("10454.61")
        b = taksit_bilesenlerini_orantila(
            anapara=D("6852.31"),
            faiz=D("3490.00"),
            masraf=0,
            vergi=0,
            yeni_toplam=yeni,
        )
        self.assertEqual(b["toplam"], yeni)
        self.assertEqual(b["anapara"] + b["faiz"] + b["masraf"] + b["vergi"], yeni)
        self.assertEqual(b["masraf"], D("0.00"))
        self.assertEqual(b["vergi"], D("0.00"))
        # Oran korunumu (yaklaşık)
        self.assertAlmostEqual(
            float(b["anapara"] / yeni),
            float(D("6852.31") / D("10342.31")),
            places=4,
        )

    def test_bilesen_orantila_sifir_toplam_hata(self):
        with self.assertRaises(ValueError):
            taksit_bilesenlerini_orantila(
                anapara=0, faiz=0, masraf=0, vergi=0, yeni_toplam=D("100")
            )

    def test_taksit_tutari_tek_digerleri_degismez(self):
        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=GUN,
            anapara=D("3000"),
            hedef_hesap_id=self.h_mev,
            aylik_faiz_orani=D("2"),
            taksit_sayisi=3,
            istek_anahtari="na-tek-tut",
        )
        t1, t2, t3 = a["taksitler"]
        eski2, eski3 = t2["toplam"], t3["toplam"]
        yeni = D("1200.00")
        oniz = NakitAvansService.taksit_tutari_onizle(
            avans_id=a["id"], taksit_id=t2["id"], yeni_tutar=yeni, kapsam=KAPSAM_TEK
        )
        self.assertEqual(len(oniz["degisecek"]), 1)
        self.assertEqual(oniz["degisecek"][0]["taksit_no"], 2)
        a2 = NakitAvansService.taksit_tutari_uygula(
            avans_id=a["id"], taksit_id=t2["id"], yeni_tutar=yeni, kapsam=KAPSAM_TEK
        )
        by_no = {t["taksit_no"]: t for t in a2["taksitler"]}
        self.assertEqual(by_no[2]["toplam"], yeni)
        self.assertEqual(by_no[1]["toplam"], t1["toplam"])
        self.assertEqual(by_no[3]["toplam"], eski3)
        self.assertEqual(by_no[2]["anapara"] + by_no[2]["faiz"], yeni)
        # NAV giriş mükerrer değil
        with get_session() as s:
            giris = s.scalars(select(FinansHareketi).where(
                FinansHareketi.hareket_turu == HAREKET_GIRIS,
                FinansHareketi.belge_no == a["belge_no"],
            )).all()
            self.assertEqual(len(giris), 1)

    def test_taksit_tutari_tum_esit_ve_oran_korunur(self):
        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=GUN,
            anapara=D("3000"),
            hedef_hesap_id=self.h_mev,
            aylik_faiz_orani=D("2"),
            taksit_sayisi=3,
            istek_anahtari="na-tum-tut",
        )
        t1 = a["taksitler"][0]
        nat_eski = t1["kk_hareket_belge_no"]
        yeni = D("10454.61")
        # Farklı oranlar: T2'ye ekstra masraf (kendi oranı)
        NakitAvansService.taksit_duzenle(
            a["taksitler"][1]["id"],
            anapara=a["taksitler"][1]["anapara"],
            faiz=a["taksitler"][1]["faiz"],
            masraf=D("30.00"),
            vergi=0,
        )
        a = NakitAvansService.getir(a["id"])
        t2_eski = next(t for t in a["taksitler"] if t["taksit_no"] == 2)
        oran_ana_t2 = t2_eski["anapara"] / t2_eski["toplam"]
        a2 = NakitAvansService.taksit_tutari_uygula(
            avans_id=a["id"],
            taksit_id=a["taksitler"][0]["id"],
            yeni_tutar=yeni,
            kapsam=KAPSAM_TUM,
        )
        for t in a2["taksitler"]:
            if t["durum"] == DURUM_IPTAL:
                continue
            self.assertEqual(t["toplam"], yeni, f"T{t['taksit_no']}")
            self.assertEqual(
                t["anapara"] + t["faiz"] + t["masraf"] + t["vergi"], yeni
            )
        t2_yeni = next(t for t in a2["taksitler"] if t["taksit_no"] == 2)
        self.assertGreater(t2_yeni["masraf"], 0)
        self.assertAlmostEqual(float(t2_yeni["anapara"] / yeni), float(oran_ana_t2), places=4)
        t1n = next(t for t in a2["taksitler"] if t["taksit_no"] == 1)
        self.assertEqual(t1n["durum"], DURUM_KARTA)
        self.assertEqual(t1n["kk_hareket_belge_no"], nat_eski)  # yerinde; yeni NAT yok
        with get_session() as s:
            fh = s.scalars(select(FinansHareketi).where(
                FinansHareketi.belge_no == nat_eski,
                FinansHareketi.hareket_turu == HAREKET_KART,
            )).all()
            self.assertEqual(len(fh), 1)
            self.assertEqual(D(str(fh[0].tutar)), yeni)
            giris = s.scalars(select(FinansHareketi).where(
                FinansHareketi.hareket_turu == HAREKET_GIRIS,
                FinansHareketi.belge_no == a["belge_no"],
            )).all()
            self.assertEqual(len(giris), 1)


    def test_odeme_oncesi_sonrasi_anapara_faiz_ayrimi(self):
        """Kayıt: anapara gider değil; ödeme: kalan yalnız anapara kadar düşer, GDF mükerrer yok."""
        a = NakitAvansService.kaydet(
            kredi_karti_id=self.kk_id,
            islem_tarihi=DENEME,
            anapara=D("3000"),
            hedef_hesap_id=self.h_mev,
            aylik_faiz_orani=D("2"),
            taksit_sayisi=2,
            istek_anahtari="na-ode-ayrim",
        )
        t1, t2 = a["taksitler"]
        self.assertEqual(a["kalan_anapara"], D("3000.00"))
        self.assertEqual(a["odenen_anapara"], D("0.00"))
        self.assertGreater(t1["faiz"], 0)

        with get_session() as s:
            gdf = list(s.scalars(select(GiderFisi)).all())
            turler = {(g.gider_turu or "").upper() for g in gdf}
            self.assertTrue(any("FAIZ" in t for t in turler), turler)
            self.assertFalse(any("ANAPARA" in t for t in turler), turler)
            # Gider tarihleri yansıma (bugüne toplanmaz)
            for g in gdf:
                if "FAIZ" in (g.gider_turu or "").upper():
                    self.assertIn(g.tarih, (t1["yansima_tarihi"], t2["yansima_tarihi"]))
            n_gdf = len(gdf)
            n_nat = len(
                list(
                    s.scalars(
                        select(FinansHareketi).where(
                            FinansHareketi.hareket_turu == HAREKET_KART
                        )
                    ).all()
                )
            )
            n_giris = len(
                list(
                    s.scalars(
                        select(FinansHareketi).where(
                            FinansHareketi.hareket_turu == HAREKET_GIRIS
                        )
                    ).all()
                )
            )
            self.assertEqual(n_nat, 2)
            self.assertEqual(n_giris, 1)

            # Gerçek ödeme: 1. taksit KK ODENDI
            od = s.get(KrediKartiOdeme, int(t1["kk_odeme_id"]))
            self.assertIsNotNone(od)
            for kt in od.taksitler or []:
                kt.durum = "ODENDI"
            s.flush()
            NakitAvansService.ekstre_odeme_sonrasi_guncelle(
                s, kredi_karti_id=self.kk_id
            )

        a2 = NakitAvansService.getir(a["id"])
        self.assertEqual(a2["odenen_anapara"], t1["anapara"])
        self.assertEqual(a2["kalan_anapara"], D("3000.00") - t1["anapara"])
        # Faiz tutarı kalandan düşülmedi
        self.assertNotEqual(a2["kalan_anapara"], D("3000.00") - t1["toplam"])

        with get_session() as s:
            gdf2 = list(s.scalars(select(GiderFisi)).all())
            self.assertEqual(len(gdf2), n_gdf)  # ikinci faiz/masraf yok
            nat2 = list(
                s.scalars(
                    select(FinansHareketi).where(
                        FinansHareketi.hareket_turu == HAREKET_KART
                    )
                ).all()
            )
            giris2 = list(
                s.scalars(
                    select(FinansHareketi).where(
                        FinansHareketi.hareket_turu == HAREKET_GIRIS
                    )
                ).all()
            )
            self.assertEqual(len(nat2), 2)
            self.assertEqual(len(giris2), 1)
            # Tekrar çağrı idempotent
            NakitAvansService.ekstre_odeme_sonrasi_guncelle(
                s, kredi_karti_id=self.kk_id
            )
        a3 = NakitAvansService.getir(a["id"])
        self.assertEqual(a3["kalan_anapara"], a2["kalan_anapara"])


def _q2_kalan(a: dict) -> Decimal:
    """Ödenmemişken kalan = anapara (karta aktarım düşürmez)."""
    return D(str(a["anapara"])) - D(str(a.get("odenen_anapara") or 0))


if __name__ == "__main__":
    unittest.main()
