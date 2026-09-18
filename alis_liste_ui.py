"""Satın Alma liste kolon ayarları — kullanıcı + firma bazında kalıcı JSON."""

from __future__ import annotations

import json
import os
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Sequence

from database.session_manager import oturum

# ekran_kodu -> (anahtar, baslik, genislik, gorunur)
ALIS_LISTE_TANIMLARI: dict[str, tuple[tuple[str, str, int, bool], ...]] = {
    "alis_siparis_listesi": (
        ("no", "Sipariş No", 130, True),
        ("tarih", "Tarih", 90, True),
        ("termin", "Termin", 90, True),
        ("kod", "Kod", 80, True),
        ("tedarikci", "Tedarikçi", 200, True),
        ("toplam", "Toplam", 110, True),
        ("odeme", "Ödeme", 110, True),
        ("kalan", "Kalan", 110, True),
        ("durum", "Durum", 100, True),
    ),
    "alis_irsaliye_listesi": (
        ("no", "İrsaliye No", 140, True),
        ("tarih", "Tarih", 90, True),
        ("kod", "Kod", 80, True),
        ("tedarikci", "Tedarikçi", 180, True),
        ("siparis", "Sipariş", 130, True),
        ("toplam", "Toplam", 100, True),
        ("fatura", "Faturalanan", 100, True),
        ("kalan", "Kalan", 100, True),
        ("durum", "Durum", 110, True),
    ),
    "alis_fatura_listesi": (
        ("no", "Fatura No", 130, True),
        ("tarih", "Tarih", 85, True),
        ("saat", "Saat", 60, True),
        ("vade", "Vade", 85, True),
        ("tedarikci", "Tedarikçi", 170, True),
        ("siparis", "Sipariş", 110, True),
        ("irsaliye", "İrsaliye", 110, True),
        ("depo", "Depo", 90, True),
        ("genel", "Genel", 95, True),
        ("odeme", "Ödeme", 95, True),
        ("kalan", "Kalan", 95, True),
        ("durum", "Durum", 80, True),
    ),
}

ALIS_LISTE_ZORUNLU = {
    "alis_siparis_listesi": frozenset({"no"}),
    "alis_irsaliye_listesi": frozenset({"no"}),
    "alis_fatura_listesi": frozenset({"no"}),
}


def _ayar_kimlik() -> tuple[str, str]:
    firma = str(oturum.company_id or oturum.firma_kodu or "0")
    kullanici = str(oturum.user_id or oturum.kullanici_adi or "0")
    return firma, kullanici


def alis_liste_ayar_dosyasi(ekran_kodu: str) -> Path:
    firma, kullanici = _ayar_kimlik()
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MuhasebeProgrami" / "ayarlar"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{ekran_kodu}_f{firma}_u{kullanici}.json"


def alis_liste_varsayilan(ekran_kodu: str) -> dict:
    tanim = ALIS_LISTE_TANIMLARI[ekran_kodu]
    sira = [k for k, _, _, _ in tanim]
    kolonlar = {
        anahtar: {"baslik": baslik, "genislik": genislik, "gorunur": gorunur}
        for anahtar, baslik, genislik, gorunur in tanim
    }
    return {"sira": sira, "kolonlar": kolonlar, "profil": "Standart"}


def alis_liste_ayarlari_yukle(ekran_kodu: str) -> dict:
    tanim = ALIS_LISTE_TANIMLARI[ekran_kodu]
    bilinen = {k for k, _, _, _ in tanim}
    varsayilan = alis_liste_varsayilan(ekran_kodu)
    yol = alis_liste_ayar_dosyasi(ekran_kodu)
    if not yol.exists():
        return varsayilan
    try:
        kayit = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return varsayilan

    sira = [k for k in (kayit.get("sira") or []) if k in bilinen]
    for k, _, _, _ in tanim:
        if k not in sira:
            sira.append(k)

    zorunlu = ALIS_LISTE_ZORUNLU.get(ekran_kodu, frozenset())
    kolonlar: dict = {}
    for anahtar, baslik, genislik, gorunur in tanim:
        cfg = (kayit.get("kolonlar") or {}).get(anahtar) or {}
        try:
            w = int(cfg.get("genislik", genislik))
        except (TypeError, ValueError):
            w = genislik
        g = bool(cfg.get("gorunur", gorunur))
        if anahtar in zorunlu:
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


def alis_liste_ayarlari_kaydet(ekran_kodu: str, ayarlar: dict) -> None:
    tanim = ALIS_LISTE_TANIMLARI[ekran_kodu]
    bilinen = {k for k, _, _, _ in tanim}
    sira = [k for k in (ayarlar.get("sira") or []) if k in bilinen]
    for k, _, _, _ in tanim:
        if k not in sira:
            sira.append(k)
    zorunlu = ALIS_LISTE_ZORUNLU.get(ekran_kodu, frozenset())
    temiz: dict = {}
    for anahtar, _, genislik, gorunur in tanim:
        cfg = (ayarlar.get("kolonlar") or {}).get(anahtar) or {}
        g = bool(cfg.get("gorunur", gorunur))
        if anahtar in zorunlu:
            g = True
        try:
            w = int(cfg.get("genislik", genislik))
        except (TypeError, ValueError):
            w = genislik
        temiz[anahtar] = {"genislik": max(40, min(w, 600)), "gorunur": g}
    firma, kullanici = _ayar_kimlik()
    yol = alis_liste_ayar_dosyasi(ekran_kodu)
    yol.write_text(
        json.dumps(
            {
                "ekran": ekran_kodu,
                "firma_id": firma,
                "kullanici_id": kullanici,
                "sira": sira,
                "kolonlar": temiz,
                "profil": ayarlar.get("profil") or "Standart",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def alis_liste_uygula(tree: ttk.Treeview, ekran_kodu: str, ayarlar: dict | None = None) -> dict:
    """Görünür kolon sırası ve genişlikleri uygular; ayar dict döner."""
    ayar = ayarlar or alis_liste_ayarlari_yukle(ekran_kodu)
    gorunen = [
        k
        for k in ayar["sira"]
        if (ayar["kolonlar"].get(k) or {}).get("gorunur", True)
    ]
    if not gorunen:
        gorunen = list(ayar["sira"])
    tree.configure(columns=gorunen, displaycolumns=gorunen)
    for k in gorunen:
        cfg = ayar["kolonlar"].get(k) or {}
        tree.heading(k, text=cfg.get("baslik") or k)
        tree.column(k, width=int(cfg.get("genislik") or 100), minwidth=40)
    return ayar


def alis_liste_degerleri(ekran_kodu: str, ayarlar: dict, ham: dict[str, object]) -> tuple:
    """Tree insert için görünür kolon sırasına göre değer tuple'ı."""
    gorunen = [
        k
        for k in ayarlar["sira"]
        if (ayarlar["kolonlar"].get(k) or {}).get("gorunur", True)
    ]
    if not gorunen:
        gorunen = list(ayarlar["sira"])
    return tuple(ham.get(k, "") for k in gorunen)


class AlisKolonAyarDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        ekran_kodu: str,
        mevcut: dict,
        *,
        on_uygula: Callable[[dict], None] | None = None,
    ):
        super().__init__(parent)
        self.ekran_kodu = ekran_kodu
        self.ayarlar = deepcopy(mevcut)
        self.on_uygula = on_uygula
        self.title("Satın Alma Liste — Kolon Ayarları")
        self.geometry("480x420")
        self.minsize(420, 360)
        self.transient(parent)
        self.grab_set()

        ttk.Label(
            self,
            text="Kolonları göster/gizle, genişlik ve sırayı ayarlayın.\nAyarlar bu kullanıcı ve firma için kaydedilir.",
        ).pack(anchor="w", padx=12, pady=(12, 6))

        liste_f = ttk.Frame(self)
        liste_f.pack(fill="both", expand=True, padx=12, pady=4)
        self.liste = tk.Listbox(liste_f, activestyle="dotbox", exportselection=False)
        self.liste.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(liste_f, orient="vertical", command=self.liste.yview)
        sb.pack(side="right", fill="y")
        self.liste.configure(yscrollcommand=sb.set)

        form = ttk.Frame(self)
        form.pack(fill="x", padx=12, pady=6)
        self.gorunur_var = tk.BooleanVar(value=True)
        self.genislik_var = tk.StringVar(value="100")
        ttk.Checkbutton(form, text="Görünür", variable=self.gorunur_var).pack(side="left")
        ttk.Label(form, text="Genişlik").pack(side="left", padx=(12, 4))
        ttk.Entry(form, textvariable=self.genislik_var, width=8).pack(side="left")
        ttk.Button(form, text="Uygula (satır)", command=self._satirdan_yaz).pack(side="left", padx=8)

        sira_f = ttk.Frame(self)
        sira_f.pack(fill="x", padx=12)
        ttk.Button(sira_f, text="↑", width=3, command=lambda: self._tasi(-1)).pack(side="left")
        ttk.Button(sira_f, text="↓", width=3, command=lambda: self._tasi(1)).pack(side="left", padx=4)

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=12)
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right", padx=8)
        ttk.Button(alt, text="Önizle", command=self._uygula).pack(side="right")

        self._sira = list(self.ayarlar.get("sira") or [])
        self._liste_doldur()
        self.liste.bind("<<ListboxSelect>>", lambda _e: self._satir_secildi())
        if self._sira:
            self.liste.selection_set(0)
            self._satir_secildi()

    def _liste_doldur(self):
        self.liste.delete(0, "end")
        for k in self._sira:
            cfg = (self.ayarlar.get("kolonlar") or {}).get(k) or {}
            isaret = "✓" if cfg.get("gorunur", True) else "·"
            self.liste.insert("end", f"{isaret}  {cfg.get('baslik', k)}  ({cfg.get('genislik', 100)})")

    def _secili_anahtar(self) -> str | None:
        sec = self.liste.curselection()
        if not sec:
            return None
        return self._sira[int(sec[0])]

    def _satir_secildi(self):
        k = self._secili_anahtar()
        if not k:
            return
        cfg = (self.ayarlar.get("kolonlar") or {}).get(k) or {}
        self.gorunur_var.set(bool(cfg.get("gorunur", True)))
        self.genislik_var.set(str(cfg.get("genislik", 100)))

    def _satirdan_yaz(self):
        k = self._secili_anahtar()
        if not k:
            return
        zorunlu = ALIS_LISTE_ZORUNLU.get(self.ekran_kodu, frozenset())
        g = bool(self.gorunur_var.get())
        if k in zorunlu:
            g = True
        try:
            w = int(self.genislik_var.get().strip())
        except ValueError:
            messagebox.showwarning("Kolon", "Geçerli bir genişlik girin.", parent=self)
            return
        self.ayarlar.setdefault("kolonlar", {})[k] = {
            **(self.ayarlar.get("kolonlar") or {}).get(k, {}),
            "gorunur": g,
            "genislik": max(40, min(w, 600)),
        }
        self._liste_doldur()
        idx = self._sira.index(k)
        self.liste.selection_set(idx)

    def _tasi(self, delta: int):
        k = self._secili_anahtar()
        if not k:
            return
        i = self._sira.index(k)
        j = i + delta
        if j < 0 or j >= len(self._sira):
            return
        self._sira[i], self._sira[j] = self._sira[j], self._sira[i]
        self.ayarlar["sira"] = list(self._sira)
        self._liste_doldur()
        self.liste.selection_set(j)

    def _mevcut(self) -> dict:
        self._satirdan_yaz()
        self.ayarlar["sira"] = list(self._sira)
        return deepcopy(self.ayarlar)

    def _uygula(self):
        ayar = self._mevcut()
        gorunen = [
            k for k in ayar["sira"] if (ayar["kolonlar"].get(k) or {}).get("gorunur", True)
        ]
        zorunlu = ALIS_LISTE_ZORUNLU.get(self.ekran_kodu, frozenset())
        if zorunlu and not any(z in gorunen for z in zorunlu):
            messagebox.showwarning("Kolon", "Zorunlu kolon görünür olmalıdır.", parent=self)
            return
        if not gorunen:
            messagebox.showwarning("Kolon", "En az bir kolon görünür olmalı.", parent=self)
            return
        if self.on_uygula:
            self.on_uygula(ayar)

    def _kaydet(self):
        self._uygula()
        alis_liste_ayarlari_kaydet(self.ekran_kodu, self.ayarlar)
        messagebox.showinfo(
            "Kolon",
            "Kolon ayarları bu kullanıcı/firma için kaydedildi.",
            parent=self,
        )
