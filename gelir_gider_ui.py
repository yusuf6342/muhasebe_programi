"""GELİR VE GİDERLER menüsü — hizmet kartları + fatura/iade/rapor iskeleti."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, ttk

from database.hizmet_service import HizmetService
from database.models.hizmet import (
    GIDER_SINIFLARI,
    HIZMET_BIRIMLERI,
    KDV_ORANLARI,
    gider_sinifi_etiket,
)
from hizmet_fatura_ui import HizmetFaturaDialog
from database.hizmet_faturasi_service import HizmetFaturasiService


def _para(tutar):
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(t):
    return t.strftime("%d.%m.%Y") if t else ""


def _menu_isaretle(app, anahtar="gelir_gider"):
    for dugme_anahtari, dugme in app.menu_dugmeleri.items():
        dugme.configure(
            style="SeciliMenu.TButton" if dugme_anahtari == anahtar else "Menu.TButton"
        )


def gelir_gider_menusu_goster(app):
    app._icerigi_temizle()
    _menu_isaretle(app)
    ttk.Label(app.icerik, text="GELİR VE GİDERLER", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text="Gider ve gelir hizmetleri, faturalar ve raporlar.",
    ).pack(anchor="w", pady=(8, 0))
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(24, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    for i, (baslik, komut) in enumerate((
        ("GİDERLER", lambda: giderler_menusu_goster(app)),
        ("GELİRLER", lambda: gelirler_menusu_goster(app)),
    )):
        ttk.Button(alt, text=baslik, style="AltMenu.TButton", command=komut).grid(
            row=i, column=0, sticky="ew", pady=4
        )


def giderler_menusu_goster(app):
    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="GİDERLER", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Gelir ve Giderler", command=lambda: gelir_gider_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(
        app.icerik,
        text="Gider hizmet kartları, gider faturaları ve raporlar.",
    ).pack(anchor="w", pady=(10, 0))
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(20, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    for i, (baslik, komut) in enumerate((
        ("GİDER HİZMET KARTLARI", lambda: hizmet_kartlari_sayfasi(app, "GIDER")),
        (
            "HİZMET ALIŞ (GİDER) FATURASI",
            lambda: hizmet_faturalari_sayfasi(app, "GIDER"),
        ),
        ("GİDER FİŞİ", lambda: _gider_fisi_ac(app)),
        (
            "HİZMET ALIŞ (GİDER) İADE FATURASI",
            lambda: _yer_tutucu(app, "HİZMET ALIŞ (GİDER) İADE FATURASI", giderler_menusu_goster),
        ),
        ("GİDER RAPORU", lambda: _yer_tutucu(app, "GİDER RAPORU", giderler_menusu_goster)),
    )):
        ttk.Button(alt, text=baslik, style="AltMenu.TButton", command=komut).grid(
            row=i, column=0, sticky="ew", pady=4
        )


def gelirler_menusu_goster(app):
    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="GELİRLER", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Gelir ve Giderler", command=lambda: gelir_gider_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(
        app.icerik,
        text="Gelir hizmet kartları, gelir faturaları ve raporlar.",
    ).pack(anchor="w", pady=(10, 0))
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(20, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    for i, (baslik, komut) in enumerate((
        ("GELİR HİZMET KARTLARI", lambda: hizmet_kartlari_sayfasi(app, "GELIR")),
        (
            "HİZMET SATIŞ (GELİR) FATURASI",
            lambda: hizmet_faturalari_sayfasi(app, "GELIR"),
        ),
        (
            "HİZMET SATIŞ (GELİR) İADE FATURASI",
            lambda: _yer_tutucu(app, "HİZMET SATIŞ (GELİR) İADE FATURASI", gelirler_menusu_goster),
        ),
        ("GELİR RAPORU", lambda: _yer_tutucu(app, "GELİR RAPORU", gelirler_menusu_goster)),
    )):
        ttk.Button(alt, text=baslik, style="AltMenu.TButton", command=komut).grid(
            row=i, column=0, sticky="ew", pady=4
        )


def _yer_tutucu(app, baslik, geri_fn):
    app._icerigi_temizle()
    _menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Geri", command=lambda: geri_fn(app)).pack(side="right")
    ttk.Label(
        app.icerik,
        text="Bu bölüm sonraki aşamada detaylandırılacak (kuruluş iskeleti hazır).",
        wraplength=700,
    ).pack(anchor="w", pady=(24, 0))


def _gider_fisi_ac(app):
    from gider_fisi_ui import gider_fisleri_sayfasi

    gider_fisleri_sayfasi(app, geri_fn=giderler_menusu_goster)


def hizmet_faturalari_sayfasi(app, fatura_turu: str):
    app._icerigi_temizle()
    _menu_isaretle(app)
    gider_mi = (fatura_turu or "").upper() == "GIDER"
    baslik = (
        "HİZMET ALIŞ (GİDER) FATURALARI"
        if gider_mi
        else "HİZMET SATIŞ (GELİR) FATURALARI"
    )
    geri = giderler_menusu_goster if gider_mi else gelirler_menusu_goster

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Geri", command=lambda: geri(app)).pack(side="right")

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True, pady=10)
    tablo = ttk.Treeview(
        cerceve,
        columns=("no", "tarih", "cari", "toplam", "odeme", "durum"),
        show="headings",
        selectmode="browse",
    )
    odeme_baslik = "Ödeme" if gider_mi else "Tahsilat"
    for k, b, w in (
        ("no", "Fatura No", 110),
        ("tarih", "Tarih", 90),
        ("cari", "Cari", 220),
        ("toplam", "Genel Toplam", 110),
        ("odeme", odeme_baslik, 110),
        ("durum", "Durum", 80),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")

    def listeyi_yenile():
        for item in tablo.get_children():
            tablo.delete(item)
        for kayit in HizmetFaturasiService.listele(fatura_turu):
            f = kayit["fatura"]
            cari_ad = f"{f.cari.cari_kodu} - {f.cari.unvan}" if f.cari else "—"
            tablo.insert(
                "",
                "end",
                iid=str(f.id),
                values=(
                    f.fatura_no,
                    _tarih(f.fatura_tarihi),
                    cari_ad,
                    _para(kayit["genel_toplam"]),
                    _para(f.odeme_tutari),
                    f.durum,
                ),
            )

    def yeni():
        dlg = HizmetFaturaDialog(app, hizmet_turu=fatura_turu)
        app.wait_window(dlg)
        if dlg.result:
            listeyi_yenile()

    def ac():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Bir fatura seçin.", parent=app)
            return
        dlg = HizmetFaturaDialog(app, hizmet_turu=fatura_turu, fatura_id=int(secim[0]))
        app.wait_window(dlg)
        if dlg.result:
            listeyi_yenile()

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=6)
    ttk.Button(butonlar, text="Yeni Fatura", command=yeni).pack(side="left", padx=(0, 6))
    ttk.Button(butonlar, text="Aç / Düzenle", command=ac).pack(side="left", padx=6)
    ttk.Button(butonlar, text="Yenile", command=listeyi_yenile).pack(side="left", padx=6)
    tablo.bind("<Double-1>", lambda _e: ac())
    listeyi_yenile()


def hizmet_kartlari_sayfasi(app, hizmet_turu: str):
    app._icerigi_temizle()
    _menu_isaretle(app)
    gider_mi = (hizmet_turu or "").upper() == "GIDER"
    baslik = "GİDER HİZMET KARTLARI" if gider_mi else "GELİR HİZMET KARTLARI"
    geri = giderler_menusu_goster if gider_mi else gelirler_menusu_goster

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Geri", command=lambda: geri(app)).pack(side="right")

    ttk.Label(
        app.icerik,
        text=(
            "Gider kartları 4 sınıfa ayrılır (işletme / personel / finans-mali / araç). "
            "Çift tık = kart + hareketler."
            if gider_mi
            else "Hizmet kartı: kod, ad, alış/satış fiyatı, muhasebe kodları. Çift tık = kart + hareketler."
        ),
    ).pack(anchor="w", pady=(10, 4))

    arac = ttk.Frame(app.icerik)
    arac.pack(fill="x", pady=4)
    ttk.Label(arac, text="Ara:").pack(side="left")
    arama = ttk.Entry(arac, width=28)
    arama.pack(side="left", padx=6)

    sinif_filtre = None
    sinif_kodlar = {etiket: kod for kod, etiket in GIDER_SINIFLARI}
    if gider_mi:
        ttk.Label(arac, text="Sınıf:").pack(side="left", padx=(12, 0))
        sinif_filtre = ttk.Combobox(
            arac,
            values=["Tümü"] + [e for _, e in GIDER_SINIFLARI],
            width=26,
            state="readonly",
        )
        sinif_filtre.set("Tümü")
        sinif_filtre.pack(side="left", padx=6)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True, pady=6)
    if gider_mi:
        kolonlar = ("kod", "ad", "sinif", "birim", "alis", "satis", "kdv", "muh", "aktif")
        basliklar = (
            ("kod", "Hizmet kodu", 100),
            ("ad", "Hizmet adı", 200),
            ("sinif", "Gider sınıfı", 160),
            ("birim", "Birim", 70),
            ("alis", "Alış fiyatı", 100),
            ("satis", "Satış fiyatı", 100),
            ("kdv", "KDV %", 60),
            ("muh", "Muhasebe", 120),
            ("aktif", "Durum", 70),
        )
    else:
        kolonlar = ("kod", "ad", "birim", "alis", "satis", "kdv", "muh", "aktif")
        basliklar = (
            ("kod", "Hizmet kodu", 110),
            ("ad", "Hizmet adı", 220),
            ("birim", "Birim", 70),
            ("alis", "Alış fiyatı", 100),
            ("satis", "Satış fiyatı", 100),
            ("kdv", "KDV %", 60),
            ("muh", "Muhasebe", 140),
            ("aktif", "Durum", 70),
        )
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    for k, b, w in basliklar:
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")

    ozet = ttk.Label(app.icerik, text="")
    ozet.pack(anchor="w", pady=4)

    def secili_sinif():
        if not sinif_filtre:
            return None
        secim = sinif_filtre.get()
        if not secim or secim == "Tümü":
            return None
        return sinif_kodlar.get(secim)

    def listeyi_yenile():
        for item in tablo.get_children():
            tablo.delete(item)
        kayitlar = HizmetService.listele(
            hizmet_turu=hizmet_turu,
            aktif_only=False,
            arama=arama.get().strip() or None,
            gider_sinifi=secili_sinif(),
        )
        for h in kayitlar:
            muh = h.muhasebe_gider_kodu if gider_mi else h.muhasebe_gelir_kodu
            if gider_mi:
                degerler = (
                    h.hizmet_kodu,
                    h.hizmet_adi,
                    gider_sinifi_etiket(h.gider_sinifi),
                    h.birim or "",
                    _para(h.alis_fiyati),
                    _para(h.satis_fiyati),
                    f"{float(h.kdv_orani or 0):g}",
                    muh or "—",
                    "Aktif" if h.aktif else "Pasif",
                )
            else:
                degerler = (
                    h.hizmet_kodu,
                    h.hizmet_adi,
                    h.birim or "",
                    _para(h.alis_fiyati),
                    _para(h.satis_fiyati),
                    f"{float(h.kdv_orani or 0):g}",
                    muh or "—",
                    "Aktif" if h.aktif else "Pasif",
                )
            tablo.insert("", "end", iid=str(h.id), values=degerler)
        ozet.configure(text=f"{len(kayitlar)} hizmet kartı")

    def secili():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Bir hizmet kartı seçin.", parent=app)
            return None
        return int(secim[0])

    def yeni():
        dialog = HizmetKartiDialog(app, hizmet_turu=hizmet_turu)
        app.wait_window(dialog)
        if dialog.result:
            listeyi_yenile()

    def duzenle():
        hid = secili()
        if hid is None:
            return
        dialog = HizmetKartiDialog(app, hizmet_turu=hizmet_turu, hizmet_id=hid)
        app.wait_window(dialog)
        if dialog.result:
            listeyi_yenile()

    def pasif():
        hid = secili()
        if hid is None:
            return
        if not messagebox.askyesno("Pasif", "Kart pasif yapılsın mı?", parent=app):
            return
        try:
            HizmetService.pasif_yap(hid)
        except ValueError as hata:
            messagebox.showerror("Hizmet", str(hata), parent=app)
            return
        listeyi_yenile()

    def fatura():
        hid = secili()
        if hid is None:
            return
        dlg = HizmetFaturaDialog(app, hizmet_turu=hizmet_turu, hizmet_id=hid)
        app.wait_window(dlg)

    fatura_etiket = (
        "HİZMET ALIŞ (GİDER) FATURASI" if gider_mi else "HİZMET SATIŞ (GELİR) FATURASI"
    )
    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=6)
    ttk.Button(butonlar, text="Yeni Kart", command=yeni).pack(side="left", padx=(0, 6))
    ttk.Button(butonlar, text="Düzenle / Hareketler", command=duzenle).pack(side="left", padx=6)
    ttk.Button(butonlar, text=fatura_etiket, command=fatura).pack(side="left", padx=6)
    ttk.Button(butonlar, text="Pasif Yap", command=pasif).pack(side="left", padx=6)
    ttk.Button(butonlar, text="Yenile", command=listeyi_yenile).pack(side="left", padx=6)

    arama.bind("<KeyRelease>", lambda _e: listeyi_yenile())
    if sinif_filtre:
        sinif_filtre.bind("<<ComboboxSelected>>", lambda _e: listeyi_yenile())
    tablo.bind("<Double-1>", lambda _e: duzenle())
    listeyi_yenile()


class HizmetKartiDialog(tk.Toplevel):
    """Hizmet kartı: tanım alanları + hareket listesi."""

    def __init__(self, parent, hizmet_turu="GIDER", hizmet_id=None):
        super().__init__(parent)
        self.hizmet_turu = (hizmet_turu or "GIDER").upper()
        self.hizmet_id = hizmet_id
        self.result = None
        etiket = "Gider" if self.hizmet_turu == "GIDER" else "Gelir"
        self.title(
            f"{etiket} Hizmet Kartı" + (" — Düzenle" if hizmet_id else " — Yeni")
        )
        self.geometry("920x680")
        self.minsize(860, 600)
        self.transient(parent)
        self.grab_set()

        mevcut = HizmetService.getir(hizmet_id) if hizmet_id else None

        kayit = ttk.Frame(self, padding=(12, 8))
        kayit.pack(side="bottom", fill="x")
        fatura_etiket = (
            "HİZMET ALIŞ (GİDER) FATURASI"
            if self.hizmet_turu == "GIDER"
            else "HİZMET SATIŞ (GELİR) FATURASI"
        )
        ttk.Button(kayit, text=fatura_etiket, command=self.fatura_ac).pack(side="left")
        ttk.Button(kayit, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(kayit, text="Kaydet", width=14, command=self.kaydet).pack(side="right")

        ust = ttk.Frame(self, padding=12)
        ust.pack(fill="both", expand=True)

        form = ttk.LabelFrame(ust, text="Hizmet bilgileri", padding=10)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        self.alanlar = {}
        self._sinif_etiket_kod = {etiket: kod for kod, etiket in GIDER_SINIFLARI}
        self._sinif_kod_etiket = {kod: etiket for kod, etiket in GIDER_SINIFLARI}
        self._kod_otomatik = not bool(hizmet_id)

        ttk.Label(form, text="Hizmet kodu *").grid(row=0, column=0, sticky="w", pady=3, padx=4)
        self.alanlar["hizmet_kodu"] = ttk.Entry(form, width=18)
        self.alanlar["hizmet_kodu"].grid(row=0, column=1, sticky="w", padx=4, pady=3)

        ttk.Label(form, text="Hizmet adı *").grid(row=0, column=2, sticky="w", pady=3, padx=4)
        self.alanlar["hizmet_adi"] = ttk.Entry(form, width=36)
        self.alanlar["hizmet_adi"].grid(row=0, column=3, sticky="ew", padx=4, pady=3)

        satir = 1
        if self.hizmet_turu == "GIDER":
            ttk.Label(form, text="Gider sınıfı *").grid(
                row=satir, column=0, sticky="w", pady=3, padx=4
            )
            self.alanlar["gider_sinifi"] = ttk.Combobox(
                form,
                values=[e for _, e in GIDER_SINIFLARI],
                width=26,
                state="readonly",
            )
            self.alanlar["gider_sinifi"].grid(row=satir, column=1, columnspan=3, sticky="w", padx=4, pady=3)
            self.alanlar["gider_sinifi"].set(self._sinif_kod_etiket["ISLETME"])
            self.alanlar["gider_sinifi"].bind("<<ComboboxSelected>>", self._sinif_degisti)
            satir += 1

        ttk.Label(form, text="Birim").grid(row=satir, column=0, sticky="w", pady=3, padx=4)
        self.alanlar["birim"] = ttk.Combobox(form, values=list(HIZMET_BIRIMLERI), width=16)
        self.alanlar["birim"].grid(row=satir, column=1, sticky="w", padx=4, pady=3)
        self.alanlar["birim"].set("Adet")

        ttk.Label(form, text="KDV %").grid(row=satir, column=2, sticky="w", pady=3, padx=4)
        self.alanlar["kdv_orani"] = ttk.Combobox(form, values=list(KDV_ORANLARI), width=10)
        self.alanlar["kdv_orani"].grid(row=satir, column=3, sticky="w", padx=4, pady=3)
        self.alanlar["kdv_orani"].set("20")
        satir += 1

        ttk.Label(form, text="Alış fiyatı").grid(row=satir, column=0, sticky="w", pady=3, padx=4)
        self.alanlar["alis_fiyati"] = ttk.Entry(form, width=16)
        self.alanlar["alis_fiyati"].grid(row=satir, column=1, sticky="w", padx=4, pady=3)

        ttk.Label(form, text="Satış fiyatı").grid(row=satir, column=2, sticky="w", pady=3, padx=4)
        self.alanlar["satis_fiyati"] = ttk.Entry(form, width=16)
        self.alanlar["satis_fiyati"].grid(row=satir, column=3, sticky="w", padx=4, pady=3)
        satir += 1

        muh = ttk.LabelFrame(ust, text="Muhasebe hesap kodları", padding=10)
        muh.pack(fill="x", pady=(8, 0))
        muh.columnconfigure(1, weight=1)
        muh.columnconfigure(3, weight=1)

        ttk.Label(muh, text="Gider muhasebe kodu").grid(row=0, column=0, sticky="w", pady=3, padx=4)
        self.alanlar["muhasebe_gider_kodu"] = ttk.Entry(muh, width=18)
        self.alanlar["muhasebe_gider_kodu"].grid(row=0, column=1, sticky="w", padx=4, pady=3)

        ttk.Label(muh, text="Gelir muhasebe kodu").grid(row=0, column=2, sticky="w", pady=3, padx=4)
        self.alanlar["muhasebe_gelir_kodu"] = ttk.Entry(muh, width=18)
        self.alanlar["muhasebe_gelir_kodu"].grid(row=0, column=3, sticky="w", padx=4, pady=3)

        ttk.Label(muh, text="KDV alış kodu").grid(row=1, column=0, sticky="w", pady=3, padx=4)
        self.alanlar["muhasebe_kdv_alis_kodu"] = ttk.Entry(muh, width=18)
        self.alanlar["muhasebe_kdv_alis_kodu"].grid(row=1, column=1, sticky="w", padx=4, pady=3)

        ttk.Label(muh, text="KDV satış kodu").grid(row=1, column=2, sticky="w", pady=3, padx=4)
        self.alanlar["muhasebe_kdv_satis_kodu"] = ttk.Entry(muh, width=18)
        self.alanlar["muhasebe_kdv_satis_kodu"].grid(row=1, column=3, sticky="w", padx=4, pady=3)

        ttk.Label(form, text="Açıklama").grid(row=satir, column=0, sticky="w", pady=3, padx=4)
        self.alanlar["aciklama"] = ttk.Entry(form)
        self.alanlar["aciklama"].grid(row=satir, column=1, columnspan=3, sticky="ew", padx=4, pady=3)

        if mevcut:
            self.alanlar["hizmet_kodu"].insert(0, mevcut.hizmet_kodu or "")
            self.alanlar["hizmet_adi"].insert(0, mevcut.hizmet_adi or "")
            if "gider_sinifi" in self.alanlar:
                self.alanlar["gider_sinifi"].set(
                    self._sinif_kod_etiket.get(
                        (mevcut.gider_sinifi or "ISLETME").upper(),
                        self._sinif_kod_etiket["ISLETME"],
                    )
                )
            self.alanlar["birim"].set(mevcut.birim or "Adet")
            self.alanlar["kdv_orani"].set(f"{float(mevcut.kdv_orani or 0):g}")
            self.alanlar["alis_fiyati"].insert(0, f"{Decimal(str(mevcut.alis_fiyati or 0)):g}")
            self.alanlar["satis_fiyati"].insert(0, f"{Decimal(str(mevcut.satis_fiyati or 0)):g}")
            self.alanlar["muhasebe_gider_kodu"].insert(0, mevcut.muhasebe_gider_kodu or "")
            self.alanlar["muhasebe_gelir_kodu"].insert(0, mevcut.muhasebe_gelir_kodu or "")
            self.alanlar["muhasebe_kdv_alis_kodu"].insert(0, mevcut.muhasebe_kdv_alis_kodu or "")
            self.alanlar["muhasebe_kdv_satis_kodu"].insert(0, mevcut.muhasebe_kdv_satis_kodu or "")
            self.alanlar["aciklama"].insert(0, mevcut.aciklama or "")
        else:
            self._kodu_yenile()
            self.alanlar["alis_fiyati"].insert(0, "0")
            self.alanlar["satis_fiyati"].insert(0, "0")

        self.alanlar["hizmet_kodu"].bind("<Key>", lambda _e: setattr(self, "_kod_otomatik", False))

        har_f = ttk.LabelFrame(ust, text="Hizmet hareketleri", padding=8)
        har_f.pack(fill="both", expand=True, pady=(10, 0))
        arac = ttk.Frame(har_f)
        arac.pack(fill="x", pady=(0, 4))
        ttk.Button(arac, text="Yenile", command=self.hareketleri_yenile).pack(side="right")
        ttk.Label(
            arac,
            text="Fatura / iade belgelerinden gelen hareketler burada listelenir.",
            foreground="#555",
        ).pack(side="left")

        cerceve = ttk.Frame(har_f)
        cerceve.pack(fill="both", expand=True)
        self.hareket_tablo = ttk.Treeview(
            cerceve,
            columns=("tarih", "tur", "belge", "miktar", "fiyat", "tutar", "aciklama"),
            show="headings",
            height=10,
        )
        for k, b, w in (
            ("tarih", "Tarih", 90),
            ("tur", "Hareket", 130),
            ("belge", "Belge", 120),
            ("miktar", "Miktar", 80),
            ("fiyat", "Birim fiyat", 100),
            ("tutar", "Tutar", 100),
            ("aciklama", "Açıklama", 220),
        ):
            self.hareket_tablo.heading(k, text=b)
            self.hareket_tablo.column(k, width=w, anchor="w")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.hareket_tablo.yview)
        self.hareket_tablo.configure(yscrollcommand=kaydir.set)
        self.hareket_tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        self.hareketleri_yenile()

    def _secili_gider_sinifi_kodu(self):
        if "gider_sinifi" not in self.alanlar:
            return None
        return self._sinif_etiket_kod.get(self.alanlar["gider_sinifi"].get())

    def _kodu_yenile(self):
        if not self._kod_otomatik:
            return
        kod = HizmetService.otomatik_kod(
            self.hizmet_turu, self._secili_gider_sinifi_kodu()
        )
        self.alanlar["hizmet_kodu"].delete(0, "end")
        self.alanlar["hizmet_kodu"].insert(0, kod)

    def _sinif_degisti(self, _event=None):
        if not self.hizmet_id:
            self._kod_otomatik = True
            self._kodu_yenile()

    def hareketleri_yenile(self):
        for item in self.hareket_tablo.get_children():
            self.hareket_tablo.delete(item)
        if not self.hizmet_id:
            return
        for h in HizmetService.hareketler(self.hizmet_id):
            self.hareket_tablo.insert(
                "",
                "end",
                values=(
                    _tarih(h.tarih),
                    h.hareket_turu,
                    h.belge_no,
                    f"{float(h.miktar or 0):g}",
                    _para(h.birim_fiyat),
                    _para(h.tutar),
                    h.aciklama or "",
                ),
            )

    def kaydet(self, sessiz=False):
        veri = {}
        for k, w in self.alanlar.items():
            if k == "gider_sinifi":
                veri[k] = self._secili_gider_sinifi_kodu() or ""
            else:
                veri[k] = w.get().strip() if hasattr(w, "get") else ""
        veri["hizmet_turu"] = self.hizmet_turu
        if self.hizmet_id:
            veri["hizmet_id"] = self.hizmet_id
        try:
            self.result = HizmetService.kaydet(veri)
        except ValueError as hata:
            messagebox.showerror("Hizmet", str(hata), parent=self)
            return False
        self.hizmet_id = self.result.id
        if not sessiz:
            messagebox.showinfo(
                "Kaydedildi",
                f"{self.result.hizmet_kodu} — {self.result.hizmet_adi}",
                parent=self,
            )
            self.hareketleri_yenile()
        return True

    def fatura_ac(self):
        if not self.hizmet_id:
            if not messagebox.askyesno(
                "Kaydet",
                "Fatura için önce kart kaydedilsin mi?",
                parent=self,
            ):
                return
            if not self.kaydet(sessiz=True):
                return
        dlg = HizmetFaturaDialog(
            self,
            hizmet_turu=self.hizmet_turu,
            hizmet_id=self.hizmet_id,
        )
        self.wait_window(dlg)
        self.hareketleri_yenile()
        self.title(f"{'Gider' if self.hizmet_turu == 'GIDER' else 'Gelir'} Hizmet Kartı — Düzenle")
