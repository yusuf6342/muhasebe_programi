"""Ayarlar → Hızlı Satış Ayarları — başlangıç müşterisi."""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, ttk

from database.access import yetki_var
from database.hizli_satis_ayarlari_service import (
    AYAR_YETKILERI,
    MOD_ATANAN,
    MOD_BOS,
    ayar_kaydet,
    ayar_oku,
)
from database.session_manager import oturum


def hizli_satis_ayarlari_goster(app) -> None:
    app._icerigi_temizle()
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk:
        kabuk.menu_secili_guncelle("ayarlar")

    ttk.Label(app.icerik, text="HIZLI SATIŞ AYARLARI", style="Baslik.TLabel").pack(
        anchor="w", padx=20, pady=(16, 0)
    )
    ttk.Label(
        app.icerik,
        text="Firma bazlı başlangıç müşterisi. İşlem sırasında yapılan seçim bu ayarı değiştirmez.",
        style="AnaPanelMuted.TLabel",
        wraplength=640,
    ).pack(anchor="w", padx=20, pady=(8, 0))

    firma_ad = getattr(oturum, "firma_unvan", None) or getattr(oturum, "firma_kodu", None) or "—"
    ttk.Label(app.icerik, text=f"Aktif firma: {firma_ad}").pack(anchor="w", padx=20, pady=(12, 0))

    kayitli = ayar_oku()
    mod_var = tk.StringVar(value=kayitli.get("baslangic_mod") or MOD_BOS)
    secili_cari_id: dict[str, int | None] = {
        "id": kayitli.get("baslangic_cari_id"),
    }
    musteri_metin = tk.StringVar(value=_musteri_metni(kayitli))

    cerceve = ttk.LabelFrame(app.icerik, text="Hızlı Satış Başlangıç Müşterisi", padding=16)
    cerceve.pack(fill="x", padx=20, pady=(20, 0))

    ttk.Radiobutton(
        cerceve,
        text="A. Müşteri alanı boş gelsin",
        variable=mod_var,
        value=MOD_BOS,
        command=lambda: _mod_degisti(),
    ).grid(row=0, column=0, columnspan=3, sticky="w")

    ttk.Radiobutton(
        cerceve,
        text="B. Seçilen müşteri otomatik gelsin",
        variable=mod_var,
        value=MOD_ATANAN,
        command=lambda: _mod_degisti(),
    ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

    ttk.Label(cerceve, text="Müşteri:").grid(row=2, column=0, sticky="w", pady=(14, 0))
    musteri_entry = ttk.Entry(cerceve, textvariable=musteri_metin, width=48, state="readonly")
    musteri_entry.grid(row=2, column=1, sticky="ew", padx=(8, 8), pady=(14, 0))
    sec_btn = ttk.Button(cerceve, text="Seç", command=lambda: _musteri_sec())
    sec_btn.grid(row=2, column=2, sticky="w", pady=(14, 0))
    cerceve.columnconfigure(1, weight=1)

    bilgi = ttk.Label(
        cerceve,
        text=(
            "Boş modda yeni satış müşterisiz açılır; ürün/barkod/sepet çalışır.\n"
            "Atanmış modda yeni satış seçilen cari ile açılır. F2 ile işlem sırasında değiştirilebilir."
        ),
        wraplength=560,
    )
    bilgi.grid(row=3, column=0, columnspan=3, sticky="w", pady=(12, 0))

    if kayitli.get("uyari"):
        ttk.Label(
            cerceve,
            text=kayitli["uyari"],
            foreground="#B71C1C",
            wraplength=560,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))

    yazma_izinli = yetki_var(*AYAR_YETKILERI)

    def _mod_degisti():
        atanmis = mod_var.get() == MOD_ATANAN
        try:
            sec_btn.configure(state="normal" if atanmis and yazma_izinli else "disabled")
        except tk.TclError:
            pass

    def _musteri_sec():
        if not yazma_izinli:
            messagebox.showerror("Yetki", "Ayar değiştirme yetkiniz yok.", parent=app)
            return
        try:
            from app import MusteriSecimDialog
            from database.cari_service import CariService
        except Exception as exc:
            messagebox.showerror("Müşteri", str(exc), parent=app)
            return
        try:
            musteriler = CariService.aktif_evrak_carileri()
        except Exception as exc:
            messagebox.showerror("Müşteri", f"Cari listesi alınamadı:\n{exc}", parent=app)
            return
        bakiyeler: dict = {}
        try:
            for sat in CariService.listele(arama="", hizli=True, cari_turu=None) or []:
                c = sat.get("cari")
                if c is not None:
                    bakiyeler[int(c.id)] = sat.get("bakiye") or Decimal("0")
        except Exception:
            bakiyeler = {}

        def _secildi(cari):
            if cari is None:
                return
            secili_cari_id["id"] = int(cari.id)
            kod = (cari.cari_kodu or "").strip()
            unvan = (cari.unvan or "").strip()
            musteri_metin.set(f"{kod} — {unvan}" if kod else unvan)
            mod_var.set(MOD_ATANAN)
            _mod_degisti()

        MusteriSecimDialog(
            app,
            musteriler=musteriler,
            bakiyeler=bakiyeler,
            on_select=_secildi,
            baslik="Hızlı Satış — Başlangıç Müşterisi",
            kayit_adi="müşteri",
        )

    def _kaydet():
        if not yazma_izinli:
            messagebox.showerror("Yetki", "Ayar değiştirme yetkiniz yok.", parent=app)
            return
        try:
            sonuc = ayar_kaydet(
                baslangic_mod=mod_var.get(),
                baslangic_cari_id=secili_cari_id.get("id"),
            )
        except Exception as hata:
            messagebox.showerror("Hızlı Satış Ayarları", str(hata), parent=app)
            return
        messagebox.showinfo(
            "Hızlı Satış Ayarları",
            "Ayar kaydedildi. Sonraki yeni satışlarda uygulanır.",
            parent=app,
        )
        # Ekranı kayıtlı haliyle yenile
        hizli_satis_ayarlari_goster(app)
        _ = sonuc

    def _vazgec():
        app.sayfa_goster("ayarlar")

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", padx=20, pady=20)
    kaydet_btn = ttk.Button(alt, text="Kaydet", command=_kaydet)
    kaydet_btn.pack(side="left")
    ttk.Button(alt, text="Vazgeç", command=_vazgec).pack(side="left", padx=8)
    if not yazma_izinli:
        kaydet_btn.configure(state="disabled")
        messagebox.showinfo(
            "Hızlı Satış Ayarları",
            "Ayarları görüntüleyebilirsiniz; değiştirme yetkiniz yok.",
            parent=app,
        )
    _mod_degisti()


def _musteri_metni(ayar: dict) -> str:
    kod = (ayar.get("cari_kodu") or "").strip()
    unvan = (ayar.get("cari_unvan") or "").strip()
    if not kod and not unvan:
        return ""
    return f"{kod} — {unvan}" if kod else unvan
