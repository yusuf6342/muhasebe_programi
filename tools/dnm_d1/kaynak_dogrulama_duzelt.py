"""Özet≠31.08 düzeltmesi + cari/stok/LOT kanıt denetimi.

K05 açılmaz. Mali yazım yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.kaynak_dogrulama_duzelt
  .venv\\Scripts\\python.exe -m tools.dnm_d1.kaynak_dogrulama_duzelt --stok-hareket
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from tools.dnm_d1._ortak import CALISMA, KAYNAK, dec, parse_tarih, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK

DONEM = DONEM_SONU
STOK_HRK_JSONL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_HAREKET.jsonl"


def _yukle(ad: str) -> dict[str, Any]:
    return json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}{ad}.json").read_text(encoding="utf-8"))


def _client():
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials, _uid_bul

    creds = load_credentials()
    c = EvobulutClient(creds)
    y = c._post(
        "index/base/",
        {"cmd": "euas", "p1": creds.kullanici_kodu, "p2": creds.sifre, "app": creds.app},
    )
    c.uid = _uid_bul(y)
    return c


def duzelt_ekstre_etiketleri() -> dict[str, Any]:
    """CARI_EKSTRE: Özet bakiyeyi 31.08 kanıtı sayma."""
    eski = _yukle("CARI_EKSTRE_KAPANIS")
    cariler = []
    sayac = Counter()
    for r in eski.get("cariler") or []:
        det = int(r.get("detay_satir_adet") or 0)
        ozet_b = (r.get("son_ozet") or {}).get("bakiye")
        dev_b = (r.get("devreden_pencere") or {}).get("bakiye")
        eski_kap = r.get("kapanis_bakiye")
        if det > 0:
            # Son detay bakiyesi varsa kanıt adayı; yine de Özet ile ayrıştır
            kanit = "DETAY_VAR_OZET_AYRI"
            kap_3108 = None  # Detay satırları ayrı FIFO/ekstre işinde; burada Özet'i 31.08 yazma
            sayac["detay_var"] += 1
        elif dec(ozet_b) != 0 and det == 0:
            kanit = "DOGRULANMAMIS_OZET"
            kap_3108 = None
            sayac["dogrulanmamis_ozet"] += 1
        else:
            kanit = "DETAY_YOK_OZET_SIFIR_VEYA_BOS"
            kap_3108 = None
            sayac["detay_yok_ozet_sifir"] += 1
        cariler.append(
            {
                "kaynak_cari_id": r.get("kaynak_cari_id"),
                "donem_sonu_dahil": DONEM.isoformat(),
                "kapanis_pencere": r.get("kapanis_pencere"),
                "devreden_pencere": r.get("devreden_pencere"),
                "dogrulanmamis_ozet": r.get("son_ozet"),
                "dogrulanmamis_ozet_bakiye": ozet_b,
                "eski_yanlis_etiket_kapanis_bakiye": eski_kap,
                "kapanis_bakiye_3108_kanitli": kap_3108,
                "detay_satir_adet": det,
                "kanit_durumu": kanit,
                "dilimler": r.get("dilimler"),
                "olcut": "finans_jq_ozet_ayristirilmis_v2",
                "uyari": (
                    "Özet.Bakiye tarih filtresinden bağımsız görünebilir; "
                    "31.08.2026 kapanış bakiyesi değildir. "
                    "Detay yoksa bakiye sıfır sayılmaz; kanıt bekler."
                ),
            }
        )
    out = {
        "format": "d1-kaynak-cari-ekstre-kapanis-v2-ozet-ayristirilmis",
        "donem_sonu_dahil": DONEM.isoformat(),
        "adet": len(cariler),
        "sayac": dict(sayac),
        "tamam_mi": False,  # Özet ayrıştırıldı; 31.08 kanıtlı kapanış paketi değil
        "onceki_dosya_uyari": (
            "D1_20260831_KAYNAK_CARI_EKSTRE_KAPANIS.json içindeki kapanis_bakiye "
            "alanı Özet'ten kopyalanmıştı; 31.08 kanıtı olarak kullanılmamalı."
        ),
        "cariler": cariler,
        "kapanis_durumu": "OZET_AYRISTIRILDI_KANIT_BEKLIYOR",
    }
    yaz_kaynak("CARI_EKSTRE_KAPANIS_DUZELTILMIS", out)

    # Eski dosyaya uyarı bandı (veriyi silmeden)
    eski2 = dict(eski)
    eski2["uyari_duzeltme"] = (
        "kapanis_bakiye alanı Özet bakiyesidir; 31.08.2026 kanıtlı kapanış değildir. "
        "Düzeltilmiş etiketler: CARI_EKSTRE_KAPANIS_DUZELTILMIS.json"
    )
    eski2["kapanis_bakiye_alani_anlami"] = "DOGRULANMAMIS_OZET_BAKIYE"
    eski2["tamam_mi"] = False
    yaz_kaynak("CARI_EKSTRE_KAPANIS", eski2)
    return out


def arastir_15_ve_ozet_riskli(client) -> dict[str, Any]:
    from entegrasyon.evobulut_client import _ana_listesi

    ak = _yukle("ACIK_KALEM")
    duz = _yukle("CARI_EKSTRE_KAPANIS_DUZELTILMIS")
    kart_idx = {
        str(r.get("R.a_id")): r for r in (_yukle("CARI").get("kayitlar") or [])
    }
    dy_ids = [str(c["kaynak_cari_id"]) for c in ak.get("cariler") or [] if c.get("detay_yok_uyari")]
    risk_ids = [
        str(c["kaynak_cari_id"])
        for c in duz.get("cariler") or []
        if c.get("kanit_durumu") == "DOGRULANMAMIS_OZET"
    ]
    hedef = sorted(set(dy_ids) | set(risk_ids), key=lambda x: int(x))

    liste = []
    for i, cid in enumerate(hedef, 1):
        if i % 10 == 0:
            client.login()
        kart = kart_idx.get(cid) or {}
        sql = client._post("cari/base/", {"cmd": "sql", "UID": client.uid, "a_id": cid})
        ana = {}
        if sql.get("status") == "OK":
            a = (sql.get("veri") or {}).get("Ana") or []
            ana = a[0] if a else {}

        # Yıllık dilimlerde ilk/son detay ara (kapama uydurma yok)
        dilimler = []
        ilk_hareket = None
        son_hareket_3108 = None
        detay_toplam = 0
        for yil in range(DONEM.year, 2014, -1):
            bas = f"01.01.{yil}"
            bit = f"31.12.{yil}" if yil < DONEM.year else DONEM.strftime("%d.%m.%Y")
            y = client._post(
                "Musteri/base/",
                {
                    "cmd": "finans_jq_listesi",
                    "UID": client.uid,
                    "musteri_id": cid,
                    "b_tarihi": bas,
                    "s_tarihi": bit,
                    "tur": "-1",
                },
            )
            v = y.get("veri") if y.get("status") == "OK" else None
            det = (v.get("Detay") or []) if isinstance(v, dict) else []
            ozet = (v.get("Özet") or v.get("Ozet")) if isinstance(v, dict) else None
            dev = v.get("Devreden") if isinstance(v, dict) else None
            dilimler.append(
                {
                    "bas": bas,
                    "son": bit,
                    "status": y.get("status"),
                    "detay_adet": len(det),
                    "ozet": ozet,
                    "devreden": dev,
                }
            )
            detay_toplam += len(det)
            for row in det:
                t = parse_tarih(row.get("Tarih"))
                if t is None:
                    continue
                if ilk_hareket is None or t < parse_tarih(ilk_hareket.get("Tarih")):
                    ilk_hareket = row
                if t <= DONEM and (
                    son_hareket_3108 is None
                    or t > parse_tarih(son_hareket_3108.get("Tarih"))
                ):
                    son_hareket_3108 = row
            time.sleep(0.03)
            if len(det) == 0 and yil < DONEM.year - 1:
                # iki boş yıl üst üste → daha geriye gitmeye devam (açılış aranıyor)
                pass

        # Fatura tur 30-37 a_cari_id
        fat_adet = {}
        for tur in ("30", "31", "32", "33", "34", "35"):
            fr = client._post(
                "fatura/base/",
                {
                    "cmd": "jq_list",
                    "UID": client.uid,
                    "sayfa": "0",
                    "ara": "",
                    "tur": tur,
                    "a_onay": "",
                    "a_cari_id": cid,
                    "a_tarih_bas": "01.01.2015",
                    "a_tarih_son": DONEM.strftime("%d.%m.%Y"),
                    "a_stok_id": "",
                    "a_stok_ack": "",
                },
            )
            ana_f = _ana_listesi(fr) if fr.get("status") == "OK" else []
            fat_adet[tur] = len(ana_f)
            time.sleep(0.02)

        ozet_ornek = None
        for d in dilimler:
            if d.get("ozet"):
                ozet_ornek = d["ozet"]
                break

        bakiye_3108 = None
        kanit_3108 = None
        if son_hareket_3108 is not None:
            bakiye_3108 = son_hareket_3108.get("Bakiye")
            kanit_3108 = "SON_DETAY_BAKIYE_<=31.08"
        elif detay_toplam == 0:
            bakiye_3108 = None
            kanit_3108 = "KANIT_YOK_DETAY_BOS"
        else:
            kanit_3108 = "DETAY_VAR_AMA_31.08_ONCESI_SON_SATIR_YOK"

        unvan = (kart.get("text") or "").split("----")[0].strip() or ana.get("a_ad")
        liste.append(
            {
                "kaynak_cari_id": cid,
                "kod": ana.get("a_kod") or kart.get("R.a_kod") or None,
                "unvan": unvan or ana.get("a_resmi_ad"),
                "kart_acilis_tarihi_api": None,  # cari/sql'de alan yok
                "kart_acilis_tarihi_durum": "UYGULANAMAZ_ALAN_YOK",
                "ilk_gercek_hareket": (
                    {
                        "tarih": ilk_hareket.get("Tarih"),
                        "tur": ilk_hareket.get("Tur"),
                        "borc": ilk_hareket.get("Borc"),
                        "alacak": ilk_hareket.get("Alacak"),
                        "bakiye": ilk_hareket.get("Bakiye"),
                        "id": ilk_hareket.get("id"),
                        "ack": ilk_hareket.get("Ack") or ilk_hareket.get("ack"),
                    }
                    if ilk_hareket
                    else None
                ),
                "kaynak_acilis_devir_kaydi": None,  # bulunamadı — uydurulmadı
                "dogrulanmamis_ozet_bakiye": ozet_ornek,
                "bakiye_3108_kanitli": bakiye_3108,
                "bakiye_3108_kanit": kanit_3108,
                "detay_toplam_tum_yillar": detay_toplam,
                "fatura_adet_tur": fat_adet,
                "dilim_ozet": [
                    {
                        "bas": d["bas"],
                        "son": d["son"],
                        "detay_adet": d["detay_adet"],
                        "ozet_bakiye": (
                            (d["ozet"][0].get("Bakiye") if isinstance(d.get("ozet"), list) and d["ozet"] else None)
                            if d.get("ozet")
                            else None
                        ),
                    }
                    for d in dilimler
                ],
                "eylul_sonrasi_tasinmadi": True,
                "sifir_sayilmadi": True,
            }
        )
        print(
            f"cari_arastir {i}/{len(hedef)} id={cid} detay={detay_toplam} "
            f"kanit={kanit_3108}",
            flush=True,
        )

    out = {
        "format": "d1-dogrulama-cari-ozet-risk-arastirma-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "adet": len(liste),
        "detay_yok_15_dahil": dy_ids,
        "dogrulanmamis_ozet_tum": risk_ids,
        "cariler": liste,
        "ozet_istatistik": {
            "kanit_yok": sum(
                1 for x in liste if x.get("bakiye_3108_kanit") == "KANIT_YOK_DETAY_BOS"
            ),
            "kanitli_detay": sum(
                1
                for x in liste
                if x.get("bakiye_3108_kanit") == "SON_DETAY_BAKIYE_<=31.08"
            ),
        },
        "sonuc": "EKSIK",
        "gerekce": (
            "Özet bakiyeler 31.08 olarak etiketlenmedi. "
            "Detay/açılış/devir bulunamayanlarda bakiye_3108_kanitli=null."
        ),
    }
    yaz_kaynak("DOGRULAMA_CARI_OZET_RISK_ARASTIRMA", out)

    # 15 cari özel düzeltilmiş liste
    only15 = [x for x in liste if x["kaynak_cari_id"] in set(dy_ids)]
    yaz_kaynak(
        "DOGRULAMA_15_CARI_DETAY",
        {
            "format": "d1-dogrulama-15-cari-detay-v2",
            "donem_sonu_dahil": DONEM.isoformat(),
            "adet": len(only15),
            "etiket_duzeltmesi": (
                "dogrulanmamis_ozet_bakiye kullanıldı; "
                "bakiye_3108_ekstre_ozet / kapanis_bakiye_3108 kaldırıldı."
            ),
            "cariler": only15,
            "sonuc": "EKSIK",
            "k05": False,
        },
    )
    return out


def esitlik_denetimi() -> dict[str, Any]:
    """Açılış(Devreden) + dönem Detay neti ≈ son Detay bakiyesi; Özet ayrı."""
    # ACIK_KALEM jsonl üzerinden detaylı cariler
    jsonl = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}ACIK_KALEM.jsonl"
    ok = fark = ozet_risk = 0
    ornek_fark = []
    ornek_ok = []
    if not jsonl.is_file():
        return {"sonuc": "EKSIK", "gerekce": "ACIK_KALEM.jsonl yok"}

    for line in jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        cid = o.get("kaynak_cari_id")
        det_n = int(o.get("detay_birlesen_adet") or 0)
        ozet = o.get("kapanis_ozet_umum") or {}
        dev = o.get("kapanis_devreden") or {}
        ozet_b = dec(ozet.get("bakiye"))
        dev_b = dec(dev.get("bakiye"))
        if det_n == 0:
            if ozet_b != 0:
                ozet_risk += 1
            continue
        # Detay birleşik değil jsonl'de tam satır yok — son_detay_bakiye kullan
        son = o.get("kapanis_son_detay_bakiye")
        if son is None:
            continue
        # Eşitlik proxy: Devreden + (Özet borc-alacak) güvenilmez; yalnız kayıt
        # Gerçek: son detay bakiye kanıt; Özet ile fark raporla
        fark_ozet = dec(son) - ozet_b
        row = {
            "kaynak_cari_id": cid,
            "devreden": str(dev_b),
            "son_detay_bakiye": son,
            "dogrulanmamis_ozet_bakiye": str(ozet_b),
            "ozet_minus_detay": str(fark_ozet),
            "doviz": "TL",  # kaynak dilimde döviz ayrımı yoksa TL varsayım — not düş
        }
        if fark_ozet == 0:
            ok += 1
            if len(ornek_ok) < 10:
                ornek_ok.append(row)
        else:
            fark += 1
            if len(ornek_fark) < 40:
                ornek_fark.append(row)

    out = {
        "format": "d1-dogrulama-cari-esitlik-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "kural": "Devreden + dönem hareketleri = kapanış; Özet ayrı doğrulanmamış alan",
        "detayli_cari_ozet_esit": ok,
        "detayli_cari_ozet_farkli": fark,
        "dogrulanmamis_ozet_detay_yok": ozet_risk,
        "ornek_fark": ornek_fark,
        "ornek_esit": ornek_ok,
        "doviz_notu": (
            "finans_jq diliminde döviz kırılımı yok; TL özet. "
            "Dövizli cari için Evo 'Dövizli Cari Ekstre' gerekir."
        ),
        "sonuc": "KISMI",
        "k05": False,
    }
    yaz_kaynak("DOGRULAMA_CARI_ESITLIK", out)
    return out


def stok_hareket_cek(client, *, limit: int = 0) -> dict[str, Any]:
    from entegrasyon.evobulut_client import _ana_listesi

    sm = _yukle("STOK_MALIYET")
    ids = [str(s["kaynak_stok_id"]) for s in (sm.get("stoklar") or [])]
    if limit:
        ids = ids[:limit]
    maliyet = {str(s["kaynak_stok_id"]): s for s in (sm.get("stoklar") or [])}

    basarili: dict[str, dict] = {}
    if STOK_HRK_JSONL.is_file():
        for line in STOK_HRK_JSONL.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            o = json.loads(line)
            sid = str(o.get("kaynak_stok_id") or "")
            if sid and o.get("status") == "OK":
                basarili[sid] = o

    t0 = time.time()
    yeni = 0
    tmp = STOK_HRK_JSONL.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for o in basarili.values():
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
        for i, sid in enumerate(ids, 1):
            if sid in basarili:
                continue
            if i % 40 == 0:
                client.login()
            try:
                y = client._post(
                    "StokHareket/base/",
                    {
                        "cmd": "list",
                        "UID": client.uid,
                        "stok_id": sid,
                        "depo": "0",
                        "birim": "0",
                        "carpan": "1",
                        "birim_adi": "",
                        "bas_tar": "01.01.2015",
                        "bit_tar": DONEM.strftime("%d.%m.%Y"),
                        "dovizli_goster": "0",
                    },
                )
                ana = _ana_listesi(y)
                ic = []
                dis = 0
                for r in ana:
                    t = parse_tarih(r.get("tarih"))
                    if t is not None and t > DONEM:
                        dis += 1
                        continue
                    ic.append(r)
                gir = sum((dec(r.get("gir_miktar")) for r in ic), Decimal("0"))
                cik = sum((dec(r.get("cik_miktar")) for r in ic), Decimal("0"))
                # depo/birim/devir/iade sayıları
                depolar = Counter(str(r.get("depo") or "") for r in ic)
                birimler = Counter(str(r.get("Birim") or "") for r in ic)
                turler = Counter(str(r.get("belge_tur") or r.get("Tur") or "") for r in ic)
                devir_n = sum(1 for r in ic if str(r.get("devir") or "0") not in ("0", "", "None"))
                m = maliyet.get(sid) or {}
                kart_kalan = dec(m.get("kalan")) if m.get("kalan") not in (None, "") else None
                net = gir - cik
                fark = (kart_kalan - net) if kart_kalan is not None else None
                kayit = {
                    "kaynak_stok_id": sid,
                    "status": "OK",
                    "kod": m.get("kod"),
                    "adi": m.get("adi"),
                    "kart_kalan": m.get("kalan"),
                    "hareket_adet": len(ic),
                    "donem_sonrasi_atlanadi": dis,
                    "gir_toplam": str(gir),
                    "cik_toplam": str(cik),
                    "hareket_net": str(net),
                    "kart_minus_hareket_net": str(fark) if fark is not None else None,
                    "depo_adet": dict(depolar),
                    "birim_adet": dict(birimler),
                    "belge_tur_adet": dict(turler),
                    "devir_bayrakli_adet": devir_n,
                    "sayfalama": {
                        "tek_cekim_adet": len(ana),
                        "toplam_alan": y.get("veri", {}).get("Toplam")
                        if isinstance(y.get("veri"), dict)
                        else None,
                        "not": "Toplam [] iken tek yanıtta tüm satırlar varsayıldı",
                    },
                    "donem_sonu_dahil": DONEM.isoformat(),
                    "alim_zamani": datetime.now().astimezone().isoformat(timespec="seconds"),
                }
                f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
                f.flush()
                basarili[sid] = kayit
                yeni += 1
            except Exception as exc:  # noqa: BLE001
                f.write(
                    json.dumps(
                        {
                            "kaynak_cari_id": None,
                            "kaynak_stok_id": sid,
                            "status": "ERR",
                            "hata": type(exc).__name__,
                            "mesaj": str(exc)[:200],
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                f.flush()
            if i % 25 == 0 or i == len(ids):
                print(
                    f"stok_hrk {i}/{len(ids)} yeni={yeni} ok={len(basarili)} "
                    f"gecen={time.time()-t0:.0f}s",
                    flush=True,
                )
            time.sleep(0.02)
    tmp.replace(STOK_HRK_JSONL)

    # Özet fark sınıfları
    sinif = Counter()
    fark_ornek = []
    negatif = []
    for sid, o in basarili.items():
        if o.get("status") != "OK":
            continue
        fark = o.get("kart_minus_hareket_net")
        if fark is None:
            sinif["kart_kalan_yok"] += 1
            continue
        fd = dec(fark)
        if fd == 0:
            sinif["esit"] += 1
        else:
            sinif["farkli"] += 1
            if len(fark_ornek) < 50:
                fark_ornek.append(o)
        if dec(o.get("kart_kalan")) < 0:
            negatif.append(
                {
                    "kaynak_stok_id": sid,
                    "kart_kalan": o.get("kart_kalan"),
                    "hareket_net": o.get("hareket_net"),
                    "korundu": True,
                }
            )

    out = {
        "format": "d1-kaynak-stok-hareket-ozet-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "hedef_adet": len(ids),
        "ok_adet": sum(1 for o in basarili.values() if o.get("status") == "OK"),
        "jsonl": STOK_HRK_JSONL.name,
        "sinif": dict(sinif),
        "fark_ornek": fark_ornek[:40],
        "negatif_korunan": negatif,
        "yapay_duzeltme": False,
        "tamam_mi": len(basarili) >= len(ids),
        "k05": False,
    }
    yaz_kaynak("STOK_HAREKET_OZET", out)
    return out


def lot_katman_analiz() -> dict[str, Any]:
    """Belge LOT + (varsa) stok hareket ack eşlemesi; maliyet katmanı uydurma yok."""
    jsonl_b = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE_SATIR.jsonl"
    sm = _yukle("STOK_MALIYET")
    maliyet = {str(s["kaynak_stok_id"]): s for s in (sm.get("stoklar") or [])}

    katmanlar = []  # miktar/tarih kanıtı; maliyet ayrı
    with jsonl_b.open(encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            t = parse_tarih(o.get("tarih"))
            if t and t > DONEM:
                continue
            tur = str(o.get("tur") or o.get("liste_tur") or "")
            for s in o.get("satirlar") or []:
                lots = s.get("seri_lot")
                if not lots:
                    continue
                if isinstance(lots, dict):
                    lots = [lots]
                if not isinstance(lots, list):
                    continue
                sid = str(s.get("a_stok_id") or s.get("stok_id") or "")
                for L in lots:
                    if not isinstance(L, dict):
                        continue
                    katmanlar.append(
                        {
                            "stok_id": sid,
                            "lot_no": L.get("a_lot_no") or L.get("a_seri_no"),
                            "lot_id": L.get("a_id"),
                            "belge_id": o.get("kaynak_belge_id"),
                            "belge_tur": tur,
                            "belge_tarih": o.get("tarih"),
                            "giren": L.get("a_giren"),
                            "cikan": L.get("a_cikan"),
                            "kalan_alan_anlik": L.get("kalan"),
                            "haric_kalan": L.get("haric_kalan"),
                            "satir_birim_fiyat": s.get("birim_fiyat"),
                            "satir_tutar": s.get("tutar"),
                            "katman_birim_maliyet_kanit": None,  # uydurulmadı
                            "katman_maliyet_durum": "BEKLIYOR",
                        }
                    )

    # Kalan lot anahtarları (son görülen)
    son: dict[str, dict] = {}
    for k in katmanlar:
        key = f"{k['stok_id']}|{k['lot_no']}"
        son[key] = k

    # FIFO-ort farkları (miktar farkından ayrı dosya)
    fifo_ort = []
    for s in sm.get("stoklar") or []:
        if s.get("maliyet_fifo") in (None, "") or s.get("maliyet_ort") in (None, ""):
            continue
        df = dec(s["maliyet_fifo"]) - dec(s["maliyet_ort"])
        if df == 0:
            continue
        fifo_ort.append(
            {
                "kaynak_stok_id": s["kaynak_stok_id"],
                "kod": s.get("kod"),
                "kalan": s.get("kalan"),
                "fifo": s.get("maliyet_fifo"),
                "ort": s.get("maliyet_ort"),
                "fark_birim": str(df),
                "fark_tutar_kalanx": str(
                    (df * dec(s.get("kalan"))).quantize(Decimal("0.0001"))
                ),
                "not": "Yöntem farkı; miktar farkı değil. Katman doğrulaması sayılmaz.",
            }
        )
    fifo_ort.sort(key=lambda x: abs(dec(x["fark_tutar_kalanx"])), reverse=True)
    yaz_kaynak(
        "DOGRULAMA_FIFO_ORT_YONTEM_AYRI",
        {
            "format": "d1-fifo-ort-yontem-ayri-v1",
            "donem_sonu_dahil": DONEM.isoformat(),
            "adet": len(fifo_ort),
            "fark_tutar_abs": str(
                sum((abs(dec(x["fark_tutar_kalanx"])) for x in fifo_ort), Decimal("0"))
            ),
            "kayitlar": fifo_ort[:200],
            "a_maliyet_fifo_tek_basina_katman_kaniti_degil": True,
        },
    )

    out = {
        "format": "d1-dogrulama-lot-katman-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "lot_hareket_satir_adet": len(katmanlar),
        "tekil_stok_lot": len(son),
        "miktar_tarih_kanit_kaynak": "fatura Seri_Lot_List + belge tarih/tur",
        "maliyet_kanit_durum": "BEKLIYOR",
        "maliyet_gerekce": (
            "Seri_Lot_List satırında katman birim maliyeti yok. "
            "a_maliyet_fifo kart düzeyi; katman doğrulaması sayılmaz. "
            "Alış faturası birim fiyatı giriş ipucu olabilir ama FIFO tüketim "
            "katmanı için yeterli kanıt değildir."
        ),
        "kalan_lot_ornek": list(son.values())[:40],
        "a_maliyet_fifo_ornek_stok": [
            {
                "stok_id": sid,
                "fifo": (maliyet.get(sid) or {}).get("maliyet_fifo"),
                "ort": (maliyet.get(sid) or {}).get("maliyet_ort"),
                "katman_kaniti": False,
            }
            for sid in list({k["stok_id"] for k in list(son.values())[:20]})
        ],
        "sonuc": "KISMI",
        "k05": False,
    }
    yaz_kaynak("DOGRULAMA_LOT_KATMAN", out)
    return out


def gerekli_ekranlar() -> dict[str, Any]:
    out = {
        "format": "d1-gerekli-evo-ekran-excel-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "maddeler": [
            {
                "eksik": "15+ cari Detay/kapama yok; Özet tarih bağımsız",
                "ekran": "Müşteri Yönetimi → Cari Kart → Hesap Ekstresi (finans)",
                "filtreler": [
                    "Cari: listedeki her ID/ünvan",
                    "Başlangıç: ilgili açılış veya 01.01.2015",
                    "Bitiş: 31.08.2026 (dahil)",
                    "Tür: Tümü",
                    "Döviz: TL ve varsa dövizli ayrı",
                ],
                "excel": "Cari Hesap Ekstresi dışa aktarım (aynı filtreler)",
            },
            {
                "eksik": "Açık kalem / kapama ilişkisi",
                "ekran": "Raporlar → Cari → Açık Hesaplar / Açık Kalemler (firma menü adı)",
                "filtreler": ["Durum: Açık", "Tarih ≤ 31.08.2026", "Cari: tümü veya risk listesi"],
                "excel": "Açık Kalem Listesi Excel",
            },
            {
                "eksik": "Kart açılış / devir belgesi",
                "ekran": "Cari Kart → Hareketler / Açılış Fişi",
                "filtreler": ["Belge türü: Açılış, Devir, Virman", "Tarih artan"],
                "excel": None,
            },
            {
                "eksik": "Döviz bazlı açılış+hareket=kapanış",
                "ekran": "Cari → Dövizli Ekstre / Döviz Bakiyeleri",
                "filtreler": ["Bitiş 31.08.2026", "Döviz kırılımı açık"],
                "excel": "Dövizli Cari Bakiye raporu",
            },
            {
                "eksik": "LOT katman maliyeti",
                "ekran": "Ürün Yönetimi → Stok Kartı → Seri/LOT / Stok Hareketleri",
                "filtreler": [
                    "Stok: LOT’lu kartlar",
                    "Tarih ≤ 31.08.2026",
                    "Depo: tümü ve depo bazlı ayrı",
                ],
                "excel": "Stok LOT Envanter / Seri-LOT Raporu Excel (31.08.2026)",
            },
            {
                "eksik": "Kart miktar ≠ hareket neti kök nedeni",
                "ekran": "Stok Hareket Raporu + Depo Envanter",
                "filtreler": [
                    "Depo kırılımı",
                    "Birim / çarpan",
                    "İrsaliye–fatura iade/iptal dahil",
                    "Açılış/devir fişleri",
                ],
                "excel": "Stok Envanter (depo+birim) 31.08.2026",
            },
        ],
    }
    yaz_kaynak("DOGRULAMA_GEREKLI_EKRAN_EXCEL", out)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--stok-hareket", action="store_true", help="2522 stok hareket çekimi")
    p.add_argument("--stok-limit", type=int, default=0)
    p.add_argument("--atla-cari-arastir", action="store_true")
    args = p.parse_args(argv)

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    print("... ekstre etiket düzelt", flush=True)
    ek = duzelt_ekstre_etiketleri()
    print("... esitlik", flush=True)
    es = esitlik_denetimi()
    print("... lot katman", flush=True)
    lot = lot_katman_analiz()
    ekr = gerekli_ekranlar()

    cari_ar = None
    if not args.atla_cari_arastir:
        print("... cari ozet risk arastir", flush=True)
        client = _client()
        cari_ar = arastir_15_ve_ozet_riskli(client)
    else:
        client = None

    stok = None
    if args.stok_hareket:
        print("... stok hareket", flush=True)
        if client is None:
            client = _client()
        stok = stok_hareket_cek(client, limit=args.stok_limit)

    ozet = {
        "format": "d1-kaynak-dogrulama-duzelt-ozet-v1",
        "zaman": now,
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "exe_paket": False,
        "cozulen": [
            {
                "madde": "ozet_31_08_etiket_kaldirildi",
                "kanit": "CARI_EKSTRE_KAPANIS_DUZELTILMIS.json",
                "sayac": ek.get("sayac"),
            }
        ],
        "bekleyen": [
            {
                "madde": "15_cari_3108_kanitli_bakiye",
                "kanit": "DOGRULAMA_15_CARI_DETAY.json / DOGRULAMA_CARI_OZET_RISK_ARASTIRMA.json",
                "durum": (cari_ar or {}).get("ozet_istatistik"),
            },
            {
                "madde": "lot_katman_maliyet",
                "kanit": "DOGRULAMA_LOT_KATMAN.json",
                "durum": lot.get("maliyet_kanit_durum"),
            },
            {
                "madde": "stok_hareket_tum",
                "kanit": "STOK_HAREKET_OZET.json" if stok else "bekliyor --stok-hareket",
                "durum": (stok or {}).get("sinif"),
            },
            {
                "madde": "cari_esitlik_doviz",
                "kanit": "DOGRULAMA_CARI_ESITLIK.json",
                "durum": {
                    "ozet_esit": es.get("detayli_cari_ozet_esit"),
                    "ozet_fark": es.get("detayli_cari_ozet_farkli"),
                    "ozet_risk_detay_yok": es.get("dogrulanmamis_ozet_detay_yok"),
                },
            },
        ],
        "gerekli_ekranlar": "DOGRULAMA_GEREKLI_EKRAN_EXCEL.json",
    }
    yaz_json(CALISMA / "KAYNAK_DOGRULAMA_DUZELT_OZET.json", ozet)

    durum_yol = CALISMA / "DURUM.json"
    durum = json.loads(durum_yol.read_text(encoding="utf-8")) if durum_yol.is_file() else {}
    durum.update(
        {
            "guncelleme": now,
            "ozet": (
                "Özet≠31.08 etiket düzeltildi. "
                f"DOGRULANMAMIS_OZET={ek['sayac'].get('dogrulanmamis_ozet')}. "
                "15 cari 31.08 kanıtı bekliyor. LOT maliyet bekliyor. K05 kapalı."
            ),
            "k05": False,
            "k06": False,
            "dogrulama_duzelt": "KAYNAK_DOGRULAMA_DUZELT_OZET.json",
            "eksik_k05": [
                "31.08 kanıtlı cari kapanış (Özet değil)",
                "LOT katman maliyeti",
                "Stok hareket tam set + fark kök neden",
                "K06/EXE erteli",
            ],
        }
    )
    yaz_json(durum_yol, durum)

    print(json.dumps({"k05": False, "ekstre_sayac": ek.get("sayac"), "stok": bool(stok)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
