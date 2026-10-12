"""Evrak satır tabloları — ortak klavye yardımcıları.

- Ürün adı / kodu / barkod hücresine çift tık veya F2: satırın bağlı stok kartı açılır.
- Üçlü iskonto hücresi: iskonto 1 → 2 → 3 ardışık küçük kutular (Enter / Tab / → ile sıradaki).
- Hücre editörlerinde ↑ / ↓ değeri yazar ve aynı kolonda önceki / sonraki satıra geçer.
  Açılır listelerde (birim, KDV …) ↑ / ↓ da satır değiştirir; liste Alt+↓ veya fareyle açılır.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Sequence

ISKONTO_ALANLARI = ("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3")
_ISKONTO_MIN_KUTU = 46
_URUN_KOLONLARI = ("urun_adi", "urun_kodu", "barkod")


def urun_kolonlari(dialog) -> set[str]:
    """Stok kartını açan kolonlar: satır içi giriş bileşeninin barkod / kod / ad kolonları."""
    from satir_ici_urun_giris import giris_bileseni

    giris = giris_bileseni(dialog)
    kolonlar = set(_URUN_KOLONLARI)
    if giris is not None:
        kolonlar |= set(getattr(giris, "urun_kolonlari", ()) or ())
    return kolonlar


def satir_stok_karti_ac(dialog, idx: int) -> bool:
    """Satırın bağlı stok kartını açar; bağlı kart yoksa kısa bilgi verir. Açıldıysa True."""
    satirlar = getattr(dialog, "satirlar", None) or []
    if not (0 <= idx < len(satirlar)):
        return False
    satir = satirlar[idx]
    kod = (satir.get("urun_kodu") or "").strip()
    if not kod or satir.get("is_manual_item") or satir.get("manuel"):
        messagebox.showinfo("Stok", "Bu satır bir stok kartına bağlı değil.", parent=dialog)
        return False
    try:
        from database.stok_service import StokService
        from stok_ui import StokKartiDialog

        stok = next((s for s in StokService.stoklari_ara(kod) if (s.stok_kodu or "").strip() == kod), None)
        if stok is None:
            messagebox.showinfo("Stok", "Stok kartı bulunamadı.", parent=dialog)
            return False
        StokKartiDialog(dialog, stok)
        return True
    except Exception as exc:
        messagebox.showerror("Stok", str(exc), parent=dialog)
        return False


def odak_tabloda_mi(dialog, tablo) -> bool:
    """F2 yalnız satır tablosu (veya üstündeki hücre editörü) odaktayken stok kartı açar."""
    try:
        odak = dialog.focus_get()
    except (tk.TclError, KeyError):
        return False
    return odak is not None and str(odak).startswith(str(tablo))


def combobox_listesini_ac(editor) -> None:
    try:
        editor.tk.call("ttk::combobox::Post", str(editor))
    except tk.TclError:
        pass


def ok_ile_gec(editor, yon: int) -> bool:
    """Sağ/sol ok hücreden çıkar mı: seçim listesi her zaman; metinde tümü seçiliyken veya imleç uçtayken."""
    try:
        if isinstance(editor, ttk.Combobox) and str(editor.cget("state")) == "readonly":
            return True
        metin = editor.get()
        if editor.selection_present():
            return editor.index("sel.first") == 0 and editor.index("sel.last") >= len(metin)
        konum = editor.index("insert")
    except tk.TclError:
        return True
    return konum >= len(metin) if yon > 0 else konum <= 0


def iskonto_parcalari(metin: str, adet: int = 3) -> list[str]:
    """«10+5» → ["10", "5", "0"] (hücre editörü başlangıç değerleri)."""
    parcalar = [p.strip() for p in str(metin or "").replace("%", "").split("+") if p.strip()]
    parcalar = parcalar[:adet]
    return parcalar + ["0"] * (adet - len(parcalar))


def iskonto_birlestir(degerler: Sequence[str]) -> str:
    """["10", "", "5"] → «10+0+5»; sondaki sıfırlar atılır."""
    temiz = [(str(d or "").strip() or "0") for d in degerler]
    while len(temiz) > 1 and temiz[-1] in ("0", "0,0", "0,00", "0.0", "0.00"):
        temiz.pop()
    return "+".join(temiz)


class UcluIskontoEditor(tk.Frame):
    """İskonto hücresinin üstünde 1–3 ardışık giriş kutusu.

    on_bitir(degerler, hareket) değeri yazar; hareket: ileri | geri | yukari | asagi | kal.
    Geçersiz değerde False döner ve editör açık kalır.
    """

    def __init__(
        self,
        tablo: ttk.Treeview,
        box: tuple[int, int, int, int],
        degerler: Sequence[str],
        *,
        on_bitir: Callable[[list[str], str], bool],
        on_iptal: Callable[[], None],
        adet: int = 3,
        yukseklik: int | None = None,
    ):
        super().__init__(tablo, bd=0, highlightthickness=1, highlightbackground="#1D4ED8")
        self._on_bitir = on_bitir
        self._on_iptal = on_iptal
        self._isleniyor = False
        self.kutular: list[ttk.Entry] = []
        self._degiskenler: list[tk.StringVar] = []
        adet = max(1, min(3, int(adet)))
        for i in range(adet):
            var = tk.StringVar(value=str(degerler[i]) if i < len(degerler) else "0")
            kutu = ttk.Entry(self, textvariable=var, justify="right", font=("Segoe UI", 10), width=4)
            kutu.grid(row=0, column=i, sticky="nsew")
            self.columnconfigure(i, weight=1, uniform="iskonto")
            kutu.bind("<Return>", lambda _e, k=i: self._ileri(k))
            kutu.bind("<KP_Enter>", lambda _e, k=i: self._ileri(k))
            kutu.bind("<Tab>", lambda _e, k=i: self._ileri(k))
            kutu.bind("<Shift-Tab>", lambda _e, k=i: self._geri(k))
            kutu.bind("<ISO_Left_Tab>", lambda _e, k=i: self._geri(k))
            kutu.bind("<Shift-Return>", lambda _e, k=i: self._geri(k))
            kutu.bind("<Right>", lambda _e, k=i: self._ileri(k) if ok_ile_gec(self.kutular[k], 1) else None)
            kutu.bind("<Left>", lambda _e, k=i: self._geri(k) if ok_ile_gec(self.kutular[k], -1) else None)
            kutu.bind("<Up>", lambda _e: self._bitir("yukari"))
            kutu.bind("<Down>", lambda _e: self._bitir("asagi"))
            kutu.bind("<Escape>", lambda _e: (self._on_iptal(), "break")[1])
            self.kutular.append(kutu)
            self._degiskenler.append(var)
        self.rowconfigure(0, weight=1)
        bx, by, bw, bh = box
        genislik = max(int(bw), adet * _ISKONTO_MIN_KUTU)
        try:
            tablo_gen = int(tablo.winfo_width())
        except tk.TclError:
            tablo_gen = 0
        if tablo_gen > 0 and bx + genislik > tablo_gen:
            bx = max(0, tablo_gen - genislik)
        self.place(x=bx, y=by, width=genislik, height=max(int(bh), int(yukseklik or 24)))
        self.lift()
        self._uygula_fn = lambda: self._bitir("kal")
        self.kutu_odakla(0)

    def degerler(self) -> list[str]:
        return [v.get().strip() for v in self._degiskenler]

    def kutu_odakla(self, i: int) -> None:
        kutu = self.kutular[i]
        try:
            kutu.focus_set()
            kutu.selection_range(0, "end")
            kutu.icursor("end")
        except tk.TclError:
            pass

    def _ileri(self, i: int):
        if i < len(self.kutular) - 1:
            self.kutu_odakla(i + 1)
            return "break"
        return self._bitir("ileri")

    def _geri(self, i: int):
        if i > 0:
            self.kutu_odakla(i - 1)
            return "break"
        return self._bitir("geri")

    def _bitir(self, hareket: str):
        if self._isleniyor:
            return "break"
        self._isleniyor = True
        try:
            self._on_bitir(self.degerler(), hareket)
        finally:
            self._isleniyor = False
        return "break"
