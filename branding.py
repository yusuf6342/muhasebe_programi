"""Cin Muhasebe — marka sabitleri, kaynak yolları, ikon ve splash yardımcıları."""

from __future__ import annotations

import logging
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable

APP_NAME = "Cin Muhasebe"
APP_NAME_COMPACT = "CinMuhasebe"
APP_TAGLINE = "Güvenli ve Düzenli İşletme Yönetimi"
APP_VERSION = "1.0.0"
APP_USER_MODEL_ID = "CinMuhasebe.Desktop"
APP_DESCRIPTION = "Cin Muhasebe Programı"

BRANDING_REL = Path("assets") / "branding"
# Küçük uygulama logosu — iconphoto (ana / alt pencereler)
APP_ICON_PNG = "CinLogo.png"
# Açılış (splash) ekranı görseli
SPLASH_FILE = "CinAcilis.png"
# Giriş / Hakkında yedek geniş görsel
LOGO_FILE = "CinAcilis.png"
# Windows EXE / görev çubuğu / kısayol
ICO_FILE = "CinLogo.ico"
ICO_FILE_LEGACY = "cin_muhasebe.ico"

# Sarı / lacivert kurumsal palet
COLOR_NAVY = "#0B1F3A"
COLOR_NAVY_SOFT = "#13294B"
COLOR_GOLD = "#F5C518"
COLOR_GOLD_DIM = "#D4A017"
COLOR_BG = "#F7F4EC"
COLOR_TEXT = "#0B1F3A"
COLOR_MUTED = "#4A5568"

_log = logging.getLogger("cin_muhasebe.branding")
_image_cache: dict[str, tk.PhotoImage] = {}
_toplevel_hook_installed = False


def project_root() -> Path:
    """Kaynak veya PyInstaller ortamında proje / paket kökünü döndürür."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def resource_path(relative_path: str | Path) -> Path:
    """
    Göreli kaynak yolunu mutlak Path'e çevirir.
    os.getcwd()'e güvenmez; PyInstaller _MEIPASS ve kaynak kökünü destekler.
    """
    rel = Path(relative_path)
    if rel.is_absolute():
        return rel
    return project_root() / rel


def branding_path(filename: str) -> Path:
    return resource_path(BRANDING_REL / filename)


def resource_exists(relative_path: str | Path) -> bool:
    yol = resource_path(relative_path)
    return yol.is_file()


def setup_branding_logging() -> None:
    """Teknik log: konsol + isteğe bağlı dosya."""
    if _log.handlers:
        return
    _log.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    _log.addHandler(handler)
    try:
        log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CinMuhasebe" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_dir / "branding.log", encoding="utf-8")
        fh.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        _log.addHandler(fh)
    except OSError:
        pass


def set_windows_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> None:
    """Windows görev çubuğu kimliği — pencere oluşmadan önce çağrılmalı."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 — açılışı engelleme
        _log.warning("AppUserModelID ayarlanamadı: %s", exc)


def _load_photoimage(path: Path, *, cache_key: str | None = None) -> tk.PhotoImage | None:
    key = cache_key or str(path)
    cached = _image_cache.get(key)
    if cached is not None:
        return cached
    if not path.is_file():
        _log.error("Görsel bulunamadı: %s", path)
        return None
    try:
        img = tk.PhotoImage(file=str(path))
    except tk.TclError as exc:
        _log.error("Görsel yüklenemedi (%s): %s", path, exc)
        return None
    _image_cache[key] = img
    return img


def get_brand_image(
    filename: str,
    *,
    max_width: int | None = None,
    max_height: int | None = None,
) -> tk.PhotoImage | None:
    """
    Branding PNG yükler; en-boy oranını koruyarak küçültür (esnetme/kırpma yok).
    Mümkünse Pillow ile yüksek kaliteli ölçek; yoksa PhotoImage subsample.
    """
    path = branding_path(filename)
    if not path.is_file():
        _log.error("Logo/ikon dosyası yok: %s", path.resolve())
        return None

    cache_key = f"{path}|{max_width}x{max_height}"
    if cache_key in _image_cache:
        return _image_cache[cache_key]

    # Yüksek kaliteli oran korumalı ölçek (opsiyonel Pillow)
    if max_width or max_height:
        try:
            from PIL import Image, ImageTk  # type: ignore

            with Image.open(path) as im:
                im = im.convert("RGBA")
                w, h = im.size
                scale = 1.0
                if max_width and w > max_width:
                    scale = min(scale, max_width / w)
                if max_height and h > max_height:
                    scale = min(scale, max_height / h)
                if scale < 1.0:
                    nw = max(1, int(round(w * scale)))
                    nh = max(1, int(round(h * scale)))
                    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(im)
            _image_cache[cache_key] = photo
            return photo
        except Exception as exc:  # noqa: BLE001 — Pillow yoksa subsample
            _log.debug("Pillow ölçek kullanılamadı, subsample: %s", exc)

    img = _load_photoimage(path, cache_key=str(path))
    if img is None:
        return None

    if max_width or max_height:
        w, h = img.width(), img.height()
        scale = 1.0
        if max_width and w > max_width:
            scale = min(scale, max_width / w)
        if max_height and h > max_height:
            scale = min(scale, max_height / h)
        if scale < 1.0:
            factor = max(1, int(round(1.0 / scale)))
            try:
                img = img.subsample(factor, factor)
            except tk.TclError as exc:
                _log.warning("Logo ölçeklenemedi, orijinal kullanılacak: %s", exc)
            else:
                _image_cache[cache_key] = img
                return img

    _image_cache[cache_key] = img
    return img


def resolve_ico_path() -> Path | None:
    """EXE/kısayol için ICO; PNG EXE icon alanında kullanılmaz."""
    for name in (ICO_FILE, ICO_FILE_LEGACY):
        yol = branding_path(name)
        if yol.is_file():
            return yol
    return None


def apply_window_icon(window: tk.Misc) -> None:
    """Ana/alt pencere: Windows'ta CinLogo.ico (iconbitmap) + CinLogo.png (iconphoto)."""
    ico = resolve_ico_path()
    png = branding_path(APP_ICON_PNG)

    try:
        if ico is not None and sys.platform == "win32":
            try:
                window.iconbitmap(default=str(ico))  # type: ignore[attr-defined]
            except tk.TclError:
                try:
                    window.iconbitmap(str(ico))  # type: ignore[attr-defined]
                except tk.TclError as exc:
                    _log.warning("iconbitmap başarısız: %s", exc)
        elif ico is not None:
            try:
                window.iconbitmap(str(ico))  # type: ignore[attr-defined]
            except tk.TclError as exc:
                _log.warning("iconbitmap başarısız: %s", exc)
        else:
            _log.warning("ICO yok: %s — yalnızca PNG iconphoto denenecek.", ICO_FILE)
    except Exception as exc:  # noqa: BLE001
        _log.warning("ICO ikon atanamadı: %s", exc)

    photo = get_brand_image(APP_ICON_PNG) if png.is_file() else None
    if photo is None:
        _log.error(
            "Uygulama ikonu yok: %s — pencere logosuz açılacak.",
            png.resolve(),
        )
        return
    try:
        window.iconphoto(True, photo)  # type: ignore[attr-defined]
        refs = getattr(window, "_cin_icon_refs", None)
        if refs is None:
            refs = []
            setattr(window, "_cin_icon_refs", refs)
        refs.append(photo)
    except tk.TclError as exc:
        _log.warning("iconphoto başarısız: %s", exc)


def install_toplevel_icon_hook() -> None:
    """Yeni Toplevel pencerelerine otomatik ikon uygular (tek seferlik)."""
    global _toplevel_hook_installed
    if _toplevel_hook_installed:
        return
    original_init = tk.Toplevel.__init__

    def _patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        try:
            apply_window_icon(self)
        except Exception as exc:  # noqa: BLE001
            _log.debug("Toplevel ikon kancası: %s", exc)

    tk.Toplevel.__init__ = _patched_init  # type: ignore[method-assign]
    _toplevel_hook_installed = True


class SplashScreen(tk.Toplevel):
    """Çerçevesiz açılış ekranı — sarı/lacivert, gerçek başlatma ile ilerler."""

    def __init__(self, master: tk.Tk):
        super().__init__(master)
        self.overrideredirect(True)
        self.configure(bg=COLOR_BG)
        self.attributes("-topmost", True)
        try:
            self.tk.call("tk", "scaling", self.winfo_fpixels("1i") / 72.0)
        except tk.TclError:
            pass

        dis_w = self.winfo_screenwidth()
        dis_h = self.winfo_screenheight()
        # DPI-dostu mantıksal boyut
        width = min(520, max(420, int(dis_w * 0.32)))
        height = min(420, max(340, int(dis_h * 0.38)))
        x = max(0, (dis_w - width) // 2)
        y = max(0, (dis_h - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

        border = tk.Frame(self, bg=COLOR_NAVY, bd=0)
        border.pack(fill="both", expand=True, padx=2, pady=2)
        inner = tk.Frame(border, bg=COLOR_BG)
        inner.pack(fill="both", expand=True, padx=2, pady=2)

        ust_serit = tk.Frame(inner, bg=COLOR_NAVY, height=8)
        ust_serit.pack(fill="x")
        tk.Frame(inner, bg=COLOR_GOLD, height=4).pack(fill="x")

        govde = tk.Frame(inner, bg=COLOR_BG)
        govde.pack(fill="both", expand=True, padx=28, pady=20)

        self._logo_ref: tk.PhotoImage | None = None
        # Splash: CinAcilis.png — oran korunur, esnetme/kırpma yok
        logo = get_brand_image(SPLASH_FILE, max_width=width - 64, max_height=int(height * 0.42))
        if logo is None:
            logo = get_brand_image(APP_ICON_PNG, max_width=width - 80, max_height=160)
        if logo is not None:
            self._logo_ref = logo
            tk.Label(govde, image=logo, bg=COLOR_BG).pack(pady=(8, 12))
        else:
            tk.Label(
                govde,
                text=APP_NAME,
                font=("Segoe UI", 22, "bold"),
                fg=COLOR_NAVY,
                bg=COLOR_BG,
            ).pack(pady=(24, 8))

        tk.Label(
            govde,
            text=APP_NAME,
            font=("Segoe UI", 18, "bold"),
            fg=COLOR_NAVY,
            bg=COLOR_BG,
        ).pack()
        tk.Label(
            govde,
            text=APP_TAGLINE,
            font=("Segoe UI", 10),
            fg=COLOR_MUTED,
            bg=COLOR_BG,
        ).pack(pady=(4, 16))

        self._status = tk.Label(
            govde,
            text="Program hazırlanıyor...",
            font=("Segoe UI", 9),
            fg=COLOR_NAVY_SOFT,
            bg=COLOR_BG,
        )
        self._status.pack(pady=(4, 8))

        style = ttk.Style(self)
        try:
            style.configure(
                "CinSplash.Horizontal.TProgressbar",
                troughcolor="#E8E2D4",
                background=COLOR_GOLD_DIM,
                bordercolor=COLOR_NAVY,
                lightcolor=COLOR_GOLD,
                darkcolor=COLOR_GOLD_DIM,
            )
            bar_style = "CinSplash.Horizontal.TProgressbar"
        except tk.TclError:
            bar_style = "Horizontal.TProgressbar"

        self._progress = ttk.Progressbar(
            govde,
            mode="determinate",
            maximum=100,
            value=0,
            length=width - 100,
            style=bar_style,
        )
        self._progress.pack(pady=(4, 8))

        tk.Label(
            govde,
            text=f"Sürüm {APP_VERSION}",
            font=("Segoe UI", 8),
            fg=COLOR_MUTED,
            bg=COLOR_BG,
        ).pack(side="bottom", pady=(8, 0))

        apply_window_icon(self)
        self.update_idletasks()
        self.update()

    def set_progress(self, value: float, status: str | None = None) -> None:
        self._progress["value"] = max(0, min(100, float(value)))
        if status:
            self._status.configure(text=status)
        try:
            self.update_idletasks()
            self.update()
        except tk.TclError:
            pass

    def close_safe(self) -> None:
        try:
            self.attributes("-topmost", False)
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass


def run_startup_with_splash(
    master: tk.Tk,
    bootstrap: Callable[[Callable[[float, str], None]], None],
) -> None:
    """
    Splash gösterirken bootstrap(progress_cb) çalıştırır.
    Hata olursa splash kapanır; istisna yeniden fırlatılır.
    """
    splash = SplashScreen(master)
    try:

        def progress(pct: float, msg: str) -> None:
            splash.set_progress(pct, msg)

        bootstrap(progress)
        splash.set_progress(100, "Tamamlandı")
        try:
            master.update_idletasks()
            master.update()
        except tk.TclError:
            pass
    except Exception:
        splash.close_safe()
        raise
    else:
        splash.close_safe()
        try:
            # topmost / grab artıkları giriş penceresini engellemesin
            master.update_idletasks()
            master.update()
        except tk.TclError:
            pass


def center_toplevel_on_screen(window: tk.Toplevel, *, width: int | None = None, height: int | None = None) -> None:
    """Withdrawn parent olsa bile diyaloğu ekranın ortasına getirir ve öne alır."""
    try:
        window.update_idletasks()
        w = width or window.winfo_width()
        h = height or window.winfo_height()
        if w < 2:
            w = window.winfo_reqwidth()
        if h < 2:
            h = window.winfo_reqheight()
        sw = window.winfo_screenwidth()
        sh = window.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        window.geometry(f"+{x}+{y}")
        window.lift()
        window.attributes("-topmost", True)
        window.after(200, lambda: _clear_topmost(window))
        window.focus_force()
    except tk.TclError:
        pass


def _clear_topmost(window: tk.Misc) -> None:
    try:
        if window.winfo_exists():
            window.attributes("-topmost", False)
    except tk.TclError:
        pass