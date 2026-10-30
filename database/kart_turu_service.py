"""Kart ana/alt türü ve cari sektör grubu tanımları + geçiş."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select

from database.access import yazma_zorunlu
from database.database import get_session
from database.models.kart_turu import KAPSAM_CARI, KAPSAM_STOK, KartAltTuru, KartAnaTuru

# Eski stok kart_turu → yeni ana tür kodu
_STOK_ESKI_ESLEME = {
    "ticari mal": "TICARI_MAL",
    "hammadde": "HAM_MADDE",
    "ham madde": "HAM_MADDE",
    "yarı mamul": "YARI_MAMUL",
    "yari mamul": "YARI_MAMUL",
    "mamul": "MAMUL",
    "sarf malzeme": "MALZEME",
    "malzeme": "MALZEME",
    "paket": "PAKET_STOK",
    "paket stok": "PAKET_STOK",
    "hizmet": "HIZMET",
    "demirbaş": "DEMIRBAS",
    "demirbas": "DEMIRBAS",
}

_STOK_ANA_SEED = (
    ("MALZEME", "Malzeme", 10),
    ("HAM_MADDE", "Ham Madde", 20),
    ("YARI_MAMUL", "Yarı Mamul", 30),
    ("MAMUL", "Mamul", 40),
    ("TICARI_MAL", "Ticari Mal", 50),
    ("PAKET_STOK", "Paket Stok", 60),
    ("HIZMET", "Hizmet", 70),
    ("DEMIRBAS", "Demirbaş", 80),
)

_STOK_ALT_SEED = {
    "HAM_MADDE": (("METAL_HM", "Metal Ham Madde"), ("AHSP_HM", "Ahşap Ham Madde")),
    "PAKET_STOK": (("SET", "Set"), ("KARMA_PAKET", "Karma Paket")),
}

_CARI_ANA_SEED = (
    ("MUSTERI", "Müşteri", "MUSTERI", 10),
    ("TEDARIKCI", "Tedarikçi", "TEDARIKCI", 20),
    ("PERSONEL", "Personel", "PERSONEL", 30),
    ("MUSTERI_TEDARIKCI", "Müşteri/Tedarikçi", "MUSTERI_TEDARIKCI", 40),
)

_CARI_ALT_SEED = {
    "MUSTERI": (
        ("PERAKENDE_MUSTERI", "Perakende Müşteri"),
        ("FABRIKA", "Fabrika"),
        ("TICARETHANE", "Ticarethane"),
    ),
    "TEDARIKCI": (
        ("URETICI", "Üretici"),
        ("ARA_TOPTANCI", "Ara Toptancı"),
        ("HIZMET_TEDARIKCISI", "Hizmet Tedarikçisi"),
    ),
}

_SEKTOR_SEED = (
    ("MOBILYACI", "Mobilyacı"),
    ("SU_TESISATCISI", "Su Tesisatçısı"),
    ("INSAATCI", "İnşaatçı"),
    ("PERAKENDE_NALBUR", "Perakende Nalbur"),
)

# Eski müşteri grubu adı → sektör adı (veya None = sektör dışı / alt türe taşınacak)
_ESKI_GRUP_SEKTOR = {
    "perakende müşteri": None,  # alt tür
    "perakende musteri": None,
    "mobilya atölyeleri": "Mobilyacı",
    "mobilya atolyeleri": "Mobilyacı",
    "üretici fabrikalar": "Mobilyacı",
    "uretici fabrikalar": "Mobilyacı",
    "nalbur": "Perakende Nalbur",
    "tesisatçılar": "Su Tesisatçısı",
    "tesisatcilar": "Su Tesisatçısı",
}


def _norm(metin: str | None) -> str:
    s = " ".join((metin or "").strip().split())
    s = unicodedata.normalize("NFKC", s)
    return s.casefold()


def _kod_uret(ad: str) -> str:
    ham = unicodedata.normalize("NFKD", ad or "")
    ham = "".join(c for c in ham if not unicodedata.combining(c))
    ham = re.sub(r"[^A-Za-z0-9]+", "_", ham.upper()).strip("_")
    return (ham or "TUR")[:40]


class KartTuruService:
    _schema_hazir: bool = False

    @staticmethod
    def ensure_schema() -> None:
        """Eksik tablo/kolon varsa bir kez kur (kart açılışında güvenli)."""
        if KartTuruService._schema_hazir:
            return
        try:
            KartTuruService.schema_ve_seed()
            KartTuruService._schema_hazir = True
        except Exception:
            # Sonraki çağrıda tekrar denensin
            KartTuruService._schema_hazir = False
            raise

    @staticmethod
    def schema_ve_seed() -> dict[str, Any]:
        """Tabloları oluştur, kolonları ekle, başlangıç tanımlarını mükerrersiz yaz."""
        from sqlalchemy import inspect, text

        from database.database import engine
        from database.models.cari import MusteriGrubu  # noqa: F401
        from database.models.stok import StokKarti  # noqa: F401

        # Modelleri metadata'ya kaydet
        from database.models import kart_turu as _kt  # noqa: F401

        if engine is None:
            raise RuntimeError("Aktif firma veritabanı yok; kart türü şeması kurulamadı.")

        insp = inspect(engine)
        if not insp.has_table("kart_ana_turleri"):
            KartAnaTuru.__table__.create(bind=engine, checkfirst=True)
        if not insp.has_table("kart_alt_turleri"):
            KartAltTuru.__table__.create(bind=engine, checkfirst=True)

        def _kolon_ekle(tablo: str, kolonlar: dict[str, str]) -> None:
            if not insp.has_table(tablo):
                return
            mevcut = {s["name"] for s in inspect(engine).get_columns(tablo)}
            with engine.begin() as conn:
                for ad, tip in kolonlar.items():
                    if ad not in mevcut:
                        conn.execute(text(f'ALTER TABLE "{tablo}" ADD COLUMN "{ad}" {tip}'))

        _kolon_ekle(
            "stok_kartlari",
            {
                "ana_kart_turu_id": "INTEGER",
                "alt_kart_turu_id": "INTEGER",
            },
        )
        _kolon_ekle(
            "cari_kartlar",
            {
                "ana_kart_turu_id": "INTEGER",
                "musteri_alt_tur_id": "INTEGER",
                "tedarikci_alt_tur_id": "INTEGER",
            },
        )
        _kolon_ekle(
            "musteri_gruplari",
            {
                "kod": "VARCHAR(40)",
                "aciklama": "VARCHAR(500)",
                "aktif": "BOOLEAN DEFAULT 1 NOT NULL",
                "sira": "INTEGER DEFAULT 100 NOT NULL",
                "sektor_listesinde": "BOOLEAN DEFAULT 1 NOT NULL",
                "sistem": "BOOLEAN DEFAULT 0 NOT NULL",
            },
        )

        seed = KartTuruService.baslangic_tanimlarini_yaz()
        try:
            gecis = KartTuruService.gecis_calistir()
        except Exception as exc:
            import logging

            logging.getLogger(__name__).exception("kart_turu gecis")
            gecis = {"hata": str(exc), "catisma": []}
        KartTuruService._schema_hazir = True
        return {"seed": seed, "gecis": gecis}

    @staticmethod
    def baslangic_tanimlarini_yaz() -> dict[str, int]:
        eklenen = {"stok_ana": 0, "stok_alt": 0, "cari_ana": 0, "cari_alt": 0, "sektor": 0}
        with get_session() as session:
            for kod, ad, sira in _STOK_ANA_SEED:
                if KartTuruService._ana_bul(session, KAPSAM_STOK, kod=kod, ad=ad):
                    continue
                session.add(
                    KartAnaTuru(
                        kapsam=KAPSAM_STOK,
                        kod=kod,
                        ad=ad,
                        sira=sira,
                        sistem=True,
                        aktif=True,
                    )
                )
                eklenen["stok_ana"] += 1
            session.flush()

            for ana_kod, altlar in _STOK_ALT_SEED.items():
                ana = KartTuruService._ana_bul(session, KAPSAM_STOK, kod=ana_kod)
                if not ana:
                    continue
                for akod, aad in altlar:
                    if KartTuruService._alt_bul(session, ana.id, kod=akod, ad=aad):
                        continue
                    session.add(
                        KartAltTuru(
                            ana_tur_id=ana.id,
                            kod=akod,
                            ad=aad,
                            sistem=True,
                            aktif=True,
                        )
                    )
                    eklenen["stok_alt"] += 1

            for kod, ad, rol, sira in _CARI_ANA_SEED:
                if KartTuruService._ana_bul(session, KAPSAM_CARI, kod=kod, ad=ad):
                    continue
                session.add(
                    KartAnaTuru(
                        kapsam=KAPSAM_CARI,
                        kod=kod,
                        ad=ad,
                        muhasebe_rol=rol,
                        sira=sira,
                        sistem=True,
                        aktif=True,
                    )
                )
                eklenen["cari_ana"] += 1
            session.flush()

            for ana_kod, altlar in _CARI_ALT_SEED.items():
                ana = KartTuruService._ana_bul(session, KAPSAM_CARI, kod=ana_kod)
                if not ana:
                    continue
                for akod, aad in altlar:
                    if KartTuruService._alt_bul(session, ana.id, kod=akod, ad=aad):
                        continue
                    session.add(
                        KartAltTuru(
                            ana_tur_id=ana.id,
                            kod=akod,
                            ad=aad,
                            sistem=True,
                            aktif=True,
                        )
                    )
                    eklenen["cari_alt"] += 1

            from database.models.cari import MusteriGrubu

            for kod, ad in _SEKTOR_SEED:
                mevcut = session.scalar(
                    select(MusteriGrubu).where(
                        or_(
                            func.lower(MusteriGrubu.ad) == ad.casefold(),
                            MusteriGrubu.kod == kod,
                        )
                    )
                )
                if mevcut:
                    if getattr(mevcut, "kod", None) is None:
                        mevcut.kod = kod
                    if hasattr(mevcut, "sektor_listesinde"):
                        mevcut.sektor_listesinde = True
                    continue
                # Benzer eski adları yeniden adlandır
                eski = None
                for eski_ad, hedef in _ESKI_GRUP_SEKTOR.items():
                    if hedef and _norm(hedef) == _norm(ad):
                        for g in session.scalars(select(MusteriGrubu)).all():
                            if _norm(g.ad) == eski_ad:
                                eski = g
                                break
                        if eski:
                            break
                if eski:
                    eski.ad = ad
                    eski.kod = kod
                    eski.sektor_listesinde = True
                    eski.aktif = True
                    continue
                session.add(
                    MusteriGrubu(
                        ad=ad,
                        kod=kod,
                        aktif=True,
                        sektor_listesinde=True,
                        sistem=True,
                        sira=100,
                    )
                )
                eklenen["sektor"] += 1
            session.flush()
        return eklenen

    @staticmethod
    def _ana_bul(session, kapsam: str, *, kod: str | None = None, ad: str | None = None):
        q = select(KartAnaTuru).where(KartAnaTuru.kapsam == kapsam)
        kayitlar = list(session.scalars(q).all())
        if kod:
            for k in kayitlar:
                if (k.kod or "").casefold() == kod.casefold():
                    return k
        if ad:
            n = _norm(ad)
            for k in kayitlar:
                if _norm(k.ad) == n:
                    return k
        return None

    @staticmethod
    def _alt_bul(session, ana_tur_id: int, *, kod: str | None = None, ad: str | None = None):
        kayitlar = list(
            session.scalars(select(KartAltTuru).where(KartAltTuru.ana_tur_id == ana_tur_id)).all()
        )
        if kod:
            for k in kayitlar:
                if (k.kod or "").casefold() == kod.casefold():
                    return k
        if ad:
            n = _norm(ad)
            for k in kayitlar:
                if _norm(k.ad) == n:
                    return k
        return None

    @staticmethod
    def ana_turleri_listele(kapsam: str, *, sadece_aktif: bool = True) -> list[KartAnaTuru]:
        KartTuruService.ensure_schema()
        with get_session() as session:
            q = select(KartAnaTuru).where(KartAnaTuru.kapsam == kapsam)
            if sadece_aktif:
                q = q.where(KartAnaTuru.aktif.is_(True))
            q = q.order_by(KartAnaTuru.sira, KartAnaTuru.ad)
            kayitlar = list(session.scalars(q).all())
            for k in kayitlar:
                session.expunge(k)
            return kayitlar

    @staticmethod
    def alt_turleri_listele(
        ana_tur_id: int | None, *, sadece_aktif: bool = True
    ) -> list[KartAltTuru]:
        if not ana_tur_id:
            return []
        KartTuruService.ensure_schema()
        with get_session() as session:
            q = select(KartAltTuru).where(KartAltTuru.ana_tur_id == int(ana_tur_id))
            if sadece_aktif:
                q = q.where(KartAltTuru.aktif.is_(True))
            q = q.order_by(KartAltTuru.sira, KartAltTuru.ad)
            kayitlar = list(session.scalars(q).all())
            for k in kayitlar:
                session.expunge(k)
            return kayitlar

    @staticmethod
    def ana_getir(ana_id: int) -> KartAnaTuru | None:
        with get_session() as session:
            k = session.get(KartAnaTuru, int(ana_id))
            if k:
                session.expunge(k)
            return k

    @staticmethod
    def alt_getir(alt_id: int) -> KartAltTuru | None:
        with get_session() as session:
            k = session.get(KartAltTuru, int(alt_id))
            if k:
                session.expunge(k)
            return k

    @staticmethod
    def ana_kaydet(veri: dict[str, Any]) -> KartAnaTuru:
        yazma_zorunlu("sistem_ayarlari", "stok_duzenleme", "cari_duzenleme")
        kapsam = (veri.get("kapsam") or "").strip().upper()
        if kapsam not in {KAPSAM_STOK, KAPSAM_CARI}:
            raise ValueError("Kapsam STOK veya CARI olmalı.")
        ad = " ".join((veri.get("ad") or "").split())
        if not ad:
            raise ValueError("Ad zorunlu.")
        kod = (veri.get("kod") or "").strip() or _kod_uret(ad)
        kayit_id = veri.get("id")
        with get_session() as session:
            for dig in session.scalars(
                select(KartAnaTuru).where(KartAnaTuru.kapsam == kapsam)
            ).all():
                if kayit_id and dig.id == int(kayit_id):
                    continue
                if _norm(dig.ad) == _norm(ad) or (dig.kod or "").casefold() == kod.casefold():
                    raise ValueError("Aynı kapsamda mükerrer ana tür kodu/adı.")
            if kayit_id:
                kayit = session.get(KartAnaTuru, int(kayit_id))
                if not kayit:
                    raise ValueError("Ana tür bulunamadı.")
            else:
                kayit = KartAnaTuru(kapsam=kapsam, sistem=False)
                session.add(kayit)
            kayit.kod = kod[:40]
            kayit.ad = ad
            kayit.aciklama = (veri.get("aciklama") or "").strip() or None
            kayit.aktif = bool(veri.get("aktif", True))
            kayit.sira = int(veri.get("sira") or 100)
            if kapsam == KAPSAM_CARI:
                rol = (veri.get("muhasebe_rol") or "").strip().upper() or None
                if not rol:
                    # Metinden tahmin etme — açık bağla
                    if _norm(ad) in {_norm("Müşteri")}:
                        rol = "MUSTERI"
                    elif _norm(ad) in {_norm("Tedarikçi")}:
                        rol = "TEDARIKCI"
                    elif _norm(ad) in {_norm("Personel")}:
                        rol = "PERSONEL"
                    elif "müşteri" in _norm(ad) and "tedarik" in _norm(ad):
                        rol = "MUSTERI_TEDARIKCI"
                    else:
                        raise ValueError(
                            "Yeni cari ana tür için muhasebe rolü seçin: "
                            "MUSTERI, TEDARIKCI, PERSONEL veya MUSTERI_TEDARIKCI."
                        )
                if rol not in {"MUSTERI", "TEDARIKCI", "PERSONEL", "MUSTERI_TEDARIKCI"}:
                    raise ValueError("Geçersiz muhasebe rolü.")
                kayit.muhasebe_rol = rol
            kayit.guncelleme_tarihi = datetime.now()
            session.flush()
            session.refresh(kayit)
            session.expunge(kayit)
            return kayit

    @staticmethod
    def alt_kaydet(veri: dict[str, Any]) -> KartAltTuru:
        yazma_zorunlu("sistem_ayarlari", "stok_duzenleme", "cari_duzenleme")
        ana_id = veri.get("ana_tur_id")
        if not ana_id:
            raise ValueError("Bağlı ana kart türü zorunlu.")
        ad = " ".join((veri.get("ad") or "").split())
        if not ad:
            raise ValueError("Ad zorunlu.")
        kod = (veri.get("kod") or "").strip() or _kod_uret(ad)
        kayit_id = veri.get("id")
        with get_session() as session:
            ana = session.get(KartAnaTuru, int(ana_id))
            if not ana:
                raise ValueError("Ana tür bulunamadı.")
            for dig in session.scalars(
                select(KartAltTuru).where(KartAltTuru.ana_tur_id == ana.id)
            ).all():
                if kayit_id and dig.id == int(kayit_id):
                    continue
                if _norm(dig.ad) == _norm(ad) or (dig.kod or "").casefold() == kod.casefold():
                    raise ValueError("Aynı ana tür altında mükerrer alt tür.")
            if kayit_id:
                kayit = session.get(KartAltTuru, int(kayit_id))
                if not kayit:
                    raise ValueError("Alt tür bulunamadı.")
                # Ana tür değişimi bağlı kartları uyumsuz bırakmasın
                if int(kayit.ana_tur_id) != int(ana.id):
                    etkilenen = KartTuruService._alt_bagli_sayisi(session, kayit.id)
                    if etkilenen:
                        raise ValueError(
                            f"Bu alt tür {etkilenen} karta bağlı; ana türü değiştirilemez. "
                            "Önce kartları güncelleyin veya yeni alt tür açın."
                        )
                    kayit.ana_tur_id = ana.id
            else:
                kayit = KartAltTuru(ana_tur_id=ana.id, sistem=False)
                session.add(kayit)
            kayit.kod = kod[:40]
            kayit.ad = ad
            kayit.aciklama = (veri.get("aciklama") or "").strip() or None
            kayit.aktif = bool(veri.get("aktif", True))
            kayit.sira = int(veri.get("sira") or 100)
            kayit.guncelleme_tarihi = datetime.now()
            session.flush()
            session.refresh(kayit)
            session.expunge(kayit)
            return kayit

    @staticmethod
    def _alt_bagli_sayisi(session, alt_id: int) -> int:
        from database.models.cari import Cari
        from database.models.stok import StokKarti

        s = session.scalar(
            select(func.count()).select_from(StokKarti).where(StokKarti.alt_kart_turu_id == alt_id)
        ) or 0
        c = session.scalar(
            select(func.count())
            .select_from(Cari)
            .where(
                or_(
                    Cari.musteri_alt_tur_id == alt_id,
                    Cari.tedarikci_alt_tur_id == alt_id,
                )
            )
        ) or 0
        return int(s) + int(c)

    @staticmethod
    def bagli_kart_sayisi(ana_id: int | None = None, alt_id: int | None = None) -> int:
        with get_session() as session:
            from database.models.cari import Cari
            from database.models.stok import StokKarti

            n = 0
            if alt_id:
                return KartTuruService._alt_bagli_sayisi(session, int(alt_id))
            if ana_id:
                n += session.scalar(
                    select(func.count())
                    .select_from(StokKarti)
                    .where(StokKarti.ana_kart_turu_id == int(ana_id))
                ) or 0
                n += session.scalar(
                    select(func.count())
                    .select_from(Cari)
                    .where(Cari.ana_kart_turu_id == int(ana_id))
                ) or 0
            return int(n)

    @staticmethod
    def pasife_al_ana(ana_id: int) -> None:
        yazma_zorunlu("sistem_ayarlari", "stok_duzenleme", "cari_duzenleme")
        with get_session() as session:
            k = session.get(KartAnaTuru, int(ana_id))
            if not k:
                raise ValueError("Ana tür bulunamadı.")
            k.aktif = False
            k.guncelleme_tarihi = datetime.now()

    @staticmethod
    def pasife_al_alt(alt_id: int) -> None:
        yazma_zorunlu("sistem_ayarlari", "stok_duzenleme", "cari_duzenleme")
        with get_session() as session:
            k = session.get(KartAltTuru, int(alt_id))
            if not k:
                raise ValueError("Alt tür bulunamadı.")
            k.aktif = False
            k.guncelleme_tarihi = datetime.now()

    @staticmethod
    def sektor_listele(*, sadece_aktif: bool = True, sektor_listesinde: bool = True) -> list[dict]:
        from database.models.cari import MusteriGrubu

        try:
            KartTuruService.ensure_schema()
        except Exception:
            pass
        with get_session() as session:
            q = select(MusteriGrubu).order_by(MusteriGrubu.sira, MusteriGrubu.ad)
            kayitlar = list(session.scalars(q).all())
            sonuc = []
            for g in kayitlar:
                if sadece_aktif and hasattr(g, "aktif") and not g.aktif:
                    continue
                if sektor_listesinde and hasattr(g, "sektor_listesinde") and not g.sektor_listesinde:
                    continue
                sonuc.append(
                    {
                        "id": g.id,
                        "ad": g.ad,
                        "kod": getattr(g, "kod", None),
                        "aciklama": getattr(g, "aciklama", None),
                        "aktif": getattr(g, "aktif", True),
                        "sira": getattr(g, "sira", 100),
                        "sektor_listesinde": getattr(g, "sektor_listesinde", True),
                    }
                )
            return sonuc

    @staticmethod
    def sektor_kaydet(veri: dict[str, Any]) -> dict:
        yazma_zorunlu("sistem_ayarlari", "cari_duzenleme")
        from database.models.cari import MusteriGrubu

        ad = " ".join((veri.get("ad") or "").split())
        if not ad:
            raise ValueError("Sektör grubu adı zorunlu.")
        # Perakende Müşteri / Hizmet Tedarikçisi sektör olamaz
        yasak = {_norm("Perakende Müşteri"), _norm("Hizmet Tedarikçisi")}
        if _norm(ad) in yasak:
            raise ValueError(
                "Perakende Müşteri ve Hizmet Tedarikçisi sektör grubu değildir; "
                "bunlar cari alt kart türüdür."
            )
        kod = (veri.get("kod") or "").strip() or _kod_uret(ad)
        kayit_id = veri.get("id")
        with get_session() as session:
            for dig in session.scalars(select(MusteriGrubu)).all():
                if kayit_id and dig.id == int(kayit_id):
                    continue
                if _norm(dig.ad) == _norm(ad):
                    raise ValueError("Aynı adlı sektör grubu zaten var.")
            if kayit_id:
                g = session.get(MusteriGrubu, int(kayit_id))
                if not g:
                    raise ValueError("Sektör bulunamadı.")
            else:
                g = MusteriGrubu(ad=ad)
                session.add(g)
            g.ad = ad
            g.kod = kod[:40]
            g.aciklama = (veri.get("aciklama") or "").strip() or None
            g.aktif = bool(veri.get("aktif", True))
            g.sira = int(veri.get("sira") or 100)
            g.sektor_listesinde = bool(veri.get("sektor_listesinde", True))
            session.flush()
            return {"id": g.id, "ad": g.ad, "kod": g.kod}

    @staticmethod
    def stok_tur_dogrula(ana_id: int | None, alt_id: int | None) -> tuple[int | None, int | None, str | None]:
        """Uyumsuz alt türü temizler; (ana, alt, uyarı) döner."""
        if not ana_id:
            return None, None, None
        ana = KartTuruService.ana_getir(int(ana_id))
        if not ana or ana.kapsam != KAPSAM_STOK:
            raise ValueError("Geçersiz stok ana kart türü.")
        if not alt_id:
            return ana.id, None, None
        alt = KartTuruService.alt_getir(int(alt_id))
        if not alt or int(alt.ana_tur_id) != int(ana.id):
            return ana.id, None, "Seçilen alt tür yeni ana türe ait değil; alt tür temizlendi."
        return ana.id, alt.id, None

    @staticmethod
    def cari_rol_metni(ana: KartAnaTuru | None, cari_turu_eski: str | None = None) -> str:
        if ana and ana.muhasebe_rol == "MUSTERI_TEDARIKCI":
            return "Müşteri/Tedarikçi"
        if ana and ana.muhasebe_rol == "TEDARIKCI":
            return "Tedarikçi"
        if ana and ana.muhasebe_rol == "PERSONEL":
            return "Personel"
        if ana and ana.muhasebe_rol == "MUSTERI":
            return "Müşteri"
        return cari_turu_eski or "Müşteri"

    @staticmethod
    def gecis_calistir() -> dict[str, Any]:
        """Eski alanları yeni yapıya taşı; tekrar çalışınca mükerrer üretme."""
        from database.models.cari import Cari, MusteriGrubu
        from database.models.stok import StokKarti

        rapor = {
            "stok_eslesen": 0,
            "stok_atlanamayan": 0,
            "cari_eslesen": 0,
            "perakende_tasi": 0,
            "hizmet_tedarikci": 0,
            "catisma": [],
            "eslesme_dokumu": [],
        }
        with get_session() as session:
            stok_analar = {
                k.kod: k
                for k in session.scalars(
                    select(KartAnaTuru).where(KartAnaTuru.kapsam == KAPSAM_STOK)
                ).all()
            }
            # Yalnız gerekli kolonlar — eski firma DB'lerinde eksik kolon hatası olmasın
            stok_satirlar = session.execute(
                select(
                    StokKarti.id,
                    StokKarti.kart_turu,
                    StokKarti.ana_kart_turu_id,
                )
            ).all()
            for sid, kart_turu, ana_id in stok_satirlar:
                if ana_id:
                    continue
                eski = (kart_turu or "").strip()
                kod = _STOK_ESKI_ESLEME.get(_norm(eski))
                ana = stok_analar.get(kod) if kod else None
                if not ana:
                    for a in stok_analar.values():
                        if _norm(a.ad) == _norm(eski):
                            ana = a
                            break
                if ana:
                    session.execute(
                        StokKarti.__table__.update()
                        .where(StokKarti.id == sid)
                        .values(ana_kart_turu_id=ana.id, kart_turu=ana.ad)
                    )
                    rapor["stok_eslesen"] += 1
                    rapor["eslesme_dokumu"].append(
                        {"tur": "stok", "eski": eski, "ana": ana.ad, "id": sid}
                    )
                else:
                    rapor["stok_atlanamayan"] += 1
                    if eski:
                        rapor["catisma"].append(
                            {"tur": "stok", "id": sid, "eski": eski, "neden": "ana_tur_yok"}
                        )

            musteri_ana = KartTuruService._ana_bul(session, KAPSAM_CARI, kod="MUSTERI")
            tedarik_ana = KartTuruService._ana_bul(session, KAPSAM_CARI, kod="TEDARIKCI")
            perakende_alt = (
                KartTuruService._alt_bul(session, musteri_ana.id, kod="PERAKENDE_MUSTERI")
                if musteri_ana
                else None
            )
            hizmet_alt = (
                KartTuruService._alt_bul(session, tedarik_ana.id, kod="HIZMET_TEDARIKCISI")
                if tedarik_ana
                else None
            )

            # PERAKENDE grubunu sektör listesinden çıkar
            for gid, gad in session.execute(select(MusteriGrubu.id, MusteriGrubu.ad)).all():
                if _norm(gad) in {_norm("Perakende Müşteri"), _norm("PERAKENDE MÜŞTERİ")}:
                    session.execute(
                        MusteriGrubu.__table__.update()
                        .where(MusteriGrubu.id == gid)
                        .values(sektor_listesinde=False, sistem=True)
                    )

            personel_ana = KartTuruService._ana_bul(session, KAPSAM_CARI, kod="PERSONEL")
            mt_ana = KartTuruService._ana_bul(session, KAPSAM_CARI, kod="MUSTERI_TEDARIKCI")
            cari_satirlar = session.execute(
                select(
                    Cari.id,
                    Cari.cari_turu,
                    Cari.musteri_grubu,
                    Cari.ana_kart_turu_id,
                    Cari.musteri_alt_tur_id,
                    Cari.tedarikci_alt_tur_id,
                )
            ).all()
            for cid, tur, grup, ana_id, m_alt, t_alt in cari_satirlar:
                guncelle: dict[str, Any] = {}
                if not ana_id:
                    tur_n = (tur or "").strip()
                    if _norm(tur_n) in {_norm("Tedarikçi")} and tedarik_ana:
                        guncelle["ana_kart_turu_id"] = tedarik_ana.id
                        rapor["cari_eslesen"] += 1
                    elif _norm(tur_n) in {_norm("Personel")} and personel_ana:
                        guncelle["ana_kart_turu_id"] = personel_ana.id
                        rapor["cari_eslesen"] += 1
                    elif _norm(tur_n) in {_norm("Müşteri/Tedarikçi"), _norm("Musteri/Tedarikci")} and mt_ana:
                        guncelle["ana_kart_turu_id"] = mt_ana.id
                        rapor["cari_eslesen"] += 1
                    elif musteri_ana:
                        guncelle["ana_kart_turu_id"] = musteri_ana.id
                        rapor["cari_eslesen"] += 1

                grup_s = (grup or "").strip()
                if grup_s and _norm(grup_s) in {_norm("Perakende Müşteri"), _norm("PERAKENDE MÜŞTERİ")}:
                    if perakende_alt:
                        if m_alt and m_alt != perakende_alt.id:
                            rapor["catisma"].append(
                                {
                                    "tur": "cari",
                                    "id": cid,
                                    "eski": grup_s,
                                    "neden": "alt_tur_catisma",
                                    "mevcut_alt": m_alt,
                                }
                            )
                        else:
                            guncelle["musteri_alt_tur_id"] = perakende_alt.id
                            guncelle["musteri_grubu"] = None
                            rapor["perakende_tasi"] += 1
                elif grup_s:
                    hedef = _ESKI_GRUP_SEKTOR.get(_norm(grup_s))
                    if hedef:
                        guncelle["musteri_grubu"] = hedef

                tur_n = (tur or "").strip()
                if _norm(tur_n) == _norm("Hizmet Tedarikçisi") and hizmet_alt and tedarik_ana:
                    if t_alt and t_alt != hizmet_alt.id:
                        rapor["catisma"].append(
                            {
                                "tur": "cari",
                                "id": cid,
                                "eski": tur_n,
                                "neden": "hizmet_alt_catisma",
                            }
                        )
                    else:
                        guncelle.update(
                            {
                                "cari_turu": "Tedarikçi",
                                "ana_kart_turu_id": tedarik_ana.id,
                                "tedarikci_alt_tur_id": hizmet_alt.id,
                            }
                        )
                        rapor["hizmet_tedarikci"] += 1

                if guncelle:
                    session.execute(
                        Cari.__table__.update().where(Cari.id == cid).values(**guncelle)
                    )

            session.flush()
        return rapor

    @staticmethod
    def stok_filtre_uygula(statement, *, ana_id=None, alt_id=None, atanmamis_alt: bool = False):
        from database.models.stok import StokKarti

        if ana_id:
            statement = statement.where(StokKarti.ana_kart_turu_id == int(ana_id))
        if atanmamis_alt:
            statement = statement.where(StokKarti.alt_kart_turu_id.is_(None))
        elif alt_id:
            statement = statement.where(StokKarti.alt_kart_turu_id == int(alt_id))
        return statement

    @staticmethod
    def cari_filtre_uygula(
        statement,
        *,
        ana_rol: str | None = None,
        alt_id: int | None = None,
        sektor: str | None = None,
        atanmamis_alt: bool = False,
        atanmamis_grup: bool = False,
        karma_yalniz: bool = False,
    ):
        from database.models.cari import Cari

        if karma_yalniz:
            statement = statement.where(Cari.cari_turu == "Müşteri/Tedarikçi")
        elif ana_rol:
            rol = ana_rol.strip()
            if rol.casefold().startswith("müşter") or rol.casefold().startswith("muster"):
                statement = statement.where(
                    or_(
                        Cari.cari_turu == "Müşteri",
                        Cari.cari_turu == "Müşteri/Tedarikçi",
                        Cari.cari_turu.ilike("müster%"),
                        Cari.cari_turu.ilike("muster%"),
                    )
                )
            elif rol.casefold().startswith("tedarik"):
                statement = statement.where(
                    or_(
                        Cari.cari_turu == "Tedarikçi",
                        Cari.cari_turu == "Müşteri/Tedarikçi",
                        Cari.cari_turu.ilike("tedarik%"),
                    )
                )
            else:
                statement = statement.where(Cari.cari_turu == rol)

        if atanmamis_alt:
            if ana_rol and ana_rol.casefold().startswith("tedarik"):
                statement = statement.where(Cari.tedarikci_alt_tur_id.is_(None))
            else:
                statement = statement.where(Cari.musteri_alt_tur_id.is_(None))
        elif alt_id:
            if ana_rol and ana_rol.casefold().startswith("tedarik"):
                statement = statement.where(Cari.tedarikci_alt_tur_id == int(alt_id))
            else:
                # Müşteri filtresinde karma carinin müşteri alt türü değerlendirilir
                statement = statement.where(
                    or_(
                        Cari.musteri_alt_tur_id == int(alt_id),
                        Cari.tedarikci_alt_tur_id == int(alt_id),
                    )
                )

        if atanmamis_grup:
            statement = statement.where(
                or_(Cari.musteri_grubu.is_(None), Cari.musteri_grubu == "")
            )
        elif sektor:
            statement = statement.where(Cari.musteri_grubu == sektor)
        return statement
