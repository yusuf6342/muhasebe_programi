"""6 Excel satırının önceki kaynak kimliğini eşlemeye taşı.

Önceki tur: STOK_ARA_55 jq_list ara= + a_kod exact → id 8/14/17/14727–29.
Pasif-dahil eşleme yalnız STOK_BAZLI kimlik_yok listesine bakınca bunları
yeniden «bulunamadı» saydı. Barkod/birim alternatifini yeni kartla karıştırmaz.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.stok_6_onceki_kimlik_tasi
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from tools.dnm_d1._ortak import CALISMA, KAYNAK, yaz_json
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.stok_49_pasif_dahil_esleme import (
    MIKTAR_AP,
    OUT_ESLEME,
    OUT_FIFO,
    _esle_3252,
    _excel_satirlari,
    _onceki_kimlik_by_satir,
    _yukle_hareket_ozetleri,
)
from tools.dnm_d1.stok_envanter_excel_devir1 import (
    STOK_MIKTAR,
    _sinif_sifir_maliyet,
    _yukle_alis_fiyatlar,
    _yukle_maliyet,
    tr_dec,
)

ARA55 = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_ARA_55_KIMLIK.json"
B55 = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_55_BARKOD_FIFO_DEVAM.json"
BAGLA49 = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_49_WEB_PASIF_BAGLA.json"
HRK76 = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_HAREKET_76_DETAY.jsonl"
OUT = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_3252_HESAPLANABILIR.json"
OUT_UZ = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_MIKTAR_KAPSAM_UZLASTIR.json"
OZET = CALISMA / "STOK_3252_HESAPLANABILIR_OZET.json"

# Bilinen 6 — ara55/hareket kanıtı (yeniden «yok» sayılmaz)
ALTI_BEKLENEN = {
    "2406720255467": "8",
    "3406718340579": "14",
    "2406718486279": "17",
    "2611061814512": "14727",
    "2611061816080": "14728",
    "2611071125554": "14729",
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _ara55_kesin() -> dict[str, dict]:
    """kod → {kaynak_stok_id, birim, kart, kanit} — yalnız a_kod exact."""
    out: dict[str, dict] = {}
    if not ARA55.is_file():
        return out
    d = json.loads(ARA55.read_text(encoding="utf-8"))
    for r in d.get("kayitlar") or []:
        kod = str(r.get("kod") or "").strip()
        bag = r.get("baglanti") or {}
        sid = bag.get("kaynak_stok_id")
        if not kod or not sid:
            continue
        bulunan = r.get("bulunan") or []
        kart = None
        for b in bulunan:
            if str(b.get("a_id")) == str(sid) and str(b.get("a_kod") or "").strip() == kod:
                kart = b
                break
        if kart is None and len(bulunan) == 1 and str(bulunan[0].get("a_kod") or "").strip() == kod:
            kart = bulunan[0]
        if kart is None:
            continue  # alternatif barkod/isim ile bağlama yok
        out[kod] = {
            "excel_satir": r.get("excel_satir"),
            "kod": kod,
            "kaynak_stok_id": str(sid),
            "birim": r.get("birim") or kart.get("ana_birim_adi"),
            "adi": r.get("adi") or kart.get("a_adi"),
            "kart": {
                "a_id": str(kart.get("a_id")),
                "a_kod": kart.get("a_kod"),
                "a_adi": kart.get("a_adi"),
                "ana_birim_adi": kart.get("ana_birim_adi"),
                "a_brm_id": kart.get("a_brm_id"),
                "a_kalan": kart.get("a_kalan"),
                "a_giren": kart.get("a_giren"),
                "a_cikan": kart.get("a_cikan"),
                "aktif_pasif": kart.get("aktif_pasif") or "Aktif",
                "kaynak_liste": "jq_list_ara_a_kod_exact",
                "ara55_tasindi": True,
            },
            "kanit": bag.get("kanit") or "stok/base jq_list ara= + a_kod exact",
            "kesin": bool(bag.get("kesin")),
            "barkod_alternatif_kullanilmadi": True,
            "yeni_kart_uretilmedi": True,
        }
    return out


def _onceki_genis() -> dict[int, str]:
    """excel_satir → id: BAZLI + ARA55 + 49 bagla + 76 hareket kod."""
    by = dict(_onceki_kimlik_by_satir())
    ara = _ara55_kesin()
    excel = {int(x["excel_satir"]): x for x in _excel_satirlari()}
    for kod, info in ara.items():
        es = info.get("excel_satir")
        if es is None:
            # kod ile excel satır bul
            for sat, row in excel.items():
                if row.get("kod") == kod:
                    es = sat
                    break
        if es is not None:
            by[int(es)] = str(info["kaynak_stok_id"])
    if BAGLA49.is_file():
        bag = json.loads(BAGLA49.read_text(encoding="utf-8"))
        for b in bag.get("baglanan") or []:
            kod = b.get("excel_kod")
            sid = b.get("kaynak_stok_id")
            if not kod or not sid:
                continue
            for sat, row in excel.items():
                if row.get("kod") == kod:
                    by[int(sat)] = str(sid)
    # 76 detay: kod → id (satır eşlemesi)
    if HRK76.is_file():
        with HRK76.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                o = json.loads(line)
                if o.get("status") != "OK":
                    continue
                kod = str(o.get("kod") or "").strip()
                sid = str(o.get("kaynak_stok_id") or "")
                if not kod or not sid:
                    continue
                for sat, row in excel.items():
                    if row.get("kod") == kod and int(sat) not in by:
                        by[int(sat)] = sid
    return by


def _miktar_birlesik_guncelle(ara: dict[str, dict]) -> dict[str, Any]:
    """3199 üzerine ara55 aktif 6 ekle (a_id tekil; aktifleştirme yok)."""
    if MIKTAR_AP.is_file():
        miktar = json.loads(MIKTAR_AP.read_text(encoding="utf-8"))
    else:
        miktar = json.loads(STOK_MIKTAR.read_text(encoding="utf-8"))
    by_id: dict[str, dict] = {}
    for k in miktar.get("kayitlar") or []:
        sid = str(k.get("a_id") or "")
        if sid:
            by_id[sid] = k
    onceki = len(by_id)
    eklendi = []
    for info in ara.values():
        kart = dict(info["kart"])
        sid = str(kart["a_id"])
        if sid in by_id:
            # mükerrer yok — yalnız eksik alan tamamla
            eski = by_id[sid]
            for key, val in kart.items():
                if eski.get(key) in (None, "") and val not in (None, ""):
                    eski[key] = val
            eski["ara55_tasindi"] = True
        else:
            by_id[sid] = kart
            eklendi.append(sid)
    kayitlar = list(by_id.values())
    out = {
        "format": "d1-kaynak-stok-envanter-aktif-pasif-v1",
        "zaman": _now(),
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "onceki_adet": onceki,
        "eklenen_ara55_aktif": len(eklendi),
        "eklenen_ids": eklendi,
        "adet": len(kayitlar),
        "tekil_a_id": True,
        "aktiflestirme_yapilmadi": True,
        "uyari": (
            "a_kalan güncel olabilir; 31.08 için hareket_net kullanılır. "
            "Güncel a_pasif, 31.08 pasifliği kanıtı değildir."
        ),
        "kayitlar": kayitlar,
        "k05": False,
    }
    yaz_json(MIKTAR_AP, out)
    return out


def _kapsam_uzlastir(miktar_adet: int) -> dict[str, Any]:
    """3199/3205 vs smoke 3141+113 — sayfa0 TotalRows ≠ tam tekil toplama."""
    once = {}
    if OUT_ESLEME.is_file():
        once = json.loads(OUT_ESLEME.read_text(encoding="utf-8"))
    toplayici = once.get("toplayici") or {}
    aktif_t = toplayici.get("smoke_aktif_total")
    pasif_t = toplayici.get("smoke_pasif_total")
    smoke_toplam = None
    if aktif_t is not None and pasif_t is not None:
        smoke_toplam = int(aktif_t) + int(pasif_t)
    return {
        "format": "d1-stok-miktar-kapsam-uzlastir-v1",
        "zaman": _now(),
        "birlesik_miktar_tekil_a_id": miktar_adet,
        "kaynak_onceki_3150": 3150,
        "eklenen_pasif_49": 49,
        "eklenen_ara55_aktif_beklenen": 6,
        "smoke_page0": {
            "aktif_total_rows": aktif_t,
            "pasif_total_rows": pasif_t,
            "toplam_total_rows": smoke_toplam,
            "page0_overlap_ids": toplayici.get("smoke_page0_overlap_ids") or [],
            "tam_toplama_degil": True,
            "aciklama": (
                "stokjq sayfa=0 TotalRows; tam sayfalama + a_id tekilleştirme değildir. "
                "İlk sayfa kontrolü tam veri toplama kabul edilmez."
            ),
        },
        "fark_analizi": {
            "smoke_eksi_birlesik": (
                (smoke_toplam - miktar_adet) if smoke_toplam is not None else None
            ),
            "olasi_nedenler": [
                "TotalRows ile tekil a_id farkı (filtre/çakışma/silinmiş)",
                "3150 jq_list dump’ı ara= ile bulunan aktif kartları kaçırmış olabilir",
                "Tam tum_stoklari_cek_aktif_pasif henüz birleşik dosyaya yazılmadı",
            ],
        },
        "gerekli_canli": (
            "Web oturumu + EvobulutClient.tum_stoklari_cek_aktif_pasif tam sayfalama; "
            "meta aktif_unique/pasif_unique/tekil_adet + alınma zamanı kaydı"
        ),
        "k05": False,
    }


def _fifo_49_aciklar(eslesen_49: list[dict], hareket_by: dict, alis: dict) -> dict:
    fifo_once = json.loads(OUT_FIFO.read_text(encoding="utf-8")) if OUT_FIFO.is_file() else {}
    miktar = fifo_once.get("miktar_dogrulama") or {}
    katman = []
    lot = []
    deger = []
    for e in eslesen_49:
        sid = str(e["kaynak_stok_id"])
        hr = hareket_by.get(sid) or {}
        alis_sat = alis.get(sid) or []
        giris_belge = []
        for s in hr.get("satirlar") or []:
            if tr_dec(s.get("gir_miktar") or 0) and tr_dec(s.get("gir_miktar")) > 0:
                giris_belge.append(
                    {
                        "tarih": s.get("tarih"),
                        "belge_tur": s.get("belge_tur"),
                        "Fat_id": s.get("Fat_id"),
                        "gir_miktar": s.get("gir_miktar"),
                        "gir_fiyat": s.get("gir_fiyat"),
                    }
                )
        alis_yok = len(alis_sat) == 0
        acilis_aday = [
            g
            for g in giris_belge
            if str(g.get("belge_tur") or "").lower().find("giriş") >= 0
            or str(g.get("Fat_id") or "") in ("0", "")
        ]
        katman.append(
            {
                "kaynak_stok_id": sid,
                "kod": e.get("kod"),
                "excel_satir": e.get("excel_satir"),
                "katman_maliyet_dogrulanmis": False,
                "alis_belge_satir_adet": len(alis_sat),
                "hareket_giris_adet": len(giris_belge),
                "eksik": (
                    "ALIS_BELGE_SATIR_YOK"
                    if alis_yok
                    else "FIFO_KATMAN_HESABI_YAPILMADI_YENIDEN_MALIYET_YOK"
                ),
                "bulunamayan_alis_acilis": {
                    "alis_belge_satir": "YOK" if alis_yok else "VAR",
                    "hareket_giris_ornek": giris_belge[:3],
                    "acilis_fiş_aday_adet": len(acilis_aday),
                    "aciklama": (
                        "Mevcut BELGE_SATIR’da bu stok_id için alış (tur 30/32/34/36) yok. "
                        "Hareket giriş fişleri katman adayı olabilir; maliyet doğrulaması "
                        "yeniden maliyet hesabı olmadan kabul edilmez."
                        if alis_yok
                        else "Alış satırı var; FIFO katman dağılımı henüz üretilmedi."
                    ),
                },
            }
        )
        deger.append(
            {
                "kaynak_stok_id": sid,
                "kod": e.get("kod"),
                "excel_tutar": e.get("tutar"),
                "excel_birim_maliyet": e.get("birim_maliyet"),
                "envanter_deger_dogrulanmis": False,
                "neden": "Katman maliyeti yok → envanter değeri doğrulanmış sayılmaz",
            }
        )
        lot.append(
            {
                "kaynak_stok_id": sid,
                "kod": e.get("kod"),
                "lot_katman": "BEKLIYOR",
                "eksik": "SERI_LOT_LIST_VEYA_BELGE_LOT_SATIR",
                "gerekli_ekran": {
                    "ekran": "Stok Seri Lot / belge LOT satırı",
                    "filtre": f"stok_id={sid}; belge≤31.08.2026",
                },
            }
        )
    return {
        "format": "d1-stok-49-pasif-fifo-lot-ayri-v1",
        "zaman": _now(),
        "miktar_dogrulama": miktar
        or {
            "adet": len(eslesen_49),
            "ok": len(eslesen_49),
            "kayitlar": [],
            "korundu": True,
        },
        "katman_maliyet_dogrulama": {
            "adet": len(katman),
            "dogrulanmis": 0,
            "alis_yok": sum(
                1
                for x in katman
                if x["eksik"] == "ALIS_BELGE_SATIR_YOK"
            ),
            "kayitlar": katman,
        },
        "envanter_deger_dogrulama": {
            "adet": len(deger),
            "dogrulanmis": 0,
            "kayitlar": deger,
        },
        "lot_katman": {
            "adet": len(lot),
            "bekliyor": len(lot),
            "kayitlar": lot,
        },
        "karsilastirma_esasi": {
            "envanter_tarihi": "2026-08-31",
            "maliyet_yontemi": "FIFO",
            "kullanici_teyitli_tamamlanan_maliyet": True,
            "kaynakta_yeniden_maliyet_baslatilmadi": True,
        },
        "k05": False,
        "yeniden_maliyet_yok": True,
    }


def main() -> int:
    ara = _ara55_kesin()
    # Beklenen 6 doğrula
    eksik_bek = [k for k, sid in ALTI_BEKLENEN.items() if ara.get(k, {}).get("kaynak_stok_id") != sid]
    assert not eksik_bek, f"ARA55 beklenen kimlik sapması: {eksik_bek}"

    miktar_ap = _miktar_birlesik_guncelle(ara)
    birlesik = list(miktar_ap["kayitlar"])
    hareket_by = _yukle_hareket_ozetleri()
    onceki = _onceki_genis()
    bagla_by_kod = {}
    if BAGLA49.is_file():
        bag = json.loads(BAGLA49.read_text(encoding="utf-8"))
        bagla_by_kod = {b["excel_kod"]: b for b in bag.get("baglanan") or []}

    excel = _excel_satirlari()
    esleme = _esle_3252(excel, birlesik, bagla_by_kod, hareket_by, onceki)

    # 6 artık kimlik_yok olmamalı
    kod6 = set(ALTI_BEKLENEN)
    yok6 = [k for k in esleme["kimlik_yok"] if k.get("kod") in kod6]
    eslesen6 = [e for e in esleme["eslesen"] if e.get("kod") in kod6]

    ids_49 = {str(b["kaynak_stok_id"]) for b in bagla_by_kod.values()} if bagla_by_kod else set()
    eslesen_49 = [e for e in esleme["eslesen"] if str(e.get("kaynak_stok_id")) in ids_49]

    # Sıfır maliyet 14 — kart doldurma yok
    sifir = [
        e
        for e in esleme["eslesen"]
        if tr_dec(e.get("birim_maliyet")) == Decimal("0")
        and tr_dec(e.get("kalan")) is not None
        and tr_dec(e.get("kalan")) > 0
    ]
    sifir_ids = {str(e["kaynak_stok_id"]) for e in sifir if e.get("kaynak_stok_id")}
    alis = _yukle_alis_fiyatlar(sifir_ids | ids_49 | set(ALTI_BEKLENEN.values()))
    maliyet_by = _yukle_maliyet()
    sifir_rapor = []
    for e in sifir:
        sid = str(e.get("kaynak_stok_id") or "") or None
        ornek = alis.get(sid or "") or []
        sinif = _sinif_sifir_maliyet(sid, ornek, maliyet_by.get(sid or ""))
        sifir_rapor.append(
            {
                "excel_satir": e.get("excel_satir"),
                "kod": e.get("kod"),
                "adi": e.get("adi"),
                "kalan": e.get("kalan"),
                "birim": e.get("birim"),
                "birim_maliyet": e.get("birim_maliyet"),
                "tutar": e.get("tutar"),
                "kaynak_stok_id": sid,
                "pasif_kart": e.get("pasif_kart"),
                "sinif": sinif.get("sinif"),
                "sinif_detay": sinif,
                "alis_satir_adet": len(ornek),
                "kart_fifo_doldurma_yok": True,
            }
        )

    # 3252 hesaplanabilir satırlar
    tekil_kart = sorted({str(e["kaynak_stok_id"]) for e in esleme["eslesen"] if e.get("kaynak_stok_id")})
    hesap = {
        "format": "d1-stok-3252-hesaplanabilir-v1",
        "zaman": _now(),
        "karsilastirma_esasi": {
            "envanter": "2026-08-31 FIFO Excel",
            "kullanici_teyit": True,
            "yeniden_maliyet_yok": True,
        },
        "satir_adet": esleme["excel_adet"],
        "eslesen_satir_adet": esleme["eslesen_adet"],
        "kimlik_yok_satir_adet": esleme["kimlik_yok_adet"],
        "tekil_kaynak_stok_id_adet": len(tekil_kart),
        "ayrim": {
            "excel_satir_3252": esleme["excel_adet"],
            "tekil_kart": len(tekil_kart),
            "satir_kart_farki": esleme["eslesen_adet"] - len(tekil_kart),
            "aciklama": "3252 satır ≠ tekil kart; çift kod/birim satırları ayrı kalır",
        },
        "alti_onceki_kimlik": {
            "adet": len(eslesen6),
            "yeniden_yok_sayilmadi": len(yok6) == 0,
            "kayitlar": [
                {
                    "kod": e["kod"],
                    "excel_satir": e["excel_satir"],
                    "kaynak_stok_id": e["kaynak_stok_id"],
                    "birim": e.get("birim"),
                    "kaynak_birim": e.get("kaynak_birim"),
                    "esleme_kanit": e.get("esleme_kanit"),
                    "ara55": ara.get(e["kod"]),
                }
                for e in eslesen6
            ],
            "hala_yok": yok6,
        },
        "pasif_pozitif_dusmedi": esleme["pasif_pozitif_karsilastirmadan_dusmedi"],
        "negatif_korundu_adet": esleme["negatif_korundu_adet"],
        "bagla_49_eslesen": sum(1 for e in esleme["eslesen"] if e.get("kod") in bagla_by_kod),
        "sifir_maliyet": {
            "adet": len(sifir_rapor),
            "sinif_say": dict(Counter(str(s.get("sinif")) for s in sifir_rapor)),
            "kart_doldurma_yok": True,
            "kayitlar": sifir_rapor,
        },
        "satirlar": [
            {
                "excel_satir": e.get("excel_satir"),
                "kod": e.get("kod"),
                "adi": e.get("adi"),
                "birim": e.get("birim"),
                "kalan": e.get("kalan"),
                "birim_maliyet": e.get("birim_maliyet"),
                "tutar": e.get("tutar"),
                "kaynak_stok_id": e.get("kaynak_stok_id"),
                "kaynak_birim": e.get("kaynak_birim"),
                "pasif_kart": e.get("pasif_kart"),
                "esleme_durum": e.get("esleme_durum"),
                "esleme_kanit": e.get("esleme_kanit"),
                "hareket_net_31_08": e.get("hareket_net_31_08"),
                "negatif_korundu": e.get("negatif_korundu"),
                "hesaplanabilir": bool(e.get("kaynak_stok_id") and e.get("birim")),
            }
            for e in esleme["eslesen"]
        ],
        "kimlik_yok": esleme["kimlik_yok"],
        "k05": False,
        "mali_yazim": False,
        "exe": False,
    }
    yaz_json(OUT, hesap)

    uz = _kapsam_uzlastir(miktar_ap["adet"])
    yaz_json(OUT_UZ, uz)

    fifo = _fifo_49_aciklar(eslesen_49, hareket_by, alis)
    yaz_json(OUT_FIFO, fifo)

    # Eşleme özetini güncelle (49 pasif dahil + 6)
    if OUT_ESLEME.is_file():
        eski = json.loads(OUT_ESLEME.read_text(encoding="utf-8"))
    else:
        eski = {}
    eski.update(
        {
            "zaman": _now(),
            "alti_onceki_kimlik_tasindi": True,
            "esleme_3252": {
                "excel_adet": esleme["excel_adet"],
                "eslesen_adet": esleme["eslesen_adet"],
                "kimlik_yok_adet": esleme["kimlik_yok_adet"],
                "pasif_pozitif_adet": esleme["pasif_pozitif_miktar_veya_deger"],
                "pasif_pozitif_dusmedi": esleme["pasif_pozitif_karsilastirmadan_dusmedi"],
                "negatif_korundu_adet": esleme["negatif_korundu_adet"],
                "bagla_49_eslesen_kod": sum(
                    1 for e in esleme["eslesen"] if e.get("kod") in bagla_by_kod
                ),
                "ara55_alti_eslesen": len(eslesen6),
            },
            "sifir_maliyet": hesap["sifir_maliyet"],
            "miktar_aktif_pasif_adet": miktar_ap["adet"],
            "k05": False,
        }
    )
    yaz_json(OUT_ESLEME, eski)

    ozet = {
        "zaman": _now(),
        "excel_3252": esleme["excel_adet"],
        "eslesen": esleme["eslesen_adet"],
        "kimlik_yok": esleme["kimlik_yok_adet"],
        "tekil_kart": len(tekil_kart),
        "alti_tasindi": len(eslesen6),
        "alti_yeniden_yok_degil": len(yok6) == 0,
        "miktar_birlesik": miktar_ap["adet"],
        "eklenen_ara55": miktar_ap["eklenen_ara55_aktif"],
        "sifir_adet": len(sifir_rapor),
        "sifir_sinif": hesap["sifir_maliyet"]["sinif_say"],
        "fifo49_miktar_ok": (fifo.get("miktar_dogrulama") or {}).get("ok"),
        "fifo49_katman_dogrulanmis": 0,
        "fifo49_alis_yok": fifo["katman_maliyet_dogrulama"]["alis_yok"],
        "pasif_pozitif_dusmedi": esleme["pasif_pozitif_karsilastirmadan_dusmedi"],
        "negatif": esleme["negatif_korundu_adet"],
        "k05": False,
        "kanit_3252": str(OUT.relative_to(CALISMA)).replace("\\", "/"),
        "kanit_uzlastir": str(OUT_UZ.relative_to(CALISMA)).replace("\\", "/"),
        "kanit_fifo": str(OUT_FIFO.relative_to(CALISMA)).replace("\\", "/"),
    }
    yaz_json(OZET, ozet)
    print(json.dumps(ozet, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
