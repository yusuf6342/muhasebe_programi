"""Fatura yazdırma ayarları — firma + kullanıcı bazlı."""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from typing import Any

from sqlalchemy import select

_LOG = logging.getLogger("invoice_print.settings")

DEFAULT_SETTINGS: dict[str, Any] = {
    "sablon_id": "kurumsal",
    "kagit": "A4",
    "yon": "dikey",
    "kopya": 1,
    "renkli": True,
    "logo_goster": True,
    "firma_bilgi_goster": True,
    "urun_kodu_goster": True,
    "aciklama_goster": True,
    "barkod_goster": False,
    "lot_goster": False,
    "kdv_dokum_goster": True,
    "banka_goster": True,
    "imza_alani_goster": True,
    "kase_goster": False,
    "yaziyla_toplam_goster": True,
    "tahsil_kalan_goster": True,
    "proje_goster": False,
    "alt_bilgi_goster": True,
    "taslak_filigran_goster": True,
    "ara_toplam_devri_goster": True,
    "satis_personeli_goster": False,
    "varsayilan_yazici": "",
    "son_pdf_klasoru": "",
    "ilk_sayfa_satir": 12,
    "sonraki_sayfa_satir": 22,
}


def _anahtar(company_id: int, user_id: int | None) -> str:
    u = int(user_id) if user_id else 0
    return f"fatura_yazdir_ayar_{int(company_id)}_{u}"


def load_print_settings(
    company_id: int | None = None, user_id: int | None = None
) -> dict[str, Any]:
    from database.session_manager import oturum
    from database.database import get_system_session
    from database.system.models import AppSetting

    cid = company_id or getattr(oturum, "company_id", None) or 0
    uid = user_id if user_id is not None else getattr(oturum, "user_id", None)
    ayar = deepcopy(DEFAULT_SETTINGS)
    if not cid:
        return ayar
    try:
        with get_system_session() as session:
            for key in (_anahtar(int(cid), uid), _anahtar(int(cid), None)):
                kayit = session.scalar(select(AppSetting).where(AppSetting.anahtar == key))
                if kayit and kayit.deger:
                    data = json.loads(kayit.deger)
                    if isinstance(data, dict):
                        ayar.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
                        break
    except Exception as exc:
        _LOG.warning("Yazdırma ayarları okunamadı: %s", exc)
    return ayar


def save_print_settings(
    settings: dict[str, Any],
    company_id: int | None = None,
    user_id: int | None = None,
) -> None:
    from database.session_manager import oturum
    from database.database import get_system_session
    from database.system.models import AppSetting

    cid = company_id or getattr(oturum, "company_id", None)
    uid = user_id if user_id is not None else getattr(oturum, "user_id", None)
    if not cid:
        return
    temiz = {k: settings.get(k, DEFAULT_SETTINGS[k]) for k in DEFAULT_SETTINGS}
    anahtar = _anahtar(int(cid), uid)
    with get_system_session() as session:
        kayit = session.scalar(select(AppSetting).where(AppSetting.anahtar == anahtar))
        metin = json.dumps(temiz, ensure_ascii=False)
        if kayit is None:
            session.add(AppSetting(anahtar=anahtar, deger=metin))
        else:
            kayit.deger = metin
        session.commit()


def reset_print_settings(
    company_id: int | None = None, user_id: int | None = None
) -> dict[str, Any]:
    ayar = deepcopy(DEFAULT_SETTINGS)
    save_print_settings(ayar, company_id=company_id, user_id=user_id)
    return ayar
