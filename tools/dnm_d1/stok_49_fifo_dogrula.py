"""49 kalan liste + tam jq_list tarama + FIFO durum doğrulama/tekilleştirme.

76 hareket ve 6 kimlik yeniden toplanmaz.
K05 / maliyet hesabı / mali / EXE yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.stok_49_fifo_dogrula
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

import openpyxl

from tools.dnm_d1._ortak import CALISMA, KAYNAK, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.stok_envanter_excel_devir1 import tr_dec

BARKOD_FIFO = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_55_BARKOD_FIFO_DEVAM.json"
FIFO_IZOLE = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_FIFO_KATMAN_IZOLE.json"
DETAY_JSONL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_HAREKET_76_DETAY.jsonl"
ESLEME = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_ENVANTER_ESLEME_COZ.json"
EXCEL = KAYNAK / "excel" / "Stok_Envanter_FIFO_D1_20260831.xlsx"
FIFO_KONTROL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_FIFO_KASA_BANKA_POS_KONTROL.json"
LOT = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_LOT_KATMAN_DEVAM.json"
BELGE = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE_SATIR.jsonl"

KURUS = Decimal("0.01")


def _q2(v: Decimal) -> Decimal:
    return v.quantize(KURUS, rounding=ROUND_HALF_UP)


def _excel_by_satir() -> dict[int, dict]:
    wb = openpyxl.load_workbook(EXCEL, data_only=True)
    ws = wb.active
    out = {}
    for r in range(2, (ws.max_row or 0) + 1):
        tut = ws.cell(r, 11).value
        if isinstance(tut, str) and "toplam" in tut.lower():
            continue
        out[r] = {
            "kod": "" if ws.cell(r, 1).value is None else str(ws.cell(r, 1).value).strip(),
            "adi": ws.cell(r, 2).value,
            "giren": ws.cell(r, 6).value,
            "cikan": ws.cell(r, 7).value,
            "kalan": ws.cell(r, 8).value,
            "birim": ws.cell(r, 9).value,
            "birim_maliyet": ws.cell(r, 10).value,
            "tutar": tut,
        }
    return out


def _liste_49(barkod_kayitlar: list[dict], by_ex: dict[int, dict]) -> list[dict]:
    rows = []
    for x in barkod_kayitlar:
        ex = by_ex.get(int(x["excel_satir"]), {})
        kal = tr_dec(ex.get("kalan") if ex else x.get("kalan")) or Decimal("0")
        tut = tr_dec(ex.get("tutar")) or Decimal("0")
        bm = tr_dec(ex.get("birim_maliyet"))
        rows.append(
            {
                "excel_satir": x["excel_satir"],
                "kod": x.get("kod") or ex.get("kod"),
                "adi": x.get("adi") or ex.get("adi"),
                "birim": x.get("birim") or ex.get("birim"),
                "kalan": str(kal),
                "birim_maliyet": str(bm) if bm is not None else None,
                "tutar": str(tut),
                "giren": str(ex.get("giren")) if ex else None,
                "cikan": str(ex.get("cikan")) if ex else None,
                "pozitif": kal > 0,
                "oncelik_skor": float(tut) if kal > 0 else -1.0,
            }
        )
    rows.sort(key=lambda r: (-r["oncelik_skor"], r["excel_satir"]))
    for i, r in enumerate(rows, 1):
        r["arama_oncelik"] = i
        del r["oncelik_skor"]
    return rows


def _taram_jq_list(client: Any, hedef_kodlar: set[str]) -> dict[str, dict]:
    """Tüm jq_list sayfalarında a_kod exact — daha önce yapılmayan tarama."""
    bulunan: dict[str, dict] = {}
    sayfa = 0
    max_sayfa = 250
    toplam_kart = 0
    while sayfa < max_sayfa:
        if sayfa and sayfa % 40 == 0:
            client.login()
        sat, adet = client.stok_liste_sayfa(sayfa, ara="")
        if not sat:
            break
        toplam_kart += len(sat)
        for s in sat:
            kod = str(s.get("a_kod") or "").strip()
            if kod in hedef_kodlar and kod not in bulunan:
                bulunan[kod] = {
                    "kaynak_stok_id": str(s.get("a_id")),
                    "a_kod": kod,
                    "a_adi": s.get("a_adi"),
                    "ana_birim_adi": s.get("ana_birim_adi"),
                    "a_brm_id": s.get("a_brm_id"),
                    "a_kalan": s.get("a_kalan"),
                    "aktif_pasif": s.get("aktif_pasif"),
                    "kanit": f"stok/base jq_list tam sayfa tarama sayfa={sayfa} a_kod exact",
                    "kesin": True,
                }
        sayfa += 1
        if adet and toplam_kart >= int(adet):
            break
        if len(sat) < 30 and sayfa > 1:
            # son sayfa olabilir
            if sayfa > (int(adet) // 30 + 3 if adet else sayfa):
                break
        time.sleep(0.02)
        if sayfa % 20 == 0:
            print(f"tarama sayfa={sayfa} kart={toplam_kart} bulunan={len(bulunan)}", flush=True)
    return {
        "_meta": {"sayfa": sayfa, "kart_tarandi": toplam_kart, "bulunan_adet": len(bulunan)},
        **{k: v for k, v in bulunan.items()},
    }


def _barkod_alt_birim_tara(client: Any, bulunan_ids: list[str], hedef_kodlar: set[str]) -> list[dict]:
    """Bilinen kartların Barkod[] / Birimler[] içinde 49 kodu ara (alternatif barkod)."""
    hits = []
    # Örneklem: yeni bağlanan + rastgele yüksek id değil — yalnızca hedef için sql barkod zaten denendi.
    # Alternatif: her bulunan_ids için Barkod listesi çek (küçük)
    for i, sid in enumerate(bulunan_ids[:30], 1):
        y = client._post(
            "stok/base/",
            {"cmd": "sql", "UID": client.uid, "a_stok_id": sid, "grupgetir": "1", "a_barkod": ""},
        )
        veri = y.get("veri") or {}
        if not isinstance(veri, dict):
            continue
        for b in veri.get("Barkod") or []:
            bn = str(b.get("a_barkod_no") or "").strip()
            if bn in hedef_kodlar:
                hits.append(
                    {
                        "excel_kod_barkod": bn,
                        "kaynak_stok_id": sid,
                        "a_brm_id": b.get("a_brm_id"),
                        "Brm_Adi": b.get("Brm_Adi"),
                        "a_carpan": b.get("a_carpan"),
                        "kanit": "stok sql Barkod[].a_barkod_no exact",
                    }
                )
        time.sleep(0.02)
    return hits


def _excel_by_kod(by_ex: dict[int, dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for r, v in by_ex.items():
        kod = v.get("kod") or ""
        if not kod:
            continue
        out[kod].append(
            {
                "excel_satir": r,
                "kalan": str(tr_dec(v.get("kalan")) or 0),
                "birim": v.get("birim"),
                "birim_maliyet": str(tr_dec(v.get("birim_maliyet")))
                if v.get("birim_maliyet") is not None
                else None,
                "tutar": str(tr_dec(v.get("tutar")) or 0),
            }
        )
    return out


def _dogrula_fifo(
    fifo_kayitlar: list[dict], excel_kod: dict[str, list[dict]], prev_28_ids: set[str]
) -> dict:
    """Durum tanımları + miktar/değer doğrulama; kimlik tekilleştirme."""
    tanimlar = {
        "FIFO_IZOLE_DETAY": (
            "Hareket satır detayından FIFO tüketim sonrası kalan katmanların tümünde "
            "gir_fiyat kanıtlı (KANITLI); katman miktar toplamı tarihli hareket_net ile "
            "eşit (negatif hariç). Kart/ortalama maliyet kullanılmadı."
        ),
        "FIFO_KATMAN_KURULDU": (
            "Katman kuyruğu kuruldu ancak doğrulanmış sayılmaz: miktar net ile uyumsuz "
            "olabilir, bedelsiz/bilinmeyen maliyet karışık olabilir veya değer kanıtı eksik. "
            "Eksik maliyet/belge varken doğrulanmış FIFO sayılmaz."
        ),
        "NEGATIF_KORUNDU": "hareket_net<0; katman uydurulmaz, negatif korunur.",
        "HAREKET_YOK": "Dönem içi giriş/çıkış satırı yok.",
    }

    dogrulanan = []
    katman_kuruldu_ham = []
    for f in fifo_kayitlar:
        sid = str(f.get("kaynak_stok_id"))
        durum = f.get("durum")
        net = tr_dec(f.get("hareket_net")) or Decimal("0")
        kat_mik = tr_dec(f.get("kalan_miktar_katman")) or Decimal("0")
        fifo_top = tr_dec(f.get("fifo_toplam_izole"))
        kod = str(f.get("kod") or "")
        ex_rows = excel_kod.get(kod) or []
        # birim eşleşen excel satırı
        ex = ex_rows[0] if len(ex_rows) == 1 else None
        if ex is None and ex_rows:
            # çoklu: miktar yakın olan
            for e in ex_rows:
                if abs((tr_dec(e["kalan"]) or 0) - net) < Decimal("0.0001") or _q2(
                    tr_dec(e["kalan"]) or 0
                ) == _q2(net):
                    ex = e
                    break
            if ex is None:
                ex = ex_rows[0]

        miktar_ok = abs(kat_mik - max(net, Decimal("0"))) <= Decimal("0.0001") if net >= 0 else False
        deger_ok = None
        deger_not = None
        if ex and fifo_top is not None and durum == "FIFO_IZOLE_DETAY":
            ex_tut = tr_dec(ex.get("tutar")) or Decimal("0")
            # gösterim hassasiyeti ile kıyas; ham fark ayrı
            deger_ok = _q2(fifo_top) == _q2(ex_tut)
            deger_not = {
                "excel_tutar": str(ex_tut),
                "fifo_toplam_izole": str(fifo_top),
                "gosterim_q2_esit": deger_ok,
                "ham_esit": fifo_top == ex_tut,
                "yontem": "Excel FIFO envanter (31.08) vs hareket gir_fiyat FIFO",
            }
        elif durum == "FIFO_IZOLE_DETAY" and fifo_top is None:
            deger_ok = False
            deger_not = {"neden": "fifo_toplam yok"}

        # Doğrulanmış mı?
        dogrulanmis = (
            durum == "FIFO_IZOLE_DETAY"
            and miktar_ok
            and deger_ok is True
            and not any(
                (k.get("maliyet_sinif") in ("BILINMEYEN", None))
                for k in (f.get("katmanlar") or [])
            )
        )
        # katmanlarda belge yoksa
        belgesiz = any(
            not k.get("kaynak_belge_id") for k in (f.get("katmanlar") or [])
        )
        if belgesiz and durum == "FIFO_IZOLE_DETAY":
            dogrulanmis = False

        kayit = {
            **{kk: f[kk] for kk in f if kk != "katmanlar"},
            "katman_adet": f.get("katman_adet"),
            "miktar_katman_vs_hareket_net_ok": miktar_ok if net >= 0 else None,
            "deger_vs_excel_envanter": deger_not,
            "dogrulanmis_fifo": dogrulanmis,
            "onceki_alis_only_28_ile_ayni_id": sid in prev_28_ids,
            "excel_satir": (ex or {}).get("excel_satir"),
        }
        if durum == "FIFO_IZOLE_DETAY":
            dogrulanan.append(kayit)
        elif durum == "FIFO_KATMAN_KURULDU":
            katman_kuruldu_ham.append(
                {
                    **kayit,
                    "dogrulanmis_fifo": False,
                    "neden_dogrulanmadi": (
                        "Katman kuruldu etiketi otomatik doğrulama değildir; "
                        "miktar/değer/maliyet eksği olabilir"
                    ),
                }
            )

    # tekilleştir: önceki 28 alış-only ile kesişim
    id_76 = {str(f["kaynak_stok_id"]) for f in fifo_kayitlar}
    tekil = {
        "onceki_FIFO_IZOLE_TAM_alis_only_28": len(prev_28_ids),
        "bu_cek_FIFO_IZOLE_DETAY_ham": sum(
            1 for f in fifo_kayitlar if f.get("durum") == "FIFO_IZOLE_DETAY"
        ),
        "bu_cek_FIFO_KATMAN_KURULDU_ham": sum(
            1 for f in fifo_kayitlar if f.get("durum") == "FIFO_KATMAN_KURULDU"
        ),
        "kesişim_onceki_28": len(prev_28_ids & id_76),
        "FIFO_IZOLE_DETAY_dogrulanmis_deger_miktar": sum(
            1 for d in dogrulanan if d.get("dogrulanmis_fifo")
        ),
        "FIFO_IZOLE_DETAY_miktar_ok_deger_uyusmaz_veya_eksik": sum(
            1 for d in dogrulanan if not d.get("dogrulanmis_fifo")
        ),
        "birlesik_tekil_dogrulanmis_stok_id": len(
            {d["kaynak_stok_id"] for d in dogrulanan if d.get("dogrulanmis_fifo")}
            | set()  # prev 28 ayrı doğrulama kanıtında; buraya karıştırma değer
        ),
        "not": (
            "Önceki 28 alış-only izole ile bu 76+6 detay kümesi kimlik kesişimi 0; "
            "sayılar toplanırken çift sayılmamalı — ayrı kovalar."
        ),
    }

    return {
        "tanimlar": tanimlar,
        "tekillestirme": tekil,
        "FIFO_IZOLE_DETAY_inceleme": dogrulanan,
        "FIFO_KATMAN_KURULDU_inceleme": katman_kuruldu_ham[:80],
        "FIFO_KATMAN_KURULDU_adet": len(katman_kuruldu_ham),
    }


def main() -> int:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    barkod = json.loads(BARKOD_FIFO.read_text(encoding="utf-8"))
    by_ex = _excel_by_satir()
    liste49 = _liste_49(barkod.get("barkod_sql_49", {}).get("kayitlar") or [], by_ex)
    hedef = {str(r["kod"]) for r in liste49 if r.get("kod")}

    client = EvobulutClient(load_credentials())
    client.login()

    print("jq_list tam tarama basliyor...", flush=True)
    tarama = _taram_jq_list(client, hedef)
    meta = tarama.pop("_meta")
    baglanan_tarama = []
    for kod, info in tarama.items():
        row = next((r for r in liste49 if r["kod"] == kod), None)
        baglanan_tarama.append({**(row or {}), "baglanti": info})

    # Alternatif barkod: 6 yeni + birkaç bilinen id üzerinde Barkod[] (sınırlı)
    ara55 = json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_ARA_55_KIMLIK.json").read_text(encoding="utf-8"))
    bilinen_ids = [
        str((a.get("baglanti") or {}).get("kaynak_stok_id"))
        for a in ara55.get("kayitlar") or []
        if (a.get("baglanti") or {}).get("kaynak_stok_id")
    ]
    # Ayrıca 76 detaydan P-kart id'leri — barkod listesi genelde sql bulamıyor; atla ağır çekim
    alt_barkod = _barkod_alt_birim_tara(client, bilinen_ids, hedef)

    # Yeni bulunanlar için hareket (yalnız yeni id; 76/6 tekrar yok)
    mevcut_detay_ids = set()
    if DETAY_JSONL.is_file():
        with DETAY_JSONL.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    o = json.loads(line)
                    mevcut_detay_ids.add(str(o.get("kaynak_stok_id")))

    yeni_hareket = []
    from tools.dnm_d1.stok_eksik_76_55_cek import _hareket_ozet

    for b in baglanan_tarama:
        sid = str(b["baglanti"]["kaynak_stok_id"])
        if sid in mevcut_detay_ids:
            continue
        client.login()
        ham = client.stok_hareketleri(
            sid, bas_tar="01.01.2015", bit_tar="31.08.2026", depo="0"
        )
        ozet = _hareket_ozet(sid, b.get("kod"), b.get("adi"), ham)
        ozet["grup"] = "kimlik_49_jq_list_tarama"
        with DETAY_JSONL.open("a", encoding="utf-8") as jf:
            jf.write(json.dumps(ozet, ensure_ascii=False) + "\n")
        yeni_hareket.append(
            {
                "kaynak_stok_id": sid,
                "kod": b.get("kod"),
                "hareket_net": ozet["hareket_net"],
                "hareket_adet": ozet["hareket_adet"],
            }
        )
        mevcut_detay_ids.add(sid)

    # FIFO doğrulama
    prev = json.loads(FIFO_IZOLE.read_text(encoding="utf-8")) if FIFO_IZOLE.is_file() else {}
    prev_ids = {str(x["kaynak_stok_id"]) for x in (prev.get("fifo_izole_kayitlar") or [])}
    excel_kod = _excel_by_kod(by_ex)
    fifo_dogrula = _dogrula_fifo(
        barkod.get("fifo_76_detay", {}).get("kayitlar") or [], excel_kod, prev_ids
    )

    # Sıfır maliyet / LOT durumu
    esleme = json.loads(ESLEME.read_text(encoding="utf-8")) if ESLEME.is_file() else {}
    sifir = (esleme.get("sifir_maliyet_pozitif") or {}).get("kayitlar") or []
    lot = json.loads(LOT.read_text(encoding="utf-8")) if LOT.is_file() else {}

    kalan_kodlar = [
        r
        for r in liste49
        if r["kod"] not in tarama and not any(h.get("excel_kod_barkod") == r["kod"] for h in alt_barkod)
    ]

    kanit = {
        "format": "d1-stok-49-fifo-dogrula-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devir": 1,
        "yeniden_toplanmadi": {
            "stok_76_hareket": True,
            "kimlik_6": True,
        },
        "kasa_banka_degistirilmedi": True,
        "liste_49": {
            "adet": len(liste49),
            "pozitif": sum(1 for r in liste49 if r["pozitif"]),
            "sifir": sum(1 for r in liste49 if not r["pozitif"]),
            "tutar_pozitif_toplam": str(
                sum((tr_dec(r["tutar"]) or 0 for r in liste49 if r["pozitif"]), Decimal(0))
            ),
            "kayitlar_oncelikli": liste49,
            "alanlar": [
                "kod",
                "adi",
                "birim",
                "kalan",
                "birim_maliyet",
                "tutar",
            ],
        },
        "yeni_arama": {
            "jq_list_tam_sayfa_tarama": meta,
            "bulunan_exact_kod": len(tarama),
            "baglanan": baglanan_tarama,
            "alternatif_barkod_hit": alt_barkod,
            "onceki_basarisiz_tekrarlanmadi": [
                "jq_list ara=tam kod (tek sayfa)",
                "barkod sql tek tek (49)",
                "pasif param jq_list",
            ],
            "yeni_yontemler": [
                "jq_list ara='' tüm sayfa a_kod exact tarama",
                "bilinen kart Barkod[] alternatif barkod",
            ],
        },
        "yeni_hareket_yalniz_yeni_id": yeni_hareket,
        "fifo_durum_dogrulama": fifo_dogrula,
        "sifir_maliyet_devam": {
            "adet": len(sifir),
            "sinif_ozet": dict(Counter(s.get("sinif") for s in sifir)),
            "kart_doldurma_yok": True,
            "gerekli_ekran_cozulemeyen": {
                "ekran": "Stok kartı → Hareket / Alış belgeleri veya Fatura alış satırı",
                "filtre": "stok_id; belge tarihi ≤31.08.2026; tur alış",
                "sutunlar": [
                    "tarih",
                    "belge_id/tur",
                    "miktar",
                    "birim",
                    "birim_fiyat",
                    "depo",
                ],
                "kullanici_beklerken_diger_isler_durmaz": True,
            },
        },
        "lot_maliyet_devam": {
            "mevcut": {
                "kanit": LOT.name if LOT.is_file() else None,
                "katman_maliyet": (lot.get("katman_maliyet") or {}).get("durum"),
                "lot_olay": lot.get("lot_olay_adet"),
            },
            "gerekli_ekran": {
                "ekran": "Fatura/irsaliye detay → Seri/LOT listesi veya stok LOT raporu",
                "filtre": {
                    "belge_tarihi": "≤31.08.2026",
                    "stok_id": "FIFO doğrulanmamış / LOT’lu kartlar",
                },
                "sutunlar": [
                    "lot_no/lot_id",
                    "özgün giriş tarihi",
                    "giren",
                    "çıkan",
                    "kalan",
                    "katman birim maliyet (zorunlu — API’de yok)",
                    "belge_id",
                ],
                "kullanici_beklerken_diger_isler_durmaz": True,
            },
        },
        "kalan_49_cozulemeyen": {
            "adet": len(kalan_kodlar),
            "kaynakta_yok_kesin_degil": True,
            "kayitlar": kalan_kodlar,
            "gerekli_ekran": {
                "ekran": "31.08.2026 FIFO stok envanter raporu satır drill-down → stok kartı",
                "filtre": {
                    "rapor_tarihi": "31.08.2026",
                    "maliyet_yontemi": "FIFO",
                    "maliyet_hesabi_tarihi": "31.08.2026",
                    "kod_listesi": [r["kod"] for r in kalan_kodlar],
                    "aktif_pasif": "Tümü + Arşiv/Silinmiş (UI)",
                },
                "sutunlar": [
                    "stok_id",
                    "kod",
                    "barkod(lar)",
                    "birim+çarpan",
                    "kalan",
                    "birim maliyet",
                    "tutar",
                    "aktif/pasif",
                ],
            },
        },
        "k05": False,
        "mali_yazim": False,
        "exe": False,
        "yeni_maliyet_hesabi_baslatilmadi": True,
    }

    yol, sha = yaz_kaynak("DOGRULAMA_STOK_49_FIFO_DOGRULA", kanit)
    ozet = {
        "zaman": kanit["zaman"],
        "liste_49": len(liste49),
        "pozitif_49": kanit["liste_49"]["pozitif"],
        "tarama_bulunan": len(tarama),
        "kalan_cozulemeyen": len(kalan_kodlar),
        "fifo_izole_detay_ham": fifo_dogrula["tekillestirme"]["bu_cek_FIFO_IZOLE_DETAY_ham"],
        "fifo_izole_dogrulanmis": fifo_dogrula["tekillestirme"][
            "FIFO_IZOLE_DETAY_dogrulanmis_deger_miktar"
        ],
        "fifo_katman_kuruldu_ham": fifo_dogrula["tekillestirme"][
            "bu_cek_FIFO_KATMAN_KURULDU_ham"
        ],
        "fifo_katman_kuruldu_dogrulanmis": 0,
        "kesisim_onceki_28": fifo_dogrula["tekillestirme"]["kesişim_onceki_28"],
        "k05": False,
        "kanit": f"kaynak/{yol.name}",
        "sha16": sha[:16],
    }
    yaz_json(CALISMA / "STOK_49_FIFO_DOGRULA_OZET.json", ozet)

    if FIFO_KONTROL.is_file():
        try:
            fifo = json.loads(FIFO_KONTROL.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            fifo = {}
        fifo["stok_49_fifo_dogrula"] = ozet
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
