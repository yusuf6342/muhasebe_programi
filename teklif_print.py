"""Teklif çıktı şablonları — müşteri ve iç maliyet tamamen ayrı.

Şablonlar:
  A) customer_quote_template
  B) internal_quote_cost_analysis_template
"""

from __future__ import annotations

import html
import logging
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

_LOG = logging.getLogger("teklif_print")


def _e(v) -> str:
    return html.escape("" if v is None else str(v))


def render_customer_quote_html(vm: CustomerQuoteViewModel) -> str:
    """customer_quote_template — maliyet/kâr yok."""
    assert_customer_model_safe(vm)
    logo = ""
    if vm.logo_data_uri:
        logo = f'<img class="logo" src="{vm.logo_data_uri}" alt="Logo"/>'
    f = vm.firma or {}
    m = vm.musteri or {}
    adres_f = " ".join(
        x for x in (f.get("adres"), f.get("ilce"), f.get("il")) if x
    )
    adres_m = m.get("adres") or ""

    satir_html = []
    for s in vm.satirlar:
        satir_html.append(
            "<tr>"
            f"<td class='c'>{s.sira}</td>"
            f"<td>{_e(s.urun_kodu)}</td>"
            f"<td>{_e(s.urun_adi)}"
            f"{('<div class=\"muted\">' + _e(s.aciklama) + '</div>') if s.aciklama else ''}</td>"
            f"<td class='r'>{_e(s.miktar_goster)}</td>"
            f"<td class='c'>{_e(s.birim)}</td>"
            f"<td class='r'>{_e(s.birim_fiyat_goster)}</td>"
            f"<td class='c'>{_e(s.iskonto_goster)}</td>"
            f"<td class='r'>{_e(s.net_goster)}</td>"
            f"<td class='c'>{_e(s.kdv_oran_goster)}</td>"
            f"<td class='r'>{_e(s.kdv_hariç_goster)}</td>"
            f"<td class='r'>{_e(s.kdv_goster)}</td>"
            f"<td class='r'>{_e(s.kdv_dahil_goster)}</td>"
            "</tr>"
        )

    banka = ""
    if vm.banka_satirlari:
        banka = "<div class='bolum'><strong>Banka Bilgileri</strong><ul>" + "".join(
            f"<li>{_e(b.get('banka',''))} — {_e(b.get('iban',''))}</li>"
            for b in vm.banka_satirlari
        ) + "</ul></div>"

    sartlar = []
    if vm.odeme_sekli:
        sartlar.append(f"<li>Ödeme Şekli: {_e(vm.odeme_sekli)}</li>")
    if vm.termin_suresi:
        sartlar.append(f"<li>Termin Süresi: {_e(vm.termin_suresi)}</li>")
    if vm.tahmini_teslim_tarihi:
        sartlar.append(f"<li>Tahmini Teslim Tarihi: {_e(vm.tahmini_teslim_tarihi)}</li>")
    if vm.teslimat_sekli:
        sartlar.append(f"<li>Teslimat Şekli: {_e(vm.teslimat_sekli)}</li>")
    if vm.gecerlilik_suresi:
        sartlar.append(f"<li>Teklif Geçerlilik Süresi: {_e(vm.gecerlilik_suresi)}</li>")
    if vm.musteri_notu:
        sartlar.append(f"<li>Teklif Notları: {_e(vm.musteri_notu)}</li>")
    if vm.ticari_sartlar:
        sartlar.append(f"<li>Ticari Şartlar: {_e(vm.ticari_sartlar)}</li>")
    sartlar_html = (
        "<div class='bolum'><strong>Ticari Şartlar</strong><ul>"
        + "".join(sartlar)
        + "</ul></div>"
        if sartlar
        else ""
    )

    html_out = f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"/>
<title>{_e(vm.belge_baslik)} {_e(vm.teklif_no)}</title>
<style>
@page {{ size: A4 portrait; margin: 12mm; }}
body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size: 10pt; color: #1a1a1a; margin: 0; }}
.wrap {{ padding: 8px 12px; }}
.ust {{ display: flex; justify-content: space-between; gap: 16px; border-bottom: 2px solid #1B2A4A; padding-bottom: 8px; }}
.logo {{ max-height: 64px; max-width: 180px; }}
h1 {{ margin: 0 0 4px; font-size: 16pt; color: #1B2A4A; }}
.meta td {{ padding: 1px 8px 1px 0; vertical-align: top; }}
.grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 10px 0; }}
.kutu {{ border: 1px solid #d1d5db; padding: 8px; border-radius: 4px; }}
.kutu h3 {{ margin: 0 0 6px; font-size: 10pt; color: #1B2A4A; }}
table.satir {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
table.satir th {{ background: #1B2A4A; color: #fff; font-size: 8pt; padding: 5px 4px; text-align: left; }}
table.satir td {{ border-bottom: 1px solid #e5e7eb; padding: 4px; font-size: 8.5pt; }}
.r {{ text-align: right; }} .c {{ text-align: center; }}
.muted {{ color: #6b7280; font-size: 8pt; }}
.toplam {{ margin-top: 10px; width: 280px; margin-left: auto; }}
.toplam td {{ padding: 3px 6px; }}
.toplam tr.genel td {{ font-weight: bold; font-size: 11pt; border-top: 2px solid #1B2A4A; }}
.bolum {{ margin-top: 12px; font-size: 9pt; }}
.imza {{ display: flex; justify-content: space-between; margin-top: 28px; }}
.imza .alan {{ width: 40%; text-align: center; border-top: 1px solid #9ca3af; padding-top: 6px; }}
</style></head><body><div class="wrap">
<div class="ust">
  <div>{logo}
    <div><strong>{_e(f.get('unvan'))}</strong></div>
    <div class="muted">{_e(adres_f)}</div>
    <div class="muted">Tel: {_e(f.get('telefon'))} · {_e(f.get('email'))} · {_e(f.get('web'))}</div>
    <div class="muted">VD: {_e(f.get('vergi_dairesi'))} · VN: {_e(f.get('vergi_no'))}</div>
  </div>
  <div>
    <h1>{_e(vm.belge_baslik)}</h1>
    <table class="meta">
      <tr><td>Teklif No</td><td><strong>{_e(vm.teklif_no)}</strong></td></tr>
      <tr><td>Tarih</td><td>{_e(vm.teklif_tarihi)}</td></tr>
      <tr><td>Geçerlilik</td><td>{_e(vm.gecerlilik_tarihi)}</td></tr>
      <tr><td>Referans</td><td>{_e(vm.referans_no) or '—'}</td></tr>
      <tr><td>Konu</td><td>{_e(vm.konu) or '—'}</td></tr>
      <tr><td>Proje</td><td>{_e(vm.proje) or '—'}</td></tr>
      <tr><td>Hazırlayan</td><td>{_e(vm.hazirlayan)}</td></tr>
      <tr><td>Satış Temsilcisi</td><td>{_e(vm.satis_temsilcisi) or '—'}</td></tr>
    </table>
  </div>
</div>
<div class="grid2">
  <div class="kutu"><h3>Müşteri</h3>
    <div><strong>{_e(m.get('unvan'))}</strong></div>
    <div>{_e(m.get('yetkili'))}</div>
    <div class="muted">{_e(adres_m)}</div>
    <div class="muted">Tel: {_e(m.get('telefon'))} · {_e(m.get('email'))}</div>
    <div class="muted">VD: {_e(m.get('vergi_dairesi'))} · VN: {_e(m.get('vergi_no'))}</div>
  </div>
  <div class="kutu"><h3>Özet</h3>
    <div>Para Birimi: <strong>{_e(vm.para_birimi)}</strong></div>
    <div>Genel Toplam: <strong>{_e(vm.genel_goster)} {_e(vm.para_birimi)}</strong></div>
  </div>
</div>
<table class="satir">
<thead><tr>
  <th>#</th><th>Kod</th><th>Ürün / Açıklama</th><th>Miktar</th><th>Birim</th>
  <th>Birim Fiyat</th><th>İsk.</th><th>Net Fiyat</th><th>KDV %</th>
  <th>KDV Hariç</th><th>KDV</th><th>KDV Dahil</th>
</tr></thead>
<tbody>
{''.join(satir_html)}
</tbody></table>
<table class="toplam">
  <tr><td>Ara Toplam</td><td class="r">{_e(vm.ara_goster)}</td></tr>
  <tr><td>İskonto Toplamı</td><td class="r">{_e(vm.iskonto_goster)}</td></tr>
  <tr><td>KDV Hariç Toplam</td><td class="r">{_e(vm.kdv_haric_goster)}</td></tr>
  <tr><td>KDV Toplamı</td><td class="r">{_e(vm.kdv_goster)}</td></tr>
  <tr class="genel"><td>KDV Dahil Genel Toplam</td><td class="r">{_e(vm.genel_goster)} {_e(vm.para_birimi)}</td></tr>
</table>
{sartlar_html}
{banka}
<div class="imza">
  <div class="alan">Hazırlayan / İmza<br/>{_e(vm.hazirlayan)}</div>
  <div class="alan">Müşteri Onay / Kaşe</div>
</div>
<div class="muted" style="margin-top:16px">{_e(vm.alt_bilgi)}</div>
</div></body></html>"""
    assert_customer_output_safe(html_out)
    return html_out


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
    hedef = Path(hedef)
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


def safe_customer_pdf_name(vm: CustomerQuoteViewModel) -> str:
    musteri = re.sub(r'[<>:"/\\|?*]+', "", (vm.musteri or {}).get("unvan") or "Musteri")[:40]
    musteri = musteri.replace(" ", "_") or "Musteri"
    no = re.sub(r"[^\w\-]+", "_", vm.teklif_no or "Teklif")
    return f"Teklif_{no}_{musteri}_{date.today().isoformat()}.pdf"


def musteri_teklif_html_uret(dialog) -> tuple[CustomerQuoteViewModel, str]:
    vm = build_customer_quote_from_dialog(dialog)
    html_metin = render_customer_quote_html(vm)
    return vm, html_metin


def musteri_teklif_pdf_uret(dialog, hedef: Path | None = None) -> Path:
    vm, html_metin = musteri_teklif_html_uret(dialog)
    if hedef is None:
        hedef = Path(tempfile.gettempdir()) / "muhasebe_teklif_a4" / safe_customer_pdf_name(vm)
    return html_to_pdf(html_metin, Path(hedef))


class MusteriTeklifOnizlemeDialog(tk.Toplevel):
    """Müşteri Teklif Ön İzlemesi — maliyet sütunu yok."""

    def __init__(self, parent, dialog):
        super().__init__(parent)
        self.dialog = dialog
        self.title("Müşteri Teklif Ön İzlemesi")
        self.geometry("960x700")
        self.transient(parent)
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.configure(bg="#6B7280")
        self.vm, self.html = musteri_teklif_html_uret(dialog)
        bar = tk.Frame(self, bg="#111827", pady=6, padx=8)
        bar.pack(fill="x")
        tk.Label(
            bar,
            text="Müşteri Teklif Ön İzlemesi",
            bg="#111827",
            fg="#F5C518",
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left", padx=8)

        def btn(t, cmd, bg="#F5C518", fg="#111"):
            b = tk.Button(
                bar, text=t, command=cmd, bg=bg, fg=fg, relief="flat", padx=8, pady=3,
                font=("Segoe UI", 9, "bold"), cursor="hand2",
            )
            b.pack(side="left", padx=2)
            return b

        btn("Tarayıcıda Aç", self._tarayici)
        btn("Yazdır / PDF", self._pdf)
        btn("PDF Kaydet", self._pdf_kaydet)
        btn("E-posta PDF", self._email)
        btn("Kapat", self.destroy, "#9CA3AF")
        cerceve = tk.Frame(self, bg="#9CA3AF")
        cerceve.pack(fill="both", expand=True, padx=8, pady=8)
        self.txt = tk.Text(cerceve, wrap="word", font=("Consolas", 9))
        self.txt.pack(fill="both", expand=True)
        # HTML özet — tarayıcı asıl görünüm
        ozet = (
            f"{self.vm.belge_baslik}  {self.vm.teklif_no}\n"
            f"Müşteri: {(self.vm.musteri or {}).get('unvan')}\n"
            f"Genel Toplam: {self.vm.genel_goster} {self.vm.para_birimi}\n"
            f"Satır sayısı: {len(self.vm.satirlar)}\n\n"
            "Tam A4 görünümü için «Tarayıcıda Aç» veya «PDF Kaydet» kullanın.\n"
            "Bu ön izleme maliyet, kâr ve alış bilgisi içermez."
        )
        self.txt.insert("1.0", ozet)
        self.txt.configure(state="disabled")
        self._html_path: Path | None = None

    def _html_yaz(self) -> Path:
        klasor = Path(tempfile.gettempdir()) / "muhasebe_teklif_a4"
        klasor.mkdir(parents=True, exist_ok=True)
        yol = klasor / f"musteri_onizleme_{datetime.now():%H%M%S}.html"
        yol.write_text(self.html, encoding="utf-8")
        self._html_path = yol
        return yol

    def _tarayici(self):
        webbrowser.open(self._html_yaz().resolve().as_uri())

    def _pdf_kaydet(self):
        yol = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=".pdf",
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

    def _pdf(self):
        self._pdf_kaydet()

    def _email(self):
        try:
            pdf = musteri_teklif_pdf_uret(self.dialog)
            messagebox.showinfo(
                "E-posta",
                f"Güvenli müşteri PDF hazırlandı:\n{pdf}\n\n"
                "E-posta istemcinize ek olarak ekleyebilirsiniz.",
                parent=self,
            )
            webbrowser.open(pdf.resolve().as_uri())
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
