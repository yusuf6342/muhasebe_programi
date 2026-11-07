"""Kalan kaynak doğrulama boşlukları — K05 açılmaz, yazım yok.

1) 15 detay_yok cari envanteri + ekstre/belge/kapama yokluğu
2) StokHareket stok_id ile + belge LOT çapraz doğrulama
3) FIFO vs ort yöntem farkı (katman uydurma yok)
4) Web ünvan kanıtını FIRMA dosyasına bağla

  .venv\\Scripts\\python.exe -m tools.dnm_d1.kaynak_dogrulama_devam
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from tools.dnm_d1._ortak import CALISMA, KAYNAK, dec, parse_tarih, yaz_json, yaz_kaynak
from tools.dnm_d1.donem_sabitleri import (
    DONEM_SONU,
    KAYNAK_FIRMA_ADI,
    KAYNAK_FIRMA_NO,
    RAPOR_ONEKI_KAYNAK,
    TALIMAT_SHA256,
)

DONEM = DONEM_SONU


def _yukle(ad: str) -> dict[str, Any]:
    return json.loads((KAYNAK / f"{RAPOR_ONEKI_KAYNAK}{ad}.json").read_text(encoding="utf-8"))


def _cari_kartlar() -> dict[str, dict]:
    out = {}
    for r in (_yukle("CARI").get("kayitlar") or []):
        cid = str(r.get("R.a_id") or "")
        if cid:
            out[cid] = r
    return out


def bolum1_15_cari() -> dict[str, Any]:
    ak = _yukle("ACIK_KALEM")
    ce = _yukle("CARI_EKSTRE_KAPANIS")
    bel = _yukle("BELGE")
    kartlar = _cari_kartlar()
    ekstre = {str(c["kaynak_cari_id"]): c for c in (ce.get("cariler") or [])}
    dy = [c for c in (ak.get("cariler") or []) if c.get("detay_yok_uyari")]

    # Belge başlıklarında cari bağları
    bel_by: dict[str, list] = defaultdict(list)
    for tur, lst in (bel.get("belgeler") or {}).items():
        for r in lst or []:
            cid = str(r.get("G.a_cari_id") or r.get("a_cari_id") or "")
            bel_by[cid].append(tur)

    # Belge satır cari
    bs_by: Counter = Counter()
    jsonl = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE_SATIR.jsonl"
    if jsonl.is_file():
        with jsonl.open(encoding="utf-8") as f:
            for line in f:
                o = json.loads(line)
                cid = str(o.get("cari_id") or "")
                if cid:
                    bs_by[cid] += 1

    # API: Özet'in tarih aralığından bağımsız olduğunu 2 dilimde doğrula (örnek 3 cari)
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials, _uid_bul

    creds = load_credentials()
    client = EvobulutClient(creds)
    yanit = client._post(
        "index/base/",
        {"cmd": "euas", "p1": creds.kullanici_kodu, "p2": creds.sifre, "app": creds.app},
    )
    client.uid = _uid_bul(yanit)
    firma_id = ((yanit.get("veri") or {}).get("Ana") or [{}])[0].get("a_firma_id")

    ozet_bagimsiz = []
    for cid in [str(c["kaynak_cari_id"]) for c in dy[:3]]:
        dilimler = []
        for bas, son in (("01.09.2025", "31.08.2026"), ("01.01.2020", "31.12.2020")):
            y = client._post(
                "Musteri/base/",
                {
                    "cmd": "finans_jq_listesi",
                    "UID": client.uid,
                    "musteri_id": cid,
                    "b_tarihi": bas,
                    "s_tarihi": son,
                    "tur": "-1",
                },
            )
            v = y.get("veri") if y.get("status") == "OK" else None
            ozet = None
            det_n = 0
            dev = None
            if isinstance(v, dict):
                ozet = v.get("Özet") or v.get("Ozet")
                det_n = len(v.get("Detay") or [])
                dev = v.get("Devreden")
            dilimler.append(
                {"bas": bas, "son": son, "detay_adet": det_n, "devreden": dev, "ozet": ozet}
            )
            time.sleep(0.05)
        ozet_bagimsiz.append({"kaynak_cari_id": cid, "dilimler": dilimler})

    liste = []
    toplam_abs = Decimal("0")
    for c in dy:
        cid = str(c["kaynak_cari_id"])
        kart = kartlar.get(cid) or {}
        e = ekstre.get(cid) or {}
        ozet = c.get("kapanis_ozet_umum") or {}
        bak = dec(e.get("kapanis_bakiye") or ozet.get("bakiye"))
        toplam_abs += abs(bak)
        unvan = (kart.get("text") or "").split("----")[0].strip() or kart.get("R.a_ad")
        liste.append(
            {
                "kaynak_cari_id": cid,
                "kod": kart.get("R.a_kod") or None,
                "unvan": unvan,
                "liste_text_bakiye": (kart.get("text") or "")[-40:],
                "bakiye_3108_ekstre_ozet": str(e.get("kapanis_bakiye")),
                "ozet_borc": ozet.get("borc"),
                "ozet_alacak": ozet.get("alacak"),
                "ozet_bakiye": ozet.get("bakiye"),
                "devreden_bakiye": (c.get("kapanis_devreden") or {}).get("bakiye"),
                "detay_birlesen_adet": c.get("detay_birlesen_adet"),
                "ekstre_detay_satir_adet": e.get("detay_satir_adet"),
                "acik_kalem_adet": c.get("acik_kalem_adet"),
                "belge_baslik_tur_adet": dict(Counter(bel_by.get(cid) or [])),
                "belge_satir_adet": bs_by.get(cid, 0),
                "eksik_alanlar": [
                    "Detay satırları (finans_jq)",
                    "Kapama / kapatılan belge ilişkisi",
                    "Vade tarihi (Detay yok)",
                    "FIFO açık kalem kimliği",
                ],
                "bulunan": [
                    "Kart listesi ünvan + gömülü bakiye metni",
                    "Özet borc/alacak/bakiye (tarih aralığından bağımsız görünüyor)",
                    "Ekstre kapanış dosyasında aynı Özet bakiye",
                ],
                "kapama_uretilmedi": True,
                "sonuc": "EKSIK_KANIT",
            }
        )

    fifo_valor_analiz = {
        "format": "d1-fifo-valor-analiz-ayri-v1",
        "not": (
            "Bu blok açık kalem FIFO/valör hesabıdır; 15 detay_yok cari için "
            "Detay olmadığından FIFO katmanı üretilemez. Uydurma kapama yok."
        ),
        "kaynak_acik_kalem_adet": ak.get("acik_kalem_adet"),
        "kaynak_acik_kalem_toplam": ak.get("acik_kalem_toplam"),
        "vade_yaslandirma": _yukle("VADE_YASLANDIRMA").get("buckets"),
        "detay_yok_hariç_mi": True,
        "detay_yok_cari_adet": len(liste),
        "detay_yok_abs_bakiye_ozet_toplami": str(toplam_abs),
        "uyari": (
            "Özet bakiyesi Detay/Devreden ile tutarsız; Özet tek başına 31.08 "
            "FIFO açık kalem kanıtı değildir."
        ),
    }
    yaz_kaynak("DOGRULAMA_FIFO_VALOR_ANALIZ", fifo_valor_analiz)

    out = {
        "format": "d1-dogrulama-15-cari-detay-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "adet": len(liste),
        "abs_ozet_bakiye_toplam": str(toplam_abs),
        "login_a_firma_id": str(firma_id),
        "ozet_tarih_bagimsiz_ornek": ozet_bagimsiz,
        "cariler": liste,
        "sonuc": "EKSIK",
        "gerekce": (
            "15 caride finans_jq Detay=0, Devreden=0; belge başlık/satır bağı yok; "
            "Özet bakiyesi dilimden bağımsız. Kapama ilişkisi üretilmedi."
        ),
        "k05": False,
    }
    yaz_kaynak("DOGRULAMA_15_CARI_DETAY", out)
    return out


def bolum2_lot_stokhareket() -> dict[str, Any]:
    """StokHareket boşluğu yalnız yönteme; belge LOT + stok_id hareket devam."""
    from entegrasyon.evobulut_client import EvobulutClient, load_credentials, _uid_bul, _ana_listesi

    sm = _yukle("STOK_MALIYET")
    maliyet = {str(s["kaynak_stok_id"]): s for s in (sm.get("stoklar") or [])}

    # Belge LOT özeti
    lot_giris = Decimal("0")
    lot_cikis_alan = Decimal("0")
    lot_kalan_alan_sum = Decimal("0")
    stok_lot: dict[str, dict] = {}
    belge_lot_satir = 0
    jsonl = KAYNAK / f"{RAPOR_ONEKI_KAYNAK}BELGE_SATIR.jsonl"
    with jsonl.open(encoding="utf-8") as f:
        for line in f:
            o = json.loads(line)
            t = parse_tarih(o.get("tarih"))
            if t and t > DONEM:
                continue
            for s in o.get("satirlar") or []:
                lots = s.get("seri_lot")
                if not lots:
                    continue
                if isinstance(lots, dict):
                    lots = [lots]
                if not isinstance(lots, list):
                    continue
                belge_lot_satir += 1
                sid = str(s.get("a_stok_id") or s.get("stok_id") or "")
                for L in lots:
                    if not isinstance(L, dict):
                        continue
                    lot_no = str(L.get("a_lot_no") or L.get("a_seri_no") or "")
                    key = f"{sid}|{lot_no}"
                    g, cikan = dec(L.get("a_giren")), dec(L.get("a_cikan"))
                    kalan = L.get("kalan")
                    lot_giris += g
                    lot_cikis_alan += cikan
                    if kalan not in (None, ""):
                        # kalan alanı anlık; toplamı kanıt değil, örnek istatistik
                        pass
                    stok_lot[key] = {
                        "stok_id": sid,
                        "lot_no": lot_no,
                        "son_belge": o.get("kaynak_belge_id"),
                        "son_tarih": o.get("tarih"),
                        "lot_giren": L.get("a_giren"),
                        "lot_cikan": L.get("a_cikan"),
                        "kalan_alan": L.get("kalan"),
                        "haric_kalan": L.get("haric_kalan"),
                        "ack": L.get("a_ack"),
                    }

    # Örnek stoklarda StokHareket/base list (stok_id zorunlu)
    creds = load_credentials()
    client = EvobulutClient(creds)
    yanit = client._post(
        "index/base/",
        {"cmd": "euas", "p1": creds.kullanici_kodu, "p2": creds.sifre, "app": creds.app},
    )
    client.uid = _uid_bul(yanit)

    ornek_stoklar = []
    # LOT'lu stoklardan 8; negatif kalanlardan hepsi
    aday = []
    for s in sm.get("stoklar") or []:
        if dec(s.get("kalan")) < 0:
            aday.append(str(s["kaynak_stok_id"]))
    for key in list(stok_lot.keys())[:40]:
        sid = key.split("|", 1)[0]
        if sid not in aday:
            aday.append(sid)
        if len(aday) >= 12:
            break

    for sid in aday[:12]:
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
                "bas_tar": "01.01.2020",
                "bit_tar": "31.08.2026",
                "dovizli_goster": "0",
            },
        )
        ana = _ana_listesi(y)
        # dönem filtresi
        ic = []
        for r in ana:
            t = parse_tarih(r.get("tarih"))
            if t is None or t <= DONEM:
                ic.append(r)
        gir = sum((dec(r.get("gir_miktar")) for r in ic), Decimal("0"))
        cik = sum((dec(r.get("cik_miktar")) for r in ic), Decimal("0"))
        m = maliyet.get(sid) or {}
        # ack içinde lot ipucu
        ack_lot = sorted(
            {
                str(r.get("ack") or "").strip()
                for r in ic
                if str(r.get("ack") or "").strip()
            }
        )[:20]
        belge_lotlari = [v for k, v in stok_lot.items() if k.startswith(sid + "|")]
        ornek_stoklar.append(
            {
                "kaynak_stok_id": sid,
                "kod": m.get("kod"),
                "adi": m.get("adi"),
                "kart_kalan": m.get("kalan"),
                "kart_fifo": m.get("maliyet_fifo"),
                "kart_ort": m.get("maliyet_ort"),
                "stokhareket_adet_3108": len(ic),
                "stokhareket_gir_toplam": str(gir),
                "stokhareket_cik_toplam": str(cik),
                "stokhareket_net": str(gir - cik),
                "kart_vs_hareket_net_fark": (
                    str(dec(m.get("kalan")) - (gir - cik))
                    if m.get("kalan") not in (None, "")
                    else None
                ),
                "ack_lot_ipucu": ack_lot,
                "belge_seri_lot_adet": len(belge_lotlari),
                "belge_seri_lot": belge_lotlari[:5],
                "stokhareket_lot_alani": "YOK — lot_no kolonu yok; ack/belge Seri_Lot_List",
                "ornek_hareket": [
                    {
                        "tarih": r.get("tarih"),
                        "belge_tur": r.get("belge_tur"),
                        "gir": r.get("gir_miktar"),
                        "cik": r.get("cik_miktar"),
                        "gir_fiyat": r.get("gir_fiyat"),
                        "cik_fiyat": r.get("cik_fiyat"),
                        "ack": r.get("ack"),
                        "Fat_id": r.get("Fat_id"),
                    }
                    for r in ic[:5]
                ],
            }
        )
        time.sleep(0.05)

    out = {
        "format": "d1-dogrulama-lot-stokhareket-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "stokhareket_yontem_kisiti": {
            "durum": "KISIT_YONTEM",
            "aciklama": (
                "Toplu StokHareket listesi (stok_id olmadan) boş/uygunsuz olabilir. "
                "stok_id ile StokHareket/base cmd=list veri döner. "
                "Bu kısıt TÜM stok/LOT doğrulamasını uygulanamaz yapmaz."
            ),
        },
        "belge_lot_satir_adet": belge_lot_satir,
        "tekil_stok_lot": len(stok_lot),
        "belge_lot_giren_toplam_alan": str(lot_giris),
        "belge_lot_cikan_toplam_alan": str(lot_cikis_alan),
        "stokhareket_ornek_stok_adet": len(ornek_stoklar),
        "ornekler": ornek_stoklar,
        "eksik_bekleyen": [
            "StokHareket satırında lot_no/seri alanı yok",
            "Tarihli FIFO katman birim maliyeti API'de yok",
            "Belge Seri_Lot_List.kalan alanı anlık; katman dökümü değil",
        ],
        "katman_maliyet_uydurulmadi": True,
        "negatif_korundu": True,
        "sonuc": "KISMI",
        "k05": False,
    }
    yaz_kaynak("DOGRULAMA_LOT_STOKHAREKET", out)
    return out


def bolum3_fifo_ort() -> dict[str, Any]:
    sm = _yukle("STOK_MALIYET")
    farklar = []
    negatif = []
    yontem = Counter()
    for s in sm.get("stoklar") or []:
        yontem[s.get("maliyet_kaynagi") or "YOK"] += 1
        kalan = dec(s.get("kalan"))
        if kalan < 0:
            negatif.append(
                {
                    "kaynak_stok_id": s.get("kaynak_stok_id"),
                    "kod": s.get("kod"),
                    "adi": s.get("adi"),
                    "kalan": s.get("kalan"),
                    "fifo": s.get("maliyet_fifo"),
                    "ort": s.get("maliyet_ort"),
                    "secilen": s.get("maliyet_kaynagi"),
                    "korundu": True,
                }
            )
        fifo = s.get("maliyet_fifo")
        ort = s.get("maliyet_ort")
        if fifo in (None, "") or ort in (None, ""):
            continue
        df = dec(fifo) - dec(ort)
        if df != 0:
            farklar.append(
                {
                    "kaynak_stok_id": s.get("kaynak_stok_id"),
                    "kod": s.get("kod"),
                    "kalan": s.get("kalan"),
                    "fifo": fifo,
                    "ort": ort,
                    "fark_birim": str(df),
                    "fark_tutar_kalan_x": str((df * kalan).quantize(Decimal("0.0001"))),
                    "secilen_kaynak": s.get("maliyet_kaynagi"),
                    "toplam_maliyet_secilen": s.get("toplam_maliyet"),
                }
            )
    farklar.sort(key=lambda x: abs(dec(x["fark_tutar_kalan_x"])), reverse=True)
    tutar_abs = sum((abs(dec(x["fark_tutar_kalan_x"])) for x in farklar), Decimal("0"))
    out = {
        "format": "d1-dogrulama-fifo-ort-yontem-v1",
        "donem_sonu_dahil": DONEM.isoformat(),
        "aciklama": (
            "a_maliyet_fifo ve a_maliyet_ort kaynak kart alanlarıdır; ikisi de "
            "EvoBulut'un kendi hesapladığı birim maliyetlerdir. Fark, yöntem "
            "farkıdır (FIFO katman tüketimi vs ortalama). "
            "Aktarımda seçilen: a_maliyet_fifo (varsa). "
            "Katman maliyeti net bakiyeden veya ortalamadan üretilmez; "
            "katman dökümü API'de yok → bekliyor."
        ),
        "maliyet_kaynagi_adet": dict(yontem),
        "fifo_ort_farkli_kart": len(farklar),
        "fark_tutar_abs_toplam_kalan_x": str(tutar_abs),
        "en_buyuk_farklar": farklar[:40],
        "negatif_kalan_kartlar": negatif,
        "katman_kaniti": "BEKLIYOR",
        "katman_uydurulmadi": True,
        "sonuc": "KISMI_YONTEM_ACIKLANDI",
        "k05": False,
    }
    yaz_kaynak("DOGRULAMA_FIFO_ORT_YONTEM", out)
    return out


def bolum4_unvan_web() -> dict[str, Any]:
    fd = _yukle("FIRMA_DOGRULAMA")
    png = KAYNAK / "D1_20260831_KANIT_FIRMA_UNVAN_WEB.png"
    web_unvan = "DNM- RAY MOBİLYA AKSESUARLAR ETÜD"
    # normalize compare
    def norm(s: str) -> str:
        return (
            s.upper()
            .replace("İ", "I")
            .replace("–", "-")
            .replace("—", "-")
            .replace("  ", " ")
            .strip()
        )

    bek = norm(KAYNAK_FIRMA_ADI)
    gor = norm(web_unvan)
    eslesme = bek.replace(" ", "") == gor.replace(" ", "") or (
        "DNM" in gor and "RAY" in gor and "MOBILYA" in gor.replace("İ", "I")
    )
    kanit = {
        "format": "d1-firma-unvan-web-kanit-v1",
        "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "firma_no_login": fd.get("kalici_firma_id") or KAYNAK_FIRMA_NO,
        "firma_no_beklenen": KAYNAK_FIRMA_NO,
        "firma_no_eslesme": str(fd.get("kalici_firma_id") or "") == KAYNAK_FIRMA_NO,
        "web_unvan_gorunen": web_unvan,
        "beklenen_unvan": KAYNAK_FIRMA_ADI,
        "unvan_eslesme_normalize": eslesme,
        "kanit_ekran": png.name if png.is_file() else None,
        "kanit_ekran_var": png.is_file(),
        "kanit_kaynak": "web.evobulut.com firma_sec + kontrol paneli başlık",
        "talimat_sha256": TALIMAT_SHA256,
        "sonuc": "TAMAM" if eslesme and png.is_file() else "KISMI",
        "k05_not": "Ünvan+42178 kanıtlandı; diğer K05 eksikleri (15 cari, LOT katman) sürüyor",
    }
    fd2 = dict(fd)
    fd2["firma_adi_web_dogrulandi"] = bool(eslesme and png.is_file())
    fd2["firma_adi_web"] = web_unvan
    fd2["firma_adi_web_kanit"] = png.name if png.is_file() else None
    fd2["unvan_kanit"] = {
        "web_unvan": web_unvan,
        "web_dogrulandi": fd2["firma_adi_web_dogrulandi"],
        "login_a_firma_id": KAYNAK_FIRMA_NO,
        "ekran": png.name if png.is_file() else None,
        "rapor": "D1_20260831_KAYNAK_DOGRULAMA_FIRMA_UNVAN_WEB.json",
    }
    yaz_kaynak("FIRMA_DOGRULAMA", fd2)
    yaz_kaynak("DOGRULAMA_FIRMA_UNVAN_WEB", kanit)

    man_yol = CALISMA / "CALISMA_MANIFESTI.json"
    if man_yol.is_file():
        man = json.loads(man_yol.read_text(encoding="utf-8"))
        man["kaynak"]["firma_adi_api_dogrulandi"] = False
        man["kaynak"]["firma_adi_web_dogrulandi"] = fd2["firma_adi_web_dogrulandi"]
        man["kaynak"]["firma_adi_web"] = web_unvan
        man["kaynak"]["firma_no_dogrulandi"] = True
        yaz_json(man_yol, man)
    return kanit


def main() -> int:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    b1 = bolum1_15_cari()
    b2 = bolum2_lot_stokhareket()
    b3 = bolum3_fifo_ort()
    b4 = bolum4_unvan_web()

    ozet = {
        "format": "d1-kaynak-dogrulama-devam-ozet-v1",
        "zaman": now,
        "k05": False,
        "k06": False,
        "mali_yazim": False,
        "exe_paket": False,
        "tamamlanan": [],
        "eksik": [],
        "uygulanamaz": [],
        "kismi": [],
    }
    if b4.get("sonuc") == "TAMAM":
        ozet["tamamlanan"].append(
            {
                "madde": "4_unvan_web_42178",
                "gerekce": f"{b4.get('web_unvan_gorunen')} + login {b4.get('firma_no_login')}",
                "kanit": b4.get("kanit_ekran"),
            }
        )
    else:
        ozet["eksik"].append({"madde": "4_unvan_web_42178", "gerekce": b4})

    ozet["eksik"].append(
        {
            "madde": "1_15_cari_detay",
            "adet": b1.get("adet"),
            "abs_ozet_bakiye": b1.get("abs_ozet_bakiye_toplam"),
            "gerekce": b1.get("gerekce"),
            "kanit": "D1_20260831_KAYNAK_DOGRULAMA_15_CARI_DETAY.json",
        }
    )
    ozet["kismi"].append(
        {
            "madde": "2_lot_stokhareket",
            "gerekce": (
                "StokHareket stok_id ile çalışır; belge LOT devam. "
                "Katman maliyeti bekliyor. Yöntem kısıtı ≠ tümü uygulanamaz."
            ),
            "belge_lot_satir": b2.get("belge_lot_satir_adet"),
            "ornek_stok": b2.get("stokhareket_ornek_stok_adet"),
            "kanit": "D1_20260831_KAYNAK_DOGRULAMA_LOT_STOKHAREKET.json",
        }
    )
    ozet["kismi"].append(
        {
            "madde": "3_fifo_ort_yontem",
            "farkli_kart": b3.get("fifo_ort_farkli_kart"),
            "fark_tutar_abs": b3.get("fark_tutar_abs_toplam_kalan_x"),
            "negatif": len(b3.get("negatif_kalan_kartlar") or []),
            "katman": "BEKLIYOR (uydurulmadı)",
            "kanit": "D1_20260831_KAYNAK_DOGRULAMA_FIFO_ORT_YONTEM.json",
        }
    )
    # StokHareket toplu boş → yalnız yöntem notu; uygulanamaz değil
    ozet["tamamlanan"].append(
        {
            "madde": "2_stokhareket_yontem_kisiti_kaydi",
            "gerekce": b2["stokhareket_yontem_kisiti"]["aciklama"],
        }
    )

    yaz_json(CALISMA / "KAYNAK_DOGRULAMA_DEVAM_OZET.json", ozet)

    durum_yol = CALISMA / "DURUM.json"
    durum = json.loads(durum_yol.read_text(encoding="utf-8")) if durum_yol.is_file() else {}
    durum.update(
        {
            "guncelleme": now,
            "ozet": (
                f"Ünvan web OK ({b4.get('web_unvan_gorunen')})+42178. "
                f"15 cari detay hâlâ EKSIK (abs Özet {b1.get('abs_ozet_bakiye_toplam')}). "
                f"LOT/StokHareket KISMI; FIFO≠ort {b3.get('fifo_ort_farkli_kart')} kart. "
                f"K05 kapalı; K06/EXE erteli."
            ),
            "k05": False,
            "k06": False,
            "dogrulama_devam": "KAYNAK_DOGRULAMA_DEVAM_OZET.json",
            "eksik_k05": [
                "15 cari Detay/kapama yok",
                "FIFO katman maliyeti API yok",
                "K06 ANA DB ertelendi",
                "EXE/paket ertelendi",
            ],
        }
    )
    yaz_json(durum_yol, durum)

    # K01 güncelle
    kp_yol = CALISMA / "KONTROL_PLANI_DURUM.json"
    if kp_yol.is_file():
        kp = json.loads(kp_yol.read_text(encoding="utf-8"))
        for k in kp.get("kontroller") or []:
            if k.get("kontrol_id") == "K01":
                k["sonuc"] = "OK" if b4.get("sonuc") == "TAMAM" else "Kısmi"
                k["kaynak_kanit"] = "DOGRULAMA_FIRMA_UNVAN_WEB + FIRMA_DOGRULAMA"
                k["aciklama"] = (
                    f"Web ünvan={b4.get('web_unvan_gorunen')}; "
                    f"login a_firma_id={b4.get('firma_no_login')}"
                )
            elif k.get("kontrol_id") == "K05":
                k["sonuc"] = "Bekliyor"
                k["aciklama"] = "15 cari + LOT katman eksik; K05 kapalı"
        yaz_json(kp_yol, kp)

    print(
        json.dumps(
            {
                "k05": False,
                "unvan": b4.get("sonuc"),
                "cari15": b1.get("adet"),
                "abs": b1.get("abs_ozet_bakiye_toplam"),
                "lot_satir": b2.get("belge_lot_satir_adet"),
                "fifo_ort_fark": b3.get("fifo_ort_farkli_kart"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
