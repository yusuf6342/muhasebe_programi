"""Hesap planı saklı borç/alacak toplamlarını fiş satırlarından yeniden hesaplar (bakım aracı).

Varsayılan kuru çalışır (hiçbir şey yazmaz). ``--uygula`` yalnız ``--hesap`` ile verilen
hesapları düzeltir; öncesinde SQLite backup API ile tarihli yedek alır ve doğrular.
Uygulama (CinMuhasebe) açıkken çalıştırmayın.

    python tools/hesap_bakiye_duzelt.py --veri "%LOCALAPPDATA%\\MuhasebeProgrami\\data"
    python tools/hesap_bakiye_duzelt.py --veri ... --hesap 120 391 600 --uygula
"""

from __future__ import annotations

import argparse
import importlib
import os
import sqlite3
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def tablo_sayilari(yol: Path) -> dict[str, int]:
    c = sqlite3.connect(f"file:{yol.as_posix()}?mode=ro", uri=True)
    try:
        adlar = [r[0] for r in c.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
        return {a: c.execute(f'select count(*) from "{a}"').fetchone()[0] for a in adlar}
    finally:
        c.close()


def yedek_al(db: Path) -> Path:
    klasor = db.parent / "yedekler" / f"hesap_bakiye_duzeltme_{datetime.now():%Y%m%d_%H%M%S}"
    klasor.mkdir(parents=True, exist_ok=False)
    yedek = klasor / db.name
    kaynak = sqlite3.connect(str(db), timeout=30)
    hedef = sqlite3.connect(str(yedek))
    try:
        kaynak.backup(hedef)
    finally:
        hedef.close()
        kaynak.close()
    c = sqlite3.connect(f"file:{yedek.as_posix()}?mode=ro", uri=True)
    butunluk = c.execute("PRAGMA integrity_check").fetchone()[0]
    c.close()
    s_kaynak, s_yedek = tablo_sayilari(db), tablo_sayilari(yedek)
    print(f"YEDEK: {yedek} ({yedek.stat().st_size} bayt)")
    print(f"  integrity_check={butunluk} tablo={len(s_yedek)} satır={sum(s_yedek.values())} "
          f"(kaynak tablo={len(s_kaynak)} satır={sum(s_kaynak.values())})")
    if butunluk != "ok" or s_kaynak != s_yedek:
        raise SystemExit("Yedek doğrulanamadı; düzeltme yapılmadı.")
    return yedek


def oturum_ac(veri: Path, company_id: int, kullanici_id: int) -> None:
    os.environ["MUHASEBE_DB_DIR"] = str(veri)
    sys.path.insert(0, str(ROOT))
    import database.database as dbm

    for m in sorted((ROOT / "database" / "models").glob("*.py")):
        if m.stem != "__init__":
            importlib.import_module(f"database.models.{m.stem}")
    from database.session_manager import oturum

    if dbm.DB_PATH != (veri / "muhasebe.db").resolve():
        raise SystemExit(f"Beklenmeyen veritabanı: {dbm.DB_PATH}")
    sistem = sqlite3.connect(f"file:{(veri / 'system.db').as_posix()}?mode=ro", uri=True)
    firma = sistem.execute(
        "select firma_kodu, unvan, firma_uid from companies where id=?", (company_id,)).fetchone()
    kullanici = sistem.execute(
        "select u.kullanici_adi, u.ad_soyad, r.kod, r.ad from users u join roles r on r.id=u.role_id "
        "where u.id=?", (kullanici_id,)).fetchone()
    sistem.close()
    if firma is None or kullanici is None:
        raise SystemExit("Firma veya kullanıcı bulunamadı.")
    dbm.company_db._engine = dbm.engine
    dbm.company_db._session_factory = dbm.SessionLocal
    dbm.company_db._company_id = company_id
    dbm.company_db._db_path = dbm.DB_PATH
    oturum.clear()
    oturum.set_user(user_id=kullanici_id, kullanici_adi=kullanici[0], ad_soyad=kullanici[1],
                    role_kod=kullanici[2], role_ad=kullanici[3], permissions=set())
    oturum.set_company(company_id=company_id, firma_kodu=firma[0], firma_unvan=firma[1],
                       firma_uid=firma[2], db_path=str(dbm.DB_PATH))
    from database.donem_service import DonemService
    from database.models.donem import Donem
    from sqlalchemy import select

    with dbm.get_session() as s:
        firma_id = DonemService._yerel_firma_id(s)
        d = s.scalar(select(Donem).where(Donem.firma_id == firma_id, Donem.kapali.is_(False))
                     .order_by(Donem.varsayilan.desc(), Donem.id.desc()))
    if d is None:
        raise SystemExit("Açık dönem yok.")
    oturum.set_period(d.id, d.donem_adi)


def yaz(baslik: str, farklar: list[dict]) -> None:
    print(f"{baslik} ({len(farklar)} hesap)")
    for f in farklar:
        print(f"  {f['hesap_kodu']:<14} {(f['hesap_adi'] or '')[:28]:<28} "
              f"borç {f['eski_borc']} → {f['yeni_borc']} | alacak {f['eski_alacak']} → {f['yeni_alacak']} "
              f"| bakiye {f['eski_bakiye']} → {f['yeni_bakiye']}")


def plan_ve_mizan() -> tuple[dict, dict, bool]:
    from database.muhasebe_service import HesapPlanService, MuhasebeRaporService

    plan = {h["hesap_kodu"]: h["bakiye"] for h in HesapPlanService.listele() if h["bakiye"] != 0}
    m = MuhasebeRaporService.mizan(date(1900, 1, 1), date(2999, 12, 31))
    mizan = {s["hesap_kodu"]: s["borc_bakiyesi"] - s["alacak_bakiyesi"] for s in m["satirlar"]}
    return plan, {k: v for k, v in mizan.items() if v != 0}, m["dengeli"]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--veri", required=True, type=Path, help="muhasebe.db ve system.db klasörü")
    p.add_argument("--hesap", nargs="*", help="Düzeltilecek hesap kodları (--uygula için zorunlu)")
    p.add_argument("--uygula", action="store_true")
    p.add_argument("--firma", type=int, default=1)
    p.add_argument("--kullanici", type=int, default=1, help="İşlem geçmişine yazılacak kullanıcı id")
    a = p.parse_args()
    veri = a.veri.expanduser().resolve()
    db = veri / "muhasebe.db"
    if not db.is_file():
        raise SystemExit(f"Veritabanı yok: {db}")
    if a.uygula and not a.hesap:
        raise SystemExit("--uygula yalnız --hesap ile seçilen hesaplara uygulanır.")
    sayilar_once = tablo_sayilari(db)
    if a.uygula:
        yedek_al(db)
    oturum_ac(veri, a.firma, a.kullanici)
    from database.muhasebe_service import HesapPlanService

    plan, mizan, _ = plan_ve_mizan()
    if a.hesap:
        print("ÖNCE bakiye:", {k: str(plan.get(k, Decimal("0"))) for k in a.hesap})
    yaz("KURU — tüm hesaplar, saklı toplam ≠ fiş satırları", HesapPlanService.bakiyeleri_yeniden_hesapla())
    if a.uygula:
        yaz("UYGULANDI", HesapPlanService.bakiyeleri_yeniden_hesapla(a.hesap, kuru=False))
        plan, mizan, dengeli = plan_ve_mizan()
        print("SONRA bakiye:", {k: str(plan.get(k, Decimal("0"))) for k in a.hesap})
        yaz("KURU — sonra, kalan farklar", HesapPlanService.bakiyeleri_yeniden_hesapla())
        print("mizan dengeli:", dengeli)
        degisen = {t: (sayilar_once.get(t), n) for t, n in tablo_sayilari(db).items() if sayilar_once.get(t) != n}
        print("Satır sayısı değişen tablolar:", degisen)
    farkli = sorted(k for k in set(plan) | set(mizan) if plan.get(k) != mizan.get(k))
    print("HESAP PLANI == MİZAN:", not farkli, *(f"{k}: plan={plan.get(k)} mizan={mizan.get(k)}" for k in farkli))


if __name__ == "__main__":
    main()
