"""Teklif formu — ürün adı / hızlı arama açılır listesi."""

from __future__ import annotations

import threading
import tkinter as tk
from decimal import Decimal
from tkinter import ttk
from typing import Any, Callable


MIN_ARAMA_HARF = 3
DEBOUNCE_MS = 320
SONUC_LIMIT = 50


def _fmt_sayi(v) -> str:
    try:
        d = Decimal(str(v or 0))
    except Exception:
        return "0"
    s = f"{d:f}".rstrip("0").rstrip(".")
    return s or "0"


class TeklifUrunAramaPaneli:
    """Ürün Adı / Ara alanı + debounce + sonuç Toplevel + klavye navigasyonu."""

    def __init__(
        self,
        parent: tk.Misc,
        entry: ttk.Entry,
        *,
        depo_getter: Callable[[], str],
        maliyet_izinli: Callable[[], bool],
        on_select: Callable[[dict], None],
        arama_fn: Callable[..., dict],
        yetki_stok: Callable[[], bool] | None = None,
        yetki_manuel: Callable[[], bool] | None = None,
        on_stok_yeni: Callable[[], None] | None = None,
        on_manuel: Callable[[], None] | None = None,
        on_manuel_isim: Callable[[str], None] | None = None,
    ):
        self.parent = parent
        self.entry = entry
        self.depo_getter = depo_getter
        self.maliyet_izinli = maliyet_izinli
        self.on_select = on_select
        self.arama_fn = arama_fn
        self.yetki_stok = yetki_stok or (lambda: False)
        self.yetki_manuel = yetki_manuel or (lambda: False)
        self.on_stok_yeni = on_stok_yeni
        self.on_manuel = on_manuel
        self.on_manuel_isim = on_manuel_isim

        self._after_id: str | None = None
        self._arama_seq = 0
        self._sonuclar: list[dict] = []
        self._popup: tk.Toplevel | None = None
        self._tree: ttk.Treeview | None = None
        self._durum_lbl: ttk.Label | None = None
        self._secili_idx = -1

        self.hint = ttk.Label(
            parent,
            text="Ürün adından art arda en az 3 harf yazın",
            foreground="#64748B",
            font=("Segoe UI", 8),
        )

        entry.bind("<KeyRelease>", self._on_key_release, add="+")
        entry.bind("<Down>", self._ok_asagi, add="+")
        entry.bind("<Up>", self._ok_yukari, add="+")
        entry.bind("<Return>", self._enter, add="+")
        entry.bind("<Escape>", self._esc, add="+")
        entry.bind("<FocusOut>", self._focus_out, add="+")
        entry.bind("<Tab>", self._tab, add="+")

    def pack_hint(self, **kw):
        self.hint.pack(**kw)

    def temizle(self):
        self._iptal_debounce()
        self.entry.delete(0, "end")
        self._sonuclar = []
        self._secili_idx = -1
        self._popup_kapat()
        self.hint.configure(text="Ürün adından art arda en az 3 harf yazın", foreground="#64748B")

    def _iptal_debounce(self):
        if self._after_id is not None:
            try:
                self.parent.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _on_key_release(self, event=None):
        if event and event.keysym in (
            "Up",
            "Down",
            "Return",
            "Escape",
            "Tab",
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
            "Alt_L",
            "Alt_R",
        ):
            return
        metin = self.entry.get().strip()
        self._iptal_debounce()
        if not metin:
            self._sonuclar = []
            self._secili_idx = -1
            self._popup_kapat()
            self.hint.configure(
                text="Ürün adından art arda en az 3 harf yazın", foreground="#64748B"
            )
            return
        if len(metin) < MIN_ARAMA_HARF:
            self._sonuclar = []
            self._secili_idx = -1
            self._popup_kapat()
            self.hint.configure(
                text="Arama için en az 3 karakter girin.", foreground="#B45309"
            )
            return
        self.hint.configure(text="Aranıyor…", foreground="#64748B")
        self._after_id = self.parent.after(DEBOUNCE_MS, self._arama_baslat)

    def _arama_baslat(self):
        self._after_id = None
        metin = self.entry.get().strip()
        if len(metin) < MIN_ARAMA_HARF:
            return
        self._arama_seq += 1
        seq = self._arama_seq
        depo = self.depo_getter()
        maliyet = bool(self.maliyet_izinli())

        def isci():
            try:
                sonuc = self.arama_fn(
                    metin,
                    depo_ad=depo,
                    min_harf=MIN_ARAMA_HARF,
                    limit=SONUC_LIMIT,
                    maliyet_dahil=maliyet,
                )
            except Exception as exc:
                sonuc = {
                    "urunler": [],
                    "toplam_eslesen": 0,
                    "daha_fazla": False,
                    "hata": str(exc),
                    "arama": metin,
                }
            try:
                self.parent.after(0, lambda: self._sonuc_uygula(seq, metin, sonuc))
            except tk.TclError:
                pass

        threading.Thread(target=isci, daemon=True).start()

    def _sonuc_uygula(self, seq: int, beklenen: str, sonuc: dict):
        if seq != self._arama_seq:
            return
        if self.entry.get().strip() != beklenen:
            return
        self._sonuclar = list(sonuc.get("urunler") or [])
        self._secili_idx = 0 if self._sonuclar else -1
        if sonuc.get("hata"):
            self.hint.configure(text=f"Arama hatası: {sonuc['hata']}", foreground="#C62828")
            self._popup_kapat()
            return
        if not self._sonuclar:
            self.hint.configure(
                text="Aramanızla eşleşen aktif ürün bulunamadı.",
                foreground="#C62828",
            )
            self._popup_goster_bos()
            return
        ekstra = ""
        if sonuc.get("daha_fazla"):
            ekstra = " — Daha fazla sonuç bulundu, aramanızı daraltın"
        self.hint.configure(
            text=f"{len(self._sonuclar)} ürün{ekstra}",
            foreground="#334155",
        )
        self._popup_goster()

    def _popup_kapat(self):
        if self._popup is not None:
            try:
                self._popup.destroy()
            except tk.TclError:
                pass
        self._popup = None
        self._tree = None
        self._durum_lbl = None

    def _kolonlar(self) -> list[tuple[str, str, int]]:
        kolonlar = [
            ("kod", "Ürün Kodu", 100),
            ("ad", "Ürün Adı", 220),
            ("marka", "Marka", 80),
            ("birim", "Birim", 50),
            ("depo_stok", "Depo Stok", 70),
            ("kul_stok", "Kullanılabilir", 80),
            ("teklif", "Teklif Fiyatı", 80),
            ("pb", "PB", 40),
        ]
        if self.maliyet_izinli():
            kolonlar.insert(6, ("alis", "Son Alış", 70))
        return kolonlar

    def _popup_olustur(self):
        self._popup_kapat()
        pop = tk.Toplevel(self.parent)
        pop.withdraw()
        pop.overrideredirect(True)
        pop.attributes("-topmost", True)
        frm = ttk.Frame(pop, padding=2)
        frm.pack(fill="both", expand=True)
        kolonlar = self._kolonlar()
        cols = [c[0] for c in kolonlar]
        tree = ttk.Treeview(frm, columns=cols, show="headings", height=10, selectmode="browse")
        for cid, baslik, w in kolonlar:
            tree.heading(cid, text=baslik)
            tree.column(cid, width=w, minwidth=40, anchor="w")
        sy = ttk.Scrollbar(frm, orient="vertical", command=tree.yview)
        sx = ttk.Scrollbar(frm, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        frm.rowconfigure(0, weight=1)
        frm.columnconfigure(0, weight=1)
        tree.tag_configure("stok_yok", foreground="#C62828")
        tree.tag_configure("manuel", foreground="#7C3AED")
        tree.bind("<Double-1>", lambda _e: self._secim_onayla())
        tree.bind("<Return>", lambda _e: self._secim_onayla())
        tree.bind("<Escape>", self._esc)
        self._durum_lbl = ttk.Label(frm, text="", foreground="#64748B")
        self._durum_lbl.grid(row=2, column=0, columnspan=2, sticky="ew", pady=2)
        self._popup = pop
        self._tree = tree
        self.parent.bind("<Configure>", self._konum_guncelle, add="+")

    def _popup_goster_bos(self):
        self._popup_olustur()
        assert self._popup and self._tree and self._durum_lbl
        for i in self._tree.get_children():
            self._tree.delete(i)
        self._durum_lbl.configure(text="Aramanızla eşleşen stok ürünü bulunamadı.")
        btn_f = ttk.Frame(self._popup)
        btn_f.pack(fill="x", padx=4, pady=4)
        ttk.Button(btn_f, text="Aramayı Temizle", command=self.temizle).pack(side="left", padx=2)
        if self.yetki_manuel() and (self.on_manuel_isim or self.on_manuel):
            ttk.Button(
                btn_f,
                text="Bu İsimle Manuel Ürün Ekle",
                command=self._manuel_isimle_ac,
            ).pack(side="left", padx=2)
        if self.yetki_stok():
            if self.on_stok_yeni:
                ttk.Button(btn_f, text="Yeni Stok Oluştur", command=self.on_stok_yeni).pack(
                    side="left", padx=2
                )
        self._konum_guncelle()
        self._popup.deiconify()

    def _manuel_isimle_ac(self):
        metin = self.entry.get().strip()
        self._popup_kapat()
        if self.on_manuel_isim:
            self.on_manuel_isim(metin)
        elif self.on_manuel:
            self.on_manuel()

    def _popup_goster(self):
        self._popup_olustur()
        assert self._popup and self._tree and self._durum_lbl
        maliyet = self.maliyet_izinli()
        for i, u in enumerate(self._sonuclar):
            tags = []
            if u.get("stok_yok"):
                tags.append("stok_yok")
            if u.get("manuel"):
                tags.append("manuel")
            depo_stok = _fmt_sayi(u.get("depo_stok"))
            if u.get("stok_yok"):
                depo_stok = f"{depo_stok} (Stok Yok)"
            vals = [
                u.get("urun_kodu") or "",
                ("[Manuel] " if u.get("manuel") else "") + (u.get("urun_adi") or ""),
                u.get("marka") or "",
                u.get("birim") or "",
                depo_stok,
                _fmt_sayi(u.get("kullanilabilir_stok")),
            ]
            if maliyet:
                vals.append(_fmt_sayi(u.get("son_alis_fiyati")))
            vals.extend(
                [
                    _fmt_sayi(u.get("teklif_fiyati")),
                    u.get("para_birimi") or "TRY",
                ]
            )
            self._tree.insert("", "end", iid=str(i), values=tuple(vals), tags=tuple(tags))
        if self._sonuclar:
            self._tree.selection_set("0")
            self._tree.focus("0")
            self._tree.see("0")
        self._durum_lbl.configure(
            text="↑↓ seç · Enter hazırla · Esc kapat"
            + (
                " · Daha fazla sonuç bulundu, aramanızı daraltın"
                if len(self._sonuclar) >= SONUC_LIMIT
                else ""
            )
        )
        self._konum_guncelle()
        self._popup.deiconify()

    def _konum_guncelle(self, _e=None):
        if not self._popup or not self._popup.winfo_exists():
            return
        try:
            self.entry.update_idletasks()
            x = self.entry.winfo_rootx()
            y = self.entry.winfo_rooty() + self.entry.winfo_height() + 2
            ekran_w = self.entry.winfo_screenwidth()
            ekran_h = self.entry.winfo_screenheight()
            w = max(self.entry.winfo_width(), 720)
            h = 280
            if x + w > ekran_w - 8:
                x = max(8, ekran_w - w - 8)
            if y + h > ekran_h - 8:
                y = max(8, self.entry.winfo_rooty() - h - 4)
            self._popup.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError:
            pass

    def _ok_asagi(self, _e=None):
        if not self._sonuclar:
            return "break"
        if self._popup is None:
            self._popup_goster()
        self._secili_idx = min(self._secili_idx + 1, len(self._sonuclar) - 1)
        self._secim_gorsel()
        return "break"

    def _ok_yukari(self, _e=None):
        if not self._sonuclar:
            return "break"
        self._secili_idx = max(self._secili_idx - 1, 0)
        self._secim_gorsel()
        return "break"

    def _secim_gorsel(self):
        if not self._tree or self._secili_idx < 0:
            return
        iid = str(self._secili_idx)
        self._tree.selection_set(iid)
        self._tree.focus(iid)
        self._tree.see(iid)

    def _enter(self, _e=None):
        if self._popup and self._sonuclar and self._secili_idx >= 0:
            self._secim_onayla()
            return "break"
        return None

    def _esc(self, _e=None):
        self._popup_kapat()
        return "break"

    def _tab(self, _e=None):
        self._popup_kapat()
        return None

    def _focus_out(self, _e=None):
        def kapat():
            try:
                odak = self.parent.focus_get()
            except tk.TclError:
                odak = None
            if self._popup and odak is not None:
                try:
                    if str(odak).startswith(str(self._popup)):
                        return
                except Exception:
                    pass
            self._popup_kapat()

        self.parent.after(180, kapat)

    def _secim_onayla(self):
        if not self._sonuclar:
            return
        idx = self._secili_idx
        if self._tree is not None:
            sel = self._tree.selection()
            if sel:
                try:
                    idx = int(sel[0])
                except ValueError:
                    pass
        if not (0 <= idx < len(self._sonuclar)):
            return
        urun = dict(self._sonuclar[idx])
        self._popup_kapat()
        self.on_select(urun)
