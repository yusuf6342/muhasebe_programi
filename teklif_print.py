"""Teklif çıktı şablonları — müşteri ve iç maliyet tamamen ayrı.

Şablonlar:
  A) customer_quote_template
  B) internal_quote_cost_analysis_template
"""

from __future__ import annotations

import html
import logging
import os
import re
import subprocess
import tempfile
import tkinter as tk
import webbrowser
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from database.teklif_customer_view import (
    CustomerQuoteSecurityError,
    CustomerQuoteViewModel,
    InternalQuoteCostViewModel,
    assert_customer_model_safe,
    assert_customer_output_safe,
    build_customer_quote_from_dialog,
    build_internal_cost_from_dialog,
    _para,
)
from teklif_customer_html import render_customer_quote_html

_LOG = logging.getLogger("teklif_print")

_TR_TRANSLIT = str.maketrans(
    {
        "ç": "c",
        "Ç": "C",
        "ğ": "g",
        "Ğ": "G",
        "ı": "i",
        "İ": "I",
        "ö": "o",
        "Ö": "O",
        "ş": "s",
        "Ş": "S",
        "ü": "u",
        "Ü": "U",
    }
)


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def render_internal_cost_html(vm: InternalQuoteCostViewModel) -> str:
    """internal_quote_cost_analysis_template — şirket içi."""
    satirlar = []
    for s in vm.satirlar:
        satirlar.append(
            "<tr>"
            f"<td>{s.sira}</td><td>{_e(s.urun_kodu)}</td><td>{_e(s.urun_adi)}</td>"
            f"<td class='r'>{_para(s.miktar)}</td><td>{_e(s.birim)}</td>"
            f"<td class='r'>{_para(s.alis_birim)}</td><td class='r'>{_para(s.alis_toplam)}</td>"
            f"<td>{_e(s.maliyet_kaynagi)}</td><td>{_e(s.maliyet_tarihi)}</td><td>{_e(s.tedarikci)}</td>"
            f"<td class='r'>{_para(s.dagitilan_masraf)}</td>"
            f"<td class='r'>{_para(s.dagitilan_yuzde_kar)}</td>"
            f"<td class='r'>{_para(s.dagitilan_maktu)}</td>"
            f"<td class='r'>{_para(s.teklif_birim)}</td><td class='r'>{_para(s.teklif_ara)}</td>"
            f"<td class='r'>{_para(s.gercek_kar)}</td><td class='r'>{_para(s.marj)}</td>"
            f"<td class='c'>{'M' if s.manuel else 'O'}</td>"
            "</tr>"
        )
    zarar = (
        f"<div class='zarar'>{_e(vm.zarar_uyarisi)}</div>" if vm.zarar_uyarisi else ""
    )
    return f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"/>
<title>İç Maliyet Analizi {_e(vm.teklif_no)}</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; font-size: 9pt; margin: 12px; }}
.bant {{ background:#C62828; color:#fff; font-weight:bold; text-align:center; padding:10px; font-size:12pt; letter-spacing:1px; }}
table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
th {{ background:#1B2A4A; color:#fff; font-size:7.5pt; padding:4px; }}
td {{ border:1px solid #ddd; padding:3px; font-size:8pt; }}
.r {{ text-align:right; }} .c {{ text-align:center; }}
.ozet td {{ padding:4px 8px; }}
.zarar {{ color:#C62828; font-weight:bold; margin:8px 0; }}
</style></head><body>
<div class="bant">{_e(vm.uyari_bant)}</div>
<h2>İç Teklif Maliyet Analizi</h2>
<p>Teklif: <strong>{_e(vm.teklif_no)}</strong> · Tarih: {_e(vm.teklif_tarihi)} · Müşteri: {_e(vm.musteri_unvan)}</p>
{zarar}
<table class="ozet">
<tr><td>Maliyet Kaynağı</td><td>{_e(vm.cost_source)}</td>
<td>Toplam Alış Maliyeti</td><td class="r">{_para(vm.total_purchase_cost)}</td></tr>
<tr><td>Maliyet Üzeri Kâr %</td><td>{_para(vm.profit_rate)}</td>
<td>Yüzdesel Kâr Tutarı</td><td class="r">{_para(vm.percentage_profit_amount)}</td></tr>
<tr><td>Maktu Kâr</td><td class="r">{_para(vm.fixed_profit_amount)}</td>
<td>Hedef Kâr</td><td class="r">{_para(vm.total_target_profit)}</td></tr>
<tr><td>Müşteri Masrafı</td><td class="r">{_para(vm.customer_expense_amount)}</td>
<td>İç Masraf</td><td class="r">{_para(vm.internal_expense_amount)}</td></tr>
<tr><td>KDV Hariç Teklif</td><td class="r">{_para(vm.calculated_offer_subtotal)}</td>
<td>Gerçekleşen Kâr</td><td class="r">{_para(vm.actual_profit_amount)}</td></tr>
<tr><td>Maliyet Üzeri Oran</td><td>{_para(vm.cost_markup_rate)}%</td>
<td>Satış Marjı</td><td>{_para(vm.sales_margin_rate)}%</td></tr>
</table>
<table>
<thead><tr>
<th>#</th><th>Kod</th><th>Ürün</th><th>Miktar</th><th>Birim</th>
<th>Alış Birim</th><th>Alış Toplam</th><th>Kaynak</th><th>Alış Tarihi</th><th>Tedarikçi</th>
<th>Dağ. Masraf</th><th>Dağ. %Kâr</th><th>Dağ. Maktu</th>
<th>Teklif Birim</th><th>Teklif Ara</th><th>Gerçek Kâr</th><th>Marj %</th><th>O/M</th>
</tr></thead>
<tbody>{''.join(satirlar)}</tbody>
</table>
<p style="margin-top:16px;color:#C62828;font-weight:bold">{_e(vm.uyari_bant)}</p>
</body></html>"""


def _chrome_paths() -> list[Path]:
    return [
        p
        for p in (
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        )
        if p.is_file()
    ]


def html_to_pdf(html_metin: str, hedef: Path) -> Path:
    hedef = Path(hedef).resolve()
    hedef.parent.mkdir(parents=True, exist_ok=True)
    klasor = Path(tempfile.gettempdir()) / "muhasebe_teklif_a4"
    klasor.mkdir(parents=True, exist_ok=True)
    html_yol = klasor / f"teklif_{datetime.now():%H%M%S%f}.html"
    html_yol.write_text(html_metin, encoding="utf-8")
    uri = html_yol.resolve().as_uri()
    for tarayici in _chrome_paths():
        try:
            proc = subprocess.run(
                [
                    str(tarayici),
                    "--headless=new",
                    "--disable-gpu",
                    "--no-pdf-header-footer",
                    f"--print-to-pdf={hedef}",
                    uri,
                ],
                capture_output=True,
                timeout=60,
                check=False,
            )
            if hedef.is_file() and hedef.stat().st_size > 500:
                return hedef
            _LOG.warning("PDF exit=%s", proc.returncode)
        except Exception as exc:
            _LOG.warning("PDF: %s", exc)
    yedek = hedef.with_suffix(".html")
    yedek.write_text(html_metin, encoding="utf-8")
    raise RuntimeError(f"PDF oluşturulamadı; HTML kaydedildi: {yedek}")


def _safe_file_piece(metin: str, maxlen: int = 40) -> str:
    t = (metin or "").translate(_TR_TRANSLIT)
    t = re.sub(r'[<>:"/\\|?*]+', "", t)
    t = re.sub(r"\s+", "_", t.strip())
    t = re.sub(r"[^\w\-]+", "_", t)
    t = re.sub(r"_+", "_", t).strip("._")
    return (t or "X")[:maxlen]


def _teklif_tarih_ddmmYYYY(vm: CustomerQuoteViewModel) -> str:
    ham = (vm.teklif_tarihi or "").strip()
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(ham, fmt).strftime("%d-%m-%Y")
        except ValueError:
            continue
    return date.today().strftime("%d-%m-%Y")


def safe_customer_export_name(vm: CustomerQuoteViewModel, uzanti: str = "pdf") -> str:
    """Teklif_No_Musteri_DD-MM-YYYY.ext — Türkçe karakterler ASCII'ye çevrilir."""
    no = _safe_file_piece(vm.teklif_no or "Teklif", 32)
    musteri = _safe_file_piece((vm.musteri or {}).get("unvan") or "Musteri", 40)
    tarih = _teklif_tarih_ddmmYYYY(vm)
    ext = (uzanti or "pdf").lstrip(".").lower() or "pdf"
    return f"Teklif_{no}_{musteri}_{tarih}.{ext}"


def safe_customer_pdf_name(vm: CustomerQuoteViewModel) -> str:
    return safe_customer_export_name(vm, "pdf")


def teklif_cikti_klasoru() -> Path:
    """Kalıcı teklif çıktı klasörü (Documents/CinMuhasebe/Teklifler)."""
    klasor = Path.home() / "Documents" / "CinMuhasebe" / "Teklifler"
    klasor.mkdir(parents=True, exist_ok=True)
    return klasor


def kaydet_teklif_cikti_yolu(vm: CustomerQuoteViewModel, uzanti: str = "pdf") -> Path:
    """Çıktı klasöründe güvenli dosya yolu (henüz yazılmaz)."""
    return teklif_cikti_klasoru() / safe_customer_export_name(vm, uzanti)


def teklif_cikti_yollari(vm: CustomerQuoteViewModel) -> dict[str, Path]:
    return {
        "pdf": kaydet_teklif_cikti_yolu(vm, "pdf"),
        "docx": kaydet_teklif_cikti_yolu(vm, "docx"),
        "html": kaydet_teklif_cikti_yolu(vm, "html"),
    }


def _klasor_ac(yol: Path) -> None:
    try:
        klasor = Path(yol).resolve()
        if klasor.is_file():
            klasor = klasor.parent
        if os.name == "nt":
            os.startfile(str(klasor))  # type: ignore[attr-defined]
        else:
            webbrowser.open(klasor.as_uri())
    except Exception as exc:
        _LOG.warning("Klasör açılamadı: %s", exc)


def musteri_teklif_html_uret(
    dialog, *, preview: bool = False, zoom_pct: int = 100
) -> tuple[CustomerQuoteViewModel, str]:
    vm = build_customer_quote_from_dialog(dialog)
    html_metin = render_customer_quote_html(vm, preview=preview, zoom_pct=zoom_pct)
    return vm, html_metin


def musteri_teklif_pdf_uret(dialog, hedef: Path | None = None) -> Path:
    vm, html_metin = musteri_teklif_html_uret(dialog, preview=False)
    if hedef is None:
        hedef = kaydet_teklif_cikti_yolu(vm, "pdf")
    else:
        hedef = Path(hedef)
        if not hedef.is_absolute():
            hedef = teklif_cikti_klasoru() / hedef.name
    hedef.parent.mkdir(parents=True, exist_ok=True)
    return html_to_pdf(html_metin, hedef)


class MusteriTeklifOnizlemeDialog(tk.Toplevel):
    """Müşteri teklif A4 yazdırma ön izlemesi — maliyet sütunu yok."""

    # A4 oranı ~ 210:297 ≈ 0.707; ekranda ~794×1123 @96dpi, önizlemede küçültülür
    _A4_W = 560
    _A4_H = 792

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.dialog = dialog
        self.zoom = 100
        self.title("Teklif Yazdırma Ön İzlemesi — A4")
        self.geometry("920x780")
        self.minsize(720, 560)
        self.transient(parent)
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.configure(bg="#6B7280")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-p>", lambda _e: self._yazdir())
        self.bind("<Control-P>", lambda _e: self._yazdir())
        self.vm, self.html = musteri_teklif_html_uret(dialog, preview=True, zoom_pct=100)
        self._html_path: Path | None = None
        self._toolbar_kur()
        self._govde_kur()
        self._yenile_a4()
        # Tarayıcıda gerçek A4 örneğini hemen aç
        self.after(200, self._tarayici_sessiz)

    def _toolbar_kur(self):
        bar = tk.Frame(self, bg="#0b1f3a", pady=6, padx=8)
        bar.pack(fill="x")
        tk.Label(
            bar,
            text="Teklif Yazdırma Ön İzlemesi · A4",
            bg="#0b1f3a",
            fg="#e8b923",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left", padx=8)

        def btn(t, cmd, bg="#e8b923", fg="#0b1f3a"):
            b = tk.Button(
                bar,
                text=t,
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

        btn("A4 Ön İzleme", self._tarayici)
        btn("Yazdır", self._yazdir)
        btn("PDF Kaydet", self._pdf_kaydet)
        btn("Word Oluştur", self._word)
        btn("WhatsApp PDF", self._whatsapp)
        btn("E-posta PDF", self._email)
        btn("Kapat", self.destroy, "#9CA3AF", "#111")

    def _govde_kur(self):
        dis = tk.Frame(self, bg="#6B7280")
        dis.pack(fill="both", expand=True, padx=10, pady=10)
        canvas = tk.Canvas(dis, bg="#6B7280", highlightthickness=0)
        sy = ttk.Scrollbar(dis, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sy.set)
        sy.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._canvas = canvas
        self._a4 = tk.Frame(
            canvas,
            bg="#FFFFFF",
            width=self._A4_W,
            height=self._A4_H,
            highlightthickness=1,
            highlightbackground="#94A3B8",
        )
        self._win = canvas.create_window((0, 0), window=self._a4, anchor="n")
        canvas.bind("<Configure>", self._canvas_ortala)
        self._a4.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )

        # A4 üst şerit
        ust = tk.Frame(self._a4, bg="#0B2A4A", height=36)
        ust.pack(fill="x")
        ust.pack_propagate(False)
        tk.Label(
            ust,
            text="FİYAT TEKLİFİ — A4 YAZDIRMA ÖRNEĞİ",
            bg="#0B2A4A",
            fg="#E8B923",
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left", padx=12, pady=6)
        tk.Label(
            ust,
            text="210 × 297 mm",
            bg="#0B2A4A",
            fg="#94A3B8",
            font=("Segoe UI", 8),
        ).pack(side="right", padx=12)

        ic = tk.Frame(self._a4, bg="#FFFFFF", padx=18, pady=12)
        ic.pack(fill="both", expand=True)
        self._lbl_baslik = tk.Label(
            ic, text="", bg="#FFFFFF", fg="#0B2A4A",
            font=("Segoe UI", 14, "bold"), anchor="w",
        )
        self._lbl_baslik.pack(fill="x", pady=(0, 6))
        self._lbl_ozet = tk.Label(
            ic,
            text="",
            bg="#FFFFFF",
            fg="#1E293B",
            justify="left",
            anchor="nw",
            font=("Segoe UI", 9),
            wraplength=self._A4_W - 48,
        )
        self._lbl_ozet.pack(fill="both", expand=True, anchor="nw")
        tk.Label(
            ic,
            text="Tam A4 görünümü tarayıcıda açılır · Alış / maliyet / ayrı masraf satırı yoktur",
            bg="#F1F5F9",
            fg="#64748B",
            font=("Segoe UI", 8),
            pady=6,
        ).pack(fill="x", pady=(8, 0))

    def _canvas_ortala(self, event):
        x = max(0, (event.width - self._A4_W) // 2)
        self._canvas.itemconfigure(self._win, width=self._A4_W)
        self._canvas.coords(self._win, x, 8)

    def _yenile_a4(self):
        m = self.vm.musteri or {}
        f = self.vm.firma or {}
        pb = self.vm.para_birimi_etiket or self.vm.para_birimi
        satirlar = []
        for s in (self.vm.satirlar or [])[:12]:
            satirlar.append(
                f"  {s.sira:>2}. {s.urun_kodu or '—'}  {s.urun_adi}  ·  "
                f"{s.miktar_goster} {s.birim}  ·  {s.birim_fiyat_goster} {pb}  ·  "
                f"{s.kdv_hariç_goster} {pb}"
            )
        if len(self.vm.satirlar or []) > 12:
            satirlar.append(f"  … +{len(self.vm.satirlar) - 12} kalem daha")
        if not satirlar:
            satirlar.append("  (ürün kalemi yok)")
        sart_ozet = []
        for madde in (self.vm.sart_maddeleri or [])[:4]:
            sart_ozet.append(f"  • {madde}")
        metin = (
            f"Firma: {f.get('unvan') or ''}\n"
            f"Teklif No: {self.vm.teklif_no}    Tarih: {self.vm.teklif_tarihi}    "
            f"Geçerlilik: {self.vm.gecerlilik_tarihi or self.vm.gecerlilik_suresi}\n"
            f"Müşteri: {m.get('unvan') or '—'}\n"
            f"Ödeme: {self.vm.odeme_sekli or '—'}    "
            f"Teslim: {self.vm.termin_suresi or self.vm.teslimat_sekli or '—'}\n"
            f"{'─' * 64}\n"
            f"1 · GENEL BİLGİLER  ·  2 · STOK / ÜRÜN KALEMLERİ  ·  3 · ÖZEL ŞARTLAR\n"
            f"{'─' * 64}\n"
            f"Stok / ürün kalemleri:\n"
            + "\n".join(satirlar)
            + f"\n{'─' * 64}\n"
            f"Ara Toplam: {self.vm.ara_goster} {pb}\n"
            f"KDV: {self.vm.kdv_goster} {pb}\n"
            f"GENEL TOPLAM: {self.vm.genel_goster} {pb}\n"
            f"{'─' * 64}\n"
            f"Özel şartlar (özet):\n"
            + ("\n".join(sart_ozet) if sart_ozet else "  —")
        )
        self._lbl_baslik.configure(
            text=f"{self.vm.belge_baslik or 'FİYAT TEKLİFİ'}  ·  {self.vm.teklif_no}"
        )
        self._lbl_ozet.configure(text=metin)

    def _html_yaz(self, *, preview: bool = True) -> Path:
        klasor = teklif_cikti_klasoru()
        yol = klasor / f"musteri_onizleme_{datetime.now():%H%M%S}.html"
        if preview:
            _, html = musteri_teklif_html_uret(
                self.dialog, preview=True, zoom_pct=self.zoom
            )
        else:
            html = self.html
        yol.write_text(html, encoding="utf-8")
        self._html_path = yol
        self.html = html
        return yol

    def _tarayici_sessiz(self):
        try:
            webbrowser.open(self._html_yaz(preview=True).resolve().as_uri())
        except Exception as exc:
            _LOG.warning("A4 ön izleme tarayıcıda açılamadı: %s", exc)

    def _tarayici(self):
        webbrowser.open(self._html_yaz(preview=True).resolve().as_uri())

    def _word(self):
        try:
            from teklif_docx import musteri_teklif_docx_uret

            hedef = kaydet_teklif_cikti_yolu(self.vm, "docx")
            yol = musteri_teklif_docx_uret(self.dialog, hedef)
            messagebox.showinfo("Word", f"Word belgesi oluşturuldu:\n{yol}", parent=self)
            _klasor_ac(yol)
        except CustomerQuoteSecurityError as exc:
            messagebox.showerror("Güvenlik", str(exc), parent=self)
        except Exception as exc:
            messagebox.showerror("Word", str(exc), parent=self)

    def _pdf_kaydet(self):
        yol = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".pdf",
            initialdir=str(teklif_cikti_klasoru()),
            initialfile=safe_customer_pdf_name(self.vm),
            filetypes=[("PDF", "*.pdf")],
        )
        if not yol:
            return
        try:
            _, temiz = musteri_teklif_html_uret(self.dialog, preview=False)
            html_to_pdf(temiz, Path(yol))
            messagebox.showinfo("PDF", f"Kaydedildi:\n{yol}", parent=self)
        except Exception as exc:
            messagebox.showerror("PDF", str(exc), parent=self)

    def _yazdir(self):
        """A4 ön izlemeyi tarayıcıda açar ve yazdırma diyaloğunu tetikler."""
        yol = self._html_yaz(preview=True)
        webbrowser.open(yol.resolve().as_uri())
        messagebox.showinfo(
            "Yazdır — A4",
            "Teklif A4 ön izlemesi tarayıcıda açıldı.\n\n"
            "Yazdırma için tarayıcıdaki «Yazdır» düğmesine basın veya Ctrl+P kullanın.\n"
            "Kağıt boyutu: A4 Dikey.",
            parent=self,
        )

    def _whatsapp(self):
        try:
            pdf = musteri_teklif_pdf_uret(self.dialog, kaydet_teklif_cikti_yolu(self.vm, "pdf"))
            messagebox.showinfo(
                "WhatsApp PDF",
                f"PDF hazırlandı:\n{pdf}\n\n"
                "Klasör açılacak; dosyayı WhatsApp'a ekleyebilirsiniz.",
                parent=self,
            )
            _klasor_ac(pdf)
        except CustomerQuoteSecurityError as exc:
            messagebox.showerror("Güvenlik", str(exc), parent=self)
        except Exception as exc:
            messagebox.showerror("WhatsApp", str(exc), parent=self)

    def _email(self):
        try:
            pdf = musteri_teklif_pdf_uret(self.dialog)
            messagebox.showinfo(
                "E-posta",
                f"Güvenli müşteri PDF hazırlandı:\n{pdf}\n\n"
                "E-posta istemcinize ek olarak ekleyebilirsiniz.",
                parent=self,
            )
            _klasor_ac(pdf)
        except CustomerQuoteSecurityError as exc:
            messagebox.showerror("Güvenlik", str(exc), parent=self)
        except Exception as exc:
            messagebox.showerror("E-posta", str(exc), parent=self)


class IcMaliyetAnaliziDialog(tk.Toplevel):
    """İç maliyet analizi — şirket içidir."""

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.dialog = dialog
        self.title("İç Maliyet Analizi — Şirket İçi")
        self.geometry("1100x720")
        self.transient(parent)
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.vm = build_internal_cost_from_dialog(dialog)
        self.html = render_internal_cost_html(self.vm)
        bar = tk.Frame(self, bg="#C62828", pady=8, padx=8)
        bar.pack(fill="x")
        tk.Label(
            bar,
            text=self.vm.uyari_bant,
            bg="#C62828",
            fg="#fff",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")
        tk.Button(
            bar, text="Tarayıcıda Aç", command=self._tarayici, bg="#F5C518", relief="flat",
            padx=8, pady=3, font=("Segoe UI", 9, "bold"),
        ).pack(side="right", padx=4)
        tk.Button(
            bar, text="PDF Kaydet", command=self._pdf, bg="#fff", relief="flat",
            padx=8, pady=3, font=("Segoe UI", 9, "bold"),
        ).pack(side="right", padx=4)
        tk.Button(
            bar, text="Kapat", command=self.destroy, bg="#9CA3AF", relief="flat", padx=8, pady=3,
        ).pack(side="right", padx=4)
        txt = tk.Text(self, wrap="none", font=("Consolas", 9))
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        ozet = (
            f"{self.vm.uyari_bant}\n\n"
            f"Teklif: {self.vm.teklif_no}  |  {self.vm.musteri_unvan}\n"
            f"Toplam Alış: {_para(self.vm.total_purchase_cost)}\n"
            f"Müşteri Masrafı: {_para(self.vm.customer_expense_amount)}  |  "
            f"İç Masraf: {_para(self.vm.internal_expense_amount)}\n"
            f"% Kâr: {_para(self.vm.profit_rate)} → {_para(self.vm.percentage_profit_amount)}\n"
            f"Maktu Kâr: {_para(self.vm.fixed_profit_amount)}\n"
            f"Teklif Ara: {_para(self.vm.calculated_offer_subtotal)}\n"
            f"Gerçek Kâr: {_para(self.vm.actual_profit_amount)}  |  "
            f"Marj: {_para(self.vm.sales_margin_rate)}%\n"
            f"{self.vm.zarar_uyarisi}\n\n"
            "Detaylı tablo için «Tarayıcıda Aç»."
        )
        txt.insert("1.0", ozet)
        txt.configure(state="disabled")

    def _tarayici(self):
        klasor = Path(tempfile.gettempdir()) / "muhasebe_teklif_a4"
        klasor.mkdir(parents=True, exist_ok=True)
        yol = klasor / f"ic_maliyet_{datetime.now():%H%M%S}.html"
        yol.write_text(self.html, encoding="utf-8")
        webbrowser.open(yol.resolve().as_uri())

    def _pdf(self):
        from database.access import maliyet_izinli

        if not maliyet_izinli():
            messagebox.showwarning("Yetki", "İç maliyet PDF yetkiniz yok.", parent=self)
            return
        yol = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".pdf",
            initialfile=f"Ic_Maliyet_{self.vm.teklif_no}_{date.today().isoformat()}.pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not yol:
            return
        try:
            html_to_pdf(self.html, Path(yol))
            messagebox.showinfo("PDF", f"İç maliyet PDF kaydedildi:\n{yol}", parent=self)
        except Exception as exc:
            messagebox.showerror("PDF", str(exc), parent=self)


def musteriye_gondermeden_once_kontrol(dialog) -> None:
    """Gönderim öncesi güvenlik — model + HTML tarama."""
    vm, html_metin = musteri_teklif_html_uret(dialog)
    assert_customer_model_safe(vm)
    assert_customer_output_safe(html_metin)
