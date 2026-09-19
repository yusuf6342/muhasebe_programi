"""Çoklu blok, sıra bağımsız arama — ortak servis.

Bloklar AND; her blok izinli alanlarda OR. Türkçe normalize + min 2 karakter.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from database.turkce_normalize import arama_like_varyantlari, turkce_normalize


def _get_session():
    """Testlerin monkeypatch'i için her çağrıda database.database üzerinden alınır."""
    from database.database import get_session

    return get_session()

# Noktalama → boşluk (aramayı bozmayan ayırıcılar)
_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def normalize_text(metin: str | None) -> str:
    """Türkçe karakter + harf büyüklüğü + boşluk/noktalama normalizasyonu."""
    if not metin:
        return ""
    # NFKC + noktalama ayırıcı
    s = unicodedata.normalize("NFKC", str(metin))
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return turkce_normalize(s)


def tokenize_query(metin: str | None, *, min_len: int = 2) -> list[str]:
    """En az min_len karakterli bloklar; mükerrerler tekilleşir (normalize anahtarla)."""
    ham = (metin or "").strip()
    if not ham:
        return []
    # Noktalama → boşluk, fazla boşluk temizle
    s = unicodedata.normalize("NFKC", ham)
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    bloklar: list[str] = []
    gorulen: set[str] = set()
    for parca in s.split(" "):
        p = parca.strip()
        if len(p) < min_len:
            continue
        anahtar = normalize_text(p)
        if not anahtar or anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        bloklar.append(p)
    return bloklar


def _alan_havuzu_stok(stok) -> str:
    """Normalize edilmiş birleşik alan metni (Python eşleşme)."""
    parcalar = [
        getattr(stok, "stok_kodu", None),
        getattr(stok, "stok_adi", None),
        getattr(stok, "barkod", None),
        getattr(stok, "marka", None),
        getattr(stok, "rapor_grubu", None),
        getattr(stok, "birim", None),
        getattr(stok, "aciklama", None),
        getattr(stok, "model", None),
        getattr(stok, "renk", None),
        getattr(stok, "raf_yeri", None),
    ]
    for b in getattr(stok, "barkodlar", None) or []:
        parcalar.append(getattr(b, "barkod", None))
    # Grup adları (yüklüyse)
    for attr in ("ana_grup", "tali_grup", "alt_grup"):
        g = getattr(stok, attr, None)
        if g is not None:
            parcalar.append(getattr(g, "ad", None) or getattr(g, "adi", None))
    return " ".join(normalize_text(p) for p in parcalar if p)


def _alan_havuzu_cari(cari) -> str:
    parcalar = [
        getattr(cari, "cari_kodu", None),
        getattr(cari, "unvan", None),
        getattr(cari, "telefon", None),
        getattr(cari, "telefon2", None),
        getattr(cari, "telefon3", None),
        getattr(cari, "vergi_numarasi", None),
        getattr(cari, "tc_kimlik", None),
        getattr(cari, "il", None),
        getattr(cari, "ilce", None),
        getattr(cari, "adres", None),
        getattr(cari, "il2", None),
        getattr(cari, "ilce2", None),
        getattr(cari, "adres2", None),
        getattr(cari, "il3", None),
        getattr(cari, "ilce3", None),
        getattr(cari, "adres3", None),
        getattr(cari, "email", None),
        getattr(cari, "musteri_grubu", None),
    ]
    return " ".join(normalize_text(p) for p in parcalar if p)


def kayit_bloklari_eslesir(havuz_norm: str, bloklar: list[str]) -> bool:
    """Tüm bloklar havuzda (AND)."""
    if not bloklar:
        return True
    for b in bloklar:
        nb = normalize_text(b)
        if not nb or nb not in havuz_norm:
            return False
    return True


def calculate_relevance(
    *,
    bloklar: list[str],
    kod: str = "",
    ad: str = "",
    barkod: str = "",
    ek_barkodlar: list[str] | None = None,
    havuz_norm: str = "",
    aktif: bool = True,
    stokta: bool | None = None,
) -> int:
    """Yüksek = daha iyi. Dokümandaki öncelik sırası."""
    if not bloklar:
        return 0
    q_birlesik = " ".join(bloklar)
    nq = normalize_text(q_birlesik)
    n_kod = normalize_text(kod)
    n_ad = normalize_text(ad)
    n_barkod = normalize_text(barkod)
    puan = 0
    # 1 Tam barkod
    if len(bloklar) == 1:
        b0 = normalize_text(bloklar[0])
        if b0 and (b0 == n_barkod or any(b0 == normalize_text(x) for x in (ek_barkodlar or []))):
            puan += 10_000
        # 2 Tam kod
        if b0 and b0 == n_kod:
            puan += 8_000
        # 3 Tam ad
        if b0 and b0 == n_ad:
            puan += 6_000
        # 4 Ad başlangıcı
        if b0 and n_ad.startswith(b0):
            puan += 4_000
    # 5 Tüm bloklar ad içinde
    if all(normalize_text(b) in n_ad for b in bloklar):
        puan += 2_000
    # 6 Farklı alanlarda (havuzda)
    if kayit_bloklari_eslesir(havuz_norm or n_ad, bloklar):
        puan += 500
    # 7 Aktif / stokta
    if aktif:
        puan += 50
    if stokta:
        puan += 30
    # 8 Alfabetik denge için küçük negatif yok — sıralamada ad kullanılır
    # Sorgu ile ad yakınlığı
    if nq and n_ad.startswith(nq):
        puan += 100
    return puan


def _blok_sql_kosullari_stok(blok: str):
    """Tek blok için parametreli OR alan koşulları."""
    from database.models.stok import StokBarkod, StokKarti

    patterns = arama_like_varyantlari(blok, max_n=12) or [f"%{blok}%"]
    kosullar = []
    for v in patterns:
        kosullar.extend(
            [
                StokKarti.stok_kodu.ilike(v),
                StokKarti.stok_adi.ilike(v),
                StokKarti.barkod.ilike(v),
                StokKarti.marka.ilike(v),
                StokKarti.rapor_grubu.ilike(v),
                StokKarti.birim.ilike(v),
                StokKarti.aciklama.ilike(v),
                StokKarti.model.ilike(v),
                StokKarti.raf_yeri.ilike(v),
            ]
        )
    # Ek barkod tablosu
    barkod_alt = select(StokBarkod.stok_id).where(
        or_(*[StokBarkod.barkod.ilike(v) for v in patterns])
    )
    kosullar.append(StokKarti.id.in_(barkod_alt))
    return or_(*kosullar)


def _blok_sql_kosullari_cari(blok: str):
    from database.models.cari import Cari

    patterns = arama_like_varyantlari(blok, max_n=24) or [f"%{blok}%"]
    kosullar = []
    for v in patterns:
        kosullar.extend(
            [
                Cari.cari_kodu.ilike(v),
                Cari.unvan.ilike(v),
                Cari.telefon.ilike(v),
                Cari.telefon2.ilike(v),
                Cari.telefon3.ilike(v),
                Cari.vergi_numarasi.ilike(v),
                Cari.tc_kimlik.ilike(v),
                Cari.il.ilike(v),
                Cari.ilce.ilike(v),
                Cari.adres.ilike(v),
                Cari.email.ilike(v),
            ]
        )
    return or_(*kosullar)


def _cari_relevance(
    *,
    bloklar: list[str],
    kod: str = "",
    unvan: str = "",
    telefon: str = "",
    vergi: str = "",
    havuz_norm: str = "",
) -> int:
    """Tam kod/telefon/vergi > kelime başı > alt metin."""
    if not bloklar:
        return 0
    n_kod = normalize_text(kod)
    n_unvan = normalize_text(unvan)
    n_tel = normalize_text(telefon)
    n_vergi = normalize_text(vergi)
    puan = 0
    if len(bloklar) == 1:
        b0 = normalize_text(bloklar[0])
        if b0 and b0 == n_kod:
            puan += 10_000
        if b0 and (b0 == n_tel or b0 == n_vergi):
            puan += 9_000
        if b0 and n_unvan.startswith(b0):
            puan += 4_000
        # Tam kelime / başlangıç
        for parca in n_unvan.split():
            if b0 and parca.startswith(b0):
                puan += 2_500
                break
    if all(normalize_text(b) in n_unvan for b in bloklar):
        puan += 2_000
    if kayit_bloklari_eslesir(havuz_norm or n_unvan, bloklar):
        puan += 500
    return puan


class SearchService:
    """Ortak arama API'si."""

    @staticmethod
    def normalize_text(metin: str | None) -> str:
        return normalize_text(metin)

    @staticmethod
    def tokenize_query(metin: str | None, *, min_len: int = 2) -> list[str]:
        return tokenize_query(metin, min_len=min_len)

    @staticmethod
    def search_stocks(
        arama: str = "",
        *,
        limit: int = 80,
        sadece_aktif: bool = True,
        sadece_stokta: bool = False,
        depo_ad: str | None = None,
        barkod_tam_once: bool = True,
    ) -> dict[str, Any]:
        """Stok çoklu blok arama.

        Dönüş: {urunler: [StokKarti], bloklar: [...], toplam: int, barkod_tam: bool}
        """
        from database.models.stok import Depo, StokBarkod, StokKarti, StokLotu

        limit = max(1, min(int(limit or 80), 100))
        ham = (arama or "").strip()
        bloklar = tokenize_query(ham)
        if not bloklar:
            return {
                "urunler": [],
                "bloklar": [],
                "toplam": 0,
                "barkod_tam": False,
                "mesaj": "En az 2 karakterli bir blok yazın." if ham else "",
            }

        with _get_session() as session:
            # 1) Tam barkod (tek blok / kesintisiz)
            if barkod_tam_once and len(bloklar) == 1:
                kod = bloklar[0]
                tam = session.scalar(
                    select(StokKarti)
                    .where(
                        StokKarti.barkod == kod,
                        or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)),
                        *((StokKarti.aktif.is_(True),) if sadece_aktif else ()),
                    )
                    .options(
                        selectinload(StokKarti.fiyatlar),
                        selectinload(StokKarti.lotlar),
                        selectinload(StokKarti.barkodlar),
                    )
                )
                if tam is None:
                    bid = session.scalar(
                        select(StokBarkod.stok_id).where(StokBarkod.barkod == kod)
                    )
                    if bid:
                        tam = session.scalar(
                            select(StokKarti)
                            .where(StokKarti.id == bid)
                            .options(
                                selectinload(StokKarti.fiyatlar),
                                selectinload(StokKarti.lotlar),
                                selectinload(StokKarti.barkodlar),
                            )
                        )
                if tam is not None:
                    return {
                        "urunler": [tam],
                        "bloklar": bloklar,
                        "toplam": 1,
                        "barkod_tam": True,
                        "mesaj": "",
                    }

            # 2) Tam stok kodu (tek blok)
            if len(bloklar) == 1:
                kod = bloklar[0]
                tam_kod = session.scalar(
                    select(StokKarti)
                    .where(
                        StokKarti.stok_kodu == kod,
                        or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)),
                        *((StokKarti.aktif.is_(True),) if sadece_aktif else ()),
                    )
                    .options(
                        selectinload(StokKarti.fiyatlar),
                        selectinload(StokKarti.lotlar),
                        selectinload(StokKarti.barkodlar),
                    )
                )
                if tam_kod is not None:
                    return {
                        "urunler": [tam_kod],
                        "bloklar": bloklar,
                        "toplam": 1,
                        "barkod_tam": False,
                        "mesaj": "",
                    }

            kosullar = [
                or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)),
            ]
            if sadece_aktif:
                kosullar.append(StokKarti.aktif.is_(True))
            for blok in bloklar:
                kosullar.append(_blok_sql_kosullari_stok(blok))

            if sadece_stokta:
                stoklu = select(StokLotu.stok_id).where(StokLotu.kalan_miktar > 0)
                if depo_ad:
                    depo = session.scalar(select(Depo).where(Depo.ad == depo_ad.strip()))
                    if depo is not None:
                        stoklu = stoklu.where(StokLotu.depo_id == depo.id)
                kosullar.append(StokKarti.id.in_(stoklu.distinct()))

            # Adayları geniş çek, Python'da kesin filtre + skor
            aday_limit = min(400, max(limit * 5, 100))
            adaylar = list(
                session.scalars(
                    select(StokKarti)
                    .where(*kosullar)
                    .options(
                        selectinload(StokKarti.fiyatlar),
                        selectinload(StokKarti.lotlar),
                        selectinload(StokKarti.barkodlar),
                    )
                    .order_by(StokKarti.stok_adi)
                    .limit(aday_limit)
                ).all()
            )

            skorlu: list[tuple[int, str, Any]] = []
            for stok in adaylar:
                havuz = _alan_havuzu_stok(stok)
                if not kayit_bloklari_eslesir(havuz, bloklar):
                    continue
                ek_b = [
                    (getattr(b, "barkod", None) or "")
                    for b in (getattr(stok, "barkodlar", None) or [])
                ]
                stokta = None
                if sadece_stokta:
                    stokta = True
                else:
                    try:
                        stokta = any(
                            Decimal(str(getattr(l, "kalan_miktar", 0) or 0)) > 0
                            for l in (getattr(stok, "lotlar", None) or [])
                        )
                    except Exception:
                        stokta = None
                puan = calculate_relevance(
                    bloklar=bloklar,
                    kod=stok.stok_kodu or "",
                    ad=stok.stok_adi or "",
                    barkod=stok.barkod or "",
                    ek_barkodlar=ek_b,
                    havuz_norm=havuz,
                    aktif=bool(stok.aktif),
                    stokta=stokta,
                )
                skorlu.append((puan, (stok.stok_adi or "").casefold(), stok))

            skorlu.sort(key=lambda x: (-x[0], x[1]))
            urunler = [s for _, _, s in skorlu[:limit]]
            return {
                "urunler": urunler,
                "bloklar": bloklar,
                "toplam": len(skorlu),
                "barkod_tam": False,
                "mesaj": ""
                if urunler
                else f"Bloklar eşleşmedi: {', '.join(bloklar)}",
            }

    @staticmethod
    def search_customers(
        arama: str = "",
        *,
        limit: int = 50,
        cari_turu: str | None = "Müşteri",
        sadece_aktif: bool = True,
    ) -> list[dict[str, Any]]:
        """Cari çoklu blok arama. Dönüş: [{cari, kod, unvan}, ...]

        Bloklar AND; her blok cari alanları VEYA yetkili alanlarında OR.
        Aynı cari tekilleşir.
        """
        from database.cari_service import CariService
        from database.models.cari import Cari

        limit = max(1, min(int(limit or 50), 100))
        ham = (arama or "").strip()
        bloklar = tokenize_query(ham)
        if not bloklar:
            return []

        with _get_session() as session:
            # Tam kod / telefon / vergi (tek blok) — üstte
            if len(bloklar) == 1:
                kod = bloklar[0]
                tam = session.scalar(
                    select(Cari).where(
                        Cari.cari_kodu == kod,
                        or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)),
                    )
                )
                if tam is None:
                    tam = session.scalar(
                        select(Cari).where(
                            or_(
                                Cari.telefon == kod,
                                Cari.telefon2 == kod,
                                Cari.telefon3 == kod,
                                Cari.vergi_numarasi == kod,
                                Cari.tc_kimlik == kod,
                            ),
                            or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)),
                        )
                    )
                if tam is not None:
                    if sadece_aktif and not tam.aktif:
                        pass
                    else:
                        ok = True
                        if cari_turu:
                            # Tür filtresi: mevcut yardımcıyı kullan
                            q = select(Cari).where(Cari.id == tam.id)
                            q = CariService._cari_turu_filtresi(q, cari_turu)
                            ok = session.scalar(q) is not None
                        if ok:
                            return [
                                {
                                    "cari": tam,
                                    "kod": (tam.cari_kodu or "").strip(),
                                    "unvan": (tam.unvan or "").strip(),
                                }
                            ]

            # Her blok için (cari alan OR yetkili) → id kümeleri kesişimi (AND)
            try:
                from database.cari_yetkili_service import CariYetkiliService
            except Exception:
                CariYetkiliService = None  # type: ignore

            temel = [
                or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)),
            ]
            if sadece_aktif:
                temel.append(Cari.aktif.is_(True))

            id_kume: set[int] | None = None
            for blok in bloklar:
                q = select(Cari.id).where(*temel, _blok_sql_kosullari_cari(blok))
                if cari_turu:
                    q = CariService._cari_turu_filtresi(q, cari_turu)
                cari_ids = set(int(x) for x in session.scalars(q.limit(2000)).all())
                yetkili_ids: set[int] = set()
                if CariYetkiliService is not None:
                    try:
                        yetkili_ids = set(
                            int(i)
                            for i in CariYetkiliService.cari_ids_yetkili_arama([blok])
                        )
                    except Exception:
                        yetkili_ids = set()
                birlesik = cari_ids | yetkili_ids
                id_kume = birlesik if id_kume is None else (id_kume & birlesik)
                if not id_kume:
                    return []

            adaylar = list(
                session.scalars(
                    select(Cari)
                    .where(Cari.id.in_(list(id_kume)), *temel)
                    .order_by(Cari.unvan)
                    .limit(min(400, max(limit * 5, 100)))
                ).all()
            )
            if cari_turu and adaylar:
                # Tür filtresi (yetkili kaynağından gelen id'ler için)
                tur_q = select(Cari.id).where(Cari.id.in_([c.id for c in adaylar]))
                tur_q = CariService._cari_turu_filtresi(tur_q, cari_turu)
                izinli = set(int(x) for x in session.scalars(tur_q).all())
                adaylar = [c for c in adaylar if c.id in izinli]

            # Yetkili eşleşen id'ler (tüm bloklar yetkilide) — skor için
            yetkili_tam: set[int] = set()
            if CariYetkiliService is not None:
                try:
                    yetkili_tam = set(
                        int(i)
                        for i in CariYetkiliService.cari_ids_yetkili_arama(bloklar)
                    )
                except Exception:
                    yetkili_tam = set()

            skorlu: list[tuple[int, str, str, dict[str, Any]]] = []
            gorulen: set[int] = set()
            for cari in adaylar:
                if cari.id in gorulen:
                    continue
                gorulen.add(cari.id)
                havuz = _alan_havuzu_cari(cari)
                puan = _cari_relevance(
                    bloklar=bloklar,
                    kod=cari.cari_kodu or "",
                    unvan=cari.unvan or "",
                    telefon=cari.telefon or "",
                    vergi=cari.vergi_numarasi or "",
                    havuz_norm=havuz,
                )
                if cari.id in yetkili_tam:
                    puan += 300
                skorlu.append(
                    (
                        puan,
                        normalize_text(cari.unvan or ""),
                        normalize_text(cari.cari_kodu or ""),
                        {
                            "cari": cari,
                            "kod": (cari.cari_kodu or "").strip(),
                            "unvan": (cari.unvan or "").strip(),
                        },
                    )
                )

            skorlu.sort(key=lambda x: (-x[0], x[1], x[2]))
            return [x[3] for x in skorlu[:limit]]

    @staticmethod
    def search_suppliers(arama: str = "", *, limit: int = 50) -> list[dict[str, Any]]:
        return SearchService.search_customers(
            arama, limit=limit, cari_turu="Tedarikçi"
        )


# Geriye uyum takma adları
build_search_conditions = _blok_sql_kosullari_stok
