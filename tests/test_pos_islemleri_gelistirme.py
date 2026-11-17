"""POS İşlemleri: komisyon/valör override, bankaya aktarım, durum, renk sabiti — izole DB."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.database import (
    Base,
    _aktif_engine_bagla,
    company_db,
    finans_hesap_schemasini_guncelle,
    get_session,
)
from database.finans_service import FinansService
from database.models.cari import Cari
from database.models.donem import Donem
from database.models.finans import BankaKarti, FinansHesabi, FinansHareketi, PosValorKaydi
from database.models.firma import Firma
from database.models.sube import Sube
from database.session_manager import oturum


def _pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


class PosIslemleriGelistirmeTest(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "pos_gel.db"
        eng = create_engine(
            f"sqlite:///{self.db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        event.listen(eng, "connect", _pragma)
        import database.models as modeller

        for bilgi in pkgutil.iter_modules(modeller.__path__):
            importlib.import_module(f"database.models.{bilgi.name}")
        Base.metadata.create_all(eng)
        finans_hesap_schemasini_guncelle(eng)
        Session = sessionmaker(bind=eng, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="POSG", unvan="POS Gel", aktif=True)
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
            musteri = Cari(cari_kodu="M001", unvan="POS Müşteri", cari_turu="Müşteri")
            s.add(musteri)
            banka = BankaKarti(
                banka_adi="TEST POS BANK",
                kk_komisyon_orani=Decimal("2"),
                pos_valor_gun=1,
                pos_hedef_hesap_turu="MEVDUAT",
                pos_valor_is_gunu=False,
                pos_otomatik_mahsup=False,
            )
            s.add(banka)
            s.flush()
            for alt in ("MEVDUAT", "KMH", "POS"):
                s.add(
                    FinansHesabi(
                        hesap_adi=f"TEST POS BANK — {alt}",
                        hesap_turu="BANKA",
                        banka_karti_id=banka.id,
                        alt_hesap_turu=alt,
                        acilis_bakiyesi=Decimal("0"),
                    )
                )
            s.commit()
            self.banka_id = banka.id
            self.musteri_id = musteri.id
        _aktif_engine_bagla(eng)
        company_db._engine = eng
        company_db._session_factory = Session
        company_db._company_id = 1
        company_db._db_path = self.db_path
        oturum.clear()
        oturum.set_user(
            user_id=1,
            kullanici_adi="t",
            ad_soyad="t",
            role_kod="YONETICI",
            role_ad="Y",
            permissions=set(),
        )
        oturum.set_company(
            company_id=1,
            firma_kodu="POSG",
            firma_unvan="POS Gel",
            firma_uid="posg",
            db_path=str(self.db_path),
        )
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            oturum.set_period(d.id, d.donem_adi)
        self._audit = patch("database.user_audit.audit_document", return_value=None)
        self._audit.start()
        self._muh = patch("database.muhasebe_entegrasyon.muhasebe_hook", return_value=None)
        self._muh.start()

    def tearDown(self):
        self._muh.stop()
        self._audit.stop()
        try:
            company_db.close()
        except Exception:
            pass
        self._tmpdir.cleanup()

    def test_karttan_komisyon_valor_saklanir_kart_degisse_eski_degismez(self):
        r = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 5),
            "1000",
            cari_id=self.musteri_id,
        )
        self.assertEqual(r["komisyon_orani"], Decimal("2"))
        self.assertEqual(r["komisyon"], Decimal("20.00"))
        self.assertEqual(r["net"], Decimal("980.00"))
        self.assertEqual(r["valor_gun"], 1)
        self.assertEqual(r["valor_tarihi"], date(2026, 11, 6))
        with get_session() as s:
            kart = s.get(BankaKarti, self.banka_id)
            kart.kk_komisyon_orani = Decimal("5")
            kart.pos_valor_gun = 10
            s.commit()
        getir = FinansService.pos_tahsilat_getir(r["belge_no"])
        self.assertEqual(getir["komisyon_orani"], Decimal("2"))
        self.assertEqual(getir["valor_gun"], 1)
        self.assertEqual(getir["valor_tarihi"], date(2026, 11, 6))

    def test_elle_komisyon_tutar_ve_kesinti_override(self):
        r = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 5),
            "1000",
            cari_id=self.musteri_id,
            komisyon_tutari="15.50",
            diger_kesinti="4.50",
            valor_gun=3,
            valor_tarihi=date(2026, 11, 20),
        )
        self.assertEqual(r["komisyon"], Decimal("15.50"))
        self.assertEqual(r["diger_kesinti"], Decimal("4.50"))
        self.assertEqual(r["net"], Decimal("980.00"))
        self.assertEqual(r["valor_gun"], 3)
        self.assertEqual(r["valor_tarihi"], date(2026, 11, 20))
        # efektif oran = 15.50/1000*100
        self.assertEqual(r["komisyon_orani"], Decimal("1.5500"))

    def test_valor_geldi_ama_aktarilmis_sayilmaz(self):
        r = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 10, 1),
            "500",
            cari_id=self.musteri_id,
            komisyon_orani="0",
            valor_tarihi=date(2026, 10, 2),
        )
        with get_session() as s:
            pv = s.get(PosValorKaydi, r["kayit_id"])
            bil = FinansService.pos_aktarim_durum_bilgisi(pv, bugun=date(2026, 11, 10))
        self.assertEqual(bil["durum_kod"], "BEKLIYOR")
        self.assertEqual(bil["ek_isaret"], "Gecikti")
        self.assertIsNone(
            FinansService.pos_tahsilat_getir(r["belge_no"]).get("gercek_yatis_tarihi")
        )

    def test_tekli_kismi_ve_mukerrer_aktarim(self):
        r = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 5),
            "1000",
            cari_id=self.musteri_id,
            komisyon_orani="0",
        )
        kid = r["kayit_id"]
        # Kısmi
        s1 = FinansService.pos_bankaya_aktar(
            [kid], tutarlar={kid: "400"}, aktarim_tarihi=date(2026, 11, 6)
        )
        self.assertEqual(s1[0]["durum"], "KISMEN")
        self.assertEqual(s1[0]["kalan"], Decimal("600.00"))
        belge = s1[0]["aktarim_belge_no"]
        # Tamamla
        s2 = FinansService.pos_bankaya_aktar(
            [kid], tutarlar={kid: "600"}, aktarim_tarihi=date(2026, 11, 7)
        )
        self.assertEqual(s2[0]["durum"], "AKTARILDI")
        self.assertEqual(s2[0]["kalan"], Decimal("0"))
        # Mükerrer
        with self.assertRaises(ValueError):
            FinansService.pos_bankaya_aktar([kid], aktarim_tarihi=date(2026, 11, 8))
        with get_session() as s:
            pv = s.get(PosValorKaydi, kid)
            self.assertEqual(pv.gercek_yatis_tutari, Decimal("1000.00"))
            # Cari tahsilat brüt bir kez (POS TAHSİLAT hareketi)
            tahsilatlar = list(
                s.scalars(
                    select(FinansHareketi).where(
                        FinansHareketi.belge_no == r["belge_no"],
                        FinansHareketi.hareket_turu == "POS TAHSİLAT",
                    )
                ).all()
            )
            self.assertEqual(len(tahsilatlar), 1)
            pva = list(
                s.scalars(
                    select(FinansHareketi).where(FinansHareketi.belge_no == belge)
                ).all()
            )
            self.assertEqual(len(pva), 2)  # POS çıkış + hedef giriş

    def test_toplu_aktarim_ayni_pva_belgesi(self):
        a = FinansService.pos_tahsilat(
            self.banka_id, date(2026, 11, 5), "100", cari_id=self.musteri_id, komisyon_orani="0"
        )
        b = FinansService.pos_tahsilat(
            self.banka_id, date(2026, 11, 5), "200", cari_id=self.musteri_id, komisyon_orani="0"
        )
        son = FinansService.pos_bankaya_aktar(
            [a["kayit_id"], b["kayit_id"]], aktarim_tarihi=date(2026, 11, 6)
        )
        self.assertEqual(len(son), 2)
        self.assertEqual(son[0]["aktarim_belge_no"], son[1]["aktarim_belge_no"])
        liste = FinansService.pos_tahsilat_listele(limit=50, sadece_kk=False)
        ids = {x["id"] for x in liste}
        self.assertIn(a["kayit_id"], ids)
        self.assertIn(b["kayit_id"], ids)
        for x in liste:
            if x["id"] in (a["kayit_id"], b["kayit_id"]):
                self.assertEqual(x["durum_kod"], "AKTARILDI")

    def test_fis_duzenle_yeniden_ac(self):
        r = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 5),
            "800",
            cari_id=self.musteri_id,
            komisyon_orani="1",
        )
        r2 = FinansService.pos_tahsilat(
            self.banka_id,
            date(2026, 11, 5),
            "900",
            cari_id=self.musteri_id,
            komisyon_orani="3",
            diger_kesinti="10",
            valor_gun=5,
            belge_no=r["belge_no"],
        )
        self.assertEqual(r2["belge_no"], r["belge_no"])
        self.assertEqual(r2["brut"], Decimal("900.00"))
        self.assertEqual(r2["komisyon"], Decimal("27.00"))
        self.assertEqual(r2["diger_kesinti"], Decimal("10"))
        self.assertEqual(r2["net"], Decimal("863.00"))
        g = FinansService.pos_tahsilat_getir(r["belge_no"])
        self.assertEqual(g["tutar"], Decimal("900.00"))
        self.assertEqual(g["komisyon_orani"], Decimal("3"))

    def test_liste_ozet_toplamlari(self):
        FinansService.pos_tahsilat(
            self.banka_id, date(2026, 11, 5), "1000", cari_id=self.musteri_id, komisyon_orani="2"
        )
        FinansService.pos_tahsilat(
            self.banka_id, date(2026, 11, 5), "500", cari_id=self.musteri_id, komisyon_orani="0"
        )
        liste = FinansService.pos_tahsilat_listele(limit=50, sadece_kk=False)
        brut = sum((x["brut"] for x in liste), Decimal("0"))
        kom = sum((x["komisyon"] for x in liste), Decimal("0"))
        net = sum((x["net"] for x in liste), Decimal("0"))
        self.assertEqual(brut, Decimal("1500.00"))
        self.assertEqual(kom, Decimal("20.00"))
        self.assertEqual(net, Decimal("1480.00"))

    def test_pos_renk_sabit(self):
        from pos_renk_prefs import POS_RENK_PALETI, pos_rengi

        # Geçici dosya için firma kodu set
        with patch("pos_renk_prefs._dosya") as dosya_mock:
            p = Path(self._tmpdir.name) / "renk.json"
            dosya_mock.return_value = p
            r1 = pos_rengi(101)
            r2 = pos_rengi(202)
            r1b = pos_rengi(101)
            self.assertEqual(r1["zemin"], POS_RENK_PALETI[0]["zemin"])
            self.assertEqual(r2["zemin"], POS_RENK_PALETI[1]["zemin"])
            self.assertEqual(r1b["zemin"], r1["zemin"])
            self.assertEqual(r1b["serit"], r1["serit"])


if __name__ == "__main__":
    unittest.main()
