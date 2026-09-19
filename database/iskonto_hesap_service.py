"""Üç kademeli (ardışık) iskonto ve net birim fiyat — ortak hesap motoru.

Satış ve alış faturaları aynı formülleri kullanır; float kullanılmaz.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from database.satis_siparisi_service import decimal

_KURUS = Decimal("0.01")
_YUZ = Decimal("100")
_BIR = Decimal("1")


def _oran(deger, alan: str = "İskonto") -> Decimal:
    o = decimal(deger if deger not in (None, "") else 0, alan, Decimal("0"))
    if o < 0 or o > _YUZ:
        raise ValueError(f"{alan} 0-100 arasında olmalıdır.")
    return o


def iskonto_oranlarini_dogrula(iskonto1=0, iskonto2=0, iskonto3=0) -> tuple[Decimal, Decimal, Decimal]:
    return (
        _oran(iskonto1, "1. İskonto"),
        _oran(iskonto2, "2. İskonto"),
        _oran(iskonto3, "3. İskonto"),
    )


def iskonto_carpani(iskonto1=0, iskonto2=0, iskonto3=0) -> Decimal:
    """(1-i1/100)×(1-i2/100)×(1-i3/100)."""
    i1, i2, i3 = iskonto_oranlarini_dogrula(iskonto1, iskonto2, iskonto3)
    carp = _BIR
    for o in (i1, i2, i3):
        carp *= _BIR - o / _YUZ
    return carp


def etkili_iskonto_orani(iskonto1=0, iskonto2=0, iskonto3=0) -> Decimal:
    """100 × [1 − çarpan]. Örn. %10+%5+%2 → %16,21 (toplanmaz)."""
    carp = iskonto_carpani(iskonto1, iskonto2, iskonto3)
    return (_YUZ * (_BIR - carp)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def yuvarla_kurus(tutar, yon: str = "normal") -> Decimal:
    """Belge motoru ile uyumlu kuruş yuvarlama (varsayılan HALF_UP)."""
    d = Decimal(str(tutar or 0))
    if yon == "asagi":
        return d.quantize(_KURUS, rounding="ROUND_DOWN")
    if yon == "yukari":
        return d.quantize(_KURUS, rounding="ROUND_UP")
    return d.quantize(_KURUS, rounding=ROUND_HALF_UP)


def satir_net_brut_indirim(miktar, brut_birim_fiyat, iskonto1=0, iskonto2=0, iskonto3=0):
    """Satır brüt, toplam iskonto tutarı, iskonto sonrası (KDV öncesi) satır tutarı."""
    miktar_d = decimal(miktar or 0, "Miktar", Decimal("0"))
    fiyat_d = decimal(brut_birim_fiyat or 0, "Birim fiyat", Decimal("0"))
    brut = miktar_d * fiyat_d
    carp = iskonto_carpani(iskonto1, iskonto2, iskonto3)
    net = brut * carp
    return brut, brut - net, net


def satir_iskonto_hesapla(
    *,
    miktar,
    brut_birim_fiyat,
    iskonto1=0,
    iskonto2=0,
    iskonto3=0,
    kdv_orani=0,
    kdv_dahil: bool = False,
    yuvarlama_yon: str = "normal",
) -> dict[str, Any]:
    """Tam satır sonucu.

    kdv_dahil=False (varsayılan): brüt birim KDV hariç kabul edilir.
      iskonto_sonrasi_birim = brut × çarpan
      net_birim_fiyat = iskonto_sonrasi_birim × (1 + KDV/100)
      net_tutar = miktar × net_birim_fiyat

    kdv_dahil=True: brüt birim KDV dahil kabul edilir; matrah ayrıştırılır,
    KDV ikinci kez eklenmez.
    """
    i1, i2, i3 = iskonto_oranlarini_dogrula(iskonto1, iskonto2, iskonto3)
    miktar_d = decimal(miktar or 0, "Miktar", Decimal("0"))
    brut_birim = decimal(brut_birim_fiyat or 0, "Birim fiyat", Decimal("0"))
    kdv = _oran(kdv_orani, "KDV")
    carp = iskonto_carpani(i1, i2, i3)
    etkili = etkili_iskonto_orani(i1, i2, i3)

    if kdv_dahil:
        # Dahil fiyattan iskonto → kalan KDV dahil; matrah = net_dahil / (1+kdv)
        dahil_birim = brut_birim * carp
        if kdv > 0:
            matrah_birim = dahil_birim / (_BIR + kdv / _YUZ)
        else:
            matrah_birim = dahil_birim
        iskonto_sonrasi_birim = matrah_birim
        net_birim = dahil_birim
        brut_satir = miktar_d * brut_birim
        iskonto_sonrasi_satir = miktar_d * matrah_birim
        iskonto_tutari = brut_satir - (miktar_d * dahil_birim)
        # Brüt KDV dahil olduğu için iskonto tutarı dahil bazda; matrah farkı ayrıca
        iskonto_tutari = miktar_d * brut_birim * (_BIR - carp)
        kdv_tutari = miktar_d * (dahil_birim - matrah_birim)
        net_tutar = miktar_d * net_birim
        brut_kdv_haric = miktar_d * (brut_birim / (_BIR + kdv / _YUZ) if kdv > 0 else brut_birim)
    else:
        iskonto_sonrasi_birim = brut_birim * carp
        net_birim = iskonto_sonrasi_birim * (_BIR + kdv / _YUZ)
        brut_satir = miktar_d * brut_birim
        iskonto_sonrasi_satir = miktar_d * iskonto_sonrasi_birim
        iskonto_tutari = brut_satir - iskonto_sonrasi_satir
        kdv_tutari = iskonto_sonrasi_satir * (kdv / _YUZ)
        net_tutar = miktar_d * net_birim
        brut_kdv_haric = brut_satir

    return {
        "iskonto_1_orani": i1,
        "iskonto_2_orani": i2,
        "iskonto_3_orani": i3,
        "etkili_iskonto_orani": etkili,
        "iskonto_carpani": carp,
        "brut_birim_fiyat": brut_birim,
        "brut_satir": yuvarla_kurus(brut_kdv_haric if not kdv_dahil else brut_satir, yuvarlama_yon),
        "iskonto_tutari": yuvarla_kurus(iskonto_tutari, yuvarlama_yon),
        "iskonto_sonrasi_birim_fiyat": yuvarla_kurus(iskonto_sonrasi_birim, yuvarlama_yon),
        "iskonto_sonrasi_satir": yuvarla_kurus(iskonto_sonrasi_satir, yuvarlama_yon),
        "kdv_orani": kdv,
        "kdv_tutari": yuvarla_kurus(kdv_tutari, yuvarlama_yon),
        "net_birim_fiyat": yuvarla_kurus(net_birim, yuvarlama_yon),
        "net_tutar": yuvarla_kurus(net_tutar, yuvarlama_yon),
        "kdv_dahil": bool(kdv_dahil),
    }


def iskonto_oran_metin(deger) -> str:
    """Oranı Entry için metne çevir; 10→1 kırpma YOK (rstrip('0') kullanılmaz)."""
    try:
        o = decimal(deger if deger not in (None, "") else 0, "İskonto", Decimal("0"))
    except ValueError:
        o = Decimal("0")
    if o == o.to_integral_value():
        return str(int(o))
    # Ondalıklı: yalnızca gereksiz sondaki sıfırları at
    s = format(o, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def iskonto_goster_metin(iskonto1=0, iskonto2=0, iskonto3=0, *, bos_goster: str = "") -> str:
    """Üç oran → '%10 + %5 + %2'; tek oran → '%10'; yoksa boş veya '%0'."""
    try:
        oranlar = list(iskonto_oranlarini_dogrula(iskonto1, iskonto2, iskonto3))
    except ValueError:
        oranlar = [Decimal("0"), Decimal("0"), Decimal("0")]
    dolu = [o for o in oranlar if o > 0]
    if not dolu:
        return bos_goster
    return " + ".join(f"%{iskonto_oran_metin(o)}" for o in dolu)


def iskonto_ipucu(
    *,
    miktar,
    brut_birim_fiyat,
    iskonto1=0,
    iskonto2=0,
    iskonto3=0,
    kdv_orani=0,
) -> str:
    h = satir_iskonto_hesapla(
        miktar=miktar,
        brut_birim_fiyat=brut_birim_fiyat,
        iskonto1=iskonto1,
        iskonto2=iskonto2,
        iskonto3=iskonto3,
        kdv_orani=kdv_orani,
    )
    oranlar = iskonto_goster_metin(iskonto1, iskonto2, iskonto3, bos_goster="%0")
    return (
        f"İskontolar: {oranlar}\n"
        f"Etkili iskonto: %{h['etkili_iskonto_orani']}\n"
        f"İskonto tutarı: {h['iskonto_tutari']}\n"
        f"İskonto sonrası birim: {h['iskonto_sonrasi_birim_fiyat']}"
    )
