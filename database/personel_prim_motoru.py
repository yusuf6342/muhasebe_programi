"""Tahsil edilmiş kâr katkısı (H), prim havuzu ve kişi dağıtımı.

Yönetim hesabıdır; genel muhasebe dönem kârı değildir. Decimal kullanır.
Örnek oranlar (%%10, 50/30/20) varsayılan öneridir — canlı politika değildir.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Iterable, Sequence

Q2 = Decimal("0.01")
Q8 = Decimal("0.00000001")
SIFIR = Decimal("0")
BIR = Decimal("1")


def D(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if v is None:
        return SIFIR
    return Decimal(str(v))


def q2(v: Decimal) -> Decimal:
    return D(v).quantize(Q2, rounding=ROUND_HALF_UP)


def tahsil_kar_katkisi(
    *,
    S,
    C,
    F,
    T,
) -> dict:
    """H = M × q; F=0 → H=0. Negatif marj korunur.

    S: KDV hariç net satış (iskonto/iade sonrası)
    C: aynı kapsamda SMM
    F: iadeler sonrası geçerli KDV dahil fatura borcu
    T: bu borca bağlı kesinleşmiş net tahsilat
    """
    s, c, f, t = D(S), D(C), D(F), D(T)
    m = s - c
    if f == 0:
        q = SIFIR
        h = SIFIR
        notlar = ["F=0: tam iptal/iade veya geçersiz borç — H=0"]
    else:
        q = min(BIR, max(SIFIR, t / f))
        h = m * q
        notlar = []
    eksik = []
    # Çağıran maliyet/tahsilat eksikliğini işaretleyebilir
    return {
        "S": q2(s),
        "C": q2(c),
        "M": q2(m),
        "F": q2(f),
        "T": q2(t),
        "q": q.quantize(Q8, rounding=ROUND_DOWN),
        "H": q2(h),
        "notlar": notlar,
        "eksik": eksik,
    }


def donem_katkisi(
    fatura_h_son: Sequence[tuple[Any, Decimal]],
    fatura_h_once: dict,
) -> Decimal:
    """Σ (H_dönem_sonu − H_önceki_kapanış). Yeni faturalarda önceki 0."""
    toplam = SIFIR
    for fid, h_son in fatura_h_son:
        h_once = D(fatura_h_once.get(fid, SIFIR))
        toplam += D(h_son) - h_once
    return q2(toplam)


# tip ipucu için
from typing import Any  # noqa: E402


def havuz_hesapla(
    *,
    tahsil_kar_katkisi_toplam,
    uygun_giderler,
    onceki_zarar_devri=0,
    guvence_tutari=0,
    prim_orani=Decimal("0.10"),
) -> dict:
    """G→N→B→bütçe. Zarar devri personele borç yazılmaz."""
    g = D(tahsil_kar_katkisi_toplam) - D(uygun_giderler)
    n = g - D(onceki_zarar_devri)
    yeni_zarar = max(SIFIR, -n)
    b = max(SIFIR, n - D(guvence_tutari))
    oran = D(prim_orani)
    if oran < 0 or oran > 1:
        raise ValueError("Prim oranı 0–1 arasında olmalı.")
    butce = b * oran
    return {
        "G": q2(g),
        "N": q2(n),
        "yeni_zarar_devri": q2(yeni_zarar),
        "B": q2(b),
        "prim_orani": oran,
        "prim_butcesi": q2(butce),
        "guvence_tutari": q2(D(guvence_tutari)),
        "aciklama": "Prim bütçesi toplam işveren maliyeti tahminidir; net ödeme değildir.",
    }


@dataclass(frozen=True)
class DagitimKisi:
    personel_id: int
    hizmet_yili: int
    performans: Decimal  # 0–100
    katilim: Decimal = BIR  # e_i


def kidem_katsayisi(hizmet_yili: int) -> Decimal:
    """k = 1 + min(yıl, 5) × 0,03"""
    y = max(0, int(hizmet_yili))
    return BIR + Decimal(min(y, 5)) * Decimal("0.03")


def _en_buyuk_kalan(paylar_ham: list[Decimal], hedef: Decimal) -> list[Decimal]:
    """Kuruş farkını en büyük kalan + sabit kimlik sırasıyla çözer."""
    asagi = [p.quantize(Q2, rounding=ROUND_DOWN) for p in paylar_ham]
    kalan_toplam = hedef - sum(asagi)
    kurus = int((kalan_toplam / Q2).to_integral_value(rounding=ROUND_HALF_UP))
    if kurus <= 0:
        return asagi
    # Kalanlar (kesir) büyükten küçüğe; eşitlikte düşük indeks (sabit sıra)
    sirali = sorted(
        range(len(paylar_ham)),
        key=lambda i: (-(paylar_ham[i] - asagi[i]), i),
    )
    for j in range(min(kurus, len(sirali))):
        asagi[sirali[j]] += Q2
    return asagi


def kisi_dagitimi(
    butce,
    kisiler: Sequence[DagitimKisi],
    *,
    agirlik_ekip=Decimal("0.50"),
    agirlik_katki=Decimal("0.30"),
    agirlik_kidem=Decimal("0.20"),
) -> dict:
    """Kişi bütçesi = ekip + katkı + kıdem. Ağırlıklar toplamı 1 olmalı."""
    butce = q2(D(butce))
    w_e, w_k, w_d = D(agirlik_ekip), D(agirlik_katki), D(agirlik_kidem)
    if q2(w_e + w_k + w_d) != BIR:
        raise ValueError("Dağıtım ağırlıkları toplamı %100 olmalı.")
    if butce <= 0 or not kisiler:
        return {
            "butce": butce,
            "kisiler": [],
            "dagitilan": SIFIR,
            "dagitilmamis": butce,
            "katki_dilimi_dagitilmadi": False,
        }

    hazir = []
    for k in kisiler:
        e = D(k.katilim)
        s = D(k.performans)
        if s < 0 or s > 100:
            raise ValueError("Performans puanı 0–100 olmalı.")
        kk = kidem_katsayisi(k.hizmet_yili)
        hazir.append((k.personel_id, e, s, kk))

    sum_e = sum(e for _, e, _, _ in hazir)
    sum_es = sum(e * s for _, e, s, _ in hazir)
    sum_ek = sum(e * kk for _, e, _, kk in hazir)

    katki_dilimi_dagitilmadi = sum_es == 0
    ekip_havuz = butce * w_e
    katki_havuz = SIFIR if katki_dilimi_dagitilmadi else butce * w_k
    kidem_havuz = butce * w_d
    dagitilmamis_katki = q2(butce * w_k) if katki_dilimi_dagitilmadi else SIFIR
    dagitilacak = q2(butce - dagitilmamis_katki)

    ekip_ham, katki_ham, kidem_ham, toplam_ham = [], [], [], []
    for _, e, s, kk in hazir:
        eh = ekip_havuz * e / sum_e if sum_e else SIFIR
        kh = katki_havuz * (e * s) / sum_es if sum_es else SIFIR
        dh = kidem_havuz * (e * kk) / sum_ek if sum_ek else SIFIR
        ekip_ham.append(eh)
        katki_ham.append(kh)
        kidem_ham.append(dh)
        toplam_ham.append(eh + kh + dh)

    # Kuruş: önce kişi toplamlarında en büyük kalan (örnek A/B/C ile uyumlu)
    toplam_q = _en_buyuk_kalan(toplam_ham, dagitilacak)

    satirlar = []
    for i, (pid, e, s, kk) in enumerate(hazir):
        # Dilim gösterimi: ekip/katkı yuvarla, kıdem = toplam − diğerleri
        ekip_g = q2(ekip_ham[i])
        katki_g = q2(katki_ham[i])
        kidem_g = toplam_q[i] - ekip_g - katki_g
        satirlar.append(
            {
                "personel_id": pid,
                "katilim": e,
                "performans": s,
                "kidem_katsayi": kk,
                "ekip_payi": ekip_g,
                "katki_payi": katki_g,
                "kidem_payi": kidem_g,
                "toplam": toplam_q[i],
            }
        )
    dagitilan = sum((s["toplam"] for s in satirlar), SIFIR)
    return {
        "butce": butce,
        "kisiler": satirlar,
        "dagitilan": q2(dagitilan),
        "dagitilmamis": q2(butce - dagitilan),
        "dagitilmamis_detay": {
            "katki_dilimi": dagitilmamis_katki,
            "kurus_duzeltme_sonrasi": q2(dagitilacak - dagitilan),
        },
        "katki_dilimi_dagitilmadi": katki_dilimi_dagitilmadi,
        "agirliklar": {"ekip": w_e, "katki": w_k, "kidem": w_d},
    }


def pos_uzlasma(brut, komisyon) -> dict:
    """Brüt borç kapama − komisyon = net; komisyon tek gider."""
    b, k = D(brut), D(komisyon)
    return {"brut": q2(b), "komisyon": q2(k), "net": q2(b - k)}
