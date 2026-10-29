"""Ortak liste filtre / sıralama / sayfalama / toplam yardımcıları.

Tüm operasyonel listelerde Excel benzeri kolon hunisi, tarih/tutar aralığı,
alt toplam satırı ve sayfa bilgisi için yeniden kullanılabilir bileşenler.
"""

from __future__ import annotations

import json
import math
import os
import re
import tkinter as tk
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from tkinter import messagebox, ttk

from database.turkce_normalize import turkce_normalize


# ---------------------------------------------------------------------------
# Temel parse yardımcıları
# ---------------------------------------------------------------------------

def tarih_oku(entry_veya_metin) -> date | None:
    """Entry veya metinden gg.aa.yyyy tarih okur; boş/hatalı → None."""
    if entry_veya_metin is None:
        return None
    if hasattr(entry_veya_metin, "get"):
        try:
            metin = entry_veya_metin.get().strip()
        except tk.TclError:
            return None
    else:
        metin = str(entry_veya_metin or "").strip()
    if not metin:
        return None
    try:
        return datetime.strptime(metin, "%d.%m.%Y").date()
    except ValueError:
        return None


def tutar_oku(entry_veya_metin) -> Decimal | None:
    """TR/EN tutar metnini Decimal'e çevirir; boş → None."""
    if entry_veya_metin is None:
        return None
    if hasattr(entry_veya_metin, "get"):
        try:
            ham = entry_veya_metin.get().strip()
        except tk.TclError:
            return None
    else:
        ham = str(entry_veya_metin or "").strip()
    if not ham:
        return None
    ham = ham.replace(".", "").replace(",", ".") if "," in ham else ham.replace(",", "")
    try:
        return Decimal(ham)
    except (InvalidOperation, ValueError):
        return None


def para_goster_tr(tutar) -> str:
    try:
        d = Decimal(str(tutar or 0))
    except Exception:
        d = Decimal("0")
    return f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def deger_metin(deger) -> str:
    if deger is None:
        return ""
    return str(deger)


# ---------------------------------------------------------------------------
# Kolon hunisi (Excel benzeri)
# ---------------------------------------------------------------------------

class TreeviewKolonFiltrePopup(tk.Toplevel):
    """Excel benzeri kolon başlığı seçim filtresi (çoklu seçim + ara)."""

    BOS_ETIKET = "(Boş)"

    def __init__(self, parent, baslik, degerler, secili=None, uygula_cb=None, temizle_cb=None):
        super().__init__(parent)
        self.title(f"Filtre: {baslik}")
        self.transient(parent)
        self.resizable(False, True)
        self.uygula_cb = uygula_cb
        self.temizle_cb = temizle_cb
        self._tum_degerler = sorted(degerler, key=lambda d: (d == "", str(d).casefold()))
        self._degiskenler = {}
        self._satirlar = []

        ust = ttk.Frame(self, padding=8)
        ust.pack(fill="x")
        ttk.Label(ust, text="Ara:").pack(side="left")
        self.arama = ttk.Entry(ust, width=28)
        self.arama.pack(side="left", padx=(4, 0), fill="x", expand=True)
        self.arama.bind("<KeyRelease>", self._ara)

        btn_ust = ttk.Frame(self, padding=(8, 0))
        btn_ust.pack(fill="x")
        ttk.Button(btn_ust, text="Tümünü seç", command=self._hepsini_sec).pack(side="left")
        ttk.Button(btn_ust, text="Hiçbirini seçme", command=self._hicbirini_sec).pack(side="left", padx=6)

        orta = ttk.Frame(self, padding=8)
        orta.pack(fill="both", expand=True)
        canvas = tk.Canvas(orta, width=280, height=260, highlightthickness=0)
        scroll = ttk.Scrollbar(orta, orient="vertical", command=canvas.yview)
        self.liste = ttk.Frame(canvas)
        self.liste.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.liste, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        baslangic = set(secili) if secili is not None else set(self._tum_degerler)
        for deger in self._tum_degerler:
            var = tk.BooleanVar(value=deger in baslangic)
            self._degiskenler[deger] = var
            satir = ttk.Frame(self.liste)
            satir.pack(fill="x", anchor="w")
            etiket = self.BOS_ETIKET if deger == "" else str(deger)
            ttk.Checkbutton(satir, text=etiket, variable=var).pack(side="left", anchor="w")
            self._satirlar.append((deger, satir))

        alt = ttk.Frame(self, padding=8)
        alt.pack(fill="x")
        ttk.Button(alt, text="Uygula", command=self._uygula).pack(side="left")
        ttk.Button(alt, text="Bu Kolonu Temizle", command=self._temizle).pack(side="left", padx=6)
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")

        self.bind("<Escape>", lambda _e: self.destroy())
        self.arama.focus_set()

    def _ara(self, _event=None):
        q = turkce_normalize(self.arama.get().strip())
        for deger, satir in self._satirlar:
            etiket = self.BOS_ETIKET if deger == "" else str(deger)
            if not q or q in turkce_normalize(etiket):
                satir.pack(fill="x", anchor="w")
            else:
                satir.pack_forget()

    def _hepsini_sec(self):
        for var in self._degiskenler.values():
            var.set(True)

    def _hicbirini_sec(self):
        for var in self._degiskenler.values():
            var.set(False)

    def _uygula(self):
        secilen = {d for d, var in self._degiskenler.items() if var.get()}
        if self.uygula_cb:
            self.uygula_cb(secilen)
        self.destroy()

    def _temizle(self):
        if self.temizle_cb:
            self.temizle_cb()
        self.destroy()


# ---------------------------------------------------------------------------
# Filtre durumu + satır eşleme
# ---------------------------------------------------------------------------

class ListeFiltreDurumu:
    """Kolon hunisi + tutar aralığı durumu."""

    def __init__(self):
        self.kolon: dict[str, set[str]] = {}
        self.tutar_min: Decimal | None = None
        self.tutar_max: Decimal | None = None
        self.siralama: tuple[str, bool] | None = None  # (kolon, reverse)
        self._popup = None

    def temizle(self):
        self.kolon.clear()
        self.tutar_min = None
        self.tutar_max = None

    def aktif_adet(self) -> int:
        n = len(self.kolon)
        if self.tutar_min is not None or self.tutar_max is not None:
            n += 1
        return n

    def kolon_uygula(self, kolon: str, secilen: set[str], tum_adaylar: set[str] | None = None):
        if not secilen:
            self.kolon[kolon] = set()
        elif tum_adaylar is not None and tum_adaylar and secilen >= tum_adaylar:
            self.kolon.pop(kolon, None)
        else:
            self.kolon[kolon] = set(secilen)

    def kolon_temizle(self, kolon: str):
        self.kolon.pop(kolon, None)


def satir_kolon_filtre_uygun(
    values: Sequence[Any],
    kolonlar: Sequence[str],
    filtre: dict[str, set[str]],
) -> bool:
    for i, kolon in enumerate(kolonlar):
        if kolon not in filtre:
            continue
        deger = "" if i >= len(values) or values[i] is None else str(values[i])
        if deger not in filtre[kolon]:
            return False
    return True


def tutar_aralik_uygun(tutar, tmin: Decimal | None, tmax: Decimal | None) -> bool:
    try:
        d = Decimal(str(tutar or 0))
    except Exception:
        d = Decimal("0")
    if tmin is not None and d < tmin:
        return False
    if tmax is not None and d > tmax:
        return False
    return True


def kolon_benzersiz_degerler(
    satirlar: Iterable,
    kolon_idx: int,
    *,
    values_key: str | Callable = "values",
) -> set[str]:
    degerler: set[str] = set()
    for s in satirlar:
        if callable(values_key):
            vals = values_key(s)
        elif isinstance(s, dict):
            vals = s.get(values_key) or ()
        elif isinstance(s, (list, tuple)) and len(s) == 2:
            vals = s[1]
        else:
            vals = s
        degerler.add("" if kolon_idx >= len(vals) or vals[kolon_idx] is None else str(vals[kolon_idx]))
    return degerler


def baslik_filtre_metni(
    baslik: str,
    *,
    filtre_aktif: bool = False,
    siralama: tuple[str, bool] | None = None,
    kolon: str | None = None,
) -> str:
    parcalar = [baslik]
    if siralama and kolon and siralama[0] == kolon:
        parcalar.append("↓" if siralama[1] else "↑")
    parcalar.append("▼" if filtre_aktif else "▾")
    return " ".join(parcalar)


def basliklari_filtre_isaretle(
    tablo: ttk.Treeview,
    basliklar: dict[str, str],
    filtre: dict[str, set],
    siralama: tuple[str, bool] | None = None,
):
    for kolon, baslik in basliklar.items():
        try:
            tablo.heading(
                kolon,
                text=baslik_filtre_metni(
                    baslik,
                    filtre_aktif=kolon in filtre,
                    siralama=siralama,
                    kolon=kolon,
                ),
            )
        except tk.TclError:
            pass


def kolon_filtre_popup_ac(
    parent,
    tablo: ttk.Treeview,
    kolon: str,
    kolonlar: Sequence[str],
    basliklar: dict[str, str],
    filtre: dict[str, set],
    aday_satirlar: Iterable,
    *,
    uygula_cb: Callable[[str, set], None],
    temizle_cb: Callable[[str], None],
    values_key: str | Callable = "values",
    popup_ref_attr: str | None = None,
    popup_owner=None,
):
    """Ortak kolon hunisi açıcı. popup_owner + popup_ref_attr ile önceki popup kapatılır."""
    owner = popup_owner if popup_owner is not None else parent
    if popup_ref_attr:
        eski = getattr(owner, popup_ref_attr, None)
        if eski is not None:
            try:
                if eski.winfo_exists():
                    eski.destroy()
            except tk.TclError:
                pass
    try:
        idx = list(kolonlar).index(kolon)
    except ValueError:
        return None
    degerler = kolon_benzersiz_degerler(aday_satirlar, idx, values_key=values_key)
    mevcut = filtre.get(kolon)
    baslik = basliklar.get(kolon, kolon)
    pop = TreeviewKolonFiltrePopup(
        parent,
        baslik,
        degerler,
        secili=mevcut,
        uygula_cb=lambda secilen, c=kolon: uygula_cb(c, secilen),
        temizle_cb=lambda c=kolon: temizle_cb(c),
    )
    try:
        x = tablo.winfo_rootx() + 40
        y = tablo.winfo_rooty() + 28
        pop.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass
    if popup_ref_attr:
        setattr(owner, popup_ref_attr, pop)
    return pop


def heading_kolon_bul(tablo: ttk.Treeview, event, kolonlar: Sequence[str]) -> str | None:
    if tablo.identify_region(event.x, event.y) != "heading":
        return None
    kolon_id = tablo.identify_column(event.x)
    try:
        idx = int(kolon_id.replace("#", "")) - 1
        return kolonlar[idx]
    except (ValueError, IndexError, TypeError):
        return None


def treeview_filtre_bagla(
    tablo: ttk.Treeview,
    basliklar: dict[str, str],
    get_filtre_dict: Callable[[], dict],
    set_filtre_dict: Callable[[dict], None] | None,
    yenile_cb: Callable[[], None],
    deger_listesi_cb: Callable[[], Iterable],
    *,
    parent=None,
    kolonlar: Sequence[str] | None = None,
    values_key: str | Callable = "values",
    haric_kolonlar: Sequence[str] | None = None,
    siralama_cb: Callable[[str], None] | None = None,
    sag_tik_filtre: bool | None = None,
    popup_ref_attr: str = "_kolon_filtre_popup",
    popup_owner=None,
) -> dict[str, Any]:
    """Treeview başlığına kolon hunisi bağlar (Excel benzeri ▾/▼).

    - ``siralama_cb`` yoksa: sol tık başlık → filtre popup (gelir_gider tarzı).
    - ``siralama_cb`` varsa veya ``sag_tik_filtre=True``: sol tık sıralar,
      sağ tık filtre açar (cari/fatura listeleri tarzı).

    ``set_filtre_dict`` None ise ``get_filtre_dict()`` dönen sözlük yerinde mutasyona
    uğrar (çoğu ekranda yeterli).

    Dönüş: ``guncelle_basliklar``, ``uygula``, ``temizle``, ``temizle_hepsi``,
    ``filtre_aktif``, ``kolonlar``.
    """
    kolon_listesi = list(kolonlar) if kolonlar is not None else list(basliklar.keys())
    haric = set(haric_kolonlar or ())
    sahibi = popup_owner if popup_owner is not None else parent
    if sahibi is None:
        try:
            sahibi = tablo.winfo_toplevel()
        except tk.TclError:
            sahibi = tablo
    parent_win = parent if parent is not None else sahibi
    sag_tik = bool(sag_tik_filtre) if sag_tik_filtre is not None else (siralama_cb is not None)

    def _filtre() -> dict:
        return get_filtre_dict() or {}

    def _yaz(yeni: dict) -> None:
        if set_filtre_dict is not None:
            set_filtre_dict(yeni)
        else:
            mevcut = get_filtre_dict()
            if mevcut is not yeni:
                mevcut.clear()
                mevcut.update(yeni)

    def guncelle_basliklar(siralama: tuple[str, bool] | None = None) -> None:
        filtre = _filtre()
        for kolon in kolon_listesi:
            if kolon in haric:
                continue
            baslik = basliklar.get(kolon, kolon)
            try:
                kwargs: dict[str, Any] = {
                    "text": baslik_filtre_metni(
                        baslik,
                        filtre_aktif=kolon in filtre,
                        siralama=siralama,
                        kolon=kolon,
                    )
                }
                if siralama_cb is not None:
                    kwargs["command"] = lambda c=kolon: siralama_cb(c)
                tablo.heading(kolon, **kwargs)
            except tk.TclError:
                pass

    def uygula(kolon: str, secilen: set) -> None:
        f = dict(_filtre())
        adaylar = list(deger_listesi_cb() or [])
        try:
            idx = kolon_listesi.index(kolon)
        except ValueError:
            return
        tum = kolon_benzersiz_degerler(adaylar, idx, values_key=values_key)
        if not secilen:
            f[kolon] = set()
        elif tum and secilen >= tum:
            f.pop(kolon, None)
        else:
            f[kolon] = set(secilen)
        _yaz(f)
        yenile_cb()

    def temizle(kolon: str) -> None:
        f = dict(_filtre())
        f.pop(kolon, None)
        _yaz(f)
        yenile_cb()

    def temizle_hepsi() -> None:
        _yaz({})
        yenile_cb()

    def _popup_ac(kolon: str) -> None:
        if kolon in haric:
            return
        kolon_filtre_popup_ac(
            parent_win,
            tablo,
            kolon,
            kolon_listesi,
            basliklar,
            _filtre(),
            deger_listesi_cb() or [],
            uygula_cb=uygula,
            temizle_cb=temizle,
            values_key=values_key,
            popup_ref_attr=popup_ref_attr,
            popup_owner=sahibi,
        )

    def _baslik_tik(event):
        kolon = heading_kolon_bul(tablo, event, kolon_listesi)
        if not kolon or kolon in haric:
            return
        _popup_ac(kolon)
        return "break"

    # Yeniden bağlama: önceki hunisi callback'ini değiştir (unbind seçimi bozar)
    seq = "<Button-3>" if sag_tik else "<Button-1>"
    attr = "_liste_filtre_bind_seq"
    onceki = getattr(tablo, attr, None)
    if onceki and onceki != seq:
        # Eski moda geçişte yalnızca bizim eklediğimiz binding id'sini kaldır
        bid = getattr(tablo, "_liste_filtre_bind_id", None)
        if bid:
            try:
                tablo.unbind(onceki, bid)
            except tk.TclError:
                pass
    bid_eski = getattr(tablo, "_liste_filtre_bind_id", None)
    if bid_eski and onceki == seq:
        try:
            tablo.unbind(seq, bid_eski)
        except tk.TclError:
            pass
    bind_id = tablo.bind(seq, _baslik_tik, add="+")
    setattr(tablo, attr, seq)
    setattr(tablo, "_liste_filtre_bind_id", bind_id)

    guncelle_basliklar()
    return {
        "guncelle_basliklar": guncelle_basliklar,
        "uygula": uygula,
        "temizle": temizle,
        "temizle_hepsi": temizle_hepsi,
        "filtre_aktif": lambda: len(_filtre()),
        "kolonlar": kolon_listesi,
        "popup_ac": _popup_ac,
    }


# ---------------------------------------------------------------------------
# UI satır oluşturucular
# ---------------------------------------------------------------------------

def tarih_aralik_ekle(
    parent,
    *,
    etiket: str = "Tarih:",
    bas_deger: str = "",
    bit_deger: str = "",
    on_select=None,
    pack_side: str = "left",
) -> tuple[ttk.Entry, ttk.Entry]:
    from ui_takvim import takvim_butonu

    ttk.Label(parent, text=etiket).pack(side=pack_side)
    bas_fr = ttk.Frame(parent)
    bas_fr.pack(side=pack_side, padx=(4, 2))
    bas = ttk.Entry(bas_fr, width=10)
    bas.pack(side="left")
    if bas_deger:
        bas.insert(0, bas_deger)
    takvim_butonu(bas_fr, bas, on_select=on_select)
    ttk.Label(parent, text="–").pack(side=pack_side, padx=2)
    bit_fr = ttk.Frame(parent)
    bit_fr.pack(side=pack_side, padx=(2, 8))
    bit = ttk.Entry(bit_fr, width=10)
    bit.pack(side="left")
    if bit_deger:
        bit.insert(0, bit_deger)
    takvim_butonu(bit_fr, bit, on_select=on_select)
    return bas, bit


def tutar_aralik_ekle(
    parent,
    *,
    etiket: str = "Tutar:",
    on_change=None,
    pack_side: str = "left",
) -> tuple[ttk.Entry, ttk.Entry]:
    ttk.Label(parent, text=etiket).pack(side=pack_side, padx=(8, 2))
    tmin = ttk.Entry(parent, width=8)
    tmin.pack(side=pack_side)
    ttk.Label(parent, text="–").pack(side=pack_side)
    tmax = ttk.Entry(parent, width=8)
    tmax.pack(side=pack_side, padx=(0, 4))
    if on_change:
        tmin.bind("<KeyRelease>", lambda _e: on_change())
        tmax.bind("<KeyRelease>", lambda _e: on_change())
        tmin.bind("<Return>", lambda _e: on_change())
        tmax.bind("<Return>", lambda _e: on_change())
    return tmin, tmax


def sayfa_cubugu_ekle(
    parent,
    *,
    onceki_cb,
    sonraki_cb,
    ozet_var_or_label=None,
) -> ttk.Label:
    """◀ / ▶ + özet etiketi. Dönüş: özet Label."""
    ozet = ttk.Label(parent, text="")
    ozet.pack(side="left")
    ttk.Button(parent, text="◀", width=3, command=onceki_cb).pack(side="left", padx=(12, 2))
    ttk.Button(parent, text="▶", width=3, command=sonraki_cb).pack(side="left")
    return ozet


def sayfa_bilgi_metni(toplam: int, sayfa: int, sayfa_boyutu: int) -> str:
    if toplam <= 0:
        return "0 kayıt"
    sayfa_sayisi = max(1, math.ceil(toplam / sayfa_boyutu))
    mevcut = min(sayfa + 1, sayfa_sayisi)
    return f"{toplam} kayıt  |  Sayfa {mevcut}/{sayfa_sayisi}"


def sayfa_dilim(satirlar: Sequence, sayfa: int, sayfa_boyutu: int) -> list:
    if sayfa_boyutu <= 0:
        return list(satirlar)
    bas = sayfa * sayfa_boyutu
    return list(satirlar[bas : bas + sayfa_boyutu])


# ---------------------------------------------------------------------------
# Alt toplam Treeview
# ---------------------------------------------------------------------------

def toplam_satiri_kur(
    parent,
    kolonlar: Sequence[str],
    kolon_duzen: dict[str, tuple[int, str]] | None = None,
    *,
    stretch_kolon: str | None = None,
    height: int = 1,
) -> ttk.Treeview:
    """Ana tablo altına hizalı Σ satırı Treeview'ı."""
    tv = ttk.Treeview(parent, columns=list(kolonlar), show="headings", height=height, selectmode="none")
    for kolon in kolonlar:
        genislik, hiza = (100, "w")
        if kolon_duzen and kolon in kolon_duzen:
            genislik, hiza = kolon_duzen[kolon]
        tv.heading(kolon, text="", anchor="center")
        tv.column(
            kolon,
            width=genislik,
            minwidth=40,
            anchor=hiza,
            stretch=(stretch_kolon is not None and kolon == stretch_kolon),
        )
    tv.tag_configure("toplam", background="#fff8e1", font=("Segoe UI", 9, "bold"))
    return tv


def toplam_genislikleri_esitle(ana: ttk.Treeview, toplam: ttk.Treeview, kolonlar: Sequence[str]):
    for kolon in kolonlar:
        try:
            genislik = ana.column(kolon, "width")
            hiza = ana.column(kolon, "anchor")
            toplam.column(kolon, width=genislik, anchor=hiza)
        except tk.TclError:
            pass


def toplam_satiri_yaz(
    toplam_tv: ttk.Treeview,
    kolonlar: Sequence[str],
    degerler: dict[str, str],
    *,
    iid: str = "toplam",
):
    satir = [degerler.get(k, "") for k in kolonlar]
    for item in toplam_tv.get_children():
        toplam_tv.delete(item)
    toplam_tv.insert("", "end", iid=iid, values=tuple(satir), tags=("toplam",))


def filtre_ozet_metni(
    *,
    gorunen: int,
    toplam: int,
    aktif_filtre: int = 0,
    ekstra: Sequence[str] | None = None,
) -> str:
    if aktif_filtre or (ekstra and any(ekstra)):
        parcalar = [f"Gösterilen: {gorunen} / {toplam}"]
    else:
        parcalar = [f"Toplam: {toplam}"]
    if aktif_filtre:
        parcalar.append(f"Aktif filtre: {aktif_filtre}")
    if ekstra:
        parcalar.extend([e for e in ekstra if e])
    return "  |  ".join(parcalar)


# ---------------------------------------------------------------------------
# DOC5: Kayıtlı görünüm (kullanıcı + firma + rapor anahtarı)
# ---------------------------------------------------------------------------

_GORUNUM_AD_RE = re.compile(r"^[\w \-ğüşıöçĞÜŞİÖÇ.]{1,80}$", re.UNICODE)

# Yürüyen / saklı bakiye kolonları — istatistik toplamına girmez (DOC5)
YURIYEN_BAKIYE_KOLONLAR = frozenset({
    "bakiye",
    "tl_bakiye",
    "usd_bakiye",
    "kalan",
    "fifo_kalan",
    "donem_sonu_bakiye",
    "devir",
    "acilış",
    "acilis",
    "running_balance",
})

IST_TOPLAM = "toplam"
IST_MAKS = "maks"
IST_MIN = "min"
IST_ORTALAMA = "ortalama"
IST_SATIR = "satir"
IST_ETIKET = {
    IST_TOPLAM: "Alt Toplam",
    IST_MAKS: "Maks",
    IST_MIN: "Min",
    IST_ORTALAMA: "Ortalama",
    IST_SATIR: "Satır Sayısı",
}


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


def _guvenli_parca(metin: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in str(metin or "0"))


def ayarlar_klasoru() -> Path:
    base = (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        / "MuhasebeProgrami"
        / "ayarlar"
    )
    base.mkdir(parents=True, exist_ok=True)
    return base


def kayitli_gorunum_dosyasi(rapor_anahtari: str) -> Path:
    """%LOCALAPPDATA%\\MuhasebeProgrami\\ayarlar\\gorunum_{rapor}_f{firma}_u{user}.json"""
    firma, kullanici = _ayar_kimlik()
    ad = (
        f"gorunum_{_guvenli_parca(rapor_anahtari)}"
        f"_f{_guvenli_parca(firma)}_u{_guvenli_parca(kullanici)}.json"
    )
    return ayarlar_klasoru() / ad


def _filtre_json_uyumlu(filtre: dict) -> dict:
    """set → list; görünüm dosyasına yazılabilir hale getirir."""
    sonuc: dict[str, Any] = {}
    for k, v in (filtre or {}).items():
        if isinstance(v, set):
            sonuc[k] = sorted(str(x) for x in v)
        elif isinstance(v, (list, tuple)):
            sonuc[k] = list(v)
        else:
            sonuc[k] = v
    return sonuc


def _filtre_set_geri(filtre: dict) -> dict[str, set[str]]:
    """JSON listelerini kolon hunisi set'lerine çevirir."""
    sonuc: dict[str, set[str]] = {}
    for k, v in (filtre or {}).items():
        if isinstance(v, set):
            sonuc[str(k)] = {str(x) for x in v}
        elif isinstance(v, (list, tuple)):
            sonuc[str(k)] = {str(x) for x in v}
        elif v is None:
            continue
        else:
            sonuc[str(k)] = {str(v)}
    return sonuc


def kayitli_gorunumleri_yukle(rapor_anahtari: str) -> dict[str, dict]:
    yol = kayitli_gorunum_dosyasi(rapor_anahtari)
    if not yol.exists():
        return {}
    try:
        ham = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(ham, dict):
        return {}
    gorunumler = ham.get("gorunumler")
    return dict(gorunumler) if isinstance(gorunumler, dict) else {}


def kayitli_gorunumleri_yaz(rapor_anahtari: str, gorunumler: dict[str, dict]) -> Path:
    yol = kayitli_gorunum_dosyasi(rapor_anahtari)
    firma, kullanici = _ayar_kimlik()
    paket = {
        "rapor": rapor_anahtari,
        "firma_id": str(firma),
        "kullanici_id": str(kullanici),
        "gorunumler": gorunumler,
    }
    yol.write_text(json.dumps(paket, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return yol


def kayitli_gorunum_listele(rapor_anahtari: str) -> list[str]:
    return sorted(kayitli_gorunumleri_yukle(rapor_anahtari).keys(), key=str.casefold)


def kayitli_gorunum_kaydet(rapor_anahtari: str, ad: str, durum: dict) -> None:
    ad = (ad or "").strip()
    if not ad or not _GORUNUM_AD_RE.match(ad):
        raise ValueError("Görünüm adı 1–80 karakter olmalı (harf, rakam, boşluk, -._).")
    paket = dict(durum or {})
    if "filtreler" in paket and isinstance(paket["filtreler"], dict):
        paket["filtreler"] = _filtre_json_uyumlu(paket["filtreler"])
    if "kolon_filtre" in paket and isinstance(paket["kolon_filtre"], dict):
        # tablo → kolon → set
        paket["kolon_filtre"] = {
            t: _filtre_json_uyumlu(f) if isinstance(f, dict) else f
            for t, f in paket["kolon_filtre"].items()
        }
    gorunumler = kayitli_gorunumleri_yukle(rapor_anahtari)
    gorunumler[ad] = paket
    kayitli_gorunumleri_yaz(rapor_anahtari, gorunumler)


def kayitli_gorunum_yukle(rapor_anahtari: str, ad: str) -> dict | None:
    ad = (ad or "").strip()
    ham = kayitli_gorunumleri_yukle(rapor_anahtari).get(ad)
    if not isinstance(ham, dict):
        return None
    paket = dict(ham)
    if "filtreler" in paket and isinstance(paket["filtreler"], dict):
        # Kriter paneli değerleri set değil; olduğu gibi bırak
        pass
    if "kolon_filtre" in paket and isinstance(paket["kolon_filtre"], dict):
        paket["kolon_filtre"] = {
            str(t): _filtre_set_geri(f) if isinstance(f, dict) else {}
            for t, f in paket["kolon_filtre"].items()
        }
    return paket


def kayitli_gorunum_sil(rapor_anahtari: str, ad: str) -> bool:
    ad = (ad or "").strip()
    gorunumler = kayitli_gorunumleri_yukle(rapor_anahtari)
    if ad not in gorunumler:
        return False
    del gorunumler[ad]
    kayitli_gorunumleri_yaz(rapor_anahtari, gorunumler)
    return True


def kayitli_gorunum_arac_cubugu(
    parent,
    rapor_anahtari: str,
    *,
    get_durum: Callable[[], dict],
    uygula_durum: Callable[[dict], None],
    pack_side: str = "left",
) -> dict[str, Any]:
    """Kaydet / Yükle / Sil araç çubuğu. Dönüş: widget referansları + yenile()."""
    cerceve = ttk.Frame(parent)
    cerceve.pack(side=pack_side, padx=(8, 0))
    ttk.Label(cerceve, text="Görünüm:").pack(side="left")
    combo = ttk.Combobox(cerceve, width=18, state="readonly")
    combo.pack(side="left", padx=4)

    def yenile_liste(secili: str | None = None) -> None:
        adlar = kayitli_gorunum_listele(rapor_anahtari)
        combo.configure(values=adlar)
        if secili and secili in adlar:
            combo.set(secili)
        elif adlar:
            if combo.get() not in adlar:
                combo.set(adlar[0])
        else:
            combo.set("")

    def kaydet() -> None:
        mevcut = combo.get().strip()
        dlg = tk.Toplevel(parent)
        dlg.title("Görünüm kaydet")
        dlg.transient(parent.winfo_toplevel())
        dlg.resizable(False, False)
        ttk.Label(dlg, text="Görünüm adı:").pack(padx=10, pady=(10, 2), anchor="w")
        ent = ttk.Entry(dlg, width=32)
        ent.pack(padx=10, pady=2)
        if mevcut:
            ent.insert(0, mevcut)
        ent.focus_set()

        def onay() -> None:
            ad = ent.get().strip()
            try:
                kayitli_gorunum_kaydet(rapor_anahtari, ad, get_durum())
            except ValueError as hata:
                messagebox.showwarning("Görünüm", str(hata), parent=dlg)
                return
            yenile_liste(ad)
            dlg.destroy()

        alt = ttk.Frame(dlg, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="Kaydet", command=onay).pack(side="left")
        ttk.Button(alt, text="İptal", command=dlg.destroy).pack(side="right")
        dlg.bind("<Return>", lambda _e: onay())
        dlg.bind("<Escape>", lambda _e: dlg.destroy())

    def yukle() -> None:
        ad = combo.get().strip()
        if not ad:
            messagebox.showinfo("Görünüm", "Yüklenecek kayıtlı görünüm yok.", parent=parent)
            return
        durum = kayitli_gorunum_yukle(rapor_anahtari, ad)
        if durum is None:
            messagebox.showwarning("Görünüm", "Görünüm bulunamadı.", parent=parent)
            yenile_liste()
            return
        uygula_durum(durum)

    def sil() -> None:
        ad = combo.get().strip()
        if not ad:
            return
        if not messagebox.askyesno("Görünüm", f"«{ad}» silinsin mi?", parent=parent):
            return
        kayitli_gorunum_sil(rapor_anahtari, ad)
        yenile_liste()

    ttk.Button(cerceve, text="Kaydet", command=kaydet).pack(side="left", padx=2)
    ttk.Button(cerceve, text="Yükle", command=yukle).pack(side="left", padx=2)
    ttk.Button(cerceve, text="Sil", command=sil).pack(side="left", padx=2)
    yenile_liste()
    return {"cerceve": cerceve, "combo": combo, "yenile": yenile_liste}


# ---------------------------------------------------------------------------
# DOC5: Seçilebilir istatistikler (Alt Toplam / Maks / Min / Ortalama / Satır)
# ---------------------------------------------------------------------------

def kolon_istatistik_uygun_mu(
    kolon: str,
    *,
    tip: str | None = None,
    yuruyen_haric: Iterable[str] | None = None,
) -> bool:
    """Yürüyen bakiye / kimlik / oran kolonlarında Alt Toplam üretme."""
    k = (kolon or "").casefold()
    haric = set(YURIYEN_BAKIYE_KOLONLAR) | {x.casefold() for x in (yuruyen_haric or ())}
    if k in haric or kolon in YURIYEN_BAKIYE_KOLONLAR:
        return False
    if tip in ("metin", "tarih", "kod", "durum"):
        return False
    if tip in ("para", "miktar", "fiyat", "yuzde", "gun", "gun1", "oran", "sayi", "tutar"):
        # birim fiyat / kur / yüzde için yalnız maks/min/ort anlamlı; toplam UI'da seçilebilir
        # ama varsayılan toplam yalnızca para/miktar
        return True
    # tip bilinmiyorsa isim sezgisel
    if any(x in k for x in ("kod", "ad", "unvan", "aciklama", "tarih", "durum", "birim", "kur")):
        return False
    return tip is None


def kolon_varsayilan_istatistik(kolon: str, tip: str | None = None) -> str | None:
    """Varsayılan özet: para/miktar → Alt Toplam; diğer sayısal → Yok."""
    if not kolon_istatistik_uygun_mu(kolon, tip=tip):
        return None
    if tip in ("para", "miktar", "tutar", "sayi") or tip is None:
        k = (kolon or "").casefold()
        if any(x in k for x in ("fiyat", "kur", "oran", "yuzde", "marj", "%")):
            return None
        if tip in ("fiyat", "yuzde", "oran", "gun1"):
            return None
        return IST_TOPLAM
    return None


def _sayisal_degerler(degerler: Iterable) -> list[Decimal]:
    sonuc: list[Decimal] = []
    for d in degerler:
        if d is None or d == "":
            continue
        if isinstance(d, Decimal):
            sonuc.append(d)
            continue
        if isinstance(d, (int, float)):
            sonuc.append(Decimal(str(d)))
            continue
        parsed = tutar_oku(d)
        if parsed is not None:
            sonuc.append(parsed)
    return sonuc


def istatistik_hesapla(
    degerler: Iterable,
    tur: str,
    *,
    satir_sayisi: int | None = None,
) -> Decimal | int | None:
    """
    tur: toplam | maks | min | ortalama | satir
    Boşta: toplam/satır → 0; maks/min/ort → None (UI «Veri yok»).
    """
    if tur == IST_SATIR:
        if satir_sayisi is not None:
            return int(satir_sayisi)
        return len([d for d in degerler if d is not None and d != ""])
    sayilar = _sayisal_degerler(degerler)
    if tur == IST_TOPLAM:
        return sum(sayilar, Decimal("0"))
    if not sayilar:
        return None
    if tur == IST_MAKS:
        return max(sayilar)
    if tur == IST_MIN:
        return min(sayilar)
    if tur == IST_ORTALAMA:
        return sum(sayilar, Decimal("0")) / Decimal(len(sayilar))
    raise ValueError(f"Bilinmeyen istatistik: {tur}")


def istatistik_metni(deger: Decimal | int | None, tur: str) -> str:
    if tur == IST_SATIR:
        return str(int(deger or 0))
    if deger is None:
        return "Veri yok"
    if isinstance(deger, int):
        return str(deger)
    return para_goster_tr(deger)


def istatistik_seridi_ekle(
    parent,
    *,
    kolon_tanim: Sequence[tuple[str, str, str | None]],
    get_satirlar: Callable[[], Sequence[dict]],
    deger_al: Callable[[dict, str], Any] | None = None,
    varsayilan: dict[str, str | None] | None = None,
    yuruyen_haric: Iterable[str] | None = None,
    pack_opts: dict | None = None,
) -> dict[str, Any]:
    """Alt şerit: kolon başına istatistik seçimi + özet metni.

    kolon_tanim: [(anahtar, baslik, tip), ...]
    """
    uygun = [
        (a, b, t)
        for a, b, t in kolon_tanim
        if kolon_istatistik_uygun_mu(a, tip=t, yuruyen_haric=yuruyen_haric)
    ]
    secimler: dict[str, str | None] = {}
    for a, _b, t in uygun:
        if varsayilan and a in varsayilan:
            secimler[a] = varsayilan[a]
        else:
            secimler[a] = kolon_varsayilan_istatistik(a, t)
    baslangic_varsayilan = dict(secimler)

    cerceve = ttk.Frame(parent)
    po = {"fill": "x", "padx": 8, "pady": (2, 4)}
    if pack_opts:
        po.update(pack_opts)
    cerceve.pack(**po)

    ust = ttk.Frame(cerceve)
    ust.pack(fill="x")
    ttk.Label(ust, text="İstatistik:").pack(side="left")
    ozet = ttk.Label(ust, text="", foreground="#1a237e")
    ozet.pack(side="left", padx=8)

    def _deger(satir: dict, kolon: str):
        if deger_al:
            return deger_al(satir, kolon)
        return satir.get(kolon)

    def guncelle(_event=None) -> str:
        satirlar = [
            s for s in (get_satirlar() or [])
            if not (isinstance(s, dict) and s.get("_sabit"))
        ]
        parcalar = []
        for a, b, _t in uygun:
            tur = secimler.get(a)
            if not tur:
                continue
            degerler = [_deger(s, a) for s in satirlar]
            sonuc = istatistik_hesapla(degerler, tur, satir_sayisi=len(satirlar))
            parcalar.append(f"{b} {IST_ETIKET.get(tur, tur)}: {istatistik_metni(sonuc, tur)}")
        metin = "  |  ".join(parcalar) if parcalar else "İstatistik seçilmedi"
        ozet.configure(text=metin)
        return metin

    def _menu_ac() -> None:
        pop = tk.Toplevel(parent)
        pop.title("İstatistik seç")
        pop.transient(parent.winfo_toplevel())
        pop.resizable(False, True)
        govde = ttk.Frame(pop, padding=8)
        govde.pack(fill="both", expand=True)
        degiskenler: dict[str, tk.StringVar] = {}
        secenekler = [("(Yok)", "")] + [(IST_ETIKET[k], k) for k in (
            IST_TOPLAM, IST_MAKS, IST_MIN, IST_ORTALAMA, IST_SATIR
        )]
        for i, (a, b, _t) in enumerate(uygun):
            ttk.Label(govde, text=b).grid(row=i, column=0, sticky="w", padx=4, pady=2)
            var = tk.StringVar(value=secimler.get(a) or "")
            degiskenler[a] = var
            cb = ttk.Combobox(
                govde,
                values=[e for e, _v in secenekler],
                state="readonly",
                width=14,
            )
            etiket = next((e for e, v in secenekler if v == (secimler.get(a) or "")), "(Yok)")
            cb.set(etiket)
            cb._secenekler = secenekler
            cb.grid(row=i, column=1, sticky="w", padx=4, pady=2)
            degiskenler[a] = cb  # type: ignore[assignment]

        def uygula() -> None:
            for a, _b, _t in uygun:
                w = degiskenler[a]
                etiket = w.get()
                secimler[a] = next((v for e, v in w._secenekler if e == etiket), None) or None
            guncelle()
            pop.destroy()

        def temizle() -> None:
            for a, _b, _t in uygun:
                secimler[a] = None
            guncelle()
            pop.destroy()

        def varsayilana() -> None:
            secimler.clear()
            secimler.update(baslangic_varsayilan)
            guncelle()
            pop.destroy()

        alt = ttk.Frame(pop, padding=8)
        alt.pack(fill="x")
        ttk.Button(alt, text="Uygula", command=uygula).pack(side="left")
        ttk.Button(alt, text="Temizle", command=temizle).pack(side="left", padx=4)
        ttk.Button(alt, text="Varsayılana dön", command=varsayilana).pack(side="left", padx=4)
        ttk.Button(alt, text="Kapat", command=pop.destroy).pack(side="right")

    ttk.Button(ust, text="Seç…", command=_menu_ac).pack(side="left")
    ttk.Button(ust, text="Temizle", command=lambda: (
        secimler.update({a: None for a, _b, _t in uygun}), guncelle()
    )).pack(side="left", padx=4)
    ttk.Button(ust, text="Varsayılan", command=lambda: (
        secimler.clear(), secimler.update(baslangic_varsayilan), guncelle()
    )).pack(side="left")

    guncelle()
    return {
        "cerceve": cerceve,
        "ozet": ozet,
        "secimler": secimler,
        "guncelle": guncelle,
        "uygun_kolonlar": [a for a, _b, _t in uygun],
    }


# ---------------------------------------------------------------------------
# DOC5: Sütun sabitleme (ttk Twin-Treeview — gerçek dondurma yok)
# ---------------------------------------------------------------------------

def kimlik_kolonlari_sec(
    kolonlar: Sequence[str],
    *,
    tip_map: dict[str, str] | None = None,
    en_fazla: int = 2,
) -> list[str]:
    """İlk 1–2 metin/kimlik kolonunu sabitleme adayı olarak seçer."""
    tip_map = tip_map or {}
    aday: list[str] = []
    for k in kolonlar:
        tip = tip_map.get(k, "metin")
        if tip in ("para", "miktar", "fiyat", "yuzde", "gun", "gun1", "oran", "sayi", "tutar"):
            continue
        if k.casefold() in YURIYEN_BAKIYE_KOLONLAR:
            continue
        aday.append(k)
        if len(aday) >= en_fazla:
            break
    return aday


def treeview_yscroll_senkron(sol: ttk.Treeview, sag: ttk.Treeview, scrollbar: ttk.Scrollbar) -> None:
    """İki Treeview dikey kaydırmasını ortak scrollbar ile senkronlar."""

    def _set(*args):
        scrollbar.set(*args)
        # Diğer ağacı aynı konuma çek
        try:
            sol.yview_moveto(args[0])
            sag.yview_moveto(args[0])
        except (tk.TclError, IndexError):
            pass

    def _yview(*args):
        sol.yview(*args)
        sag.yview(*args)

    scrollbar.configure(command=_yview)
    sol.configure(yscrollcommand=_set)
    sag.configure(yscrollcommand=_set)

    def _teker(event, hedef=None):
        delta = -1 if getattr(event, "delta", 0) > 0 else 1
        if hasattr(event, "num"):
            if event.num == 4:
                delta = -1
            elif event.num == 5:
                delta = 1
        sol.yview_scroll(delta, "units")
        sag.yview_scroll(delta, "units")
        return "break"

    for tv in (sol, sag):
        tv.bind("<MouseWheel>", _teker, add="+")
        tv.bind("<Button-4>", _teker, add="+")
        tv.bind("<Button-5>", _teker, add="+")


class SolSabitTablo:
    """Sol 1–2 kolon sabit; sağ kalan kolonlar yatay kayar (ttk klonlama).

    Not: ttk.Treeview native freeze desteklemez; bu sınıf pratik sol sabitlemedir.
    ``ana_tablo`` sağdaki kaydırılabilir Treeview'dır (filtre/sıralama bağları buraya).
    """

    def __init__(
        self,
        parent,
        *,
        sabit_kolonlar: Sequence[str],
        diger_kolonlar: Sequence[str],
        basliklar: dict[str, str],
        genislikler: dict[str, int] | None = None,
        hizalar: dict[str, str] | None = None,
        selectmode: str = "browse",
        style: str | None = None,
    ):
        self.sabit_kolonlar = list(sabit_kolonlar)
        self.diger_kolonlar = list(diger_kolonlar)
        self.tum_kolonlar = self.sabit_kolonlar + self.diger_kolonlar
        self.basliklar = basliklar
        genislikler = genislikler or {}
        hizalar = hizalar or {}

        self.cerceve = ttk.Frame(parent)
        self.cerceve.rowconfigure(0, weight=1)
        self.cerceve.columnconfigure(1, weight=1)

        sol_fr = ttk.Frame(self.cerceve)
        sol_fr.grid(row=0, column=0, sticky="nsw")
        sag_fr = ttk.Frame(self.cerceve)
        sag_fr.grid(row=0, column=1, sticky="nsew")
        sag_fr.rowconfigure(0, weight=1)
        sag_fr.columnconfigure(0, weight=1)

        kw = {"show": "headings", "selectmode": selectmode, "height": 16}
        if style:
            kw["style"] = style
        self.sol = ttk.Treeview(sol_fr, columns=self.sabit_kolonlar, **kw)
        self.sag = ttk.Treeview(sag_fr, columns=self.diger_kolonlar, **kw)
        self.ana_tablo = self.sag

        for k in self.sabit_kolonlar:
            self.sol.heading(k, text=basliklar.get(k, k))
            self.sol.column(
                k,
                width=genislikler.get(k, 100),
                minwidth=40,
                stretch=False,
                anchor=hizalar.get(k, "w"),
            )
        for k in self.diger_kolonlar:
            self.sag.heading(k, text=basliklar.get(k, k))
            self.sag.column(
                k,
                width=genislikler.get(k, 100),
                minwidth=40,
                stretch=False,
                anchor=hizalar.get(k, "w"),
            )

        dikey = ttk.Scrollbar(self.cerceve, orient="vertical")
        dikey.grid(row=0, column=2, sticky="ns")
        treeview_yscroll_senkron(self.sol, self.sag, dikey)
        yatay = ttk.Scrollbar(sag_fr, orient="horizontal", command=self.sag.xview)
        self.sag.configure(xscrollcommand=yatay.set)
        self.sol.pack(fill="y", expand=False)
        self.sag.grid(row=0, column=0, sticky="nsew")
        yatay.grid(row=1, column=0, sticky="ew")

        def _secim_aktar(kaynak, hedef, _event=None):
            try:
                hedef.selection_set(kaynak.selection())
            except tk.TclError:
                pass

        self.sol.bind("<<TreeviewSelect>>", lambda e: _secim_aktar(self.sol, self.sag, e), add="+")
        self.sag.bind("<<TreeviewSelect>>", lambda e: _secim_aktar(self.sag, self.sol, e), add="+")

    def pack(self, **kw):
        self.cerceve.pack(**kw)
        return self

    def grid(self, **kw):
        self.cerceve.grid(**kw)
        return self

    def temizle(self) -> None:
        self.sol.delete(*self.sol.get_children())
        self.sag.delete(*self.sag.get_children())

    def satir_ekle(self, iid: str, values_map: dict[str, Any], *, tags: Sequence[str] = ()) -> None:
        sol_vals = tuple(values_map.get(k, "") for k in self.sabit_kolonlar)
        sag_vals = tuple(values_map.get(k, "") for k in self.diger_kolonlar)
        self.sol.insert("", "end", iid=iid, values=sol_vals, tags=tuple(tags))
        self.sag.insert("", "end", iid=iid, values=sag_vals, tags=tuple(tags))

    def baslik_guncelle(self, kolon: str, text: str, **heading_kw) -> None:
        tv = self.sol if kolon in self.sabit_kolonlar else self.sag
        try:
            tv.heading(kolon, text=text, **heading_kw)
        except tk.TclError:
            pass


# ---------------------------------------------------------------------------
# DOC5: Grup ağacı — aramalı çoklu seçim, üst → alt dahil
# ---------------------------------------------------------------------------

def grup_agacini_duzlestir(
    dugumler: Sequence[dict],
    *,
    id_key: str = "id",
    ad_key: str = "ad",
    cocuk_key: str = "cocuklar",
) -> list[dict]:
    """Ağacı {id, ad, parent_id, seviye, yol} satırlarına çevirir."""
    sonuc: list[dict] = []

    def gez(dugum: dict, parent_id, seviye: int, yol: str) -> None:
        did = dugum.get(id_key)
        ad = dugum.get(ad_key) or dugum.get("kod") or str(did)
        yol_yeni = f"{yol} / {ad}" if yol else str(ad)
        sonuc.append({
            "id": did,
            "ad": ad,
            "parent_id": parent_id,
            "seviye": seviye,
            "yol": yol_yeni,
            "cocuklar": dugum.get(cocuk_key) or [],
        })
        for c in dugum.get(cocuk_key) or []:
            gez(c, did, seviye + 1, yol_yeni)

    for d in dugumler or []:
        gez(d, None, 0, "")
    return sonuc


def grup_alt_idler(
    dugumler: Sequence[dict],
    secili_idler: Iterable,
    *,
    id_key: str = "id",
    cocuk_key: str = "cocuklar",
) -> set:
    """Seçilen düğüm + tüm alt düğüm id'leri (parent-includes-children)."""
    istenen = {x for x in secili_idler if x is not None and x != ""}
    # normalize int where possible
    norm: set = set()
    for x in istenen:
        try:
            norm.add(int(x))
        except (TypeError, ValueError):
            norm.add(x)
    sonuc: set = set()

    def gez(dugum: dict, ata_secili: bool) -> None:
        did = dugum.get(id_key)
        try:
            did_n = int(did) if did is not None else did
        except (TypeError, ValueError):
            did_n = did
        secili = ata_secili or did_n in norm or did in norm
        if secili and did is not None:
            sonuc.add(did_n)
        for c in dugum.get(cocuk_key) or []:
            gez(c, secili)

    for d in dugumler or []:
        gez(d, False)
    return sonuc


class GrupAgaciSecici(tk.Toplevel):
    """Aramalı, çoklu seçimli grup ağacı; üst seçimi altları kapsar."""

    def __init__(
        self,
        parent,
        dugumler: Sequence[dict],
        *,
        baslik: str = "Grup seç",
        secili: Iterable | None = None,
        uygula_cb: Callable[[set], None] | None = None,
        id_key: str = "id",
        ad_key: str = "ad",
        cocuk_key: str = "cocuklar",
    ):
        super().__init__(parent)
        self.title(baslik)
        self.transient(parent)
        self.resizable(True, True)
        self.uygula_cb = uygula_cb
        self._dugumler = list(dugumler or [])
        self._id_key = id_key
        self._ad_key = ad_key
        self._cocuk_key = cocuk_key
        self._degiskenler: dict[Any, tk.BooleanVar] = {}
        self._satirlar: list[tuple[Any, ttk.Frame, str]] = []

        ust = ttk.Frame(self, padding=8)
        ust.pack(fill="x")
        ttk.Label(ust, text="Ara:").pack(side="left")
        self.arama = ttk.Entry(ust, width=28)
        self.arama.pack(side="left", padx=(4, 0), fill="x", expand=True)
        self.arama.bind("<KeyRelease>", self._ara)

        btn_ust = ttk.Frame(self, padding=(8, 0))
        btn_ust.pack(fill="x")
        ttk.Button(btn_ust, text="Tümünü seç", command=self._hepsini_sec).pack(side="left")
        ttk.Button(btn_ust, text="Hiçbirini seçme", command=self._hicbirini_sec).pack(side="left", padx=6)

        orta = ttk.Frame(self, padding=8)
        orta.pack(fill="both", expand=True)
        canvas = tk.Canvas(orta, width=340, height=320, highlightthickness=0)
        scroll = ttk.Scrollbar(orta, orient="vertical", command=canvas.yview)
        self.liste = ttk.Frame(canvas)
        self.liste.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.liste, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        baslangic = set()
        for x in secili or ():
            try:
                baslangic.add(int(x))
            except (TypeError, ValueError):
                baslangic.add(x)

        duz = grup_agacini_duzlestir(
            self._dugumler, id_key=id_key, ad_key=ad_key, cocuk_key=cocuk_key
        )
        for kayit in duz:
            did = kayit["id"]
            try:
                did_n = int(did) if did is not None else did
            except (TypeError, ValueError):
                did_n = did
            var = tk.BooleanVar(value=did_n in baslangic or did in baslangic)
            self._degiskenler[did_n] = var
            satir = ttk.Frame(self.liste)
            satir.pack(fill="x", anchor="w")
            girinti = "  " * int(kayit["seviye"])
            etiket = f"{girinti}{kayit['ad']}"
            ttk.Checkbutton(satir, text=etiket, variable=var).pack(side="left", anchor="w")
            self._satirlar.append((did_n, satir, etiket))

        alt = ttk.Frame(self, padding=8)
        alt.pack(fill="x")
        ttk.Button(alt, text="Uygula", command=self._uygula).pack(side="left")
        ttk.Button(alt, text="Temizle", command=self._temizle).pack(side="left", padx=6)
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.arama.focus_set()

    def _ara(self, _event=None):
        q = turkce_normalize(self.arama.get().strip())
        for _did, satir, etiket in self._satirlar:
            if not q or q in turkce_normalize(etiket):
                satir.pack(fill="x", anchor="w")
            else:
                satir.pack_forget()

    def _hepsini_sec(self):
        for var in self._degiskenler.values():
            var.set(True)

    def _hicbirini_sec(self):
        for var in self._degiskenler.values():
            var.set(False)

    def _secili_idler(self) -> set:
        return {d for d, var in self._degiskenler.items() if var.get()}

    def _uygula(self):
        secilen = self._secili_idler()
        genis = grup_alt_idler(
            self._dugumler,
            secilen,
            id_key=self._id_key,
            cocuk_key=self._cocuk_key,
        )
        if self.uygula_cb:
            self.uygula_cb(genis if genis else secilen)
        self.destroy()

    def _temizle(self):
        if self.uygula_cb:
            self.uygula_cb(set())
        self.destroy()


def grup_agaci_filtre_ekle(
    parent,
    *,
    dugumler_cb: Callable[[], Sequence[dict]],
    get_secili: Callable[[], set | list | None],
    set_secili: Callable[[set], None],
    etiket: str = "Stok grubu",
    pack_side: str = "left",
) -> dict[str, Any]:
    """Kriter paneline aramalı grup seçici düğmesi ekler."""
    kutu = ttk.Frame(parent)
    kutu.pack(side=pack_side, padx=(0, 8))
    ttk.Label(kutu, text=etiket).pack(anchor="w")
    ozet = ttk.Label(kutu, text="(Tümü)", foreground="#667085")
    ozet.pack(side="left")

    def _ozet_yaz(secili: set | None = None) -> None:
        s = set(secili) if secili is not None else set(get_secili() or ())
        if not s:
            ozet.configure(text="(Tümü)")
        elif len(s) == 1:
            ozet.configure(text=f"1 grup")
        else:
            ozet.configure(text=f"{len(s)} grup")

    def ac() -> None:
        GrupAgaciSecici(
            parent.winfo_toplevel(),
            dugumler_cb() or [],
            secili=get_secili() or (),
            uygula_cb=lambda s: (set_secili(set(s)), _ozet_yaz(set(s))),
        )

    ttk.Button(kutu, text="Seç…", command=ac).pack(side="left", padx=4)
    _ozet_yaz()
    return {"cerceve": kutu, "ozet": ozet, "yenile_ozet": _ozet_yaz, "ac": ac}
