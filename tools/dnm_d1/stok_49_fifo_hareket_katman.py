"""49 pasif FIFO katman — mevcut STOK_HAREKET_49 (yeniden stok/kimlik yok).

BELGE_SATIR başlığı var ama satır boş olanlarda hareket gir_fiyat kullanılır.
Kart/ortalama maliyet doldurulmaz. Kaynakta yeniden maliyet hesabı yok.
LOT: mevcut LOT_KATMAN_DEVAM ile eşleştirilir.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.stok_49_fifo_hareket_katman
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from tools.dnm_d1._ortak import CALISMA, KAYNAK, parse_tarih, yaz_json
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.stok_envanter_excel_devir1 import EXCEL_HEDEF, _oku_excel, tr_dec

HRK49 = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_HAREKET_49_PASIF.jsonl"
BAGLA = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_49_WEB_PASIF_BAGLA.json"
BELGE = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE_SATIR.jsonl"
LOT = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_LOT_KATMAN_DEVAM.json"
ESLEME = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_3252_HESAPLANABILIR.json"
OUT = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_49_FIFO_HAREKET_KATMAN.json"
OZET = CALISMA / "STOK_49_FIFO_HAREKET_KATMAN_OZET.json"


@dataclass
class Katman:
    sira: int
    belge_id: str
    belge_tur: str | None
    belge_tarih: str | None
    giren: Decimal
    kalan: Decimal
    birim_maliyet: Decimal | None
    maliyet_sinif: str
    kaynak: str
    birim: str | None = None


def _yukle_belge_by_id() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not BELGE.is_file():
        return out
    with BELGE.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            if o.get("status") != "OK":
                continue
            bid = str(o.get("kaynak_belge_id") or "")
            if bid:
                out[bid] = o
    return out


def _fifo_from_hareket(satirlar: list[dict]) -> tuple[list[Katman], str]:
    """Girişleri sırayla katmanla; çıkışları FIFO tüket."""
    olaylar: list[tuple] = []
    for s in satirlar:
        t = parse_tarih(s.get("tarih"))
        if t is None or t > DONEM_SONU:
            continue
        gir = tr_dec(s.get("gir_miktar")) or Decimal("0")
        cik = tr_dec(s.get("cik_miktar")) or Decimal("0")
        if gir > 0:
            olaylar.append(("G", t, s, gir))
        if cik > 0:
            olaylar.append(("C", t, s, cik))
    olaylar.sort(key=lambda x: (x[1], 0 if x[0] == "G" else 1, str(x[2].get("id") or "")))

    q: deque[Katman] = deque()
    sira = 0
    for tip, t, s, mik in olaylar:
        if tip == "G":
            sira += 1
            fiyat = tr_dec(s.get("gir_fiyat"))
            if fiyat is None:
                sinif = "BILINMEYEN"
            elif fiyat == 0:
                sinif = "BEDELSIZ_SIFIR"
            else:
                sinif = "KANITLI_HAREKET_GIR_FIYAT"
            q.append(
                Katman(
                    sira=sira,
                    belge_id=str(s.get("Fat_id") or s.get("id") or ""),
                    belge_tur=s.get("belge_tur") or s.get("Fat_Tur_id"),
                    belge_tarih=t.isoformat(),
                    giren=mik,
                    kalan=mik,
                    birim_maliyet=fiyat if sinif != "BILINMEYEN" else None,
                    maliyet_sinif=sinif,
                    kaynak="STOK_HAREKET_49_PASIF.satirlar",
                    birim=s.get("Birim"),
                )
            )
        else:
            kalan_cik = mik
            while kalan_cik > 0 and q:
                k = q[0]
                al = min(k.kalan, kalan_cik)
                k.kalan -= al
                kalan_cik -= al
                if k.kalan == 0:
                    q.popleft()
            if kalan_cik > 0:
                return list(q), "CIKIS_KATMAN_YETERSIZ"
    return list(q), "OK"


def main() -> int:
    bagla = json.loads(BAGLA.read_text(encoding="utf-8"))
    ids = {str(b["kaynak_stok_id"]): b for b in bagla["baglanan"]}
    excel_by_kod: dict[str, list] = defaultdict(list)
    if ESLEME.is_file():
        es = json.loads(ESLEME.read_text(encoding="utf-8"))
        for s in es.get("satirlar") or []:
            if str(s.get("kaynak_stok_id")) in ids:
                excel_by_kod[str(s["kaynak_stok_id"])].append(s)
    else:
        rows, _ = _oku_excel(EXCEL_HEDEF)
        kod_bag = {b["excel_kod"]: str(b["kaynak_stok_id"]) for b in bagla["baglanan"]}
        for r in rows:
            sid = kod_bag.get(r.get("kod") or "")
            if sid:
                excel_by_kod[sid].append(
                    {
                        "kod": r["kod"],
                        "kalan": str(r["kalan"]),
                        "tutar": str(r["tutar"]),
                        "birim_maliyet": str(r["birim_maliyet"]) if r["birim_maliyet"] is not None else None,
                        "excel_satir": r["excel_satir"],
                    }
                )

    belge_by = _yukle_belge_by_id()
    lot_by_stok: dict[str, list] = defaultdict(list)
    if LOT.is_file():
        lot = json.loads(LOT.read_text(encoding="utf-8"))
        for x in lot.get("kalan_ornek") or lot.get("kayitlar") or []:
            sid = str(x.get("stok_id") or x.get("kaynak_stok_id") or "")
            if sid:
                lot_by_stok[sid].append(x)

    hrk: dict[str, dict] = {}
    with HRK49.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            if o.get("status") == "OK":
                hrk[str(o["kaynak_stok_id"])] = o

    kayitlar = []
    durum_c: Counter = Counter()
    for sid, b in ids.items():
        h = hrk.get(sid) or {}
        exs = excel_by_kod.get(sid) or []
        ex = exs[0] if exs else {}
        kalan_ex = tr_dec(ex.get("kalan"))
        tutar_ex = tr_dec(ex.get("tutar"))
        net = tr_dec(h.get("hareket_net"))
        katmanlar, fifo_durum = _fifo_from_hareket(h.get("satirlar") or [])
        # BELGE_SATIR satır doluluğu
        fat_ids = {
            str(s.get("Fat_id"))
            for s in (h.get("satirlar") or [])
            if s.get("Fat_id") not in (None, "", "0")
        }
        belge_satir_dolu = 0
        belge_satir_bos = 0
        for fid in fat_ids:
            bel = belge_by.get(fid)
            if not bel:
                continue
            if bel.get("satirlar"):
                belge_satir_dolu += 1
            else:
                belge_satir_bos += 1

        kalan_kat = sum((k.kalan for k in katmanlar), Decimal("0"))
        deger_kat = sum(
            (
                k.kalan * (k.birim_maliyet or Decimal("0"))
                for k in katmanlar
                if k.maliyet_sinif != "BILINMEYEN"
            ),
            Decimal("0"),
        )
        bilinmeyen = sum(1 for k in katmanlar if k.maliyet_sinif == "BILINMEYEN")
        miktar_ok = (
            kalan_ex is not None
            and net is not None
            and (abs(kalan_ex - net) <= Decimal("0.01") or kalan_ex < 0)
        )
        katman_miktar_ok = kalan_ex is not None and abs(kalan_kat - max(kalan_ex, Decimal("0"))) <= Decimal(
            "0.0001"
        )
        deger_ok = False
        if (
            tutar_ex is not None
            and bilinmeyen == 0
            and katmanlar
            and fifo_durum == "OK"
        ):
            deger_ok = abs(deger_kat - tutar_ex) <= Decimal("0.02")

        if not miktar_ok:
            durum = "MIKTAR_UYUSMAZ"
        elif fifo_durum != "OK":
            durum = fifo_durum
        elif bilinmeyen:
            durum = "KATMAN_MIKTAR_OK_MALIYET_BILINMEYEN"
        elif not katmanlar and (kalan_ex or Decimal("0")) == 0:
            durum = "FIFO_TUKETILDI_VEYA_SIFIR"
        elif deger_ok:
            durum = "FIFO_HAREKET_KATMAN_DEGER_OK"
        elif katman_miktar_ok:
            durum = "FIFO_HAREKET_KATMAN_MIKTAR_OK_DEGER_FARK"
        else:
            durum = "FIFO_HAREKET_KATMAN_KURULDU_DOGRULANMADI"

        durum_c[durum] += 1
        kayitlar.append(
            {
                "kaynak_stok_id": sid,
                "kod": b.get("excel_kod"),
                "excel_satir": ex.get("excel_satir"),
                "excel_kalan": str(kalan_ex) if kalan_ex is not None else None,
                "excel_tutar": str(tutar_ex) if tutar_ex is not None else None,
                "excel_birim_maliyet": ex.get("birim_maliyet"),
                "hareket_net": h.get("hareket_net"),
                "miktar_ok": miktar_ok,
                "durum": durum,
                "katman_adet": len(katmanlar),
                "katman_kalan_toplam": str(kalan_kat),
                "katman_deger": str(deger_kat),
                "deger_ok": deger_ok,
                "bilinmeyen_katman": bilinmeyen,
                "belge_fat_id_adet": len(fat_ids),
                "belge_satir_dolu": belge_satir_dolu,
                "belge_satir_bos_baslik": belge_satir_bos,
                "eksik_belge": (
                    "BELGE_SATIR_SATIRLAR_BOS — hareket gir_fiyat ile katman kuruldu"
                    if belge_satir_bos and belge_satir_dolu == 0
                    else (
                        None
                        if belge_satir_dolu
                        else "BELGE_SATIR_YOK_VEYA_FAT_ID_0 — yalnız hareket"
                    )
                ),
                "katmanlar": [
                    {
                        "sira": k.sira,
                        "belge_id": k.belge_id,
                        "belge_tur": k.belge_tur,
                        "belge_tarih": k.belge_tarih,
                        "giren": str(k.giren),
                        "kalan": str(k.kalan),
                        "birim_maliyet": str(k.birim_maliyet) if k.birim_maliyet is not None else None,
                        "maliyet_sinif": k.maliyet_sinif,
                        "kaynak": k.kaynak,
                        "birim": k.birim,
                    }
                    for k in katmanlar
                    if k.kalan != 0
                ],
                "lot": {
                    "onceki_kayit_adet": len(lot_by_stok.get(sid) or []),
                    "durum": "ONCEKI_VAR" if lot_by_stok.get(sid) else "BEKLIYOR_SERI_LOT_LIST",
                    "eksik": None
                    if lot_by_stok.get(sid)
                    else "Seri_Lot_List katman maliyet + stok_id bağını canlı tamamla",
                },
                "kart_ortalama_doldurma_yok": True,
                "yeniden_maliyet_yok": True,
            }
        )

    out = {
        "format": "d1-stok-49-fifo-hareket-katman-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "adet": len(kayitlar),
        "durum_say": dict(durum_c),
        "miktar_ok": sum(1 for x in kayitlar if x["miktar_ok"]),
        "deger_ok": sum(1 for x in kayitlar if x["deger_ok"]),
        "katman_kuruldu": sum(1 for x in kayitlar if x["katman_adet"] > 0),
        "belge_satir_bos_baslik_adet": sum(
            1 for x in kayitlar if (x.get("belge_satir_bos_baslik") or 0) > 0
        ),
        "lot_bekliyor": sum(1 for x in kayitlar if x["lot"]["durum"].startswith("BEKLIYOR")),
        "kayitlar": kayitlar,
        "karsilastirma_esasi": {
            "envanter": "2026-08-31 FIFO Excel",
            "katman_kaynak": "STOK_HAREKET gir_fiyat (BELGE_SATIR satır boşsa)",
            "yeniden_maliyet_yok": True,
        },
        "k05": False,
        "mali_yazim": False,
        "stok_kimlik_yeniden_toplanmadi": True,
        "kasa_yeniden_toplanmadi": True,
    }
    yaz_json(OUT, out)
    ozet = {
        "zaman": out["zaman"],
        "adet": out["adet"],
        "durum_say": out["durum_say"],
        "miktar_ok": out["miktar_ok"],
        "deger_ok": out["deger_ok"],
        "katman_kuruldu": out["katman_kuruldu"],
        "lot_bekliyor": out["lot_bekliyor"],
        "k05": False,
        "kanit": str(OUT.relative_to(CALISMA)).replace("\\", "/"),
    }
    yaz_json(OZET, ozet)
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
