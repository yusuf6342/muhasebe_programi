"""Cari listesi kolon ayarları (müşteri / tedarikçi ortak)."""

from __future__ import annotations

import json
import os
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import ttk
from typing import Callable

from database.session_manager import oturum
from satis_tema import BEYAZ, LACIVERT, METIN, font

EKRAN_KODU = "cari_kartlari_listesi"

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
    ("agirlikli", "Ağırlıklı Ortalama Geçen Gün", 180, True),
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


class CariListeKolonAyarDialog(tk.Toplevel):
    """Kolon göster/gizle + genişlik."""

    def __init__(self, parent, ayarlar: dict, *, on_uygula: Callable[[dict], None] | None = None):
        super().__init__(parent)
        self.title("Cari Liste Kolon Ayarları")
        self.geometry("480x420")
        self.transient(parent)
        self.grab_set()
        self._on_uygula = on_uygula
        self.ayarlar = deepcopy(ayarlar or cari_liste_varsayilan_ayarlari())
        self._vars: dict[str, tk.BooleanVar] = {}

        govde = ttk.Frame(self, padding=10)
        govde.pack(fill="both", expand=True)
        ttk.Label(govde, text="Görünür kolonlar", font=font(10, "bold", self)).pack(anchor="w")

        canvas = tk.Canvas(govde, highlightthickness=0)
        scroll = ttk.Scrollbar(govde, orient="vertical", command=canvas.yview)
        ic = ttk.Frame(canvas)
        ic.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=ic, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        for anahtar, baslik, _w, _g in CARI_LISTE_KOLONLARI:
            cfg = (self.ayarlar.get("kolonlar") or {}).get(anahtar) or {}
            var = tk.BooleanVar(value=bool(cfg.get("gorunur", True)))
            if anahtar in CARI_LISTE_ZORUNLU:
                var.set(True)
            self._vars[anahtar] = var
            satir = ttk.Frame(ic)
            satir.pack(fill="x", pady=2)
            cb = ttk.Checkbutton(satir, text=baslik, variable=var)
            cb.pack(side="left")
            if anahtar in CARI_LISTE_ZORUNLU:
                cb.state(["disabled"])

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Varsayılan", command=self._varsayilan).pack(side="left")
        ttk.Button(alt, text="Uygula", command=self._uygula).pack(side="right", padx=(6, 0))
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")

    def _varsayilan(self):
        self.ayarlar = cari_liste_varsayilan_ayarlari()
        for anahtar, _b, _w, g in CARI_LISTE_KOLONLARI:
            self._vars[anahtar].set(True if anahtar in CARI_LISTE_ZORUNLU else g)

    def _uygula(self):
        for anahtar, var in self._vars.items():
            if anahtar not in self.ayarlar.setdefault("kolonlar", {}):
                self.ayarlar["kolonlar"][anahtar] = {}
            g = True if anahtar in CARI_LISTE_ZORUNLU else bool(var.get())
            self.ayarlar["kolonlar"][anahtar]["gorunur"] = g
            if "genislik" not in self.ayarlar["kolonlar"][anahtar]:
                for k, _b, w, _g in CARI_LISTE_KOLONLARI:
                    if k == anahtar:
                        self.ayarlar["kolonlar"][anahtar]["genislik"] = w
                        break
        cari_liste_ayarlari_kaydet(self.ayarlar)
        if self._on_uygula:
            self._on_uygula(self.ayarlar)
        self.destroy()
