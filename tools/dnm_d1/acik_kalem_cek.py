"""Cari açık kalem / vade / valör — finans_jq_listesi Detay (≤1 yıl dilimler).

Özet.Bakiye dönem kapanışı değildir; kapanış = Devreden + Detay neti / son satır Bakiye.
Salt okuma. Ara: ACIK_KALEM.jsonl

  .venv\\Scripts\\python.exe -m tools.dnm_d1.acik_kalem_cek
  .venv\\Scripts\\python.exe -m tools.dnm_d1.acik_kalem_cek --limit 20 --yeniden
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from tools.dnm_d1._ortak import KAYNAK, dec, oturum_gecersiz_mi, parse_tarih, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK

JSONL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}ACIK_KALEM.jsonl"


def _ozet_blok(blok: Any) -> dict[str, str]:
    if isinstance(blok, list) and blok:
        b = blok[0] if isinstance(blok[0], dict) else {}
    elif isinstance(blok, dict):
        b = blok
    else:
        b = {}
    return {
        "borc": str(dec(b.get("Borc") or b.get("borc"))),
        "alacak": str(dec(b.get("Alacak") or b.get("alacak"))),
        "bakiye": str(dec(b.get("Bakiye") or b.get("bakiye"))),
    }


def _dilimler(son: date = DONEM_SONU) -> list[tuple[str, str]]:
    """Kapanış 1y penceresi + 2015..son yıllık dilimler (id ile birleştirilir)."""
    out: list[tuple[str, str]] = [
        (date(2025, 9, 1).strftime("%d.%m.%Y"), son.strftime("%d.%m.%Y"))
    ]
    for yil in range(son.year, 2014, -1):
        bas = date(yil, 1, 1)
        bit = min(date(yil, 12, 31), son)
        if bas <= son:
            out.append((bas.strftime("%d.%m.%Y"), bit.strftime("%d.%m.%Y")))
    return out


def _cek(c, mid: str, bas: str, son: str, *, yeniden: bool = True) -> dict[str, Any]:
    y = c._post(
        "Musteri/base/",
        {
            "cmd": "finans_jq_listesi",
            "UID": c.uid,
            "musteri_id": str(mid),
            "b_tarihi": bas,
            "s_tarihi": son,
            "tur": "-1",
        },
    )
    if oturum_gecersiz_mi(y) and yeniden:
        c.login()
        return _cek(c, mid, bas, son, yeniden=False)
    if y.get("status") != "OK":
        return {
            "bas": bas,
            "son": son,
            "status": y.get("status"),
            "hata": y.get("veri"),
            "detay": [],
            "devreden": None,
            "ozet": None,
        }
    veri = y.get("veri")
    if not isinstance(veri, dict):
        return {
            "bas": bas,
            "son": son,
            "status": "ERR",
            "hata": veri,
            "detay": [],
            "devreden": None,
            "ozet": None,
        }
    det = veri.get("Detay") or []
    if not isinstance(det, list):
        det = []
    return {
        "bas": bas,
        "son": son,
        "status": "OK",
        "detay": [x for x in det if isinstance(x, dict)],
        "devreden": _ozet_blok(veri.get("Devreden")),
        "ozet": _ozet_blok(veri.get("Özet") or veri.get("Ozet")),
        "detay_toplam_sayisi": veri.get("Detay_Toplam_Sayisi"),
    }


def _fifo_acik(detay: list[dict], *, mid: str) -> tuple[list[dict], Decimal]:
    """Borç satırlarını alacaklarla FIFO kapat; kalan açık kalemler."""
    acik: list[dict[str, Any]] = []
    for row in sorted(
        detay,
        key=lambda r: (parse_tarih(r.get("Tarih")) or date.min, int(str(r.get("Satir") or 0) or 0)),
    ):
        t = parse_tarih(row.get("Tarih"))
        if t is None or t > DONEM_SONU:
            continue
        borc = dec(row.get("Borc"))
        alacak = dec(row.get("Alacak"))
        if borc > 0:
            acik.append(
                {
                    "kaynak_cari_id": mid,
                    "kaynak_hareket_id": str(row.get("id") or ""),
                    "tur": str(row.get("Tur") or ""),
                    "tur_adi": row.get("Tur_adi"),
                    "belge_no": row.get("Belge_NO"),
                    "tarih": t.isoformat(),
                    "vade_tarihi": (
                        parse_tarih(row.get("Vade_Tarihi")).isoformat()
                        if parse_tarih(row.get("Vade_Tarihi"))
                        else None
                    ),
                    "ack": row.get("ACK"),
                    "orijinal_borc": str(borc),
                    "kalan": str(borc),
                    "doviz": row.get("Dov_Sembol") or "TL",
                    "modul_id": row.get("modul_id"),
                    "modulu": row.get("modulu"),
                }
            )
        if alacak > 0 and acik:
            kalan_odeme = alacak
            for item in acik:
                ik = dec(item["kalan"])
                if ik <= 0:
                    continue
                kullan = min(ik, kalan_odeme)
                item["kalan"] = str(ik - kullan)
                kalan_odeme -= kullan
                if kalan_odeme <= 0:
                    break
    kalan_liste = [x for x in acik if dec(x["kalan"]) > 0]
    toplam = sum((dec(x["kalan"]) for x in kalan_liste), Decimal("0"))
    return kalan_liste, toplam


def _yaslandir(kalemler: list[dict], bugun: date = DONEM_SONU) -> dict[str, str]:
    buckets = {
        "vadesi_gelmemis": Decimal("0"),
        "0_30": Decimal("0"),
        "31_60": Decimal("0"),
        "61_90": Decimal("0"),
        "91_plus": Decimal("0"),
        "vade_yok": Decimal("0"),
    }
    for k in kalemler:
        tut = dec(k["kalan"])
        vd = parse_tarih(k.get("vade_tarihi"))
        if vd is None:
            buckets["vade_yok"] += tut
            continue
        gun = (bugun - vd).days
        if gun < 0:
            buckets["vadesi_gelmemis"] += tut
        elif gun <= 30:
            buckets["0_30"] += tut
        elif gun <= 60:
            buckets["31_60"] += tut
        elif gun <= 90:
            buckets["61_90"] += tut
        else:
            buckets["91_plus"] += tut
    return {k: str(v) for k, v in buckets.items()}


def _birlestir(birlesen: dict[str, dict], rows: list[dict]) -> None:
    for row in rows:
        rid = str(row.get("id") or "")
        if not rid:
            rid = f"{row.get('Tarih')}|{row.get('Satir')}|{row.get('Borc')}|{row.get('Alacak')}"
        birlesen[rid] = row


def _cari_acik(c, mid: str) -> dict[str, Any]:
    birlesen: dict[str, dict] = {}
    dilim_ozet = []
    kapanis_dev = None
    kapanis_ozet = None
    kapanis_son_bakiye = None
    kapanis_bas = "01.09.2025"
    kapanis_son = DONEM_SONU.strftime("%d.%m.%Y")

    # 1) Kapanış 1y penceresi
    r0 = _cek(c, mid, kapanis_bas, kapanis_son)
    dilim_ozet.append(
        {
            "bas": kapanis_bas,
            "son": kapanis_son,
            "status": r0.get("status"),
            "detay_adet": len(r0.get("detay") or []),
            "devreden": r0.get("devreden"),
            "hata": r0.get("hata"),
        }
    )
    kapanis_dev = r0.get("devreden")
    kapanis_ozet = r0.get("ozet")
    det0 = r0.get("detay") or []
    if det0:
        kapanis_son_bakiye = str(dec(det0[-1].get("Bakiye")))
    _birlestir(birlesen, det0)

    # 2) Devreden ≠ 0 veya kapanış detayı boşsa geriye yıllık dilimler
    ihtiyac_gecmis = abs(dec((kapanis_dev or {}).get("bakiye"))) > 0 or not det0
    if ihtiyac_gecmis:
        bos_yil = 0
        for bas, son in _dilimler()[1:]:
            r = _cek(c, mid, bas, son)
            n = len(r.get("detay") or [])
            dilim_ozet.append(
                {
                    "bas": bas,
                    "son": son,
                    "status": r.get("status"),
                    "detay_adet": n,
                    "devreden": r.get("devreden"),
                    "hata": r.get("hata"),
                }
            )
            _birlestir(birlesen, r.get("detay") or [])
            time.sleep(0.02)
            if n == 0:
                bos_yil += 1
                if bos_yil >= 2:
                    break
            else:
                bos_yil = 0

    detay = list(birlesen.values())
    # Devreden bakiyesi için sentetik kalem (geçmiş detay yoksa)
    dev_bak = dec((kapanis_dev or {}).get("bakiye"))
    # FIFO yalnız gerçek detay üzerinde; Devreden ayrıca raporlanır
    acik, acik_toplam = _fifo_acik(detay, mid=mid)
    # Eğer detay boş ve ozet/devreden sıfır değilse işaretle
    detay_yok = len(detay) == 0 and (
        abs(dec((kapanis_ozet or {}).get("bakiye"))) > 0 or abs(dev_bak) > 0
    )
    if detay_yok and abs(dev_bak) > 0:
        acik.append(
            {
                "kaynak_cari_id": mid,
                "kaynak_hareket_id": "DEVREDEN",
                "tur": "DEVIR",
                "tur_adi": "Devreden (detay yok)",
                "belge_no": "",
                "tarih": None,
                "vade_tarihi": None,
                "ack": "Detay boş; Devreden bakiyesi açık kalem proxy",
                "orijinal_borc": str(abs(dev_bak)),
                "kalan": str(abs(dev_bak)),
                "doviz": "TL",
                "modul_id": None,
                "modulu": None,
                "proxy": True,
            }
        )
        acik_toplam = abs(dev_bak)

    return {
        "kaynak_cari_id": mid,
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "alim_zamani": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kapanis_devreden": kapanis_dev,
        "kapanis_ozet_umum": kapanis_ozet,
        "kapanis_son_detay_bakiye": kapanis_son_bakiye,
        "detay_birlesen_adet": len(detay),
        "acik_kalem_adet": len(acik),
        "acik_kalem_toplam": str(acik_toplam),
        "yaslandirma": _yaslandir(acik),
        "acik_kalemler": acik,
        "dilimler": dilim_ozet,
        "detay_yok_uyari": detay_yok,
        "olcut": "finans_jq_listesi_detay_fifo_v1",
        "uyari": (
            "Özet.Bakiye dönem kapanışı değildir. "
            "Kapanış için son Detay.Bakiye / Devreden+net kullanılır."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--yeniden", action="store_true")
    p.add_argument("--tum", action="store_true", help="Sıfır bakiyeliler dahil")
    args = p.parse_args(argv)

    ekstre_yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}CARI_EKSTRE_KAPANIS.json"
    cariler = json.loads(ekstre_yol.read_text(encoding="utf-8")).get("cariler") or []
    ids: list[str] = []
    for r in cariler:
        cid = str(r.get("kaynak_cari_id") or "")
        if not cid:
            continue
        if args.tum:
            ids.append(cid)
            continue
        bak = dec(r.get("kapanis_bakiye"))
        # Özet yanıltıcı olabilir; sıfır-dışı veya detay_adet>0 olanları al
        if bak != 0 or int(r.get("detay_satir_adet") or 0) > 0:
            ids.append(cid)
        elif abs(bak) == 0:
            # yine de ozet borc/alacak varsa
            if dec(r.get("kapanis_borc_ozet")) != 0 or dec(r.get("kapanis_alacak_ozet")) != 0:
                ids.append(cid)
    # Tekrarları koru sırayla
    seen = set()
    uniq = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            uniq.append(i)
    ids = uniq
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
                cid = str(o.get("kaynak_cari_id") or "")
                if cid and o.get("acik_kalemler") is not None:
                    basarili[cid] = o
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
        for i, cid in enumerate(ids, 1):
            if cid in basarili:
                if i % 50 == 0:
                    print(f"atlandi {i}/{len(ids)}", flush=True)
                continue
            try:
                if i % 25 == 0:
                    c.login()
                kayit = _cari_acik(c, cid)
                f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
                f.flush()
                basarili[cid] = kayit
                yeni += 1
            except Exception as exc:  # noqa: BLE001
                f.write(
                    json.dumps(
                        {
                            "kaynak_cari_id": cid,
                            "hata": type(exc).__name__,
                            "mesaj": str(exc)[:240],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                f.flush()
            if i % 5 == 0 or i == len(ids):
                print(
                    f"acik_kalem {i}/{len(ids)} yeni={yeni} ok={len(basarili)} "
                    f"gecen={time.time()-t0:.0f}s",
                    flush=True,
                )
    tmp.replace(JSONL)

    liste = list(basarili.values())
    tum_kalem = []
    for x in liste:
        tum_kalem.extend(x.get("acik_kalemler") or [])
    detay_yok = sum(1 for x in liste if x.get("detay_yok_uyari"))
    out = {
        "format": "d1-kaynak-acik-kalem-v1",
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "cari_adet": len(liste),
        "hedef_cari_adet": len(ids),
        "acik_kalem_adet": len(tum_kalem),
        "acik_kalem_toplam": str(sum((dec(k["kalan"]) for k in tum_kalem), Decimal("0"))),
        "detay_yok_cari_adet": detay_yok,
        "tamam_mi": len(liste) >= len(ids),
        "cariler": liste,
        "kapanis_durumu": "ACIK_KALEM_FIFO" if len(liste) >= len(ids) else "KISMI_ACIK_KALEM",
    }
    yaz_kaynak("ACIK_KALEM", out)
    # Yaşlandırma özet tablosu
    yas = {
        "vadesi_gelmemis": Decimal("0"),
        "0_30": Decimal("0"),
        "31_60": Decimal("0"),
        "61_90": Decimal("0"),
        "91_plus": Decimal("0"),
        "vade_yok": Decimal("0"),
    }
    for x in liste:
        for k, v in (x.get("yaslandirma") or {}).items():
            if k in yas:
                yas[k] += dec(v)
    yaz_kaynak(
        "VADE_YASLANDIRMA",
        {
            "format": "d1-kaynak-vade-yaslandirma-v1",
            "donem_sonu_dahil": DONEM_SONU.isoformat(),
            "buckets": {k: str(v) for k, v in yas.items()},
            "kaynak": "ACIK_KALEM",
        },
    )
    print(
        "OZET acik",
        out["acik_kalem_adet"],
        "toplam",
        out["acik_kalem_toplam"],
        "detay_yok",
        detay_yok,
        flush=True,
    )
    return 0 if out["tamam_mi"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
