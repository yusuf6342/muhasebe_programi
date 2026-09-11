"""EvoBulut arka plan aktarım logunu okuyup durum özeti üretir."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_ENTEGRASYON = Path(__file__).resolve().parent / "entegrasyon"
_LOG_ADAYLARI = (
    _ENTEGRASYON / "_full_import_progress.txt",
    _ENTEGRASYON / "_full_import_log.txt",
)
LOG_YOLU = _LOG_ADAYLARI[0]
PID_YOLU = _ENTEGRASYON / "_full_import.pid"

# Log sessizliği: liste çekimi uzun sürebilir; süreç canlıysa yine "aktif"
CANLI_ESIK_SN = 90

_ADIM_RE = re.compile(r"===\s*ADIM:\s*(\S+)\s*===")
_ILERLEME_RE = re.compile(
    r"(\d+)\s*/\s*(\d+)\s*.*?olu.?turulan\s*=\s*(\d+).*?atlanan\s*=\s*(\d+).*?hata\s*=\s*(\d+)",
    re.IGNORECASE | re.DOTALL,
)
_LISTE_RE = re.compile(r"liste\s+çekiliyor|liste\s+cekiliyor|sayfa\s+\d+", re.IGNORECASE)


@dataclass
class AktarimDurum:
    aktif: bool
    bitti: bool
    metin: str
    adim: str = ""
    mevcut: int = 0
    toplam: int = 0
    log_var: bool = False
    surec_var: bool = False


def _surec_calisiyor_mu() -> bool:
    """_full_import.pid dosyasındaki süreç yaşıyor mu?"""
    try:
        if not PID_YOLU.is_file():
            return False
        ham = PID_YOLU.read_text(encoding="utf-8-sig").strip().split()[0]
        pid = int(ham)
    except (OSError, ValueError, IndexError):
        return False
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            k32 = ctypes.windll.kernel32
            for access in (0x1000, 0x0400, 0x0010):  # LIMITED / QUERY / VM_READ
                handle = k32.OpenProcess(access, False, pid)
                if handle:
                    k32.CloseHandle(handle)
                    return True
            # GetExitCodeProcess via SYNCHRONIZE
            handle = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if not handle:
                return False
            exit_code = ctypes.c_ulong()
            ok = k32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            k32.CloseHandle(handle)
            # 259 = STILL_ACTIVE
            return bool(ok) and exit_code.value == 259
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _log_metni_oku(yol: Path) -> str:
    """PowerShell yönlendirmesi UTF-16 yazabilir; UTF-8 de desteklenir."""
    ham = yol.read_bytes()
    if ham.startswith(b"\xff\xfe") or ham.startswith(b"\xfe\xff"):
        return ham.decode("utf-16", errors="replace")
    if b"\x00" in ham[:200]:
        return ham.decode("utf-16-le", errors="replace")
    for enc in ("utf-8", "cp1254", "latin-1"):
        try:
            return ham.decode(enc)
        except UnicodeDecodeError:
            continue
    return ham.decode("utf-8", errors="replace")


def durum_oku(log_yolu: Path | None = None) -> AktarimDurum:
    surec = _surec_calisiyor_mu()

    if log_yolu is not None:
        adaylar = [log_yolu]
    else:
        adaylar = [p for p in _LOG_ADAYLARI if p.is_file()]
        if not adaylar and not surec:
            return AktarimDurum(
                aktif=False, bitti=False, metin="EvoBulut aktarımı yok", log_var=False
            )
        if adaylar:
            adaylar.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    if not adaylar:
        return AktarimDurum(
            aktif=surec,
            bitti=False,
            metin="EvoBulut aktarılıyor (log henüz yok)…" if surec else "EvoBulut aktarımı yok",
            log_var=False,
            surec_var=surec,
        )

    yol = adaylar[0]
    try:
        mtime = yol.stat().st_mtime
        yas = datetime.now(timezone.utc).timestamp() - mtime
        ham = _log_metni_oku(yol)
    except OSError:
        return AktarimDurum(
            aktif=surec,
            bitti=False,
            metin="Aktarım logu okunamadı",
            log_var=True,
            surec_var=surec,
        )

    satirlar = [s.strip() for s in ham.splitlines() if s.strip()]
    if not satirlar:
        return AktarimDurum(
            aktif=surec,
            bitti=False,
            metin="Aktarım logu boş",
            log_var=True,
            surec_var=surec,
        )

    bitti = any("=== ÖZET ===" in s or "=== OZET ===" in s for s in satirlar[-40:])
    adim = ""
    adim_idx = -1
    for i in range(len(satirlar) - 1, -1, -1):
        m = _ADIM_RE.search(satirlar[i])
        if m:
            adim = m.group(1)
            adim_idx = i
            break

    # Sadece son adımdan sonraki satırlardan ilerleme al
    son_bolum = satirlar[adim_idx + 1 :] if adim_idx >= 0 else satirlar[-40:]
    ilerleme = ""
    mevcut = toplam = 0
    liste_cekiliyor = False
    for s in reversed(son_bolum):
        if _LISTE_RE.search(s) and not ilerleme:
            liste_cekiliyor = True
            if "sayfa" in s.casefold():
                ilerleme = s
            elif not ilerleme:
                ilerleme = "liste çekiliyor…"
        m = _ILERLEME_RE.search(s)
        if m:
            mevcut, toplam = int(m.group(1)), int(m.group(2))
            ilerleme = (
                f"{mevcut}/{toplam}  oluşturulan={m.group(3)}  "
                f"atlanan={m.group(4)}  hata={m.group(5)}"
            )
            liste_cekiliyor = False
            break
        if s.startswith("[") and ("çekilen=" in s.casefold() or "cekilen=" in s.casefold()):
            if not ilerleme:
                ilerleme = s

    log_taze = yas <= CANLI_ESIK_SN
    aktif = (not bitti) and (surec or log_taze)
    adim_goster = adim.replace("_", " ") if adim else "…"

    if bitti:
        metin = f"EvoBulut aktarımı bitti — {ilerleme or adim_goster}"
    elif aktif:
        if liste_cekiliyor and not mevcut:
            metin = f"EvoBulut aktarılıyor: {adim_goster} — liste çekiliyor…"
        else:
            metin = f"EvoBulut aktarılıyor: {adim_goster} — {ilerleme or 'çalışıyor…'}"
    else:
        metin = (
            f"EvoBulut aktarımı durdu ({int(yas)} sn sessiz) — "
            f"{adim_goster} — {ilerleme or 'log güncellenmiyor'}"
        )
    return AktarimDurum(
        aktif=aktif,
        bitti=bitti,
        metin=metin,
        adim=adim,
        mevcut=mevcut,
        toplam=toplam,
        log_var=True,
        surec_var=surec,
    )
