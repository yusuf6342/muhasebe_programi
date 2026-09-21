"""Net toplamı satır birim fiyatlarına oransal dağıtma + fatura sağlaması (Decimal).

Dağıtım KDV dahil satır genel tutarı üzerinden yapılır (mevcut fatura satır motoru ile uyumlu).
Brüt / işlem alanları hesap izi olarak korunur; muhasebe tutarı = Net.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable

from database.fatura_genel_toplam_service import (
    ISLEM_INDIRIM,
    ISLEM_MASRAF,
    ISLEM_YOK,
    kurus,
    netten_islem,
    oran_yuvarla,
)

FIYAT_HAS = Decimal("0.0001")
# Residual kapatmada yüksek miktarlı satırlar için iç hassasiyet (gösterim kaybetmeden)
FIYAT_HAS_IC = Decimal("0.000001")
TOLERANS = Decimal("0.01")


def _d(deger, varsayilan: Decimal = Decimal("0")) -> Decimal:
    if deger is None or deger == "":
        return varsayilan
    if isinstance(deger, Decimal):
        return deger
    try:
        return Decimal(str(deger))
    except Exception:
        return varsayilan


def satir_dagitima_uygun(veri: dict) -> bool:
    """Sıfır miktar/tutar, ücretsiz veya açıkça kilitli satırlar dağıtıma girmez.

    manuel_fiyat yalnızca audit bayrağıdır; dağıtımdan çıkarmaz.
    Dağıtım kilidi: dagitima_kapali / fiyat_kilitli / distribution_locked.
    """
    if bool(
        veri.get("dagitima_kapali")
        or veri.get("fiyat_kilitli")
        or veri.get("distribution_locked")
    ):
        return False
    if bool(veri.get("ucretsiz")):
        return False
    miktar = _d(veri.get("miktar") or 0)
    if miktar <= 0:
        return False
    return True


def satir_kdv_dahil_genel(
    veri: dict,
    *,
    satir_net_fn: Callable | None = None,
) -> Decimal:
    """Satırın KDV dahil genel tutarı (dağıtıma esas)."""
    from database.satis_faturasi_service import SatisFaturasiService

    miktar = _d(veri.get("miktar") or 0)
    fiyat = _d(veri.get("birim_satis_fiyati", veri.get("birim_fiyat", veri.get("birim_alis_fiyati", 0))))
    kdv = _d(veri.get("kdv_orani") or 0)
    if satir_net_fn:
        _, _, net = satir_net_fn(
            miktar,
            fiyat,
            veri.get("iskonto_orani") or 0,
            veri.get("iskonto_orani_2") or 0,
            veri.get("iskonto_orani_3") or 0,
        )
    else:
        _, _, net = SatisFaturasiService._satir_net(
            miktar,
            fiyat,
            veri.get("iskonto_orani") or 0,
            veri.get("iskonto_orani_2") or 0,
            veri.get("iskonto_orani_3") or 0,
        )
    net = kurus(net)
    kdv_t = kurus(net * kdv / Decimal("100"))
    return kurus(net + kdv_t)


def hedef_genelden_birim_fiyat(
    veri: dict,
    hedef_satir_genel: Decimal,
    *,
    hassasiyet: Decimal = FIYAT_HAS,
) -> Decimal:
    """KDV dahil satır tutarından liste birim fiyatını geri hesaplar."""
    from database.iskonto_hesap_service import iskonto_carpani

    miktar = _d(veri.get("miktar") or 0)
    kdv = _d(veri.get("kdv_orani") or 0)
    if miktar <= 0:
        raise ValueError("Miktarı olmayan satıra fiyat dağıtılamaz.")
    carpani = iskonto_carpani(
        veri.get("iskonto_orani") or 0,
        veri.get("iskonto_orani_2") or 0,
        veri.get("iskonto_orani_3") or 0,
    )
    if carpani <= 0:
        raise ValueError("%100 iskontolu satıra fiyat dağıtılamaz.")
    net = _d(hedef_satir_genel) / (Decimal("1") + kdv / Decimal("100"))
    fiyat = net / (miktar * carpani)
    if fiyat < 0:
        raise ValueError("Hesaplanan birim fiyat negatif olamaz.")
    return fiyat.quantize(hassasiyet, rounding=ROUND_HALF_UP)


def _fiyat_uygula_kopya(veri: dict, fiyat: Decimal) -> dict:
    t = dict(veri)
    t["birim_fiyat"] = fiyat
    t["birim_satis_fiyati"] = fiyat
    t["birim_alis_fiyati"] = fiyat
    return t


def fiyat_hedef_geneli_saglar(
    veri: dict,
    hedef_satir_genel: Decimal,
    *,
    hassasiyet: Decimal = FIYAT_HAS_IC,
    arama_adim: int = 80,
) -> Decimal | None:
    """Hedef KDV dahil satır tutarını tam üreten birim fiyatı bulur; yoksa None."""
    hedef_s = kurus(hedef_satir_genel)
    if hedef_s < 0:
        return None
    try:
        base = hedef_genelden_birim_fiyat(veri, hedef_s, hassasiyet=hassasiyet)
    except ValueError:
        return None

    def _eslesir(fiyat: Decimal) -> bool:
        if fiyat < 0:
            return False
        return satir_kdv_dahil_genel(_fiyat_uygula_kopya(veri, fiyat)) == hedef_s

    if _eslesir(base):
        return base
    adim = hassasiyet
    for n in range(1, arama_adim + 1):
        for isaret in (1, -1):
            aday = (base + adim * n * isaret).quantize(hassasiyet, rounding=ROUND_HALF_UP)
            if _eslesir(aday):
                return aday
    return None


def residual_duzeltme_satiri_sec(
    satirlar: list[dict],
    uygun_indeksler: list[int],
    residual: Decimal,
) -> tuple[int, Decimal, Decimal] | None:
    """Residual'ı tam temsil edebilen satırı seçer.

    Öncelik: miktar==1 → temsil edilebilir → en küçük miktar → en küçük indeks.
    Dönüş: (idx, yeni_birim_fiyat, hedef_satir_genel) veya None.
    """
    residual = kurus(residual)
    if residual == 0:
        return None

    adaylar: list[tuple] = []
    for idx in uygun_indeksler:
        veri = satirlar[idx]
        if not satir_dagitima_uygun(veri):
            continue
        miktar = _d(veri.get("miktar") or 0)
        if miktar <= 0:
            continue
        mevcut = satir_kdv_dahil_genel(veri)
        hedef_s = kurus(mevcut + residual)
        if hedef_s < 0:
            continue
        # Önce standart, yetmezse iç hassasiyet
        fiyat = fiyat_hedef_geneli_saglar(veri, hedef_s, hassasiyet=FIYAT_HAS)
        if fiyat is None:
            fiyat = fiyat_hedef_geneli_saglar(veri, hedef_s, hassasiyet=FIYAT_HAS_IC)
        if fiyat is None:
            continue
        miktar_1_ceza = 0 if miktar == 1 else 1
        adaylar.append((miktar_1_ceza, miktar, idx, fiyat, hedef_s))

    if not adaylar:
        return None
    adaylar.sort(key=lambda t: (t[0], t[1], t[2]))
    _, _, idx, fiyat, hedef_s = adaylar[0]
    return idx, fiyat, hedef_s


def _satira_fiyat_yaz(veri: dict, fiyat: Decimal, *, alis: bool, alan: str) -> None:
    veri[alan] = fiyat
    veri["birim_fiyat"] = fiyat
    if alis:
        veri["birim_alis_fiyati"] = fiyat
    else:
        veri["birim_satis_fiyati"] = fiyat


def fiyat_snapshot_al(satirlar: list[dict]) -> list[dict]:
    """Geri alma için birim fiyat anlık görüntüsü."""
    sonuc = []
    for s in satirlar:
        sonuc.append(
            {
                "birim_satis_fiyati": s.get("birim_satis_fiyati"),
                "birim_fiyat": s.get("birim_fiyat"),
                "birim_alis_fiyati": s.get("birim_alis_fiyati"),
                "birim_fiyat_doviz": s.get("birim_fiyat_doviz"),
            }
        )
    return sonuc


def fiyat_snapshot_uygula(satirlar: list[dict], snapshot: list[dict], *, alis: bool = False) -> None:
    for i, snap in enumerate(snapshot):
        if i >= len(satirlar):
            break
        s = satirlar[i]
        for alan in ("birim_satis_fiyati", "birim_fiyat", "birim_alis_fiyati", "birim_fiyat_doviz"):
            if alan in snap and snap[alan] is not None:
                s[alan] = snap[alan]
        if alis:
            if snap.get("birim_alis_fiyati") is not None:
                s["birim_alis_fiyati"] = snap["birim_alis_fiyati"]
                s["birim_fiyat"] = snap.get("birim_fiyat", snap["birim_alis_fiyati"])
        else:
            if snap.get("birim_satis_fiyati") is not None:
                s["birim_satis_fiyati"] = snap["birim_satis_fiyati"]
                s["birim_fiyat"] = snap.get("birim_fiyat", snap["birim_satis_fiyati"])


def neti_fiyatlara_dagit(
    satirlar: list[dict],
    hedef_net: Decimal,
    *,
    alis: bool = False,
    fiyat_alani: str | None = None,
) -> dict[str, Any]:
    """Hedef Net Toplamı satır birim fiyatlarına oransal dağıtır (yerinde günceller).

    Dönüş: brut_oncesi, fark, islem_*, yeni_net, dagitilan_satir_sayisi
    """
    hedef = kurus(hedef_net)
    if hedef < 0:
        raise ValueError("Net toplam negatif olamaz.")

    uygun: list[tuple[int, Decimal]] = []
    mevcut_uygun = Decimal("0")
    mevcut_tum = Decimal("0")
    for i, veri in enumerate(satirlar):
        genel = satir_kdv_dahil_genel(veri)
        if genel > 0 or _d(veri.get("miktar") or 0) > 0:
            # Sıfır tutarlı satırlar toplama girmez
            if genel > 0:
                mevcut_tum += genel
        if not satir_dagitima_uygun(veri):
            continue
        if genel <= 0:
            continue
        uygun.append((i, genel))
        mevcut_uygun += genel
    mevcut_uygun = kurus(mevcut_uygun)
    mevcut_tum = kurus(mevcut_tum)

    if not uygun:
        raise ValueError(
            "Fiyatlara dağıtılacak uygun satır yok "
            "(miktar/tutar sıfır, ücretsiz veya dağıtıma kilitli satırlar hariç)."
        )

    # Brüt iz = dağıtım öncesi tüm satır toplamı; fark tüm faturaya göre
    brut = mevcut_tum
    islem = netten_islem(brut, hedef)
    fark = kurus(hedef - brut)

    # Oransal dağıtım yalnızca uygun satırlara (ağırlık = uygun havuz)
    biriken = Decimal("0")
    hedefler: dict[int, Decimal] = {}
    for sira, (idx, genel) in enumerate(uygun):
        if sira < len(uygun) - 1:
            pay = kurus(fark * (genel / mevcut_uygun))
            yeni = kurus(genel + pay)
            hedefler[idx] = yeni
            biriken += pay
        else:
            hedefler[idx] = kurus(genel + (fark - biriken))

    alan = fiyat_alani or ("birim_alis_fiyati" if alis else "birim_satis_fiyati")
    for idx, hedef_satir in hedefler.items():
        if hedef_satir < 0:
            raise ValueError("Dağıtım sonrası satır tutarı negatif olamaz.")
        veri = satirlar[idx]
        yeni_fiyat = hedef_genelden_birim_fiyat(veri, hedef_satir)
        _satira_fiyat_yaz(veri, yeni_fiyat, alis=alis, alan=alan)

    # 2. aşama: residual = hedef − satır toplamı; körlemesine son satır değil
    uygun_idxs = [idx for idx, _ in uygun]
    yeni_toplam = kurus(sum((satir_kdv_dahil_genel(s) for s in satirlar), Decimal("0")))
    residual = kurus(hedef - yeni_toplam)
    residual_satir = None
    if residual != 0:
        secim = residual_duzeltme_satiri_sec(satirlar, uygun_idxs, residual)
        if secim is None:
            detay = []
            for idx in uygun_idxs:
                v = satirlar[idx]
                detay.append(
                    f"satır#{idx + 1} miktar={_d(v.get('miktar'))} "
                    f"genel={satir_kdv_dahil_genel(v)}"
                )
            raise ValueError(
                f"Kuruş farkı ({residual} TL) uygun satırda temsil edilemedi. "
                f"Hedef: {hedef}, Dağıtım sonrası: {yeni_toplam}. "
                + "; ".join(detay)
            )
        son_idx, yeni_fiyat, _hedef_s = secim
        residual_satir = son_idx + 1
        _satira_fiyat_yaz(satirlar[son_idx], yeni_fiyat, alis=alis, alan=alan)

    yeni_net = kurus(sum((satir_kdv_dahil_genel(s) for s in satirlar), Decimal("0")))
    # Tam eşleşme zorunlu — toleransla geçirme
    if yeni_net != hedef:
        raise ValueError(
            f"Dağıtım sonrası toplam hedefe uymadı. Hedef: {hedef}, "
            f"Hesaplanan: {yeni_net}, residual: {kurus(hedef - yeni_net)}"
        )

    return {
        "brut_oncesi": brut,
        "fark": fark,
        "islem_turu": islem["islem_turu"],
        "islem_orani": islem["islem_orani"],
        "islem_tutari": islem["islem_tutari"],
        "net_toplam": yeni_net,
        "hedef_net": hedef,
        "dagitilan_satir_sayisi": len(uygun),
        "residual": residual,
        "residual_duzeltilen_satir": residual_satir,
    }


def fatura_saglama(
    satirlar: list[dict],
    *,
    hedef_net: Decimal | None = None,
    tl_genel_toplam: Decimal | None = None,
    tolerans: Decimal = TOLERANS,
) -> dict[str, Any]:
    """Merkezi fatura sağlaması. ok=False ise kayıt/yazdırma engellenmeli."""
    from database.satis_faturasi_service import SatisFaturasiService

    sorunlar: list[str] = []
    toplam = SatisFaturasiService.toplam(satirlar)
    matrah = kurus(toplam["ara_toplam"] - toplam["iskonto"])
    kdv = kurus(toplam["kdv"])
    genel = kurus(toplam["genel_toplam"])

    # KDV oranı bazında satır KDV toplamı
    kdv_grup: dict[Decimal, Decimal] = {}
    matrah_satir_toplam = Decimal("0")
    for i, veri in enumerate(satirlar):
        miktar = _d(veri.get("miktar") or 0)
        if miktar <= 0:
            continue
        genel_s = satir_kdv_dahil_genel(veri)
        if genel_s < 0:
            sorunlar.append(f"Satır {i + 1}: negatif satır toplamı ({genel_s})")
        from database.satis_faturasi_service import SatisFaturasiService as SFS

        _, _, net = SFS._satir_net(
            miktar,
            _d(veri.get("birim_satis_fiyati", veri.get("birim_fiyat", veri.get("birim_alis_fiyati", 0)))),
            veri.get("iskonto_orani") or 0,
            veri.get("iskonto_orani_2") or 0,
            veri.get("iskonto_orani_3") or 0,
        )
        net = kurus(net)
        oran = _d(veri.get("kdv_orani") or 0)
        kdv_s = kurus(net * oran / Decimal("100"))
        matrah_satir_toplam += net
        kdv_grup[oran] = kurus(kdv_grup.get(oran, Decimal("0")) + kdv_s)

    matrah_satir_toplam = kurus(matrah_satir_toplam)
    if abs(matrah_satir_toplam - matrah) > tolerans:
        sorunlar.append(
            f"Matrah uyuşmazlığı: satırlar {matrah_satir_toplam} ≠ fatura {matrah}"
        )
    kdv_grup_toplam = kurus(sum(kdv_grup.values(), Decimal("0")))
    if abs(kdv_grup_toplam - kdv) > tolerans:
        sorunlar.append(
            f"KDV uyuşmazlığı: oran grupları {kdv_grup_toplam} ≠ fatura {kdv}"
        )

    hedef = kurus(hedef_net if hedef_net is not None else (tl_genel_toplam or genel))
    fark = kurus(genel - hedef)
    if abs(fark) > tolerans:
        sorunlar.append(
            f"Genel toplam uyuşmazlığı: satırlardan {genel} ≠ hedef Net {hedef} (fark {fark})"
        )

    return {
        "ok": len(sorunlar) == 0,
        "sorunlar": sorunlar,
        "matrah": matrah,
        "kdv": kdv,
        "genel_toplam": genel,
        "hedef_net": hedef,
        "fark": fark,
        "ara_toplam": kurus(toplam["ara_toplam"]),
        "iskonto": kurus(toplam["iskonto"]),
        "kdv_gruplari": kdv_grup,
    }


def saglama_hata_metni(sonuc: dict[str, Any]) -> str:
    if sonuc.get("ok"):
        return ""
    satirlar = sonuc.get("sorunlar") or ["Fatura sağlaması başarısız."]
    fark = sonuc.get("fark")
    baslik = "Fatura sağlaması başarısız"
    if fark is not None:
        baslik += f" (fark: {fark} TL)"
    return baslik + ":\n- " + "\n- ".join(str(s) for s in satirlar)
