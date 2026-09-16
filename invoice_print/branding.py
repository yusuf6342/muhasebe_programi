"""Firma markası / logo — aktif Company kaydından."""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select

_LOG = logging.getLogger("invoice_print.branding")


def _ayar_anahtar(company_id: int) -> str:
    return f"fatura_branding_{int(company_id)}"


def load_company_branding(company_id: int | None = None) -> dict[str, Any]:
    """Aktif (veya verilen) firmanın baskı markasını döndürür."""
    from database.session_manager import oturum
    from database.database import get_system_session
    from database.system.models import AppSetting, Company

    cid = company_id
    if cid is None:
        cid = getattr(oturum, "company_id", None)
    sonuc: dict[str, Any] = {
        "company_id": cid,
        "unvan": getattr(oturum, "firma_unvan", None) or "",
        "kisa_ad": "",
        "firma_kodu": getattr(oturum, "firma_kodu", None) or "",
        "adres": "",
        "ilce": "",
        "il": "",
        "telefon": "",
        "email": "",
        "web": "",
        "vergi_dairesi": "",
        "vergi_no": "",
        "mersis": "",
        "ticaret_sicil": "",
        "ibanlar": [],
        "alt_bilgi": "",
        "yetkili": "",
        "logo_yolu": None,
        "kase_yolu": None,
    }
    if not cid:
        return sonuc
    try:
        with get_system_session() as session:
            c = session.get(Company, int(cid))
            if c is not None:
                sonuc.update(
                    {
                        "unvan": c.unvan or sonuc["unvan"],
                        "kisa_ad": c.kisa_ad or "",
                        "firma_kodu": c.firma_kodu or "",
                        "adres": c.adres or "",
                        "ilce": c.ilce or "",
                        "il": c.il or "",
                        "telefon": c.telefon or "",
                        "email": c.email or "",
                        "web": c.internet or "",
                        "vergi_dairesi": c.vergi_dairesi or "",
                        "vergi_no": c.vergi_no or "",
                        "logo_yolu": c.logo_yolu,
                    }
                )
            ekstra = session.scalar(
                select(AppSetting).where(AppSetting.anahtar == _ayar_anahtar(int(cid)))
            )
            if ekstra and ekstra.deger:
                try:
                    data = json.loads(ekstra.deger)
                    if isinstance(data, dict):
                        for k in (
                            "mersis",
                            "ticaret_sicil",
                            "ibanlar",
                            "alt_bilgi",
                            "yetkili",
                            "kase_yolu",
                        ):
                            if k in data and data[k] not in (None, ""):
                                sonuc[k] = data[k]
                except json.JSONDecodeError:
                    pass
    except Exception as exc:
        _LOG.exception("Firma markası yüklenemedi: %s", exc)
    return sonuc


def logo_data_uri(logo_yolu: str | None, *, max_kenar_px: int = 480) -> str | None:
    """PNG/JPG → data URI; yoksa veya hata varsa None (program kapanmaz)."""
    if not logo_yolu:
        return None
    yol = Path(logo_yolu)
    if not yol.is_file():
        return None
    try:
        from PIL import Image
        import io

        with Image.open(yol) as im:
            im = im.convert("RGBA") if im.mode in ("P", "RGBA") else im.convert("RGB")
            im.thumbnail((max_kenar_px, max_kenar_px), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            fmt = "PNG" if im.mode == "RGBA" else "JPEG"
            im.save(buf, format=fmt, optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            mime = "image/png" if fmt == "PNG" else "image/jpeg"
            return f"data:{mime};base64,{b64}"
    except Exception as exc:
        _LOG.warning("Logo okunamadı (%s): %s", logo_yolu, exc)
        return None


def save_branding_extras(company_id: int, extras: dict[str, Any]) -> None:
    from database.database import get_system_session
    from database.system.models import AppSetting
    from sqlalchemy import select

    anahtar = _ayar_anahtar(int(company_id))
    with get_system_session() as session:
        kayit = session.scalar(select(AppSetting).where(AppSetting.anahtar == anahtar))
        metin = json.dumps(extras, ensure_ascii=False)
        if kayit is None:
            session.add(AppSetting(anahtar=anahtar, deger=metin))
        else:
            kayit.deger = metin
        session.commit()
