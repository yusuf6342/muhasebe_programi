"""Cari / yetkili fotoğraf alanı — ortak bileşen (yükle, değiştir, kaldır, büyük görüntü).

Önizleme arka planda yüklenir; geç gelen sonuç başka cari/kişiye geçildiyse yok sayılır.
``aninda=False`` iken seçim formda bekler ve ``bekleyeni_uygula`` ile kaydedilir.
"""

from __future__ import annotations

import io
import tkinter as tk
from tkinter import filedialog, messagebox

from cari_kart_tema import BEYAZ, CIZGI, IKINCIL, LACIVERT, font, tk_buton
from database.cari_foto_service import DOSYA_FILTRESI, CariFotoService, goruntu_hazirla

_ZEMIN = "#F1F4F9"


class FotoAlani(tk.Frame):
    def __init__(self, parent, *, sahip_turu: str, baslik: str, aninda: bool = True,
                 sabit_boyut: tuple[int, int] | None = None, on_degisim=None, bg: str = BEYAZ):
        super().__init__(parent, bg=bg)
        self.sahip_turu = sahip_turu
        self.aninda = aninda
        self._on_degisim = on_degisim
        self.sahip_id: int | None = None
        self.cari_id: int | None = None
        self._token = 0
        self._pil = None
        self._tk_img = None
        self._var = False
        self._mesgul = False
        self._ciz_after = None
        # Bekleyen değişiklik: None | ("YUKLE", hazir dict) | ("KALDIR", None)
        self.bekleyen: tuple | None = None

        tk.Label(self, text=baslik, bg=bg, fg=LACIVERT, font=font(9, "bold", self)).pack(anchor="w")
        alt = tk.Frame(self, bg=bg)
        alt.pack(side="bottom", fill="x", pady=(4, 0))
        self.yukle_btn = tk_buton(alt, "Yükle", self.dosya_sec, rol="ikincil")
        self.yukle_btn.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.kaldir_btn = tk_buton(alt, "Kaldır", self.kaldir, rol="ikincil")
        self.kaldir_btn.pack(side="left", fill="x", expand=True, padx=(2, 0))
        if sabit_boyut:
            self.tuval = tk.Canvas(self, width=sabit_boyut[0], height=sabit_boyut[1], bg=_ZEMIN,
                                   highlightthickness=1, highlightbackground=CIZGI)
            self.tuval.pack(pady=(2, 0))
        else:
            self.tuval = tk.Canvas(self, width=1, height=1, bg=_ZEMIN,
                                   highlightthickness=1, highlightbackground=CIZGI)
            self.tuval.pack(fill="both", expand=True, pady=(2, 0))
        self.tuval.bind("<Configure>", lambda _e: self._ciz_planla())
        self.tuval.bind("<Double-Button-1>", lambda _e: self.buyuk_goster())
        self._dugmeleri_ayarla()

    # --- Sahip / yükleme ---

    def sahip_ata(self, sahip_id: int | None, *, cari_id: int | None = None) -> None:
        """Başka cari/kişiye geçiş: eski görüntü hemen temizlenir, yenisi arka planda gelir."""
        self._token += 1
        token = self._token
        self.sahip_id = int(sahip_id) if sahip_id else None
        self.cari_id = int(cari_id) if cari_id else (self.sahip_id if self.sahip_turu == "CARI" else None)
        self.bekleyen = None
        self._pil = None
        self._var = False
        self._ciz()
        self._dugmeleri_ayarla()
        if not self.sahip_id:
            return
        sahip_turu, sahip, cari = self.sahip_turu, self.sahip_id, self.cari_id

        def _is():
            return CariFotoService.getir(sahip_turu, sahip, cari_id=cari)

        def _ok(veri):
            if token != self._token or not self.winfo_exists():
                return
            self._goruntu_ata(veri)

        from ui_bg import arka_planda

        arka_planda(self, _is, on_ok=_ok, on_err=lambda _h: None)

    def _goruntu_ata(self, veri: bytes | None) -> None:
        self._pil = None
        if veri:
            try:
                from PIL import Image

                with Image.open(io.BytesIO(veri)) as img:
                    img.load()
                    self._pil = img.copy()
            except Exception:
                self._pil = None
        self._var = self._pil is not None
        self._ciz()
        self._dugmeleri_ayarla()

    # --- Çizim ---

    def _ciz_planla(self):
        if self._ciz_after is not None:
            try:
                self.after_cancel(self._ciz_after)
            except tk.TclError:
                pass
        self._ciz_after = self.after(40, self._ciz)

    def _ciz(self):
        self._ciz_after = None
        try:
            w = max(20, self.tuval.winfo_width() - 4)
            h = max(20, self.tuval.winfo_height() - 4)
        except tk.TclError:
            return
        self.tuval.delete("all")
        if self._pil is None:
            r = min(w, h) // 6
            cx, cy = w // 2 + 2, h // 2 - r
            self.tuval.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#D5DCE6", outline="")
            self.tuval.create_arc(cx - 2 * r, cy + r + 4, cx + 2 * r, cy + 5 * r, start=0, extent=180,
                                  fill="#D5DCE6", outline="")
            self.tuval.create_text(w // 2 + 2, min(h - 8, cy + 4 * r), text="Fotoğraf yok", fill=IKINCIL,
                                   font=font(8, root=self))
            self._tk_img = None
            return
        from PIL import Image, ImageTk

        iw, ih = self._pil.size
        oran = min(w / iw, h / ih, 1.0)
        boy = (max(1, int(iw * oran)), max(1, int(ih * oran)))
        img = self._pil if boy == (iw, ih) else self._pil.resize(boy, Image.Resampling.LANCZOS)
        self._tk_img = ImageTk.PhotoImage(img, master=self)
        self.tuval.create_image(w // 2 + 2, h // 2 + 2, image=self._tk_img, anchor="center")

    def _dugmeleri_ayarla(self):
        gorunen_var = self._var
        try:
            self.yukle_btn.configure(text="Değiştir" if gorunen_var else "Yükle",
                                     state="disabled" if self._mesgul else "normal")
            self.kaldir_btn.configure(state="normal" if gorunen_var and not self._mesgul else "disabled")
        except tk.TclError:
            pass

    # --- Eylemler ---

    def dosya_sec(self):
        if self._mesgul:
            return
        yol = filedialog.askopenfilename(parent=self, title="Fotoğraf seç", filetypes=DOSYA_FILTRESI)
        if not yol:
            return  # İptal: mevcut görüntü korunur
        self._mesgul = True
        self._dugmeleri_ayarla()
        token = self._token

        def _ok(hazir):
            self._mesgul = False
            if token != self._token or not self.winfo_exists():
                return
            self._hazir_uygula(hazir)

        def _err(hata):
            self._mesgul = False
            if self.winfo_exists():
                self._dugmeleri_ayarla()
                messagebox.showerror("Fotoğraf", str(hata), parent=self)

        from ui_bg import arka_planda

        arka_planda(self, lambda: goruntu_hazirla(yol), on_ok=_ok, on_err=_err)

    def _hazir_uygula(self, hazir: dict) -> None:
        if self.aninda and self.sahip_id:
            try:
                CariFotoService.kaydet(self.sahip_turu, self.sahip_id, None, hazir=hazir)
            except (ValueError, PermissionError) as hata:
                self._dugmeleri_ayarla()
                messagebox.showerror("Fotoğraf", str(hata), parent=self)
                return
        else:
            self.bekleyen = ("YUKLE", hazir)
        self._goruntu_ata(hazir["kucuk"])
        if callable(self._on_degisim):
            self._on_degisim()

    def kaldir(self):
        if self._mesgul or not self._var:
            return
        if not messagebox.askyesno("Fotoğraf", "Fotoğraf kaldırılsın mı?", parent=self):
            return
        if self.aninda and self.sahip_id:
            try:
                CariFotoService.kaldir(self.sahip_turu, self.sahip_id)
            except (ValueError, PermissionError) as hata:
                messagebox.showerror("Fotoğraf", str(hata), parent=self)
                return
            self.bekleyen = None
        else:
            self.bekleyen = ("KALDIR", None) if self.sahip_id else None
        self._goruntu_ata(None)
        if callable(self._on_degisim):
            self._on_degisim()

    def bekleyeni_uygula(self, sahip_id: int) -> None:
        """Kaydedilmemiş sahibin (yeni cari/kişi) bekleyen fotoğraf değişikliğini yazar."""
        islem = self.bekleyen
        self.sahip_id = int(sahip_id)
        if self.sahip_turu == "CARI":
            self.cari_id = self.sahip_id
        if not islem:
            return
        if islem[0] == "YUKLE":
            CariFotoService.kaydet(self.sahip_turu, self.sahip_id, None, hazir=islem[1])
        else:
            CariFotoService.kaldir(self.sahip_turu, self.sahip_id)
        self.bekleyen = None

    def buyuk_goster(self):
        if not self._var:
            return
        veri = None
        if self.bekleyen and self.bekleyen[0] == "YUKLE":
            veri = self.bekleyen[1]["veri"]
        elif self.sahip_id:
            veri = CariFotoService.getir(self.sahip_turu, self.sahip_id, buyuk=True, cari_id=self.cari_id)
        if not veri:
            return
        from PIL import Image, ImageTk

        pencere = tk.Toplevel(self)
        pencere.title("Fotoğraf")
        pencere.configure(bg="#000000")
        pencere.transient(self.winfo_toplevel())
        with Image.open(io.BytesIO(veri)) as img:
            img.load()
            sw = max(200, self.winfo_screenwidth() - 160)
            sh = max(200, self.winfo_screenheight() - 200)
            img.thumbnail((sw, sh))
            pencere._img = ImageTk.PhotoImage(img, master=pencere)
        tk.Label(pencere, image=pencere._img, bg="#000000").pack()
        pencere.bind("<Escape>", lambda _e: pencere.destroy())
        pencere.bind("<Button-1>", lambda _e: pencere.destroy())
        pencere.focus_set()
