"""Stok miktar + maliyet (FIFO/ort/alış) kapanışı; LOT izi fatura Seri_Lot_List’ten.

StokHareket/base list bu firmada boş döndüğü için hareket satırı yoksa kart sql kullanılır.
Salt okuma. Ara: STOK_MALIYET.jsonl

  .venv\\Scripts\\python.exe -m tools.dnm_d1.stok_maliyet_cek
  .venv\\Scripts\\python.exe -m tools.dnm_d1.stok_maliyet_cek --limit 100 --yeniden
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from tools.dnm_d1._ortak import KAYNAK, dec, dec_opt, oturum_gecersiz_mi, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK

JSONL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_MALIYET.jsonl"


def _stok_sql(c, sid: str, *, yeniden: bool = True) -> dict[str, Any]:
    y = c._post(
        "stok/base/",
        {
            "cmd": "sql",
            "UID": c.uid,
            "a_stok_id": str(sid),
            "grupgetir": "1",
            "a_barkod": "",
        },
    )
    if oturum_gecersiz_mi(y) and yeniden:
        c.login()
        return _stok_sql(c, sid, yeniden=False)
    veri = y.get("veri") or {}
    ana = veri.get("Ana") if isinstance(veri, dict) else None
    if isinstance(ana, list) and ana and isinstance(ana[0], dict):
        return ana[0]
    return {}


def _kart_kapanis(r: dict, *, sid: str) -> dict[str, Any]:
    kalan = dec_opt(r.get("a_kalan"))
    fifo = dec_opt(r.get("a_maliyet_fifo"))
    ort = dec_opt(r.get("a_maliyet_ort"))
    alis = dec_opt(r.get("a_fiyat_al"))
    env = dec_opt(r.get("a_envfiy"))
    birim = fifo if fifo is not None else (ort if ort is not None else alis)
    tutar = None
    if kalan is not None and birim is not None:
        tutar = (kalan * birim).quantize(Decimal("0.0001"))
    return {
        "kaynak_stok_id": sid,
        "kod": r.get("a_kod"),
        "adi": r.get("a_adi"),
        "birim_id": r.get("a_brm_id"),
        "giren": str(dec(r.get("a_giren"))) if r.get("a_giren") not in (None, "") else None,
        "cikan": str(dec(r.get("a_cikan"))) if r.get("a_cikan") not in (None, "") else None,
        "kalan": str(kalan) if kalan is not None else None,
        "maliyet_fifo": str(fifo) if fifo is not None else None,
        "maliyet_ort": str(ort) if ort is not None else None,
        "fiyat_al": str(alis) if alis is not None else None,
        "envfiy": str(env) if env is not None else None,
        "birim_maliyet_secilen": str(birim) if birim is not None else None,
        "maliyet_kaynagi": (
            "a_maliyet_fifo"
            if fifo is not None
            else ("a_maliyet_ort" if ort is not None else ("a_fiyat_al" if alis is not None else None))
        ),
        "toplam_maliyet": str(tutar) if tutar is not None else None,
        "maliyet_fifo_tar": r.get("a_maliyet_fifo_tar"),
        "maliyet_ort_tar": r.get("a_maliyet_ort_tar"),
        "doviz_al": r.get("dov_al_kodu") or r.get("doviz_al_sembol"),
        "alim_zamani": datetime.now().astimezone().isoformat(timespec="seconds"),
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "uyari": (
            "StokHareket list boş; LOT katmanı fatura Seri_Lot_List + kart maliyeti. "
            "API maliyet tarihi görüntü anına yakın olabilir."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--yeniden", action="store_true")
    p.add_argument("--sifir-dahil", action="store_true")
    args = p.parse_args(argv)

    stok_yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_MIKTAR.json"
    kayitlar = json.loads(stok_yol.read_text(encoding="utf-8")).get("kayitlar") or []
    ids: list[str] = []
    for r in kayitlar:
        sid = str(r.get("a_id") or "")
        if not sid:
            continue
        if args.sifir_dahil or dec(r.get("a_kalan")) != 0:
            ids.append(sid)
    if args.limit:
        ids = ids[: args.limit]

    KAYNAK.mkdir(parents=True, exist_ok=True)
    if args.yeniden and JSONL.is_file():
        JSONL.unlink()

    basarili: dict[str, dict] = {}
    if JSONL.is_file() and not args.yeniden:
        for line in JSONL.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                o = json.loads(line)
                sid = str(o.get("kaynak_stok_id") or "")
                if sid and o.get("kalan") is not None:
                    basarili[sid] = o
            except json.JSONDecodeError:
                pass

    c = EvobulutClient(load_credentials())
    c.login()
    t0 = time.time()
    yeni = 0
    tmp = JSONL.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for o in basarili.values():
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
        for i, sid in enumerate(ids, 1):
            if sid in basarili:
                continue
            try:
                if i % 40 == 0:
                    c.login()
                ham = _stok_sql(c, sid)
                if not ham:
                    f.write(
                        json.dumps(
                            {"kaynak_stok_id": sid, "hata": "BOS_SQL"},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                else:
                    kayit = _kart_kapanis(ham, sid=sid)
                    f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
                    basarili[sid] = kayit
                    yeni += 1
                f.flush()
            except Exception as exc:  # noqa: BLE001
                f.write(
                    json.dumps(
                        {
                            "kaynak_stok_id": sid,
                            "hata": type(exc).__name__,
                            "mesaj": str(exc)[:200],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                f.flush()
            if i % 25 == 0 or i == len(ids):
                print(
                    f"stok_maliyet {i}/{len(ids)} yeni={yeni} ok={len(basarili)} "
                    f"gecen={time.time()-t0:.0f}s",
                    flush=True,
                )
            time.sleep(0.01)
    tmp.replace(JSONL)

    liste = list(basarili.values())
    toplam_maliyet = sum(
        (dec(x.get("toplam_maliyet")) for x in liste if x.get("toplam_maliyet") is not None),
        Decimal("0"),
    )
    toplam_miktar = sum(
        (dec(x.get("kalan")) for x in liste if x.get("kalan") is not None),
        Decimal("0"),
    )
    out = {
        "format": "d1-kaynak-stok-maliyet-v1",
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "adet": len(liste),
        "hedef_adet": len(ids),
        "tamam_mi": len(liste) >= len(ids),
        "toplam_kalan_miktar": str(toplam_miktar),
        "toplam_maliyet_tl": str(toplam_maliyet),
        "lot_hareket_api": "BOS_StokHareket_list",
        "stoklar": liste,
        "kapanis_durumu": "STOK_KART_MALIYET" if len(liste) >= len(ids) else "KISMI_STOK_MALIYET",
    }
    yaz_kaynak("STOK_MALIYET", out)
    print(
        "OZET stok",
        out["adet"],
        "miktar",
        out["toplam_kalan_miktar"],
        "maliyet",
        out["toplam_maliyet_tl"],
        flush=True,
    )
    return 0 if out["tamam_mi"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
