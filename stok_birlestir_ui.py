"""Yanlışlıkla açılmış iki stok kartını tek karta birleştirme."""

from __future__ import annotations

from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, ttk

from database.stok_service import StokService
from urun_sec_ui import UrunSecDialog


def _para(tutar):
    return f"{float(tutar):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class StokBirlestirDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("Stok Birleştir")
        self.geometry("720x420")
        self.minsize(640, 380)
        self.transient(parent)
        self.grab_set()

        self.aktarilacak = None  # kaynak (silinecek)
        self.aktarilan = None  # hedef (kalacak)

        ttk.Label(
            self,
            text=(
                "Aktarılacak stok hareketleri aktarılan stoka işlenir.\n"
                "Birim fark etmez; işlem sonrası aktarılan stok birimi geçerlidir.\n"
                "Aktarılacak stok boşalınca otomatik silinir."
            ),
            justify="left",
        ).pack(anchor="w", padx=14, pady=(12, 6))

        cerceve = ttk.LabelFrame(self, text="Stok Seçimi", padding=12)
        cerceve.pack(fill="x", padx=14, pady=8)
        cerceve.columnconfigure(1, weight=1)

        ttk.Label(cerceve, text="Aktarılacak Stok (silinecek)").grid(row=0, column=0, sticky="w", pady=4)
        self.aktarilacak_etiket = ttk.Label(cerceve, text="— seçilmedi —", foreground="#444444")
        self.aktarilacak_etiket.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Button(cerceve, text="Seç", command=self._aktarilacak_sec).grid(row=0, column=2, padx=4)

        ttk.Label(cerceve, text="Aktarılan Stok (kalacak)").grid(row=1, column=0, sticky="w", pady=4)
        self.aktarilan_etiket = ttk.Label(cerceve, text="— seçilmedi —", foreground="#444444")
        self.aktarilan_etiket.grid(row=1, column=1, sticky="w", padx=8)
        ttk.Button(cerceve, text="Seç", command=self._aktarilan_sec).grid(row=1, column=2, padx=4)

        ozet = ttk.LabelFrame(self, text="Özet", padding=12)
        ozet.pack(fill="both", expand=True, padx=14, pady=8)
        self.ozet = ttk.Label(ozet, text="İki stok kartı seçildiğinde özet burada görünür.", justify="left")
        self.ozet.pack(anchor="w")

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=14, pady=12)
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Birleştir", command=self.birlestir).pack(side="right", padx=8)

    def _stok_metin(self, stok):
        mevcut = sum((lot.kalan_miktar for lot in stok.lotlar), Decimal("0"))
        return (
            f"{stok.stok_kodu} — {stok.stok_adi}  |  Birim: {stok.birim}  |  "
            f"Mevcut: {_para(mevcut)}  |  Barkod: {stok.barkod or '-'}"
        )

    def _aktarilacak_sec(self):
        UrunSecDialog(self, on_select=self._aktarilacak_geldi)

    def _aktarilan_sec(self):
        UrunSecDialog(self, on_select=self._aktarilan_geldi)

    def _aktarilacak_geldi(self, degerler):
        kod = (degerler[0] or "").strip()
        stok = next((s for s in StokService.stoklari_ara(kod) if s.stok_kodu == kod), None)
        if not stok:
            messagebox.showerror("Stok", "Aktarılacak stok bulunamadı.", parent=self)
            return
        self.aktarilacak = stok
        self.aktarilacak_etiket.configure(text=self._stok_metin(stok))
        self._ozet_guncelle()

    def _aktarilan_geldi(self, degerler):
        kod = (degerler[0] or "").strip()
        stok = next((s for s in StokService.stoklari_ara(kod) if s.stok_kodu == kod), None)
        if not stok:
            messagebox.showerror("Stok", "Aktarılan stok bulunamadı.", parent=self)
            return
        self.aktarilan = stok
        self.aktarilan_etiket.configure(text=self._stok_metin(stok))
        self._ozet_guncelle()

    def _ozet_guncelle(self):
        if not self.aktarilacak or not self.aktarilan:
            return
        if self.aktarilacak.id == self.aktarilan.id:
            self.ozet.configure(text="Uyarı: İki seçim aynı stok. Farklı kartlar seçin.")
            return
        self.ozet.configure(
            text=(
                f"«{self.aktarilacak.stok_kodu}» → «{self.aktarilan.stok_kodu}» birleştirilecek.\n"
                f"Hedef birim: {self.aktarilan.birim}\n"
                f"Kaynak kart silinecek; tüm hareket ve belge satırları hedef koda geçecek."
            )
        )

    def birlestir(self):
        if not self.aktarilacak or not self.aktarilan:
            messagebox.showwarning("Eksik", "Aktarılacak ve aktarılan stoku seçin.", parent=self)
            return
        if self.aktarilacak.id == self.aktarilan.id:
            messagebox.showerror("Hata", "İki stok aynı olamaz.", parent=self)
            return
        if not messagebox.askyesno(
            "Onay",
            (
                f"{self.aktarilacak.stok_kodu} kartı {self.aktarilan.stok_kodu} kartına birleştirilsin mi?\n\n"
                f"Bu işlem geri alınamaz. Kaynak kart silinir."
            ),
            parent=self,
        ):
            return
        try:
            sonuc = StokService.stok_birlestir(self.aktarilacak.id, self.aktarilan.id)
        except ValueError as hata:
            messagebox.showerror("Birleştirilemedi", str(hata), parent=self)
            return
        self.result = sonuc
        messagebox.showinfo(
            "Tamam",
            (
                f"Birleştirme tamamlandı.\n"
                f"{sonuc['eski_kod']} → {sonuc['yeni_kod']} ({sonuc['yeni_ad']})\n"
                f"Belge satırı: {sonuc['belge_satir']}  |  Hareket: {sonuc['hareket']}  |  Lot: {sonuc['lot']}\n"
                f"Birim: {sonuc['yeni_birim']}"
            ),
            parent=self,
        )
        self.destroy()


def stok_birlestir_sayfasi_goster(app):
    app._icerigi_temizle()
    for dugme_anahtari, dugme in app.menu_dugmeleri.items():
        dugme.configure(style="SeciliMenu.TButton" if dugme_anahtari == "stoklar" else "Menu.TButton")
    ttk.Label(app.icerik, text="STOK BİRLEŞTİR", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text=(
            "Yanlışlıkla iki kod açılmış stok kartlarını tek kartta birleştirir. "
            "Aktarılacak stok hareketleri aktarılan stoka yazılır; kaynak kart silinir. "
            "Birim fark etmez — aktarılan stok birimi kullanılır."
        ),
        wraplength=780,
        justify="left",
    ).pack(anchor="w", pady=(14, 10))
    dugmeler = ttk.Frame(app.icerik)
    dugmeler.pack(anchor="w", pady=8)
    ttk.Button(dugmeler, text="Stok Birleştir…", command=lambda: _ac(app)).pack(side="left")
    ttk.Button(dugmeler, text="← Stoklar Menüsü", command=lambda: app.sayfa_goster("stoklar")).pack(
        side="left", padx=10
    )


def _ac(app):
    dialog = StokBirlestirDialog(app)
    app.wait_window(dialog)
    if dialog.result and hasattr(app, "stok_tablosu"):
        try:
            app.stok_listesini_yenile()
        except Exception:
            pass
