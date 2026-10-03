"""Stok kalanları ölçümü — gerçek firma DB'sinin GEÇİCİ KOPYASI üzerinde (gerçek dosya yalnız okunur).

1. STK-013: ağır stok raporlarının servis süresi ve arayüz kilitlenmesi.
   * Önce (eski davranış): sorgu + tablo doldurma ana thread'de → arayüz bu süre boyunca donar.
   * Sonra: ``arka_plan_rapor`` + ``tabloyu_parcali_doldur``; ana thread'de 10 ms'lik sayaç çalışır,
     iki tık arası en uzun boşluk = arayüzün en uzun donma süresi.
   Sonuç: inceleme\\stoklar\\stk013_performans.json
2. Stok uyarıları yeniden sınıflandırma (Tükendi / Stok girişi yok / Kritik): önce/sonra sayıları,
   geçmiş olay kayıtlarının korunduğu, yeni bildirim sayısı. Sonuç: inceleme\\stoklar\\stok_uyari_siniflandirma.json

Kullanım: .venv\\Scripts\\python.exe tools\\stok_kalanlar_olcum.py --db KOPYA_VEYA_GERCEK [--sadece rapor|uyari]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STK013 = ROOT / "inceleme" / "stoklar" / "stk013_performans.json"
UYARI = ROOT / "inceleme" / "stoklar" / "stok_uyari_siniflandirma.json"


def _kopyala(kaynak: Path, hedef: Path) -> None:
    src = sqlite3.connect(f"file:{kaynak.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(str(hedef))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _bagla(kopya: Path) -> None:
    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import sessionmaker

    from database.database import Base, _aktif_engine_bagla, cari_kart_schemasini_guncelle, company_db, get_session
    from database.models.donem import Donem
    from database.session_manager import oturum
    from tests.stok_test_ortami import _modelleri_yukle, _pragma

    engine = create_engine(f"sqlite:///{kopya.as_posix()}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", _pragma)
    _modelleri_yukle()
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    _aktif_engine_bagla(engine)
    company_db._engine = engine
    company_db._session_factory = Session
    company_db._company_id = 1
    company_db._db_path = kopya
    cari_kart_schemasini_guncelle()
    oturum.clear()
    oturum.set_user(user_id=1, kullanici_adi="olcum", ad_soyad="Ölçüm", role_kod="YONETICI",
                    role_ad="Yönetici", permissions=set())
    oturum.set_company(company_id=1, firma_kodu="OLC", firma_unvan="Ölçüm", firma_uid="olcum", db_path=str(kopya))
    with get_session() as s:
        d = s.scalar(select(Donem).where(Donem.aktif.is_(True)).limit(1)) or s.scalar(select(Donem).limit(1))
        if d is not None:
            oturum.set_period(d.id, d.donem_adi)
    import database.stok_service  # noqa: F401  (kancaları kaydeder)


def rapor_olcumu() -> dict:
    import tkinter as tk
    from tkinter import ttk

    import stok_rapor_ui
    from database.rapor_service import RaporService
    from stok_rapor_ui import arka_plan_rapor, tabloyu_parcali_doldur

    hatalar: list[str] = []
    stok_rapor_ui.messagebox.showerror = lambda baslik, mesaj, **_k: hatalar.append(f"{baslik}: {mesaj}")

    bugun = date.today()
    raporlar = {
        "satilmayan_urunler": (lambda: RaporService.satilmayan_urunler(30, None), 6),
        "stok_devir_hizi": (lambda: RaporService.stok_devir_hizi(date(bugun.year, 1, 1), bugun, None, "FIFO"), 8),
        "stok_hareket_raporu_bu_ay": (lambda: RaporService.stok_hareket_raporu(
            baslangic=bugun.replace(day=1), bitis=bugun, stok=None, depo_adi=None, hareket_turu=None,
            belge_no=None, lot=None), 11),
        "stok_hareket_raporu_yil": (lambda: RaporService.stok_hareket_raporu(
            baslangic=date(bugun.year, 1, 1), bitis=bugun, stok=None, depo_adi=None, hareket_turu=None,
            belge_no=None, lot=None), 11),
        "stok_envanter": (lambda: RaporService.stok_envanter(tarih=bugun, maliyet_yontemi="FIFO"), 8),
    }
    root = tk.Tk()
    root.withdraw()
    sonuc: dict = {}
    for ad, (yukle, kolon) in raporlar.items():
        # Önce: eski senkron akış — sorgu + tüm satırların tek seferde eklenmesi ana thread'de
        cerceve = ttk.Frame(root)
        tablo = ttk.Treeview(cerceve, columns=[f"k{i}" for i in range(kolon)], show="headings")
        print(ad, "ölçülüyor…", flush=True)
        t0 = time.perf_counter()
        try:
            rapor = yukle()
        except Exception as hata:  # noqa: BLE001
            sonuc[ad] = {"hata": f"{type(hata).__name__}: {hata}"}
            print(ad, sonuc[ad], flush=True)
            cerceve.destroy()
            continue
        t_sorgu = time.perf_counter() - t0
        for s in rapor["satirlar"]:
            tablo.insert("", "end", values=[str(v) for v in list(s.values())[:kolon]])
        root.update()
        t_once = time.perf_counter() - t0
        satir = len(rapor["satirlar"])
        tablo.destroy()

        # Sonra: arka plan + parçalı doldurma; ana thread'de 10 ms sayaç
        tablo = ttk.Treeview(cerceve, columns=[f"k{i}" for i in range(kolon)], show="headings")
        ozet = ttk.Label(cerceve, text="")
        buton = ttk.Button(cerceve, text="Getir")
        durum = {"bitti": False, "son": None, "max_bosluk": 0.0, "tik": 0, "yukleniyor_goruldu": False}

        def tik():
            simdi = time.perf_counter()
            if durum["son"] is not None:
                durum["max_bosluk"] = max(durum["max_bosluk"], simdi - durum["son"])
            durum["son"] = simdi
            durum["tik"] += 1
            if not durum["bitti"]:
                root.after(10, tik)

        def goster(r, _tablo=tablo):
            tabloyu_parcali_doldur(_tablo, r["satirlar"], lambda s: [str(v) for v in list(s.values())[:kolon]],
                                   bitti=lambda: durum.update(bitti=True))
            if not r["satirlar"]:
                durum["bitti"] = True

        t1 = time.perf_counter()
        durum["son"] = t1
        root.after(10, tik)
        arka_plan_rapor(root, ozet, buton, yukle, goster, ad)
        durum["yukleniyor_goruldu"] = ozet.cget("text").startswith("Yükleniyor")
        sinir = time.perf_counter() + 600
        while not durum["bitti"] and not hatalar and time.perf_counter() < sinir:
            root.update()
            time.sleep(0.002)
        if hatalar:
            durum["hata"] = hatalar.pop()
        t_sonra = time.perf_counter() - t1
        eklenen = len(tablo.get_children())
        cerceve.destroy()
        sonuc[ad] = {
            "satir": satir, "servis_sorgu_sn": round(t_sorgu, 3),
            "once_arayuz_donma_sn": round(t_once, 3),
            "sonra_toplam_sure_sn": round(t_sonra, 3),
            "sonra_en_uzun_arayuz_donmasi_sn": round(durum["max_bosluk"], 3),
            "sonra_sayac_tik": durum["tik"], "yukleniyor_gostergesi": durum["yukleniyor_goruldu"],
            "tabloya_eklenen": eklenen, **({"hata": durum["hata"]} if durum.get("hata") else {}),
        }
        print(ad, sonuc[ad], flush=True)
    root.destroy()
    return sonuc


def _uyari_sayilari(session) -> dict:
    from sqlalchemy import func, select

    from database.models.stok_uyari import StokIhtiyac, StokIhtiyacGecmisi

    aktif = list(session.scalars(select(StokIhtiyac).where(StokIhtiyac.aktif.is_(True))).all())
    dagilim: dict[str, int] = {}
    for k in aktif:
        dagilim[k.nedenler or ""] = dagilim.get(k.nedenler or "", 0) + 1
    return {
        "ihtiyac_kaydi_toplam": session.scalar(select(func.count(StokIhtiyac.id))),
        "aktif": len(aktif),
        "neden_dagilimi": dict(sorted(dagilim.items(), key=lambda x: -x[1])),
        "gecmis_kaydi_toplam": session.scalar(select(func.count(StokIhtiyacGecmisi.id))),
        "gorulmemis": sum(1 for k in aktif if not k.goruldu),
    }


def uyari_siniflandir() -> dict:
    from sqlalchemy import func, select

    from database.database import get_session
    from database.models.stok_uyari import StokIhtiyacGecmisi
    from database.stok_uyari_service import StokUyariService

    sonuc: dict = {}
    with get_session() as s:
        if not StokUyariService.tablolar_var(s):
            StokUyariService.schema_hazirla()
    with get_session() as s:
        sonuc["once"] = _uyari_sayilari(s)
        gecmis_once = {g.id: (g.ihtiyac_id, g.islem, g.detay) for g in s.scalars(select(StokIhtiyacGecmisi)).all()}
    sonuc["once"]["aktif_sayisi"] = StokUyariService.aktif_sayisi()
    sonuc["siniflandirma_gerekli_once"] = StokUyariService.ilk_tarama_gerekli()
    StokUyariService.olaylari_al()
    t = time.perf_counter()
    sonuc["tarama"] = StokUyariService.toplu_degerlendir(ilk_tarama=True)
    sonuc["tarama"]["olcum_sn"] = round(time.perf_counter() - t, 2)
    sonuc["yeni_bildirim"] = len(StokUyariService.olaylari_al())
    with get_session() as s:
        sonuc["sonra"] = _uyari_sayilari(s)
        gecmis_sonra = {g.id: (g.ihtiyac_id, g.islem, g.detay) for g in s.scalars(select(StokIhtiyacGecmisi)).all()}
        sonuc["yeni_gecmis_islemleri"] = dict(s.execute(
            select(StokIhtiyacGecmisi.islem, func.count()).where(StokIhtiyacGecmisi.id.notin_(list(gecmis_once) or [0]))
            .group_by(StokIhtiyacGecmisi.islem)).all())
    sonuc["sonra"]["aktif_sayisi"] = StokUyariService.aktif_sayisi()
    sonuc["gecmis_korundu"] = all(gecmis_sonra.get(i) == v for i, v in gecmis_once.items())
    sonuc["siniflandirma_gerekli_sonra"] = StokUyariService.ilk_tarama_gerekli()
    print(json.dumps({k: sonuc[k] for k in ("tarama", "yeni_bildirim", "gecmis_korundu", "yeni_gecmis_islemleri")},
                     ensure_ascii=False, default=str))
    print("Önce:", sonuc["once"]["aktif_sayisi"], "Sonra:", sonuc["sonra"]["aktif_sayisi"])
    return sonuc


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--sadece", choices=("rapor", "uyari"))
    a = ap.parse_args()
    gecici = Path(tempfile.mkdtemp(prefix="cin_stok_kalan_olcum_"))
    os.environ["MUHASEBE_DB_DIR"] = str(gecici)
    kopya = gecici / "firma.db"
    _kopyala(Path(a.db), kopya)
    _bagla(kopya)
    ortak = {"kaynak": str(a.db), "kopya": str(kopya), "zaman": datetime.now().isoformat(timespec="seconds")}
    if a.sadece in (None, "rapor"):
        STK013.write_text(json.dumps({**ortak, "raporlar": rapor_olcumu(),
                                      "aciklama": ("once_arayuz_donma_sn: eski senkron akışta arayüzün donduğu süre "
                                                   "(sorgu + tablo doldurma). sonra_en_uzun_arayuz_donmasi_sn: arka "
                                                   "plan + parçalı doldurmada ana thread'in en uzun cevapsız kaldığı "
                                                   "süre (10 ms sayaç tıkları arası).")},
                                     ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print("Rapor:", STK013)
    if a.sadece in (None, "uyari"):
        UYARI.write_text(json.dumps({**ortak, **uyari_siniflandir()}, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")
        print("Rapor:", UYARI)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
