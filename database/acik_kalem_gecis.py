"""Açık kalem / kapatma altyapısına veri geçişi: yedek, kuru çalışma (rapor) ve mutabakat.

Kullanım (yalnız rapor; veritabanı salt okunur açılır):
    python -m database.acik_kalem_gecis --db KOPYA.db --rapor rapor.txt

Uygulama (önce doğrulanmış yedek alınır; gerçek veri klasöründe ek onay gerekir):
    python -m database.acik_kalem_gecis --db KOPYA.db --uygula --yedek-klasoru YEDEK

Kurallar:
- Eşleştirme güvenilir değilse (açık kalem neti ≠ cari bakiye) fark, açıklamalı
  "Geçiş Devir Farkı" kalemi olarak taşınır. Kalem satis_tutari=0 ile yazılır; cari bakiyeyi
  değiştirmez, gerçek fatura/tahsilat ile otomatik eşleştirilmez.
- Fatura içi tahsilatın cari bakiyeye yansımamasından doğan fark devir farkı yapılmaz;
  "manuel inceleme gereken bakiye farkı" olarak ayrıca raporlanır.
- Döviz kalemli cariler otomatik düzeltilmez, manuel inceleme listesine alınır.
- Her cari için en fazla bir devir farkı kaydı oluşur; tekrar çalıştırma mükerrer kayıt üretmez.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from database.acik_kalem_service import GECIS_DEVIR_ONEKI, TOLERANS, AcikKalemService, _kurus, para_anahtari
from database.models.cari import Cari, CariIslem, CariKapatma, SatisHareketi

DEVIR = "DEVIR_FARKI"
MANUEL = "MANUEL_INCELEME"
BAKIYE_FARKI_NEDENI = (
    "Fatura içi tahsilat açık kalemi kapatmış ancak cari bakiyeye alacak olarak yansımamış; "
    "manuel inceleme gereken bakiye farkı (otomatik devir farkı / bakiye düzeltmesi yapılmadı)."
)


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
    with closing(sqlite3.connect(f"file:{kaynak.resolve().as_posix()}?mode=ro", uri=True)) as src, \
            closing(sqlite3.connect(hedef)) as dst:
        src.backup(dst)
    return hedef


def _tablo_sayilari(db_yolu: str | os.PathLike) -> dict[str, int]:
    with closing(sqlite3.connect(f"file:{Path(db_yolu).resolve().as_posix()}?mode=ro", uri=True)) as c:
        tablolar = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        return {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tablolar}


def yedek_dogrula(kaynak: str | os.PathLike, yedek: str | os.PathLike, beklenen_rapor: dict) -> dict:
    """Yedeğin bütünlüğünü, tablo sayılarını ve geri yüklenebilirliğini doğrular.

    Geri yükleme provası: yedek geçici klasöre kopyalanır, oradan açılıp kuru çalışma yeniden
    hesaplanır; sonuç işlem öncesi raporla birebir aynı olmalıdır.
    """
    with closing(sqlite3.connect(f"file:{Path(yedek).resolve().as_posix()}?mode=ro", uri=True)) as c:
        butunluk = c.execute("PRAGMA integrity_check").fetchone()[0]
    kaynak_sayilari = _tablo_sayilari(kaynak)
    yedek_sayilari = _tablo_sayilari(yedek)
    farkli_tablolar = sorted(
        t for t in set(kaynak_sayilari) | set(yedek_sayilari)
        if kaynak_sayilari.get(t) != yedek_sayilari.get(t)
    )
    with tempfile.TemporaryDirectory() as gecici:
        geri = Path(gecici) / "geri_yukleme_provasi.db"
        shutil.copy2(yedek, geri)
        session, motor = salt_okunur_oturum(geri)
        try:
            prova = gecis_kuru_calisma(session, bugun=beklenen_rapor["tarih"])
        finally:
            session.close()
            motor.dispose()
    prova_ayni = _rapor_imzasi(prova) == _rapor_imzasi(beklenen_rapor)
    return {
        "yedek": str(yedek),
        "boyut": Path(yedek).stat().st_size,
        "butunluk": butunluk,
        "tablo_sayisi": len(yedek_sayilari),
        "farkli_tablolar": farkli_tablolar,
        "geri_yukleme_provasi_ayni": prova_ayni,
        "gecerli": butunluk == "ok" and not farkli_tablolar and prova_ayni,
    }


def _rapor_imzasi(rapor: dict) -> list[tuple]:
    return [(c["cari_id"], str(c["bakiye"]), str(c["acik_net"]), str(c["fark"])) for c in rapor["cariler"]]


def _kapatma_tablosu_var(session) -> bool:
    try:
        return AcikKalemService._tablo_var(session)
    except Exception:
        return False


def _gecis_tablosu_var(session) -> bool:
    from sqlalchemy import inspect as sa_inspect

    from database.models.acik_kalem_gecis import AcikKalemGecisKaydi

    return sa_inspect(session.connection()).has_table(AcikKalemGecisKaydi.__tablename__)


def fatura_ici_tahsilatlar(session, cari_id: int) -> list[tuple[str, Decimal]]:
    """Cari bakiyeye alacak olarak yansımamış fatura içi tahsilatlar: [(fatura_no, tutar)].

    Fatura içi tahsilat açık kalemi kapatır; cari hareketi (CariIslem) yoksa bakiye düşmez.
    """
    from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiTahsilati

    sonuc = []
    for fatura in session.scalars(
        select(SatisFaturasi).where(
            SatisFaturasi.cari_id == int(cari_id),
            SatisFaturasi.onaylandi.is_(True),
            func.coalesce(SatisFaturasi.durum, "") != "İPTAL",
        ).order_by(SatisFaturasi.id)
    ).all():
        if (getattr(fatura, "para_birimi", "TRY") or "TRY") != "TRY":
            continue
        toplam = sum(
            (Decimal(str(t.tutar or 0)) for t in session.scalars(
                select(SatisFaturasiTahsilati).where(SatisFaturasiTahsilati.fatura_id == fatura.id)
            ).all()),
            Decimal("0"),
        )
        if toplam <= 0:
            continue
        cari_hareketi = session.scalar(
            select(CariIslem.id).where(CariIslem.cari_id == int(cari_id), CariIslem.belge_no == fatura.fatura_no)
        )
        if cari_hareketi is None:
            sonuc.append((fatura.fatura_no, _kurus(toplam)))
    return sonuc


def gecis_kuru_calisma(session, *, bugun: date | None = None) -> dict:
    """Veriyi DEĞİŞTİRMEDEN cari bazında mutabakat ve önerilen geçiş işlemlerini döndürür."""
    bugun = bugun or date.today()
    tablo_var = _kapatma_tablosu_var(session)
    gecis_var = _gecis_tablosu_var(session)
    gecilmis: set[int] = set()
    if gecis_var:
        from database.models.acik_kalem_gecis import AcikKalemGecisKaydi

        gecilmis = set(session.scalars(select(AcikKalemGecisKaydi.cari_id)).all())
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
        fic = fatura_ici_tahsilatlar(session, cari.id)
        fic_toplam = _kurus(sum((t for _, t in fic), Decimal("0")))
        oneri = None
        if not m["uyumlu"]:
            if doviz_kalem:
                oneri = {
                    "islem": MANUEL,
                    "tutar": Decimal("0"),
                    "manuel_tutar": m["fark"],
                    "aciklama": "Döviz sabit açık kalem var; TL bakiye ile doğrudan karşılaştırılamaz.",
                }
            else:
                devir = _kurus(m["fark"] - fic_toplam)
                manuel_aciklama = BAKIYE_FARKI_NEDENI if fic_toplam else ""
                if abs(devir) <= TOLERANS:
                    oneri = {"islem": MANUEL, "tutar": Decimal("0"), "manuel_tutar": fic_toplam,
                             "aciklama": manuel_aciklama}
                elif cari.id in gecilmis:
                    oneri = {"islem": MANUEL, "tutar": Decimal("0"), "manuel_tutar": m["fark"],
                             "aciklama": "Bu cari için geçiş devir farkı daha önce oluşturulmuş; "
                                         "sonradan oluşan fark yeniden devredilmez, manuel inceleyin."}
                else:
                    oneri = {
                        "islem": DEVIR,
                        "tutar": devir,
                        "manuel_tutar": fic_toplam,
                        "aciklama": (
                            "Eski kapatmalar belge bazında eşleştirilemedi; net fark açıklamalı geçiş devri "
                            + ("(açık borç) olarak" if devir > 0 else "(avans/açık alacak) olarak")
                            + " taşındı. Gerçek fatura veya tahsilat değildir."
                        ),
                        "manuel_aciklama": manuel_aciklama,
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
            "fatura_ici_tahsilat": fic_toplam,
            "fatura_ici_belgeler": fic,
            "acik_kalem_sayisi": acik_sayi,
            "avans_kalem_sayisi": avans_sayi,
            "doviz_kalem_sayisi": doviz_kalem,
            "kayitli_kapatma_sayisi": kayitli,
            "oneri": oneri,
        })
    uyumsuz = [s for s in satirlar if not s["uyumlu"]]
    devirler = [s for s in uyumsuz if s["oneri"] and s["oneri"]["islem"] == DEVIR]
    manueller = [s for s in uyumsuz if s["oneri"] and s["oneri"]["manuel_tutar"]]
    return {
        "tarih": bugun,
        "kapatma_tablosu_var": tablo_var,
        "cari_sayisi": len(satirlar),
        "uyumlu_sayisi": len(satirlar) - len(uyumsuz),
        "uyumsuz_sayisi": len(uyumsuz),
        "devir_farki_sayisi": len(devirler),
        "devir_farki_toplam_mutlak": _kurus(sum((abs(s["oneri"]["tutar"]) for s in devirler), Decimal("0"))),
        "manuel_inceleme_sayisi": len(manueller),
        "manuel_inceleme_toplam": _kurus(sum((abs(s["oneri"]["manuel_tutar"]) for s in manueller), Decimal("0"))),
        "toplam_mutlak_fark": _kurus(sum((abs(s["fark"]) for s in uyumsuz), Decimal("0"))),
        "cariler": satirlar,
    }


def gecis_uygula(session, rapor: dict, *, tarih: date | None = None, yedek_yolu: str | None = None) -> list[dict]:
    """Kuru çalışma raporundaki DEVIR_FARKI önerilerini uygular (commit çağıran tarafta).

    Mükerrer kayıt koruması: carinin geçiş kaydı veya DVF kalemi varsa atlanır. Güncel fark,
    raporda planlanan tutardan sapmışsa (arada yeni işlem olmuşsa) cari atlanır.
    """
    from database.models.acik_kalem_gecis import AcikKalemGecisKaydi

    AcikKalemService.schema_hazirla(session.get_bind())
    AcikKalemGecisKaydi.__table__.create(bind=session.connection(), checkfirst=True)
    tarih = tarih or date.today()
    uygulanan = []
    for s in rapor["cariler"]:
        oneri = s.get("oneri")
        if not oneri or oneri["islem"] != DEVIR:
            continue
        cid = s["cari_id"]
        if session.scalar(select(AcikKalemGecisKaydi.id).where(AcikKalemGecisKaydi.cari_id == cid)) is not None:
            continue
        if session.scalar(select(SatisHareketi.id).where(
            SatisHareketi.cari_id == cid, SatisHareketi.belge_no.like(f"{GECIS_DEVIR_ONEKI}%")
        ).limit(1)) is not None:
            continue
        guncel = AcikKalemService.mutabakat(session, cid)
        fic = _kurus(sum((t for _, t in fatura_ici_tahsilatlar(session, cid)), Decimal("0")))
        devir = _kurus(guncel["fark"] - fic)
        if abs(devir) <= TOLERANS or abs(devir - Decimal(str(oneri["tutar"]))) > TOLERANS:
            continue
        belge_no = f"{GECIS_DEVIR_ONEKI}{cid}-{tarih:%Y%m%d}"
        hareket = SatisHareketi(
            cari_id=cid, satis_tarihi=tarih, belge_no=belge_no,
            satis_tutari=Decimal("0"), kalan_acik_tutar=devir, para_birimi="TRY",
            doviz_tutari=Decimal("0"), kur=Decimal("1"), borc_esasi="TL_SABIT",
        )
        session.add(hareket)
        session.flush()
        session.add(AcikKalemGecisKaydi(
            cari_id=cid, hareket_id=int(hareket.id), belge_no=belge_no, tutar=devir,
            onceki_bakiye=guncel["bakiye"], onceki_acik_net=guncel["acik_net"], haric_tutar=fic,
            aciklama=oneri["aciklama"][:500], tarih=tarih, olusturma=datetime.now(),
            yedek_yolu=(str(yedek_yolu)[:500] if yedek_yolu else None),
        ))
        session.flush()
        uygulanan.append({"cari_id": cid, "cari_kodu": s["cari_kodu"], "belge_no": belge_no, "tutar": devir,
                          "aciklama": oneri["aciklama"]})
    return uygulanan


def bakiye_anlik(session) -> dict[int, dict]:
    """Tüm carilerin (bakiyesi sıfır olanlar dahil) merkezi net bakiyesi."""
    from database.cari_bakiye_service import net_bakiye

    return {
        int(c.id): {"cari_kodu": c.cari_kodu, "bakiye": _kurus(net_bakiye(int(c.id), session=session)["bakiye"])}
        for c in session.scalars(select(Cari).order_by(Cari.id)).all()
    }


def bakiye_karsilastir(once: dict[int, dict], sonra: dict[int, dict], cari_idleri=None) -> dict:
    kume = set(cari_idleri) if cari_idleri is not None else set(once) | set(sonra)
    farklar = [
        {"cari_id": cid, "cari_kodu": (once.get(cid) or sonra.get(cid))["cari_kodu"],
         "once": (once.get(cid) or {}).get("bakiye"), "sonra": (sonra.get(cid) or {}).get("bakiye")}
        for cid in sorted(kume)
        if (once.get(cid) or {}).get("bakiye") != (sonra.get(cid) or {}).get("bakiye")
    ]
    return {"karsilastirilan": len(kume), "ayni": len(kume) - len(farklar), "farkli": farklar}


def mutabakat_raporu(session) -> list[dict]:
    """Tüm cariler için bakiye = açık borç − açık alacak − avans kontrolü."""
    return [
        AcikKalemService.mutabakat(session, cid)
        for cid in session.scalars(select(Cari.id).order_by(Cari.id)).all()
    ]


def _tl(d) -> str:
    return f"{Decimal(str(d)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def rapor_metni(rapor: dict, *, baslik: str = "KURU ÇALIŞMA RAPORU") -> str:
    satirlar = [
        f"AÇIK KALEM GEÇİŞİ — {baslik} ({rapor['tarih']:%d.%m.%Y})",
        f"Kapatma tablosu mevcut: {'Evet' if rapor['kapatma_tablosu_var'] else 'Hayır (ilk açılışta oluşturulur)'}",
        f"Hareketli cari: {rapor['cari_sayisi']} · Uyumlu: {rapor['uyumlu_sayisi']} · Uyumsuz: {rapor['uyumsuz_sayisi']}",
        f"Toplam mutlak fark: {_tl(rapor['toplam_mutlak_fark'])} TL",
        f"Geçiş Devir Farkı önerilen: {rapor['devir_farki_sayisi']} cari · {_tl(rapor['devir_farki_toplam_mutlak'])} TL (mutlak)",
        f"Manuel inceleme gereken bakiye farkı: {rapor['manuel_inceleme_sayisi']} cari · "
        f"{_tl(rapor['manuel_inceleme_toplam'])} TL (otomatik kayıt oluşturulmaz)",
        "",
        "Uyumsuz cariler:",
        f"  {'Kod':<12} {'Ünvan':<40} {'Bakiye':>14} {'Açık borç':>14} {'Avans':>12} {'Açık net':>14} "
        f"{'Fark':>12} {'Devir':>12} {'Manuel':>10}  Öneri",
    ]
    for s in [c for c in rapor["cariler"] if not c["uyumlu"]]:
        o = s["oneri"] or {}
        satirlar.append(
            f"  {s['cari_kodu']:<12} {str(s['unvan'])[:40]:<40} {_tl(s['bakiye']):>14} {_tl(s['acik_borc']):>14} "
            f"{_tl(s['avans']):>12} {_tl(s['acik_net']):>14} {_tl(s['fark']):>12} {_tl(o.get('tutar', 0)):>12} "
            f"{_tl(o.get('manuel_tutar', 0)):>10}  {o.get('islem', '-')}"
        )
    manuel = [c for c in rapor["cariler"] if c["oneri"] and c["oneri"]["manuel_tutar"]]
    if manuel:
        satirlar += ["", "MANUEL İNCELEME GEREKEN BAKİYE FARKLARI (otomatik devir farkı / bakiye düzeltmesi yapılmadı):"]
        for s in manuel:
            satirlar.append(f"  {s['cari_kodu']} {s['unvan']}: {_tl(s['oneri']['manuel_tutar'])} TL — {s['oneri']['aciklama'] or s['oneri'].get('manuel_aciklama', '')}")
            for no, t in s["fatura_ici_belgeler"]:
                satirlar.append(f"      {no}: fatura içi tahsilat {_tl(t)} TL, cari hareketi yok")
    return "\n".join(satirlar)


def _json_yaz(yol: Path, veri) -> None:
    yol.write_text(json.dumps(veri, default=str, ensure_ascii=False, indent=2), encoding="utf-8")


def _gercek_veri_klasoru_mu(yol: Path) -> bool:
    kok = Path(os.environ.get("LOCALAPPDATA", "")) / "MuhasebeProgrami"
    try:
        return kok.exists() and kok.resolve() in yol.resolve().parents
    except OSError:
        return False


def tam_gecis(db: str | os.PathLike, klasor: str | os.PathLike) -> dict:
    """Rapor → yedek → yedek doğrulama → uygulama → karşılaştırma → tekrar çalıştırma testi."""
    db = Path(db)
    klasor = Path(klasor)
    klasor.mkdir(parents=True, exist_ok=True)
    session, motor = salt_okunur_oturum(db)
    try:
        once_rapor = gecis_kuru_calisma(session)
        once_bakiye = bakiye_anlik(session)
    finally:
        session.close()
        motor.dispose()
    (klasor / "01_islem_oncesi_rapor.txt").write_text(rapor_metni(once_rapor, baslik="İŞLEM ÖNCESİ RAPOR"), encoding="utf-8")
    _json_yaz(klasor / "01_islem_oncesi_rapor.json", once_rapor)
    _json_yaz(klasor / "01_islem_oncesi_bakiyeler.json", once_bakiye)

    yedek = yedekle(db, klasor)
    dogrulama = yedek_dogrula(db, yedek, once_rapor)
    _json_yaz(klasor / "02_yedek_dogrulama.json", dogrulama)
    if not dogrulama["gecerli"]:
        raise RuntimeError(f"Yedek doğrulanamadı; geçiş uygulanmadı: {dogrulama}")

    session, motor = yazilabilir_oturum(db)
    try:
        uygulanan = gecis_uygula(session, once_rapor, yedek_yolu=str(yedek))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        motor.dispose()

    session, motor = yazilabilir_oturum(db)
    try:
        ikinci = gecis_uygula(session, gecis_kuru_calisma(session))
        session.rollback()
        sonra_rapor = gecis_kuru_calisma(session)
        sonra_bakiye = bakiye_anlik(session)
        dvf_sayisi = session.scalar(select(func.count(SatisHareketi.id)).where(
            SatisHareketi.belge_no.like(f"{GECIS_DEVIR_ONEKI}%")))
    finally:
        session.close()
        motor.dispose()
    rapor_cari = [c["cari_id"] for c in once_rapor["cariler"]]
    karsilastirma = bakiye_karsilastir(once_bakiye, sonra_bakiye, rapor_cari)
    tum_karsilastirma = bakiye_karsilastir(once_bakiye, sonra_bakiye)
    aciklanamayan = [
        c for c in sonra_rapor["cariler"]
        if not c["uyumlu"] and abs(c["fark"] - c["fatura_ici_tahsilat"]) > TOLERANS
    ]
    ozet = {
        "db": str(db),
        "yedek": dogrulama,
        "uygulanan_sayisi": len(uygulanan),
        "uygulanan": uygulanan,
        "dvf_kalem_sayisi": dvf_sayisi,
        "ikinci_calistirma_yeni_kayit": len(ikinci),
        "bakiye_karsilastirma_427": karsilastirma,
        "bakiye_karsilastirma_tum_cariler": {k: v for k, v in tum_karsilastirma.items()},
        "sonra_uyumlu": sonra_rapor["uyumlu_sayisi"],
        "sonra_uyumsuz": sonra_rapor["uyumsuz_sayisi"],
        "sonra_manuel_inceleme": [
            {"cari_kodu": c["cari_kodu"], "fark": c["fark"], "fatura_ici_tahsilat": c["fatura_ici_tahsilat"]}
            for c in sonra_rapor["cariler"] if not c["uyumlu"]
        ],
        "aciklanamayan_fark_sayisi": len(aciklanamayan),
    }
    (klasor / "03_islem_sonrasi_rapor.txt").write_text(rapor_metni(sonra_rapor, baslik="İŞLEM SONRASI RAPOR"), encoding="utf-8")
    _json_yaz(klasor / "03_islem_sonrasi_rapor.json", sonra_rapor)
    _json_yaz(klasor / "03_islem_sonrasi_bakiyeler.json", sonra_bakiye)
    _json_yaz(klasor / "04_gecis_ozeti.json", ozet)
    return ozet


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
        metin = rapor_metni(rapor)
        print(metin)
        if a.rapor:
            Path(a.rapor).write_text(metin, encoding="utf-8")
        if a.json:
            _json_yaz(Path(a.json), rapor)
        return 0
    if not a.yedek_klasoru:
        ap.error("--uygula için --yedek-klasoru zorunlu.")
    if _gercek_veri_klasoru_mu(db) and not a.gercek_veri_onayi:
        ap.error("Gerçek veri klasörü: önce kopya üzerinde deneyin; bilinçli uygulama için --gercek-veri-onayi.")
    ozet = tam_gecis(db, a.yedek_klasoru)
    print(json.dumps(ozet, default=str, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
