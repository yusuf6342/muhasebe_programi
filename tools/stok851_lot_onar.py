"""Stok 851'in (2608101620349) 18.09.2026 birleştirmesinde kaybolan lot 1 kaydını yedekten geri getirir.

Kanıt: 14.09.2026 yedeklerinde lot 1 (stok 3 «8690000000036», ANA DEPO, BİRR-20260908, 08.09.2026,
kalan 60, maliyet 223,744) mevcut; 6 hareket (lot_id=1) birleştirmeyle stok 851'e taşınmış, lot ise
kaynak kart fiziksel silinirken kaybolmuş. Yalnız lot kaydı geri gelir (id=1, stok_id=851); stok
hareketi, cari, finans veya muhasebe kaydı oluşturulmaz.

Varsayılan kuru çalışmadır (--dry-run). Yazmak için --uygula; gerçek DB'de önce CinMuhasebe.exe
kontrol edilir ve doğrulanmış yedek (backup API + integrity_check + tablo satır sayıları) alınır.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MUHASEBE_DB_DIR", tempfile.mkdtemp(prefix="cin_lot_onar_"))

LOCAL = Path(os.environ["LOCALAPPDATA"]) / "MuhasebeProgrami"
VARSAYILAN_DB = LOCAL / "data" / "muhasebe.db"
KANIT_YEDEKLERI = (
    LOCAL / "data" / "yedekler" / "muhasebe_gecis_v6_20260914_133014.db",
    LOCAL / "data" / "yedekler" / "test_asama7" / "RAY001_20260914_133456.db",
)
SONUC = ROOT / "inceleme" / "stoklar" / "stok851_lot_onar_sonuc.json"
HEDEF_STOK, KAYNAK_STOK, LOT_ID = 851, 3, 1
ALANLAR = ("depo_id", "lot_no", "tedarikci", "giris_tarihi", "kalan_miktar", "birim_maliyet")


def _ro(yol: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{yol.as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def uygulama_calisiyor() -> bool:
    try:
        cikti = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CinMuhasebe.exe"],
                               capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return False
    return "CinMuhasebe.exe" in cikti


def yedekteki_lot() -> dict:
    """Kanıt yedeklerinin hepsinde lot 1 aynı olmalı ve kaynak kartın hareket neti kalanla eşleşmeli."""
    from database.stok_service import CIKIS_HAREKETLERI, GIRIS_HAREKETLERI

    bulunan = []
    for yol in KANIT_YEDEKLERI:
        c = _ro(yol)
        try:
            if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError(f"Kanıt yedeği bozuk: {yol}")
            r = c.execute("SELECT * FROM stok_lotlari WHERE id=?", (LOT_ID,)).fetchone()
            if r is None or r["stok_id"] != KAYNAK_STOK:
                raise RuntimeError(f"Kanıt yedeğinde lot {LOT_ID} / stok {KAYNAK_STOK} yok: {yol}")
            net = Decimal("0")
            for h in c.execute("SELECT hareket_turu, miktar FROM stok_hareketleri WHERE lot_id=?", (LOT_ID,)):
                m = Decimal(str(h["miktar"]))
                net += m if h["hareket_turu"] in GIRIS_HAREKETLERI else -m if h["hareket_turu"] in CIKIS_HAREKETLERI else 0
            lot = {k: r[k] for k in ALANLAR}
            if Decimal(str(lot["kalan_miktar"])) != net:
                raise RuntimeError(f"Yedekte lot kalanı ({lot['kalan_miktar']}) hareket netiyle ({net}) eşleşmiyor")
            bulunan.append(lot)
        finally:
            c.close()
    if any(b != bulunan[0] for b in bulunan):
        raise RuntimeError("Kanıt yedeklerindeki lot değerleri birbirini tutmuyor")
    return bulunan[0]


def mutabakat(db: Path) -> dict:
    from database.stok_service import CIKIS_HAREKETLERI, GIRIS_HAREKETLERI

    c = _ro(db)
    try:
        giris = cikis = Decimal("0")
        for h in c.execute("SELECT hareket_turu, miktar FROM stok_hareketleri WHERE stok_id=?", (HEDEF_STOK,)):
            m = Decimal(str(h["miktar"]))
            if h["hareket_turu"] in GIRIS_HAREKETLERI:
                giris += m
            elif h["hareket_turu"] in CIKIS_HAREKETLERI:
                cikis += m
        lot = Decimal(str(c.execute("SELECT COALESCE(SUM(kalan_miktar),0) FROM stok_lotlari WHERE stok_id=?",
                                    (HEDEF_STOK,)).fetchone()[0]))
        lot1_net = Decimal("0")
        lot1_hareket = []
        for h in c.execute("SELECT id, stok_id, depo_id, hareket_turu, miktar FROM stok_hareketleri WHERE lot_id=? "
                           "ORDER BY id", (LOT_ID,)):
            m = Decimal(str(h["miktar"]))
            lot1_net += m if h["hareket_turu"] in GIRIS_HAREKETLERI else -m
            lot1_hareket.append(dict(h))
        sayim = {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                 for t in ("stok_hareketleri", "stok_lotlari", "cari_islemleri", "muhasebe_fisleri",
                           "muhasebe_fis_satirlari", "finans_hareketleri")
                 if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()}
        return {
            "hareket_bakiyesi": giris - cikis,
            "lot_toplami": lot,
            "fark": giris - cikis - lot,
            "lot1_var": c.execute("SELECT COUNT(*) FROM stok_lotlari WHERE id=?", (LOT_ID,)).fetchone()[0] == 1,
            "lot1_hareketleri": lot1_hareket,
            "lot1_hareket_neti": lot1_net,
            "tablo_sayilari": sayim,
        }
    finally:
        c.close()


def on_kosullar(db: Path, lot: dict, once: dict) -> list[str]:
    hata = []
    c = _ro(db)
    try:
        if not c.execute("SELECT 1 FROM stok_kartlari WHERE id=?", (HEDEF_STOK,)).fetchone():
            hata.append("Hedef stok 851 yok")
        if once["lot1_var"]:
            hata.append("Lot 1 zaten mevcut (onarım gerekmez / tekrar çalıştırılamaz)")
        if c.execute("SELECT 1 FROM stok_lotlari WHERE stok_id=? AND depo_id=? AND lot_no=?",
                     (HEDEF_STOK, lot["depo_id"], lot["lot_no"])).fetchone():
            hata.append("Hedefte aynı depo + lot_no ile lot var")
        if not c.execute("SELECT 1 FROM depolar WHERE id=?", (lot["depo_id"],)).fetchone():
            hata.append("Lotun deposu yok")
    finally:
        c.close()
    if len(once["lot1_hareketleri"]) != 6 or any(h["stok_id"] != HEDEF_STOK or h["depo_id"] != lot["depo_id"]
                                                 for h in once["lot1_hareketleri"]):
        hata.append("lot_id=1 hareketleri beklenen 6 hareket / stok 851 / aynı depo değil")
    if once["lot1_hareket_neti"] != Decimal(str(lot["kalan_miktar"])):
        hata.append(f"lot 1 hareket neti ({once['lot1_hareket_neti']}) yedekteki kalanla eşleşmiyor")
    if once["fark"] != Decimal(str(lot["kalan_miktar"])):
        hata.append(f"Hareket bakiyesi − lot toplamı ({once['fark']}) geri getirilecek miktara eşit değil")
    return hata


def lotu_geri_getir(db: Path, lot: dict) -> None:
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import Session

    from database.models.stok import StokLotu

    motor = create_engine(f"sqlite:///{db.resolve().as_posix()}", connect_args={"timeout": 30})

    @event.listens_for(motor, "connect")
    def _fk(dbapi_con, _):
        dbapi_con.execute("PRAGMA foreign_keys=ON")

    try:
        with Session(motor) as s, s.begin():
            s.add(StokLotu(
                id=LOT_ID, stok_id=HEDEF_STOK, depo_id=int(lot["depo_id"]), lot_no=lot["lot_no"],
                tedarikci=lot["tedarikci"], giris_tarihi=date.fromisoformat(str(lot["giris_tarihi"])[:10]),
                kalan_miktar=Decimal(str(lot["kalan_miktar"])), birim_maliyet=Decimal(str(lot["birim_maliyet"])),
            ))
            s.flush()
    finally:
        motor.dispose()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(VARSAYILAN_DB))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True)
    g.add_argument("--uygula", action="store_true")
    ap.add_argument("--sonuc", default=str(SONUC))
    a = ap.parse_args()
    db = Path(a.db)
    gercek = db.resolve() == VARSAYILAN_DB.resolve()
    rapor: dict = {"zaman": datetime.now().isoformat(timespec="seconds"), "db": str(db), "gercek_db": gercek,
                   "uygula": a.uygula, "kanit_yedekleri": [str(y) for y in KANIT_YEDEKLERI]}

    def yaz(kod: int) -> int:
        Path(a.sonuc).parent.mkdir(parents=True, exist_ok=True)
        Path(a.sonuc).write_text(json.dumps(rapor, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps({k: rapor.get(k) for k in ("durum", "hatalar", "yedek")}, ensure_ascii=False, default=str))
        for k in ("once", "sonra"):
            if k in rapor:
                m = rapor[k]
                print(f"{k}: hareket={m['hareket_bakiyesi']} lot={m['lot_toplami']} fark={m['fark']} "
                      f"lot1={m['lot1_var']} sayilar={m['tablo_sayilari']}")
        return kod

    lot = yedekteki_lot()
    rapor["geri_getirilecek_lot"] = {"id": LOT_ID, "stok_id": HEDEF_STOK, **lot}
    rapor["once"] = mutabakat(db)
    hatalar = on_kosullar(db, lot, rapor["once"])
    if hatalar:
        rapor["durum"], rapor["hatalar"] = "ön koşul sağlanmadı, değişiklik yok", hatalar
        return yaz(2)
    if not a.uygula:
        rapor["durum"] = "kuru çalışma: ön koşullar tamam, yazılmadı"
        return yaz(0)
    if gercek:
        if uygulama_calisiyor():
            rapor["durum"] = "program açık, uygulanmadı"
            return yaz(3)
        from database.gecis_guvenligi import GecisYedekHatasi, dogrulanmis_yedek
        try:
            y = dogrulanmis_yedek(db, "stok851_lot_onar")
        except GecisYedekHatasi as hata:
            rapor["durum"] = f"yedek doğrulanamadı, uygulanmadı: {hata}"
            return yaz(4)
        rapor["yedek"] = {"yol": str(y.yol), "tablo": len(y.tablo_sayilari), "satir": sum(y.tablo_sayilari.values()),
                          "dogrulama": "integrity_check ok, tablo satır sayıları eşit"}
    try:
        lotu_geri_getir(db, lot)
    except Exception as hata:
        rapor["durum"] = f"geri alındı: {hata}"
        return yaz(5)
    rapor["sonra"] = sonra = mutabakat(db)
    c = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    rapor["integrity_sonrasi"] = c.execute("PRAGMA integrity_check").fetchone()[0]
    c.close()
    beklenen = dict(rapor["once"]["tablo_sayilari"])
    beklenen["stok_lotlari"] += 1
    sorun = []
    if sonra["fark"] != 0:
        sorun.append(f"mutabakat farkı {sonra['fark']}")
    if sonra["tablo_sayilari"] != beklenen:
        sorun.append(f"beklenmeyen tablo sayısı değişimi {sonra['tablo_sayilari']}")
    if rapor["integrity_sonrasi"] != "ok":
        sorun.append("integrity_check başarısız")
    rapor["hatalar"] = sorun
    rapor["durum"] = "uygulandı, mutabakat tamam" if not sorun else "uygulandı ancak doğrulama sorunu"
    return yaz(0 if not sorun else 6)


if __name__ == "__main__":
    raise SystemExit(main())
