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

# Sabit beş ana cari kart türü — kullanıcı yeni ana tür ekleyemez.
CARI_ANA_KODLARI = (
    "MUSTERI",
    "TEDARIKCI",
    "PERSONEL",
    "RESMI_KURUMLAR",
    "DUZENLEYICI",
)
# «Diğer Cari Listesi» görüntüleme grubu (6. ana tür değil)
DIGER_CARI_ANA_KODLARI = ("PERSONEL", "RESMI_KURUMLAR", "DUZENLEYICI")
DIGER_CARI_ANA_ADLARI = ("Personel", "Resmi Kurumlar", "Düzenleyici Hesaplar")
ESLEME_GEREKEN_ETIKET = "Tür eşlemesi gereken kayıtlar"
DIGER_LISTE_ANAHTARLARI = frozenset(
    {
        "diğer",
        "diger",
        "diğer cari",
        "diger cari",
        "diğer cari listesi",
        "diger cari listesi",
        "diger_cari",
        "digerler",
    }
)
ESLEME_GEREKEN_ANAHTARLARI = frozenset(
    {
        "esleme_gereken",
        "eşleme_gereken",
        "tür eşlemesi gereken kayıtlar",
        "tur eslemesi gereken kayitlar",
        "eşleme gereken",
        "esleme gereken",
    }
)
_CARI_ANA_SEED = (
    ("MUSTERI", "Müşteri", "MUSTERI", 10),
    ("TEDARIKCI", "Tedarikçi", "TEDARIKCI", 20),
    ("PERSONEL", "Personel", "PERSONEL", 30),
    ("RESMI_KURUMLAR", "Resmi Kurumlar", "RESMI_KURUMLAR", 40),
    ("DUZENLEYICI", "Düzenleyici Hesaplar", "DUZENLEYICI", 50),
)
# Eski / fazla ana tür kodları — kartlar taşındıktan sonra pasifleştirilir
_CARI_ANA_IPTAL_KODLAR = ("MUSTERI_TEDARIKCI", "DIGER", "DIGER_CARI", "MUSTERI_VE_TEDARIKCI")

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
    "PERSONEL": (),
    "RESMI_KURUMLAR": (),
    "DUZENLEYICI": (),
}

# Eski cari_turu / rol metni → yeni ana tür kodu (kesin eşleşmeler)
_CARI_ESKI_TUR_ESLEME = {
    "müşteri": "MUSTERI",
    "musteri": "MUSTERI",
    "tedarikçi": "TEDARIKCI",
    "tedarikci": "TEDARIKCI",
    "personel": "PERSONEL",
    "resmi kurumlar": "RESMI_KURUMLAR",
    "resmi kurum": "RESMI_KURUMLAR",
    "düzenleyici hesaplar": "DUZENLEYICI",
    "duzenleyici hesaplar": "DUZENLEYICI",
    "düzenleyici": "DUZENLEYICI",
    "duzenleyici": "DUZENLEYICI",
}
# Belirsiz — otomatik sınıflandırılmaz
_CARI_BELIRSIZ_TURLER = {
    "müşteri/tedarikçi",
    "musteri/tedarikci",
    "müşteri ve tedarikçi",
    "musteri ve tedarikci",
    "diğer",
    "diger",
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
                "ust_cari_id": "INTEGER",
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
                mevcut = KartTuruService._ana_bul(session, KAPSAM_CARI, kod=kod, ad=ad)
                if mevcut:
                    # Mevcut beşli tanımı aktif / sistem / doğru ad-rol ile tut
                    mevcut.ad = ad
                    mevcut.kod = kod
                    mevcut.muhasebe_rol = rol
                    mevcut.sira = sira
                    mevcut.sistem = True
                    mevcut.aktif = True
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
            # Fazla / eski ana tür tanımlarını pasifleştir (kartlar silinmez)
            for eski_kod in _CARI_ANA_IPTAL_KODLAR:
                eski = KartTuruService._ana_bul(session, KAPSAM_CARI, kod=eski_kod)
                if eski and eski.aktif:
                    eski.aktif = False
            for dig in session.scalars(
                select(KartAnaTuru).where(KartAnaTuru.kapsam == KAPSAM_CARI)
            ).all():
                if (dig.kod or "").upper() not in CARI_ANA_KODLARI and dig.aktif:
                    dig.aktif = False

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
                # Yeni cari ana tür açılamaz — yalnız sabit beş tür
                if not kayit_id:
                    raise ValueError(
                        "Cari ana kart türü sabittir (Müşteri, Tedarikçi, Personel, "
                        "Resmi Kurumlar, Düzenleyici Hesaplar). Yeni ana tür eklenemez; "
                        "alt tür / alt hesap kullanın."
                    )
                rol = (veri.get("muhasebe_rol") or "").strip().upper() or (kayit.muhasebe_rol or "")
                kod_u = (kayit.kod or kod or "").strip().upper()
                if kod_u not in CARI_ANA_KODLARI and rol not in CARI_ANA_KODLARI:
                    raise ValueError(
                        "Cari ana tür yalnız şu kodlardan biri olabilir: "
                        + ", ".join(CARI_ANA_KODLARI)
                    )
                if rol and rol not in CARI_ANA_KODLARI:
                    raise ValueError("Geçersiz muhasebe rolü.")
                if rol:
                    kayit.muhasebe_rol = rol
                # Beşli dışı kayıtlar yalnız pasifleştirilebilir
                if kod_u not in CARI_ANA_KODLARI and bool(veri.get("aktif", True)):
                    raise ValueError("Fazla cari ana tür yeniden aktifleştirilemez.")
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
        """Ana tür kaydından cari_turu metni (beşli yapı)."""
        rol = (getattr(ana, "muhasebe_rol", None) or getattr(ana, "kod", None) or "").upper()
        ad = (getattr(ana, "ad", None) or "").strip()
        if rol == "TEDARIKCI" or ad == "Tedarikçi":
            return "Tedarikçi"
        if rol == "PERSONEL" or ad == "Personel":
            return "Personel"
        if rol == "RESMI_KURUMLAR" or ad == "Resmi Kurumlar":
            return "Resmi Kurumlar"
        if rol == "DUZENLEYICI" or ad == "Düzenleyici Hesaplar":
            return "Düzenleyici Hesaplar"
        if rol == "MUSTERI" or ad == "Müşteri":
            return "Müşteri"
        # Eski karma rol artık ana tür değil — eski metni koruma (belirsiz rapor)
        if rol == "MUSTERI_TEDARIKCI":
            return cari_turu_eski or "Müşteri/Tedarikçi"
        return cari_turu_eski or "Müşteri"

    @staticmethod
    def cari_ana_kod_esle(eski_tur: str | None, *, muhasebe_rol: str | None = None) -> str | None:
        """Eski alan → yeni ana tür kodu. Belirsizde None."""
        rol = (muhasebe_rol or "").strip().upper()
        if rol in CARI_ANA_KODLARI:
            return rol
        if rol in _CARI_ANA_IPTAL_KODLAR or rol == "MUSTERI_TEDARIKCI":
            return None
        n = _norm(eski_tur)
        if not n:
            return None
        if n in _CARI_BELIRSIZ_TURLER:
            return None
        if n in _CARI_ESKI_TUR_ESLEME:
            return _CARI_ESKI_TUR_ESLEME[n]
        # Kısmi eşleşme (yalnız kesin önekler)
        if n.startswith("tedarik"):
            return "TEDARIKCI"
        if n.startswith("personel"):
            return "PERSONEL"
        if n.startswith("resmi"):
            return "RESMI_KURUMLAR"
        if n.startswith("düzenleyici") or n.startswith("duzenleyici"):
            return "DUZENLEYICI"
        if n.startswith("müşter") or n.startswith("muster"):
            # "müşteri/tedarikçi" belirsiz listede
            if "tedarik" in n:
                return None
            return "MUSTERI"
        return None

    @staticmethod
    def evo_grup_kaynak_turu(musteri_grubu: str | None) -> str | None:
        """«Evo: PERSONEL» → «PERSONEL»; Evo etiketi yoksa None."""
        g = (musteri_grubu or "").strip()
        if not g:
            return None
        n = _norm(g)
        if not n.startswith("evo:"):
            return None
        return g.split(":", 1)[1].strip() or None

    @staticmethod
    def _tr_kucuk(metin: str | None) -> str:
        """Türkçe İ/I güvenli küçük harf (Evo MUSTIP eşlemesiyle uyumlu)."""
        return (metin or "").strip().replace("İ", "i").replace("I", "ı").lower()

    @staticmethod
    def evo_grup_ana_kod(musteri_grubu: str | None) -> str | None:
        """Evo müşteri grubundan kesin ana tür kodu; bilinmeyen/boş → None (rastgele atama yok)."""
        kaynak = KartTuruService.evo_grup_kaynak_turu(musteri_grubu)
        if kaynak is None:
            return None
        # Evo haritası ile aynı sözlük (import döngüsü yok — yerel eşleme)
        n = KartTuruService._tr_kucuk(kaynak)
        harita = {
            "müşteri": "MUSTERI",
            "perakende müşteriler": "MUSTERI",
            "tedarikçi": "TEDARIKCI",
            "hizmet satıcılar": "TEDARIKCI",
            "personel": "PERSONEL",
            "resmi kurumlar": "RESMI_KURUMLAR",
            "resmi kurum": "RESMI_KURUMLAR",
            "düzenleyici": "DUZENLEYICI",
            "düzenleyici hesaplar": "DUZENLEYICI",
            "duzenleyici": "DUZENLEYICI",
            "duzenleyici hesaplar": "DUZENLEYICI",
        }
        if n in harita:
            return harita[n]
        return KartTuruService.cari_ana_kod_esle(kaynak)

    @staticmethod
    def digger_liste_mi(cari_turu: str | None) -> bool:
        n = _norm(cari_turu)
        return n in DIGER_LISTE_ANAHTARLARI or (cari_turu or "").strip().upper() == "DIGER"

    @staticmethod
    def esleme_gereken_filtre_mi(cari_turu: str | None) -> bool:
        n = _norm(cari_turu)
        return n in ESLEME_GEREKEN_ANAHTARLARI or n == _norm(ESLEME_GEREKEN_ETIKET)

    @staticmethod
    def cari_esleme_gereken_mi(
        *,
        cari_turu: str | None = None,
        ana_kod: str | None = None,
        musteri_grubu: str | None = None,
        ana_id: int | None = None,
    ) -> bool:
        """Kartın «Tür eşlemesi gereken» filtresine düşüp düşmeyeceği (yeni ana tür değil)."""
        tur_n = _norm(cari_turu)
        if tur_n in _CARI_BELIRSIZ_TURLER:
            return True
        kod = (ana_kod or "").strip().upper()
        if kod in _CARI_ANA_IPTAL_KODLAR:
            return True
        if not kod and not ana_id and not KartTuruService.cari_ana_kod_esle(cari_turu):
            return True
        # Evo'dan gelip haritada olmayan tür → varsayılan Müşteri; elle düzeltilmeli
        kaynak = KartTuruService.evo_grup_kaynak_turu(musteri_grubu)
        if kaynak is not None and KartTuruService.evo_grup_ana_kod(musteri_grubu) is None:
            return True
        return False

    @staticmethod
    def gecis_calistir() -> dict[str, Any]:
        """Eski alanları yeni yapıya taşı; tekrar çalışınca mükerrer üretme."""
        from database.models.cari import Cari, MusteriGrubu
        from database.models.stok import StokKarti

        rapor = {
            "stok_eslesen": 0,
            "stok_atlanamayan": 0,
            "cari_eslesen": 0,
            "cari_zaten_dogru": 0,
            "evo_grup_duzeltme": 0,
            "perakende_tasi": 0,
            "hizmet_tedarikci": 0,
            "belirsiz": [],
            "kaldirilan_turler": [],
            "tur_sayilari_once": {},
            "tur_sayilari_sonra": {},
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
            resmi_ana = KartTuruService._ana_bul(session, KAPSAM_CARI, kod="RESMI_KURUMLAR")
            duzen_ana = KartTuruService._ana_bul(session, KAPSAM_CARI, kod="DUZENLEYICI")
            mt_ana = KartTuruService._ana_bul(session, KAPSAM_CARI, kod="MUSTERI_TEDARIKCI")
            ana_by_id = {
                a.id: a
                for a in session.scalars(
                    select(KartAnaTuru).where(KartAnaTuru.kapsam == KAPSAM_CARI)
                ).all()
            }
            ana_by_kod = {
                (a.kod or "").upper(): a
                for a in ana_by_id.values()
                if (a.kod or "").upper() in CARI_ANA_KODLARI
            }

            def _tur_etiket(ana_id, tur_metin) -> str:
                if ana_id and ana_id in ana_by_id:
                    return ana_by_id[ana_id].ad or (tur_metin or "?")
                return (tur_metin or "?").strip() or "?"

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
            for _cid0, tur0, _g0, ana0, _m0, _t0 in cari_satirlar:
                et = _tur_etiket(ana0, tur0)
                rapor["tur_sayilari_once"][et] = rapor["tur_sayilari_once"].get(et, 0) + 1

            for cid, tur, grup, ana_id, m_alt, t_alt in cari_satirlar:
                guncelle: dict[str, Any] = {}
                mevcut_ana = ana_by_id.get(ana_id) if ana_id else None
                mevcut_kod = (mevcut_ana.kod or "").upper() if mevcut_ana else ""

                # Zaten doğru beşlideyse dokunma (tekrar çalıştırmada bozma)
                if mevcut_kod in CARI_ANA_KODLARI:
                    # Evo varsayılan Müşteri düşümü: kesin Evo grubu farklı ana türe işaret ediyorsa düzelt
                    # (tam devir yeniden çalıştırılmaz; yalnız yanlış eşlenen mevcut kartlar)
                    evo_hedef = KartTuruService.evo_grup_ana_kod(grup)
                    if (
                        mevcut_kod == "MUSTERI"
                        and evo_hedef
                        and evo_hedef != "MUSTERI"
                        and evo_hedef in ana_by_kod
                    ):
                        yeni = ana_by_kod[evo_hedef]
                        guncelle["ana_kart_turu_id"] = yeni.id
                        guncelle["cari_turu"] = KartTuruService.cari_rol_metni(yeni, tur)
                        rapor["evo_grup_duzeltme"] += 1
                        rapor["cari_eslesen"] += 1
                        rapor["eslesme_dokumu"].append(
                            {
                                "tur": "cari",
                                "id": cid,
                                "eski": tur,
                                "eski_ana": mevcut_ana.ad if mevcut_ana else None,
                                "ana": yeni.ad,
                                "neden": "evo_grup_kesin_esleme",
                                "evo_grup": (grup or "").strip(),
                            }
                        )
                    else:
                        rapor["cari_zaten_dogru"] += 1
                        # cari_turu metnini ana türle hizala (bakiye/hareket yok)
                        hedef_metin = KartTuruService.cari_rol_metni(mevcut_ana, tur)
                        if (tur or "").strip() != hedef_metin:
                            guncelle["cari_turu"] = hedef_metin
                        # Evo grubu haritada yoksa belirsiz raporla (tür atama)
                        if KartTuruService.cari_esleme_gereken_mi(
                            cari_turu=tur,
                            ana_kod=mevcut_kod,
                            musteri_grubu=grup,
                            ana_id=ana_id,
                        ):
                            rapor["belirsiz"].append(
                                {
                                    "id": cid,
                                    "cari_turu": tur,
                                    "ana_tur": mevcut_ana.ad if mevcut_ana else None,
                                    "neden": "evo_tur_eslenemedi",
                                    "evo_grup": (grup or "").strip() or None,
                                }
                            )
                elif mevcut_kod in _CARI_ANA_IPTAL_KODLAR or (
                    mevcut_ana and mevcut_kod not in CARI_ANA_KODLARI and mevcut_kod
                ):
                    # Fazla ana tür bağlı — kesin eşleme yoksa belirsiz bırak
                    hedef_kod = KartTuruService.cari_ana_kod_esle(
                        tur, muhasebe_rol=getattr(mevcut_ana, "muhasebe_rol", None)
                    )
                    if hedef_kod and hedef_kod in ana_by_kod:
                        yeni = ana_by_kod[hedef_kod]
                        guncelle["ana_kart_turu_id"] = yeni.id
                        guncelle["cari_turu"] = KartTuruService.cari_rol_metni(yeni, tur)
                        rapor["cari_eslesen"] += 1
                        rapor["eslesme_dokumu"].append(
                            {
                                "tur": "cari",
                                "id": cid,
                                "eski": tur,
                                "eski_ana": mevcut_ana.ad if mevcut_ana else None,
                                "ana": yeni.ad,
                            }
                        )
                    else:
                        rapor["belirsiz"].append(
                            {
                                "id": cid,
                                "cari_turu": tur,
                                "ana_tur": mevcut_ana.ad if mevcut_ana else None,
                                "neden": "fazla_ana_tur_otomatik_eslenemedi",
                            }
                        )
                elif not ana_id:
                    tur_n = (tur or "").strip()
                    hedef_kod = KartTuruService.cari_ana_kod_esle(tur_n)
                    if _norm(tur_n) == _norm("Hizmet Tedarikçisi"):
                        hedef_kod = "TEDARIKCI"
                    if hedef_kod and hedef_kod in ana_by_kod:
                        yeni = ana_by_kod[hedef_kod]
                        guncelle["ana_kart_turu_id"] = yeni.id
                        guncelle["cari_turu"] = KartTuruService.cari_rol_metni(yeni, tur_n)
                        rapor["cari_eslesen"] += 1
                        rapor["eslesme_dokumu"].append(
                            {"tur": "cari", "id": cid, "eski": tur_n, "ana": yeni.ad}
                        )
                    elif _norm(tur_n) in _CARI_BELIRSIZ_TURLER or not tur_n:
                        rapor["belirsiz"].append(
                            {
                                "id": cid,
                                "cari_turu": tur_n,
                                "ana_tur": None,
                                "neden": "belirsiz_eski_tur",
                            }
                        )
                    else:
                        rapor["belirsiz"].append(
                            {
                                "id": cid,
                                "cari_turu": tur_n,
                                "ana_tur": None,
                                "neden": "esleme_yok",
                            }
                        )

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
            # Pasif fazla tür tanımlarını raporla (kart silinmez)
            for dig in session.scalars(
                select(KartAnaTuru).where(KartAnaTuru.kapsam == KAPSAM_CARI)
            ).all():
                kod_u = (dig.kod or "").upper()
                if kod_u not in CARI_ANA_KODLARI:
                    if dig.aktif:
                        dig.aktif = False
                    rapor["kaldirilan_turler"].append(
                        {"id": dig.id, "kod": dig.kod, "ad": dig.ad, "aktif": False}
                    )

            # Son sayılar
            son_satirlar = session.execute(
                select(Cari.id, Cari.cari_turu, Cari.ana_kart_turu_id)
            ).all()
            ana_by_id = {
                a.id: a
                for a in session.scalars(
                    select(KartAnaTuru).where(KartAnaTuru.kapsam == KAPSAM_CARI)
                ).all()
            }
            for _cid1, tur1, ana1 in son_satirlar:
                et = _tur_etiket(ana1, tur1)
                rapor["tur_sayilari_sonra"][et] = rapor["tur_sayilari_sonra"].get(et, 0) + 1

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

        # karma_yalniz artık ayrı ana tür değil — eski çağrılar boş sonuç görür
        if karma_yalniz:
            statement = statement.where(Cari.cari_turu == "Müşteri/Tedarikçi")
        elif ana_rol:
            rol = ana_rol.strip()
            # Diğer Cari Listesi: Personel + Resmi + Düzenleyici (6. ana tür değil)
            if KartTuruService.digger_liste_mi(rol):
                digger_idler: list[int] = []
                digger_adlar: list[str] = []
                try:
                    for a in KartTuruService.ana_turleri_listele(KAPSAM_CARI, sadece_aktif=False):
                        if (a.kod or "").upper() in DIGER_CARI_ANA_KODLARI:
                            digger_idler.append(int(a.id))
                            digger_adlar.append(a.ad)
                except Exception:
                    digger_idler, digger_adlar = [], list(DIGER_CARI_ANA_ADLARI)
                kosullar = []
                if digger_idler:
                    kosullar.append(Cari.ana_kart_turu_id.in_(digger_idler))
                if digger_adlar:
                    kosullar.append(
                        Cari.ana_kart_turu_id.is_(None) & Cari.cari_turu.in_(digger_adlar)
                    )
                for ad in DIGER_CARI_ANA_ADLARI:
                    if ad not in digger_adlar:
                        kosullar.append(Cari.cari_turu == ad)
                if kosullar:
                    statement = statement.where(or_(*kosullar))
                else:
                    statement = statement.where(Cari.cari_turu.in_(DIGER_CARI_ANA_ADLARI))
            elif KartTuruService.esleme_gereken_filtre_mi(rol):
                # Eşleme gereken: belirsiz metin + Evo'da haritasız grup (rastgele tür yok)
                # Bilinen Evo: Müşteri/Tedarikçi/Personel… burada çekilmez
                iptal_idler: list[int] = []
                try:
                    for a in KartTuruService.ana_turleri_listele(KAPSAM_CARI, sadece_aktif=False):
                        if (a.kod or "").upper() in _CARI_ANA_IPTAL_KODLAR:
                            iptal_idler.append(int(a.id))
                except Exception:
                    iptal_idler = []
                kosullar = [
                    Cari.cari_turu.in_(("Müşteri/Tedarikçi", "Diğer", "Diger")),
                    Cari.musteri_grubu.ilike("Evo: Türü belirtilmemiş%"),
                    Cari.musteri_grubu.ilike("Evo: Turu belirtilmemis%"),
                ]
                if iptal_idler:
                    kosullar.append(Cari.ana_kart_turu_id.in_(iptal_idler))
                kosullar.append(
                    Cari.ana_kart_turu_id.is_(None)
                    & or_(
                        Cari.cari_turu.is_(None),
                        Cari.cari_turu == "",
                        Cari.cari_turu.in_(("Müşteri/Tedarikçi", "Diğer", "Diger")),
                    )
                )
                statement = statement.where(or_(*kosullar))
            else:
                kod = KartTuruService.cari_ana_kod_esle(rol) or rol.strip().upper()
                ana = None
                try:
                    for a in KartTuruService.ana_turleri_listele(KAPSAM_CARI, sadece_aktif=False):
                        if (a.kod or "").upper() == kod or _norm(a.ad) == _norm(rol):
                            ana = a
                            break
                except Exception:
                    ana = None
                if ana:
                    # Liste grupları güncel Ana Cari Kart Türü alanına göre
                    statement = statement.where(
                        or_(
                            Cari.ana_kart_turu_id == int(ana.id),
                            # Henüz ana_id yazılmamış eski satırlar (aynı metin)
                            (Cari.ana_kart_turu_id.is_(None) & (Cari.cari_turu == ana.ad)),
                        )
                    )
                elif rol.casefold().startswith("müşter") or rol.casefold().startswith("muster"):
                    statement = statement.where(Cari.cari_turu == "Müşteri")
                elif rol.casefold().startswith("tedarik"):
                    statement = statement.where(Cari.cari_turu == "Tedarikçi")
                else:
                    statement = statement.where(Cari.cari_turu == rol)

        if atanmamis_alt:
            if ana_rol and (
                ana_rol.casefold().startswith("tedarik")
                or (KartTuruService.cari_ana_kod_esle(ana_rol) == "TEDARIKCI")
            ):
                statement = statement.where(Cari.tedarikci_alt_tur_id.is_(None))
            else:
                statement = statement.where(Cari.musteri_alt_tur_id.is_(None))
        elif alt_id:
            if ana_rol and (
                ana_rol.casefold().startswith("tedarik")
                or (KartTuruService.cari_ana_kod_esle(ana_rol) == "TEDARIKCI")
            ):
                statement = statement.where(Cari.tedarikci_alt_tur_id == int(alt_id))
            else:
                statement = statement.where(Cari.musteri_alt_tur_id == int(alt_id))

        if atanmamis_grup:
            statement = statement.where(
                or_(Cari.musteri_grubu.is_(None), Cari.musteri_grubu == "")
            )
        elif sektor:
            statement = statement.where(Cari.musteri_grubu == sektor)
        return statement
