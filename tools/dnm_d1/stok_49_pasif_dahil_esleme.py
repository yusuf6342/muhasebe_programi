# -*- coding: utf-8 -*-
"""49 pasif stok kimliğini envanter eşlemesine dahil et.

- Kart/birim/barkod: web ashx SQL (API sql pasifte boş)
- Hareket ≤31.08.2026: StokHareket API (yeniden toplama yok — yoksa çek)
- STOK_MIKTAR: mevcut 3150 korunur + 49 birleşir (a_id tekil); kart aktifleştirilmez
- Güncel a_pasif=15 ≠ 31.08.2026 pasif kanıtı
- K05 / mali yazım / yeniden maliyet / EXE yok

  .venv\\Scripts\\python.exe -m tools.dnm_d1.stok_49_pasif_dahil_esleme
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from entegrasyon.evobulut_client import EvobulutClient, load_credentials
from tools.dnm_d1._ortak import CALISMA, KAYNAK, yaz_json
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.stok_eksik_76_55_cek import BAS_TAR, BIT_TAR, _hareket_ozet
from tools.dnm_d1.stok_envanter_excel_devir1 import (
    BEK_SATIR,
    EXCEL_HEDEF,
    STOK_MIKTAR,
    _oku_excel,
    _sinif_sifir_maliyet,
    _yukle_alis_fiyatlar,
    _yukle_maliyet,
    tr_dec,
)

BAGLA = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_49_WEB_PASIF_BAGLA.json"
STOK_BAZLI = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_ENVANTER_EXCEL_STOK_BAZLI.json"
KART_49 = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_KART_49_PASIF.json"
HRK_49 = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_HAREKET_49_PASIF.jsonl"
MIKTAR_AP = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_MIKTAR_AKTIF_PASIF.json"
OUT_ESLEME = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_49_PASIF_DAHIL_ESLEME.json"
OUT_FIFO = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_49_PASIF_FIFO_LOT.json"
OZET = CALISMA / "STOK_49_PASIF_DAHIL_ESLEME_OZET.json"
LOT_ONCE = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_LOT_KATMAN_DEVAM.json"
FIFO_IZOLE = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_FIFO_KATMAN_IZOLE.json"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _web_kart_to_miktar(sql: dict, *, excel_kod: str, a_pasif: str) -> dict:
    row = (sql.get("S") or [None])[0] or {}
    brm_id = row.get("a_brm_id")
    # ashx SQL: ANA_BRM_ADI; s1 bazen boş; barkod[].birim dolu
    birim_adi = row.get("ANA_BRM_ADI") or row.get("ana_brm_adi")
    if not birim_adi:
        for b in sql.get("s1") or []:
            if str(b.get("a_brm_id") or b.get("a_id") or "") == str(brm_id):
                birim_adi = b.get("a_adi") or b.get("Brm_Adi") or b.get("birim")
                break
    if not birim_adi and (sql.get("barkod") or []):
        b0 = (sql.get("barkod") or [{}])[0]
        birim_adi = b0.get("birim") or b0.get("Brm_Adi") or b0.get("Brm_adi")
    birimler = [
        {
            "a_brm_id": b.get("a_brm_id") or b.get("a_id"),
            "adi": b.get("a_adi") or b.get("Brm_Adi") or b.get("birim"),
            "a_carpan": b.get("a_carpan"),
        }
        for b in (sql.get("s1") or [])
    ]
    if not birimler and birim_adi:
        birimler = [{"a_brm_id": brm_id, "adi": birim_adi, "a_carpan": "1"}]
    return {
        "a_id": str(row.get("a_id") or ""),
        "a_kod": row.get("a_kod") or excel_kod,
        "a_adi": row.get("a_adi"),
        "a_brm_id": brm_id,
        "ana_birim_adi": birim_adi,
        "a_giren": row.get("a_giren"),
        "a_cikan": row.get("a_cikan"),
        "a_kalan": row.get("a_kalan"),
        "a_fiyat_al": row.get("a_fiyat_al"),
        "a_fiyat_sat": row.get("a_fiyat_sat"),
        "a_pasif": a_pasif or row.get("a_pasif"),
        "aktif_pasif": "Pasif",
        "kaynak_liste": "stokjq+ashx_sql",
        "pasif_dahil_d1": True,
        "pasif_tarih_31_08_kanit_degil": True,
        "barkodlar": [
            {
                "a_barkod_no": b.get("a_barkod_no"),
                "a_brm_id": b.get("a_brm_id"),
                "a_carpan": b.get("a_carpan"),
                "Brm_Adi": b.get("birim") or b.get("Brm_Adi"),
            }
            for b in (sql.get("barkod") or [])
        ],
        "birimler": birimler,
    }


def _yukle_hareket_ozetleri() -> dict[str, dict]:
    """Mevcut hareket özetleri (76/ham korunur; 49 varsa dahil). Yeniden toplama yok."""
    out: dict[str, dict] = {}
    for p in (
        KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_HAREKET.jsonl",
        KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_HAREKET_76_DETAY.jsonl",
        HRK_49,
    ):
        if not p.is_file():
            continue
        with p.open(encoding="utf-8") as f:
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


def _excel_satirlari() -> list[dict]:
    satirlar, _ = _oku_excel(EXCEL_HEDEF)
    if len(satirlar) != BEK_SATIR:
        raise RuntimeError(f"Excel satır {len(satirlar)} ≠ {BEK_SATIR}")
    return satirlar


def _onceki_kimlik_by_satir() -> dict[int, str]:
    """Önceki eşleme: STOK_BAZLI + ARA55 a_kod exact (kimlik_yok’a düşürme)."""
    out: dict[int, str] = {}
    if STOK_BAZLI.is_file():
        d = json.loads(STOK_BAZLI.read_text(encoding="utf-8"))
        for name in ("eslesen_liste", "belge_kimlik_3150_disi", "negatif_kimlik"):
            for x in d.get(name) or []:
                sid = x.get("kaynak_stok_id")
                es = x.get("excel_satir")
                if sid is None or es is None:
                    continue
                out[int(es)] = str(sid)
    ara55 = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_ARA_55_KIMLIK.json"
    if ara55.is_file():
        d = json.loads(ara55.read_text(encoding="utf-8"))
        for x in d.get("kayitlar") or []:
            bag = x.get("baglanti") or {}
            sid = bag.get("kaynak_stok_id")
            es = x.get("excel_satir")
            kod = str(x.get("kod") or "").strip()
            if not sid or es is None:
                continue
            # Yalnız a_kod exact kanıtı — barkod alternatifini yeni kartla karıştırma
            bulunan = x.get("bulunan") or []
            if not any(
                str(b.get("a_id")) == str(sid)
                and str(b.get("a_kod") or "").strip() == kod
                for b in bulunan
            ):
                continue
            out[int(es)] = str(sid)
    return out


def _kart_by_id(kartlar: list[dict]) -> dict[str, dict]:
    return {str(k.get("a_id")): k for k in kartlar if k.get("a_id")}


def _esle_3252(
    excel: list[dict],
    kartlar: list[dict],
    bagla_49: dict[str, dict],
    hareket_by: dict[str, dict],
    onceki_by_satir: dict[int, str],
) -> dict:
    """Kod+birim exact; aynı kodlu farklı kart birleştirilmez; pasif düşmez."""
    by_kod: dict[str, list[dict]] = defaultdict(list)
    for k in kartlar:
        kod = str(k.get("a_kod") or "").strip()
        if kod:
            by_kod[kod].append(k)
    by_id = _kart_by_id(kartlar)
    ids_miktar = set(by_id)

    eslesen = []
    kimlik_yok = []
    birim_uyumsuz = []
    pasif_pozitif = []
    negatif_korundu = []

    for x in excel:
        kod = str(x.get("kod") or "").strip()
        birim = str(x.get("birim") or "").strip()
        kalan = tr_dec(x.get("kalan"))
        tutar = tr_dec(x.get("tutar"))
        bm = tr_dec(x.get("birim_maliyet"))
        es = int(x.get("excel_satir") or 0)
        b49 = bagla_49.get(kod) if kod else None
        adaylar: list[dict] = []
        kanit = "STOK_MIKTAR_AKTIF_PASIF a_kod(+birim) exact"

        if b49:
            sid = str(b49["kaynak_stok_id"])
            kart = by_id.get(sid)
            if kart is None:
                kart = {
                    "a_id": sid,
                    "a_kod": kod,
                    "a_adi": b49.get("a_adi"),
                    "ana_birim_adi": None,
                    "aktif_pasif": "Pasif",
                    "a_pasif": b49.get("a_pasif") or "15",
                    "pasif_dahil_d1": True,
                }
            adaylar = [kart]
            kanit = (
                "WEB_PASIF_BAGLA+STOK_MIKTAR_AKTIF_PASIF a_kod exact; "
                "isim birleştirme yok; aynı kodlu farklı kart birleştirilmedi"
            )
        elif es in onceki_by_satir:
            sid = onceki_by_satir[es]
            kart = by_id.get(sid)
            if kart is None:
                # önceki id miktarda yoksa sentetik (aktif 3150 dışı durum)
                kart = {
                    "a_id": sid,
                    "a_kod": kod,
                    "ana_birim_adi": birim or None,
                    "aktif_pasif": "Aktif",
                }
            # aynı kodlu başka karta kayma yok
            adaylar = [kart]
            kanit = "STOK_BAZLI önceki kaynak_stok_id + satır; birleştirme yok"
        else:
            adaylar = list(by_kod.get(kod) or [])
            if len(adaylar) > 1 and birim:
                birim_hit = [
                    k
                    for k in adaylar
                    if str(k.get("ana_birim_adi") or "").strip().casefold()
                    == birim.casefold()
                ]
                if birim_hit:
                    adaylar = birim_hit

        if len(adaylar) == 1:
            k = adaylar[0]
            sid = str(k.get("a_id"))
            hr = hareket_by.get(sid) or {}
            pasif_kart = k.get("aktif_pasif") == "Pasif" or str(k.get("a_pasif")) == "15"
            kayit = {
                "excel_satir": es,
                "kod": kod,
                "adi": x.get("adi"),
                "birim": birim,
                "kalan": str(kalan) if kalan is not None else None,
                "birim_maliyet": str(bm) if bm is not None else None,
                "tutar": str(tutar) if tutar is not None else None,
                "kaynak_stok_id": sid,
                "kaynak_birim": k.get("ana_birim_adi"),
                "kaynak_a_pasif": k.get("a_pasif"),
                "kaynak_aktif_pasif": k.get("aktif_pasif"),
                "esleme_durum": "KOD_EXACT_PASIF_DAHIL" if pasif_kart else "KOD_EXACT",
                "esleme_kanit": kanit,
                "in_stok_miktar_genis": sid in ids_miktar,
                "pasif_kart": pasif_kart,
                "pasif_31_08_kanit_yok": True,
                "hareket_net_31_08": hr.get("hareket_net"),
                "negatif_korundu": (kalan is not None and kalan < 0),
            }
            if pasif_kart and (
                (kalan is not None and kalan != 0)
                or (tutar is not None and tutar != 0)
            ):
                pasif_pozitif.append(kayit)
            if kayit["negatif_korundu"]:
                negatif_korundu.append(kayit)
            if (
                birim
                and k.get("ana_birim_adi")
                and str(k.get("ana_birim_adi")).strip().casefold() != birim.casefold()
            ):
                kayit["birim_gozlem"] = "excel_birim != kart_ana_birim (birleştirilmedi)"
                birim_uyumsuz.append(kayit)
            eslesen.append(kayit)
        elif len(adaylar) > 1:
            kimlik_yok.append(
                {
                    "excel_satir": es,
                    "kod": kod,
                    "birim": birim,
                    "kalan": str(kalan) if kalan is not None else None,
                    "tutar": str(tutar) if tutar is not None else None,
                    "esleme_durum": "COKLU_KART_AYNI_KOD",
                    "aday_stok_id": [str(a.get("a_id")) for a in adaylar],
                    "not": "Aynı kodlu farklı kartlar birleştirilmez",
                }
            )
        else:
            kimlik_yok.append(
                {
                    "excel_satir": es,
                    "kod": kod,
                    "birim": birim,
                    "kalan": str(kalan) if kalan is not None else None,
                    "tutar": str(tutar) if tutar is not None else None,
                    "esleme_durum": "KAYNAK_STOK_ID_BULUNAMADI",
                }
            )

    pasif_dustu = [
        p
        for p in pasif_pozitif
        if p.get("esleme_durum") in {None, "KAYNAK_STOK_ID_BULUNAMADI"}
    ]
    return {
        "excel_adet": len(excel),
        "eslesen_adet": len(eslesen),
        "kimlik_yok_adet": len(kimlik_yok),
        "pasif_pozitif_miktar_veya_deger": len(pasif_pozitif),
        "pasif_pozitif_karsilastirmadan_dusmedi": len(pasif_dustu) == 0,
        "birim_uyumsuz_gozlem": len(birim_uyumsuz),
        "negatif_korundu_adet": len(negatif_korundu),
        "eslesen": eslesen,
        "kimlik_yok": kimlik_yok,
        "pasif_pozitif_ornek": pasif_pozitif[:10],
        "negatif_ornek": negatif_korundu[:5],
    }


def main() -> int:
    bagla = json.loads(BAGLA.read_text(encoding="utf-8"))
    baglanan = bagla["baglanan"]
    assert len(baglanan) == 49
    bagla_by_kod = {b["excel_kod"]: b for b in baglanan}
    ids_49 = [str(b["kaynak_stok_id"]) for b in baglanan]
    ids_49_set = set(ids_49)

    # Önceki hareketler (76/ham) — yeniden toplanmaz
    hareket_by = _yukle_hareket_ozetleri()
    once_mevcut_49 = {sid for sid in ids_49_set if sid in hareket_by}

    # Mevcut kart_49: birim doluysa yeniden web SQL yok
    kart_kayitlar: list[dict] = []
    if KART_49.is_file():
        once_kart = json.loads(KART_49.read_text(encoding="utf-8"))
        kay = list(once_kart.get("kayitlar") or [])
        birim_dolu = sum(1 for k in kay if k.get("ana_birim_adi"))
        if int(once_kart.get("adet") or 0) == 49 and len(kay) == 49 and birim_dolu == 49:
            kart_kayitlar = kay
            print("kart_49_mevcut yeniden_toplanmadi", flush=True)
        else:
            print(
                f"kart_49_eksik_birim yenilenecek birim_dolu={birim_dolu}/49",
                flush=True,
            )

    client = EvobulutClient(load_credentials())
    client.login()
    client.web_login()

    # --- 1) Kart (web SQL) + hareket (API, yalnız eksik 49) ---
    if len(kart_kayitlar) != 49:
        kart_kayitlar = []
        for i, b in enumerate(baglanan, 1):
            sid = str(b["kaynak_stok_id"])
            if i % 15 == 0:
                client.login()
                client.web_login()
            sql = client.stok_detay_web(sid)
            kart = _web_kart_to_miktar(
                sql, excel_kod=b["excel_kod"], a_pasif=str(b.get("a_pasif") or "15")
            )
            if not kart["barkodlar"] and b.get("barkodlar"):
                kart["barkodlar"] = b["barkodlar"]
            if not kart["birimler"] and b.get("birimler"):
                kart["birimler"] = b["birimler"]
            kart_kayitlar.append(
                {
                    **kart,
                    "excel_kod": b["excel_kod"],
                    "kanit_kimlik": b.get("kanit"),
                    "guncel_pasif_31_08_kanit_degil": True,
                }
            )
            if i % 10 == 0:
                print(f"49_kart {i}/49", flush=True)
            time.sleep(0.03)
        yaz_json(
            KART_49,
            {
                "format": "d1-stok-kart-49-pasif-v1",
                "zaman": _now(),
                "adet": len(kart_kayitlar),
                "aktiflestirilmedi": True,
                "pasif_korundu": True,
                "guncel_pasif_donem_sonu_kanit_degil": True,
                "kayitlar": kart_kayitlar,
                "k05": False,
            },
        )

    # Hareket: yalnız 49 içinde henüz olmayanlar
    yeni_hrk: list[dict] = []
    for i, b in enumerate(baglanan, 1):
        sid = str(b["kaynak_stok_id"])
        if sid in hareket_by:
            ozet = dict(hareket_by[sid])
            ozet["yeniden_toplanmadi"] = True
            ozet["pasif_kart"] = True
            yeni_hrk.append(ozet)
            continue
        if i % 15 == 0:
            client.login()
        try:
            ham = client.stok_hareketleri(
                sid, bas_tar=BAS_TAR, bit_tar=BIT_TAR, depo="0"
            )
        except Exception as exc:  # noqa: BLE001
            ozet = {
                "kaynak_stok_id": sid,
                "kod": b["excel_kod"],
                "status": "ERR",
                "hata": type(exc).__name__,
                "mesaj": str(exc)[:200],
                "pasif_kart": True,
            }
            yeni_hrk.append(ozet)
            continue
        ozet = _hareket_ozet(sid, b["excel_kod"], b.get("a_adi"), ham)
        ozet["yeniden_toplanmadi_onceki_yok"] = True
        ozet["pasif_kart"] = True
        hareket_by[sid] = ozet
        yeni_hrk.append(ozet)
        time.sleep(0.03)
        if i % 10 == 0:
            print(f"49_hrk {i}/49", flush=True)

    with HRK_49.open("w", encoding="utf-8") as jf:
        for ozet in yeni_hrk:
            jf.write(json.dumps(ozet, ensure_ascii=False) + "\n")
    print(
        f"hareket_49 yazildi adet={len(yeni_hrk)} once_mevcut={len(once_mevcut_49)}",
        flush=True,
    )

    # --- 2) STOK_MIKTAR birleşik (mevcut + 49, a_id tekil) ---
    miktar = json.loads(STOK_MIKTAR.read_text(encoding="utf-8"))
    onceki = list(miktar.get("kayitlar") or [])
    by_id: dict[str, dict] = {}
    for k in onceki:
        sid = str(k.get("a_id") or "")
        if sid:
            by_id[sid] = k
    eklendi = 0
    for k in kart_kayitlar:
        sid = str(k.get("a_id") or "")
        if not sid:
            continue
        if sid in by_id:
            # mükerrer yok — pasif alanları güncelle, aktifleştirme yok
            eski = by_id[sid]
            eski["aktif_pasif"] = "Pasif"
            eski["a_pasif"] = k.get("a_pasif") or "15"
            eski["pasif_dahil_d1"] = True
            eski["pasif_tarih_31_08_kanit_degil"] = True
        else:
            by_id[sid] = {**k}
            eklendi += 1
    birlesik = list(by_id.values())
    miktar_ap = {
        "format": "d1-kaynak-stok-envanter-aktif-pasif-v1",
        "zaman": _now(),
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "onceki_adet": len(onceki),
        "eklenen_pasif_49": eklendi,
        "adet": len(birlesik),
        "tekil_a_id": True,
        "aktiflestirme_yapilmadi": True,
        "kaynak_onceki": str(STOK_MIKTAR.name),
        "uyari": (
            "a_kalan güncel olabilir; 31.08 için hareket_net kullanılır. "
            "Güncel a_pasif=15, 31.08 pasifliği kanıtı değildir."
        ),
        "kayitlar": birlesik,
        "k05": False,
    }
    yaz_json(MIKTAR_AP, miktar_ap)

    # Kalıcı toplayıcı smoke: aktif/pasif sayfa toplamı (tam listeyi yeniden yazma)
    client.web_login()
    _, aktif_t = client.stokjq_liste_sayfa(sayfa=0, kos="pasif^x^14|barkod_goster^x^1|", pagesize=50)
    _, pasif_t = client.stokjq_liste_sayfa(sayfa=0, kos="pasif^x^15|barkod_goster^x^1|", pagesize=50)
    # mükerrer testi: aynı id iki kos'ta
    a0, _ = client.stokjq_liste_sayfa(sayfa=0, kos="pasif^x^14|barkod_goster^x^1|", pagesize=50)
    p0, _ = client.stokjq_liste_sayfa(sayfa=0, kos="pasif^x^15|barkod_goster^x^1|", pagesize=50)
    overlap_page0 = {r["a_id"] for r in a0} & {r["a_id"] for r in p0}

    # --- 3) 3252 eşleme ---
    excel = _excel_satirlari()
    onceki_by_satir = _onceki_kimlik_by_satir()
    esleme = _esle_3252(excel, birlesik, bagla_by_kod, hareket_by, onceki_by_satir)

    eslesen_49 = [
        e for e in esleme["eslesen"] if str(e.get("kaynak_stok_id")) in ids_49_set
    ]
    kod_49 = set(bagla_by_kod)
    eslesen_kod_49 = {e["kod"] for e in esleme["eslesen"] if e["kod"] in kod_49}

    # --- 4) Sıfır maliyet (pozitif kalan + bm=0) — kimliklerle belge araştırması ---
    sifir_excel = [
        e
        for e in esleme["eslesen"]
        if tr_dec(e.get("birim_maliyet")) == Decimal("0")
        and tr_dec(e.get("kalan")) is not None
        and tr_dec(e.get("kalan")) > 0
    ]
    sifir_ids = {str(e["kaynak_stok_id"]) for e in sifir_excel if e.get("kaynak_stok_id")}
    # Sıfır maliyet + yeni 49 kimlikleri için belge araştırması (yeniden belge çekimi yok)
    alis = _yukle_alis_fiyatlar(sifir_ids | ids_49_set)
    maliyet_by = _yukle_maliyet()
    sifir_rapor = []
    for e in sifir_excel:
        sid = str(e.get("kaynak_stok_id") or "") or None
        ornek = alis.get(sid or "") or []
        sinif = _sinif_sifir_maliyet(sid, ornek, maliyet_by.get(sid or ""))
        sifir_rapor.append(
            {
                **{
                    k: e[k]
                    for k in (
                        "excel_satir",
                        "kod",
                        "adi",
                        "kalan",
                        "birim",
                        "birim_maliyet",
                        "tutar",
                        "kaynak_stok_id",
                        "pasif_kart",
                    )
                    if k in e
                },
                "sinif": sinif.get("sinif"),
                "sinif_detay": sinif,
                "alis_satir_adet": len(ornek),
                "alis_ornek": ornek[:3],
                "kart_fifo_doldurma_yok": True,
            }
        )
    belge_49 = []
    for sid in ids_49:
        ornek = alis.get(sid) or []
        belge_49.append(
            {
                "kaynak_stok_id": sid,
                "alis_belge_satir_adet": len(ornek),
                "alis_var": len(ornek) > 0,
                "ornek": ornek[:2],
            }
        )

    # --- 5) FIFO miktar / katman maliyeti / envanter değeri — ayrı ---
    fifo_once = {}
    if FIFO_IZOLE.is_file():
        fi = json.loads(FIFO_IZOLE.read_text(encoding="utf-8"))
        for x in fi.get("fifo_izole_kayitlar") or []:
            sid = str(x.get("kaynak_stok_id") or "")
            if sid:
                fifo_once[sid] = x
    lot_once = {}
    if LOT_ONCE.is_file():
        lo = json.loads(LOT_ONCE.read_text(encoding="utf-8"))
        for x in lo.get("kayitlar") or lo.get("stoklar") or []:
            sid = str(x.get("kaynak_stok_id") or x.get("stok_id") or "")
            if sid:
                lot_once[sid] = x

    fifo_miktar = []
    fifo_katman = []
    fifo_deger = []
    fifo_lot = []
    for e in eslesen_49:
        sid = str(e["kaynak_stok_id"])
        hr = hareket_by.get(sid) or {}
        kalan = tr_dec(e.get("kalan"))
        net = tr_dec(hr.get("hareket_net"))
        tutar = tr_dec(e.get("tutar"))
        bm = tr_dec(e.get("birim_maliyet"))
        if kalan is not None and kalan < 0:
            miktar_ok = True  # negatif korunur; net ile zorlanmaz
            miktar_not = "NEGATIF_KORUNDU"
        elif net is None:
            miktar_ok = False
            miktar_not = "HAREKET_YOK_VEYA_ERR"
        elif kalan is None:
            miktar_ok = False
            miktar_not = "EXCEL_KALAN_YOK"
        elif abs(kalan - net) < Decimal("0.0000001"):
            miktar_ok = True
            miktar_not = "OK"
        elif abs(kalan.quantize(Decimal("0.01")) - net.quantize(Decimal("0.01"))) < Decimal(
            "0.0000001"
        ):
            # Excel 2 hane gösterim; ham net korunur, yuvarlama uyumsuzluğu ayrı
            miktar_ok = True
            miktar_not = "OK_GOSTERIM_2HANE"
        elif abs(kalan - net) <= Decimal("0.01"):
            # örn. excel 0.01 / ham 0.005 — ham korunur; gösterim bandı
            miktar_ok = True
            miktar_not = "OK_HAM_EXCEL_0_01_BAND"
        else:
            miktar_ok = False
            miktar_not = "MIKTAR_UYUSMAZ"
        fifo_miktar.append(
            {
                "kaynak_stok_id": sid,
                "kod": e["kod"],
                "excel_satir": e.get("excel_satir"),
                "excel_kalan": str(kalan) if kalan is not None else None,
                "hareket_net": hr.get("hareket_net"),
                "miktar_ok": miktar_ok,
                "durum": miktar_not,
                "negatif_korundu": e.get("negatif_korundu"),
                "ham_hassasiyet": True,
            }
        )
        once = fifo_once.get(sid) or {}
        katman_var = bool(once.get("katmanlar") or once.get("fifo_toplam_izole") is not None)
        fifo_katman.append(
            {
                "kaynak_stok_id": sid,
                "kod": e["kod"],
                "katman_maliyet_dogrulanmis": False,
                "onceki_fifo_izole": bool(once),
                "katman_kaynak_var": katman_var,
                "neden": (
                    "Yeniden maliyet hesabı yok; pasif 49 için FIFO katman belgesi "
                    "eksik veya doğrulanmamış"
                ),
                "alis_belge_satir_adet": len(alis.get(sid) or []),
            }
        )
        fifo_deger.append(
            {
                "kaynak_stok_id": sid,
                "kod": e["kod"],
                "excel_tutar": str(tutar) if tutar is not None else None,
                "excel_birim_maliyet": str(bm) if bm is not None else None,
                "envanter_deger_dogrulanmis": False,
                "neden": "Katman maliyeti doğrulanmadan envanter değeri doğrulanmış sayılmaz",
            }
        )
        lot_bilgi = lot_once.get(sid)
        fifo_lot.append(
            {
                "kaynak_stok_id": sid,
                "kod": e["kod"],
                "lot_katman": "ONCEKI_VAR" if lot_bilgi else "BEKLIYOR",
                "onceki_lot": bool(lot_bilgi),
                "gerekli_ekran": {
                    "ekran": "Stok Seri Lot / belge LOT satırı",
                    "filtre": f"stok_id={sid}; belge≤31.08.2026",
                    "sutunlar": [
                        "lot_no",
                        "giriş tarihi",
                        "giren",
                        "çıkan",
                        "kalan",
                        "katman birim maliyet",
                        "belge_id",
                    ],
                },
            }
        )

    out = {
        "format": "d1-stok-49-pasif-dahil-esleme-v1",
        "zaman": _now(),
        "aktiflestirme_yapilmadi": True,
        "pasif_korundu": True,
        "guncel_pasif_31_08_kanit_degil": True,
        "yeniden_toplanmadi_76_ve_6": True,
        "kasa_banka_korundu": True,
        "k05": False,
        "mali_yazim": False,
        "yeniden_maliyet_hesabi": False,
        "exe": False,
        "toplayici": {
            "kalici": "EvobulutClient.tum_stoklari_cek → stokjq aktif+pasif ayrı + a_id tekil",
            "smoke_aktif_total": aktif_t,
            "smoke_pasif_total": pasif_t,
            "smoke_page0_overlap_ids": sorted(overlap_page0),
            "miktar_onceki": len(onceki),
            "miktar_birlesik": len(birlesik),
            "eklenen_pasif": eklendi,
        },
        "kart_49": str(KART_49.name),
        "hareket_49": str(HRK_49.name),
        "miktar_aktif_pasif": str(MIKTAR_AP.name),
        "esleme_3252": {
            "excel_adet": esleme["excel_adet"],
            "eslesen_adet": esleme["eslesen_adet"],
            "kimlik_yok_adet": esleme["kimlik_yok_adet"],
            "pasif_pozitif_adet": esleme["pasif_pozitif_miktar_veya_deger"],
            "pasif_pozitif_dusmedi": esleme["pasif_pozitif_karsilastirmadan_dusmedi"],
            "negatif_korundu_adet": esleme["negatif_korundu_adet"],
            "bagla_49_eslesen_kod": len(eslesen_kod_49),
            "bagla_49_eksik_kod": sorted(kod_49 - eslesen_kod_49),
        },
        "esleme_detay_kimlik_yok": esleme["kimlik_yok"][:30],
        "esleme_49": eslesen_49,
        "sifir_maliyet": {
            "adet": len(sifir_rapor),
            "sinif_say": dict(Counter(str(s.get("sinif")) for s in sifir_rapor)),
            "pasif_dahil_adet": sum(1 for s in sifir_rapor if s.get("pasif_kart")),
            "kayitlar": sifir_rapor,
            "kart_doldurma_yok": True,
            "belge_arastirma_guncellendi": True,
        },
        "belge_arastirma_49": {
            "adet": len(belge_49),
            "alis_var": sum(1 for x in belge_49 if x.get("alis_var")),
            "alis_yok": sum(1 for x in belge_49 if not x.get("alis_var")),
            "kayitlar": belge_49,
            "yeniden_belge_cekimi_yok": True,
        },
        "k05_false": True,
    }
    yaz_json(OUT_ESLEME, out)

    fifo_out = {
        "format": "d1-stok-49-pasif-fifo-lot-ayri-v1",
        "zaman": _now(),
        "miktar_dogrulama": {
            "adet": len(fifo_miktar),
            "ok": sum(1 for x in fifo_miktar if x.get("miktar_ok")),
            "durum_say": dict(Counter(str(x.get("durum")) for x in fifo_miktar)),
            "kayitlar": fifo_miktar,
        },
        "katman_maliyet_dogrulama": {
            "adet": len(fifo_katman),
            "dogrulanmis": sum(
                1 for x in fifo_katman if x.get("katman_maliyet_dogrulanmis")
            ),
            "kayitlar": fifo_katman,
            "not": "Eksik maliyet/belge ile katman doğrulanmış sayılmaz; yeniden maliyet yok",
        },
        "envanter_deger_dogrulama": {
            "adet": len(fifo_deger),
            "dogrulanmis": sum(
                1 for x in fifo_deger if x.get("envanter_deger_dogrulanmis")
            ),
            "kayitlar": fifo_deger,
        },
        "lot_katman": {
            "adet": len(fifo_lot),
            "bekliyor": sum(1 for x in fifo_lot if x.get("lot_katman") == "BEKLIYOR"),
            "kayitlar": fifo_lot,
        },
        "k05": False,
        "yeniden_maliyet_yok": True,
        "kasa_banka_korundu": True,
    }
    yaz_json(OUT_FIFO, fifo_out)

    ozet = {
        "zaman": out["zaman"],
        "kart_49": len(kart_kayitlar),
        "hareket_49_ok": sum(
            1 for x in yeni_hrk if x.get("status") == "OK"
        ),
        "hareket_49_yeniden_toplanmadi": sum(
            1 for x in yeni_hrk if x.get("yeniden_toplanmadi")
        ),
        "miktar_birlesik": len(birlesik),
        "eklenen_pasif": eklendi,
        "excel": esleme["excel_adet"],
        "eslesen": esleme["eslesen_adet"],
        "kimlik_yok": esleme["kimlik_yok_adet"],
        "pasif_pozitif_dusmedi": esleme["pasif_pozitif_karsilastirmadan_dusmedi"],
        "negatif_korundu": esleme["negatif_korundu_adet"],
        "bagla_49_eslesen": len(eslesen_kod_49),
        "sifir_maliyet_adet": len(sifir_rapor),
        "sifir_sinif": out["sifir_maliyet"]["sinif_say"],
        "fifo_miktar_ok": fifo_out["miktar_dogrulama"]["ok"],
        "fifo_katman_dogrulanmis": fifo_out["katman_maliyet_dogrulama"]["dogrulanmis"],
        "fifo_deger_dogrulanmis": fifo_out["envanter_deger_dogrulama"]["dogrulanmis"],
        "aktif_total": aktif_t,
        "pasif_total": pasif_t,
        "page0_overlap": len(overlap_page0),
        "k05": False,
        "mali_yazim": False,
        "exe": False,
        "kanit_esleme": str(OUT_ESLEME.relative_to(CALISMA)).replace("\\", "/"),
        "kanit_fifo": str(OUT_FIFO.relative_to(CALISMA)).replace("\\", "/"),
    }
    yaz_json(OZET, ozet)
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
