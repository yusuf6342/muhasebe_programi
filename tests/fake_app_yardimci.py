"""UI smoke testleri için ortak FakeApp stub'ları.

Gerçek MuhasebeApp yerine hafif Tk kabuğu; menü/hub açılış süreleri ve
widget smoke için. Ana panel bağımlı ekranlar (Hızlı Satış, Gelir-Gider)
için gerekli stub alanlarını sağlar.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def fake_app(*, geometry: str = "1100x700+-5000+-5000") -> tk.Tk:
    """Stub'lu Tk kökü; ekran dışı tutulur."""

    class FakeApp(tk.Tk):
        def __init__(self):
            super().__init__()
            self.withdraw()
            try:
                self.geometry(geometry)
            except tk.TclError:
                pass
            self.icerik = tk.Frame(self)
            self.icerik.pack(fill="both", expand=True)
            self._ana_panel_kabuk = None
            self.menu_dugmeleri: dict = {}
            self._aktif_sayfa = None
            self.cizim_sayaci: dict = {}

        def nav_sayfa_isaretle(self, *_a, **_k):
            pass

        def yetki_var(self, *_a, **_k):
            return True

        def _icerigi_temizle(self):
            for w in self.icerik.winfo_children():
                w.destroy()

        def stoklar_menusu_goster(self):
            self._icerigi_temizle()
            ttk.Label(self.icerik, text="STOKLAR").pack()

        def cariler_menusu_goster(self):
            self._icerigi_temizle()

        def faturalar_menusu_goster(self):
            self._icerigi_temizle()

        def tedarikci_karti_ac(self, *_a, **_k):
            pass

        def status_goster(self, *_a, **_k):
            pass

        def _alt_menu_dugme(self, parent, baslik, komut, row=0, column=0, sticky="ew", pady=4):
            b = ttk.Button(parent, text=baslik, command=komut)
            b.grid(row=row, column=column, sticky=sticky, pady=pady)
            return b

        def sayfa_goster(self, anahtar, ust_duzey=False):
            self._aktif_sayfa = anahtar

    return FakeApp()
