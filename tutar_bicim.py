"""Tahsilat / ödeme evrakları — Türkçe tutar biçimi ve belirgin cari adı / tutar yazı tipleri.

Biçimleme yalnızca görüntüdür; kayda giden değer ``tutar_coz`` ile aynı Decimal'dir.
"""

from __future__ import annotations

import re
import tkinter as tk
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from satis_tema import font

KURUS = Decimal("0.01")
ISIM_PUNTO = 12
TUTAR_PUNTO = 15

_BINLIK_NOKTALI = re.compile(r"-?\d{1,3}(\.\d{3})+")


def tutar_coz(metin) -> Decimal:
    """'1.234.567,89', '1234,5', '1.234' (binlik), '300.00' (ondalık nokta) → Decimal."""
    if isinstance(metin, Decimal):
        return metin
    if isinstance(metin, (int, float)):
        return Decimal(str(metin))
    ham = str(metin or "").strip().replace(" ", "").replace("\u00a0", "")
    ham = re.sub(r"(?i)(tl|₺|try)$", "", ham)
    if not ham:
        raise ValueError("Tutar girilmelidir.")
    if "," in ham and "." in ham and ham.rfind(".") > ham.rfind(","):
        ham = ham.replace(",", "")
    elif "," in ham:
        ham = ham.replace(".", "").replace(",", ".")
    elif ham.count(".") > 1 or _BINLIK_NOKTALI.fullmatch(ham):
        ham = ham.replace(".", "")
    try:
        sonuc = Decimal(ham)
    except InvalidOperation:
        raise ValueError("Tutar geçerli bir sayı olmalıdır (ör. 1.234,50).") from None
    if not sonuc.is_finite():
        raise ValueError("Tutar geçerli bir sayı olmalıdır (ör. 1.234,50).")
    return sonuc


def tr_tutar(deger, *, birim: str = "") -> str:
    """Decimal → '1.234.567,89' (isteğe bağlı ' TL')."""
    d = Decimal(str(deger or 0)).quantize(KURUS, rounding=ROUND_HALF_UP)
    metin = f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{metin} {birim}" if birim else metin


def servis_metni(deger) -> str:
    """Virgül ondalıklı, binliksiz metin ('1234,50'); tüm tutar ayrıştırıcıları aynı sonucu verir."""
    d = tutar_coz(deger).quantize(KURUS, rounding=ROUND_HALF_UP)
    return f"{d:.2f}".replace(".", ",")


def isim_fontu(root: tk.Misc | None = None) -> tuple:
    return font(ISIM_PUNTO, "bold", root)


def baslik_isim_fontu(root: tk.Misc | None = None) -> tuple:
    """Evrak başlığındaki cari adı (etiket) — giriş alanlarından bir boy büyük."""
    return font(ISIM_PUNTO + 2, "bold", root)


def tutar_fontu(root: tk.Misc | None = None) -> tuple:
    return font(TUTAR_PUNTO, "bold", root)


def tutar_alani(entry: tk.Widget, var: tk.StringVar | None = None) -> None:
    """Tutar girişini büyük/koyu yapar; alan terk edilince Türkçe biçime çevirir."""
    try:
        entry.configure(font=tutar_fontu(entry), justify="right")
    except tk.TclError:
        pass

    def _bicimle(_e=None):
        metin = var.get() if var is not None else entry.get()
        if not str(metin).strip():
            return
        try:
            yeni = tr_tutar(tutar_coz(metin))
        except ValueError:
            return
        if yeni == metin:
            return
        if var is not None:
            var.set(yeni)
        else:
            durum = str(entry.cget("state"))
            if durum in ("readonly", "disabled"):
                return
            entry.delete(0, "end")
            entry.insert(0, yeni)

    entry.bind("<FocusOut>", _bicimle, add="+")
