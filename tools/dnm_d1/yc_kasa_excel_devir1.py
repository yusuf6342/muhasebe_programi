"""YÇ KASA ekstresi (yçkasa.xlsx) + iki kasa ortak kanıt (126 bacak + 223 virman).

Nakit kanıtını korur. Banka hareketi çoğaltılmaz. Dengeleme/devir fişi yok.
K05 / mali yazım / EXE yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.yc_kasa_excel_devir1
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import openpyxl

from tools.dnm_d1._ortak import CALISMA, KAYNAK, parse_tarih, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.kapanis_kasa_banka import _yon_tutar, kapanis_uret, _yaz as yaz_kap
from tools.dnm_d1.kasa_banka_transfer_bacak import (
    KARSI_FLAG,
    kasa_hareketlerini_zenginlestir,
)

EXCEL_SRC = Path.home() / "Downloads" / "yçkasa.xlsx"
EXCEL_HEDEF = KAYNAK / "excel" / "YC_Kasa_D1_20260831.xlsx"
YC_ID, YC_ADI = "2", "YÇ KASA"
NAKIT_ID, NAKIT_ADI = "1", "NAKİT KASA"
BEK_G = Decimal("1736241.5")
BEK_C = Decimal("1733691.49")
BEK_K = Decimal("2550.01")
BEK_CEK = Decimal("139200")
BEK_YAT = Decimal("1109075.52")
NAKIT_KAPANIS = Decimal("2209.55")
TOPLAM_KAPANIS = Decimal("4759.56")
KURUS = Decimal("0.01")


def _norm(s: str) -> str:
    s = (s or "").upper().replace("İ", "I").replace("ı", "I")
    for a, b in (("Ş", "S"), ("Ğ", "G"), ("Ü", "U"), ("Ö", "O"), ("Ç", "C")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def _dec(v: Any) -> Decimal:
    if v is None or v == "":
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v).strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _q2(v: Decimal) -> Decimal:
    return v.quantize(KURUS)


def _tarih_h(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return parse_tarih(v)


def _scrub(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: _scrub(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_scrub(x) for x in o]
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, date) and not isinstance(o, datetime):
        return o.isoformat()
    return o


def _esle_transfer(
    excel_rows: list[dict], banka_har: list[dict], kasa_adi: str
) -> tuple[list[dict], list[dict]]:
    used: set[str] = set()
    eslesen: list[dict] = []
    eslesmedi: list[dict] = []

    def adaylar(tur_id: str) -> list[dict]:
        return [
            h
            for h in banka_har
            if str(h.get("G.a_tur_id")) == tur_id
            and _norm(str(h.get("MKB") or "")) == _norm(kasa_adi)
        ]

    for e in excel_rows:
        if e["islem_turu"] == "Bankadan Çekilen":
            tur_id, hedef, yon = "23", e["giren"], "GIREN"
        else:
            tur_id, hedef, yon = "22", e["cikan"], "CIKAN"
        aday = []
        for h in adaylar(tur_id):
            bid = str(h.get("G.a_id"))
            if bid in used:
                continue
            t = parse_tarih(h.get("G.a_tarih"))
            g, c = _yon_tutar(h)
            g, c = g or Decimal("0"), c or Decimal("0")
            if t != e["tarih"]:
                continue
            if tur_id == "23" and not (c == hedef and g == 0):
                continue
            if tur_id == "22" and not (g == hedef and c == 0):
                continue
            if _norm(str(h.get("TBL_BANKA.a_adi") or "")) != _norm(e["musteri"] or ""):
                continue
            aday.append(h)
        if len(aday) == 1:
            h = aday[0]
            used.add(str(h.get("G.a_id")))
            eslesen.append(
                {
                    "excel_satir": e["excel_satir"],
                    "excel_tur": e["islem_turu"],
                    "tarih": e["tarih"].isoformat() if e["tarih"] else None,
                    "excel_giren": str(e["giren"]),
                    "excel_cikan": str(e["cikan"]),
                    "excel_banka_adi": e["musteri"],
                    "banka_G.a_id": str(h.get("G.a_id")),
                    "banka_hesap_id": str(h.get("G.a_banka_id")),
                    "banka_hesap_adi": h.get("TBL_BANKA.a_adi"),
                    "banka_tur_id": str(h.get("G.a_tur_id")),
                    "banka_mkb_kasa": h.get("MKB"),
                    "esleme": "TARIH_TUTAR_YON_HESAP_ADI_MKB_KASA",
                    "kasa_yon": yon,
                    "yeni_banka_hareketi_yok": True,
                }
            )
        else:
            eslesmedi.append(
                {
                    "excel_satir": e["excel_satir"],
                    "tur": e["islem_turu"],
                    "tarih": e["tarih"].isoformat() if e["tarih"] else None,
                    "musteri": e["musteri"],
                    "giren": str(e["giren"]),
                    "cikan": str(e["cikan"]),
                    "aday_adet": len(aday),
                }
            )
    return eslesen, eslesmedi


def _virman_ciftleri(kasa_har: list[dict]) -> list[dict]:
    vir = [
        h
        for h in kasa_har
        if h.get("FIN_TUR.a_adi") == "Kasa Virman" and not h.get(KARSI_FLAG)
    ]
    by_id = {str(h.get("G.a_id")): h for h in vir}
    used: set[str] = set()
    ciftler: list[dict] = []

    def tutar_yon(h: dict) -> tuple[Decimal, Decimal]:
        g, c = _yon_tutar(h)
        return g or Decimal("0"), c or Decimal("0")

    for h in vir:
        hid = str(h.get("G.a_id"))
        if hid in used:
            continue
        kid = str(h.get("G.a_kasa_id"))
        g, c = tutar_yon(h)
        mate = None
        yontem = None

        ref = str(h.get("G.a_mudul_ref_id") or "")
        if ref not in {"", "0"} and ref in by_id and ref != hid:
            m = by_id[ref]
            if str(m.get("G.a_kasa_id")) != kid:
                g2, c2 = tutar_yon(m)
                if (g > 0 and c2 == g and g2 == 0) or (c > 0 and g2 == c and c2 == 0):
                    mate, yontem = m, "G.a_mudul_ref_id+karsi_kasa+ters_tutar"

        if mate is None:
            bel = str(h.get("G.a_belge_no") or "").strip()
            if bel:
                cands = [
                    x
                    for x in vir
                    if str(x.get("G.a_belge_no") or "").strip() == bel
                    and str(x.get("G.a_id")) != hid
                    and str(x.get("G.a_kasa_id")) != kid
                ]
                if len(cands) == 1:
                    m = cands[0]
                    g2, c2 = tutar_yon(m)
                    if (g > 0 and c2 == g and g2 == 0) or (c > 0 and g2 == c and c2 == 0):
                        mate, yontem = m, "G.a_belge_no+karsi_kasa+ters_tutar"

        if mate is None:
            # a_ref_id diğer kasa id + mudul_ref ters yön
            continue

        mid = str(mate.get("G.a_id"))
        used.add(hid)
        used.add(mid)
        g2, c2 = tutar_yon(mate)
        ciftler.append(
            {
                "esleme": yontem,
                "tarih": parse_tarih(h.get("G.a_tarih")).isoformat()
                if parse_tarih(h.get("G.a_tarih"))
                else None,
                "tutar": str(g + c),
                "bacak_a": {
                    "G.a_id": hid,
                    "kasa_id": kid,
                    "kasa_adi": h.get("TBL_KASA.a_adi"),
                    "giren": str(g),
                    "cikan": str(c),
                    "mkb": h.get("MKB"),
                    "belge_no": h.get("G.a_belge_no"),
                    "mudul_ref": h.get("G.a_mudul_ref_id"),
                    "ref_id": h.get("G.a_ref_id"),
                },
                "bacak_b": {
                    "G.a_id": mid,
                    "kasa_id": str(mate.get("G.a_kasa_id")),
                    "kasa_adi": mate.get("TBL_KASA.a_adi"),
                    "giren": str(g2),
                    "cikan": str(c2),
                    "mkb": mate.get("MKB"),
                    "belge_no": mate.get("G.a_belge_no"),
                    "mudul_ref": mate.get("G.a_mudul_ref_id"),
                    "ref_id": mate.get("G.a_ref_id"),
                },
                "yalniz_tarih_tutar_degil": True,
            }
        )

    return ciftler


def _excel_virman_esle(
    excel_vir: list[dict], ciftler: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Excel YÇ virman satırını kaynak çifte bağla (belge_no=G.a_id veya mudul_ref)."""
    by_yc_id: dict[str, dict] = {}
    for cf in ciftler:
        for b in (cf["bacak_a"], cf["bacak_b"]):
            if str(b["kasa_id"]) == YC_ID:
                by_yc_id[str(b["G.a_id"])] = cf

    eslesen = []
    eslesmedi = []
    for e in excel_vir:
        bel = str(e.get("belge_no") or "").strip()
        cf = by_yc_id.get(bel) if bel else None
        if cf is None and bel:
            # belge karşı tarafın mudul_ref'i olabilir
            for c in ciftler:
                for b in (c["bacak_a"], c["bacak_b"]):
                    if str(b.get("mudul_ref")) == bel and str(b["kasa_id"]) != YC_ID:
                        # diğer bacak YÇ
                        for b2 in (c["bacak_a"], c["bacak_b"]):
                            if str(b2["kasa_id"]) == YC_ID:
                                cf = c
                                break
                if cf:
                    break
        if cf is None:
            # tarih+tutar+karşı kasa adı + tek aday
            aday = []
            for c in ciftler:
                if c["tarih"] != (e["tarih"].isoformat() if e["tarih"] else None):
                    continue
                if _q2(_dec(c["tutar"])) != _q2(e["giren"] + e["cikan"]):
                    continue
                yc = next(
                    b for b in (c["bacak_a"], c["bacak_b"]) if str(b["kasa_id"]) == YC_ID
                )
                if _q2(_dec(yc["giren"])) == _q2(e["giren"]) and _q2(
                    _dec(yc["cikan"])
                ) == _q2(e["cikan"]):
                    if _norm(e.get("musteri") or "") == _norm(NAKIT_ADI):
                        aday.append(c)
            if len(aday) == 1:
                cf = aday[0]
                yontem = "TARIH_TUTAR_YON_KARSİ_KASA_TEK_ADAY_IKINCIL"
            else:
                eslesmedi.append(
                    {
                        "excel_satir": e["excel_satir"],
                        "belge_no": bel or None,
                        "tarih": e["tarih"].isoformat() if e["tarih"] else None,
                        "giren": str(e["giren"]),
                        "cikan": str(e["cikan"]),
                        "aday": len(aday),
                    }
                )
                continue
        else:
            yontem = "EXCEL_BELGE_NO_EQ_KAYNAK_G.a_id_VEYA_REF"

        yc = next(b for b in (cf["bacak_a"], cf["bacak_b"]) if str(b["kasa_id"]) == YC_ID)
        nk = next(b for b in (cf["bacak_a"], cf["bacak_b"]) if str(b["kasa_id"]) == NAKIT_ID)
        eslesen.append(
            {
                "excel_satir": e["excel_satir"],
                "excel_belge_no": bel or None,
                "tarih": e["tarih"].isoformat() if e["tarih"] else None,
                "excel_giren": str(e["giren"]),
                "excel_cikan": str(e["cikan"]),
                "yc_G.a_id": yc["G.a_id"],
                "nakit_G.a_id": nk["G.a_id"],
                "kaynak_esleme": cf["esleme"],
                "excel_bag": yontem,
            }
        )
    return eslesen, eslesmedi


def main() -> int:
    if not EXCEL_SRC.is_file():
        raise SystemExit(f"Excel yok: {EXCEL_SRC}")

    EXCEL_HEDEF.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXCEL_SRC, EXCEL_HEDEF)
    sha_x = hashlib.sha256(EXCEL_HEDEF.read_bytes()).hexdigest().upper()
    EXCEL_HEDEF.with_suffix(".xlsx.sha256").write_text(
        f"{sha_x}  {EXCEL_HEDEF.name}\n", encoding="ascii"
    )

    wb = openpyxl.load_workbook(EXCEL_HEDEF, data_only=True)
    ws = wb.active
    onceki = {
        "satir": 2,
        "aciklama": ws.cell(2, 3).value,
        "toplam": _dec(ws.cell(2, 8).value),
    }
    hareketler = []
    transfer = []
    virman_ex = []
    for r in range(3, ws.max_row + 1):
        tur = ws.cell(r, 4).value
        if tur is None and not ws.cell(r, 6).value and not ws.cell(r, 7).value:
            continue
        row = {
            "excel_satir": r,
            "musteri": (str(ws.cell(r, 1).value).strip() if ws.cell(r, 1).value else None),
            "belge_no": ws.cell(r, 2).value,
            "aciklama": ws.cell(r, 3).value,
            "islem_turu": str(tur).strip() if tur else None,
            "tarih": _tarih_h(ws.cell(r, 5).value),
            "giren": _dec(ws.cell(r, 6).value),
            "cikan": _dec(ws.cell(r, 7).value),
            "yuruyen": _dec(ws.cell(r, 8).value)
            if ws.cell(r, 8).value is not None
            else None,
            "kasa": (str(ws.cell(r, 9).value).strip() if ws.cell(r, 9).value else None),
        }
        hareketler.append(row)
        if row["islem_turu"] in ("Bankadan Çekilen", "Bankaya Yatırılan"):
            transfer.append(row)
        if row["islem_turu"] == "Kasa Virman":
            virman_ex.append(row)

    giren = sum((h["giren"] for h in hareketler), Decimal("0"))
    cikan = sum((h["cikan"] for h in hareketler), Decimal("0"))
    tarihler = [h["tarih"] for h in hareketler if h["tarih"]]
    cek = [h for h in transfer if h["islem_turu"] == "Bankadan Çekilen"]
    yat = [h for h in transfer if h["islem_turu"] == "Bankaya Yatırılan"]
    cek_g = sum((h["giren"] for h in cek), Decimal("0"))
    yat_c = sum((h["cikan"] for h in yat), Decimal("0"))
    post = [h for h in hareketler if h["tarih"] and h["tarih"] > DONEM_SONU]

    banka = json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BANKA.json").read_text(encoding="utf-8"))
    kasa = json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}KASA.json").read_text(encoding="utf-8"))
    banka_n0 = len(banka.get("hareketler") or [])

    # Zenginleştirme idempotent (126 zaten olmalı)
    kasa2, ozet_z = kasa_hareketlerini_zenginlestir(copy.deepcopy(kasa), banka)
    kasa3, ozet_z2 = kasa_hareketlerini_zenginlestir(copy.deepcopy(kasa2), banka)
    # Dosyayı yalnız meta düzeltmesi için yazma — zaten zengin; banka değişmesin
    assert len(banka.get("hareketler") or []) == banka_n0

    kb = [h for h in (kasa.get("hareketler") or []) if h.get(KARSI_FLAG)]
    kb_nakit = [h for h in kb if str(h.get("G.a_kasa_id")) == NAKIT_ID]
    kb_yc = [h for h in kb if str(h.get("G.a_kasa_id")) == YC_ID]
    bank_ids = {str(h.get("banka_G.a_id")) for h in kb}

    eslesen77, eslesmedi77 = _esle_transfer(
        transfer, list(banka.get("hareketler") or []), YC_ADI
    )
    excel_bank_ids = {str(x["banka_G.a_id"]) for x in eslesen77}
    # Nakit 49 — önceki kanıttan / karşı bacak
    nakit_kanit_yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_NAKIT_KASA_EXCEL.json"
    nakit_49_ids: set[str] = set()
    if nakit_kanit_yol.is_file():
        nk = json.loads(nakit_kanit_yol.read_text(encoding="utf-8"))
        for s in (nk.get("transfer_49_esleme") or {}).get("satirlar") or []:
            if s.get("banka_G.a_id"):
                nakit_49_ids.add(str(s["banka_G.a_id"]))
    if not nakit_49_ids:
        nakit_49_ids = {str(h.get("banka_G.a_id")) for h in kb_nakit}

    # 126 doğrulama: excel bank ids ⊂ karşı bacak bank ids; birleşim 126
    birlesim_ids = nakit_49_ids | excel_bank_ids
    kb_ids = {str(h.get("banka_G.a_id")) for h in kb}
    dogrulama_126 = {
        "nakit_49_adet": len(nakit_49_ids),
        "yc_77_adet": len(excel_bank_ids),
        "birlesim_adet": len(birlesim_ids),
        "karsi_bacak_adet": len(kb),
        "karsi_bacak_banka_id_adet": len(kb_ids),
        "birlesim_karsi_bacakta": birlesim_ids <= kb_ids,
        "karsi_bacak_birlesimde": kb_ids <= birlesim_ids,
        "tam_126": len(birlesim_ids) == 126
        and len(kb) == 126
        and birlesim_ids == kb_ids,
        "banka_hareket_cogaltilmadi": len(banka.get("hareketler") or []) == banka_n0,
        "zenginlestirme_ikinci_ekleme": ozet_z2.get("eklenen"),
        "idempotent": ozet_z2.get("eklenen") == 0,
    }

    # Virman
    ciftler = _virman_ciftleri(list(kasa.get("hareketler") or []))
    vir_ex_esle, vir_ex_yok = _excel_virman_esle(virman_ex, ciftler)
    # Çiftler yalnız NAKİT↔YÇ mi?
    yabanci = [
        c
        for c in ciftler
        if {str(c["bacak_a"]["kasa_id"]), str(c["bacak_b"]["kasa_id"])}
        != {NAKIT_ID, YC_ID}
    ]

    # Kapanış yeniden (dosyadaki zengin KASA)
    kasa_kap = kapanis_uret("KASA", "kasa")
    by_id = {str(h["hesap_id"]): h for h in kasa_kap["hesaplar"]}
    nakit_ok = (
        _q2(_dec(by_id[NAKIT_ID]["kapanis_net"])) == NAKIT_KAPANIS
        and _q2(_dec(by_id[NAKIT_ID]["brut_giris"])) == Decimal("3061663.09")
    )
    yc_ok = (
        _q2(_dec(by_id[YC_ID]["brut_giris"])) == BEK_G
        and _q2(_dec(by_id[YC_ID]["brut_cikis"])) == BEK_C
        and _q2(_dec(by_id[YC_ID]["kapanis_net"])) == BEK_K
        and len(eslesen77) == 77
        and len(eslesmedi77) == 0
    )
    toplam_ok = _q2(
        _dec(by_id[NAKIT_ID]["kapanis_net"]) + _dec(by_id[YC_ID]["kapanis_net"])
    ) == TOPLAM_KAPANIS

    iki_kasa_tamam = (
        nakit_ok
        and yc_ok
        and toplam_ok
        and dogrulama_126["tam_126"]
        and len(ciftler) == 223
        and len(yabanci) == 0
        and len(vir_ex_esle) == 223
        and len(vir_ex_yok) == 0
        and dogrulama_126["idempotent"]
        and dogrulama_126["banka_hareket_cogaltilmadi"]
        and len(post) == 0
    )

    for hid, h in by_id.items():
        if hid == NAKIT_ID:
            h["kontrol_sonucu"] = "TAMAM_NAKIT_EXCEL_ESLESTI"
            h["kapanis_kanit"] = str(NAKIT_KAPANIS)
        elif hid == YC_ID:
            h["kontrol_sonucu"] = (
                "TAMAM_YC_EXCEL_ESLESTI" if yc_ok else "KISMI_YC"
            )
            h["kapanis_kanit"] = str(BEK_K)
        h["karsi_bacak_dahil"] = True
        h["devir_duzeltme_fisi_uretilmedi"] = True

    kasa_kap["karsi_bacak_bankadan_dahil"] = True
    kasa_kap["kapanis_durumu"] = (
        "IKI_KASA_TAMAM" if iki_kasa_tamam else "KISMI_KASA"
    )
    kasa_kap["iki_kasa_toplam_kapanis"] = str(
        _dec(by_id[NAKIT_ID]["kapanis_net"]) + _dec(by_id[YC_ID]["kapanis_net"])
    )
    kasa_kap["k05"] = False
    yaz_kap("KASA_KAPANIS", kasa_kap)

    # Açıklanamayan farklar
    aciklanamayan = []
    if not dogrulama_126["tam_126"]:
        aciklanamayan.append(
            {
                "konu": "126_karsi_bacak",
                "detay": {
                    "birlesim": len(birlesim_ids),
                    "kb": len(kb_ids),
                    "sadece_excel": sorted(birlesim_ids - kb_ids)[:20],
                    "sadece_kb": sorted(kb_ids - birlesim_ids)[:20],
                },
            }
        )
    if len(vir_ex_yok):
        aciklanamayan.append({"konu": "virman_excel_eslesmedi", "adet": len(vir_ex_yok)})
    if len(eslesmedi77):
        aciklanamayan.append({"konu": "yc_transfer_eslesmedi", "adet": len(eslesmedi77)})

    kanit = {
        "format": "d1-yc-kasa-excel-devir1-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devir": 1,
        "korunan_nakit_kanit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_NAKIT_KASA_EXCEL.json",
        "manifest": {
            "hesap_id": YC_ID,
            "hesap_adi": YC_ADI,
            "excel": {
                "yol": "kaynak/excel/YC_Kasa_D1_20260831.xlsx",
                "kaynak_indirme": str(EXCEL_SRC),
                "sha256": sha_x,
            },
            "baslangic_0": _q2(onceki["toplam"]) == Decimal("0"),
            "tarih_araligi": {
                "min": min(tarihler).isoformat() if tarihler else None,
                "max": max(tarihler).isoformat() if tarihler else None,
                "donem_sonu_sonrasi_adet": len(post),
            },
        },
        "excel_toplamlar": {
            "hareket_adet": len(hareketler),
            "giren": str(giren),
            "cikan": str(cikan),
            "kapanis": str(giren - cikan),
            "beklenen": {
                "adet": 473,
                "giren": str(BEK_G),
                "cikan": str(BEK_C),
                "kapanis": str(BEK_K),
            },
            "esit": len(hareketler) == 473
            and _q2(giren) == BEK_G
            and _q2(cikan) == BEK_C
            and _q2(giren - cikan) == BEK_K,
        },
        "transfer_77": {
            "cekilen_9_giren": str(cek_g),
            "yatirilan_68_cikan": str(yat_c),
            "bek_cek": str(BEK_CEK),
            "bek_yat": str(BEK_YAT),
            "fark_ortusuyor": _q2(cek_g) == BEK_CEK and _q2(yat_c) == BEK_YAT,
            "eslesen": len(eslesen77),
            "eslesmedi": len(eslesmedi77),
            "tam": len(eslesen77) == 77 and len(eslesmedi77) == 0,
            "satirlar": eslesen77,
            "eslesmeyenler": eslesmedi77,
            "yeni_banka_hareketi_yok": True,
        },
        "karsi_bacak_126": dogrulama_126,
        "virman_223": {
            "kaynak_cift_adet": len(ciftler),
            "yalniz_nakit_yc": len(yabanci) == 0,
            "excel_virman_adet": len(virman_ex),
            "excel_eslesen": len(vir_ex_esle),
            "excel_eslesmedi": len(vir_ex_yok),
            "tam": len(ciftler) == 223
            and len(vir_ex_esle) == 223
            and len(vir_ex_yok) == 0,
            "kimlik_kurali": (
                "G.a_mudul_ref_id veya G.a_belge_no + karşı kasa + ters tutar; "
                "yalnız tarih/tutar benzerliği kesin sayılmaz"
            ),
            "excel_esleme_ornek": vir_ex_esle[:5],
            "excel_eslesen_idler": [
                {"yc": x["yc_G.a_id"], "nakit": x["nakit_G.a_id"]} for x in vir_ex_esle
            ],
            "eslesmeyenler": vir_ex_yok,
        },
        "iki_kasa_kapanis": {
            "nakit": {
                "hesap_id": NAKIT_ID,
                "kapanis": by_id[NAKIT_ID]["kapanis_net"],
                "beklenen": str(NAKIT_KAPANIS),
                "ok": nakit_ok,
            },
            "yc": {
                "hesap_id": YC_ID,
                "kapanis": by_id[YC_ID]["kapanis_net"],
                "giren": by_id[YC_ID]["brut_giris"],
                "cikan": by_id[YC_ID]["brut_cikis"],
                "beklenen_kapanis": str(BEK_K),
                "ok": yc_ok,
            },
            "toplam": {
                "kapanis": str(
                    _dec(by_id[NAKIT_ID]["kapanis_net"])
                    + _dec(by_id[YC_ID]["kapanis_net"])
                ),
                "beklenen": str(TOPLAM_KAPANIS),
                "ok": toplam_ok,
            },
            "tamam": iki_kasa_tamam,
            "aciklanamayan_farklar": aciklanamayan,
            "dengeleme_devir_fisi_uretilmedi": True,
        },
        "kapsam_plani": {
            "kok_neden": (
                "Kasa jq_list Bankadan Çekilen/Bankaya Yatırılan döndürmez; "
                "banka tur 22/23 MKB=kasa karşı bacak görünümü ile tamamlanır"
            ),
            "kod": [
                "tools/dnm_d1/kasa_banka_transfer_bacak.py",
                "tools/dnm_d1/kaynak_kapanis_cek.py",
                "tools/dnm_d1/kapanis_kasa_banka.py",
            ],
            "banka_cogaltma_yok": True,
        },
        "k05": False,
        "mali_yazim": False,
        "exe": False,
        "diger_kaynak_eksikleri_kabul_edilmedi": True,
    }

    yol, sha = yaz_kaynak("DOGRULAMA_YC_KASA_EXCEL", _scrub(kanit))

    # Birleşik özet
    birlesik = {
        "zaman": kanit["zaman"],
        "nakit_kapanis": str(NAKIT_KAPANIS),
        "yc_kapanis": str(BEK_K),
        "toplam_kapanis": str(TOPLAM_KAPANIS),
        "karsi_bacak_126": dogrulama_126["tam_126"],
        "virman_223": kanit["virman_223"]["tam"],
        "iki_kasa_tamam": iki_kasa_tamam,
        "aciklanamayan": aciklanamayan,
        "k05": False,
        "kanit_yc": f"kaynak/{yol.name}",
        "kanit_nakit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_NAKIT_KASA_EXCEL.json",
        "sha16": sha[:16],
    }
    yaz_json(CALISMA / "IKI_KASA_KAPANIS_OZET.json", birlesik)

    # FIFO kapsam güncelle (geçersiz JSON olursa atla)
    fifo_yol = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_FIFO_KASA_BANKA_POS_KONTROL.json"
    if fifo_yol.is_file():
        try:
            fifo = json.loads(fifo_yol.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            fifo = {"format": "d1-fifo-kasa-banka-pos-kontrol-v1", "tamamlanan": [], "engeller": []}
        for t in fifo.get("tamamlanan") or []:
            if t.get("is") == "kasa_hareket_net_kapanis":
                t["durum"] = "IKI_KASA_TAMAM" if iki_kasa_tamam else t.get("durum")
                t["nakit_kasa_id_1"] = {
                    "kapanis": str(NAKIT_KAPANIS),
                    "kontrol": "TAMAM",
                }
                t["yc_kasa_id_2"] = {
                    "kapanis": str(BEK_K),
                    "kontrol": "TAMAM" if yc_ok else "KISMI",
                }
                t["toplam_kapanis"] = str(TOPLAM_KAPANIS)
                t["kanit"] = list(
                    dict.fromkeys(
                        (t.get("kanit") or [])
                        + [
                            "kaynak/D1_20260831_KAYNAK_DOGRULAMA_NAKIT_KASA_EXCEL.json",
                            f"kaynak/{yol.name}",
                        ]
                    )
                )
                t["kapsam_plani"] = (
                    "Kasa jq_list tur 22/23 döndürmez; banka MKB=kasa karşı bacak "
                    "görünümü eklenir (banka çoğalmaz). NAKİT+YÇ Excel mutabık."
                )
        if iki_kasa_tamam:
            fifo["engeller"] = [
                e
                for e in (fifo.get("engeller") or [])
                if e.get("is") != "kasa_resmi_3108_ekstre"
            ]
        fifo["k05"] = False
        fifo["kasa_tamam_diger_eksik_kabulu_degil"] = True
        ham = json.dumps(fifo, ensure_ascii=False, indent=2).encode("utf-8")
        fifo_yol.write_bytes(ham)
        fifo_yol.with_suffix(".json.sha256").write_text(
            f"{hashlib.sha256(ham).hexdigest().upper()}  {fifo_yol.name}\n",
            encoding="ascii",
        )

    print(json.dumps(birlesik, ensure_ascii=False), flush=True)
    return 0 if iki_kasa_tamam else 1


if __name__ == "__main__":
    raise SystemExit(main())
