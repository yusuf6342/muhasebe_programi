"""Açık kalem / kapatma altyapısına veri geçişi: yedek, kuru çalışma (rapor) ve mutabakat.

Kullanım (yalnız rapor; veritabanı salt okunur açılır):
    python -m database.acik_kalem_gecis --db KOPYA.db --rapor rapor.txt

Uygulama (önce yedek alınır; gerçek veri klasöründe ek onay gerekir):
    python -m database.acik_kalem_gecis --db KOPYA.db --uygula --yedek-klasoru YEDEK

Kural: eşleştirme güvenilir değilse (açık kalem neti ≠ cari bakiye) fark, açıklamalı
"Geçiş Devir Farkı" kalemi olarak taşınır. Kalem satis_tutari=0 ile yazılır; cari bakiyeyi
değiştirmez, yalnız açık kalem netini bakiyeye eşitler. Döviz kalemli cariler otomatik
düzeltilmez, manuel inceleme listesine alınır.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database.acik_kalem_service import GECIS_DEVIR_ONEKI, AcikKalemService, _kurus, para_anahtari
from database.models.cari import Cari, CariKapatma, SatisHareketi


def _modelleri_yukle() -> None:
    """Bağımsız çalışmada tüm ORM ilişkileri çözülebilsin diye model modüllerini kaydeder."""
    import importlib
    import pkgutil

    import database.models as paket

    for bilgi in pkgutil.iter_modules(paket.__path__):
        importlib.import_module(f"{paket.__name__}.{bilgi.name}")


def salt_okunur_oturum(db_yolu: str | os.PathLike):
    _modelleri_yukle()
    yol = Path(db_yolu).resolve().as_posix()
    motor = create_engine(f"sqlite:///file:{yol}?mode=ro&uri=true", future=True)
    return sessionmaker(bind=motor, autoflush=False, future=True)(), motor


def yazilabilir_oturum(db_yolu: str | os.PathLike):
    _modelleri_yukle()
    motor = create_engine(f"sqlite:///{Path(db_yolu).resolve().as_posix()}", future=True)
    return sessionmaker(bind=motor, autoflush=False, future=True)(), motor


def yedekle(db_yolu: str | os.PathLike, hedef_klasor: str | os.PathLike) -> Path:
    """SQLite çevrimiçi yedek API'si ile tutarlı kopya."""
    kaynak = Path(db_yolu)
    hedef_klasor = Path(hedef_klasor)
    hedef_klasor.mkdir(parents=True, exist_ok=True)
    hedef = hedef_klasor / f"{kaynak.stem}_gecis_oncesi_{datetime.now():%Y%m%d_%H%M%S}{kaynak.suffix}"
    with sqlite3.connect(f"file:{kaynak.resolve().as_posix()}?mode=ro", uri=True) as src, sqlite3.connect(hedef) as dst:
        src.backup(dst)
    return hedef


def _kapatma_tablosu_var(session) -> bool:
    try:
        return AcikKalemService._tablo_var(session)
    except Exception:
        return False


def gecis_kuru_calisma(session, *, bugun: date | None = None) -> dict:
    """Veriyi DEĞİŞTİRMEDEN cari bazında mutabakat ve önerilen geçiş işlemlerini döndürür."""
    bugun = bugun or date.today()
    tablo_var = _kapatma_tablosu_var(session)
    cariler = session.scalars(select(Cari).order_by(Cari.id)).all()
    satirlar = []
    for cari in cariler:
        hareketler = session.scalars(select(SatisHareketi).where(SatisHareketi.cari_id == cari.id)).all()
        m = AcikKalemService.mutabakat(session, cari.id)
        if not hareketler and m["bakiye"] == 0:
            continue
        doviz_kalem = sum(1 for h in hareketler if para_anahtari(h) != "TRY" and abs(_kurus(h.kalan_acik_tutar)) > 0)
        acik_sayi = sum(1 for h in hareketler if _kurus(h.kalan_acik_tutar) > 0)
        avans_sayi = sum(1 for h in hareketler if _kurus(h.kalan_acik_tutar) < 0)
        kayitli = 0
        if tablo_var:
            kayitli = len(session.scalars(
                select(CariKapatma.id).where(CariKapatma.cari_id == cari.id, CariKapatma.iptal.is_(False))
            ).all())
        oneri = None
        if not m["uyumlu"]:
            if doviz_kalem:
                oneri = {
                    "islem": "MANUEL_INCELEME",
                    "tutar": m["fark"],
                    "aciklama": "Döviz sabit açık kalem var; TL bakiye ile doğrudan karşılaştırılamaz.",
                }
            else:
                oneri = {
                    "islem": "DEVIR_FARKI",
                    "tutar": m["fark"],
                    "aciklama": (
                        "Eski kapatmalar belge bazında eşleştirilemedi; net fark açıklamalı geçiş devri "
                        + ("(açık borç) olarak" if m["fark"] > 0 else "(avans/açık alacak) olarak")
                        + " taşınacak."
                    ),
                }
        satirlar.append({
            "cari_id": int(cari.id),
            "cari_kodu": cari.cari_kodu,
            "unvan": cari.unvan,
            "cari_turu": cari.cari_turu,
            "bakiye": m["bakiye"],
            "acik_borc": m["acik_borc"],
            "avans": m["avans"],
            "acik_net": m["acik_net"],
            "fark": m["fark"],
            "uyumlu": m["uyumlu"],
            "acik_kalem_sayisi": acik_sayi,
            "avans_kalem_sayisi": avans_sayi,
            "doviz_kalem_sayisi": doviz_kalem,
            "kayitli_kapatma_sayisi": kayitli,
            "oneri": oneri,
        })
    uyumsuz = [s for s in satirlar if not s["uyumlu"]]
    return {
        "tarih": bugun,
        "kapatma_tablosu_var": tablo_var,
        "cari_sayisi": len(satirlar),
        "uyumlu_sayisi": len(satirlar) - len(uyumsuz),
        "uyumsuz_sayisi": len(uyumsuz),
        "devir_farki_sayisi": sum(1 for s in uyumsuz if s["oneri"] and s["oneri"]["islem"] == "DEVIR_FARKI"),
        "manuel_inceleme_sayisi": sum(1 for s in uyumsuz if s["oneri"] and s["oneri"]["islem"] == "MANUEL_INCELEME"),
        "toplam_mutlak_fark": _kurus(sum((abs(s["fark"]) for s in uyumsuz), Decimal("0"))),
        "cariler": satirlar,
    }


def gecis_uygula(session, rapor: dict, *, tarih: date | None = None) -> list[dict]:
    """Kuru çalışma raporundaki DEVIR_FARKI önerilerini uygular (commit çağıran tarafta)."""
    AcikKalemService.schema_hazirla(session.get_bind())
    tarih = tarih or date.today()
    uygulanan = []
    for s in rapor["cariler"]:
        oneri = s.get("oneri")
        if not oneri or oneri["islem"] != "DEVIR_FARKI":
            continue
        guncel = AcikKalemService.mutabakat(session, s["cari_id"])
        fark = guncel["fark"]
        if guncel["uyumlu"] or fark == 0:
            continue
        belge_no = f"{GECIS_DEVIR_ONEKI}{s['cari_id']}-{tarih:%Y%m%d}"
        session.add(SatisHareketi(
            cari_id=s["cari_id"], satis_tarihi=tarih, belge_no=belge_no,
            satis_tutari=Decimal("0"), kalan_acik_tutar=fark, para_birimi="TRY",
            doviz_tutari=Decimal("0"), kur=Decimal("1"), borc_esasi="TL_SABIT",
        ))
        session.flush()
        if fark > 0:
            AcikKalemService.avanslari_uygula(session, s["cari_id"], para_birimi="TRY")
        uygulanan.append({"cari_id": s["cari_id"], "belge_no": belge_no, "tutar": fark,
                          "aciklama": oneri["aciklama"]})
    return uygulanan


def mutabakat_raporu(session) -> list[dict]:
    """Tüm cariler için bakiye = açık borç − açık alacak − avans kontrolü."""
    return [
        AcikKalemService.mutabakat(session, cid)
        for cid in session.scalars(select(Cari.id).order_by(Cari.id)).all()
    ]


def rapor_metni(rapor: dict, *, en_fazla: int = 200) -> str:
    satirlar = [
        f"AÇIK KALEM GEÇİŞİ — KURU ÇALIŞMA RAPORU ({rapor['tarih']:%d.%m.%Y})",
        f"Kapatma tablosu mevcut: {'Evet' if rapor['kapatma_tablosu_var'] else 'Hayır (ilk açılışta oluşturulur)'}",
        f"Hareketli cari: {rapor['cari_sayisi']} · Uyumlu: {rapor['uyumlu_sayisi']} · Uyumsuz: {rapor['uyumsuz_sayisi']}",
        f"Önerilen devir farkı: {rapor['devir_farki_sayisi']} · Manuel inceleme: {rapor['manuel_inceleme_sayisi']}",
        f"Toplam mutlak fark: {rapor['toplam_mutlak_fark']:,.2f} TL",
        "",
        "Uyumsuz cariler (bakiye / açık borç / avans / açık net / fark / öneri):",
    ]
    for s in [c for c in rapor["cariler"] if not c["uyumlu"]][:en_fazla]:
        oneri = s["oneri"]["islem"] if s["oneri"] else "-"
        satirlar.append(
            f"  {s['cari_kodu']:<12} {str(s['unvan'])[:40]:<40} {s['bakiye']:>14,.2f} {s['acik_borc']:>14,.2f} "
            f"{s['avans']:>12,.2f} {s['acik_net']:>14,.2f} {s['fark']:>12,.2f}  {oneri}"
        )
    return "\n".join(satirlar)


def _gercek_veri_klasoru_mu(yol: Path) -> bool:
    kok = Path(os.environ.get("LOCALAPPDATA", "")) / "MuhasebeProgrami"
    try:
        return kok.exists() and kok.resolve() in yol.resolve().parents
    except OSError:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Açık kalem geçişi: kuru çalışma / uygulama")
    ap.add_argument("--db", required=True)
    ap.add_argument("--rapor", help="Metin rapor dosyası")
    ap.add_argument("--json", help="JSON rapor dosyası")
    ap.add_argument("--uygula", action="store_true")
    ap.add_argument("--yedek-klasoru")
    ap.add_argument("--gercek-veri-onayi", action="store_true")
    a = ap.parse_args(argv)
    db = Path(a.db)
    if not a.uygula:
        session, motor = salt_okunur_oturum(db)
        try:
            rapor = gecis_kuru_calisma(session)
        finally:
            session.close()
            motor.dispose()
    else:
        if not a.yedek_klasoru:
            ap.error("--uygula için --yedek-klasoru zorunlu.")
        if _gercek_veri_klasoru_mu(db) and not a.gercek_veri_onayi:
            ap.error("Gerçek veri klasörü: önce kopya üzerinde deneyin; bilinçli uygulama için --gercek-veri-onayi.")
        yedek = yedekle(db, a.yedek_klasoru)
        print(f"Yedek: {yedek}")
        session, motor = yazilabilir_oturum(db)
        try:
            rapor = gecis_kuru_calisma(session)
            uygulanan = gecis_uygula(session, rapor)
            session.commit()
            rapor["uygulanan"] = uygulanan
        finally:
            session.close()
            motor.dispose()
    metin = rapor_metni(rapor)
    print(metin)
    if a.rapor:
        Path(a.rapor).write_text(metin, encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps(rapor, default=str, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
