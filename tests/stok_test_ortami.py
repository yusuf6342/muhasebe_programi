"""Stok testleri için izole firma veritabanı (her test kendi geçici SQLite dosyası)."""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from database.database import Base, _aktif_engine_bagla, company_db, get_session  # noqa: E402
from database.models.cari import Cari  # noqa: E402
from database.models.donem import Donem  # noqa: E402
from database.models.firma import Firma  # noqa: E402
from database.models.stok import Depo, StokBirim, StokHareketi, StokKarti, StokLotu  # noqa: E402
from database.session_manager import oturum  # noqa: E402


def _pragma(dbapi_connection, _rec):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def _modelleri_yukle() -> None:
    import database.models.alis_faturasi  # noqa: F401
    import database.models.alis_iade_faturasi  # noqa: F401
    import database.models.alis_irsaliyesi  # noqa: F401
    import database.models.alis_masraf  # noqa: F401
    import database.models.alis_siparisi  # noqa: F401
    import database.models.finans  # noqa: F401
    import database.models.genel_muhasebe  # noqa: F401
    import database.models.hizli_satis  # noqa: F401
    import database.models.hizmet  # noqa: F401
    import database.models.hizmet_faturasi  # noqa: F401
    import database.models.masraf_dagitim  # noqa: F401
    import database.models.satis_faturasi  # noqa: F401
    import database.models.satis_iade_faturasi  # noqa: F401
    import database.models.satis_irsaliyesi  # noqa: F401
    import database.models.satis_siparisi  # noqa: F401
    import database.models.stok_sayim  # noqa: F401
    try:
        import database.models.stok_uyari  # noqa: F401
    except ImportError:
        pass


class StokOrtami:
    """Temiz firma DB: ANA DEPO + DEPO 2, U001 (Adet, Koli=12), tedarikçi T001, müşteri M001."""

    def __init__(self, ad: str = "stok"):
        self._tmp = tempfile.TemporaryDirectory(prefix=f"stok_{ad}_")
        self.db_path = Path(self._tmp.name) / "firma.db"
        self.engine = create_engine(
            f"sqlite:///{self.db_path.as_posix()}", connect_args={"check_same_thread": False}
        )
        event.listen(self.engine, "connect", _pragma)
        _modelleri_yukle()
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, expire_on_commit=False)
        with Session() as s:
            firma = Firma(firma_kodu="STK", unvan="Stok Test", aktif=True)
            s.add(firma)
            s.flush()
            s.add(Donem(firma_id=firma.id, donem_adi="2026", baslangic_tarihi=date(2026, 1, 1),
                        bitis_tarihi=date(2026, 12, 31), aktif=True, kapali=False, varsayilan=True))
            s.add(Depo(ad="ANA DEPO", aktif=True, varsayilan=True))
            s.add(Depo(ad="DEPO 2", aktif=True))
            stok = StokKarti(stok_kodu="U001", stok_adi="Test Ürün", birim="Adet", aktif=True,
                             is_deleted=False, minimum_stok=Decimal("0"))
            s.add(stok)
            s.flush()
            s.add(StokBirim(stok_id=stok.id, birim_adi="Koli", carpan=Decimal("12")))
            s.add(Cari(cari_kodu="T001", unvan="Test Tedarikçi", cari_turu="Tedarikçi", aktif=True))
            s.add(Cari(cari_kodu="M001", unvan="Test Müşteri", cari_turu="Müşteri", aktif=True))
            s.commit()

        _aktif_engine_bagla(self.engine)
        company_db._engine = self.engine
        company_db._session_factory = Session
        company_db._company_id = 97
        company_db._db_path = self.db_path
        oturum.clear()
        oturum.set_user(user_id=1, kullanici_adi="admin", ad_soyad="Test Admin",
                        role_kod="YONETICI", role_ad="Yönetici", permissions=set())
        oturum.set_company(company_id=97, firma_kodu="STK", firma_unvan="Stok Test",
                           firma_uid="stk-test", db_path=str(self.db_path))
        with get_session() as s:
            d = s.scalar(select(Donem).limit(1))
            oturum.set_period(d.id, d.donem_adi)
            self.ted_id = s.scalar(select(Cari.id).where(Cari.cari_kodu == "T001"))
            self.mus_id = s.scalar(select(Cari.id).where(Cari.cari_kodu == "M001"))
        self._yamalar = [
            patch("database.muhasebe_entegrasyon.muhasebe_hook", lambda *_a, **_k: None),
            patch("database.satis_personeli.secimi_dogrula", return_value=(1, "Test Admin")),
        ]
        for p in self._yamalar:
            p.start()

    def kapat(self) -> None:
        for p in reversed(self._yamalar):
            p.stop()
        try:
            company_db.close()
        except Exception:  # noqa: BLE001
            pass
        company_db._engine = None
        company_db._session_factory = None
        oturum.clear()
        try:
            self.engine.dispose()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._tmp.cleanup()
        except Exception:  # noqa: BLE001
            pass

    # --- belge yardımcıları ---
    def urun_ekle(self, kod: str, ad: str, birim: str = "Adet", **alanlar) -> int:
        with get_session() as s:
            alanlar.setdefault("minimum_stok", Decimal("0"))
            stok = StokKarti(stok_kodu=kod, stok_adi=ad, birim=birim, aktif=True, is_deleted=False, **alanlar)
            s.add(stok)
            s.flush()
            return int(stok.id)

    def alis(self, miktar, fiyat, tarih, lot="", birim="Adet", depo="ANA DEPO", fatura_id=None, rv=None,
             kod="U001", aciklama=None):
        from database.alis_faturasi_service import AlisFaturasiService

        veriler = {"fatura_tarihi": tarih, "vade_tarihi": tarih, "cari_id": self.ted_id,
                   "depo": depo, "odeme_tutari": Decimal("0"), "aciklama": aciklama}
        if rv is not None:
            veriler["row_version"] = rv
        return AlisFaturasiService.kaydet(
            veriler,
            [{"urun_kodu": kod, "urun_adi": "Test Ürün", "miktar": Decimal(str(miktar)),
              "birim": birim, "birim_fiyat": Decimal(str(fiyat)), "iskonto_orani": Decimal("0"),
              "kdv_orani": Decimal("20"), "lot_no": lot}],
            fatura_id=fatura_id,
        )

    def satis(self, miktar, fiyat, tarih, birim="Adet", onayla=True, depo="ANA DEPO", kod="U001"):
        from database.satis_faturasi_service import SatisFaturasiService

        f = SatisFaturasiService.kaydet(
            {"fatura_tarihi": tarih, "vade_tarihi": tarih, "cari_id": self.mus_id,
             "depo": depo, "odeme_tutari": Decimal("0"), "sales_person_id": 1},
            [{"urun_kodu": kod, "urun_adi": "Test Ürün", "miktar": Decimal(str(miktar)),
              "birim": birim, "birim_fiyat": Decimal(str(fiyat)), "iskonto_orani": Decimal("0"),
              "kdv_orani": Decimal("20")}],
        )
        if onayla:
            SatisFaturasiService.onayla(f.id)
        return f

    def lot_toplam(self, depo=None, kod="U001") -> Decimal:
        with get_session() as s:
            q = select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).join(
                StokKarti, StokKarti.id == StokLotu.stok_id
            ).where(StokKarti.stok_kodu == kod)
            if depo:
                q = q.join(Depo, Depo.id == StokLotu.depo_id).where(Depo.ad == depo)
            return Decimal(str(s.scalar(q) or 0))

    def lot_deger(self, depo=None, kod="U001") -> Decimal:
        with get_session() as s:
            q = select(StokLotu).join(StokKarti, StokKarti.id == StokLotu.stok_id).where(StokKarti.stok_kodu == kod)
            if depo:
                q = q.join(Depo, Depo.id == StokLotu.depo_id).where(Depo.ad == depo)
            return sum((Decimal(str(l.kalan_miktar)) * Decimal(str(l.birim_maliyet))
                        for l in s.scalars(q).all()), Decimal("0"))

    def hareket_bakiye(self, depo=None, kod="U001") -> Decimal:
        from database.stok_service import CIKIS_HAREKETLERI, GIRIS_HAREKETLERI

        with get_session() as s:
            q = select(StokHareketi).join(StokKarti, StokKarti.id == StokHareketi.stok_id).where(
                StokKarti.stok_kodu == kod
            )
            if depo:
                q = q.join(Depo, Depo.id == StokHareketi.depo_id).where(Depo.ad == depo)
            top = Decimal("0")
            for h in s.scalars(q).all():
                if h.hareket_turu in GIRIS_HAREKETLERI:
                    top += Decimal(str(h.miktar))
                elif h.hareket_turu in CIKIS_HAREKETLERI:
                    top -= Decimal(str(h.miktar))
            return top

    def hareket_sayisi(self, tur=None) -> int:
        with get_session() as s:
            q = select(func.count(StokHareketi.id))
            if tur:
                q = q.where(StokHareketi.hareket_turu == tur)
            return int(s.scalar(q) or 0)
