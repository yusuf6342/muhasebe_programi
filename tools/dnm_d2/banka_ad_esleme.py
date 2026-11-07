"""Banka adından bölüm eşleme kuralları (D2 Word §09) — yazım yok; önizleme.

Kredi kartı ifadesi «kredi» sözcüğünden önce değerlendirilir.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def _norm(ad: str) -> str:
    s = unicodedata.normalize("NFKC", ad or "")
    s = s.replace("İ", "I").replace("ı", "i")
    s = s.upper()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def banka_cati(ad: str) -> str:
    n = _norm(ad)
    if "ENPARA" in n and "SAHIS" in n.replace("Ş", "S"):
        return "Enpara Şahıs"
    if "ENPARA" in n and ("SIRKET" in n.replace("Ş", "S") or "ŞİRKET" in ad.upper()):
        return "Enpara Şirket"
    if "ENPARA" in n:
        # sahiplik belirsiz — inceleme
        if "ŞAHIS" in ad.upper() or "SAHIS" in n:
            return "Enpara Şahıs"
        if "ŞİRKET" in ad.upper() or "SIRKET" in n:
            return "Enpara Şirket"
        return "Enpara (sahiplik incele)"
    if "AKBANK" in n:
        return "Akbank"
    if "YAPI KREDI" in n or "YAPIKREDI" in n.replace(" ", "") or "YAPI KREDİ" in ad.upper():
        return "Yapı Kredi"
    if "VAKIF" in n:
        return "Vakıfbank"
    if "HALKBANK" in n or "HALK BANK" in n:
        return "Halkbank"
    if "IS BANK" in n or "İŞ BANK" in ad.upper() or "ISBANK" in n.replace(" ", ""):
        return "İş Bankası"
    if "PAYTR" in n:
        return "PayTR aracı (çatı banka adı değil)"
    return "Diğer / inceleme"


def banka_bolum_oner(ad: str) -> dict[str, Any]:
    n = _norm(ad)
    cati = banka_cati(ad)
    # Sıra: kredi kartı → KMH → POS → kredi → vadeli/mevduat → yatırım
    if "KREDI KART" in n.replace("İ", "I") or "KREDİ KART" in ad.upper():
        bolum = "Kredi Kartları"
        kural = "KREDİ KARTI ifadesi → Kredi Kartları (Krediler değil)"
    elif re.search(r"\bKMH\b", n) or "KREDILI MEVDUAT" in n or "KREDİLİ MEVDUAT" in ad.upper():
        bolum = "KMH"
        kural = "KMH / kredili mevduat"
    elif "POS" in n or "SANAL POS" in n:
        bolum = "POS"
        kural = "POS / sanal POS — bağlı mevduat ayrı"
    elif re.search(r"\bKREDI\b", n) or "TİCARİ KREDİ" in ad.upper() or "TAKSİTLİ KREDİ" in ad.upper():
        bolum = "Krediler"
        kural = "Kredi (kart/KMH elendikten sonra)"
    elif "YATIRIM" in n or "MENKUL" in n or "HISSE" in n or " FON" in f" {n}":
        bolum = "Yatırım"
        kural = "Yatırım / menkul"
    elif "VADELI" in n or "VADESIZ" in n or "MEVDUAT" in n:
        bolum = "Mevduat"
        kural = "Vadeli/vadesiz/mevduat"
    else:
        bolum = "İnceleme"
        kural = "Belirsiz ad — yapılandırılmış tür olmadan yazılmaz"
    return {
        "ozgun_ad": ad,
        "normalize": n,
        "cati": cati,
        "bolum": bolum,
        "kural": kural,
        "yazim_yok": True,
    }
