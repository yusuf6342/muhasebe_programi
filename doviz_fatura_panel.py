"""Satış faturası kartına döviz alanları entegrasyonu."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import tkinter as tk
from tkinter import messagebox, ttk

from database.doviz_service import DovizService, kur_turu_etiket
from database.models.doviz import BORC_ESASLARI, KUR_TURLERI, PARA_BIRIMLERI
from ui_takvim import takvim_butonu


def _para_goster(tutar, pb="TRY") -> str:
    try:
        d = Decimal(str(tutar or 0))
    except (InvalidOperation, TypeError):
        d = Decimal("0")
    metin = f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{metin} {pb}"


def doviz_paneli_kur(kart, ust_cerceve: ttk.LabelFrame) -> None:
    """Fatura kartına para birimi / kur panelini ekler."""
    kart._doviz_para_birimi = tk.StringVar(value="TRY")
    kart._doviz_kur_tarihi = tk.StringVar(value=datetime.now().strftime("%d.%m.%Y"))
    kart._doviz_kur_turu = tk.StringVar(value="forex_selling")
    kart._doviz_kur = tk.StringVar(value="1")
    kart._doviz_kur_kaynagi = tk.StringVar(value="TCMB")
    kart._doviz_borc_esasi = tk.StringVar(value="TL_SABIT")
    kart._doviz_sabitlendi = tk.BooleanVar(value=False)

    satir1 = ttk.Frame(ust_cerceve)
    satir1.pack(fill="x", pady=2)
    ttk.Label(satir1, text="Para Birimi:").pack(side="left", padx=(0, 4))
    pb_kutu = ttk.Combobox(
        satir1,
        textvariable=kart._doviz_para_birimi,
        values=("TRY", "USD", "EUR"),
        state="readonly",
        width=8,
    )
    pb_kutu.pack(side="left", padx=(0, 12))
    pb_kutu.bind("<<ComboboxSelected>>", lambda _e: doviz_para_birimi_degisti(kart))

    ttk.Label(satir1, text="Kur Tarihi:").pack(side="left", padx=(0, 4))
    kur_tarih = ttk.Entry(satir1, textvariable=kart._doviz_kur_tarihi, width=12)
    kur_tarih.pack(side="left")
    takvim_butonu(satir1, kur_tarih, lambda: doviz_kur_tarihi_degisti(kart))

    ttk.Label(satir1, text="Kur Türü:").pack(side="left", padx=(12, 4))
    kur_turu_kutu = ttk.Combobox(
        satir1,
        textvariable=kart._doviz_kur_turu,
        values=[k for k, _ in KUR_TURLERI],
        state="readonly",
        width=16,
    )
    kur_turu_kutu.pack(side="left")
    kur_turu_kutu.bind("<<ComboboxSelected>>", lambda _e: doviz_kuru_yenile(kart, sessiz=True))

    satir2 = ttk.Frame(ust_cerceve)
    satir2.pack(fill="x", pady=2)
    ttk.Label(satir2, text="Kur:").pack(side="left", padx=(0, 4))
    kart._doviz_kur_giris = ttk.Entry(satir2, textvariable=kart._doviz_kur, width=14)
    kart._doviz_kur_giris.pack(side="left")
    kart._doviz_kur_giris.bind("<FocusOut>", lambda _e: doviz_manuel_kur(kart))

    ttk.Button(satir2, text="TCMB'den Getir", command=lambda: doviz_tcmb_getir(kart)).pack(
        side="left", padx=6
    )
    ttk.Button(satir2, text="Kuru Sabitle", command=lambda: doviz_kuru_sabitle(kart)).pack(
        side="left", padx=4
    )

    kart._doviz_sabit_etiket = ttk.Label(satir2, text="", foreground="#2e7d32")
    kart._doviz_sabit_etiket.pack(side="left", padx=8)

    ttk.Label(satir2, text="Kaynak:").pack(side="left", padx=(12, 4))
    ttk.Label(satir2, textvariable=kart._doviz_kur_kaynagi, foreground="#555555").pack(side="left")

    satir3 = ttk.Frame(ust_cerceve)
    satir3.pack(fill="x", pady=2)
    ttk.Label(satir3, text="Borç Esası:").pack(side="left", padx=(0, 4))
    borc_kutu = ttk.Combobox(
        satir3,
        textvariable=kart._doviz_borc_esasi,
        values=[k for k, _ in BORC_ESASLARI],
        state="readonly",
        width=14,
    )
    borc_kutu.pack(side="left")

    kart._doviz_ozet_etiket = ttk.Label(
        satir3,
        text="TL yekün: matrah + KDV hesaplanır",
        foreground="#1565c0",
    )
    kart._doviz_ozet_etiket.pack(side="left", padx=(16, 0))

    doviz_para_birimi_degisti(kart)


def _fatura_tarihi_al(kart):
    for alan in ("fatura_tarihi", "siparis_tarihi", "iade_tarihi"):
        try:
            return datetime.strptime(kart.girdiler[alan].get(), "%d.%m.%Y").date()
        except (ValueError, KeyError, AttributeError, TypeError):
            continue
    try:
        return datetime.strptime(kart.tarih.get(), "%d.%m.%Y").date()
    except (ValueError, AttributeError, TypeError):
        pass
    return datetime.now().date()


def _fiyat_alani(kart, satir: dict | None = None) -> str:
    """Kart veya satırdaki birim fiyat anahtarını bulur."""
    ozel = getattr(kart, "_doviz_fiyat_alani", None)
    if ozel:
        return ozel
    if satir:
        if "birim_satis_fiyati" in satir:
            return "birim_satis_fiyati"
        if "birim_fiyat" in satir:
            return "birim_fiyat"
    girdiler = getattr(kart, "satir_girdileri", {}) or {}
    if "birim_satis_fiyati" in girdiler:
        return "birim_satis_fiyati"
    return "birim_fiyat"


def doviz_para_birimi_degisti(kart) -> None:
    pb = (kart._doviz_para_birimi.get() or "TRY").upper()
    if pb == "TRY":
        kart._doviz_kur.set("1")
        kart._doviz_kur_kaynagi.set("MANUEL")
        kart._doviz_sabitlendi.set(True)
        kart._doviz_kur_giris.configure(state="disabled")
        kart._doviz_sabit_etiket.configure(text="✓ TL fatura")
    else:
        kart._doviz_kur_giris.configure(state="normal")
        kart._doviz_sabitlendi.set(False)
        kart._doviz_sabit_etiket.configure(text="")
        if not kart._doviz_kur_tarihi.get().strip():
            kart._doviz_kur_tarihi.set(_fatura_tarihi_al(kart).strftime("%d.%m.%Y"))
        doviz_kuru_yenile(kart, sessiz=True)
    doviz_ozet_guncelle(kart)


def doviz_kur_tarihi_degisti(kart) -> None:
    doviz_kuru_yenile(kart, sessiz=True)


def doviz_kuru_yenile(kart, sessiz: bool = False) -> None:
    pb = (kart._doviz_para_birimi.get() or "TRY").upper()
    if pb == "TRY":
        kart._doviz_kur.set("1")
        return
    if kart._doviz_sabitlendi.get():
        return
    try:
        kur_tarihi = datetime.strptime(kart._doviz_kur_tarihi.get(), "%d.%m.%Y").date()
    except ValueError:
        if not sessiz:
            messagebox.showwarning("Kur", "Geçerli bir kur tarihi girin (GG.AA.YYYY).", parent=kart)
        return
    try:
        bilgi = DovizService.fatura_kur_bilgisi(
            pb,
            kur_tarihi,
            kart._doviz_kur_turu.get(),
        )
        kart._doviz_kur.set(str(bilgi["kur"]))
        kart._doviz_kur_kaynagi.set(bilgi["kur_kaynagi"])
    except ValueError as hata:
        if not sessiz:
            messagebox.showwarning("Kur", str(hata), parent=kart)


def doviz_tcmb_getir(kart) -> None:
    pb = (kart._doviz_para_birimi.get() or "TRY").upper()
    if pb == "TRY":
        messagebox.showinfo("Kur", "TL faturalarda kur gerekmez.", parent=kart)
        return
    try:
        kur_tarihi = datetime.strptime(kart._doviz_kur_tarihi.get(), "%d.%m.%Y").date()
    except ValueError:
        kur_tarihi = _fatura_tarihi_al(kart)
        kart._doviz_kur_tarihi.set(kur_tarihi.strftime("%d.%m.%Y"))
    try:
        kayitlar = DovizService.tcmb_kurlari_cek(kur_tarihi)
        hedef = next((k for k in kayitlar if k["currency_code"] == pb), None)
        if not hedef:
            raise ValueError(f"TCMB yanıtında {pb} kuru bulunamadı.")
        kur_turu = kart._doviz_kur_turu.get()
        kart._doviz_kur.set(str(hedef.get(kur_turu, hedef["forex_selling"])))
        kart._doviz_kur_kaynagi.set("TCMB")
        kart._doviz_sabitlendi.set(False)
        kart._doviz_sabit_etiket.configure(text="")
        doviz_satirlari_tl_cevir(kart)
        doviz_ozet_guncelle(kart)
        messagebox.showinfo(
            "Kur",
            f"{pb} kuru TCMB'den alındı: {kart._doviz_kur.get()}",
            parent=kart,
        )
    except ValueError as hata:
        messagebox.showerror("TCMB", str(hata), parent=kart)


def doviz_manuel_kur(kart) -> None:
    pb = (kart._doviz_para_birimi.get() or "TRY").upper()
    if pb == "TRY":
        return
    try:
        kur = Decimal(str(kart._doviz_kur.get().replace(",", ".")))
        if kur <= 0:
            raise ValueError
        kart._doviz_kur_kaynagi.set("MANUEL")
        kart._doviz_sabitlendi.set(False)
        kart._doviz_sabit_etiket.configure(text="")
        doviz_satirlari_tl_cevir(kart)
        doviz_ozet_guncelle(kart)
    except (ValueError, InvalidOperation):
        messagebox.showwarning("Kur", "Geçerli bir kur değeri girin.", parent=kart)


def doviz_kuru_sabitle(kart) -> None:
    pb = (kart._doviz_para_birimi.get() or "TRY").upper()
    if pb == "TRY":
        kart._doviz_sabitlendi.set(True)
        kart._doviz_sabit_etiket.configure(text="✓ Kur sabitlendi (TL)")
        return
    try:
        kur = Decimal(str(kart._doviz_kur.get().replace(",", ".")))
        if kur <= 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        messagebox.showwarning("Kur", "Önce geçerli bir kur girin.", parent=kart)
        return
    kart._doviz_sabitlendi.set(True)
    kaynak = kart._doviz_kur_kaynagi.get()
    if kaynak not in ("TCMB", "MANUEL", "OZEL"):
        kart._doviz_kur_kaynagi.set("MANUEL")
    kart._doviz_sabit_etiket.configure(
        text=f"✓ Kur sabitlendi ({pb} {kur} — {kur_turu_etiket(kart._doviz_kur_turu.get())})"
    )
    doviz_satirlari_tl_cevir(kart)
    doviz_ozet_guncelle(kart)


def doviz_satirlari_tl_cevir(kart) -> None:
    """Döviz birim fiyatlarını TL'ye çevirip mevcut satır listesini günceller."""
    pb = (kart._doviz_para_birimi.get() or "TRY").upper()
    if pb == "TRY":
        return
    try:
        kur = Decimal(str(kart._doviz_kur.get().replace(",", ".")))
    except (InvalidOperation, ValueError):
        return
    for satir in getattr(kart, "satirlar", []):
        alan = _fiyat_alani(kart, satir)
        bf_doviz = satir.get("birim_fiyat_doviz")
        if bf_doviz is None:
            bf_doviz = satir.get(alan, 0)
            satir["birim_fiyat_doviz"] = bf_doviz
        try:
            bf_doviz = Decimal(str(bf_doviz or 0))
        except (InvalidOperation, TypeError):
            bf_doviz = Decimal("0")
        if bf_doviz > 0:
            tl_bf = DovizService.dovizden_tle(bf_doviz, kur, Decimal("0.0001"))
            satir[alan] = tl_bf
            if alan == "birim_fiyat":
                satir["birim_alis_fiyati"] = tl_bf
            satir["birim_fiyat_doviz"] = bf_doviz
    if hasattr(kart, "_satir_listesini_yenile"):
        kart._satir_listesini_yenile()
    if hasattr(kart, "_bakiye_guncelle"):
        kart._bakiye_guncelle()
    if hasattr(kart, "_toplamlari_guncelle"):
        try:
            kart._toplamlari_guncelle()
        except Exception:
            pass


def doviz_ozet_guncelle(kart) -> None:
    etiket = getattr(kart, "_doviz_ozet_etiket", None)
    if etiket is None:
        return
    pb = (kart._doviz_para_birimi.get() or "TRY").upper()
    if pb == "TRY":
        etiket.configure(text="TL fatura — birim fiyatlar TL cinsindendir.")
        return
    try:
        kur = Decimal(str(kart._doviz_kur.get().replace(",", ".")))
    except (InvalidOperation, ValueError):
        etiket.configure(text=f"{pb} fatura — kur girin")
        return
    etiket.configure(
        text=f"{pb} birim fiyat × {kur} = TL matrah/KDV/yekün hesaplanır"
    )


def doviz_verilerini_topla(kart) -> dict:
    pb = (kart._doviz_para_birimi.get() or "TRY").upper()
    kur = Decimal(str((kart._doviz_kur.get() or "1").replace(",", ".")))
    kur_tarihi = None
    if pb != "TRY":
        try:
            kur_tarihi = datetime.strptime(kart._doviz_kur_tarihi.get(), "%d.%m.%Y").date()
        except ValueError as hata:
            raise ValueError("Geçerli bir kur tarihi girin.") from hata
        if kur <= 0:
            raise ValueError("Kur sıfırdan büyük olmalıdır.")
        if not kart._doviz_sabitlendi.get():
            raise ValueError("Kaydetmeden önce kuru sabitleyin (Kuru Sabitle).")
    doviz_ara = Decimal("0")
    if pb != "TRY":
        for satir in getattr(kart, "satirlar", []):
            alan = _fiyat_alani(kart, satir)
            bf = Decimal(str(satir.get("birim_fiyat_doviz") or satir.get(alan) or 0))
            miktar = Decimal(str(satir.get("miktar") or 0))
            isk1 = Decimal(str(satir.get("iskonto_orani", 0) or 0))
            isk2 = Decimal(str(satir.get("iskonto_orani_2", 0) or 0))
            isk3 = Decimal(str(satir.get("iskonto_orani_3", 0) or 0))
            net = bf
            for isk in (isk1, isk2, isk3):
                if isk:
                    net = net * (Decimal("1") - isk / Decimal("100"))
            doviz_ara += miktar * net
    return {
        "para_birimi": pb,
        "kur": kur,
        "kur_tarihi": kur_tarihi or _fatura_tarihi_al(kart),
        "kur_turu": kart._doviz_kur_turu.get(),
        "kur_kaynagi": kart._doviz_kur_kaynagi.get(),
        "kur_sabitlendi": kart._doviz_sabitlendi.get(),
        "borc_esasi": kart._doviz_borc_esasi.get(),
        "doviz_ara_toplam": doviz_ara.quantize(Decimal("0.01")),
    }


def doviz_verilerini_doldur(kart, fatura) -> None:
    if not hasattr(kart, "_doviz_para_birimi"):
        return
    pb = (getattr(fatura, "para_birimi", None) or "TRY").upper()
    kart._doviz_para_birimi.set(pb)
    kart._doviz_kur.set(str(getattr(fatura, "kur", 1) or 1))
    kt = getattr(fatura, "kur_tarihi", None)
    kart._doviz_kur_tarihi.set(
        kt.strftime("%d.%m.%Y") if kt else _fatura_tarihi_al(kart).strftime("%d.%m.%Y")
    )
    kart._doviz_kur_turu.set(getattr(fatura, "kur_turu", "forex_selling") or "forex_selling")
    kart._doviz_kur_kaynagi.set(getattr(fatura, "kur_kaynagi", "TCMB") or "TCMB")
    kart._doviz_borc_esasi.set(getattr(fatura, "borc_esasi", "TL_SABIT") or "TL_SABIT")
    sabit = bool(getattr(fatura, "kur_sabitlendi", False))
    kart._doviz_sabitlendi.set(sabit)
    if sabit:
        kart._doviz_sabit_etiket.configure(
            text=f"✓ Kur sabitlendi ({pb} {getattr(fatura, 'kur', 1)})"
        )
    doviz_para_birimi_degisti(kart)


def doviz_satir_kaydet_oncesi(kart, satir: dict) -> dict:
    """Satır eklerken döviz birim fiyatını saklar."""
    pb = (getattr(kart, "_doviz_para_birimi", None) and kart._doviz_para_birimi.get() or "TRY").upper()
    if pb == "TRY":
        return satir
    alan = _fiyat_alani(kart, satir)
    try:
        bf = Decimal(str(satir.get(alan) or 0))
    except (InvalidOperation, TypeError):
        bf = Decimal("0")
    satir = dict(satir)
    satir["birim_fiyat_doviz"] = bf
    try:
        kur = Decimal(str(kart._doviz_kur.get().replace(",", ".")))
        tl = DovizService.dovizden_tle(bf, kur, Decimal("0.0001"))
        satir[alan] = tl
        if alan == "birim_fiyat":
            satir["birim_alis_fiyati"] = tl
        elif alan == "birim_satis_fiyati":
            satir["birim_fiyat"] = tl
    except (InvalidOperation, ValueError):
        pass
    return satir
