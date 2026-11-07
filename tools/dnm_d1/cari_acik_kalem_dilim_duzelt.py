"""Açık kalem: 2015–2019 çok yıllık ERR dilimini yıllık dilimlere böl; detay_yok + cari22 yeniden.

Stok/kasa yeniden toplanmaz. Yazdır beklenmez — API finans_jq ile devam.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.cari_acik_kalem_dilim_duzelt
"""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from entegrasyon.evobulut_client import EvobulutClient, load_credentials
from tools.dnm_d1._ortak import CALISMA, KAYNAK, yaz_json
from tools.dnm_d1.acik_kalem_cek import (
    JSONL,
    _cari_acik,
    _dilimler,
    _yaslandir,
)
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK

ACIK = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}ACIK_KALEM.json"
CARI22 = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_CARI22_KAPANIS_KANIT.json"
OUT = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_CARI_ACIK_KALEM_DILIM_DUZELT.json"
OZET = CALISMA / "CARI_ACIK_KALEM_DILIM_DUZELT_OZET.json"


def _yillik_2015_2019() -> list[tuple[str, str]]:
    out = []
    for y in range(2015, 2020):
        out.append((f"01.01.{y}", f"31.12.{y}"))
    return out


def _dilimler_duzgun() -> list[tuple[str, str]]:
    """Mevcut _dilimler + 2015-2019 garantili yıllık (çok yıllık blok yok)."""
    seen = set()
    out: list[tuple[str, str]] = []
    for bas, son in list(_dilimler()) + _yillik_2015_2019():
        # red flag: span > 366 days
        try:
            b = date(int(bas[6:]), int(bas[3:5]), int(bas[0:2]))
            s = date(int(son[6:]), int(son[3:5]), int(son[0:2]))
            if (s - b).days > 366:
                continue
        except ValueError:
            continue
        key = (bas, son)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def main() -> int:
    # Patch dilimler used by _cari_acik via module attribute if needed —
    # instead call _cari_acik after monkeypatch
    import tools.dnm_d1.acik_kalem_cek as mod

    mod._dilimler = _dilimler_duzgun  # type: ignore[assignment]

    ak = json.loads(ACIK.read_text(encoding="utf-8")) if ACIK.is_file() else {"cariler": []}
    detay_yok_ids = []
    for c in ak.get("cariler") or []:
        if c.get("detay_yok_uyari") or int(c.get("detay_birlesen_adet") or 0) == 0:
            # yalnız özet bakiye ≠ 0 veya uyarı olanlar öncelik
            from tools.dnm_d1._ortak import dec

            oz = c.get("kapanis_ozet_umum") or {}
            if c.get("detay_yok_uyari") or abs(dec(oz.get("bakiye"))) > 0:
                detay_yok_ids.append(str(c["kaynak_cari_id"]))

    c22 = json.loads(CARI22.read_text(encoding="utf-8")) if CARI22.is_file() else {}
    cari22_ids = []
    for c in c22.get("cariler") or []:
        if c.get("kanit_durumu") != "KANITLI" and not c.get("kapanis_bakiye_3108_kanitli"):
            cari22_ids.append(str(c.get("kaynak_cari_id")))

    # birleşik hedef: tüm cari22 + özet bakiyeli detay_yok (üst sınır)
    hedefler = []
    seen = set()
    for mid in cari22_ids + detay_yok_ids[:40]:
        if mid in seen:
            continue
        seen.add(mid)
        hedefler.append(mid)
    print(f"hedef_cari={len(hedefler)} cari22={len(cari22_ids)} detay_yok_aday={len(detay_yok_ids)}", flush=True)

    client = EvobulutClient(load_credentials())
    client.login()

    yenilenen = []
    # jsonl append for updated
    mevcut_jsonl: dict[str, dict] = {}
    if JSONL.is_file():
        with JSONL.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                o = json.loads(line)
                mid = str(o.get("kaynak_cari_id") or "")
                if mid:
                    mevcut_jsonl[mid] = o

    for i, mid in enumerate(hedefler, 1):
        if i % 10 == 0:
            client.login()
            print(f"cari_acik {i}/{len(hedefler)}", flush=True)
        try:
            row = _cari_acik(client, mid)
        except Exception as exc:  # noqa: BLE001
            row = {
                "kaynak_cari_id": mid,
                "status": "ERR",
                "hata": f"{type(exc).__name__}:{exc}"[:200],
                "detay_birlesen_adet": 0,
                "acik_kalem_adet": 0,
            }
        row["alim_zamani"] = datetime.now().astimezone().isoformat(timespec="seconds")
        row["dilim_duzeltme"] = True
        # çok yıllık ERR kaldı mı?
        row["cok_yillik_err_kaldi"] = any(
            (d.get("status") == "ERR" and "1 yıldan" in str(d.get("hata") or ""))
            for d in (row.get("dilimler") or [])
        )
        mevcut_jsonl[mid] = row
        yenilenen.append(
            {
                "kaynak_cari_id": mid,
                "detay_birlesen_adet": row.get("detay_birlesen_adet"),
                "acik_kalem_adet": row.get("acik_kalem_adet"),
                "acik_kalem_toplam": row.get("acik_kalem_toplam"),
                "detay_yok_uyari": row.get("detay_yok_uyari"),
                "cok_yillik_err_kaldi": row.get("cok_yillik_err_kaldi"),
                "kapanis_son_detay_bakiye": row.get("kapanis_son_detay_bakiye"),
            }
        )
        time.sleep(0.05)

    with JSONL.open("w", encoding="utf-8") as f:
        for mid, o in sorted(mevcut_jsonl.items(), key=lambda x: int(x[0] or 0)):
            f.write(json.dumps(o, ensure_ascii=False) + "\n")

    # cari22 güncelle
    by_new = {str(x["kaynak_cari_id"]): x for x in yenilenen}
    if c22.get("cariler"):
        kanitli = 0
        for c in c22["cariler"]:
            mid = str(c.get("kaynak_cari_id"))
            neu = mevcut_jsonl.get(mid)
            if not neu:
                continue
            det = int(neu.get("detay_birlesen_adet") or 0)
            if det > 0 and neu.get("kapanis_son_detay_bakiye") is not None:
                c["kanit_durumu"] = "KANITLI_DETAY"
                c["kapanis_bakiye_3108_kanitli"] = True
                c["detay_satir_adet"] = det
                c["kanitli"] = True
                c["kaynak"] = "finans_jq dilim düzeltme"
                kanitli += 1
            elif mid in by_new:
                c["son_deneme"] = by_new[mid]
        c22["kanitli_adet"] = sum(
            1
            for c in c22["cariler"]
            if c.get("kanit_durumu", "").startswith("KANITLI") or c.get("kapanis_bakiye_3108_kanitli")
        )
        c22["kanitsiz_adet"] = c22.get("adet_22", 22) - c22["kanitli_adet"]
        c22["zaman"] = datetime.now().astimezone().isoformat(timespec="seconds")
        c22["dilim_duzeltme"] = True
        yaz_json(CARI22, c22)

    out = {
        "format": "d1-cari-acik-kalem-dilim-duzelt-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "hedef_adet": len(hedefler),
        "yenilenen_adet": len(yenilenen),
        "detay_gelen": sum(1 for x in yenilenen if int(x.get("detay_birlesen_adet") or 0) > 0),
        "hala_detay_yok": sum(1 for x in yenilenen if not int(x.get("detay_birlesen_adet") or 0)),
        "cok_yillik_err_kaldi": sum(1 for x in yenilenen if x.get("cok_yillik_err_kaldi")),
        "cari22_kanitli": c22.get("kanitli_adet"),
        "cari22_kanitsiz": c22.get("kanitsiz_adet"),
        "kayitlar": yenilenen[:80],
        "eksik_kaynak": (
            "Bazı carilerde finans_jq tüm yıllık dilimlerde Detay boş — "
            "UI Yazdır ekstre veya farklı API gerekir; beklerken diğer işler sürer"
        ),
        "aktarim_engeli": True,
        "k05": False,
        "stok_yeniden_toplanmadi": True,
        "kasa_yeniden_toplanmadi": True,
    }
    yaz_json(OUT, out)
    ozet = {
        "zaman": out["zaman"],
        "hedef": out["hedef_adet"],
        "detay_gelen": out["detay_gelen"],
        "hala_detay_yok": out["hala_detay_yok"],
        "cari22_kanitli": out["cari22_kanitli"],
        "cari22_kanitsiz": out["cari22_kanitsiz"],
        "aktarim_engeli": True,
        "k05": False,
        "kanit": str(OUT.relative_to(CALISMA)).replace("\\", "/"),
    }
    yaz_json(OZET, ozet)
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
