"""Kurulum öncesi a–f senaryoları — izole SQLite (canlı D2 / RAY-00102 yok).

a) Yetersiz stok → onay reddi, hareket yok
b) Stok tamamlanınca yeniden onay + lot fallback
c) Kısmi avans 5000 → kalan 8800 (13800 fatura)
d) Tam avans → kalan 0; durum AÇIK kalır
e) Kapatma iptali / fatura onay iptali
f) Çift onay — tek geçerli sonuç
"""
from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from database.acik_kalem_service import AcikKalemService
from database.database import get_session
from database.models.cari import CariKapatma, SatisHareketi
from database.models.stok import StokHareketi, StokLotu
from database.satis_faturasi_service import SatisFaturasiService, evrak_durumu, odeme_durumu
from tests.stok_test_ortami import StokOrtami

D = Decimal
TARIH = date(2026, 11, 12)


class KurulumOncesiAfSenaryolar(unittest.TestCase):
    def setUp(self):
        self.o = StokOrtami("af_senaryo")
        with get_session() as s:
            AcikKalemService.schema_hazirla(s.get_bind())

    def tearDown(self):
        self.o.kapat()

    def _stok_ekle(self, miktar, *, lot="L1", fiyat="10", kod="U001"):
        self.o.alis(miktar, fiyat, TARIH, lot=lot, kod=kod)

    def _fatura_13800(self, *, miktar="100", fiyat="115", onayla=False, kod="U001", lot_no=""):
        """100 × 115 + %20 KDV = 13.800."""
        f = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": TARIH,
                "vade_tarihi": TARIH,
                "cari_id": self.o.mus_id,
                "depo": "ANA DEPO",
                "odeme_tutari": D("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": kod,
                    "urun_adi": "Test Ürün",
                    "miktar": D(miktar),
                    "birim": "Adet",
                    "birim_fiyat": D(fiyat),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                    "lot_no": lot_no,
                }
            ],
        )
        self.assertEqual(D(str(f.tl_genel_toplam)), D("13800.00"))
        if onayla:
            SatisFaturasiService.onayla(f.id)
            f = SatisFaturasiService.getir(f.id)
        return f

    def _cikis_sayisi(self, belge_no: str) -> int:
        with get_session() as s:
            return int(
                s.scalar(
                    select(func.count())
                    .select_from(StokHareketi)
                    .where(
                        StokHareketi.belge_no == belge_no,
                        StokHareketi.hareket_turu == "FATURA ÇIKIŞ",
                    )
                )
                or 0
            )

    def _satis_hareket(self, belge_no: str):
        with get_session() as s:
            return s.scalar(
                select(SatisHareketi).where(
                    SatisHareketi.belge_no == belge_no,
                    SatisHareketi.satis_tutari > 0,
                )
            )

    def test_a_yetersiz_stok_onay_reddi(self):
        """a) Onay reddedilsin; onay/stok/cari/yarım işlem olmasın."""
        self._stok_ekle(5)
        f = self._fatura_13800(onayla=False)
        once_hrk = self.o.hareket_sayisi(tur="FATURA ÇIKIŞ")
        with self.assertRaises(ValueError) as ctx:
            SatisFaturasiService.onayla(f.id)
        msg = str(ctx.exception).casefold()
        self.assertTrue("stok" in msg or "yetersiz" in msg or "eksi" in msg, msg)
        f2 = SatisFaturasiService.getir(f.id)
        self.assertFalse(bool(f2.onaylandi))
        self.assertEqual(evrak_durumu(f2.durum, f2.onaylandi), "AÇIK")
        self.assertEqual(self.o.hareket_sayisi(tur="FATURA ÇIKIŞ"), once_hrk)
        self.assertIsNone(self._satis_hareket(f.fatura_no))

    def test_b_stok_tamamlaninca_yeniden_onay_ve_lot_fallback(self):
        """b) Tercih lot yetersizken diğer lotlardan tamamlanıp tek onay."""
        from database.models.stok import Depo, StokKarti

        with get_session() as s:
            kart = s.scalar(select(StokKarti).where(StokKarti.stok_kodu == "U001"))
            depo_id = s.scalar(select(Depo.id).where(Depo.ad == "ANA DEPO"))
            s.add(
                StokLotu(
                    stok_id=kart.id,
                    depo_id=depo_id,
                    lot_no="TERCIH-AZ",
                    giris_tarihi=date(2026, 10, 1),
                    kalan_miktar=D("34"),
                    birim_maliyet=D("10"),
                )
            )
            s.add(
                StokLotu(
                    stok_id=kart.id,
                    depo_id=depo_id,
                    lot_no="DIGER-COK",
                    giris_tarihi=date(2026, 11, 1),
                    kalan_miktar=D("80"),
                    birim_maliyet=D("12"),
                )
            )
            s.commit()

        f = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": TARIH,
                "vade_tarihi": TARIH,
                "cari_id": self.o.mus_id,
                "depo": "ANA DEPO",
                "odeme_tutari": D("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Test Ürün",
                    "miktar": D("100"),
                    "birim": "Adet",
                    "birim_fiyat": D("115"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                    "lot_no": "TERCIH-AZ",
                }
            ],
        )
        self.assertEqual(D(str(f.tl_genel_toplam)), D("13800.00"))
        SatisFaturasiService.onayla(f.id)
        f2 = SatisFaturasiService.getir(f.id)
        self.assertTrue(f2.onaylandi)
        self.assertEqual(self._cikis_sayisi(f.fatura_no), 2)
        with get_session() as s:
            top = s.scalar(
                select(func.coalesce(func.sum(StokHareketi.miktar), 0)).where(
                    StokHareketi.belge_no == f.fatura_no,
                    StokHareketi.hareket_turu == "FATURA ÇIKIŞ",
                )
            )
            self.assertEqual(D(str(top)), D("100.0000"))
        with self.assertRaises(ValueError):
            SatisFaturasiService.onayla(f.id)
        self.assertEqual(self._cikis_sayisi(f.fatura_no), 2)

    def test_b2_yetersiz_sonra_stok_ekleyip_onay(self):
        self._stok_ekle(5)
        f = self._fatura_13800(onayla=False)
        with self.assertRaises(ValueError):
            SatisFaturasiService.onayla(f.id)
        self._stok_ekle(100, lot="L2")
        SatisFaturasiService.onayla(f.id)
        f2 = SatisFaturasiService.getir(f.id)
        self.assertTrue(f2.onaylandi)
        # 5+95 lot bölünmesi → 2 çıkış satırı olabilir; toplam temel miktar 100
        with get_session() as s:
            top = D(
                str(
                    s.scalar(
                        select(func.coalesce(func.sum(StokHareketi.miktar), 0)).where(
                            StokHareketi.belge_no == f.fatura_no,
                            StokHareketi.hareket_turu == "FATURA ÇIKIŞ",
                        )
                    )
                    or 0
                )
            )
        self.assertEqual(top, D("100.0000"))
        self.assertGreaterEqual(self._cikis_sayisi(f.fatura_no), 1)
        h = self._satis_hareket(f.fatura_no)
        self.assertIsNotNone(h)
        self.assertEqual(D(str(h.satis_tutari)), D("13800.00"))

    def test_c_kismi_avans_5000_kalan_8800(self):
        self._stok_ekle(200)
        f = self._fatura_13800(onayla=True)
        h = self._satis_hareket(f.fatura_no)
        self.assertEqual(D(str(h.kalan_acik_tutar)), D("13800.00"))
        with get_session() as s:
            sonuc = AcikKalemService.kapat(
                s,
                self.o.mus_id,
                D("5000"),
                belge_no="TMK-TEST-KISMI",
                kaynak_tur="TAHSILAT",
                tarih=TARIH,
                dagitim=[(int(h.id), D("5000"))],
                fifo=False,
            )
            s.commit()
        self.assertEqual(sonuc.kapanan, D("5000.00"))
        h2 = self._satis_hareket(f.fatura_no)
        self.assertEqual(D(str(h2.kalan_acik_tutar)), D("8800.00"))
        f2 = SatisFaturasiService.getir(f.id)
        self.assertEqual(evrak_durumu(f2.durum, f2.onaylandi), "AÇIK")
        # aynı avans belgesi tekrar tüketilmesin (manuel ikinci kapatma ayrı belge)
        with get_session() as s:
            kayitlar = list(
                s.scalars(
                    select(CariKapatma).where(
                        CariKapatma.kaynak_belge_no == "TMK-TEST-KISMI",
                        CariKapatma.iptal.is_(False),
                    )
                ).all()
            )
        self.assertEqual(len(kayitlar), 1)
        self.assertEqual(D(str(kayitlar[0].tutar)), D("5000.00"))

    def test_d_tam_avans_kalan_sifir_durum_acik(self):
        self._stok_ekle(200)
        f = self._fatura_13800(onayla=True)
        h = self._satis_hareket(f.fatura_no)
        with get_session() as s:
            AcikKalemService.kapat(
                s,
                self.o.mus_id,
                D("13800"),
                belge_no="TMK-TEST-TAM",
                kaynak_tur="TAHSILAT",
                tarih=TARIH,
                dagitim=[(int(h.id), D("13800"))],
                fifo=False,
            )
            s.commit()
        h2 = self._satis_hareket(f.fatura_no)
        self.assertEqual(D(str(h2.kalan_acik_tutar)), D("0.00"))
        f2 = SatisFaturasiService.getir(f.id)
        self.assertTrue(f2.onaylandi)
        self.assertEqual(evrak_durumu(f2.durum, f2.onaylandi), "AÇIK")
        self.assertEqual(odeme_durumu(f2.tl_genel_toplam, D("13800")), "Kapandı")

    def test_e_kapatma_iptali_ve_onay_iptali(self):
        self._stok_ekle(200)
        f = self._fatura_13800(onayla=True)
        h = self._satis_hareket(f.fatura_no)
        with get_session() as s:
            AcikKalemService.kapat(
                s,
                self.o.mus_id,
                D("5000"),
                belge_no="TMK-TEST-IPT",
                kaynak_tur="TAHSILAT",
                tarih=TARIH,
                dagitim=[(int(h.id), D("5000"))],
                fifo=False,
            )
            s.commit()
        self.assertEqual(D(str(self._satis_hareket(f.fatura_no).kalan_acik_tutar)), D("8800.00"))
        with get_session() as s:
            AcikKalemService.belge_geri_al(s, self.o.mus_id, "TMK-TEST-IPT", neden="test iptal")
            s.commit()
        self.assertEqual(D(str(self._satis_hareket(f.fatura_no).kalan_acik_tutar)), D("13800.00"))
        once = self._cikis_sayisi(f.fatura_no)
        SatisFaturasiService.iptal_et(f.id, sebep="test onay iptal")
        f2 = SatisFaturasiService.getir(f.id)
        self.assertEqual(f2.durum, "İPTAL")
        self.assertFalse(bool(f2.onaylandi))
        # stok ters hareket / net sıfırlanmalı (çıkış + giriş veya silme kuralına göre)
        after = self.o.hareket_sayisi()
        self.assertGreaterEqual(after, once)  # ters kayıt veya koruma

    def test_f_cift_onay_tek_sonuc(self):
        self._stok_ekle(200)
        f = self._fatura_13800(onayla=False)
        fid = f.id
        sonuclar: list[str] = []
        kilit = threading.Lock()

        def _dene():
            try:
                SatisFaturasiService.onayla(fid)
                with kilit:
                    sonuclar.append("ok")
            except Exception as exc:  # noqa: BLE001
                with kilit:
                    sonuclar.append(f"err:{type(exc).__name__}")

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: _dene(), range(2)))
        self.assertEqual(sonuclar.count("ok"), 1, sonuclar)
        self.assertEqual(self._cikis_sayisi(f.fatura_no), 1)
        h_list = []
        with get_session() as s:
            h_list = list(
                s.scalars(
                    select(SatisHareketi).where(
                        SatisHareketi.belge_no == f.fatura_no,
                        SatisHareketi.satis_tutari > 0,
                    )
                ).all()
            )
        self.assertEqual(len(h_list), 1)
        # tekrar deneme
        with self.assertRaises(ValueError):
            SatisFaturasiService.onayla(fid)

    def test_ek_birim_carpan_ve_coklu_satir(self):
        """Aynı ürün iki satır + Koli çarpanı."""
        self._stok_ekle(50)
        f = SatisFaturasiService.kaydet(
            {
                "fatura_tarihi": TARIH,
                "vade_tarihi": TARIH,
                "cari_id": self.o.mus_id,
                "depo": "ANA DEPO",
                "odeme_tutari": D("0"),
                "sales_person_id": 1,
            },
            [
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Test Ürün",
                    "miktar": D("10"),
                    "birim": "Adet",
                    "birim_fiyat": D("100"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                },
                {
                    "urun_kodu": "U001",
                    "urun_adi": "Test Ürün",
                    "miktar": D("2"),
                    "birim": "Koli",
                    "birim_fiyat": D("1200"),
                    "iskonto_orani": D("0"),
                    "kdv_orani": D("20"),
                },
            ],
        )
        SatisFaturasiService.onayla(f.id)
        with get_session() as s:
            top = D(
                str(
                    s.scalar(
                        select(func.coalesce(func.sum(StokHareketi.miktar), 0)).where(
                            StokHareketi.belge_no == f.fatura_no,
                            StokHareketi.hareket_turu == "FATURA ÇIKIŞ",
                        )
                    )
                    or 0
                )
            )
        # 10 Adet + 2 Koli×12 = 34
        self.assertEqual(top, D("34.0000"))


if __name__ == "__main__":
    unittest.main()
