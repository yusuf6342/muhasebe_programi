"""Uzlaşmalı satış faturalarında cari borcu Brüt'ten Net'e düzeltme: kuru çalışma, yedek, uygulama.

Eski sürümde onay, cari borç satırına (``cari_satis_hareketleri``) satırların Brüt toplamını
yazıyordu; uzlaşma / genel indirim-masraf sonrası Net (``tl_genel_toplam``) yok sayılıyordu.

Kullanım (yalnız rapor; veritabanı salt okunur açılır):
    python -m database.uzlasma_net_duzeltme --db KOPYA.db --rapor rapor.txt

Uygulama (önce doğrulanmış yedek alınır; gerçek veri klasöründe ek onay gerekir):
    python -m database.uzlasma_net_duzeltme --db KOPYA.db --uygula --yedek-klasoru YEDEK

Kurallar:
- Yalnız onaylı, iptal/silinmiş olmayan satış faturaları; borç satırı Net'ten farklı olanlar.
- Tahsilatlar, makbuz bağları ve kapatma kayıtları değişmez: kapanan tutar (borç − kalan) korunur,
  yeni kalan = Net − kapanan.
- Kapanan tutar Net'i aşıyorsa (fazla tahsilat) veya fatura dövizliyse otomatik düzeltilmez,
  manuel inceleme listesine alınır.
- Tüm düzeltmeler tek transaction'dadır; tekrar çalıştırma yeni değişiklik üretmez.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from database.acik_kalem_gecis import (
    _gercek_veri_klasoru_mu,
    salt_okunur_oturum,
    yazilabilir_oturum,
    yedekle,
)
from database.models.cari import SatisHareketi
from database.models.satis_faturasi import SatisFaturasi

KURUS = Decimal("0.01")
DUZELT = "DUZELT"
MANUEL = "MANUEL_INCELEME"


def _k(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(KURUS)


def kuru_calisma(session) -> dict:
    """Cari borcu Net'ten farklı onaylı satış faturalarını listeler (değişiklik yapmaz)."""
    from database.satis_faturasi_service import SatisFaturasiService

    faturalar = session.scalars(
        select(SatisFaturasi)
        .options(selectinload(SatisFaturasi.satirlar))
        .where(
            SatisFaturasi.onaylandi.is_(True),
            SatisFaturasi.durum != "İPTAL",
            or_(SatisFaturasi.is_deleted.is_(False), SatisFaturasi.is_deleted.is_(None)),
        )
        .order_by(SatisFaturasi.id)
    ).all()
    kalemler = []
    for f in faturalar:
        hareket = session.scalar(
            select(SatisHareketi).where(
                SatisHareketi.belge_no == f.fatura_no, SatisHareketi.cari_id == f.cari_id
            )
        )
        if hareket is None:
            continue
        net = _k(SatisFaturasiService.net_toplam(f))
        eski = _k(hareket.satis_tutari)
        if abs(eski - net) < KURUS:
            continue
        eski_kalan = _k(hareket.kalan_acik_tutar)
        kapanan = eski - eski_kalan
        yeni_kalan = net - kapanan
        doviz = (hareket.para_birimi or "TRY").upper() != "TRY"
        if doviz:
            karar, neden = MANUEL, "Dövizli fatura; otomatik düzeltilmez."
        elif yeni_kalan < 0:
            karar, neden = MANUEL, (
                f"Kapanan {kapanan} TL Net {net} TL'yi aşıyor (fazla tahsilat); otomatik düzeltilmez."
            )
        else:
            karar, neden = DUZELT, ""
        kalemler.append(
            {
                "fatura_id": int(f.id),
                "fatura_no": f.fatura_no,
                "cari_id": int(f.cari_id),
                "hareket_id": int(hareket.id),
                "brut": _k(SatisFaturasiService.toplam(f.satirlar)["genel_toplam"]),
                "net": net,
                "eski_borc": eski,
                "eski_kalan": eski_kalan,
                "kapanan": kapanan,
                "yeni_borc": net,
                "yeni_kalan": yeni_kalan,
                "karar": karar,
                "neden": neden,
            }
        )
    return {
        "tarih": datetime.now().isoformat(timespec="seconds"),
        "kalemler": kalemler,
        "duzeltilecek": sum(1 for k in kalemler if k["karar"] == DUZELT),
        "manuel": sum(1 for k in kalemler if k["karar"] == MANUEL),
    }


def uygula(session, rapor: dict) -> list[dict]:
    """Rapordaki DUZELT kalemlerini uygular; commit çağıran tarafındadır."""
    uygulanan = []
    for k in rapor["kalemler"]:
        if k["karar"] != DUZELT:
            continue
        hareket = session.get(SatisHareketi, k["hareket_id"])
        if hareket is None:
            continue
        if _k(hareket.satis_tutari) != k["eski_borc"] or _k(hareket.kalan_acik_tutar) != k["eski_kalan"]:
            raise RuntimeError(f"{k['fatura_no']}: borç satırı rapordan sonra değişmiş; işlem iptal.")
        hareket.satis_tutari = k["yeni_borc"]
        hareket.kalan_acik_tutar = k["yeni_kalan"]
        uygulanan.append(k)
    session.flush()
    return uygulanan


def rapor_metni(rapor: dict, *, baslik: str = "UZLAŞMA NET DÜZELTME — KURU ÇALIŞMA") -> str:
    satirlar = [
        baslik,
        f"Tarih: {rapor['tarih']}",
        f"Etkilenen fatura: {len(rapor['kalemler'])} · Düzeltilecek: {rapor['duzeltilecek']} · "
        f"Manuel inceleme: {rapor['manuel']}",
        "",
    ]
    for k in rapor["kalemler"]:
        satirlar.append(
            f"{k['fatura_no']} (cari {k['cari_id']}): Brüt {k['brut']} · Net {k['net']} · "
            f"cari borç {k['eski_borc']} → {k['yeni_borc']} · kalan {k['eski_kalan']} → {k['yeni_kalan']} "
            f"(kapanan {k['kapanan']}) · {k['karar']}" + (f" — {k['neden']}" if k["neden"] else "")
        )
    return "\n".join(satirlar)


def yedek_dogrula(yedek: Path) -> None:
    with closing(sqlite3.connect(f"file:{Path(yedek).resolve().as_posix()}?mode=ro", uri=True)) as c:
        sonuc = c.execute("PRAGMA integrity_check").fetchone()[0]
    if sonuc != "ok":
        raise RuntimeError(f"Yedek doğrulanamadı ({sonuc}); düzeltme uygulanmadı.")


def tam_duzeltme(db: str | Path, klasor: str | Path) -> dict:
    """Rapor → yedek → yedek doğrulama → tek transaction'da uygulama → tekrar çalıştırma kontrolü."""
    db, klasor = Path(db), Path(klasor)
    klasor.mkdir(parents=True, exist_ok=True)
    session, motor = salt_okunur_oturum(db)
    try:
        once = kuru_calisma(session)
    finally:
        session.close()
        motor.dispose()
    (klasor / "01_duzeltme_oncesi.txt").write_text(rapor_metni(once), encoding="utf-8")

    yedek = yedekle(db, klasor)
    yedek_dogrula(yedek)

    session, motor = yazilabilir_oturum(db)
    try:
        uygulanan = uygula(session, once)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        motor.dispose()

    session, motor = salt_okunur_oturum(db)
    try:
        sonra = kuru_calisma(session)
    finally:
        session.close()
        motor.dispose()
    (klasor / "02_duzeltme_sonrasi.txt").write_text(
        rapor_metni(sonra, baslik="UZLAŞMA NET DÜZELTME — SONRASI"), encoding="utf-8"
    )
    ozet = {
        "db": str(db),
        "yedek": str(yedek),
        "uygulanan_sayisi": len(uygulanan),
        "uygulanan": uygulanan,
        "kalan_duzeltilecek": sonra["duzeltilecek"],
        "manuel": [k for k in sonra["kalemler"] if k["karar"] == MANUEL],
    }
    (klasor / "03_ozet.json").write_text(
        json.dumps(ozet, default=str, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return ozet


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Uzlaşmalı satış faturası cari borç düzeltmesi")
    ap.add_argument("--db", required=True)
    ap.add_argument("--rapor", help="Metin rapor dosyası")
    ap.add_argument("--uygula", action="store_true")
    ap.add_argument("--yedek-klasoru")
    ap.add_argument("--gercek-veri-onayi", action="store_true")
    a = ap.parse_args(argv)
    db = Path(a.db)
    if not a.uygula:
        session, motor = salt_okunur_oturum(db)
        try:
            metin = rapor_metni(kuru_calisma(session))
        finally:
            session.close()
            motor.dispose()
        print(metin)
        if a.rapor:
            Path(a.rapor).write_text(metin, encoding="utf-8")
        return 0
    if not a.yedek_klasoru:
        ap.error("--uygula için --yedek-klasoru zorunlu.")
    if _gercek_veri_klasoru_mu(db) and not a.gercek_veri_onayi:
        ap.error("Gerçek veri klasörü: önce kopya üzerinde deneyin; bilinçli uygulama için --gercek-veri-onayi.")
    print(json.dumps(tam_duzeltme(db, a.yedek_klasoru), default=str, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
