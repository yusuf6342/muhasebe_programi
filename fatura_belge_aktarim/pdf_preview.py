"""PDF / görsel önizleme — kontrol ekranı sol panel."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path


def sayfa_sayisi(yol: Path | str) -> int:
    p = Path(yol)
    if not p.is_file():
        return 0
    ext = p.suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}:
        return 1
    if ext != ".pdf":
        return 0
    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf  # type: ignore
    doc = pymupdf.open(p)
    try:
        return int(doc.page_count)
    finally:
        doc.close()


def sayfa_png_bytes(yol: Path | str, sayfa: int = 0, *, genislik: int = 520) -> bytes | None:
    """Belirtilen sayfayı PNG baytlarına çevir (0-indeks). Görsellerde sayfa yok sayılır."""
    p = Path(yol)
    if not p.is_file():
        return None
    ext = p.suffix.lower()
    genislik = max(120, int(genislik))

    if ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}:
        try:
            from PIL import Image
        except ImportError:
            return p.read_bytes() if ext == ".png" else None
        with Image.open(p) as im:
            im = im.convert("RGB")
            w, h = im.size
            if w > genislik:
                oran = genislik / float(w)
                im = im.resize((genislik, max(1, int(h * oran))), Image.Resampling.LANCZOS)
            buf = BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()

    if ext != ".pdf":
        return None

    try:
        import pymupdf
    except ImportError:
        import fitz as pymupdf  # type: ignore

    doc = pymupdf.open(p)
    try:
        n = int(doc.page_count)
        if n <= 0:
            return None
        idx = max(0, min(int(sayfa), n - 1))
        page = doc.load_page(idx)
        rect = page.rect
        zoom = genislik / float(rect.width) if rect.width else 1.0
        mat = pymupdf.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()
