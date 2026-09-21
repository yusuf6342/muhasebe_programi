"""Fatura geneli Brüt / Net / İndirim-Masraf hesaplama (Decimal).

calculated_gross_total  = satırlardan güncel KDV-dahil toplam
locked_gross_total      = kullanıcı/dağıtım ile sabitlenen referans Brüt
target_net_total        = yuvarlama veya elle verilen Net hedefi
gross_lock_active       = True iken ekran Brüt = locked; işlem hedefe göre türetilir

Muhasebe nihai tutarı = Net (tl_genel_toplam).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

KURUS = Decimal("0.01")
ORAN_HAS = Decimal("0.0001")

ISLEM_INDIRIM = "INDIRIM"
ISLEM_MASRAF = "MASRAF"
ISLEM_YOK = ""

# Dağıtım aktifken satır değişikliği seçimleri
SECIM_HEDEF_KORU = "hedef_koru"
SECIM_HEDEFE_EKLE = "hedefe_ekle"
SECIM_DAGITIM_IPTAL = "dagitim_iptal"

# Alan adları (UI/DB eşlemesi — geriye uyumlu)
# calculated_gross_total → satır KDV-dahil / _calculated_gross_total
# locked_gross_total     → tl_brut_toplam / _locked_gross_total / _dagitim_oncesi_brut
# invoice_adjustment_*   → genel_islem_turu / orani / tutari
# target_net_total       → _hedef_net_toplam (kayıtta tl_genel_toplam)
# gross_lock_active      → kilit; ekran Brüt = locked


def _d(deger, varsayilan: Decimal = Decimal("0")) -> Decimal:
    if deger is None or deger == "":
        return varsayilan
    if isinstance(deger, Decimal):
        return deger
    ham = str(deger).strip().replace("✦", "").replace("TL", "").replace("tl", "").strip()
    if not ham:
        return varsayilan
    if "," in ham and "." in ham:
        if ham.rfind(",") > ham.rfind("."):
            ham = ham.replace(".", "").replace(",", ".")
        else:
            ham = ham.replace(",", "")
    elif "," in ham:
        ham = ham.replace(".", "").replace(",", ".")
    try:
        return Decimal(ham)
    except Exception:
        return varsayilan


def kurus(tutar) -> Decimal:
    return _d(tutar).quantize(KURUS, rounding=ROUND_HALF_UP)


def oran_yuvarla(oran) -> Decimal:
    return _d(oran).quantize(ORAN_HAS, rounding=ROUND_HALF_UP)


def islem_turunu_normalize(tur: str | None) -> str:
    t = (tur or "").strip().upper()
    if t in ("INDIRIM", "İNDİRİM", "IND", "DISC", "DISCOUNT"):
        return ISLEM_INDIRIM
    if t in ("MASRAF", "EK", "EXPENSE", "SURCHARGE"):
        return ISLEM_MASRAF
    return ISLEM_YOK


def tutardan_oran(brut: Decimal, tutar: Decimal) -> Decimal:
    b = kurus(brut)
    if b <= 0:
        return oran_yuvarla(0)
    return oran_yuvarla(_d(tutar) / b * Decimal("100"))


def orandan_tutar(brut: Decimal, oran: Decimal) -> Decimal:
    b = kurus(brut)
    if b <= 0:
        return kurus(0)
    return kurus(b * _d(oran) / Decimal("100"))


def net_hesapla(brut: Decimal, islem_turu: str | None, islem_tutari: Decimal) -> Decimal:
    b = kurus(brut)
    t = kurus(islem_tutari)
    tur = islem_turunu_normalize(islem_turu)
    if tur == ISLEM_INDIRIM:
        return kurus(max(Decimal("0"), b - t))
    if tur == ISLEM_MASRAF:
        return kurus(b + t)
    return b


def netten_islem(brut: Decimal, net: Decimal) -> dict[str, Any]:
    """Hedef net ile referans brüt farkından tür / tutar / oran üret."""
    b = kurus(brut)
    n = kurus(net)
    if n < 0:
        raise ValueError("Net toplam negatif olamaz.")
    if b <= 0:
        return {
            "brut_toplam": b,
            "islem_turu": ISLEM_YOK,
            "islem_orani": oran_yuvarla(0),
            "islem_tutari": kurus(0),
            "net_toplam": kurus(0),
        }
    fark = kurus(n - b)
    if fark == 0:
        return {
            "brut_toplam": b,
            "islem_turu": ISLEM_YOK,
            "islem_orani": oran_yuvarla(0),
            "islem_tutari": kurus(0),
            "net_toplam": b,
        }
    if fark < 0:
        tutar = kurus(-fark)
        if tutar > b:
            raise ValueError("İndirim tutarı brüt toplamı aşamaz.")
        return {
            "brut_toplam": b,
            "islem_turu": ISLEM_INDIRIM,
            "islem_orani": tutardan_oran(b, tutar),
            "islem_tutari": tutar,
            "net_toplam": kurus(b - tutar),
        }
    tutar = fark
    return {
        "brut_toplam": b,
        "islem_turu": ISLEM_MASRAF,
        "islem_orani": tutardan_oran(b, tutar),
        "islem_tutari": tutar,
        "net_toplam": kurus(b + tutar),
    }


def islem_uygula(
    brut: Decimal,
    *,
    islem_turu: str | None = None,
    islem_orani: Decimal | None = None,
    islem_tutari: Decimal | None = None,
    kaynak: str = "tutar",
) -> dict[str, Any]:
    """Oran veya tutardan net üret. kaynak: 'oran' | 'tutar' | 'tur'."""
    b = kurus(brut)
    tur = islem_turunu_normalize(islem_turu)
    if tur == ISLEM_YOK or b <= 0:
        return {
            "brut_toplam": b,
            "islem_turu": ISLEM_YOK,
            "islem_orani": oran_yuvarla(0),
            "islem_tutari": kurus(0),
            "net_toplam": b,
        }
    oran = oran_yuvarla(islem_orani or 0)
    tutar = kurus(islem_tutari or 0)
    if kaynak == "oran":
        if oran < 0:
            raise ValueError("İşlem oranı negatif olamaz.")
        tutar = orandan_tutar(b, oran)
    else:
        if tutar < 0:
            raise ValueError("İşlem tutarı negatif olamaz.")
        oran = tutardan_oran(b, tutar)
    if tur == ISLEM_INDIRIM and tutar > b:
        raise ValueError("İndirim tutarı brüt toplamı aşamaz.")
    net = net_hesapla(b, tur, tutar)
    if tutar == 0 and oran == 0:
        tur = ISLEM_YOK
    return {
        "brut_toplam": b,
        "islem_turu": tur,
        "islem_orani": oran,
        "islem_tutari": tutar,
        "net_toplam": net,
    }


def satir_genelinden_brut(satir_genel_toplam: Decimal) -> Decimal:
    """Satır motorundan gelen genel_toplam = Brüt Toplam."""
    return kurus(satir_genel_toplam)


def eski_kayit_normalize(
    *,
    tl_genel_toplam: Decimal | None = None,
    tl_brut_toplam: Decimal | None = None,
    genel_islem_turu: str | None = None,
    genel_islem_orani: Decimal | None = None,
    genel_islem_tutari: Decimal | None = None,
) -> dict[str, Any]:
    """Eski faturalar: brüt=net=tl_genel_toplam, işlem yok."""
    net = kurus(tl_genel_toplam or 0)
    brut = kurus(tl_brut_toplam) if tl_brut_toplam is not None else net
    tur = islem_turunu_normalize(genel_islem_turu)
    oran = oran_yuvarla(genel_islem_orani or 0)
    tutar = kurus(genel_islem_tutari or 0)
    if tur == ISLEM_YOK and tutar == 0 and oran == 0:
        brut = net
    return {
        "brut_toplam": brut,
        "islem_turu": tur,
        "islem_orani": oran,
        "islem_tutari": tutar,
        "net_toplam": net if tur == ISLEM_YOK else net_hesapla(brut, tur, tutar),
    }


def calculated_gross_guncelle(
    *,
    satir_net_toplam: Decimal,
    dagitim_uygulandi: bool = False,
    dagitim_oncesi_brut: Decimal | None = None,
    hedef_net: Decimal | None = None,
) -> Decimal:
    """Satırlardan güncel calculated_gross (KDV Matrahı + KDV).

    Her çağrıda sıfırdan üretilir. Kilit/sabit brüt bu fonksiyonda tutulmaz;
    ``referans_brut_al`` / ``fatura_toplam_durumu`` kilit mantığını uygular.
    """
    _ = (dagitim_uygulandi, dagitim_oncesi_brut, hedef_net)
    return kurus(satir_net_toplam)


def referans_brut_al(
    *,
    calculated_gross_total: Decimal,
    gross_lock_active: bool = False,
    locked_gross_total: Decimal | None = None,
) -> Decimal:
    """Kilit açıksa sabit brüt; değilse satırlardan hesaplanan brüt."""
    if gross_lock_active and locked_gross_total is not None:
        return kurus(locked_gross_total)
    return kurus(calculated_gross_total)


def kdv_brut_net_satir_saglama(
    *,
    kdv_matrahi: Decimal,
    kdv_toplami: Decimal,
    brut_toplam: Decimal,
    islem_turu: str | None,
    islem_tutari: Decimal,
    net_toplam: Decimal,
    tolerans: Decimal = KURUS,
    gross_lock_active: bool = False,
    calculated_gross_total: Decimal | None = None,
) -> dict[str, Any]:
    """KDV Matrahı + KDV = calculated gross; referans Brüt ± işlem = Net.

    Kilit açıksa Matrah+KDV, ekrandaki sabit Brüt ile değil calculated_gross
    ile karşılaştırılır (KDV değişince satır toplamı güncellenir, kilit bozulmaz).
    """
    sorunlar: list[str] = []
    matrah = kurus(kdv_matrahi)
    kdv = kurus(kdv_toplami)
    brut = kurus(brut_toplam)
    net = kurus(net_toplam)
    beklenen_brut = kurus(matrah + kdv)
    karsilastir = (
        kurus(calculated_gross_total)
        if gross_lock_active and calculated_gross_total is not None
        else brut
    )
    if abs(beklenen_brut - karsilastir) > tolerans:
        sorunlar.append(
            f"Satır Brüt ({karsilastir}) ≠ KDV Matrahı ({matrah}) + KDV ({kdv}); "
            f"beklenen {beklenen_brut}"
        )
    beklenen_net = net_hesapla(brut, islem_turu, islem_tutari)
    if abs(beklenen_net - net) > tolerans:
        sorunlar.append(
            f"Net Toplam ({net}) ≠ Brüt ({brut}) ± işlem; beklenen {beklenen_net}"
        )
    return {"ok": len(sorunlar) == 0, "sorunlar": sorunlar}


def fatura_toplam_durumu(
    *,
    satir_net_toplam: Decimal,
    dagitim_uygulandi: bool = False,
    dagitim_oncesi_brut: Decimal | None = None,
    hedef_net: Decimal | None = None,
    islem_turu: str | None = None,
    islem_orani: Decimal | None = None,
    islem_tutari: Decimal | None = None,
    islem_kaynak: str = "tutar",
    gross_lock_active: bool | None = None,
    locked_gross_total: Decimal | None = None,
    target_net_total: Decimal | None = None,
) -> dict[str, Any]:
    """Ortak Brüt / Net / işlem hesabı (satış + alış).

    - calculated_gross her zaman satırlardan.
    - Kilit açıksa ekran Brüt = locked_gross; işlem hedef net'ten türetilir.
    - Kilit kapalıysa Brüt = calculated; işlem oran/tutar kaynaklı uygulanır.
    """
    calculated = calculated_gross_guncelle(satir_net_toplam=satir_net_toplam)

    locked = locked_gross_total
    if locked is None and dagitim_oncesi_brut is not None:
        locked = dagitim_oncesi_brut

    hedef = target_net_total if target_net_total is not None else hedef_net

    # Kilit: UI açıkça söylerse; yoksa dağıtım + sabit brüt; yoksa hedef≠sabit brüt
    if gross_lock_active is not None:
        lock = bool(gross_lock_active)
    elif dagitim_uygulandi and locked is not None:
        lock = True
    elif (
        locked is not None
        and hedef is not None
        and abs(kurus(locked) - kurus(hedef)) > KURUS
    ):
        lock = True
    else:
        lock = False

    referans = referans_brut_al(
        calculated_gross_total=calculated,
        gross_lock_active=lock,
        locked_gross_total=locked,
    )

    if lock and hedef is not None:
        try:
            iz = netten_islem(referans, kurus(hedef))
        except ValueError:
            iz = {
                "brut_toplam": referans,
                "islem_turu": islem_turunu_normalize(islem_turu),
                "islem_orani": oran_yuvarla(islem_orani or 0),
                "islem_tutari": kurus(islem_tutari or 0),
                "net_toplam": kurus(hedef),
            }
        return {
            "calculated_gross_total": calculated,
            "locked_gross_total": kurus(locked) if locked is not None else referans,
            "gross_lock_active": True,
            "brut_toplam": referans,
            "invoice_adjustment_amount": iz["islem_tutari"],
            "target_net_total": kurus(hedef),
            "net_total": iz["net_toplam"],
            "islem_turu": iz["islem_turu"],
            "islem_orani": iz["islem_orani"],
            "islem_tutari": iz["islem_tutari"],
            "hedef_sapma": kurus(calculated - kurus(hedef)),
        }

    if lock:
        # Kilit var, hedef yok → işlem alanlarından net üret (referans = locked)
        try:
            sonuc = islem_uygula(
                referans,
                islem_turu=islem_turu,
                islem_orani=islem_orani,
                islem_tutari=islem_tutari,
                kaynak=islem_kaynak or "tutar",
            )
        except ValueError:
            sonuc = {
                "brut_toplam": referans,
                "islem_turu": ISLEM_YOK,
                "islem_orani": oran_yuvarla(0),
                "islem_tutari": kurus(0),
                "net_toplam": referans,
            }
        return {
            "calculated_gross_total": calculated,
            "locked_gross_total": kurus(locked) if locked is not None else referans,
            "gross_lock_active": True,
            "brut_toplam": sonuc["brut_toplam"],
            "invoice_adjustment_amount": sonuc["islem_tutari"],
            "target_net_total": sonuc["net_toplam"],
            "net_total": sonuc["net_toplam"],
            "islem_turu": sonuc["islem_turu"],
            "islem_orani": sonuc["islem_orani"],
            "islem_tutari": sonuc["islem_tutari"],
            "hedef_sapma": kurus(calculated - sonuc["net_toplam"]),
        }

    # Kilit kapalı: normal satır brütü + işlem
    try:
        sonuc = islem_uygula(
            calculated,
            islem_turu=islem_turu,
            islem_orani=islem_orani,
            islem_tutari=islem_tutari,
            kaynak=islem_kaynak or "tutar",
        )
    except ValueError:
        sonuc = {
            "brut_toplam": calculated,
            "islem_turu": ISLEM_YOK,
            "islem_orani": oran_yuvarla(0),
            "islem_tutari": kurus(0),
            "net_toplam": calculated,
        }
    return {
        "calculated_gross_total": calculated,
        "locked_gross_total": None,
        "gross_lock_active": False,
        "brut_toplam": sonuc["brut_toplam"],
        "invoice_adjustment_amount": sonuc["islem_tutari"],
        "target_net_total": None,
        "net_total": sonuc["net_toplam"],
        "islem_turu": sonuc["islem_turu"],
        "islem_orani": sonuc["islem_orani"],
        "islem_tutari": sonuc["islem_tutari"],
        "hedef_sapma": kurus(0),
    }


def brut_net_esitlik_saglama(
    *,
    brut: Decimal,
    islem_turu: str | None,
    islem_tutari: Decimal,
    net: Decimal,
    satir_net: Decimal,
    tolerans: Decimal = KURUS,
) -> dict[str, Any]:
    """Kayıt öncesi: Net = Brüt + Masraf − İndirim; |satır − net| ≤ 0,01."""
    sorunlar: list[str] = []
    b = kurus(brut)
    n = kurus(net)
    s = kurus(satir_net)
    t = kurus(islem_tutari)
    tur = islem_turunu_normalize(islem_turu)
    beklenen = net_hesapla(b, tur, t)
    if abs(beklenen - n) > tolerans:
        sorunlar.append(
            f"Net Toplam ({n}) ≠ Brüt ({b}) ± işlem ({tur or 'yok'}, {t}); "
            f"beklenen {beklenen}"
        )
    if abs(s - n) > tolerans:
        sorunlar.append(
            f"Dağıtılmış satır toplamı ({s}) ile Net Toplam ({n}) arasında "
            f"{kurus(s - n)} TL fark var (izin ≤ {tolerans}). "
            "Brüt veya Net güncel değil; Fiyatlara Dağıt / Geri Al kullanın."
        )
    return {
        "ok": len(sorunlar) == 0,
        "sorunlar": sorunlar,
        "beklenen_net": beklenen,
        "fark_satir_net": kurus(s - n),
    }
