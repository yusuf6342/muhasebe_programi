"""Tablo sıralama yardımcıları — görünüm sırası (veritabanını değiştirmez).

Cari Hareketler ve benzeri ttk.Treeview ekranlarında yeniden kullanılabilir.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Sequence

# Türkçe alfabetik sıra (küçük harf)
_TR_HARF_SIRA = {
    "a": "01",
    "b": "02",
    "c": "03",
    "ç": "04",
    "d": "05",
    "e": "06",
    "f": "07",
    "g": "08",
    "ğ": "09",
    "h": "10",
    "ı": "11",
    "i": "12",
    "j": "13",
    "k": "14",
    "l": "15",
    "m": "16",
    "n": "17",
    "o": "18",
    "ö": "19",
    "p": "20",
    "q": "21",
    "r": "22",
    "s": "23",
    "ş": "24",
    "t": "25",
    "u": "26",
    "ü": "27",
    "v": "28",
    "w": "29",
    "x": "30",
    "y": "31",
    "z": "32",
}

_SIRALAMA_ISARET_ARTAN = " ▲"
_SIRALAMA_ISARET_AZALAN = " ▼"
_SIRALAMA_ISARET_RE = re.compile(r"\s*[▲▼]\s*$")


def baslik_isaretini_temizle(baslik: str) -> str:
    return _SIRALAMA_ISARET_RE.sub("", baslik or "").rstrip()


def baslik_sirali(baslik: str, *, aktif: bool, azalan: bool) -> str:
    temiz = baslik_isaretini_temizle(baslik)
    if not aktif:
        return temiz
    return temiz + (_SIRALAMA_ISARET_AZALAN if azalan else _SIRALAMA_ISARET_ARTAN)


def tarih_coz(deger: Any) -> date | None:
    """Görünen veya ham tarih değerini date'e çevirir; boşsa None."""
    if deger is None or deger == "":
        return None
    if isinstance(deger, datetime):
        return deger.date()
    if isinstance(deger, date):
        return deger
    metin = str(deger).strip()
    if not metin:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S"):
        try:
            return datetime.strptime(metin[:19], fmt).date()
        except ValueError:
            continue
    return None


def para_coz(deger: Any) -> Decimal | None:
    """Türkçe biçimli tutarı Decimal'e çevirir (1.250,50 TL, ₺1.250,50, -100)."""
    if deger is None or deger == "":
        return None
    if isinstance(deger, Decimal):
        return deger
    if isinstance(deger, (int, float)):
        return Decimal(str(deger))
    metin = str(deger).strip()
    if not metin or metin in ("—", "-", "–"):
        return None
    metin = (
        metin.replace("₺", "")
        .replace("TL", "")
        .replace("tl", "")
        .replace("\u00a0", "")
        .replace(" ", "")
    )
    eksi = False
    if metin.startswith("(") and metin.endswith(")"):
        eksi = True
        metin = metin[1:-1]
    if metin.startswith("-"):
        eksi = True
        metin = metin[1:]
    elif metin.endswith("-"):
        eksi = True
        metin = metin[:-1]
    # Binlik ayırıcı nokta, ondalık virgül (TR)
    if "," in metin and "." in metin:
        metin = metin.replace(".", "").replace(",", ".")
    elif "," in metin:
        metin = metin.replace(",", ".")
    elif "." in metin:
        parcalar = metin.split(".")
        # 1.250 / 10.000 → binlik; 1.5 / 12.50 → ondalık
        if len(parcalar) >= 2 and all(p.isdigit() for p in parcalar):
            if len(parcalar[-1]) == 3:
                metin = "".join(parcalar)
            # aksi halde nokta ondalık ayracı olarak kalır
        else:
            metin = metin.replace(".", "")
    try:
        sayi = Decimal(metin)
    except (InvalidOperation, ValueError):
        return None
    return -sayi if eksi else sayi


def turkce_metin_anahtar(metin: Any) -> str | None:
    """Türkçe karakter duyarlı alfabetik sıralama anahtarı."""
    if metin is None:
        return None
    s = str(metin).strip()
    if not s:
        return None
    # Türkçe I/İ → küçük harf tutarlılığı
    s = s.replace("İ", "i").replace("I", "ı").casefold()
    parcalar: list[str] = []
    for ch in s:
        parcalar.append(_TR_HARF_SIRA.get(ch, f"99{ord(ch):04d}"))
    return "".join(parcalar)


def dogal_belge_anahtar(metin: Any) -> tuple | None:
    """F2 < F10 < F100 doğal (alphanumeric) sıralama."""
    if metin is None:
        return None
    s = str(metin).strip()
    if not s:
        return None
    parcalar = re.split(r"(\d+)", s)
    sonuc: list = []
    for p in parcalar:
        if not p:
            continue
        if p.isdigit():
            sonuc.append((0, int(p)))
        else:
            t = turkce_metin_anahtar(p)
            sonuc.append((1, t if t is not None else ""))
    return tuple(sonuc) if sonuc else None


def _bos_mu(anahtar: Any) -> bool:
    if anahtar is None:
        return True
    if anahtar == "":
        return True
    if isinstance(anahtar, tuple) and len(anahtar) == 0:
        return True
    return False


def liste_sirala(
    satirlar: Sequence[Any],
    *,
    anahtar_fn: Callable[[Any], Any],
    azalan: bool = False,
    ikincil_fn: Callable[[Any], Any] | None = None,
) -> list:
    """Boş değerler her zaman sonda; dolu kayıtlar artan/azalan; kararlı ikincil anahtar."""

    def _ikinci(satir: Any):
        if ikincil_fn is None:
            return ()
        try:
            return ikincil_fn(satir)
        except Exception:
            return ()

    dolu: list[tuple[Any, Any, Any]] = []
    bos: list[tuple[Any, Any]] = []
    for satir in satirlar:
        try:
            k = anahtar_fn(satir)
        except Exception:
            k = None
        ik = _ikinci(satir)
        if _bos_mu(k):
            bos.append((ik, satir))
        else:
            dolu.append((k, ik, satir))

    dolu.sort(key=lambda x: (x[0], x[1]), reverse=bool(azalan))
    # Boşlar kendi içinde ikincil anahtarla kararlı kalsın
    bos.sort(key=lambda x: x[0])
    return [s for _, _, s in dolu] + [s for _, s in bos]


def siralama_yonu_degistir(onceki_kolon: str | None, onceki_azalan: bool, yeni_kolon: str) -> tuple[str, bool]:
    """İlk tık artan; aynı sütuna ikinci tık azalan; diğerine geçişte artan."""
    if onceki_kolon == yeni_kolon:
        return yeni_kolon, (not onceki_azalan)
    return yeni_kolon, False


def treeview_basliklari_guncelle(
    tablo,
    kolonlar: Iterable[str],
    basliklar: dict[str, str],
    *,
    aktif_kolon: str | None,
    azalan: bool,
    hizalar: dict[str, str] | None = None,
    komut_fn: Callable[[str], None] | None = None,
) -> None:
    """Sütun başlıklarına ▲/▼ uygular; isteğe bağlı tıklama komutu bağlar."""
    hizalar = hizalar or {}
    for kolon in kolonlar:
        ham = basliklar.get(kolon, kolon)
        metin = baslik_sirali(ham, aktif=(kolon == aktif_kolon), azalan=azalan)
        kw: dict[str, Any] = {"text": metin}
        if kolon in hizalar:
            kw["anchor"] = hizalar[kolon]
        if komut_fn is not None:
            kw["command"] = (lambda c=kolon: komut_fn(c))
        tablo.heading(kolon, **kw)
