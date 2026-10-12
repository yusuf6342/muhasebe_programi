"""Cari Hesaplar «Borç / Alacak Özeti» — cari kart ve evrak üst paneli aynı metin/rengi kullanır.

Değerler ``CariService.kart_ozet_metrikleri`` sonucundan üretilir (yeni formül yok).
Son işlem ve bekleyen sipariş satırları evrak panelinde gösterilmez.
"""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from typing import Any

from cari_kart_tema import BASARI, IKINCIL, LACIVERT, UYARI

OZET_SATIRLARI = (
    "Toplam borç",
    "Toplam alacak",
    "Kalan Bakiye",
    "Bakiye yönü",
    "Ortalama borç kapatma süresi",
    "Ortalama Valör",
    "Ortalama Valör Tarihi",
    "Ortalama Valör Gün Sayısı",
)
BUYUK_SATIRLAR = frozenset({"Kalan Bakiye", "Ortalama Valör"})
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


def bakiye_rengi(bakiye: Decimal) -> str:
    if bakiye > 0:
        return UYARI
    if bakiye < 0:
        return BASARI
    return IKINCIL


def ozet_metinleri(metrik: dict[str, Any] | None, *, tedarikci_modu: bool = False) -> dict[str, tuple[str, str]]:
    """{satır başlığı: (metin, renk)} — metrik yoksa tüm satırlar «—»."""
    if not metrik:
        return {b: ("—", LACIVERT) for b in OZET_SATIRLARI}
    bakiye = Decimal(str(metrik.get("bakiye") or 0))
    durum = metrik.get("bakiye_durumu") or "Bakiye yok"
    renk = bakiye_rengi(bakiye)
    odenen = float(metrik.get("odenen_ortalama_valor_gun") or 0)
    bvalor = float(metrik.get("bakiye_ortalama_valor_gun") or 0)
    valor_etiket = metrik.get("valor_turu_etiket") or "Valör Yok"
    valor_tarih = metrik.get("ortalama_valor_tarihi")
    sebep = metrik.get("ortalama_valor_sebep")
    yon = metrik.get("bakiye_yonu")
    if tedarikci_modu:
        yon_yazi = bakiye_yon_metni(bakiye, tedarikci_modu=True)
    elif yon == "BORCLU":
        yon_yazi = "Borçlu"
    elif yon == "ALACAKLI":
        yon_yazi = "Alacaklı"
    elif yon == "KAPALI":
        yon_yazi = "Kapalı"
    else:
        yon_yazi = durum if durum and durum != "Bakiye yok" else (
            "Borçlu" if bakiye > 0 else ("Alacaklı" if bakiye < 0 else "Kapalı")
        )
    if valor_tarih is not None or (bvalor and metrik.get("valor_turu") != "YOK"):
        gun_yazi = f"{bvalor:.1f} gün"
    else:
        gun_yazi = sebep or "0 gün"
    return {
        "Toplam borç": (para_goster(metrik.get("toplam_borc") or 0), LACIVERT),
        "Toplam alacak": (para_goster(metrik.get("toplam_alacak") or 0), LACIVERT),
        "Kalan Bakiye": (para_goster(abs(bakiye)), renk),
        "Bakiye yönü": (yon_yazi, renk),
        "Ortalama borç kapatma süresi": (f"{odenen:.1f} gün", LACIVERT),
        "Ortalama Valör": (valor_etiket, LACIVERT),
        "Ortalama Valör Tarihi": (
            tarih_goster(valor_tarih) if valor_tarih is not None else (sebep or "—"), LACIVERT
        ),
        "Ortalama Valör Gün Sayısı": (gun_yazi, LACIVERT),
    }


def kisa_bakiye_valor_metni(metrik: dict[str, Any] | None) -> tuple[str, str, str]:
    """(bakiye metni, valör metni, bakiye rengi) — Hızlı Satış müşteri altı satırı.

    Kaynak ve işaret kuralı Cari Hesaplar ile aynı (``ozet_metinleri``):
    pozitif bakiye müşterinin borcu, negatif alacağı. Valör = «Ortalama Valör Tarihi».
    """
    if not metrik:
        return "Bakiye bilgisi yok", "Valör bilgisi yok", IKINCIL
    metinler = ozet_metinleri(metrik)
    bakiye = Decimal(str(metrik.get("bakiye") or 0))
    tutar, renk = metinler["Kalan Bakiye"]
    yon = metinler["Bakiye yönü"][0]
    yon_kisa = {"Borçlu": "Borç", "Alacaklı": "Alacak"}.get(yon, "Kapalı" if bakiye == 0 else yon)
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
            yazi = ("Segoe UI", 10 if buyuk else 8, "bold")
            if font_fn is not None:
                try:
                    yazi = font_fn(10 if buyuk else 8, "bold")
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
            # after_idle değil: update_idletasks (ör. makbuz açılışı) sorguyu beklemesin
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
