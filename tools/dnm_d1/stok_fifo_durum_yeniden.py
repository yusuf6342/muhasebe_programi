"""FIFO durum yeniden sınıflama + 49/ekran engeli güncellemesi (76/6 yeniden çekilmez).

- FIFO_KATMAN_KURULDU içinde net=0+boş katman → FIFO_TUKETILDI_KALAN_SIFIR
- Değer uyumsuzluğunda birim/çarpan oranı gözlemi
- Doğrulanmış sayımı güncelle; önceki 28 ile tekilleştir
- K05 / mali / EXE / maliyet hesabı yok

  .venv\\Scripts\\python.exe -m tools.dnm_d1.stok_fifo_durum_yeniden
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import openpyxl

from tools.dnm_d1._ortak import CALISMA, KAYNAK, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.stok_envanter_excel_devir1 import tr_dec

BARKOD_FIFO = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_55_BARKOD_FIFO_DEVAM.json"
FIFO_IZOLE = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_FIFO_KATMAN_IZOLE.json"
ONCEKI_49 = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_49_FIFO_DOGRULA.json"
DETAY = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_HAREKET_76_DETAY.jsonl"
ESLEME = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_ENVANTER_ESLEME_COZ.json"
EXCEL = KAYNAK / "excel" / "Stok_Envanter_FIFO_D1_20260831.xlsx"
BELGE = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE_SATIR.jsonl"
FIFO_KONTROL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_FIFO_KASA_BANKA_POS_KONTROL.json"
LOT = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_LOT_KATMAN_DEVAM.json"

KURUS = Decimal("0.01")


def _q2(v: Decimal) -> Decimal:
    return v.quantize(KURUS, rounding=ROUND_HALF_UP)


def _excel_rows() -> list[dict]:
    wb = openpyxl.load_workbook(EXCEL, data_only=True)
    ws = wb.active
    rows = []
    for r in range(2, (ws.max_row or 0) + 1):
        tut = ws.cell(r, 11).value
        if isinstance(tut, str) and "toplam" in tut.lower():
            continue
        rows.append(
            {
                "excel_satir": r,
                "kod": "" if ws.cell(r, 1).value is None else str(ws.cell(r, 1).value).strip(),
                "adi": ws.cell(r, 2).value,
                "birim": str(ws.cell(r, 9).value or "").strip(),
                "kalan": tr_dec(ws.cell(r, 8).value) or Decimal("0"),
                "birim_maliyet": tr_dec(ws.cell(r, 10).value),
                "tutar": tr_dec(tut) or Decimal("0"),
            }
        )
    return rows


def _oran(a: Decimal, b: Decimal) -> Decimal | None:
    if b == 0:
        return None
    return (a / b).quantize(Decimal("0.0001"))


def main() -> int:
    barkod = json.loads(BARKOD_FIFO.read_text(encoding="utf-8"))
    onceki49 = json.loads(ONCEKI_49.read_text(encoding="utf-8")) if ONCEKI_49.is_file() else {}
    prev = json.loads(FIFO_IZOLE.read_text(encoding="utf-8")) if FIFO_IZOLE.is_file() else {}
    prev_28 = {str(x["kaynak_stok_id"]) for x in (prev.get("fifo_izole_kayitlar") or [])}
    excel = _excel_rows()
    by_kod = defaultdict(list)
    for e in excel:
        if e["kod"]:
            by_kod[e["kod"]].append(e)

    yenilenmis = []
    for f in barkod.get("fifo_76_detay", {}).get("kayitlar") or []:
        sid = str(f.get("kaynak_stok_id"))
        net = tr_dec(f.get("hareket_net")) or Decimal("0")
        kat = tr_dec(f.get("kalan_miktar_katman")) or Decimal("0")
        top = tr_dec(f.get("fifo_toplam_izole"))
        kod = str(f.get("kod") or "")
        eski = f.get("durum")

        if net < 0:
            durum = "NEGATIF_KORUNDU"
        elif eski == "HAREKET_YOK":
            durum = "HAREKET_YOK"
        elif net == 0 and kat == 0 and int(f.get("katman_adet") or 0) == 0:
            durum = "FIFO_TUKETILDI_KALAN_SIFIR"
        elif eski == "FIFO_IZOLE_DETAY":
            durum = "FIFO_IZOLE_DETAY"
        else:
            durum = "FIFO_KATMAN_KURULDU_DOGRULANMADI"

        # excel eşle
        birim = ""
        if f.get("katmanlar"):
            birim = str(f["katmanlar"][0].get("birim") or "")
        cands = [e for e in by_kod.get(kod, []) if not birim or e["birim"].casefold() == birim.casefold()]
        if not cands:
            cands = by_kod.get(kod, [])
        best = None
        for e in cands:
            if e["kalan"] == net or _q2(e["kalan"]) == _q2(net):
                best = e
                break
        if best is None and len(cands) == 1:
            best = cands[0]

        miktar_ok = (net < 0) or (abs(kat - max(net, Decimal("0"))) <= Decimal("0.0001"))
        deger = None
        dogrulanmis = False
        if durum == "FIFO_TUKETILDI_KALAN_SIFIR":
            ex0 = best and best["kalan"] == 0
            dogrulanmis = bool(ex0) or (best is None and net == 0)
            deger = {
                "excel_kalan": str(best["kalan"]) if best else None,
                "excel_tutar": str(best["tutar"]) if best else None,
                "beklenen": "kalan=0 tutar=0",
                "gosterim_uyum": dogrulanmis,
            }
        elif durum == "FIFO_IZOLE_DETAY" and top is not None and best is not None:
            oran = _oran(top, best["tutar"]) if best["tutar"] != 0 else None
            q_esit = _q2(top) == _q2(best["tutar"])
            birim_carpan_gozlem = None
            if not q_esit and oran is not None:
                # yakın tam sayı çarpan?
                nearest = oran.to_integral_value(rounding=ROUND_HALF_UP)
                if abs(oran - nearest) <= Decimal("0.05") and nearest >= 2:
                    birim_carpan_gozlem = str(nearest)
            deger = {
                "excel_satir": best["excel_satir"],
                "excel_tutar": str(best["tutar"]),
                "excel_birim": best["birim"],
                "katman_birim": birim or None,
                "fifo_toplam_izole": str(top),
                "gosterim_q2_esit": q_esit,
                "oran_fifo_div_excel": str(oran) if oran is not None else None,
                "birim_carpan_gozlem": birim_carpan_gozlem,
                "not": (
                    "Oran≈tam sayı ise birim/çarpan farkı adayı; aktarım hatası sayılmaz, "
                    "doğrulanmış FIFO da sayılmaz (dönüşüm kanıtı yok)."
                    if birim_carpan_gozlem
                    else None
                ),
            }
            dogrulanmis = miktar_ok and q_esit and not birim_carpan_gozlem

        yenilenmis.append(
            {
                "kaynak_stok_id": sid,
                "kod": kod,
                "durum_eski": eski,
                "durum_yeni": durum,
                "hareket_net": str(net),
                "kalan_miktar_katman": str(kat),
                "fifo_toplam_izole": str(top) if top is not None else None,
                "miktar_ok": miktar_ok,
                "deger_vs_excel": deger,
                "dogrulanmis_fifo": dogrulanmis,
                "onceki_28_kesisim": sid in prev_28,
                "negatif_korundu": net < 0,
                "ham_miktar_hassasiyeti": True,
            }
        )

    sayac = Counter(x["durum_yeni"] for x in yenilenmis)
    dogrulanan_ids = {x["kaynak_stok_id"] for x in yenilenmis if x["dogrulanmis_fifo"]}

    # Sıfır maliyet: tüm belge türlerinde stok satırı (alış dışı ipucu; doldurma yok)
    sifir = []
    if ESLEME.is_file():
        es = json.loads(ESLEME.read_text(encoding="utf-8"))
        sifir = (es.get("sifir_maliyet_pozitif") or {}).get("kayitlar") or []
    sifir_ids = {str(s.get("kaynak_stok_id")) for s in sifir if s.get("kaynak_stok_id")}
    belge_hit = defaultdict(list)
    if sifir_ids and BELGE.is_file():
        with BELGE.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                o = json.loads(line)
                if o.get("status") != "OK":
                    continue
                for s in o.get("satirlar") or []:
                    sid = str(s.get("stok_id") or "")
                    if sid in sifir_ids:
                        belge_hit[sid].append(
                            {
                                "belge_id": o.get("kaynak_belge_id"),
                                "tur": o.get("tur"),
                                "tarih": o.get("tarih"),
                                "birim_fiyat": s.get("birim_fiyat"),
                                "miktar": s.get("miktar"),
                                "birim": s.get("birim"),
                            }
                        )
    sifir_guncel = []
    for s in sifir:
        sid = str(s.get("kaynak_stok_id") or "")
        hits = belge_hit.get(sid) or []
        alis = [h for h in hits if str(h.get("tur")) in {"30", "32", "34", "36"}]
        sifir_guncel.append(
            {
                **s,
                "belge_satir_adet_tum_tur": len(hits),
                "alis_belge_adet": len(alis),
                "belge_ornek": hits[:3],
                "kart_doldurma_yok": True,
            }
        )

    lot = json.loads(LOT.read_text(encoding="utf-8")) if LOT.is_file() else {}

    # 49 listesi önceki kanıttan
    liste49 = (onceki49.get("liste_49") or {}).get("kayitlar_oncelikli") or []

    tanimlar = {
        "FIFO_IZOLE_DETAY": (
            "Hareket satır detayından FIFO sonrası kalan katmanlar; hepsi KANITLI gir_fiyat; "
            "katman miktar toplamı = tarihli hareket_net (≥0)."
        ),
        "FIFO_TUKETILDI_KALAN_SIFIR": (
            "Girişler çıkışlarla tüketilmiş; hareket_net=0 ve kalan katman yok. "
            "Eski etikette yanlışlıkla 'katman kuruldu' görünüyordu; doğrulama: Excel kalan=0."
        ),
        "FIFO_KATMAN_KURULDU_DOGRULANMADI": (
            "Katman üretimi denendi ancak eksik maliyet/belge veya miktar uyumsuzluğu var; "
            "doğrulanmış sayılmaz."
        ),
        "NEGATIF_KORUNDU": "hareket_net<0; katman uydurulmaz.",
        "HAREKET_YOK": "Dönem içi hareket satırı yok.",
    }

    kanit = {
        "format": "d1-stok-fifo-durum-yeniden-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devir": 1,
        "yeniden_toplanmadi_76_ve_6": True,
        "kasa_banka_degistirilmedi": True,
        "tanimlar": tanimlar,
        "sayac_yeni": dict(sayac),
        "tekillestirme": {
            "onceki_alis_only_FIFO_IZOLE_TAM_28": len(prev_28),
            "kesisim_28": len(prev_28 & {x["kaynak_stok_id"] for x in yenilenmis}),
            "dogrulanmis_bu_cek": len(dogrulanan_ids),
            "FIFO_IZOLE_DETAY_ham": sayac.get("FIFO_IZOLE_DETAY", 0),
            "FIFO_IZOLE_DETAY_dogrulanmis_deger": sum(
                1
                for x in yenilenmis
                if x["durum_yeni"] == "FIFO_IZOLE_DETAY" and x["dogrulanmis_fifo"]
            ),
            "FIFO_TUKETILDI_dogrulanmis": sum(
                1
                for x in yenilenmis
                if x["durum_yeni"] == "FIFO_TUKETILDI_KALAN_SIFIR" and x["dogrulanmis_fifo"]
            ),
            "FIFO_KATMAN_DOGRULANMADI": sayac.get("FIFO_KATMAN_KURULDU_DOGRULANMADI", 0),
            "not": "28 alış-only ile bu küme ayrı; sayılar toplanırken çiftlenmez.",
        },
        "kayitlar": yenilenmis,
        "birim_carpan_gozlem_adet": sum(
            1
            for x in yenilenmis
            if (x.get("deger_vs_excel") or {}).get("birim_carpan_gozlem")
        ),
        "liste_49_korundu": {
            "adet": len(liste49),
            "pozitif": sum(1 for r in liste49 if r.get("pozitif")),
            "kaynak": "DOGRULAMA_STOK_49_FIFO_DOGRULA.json",
            "jq_list_tam_tarama_bulunan": 0,
            "envanter_rapor_sekmesi": {
                "url_ipucu": "rapor_goster.aspx RAP_UID açık sekme",
                "sonuc": "The document is not found — drill-down yapılamadı",
                "kaynakta_yok_kesin_degil": True,
            },
        },
        "sifir_maliyet": {
            "kayitlar": sifir_guncel,
            "sinif_onceki": dict(Counter(s.get("sinif") for s in sifir_guncel)),
            "kart_doldurma_yok": True,
            "gerekli_ekran": {
                "ekran": "Stok kartı hareket / Alış faturası satırı",
                "filtre": "stok_id; ≤31.08.2026; alış turları",
                "sutunlar": [
                    "tarih",
                    "belge_id",
                    "tur",
                    "miktar",
                    "birim",
                    "birim_fiyat",
                    "depo",
                ],
                "beklerken_diger_is_durmaz": True,
            },
        },
        "lot_maliyet": {
            "mevcut_durum": (lot.get("katman_maliyet") or {}).get("durum"),
            "lot_olay": lot.get("lot_olay_adet"),
            "gerekli_ekran": {
                "ekran": "Fatura/irsaliye → Seri/LOT veya stok LOT raporu",
                "filtre": {"belge_tarihi": "≤31.08.2026", "stok_id": "LOT’lu / doğrulanmamış FIFO"},
                "sutunlar": [
                    "lot_no",
                    "giriş tarihi",
                    "giren",
                    "çıkan",
                    "kalan",
                    "katman birim maliyet",
                    "belge_id",
                ],
                "beklerken_diger_is_durmaz": True,
            },
        },
        "kalan_49_gerekli_ekran": {
            "ekran": "31.08.2026 FIFO envanter (yeniden aç) → satır → stok kartı",
            "filtre": {
                "rapor_tarihi": "31.08.2026",
                "maliyet_yontemi": "FIFO",
                "maliyet_hesabi_tarihi": "31.08.2026",
                "aktif_pasif": "Tümü+Arşiv",
                "kod_oncelik": [r["kod"] for r in liste49[:15]],
            },
            "sutunlar": [
                "stok_id",
                "kod",
                "barkodlar",
                "birim+çarpan",
                "kalan",
                "birim maliyet",
                "tutar",
            ],
            "onceki_rapor_sekmesi_belge_bulunamadi": True,
        },
        "k05": False,
        "mali_yazim": False,
        "exe": False,
        "yeni_maliyet_hesabi_baslatilmadi": True,
    }

    yol, sha = yaz_kaynak("DOGRULAMA_STOK_FIFO_DURUM_YENIDEN", kanit)
    ozet = {
        "zaman": kanit["zaman"],
        "sayac": dict(sayac),
        "dogrulanmis_izole": kanit["tekillestirme"]["FIFO_IZOLE_DETAY_dogrulanmis_deger"],
        "dogrulanmis_tuketildi": kanit["tekillestirme"]["FIFO_TUKETILDI_dogrulanmis"],
        "katman_dogrulanmadi": kanit["tekillestirme"]["FIFO_KATMAN_DOGRULANMADI"],
        "birim_carpan_gozlem": kanit["birim_carpan_gozlem_adet"],
        "liste_49": len(liste49),
        "envanter_sekme": "document_not_found",
        "k05": False,
        "kanit": f"kaynak/{yol.name}",
        "sha16": sha[:16],
    }
    yaz_json(CALISMA / "STOK_FIFO_DURUM_YENIDEN_OZET.json", ozet)

    if FIFO_KONTROL.is_file():
        try:
            fifo = json.loads(FIFO_KONTROL.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            fifo = {}
        fifo["stok_fifo_durum_yeniden"] = ozet
        fifo["k05"] = False
        ham = json.dumps(fifo, ensure_ascii=False, indent=2).encode("utf-8")
        FIFO_KONTROL.write_bytes(ham)
        import hashlib

        FIFO_KONTROL.with_suffix(".json.sha256").write_text(
            f"{hashlib.sha256(ham).hexdigest().upper()}  {FIFO_KONTROL.name}\n",
            encoding="ascii",
        )

    print(json.dumps(ozet, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
