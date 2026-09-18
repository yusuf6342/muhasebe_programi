"""Stok kartları listesi: kolon ayarları, gelişmiş filtre, tipografi yardımcıları."""

from __future__ import annotations

import json
import os
import tkinter as tk
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from database.access import maliyet_izinli
from database.session_manager import oturum
from satis_tema import BEYAZ, LACIVERT, LACIVERT_HOVER, METIN, ACIK_SARI, KOYU_LACIVERT, font

EKRAN_KODU = "stok_kartlari_listesi"

# anahtar, baslik, varsayilan_genislik, varsayilan_gorunur
STOK_LISTE_KOLONLARI = (
    ("kod", "Stok Kodu", 120, True),
    ("ad", "Stok Adı", 260, True),
    ("barkod", "Barkod", 130, True),
    ("birim", "Birim", 70, True),
    ("kdv", "KDV %", 70, True),
    ("alis", "Alış Fiyatı", 110, True),
    ("satis1", "Satış Fiyatı 1", 110, True),
    ("satis2", "Satış Fiyatı 2", 110, False),
    ("satis3", "Satış Fiyatı 3", 110, False),
    ("satis4", "Satış Fiyatı 4", 110, False),
    ("miktar", "Toplam Mevcut", 110, True),
    ("tur", "Kart Türü", 110, False),
    ("grup", "Stok Grubu (Yol)", 160, True),
    ("ana_grup", "Ana Grup", 120, False),
    ("tali_grup", "Tali Grup", 120, False),
    ("alt_grup", "Alt Grup", 120, False),
    ("aktif", "Aktiflik", 80, False),
)

STOK_LISTE_SAG = frozenset({"alis", "satis1", "satis2", "satis3", "satis4", "miktar"})
STOK_LISTE_ORTA = frozenset({"kdv", "birim", "aktif"})
STOK_LISTE_ZORUNLU = frozenset({"ad"})  # tamamen kapatılamaz
STOK_LISTE_SAYISAL = frozenset({"alis", "satis1", "satis2", "satis3", "satis4", "miktar", "kdv"})

_STRIPE = "#E4EBF3"


def para_goster_bos(tutar) -> str:
    """None → tire; 0 → 0,00 TL; diğer → para biçimi."""
    if tutar is None:
        return "—"
    try:
        d = Decimal(str(tutar))
    except (InvalidOperation, ValueError, TypeError):
        return "—"
    return f"{float(d):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def miktar_goster(miktar) -> str:
    if miktar is None:
        return "0"
    try:
        d = Decimal(str(miktar))
    except (InvalidOperation, ValueError, TypeError):
        return "0"
    metin = f"{d:,.4f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", ".")
    return metin or "0"


def stok_liste_varsayilan_ayarlari() -> dict:
    sira = [k for k, _, _, _ in STOK_LISTE_KOLONLARI]
    kolonlar = {
        anahtar: {
            "baslik": baslik,
            "genislik": genislik,
            "gorunur": gorunur,
        }
        for anahtar, baslik, genislik, gorunur in STOK_LISTE_KOLONLARI
    }
    return {"sira": sira, "kolonlar": kolonlar, "profil": "Standart"}


def _ayar_kimlik() -> tuple[str, str]:
    firma = str(oturum.company_id or oturum.firma_kodu or "0")
    kullanici = str(oturum.user_id or oturum.kullanici_adi or "0")
    return firma, kullanici


def stok_liste_ayar_dosyasi() -> Path:
    firma, kullanici = _ayar_kimlik()
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MuhasebeProgrami" / "ayarlar"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"stok_liste_kolon_{firma}_{kullanici}.json"


def stok_liste_ayarlari_yukle() -> dict:
    varsayilan = stok_liste_varsayilan_ayarlari()
    yol = stok_liste_ayar_dosyasi()
    if not yol.exists():
        return deepcopy(varsayilan)
    try:
        kayit = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return deepcopy(varsayilan)

    bilinen = {k for k, _, _, _ in STOK_LISTE_KOLONLARI}
    sira = [k for k in (kayit.get("sira") or []) if k in bilinen]
    for k, _, _, _ in STOK_LISTE_KOLONLARI:
        if k not in sira:
            sira.append(k)

    kolonlar = {}
    gelen_kol = kayit.get("kolonlar") or {}
    for anahtar, baslik, genislik, gorunur in STOK_LISTE_KOLONLARI:
        gelen = gelen_kol.get(anahtar) or {}
        try:
            w = int(gelen.get("genislik", genislik))
        except (TypeError, ValueError):
            w = genislik
        g = bool(gelen.get("gorunur", gorunur))
        if anahtar in STOK_LISTE_ZORUNLU:
            g = True
        if anahtar == "alis" and not maliyet_izinli():
            g = False
        kolonlar[anahtar] = {
            "baslik": baslik,
            "genislik": max(40, min(w, 600)),
            "gorunur": g,
        }
    return {
        "sira": sira,
        "kolonlar": kolonlar,
        "profil": kayit.get("profil") or "Standart",
    }


def stok_liste_ayarlari_kaydet(ayarlar: dict) -> None:
    bilinen = {k for k, _, _, _ in STOK_LISTE_KOLONLARI}
    sira = [k for k in (ayarlar.get("sira") or []) if k in bilinen]
    for k, _, _, _ in STOK_LISTE_KOLONLARI:
        if k not in sira:
            sira.append(k)
    temiz_kol = {}
    for anahtar, baslik, genislik, gorunur in STOK_LISTE_KOLONLARI:
        cfg = (ayarlar.get("kolonlar") or {}).get(anahtar) or {}
        g = bool(cfg.get("gorunur", gorunur))
        if anahtar in STOK_LISTE_ZORUNLU:
            g = True
        try:
            w = int(cfg.get("genislik", genislik))
        except (TypeError, ValueError):
            w = genislik
        temiz_kol[anahtar] = {"genislik": max(40, min(w, 600)), "gorunur": g}
    yol = stok_liste_ayar_dosyasi()
    yol.write_text(
        json.dumps(
            {
                "ekran": EKRAN_KODU,
                "firma_id": _ayar_kimlik()[0],
                "kullanici_id": _ayar_kimlik()[1],
                "sira": sira,
                "kolonlar": temiz_kol,
                "profil": ayarlar.get("profil") or "Standart",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def stok_liste_treeview_stil(tablo: ttk.Treeview, root: tk.Misc | None = None) -> None:
    stil = ttk.Style(root)
    try:
        if "clam" in stil.theme_names():
            stil.theme_use("clam")
    except tk.TclError:
        pass
    f_govde = font(11, root=root)
    f_baslik = font(11, "bold", root=root)
    stil.configure(
        "StokListe.Treeview",
        font=f_govde,
        rowheight=32,
        fieldbackground=BEYAZ,
        background=BEYAZ,
        foreground=METIN,
        borderwidth=1,
        relief="solid",
    )
    stil.configure(
        "StokListe.Treeview.Heading",
        font=f_baslik,
        background=LACIVERT,
        foreground=BEYAZ,
        relief="flat",
        borderwidth=0,
        padding=(8, 8),
    )
    stil.map(
        "StokListe.Treeview",
        background=[("selected", ACIK_SARI)],
        foreground=[("selected", KOYU_LACIVERT)],
    )
    stil.map(
        "StokListe.Treeview.Heading",
        background=[("active", LACIVERT_HOVER), ("pressed", LACIVERT_HOVER)],
        foreground=[("active", BEYAZ), ("pressed", BEYAZ)],
    )
    tablo.configure(style="StokListe.Treeview")
    tablo.tag_configure("tek", background=BEYAZ)
    tablo.tag_configure("cift", background=_STRIPE)
    tablo.tag_configure("pasif", foreground="#627D98")


def kolon_anchor(anahtar: str) -> str:
    if anahtar in STOK_LISTE_SAG:
        return "e"
    if anahtar in STOK_LISTE_ORTA:
        return "center"
    return "w"


def aktif_filtre_sayisi(filtre: dict | None) -> int:
    if not filtre:
        return 0
    sayac = 0
    for anahtar, deger in filtre.items():
        if anahtar.endswith("_bos_dahil"):
            continue
        if deger is None or deger == "" or deger == [] or deger == ():
            continue
        if anahtar in ("stok_durumu", "aktiflik") and str(deger).lower() in ("tumu", "tümü", ""):
            continue
        if isinstance(deger, bool):
            continue
        sayac += 1
    return sayac


class StokKolonAyarDialog(tk.Toplevel):
    """Kolon göster/gizle, sıra ve genişlik."""

    def __init__(self, parent, ayarlar: dict, on_uygula: Callable[[dict], None]):
        super().__init__(parent)
        self.title("Stok Listesi — Kolon Ayarları")
        self.geometry("560x560")
        self.minsize(480, 420)
        self.transient(parent)
        self.grab_set()
        self.on_uygula = on_uygula
        self.ayarlar = deepcopy(ayarlar or stok_liste_varsayilan_ayarlari())
        self._sira = list(self.ayarlar.get("sira") or [k for k, _, _, _ in STOK_LISTE_KOLONLARI])
        self._satirlar: dict[str, tuple[tk.BooleanVar, tk.IntVar]] = {}

        ttk.Label(
            self,
            text="Kolon görünürlüğü, sırası ve genişliği. Stok Adı kapatılamaz.",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=12, pady=(12, 6))

        ust = ttk.Frame(self)
        ust.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Button(ust, text="Varsayılana Dön", command=self._varsayilan).pack(side="left")
        if not maliyet_izinli():
            ttk.Label(ust, text="Alış fiyatı yetkiniz yok — kolon gizlenir.", foreground="#9B1C1C").pack(
                side="left", padx=10
            )

        govde = ttk.Frame(self, padding=8)
        govde.pack(fill="both", expand=True, padx=8)
        sol = ttk.Frame(govde)
        sol.pack(side="left", fill="both", expand=True)
        sag = ttk.Frame(govde)
        sag.pack(side="right", fill="y", padx=(8, 0))

        self.liste = tk.Listbox(sol, height=18, activestyle="dotbox", exportselection=False)
        self.liste.pack(side="left", fill="both", expand=True)
        kaydir = ttk.Scrollbar(sol, orient="vertical", command=self.liste.yview)
        self.liste.configure(yscrollcommand=kaydir.set)
        kaydir.pack(side="right", fill="y")
        self.liste.bind("<<ListboxSelect>>", self._satir_secildi)

        ttk.Button(sag, text="Yukarı", command=self._yukari).pack(fill="x", pady=2)
        ttk.Button(sag, text="Aşağı", command=self._asagi).pack(fill="x", pady=2)

        form = ttk.LabelFrame(self, text="Seçili kolon", padding=10)
        form.pack(fill="x", padx=12, pady=6)
        self._gorunur_var = tk.BooleanVar(value=True)
        self._genislik_var = tk.IntVar(value=120)
        self._secili_lbl = ttk.Label(form, text="—")
        self._secili_lbl.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Checkbutton(form, text="Göster", variable=self._gorunur_var, command=self._formdan_yaz).grid(
            row=1, column=0, sticky="w"
        )
        ttk.Label(form, text="Genişlik (px)").grid(row=2, column=0, sticky="w", pady=4)
        spin = ttk.Spinbox(
            form, from_=40, to=600, textvariable=self._genislik_var, width=8, command=self._formdan_yaz
        )
        spin.grid(row=2, column=1, sticky="w")
        spin.bind("<FocusOut>", lambda _e: self._formdan_yaz())
        self._secili_anahtar = None

        alt = ttk.Frame(self, padding=12)
        alt.pack(fill="x")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right", padx=8)
        ttk.Button(alt, text="Uygula", command=self._uygula).pack(side="right")

        self._listeyi_doldur()
        if self._sira:
            self.liste.selection_set(0)
            self._satir_secildi()

    def _baslik(self, anahtar: str) -> str:
        return (self.ayarlar.get("kolonlar") or {}).get(anahtar, {}).get("baslik") or anahtar

    def _listeyi_doldur(self):
        self.liste.delete(0, "end")
        for anahtar in self._sira:
            cfg = (self.ayarlar.get("kolonlar") or {}).get(anahtar) or {}
            isaret = "✓" if cfg.get("gorunur", True) else "·"
            self.liste.insert("end", f"{isaret}  {self._baslik(anahtar)}  ({cfg.get('genislik', 100)}px)")

    def _satir_secildi(self, _e=None):
        secim = self.liste.curselection()
        if not secim:
            return
        if self._secili_anahtar:
            self._formdan_yaz()
        anahtar = self._sira[secim[0]]
        self._secili_anahtar = anahtar
        cfg = (self.ayarlar.get("kolonlar") or {}).get(anahtar) or {}
        self._secili_lbl.configure(text=self._baslik(anahtar))
        self._gorunur_var.set(bool(cfg.get("gorunur", True)))
        self._genislik_var.set(int(cfg.get("genislik", 100)))
        # Zorunlu / yetki
        durum = "normal"
        if anahtar in STOK_LISTE_ZORUNLU or (anahtar == "alis" and not maliyet_izinli()):
            if anahtar in STOK_LISTE_ZORUNLU:
                self._gorunur_var.set(True)
            if anahtar == "alis" and not maliyet_izinli():
                self._gorunur_var.set(False)
                durum = "disabled"
            elif anahtar in STOK_LISTE_ZORUNLU:
                durum = "disabled"

    def _formdan_yaz(self):
        anahtar = self._secili_anahtar
        if not anahtar:
            return
        kolonlar = self.ayarlar.setdefault("kolonlar", {})
        cfg = kolonlar.setdefault(anahtar, {"baslik": self._baslik(anahtar), "genislik": 100, "gorunur": True})
        g = bool(self._gorunur_var.get())
        if anahtar in STOK_LISTE_ZORUNLU:
            g = True
        if anahtar == "alis" and not maliyet_izinli():
            g = False
        try:
            w = int(self._genislik_var.get())
        except (tk.TclError, ValueError, TypeError):
            w = cfg.get("genislik", 100)
        cfg["gorunur"] = g
        cfg["genislik"] = max(40, min(w, 600))
        self.ayarlar["sira"] = list(self._sira)
        # Listeyi yenile, seçimi koru
        idx = self._sira.index(anahtar)
        self._listeyi_doldur()
        self.liste.selection_set(idx)

    def _yukari(self):
        secim = self.liste.curselection()
        if not secim or secim[0] == 0:
            return
        self._formdan_yaz()
        i = secim[0]
        self._sira[i - 1], self._sira[i] = self._sira[i], self._sira[i - 1]
        self.ayarlar["sira"] = list(self._sira)
        self._listeyi_doldur()
        self.liste.selection_set(i - 1)
        self._satir_secildi()

    def _asagi(self):
        secim = self.liste.curselection()
        if not secim or secim[0] >= len(self._sira) - 1:
            return
        self._formdan_yaz()
        i = secim[0]
        self._sira[i + 1], self._sira[i] = self._sira[i], self._sira[i + 1]
        self.ayarlar["sira"] = list(self._sira)
        self._listeyi_doldur()
        self.liste.selection_set(i + 1)
        self._satir_secildi()

    def _varsayilan(self):
        self.ayarlar = stok_liste_varsayilan_ayarlari()
        if not maliyet_izinli():
            self.ayarlar["kolonlar"]["alis"]["gorunur"] = False
        self._sira = list(self.ayarlar["sira"])
        self._secili_anahtar = None
        self._listeyi_doldur()
        self.liste.selection_set(0)
        self._satir_secildi()

    def _mevcut(self) -> dict:
        self._formdan_yaz()
        self.ayarlar["sira"] = list(self._sira)
        return deepcopy(self.ayarlar)

    def _uygula(self):
        ayar = self._mevcut()
        gorunen = [
            k
            for k in ayar["sira"]
            if (ayar["kolonlar"].get(k) or {}).get("gorunur", True)
            and not (k == "alis" and not maliyet_izinli())
        ]
        if "ad" not in gorunen:
            messagebox.showwarning("Kolon", "Stok Adı kolonu görünür olmalıdır.", parent=self)
            return
        if not gorunen:
            messagebox.showwarning("Kolon", "En az bir kolon görünür olmalı.", parent=self)
            return
        if self.on_uygula:
            self.on_uygula(ayar)

    def _kaydet(self):
        self._uygula()
        stok_liste_ayarlari_kaydet(self.ayarlar)
        messagebox.showinfo("Kolon", "Kolon ayarları bu kullanıcı/firma için kaydedildi.", parent=self)


class StokFiltreDialog(tk.Toplevel):
    """Gelişmiş stok listesi filtreleri (VE mantığı)."""

    def __init__(
        self,
        parent,
        mevcut: dict | None,
        *,
        gruplar: list[str],
        kart_turleri: list[str],
        birimler: list[str],
        kdv_oranlari: list[str],
        depolar: list[str],
        on_uygula: Callable[[dict], None],
    ):
        super().__init__(parent)
        self.title("Stok Listesi — Filtreler")
        self.geometry("520x640")
        self.minsize(460, 520)
        self.transient(parent)
        self.grab_set()
        self.on_uygula = on_uygula
        self.result = None
        f = dict(mevcut or {})

        canvas = tk.Canvas(self, highlightthickness=0)
        kaydir = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        ic = ttk.Frame(canvas)
        ic.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=ic, anchor="nw")
        canvas.configure(yscrollcommand=kaydir.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=12)
        kaydir.pack(side="right", fill="y", pady=12, padx=(0, 8))

        r = 0
        ttk.Label(ic, text="Stok adı / kod / barkod", font=("Segoe UI", 9, "bold")).grid(
            row=r, column=0, sticky="w"
        )
        r += 1
        self.metin = ttk.Entry(ic, width=42)
        self.metin.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        self.metin.insert(0, f.get("metin") or "")
        r += 1

        # Kademeli stok grubu filtreleri
        ttk.Label(ic, text="Ana / Tali / Alt Grup", font=("Segoe UI", 9, "bold")).grid(
            row=r, column=0, sticky="w"
        )
        r += 1
        grup_satir = ttk.Frame(ic)
        grup_satir.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(2, 8))
        self._ana_map: dict[str, int] = {}
        self._tali_map: dict[str, int] = {}
        self._alt_map: dict[str, int] = {}
        self.ana_cb = ttk.Combobox(grup_satir, width=18)
        self.tali_cb = ttk.Combobox(grup_satir, width=18, state="disabled")
        self.alt_cb = ttk.Combobox(grup_satir, width=18, state="disabled")
        self.ana_cb.pack(side="left", padx=(0, 4))
        self.tali_cb.pack(side="left", padx=(0, 4))
        self.alt_cb.pack(side="left")
        try:
            from database.stok_grup_service import SEVIYE_ANA, SEVIYE_TALI, SEVIYE_ALT, StokGrupService

            for g in StokGrupService.listele(seviye=SEVIYE_ANA, aktif_only=True):
                et = g.get("etiket") or g.get("ad")
                self._ana_map[et] = g["id"]
            self.ana_cb.configure(values=["(Tümü)"] + list(self._ana_map.keys()))
            self.ana_cb.set("(Tümü)")
            if f.get("ana_grup_id"):
                for et, gid in self._ana_map.items():
                    if gid == f["ana_grup_id"]:
                        self.ana_cb.set(et)
                        break

            def _ana_ch(_e=None):
                self._tali_map.clear()
                self._alt_map.clear()
                self.tali_cb.set("")
                self.alt_cb.set("")
                et = self.ana_cb.get()
                aid = self._ana_map.get(et)
                if not aid:
                    self.tali_cb.configure(values=[], state="disabled")
                    self.alt_cb.configure(values=[], state="disabled")
                    return
                for g in StokGrupService.listele(
                    seviye=SEVIYE_TALI, parent_id=aid, aktif_only=True
                ):
                    e2 = g.get("etiket") or g.get("ad")
                    self._tali_map[e2] = g["id"]
                self.tali_cb.configure(
                    values=["(Tümü)"] + list(self._tali_map.keys()), state="readonly"
                )
                self.tali_cb.set("(Tümü)")
                self.alt_cb.configure(values=[], state="disabled")

            def _tali_ch(_e=None):
                self._alt_map.clear()
                self.alt_cb.set("")
                tid = self._tali_map.get(self.tali_cb.get())
                if not tid:
                    self.alt_cb.configure(values=[], state="disabled")
                    return
                for g in StokGrupService.listele(
                    seviye=SEVIYE_ALT, parent_id=tid, aktif_only=True
                ):
                    e2 = g.get("etiket") or g.get("ad")
                    self._alt_map[e2] = g["id"]
                self.alt_cb.configure(
                    values=["(Tümü)"] + list(self._alt_map.keys()), state="readonly"
                )
                self.alt_cb.set("(Tümü)")

            self.ana_cb.bind("<<ComboboxSelected>>", _ana_ch)
            self.tali_cb.bind("<<ComboboxSelected>>", _tali_ch)
            if f.get("ana_grup_id"):
                _ana_ch()
                if f.get("tali_grup_id"):
                    for et, gid in self._tali_map.items():
                        if gid == f["tali_grup_id"]:
                            self.tali_cb.set(et)
                            break
                    _tali_ch()
                    if f.get("alt_grup_id"):
                        for et, gid in self._alt_map.items():
                            if gid == f["alt_grup_id"]:
                                self.alt_cb.set(et)
                                break
        except Exception:
            pass
        r += 1

        def _listbox(etiket, degerler, secilen, yukseklik=5):
            nonlocal r
            ttk.Label(ic, text=etiket, font=("Segoe UI", 9, "bold")).grid(row=r, column=0, sticky="w")
            r += 1
            cer = ttk.Frame(ic)
            cer.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(2, 8))
            lb = tk.Listbox(cer, selectmode="extended", height=yukseklik, exportselection=False)
            sb = ttk.Scrollbar(cer, orient="vertical", command=lb.yview)
            lb.configure(yscrollcommand=sb.set)
            lb.pack(side="left", fill="x", expand=True)
            sb.pack(side="right", fill="y")
            for d in degerler:
                lb.insert("end", d)
            sec_set = {str(x) for x in (secilen or [])}
            for i, d in enumerate(degerler):
                if str(d) in sec_set:
                    lb.selection_set(i)
            r += 1
            return lb

        self.grup_lb = _listbox("Stok grubu yolu (eski/çoklu)", gruplar, f.get("gruplar"))
        self.tur_lb = _listbox("Kart türü (çoklu)", kart_turleri, f.get("kart_turleri"), 4)
        self.birim_lb = _listbox("Birim (çoklu)", birimler, f.get("birimler"), 4)
        self.kdv_lb = _listbox("KDV oranı (çoklu)", kdv_oranlari, f.get("kdv_oranlari"), 4)
        self.depo_lb = _listbox("Depo (çoklu)", depolar, f.get("depolar"), 4)

        def _aralik(etiket, min_key, max_key, bos_key):
            nonlocal r
            ttk.Label(ic, text=etiket, font=("Segoe UI", 9, "bold")).grid(row=r, column=0, sticky="w")
            r += 1
            satir = ttk.Frame(ic)
            satir.grid(row=r, column=0, columnspan=2, sticky="w", pady=(2, 4))
            ttk.Label(satir, text="Min").pack(side="left")
            min_e = ttk.Entry(satir, width=12)
            min_e.pack(side="left", padx=4)
            if f.get(min_key) not in (None, ""):
                min_e.insert(0, str(f.get(min_key)).replace(".", ","))
            ttk.Label(satir, text="Maks").pack(side="left", padx=(8, 0))
            max_e = ttk.Entry(satir, width=12)
            max_e.pack(side="left", padx=4)
            if f.get(max_key) not in (None, ""):
                max_e.insert(0, str(f.get(max_key)).replace(".", ","))
            r += 1
            bos_var = tk.BooleanVar(value=bool(f.get(bos_key, False)))
            ttk.Checkbutton(ic, text="Boş fiyatları dahil et", variable=bos_var).grid(
                row=r, column=0, sticky="w", pady=(0, 8)
            )
            r += 1
            return min_e, max_e, bos_var

        self.alis_min, self.alis_max, self.alis_bos = _aralik(
            "Alış fiyatı", "alis_min", "alis_max", "alis_bos_dahil"
        )
        if not maliyet_izinli():
            for w in (self.alis_min, self.alis_max):
                w.configure(state="disabled")
        self.satis_min, self.satis_max, self.satis_bos = _aralik(
            "Satış fiyatı 1", "satis1_min", "satis1_max", "satis1_bos_dahil"
        )

        ttk.Label(ic, text="Mevcut miktar", font=("Segoe UI", 9, "bold")).grid(row=r, column=0, sticky="w")
        r += 1
        miktar_satir = ttk.Frame(ic)
        miktar_satir.grid(row=r, column=0, columnspan=2, sticky="w", pady=(2, 8))
        ttk.Label(miktar_satir, text="Min").pack(side="left")
        self.miktar_min = ttk.Entry(miktar_satir, width=12)
        self.miktar_min.pack(side="left", padx=4)
        if f.get("miktar_min") not in (None, ""):
            self.miktar_min.insert(0, str(f.get("miktar_min")).replace(".", ","))
        ttk.Label(miktar_satir, text="Maks").pack(side="left", padx=(8, 0))
        self.miktar_max = ttk.Entry(miktar_satir, width=12)
        self.miktar_max.pack(side="left", padx=4)
        if f.get("miktar_max") not in (None, ""):
            self.miktar_max.insert(0, str(f.get("miktar_max")).replace(".", ","))
        r += 1

        ttk.Label(ic, text="Stok durumu", font=("Segoe UI", 9, "bold")).grid(row=r, column=0, sticky="w")
        r += 1
        self.stok_durumu = ttk.Combobox(
            ic,
            values=("Tümü", "Stokta var", "Sıfır stok", "Eksi stok"),
            state="readonly",
            width=24,
        )
        durum_map = {
            "tumu": "Tümü",
            "var": "Stokta var",
            "sifir": "Sıfır stok",
            "eksi": "Eksi stok",
        }
        self.stok_durumu.set(durum_map.get(str(f.get("stok_durumu") or "tumu").lower(), "Tümü"))
        self.stok_durumu.grid(row=r, column=0, sticky="w", pady=(2, 8))
        r += 1

        ttk.Label(ic, text="Aktiflik", font=("Segoe UI", 9, "bold")).grid(row=r, column=0, sticky="w")
        r += 1
        self.aktiflik = ttk.Combobox(
            ic, values=("Aktif", "Pasif", "Tümü"), state="readonly", width=24
        )
        aktif_map = {"aktif": "Aktif", "pasif": "Pasif", "tumu": "Tümü"}
        self.aktiflik.set(aktif_map.get(str(f.get("aktiflik") or "aktif").lower(), "Aktif"))
        self.aktiflik.grid(row=r, column=0, sticky="w", pady=(2, 8))

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x", side="bottom")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Uygula", command=self._uygula).pack(side="right", padx=8)
        ttk.Button(alt, text="Temizle", command=self._temizle).pack(side="left")

    @staticmethod
    def _lb_secimler(lb: tk.Listbox) -> list[str]:
        return [lb.get(i) for i in lb.curselection()]

    @staticmethod
    def _sayi_oku(widget) -> Decimal | None:
        metin = (widget.get() or "").strip().replace(" ", "").replace(".", "").replace(",", ".")
        # TR: 1.234,56 → remove thousands carefully
        ham = (widget.get() or "").strip().replace(" ", "")
        if not ham:
            return None
        if "," in ham and "." in ham:
            ham = ham.replace(".", "").replace(",", ".")
        elif "," in ham:
            ham = ham.replace(",", ".")
        try:
            return Decimal(ham)
        except (InvalidOperation, ValueError):
            raise ValueError(f"Geçersiz sayı: {widget.get()}")

    def _topla(self) -> dict:
        durum_rev = {
            "Tümü": "tumu",
            "Stokta var": "var",
            "Sıfır stok": "sifir",
            "Eksi stok": "eksi",
        }
        aktif_rev = {"Aktif": "aktif", "Pasif": "pasif", "Tümü": "tumu"}
        filtre = {
            "metin": (self.metin.get() or "").strip(),
            "gruplar": self._lb_secimler(self.grup_lb),
            "ana_grup_id": getattr(self, "_ana_map", {}).get(self.ana_cb.get())
            if hasattr(self, "ana_cb")
            else None,
            "tali_grup_id": getattr(self, "_tali_map", {}).get(self.tali_cb.get())
            if hasattr(self, "tali_cb")
            else None,
            "alt_grup_id": getattr(self, "_alt_map", {}).get(self.alt_cb.get())
            if hasattr(self, "alt_cb")
            else None,
            "kart_turleri": self._lb_secimler(self.tur_lb),
            "birimler": self._lb_secimler(self.birim_lb),
            "kdv_oranlari": self._lb_secimler(self.kdv_lb),
            "depolar": self._lb_secimler(self.depo_lb),
            "alis_min": self._sayi_oku(self.alis_min) if maliyet_izinli() else None,
            "alis_max": self._sayi_oku(self.alis_max) if maliyet_izinli() else None,
            "alis_bos_dahil": bool(self.alis_bos.get()) if maliyet_izinli() else False,
            "satis1_min": self._sayi_oku(self.satis_min),
            "satis1_max": self._sayi_oku(self.satis_max),
            "satis1_bos_dahil": bool(self.satis_bos.get()),
            "miktar_min": self._sayi_oku(self.miktar_min),
            "miktar_max": self._sayi_oku(self.miktar_max),
            "stok_durumu": durum_rev.get(self.stok_durumu.get(), "tumu"),
            "aktiflik": aktif_rev.get(self.aktiflik.get(), "aktif"),
        }
        return filtre

    def _temizle(self):
        self.result = {}
        if self.on_uygula:
            self.on_uygula({})
        self.destroy()

    def _uygula(self):
        try:
            filtre = self._topla()
        except ValueError as hata:
            messagebox.showerror("Filtre", str(hata), parent=self)
            return
        self.result = filtre
        if self.on_uygula:
            self.on_uygula(filtre)
        self.destroy()
