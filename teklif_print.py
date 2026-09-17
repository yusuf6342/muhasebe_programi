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


def musteri_teklif_html_uret(dialog) -> tuple[CustomerQuoteViewModel, str]:
    vm = build_customer_quote_from_dialog(dialog)
    html_metin = render_customer_quote_html(vm)
    return vm, html_metin


def musteri_teklif_pdf_uret(dialog, hedef: Path | None = None) -> Path:
    vm, html_metin = musteri_teklif_html_uret(dialog)
    if hedef is None:
        hedef = kaydet_teklif_cikti_yolu(vm, "pdf")
    else:
        hedef = Path(hedef)
        if not hedef.is_absolute():
            hedef = teklif_cikti_klasoru() / hedef.name
    hedef.parent.mkdir(parents=True, exist_ok=True)
    return html_to_pdf(html_metin, hedef)


class MusteriTeklifOnizlemeDialog(tk.Toplevel):
    """Müşteri Teklif Ön İzlemesi — maliyet sütunu yok."""

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.dialog = dialog
        self.title("Müşteri Teklif Ön İzlemesi")
        self.geometry("1040x720")
        self.transient(parent)
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.configure(bg="#6B7280")
        self.vm, self.html = musteri_teklif_html_uret(dialog)
        bar = tk.Frame(self, bg="#0b1f3a", pady=6, padx=8)
        bar.pack(fill="x")
        tk.Label(
            bar,
            text="Müşteri Teklif Ön İzlemesi",
            bg="#0b1f3a",
            fg="#e8b923",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left", padx=8)

        def btn(t, cmd, bg="#e8b923", fg="#0b1f3a"):
            b = tk.Button(
                bar, text=t, command=cmd, bg=bg, fg=fg, relief="flat", padx=8, pady=3,
                font=("Segoe UI", 9, "bold"), cursor="hand2",
            )
            b.pack(side="left", padx=2)
            return b

        btn("Tarayıcıda Aç", self._tarayici)
        btn("Word Oluştur", self._word)
        btn("PDF Kaydet", self._pdf_kaydet)
        btn("Yazdır", self._yazdir)
        btn("WhatsApp PDF", self._whatsapp)
        btn("E-posta PDF", self._email)
        btn("Kapat", self.destroy, "#9CA3AF", "#111")
        cerceve = tk.Frame(self, bg="#9CA3AF")
        cerceve.pack(fill="both", expand=True, padx=8, pady=8)
        self.txt = tk.Text(cerceve, wrap="word", font=("Consolas", 9))
        self.txt.pack(fill="both", expand=True)
        ozet = (
            f"{self.vm.belge_baslik}  {self.vm.teklif_no}\n"
            f"Müşteri: {(self.vm.musteri or {}).get('unvan')}\n"
            f"Genel Toplam: {self.vm.genel_goster} {self.vm.para_birimi_etiket or self.vm.para_birimi}\n"
            f"Satır sayısı: {len(self.vm.satirlar)}\n\n"
            "Tam A4 görünümü için «Tarayıcıda Aç», «Word Oluştur» veya «PDF Kaydet» kullanın.\n"
            "Bu ön izleme maliyet, kâr ve alış bilgisi içermez."
        )
        self.txt.insert("1.0", ozet)
        self.txt.configure(state="disabled")
        self._html_path: Path | None = None

    def _html_yaz(self) -> Path:
        klasor = teklif_cikti_klasoru()
        yol = klasor / f"musteri_onizleme_{datetime.now():%H%M%S}.html"
        yol.write_text(self.html, encoding="utf-8")
        self._html_path = yol
        return yol

    def _tarayici(self):
        webbrowser.open(self._html_yaz().resolve().as_uri())

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
            html_to_pdf(self.html, Path(yol))
            messagebox.showinfo("PDF", f"Kaydedildi:\n{yol}", parent=self)
        except Exception as exc:
            messagebox.showerror("PDF", str(exc), parent=self)

    def _yazdir(self):
        webbrowser.open(self._html_yaz().resolve().as_uri())
        messagebox.showinfo(
            "Yazdır",
            "Teklif tarayıcıda açıldı. Yazdırma için Ctrl+P kullanın.",
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
