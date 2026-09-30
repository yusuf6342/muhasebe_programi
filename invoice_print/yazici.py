"""Windows yazıcı listesi ve PDF'i seçilen yazıcıya A4 dikey basma (winspool/GDI, ctypes)."""

from __future__ import annotations

import ctypes
import struct
import sys
from ctypes import wintypes
from pathlib import Path

_PRINTER_ENUM_LOCAL = 0x2
_PRINTER_ENUM_CONNECTIONS = 0x4
_DM_OUT_BUFFER = 2
_DM_IN_BUFFER = 8
_DM_ORIENTATION = 0x1
_DM_PAPERSIZE = 0x2
_DMORIENT_PORTRAIT = 1
_DMPAPER_A4 = 9
_LOGPIXELSX, _LOGPIXELSY = 88, 90
_PHYSICALWIDTH, _PHYSICALHEIGHT = 110, 111
_PHYSICALOFFSETX, _PHYSICALOFFSETY = 112, 113
_HALFTONE = 4
_SRCCOPY = 0x00CC0020
_EN_FAZLA_DPI = 300


class _PRINTER_INFO_4(ctypes.Structure):
    _fields_ = [("pPrinterName", wintypes.LPWSTR), ("pServerName", wintypes.LPWSTR), ("Attributes", wintypes.DWORD)]


class _DOCINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_int),
        ("lpszDocName", wintypes.LPCWSTR),
        ("lpszOutput", wintypes.LPCWSTR),
        ("lpszDatatype", wintypes.LPCWSTR),
        ("fwType", wintypes.DWORD),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _dll():
    if sys.platform != "win32":
        raise ValueError("Doğrudan yazdırma yalnızca Windows'ta desteklenir.")
    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    winspool.EnumPrintersW.argtypes = [
        wintypes.DWORD, wintypes.LPWSTR, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
    ]
    winspool.GetDefaultPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    winspool.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
    winspool.ClosePrinter.argtypes = [wintypes.HANDLE]
    winspool.DocumentPropertiesW.argtypes = [
        wintypes.HWND, wintypes.HANDLE, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
    ]
    winspool.DocumentPropertiesW.restype = wintypes.LONG
    gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
    gdi32.CreateDCW.restype = ctypes.c_void_p
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi32.GetDeviceCaps.argtypes = [ctypes.c_void_p, ctypes.c_int]
    gdi32.StartDocW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_DOCINFOW)]
    for ad in ("StartPage", "EndPage", "EndDoc", "AbortDoc"):
        getattr(gdi32, ad).argtypes = [ctypes.c_void_p]
    gdi32.SetStretchBltMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
    gdi32.SetBrushOrgEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    gdi32.StretchDIBits.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_void_p, ctypes.POINTER(_BITMAPINFOHEADER), wintypes.UINT, wintypes.DWORD,
    ]
    return winspool, gdi32


def yazicilar() -> list[str]:
    winspool, _ = _dll()
    bayrak = _PRINTER_ENUM_LOCAL | _PRINTER_ENUM_CONNECTIONS
    gerekli, adet = wintypes.DWORD(0), wintypes.DWORD(0)
    winspool.EnumPrintersW(bayrak, None, 4, None, 0, ctypes.byref(gerekli), ctypes.byref(adet))
    if not gerekli.value:
        return []
    tampon = ctypes.create_string_buffer(gerekli.value)
    if not winspool.EnumPrintersW(
        bayrak, None, 4, tampon, gerekli, ctypes.byref(gerekli), ctypes.byref(adet)
    ):
        return []
    dizi = ctypes.cast(tampon, ctypes.POINTER(_PRINTER_INFO_4))
    return [dizi[i].pPrinterName for i in range(adet.value) if dizi[i].pPrinterName]


def varsayilan_yazici() -> str | None:
    winspool, _ = _dll()
    boy = wintypes.DWORD(0)
    winspool.GetDefaultPrinterW(None, ctypes.byref(boy))
    if not boy.value:
        return None
    tampon = ctypes.create_unicode_buffer(boy.value)
    if not winspool.GetDefaultPrinterW(tampon, ctypes.byref(boy)):
        return None
    return tampon.value or None


def _a4_dikey_devmode(winspool, yazici: str):
    """Yazıcının varsayılan ayarlarını alır, kâğıdı A4 ve yönü dikey yapar."""
    tutamac = wintypes.HANDLE()
    if not winspool.OpenPrinterW(yazici, ctypes.byref(tutamac), None):
        return None
    try:
        boy = winspool.DocumentPropertiesW(None, tutamac, yazici, None, None, 0)
        if boy <= 0:
            return None
        dm = ctypes.create_string_buffer(boy)
        if winspool.DocumentPropertiesW(None, tutamac, yazici, dm, None, _DM_OUT_BUFFER) < 0:
            return None
        # DEVMODEW: dmFields @72, dmOrientation @76, dmPaperSize @78
        alanlar = struct.unpack_from("<I", dm, 72)[0] | _DM_ORIENTATION | _DM_PAPERSIZE
        struct.pack_into("<I", dm, 72, alanlar)
        struct.pack_into("<h", dm, 76, _DMORIENT_PORTRAIT)
        struct.pack_into("<h", dm, 78, _DMPAPER_A4)
        winspool.DocumentPropertiesW(None, tutamac, yazici, dm, dm, _DM_IN_BUFFER | _DM_OUT_BUFFER)
        return dm
    finally:
        winspool.ClosePrinter(tutamac)


def _bgr_satirlari(pix) -> bytes:
    """RGB pixmap → 4 bayta hizalı, yukarıdan aşağı BGR satırları (24 bit DIB)."""
    ham = bytearray(pix.samples)
    ham[0::3], ham[2::3] = ham[2::3], ham[0::3]
    satir = pix.width * 3
    dolgu = (-satir) % 4
    if not dolgu and pix.stride == satir:
        return bytes(ham)
    ek = b"\x00" * dolgu
    return b"".join(bytes(ham[i * pix.stride : i * pix.stride + satir]) + ek for i in range(pix.height))


def pdf_yazdir(pdf: Path, yazici: str, *, belge_adi: str = "Belge", cikti_dosyasi: str | None = None) -> int:
    """PDF'i yazıcıya gerçek ölçekte (A4) basar; basılan sayfa sayısını döndürür.

    ``cikti_dosyasi`` yalnızca dosyaya yazan sürücüler içindir (ör. Microsoft Print to PDF).
    """
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz

    winspool, gdi32 = _dll()
    dm = _a4_dikey_devmode(winspool, yazici)
    hdc = gdi32.CreateDCW("WINSPOOL", yazici, None, dm)
    if not hdc:
        raise ValueError(f"Yazıcıya bağlanılamadı: {yazici}")
    doc = fitz.open(str(pdf))
    basilan = 0
    try:
        di = _DOCINFOW(ctypes.sizeof(_DOCINFOW), belge_adi, cikti_dosyasi, None, 0)
        if gdi32.StartDocW(hdc, ctypes.byref(di)) <= 0:
            raise ValueError(f"Yazdırma işi başlatılamadı ({yazici}).")
        try:
            dpi_x = gdi32.GetDeviceCaps(hdc, _LOGPIXELSX) or 300
            dpi_y = gdi32.GetDeviceCaps(hdc, _LOGPIXELSY) or 300
            fiz_w = gdi32.GetDeviceCaps(hdc, _PHYSICALWIDTH)
            fiz_h = gdi32.GetDeviceCaps(hdc, _PHYSICALHEIGHT)
            off_x = gdi32.GetDeviceCaps(hdc, _PHYSICALOFFSETX)
            off_y = gdi32.GetDeviceCaps(hdc, _PHYSICALOFFSETY)
            gdi32.SetStretchBltMode(hdc, _HALFTONE)
            gdi32.SetBrushOrgEx(hdc, 0, 0, None)
            for sayfa in doc:
                w_px = sayfa.rect.width / 72 * dpi_x
                h_px = sayfa.rect.height / 72 * dpi_y
                olcek = min(1.0, (fiz_w or w_px) / w_px, (fiz_h or h_px) / h_px)
                hedef_w, hedef_h = int(w_px * olcek), int(h_px * olcek)
                x = int(((fiz_w or hedef_w) - hedef_w) / 2) - off_x
                y = int(((fiz_h or hedef_h) - hedef_h) / 2) - off_y
                pix = sayfa.get_pixmap(dpi=min(dpi_x, _EN_FAZLA_DPI), alpha=False, colorspace=fitz.csRGB)
                bmi = _BITMAPINFOHEADER(
                    ctypes.sizeof(_BITMAPINFOHEADER), pix.width, -pix.height, 1, 24, 0, 0, 0, 0, 0, 0
                )
                bitler = _bgr_satirlari(pix)
                if gdi32.StartPage(hdc) <= 0:
                    raise ValueError("Yazıcı sayfası başlatılamadı.")
                gdi32.StretchDIBits(
                    hdc, x, y, hedef_w, hedef_h, 0, 0, pix.width, pix.height,
                    bitler, ctypes.byref(bmi), 0, _SRCCOPY,
                )
                if gdi32.EndPage(hdc) <= 0:
                    raise ValueError("Yazıcı sayfası tamamlanamadı.")
                basilan += 1
        except Exception:
            gdi32.AbortDoc(hdc)
            raise
        gdi32.EndDoc(hdc)
    finally:
        doc.close()
        gdi32.DeleteDC(hdc)
    return basilan
