"""DNM D1 devam: örtüşen cari riskler, 628 stok hareket, LOT/fark analizi.

Tahmini menü adı yazmaz. K05 açılmaz. Mali yazım yok.

  .venv\\Scripts\\python.exe -m tools.dnm_d1.kaynak_dogrulama_devam2
  .venv\\Scripts\\python.exe -m tools.dnm_d1.kaynak_dogrulama_devam2 --atla-stok628
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
KESIM = "2026-09-01T00:00:00+03:00"
STOK_HRK_JSONL = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}STOK_HAREKET.jsonl"


def _yukle(ad: str) -> dict[str, Any]:
    return json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}{ad}.json").read_text(encoding="utf-8"))


def gerekli_rapor_tablosu() -> dict[str, Any]:
    """Yalnızca doğrulanmış API/kanıt adları; menü yolu bilinmiyorsa DOGRULANMADI."""
    maddeler = [
        {
            "oncelik": 1,
            "sorun": "15/22 cari: Özet tarih bağımsız; 31.08 kanıtlı bakiye yok",
            "kaynak_dogrulanmis_ad": "Musteri/base cmd=finans_jq_listesi (Cari hesap ekstresi API)",
            "menu_yolu": "DOGRULANMADI — web menü yolu ekrandan teyit edilmedi",
            "tarih_filtresi": "Bitiş ≤ 31.08.2026 dahil; kesim 01.09.2026 00:00 Europe/Istanbul; max 1 yıl dilim",
            "gerekli_sutunlar": [
                "Tarih",
                "Belge/Tür",
                "Borç",
                "Alacak",
                "Bakiye",
                "Vade (varsa)",
                "Belge no / id",
            ],
            "mevcut_mu": "KISMI — API Özet var, Detay çoğu risk caride boş",
            "dosya": "CARI_EKSTRE_KAPANIS_DUZELTILMIS.json / DOGRULAMA_15_CARI_DETAY.json",
        },
        {
            "oncelik": 2,
            "sorun": "Açık kalem / kapama ilişkisi (Detay boş cariler)",
            "kaynak_dogrulanmis_ad": "DOGRULANMADI — ayrı açık-kalem rapor uç noktası doğrulanmadı",
            "menu_yolu": "DOGRULANMADI",
            "tarih_filtresi": "≤ 31.08.2026",
            "gerekli_sutunlar": ["Cari", "Belge", "Kalan", "Vade", "Kapama bağları"],
            "mevcut_mu": "HAYIR",
            "dosya": None,
        },
        {
            "oncelik": 3,
            "sorun": "Kart miktar ≠ StokHareket neti (depo/birim/açılış)",
            "kaynak_dogrulanmis_ad": "StokHareket/base cmd=list (stok_id zorunlu)",
            "menu_yolu": "DOGRULANMADI — stok kart hareket ekranı yolu teyit edilmedi",
            "tarih_filtresi": "01.01.2015 – 31.08.2026 dahil",
            "gerekli_sutunlar": [
                "tarih",
                "belge_tur",
                "depo",
                "Birim",
                "gir_miktar",
                "cik_miktar",
                "devir",
                "Fat_id",
                "ack",
            ],
            "mevcut_mu": "KISMI — 2522 çekildi; 628 sıfır-bakiye bu koşuda tamamlanır",
            "dosya": "STOK_HAREKET.jsonl",
        },
        {
            "oncelik": 4,
            "sorun": "LOT katman miktar/tarih/maliyet",
            "kaynak_dogrulanmis_ad": "fatura/base cmd=sql → Detay.Seri_Lot_List",
            "menu_yolu": "DOGRULANMADI — Seri/LOT ekran yolu teyit edilmedi",
            "tarih_filtresi": "Belge tarihi ≤ 31.08.2026",
            "gerekli_sutunlar": [
                "a_lot_no",
                "a_giren",
                "a_cikan",
                "kalan (anlık alan)",
                "belge tarih/tur",
                "katman birim maliyet (API’de yok)",
            ],
            "mevcut_mu": "KISMI — miktar/tarih belge satırında; katman maliyet yok",
            "dosya": "BELGE_SATIR.jsonl / DOGRULAMA_LOT_KATMAN.json",
        },
        {
            "oncelik": 5,
            "sorun": "Döviz bazlı açılış+hareket=kapanış",
            "kaynak_dogrulanmis_ad": "DOGRULANMADI — dövizli ekstre API/komut doğrulanmadı",
            "menu_yolu": "DOGRULANMADI",
            "tarih_filtresi": "≤ 31.08.2026",
            "gerekli_sutunlar": ["Döviz", "Borç", "Alacak", "Bakiye"],
            "mevcut_mu": "HAYIR",
            "dosya": None,
        },
    ]
    out = {
        "format": "d1-gerekli-kaynak-rapor-tablosu-v2",
        "donem_sonu_dahil": DONEM.isoformat(),
        "kesim_istanbul": KESIM,
        "ilk_alinacak": maddeler[0],
        "maddeler": maddeler,
        "not": (
            "Menü yolları tahmin edilmedi. Önceki GEREKLI_EKRAN_EXCEL içindeki "
            "'Raporlar → …' ifadeleri doğrulanmamış varsayımdı; bu tabloda DOGRULANMADI."
        ),
    }
    yaz_kaynak("DOGRULAMA_GEREKLI_EKRAN_EXCEL", out)
    return out


def cari_ortusme_analiz() -> dict[str, Any]:
    ak = _yukle("ACIK_KALEM")
    duz = _yukle("CARI_EKSTRE_KAPANIS_DUZELTILMIS")
    es = _yukle("DOGRULAMA_CARI_ESITLIK")
    risk15 = {
        str(c["kaynak_cari_id"])
        for c in (ak.get("cariler") or [])
        if c.get("detay_yok_uyari")
    }
    risk22 = {
        str(c["kaynak_cari_id"])
        for c in (duz.get("cariler") or [])
        if c.get("kanit_durumu") == "DOGRULANMAMIS_OZET"
    }
    # 110 özet-detay fark: esitlik dosyasındaki ornek_fark + jsonl tarama
    fark_ids = set()
    for r in es.get("ornek_fark") or []:
        if r.get("kaynak_cari_id"):
            fark_ids.add(str(r["kaynak_cari_id"]))
    # Tam 110 için ACIK_KALEM.jsonl
    jsonl = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}ACIK_KALEM.jsonl"
    fark_110: list[dict] = []
    if jsonl.is_file():
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            o = json.loads(line)
            cid = str(o.get("kaynak_cari_id") or "")
            det_n = int(o.get("detay_birlesen_adet") or 0)
            if det_n <= 0:
                continue
            son = o.get("kapanis_son_detay_bakiye")
            ozet_b = dec((o.get("kapanis_ozet_umum") or {}).get("bakiye"))
            if son is None:
                continue
            if dec(son) != ozet_b:
                fark_110.append(
                    {
                        "kaynak_cari_id": cid,
                        "son_detay_bakiye": son,
                        "dogrulanmamis_ozet_bakiye": str(ozet_b),
                        "fark": str(dec(son) - ozet_b),
                        "devreden": (o.get("kapanis_devreden") or {}).get("bakiye"),
                        "acik_kalem_adet": o.get("acik_kalem_adet"),
                        "not": (
                            "Özet 31.08 kanıtı değil. Fark, Özet’in tarih bağımsız "
                            "olmasından kaynaklanabilir; Eylül bakiyesi taşınmadı."
                        ),
                    }
                )
                fark_ids.add(cid)

    set110 = {x["kaynak_cari_id"] for x in fark_110}
    birlesim = risk15 | risk22 | set110
    out = {
        "format": "d1-dogrulama-cari-ortusme-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "kesim_istanbul": KESIM,
        "grup_adetleri_ayri": {
            "detay_yok_15": len(risk15),
            "dogrulanmamis_ozet_22": len(risk22),
            "ozet_detay_fark_110": len(fark_110),
        },
        "ortusme": {
            "15_∩_22": len(risk15 & risk22),
            "15_∩_110": len(risk15 & set110),
            "22_∩_110": len(risk22 & set110),
            "15_∩_22_∩_110": len(risk15 & risk22 & set110),
            "birlesim_tekil": len(birlesim),
        },
        "uyari": "Grup adetleri toplanmaz; örtüşme tekil birleşimde raporlanır.",
        "detay_yok_15_ids": sorted(risk15, key=lambda x: int(x)),
        "dogrulanmamis_ozet_22_ids": sorted(risk22, key=lambda x: int(x)),
        "ozet_detay_fark_110_ornek": fark_110[:40],
        "ozet_detay_fark_110_adet": len(fark_110),
        "acilis_devir": {
            "durum": "BULUNAMADI_MEVCUT_KANITTA",
            "gerekce": (
                "cari/base sql açılış tarihi alanı içermiyor; "
                "finans_jq Detay boş risk carilerde ilk hareket/devir yok. "
                "Sahte açılış üretilmedi."
            ),
        },
        "bakiye_3108": {
            "etiket": "dogrulanmamis_ozet veya null",
            "kanitli_adet_15": 0,
            "not": "Güncel kart bakiyesi 31.08 kapanışı olarak kullanılmadı.",
        },
        "sonuc": "EKSIK",
        "k05": False,
    }
    yaz_kaynak("DOGRULAMA_CARI_ORTUSME", out)
    return out


def lot_dogrulama() -> dict[str, Any]:
    sm = _yukle("STOK_MALIYET")
    maliyet = {str(s["kaynak_stok_id"]): s for s in (sm.get("stoklar") or [])}
    jsonl = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE_SATIR.jsonl"

    giris_tur = {"30", "32", "34", "36"}
    cikis_tur = {"31", "33", "35", "37"}
    olaylar = []
    kalan_son: dict[str, dict] = {}
    maliyet_kanit = Counter()

    with jsonl.open(encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            if o.get("status") != "OK":
                continue
            t = parse_tarih(o.get("tarih"))
            if t is not None and t > DONEM:
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
                    lot_no = str(L.get("a_lot_no") or L.get("a_seri_no") or "")
                    key = f"{sid}|{lot_no}"
                    yon = "GIRIS" if tur in giris_tur else ("CIKIS" if tur in cikis_tur else "DIGER")
                    # Özgün giriş tarihi: alış yönü belge tarihi (katman FIFO maliyeti değil)
                    ozgun_giris_tarih = o.get("tarih") if yon == "GIRIS" else None
                    satir_fiyat = s.get("birim_fiyat")
                    # Satır fiyatı giriş ipucu; FIFO katman maliyeti kanıtı DEĞİL
                    if yon == "GIRIS" and satir_fiyat not in (None, ""):
                        maliyet_durum = "GIRIS_SATIR_FIYAT_IPUCU_KATMAN_DEGIL"
                        maliyet_kanit["giris_satir_fiyat_ipucu"] += 1
                    else:
                        maliyet_durum = "KATMAN_MALIYET_YOK"
                        maliyet_kanit["katman_maliyet_yok"] += 1
                    kayit = {
                        "stok_id": sid,
                        "lot_no": lot_no,
                        "lot_id": L.get("a_id"),
                        "belge_id": o.get("kaynak_belge_id"),
                        "belge_tur": tur,
                        "belge_tarih": o.get("tarih"),
                        "yon": yon,
                        "giren": L.get("a_giren"),
                        "cikan": L.get("a_cikan"),
                        "kalan_alan_anlik": L.get("kalan"),
                        "ozgun_giris_tarih_aday": ozgun_giris_tarih,
                        "satir_birim_fiyat": satir_fiyat,
                        "katman_maliyet_durum": maliyet_durum,
                        "kart_a_maliyet_fifo": (maliyet.get(sid) or {}).get("maliyet_fifo"),
                        "kart_fifo_katman_kaniti_degil": True,
                    }
                    olaylar.append(kayit)
                    prev = kalan_son.get(key)
                    # Son belge tarihine göre kalan alan güncelle (anlık API alanı)
                    if prev is None or (t or DONEM) >= (
                        parse_tarih(prev.get("belge_tarih")) or DONEM
                    ):
                        if yon == "GIRIS" or prev is None:
                            kalan_son[key] = {
                                **kayit,
                                "ilk_giris_tarih": (
                                    ozgun_giris_tarih
                                    or (prev or {}).get("ilk_giris_tarih")
                                ),
                            }
                        else:
                            kalan_son[key] = {
                                **kayit,
                                "ilk_giris_tarih": (prev or {}).get("ilk_giris_tarih"),
                            }
                            if prev and prev.get("ilk_giris_tarih"):
                                kalan_son[key]["ilk_giris_tarih"] = prev["ilk_giris_tarih"]

    # Giriş tarihi olan tekil lot oranı
    giris_tarihli = sum(1 for v in kalan_son.values() if v.get("ilk_giris_tarih") or v.get("ozgun_giris_tarih_aday"))
    out = {
        "format": "d1-dogrulama-lot-katman-devam-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "kesim_istanbul": KESIM,
        "lot_olay_adet": len(olaylar),
        "tekil_stok_lot": len(kalan_son),
        "miktar_kanit": "Seri_Lot_List a_giren/a_cikan/kalan_alan",
        "ozgun_giris_tarih_kanit": "Alış yönü (tur 30/32/…) belge tarihi",
        "giris_tarihli_lot_adet": giris_tarihli,
        "katman_maliyet": {
            "durum": "BEKLIYOR",
            "sayac": dict(maliyet_kanit),
            "gerekce": (
                "Seri_Lot_List’te katman birim maliyet yok. "
                "a_maliyet_fifo kart düzeyi; katman doğrulaması sayılmaz. "
                "Alış satır birim fiyatı yalnızca giriş ipucu."
            ),
        },
        "kalan_ornek": list(kalan_son.values())[:40],
        "sonuc": "KISMI",
        "k05": False,
    }
    yaz_kaynak("DOGRULAMA_LOT_KATMAN_DEVAM", out)
    return out


def stok_fark_derin() -> dict[str, Any]:
    """215/1063 farkları mevcut hareket+belge bağlamında sınıflandır (kart kalan = güncel uyarı)."""
    sm = _yukle("STOK_MALIYET")
    # UYARI: kart a_kalan görüntü anı olabilir; 31.08 kanıtı değil
    jsonl = STOK_HRK_JSONL
    sinif = Counter()
    ornek = defaultdict(list)
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        if o.get("status") != "OK":
            continue
        fark = o.get("kart_minus_hareket_net")
        if fark is None:
            continue
        fd = dec(fark)
        hrk = int(o.get("hareket_adet") or 0)
        tur = o.get("belge_tur_adet") or {}
        depolar = o.get("depo_adet") or {}
        birimler = o.get("birim_adet") or {}
        devir = int(o.get("devir_bayrakli_adet") or 0)
        # İade/iptal ipucu belge_tur adlarında
        tur_join = " ".join(str(k) for k in tur.keys()).lower()
        iade = any(x in tur_join for x in ("iade", "iad"))
        iptal = "iptal" in tur_join

        row = {
            "kaynak_stok_id": o.get("kaynak_stok_id"),
            "kod": o.get("kod"),
            "kart_kalan_goruntu_ani_uyari": o.get("kart_kalan"),
            "hareket_net_3108": o.get("hareket_net"),
            "fark_kart_minus_hrk": fark,
            "hareket_adet": hrk,
            "depo_adet": depolar,
            "birim_adet": birimler,
            "belge_tur_adet": tur,
            "devir_bayrakli_adet": devir,
            "iade_ipucu": iade,
            "iptal_ipucu": iptal,
            "uyari": (
                "kart_kalan API görüntü anına yakın olabilir; "
                "31.08 kapanış miktarı olarak kullanılmaz. Fark sınıflandırması tanı içindir."
            ),
        }
        if fd == 0:
            sinif["esit"] += 1
            continue
        if hrk == 0:
            sinif["hareket_bos_kart_dolu"] += 1
            key = "hareket_bos"
        elif len(depolar) > 1:
            sinif["coklu_depo"] += 1
            key = "coklu_depo"
        elif len(birimler) > 1:
            sinif["coklu_birim"] += 1
            key = "coklu_birim"
        elif devir > 0:
            sinif["devir_bayrakli"] += 1
            key = "devir"
        elif iade:
            sinif["iade_ipucu"] += 1
            key = "iade"
        elif iptal:
            sinif["iptal_ipucu"] += 1
            key = "iptal"
        else:
            sinif["diger_fark"] += 1
            key = "diger"
        if len(ornek[key]) < 12:
            ornek[key].append(row)

    out = {
        "format": "d1-dogrulama-stok-fark-derin-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "kesim_istanbul": KESIM,
        "kapsam": "STOK_HAREKET.jsonl (çekim anındaki kart kalan ile karşılaştırma — uyarılı)",
        "sinif": dict(sinif),
        "ornekler": dict(ornek),
        "yapay_duzeltme": False,
        "negatif_korundu": True,
        "sonuc": "KISMI_TANI",
        "k05": False,
        "not": (
            "215/1063 sayıları önceki 2522’lik çekime aitti. "
            "628 sıfır-bakiye kart hareketi ayrıca tamamlanır; "
            "güncel kart bakiyesi 31.08 envanter yerine geçmez."
        ),
    }
    yaz_kaynak("DOGRULAMA_STOK_FARK_DERIN", out)
    return out


def stok628_hareket(client, *, limit: int = 0) -> dict[str, Any]:
    from entegrasyon.evobulut_client import _ana_listesi

    st = _yukle("STOK_MIKTAR")
    have: set[str] = set()
    basarili: dict[str, dict] = {}
    if STOK_HRK_JSONL.is_file():
        for line in STOK_HRK_JSONL.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            o = json.loads(line)
            sid = str(o.get("kaynak_stok_id") or "")
            if sid and o.get("status") == "OK":
                have.add(sid)
                basarili[sid] = o

    eksik = []
    for r in st.get("kayitlar") or []:
        sid = str(r.get("a_id") or "")
        if sid and sid not in have:
            eksik.append(r)
    if limit:
        eksik = eksik[:limit]

    t0 = time.time()
    yeni = 0
    tmp = STOK_HRK_JSONL.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for o in basarili.values():
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
        for i, r in enumerate(eksik, 1):
            sid = str(r.get("a_id"))
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
                for h in ana:
                    t = parse_tarih(h.get("tarih"))
                    if t is not None and t > DONEM:
                        dis += 1
                        continue
                    ic.append(h)
                gir = sum((dec(h.get("gir_miktar")) for h in ic), Decimal("0"))
                cik = sum((dec(h.get("cik_miktar")) for h in ic), Decimal("0"))
                kart_kalan = dec(r.get("a_kalan"))
                net = gir - cik
                kayit = {
                    "kaynak_stok_id": sid,
                    "status": "OK",
                    "kod": r.get("a_kod"),
                    "adi": r.get("a_adi"),
                    "kart_kalan": str(kart_kalan),
                    "kart_giren": r.get("a_giren"),
                    "kart_cikan": r.get("a_cikan"),
                    "grup": "once_628_sifir_kalan_dahil",
                    "hareket_adet": len(ic),
                    "donem_sonrasi_atlanadi": dis,
                    "gir_toplam": str(gir),
                    "cik_toplam": str(cik),
                    "hareket_net": str(net),
                    "kart_minus_hareket_net": str(kart_kalan - net),
                    "depo_adet": dict(Counter(str(h.get("depo") or "") for h in ic)),
                    "birim_adet": dict(Counter(str(h.get("Birim") or "") for h in ic)),
                    "belge_tur_adet": dict(
                        Counter(str(h.get("belge_tur") or h.get("Tur") or "") for h in ic)
                    ),
                    "devir_bayrakli_adet": sum(
                        1
                        for h in ic
                        if str(h.get("devir") or "0") not in ("0", "", "None")
                    ),
                    "donem_sonu_dahil": DONEM.isoformat(),
                    "alim_zamani": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "uyari": "kart_kalan görüntü anı; 31.08 envanter yerine geçmez",
                }
                f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
                f.flush()
                basarili[sid] = kayit
                yeni += 1
            except Exception as exc:  # noqa: BLE001
                f.write(
                    json.dumps(
                        {
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
            if i % 25 == 0 or i == len(eksik):
                print(
                    f"stok628 {i}/{len(eksik)} yeni={yeni} ok={len(basarili)} "
                    f"gecen={time.time()-t0:.0f}s",
                    flush=True,
                )
            time.sleep(0.02)
    tmp.replace(STOK_HRK_JSONL)

    # Dönem kapsam özeti 3150
    sinif = Counter()
    for o in basarili.values():
        if o.get("status") != "OK":
            sinif["err"] += 1
            continue
        hrk = int(o.get("hareket_adet") or 0)
        if hrk == 0:
            sinif["hareket_yok"] += 1
        else:
            sinif["hareket_var"] += 1
        if dec(o.get("kart_kalan")) != 0 and hrk == 0:
            sinif["bos_hrk_kart_dolu"] += 1
        elif dec(o.get("kart_minus_hareket_net") or 0) != 0:
            sinif["fark_var"] += 1
        else:
            sinif["esit_veya_sifir_es"] += 1

    out = {
        "format": "d1-stok-hareket-3150-kapsam-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "kesim_istanbul": KESIM,
        "hedef_kart": 3150,
        "ok_adet": sum(1 for o in basarili.values() if o.get("status") == "OK"),
        "yeni_628": yeni,
        "sinif": dict(sinif),
        "tamam_mi": len(basarili) >= 3150,
        "jsonl": STOK_HRK_JSONL.name,
        "k05": False,
    }
    yaz_kaynak("STOK_HAREKET_3150_OZET", out)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--atla-stok628", action="store_true")
    p.add_argument("--stok-limit", type=int, default=0)
    args = p.parse_args(argv)

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    print("... rapor tablosu", flush=True)
    tab = gerekli_rapor_tablosu()
    print("... cari ortusme", flush=True)
    cari = cari_ortusme_analiz()
    print("... lot", flush=True)
    lot = lot_dogrulama()
    print("... stok fark derin", flush=True)
    fark = stok_fark_derin()

    stok = None
    if not args.atla_stok628:
        print("... stok 628+ kapsami", flush=True)
        from entegrasyon.evobulut_client import EvobulutClient, load_credentials, _uid_bul

        creds = load_credentials()
        client = EvobulutClient(creds)
        y = client._post(
            "index/base/",
            {
                "cmd": "euas",
                "p1": creds.kullanici_kodu,
                "p2": creds.sifre,
                "app": creds.app,
            },
        )
        client.uid = _uid_bul(y)
        stok = stok628_hareket(client, limit=args.stok_limit)

    ozet = {
        "format": "d1-kaynak-dogrulama-devam2-ozet-v1",
        "zaman": now,
        "firma": {"no": "42178", "adi": "DNM – RAY MOBİLYA AKSESUARLAR ETÜD"},
        "donem_sonu_dahil": DONEM.isoformat(),
        "kesim_istanbul": KESIM,
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "exe_paket": False,
        "ilk_gerekli_rapor": tab["ilk_alinacak"],
        "dogrulanan": [
            {
                "madde": "cari_ortusme_tekil",
                "birlesim": cari["ortusme"]["birlesim_tekil"],
                "ayri": cari["grup_adetleri_ayri"],
                "kanit": "DOGRULAMA_CARI_ORTUSME.json",
            },
            {
                "madde": "lot_miktar_tarih_kismi",
                "olay": lot["lot_olay_adet"],
                "tekil": lot["tekil_stok_lot"],
                "giris_tarihli": lot["giris_tarihli_lot_adet"],
                "kanit": "DOGRULAMA_LOT_KATMAN_DEVAM.json",
            },
            {
                "madde": "stok_fark_sinif_tanisi",
                "sinif": fark["sinif"],
                "kanit": "DOGRULAMA_STOK_FARK_DERIN.json",
            },
        ],
        "acik": [
            {
                "madde": "15_cari_3108_kanit",
                "durum": "EKSIK — Detay/açılış yok; Özet 31.08 sayılmadı",
            },
            {
                "madde": "lot_katman_maliyet",
                "durum": lot["katman_maliyet"]["durum"],
            },
            {
                "madde": "stok_3150_hareket",
                "durum": (stok or {}).get("sinif") or "atlanmadi",
                "ok": (stok or {}).get("ok_adet"),
            },
            {"madde": "K06_EXE", "durum": "ERTELI"},
        ],
    }
    yaz_json(CALISMA / "KAYNAK_DOGRULAMA_DEVAM2_OZET.json", ozet)

    durum_yol = CALISMA / "DURUM.json"
    durum = json.loads(durum_yol.read_text(encoding="utf-8")) if durum_yol.is_file() else {}
    durum.update(
        {
            "guncelleme": now,
            "ozet": (
                f"Cari birleşim tekil={cari['ortusme']['birlesim_tekil']} "
                f"(15∩22={cari['ortusme']['15_∩_22']}; toplanmadı). "
                f"LOT olay={lot['lot_olay_adet']}; maliyet BEKLIYOR. "
                f"Stok3150 ok={(stok or {}).get('ok_adet')}. "
                f"İlk gereken: finans_jq Detay/ekstre ≤31.08. K05 kapalı."
            ),
            "k05": False,
            "k06": False,
            "dogrulama_devam2": "KAYNAK_DOGRULAMA_DEVAM2_OZET.json",
            "kullanici_adimi_gerekli": [
                "İlk: Cari hesap ekstresi (finans_jq Detay) — 15/22 risk, bitiş 31.08.2026",
                "K06 ANA DB erteli",
            ],
            "eksik_k05": [
                "31.08 kanıtlı cari kapanış (Özet değil)",
                "LOT katman maliyeti",
                "Stok kart kalanının 31.08 envanter kanıtı (görüntü anı ≠ kapanış)",
                "K06/EXE erteli",
            ],
        }
    )
    yaz_json(durum_yol, durum)

    print(
        json.dumps(
            {
                "k05": False,
                "cari_birlesim": cari["ortusme"],
                "lot": lot["tekil_stok_lot"],
                "stok_ok": (stok or {}).get("ok_adet"),
                "ilk_rapor": tab["ilk_alinacak"]["kaynak_dogrulanmis_ad"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
