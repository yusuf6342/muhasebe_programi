"""Tahsilat ve mahsup esaslı kâr gerçekleşme — mevcut kapatma paylarından salt okunur rapor.

Formül (fatura bazında):
  N = KDV hariç net satış (iade sonrası)
  C = satılan mal maliyeti (satış satır maliyeti; yoksa hesaplanamaz)
  G = N − C  (brüt satış kârı; zarar negatif)
  F = KDV dahil ekonomik alacak (açık kalem esas tutarı)
  S = geçerli kapatma payları toplamı (nakit/mahsup; mevcut cari_kapatmalar)
  r = min(1, S/F)  (F=0 ise oran yok)
  R = G × r   B = G − R
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.database import get_session

_Q = Decimal("0.01")
_SIFIR = Decimal("0")


def _q2(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(_Q, rounding=ROUND_HALF_UP)


def _maliyet_izinli() -> bool:
    try:
        from database.access import yetki_var, oturum_var

        if not oturum_var():
            return True
        return bool(
            yetki_var(
                "maliyet_goruntuleme",
                "satis_maliyet_goruntuleme",
                "satis_goruntuleme",
                "finans_goruntuleme",
                "goruntuleme",
            )
        )
    except Exception:
        return True


def fatura_kar_gerceklesme(
    bas: date,
    bit: date,
    *,
    rapor_tarihi: date | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Satış dönemine göre fatura listesi + gerçekleşen/bekleyen brüt kâr."""
    from database.kapatma_izleme_service import fatura_odeme_ozeti
    from database.models.satis_faturasi import SatisFaturasi
    # İlişki mapper'ları (sipariş / irsaliye) kayıtlı olsun
    import database.models.satis_siparisi  # noqa: F401
    import database.models.satis_irsaliyesi  # noqa: F401
    import database.models.cari  # noqa: F401

    rapor_tarihi = rapor_tarihi or date.today()
    maliyet_ok = _maliyet_izinli()
    satirlar: list[dict[str, Any]] = []
    ozet = {
        "toplam_brut_kar": _SIFIR,
        "gerceklesen_brut_kar": _SIFIR,
        "bekleyen_brut_kar": _SIFIR,
        "toplam_net_satis": _SIFIR,
        "toplam_karsilanan": _SIFIR,
        "toplam_alacak": _SIFIR,
        "hesap_disi": 0,
        "maliyet_eksik": 0,
        "fatura_sayisi": 0,
    }

    with get_session() as session:
        kosul = [
            SatisFaturasi.fatura_tarihi >= bas,
            SatisFaturasi.fatura_tarihi <= bit,
        ]
        if hasattr(SatisFaturasi, "is_deleted"):
            kosul.append(SatisFaturasi.is_deleted.is_(False))
        faturalar = list(
            session.scalars(
                select(SatisFaturasi)
                .where(*kosul)
                .options(
                    selectinload(SatisFaturasi.satirlar),
                    selectinload(SatisFaturasi.cari),
                )
                .order_by(SatisFaturasi.fatura_tarihi.desc(), SatisFaturasi.id.desc())
                .limit(limit)
            ).all()
        )
        for f in faturalar:
            if getattr(f, "cancelled_at", None):
                continue
            net = _q2(getattr(f, "tl_matrah", None) or 0)
            maliyet = _SIFIR
            maliyet_var = False
            for s in f.satirlar or []:
                birim_m = _q2(getattr(s, "fifo_birim_maliyeti", None) or 0)
                miktar = _q2(getattr(s, "miktar", 0))
                carpan = _q2(getattr(s, "birim_carpani", None) or 1)
                if carpan == 0:
                    carpan = Decimal("1")
                if birim_m > 0 or miktar != 0:
                    # fifo 0 ve miktar > 0 → maliyet eksik sayılabilir; satırda herhangi
                    # pozitif fifo varsa maliyet_var True
                    if birim_m > 0:
                        maliyet_var = True
                    maliyet += _q2(abs(miktar) * carpan * birim_m)
            # Tüm satırlarda fifo=0 ise eksik maliyet
            if f.satirlar and all(_q2(getattr(s, "fifo_birim_maliyeti", 0) or 0) == 0 for s in f.satirlar):
                maliyet_var = False
                maliyet = _SIFIR
            try:
                odeme = fatura_odeme_ozeti(int(f.id), "SATIS")
            except Exception:
                odeme = {
                    "toplam": _q2(getattr(f, "tl_genel_toplam", 0)),
                    "kapanan": _SIFIR,
                    "kalan": _q2(getattr(f, "tl_genel_toplam", 0)),
                    "durum": "—",
                }
            F = _q2(odeme.get("toplam") or 0)
            S = _q2(odeme.get("kapanan") or 0)
            if F < 0:
                F = abs(F)
            if S < 0:
                S = abs(S)
            if S > F and F > 0:
                # avans fazlası oranı %100'ü aşmaz
                S_oran = F
            else:
                S_oran = S
            oran = (S_oran / F) if F > 0 else (_SIFIR if S == 0 else Decimal("1"))
            if oran > 1:
                oran = Decimal("1")

            hesap_disi = False
            if not maliyet_var:
                ozet["maliyet_eksik"] += 1
                brut = None
                gerceklesen = None
                bekleyen = None
                hesap_disi = True
                ozet["hesap_disi"] += 1
            else:
                brut = _q2(net - maliyet) if maliyet_ok else None
                if brut is None:
                    gerceklesen = None
                    bekleyen = None
                else:
                    gerceklesen = _q2(brut * oran)
                    bekleyen = _q2(brut - gerceklesen)
                    ozet["toplam_brut_kar"] += brut
                    ozet["gerceklesen_brut_kar"] += gerceklesen
                    ozet["bekleyen_brut_kar"] += bekleyen

            ozet["toplam_net_satis"] += net
            ozet["toplam_alacak"] += F
            ozet["toplam_karsilanan"] += S
            ozet["fatura_sayisi"] += 1

            cari = f.cari
            durum = "Gerçekleşmedi"
            if F > 0 and S_oran <= 0:
                durum = "Gerçekleşmedi"
            elif F > 0 and S_oran >= F:
                durum = "Tam gerçekleşti"
            elif S_oran > 0:
                durum = "Kısmen gerçekleşti"

            satirlar.append(
                {
                    "fatura_id": int(f.id),
                    "fatura_no": f.fatura_no,
                    "tarih": f.fatura_tarihi,
                    "cari_id": int(f.cari_id) if f.cari_id else None,
                    "musteri": (cari.unvan if cari else "") or "",
                    "net_satis": net,
                    "maliyet": maliyet if maliyet_var and maliyet_ok else None,
                    "brut_kar": brut if maliyet_ok else None,
                    "alacak_f": F,
                    "karsilanan_s": S,
                    "oran": oran,
                    "gerceklesen": gerceklesen if maliyet_ok else None,
                    "bekleyen": bekleyen if maliyet_ok else None,
                    "durum": durum if not hesap_disi else "Kâr hesaplanamıyor",
                    "odeme_durumu": odeme.get("durum") or "",
                    "hesap_disi": hesap_disi,
                }
            )

    return {
        "bas": bas,
        "bit": bit,
        "rapor_tarihi": rapor_tarihi,
        "esas": "Kesin tahsilat ve mahsup",
        "maliyet_ok": maliyet_ok,
        "ozet": ozet,
        "satirlar": satirlar,
    }
