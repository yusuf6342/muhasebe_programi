"""Kasa↔Banka transfer karşı bacakları (tur 22/23).

EvoBulut KasaHareketleri jq_list Bankadan Çekilen / Bankaya Yatırılan
satırlarını döndürmüyor; aynı olay BankHareketleri'nde tur 22/23 + MKB=kasa
ile duruyor. Bu modül kasa kapsamına **görünüm** satırı ekler; banka hareketi
çoğaltılmaz; yeni cari/gelir/gider üretilmez.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.kasa_banka_transfer_bacak
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from tools.dnm_d1._ortak import KAYNAK, parse_tarih, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.kapanis_kasa_banka import _yon_tutar

BANKA_TUR_YATIRILAN = "22"  # Bankaya Yatırılan → kasa çıkan
BANKA_TUR_CEKILEN = "23"  # Bankadan Çekilen → kasa giren
KARSI_FLAG = "karsi_bacak_bankadan"


def _norm(s: str) -> str:
    s = (s or "").upper().replace("İ", "I").replace("ı", "I")
    for a, b in (("Ş", "S"), ("Ğ", "G"), ("Ü", "U"), ("Ö", "O"), ("Ç", "C")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def _kasa_ad_index(kartlar: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k in kartlar:
        kid = str(k.get("id") or "")
        ad = str(k.get("text") or "").strip()
        if kid and ad:
            out[_norm(ad)] = kid
    return out


def _mevcut_banka_linkleri(hareketler: list[dict]) -> set[str]:
    ids: set[str] = set()
    for h in hareketler:
        if h.get(KARSI_FLAG):
            bid = str(h.get("banka_G.a_id") or "")
            if bid:
                ids.add(bid)
            continue
        # Ham kasa satırında tur adı banka transferi ise (ileride API gelirse)
        tur = str(h.get("FIN_TUR.a_adi") or "")
        if tur in ("Bankadan Çekilen", "Bankaya Yatırılan"):
            # Kimlik yoksa tarih+tutar ile bankaya bağlanacak; şimdilik tur var say
            ids.add(f"HAM:{h.get('G.a_id')}")
    return ids


def bankadan_kasa_karsi_bacaklar(
    banka_hareketler: list[dict],
    kasa_kartlar: list[dict],
    *,
    mevcut_kasa_hareketler: list[dict] | None = None,
    donem_sonu=DONEM_SONU,
) -> list[dict[str, Any]]:
    """Banka tur 22/23 → kasa görünüm satırları (idempotent ekleme için banka_G.a_id)."""
    ad_idx = _kasa_ad_index(kasa_kartlar)
    mevcut_link = _mevcut_banka_linkleri(mevcut_kasa_hareketler or [])
    out: list[dict[str, Any]] = []

    for h in banka_hareketler:
        tur_id = str(h.get("G.a_tur_id") or "")
        if tur_id not in {BANKA_TUR_YATIRILAN, BANKA_TUR_CEKILEN}:
            continue
        t = parse_tarih(h.get("G.a_tarih"))
        if t is None or t > donem_sonu:
            continue
        mkb = str(h.get("MKB") or "").strip()
        kasa_id = ad_idx.get(_norm(mkb))
        if not kasa_id:
            continue
        bid = str(h.get("G.a_id") or "")
        if not bid or bid in mevcut_link:
            continue

        g, c = _yon_tutar(h)
        g = g or Decimal("0")
        c = c or Decimal("0")
        tur_adi = str(h.get("FIN_TUR.a_adi") or "")

        # Kasa yönü: bankadan çekilen → kasa giren; bankaya yatırılan → kasa çıkan
        if tur_id == BANKA_TUR_CEKILEN:
            k_giren, k_cikan = c, Decimal("0")  # banka çıkan = kasa giren
            if g != 0:
                # Beklenmeyen: banka tarafında giren dolu
                continue
        else:
            k_giren, k_cikan = Decimal("0"), g  # banka giren = kasa çıkan
            if c != 0:
                continue

        out.append(
            {
                "G.a_id": f"KB-{bid}",
                "G.a_kasa_id": kasa_id,
                "TBL_KASA.a_adi": mkb,
                "G.a_tur_id": tur_id,
                "FIN_TUR.a_adi": tur_adi,
                "G.a_tarih": h.get("G.a_tarih"),
                "G.a_vtarih": h.get("G.a_vtarih"),
                "G.a_ack": h.get("G.a_ack"),
                "G.a_giren": str(k_giren),
                "G.a_cikan": str(k_cikan),
                "G.a_dov_id": h.get("G.a_dov_id"),
                "FIN_DOV.a_kod": h.get("FIN_DOV.a_kod") or "TL",
                "FIN_DOV.a_adi": h.get("FIN_DOV.a_adi"),
                "MKB": h.get("TBL_BANKA.a_adi"),
                "MKB_KOD": None,
                "G.a_belge_no": h.get("G.a_belge_no"),
                "G.a_kontrol": h.get("G.a_kontrol"),
                "G.a_ref_id": h.get("G.a_ref_id"),
                "G.a_modul_id": h.get("G.a_modul_id"),
                "G.a_mudul_ref_id": h.get("G.a_mudul_ref_id"),
                KARSI_FLAG: True,
                "banka_G.a_id": bid,
                "banka_hesap_id": str(h.get("G.a_banka_id") or ""),
                "banka_hesap_adi": h.get("TBL_BANKA.a_adi"),
                "aciklama_kapsam": (
                    "Kasa jq_list bu türü döndürmedi; banka tur 22/23 kaydının "
                    "kasa görünümü. Banka hareketi çoğaltılmaz."
                ),
            }
        )
        mevcut_link.add(bid)
    return out


def kasa_hareketlerini_zenginlestir(
    kasa: dict[str, Any], banka: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """KASA ham dict'e karşı bacak ekler; özet meta döner. İdempotent."""
    kartlar = list(kasa.get("kartlar") or [])
    hareketler = list(kasa.get("hareketler") or [])
    once = len(hareketler)
    once_link = len(_mevcut_banka_linkleri(hareketler))
    ekler = bankadan_kasa_karsi_bacaklar(
        list(banka.get("hareketler") or []),
        kartlar,
        mevcut_kasa_hareketler=hareketler,
    )
    hareketler.extend(ekler)
    kasa = {
        **kasa,
        "hareketler": hareketler,
        "hareket_adet": len(hareketler),
        "karsi_bacak_bankadan": {
            "eklenen_adet": len(ekler),
            "onceki_hareket_adet": once,
            "onceki_link_adet": once_link,
            "sonraki_hareket_adet": len(hareketler),
            "olcut": "BANKA tur_id 22/23 + MKB=kasa adı → kasa görünümü",
            "banka_hareket_cogaltilmadi": True,
            "yeni_cari_gelir_gider_yok": True,
        },
    }
    ozet = {
        "eklenen": len(ekler),
        "kasa_hesap_dagilim": {},
        "tur_dagilim": {},
    }
    from collections import Counter

    kd: Counter = Counter()
    td: Counter = Counter()
    for e in ekler:
        kd[str(e.get("G.a_kasa_id"))] += 1
        td[str(e.get("FIN_TUR.a_adi"))] += 1
    ozet["kasa_hesap_dagilim"] = dict(kd)
    ozet["tur_dagilim"] = dict(td)
    return kasa, ozet


def zenginlestir_kaynak_dosyalari() -> dict[str, Any]:
    kasa_yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}KASA.json"
    banka_yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BANKA.json"
    kasa = json.loads(kasa_yol.read_text(encoding="utf-8"))
    banka = json.loads(banka_yol.read_text(encoding="utf-8"))
    banka_adet_once = len(banka.get("hareketler") or [])

    kasa2, ozet = kasa_hareketlerini_zenginlestir(kasa, banka)
    # İkinci geçiş idempotent (meta birinci geçişe kilitlenir)
    kasa3, ozet2 = kasa_hareketlerini_zenginlestir(copy.deepcopy(kasa2), banka)
    if ozet["eklenen"] > 0:
        kasa2["karsi_bacak_bankadan"] = {
            **(kasa2.get("karsi_bacak_bankadan") or {}),
            "eklenen_adet": ozet["eklenen"],
            "idempotent_dogrulandi": ozet2["eklenen"] == 0,
        }
    banka_adet_sonra = len(banka.get("hareketler") or [])

    ham = json.dumps(kasa2, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    kasa_yol.write_bytes(ham)
    sha = hashlib.sha256(ham).hexdigest().upper()
    kasa_yol.with_suffix(".sha256").write_text(f"{sha}  {kasa_yol.name}\n", encoding="ascii")
    # BANKA.json dokunulmadı — yeniden yazma

    return {
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kasa_sha16": sha[:16],
        "birinci_ekleme": ozet,
        "ikinci_gecis_ekleme": ozet2,
        "idempotent": ozet2["eklenen"] == 0,
        "banka_hareket_adet_once": banka_adet_once,
        "banka_hareket_adet_sonra": banka_adet_sonra,
        "banka_degismedi": banka_adet_once == banka_adet_sonra,
    }


def main() -> int:
    sonuc = zenginlestir_kaynak_dosyalari()
    yaz_kaynak("DOGRULAMA_KASA_BANKA_KARSI_BACAK_ZENGINLESTIRME", sonuc)
    # kapanış yeniden
    from tools.dnm_d1.kapanis_kasa_banka import kapanis_uret, _yaz

    kasa_kap = kapanis_uret("KASA", "kasa")
    # NAKİT kontrol notu
    for h in kasa_kap.get("hesaplar") or []:
        if str(h.get("hesap_id")) == "1":
            h["nakit_excel_hedef_kapanis"] = "2209.55"
            h["karsi_bacak_dahil"] = True
    kasa_kap["karsi_bacak_bankadan_dahil"] = True
    kasa_kap["kapanis_durumu"] = "KISMI_HAREKET_NETI_KARSİ_BACAK_DAHIL"
    _yaz("KASA_KAPANIS", kasa_kap)
    print(json.dumps(sonuc, ensure_ascii=False), flush=True)
    nakit = next(h for h in kasa_kap["hesaplar"] if str(h["hesap_id"]) == "1")
    print(
        "NAKIT",
        nakit["brut_giris"],
        nakit["brut_cikis"],
        nakit["kapanis_net"],
        nakit["hareket_adet"],
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
