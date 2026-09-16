"""Para tutarını Türkçe yazıya çevirir (test edilebilir)."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

_BIRLER = (
    "",
    "Bir",
    "İki",
    "Üç",
    "Dört",
    "Beş",
    "Altı",
    "Yedi",
    "Sekiz",
    "Dokuz",
)
_ONLAR = (
    "",
    "On",
    "Yirmi",
    "Otuz",
    "Kırk",
    "Elli",
    "Altmış",
    "Yetmiş",
    "Seksen",
    "Doksan",
)
_BINLIK = (
    "",
    "Bin",
    "Milyon",
    "Milyar",
    "Trilyon",
    "Katrilyon",
)

_PB = {
    "TRY": ("Türk Lirası", "Kuruş"),
    "TL": ("Türk Lirası", "Kuruş"),
    "USD": ("Amerikan Doları", "Cent"),
    "EUR": ("Euro", "Cent"),
    "GBP": ("İngiliz Sterlini", "Penny"),
}


def _uc_hane(n: int) -> str:
    if n <= 0:
        return ""
    yuz = n // 100
    on = (n % 100) // 10
    bir = n % 10
    parca: list[str] = []
    if yuz:
        if yuz == 1:
            parca.append("Yüz")
        else:
            parca.append(f"{_BIRLER[yuz]} Yüz")
    if on:
        parca.append(_ONLAR[on])
    if bir:
        parca.append(_BIRLER[bir])
    return " ".join(parca)


def _tam_sayi_yazi(n: int) -> str:
    if n == 0:
        return "Sıfır"
    if n < 0:
        return "Eksi " + _tam_sayi_yazi(-n)
    parcalar: list[str] = []
    grup = 0
    while n > 0:
        uc = n % 1000
        if uc:
            if grup == 1 and uc == 1:
                metin = "Bin"
            else:
                metin = _uc_hane(uc)
                if _BINLIK[grup]:
                    metin = f"{metin} {_BINLIK[grup]}".strip()
            parcalar.append(metin)
        n //= 1000
        grup += 1
    return " ".join(reversed(parcalar))


def amount_to_words(
    amount,
    currency: str = "TRY",
    *,
    sifir_kurus_gizle: bool = True,
    iade: bool = False,
) -> str:
    """Örn: 'Yalnız Bin İki Yüz Otuz Dört Türk Lirası Elli Altı Kuruştur.'"""
    d = Decimal(str(amount or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    negatif = d < 0 or iade
    d = abs(d)
    tam = int(d)
    kurus = int((d - tam) * 100)
    pb = (currency or "TRY").upper()
    ana, alt = _PB.get(pb, (pb, "Kuruş"))
    yazi = _tam_sayi_yazi(tam)
    if kurus and not (sifir_kurus_gizle and kurus == 0):
        govde = f"{yazi} {ana} {_tam_sayi_yazi(kurus)} {alt}"
    elif kurus:
        govde = f"{yazi} {ana} {_tam_sayi_yazi(kurus)} {alt}"
    else:
        govde = f"{yazi} {ana}"
    if negatif:
        govde = f"Eksi {govde}"
    return f"Yalnız {govde}tur."
