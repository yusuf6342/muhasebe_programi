"""Ana panel açık ekranlar yığını.

Her ana menü (GİRİŞ, SATIŞLAR, STOKLAR …) içerik alanında kendi kalıcı çerçevesinde
yaşar. Menü değiştirmek önceki ekranı yok etmez; gizler. ``app.icerik`` her zaman öndeki
ekranın çerçevesini gösterir, böylece modüllerin ``..._goster(app)`` fonksiyonları ve
``app._icerigi_temizle()`` yalnızca kendi ekranlarını etkiler.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from ana_panel_tema import ACIK_BG, BEYAZ, CIZGI, FONT_ALT, FONT_UI_BOLD, LACIVERT, PASIF

TEMEL_EKRAN = "giris"

EKRAN_BASLIKLARI: dict[str, str] = {
    "giris": "GİRİŞ",
    "hizli_satis": "HIZLI SATIŞ",
    "satislar": "SATIŞLAR",
    "satin_alma": "SATIN ALMA",
    "stoklar": "STOKLAR",
    "finans": "FİNANS",
    "gelir_gider": "GELİR-GİDER",
    "genel_muhasebe": "GENEL MUHASEBE",
    "cek_senet": "ÇEK VE SENET",
    "ozet_tablolar": "ÖZET TABLOLAR",
    "raporlar": "RAPORLAR",
    "sistem": "KULLANICI VE FİRMA",
    "servis": "SERVİS VE SİSTEM",
    "ayarlar": "AYARLAR",
}

# Uygulama geneli durum: ekran değişiminde saklanıp geri yüklenmez.
_ORTAK_ONEKLER = (
    "_busy",
    "_nav",
    "_ekran",
    "_aktarim",
    "_sayfa_yukleniyor",
    "_aktif_sayfa",
    "_cin_basarili",
    "_ana_panel_kabuk",
    "_last_child_ids",
    "_tclCommands",
    "_tkloaded",
)
_ORTAK_ADLAR = frozenset(
    {
        "icerik",
        "tk",
        "master",
        "children",
        "widgetName",
        "_w",
        "_name",
        "menu_dugmeleri",
        "ekran_kabi",
        "ekran_seridi",
        "app_version",
    }
)


def _ortak_mi(ad: str) -> bool:
    return ad in _ORTAK_ADLAR or ad.startswith(_ORTAK_ONEKLER)


def _icinde_mi(widget, kap) -> bool:
    try:
        yol = str(widget)
        kok = str(kap)
    except Exception:
        return False
    return yol == kok or yol.startswith(kok + ".")


class Ekran:
    """Tek bir ana menünün kalıcı çerçevesi ve ona ait gezinme/odak durumu."""

    def __init__(self, anahtar: str, cerceve: tk.Frame):
        self.anahtar = anahtar
        self.baslik = EKRAN_BASLIKLARI.get(anahtar, anahtar.upper())
        self.cerceve = cerceve
        self.son_odak = None
        self.nav_gecmis: list = []
        self.nav_yeniden_ac = None
        # Ekran öndeyken app üzerinde değişen öznitelikler (ör. cari_tablosu)
        self.durum: dict = {}
        self._baz: dict = {}
        # Ana menü kök sayfası mı gösteriliyor (alt sayfaya geçince False)
        self.kokte = False
        self.kapatma_kontrolleri: list[Callable[[], bool]] = []

    def var_mi(self) -> bool:
        try:
            return bool(self.cerceve.winfo_exists())
        except tk.TclError:
            return False


class EkranYoneticisi:
    def __init__(self, app, kap: tk.Frame, serit: tk.Frame | None = None):
        self.app = app
        self.kap = kap
        self.serit = serit
        self.ekranlar: dict[str, Ekran] = {}
        self.acilis_sirasi: list[str] = []
        # Son kullanılan en sonda (z-sırası); kapatınca bir öncekine dönülür
        self.yigin: list[str] = []
        self.aktif: Ekran | None = None

    # —— Sorgular ——
    def getir(self, anahtar: str) -> Ekran | None:
        ekran = self.ekranlar.get(anahtar)
        if ekran is not None and not ekran.var_mi():
            self._kayit_sil(anahtar)
            return None
        return ekran

    def aktif_anahtar(self) -> str | None:
        return self.aktif.anahtar if self.aktif is not None else None

    def ekran_bul(self, widget) -> Ekran | None:
        for ekran in self.ekranlar.values():
            if _icinde_mi(widget, ekran.cerceve):
                return ekran
        return None

    # —— Açma / öne getirme ——
    def olustur(self, anahtar: str) -> Ekran:
        mevcut = self.getir(anahtar)
        if mevcut is not None:
            self.one_getir(anahtar)
            return mevcut
        if not self.ekranlar:
            # Ekran öncesi kaba doğrudan çizilmiş artıklar
            for w in list(self.kap.winfo_children()):
                try:
                    w.destroy()
                except tk.TclError:
                    pass
        self._geri_plana_al()
        cerceve = tk.Frame(self.kap, bg=ACIK_BG)
        ekran = Ekran(anahtar, cerceve)
        self.ekranlar[anahtar] = ekran
        self.acilis_sirasi.append(anahtar)
        self.yigin.append(anahtar)
        self._goster(ekran, yeni=True)
        return ekran

    def one_getir(self, anahtar: str) -> bool:
        ekran = self.getir(anahtar)
        if ekran is None:
            return False
        if ekran is self.aktif:
            return True
        self._geri_plana_al()
        if anahtar in self.yigin:
            self.yigin.remove(anahtar)
        self.yigin.append(anahtar)
        self._goster(ekran, yeni=False)
        self.odakla(ekran)
        return True

    def odakla(self, ekran: Ekran | None = None) -> None:
        """Ekranın son odaklı alanına (yoksa çerçevesine) odak verir.

        Açık bir belge penceresi (Toplevel) odağı tutuyorsa ondan çalmaz.
        """
        ekran = ekran or self.aktif
        if ekran is None or not ekran.var_mi():
            return
        try:
            simdiki = self.app.focus_get()
        except (tk.TclError, KeyError):
            simdiki = None
        try:
            if simdiki is not None and simdiki.winfo_toplevel() is not self.app:
                return
        except tk.TclError:
            pass
        hedef = ekran.son_odak
        try:
            if hedef is not None and hedef.winfo_exists() and _icinde_mi(hedef, ekran.cerceve):
                hedef.focus_set()
                return
        except tk.TclError:
            pass
        if simdiki is not None and _icinde_mi(simdiki, ekran.cerceve):
            return
        try:
            ekran.cerceve.focus_set()
        except tk.TclError:
            pass

    # —— Kapatma ——
    def kapatma_kontrolu_ekle(self, fn: Callable[[], bool], anahtar: str | None = None) -> None:
        """Ekran kapatılırken çağrılır; False dönerse kapatma iptal edilir."""
        ekran = self.getir(anahtar) if anahtar else self.aktif
        if ekran is not None:
            ekran.kapatma_kontrolleri.append(fn)

    def _kapatilabilir_mi(self, ekran: Ekran) -> bool:
        for fn in list(ekran.kapatma_kontrolleri):
            try:
                if fn() is False:
                    return False
            except tk.TclError:
                continue
        return True

    def kapatma_onayi(self) -> bool:
        """Tüm açık ekranlar kapatılabilir mi (firma değiştir / oturum kapat / çıkış)."""
        for anahtar in list(reversed(self.yigin)):
            ekran = self.getir(anahtar)
            if ekran is None:
                continue
            if not self._kapatilabilir_mi(ekran):
                if ekran is not self.aktif:
                    self.one_getir(anahtar)
                return False
        return True

    def kapat(self, anahtar: str, *, sor: bool = True) -> bool:
        ekran = self.getir(anahtar)
        if ekran is None:
            return False
        if anahtar == TEMEL_EKRAN and sor:
            return False
        if sor and not self._kapatilabilir_mi(ekran):
            return False
        on_mu = ekran is self.aktif
        self._kayit_sil(anahtar)
        try:
            ekran.cerceve.destroy()
        except tk.TclError:
            pass
        if on_mu:
            onceki = next((a for a in reversed(self.yigin) if self.getir(a) is not None), None)
            if onceki is not None:
                self._goster(self.ekranlar[onceki], yeni=False)
                self.odakla(self.ekranlar[onceki])
            else:
                self._bosalt_icerik()
                acici = getattr(self.app, "ana_sayfa_goster", None)
                if callable(acici):
                    acici()
        else:
            self.serit_guncelle()
        return True

    def aktif_ekrani_kapat(self) -> bool:
        if self.aktif is None or self.aktif.anahtar == TEMEL_EKRAN:
            return False
        return self.kapat(self.aktif.anahtar)

    def tumunu_kapat(self) -> None:
        """Tüm ekranları yok eder (firma değiştir / oturum kapat)."""
        for anahtar in list(self.ekranlar):
            ekran = self.ekranlar.pop(anahtar)
            try:
                ekran.cerceve.destroy()
            except tk.TclError:
                pass
        self.acilis_sirasi.clear()
        self.yigin.clear()
        self.aktif = None
        self._bosalt_icerik()
        self.serit_guncelle()

    # —— İç işler ——
    def _kayit_sil(self, anahtar: str) -> None:
        self.ekranlar.pop(anahtar, None)
        if anahtar in self.acilis_sirasi:
            self.acilis_sirasi.remove(anahtar)
        if anahtar in self.yigin:
            self.yigin.remove(anahtar)
        if self.aktif is not None and self.aktif.anahtar == anahtar:
            self.aktif = None

    def _bosalt_icerik(self) -> None:
        app = self.app
        app.icerik = self.kap
        app._aktif_sayfa = None
        app._nav_gecmis = []
        app._nav_yeniden_ac = None

    def _durumu_yaz(self, ekran: Ekran) -> None:
        app = self.app
        ekran.nav_gecmis = list(getattr(app, "_nav_gecmis", None) or [])
        ekran.nav_yeniden_ac = getattr(app, "_nav_yeniden_ac", None)
        baz = ekran._baz
        for ad, deger in list(vars(app).items()):
            if _ortak_mi(ad):
                continue
            if ad in baz and baz[ad] is deger:
                continue
            if isinstance(deger, tk.Misc):
                # Başka pencereye / ekrana ait widget ekran durumu değildir
                if not _icinde_mi(deger, ekran.cerceve):
                    continue
            ekran.durum[ad] = deger

    def _geri_plana_al(self) -> None:
        ekran = self.aktif
        if ekran is None:
            return
        try:
            # Ana penceredeki son odak; odak o an bir belge penceresinde olsa da doğru
            odak = self.app.focus_lastfor()
        except (tk.TclError, KeyError):
            odak = None
        if odak is not None and _icinde_mi(odak, ekran.cerceve):
            ekran.son_odak = odak
        self._durumu_yaz(ekran)
        try:
            ekran.cerceve.pack_forget()
        except tk.TclError:
            pass
        self.aktif = None

    def _goster(self, ekran: Ekran, *, yeni: bool) -> None:
        app = self.app
        if not yeni:
            for ad, deger in ekran.durum.items():
                try:
                    setattr(app, ad, deger)
                except Exception:
                    pass
        app.icerik = ekran.cerceve
        app._aktif_sayfa = ekran.anahtar
        app._nav_gecmis = list(ekran.nav_gecmis)
        app._nav_yeniden_ac = ekran.nav_yeniden_ac
        app._nav_son_push = False
        app._nav_ileri = False
        ekran._baz = dict(vars(app))
        self.aktif = ekran
        try:
            ekran.cerceve.pack(fill="both", expand=True)
        except tk.TclError:
            pass
        kabuk = getattr(app, "_ana_panel_kabuk", None)
        if kabuk is not None:
            try:
                kabuk.menu_secili_guncelle(ekran.anahtar)
            except Exception:
                pass
        guncelle = getattr(app, "geri_cubugu_guncelle", None)
        if callable(guncelle):
            guncelle()
        self.serit_guncelle()

    # —— Açık ekranlar şeridi ——
    def serit_guncelle(self) -> None:
        serit = self.serit
        if serit is None:
            return
        try:
            for w in serit.winfo_children():
                w.destroy()
        except tk.TclError:
            return
        if not self.acilis_sirasi:
            return
        tk.Label(serit, text="Açık ekranlar:", bg=ACIK_BG, fg=PASIF, font=FONT_ALT).pack(
            side="left", padx=(4, 6)
        )
        for anahtar in self.acilis_sirasi:
            ekran = self.ekranlar.get(anahtar)
            if ekran is None:
                continue
            self._sekme_ciz(serit, ekran, ekran is self.aktif)

    def _sekme_ciz(self, serit: tk.Frame, ekran: Ekran, aktif: bool) -> None:
        bg = LACIVERT if aktif else BEYAZ
        fg = BEYAZ if aktif else LACIVERT
        sekme = tk.Frame(serit, bg=bg, highlightthickness=1, highlightbackground=CIZGI)
        sekme.pack(side="left", padx=2, pady=(0, 4))
        etiket = tk.Label(
            sekme,
            text=ekran.baslik,
            bg=bg,
            fg=fg,
            font=FONT_UI_BOLD if aktif else FONT_ALT,
            padx=10,
            pady=3,
            cursor="hand2",
        )
        etiket.pack(side="left")
        etiket.bind("<Button-1>", lambda _e, a=ekran.anahtar: self._sekme_tikla(a))
        if ekran.anahtar == TEMEL_EKRAN:
            return
        kapat = tk.Label(
            sekme, text="×", bg=bg, fg=fg, font=FONT_UI_BOLD, padx=6, pady=3, cursor="hand2"
        )
        kapat.pack(side="left")
        kapat.bind("<Button-1>", lambda _e, a=ekran.anahtar: self.kapat(a))

    def _sekme_tikla(self, anahtar: str) -> None:
        goster = getattr(self.app, "sayfa_goster", None)
        if callable(goster):
            goster(anahtar, ust_duzey=True)
        else:
            self.one_getir(anahtar)
