"""Fatura satır tablosu kolon tercihleri — firma / kullanıcı / ekran bazında.

Satış ve alış fatura satırları için ayrı ekran kodları.
Gizleme yalnızca displaycolumns ile; values / veri modeli değişmez.
"""

from __future__ import annotations

import json
import logging
import os
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Any, Callable

logger = logging.getLogger(__name__)

EKRAN_SATIS = "satis_faturasi_satirlari"
EKRAN_ALIS = "alis_faturasi_satirlari"

# id, baslik, genislik, min_w, max_w, gorunur, zorunlu
FATURA_SATIR_KOLON_TANIM: dict[str, tuple[tuple[str, str, int, int, int, bool, bool], ...]] = {
    EKRAN_SATIS: (
        ("sira", "Sıra", 48, 40, 80, True, False),
        ("urun_kodu", "Ürün Kodu", 95, 90, 220, True, False),
        ("urun_adi", "Ürün Adı", 220, 180, 500, True, True),
        ("barkod", "Barkod", 110, 80, 220, True, False),
        ("miktar", "Miktar", 78, 65, 140, True, False),
        ("birim", "Birim", 70, 50, 120, True, False),
        ("fiyat", "Birim Fiyat", 100, 70, 200, True, False),
        ("para_birimi", "PB", 50, 40, 80, True, False),
        ("kur", "Kur", 70, 50, 120, True, False),
        ("iskonto", "İskonto %", 160, 100, 280, True, False),
        ("iskonto_tutar", "İskonto Tutarı", 110, 90, 200, True, False),
        ("kdv", "KDV %", 80, 72, 120, True, False),
        ("kdv_tutar", "KDV Tutarı", 90, 70, 180, True, False),
        ("net_birim", "Net Birim Fiyat", 110, 90, 200, True, False),
        ("toplam", "Net Tutar", 110, 90, 220, True, False),
        ("aciklama", "Açıklama", 140, 120, 400, True, False),
    ),
    EKRAN_ALIS: (
        ("barkod", "Barkod", 110, 80, 220, True, False),
        ("kod", "Ürün Kodu", 100, 90, 220, True, False),
        ("ad", "Ürün Adı", 220, 180, 500, True, True),
        ("aciklama", "Açıklama", 140, 120, 400, True, False),
        ("miktar", "Miktar", 78, 65, 140, True, False),
        ("birim", "Birim", 70, 50, 120, True, False),
        ("fiyat", "Alış Fiyatı", 100, 70, 200, True, False),
        ("iskonto", "İskonto", 160, 100, 280, True, False),
        ("kdv", "KDV %", 80, 72, 120, True, False),
        ("net_birim", "Net Birim Fiyat", 110, 90, 200, True, False),
        ("lot", "Lot No", 90, 60, 160, True, False),
        ("lot_girisi", "Lot Girişi", 90, 60, 160, True, False),
        ("toplam", "Net Tutar", 110, 90, 220, True, False),
        ("siparis_miktar", "Sipariş Miktarı", 100, 70, 160, True, False),
        ("irsaliye_miktar", "İrsaliye Miktarı", 100, 70, 160, True, False),
        ("fatura_miktar", "Fatura Miktarı", 100, 70, 160, True, False),
    ),
}

_SAG_HIZA = frozenset(
    {"fiyat", "toplam", "miktar", "iskonto_tutar", "kdv_tutar", "kur", "net_birim"}
)
_ORTA_HIZA = frozenset({"sira", "birim", "para_birimi", "kdv"})


def _ayar_kimlik() -> tuple[str, str]:
    firma, kullanici = "0", "0"
    try:
        from database.session_manager import oturum

        firma = str(
            getattr(oturum, "company_id", None)
            or getattr(oturum, "firma_kodu", None)
            or "0"
        )
        kullanici = str(
            getattr(oturum, "user_id", None)
            or getattr(oturum, "kullanici_adi", None)
            or "0"
        )
    except Exception:
        pass
    return firma, kullanici


def kolon_tanim_map(ekran_kodu: str) -> dict[str, dict[str, Any]]:
    tanim = FATURA_SATIR_KOLON_TANIM[ekran_kodu]
    return {
        k: {
            "baslik": b,
            "genislik": g,
            "min_width": mn,
            "max_width": mx,
            "gorunur": gor,
            "zorunlu": zor,
        }
        for k, b, g, mn, mx, gor, zor in tanim
    }


def zorunlu_kolonlar(ekran_kodu: str) -> frozenset[str]:
    return frozenset(k for k, *_, zor in FATURA_SATIR_KOLON_TANIM[ekran_kodu] if zor)


def ayar_dosyasi(ekran_kodu: str) -> Path:
    firma, kullanici = _ayar_kimlik()
    base = (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        / "MuhasebeProgrami"
        / "ayarlar"
    )
    base.mkdir(parents=True, exist_ok=True)
    safe_f = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(firma))
    safe_u = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(kullanici))
    return base / f"{ekran_kodu}_f{safe_f}_u{safe_u}.json"


def varsayilan_ayarlar(ekran_kodu: str) -> dict:
    tanim = FATURA_SATIR_KOLON_TANIM[ekran_kodu]
    sira = [k for k, *_ in tanim]
    kolonlar = {
        k: {
            "baslik": b,
            "genislik": g,
            "min_width": mn,
            "max_width": mx,
            "gorunur": gor,
            "zorunlu": zor,
        }
        for k, b, g, mn, mx, gor, zor in tanim
    }
    return {"sira": sira, "kolonlar": kolonlar, "_sira": sira}


def _eski_format_birlestir(kayit: dict) -> dict:
    if "kolonlar" in kayit and isinstance(kayit.get("kolonlar"), dict):
        return kayit
    sira = kayit.get("_sira") or kayit.get("sira")
    kolonlar = {
        k: v
        for k, v in kayit.items()
        if k not in ("_sira", "sira", "ekran", "firma_id", "kullanici_id", "profil")
        and isinstance(v, dict)
    }
    return {"sira": sira or [], "kolonlar": kolonlar}


def ayarlari_yukle(ekran_kodu: str) -> dict:
    varsayilan = varsayilan_ayarlar(ekran_kodu)
    bilinen = kolon_tanim_map(ekran_kodu)
    yol = ayar_dosyasi(ekran_kodu)
    kayit: dict | None = None
    if yol.exists():
        try:
            kayit = json.loads(yol.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as hata:
            logger.warning("Kolon ayarı okunamadı (%s): %s — varsayılan", yol, hata)
            return varsayilan
    else:
        if ekran_kodu == EKRAN_SATIS:
            eski = yol.parent / "fatura_satir_kolonlari.json"
            if eski.exists():
                try:
                    kayit = json.loads(eski.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    kayit = None
            if kayit is None:
                # Eski firma_kullanici dosyası
                for aday in yol.parent.glob("fatura_satir_kolonlari_*.json"):
                    try:
                        kayit = json.loads(aday.read_text(encoding="utf-8"))
                        break
                    except (OSError, json.JSONDecodeError):
                        continue
        if kayit is None:
            return varsayilan

    try:
        kayit = _eski_format_birlestir(kayit)
        ham_kolon = kayit.get("kolonlar") or {}
        sira = [k for k in (kayit.get("sira") or kayit.get("_sira") or []) if k in bilinen]
        for k in bilinen:
            if k not in sira:
                if k == "net_birim" and "toplam" in sira:
                    sira.insert(sira.index("toplam"), k)
                else:
                    sira.append(k)
        zorunlu = zorunlu_kolonlar(ekran_kodu)
        kolonlar: dict = {}
        for anahtar, meta in bilinen.items():
            cfg = ham_kolon.get(anahtar) or {}
            try:
                w = int(cfg.get("genislik", meta["genislik"]))
            except (TypeError, ValueError):
                w = meta["genislik"]
            w = max(meta["min_width"], min(w, meta["max_width"]))
            g = bool(cfg.get("gorunur", meta["gorunur"]))
            if anahtar in zorunlu:
                g = True
            kolonlar[anahtar] = {
                "baslik": meta["baslik"],
                "genislik": w,
                "min_width": meta["min_width"],
                "max_width": meta["max_width"],
                "gorunur": g,
                "zorunlu": anahtar in zorunlu,
            }
        if not any(c["gorunur"] for c in kolonlar.values()):
            for k in zorunlu or list(kolonlar)[:1]:
                if k in kolonlar:
                    kolonlar[k]["gorunur"] = True
        return {"sira": sira, "kolonlar": kolonlar, "_sira": sira}
    except Exception as hata:
        logger.exception("Kolon ayarı doğrulanamadı (%s): %s", ekran_kodu, hata)
        return varsayilan


def ayarlari_kaydet(ekran_kodu: str, ayarlar: dict) -> None:
    bilinen = kolon_tanim_map(ekran_kodu)
    zorunlu = zorunlu_kolonlar(ekran_kodu)
    sira = [k for k in (ayarlar.get("sira") or ayarlar.get("_sira") or []) if k in bilinen]
    for k in bilinen:
        if k not in sira:
            sira.append(k)
    ham = ayarlar.get("kolonlar") or ayarlar
    temiz: dict = {}
    for anahtar, meta in bilinen.items():
        cfg = ham.get(anahtar) or {}
        if not isinstance(cfg, dict):
            cfg = {}
        try:
            w = int(cfg.get("genislik", meta["genislik"]))
        except (TypeError, ValueError):
            w = meta["genislik"]
        w = max(meta["min_width"], min(w, meta["max_width"]))
        g = bool(cfg.get("gorunur", meta["gorunur"]))
        if anahtar in zorunlu:
            g = True
        temiz[anahtar] = {"genislik": w, "gorunur": g}
    if not any(c["gorunur"] for c in temiz.values()):
        for k in zorunlu:
            temiz[k]["gorunur"] = True
    firma, kullanici = _ayar_kimlik()
    yol = ayar_dosyasi(ekran_kodu)
    yol.write_text(
        json.dumps(
            {
                "ekran": ekran_kodu,
                "firma_id": firma,
                "kullanici_id": kullanici,
                "sira": sira,
                "kolonlar": temiz,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def flat_to_nested(flat: dict, ekran_kodu: str) -> dict:
    bilinen = kolon_tanim_map(ekran_kodu)
    sira = [k for k in (flat.get("_sira") or flat.get("sira") or []) if k in bilinen]
    for k in bilinen:
        if k not in sira:
            sira.append(k)
    kolonlar = {}
    for k, meta in bilinen.items():
        cfg = flat.get(k) or {}
        if not isinstance(cfg, dict):
            cfg = {}
        kolonlar[k] = {
            "baslik": meta["baslik"],
            "genislik": int(cfg.get("genislik", meta["genislik"])),
            "gorunur": bool(cfg.get("gorunur", True)),
            "min_width": meta["min_width"],
            "max_width": meta["max_width"],
            "zorunlu": meta["zorunlu"],
        }
    return {"sira": sira, "kolonlar": kolonlar, "_sira": sira}


def nested_to_flat(ayar: dict, ekran_kodu: str) -> dict:
    bilinen = kolon_tanim_map(ekran_kodu)
    flat: dict = {}
    for k, meta in bilinen.items():
        cfg = (ayar.get("kolonlar") or {}).get(k) or {}
        flat[k] = {
            "baslik": meta["baslik"],
            "genislik": int(cfg.get("genislik", meta["genislik"])),
            "gorunur": bool(cfg.get("gorunur", meta["gorunur"])),
            "min_width": meta["min_width"],
            "max_width": meta["max_width"],
            "zorunlu": meta["zorunlu"],
        }
    flat["_sira"] = list(ayar.get("sira") or ayar.get("_sira") or list(bilinen))
    return flat


def tabloya_uygula(tree: ttk.Treeview, ekran_kodu: str, ayarlar: dict | None = None) -> dict:
    """displaycolumns + genişlik; columns listesini kesmez."""
    ayar = ayarlar or ayarlari_yukle(ekran_kodu)
    if "kolonlar" not in ayar:
        ayar = flat_to_nested(ayar, ekran_kodu)
    bilinen = kolon_tanim_map(ekran_kodu)
    sira = [k for k in (ayar.get("sira") or []) if k in bilinen]
    for k in bilinen:
        if k not in sira:
            sira.append(k)
    ayar["sira"] = sira
    ayar["_sira"] = sira

    tum = tuple(k for k, *_ in FATURA_SATIR_KOLON_TANIM[ekran_kodu])
    try:
        mevcut = tuple(tree.cget("columns") or ())
    except tk.TclError:
        mevcut = ()
    if mevcut != tum:
        try:
            tree.configure(columns=tum)
        except tk.TclError:
            pass

    gorunen: list[str] = []
    for anahtar in sira:
        meta = bilinen[anahtar]
        cfg = (ayar.get("kolonlar") or {}).get(anahtar) or {}
        try:
            w = int(cfg.get("genislik", meta["genislik"]))
        except (TypeError, ValueError):
            w = meta["genislik"]
        w = max(meta["min_width"], min(w, meta["max_width"]))
        if anahtar in _SAG_HIZA:
            anchor = "e"
        elif anahtar in _ORTA_HIZA:
            anchor = "center"
        else:
            anchor = "w"
        tree.heading(anahtar, text=meta["baslik"], anchor=anchor)
        tree.column(
            anahtar,
            width=w,
            minwidth=meta["min_width"],
            stretch=(anahtar in ("urun_adi", "ad", "aciklama")),
            anchor=anchor,
        )
        gorunur = bool(cfg.get("gorunur", True)) or meta["zorunlu"]
        ayar.setdefault("kolonlar", {})[anahtar] = {
            **meta,
            "genislik": w,
            "gorunur": gorunur,
        }
        if gorunur:
            gorunen.append(anahtar)
    if not gorunen:
        zor = list(zorunlu_kolonlar(ekran_kodu)) or [tum[0]]
        gorunen = zor
        for k in gorunen:
            ayar["kolonlar"][k]["gorunur"] = True
    tree["displaycolumns"] = gorunen
    return ayar


def tree_genislikleri_oku(tree: ttk.Treeview, ekran_kodu: str, ayar: dict) -> dict:
    ayar = deepcopy(ayar)
    if "kolonlar" not in ayar:
        ayar = flat_to_nested(ayar, ekran_kodu)
    bilinen = kolon_tanim_map(ekran_kodu)
    for anahtar in bilinen:
        try:
            w = int(tree.column(anahtar, "width"))
        except tk.TclError:
            continue
        meta = bilinen[anahtar]
        w = max(meta["min_width"], min(w, meta["max_width"]))
        ayar["kolonlar"].setdefault(anahtar, {})["genislik"] = w
    return ayar


def otomatik_sigdir(tree: ttk.Treeview, kolon_id: str, *, max_ornek: int = 40) -> int:
    try:
        f = tkfont.nametofont("TkDefaultFont")
    except tk.TclError:
        f = tkfont.Font(family="Segoe UI", size=10)
    baslik = tree.heading(kolon_id, "text") or kolon_id
    genislik = f.measure(str(baslik)) + 28
    say = 0
    for iid in tree.get_children(""):
        if say >= max_ornek:
            break
        try:
            deger = tree.set(iid, kolon_id)
        except tk.TclError:
            continue
        genislik = max(genislik, f.measure(str(deger)) + 24)
        say += 1
    return max(40, min(genislik, 480))


def resize_bagla(
    tree: ttk.Treeview,
    ekran_kodu: str,
    *,
    ayar_getter: Callable[[], dict],
    ayar_setter: Callable[[dict], None],
    parent: tk.Misc | None = None,
) -> None:
    """Fare sürükleme bitince debounce kayıt; ayırıcıya çift tık = otomatik sığdır."""
    durum = {"surukleniyor": False, "after": None}

    def _kaydet_genislik():
        durum["after"] = None
        try:
            ayar = tree_genislikleri_oku(tree, ekran_kodu, ayar_getter())
            ayar_setter(ayar)
            ayarlari_kaydet(ekran_kodu, ayar)
        except Exception:
            logger.exception("Kolon genişliği kaydedilemedi")

    def _debounce_kaydet():
        widget = parent or tree
        if durum["after"] is not None:
            try:
                widget.after_cancel(durum["after"])
            except tk.TclError:
                pass
        durum["after"] = widget.after(350, _kaydet_genislik)

    def _btn1(event):
        if tree.identify_region(event.x, event.y) == "separator":
            durum["surukleniyor"] = True
        else:
            durum["surukleniyor"] = False

    def _release(_event=None):
        if durum["surukleniyor"]:
            durum["surukleniyor"] = False
            _debounce_kaydet()

    def _cift(event):
        if tree.identify_region(event.x, event.y) != "separator":
            return
        col = tree.identify_column(event.x)
        try:
            idx = int(str(col).replace("#", "")) - 1
        except ValueError:
            return
        gorunen = list(tree["displaycolumns"] or tree["columns"] or ())
        if idx < 0 or idx >= len(gorunen):
            return
        hedef = gorunen[idx]
        w = otomatik_sigdir(tree, hedef)
        bilinen = kolon_tanim_map(ekran_kodu)
        meta = bilinen.get(hedef) or {}
        w = max(int(meta.get("min_width", 40)), min(w, int(meta.get("max_width", 500))))
        tree.column(hedef, width=w)
        _debounce_kaydet()
        return "break"

    tree.bind("<ButtonPress-1>", _btn1, add="+")
    tree.bind("<ButtonRelease-1>", _release, add="+")
    tree.bind("<Double-Button-1>", _cift, add="+")


class FaturaSatirKolonAyarDialog(tk.Toplevel):
    """Kolon görünürlük / sıra / genişlik — Uygula / Vazgeç / Varsayılana Dön."""

    def __init__(
        self,
        parent,
        ekran_kodu: str,
        mevcut: dict,
        *,
        on_uygula: Callable[[dict], None] | None = None,
        baslik: str | None = None,
    ):
        super().__init__(parent)
        self.ekran_kodu = ekran_kodu
        if "kolonlar" not in mevcut:
            mevcut = flat_to_nested(mevcut, ekran_kodu)
        self.ayarlar = deepcopy(mevcut)
        self.on_uygula = on_uygula
        self._zorunlu = zorunlu_kolonlar(ekran_kodu)
        self._bilinen = kolon_tanim_map(ekran_kodu)
        self.title(baslik or "Kolon Ayarları")
        self.geometry("540x580")
        self.minsize(460, 440)
        self.transient(parent)
        self.grab_set()

        ttk.Label(
            self,
            text="Kolonları göster/gizle, genişlik ve sırayı ayarlayın.\n"
            "Ayarlar bu firma ve kullanıcı için kalıcıdır.",
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=12, pady=(12, 6))

        ust = ttk.Frame(self)
        ust.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Button(ust, text="Tümünü Göster", command=self._tumunu_goster).pack(side="left")
        ttk.Button(ust, text="Varsayılana Dön", command=self._varsayilan).pack(side="left", padx=6)

        liste = ttk.Frame(self, padding=8)
        liste.pack(fill="both", expand=True, padx=8, pady=4)
        baslik_f = ttk.Frame(liste)
        baslik_f.pack(fill="x")
        ttk.Label(baslik_f, text="Görünür", width=8).pack(side="left")
        ttk.Label(baslik_f, text="Kolon", width=22).pack(side="left")
        ttk.Label(baslik_f, text="Genişlik", width=10).pack(side="left")
        ttk.Label(baslik_f, text="Sıra", width=8).pack(side="left")

        canvas = tk.Canvas(liste, highlightthickness=0)
        kaydir = ttk.Scrollbar(liste, orient="vertical", command=canvas.yview)
        self._ic = ttk.Frame(canvas)
        self._ic.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._ic, anchor="nw")
        canvas.configure(yscrollcommand=kaydir.set)
        canvas.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")

        self._satirlar: dict = {}
        self._sira = list(self.ayarlar.get("sira") or list(self._bilinen))
        self._listeyi_ciz()

        alt = ttk.Frame(self, padding=12)
        alt.pack(fill="x")
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Uygula", command=self._uygula_kaydet).pack(side="right", padx=8)

    def _listeyi_ciz(self):
        for w in list(self._ic.winfo_children()):
            w.destroy()
        self._satirlar = {}
        for anahtar in self._sira:
            meta = self._bilinen.get(anahtar) or {}
            cfg = (self.ayarlar.get("kolonlar") or {}).get(anahtar) or meta
            satir = ttk.Frame(self._ic)
            satir.pack(fill="x", pady=2)
            gorunur = tk.BooleanVar(value=bool(cfg.get("gorunur", True)))
            genislik = tk.IntVar(value=int(cfg.get("genislik", meta.get("genislik", 90))))
            cb = ttk.Checkbutton(satir, variable=gorunur, width=4)
            cb.pack(side="left", padx=(4, 8))
            if anahtar in self._zorunlu:
                gorunur.set(True)
                try:
                    cb.state(["disabled"])
                except tk.TclError:
                    pass
            ttk.Label(satir, text=meta.get("baslik") or anahtar, width=22).pack(side="left")
            mn = int(meta.get("min_width", 40))
            mx = int(meta.get("max_width", 600))
            ttk.Spinbox(satir, from_=mn, to=mx, textvariable=genislik, width=8).pack(
                side="left", padx=8
            )
            ttk.Button(satir, text="↑", width=3, command=lambda k=anahtar: self._tasi(k, -1)).pack(
                side="left", padx=2
            )
            ttk.Button(satir, text="↓", width=3, command=lambda k=anahtar: self._tasi(k, 1)).pack(
                side="left"
            )
            self._satirlar[anahtar] = (gorunur, genislik)

    def _tasi(self, anahtar, yon):
        self._degerleri_yaz()
        i = self._sira.index(anahtar)
        j = i + yon
        if j < 0 or j >= len(self._sira):
            return
        self._sira[i], self._sira[j] = self._sira[j], self._sira[i]
        self._listeyi_ciz()

    def _degerleri_yaz(self):
        kolonlar = self.ayarlar.setdefault("kolonlar", {})
        for anahtar, (gorunur, genislik) in self._satirlar.items():
            meta = self._bilinen[anahtar]
            try:
                w = int(genislik.get())
            except (tk.TclError, ValueError, TypeError):
                w = meta["genislik"]
            w = max(meta["min_width"], min(w, meta["max_width"]))
            g = True if anahtar in self._zorunlu else bool(gorunur.get())
            kolonlar[anahtar] = {**meta, "genislik": w, "gorunur": g}
        self.ayarlar["sira"] = list(self._sira)
        self.ayarlar["_sira"] = list(self._sira)

    def _tumunu_goster(self):
        for gorunur, _ in self._satirlar.values():
            gorunur.set(True)

    def _varsayilan(self):
        self.ayarlar = varsayilan_ayarlar(self.ekran_kodu)
        self._sira = list(self.ayarlar["sira"])
        self._listeyi_ciz()

    def _uygula_kaydet(self):
        self._degerleri_yaz()
        gorunen = [k for k, c in self.ayarlar["kolonlar"].items() if c.get("gorunur")]
        if not gorunen:
            messagebox.showwarning(
                "Kolon",
                "En az bir kolon görünür olmalıdır. Ürün Adı gizlenemez.",
                parent=self,
            )
            return
        if self.ekran_kodu == EKRAN_SATIS:
            sira_g = (self.ayarlar["kolonlar"].get("sira") or {}).get("gorunur", True)
            ad_g = (self.ayarlar["kolonlar"].get("urun_adi") or {}).get("gorunur", True)
            if not sira_g and not ad_g:
                messagebox.showwarning(
                    "Kolon",
                    "Sıra ve Ürün Adı aynı anda gizlenemez.",
                    parent=self,
                )
                return
        ayarlari_kaydet(self.ekran_kodu, self.ayarlar)
        if self.on_uygula:
            self.on_uygula(self.ayarlar)
        self.destroy()
