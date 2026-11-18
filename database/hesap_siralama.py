"""Finans hesap listeleri: sınıf adı A–Z, sonra hesap adı A–Z (Türkçe + doğal sayı).

Görünüm sırasıdır; bakiyeleri / mali kayıtları değiştirmez.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

from database.models.finans import BANKA_ALT_HESAP_TURLERI
from ui_tablo_siralama import dogal_belge_anahtar

# Ekranda görünen sınıf etiketleri (Ana Kart → Hesaplar ile uyumlu)
_SINIF_ETIKET = dict(BANKA_ALT_HESAP_TURLERI)
_SINIF_ETIKET["VADELI"] = "Yatırım"
_SINIF_ETIKET["YATIRIM"] = "Yatırım"
_SINIF_ETIKET["KASA"] = "Kasa"

_OZEL_BASTAR = frozenset(
    {
        "",
        "seçiniz",
        "seciniz",
        "tümü",
        "tumu",
        "—",
        "-",
        "–",
    }
)


def hesap_sinif_gorunen_adi(hesap: Any, *, sinif_adi: str | None = None) -> str:
    """Ekranda gösterilen sınıf adı (sıralama birinci anahtarı)."""
    if sinif_adi is not None and str(sinif_adi).strip():
        return str(sinif_adi).strip()
    if hesap is None:
        return ""
    if isinstance(hesap, dict):
        for k in ("sinif_adi", "sinif", "alt_hesap_turu_etiket"):
            v = hesap.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        alt = (hesap.get("alt_hesap_turu") or "").strip().upper()
        tur = (hesap.get("hesap_turu") or "").strip().upper()
    else:
        alt = (getattr(hesap, "alt_hesap_turu", None) or "").strip().upper()
        tur = (getattr(hesap, "hesap_turu", None) or "").strip().upper()
    if alt.startswith("VADELI"):
        return _SINIF_ETIKET["VADELI"]
    if alt in _SINIF_ETIKET:
        return _SINIF_ETIKET[alt]
    if tur == "KASA":
        return _SINIF_ETIKET["KASA"]
    if tur:
        return tur.title()
    return alt or ""


def hesap_adi_gorunen(hesap: Any, *, hesap_adi: str | None = None) -> str:
    if hesap_adi is not None:
        return str(hesap_adi).strip()
    if hesap is None:
        return ""
    if isinstance(hesap, dict):
        return str(hesap.get("hesap_adi") or hesap.get("ad") or "").strip()
    return str(getattr(hesap, "hesap_adi", None) or "").strip()


def _hesap_kodu(hesap: Any) -> str:
    if hesap is None:
        return ""
    if isinstance(hesap, dict):
        return str(hesap.get("hesap_kodu") or hesap.get("hesap_no") or "").strip()
    return str(
        getattr(hesap, "hesap_kodu", None) or getattr(hesap, "hesap_no", None) or ""
    ).strip()


def _hesap_id(hesap: Any) -> int:
    if hesap is None:
        return 0
    if isinstance(hesap, dict):
        try:
            return int(hesap.get("id") or 0)
        except (TypeError, ValueError):
            return 0
    try:
        return int(getattr(hesap, "id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def hesap_siralama_anahtari(
    hesap: Any = None,
    *,
    sinif_adi: str | None = None,
    hesap_adi: str | None = None,
    hesap_kodu: str | None = None,
    hesap_id: int | None = None,
) -> tuple:
    """(sınıf, ad, kod, id) — Türkçe + doğal sayı; kararlı eşitlikte kimlik."""
    sinif = hesap_sinif_gorunen_adi(hesap, sinif_adi=sinif_adi)
    ad = hesap_adi_gorunen(hesap, hesap_adi=hesap_adi)
    kod = (hesap_kodu if hesap_kodu is not None else _hesap_kodu(hesap)) or ""
    hid = int(hesap_id) if hesap_id is not None else _hesap_id(hesap)
    return (
        dogal_belge_anahtar(sinif) or (),
        dogal_belge_anahtar(ad) or (),
        dogal_belge_anahtar(kod) or (),
        hid,
    )


def hesaplari_sirala(
    hesaplar: Iterable[Any],
    *,
    sinif_adi_fn: Callable[[Any], str] | None = None,
    hesap_adi_fn: Callable[[Any], str] | None = None,
) -> list:
    """Sınıf A–Z, sınıf içinde hesap adı A–Z."""
    liste = list(hesaplar or [])

    def _anahtar(h):
        return hesap_siralama_anahtari(
            h,
            sinif_adi=sinif_adi_fn(h) if sinif_adi_fn else None,
            hesap_adi=hesap_adi_fn(h) if hesap_adi_fn else None,
        )

    return sorted(liste, key=_anahtar)


def metin_sirala(metinler: Iterable[str | None]) -> list[str]:
    """Saf metin listesini Türkçe + doğal sırayla döndür."""
    return sorted(
        [str(m).strip() for m in (metinler or []) if m is not None and str(m).strip() != ""],
        key=lambda m: dogal_belge_anahtar(m) or (),
    )


def _ozel_mi(etiket: str) -> bool:
    return (etiket or "").strip().casefold().replace("İ", "i").replace("I", "ı") in _OZEL_BASTAR or (
        (etiket or "").strip().casefold() in {"seçiniz", "seciniz", "tümü", "tumu"}
    )


def etiket_listesini_sirala(
    etiketler: Sequence[str],
    *,
    bastaki_ozeller: Sequence[str] = ("Tümü", "Seçiniz", ""),
) -> list[str]:
    """Combobox değerleri: özel seçenekler başta (bilinen sırada), kalanlar alfabetik."""
    gorulen: set[str] = set()
    bastan: list[str] = []
    for o in bastaki_ozeller:
        for e in etiketler:
            if e == o and e not in gorulen:
                bastan.append(e)
                gorulen.add(e)
    diger = [e for e in etiketler if e not in gorulen]
    # Bilinmeyen özeller (ör. "—") başta kalsın ama alfabetik gövdede değil
    ozel_diger = [e for e in diger if _ozel_mi(e)]
    normal = [e for e in diger if not _ozel_mi(e)]
    normal_sirali = sorted(normal, key=lambda m: dogal_belge_anahtar(m) or ())
    return bastan + ozel_diger + normal_sirali


def sinif_ciftlerini_sirala(
    ogeler: Sequence[tuple[str, str]],
) -> list[tuple[str, str]]:
    """(kod, etiket) listesini görünen etiket A–Z ile sırala."""
    return sorted(ogeler, key=lambda x: dogal_belge_anahtar(x[1]) or ())
