"""ÖZET TABLOLAR menüsü — bilanço benzeri özet tablolar."""

from __future__ import annotations

from tkinter import ttk


def _ozet_tablolar_menu_isaretle(app):
    for dugme_anahtari, dugme in app.menu_dugmeleri.items():
        dugme.configure(
            style="SeciliMenu.TButton" if dugme_anahtari == "ozet_tablolar" else "Menu.TButton"
        )


def _bilanco_ac(app):
    from bilanco_ui import bilanco_sayfasi_goster

    bilanco_sayfasi_goster(app)


def _gelir_tablosu_ac(app):
    from gelir_tablosu_ui import gelir_tablosu_sayfasi_goster

    gelir_tablosu_sayfasi_goster(app)


def ozet_tablolar_menusu_goster(app):
    app._icerigi_temizle()
    _ozet_tablolar_menu_isaretle(app)
    ttk.Label(app.icerik, text="ÖZET TABLOLAR", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text="Varlık–kaynak özeti, gelir tablosu ve diğer özet tablolar.",
    ).pack(anchor="w", pady=(8, 0))
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(24, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    for i, (baslik, komut) in enumerate((
        ("BİLANÇO / ÖZET TABLO", lambda: _bilanco_ac(app)),
        ("GELİR TABLOSU", lambda: _gelir_tablosu_ac(app)),
    )):
        ttk.Button(alt, text=baslik, style="AltMenu.TButton", command=komut).grid(
            row=i, column=0, sticky="ew", pady=4
        )
