"""Tkinter UI'yi dondurmadan arka planda iş çalıştırma."""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any


def arka_planda(
    widget,
    is_fn: Callable[[], Any],
    on_ok: Callable[[Any], None] | None = None,
    on_err: Callable[[BaseException], None] | None = None,
) -> None:
    """is_fn'i daemon thread'de çalıştır; sonucu ana thread'de uygula.

    Tk `after` başka thread'den güvenilir değil (özellikle mainloop henüz
    yokken «main thread is not in main loop»). Bu yüzden sonuçlar kuyruğa
    yazılır; `after` yalnızca ana thread'den (arka_planda çağrısı / poll) planlanır.
    """

    if widget is None:
        return

    q: queue.SimpleQueue = getattr(widget, "_ui_bg_q", None)
    if q is None:
        q = queue.SimpleQueue()
        widget._ui_bg_q = q
        widget._ui_bg_pending = 0

    def _drain() -> None:
        try:
            if not widget.winfo_exists():
                return
        except Exception:
            return
        while True:
            try:
                kind, cb, payload = q.get_nowait()
            except queue.Empty:
                break
            try:
                widget._ui_bg_pending = max(0, int(getattr(widget, "_ui_bg_pending", 0)) - 1)
            except Exception:
                pass
            if cb is None:
                continue
            try:
                if kind == "ok":
                    cb(payload)
                else:
                    cb(payload)
            except Exception:
                # UI callback hatası kartı düşürmesin
                pass
        try:
            if int(getattr(widget, "_ui_bg_pending", 0)) > 0 and widget.winfo_exists():
                widget.after(15, _drain)
        except Exception:
            return

    def _poll_baslat() -> None:
        try:
            if not widget.winfo_exists():
                return
            widget.after(15, _drain)
        except Exception:
            return

    # İlk planlama ana thread'de (arka_planda UI'dan çağrılır)
    try:
        widget._ui_bg_pending = int(getattr(widget, "_ui_bg_pending", 0)) + 1
    except Exception:
        pass
    _poll_baslat()

    def _calistir() -> None:
        try:
            sonuc = is_fn()
        except BaseException as exc:  # noqa: BLE001
            q.put(("err", on_err, exc))
        else:
            q.put(("ok", on_ok, sonuc))
        # Worker yalnızca kuyruğa yazar; after'ı ana thread poll zaten sürdürür.
        # Ek kick: bazı ortamlarda idle gecikir — try/except ile dene.
        try:
            if widget.winfo_exists():
                widget.after(0, _drain)
        except Exception:
            pass

    threading.Thread(target=_calistir, daemon=True).start()


def ui_guncelle(widget, fn: Callable[[], None]) -> None:
    """Worker thread içinden güvenli UI güncellemesi."""

    def _guvenli() -> None:
        try:
            if widget is not None and widget.winfo_exists():
                fn()
        except Exception:
            return

    try:
        if widget is not None and widget.winfo_exists():
            widget.after(0, _guvenli)
            return
    except Exception:
        pass
    # after reddedilirse arka_planda kuyruğuna bırak
    arka_planda(widget, lambda: True, on_ok=lambda _r: _guvenli())
