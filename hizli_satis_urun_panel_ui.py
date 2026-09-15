"""Hızlı Satış Aşama 3 — ürün grupları + tıklanabilir kartlar."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable

from database.stok_service import RESIM_KLASORU, StokService

SARİ = "#F5C518"
KOYU_GRI = "#2B2F33"
ACIK_GRI = "#F3F4F6"
KART_BG = "#FFFFFF"
KART_BORDER = "#D1D5DB"
KART_HOVER = "#FFF8DC"

# 1366×768 dokunmatik: ~4 sütun × ~3 satır görünür alan
SAYFA_BOYUTU = 24
KART_GENISLIK = 148
KART_YUKSEKLIK = 168
RESIM_BOYUT = 72


def _para(tutar) -> str:
    return f"{float(tutar):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _kisa_ad(ad: str, limit: int = 28) -> str:
    metin = (ad or "").strip()
    if len(metin) <= limit:
        return metin
    return metin[: limit - 1] + "…"


class HizliSatisUrunPanel:
    """Sol grup listesi + orta ürün kart ızgarası; tıklanınca on_urun_sec(dict)."""

    def __init__(
        self,
        sol: tk.Misc,
        merkez: tk.Misc,
        *,
        on_urun_sec: Callable[[dict], None],
        bg: str = ACIK_GRI,
    ):
        self.on_urun_sec = on_urun_sec
        self.bg = bg
        self.secili_grup: str | None = None
        self._offset = 0
        self._toplam = 0
        self._foto_refs: list = []
        self._grup_dugmeleri: dict[str, tk.Button] = {}
        self.fiyat_adi: str | None = None

        self._sol_kur(sol)
        self._merkez_kur(merkez)
        self.gruplari_yenile()

    # —— Sol: gruplar ——

    def _sol_kur(self, sol: tk.Misc) -> None:
        for w in sol.winfo_children():
            w.destroy()

        kabuk = tk.Frame(sol, bg=self.bg)
        kabuk.pack(fill="both", expand=True)
        kabuk.rowconfigure(0, weight=1)
        kabuk.columnconfigure(0, weight=1)

        self.grup_canvas = tk.Canvas(kabuk, bg=self.bg, highlightthickness=0, width=168)
        self.grup_canvas.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(kabuk, orient="vertical", command=self.grup_canvas.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.grup_canvas.configure(yscrollcommand=sb.set)

        self.grup_icerik = tk.Frame(self.grup_canvas, bg=self.bg)
        self._grup_pencere = self.grup_canvas.create_window(
            (0, 0), window=self.grup_icerik, anchor="nw"
        )
        self.grup_icerik.bind(
            "<Configure>",
            lambda _e: self.grup_canvas.configure(scrollregion=self.grup_canvas.bbox("all")),
        )
        self.grup_canvas.bind(
            "<Configure>",
            lambda e: self.grup_canvas.itemconfigure(self._grup_pencere, width=e.width),
        )

    def gruplari_yenile(self) -> None:
        for w in self.grup_icerik.winfo_children():
            w.destroy()
        self._grup_dugmeleri.clear()

        try:
            gruplar = StokService.hizli_satis_gruplari()
        except Exception as exc:
            tk.Label(
                self.grup_icerik,
                text=f"Gruplar yüklenemedi:\n{exc}",
                bg=self.bg,
                fg="#C62828",
                justify="left",
                wraplength=150,
                font=("Segoe UI", 8),
            ).pack(fill="x", pady=8)
            return

        if not gruplar:
            tk.Label(
                self.grup_icerik,
                text="Tanımlı rapor grubu yok.",
                bg=self.bg,
                fg="#6B7280",
                font=("Segoe UI", 9),
            ).pack(pady=16)
            return

        for g in gruplar:
            kod = g["kod"]
            ad = g["ad"]
            dugme = tk.Button(
                self.grup_icerik,
                text=ad,
                bg=SARİ,
                fg=KOYU_GRI,
                activebackground="#E6B800",
                activeforeground=KOYU_GRI,
                font=("Segoe UI", 10, "bold"),
                relief="flat",
                bd=0,
                padx=10,
                pady=14,
                cursor="hand2",
                wraplength=140,
                justify="center",
                command=lambda k=kod: self.grup_sec(k),
            )
            dugme.pack(fill="x", pady=3, padx=2)
            self._grup_dugmeleri[kod] = dugme

        if StokService.SIK_SATILANLAR_KOD in self._grup_dugmeleri:
            self.grup_sec(StokService.SIK_SATILANLAR_KOD)
        else:
            self.grup_sec(gruplar[0]["kod"])

    def grup_sec(self, grup_kod: str) -> None:
        self.secili_grup = grup_kod
        self._offset = 0
        for kod, dugme in self._grup_dugmeleri.items():
            if kod == grup_kod:
                dugme.configure(
                    bg=KOYU_GRI,
                    fg=SARİ,
                    activebackground="#1a1d20",
                    activeforeground=SARİ,
                    relief="sunken",
                )
            else:
                dugme.configure(
                    bg=SARİ,
                    fg=KOYU_GRI,
                    activebackground="#E6B800",
                    activeforeground=KOYU_GRI,
                    relief="flat",
                )
        self.kartlari_yenile()

    # —— Orta: kartlar ——

    def _merkez_kur(self, merkez: tk.Misc) -> None:
        for w in merkez.winfo_children():
            w.destroy()

        kabuk = tk.Frame(merkez, bg=self.bg)
        kabuk.pack(fill="both", expand=True)
        kabuk.rowconfigure(0, weight=1)
        kabuk.columnconfigure(0, weight=1)

        self.kart_canvas = tk.Canvas(kabuk, bg=self.bg, highlightthickness=0)
        self.kart_canvas.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(kabuk, orient="vertical", command=self.kart_canvas.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.kart_canvas.configure(yscrollcommand=sb.set)

        self.kart_icerik = tk.Frame(self.kart_canvas, bg=self.bg)
        self._kart_pencere = self.kart_canvas.create_window(
            (0, 0), window=self.kart_icerik, anchor="nw"
        )
        self.kart_icerik.bind(
            "<Configure>",
            lambda _e: self.kart_canvas.configure(scrollregion=self.kart_canvas.bbox("all")),
        )
        self.kart_canvas.bind("<Configure>", self._kart_genislik_ayarla)
        self.kart_canvas.bind("<MouseWheel>", self._fare_tekerlek)
        self.kart_icerik.bind("<MouseWheel>", self._fare_tekerlek)

        alt = tk.Frame(kabuk, bg=self.bg)
        alt.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.onceki_btn = tk.Button(
            alt,
            text="◀ Önceki",
            command=self._onceki_sayfa,
            bg=KOYU_GRI,
            fg=SARİ,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=10,
            pady=6,
            cursor="hand2",
        )
        self.onceki_btn.pack(side="left")
        self.sayfa_lbl = tk.Label(
            alt,
            text="",
            bg=self.bg,
            fg=KOYU_GRI,
            font=("Segoe UI", 9),
        )
        self.sayfa_lbl.pack(side="left", expand=True)
        self.sonraki_btn = tk.Button(
            alt,
            text="Sonraki ▶",
            command=self._sonraki_sayfa,
            bg=KOYU_GRI,
            fg=SARİ,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=10,
            pady=6,
            cursor="hand2",
        )
        self.sonraki_btn.pack(side="right")

    def _kart_genislik_ayarla(self, event) -> None:
        self.kart_canvas.itemconfigure(self._kart_pencere, width=event.width)

    def _fare_tekerlek(self, event) -> str:
        self.kart_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def kartlari_yenile(self) -> None:
        for w in self.kart_icerik.winfo_children():
            w.destroy()
        self._foto_refs.clear()

        if not self.secili_grup:
            return

        try:
            sonuc = StokService.hizli_satis_urunleri(
                self.secili_grup,
                limit=SAYFA_BOYUTU,
                offset=self._offset,
                fiyat_adi=self.fiyat_adi,
            )
        except Exception as exc:
            tk.Label(
                self.kart_icerik,
                text=f"Ürünler yüklenemedi:\n{exc}",
                bg=self.bg,
                fg="#C62828",
                font=("Segoe UI", 10),
            ).pack(pady=24)
            self._sayfa_bilgi(0)
            return

        urunler = sonuc.get("urunler") or []
        self._toplam = int(sonuc.get("toplam") or 0)
        self._sayfa_bilgi(len(urunler))

        if not urunler:
            mesaj = "Bu grupta ürün yok."
            if self.secili_grup == StokService.SIK_SATILANLAR_KOD:
                mesaj = (
                    "Sık satılan ürün henüz yok.\n"
                    "(Onaylı satış geçmişinden doldurulur — başka bir grup seçin.)"
                )
            tk.Label(
                self.kart_icerik,
                text=mesaj,
                bg=self.bg,
                fg="#6B7280",
                font=("Segoe UI", 10),
                justify="center",
            ).pack(expand=True, pady=40)
            return

        genislik = self.kart_canvas.winfo_width()
        if genislik < 50:
            genislik = 600
        sutun = max(1, genislik // (KART_GENISLIK + 12))
        for i, urun in enumerate(urunler):
            r, c = divmod(i, sutun)
            kart = self._kart_olustur(self.kart_icerik, urun)
            kart.grid(row=r, column=c, padx=6, pady=6, sticky="n")

        self.kart_canvas.yview_moveto(0)

    def _sayfa_bilgi(self, gosterilen: int) -> None:
        if self._toplam <= 0:
            self.sayfa_lbl.configure(text="0 ürün")
            self.onceki_btn.configure(state="disabled")
            self.sonraki_btn.configure(state="disabled")
            return
        bas = self._offset + 1
        bit = self._offset + gosterilen
        sayfa = (self._offset // SAYFA_BOYUTU) + 1
        toplam_sayfa = max(1, (self._toplam + SAYFA_BOYUTU - 1) // SAYFA_BOYUTU)
        self.sayfa_lbl.configure(
            text=f"{bas}–{bit} / {self._toplam}  ·  Sayfa {sayfa}/{toplam_sayfa}"
        )
        self.onceki_btn.configure(state="normal" if self._offset > 0 else "disabled")
        self.sonraki_btn.configure(
            state="normal" if self._offset + SAYFA_BOYUTU < self._toplam else "disabled"
        )

    def _onceki_sayfa(self) -> None:
        self._offset = max(0, self._offset - SAYFA_BOYUTU)
        self.kartlari_yenile()

    def _sonraki_sayfa(self) -> None:
        if self._offset + SAYFA_BOYUTU < self._toplam:
            self._offset += SAYFA_BOYUTU
            self.kartlari_yenile()

    def _kart_olustur(self, parent: tk.Misc, urun: dict) -> tk.Frame:
        kart = tk.Frame(
            parent,
            bg=KART_BG,
            highlightbackground=KART_BORDER,
            highlightthickness=1,
            width=KART_GENISLIK,
            height=KART_YUKSEKLIK,
            cursor="hand2",
        )
        kart.pack_propagate(False)

        resim_lbl = tk.Label(kart, bg=KART_BG, width=10, height=4)
        resim_lbl.pack(pady=(10, 4))
        self._resim_yukle(resim_lbl, urun.get("resim_yolu"))

        ad_lbl = tk.Label(
            kart,
            text=_kisa_ad(urun.get("stok_adi") or urun.get("stok_kodu") or ""),
            bg=KART_BG,
            fg=KOYU_GRI,
            font=("Segoe UI", 9, "bold"),
            wraplength=KART_GENISLIK - 16,
            justify="center",
        )
        ad_lbl.pack(padx=6)

        fiyat = urun.get("birim_fiyat")
        fiyat_metin = f"{_para(fiyat)} TL" if fiyat is not None else "—"
        fiyat_lbl = tk.Label(
            kart,
            text=fiyat_metin,
            bg=KART_BG,
            fg="#1B5E20",
            font=("Segoe UI", 10, "bold"),
        )
        fiyat_lbl.pack(pady=(4, 8))

        def tikla(_event=None, u=urun):
            self.on_urun_sec(u)

        def hover_in(_e=None):
            for w in (kart, resim_lbl, ad_lbl, fiyat_lbl):
                try:
                    w.configure(bg=KART_HOVER)
                except tk.TclError:
                    pass

        def hover_out(_e=None):
            for w in (kart, resim_lbl, ad_lbl, fiyat_lbl):
                try:
                    w.configure(bg=KART_BG)
                except tk.TclError:
                    pass

        for w in (kart, resim_lbl, ad_lbl, fiyat_lbl):
            w.bind("<Button-1>", tikla)
            w.bind("<Enter>", hover_in)
            w.bind("<Leave>", hover_out)

        return kart

    def _resim_yukle(self, label: tk.Label, yol: str | None) -> None:
        if not yol:
            label.configure(text="[ ]", font=("Segoe UI", 22), fg="#9CA3AF")
            return
        path = Path(yol)
        if not path.is_file():
            aday = RESIM_KLASORU / path.name
            if aday.is_file():
                path = aday
        if not path.is_file():
            label.configure(text="[ ]", font=("Segoe UI", 22), fg="#9CA3AF")
            return

        foto = self._foto_olustur(path, RESIM_BOYUT, RESIM_BOYUT)
        if foto is None:
            label.configure(text="[ ]", font=("Segoe UI", 22), fg="#9CA3AF")
            return
        self._foto_refs.append(foto)
        label.configure(image=foto, text="")

    @staticmethod
    def _foto_olustur(path: Path, max_w: int, max_h: int) -> tk.PhotoImage | None:
        try:
            from PIL import Image, ImageTk  # type: ignore

            with Image.open(path) as im:
                im = im.convert("RGBA")
                im.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                return ImageTk.PhotoImage(im)
        except Exception:
            pass
        try:
            img = tk.PhotoImage(file=str(path))
            w, h = img.width(), img.height()
            if w > max_w or h > max_h:
                factor = max(1, int(max(w / max_w, h / max_h)))
                img = img.subsample(factor, factor)
            return img
        except Exception:
            return None
