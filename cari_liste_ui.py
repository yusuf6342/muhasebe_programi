"""Cari listesi kolon ayarları (müşteri / tedarikçi ortak)."""

from __future__ import annotations

import json
import math
import os
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import ttk
from typing import Callable

from database.session_manager import oturum
from satis_tema import BEYAZ, LACIVERT, METIN, font

EKRAN_KODU = "cari_kartlari_listesi"


def gecen_gun_sayi(deger) -> float:
    """Geçen gün ham değeri (sıralama / hesap). Boş veya hatalı → 0.0."""
    if deger is None or deger == "":
        return 0.0
    try:
        if isinstance(deger, str):
            s = deger.strip().replace(" ", "").replace(",", ".")
            if not s:
                return 0.0
            return float(s)
        return float(deger)
    except (TypeError, ValueError):
        return 0.0


def gecen_gun_goster(deger) -> str:
    """Liste görüntüsü: küsuratsız tam gün.

    0,50 ve üzeri yukarı, altı aşağı. Python round() kullanılmaz
    (banker's rounding yok); pozitif değerlerde floor(x + 0.5).
    """
    x = gecen_gun_sayi(deger)
    if x < 0:
        x = 0.0
    return str(int(math.floor(x + 0.5)))

# anahtar, baslik, varsayilan_genislik, varsayilan_gorunur
CARI_LISTE_KOLONLARI = (
    ("kod", "Cari Kodu", 110, True),
    ("unvan", "Cari Adı", 220, True),
    ("grup", "Grup", 135, True),
    ("telefon", "Telefon", 115, True),
    ("email", "E-posta", 180, True),
    ("ana_yetkili", "Ana Yetkili", 140, False),
    ("yetkili_telefon", "Yetkili Telefonu", 120, False),
    ("yaklasan_dogum", "Yaklaşan Doğum Günü", 130, False),
    ("bakiye", "Yekûn Bakiye", 140, True),
    ("agirlikli", "Valör", 110, True),
    ("durum", "Durum", 75, True),
)

CARI_LISTE_SAG = frozenset({"bakiye", "agirlikli"})
CARI_LISTE_ZORUNLU = frozenset({"kod", "unvan"})


def cari_liste_varsayilan_ayarlari() -> dict:
    sira = [k for k, _, _, _ in CARI_LISTE_KOLONLARI]
    kolonlar = {
        anahtar: {"baslik": baslik, "genislik": genislik, "gorunur": gorunur}
        for anahtar, baslik, genislik, gorunur in CARI_LISTE_KOLONLARI
    }
    return {"sira": sira, "kolonlar": kolonlar, "profil": "Standart"}


def _ayar_kimlik() -> tuple[str, str]:
    firma = str(oturum.company_id or oturum.firma_kodu or "0")
    kullanici = str(oturum.user_id or oturum.kullanici_adi or "0")
    return firma, kullanici


def cari_liste_ayar_dosyasi() -> Path:
    firma, kullanici = _ayar_kimlik()
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MuhasebeProgrami" / "ayarlar"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"cari_liste_kolon_{firma}_{kullanici}.json"


def cari_liste_ayarlari_yukle() -> dict:
    varsayilan = cari_liste_varsayilan_ayarlari()
    yol = cari_liste_ayar_dosyasi()
    if not yol.exists():
        return deepcopy(varsayilan)
    try:
        kayit = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return deepcopy(varsayilan)

    bilinen = {k for k, _, _, _ in CARI_LISTE_KOLONLARI}
    sira = [k for k in (kayit.get("sira") or []) if k in bilinen]
    for k, _, _, _ in CARI_LISTE_KOLONLARI:
        if k not in sira:
            sira.append(k)

    kolonlar = {}
    gelen_kol = kayit.get("kolonlar") or {}
    for anahtar, baslik, genislik, gorunur in CARI_LISTE_KOLONLARI:
        gelen = gelen_kol.get(anahtar) or {}
        try:
            w = int(gelen.get("genislik", genislik))
        except (TypeError, ValueError):
            w = genislik
        g = bool(gelen.get("gorunur", gorunur))
        if anahtar in CARI_LISTE_ZORUNLU:
            g = True
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


def cari_liste_ayarlari_kaydet(ayarlar: dict) -> None:
    bilinen = {k for k, _, _, _ in CARI_LISTE_KOLONLARI}
    sira = [k for k in (ayarlar.get("sira") or []) if k in bilinen]
    for k, _, _, _ in CARI_LISTE_KOLONLARI:
        if k not in sira:
            sira.append(k)
    temiz_kol = {}
    for anahtar, _baslik, genislik, gorunur in CARI_LISTE_KOLONLARI:
        cfg = (ayarlar.get("kolonlar") or {}).get(anahtar) or {}
        g = bool(cfg.get("gorunur", gorunur))
        if anahtar in CARI_LISTE_ZORUNLU:
            g = True
        try:
            w = int(cfg.get("genislik", genislik))
        except (TypeError, ValueError):
            w = genislik
        temiz_kol[anahtar] = {"genislik": max(40, min(w, 600)), "gorunur": g}
    yol = cari_liste_ayar_dosyasi()
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


def gorunur_kolonlar(ayarlar: dict | None = None) -> list[str]:
    ayar = ayarlar or cari_liste_ayarlari_yukle()
    sira = ayar.get("sira") or []
    kolonlar = ayar.get("kolonlar") or {}
    return [k for k in sira if (kolonlar.get(k) or {}).get("gorunur", True)]


def baslik_metni(anahtar: str, *, etiket: str = "Cari") -> str:
    ozel = {
        "kod": f"{etiket} Kodu",
        "unvan": f"{etiket} Adı",
        "grup": f"{etiket} Grubu",
    }
    if anahtar in ozel:
        return ozel[anahtar]
    for k, baslik, _, _ in CARI_LISTE_KOLONLARI:
        if k == anahtar:
            return baslik
    return anahtar


def tablo_genisliklerini_kaydet(tablo: ttk.Treeview, ayarlar: dict) -> dict:
    """Kullanıcının başlıktan sürüklediği kolon genişliklerini ayara yazar ve kaydeder."""
    kolonlar = ayarlar.setdefault("kolonlar", {})
    degisti = False
    for anahtar in tablo["columns"]:
        try:
            w = int(tablo.column(anahtar, "width"))
        except (tk.TclError, TypeError, ValueError):
            continue
        cfg = kolonlar.setdefault(anahtar, {})
        if int(cfg.get("genislik") or 0) != w:
            cfg["genislik"] = max(40, min(w, 600))
            degisti = True
    if degisti:
        cari_liste_ayarlari_kaydet(ayarlar)
    return ayarlar


class CariListeKolonAyarDialog(tk.Toplevel):
    """Kolon göster/gizle, genişlik ve sıra."""

    def __init__(self, parent, ayarlar: dict, *, on_uygula: Callable[[dict], None] | None = None):
        super().__init__(parent)
        self.title("Cari Liste Kolon Ayarları")
        self.geometry("560x480")
        self.minsize(480, 360)
        self.transient(parent)
        self._on_uygula = on_uygula
        self.ayarlar = deepcopy(ayarlar or cari_liste_varsayilan_ayarlari())
        self._vars: dict[str, tk.BooleanVar] = {}
        self._genislik: dict[str, tk.StringVar] = {}
        self._sira: list[str] = list(self.ayarlar.get("sira") or [])
        for k, _b, _w, _g in CARI_LISTE_KOLONLARI:
            if k not in self._sira:
                self._sira.append(k)

        govde = ttk.Frame(self, padding=10)
        govde.pack(fill="both", expand=True)
        ttk.Label(
            govde,
            text="Görünür kolonlar, genişlik (piksel) ve sıra",
            font=font(10, "bold", self),
        ).pack(anchor="w", pady=(0, 6))

        canvas = tk.Canvas(govde, highlightthickness=0)
        scroll = ttk.Scrollbar(govde, orient="vertical", command=canvas.yview)
        self._ic = ttk.Frame(canvas)
        self._ic.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._ic, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        basliklar = {k: b for k, b, _w, _g in CARI_LISTE_KOLONLARI}
        for anahtar, _baslik, varsayilan_w, _g in CARI_LISTE_KOLONLARI:
            cfg = (self.ayarlar.get("kolonlar") or {}).get(anahtar) or {}
            var = tk.BooleanVar(value=bool(cfg.get("gorunur", True)))
            if anahtar in CARI_LISTE_ZORUNLU:
                var.set(True)
            self._vars[anahtar] = var
            self._genislik[anahtar] = tk.StringVar(value=str(cfg.get("genislik") or varsayilan_w))
        self._basliklar = basliklar
        self._satirlari_ciz()

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Varsayılan", command=self._varsayilan).pack(side="left")
        ttk.Button(alt, text="Uygula", command=self._uygula).pack(side="right", padx=(6, 0))
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        self.grab_set()

    def _satirlari_ciz(self):
        for w in self._ic.winfo_children():
            w.destroy()
        for i, anahtar in enumerate(self._sira):
            satir = ttk.Frame(self._ic)
            satir.pack(fill="x", pady=2)
            cb = ttk.Checkbutton(
                satir, text=self._basliklar[anahtar], variable=self._vars[anahtar], width=26
            )
            cb.pack(side="left")
            if anahtar in CARI_LISTE_ZORUNLU:
                cb.state(["disabled"])
            ttk.Spinbox(
                satir,
                from_=40,
                to=600,
                increment=10,
                width=6,
                textvariable=self._genislik[anahtar],
            ).pack(side="left", padx=(6, 6))
            yukari = ttk.Button(satir, text="▲", width=3, command=lambda a=anahtar: self._tasi(a, -1))
            yukari.pack(side="left")
            asagi = ttk.Button(satir, text="▼", width=3, command=lambda a=anahtar: self._tasi(a, 1))
            asagi.pack(side="left", padx=(2, 0))
            if i == 0:
                yukari.state(["disabled"])
            if i == len(self._sira) - 1:
                asagi.state(["disabled"])

    def _tasi(self, anahtar: str, yon: int):
        i = self._sira.index(anahtar)
        j = i + yon
        if not 0 <= j < len(self._sira):
            return
        self._sira[i], self._sira[j] = self._sira[j], self._sira[i]
        self._satirlari_ciz()

    def _varsayilan(self):
        self.ayarlar = cari_liste_varsayilan_ayarlari()
        self._sira = [k for k, _b, _w, _g in CARI_LISTE_KOLONLARI]
        for anahtar, _b, w, g in CARI_LISTE_KOLONLARI:
            self._vars[anahtar].set(True if anahtar in CARI_LISTE_ZORUNLU else g)
            self._genislik[anahtar].set(str(w))
        self._satirlari_ciz()

    def _uygula(self):
        kolonlar = self.ayarlar.setdefault("kolonlar", {})
        varsayilan_w = {k: w for k, _b, w, _g in CARI_LISTE_KOLONLARI}
        for anahtar, var in self._vars.items():
            cfg = kolonlar.setdefault(anahtar, {})
            cfg["gorunur"] = True if anahtar in CARI_LISTE_ZORUNLU else bool(var.get())
            try:
                w = int(str(self._genislik[anahtar].get()).strip())
            except (TypeError, ValueError):
                w = int(cfg.get("genislik") or varsayilan_w[anahtar])
            cfg["genislik"] = max(40, min(w, 600))
        self.ayarlar["sira"] = list(self._sira)
        cari_liste_ayarlari_kaydet(self.ayarlar)
        self.ayarlar = cari_liste_ayarlari_yukle()
        if self._on_uygula:
            self._on_uygula(self.ayarlar)
        self.destroy()
