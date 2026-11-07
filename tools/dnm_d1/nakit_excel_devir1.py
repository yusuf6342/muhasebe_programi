"""NAKİT KASA ekstresi (nakit.xlsx) → Devir 1 kanıt + 49 banka karşı bacak eşlemesi.

K05 açmaz. Düzeltme/devir fişi (342.680) üretilmez. Mali yazım/EXE yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.nakit_excel_devir1
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import openpyxl

from tools.dnm_d1._ortak import CALISMA, KAYNAK, parse_tarih, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.kapanis_kasa_banka import _yon_tutar
from tools.dnm_d1.kasa_banka_transfer_bacak import KARSI_FLAG

EXCEL_SRC = Path.home() / "Downloads" / "nakit.xlsx"
EXCEL_HEDEF = KAYNAK / "excel" / "Nakit_Kasa_D1_20260831.xlsx"
KASA_ID = "1"
KASA_ADI = "NAKİT KASA"
BEK_GIREN = Decimal("3061663.09")
BEK_CIKAN = Decimal("3059453.54")
BEK_KAPANIS = Decimal("2209.55")
BEK_CEKILEN_GIREN = Decimal("596500")
BEK_YATIRILAN_CIKAN = Decimal("253820")
ONCEKI_HAM_GIREN = Decimal("2465163.09")
ONCEKI_HAM_CIKAN = Decimal("2805633.54")
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
    transfer49 = []
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
            "yuruyen": _dec(ws.cell(r, 8).value) if ws.cell(r, 8).value is not None else None,
            "kasa": (str(ws.cell(r, 9).value).strip() if ws.cell(r, 9).value else None),
        }
        hareketler.append(row)
        if row["islem_turu"] in ("Bankadan Çekilen", "Bankaya Yatırılan"):
            transfer49.append(row)

    giren = sum((h["giren"] for h in hareketler), Decimal("0"))
    cikan = sum((h["cikan"] for h in hareketler), Decimal("0"))
    cekilen = [h for h in transfer49 if h["islem_turu"] == "Bankadan Çekilen"]
    yatirilan = [h for h in transfer49 if h["islem_turu"] == "Bankaya Yatırılan"]
    cek_g = sum((h["giren"] for h in cekilen), Decimal("0"))
    yat_c = sum((h["cikan"] for h in yatirilan), Decimal("0"))

    banka = json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BANKA.json").read_text(encoding="utf-8"))
    kasa = json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}KASA.json").read_text(encoding="utf-8"))

    # Eşleme: banka kimliği (hesap adı + tarih + yön/tutar + MKB=NAKİT KASA)
    used: set[str] = set()
    eslesen = []
    eslesmedi = []

    def bank_adaylari(tur_id: str) -> list[dict]:
        return [
            h
            for h in (banka.get("hareketler") or [])
            if str(h.get("G.a_tur_id")) == tur_id
            and _norm(str(h.get("MKB") or "")) == _norm(KASA_ADI)
        ]

    for e in transfer49:
        if e["islem_turu"] == "Bankadan Çekilen":
            tur_id = "23"
            hedef_bank_cikan = e["giren"]
            adaylar = []
            for h in bank_adaylari(tur_id):
                bid = str(h.get("G.a_id"))
                if bid in used:
                    continue
                t = parse_tarih(h.get("G.a_tarih"))
                g, c = _yon_tutar(h)
                if t != e["tarih"] or (c or 0) != hedef_bank_cikan or (g or 0) != 0:
                    continue
                bank_adi = str(h.get("TBL_BANKA.a_adi") or "").strip()
                if _norm(bank_adi) != _norm(e["musteri"] or ""):
                    continue
                # Kimlik: tarih + tutar yönü + banka hesap adı + MKB kasa (filtrede)
                adaylar.append(h)
            if len(adaylar) == 1:
                h = adaylar[0]
                used.add(str(h.get("G.a_id")))
                eslesen.append(
                    {
                        "excel_satir": e["excel_satir"],
                        "excel_tur": e["islem_turu"],
                        "tarih": e["tarih"].isoformat() if e["tarih"] else None,
                        "excel_giren": str(e["giren"]),
                        "excel_cikan": str(e["cikan"]),
                        "excel_banka_adi": e["musteri"],
                        "banka_G.a_id": h.get("G.a_id"),
                        "banka_hesap_id": h.get("G.a_banka_id"),
                        "banka_hesap_adi": h.get("TBL_BANKA.a_adi"),
                        "banka_tur_id": h.get("G.a_tur_id"),
                        "banka_giren": h.get("G.a_giren"),
                        "banka_cikan": h.get("G.a_cikan"),
                        "banka_mkb_kasa": h.get("MKB"),
                        "banka_ref_id_kasa": h.get("G.a_ref_id"),
                        "esleme": "TARIH_TUTAR_YON_HESAP_ADI_MKB_KASA",
                        "kasa_yon": "GIREN",
                        "yeni_banka_hareketi_yok": True,
                    }
                )
            else:
                eslesmedi.append({"excel": e, "aday_adet": len(adaylar)})
        else:
            tur_id = "22"
            hedef_bank_giren = e["cikan"]
            adaylar = []
            for h in bank_adaylari(tur_id):
                bid = str(h.get("G.a_id"))
                if bid in used:
                    continue
                t = parse_tarih(h.get("G.a_tarih"))
                g, c = _yon_tutar(h)
                if t != e["tarih"] or (g or 0) != hedef_bank_giren or (c or 0) != 0:
                    continue
                bank_adi = str(h.get("TBL_BANKA.a_adi") or "").strip()
                if _norm(bank_adi) != _norm(e["musteri"] or ""):
                    continue
                adaylar.append(h)
            if len(adaylar) == 1:
                h = adaylar[0]
                used.add(str(h.get("G.a_id")))
                eslesen.append(
                    {
                        "excel_satir": e["excel_satir"],
                        "excel_tur": e["islem_turu"],
                        "tarih": e["tarih"].isoformat() if e["tarih"] else None,
                        "excel_giren": str(e["giren"]),
                        "excel_cikan": str(e["cikan"]),
                        "excel_banka_adi": e["musteri"],
                        "banka_G.a_id": h.get("G.a_id"),
                        "banka_hesap_id": h.get("G.a_banka_id"),
                        "banka_hesap_adi": h.get("TBL_BANKA.a_adi"),
                        "banka_tur_id": h.get("G.a_tur_id"),
                        "banka_giren": h.get("G.a_giren"),
                        "banka_cikan": h.get("G.a_cikan"),
                        "banka_mkb_kasa": h.get("MKB"),
                        "banka_ref_id_kasa": h.get("G.a_ref_id"),
                        "esleme": "TARIH_TUTAR_YON_HESAP_ADI_MKB_KASA",
                        "kasa_yon": "CIKAN",
                        "yeni_banka_hareketi_yok": True,
                    }
                )
            else:
                eslesmedi.append({"excel": {**e, "tarih": e["tarih"].isoformat() if e["tarih"] else None}, "aday_adet": len(adaylar)})

    # Kapsam dışı nedeni
    kasa_tur = Counter(
        (h.get("FIN_TUR.a_adi"), str(h.get("G.a_tur_id")))
        for h in (kasa.get("hareketler") or [])
        if str(h.get("G.a_kasa_id")) == KASA_ID and not h.get(KARSI_FLAG)
    )
    kapsam_neden = {
        "kok_neden": (
            "KasaHareketleri/base jq_list Bankadan Çekilen / Bankaya Yatırılan "
            "(banka tur 22/23 kasa bacağı) satırlarını döndürmüyor. "
            "Aynı olay BankHareketleri'nde tur 22/23 + MKB=NAKİT KASA + a_ref_id=1 ile duruyor."
        ),
        "onceki_ham_nakit_turlar": {f"{a}|{b}": n for (a, b), n in kasa_tur.items()},
        "excel_transfer_adet": len(transfer49),
        "duzeltme": (
            "tools.dnm_d1.kasa_banka_transfer_bacak + kaynak_kapanis_cek zenginleştirme; "
            "banka hareketi çoğaltılmaz"
        ),
    }

    # Zenginleştir + idempotent test (dosyaya yazar)
    from tools.dnm_d1.kasa_banka_transfer_bacak import zenginlestir_kaynak_dosyalari
    from tools.dnm_d1.kapanis_kasa_banka import kapanis_uret, _yaz as yaz_kap

    zeng = zenginlestir_kaynak_dosyalari()
    kasa_kap = kapanis_uret("KASA", "kasa")
    nakit_kap = next(h for h in kasa_kap["hesaplar"] if str(h["hesap_id"]) == KASA_ID)
    nakit_tamam = (
        _q2(_dec(nakit_kap["brut_giris"])) == BEK_GIREN
        and _q2(_dec(nakit_kap["brut_cikis"])) == BEK_CIKAN
        and _q2(_dec(nakit_kap["kapanis_net"])) == BEK_KAPANIS
        and len(eslesen) == 49
        and len(eslesmedi) == 0
        and zeng["idempotent"]
        and zeng["banka_degismedi"]
    )
    for h in kasa_kap["hesaplar"]:
        if str(h["hesap_id"]) == KASA_ID:
            h["kontrol_sonucu"] = "TAMAM_NAKIT_EXCEL_ESLESTI" if nakit_tamam else "KISMI"
            h["nakit_excel_kapanis"] = str(BEK_KAPANIS)
            h["karsi_bacak_dahil"] = True
            h["devir_duzeltme_fisi_342680_uretilmedi"] = True
        else:
            h["kontrol_sonucu"] = "BEKLIYOR_YC_EXCEL"
    kasa_kap["karsi_bacak_bankadan_dahil"] = True
    kasa_kap["kapanis_durumu"] = (
        "NAKIT_TAMAM_YC_BEKLIYOR" if nakit_tamam else "KISMI_HAREKET_NETI_KARSİ_BACAK"
    )
    yaz_kap("KASA_KAPANIS", kasa_kap)

    # Yürüyen bakiye hızlı kontrol
    bakiye = onceki["toplam"]
    yuruyen_hata = 0
    for h in hareketler:
        bakiye = bakiye + h["giren"] - h["cikan"]
        if h["yuruyen"] is not None and _q2(bakiye) != _q2(h["yuruyen"]):
            yuruyen_hata += 1

    kanit = {
        "format": "d1-nakit-kasa-excel-devir1-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devir": 1,
        "manifest": {
            "hesap_id": KASA_ID,
            "hesap_adi": KASA_ADI,
            "excel": {
                "yol": "kaynak/excel/Nakit_Kasa_D1_20260831.xlsx",
                "kaynak_indirme": str(EXCEL_SRC),
                "sha256": sha_x,
            },
            "baslangic_0": _q2(onceki["toplam"]) == Decimal("0"),
            "onceki_durum": onceki,
        },
        "excel_toplamlar": {
            "hareket_adet": len(hareketler),
            "giren": str(giren),
            "cikan": str(cikan),
            "kapanis": str(giren - cikan),
            "beklenen_hareket": 4935,
            "beklenen_giren": str(BEK_GIREN),
            "beklenen_cikan": str(BEK_CIKAN),
            "beklenen_kapanis": str(BEK_KAPANIS),
            "esit": _q2(giren) == BEK_GIREN
            and _q2(cikan) == BEK_CIKAN
            and _q2(giren - cikan) == BEK_KAPANIS
            and len(hareketler) == 4935,
        },
        "onceki_ham_fark": {
            "onceki_giren": str(ONCEKI_HAM_GIREN),
            "onceki_cikan": str(ONCEKI_HAM_CIKAN),
            "giren_fark": str(giren - ONCEKI_HAM_GIREN),
            "cikan_fark": str(cikan - ONCEKI_HAM_CIKAN),
            "net_fark_342680": str((giren - cikan) - (ONCEKI_HAM_GIREN - ONCEKI_HAM_CIKAN)),
            "cekilen_29_giren": str(cek_g),
            "yatirilan_20_cikan": str(yat_c),
            "fark_cekilen_ile_esit": _q2(giren - ONCEKI_HAM_GIREN) == BEK_CEKILEN_GIREN
            and _q2(cek_g) == BEK_CEKILEN_GIREN,
            "fark_yatirilan_ile_esit": _q2(cikan - ONCEKI_HAM_CIKAN) == BEK_YATIRILAN_CIKAN
            and _q2(yat_c) == BEK_YATIRILAN_CIKAN,
            "devir_duzeltme_fisi_uretilmedi": True,
        },
        "transfer_49_esleme": {
            "adet": len(transfer49),
            "eslesen": len(eslesen),
            "eslesmedi": len(eslesmedi),
            "tam": len(eslesen) == 49 and len(eslesmedi) == 0,
            "kural": "tarih + tutar/yön + banka hesap adı + MKB=NAKİT KASA (yalnız tarih/tutar değil)",
            "satirlar": eslesen,
            "eslesmeyenler": eslesmedi,
            "yeni_banka_hareketi_olusturulmadi": True,
            "yeni_cari_gelir_gider_yok": True,
        },
        "kapsam_disi_neden_ve_duzeltme": kapsam_neden,
        "zenginlestirme": zeng,
        "yuruyen_bakiye_hata_adet": yuruyen_hata,
        "nakit_kasa_kontrol": {
            "tamam": nakit_tamam,
            "kapanis_net": nakit_kap["kapanis_net"],
            "brut_giris": nakit_kap["brut_giris"],
            "brut_cikis": nakit_kap["brut_cikis"],
            "hareket_adet": nakit_kap["hareket_adet"],
            "excel_ile_esit": nakit_tamam,
        },
        "k05": False,
        "mali_yazim": False,
        "exe": False,
        "duzeltme_fisi_342680_uretilmedi": True,
    }

    def scrub(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: scrub(v) for k, v in o.items()}
        if isinstance(o, list):
            return [scrub(x) for x in o]
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, date) and not isinstance(o, datetime):
            return o.isoformat()
        return o

    yol, sha = yaz_kaynak("DOGRULAMA_NAKIT_KASA_EXCEL", scrub(kanit))
    ozet = {
        "zaman": kanit["zaman"],
        "excel_4935_ok": kanit["excel_toplamlar"]["esit"],
        "esleme_49": kanit["transfer_49_esleme"]["tam"],
        "nakit_kontrol_tamam": nakit_tamam,
        "kapanis": nakit_kap["kapanis_net"],
        "idempotent": zeng["idempotent"],
        "banka_degismedi": zeng["banka_degismedi"],
        "k05": False,
        "kanit": f"kaynak/{yol.name}",
        "sha16": sha[:16],
    }
    yaz_json(CALISMA / "NAKIT_KASA_EXCEL_OZET.json", ozet)
    print(json.dumps(ozet, ensure_ascii=False), flush=True)
    return 0 if nakit_tamam else 1


if __name__ == "__main__":
    raise SystemExit(main())
