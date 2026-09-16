"""Satış faturası önizleme / yazdır / basit PDF — mevcut kart verisinden.

E-fatura gönderimi yok; yalnızca yerel önizleme ve çıktı.
"""

from __future__ import annotations

import tempfile
import tkinter as tk
import webbrowser
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any


def _para(tutar) -> str:
    try:
        d = Decimal(str(tutar or 0))
    except Exception:
        d = Decimal("0")
    return f"{d:,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(t) -> str:
    if t is None:
        return ""
    if isinstance(t, datetime):
        return t.strftime("%d.%m.%Y")
    if isinstance(t, date):
        return t.strftime("%d.%m.%Y")
    return str(t)


def _miktar(m) -> str:
    metin = f"{Decimal(str(m or 0)):f}".rstrip("0").rstrip(".")
    return metin or "0"


def fatura_ozet_alanlari(kart) -> list[tuple[str, str]]:
    """Açık fatura kartından önizleme alanları üretir."""
    fatura_no = ""
    if hasattr(kart, "fatura_no_alani"):
        try:
            fatura_no = kart.fatura_no_alani.get().strip()
        except tk.TclError:
            fatura_no = ""
    if not fatura_no and getattr(kart, "fatura", None):
        fatura_no = getattr(kart.fatura, "fatura_no", "") or ""

    musteri = ""
    try:
        cari = kart._secili_musteri() if hasattr(kart, "_secili_musteri") else None
        if cari:
            musteri = f"{cari.cari_kodu} — {cari.unvan}"
        elif hasattr(kart, "musteri"):
            musteri = (kart.musteri.get() or "").strip()
    except Exception:
        musteri = ""

    tarih = ""
    vade = ""
    try:
        tarih = kart.girdiler.get("siparis_tarihi").get() if kart.girdiler.get("siparis_tarihi") else ""
        vade = kart.girdiler.get("termin_tarihi").get() if kart.girdiler.get("termin_tarihi") else ""
    except Exception:
        pass

    durum = "TASLAK"
    try:
        if getattr(kart, "fatura", None) and getattr(kart.fatura, "onaylandi", False):
            durum = "ONAYLANDI"
        elif getattr(kart, "fatura", None) and (kart.fatura.durum or "") == "İPTAL":
            durum = "İPTAL"
        elif hasattr(kart, "durum"):
            durum = kart.durum.get() or "TASLAK"
    except Exception:
        pass

    genel = getattr(kart, "_hesaplanan_genel", Decimal("0"))
    alanlar = [
        ("Fatura No", fatura_no or "—"),
        ("Durum", durum),
        ("Müşteri", musteri or "—"),
        ("Fatura Tarihi", tarih or "—"),
        ("Vade Tarihi", vade or "—"),
        ("Genel Toplam", _para(genel)),
    ]

    satirlar = getattr(kart, "satirlar", None) or []
    for i, s in enumerate(satirlar[:40], start=1):
        kod = s.get("urun_kodu") or ""
        ad = s.get("urun_adi") or ""
        miktar = _miktar(s.get("miktar"))
        birim = s.get("birim") or ""
        fiyat = _para(s.get("birim_satis_fiyati") or 0)
        alanlar.append(
            (f"Satır {i}", f"{kod} | {ad} | {miktar} {birim} × {fiyat}")
        )
    if len(satirlar) > 40:
        alanlar.append(("…", f"+{len(satirlar) - 40} satır daha"))
    return alanlar


def fatura_onizle(parent, kart) -> None:
    from belge_onizleme_ui import BelgeOnizlemeDialog

    alanlar = fatura_ozet_alanlari(kart)
    no = next((v for k, v in alanlar if k == "Fatura No"), "—")
    dialog = BelgeOnizlemeDialog(
        parent,
        f"Satış Faturası — {no}",
        alanlar,
        geometry="620x560",
        dipnot="Bu önizleme yerel kayıttan üretilir; e-fatura gönderimi değildir.",
    )
    if dialog.winfo_exists():
        parent.wait_window(dialog)


def _basit_pdf(baslik: str, satirlar: list[str], yol: Path) -> Path:
    yol.parent.mkdir(parents=True, exist_ok=True)

    def esc(t: str) -> str:
        return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    content = ["BT", "/F1 9 Tf", "40 800 Td"]
    first = True
    y = 800
    for line in [baslik, ""] + list(satirlar):
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
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n",
        b"4 0 obj<< /Length "
        + str(len(stream)).encode()
        + b" >>stream\n"
        + stream
        + b"\nendstream\nendobj\n",
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objs:
        offsets.append(len(out))
        out.extend(obj)
    xref = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode())
    out.extend(
        f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    yol.write_bytes(out)
    return yol


def fatura_pdf_kaydet(parent, kart) -> Path | None:
    alanlar = fatura_ozet_alanlari(kart)
    no = next((v for k, v in alanlar if k == "Fatura No"), "fatura")
    guvenli = "".join(c if c.isalnum() or c in "-_" else "_" for c in no) or "fatura"
    yol = filedialog.asksaveasfilename(
        parent=parent,
        title="Fatura PDF Kaydet",
        defaultextension=".pdf",
        initialfile=f"{guvenli}.pdf",
        filetypes=[("PDF", "*.pdf")],
    )
    if not yol:
        return None
    satirlar = [f"{k}: {v}" for k, v in alanlar]
    try:
        return _basit_pdf(f"Satis Faturasi {no}", satirlar, Path(yol))
    except Exception as hata:
        messagebox.showerror("PDF", f"PDF oluşturulamadı:\n{hata}", parent=parent)
        return None


def fatura_yazdir(parent, kart) -> None:
    """HTML geçici dosya ile tarayıcı yazdırma diyaloğu."""
    alanlar = fatura_ozet_alanlari(kart)
    no = next((v for k, v in alanlar if k == "Fatura No"), "—")
    satir_html = "".join(
        f"<tr><td style='padding:4px 8px;border-bottom:1px solid #ddd;color:#555'>{k}</td>"
        f"<td style='padding:4px 8px;border-bottom:1px solid #ddd'>{v}</td></tr>"
        for k, v in alanlar
    )
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Satış Faturası {no}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1F2937}}
h1{{color:#0B2A4A;font-size:20px;margin:0 0 8px}}
.meta{{color:#667085;font-size:12px;margin-bottom:16px}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
@media print{{button{{display:none}}}}
</style></head><body>
<h1>Satış Faturası</h1>
<div class="meta">Yerel çıktı — e-fatura değildir</div>
<table>{satir_html}</table>
<script>window.onload=function(){{window.print();}}</script>
</body></html>"""
    try:
        tmp = Path(tempfile.gettempdir()) / f"satis_fatura_{no.replace('/', '_')}.html"
        tmp.write_text(html, encoding="utf-8")
        webbrowser.open(tmp.as_uri())
    except Exception as hata:
        messagebox.showerror("Yazdır", f"Yazdırma önizlemesi açılamadı:\n{hata}", parent=parent)
