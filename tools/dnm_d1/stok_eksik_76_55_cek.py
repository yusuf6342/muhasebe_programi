"""Devir 1 — 76 belge-kimlikli + 55 kimliksiz stok kaynak tamamlaması.

- 76 stok_id: kart (liste/sql) + StokHareket satır detayı ≤31.08.2026
- Negatifler 1193, 6178, 11968 dahil; negatif korunur
- 55 Excel kodu: jq_list ara= exact; pasif/barkod hipotezi; dosyada yok ≠ kaynakta yok
- 1358: belge/kart kanıtı; yalnız hareket_net=12 kesin sayılmaz
- 23 fark: Excel gösterim hassasiyeti; FIFO ham hassasiyet
- K05 / maliyet hesabı / mali yazım / EXE yok

  .venv\\Scripts\\python.exe -m tools.dnm_d1.stok_eksik_76_55_cek
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from tools.dnm_d1._ortak import CALISMA, KAYNAK, dec, parse_tarih, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK

ESLEME = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_ENVANTER_ESLEME_COZ.json"
BELGE_SATIR = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE_SATIR.jsonl"
STOK_MIKTAR = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_MIKTAR.json"
FIFO_KONTROL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_FIFO_KASA_BANKA_POS_KONTROL.json"
DETAY_JSONL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_HAREKET_76_DETAY.jsonl"
KART_76 = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_KART_76_BELGE_KIMLIK.json"
ARA_55 = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_ARA_55_KIMLIK.json"

NEGATIF_IDS = {"1193", "6178", "11968"}
BAS_TAR = "01.01.2015"
BIT_TAR = DONEM_SONU.strftime("%d.%m.%Y")
KURUS = Decimal("0.01")


def _q2(v: Decimal) -> Decimal:
    return v.quantize(KURUS, rounding=ROUND_HALF_UP)


def _hareket_ozet(sid: str, kod: str | None, adi: str | None, satirlar: list[dict]) -> dict:
    ic = []
    dis = 0
    for h in satirlar:
        t = parse_tarih(h.get("tarih"))
        if t is not None and t > DONEM_SONU:
            dis += 1
            continue
        ic.append(h)
    # sıra: tarih, id
    ic.sort(
        key=lambda h: (
            parse_tarih(h.get("tarih")) or DONEM_SONU,
            int(str(h.get("id") or "0") or 0),
        )
    )
    gir = sum((dec(h.get("gir_miktar")) for h in ic), Decimal("0"))
    cik = sum((dec(h.get("cik_miktar")) for h in ic), Decimal("0"))
    net = gir - cik
    return {
        "kaynak_stok_id": sid,
        "status": "OK",
        "kod": kod,
        "adi": adi,
        "grup": "belge_kimlik_76_3150_disi",
        "hareket_adet": len(ic),
        "donem_sonrasi_atlanadi": dis,
        "gir_toplam": str(gir),
        "cik_toplam": str(cik),
        "hareket_net": str(net),
        "depo_adet": dict(Counter(str(h.get("depo") or "") for h in ic)),
        "birim_adet": dict(Counter(str(h.get("Birim") or "") for h in ic)),
        "belge_tur_adet": dict(
            Counter(str(h.get("belge_tur") or h.get("Tur") or "") for h in ic)
        ),
        "devir_bayrakli_adet": sum(
            1 for h in ic if str(h.get("devir") or "0") not in ("0", "", "None")
        ),
        "fat_id_adet": len({str(h.get("Fat_id") or "") for h in ic if h.get("Fat_id")}),
        "sayfalama": {
            "tek_cekim_adet": len(satirlar),
            "donem_ici_adet": len(ic),
            "not": "StokHareket cmd=list tek yanıt; toplam alanı yoksa tek çekim varsayımı",
        },
        "donem_sonu_dahil": DONEM_SONU.isoformat(),
        "bas_tar": BAS_TAR,
        "bit_tar": BIT_TAR,
        "alim_zamani": datetime.now().astimezone().isoformat(timespec="seconds"),
        "negatif_korundu": sid in NEGATIF_IDS,
        "satirlar": [
            {
                "id": h.get("id"),
                "tarih": h.get("tarih"),
                "belge_tur": h.get("belge_tur") or h.get("Tur"),
                "Fat_id": h.get("Fat_id"),
                "Fat_belge_no": h.get("Fat_belge_no"),
                "Fat_Tur_id": h.get("Fat_Tur_id"),
                "depo": h.get("depo"),
                "Birim": h.get("Birim"),
                "gir_miktar": h.get("gir_miktar"),
                "cik_miktar": h.get("cik_miktar"),
                "gir_fiyat": h.get("gir_fiyat"),
                "cik_fiyat": h.get("cik_fiyat"),
                "devir": h.get("devir"),
                "a_stok_id": h.get("a_stok_id"),
                "ack": h.get("ack"),
            }
            for h in ic
        ],
    }


def _kart_ara(client: Any, sid: str, excel_kod: str | None) -> dict:
    """Kart: önce a_id ara, sonra excel kod exact, sql detay."""
    out: dict[str, Any] = {
        "kaynak_stok_id": sid,
        "liste_bulundu": False,
        "sql_bulundu": False,
        "kart": None,
        "sql_mesaj": None,
    }
    # sql
    try:
        y = client._post(
            "stok/base/",
            {
                "cmd": "sql",
                "UID": client.uid,
                "a_stok_id": str(sid),
                "grupgetir": "1",
                "a_barkod": "",
            },
        )
        veri = y.get("veri") or y.get("Veri") or {}
        if isinstance(veri, list):
            out["sql_mesaj"] = veri[0] if veri else "bos_list"
        elif isinstance(veri, dict):
            ana = veri.get("Ana") or veri.get("ana")
            if isinstance(ana, list) and ana:
                out["sql_bulundu"] = True
                out["kart"] = ana[0]
            elif veri.get("a_id") or veri.get("Ana"):
                out["sql_bulundu"] = True
                out["kart"] = veri if veri.get("a_id") else (ana[0] if ana else veri)
            else:
                out["sql_mesaj"] = str(veri)[:200]
    except Exception as exc:  # noqa: BLE001
        out["sql_mesaj"] = f"{type(exc).__name__}:{exc}"[:200]

    # jq_list ara by id then kod
    for ara in (sid, excel_kod or ""):
        if not ara:
            continue
        try:
            sat, adet = client.stok_liste_sayfa(0, ara=str(ara))
        except Exception as exc:  # noqa: BLE001
            out.setdefault("liste_hata", str(exc)[:120])
            continue
        exact = [
            s
            for s in sat
            if str(s.get("a_id")) == str(sid)
            or (excel_kod and str(s.get("a_kod") or "").strip() == str(excel_kod).strip())
        ]
        if exact:
            hit = next((s for s in exact if str(s.get("a_id")) == str(sid)), exact[0])
            out["liste_bulundu"] = True
            out["liste_adet"] = adet
            if not out.get("kart"):
                out["kart"] = hit
            else:
                out["liste_kart"] = {
                    "a_id": hit.get("a_id"),
                    "a_kod": hit.get("a_kod"),
                    "a_adi": hit.get("a_adi"),
                    "ana_birim_adi": hit.get("ana_birim_adi"),
                    "a_brm_id": hit.get("a_brm_id"),
                    "a_kalan": hit.get("a_kalan"),
                    "aktif_pasif": hit.get("aktif_pasif"),
                }
            break
    return out


def _exact_ara_kod(client: Any, kod: str) -> list[dict]:
    sat, adet = client.stok_liste_sayfa(0, ara=kod)
    exact = [s for s in sat if str(s.get("a_kod") or "").strip() == kod]
    # barkod alanı listede yok; alternatif: aynı ara sonucu farklı kod = bağlama
    return exact


def _belge_1358() -> dict:
    """1358 kesin kanıt: BELGE_SATIR stok_id + kod ilişkisi."""
    belgeler = []
    with BELGE_SATIR.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            if o.get("status") != "OK":
                continue
            for i, s in enumerate(o.get("satirlar") or []):
                sid = str(s.get("stok_id") or s.get("a_stok_id") or "")
                if sid != "1358":
                    continue
                belgeler.append(
                    {
                        "belge_id": o.get("kaynak_belge_id"),
                        "tur": o.get("tur"),
                        "tarih": o.get("tarih"),
                        "satir_index": i,
                        "stok_kod": s.get("stok_kod"),
                        "stok_id": sid,
                        "miktar": s.get("miktar"),
                        "birim": s.get("birim"),
                        "birim_fiyat": s.get("birim_fiyat"),
                        "depo_id": s.get("depo_id"),
                    }
                )
    miktar = json.loads(STOK_MIKTAR.read_text(encoding="utf-8"))
    kart = next(
        (r for r in (miktar.get("kayitlar") or []) if str(r.get("a_id")) == "1358"),
        None,
    )
    return {
        "kaynak_stok_id": "1358",
        "excel_kod": "8697393764057",
        "onceki_esleme": "BELIRSIZ_HAREKET_NET_COZULDU — yalnız net=12 kesin sayılmaz",
        "kart_3150": {
            "a_id": "1358",
            "a_kod": (kart or {}).get("a_kod"),
            "a_adi": (kart or {}).get("a_adi"),
            "a_kalan": (kart or {}).get("a_kalan"),
            "ana_birim_adi": (kart or {}).get("ana_birim_adi"),
        }
        if kart
        else None,
        "belge_satir_adet": len(belgeler),
        "belge_stok_kod_uyum": all(
            str(b.get("stok_kod") or "") == "8697393764057" for b in belgeler
        )
        if belgeler
        else False,
        "belge_ornek": belgeler[:5],
        "kesin_esleme": bool(kart)
        and str((kart or {}).get("a_kod") or "") == "8697393764057"
        and len(belgeler) > 0
        and all(str(b.get("stok_kod") or "") == "8697393764057" for b in belgeler),
        "destekleyici_miktar_net_12": True,
        "aciklama": (
            "Kesin: STOK_MIKTAR a_id=1358 a_kod=8697393764057 + BELGE_SATIR aynı "
            "stok_id/kod. hareket_net=12 yalnız destekleyici."
            if (
                kart
                and str((kart or {}).get("a_kod") or "") == "8697393764057"
                and belgeler
            )
            else "Kart veya belge ilişkisi eksik — kesin sayılmaz"
        ),
    }


def main() -> int:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    esleme = json.loads(ESLEME.read_text(encoding="utf-8"))
    belge_kayitlar = esleme.get("belge_ile_kimlik", {}).get("kayitlar") or []
    ids_76 = sorted(
        {
            str(b["kaynak_stok_id"])
            for b in belge_kayitlar
            if not b.get("in_stok_miktar_3150") and b.get("kaynak_stok_id")
        }
    )
    # excel kod map
    kod_by_id: dict[str, str] = {}
    excel_by_id: dict[str, list] = defaultdict(list)
    for b in belge_kayitlar:
        if b.get("in_stok_miktar_3150"):
            continue
        sid = str(b.get("kaynak_stok_id") or "")
        if not sid:
            continue
        if b.get("kod"):
            kod_by_id[sid] = str(b["kod"])
        excel_by_id[sid].append(b)

    kimlik_yok = esleme.get("kimlik_yok") or []
    assert set(NEGATIF_IDS).issubset(set(ids_76)), "negatif ID'ler 76 kapsamında olmalı"

    client = EvobulutClient(load_credentials())
    client.login()

    # --- 76 kart + hareket ---
    kart_76: list[dict] = []
    detay_ozet: list[dict] = []
    with DETAY_JSONL.open("w", encoding="utf-8") as jf:
        for i, sid in enumerate(ids_76, 1):
            if i % 25 == 0:
                client.login()
            excel_kod = kod_by_id.get(sid)
            kart_bilgi = _kart_ara(client, sid, excel_kod)
            kart_76.append(
                {
                    **kart_bilgi,
                    "excel_kod": excel_kod,
                    "excel_satirlar": [
                        {
                            "excel_satir": x.get("excel_satir"),
                            "kalan": x.get("kalan"),
                            "birim": x.get("birim"),
                            "adi": x.get("adi"),
                        }
                        for x in excel_by_id.get(sid, [])
                    ],
                    "negatif_hedef": sid in NEGATIF_IDS,
                }
            )
            try:
                ham = client.stok_hareketleri(
                    sid, bas_tar=BAS_TAR, bit_tar=BIT_TAR, depo="0"
                )
            except Exception as exc:  # noqa: BLE001
                kayit = {
                    "kaynak_stok_id": sid,
                    "status": "ERR",
                    "hata": type(exc).__name__,
                    "mesaj": str(exc)[:200],
                }
                jf.write(json.dumps(kayit, ensure_ascii=False) + "\n")
                detay_ozet.append(kayit)
                time.sleep(0.02)
                continue
            kod = excel_kod or (kart_bilgi.get("kart") or {}).get("a_kod")
            adi = (kart_bilgi.get("kart") or {}).get("a_adi")
            if not adi and excel_by_id.get(sid):
                adi = excel_by_id[sid][0].get("adi")
            ozet = _hareket_ozet(sid, kod, adi, ham)
            # Excel kalan ile karşılaştır (gösterim hassasiyeti ayrı)
            for x in excel_by_id.get(sid, []):
                try:
                    ex = Decimal(str(x.get("kalan")))
                except Exception:
                    continue
                hn = Decimal(ozet["hareket_net"])
                ozet.setdefault("excel_karsilastirma", []).append(
                    {
                        "excel_satir": x.get("excel_satir"),
                        "excel_kalan": str(ex),
                        "hareket_net": str(hn),
                        "gosterim_hassasiyeti_esit": _q2(hn) == _q2(ex)
                        if ex == ex.quantize(KURUS)
                        else _q2(hn) == ex,
                        "ham_esit": hn == ex,
                    }
                )
            jf.write(json.dumps(ozet, ensure_ascii=False) + "\n")
            jf.flush()
            detay_ozet.append(
                {
                    "kaynak_stok_id": sid,
                    "status": "OK",
                    "kod": kod,
                    "hareket_adet": ozet["hareket_adet"],
                    "gir_toplam": ozet["gir_toplam"],
                    "cik_toplam": ozet["cik_toplam"],
                    "hareket_net": ozet["hareket_net"],
                    "depo_adet": ozet["depo_adet"],
                    "birim_adet": ozet["birim_adet"],
                    "devir_bayrakli_adet": ozet["devir_bayrakli_adet"],
                    "liste_kart": kart_bilgi.get("liste_bulundu"),
                    "sql_kart": kart_bilgi.get("sql_bulundu"),
                    "negatif_korundu": sid in NEGATIF_IDS,
                    "excel_karsilastirma": ozet.get("excel_karsilastirma"),
                }
            )
            if i % 10 == 0 or i == len(ids_76):
                print(f"76_cek {i}/{len(ids_76)}", flush=True)
            time.sleep(0.03)

    yaz_json(KART_76, {
        "format": "d1-stok-kart-76-belge-kimlik-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "adet": len(kart_76),
        "liste_bulunan": sum(1 for k in kart_76 if k.get("liste_bulundu")),
        "sql_bulunan": sum(1 for k in kart_76 if k.get("sql_bulundu")),
        "kayitlar": kart_76,
        "k05": False,
    })

    # --- 55 ara ---
    ara_55: list[dict] = []
    client.login()
    for i, row in enumerate(kimlik_yok, 1):
        if row.get("esleme_durum") != "KAYNAK_STOK_ID_BULUNAMADI":
            continue
        kod = str(row.get("kod") or "").strip()
        if not kod:
            ara_55.append({**row, "ara_durum": "BOS_KOD", "bulunan": []})
            continue
        if i % 20 == 0:
            client.login()
        try:
            exact = _exact_ara_kod(client, kod)
            # P-prefix: ara base de dene (birleştirme değil; alternatif birim kartı hipotezi)
            alt = []
            if kod.startswith("P") and len(kod) > 1:
                base = kod[1:]
                base_hits = _exact_ara_kod(client, base)
                alt = [
                    {
                        "a_id": h.get("a_id"),
                        "a_kod": h.get("a_kod"),
                        "ana_birim_adi": h.get("ana_birim_adi"),
                        "a_kalan": h.get("a_kalan"),
                        "aktif_pasif": h.get("aktif_pasif"),
                        "not": "P-önekli excel kodunun base kod exact listesi — ayrı kart hipotezi",
                    }
                    for h in base_hits
                ]
            bulunan = [
                {
                    "a_id": h.get("a_id"),
                    "a_kod": h.get("a_kod"),
                    "a_adi": h.get("a_adi"),
                    "ana_birim_adi": h.get("ana_birim_adi"),
                    "a_brm_id": h.get("a_brm_id"),
                    "a_kalan": h.get("a_kalan"),
                    "a_giren": h.get("a_giren"),
                    "a_cikan": h.get("a_cikan"),
                    "aktif_pasif": h.get("aktif_pasif"),
                }
                for h in exact
            ]
            # Exact tek hit → bağla
            bag = None
            if len(bulunan) == 1:
                bag = {
                    "kaynak_stok_id": str(bulunan[0]["a_id"]),
                    "kanit": "stok/base jq_list ara= + a_kod exact",
                    "kesin": True,
                }
            ara_55.append(
                {
                    "excel_satir": row.get("excel_satir"),
                    "kod": kod,
                    "adi": row.get("adi"),
                    "birim": row.get("birim"),
                    "kalan": row.get("kalan"),
                    "ara_durum": "BULUNDU" if bulunan else "LISTEDE_YOK_OTURUM",
                    "bulunan": bulunan,
                    "base_kod_alternatif": alt,
                    "baglanti": bag,
                    "dosyada_yok_kaynakta_yok_degil": True,
                }
            )
        except Exception as exc:  # noqa: BLE001
            ara_55.append(
                {
                    "excel_satir": row.get("excel_satir"),
                    "kod": kod,
                    "ara_durum": "ERR",
                    "hata": f"{type(exc).__name__}:{exc}"[:200],
                    "dosyada_yok_kaynakta_yok_degil": True,
                }
            )
        time.sleep(0.03)
        if i % 10 == 0 or i == len(kimlik_yok):
            print(f"55_ara {i}/{len(kimlik_yok)}", flush=True)

    yaz_json(ARA_55, {
        "format": "d1-stok-ara-55-kimlik-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "adet": len(ara_55),
        "bulunan": sum(1 for a in ara_55 if a.get("ara_durum") == "BULUNDU"),
        "listede_yok": sum(1 for a in ara_55 if a.get("ara_durum") == "LISTEDE_YOK_OTURUM"),
        "baglanan": sum(1 for a in ara_55 if (a.get("baglanti") or {}).get("kesin")),
        "kayitlar": ara_55,
        "k05": False,
    })

    # --- 1358 ---
    dogrulama_1358 = _belge_1358()
    # canlı hareket net destek
    try:
        hr1358 = client.stok_hareketleri("1358", bas_tar=BAS_TAR, bit_tar=BIT_TAR)
        o1358 = _hareket_ozet("1358", "8697393764057", None, hr1358)
        dogrulama_1358["canli_hareket_net"] = o1358["hareket_net"]
        dogrulama_1358["canli_hareket_adet"] = o1358["hareket_adet"]
    except Exception as exc:  # noqa: BLE001
        dogrulama_1358["canli_hata"] = str(exc)[:120]

    # --- 23 gösterim hassasiyeti (önceki kayıt) ---
    mf = (esleme.get("miktar_fark_23") or {}).get("kayitlar") or []
    gosterim = {
        "sinif": "EXCEL_GOSTERIM_HASSASIYETINDE_ESLESTI",
        "adet": len(mf),
        "aktarim_hatasiz_genellemesi_yok": True,
        "fifo_ham_hassasiyet_korunur": True,
        "aciklama": (
            "23 satırda q2(hareket_net) Excel kalan (2 ondalık) ile eşit. "
            "Bu gösterim hassasiyeti eşleşmesidir; tüm aktarımın hatasız olduğu "
            "sonucuna genişletilmez. FIFO katmanında ham miktar kullanılır."
        ),
    }

    # Negatif özet
    negatif_ozet = []
    for sid in sorted(NEGATIF_IDS):
        d = next((x for x in detay_ozet if x.get("kaynak_stok_id") == sid), None)
        negatif_ozet.append(
            {
                "kaynak_stok_id": sid,
                "excel_kod": kod_by_id.get(sid),
                "hareket": d,
                "korundu": True,
                "duzeltme_yok": True,
            }
        )

    # Sıfır maliyet / FIFO devam ipuçları
    sifir = esleme.get("sifir_maliyet_pozitif") or {}
    baglanan_ids = [
        str(a["baglanti"]["kaynak_stok_id"])
        for a in ara_55
        if (a.get("baglanti") or {}).get("kesin")
    ]

    kanit = {
        "format": "d1-stok-eksik-76-55-cek-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devir": 1,
        "kasa_banka_korundu": True,
        "yeni_maliyet_hesabi_baslatilmadi": True,
        "kapsam_76": {
            "adet": len(ids_76),
            "negatif_dahil": sorted(NEGATIF_IDS),
            "hareket_ok": sum(1 for d in detay_ozet if d.get("status") == "OK"),
            "hareket_err": sum(1 for d in detay_ozet if d.get("status") == "ERR"),
            "liste_kart_bulunan": sum(1 for k in kart_76 if k.get("liste_bulundu")),
            "sql_kart_bulunan": sum(1 for k in kart_76 if k.get("sql_bulundu")),
            "detay_jsonl": f"kaynak/{DETAY_JSONL.name}",
            "kart_json": f"kaynak/{KART_76.name}",
            "filtre": {"bas_tar": BAS_TAR, "bit_tar": BIT_TAR, "depo": "0"},
            "ozet": detay_ozet,
        },
        "kapsam_55": {
            "adet": len(ara_55),
            "bulunan": sum(1 for a in ara_55 if a.get("ara_durum") == "BULUNDU"),
            "listede_yok_oturum": sum(
                1 for a in ara_55 if a.get("ara_durum") == "LISTEDE_YOK_OTURUM"
            ),
            "baglanan_adet": len(baglanan_ids),
            "baglanan_ids": baglanan_ids,
            "ara_json": f"kaynak/{ARA_55.name}",
            "kural": "Mevcut dosyada yok = kaynakta yok değildir",
        },
        "dogrulama_1358": dogrulama_1358,
        "miktar_fark_23_gosterim": gosterim,
        "negatif_korunan": negatif_ozet,
        "sifir_maliyet_devam": {
            "onceki_sinif": sifir.get("sinif_sayac"),
            "kart_doldurma_yok": True,
            "sonraki": "Alış BELGE_SATIR eksik olanlar + yeni bağlanan 55 ID alış/giriş",
        },
        "fifo_lot_devam": {
            "76_detay_satir_hazir": True,
            "cikisli_katman": "DETAY jsonl gir_fiyat + sıra ile izole FIFO adayı",
            "lot_katman_maliyet": "Seri_Lot_List hâlâ birim maliyet yok — açık",
            "sonraki_filtre": {
                "StokHareket": "çıkışlı 3150 kartlar (özet yetersiz)",
                "Seri_Lot": "belge≤31.08.2026; katman birim maliyet ekran/Excel",
            },
        },
        "k05": False,
        "mali_yazim": False,
        "exe": False,
    }

    yol, sha = yaz_kaynak("DOGRULAMA_STOK_EKSIK_76_55_CEK", kanit)
    ozet = {
        "zaman": kanit["zaman"],
        "cekilen_76": len(ids_76),
        "hareket_ok": kanit["kapsam_76"]["hareket_ok"],
        "liste_kart": kanit["kapsam_76"]["liste_kart_bulunan"],
        "sql_kart": kanit["kapsam_76"]["sql_kart_bulunan"],
        "ara_55_bulunan": kanit["kapsam_55"]["bulunan"],
        "ara_55_baglanan": kanit["kapsam_55"]["baglanan_adet"],
        "kesin_1358": dogrulama_1358.get("kesin_esleme"),
        "gosterim_23": True,
        "negatif_ids": sorted(NEGATIF_IDS),
        "k05": False,
        "kanit": f"kaynak/{yol.name}",
        "sha16": sha[:16],
    }
    yaz_json(CALISMA / "STOK_EKSIK_76_55_OZET.json", ozet)

    if FIFO_KONTROL.is_file():
        try:
            fifo = json.loads(FIFO_KONTROL.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            fifo = {"tamamlanan": [], "engeller": []}
        fifo["stok_eksik_76_55"] = ozet
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
