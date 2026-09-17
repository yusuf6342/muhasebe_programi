"""EvoBulut banka kart aktarım diyaloğu."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ui_bg import arka_planda


class EvobulutBankaKartAktarDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = None
        self.title("EvoBulut — Banka Kartları Aktar")
        self.geometry("560x440")
        self.minsize(520, 380)
        self.transient(parent)
        self.grab_set()
        self._busy = False

        ttk.Label(
            self,
            text="EvoBulut banka kartlarını Cin Muhasebe banka sistemine aktarın.",
            style="Baslik.TLabel",
        ).pack(anchor="w", padx=14, pady=(14, 4))
        ttk.Label(
            self,
            text=(
                "Her Evo banka kartı için BankaKarti + 5 alt hesap (Mevduat/KMH/POS/KK/Krediler) oluşur.\n"
                "Eşleştirme (evo_banka_id → yerel kart) ilerideki banka hareket aktarımı için saklanır.\n"
                "API işlemlerinde EvoBulut şifre ekranı açılır."
            ),
            wraplength=520,
        ).pack(anchor="w", padx=14, pady=(0, 12))

        dugmeler = ttk.Frame(self)
        dugmeler.pack(fill="x", padx=14, pady=8)
        ttk.Button(
            dugmeler,
            text="EvoBulut hesabı / şifre…",
            command=self._sifre,
        ).pack(fill="x", pady=4)
        ttk.Button(
            dugmeler,
            text="Karşılaştır (yazma yok)",
            command=self._karsilastir,
        ).pack(fill="x", pady=4)
        ttk.Button(
            dugmeler,
            text="API’den aktar ve eşleştir",
            command=self._aktar,
        ).pack(fill="x", pady=4)
        ttk.Button(dugmeler, text="Kapat", command=self.destroy).pack(fill="x", pady=(12, 0))

        self.durum = ttk.Label(self, text="", wraplength=520, justify="left")
        self.durum.pack(anchor="w", padx=14, pady=(8, 12))

    def _kimlik_al(self):
        from evobulut_login_ui import ensure_evobulut_credentials

        return ensure_evobulut_credentials(self)

    def _sifre(self) -> None:
        creds = self._kimlik_al()
        if creds:
            messagebox.showinfo(
                "EvoBulut",
                f"Giriş başarılı.\nKullanıcı: {creds.kullanici_kodu}",
                parent=self,
            )

    def _ozet(self, metin: str) -> None:
        self._busy = False
        self.durum.configure(text=metin)
        messagebox.showinfo("Banka kartları", metin, parent=self)

    def _hata(self, exc: BaseException) -> None:
        self._busy = False
        self.durum.configure(text="")
        messagebox.showerror("EvoBulut banka", str(exc), parent=self)

    def _karsilastir(self) -> None:
        if self._busy:
            return
        creds = self._kimlik_al()
        if not creds:
            return
        self._busy = True
        self.durum.configure(text="Karşılaştırılıyor…")

        def is_fn():
            from entegrasyon.evobulut_client import EvobulutClient
            from entegrasyon.banka_kart_import import karsilastir

            c = EvobulutClient(creds)
            c.login()
            return karsilastir(c.banka_kart_listesi())

        def ok(rapor):
            metin = (
                f"Evo: {rapor.evo_adet}\n"
                f"Yerel: {rapor.yerel_adet}\n"
                f"Eşleşen: {len(rapor.eslesen)}\n"
                f"Sadece Evo (aktarılacak): {len(rapor.sadece_evo)}\n"
                f"Sadece Cin Muhasebe: {len(rapor.sadece_yerel)}"
            )
            if rapor.sadece_evo:
                metin += "\n\nAktarılacak örnekler:\n- " + "\n- ".join(
                    f"{x['evo_adi']} (#{x['evo_id']})" for x in rapor.sadece_evo[:8]
                )
            self._ozet(metin)

        arka_planda(self, is_fn, tamam=ok, hata=lambda e: self._hata(e))

    def _aktar(self) -> None:
        if self._busy:
            return
        creds = self._kimlik_al()
        if not creds:
            return
        if not messagebox.askyesno(
            "Onay",
            "EvoBulut’taki tüm banka kartları Cin Muhasebe’ye aktarılsın mı?\n"
            "Mevcut eşleşen kartlar güncellenir; yenileri oluşturulur.",
            parent=self,
        ):
            return
        self._busy = True
        self.durum.configure(text="Aktarılıyor…")

        def is_fn():
            from entegrasyon.banka_kart_import import aktar_api_den

            return aktar_api_den(guncelle=True, creds=creds)

        def ok(pair):
            sonuc, rapor = pair
            metin = (
                f"Oluşturulan: {sonuc.olusturulan}\n"
                f"Güncellenen/eşleşen: {sonuc.atlanan}\n"
                f"Hata: {len(sonuc.hatalar)}\n\n"
                f"Son durum — Evo {rapor.evo_adet}, eşleşen {len(rapor.eslesen)}, "
                f"sadece Evo {len(rapor.sadece_evo)}"
            )
            if sonuc.hatalar:
                metin += "\n\n" + "\n".join(sonuc.hatalar[:5])
            self.result = sonuc
            self._ozet(metin)

        arka_planda(self, is_fn, tamam=ok, hata=lambda e: self._hata(e))
