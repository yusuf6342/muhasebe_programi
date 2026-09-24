"""Uzlaşılan tutar → fatura Net; farkı satır birim fiyatlarına orantılı dağıtır."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable

from database.fatura_genel_toplam_service import kurus, oran_yuvarla, tutardan_oran

FIYAT_HAS = Decimal("0.0001")


def uzlasilan_indirim_masraf(brut, uzlasilan) -> dict[str, Any]:
    """Brüt ile uzlaşılan farkından hem İndirim hem Masraf (biri genelde 0).

    Net her zaman uzlaşılan tutara yuvarlanır (kuruş farkı kapanır).
    Fiyat dağıtımı sonrası brüt≈net olduğunda ikisi de 0 kalır.
    """
    b = kurus(brut)
    if uzlasilan is None or uzlasilan == "":
        return {
            "brut": b,
            "indirim_tutari": kurus(0),
            "indirim_orani": oran_yuvarla(0),
            "masraf_tutari": kurus(0),
            "masraf_orani": oran_yuvarla(0),
            "net": b,
            "islem_turu": "",
            "islem_tutari": kurus(0),
            "islem_orani": oran_yuvarla(0),
        }
    u = kurus(uzlasilan)
    if u < 0:
        raise ValueError("Uzlaşılan tutar negatif olamaz.")
    fark = kurus(u - b)
    indirim = kurus(0)
    masraf = kurus(0)
    tur = ""
    if fark < 0:
        indirim = kurus(-fark)
        tur = "INDIRIM"
    elif fark > 0:
        masraf = fark
        tur = "MASRAF"
    net = u
    ind_oran = tutardan_oran(b, indirim) if b > 0 and indirim > 0 else oran_yuvarla(0)
    mas_oran = tutardan_oran(b, masraf) if b > 0 and masraf > 0 else oran_yuvarla(0)
    islem_tutar = indirim if tur == "INDIRIM" else (masraf if tur == "MASRAF" else kurus(0))
    islem_oran = ind_oran if tur == "INDIRIM" else (mas_oran if tur == "MASRAF" else oran_yuvarla(0))
    return {
        "brut": b,
        "indirim_tutari": indirim,
        "indirim_orani": ind_oran,
        "masraf_tutari": masraf,
        "masraf_orani": mas_oran,
        "net": net,
        "islem_turu": tur,
        "islem_tutari": islem_tutar,
        "islem_orani": islem_oran,
    }


def iskonto_carpani(iskonto1=0, iskonto2=0, iskonto3=0) -> Decimal:
    carpani = Decimal("1")
    for sira, oran_ham in enumerate((iskonto1, iskonto2, iskonto3), start=1):
        oran = Decimal(str(oran_ham or 0))
        if oran < 0 or oran > 100:
            raise ValueError(f"İskonto {sira} 0-100 arasında olmalıdır.")
        carpani *= Decimal("1") - oran / Decimal("100")
    return carpani


def hedef_satir_genelden_birim_fiyat(
    *,
    miktar,
    kdv_orani,
    hedef_satir_genel,
    iskonto_orani=0,
    iskonto_orani_2=0,
    iskonto_orani_3=0,
) -> Decimal:
    """KDV dahil satır tutarından liste birim fiyatını geri hesaplar."""
    m = Decimal(str(miktar or 0))
    kdv = Decimal(str(kdv_orani or 0))
    hedef = kurus(hedef_satir_genel)
    if m <= 0:
        raise ValueError("Miktarı olmayan satıra fiyat yansıtılamaz.")
    carpani = iskonto_carpani(iskonto_orani, iskonto_orani_2, iskonto_orani_3)
    if carpani <= 0:
        raise ValueError("%100 iskontolu satıra fiyat yansıtılamaz.")
    net = hedef / (Decimal("1") + kdv / Decimal("100"))
    fiyat = net / (m * carpani)
    return fiyat.quantize(FIYAT_HAS, rounding=ROUND_HALF_UP)


def satir_hedefleri_orantili(
    mevcut_geneller: list[Decimal],
    hedef: Decimal,
    *,
    kapali: list[bool] | None = None,
) -> list[Decimal]:
    """Açık satırlara (hedef − kapalı tutar) orantılı KDV-dahil hedef tutarlar.

    Son açık satıra kalan kuruş verilir; kapalı satırlar kendi mevcut tutarını korur.
    """
    n = len(mevcut_geneller)
    if n == 0:
        raise ValueError("Fiyat yansıtmak için en az bir satır gerekli.")
    hedef_k = kurus(hedef)
    if hedef_k < 0:
        raise ValueError("Uzlaşılan tutar negatif olamaz.")
    kap = list(kapali) if kapali is not None else [False] * n
    if len(kap) != n:
        raise ValueError("Kapalı bayrak sayısı satır sayısıyla uyuşmuyor.")

    hedefler = [kurus(0)] * n
    sabit = kurus(0)
    acik_idx: list[int] = []
    acik_mevcut: list[Decimal] = []
    for i, g in enumerate(mevcut_geneller):
        g_k = kurus(g)
        if kap[i]:
            hedefler[i] = g_k
            sabit += g_k
        else:
            acik_idx.append(i)
            acik_mevcut.append(g_k)

    if not acik_idx:
        if kurus(sabit) != hedef_k:
            raise ValueError(
                "Tüm satırlar dağıtıma kapalı; uzlaşılan tutar satır toplamına eşit olmalı."
            )
        return hedefler

    kalan_hedef = kurus(hedef_k - sabit)
    if kalan_hedef < 0:
        raise ValueError(
            "Kapalı satır tutarları uzlaşılan tutarı aşıyor; dağıtım yapılamaz."
        )

    acik_toplam = kurus(sum(acik_mevcut, Decimal("0")))
    if acik_toplam > 0:
        biriken = kurus(0)
        for j, idx in enumerate(acik_idx[:-1]):
            pay = kurus(kalan_hedef * (acik_mevcut[j] / acik_toplam))
            hedefler[idx] = pay
            biriken += pay
        hedefler[acik_idx[-1]] = kurus(kalan_hedef - biriken)
    else:
        # Açık satırlar 0 tutarlıysa miktar yoksa eşit böl (çağıran miktarı kontrol eder)
        adet = len(acik_idx)
        biriken = kurus(0)
        pay_esit = kurus(kalan_hedef / Decimal(adet)) if adet else kurus(0)
        for idx in acik_idx[:-1]:
            hedefler[idx] = pay_esit
            biriken += pay_esit
        hedefler[acik_idx[-1]] = kurus(kalan_hedef - biriken)

    return hedefler


def uzlasilan_fiyatlara_dagit(
    satirlar: list[dict[str, Any]],
    hedef,
    *,
    satir_genel_fn: Callable[[dict[str, Any]], Decimal],
) -> dict[str, Any]:
    """Uzlaşılan hedefi satır birim_satis_fiyati alanlarına orantılı yazar.

    satir_genel_fn(veri) → satırın KDV dahil genel tutarı (Decimal).
    dagitima_kapali=True satırlar fiyatı değişmez.
    """
    if not satirlar:
        raise ValueError("Önce fatura satırı ekleyin.")
    hedef_k = kurus(hedef)
    if hedef_k < 0:
        raise ValueError("Uzlaşılan tutar negatif olamaz.")

    mevcut: list[Decimal] = []
    kapali: list[bool] = []
    for veri in satirlar:
        miktar = Decimal(str(veri.get("miktar") or 0))
        kap = bool(veri.get("dagitima_kapali"))
        if miktar <= 0 and not kap:
            raise ValueError("Miktarı olmayan satıra fiyat yansıtılamaz.")
        mevcut.append(kurus(satir_genel_fn(veri)))
        kapali.append(kap)

    onceki = kurus(sum(mevcut, Decimal("0")))
    if onceki == hedef_k:
        return {
            "hedef": hedef_k,
            "onceki_toplam": onceki,
            "yeni_toplam": onceki,
            "degisti": False,
            "dagitilan_satir_sayisi": 0,
        }

    hedefler = satir_hedefleri_orantili(mevcut, hedef_k, kapali=kapali)
    dagitilan = 0
    for i, veri in enumerate(satirlar):
        if kapali[i]:
            continue
        if hedefler[i] < 0:
            raise ValueError("Hesaplanan satır tutarı negatif olamaz.")
        yeni = hedef_satir_genelden_birim_fiyat(
            miktar=veri.get("miktar") or 0,
            kdv_orani=veri.get("kdv_orani") or 0,
            hedef_satir_genel=hedefler[i],
            iskonto_orani=veri.get("iskonto_orani") or 0,
            iskonto_orani_2=veri.get("iskonto_orani_2") or 0,
            iskonto_orani_3=veri.get("iskonto_orani_3") or 0,
        )
        if yeni < 0:
            raise ValueError("Hesaplanan birim fiyat negatif olamaz.")
        veri["birim_satis_fiyati"] = yeni
        if "birim_fiyat" in veri:
            veri["birim_fiyat"] = yeni
        dagitilan += 1

    yeni_toplam = _kurus_farki_fiyatlarda_kapat(satirlar, kapali, hedef_k, satir_genel_fn)
    return {
        "hedef": hedef_k,
        "onceki_toplam": onceki,
        "yeni_toplam": yeni_toplam,
        "degisti": True,
        "dagitilan_satir_sayisi": dagitilan,
        "kalan_fark": kurus(hedef_k - yeni_toplam),
    }


def _fiyat_yaz(veri: dict[str, Any], fiyat: Decimal) -> None:
    veri["birim_satis_fiyati"] = fiyat
    if "birim_fiyat" in veri:
        veri["birim_fiyat"] = fiyat


def _kurus_farki_fiyatlarda_kapat(
    satirlar: list[dict[str, Any]],
    kapali: list[bool],
    hedef_k: Decimal,
    satir_genel_fn: Callable[[dict[str, Any]], Decimal],
) -> Decimal:
    """Kalan kuruşu açık satırlarda birim fiyat adımlarıyla kapatır.

    Teorik geri hesap yetmezse ±0,0001 fiyat adımları dener; küçük miktarlı
    satırlar tercih edilir (daha ince genel tutar adımı).
    """

    def _toplam() -> Decimal:
        return kurus(sum((satir_genel_fn(v) for v in satirlar), Decimal("0")))

    acik = [
        i
        for i in range(len(satirlar))
        if not kapali[i] and Decimal(str(satirlar[i].get("miktar") or 0)) > 0
    ]
    if not acik:
        return _toplam()
    acik.sort(key=lambda i: Decimal(str(satirlar[i].get("miktar") or 0)))

    # 1) Teorik hedefe geri hesap (küçük miktar önce)
    for _ in range(12):
        yeni_toplam = _toplam()
        fark = kurus(hedef_k - yeni_toplam)
        if fark == 0:
            return yeni_toplam
        ilerleme = False
        for idx in acik:
            veri = satirlar[idx]
            son_hedef = kurus(satir_genel_fn(veri) + fark)
            if son_hedef < 0:
                continue
            eski = Decimal(str(veri.get("birim_satis_fiyati") or 0))
            try:
                yeni = hedef_satir_genelden_birim_fiyat(
                    miktar=veri.get("miktar") or 0,
                    kdv_orani=veri.get("kdv_orani") or 0,
                    hedef_satir_genel=son_hedef,
                    iskonto_orani=veri.get("iskonto_orani") or 0,
                    iskonto_orani_2=veri.get("iskonto_orani_2") or 0,
                    iskonto_orani_3=veri.get("iskonto_orani_3") or 0,
                )
            except ValueError:
                continue
            if yeni < 0:
                continue
            _fiyat_yaz(veri, yeni)
            deneme = _toplam()
            if abs(kurus(hedef_k - deneme)) < abs(fark):
                ilerleme = True
                if deneme == hedef_k:
                    return deneme
                break
            _fiyat_yaz(veri, eski)
        if not ilerleme:
            break

    # 2) ±0,0001 adım araması
    for _ in range(60):
        yeni_toplam = _toplam()
        fark = kurus(hedef_k - yeni_toplam)
        if fark == 0:
            return yeni_toplam
        best_i = None
        best_fiyat = None
        best_abs = abs(fark)
        for idx in acik:
            veri = satirlar[idx]
            base = Decimal(str(veri.get("birim_satis_fiyati") or 0))
            for adim in range(1, 150):
                bulundu = False
                for isaret in (1, -1):
                    cand = (base + Decimal(isaret) * Decimal(adim) * FIYAT_HAS).quantize(
                        FIYAT_HAS, rounding=ROUND_HALF_UP
                    )
                    if cand < 0:
                        continue
                    _fiyat_yaz(veri, cand)
                    d = abs(kurus(hedef_k - _toplam()))
                    _fiyat_yaz(veri, base)
                    if d < best_abs:
                        best_abs = d
                        best_i = idx
                        best_fiyat = cand
                        if d == 0:
                            bulundu = True
                            break
                if bulundu:
                    break
            if best_abs == 0:
                break
        if best_i is None or best_fiyat is None or best_abs >= abs(fark):
            break
        _fiyat_yaz(satirlar[best_i], best_fiyat)

    return _toplam()
