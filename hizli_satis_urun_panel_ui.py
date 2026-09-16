"""Hızlı Satış Aşama 3 — ürün grupları + tıklanabilir kartlar + ÜRÜN EKLE pin."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from typing import Callable

from database.hizli_satis_service import HizliSatisService
from database.stok_service import RESIM_KLASORU, StokService

SARİ = "#F5C518"
KOYU_GRI = "#2B2F33"
LACIVERT = "#0B1F3A"
ACIK_GRI = "#F3F4F6"
KART_BG = "#FFFFFF"
KART_BORDER = "#D1D5DB"
KART_HOVER = "#FFF8DC"
STOK_YOK_FG = "#C62828"

# 1366×768 dokunmatik: ~4 sütun × ~3 satır görünür alan
SAYFA_BOYUTU = 24
KART_GENISLIK = 148
KART_YUKSEKLIK = 196
RESIM_BOYUT = 56


def _para(tutar) -> str:
    return f"{float(tutar):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _miktar_goster(miktar) -> str:
    """Türkçe ondalık (virgül); gereksiz ondalık sıfırları at (120 → 120, değil 12)."""
    try:
        from decimal import Decimal

        d = Decimal(str(miktar or 0))
        if d == d.to_integral_value():
            metin = str(int(d))
        else:
            metin = format(d, "f").rstrip("0").rstrip(".")
    except Exception:
        metin = str(miktar or 0)
    return (metin or "0").replace(".", ",")


def _kisa_ad(ad: str, limit: int = 28) -> str:
    metin = (ad or "").strip()
    if len(metin) <= limit:
        return metin
    return metin[: limit - 1] + "…"


def _kisa_barkod(barkod: str | None, limit: int = 18) -> str:
    metin = (barkod or "").strip()
    if not metin:
        return "—"
    if len(metin) <= limit:
        return metin
    return metin[: limit - 1] + "…"


def _kart_metinleri(urun: dict) -> dict[str, str]:
    """Kart üzerinde gösterilecek barkod / ad / depo / fiyat (smoke & UI)."""
    ad_kaynak = (
        urun.get("kisa_ad")
        or urun.get("stok_adi")
        or urun.get("ad")
        or urun.get("urun_adi")
        or urun.get("stok_kodu")
        or ""
    )
    birim = (urun.get("birim") or "Adet").strip() or "Adet"
    fiyat = urun.get("birim_fiyat")
    try:
        from decimal import Decimal

        mevcut = Decimal(str(urun.get("mevcut_stok") or 0))
    except Exception:
        mevcut = 0
    if mevcut <= 0:
        depo = "STOK YOK"
    else:
        depo = f"Depo: {_miktar_goster(urun.get('mevcut_stok'))} {birim}"
    return {
        "barkod": _kisa_barkod(urun.get("barkod")),
        "ad": _kisa_ad(str(ad_kaynak)),
        "depo": depo,
        "fiyat": f"{_para(fiyat)} TL" if fiyat is not None else "—",
        "stok_yok": mevcut <= 0,
        "kod": (urun.get("stok_kodu") or "").strip(),
    }


class HizliSatisUrunPanel:
    """Sol grup listesi + orta ürün kart ızgarası; tıklanınca on_urun_sec(dict)."""

    def __init__(
        self,
        sol: tk.Misc,
        merkez: tk.Misc,
        *,
        on_urun_sec: Callable[[dict], None],
        bg: str = ACIK_GRI,
        parent_for_dialog: tk.Misc | None = None,
    ):
        self.on_urun_sec = on_urun_sec
        self.bg = bg
        self.parent_for_dialog = parent_for_dialog or merkez
        self.secili_grup: str | None = None
        self._offset = 0
        self._toplam = 0
        self._foto_refs: list = []
        self._grup_dugmeleri: dict[str, tk.Button] = {}
        self._son_urunler: list[dict] = []
        self.fiyat_adi: str | None = None

        self._sol_kur(sol)
        self._merkez_kur(merkez)
        self.gruplari_yenile()

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
        onceki = self.secili_grup
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
                text="Tanımlı grup yok.\nÜRÜN EKLE ile başlayın.",
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

        if onceki and onceki in self._grup_dugmeleri:
            self.grup_sec(onceki)
        elif StokService.SIK_SATILANLAR_KOD in self._grup_dugmeleri:
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

    def _merkez_kur(self, merkez: tk.Misc) -> None:
        for w in merkez.winfo_children():
            w.destroy()

        kabuk = tk.Frame(merkez, bg=self.bg)
        kabuk.pack(fill="both", expand=True)
        kabuk.rowconfigure(1, weight=1)
        kabuk.columnconfigure(0, weight=1)

        ust = tk.Frame(kabuk, bg=self.bg)
        ust.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.urun_ekle_btn = tk.Button(
            ust,
            text="＋  ÜRÜN EKLE",
            command=self._urun_ekle_ac,
            bg=SARİ,
            fg=KOYU_GRI,
            activebackground="#E6B800",
            activeforeground=KOYU_GRI,
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            bd=0,
            padx=16,
            pady=10,
            cursor="hand2",
        )
        self.urun_ekle_btn.pack(side="left")
        tk.Label(
            ust,
            text="Mevcut stok kartını Hızlı Satış'a ekler (stok kartı oluşturmaz)",
            bg=self.bg,
            fg="#6B7280",
            font=("Segoe UI", 8),
        ).pack(side="left", padx=10)

        self.kart_canvas = tk.Canvas(kabuk, bg=self.bg, highlightthickness=0)
        self.kart_canvas.grid(row=1, column=0, sticky="nsew")
        sb = ttk.Scrollbar(kabuk, orient="vertical", command=self.kart_canvas.yview)
        sb.grid(row=1, column=1, sticky="ns")
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
        alt.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
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

    def _urun_ekle_ac(self) -> None:
        from hizli_satis_urun_ekle_ui import HizliSatisUrunEkleDialog

        dlg = HizliSatisUrunEkleDialog(
            self.parent_for_dialog,
            varsayilan_hizli_grup_kod=self.secili_grup,
            fiyat_adi=self.fiyat_adi,
            on_degisti=self._pin_sonrasi_yenile,
        )
        self.parent_for_dialog.wait_window(dlg)

    def _pin_sonrasi_yenile(self) -> None:
        self.gruplari_yenile()

    def _kart_genislik_ayarla(self, event) -> None:
        self.kart_canvas.itemconfigure(self._kart_pencere, width=event.width)

    def _fare_tekerlek(self, event) -> str:
        self.kart_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        return "break"

    def kartlari_yenile(self) -> None:
        for w in self.kart_icerik.winfo_children():
            w.destroy()
        self._foto_refs.clear()
        self._son_urunler = []

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
        self._son_urunler = list(urunler)
        self._toplam = int(sonuc.get("toplam") or 0)
        self._sayfa_bilgi(len(urunler))

        if not urunler:
            mesaj = "Bu grupta ürün yok."
            if self.secili_grup == StokService.SIK_SATILANLAR_KOD:
                mesaj = (
                    "Sık satılan ürün henüz yok.\n"
                    "(Onaylı satış geçmişinden doldurulur — başka bir grup seçin.)"
                )
            elif str(self.secili_grup).startswith("HSG:"):
                mesaj = "Bu hızlı satış grubunda pinli ürün yok.\nÜRÜN EKLE ile ekleyin."
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
        """Küçük görsel + barkod / ad / depo / fiyat; pin menüsü sağ tık."""
        metin = _kart_metinleri(urun)
        bg = (urun.get("kart_rengi") or "").strip() or KART_BG
        if not bg.startswith("#"):
            bg = KART_BG

        kart = tk.Frame(
            parent,
            bg=bg,
            highlightbackground=KART_BORDER,
            highlightthickness=1,
            width=KART_GENISLIK,
            height=KART_YUKSEKLIK,
            cursor="hand2",
        )
        kart.pack_propagate(False)

        resim_cerceve = tk.Frame(
            kart,
            bg=bg,
            width=RESIM_BOYUT + 4,
            height=RESIM_BOYUT + 4,
        )
        resim_cerceve.pack(pady=(6, 2))
        resim_cerceve.pack_propagate(False)
        resim_lbl = tk.Label(
            resim_cerceve,
            bg=bg,
            fg="#9CA3AF",
            font=("Segoe UI", 12),
            anchor="center",
        )
        resim_lbl.pack(fill="both", expand=True)
        self._resim_yukle(resim_lbl, urun.get("resim_yolu"))

        metin_kutu = tk.Frame(kart, bg=bg)
        metin_kutu.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        kod_lbl = None
        if metin.get("kod"):
            kod_lbl = tk.Label(
                metin_kutu,
                text=metin["kod"],
                bg=bg,
                fg="#6B7280",
                font=("Consolas", 7),
            )
            kod_lbl.pack(padx=2)

        barkod_lbl = tk.Label(
            metin_kutu,
            text=metin["barkod"],
            bg=bg,
            fg=LACIVERT,
            font=("Consolas", 8),
            wraplength=KART_GENISLIK - 12,
            justify="center",
        )
        barkod_lbl.pack(padx=2)

        ad_lbl = tk.Label(
            metin_kutu,
            text=metin["ad"],
            bg=bg,
            fg=KOYU_GRI,
            font=("Segoe UI", 9, "bold"),
            wraplength=KART_GENISLIK - 16,
            justify="center",
        )
        ad_lbl.pack(padx=4, pady=(2, 0))

        miktar_lbl = tk.Label(
            metin_kutu,
            text=metin["depo"],
            bg=bg,
            fg=STOK_YOK_FG if metin.get("stok_yok") else LACIVERT,
            font=("Segoe UI", 8, "bold"),
            wraplength=KART_GENISLIK - 12,
            justify="center",
        )
        miktar_lbl.pack(padx=2, pady=(2, 0))

        fiyat_lbl = tk.Label(
            metin_kutu,
            text=metin["fiyat"],
            bg=bg,
            fg="#1B5E20",
            font=("Segoe UI", 10, "bold"),
        )
        fiyat_lbl.pack(pady=(4, 2))

        def tikla(_event=None, u=urun):
            self.on_urun_sec(u)

        hover_hedefler = [
            kart,
            resim_cerceve,
            resim_lbl,
            metin_kutu,
            barkod_lbl,
            ad_lbl,
            miktar_lbl,
            fiyat_lbl,
        ]
        if kod_lbl is not None:
            hover_hedefler.append(kod_lbl)

        def hover_in(_e=None):
            for w in hover_hedefler:
                try:
                    w.configure(bg=KART_HOVER)
                except tk.TclError:
                    pass

        def hover_out(_e=None):
            for w in hover_hedefler:
                try:
                    w.configure(bg=bg)
                except tk.TclError:
                    pass

        for w in hover_hedefler:
            w.bind("<Button-1>", tikla)
            w.bind("<Enter>", hover_in)
            w.bind("<Leave>", hover_out)
            if urun.get("pin_id"):
                w.bind("<Button-3>", lambda e, u=urun: self._pin_menu(e, u))

        return kart

    def _pin_menu(self, event, urun: dict) -> None:
        pin_id = urun.get("pin_id")
        if not pin_id:
            return
        menu = tk.Menu(self.kart_icerik, tearoff=0)
        menu.add_command(label="Düzenle…", command=lambda: self._pin_duzenle(urun))
        menu.add_command(label="Gruba taşı…", command=lambda: self._pin_tasi(urun))
        menu.add_separator()
        menu.add_command(label="Sıra ← sol", command=lambda: self._pin_sira(pin_id, "left"))
        menu.add_command(label="Sıra → sağ", command=lambda: self._pin_sira(pin_id, "right"))
        menu.add_command(label="İlk sıraya", command=lambda: self._pin_sira(pin_id, "first"))
        menu.add_command(label="Son sıraya", command=lambda: self._pin_sira(pin_id, "last"))
        menu.add_separator()
        menu.add_command(label="Pasifleştir", command=lambda: self._pin_pasif(pin_id))
        menu.add_command(
            label="Hızlı Satış'tan kaldır…",
            command=lambda: self._pin_kaldir(urun),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _pin_sira(self, pin_id: int, yon: str) -> None:
        try:
            HizliSatisService.pin_sira_tasi(int(pin_id), yon)
            self.kartlari_yenile()
        except ValueError as exc:
            messagebox.showwarning("Sıra", str(exc), parent=self.parent_for_dialog)

    def _pin_pasif(self, pin_id: int) -> None:
        try:
            HizliSatisService.pin_guncelle(int(pin_id), aktif=False)
            self.kartlari_yenile()
        except ValueError as exc:
            messagebox.showwarning("Pin", str(exc), parent=self.parent_for_dialog)

    def _pin_kaldir(self, urun: dict) -> None:
        pin_id = urun.get("pin_id")
        if not pin_id:
            return
        kod = urun.get("stok_kodu") or ""
        if not messagebox.askyesno(
            "Hızlı Satış'tan kaldır",
            (
                f"«{kod}» Hızlı Satış ekranından kaldırılacak.\n"
                "Stok kartı silinmez. Devam edilsin mi?"
            ),
            parent=self.parent_for_dialog,
        ):
            return
        try:
            HizliSatisService.pin_kaldir(int(pin_id))
            self.kartlari_yenile()
        except ValueError as exc:
            messagebox.showerror("Kaldır", str(exc), parent=self.parent_for_dialog)

    def _pin_duzenle(self, urun: dict) -> None:
        pin_id = urun.get("pin_id")
        if not pin_id:
            return
        kisa = simpledialog.askstring(
            "Kısa ad",
            "Kart üzerinde görünecek kısa ad:",
            initialvalue=urun.get("kisa_ad") or urun.get("stok_adi") or "",
            parent=self.parent_for_dialog,
        )
        if kisa is None:
            return
        try:
            HizliSatisService.pin_guncelle(int(pin_id), kisa_ad=kisa.strip() or None)
            self.kartlari_yenile()
        except ValueError as exc:
            messagebox.showwarning("Düzenle", str(exc), parent=self.parent_for_dialog)

    def _pin_tasi(self, urun: dict) -> None:
        pin_id = urun.get("pin_id")
        if not pin_id:
            return
        gruplar = HizliSatisService.hizli_gruplari_listele()
        if not gruplar:
            messagebox.showinfo("Grup", "Taşınacak grup yok.", parent=self.parent_for_dialog)
            return
        adlar = [g["ad"] for g in gruplar]
        top = tk.Toplevel(self.parent_for_dialog)
        top.title("Gruba taşı")
        top.geometry("320x280")
        top.transient(self.parent_for_dialog)
        top.grab_set()
        lst = tk.Listbox(top)
        lst.pack(fill="both", expand=True, padx=8, pady=8)
        for a in adlar:
            lst.insert("end", a)

        def onay():
            sec = lst.curselection()
            if not sec:
                return
            hedef = gruplar[sec[0]]
            try:
                HizliSatisService.pin_guncelle(
                    int(pin_id), hizli_satis_grubu_id=int(hedef["id"])
                )
                top.destroy()
                self.gruplari_yenile()
            except ValueError as exc:
                messagebox.showwarning("Taşı", str(exc), parent=top)

        ttk.Button(top, text="Taşı", command=onay).pack(pady=6)

    def _resim_yukle(self, label: tk.Label, yol: str | None) -> None:
        placeholder = {"text": "[ ]", "font": ("Segoe UI", 12), "fg": "#9CA3AF", "image": ""}
        if not yol:
            label.configure(**placeholder)
            return
        path = Path(yol)
        if not path.is_file():
            aday = RESIM_KLASORU / path.name
            if aday.is_file():
                path = aday
        if not path.is_file():
            label.configure(**placeholder)
            return

        foto = self._foto_olustur(path, RESIM_BOYUT, RESIM_BOYUT)
        if foto is None:
            label.configure(**placeholder)
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
