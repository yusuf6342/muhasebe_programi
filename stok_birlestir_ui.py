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
        self.geometry("780x620")
        self.minsize(700, 560)
        self.transient(parent)
        self.grab_set()

        self.aktarilacak = None  # kaynak (pasife alınacak)
        self.aktarilan = None  # hedef (kalacak)
        self._onizleme = None

        ttk.Label(
            self,
            text=(
                "Kaynak Stok: hareketleri aktarılır, işlem sonunda pasife alınır.\n"
                "Hedef Stok: kaynak hareketlerini ve FIFO lotlarını devralır.\n"
                "Geçmiş belgelerdeki ürün adı / kod / birim snapshot'ları korunur."
            ),
            justify="left",
        ).pack(anchor="w", padx=14, pady=(12, 6))

        cerceve = ttk.LabelFrame(self, text="Stok Seçimi", padding=12)
        cerceve.pack(fill="x", padx=14, pady=8)
        cerceve.columnconfigure(1, weight=1)

        ttk.Label(cerceve, text="Kaynak Stok (aktarılacak)").grid(
            row=0, column=0, sticky="w", pady=4
        )
        self.aktarilacak_etiket = ttk.Label(cerceve, text="— seçilmedi —", foreground="#444444")
        self.aktarilacak_etiket.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Button(cerceve, text="Seç", command=self._aktarilacak_sec).grid(
            row=0, column=2, padx=4
        )

        ttk.Label(cerceve, text="Hedef Stok (kalacak)").grid(row=1, column=0, sticky="w", pady=4)
        self.aktarilan_etiket = ttk.Label(cerceve, text="— seçilmedi —", foreground="#444444")
        self.aktarilan_etiket.grid(row=1, column=1, sticky="w", padx=8)
        ttk.Button(cerceve, text="Seç", command=self._aktarilan_sec).grid(
            row=1, column=2, padx=4
        )

        gerekce_fr = ttk.Frame(cerceve)
        gerekce_fr.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        gerekce_fr.columnconfigure(1, weight=1)
        ttk.Label(gerekce_fr, text="Birleştirme gerekçesi").grid(row=0, column=0, sticky="w")
        self.gerekce_var = tk.StringVar()
        ttk.Entry(gerekce_fr, textvariable=self.gerekce_var).grid(
            row=0, column=1, sticky="ew", padx=8
        )

        ozet = ttk.LabelFrame(self, text="Birleştirme Önizlemesi", padding=12)
        ozet.pack(fill="both", expand=True, padx=14, pady=8)
        self.ozet = tk.Text(ozet, height=16, wrap="word", relief="flat", background="#f7f7f7")
        self.ozet.pack(fill="both", expand=True)
        self.ozet.insert("1.0", "İki stok kartı seçildiğinde etki özeti burada görünür.")
        self.ozet.configure(state="disabled")

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=14, pady=12)
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Birleştir", command=self.birlestir).pack(side="right", padx=8)
        ttk.Button(alt, text="Önizlemeyi Yenile", command=self._ozet_guncelle).pack(
            side="left"
        )

    def _stok_metin(self, stok):
        mevcut = sum((lot.kalan_miktar for lot in stok.lotlar), Decimal("0"))
        return (
            f"{stok.stok_kodu} — {stok.stok_adi}  |  Birim: {stok.birim}  |  "
            f"Mevcut: {_para(mevcut)}  |  Barkod: {stok.barkod or '-'}"
        )

    def _aktarilacak_sec(self):
        UrunSecDialog(self, on_select=self._aktarilacak_geldi, ayrintili=True)

    def _aktarilan_sec(self):
        UrunSecDialog(self, on_select=self._aktarilan_geldi, ayrintili=True)

    def _aktarilacak_geldi(self, degerler):
        kod = (degerler[0] or "").strip()
        stok = next((s for s in StokService.stoklari_ara(kod) if s.stok_kodu == kod), None)
        if not stok:
            messagebox.showerror("Stok", "Kaynak stok bulunamadı.", parent=self)
            return
        self.aktarilacak = stok
        self.aktarilacak_etiket.configure(text=self._stok_metin(stok))
        self._ozet_guncelle()

    def _aktarilan_geldi(self, degerler):
        kod = (degerler[0] or "").strip()
        stok = next((s for s in StokService.stoklari_ara(kod) if s.stok_kodu == kod), None)
        if not stok:
            messagebox.showerror("Stok", "Hedef stok bulunamadı.", parent=self)
            return
        self.aktarilan = stok
        self.aktarilan_etiket.configure(text=self._stok_metin(stok))
        self._ozet_guncelle()

    def _ozet_yaz(self, metin: str):
        self.ozet.configure(state="normal")
        self.ozet.delete("1.0", "end")
        self.ozet.insert("1.0", metin)
        self.ozet.configure(state="disabled")

    def _ozet_guncelle(self):
        self._onizleme = None
        if not self.aktarilacak or not self.aktarilan:
            return
        if self.aktarilacak.id == self.aktarilan.id:
            self._ozet_yaz("Uyarı: Kaynak ve hedef aynı stok. Farklı kartlar seçin.")
            return
        try:
            o = StokService.stok_birlestir_onizleme(self.aktarilacak.id, self.aktarilan.id)
        except ValueError as hata:
            self._ozet_yaz(str(hata))
            return
        self._onizleme = o
        self._ozet_yaz(
            (
                f"Kaynak: {o['kaynak_kod']} — {o['kaynak_ad']}\n"
                f"Hedef:  {o['hedef_kod']} — {o['hedef_ad']}\n"
                f"\n"
                f"Kaynak toplam giriş: {_para(o['kaynak_toplam_giris'])}\n"
                f"Kaynak toplam çıkış: {_para(o['kaynak_toplam_cikis'])}\n"
                f"Kaynak net (hareket): {_para(o['kaynak_net'])}\n"
                f"Kaynak lot bakiyesi: {_para(o['kaynak_lot_miktar'])}\n"
                f"Hedef mevcut miktar: {_para(o['hedef_mevcut'])}\n"
                f"Birleştirme sonrası beklenen hedef: {_para(o['beklenen_hedef_miktar'])}\n"
                f"\n"
                f"Etkilenecek hareket: {o['hareket_adet']}\n"
                f"Etkilenecek belge satırı (snapshot korunur): {o['belge_satir_adet']}\n"
                f"Etkilenecek depo: {o['depo_adet']}\n"
                f"\n"
                f"Onaylandığında hareket ve FIFO lotları hedef stock_id'ye taşınır;\n"
                f"kaynak kart pasife alınır (silinmez)."
            )
        )

    def birlestir(self):
        if not self.aktarilacak or not self.aktarilan:
            messagebox.showwarning("Eksik", "Kaynak ve hedef stoku seçin.", parent=self)
            return
        if self.aktarilacak.id == self.aktarilan.id:
            messagebox.showerror("Hata", "Kaynak ve hedef stok aynı olamaz.", parent=self)
            return
        if self._onizleme is None:
            self._ozet_guncelle()
        o = self._onizleme
        if not o:
            messagebox.showerror("Önizleme", "Önizleme alınamadı; seçimleri kontrol edin.", parent=self)
            return

        onay_metin = (
            f"Kaynak: {o['kaynak_kod']} — {o['kaynak_ad']}\n"
            f"Hedef: {o['hedef_kod']} — {o['hedef_ad']}\n\n"
            f"Kaynak giriş: {_para(o['kaynak_toplam_giris'])}\n"
            f"Kaynak çıkış: {_para(o['kaynak_toplam_cikis'])}\n"
            f"Kaynak net: {_para(o['kaynak_net'])}\n"
            f"Hedef mevcut: {_para(o['hedef_mevcut'])}\n"
            f"Beklenen hedef miktar: {_para(o['beklenen_hedef_miktar'])}\n"
            f"Hareket: {o['hareket_adet']}  |  Belge satırı: {o['belge_satir_adet']}  |  "
            f"Depo: {o['depo_adet']}\n\n"
            f"Kaynak kart pasife alınacak. Devam edilsin mi?"
        )
        if not messagebox.askyesno("Birleştirme Onayı", onay_metin, parent=self):
            return

        try:
            sonuc = StokService.stok_birlestir(
                self.aktarilacak.id,
                self.aktarilan.id,
                gerekce=self.gerekce_var.get(),
            )
        except ValueError as hata:
            messagebox.showerror("Birleştirilemedi", str(hata), parent=self)
            return
        except Exception as hata:
            messagebox.showerror("Birleştirilemedi", str(hata), parent=self)
            return

        self.result = sonuc
        depo_satirlari = []
        for d in sonuc.get("depo_bakiyeleri") or []:
            depo_satirlari.append(
                f"  depo {d['depo_id']}: {_para(d['onceki'])} + {_para(d['kaynak'])} "
                f"→ {_para(d['sonra'])}"
            )
        depo_blok = "\n".join(depo_satirlari) if depo_satirlari else "  (depo bakiyesi yok)"
        messagebox.showinfo(
            "Birleştirme Tamamlandı",
            (
                f"{sonuc['eski_kod']} → {sonuc['yeni_kod']} ({sonuc['yeni_ad']})\n\n"
                f"Aktarılan hareket: {sonuc['hareket']}\n"
                f"Aktarılan giriş: {_para(sonuc['aktarilan_giris'])}\n"
                f"Aktarılan çıkış: {_para(sonuc['aktarilan_cikis'])}\n"
                f"FIFO/lot: {sonuc['lot']} "
                f"(taşınan {sonuc['lot_tasinan']}, birleşen {sonuc['lot_birlesen']})\n"
                f"Hedef miktar: {_para(sonuc['hedef_miktar_once'])} → "
                f"{_para(sonuc['hedef_miktar_sonra'])}\n"
                f"Depo bakiyeleri:\n{depo_blok}\n"
                f"Kaynak durum: {sonuc['kaynak_durum']}\n"
                f"Belge satırı (snapshot korundu): {sonuc['belge_satir']}"
            ),
            parent=self,
        )
        self.destroy()


def stok_birlestir_sayfasi_goster(app):
    app._icerigi_temizle()
    for dugme_anahtari, dugme in app.menu_dugmeleri.items():
        dugme.configure(
            style="SeciliMenu.TButton" if dugme_anahtari == "stoklar" else "Menu.TButton"
        )
    ttk.Label(app.icerik, text="STOK BİRLEŞTİR", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text=(
            "Yanlışlıkla iki kod açılmış stok kartlarını tek kartta birleştirir. "
            "Kaynak stoğun hareket ve FIFO lotları hedefe aktarılır; miktar lotlardan "
            "yeniden doğrulanır. Kaynak kart pasife alınır (geçmiş belgeler korunur). "
            "Stok seçiminde 5 kelimelik ayrıntılı ürün araması kullanılabilir."
        ),
        wraplength=780,
        justify="left",
    ).pack(anchor="w", pady=(14, 10))
    dugmeler = ttk.Frame(app.icerik)
    dugmeler.pack(anchor="w", pady=8)
    ttk.Button(dugmeler, text="Stok Birleştir…", command=lambda: _ac(app)).pack(side="left")
    ttk.Button(
        dugmeler, text="← Stoklar Menüsü", command=lambda: app.sayfa_goster("stoklar")
    ).pack(side="left", padx=10)


def _ac(app):
    dialog = StokBirlestirDialog(app)
    app.wait_window(dialog)
    if dialog.result and hasattr(app, "stok_tablosu"):
        try:
            app.stok_listesini_yenile()
        except Exception:
            pass
