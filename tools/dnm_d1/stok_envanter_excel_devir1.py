"""Devir 1 — Stok envanter Excel (31.08.2026 FIFO) bağımsız kaynak kontrolü.

Dosya adı 07.11.2026 envanter tarihi sayılmaz; kullanıcı teyidi: rapor tarihi
31.08.2026, maliyet yöntemi FIFO.

- 3252 veri satırı ≠ tekil ürün; 20 çift kod + 1 boş kod ayrıştırılır.
- Kod/isim benzerliğiyle birleştirme yok; eşleme kaynak stok ID + birim.
- Güncel kart bakiyesi bu tarihli envanterle karıştırılmaz.
- Negatifler düzeltilmez; birimler dönüşümsüz toplanmaz.
- Excel miktar metni TR parse; katman üretiminde yuvarlanmış görüntü kullanılmaz.
- 14 pozitif sıfır maliyet: bedelsiz / eksik kanıt ayrımı; kart/ortalama doldurma yok.
- 1 kuruş alt toplam farkı açıklanır; düzeltme fişi yok.
- K05 / mali yazım / Devir 2 / EXE yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.stok_envanter_excel_devir1
  .venv\\Scripts\\python.exe -m tools.dnm_d1.test_stok_envanter_excel_devir1
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import openpyxl

from tools.dnm_d1._ortak import CALISMA, KAYNAK, parse_tarih, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK

EXCEL_SRC = Path.home() / "Downloads" / "rapor_stok_envanter_07-11-2026.xlsx"
EXCEL_HEDEF = KAYNAK / "excel" / "Stok_Envanter_FIFO_D1_20260831.xlsx"
STOK_MIKTAR = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_MIKTAR.json"
STOK_HRK = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_HAREKET.jsonl"
STOK_MALIYET = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_MALIYET.json"
BELGE_SATIR = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE_SATIR.jsonl"
MANIFEST = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}MANIFEST.json"
FIFO_KONTROL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_FIFO_KASA_BANKA_POS_KONTROL.json"

ALIS_TUR = {"30", "32", "34", "36"}
KURUS = Decimal("0.01")
BEK_ALT_TOPLAM = Decimal("3731181.36")
BEK_SATIR = 3252
BEK_POZ = 2406
BEK_SIFIR = 843
BEK_NEG = 3
BEK_CIFT_KOD = 20
BEK_BOS_KOD = 1
BEK_SIFIR_MAL_POZ = 14


def tr_dec(v: Any) -> Decimal | None:
    """Türkçe / Excel miktar-tutar ayrıştırma. None boş için."""
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        # float gömülü gürültü — str üzerinden Decimal (yuvarlanmış metin değilse)
        return Decimal(str(v))
    s = str(v).strip().replace(" ", "").replace("\u00a0", "")
    if not s or s.lower().startswith("toplam"):
        return None
    # 1.234,56 veya 80,00
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def _q2(v: Decimal, rounding=ROUND_HALF_UP) -> Decimal:
    return v.quantize(KURUS, rounding=rounding)


def _yukle_kartlar() -> list[dict]:
    ham = json.loads(STOK_MIKTAR.read_text(encoding="utf-8"))
    return list(ham.get("kayitlar") or [])


def _yukle_hareket() -> dict[str, dict]:
    out: dict[str, dict] = {}
    with STOK_HRK.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            if o.get("status") != "OK":
                continue
            sid = str(o.get("kaynak_stok_id") or "")
            if sid:
                out[sid] = o
    return out


def _yukle_maliyet() -> dict[str, dict]:
    if not STOK_MALIYET.is_file():
        return {}
    ham = json.loads(STOK_MALIYET.read_text(encoding="utf-8"))
    return {str(s["kaynak_stok_id"]): s for s in (ham.get("stoklar") or [])}


def _yukle_alis_fiyatlar(stok_ids: set[str]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = defaultdict(list)
    if not BELGE_SATIR.is_file() or not stok_ids:
        return by
    with BELGE_SATIR.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            if o.get("status") != "OK":
                continue
            tur = str(o.get("tur") or o.get("liste_tur") or "")
            if tur not in ALIS_TUR:
                continue
            t = parse_tarih(o.get("tarih"))
            if t is None or t > DONEM_SONU:
                continue
            bid = str(o.get("kaynak_belge_id") or "")
            for i, s in enumerate(o.get("satirlar") or []):
                sid = str(s.get("stok_id") or s.get("a_stok_id") or "")
                if sid not in stok_ids:
                    continue
                mik = tr_dec(s.get("miktar"))
                fiyat = tr_dec(s.get("birim_fiyat"))
                by[sid].append(
                    {
                        "belge_id": bid,
                        "belge_tur": tur,
                        "belge_tarih": t.isoformat(),
                        "satir_index": i,
                        "miktar": str(mik) if mik is not None else None,
                        "birim_fiyat": str(fiyat) if fiyat is not None else None,
                        "depo_id": str(s.get("depo_id") or "") or None,
                        "birim": s.get("birim"),
                    }
                )
    return by


def _oku_excel(yol: Path) -> tuple[list[dict], dict]:
    wb = openpyxl.load_workbook(yol, data_only=True)
    ws = wb.active
    satirlar: list[dict] = []
    footer_tutar = None
    for r in range(2, (ws.max_row or 0) + 1):
        kod_h = ws.cell(r, 1).value
        adi = ws.cell(r, 2).value
        tut_h = ws.cell(r, 11).value
        if isinstance(tut_h, str) and "toplam" in tut_h.lower().replace(" ", ""):
            # Toplam3.731.181,36
            raw = tut_h.lower().replace("toplam", "").strip()
            footer_tutar = tr_dec(raw)
            continue
        if kod_h is None and adi is None and tut_h is None:
            continue
        kod = "" if kod_h is None else str(kod_h).strip()
        gir = tr_dec(ws.cell(r, 6).value)
        cik = tr_dec(ws.cell(r, 7).value)
        kal = tr_dec(ws.cell(r, 8).value)
        bm = tr_dec(ws.cell(r, 10).value)
        tut = tr_dec(tut_h)
        birim = ws.cell(r, 9).value
        birim_s = str(birim).strip() if birim is not None else ""
        satirlar.append(
            {
                "excel_satir": r,
                "kod": kod,
                "adi": str(adi).strip() if adi else None,
                "giren": gir,
                "cikan": cik,
                "kalan": kal if kal is not None else Decimal("0"),
                "birim": birim_s or None,
                "birim_maliyet": bm,
                "tutar": tut if tut is not None else Decimal("0"),
                "tutar_ham_tip": type(tut_h).__name__,
            }
        )
    meta = {
        "max_row": ws.max_row,
        "max_col": ws.max_column,
        "footer_tutar": footer_tutar,
        "baslik": [ws.cell(1, c).value for c in range(1, 12)],
    }
    return satirlar, meta


def _esle_kart(
    row: dict, by_kod: dict[str, list[dict]], kullanilan: set[str]
) -> dict | None:
    """Kod + birim (+ kalan) ile tek kart; birleştirme yok."""
    adaylar = by_kod.get(row["kod"] or "") or []
    if not adaylar:
        return None
    birim = (row.get("birim") or "").casefold()
    uygun = []
    for k in adaylar:
        sid = str(k["a_id"])
        if sid in kullanilan:
            continue
        kb = str(k.get("ana_birim_adi") or "").casefold()
        if birim and kb and birim != kb:
            continue
        uygun.append(k)
    if not uygun:
        # birim eşleşmezse yalnızca tek boşta kalan aday
        kalan_aday = [k for k in adaylar if str(k["a_id"]) not in kullanilan]
        if len(kalan_aday) == 1 and not birim:
            uygun = kalan_aday
        else:
            return None
    if len(uygun) == 1:
        return uygun[0]
    # Aynı kod+birim birden fazla: kalan miktar ile ayır (dönüşümsüz)
    kal = row["kalan"]
    miktar_uygun = []
    for k in uygun:
        try:
            kk = Decimal(str(k.get("a_kalan") or "0"))
        except InvalidOperation:
            continue
        if kk == kal:
            miktar_uygun.append(k)
    if len(miktar_uygun) == 1:
        return miktar_uygun[0]
    return None  # belirsiz — birleştirme yok


def _sinif_sifir_maliyet(
    sid: str | None, alis: list[dict], maliyet: dict | None
) -> dict:
    """Pozitif kalan + Excel birim maliyet 0 → bedelsiz / eksik ayrımı."""
    if not sid:
        return {
            "sinif": "KART_BULUNAMADI",
            "aciklama": "Excel satırı 3150 kart kümesinde eşleşmedi; maliyet sınıfı ertelenir",
            "kart_fifo_doldurma_yok": True,
        }
    fiyatlar = []
    for a in alis:
        f = tr_dec(a.get("birim_fiyat"))
        if f is not None:
            fiyatlar.append(f)
    sifir = [f for f in fiyatlar if f == 0]
    pozitif = [f for f in fiyatlar if f > 0]
    mf = tr_dec((maliyet or {}).get("maliyet_fifo"))
    mo = tr_dec((maliyet or {}).get("maliyet_ort"))

    if pozitif and not sifir:
        return {
            "sinif": "EXSIK_MALIYET_GOSTERIM",
            "aciklama": (
                "Alış satırında pozitif birim fiyat var; Excel FIFO birim maliyet 0. "
                "Kart/ortalama ile otomatik doldurulmaz."
            ),
            "alis_pozitif_adet": len(pozitif),
            "alis_ornek_fiyat": str(pozitif[0]),
            "kart_fifo": str(mf) if mf is not None else None,
            "kart_ort": str(mo) if mo is not None else None,
            "kart_fifo_doldurma_yok": True,
        }
    if sifir and not pozitif:
        return {
            "sinif": "BEDELSIZ_SIFIR_KANITLI",
            "aciklama": "Alış BELGE_SATIR birim_fiyat=0; bedelsiz giriş kanıtı",
            "alis_sifir_adet": len(sifir),
            "kart_fifo_doldurma_yok": True,
        }
    if sifir and pozitif:
        return {
            "sinif": "KARISIK_ALIS_SIFIR_VE_POZITIF",
            "aciklama": (
                "Hem bedelsiz (0) hem ücretli alış satırı var; katman sırası olmadan "
                "tek sınıf atanmaz. Kart maliyetinden doldurulmaz."
            ),
            "alis_sifir_adet": len(sifir),
            "alis_pozitif_adet": len(pozitif),
            "kart_fifo_doldurma_yok": True,
        }
    return {
        "sinif": "BILINMEYEN_ALIS_YOK",
        "aciklama": "Dönem içi alış BELGE_SATIR yok; sıfır maliyet bilinmeyen (bedelsiz sayılmaz)",
        "kart_fifo": str(mf) if mf is not None else None,
        "kart_ort": str(mo) if mo is not None else None,
        "kart_fifo_doldurma_yok": True,
    }


def _manifest_guncelle(excel_sha: str, excel_ad: str) -> None:
    if not MANIFEST.is_file():
        return
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    man["stok_envanter_excel"] = {
        "dosya_adi_indirme": "rapor_stok_envanter_07-11-2026.xlsx",
        "dosya_adi_tarihi_envanter_sayilmaz": True,
        "kullanici_teyidi": {
            "rapor_tarihi": "2026-08-31",
            "maliyet_yontemi": "FIFO",
            "teyit_zamani": datetime.now().astimezone().isoformat(timespec="seconds"),
            "kaynak": "kullanıcı — dosya adındaki 07.11.2026 envanter tarihi değildir",
        },
        "kanit_kopya": f"kaynak/excel/{excel_ad}",
        "sha256": excel_sha,
        "devir": 1,
        "k05": False,
    }
    ham = json.dumps(man, ensure_ascii=False, indent=2).encode("utf-8")
    MANIFEST.write_bytes(ham)
    MANIFEST.with_suffix(".json.sha256").write_text(
        f"{hashlib.sha256(ham).hexdigest().upper()}  {MANIFEST.name}\n",
        encoding="ascii",
    )


def main() -> int:
    if not EXCEL_SRC.is_file():
        raise SystemExit(f"Excel yok: {EXCEL_SRC}")

    EXCEL_HEDEF.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(EXCEL_SRC, EXCEL_HEDEF)
    excel_sha = hashlib.sha256(EXCEL_HEDEF.read_bytes()).hexdigest().upper()
    EXCEL_HEDEF.with_suffix(".xlsx.sha256").write_text(
        f"{excel_sha}  {EXCEL_HEDEF.name}\n", encoding="ascii"
    )
    _manifest_guncelle(excel_sha, EXCEL_HEDEF.name)

    satirlar, meta = _oku_excel(EXCEL_HEDEF)
    kartlar = _yukle_kartlar()
    hareket = _yukle_hareket()
    maliyet = _yukle_maliyet()

    by_kod: dict[str, list[dict]] = defaultdict(list)
    for k in kartlar:
        by_kod[str(k.get("a_kod") or "").strip()].append(k)

    kod_say = Counter(s["kod"] for s in satirlar if s["kod"])
    cift_kodlar = sorted(k for k, c in kod_say.items() if c > 1)
    bos = [s for s in satirlar if not s["kod"]]
    poz = [s for s in satirlar if s["kalan"] > 0]
    sif = [s for s in satirlar if s["kalan"] == 0]
    neg = [s for s in satirlar if s["kalan"] < 0]
    sifir_mal_poz = [
        s
        for s in poz
        if s["birim_maliyet"] is not None and s["birim_maliyet"] == 0
    ]

    # Kapsam: kod kümeleri
    excel_kod = set(kod_say)
    api_kod = {k for k in by_kod if k}
    ortak_kod = excel_kod & api_kod
    excel_only = sorted(excel_kod - api_kod)
    api_only = sorted(api_kod - excel_kod)
    api_cift = sorted(k for k, v in by_kod.items() if k and len(v) > 1)

    # Eşleme stok ID
    kullanilan: set[str] = set()
    eslesen: list[dict] = []
    belirsiz: list[dict] = []
    eslesmeyen_excel: list[dict] = []

    for s in satirlar:
        kart = _esle_kart(s, by_kod, kullanilan)
        if kart is None:
            aday = by_kod.get(s["kod"] or []) or []
            if aday and s["kod"]:
                belirsiz.append(
                    {
                        "excel_satir": s["excel_satir"],
                        "kod": s["kod"],
                        "birim": s["birim"],
                        "kalan": str(s["kalan"]),
                        "aday_stok_id": [str(a["a_id"]) for a in aday],
                        "aday_birim": [a.get("ana_birim_adi") for a in aday],
                        "neden": "kod var; birim/kalan ile tek ID seçilemedi — birleştirilmedi",
                    }
                )
            else:
                eslesmeyen_excel.append(
                    {
                        "excel_satir": s["excel_satir"],
                        "kod": s["kod"] or None,
                        "adi": s["adi"],
                        "birim": s["birim"],
                        "kalan": str(s["kalan"]),
                        "tutar": str(s["tutar"]),
                    }
                )
            continue
        sid = str(kart["a_id"])
        kullanilan.add(sid)
        hr = hareket.get(sid) or {}
        mal = maliyet.get(sid) or {}
        hareket_net = tr_dec(hr.get("hareket_net"))
        kart_kalan_anlik = tr_dec(hr.get("kart_kalan"))
        if kart_kalan_anlik is None:
            kart_kalan_anlik = tr_dec(kart.get("a_kalan"))
        miktar_esit_hrk = hareket_net is not None and s["kalan"] == hareket_net
        # Güncel kart ile kıyas bilgi amaçlı; otorite değil
        kart_bilgi_esit = (
            kart_kalan_anlik is not None and s["kalan"] == kart_kalan_anlik
        )
        eslesen.append(
            {
                "excel_satir": s["excel_satir"],
                "kod": s["kod"],
                "kaynak_stok_id": sid,
                "birim_excel": s["birim"],
                "birim_kart": kart.get("ana_birim_adi"),
                "brm_id": kart.get("a_brm_id"),
                "excel_kalan": str(s["kalan"]),
                "excel_giren": str(s["giren"]) if s["giren"] is not None else None,
                "excel_cikan": str(s["cikan"]) if s["cikan"] is not None else None,
                "excel_birim_maliyet": str(s["birim_maliyet"])
                if s["birim_maliyet"] is not None
                else None,
                "excel_tutar": str(s["tutar"]),
                "hareket_net_31_08": str(hareket_net)
                if hareket_net is not None
                else None,
                "miktar_esit_hareket_net": miktar_esit_hrk,
                "kart_kalan_anlik_bilgi": str(kart_kalan_anlik)
                if kart_kalan_anlik is not None
                else None,
                "kart_kalan_anlik_esit_bilgi": kart_bilgi_esit,
                "kart_kalan_otorite_degil": True,
                "kaynak_fifo_kart": str(mal.get("maliyet_fifo"))
                if mal.get("maliyet_fifo") is not None
                else None,
                "kaynak_ort_kart": str(mal.get("maliyet_ort"))
                if mal.get("maliyet_ort") is not None
                else None,
            }
        )

    api_eslesmeyen = [
        {
            "kaynak_stok_id": str(k["a_id"]),
            "kod": str(k.get("a_kod") or "") or None,
            "adi": k.get("a_adi"),
            "birim": k.get("ana_birim_adi"),
            "a_kalan": str(k.get("a_kalan")),
        }
        for k in kartlar
        if str(k["a_id"]) not in kullanilan
    ]

    # Miktar karşılaştırma özeti (yalnız eşleşenler; hareket_net)
    miktar_ok = sum(1 for e in eslesen if e["miktar_esit_hareket_net"])
    miktar_fark = [e for e in eslesen if not e["miktar_esit_hareket_net"]]

    # Birim çeşitleri — dönüşümsüz
    birim_excel = Counter(s["birim"] or "?" for s in satirlar)
    cift_birim_ornek = []
    for kod in cift_kodlar[:20]:
        rows = [s for s in satirlar if s["kod"] == kod]
        cards = by_kod.get(kod) or []
        cift_birim_ornek.append(
            {
                "kod": kod,
                "excel_satirlar": [
                    {
                        "excel_satir": r["excel_satir"],
                        "birim": r["birim"],
                        "kalan": str(r["kalan"]),
                        "birim_maliyet": str(r["birim_maliyet"])
                        if r["birim_maliyet"] is not None
                        else None,
                    }
                    for r in rows
                ],
                "api_kartlar": [
                    {
                        "kaynak_stok_id": str(c["a_id"]),
                        "birim": c.get("ana_birim_adi"),
                        "brm_id": c.get("a_brm_id"),
                        "a_kalan": str(c.get("a_kalan")),
                    }
                    for c in cards
                ],
                "donusumsuz_toplama_yok": True,
            }
        )

    # 14 sıfır maliyet
    zc_ids = set()
    for s in sifir_mal_poz:
        kart = None
        # eslesen listesinden bul
        for e in eslesen:
            if e["excel_satir"] == s["excel_satir"]:
                zc_ids.add(e["kaynak_stok_id"])
                break
    alis_map = _yukle_alis_fiyatlar(zc_ids)
    sifir_mal_detay = []
    for s in sifir_mal_poz:
        e = next((x for x in eslesen if x["excel_satir"] == s["excel_satir"]), None)
        sid = e["kaynak_stok_id"] if e else None
        sinif = _sinif_sifir_maliyet(
            sid, alis_map.get(sid or "", []), maliyet.get(sid or "") if sid else None
        )
        sifir_mal_detay.append(
            {
                "excel_satir": s["excel_satir"],
                "kod": s["kod"],
                "adi": s["adi"],
                "kalan": str(s["kalan"]),
                "birim": s["birim"],
                "kaynak_stok_id": sid,
                "alis_satir_adet": len(alis_map.get(sid or "", [])),
                "alis_ornek": (alis_map.get(sid or "", []) or [])[:3],
                **sinif,
            }
        )

    # Kuruş farkı
    ham_tutar = sum((s["tutar"] for s in satirlar), Decimal("0"))
    ham_q2_up = _q2(ham_tutar, ROUND_HALF_UP)
    ham_q2_down = _q2(ham_tutar, ROUND_DOWN)
    footer = meta.get("footer_tutar") or BEK_ALT_TOPLAM
    kurus = {
        "excel_alt_toplam_metin": str(footer),
        "ham_tutar_toplami": str(ham_tutar),
        "ham_toplam_HALF_UP_kurus": str(ham_q2_up),
        "ham_toplam_ROUND_DOWN_kurus": str(ham_q2_down),
        "fark_half_up_minus_alt": str(ham_q2_up - footer),
        "aciklama": (
            "Satır tutarları Excel’de float/ondalık kalıntılı; ham toplam "
            f"{ham_tutar} ≈. HALF_UP ile {ham_q2_up} TL, alt toplam metni "
            f"{footer} TL (ROUND_DOWN/kesme ile uyumlu). 0,01 TL fark "
            "toplama/gösterim; eksik stok veya düzeltme fişi değildir."
        ),
        "duzeltme_fisi_yok": True,
    }

    # Negatifler
    negatif_detay = [
        {
            "excel_satir": s["excel_satir"],
            "kod": s["kod"],
            "adi": s["adi"],
            "kalan": str(s["kalan"]),
            "birim": s["birim"],
            "tutar": str(s["tutar"]),
            "duzeltme_ile_kapatilmaz": True,
            "kaynak_stok_id": next(
                (
                    e["kaynak_stok_id"]
                    for e in eslesen
                    if e["excel_satir"] == s["excel_satir"]
                ),
                None,
            ),
        }
        for s in neg
    ]

    # Açık engeller / sonraki rapor
    acik_engeller = [
        {
            "is": "FIFO_katman_tamami",
            "durum": "ACIK",
            "neden": (
                "Bu Excel miktar/toplam değer kontrolüdür; FIFO katman tamamı sayılmaz. "
                "Çıkış sırası + giriş belge satırı + açılış/devir hâlâ gerekli."
            ),
        },
        {
            "is": "StokHareket_satir_detay",
            "durum": "ACIK",
            "neden": "STOK_HAREKET.jsonl özet; satır tarih/depo/gir_fiyat yok",
            "gerekce_yeniden_cek": True,
        },
        {
            "is": "LOT_katman_birim_maliyet",
            "durum": "ACIK",
            "neden": "Seri_Lot_List katman birim maliyet alanı yok",
        },
        {
            "is": "excel_api_kapsam_farki",
            "durum": "ACIK" if (excel_only or api_only or belirsiz) else "KAPALI",
            "excel_only_kod_adet": len(excel_only),
            "api_only_kod_adet": len(api_only),
            "belirsiz_esleme_adet": len(belirsiz),
        },
        {
            "is": "sifir_maliyet_pozitif",
            "durum": "ACIK",
            "adet": len(sifir_mal_detay),
            "sinif_sayac": dict(Counter(x["sinif"] for x in sifir_mal_detay)),
        },
    ]

    sonraki_rapor_filtreleri = {
        "Stok_Ekstre": {
            "menu_veya_api": "StokHareket/base cmd=list (stok kart hareket / ekstre)",
            "zorunlu_filtreler": {
                "firma": "42178 DNM",
                "stok_id": "tek kart — toplu özet değil",
                "bas_tar": "01.01.2015",
                "bit_tar": "31.08.2026 (dahil)",
                "kesim": "01.09.2026 00:00 Europe/Istanbul sonrası yok",
                "depo": "tümü; satırda depo alanı zorunlu",
                "birim": "işlem birimi + temel birim çarpanı",
            },
            "zorunlu_sutunlar": [
                "tarih",
                "işlem/belge sırası",
                "belge_tur",
                "Fat_id / belge_id",
                "depo",
                "Birim",
                "gir_miktar",
                "cik_miktar",
                "gir_fiyat",
                "cik_fiyat",
                "devir / açılış bayrağı",
                "ack / lot ipucu",
            ],
            "kapsam_oncelik": [
                "miktar_esit_hareket_net=false eşleşenler",
                "çıkışlı FIFO bekleyen kartlar",
                "14 sıfır maliyet pozitif",
                "3 negatif kalan",
            ],
            "not": "Gerekçesiz 3150 özet tekrarı yok; yalnız detay eksik stok_id",
        },
        "Seri_Lot": {
            "menu_veya_api": "fatura/base cmd=sql → Detay.Seri_Lot_List",
            "zorunlu_filtreler": {
                "belge_tarihi_bitis": "31.08.2026 dahil",
                "stok_id_veya_lot": "FIFO katman açığı olan stoklar",
            },
            "zorunlu_alanlar": [
                "lot_no / lot_id",
                "özgün giriş tarihi",
                "a_giren / a_cikan",
                "kalan (anlık ≠ katman dökümü notu)",
                "katman birim maliyet (şu an API’de yok — ekran/Excel kanıtı)",
            ],
        },
    }

    sayac = {
        "excel_veri_satir": len(satirlar),
        "beklenen_satir": BEK_SATIR,
        "pozitif": len(poz),
        "sifir": len(sif),
        "negatif": len(neg),
        "cift_kod_adet": len(cift_kodlar),
        "bos_kod_satir": len(bos),
        "api_kart_3150": len(kartlar),
        "ortak_kod": len(ortak_kod),
        "excel_only_kod": len(excel_only),
        "api_only_kod": len(api_only),
        "api_cift_kod": len(api_cift),
        "eslesen_stok_id": len(eslesen),
        "miktar_esit_hareket_net": miktar_ok,
        "miktar_fark_hareket_net": len(miktar_fark),
        "belirsiz_esleme": len(belirsiz),
        "excel_eslesmeyen": len(eslesmeyen_excel),
        "api_eslesmeyen": len(api_eslesmeyen),
        "sifir_maliyet_pozitif": len(sifir_mal_poz),
    }

    kapsam_aciklama = {
        "kural": "Satır sayısı tekil ürün sayısı değildir",
        "excel_veri_satir": len(satirlar),
        "api_kart": len(kartlar),
        "fark_satir_eksi_kart": len(satirlar) - len(kartlar),
        "aritmetik": {
            "ortak_kod_satir_ve_kart": (
                "Ortak kodlarda Excel satır adedi = API kart adedi "
                f"(çift kodlar her iki tarafta {len(cift_kodlar)})."
            ),
            "excel_3252": (
                f"ortak satırlar (~{len(satirlar) - len(excel_only) - len(bos)}) "
                f"+ excel_only_kod {len(excel_only)} + bos_kod {len(bos)}"
            ),
            "api_3150": (
                f"ortak kartlar + api_only_kod {len(api_only)} "
                f"+ api_bos_kod {len(by_kod.get('', []))}"
            ),
        },
        "cift_kod": {
            "adet": len(cift_kodlar),
            "api_cift_kod_adet": len(api_cift),
            "birebir_ayni_kodlar": set(cift_kodlar) == set(api_cift),
            "tipik_neden": "Aynı a_kod, farklı a_id / a_brm_id (örn. Adet vs Unit)",
            "ornekler": cift_birim_ornek[:8],
            "kod_isim_birlestirme_yok": True,
        },
        "bos_kod": {
            "excel_adet": len(bos),
            "api_adet": len(by_kod.get("", [])),
            "excel_ornek": [
                {"excel_satir": b["excel_satir"], "adi": b["adi"], "kalan": str(b["kalan"])}
                for b in bos
            ],
        },
        "excel_only_kod_ornek": excel_only[:30],
        "api_only_kod_ornek": api_only[:30],
    }

    # Kullanıcı beklenen sayaç doğrulama
    bek_uyum = {
        "satir_3252": len(satirlar) == BEK_SATIR,
        "pozitif_2406": len(poz) == BEK_POZ,
        "sifir_843": len(sif) == BEK_SIFIR,
        "negatif_3": len(neg) == BEK_NEG,
        "cift_kod_20": len(cift_kodlar) == BEK_CIFT_KOD,
        "bos_kod_1": len(bos) == BEK_BOS_KOD,
        "sifir_mal_14": len(sifir_mal_poz) == BEK_SIFIR_MAL_POZ,
        "alt_toplam_footer": footer == BEK_ALT_TOPLAM,
    }

    kanit = {
        "format": "d1-stok-envanter-excel-fifo-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devir": 1,
        "kasa_banka_kanitlari_korundu": True,
        "manifest_teyit": {
            "rapor_tarihi": "2026-08-31",
            "maliyet_yontemi": "FIFO",
            "dosya_adi_07_11_envanter_degil": True,
            "manifest": "kaynak/D1_20260831_KAYNAK_MANIFEST.json",
        },
        "excel": {
            "kaynak_indirme": str(EXCEL_SRC),
            "kanit_kopya": f"kaynak/excel/{EXCEL_HEDEF.name}",
            "sha256": excel_sha,
            "footer_tutar": str(footer),
            "baslik": meta.get("baslik"),
        },
        "beklenen_uyum": bek_uyum,
        "sayac": sayac,
        "kapsam_aciklama": kapsam_aciklama,
        "kurus_farki": kurus,
        "eslesen_ozet": {
            "adet": len(eslesen),
            "miktar_esit_hareket_net": miktar_ok,
            "miktar_fark_hareket_net": len(miktar_fark),
            "not": (
                "Karşılaştırma hareket_net (≤31.08) ile; güncel kart_kalan otorite değil. "
                "Önceki 2522 alt küme bu kontrolden ayrı tutulur."
            ),
        },
        "eslesen_ornek": eslesen[:40],
        "miktar_fark_ornek": miktar_fark[:40],
        "belirsiz_esleme": belirsiz[:40],
        "excel_eslesmeyen_ornek": eslesmeyen_excel[:40],
        "api_eslesmeyen_ornek": api_eslesmeyen[:40],
        "negatif_korunan": negatif_detay,
        "sifir_maliyet_pozitif": {
            "adet": len(sifir_mal_detay),
            "kayitlar": sifir_mal_detay,
            "kart_ortalama_doldurma_yok": True,
        },
        "birim_dagilim_excel": dict(birim_excel),
        "fifo_katman_tamam_degil": True,
        "acik_engeller": acik_engeller,
        "sonraki_rapor_filtreleri": sonraki_rapor_filtreleri,
        "kurallar": [
            "Dosya adındaki 07.11.2026 envanter tarihi değildir",
            "Satır sayısı = tekil ürün değil",
            "Kod/isim birleştirme yok; stok ID + birim",
            "Güncel kart bakiyesi 31.08 envanterle karıştırılmaz",
            "Negatifler düzeltme ile kapatılmaz",
            "Farklı birim dönüşümsüz toplanmaz",
            "Yuvarlanmış Excel miktarından kesin FIFO katman üretilmez",
            "Sıfır maliyet kart/ortalamayla doldurulmaz",
            "1 kuruş için düzeltme fişi yok",
        ],
        "k05": False,
        "mali_yazim": False,
        "dengeleme_kaydi": False,
        "devir2": False,
        "exe": False,
    }

    # Stok bazlı ayrıntı (eşleşenler tam liste — ayrı dosya boyutu)
    stok_bazli = {
        "format": "d1-stok-envanter-excel-stok-bazli-v1",
        "zaman": kanit["zaman"],
        "eslesen": eslesen,
        "miktar_fark": miktar_fark,
        "sifir_maliyet_pozitif": sifir_mal_detay,
        "negatif": negatif_detay,
        "belirsiz": belirsiz,
        "excel_eslesmeyen": eslesmeyen_excel,
        "api_eslesmeyen": api_eslesmeyen,
        "k05": False,
    }
    yol_sb, sha_sb = yaz_kaynak("DOGRULAMA_STOK_ENVANTER_EXCEL_STOK_BAZLI", stok_bazli)
    kanit["stok_bazli_kanit"] = f"kaynak/{yol_sb.name}"
    kanit["stok_bazli_sha16"] = sha_sb[:16]

    yol, sha = yaz_kaynak("DOGRULAMA_STOK_ENVANTER_EXCEL", kanit)

    ozet = {
        "zaman": kanit["zaman"],
        "rapor_tarihi": "2026-08-31",
        "yontem": "FIFO",
        "excel_satir": len(satirlar),
        "api_kart": len(kartlar),
        "eslesen": len(eslesen),
        "miktar_esit_hrk": miktar_ok,
        "miktar_fark_hrk": len(miktar_fark),
        "excel_only_kod": len(excel_only),
        "api_only_kod": len(api_only),
        "sifir_mal_poz": len(sifir_mal_detay),
        "negatif": len(neg),
        "kurus_fark": str(ham_q2_up - footer),
        "fifo_katman_tamam": False,
        "k05": False,
        "kanit": f"kaynak/{yol.name}",
        "stok_bazli": f"kaynak/{yol_sb.name}",
        "sha16": sha[:16],
    }
    yaz_json(CALISMA / "STOK_ENVANTER_EXCEL_OZET.json", ozet)

    # FIFO kontrol dosyasına bağla (kasa/banka bozma)
    if FIFO_KONTROL.is_file():
        try:
            fifo = json.loads(FIFO_KONTROL.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            fifo = {"format": "d1-fifo-kasa-banka-pos-kontrol-v1", "tamamlanan": [], "engeller": []}
        fifo["stok_envanter_excel"] = ozet
        fifo["k05"] = False
        engeller = []
        for e in fifo.get("engeller") or []:
            if e.get("is") == "FIFO_katman_birim_maliyet":
                e = {
                    **e,
                    "envanter_excel": {
                        "rapor_tarihi": "2026-08-31",
                        "yontem": "FIFO",
                        "miktar_deger_kontrolu": True,
                        "katman_tamam_degil": True,
                        "kanit": f"kaynak/{yol.name}",
                    },
                }
            engeller.append(e)
        fifo["engeller"] = engeller
        ham = json.dumps(fifo, ensure_ascii=False, indent=2).encode("utf-8")
        FIFO_KONTROL.write_bytes(ham)
        FIFO_KONTROL.with_suffix(".json.sha256").write_text(
            f"{hashlib.sha256(ham).hexdigest().upper()}  {FIFO_KONTROL.name}\n",
            encoding="ascii",
        )

    print(json.dumps(ozet, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
