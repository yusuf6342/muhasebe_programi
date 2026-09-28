"""Makbuz çıktı önizlemesi — tekli / toplu; Yazdır, PDF Oluştur, Word Oluştur.

Önizleme, yazdırılacak PDF'in kendisinden çizilir. Çıktı almak hiçbir kayıt oluşturmaz veya değiştirmez.
"""

from __future__ import annotations

import base64
import os
import tempfile
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import makbuz_cikti as mc
from satis_tema import ACIK_BG, ACIK_SARI, BASARI, BEYAZ, CIZGI, IKINCIL, LACIVERT, SARI, UYARI, font, stil_uygula, tk_buton

YAZDIRMA_IPUCU = {
    mc.A5: "Yazıcı penceresinde kâğıt: A5 · Yön: Dikey · Ölçek: Gerçek boyut (%100).",
    mc.A4_IKILI: "Yazıcı penceresinde kâğıt: A4 · Yön: Yatay · Ölçek: Gerçek boyut (%100). Kesim çizgisinden ikiye ayırın.",
}
_ETIKET_YERLESIM = {etiket: kod for kod, etiket in mc.YERLESIMLER.items()}


def dosyayi_ac(yol) -> None:
    os.startfile(str(yol))  # type: ignore[attr-defined]


def _varsayilan_klasor() -> Path:
    for aday in (Path.home() / "Documents", Path.home() / "Belgeler", Path.home()):
        if aday.is_dir():
            return aday
    return Path.cwd()


class MakbuzCiktiDialog(tk.Toplevel):
    son_klasor: Path | None = None

    def __init__(self, parent, makbuz_ids, yerlesim: str = mc.A5, *, veriler: list[dict] | None = None):
        super().__init__(parent)
        self.withdraw()
        self.makbuz_ids = [int(i) for i in makbuz_ids]
        if not self.makbuz_ids and not veriler:
            self.destroy()
            raise ValueError("Çıktı için en az bir makbuz seçin.")
        try:
            self.veriler = veriler if veriler is not None else mc.makbuz_cikti_verileri(self.makbuz_ids)
        except Exception:
            self.destroy()
            raise
        self.yerlesim = yerlesim if yerlesim in mc.YERLESIMLER else mc.A5
        self.sayfa = 0
        self._pdf: dict[str, bytes] = {}
        self._belge = None
        self._resim = None
        self._cizim_after = None

        stil_uygula(root=self)
        self.configure(bg=ACIK_BG)
        self.title(self._baslik())
        self._boyutlandir()
        self._arayuz()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Prior>", lambda _e: self.sayfa_git(-1))
        self.bind("<Next>", lambda _e: self.sayfa_git(1))
        self.bind("<Control-p>", lambda _e: (self.yazdir(), "break")[1])

        self._onceki_grab = self.grab_current()
        if self._onceki_grab is not None:
            self.transient(self._onceki_grab.winfo_toplevel())
        else:
            try:
                self.transient(parent.winfo_toplevel())
            except tk.TclError:
                pass
        self.deiconify()
        if self._onceki_grab is not None:
            self.grab_set()
            self.bind("<Destroy>", self._grab_geri_ver, add="+")
        self._yerlesimi_uygula()
        self.focus_set()

    # ─── Pencere ─────────────────────────────────────────────────
    def _baslik(self) -> str:
        if len(self.veriler) == 1:
            v = self.veriler[0]
            return f"Makbuz Çıktısı — {v['makbuz_no'] or v['belge_no']}"
        return f"Makbuz Çıktısı — {len(self.veriler)} makbuz"

    def _boyutlandir(self):
        try:
            from ui_pencere import calisma_alani

            x, y, gen, yuk = calisma_alani(self)
        except Exception:
            x, y, gen, yuk = 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()
        genislik = max(760, min(1100, gen - 60))
        yukseklik = max(480, min(900, yuk - 40))
        self.minsize(min(760, gen), min(440, yuk))
        self.geometry(f"{genislik}x{yukseklik}+{x + (gen - genislik) // 2}+{y + max(0, (yuk - yukseklik) // 2)}")

    def _grab_geri_ver(self, event):
        if event.widget is not self:
            return
        onceki = self._onceki_grab
        try:
            if onceki is not None and onceki.winfo_exists():
                onceki.after_idle(onceki.grab_set)
        except tk.TclError:
            pass

    def _arayuz(self):
        ust = tk.Frame(self, bg=LACIVERT)
        ust.pack(side="top", fill="x")
        tk.Label(ust, text=self._baslik().upper(), bg=LACIVERT, fg=BEYAZ, font=font(15, "bold", self), anchor="w").pack(
            side="top", anchor="w", padx=16, pady=(10, 0)
        )
        nolar = ", ".join(v["makbuz_no"] or v["belge_no"] for v in self.veriler[:8])
        if len(self.veriler) > 8:
            nolar += f" … (+{len(self.veriler) - 8})"
        tk.Label(ust, text=nolar, bg=LACIVERT, fg=ACIK_SARI, font=font(10, root=self), anchor="w").pack(
            side="top", anchor="w", padx=16, pady=(2, 10)
        )
        tk.Frame(self, bg=SARI, height=3).pack(side="top", fill="x")

        arac = tk.Frame(self, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        arac.pack(side="top", fill="x")
        sol = tk.Frame(arac, bg=BEYAZ)
        sol.pack(side="left", padx=10, pady=8)
        tk.Label(sol, text="Sayfa düzeni", bg=BEYAZ, fg=IKINCIL, font=font(10, root=self)).pack(side="left")
        self.yerlesim_cb = ttk.Combobox(sol, values=tuple(mc.YERLESIMLER.values()), state="readonly", width=46)
        self.yerlesim_cb.set(mc.YERLESIMLER[self.yerlesim])
        self.yerlesim_cb.pack(side="left", padx=(6, 14))
        self.yerlesim_cb.bind("<<ComboboxSelected>>", self._yerlesim_secildi)
        self.btn_onceki = tk_buton(sol, "◀", lambda: self.sayfa_git(-1), rol="geri", width=3)
        self.btn_onceki.pack(side="left")
        self.sayfa_lbl = tk.Label(sol, bg=BEYAZ, fg=LACIVERT, font=font(10, "bold", self), width=13)
        self.sayfa_lbl.pack(side="left", padx=4)
        self.btn_sonraki = tk_buton(sol, "▶", lambda: self.sayfa_git(1), rol="geri", width=3)
        self.btn_sonraki.pack(side="left")

        alt = tk.Frame(self, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        alt.pack(side="bottom", fill="x")
        alt.columnconfigure(0, weight=1)
        bilgi = tk.Frame(alt, bg=BEYAZ)
        bilgi.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=6)
        self.ipucu_lbl = tk.Label(bilgi, bg=BEYAZ, fg=IKINCIL, font=font(9, root=self), anchor="w", justify="left")
        self.ipucu_lbl.pack(side="top", fill="x")
        self.mesaj_lbl = tk.Label(bilgi, bg=BEYAZ, fg=IKINCIL, font=font(9, root=self), anchor="w", justify="left")
        self.mesaj_lbl.pack(side="top", fill="x", pady=(2, 0))
        bilgi.bind(
            "<Configure>",
            lambda e: [lbl.configure(wraplength=max(160, e.width - 4)) for lbl in (self.ipucu_lbl, self.mesaj_lbl)],
            add="+",
        )
        dugmeler = tk.Frame(alt, bg=BEYAZ)
        dugmeler.grid(row=0, column=1, sticky="e", padx=8, pady=8)
        self.btn_yazdir = tk_buton(dugmeler, "Yazdır  (Ctrl+P)", self.yazdir, rol="yazdir")
        self.btn_pdf = tk_buton(dugmeler, "PDF Oluştur", self.pdf_olustur, rol="kaydet")
        self.btn_word = tk_buton(dugmeler, "Word Oluştur", self.word_olustur, rol="duzenle")
        self.btn_kapat = tk_buton(dugmeler, "Kapat", self.destroy, rol="geri")
        for b in (self.btn_yazdir, self.btn_pdf, self.btn_word, self.btn_kapat):
            b.pack(side="left", padx=4)

        self.kanvas = tk.Canvas(self, bg="#8795A1", highlightthickness=0, bd=0)
        self.kanvas.pack(side="top", fill="both", expand=True)
        self.kanvas.bind("<Configure>", lambda _e: self._cizimi_planla())
        self.kanvas.bind("<MouseWheel>", lambda e: self.sayfa_git(-1 if e.delta > 0 else 1))

    # ─── Önizleme ────────────────────────────────────────────────
    def pdf(self, yerlesim: str | None = None) -> bytes:
        yerlesim = yerlesim or self.yerlesim
        if yerlesim not in self._pdf:
            self._pdf[yerlesim] = mc.pdf_uret(self.veriler, yerlesim)
        return self._pdf[yerlesim]

    @property
    def sayfa_sayisi(self) -> int:
        return len(self._belge) if self._belge is not None else 0

    def _yerlesim_secildi(self, _e=None):
        kod = _ETIKET_YERLESIM.get(self.yerlesim_cb.get(), mc.A5)
        if kod != self.yerlesim:
            self.yerlesim_degistir(kod)

    def yerlesim_degistir(self, yerlesim: str):
        self.yerlesim = yerlesim if yerlesim in mc.YERLESIMLER else mc.A5
        self.yerlesim_cb.set(mc.YERLESIMLER[self.yerlesim])
        self._yerlesimi_uygula()

    def _yerlesimi_uygula(self):
        fitz = mc._fitz()
        try:
            self._belge = fitz.open(stream=self.pdf(), filetype="pdf")
        except Exception as hata:
            self._belge = None
            self._mesaj(f"Önizleme hazırlanamadı: {hata}", UYARI)
            return
        self.sayfa = 0
        adet = len(self.veriler)
        self.ipucu_lbl.configure(
            text=f"{adet} makbuz · {self.sayfa_sayisi} sayfa · {mc.YERLESIMLER[self.yerlesim]}\n"
            f"{YAZDIRMA_IPUCU[self.yerlesim]}"
        )
        self._cizimi_planla()

    def sayfa_git(self, adim: int):
        if not self.sayfa_sayisi:
            return "break"
        yeni = max(0, min(self.sayfa_sayisi - 1, self.sayfa + adim))
        if yeni != self.sayfa:
            self.sayfa = yeni
            self._ciz()
        return "break"

    def _cizimi_planla(self):
        if self._cizim_after:
            try:
                self.after_cancel(self._cizim_after)
            except tk.TclError:
                pass
        self._cizim_after = self.after(60, self._ciz)

    def _ciz(self):
        self._cizim_after = None
        if not self.winfo_exists() or self._belge is None:
            return
        toplam = self.sayfa_sayisi
        self.sayfa_lbl.configure(text=f"Sayfa {self.sayfa + 1} / {toplam}")
        self.btn_onceki.configure(state="normal" if self.sayfa > 0 else "disabled")
        self.btn_sonraki.configure(state="normal" if self.sayfa < toplam - 1 else "disabled")
        gen = max(200, self.kanvas.winfo_width())
        yuk = max(200, self.kanvas.winfo_height())
        page = self._belge[self.sayfa]
        olcek = max(0.1, min((gen - 32) / page.rect.width, (yuk - 32) / page.rect.height))
        fitz = mc._fitz()
        png = page.get_pixmap(matrix=fitz.Matrix(olcek, olcek), alpha=False).tobytes("png")
        self._resim = tk.PhotoImage(data=base64.b64encode(png).decode("ascii"))
        self.kanvas.delete("all")
        cx, cy = gen // 2, yuk // 2
        w, h = self._resim.width(), self._resim.height()
        self.kanvas.create_rectangle(cx - w // 2 + 4, cy - h // 2 + 4, cx + w // 2 + 4, cy + h // 2 + 4, fill="#5F6B76", outline="")
        self.kanvas.create_image(cx, cy, image=self._resim, tags=("sayfa",))

    def _mesaj(self, metin: str, renk: str = IKINCIL):
        if self.winfo_exists():
            self.mesaj_lbl.configure(text=metin, fg=renk)

    # ─── Çıktı ───────────────────────────────────────────────────
    def yazdir(self):
        try:
            klasor = Path(tempfile.gettempdir()) / "CinMuhasebe_Yazdir"
            klasor.mkdir(parents=True, exist_ok=True)
            ad = mc.dosya_adi(self.veriler, self.yerlesim, "pdf")
            hedef = mc.bos_dosya_yolu(klasor / ad)
            mc._yaz(hedef, self.pdf(), False)
            dosyayi_ac(hedef)
        except Exception as hata:
            messagebox.showerror("Yazdır", f"Yazdırma dosyası açılamadı:\n{hata}", parent=self)
            return None
        self._mesaj(
            f"Yazdırma dosyası PDF görüntüleyicide açıldı ({datetime.now():%H:%M}). {YAZDIRMA_IPUCU[self.yerlesim]}",
            BASARI,
        )
        return hedef

    def _kaydet(self, uzanti: str, aciklama: str, uretici):
        ad = mc.dosya_adi(self.veriler, self.yerlesim, uzanti)
        klasor = MakbuzCiktiDialog.son_klasor or _varsayilan_klasor()
        yol = filedialog.asksaveasfilename(
            parent=self,
            title=f"{aciklama} Kaydet",
            initialdir=str(klasor),
            initialfile=ad,
            defaultextension=f".{uzanti}",
            filetypes=[(aciklama, f"*.{uzanti}")],
            confirmoverwrite=True,
        )
        if not yol:
            return None
        hedef = Path(yol)
        if hedef.suffix.lower() != f".{uzanti}":
            hedef = hedef.with_name(hedef.name + f".{uzanti}")
            if hedef.exists() and not messagebox.askyesno(
                f"{aciklama} Kaydet", f"{hedef.name} zaten var.\nÜzerine yazılsın mı?", parent=self
            ):
                return None
        try:
            # Aynı adlı dosya için üzerine yazma onayı kayıt penceresinde alındı.
            uretici(self.veriler, hedef, self.yerlesim, uzerine_yaz=True)
        except Exception as hata:
            messagebox.showerror(f"{aciklama} Kaydet", str(hata), parent=self)
            return None
        MakbuzCiktiDialog.son_klasor = hedef.parent
        self._mesaj(f"{aciklama} kaydedildi: {hedef}", BASARI)
        if messagebox.askyesno(f"{aciklama} Kaydet", f"Dosya kaydedildi:\n{hedef}\n\nŞimdi açılsın mı?", parent=self):
            try:
                dosyayi_ac(hedef)
            except OSError as hata:
                messagebox.showerror(f"{aciklama} Kaydet", str(hata), parent=self)
        return hedef

    def pdf_olustur(self):
        return self._kaydet("pdf", "PDF dosyası", self._pdf_yaz)

    def word_olustur(self):
        return self._kaydet("docx", "Word belgesi", mc.docx_kaydet)

    def _pdf_yaz(self, veriler, hedef, yerlesim, *, uzerine_yaz):
        return mc._yaz(Path(hedef), self.pdf(yerlesim), uzerine_yaz)


def makbuz_ciktisi_ac(parent, makbuz_ids, yerlesim: str = mc.A5, *, bekle: bool = False) -> MakbuzCiktiDialog | None:
    try:
        dialog = MakbuzCiktiDialog(parent, makbuz_ids, yerlesim)
    except Exception as hata:
        messagebox.showerror("Makbuz Çıktısı", f"Çıktı hazırlanamadı:\n{hata}", parent=parent)
        return None
    if bekle and dialog.winfo_exists():
        parent.wait_window(dialog)
    return dialog
