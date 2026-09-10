"""Gider fişi — cari yok, kasa/bankadan ödeme, gider hizmet kartı zorunlu."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, ttk

from database.finans_service import FinansService
from database.models.hizmet import gider_sinifi_etiket
from database.satis_siparisi_service import decimal
from ui_takvim import tarih_alani


def _para(tutar):
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(t):
    return t.strftime("%d.%m.%Y") if t else ""


def _hesap_etiket(h, bakiye_goster=False):
    if not h:
        return ""
    alt = (h.alt_hesap_turu or "").replace("_", " ")
    if (h.hesap_turu or "").upper() == "KASA":
        etiket = f"Kasa — {h.hesap_adi}"
    else:
        etiket = f"{h.hesap_adi}" + (f" ({alt})" if alt else "")
    if bakiye_goster:
        etiket = f"{etiket}  ({_para(FinansService.bakiye(h))})"
    return etiket


class GiderFisiDialog(tk.Toplevel):
    """Cari hesabı olmayan gider fişi; hizmet kartı + ödeme hesabı."""

    def __init__(self, parent, finans_hesap_id=None):
        super().__init__(parent)
        self.result = None
        self.hizmet_id = None
        self.title("Gider Fişi")
        self.geometry("620x440")
        self.minsize(560, 400)
        self.transient(parent)
        self.grab_set()

        hesaplar = FinansService.gider_fisi_odeme_hesaplari()
        self.hesap_map = {_hesap_etiket(h, bakiye_goster=True): h for h in hesaplar}
        self._tum_etiketler = list(self.hesap_map)

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

        ttk.Label(form, text="Ödeme hesabı *").grid(row=1, column=0, sticky="nw", padx=4, pady=6)
        hesap_cerceve = ttk.Frame(form)
        hesap_cerceve.grid(row=1, column=1, sticky="ew", padx=4, pady=6)
        hesap_cerceve.columnconfigure(0, weight=1)
        self.hesap_var = tk.StringVar()
        self.hesap_combo = ttk.Combobox(
            hesap_cerceve,
            textvariable=self.hesap_var,
            values=self._tum_etiketler,
            width=48,
        )
        self.hesap_combo.grid(row=0, column=0, sticky="ew")
        self.hesap_combo.bind("<KeyRelease>", self._hesap_filtrele)
        ttk.Label(
            hesap_cerceve,
            text="Aramak için kasa/banka adından en az 3 harf yazın.",
            foreground="#555",
            font=("Segoe UI", 8),
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        if finans_hesap_id:
            for etiket, h in self.hesap_map.items():
                if h.id == int(finans_hesap_id):
                    self.hesap_var.set(etiket)
                    break
        elif self.hesap_map:
            self.hesap_combo.current(0)

        ttk.Label(form, text="Gider hizmeti *").grid(row=2, column=0, sticky="w", padx=4, pady=6)
        hz = ttk.Frame(form)
        hz.grid(row=2, column=1, sticky="ew", padx=4, pady=6)
        self.hizmet_lbl = ttk.Label(hz, text="— seçilmedi —", width=36)
        self.hizmet_lbl.pack(side="left")
        ttk.Button(hz, text="Seç", command=self.hizmet_sec).pack(side="left", padx=4)
        ttk.Button(hz, text="Yeni Kart", command=self.hizmet_yeni).pack(side="left")

        ttk.Label(form, text="Tutar *").grid(row=3, column=0, sticky="w", padx=4, pady=6)
        self.tutar = ttk.Entry(form, width=18)
        self.tutar.grid(row=3, column=1, sticky="w", padx=4, pady=6)

        ttk.Label(form, text="Açıklama").grid(row=4, column=0, sticky="nw", padx=4, pady=6)
        self.aciklama = ttk.Entry(form, width=42)
        self.aciklama.grid(row=4, column=1, sticky="ew", padx=4, pady=6)

        ttk.Label(
            form,
            text="Cari hesap gerekmez. Örnek: kasadan ekmek alımı → işletme gideri hizmet kartı.",
            foreground="#555",
            wraplength=420,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))

        alt = ttk.Frame(self, padding=(14, 8))
        alt.pack(fill="x", side="bottom")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(alt, text="Kaydet", width=12, command=self.kaydet).pack(side="right")

    def _hesap_filtrele(self, _event=None):
        metin = self.hesap_var.get().strip()
        if not metin:
            self.hesap_combo["values"] = self._tum_etiketler
            return
        if len(metin) < 3:
            self.hesap_combo["values"] = ()
            return
        ara = metin.casefold()
        bulunan = []
        for etiket, h in self.hesap_map.items():
            ad = (h.hesap_adi or "").casefold()
            if ara in ad or ara in etiket.casefold():
                bulunan.append(etiket)
        self.hesap_combo["values"] = bulunan

    def _hizmet_yaz(self, hizmet):
        if not hizmet:
            self.hizmet_id = None
            self.hizmet_lbl.configure(text="— seçilmedi —")
            return
        self.hizmet_id = hizmet.id
        sinif = gider_sinifi_etiket(hizmet.gider_sinifi)
        self.hizmet_lbl.configure(
            text=f"{hizmet.hizmet_kodu} — {hizmet.hizmet_adi} ({sinif})"
        )

    def hizmet_sec(self):
        from hizmet_fatura_ui import HizmetSecDialog

        dlg = HizmetSecDialog(self, "GIDER")
        self.wait_window(dlg)
        if dlg.result:
            self._hizmet_yaz(dlg.result)

    def hizmet_yeni(self):
        from gelir_gider_ui import HizmetKartiDialog

        dlg = HizmetKartiDialog(self, hizmet_turu="GIDER")
        self.wait_window(dlg)
        if dlg.result:
            self._hizmet_yaz(dlg.result)

    def kaydet(self):
        try:
            hesap = self.hesap_map.get(self.hesap_var.get())
            if not hesap:
                raise ValueError("Ödeme hesabı seçin.")
            if not self.hizmet_id:
                raise ValueError("Gider hizmet kartı seçin.")
            tarih = datetime.strptime(self.girdiler["tarih"].get(), "%d.%m.%Y").date()
            tutar = decimal(self.tutar.get(), "Tutar", Decimal("0.01"))
            self.result = FinansService.gider_fisi_kaydet(
                {
                    "tarih": tarih,
                    "finans_hesap_id": hesap.id,
                    "hizmet_id": self.hizmet_id,
                    "tutar": tutar,
                    "aciklama": self.aciklama.get().strip() or None,
                }
            )
        except ValueError as hata:
            messagebox.showerror("Gider fişi", str(hata), parent=self)
            return
        messagebox.showinfo(
            "Kaydedildi",
            f"{self.result.belge_no} — {_para(self.result.tutar)}",
            parent=self,
        )
        self.destroy()


def gider_fisleri_sayfasi(app, geri_fn=None):
    """Gider fişi listesi + yeni fiş."""
    from gelir_gider_ui import _menu_isaretle, giderler_menusu_goster

    app._icerigi_temizle()
    _menu_isaretle(app)
    geri = geri_fn or giderler_menusu_goster

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="GİDER FİŞİ", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Geri", command=lambda: geri(app)).pack(side="right")

    ttk.Label(
        app.icerik,
        text="Kasa/bankadan cari olmadan ödeme. Hizmet kartı ile gider sınıfı takip edilir.",
    ).pack(anchor="w", pady=(10, 4))

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True, pady=6)
    tablo = ttk.Treeview(
        cerceve,
        columns=("belge", "tarih", "hesap", "hizmet", "tutar", "durum", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("belge", "Belge", 100),
        ("tarih", "Tarih", 90),
        ("hesap", "Hesap", 160),
        ("hizmet", "Hizmet", 200),
        ("tutar", "Tutar", 100),
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
        for f in FinansService.gider_fisi_listele():
            hiz = f.hizmet
            tablo.insert(
                "",
                "end",
                iid=str(f.id),
                values=(
                    f.belge_no,
                    _tarih(f.tarih),
                    _hesap_etiket(f.finans_hesap) if f.finans_hesap else "—",
                    f"{hiz.hizmet_kodu} — {hiz.hizmet_adi}" if hiz else "—",
                    _para(f.tutar),
                    f.durum,
                    (f.aciklama or "")[:80],
                ),
            )

    def yeni(hesap_id=None):
        dlg = GiderFisiDialog(app, finans_hesap_id=hesap_id)
        app.wait_window(dlg)
        if dlg.result:
            yenile()

    def iptal():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Bir fiş seçin.", parent=app)
            return
        if not messagebox.askyesno("İptal", "Gider fişi iptal edilsin mi?", parent=app):
            return
        try:
            FinansService.gider_fisi_iptal(int(secim[0]))
        except ValueError as hata:
            messagebox.showerror("İptal", str(hata), parent=app)
            return
        yenile()

    def ac(_event=None):
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Bir fiş seçin.", parent=app)
            return
        degerler = tablo.item(secim[0], "values")
        belge_no = (degerler[0] if degerler else "") or ""
        if not belge_no:
            return
        from belge_onizleme_ui import gider_fisi_onizle

        gider_fisi_onizle(app, belge_no)

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=6)
    ttk.Button(butonlar, text="Yeni Gider Fişi", command=lambda: yeni()).pack(side="left")
    ttk.Button(butonlar, text="Belgeyi Aç", command=ac).pack(side="left", padx=8)
    ttk.Button(butonlar, text="İptal Et", command=iptal).pack(side="left", padx=8)
    ttk.Button(butonlar, text="Yenile", command=yenile).pack(side="left")
    tablo.bind("<Double-1>", ac)

    yenile()
