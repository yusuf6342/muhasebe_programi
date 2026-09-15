"""Hızlı Satış — fiş / A4 önizleme, PDF kaydet, satış sonrası diyalog (Aşama 8).

Yazıcı hatası satışı geri almaz. Thermal SDK ve WhatsApp gönderimi ertelendi;
PDF dosya kaydı yeterli (kullanıcı WhatsApp'a kendisi ekleyebilir).
"""

from __future__ import annotations

import html
import tempfile
import tkinter as tk
import webbrowser
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from database.hizli_satis_service import HizliSatisService
from database.session_manager import oturum
from hizli_satis_log import islem_yaz

SARİ = "#F5C518"
KOYU_GRI = "#2B2F33"
ACIK_GRI = "#F3F4F6"
YESIL = "#2E7D32"
BEYAZ = "#FFFFFF"


def _para(tutar) -> str:
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _miktar(m) -> str:
    metin = f"{Decimal(str(m or 0)):f}".rstrip("0").rstrip(".")
    return metin or "0"


def _tarih(t) -> str:
    if t is None:
        return ""
    if isinstance(t, datetime):
        return t.strftime("%d.%m.%Y %H:%M")
    if isinstance(t, date):
        return t.strftime("%d.%m.%Y")
    return str(t)


def _firma_adi() -> str:
    return (getattr(oturum, "firma_unvan", None) or "").strip() or "Cin Muhasebe"


def _basit_pdf_olustur(baslik: str, satirlar: list[str], yol: Path) -> Path:
    """Bağımlılıksız metin PDF (çek/senet & muhasebe ile aynı yaklaşım)."""
    yol.parent.mkdir(parents=True, exist_ok=True)
    icerik = [baslik, ""] + list(satirlar)

    def esc(t: str) -> str:
        return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    y = 800
    content = ["BT", "/F1 9 Tf", "40 800 Td"]
    first = True
    for line in icerik:
        safe = esc(line[:110])
        if first:
            content.append(f"({safe}) Tj")
            first = False
        else:
            content.append("0 -12 Td")
            content.append(f"({safe}) Tj")
            y -= 12
            if y < 40:
                break
    content.append("ET")
    stream = "\n".join(content).encode("latin-1", errors="replace")

    objs = [
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n",
        (
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
        ),
        (
            f"4 0 obj<< /Length {len(stream)} >>stream\n".encode()
            + stream
            + b"\nendstream\nendobj\n"
        ),
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objs:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode())
    out.extend(
        f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    yol.write_bytes(out)
    return yol


def fis_html(veri: dict[str, Any]) -> str:
    """Dar fiş (tarayıcı yazdırma / önizleme)."""
    firma = html.escape(str(veri.get("firma") or _firma_adi()))
    satir_html = ""
    for s in veri.get("satirlar") or []:
        satir_html += (
            f"<tr><td>{html.escape(str(s.get('urun_adi') or s.get('urun_kodu') or ''))}</td>"
            f"<td class='r'>{html.escape(_miktar(s.get('miktar')))}</td>"
            f"<td class='r'>{html.escape(_para(s.get('satir_toplam')))}</td></tr>"
        )
    odeme_html = "".join(
        f"<tr><td>{html.escape(str(o.get('odeme_sekli') or ''))}</td>"
        f"<td class='r'>{html.escape(_para(o.get('tutar')))}</td></tr>"
        for o in (veri.get("tahsilatlar") or [])
    )
    if not odeme_html and float(veri.get("kalan") or 0) > 0:
        odeme_html = (
            f"<tr><td>Açık hesap</td><td class='r'>"
            f"{html.escape(_para(veri.get('kalan')))}</td></tr>"
        )
    return f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"/>
<title>Fiş {html.escape(str(veri.get('fatura_no') or ''))}</title>
<style>
  body {{ font-family: 'Consolas','Courier New',monospace; width: 280px; margin: 12px auto;
         color: #111; font-size: 12px; }}
  h1 {{ font-size: 14px; text-align: center; margin: 0 0 8px; }}
  .meta {{ text-align: center; margin-bottom: 10px; font-size: 11px; }}
  table {{ width: 100%; border-collapse: collapse; }}
  td {{ padding: 2px 0; vertical-align: top; }}
  .r {{ text-align: right; white-space: nowrap; }}
  .cizgi {{ border-top: 1px dashed #333; margin: 8px 0; }}
  .toplam {{ font-weight: bold; font-size: 13px; }}
  .toolbar button {{ padding: 6px 12px; margin-bottom: 8px; }}
  @media print {{ .toolbar {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<div class="toolbar"><button onclick="window.print()">Yazdır</button></div>
<h1>{firma}</h1>
<div class="meta">HIZLI SATIŞ FİŞİ<br/>
{html.escape(str(veri.get('fatura_no') or ''))}<br/>
{_tarih(veri.get('fatura_tarihi'))} {html.escape(str(veri.get('islem_saati') or ''))}<br/>
Kasiyer: {html.escape(str(veri.get('kasiyer') or '—'))}<br/>
Müşteri: {html.escape(str(veri.get('musteri') or '—'))}
</div>
<table>{satir_html}</table>
<div class="cizgi"></div>
<table>
<tr><td>Ara</td><td class="r">{html.escape(_para(veri.get('ara_toplam')))}</td></tr>
<tr><td>İskonto</td><td class="r">{html.escape(_para(veri.get('iskonto')))}</td></tr>
<tr><td>KDV</td><td class="r">{html.escape(_para(veri.get('kdv')))}</td></tr>
<tr class="toplam"><td>GENEL</td><td class="r">{html.escape(_para(veri.get('genel_toplam')))}</td></tr>
</table>
<div class="cizgi"></div>
<table>{odeme_html}
<tr><td>Tahsil</td><td class="r">{html.escape(_para(veri.get('tahsilat_tutari')))}</td></tr>
<tr><td>Kalan</td><td class="r">{html.escape(_para(veri.get('kalan')))}</td></tr>
</table>
<p style="text-align:center;margin-top:12px;font-size:10px">Teşekkür ederiz</p>
</body></html>
"""


def a4_html(veri: dict[str, Any]) -> str:
    """A4 satış belgesi (belge_onizleme tarzı tablo)."""
    firma = html.escape(str(veri.get("firma") or _firma_adi()))
    satirlar = ""
    for i, s in enumerate(veri.get("satirlar") or [], start=1):
        satirlar += (
            f"<tr><td>{i}</td>"
            f"<td>{html.escape(str(s.get('urun_kodu') or ''))}</td>"
            f"<td>{html.escape(str(s.get('urun_adi') or ''))}</td>"
            f"<td class='r'>{html.escape(_miktar(s.get('miktar')))}</td>"
            f"<td>{html.escape(str(s.get('birim') or ''))}</td>"
            f"<td class='r'>{html.escape(_para(s.get('birim_fiyat')))}</td>"
            f"<td class='r'>{html.escape(str(s.get('iskonto_orani') or 0))}%</td>"
            f"<td class='r'>{html.escape(_para(s.get('satir_toplam')))}</td></tr>"
        )
    odemeler = "".join(
        f"<tr><td>{html.escape(str(o.get('odeme_sekli') or ''))}</td>"
        f"<td>{html.escape(str(o.get('hesap') or '—'))}</td>"
        f"<td class='r'>{html.escape(_para(o.get('tutar')))}</td></tr>"
        for o in (veri.get("tahsilatlar") or [])
    )
    return f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"/>
<title>Satış {html.escape(str(veri.get('fatura_no') or ''))}</title>
<style>
  body {{ font-family: 'Segoe UI', Tahoma, sans-serif; margin: 24px; color: #111; }}
  h1 {{ font-size: 18px; margin: 0 0 4px; }}
  .alt {{ color: #555; margin-bottom: 16px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 8px; }}
  th, td {{ border-bottom: 1px solid #ccc; padding: 6px 8px; text-align: left; }}
  th {{ background: #f3f4f6; }}
  .r {{ text-align: right; }}
  .toolbar button {{ padding: 6px 14px; margin-bottom: 12px; }}
  @media print {{ .toolbar {{ display: none; }} }}
</style></head><body>
<div class="toolbar"><button onclick="window.print()">Yazdır</button></div>
<h1>{firma}</h1>
<div class="alt">Hızlı Satış Belgesi — {html.escape(str(veri.get('fatura_no') or ''))}</div>
<p>Tarih: {_tarih(veri.get('fatura_tarihi'))} {html.escape(str(veri.get('islem_saati') or ''))}<br/>
Kasiyer: {html.escape(str(veri.get('kasiyer') or '—'))}<br/>
Müşteri: {html.escape(str(veri.get('musteri') or '—'))}</p>
<table>
<thead><tr><th>#</th><th>Kod</th><th>Ürün</th><th>Miktar</th><th>Birim</th>
<th>Fiyat</th><th>İsk</th><th>Toplam</th></tr></thead>
<tbody>{satirlar}</tbody>
</table>
<p><b>Ara:</b> {html.escape(_para(veri.get('ara_toplam')))} &nbsp;
<b>İskonto:</b> {html.escape(_para(veri.get('iskonto')))} &nbsp;
<b>KDV:</b> {html.escape(_para(veri.get('kdv')))} &nbsp;
<b>Genel:</b> {html.escape(_para(veri.get('genel_toplam')))}</p>
<table><thead><tr><th>Ödeme</th><th>Hesap</th><th>Tutar</th></tr></thead>
<tbody>{odemeler or '<tr><td colspan="3">—</td></tr>'}
<tr><td colspan="2"><b>Tahsil / Kalan</b></td>
<td class="r"><b>{html.escape(_para(veri.get('tahsilat_tutari')))} / {html.escape(_para(veri.get('kalan')))}</b></td></tr>
</tbody></table>
</body></html>
"""


def _html_ac(html_metin: str, dosya_on_eki: str, parent=None) -> Path | None:
    try:
        klasor = Path(tempfile.gettempdir()) / "muhasebe_belge"
        klasor.mkdir(exist_ok=True)
        guvenli = "".join(c if c.isalnum() or c in "-_" else "_" for c in dosya_on_eki)[:40]
        dosya = klasor / f"{guvenli}.html"
        dosya.write_text(html_metin, encoding="utf-8")
        webbrowser.open(dosya.as_uri())
        if parent is not None:
            messagebox.showinfo(
                "Yazdırma",
                "Belge tarayıcıda açıldı.\n"
                "Yazdır için düğmeye basın veya Ctrl+P kullanın.\n\n"
                "Yazıcı hatası satışı geri almaz.",
                parent=parent,
            )
        return dosya
    except Exception as hata:
        islem_yaz("YAZDIRMA_HATASI", str(hata), detay={"on_ek": dosya_on_eki})
        if parent is not None:
            messagebox.showerror(
                "Yazdırma",
                f"Önizleme açılamadı (satış kayıtlı kaldı):\n{hata}",
                parent=parent,
            )
        return None


def fis_yazdir(parent, fatura_id: int) -> bool:
    try:
        veri = HizliSatisService.fatura_cikti_verisi(fatura_id)
    except Exception as hata:
        islem_yaz("YAZDIRMA_HATASI", str(hata), detay={"fatura_id": fatura_id, "mod": "fis"})
        messagebox.showerror("Fiş", f"Fiş verisi alınamadı:\n{hata}", parent=parent)
        return False
    return _html_ac(fis_html(veri), f"fis_{veri.get('fatura_no')}", parent) is not None


def a4_yazdir(parent, fatura_id: int) -> bool:
    try:
        veri = HizliSatisService.fatura_cikti_verisi(fatura_id)
    except Exception as hata:
        islem_yaz("YAZDIRMA_HATASI", str(hata), detay={"fatura_id": fatura_id, "mod": "a4"})
        messagebox.showerror("A4", f"Belge verisi alınamadı:\n{hata}", parent=parent)
        return False
    return _html_ac(a4_html(veri), f"a4_{veri.get('fatura_no')}", parent) is not None


def pdf_metin_satirlari(veri: dict[str, Any]) -> list[str]:
    """PDF için düz metin satırları (Türkçe karakterler latin-1'e düşer)."""
    lines = [
        str(veri.get("firma") or _firma_adi()),
        f"Hizli Satis: {veri.get('fatura_no') or ''}",
        f"Tarih: {_tarih(veri.get('fatura_tarihi'))} {veri.get('islem_saati') or ''}",
        f"Musteri: {veri.get('musteri') or ''}",
        f"Kasiyer: {veri.get('kasiyer') or ''}",
        "-" * 60,
    ]
    for s in veri.get("satirlar") or []:
        lines.append(
            f"{s.get('urun_kodu') or ''} {s.get('urun_adi') or ''}  "
            f"x{_miktar(s.get('miktar'))}  {_para(s.get('satir_toplam'))}"
        )
    lines.append("-" * 60)
    lines.append(f"Ara: {_para(veri.get('ara_toplam'))}")
    lines.append(f"Iskonto: {_para(veri.get('iskonto'))}")
    lines.append(f"KDV: {_para(veri.get('kdv'))}")
    lines.append(f"Genel: {_para(veri.get('genel_toplam'))}")
    lines.append(f"Tahsil: {_para(veri.get('tahsilat_tutari'))}")
    lines.append(f"Kalan: {_para(veri.get('kalan'))}")
    for o in veri.get("tahsilatlar") or []:
        lines.append(f"  {o.get('odeme_sekli')}: {_para(o.get('tutar'))}")
    return lines


def pdf_kaydet(parent, fatura_id: int) -> Path | None:
    try:
        veri = HizliSatisService.fatura_cikti_verisi(fatura_id)
    except Exception as hata:
        islem_yaz("YAZDIRMA_HATASI", str(hata), detay={"fatura_id": fatura_id, "mod": "pdf"})
        messagebox.showerror("PDF", f"Belge verisi alınamadı:\n{hata}", parent=parent)
        return None

    fno = str(veri.get("fatura_no") or "satis").replace("/", "-")
    yol = filedialog.asksaveasfilename(
        parent=parent,
        title="PDF kaydet",
        defaultextension=".pdf",
        filetypes=[("PDF", "*.pdf")],
        initialfile=f"hizli_satis_{fno}.pdf",
    )
    if not yol:
        return None
    if not str(yol).lower().endswith(".pdf"):
        yol = f"{yol}.pdf"
    try:
        _basit_pdf_olustur(f"Hizli Satis {fno}", pdf_metin_satirlari(veri), Path(yol))
        islem_yaz("PDF", f"PDF kaydedildi: {yol}", detay={"fatura_no": fno})
        messagebox.showinfo(
            "PDF",
            f"Kaydedildi:\n{yol}\n\n"
            "(WhatsApp gönderimi yok — dosyayı paylaşabilirsiniz.)",
            parent=parent,
        )
        return Path(yol)
    except Exception as hata:
        islem_yaz("YAZDIRMA_HATASI", str(hata), detay={"fatura_id": fatura_id, "mod": "pdf"})
        messagebox.showerror(
            "PDF",
            f"PDF kaydedilemedi (satış kayıtlı kaldı):\n{hata}",
            parent=parent,
        )
        return None


class HizliSatisBasariDialog(tk.Toplevel):
    """Satış sonrası: fatura no + Yazdır / PDF / Kapat (yazdırma satışı bozmaz)."""

    def __init__(self, parent, sonuc: dict[str, Any]):
        super().__init__(parent)
        self.sonuc = sonuc
        self.fatura_id = int(sonuc.get("fatura_id") or 0)
        self.title("Satış tamamlandı")
        self.configure(bg=ACIK_GRI)
        self.geometry("420x280")
        self.minsize(380, 240)
        self.transient(parent)
        self.grab_set()

        kalan = sonuc.get("kalan") or Decimal("0")
        ekstra = ""
        if Decimal(str(kalan)) > 0:
            ekstra = f"\nAçık hesap kalan: {_para(kalan)}"

        tk.Label(
            self,
            text="SATIŞ KAYDEDİLDİ",
            bg=ACIK_GRI,
            fg=YESIL,
            font=("Segoe UI", 14, "bold"),
        ).pack(pady=(16, 8))
        tk.Label(
            self,
            text=(
                f"Fatura: {sonuc.get('fatura_no')}\n"
                f"Tutar: {_para(sonuc.get('genel_toplam'))}\n"
                f"Tahsilat: {_para(sonuc.get('tahsilat_tutari'))}"
                f"{ekstra}"
            ),
            bg=ACIK_GRI,
            fg=KOYU_GRI,
            font=("Segoe UI", 11),
            justify="left",
        ).pack(padx=20, anchor="w")

        tk.Label(
            self,
            text="Yazıcı hatası satışı geri almaz.",
            bg=ACIK_GRI,
            fg="#666666",
            font=("Segoe UI", 9),
        ).pack(pady=(10, 4))

        alt = tk.Frame(self, bg=ACIK_GRI)
        alt.pack(fill="x", side="bottom", padx=12, pady=12)

        tk.Button(
            alt,
            text="Kapat",
            command=self.destroy,
            bg="#9E9E9E",
            fg=BEYAZ,
            relief="flat",
            padx=12,
            pady=8,
        ).pack(side="right", padx=3)
        tk.Button(
            alt,
            text="PDF",
            command=self._pdf,
            bg=KOYU_GRI,
            fg=SARİ,
            relief="flat",
            padx=12,
            pady=8,
        ).pack(side="right", padx=3)
        tk.Button(
            alt,
            text="A4 Yazdır",
            command=self._a4,
            bg=KOYU_GRI,
            fg=BEYAZ,
            relief="flat",
            padx=12,
            pady=8,
        ).pack(side="right", padx=3)
        tk.Button(
            alt,
            text="Fiş Yazdır",
            command=self._fis,
            bg=YESIL,
            fg=BEYAZ,
            relief="flat",
            padx=12,
            pady=8,
        ).pack(side="right", padx=3)

        self.bind("<Escape>", lambda _e: self.destroy())
        self.focus_set()

    def _fis(self) -> None:
        if self.fatura_id:
            fis_yazdir(self, self.fatura_id)

    def _a4(self) -> None:
        if self.fatura_id:
            a4_yazdir(self, self.fatura_id)

    def _pdf(self) -> None:
        if self.fatura_id:
            pdf_kaydet(self, self.fatura_id)


def basari_dialog_goster(parent, sonuc: dict[str, Any]) -> None:
    dlg = HizliSatisBasariDialog(parent, sonuc)
    parent.wait_window(dlg)
