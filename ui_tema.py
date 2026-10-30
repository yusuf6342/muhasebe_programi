"""Kullanıcıya özel hazır renk temaları — merkezi palet ve uygulama.

Gece teması altyapıda tanımlı ama ilk aşamada seçim listesinde yok.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Teknik kimlikler sabit; görünen ad değişebilir
TEMA_KLASIK = "klasik"
TEMA_FERAH = "ferah"
TEMA_MODERN = "modern"
TEMA_SADE = "sade"
TEMA_GECE = "gece"  # 2. aşama — seçim listesinde yok

# Mevcut programdan türetilen Klasik (örnek HEX’e zorlanmaz)
_KLASIK = {
    "LACIVERT": "#102A43",
    "KOYU_LACIVERT": "#081B2C",
    "LACIVERT_HOVER": "#1A3A56",
    "SARI": "#F4C542",
    "SARI_HOVER": "#FFE89A",
    "ACIK_BG": "#F3F6F9",
    "BEYAZ": "#FFFFFF",
    "METIN": "#172B4D",
    "METIN_ACIK": "#E8EEF4",
    "PASIF": "#627D98",
    "IKINCIL": "#627D98",
    "CIZGI": "#D9E2EC",
    "BASARI": "#1F9D74",
    "UYARI": "#D64545",
    "KART_GOLEGE": "#E2E8EE",
}

_FERAH = {
    **_KLASIK,
    "LACIVERT": "#183E63",
    "KOYU_LACIVERT": "#102A43",
    "LACIVERT_HOVER": "#21507A",
    "SARI": "#D5EAFE",
    "SARI_HOVER": "#E8F3FE",
    "ACIK_BG": "#F2F6FB",
    "METIN": "#23364B",
    "METIN_ACIK": "#F5F8FF",
    "PASIF": "#475E77",
    "IKINCIL": "#475E77",
    "CIZGI": "#C9D7E6",
    "KART_GOLEGE": "#EAF2FA",
}

_MODERN = {
    **_KLASIK,
    "LACIVERT": "#27333D",
    "KOYU_LACIVERT": "#1A2229",
    "LACIVERT_HOVER": "#344550",
    "SARI": "#6FE1CB",
    "SARI_HOVER": "#A5EDDE",
    "ACIK_BG": "#F1F6F5",
    "METIN": "#253C37",
    "METIN_ACIK": "#F5F8FF",
    "PASIF": "#49615A",
    "IKINCIL": "#49615A",
    "CIZGI": "#C6D7D2",
    "KART_GOLEGE": "#E7F2EF",
}

_SADE = {
    **_KLASIK,
    "LACIVERT": "#164D51",
    "KOYU_LACIVERT": "#0E3437",
    "LACIVERT_HOVER": "#1E6368",
    "SARI": "#E8D9B9",
    "SARI_HOVER": "#F2E9D4",
    "ACIK_BG": "#F6F4EF",
    "BEYAZ": "#FFFEFA",
    "METIN": "#2B3937",
    "METIN_ACIK": "#F5F8FF",
    "PASIF": "#555F58",
    "IKINCIL": "#555F58",
    "CIZGI": "#D6D7C9",
    "KART_GOLEGE": "#EFEEE5",
}

_GECE = {
    **_KLASIK,
    "LACIVERT": "#101A2B",
    "KOYU_LACIVERT": "#0A101C",
    "LACIVERT_HOVER": "#1A2740",
    "SARI": "#F4C542",
    "ACIK_BG": "#131F31",
    "BEYAZ": "#1A283C",
    "METIN": "#E8EEF4",
    "METIN_ACIK": "#E8EEF4",
    "PASIF": "#8BA3BD",
    "IKINCIL": "#8BA3BD",
    "CIZGI": "#2A3A50",
}

TEMALAR: dict[str, dict[str, Any]] = {
    TEMA_KLASIK: {"id": TEMA_KLASIK, "ad": "Klasik", "asama": 1, "renkler": _KLASIK},
    TEMA_FERAH: {"id": TEMA_FERAH, "ad": "Ferah", "asama": 1, "renkler": _FERAH},
    TEMA_MODERN: {"id": TEMA_MODERN, "ad": "Modern", "asama": 1, "renkler": _MODERN},
    TEMA_SADE: {"id": TEMA_SADE, "ad": "Sade", "asama": 1, "renkler": _SADE},
    TEMA_GECE: {"id": TEMA_GECE, "ad": "Gece", "asama": 2, "renkler": _GECE},
}

_AKTIF_ID = TEMA_KLASIK
_PREF_SURUM = 1

_HEDEF_MODULLER = (
    "ana_panel_tema",
    "ana_panel_ui",
    "fatura_tema",
    "satis_tema",
    "stok_kart_tema",
    "cari_kart_tema",
    "siparis_tema",
    "firma_secim_theme",
)


def etkin_temalar() -> list[dict[str, Any]]:
    """İlk aşama seçim listesi — gece yok."""
    return [dict(t) for t in TEMALAR.values() if int(t.get("asama") or 1) == 1]


def tema_getir(tema_id: str | None) -> dict[str, Any]:
    tid = (tema_id or TEMA_KLASIK).strip().lower()
    t = TEMALAR.get(tid)
    if t is None or int(t.get("asama") or 1) > 1:
        return TEMALAR[TEMA_KLASIK]
    return t


def aktif_tema_id() -> str:
    return _AKTIF_ID


def aktif_palet() -> dict[str, str]:
    return dict(tema_getir(_AKTIF_ID)["renkler"])


def _tercih_yolu(user_id: int | None) -> Path:
    from database.database import DB_DIR

    uid = int(user_id or 0)
    return Path(DB_DIR) / "kullanici_tercihleri" / f"tema_u{uid}.json"


def tercih_oku(user_id: int | None) -> str:
    yol = _tercih_yolu(user_id)
    try:
        if not yol.is_file():
            return TEMA_KLASIK
        veri = json.loads(yol.read_text(encoding="utf-8"))
        tid = str(veri.get("tema_id") or TEMA_KLASIK)
        if tid not in TEMALAR or int(TEMALAR[tid].get("asama") or 1) > 1:
            return TEMA_KLASIK
        return tid
    except Exception:
        return TEMA_KLASIK


def tercih_yaz(user_id: int | None, tema_id: str) -> None:
    tid = tema_getir(tema_id)["id"]
    yol = _tercih_yolu(user_id)
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(
        json.dumps({"tema_id": tid, "surum": _PREF_SURUM}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _modullere_uygula(renkler: dict[str, str]) -> None:
    for ad in _HEDEF_MODULLER:
        mod = sys.modules.get(ad)
        if mod is None:
            try:
                __import__(ad)
                mod = sys.modules.get(ad)
            except Exception:
                continue
        if mod is None:
            continue
        for k, v in renkler.items():
            if hasattr(mod, k):
                setattr(mod, k, v)
        # fatura_tema ek eşlemeler
        if ad == "fatura_tema":
            if hasattr(mod, "LACIVERT_ORTA") and "LACIVERT_HOVER" in renkler:
                setattr(mod, "LACIVERT_ORTA", renkler.get("LACIVERT_HOVER", renkler["LACIVERT"]))
            if hasattr(mod, "SECIM") and "SARI" in renkler:
                setattr(mod, "SECIM", renkler["SARI"])


def uygula(tema_id: str | None, *, root=None) -> str:
    """Temayı bellek + açık stil kaynaklarına uygular. Geçersiz id → klasik."""
    global _AKTIF_ID
    t = tema_getir(tema_id)
    _AKTIF_ID = t["id"]
    _modullere_uygula(t["renkler"])
    if root is not None:
        try:
            from ana_panel_tema import stil_uygula
            from tkinter import ttk

            stil_uygula(ttk.Style(root))
        except Exception:
            pass
        try:
            kabuk = getattr(root, "_ana_panel_kabuk", None)
            if kabuk is not None and hasattr(kabuk, "tema_yenile"):
                kabuk.tema_yenile()
            elif kabuk is not None and hasattr(kabuk, "_menu_renklerini_yenile"):
                kabuk._menu_renklerini_yenile()
        except Exception:
            pass
    return _AKTIF_ID


def oturum_temasini_yukle(root=None) -> str:
    """Oturum açılışında bir kez — stok kartı her açılışta DB okumaz."""
    from database.session_manager import oturum

    tid = tercih_oku(oturum.user_id)
    return uygula(tid, root=root)
