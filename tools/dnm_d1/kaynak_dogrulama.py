"""DNM D1 kaynak doğrulama — mali yazım yok; K05 açılmaz.

1) detay_yok 15 cari ↔ ekstre
2) 628 maliyetsiz stok sınıflandırma
3) LOT/seri belge satır izi + FIFO yöntem farkı
4) 31.08.2026 tarih sınırı
5) Banka → hedef bölüm eşlemesi
6) Firma ünvan kanıt bağlama

  .venv\\Scripts\\python.exe -m tools.dnm_d1.kaynak_dogrulama
  .venv\\Scripts\\python.exe -m tools.dnm_d1.kaynak_dogrulama --yeniden-15
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from tools.dnm_d1._ortak import CALISMA, KAYNAK, dec, parse_tarih, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import (
    DONEM_SONU,
    KAYNAK_FIRMA_ADI,
    KAYNAK_FIRMA_NO,
    RAPOR_ONEKI_KAYNAK,
    TALIMAT_DOSYA,
    TALIMAT_SHA256,
)

DONEM = DONEM_SONU  # 2026-08-31 dahil


def _yukle(ad: str) -> dict[str, Any]:
    return json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}{ad}.json").read_text(encoding="utf-8"))


def _cari_adlari() -> dict[str, str]:
    cari = _yukle("CARI")
    out: dict[str, str] = {}
    for r in cari.get("kayitlar") or []:
        cid = str(r.get("R.a_id") or r.get("a_id") or "")
        if not cid:
            continue
        ad = (
            r.get("text")
            or " ".join(
                str(x)
                for x in (r.get("R.a_ad"), r.get("R.a_soy"), r.get("R.a_resmi_ad"))
                if x
            ).strip()
            or cid
        )
        out[cid] = str(ad)[:160]
    return out


def _bolum1_detay_yok(yeniden_15: bool) -> dict[str, Any]:
    ak = _yukle("ACIK_KALEM")
    ce = _yukle("CARI_EKSTRE_KAPANIS")
    adlar = _cari_adlari()
    ekstre = {str(c["kaynak_cari_id"]): c for c in (ce.get("cariler") or [])}
    dy = [c for c in (ak.get("cariler") or []) if c.get("detay_yok_uyari")]

    yeniden_sonuc: list[dict[str, Any]] = []
    if yeniden_15 and dy:
        from entegrasyon.evobulut_client import EvobulutClient, load_credentials
        from tools.dnm_d1.acik_kalem_cek import _birlestir, _cek, _fifo_acik

        client = EvobulutClient(load_credentials())
        client.login()
        jsonl = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}ACIK_KALEM.jsonl"
        kayitlar: dict[str, dict] = {}
        if jsonl.is_file():
            for line in jsonl.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                o = json.loads(line)
                cid = str(o.get("kaynak_cari_id") or "")
                if cid:
                    kayitlar[cid] = o

        # Geniş dilimler; oturum hatasında login + 1 retry (erken kesme yok)
        dilimler = [
            ("01.09.2025", "31.08.2026"),
            ("01.01.2026", "31.08.2026"),
            ("01.01.2025", "31.12.2025"),
            ("01.01.2024", "31.12.2024"),
            ("01.01.2023", "31.12.2023"),
            ("01.01.2022", "31.12.2022"),
            ("01.01.2021", "31.12.2021"),
            ("01.01.2020", "31.12.2020"),
            ("01.01.2015", "31.12.2019"),
        ]

        def _cek_guvenli(mid: str, bas: str, son: str) -> dict[str, Any]:
            client.login()
            r = _cek(client, mid, bas, son)
            st = str(r.get("status") or "")
            if st not in ("OK",) or r.get("hata"):
                time.sleep(0.3)
                client.login()
                r = _cek(client, mid, bas, son)
            return r

        for i, c in enumerate(dy, 1):
            cid = str(c["kaynak_cari_id"])
            birlesen: dict[str, dict] = {}
            dilim_ozet = []
            kapanis_dev = None
            kapanis_ozet = None
            kapanis_son_bakiye = None
            for bas, son in dilimler:
                r = _cek_guvenli(cid, bas, son)
                n = len(r.get("detay") or [])
                dilim_ozet.append(
                    {
                        "bas": bas,
                        "son": son,
                        "status": r.get("status"),
                        "detay_adet": n,
                        "devreden": r.get("devreden"),
                        "hata": r.get("hata"),
                    }
                )
                if bas == "01.09.2025":
                    kapanis_dev = r.get("devreden")
                    kapanis_ozet = r.get("ozet")
                    det0 = r.get("detay") or []
                    if det0:
                        kapanis_son_bakiye = str(dec(det0[-1].get("Bakiye")))
                _birlestir(birlesen, r.get("detay") or [])
                time.sleep(0.05)
            detay = list(birlesen.values())
            acik, acik_toplam = _fifo_acik(detay, mid=cid)
            dev_bak = dec((kapanis_dev or {}).get("bakiye"))
            detay_yok = len(detay) == 0 and (
                abs(dec((kapanis_ozet or {}).get("bakiye"))) > 0 or abs(dev_bak) > 0
            )
            # Proxy yalnız Devreden≠0 ve detay yoksa; Özet bakiyesini açık kalem sayma
            if detay_yok and abs(dev_bak) > 0:
                acik.append(
                    {
                        "kaynak_cari_id": cid,
                        "kaynak_hareket_id": "DEVREDEN",
                        "tur": "DEVIR",
                        "tur_adi": "Devreden (detay yok)",
                        "belge_no": "",
                        "tarih": None,
                        "vade_tarihi": None,
                        "ack": "Detay boş; Devreden bakiyesi açık kalem proxy",
                        "orijinal_borc": str(abs(dev_bak)),
                        "kalan": str(abs(dev_bak)),
                        "doviz": "TL",
                        "proxy": True,
                    }
                )
                acik_toplam = abs(dev_bak)
            yeni = {
                "kaynak_cari_id": cid,
                "donem_sonu_dahil": DONEM.isoformat(),
                "alim_zamani": datetime.now().astimezone().isoformat(timespec="seconds"),
                "kapanis_devreden": kapanis_dev,
                "kapanis_ozet_umum": kapanis_ozet,
                "kapanis_son_detay_bakiye": kapanis_son_bakiye,
                "detay_birlesen_adet": len(detay),
                "acik_kalem_adet": len(acik),
                "acik_kalem_toplam": str(acik_toplam),
                "acik_kalemler": acik,
                "dilimler": dilim_ozet,
                "detay_yok_uyari": detay_yok,
                "olcut": "finans_jq_listesi_detay_fifo_v1_yeniden15",
                "uyari": (
                    "Özet.Bakiye dönem kapanışı değildir. "
                    "detay_yok iken tamam/sıfır işaretlenmez."
                ),
            }
            kayitlar[cid] = yeni
            yeniden_sonuc.append(
                {
                    "kaynak_cari_id": cid,
                    "detay_birlesen_adet": yeni.get("detay_birlesen_adet"),
                    "detay_yok_uyari": yeni.get("detay_yok_uyari"),
                    "acik_kalem_adet": yeni.get("acik_kalem_adet"),
                    "acik_kalem_toplam": yeni.get("acik_kalem_toplam"),
                    "dilim_hata": [
                        d
                        for d in dilim_ozet
                        if d.get("status") not in ("OK", None) or d.get("hata")
                    ],
                }
            )
            print(
                f"yeniden15 {i}/{len(dy)} id={cid} "
                f"detay={yeni.get('detay_birlesen_adet')} "
                f"detay_yok={yeni.get('detay_yok_uyari')}",
                flush=True,
            )
        # ACIK_KALEM JSON’u güncelle (sıfır yazmadan; tamam saymadan)
        liste = list(kayitlar.values())
        tum = []
        for x in liste:
            tum.extend(x.get("acik_kalemler") or [])
        detay_yok_n = sum(1 for x in liste if x.get("detay_yok_uyari"))
        out_ak = {
            "format": "d1-kaynak-acik-kalem-v1",
            "donem_sonu_dahil": DONEM.isoformat(),
            "cari_adet": len(liste),
            "hedef_cari_adet": ak.get("hedef_cari_adet"),
            "acik_kalem_adet": len(tum),
            "acik_kalem_toplam": str(sum((dec(k["kalan"]) for k in tum), Decimal("0"))),
            "detay_yok_cari_adet": detay_yok_n,
            "tamam_mi": False if detay_yok_n else bool(ak.get("tamam_mi")),
            "cariler": liste,
            "kapanis_durumu": (
                "ACIK_KALEM_FIFO_EKSIK_DETAY"
                if detay_yok_n
                else (ak.get("kapanis_durumu") or "ACIK_KALEM_FIFO")
            ),
            "uyari": (
                "detay_yok cari sayısı >0 iken ACIK_KALEM tamamlandı sayılmaz; "
                "eksik veri sıfır yazılmaz."
            ),
        }
        # tamam_mi: hedef karşılandı ama detay_yok varsa kapı için False
        if detay_yok_n:
            out_ak["tamam_mi"] = False
        elif len(liste) >= int(ak.get("hedef_cari_adet") or 0):
            out_ak["tamam_mi"] = True
        yaz_kaynak("ACIK_KALEM", out_ak)
        tmp = jsonl.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for o in liste:
                f.write(json.dumps(o, ensure_ascii=False) + "\n")
        tmp.replace(jsonl)
        ak = out_ak
        dy = [c for c in (ak.get("cariler") or []) if c.get("detay_yok_uyari")]

    satirlar = []
    for c in dy:
        cid = str(c["kaynak_cari_id"])
        e = ekstre.get(cid) or {}
        ozet = c.get("kapanis_ozet_umum") or {}
        satirlar.append(
            {
                "kaynak_cari_id": cid,
                "unvan": adlar.get(cid),
                "detay_birlesen_adet": c.get("detay_birlesen_adet"),
                "acik_kalem_adet": c.get("acik_kalem_adet"),
                "acik_kalem_toplam": c.get("acik_kalem_toplam"),
                "devreden_bakiye": (c.get("kapanis_devreden") or {}).get("bakiye"),
                "ozet_bakiye": ozet.get("bakiye"),
                "ozet_borc": ozet.get("borc"),
                "ozet_alacak": ozet.get("alacak"),
                "ekstre_kapanis_bakiye": e.get("kapanis_bakiye"),
                "ekstre_detay_satir_adet": e.get("detay_satir_adet"),
                "ekstre_son_ozet": e.get("son_ozet"),
                "dilim_ozet": c.get("dilimler"),
                "sonuc": "EKSIK",
                "gerekce": (
                    "finans_jq Detay boş; Devreden 0; Özet/ekstre sıfır-dışı bakiye gösteriyor. "
                    "Özet dönem kapanışı sayılmaz. Açık kalem sıfır/tamam yazılmadı."
                ),
            }
        )

    return {
        "format": "d1-dogrulama-acik-kalem-detay-yok-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "adet": len(satirlar),
        "yeniden_cekildi": bool(yeniden_15),
        "yeniden_ozet": yeniden_sonuc,
        "cariler": satirlar,
        "durum": "EKSIK" if satirlar else "TAMAM",
        "k05_etkisi": "detay_yok>0 → ACIK_KALEM tam kabul edilmez; K05 açılmaz",
    }


def _bolum2_stok628() -> dict[str, Any]:
    st = _yukle("STOK_MIKTAR")
    sm = _yukle("STOK_MALIYET")
    maliyet_ids = {str(s["kaynak_stok_id"]) for s in (sm.get("stoklar") or [])}
    sinif: dict[str, list] = defaultdict(list)
    for r in st.get("kayitlar") or []:
        sid = str(r.get("a_id") or "")
        if not sid or sid in maliyet_ids:
            continue
        kalan = dec(r.get("a_kalan"))
        giren = dec(r.get("a_giren"))
        cikan = dec(r.get("a_cikan"))
        fifo = r.get("a_maliyet_fifo")
        ort = r.get("a_maliyet_ort")
        alis = r.get("a_fiyat_al")
        kayit = {
            "kaynak_stok_id": sid,
            "kod": r.get("a_kod"),
            "adi": r.get("a_adi"),
            "kalan": str(kalan),
            "giren": str(giren),
            "cikan": str(cikan),
            "liste_fifo": fifo,
            "liste_ort": ort,
            "liste_fiyat_al": alis,
        }
        if kalan == 0 and giren == 0 and cikan == 0:
            sinif["sifir_hareket_sifir_bakiye"].append(kayit)
        elif kalan == 0 and (giren != 0 or cikan != 0):
            sinif["sifir_bakiye_hareketli"].append(kayit)
        elif kalan != 0:
            # Maliyet çekimine dahil olmalıydı; yoksa gerçek eksik
            sinif["bakiye_var_maliyet_cekimi_yok"].append(kayit)
        else:
            sinif["diger"].append(kayit)

    ozet = {k: len(v) for k, v in sinif.items()}
    # örnekler
    ornek = {k: v[:15] for k, v in sinif.items()}
    return {
        "format": "d1-dogrulama-stok-maliyetsiz-sinif-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "toplam_kart": st.get("adet") or len(st.get("kayitlar") or []),
        "maliyet_cekilen": len(maliyet_ids),
        "maliyetsiz_adet": sum(ozet.values()),
        "sinif_adet": ozet,
        "ornekler": ornek,
        "not": (
            "Maliyet çekimi yalnız a_kalan≠0 kartlara uygulandı. "
            "Sıfır bakiye kartlar bilinçli dışarıda; negatif bakiyeler korunur."
        ),
        "durum": (
            "EKSIK"
            if ozet.get("bakiye_var_maliyet_cekimi_yok")
            else "TAMAM_SINIFLANDIRILDI"
        ),
    }


def _lot_parse(lot: Any) -> list[dict]:
    if lot is None or lot in ("", {}, []):
        return []
    if isinstance(lot, dict):
        return [lot]
    if isinstance(lot, list):
        return [x for x in lot if isinstance(x, dict)]
    return []


def _bolum3_lot_fifo() -> dict[str, Any]:
    sm = _yukle("STOK_MALIYET")
    jsonl = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE_SATIR.jsonl"
    # tur: 30 alış, 31 satış, 32 alış iade, 33 satış iade (yaklaşık Evo)
    giris_tur = {"30", "32", "34", "36"}  # alış / iade alış yönü
    cikis_tur = {"31", "33", "35", "37"}

    lot_hareket: list[dict] = []
    lot_kalan: dict[str, dict] = {}
    belgeler_lot = 0
    satir_lot = 0
    donem_disi = 0

    with jsonl.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            o = json.loads(line)
            if o.get("status") != "OK":
                continue
            t = parse_tarih(o.get("tarih"))
            tur = str(o.get("tur") or o.get("liste_tur") or "")
            if t is not None and t > DONEM:
                donem_disi += 1
                continue
            has_lot = False
            for s in o.get("satirlar") or []:
                lots = _lot_parse(s.get("seri_lot"))
                if not lots:
                    continue
                has_lot = True
                satir_lot += 1
                sid = str(s.get("a_stok_id") or s.get("stok_id") or "")
                mik = dec(s.get("miktar"))
                for L in lots:
                    lot_no = str(L.get("a_lot_no") or L.get("a_seri_no") or L.get("a_id") or "")
                    key = f"{sid}|{lot_no}"
                    yon = "GIRIS" if tur in giris_tur else ("CIKIS" if tur in cikis_tur else "DIGER")
                    kayit = {
                        "belge_id": o.get("kaynak_belge_id"),
                        "tur": tur,
                        "tarih": o.get("tarih"),
                        "stok_id": sid,
                        "lot_no": lot_no,
                        "yon": yon,
                        "satir_miktar": str(mik),
                        "lot_giren": L.get("a_giren"),
                        "lot_cikan": L.get("a_cikan"),
                        "lot_kalan_alan": L.get("kalan"),
                        "lot_haric_kalan": L.get("haric_kalan"),
                        "lot_id": L.get("a_id"),
                    }
                    lot_hareket.append(kayit)
                    # Son görülen kalan alanı (API anlık; katman değil)
                    lot_kalan[key] = {
                        "stok_id": sid,
                        "lot_no": lot_no,
                        "kalan_alan": L.get("kalan"),
                        "haric_kalan": L.get("haric_kalan"),
                        "son_belge": o.get("kaynak_belge_id"),
                        "son_tarih": o.get("tarih"),
                    }
            if has_lot:
                belgeler_lot += 1

    # FIFO yöntem farkı: kart fifo vs ort vs alış
    yontem = Counter()
    fark_fifo_ort = []
    negatif_kalan = 0
    for s in sm.get("stoklar") or []:
        yontem[s.get("maliyet_kaynagi") or "YOK"] += 1
        if dec(s.get("kalan")) < 0:
            negatif_kalan += 1
        fifo = dec(s.get("maliyet_fifo")) if s.get("maliyet_fifo") not in (None, "") else None
        ort = dec(s.get("maliyet_ort")) if s.get("maliyet_ort") not in (None, "") else None
        if fifo is not None and ort is not None and fifo != ort:
            fark_fifo_ort.append(
                {
                    "kaynak_stok_id": s.get("kaynak_stok_id"),
                    "kod": s.get("kod"),
                    "kalan": s.get("kalan"),
                    "fifo": s.get("maliyet_fifo"),
                    "ort": s.get("maliyet_ort"),
                    "fark": str(fifo - ort),
                    "secilen": s.get("maliyet_kaynagi"),
                }
            )

    # Belge satır miktarı vs lot giren/çıkan tutarlılık örnekleri
    tutarsiz = []
    for h in lot_hareket:
        lg, lc = dec(h.get("lot_giren")), dec(h.get("lot_cikan"))
        smik = dec(h.get("satir_miktar"))
        if h["yon"] == "GIRIS" and lg != 0 and smik != 0 and abs(lg) != abs(smik):
            tutarsiz.append({**h, "neden": "giris_mik_lot_uyusmazligi"})
        elif h["yon"] == "CIKIS" and lc != 0 and smik != 0 and abs(lc) != abs(smik):
            tutarsiz.append({**h, "neden": "cikis_mik_lot_uyusmazligi"})
        if len(tutarsiz) >= 50:
            break

    return {
        "format": "d1-dogrulama-lot-fifo-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "stok_hareket_api": "BOS_StokHareket_list",
        "stok_hareket_api_durum": "UYGULANAMAZ",
        "stok_hareket_api_gerekce": (
            "Kaynak StokHareket/base list bu firmada boş; "
            "LOT izi yalnız fatura Seri_Lot_List + kart maliyeti."
        ),
        "belge_lot_belge_adet": belgeler_lot,
        "belge_lot_satir_adet": satir_lot,
        "lot_hareket_adet": len(lot_hareket),
        "tekil_stok_lot_anahtar": len(lot_kalan),
        "donem_disi_belge_atlanadi": donem_disi,
        "maliyet_yontem_adet": dict(yontem),
        "fifo_ort_farkli_kart_adet": len(fark_fifo_ort),
        "fifo_ort_fark_ornek": fark_fifo_ort[:30],
        "negatif_kalan_kart_adet": negatif_kalan,
        "negatif_korundu": True,
        "lot_mik_tutarsizlik_ornek": tutarsiz[:30],
        "lot_kalan_ornek": list(lot_kalan.values())[:30],
        "fifo_katman_izlenebilirlik": {
            "durum": "KISMI",
            "gerekce": (
                "Seri_Lot_List belge satırında lot_no/giren/cikan/kalan alanı verir; "
                "tarihli FIFO katman maliyeti (alış birim×kalan katman) API’de yok. "
                "Kart a_maliyet_fifo anlık birim maliyettir; katman dökümü üretilemez."
            ),
        },
        "durum": "KISMI",
    }


def _bolum4_tarih_siniri() -> dict[str, Any]:
    moduller = {}

    def _scan_hareket(ad: str, tarih_alan: tuple[str, ...]) -> dict[str, Any]:
        veri = _yukle(ad)
        rows = veri.get("hareketler") or veri.get("kayitlar") or []
        ic, dis, parse_hata = 0, 0, 0
        dis_ornek = []
        for r in rows:
            raw = None
            for k in tarih_alan:
                if r.get(k) not in (None, ""):
                    raw = r.get(k)
                    break
            t = parse_tarih(raw)
            if t is None:
                parse_hata += 1
                continue
            if t <= DONEM:
                ic += 1
            else:
                dis += 1
                if len(dis_ornek) < 10:
                    dis_ornek.append({"tarih": t.isoformat(), "id": r.get("G.a_id") or r.get("a_id")})
        return {
            "toplam": len(rows),
            "donem_ici_dahil": ic,
            "donem_sonrasi": dis,
            "parse_hata": parse_hata,
            "donem_sonrasi_ornek": dis_ornek,
        }

    moduller["KASA"] = _scan_hareket("KASA", ("G.a_tarih", "a_tarih"))
    moduller["BANKA"] = _scan_hareket("BANKA", ("G.a_tarih", "a_tarih"))

    # POS valor: valor_tarihi > 31.08 olanlar kapanışta valor_bekleyen olmalı
    pv = _yukle("POS_VALOR")
    moduller["POS_VALOR"] = {
        "bloke_adet": pv.get("bloke_adet"),
        "valor_bekleyen_adet": pv.get("valor_bekleyen_adet"),
        "valor_bekleyen_toplam": pv.get("valor_bekleyen_toplam"),
        "bankaya_gecmis_adet": pv.get("bankaya_gecmis_adet"),
        "not": (
            "valor_tarihi > 31.08.2026 olanlar valor_bekleyen’de; "
            "sonraki banka geçişi 31.08 kapanış netini değiştirmez (ayrı kova)."
        ),
    }

    # Belge başlık tarihleri
    bel = _yukle("BELGE")
    ic = dis = 0
    for _tur, lst in (bel.get("belgeler") or {}).items():
        for r in lst or []:
            t = parse_tarih(r.get("G.a_tarih") or r.get("a_tarih"))
            if t is None:
                continue
            if t <= DONEM:
                ic += 1
            else:
                dis += 1
    moduller["BELGE"] = {"donem_ici_dahil": ic, "donem_sonrasi_filtrelenmeli": dis}

    # Belge satır
    bs = _yukle("BELGE_SATIR")
    moduller["BELGE_SATIR"] = {
        "belge_adet": bs.get("belge_adet"),
        "hedef": bs.get("hedef_belge_adet"),
        "tamam_mi": bs.get("tamam_mi"),
        "filtre": "çekimde t>31.08 atlandı",
    }

    # Cari açık kalem tarihleri
    ak = _yukle("ACIK_KALEM")
    ak_dis = 0
    for c in ak.get("cariler") or []:
        for k in c.get("acik_kalemler") or []:
            t = parse_tarih(k.get("tarih"))
            if t and t > DONEM:
                ak_dis += 1
    moduller["ACIK_KALEM"] = {
        "acik_kalem_adet": ak.get("acik_kalem_adet"),
        "detay_yok_cari_adet": ak.get("detay_yok_cari_adet"),
        "donem_sonrasi_kalem": ak_dis,
        "tamam_mi_bayrak": ak.get("tamam_mi"),
        "uyari": "detay_yok>0 iken tamam kabul edilmez",
    }

    sm = _yukle("STOK_MALIYET")
    moduller["STOK_MALIYET"] = {
        "adet": sm.get("adet"),
        "toplam_maliyet_tl": sm.get("toplam_maliyet_tl"),
        "uyari": sm.get("stoklar", [{}])[0].get("uyari") if sm.get("stoklar") else None,
        "not": "Kart maliyeti görüntü anına yakın olabilir; tarihli envanter API katmanı yok",
    }

    ihlal = []
    for ad, m in moduller.items():
        if isinstance(m, dict) and m.get("donem_sonrasi"):
            ihlal.append(ad)
    if (moduller.get("ACIK_KALEM") or {}).get("donem_sonrasi_kalem"):
        ihlal.append("ACIK_KALEM_tarih")

    return {
        "format": "d1-dogrulama-tarih-siniri-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "haric_ust": "2026-09-01T00:00:00+03:00",
        "moduller": moduller,
        "donem_sonrasi_ihlal_modulleri": ihlal,
        "durum": "TAMAM" if not ihlal else "EKSIK",
        "gerekce": (
            "Kasa/banka ham JSON dönem dışı satır içeriyorsa kapanış neti zaten "
            "parse_tarih<=31.08 ile filtrelenir; POS valor_bekleyen ayrı kovadır."
            if not ihlal
            else "Dönem sonrası satır tespit edildi — ayrıntıya bak."
        ),
    }


def _hedef_bolum(ad: str, *, posmu: Any) -> str:
    u = (ad or "").upper()
    if str(posmu) in ("1", "true", "True") or " POS" in f" {u}" or u.endswith("POS") or "POS BAĞLI" in u or "POS HESABI" in u:
        # "halkbank esnaf kredisi" yanlışlıkla pos listesinde olabilir — ad öncelikli
        if "KREDİ KART" in u or "KREDI KART" in u:
            return "KREDI_KARTI"
        if re.search(r"\bKRED[Iİ]", u) and "POS" not in u and "KART" not in u:
            return "KREDILER"
        return "POS"
    if "KREDİ KART" in u or "KREDI KART" in u or "AXESS" in u or "WORLD" in u and "KART" in u:
        return "KREDI_KARTI"
    if "KMH" in u:
        return "KMH"
    if re.search(r"\bKRED[Iİ]", u) and "KART" not in u:
        return "KREDILER"
    if "HİSSE" in u or "HISSE" in u or "FON" in u:
        return "DIGER_YATIRIM"
    if u.startswith("01 ") or " MEWDUAT" in u or "MEVDUAT" in u or "ENPARA MEHMET" in u:
        return "MEVDUAT"
    # varsayılan: 01 mevduat/kmh benzeri
    if u.startswith("01"):
        return "MEVDUAT" if "KMH" not in u else "KMH"
    if u.startswith("02"):
        return "KREDI_KARTI"
    if u.startswith("03"):
        return "KREDILER"
    if u.startswith("04"):
        return "DIGER_YATIRIM"
    return "MEVDUAT"


def _bolum5_banka_esleme() -> dict[str, Any]:
    banka = _yukle("BANKA")
    pk = _yukle("POS_KART_KREDI")
    bk = _yukle("BANKA_KAPANIS")
    kapanis = {
        str(h.get("kaynak_hesap_id") or h.get("hesap_id")): h
        for h in (bk.get("hesaplar") or [])
    }
    eski = {}
    for grup, key in (
        ("POS", "pos"),
        ("KREDI_KARTI", "kredi_karti"),
        ("KREDILER", "kredi"),
        ("DIGER", "diger_banka"),
    ):
        for r in pk.get(key) or []:
            eski[str(r["id"])] = grup

    esleme = []
    uyari = []
    sayac = Counter()
    for k in banka.get("kartlar") or []:
        hid = str(k.get("id"))
        ad = str(k.get("text") or "")
        bolum = _hedef_bolum(ad, posmu=k.get("a_posmu"))
        sayac[bolum] += 1
        onceki = eski.get(hid)
        kap = kapanis.get(hid) or {}
        row = {
            "kaynak_banka_id": hid,
            "hesap_adi": ad,
            "a_posmu": k.get("a_posmu"),
            "a_posgun": k.get("a_posgun"),
            "hedef_bolum": bolum,
            "onceki_sinif": onceki,
            "kapanis_net": kap.get("kapanis_net") or kap.get("net"),
        }
        if onceki and onceki != bolum and not (
            onceki == "DIGER" and bolum in ("MEVDUAT", "KMH", "DIGER_YATIRIM")
        ):
            row["sinif_farki"] = True
            if onceki == "POS" and bolum != "POS":
                row["duzeltme"] = f"onceki POS → önerilen {bolum}"
            uyari.append(row)
        esleme.append(row)

    return {
        "format": "d1-dogrulama-banka-hedef-bolum-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "hedef_bolumler": [
            "MEVDUAT",
            "KMH",
            "POS",
            "KREDI_KARTI",
            "KREDILER",
            "DIGER_YATIRIM",
        ],
        "adet": dict(sayac),
        "hesaplar": esleme,
        "uyari_hesaplar": uyari,
        "korunan_ayrimlar": {
            "POS": sayac.get("POS", 0),
            "KREDI_KARTI": sayac.get("KREDI_KARTI", 0),
            "KREDILER": sayac.get("KREDILER", 0),
            "KMH": sayac.get("KMH", 0),
            "MEVDUAT": sayac.get("MEVDUAT", 0),
        },
        "durum": "TAMAM_ESLEME" if esleme else "EKSIK",
        "not": (
            "Hedef Cin banka alt hesap türleri: MEVDUAT|KMH|POS|KREDI_KARTI|KREDILER. "
            "Yazım yok; yalnız eşleme önerisi."
        ),
    }


def _bolum6_firma() -> dict[str, Any]:
    fd = _yukle("FIRMA_DOGRULAMA")
    talimat_yol = CALISMA / Path(TALIMAT_DOSYA).name
    if not talimat_yol.is_file():
        # donem_sabitleri göreli yol
        talimat_yol = Path(__file__).resolve().parents[2] / TALIMAT_DOSYA

    # Sohbet geçmişinde kullanıcı web teyidi bulunamadı; talimat + login bağlanır
    kanit = {
        "format": "d1-firma-unvan-kanit-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "firma_no": KAYNAK_FIRMA_NO,
        "firma_adi_beklenen": KAYNAK_FIRMA_ADI,
        "login_a_firma_id": fd.get("kalici_firma_id") or fd.get("beklenen_firma_no"),
        "login_dogrulandi": bool(fd.get("dogrulandi")),
        "firma_adi_api": fd.get("firma_adi_api"),
        "talimat": {
            "dosya": str(talimat_yol.name),
            "sha256": TALIMAT_SHA256,
            "kaynak_firma_satiri": KAYNAK_FIRMA_ADI,
            "kaynak_firma_no": KAYNAK_FIRMA_NO,
            "rol": "Kullanıcının paylaştığı talimat Excel’inde ünvan + 42178 yazılı",
        },
        "web_ekran_teyidi": {
            "durum": "EKSIK",
            "gerekce": (
                "Sohbet/agent kayıtlarında kullanıcının web.evobulut.com ekran teyidi "
                "metni bulunamadı. API unvan boş. Login yalnız a_firma_id=42178 kanıtlar."
            ),
        },
        "bagli_kanit_dosyalari": [
            "kaynak/D1_20260831_KAYNAK_FIRMA_DOGRULAMA.json",
            "Cin_Muhasebe_DNM_D1_Bakiye_Mutabakat_Talimati_2026-11-06.xlsx",
            "CALISMA_MANIFESTI.json",
        ],
        "sonuc": "KISMI",
        "k05_etkisi": "Firma no OK; unvan web teyidi eksik → K01 kısmi, K05 açılmaz",
    }
    # FIRMA_DOGRULAMA’ya bağla (sıfır/tamam uydurma yok)
    fd2 = dict(fd)
    fd2["unvan_kanit"] = {
        "talimat_sha256": TALIMAT_SHA256,
        "talimat_firma_adi": KAYNAK_FIRMA_ADI,
        "talimat_firma_no": KAYNAK_FIRMA_NO,
        "web_ekran_teyidi": False,
        "web_teyit_gerekce": kanit["web_ekran_teyidi"]["gerekce"],
        "rapor": "D1_20260831_DOGRULAMA_FIRMA_UNVAN.json",
    }
    fd2["firma_adi_web_dogrulandi"] = False
    yaz_kaynak("FIRMA_DOGRULAMA", fd2)
    yaz_kaynak("DOGRULAMA_FIRMA_UNVAN", kanit)
    return kanit


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--yeniden-15",
        action="store_true",
        help="detay_yok 15 cariyi taze oturumla yeniden çek (sıfır yazmaz)",
    )
    args = p.parse_args(argv)

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    b1 = _bolum1_detay_yok(args.yeniden_15)
    yaz_kaynak("DOGRULAMA_ACIK_KALEM_DETAY_YOK", b1)
    b2 = _bolum2_stok628()
    yaz_kaynak("DOGRULAMA_STOK_MALIYETSIZ_SINIF", b2)
    b3 = _bolum3_lot_fifo()
    yaz_kaynak("DOGRULAMA_LOT_FIFO", b3)
    b4 = _bolum4_tarih_siniri()
    yaz_kaynak("DOGRULAMA_TARIH_SINIRI", b4)
    b5 = _bolum5_banka_esleme()
    yaz_kaynak("DOGRULAMA_BANKA_HEDEF_BOLUM", b5)
    b6 = _bolum6_firma()

    tamam, eksik, uygulanamaz = [], [], []

    def _sinif(ad: str, durum: str, gerekce: str) -> None:
        row = {"madde": ad, "durum": durum, "gerekce": gerekce}
        if durum == "TAMAM":
            tamam.append(row)
        elif durum == "UYGULANAMAZ":
            uygulanamaz.append(row)
        else:
            eksik.append(row)

    _sinif(
        "1_acik_kalem_15",
        "EKSIK" if b1.get("adet") else "TAMAM",
        f"detay_yok={b1.get('adet')}; Özet≠Detay; sıfır/tamam işaretlenmedi",
    )
    _sinif(
        "2_stok_628_sinif",
        "TAMAM" if b2.get("durum") == "TAMAM_SINIFLANDIRILDI" else "EKSIK",
        json.dumps(b2.get("sinif_adet"), ensure_ascii=False),
    )
    _sinif(
        "3_lot_fifo",
        "EKSIK",
        b3["fifo_katman_izlenebilirlik"]["gerekce"],
    )
    _sinif(
        "3_stok_hareket_api",
        "UYGULANAMAZ",
        b3["stok_hareket_api_gerekce"],
    )
    _sinif(
        "4_tarih_siniri_3108",
        "TAMAM" if b4.get("durum") == "TAMAM" else "EKSIK",
        b4.get("gerekce") or "",
    )
    _sinif(
        "5_banka_bolum_esleme",
        "TAMAM",
        f"adet={b5.get('korunan_ayrimlar')}; uyari={len(b5.get('uyari_hesaplar') or [])}",
    )
    _sinif(
        "6_firma_unvan",
        "EKSIK",
        "42178 login+talimat bağlı; web ekran teyidi yok",
    )

    ozet = {
        "format": "d1-kaynak-dogrulama-ozet-v1",
        "zaman": now,
        "donem_sonu_dahil": DONEM.isoformat(),
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "exe_paket": False,
        "tamamlanan": tamam,
        "eksik": eksik,
        "uygulanamaz": uygulanamaz,
        "kanitlar": {
            "acik_kalem_15": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_ACIK_KALEM_DETAY_YOK.json",
            "stok_628": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_STOK_MALIYETSIZ_SINIF.json",
            "lot_fifo": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_LOT_FIFO.json",
            "tarih": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_TARIH_SINIRI.json",
            "banka": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_BANKA_HEDEF_BOLUM.json",
            "firma": "kaynak/D1_20260831_KAYNAK_DOGRULAMA_FIRMA_UNVAN.json",
        },
    }
    yaz_json(CALISMA / "KAYNAK_DOGRULAMA_OZET.json", ozet)

    # DURUM güncelle — K05 kapalı
    durum_yol = CALISMA / "DURUM.json"
    durum = json.loads(durum_yol.read_text(encoding="utf-8")) if durum_yol.is_file() else {}
    durum.update(
        {
            "guncelleme": now,
            "ozet": (
                f"Kaynak doğrulama: detay_yok={b1.get('adet')}; "
                f"stok628={b2.get('sinif_adet')}; "
                f"LOT satır={b3.get('belge_lot_satir_adet')}; "
                f"banka eşleme OK; unvan web EKSIK. K05/K06 kapalı."
            ),
            "k05": False,
            "k06": False,
            "dogrulama_ozet": "KAYNAK_DOGRULAMA_OZET.json",
            "eksik_k05": [e["madde"] + ": " + e["gerekce"] for e in eksik]
            + ["K06 ANA DB ertelendi", "EXE/paket ertelendi"],
        }
    )
    yaz_json(durum_yol, durum)

    print(json.dumps(
        {
            "tamam": len(tamam),
            "eksik": len(eksik),
            "uygulanamaz": len(uygulanamaz),
            "detay_yok": b1.get("adet"),
            "stok628": b2.get("sinif_adet"),
            "lot_satir": b3.get("belge_lot_satir_adet"),
            "k05": False,
        },
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
