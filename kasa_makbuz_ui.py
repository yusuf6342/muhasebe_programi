"""Kasa tahsilat makbuzu ve ödeme makbuzu."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, ttk

from database.cari_service import CariService
from database.finans_service import FinansService
from database.satis_siparisi_service import decimal
from ui_takvim import tarih_alani


def _para(tutar):
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _kasa_etiket(h):
    if not h:
        return ""
    bak = FinansService.bakiye(h)
    return f"{h.hesap_adi}  ({_para(bak)})"


def _cari_etiket(cari):
    return f"{cari.cari_kodu} - {cari.unvan}"


class KasaMakbuzDialog(tk.Toplevel):
    """Tahsilat makbuzu (kasaya giriş) veya ödeme makbuzu (kasadan çıkış)."""

    def __init__(self, parent, makbuz_turu: str, finans_hesap_id=None):
        super().__init__(parent)
        self.result = None
        self.makbuz_turu = (makbuz_turu or "").strip().upper()
        if self.makbuz_turu not in ("TAHSILAT", "ODEME"):
            raise ValueError("makbuz_turu TAHSILAT veya ODEME olmalıdır.")

        tahsilat = self.makbuz_turu == "TAHSILAT"
        self.title("Tahsilat Makbuzu" if tahsilat else "Ödeme Makbuzu")
        self.geometry("560x420")
        self.minsize(520, 380)
        self.transient(parent)
        self.grab_set()

        kasalar = FinansService.kasa_hesaplari()
        self.kasa_map = {_kasa_etiket(h): h for h in kasalar}
        self._tum_kasa_etiketleri = list(self.kasa_map)

        cariler = CariService.listele()
        self.cari_map = {}
        self._tum_cari_etiketleri = []
        for o in cariler:
            cari = o["cari"]
            etiket = _cari_etiket(cari)
            self.cari_map[etiket] = cari.id
            self._tum_cari_etiketleri.append(etiket)

        form = ttk.Frame(self, padding=14)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)

        self.girdiler = {}
        tarih_alani(
            form,
            0,
            "Tarih *",
            "tarih",
            date.today().strftime("%d.%m.%Y"),
            self.girdiler,
        )

        cari_etiket = "Cari hesap * (gönderen)" if tahsilat else "Cari hesap * (alıcı)"
        ttk.Label(form, text=cari_etiket).grid(row=1, column=0, sticky="nw", padx=4, pady=6)
        cari_c = ttk.Frame(form)
        cari_c.grid(row=1, column=1, sticky="ew", padx=4, pady=6)
        cari_c.columnconfigure(0, weight=1)
        self.cari_var = tk.StringVar()
        self.cari_combo = ttk.Combobox(
            cari_c,
            textvariable=self.cari_var,
            values=self._tum_cari_etiketleri,
            width=42,
        )
        self.cari_combo.grid(row=0, column=0, sticky="ew")
        self.cari_combo.bind("<KeyRelease>", self._cari_filtrele)
        ttk.Label(
            cari_c,
            text="Aramak için cari adından en az 3 harf yazın.",
            foreground="#555",
            font=("Segoe UI", 8),
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        ttk.Label(form, text="Kasa *").grid(row=2, column=0, sticky="nw", padx=4, pady=6)
        kasa_c = ttk.Frame(form)
        kasa_c.grid(row=2, column=1, sticky="ew", padx=4, pady=6)
        kasa_c.columnconfigure(0, weight=1)
        self.kasa_var = tk.StringVar()
        self.kasa_combo = ttk.Combobox(
            kasa_c,
            textvariable=self.kasa_var,
            values=self._tum_kasa_etiketleri,
            width=42,
        )
        self.kasa_combo.grid(row=0, column=0, sticky="ew")
        self.kasa_combo.bind("<KeyRelease>", self._kasa_filtrele)
        if finans_hesap_id:
            for etiket, h in self.kasa_map.items():
                if h.id == int(finans_hesap_id):
                    self.kasa_var.set(etiket)
                    break
        elif self.kasa_map:
            self.kasa_combo.current(0)

        ttk.Label(form, text="Tutar *").grid(row=3, column=0, sticky="w", padx=4, pady=6)
        self.tutar = ttk.Entry(form, width=18)
        self.tutar.grid(row=3, column=1, sticky="w", padx=4, pady=6)

        ttk.Label(form, text="Makbuz no").grid(row=4, column=0, sticky="w", padx=4, pady=6)
        self.makbuz_no = ttk.Entry(form, width=24)
        self.makbuz_no.grid(row=4, column=1, sticky="w", padx=4, pady=6)

        ttk.Label(form, text="Açıklama").grid(row=5, column=0, sticky="nw", padx=4, pady=6)
        self.aciklama = ttk.Entry(form, width=42)
        self.aciklama.grid(row=5, column=1, sticky="ew", padx=4, pady=6)

        ipucu = (
            "Cariden nakit tahsilat — kasaya giriş yazılır."
            if tahsilat
            else "Cariye nakit ödeme — kasadan çıkış yazılır."
        )
        ttk.Label(form, text=ipucu, foreground="#555", wraplength=420).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )

        alt = ttk.Frame(self, padding=(14, 8))
        alt.pack(fill="x", side="bottom")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(alt, text="Kaydet", width=12, command=self.kaydet).pack(side="right")

    def _cari_filtrele(self, _event=None):
        metin = self.cari_var.get().strip()
        if not metin:
            self.cari_combo["values"] = self._tum_cari_etiketleri
            return
        if len(metin) < 3:
            self.cari_combo["values"] = ()
            return
        ara = metin.casefold()
        self.cari_combo["values"] = [
            e for e in self._tum_cari_etiketleri if ara in e.casefold()
        ]

    def _kasa_filtrele(self, _event=None):
        metin = self.kasa_var.get().strip()
        if not metin:
            self.kasa_combo["values"] = self._tum_kasa_etiketleri
            return
        if len(metin) < 3:
            self.kasa_combo["values"] = ()
            return
        ara = metin.casefold()
        bulunan = []
        for etiket, h in self.kasa_map.items():
            ad = (h.hesap_adi or "").casefold()
            if ara in ad or ara in etiket.casefold():
                bulunan.append(etiket)
        self.kasa_combo["values"] = bulunan

    def kaydet(self):
        try:
            cari_metin = (self.cari_var.get() or "").strip()
            cari_id = self.cari_map.get(cari_metin) if cari_metin else None
            if not cari_id:
                raise ValueError("Cari hesap seçin.")
            hesap = self.kasa_map.get(self.kasa_var.get())
            if not hesap:
                raise ValueError("Kasa seçin.")
            tarih = datetime.strptime(self.girdiler["tarih"].get(), "%d.%m.%Y").date()
            tutar = decimal(self.tutar.get(), "Tutar", Decimal("0.01"))
            veriler = {
                "tarih": tarih,
                "finans_hesap_id": hesap.id,
                "cari_id": cari_id,
                "tutar": tutar,
                "makbuz_no": self.makbuz_no.get().strip() or None,
                "aciklama": self.aciklama.get().strip() or None,
            }
            if self.makbuz_turu == "TAHSILAT":
                self.result = FinansService.kasa_tahsilat_makbuzu_kaydet(veriler)
            else:
                self.result = FinansService.kasa_odeme_makbuzu_kaydet(veriler)
        except ValueError as hata:
            messagebox.showerror(self.title(), str(hata), parent=self)
            return
        messagebox.showinfo(
            "Kaydedildi",
            f"{self.result.belge_no} — {_para(self.result.tutar)}",
            parent=self,
        )
        self.destroy()


def kasa_makbuzlari_sayfasi(app, makbuz_turu=None, geri_fn=None):
    """Makbuz listesi (isteğe bağlı filtre: TAHSILAT / ODEME)."""
    from finans_ui import finans_menusu_goster, _finans_menu_isaretle

    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    geri = geri_fn or finans_menusu_goster

    if makbuz_turu == "TAHSILAT":
        baslik = "TAHSİLAT MAKBUZLARI"
    elif makbuz_turu == "ODEME":
        baslik = "ÖDEME MAKBUZLARI"
    else:
        baslik = "KASA MAKBUZLARI"

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Geri", command=lambda: geri(app)).pack(side="right")

    ttk.Label(
        app.icerik,
        text="Kasa üzerinden cari tahsilat (TMK) ve ödeme (OMK) makbuzları.",
    ).pack(anchor="w", pady=(10, 4))

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True, pady=6)
    tablo = ttk.Treeview(
        cerceve,
        columns=("belge", "tarih", "tur", "kasa", "cari", "tutar", "durum", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("belge", "Belge", 110),
        ("tarih", "Tarih", 90),
        ("tur", "Tür", 90),
        ("kasa", "Kasa", 140),
        ("cari", "Cari", 200),
        ("tutar", "Tutar", 110),
        ("durum", "Durum", 70),
        ("aciklama", "Açıklama", 200),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")

    def yenile():
        for item in tablo.get_children():
            tablo.delete(item)
        for m in FinansService.kasa_makbuz_listele(makbuz_turu=makbuz_turu):
            cari = getattr(m, "cari", None)
            tablo.insert(
                "",
                "end",
                iid=str(m.id),
                values=(
                    m.belge_no,
                    m.tarih.strftime("%d.%m.%Y") if m.tarih else "",
                    "Tahsilat" if m.makbuz_turu == "TAHSILAT" else "Ödeme",
                    m.finans_hesap.hesap_adi if m.finans_hesap else "—",
                    f"{cari.cari_kodu} - {cari.unvan}" if cari else "—",
                    _para(m.tutar),
                    m.durum,
                    (m.aciklama or "")[:80],
                ),
            )

    def yeni(tur):
        dlg = KasaMakbuzDialog(app, makbuz_turu=tur)
        app.wait_window(dlg)
        if dlg.result:
            yenile()

    def iptal():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Bir makbuz seçin.", parent=app)
            return
        if not messagebox.askyesno("İptal", "Makbuz iptal edilsin mi?", parent=app):
            return
        try:
            FinansService.kasa_makbuz_iptal(int(secim[0]))
        except ValueError as hata:
            messagebox.showerror("İptal", str(hata), parent=app)
            return
        yenile()

    def ac(_event=None):
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Bir makbuz seçin.", parent=app)
            return
        degerler = tablo.item(secim[0], "values")
        belge_no = (degerler[0] if degerler else "") or ""
        if not belge_no:
            return
        from belge_onizleme_ui import kasa_makbuz_onizle

        kasa_makbuz_onizle(app, belge_no)

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=6)
    if makbuz_turu in (None, "TAHSILAT"):
        ttk.Button(
            butonlar, text="Yeni Tahsilat Makbuzu", command=lambda: yeni("TAHSILAT")
        ).pack(side="left")
    if makbuz_turu in (None, "ODEME"):
        ttk.Button(
            butonlar, text="Yeni Ödeme Makbuzu", command=lambda: yeni("ODEME")
        ).pack(side="left", padx=8)
    ttk.Button(butonlar, text="Belgeyi Aç", command=ac).pack(side="left", padx=8)
    ttk.Button(butonlar, text="İptal Et", command=iptal).pack(side="left", padx=8)
    ttk.Button(butonlar, text="Yenile", command=yenile).pack(side="left")
    tablo.bind("<Double-1>", ac)

    yenile()
