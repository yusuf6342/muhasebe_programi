"""Cari Hesaplar «Borç / Alacak Özeti» — cari kart ve evrak üst paneli aynı metin/rengi kullanır.

Değerler ``CariService.kart_ozet_metrikleri`` sonucundan üretilir (yeni formül yok).
Beş satır: Toplam Borç, Toplam Alacak, Kalan Bakiye (B)/(A), Kalan Bakiye Gün, Kapatılan Bakiye Gün.
"""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from typing import Any

from cari_kart_tema import BASARI, IKINCIL, LACIVERT, UYARI

OZET_SATIRLARI = (
    "Toplam Borç",
    "Toplam Alacak",
    "Kalan Bakiye",
    "Kalan Bakiye Gün",
    "Kapatılan Bakiye Gün",
)
BUYUK_SATIRLAR = frozenset({"Kalan Bakiye", "Kalan Bakiye Gün"})
GECIKME_MS = 120


def para_goster(tutar) -> str:
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def tarih_goster(tarih) -> str:
    return tarih.strftime("%d.%m.%Y")


def bakiye_yon_metni(bakiye: Decimal, *, tedarikci_modu: bool = False) -> str:
    """Tedarikçide pozitif bakiye bizim borcumuzdur; yön açık yazılır."""
    if tedarikci_modu:
        if bakiye > 0:
            return "Alacaklı (tedarikçiye borcumuz)"
        if bakiye < 0:
            return "Borçlu (tedarikçiden alacağımız)"
        return "Kapalı"
    if bakiye > 0:
        return "Borçlu"
    if bakiye < 0:
        return "Alacaklı"
    return "Kapalı"


def bakiye_yon_eki(bakiye: Decimal, *, tedarikci_modu: bool = False) -> str:
    """Kalan bakiye satırı için (B)/(A); sıfırda boş."""
    if bakiye == 0:
        return ""
    if tedarikci_modu:
        return "(A)" if bakiye > 0 else "(B)"
    return "(B)" if bakiye > 0 else "(A)"


def bakiye_rengi(bakiye: Decimal) -> str:
    if bakiye > 0:
        return UYARI
    if bakiye < 0:
        return BASARI
    return IKINCIL


def gun_goster(deger) -> str:
    """Sayısal gün + «GÜN». Boş/None → «—»; gerçek 0 → «0 GÜN»."""
    if deger is None or deger == "":
        return "—"
    try:
        x = float(deger)
    except (TypeError, ValueError):
        return "—"
    if abs(x - round(x)) < 1e-9:
        return f"{int(round(x))} GÜN"
    return f"{x:.1f}".replace(".", ",") + " GÜN"


def kalan_bakiye_metni(bakiye: Decimal, *, tedarikci_modu: bool = False) -> str:
    """Pozitif tutar + yön eki; çift eksi işareti yok."""
    tutar = para_goster(abs(bakiye))
    ek = bakiye_yon_eki(bakiye, tedarikci_modu=tedarikci_modu)
    return f"{tutar} {ek}".strip() if ek else tutar


def ozet_metinleri(metrik: dict[str, Any] | None, *, tedarikci_modu: bool = False) -> dict[str, tuple[str, str]]:
    """{satır başlığı: (metin, renk)} — metrik yoksa tüm satırlar «—»."""
    if not metrik:
        return {b: ("—", LACIVERT) for b in OZET_SATIRLARI}
    bakiye = Decimal(str(metrik.get("bakiye") or 0))
    renk = bakiye_rengi(bakiye)
    # Kalan bakiye gün = açık kalan tutarın işlem-tarihi yaşı (vade gecikmesi değil).
    # Valör üretilemediyse / açık kalem yoksa sahte «0 GÜN» gösterme.
    sebep = (metrik.get("ortalama_valor_sebep") or "").strip()
    gun_deger = metrik.get("bakiye_ortalama_valor_gun")
    if metrik.get("valor_turu") == "YOK" and metrik.get("ortalama_valor_tarihi") is None:
        kalan_gun = gun_goster(gun_deger) if gun_deger else "—"
    elif sebep in ("Açık hareket yok", "Tarih eksik", "Oturum yok") and not gun_deger:
        kalan_gun = "—"
    elif "bakiye_ortalama_valor_gun" not in metrik and metrik.get("ortalama_valor_tarihi") is None:
        kalan_gun = "—"
    else:
        kalan_gun = gun_goster(gun_deger)

    if "odenen_ortalama_valor_gun" not in metrik:
        kapatilan_gun = "—"
    else:
        kapatilan_gun = gun_goster(metrik.get("odenen_ortalama_valor_gun"))

    return {
        "Toplam Borç": (para_goster(metrik.get("toplam_borc") or 0), LACIVERT),
        "Toplam Alacak": (para_goster(metrik.get("toplam_alacak") or 0), LACIVERT),
        "Kalan Bakiye": (kalan_bakiye_metni(bakiye, tedarikci_modu=tedarikci_modu), renk),
        "Kalan Bakiye Gün": (kalan_gun, LACIVERT),
        "Kapatılan Bakiye Gün": (kapatilan_gun, LACIVERT),
    }


def kisa_bakiye_valor_metni(metrik: dict[str, Any] | None) -> tuple[str, str, str]:
    """(bakiye metni, valör metni, bakiye rengi) — Hızlı Satış müşteri altı satırı.

    Kaynak ve işaret kuralı Cari Hesaplar ile aynı (``ozet_metinleri``):
    pozitif bakiye müşterinin borcu, negatif alacağı.
    """
    if not metrik:
        return "Bakiye bilgisi yok", "Valör bilgisi yok", IKINCIL
    bakiye = Decimal(str(metrik.get("bakiye") or 0))
    renk = bakiye_rengi(bakiye)
    tutar = para_goster(abs(bakiye))
    yon = bakiye_yon_metni(bakiye, tedarikci_modu=False)
    yon_kisa = {"Borçlu": "Borç", "Alacaklı": "Alacak", "Kapalı": "Kapalı"}.get(yon, yon)
    valor_tarih = metrik.get("ortalama_valor_tarihi")
    valor = f"Valör {tarih_goster(valor_tarih)}" if valor_tarih is not None else "Valör bilgisi yok"
    return f"Bakiye {tutar} {yon_kisa}", valor, renk


class EvrakCariOzetPaneli:
    """Evrak üst panelindeki kompakt Borç / Alacak özeti (Cari Hesaplar ile aynı değerler)."""

    def __init__(self, kap, *, bg: str, font_fn=None, tedarikci_modu: bool = False, pady: int = 0):
        self.kap = kap
        self.tedarikci_modu = tedarikci_modu
        self.degerler: dict[str, tk.Label] = {}
        self.basliklar: dict[str, tk.Label] = {}
        self.cari_id: int | None = None
        self._bekleyen = None
        kap.columnconfigure(0, weight=0)
        kap.columnconfigure(1, weight=1)
        for satir, baslik in enumerate(OZET_SATIRLARI):
            buyuk = baslik in BUYUK_SATIRLAR
            yazi = ("Segoe UI", 11 if buyuk else 9, "bold")
            if font_fn is not None:
                try:
                    yazi = font_fn(11 if buyuk else 9, "bold")
                except Exception:  # noqa: BLE001
                    pass
            lbl = tk.Label(kap, text=baslik, bg=bg, fg=LACIVERT, font=yazi, anchor="w", bd=0, padx=0, pady=0)
            lbl.grid(row=satir, column=0, sticky="w", padx=(0, 6), pady=pady)
            deger = tk.Label(kap, text="—", bg=bg, fg=LACIVERT, font=yazi, anchor="e", bd=0, padx=0, pady=0)
            deger.grid(row=satir, column=1, sticky="e", pady=pady)
            self.basliklar[baslik] = lbl
            self.degerler[baslik] = deger

    def uygula(self, metrik: dict[str, Any] | None) -> None:
        for baslik, (metin, renk) in ozet_metinleri(metrik, tedarikci_modu=self.tedarikci_modu).items():
            lbl = self.degerler.get(baslik)
            if lbl is None:
                continue
            try:
                lbl.configure(text=metin, fg=renk)
            except tk.TclError:
                pass

    def yenile(self, cari_id: int | None, *, hemen: bool = False) -> None:
        """Cari değişince / kayıt / tahsilat sonrası; ardışık çağrılar tek sorguya iner."""
        self.cari_id = int(cari_id) if cari_id else None
        if hemen:
            self._yukle()
            return
        if self._bekleyen is not None:
            return
        try:
            self._bekleyen = self.kap.after(GECIKME_MS, self._yukle)
        except tk.TclError:
            self._bekleyen = None

    def _yukle(self) -> None:
        self._bekleyen = None
        try:
            if not self.kap.winfo_exists():
                return
        except tk.TclError:
            return
        if not self.cari_id:
            self.uygula(None)
            return
        try:
            from database.cari_service import CariService

            metrik = CariService.kart_ozet_metrikleri(self.cari_id)
        except Exception:  # noqa: BLE001
            metrik = None
        self.uygula(metrik)
