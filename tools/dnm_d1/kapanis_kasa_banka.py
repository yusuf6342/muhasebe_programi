"""Mevcut KASA/BANKA ham JSON’dan 31.08.2026 kapanış özetlerini üretir.

Boş değer sıfır yazılmaz. Hareket tarihi parse edilemeyen satırlar ayrı listelenir.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tools.dnm_d1.donem_sabitleri import CALISMA_KOK, DONEM_SONU, RAPOR_ONEKI_KAYNAK

KOK = Path(__file__).resolve().parents[2]
KAYNAK = KOK / CALISMA_KOK / "kaynak"

_TARIH = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})")


def _dec(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        s = str(v).strip().replace(" ", "").replace(",", ".")
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _tarih(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    s = str(v).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    m = _TARIH.search(s)
    if not m:
        return None
    g, a, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if y < 100:
        y += 2000
    try:
        return date(y, a, g)
    except ValueError:
        return None


def _yaz(ad: str, veri: Any) -> Path:
    KAYNAK.mkdir(parents=True, exist_ok=True)
    yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}{ad}.json"
    ham = json.dumps(veri, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    yol.write_bytes(ham)
    ozet = hashlib.sha256(ham).hexdigest().upper()
    yol.with_suffix(".sha256").write_text(f"{ozet}  {yol.name}\n", encoding="ascii")
    print("YAZILDI", yol.name, "sha", ozet[:16], flush=True)
    return yol


def _hesap_id(satir: dict, *, modul: str) -> str:
    if modul == "banka":
        adaylar = ("G.a_banka_id", "a_banka_id", "G.a_bank_id", "a_bank_id")
    else:
        adaylar = ("G.a_kasa_id", "a_kasa_id", "G.a_kas_id", "a_kas_id")
    for k in adaylar:
        if satir.get(k) not in (None, ""):
            return str(satir.get(k))
    return "?"


def _hesap_adi(satir: dict, kartlar: dict[str, str], *, modul: str) -> str:
    hid = _hesap_id(satir, modul=modul)
    if hid in kartlar:
        return kartlar[hid]
    for k in (
        "TBL_BANKA.a_adi",
        "TBL_KASA.a_adi",
        "G.a_kasa_adi",
        "G.a_bank_adi",
        "kasa",
        "banka",
        "text",
    ):
        if satir.get(k):
            return str(satir.get(k))[:120]
    return hid


def _yon_tutar(satir: dict) -> tuple[Decimal | None, Decimal | None]:
    """(giris, cikis) brüt tutarlar."""
    giren = _dec(satir.get("G.a_giren") or satir.get("a_giren") or satir.get("R.a_giren"))
    cikan = _dec(satir.get("G.a_cikan") or satir.get("a_cikan") or satir.get("R.a_cikan"))
    if giren is not None or cikan is not None:
        return giren or Decimal("0"), cikan or Decimal("0")
    tutar = _dec(satir.get("G.a_tutar") or satir.get("a_tutar") or satir.get("tutar"))
    if tutar is None:
        return None, None
    # İşaretli tutar: + giriş, - çıkış varsayımı (kanıt yoksa belirsiz)
    if tutar >= 0:
        return tutar, Decimal("0")
    return Decimal("0"), abs(tutar)


def kapanis_uret(ham_ad: str, modul: str) -> dict[str, Any]:
    yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}{ham_ad}.json"
    ham = json.loads(yol.read_text(encoding="utf-8"))
    kartlar_raw = ham.get("kartlar") or []
    hareketler = ham.get("hareketler") or []
    kart_ad: dict[str, str] = {}
    for k in kartlar_raw:
        kid = str(k.get("id") or k.get("R.a_id") or k.get("a_id") or k.get("G.a_id") or "")
        ad = str(k.get("text") or k.get("R.a_adi") or k.get("a_adi") or kid)
        if kid:
            kart_ad[kid] = ad

    ozet: dict[str, dict[str, Any]] = {}
    parse_hatasi: list[dict] = []
    donem_disi = 0
    donem_ici = 0

    for s in hareketler:
        if not isinstance(s, dict):
            continue
        t = None
        for tk in ("G.a_tarih", "a_tarih", "tarih", "G.a_ftarih"):
            t = _tarih(s.get(tk))
            if t:
                break
        if t is None:
            parse_hatasi.append({"neden": "tarih_yok", "id": s.get("G.a_id") or s.get("a_id")})
            continue
        if t > DONEM_SONU:
            donem_disi += 1
            continue
        donem_ici += 1
        hid = _hesap_id(s, modul=modul)
        g, c = _yon_tutar(s)
        if g is None and c is None:
            parse_hatasi.append({"neden": "tutar_yok", "id": s.get("G.a_id"), "hesap": hid})
            continue
        g = g or Decimal("0")
        c = c or Decimal("0")
        dov = str(
            s.get("FIN_DOV.a_kod")
            or s.get("G.a_dov_adi")
            or s.get("a_dov_adi")
            or "TL"
        )
        row = ozet.setdefault(
            hid,
            {
                "hesap_id": hid,
                "hesap_adi": _hesap_adi(s, kart_ad, modul=modul),
                "para_birimi": dov,
                "brut_giris": Decimal("0"),
                "brut_cikis": Decimal("0"),
                "hareket_adet": 0,
                "ilk_tarih": t.isoformat(),
                "son_tarih": t.isoformat(),
            },
        )
        row["brut_giris"] += g
        row["brut_cikis"] += c
        row["hareket_adet"] += 1
        if t.isoformat() < row["ilk_tarih"]:
            row["ilk_tarih"] = t.isoformat()
        if t.isoformat() > row["son_tarih"]:
            row["son_tarih"] = t.isoformat()

    satirlar = []
    for hid, row in sorted(ozet.items(), key=lambda x: x[0]):
        kapanis = row["brut_giris"] - row["brut_cikis"]
        satirlar.append(
            {
                **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in row.items()},
                "olcut": "hareketlerden_net_kapanis",
                "kapanis_net": str(kapanis),
                "gercek_baslangic": None,  # ayrı devir belgesi yoksa bilinmiyor — sıfır yazılmaz
                "uyari": (
                    "Net = dönem içi brüt giriş − çıkış; kaynak açılış/devir ayrı belgelenmeden "
                    "gerçek başlangıç bilinmiyor sayılır."
                ),
            }
        )

    return {
        "format": f"d1-kaynak-{modul}-kapanis-v1",
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "kaynak_ham": yol.name,
        "kart_adet": len(kartlar_raw),
        "hareket_toplam": len(hareketler),
        "donem_ici_hareket": donem_ici,
        "donem_disi_hareket": donem_disi,
        "tarih_veya_tutar_hatasi": len(parse_hatasi),
        "parse_hata_ornek": parse_hatasi[:50],
        "hesap_adet": len(satirlar),
        "hesaplar": satirlar,
        "kapanis_durumu": "KISMI_HAREKET_NETI",
        "karsi_bacak_bankadan_adet": sum(
            1 for s in hareketler if isinstance(s, dict) and s.get("karsi_bacak_bankadan")
        ),
        "not": (
            "Bu rapor gerçek başlangıç/devir belgesi olmadan net hareket kapanışıdır. "
            "K05 için resmi kaynak kasa/banka ekstresi veya doğrulanmış açılış + hareket gerekir. "
            "Kasa jq_list’te olmayan Bankadan Çekilen/Bankaya Yatırılan bacakları "
            "BANKA tur 22/23 MKB=kasa görünümü ile KASA ham’a eklenmiş olabilir "
            "(banka hareketi çoğaltılmaz)."
        ),
    }


def main() -> int:
    kasa = kapanis_uret("KASA", "kasa")
    banka = kapanis_uret("BANKA", "banka")
    _yaz("KASA_KAPANIS", kasa)
    _yaz("BANKA_KAPANIS", banka)
    print("KASA_HESAP", kasa["hesap_adet"], "BANKA_HESAP", banka["hesap_adet"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
