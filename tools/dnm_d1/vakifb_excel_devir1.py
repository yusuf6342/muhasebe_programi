"""VAKIFBANK ekstresi (vakıfb.xlsx) → Devir 1 kanıt + AKBANK 4355 fark araştırması.

D1: satır 3–46 (≤31.08.2026). D2: satır 47–52 (09.09 / 12.10.2026) — D1'e katılmaz.
K05 açmaz. Düzeltme fişi / mali yazım / EXE yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.vakifb_excel_devir1
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import openpyxl

from tools.dnm_d1._ortak import CALISMA, KAYNAK, parse_tarih, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.kapanis_kasa_banka import _yon_tutar

EXCEL_SRC = Path.home() / "Downloads" / "vakıfb.xlsx"
EXCEL_HEDEF = KAYNAK / "excel" / "Vakifbank_Buyukcekmece_D1_20260831.xlsx"

HESAP_ID = "5"
HESAP_ADI = "01 VAKIFBANK BÜYÜKÇEKMECE"
AKBANK_ID = "1"
ONCEKI_DURUM_SATIR = 2
D1_SATIR_BAS, D1_SATIR_SON = 3, 46
D2_SATIR_BAS, D2_SATIR_SON = 47, 52
BEKLENEN_D1_GIREN = Decimal("942533.61")
BEKLENEN_D1_CIKAN = Decimal("941874.61")
BEKLENEN_D1_KAPANIS = Decimal("659.00")
BEKLENEN_DOSYA_SON = Decimal("863.08")
MAYIS_NET = Decimal("50145")
ONCEKI_DONEM_NETI_0106 = Decimal("-49486")  # Banka Toplamı 01.06 filtresi
KURUS = Decimal("0.01")
FILTRE_BANKA_TOPLAMI_BAS = date(2025, 6, 1)


def _dec_opt(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    try:
        return Decimal(str(v).strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _q2(v: Decimal) -> Decimal:
    return v.quantize(KURUS)


def _tarih_hucre(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return parse_tarih(v)


def _anahtar(t: date | None, giren: Decimal, cikan: Decimal, tur: str | None) -> tuple:
    return (
        t.isoformat() if t else None,
        str(_q2(giren)),
        str(_q2(cikan)),
        (tur or "").strip(),
    )


def _oku_excel(yol: Path) -> tuple[dict[str, Any], list[dict], list[dict]]:
    wb = openpyxl.load_workbook(yol, data_only=True)
    ws = wb.active
    onceki = {
        "excel_satir": ONCEKI_DURUM_SATIR,
        "aciklama": ws.cell(ONCEKI_DURUM_SATIR, 3).value,
        "toplam": _dec_opt(ws.cell(ONCEKI_DURUM_SATIR, 8).value),
        "iddia": "01.05.2025 öncesi banka durumu 0 TL",
    }

    def oku_aralik(bas: int, son: int) -> list[dict]:
        out = []
        for r in range(bas, son + 1):
            t = _tarih_hucre(ws.cell(r, 5).value)
            giren = _dec_opt(ws.cell(r, 6).value) or Decimal("0")
            cikan = _dec_opt(ws.cell(r, 7).value) or Decimal("0")
            toplam = _dec_opt(ws.cell(r, 8).value)
            out.append(
                {
                    "excel_satir": r,
                    "musteri": (str(ws.cell(r, 1).value).strip() if ws.cell(r, 1).value else None),
                    "belge_no": ws.cell(r, 2).value,
                    "aciklama": ws.cell(r, 3).value,
                    "islem_turu": (str(ws.cell(r, 4).value).strip() if ws.cell(r, 4).value else None),
                    "tarih": t.isoformat() if t else None,
                    "tarih_date": t,
                    "giren": giren,
                    "cikan": cikan,
                    "yuruyen_bakiye": toplam,
                    "banka": (str(ws.cell(r, 9).value).strip() if ws.cell(r, 9).value else None),
                }
            )
        return out

    return onceki, oku_aralik(D1_SATIR_BAS, D1_SATIR_SON), oku_aralik(D2_SATIR_BAS, D2_SATIR_SON)


def _yuruyen_kontrol(satirlar: list[dict], baslangic: Decimal) -> dict[str, Any]:
    bakiye = baslangic
    hatalar = []
    for s in satirlar:
        bakiye = bakiye + s["giren"] - s["cikan"]
        bek = s["yuruyen_bakiye"]
        if bek is None or _q2(bakiye) != _q2(bek):
            hatalar.append(
                {
                    "excel_satir": s["excel_satir"],
                    "hesaplanan": str(bakiye),
                    "excel_toplam": str(bek) if bek is not None else None,
                }
            )
    return {
        "baslangic": str(baslangic),
        "son_hesaplanan": str(bakiye),
        "son_excel": str(satirlar[-1]["yuruyen_bakiye"]) if satirlar else None,
        "aritmetik_tutarli": len(hatalar) == 0,
        "hata_adet": len(hatalar),
        "hatalar": hatalar[:20],
    }


def _eslestir(excel_d1: list[dict], kaynak: list[dict]) -> dict[str, Any]:
    kaynak_bag: dict[tuple, list[dict]] = defaultdict(list)
    for h in kaynak:
        t = parse_tarih(h.get("G.a_tarih"))
        g, c = _yon_tutar(h)
        g = g or Decimal("0")
        c = c or Decimal("0")
        tur = str(h.get("FIN_TUR.a_adi") or "").strip()
        kaynak_bag[_anahtar(t, g, c, tur)].append(
            {
                "G.a_id": h.get("G.a_id"),
                "tarih": t.isoformat() if t else None,
                "giren": str(g),
                "cikan": str(c),
                "islem_turu": tur,
                "ack": h.get("G.a_ack"),
                "mkb": h.get("MKB"),
            }
        )

    eslesen = []
    excel_fazla = []
    kullanilan: Counter = Counter()

    for s in excel_d1:
        t = s["tarih_date"]
        key = _anahtar(t, s["giren"], s["cikan"], s["islem_turu"])
        adaylar = kaynak_bag.get(key) or []
        idx = kullanilan[key]
        if idx < len(adaylar):
            k = adaylar[idx]
            kullanilan[key] += 1
            eslesen.append(
                {
                    "excel_satir": s["excel_satir"],
                    "kaynak_G.a_id": k["G.a_id"],
                    "tarih": s["tarih"],
                    "giren": str(s["giren"]),
                    "cikan": str(s["cikan"]),
                    "islem_turu": s["islem_turu"],
                    "esleme": "TARIH_TUTAR_TUR",
                }
            )
        else:
            excel_fazla.append(
                {
                    "excel_satir": s["excel_satir"],
                    "tarih": s["tarih"],
                    "giren": str(s["giren"]),
                    "cikan": str(s["cikan"]),
                    "islem_turu": s["islem_turu"],
                    "aciklama": s["aciklama"],
                }
            )

    kaynak_fazla = []
    for key, adaylar in kaynak_bag.items():
        kalan = adaylar[kullanilan[key] :]
        for k in kalan:
            kaynak_fazla.append(k)

    return {
        "excel_d1_adet": len(excel_d1),
        "kaynak_d1_adet": len(kaynak),
        "eslesen_adet": len(eslesen),
        "excel_fazla_adet": len(excel_fazla),
        "kaynak_fazla_adet": len(kaynak_fazla),
        "tam_eslesme": len(excel_fazla) == 0 and len(kaynak_fazla) == 0 and len(eslesen) == len(excel_d1),
        "eslesen": eslesen,
        "excel_fazla": excel_fazla,
        "kaynak_fazla": kaynak_fazla,
        "kimlik_anahtari": "tarih + giren(kurus) + cikan(kurus) + islem_turu (G.a_id Excel'de yok)",
    }


def _akbank_4355(banka: dict) -> dict[str, Any]:
    hedef = Decimal("4355")
    excel_giren = Decimal("6357911.93")  # Banka Toplamı R002 (kurus)
    excel_toplam = Decimal("435.18")  # yaklaşık; kanıtta ham float ayrı

    hareketler = [
        h
        for h in (banka.get("hareketler") or [])
        if str(h.get("G.a_banka_id") or "") == AKBANK_ID
    ]
    aralik = []
    for h in hareketler:
        t = parse_tarih(h.get("G.a_tarih"))
        if t and FILTRE_BANKA_TOPLAMI_BAS <= t <= DONEM_SONU:
            aralik.append(h)

    g_sum = Decimal("0")
    c_sum = Decimal("0")
    for h in aralik:
        g, c = _yon_tutar(h)
        g_sum += g or Decimal("0")
        c_sum += c or Decimal("0")

    fark_giren = excel_giren - _q2(g_sum)

    # Tekil / çift / üçlü arama (yalnız girişler)
    giren_list = []
    for h in aralik:
        g, c = _yon_tutar(h)
        g = g or Decimal("0")
        if g > 0:
            giren_list.append((g, h))

    tekil = []
    for g, h in giren_list:
        if _q2(g) == hedef:
            tekil.append(
                {
                    "G.a_id": h.get("G.a_id"),
                    "tarih": h.get("G.a_tarih"),
                    "tur": h.get("FIN_TUR.a_adi"),
                    "giren": str(g),
                    "ack": h.get("G.a_ack"),
                    "mkb": h.get("MKB"),
                    "komisyon": h.get("G.a_komisyon"),
                }
            )

    cift = []
    n = len(giren_list)
    # Sınırlı: küçük adaylar (<= hedef)
    aday = [(g, h) for g, h in giren_list if g <= hedef]
    for i in range(len(aday)):
        g1, h1 = aday[i]
        for j in range(i + 1, len(aday)):
            g2, h2 = aday[j]
            if _q2(g1 + g2) == hedef:
                cift.append(
                    {
                        "idler": [h1.get("G.a_id"), h2.get("G.a_id")],
                        "tarihler": [h1.get("G.a_tarih"), h2.get("G.a_tarih")],
                        "turler": [h1.get("FIN_TUR.a_adi"), h2.get("FIN_TUR.a_adi")],
                        "girenler": [str(g1), str(g2)],
                        "ack": [h1.get("G.a_ack"), h2.get("G.a_ack")],
                    }
                )
                if len(cift) >= 30:
                    break
        if len(cift) >= 30:
            break

    # Tür bazlı: Excel = kaynak − tür?
    tur_ozet = []
    by_tur: dict[str, list] = defaultdict(list)
    for h in aralik:
        by_tur[str(h.get("FIN_TUR.a_adi") or "?")].append(h)
    for tur, rows in sorted(by_tur.items()):
        tg = sum((_yon_tutar(h)[0] or Decimal("0")) for h in rows)
        tc = sum((_yon_tutar(h)[1] or Decimal("0")) for h in rows)
        tur_ozet.append(
            {
                "tur": tur,
                "adet": len(rows),
                "giren": str(tg),
                "cikan": str(tc),
                "giren_excel_farkina_esit": _q2(tg) == hedef,
                "kaynak_eksi_bu_tur_giren_excel_esit": _q2(g_sum - tg) == excel_giren,
            }
        )

    # Banka Toplamı Excel görünümü: filtre tarihi = a_vtarih (yoksa a_tarih)
    g_vt = Decimal("0")
    c_vt = Decimal("0")
    n_vt = 0
    valor_sonrasi_girenler = []  # a_tarih dönemde, açık a_vtarih dönem dışında
    for h in hareketler:
        t = parse_tarih(h.get("G.a_tarih"))
        vt_ham = parse_tarih(h.get("G.a_vtarih"))
        filtre_t = vt_ham or t
        in_t = bool(t and FILTRE_BANKA_TOPLAMI_BAS <= t <= DONEM_SONU)
        in_filtre = bool(filtre_t and FILTRE_BANKA_TOPLAMI_BAS <= filtre_t <= DONEM_SONU)
        if in_filtre:
            g, c = _yon_tutar(h)
            g_vt += g or Decimal("0")
            c_vt += c or Decimal("0")
            n_vt += 1
        if in_t and vt_ham is not None and not (
            FILTRE_BANKA_TOPLAMI_BAS <= vt_ham <= DONEM_SONU
        ):
            g, c = _yon_tutar(h)
            valor_sonrasi_girenler.append(
                {
                    "G.a_id": h.get("G.a_id"),
                    "a_tarih": t.isoformat() if t else None,
                    "a_vtarih": vt_ham.isoformat(),
                    "giren": str(g or 0),
                    "cikan": str(c or 0),
                    "tur": h.get("FIN_TUR.a_adi"),
                    "mkb": h.get("MKB"),
                    "ack": h.get("G.a_ack"),
                }
            )

    valor_giren = sum((Decimal(x["giren"]) for x in valor_sonrasi_girenler), Decimal("0"))
    valor_cikan = sum((Decimal(x["cikan"]) for x in valor_sonrasi_girenler), Decimal("0"))
    vtarih_excel_esit = _q2(g_vt) == excel_giren and _q2(c_vt) == _q2(c_sum)

    # Alan bayrakları
    bayrak = {}
    for fld in ("G.a_kontrol", "G.a_pos_bloke", "G.a_mn_kapat", "G.a_taksit"):
        groups: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        counts: Counter = Counter()
        for h in aralik:
            k = str(h.get(fld) if h.get(fld) is not None else "")
            counts[k] += 1
            g, _c = _yon_tutar(h)
            groups[k] += g or Decimal("0")
        bayrak[fld] = {
            "adet": dict(counts),
            "giren_toplam": {k: str(v) for k, v in groups.items()},
            "4355_eslesen_deger": [k for k, v in groups.items() if _q2(v) == hedef],
        }

    # MKB / cari tarafı: giren=4355 yoksa, belki net etki
    # Günlük giren toplamı = 4355?
    gunluk: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for h in aralik:
        t = parse_tarih(h.get("G.a_tarih"))
        g, _c = _yon_tutar(h)
        if t and g:
            gunluk[t.isoformat()] += g
    gun_4355 = [
        {"tarih": k, "giren": str(v)} for k, v in sorted(gunluk.items()) if _q2(v) == hedef
    ]

    # Üçlü arama — yalnız küçük adaylar, sınırlı
    uclu = []
    kucuk = [(g, h) for g, h in aday if g < hedef]
    for i in range(min(len(kucuk), 80)):
        for j in range(i + 1, min(len(kucuk), 80)):
            s2 = kucuk[i][0] + kucuk[j][0]
            if s2 >= hedef:
                continue
            need = hedef - s2
            for k in range(j + 1, min(len(kucuk), 80)):
                if _q2(kucuk[k][0]) == _q2(need):
                    hs = [kucuk[i][1], kucuk[j][1], kucuk[k][1]]
                    uclu.append(
                        {
                            "idler": [x.get("G.a_id") for x in hs],
                            "tarihler": [x.get("G.a_tarih") for x in hs],
                            "turler": [x.get("FIN_TUR.a_adi") for x in hs],
                            "girenler": [str(kucuk[i][0]), str(kucuk[j][0]), str(kucuk[k][0])],
                        }
                    )
                    break
            if len(uclu) >= 15:
                break
        if len(uclu) >= 15:
            break

    bulgular = []
    if vtarih_excel_esit and _q2(valor_giren) == hedef:
        bulgular.append(
            "KÖK_NEDEN: Banka Toplamı Excel a_vtarih (yoksa a_tarih) ile süzüyor; "
            "ham a_tarih süzgeci 31.08.2026 tarihli / valorü 01.09.2026 olan "
            f"{len(valor_sonrasi_girenler)} KK tahsilatını (giren toplam {valor_giren}) "
            "döneme dahil ediyor → Excel−kaynak(a_tarih) = −4355"
        )
    elif _q2(valor_giren) == hedef:
        bulgular.append(
            f"a_tarih dönemde + açık a_vtarih dönem dışı giren toplamı=4355 "
            f"({len(valor_sonrasi_girenler)} hareket)"
        )
    if tekil:
        bulgular.append("Tekil giren=4355 hareket bulundu (ikincil)")
    if any(t["giren_excel_farkina_esit"] for t in tur_ozet):
        bulgular.append("Bir işlem türünün giren toplamı tam 4355 (ikincil)")
    if gun_4355:
        bulgular.append(f"Günlük giren toplamı=4355 gün (ikincil): {len(gun_4355)}")
    for fld, info in bayrak.items():
        if info["4355_eslesen_deger"]:
            bulgular.append(f"{fld} giren=4355 (ikincil): {info['4355_eslesen_deger']}")
    if not bulgular:
        bulgular.append("4355 kaynak hareketlerine indirgenemedi")

    return {
        "hesap_id": AKBANK_ID,
        "hesap_adi": "001 AKBANK AVCILAR KMH POS BAĞLI",
        "filtre": {
            "baslangic": FILTRE_BANKA_TOPLAMI_BAS.isoformat(),
            "bitis": DONEM_SONU.isoformat(),
        },
        "excel_banka_toplami_giren_kurus": str(excel_giren),
        "kaynak_a_tarih_giren": str(g_sum),
        "kaynak_a_tarih_cikan": str(c_sum),
        "kaynak_a_tarih_net": str(g_sum - c_sum),
        "kaynak_a_tarih_hareket_adet": len(aralik),
        "fark_giren_excel_eksi_a_tarih": str(fark_giren),
        "fark_kurus": str(_q2(excel_giren) - _q2(g_sum)),
        "hedef_fark": str(hedef),
        "kok_neden_vtarih": {
            "aciklama": (
                "Excel Banka Toplamı filtre tarihi ≈ G.a_vtarih; boşsa G.a_tarih. "
                "a_tarih=31.08.2026 ve a_vtarih=01.09.2026 KK tahsilatları Excel döneminde yok, "
                "ham a_tarih toplamında var."
            ),
            "vtarih_veya_tarih_filtre_giren": str(g_vt),
            "vtarih_veya_tarih_filtre_cikan": str(c_vt),
            "vtarih_veya_tarih_hareket_adet": n_vt,
            "excel_giren_ile_esit": _q2(g_vt) == excel_giren,
            "excel_cikan_ile_kurus_esit": _q2(c_vt) == _q2(c_sum),
            "valor_01_09_hareket_adet": len(valor_sonrasi_girenler),
            "valor_01_09_giren_toplam": str(valor_giren),
            "valor_01_09_cikan_toplam": str(valor_cikan),
            "valor_01_09_giren_4355_esit": _q2(valor_giren) == hedef,
            "hareketler": valor_sonrasi_girenler,
        },
        "tekil_4355": tekil,
        "cift_4355_adet_ikincil": len(cift),
        "uclu_4355_adet_ikincil": len(uclu),
        "tur_ozet": tur_ozet,
        "bayrak_alanlari": bayrak,
        "gunluk_giren_4355": gun_4355,
        "bulgular": bulgular,
        "duzeltme_fisi_uretilmedi": True,
        "kapanis_kabulu_yapilmadi": True,
        "not": (
            "Bu bulgu AKBANK hesabındaki Banka Toplamı Excel farkını açıklar; "
            "düzeltme fişi üretmez; diğer hesap kabulü yerine geçmez; K05 açmaz."
        ),
    }


def main() -> int:
    if not EXCEL_SRC.is_file():
        raise SystemExit(f"Excel yok: {EXCEL_SRC}")

    EXCEL_HEDEF.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXCEL_SRC, EXCEL_HEDEF)
    ham_xlsx = EXCEL_HEDEF.read_bytes()
    sha_xlsx = hashlib.sha256(ham_xlsx).hexdigest().upper()
    EXCEL_HEDEF.with_suffix(".xlsx.sha256").write_text(
        f"{sha_xlsx}  {EXCEL_HEDEF.name}\n", encoding="ascii"
    )

    onceki, d1, d2 = _oku_excel(EXCEL_HEDEF)
    # tarih_date serileştirme için ayır
    for s in d1 + d2:
        s.pop("tarih_date", None)  # yeniden parse edilecek; aşağıda tutuyoruz
    # yeniden oku with dates for logic — restore from iso
    for s in d1 + d2:
        s["tarih_date"] = parse_tarih(s["tarih"])

    onceki_bakiye = onceki["toplam"] if onceki["toplam"] is not None else Decimal("0")
    yuruyen_d1 = _yuruyen_kontrol(d1, onceki_bakiye)
    # D2 yürüyen: D1 son bakiyeden devam (dosya bütünlüğü); D1 hesabına katılmaz
    d1_son = d1[-1]["yuruyen_bakiye"] if d1 else onceki_bakiye
    yuruyen_d2 = _yuruyen_kontrol(d2, d1_son or Decimal("0"))

    giren_d1 = sum((s["giren"] for s in d1), Decimal("0"))
    cikan_d1 = sum((s["cikan"] for s in d1), Decimal("0"))
    kapanis_d1 = onceki_bakiye + giren_d1 - cikan_d1

    # Mayıs ayrımı
    mayis = [s for s in d1 if s["tarih_date"] and s["tarih_date"] < FILTRE_BANKA_TOPLAMI_BAS]
    donem_0106 = [
        s
        for s in d1
        if s["tarih_date"] and FILTRE_BANKA_TOPLAMI_BAS <= s["tarih_date"] <= DONEM_SONU
    ]
    mayis_giren = sum((s["giren"] for s in mayis), Decimal("0"))
    mayis_cikan = sum((s["cikan"] for s in mayis), Decimal("0"))
    mayis_net = mayis_giren - mayis_cikan
    donem_giren = sum((s["giren"] for s in donem_0106), Decimal("0"))
    donem_cikan = sum((s["cikan"] for s in donem_0106), Decimal("0"))
    donem_net = donem_giren - donem_cikan

    banka = json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BANKA.json").read_text(encoding="utf-8"))
    kaynak_tum = [
        h for h in (banka.get("hareketler") or []) if str(h.get("G.a_banka_id") or "") == HESAP_ID
    ]
    kaynak_d1 = []
    kaynak_d2_hamda = []
    for h in kaynak_tum:
        t = parse_tarih(h.get("G.a_tarih"))
        if t is None:
            continue
        if t <= DONEM_SONU:
            kaynak_d1.append(h)
        else:
            kaynak_d2_hamda.append(h)

    esleme = _eslestir(d1, kaynak_d1)

    # Kaynak toplamları D1
    kg = sum(((_yon_tutar(h)[0] or Decimal("0")) for h in kaynak_d1), Decimal("0"))
    kc = sum(((_yon_tutar(h)[1] or Decimal("0")) for h in kaynak_d1), Decimal("0"))

    kapanis_tamam = (
        esleme["tam_eslesme"]
        and yuruyen_d1["aritmetik_tutarli"]
        and _q2(giren_d1) == BEKLENEN_D1_GIREN
        and _q2(cikan_d1) == BEKLENEN_D1_CIKAN
        and _q2(kapanis_d1) == BEKLENEN_D1_KAPANIS
        and _q2(onceki_bakiye) == Decimal("0")
        and _q2(kg) == _q2(giren_d1)
        and _q2(kc) == _q2(cikan_d1)
    )

    d2_ser = []
    for s in d2:
        d2_ser.append(
            {
                "excel_satir": s["excel_satir"],
                "tarih": s["tarih"],
                "giren": str(s["giren"]),
                "cikan": str(s["cikan"]),
                "yuruyen_bakiye": str(s["yuruyen_bakiye"]) if s["yuruyen_bakiye"] is not None else None,
                "islem_turu": s["islem_turu"],
                "musteri": s["musteri"],
                "aciklama": s["aciklama"],
                "d1_hesaplamasina_katilmaz": True,
                "devir": 2,
            }
        )

    d1_ser = []
    for s in d1:
        d1_ser.append(
            {
                "excel_satir": s["excel_satir"],
                "tarih": s["tarih"],
                "giren": str(s["giren"]),
                "cikan": str(s["cikan"]),
                "yuruyen_bakiye": str(s["yuruyen_bakiye"]) if s["yuruyen_bakiye"] is not None else None,
                "islem_turu": s["islem_turu"],
                "musteri": s["musteri"],
                "aciklama": s["aciklama"],
                "devir": 1,
            }
        )

    akbank = _akbank_4355(banka)

    kanit = {
        "format": "d1-vakifbank-ekstre-excel-devir1-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devir": 1,
        "devir_2": "OGLEDEN_SONRA_BEKLIYOR",
        "manifest": {
            "hesap_id": HESAP_ID,
            "hesap_adi": HESAP_ADI,
            "excel": {
                "yol": "kaynak/excel/Vakifbank_Buyukcekmece_D1_20260831.xlsx",
                "kaynak_indirme": str(EXCEL_SRC),
                "sha256": sha_xlsx,
            },
            "kapsam_d1": {
                "satirlar": f"{D1_SATIR_BAS}-{D1_SATIR_SON}",
                "hareket_adet": len(d1),
                "bitis": DONEM_SONU.isoformat(),
            },
            "kapsam_d2_referans": {
                "satirlar": f"{D2_SATIR_BAS}-{D2_SATIR_SON}",
                "hareket_adet": len(d2),
                "tarihler": sorted({s["tarih"] for s in d2 if s["tarih"]}),
                "d1_hesaplamasina_katilmaz": True,
                "dosya_son_bakiye_agustos_kapanisi_degil": True,
                "dosya_son_bakiye": str(d2[-1]["yuruyen_bakiye"]) if d2 else None,
            },
            "kaynak_ham": "kaynak/D1_20260831_KAYNAK_BANKA.json",
        },
        "onceki_durum_0105": {
            **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in onceki.items()},
            "dogrulandi_0": _q2(onceki_bakiye) == Decimal("0"),
        },
        "d1_toplamlar": {
            "giren": str(giren_d1),
            "cikan": str(cikan_d1),
            "kapanis_0_arti_giren_eksi_cikan": str(kapanis_d1),
            "beklenen_giren": str(BEKLENEN_D1_GIREN),
            "beklenen_cikan": str(BEKLENEN_D1_CIKAN),
            "beklenen_kapanis": str(BEKLENEN_D1_KAPANIS),
            "giren_esit": _q2(giren_d1) == BEKLENEN_D1_GIREN,
            "cikan_esit": _q2(cikan_d1) == BEKLENEN_D1_CIKAN,
            "kapanis_esit": _q2(kapanis_d1) == BEKLENEN_D1_KAPANIS,
            "dosya_son_863_agustos_yapilmadi": True,
            "beklenen_dosya_son": str(BEKLENEN_DOSYA_SON),
            "dosya_son_gozlenen": str(d2[-1]["yuruyen_bakiye"]) if d2 else None,
        },
        "yuruyen_bakiye_d1": yuruyen_d1,
        "yuruyen_bakiye_d2_dosya_butunlugu": yuruyen_d2,
        "mayis_ve_onceki_donem_neti": {
            "mayis_hareket_adet": len(mayis),
            "mayis_giren": str(mayis_giren),
            "mayis_cikan": str(mayis_cikan),
            "mayis_net": str(mayis_net),
            "mayis_net_beklenen_50145": _q2(mayis_net) == MAYIS_NET,
            "donem_0106_3108_net": str(donem_net),
            "onceki_banka_toplami_donem_neti": str(ONCEKI_DONEM_NETI_0106),
            "aciklama": (
                f"Önceki Banka Toplamı dönem neti ({ONCEKI_DONEM_NETI_0106}) + Mayıs neti "
                f"({mayis_net}) = kapanış ({donem_net + mayis_net}). "
                "Mayıs hareketleri D1 kapsamına alındığında 50.145 TL ayrıca devir/açılış eklenmez."
            ),
            "ayrica_devir_eklenmedi": True,
            "aritmetik": {
                "donem_net_arti_mayis": str(donem_net + mayis_net),
                "kapanis": str(kapanis_d1),
                "esit": _q2(donem_net + mayis_net) == _q2(kapanis_d1),
                "onceki_negatif_arti_mayis": str(ONCEKI_DONEM_NETI_0106 + MAYIS_NET),
            },
        },
        "kaynak_karsilastirma": {
            "kaynak_tum_hesap_adet": len(kaynak_tum),
            "kaynak_d1_adet": len(kaynak_d1),
            "kaynak_d2_hamda_adet": len(kaynak_d2_hamda),
            "kaynak_d1_giren": str(kg),
            "kaynak_d1_cikan": str(kc),
            "kaynak_d1_net": str(kg - kc),
            "excel_kaynak_giren_kurus_esit": _q2(kg) == _q2(giren_d1),
            "excel_kaynak_cikan_kurus_esit": _q2(kc) == _q2(cikan_d1),
            "ham_kaynakta_d2_yok_beklenen": len(kaynak_d2_hamda) == 0,
            "esleme": esleme,
        },
        "d1_hareketler": d1_ser,
        "d2_referans_hareketler": d2_ser,
        "kapanis_kontrolu": {
            "hesap_id": HESAP_ID,
            "hesap_adi": HESAP_ADI,
            "tamam": kapanis_tamam,
            "kapanis_bakiye": str(BEKLENEN_D1_KAPANIS),
            "diger_hesaplar_icin_kabul_yerine_kullanilmaz": True,
            "kapsam": "yalnız bu Vakıfbank hesabı",
        },
        "akbank_4355_arastirma": akbank,
        "duzeltme_fisi_uretilmedi": True,
        "k05": False,
        "mali_yazim": False,
        "exe": False,
    }

    # tarih_date temizle nested
    def scrub(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: scrub(v) for k, v in o.items() if k != "tarih_date"}
        if isinstance(o, list):
            return [scrub(x) for x in o]
        if isinstance(o, Decimal):
            return str(o)
        return o

    kanit = scrub(kanit)
    yol, sha = yaz_kaynak("DOGRULAMA_VAKIFBANK_EKSTRE_EXCEL", kanit)

    ozet = {
        "zaman": kanit["zaman"],
        "hesap_id": HESAP_ID,
        "d1_hareket": len(d1),
        "d2_referans": len(d2),
        "kapanis": str(kapanis_d1),
        "kapanis_kontrol_tamam": kapanis_tamam,
        "esleme_tam": esleme["tam_eslesme"],
        "yuruyen_tutarli": yuruyen_d1["aritmetik_tutarli"],
        "mayis_net": str(mayis_net),
        "akbank_4355_bulgular": akbank["bulgular"],
        "k05": False,
        "kanit": f"kaynak/{yol.name}",
        "excel_sha256": sha_xlsx,
    }
    yaz_json(CALISMA / "VAKIFBANK_EKSTRE_EXCEL_OZET.json", ozet)

    print(
        json.dumps(
            {
                "kapanis_tamam": kapanis_tamam,
                "esleme": esleme["tam_eslesme"],
                "d1": len(d1),
                "d2": len(d2),
                "kapanis": str(kapanis_d1),
                "akbank_bulgular": akbank["bulgular"],
                "sha": sha[:16],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
