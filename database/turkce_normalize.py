"""Türkçe karakter duyarsız metin normalizasyonu (yalnız arama amaçlı)."""

from __future__ import annotations

# Arama için katlanmış biçim: İ/I/ı → i, Ş→s, Ğ→g, Ü→u, Ö→o, Ç→c
_TR_FOLD = str.maketrans(
    {
        "İ": "i",
        "I": "i",
        "ı": "i",
        "i": "i",
        "Ş": "s",
        "ş": "s",
        "Ğ": "g",
        "ğ": "g",
        "Ü": "u",
        "ü": "u",
        "Ö": "o",
        "ö": "o",
        "Ç": "c",
        "ç": "c",
    }
)

# SQL LIKE için tek konum genişletmeleri (parametreli sorguda kullanılır)
_EXPAND: dict[str, tuple[str, ...]] = {
    "c": ("c", "ç", "Ç", "C"),
    "ç": ("c", "ç", "Ç", "C"),
    "g": ("g", "ğ", "Ğ", "G"),
    "ğ": ("g", "ğ", "Ğ", "G"),
    "i": ("i", "ı", "İ", "I"),
    "ı": ("i", "ı", "İ", "I"),
    "o": ("o", "ö", "Ö", "O"),
    "ö": ("o", "ö", "Ö", "O"),
    "s": ("s", "ş", "Ş", "S"),
    "ş": ("s", "ş", "Ş", "S"),
    "u": ("u", "ü", "Ü", "U"),
    "ü": ("u", "ü", "Ü", "U"),
}


def turkce_normalize(metin: str | None) -> str:
    """Büyük/küçük ve Türkçe karakter farklarını yok sayan arama anahtarı."""
    if not metin:
        return ""
    return str(metin).translate(_TR_FOLD).casefold()


def arama_like_varyantlari(metin: str, max_n: int = 20) -> list[str]:
    """Parametreli LIKE için %varyant% kalıpları (Türkçe harf alternatifleri)."""
    q = (metin or "").strip()
    if not q:
        return []
    adaylar: set[str] = {q, q.lower(), q.upper(), q.casefold(), turkce_normalize(q)}
    # Her konumda tek harf genişletmesi
    for i, ch in enumerate(q):
        alts = _EXPAND.get(ch) or _EXPAND.get(ch.casefold())
        if not alts:
            continue
        for a in alts:
            adaylar.add(q[:i] + a + q[i + 1 :])
    # Normalize edilmiş metinde de tek konum genişlet
    nq = turkce_normalize(q)
    for i, ch in enumerate(nq):
        alts = _EXPAND.get(ch)
        if not alts:
            continue
        for a in alts:
            adaylar.add(nq[:i] + a + nq[i + 1 :])
    out: list[str] = []
    seen: set[str] = set()
    for a in adaylar:
        a = (a or "").strip()
        if not a or a in seen:
            continue
        seen.add(a)
        out.append(f"%{a}%")
        if len(out) >= max_n:
            break
    return out


def kelime_basi_eslesme(alan: str, arama: str) -> bool:
    """Normalize edilmiş alanda kelime başı eşleşmesi."""
    n_alan = turkce_normalize(alan)
    n_ara = turkce_normalize(arama)
    if not n_ara or not n_alan:
        return False
    if n_alan.startswith(n_ara):
        return True
    for parca in n_alan.replace("-", " ").replace("/", " ").split():
        if parca.startswith(n_ara):
            return True
    return False
