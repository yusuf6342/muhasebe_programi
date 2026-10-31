"""Ortak menü araması — Ctrl+K / Menü ara alanı.

Menü envanteri ``ana_panel_ui.MENU_OGELERI`` / ``MENU_ALT_OGELERI`` ve bilinen hub
kayıtlarından üretilir; yeni menü eklendiğinde buraya ikinci bir liste yazmak gerekmez
(hub kayıtları ``EK_MENU_KAYITLARI`` ile genişletilir).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from database.turkce_normalize import turkce_normalize


def _yetki_var(*kodlar: str) -> bool:
    try:
        from database.access import yetki_var

        return bool(yetki_var(*kodlar)) if kodlar else True
    except Exception:
        return True


# (id, ad, yol, es_anlamlilar, acici_fn_factory, yetki_kodlari)
# acici: app -> None  (lazy; string tip: "sayfa:xxx" | "alt:metot" | "fn:modul.fonksiyon")
EK_MENU_KAYITLARI: tuple[tuple[str, str, str, tuple[str, ...], str, tuple[str, ...]], ...] = (
    (
        "satis.teklifler",
        "Teklifler",
        "Satışlar › Teklifler",
        ("teklif", "teklif formu", "fiyat teklifi", "müşteri teklifi", "quote"),
        "fn:teklif_ui.teklifler_hub_goster",
        ("satis_goruntuleme", "goruntuleme", "satis_duzenleme", "yeni_kayit"),
    ),
    (
        "ozet.bilanco",
        "Dönen Sermaye Bilançosu",
        "Özet Tablolar › Dönen Sermaye Bilançosu",
        ("bilanço", "bilanco", "sermaye"),
        "fn:bilanco_ui.bilanco_sayfasi_goster",
        ("finans_goruntuleme", "satis_goruntuleme", "goruntuleme"),
    ),
    (
        "ozet.gelir_tablosu",
        "Gelir Tablosu",
        "Özet Tablolar › Gelir Tablosu",
        ("gelir", "zarar", "kar zarar", "dönem kârı", "donem kari", "gider grupları", "karşılaştırmalı gelir tablosu"),
        "fn:gelir_tablosu_ui.gelir_tablosu_sayfasi_goster",
        ("finans_goruntuleme", "satis_goruntuleme", "goruntuleme"),
    ),
    (
        "gg.gider_raporlari",
        "Gider Raporları",
        "Gelir ve Giderler › Giderler › Gider Raporları",
        ("gider raporları", "masraf", "gider dağılımı", "kârı tüketen giderler", "bütçe", "POS maliyeti", "başa baş", "R01", "R08"),
        "fn:gider_rapor_ui.gider_raporlari_merkezi_goster",
        ("finans_goruntuleme", "goruntuleme"),
    ),
    (
        "gg.gider_rapor_ayarlari",
        "Gider Rapor Ayarları",
        "Gelir ve Giderler › Giderler › Gider Rapor Ayarları",
        ("gider sınıf", "dağıtım kuralları", "bütçe planları", "rapor tanımları"),
        "fn:gider_rapor_ui.gider_rapor_ayarlari_goster",
        ("finans_goruntuleme", "goruntuleme"),
    ),
    (
        "gg.gider_kartlari",
        "Gider Hizmet Kartları",
        "Gelir ve Giderler › Giderler › Gider Hizmet Kartları",
        ("gider kartı", "hizmet gider"),
        "fn:gelir_gider_ui.giderler_menusu_goster",
        ("finans_goruntuleme", "goruntuleme"),
    ),
    (
        "ozet.kar_gerceklesme",
        "Tahsilat ve Mahsup Esaslı Kâr Gerçekleşme Raporu",
        "Özet Tablolar › Kârlılık › Tahsilat ve Mahsup Esaslı Kâr Gerçekleşme Raporu",
        ("kâr", "kar", "gerçekleşme", "gerceklesme", "tahsilat", "mahsup", "realize"),
        "fn:kar_gerceklesme_ui.kar_gerceklesme_raporu_goster",
        ("satis_goruntuleme", "finans_goruntuleme", "goruntuleme"),
    ),
    (
        "finans.banka_transfer",
        "Banka Transfer ve Virman İşlemleri",
        "Finans › Banka İşlemleri › Banka Transfer ve Virman İşlemleri",
        ("virman", "eft", "fast", "havale", "transfer"),
        "fn:finans_ui.bankalar_arasi_virman_sayfasi_goster",
        ("finans_goruntuleme", "goruntuleme"),
    ),
    (
        "stok.konsinye",
        "Konsinye Takibi",
        "Stoklar › Konsinye Takibi",
        ("konsinye", "konsinyasyon", "müşteride mal", "tedarikçi malı"),
        "fn:konsinye_ui.konsinye_takibi_goster",
        ("stok_goruntuleme", "goruntuleme"),
    ),
    (
        "stok.yerine_koyma",
        "Yerine Koyma Maliyeti / Stok Yatırım Verimliliği",
        "Raporlar › Stok Raporları › Stok Yatırım Verimliliği",
        ("yerine koyma", "yenileme maliyeti", "tedarik maliyeti", "gmroi", "ürün fiyat değişimi"),
        "fn:stok_raporlari_ui.yatirim_verimliligi_goster",
        ("stok_goruntuleme", "goruntuleme"),
    ),
)


def _acici_coz(tip: str) -> Callable[[Any], None]:
    if tip.startswith("sayfa:"):
        anahtar = tip.split(":", 1)[1]

        def _fn(app, a=anahtar):
            app.sayfa_goster(a, ust_duzey=True)

        return _fn
    if tip.startswith("alt:"):
        metot = tip.split(":", 1)[1]

        def _fn(app, m=metot):
            kabuk = getattr(app, "_ana_panel_kabuk", None)
            if kabuk is not None and hasattr(kabuk, "alt_menu_ac"):
                kabuk.alt_menu_ac(m)
            elif hasattr(app, m):
                getattr(app, m)()

        return _fn
    if tip.startswith("fn:"):
        yol = tip.split(":", 1)[1]
        mod, ad = yol.rsplit(".", 1)

        def _fn(app, modul=mod, fname=ad):
            import importlib

            m = importlib.import_module(modul)
            getattr(m, fname)(app)

        return _fn
    raise ValueError(f"Bilinmeyen açıcı: {tip}")


def menu_envanteri(app=None) -> list[dict]:
    """Yetkiye göre süzülmüş menü kayıtları."""
    from ana_panel_ui import MENU_ALT_OGELERI, MENU_OGELERI

    kayitlar: list[dict] = []
    for etiket, anahtar, _simge, _v in MENU_OGELERI:
        yetkiler = ()
        if anahtar in ("sistem",):
            yetkiler = ("kullanici_yonetme", "firma_yonetme", "sistem_ayarlari")
        kayitlar.append(
            {
                "id": f"ana.{anahtar}",
                "ad": etiket,
                "yol": etiket,
                "es": (),
                "ac": _acici_coz(f"sayfa:{anahtar}"),
                "yetki": yetkiler,
            }
        )
        for alt_etiket, alt_anahtar, alt_yetki in MENU_ALT_OGELERI.get(anahtar, ()):
            kayitlar.append(
                {
                    "id": f"alt.{anahtar}.{alt_anahtar}",
                    "ad": alt_etiket,
                    "yol": f"{etiket} › {alt_etiket}",
                    "es": (),
                    "ac": _acici_coz(f"alt:{alt_anahtar}"),
                    "yetki": alt_yetki,
                }
            )
    for mid, ad, yol, es, tip, yetki in EK_MENU_KAYITLARI:
        kayitlar.append(
            {
                "id": mid,
                "ad": ad,
                "yol": yol,
                "es": es,
                "ac": _acici_coz(tip),
                "yetki": yetki,
            }
        )
    sonuc = []
    for k in kayitlar:
        yetki = k.get("yetki") or ()
        if yetki and not _yetki_var(*yetki):
            continue
        sonuc.append(k)
    return sonuc


def _eslesme_skoru(kayit: dict, sorgu: str) -> int | None:
    """Düşük skor = daha iyi. Eşleşme yoksa None."""
    q = turkce_normalize(sorgu)
    if not q:
        return None
    kelimeler = [k for k in q.split() if k]
    if not kelimeler:
        return None
    ad = turkce_normalize(kayit["ad"])
    yol = turkce_normalize(kayit["yol"])
    es = " ".join(turkce_normalize(x) for x in (kayit.get("es") or ()))
    havuz = f"{ad} {yol} {es}"
    if not all(k in havuz for k in kelimeler):
        return None
    if ad == q:
        return 0
    if ad.startswith(q):
        return 1
    if any(ad.startswith(k) or f" {k}" in f" {ad}" for k in kelimeler):
        return 2
    if all(k in ad for k in kelimeler):
        return 3
    if any(k in es for k in kelimeler):
        return 4
    return 5


def menu_ara(sorgu: str, kayitlar: list[dict] | None = None, limit: int = 40) -> list[dict]:
    kayitlar = kayitlar if kayitlar is not None else menu_envanteri()
    q = (sorgu or "").strip()
    if not q:
        return kayitlar[: min(12, len(kayitlar))]
    adaylar = []
    for k in kayitlar:
        skor = _eslesme_skoru(k, q)
        if skor is None:
            continue
        adaylar.append((skor, k["ad"].lower(), k))
    adaylar.sort(key=lambda x: (x[0], x[1]))
    return [a[2] for a in adaylar[:limit]]


class MenuAramaCubugu:
    """Üst çubukta Menü ara alanı + sonuç paneli."""

    def __init__(self, parent, app):
        self.app = app
        self._kayitlar: list[dict] = []
        self._sonuclar: list[dict] = []
        self._after = None
        self._panel = None

        self.cerceve = tk.Frame(parent, bg=parent.cget("bg") if parent.cget("bg") else "#FFFFFF")
        tk.Label(
            self.cerceve, text="Menü ara", bg=self.cerceve["bg"], fg="#555", font=("Segoe UI", 8)
        ).pack(anchor="w")
        satir = tk.Frame(self.cerceve, bg=self.cerceve["bg"])
        satir.pack(fill="x")
        self.entry = ttk.Entry(satir, width=28)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.insert(0, "")
        self.entry.bind("<KeyRelease>", self._yazildi)
        self.entry.bind("<Down>", self._asagi)
        self.entry.bind("<Up>", self._yukari)
        self.entry.bind("<Return>", self._enter)
        self.entry.bind("<Escape>", self._kapat)
        self.entry.bind("<FocusIn>", lambda _e: self._yenile_dizin())

        try:
            app.bind_all("<Control-k>", self._kisayol)
            app.bind_all("<Control-K>", self._kisayol)
        except tk.TclError:
            pass

    def pack(self, **kw):
        self.cerceve.pack(**kw)

    def odaklan(self):
        self._yenile_dizin()
        self.entry.focus_set()
        self.entry.selection_range(0, "end")
        self._goster_sonuclar(self.entry.get())

    def _kisayol(self, _event=None):
        self.odaklan()
        return "break"

    def _yenile_dizin(self):
        self._kayitlar = menu_envanteri(self.app)

    def _yazildi(self, _event=None):
        if self._after:
            try:
                self.app.after_cancel(self._after)
            except Exception:
                pass
        self._after = self.app.after(150, lambda: self._goster_sonuclar(self.entry.get()))

    def _goster_sonuclar(self, sorgu: str):
        self._sonuclar = menu_ara(sorgu, self._kayitlar)
        if self._panel is not None:
            try:
                self._panel.destroy()
            except tk.TclError:
                pass
            self._panel = None
        if not self.entry.winfo_viewable():
            return
        self._panel = tk.Toplevel(self.app)
        self._panel.overrideredirect(True)
        self._panel.attributes("-topmost", True)
        self._panel.configure(bg="#FFFFFF", highlightthickness=1, highlightbackground="#1a3a6b")
        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() + self.entry.winfo_height() + 2
        self._panel.geometry(f"420x280+{x}+{y}")
        lb = tk.Listbox(
            self._panel,
            font=("Segoe UI", 9),
            activestyle="dotbox",
            selectmode="browse",
            bg="#FFFFFF",
            fg="#1a1a1a",
            highlightthickness=0,
            bd=0,
        )
        lb.pack(fill="both", expand=True, padx=2, pady=2)
        self._listbox = lb
        if not self._sonuclar:
            lb.insert("end", f"Sonuç bulunamadı: {sorgu.strip() or '—'}")
            lb.configure(state="disabled")
            return
        for k in self._sonuclar:
            lb.insert("end", f"{k['ad']}  —  {k['yol']}")
        lb.selection_set(0)
        lb.bind("<Double-Button-1>", self._enter)
        lb.bind("<Return>", self._enter)

    def _asagi(self, _e=None):
        lb = getattr(self, "_listbox", None)
        if not lb or not self._sonuclar:
            return "break"
        i = lb.curselection()
        n = (i[0] + 1) if i else 0
        if n >= len(self._sonuclar):
            n = 0
        lb.selection_clear(0, "end")
        lb.selection_set(n)
        lb.see(n)
        return "break"

    def _yukari(self, _e=None):
        lb = getattr(self, "_listbox", None)
        if not lb or not self._sonuclar:
            return "break"
        i = lb.curselection()
        n = (i[0] - 1) if i else len(self._sonuclar) - 1
        if n < 0:
            n = len(self._sonuclar) - 1
        lb.selection_clear(0, "end")
        lb.selection_set(n)
        lb.see(n)
        return "break"

    def _enter(self, _e=None):
        lb = getattr(self, "_listbox", None)
        if not lb or not self._sonuclar:
            self._kapat()
            return "break"
        i = lb.curselection()
        idx = i[0] if i else 0
        if idx >= len(self._sonuclar):
            return "break"
        kayit = self._sonuclar[idx]
        self._kapat()
        try:
            kayit["ac"](self.app)
        except Exception as hata:
            from tkinter import messagebox

            messagebox.showerror("Menü", str(hata), parent=self.app)
        return "break"

    def _kapat(self, _e=None):
        if self._panel is not None:
            try:
                self._panel.destroy()
            except tk.TclError:
                pass
            self._panel = None
        return "break"
