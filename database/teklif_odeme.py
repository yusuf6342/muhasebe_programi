"""Teklif ödeme şekli — Excel vade formatı, çoklu seçim, gün/vade hesapları."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any


ODEME_SEKILLERI: tuple[str, ...] = (
    "Nakit",
    "Kredi Kartı",
    "Çek",
    "Senet",
    "Açık Hesap",
)

NAKIT_ALT = ("Havale", "Kasa")
VADELI_SEKILLER = frozenset({"Çek", "Senet", "Açık Hesap"})
KREDI_KARTI = "Kredi Kartı"
NAKIT = "Nakit"


def kk_taksit_secenekleri() -> list[str]:
    return ["Tek Çekim"] + [f"{i} Taksit" for i in range(2, 13)]


def kk_taksit_etiket(sayi: int | None) -> str:
    n = int(sayi or 1)
    if n <= 1:
        return "Tek Çekim"
    return f"{n} Taksit"


def kk_taksit_sayisi(etiket: str | None) -> int | None:
    metin = (etiket or "").strip()
    if not metin:
        return None
    if metin.casefold() in ("tek çekim", "tek cekim", "1", "1 taksit"):
        return 1
    rakam = "".join(ch for ch in metin if ch.isdigit())
    if not rakam:
        return None
    return max(1, min(12, int(rakam)))


def kk_vade_gun(taksit: int | None) -> int:
    """Excel: tek çekim → 1 gün; N taksit → ((N+1)/2)*30 gün."""
    n = int(taksit or 1)
    if n <= 1:
        return 1
    return int(round((n + 1) / 2 * 30))


def vade_tarihi_hesapla(baslangic: date, gun: int) -> date:
    return baslangic + timedelta(days=int(gun))


def gun_hesapla(baslangic: date, vade: date) -> int:
    return max(0, (vade - baslangic).days)


def kalem_hesapla(
    sekil: str,
    *,
    islem_tarihi: date,
    alt: str | None = None,
    taksit: int | None = None,
    gun: int | None = None,
    vade: date | None = None,
    vade_elle: bool = False,
) -> dict[str, Any]:
    """Tek ödeme kalemi için gün / vade üret (Excel kuralları)."""
    s = (sekil or "").strip()
    sonuc: dict[str, Any] = {
        "sekil": s,
        "alt": None,
        "taksit": None,
        "gun": 0,
        "vade": islem_tarihi,
    }
    if s == NAKIT:
        sonuc["alt"] = (alt or "Havale").strip() or "Havale"
        sonuc["gun"] = 0
        sonuc["vade"] = islem_tarihi
        return sonuc
    if s == KREDI_KARTI:
        t = int(taksit or 1)
        g = kk_vade_gun(t)
        sonuc["taksit"] = t
        sonuc["gun"] = g
        sonuc["vade"] = vade_tarihi_hesapla(islem_tarihi, g)
        return sonuc
    if s in VADELI_SEKILLER:
        sonuc["alt"] = "Vadeli"
        if vade_elle and vade is not None:
            sonuc["vade"] = vade
            sonuc["gun"] = gun_hesapla(islem_tarihi, vade)
        elif gun is not None:
            g = max(0, int(gun))
            sonuc["gun"] = g
            sonuc["vade"] = vade_tarihi_hesapla(islem_tarihi, g)
        elif vade is not None:
            sonuc["vade"] = vade
            sonuc["gun"] = gun_hesapla(islem_tarihi, vade)
        else:
            sonuc["gun"] = 0
            sonuc["vade"] = islem_tarihi
        return sonuc
    return sonuc


def kalem_ozet(kalem: dict[str, Any]) -> str:
    s = (kalem.get("sekil") or "").strip()
    if not s:
        return ""
    if s == NAKIT:
        alt = kalem.get("alt") or "Havale"
        return f"{s} ({alt})"
    if s == KREDI_KARTI:
        return f"{s} — {kk_taksit_etiket(kalem.get('taksit'))}"
    if s in VADELI_SEKILLER:
        parcalar = [s]
        g = kalem.get("gun")
        if g is not None:
            parcalar.append(f"{int(g)} gün")
        v = kalem.get("vade")
        if isinstance(v, date):
            parcalar.append(f"vade {v.strftime('%d.%m.%Y')}")
        elif isinstance(v, str) and v.strip():
            parcalar.append(f"vade {v.strip()}")
        return " — ".join(parcalar)
    return s


def odeme_ozet_listeden(kalemler: list[dict[str, Any]]) -> str:
    return "; ".join(kalem_ozet(k) for k in kalemler if (k.get("sekil") or "").strip())


def odeme_ozet(
    sekil: str | None,
    *,
    taksit: int | None = None,
    vade_gun: int | None = None,
    vade_tarihi: date | None = None,
    alt: str | None = None,
) -> str:
    """Tekli / geri uyumluluk özeti."""
    return kalem_ozet(
        {
            "sekil": sekil,
            "alt": alt,
            "taksit": taksit,
            "gun": vade_gun,
            "vade": vade_tarihi,
        }
    )


def odeme_sekil_normalize(ham: str | None) -> str:
    metin = (ham or "").strip()
    if not metin:
        return ""
    # Çoklu özet: ilk parçayı al
    ilk = metin.split(";")[0].strip()
    for s in ODEME_SEKILLERI:
        if ilk.casefold() == s.casefold() or ilk.casefold().startswith(s.casefold()):
            return s
    m = ilk.casefold().replace("ı", "i").replace("İ", "i")
    if "kredi" in m or "kk" in m or "kart" in m:
        return KREDI_KARTI
    if "cek" in m or "çek" in ilk.casefold():
        return "Çek"
    if "senet" in m:
        return "Senet"
    if "acik" in m or "açık" in ilk.casefold():
        return "Açık Hesap"
    if "nakit" in m or "pesin" in m or "peşin" in ilk.casefold() or "havale" in m or "kasa" in m:
        return NAKIT
    return ""


def _tarih_seri(v: Any) -> str | None:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _tarih_coz(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date):
        return v
    metin = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            from datetime import datetime

            return datetime.strptime(metin[:10] if fmt.startswith("%Y") else metin, fmt).date()
        except ValueError:
            continue
    return None


def kalemleri_serileştir(kalemler: list[dict[str, Any]]) -> str:
    temiz = []
    for k in kalemler:
        if not (k.get("sekil") or "").strip():
            continue
        temiz.append(
            {
                "sekil": k.get("sekil"),
                "alt": k.get("alt"),
                "taksit": k.get("taksit"),
                "gun": k.get("gun"),
                "vade": _tarih_seri(k.get("vade")),
            }
        )
    return json.dumps(temiz, ensure_ascii=False)


def kalemleri_yukle(ham: str | None) -> list[dict[str, Any]]:
    metin = (ham or "").strip()
    if not metin:
        return []
    try:
        veri = json.loads(metin)
    except json.JSONDecodeError:
        return []
    if not isinstance(veri, list):
        return []
    sonuc = []
    for k in veri:
        if not isinstance(k, dict):
            continue
        sonuc.append(
            {
                "sekil": k.get("sekil"),
                "alt": k.get("alt"),
                "taksit": k.get("taksit"),
                "gun": k.get("gun"),
                "vade": _tarih_coz(k.get("vade")),
            }
        )
    return sonuc


def kayittan_odeme(teklif: Any) -> dict[str, Any]:
    """Model / ORM → UI veri sözlüğü."""
    kalemler = kalemleri_yukle(getattr(teklif, "odeme_json", None))
    if not kalemler:
        sekil = odeme_sekil_normalize(getattr(teklif, "odeme_sekli", None))
        if sekil:
            kalemler = [
                {
                    "sekil": sekil,
                    "alt": getattr(teklif, "odeme_nakit_turu", None) or ("Havale" if sekil == NAKIT else None),
                    "taksit": getattr(teklif, "odeme_taksit", None),
                    "gun": getattr(teklif, "odeme_vade_gun", None),
                    "vade": getattr(teklif, "odeme_vade_tarihi", None),
                }
            ]
    ozet = odeme_ozet_listeden(kalemler) or (getattr(teklif, "odeme_sekli", None) or "")
    ilk = kalemler[0] if kalemler else {}
    return {
        "odeme_sekli": ozet,
        "odeme_taksit": ilk.get("taksit"),
        "odeme_vade_gun": ilk.get("gun"),
        "odeme_vade_tarihi": ilk.get("vade"),
        "odeme_nakit_turu": ilk.get("alt") if ilk.get("sekil") == NAKIT else None,
        "odeme_json": kalemleri_serileştir(kalemler) if kalemler else None,
        "kalemler": kalemler,
        "ozet": ozet,
    }
