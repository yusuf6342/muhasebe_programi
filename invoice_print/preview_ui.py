"""Fatura Yazdırma Önizleme penceresi."""

from __future__ import annotations

import logging
import tempfile
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from invoice_print.html_renderer import render_invoice_html
from invoice_print.pdf_service import render_invoice_to_pdf, safe_pdf_filename
from invoice_print.printer_service import print_invoice
from invoice_print.service import InvoicePrintService
from invoice_print.settings import load_print_settings, save_print_settings
from invoice_print.view_model import InvoicePrintViewModel

_LOG = logging.getLogger("invoice_print.preview_ui")

ZOOM_SEVIYELERI = (50, 75, 100, 125, 150)


class FaturaYazdirmaOnizlemeDialog(tk.Toplevel):
    def __init__(self, parent, vm: InvoicePrintViewModel):
        super().__init__(parent)
        self.parent = parent
        self.vm = vm
        self.zoom = 100
        self.sayfa = 1
        self._html_path: Path | None = None
        self.title(f"Fatura Yazdırma Önizleme — {vm.fatura_no}")
        self.geometry("980x720")
        self.minsize(720, 520)
        self.transient(parent)
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.configure(bg="#6B7280")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-p>", lambda _e: self._yazdir())
        self.bind("<Control-P>", lambda _e: self._yazdir())
        self.bind("<Control-e>", lambda _e: self._pdf_kaydet())
        self.bind("<Control-E>", lambda _e: self._pdf_kaydet())
        self.bind("<Left>", lambda _e: self._onceki())
        self.bind("<Right>", lambda _e: self._sonraki())
        self._toolbar()
        self._govde()
        self._yenile_onizleme()

    def _toolbar(self):
        bar = tk.Frame(self, bg="#111827", pady=6, padx=8)
        bar.pack(fill="x")

        def btn(metin, cmd, bg="#F5C518", fg="#111"):
            b = tk.Button(
                bar,
                text=metin,
                command=cmd,
                bg=bg,
                fg=fg,
                relief="flat",
                padx=8,
                pady=3,
                font=("Segoe UI", 9, "bold"),
                cursor="hand2",
            )
            b.pack(side="left", padx=2)
            return b

        btn("◀", self._onceki, "#374151", "#fff")
        self.sayfa_lbl = tk.Label(bar, text="1 / 1", bg="#111827", fg="#fff", width=8)
        self.sayfa_lbl.pack(side="left", padx=4)
        btn("▶", self._sonraki, "#374151", "#fff")
        btn("−", self._uzaklastir, "#374151", "#fff")
        self.zoom_lbl = tk.Label(bar, text="100%", bg="#111827", fg="#F5C518", width=5)
        self.zoom_lbl.pack(side="left")
        btn("+", self._yakinlastir, "#374151", "#fff")
        btn("Sığdır", self._sigdir, "#374151", "#fff")
        btn("%100", self._gercek, "#374151", "#fff")
        btn("Tarayıcıda Aç", self._tarayici)
        btn("Yazdır", self._yazdir)
        btn("PDF Kaydet", self._pdf_kaydet)
        btn("E-posta PDF", self._email_pdf)
        self.sablon = ttk.Combobox(
            bar,
            values=("kurumsal", "sade", "dahili"),
            width=10,
            state="readonly",
        )
        self.sablon.set(self.vm.sablon_id or "kurumsal")
        self.sablon.pack(side="left", padx=6)
        self.sablon.bind("<<ComboboxSelected>>", lambda _e: self._sablon_degisti())
        btn("Ayarlar", self._ayarlar, "#374151", "#fff")
        btn("Kapat", self.destroy, "#9CA3AF", "#111")

    def _govde(self):
        cerceve = tk.Frame(self, bg="#9CA3AF")
        cerceve.pack(fill="both", expand=True, padx=8, pady=8)
        self.canvas = tk.Canvas(cerceve, bg="#9CA3AF", highlightthickness=0)
        sy = ttk.Scrollbar(cerceve, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sy.set)
        sy.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg="#9CA3AF")
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="n")
        self.inner.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self._win, width=e.width),
        )
        self.ozet = tk.Label(
            self.inner,
            text="",
            bg="#FFFFFF",
            fg="#111827",
            justify="left",
            anchor="nw",
            font=("Segoe UI", 10),
            padx=24,
            pady=20,
            wraplength=700,
        )
        self.ozet.pack(pady=16, padx=40, fill="x")
        tk.Label(
            self.inner,
            text="Tam A4 görünümü için «Tarayıcıda Aç» veya Yazdır / PDF kullanın.\n"
            "Önizleme, PDF ve yazıcı aynı veri modelini kullanır.",
            bg="#9CA3AF",
            fg="#1F2937",
            font=("Segoe UI", 9),
        ).pack(pady=(0, 12))

    def _toplam_sayfa(self) -> int:
        return max(1, len(self.vm.sayfalar or [self.vm.satirlar]))

    def _yenile_onizleme(self):
        ts = self._toplam_sayfa()
        self.sayfa = max(1, min(self.sayfa, ts))
        self.sayfa_lbl.configure(text=f"{self.sayfa} / {ts}")
        self.zoom_lbl.configure(text=f"%{self.zoom}")
        f = self.vm.firma or {}
        m = self.vm.musteri or {}
        sayfa_satir = (self.vm.sayfalar or [self.vm.satirlar])[self.sayfa - 1]
        satir_ozet = "\n".join(
            f"  {s.sira}. {s.urun_kodu} {s.urun_adi} — {s.miktar_goster} {s.birim} "
            f"| {s.satir_toplam_goster}"
            for s in sayfa_satir[:30]
        )
        if len(sayfa_satir) > 30:
            satir_ozet += f"\n  … +{len(sayfa_satir) - 30} satır"
        filigran = f"\n\n⚠ {self.vm.filigran}" if self.vm.filigran else ""
        metin = (
            f"{self.vm.belge_turu}\n"
            f"{f.get('unvan') or ''}\n"
            f"Fatura: {self.vm.fatura_no}   Tarih: {self.vm.fatura_tarihi}   "
            f"Vade: {self.vm.vade_tarihi}\n"
            f"Sayın: {m.get('cari_kodu') or ''} {m.get('unvan') or ''}\n"
            f"{'─' * 56}\n"
            f"{satir_ozet}\n"
            f"{'─' * 56}\n"
            f"Genel Toplam: {self.vm.genel_goster}\n"
            f"{self.vm.yaziyla_toplam}\n"
            f"Sayfa {self.sayfa}/{ts}   Zoom %{self.zoom}"
            f"{filigran}"
        )
        self.ozet.configure(text=metin, wraplength=max(480, int(7 * self.zoom)))
        try:
            klasor = Path(tempfile.gettempdir()) / "muhasebe_fatura_a4"
            klasor.mkdir(parents=True, exist_ok=True)
            self._html_path = klasor / f"preview_{id(self)}.html"
            self._html_path.write_text(
                render_invoice_html(self.vm, zoom_pct=self.zoom, toolbar=True),
                encoding="utf-8",
            )
        except Exception as exc:
            _LOG.exception("Önizleme HTML yazılamadı: %s", exc)

    def _onceki(self):
        if self.sayfa > 1:
            self.sayfa -= 1
            self._yenile_onizleme()

    def _sonraki(self):
        if self.sayfa < self._toplam_sayfa():
            self.sayfa += 1
            self._yenile_onizleme()

    def _yakinlastir(self):
        i = ZOOM_SEVIYELERI.index(self.zoom) if self.zoom in ZOOM_SEVIYELERI else 2
        self.zoom = ZOOM_SEVIYELERI[min(len(ZOOM_SEVIYELERI) - 1, i + 1)]
        self._yenile_onizleme()

    def _uzaklastir(self):
        i = ZOOM_SEVIYELERI.index(self.zoom) if self.zoom in ZOOM_SEVIYELERI else 2
        self.zoom = ZOOM_SEVIYELERI[max(0, i - 1)]
        self._yenile_onizleme()

    def _sigdir(self):
        self.zoom = 75
        self._yenile_onizleme()

    def _gercek(self):
        self.zoom = 100
        self._yenile_onizleme()

    def _tarayici(self):
        if self._html_path and self._html_path.is_file():
            webbrowser.open(self._html_path.as_uri())
        else:
            webbrowser.open(InvoicePrintService.open_html_preview(self.vm).as_uri())

    def _yazdir(self):
        try:
            print_invoice(self.vm)
            messagebox.showinfo(
                "Yazdır",
                "Belge tarayıcıda açıldı.\nYazıcı seçmek için yazdır diyaloğunu kullanın (Ctrl+P).",
                parent=self,
            )
        except ValueError as exc:
            messagebox.showerror("Yazdır", str(exc), parent=self)

    def _pdf_yolu_sec(self) -> Path | None:
        ayar = load_print_settings()
        baslangic = ayar.get("son_pdf_klasoru") or str(Path.home() / "Documents")
        ad = safe_pdf_filename(self.vm)
        yol = filedialog.asksaveasfilename(
            parent=self,
            title="PDF Kaydet",
            initialdir=baslangic,
            initialfile=ad,
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not yol:
            return None
        p = Path(yol)
        ayar["son_pdf_klasoru"] = str(p.parent)
        try:
            save_print_settings(ayar)
        except Exception:
            pass
        return p

    def _pdf_kaydet(self):
        hedef = self._pdf_yolu_sec()
        if not hedef:
            return
        try:
            render_invoice_to_pdf(self.vm, hedef)
            messagebox.showinfo("PDF", f"PDF kaydedildi:\n{hedef}", parent=self)
        except ValueError as exc:
            messagebox.showerror("PDF", str(exc), parent=self)
        except Exception as exc:
            _LOG.exception("PDF hata: %s", exc)
            messagebox.showerror(
                "PDF",
                "Fatura PDF dosyası oluşturulamadı. Kayıt klasörünü ve dosya izinlerini kontrol edin.",
                parent=self,
            )

    def _email_pdf(self):
        self._pdf_kaydet()

    def _sablon_degisti(self):
        sid = self.sablon.get() or "kurumsal"
        if sid == "dahili":
            try:
                InvoicePrintService.yetki_kontrol("dahili")
            except PermissionError as exc:
                messagebox.showwarning("Yetki", str(exc), parent=self)
                self.sablon.set(self.vm.sablon_id or "kurumsal")
                return
        try:
            parent = self.parent
            if getattr(parent, "satirlar", None) is not None:
                self.vm = InvoicePrintService.build_from_kart(parent, template_id=sid)
            elif self.vm.fatura_id:
                self.vm = InvoicePrintService.build_invoice_print_model(
                    self.vm.fatura_id, template_id=sid
                )
            else:
                self.vm.sablon_id = sid
            self.sayfa = 1
            self._yenile_onizleme()
        except Exception as exc:
            messagebox.showerror("Şablon", str(exc), parent=self)

    def _ayarlar(self):
        from invoice_print.settings_ui import FaturaYazdirmaAyarlariDialog

        FaturaYazdirmaAyarlariDialog(self)


def fatura_yazdirma_onizleme_ac(parent, *, kart=None, fatura_id: int | None = None):
    try:
        InvoicePrintService.yetki_kontrol("onizleme")
        vm = InvoicePrintService.preview_invoice(fatura_id, kart=kart)
    except ValueError as exc:
        messagebox.showerror("Önizleme", str(exc), parent=parent)
        return None
    except Exception as exc:
        _LOG.exception("Önizleme açılamadı: %s", exc)
        messagebox.showerror(
            "Önizleme",
            "Fatura önizlemesi açılamadı. Lütfen faturayı kontrol edip tekrar deneyin.",
            parent=parent,
        )
        return None
    return FaturaYazdirmaOnizlemeDialog(parent, vm)
