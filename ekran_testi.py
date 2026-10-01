"""Kurulu test EXE'si için ekran açılış denetimi.

    CinMuhasebe.exe --ekran-testi C:\\yol\\rapor.txt [--kayit-dene]

Yalnız test kurulumunda (veya MUHASEBE_DB_DIR ile) çalışır; gerçek veri klasöründe reddeder.
İlk yönetici parolasıyla otomatik giriş yapar, ana menüleri ve belge/kart ekranlarını
ekran dışında açıp kapatır, sonucu rapor dosyasına yazar. Parolayı değiştirmez, kayıt yapmaz.
``--kayit-dene`` yalnız MUHASEBE_DB_DIR ile verilen geçici klasörde kabul edilir: Satın Alma
talebi ve masraf dağıtımı test kaydı oluşturup listeden yeniden açar.
"""

from __future__ import annotations

import tkinter as tk
import traceback
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

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


def calistir(rapor_yolu: str | Path, bootstrap, *, kayit_dene: bool = False) -> int:
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
        from alis_ui import AlisIadeFaturasiDialog, AlisIrsaliyesiDialog, AlisSiparisiDialog
        from satin_alma_ui import SatinAlmaTalepDialog, TedarikciTeklifDialog
        from satis_irsaliyesi_ui import SatisIrsaliyesiDialog

        _dene("Satış irsaliyesi (yeni)", lambda: SatisIrsaliyesiDialog(app))
        _dene("Alış siparişi (yeni)", lambda: AlisSiparisiDialog(app))
        _dene("Alış irsaliyesi (yeni)", lambda: AlisIrsaliyesiDialog(app))
        _dene("Alış iade faturası (yeni)", lambda: AlisIadeFaturasiDialog(app))
        _dene("Satın alma talebi (yeni)", lambda: SatinAlmaTalepDialog(app))
        _dene("Tedarikçi teklifi (yeni)", lambda: TedarikciTeklifDialog(app))
        _dene("Stok kartı (yeni)", lambda: StokKartiDialog(app))
        if ilk_stok is not None:
            _dene("Stok kartı (mevcut kayıt)", lambda: StokKartiDialog(app, stok=_stok_yukle(ilk_stok)))
        _dene("Cari kart (yeni)", lambda: CariDialog(app))
        if ilk_cari is not None:
            _dene("Cari kart (mevcut kayıt)", lambda: CariDialog(app, CariService.getir(ilk_cari)))

        _dene("Müşteri ekstresi: TL / USD karşılığı", lambda: _ekstre_denetimi(app, "rapor_musteri_ekstresi"))
        _dene("Tedarikçi ekstresi: TL / USD karşılığı", lambda: _ekstre_denetimi(app, "rapor_tedarikci_ekstresi"))
        _satin_alma_menuleri(app, _dene)
        if kayit_dene:
            if db.DB_DIR_KAYNAGI != "MUHASEBE_DB_DIR":
                basarisiz += 1
                satirlar.append("HATA  --kayit-dene yalnız MUHASEBE_DB_DIR geçici klasöründe çalışır")
            else:
                _dene("Satın alma talebi: kaydet → listeden yeniden aç", lambda: _talep_kayit_denetimi(app))
                _dene("Masraf dağıtımı: kaydet → listeden yeniden aç", lambda: _masraf_kayit_denetimi(app))
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


def _bekle(app, kosul, sure: float = 20.0) -> bool:
    import time

    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        app.update()
        if not getattr(app, "_busy_pending", False) and kosul():
            return True
        time.sleep(0.05)
    return False


def _alt_widgetlar(kok):
    yigin = list(kok.winfo_children())
    while yigin:
        w = yigin.pop()
        yield w
        yigin.extend(w.winfo_children())


def _ekstre_denetimi(app, metod: str):
    """Müşteri/tedarikçi ekstresi: ilk cari ile TL ve USD karşılığı görünümlerini getirir."""
    from cari_usd_rapor_ui import GORUNUM_TL, GORUNUM_USD

    getattr(app, metod)()
    app.update()
    degerler = list(app.ekstre_musteri.cget("values") or ())
    if not degerler:
        return None
    app.ekstre_musteri.set(degerler[0])
    dugme = next(
        w for w in _alt_widgetlar(app.icerik)
        if isinstance(w, ttk.Button) and str(w.cget("text")) == "Raporu Getir / Uygula"
    )
    app.ekstre_gorunum.set(GORUNUM_TL)
    dugme.invoke()
    app.update()
    app.ekstre_gorunum.set(GORUNUM_USD)
    dugme.invoke()
    app.update()
    if app._ekstre_usd is None or not app._ekstre_usd.winfo_ismapped():
        raise RuntimeError("USD karşılığı görünümü açılmadı")
    if not app._ekstre_usd.tablo.get_children():
        raise RuntimeError("USD karşılığı tablosu boş (toplam satırı bile yok)")
    return None


def _hub_karti(app, baslik: str):
    return next(
        (w for w in _alt_widgetlar(app.icerik)
         if w.__class__.__name__ == "HubKart" and getattr(w, "_baslik", "") == baslik),
        None,
    )


def _gorunur_metinler(kok) -> list[str]:
    return [
        str(w.cget("text")) for w in _alt_widgetlar(kok)
        if isinstance(w, tk.Label) and w.winfo_ismapped()
    ]


def _satin_alma_hubuna_don(app) -> None:
    from satin_alma_ui import satin_alma_hub_goster

    app.sayfa_goster("satin_alma", ust_duzey=True)
    _bekle(app, lambda: app._ekran_yoneticisi.aktif_anahtar() == "satin_alma")
    satin_alma_hub_goster(app)
    if not _bekle(app, lambda: _hub_karti(app, "MASRAF DAĞITIMI") is not None):
        raise RuntimeError("Satın Alma hub kartları çizilmedi")


def _kart_tikla_liste(app, kart: str, baslik: str):
    _satin_alma_hubuna_don(app)
    _hub_karti(app, kart)._click()
    if not _bekle(app, lambda: _hub_karti(app, kart) is None and baslik in _gorunur_metinler(app.icerik)):
        raise RuntimeError(
            f"«{baslik}» ekranı görünür olmadı; içerikte {len(app.icerik.winfo_children())} çerçeve var"
        )
    return next(w for w in _alt_widgetlar(app.icerik) if w.winfo_class() == "Treeview")


def _kart_tikla_pencere(app, kart: str):
    _satin_alma_hubuna_don(app)
    once = {str(w) for w in app.winfo_children()}
    _hub_karti(app, kart)._click()
    yeni: list = []

    def acildi():
        yeni[:] = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and str(w) not in once]
        return bool(yeni)

    if not _bekle(app, acildi):
        raise RuntimeError("kart tıklandı ama pencere açılmadı")
    if not yeni[0].winfo_viewable():
        raise RuntimeError("pencere açıldı ama görünür değil")
    return yeni[0]


def _satin_alma_menuleri(app, dene) -> None:
    def liste(baslik):
        def ac():
            _kart_tikla_liste(app, baslik, baslik)

        return ac

    dene("Satın Alma → MASRAF DAĞITIMI kartı (liste görünür)", liste("MASRAF DAĞITIMI"))
    dene("Satın Alma → SATIN ALMA TALEP LİSTESİ kartı (liste görünür)", liste("SATIN ALMA TALEP LİSTESİ"))
    dene("Satın Alma → SATIN ALMA TALEPLERİ kartı (form)", lambda: _kart_tikla_pencere(app, "SATIN ALMA TALEPLERİ"))


def _ekran_testi_kayitlari() -> dict:
    """Geçici test klasöründe masraf dağıtımı için tedarikçi, ürün, alış ve gider belgesi."""
    from datetime import date
    from decimal import Decimal

    from sqlalchemy import select

    from database.alis_faturasi_service import AlisFaturasiService
    from database.database import get_session
    from database.hizmet_faturasi_service import HizmetFaturasiService
    from database.models.alis_faturasi import AlisFaturasiSatiri
    from database.models.cari import Cari
    from database.models.hizmet import HizmetKarti
    from database.models.stok import StokKarti

    with get_session() as s:
        if s.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == "EKRANTEST")) is None:
            s.add(StokKarti(stok_kodu="EKRANTEST", stok_adi="Ekran Testi Ürünü", birim="Adet", aktif=True,
                            is_deleted=False))
        if s.scalar(select(HizmetKarti.id).where(HizmetKarti.hizmet_kodu == "EKRANNAK")) is None:
            s.add(HizmetKarti(hizmet_kodu="EKRANNAK", hizmet_adi="Ekran Testi Nakliye", hizmet_turu="GIDER",
                              birim="Adet", aktif=True))
        for kod, unvan in (("EKRANTED", "Ekran Testi Tedarikçi"), ("EKRANNAKL", "Ekran Testi Nakliyeci")):
            if s.scalar(select(Cari.id).where(Cari.cari_kodu == kod)) is None:
                s.add(Cari(cari_kodu=kod, unvan=unvan, cari_turu="Tedarikçi", aktif=True))
    with get_session() as s:
        tedarikci = s.scalar(select(Cari.id).where(Cari.cari_kodu == "EKRANTED"))
        nakliyeci = s.scalar(select(Cari.id).where(Cari.cari_kodu == "EKRANNAKL"))
    bugun = date.today()
    alis = AlisFaturasiService.kaydet(
        {"fatura_tarihi": bugun, "vade_tarihi": bugun, "cari_id": tedarikci, "depo": "ANA DEPO",
         "odeme_tutari": Decimal("0")},
        [{"urun_kodu": "EKRANTEST", "urun_adi": "Ekran Testi Ürünü", "miktar": Decimal("10"), "birim": "Adet",
          "birim_fiyat": Decimal("100"), "iskonto_orani": Decimal("0"), "kdv_orani": Decimal("20")}],
    )
    gider = HizmetFaturasiService.kaydet(
        {"fatura_tarihi": bugun, "vade_tarihi": bugun, "cari_id": nakliyeci, "fatura_turu": "GIDER",
         "odeme_tutari": Decimal("0")},
        [{"hizmet_kodu": "EKRANNAK", "miktar": Decimal("1"), "birim_fiyat": Decimal("100"),
          "kdv_orani": Decimal("20")}],
    )
    with get_session() as s:
        alis_satir = s.scalar(select(AlisFaturasiSatiri.id).where(AlisFaturasiSatiri.fatura_id == alis.id))
    return {"alis_satir": int(alis_satir), "gider_id": int(gider.id)}


def _talep_kayit_denetimi(app):
    from decimal import Decimal

    from satin_alma_talep_ui import talep_formu_ac

    d = _kart_tikla_pencere(app, "SATIN ALMA TALEPLERİ")
    satir = d._yeni_satir(("EKRANTEST", "Ekran Testi Ürünü", "Adet"))
    satir["miktar"] = Decimal("3")
    d.satirlar.append(satir)
    d._satirlari_yenile()
    d.departman.insert(0, "Ekran testi")
    if not d._kaydet():
        raise RuntimeError(f"talep kaydedilemedi: {d.mesaj_lbl.cget('text')}")
    tid = d.talep_id
    d.destroy()
    tablo = _kart_tikla_liste(app, "SATIN ALMA TALEP LİSTESİ", "SATIN ALMA TALEP LİSTESİ")
    if str(tid) not in tablo.get_children():
        raise RuntimeError(f"kaydedilen talep (id={tid}) listede yok")
    d2 = talep_formu_ac(app, tid)
    if d2 is None or d2.departman.get() != "Ekran testi" or len(d2.satirlar) != 1:
        raise RuntimeError("yeniden açılan talep kaydedilen bilgileri göstermiyor")
    return d2


def _masraf_kayit_denetimi(app):
    from database.masraf_dagitim_service import MasrafDagitimService
    from masraf_dagitim_ui import MasrafDagitimDialog
    from satin_alma_ui import pencere_ac

    veri = _ekran_testi_kayitlari()
    d = pencere_ac(app, MasrafDagitimDialog, baslik="Masraf dağıtımı")
    if d is None:
        raise RuntimeError("masraf dağıtımı kartı açılmadı")
    d.kaynak_ayarla(veri["gider_id"])
    d.hedef_ekle([h for h in MasrafDagitimService.hedef_satirlar() if h["satir_id"] == veri["alis_satir"]])
    if not d.taslak_kaydet(sessiz=True):
        raise RuntimeError("masraf dağıtımı taslağı kaydedilemedi")
    did = d.dagitim_id
    d.destroy()
    tablo = _kart_tikla_liste(app, "MASRAF DAĞITIMI", "MASRAF DAĞITIMI")
    if str(did) not in tablo.get_children():
        raise RuntimeError(f"kaydedilen dağıtım (id={did}) listede yok")
    d2 = pencere_ac(app, MasrafDagitimDialog, dagitim_id=did, baslik="Masraf dağıtımı")
    if d2 is None or d2.kaynak["id"] != veri["gider_id"] or [h["satir_id"] for h in d2.hedefler] != [
        veri["alis_satir"]
    ]:
        raise RuntimeError("yeniden açılan dağıtım kaydedilen bilgileri göstermiyor")
    return d2


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
