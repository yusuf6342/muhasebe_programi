"""PDF üretimi — Edge/Chrome headless veya HTML yedek."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
import time
import uuid
from datetime import date, datetime
from pathlib import Path

from invoice_print.html_renderer import render_invoice_html
from invoice_print.view_model import InvoicePrintViewModel

_LOG = logging.getLogger("invoice_print.pdf")

_ONIZLEME_KLASOR = Path(tempfile.gettempdir()) / "muhasebe_fatura_onizleme"
_ONIZLEME_MAX_YAS_SN = 3600  # 1 saat


def safe_pdf_filename(vm: InvoicePrintViewModel) -> str:
    musteri = (vm.musteri or {}).get("unvan") or "Musteri"
    musteri = re.sub(r'[<>:"/\\|?*]+', "", musteri)[:40].strip() or "Musteri"
    musteri = musteri.replace(" ", "_")
    no = re.sub(r"[^\w\-]+", "_", vm.fatura_no or "Yeni")
    gun = date.today().isoformat()
    tur_u = (vm.belge_turu or "").upper()
    tur = "Alis" if ("ALI" in tur_u and "SAT" not in tur_u) else "Satis"
    return f"{tur}_Faturasi_{no}_{musteri}_{gun}.pdf"


def onizleme_klasoru() -> Path:
    _ONIZLEME_KLASOR.mkdir(parents=True, exist_ok=True)
    return _ONIZLEME_KLASOR


def eski_onizleme_pdflerini_temizle(*, max_yas_sn: int = _ONIZLEME_MAX_YAS_SN) -> None:
    """Geçici önizleme PDF/HTML dosyalarını güvenli biçimde siler."""
    klasor = onizleme_klasoru()
    simdi = time.time()
    for yol in klasor.glob("onizleme_*"):
        try:
            if simdi - yol.stat().st_mtime > max_yas_sn:
                yol.unlink(missing_ok=True)
        except OSError:
            pass


def gecici_onizleme_pdf_yolu(vm: InvoicePrintViewModel) -> Path:
    """Çakışmasız geçici PDF yolu (UUID + zaman damgası)."""
    klasor = onizleme_klasoru()
    no = re.sub(r"[^\w\-]+", "_", (vm.fatura_no or "yeni"))[:24]
    ad = f"onizleme_{no}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}.pdf"
    return klasor / ad


def _html_gecici(vm: InvoicePrintViewModel) -> Path:
    klasor = Path(tempfile.gettempdir()) / "muhasebe_fatura_a4"
    klasor.mkdir(parents=True, exist_ok=True)
    yol = klasor / f"onizleme_{vm.fatura_id or 'yeni'}_{datetime.now():%H%M%S}_{uuid.uuid4().hex[:6]}.html"
    yol.write_text(render_invoice_html(vm, toolbar=False, zoom_pct=100), encoding="utf-8")
    return yol


def _chrome_edge_paths() -> list[Path]:
    adaylar = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    return [p for p in adaylar if p.is_file()]


def render_invoice_to_pdf(vm: InvoicePrintViewModel, hedef: Path) -> Path:
    """A4 PDF. Türkçe karakter için Chromium print-to-pdf tercih edilir."""
    hedef = Path(hedef)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    html_yol = _html_gecici(vm)
    uri = html_yol.resolve().as_uri()
    son_hata: Exception | None = None
    for tarayici in _chrome_edge_paths():
        try:
            cmd = [
                str(tarayici),
                "--headless=new",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={hedef}",
                uri,
            ]
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=60,
                check=False,
            )
            if hedef.is_file() and hedef.stat().st_size > 500:
                try:
                    html_yol.unlink(missing_ok=True)
                except OSError:
                    pass
                return hedef
            son_hata = RuntimeError(
                (proc.stderr or b"").decode("utf-8", errors="ignore")[:300]
                or f"exit={proc.returncode}"
            )
        except Exception as exc:
            son_hata = exc
            _LOG.warning("PDF motoru başarısız (%s): %s", tarayici.name, exc)

    yedek = hedef.with_suffix(".html")
    yedek.write_text(
        render_invoice_html(vm, toolbar=True, zoom_pct=100), encoding="utf-8"
    )
    _LOG.error(
        "PDF oluşturulamadı, HTML kaydedildi | fatura_id=%s yol=%s hata=%s",
        vm.fatura_id,
        yedek,
        son_hata,
    )
    raise ValueError(
        "Fatura PDF dosyası oluşturulamadı. Edge veya Chrome kurulu olmalı; "
        "kayıt klasörünü ve dosya izinlerini kontrol edin.\n"
        f"(Geçici HTML: {yedek})"
    )


def render_preview_pdf_and_open(vm: InvoicePrintViewModel) -> Path:
    """Geçici PDF oluşturup varsayılan görüntüleyicide açar (kalıcı kayıt yok)."""
    eski_onizleme_pdflerini_temizle()
    hedef = gecici_onizleme_pdf_yolu(vm)
    render_invoice_to_pdf(vm, hedef)
    try:
        os.startfile(str(hedef))
    except OSError as exc:
        raise ValueError(
            f"PDF oluşturuldu ancak açılamadı:\n{hedef}\n\n{exc}"
        ) from exc
    return hedef


def html_dosyasi_yaz(vm: InvoicePrintViewModel, hedef: Path | None = None) -> Path:
    if hedef is None:
        return _html_gecici(vm)
    hedef = Path(hedef)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(render_invoice_html(vm, toolbar=True, zoom_pct=100), encoding="utf-8")
    return hedef
