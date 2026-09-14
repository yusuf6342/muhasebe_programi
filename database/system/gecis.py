"""AŞAMA 6 — mevcut verilerin güvenli çok firmalı geçişi.

Strateji: muhasebe.db içeriği taşınmaz; Ray Mobilya firmasına bağlanır.
Geçiş öncesi yedek alınır, satır sayıları / kritik toplamlar kaydedilir.
İkinci çalıştırmada mükerrer firma/kullanıcı oluşmaz (bootstrap zaten idempotent).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from database.system.models import AppSetting, Company

GECIS_FLAG = "gecis_v6_tamam"
GECIS_SNAPSHOT = "gecis_v6_snapshot"
GECIS_YEDEK = "gecis_v6_yedek_yolu"
RAY_KOD = "RAY001"

# Doğrulanacak operasyon tabloları
SAYIM_TABLOLARI = (
    "satis_faturalari",
    "satis_faturasi_satirlari",
    "alis_faturalari",
    "stok_kartlari",
    "stok_hareketleri",
    "cari_kartlar",
    "cari_islemleri",
    "finans_hesaplari",
    "finans_hareketleri",
    "kasa_makbuzlari",
)


def _ayar_oku(session, anahtar: str) -> str | None:
    kayit = session.scalar(select(AppSetting).where(AppSetting.anahtar == anahtar))
    return kayit.deger if kayit else None


def _ayar_yaz(session, anahtar: str, deger: str) -> None:
    kayit = session.scalar(select(AppSetting).where(AppSetting.anahtar == anahtar))
    if kayit is None:
        session.add(AppSetting(anahtar=anahtar, deger=deger))
    else:
        kayit.deger = deger


def _sqlite_sayim(db_path: Path) -> dict[str, Any]:
    """Operasyon DB'sinden satır sayıları ve kritik toplamlar."""
    if not db_path.is_file():
        raise FileNotFoundError(f"Veritabanı yok: {db_path}")

    con = sqlite3.connect(str(db_path))
    try:
        cur = con.cursor()
        tablolar = {
            r[0]
            for r in cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        sayimlar: dict[str, int] = {}
        for tablo in SAYIM_TABLOLARI:
            if tablo in tablolar:
                sayimlar[tablo] = int(
                    cur.execute(f'SELECT COUNT(*) FROM "{tablo}"').fetchone()[0]
                )
            else:
                sayimlar[tablo] = 0

        def _sum(sql: str) -> str:
            try:
                val = cur.execute(sql).fetchone()[0]
            except sqlite3.Error:
                return "0"
            if val is None:
                return "0"
            return str(Decimal(str(val)))

        toplamlar = {
            "satis_tl_genel_toplam": _sum(
                'SELECT COALESCE(SUM(tl_genel_toplam),0) FROM satis_faturalari '
                "WHERE COALESCE(durum,'') != 'İPTAL'"
            ),
            "alis_tl_genel_toplam": _sum(
                'SELECT COALESCE(SUM(tl_genel_toplam),0) FROM alis_faturalari '
                "WHERE COALESCE(durum,'') != 'İPTAL'"
            )
            if "alis_faturalari" in tablolar
            else "0",
            "finans_hesap_acilis": _sum(
                "SELECT COALESCE(SUM(acilis_bakiyesi),0) FROM finans_hesaplari"
            )
            if "finans_hesaplari" in tablolar
            else "0",
            "cari_sayisi": str(sayimlar.get("cari_kartlar", 0)),
            "stok_sayisi": str(sayimlar.get("stok_kartlari", 0)),
        }
        # tl_genel_toplam kolonu yoksa eski şema: satırlardan hesaplama yok, 0 bırak
        if "satis_faturalari" in tablolar:
            cols = {
                r[1]
                for r in cur.execute('PRAGMA table_info("satis_faturalari")').fetchall()
            }
            if "tl_genel_toplam" not in cols:
                toplamlar["satis_tl_genel_toplam"] = "kolon_yok"
        if "alis_faturalari" in tablolar:
            cols = {
                r[1]
                for r in cur.execute('PRAGMA table_info("alis_faturalari")').fetchall()
            }
            if "tl_genel_toplam" not in cols:
                toplamlar["alis_tl_genel_toplam"] = "kolon_yok"

        return {
            "db_path": str(db_path.resolve()),
            "db_boyut_byte": db_path.stat().st_size,
            "sayimlar": sayimlar,
            "toplamlar": toplamlar,
            "zaman": datetime.now().isoformat(timespec="seconds"),
        }
    finally:
        con.close()


def yedek_olustur(db_path: Path, yedek_dir: Path | None = None) -> Path:
    """muhasebe.db (+ wal/shm) kopyası — geçiş öncesi."""
    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"Yedeklenecek dosya yok: {db_path}")
    hedef_dir = Path(yedek_dir) if yedek_dir else (db_path.parent / "yedekler")
    hedef_dir.mkdir(parents=True, exist_ok=True)
    damga = datetime.now().strftime("%Y%m%d_%H%M%S")
    hedef = hedef_dir / f"muhasebe_gecis_v6_{damga}.db"
    shutil.copy2(db_path, hedef)
    for ek in ("-wal", "-shm"):
        kaynak = Path(str(db_path) + ek)
        if kaynak.is_file():
            shutil.copy2(kaynak, Path(str(hedef) + ek))
    return hedef


def snapshotlari_karsilastir(once: dict, sonra: dict) -> dict[str, Any]:
    """Önce/sonra sayım ve toplam farkları."""
    farklar: dict[str, Any] = {"uyumlu": True, "sayim": {}, "toplam": {}}
    for tablo, once_n in (once.get("sayimlar") or {}).items():
        sonra_n = (sonra.get("sayimlar") or {}).get(tablo, 0)
        fark = int(sonra_n) - int(once_n)
        farklar["sayim"][tablo] = {"once": once_n, "sonra": sonra_n, "fark": fark}
        if fark != 0:
            farklar["uyumlu"] = False
    for anahtar, once_v in (once.get("toplamlar") or {}).items():
        sonra_v = (sonra.get("toplamlar") or {}).get(anahtar)
        farklar["toplam"][anahtar] = {"once": once_v, "sonra": sonra_v}
        if str(once_v) != str(sonra_v):
            farklar["uyumlu"] = False
    return farklar


def gecis_durumu(session) -> dict[str, Any]:
    tamam = _ayar_oku(session, GECIS_FLAG) == "1"
    yedek = _ayar_oku(session, GECIS_YEDEK)
    snap_raw = _ayar_oku(session, GECIS_SNAPSHOT)
    snapshot = json.loads(snap_raw) if snap_raw else None
    firma = session.scalar(select(Company).where(Company.firma_kodu == RAY_KOD))
    return {
        "tamam": tamam,
        "yedek_yolu": yedek,
        "snapshot": snapshot,
        "ray_firma_id": firma.id if firma else None,
        "ray_db_path": firma.db_path if firma else None,
        "ray_unvan": firma.unvan if firma else None,
    }


def gecis_calistir(
    session,
    *,
    muhasebe_db_path: Path,
    yedek_dir: Path | None = None,
    zorla_yedek: bool = False,
) -> dict[str, Any]:
    """
    Güvenli geçiş adımları (idempotent):
    1) İlk seferde otomatik yedek
    2) Snapshot al / güncelle doğrulama
    3) Ray firmasının db_path'inin muhasebe.db olduğunu doğrula
    4) Flag yaz
    Operasyon verisine INSERT/UPDATE/DELETE yapmaz.
    """
    muhasebe_db_path = Path(muhasebe_db_path).resolve()
    sonuc: dict[str, Any] = {
        "yedek_alindi": False,
        "yedek_yolu": None,
        "snapshot": None,
        "dogrulama": None,
        "zaten_tamam": False,
        "mesajlar": [],
    }

    firma = session.scalar(select(Company).where(Company.firma_kodu == RAY_KOD))
    if firma is None:
        raise RuntimeError(
            "Ray Mobilya firması system.db içinde yok. Önce sistem bootstrap çalışmalı."
        )

    beklenen = str(muhasebe_db_path)
    if Path(firma.db_path).resolve() != muhasebe_db_path:
        # Yol kaymışsa güvenli güncelle (içerik taşınmaz)
        sonuc["mesajlar"].append(
            f"Firma DB yolu güncellendi: {firma.db_path} → {beklenen}"
        )
        firma.db_path = beklenen

    onceki_tamam = _ayar_oku(session, GECIS_FLAG) == "1"
    onceki_snap_raw = _ayar_oku(session, GECIS_SNAPSHOT)
    onceki_snap = json.loads(onceki_snap_raw) if onceki_snap_raw else None

    # Yedek: ilk geçişte veya zorla
    if not onceki_tamam or zorla_yedek:
        yedek = yedek_olustur(muhasebe_db_path, yedek_dir)
        _ayar_yaz(session, GECIS_YEDEK, str(yedek))
        sonuc["yedek_alindi"] = True
        sonuc["yedek_yolu"] = str(yedek)
        sonuc["mesajlar"].append(f"Yedek alındı: {yedek}")
    else:
        sonuc["yedek_yolu"] = _ayar_oku(session, GECIS_YEDEK)
        sonuc["zaten_tamam"] = True
        sonuc["mesajlar"].append("Geçiş daha önce tamamlanmış; yeniden doğrulanıyor.")

    # Güncel snapshot
    guncel = _sqlite_sayim(muhasebe_db_path)
    sonuc["snapshot"] = guncel

    if onceki_snap is None:
        _ayar_yaz(session, GECIS_SNAPSHOT, json.dumps(guncel, ensure_ascii=False))
        sonuc["dogrulama"] = {
            "uyumlu": True,
            "not": "İlk snapshot kaydedildi (karşılaştırma referansı).",
        }
        sonuc["mesajlar"].append("İlk doğrulama snapshot'ı kaydedildi.")
    else:
        kars = snapshotlari_karsilastir(onceki_snap, guncel)
        sonuc["dogrulama"] = kars
        if kars["uyumlu"]:
            sonuc["mesajlar"].append("Sayısal doğrulama: kayıtlar uyumlu.")
        else:
            sonuc["mesajlar"].append(
                "UYARI: Snapshot ile güncel sayılar farklı "
                "(geçiş sonrası normal işlem yapılmış olabilir)."
            )
        # Referans snapshot'ı ilk geçişte dondur — üzerine yazma
        # (işlem sonrası farklar bilgilendirme amaçlı)

    _ayar_yaz(session, GECIS_FLAG, "1")
    _ayar_yaz(session, "kurulum_tamam", "1")
    session.flush()
    return sonuc


def canli_dogrulama(muhasebe_db_path: Path, session) -> dict[str, Any]:
    """UI / smoke için: kayıtlı snapshot vs şu anki DB."""
    durum = gecis_durumu(session)
    guncel = _sqlite_sayim(Path(muhasebe_db_path))
    once = durum.get("snapshot")
    kars = snapshotlari_karsilastir(once, guncel) if once else None
    return {
        "durum": durum,
        "guncel": guncel,
        "karsilastirma": kars,
        "ray_db_eslesiyor": (
            durum.get("ray_db_path")
            and Path(durum["ray_db_path"]).resolve() == Path(muhasebe_db_path).resolve()
        ),
    }
