"""Evo banka ürün adı → üst çatı + alt hesap türü sınıflandırması.

Banka çatısını ürünün tam adından yeniden üretmez; kurum + hesap sahibi/grubunu ayırır.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def _norm(s: str) -> str:
    """Türkçe İ/I/ı güvenli normalize; birleşik işaretleri temizler."""
    s = unicodedata.normalize("NFKC", s or "")
    # casefold öncesi: İ→i, I→i (aksi halde İ.casefold() = i + combining dot)
    s = s.replace("İ", "i").replace("I", "i").replace("ı", "i")
    s = s.casefold()
    s = s.replace("ş", "s").replace("ğ", "g").replace("ü", "u").replace("ö", "o").replace("ç", "c")
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    return " ".join(s.split())


def siniflandir_urun_turu(ad: str, *, posmu: bool = False) -> str:
    """Döndürür: MEVDUAT|KMH|POS|KREDI_KARTI|KREDILER."""
    n = _norm(ad)
    # sıra önemli — çakışan ifadeler
    if "kredili mevduat" in n or re.search(r"\bkmh\b", n) or "ek hesap" in n or "avans hesap" in n:
        return "KMH"
    # kart POS tahsilatı ≠ işletmenin kredi kartı borcu
    if "kredi karti pos" in n or "pos tahsilat" in n or ("pos" in n and "tahsil" in n):
        return "POS"
    if (
        "kredi kart" in n
        or "axess" in n
        or "business kart" in n
        or ("busines" in n and "kart" in n)
        or (("troy" in n or "world" in n or "play" in n) and "kart" in n)
    ):
        return "KREDI_KARTI"
    if (
        "ticari kredi" in n
        or "taksitli kredi" in n
        or "kredi sozles" in n
        or "kredi hesab" in n
        or "esnaf kredi" in n
        or re.search(r"\bnolu\b.*\bkredi\b", n)
        or re.search(r"\bkredi\b.*\bnolu\b", n)
        or re.search(r"\bnumarali\b.*\bkredi\b", n)
        or re.search(r"\brkn\b", n)
    ):
        return "KREDILER"
    if re.search(r"\bkredi\b", n) and "kart" not in n and "pos" not in n and "mevduat" not in n:
        return "KREDILER"
    # a_posmu yalnız açık POS kelimesi yoksa ve kredi/kart kanıtı yoksa
    if posmu or re.search(r"\bpos\b", n) or "uye isyeri" in n or "sanal pos" in n:
        if "pos cihaz" in n or "pos kira" in n:
            return "MEVDUAT"  # belirsiz/cihaz — çağıran belirsiz işaretler
        return "POS"
    if "vadesiz" in n or "mevduat" in n:
        return "MEVDUAT"
    return "MEVDUAT"


def siniflandir_cati(ad: str) -> tuple[str, str]:
    """(üst_çatı_adı, sahip_grup_notu). Enpara Mehmet Can ≠ Enpara Şirketim."""
    n = _norm(ad)
    # Enpara grup ayrımı önce
    if "enpara" in n:
        # Şirket / Şirketim / şirket POS-KK → Şirketim; şahıs/Mehmet Can ayrı
        if "sirketim" in n or "sirket" in n:
            return "Enpara Şirketim", "sirketim"
        if "mehmet can" in n or "sahis" in n or "sahsi" in n:
            return "Enpara Mehmet Can", "mehmet_can"
        return "Enpara Mehmet Can", "enpara_belirsiz_grup"

    if "paytr" in n:
        return "PayTR Yapı Kredi", "paytr"
    if "purlikit" in n and "akbank" in n:
        return "Purlikit Akbank", "purlikit"
    if "ronesans" in n or "hisse" in n:
        return "Rönesans Holding Hisse", "hisse"
    if "rsc world" in n or "rs c world" in n or n.startswith("rsc "):
        return "RSÇ World", "rsc"

    if "akbank" in n:
        return "Akbank", "akbank"
    if "yapi kredi" in n or "yapikredi" in n or "yapi kred" in n:
        return "Yapı Kredi", "yapi_kredi"
    if "denizbank" in n or "deniz bank" in n:
        return "Denizbank", "denizbank"
    if "halkbank" in n or "halk bank" in n:
        return "Halkbank", "halkbank"
    if "vakifbank" in n or "vakif bank" in n:
        return "Vakıfbank", "vakifbank"
    if "kuveyt" in n:
        return "Kuveyt Türk", "kuveyt"
    if re.search(r"\bqnb\b", n) or "finansbank" in n:
        return "QNB", "qnb"
    if "ziraat" in n:
        return "Ziraat Bankası", "ziraat"
    if "garanti" in n:
        return "Garanti BBVA", "garanti"
    if "is bank" in n or "isbank" in n:
        return "İş Bankası", "isbank"

    # bilinmeyen — ürün adının kendisini çatı yapma; kısa kurum tahmini
    return ad.strip()[:60] or "Bilinmeyen Banka", "bilinmeyen"


def siniflandir_evo_satir(satir: dict[str, Any]) -> dict[str, Any]:
    ad = str(satir.get("text") or satir.get("a_adi") or satir.get("banka_adi") or "")
    posmu = str(satir.get("a_posmu") or "") in {"1", "true", "True", "E", "e"}
    cati, grup = siniflandir_cati(ad)
    tur = siniflandir_urun_turu(ad, posmu=posmu)
    # POS cihaz kirası özel
    n = _norm(ad)
    belirsiz = False
    if "pos cihaz" in n or "pos kira" in n:
        belirsiz = True
        tur = "MEVDUAT"
    if grup in {"enpara_belirsiz_grup", "bilinmeyen"}:
        belirsiz = True
    return {
        "cati": cati,
        "grup": grup,
        "urun_turu": tur,
        "urun_adi": ad.strip()[:100],
        "belirsiz": belirsiz,
        "posmu": posmu,
    }
