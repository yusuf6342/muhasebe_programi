"""PDF fatura satır çıkarma — tablo, koordinat ve metin tabanlı."""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Any

from fatura_belge_aktarim.normalize import (
    birim_normalize,
    header_key_plain,
    normalize_header,
    parse_decimal_tr,
)

_LOG = logging.getLogger("fatura_belge_aktarim.pdf_lines")

HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "sira": ("sıra no", "sira no", "sıra", "sira", "no", "satır", "satir", "kalem", "#"),
    "urun_kodu": (
        "ürün hizmet kodu",
        "urun hizmet kodu",
        "mal hizmet kodu",
        "ürün kodu",
        "urun kodu",
        "malzeme kodu",
        "stok kodu",
        "mal/hizmet kodu",
        "ürün no",
        "urun no",
    ),
    "aciklama": (
        "ürün hizmet adı",
        "urun hizmet adi",
        "ürün hizmet adi",
        "mal hizmet",
        "mal/hizmet",
        "ürün açıklaması",
        "urun aciklamasi",
        "ürün",
        "urun",
        "açıklama",
        "aciklama",
        "malzeme",
        "hizmet",
        "cinsi",
        "adı",
        "adi",
        "name",
        "description",
    ),
    "miktar": ("miktar", "adet", "qty", "quantity", "mik"),
    "birim": ("birim", "ölçü birimi", "olcu birimi", "birimi", "unit"),
    "birim_fiyat": (
        "birim fiyat",
        "fiyat",
        "birim bedel",
        "birim fiyatı",
        "birim fiyati",
        "unit price",
        "bfiyat",
    ),
    "iskonto": ("iskonto", "indirim", "isk", "iskonto tutarı", "iskonto tutari", "iskonto oranı", "iskonto orani"),
    "kdv_orani": ("kdv", "kdv oranı", "kdv orani", "kdv %", "kdv%", "vergi oranı", "vergi orani"),
    "kdv_tutari": ("kdv tutarı", "kdv tutari", "hesaplanan kdv", "vergi tutarı", "vergi tutari"),
    "satir_toplam": (
        "ürün hizmet tutarı",
        "urun hizmet tutari",
        "mal hizmet tutarı",
        "mal/hizmet tutarı",
        "mal hizmet tutari",
        "satır toplamı",
        "satir toplami",
        "satır tutarı",
        "satir tutari",
        "net tutar",
        "line extension",
        "amount",
        "tutar",
    ),
}

REGION_START = (
    "mal/hizmet bilgileri",
    "mal hizmet bilgileri",
    "fatura kalemleri",
    "ürünler",
    "urunler",
    "hizmetler",
    "mal hizmet",
    "kalemler",
)

REGION_END = (
    "mal/hizmet toplam tutarı",
    "mal hizmet toplam",
    "toplam iskonto",
    "toplam indirim",
    "hesaplanan kdv",
    "vergiler dahil toplam",
    "ödenecek tutar",
    "odenecek tutar",
    "genel toplam",
    "yalnız",
    "yalniz",
    "notlar",
    "ödeme bilgileri",
    "odeme bilgileri",
    "toplam tutar",
    "ara toplam",
)


def map_header_field(cell: Any) -> str | None:
    norm = normalize_header(cell)
    plain = header_key_plain(cell)
    if not norm:
        return None

    best: tuple[int, int, str] | None = None  # score, alias_len, field

    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            a_norm = normalize_header(alias)
            a_plain = header_key_plain(alias)
            if not a_norm:
                continue
            score = 0
            if norm == a_norm or plain == a_plain:
                score = 100
            elif len(a_norm) >= 6 and norm.startswith(a_norm):
                score = 90
            elif len(norm) >= 6 and a_norm.startswith(norm) and len(a_norm) - len(norm) <= 8:
                score = 85
            elif f" {a_norm} " in f" {norm} " or norm.startswith(a_norm + " ") or norm.endswith(" " + a_norm):
                # kısa genel kelime: başlık büyük ölçüde alias olmalı
                extra = len(norm) - len(a_norm)
                if extra <= 2:
                    score = 80 if len(a_norm) >= 4 else 45
                elif extra <= 8 and len(a_norm) >= 5:
                    score = 55
                else:
                    score = 0
            elif len(a_norm) >= 8 and a_norm in norm:
                score = 70
            if score <= 0:
                continue
            cand = (score, len(a_norm), field)
            if best is None or cand[0] > best[0] or (cand[0] == best[0] and cand[1] > best[1]):
                best = cand

    return best[2] if best else None


def build_column_map(header_row: list[Any]) -> dict[int, str]:
    """Her sütun için en iyi alanı seç; aynı alan iki kez yazılırsa daha yüksek skor kazanır."""
    scored: list[tuple[int, int, int, str]] = []  # score, alias_proxy, col, field
    for idx, cell in enumerate(header_row or []):
        field = map_header_field(cell)
        if not field:
            continue
        # skor tahmini: map_header_field iç skorunu yeniden hesaplamak yerine hücre uzunluğu
        norm = normalize_header(cell)
        score = 50
        for alias in HEADER_ALIASES.get(field, ()):
            a = normalize_header(alias)
            if norm == a:
                score = max(score, 100 + len(a))
            elif a and a in norm:
                score = max(score, 70 + len(a))
        scored.append((score, len(norm), idx, field))
    scored.sort(reverse=True)
    mapping: dict[int, str] = {}
    used: set[str] = set()
    for _score, _ln, idx, field in scored:
        if field in used:
            continue
        mapping[idx] = field
        used.add(field)
    return mapping


def is_region_start(text: str) -> bool:
    n = normalize_header(text)
    p = header_key_plain(text)
    return any(s in n or s in p for s in REGION_START)


def is_region_end(text: str) -> bool:
    n = normalize_header(text)
    p = header_key_plain(text)
    return any(e in n or e in p for e in REGION_END)


def is_total_like_row(row: dict[str, Any]) -> bool:
    acik = str(row.get("aciklama") or "")
    return is_region_end(acik) or bool(
        re.search(r"^(toplam|genel|ödenecek|odenecek|kdv\s*toplam|ara\s*toplam)", acik.strip(), re.I)
    )


def line_acceptable(row: dict[str, Any]) -> tuple[bool, str]:
    acik = (row.get("aciklama") or "").strip()
    miktar = row.get("miktar")
    fiyat = row.get("birim_fiyat")
    toplam = row.get("satir_toplam")
    if not acik:
        return False, "açıklama yok"
    if is_total_like_row(row):
        return False, "toplam/özet satırı"
    if miktar is None or miktar <= 0:
        return False, "miktar geçersiz"
    if fiyat is not None and fiyat >= 0:
        return True, "ok"
    if toplam is not None and toplam >= 0:
        return True, "ok_toplamdan"
    return False, "fiyat ve satır toplamı yok"


def finalize_line(row: dict[str, Any], *, sira: int, method: str, page: int, guven: Decimal) -> dict[str, Any]:
    miktar = row.get("miktar")
    fiyat = row.get("birim_fiyat")
    toplam = row.get("satir_toplam")
    hesaplandi = False
    if (fiyat is None or fiyat == 0) and miktar and toplam is not None and miktar != 0:
        fiyat = (toplam / miktar).quantize(Decimal("0.000001"))
        hesaplandi = True
    if toplam is None and miktar is not None and fiyat is not None:
        isk = row.get("iskonto_orani") or Decimal("0")
        toplam = (miktar * fiyat * (Decimal("1") - isk / Decimal("100"))).quantize(Decimal("0.01"))
    out = {
        "sira": sira,
        "line_number": sira,
        "aciklama": (row.get("aciklama") or "").strip()[:500],
        "description": (row.get("aciklama") or "").strip()[:500],
        "satici_urun_kodu": (row.get("urun_kodu") or "").strip() or None,
        "supplier_product_code": (row.get("urun_kodu") or "").strip() or None,
        "alici_urun_kodu": None,
        "barkod": (row.get("barkod") or None),
        "barcode": row.get("barkod"),
        "miktar": miktar,
        "quantity": miktar,
        "birim": birim_normalize(row.get("birim") or "ADET"),
        "unit": birim_normalize(row.get("birim") or "ADET"),
        "birim_fiyat": fiyat,
        "unit_price": fiyat,
        "unit_factor": Decimal("1"),
        "iskonto_orani": row.get("iskonto_orani") or Decimal("0"),
        "discount_rate": row.get("iskonto_orani") or Decimal("0"),
        "discount_amount": row.get("iskonto_tutari") or Decimal("0"),
        "kdv_orani": row.get("kdv_orani") if row.get("kdv_orani") is not None else Decimal("20"),
        "vat_rate": row.get("kdv_orani") if row.get("kdv_orani") is not None else Decimal("20"),
        "vat_amount": row.get("kdv_tutari") or Decimal("0"),
        "satir_toplam": toplam,
        "line_net_total": toplam,
        "guven": guven,
        "confidence": float(guven),
        "kaynak": method,
        "source_method": method,
        "source_page": page,
        "source_bbox": row.get("bbox"),
        "match_status": "unmatched",
        "hesaplandi": hesaplandi,
    }
    return out


def row_cells_to_dict(cells: list[Any], colmap: dict[int, str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    leftovers: list[str] = []
    for idx, cell in enumerate(cells):
        text = str(cell or "").strip()
        if not text:
            continue
        field = colmap.get(idx)
        if field is None:
            leftovers.append(text)
            continue
        if field in {"miktar", "birim_fiyat", "iskonto", "kdv_orani", "kdv_tutari", "satir_toplam"}:
            # Miktar hücresinden birim ayır (120m, 10 Adet)
            if field == "miktar":
                m = re.match(
                    r"^\s*([\d.,]+)\s*([A-Za-zÇĞİÖŞÜçğıöşü%]{0,12})\s*$",
                    text.replace(" ", ""),
                )
                if m:
                    val = parse_decimal_tr(m.group(1))
                    data["miktar"] = val
                    birim_txt = m.group(2) or ""
                    if birim_txt and birim_txt.upper() not in {"TL", "TRY", "%"} and "birim" not in data:
                        data["birim"] = birim_txt
                    continue
            val = parse_decimal_tr(text)
            if field == "iskonto":
                # oran veya tutar; % işareti varsa oran
                if "%" in str(cell) or (val is not None and val <= 100):
                    data["iskonto_orani"] = val
                else:
                    data["iskonto_tutari"] = val
            elif field == "kdv_orani":
                data["kdv_orani"] = val
            elif field == "kdv_tutari":
                data["kdv_tutari"] = val
            else:
                data[field] = val
        elif field == "birim":
            data["birim"] = text
        elif field == "sira":
            continue
        else:
            data[field] = text
    if "aciklama" not in data and leftovers:
        # Sayısal olmayan ilk leftover açıklama
        for t in leftovers:
            if parse_decimal_tr(t) is None and not re.fullmatch(r"[A-Za-z]{1,6}", t):
                data["aciklama"] = t
                break
        if "aciklama" not in data:
            data["aciklama"] = leftovers[0]
    return data


def tables_to_lines(tables: list[list[list[Any]]], *, method: str, page: int, guven: Decimal) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    rejected: list[tuple[str, str]] = []
    for table in tables:
        if not table or len(table) < 2:
            continue
        header_idx = None
        colmap: dict[int, str] = {}
        for i, row in enumerate(table[:5]):
            cmap = build_column_map(row)
            if len(cmap) >= 2 and ("aciklama" in cmap.values() or "miktar" in cmap.values()):
                header_idx = i
                colmap = cmap
                break
        if header_idx is None:
            # Varsayım: açıklama, miktar, birim, fiyat, kdv, tutar
            sample = table[0]
            if len(sample) >= 4:
                colmap = {0: "aciklama", 1: "miktar", 2: "birim", 3: "birim_fiyat"}
                if len(sample) >= 5:
                    colmap[4] = "kdv_orani"
                if len(sample) >= 6:
                    colmap[5] = "satir_toplam"
                header_idx = -1
            else:
                continue
        start = header_idx + 1
        for raw in table[start:]:
            cells = [c for c in (raw or [])]
            joined = " ".join(str(c or "") for c in cells).strip()
            if not joined:
                continue
            if is_region_end(joined):
                break
            data = row_cells_to_dict(cells, colmap)
            ok, reason = line_acceptable(data)
            if not ok:
                rejected.append((joined[:80], reason))
                continue
            lines.append(finalize_line(data, sira=len(lines) + 1, method=method, page=page, guven=guven))
    _LOG.info(
        "Tablo satır çıkarma method=%s page=%s kabul=%s red=%s",
        method,
        page,
        len(lines),
        len(rejected),
    )
    for j, reason in rejected[:30]:
        _LOG.info("Reddedilen satır: %s | neden=%s", j, reason)
    return lines


def extract_tables_pdfplumber(pdf_bytes: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Çoklu tablo stratejisi ile satır çıkar."""
    import io

    try:
        import pdfplumber
    except ImportError:
        _LOG.warning("pdfplumber yok; tablo çıkarma atlandı")
        return [], {"pdfplumber": False}

    strategies = [
        ("lines", {"vertical_strategy": "lines", "horizontal_strategy": "lines"}),
        ("lines_strict", {"vertical_strategy": "lines_strict", "horizontal_strategy": "lines_strict"}),
        ("text", {"vertical_strategy": "text", "horizontal_strategy": "text"}),
        ("explicit_text", {"vertical_strategy": "text", "horizontal_strategy": "lines"}),
    ]
    diag: dict[str, Any] = {"pdfplumber": True, "pages": [], "strategy_hits": {}}
    best: list[dict[str, Any]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        diag["page_count"] = len(pdf.pages)
        for page_number, page in enumerate(pdf.pages, start=1):
            page_info: dict[str, Any] = {"page": page_number, "tables": []}
            page_best: list[dict[str, Any]] = []
            for name, settings in strategies:
                try:
                    tables = page.extract_tables(table_settings=settings) or []
                except Exception as exc:  # noqa: BLE001
                    _LOG.debug("Tablo stratejisi %s başarısız: %s", name, exc)
                    tables = []
                page_info["tables"].append(
                    {
                        "strategy": name,
                        "count": len(tables),
                        "shapes": [[len(t), len(t[0]) if t else 0] for t in tables],
                    }
                )
                lines = tables_to_lines(tables, method=f"pdf_table:{name}", page=page_number, guven=Decimal("70"))
                if len(lines) > len(page_best):
                    page_best = lines
                    diag["strategy_hits"][f"{page_number}:{name}"] = len(lines)
            # Varsayılan extract_tables
            try:
                default_tables = page.extract_tables() or []
                lines = tables_to_lines(
                    default_tables, method="pdf_table:default", page=page_number, guven=Decimal("68")
                )
                if len(lines) > len(page_best):
                    page_best = lines
            except Exception:  # noqa: BLE001
                pass
            best.extend(page_best)
            diag["pages"].append(page_info)
    # sıra yeniden numarala
    for i, line in enumerate(best, start=1):
        line["sira"] = i
        line["line_number"] = i
    return best, diag


def words_to_lines_by_coordinates(pdf_bytes: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Kelime koordinatlarıyla satır/sütun çıkarımı."""
    import io

    try:
        import pdfplumber
    except ImportError:
        return [], {"coordinates": False}

    diag: dict[str, Any] = {"coordinates": True, "pages": []}
    all_lines: list[dict[str, Any]] = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False) or []
            diag["pages"].append({"page": page_number, "word_count": len(words)})
            if not words:
                continue
            # y'ye göre satır grupları
            rows: list[list[dict]] = []
            for w in sorted(words, key=lambda x: (round(float(x["top"]), 0), float(x["x0"]))):
                top = float(w["top"])
                if not rows or abs(top - float(rows[-1][0]["top"])) > 4:
                    rows.append([w])
                else:
                    rows[-1].append(w)

            # Başlık satırını bul
            header_map: dict[str, tuple[float, float]] = {}
            header_row_idx = None
            in_region = False
            for ri, row_words in enumerate(rows):
                text = " ".join(w["text"] for w in row_words)
                if is_region_end(text) and in_region:
                    break
                if is_region_start(text):
                    in_region = True
                fields_found = []
                for w in row_words:
                    field = map_header_field(w["text"])
                    if field:
                        fields_found.append((field, float(w["x0"]), float(w["x1"])))
                if len(fields_found) >= 2 and (
                    any(f[0] == "aciklama" for f in fields_found)
                    or any(f[0] == "miktar" for f in fields_found)
                ):
                    header_row_idx = ri
                    for field, x0, x1 in fields_found:
                        header_map[field] = (x0, x1)
                    in_region = True
                    break

            if header_row_idx is None or not header_map:
                continue

            def assign_field(x_mid: float) -> str | None:
                best_f = None
                best_d = 1e9
                for field, (x0, x1) in header_map.items():
                    mid = (x0 + x1) / 2
                    d = abs(x_mid - mid)
                    if x0 - 15 <= x_mid <= x1 + 15 and d < best_d:
                        best_d = d
                        best_f = field
                return best_f

            pending_desc = ""
            for row_words in rows[header_row_idx + 1 :]:
                text = " ".join(w["text"] for w in row_words)
                if is_region_end(text):
                    break
                bucket: dict[str, list[str]] = {}
                for w in row_words:
                    field = assign_field((float(w["x0"]) + float(w["x1"])) / 2)
                    if not field:
                        continue
                    bucket.setdefault(field, []).append(w["text"])
                data: dict[str, Any] = {}
                for field, parts in bucket.items():
                    joined = " ".join(parts).strip()
                    if field in {"miktar", "birim_fiyat", "kdv_orani", "kdv_tutari", "satir_toplam", "iskonto"}:
                        val = parse_decimal_tr(joined)
                        if field == "iskonto":
                            data["iskonto_orani"] = val
                        else:
                            data[field] = val
                    else:
                        data[field] = joined
                # Çok satırlı açıklama birleştirme
                has_qty = data.get("miktar") is not None
                has_price = data.get("birim_fiyat") is not None or data.get("satir_toplam") is not None
                if not has_qty and not has_price:
                    cont = data.get("aciklama") or text
                    if cont and pending_desc:
                        pending_desc = f"{pending_desc} {cont}".strip()
                    elif cont and all_lines:
                        all_lines[-1]["aciklama"] = f"{all_lines[-1].get('aciklama') or ''} {cont}".strip()
                        all_lines[-1]["description"] = all_lines[-1]["aciklama"]
                    continue
                if pending_desc:
                    data["aciklama"] = f"{pending_desc} {data.get('aciklama') or ''}".strip()
                    pending_desc = ""
                ok, reason = line_acceptable(data)
                if not ok:
                    _LOG.info("Koordinat satır red: %s | %s", text[:80], reason)
                    continue
                all_lines.append(
                    finalize_line(
                        data,
                        sira=len(all_lines) + 1,
                        method="pdf_coordinates",
                        page=page_number,
                        guven=Decimal("62"),
                    )
                )
    for i, line in enumerate(all_lines, start=1):
        line["sira"] = i
        line["line_number"] = i
    diag["line_count"] = len(all_lines)
    return all_lines, diag


def text_heuristic_lines(metin: str) -> list[dict[str, Any]]:
    """Düz metin yedek: miktar + birim + fiyat kalıpları (genel, tedarikçiye özel değil)."""
    if not metin:
        return []
    lines_out: list[dict[str, Any]] = []
    raw_lines = metin.splitlines()
    # Bölge kırp
    start = 0
    end = len(raw_lines)
    for i, ln in enumerate(raw_lines):
        if is_region_start(ln):
            start = i + 1
            break
    for i in range(start, len(raw_lines)):
        if is_region_end(raw_lines[i]):
            end = i
            break
    body = raw_lines[start:end]

    # Örnek: ... 10 Adet 1.250,00 20 12.500,00
    pat = re.compile(
        r"^(?P<acik>.+?)\s+(?P<mik>\d+(?:[.,]\d+)?)\s+(?P<birim>[A-Za-zÇĞİÖŞÜçğıöşü]{1,12})"
        r"\s+(?P<fiyat>\d{1,3}(?:[.,]\d{3})*[.,]\d{2}|\d+[.,]\d+|\d+)"
        r"(?:\s+(?P<kdv>%?\d{1,2}(?:[.,]\d+)?))?"
        r"(?:\s+(?P<toplam>\d{1,3}(?:[.,]\d{3})*[.,]\d{2}|\d+[.,]\d+|\d+))?\s*$"
    )
    pending = ""
    for ln in body:
        s = ln.strip()
        if not s or is_region_end(s):
            continue
        m = pat.match(s)
        if not m:
            # devam açıklama?
            if pending or (lines_out and not re.search(r"\d", s)):
                pending = f"{pending} {s}".strip() if pending else s
            continue
        acik = (pending + " " + m.group("acik")).strip() if pending else m.group("acik").strip()
        pending = ""
        data = {
            "aciklama": acik,
            "miktar": parse_decimal_tr(m.group("mik")),
            "birim": m.group("birim"),
            "birim_fiyat": parse_decimal_tr(m.group("fiyat")),
            "kdv_orani": parse_decimal_tr(m.group("kdv")) if m.group("kdv") else Decimal("20"),
            "satir_toplam": parse_decimal_tr(m.group("toplam")) if m.group("toplam") else None,
        }
        ok, reason = line_acceptable(data)
        if not ok:
            _LOG.info("Metin satır red: %s | %s", s[:80], reason)
            continue
        lines_out.append(
            finalize_line(data, sira=len(lines_out) + 1, method="pdf_text_heuristic", page=1, guven=Decimal("45"))
        )
    return lines_out
