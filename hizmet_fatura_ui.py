"""Hizmet alış / satış fatura diyalogları — sade standart fatura."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal
from tkinter import messagebox, ttk

from database.finans_service import FinansService
from database.hizmet_faturasi_service import (
    ODEME_SEKILLERI,
    TAHSILAT_SEKILLERI,
    HizmetFaturasiService,
)
from database.hizmet_service import HizmetService
from database.models.hizmet import HIZMET_BIRIMLERI, KDV_ORANLARI
from database.satis_siparisi_service import decimal
from ui_takvim import saat_dogrula, saat_varsayilan, tarih_alani


def _para(tutar):
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(t):
    return t.strftime("%d.%m.%Y") if t else ""


def _satir_toplam(satir) -> Decimal:
    miktar = decimal(satir["miktar"], "Miktar")
    fiyat = decimal(satir["birim_fiyat"], "Birim fiyat")
    isk = decimal(satir.get("iskonto_orani", 0), "İskonto")
    kdv = decimal(satir.get("kdv_orani", 0), "KDV")
    net = miktar * fiyat - (miktar * fiyat * isk / Decimal("100"))
    return (net + net * kdv / Decimal("100")).quantize(Decimal("0.01"))


class HizmetSecDialog(tk.Toplevel):
    def __init__(self, parent, hizmet_turu="GIDER", arama=""):
        super().__init__(parent)
        self.result = None
        self.hizmet_turu = (hizmet_turu or "GIDER").upper()
        self.title("Hizmet Seç")
        self.geometry("640x420")
        self.transient(parent)
        self.grab_set()

        ust = ttk.Frame(self, padding=8)
        ust.pack(fill="x")
        ttk.Label(ust, text="Ara:").pack(side="left")
        self.arama = ttk.Entry(ust, width=36)
        self.arama.pack(side="left", padx=6)
        if arama:
            self.arama.insert(0, arama)
        ttk.Button(ust, text="Yenile", command=self.yenile).pack(side="left")

        cerceve = ttk.Frame(self, padding=8)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=("kod", "ad", "birim", "fiyat", "kdv"),
            show="headings",
            selectmode="browse",
        )
        for k, b, w in (
            ("kod", "Kod", 100),
            ("ad", "Ad", 240),
            ("birim", "Birim", 70),
            ("fiyat", "Fiyat", 100),
            ("kdv", "KDV %", 60),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w)
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        self.tablo.bind("<Double-1>", lambda _e: self.sec())

        alt = ttk.Frame(self, padding=8)
        alt.pack(fill="x")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Seç", command=self.sec).pack(side="right", padx=8)

        self.arama.bind("<KeyRelease>", lambda _e: self.yenile())
        self.yenile()

    def yenile(self):
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        gider_mi = self.hizmet_turu == "GIDER"
        for h in HizmetService.listele(
            hizmet_turu=self.hizmet_turu,
            aktif_only=True,
            arama=self.arama.get().strip() or None,
        ):
            fiyat = h.alis_fiyati if gider_mi else h.satis_fiyati
            self.tablo.insert(
                "",
                "end",
                iid=str(h.id),
                values=(
                    h.hizmet_kodu,
                    h.hizmet_adi,
                    h.birim or "",
                    f"{float(fiyat or 0):g}",
                    f"{float(h.kdv_orani or 0):g}",
                ),
            )

    def sec(self):
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Bir hizmet seçin.", parent=self)
            return
        self.result = HizmetService.getir(int(secim[0]))
        self.destroy()


class HizmetOdemeDialog(tk.Toplevel):
    def __init__(self, parent, gelir_mi=False, kayit=None):
        super().__init__(parent)
        self.result = None
        self.gelir_mi = gelir_mi
        self.title("Tahsilat" if gelir_mi else "Ödeme")
        self.geometry("420x240")
        self.transient(parent)
        self.grab_set()
        self.girdiler = {}
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        sekiller = TAHSILAT_SEKILLERI if gelir_mi else ODEME_SEKILLERI
        hesaplar = [h.hesap_adi for h in FinansService.hesaplar()]
        for sira, (etiket, alan) in enumerate((
            ("Tarih", "tarih"),
            ("Tutar", "tutar"),
            ("Şekil", "odeme_sekli"),
            ("Hesap", "hesap"),
            ("Açıklama", "aciklama"),
        )):
            ttk.Label(frame, text=etiket).grid(row=sira, column=0, sticky="w", pady=4)
            if alan == "odeme_sekli":
                w = ttk.Combobox(frame, values=sekiller, state="readonly", width=28)
                w.set((kayit or {}).get(alan) or sekiller[0])
            elif alan == "hesap":
                w = ttk.Combobox(frame, values=hesaplar, width=28)
                if kayit and kayit.get("hesap"):
                    w.set(kayit["hesap"])
                elif hesaplar:
                    w.set(hesaplar[0])
            else:
                w = ttk.Entry(frame, width=30)
                if kayit and kayit.get(alan) is not None:
                    deger = kayit[alan]
                    w.insert(
                        0,
                        deger.strftime("%d.%m.%Y") if hasattr(deger, "strftime") else str(deger),
                    )
                elif alan == "tarih":
                    w.insert(0, date.today().strftime("%d.%m.%Y"))
            w.grid(row=sira, column=1, padx=6, pady=4)
            self.girdiler[alan] = w
        alt = ttk.Frame(frame)
        alt.grid(row=6, column=0, columnspan=2, sticky="e", pady=10)
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Tamam", command=self.tamam).pack(side="right", padx=8)

    def tamam(self):
        try:
            veri = {a: w.get().strip() for a, w in self.girdiler.items()}
            veri["tarih"] = datetime.strptime(veri["tarih"], "%d.%m.%Y").date()
            veri["tutar"] = decimal(veri["tutar"], "Tutar", Decimal("0.01"))
            if not veri.get("hesap"):
                raise ValueError("Hesap seçin.")
            self.result = veri
            self.destroy()
        except ValueError as hata:
            messagebox.showerror(self.title(), str(hata), parent=self)


class HizmetFaturaDialog(tk.Toplevel):
    """Sade standart hizmet alış / satış faturası."""

    def __init__(
        self,
        parent,
        hizmet_turu="GIDER",
        hizmet_id=None,
        fatura=None,
        fatura_id=None,
    ):
        super().__init__(parent)
        self.hizmet_turu = (hizmet_turu or "GIDER").upper()
        self.gelir_mi = self.hizmet_turu == "GELIR"
        self.fatura = fatura or (
            HizmetFaturasiService.getir(fatura_id) if fatura_id else None
        )
        if self.fatura:
            self.hizmet_turu = (self.fatura.fatura_turu or self.hizmet_turu).upper()
            self.gelir_mi = self.hizmet_turu == "GELIR"
        self.on_hizmet_id = hizmet_id
        self.result = None
        self.satirlar: list[dict] = []
        self.odemeler: list[dict] = []
        self.girdiler = {}
        self.satir_girdileri = {}

        baslik = (
            "HİZMET SATIŞ (GELİR) FATURASI"
            if self.gelir_mi
            else "HİZMET ALIŞ (GİDER) FATURASI"
        )
        self.title(baslik)
        self.geometry("980x680")
        self.minsize(860, 560)
        self.transient(parent)
        self.grab_set()

        cariler = list(HizmetFaturasiService.aktif_cariler(self.hizmet_turu))
        if self.fatura and self.fatura.cari and self.fatura.cari not in cariler:
            cariler.append(self.fatura.cari)
        self.cari_map = {f"{c.cari_kodu} - {c.unvan}": c for c in cariler}

        ust_btn = ttk.Frame(self, padding=(10, 8))
        ust_btn.pack(side="top", fill="x")
        ttk.Button(ust_btn, text="Kaydet (F1)", width=14, command=self.kaydet).pack(
            side="right", padx=4
        )
        ttk.Button(ust_btn, text="İptal Et", command=self.iptal_et).pack(side="right", padx=4)
        ttk.Button(ust_btn, text="Kapat", command=self.destroy).pack(side="right", padx=4)
        self.bind("<F1>", lambda _e: self.kaydet())

        govde = ttk.Frame(self, padding=10)
        govde.pack(fill="both", expand=True)

        self._baslik_olustur(govde, baslik)
        self._satirlar_olustur(govde)
        alt = ttk.Frame(govde)
        alt.pack(fill="x", pady=(8, 0))
        alt.columnconfigure(0, weight=1)
        alt.columnconfigure(1, weight=1)
        self._odeme_olustur(alt)
        self._aciklama_olustur(alt)

        if self.fatura:
            self._faturayi_doldur()
        elif self.on_hizmet_id:
            self._hizmet_satir_ekle(self.on_hizmet_id)

        self._toplamlari_guncelle()

    def _entry(self, parent, satir, etiket, alan, deger="", sutun=0, genislik=28, readonly=False):
        ttk.Label(parent, text=etiket).grid(row=satir, column=sutun, sticky="w", padx=6, pady=3)
        w = ttk.Entry(parent, width=genislik)
        w.grid(row=satir, column=sutun + 1, sticky="w", padx=6, pady=3)
        w.insert(0, deger)
        if readonly:
            w.configure(state="readonly")
        self.girdiler[alan] = w
        return w

    def _baslik_olustur(self, parent, baslik):
        ttk.Label(parent, text=baslik, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        genel = ttk.LabelFrame(parent, text="Fatura Bilgileri", padding=8)
        genel.pack(fill="x", pady=(6, 8))
        genel.columnconfigure(1, weight=1)
        genel.columnconfigure(3, weight=1)

        fatura_no = (
            self.fatura.fatura_no
            if self.fatura
            else HizmetFaturasiService.fatura_no(self.hizmet_turu)
        )
        self._entry(genel, 0, "Fatura No", "fatura_no", fatura_no, readonly=True)
        tarih_alani(
            genel,
            1,
            "Fatura Tarihi",
            "fatura_tarihi",
            _tarih(self.fatura.fatura_tarihi) if self.fatura else date.today().strftime("%d.%m.%Y"),
            self.girdiler,
            on_select=self.vade_gun_degisti,
        )
        saat = saat_varsayilan(
            self.fatura.islem_saati
            if self.fatura and self.fatura.islem_saati
            else (self.fatura.olusturma_tarihi.strftime("%H:%M") if self.fatura else None)
        )
        self._entry(genel, 2, "İşlem Saati", "islem_saati", saat)

        tarih_alani(
            genel,
            0,
            "Vade Tarihi",
            "vade_tarihi",
            _tarih(self.fatura.vade_tarihi) if self.fatura else date.today().strftime("%d.%m.%Y"),
            self.girdiler,
            sutun=2,
            on_select=self.vade_tarih_degisti,
        )
        self._entry(
            genel,
            1,
            "Vade Günü",
            "vade_gunu",
            str(self.fatura.vade_gunu if self.fatura else 0),
            sutun=2,
            genislik=12,
        )
        self.girdiler["fatura_tarihi"].bind("<FocusOut>", self.vade_gun_degisti)
        self.girdiler["vade_tarihi"].bind("<FocusOut>", self.vade_tarih_degisti)
        self.girdiler["vade_gunu"].bind("<KeyRelease>", self.vade_gun_degisti)

        self.cari_etiket = "Hizmet alan" if self.gelir_mi else "Hizmet veren"
        ttk.Label(genel, text=self.cari_etiket).grid(row=3, column=0, sticky="w", padx=6, pady=3)
        self.cari_var = tk.StringVar()
        self.cari_combo = ttk.Combobox(
            genel,
            textvariable=self.cari_var,
            values=list(self.cari_map),
            state="readonly",
            width=36,
        )
        self.cari_combo.grid(row=3, column=1, sticky="w", padx=6, pady=3)

        ttk.Label(genel, text="Durum").grid(row=2, column=2, sticky="w", padx=6, pady=3)
        self.durum = ttk.Combobox(
            genel, values=("AÇIK", "KAPALI", "İPTAL"), state="disabled", width=16
        )
        self.durum.grid(row=2, column=3, sticky="w", padx=6, pady=3)
        self.durum.set(self.fatura.durum if self.fatura else "AÇIK")

    def _satirlar_olustur(self, parent):
        kutu = ttk.LabelFrame(parent, text="Fatura Satırları", padding=8)
        kutu.pack(fill="both", expand=True)

        giris = ttk.Frame(kutu)
        giris.pack(fill="x", pady=(0, 6))
        alanlar = (
            ("Kod", "hizmet_kodu", 12),
            ("Ad", "hizmet_adi", 22),
            ("Miktar", "miktar", 8),
            ("Birim", "birim", 8),
            ("Birim Fiyat", "birim_fiyat", 10),
            ("İsk %", "iskonto_orani", 6),
            ("KDV %", "kdv_orani", 6),
        )
        for i, (etiket, alan, w) in enumerate(alanlar):
            ttk.Label(giris, text=etiket).grid(row=0, column=i, sticky="w", padx=2)
            if alan == "birim":
                widget = ttk.Combobox(giris, values=list(HIZMET_BIRIMLERI), width=w)
                widget.set("Adet")
            elif alan == "kdv_orani":
                widget = ttk.Combobox(giris, values=list(KDV_ORANLARI), width=w)
                widget.set("20")
            else:
                widget = ttk.Entry(giris, width=w)
            widget.grid(row=1, column=i, padx=2, pady=2)
            self.satir_girdileri[alan] = widget

        self.satir_girdileri["iskonto_orani"].insert(0, "0")
        self.satir_girdileri["miktar"].insert(0, "1")
        self.satir_girdileri["hizmet_kodu"].bind("<Return>", self.hizmet_ara)
        self.satir_girdileri["hizmet_adi"].bind("<Return>", self.hizmet_ara)

        btn = ttk.Frame(kutu)
        btn.pack(fill="x", pady=2)
        ttk.Button(btn, text="Hizmet Seç", command=self.hizmet_sec).pack(side="left")
        ttk.Button(btn, text="Yeni Hizmet Kartı", command=self.yeni_hizmet_karti).pack(
            side="left", padx=6
        )
        ttk.Button(btn, text="Satır Ekle", command=self.satir_ekle).pack(side="left", padx=6)
        ttk.Button(btn, text="Satır Sil", command=self.satir_sil).pack(side="left")

        cerceve = ttk.Frame(kutu)
        cerceve.pack(fill="both", expand=True, pady=4)
        kolonlar = ("kod", "ad", "miktar", "birim", "fiyat", "isk", "kdv", "toplam")
        self.tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", height=8)
        for k, b, w in (
            ("kod", "Kod", 90),
            ("ad", "Hizmet Adı", 200),
            ("miktar", "Miktar", 70),
            ("birim", "Birim", 60),
            ("fiyat", "Birim Fiyat", 90),
            ("isk", "İsk %", 50),
            ("kdv", "KDV %", 50),
            ("toplam", "Satır Toplamı", 100),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="w")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        self.tablo.bind("<Double-1>", lambda _e: self.satir_duzenle())

        self.toplam_etiket = ttk.Label(kutu, text="", font=("Segoe UI", 10, "bold"))
        self.toplam_etiket.pack(anchor="e", pady=(4, 0))

    def _odeme_olustur(self, parent):
        baslik = "Tahsilatlar" if self.gelir_mi else "Ödemeler"
        kutu = ttk.LabelFrame(parent, text=baslik, padding=8)
        kutu.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.odeme_tablo = ttk.Treeview(
            kutu, columns=("tarih", "tutar", "sekil", "hesap"), show="headings", height=4
        )
        for k, b, w in (
            ("tarih", "Tarih", 90),
            ("tutar", "Tutar", 100),
            ("sekil", "Şekil", 140),
            ("hesap", "Hesap", 120),
        ):
            self.odeme_tablo.heading(k, text=b)
            self.odeme_tablo.column(k, width=w)
        self.odeme_tablo.pack(fill="both", expand=True)
        btn = ttk.Frame(kutu)
        btn.pack(fill="x", pady=4)
        ttk.Button(btn, text="Ekle", command=self.odeme_ekle).pack(side="left")
        ttk.Button(btn, text="Sil", command=self.odeme_sil).pack(side="left", padx=6)

    def _aciklama_olustur(self, parent):
        kutu = ttk.LabelFrame(parent, text="Açıklama", padding=8)
        kutu.grid(row=0, column=1, sticky="nsew")
        self.aciklama = tk.Text(kutu, height=4, wrap="word")
        self.aciklama.pack(fill="both", expand=True)

    def vade_gun_degisti(self, _event=None):
        try:
            fatura_tarihi = datetime.strptime(
                self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y"
            ).date()
            gun = int(self.girdiler["vade_gunu"].get() or 0)
            vade = fatura_tarihi + timedelta(days=gun)
        except (ValueError, TypeError):
            return
        self.girdiler["vade_tarihi"].configure(state="normal")
        self.girdiler["vade_tarihi"].delete(0, "end")
        self.girdiler["vade_tarihi"].insert(0, _tarih(vade))

    def vade_tarih_degisti(self, _event=None):
        try:
            fatura_tarihi = datetime.strptime(
                self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y"
            ).date()
            vade = datetime.strptime(self.girdiler["vade_tarihi"].get(), "%d.%m.%Y").date()
        except ValueError:
            return
        self.girdiler["vade_gunu"].delete(0, "end")
        self.girdiler["vade_gunu"].insert(0, str((vade - fatura_tarihi).days))

    def hizmet_sec(self):
        dlg = HizmetSecDialog(self, self.hizmet_turu)
        self.wait_window(dlg)
        if dlg.result:
            self._hizmeti_forma_yaz(dlg.result)

    def yeni_hizmet_karti(self):
        from gelir_gider_ui import HizmetKartiDialog

        dlg = HizmetKartiDialog(self, hizmet_turu=self.hizmet_turu)
        self.wait_window(dlg)
        if dlg.result:
            self._hizmeti_forma_yaz(dlg.result)

    def hizmet_ara(self, _event=None):
        kod = self.satir_girdileri["hizmet_kodu"].get().strip()
        ad = self.satir_girdileri["hizmet_adi"].get().strip()
        arama = kod or ad
        if len(arama) < 2:
            return
        dlg = HizmetSecDialog(self, self.hizmet_turu, arama=arama)
        self.wait_window(dlg)
        if dlg.result:
            self._hizmeti_forma_yaz(dlg.result)

    def _hizmeti_forma_yaz(self, hizmet):
        for alan in ("hizmet_kodu", "hizmet_adi", "birim_fiyat", "miktar", "iskonto_orani"):
            w = self.satir_girdileri[alan]
            if isinstance(w, ttk.Combobox):
                continue
            w.delete(0, "end")
        self.satir_girdileri["hizmet_kodu"].insert(0, hizmet.hizmet_kodu or "")
        self.satir_girdileri["hizmet_adi"].insert(0, hizmet.hizmet_adi or "")
        self.satir_girdileri["birim"].set(hizmet.birim or "Adet")
        fiyat = hizmet.satis_fiyati if self.gelir_mi else hizmet.alis_fiyati
        self.satir_girdileri["birim_fiyat"].insert(0, f"{Decimal(str(fiyat or 0)):g}")
        self.satir_girdileri["miktar"].insert(0, "1")
        self.satir_girdileri["iskonto_orani"].insert(0, "0")
        self.satir_girdileri["kdv_orani"].set(f"{float(hizmet.kdv_orani or 0):g}")
        self.satir_girdileri["miktar"].focus_set()

    def _hizmet_satir_ekle(self, hizmet_id):
        hizmet = HizmetService.getir(hizmet_id)
        if not hizmet:
            return
        self._hizmeti_forma_yaz(hizmet)
        self.satir_ekle()

    def _formdan_satir(self) -> dict:
        kod = self.satir_girdileri["hizmet_kodu"].get().strip().upper()
        ad = self.satir_girdileri["hizmet_adi"].get().strip()
        if not kod or not ad:
            raise ValueError("Hizmet kodu ve adı zorunludur.")
        return {
            "hizmet_kodu": kod,
            "hizmet_adi": ad,
            "miktar": decimal(self.satir_girdileri["miktar"].get(), "Miktar", Decimal("0.0001")),
            "birim": self.satir_girdileri["birim"].get().strip() or "Adet",
            "birim_fiyat": decimal(
                self.satir_girdileri["birim_fiyat"].get(), "Birim fiyat", Decimal("0")
            ),
            "iskonto_orani": decimal(
                self.satir_girdileri["iskonto_orani"].get() or 0, "İskonto", Decimal("0")
            ),
            "kdv_orani": decimal(
                self.satir_girdileri["kdv_orani"].get() or 20, "KDV", Decimal("0")
            ),
            "aciklama": "",
        }

    def satir_ekle(self):
        try:
            self.satirlar.append(self._formdan_satir())
        except ValueError as hata:
            messagebox.showerror("Satır", str(hata), parent=self)
            return
        self._satir_form_temizle()
        self._satir_listesini_yenile()

    def satir_sil(self):
        secim = self.tablo.selection()
        if not secim:
            return
        self.satirlar.pop(int(secim[0]))
        self._satir_listesini_yenile()

    def satir_duzenle(self):
        secim = self.tablo.selection()
        if not secim:
            return
        idx = int(secim[0])
        satir = self.satirlar.pop(idx)
        self._satir_form_temizle()
        self.satir_girdileri["hizmet_kodu"].insert(0, satir["hizmet_kodu"])
        self.satir_girdileri["hizmet_adi"].insert(0, satir["hizmet_adi"])
        self.satir_girdileri["birim"].set(satir.get("birim") or "Adet")
        self.satir_girdileri["miktar"].insert(0, f"{Decimal(str(satir['miktar'])):g}")
        self.satir_girdileri["birim_fiyat"].insert(0, f"{Decimal(str(satir['birim_fiyat'])):g}")
        self.satir_girdileri["iskonto_orani"].insert(
            0, f"{Decimal(str(satir.get('iskonto_orani', 0))):g}"
        )
        self.satir_girdileri["kdv_orani"].set(f"{float(satir.get('kdv_orani') or 0):g}")
        self._satir_listesini_yenile()

    def _satir_form_temizle(self):
        for alan, w in self.satir_girdileri.items():
            if alan == "birim":
                w.set("Adet")
            elif alan == "kdv_orani":
                w.set("20")
            else:
                w.delete(0, "end")
        self.satir_girdileri["miktar"].insert(0, "1")
        self.satir_girdileri["iskonto_orani"].insert(0, "0")

    def _satir_listesini_yenile(self):
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        for i, s in enumerate(self.satirlar):
            self.tablo.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    s["hizmet_kodu"],
                    s["hizmet_adi"],
                    f"{float(s['miktar']):g}",
                    s.get("birim") or "",
                    _para(s["birim_fiyat"]),
                    f"{float(s.get('iskonto_orani') or 0):g}",
                    f"{float(s.get('kdv_orani') or 0):g}",
                    _para(_satir_toplam(s)),
                ),
            )
        self._toplamlari_guncelle()

    def _toplamlari_guncelle(self):
        t = HizmetFaturasiService.toplam(self.satirlar)
        odeme = sum((decimal(o["tutar"], "Tutar") for o in self.odemeler), Decimal("0"))
        etiket = "Tahsilat" if self.gelir_mi else "Ödeme"
        self.toplam_etiket.configure(
            text=(
                f"Ara: {_para(t['ara_toplam'])}  |  "
                f"İskonto: {_para(t['iskonto'])}  |  "
                f"KDV: {_para(t['kdv'])}  |  "
                f"Genel: {_para(t['genel_toplam'])}  |  "
                f"{etiket}: {_para(odeme)}"
            )
        )

    def odeme_ekle(self):
        dlg = HizmetOdemeDialog(self, gelir_mi=self.gelir_mi)
        self.wait_window(dlg)
        if dlg.result:
            self.odemeler.append(dlg.result)
            self._odeme_yenile()

    def odeme_sil(self):
        secim = self.odeme_tablo.selection()
        if not secim:
            return
        self.odemeler.pop(int(secim[0]))
        self._odeme_yenile()

    def _odeme_yenile(self):
        for item in self.odeme_tablo.get_children():
            self.odeme_tablo.delete(item)
        for i, o in enumerate(self.odemeler):
            self.odeme_tablo.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    _tarih(o["tarih"]),
                    _para(o["tutar"]),
                    o.get("odeme_sekli") or "",
                    o.get("hesap") or "",
                ),
            )
        self._toplamlari_guncelle()

    def _faturayi_doldur(self):
        f = self.fatura
        if f.cari:
            anahtar = f"{f.cari.cari_kodu} - {f.cari.unvan}"
            if anahtar not in self.cari_map:
                self.cari_map[anahtar] = f.cari
                self.cari_combo["values"] = list(self.cari_map)
            self.cari_var.set(anahtar)
        self.girdiler["fatura_tarihi"].delete(0, "end")
        self.girdiler["fatura_tarihi"].insert(0, _tarih(f.fatura_tarihi))
        self.girdiler["islem_saati"].delete(0, "end")
        self.girdiler["islem_saati"].insert(
            0, saat_varsayilan(f.islem_saati or f.olusturma_tarihi.strftime("%H:%M"))
        )
        self.girdiler["vade_tarihi"].delete(0, "end")
        self.girdiler["vade_tarihi"].insert(0, _tarih(f.vade_tarihi))
        self.girdiler["vade_gunu"].delete(0, "end")
        self.girdiler["vade_gunu"].insert(0, str(f.vade_gunu or 0))
        self.durum.configure(state="readonly")
        self.durum.set(f.durum)
        self.durum.configure(state="disabled")
        if f.aciklama:
            self.aciklama.insert("1.0", f.aciklama)
        self.satirlar.clear()
        for s in f.satirlar:
            self.satirlar.append(
                {
                    "hizmet_kodu": s.hizmet_kodu,
                    "hizmet_adi": s.hizmet_adi,
                    "miktar": s.miktar,
                    "birim": s.birim,
                    "birim_fiyat": s.birim_fiyat,
                    "iskonto_orani": s.iskonto_orani,
                    "kdv_orani": s.kdv_orani,
                    "aciklama": s.aciklama or "",
                }
            )
        self.odemeler.clear()
        if f.odeme_tutari and Decimal(str(f.odeme_tutari)) > 0:
            self.odemeler.append(
                {
                    "tarih": f.fatura_tarihi,
                    "tutar": f.odeme_tutari,
                    "odeme_sekli": f.odeme_sekli or "",
                    "hesap": f.odeme_hesabi or "",
                    "aciklama": "",
                }
            )
        self._satir_listesini_yenile()
        self._odeme_yenile()

    def kaydet(self):
        try:
            cari = self.cari_map.get(self.cari_var.get())
            if not cari:
                raise ValueError(f"{self.cari_etiket} seçin.")
            if not self.satirlar:
                raise ValueError("En az bir fatura satırı ekleyin.")
            fatura_tarihi = datetime.strptime(
                self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y"
            ).date()
            vade_tarihi = datetime.strptime(
                self.girdiler["vade_tarihi"].get(), "%d.%m.%Y"
            ).date()
            islem_saati = saat_dogrula(self.girdiler["islem_saati"].get())
            odeme_tutari = sum(
                (decimal(o["tutar"], "Tutar") for o in self.odemeler), Decimal("0")
            )
            ilk = self.odemeler[0] if self.odemeler else {}
            self.result = HizmetFaturasiService.kaydet(
                {
                    "fatura_no": self.girdiler["fatura_no"].get().strip(),
                    "fatura_turu": self.hizmet_turu,
                    "fatura_tarihi": fatura_tarihi,
                    "islem_saati": islem_saati,
                    "vade_tarihi": vade_tarihi,
                    "cari_id": cari.id,
                    "odeme_tutari": odeme_tutari,
                    "odeme_sekli": ilk.get("odeme_sekli"),
                    "odeme_hesabi": ilk.get("hesap"),
                    "aciklama": self.aciklama.get("1.0", "end").strip() or None,
                },
                self.satirlar,
                self.fatura.id if self.fatura else None,
            )
        except ValueError as hata:
            messagebox.showerror("Fatura kaydedilemedi", str(hata), parent=self)
            return
        messagebox.showinfo(
            "Kaydedildi",
            f"{self.result.fatura_no} kaydedildi.",
            parent=self,
        )
        self.destroy()

    def iptal_et(self):
        if not self.fatura:
            self.destroy()
            return
        if not messagebox.askyesno("İptal", "Bu fatura iptal edilsin mi?", parent=self):
            return
        try:
            HizmetFaturasiService.iptal_et(self.fatura.id)
        except ValueError as hata:
            messagebox.showerror("İptal", str(hata), parent=self)
            return
        self.result = True
        self.destroy()
