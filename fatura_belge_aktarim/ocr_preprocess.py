"""OCR öncesi görüntü iyileştirme (OpenCV). Orijinal dosya değiştirilmez."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

_LOG = logging.getLogger("fatura_belge_aktarim.ocr_preprocess")


def _pil_to_cv(image: Any) -> np.ndarray:
    from PIL import Image

    if isinstance(image, Image.Image):
        rgb = image.convert("RGB")
        arr = np.array(rgb)
        import cv2

        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    return image


def _cv_to_pil(bgr: np.ndarray) -> Any:
    import cv2
    from PIL import Image

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def detect_and_rotate(bgr: np.ndarray) -> np.ndarray:
    """OSD ile yön düzelt (osd yoksa dokunma)."""
    try:
        import cv2
        import pytesseract
        from fatura_belge_aktarim.ocr_config import configure_pytesseract

        if not configure_pytesseract():
            return bgr
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        from PIL import Image

        osd = pytesseract.image_to_osd(Image.fromarray(rgb))
        angle = 0
        for line in osd.splitlines():
            if "Rotate:" in line:
                angle = int(line.split(":")[-1].strip())
                break
        if angle in (90, 180, 270):
            if angle == 90:
                bgr = cv2.rotate(bgr, cv2.ROTATE_90_CLOCKWISE)
            elif angle == 180:
                bgr = cv2.rotate(bgr, cv2.ROTATE_180)
            elif angle == 270:
                bgr = cv2.rotate(bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
            _LOG.info("OSD döndürme=%s", angle)
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("OSD atlandı: %s", exc)
    return bgr


def deskew(bgr: np.ndarray) -> np.ndarray:
    try:
        import cv2

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.bitwise_not(gray)
        coords = np.column_stack(np.where(gray > 0))
        if coords.size < 100:
            return bgr
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        if abs(angle) < 0.3 or abs(angle) > 15:
            return bgr
        (h, w) = bgr.shape[:2]
        m = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
        return cv2.warpAffine(bgr, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("Deskew atlandı: %s", exc)
        return bgr


def preprocess_for_ocr(image: Any) -> Any:
    """
    PIL Image veya BGR ndarray alır; OCR için işlenmiş PIL Image döndürür.
    Orijinal nesne değiştirilmez.
    """
    try:
        import cv2
    except ImportError:
        _LOG.warning("OpenCV yok; basit gri tonlama")
        from PIL import Image, ImageEnhance, ImageOps

        if not hasattr(image, "convert"):
            return image
        gray = ImageOps.grayscale(image.copy())
        gray = ImageOps.autocontrast(gray)
        return ImageEnhance.Contrast(gray).enhance(1.5)

    bgr = _pil_to_cv(image).copy()
    h, w = bgr.shape[:2]
    # Çok düşük çözünürlük büyüt
    if min(h, w) < 1000:
        scale = 1000 / max(1, min(h, w))
        bgr = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    bgr = detect_and_rotate(bgr)
    bgr = deskew(bgr)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    # Adaptif eşik — fatura için soft binary
    thr = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
    )
    # Kenar kırpma (çok koyu kenar)
    coords = cv2.findNonZero(255 - thr)
    if coords is not None:
        x, y, bw, bh = cv2.boundingRect(coords)
        pad = 8
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(thr.shape[1], x + bw + pad), min(thr.shape[0], y + bh + pad)
        if (x1 - x0) > 100 and (y1 - y0) > 100:
            thr = thr[y0:y1, x0:x1]
    return _cv_to_pil(cv2.cvtColor(thr, cv2.COLOR_GRAY2BGR))
