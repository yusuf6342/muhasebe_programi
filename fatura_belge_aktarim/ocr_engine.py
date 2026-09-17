"""Tesseract OCR motoru — PDF/görsel → fatura satırları."""

from __future__ import annotations

import io
import logging
import traceback
from decimal import Decimal
from pathlib import Path
from typing import Any

from fatura_belge_aktarim.json_codec import dumps_accounting
from fatura_belge_aktarim.ocr_config import (
    OCR_LANG,
    KULLANICI_OCR_HATASI,
    configure_pytesseract,
    find_tesseract,
    list_tesseract_languages,
    tesseract_version,
)
from fatura_belge_aktarim.ocr_preprocess import preprocess_for_ocr
from fatura_belge_aktarim.pdf_lines import (
    build_column_map,
    finalize_line,
    is_region_end,
    is_region_start,
    line_acceptable,
    map_header_field,
    row_cells_to_dict,
    text_heuristic_lines,
)
from fatura_belge_aktarim.ubl_extractor import ExtractedInvoice

_LOG = logging.getLogger("fatura_belge_aktarim.ocr_engine")

PSM_CANDIDATES = (6, 4, 11, 12)
DPI_DEFAULT = 300

OCR_SATIR_BULUNAMADI = (
    "Fatura başlık bilgileri okundu ancak ürün veya hizmet satırları\n"
    "belirlenemedi. Belgeyi farklı OCR ayarıyla yeniden deneyebilir,\n"
    "XML dosyası seçebilir veya satırları manuel ekleyebilirsiniz."
)


def render_pdf_pages(pdf_bytes: bytes, *, dpi: int = DPI_DEFAULT) -> list[dict[str, Any]]:
    """PDF → PNG sayfa görüntüleri (PyMuPDF; Poppler gerekmez)."""
    import fitz  # PyMuPDF
    from PIL import Image

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    pages: list[dict[str, Any]] = []
    for page_number, page in enumerate(doc, start=1):
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        png = pixmap.tobytes("png")
        img = Image.open(io.BytesIO(png))
        pages.append({"page_number": page_number, "image": img, "image_bytes": png})
    doc.close()
    return pages


def load_image_pages(data: bytes | Path) -> list[dict[str, Any]]:
    from PIL import Image

    if isinstance(data, Path):
        data = data.read_bytes()
    img = Image.open(io.BytesIO(data))
    if getattr(img, "n_frames", 1) > 1:
        pages = []
        for i in range(img.n_frames):
            img.seek(i)
            frame = img.copy().convert("RGB")
            pages.append({"page_number": i + 1, "image": frame, "image_bytes": None})
        return pages
    return [{"page_number": 1, "image": img.convert("RGB"), "image_bytes": None}]


def _words_from_data(data: dict[str, list], *, page: int) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    n = len(data.get("text") or [])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        conf = float(data["conf"][i]) if str(data["conf"][i]) not in {"-1", ""} else 0.0
        words.append(
            {
                "text": text,
                "left": int(data["left"][i]),
                "top": int(data["top"][i]),
                "width": int(data["width"][i]),
                "height": int(data["height"][i]),
                "conf": conf,
                "page": page,
                "block": int(data["block_num"][i]),
                "par": int(data["par_num"][i]),
                "line": int(data["line_num"][i]),
            }
        )
    return words


def _group_ocr_rows(words: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    if not words:
        return []
    # Önce Tesseract satır numarası, yoksa top yakını
    by_key: dict[tuple, list] = {}
    for w in words:
        key = (w["page"], w["block"], w["par"], w["line"])
        by_key.setdefault(key, []).append(w)
    rows = []
    for key in sorted(by_key.keys(), key=lambda k: (k[0], min(x["top"] for x in by_key[k]))):
        rows.append(sorted(by_key[key], key=lambda x: x["left"]))
    return rows


def _ocr_rows_to_lines(
    rows: list[list[dict[str, Any]]], *, page: int, method: str, guven_base: Decimal
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    rejected: list[tuple[str, str]] = []
    lines: list[dict[str, Any]] = []

    header_map: dict[str, tuple[float, float]] = {}
    header_idx = None
    in_region = False

    for ri, row_words in enumerate(rows):
        text = " ".join(w["text"] for w in row_words)
        if is_region_end(text) and (in_region or header_idx is not None):
            break
        if is_region_start(text):
            in_region = True
        fields = []
        for w in row_words:
            field = map_header_field(w["text"])
            if field:
                fields.append((field, float(w["left"]), float(w["left"] + w["width"])))
        # Çoklu kelimeli başlık birleşimi
        joined_fields = build_column_map([text]) 
        # satırdaki tek tek kelimeler yetmezse tüm satırı dene
        if len(fields) >= 2 or (
            joined_fields and ("aciklama" in joined_fields.values() or "miktar" in joined_fields.values())
        ):
            if len(fields) >= 2:
                header_idx = ri
                for field, x0, x1 in fields:
                    header_map[field] = (x0, x1)
                in_region = True
                break

    # Alternatif: başlık satırını hücre gibi parse et
    if header_idx is None:
        for ri, row_words in enumerate(rows):
            cells = [w["text"] for w in row_words]
            cmap = build_column_map(cells)
            if len(cmap) >= 2 and (
                "aciklama" in cmap.values() or "miktar" in cmap.values() or "birim_fiyat" in cmap.values()
            ):
                header_idx = ri
                for idx, field in cmap.items():
                    if idx < len(row_words):
                        w = row_words[idx]
                        header_map[field] = (float(w["left"]), float(w["left"] + w["width"]))
                break

    if header_idx is None or not header_map:
        # Sezgisel metin
        metin = "\n".join(" ".join(w["text"] for w in r) for r in rows)
        heur = text_heuristic_lines(metin)
        for i, ln in enumerate(heur, start=1):
            ln["source_method"] = method
            ln["kaynak"] = method
            ln["source_page"] = page
            ln["sira"] = i
            ln["line_number"] = i
        return heur, rejected

    def assign_field(x_mid: float) -> str | None:
        best_f = None
        best_d = 1e9
        for field, (x0, x1) in header_map.items():
            mid = (x0 + x1) / 2
            d = abs(x_mid - mid)
            if x0 - 40 <= x_mid <= x1 + 40 and d < best_d:
                best_d = d
                best_f = field
        return best_f

    pending = ""
    for row_words in rows[header_idx + 1 :]:
        text = " ".join(w["text"] for w in row_words)
        if is_region_end(text):
            break
        bucket: dict[str, list[str]] = {}
        for w in row_words:
            field = assign_field(float(w["left"]) + float(w["width"]) / 2)
            if not field:
                continue
            bucket.setdefault(field, []).append(w["text"])
        data: dict[str, Any] = {}
        from fatura_belge_aktarim.normalize import parse_decimal_tr

        for field, parts in bucket.items():
            joined = " ".join(parts).strip()
            if field in {"miktar", "birim_fiyat", "kdv_orani", "kdv_tutari", "satir_toplam", "iskonto"}:
                val = parse_decimal_tr(joined)
                if field == "iskonto":
                    data["iskonto_orani"] = val
                elif field == "miktar":
                    # birim ayır
                    import re

                    m = re.match(
                        r"^\s*([\d.,]+)\s*([A-Za-zÇĞİÖŞÜçğıöşü%]{0,12})\s*$",
                        joined.replace(" ", ""),
                    )
                    if m:
                        data["miktar"] = parse_decimal_tr(m.group(1))
                        if m.group(2) and m.group(2).upper() not in {"TL", "TRY", "%"}:
                            data["birim"] = m.group(2)
                    else:
                        data["miktar"] = val
                else:
                    data[field] = val
            else:
                data[field] = joined

        has_qty = data.get("miktar") is not None
        has_price = data.get("birim_fiyat") is not None or data.get("satir_toplam") is not None
        if not has_qty and not has_price:
            cont = data.get("aciklama") or text
            if cont and lines:
                lines[-1]["aciklama"] = f"{lines[-1].get('aciklama') or ''} {cont}".strip()
                lines[-1]["description"] = lines[-1]["aciklama"]
            elif cont:
                pending = f"{pending} {cont}".strip()
            continue
        if pending:
            data["aciklama"] = f"{pending} {data.get('aciklama') or ''}".strip()
            pending = ""
        ok, reason = line_acceptable(data)
        if not ok:
            rejected.append((text[:100], reason))
            continue
        avg_conf = sum(w["conf"] for w in row_words) / max(1, len(row_words))
        guven = min(Decimal("85"), guven_base + Decimal(str(round(avg_conf / 10, 1))))
        bbox = (
            min(w["left"] for w in row_words),
            min(w["top"] for w in row_words),
            max(w["left"] + w["width"] for w in row_words),
            max(w["top"] + w["height"] for w in row_words),
        )
        data["bbox"] = bbox
        line = finalize_line(data, sira=len(lines) + 1, method=method, page=page, guven=guven)
        line["confidence"] = float(avg_conf)
        lines.append(line)
    return lines, rejected


def _score_result(
    lines: list[dict[str, Any]],
    words: list[dict[str, Any]],
    header: ExtractedInvoice | None,
) -> float:
    if not lines:
        return 0.0
    avg_conf = sum(float(w.get("conf") or 0) for w in words) / max(1, len(words))
    score = len(lines) * 20 + avg_conf * 0.3
    # zorunlu alanlar
    for ln in lines:
        if ln.get("aciklama"):
            score += 5
        if ln.get("miktar"):
            score += 5
        if ln.get("birim_fiyat") or ln.get("satir_toplam"):
            score += 5
    # toplam mutabakatı
    if header and (header.toplamlar or {}).get("odenecek") or (header and (header.toplamlar or {}).get("genel_toplam")):
        hedef = (header.toplamlar or {}).get("odenecek") or (header.toplamlar or {}).get("genel_toplam")
        hesap = Decimal("0")
        for ln in lines:
            mik = ln.get("miktar") or Decimal("0")
            fiyat = ln.get("birim_fiyat") or Decimal("0")
            isk = (ln.get("iskonto_orani") or Decimal("0")) / Decimal("100")
            kdv = (ln.get("kdv_orani") or Decimal("0")) / Decimal("100")
            net = mik * fiyat * (Decimal("1") - isk)
            hesap += net * (Decimal("1") + kdv)
        if hedef and hedef > 0:
            fark = abs(hesap - hedef) / hedef
            score += max(0, 40 * (1 - float(min(fark, 1))))
    return score


def run_tesseract_on_image(
    image: Any,
    *,
    page: int = 1,
    header: ExtractedInvoice | None = None,
) -> dict[str, Any]:
    """Tek sayfa: çoklu PSM dene, en iyi fatura yapısını seç."""
    from pytesseract import Output
    import pytesseract

    path = configure_pytesseract()
    if not path:
        raise RuntimeError("Tesseract bulunamadı")

    processed = preprocess_for_ocr(image)
    langs = list_tesseract_languages(path)
    lang = OCR_LANG if ("tur" in langs and "eng" in langs) else ("tur" if "tur" in langs else "eng")

    best: dict[str, Any] | None = None
    trials: list[dict[str, Any]] = []

    for psm in PSM_CANDIDATES:
        config = f"--oem 3 --psm {psm}"
        try:
            data = pytesseract.image_to_data(
                processed, lang=lang, config=config, output_type=Output.DICT
            )
            words = _words_from_data(data, page=page)
            rows = _group_ocr_rows(words)
            lines, rejected = _ocr_rows_to_lines(
                rows, page=page, method="tesseract_ocr", guven_base=Decimal("45")
            )
            # düz metin yedek
            if not lines:
                plain = pytesseract.image_to_string(processed, lang=lang, config=config)
                lines = text_heuristic_lines(plain or "")
                for ln in lines:
                    ln["source_method"] = "tesseract_ocr"
                    ln["kaynak"] = "tesseract_ocr"
                    ln["source_page"] = page
            score = _score_result(lines, words, header)
            trial = {
                "psm": psm,
                "word_count": len(words),
                "avg_conf": (sum(w["conf"] for w in words) / max(1, len(words))),
                "line_count": len(lines),
                "rejected": rejected[:20],
                "score": score,
                "lines": lines,
                "plain_len": sum(len(w["text"]) for w in words),
            }
            trials.append({k: v for k, v in trial.items() if k != "lines"})
            _LOG.info(
                "OCR psm=%s words=%s lines=%s score=%.1f avg_conf=%.1f",
                psm,
                len(words),
                len(lines),
                score,
                trial["avg_conf"],
            )
            if best is None or score > best["score"]:
                best = trial
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("OCR psm=%s hata: %s", psm, exc)
            trials.append({"psm": psm, "error": str(exc), "score": 0})

    if best is None:
        return {"lines": [], "trials": trials, "lang": lang, "path": path}
    return {
        "lines": best["lines"],
        "trials": trials,
        "best_psm": best["psm"],
        "score": best["score"],
        "lang": lang,
        "path": path,
        "rejected": best.get("rejected") or [],
    }


def extract_with_ocr(
    data: bytes,
    *,
    is_pdf: bool = True,
    header: ExtractedInvoice | None = None,
    dosya_adi: str = "",
) -> tuple[ExtractedInvoice, dict[str, Any]]:
    """PDF veya görsel baytlarından OCR ile ExtractedInvoice üret."""
    diag: dict[str, Any] = {
        "ocr_used": True,
        "tesseract_path": find_tesseract(),
        "tesseract_version": tesseract_version(),
        "pages": [],
    }
    out = header or ExtractedInvoice(kaynak="tesseract_ocr", guven=Decimal("40"))
    out.kaynak = "tesseract_ocr"

    try:
        if not configure_pytesseract():
            out.uyarılar.append(
                "Tesseract OCR bulunamadı. Servis ve Sistem Kontrolü > OCR ayarlarından yolu tanımlayın."
            )
            out.uyarılar.append(OCR_SATIR_BULUNAMADI)
            diag["error"] = "tesseract_not_found"
            return out, diag

        if is_pdf:
            pages = render_pdf_pages(data, dpi=DPI_DEFAULT)
        else:
            pages = load_image_pages(data)
        diag["page_count"] = len(pages)

        all_lines: list[dict[str, Any]] = []
        all_text: list[str] = []
        best_psms: list[int] = []

        for page_info in pages:
            page_no = page_info["page_number"]
            result = run_tesseract_on_image(page_info["image"], page=page_no, header=out)
            diag["pages"].append(
                {
                    "page": page_no,
                    "best_psm": result.get("best_psm"),
                    "line_count": len(result.get("lines") or []),
                    "trials": result.get("trials"),
                    "lang": result.get("lang"),
                }
            )
            if result.get("best_psm"):
                best_psms.append(int(result["best_psm"]))
            for ln in result.get("lines") or []:
                all_lines.append(ln)
            # başlık için düz metin
            try:
                import pytesseract

                plain = pytesseract.image_to_string(
                    preprocess_for_ocr(page_info["image"]),
                    lang=result.get("lang") or OCR_LANG,
                    config="--oem 3 --psm 6",
                )
                all_text.append(plain or "")
            except Exception:  # noqa: BLE001
                pass

        metin = "\n".join(all_text)
        if metin.strip():
            from fatura_belge_aktarim.pdf_extractor import _header_from_text

            _header_from_text(metin, out)

        for i, ln in enumerate(all_lines, start=1):
            ln["sira"] = i
            ln["line_number"] = i
            ln["source_method"] = "tesseract_ocr"
            ln["kaynak"] = "tesseract_ocr"

        out.satirlar = all_lines
        diag["line_count"] = len(all_lines)
        diag["best_psms"] = best_psms
        diag["winning_method"] = "tesseract_ocr" if all_lines else None

        if all_lines:
            out.guven = Decimal("55")
            out.uyarılar.append(
                f"Tesseract OCR ile {len(all_lines)} satır okundu (psm={best_psms or '-'}). Alanları kontrol edin."
            )
        else:
            out.uyarılar.append(OCR_SATIR_BULUNAMADI)
            _LOG.warning(
                "OCR satır bulamadı dosya=%s path=%s pages=%s",
                dosya_adi,
                diag.get("tesseract_path"),
                diag.get("page_count"),
            )

        _LOG.info(
            "OCR tamam path=%s ver=%s lang=%s pages=%s lines=%s",
            diag.get("tesseract_path"),
            diag.get("tesseract_version"),
            OCR_LANG,
            diag.get("page_count"),
            len(all_lines),
        )
        return out, diag

    except Exception as exc:  # noqa: BLE001
        _LOG.error(
            "OCR hata dosya=%s path=%s\n%s",
            dosya_adi,
            find_tesseract(),
            traceback.format_exc(),
        )
        out.uyarılar.append(KULLANICI_OCR_HATASI)
        diag["error"] = type(exc).__name__
        diag["traceback"] = traceback.format_exc()[-2000:]
        raise ValueError(KULLANICI_OCR_HATASI) from exc
