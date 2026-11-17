"""Cari Hesaplar «Borç / Alacak Özeti» — cari kart ve evrak üst paneli aynı metin/rengi kullanır.

Değerler ``CariService.kart_ozet_metrikleri`` sonucundan üretilir (yeni formül yok).
Beş satır: Toplam Borç, Toplam Alacak, Kalan Bakiye (B)/(A), Açık Valör Gün (T−I belge yaşı),
Kapanan Valör Gün (P−I). Vade farkı (P−V) ayrı ölçü olarak serviste tutulur.
"""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from typing import Any

from cari_kart_tema import BASARI, BEYAZ, CIZGI, IKINCIL, LACIVERT, UYARI

# Tedarikçi alacaklı (biz borçluyuz, net<0 / (A)): yeşil değil siyah — yalnız yazı rengi
TEDARIKCI_ALACAK_RENK = "#000000"

OZET_SATIRLARI = (
    "Toplam Borç",
    "Toplam Alacak",
    "Kalan Bakiye",
    "Açık Valör Gün",
    "Kapanan Valör Gün",
)
# Eski başlıklar (geriye dönük eşleme)
_ESKI_ACIK = "Kalan Bakiye Gün"
_ESKI_KAPANAN = "Kapatılan Bakiye Gün"

BUYUK_SATIRLAR = frozenset({"Kalan Bakiye", "Açık Valör Gün", _ESKI_ACIK})
GECIKME_MS = 120


def para_goster(tutar) -> str:
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def tarih_goster(tarih) -> str:
    return tarih.strftime("%d.%m.%Y")


def bakiye_yon_metni(bakiye: Decimal, *, tedarikci_modu: bool = False) -> str:
    """net>0 Borçlu (cari bize borçlu); net<0 Alacaklı (cari bizden alacaklı). Tür bağımsız."""
    del tedarikci_modu
    if bakiye > 0:
        return "Borçlu — cari bize borçlu"
    if bakiye < 0:
        return "Alacaklı — cari bizden alacaklı"
    return "Kapalı"


def bakiye_yon_eki(bakiye: Decimal, *, tedarikci_modu: bool = False) -> str:
    """Kalan bakiye satırı için (B)/(A); sıfırda boş. Tür bağımsız."""
    del tedarikci_modu
    if bakiye == 0:
        return ""
    return "(B)" if bakiye > 0 else "(A)"


def tedarikci_ana_turu_mu(cari_turu: str | None = None, ana_tur: str | None = None) -> bool:
    """Gerçek ana cari türü Tedarikçi mi? Kod öneki (T/M) kullanılmaz."""
    tur = (cari_turu or "").strip()
    ana = (ana_tur or "").strip()
    return tur == "Tedarikçi" or ana == "Tedarikçi"


def bakiye_rengi(bakiye: Decimal, *, tedarikci_modu: bool = False) -> str:
    """net>0 borçlu (kırmızı); net<0 alacaklı — müşteri yeşil, tedarikçi siyah."""
    if bakiye > 0:
        return UYARI
    if bakiye < 0:
        return TEDARIKCI_ALACAK_RENK if tedarikci_modu else BASARI
    return IKINCIL


def gun_goster(deger) -> str:
    """Sayısal gün + «GÜN» (iki ondalık). Boş/None → «—»; gerçek 0 → «0,00 GÜN»."""
    if deger is None or deger == "":
        return "—"
    try:
        x = float(deger)
    except (TypeError, ValueError):
        return "—"
    return f"{x:.2f}".replace(".", ",") + " GÜN"


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
    renk = bakiye_rengi(bakiye, tedarikci_modu=tedarikci_modu)
    # Açık valör = T − I (belge yaşı, tutar-ağırlıklı). Avans → «—».
    sebep = (metrik.get("ortalama_valor_sebep") or "").strip()
    uyari = (metrik.get("ortalama_valor_uyari") or "").strip()
    gun_deger = metrik.get("bakiye_ortalama_valor_gun")
    olcu = (metrik.get("olcu_acik") or metrik.get("olcu") or "").strip()

    if metrik.get("valor_turu") == "YOK" and metrik.get("ortalama_valor_tarihi") is None:
        kalan_gun = gun_goster(gun_deger) if gun_deger is not None else "—"
    elif sebep in ("Açık hareket yok", "Tarih eksik", "Oturum yok", "Vade eksik") and gun_deger is None:
        kalan_gun = "— / açık kalem yok" if "açık" in sebep.casefold() or sebep == "Açık hareket yok" else "—"
    elif gun_deger is None and "bakiye_ortalama_valor_gun" in metrik:
        if olcu == "avans_bekleme_yasi_T_eksi_I" or "avans" in uyari.casefold():
            kalan_gun = "— / valör yok"
        else:
            kalan_gun = "— / açık valör yok"
    elif "bakiye_ortalama_valor_gun" not in metrik and metrik.get("ortalama_valor_tarihi") is None:
        kalan_gun = "—"
    else:
        kalan_gun = gun_goster(gun_deger)

    if "odenen_ortalama_valor_gun" not in metrik:
        kapatilan_gun = "—"
    else:
        od = metrik.get("odenen_ortalama_valor_gun")
        kapatilan_gun = gun_goster(od) if od is not None else "— / kapanan işlem yok"

    return {
        "Toplam Borç": (para_goster(metrik.get("toplam_borc") or 0), LACIVERT),
        "Toplam Alacak": (para_goster(metrik.get("toplam_alacak") or 0), LACIVERT),
        "Kalan Bakiye": (kalan_bakiye_metni(bakiye, tedarikci_modu=tedarikci_modu), renk),
        "Açık Valör Gün": (kalan_gun, LACIVERT),
        "Kapanan Valör Gün": (kapatilan_gun, LACIVERT),
    }


def kisa_bakiye_valor_metni(
    metrik: dict[str, Any] | None, *, tedarikci_modu: bool = False
) -> tuple[str, str, str]:
    """(bakiye metni, valör metni, bakiye rengi) — Hızlı Satış müşteri altı satırı.

    Kaynak ve işaret kuralı Cari Hesaplar ile aynı (``ozet_metinleri``):
    pozitif bakiye müşterinin borcu, negatif alacağı.
    Müşteri ekranı varsayılan; tedarikçi_modu=True ise alacak siyah.
    """
    if not metrik:
        return "Bakiye bilgisi yok", "Valör bilgisi yok", IKINCIL
    bakiye = Decimal(str(metrik.get("bakiye") or 0))
    renk = bakiye_rengi(bakiye, tedarikci_modu=tedarikci_modu)
    tutar = para_goster(abs(bakiye))
    yon = bakiye_yon_metni(bakiye, tedarikci_modu=False)
    if yon.startswith("Borçlu"):
        yon_kisa = "Borç"
    elif yon.startswith("Alacaklı"):
        yon_kisa = "Alacak"
    else:
        yon_kisa = "Kapalı"
    valor_tarih = metrik.get("ortalama_valor_tarihi")
    gun = metrik.get("bakiye_ortalama_valor_gun")
    if valor_tarih is not None:
        valor = f"Valör {tarih_goster(valor_tarih)}"
    elif gun is not None:
        valor = f"Açık valör {gun_goster(gun)}"
    else:
        valor = "Valör bilgisi yok"
    return f"Bakiye {tutar} {yon_kisa}", valor, renk


class EvrakCariOzetPaneli:
    """Evrak üst panelindeki kompakt Borç / Alacak özeti (Cari Hesaplar ile aynı değerler)."""

    def __init__(
        self,
        kap,
        *,
        bg: str,
        font_fn=None,
        tedarikci_modu: bool = False,
        pady: int = 0,
        kompakt: bool = False,
    ):
        self.kap = kap
        self.tedarikci_modu = tedarikci_modu
        self.degerler: dict[str, tk.Label] = {}
        self.basliklar: dict[str, tk.Label] = {}
        self.cari_id: int | None = None
        self._bekleyen = None
        # Diğer panellerdeki Entry ile uyumlu çerçeve iç boşluğu
        try:
            import fatura_tema as ftema

            _ip = max(1, ftema.form_ipady())
            if pady <= 0:
                pady = ftema.form_pady()
        except Exception:  # noqa: BLE001
            _ip = 2
        kap.columnconfigure(0, weight=0)
        kap.columnconfigure(1, weight=1)
        for satir, baslik in enumerate(OZET_SATIRLARI):
            # kompakt: vurgulu satırlar daha yüksek kutu oluşturmasın (fatura üst paneli)
            buyuk = (baslik in BUYUK_SATIRLAR) and not kompakt
            yazi = ("Segoe UI", 11 if buyuk else 9, "bold")
            if font_fn is not None:
                try:
                    yazi = font_fn(11 if buyuk else 9, "bold")
                except Exception:  # noqa: BLE001
                    pass
            lbl = tk.Label(kap, text=baslik, bg=bg, fg=LACIVERT, font=yazi, anchor="w", bd=0, padx=0, pady=0)
            lbl.grid(row=satir, column=0, sticky="w", padx=(0, 6), pady=pady)
            # Değer: diğer tek satırlık alanlarla uyumlu çerçeve; salt okunur, sağa hizalı
            cer = tk.Frame(
                kap,
                bg=BEYAZ,
                highlightthickness=1,
                highlightbackground=CIZGI,
                highlightcolor=CIZGI,
                bd=0,
            )
            cer.grid(row=satir, column=1, sticky="nsew", pady=pady)
            if kompakt:
                try:
                    import fatura_tema as ftema

                    cer.configure(height=ftema.form_satir_dis_yukseklik())
                    cer.grid_propagate(False)
                except Exception:  # noqa: BLE001
                    pass
            deger = tk.Label(
                cer, text="—", bg=BEYAZ, fg=LACIVERT, font=yazi, anchor="e", bd=0, padx=4, pady=_ip,
            )
            deger.pack(fill="both", expand=True)
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
