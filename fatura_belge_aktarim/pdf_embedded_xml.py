"""PDF içindeki gömülü UBL-TR XML / ZIP eklerini çıkar."""

from __future__ import annotations

import io
import logging
import zipfile
from typing import Any

_LOG = logging.getLogger("fatura_belge_aktarim.pdf_embedded")


def extract_embedded_xml_candidates(pdf_bytes: bytes) -> list[tuple[str, bytes]]:
    """PDF eklerinden (.xml / .ubl / .zip) aday XML içerikleri döndür."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return []

    reader = PdfReader(io.BytesIO(pdf_bytes))
    if getattr(reader, "is_encrypted", False):
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            return []

    found: list[tuple[str, bytes]] = []
    seen: set[str] = set()

    def _add(name: str, data: bytes) -> None:
        if not data or len(data) < 20:
            return
        key = f"{name}:{len(data)}"
        if key in seen:
            return
        seen.add(key)
        lower = (name or "").lower()
        if lower.endswith(".zip") or data[:2] == b"PK":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    for n in zf.namelist():
                        if n.lower().endswith((".xml", ".ubl")):
                            _add(n, zf.read(n))
            except Exception as exc:  # noqa: BLE001
                _LOG.debug("Gömülü ZIP açılamadı (%s): %s", name, exc)
            return
        # XML benzeri içerik
        head = data[:200].lstrip()
        if head.startswith(b"<?xml") or b"<Invoice" in data[:2000] or b":Invoice" in data[:2000]:
            found.append((name or "embedded.xml", data))

    # pypdf attachments
    try:
        attachments = getattr(reader, "attachments", None) or {}
        if isinstance(attachments, dict):
            for name, payloads in attachments.items():
                items = payloads if isinstance(payloads, list) else [payloads]
                for payload in items:
                    if isinstance(payload, bytes):
                        _add(str(name), payload)
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("attachments okunamadı: %s", exc)

    # Names / EmbeddedFiles tree (eski PDF'ler)
    try:
        root = reader.trailer.get("/Root") if reader.trailer else None
        if root is not None:
            names = root.get("/Names") if hasattr(root, "get") else None
            if names is not None:
                ef = names.get("/EmbeddedFiles") if hasattr(names, "get") else None
                _walk_name_tree(ef, _add)
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("EmbeddedFiles ağacı okunamadı: %s", exc)

    # Sayfa annotation FileAttachment
    try:
        for page in reader.pages:
            annots = page.get("/Annots") if hasattr(page, "get") else None
            if not annots:
                continue
            for annot in annots:
                try:
                    obj = annot.get_object() if hasattr(annot, "get_object") else annot
                    if (obj.get("/Subtype") if hasattr(obj, "get") else None) != "/FileAttachment":
                        continue
                    fs = obj.get("/FS") if hasattr(obj, "get") else None
                    if fs is None:
                        continue
                    fs = fs.get_object() if hasattr(fs, "get_object") else fs
                    ef = fs.get("/EF") if hasattr(fs, "get") else None
                    if ef is None:
                        continue
                    ef = ef.get_object() if hasattr(ef, "get_object") else ef
                    stream = ef.get("/F") or ef.get("/UF")
                    if stream is None:
                        continue
                    stream = stream.get_object() if hasattr(stream, "get_object") else stream
                    data = stream.get_data() if hasattr(stream, "get_data") else bytes(stream)
                    fname = ""
                    if hasattr(fs, "get"):
                        fname = str(fs.get("/UF") or fs.get("/F") or "attachment.xml")
                    _add(fname, data)
                except Exception:  # noqa: BLE001
                    continue
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("Annotation ekleri okunamadı: %s", exc)

    _LOG.info("Gömülü XML aday sayısı=%s adlar=%s", len(found), [n for n, _ in found])
    return found


def _walk_name_tree(node: Any, add_fn) -> None:
    if node is None:
        return
    try:
        node = node.get_object() if hasattr(node, "get_object") else node
    except Exception:
        return
    if not hasattr(node, "get"):
        return
    kids = node.get("/Kids")
    if kids:
        for kid in kids:
            _walk_name_tree(kid, add_fn)
    names = node.get("/Names")
    if not names:
        return
    # [name, fileSpec, name, fileSpec, ...]
    it = list(names)
    for i in range(0, len(it) - 1, 2):
        try:
            name = str(it[i])
            fs = it[i + 1]
            fs = fs.get_object() if hasattr(fs, "get_object") else fs
            ef = fs.get("/EF") if hasattr(fs, "get") else None
            if ef is None:
                continue
            ef = ef.get_object() if hasattr(ef, "get_object") else ef
            stream = ef.get("/F") or ef.get("/UF")
            if stream is None:
                continue
            stream = stream.get_object() if hasattr(stream, "get_object") else stream
            data = stream.get_data() if hasattr(stream, "get_data") else bytes(stream)
            add_fn(name, data)
        except Exception:  # noqa: BLE001
            continue


def try_extract_ubl_from_pdf(pdf_bytes: bytes):
    """İlk geçerli UBL Invoice'i döndür veya None."""
    from fatura_belge_aktarim.ubl_extractor import extract_ubl_xml

    for name, data in extract_embedded_xml_candidates(pdf_bytes):
        try:
            inv = extract_ubl_xml(data)
            if inv.satirlar:
                inv.kaynak = "ubl_xml"
                inv.uyarılar.append(f"PDF içindeki gömülü XML kullanıldı: {name}")
                inv.guven = max(inv.guven, __import__("decimal").Decimal("95"))
                _LOG.info("Gömülü UBL kullanıldı dosya=%s satir=%s", name, len(inv.satirlar))
                return inv
        except Exception as exc:  # noqa: BLE001
            _LOG.debug("Gömülü XML UBL değil (%s): %s", name, exc)
    return None
