"""Hizmet alış / satış fatura diyalogları — Alış faturası yerleşimine yakın."""

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
from doviz_fatura_panel import (
    doviz_ozet_guncelle,
    doviz_paneli_kur,
    doviz_satir_kaydet_oncesi,
    doviz_verilerini_doldur,
    doviz_verilerini_topla,
)
from ui_takvim import saat_dogrula, saat_varsayilan, tarih_alani

# Kullanıcı menü etiketleri → kayıt şekilleri
_ODEME_MENU = (
    ("Nakit", "KASA ÖDEME"),
    ("Havale/EFT", "GÖNDERİLEN HAVALE"),
    ("Kredi Kartı", "KREDİ KARTIYLA ÖDEME"),
)
_TAHSILAT_MENU = (
    ("Nakit", "KASA TAHSİLAT"),
    ("Havale/EFT", "ALINAN HAVALE"),
    ("Kredi Kartı", "KREDİ KARTIYLA TAHSİLAT"),
)


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
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

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
    def __init__(
        self,
        parent,
        gelir_mi=False,
        kayit=None,
        varsayilan_sekil=None,
        *,
        max_tutar: Decimal | None = None,
    ):
        super().__init__(parent)
        self.result = None
        self.gelir_mi = gelir_mi
        self.max_tutar = (
            Decimal(str(max_tutar)).quantize(Decimal("0.01")) if max_tutar is not None else None
        )
        self.title("Tahsilat" if gelir_mi else "Ödeme Yap")
        self.geometry("420x280")
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)
        self.girdiler = {}
        self._hesap_secenekleri: list[str] = []
        self._hesap_id_map: dict[str, int] = {}
        self._sekil_turu: str | None = None
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill="both", expand=True)
        sekiller = list(TAHSILAT_SEKILLERI if gelir_mi else ODEME_SEKILLERI)
        baslangic_sekil = (
            (kayit or {}).get("odeme_sekli")
            or varsayilan_sekil
            or sekiller[0]
        )
        self._hesap_etiket = ttk.Label(frame, text="Hesap")
        for sira, (etiket, alan) in enumerate((
            ("Tarih", "tarih"),
            ("Tutar", "tutar"),
            ("Şekil", "odeme_sekli"),
            ("Hesap", "hesap"),
            ("Açıklama", "aciklama"),
        )):
            lbl = self._hesap_etiket if alan == "hesap" else ttk.Label(frame, text=etiket)
            lbl.grid(row=sira, column=0, sticky="w", pady=4)
            if alan == "odeme_sekli":
                w = ttk.Combobox(frame, values=sekiller, state="readonly", width=28)
                w.set(baslangic_sekil if baslangic_sekil in sekiller else sekiller[0])
                w.bind("<<ComboboxSelected>>", lambda _e: self._sekil_degisti(), add="+")
            elif alan == "hesap":
                w = ttk.Combobox(frame, values=(), width=28)
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
                elif alan == "tutar" and self.max_tutar is not None and not (kayit or {}).get("tutar"):
                    w.insert(0, f"{self.max_tutar:.2f}".replace(".", ","))
            w.grid(row=sira, column=1, padx=6, pady=4)
            self.girdiler[alan] = w
        self._uyari_lbl = ttk.Label(frame, text="", foreground="#a33", wraplength=280)
        self._uyari_lbl.grid(row=5, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self._onceki_hesap = ((kayit or {}).get("hesap") or "").strip()
        self._sekil_degisti(ilk=True)
        alt = ttk.Frame(frame)
        alt.grid(row=6, column=0, columnspan=2, sticky="e", pady=10)
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Tamam", command=self.tamam).pack(side="right", padx=8)

    def _sekil_degisti(self, ilk: bool = False):
        from database.hizmet_faturasi_service import odeme_sekli_hesap_uygun_mu

        sekil = (self.girdiler["odeme_sekli"].get() or "").strip()
        onceki = (self.girdiler["hesap"].get() or "").strip()
        self._sekil_turu = FinansService.odeme_sekil_turu(sekil, gelir_mi=self.gelir_mi)
        etiket_map = {
            "KART": "POS hesabı" if self.gelir_mi else "Kredi Kartı",
            "HAVALE": "Banka Hesabı",
            "KASA": "Kasa",
        }
        self._hesap_etiket.configure(text=etiket_map.get(self._sekil_turu or "", "Hesap"))
        self._hesap_secenekleri = []
        self._hesap_id_map = {}
        okuma_hatasi = None
        try:
            hesaplar = (
                FinansService.tahsilat_hesaplari(sekil)
                if self.gelir_mi
                else FinansService.odeme_hesaplari(sekil)
            )
            for h in hesaplar:
                if not getattr(h, "aktif", True):
                    continue
                ad = (h.hesap_adi or "").strip()
                if not ad:
                    continue
                self._hesap_secenekleri.append(ad)
                if getattr(h, "id", None) is not None:
                    self._hesap_id_map[ad] = int(h.id)
        except Exception as hata:
            okuma_hatasi = str(hata)
            self._hesap_secenekleri = []
            self._hesap_id_map = {}
        w = self.girdiler["hesap"]
        w.configure(values=self._hesap_secenekleri)
        aday = onceki if onceki in self._hesap_secenekleri else (
            self._onceki_hesap if self._onceki_hesap in self._hesap_secenekleri else ""
        )
        if not aday and len(self._hesap_secenekleri) == 1:
            aday = self._hesap_secenekleri[0]
        w.set(aday)
        if okuma_hatasi:
            self._uyari_lbl.configure(text=f"Hesap listesi okunamadı: {okuma_hatasi}")
        elif not self._hesap_secenekleri:
            msg = odeme_sekli_hesap_uygun_mu(sekil, "", gelir_mi=self.gelir_mi) or ""
            if not msg or "Hesap seçin" in msg:
                if self._sekil_turu == "KART":
                    msg = (
                        "Bu tahsilat şekli için uygun POS hesabı yok."
                        if self.gelir_mi
                        else "Bu ödeme şekli için tanımlı kredi kartı hesabı yok."
                    )
                elif self._sekil_turu == "HAVALE":
                    msg = "Bu şekil için uygun mevduat/KMH hesabı yok."
                elif self._sekil_turu == "KASA":
                    msg = "Bu şekil için uygun kasa hesabı yok."
                else:
                    msg = "Bu ödeme/tahsilat şekli için uygun hesap yok."
            self._uyari_lbl.configure(text=msg)
        else:
            self._uyari_lbl.configure(text="")

    def tamam(self):
        from database.hizmet_faturasi_service import odeme_sekli_hesap_uygun_mu

        try:
            veri = {a: w.get().strip() for a, w in self.girdiler.items()}
            veri["tarih"] = datetime.strptime(veri["tarih"], "%d.%m.%Y").date()
            veri["tutar"] = decimal(veri["tutar"], "Tutar", Decimal("0.01"))
            if veri["tutar"] <= 0:
                raise ValueError("Tutar 0'dan büyük olmalıdır.")
            if self.max_tutar is not None and veri["tutar"] > self.max_tutar:
                raise ValueError(
                    f"Tutar kalanı aşamaz (kalan {_para(self.max_tutar).replace(' TL', '')})."
                )
            hesap_id = self._hesap_id_map.get((veri.get("hesap") or "").strip())
            uyari = odeme_sekli_hesap_uygun_mu(
                veri.get("odeme_sekli"),
                veri.get("hesap"),
                gelir_mi=self.gelir_mi,
                finans_hesap_id=hesap_id,
            )
            if uyari:
                raise ValueError(uyari)
            if hesap_id is not None:
                veri["finans_hesap_id"] = hesap_id
            self.result = veri
            self.destroy()
        except ValueError as hata:
            messagebox.showerror(self.title(), str(hata), parent=self)


class HizmetFaturaDialog(tk.Toplevel):
    """Hizmet alış / satış faturası — Alış benzeri alt özet + satır açıklaması."""

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
        self.fatura = fatura or (
            HizmetFaturasiService.getir(fatura_id) if fatura_id else None
        )
        if self.fatura:
            self.hizmet_turu = (self.fatura.fatura_turu or self.hizmet_turu).upper()
        from database.hizmet_faturasi_service import _kart_turu

        self.kart_turu = _kart_turu(self.hizmet_turu)
        self.iade_mi = self.hizmet_turu in ("GIDER_IADE", "GELIR_IADE")
        self.gelir_mi = self.kart_turu == "GELIR"
        self.on_hizmet_id = hizmet_id
        self.result = None
        self.satirlar: list[dict] = []
        self.odemeler: list[dict] = []
        self.girdiler = {}
        self.satir_girdileri = {}
        self._form_hizmet_id = None

        baslik_map = {
            "GIDER": "HİZMET ALIŞ (GİDER) FATURASI",
            "GIDER_IADE": "HİZMET ALIŞ (GİDER) İADE FATURASI",
            "GELIR": "HİZMET SATIŞ (GELİR) FATURASI",
            "GELIR_IADE": "HİZMET SATIŞ (GELİR) İADE FATURASI",
        }
        baslik = baslik_map.get(self.hizmet_turu, "HİZMET FATURASI")
        self.title(baslik)
        self.geometry("1040x720")
        self.minsize(900, 600)
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        self._secili_cari_id = None
        self._secili_cari_ad = ""

        self._toolbar_kur(baslik)
        self.bind("<F1>", lambda _e: self.kaydet())

        govde = ttk.Frame(self, padding=10)
        govde.pack(fill="both", expand=True)

        self._baslik_olustur(govde, baslik)
        doviz_cerceve = ttk.LabelFrame(govde, text="DÖVİZ / KUR", padding=6)
        doviz_cerceve.pack(fill="x", pady=(0, 6))
        self._doviz_fiyat_alani = "birim_fiyat"
        doviz_paneli_kur(self, doviz_cerceve)
        self._satirlar_olustur(govde)
        self._alt_ozet_kur(govde)

        if self.fatura:
            self._faturayi_doldur()
        elif self.on_hizmet_id:
            self._hizmet_satir_ekle(self.on_hizmet_id)

        self._toplamlari_guncelle()

    def _toolbar_kur(self, baslik: str):
        ust_btn = ttk.Frame(self, padding=(10, 8))
        ust_btn.pack(side="top", fill="x")
        ttk.Button(ust_btn, text="Kaydet (F1)", width=14, command=self.kaydet).pack(
            side="right", padx=4
        )
        self._odeme_yap_menu_kur(ust_btn)
        ttk.Button(ust_btn, text="İptal Et", command=self.iptal_et).pack(side="right", padx=4)
        if self.hizmet_turu == "GIDER":
            ttk.Button(ust_btn, text="Bağlı Alış Faturaları", command=self._masraf_dagitimlari).pack(
                side="right", padx=4
            )
        if self.fatura:
            from muhasebe_durum_ui import baslik_guncelle, fis_dugmesi

            fis_dugmesi(ust_btn, "hizmet_faturasi", lambda: getattr(self.fatura, "id", None)).pack(
                side="right", padx=4
            )
            baslik_guncelle(self, baslik, "hizmet_faturasi", self.fatura.id)
        ttk.Button(ust_btn, text="Kapat", command=self.destroy).pack(side="right", padx=4)

    def _odeme_yap_menu_kur(self, parent):
        etiket = "Tahsilat Yap" if self.gelir_mi else "Ödeme Yap"
        mb = ttk.Menubutton(parent, text=etiket)
        menu = tk.Menu(mb, tearoff=0)
        for baslik, sekil in (_TAHSILAT_MENU if self.gelir_mi else _ODEME_MENU):
            menu.add_command(
                label=baslik,
                command=lambda s=sekil: self.odeme_ekle(varsayilan_sekil=s),
            )
        menu.add_separator()
        menu.add_command(label="Diğer…", command=lambda: self.odeme_ekle())
        mb.configure(menu=menu)
        mb.pack(side="right", padx=4)
        self._odeme_yap_mb = mb

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

        self.cari_etiket = "Hizmet alan" if self.gelir_mi else "Tedarikçi"
        ttk.Label(genel, text=self.cari_etiket).grid(row=3, column=0, sticky="w", padx=6, pady=3)
        cari_satir = ttk.Frame(genel)
        cari_satir.grid(row=3, column=1, columnspan=3, sticky="ew", padx=6, pady=3)
        self.cari_var = tk.StringVar()
        self.cari_entry = ttk.Entry(cari_satir, textvariable=self.cari_var, width=36)
        self.cari_entry.pack(side="left", fill="x", expand=True)
        self.cari_combo = self.cari_entry
        ttk.Button(cari_satir, text="Cari Kart", command=self.cari_kart_ac).pack(
            side="left", padx=(6, 0)
        )
        ipucu = (
            "Ad veya cari kodu yazarak ara (↑↓, Enter, Esc)"
            if self.gelir_mi
            else "Tedarikçi unvanı veya cari kodu yazarak ara (↑↓, Enter, Esc)"
        )
        self._cari_kod_lbl = ttk.Label(genel, text=ipucu, foreground="#555")
        self._cari_kod_lbl.grid(row=4, column=1, columnspan=3, sticky="w", padx=6, pady=(0, 3))
        from cari_arama_alani import CariAramaAlani

        self._cari_arama = CariAramaAlani(
            self,
            self.cari_entry,
            cari_turu="EVRAK" if self.gelir_mi else "Tedarikçi",
            on_secim=self._cari_secildi,
            on_temizle=self._cari_temizle,
            secili_ad=lambda: self._secili_cari_ad,
            kayit_adi="Cari" if self.gelir_mi else "Tedarikçi",
        )

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
            ("Ad", "hizmet_adi", 18),
            ("Açıklama", "aciklama", 18),
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
        kolonlar = ("kod", "ad", "aciklama", "miktar", "birim", "fiyat", "isk", "kdv", "toplam")
        self.tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", height=8)
        for k, b, w in (
            ("kod", "Kod", 80),
            ("ad", "Hizmet Adı", 160),
            ("aciklama", "Açıklama", 140),
            ("miktar", "Miktar", 60),
            ("birim", "Birim", 50),
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

    def _alt_ozet_kur(self, parent):
        """Solda Ayrıntılı Notlar / Ödemeler, sağda toplamlar."""
        alt = ttk.Frame(parent)
        alt.pack(fill="x", pady=(8, 0))
        alt.columnconfigure(0, weight=3)
        alt.columnconfigure(1, weight=2)

        sol = ttk.Frame(alt)
        sol.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        nb = ttk.Notebook(sol)
        nb.pack(fill="both", expand=True)
        not_fr = ttk.Frame(nb, padding=4)
        odeme_fr = ttk.Frame(nb, padding=4)
        nb.add(not_fr, text="Ayrıntılı Notlar")
        nb.add(odeme_fr, text="Ödemeler" if not self.gelir_mi else "Tahsilatlar")
        self.aciklama = tk.Text(not_fr, height=4, wrap="word")
        self.aciklama.pack(fill="both", expand=True)
        self.ayrintili_notlar = self.aciklama

        self._kayitli_kapatanlar: dict[str, dict] = {}
        self.odeme_tablo = ttk.Treeview(
            odeme_fr,
            columns=(
                "tarih",
                "tur",
                "belge",
                "sekil",
                "hesap",
                "evrak_toplam",
                "uygulanan",
                "pb",
                "aciklama",
                "durum",
            ),
            show="headings",
            height=5,
            selectmode="browse",
        )
        for k, b, w in (
            ("tarih", "Tarih", 80),
            ("tur", "Belge türü", 120),
            ("belge", "Belge no", 110),
            ("sekil", "Şekil", 90),
            ("hesap", "Hesap", 130),
            ("evrak_toplam", "Evrak tutarı", 90),
            ("uygulanan", "Bu faturaya", 90),
            ("pb", "PB", 40),
            ("aciklama", "Açıklama", 100),
            ("durum", "Durum", 80),
        ):
            self.odeme_tablo.heading(k, text=b)
            self.odeme_tablo.column(k, width=w, anchor="e" if k in ("evrak_toplam", "uygulanan") else "w")
        self.odeme_tablo.pack(fill="both", expand=True)
        self.odeme_tablo.bind("<Double-1>", lambda _e: self.odeme_evraki_ac())
        self.odeme_tablo.bind("<Button-1>", self._odeme_belge_tik)
        odeme_btn = ttk.Frame(odeme_fr)
        odeme_btn.pack(fill="x", pady=4)
        ttk.Button(
            odeme_btn,
            text="Ödeme Yap" if not self.gelir_mi else "Tahsilat Ekle",
            command=self.odeme_ekle,
        ).pack(side="left")
        ttk.Button(odeme_btn, text="Evrakı Aç", command=self.odeme_evraki_ac).pack(side="left", padx=4)
        ttk.Button(odeme_btn, text="Düzenle", command=self.odeme_duzenle).pack(side="left", padx=4)
        ttk.Button(odeme_btn, text="Sil / İptal", command=self.odeme_sil).pack(side="left", padx=4)
        ttk.Button(odeme_btn, text="Yenile", command=self._odeme_yenile).pack(side="left", padx=4)
        self.odeme_ozet = ttk.Label(odeme_fr, text="Ödenen: 0,00 TL | Kalan: 0,00 TL")
        self.odeme_ozet.pack(anchor="w")
        self.odeme_uyari = ttk.Label(odeme_fr, text="", foreground="#a15c00", wraplength=520)
        self.odeme_uyari.pack(anchor="w")

        sag = ttk.LabelFrame(alt, text="Toplamlar", padding=8)
        sag.grid(row=0, column=1, sticky="ne")
        self._ozet_lbls: dict[str, ttk.Label] = {}
        satirlar = (
            ("ara", "Ara Toplam"),
            ("iskonto", "İskonto"),
            ("matrah", "KDV Matrahı"),
            ("kdv", "KDV"),
            ("doviz", "Döviz Karşılığı"),
            ("net", "Net Toplam"),
            ("odenen", "Ödenen"),
            ("kalan", "Kalan Tutar"),
        )
        for i, (anahtar, etiket) in enumerate(satirlar):
            ttk.Label(sag, text=etiket).grid(row=i, column=0, sticky="e", padx=(0, 8), pady=1)
            lbl = ttk.Label(
                sag,
                text="—" if anahtar == "doviz" else "0,00 TL",
                font=("Segoe UI", 10, "bold") if anahtar in ("net", "kalan") else ("Segoe UI", 9),
                width=14,
                anchor="e",
            )
            lbl.grid(row=i, column=1, sticky="e", pady=1)
            self._ozet_lbls[anahtar] = lbl
        # Geriye uyumluluk: eski tek satır etiket
        self.toplam_etiket = self._ozet_lbls["net"]

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
        dlg = HizmetSecDialog(self, self.kart_turu)
        self.wait_window(dlg)
        if dlg.result:
            self._hizmeti_forma_yaz(dlg.result)

    def yeni_hizmet_karti(self):
        from gelir_gider_ui import HizmetKartiDialog

        dlg = HizmetKartiDialog(self, hizmet_turu=self.kart_turu)
        self.wait_window(dlg)
        if dlg.result:
            self._hizmeti_forma_yaz(dlg.result)

    def hizmet_ara(self, _event=None):
        kod = self.satir_girdileri["hizmet_kodu"].get().strip()
        ad = self.satir_girdileri["hizmet_adi"].get().strip()
        arama = kod or ad
        if len(arama) < 2:
            return
        dlg = HizmetSecDialog(self, self.kart_turu, arama=arama)
        self.wait_window(dlg)
        if dlg.result:
            self._hizmeti_forma_yaz(dlg.result)

    def _hizmeti_forma_yaz(self, hizmet):
        for alan in ("hizmet_kodu", "hizmet_adi", "birim_fiyat", "miktar", "iskonto_orani", "aciklama"):
            w = self.satir_girdileri.get(alan)
            if w is None or isinstance(w, ttk.Combobox):
                continue
            w.delete(0, "end")
        self._form_hizmet_id = int(hizmet.id)
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
        hizmet = HizmetService.kodla_getir(kod) if hasattr(HizmetService, "kodla_getir") else None
        if hizmet is None:
            # kodla_getir yoksa liste üzerinden doğrula
            for h in HizmetService.listele(hizmet_turu=self.kart_turu, aktif_only=False, arama=kod):
                if (h.hizmet_kodu or "").upper() == kod:
                    hizmet = h
                    break
        if not hizmet:
            raise ValueError(f"{kod} kodlu hizmet kartı bulunamadı. Stok kartı seçilemez.")
        if (hizmet.hizmet_turu or "").upper() != self.kart_turu:
            raise ValueError(
                f"{kod} bu fatura türü için uygun değil ({hizmet.hizmet_turu})."
            )
        return {
            "hizmet_id": int(hizmet.id),
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
            "aciklama": self.satir_girdileri["aciklama"].get().strip(),
        }

    def satir_ekle(self):
        try:
            self.satirlar.append(doviz_satir_kaydet_oncesi(self, self._formdan_satir()))
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
        self._form_hizmet_id = satir.get("hizmet_id")
        self.satir_girdileri["hizmet_kodu"].insert(0, satir["hizmet_kodu"])
        self.satir_girdileri["hizmet_adi"].insert(0, satir["hizmet_adi"])
        self.satir_girdileri["aciklama"].insert(0, satir.get("aciklama") or "")
        self.satir_girdileri["birim"].set(satir.get("birim") or "Adet")
        self.satir_girdileri["miktar"].insert(0, f"{Decimal(str(satir['miktar'])):g}")
        self.satir_girdileri["birim_fiyat"].insert(0, f"{Decimal(str(satir['birim_fiyat'])):g}")
        self.satir_girdileri["iskonto_orani"].insert(
            0, f"{Decimal(str(satir.get('iskonto_orani', 0))):g}"
        )
        self.satir_girdileri["kdv_orani"].set(f"{float(satir.get('kdv_orani') or 0):g}")
        self._satir_listesini_yenile()

    def _satir_form_temizle(self):
        self._form_hizmet_id = None
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
                    s.get("aciklama") or "",
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
        net = t["genel_toplam"]
        kalan = net - odeme
        self._ozet_lbls["ara"].configure(text=_para(t["ara_toplam"]))
        self._ozet_lbls["iskonto"].configure(text=_para(t["iskonto"]))
        self._ozet_lbls["matrah"].configure(text=_para(t.get("matrah", t["ara_toplam"] - t["iskonto"])))
        self._ozet_lbls["kdv"].configure(text=_para(t["kdv"]))
        self._ozet_lbls["net"].configure(text=_para(net))
        self._ozet_lbls["odenen"].configure(text=_para(odeme))
        self._ozet_lbls["kalan"].configure(text=_para(kalan))
        odenen_etiket = "Tahsil edilen" if self.gelir_mi else "Ödenen"
        self.odeme_ozet.configure(
            text=f"{odenen_etiket}: {_para(odeme)} | Kalan: {_para(kalan)}"
        )
        if hasattr(self, "_doviz_para_birimi"):
            doviz_ozet_guncelle(self)
            pb = (self._doviz_para_birimi.get() or "TRY").upper()
            if pb != "TRY":
                try:
                    kur = Decimal(str(self._doviz_kur.get()).replace(",", ".") or "1")
                    doviz_net = (net / kur).quantize(Decimal("0.01")) if kur else Decimal("0")
                    self._ozet_lbls["doviz"].configure(
                        text=f"{float(doviz_net):,.2f} {pb}".replace(",", "X").replace(".", ",").replace("X", ".")
                    )
                except Exception:
                    self._ozet_lbls["doviz"].configure(text="—")
            else:
                self._ozet_lbls["doviz"].configure(text="—")

    def _fatura_id(self) -> int | None:
        f = getattr(self, "fatura", None)
        return int(f.id) if f and getattr(f, "id", None) else None

    def odeme_ekle(self, varsayilan_sekil=None):
        t = HizmetFaturasiService.toplam(self.satirlar)
        # Kayıtlı faturada kalan = kapatma özeti; taslakta yerel ödemeler
        fid = self._fatura_id()
        if fid:
            try:
                bil = HizmetFaturasiService.kapatan_odemeleri(fid)
                kalan = Decimal(str(bil.get("kalan") or 0)).quantize(Decimal("0.01"))
            except Exception:
                odenen = sum((decimal(o["tutar"], "Tutar") for o in self.odemeler), Decimal("0"))
                kalan = (t["genel_toplam"] - odenen).quantize(Decimal("0.01"))
        else:
            odenen = sum((decimal(o["tutar"], "Tutar") for o in self.odemeler), Decimal("0"))
            kalan = (t["genel_toplam"] - odenen).quantize(Decimal("0.01"))
        if kalan <= 0:
            messagebox.showwarning(
                self.title(),
                "Fatura kalanı yok; ek ödeme/tahsilat yapılamaz.",
                parent=self,
            )
            return
        dlg = HizmetOdemeDialog(
            self,
            gelir_mi=self.gelir_mi,
            varsayilan_sekil=varsayilan_sekil,
            max_tutar=kalan,
        )
        self.wait_window(dlg)
        if dlg.result:
            self.odemeler.append(dlg.result)
            self._odeme_yenile()

    def _secili_kapatan(self) -> dict | None:
        secim = self.odeme_tablo.selection()
        if not secim:
            return None
        return self._kayitli_kapatanlar.get(secim[0])

    def _odeme_belge_tik(self, event):
        """Belge no sütununa tıklanınca kaynak evrakı aç."""
        bolge = self.odeme_tablo.identify_region(event.x, event.y)
        if bolge != "cell":
            return
        sutun = self.odeme_tablo.identify_column(event.x)
        # #3 = belge
        if sutun != "#3":
            return
        satir = self.odeme_tablo.identify_row(event.y)
        if not satir:
            return
        self.odeme_tablo.selection_set(satir)
        self.odeme_tablo.focus(satir)
        self.after(10, self.odeme_evraki_ac)

    def odeme_evraki_ac(self):
        """Kaynak türü + kayıt kimliği (makbuz_id / cari_islem_id) ile gerçek evrakı aç."""
        sat = self._secili_kapatan()
        if not sat:
            # Taslak yerel ödeme — açılacak kaynak yok
            if not self._fatura_id():
                messagebox.showinfo(
                    "Evrak",
                    "Ödeme henüz kaydedilmedi; kaynak evrak faturayla birlikte oluşur.",
                    parent=self,
                )
            else:
                messagebox.showinfo("Evrak", "Satır seçin.", parent=self)
            return
        if sat.get("kaynak") == "BILINMIYOR":
            messagebox.showinfo(
                "Evrak",
                "Bu pay kayıtlı bir kaynak evraka bağlanamıyor (varsayımsal ödeme üretilmez).",
                parent=self,
            )
            return
        belge = (sat.get("belge_no") or sat.get("evrak_no") or "").strip()
        ac_tur = (sat.get("ac_tur") or sat.get("tur") or "").strip()
        makbuz_id = sat.get("makbuz_id")
        cari_islem_id = sat.get("cari_islem_id")
        acildi = False
        try:
            if makbuz_id:
                from kasa_makbuz_ui import KasaMakbuzDialog
                from database.finans_service import FinansService as FS

                m = FS.kasa_makbuz_getir(int(makbuz_id))
                if m is not None:
                    tur = (m.makbuz_turu or "TAHSILAT").upper()
                    dlg = KasaMakbuzDialog(self, makbuz_turu=tur, makbuz_id=int(m.id))
                    self.wait_window(dlg)
                    acildi = True
            if not acildi and (belge or cari_islem_id):
                from belge_onizleme_ui import hareket_belgeyi_ac

                # Kimlik biliniyorsa tür + belge_no ile aç (tahmin yok)
                if belge and hareket_belgeyi_ac(self, ac_tur, belge):
                    acildi = True
        except Exception as hata:
            messagebox.showerror("Evrak", str(hata), parent=self)
            return
        if not acildi:
            messagebox.showinfo(
                "Evrak",
                f"{belge or '—'} için açılabilir kayıt bulunamadı "
                f"(tür={ac_tur or '—'}, kapatma id={sat.get('kayit_id')}, "
                f"makbuz={makbuz_id}, cari_islem={cari_islem_id}).",
                parent=self,
            )
        fid = self._fatura_id()
        if fid:
            try:
                HizmetFaturasiService.odeme_durumunu_senkronla(fid)
                self.fatura = HizmetFaturasiService.getir(fid)
            except Exception:
                pass
        self._odeme_yenile()

    def odeme_duzenle(self):
        sat = self._secili_kapatan()
        if not sat:
            # Taslak: yerel satır düzenleme yok — sil/yeniden ekle
            if not self._fatura_id():
                messagebox.showinfo(
                    "Düzenle",
                    "Kayıtlı olmayan ödeme satırını silip yeniden ekleyin.",
                    parent=self,
                )
            else:
                messagebox.showinfo("Düzenle", "Satır seçin.", parent=self)
            return
        if sat.get("kaynak") == "BILINMIYOR":
            messagebox.showinfo("Düzenle", "Bağlantısız pay düzenlenemez.", parent=self)
            return
        # Aç = düzenleme akışı (makbuz / cari işlem önizlemede Düzenle)
        self.odeme_evraki_ac()
        fid = self._fatura_id()
        if fid:
            try:
                HizmetFaturasiService.odeme_durumunu_senkronla(fid)
                self.fatura = HizmetFaturasiService.getir(fid)
            except Exception:
                pass
        self._odeme_yenile()

    def odeme_sil(self):
        # Taslak yerel liste
        if not self._fatura_id():
            secim = self.odeme_tablo.selection()
            if not secim:
                return
            try:
                self.odemeler.pop(int(secim[0]))
            except (IndexError, ValueError):
                return
            self._odeme_yenile()
            return
        sat = self._secili_kapatan()
        if not sat:
            messagebox.showinfo("Sil", "Satır seçin.", parent=self)
            return
        if sat.get("kaynak") == "BILINMIYOR":
            messagebox.showinfo(
                "Sil",
                "Bağlantısız pay silinemez; önce doğrulanabilir kapatma kaydı gerekir.",
                parent=self,
            )
            return
        belge = (sat.get("belge_no") or sat.get("evrak_no") or "").strip()
        pay = sat.get("pay")
        etkilenen = []
        try:
            from database.kapatma_izleme_service import kaynak_dagitim_detayi

            dag = kaynak_dagitim_detayi(belge, int(self.fatura.cari_id))
            for s in dag.get("satirlar") or []:
                etkilenen.append(
                    f"  • {s.get('evrak_no') or s.get('belge_no')}: {_para(s.get('kapatilan'))}"
                )
        except Exception:
            etkilenen = [f"  • {self.fatura.fatura_no}: {_para(pay)}"]
        if not messagebox.askyesno(
            "Sil / İptal",
            (
                f"Evrak: {belge}\n"
                f"Bu faturaya uygulanan: {_para(pay)}\n"
                f"Evrak toplamı: {_para(sat.get('evrak_toplami'))}\n\n"
                "Etkilenecek faturalar / kalemler:\n"
                + ("\n".join(etkilenen) if etkilenen else "  (liste okunamadı)")
                + "\n\nKaynak evrakın mali etkileri ve kapatma bağlantıları birlikte iptal edilir.\n"
                "Devam edilsin mi?"
            ),
            parent=self,
        ):
            return
        try:
            from database.finans_service import FinansService

            hedef = FinansService.tahsilat_detay_hedef_coz(
                belge, cari_id=int(self.fatura.cari_id)
            )
            kwargs = {"neden": f"Hizmet fatura ödeme iptal {self.fatura.fatura_no}"}
            if hedef["tur"] == "makbuz":
                kwargs["makbuz_id"] = hedef["id"]
            elif hedef["tur"] == "pos_valor":
                kwargs["pos_valor_id"] = hedef["id"]
            else:
                kwargs["cari_islem_id"] = hedef["id"]
            FinansService.tahsilat_detay_iptal(**kwargs)
            HizmetFaturasiService.odeme_durumunu_senkronla(int(self.fatura.id))
            self.fatura = HizmetFaturasiService.getir(int(self.fatura.id))
        except (ValueError, PermissionError) as hata:
            messagebox.showerror("Silinemedi", str(hata), parent=self)
            return
        except Exception as hata:
            # Ödeme makbuzu / EVB cari işlem — alternatif: kaynak belgenin tahsislerini geri al
            try:
                from database.acik_kalem_service import AcikKalemService
                from database.database import get_session

                with get_session() as session:
                    AcikKalemService.belge_geri_al(
                        session,
                        int(self.fatura.cari_id),
                        belge,
                        neden=f"Hizmet fatura ödeme iptal {self.fatura.fatura_no}",
                    )
                HizmetFaturasiService.odeme_durumunu_senkronla(int(self.fatura.id))
                self.fatura = HizmetFaturasiService.getir(int(self.fatura.id))
            except Exception:
                messagebox.showerror("Silinemedi", str(hata), parent=self)
                return
        messagebox.showinfo("Silindi", f"{belge} iptal edildi; fatura durumu güncellendi.", parent=self)
        self._odeme_yenile()

    def _odeme_yenile(self):
        for item in self.odeme_tablo.get_children():
            self.odeme_tablo.delete(item)
        self._kayitli_kapatanlar.clear()
        uyari = ""
        fid = self._fatura_id()
        if fid:
            try:
                bil = HizmetFaturasiService.kapatan_odemeleri(fid)
                if bil.get("uyari"):
                    uyari = bil["uyari"]
                for i, s in enumerate(bil.get("satirlar") or []):
                    iid = str(i)
                    self._kayitli_kapatanlar[iid] = s
                    self.odeme_tablo.insert(
                        "",
                        "end",
                        iid=iid,
                        values=(
                            _tarih(s.get("tarih")),
                            s.get("evrak_turu") or s.get("tur") or "",
                            s.get("evrak_no") or s.get("belge_no") or "",
                            s.get("odeme_sekli") or s.get("tur") or "",
                            s.get("hesap") or "",
                            _para(s.get("evrak_toplami")) if s.get("evrak_toplami") is not None else "—",
                            _para(s.get("pay")),
                            s.get("para_birimi") or "TRY",
                            (s.get("aciklama") or "")[:40],
                            s.get("durum") or ("Geçerli" if s.get("kaynak") == "KAYIT" else s.get("kaynak") or ""),
                        ),
                    )
                # Özet: kapatma tutarları
                odenen = Decimal(str(bil.get("kapanan") or 0))
                kalan = Decimal(str(bil.get("kalan") or 0))
                odenen_etiket = "Tahsil edilen" if self.gelir_mi else "Ödenen"
                self.odeme_ozet.configure(
                    text=f"{odenen_etiket}: {_para(odenen)} | Kalan: {_para(kalan)}"
                )
                self._ozet_lbls["odenen"].configure(text=_para(odenen))
                self._ozet_lbls["kalan"].configure(text=_para(kalan))
            except Exception as hata:
                uyari = f"Kapatma listesi okunamadı: {hata}"
        else:
            for i, o in enumerate(self.odemeler):
                iid = str(i)
                self.odeme_tablo.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        _tarih(o.get("tarih")),
                        "Yeni ödeme (kayıt sonrası)",
                        "—",
                        o.get("odeme_sekli") or "",
                        o.get("hesap") or "",
                        _para(o.get("tutar")),
                        _para(o.get("tutar")),
                        "TRY",
                        o.get("aciklama") or "",
                        "Taslak",
                    ),
                )
        if hasattr(self, "odeme_uyari"):
            self.odeme_uyari.configure(text=uyari)
        if not fid:
            self._toplamlari_guncelle()

    def _cari_secildi(self, cari):
        self._secili_cari_id = int(cari.id)
        self._secili_cari_ad = (cari.unvan or "").strip()
        self.cari_var.set(self._secili_cari_ad)
        kod = (cari.cari_kodu or "").strip()
        tur = (cari.cari_turu or "").strip()
        self._cari_kod_lbl.configure(
            text=f"{kod} · {tur}" if kod else (tur or "Seçildi"),
            foreground="#0F172A",
        )

    def _cari_temizle(self):
        self._secili_cari_id = None
        self._secili_cari_ad = ""
        ipucu = (
            "Ad veya cari kodu yazarak ara (↑↓, Enter, Esc)"
            if self.gelir_mi
            else "Tedarikçi unvanı veya cari kodu yazarak ara (↑↓, Enter, Esc)"
        )
        self._cari_kod_lbl.configure(text=ipucu, foreground="#555")

    def cari_kart_ac(self):
        if not self._secili_cari_id:
            messagebox.showinfo("Cari Kart", f"Önce {self.cari_etiket.lower()} seçin.", parent=self)
            return
        from database.cari_service import CariService
        from cari_kart_ui import CariDialog

        cari = CariService.getir(self._secili_cari_id)
        if cari is None:
            messagebox.showerror("Cari Kart", "Cari bulunamadı.", parent=self)
            return
        arama = getattr(self, "_cari_arama", None)
        if arama is not None:
            try:
                arama.kapat()
            except Exception:
                pass
        dlg = CariDialog(self, cari=cari, cari_turu=cari.cari_turu or "Tedarikçi")
        self.wait_window(dlg)
        try:
            self.grab_set()
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass
        # Form alanları aynı pencerede kaldığı için girilmiş bilgiler korunur;
        # kart güncellendiyse seçili unvanı yenile.
        guncel = CariService.getir(self._secili_cari_id)
        if guncel is not None:
            self._cari_secildi(guncel)

    def _faturayi_doldur(self):
        f = self.fatura
        if f.cari:
            self._cari_secildi(f.cari)
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
        self.aciklama.delete("1.0", "end")
        if f.aciklama:
            self.aciklama.insert("1.0", f.aciklama)
        self.satirlar.clear()
        pb = (getattr(f, "para_birimi", None) or "TRY").upper()
        for s in f.satirlar:
            bf = s.birim_fiyat
            bf_doviz = getattr(s, "birim_fiyat_doviz", None) or 0
            if pb != "TRY" and bf_doviz:
                bf = bf_doviz
            self.satirlar.append(
                {
                    "hizmet_id": getattr(s, "hizmet_id", None),
                    "hizmet_kodu": s.hizmet_kodu,
                    "hizmet_adi": s.hizmet_adi,
                    "miktar": s.miktar,
                    "birim": s.birim,
                    "birim_fiyat": bf,
                    "birim_fiyat_doviz": bf_doviz or None,
                    "iskonto_orani": s.iskonto_orani,
                    "kdv_orani": s.kdv_orani,
                    "aciklama": s.aciklama or "",
                }
            )
        self.odemeler.clear()
        # Kayıtlı kapatmalar Ödemeler/Tahsilatlar sekmesinde gerçek kaynaklardan gelir;
        # burada varsayımsal ödeme satırı üretilmez.
        if hasattr(self, "_doviz_para_birimi"):
            doviz_verilerini_doldur(self, f)
        self._satir_listesini_yenile()
        self._odeme_yenile()

    def kaydet(self):
        try:
            if not self._secili_cari_id:
                raise ValueError(f"{self.cari_etiket} seçin.")
            if not self.satirlar:
                raise ValueError("En az bir fatura satırı ekleyin.")
            # Satırların hizmet kartı olduğunu doğrula
            for s in self.satirlar:
                kod = (s.get("hizmet_kodu") or "").strip().upper()
                bulundu = None
                for h in HizmetService.listele(
                    hizmet_turu=self.kart_turu, aktif_only=False, arama=kod
                ):
                    if (h.hizmet_kodu or "").upper() == kod:
                        bulundu = h
                        break
                if not bulundu:
                    raise ValueError(
                        f"{kod}: hizmet kartı değil veya bulunamadı. Stok kartı kullanılamaz."
                    )
            fatura_tarihi = datetime.strptime(
                self.girdiler["fatura_tarihi"].get(), "%d.%m.%Y"
            ).date()
            vade_tarihi = datetime.strptime(
                self.girdiler["vade_tarihi"].get(), "%d.%m.%Y"
            ).date()
            islem_saati = saat_dogrula(self.girdiler["islem_saati"].get())
            # Yeni/taslak ödemeler + mevcut kapatma senkronu
            yeni_odeme = sum(
                (decimal(o["tutar"], "Tutar") for o in self.odemeler), Decimal("0")
            )
            ilk = self.odemeler[0] if self.odemeler else {}
            if self.fatura and yeni_odeme <= 0:
                # Satır/KDV kaydı; mevcut kapatma tutarını koru (ikinci ödeme üretme)
                odeme_tutari = Decimal(str(self.fatura.odeme_tutari or 0))
                odeme_sekli = self.fatura.odeme_sekli
                odeme_hesabi = self.fatura.odeme_hesabi
            else:
                odeme_tutari = yeni_odeme
                odeme_sekli = ilk.get("odeme_sekli") or None
                odeme_hesabi = ilk.get("hesap") or None
            # Model tek ödeme satırı tutar; farklı şekil/hesap birleştirilmez
            if len(self.odemeler) > 1:
                sekiller = {(o.get("odeme_sekli") or "").strip() for o in self.odemeler}
                hesaplar = {(o.get("hesap") or "").strip() for o in self.odemeler}
                if len(sekiller) > 1 or len(hesaplar) > 1:
                    raise ValueError(
                        "Birden fazla ödeme/tahsilat aynı şekil ve hesapta olmalıdır. "
                        "Farklı hesaplar için ayrı makbuz kullanın."
                    )
            veriler = {
                "fatura_no": self.girdiler["fatura_no"].get().strip(),
                "fatura_turu": self.hizmet_turu,
                "fatura_tarihi": fatura_tarihi,
                "islem_saati": islem_saati,
                "vade_tarihi": vade_tarihi,
                "cari_id": int(self._secili_cari_id),
                "odeme_tutari": odeme_tutari,
                "odeme_sekli": odeme_sekli,
                "odeme_hesabi": odeme_hesabi,
                "aciklama": self.aciklama.get("1.0", "end").strip() or None,
            }
            if hasattr(self, "_doviz_para_birimi"):
                veriler.update(doviz_verilerini_topla(self))
            self.result = HizmetFaturasiService.kaydet(
                veriler,
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

    def _masraf_dagitimlari(self):
        if not self.fatura:
            messagebox.showinfo("Masraf Dağıtımı", "Önce faturayı kaydedin.", parent=self)
            return
        from masraf_dagitim_ui import bagli_dagitimlar_goster

        bagli_dagitimlar_goster(self, kaynak_id=int(self.fatura.id))

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
