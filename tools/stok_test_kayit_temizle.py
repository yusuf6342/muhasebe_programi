"""Gerçek firma veritabanında test kayıtlarını doğrulayıp temizler (kullanıcı kararı 4).

Kapsam (yalnızca bunlar):
  * TEST-STOK-001 / TEST-UPD-001 stok kartları ve kartın kendi alt kayıtları
    (birim, barkod, fiyat, fiyat geçmişi, resim). Kartın hiçbir belge/hareket/lot bağlantısı
    yoksa silinir; bağlantı bulunursa dokunulmaz.
  * Lot kimliği 1 (mevcut olmayan lot) üzerindeki şüpheli 6 stok hareketi
    (ARAY000001, SRAY000001 ×2, SRAY000003, SRAY000004, PKT000001 — stok 851).
    Bu hareketler bir belgeye (fatura, paket fişi, cari/finans kaydı) bağlıysa SİLİNMEZ;
    yalnızca rapor edilir ve kullanıcı kararı beklenir.

Varsayılan kuru çalıştırmadır (hiçbir şey yazılmaz). ``--uygula`` ile:
  1. CinMuhasebe.exe çalışıyorsa durur,
  2. SQLite backup API ile ``data\\yedekler\\`` altına yedek alır; integrity_check + tablo satır
     sayıları doğrulanmazsa durur,
  3. tek transaction içinde siler; beklenen satır sayısı tutmazsa geri alır,
  4. önce/sonra stok mutabakatını ``inceleme\\stoklar\\test_kayit_temizlik_sonuc.json`` dosyasına yazar.
Tekrar çalıştırıldığında silinecek kayıt kalmadığını raporlar (idempotent).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VARSAYILAN_DB = Path.home() / "AppData/Local/MuhasebeProgrami/data/muhasebe.db"
SONUC = ROOT / "inceleme" / "stoklar" / "test_kayit_temizlik_sonuc.json"

TEST_KARTLARI = ("TEST-STOK-001", "TEST-UPD-001")
KART_ALT_TABLOLARI = ("stok_birimleri", "stok_barkodlari", "stok_fiyatlari", "stok_fiyat_gecmisi", "stok_resimleri")
SUPHELI_BELGELER = ("ARAY000001", "SRAY000001", "SRAY000003", "SRAY000004", "PKT000001")
SUPHELI_STOK_ID = 851
SUPHELI_LOT_ID = 1

GIRIS = ("GİRİŞ", "FATURA GİRİŞ", "İADE GİRİŞ", "TRANSFER GİRİŞ", "PAKET GİRİŞ", "SAYIM GİRİŞ",
         "İRSALİYE İADE GİRİŞ")
CIKIS = ("FATURA ÇIKIŞ", "ÇIKIŞ", "TRANSFER ÇIKIŞ", "PAKET ÇIKIŞ", "SAYIM ÇIKIŞ", "İRSALİYE ÇIKIŞ")


def _yer(n: int) -> str:
    return ",".join("?" * n)


def tablolar(cur) -> list[str]:
    return [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]


def kolonlar(cur, t: str) -> list[tuple[str, str]]:
    return [(c[1], (c[2] or "").upper()) for c in cur.execute(f'PRAGMA table_info("{t}")')]


def mutabakat(cur) -> dict:
    g, c = _yer(len(GIRIS)), _yer(len(CIKIS))
    farklar = cur.execute(f"""
        WITH h AS (SELECT stok_id, depo_id,
                SUM(CASE WHEN hareket_turu IN ({g}) THEN miktar WHEN hareket_turu IN ({c}) THEN -miktar ELSE 0 END) net
              FROM stok_hareketleri GROUP BY 1, 2),
             l AS (SELECT stok_id, depo_id, SUM(kalan_miktar) kalan FROM stok_lotlari GROUP BY 1, 2)
        SELECT h.stok_id, h.depo_id, ROUND(h.net, 4), ROUND(COALESCE(l.kalan, 0), 4)
        FROM h LEFT JOIN l ON l.stok_id = h.stok_id AND l.depo_id = h.depo_id
        WHERE ABS(h.net - COALESCE(l.kalan, 0)) > 0.0001""", GIRIS + CIKIS).fetchall()
    s851 = cur.execute(f"""SELECT
        COALESCE(SUM(CASE WHEN hareket_turu IN ({g}) THEN miktar WHEN hareket_turu IN ({c}) THEN -miktar END), 0),
        COUNT(*) FROM stok_hareketleri WHERE stok_id = ?""", GIRIS + CIKIS + (SUPHELI_STOK_ID,)).fetchone()
    lot851 = cur.execute("SELECT COALESCE(SUM(kalan_miktar), 0) FROM stok_lotlari WHERE stok_id = ?",
                         (SUPHELI_STOK_ID,)).fetchone()[0]
    return {
        "stok_karti": cur.execute("SELECT COUNT(*) FROM stok_kartlari").fetchone()[0],
        "stok_hareketi": cur.execute("SELECT COUNT(*) FROM stok_hareketleri").fetchone()[0],
        "stok_lotu": cur.execute("SELECT COUNT(*) FROM stok_lotlari").fetchone()[0],
        "lot_hareket_farkli_stok_depo": len(farklar),
        "lot_hareket_farklari": [list(f) for f in farklar[:20]],
        "stok_851": {"hareket_bakiyesi": s851[0], "hareket_sayisi": s851[1], "lot_toplami": lot851},
    }


def test_kartlarini_incele(cur) -> dict:
    kartlar = cur.execute(
        f"SELECT id, stok_kodu, stok_adi FROM stok_kartlari WHERE stok_kodu IN ({_yer(len(TEST_KARTLARI))})",
        TEST_KARTLARI,
    ).fetchall()
    sonuc = {"kartlar": [list(k) for k in kartlar], "baglantilar": [], "alt_kayitlar": {}, "silinebilir": False}
    if not kartlar:
        return sonuc
    ids = [k[0] for k in kartlar]
    kodlar = [k[1] for k in kartlar]
    for k in kartlar:
        if not (k[2] or "").casefold().startswith("test"):
            sonuc["baglantilar"].append(f"{k[1]} kart adı test kaydı gibi görünmüyor: {k[2]}")
    for t in tablolar(cur):
        if t == "stok_kartlari":
            continue
        for ad, _tip in kolonlar(cur, t):
            sayi = 0
            if ad in ("stok_id", "paket_stok_id", "bilesen_stok_id"):
                sayi = cur.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{ad}" IN ({_yer(len(ids))})', ids).fetchone()[0]
            elif ad in ("urun_kodu", "stok_kodu", "hizmet_kodu"):
                sayi = cur.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{ad}" IN ({_yer(len(kodlar))})', kodlar).fetchone()[0]
            if not sayi:
                continue
            if t in KART_ALT_TABLOLARI and ad == "stok_id":
                sonuc["alt_kayitlar"][t] = sayi
            else:
                sonuc["baglantilar"].append(f"{t}.{ad}: {sayi}")
    sonuc["silinebilir"] = not sonuc["baglantilar"]
    return sonuc


def supheli_hareketleri_incele(cur) -> dict:
    hareketler = cur.execute(
        f"""SELECT id, tarih, hareket_turu, belge_no, stok_id, lot_id, miktar FROM stok_hareketleri
            WHERE lot_id = ? AND belge_no IN ({_yer(len(SUPHELI_BELGELER))})""",
        (SUPHELI_LOT_ID,) + SUPHELI_BELGELER,
    ).fetchall()
    lot_var = cur.execute("SELECT COUNT(*) FROM stok_lotlari WHERE id = ?", (SUPHELI_LOT_ID,)).fetchone()[0]
    nolar = sorted({h[3] for h in hareketler})
    baglantilar: list[str] = []
    for t in tablolar(cur):
        if t == "stok_hareketleri":
            continue
        for ad, tip in kolonlar(cur, t):
            if not tip.startswith(("VARCHAR", "TEXT", "CHAR")) or not nolar:
                continue
            try:
                sayi = cur.execute(f'SELECT COUNT(*) FROM "{t}" WHERE "{ad}" IN ({_yer(len(nolar))})', nolar).fetchone()[0]
            except sqlite3.Error:
                continue
            if sayi:
                baglantilar.append(f"{t}.{ad}: {sayi}")
    diger_stok = cur.execute(
        f"""SELECT id, hareket_turu, belge_no, stok_id, lot_id, miktar FROM stok_hareketleri
            WHERE belge_no IN ({_yer(len(SUPHELI_BELGELER))}) AND NOT (lot_id = ? AND stok_id = ?)""",
        SUPHELI_BELGELER + (SUPHELI_LOT_ID, SUPHELI_STOK_ID),
    ).fetchall()
    return {
        "hareketler": [list(h) for h in hareketler],
        "lot_1_mevcut": bool(lot_var),
        "belge_baglantilari": baglantilar,
        "ayni_belgedeki_diger_hareketler": [list(h) for h in diger_stok],
        "silinebilir": bool(hareketler) and not baglantilar and not diger_stok and not lot_var,
    }


def uygulama_calisiyor() -> bool:
    try:
        cikti = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CinMuhasebe.exe"],
                               capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return False
    return "CinMuhasebe.exe" in cikti


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(VARSAYILAN_DB))
    ap.add_argument("--uygula", action="store_true")
    ap.add_argument("--sonuc", default=str(SONUC))
    a = ap.parse_args()
    db = Path(a.db)

    ro = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    cur = ro.cursor()
    rapor: dict = {"zaman": datetime.now().isoformat(timespec="seconds"), "db": str(db), "uygula": a.uygula}
    rapor["once"] = mutabakat(cur)
    kart = test_kartlarini_incele(cur)
    hareket = supheli_hareketleri_incele(cur)
    ro.close()
    rapor["test_kartlari"] = kart
    rapor["supheli_hareketler"] = hareket

    silinecek_kart = kart["silinebilir"] and bool(kart["kartlar"])
    silinecek_hareket = hareket["silinebilir"]
    rapor["karar"] = {
        "test_kartlari": (
            "zaten temiz" if not kart["kartlar"]
            else "silinecek" if silinecek_kart
            else "DOKUNULMADI — bağlantı var: " + "; ".join(kart["baglantilar"])
        ),
        "supheli_hareketler": (
            "zaten temiz" if not hareket["hareketler"]
            else "silinecek" if silinecek_hareket
            else "DOKUNULMADI — hareketler gerçek belgelere bağlı (kullanıcı kararı gerekli): "
                 + "; ".join(hareket["belge_baglantilari"] or ["aynı belgede başka stok hareketleri var"])
        ),
    }

    if a.uygula and (silinecek_kart or silinecek_hareket):
        if uygulama_calisiyor():
            print("CinMuhasebe.exe çalışıyor; kapatıp yeniden deneyin. Hiçbir değişiklik yapılmadı.")
            return 2
        from database.gecis_guvenligi import GecisYedekHatasi, dogrulanmis_yedek

        try:
            yedek = dogrulanmis_yedek(db, "stok_test_temizlik")
        except GecisYedekHatasi as hata:
            rapor["yedek_hatasi"] = str(hata)
            print(f"Yedek doğrulanamadı, veri değişikliği yapılmadı: {hata}")
            Path(a.sonuc).write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            return 3
        rapor["yedek"] = {"yol": str(yedek.yol), "tablo": len(yedek.tablo_sayilari),
                          "satir": sum(yedek.tablo_sayilari.values()),
                          "dogrulama": "integrity_check ok, tablo satır sayıları eşit"}
        con = sqlite3.connect(str(db), timeout=30, isolation_level=None)
        silinen: dict[str, int] = {}
        try:
            con.execute("PRAGMA foreign_keys=ON")
            con.execute("BEGIN IMMEDIATE")
            if silinecek_kart:
                ids = [k[0] for k in kart["kartlar"]]
                for t, beklenen in kart["alt_kayitlar"].items():
                    n = con.execute(f'DELETE FROM "{t}" WHERE stok_id IN ({_yer(len(ids))})', ids).rowcount
                    if n != beklenen:
                        raise RuntimeError(f"{t}: beklenen {beklenen}, silinen {n}")
                    silinen[t] = n
                n = con.execute(f"DELETE FROM stok_kartlari WHERE id IN ({_yer(len(ids))})", ids).rowcount
                if n != len(ids):
                    raise RuntimeError(f"stok_kartlari: beklenen {len(ids)}, silinen {n}")
                silinen["stok_kartlari"] = n
            if silinecek_hareket:
                hid = [h[0] for h in hareket["hareketler"]]
                n = con.execute(f"DELETE FROM stok_hareketleri WHERE id IN ({_yer(len(hid))})", hid).rowcount
                if n != len(hid):
                    raise RuntimeError(f"stok_hareketleri: beklenen {len(hid)}, silinen {n}")
                silinen["stok_hareketleri"] = n
            con.execute("COMMIT")
        except Exception as hata:
            con.execute("ROLLBACK")
            con.close()
            rapor["hata"] = f"Geri alındı: {hata}"
            print(rapor["hata"])
            Path(a.sonuc).write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            return 4
        rapor["silinen"] = silinen
        rapor["butunluk_sonrasi"] = con.execute("PRAGMA integrity_check").fetchone()[0]
        con.close()
        ro = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        rapor["sonra"] = mutabakat(ro.cursor())
        ro.close()

    Path(a.sonuc).parent.mkdir(parents=True, exist_ok=True)
    Path(a.sonuc).write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: rapor[k] for k in ("karar",)}, ensure_ascii=False, indent=2))
    print("Önce:", {k: rapor["once"][k] for k in ("stok_karti", "stok_hareketi", "lot_hareket_farkli_stok_depo", "stok_851")})
    if "sonra" in rapor:
        print("Sonra:", {k: rapor["sonra"][k] for k in ("stok_karti", "stok_hareketi", "lot_hareket_farkli_stok_depo", "stok_851")})
        print("Silinen:", rapor["silinen"], "Bütünlük:", rapor["butunluk_sonrasi"])
        print("Yedek:", rapor["yedek"]["yol"])
    print("Rapor:", a.sonuc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
