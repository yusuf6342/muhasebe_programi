"""Ayarlar → Fiyat Görünümü."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from database.fiyat_gorunum_service import (
    VARSAYILAN_AYAR,
    ayarlari_kaydet,
    ayarlari_yukle,
    onizleme_ornekleri,
    varsayilanlara_don,
)


def fiyat_gorunum_goster(app) -> None:
    app._icerigi_temizle()
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk:
        kabuk.menu_secili_guncelle("ayarlar")

    ttk.Label(app.icerik, text="FİYAT GÖRÜNÜMÜ", style="Baslik.TLabel").pack(
        anchor="w", padx=20, pady=(16, 0)
    )
    ttk.Label(
        app.icerik,
        text="Birim / liste / net fiyatların ekran ve çıktı gösterimi. Kayıtlı hassasiyet değişmez.",
        style="AnaPanelMuted.TLabel",
    ).pack(anchor="w", padx=20, pady=(8, 0))

    mevcut = ayarlari_yukle(zorla=True)
    cerceve = ttk.LabelFrame(app.icerik, text="Fiyat Görünümü", padding=16)
    cerceve.pack(fill="x", padx=20, pady=(24, 0))

    ttk.Label(cerceve, text="Ondalık basamak sayısı (0–8):").grid(
        row=0, column=0, sticky="w", padx=(0, 12), pady=4
    )
    basamak_var = tk.IntVar(value=int(mevcut["ondalik_basamak"]))
    basamak = ttk.Spinbox(
        cerceve, from_=0, to=8, textvariable=basamak_var, width=6, justify="center"
    )
    basamak.grid(row=0, column=1, sticky="w", pady=4)

    tam_var = tk.BooleanVar(value=bool(mevcut["tam_sayida_ondalik"]))
    ttk.Checkbutton(
        cerceve,
        text="Tam sayı fiyatlarda ondalık göster",
        variable=tam_var,
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=4)

    tamamla_var = tk.BooleanVar(value=bool(mevcut["sifirla_tamamla"]))
    ttk.Checkbutton(
        cerceve,
        text="Kesirli fiyatları seçilen basamak sayısına sıfırla tamamla",
        variable=tamamla_var,
    ).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)

    binlik_var = tk.BooleanVar(value=bool(mevcut["binlik_ayirici"]))
    ttk.Checkbutton(
        cerceve,
        text="Binlik ayırıcı kullan (Türkçe: 1.234,5000)",
        variable=binlik_var,
    ).grid(row=3, column=0, columnspan=2, sticky="w", pady=4)

    onizleme = ttk.LabelFrame(app.icerik, text="Canlı önizleme", padding=12)
    onizleme.pack(fill="both", expand=True, padx=20, pady=(16, 0))
    onizleme_metin = tk.Text(onizleme, height=10, width=56, wrap="word")
    onizleme_metin.pack(fill="both", expand=True)
    onizleme_metin.configure(state="disabled")

    def _ayar_sozluk() -> dict:
        try:
            n = int(basamak_var.get())
        except (tk.TclError, TypeError, ValueError):
            n = 4
        return {
            "ondalik_basamak": max(0, min(8, n)),
            "tam_sayida_ondalik": bool(tam_var.get()),
            "sifirla_tamamla": bool(tamamla_var.get()),
            "binlik_ayirici": bool(binlik_var.get()),
        }

    def _onizleme_yenile(*_a):
        satirlar = onizleme_ornekleri(_ayar_sozluk())
        blok = "Kayıtlı → Ekran\n" + "\n".join(f"  {k}  →  {v}" for k, v in satirlar)
        onizleme_metin.configure(state="normal")
        onizleme_metin.delete("1.0", "end")
        onizleme_metin.insert("1.0", blok)
        onizleme_metin.configure(state="disabled")

    for v in (basamak_var, tam_var, tamamla_var, binlik_var):
        try:
            v.trace_add("write", _onizleme_yenile)
        except Exception:
            pass
    basamak.bind("<KeyRelease>", _onizleme_yenile)
    basamak.bind("<<Increment>>", _onizleme_yenile)
    basamak.bind("<<Decrement>>", _onizleme_yenile)
    _onizleme_yenile()

    def _kaydet():
        try:
            ayarlari_kaydet(_ayar_sozluk())
            messagebox.showinfo(
                "Fiyat Görünümü",
                "Ayarlar kaydedildi. Açık evraklarda listeyi yenilediğinizde uygulanır.",
                parent=app,
            )
        except Exception as hata:
            messagebox.showerror("Fiyat Görünümü", str(hata), parent=app)

    def _varsayilan():
        ayar = varsayilanlara_don()
        basamak_var.set(int(ayar["ondalik_basamak"]))
        tam_var.set(bool(ayar["tam_sayida_ondalik"]))
        tamamla_var.set(bool(ayar["sifirla_tamamla"]))
        binlik_var.set(bool(ayar["binlik_ayirici"]))
        _onizleme_yenile()
        messagebox.showinfo("Fiyat Görünümü", "Varsayılan ayarlar uygulandı ve kaydedildi.", parent=app)

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", padx=20, pady=20)
    ttk.Button(alt, text="Kaydet", command=_kaydet).pack(side="left")
    ttk.Button(alt, text="Varsayılanlara Dön", command=_varsayilan).pack(side="left", padx=8)
    ttk.Button(alt, text="Geri", command=lambda: app.sayfa_goster("ayarlar")).pack(
        side="left", padx=8
    )
