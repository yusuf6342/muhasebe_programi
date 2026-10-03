"""Stok 851'e (2608101620349) lot_id=1 ile bağlı 6 hareketi kaynak belgeleriyle doğrular (salt okunur).

Her hareket için: kaynak belge (fatura / paket fişi), satırlar, cari hareketi, finans hareketi,
muhasebe fişi ve muhasebe belge durumu, oluşturan kullanıcı, tarih, tutar, açıklama, cari kartın
gerçeklik göstergeleri (başka kayıtlarla ilişkisi) ve stok birleştirme izi toplanır.

Bir hareket yalnız şu koşulların TAMAMI sağlanırsa "kesin test" sayılır:
  * cari veya ürün kartı test kartıdır (kod/ad "TEST" ile başlar) VEYA belge açıklaması "test" içerir,
  * cari kartın bu belgeler dışında finans / cari / başka belge bağı yoktur,
  * aynı belgede başka ürünlerin stok hareketi yoktur.
Kesin olmayan hiçbir kayda yazılmaz; sonuç ``inceleme\\stoklar\\stok851_dogrulama.json``.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SONUC = ROOT / "inceleme" / "stoklar" / "stok851_dogrulama.json"
STOK_ID, LOT_ID = 851, 1
BELGELER = ("ARAY000001", "SRAY000001", "SRAY000003", "SRAY000004", "PKT000001")
GIRIS = ("GİRİŞ", "FATURA GİRİŞ", "İADE GİRİŞ", "TRANSFER GİRİŞ", "PAKET GİRİŞ", "SAYIM GİRİŞ", "İRSALİYE İADE GİRİŞ")
CIKIS = ("FATURA ÇIKIŞ", "ÇIKIŞ", "TRANSFER ÇIKIŞ", "PAKET ÇIKIŞ", "SAYIM ÇIKIŞ", "İRSALİYE ÇIKIŞ")


def _rows(c, sql, *a) -> list[dict]:
    try:
        return [dict(r) for r in c.execute(sql, a)]
    except sqlite3.Error as hata:
        return [{"_hata": str(hata)}]


def _kolonlar(c, t) -> set[str]:
    return {r[1] for r in c.execute(f'PRAGMA table_info("{t}")')}


def _test_gibi(*metinler) -> bool:
    return any("test" in (m or "").casefold() for m in metinler)


def cari_kanit(c, cari_id: int, belge_nolari: set[str]) -> dict:
    kart = (_rows(c, "SELECT id, cari_kodu, unvan, cari_turu, aktif FROM cari_kartlar WHERE id=?", cari_id) or [{}])[0]
    baglar = {}
    for t, kosul in (
        ("satis_faturalari", "cari_id=? AND fatura_no NOT IN ({})"),
        ("alis_faturalari", "cari_id=? AND fatura_no NOT IN ({})"),
        ("cari_islemleri", "cari_id=?"),
        ("cari_satis_hareketleri", "cari_id=? AND COALESCE(belge_no,'') NOT IN ({})"),
        ("kasa_makbuzlari", "cari_id=?"),
        ("satis_iade_faturalari", "cari_id=?"),
        ("alis_iade_faturalari", "cari_id=?"),
    ):
        ph = ",".join("?" * len(belge_nolari))
        sql = f"SELECT COUNT(*) n FROM {t} WHERE " + kosul.format(ph)
        args = (cari_id, *sorted(belge_nolari)) if "{}" in kosul else (cari_id,)
        r = _rows(c, sql, *args)
        if r and "n" in r[0] and r[0]["n"]:
            baglar[t] = r[0]["n"]
    test_aciklamali = _rows(c, "SELECT belge_no, islem_turu, aciklama FROM cari_islemleri "
                               "WHERE cari_id=? AND LOWER(aciklama) LIKE '%test%'", cari_id)
    return {
        "kart": kart,
        "test_karti": _test_gibi(kart.get("cari_kodu"), kart.get("unvan")),
        "bu_belgeler_disindaki_baglar": baglar,
        "test_aciklamali_cari_islemleri": test_aciklamali,
        "gercek_bag_var": bool(baglar),
    }


def belge_kanit(c, no: str) -> dict:
    k: dict = {"belge_no": no}
    if no.startswith("SRAY"):
        f = (_rows(c, "SELECT * FROM satis_faturalari WHERE fatura_no=?", no) or [{}])[0]
        k["tur"] = "Satış faturası"
        k["fatura"] = {a: f.get(a) for a in ("id", "fatura_no", "fatura_tarihi", "cari_id", "durum", "onaylandi",
                                             "tl_genel_toplam", "tahsilat_tutari", "tahsilat_sekli", "aciklama",
                                             "olusturma_tarihi", "created_by_username", "created_by_user_id")}
        k["satirlar"] = _rows(c, "SELECT id, urun_kodu, urun_adi, barkod, miktar, birim, birim_fiyat, lot_cikisi, "
                                 "fifo_birim_maliyeti FROM satis_faturasi_satirlari WHERE fatura_id=?", f.get("id"))
        evrak_turu, kaynak_id = "satis_faturasi", f.get("id")
    elif no.startswith("ARAY"):
        f = (_rows(c, "SELECT * FROM alis_faturalari WHERE fatura_no=?", no) or [{}])[0]
        k["tur"] = "Alış faturası"
        k["fatura"] = {a: f.get(a) for a in ("id", "fatura_no", "fatura_tarihi", "cari_id", "durum", "odeme_tutari",
                                             "aciklama", "olusturma_tarihi", "tedarikci_fatura_no")}
        k["satirlar"] = _rows(c, "SELECT id, urun_kodu, urun_adi, barkod, miktar, birim, birim_fiyat, lot_girisi "
                                 "FROM alis_faturasi_satirlari WHERE fatura_id=?", f.get("id"))
        evrak_turu, kaynak_id = "alis_faturasi", f.get("id")
    else:
        f = (_rows(c, "SELECT * FROM stok_paket_uretimleri WHERE fis_no=?", no) or [{}])[0]
        k["tur"] = "Paket üretim fişi"
        k["fatura"] = f
        k["satirlar"] = _rows(c, "SELECT * FROM stok_paket_bilesenleri WHERE paket_stok_id=?", f.get("paket_stok_id"))
        evrak_turu, kaynak_id = None, f.get("id")
    k["kullanici"] = (k["fatura"].get("created_by_username") or "kayıtlı değil (belge tablosunda kullanıcı izi yok)")
    k["cari_hareketleri"] = _rows(c, "SELECT id, cari_id, satis_tarihi, satis_tutari FROM cari_satis_hareketleri "
                                     "WHERE belge_no=?", no)
    k["finans_hareketleri"] = _rows(c, "SELECT id, hesap_id, tarih, hareket_turu, tutar, aciklama FROM "
                                       "finans_hareketleri WHERE belge_no=?", no)
    mf = _kolonlar(c, "muhasebe_fisleri")
    kosul = "belge_no=?" + (" OR (kaynak_turu=? AND kaynak_id=?)" if {"kaynak_turu", "kaynak_id"} <= mf else "")
    args = (no, evrak_turu, kaynak_id) if "kaynak_turu" in kosul else (no,)
    k["muhasebe_fisleri"] = _rows(c, f"SELECT id, fis_no, fis_tarihi, durum, toplam_borc, kaynak_turu, kaynak_id "
                                     f"FROM muhasebe_fisleri WHERE {kosul}", *args)
    k["muhasebe_belge_durumu"] = _rows(c, "SELECT evrak_turu, kaynak_id, durum, aciklama FROM muhasebe_belge_durumlari "
                                          "WHERE belge_no=?", no)
    k["diger_urun_hareketleri"] = _rows(c, "SELECT id, hareket_turu, stok_id, lot_id, miktar FROM stok_hareketleri "
                                           "WHERE belge_no=? AND stok_id<>?", no, STOK_ID)
    k["aciklama_test"] = _test_gibi(k["fatura"].get("aciklama"))
    return k


def mutabakat(c) -> dict:
    g, ci = ",".join("?" * len(GIRIS)), ",".join("?" * len(CIKIS))
    net, sayi = c.execute(f"""SELECT COALESCE(SUM(CASE WHEN hareket_turu IN ({g}) THEN miktar
                                  WHEN hareket_turu IN ({ci}) THEN -miktar END), 0), COUNT(*)
                              FROM stok_hareketleri WHERE stok_id=?""", GIRIS + CIKIS + (STOK_ID,)).fetchone()
    lot = c.execute("SELECT COALESCE(SUM(kalan_miktar),0), COUNT(*) FROM stok_lotlari WHERE stok_id=?",
                    (STOK_ID,)).fetchone()
    return {"stok_851_hareket_bakiyesi": net, "stok_851_hareket_sayisi": sayi,
            "stok_851_lot_toplami": lot[0], "stok_851_lot_sayisi": lot[1],
            "stok_hareketi_toplam": c.execute("SELECT COUNT(*) FROM stok_hareketleri").fetchone()[0],
            "stok_lotu_toplam": c.execute("SELECT COUNT(*) FROM stok_lotlari").fetchone()[0],
            "muhasebe_fisi_toplam": c.execute("SELECT COUNT(*) FROM muhasebe_fisleri").fetchone()[0]}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="Gerçek DB'nin salt okunur kopyası")
    ap.add_argument("--kaynak", default="", help="Kopyanın alındığı gerçek DB yolu (rapor için)")
    ap.add_argument("--sonuc", default=str(SONUC))
    a = ap.parse_args()
    c = sqlite3.connect(f"file:{Path(a.db).as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row

    hareketler = _rows(c, f"""SELECT id, tarih, hareket_turu, belge_no, stok_id, depo_id, lot_id, miktar, birim_maliyet,
                                     olusturma_tarihi FROM stok_hareketleri
                              WHERE stok_id=? AND lot_id=? AND belge_no IN ({','.join('?' * len(BELGELER))})
                              ORDER BY id""", STOK_ID, LOT_ID, *BELGELER)
    belgeler = {no: belge_kanit(c, no) for no in sorted({h["belge_no"] for h in hareketler})}
    cari_idler = {b["fatura"].get("cari_id") for b in belgeler.values() if b["fatura"].get("cari_id")}
    cariler = {cid: cari_kanit(c, cid, set(BELGELER)) for cid in sorted(cari_idler)}
    urun = (_rows(c, "SELECT id, stok_kodu, stok_adi, aktif FROM stok_kartlari WHERE id=?", STOK_ID) or [{}])[0]
    urun["hareket_sayisi"] = c.execute("SELECT COUNT(*) FROM stok_hareketleri WHERE stok_id=?", (STOK_ID,)).fetchone()[0]
    urun["test_karti"] = _test_gibi(urun.get("stok_kodu"), urun.get("stok_adi"))
    birlestirme = _rows(c, "SELECT id, entity_type, record_id, record_code, record_title, deletion_note, deleted_at, "
                           "deleted_by_username, related_records_json FROM deleted_record_logs "
                           "WHERE entity_type='stok_birlestir' AND related_records_json LIKE ?", f'%"id": {STOK_ID},%')
    lot_var = bool(c.execute("SELECT COUNT(*) FROM stok_lotlari WHERE id=?", (LOT_ID,)).fetchone()[0])

    tablo = []
    for h in hareketler:
        b = belgeler[h["belge_no"]]
        cid = b["fatura"].get("cari_id")
        ck = cariler.get(cid) if cid else None
        test_isareti = urun["test_karti"] or b["aciklama_test"] or bool(ck and ck["test_karti"])
        engeller = []
        if not test_isareti:
            engeller.append("Belgede / cari / üründe test işareti yok")
        if ck and ck["gercek_bag_var"]:
            engeller.append(f"Cari kartın başka kayıtları var: {ck['bu_belgeler_disindaki_baglar']}")
        if b["diger_urun_hareketleri"]:
            engeller.append(f"Aynı belgede başka ürün hareketleri var ({len(b['diger_urun_hareketleri'])})")
        if b["finans_hareketleri"]:
            engeller.append("Belgeye bağlı kasa/banka (finans) hareketi var")
        if not urun["test_karti"] and urun["hareket_sayisi"] > len(hareketler):
            engeller.append(f"Ürün gerçek kart ({urun['hareket_sayisi']} hareket)")
        tablo.append({
            "hareket_id": h["id"], "tarih": h["tarih"], "hareket_turu": h["hareket_turu"], "belge_no": h["belge_no"],
            "miktar": h["miktar"], "birim_maliyet": h["birim_maliyet"], "olusturma": h["olusturma_tarihi"],
            "belge_turu": b["tur"], "belge_id": b["fatura"].get("id"),
            "belge_tutari": b["fatura"].get("tl_genel_toplam") or b["fatura"].get("odeme_tutari")
            or b["fatura"].get("toplam_maliyet"),
            "belge_aciklama": b["fatura"].get("aciklama"), "kullanici": b["kullanici"],
            "cari": (ck or {}).get("kart"), "cari_hareket_idleri": [r.get("id") for r in b["cari_hareketleri"]],
            "finans_hareket_idleri": [r.get("id") for r in b["finans_hareketleri"]],
            "muhasebe_fis_idleri": [r.get("id") for r in b["muhasebe_fisleri"]],
            "muhasebe_belge_durumu": [r.get("durum") for r in b["muhasebe_belge_durumu"]],
            "kesin_test": not engeller, "engeller": engeller,
            "karar": "Düzeltilebilir (kesin test)" if not engeller else "DOKUNULMADI — test olduğu kesin değil",
        })

    ozet_karar = ("Hiçbir hareket kesin test kaydı değil; veri değiştirilmedi."
                  if not any(t["kesin_test"] for t in tablo) else "Kesin test kayıtları var; ayrı uygulama gerekir.")
    rapor = {
        "zaman": datetime.now().isoformat(timespec="seconds"),
        "kaynak_db": a.kaynak, "incelenen_kopya": str(a.db), "yazma_yapildi": False,
        "urun": urun, "lot_1_mevcut": lot_var,
        "kok_neden_kaniti": {
            "aciklama": ("Hareketler 18.09.2026'daki stok birleştirmesiyle stok 3 (8690000000036 «MİNNES RAY FRENLİ 50») "
                         "kartından stok 851'e taşınmış (5 belge satırı, 6 hareket, 1 lot). Lot 1 bugün mevcut değil; "
                         "6 hareketin net etkisi +60 = hareket bakiyesi (61) − lot toplamı (1). Fark belgelerden değil, "
                         "birleştirme sırasında/sonrasında kaybolan lot kaydından kaynaklanıyor."),
            "birlestirme_kayitlari": birlestirme,
            "alti_hareket_net": sum((t["miktar"] if t["hareket_turu"] in GIRIS else -t["miktar"]) for t in tablo),
        },
        "hareketler": tablo, "belgeler": belgeler, "cariler": cariler,
        "mutabakat": mutabakat(c), "karar": ozet_karar,
        "kullanici_karari_gereken": [
            "Bu 5 belge (ARAY000001, SRAY000001/3/4, PKT000001) gerçek işlem mi, programın ilk deneme kullanımı mı?",
            "Gerçekse: ürün 2608101620349 fiziksel sayımı yapılıp eksik lot sayım fişiyle tamamlanmalı "
            "(hareket bakiyesi 61, lot 1).",
            "Denemeyse: belgeler mevcut iptal yollarıyla (satış/alış faturası iptali, paket fişi geri alma) iptal "
            "edilmeli; SRAY000004 kasa tahsilatı (finans 30) ve cari işlemleri birlikte değerlendirilmeli.",
        ],
    }
    Path(a.sonuc).parent.mkdir(parents=True, exist_ok=True)
    Path(a.sonuc).write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for t in tablo:
        print(t["hareket_id"], t["belge_no"], t["hareket_turu"], t["miktar"], "|", t["karar"], "|", "; ".join(t["engeller"]))
    print("Karar:", ozet_karar)
    print("Mutabakat:", rapor["mutabakat"])
    print("Rapor:", a.sonuc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
