"""EvoBulut stok aktarım diyaloğu — API (evobulut.env)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk


class EvobulutStokAktarDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("EvoBulut — Stok Aktar")
        self.geometry("520x300")
        self.minsize(480, 280)
        self.transient(parent)
        self.grab_set()

        ttk.Label(
            self,
            text="EvoBulut stok kartlarını bu programa aktarın.",
            style="Baslik.TLabel",
        ).pack(anchor="w", padx=14, pady=(14, 4))
        ttk.Label(
            self,
            text=(
                "Canlı API için entegrasyon/evobulut.env içinde kullanıcı kodu ve şifre gerekir.\n"
                "Kart aktarımı: kod, ad, birim, fiyatlar, marka/model.\n"
                "Stok giriş: API’de fiş listesi yok; a_kalan açılış GİRİŞ olarak yazılır (EVB-SG-…)."
            ),
            wraplength=480,
        ).pack(anchor="w", padx=14, pady=(0, 12))

        dugmeler = ttk.Frame(self)
        dugmeler.pack(fill="x", padx=14, pady=8)
        ttk.Button(
            dugmeler,
            text="API’den çek (evobulut.env)",
            command=self._apiden,
        ).pack(fill="x", pady=4)
        ttk.Button(
            dugmeler,
            text="Stok giriş / açılış miktarlarını aktar (API)",
            command=self._giris_apiden,
        ).pack(fill="x", pady=4)
        ttk.Button(dugmeler, text="Kapat", command=self.destroy).pack(fill="x", pady=(12, 0))

        self.durum = ttk.Label(self, text="")
        self.durum.pack(anchor="w", padx=14, pady=(8, 12))

    def _ozet_goster(self, sonuc) -> None:
        msg = (
            f"Çekilen: {sonuc.cekilen}  |  Eklenen: {sonuc.eklenen}  |  "
            f"Güncellenen: {sonuc.guncellenen}  |  Atlanan: {sonuc.atlanan}"
        )
        if sonuc.hatalar:
            msg += "\nİlk hatalar:\n" + "\n".join(sonuc.hatalar[:5])
        self.durum.configure(text=msg)
        messagebox.showinfo("Aktarım sonucu", msg, parent=self)
        self.result = sonuc

    def _kimlik_var_mi(self) -> bool:
        from entegrasyon.evobulut_client import credentials_available

        if credentials_available():
            return True
        messagebox.showwarning(
            "EvoBulut API",
            "Kimlik bilgisi yok.\n\n"
            "1) entegrasyon/evobulut_config.example.env dosyasını\n"
            "   entegrasyon/evobulut.env olarak kopyalayın\n"
            "2) EVOBULUT_KULLANICI_KODU ve EVOBULUT_SIFRE doldurun\n"
            "3) Tekrar deneyin",
            parent=self,
        )
        return False

    def _apiden(self) -> None:
        try:
            from entegrasyon.evobulut_client import EvobulutConfigError
            from entegrasyon.stok_import import aktar_api_den

            if not self._kimlik_var_mi():
                return
            if not messagebox.askyesno(
                "API aktarımı",
                "EvoBulut API’den tüm stok listesi çekilip kaydedilecek.\n"
                "Mevcut kartlar stok koduna göre güncellenir.\nDevam?",
                parent=self,
            ):
                return
            self.durum.configure(text="API’den çekiliyor… (birkaç dakika sürebilir)")
            self.update_idletasks()
            sonuc = aktar_api_den()
            self._ozet_goster(sonuc)
        except EvobulutConfigError as exc:
            messagebox.showwarning("EvoBulut API", str(exc), parent=self)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("EvoBulut API", str(exc), parent=self)

    def _giris_apiden(self) -> None:
        try:
            from entegrasyon.evobulut_client import EvobulutConfigError
            from entegrasyon.stok_giris_import import aktar_api_den

            if not self._kimlik_var_mi():
                return
            if not messagebox.askyesno(
                "Stok giriş / açılış aktarımı",
                "EvoBulut’taki güncel stok miktarları (a_kalan) GİRİŞ hareketi olarak yazılacak.\n"
                "Sıfır kalanlar atlanır; aynı fiş tekrar yazılmaz (EVB-SG-…).\n"
                "Önce stok kartlarının aktarılmış olması gerekir.\n"
                "Not: API’de ayrı stok giriş fişi listesi yok.\n\nDevam?",
                parent=self,
            ):
                return
            self.durum.configure(text="Stok miktarları çekiliyor… (birkaç dakika sürebilir)")
            self.update_idletasks()
            sonuc = aktar_api_den()
            msg = (
                f"Çekilen: {sonuc.cekilen}  |  Oluşturulan: {sonuc.olusturulan}  |  "
                f"Atlanan: {sonuc.atlanan}  |  Sıfır: {sonuc.sifir_kalan}"
            )
            if sonuc.hatalar:
                msg += "\nİlk hatalar:\n" + "\n".join(sonuc.hatalar[:5])
            self.durum.configure(text=msg)
            messagebox.showinfo("Stok giriş aktarım sonucu", msg, parent=self)
            self.result = sonuc
        except EvobulutConfigError as exc:
            messagebox.showwarning("EvoBulut API", str(exc), parent=self)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("EvoBulut API", str(exc), parent=self)
