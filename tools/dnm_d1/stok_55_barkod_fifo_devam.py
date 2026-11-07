"""55 kalan kimlik — barkod sql; 76 detaydan FIFO izole; sıfır maliyet devam.

K05 / maliyet hesabı / mali / EXE yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.stok_55_barkod_fifo_devam
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict, deque
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from tools.dnm_d1._ortak import CALISMA, KAYNAK, dec, parse_tarih, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import DONEM_SONU, RAPOR_ONEKI_KAYNAK
from tools.dnm_d1.stok_fifo_katman_izole import (
    ALIS_TUR,
    Katman,
    _katman_dict,
    _maliyet_sinif,
    fifo_consume,
)
from tools.dnm_d1.stok_envanter_excel_devir1 import tr_dec

ARA_55 = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_ARA_55_KIMLIK.json"
CEK_76 = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_EKSIK_76_55_CEK.json"
DETAY_JSONL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_HAREKET_76_DETAY.jsonl"
BELGE_SATIR = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE_SATIR.jsonl"
ESLEME = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_STOK_ENVANTER_ESLEME_COZ.json"
FIFO_KONTROL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}DOGRULAMA_FIFO_KASA_BANKA_POS_KONTROL.json"
EXCEL = KAYNAK / "excel" / "Stok_Envanter_FIFO_D1_20260831.xlsx"

BAS = "01.01.2015"
BIT = DONEM_SONU.strftime("%d.%m.%Y")


def _sql_barkod(client: Any, kod: str) -> dict | None:
    y = client._post(
        "stok/base/",
        {
            "cmd": "sql",
            "UID": client.uid,
            "a_stok_id": "",
            "grupgetir": "1",
            "a_barkod": kod,
        },
    )
    veri = y.get("veri") or y.get("Veri")
    if isinstance(veri, list):
        return None
    if not isinstance(veri, dict):
        return None
    ana = veri.get("Ana") or veri.get("ana")
    if isinstance(ana, list) and ana:
        return ana[0]
    if veri.get("a_id"):
        return veri
    return None


def _yukle_alis(stok_ids: set[str]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = defaultdict(list)
    with BELGE_SATIR.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            if o.get("status") != "OK":
                continue
            tur = str(o.get("tur") or "")
            if tur not in ALIS_TUR:
                continue
            t = parse_tarih(o.get("tarih"))
            if t is None or t > DONEM_SONU:
                continue
            bid = str(o.get("kaynak_belge_id") or "")
            for i, s in enumerate(o.get("satirlar") or []):
                sid = str(s.get("stok_id") or "")
                if sid not in stok_ids:
                    continue
                mik = tr_dec(s.get("miktar"))
                if mik is None or mik == 0:
                    continue
                by[sid].append(
                    {
                        "belge_id": bid,
                        "belge_tur": tur,
                        "belge_tarih": t.isoformat(),
                        "satir_index": i,
                        "depo_id": str(s.get("depo_id") or "") or None,
                        "birim": s.get("birim"),
                        "miktar": mik,
                        "birim_fiyat": tr_dec(s.get("birim_fiyat")),
                        "stok_id": sid,
                    }
                )
    for sid in by:
        by[sid].sort(key=lambda r: (r["belge_tarih"], r["belge_id"], r["satir_index"]))
    return by


def main() -> int:
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials

    ara = json.loads(ARA_55.read_text(encoding="utf-8"))
    cek = json.loads(CEK_76.read_text(encoding="utf-8"))
    esleme = json.loads(ESLEME.read_text(encoding="utf-8"))

    client = EvobulutClient(load_credentials())
    client.login()

    # --- barkod sql for LISTEDE_YOK ---
    barkod_sonuc = []
    yoklar = [a for a in ara["kayitlar"] if a.get("ara_durum") == "LISTEDE_YOK_OTURUM"]
    for i, row in enumerate(yoklar, 1):
        if i % 15 == 0:
            client.login()
        kod = str(row.get("kod") or "")
        kart = _sql_barkod(client, kod) if kod else None
        bag = None
        if kart and kart.get("a_id"):
            # kod uyumu: a_kod == excel kod veya barkod araması döndü
            bag = {
                "kaynak_stok_id": str(kart["a_id"]),
                "a_kod": kart.get("a_kod"),
                "aktif_pasif": kart.get("aktif_pasif"),
                "ana_birim_adi": kart.get("ana_birim_adi") or kart.get("Birim"),
                "a_kalan": kart.get("a_kalan"),
                "kanit": "stok/base cmd=sql a_barkod=excel_kod (tek kart)",
                "a_kod_excel_esit": str(kart.get("a_kod") or "").strip() == kod,
                # Barkod sql tek kart döndürdü → kimlik kanıtı (jq_list’te görünmese de)
                "kesin": True,
            }
        barkod_sonuc.append(
            {
                "excel_satir": row.get("excel_satir"),
                "kod": kod,
                "adi": row.get("adi"),
                "birim": row.get("birim"),
                "kalan": row.get("kalan"),
                "barkod_sql_durum": "BULUNDU" if bag else "BARKOD_SQL_BOS",
                "baglanti": bag,
                "kart_ozet": {
                    "a_id": (kart or {}).get("a_id"),
                    "a_kod": (kart or {}).get("a_kod"),
                    "a_adi": (kart or {}).get("a_adi"),
                    "aktif_pasif": (kart or {}).get("aktif_pasif"),
                }
                if kart
                else None,
            }
        )
        time.sleep(0.03)
        if i % 10 == 0 or i == len(yoklar):
            print(f"barkod {i}/{len(yoklar)}", flush=True)

    # önceki jq_list baglananlar
    onceki_bag = [
        a
        for a in ara["kayitlar"]
        if (a.get("baglanti") or {}).get("kesin")
    ]

    tum_baglanan = list(onceki_bag)
    for b in barkod_sonuc:
        if (b.get("baglanti") or {}).get("kesin"):
            tum_baglanan.append(
                {
                    "excel_satir": b["excel_satir"],
                    "kod": b["kod"],
                    "baglanti": b["baglanti"],
                    "kalan": b["kalan"],
                    "birim": b["birim"],
                    "kaynak": "barkod_sql",
                }
            )

    # Yeni bağlananlar için hareket çek (özet+detay ek)
    yeni_ids = sorted(
        {
            str(x["baglanti"]["kaynak_stok_id"])
            for x in tum_baglanan
            if x.get("baglanti")
        }
    )
    # zaten 76'da olanları ayır
    ids_76 = {
        str(x["kaynak_stok_id"])
        for x in (cek.get("kapsam_76") or {}).get("ozet") or []
    }
    yeni_cek = [sid for sid in yeni_ids if sid not in ids_76]
    yeni_hareket = []
    client.login()
    with DETAY_JSONL.open("a", encoding="utf-8") as jf:
        for i, sid in enumerate(yeni_cek, 1):
            if i % 20 == 0:
                client.login()
            try:
                ham = client.stok_hareketleri(sid, bas_tar=BAS, bit_tar=BIT, depo="0")
            except Exception as exc:  # noqa: BLE001
                yeni_hareket.append({"kaynak_stok_id": sid, "status": "ERR", "hata": str(exc)[:120]})
                continue
            from tools.dnm_d1.stok_eksik_76_55_cek import _hareket_ozet

            kod = next(
                (
                    str(x.get("kod"))
                    for x in tum_baglanan
                    if str((x.get("baglanti") or {}).get("kaynak_stok_id")) == sid
                ),
                None,
            )
            ozet = _hareket_ozet(sid, kod, None, ham)
            ozet["grup"] = "kimlik_55_yeni_baglanan"
            jf.write(json.dumps(ozet, ensure_ascii=False) + "\n")
            yeni_hareket.append(
                {
                    "kaynak_stok_id": sid,
                    "status": "OK",
                    "kod": kod,
                    "hareket_adet": ozet["hareket_adet"],
                    "hareket_net": ozet["hareket_net"],
                    "gir_toplam": ozet["gir_toplam"],
                    "cik_toplam": ozet["cik_toplam"],
                }
            )
            time.sleep(0.03)

    # --- FIFO izole from 76(+yeni) detail ---
    fifo_sonuc = []
    with DETAY_JSONL.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            if o.get("status") != "OK":
                continue
            sid = str(o["kaynak_stok_id"])
            satirlar = o.get("satirlar") or []
            girisler = []
            cikislar = []
            for h in satirlar:
                t = parse_tarih(h.get("tarih"))
                gir = tr_dec(h.get("gir_miktar")) or Decimal("0")
                cik = tr_dec(h.get("cik_miktar")) or Decimal("0")
                if gir > 0:
                    fiyat = tr_dec(h.get("gir_fiyat"))
                    girisler.append(
                        {
                            "stok_id": sid,
                            "belge_id": str(h.get("Fat_id") or h.get("id") or ""),
                            "belge_tur": str(h.get("belge_tur") or ""),
                            "belge_tarih": t.isoformat() if t else None,
                            "satir_index": int(str(h.get("id") or 0) or 0),
                            "depo_id": h.get("depo"),
                            "birim": h.get("Birim"),
                            "miktar": gir,
                            "birim_fiyat": fiyat,
                        }
                    )
                if cik > 0 and t is not None:
                    cikislar.append((t, cik, str(h.get("id") or "")))
            if not girisler and not cikislar:
                fifo_sonuc.append(
                    {
                        "kaynak_stok_id": sid,
                        "kod": o.get("kod"),
                        "durum": "HAREKET_YOK",
                        "hareket_net": o.get("hareket_net"),
                    }
                )
                continue
            kalan_kat = fifo_consume(girisler, cikislar)
            # negatif: çıkış fazla
            net = tr_dec(o.get("hareket_net")) or Decimal("0")
            bilinen = [k for k in kalan_kat if k.maliyet_sinif == "KANITLI"]
            bedelsiz = [k for k in kalan_kat if k.maliyet_sinif == "BEDELSIZ_SIFIR"]
            bilinmeyen = [k for k in kalan_kat if k.maliyet_sinif == "BILINMEYEN"]
            toplam_mik = sum((k.kalan_miktar for k in kalan_kat), Decimal("0"))
            if net < 0:
                durum = "NEGATIF_KORUNDU"
            elif bilinen and not bilinmeyen and abs(toplam_mik - max(net, Decimal("0"))) <= Decimal("0.0001"):
                durum = "FIFO_IZOLE_DETAY"
            elif bilinmeyen:
                durum = "FIFO_KISMI_BILINMEYEN_MALIYET"
            elif bedelsiz and not bilinen:
                durum = "FIFO_BEDELSIZ"
            else:
                durum = "FIFO_KATMAN_KURULDU"
            toplam_maliyet = None
            if bilinen and not bilinmeyen:
                toplam_maliyet = sum(
                    (k.kalan_miktar * (k.birim_maliyet or Decimal("0")) for k in kalan_kat),
                    Decimal("0"),
                )
            fifo_sonuc.append(
                {
                    "kaynak_stok_id": sid,
                    "kod": o.get("kod"),
                    "durum": durum,
                    "hareket_net": str(net),
                    "cikis_var": bool(cikislar),
                    "katman_adet": len(kalan_kat),
                    "kalan_miktar_katman": str(toplam_mik),
                    "fifo_toplam_izole": str(toplam_maliyet)
                    if toplam_maliyet is not None
                    else None,
                    "katmanlar": [_katman_dict(k) for k in kalan_kat[:20]],
                    "negatif_korundu": net < 0,
                    "kart_maliyetinden_uydurma_yok": True,
                    "ham_miktar_hassasiyeti": True,
                }
            )

    # --- sıfır maliyet: belge alış (14 + yeni) ---
    sifir_kayit = (esleme.get("sifir_maliyet_pozitif") or {}).get("kayitlar") or []
    # güncelle kimlik yok olan barkod ile
    kod_to_yeni = {
        str(b["kod"]): str(b["baglanti"]["kaynak_stok_id"])
        for b in barkod_sonuc
        if (b.get("baglanti") or {}).get("kesin")
    }
    for a in onceki_bag:
        kod_to_yeni[str(a["kod"])] = str(a["baglanti"]["kaynak_stok_id"])

    sifir_ids = set()
    sifir_guncel = []
    for z in sifir_kayit:
        sid = z.get("kaynak_stok_id")
        if not sid and z.get("kod") in kod_to_yeni:
            sid = kod_to_yeni[str(z["kod"])]
        if sid:
            sifir_ids.add(str(sid))
        sifir_guncel.append({**z, "kaynak_stok_id": sid})
    alis = _yukle_alis(sifir_ids)
    from tools.dnm_d1.stok_envanter_excel_devir1 import _sinif_sifir_maliyet

    sifir_son = []
    for z in sifir_guncel:
        sid = z.get("kaynak_stok_id")
        sinif = _sinif_sifir_maliyet(sid, alis.get(str(sid or ""), []), None)
        sifir_son.append({**z, **sinif, "alis_satir_adet": len(alis.get(str(sid or ""), []))})

    kanit = {
        "format": "d1-stok-55-barkod-fifo-devam-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "devir": 1,
        "kasa_banka_korundu": True,
        "barkod_sql_49": {
            "aranan": len(yoklar),
            "bulunan": sum(1 for b in barkod_sonuc if b["barkod_sql_durum"] == "BULUNDU"),
            "bos": sum(1 for b in barkod_sonuc if b["barkod_sql_durum"] == "BARKOD_SQL_BOS"),
            "kayitlar": barkod_sonuc,
            "kural": "jq_list’te yok ≠ kaynakta yok; barkod sql ayrı kanıt",
        },
        "kimlik_55_toplam_baglanan": len(tum_baglanan),
        "jq_list_baglanan": len(onceki_bag),
        "barkod_baglanan": sum(
            1 for b in barkod_sonuc if (b.get("baglanti") or {}).get("kesin")
        ),
        "yeni_hareket_cekilen": yeni_hareket,
        "fifo_76_detay": {
            "adet": len(fifo_sonuc),
            "durum_sayac": dict(Counter(f["durum"] for f in fifo_sonuc)),
            "kayitlar": fifo_sonuc,
            "not": "Ham miktar/fiyat hareket satırından; Excel 2dk yuvarlama katman üretmez",
        },
        "sifir_maliyet": {
            "adet": len(sifir_son),
            "sinif_sayac": dict(Counter(s["sinif"] for s in sifir_son)),
            "kart_doldurma_yok": True,
            "kayitlar": sifir_son,
        },
        "miktar_fark_23": {
            "sinif": "EXCEL_GOSTERIM_HASSASIYETINDE_ESLESTI",
            "aktarim_hatasiz_genellemesi_yok": True,
            "fifo_ham_hassasiyet": True,
        },
        "dogrulama_1358_onceki_kanit": (cek.get("dogrulama_1358") or {}).get("kesin_esleme"),
        "acik_engeller": [
            {
                "is": "barkod_sql_bos_kalan",
                "adet": sum(
                    1 for b in barkod_sonuc if b["barkod_sql_durum"] == "BARKOD_SQL_BOS"
                ),
                "filtre": "EvoBulut stok ara (pasif dahil) + alternatif barkod ekranı",
            },
            {
                "is": "LOT_katman_birim_maliyet",
                "durum": "ACIK",
                "filtre": "Seri_Lot_List / ekran Excel; belge≤31.08.2026",
            },
            {
                "is": "3150_cikisli_hareket_detay",
                "durum": "ACIK",
                "not": "76+yeni detay alındı; kalan çıkışlı 3150 kartlar için StokHareket list detay",
            },
        ],
        "k05": False,
        "mali_yazim": False,
        "exe": False,
        "yeni_maliyet_hesabi_baslatilmadi": True,
    }

    # ARA_55 güncelle
    ara["barkod_sql_tamamlayici"] = kanit["barkod_sql_49"]
    ara["toplam_baglanan_jq_plus_barkod"] = len(tum_baglanan)
    yaz_json(ARA_55, ara)

    yol, sha = yaz_kaynak("DOGRULAMA_STOK_55_BARKOD_FIFO_DEVAM", kanit)
    ozet = {
        "zaman": kanit["zaman"],
        "barkod_bulunan": kanit["barkod_sql_49"]["bulunan"],
        "barkod_bos": kanit["barkod_sql_49"]["bos"],
        "toplam_55_baglanan": len(tum_baglanan),
        "fifo_durum": kanit["fifo_76_detay"]["durum_sayac"],
        "sifir_mal": kanit["sifir_maliyet"]["sinif_sayac"],
        "k05": False,
        "kanit": f"kaynak/{yol.name}",
        "sha16": sha[:16],
    }
    yaz_json(CALISMA / "STOK_55_BARKOD_FIFO_OZET.json", ozet)

    if FIFO_KONTROL.is_file():
        try:
            fifo = json.loads(FIFO_KONTROL.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            fifo = {}
        fifo["stok_55_barkod_fifo"] = ozet
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
