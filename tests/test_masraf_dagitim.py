"""Masraf dağıtımı: gider belgesi → alış katmanı maliyeti (stok / SMM), GM fişi, geri alma.

Kabul örneği: 100 adet, 10.000 TL alış + 1.000 TL nakliye → birim maliyet 110.
40 adet satılmışsa 400 TL SMM'ye, 600 TL stoka gider.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from database.database import Base, _aktif_engine_bagla, company_db, get_session
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.firma import Firma
from database.models.stok import Depo, StokKarti, StokLotu
from database.session_manager import oturum

TARIH_ALIS = date(2026, 6, 1)
TARIH_SATIS = date(2026, 6, 5)
TARIH_GIDER = date(2026, 6, 2)
TARIH_DAGITIM = date(2026, 6, 10)


def _sqlite_pragma(dbapi_connection, _connection_record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class MasrafDagitimTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_masraf_dagitim.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _sqlite_pragma)

        import database.models.cari  # noqa: F401
        import database.models.stok  # noqa: F401
        import database.models.firma  # noqa: F401
        import database.models.donem  # noqa: F401
        import database.models.alis_faturasi  # noqa: F401
        import database.models.alis_iade_faturasi  # noqa: F401
        import database.models.alis_irsaliyesi  # noqa: F401
        import database.models.alis_siparisi  # noqa: F401
        import database.models.alis_masraf  # noqa: F401
        import database.models.finans  # noqa: F401
        import database.models.satis_faturasi  # noqa: F401
        import database.models.satis_iade_faturasi  # noqa: F401
        import database.models.satis_irsaliyesi  # noqa: F401
        import database.models.satis_siparisi  # noqa: F401
        import database.models.hizli_satis  # noqa: F401
        import database.models.hizmet  # noqa: F401
        import database.models.hizmet_faturasi  # noqa: F401
        import database.models.genel_muhasebe  # noqa: F401
        import database.models.masraf_dagitim  # noqa: F401

        Base.metadata.create_all(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)

        from database.models.hizmet import HizmetKarti

        with Session() as s:
            firma = Firma(firma_kodu="MDT", unvan="Masraf Dagitim Test", aktif=True)
            s.add(firma)
            s.flush()
            self.firma_id = firma.id
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="2026",
                    baslangic_tarihi=date(2026, 1, 1),
                    bitis_tarihi=date(2026, 12, 31),
                    aktif=True,
                    kapali=False,
                    varsayilan=True,
                )
            )
            s.add(Depo(ad="ANA DEPO", aktif=True))
            s.add(Depo(ad="YEDEK DEPO", aktif=True))
            s.add(StokKarti(stok_kodu="U001", stok_adi="Test Ürün", birim="Adet", aktif=True, is_deleted=False,
                            agirlik="2 kg"))
            s.add(StokKarti(stok_kodu="U002", stok_adi="Koli Ürün", birim="Koli", aktif=True, is_deleted=False))
            s.add(Cari(cari_kodu="T001", unvan="Test Tedarikçi", cari_turu="Tedarikçi", aktif=True))
            s.add(Cari(cari_kodu="M001", unvan="Test Müşteri", cari_turu="Müşteri", aktif=True))
            s.add(Cari(cari_kodu="N001", unvan="Nakliyeci", cari_turu="Tedarikçi", aktif=True))
            s.add(HizmetKarti(hizmet_kodu="NAKLIYE", hizmet_adi="Nakliye Gideri", hizmet_turu="GIDER",
                              birim="Adet", aktif=True))
            s.add(HizmetKarti(hizmet_kodu="KIRA", hizmet_adi="Depo Kirası", hizmet_turu="GIDER",
                              birim="Adet", aktif=True))
            s.commit()

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 98
        company_db._db_path = self.db_path

        oturum.clear()
        oturum.set_user(user_id=1, kullanici_adi="admin", ad_soyad="Test Admin", role_kod="YONETICI",
                        role_ad="Yönetici", permissions=set())
        oturum.set_company(company_id=98, firma_kodu="MDT", firma_unvan="Masraf Dagitim Test",
                           firma_uid="mdt-test", db_path=str(self.db_path))
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            oturum.set_period(d.id, d.donem_adi)
            self.tedarikci_id = s.scalar(select(Cari.id).where(Cari.cari_kodu == "T001"))
            self.musteri_id = s.scalar(select(Cari.id).where(Cari.cari_kodu == "M001"))
            self.nakliyeci_id = s.scalar(select(Cari.id).where(Cari.cari_kodu == "N001"))

        self._muhasebe_patch = patch("database.muhasebe_entegrasyon.muhasebe_hook", lambda *_a, **_k: None)
        self._muhasebe_patch.start()
        self._sp_patch = patch("database.satis_personeli.secimi_dogrula", return_value=(1, "Test Admin"))
        self._sp_patch.start()
        from database.masraf_dagitim_service import MasrafDagitimService

        MasrafDagitimService._hazir_motor = None

    def tearDown(self):
        self._sp_patch.stop()
        self._muhasebe_patch.stop()
        try:
            company_db.close()
        except Exception:
            pass
        if company_db._engine is not None:
            try:
                company_db._engine.dispose()
            except Exception:
                pass
        company_db._engine = None
        company_db._session_factory = None
        oturum.clear()
        self._tmpdir.cleanup()

    # ------------------------------------------------------------ yardımcı
    def _alis(self, kod="U001", miktar="100", fiyat="100", lot="LOT-A", birim="Adet"):
        from database.alis_faturasi_service import AlisFaturasiService

        f = AlisFaturasiService.kaydet(
            {"fatura_tarihi": TARIH_ALIS, "vade_tarihi": TARIH_ALIS, "cari_id": self.tedarikci_id,
             "depo": "ANA DEPO", "odeme_tutari": Decimal("0")},
            [{"urun_kodu": kod, "urun_adi": kod, "miktar": Decimal(miktar), "birim": birim,
              "birim_fiyat": Decimal(fiyat), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20"),
              "lot_no": lot}],
        )
        with get_session() as s:
            from database.models.alis_faturasi import AlisFaturasiSatiri

            satir_id = s.scalar(select(AlisFaturasiSatiri.id).where(AlisFaturasiSatiri.fatura_id == f.id))
        return int(f.id), int(satir_id)

    def _gider(self, tutar="1000", kod="NAKLIYE", ek_kira=None):
        from database.hizmet_faturasi_service import HizmetFaturasiService

        satirlar = [{"hizmet_kodu": kod, "miktar": Decimal("1"), "birim_fiyat": Decimal(tutar),
                     "kdv_orani": Decimal("20")}]
        if ek_kira:
            satirlar.append({"hizmet_kodu": "KIRA", "miktar": Decimal("1"), "birim_fiyat": Decimal(ek_kira),
                             "kdv_orani": Decimal("20")})
        f = HizmetFaturasiService.kaydet(
            {"fatura_tarihi": TARIH_GIDER, "vade_tarihi": TARIH_GIDER, "cari_id": self.nakliyeci_id,
             "fatura_turu": "GIDER", "odeme_tutari": Decimal("0")},
            satirlar,
        )
        from database.masraf_dagitim_service import MasrafDagitimService

        detay = MasrafDagitimService.kaynak_detay(f.id)
        return int(f.id), [s["id"] for s in detay["satirlar"]]

    def _sat(self, miktar="40", kod="U001"):
        from database.satis_faturasi_service import SatisFaturasiService

        f = SatisFaturasiService.kaydet(
            {"fatura_tarihi": TARIH_SATIS, "vade_tarihi": TARIH_SATIS, "cari_id": self.musteri_id,
             "depo": "ANA DEPO", "odeme_tutari": Decimal("0"), "sales_person_id": 1},
            [{"urun_kodu": kod, "urun_adi": kod, "miktar": Decimal(miktar), "birim": "Adet",
              "birim_fiyat": Decimal("200"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20")}],
        )
        SatisFaturasiService.onayla(f.id)
        return int(f.id)

    def _gm_kur(self, eksik: tuple[str, ...] = ()):
        from database.models.genel_muhasebe import HesapPlani, MuhasebeHesapEsleme

        hesaplar = {
            "ticari_mallar": ("153.01.0001", "Ticari Mallar", "Aktif"),
            "satilan_mal_maliyeti": ("621.01.0001", "SMM", "Gider"),
            "giderler": ("770.01.0001", "Genel Yönetim Giderleri", "Gider"),
        }
        with get_session() as s:
            for anahtar, (kod, ad, tur) in hesaplar.items():
                h = HesapPlani(firma_id=self.firma_id, hesap_kodu=kod, hesap_adi=ad, hesap_seviyesi=3,
                               hesap_turu=tur, borc_toplam=0, alacak_toplam=0, aktif=True)
                s.add(h)
                s.flush()
                if anahtar not in eksik:
                    s.add(MuhasebeHesapEsleme(firma_id=self.firma_id, anahtar=anahtar, aciklama=ad,
                                              hesap_id=h.id, aktif=True))

    def _veri(self, kaynak_id, kaynak_satirlar, hedefler, tutar="1000", yontem="TUTAR"):
        return {
            "dagitim_tarihi": TARIH_DAGITIM,
            "kaynak_id": kaynak_id,
            "kaynak_satir_idler": kaynak_satirlar,
            "tutar": Decimal(tutar),
            "yontem": yontem,
            "hedefler": [h if isinstance(h, dict) else {"satir_id": h} for h in hedefler],
        }

    def _lot(self, lot_no="LOT-A", depo="ANA DEPO"):
        with get_session() as s:
            depo_id = s.scalar(select(Depo.id).where(Depo.ad == depo))
            return s.scalar(select(StokLotu).where(StokLotu.lot_no.like(f"{lot_no}%"), StokLotu.depo_id == depo_id))

    # ------------------------------------------------------------ testler
    def test_kabul_ornegi_stok_smm_gm_ve_geri_alma(self):
        from database.masraf_dagitim_service import MasrafDagitimService
        from database.models.genel_muhasebe import MuhasebeFisi, MuhasebeFisiSatiri
        from database.models.satis_faturasi import SatisFaturasiSatiri

        self._gm_kur()
        _fid, alis_satir = self._alis()
        satis_id = self._sat("40")
        kaynak_id, ks = self._gider("1000")

        onizleme = MasrafDagitimService.onizle(self._veri(kaynak_id, ks, [alis_satir]))
        self.assertEqual(onizleme["engeller"], [])
        s0 = onizleme["satirlar"][0]
        self.assertEqual(s0["pay"], Decimal("1000.00"))
        self.assertEqual(s0["yeni_birim_maliyet"], Decimal("110.0000"))
        self.assertEqual(onizleme["stok_payi"], Decimal("600.00"))
        self.assertEqual(onizleme["smm_payi"], Decimal("400.00"))

        did = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir]))
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("100"))  # taslak etkisiz
        sonuc = MasrafDagitimService.onayla(did)
        self.assertEqual(sonuc["stok_payi"], Decimal("600.00"))
        self.assertEqual(sonuc["smm_payi"], Decimal("400.00"))
        lot = self._lot()
        self.assertEqual(Decimal(str(lot.birim_maliyet)), Decimal("110"))
        self.assertEqual(Decimal(str(lot.kalan_miktar)) * Decimal(str(lot.birim_maliyet)), Decimal("6600"))
        with get_session() as s:
            satis = s.scalar(select(SatisFaturasiSatiri).where(SatisFaturasiSatiri.fatura_id == satis_id))
            self.assertEqual(Decimal(str(satis.fifo_birim_maliyeti)) * Decimal(str(satis.miktar)), Decimal("4400"))
            fis = s.get(MuhasebeFisi, sonuc["fis_id"])
            self.assertEqual(fis.kaynak_turu, "masraf_dagitimi")
            self.assertEqual(Decimal(str(fis.toplam_borc)), Decimal(str(fis.toplam_alacak)))
            kalemler = {r.hesap_kodu: (Decimal(str(r.borc)), Decimal(str(r.alacak)))
                        for r in s.scalars(select(MuhasebeFisiSatiri).where(MuhasebeFisiSatiri.fis_id == fis.id))}
        self.assertEqual(kalemler["153.01.0001"], (Decimal("600.00"), Decimal("0.00")))
        self.assertEqual(kalemler["621.01.0001"], (Decimal("400.00"), Decimal("0.00")))
        self.assertEqual(kalemler["770.01.0001"], (Decimal("0.00"), Decimal("1000.00")))

        # Kâr analizi / gelir tablosu uyumu
        from database.rapor_service import RaporService

        gt = RaporService.gelir_tablosu(date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(Decimal(str(gt["ozet"]["maliyete_aktarilan_masraf"])), Decimal("1000.00"))

        # Çift onay etkisiz
        from database.masraf_dagitim_service import ZatenIslendi

        with self.assertRaises(ZatenIslendi):
            MasrafDagitimService.onayla(did)
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("110"))

        # Bağlı belgeler kilitli
        from database.alis_faturasi_service import AlisFaturasiService
        from database.hizmet_faturasi_service import HizmetFaturasiService

        with self.assertRaises(ValueError):
            AlisFaturasiService.iptal_et(_fid)
        with self.assertRaises(ValueError):
            HizmetFaturasiService.iptal_et(kaynak_id)

        # Geri alma: maliyet eski haline, ters fiş, ikinci geri alma etkisiz
        with self.assertRaises(ValueError):
            MasrafDagitimService.geri_al(did, "")
        self.assertTrue(MasrafDagitimService.geri_al(did, "Yanlış belge"))
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("100"))
        self.assertFalse(MasrafDagitimService.geri_al(did, "tekrar"))
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("100"))
        d = MasrafDagitimService.getir(did)
        self.assertEqual(d["durum"], "İPTAL EDİLDİ")
        with get_session() as s:
            ters = s.get(MuhasebeFisi, d["ters_fis_id"])
            self.assertEqual(Decimal(str(ters.toplam_borc)), Decimal("1000.00"))
            satis = s.scalar(select(SatisFaturasiSatiri).where(SatisFaturasiSatiri.fatura_id == satis_id))
            self.assertEqual(Decimal(str(satis.fifo_birim_maliyeti)), Decimal("100"))
        islemler = [g["islem"] for g in d["gecmis"]]
        self.assertEqual(islemler, ["TASLAK OLUŞTUR", "ONAY", "GERİ AL"])
        # Geri alma sonrası kilit kalkar
        MasrafDagitimService.kilit_kontrol(alis_fatura_id=_fid)

    def test_kismi_dagitim_ve_asim_engeli(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        _f, alis_satir = self._alis()
        kaynak_id, ks = self._gider("1000")
        d1 = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir], tutar="600"))
        MasrafDagitimService.onayla(d1)
        d2 = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir], tutar="400"))
        sonuc = MasrafDagitimService.onayla(d2)
        self.assertIsNone(sonuc["fis_id"])  # GM kullanılmıyor → uyarı ile onay
        self.assertTrue(any("muhasebe" in u.lower() for u in sonuc["uyarilar"]))
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("110"))
        with self.assertRaises(ValueError) as ctx:
            MasrafDagitimService.onizle(self._veri(kaynak_id, ks, [alis_satir], tutar="1"))
        self.assertIn("aşamaz", str(ctx.exception))
        self.assertEqual(MasrafDagitimService.kaynak_belgeler(), [])

    def test_onizleme_gecersizlesir(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        _f, alis_satir = self._alis()
        kaynak_id, ks = self._gider("1000")
        did = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir]))
        self._sat("10")
        with self.assertRaises(ValueError) as ctx:
            MasrafDagitimService.onayla(did)
        self.assertIn("Önizleme", str(ctx.exception))
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("100"))
        MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir]), did)
        sonuc = MasrafDagitimService.onayla(did)
        self.assertEqual(sonuc["smm_payi"], Decimal("100.00"))

    def test_eksik_hesap_eslemesi_onayi_engeller(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        self._gm_kur(eksik=("satilan_mal_maliyeti",))
        _f, alis_satir = self._alis()
        self._sat("40")
        kaynak_id, ks = self._gider("1000")
        oniz = MasrafDagitimService.onizle(self._veri(kaynak_id, ks, [alis_satir]))
        self.assertTrue(any("satilan_mal_maliyeti" in e for e in oniz["engeller"]))
        did = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir]))
        with self.assertRaises(ValueError):
            MasrafDagitimService.onayla(did)
        self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("100"))
        self.assertEqual(MasrafDagitimService.getir(did)["durum"], "TASLAK")

    def test_yontemler_ve_dogrulamalar(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        _f1, s1 = self._alis("U001", "100", "100", "LOT-A")
        _f2, s2 = self._alis("U001", "50", "100", "LOT-B")
        _f3, s3 = self._alis("U002", "10", "500", "LOT-C", birim="Koli")
        kaynak_id, ks = self._gider("1000")

        tutar = MasrafDagitimService.onizle(self._veri(kaynak_id, ks, [s1, s2, s3]))
        paylar = {s["alis_fatura_satiri_id"]: s["pay"] for s in tutar["satirlar"]}
        self.assertEqual(sum(paylar.values()), Decimal("1000.00"))
        self.assertEqual(paylar[s1], Decimal("500.00"))

        # Miktar: 100/50 → 666.67 / 333.33 (kuruş kalanı deterministik)
        miktar = MasrafDagitimService.onizle(self._veri(kaynak_id, ks, [s1, s2], yontem="MIKTAR"))
        mp = [s["pay"] for s in miktar["satirlar"]]
        self.assertEqual(mp, [Decimal("666.67"), Decimal("333.33")])
        with self.assertRaises(ValueError) as ctx:
            MasrafDagitimService.onizle(self._veri(kaynak_id, ks, [s1, s3], yontem="MIKTAR"))
        self.assertIn("birim", str(ctx.exception))

        # Ağırlık: U001 kartında 2 kg var, U002'de yok → hata
        with self.assertRaises(ValueError) as ctx:
            MasrafDagitimService.onizle(self._veri(kaynak_id, ks, [s1, s3], yontem="AGIRLIK"))
        self.assertIn("Ağırlık", str(ctx.exception))
        agir = MasrafDagitimService.onizle(
            self._veri(kaynak_id, ks, [s1, {"satir_id": s3, "olcu": "30"}], yontem="AGIRLIK")
        )
        ap = {s["alis_fatura_satiri_id"]: s["pay"] for s in agir["satirlar"]}
        self.assertEqual(ap[s1], Decimal("400.00"))  # 200 kg / (200+300)
        with self.assertRaises(ValueError):
            MasrafDagitimService.onizle(self._veri(kaynak_id, ks, [s1, s2], yontem="HACIM"))

        # Elle: toplam tutara eşit olmalı
        with self.assertRaises(ValueError):
            MasrafDagitimService.onizle(self._veri(
                kaynak_id, ks, [{"satir_id": s1, "elle_tutar": "300"}, {"satir_id": s2, "elle_tutar": "600"}],
                yontem="ELLE"))
        elle = MasrafDagitimService.onizle(self._veri(
            kaynak_id, ks, [{"satir_id": s1, "elle_tutar": "300"}, {"satir_id": s2, "elle_tutar": "700"}],
            yontem="ELLE"))
        self.assertEqual([s["pay"] for s in elle["satirlar"]], [Decimal("300.00"), Decimal("700.00")])

        with self.assertRaises(ValueError):
            MasrafDagitimService.onizle(self._veri(kaynak_id, ks, [s1, s1]))
        with self.assertRaises(ValueError):
            v = self._veri(kaynak_id, ks, [s1])
            v["dagitim_tarihi"] = date(2099, 1, 1)
            MasrafDagitimService.onizle(v)

    def test_uygunluk_ve_kdv_haric(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        kaynak_id, ks = self._gider("1000", ek_kira="500")
        belgeler = MasrafDagitimService.kaynak_belgeler()
        self.assertEqual(len(belgeler), 1)
        self.assertEqual(belgeler[0]["uygun_tutar"], Decimal("1000.00"))  # kira uygun değil, KDV hariç
        self.assertEqual(belgeler[0]["kalan"], Decimal("1500.00"))
        detay = MasrafDagitimService.kaynak_detay(kaynak_id)
        self.assertEqual([s["uygun"] for s in detay["satirlar"]], [True, False])

    def test_kapali_donem_engeli(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        _f, alis_satir = self._alis()
        kaynak_id, ks = self._gider("1000")
        with get_session() as s:
            s.add(Donem(firma_id=self.firma_id, donem_adi="Kapalı", baslangic_tarihi=date(2026, 6, 10),
                        bitis_tarihi=date(2026, 6, 10), aktif=False, kapali=True, varsayilan=False))
        with self.assertRaises(ValueError) as ctx:
            MasrafDagitimService.onizle(self._veri(kaynak_id, ks, [alis_satir]))
        self.assertIn("kapalı", str(ctx.exception))

    def test_transfer_zinciri_ve_alis_iadesi(self):
        from database.alis_iade_faturasi_service import AlisIadeFaturasiService
        from database.masraf_dagitim_service import MasrafDagitimService
        from database.stok_service import StokService

        _f, alis_satir = self._alis()
        StokService.depo_transfer_kaydet(
            {"cikis_depo": "ANA DEPO", "giris_depo": "YEDEK DEPO", "fis_tarihi": date(2026, 6, 3)},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("30"), "birim_fiyat": Decimal("100")}],
        )
        AlisIadeFaturasiService.kaydet(
            {"iade_tarihi": date(2026, 6, 4), "cari_id": self.tedarikci_id, "depo": "ANA DEPO"},
            [{"urun_kodu": "U001", "urun_adi": "Test Ürün", "miktar": Decimal("10"), "birim_fiyat": Decimal("100"),
              "kdv_orani": Decimal("20"), "kaynak_fatura_satiri_id": alis_satir}],
        )
        kaynak_id, ks = self._gider("1000")
        did = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir]))
        sonuc = MasrafDagitimService.onayla(did)
        # 60 ana depoda + 30 yedek depoda stokta, 10 tedarikçiye iade
        self.assertEqual(sonuc["stok_payi"], Decimal("900.00"))
        self.assertEqual(sonuc["iade_payi"], Decimal("100.00"))
        self.assertEqual(sonuc["smm_payi"], Decimal("0.00"))
        with get_session() as s:
            yedek_id = s.scalar(select(Depo.id).where(Depo.ad == "YEDEK DEPO"))
            yedek_lot = s.scalar(select(StokLotu).where(StokLotu.depo_id == yedek_id))
        self.assertEqual(Decimal(str(yedek_lot.birim_maliyet)), Decimal("110"))
        self.assertTrue(MasrafDagitimService.geri_al(did, "test"))
        with get_session() as s:
            yedek_lot = s.get(StokLotu, yedek_lot.id)
        self.assertEqual(Decimal(str(yedek_lot.birim_maliyet)), Decimal("100"))

    def test_liste_filtre_ve_taslak_iptal(self):
        from database.masraf_dagitim_service import MasrafDagitimService

        _f, alis_satir = self._alis()
        kaynak_id, ks = self._gider("1000")
        did = MasrafDagitimService.taslak_kaydet(self._veri(kaynak_id, ks, [alis_satir], tutar="250"))
        liste = MasrafDagitimService.listele(durum="TASLAK")
        self.assertEqual([x["id"] for x in liste], [did])
        self.assertEqual(MasrafDagitimService.listele(durum="ONAYLANDI"), [])
        self.assertEqual(len(MasrafDagitimService.listele(cari_id=self.nakliyeci_id)), 1)
        self.assertEqual(MasrafDagitimService.fatura_baglantilari(_f)[0]["pay"], Decimal("250.00"))
        MasrafDagitimService.iptal_et(did, "vazgeçildi")
        self.assertEqual(MasrafDagitimService.getir(did)["durum"], "İPTAL EDİLDİ")
        with self.assertRaises(ValueError):
            MasrafDagitimService.onayla(did)


    def test_ekran_akisi_onizle_onayla_geri_al(self):
        import tkinter as tk

        from database.masraf_dagitim_service import MasrafDagitimService
        from masraf_dagitim_ui import MasrafDagitimDialog

        _f, alis_satir = self._alis()
        self._sat("40")
        kaynak_id, ks = self._gider("1000", ek_kira="500")
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("Tk yok")
        root.withdraw()
        try:
            with patch("masraf_dagitim_ui.messagebox") as mb:
                mb.askyesno.return_value = True
                d = MasrafDagitimDialog(root)
                d.withdraw()
                d.tarih.delete(0, "end")
                d.tarih.insert(0, TARIH_DAGITIM.strftime("%d.%m.%Y"))
                d.kaynak_ayarla(kaynak_id)
                self.assertEqual(d.secili_kaynak, {ks[0]})  # kira otomatik seçilmez
                self.assertEqual(d.tutar.get(), "1000")
                d.hedef_ekle([h for h in MasrafDagitimService.hedef_satirlar() if h["satir_id"] == alis_satir])
                self.assertTrue(d.onizle())
                self.assertEqual(d.hedef_tablo.item(str(alis_satir), "values")[-1], "110")
                d.tutar.delete(0, "end")
                d.tutar.insert(0, "1000")
                d._degisiklik()
                self.assertIsNone(d.onizleme)  # değişiklik önizlemeyi geçersiz kılar
                self.assertTrue(d.onayla())
                self.assertEqual(d.durum, "ONAYLANDI")
                self.assertEqual(str(d.tarih.cget("state")), "disabled")
                self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("110"))
                self.assertTrue(d.geri_al("ekran testi"))
                self.assertEqual(d.durum, "İPTAL EDİLDİ")
                self.assertEqual(Decimal(str(self._lot().birim_maliyet)), Decimal("100"))
                d.kapat()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
