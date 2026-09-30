"""Kurulu test EXE'si için ekran açılış denetimi.

    CinMuhasebe.exe --ekran-testi C:\\yol\\rapor.txt

Yalnız test kurulumunda (veya MUHASEBE_DB_DIR ile) çalışır; gerçek veri klasöründe reddeder.
İlk yönetici parolasıyla otomatik giriş yapar, ana menüleri ve belge/kart ekranlarını
ekran dışında açıp kapatır, sonucu rapor dosyasına yazar. Parolayı değiştirmez, kayıt yapmaz.
"""

from __future__ import annotations

import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

ANA_MENULER = (
    "giris",
    "satislar",
    "satin_alma",
    "stoklar",
    "finans",
    "gelir_gider",
    "ozet_tablolar",
    "genel_muhasebe",
)


def _ilk_parola(veri_klasoru: Path) -> str:
    dosya = veri_klasoru / "ILK_YONETICI_SIFRE.txt"
    for satir in dosya.read_text(encoding="utf-8").splitlines():
        if satir.startswith("Parola:"):
            return satir.split(":", 1)[1].strip()
    raise RuntimeError(f"İlk parola bulunamadı: {dosya}")


def _otomatik_giris(_parent) -> bool:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    import auth_ui
    from database.database import DB_DIR, get_system_session
    from database.session_manager import oturum
    from database.system.auth_service import AuthService
    from database.system.models import User

    AuthService.cikis()
    with get_system_session() as session:
        AuthService.giris(session, "admin", _ilk_parola(DB_DIR))
    with get_system_session() as session:
        user = session.scalar(
            select(User)
            .options(selectinload(User.role), selectinload(User.companies))
            .where(User.id == oturum.user_id)
        )
        firmalar = [auth_ui.firma_ozet(f) for f in AuthService.kullanici_firmalari(session, user)]
    auth_ui.firma_oturumu_ac(firmalar[0])
    return True


def calistir(rapor_yolu: str | Path, bootstrap) -> int:
    from database import database as db

    rapor = Path(rapor_yolu)
    rapor.parent.mkdir(parents=True, exist_ok=True)
    satirlar: list[str] = [
        f"Cin Muhasebe ekran testi — {datetime.now():%d.%m.%Y %H:%M:%S}",
        f"Program: {db.program_klasoru()}",
        f"Veri klasörü: {db.veri_konumu_ozeti()}",
    ]
    if not (db.TEST_KURULUMU or db.DB_DIR_KAYNAGI == "MUHASEBE_DB_DIR"):
        satirlar.append("REDDEDİLDİ: yalnız test kurulumunda çalışır.")
        rapor.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
        return 2

    mesajlar: list[tuple[str, str, str]] = []

    def _kaydet(tur, sonuc):
        def f(baslik="", metin="", **_k):
            mesajlar.append((tur, str(baslik), str(metin)))
            return sonuc

        return f

    yedek = {}
    for ad, sonuc in (
        ("showinfo", "ok"),
        ("showwarning", "ok"),
        ("showerror", "ok"),
        ("askyesno", True),
        ("askokcancel", True),
        ("askyesnocancel", False),
        ("askretrycancel", False),
        ("askquestion", "yes"),
    ):
        yedek[ad] = getattr(messagebox, ad)
        setattr(messagebox, ad, _kaydet(ad, sonuc))

    import auth_ui
    import branding
    import ui_pencere

    yedek_giris = auth_ui.oturum_akisi_calistir
    yedek_splash = branding.run_startup_with_splash
    yedek_pencere = ui_pencere.belge_penceresini_hazirla
    auth_ui.oturum_akisi_calistir = _otomatik_giris
    branding.run_startup_with_splash = lambda _root, fn: fn(lambda *_a, **_k: None)

    def _ekran_disi(win, **_k):
        try:
            win.geometry("1200x720+-6000+-6000")
        except tk.TclError:
            pass
        return {}

    ui_pencere.belge_penceresini_hazirla = _ekran_disi

    basarisiz = 0
    app = None
    geri_cagri_hatalari: list[str] = []
    try:
        from app import MuhasebeApp

        app = MuhasebeApp(startup_bootstrap=bootstrap)
        if not getattr(app, "_cin_basarili", False):
            raise RuntimeError("Giriş / açılış tamamlanamadı")
        app.geometry("1360x760+-6000+-6000")
        app.report_callback_exception = lambda *e: geri_cagri_hatalari.append(
            "".join(traceback.format_exception(*e))
        )

        from database.session_manager import oturum

        satirlar.append(f"Firma: {oturum.firma_unvan} (kod {oturum.firma_kodu})")
        satirlar.append(f"Kullanıcı: {oturum.kullanici_adi}")
        try:
            from sqlalchemy import func, select

            from database.database import get_session
            from database.models.cari import Cari
            from database.models.stok import StokKarti

            with get_session() as s:
                cari_n = s.scalar(select(func.count(Cari.id))) or 0
                stok_n = s.scalar(select(func.count(StokKarti.id))) or 0
                orn_c = s.scalar(select(func.count(Cari.id)).where(Cari.unvan.like("ÖRNEK VERİ%"))) or 0
                orn_s = s.scalar(
                    select(func.count(StokKarti.id)).where(StokKarti.stok_adi.like("ÖRNEK VERİ%"))
                ) or 0
                ilk_cari = s.scalar(select(Cari.id).order_by(Cari.id))
                ilk_stok = s.scalar(select(StokKarti.id).order_by(StokKarti.id))
            from database.models.stok import StokLotu
            from database.satis_faturasi_service import SatisFaturasiService

            with get_session() as s:
                stoklu = s.scalar(
                    select(func.count(func.distinct(StokLotu.stok_id))).where(StokLotu.kalan_miktar > 0)
                ) or 0
            satirlar.append(
                f"Kayıtlar: {cari_n} cari ({orn_c} ÖRNEK VERİ), {stok_n} stok ({orn_s} ÖRNEK VERİ), "
                f"{stoklu} üründe stok var"
            )
            satirlar.append(f"Sıradaki satış fatura no: {SatisFaturasiService.fatura_no()}")
        except Exception as exc:
            ilk_cari = ilk_stok = None
            satirlar.append(f"Kayıt sayımı yapılamadı: {exc}")
        satirlar.append("")

        def _dene(ad, fn):
            nonlocal basarisiz
            once_m, once_g = len(mesajlar), len(geri_cagri_hatalari)
            w = None
            try:
                w = fn()
                app.update()
                hatalar = [m for m in mesajlar[once_m:] if m[0] == "showerror"]
                hatalar += [("geri çağrı", "", g) for g in geri_cagri_hatalari[once_g:]]
                acik = w is None or (isinstance(w, tk.Misc) and bool(w.winfo_exists()))
                if hatalar or not acik:
                    basarisiz += 1
                    satirlar.append(f"HATA  {ad}")
                    for h in hatalar:
                        satirlar.append(f"      {h[0]}: {h[1]} — {h[2]}".rstrip())
                    if not acik:
                        satirlar.append("      pencere açılır açılmaz kapandı")
                else:
                    baslik = ""
                    if isinstance(w, (tk.Toplevel, tk.Tk)):
                        baslik = f" — «{w.title()}»"
                    satirlar.append(f"OK    {ad}{baslik}")
                for m in mesajlar[once_m:]:
                    if m[0] != "showerror":
                        satirlar.append(f"      (bilgi {m[0]}: {m[1]} — {m[2][:160]})")
            except Exception:
                basarisiz += 1
                satirlar.append(f"HATA  {ad}")
                satirlar.extend("      " + s for s in traceback.format_exc().rstrip().splitlines())
            finally:
                if isinstance(w, tk.Toplevel):
                    try:
                        w.grab_release()
                        w.destroy()
                    except tk.TclError:
                        pass
                try:
                    app.update()
                except tk.TclError:
                    pass

        def _menu(anahtar):
            def f():
                import time

                app.sayfa_goster(anahtar, ust_duzey=True)
                bitis = time.monotonic() + 30
                ekran = None
                while time.monotonic() < bitis:
                    app.update()
                    ekran = app._ekran_yoneticisi.getir(anahtar)
                    if (
                        not getattr(app, "_busy_pending", False)
                        and ekran is not None
                        and ekran.cerceve.winfo_children()
                    ):
                        break
                    time.sleep(0.05)
                if ekran is None or not ekran.cerceve.winfo_children():
                    raise RuntimeError("ekran içeriği çizilmedi")
                return None

            return f

        for anahtar in ANA_MENULER:
            _dene(f"Ana menü → {anahtar}", _menu(anahtar))

        from alis_ui import AlisFaturasiDialog
        from app import SatisFaturasiDialog
        from satis_siparisi_ui import SatisSiparisiKarti
        from cari_kart_ui import CariDialog
        from database.cari_service import CariService
        from stok_ui import StokKartiDialog
        from teklif_ui import TeklifDialog

        _dene("Satış faturası (yeni)", lambda: SatisFaturasiDialog(app, cari_ac=lambda c: CariDialog(app, c)))
        _dene("Alış faturası (yeni)", lambda: AlisFaturasiDialog(app))
        _dene("Teklif (yeni)", lambda: TeklifDialog(app))
        _dene("Satış siparişi (yeni)", lambda: SatisSiparisiKarti(app))
        _dene("Stok kartı (yeni)", lambda: StokKartiDialog(app))
        if ilk_stok is not None:
            _dene("Stok kartı (mevcut kayıt)", lambda: StokKartiDialog(app, stok=_stok_yukle(ilk_stok)))
        _dene("Cari kart (yeni)", lambda: CariDialog(app))
        if ilk_cari is not None:
            _dene("Cari kart (mevcut kayıt)", lambda: CariDialog(app, CariService.getir(ilk_cari)))
    except Exception:
        basarisiz += 1
        satirlar.append("HATA  Program açılışı")
        satirlar.extend("      " + s for s in traceback.format_exc().rstrip().splitlines())
        for m in mesajlar:
            satirlar.append(f"      {m[0]}: {m[1]} — {m[2]}")
    finally:
        for ad, f in yedek.items():
            setattr(messagebox, ad, f)
        auth_ui.oturum_akisi_calistir = yedek_giris
        branding.run_startup_with_splash = yedek_splash
        ui_pencere.belge_penceresini_hazirla = yedek_pencere
        if app is not None:
            try:
                app.destroy()
            except tk.TclError:
                pass

    satirlar.append("")
    satirlar.append("SONUÇ: " + ("BAŞARILI" if basarisiz == 0 else f"{basarisiz} HATA"))
    rapor.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    return 0 if basarisiz == 0 else 1


def _stok_yukle(stok_id: int):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from database.database import get_session
    from database.models.stok import StokKarti

    with get_session() as session:
        stok = session.scalar(
            select(StokKarti)
            .where(StokKarti.id == stok_id)
            .options(
                selectinload(StokKarti.fiyatlar),
                selectinload(StokKarti.lotlar),
                selectinload(StokKarti.birimler),
                selectinload(StokKarti.barkodlar),
                selectinload(StokKarti.resimler),
            )
        )
        session.expunge(stok)
        return stok
