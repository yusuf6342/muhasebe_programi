"""Tkinter UI'yi dondurmadan arka planda iş çalıştırma."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any


def arka_planda(
    widget,
    is_fn: Callable[[], Any],
    on_ok: Callable[[Any], None] | None = None,
    on_err: Callable[[BaseException], None] | None = None,
) -> None:
    """is_fn'i daemon thread'de çalıştır; sonucu widget.after ile ana threade taşı."""

    def _calistir() -> None:
        try:
            sonuc = is_fn()
        except BaseException as exc:  # noqa: BLE001
            if on_err is not None:
                widget.after(0, lambda e=exc: on_err(e))
            return
        if on_ok is not None:
            widget.after(0, lambda s=sonuc: on_ok(s))

    threading.Thread(target=_calistir, daemon=True).start()


def ui_guncelle(widget, fn: Callable[[], None]) -> None:
    """Worker thread içinden güvenli UI güncellemesi."""
    widget.after(0, fn)
