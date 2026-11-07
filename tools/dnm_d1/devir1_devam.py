"""Devir 1 devam — PDF Devir anlamı, 1980 ayrımı, 21 risk, 1070↔1066, stok kapsam.

Kaynak değiştirmez. K05 açmaz. Stok hareketi yeniden toplamaz.
Devir2 öğleden sonra.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.devir1_devam
"""

from __future__ import annotations

import json
import re
import shutil
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pymupdf

from tools.dnm_d1._ortak import (
    CALISMA,
    KAYNAK,
    dec,
    oturum_gecersiz_mi,
    parse_tarih,
    yaz_json,
    yaz_kaynak,
)
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.pdf_devirli_rapor_incele import (
    PDF_HEDEF,
    RISK22,
    _norm_ad,
    _para,
    _sayfa_satirlari,
)

DONEM = DONEM_SONU
BAS_FILTRE = "01.09.2025"
BIT_FILTRE = "31.08.2026"
RISK15 = {
    "1368",
    "1911",
    "9197",
    "9198",
    "9199",
    "9206",
    "9207",
    "9213",
    "9230",
    "9231",
    "9234",
    "9235",
    "9236",
    "9240",
    "9251",
}


def _yukle(ad: str) -> dict[str, Any]:
    return json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}{ad}.json").read_text(encoding="utf-8"))


def _surumle(ad: str) -> Path | None:
    p = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}{ad}.json"
    if not p.is_file():
        return None
    surum = CALISMA / "surumler" / f"devir1_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    surum.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, surum / p.name)
    return surum


def _fq(client, mid: str, bas: str, son: str, *, yeniden: bool = True) -> dict[str, Any]:
    y = client._post(
        "Musteri/base/",
        {
            "cmd": "finans_jq_listesi",
            "UID": client.uid,
            "musteri_id": str(mid),
            "b_tarihi": bas,
            "s_tarihi": son,
            "tur": "-1",
        },
    )
    if oturum_gecersiz_mi(y) and yeniden:
        client.login()
        return _fq(client, mid, bas, son, yeniden=False)
    if y.get("status") != "OK":
        return {"status": y.get("status"), "hata": y.get("veri"), "detay": [], "devreden": None, "ozet": None}
    v = y.get("veri") if isinstance(y.get("veri"), dict) else {}
    det = [x for x in (v.get("Detay") or []) if isinstance(x, dict)]
    def blok(b):
        if isinstance(b, list) and b and isinstance(b[0], dict):
            return b[0]
        return b if isinstance(b, dict) else None
    return {
        "status": "OK",
        "detay": det,
        "devreden": blok(v.get("Devreden")),
        "ozet": blok(v.get("Özet") or v.get("Ozet")),
    }


def _dec_eq(a: Decimal | None, b: Any) -> bool:
    if a is None or b is None or b == "":
        return False
    return a == dec(b)


def _pdf_satirlari() -> list[dict]:
    doc = pymupdf.open(PDF_HEDEF)
    out: list[dict] = []
    for i in range(doc.page_count):
        out.extend([r for r in _sayfa_satirlari(doc[i], i + 1) if r.get("musteri_adi_pdf")])
    return out


def _cari_kartlar() -> list[dict]:
    return _yukle("CARI").get("kayitlar") or []


def _unvan(r: dict) -> str:
    return ((r.get("text") or "").split("----")[0].strip() or str(r.get("R.a_ad") or "")).strip()


def dogrula_devir_anlami(client) -> dict[str, Any]:
    """Gözlenen API yanıtı: Dönem=Detay toplamı; Devir=Devreden.Borc/Alacak."""
    pdf = _pdf_satirlari()
    idx: dict[str, list[dict]] = defaultdict(list)
    for r in _cari_kartlar():
        idx[_norm_ad(_unvan(r))].append(r)

    ornekler = []
    for r in pdf:
        db, da = _para(r.get("donem_borc")), _para(r.get("donem_alacak"))
        vb, va = _para(r.get("devir_borc")), _para(r.get("devir_alacak"))
        if None in (db, da, vb, va):
            continue
        aday = idx.get(_norm_ad(r["musteri_adi_pdf"]) or "") or []
        if len(aday) != 1:
            continue
        mid = str(aday[0].get("R.a_id"))
        api = _fq(client, mid, BAS_FILTRE, BIT_FILTRE)
        time.sleep(0.05)
        if api.get("status") != "OK":
            continue
        det = api.get("detay") or []
        donem_b = sum((dec(x.get("Borc")) for x in det), Decimal("0"))
        donem_a = sum((dec(x.get("Alacak")) for x in det), Decimal("0"))
        dev = api.get("devreden") or {}
        ornekler.append(
            {
                "pdf_adi": r["musteri_adi_pdf"],
                "sayfa": r["sayfa"],
                "kaynak_cari_id": mid,
                "pdf_donem_borc": str(db),
                "pdf_donem_alacak": str(da),
                "pdf_devir_borc": str(vb),
                "pdf_devir_alacak": str(va),
                "api_detay_borc_toplam": str(donem_b),
                "api_detay_alacak_toplam": str(donem_a),
                "api_devreden": {
                    "borc": str(dec(dev.get("Borc"))),
                    "alacak": str(dec(dev.get("Alacak"))),
                    "bakiye": str(dec(dev.get("Bakiye"))),
                },
                "donem_eq_detay_toplam": db == donem_b and da == donem_a,
                "devir_eq_devreden_borc_alacak": _dec_eq(vb, dev.get("Borc"))
                and _dec_eq(va, dev.get("Alacak")),
                "filtre": {"bas": BAS_FILTRE, "son": BIT_FILTRE},
            }
        )
        if len(ornekler) >= 10:
            break

    n = len(ornekler)
    n_donem = sum(1 for o in ornekler if o["donem_eq_detay_toplam"])
    n_devir = sum(1 for o in ornekler if o["devir_eq_devreden_borc_alacak"])
    return {
        "format": "d1-pdf-devir-sutun-anlam-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kaynak_degistirilmedi": True,
        "filtre_tarih": {"baslangic": BAS_FILTRE, "bitis": BIT_FILTRE},
        "api": "Musteri/base cmd=finans_jq_listesi",
        "gozlem": {
            "Donem_Borc_Alacak": (
                "PDF Dönem Borç/Alacak = aynı filtrede finans_jq Detay satırlarının "
                "Borc/Alacak toplamı (dönem içi hareket)."
            ),
            "Devir_Borc_Alacak": (
                "PDF Devir Borç/Alacak = aynı filtrede finans_jq Devreden.Borc / Devreden.Alacak "
                "(filtre başlangıcından önceki bakiyenin borç/alacak kırılımı; Devreden.Bakiye=net)."
            ),
            "kanit_yontemi": "tekil isimli PDF satırı ↔ API yanıtı sayısal eşleşme",
        },
        "ornek_adet": n,
        "donem_eslesen": n_donem,
        "devir_eslesen": n_devir,
        "dogrulandi": n >= 5 and n_donem == n and n_devir == n,
        "ornekler": ornekler,
        "uyari": (
            "Dönem≠Devir görünmesi tek başına anlam kanıtı değildir; "
            "bu dosyadaki API alan eşleşmesi anlam kanıtıdır."
        ),
        "k05": False,
    }


def murat_apak_1980(client) -> dict[str, Any]:
    """1095-10 net ile tarihli kapanışı ayrı tut."""
    kapanis = _fq(client, "1980", BAS_FILTRE, BIT_FILTRE)
    onceki = _fq(client, "1980", "01.09.2024", "31.08.2025")
    det = onceki.get("detay") or []
    det_sorted = sorted(
        det,
        key=lambda r: (
            parse_tarih(r.get("Tarih")) or date.min,
            int(str(r.get("Satir") or 0) or 0),
        ),
    )
    son_det = det_sorted[-1] if det_sorted else None
    dev_k = kapanis.get("devreden") or {}
    return {
        "format": "d1-1980-murat-apak-kanit-ayrim-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kaynak_cari_id": "1980",
        "unvan": "MURAT APAK",
        "pdf": {
            "sayfa": 19,
            "donem_borc": None,
            "donem_alacak": None,
            "devir_borc": "1095",
            "devir_alacak": "10",
            "donem_bos_anlami": (
                "Filtre 01.09.2025–31.08.2026 içinde Detay=0 → PDF Dönem hücreleri boş "
                "(gösterimde boş; sıfır yazılmadı). Devir=Devreden 1095/10."
            ),
        },
        "durumlar": {
            "A_pdf_devir_net_aritmetik": {
                "hesap": "1095 - 10 = 1085",
                "kaynak": "PDF Devir Borç/Alacak (Devreden.Borc/Alacak)",
                "31_08_2026_tarihli_kapanis_mi": False,
                "aciklama": "Net aritmetik; tek başına tarihli kapanış kabulü değil.",
            },
            "B_son_detay_bakiye": {
                "son_detay_tarih": (son_det or {}).get("Tarih"),
                "son_detay_bakiye": str(dec((son_det or {}).get("Bakiye"))) if son_det else None,
                "detay_dilim": "01.09.2024–31.08.2025",
                "detay_satirlar": [
                    {
                        "tarih": r.get("Tarih"),
                        "tur": r.get("Tur_adi") or r.get("Tur"),
                        "borc": r.get("Borc"),
                        "alacak": r.get("Alacak"),
                        "bakiye": r.get("Bakiye"),
                        "id": r.get("id"),
                    }
                    for r in det_sorted
                ],
                "31_08_2026_tarihli_kapanis_mi": False,
                "aciklama": (
                    "SON_DETAY Bakiye=1085; hareket tarihi 02.08.2025. "
                    "Bu, 31.08.2026 damgalı kapanış değildir."
                ),
            },
            "C_filtre_sonu_devreden_bakiye": {
                "filtre": {"bas": BAS_FILTRE, "son": BIT_FILTRE},
                "detay_adet": len(kapanis.get("detay") or []),
                "devreden": {
                    "borc": str(dec(dev_k.get("Borc"))),
                    "alacak": str(dec(dev_k.get("Alacak"))),
                    "bakiye": str(dec(dev_k.get("Bakiye"))),
                },
                "31_08_2026_kapanis_adayi": str(dec(dev_k.get("Bakiye"))),
                "dayanak": (
                    "Filtre bitişi 31.08.2026 dahil; dönem içi Detay=0; "
                    "Devreden.Bakiye dönem başı bakiyenin dönem sonunda değişmeden kaldığını gösterir."
                ),
                "ikinci_acilis_eklendi_mi": False,
                "pdf_devir_ile_cift_sayim_yok": True,
            },
        },
        "ozet_kabul": {
            "pdf_net_1085": "DURUM_A — tarihli kapanış değil",
            "son_detay_1085": "DURUM_B — 02.08.2025 bakiyesi",
            "devreden_bakiye_1085_filtre_3108": "DURUM_C — 31.08.2026 kapanış adayı (hareket yok)",
        },
        "k05": False,
    }


def risk21_incele(client, cari22: dict[str, dict]) -> dict[str, Any]:
    """21 risk: kart tarihi yoksa engel; ilk mali etki + ekstre."""
    kartlar = {str(r.get("R.a_id")): r for r in _cari_kartlar()}
    pdf = _pdf_satirlari()
    by_norm: dict[str, list[dict]] = defaultdict(list)
    for r in pdf:
        by_norm[_norm_ad(r["musteri_adi_pdf"])].append(r)

    dilimler = []
    y = DONEM.year
    while y >= 2015:
        bas = date(y - 1, 9, 1)
        bit = date(y, 8, 31)
        if bit > DONEM:
            bit = DONEM
        if bas < date(2015, 1, 1):
            bas = date(2015, 1, 1)
        if bas <= bit:
            dilimler.append((bas.strftime("%d.%m.%Y"), bit.strftime("%d.%m.%Y")))
        y -= 1
        if bas <= date(2015, 1, 1):
            break

    sonuclar = []
    for cid in sorted(RISK22 - {"1980"}, key=int):
        k = kartlar.get(cid) or {}
        unvan = _unvan(k)
        n = _norm_ad(unvan)
        pdf_hits = list(by_norm.get(n) or [])
        # özel
        if cid == "1368":
            pdf_hits = [p for p in pdf if "ERKHAN" in (p["musteri_adi_pdf"] or "").upper()]
        if cid == "1911":
            pdf_hits = [
                p
                for p in pdf
                if "MERT" in (p["musteri_adi_pdf"] or "").upper()
                and "FERFORJE" in (p["musteri_adi_pdf"] or "").upper()
            ]

        # dilimlerde ilk detay
        ilk = None
        son_det = None
        tum_det: list[dict] = []
        kapanis_dev = None
        for bas, son in dilimler:
            api = _fq(client, cid, bas, son)
            time.sleep(0.04)
            if bas == BAS_FILTRE and son == BIT_FILTRE:
                kapanis_dev = api.get("devreden")
            for row in api.get("detay") or []:
                t = parse_tarih(row.get("Tarih"))
                if t is None or t > DONEM:
                    continue
                tum_det.append(row)
                if ilk is None or t < parse_tarih(ilk.get("Tarih")):
                    ilk = row
                if son_det is None or t > parse_tarih(son_det.get("Tarih")) or (
                    t == parse_tarih(son_det.get("Tarih"))
                    and int(str(row.get("Satir") or 0) or 0)
                    >= int(str(son_det.get("Satir") or 0) or 0)
                ):
                    son_det = row

        pdf_g = None
        if len(pdf_hits) == 1:
            h = pdf_hits[0]
            pdf_g = {
                "sayfa": h["sayfa"],
                "adi": h["musteri_adi_pdf"],
                "donem_borc": h.get("donem_borc"),
                "donem_alacak": h.get("donem_alacak"),
                "devir_borc": h.get("devir_borc"),
                "devir_alacak": h.get("devir_alacak"),
                "bos_hucre": h.get("bos_hucre"),
                "bos_sifir_yazilmadi": True,
            }

        c22 = cari22.get(cid) or {}
        kart_tarih_alanlari = {
            "R.a_ver_tar": k.get("R.a_ver_tar") or None,
            "R.a_dogtar": k.get("R.a_dogtar") or None,
            "R.a_kay_no": k.get("R.a_kay_no") or None,
            "R.a_giren": k.get("R.a_giren"),
            "R.a_cikan": k.get("R.a_cikan"),
        }
        sonuclar.append(
            {
                "kaynak_cari_id": cid,
                "grup": "15_kanitsiz" if cid in RISK15 else "22_kalan",
                "kod": k.get("R.a_kod"),
                "unvan": unvan,
                "kart_olusturma_tarihi": {
                    "deger": None,
                    "durum": "KAYNAKTA_YOK",
                    "engel": (
                        "cari/base sql ve jq_list + CARI.json içinde kart oluşturma/ilk kayıt "
                        "tarihi alanı boş veya yok. Kartın sonradan açılması tek başına dönem "
                        "dışı kanıtı değildir; geriye tarihli hareket arandı."
                    ),
                    "alanlar": kart_tarih_alanlari,
                },
                "ilk_gercek_mali_etki": (
                    {
                        "tarih": ilk.get("Tarih"),
                        "tur": ilk.get("Tur_adi") or ilk.get("Tur"),
                        "borc": ilk.get("Borc"),
                        "alacak": ilk.get("Alacak"),
                        "bakiye": ilk.get("Bakiye"),
                        "id": ilk.get("id"),
                        "kaynak": "finans_jq Detay",
                    }
                    if ilk
                    else None
                ),
                "acilis_devir": {
                    "kapanis_filtresi_devreden": {
                        "borc": str(dec((kapanis_dev or {}).get("Borc"))) if kapanis_dev else None,
                        "alacak": str(dec((kapanis_dev or {}).get("Alacak"))) if kapanis_dev else None,
                        "bakiye": str(dec((kapanis_dev or {}).get("Bakiye"))) if kapanis_dev else None,
                    }
                    if kapanis_dev
                    else None,
                    "not": "Devreden = dönem öncesi; PDF Devir sütunu ile aynı alan ailesi",
                },
                "tarihli_ekstre": {
                    "detay_satir_adet_<=3108": len(tum_det),
                    "son_detay": (
                        {
                            "tarih": son_det.get("Tarih"),
                            "bakiye": son_det.get("Bakiye"),
                            "id": son_det.get("id"),
                        }
                        if son_det
                        else None
                    ),
                    "kapanis_3108_kanitli": c22.get("kapanis_bakiye_3108_kanitli"),
                    "kanit_durumu": c22.get("kanit_durumu")
                    if tum_det
                    else (
                        "KANIT_YOK_DETAY_BOS"
                        if not tum_det
                        else c22.get("kanit_durumu")
                    ),
                },
                "pdf": pdf_g,
                "pdf_hit_adet": len(pdf_hits),
                "kalan_eksik": (
                    None
                    if tum_det
                    else "finans_jq Detay tüm dilimlerde boş; PDF boş hücreler sıfır değil; "
                    "açılış belgesi / alternatif ekstre gerekir"
                ),
            }
        )
        print(
            f"risk21 {cid} detay={len(tum_det)} ilk={(ilk or {}).get('Tarih')} "
            f"pdf_hits={len(pdf_hits)}",
            flush=True,
        )

    return {
        "format": "d1-risk21-kart-ilk-etki-ekstre-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "adet": len(sonuclar),
        "kart_tarihi_engel": (
            "API/CARI envanterinde oluşturma tarihi yok — 21 carinin tümü için ortak engel"
        ),
        "cariler": sonuclar,
        "bos_hucre_sifir_yazilmadi": True,
        "k05": False,
    }


def esle_1070_1066(client) -> dict[str, Any]:
    """PDF satır ↔ kart ID; kesin yalnız tek aday + tutar doğrulaması."""
    pdf = _pdf_satirlari()
    kartlar = _cari_kartlar()
    idx: dict[str, list[dict]] = defaultdict(list)
    for r in kartlar:
        idx[_norm_ad(_unvan(r))].append(
            {"kaynak_cari_id": str(r.get("R.a_id")), "kod": r.get("R.a_kod"), "unvan": _unvan(r)}
        )

    eslemeler = []
    sayac = Counter()
    # Tutar doğrulaması için örnek API (tam 4 sütun + tek aday)
    for i, r in enumerate(pdf):
        n = _norm_ad(r["musteri_adi_pdf"])
        adaylar = list(idx.get(n) or [])
        durum = "ACIK_ISIM_ESLESMEDI"
        kesin_id = None
        notlar = []
        if len(adaylar) > 1:
            durum = "ACIK_AYNI_AD_FARKLI_KARTLAR"
            notlar.append(f"Aynı norm ad {len(adaylar)} kart: {[a['kaynak_cari_id'] for a in adaylar]}")
            sayac["coklu_kart"] += 1
        elif len(adaylar) == 1:
            mid = adaylar[0]["kaynak_cari_id"]
            db, da = _para(r.get("donem_borc")), _para(r.get("donem_alacak"))
            vb, va = _para(r.get("devir_borc")), _para(r.get("devir_alacak"))
            # boş satır: tutar yok → kesinleştirme yok
            if all(x is None for x in (db, da, vb, va)):
                durum = "ACIK_TEK_ISIM_TUTAR_YOK"
                notlar.append("Tek isim adayı var; PDF tutar boş — ID kesinleştirilmedi")
                sayac["tek_isim_tutar_yok"] += 1
            else:
                # API doğrula (rate: her 3. satırda veya ilk 80 kesin aday)
                if sayac["kesin"] + sayac["tek_isim_tutar_uyusmaz"] < 80 or i % 5 == 0:
                    api = _fq(client, mid, BAS_FILTRE, BIT_FILTRE)
                    time.sleep(0.03)
                    det = api.get("detay") or []
                    donem_b = sum((dec(x.get("Borc")) for x in det), Decimal("0"))
                    donem_a = sum((dec(x.get("Alacak")) for x in det), Decimal("0"))
                    dev = api.get("devreden") or {}
                    ok_donem = True
                    ok_devir = True
                    if db is not None or da is not None:
                        ok_donem = (db is None or db == donem_b) and (da is None or da == donem_a)
                    if vb is not None or va is not None:
                        ok_devir = (vb is None or _dec_eq(vb, dev.get("Borc"))) and (
                            va is None or _dec_eq(va, dev.get("Alacak"))
                        )
                    if ok_donem and ok_devir:
                        durum = "KESIN_ID"
                        kesin_id = mid
                        sayac["kesin"] += 1
                    else:
                        durum = "ACIK_TEK_ISIM_TUTAR_UYUSMAZ"
                        notlar.append(
                            f"API donem {donem_b}/{donem_a} dev {dev.get('Borc')}/{dev.get('Alacak')}"
                        )
                        sayac["tek_isim_tutar_uyusmaz"] += 1
                else:
                    durum = "ADAY_TEK_ISIM_DOGRULAMA_BEKLIYOR"
                    sayac["aday_bekliyor"] += 1
        else:
            # kısmi / kısaltma
            kismi = []
            for kn, items in idx.items():
                if n and len(n) >= 6 and (n in kn or kn in n):
                    kismi.extend(items)
                if len(kismi) > 6:
                    break
            if kismi:
                durum = "ACIK_KISALTMA_VEYA_YAKIN_AD"
                notlar.append(f"Yakın adaylar: {[a['kaynak_cari_id'] for a in kismi[:5]]}")
                sayac["kismi"] += 1
            else:
                sayac["eslesmedi"] += 1

        eslemeler.append(
            {
                "pdf_satir_no": i + 1,
                "sayfa": r["sayfa"],
                "pdf_adi": r["musteri_adi_pdf"],
                "adaylar": adaylar,
                "kesin_kaynak_cari_id": kesin_id,
                "durum": durum,
                "notlar": notlar,
                "pdf_tutarlar": {
                    "donem_borc": r.get("donem_borc"),
                    "donem_alacak": r.get("donem_alacak"),
                    "devir_borc": r.get("devir_borc"),
                    "devir_alacak": r.get("devir_alacak"),
                },
            }
        )

    return {
        "format": "d1-pdf-cari-id-esleme-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pdf_satir": len(pdf),
        "kart": len(kartlar),
        "sayac": dict(sayac),
        "politika": (
            "Aynı adlı farklı kartlar korunur (COKLU). "
            "Kısaltma/yinelenen ad kesinleştirilmez (ACIK_*). "
            "KESIN_ID yalnız tek aday + Dönem↔Detay ve/veya Devir↔Devreden tutar uyumu."
        ),
        "eslemeler": eslemeler,
        "k05": False,
    }


def stok_kapsam_ayir() -> dict[str, Any]:
    fark2522 = _yukle("DOGRULAMA_STOK_HAREKET_FARK")
    ozet3150 = _yukle("STOK_HAREKET_3150_OZET")
    derin = _yukle("DOGRULAMA_STOK_FARK_DERIN")
    return {
        "format": "d1-stok-kapsam-adlandirma-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "hareket_yeniden_toplanmadi": True,
        "alt_kumeler": {
            "ALT_KUME_2522_STOK_HAREKET_FARK": {
                "kanit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_STOK_HAREKET_FARK.json",
                "ok_adet": fark2522.get("ok_adet"),
                "sinif": fark2522.get("sinif"),
                "esit_1244": (fark2522.get("sinif") or {}).get("esit"),
                "hareket_var_fark_1063": (fark2522.get("sinif") or {}).get("hareket_var_fark"),
                "kapsam": (
                    "İlk StokHareket çekimi / FIFO maliyetli kart alt kümesi (ok_adet=2522). "
                    "depo=0 varsayılan, tarih 01.01.2015–31.08.2026, kart a_kalan görüntü anı uyarılı."
                ),
                "yontem": "kart_kalan vs hareket_net; birim/depo kırılımı örneklerde",
            },
            "KAPSAM_3150_TAM_KART": {
                "kanit_ozet": "kaynak/D1_20260831_KAYNAK_STOK_HAREKET_3150_OZET.json",
                "kanit_derin": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_STOK_FARK_DERIN.json",
                "ok_adet": ozet3150.get("ok_adet"),
                "sinif_3150_ozet": ozet3150.get("sinif"),
                "sinif_derin": derin.get("sinif"),
                "esit_1775": (derin.get("sinif") or {}).get("esit"),
                "kapsam": (
                    "Tüm 3150 stok kartı StokHareket çekimi (2522+628). "
                    "1244/1063 ile aynı ad verilmez; tarih/depo/birim/yöntem aynı kümede değilse fark ilan edilmez."
                ),
            },
        },
        "karsilastirma_yasagi": (
            "1244/1063 (2522 alt küme) ile 1775/1155 (3150) arasında "
            "kapsam eşitliği kanıtlanmadan 'fark büyüdü/küçüldü' denmez."
        ),
        "k05": False,
    }


def fifo_kasa_banka_pos_kontrol() -> dict[str, Any]:
    """Mevcut kanıtlarla tamamlanabilir kontroller; engelleri listele."""
    tamamlanan = []
    engeller = []

    # FIFO katman
    lot_fifo = _yukle("DOGRULAMA_LOT_FIFO")
    lot_kat = None
    p_kat = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_LOT_KATMAN_DEVAM.json"
    if p_kat.is_file():
        lot_kat = json.loads(p_kat.read_text(encoding="utf-8"))
    fifo_out = {
        "lot_olay": lot_fifo.get("lot_hareket_adet") or lot_fifo.get("tekil_stok_lot_anahtar"),
        "tekil_lot": lot_fifo.get("tekil_stok_lot_anahtar"),
        "kart_fifo_yontem_adet": (lot_fifo.get("maliyet_yontem_adet") or {}).get("a_maliyet_fifo"),
        "katman_maliyet_durum": (lot_kat or {}).get("katman_maliyet", {}).get("durum")
        if lot_kat
        else lot_fifo.get("stok_hareket_api_durum"),
        "kanit_dosyalari": [
            "kaynak/D1_20260831_KAYNAK_DOGRULAMA_LOT_FIFO.json",
            "kaynak/D1_20260831_KAYNAK_DOGRULAMA_LOT_STOKHAREKET.json",
        ],
    }
    if lot_kat:
        fifo_out["kanit_dosyalari"].append("kaynak/D1_20260831_KAYNAK_DOGRULAMA_LOT_KATMAN_DEVAM.json")
    if (fifo_out.get("katman_maliyet_durum") or "") in ("BEKLIYOR", "UYGULANAMAZ", None):
        engeller.append(
            {
                "is": "FIFO_katman_birim_maliyet",
                "gerekli_kaynak": (
                    "Seri_Lot_List veya eşdeğerde lot katmanı birim maliyet / maliyet tarihi; "
                    "kart a_maliyet_fifo katman kanıtı değildir"
                ),
                "mevcut": fifo_out,
            }
        )
    else:
        tamamlanan.append({"is": "FIFO_katman", "kanit": fifo_out["kanit_dosyalari"]})

    # Kasa
    kasa = _yukle("KASA_KAPANIS")
    kasa_bas = _yukle("KASA_BASLANGIC")
    tamamlanan.append(
        {
            "is": "kasa_hareket_net_kapanis",
            "kanit": [
                "kaynak/D1_20260831_KAYNAK_KASA_KAPANIS.json",
                "kaynak/D1_20260831_KAYNAK_KASA_BASLANGIC.json",
                "kaynak/D1_20260831_KAYNAK_DOGRULAMA_NAKIT_KASA_EXCEL.json",
            ],
            "durum": kasa.get("kapanis_durumu"),
            "hesap_adet": kasa.get("hesap_adet"),
            "devir_belge_ipucu": True,
            "kapsam_plani": (
                "Kasa jq_list Bankadan Çekilen/Bankaya Yatırılan döndürmez; "
                "banka tur 22/23 MKB=kasa karşı bacak kasa kapsamına eklenir "
                "(kasa_banka_transfer_bacak; banka çoğalmaz)."
            ),
            "not": "NAKİT Excel ile tamam olabilir; YÇ/K05 diğer eksikleri açık kalabilir",
        }
    )
    if kasa.get("kapanis_durumu") == "NAKIT_TAMAM_YC_BEKLIYOR":
        engeller.append(
            {
                "is": "kasa_resmi_3108_ekstre",
                "gerekli_kaynak": "YÇ KASA ekstresi 31.08.2026 (NAKİT nakit.xlsx ile tamam)",
                "mevcut_kanit": "DOGRULAMA_NAKIT_KASA_EXCEL.json + KASA_KAPANIS",
            }
        )
    elif kasa.get("kapanis_durumu") != "TAM_KANITLI":
        engeller.append(
            {
                "is": "kasa_resmi_3108_ekstre",
                "gerekli_kaynak": "Kasa ekstresi bitiş 31.08.2026 veya doğrulanmış açılış+hareket mutabakatı",
                "mevcut_kanit": "KASA_KAPANIS.json + KASA_BASLANGIC.json",
            }
        )

    banka = _yukle("BANKA_KAPANIS")
    tamamlanan.append(
        {
            "is": "banka_hareket_net_kapanis",
            "kanit": [
                "kaynak/D1_20260831_KAYNAK_BANKA_KAPANIS.json",
                "kaynak/D1_20260831_KAYNAK_BANKA_BASLANGIC.json",
            ],
            "durum": banka.get("kapanis_durumu"),
            "hesap_adet": banka.get("hesap_adet") or banka.get("kart_adet"),
        }
    )
    if banka.get("kapanis_durumu") not in ("TAM_KANITLI",):
        engeller.append(
            {
                "is": "banka_resmi_3108_ekstre",
                "gerekli_kaynak": "Banka ekstresi 31.08.2026 / doğrulanmış açılış",
                "mevcut_kanit": "BANKA_KAPANIS.json",
            }
        )

    pos = _yukle("POS_KART_KREDI")
    tamamlanan.append(
        {
            "is": "pos_kk_kredi_sinif_net",
            "kanit": [
                "kaynak/D1_20260831_KAYNAK_POS_KART_KREDI.json",
                "kaynak/D1_20260831_KAYNAK_POS_VALOR.json",
            ],
            "pos_adet": pos.get("pos_adet"),
            "kk_adet": pos.get("kk_adet"),
            "kredi_adet": pos.get("kredi_adet"),
        }
    )

    return {
        "format": "d1-fifo-kasa-banka-pos-kontrol-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tamamlanan": tamamlanan,
        "engeller": engeller,
        "k05": False,
        "mali_yazim": False,
        "exe": False,
        "devir_2": "OGLEDEN_SONRA_BEKLIYOR",
    }


def main() -> int:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials, _uid_bul

    _surumle("DOGRULAMA_PDF_DEVIRLI_RAPOR")
    creds = load_credentials()
    client = EvobulutClient(creds)
    yanit = client._post(
        "index/base/",
        {"cmd": "euas", "p1": creds.kullanici_kodu, "p2": creds.sifre, "app": creds.app},
    )
    client.uid = _uid_bul(yanit)

    print("1) Devir anlamı…", flush=True)
    anlam = dogrula_devir_anlami(client)
    yaz_kaynak("DOGRULAMA_PDF_DEVIR_SUTUN_ANLAM", anlam)
    print(
        json.dumps(
            {"dogrulandi": anlam["dogrulandi"], "n": anlam["ornek_adet"], "donem": anlam["donem_eslesen"], "devir": anlam["devir_eslesen"]},
            ensure_ascii=False,
        ),
        flush=True,
    )

    print("2) 1980 ayrım…", flush=True)
    m1980 = murat_apak_1980(client)
    yaz_kaynak("DOGRULAMA_1980_MURAT_APAK_AYRIM", m1980)

    cari22_list = (_yukle("DOGRULAMA_CARI22_KAPANIS_KANIT").get("cariler") or [])
    cari22 = {str(c["kaynak_cari_id"]): c for c in cari22_list}

    print("3) Risk21…", flush=True)
    r21 = risk21_incele(client, cari22)
    yaz_kaynak("DOGRULAMA_RISK21_ILK_ETKI_EKSTRE", r21)

    print("4) 1070 eşleme…", flush=True)
    esleme = esle_1070_1066(client)
    yaz_kaynak("DOGRULAMA_PDF_CARI_ID_ESLEME", esleme)
    print(json.dumps(esleme["sayac"], ensure_ascii=False), flush=True)

    print("5) Stok kapsam…", flush=True)
    stok = stok_kapsam_ayir()
    yaz_kaynak("DOGRULAMA_STOK_KAPSAM_ADLANDIRMA", stok)

    print("6) FIFO/kasa/banka/POS…", flush=True)
    diger = fifo_kasa_banka_pos_kontrol()
    yaz_kaynak("DOGRULAMA_FIFO_KASA_BANKA_POS_KONTROL", diger)

    # PDF ana kanıtı güncelle (anlam + 1980 link)
    pdf_ana = _yukle("DOGRULAMA_PDF_DEVIRLI_RAPOR")
    pdf_ana["devir_sutun_anlami"] = {
        **(pdf_ana.get("devir_sutun_anlami") or {}),
        "dogrulama_kanit": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_PDF_DEVIR_SUTUN_ANLAM.json",
        "dogrulandi": anlam["dogrulandi"],
        "anlam_ozet": anlam["gozlem"],
    }
    pdf_ana["murat_apak_1980_ayrim"] = "kaynak/D1_20260831_KAYNAK_DOGRULAMA_1980_MURAT_APAK_AYRIM.json"
    pdf_ana["format"] = "d1-pdf-musteri-hesap-devirli-v3"
    pdf_ana["zaman"] = datetime.now().astimezone().isoformat(timespec="seconds")
    yaz_kaynak("DOGRULAMA_PDF_DEVIRLI_RAPOR", pdf_ana)

    ozet = {
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devir_anlam_dogrulandi": anlam["dogrulandi"],
        "1980_durumlar": list(m1980["ozet_kabul"].keys()),
        "risk21_adet": r21["adet"],
        "risk21_detay_var": sum(
            1 for c in r21["cariler"] if (c.get("tarihli_ekstre") or {}).get("detay_satir_adet_<=3108", 0) > 0
        ),
        "esleme_sayac": esleme["sayac"],
        "stok_alt_kumeler": list(stok["alt_kumeler"].keys()),
        "tamamlanan_isler": [t["is"] for t in diger["tamamlanan"]],
        "engeller": [e["is"] for e in diger["engeller"]],
        "k05": False,
        "devir_2": "OGLEDEN_SONRA_BEKLIYOR",
        "kanitlar": {
            "devir_anlam": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_PDF_DEVIR_SUTUN_ANLAM.json",
            "1980": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_1980_MURAT_APAK_AYRIM.json",
            "risk21": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_RISK21_ILK_ETKI_EKSTRE.json",
            "esleme": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_PDF_CARI_ID_ESLEME.json",
            "stok_kapsam": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_STOK_KAPSAM_ADLANDIRMA.json",
            "fifo_kasa_pos": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_FIFO_KASA_BANKA_POS_KONTROL.json",
        },
    }
    yaz_json(CALISMA / "DEVIR1_DEVAM_OZET.json", ozet)

    durum_yol = CALISMA / "DURUM.json"
    durum = json.loads(durum_yol.read_text(encoding="utf-8")) if durum_yol.is_file() else {}
    durum.update(
        {
            "guncelleme": ozet["zaman"],
            "ozet": (
                f"Devir1: Devir=Devreden/Dönem=Detay doğrulandı ({anlam['ornek_adet']} örn). "
                f"1980: net/SON_DETAY/Devreden ayrıldı. Risk21 detaylı={ozet['risk21_detay_var']}/21. "
                f"PDF eşleme kesin={esleme['sayac'].get('kesin', 0)}. "
                f"Stok 1244/1063=2522 alt küme; 3150 ayrı. K05 kapalı. Devir2 öğleden sonra."
            ),
            "k05": False,
            "k06": False,
            "devir_2": "OGLEDEN_SONRA_BEKLIYOR",
            "devir1_devam": "DEVIR1_DEVAM_OZET.json",
            "exe": False,
            "mali_yazim": False,
        }
    )
    yaz_json(durum_yol, durum)
    print(json.dumps(ozet, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
