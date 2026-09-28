"""Tahsilat / ödeme makbuzu: MKB numaralandırma, cari bakiye, kartla tahsilat/ödeme, düzenleme, iptal.

Yalnız geçici test veritabanı kullanır.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import sessionmaker

from database.database import (
    Base,
    _aktif_engine_bagla,
    company_db,
    get_session,
    kasa_makbuz_schemasini_guncelle,
)
from database.finans_service import FinansService
from database.models.cari import Cari, CariIslem
from database.models.donem import Donem
from database.models.finans import (
    BankaKarti,
    FinansHareketi,
    FinansHesabi,
    KasaMakbuzu,
    KrediKartiOdeme,
    KrediKartiTanimi,
    PosValorKaydi,
)
from database.models.firma import Firma
from database.models.sube import Sube
from database.session_manager import oturum


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


class TahsilatMakbuzuTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test_makbuz.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        import importlib
        import pkgutil

        import database.models as modeller

        for bilgi in pkgutil.iter_modules(modeller.__path__):
            importlib.import_module(f"database.models.{bilgi.name}")

        Base.metadata.create_all(eng)
        self.eng = eng
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="MKT", unvan="Makbuz Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(Sube(firma_id=firma.id, sube_kodu="MERKEZ", sube_adi="Merkez", merkez=True, aktif=True))
            s.add(
                Donem(
                    firma_id=firma.id,
                    donem_adi="2026",
                    baslangic_tarihi=date(2000, 1, 1),
                    bitis_tarihi=date(2099, 12, 31),
                    aktif=True,
                    kapali=False,
                    varsayilan=True,
                )
            )
            musteri = Cari(cari_kodu="M001", unvan="ALİ ÇELİK MOBİLYA LTD", cari_turu="Müşteri")
            tedarikci = Cari(cari_kodu="T001", unvan="YILDIZ AKSESUAR", cari_turu="Tedarikçi")
            s.add_all([musteri, tedarikci])
            kasa = FinansHesabi(hesap_adi="TEST KASA", hesap_turu="KASA", acilis_bakiyesi=Decimal("50000"))
            s.add(kasa)
            banka = BankaKarti(banka_adi="TEST BANK", kk_komisyon_orani=Decimal("2"), pos_valor_gun=1)
            s.add(banka)
            s.flush()
            hesaplar = {}
            for alt, tur in (
                ("MEVDUAT", "BANKA"),
                ("KMH", "BANKA"),
                ("POS", "BANKA"),
                ("KREDI_KARTI", "KREDİ KARTI"),
            ):
                h = FinansHesabi(
                    hesap_adi=f"TEST BANK — {alt}",
                    hesap_turu=tur,
                    banka_karti_id=banka.id,
                    alt_hesap_turu=alt,
                    acilis_bakiyesi=Decimal("10000") if alt == "MEVDUAT" else Decimal("0"),
                )
                s.add(h)
                hesaplar[alt] = h
            kk = KrediKartiTanimi(
                banka_karti_id=banka.id, kart_adi="ŞİRKET KARTI", kart_limiti=Decimal("20000"), aktif=True
            )
            s.add(kk)
            s.flush()
            # Müşterinin açılış borcu 1.000 TL
            s.add(
                CariIslem(
                    cari_id=musteri.id,
                    tarih=date(2026, 1, 2),
                    islem_turu="Açılış",
                    belge_no="ACL-1",
                    borc=Decimal("1000"),
                    alacak=Decimal("0"),
                )
            )
            s.add(
                CariIslem(
                    cari_id=tedarikci.id,
                    tarih=date(2026, 1, 2),
                    islem_turu="Açılış",
                    belge_no="ACL-2",
                    borc=Decimal("5000"),
                    alacak=Decimal("0"),
                )
            )
            s.commit()
            self.musteri_id = musteri.id
            self.tedarikci_id = tedarikci.id
            self.kasa_id = kasa.id
            self.pos_id = hesaplar["POS"].id
            self.kmh_id = hesaplar["KMH"].id
            self.kk_hesap_id = hesaplar["KREDI_KARTI"].id
            self.mevduat_adi = hesaplar["MEVDUAT"].hesap_adi
            self.kk_id = kk.id

        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = sessionmaker(
            bind=eng, autoflush=False, autocommit=False, expire_on_commit=False
        )
        company_db._company_id = 91
        company_db._db_path = self.db_path
        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="admin",
            ad_soyad="Test Admin",
            role_kod="YONETICI",
            role_ad="Yönetici",
            permissions=set(),
        )
        oturum.set_company(
            company_id=91, firma_kodu="MKT", firma_unvan="Makbuz Test", firma_uid="mkt", db_path=str(self.db_path)
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            oturum.set_period(d.id, d.donem_adi)
        self._audit = patch("database.user_audit.audit_document", return_value=None)
        self._audit.start()

    def tearDown(self):
        self._audit.stop()
        try:
            company_db.close()
        except Exception:
            pass
        try:
            self.eng.dispose()
        except Exception:
            pass
        oturum.clear()
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    # —— yardımcılar ——
    def _nakit(self, tutar, **ek):
        veri = {
            "tarih": date.today(),
            "cari_id": self.musteri_id,
            "makbuz_no_otomatik": True,
            "satirlar": [
                {"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": tutar}
            ],
        }
        veri.update(ek)
        return FinansService.kasa_tahsilat_makbuzu_kaydet(veri)

    def _hareketler(self, belge_no):
        with get_session() as s:
            return list(s.scalars(select(FinansHareketi).where(FinansHareketi.belge_no == belge_no)).all())

    def _bakiye(self, cari_id):
        return FinansService.cari_bakiye_ozeti(cari_id)

    # —— numaralandırma ——
    def test_oneri_numara_tuketmez_ve_ardisik_ilerler(self):
        self.assertEqual(FinansService.makbuz_no_oner(), "MKB-00001")
        self.assertEqual(FinansService.makbuz_no_oner(), "MKB-00001", "öneri numara tüketmemeli")
        m1 = self._nakit("100")
        m2 = self._nakit("50")
        self.assertEqual((m1.makbuz_no, m2.makbuz_no), ("MKB-00001", "MKB-00002"))
        self.assertEqual(FinansService.makbuz_no_oner(), "MKB-00003")

    def test_farkli_bicimli_elle_numara_diziyi_bozmaz_ve_mkb_dizisini_surdurur(self):
        self._nakit("10", makbuz_no_otomatik=False, makbuz_no="EVB-KS-10841")
        self._nakit("10", makbuz_no_otomatik=False, makbuz_no="MKB-12A")
        self.assertEqual(FinansService.makbuz_no_oner(), "MKB-00001")
        self._nakit("10", makbuz_no_otomatik=False, makbuz_no="MKB-00010")
        self.assertEqual(self._nakit("10").makbuz_no, "MKB-00011")

    def test_numara_siniri_asilinca_bicim_genisler(self):
        self._nakit("10", makbuz_no_otomatik=False, makbuz_no="MKB-99999")
        self.assertEqual(self._nakit("10").makbuz_no, "MKB-100000")

    def test_mukerrer_elle_numara_reddedilir(self):
        self._nakit("10", makbuz_no_otomatik=False, makbuz_no="MKB-00007")
        with self.assertRaises(ValueError):
            self._nakit("10", makbuz_no_otomatik=False, makbuz_no=" mkb-00007 ")
        self.assertTrue(FinansService.makbuz_no_kullanimda_mi("mkb-00007"))
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(KasaMakbuzu.id))), 1)

    def test_eszamanli_kayitlar_farkli_numara_alir(self):
        sonuclar, hatalar = [], []
        bariyer = threading.Barrier(4)

        def kaydet(tutar):
            try:
                bariyer.wait()
                sonuclar.append(self._nakit(tutar).makbuz_no)
            except Exception as exc:  # pragma: no cover - teşhis
                hatalar.append(exc)

        is_parcaciklari = [threading.Thread(target=kaydet, args=(str(10 + i),)) for i in range(4)]
        for t in is_parcaciklari:
            t.start()
        for t in is_parcaciklari:
            t.join()
        self.assertEqual(hatalar, [])
        self.assertEqual(sorted(sonuclar), ["MKB-00001", "MKB-00002", "MKB-00003", "MKB-00004"])

    # —— bakiye ——
    def test_bakiye_borc_alacak_yonu_ve_kayit_sonrasi(self):
        self.assertEqual(
            self._bakiye(self.musteri_id),
            {"bakiye": Decimal("1000.00"), "tutar": Decimal("1000.00"), "yon": "Borçlu"},
        )
        self._nakit("400")
        self.assertEqual(self._bakiye(self.musteri_id)["tutar"], Decimal("600.00"))
        self._nakit("800")
        ozet = self._bakiye(self.musteri_id)
        self.assertEqual((ozet["tutar"], ozet["yon"]), (Decimal("200.00"), "Alacaklı"))
        self.assertEqual(self._bakiye(self.tedarikci_id)["yon"], "Borçlu")

    # —— kartla tahsilat ——
    def test_musteriden_kartla_tahsilat_pos_hesabina_komisyon_ve_valor(self):
        m = FinansService.kasa_tahsilat_makbuzu_kaydet(
            {
                "tarih": date.today(),
                "cari_id": self.musteri_id,
                "makbuz_no_otomatik": True,
                "satirlar": [
                    {
                        "odeme_sekli": "KREDİ KARTIYLA TAHSİLAT",
                        "finans_hesap_id": self.pos_id,
                        "tutar": "1000",
                        "kart_tipi": "KREDI_KARTI",
                        "taksit_sayisi": 1,
                    }
                ],
            }
        )
        hareketler = self._hareketler(m.belge_no)
        self.assertEqual(
            sorted((h.hesap_id, h.hareket_turu, h.tutar) for h in hareketler),
            [(self.pos_id, "POS KOMİSYON", Decimal("20.00")), (self.pos_id, "POS TAHSİLAT", Decimal("1000.00"))],
        )
        self.assertFalse(any(h.hesap_id == self.kasa_id for h in hareketler))
        with get_session() as s:
            pv = s.scalar(select(PosValorKaydi).where(PosValorKaydi.belge_no == m.belge_no))
            self.assertEqual((pv.net_tutar, pv.cari_id, pv.durum), (Decimal("980.00"), self.musteri_id, "BEKLIYOR"))
            islem = s.scalar(select(CariIslem).where(CariIslem.belge_no == m.belge_no))
            self.assertEqual((islem.islem_turu, islem.alacak), ("Tahsilat", Decimal("1000.00")))
        self.assertEqual(m.satirlar[0].pos_valor_id, pv.id)
        self.assertEqual(self._bakiye(self.musteri_id)["tutar"], Decimal("0.00"))

    def test_kart_tahsilati_kasa_hesabina_yazilamaz(self):
        with self.assertRaises(ValueError):
            FinansService.kasa_tahsilat_makbuzu_kaydet(
                {
                    "tarih": date.today(),
                    "cari_id": self.musteri_id,
                    "satirlar": [
                        {"odeme_sekli": "KREDİ KARTIYLA TAHSİLAT", "finans_hesap_id": self.kasa_id, "tutar": "10"}
                    ],
                }
            )
        with self.assertRaises(ValueError):
            FinansService.kasa_tahsilat_makbuzu_kaydet(
                {
                    "tarih": date.today(),
                    "cari_id": self.musteri_id,
                    "satirlar": [{"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.pos_id, "tutar": "10"}],
                }
            )

    # —— tedarikçiye şirket kartıyla ödeme ——
    def _kk_odeme(self, tutar="3000", taksit=3):
        return FinansService.kasa_odeme_makbuzu_kaydet(
            {
                "tarih": date.today(),
                "cari_id": self.tedarikci_id,
                "satirlar": [
                    {
                        "odeme_sekli": "ŞİRKET KREDİ KARTI",
                        "kredi_karti_id": self.kk_id,
                        "tutar": tutar,
                        "taksit_sayisi": taksit,
                    }
                ],
            }
        )

    def test_tedarikciye_sirket_karti_ile_odeme(self):
        m = self._kk_odeme()
        self.assertEqual(m.makbuz_turu, "ODEME")
        self.assertTrue(m.belge_no.startswith("OMK-"))
        hareketler = self._hareketler(m.belge_no)
        self.assertEqual([(h.hesap_id, h.hareket_turu, h.tutar) for h in hareketler], [(self.kk_hesap_id, "KK ÖDEME", Decimal("3000.00"))])
        with get_session() as s:
            islem = s.scalar(select(CariIslem).where(CariIslem.belge_no == m.belge_no))
            self.assertEqual(islem.islem_turu, "Ödeme")
            ko = s.scalar(select(KrediKartiOdeme).where(KrediKartiOdeme.id == m.satirlar[0].kk_odeme_id))
            self.assertEqual((ko.taksit_sayisi, ko.tutar, ko.durum, len(ko.taksitler)), (3, Decimal("3000.00"), "AÇIK", 3))
            kk_hesap = s.get(FinansHesabi, self.kk_hesap_id)
            self.assertEqual(FinansService.bakiye(kk_hesap), Decimal("3000.00"))
        self.assertEqual(self._bakiye(self.tedarikci_id)["tutar"], Decimal("2000.00"))

    def test_kart_limiti_asilamaz(self):
        with self.assertRaises(ValueError):
            self._kk_odeme(tutar="25000", taksit=1)

    # —— düzenleme / iptal ——
    def test_duzenleme_ikinci_hareket_olusturmaz(self):
        m = self._nakit("300")
        g = FinansService.kasa_makbuz_guncelle(
            m.id,
            {
                "tarih": date.today(),
                "cari_id": self.musteri_id,
                "makbuz_no": m.makbuz_no,
                "satirlar": [
                    {"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": "250"},
                    {"odeme_sekli": "GELEN HAVALE", "hesap": self.mevduat_adi, "tutar": "100"},
                ],
            },
        )
        self.assertEqual((g.id, g.belge_no, g.makbuz_no, g.tutar), (m.id, m.belge_no, "MKB-00001", Decimal("350.00")))
        self.assertEqual(sorted(h.tutar for h in self._hareketler(m.belge_no)), [Decimal("100.00"), Decimal("250.00")])
        with get_session() as s:
            self.assertEqual(s.scalar(select(func.count(CariIslem.id)).where(CariIslem.belge_no == m.belge_no)), 2)
        self.assertEqual(self._bakiye(self.musteri_id)["tutar"], Decimal("650.00"))
        self.assertEqual(FinansService.makbuz_no_oner(), "MKB-00002")

    def test_duzenlemede_numara_degisir_baglantilar_korunur(self):
        m = self._nakit("300")
        g = FinansService.kasa_makbuz_guncelle(
            m.id,
            {
                "tarih": date.today(),
                "cari_id": self.musteri_id,
                "makbuz_no": "ELLE-1",
                "satirlar": [{"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": "300"}],
            },
        )
        self.assertEqual((g.makbuz_no, g.belge_no), ("ELLE-1", m.belge_no))
        self.assertEqual(len(self._hareketler(m.belge_no)), 1)

    def test_iptal_tum_etkileri_geri_alir_baglanti_korunur(self):
        m = self._kk_odeme()
        FinansService.kasa_makbuz_iptal(m.id)
        self.assertEqual(self._hareketler(m.belge_no), [])
        with get_session() as s:
            ko = s.get(KrediKartiOdeme, m.satirlar[0].kk_odeme_id)
            self.assertEqual(ko.durum, "İPTAL")
            self.assertEqual(s.get(KasaMakbuzu, m.id).durum, "IPTAL")
        self.assertEqual(self._bakiye(self.tedarikci_id)["tutar"], Decimal("5000.00"))
        with self.assertRaises(ValueError):
            FinansService.kasa_makbuz_iptal(m.id)

    def test_valoru_aktarilmis_pos_makbuzu_kilitli(self):
        m = FinansService.kasa_tahsilat_makbuzu_kaydet(
            {
                "tarih": date.today(),
                "cari_id": self.musteri_id,
                "satirlar": [
                    {"odeme_sekli": "KREDİ KARTIYLA TAHSİLAT", "finans_hesap_id": self.pos_id, "tutar": "500"}
                ],
            }
        )
        with get_session() as s:
            s.get(PosValorKaydi, m.satirlar[0].pos_valor_id).durum = "AKTARILDI"
        self.assertIsNotNone(FinansService.makbuz_kilit_nedeni(m.id))
        with self.assertRaises(ValueError):
            FinansService.kasa_makbuz_iptal(m.id)
        with self.assertRaises(ValueError):
            FinansService.kasa_makbuz_guncelle(
                m.id,
                {
                    "tarih": date.today(),
                    "cari_id": self.musteri_id,
                    "satirlar": [{"odeme_sekli": "NAKİT / KASA", "finans_hesap_id": self.kasa_id, "tutar": "500"}],
                },
            )
        self.assertEqual(len(self._hareketler(m.belge_no)), 2)

    def test_makbuza_bagli_kart_kaydi_kendi_ekranindan_guncellenemez(self):
        m = self._kk_odeme(taksit=1)
        with self.assertRaises(ValueError):
            FinansService.kredi_karti_odeme(
                1, self.kk_id, self.tedarikci_id, date.today(), "10", belge_no=f"{m.belge_no}-K1"
            )

    # —— liste ——
    def test_liste_cari_adinin_ortasindan_ve_numaradan_arar(self):
        self._nakit("10")
        self.assertEqual(len(FinansService.kasa_makbuz_listele("TAHSILAT", arama="celik")), 1)
        self.assertEqual(len(FinansService.kasa_makbuz_listele("TAHSILAT", arama="mkb-00001")), 1)
        self.assertEqual(FinansService.kasa_makbuz_listele("TAHSILAT", arama="yok-böyle"), [])
        self.assertEqual(len(FinansService.kasa_makbuz_listele("TAHSILAT", durum="IPTAL")), 0)


class MakbuzSemaGecisTest(unittest.TestCase):
    ESKI = """
        CREATE TABLE kasa_makbuzlari (id INTEGER PRIMARY KEY, belge_no VARCHAR(50), makbuz_no VARCHAR(50));
        CREATE TABLE kasa_makbuz_satirlari (id INTEGER PRIMARY KEY, makbuz_id INTEGER, tutar NUMERIC);
    """

    def _engine(self, klasor, satirlar):
        eng = create_engine(f"sqlite:///{(Path(klasor) / 'eski.db').as_posix()}")
        with eng.begin() as c:
            for komut in self.ESKI.strip().split(";"):
                if komut.strip():
                    c.execute(text(komut))
            for i, no in enumerate(satirlar, 1):
                c.execute(text("INSERT INTO kasa_makbuzlari VALUES (:i, :b, :n)"), {"i": i, "b": f"TMK-{i}", "n": no})
        return eng

    def test_sutunlar_ve_benzersiz_indeks_eklenir_veri_degismez(self):
        with tempfile.TemporaryDirectory() as d:
            eng = self._engine(d, ["EVB-1", None, ""])
            kasa_makbuz_schemasini_guncelle(eng)
            kasa_makbuz_schemasini_guncelle(eng)
            with eng.connect() as c:
                sutunlar = {r[1] for r in c.execute(text("PRAGMA table_info(kasa_makbuz_satirlari)"))}
                self.assertTrue({"kart_tipi", "taksit_sayisi", "kredi_karti_id", "pos_valor_id", "kk_odeme_id"} <= sutunlar)
                self.assertIsNotNone(c.execute(text("SELECT 1 FROM sqlite_master WHERE name='ux_kasa_makbuz_no'")).first())
                self.assertEqual(
                    c.execute(text("SELECT makbuz_no FROM kasa_makbuzlari ORDER BY id")).fetchall(),
                    [("EVB-1",), (None,), ("",)],
                )
            eng.dispose()

    def test_mukerrer_eski_numara_varsa_indeks_atlanir(self):
        with tempfile.TemporaryDirectory() as d:
            eng = self._engine(d, ["A-1", "a-1 "])
            kasa_makbuz_schemasini_guncelle(eng)
            with eng.connect() as c:
                self.assertIsNone(c.execute(text("SELECT 1 FROM sqlite_master WHERE name='ux_kasa_makbuz_no'")).first())
                self.assertEqual(c.execute(text("SELECT count(*) FROM kasa_makbuzlari")).scalar(), 2)
            eng.dispose()


if __name__ == "__main__":
    unittest.main()
