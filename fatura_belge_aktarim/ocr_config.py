"""Tesseract OCR yapılandırması — bilgisayar/uygulama ayarı (firma bağımsız)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("fatura_belge_aktarim.ocr_config")

DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
DEFAULT_TESSERACT_X86 = r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
OCR_LANG = "tur+eng"
KULLANICI_OCR_HATASI = (
    "Fatura OCR işlemi tamamlanamadı. Belge kaydedilmedi.\n"
    "OCR ayarlarını kontrol edip yeniden deneyebilirsiniz."
)


def _ayar_dosyasi() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MuhasebeProgrami" / "ayarlar"
    base.mkdir(parents=True, exist_ok=True)
    return base / "ocr_ayarlar.json"


def ocr_ayarlari_yukle() -> dict[str, Any]:
    yol = _ayar_dosyasi()
    varsayilan: dict[str, Any] = {
        "tesseract_path": None,
        "lang": OCR_LANG,
        "son_test_zamani": None,
        "son_test_sonucu": None,
    }
    if not yol.exists():
        return dict(varsayilan)
    try:
        veri = json.loads(yol.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(varsayilan)
    if not isinstance(veri, dict):
        return dict(varsayilan)
    out = dict(varsayilan)
    out.update({k: veri.get(k, varsayilan[k]) for k in varsayilan})
    return out


def ocr_ayarlari_kaydet(ayarlar: dict[str, Any]) -> None:
    mevcut = ocr_ayarlari_yukle()
    mevcut.update({k: v for k, v in (ayarlar or {}).items() if k in mevcut or k in ayarlar})
    _ayar_dosyasi().write_text(
        json.dumps(mevcut, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_ocr_setting(key: str, default: Any = None) -> Any:
    return ocr_ayarlari_yukle().get(key, default)


def set_tesseract_path(path: str | None) -> None:
    ocr_ayarlari_kaydet({"tesseract_path": path or None})


def find_tesseract() -> str | None:
    configured = get_ocr_setting("tesseract_path")
    candidates = [
        configured,
        os.environ.get("TESSERACT_CMD"),
        shutil.which("tesseract"),
        DEFAULT_TESSERACT,
        DEFAULT_TESSERACT_X86,
    ]
    for path in candidates:
        if path and os.path.isfile(str(path)):
            return str(path)
    return None


def configure_pytesseract() -> str | None:
    """pytesseract.tesseract_cmd ayarla; yol yoksa None (program kapanmaz)."""
    path = find_tesseract()
    if not path:
        return None
    try:
        import pytesseract

        pytesseract.pytesseract.tesseract_cmd = path
    except ImportError:
        _LOG.warning("pytesseract paketi yok")
        return path
    return path


def tesseract_version(path: str | None = None) -> str | None:
    exe = path or find_tesseract()
    if not exe:
        return None
    try:
        r = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        out = (r.stdout or r.stderr or "").strip().splitlines()
        return out[0] if out else None
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("Tesseract sürüm okunamadı: %s", exc)
        return None


def list_tesseract_languages(path: str | None = None) -> list[str]:
    exe = path or find_tesseract()
    if not exe:
        return []
    try:
        r = subprocess.run(
            [exe, "--list-langs"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        lines = (r.stdout or r.stderr or "").splitlines()
        langs: list[str] = []
        for ln in lines:
            s = ln.strip()
            if not s or s.lower().startswith("list of") or s.lower().startswith("available"):
                continue
            langs.append(s)
        return langs
    except Exception as exc:  # noqa: BLE001
        _LOG.debug("Dil listesi alınamadı: %s", exc)
        return []


def ocr_durum_raporu() -> dict[str, Any]:
    """Servis ekranı için durum özeti."""
    ayar = ocr_ayarlari_yukle()
    path = find_tesseract()
    langs = list_tesseract_languages(path) if path else []
    ver = tesseract_version(path) if path else None
    return {
        "bulundu": bool(path),
        "tesseract_path": path,
        "version": ver,
        "languages": langs,
        "tur": "tur" in langs,
        "eng": "eng" in langs,
        "osd": "osd" in langs,
        "lang_default": ayar.get("lang") or OCR_LANG,
        "configured_path": ayar.get("tesseract_path"),
        "son_test_zamani": ayar.get("son_test_zamani"),
        "son_test_sonucu": ayar.get("son_test_sonucu"),
        "pytesseract_ok": _pytesseract_import_ok(),
        "opencv_ok": _pkg_ok("cv2"),
        "pymupdf_ok": _pkg_ok("fitz"),
        "pillow_ok": _pkg_ok("PIL"),
    }


def _pkg_ok(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _pytesseract_import_ok() -> bool:
    try:
        import pytesseract  # noqa: F401

        return True
    except ImportError:
        return False


def tesseract_test_et() -> dict[str, Any]:
    """Basit OCR duman testi; sonucu ayarlara yazar."""
    from PIL import Image, ImageDraw, ImageFont

    path = configure_pytesseract()
    sonuc: dict[str, Any] = {
        "ok": False,
        "mesaj": "",
        "path": path,
        "version": tesseract_version(path),
        "languages": list_tesseract_languages(path),
    }
    if not path:
        sonuc["mesaj"] = "Tesseract bulunamadı."
        ocr_ayarlari_kaydet(
            {
                "son_test_zamani": datetime.now().isoformat(timespec="seconds"),
                "son_test_sonucu": sonuc["mesaj"],
            }
        )
        return sonuc
    try:
        import pytesseract

        img = Image.new("RGB", (420, 80), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((10, 25), "Fatura Test 1.250,00 TL", fill=(0, 0, 0))
        text = pytesseract.image_to_string(img, lang="eng", config="--oem 3 --psm 7")
        ok = bool((text or "").strip())
        sonuc["ok"] = ok
        sonuc["ocr_text"] = (text or "").strip()[:200]
        sonuc["mesaj"] = "OCR testi başarılı." if ok else "OCR çıktı üretmedi."
    except Exception as exc:  # noqa: BLE001
        _LOG.exception("OCR test hatası")
        sonuc["mesaj"] = f"OCR test başarısız: {type(exc).__name__}"
    ocr_ayarlari_kaydet(
        {
            "son_test_zamani": datetime.now().isoformat(timespec="seconds"),
            "son_test_sonucu": sonuc["mesaj"],
        }
    )
    return sonuc
