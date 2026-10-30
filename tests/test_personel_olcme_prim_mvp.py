"""Ölçme / Prim: H=15000, 50/30/20 eşit 3 kişi, idempotent bordro, iptal→yeniden onay."""

from __future__ import annotations

import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("MUHASEBE_DB_DIR", tempfile.mkdtemp(prefix="cin_olcme_prim_"))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from database.database import Base
from database.models.personel import PersonelHakedis
from database.models.personel_performans import PersonelPrimDonem, PersonelPrimPay
from database.personel_performans_sema import schema_hazirla
from database.personel_performans_service import PersonelPerformansService
from database.personel_prim_motoru import DagitimKisi, kisi_dagitimi, tahsil_kar_katkisi
from database.personel_service import PersonelService
from database.session_manager import oturum


class HFormulOrnekTest(unittest.TestCase):
    """Belge örneği: S=100.000 C=70.000 tahsilat %50 → H=15.000."""

    def test_h_ornek_15000(self):
        h = tahsil_kar_katkisi(S=100_000, C=70_000, F=100_000, T=50_000)
        self.assertEqual(h["M"], Decimal("30000.00"))
        self.assertEqual(h["H"], Decimal("15000.00"))

    def test_h_servis_tahsilat_orani(self):
        h = PersonelPerformansService.tahsil_kar_h(
            S=100_000, C=70_000, tahsilat_orani=Decimal("0.5")
        )
        self.assertEqual(h["H"], Decimal("15000.00"))


class EsitUcKisiDagitimTest(unittest.TestCase):
    """Üç eşit kişi: 50/30/20, kuruş en büyük kalan; toplam = havuz."""

    def test_50_30_20_esit_uc_kisi(self):
        butce = Decimal("10000.00")
        d = kisi_dagitimi(
            butce,
            [
                DagitimKisi(1, 0, Decimal(100), Decimal(1)),
                DagitimKisi(2, 0, Decimal(100), Decimal(1)),
                DagitimKisi(3, 0, Decimal(100), Decimal(1)),
            ],
            agirlik_ekip=Decimal("0.50"),
            agirlik_katki=Decimal("0.30"),
            agirlik_kidem=Decimal("0.20"),
        )
        self.assertEqual(len(d["kisiler"]), 3)
        self.assertEqual(d["dagitilan"], butce)
        self.assertEqual(d["dagitilmamis"], Decimal("0.00"))
        tutarlar = [s["toplam"] for s in d["kisiler"]]
        self.assertLessEqual(max(tutarlar) - min(tutarlar), Decimal("0.01"))
        self.assertEqual(sum(tutarlar, Decimal("0")), butce)
        ekip = sum((s["ekip_payi"] for s in d["kisiler"]), Decimal("0"))
        katki = sum((s["katki_payi"] for s in d["kisiler"]), Decimal("0"))
        kidem = sum((s["kidem_payi"] for s in d["kisiler"]), Decimal("0"))
        self.assertEqual(ekip + katki + kidem, butce)
        self.assertAlmostEqual(float(ekip), 5000.0, delta=0.05)
        self.assertAlmostEqual(float(katki), 3000.0, delta=0.05)
        self.assertAlmostEqual(float(kidem), 2000.0, delta=0.05)


class PrimDonemBordroTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cin_olcme_db_")
        cls.db = Path(cls.tmp) / "test.db"
        cls.engine = create_engine(f"sqlite:///{cls.db.as_posix()}", future=True)
        import database.models.personel  # noqa: F401
        import database.models.personel_performans  # noqa: F401
        import database.models.kart_turu  # noqa: F401

        Base.metadata.create_all(cls.engine)
        schema_hazirla(cls.engine)

    def setUp(self):
        self.sf = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self._patches = [
            patch("database.personel_service.get_session", self._session_cm),
            patch("database.personel_performans_service.get_session", self._session_cm),
            patch("database.personel_service.schema_hazirla"),
            patch("database.personel_performans_service.schema_hazirla"),
            patch("database.personel_performans_sema.schema_hazirla"),
            patch("database.access.yetki_var", return_value=True),
            patch("database.access.yetki_zorunlu"),
            patch("database.access.yazma_zorunlu"),
            patch("database.access.aktif_firma_zorunlu"),
            patch("database.donem_service.DonemService.kayit_izinli_mi", return_value=True),
        ]
        for p in self._patches:
            p.start()
        oturum.user_id = 7
        oturum.kullanici_adi = "olcme_test"
        oturum.ad_soyad = "Ölçme Test"
        oturum.role_kod = "YONETICI"
        oturum.permissions = set()
        self.pids = []
        self._uid = getattr(type(self), "_uid_seq", 0)
        type(self)._uid_seq = self._uid + 1
        for i, ad in enumerate(("Ali", "Veli", "Ayşe"), start=1):
            r = PersonelService.kaydet(
                {
                    "kod": f"O{self._uid:02d}{i}",
                    "ad": ad,
                    "soyad": "Test",
                    "kimlik_turu": "DIGER",
                    "calisma_durumu": "AKTIF",
                    "donem": {"giris_tarihi": "2024-01-01", "gorev": "Depo"},
                }
            )
            self.pids.append(r["id"])

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _session_cm(self):
        outer = self

        class CM:
            def __enter__(self):
                self.s = outer.sf()
                return self.s

            def __exit__(self, exc_type, exc, tb):
                try:
                    if exc_type is not None:
                        self.s.rollback()
                    else:
                        self.s.commit()
                except Exception:
                    self.s.rollback()
                    raise
                finally:
                    self.s.close()
                return False

        return CM()

    def _kisiler(self):
        return [
            {"personel_id": self.pids[0], "hizmet_yili": 0, "performans": 100, "katilim": 1},
            {"personel_id": self.pids[1], "hizmet_yili": 0, "performans": 100, "katilim": 1},
            {"personel_id": self.pids[2], "hizmet_yili": 0, "performans": 100, "katilim": 1},
        ]

    def test_hesap_idempotent_ve_bordro_aktarim(self):
        donem = PersonelPerformansService.prim_donem_olustur(
            2026, 10, havuz=10_000, politika_json='{"ekip":50,"katki":30,"kidem":20}'
        )
        tekrar = PersonelPerformansService.prim_donem_olustur(2026, 10, havuz=10_000)
        self.assertTrue(tekrar.get("mevcut"))
        self.assertEqual(tekrar["id"], donem["id"])
        self.assertEqual(donem.get("olcut_surum") or tekrar.get("olcut_surum"), "2026-10-16")

        kisiler = self._kisiler()
        r1 = PersonelPerformansService.prim_hesapla(
            donem["id"], kisiler=kisiler, havuz=10_000, satis_verisinden=False
        )
        r2 = PersonelPerformansService.prim_hesapla(
            donem["id"], kisiler=kisiler, havuz=10_000, satis_verisinden=False
        )
        self.assertEqual(len(r1["paylar"]), 3)
        self.assertEqual(len(r2["paylar"]), 3)
        with self._session_cm() as s:
            n = s.scalar(
                select(func.count())
                .select_from(PersonelPrimPay)
                .where(PersonelPrimPay.donem_id == donem["id"])
            )
        self.assertEqual(n, 3)
        self.assertEqual(Decimal(str(r1["dagitilan"])), Decimal(str(r2["dagitilan"])))

        onay = PersonelPerformansService.prim_onayla(donem["id"], bordroya_aktar=True)
        self.assertEqual(onay["durum"], "BORDROYA_AKTARILDI")
        bag = onay["bordro"]
        self.assertTrue(bag["baglandi"])
        self.assertEqual(bag["hakedis_sayisi"], 3)
        self.assertFalse(bag.get("tekrar"))

        # İkinci aktarım — yeni hakediş açılmaz
        bag2 = PersonelPerformansService.prim_bordroya_bagla(donem["id"])
        self.assertTrue(bag2["baglandi"])
        self.assertTrue(bag2.get("tekrar"))
        with self._session_cm() as s:
            n_hak = s.scalar(
                select(func.count())
                .select_from(PersonelHakedis)
                .where(
                    PersonelHakedis.kayit_turu == "PRIM",
                    PersonelHakedis.yil == 2026,
                    PersonelHakedis.ay == 10,
                    PersonelHakedis.durum != "IPTAL",
                )
            )
            d = s.get(PersonelPrimDonem, donem["id"])
            self.assertEqual(d.durum, "BORDROYA_AKTARILDI")
        self.assertEqual(n_hak, 3)

        # Kapalı dönemde yeniden hesap engelli
        with self.assertRaises(ValueError):
            PersonelPerformansService.prim_hesapla(donem["id"], kisiler=kisiler)

    def test_iptal_sonra_yeniden_onay_cift_borc_yok(self):
        donem = PersonelPerformansService.prim_donem_olustur(
            2026, 11, havuz=10_000, politika_json='{"ekip":50,"katki":30,"kidem":20}'
        )
        PersonelPerformansService.prim_hesapla(
            donem["id"], kisiler=self._kisiler(), havuz=10_000, satis_verisinden=False
        )
        PersonelPerformansService.prim_onayla(donem["id"], bordroya_aktar=True)

        with self._session_cm() as s:
            n1 = s.scalar(
                select(func.count())
                .select_from(PersonelHakedis)
                .where(
                    PersonelHakedis.kayit_turu == "PRIM",
                    PersonelHakedis.yil == 2026,
                    PersonelHakedis.ay == 11,
                )
            )
        self.assertEqual(n1, 3)

        iptal = PersonelPerformansService.prim_iptal(donem["id"])
        self.assertEqual(iptal["durum"], "HESAPLANDI")
        self.assertEqual(iptal["iptal_edilen_hakedis"], 3)

        with self._session_cm() as s:
            aktif = s.scalar(
                select(func.count())
                .select_from(PersonelHakedis)
                .where(
                    PersonelHakedis.kayit_turu == "PRIM",
                    PersonelHakedis.yil == 2026,
                    PersonelHakedis.ay == 11,
                    PersonelHakedis.durum != "IPTAL",
                )
            )
        self.assertEqual(aktif, 0)

        # Yeniden onay — aynı kaynak satırları yeniden kullanılır, toplam 3 PRIM satırı kalır
        onay2 = PersonelPerformansService.prim_onayla(donem["id"], bordroya_aktar=True)
        self.assertEqual(onay2["durum"], "BORDROYA_AKTARILDI")
        with self._session_cm() as s:
            toplam_prim = s.scalar(
                select(func.count())
                .select_from(PersonelHakedis)
                .where(
                    PersonelHakedis.kayit_turu == "PRIM",
                    PersonelHakedis.yil == 2026,
                    PersonelHakedis.ay == 11,
                )
            )
            aktif2 = s.scalar(
                select(func.count())
                .select_from(PersonelHakedis)
                .where(
                    PersonelHakedis.kayit_turu == "PRIM",
                    PersonelHakedis.yil == 2026,
                    PersonelHakedis.ay == 11,
                    PersonelHakedis.durum != "IPTAL",
                )
            )
            ek_toplam = s.scalar(
                select(func.sum(PersonelHakedis.ek_odeme)).where(
                    PersonelHakedis.kayit_turu == "PRIM",
                    PersonelHakedis.yil == 2026,
                    PersonelHakedis.ay == 11,
                    PersonelHakedis.durum != "IPTAL",
                )
            )
        self.assertEqual(toplam_prim, 3)  # çift satır yok
        self.assertEqual(aktif2, 3)
        self.assertEqual(Decimal(str(ek_toplam or 0)), Decimal("10000.00"))

    def test_kariyer_karari_kalici(self):
        k = PersonelPerformansService.kariyer_karari(
            {
                "personel_id": self.pids[0],
                "kademe": "YETKIN",
                "yol": "UZMANLIK",
                "unvan": "Depo Uzmanı",
                "gorev": "Hazırlama",
                "ucret_bandi": "B2",
                "gecerlilik": "2026-11-01",
                "onayli": False,
            }
        )
        self.assertTrue(k["ortaklik_degil"])
        liste = PersonelPerformansService.kariyer_listele(self.pids[0])
        self.assertTrue(any(x["id"] == k["id"] and x["unvan"] == "Depo Uzmanı" for x in liste))
        onay = PersonelPerformansService.kariyer_onayla(k["id"])
        self.assertTrue(onay["onayli"])

    def test_kapali_donem_olcut_sessiz_yeniden_yazilmaz(self):
        donem = PersonelPerformansService.prim_donem_olustur(2026, 12, havuz=1000)
        PersonelPerformansService.prim_hesapla(
            donem["id"], kisiler=self._kisiler()[:1], havuz=1000, satis_verisinden=False
        )
        PersonelPerformansService.degerlendirme_kaydet(
            {
                "personel_id": self.pids[0],
                "yil": 2026,
                "ay": 12,
                "gorev_sonucu": 80,
                "kalite": 80,
                "ekip_katkisi": 80,
                "gelisim": 80,
                "ornek_sayisi": 10,
                "kesin": True,
                "olcut_surum": "2026-10-16",
            }
        )
        PersonelPerformansService.prim_onayla(donem["id"], bordroya_aktar=True)
        with self.assertRaises(ValueError):
            PersonelPerformansService.degerlendirme_kaydet(
                {
                    "personel_id": self.pids[0],
                    "yil": 2026,
                    "ay": 12,
                    "gorev_sonucu": 90,
                    "kalite": 90,
                    "ekip_katkisi": 90,
                    "gelisim": 90,
                    "ornek_sayisi": 10,
                    "kesin": True,
                    "olcut_surum": "2026-11-01-YENI",
                }
            )

    def test_prim_excel_pdf_donem_pay_ciktisi(self):
        donem = PersonelPerformansService.prim_donem_olustur(
            2026, 9, havuz=10_000, politika_json='{"ekip":50,"katki":30,"kidem":20}'
        )
        PersonelPerformansService.prim_hesapla(
            donem["id"], kisiler=self._kisiler(), havuz=10_000, satis_verisinden=False
        )
        cikti = PersonelPerformansService.prim_donem_cikti(donem["id"])
        self.assertEqual(cikti["yil"], 2026)
        self.assertEqual(cikti["ay"], 9)
        self.assertEqual(len(cikti["satirlar"]), 3)
        self.assertEqual(Decimal(str(cikti["dagitilan"])), Decimal("10000.00"))
        self.assertIn("olcut_surum", cikti)
        self.assertIn("politika_json", cikti)

        xlsx = Path(self.tmp) / "prim_pay.xlsx"
        pdf = Path(self.tmp) / "prim_pay.pdf"
        PersonelPerformansService.prim_excel_aktar(donem["id"], str(xlsx))
        self.assertTrue(xlsx.is_file() and xlsx.stat().st_size > 0)
        try:
            PersonelPerformansService.prim_pdf_aktar(donem["id"], str(pdf))
            self.assertTrue(pdf.is_file() and pdf.stat().st_size > 0)
        except RuntimeError as exc:
            if "reportlab" not in str(exc).casefold():
                raise
        from openpyxl import load_workbook

        wb = load_workbook(xlsx)
        ws = wb.active
        metin = " ".join(str(c.value or "") for row in ws.iter_rows(max_row=12) for c in row)
        self.assertIn("2026-09", metin)
        self.assertIn("Politika", metin)


class AyarFormTurTest(unittest.TestCase):
    """personel_ayar_ui — gün/oran/tarih/bool tür ayrımı (simpledialog yok)."""

    def test_alan_turu_ve_ozet(self):
        from personel_ayar_ui import _alan_turu, _deger_ozeti, _parse_deger_json

        self.assertEqual(_alan_turu("gun_oncesi", 1), "gun")
        self.assertEqual(_alan_turu("takip_ay_sonu", True), "bool")
        self.assertEqual(_alan_turu("prim_orani", 0.1), "oran")
        self.assertEqual(_alan_turu("baslangic", "2026-01-01"), "tarih")
        ozet = _deger_ozeti('{"gun_oncesi": 1, "aciklama": "x"}')
        self.assertIn("gün", ozet)
        self.assertIn("gun_oncesi", ozet)
        veri = _parse_deger_json(
            '{"hizmet_yil_esikleri":[{"max_yil":5,"gun":14}],"yas_18_alti_veya_50_ustu_min":20}'
        )
        self.assertIn("hizmet_yil_esikleri", veri)
        import personel_ayar_ui as ayar_mod

        self.assertFalse(hasattr(ayar_mod, "simpledialog"))
        src = (Path(__file__).resolve().parents[1] / "personel_ayar_ui.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("from tkinter import messagebox, simpledialog", src)
        self.assertNotIn("simpledialog.askstring", src)


class SgkPersonelBaglantiTest(unittest.TestCase):
    """Özlük/SGK: MPHB → standart personel kartı bağlantısı (ikinci depo yok)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="cin_sgk_bag_")
        cls.db = Path(cls.tmp) / "test.db"
        cls.engine = create_engine(f"sqlite:///{cls.db.as_posix()}", future=True)
        import database.models.personel  # noqa: F401
        import database.models.kart_turu  # noqa: F401

        Base.metadata.create_all(cls.engine)
        from database.personel_sema import schema_hazirla as personel_schema

        personel_schema(cls.engine)

    def setUp(self):
        self.sf = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self._patches = [
            patch("database.personel_service.get_session", self._session_cm),
            patch("database.personel_sgk_service.get_session", self._session_cm),
            patch("database.personel_service.schema_hazirla"),
            patch("database.personel_sgk_service.schema_hazirla"),
            patch("database.personel_sema.schema_hazirla"),
            patch("database.access.yetki_var", return_value=True),
            patch("database.access.yetki_zorunlu"),
            patch("database.access.yazma_zorunlu"),
            patch("database.access.aktif_firma_zorunlu"),
            patch("database.donem_service.DonemService.kayit_izinli_mi", return_value=True),
        ]
        for p in self._patches:
            p.start()
        oturum.user_id = 8
        oturum.kullanici_adi = "sgk_test"
        oturum.ad_soyad = "SGK Test"
        oturum.role_kod = "YONETICI"
        oturum.permissions = set()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _session_cm(self):
        outer = self

        class CM:
            def __enter__(self):
                self.s = outer.sf()
                return self.s

            def __exit__(self, exc_type, exc, tb):
                try:
                    if exc_type is not None:
                        self.s.rollback()
                    else:
                        self.s.commit()
                except Exception:
                    self.s.rollback()
                    raise
                finally:
                    self.s.close()
                return False

        return CM()

    def test_mphb_personel_bagla_tek_depo(self):
        from database.personel_sgk_service import PersonelSgkService

        kart = PersonelService.kaydet(
            {
                "kod": "SGK01",
                "ad": "Bağlı",
                "soyad": "Personel",
                "kimlik_turu": "DIGER",
                "calisma_durumu": "AKTIF",
                "donem": {"giris_tarihi": "2025-01-01", "gorev": "Depo"},
            }
        )
        islem = PersonelSgkService.kaydet(
            {
                "islem_turu": "MPHB",
                "isyeri_kodu": "MERKEZ",
                "donem_yil": 2026,
                "donem_ay": 10,
                "nitelik": "ASIL",
                "durum": "HAZIRLANACAK",
            }
        )
        PersonelSgkService.bagla_personel(islem["id"], kart["id"])
        # İkinci bağlama idempotent
        PersonelSgkService.bagla_personel(islem["id"], kart["id"])
        liste = PersonelSgkService.listele(personel_id=kart["id"])
        self.assertTrue(any(x["id"] == islem["id"] for x in liste))
        kayit = next(x for x in liste if x["id"] == islem["id"])
        self.assertIn(kart["id"], kayit["bagli_personel_ids"])
        # Aynı işyeri/dönem ikinci MPHB engelli
        with self.assertRaises(ValueError):
            PersonelSgkService.kaydet(
                {
                    "islem_turu": "MPHB",
                    "isyeri_kodu": "MERKEZ",
                    "donem_yil": 2026,
                    "donem_ay": 10,
                    "nitelik": "ASIL",
                    "durum": "HAZIRLANACAK",
                }
            )


if __name__ == "__main__":
    unittest.main()
