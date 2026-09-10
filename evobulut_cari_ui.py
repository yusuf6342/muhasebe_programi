"""EvoBulut cari aktarım diyaloğu — Excel/CSV veya (kimlik varsa) API."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


class EvobulutCariAktarDialog(tk.Toplevel):
    def __init__(self, parent, varsayilan_tur: str = "Müşteri"):
        super().__init__(parent)
        self.result = None
        self.varsayilan_tur = varsayilan_tur or "Müşteri"
        self.title("EvoBulut — Cari Aktar")
        self.geometry("520x340")
        self.minsize(480, 300)
        self.transient(parent)
        self.grab_set()

        ttk.Label(
            self,
            text="EvoBulut cari hesaplarını bu programa aktarın.",
            style="Baslik.TLabel",
        ).pack(anchor="w", padx=14, pady=(14, 4))
        ttk.Label(
            self,
            text=(
                "Canlı API için entegrasyon/evobulut.env içinde kullanıcı kodu ve şifre gerekir.\n"
                "Yoksa EvoBulut’tan Excel/CSV dışa aktarıp buradan seçin.\n"
                "Açılış/devir: API’deki güncel cari bakiyeler açılış fişi olarak yazılır."
            ),
            wraplength=480,
        ).pack(anchor="w", padx=14, pady=(0, 12))

        dugmeler = ttk.Frame(self)
        dugmeler.pack(fill="x", padx=14, pady=8)
        ttk.Button(
            dugmeler,
            text="Excel / CSV dosyasından aktar…",
            command=self._dosyadan,
        ).pack(fill="x", pady=4)
        ttk.Button(
            dugmeler,
            text="API’den çek (evobulut.env)",
            command=self._apiden,
        ).pack(fill="x", pady=4)
        ttk.Button(
            dugmeler,
            text="Açılış / devir bakiyelerini aktar (API)",
            command=self._acilis_apiden,
        ).pack(fill="x", pady=4)
        ttk.Button(dugmeler, text="Kapat", command=self.destroy).pack(fill="x", pady=(12, 0))

        self.durum = ttk.Label(self, text="")
        self.durum.pack(anchor="w", padx=14, pady=(8, 12))

    def _ozet_goster(self, sonuc) -> None:
        msg = (
            f"Eklenen: {sonuc.eklenen}  |  Güncellenen: {sonuc.guncellenen}  |  "
            f"Atlanan: {sonuc.atlanan}"
        )
        if sonuc.hatalar:
            msg += f"\nİlk hatalar:\n" + "\n".join(sonuc.hatalar[:5])
        self.durum.configure(text=msg)
        messagebox.showinfo("Aktarım sonucu", msg, parent=self)
        self.result = sonuc

    def _dosyadan(self) -> None:
        yol = filedialog.askopenfilename(
            parent=self,
            title="EvoBulut cari Excel/CSV",
            filetypes=[
                ("Excel / CSV", "*.xlsx;*.xlsm;*.csv"),
                ("Excel", "*.xlsx;*.xlsm"),
                ("CSV", "*.csv"),
                ("Tüm dosyalar", "*.*"),
            ],
        )
        if not yol:
            return
        try:
            from entegrasyon.cari_import import aktar_dosyadan

            self.durum.configure(text="Aktarılıyor…")
            self.update_idletasks()
            sonuc = aktar_dosyadan(yol, varsayilan_tur=self.varsayilan_tur)
            self._ozet_goster(sonuc)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Aktarım", str(exc), parent=self)

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
            "3) Tekrar deneyin\n\n"
            "Alternatif: EvoBulut’tan Excel dışa aktarıp dosyadan yükleyin.",
            parent=self,
        )
        return False

    def _apiden(self) -> None:
        try:
            from entegrasyon.evobulut_client import EvobulutConfigError
            from entegrasyon.cari_import import aktar_api_den

            if not self._kimlik_var_mi():
                return
            if not messagebox.askyesno(
                "API aktarımı",
                "EvoBulut API’den tüm cari listesi çekilip kaydedilecek.\nDevam?",
                parent=self,
            ):
                return
            self.durum.configure(text="API’den çekiliyor…")
            self.update_idletasks()
            sonuc = aktar_api_den(varsayilan_tur=self.varsayilan_tur)
            self._ozet_goster(sonuc)
        except EvobulutConfigError as exc:
            messagebox.showwarning("EvoBulut API", str(exc), parent=self)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("EvoBulut API", str(exc), parent=self)

    def _acilis_apiden(self) -> None:
        try:
            from entegrasyon.evobulut_client import EvobulutConfigError
            from entegrasyon.cari_acilis_import import aktar_api_den

            if not self._kimlik_var_mi():
                return
            if not messagebox.askyesno(
                "Açılış / devir aktarımı",
                "EvoBulut’taki güncel cari bakiyeler açılış fişi olarak yazılacak.\n"
                "Sıfır bakiyeler atlanır; aynı fiş tekrar yazılmaz (EVB-ACL-…).\n"
                "Önce cari kartların aktarılmış olması gerekir.\n\nDevam?",
                parent=self,
            ):
                return
            self.durum.configure(text="Açılış bakiyeleri çekiliyor…")
            self.update_idletasks()
            sonuc = aktar_api_den()
            msg = (
                f"Çekilen: {sonuc.cekilen}  |  Oluşturulan: {sonuc.olusturulan}  |  "
                f"Atlanan: {sonuc.atlanan}  |  Sıfır: {sonuc.sifir_bakiye}"
            )
            if sonuc.hatalar:
                msg += f"\nİlk hatalar:\n" + "\n".join(sonuc.hatalar[:5])
            self.durum.configure(text=msg)
            messagebox.showinfo("Açılış aktarım sonucu", msg, parent=self)
            self.result = sonuc
        except EvobulutConfigError as exc:
            messagebox.showwarning("EvoBulut API", str(exc), parent=self)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("EvoBulut API", str(exc), parent=self)
