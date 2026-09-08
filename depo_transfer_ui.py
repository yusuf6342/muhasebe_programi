"""Depolar arası transfer fişi arayüzü."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, ttk

from database.stok_service import StokService
from database.satis_siparisi_service import decimal
from ui_takvim import takvim_butonu
from urun_sec_ui import UrunSecDialog


def _para(tutar):
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(t):
    return t.strftime("%d.%m.%Y") if t else ""


class DepoTransferFisiDialog(tk.Toplevel):
    """Çıkış/giriş deposu, miktar, birim fiyat (çıkış deposundan varsayılan) ve tutar."""

    def __init__(self, parent, fis=None):
        super().__init__(parent)
        self.result = None
        self.fis = fis
        self.satirlar = []
        self.title("Depo Transfer Fişi" + (f" — {fis.fis_no}" if fis else ""))
        self.geometry("980x620")
        self.minsize(860, 520)
        self.transient(parent)
        self.grab_set()

        ust = ttk.LabelFrame(self, text="Fiş Bilgileri", padding=10)
        ust.pack(fill="x", padx=12, pady=10)
        for col in range(6):
            ust.columnconfigure(col, weight=1 if col % 2 == 1 else 0)

        ttk.Label(ust, text="Fiş No").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.fis_no = ttk.Entry(ust, width=18)
        self.fis_no.grid(row=0, column=1, sticky="w", padx=4, pady=4)
        self.fis_no.insert(0, fis.fis_no if fis else StokService.depo_transfer_fis_no())
        self.fis_no.configure(state="readonly")

        ttk.Label(ust, text="Tarih").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        tarih_cerceve = ttk.Frame(ust)
        tarih_cerceve.grid(row=0, column=3, sticky="w", padx=4, pady=4)
        self.tarih = ttk.Entry(tarih_cerceve, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, _tarih(fis.fis_tarihi) if fis else _tarih(date.today()))
        takvim_butonu(tarih_cerceve, self.tarih)

        depolar = tuple(d.ad for d in StokService.depolar()) or ("ANA DEPO",)
        ttk.Label(ust, text="Çıkış Deposu").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self.cikis_depo = ttk.Combobox(ust, values=depolar, state="readonly", width=28)
        self.cikis_depo.grid(row=1, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(ust, text="Giriş Deposu").grid(row=1, column=2, sticky="w", padx=4, pady=4)
        self.giris_depo = ttk.Combobox(ust, values=depolar, state="readonly", width=28)
        self.giris_depo.grid(row=1, column=3, sticky="w", padx=4, pady=4)
        if fis:
            self.cikis_depo.set(fis.cikis_depo)
            self.giris_depo.set(fis.giris_depo)
        else:
            if depolar:
                self.cikis_depo.current(0)
            if len(depolar) > 1:
                self.giris_depo.current(1)
            elif depolar:
                self.giris_depo.current(0)

        ttk.Label(ust, text="Açıklama").grid(row=2, column=0, sticky="w", padx=4, pady=4)
        self.aciklama = ttk.Entry(ust, width=70)
        self.aciklama.grid(row=2, column=1, columnspan=3, sticky="ew", padx=4, pady=4)
        if fis and fis.aciklama:
            self.aciklama.insert(0, fis.aciklama)

        satir_cerceve = ttk.LabelFrame(self, text="Transfer Satırları", padding=10)
        satir_cerceve.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        form = ttk.Frame(satir_cerceve)
        form.pack(fill="x")
        self.urun_kodu = ttk.Entry(form, width=14)
        self.urun_adi = ttk.Entry(form, width=28)
        self.birim = ttk.Combobox(form, values=("Adet", "Kg", "Metre", "Koli", "Paket"), width=8)
        self.birim.set("Adet")
        self.miktar = ttk.Entry(form, width=10)
        self.birim_fiyat = ttk.Entry(form, width=12)
        self.tutar = ttk.Entry(form, width=12, state="readonly")
        self.miktar.insert(0, "1")
        self.birim_fiyat.insert(0, "0")
        alanlar = (
            ("Kod", self.urun_kodu),
            ("Ürün Adı", self.urun_adi),
            ("Birim", self.birim),
            ("Miktar", self.miktar),
            ("Birim Fiyat", self.birim_fiyat),
            ("Tutar", self.tutar),
        )
        for i, (etiket, widget) in enumerate(alanlar):
            ttk.Label(form, text=etiket).grid(row=0, column=i, sticky="w", padx=3)
            widget.grid(row=1, column=i, sticky="w", padx=3, pady=2)
        butonlar = ttk.Frame(form)
        butonlar.grid(row=1, column=len(alanlar), sticky="w", padx=8)
        ttk.Button(butonlar, text="Stok Seç", command=self.stok_sec).pack(side="left", padx=2)
        ttk.Button(butonlar, text="Satır Ekle", command=self.satir_ekle).pack(side="left", padx=2)
        ttk.Button(butonlar, text="Satır Sil", command=self.satir_sil).pack(side="left", padx=2)
        ttk.Label(
            form,
            text="Birim fiyat: çıkış deposundaki maliyet (manuel değiştirilebilir)",
            foreground="#666666",
        ).grid(row=2, column=0, columnspan=6, sticky="w", pady=(4, 0))

        self.miktar.bind("<KeyRelease>", self._tutar_guncelle)
        self.birim_fiyat.bind("<KeyRelease>", self._tutar_guncelle)
        self.cikis_depo.bind("<<ComboboxSelected>>", self._cikis_depo_degisti)

        kolonlar = ("kod", "ad", "birim", "miktar", "fiyat", "tutar")
        self.tablo = ttk.Treeview(satir_cerceve, columns=kolonlar, show="headings", height=12)
        basliklar = {
            "kod": "Ürün Kodu",
            "ad": "Ürün Adı",
            "birim": "Birim",
            "miktar": "Miktar",
            "fiyat": "Birim Fiyat",
            "tutar": "Tutar",
        }
        for kolon in kolonlar:
            self.tablo.heading(kolon, text=basliklar[kolon])
            self.tablo.column(kolon, width=120, anchor="w")
        self.tablo.column("ad", width=260)
        self.tablo.pack(fill="both", expand=True, pady=8)
        self.tablo.bind("<<TreeviewSelect>>", self._satir_secildi)

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=10)
        self.toplam_etiket = ttk.Label(alt, text="Genel Toplam: 0,00 TL", font=("Segoe UI", 11, "bold"))
        self.toplam_etiket.pack(side="left")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        self.kaydet_btn = ttk.Button(alt, text="Kaydet (F1)", command=self.kaydet)
        self.kaydet_btn.pack(side="right", padx=8)
        self.bind_all("<F1>", self._f1)
        self.protocol("WM_DELETE_WINDOW", self._kapat)

        if fis:
            for s in fis.satirlar:
                self.satirlar.append(
                    {
                        "urun_kodu": s.urun_kodu,
                        "urun_adi": s.urun_adi,
                        "birim": s.birim,
                        "miktar": s.miktar,
                        "birim_fiyat": s.birim_fiyat,
                        "tutar": s.tutar,
                    }
                )
            self._listeyi_yenile()
            # Kayıtlı fiş sadece görüntüleme
            self.kaydet_btn.configure(state="disabled")
            for w in (
                self.tarih,
                self.cikis_depo,
                self.giris_depo,
                self.aciklama,
                self.urun_kodu,
                self.urun_adi,
                self.miktar,
                self.birim_fiyat,
            ):
                try:
                    w.configure(state="disabled")
                except tk.TclError:
                    pass

    def _f1(self, _e=None):
        if str(self.kaydet_btn.cget("state")) != "disabled":
            self.kaydet()
        return "break"

    def _kapat(self):
        try:
            self.unbind_all("<F1>")
        except tk.TclError:
            pass
        self.destroy()

    def _tutar_guncelle(self, _e=None):
        try:
            m = decimal(self.miktar.get() or 0, "Miktar", Decimal("0"))
            f = decimal(self.birim_fiyat.get() or 0, "Fiyat", Decimal("0"))
            t = m * f
        except ValueError:
            t = Decimal("0")
        self.tutar.configure(state="normal")
        self.tutar.delete(0, "end")
        self.tutar.insert(0, f"{t:f}".rstrip("0").rstrip(".") or "0")
        self.tutar.configure(state="readonly")

    def _cikis_depo_degisti(self, _e=None):
        kod = self.urun_kodu.get().strip()
        if kod:
            self._fiyat_doldur(kod)

    def _fiyat_doldur(self, kod):
        depo = self.cikis_depo.get().strip()
        maliyetler = StokService.maliyetler(kod, depo) if depo else {}
        # Çıkış deposundaki fiyat: ağırlıklı ortalama, yoksa FIFO
        fiyat = maliyetler.get("agirlikli") or maliyetler.get("fifo") or Decimal("0")
        self.birim_fiyat.delete(0, "end")
        self.birim_fiyat.insert(0, f"{fiyat:f}".rstrip("0").rstrip(".") or "0")
        self._tutar_guncelle()

    def stok_sec(self):
        UrunSecDialog(self, on_select=self._urun_secildi)

    def _urun_secildi(self, degerler):
        kod = (degerler[0] or "").strip()
        self.urun_kodu.delete(0, "end")
        self.urun_kodu.insert(0, kod)
        self.urun_adi.delete(0, "end")
        self.urun_adi.insert(0, degerler[1] or "")
        self.birim.set(degerler[2] or "Adet")
        if not self.miktar.get().strip():
            self.miktar.insert(0, "1")
        self._fiyat_doldur(kod)
        try:
            self.miktar.focus_set()
        except tk.TclError:
            pass

    def satir_ekle(self):
        kod = self.urun_kodu.get().strip()
        ad = self.urun_adi.get().strip()
        if not kod or not ad:
            messagebox.showwarning("Eksik bilgi", "Önce stok seçin.", parent=self)
            return
        try:
            miktar = decimal(self.miktar.get() or 0, "Miktar", Decimal("0.0001"))
            fiyat = decimal(self.birim_fiyat.get() or 0, "Birim fiyat", Decimal("0"))
        except ValueError as hata:
            messagebox.showerror("Geçersiz satır", str(hata), parent=self)
            return
        self.satirlar.append(
            {
                "urun_kodu": kod,
                "urun_adi": ad,
                "birim": self.birim.get() or "Adet",
                "miktar": miktar,
                "birim_fiyat": fiyat,
                "tutar": miktar * fiyat,
            }
        )
        self._form_temizle()
        self._listeyi_yenile()

    def _form_temizle(self):
        for w in (self.urun_kodu, self.urun_adi, self.miktar, self.birim_fiyat):
            w.delete(0, "end")
        self.birim.set("Adet")
        self.miktar.insert(0, "1")
        self.birim_fiyat.insert(0, "0")
        self._tutar_guncelle()

    def satir_sil(self):
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("Satır sil", "Silinecek satırı seçin.", parent=self)
            return
        idx = int(secim[0])
        if 0 <= idx < len(self.satirlar):
            self.satirlar.pop(idx)
            self._listeyi_yenile()

    def _satir_secildi(self, _e=None):
        secim = self.tablo.selection()
        if not secim:
            return
        idx = int(secim[0])
        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        self._form_temizle()
        self.urun_kodu.insert(0, s["urun_kodu"])
        self.urun_adi.insert(0, s["urun_adi"])
        self.birim.set(s.get("birim") or "Adet")
        self.miktar.delete(0, "end")
        self.miktar.insert(0, str(s["miktar"]))
        self.birim_fiyat.delete(0, "end")
        self.birim_fiyat.insert(0, str(s["birim_fiyat"]))
        self._tutar_guncelle()

    def _listeyi_yenile(self):
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        genel = Decimal("0")
        for i, s in enumerate(self.satirlar):
            tutar = decimal(s.get("tutar", 0), "Tutar", Decimal("0"))
            genel += tutar
            self.tablo.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    s["urun_kodu"],
                    s["urun_adi"],
                    s.get("birim", "Adet"),
                    s["miktar"],
                    _para(s["birim_fiyat"]),
                    _para(tutar),
                ),
            )
        self.toplam_etiket.configure(text=f"Genel Toplam: {_para(genel)}")

    def kaydet(self):
        if self.fis:
            return
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
        except ValueError:
            messagebox.showerror("Tarih", "Tarih GG.AA.YYYY formatında olmalı.", parent=self)
            return
        if not self.satirlar:
            messagebox.showwarning("Satır", "En az bir satır ekleyin.", parent=self)
            return
        try:
            fis_id = StokService.depo_transfer_kaydet(
                {
                    "fis_no": self.fis_no.get().strip(),
                    "fis_tarihi": tarih,
                    "cikis_depo": self.cikis_depo.get(),
                    "giris_depo": self.giris_depo.get(),
                    "aciklama": self.aciklama.get().strip(),
                },
                self.satirlar,
            )
        except ValueError as hata:
            messagebox.showerror("Kayıt başarısız", str(hata), parent=self)
            return
        self.result = fis_id
        messagebox.showinfo("Kaydedildi", f"Transfer fişi kaydedildi: {self.fis_no.get()}", parent=self)
        self._kapat()


def depo_transfer_listesini_goster(app):
    """MuhasebeApp.icerik içinde transfer fiş listesini çizer."""
    app._icerigi_temizle()
    for dugme_anahtari, dugme in app.menu_dugmeleri.items():
        dugme.configure(style="SeciliMenu.TButton" if dugme_anahtari == "stoklar" else "Menu.TButton")
    ttk.Label(app.icerik, text="DEPO TRANSFER FİŞİ", style="Baslik.TLabel").pack(anchor="w")
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x", pady=14)
    ttk.Button(ust, text="← Stoklar Menüsü", command=lambda: app.sayfa_goster("stoklar")).pack(side="right")
    ttk.Button(ust, text="Yeni Transfer Fişi", command=lambda: _yeni(app)).pack(side="left")
    ttk.Button(ust, text="Görüntüle", command=lambda: _goruntule(app)).pack(side="left", padx=8)
    ttk.Button(ust, text="Yenile", command=lambda: depo_transfer_listesini_goster(app)).pack(side="left")

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    kolonlar = ("fis_no", "tarih", "cikis", "giris", "toplam", "aciklama")
    basliklar = ("Fiş No", "Tarih", "Çıkış Deposu", "Giriş Deposu", "Genel Toplam", "Açıklama")
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    for kolon, baslik in zip(kolonlar, basliklar):
        tablo.heading(kolon, text=baslik)
        tablo.column(kolon, width=130, anchor="w")
    tablo.column("aciklama", width=260)
    kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydirma.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydirma.pack(side="right", fill="y")
    tablo.bind("<Double-1>", lambda _e: _goruntule(app))
    app._depo_transfer_tablosu = tablo
    for fis in StokService.depo_transfer_listele():
        tablo.insert(
            "",
            "end",
            iid=str(fis.id),
            values=(
                fis.fis_no,
                _tarih(fis.fis_tarihi),
                fis.cikis_depo,
                fis.giris_depo,
                _para(fis.genel_toplam),
                fis.aciklama or "",
            ),
        )


def _yeni(app):
    dialog = DepoTransferFisiDialog(app)
    app.wait_window(dialog)
    if dialog.result:
        depo_transfer_listesini_goster(app)


def _goruntule(app):
    tablo = getattr(app, "_depo_transfer_tablosu", None)
    if not tablo:
        return
    secim = tablo.selection()
    if not secim:
        messagebox.showinfo("Seçim", "Görüntülenecek fişi seçin.", parent=app)
        return
    fis = StokService.depo_transfer_getir(int(secim[0]))
    if not fis:
        messagebox.showerror("Fiş", "Fiş bulunamadı.", parent=app)
        return
    DepoTransferFisiDialog(app, fis)
