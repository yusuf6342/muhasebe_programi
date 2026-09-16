"""Hızlı Satış Aşama 5 — tahsilat / ödeme penceresi (POS görünümü)."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from tkinter import messagebox, ttk
from typing import Any, Callable

from database.access import yetki_var
from database.hizli_satis_service import HizliSatisService
from hizli_satis_musteri import IZIN_ACIK_HESAP

SARİ = "#F5C518"
KOYU_GRI = "#2B2F33"
ACIK_GRI = "#F3F4F6"
YESIL = "#2E7D32"
KIRMIZI = "#C62828"
BEYAZ = "#FFFFFF"
MAVI = "#1565C0"

KURUS = Decimal("0.01")

NAKİT = "NAKİT / KASA"
HAVALE = "GELEN HAVALE"
KK = "KREDİ KARTIYLA TAHSİLAT"
ACIK = "AÇIK HESAP"

HIZLI_NAKIT_TUTARLARI = (
    Decimal("50"),
    Decimal("100"),
    Decimal("200"),
    Decimal("500"),
    Decimal("1000"),
)


def _kurus(tutar) -> Decimal:
    try:
        return Decimal(str(tutar)).quantize(KURUS, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def _para(tutar) -> str:
    return f"{float(_kurus(tutar)):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _parse_tutar(metin: str) -> Decimal:
    s = (metin or "").strip().replace("TL", "").replace("tl", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return _kurus(Decimal(s))
    except (InvalidOperation, TypeError, ValueError) as hata:
        raise ValueError("Geçerli bir tutar girin.") from hata


class HizliSatisTahsilatDialog(tk.Toplevel):
    """Ödeme şekilleri + kısmi tahsilat; onayda callback ile kayıt."""

    def __init__(
        self,
        parent,
        *,
        genel_toplam: Decimal | str | float,
        musteri_unvan: str = "",
        musteri_bakiye=None,
        risk_limiti=None,
        on_onay: Callable[[list[dict[str, Any]]], None] | None = None,
    ):
        super().__init__(parent)
        self.title("TAHSİLAT — Hızlı Satış")
        self.configure(bg=KOYU_GRI)
        self.transient(parent)
        self.grab_set()

        self.genel_toplam = _kurus(genel_toplam)
        self.musteri_unvan = (musteri_unvan or "").strip()
        self.musteri_bakiye = musteri_bakiye
        self.risk_limiti = risk_limiti
        self.on_onay = on_onay
        self.result: list[dict[str, Any]] | None = None
        self.odeme_satirlari: list[dict[str, Any]] = []
        self._aktif_sekil = NAKİT
        self._orta_canvas: tk.Canvas | None = None
        self._orta_icerik: tk.Frame | None = None

        self._ui_kur()
        self._pencereyi_yerlestir()
        self._ozet_yenile()
        self.protocol("WM_DELETE_WINDOW", self._iptal)
        self.bind("<Escape>", lambda _e: self._iptal())
        self.bind("<F12>", lambda _e: self._tamamla())
        self.after(80, lambda: self.tutar_entry.focus_set())

    def _pencereyi_yerlestir(self) -> None:
        """Ekrana sığdır; 1366×768 ve küçük çözünürlüklerde alt butonlar kesilmesin."""
        self.update_idletasks()
        sw = max(int(self.winfo_screenwidth()), 800)
        sh = max(int(self.winfo_screenheight()), 600)
        # Görev çubuğu / DPI payı bırak
        max_w = min(720, max(560, sw - 40))
        max_h = min(640, max(480, sh - 80))
        self.minsize(560, 420)
        self.geometry(f"{max_w}x{max_h}")
        x = max(0, (sw - max_w) // 2)
        y = max(0, (sh - max_h) // 2)
        self.geometry(f"{max_w}x{max_h}+{x}+{y}")

    def _orta_scroll_guncelle(self, _event=None) -> None:
        if self._orta_canvas is None:
            return
        self._orta_canvas.configure(scrollregion=self._orta_canvas.bbox("all"))

    def _orta_genislik_ayarla(self, event) -> None:
        if self._orta_canvas is None or self._orta_icerik is None:
            return
        self._orta_canvas.itemconfigure(self._orta_pencere_id, width=max(event.width, 1))

    def _orta_tekerlek(self, event) -> None:
        if self._orta_canvas is None:
            return
        # Yalnızca bu dialog üzerindeki tekerlek olaylarını yakala
        w = event.widget
        try:
            while w is not None:
                if w is self:
                    break
                w = w.master
            else:
                return
        except tk.TclError:
            return
        if getattr(event, "num", None) == 4:
            self._orta_canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            self._orta_canvas.yview_scroll(1, "units")
        else:
            adim = int(-1 * (event.delta / 120)) if getattr(event, "delta", 0) else 0
            if adim:
                self._orta_canvas.yview_scroll(adim, "units")

    def _ui_kur(self) -> None:
        # Sabit alt çubuk ÖNCE pack edilir → her zaman görünür (sticky footer)
        alt = tk.Frame(self, bg="#1a1d20", pady=10, padx=10)
        alt.pack(side="bottom", fill="x")
        alt.columnconfigure(0, weight=1)
        alt.columnconfigure(1, weight=2)
        tk.Button(
            alt,
            text="İPTAL (Esc)",
            bg=KIRMIZI,
            fg=BEYAZ,
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            pady=12,
            command=self._iptal,
        ).grid(row=0, column=0, sticky="ew", padx=4)
        tk.Button(
            alt,
            text="SATIŞI ONAYLA (F12)",
            bg=YESIL,
            fg=BEYAZ,
            font=("Segoe UI", 12, "bold"),
            relief="flat",
            pady=12,
            command=self._tamamla,
        ).grid(row=0, column=1, sticky="ew", padx=4)

        self.ozet_lbl = tk.Label(
            self,
            text="",
            bg=KOYU_GRI,
            fg=BEYAZ,
            font=("Segoe UI", 11, "bold"),
            anchor="e",
            justify="right",
            padx=14,
            pady=6,
        )
        self.ozet_lbl.pack(side="bottom", fill="x")

        ust = tk.Frame(self, bg=SARİ, pady=10, padx=14)
        ust.pack(side="top", fill="x")
        tk.Label(
            ust,
            text="TAHSİLAT",
            bg=SARİ,
            fg=KOYU_GRI,
            font=("Segoe UI", 16, "bold"),
        ).pack(side="left")
        tk.Label(
            ust,
            text=_para(self.genel_toplam),
            bg=SARİ,
            fg=KOYU_GRI,
            font=("Segoe UI", 18, "bold"),
        ).pack(side="right")

        # Kaydırılabilir orta alan (üst form + ödeme listesi)
        orta_dis = tk.Frame(self, bg=KOYU_GRI)
        orta_dis.pack(side="top", fill="both", expand=True)
        orta_dis.rowconfigure(0, weight=1)
        orta_dis.columnconfigure(0, weight=1)

        self._orta_canvas = tk.Canvas(
            orta_dis, bg=KOYU_GRI, highlightthickness=0, borderwidth=0
        )
        kaydir = ttk.Scrollbar(orta_dis, orient="vertical", command=self._orta_canvas.yview)
        self._orta_canvas.configure(yscrollcommand=kaydir.set)
        self._orta_canvas.grid(row=0, column=0, sticky="nsew")
        kaydir.grid(row=0, column=1, sticky="ns")

        icerik = tk.Frame(self._orta_canvas, bg=KOYU_GRI)
        self._orta_icerik = icerik
        self._orta_pencere_id = self._orta_canvas.create_window((0, 0), window=icerik, anchor="nw")
        icerik.bind("<Configure>", self._orta_scroll_guncelle)
        self._orta_canvas.bind("<Configure>", self._orta_genislik_ayarla)
        self.bind_all("<MouseWheel>", self._orta_tekerlek, add="+")
        self.bind_all("<Button-4>", self._orta_tekerlek, add="+")
        self.bind_all("<Button-5>", self._orta_tekerlek, add="+")
        self.bind("<Destroy>", self._orta_tekerlek_temizle, add="+")

        if self.musteri_unvan:
            tk.Label(
                icerik,
                text=f"Müşteri: {self.musteri_unvan}",
                bg=KOYU_GRI,
                fg=BEYAZ,
                font=("Segoe UI", 10),
                anchor="w",
            ).pack(fill="x", padx=14, pady=(8, 0))

        # Ödeme şekli butonları
        sekil_fr = tk.Frame(icerik, bg=KOYU_GRI, pady=8)
        sekil_fr.pack(fill="x", padx=10)
        self._sekil_butonlari: dict[str, tk.Button] = {}
        etiketler = (
            (NAKİT, "NAKİT"),
            (KK, "K.KARTI / POS"),
            (HAVALE, "HAVALE"),
            (ACIK, "AÇIK HESAP"),
        )
        for i, (kod, yazi) in enumerate(etiketler):
            sekil_fr.columnconfigure(i, weight=1)
            btn = tk.Button(
                sekil_fr,
                text=yazi,
                bg=KOYU_GRI,
                fg=SARİ,
                activebackground="#1a1d20",
                activeforeground=SARİ,
                font=("Segoe UI", 10, "bold"),
                relief="flat",
                highlightthickness=2,
                highlightbackground=SARİ,
                pady=10,
                command=lambda k=kod: self._sekil_sec(k),
            )
            btn.grid(row=0, column=i, sticky="ew", padx=3)
            self._sekil_butonlari[kod] = btn

        # Form
        form = tk.Frame(icerik, bg=ACIK_GRI, padx=12, pady=10)
        form.pack(fill="x", padx=10, pady=6)

        tk.Label(form, text="Tutar", bg=ACIK_GRI, fg=KOYU_GRI, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.tutar_var = tk.StringVar()
        self.tutar_entry = tk.Entry(
            form,
            textvariable=self.tutar_var,
            font=("Segoe UI", 14, "bold"),
            width=14,
            justify="right",
        )
        self.tutar_entry.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.tutar_var.set(f"{self.genel_toplam:.2f}".replace(".", ","))

        tk.Label(form, text="Hesap", bg=ACIK_GRI, fg=KOYU_GRI, font=("Segoe UI", 10, "bold")).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        self.hesap_var = tk.StringVar()
        self.hesap_cb = ttk.Combobox(form, textvariable=self.hesap_var, state="readonly", width=36)
        self.hesap_cb.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        # KK ek alanları
        self.kk_frame = tk.Frame(form, bg=ACIK_GRI)
        self.kk_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        tk.Label(self.kk_frame, text="Banka / POS notu", bg=ACIK_GRI, fg=KOYU_GRI).grid(
            row=0, column=0, sticky="w"
        )
        self.kk_banka_var = tk.StringVar()
        tk.Entry(self.kk_frame, textvariable=self.kk_banka_var, width=24).grid(
            row=0, column=1, padx=6, sticky="w"
        )
        tk.Label(self.kk_frame, text="Taksit", bg=ACIK_GRI, fg=KOYU_GRI).grid(
            row=0, column=2, sticky="w", padx=(12, 0)
        )
        self.kk_taksit_var = tk.StringVar(value="1")
        tk.Entry(self.kk_frame, textvariable=self.kk_taksit_var, width=6).grid(
            row=0, column=3, padx=6, sticky="w"
        )

        # Nakit hızlı tutarlar
        self.nakit_frame = tk.Frame(form, bg=ACIK_GRI)
        self.nakit_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        tk.Button(
            self.nakit_frame,
            text="TAMAMI",
            bg=YESIL,
            fg=BEYAZ,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=10,
            pady=6,
            command=self._tamami_yaz,
        ).pack(side="left", padx=2)
        for t in HIZLI_NAKIT_TUTARLARI:
            tk.Button(
                self.nakit_frame,
                text=str(int(t)),
                bg=KOYU_GRI,
                fg=SARİ,
                font=("Segoe UI", 9, "bold"),
                relief="flat",
                padx=10,
                pady=6,
                command=lambda x=t: self._tutar_yaz(x),
            ).pack(side="left", padx=2)

        self.para_ustu_lbl = tk.Label(
            form,
            text="",
            bg=ACIK_GRI,
            fg=MAVI,
            font=("Segoe UI", 11, "bold"),
            anchor="w",
        )
        self.para_ustu_lbl.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.tutar_var.trace_add("write", lambda *_: self._para_ustu_guncelle())

        tk.Button(
            form,
            text="ÖDEMEYİ LİSTEYE EKLE",
            bg=SARİ,
            fg=KOYU_GRI,
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            pady=8,
            command=self._odeme_ekle,
        ).grid(row=5, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        # Liste
        liste_fr = tk.Frame(icerik, bg=KOYU_GRI, padx=10)
        liste_fr.pack(fill="x", pady=6)
        tk.Label(
            liste_fr,
            text="Ödeme satırları (kısmi tahsilat desteklenir)",
            bg=KOYU_GRI,
            fg=SARİ,
            font=("Segoe UI", 9, "bold"),
            anchor="w",
        ).pack(fill="x")
        self.liste = ttk.Treeview(
            liste_fr,
            columns=("sekil", "hesap", "tutar"),
            show="headings",
            height=4,
        )
        self.liste.heading("sekil", text="Ödeme Şekli")
        self.liste.heading("hesap", text="Hesap")
        self.liste.heading("tutar", text="Tutar")
        self.liste.column("sekil", width=180)
        self.liste.column("hesap", width=220)
        self.liste.column("tutar", width=120, anchor="e")
        self.liste.pack(fill="x", pady=(4, 0))
        tk.Button(
            liste_fr,
            text="Seçili satırı sil",
            bg=KIRMIZI,
            fg=BEYAZ,
            relief="flat",
            command=self._satir_sil,
        ).pack(anchor="e", pady=4)

        self._sekil_sec(NAKİT)

    def _orta_tekerlek_temizle(self, event=None) -> None:
        """Dialog yok edilince scroll referansını bırak (bind_all handler no-op olur)."""
        if event is not None and event.widget is not self:
            return
        self._orta_canvas = None
        self._orta_icerik = None

    def _sekil_sec(self, sekil: str) -> None:
        self._aktif_sekil = sekil
        for kod, btn in self._sekil_butonlari.items():
            if kod == sekil:
                btn.configure(bg=SARİ, fg=KOYU_GRI, activebackground="#E0B000")
            else:
                btn.configure(bg=KOYU_GRI, fg=SARİ, activebackground="#1a1d20")

        acik = sekil == ACIK
        if acik:
            self.hesap_cb.configure(state="disabled")
            self.hesap_var.set("")
            kalan = self._kalan()
            self.tutar_var.set(f"{kalan:.2f}".replace(".", ",") if kalan > 0 else "0,00")
        else:
            self.hesap_cb.configure(state="readonly")
            adlar = HizliSatisService.hesap_adlari(sekil)
            self.hesap_cb["values"] = adlar
            self.hesap_var.set(adlar[0] if adlar else "")

        if sekil == KK:
            self.kk_frame.grid()
        else:
            self.kk_frame.grid_remove()

        if sekil == NAKİT:
            self.nakit_frame.grid()
        else:
            self.nakit_frame.grid_remove()

        self._para_ustu_guncelle()
        self.after_idle(self._orta_scroll_guncelle)

    def _tamami_yaz(self) -> None:
        self._tutar_yaz(self._kalan() if self._kalan() > 0 else self.genel_toplam)

    def _tutar_yaz(self, tutar: Decimal) -> None:
        self.tutar_var.set(f"{_kurus(tutar):.2f}".replace(".", ","))

    def _tahsil_edilen(self) -> Decimal:
        return _kurus(sum((_kurus(s["tutar"]) for s in self.odeme_satirlari), Decimal("0")))

    def _kalan(self) -> Decimal:
        return _kurus(self.genel_toplam - self._tahsil_edilen())

    def _para_ustu_guncelle(self) -> None:
        if self._aktif_sekil != NAKİT:
            self.para_ustu_lbl.configure(text="")
            return
        try:
            alinan = _parse_tutar(self.tutar_var.get())
        except ValueError:
            self.para_ustu_lbl.configure(text="")
            return
        kalan = self._kalan()
        if alinan > kalan > 0:
            self.para_ustu_lbl.configure(text=f"Para üstü: {_para(alinan - kalan)}")
        elif alinan > self.genel_toplam and not self.odeme_satirlari:
            self.para_ustu_lbl.configure(text=f"Para üstü: {_para(alinan - self.genel_toplam)}")
        else:
            self.para_ustu_lbl.configure(text="")

    def _ozet_yenile(self) -> None:
        ed = self._tahsil_edilen()
        kalan = self._kalan()
        self.ozet_lbl.configure(
            text=(
                f"Tahsil edilen: {_para(ed)}   |   "
                f"Kalan (açık hesap): {_para(kalan)}"
            )
        )
        self._para_ustu_guncelle()

    def _liste_yenile(self) -> None:
        for i in self.liste.get_children():
            self.liste.delete(i)
        for idx, s in enumerate(self.odeme_satirlari):
            self.liste.insert(
                "",
                "end",
                iid=str(idx),
                values=(s["odeme_sekli"], s.get("hesap") or "—", _para(s["tutar"])),
            )
        self._ozet_yenile()

    def _odeme_ekle(self) -> None:
        try:
            tutar = _parse_tutar(self.tutar_var.get())
        except ValueError as hata:
            messagebox.showwarning("Tutar", str(hata), parent=self)
            return
        if tutar <= 0:
            messagebox.showwarning("Tutar", "Tutar sıfırdan büyük olmalı.", parent=self)
            return

        kalan = self._kalan()
        sekil = self._aktif_sekil

        if sekil == ACIK:
            if not yetki_var(IZIN_ACIK_HESAP):
                messagebox.showerror(
                    "Yetki",
                    "Açık hesap için «hizli_satis_acik_hesap» yetkisi gerekir.",
                    parent=self,
                )
                return
            # Açık hesap satırı listeye yazılmaz; kalan otomatik açık kalır.
            # Kullanıcıya bilgi: tutarı listeye ekleme, doğrudan onayda kalan işlenir.
            if self._tahsil_edilen() + tutar < self.genel_toplam and tutar < kalan:
                # Kısmi açık: diğer ödemeler zaten listede; kalan onayda açık hesap
                messagebox.showinfo(
                    "Açık hesap",
                    f"Kalan {_para(kalan)} açık hesapta bırakılacak. "
                    "Ek ödeme eklemeden «Satışı Onayla»ya basın.",
                    parent=self,
                )
                return
            messagebox.showinfo(
                "Açık hesap",
                "Tamamı veya kalan açık hesap için doğrudan «Satışı Onayla» kullanın "
                "(ödeme satırı eklenmez).",
                parent=self,
            )
            return

        # Nakit: fazla girildiyse yalnızca kalan kadar tahsilat, para üstü bilgilendirme
        kayit_tutar = tutar
        if sekil == NAKİT and tutar > kalan:
            kayit_tutar = kalan
            if kayit_tutar <= 0:
                messagebox.showinfo("Tahsilat", "Kalan tutar yok.", parent=self)
                return
            messagebox.showinfo(
                "Para üstü",
                f"Tahsil edilecek: {_para(kayit_tutar)}\nPara üstü: {_para(tutar - kayit_tutar)}",
                parent=self,
            )
        elif tutar > kalan:
            messagebox.showwarning(
                "Tutar",
                f"Kalan tutarı ({_para(kalan)}) aşamaz.",
                parent=self,
            )
            return

        hesap = self.hesap_var.get().strip()
        if not hesap:
            messagebox.showwarning(
                "Hesap",
                "Bu ödeme şekli için uygun kasa/banka/POS hesabı seçin.",
                parent=self,
            )
            return

        aciklama = "Hızlı satış tahsilatı"
        if sekil == KK:
            banka = self.kk_banka_var.get().strip()
            taksit = self.kk_taksit_var.get().strip() or "1"
            parcalar = []
            if banka:
                parcalar.append(f"Banka: {banka}")
            parcalar.append(f"Taksit: {taksit}")
            aciklama = " | ".join(parcalar)

        self.odeme_satirlari.append(
            {
                "odeme_sekli": sekil,
                "hesap": hesap,
                "tutar": kayit_tutar,
                "aciklama": aciklama,
            }
        )
        self._liste_yenile()
        yeni_kalan = self._kalan()
        self.tutar_var.set(f"{yeni_kalan:.2f}".replace(".", ",") if yeni_kalan > 0 else "0,00")

    def _satir_sil(self) -> None:
        sec = self.liste.selection()
        if not sec:
            return
        try:
            idx = int(sec[0])
        except ValueError:
            return
        if 0 <= idx < len(self.odeme_satirlari):
            self.odeme_satirlari.pop(idx)
            self._liste_yenile()

    def _iptal(self) -> None:
        self.result = None
        self.destroy()

    def _tamamla(self) -> None:
        # Formdan tek satır (liste boşsa)
        if not self.odeme_satirlari and self._aktif_sekil != ACIK:
            try:
                tutar = _parse_tutar(self.tutar_var.get())
            except ValueError as hata:
                messagebox.showwarning("Tutar", str(hata), parent=self)
                return
            hesap = self.hesap_var.get().strip()
            if not hesap:
                messagebox.showwarning(
                    "Hesap",
                    "Kasa/banka/POS hesabı seçin veya açık hesap kullanın.",
                    parent=self,
                )
                return
            kayit = tutar
            if self._aktif_sekil == NAKİT and tutar > self.genel_toplam:
                messagebox.showinfo(
                    "Para üstü",
                    f"Tahsil: {_para(self.genel_toplam)}\nPara üstü: {_para(tutar - self.genel_toplam)}",
                    parent=self,
                )
                kayit = self.genel_toplam
            if kayit <= 0:
                messagebox.showwarning("Tutar", "Tutar sıfırdan büyük olmalı.", parent=self)
                return
            if kayit > self.genel_toplam:
                messagebox.showwarning("Tutar", "Tutar genel toplamı aşamaz.", parent=self)
                return
            aciklama = "Hızlı satış tahsilatı"
            if self._aktif_sekil == KK:
                banka = self.kk_banka_var.get().strip()
                taksit = self.kk_taksit_var.get().strip() or "1"
                aciklama = f"Banka: {banka or '—'} | Taksit: {taksit}"
            self.odeme_satirlari.append(
                {
                    "odeme_sekli": self._aktif_sekil,
                    "hesap": hesap,
                    "tutar": _kurus(kayit),
                    "aciklama": aciklama,
                }
            )
            self._liste_yenile()

        kalan = self._kalan()
        if kalan > 0:
            if not yetki_var(IZIN_ACIK_HESAP):
                messagebox.showerror(
                    "Açık hesap",
                    f"Kalan {_para(kalan)} için açık hesap yetkisi gerekir "
                    "veya ödemeyi tamamlayın.",
                    parent=self,
                )
                return
            if not messagebox.askyesno(
                "Açık hesap",
                f"Kalan {_para(kalan)} cariye açık hesap yazılacak. Devam?",
                parent=self,
            ):
                return

        if self._tahsil_edilen() <= 0 and kalan != self.genel_toplam:
            messagebox.showwarning("Tahsilat", "Ödeme bilgisi eksik.", parent=self)
            return

        if not self.odeme_satirlari and kalan == self.genel_toplam:
            if not yetki_var(IZIN_ACIK_HESAP):
                messagebox.showerror(
                    "Yetki",
                    "Açık hesap satışı için yetki gerekir.",
                    parent=self,
                )
                return

        self.result = list(self.odeme_satirlari)
        if self.on_onay:
            try:
                self.on_onay(self.result)
            except Exception as hata:
                messagebox.showerror("Kayıt hatası", str(hata), parent=self)
                self.result = None
                return
        self.destroy()


def tahsilat_goster(
    parent,
    *,
    genel_toplam,
    musteri_unvan: str = "",
    musteri_bakiye=None,
    risk_limiti=None,
) -> list[dict[str, Any]] | None:
    """Modal tahsilat; onaylanırsa ödeme satırları listesi, iptalde None."""
    dlg = HizliSatisTahsilatDialog(
        parent,
        genel_toplam=genel_toplam,
        musteri_unvan=musteri_unvan,
        musteri_bakiye=musteri_bakiye,
        risk_limiti=risk_limiti,
    )
    parent.wait_window(dlg)
    return dlg.result
