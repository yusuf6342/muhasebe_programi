"""Alınan Sipariş kartı — kurumsal, klavye odaklı.

Kaydetmek stok çıkışı veya cari borç oluşturmaz. Sevk/fatura miktarları irsaliye ve
fatura kayıtlarından gelir; bağlı satırın ürünü/birimi değiştirilemez, miktarı
sevk/fatura edilenin altına indirilemez.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk
from birim_hatasi_ui import birim_hatasi_goster
from typing import Any

from database.satis_siparisi_service import (
    PARA_BIRIMLERI,
    SatisSiparisiService,
    belge_toplamlari,
    decimal,
    satir_hesapla,
    siparis_ilerleme,
)
from satis_irsaliyesi_ui import YENI_NO_METNI, _AkisCubugu, _sayi, _tarih, _tarih_coz, toplam_miktar_ozeti
from satis_tema import (
    ACIK_BG,
    ACIK_SARI,
    BEYAZ,
    CIZGI,
    IKINCIL,
    KOYU_LACIVERT,
    LACIVERT,
    METIN,
    SARI,
    font,
    stil_uygula,
    tk_buton,
    treeview_stil,
)
from ui_takvim import (
    saat_alani_bagla,
    saat_dogrula,
    saat_kisa_giris_coz,
    saat_varsayilan,
    takvim_entry_bagla,
)
YESIL = "#1F9D74"
TURUNCU = "#E07B00"
KIRMIZI = "#D64545"
MAVI = "#1565C0"
GRI = "#627D98"

DURUM_RENK = {
    "TASLAK": (GRI, BEYAZ),
    "AÇIK": (MAVI, BEYAZ),
    "KISMİ İRSALİYELİ": (TURUNCU, BEYAZ),
    "İRSALİYELİ": ("#00838F", BEYAZ),
    "KISMİ FATURALI": (SARI, KOYU_LACIVERT),
    "FATURALI": (YESIL, BEYAZ),
    "İPTAL": (KIRMIZI, BEYAZ),
}
BIRIMLER = ("Adet", "Kg", "Gr", "Metre", "Litre", "Paket", "Koli", "Kutu", "Takım", "Set")
MANUEL_KOD = "MANUEL"
MALIYET_ALANLARI = (
    "fifo_birim_maliyeti", "son_alis_birim_maliyeti", "ortalama_birim_maliyeti",
    "agirlikli_ortalama_birim_maliyeti",
)


def para_metni(tutar, pb: str = "TRY") -> str:
    try:
        metin = f"{Decimal(str(tutar or 0)):,.2f}"
    except Exception:
        metin = "0.00"
    metin = metin.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{metin} {'TL' if (pb or 'TRY') == 'TRY' else pb}"


KDV_SECENEKLERI = ("0", "1", "10", "20")
TESLIM_SEKLI_SECENEKLERI = ("İşyerinden", "Kargo", "Ambar", "Bizim araçla teslim")
# Üst form kutuları = güncel Satış Faturası (fatura_tema FORM_SATIR_TABAN).
# Ürün tablosu satır yüksekliği = Teklif Formu (TABLO_SATIR_TABAN × katsayı).


def _saat_opsiyonel(metin: str) -> str | None:
    """Boş → None; kısa giriş (16 / 1643) HH:mm'ye çevrilir; '00:00' geçerli kalır."""
    return saat_kisa_giris_coz(metin, bos_izinli=True, alan_adi="Teslim saati")


def _satir_iskonto_metni(s: dict[str, Any]) -> str:
    from satir_ici_urun_giris import iskonto_metni

    return iskonto_metni(s)


def _iskonto_metni(s: dict[str, Any]) -> str:
    oranlar = [decimal(s.get(k) or 0, "İskonto") for k in ("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3")]
    dolu = [f"%{_sayi(o)}" for o in oranlar if o > 0]
    return " + ".join(dolu) or "—"


class SatisSiparisiKarti(tk.Toplevel):
    """Alınan sipariş kartı (yeni / aç / düzenle)."""

    def __init__(self, parent, siparis=None, cari=None):
        super().__init__(parent)
        try:
            self._kur(parent, siparis, cari)
        except Exception:
            try:
                self.grab_release()
                self.destroy()
            except tk.TclError:
                pass
            raise

    def _kur(self, parent, siparis, cari):
        self.withdraw()
        self.siparis = None
        self.result = None
        self.cari = None
        self.satirlar: list[dict[str, Any]] = []
        self.girdiler: dict[str, Any] = {}
        self._kaydediliyor = False
        self._kayit_imzasi: tuple | None = None
        self._durum_var = tk.StringVar(value="TASLAK")
        self._musteri_var = tk.StringVar(value="")
        self._musteri_etiket = ""
        self._avans = Decimal("0")
        self._uzlasilan_tutar = None
        self._uzlasilan_ui_kilit = False
        self._uzlasilan_fiyat_snapshot = None
        self._uzlasilan_snapshot_brut = None
        self._hesaplanan_genel = Decimal("0")
        self._genel_islem_turu = ""
        self._genel_islem_orani = Decimal("0")
        self._genel_islem_tutari = Decimal("0")
        self._siparis_ozet_refs: dict[str, Any] = {}
        self.siparis_toplam_degerleri: dict[str, Any] = {}
        self.title("Alınan Sipariş")
        stil_uygula(root=self)
        try:
            import fatura_tema as ftema
            import siparis_tema as stema

            ftema.stil_uygula(ttk.Style(self), root=self)
            stil_uygula(root=self)
            stema.stil_uygula(root=self)
        except Exception:
            pass
        try:
            from database.satis_irsaliyesi_service import SatisIrsaliyesiService

            self.depolar = SatisIrsaliyesiService.depolar() or ["ANA DEPO"]
        except Exception:
            self.depolar = ["ANA DEPO"]
        try:
            from database.doviz_service import DovizService

            self.para_birimleri = list(DovizService.para_birimleri()) or list(PARA_BIRIMLERI)
        except Exception:
            self.para_birimleri = list(PARA_BIRIMLERI)
        if "TRY" not in self.para_birimleri:
            self.para_birimleri.insert(0, "TRY")

        self.configure(bg=ACIK_BG)
        self._mevcut_bakiye = Decimal("0")
        self._ust_baslik()
        self._arac_cubugu()
        # Üst sabit + ürün tablosu esnek + toplamlar altta sabit (sayfa kaydırması yok)
        self._govde_kur()
        self._siparis_ust_dort_panel_kur()
        self._satir_alani()
        self._aciklama_ve_toplam()
        # Önce alt toplam (sabit), sonra gövde expand — sayfa kaydırması yok
        self._toplamlar_dis.pack(side="bottom", fill="x", padx=8, pady=(0, 4))
        self._govde.pack(side="top", fill="both", expand=True, padx=8, pady=(0, 0))
        self._kisayollar()
        from evrak_baslik_gezinme import baslik_gezinme_kur

        baslik_gezinme_kur(self, self._baslik_kaplari, son_hedef=self._satir_ici_giris.odakla)
        self.after(80, self._siparis_ust_alt_sinir_hizala)

        from ui_pencere import belge_penceresini_hazirla

        belge_penceresini_hazirla(
            self, min_genislik=900, min_yukseklik=560, varsayilan_genislik=1320,
            varsayilan_yukseklik=780, maximize=True,
        )
        self.deiconify()
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)
        self.protocol("WM_DELETE_WINDOW", self.kapat)

        if siparis is not None:
            guncel = SatisSiparisiService.getir(int(siparis.id))
            if guncel is None:
                raise ValueError("Sipariş bulunamadı; silinmiş olabilir.")
            self._kayit_yukle(guncel)
            self._satir_ici_giris.odakla()
        else:
            if cari is not None:
                self._musteri_ata(cari)
            self._kayit_imzasi = self._imza()
            self.satir_listesini_yenile()
            self._kilit_uygula()
            def _musteri_odak():
                try:
                    self.musteri.focus_force()
                    self.musteri.icursor("end")
                except tk.TclError:
                    pass
            self.after_idle(_musteri_odak)
            self.after(120, _musteri_odak)

    # ------------------------------------------------------------------ düzen
    def _ust_baslik(self):
        # Fatura üst şeridine yakın kompakt lacivert başlık
        ust = tk.Frame(self, bg=LACIVERT)
        ust.pack(fill="x")
        sol = tk.Frame(ust, bg=LACIVERT)
        sol.pack(side="left", fill="x", expand=True, padx=12, pady=(8, 6))
        tk.Label(sol, text="ALINAN SİPARİŞ", bg=LACIVERT, fg=BEYAZ, font=font(16, "bold", self)).pack(anchor="w")
        self._meta_label = tk.Label(sol, text="Yeni sipariş", bg=LACIVERT, fg=ACIK_SARI, font=font(9, root=self))
        self._meta_label.pack(anchor="w")
        self._badge = tk.Label(ust, text="TASLAK", bg=GRI, fg=BEYAZ, font=font(10, "bold", self), padx=10, pady=4)
        self._badge.pack(side="right", padx=12)
        self._ilerleme_badge = tk.Label(ust, text="", bg=LACIVERT, fg=ACIK_SARI, font=font(9, "bold", self))
        self._ilerleme_badge.pack(side="right", padx=4)
        tk.Frame(self, bg=SARI, height=2).pack(fill="x")

    def _arac_cubugu(self):
        cubuk = _AkisCubugu(self, bg=ACIK_BG)
        cubuk.pack(fill="x", padx=8, pady=(4, 0))
        self.btn: dict[str, tk.Button] = {}

        def ekle(anahtar, metin, komut, rol):
            self.btn[anahtar] = cubuk.ekle(tk_buton(cubuk, metin, komut, rol=rol))

        ekle("yeni", "Yeni", self.yeni_belge, "yeni")
        ekle("liste", "Sipariş Listesi", self.siparis_listesini_ac, "ara")
        ekle("kaydet", "Kaydet (F2)", self.kaydet, "kaydet")
        ekle("onayla", "Kaydet ve Onayla", self.kaydet_ve_onayla, "kaydet")
        ekle("onay_kaldir", "Onayı Kaldır", self.onay_kaldir, "duzenle")
        ekle("irsaliye", "İrsaliyeye Aktar", self.irsaliyeye_aktar, "yeni")
        ekle("fatura", "Faturaya Aktar", self.faturaya_aktar, "yeni")
        ekle("bagli", "Bağlı Evraklar", self.bagli_evraklari_goster, "duzenle")
        ekle("onizleme", "Önizleme", self.onizleme, "yazdir")
        ekle("yazdir", "Yazdır", self.yazdir, "yazdir")
        ekle("pdf", "PDF Kaydet", self.pdf_kaydet, "yazdir")
        ekle("word", "Word Kaydet", self.word_kaydet, "yazdir")
        ekle("iptal", "İptal Et", self.iptal_et, "iptal")
        ekle("sil", "Sil", self.sil, "iptal")
        ekle("kapat", "Kapat", self.kapat, "geri")

    def _govde_kur(self):
        """Kaydırılabilir sayfa yok: üst paneller + ürün tablosu (esnek) aynı gövdede."""
        self._govde = tk.Frame(self, bg=ACIK_BG)
        self.icerik = self._govde  # üst paneller / sarı çizgi buraya
        self.canvas = None  # eski canvas API uyumu (yok)

    def _panel(self, baslik: str, parent=None, *, genislet=False) -> tk.Frame:
        """Ürün satırları / toplam paneli. Üst dört panel LabelFrame kullanır."""
        hedef = parent if parent is not None else self.icerik
        dis = tk.Frame(hedef, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        if genislet:
            dis.pack(fill="both", expand=True, pady=(2, 0), padx=0)
        else:
            dis.pack(fill="x", pady=(2, 0), padx=0)
        ust = tk.Frame(dis, bg=BEYAZ)
        ust.pack(fill="x")
        tk.Frame(ust, bg=SARI, width=4).pack(side="left", fill="y")
        tk.Label(ust, text=baslik, bg=BEYAZ, fg=LACIVERT, font=font(10, "bold", self)).pack(
            side="left", padx=8, pady=2
        )
        ic = tk.Frame(dis, bg=BEYAZ)
        ic.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        return ic

    def _etiket(self, parent, metin, row, col, zorunlu=False, style_bg=None):
        bg = style_bg if style_bg is not None else BEYAZ
        py = getattr(self, "_siparis_form_pady", 2)
        tk.Label(
            parent, text=metin + (" *" if zorunlu else ""), bg=bg,
            fg=KIRMIZI if zorunlu else IKINCIL, font=font(9, root=self),
        ).grid(row=row, column=col, padx=(0, 4), pady=py, sticky="w")

    def _girdi(self, parent, row, col, label, field, value="", width=24, zorunlu=False, colspan=1):
        self._etiket(parent, label, row, col * 2, zorunlu)
        widget = ttk.Entry(parent, width=width, style="FaturaUst.TEntry")
        py = getattr(self, "_siparis_form_pady", 2)
        ipady = getattr(self, "_siparis_form_ipady", 0)
        widget.grid(
            row=row, column=col * 2 + 1, columnspan=colspan,
            padx=0, pady=py, sticky="ew", ipady=ipady,
        )
        if value:
            widget.insert(0, value)
        self.girdiler[field] = widget
        return widget

    def _siparis_ust_dort_panel_kur(self):
        """Sipariş Bilgileri | Teslimat Koşulları | Depo Döviz ve Diğer | Müşteri Hesap Özeti.

        Ölçü / stil = güncel Satış Faturası üst paneli (FaturaUst.*, ipady=0, 1,5 mm aralık).
        """
        import fatura_tema as ftema

        py = ftema.form_pady()
        _ipady = 0  # fatura: yükseklik stil padding’inde; özet kutusuyla çift şişme olmasın
        self._siparis_form_ipady = _ipady
        self._siparis_form_pady = py
        self._siparis_ozet_kutu_h = ftema.form_satir_dis_yukseklik()
        self._siparis_satir_yuvasi = self._siparis_ozet_kutu_h + 2 * py

        try:
            stil = ttk.Style(self)
            ftema.stil_uygula(stil, root=self)
            stil.configure(
                "FaturaUst.TLabel",
                font=ftema.font(9, root=self),
                foreground=ftema.IKINCIL,
            )
            stil.configure(
                "FaturaUst.TLabelframe.Label",
                font=ftema.font(9, "bold", self),
                foreground=ftema.LACIVERT,
            )
            stil.configure("FaturaUst.TLabelframe", padding=(6, 2))
        except tk.TclError:
            stil = None

        gap = 8
        self._siparis_ust_gap = gap

        ust = ttk.Frame(self.icerik)
        ust.pack(fill="x", padx=0, pady=(0, 0))
        self._ust_dort_panel = ust
        for c in range(4):
            ust.columnconfigure(c, weight=1, minsize=160, uniform="siparis_ust")
        ust.rowconfigure(0, weight=0)

        def _bes_satir_yuva(panel, satir_sayisi=5):
            for r in range(satir_sayisi):
                panel.rowconfigure(r, weight=0, minsize=self._siparis_satir_yuvasi)

        # ——— 1 Sipariş Bilgileri (= fatura Müşteri paneli) ———
        p1 = ttk.LabelFrame(ust, text="Sipariş Bilgileri", padding=(6, 2), style="FaturaUst.TLabelframe")
        p1.grid(row=0, column=0, sticky="new", padx=(0, gap), pady=0)
        p1.columnconfigure(0, minsize=72, weight=0)
        p1.columnconfigure(1, weight=1)
        _bes_satir_yuva(p1)

        ttk.Label(p1, text="Müşteri Adı", style="FaturaUst.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 4), pady=py
        )
        ad_fr = ttk.Frame(p1)
        ad_fr.grid(row=0, column=1, sticky="ew", pady=py)
        ad_fr.columnconfigure(0, weight=1)
        self.musteri = ttk.Entry(
            ad_fr, textvariable=self._musteri_var, width=28, style="FaturaMusteriAd.TEntry"
        )
        self.musteri.pack(side="left", fill="x", expand=True, ipady=_ipady)
        self.musteri.bind("<Return>", self.musteri_ara)

        ttk.Label(p1, text="Müşteri Kodu", style="FaturaUst.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 4), pady=py
        )
        kod_fr = ttk.Frame(p1)
        kod_fr.grid(row=1, column=1, sticky="ew", pady=py)
        self.musteri_kodu = ttk.Entry(kod_fr, width=12, style="FaturaUst.TEntry")
        self.musteri_kodu.pack(side="left", ipady=_ipady)
        self.musteri_kodu.configure(state="readonly")
        self._musteri_btn = ttk.Button(
            kod_fr, text="Ara", width=5, style="FaturaUst.TButton", command=self.musteri_sec,
        )
        self._musteri_btn.pack(side="left", padx=(4, 0), ipady=_ipady)

        ttk.Label(p1, text="Adres", style="FaturaUst.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 4), pady=py
        )
        adres_ust = ttk.Frame(p1)
        adres_ust.grid(row=2, column=1, sticky="ew", pady=py)
        adres_ust.columnconfigure(0, weight=1)
        self.adres_secimi = ttk.Combobox(
            adres_ust, state="readonly", width=22, style="FaturaUst.TCombobox"
        )
        self.adres_secimi.grid(row=0, column=0, sticky="ew", ipady=_ipady)
        self.adres_secimi.bind("<<ComboboxSelected>>", self._siparis_adres_secildi)
        self._siparis_adres_map: dict[str, dict] = {}

        _adres_h = ftema.form_cok_satir_text_yukseklik(2)
        adres_fr = ttk.Frame(p1)
        adres_fr.grid(row=3, column=1, rowspan=2, sticky="nsew", pady=py)
        adres_fr.columnconfigure(0, weight=1)
        adres_fr.rowconfigure(0, weight=1)
        self._siparis_adres_fr = adres_fr
        self.teslimat_adresi_text = tk.Text(
            adres_fr, height=_adres_h, width=24, wrap="word", font=ftema.font(9, root=self),
            relief="solid", bd=1, highlightthickness=0, padx=4, pady=2,
            bg=ftema.BEYAZ, fg=ftema.METIN,
        )
        self.teslimat_adresi_text.grid(row=0, column=0, sticky="nsew")
        self.girdiler["teslimat_adresi"] = self.teslimat_adresi_text
        _gizli = ttk.Frame(p1)
        self.girdiler["teslimat_il"] = ttk.Entry(_gizli)
        self.girdiler["teslimat_ilce"] = ttk.Entry(_gizli)
        self.girdiler["siparis_no"] = ttk.Entry(_gizli)
        self.girdiler["siparis_no"].insert(0, YENI_NO_METNI)
        self.girdiler["bakiye"] = ttk.Entry(_gizli)
        self.girdiler["avans"] = ttk.Entry(_gizli)

        # ——— 2 Teslimat Koşulları (= fatura Belge paneli: tarih|saat yan yana) ———
        p2 = ttk.LabelFrame(ust, text="Teslimat Koşulları", padding=(6, 2), style="FaturaUst.TLabelframe")
        p2.grid(row=0, column=1, sticky="new", padx=(0, gap), pady=0)
        p2.columnconfigure(0, minsize=72, weight=0)
        p2.columnconfigure(1, weight=1)
        p2.columnconfigure(2, minsize=48, weight=0)
        p2.columnconfigure(3, weight=1)
        _bes_satir_yuva(p2)
        bugun = date.today().strftime("%d.%m.%Y")

        ttk.Label(p2, text="Sipariş Tarihi", style="FaturaUst.TLabel").grid(
            row=0, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        e_st = ttk.Entry(p2, width=12, style="FaturaUst.TEntry")
        e_st.insert(0, bugun)
        takvim_entry_bagla(e_st)
        e_st.grid(row=0, column=1, padx=(0, 8), pady=py, sticky="ew", ipady=_ipady)
        self.girdiler["siparis_tarihi"] = e_st
        ttk.Label(p2, text="Sipariş Saati", style="FaturaUst.TLabel").grid(
            row=0, column=2, padx=(0, 6), pady=py, sticky="w"
        )
        e_ss = ttk.Entry(p2, width=7, style="FaturaUst.TEntry")
        e_ss.insert(0, saat_varsayilan())
        e_ss.grid(row=0, column=3, padx=0, pady=py, sticky="ew", ipady=_ipady)
        self.girdiler["siparis_saati"] = e_ss

        ttk.Label(p2, text="Teslim Tarihi", style="FaturaUst.TLabel").grid(
            row=1, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        e_tt = ttk.Entry(p2, width=12, style="FaturaUst.TEntry")
        e_tt.insert(0, bugun)
        takvim_entry_bagla(e_tt)
        e_tt.grid(row=1, column=1, padx=(0, 8), pady=py, sticky="ew", ipady=_ipady)
        self.girdiler["termin_tarihi"] = e_tt
        ttk.Label(p2, text="Teslim Saati", style="FaturaUst.TLabel").grid(
            row=1, column=2, padx=(0, 6), pady=py, sticky="w"
        )
        e_ts = ttk.Entry(p2, width=7, style="FaturaUst.TEntry")
        e_ts.grid(row=1, column=3, padx=0, pady=py, sticky="ew", ipady=_ipady)
        self.girdiler["teslim_saati"] = e_ts
        # Yazarken dönüştürme; FocusOut / Enter / kaydet öncesi HH:mm
        self._teslim_saati_bicimlendir = saat_alani_bagla(
            e_ts, bos_izinli=True, alan_adi="Teslim saati", parent=self
        )

        ttk.Label(p2, text="Teslim Şekli", style="FaturaUst.TLabel").grid(
            row=2, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        self.teslim_sekli = ttk.Combobox(
            p2, values=TESLIM_SEKLI_SECENEKLERI, state="readonly", width=18, style="FaturaUst.TCombobox"
        )
        self.teslim_sekli.grid(row=2, column=1, columnspan=3, sticky="ew", pady=py, ipady=_ipady)
        self.girdiler["teslim_sekli"] = self.teslim_sekli

        # Diğer bilgiler — kompakt, üst panelde görünür (ayrı pencere yok)
        ttk.Label(p2, text="Müş. Sipariş No", style="FaturaUst.TLabel").grid(
            row=3, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        e_msn = ttk.Entry(p2, width=12, style="FaturaUst.TEntry")
        e_msn.grid(row=3, column=1, padx=(0, 8), pady=py, sticky="ew", ipady=_ipady)
        self.girdiler["musteri_siparis_no"] = e_msn
        ttk.Label(p2, text="Ödeme Koşulu", style="FaturaUst.TLabel").grid(
            row=3, column=2, padx=(0, 6), pady=py, sticky="w"
        )
        e_ok = ttk.Entry(p2, width=10, style="FaturaUst.TEntry")
        e_ok.grid(row=3, column=3, padx=0, pady=py, sticky="ew", ipady=_ipady)
        self.girdiler["odeme_kosulu"] = e_ok

        ttk.Label(p2, text="Serbest Teslim", style="FaturaUst.TLabel").grid(
            row=4, column=0, padx=(0, 6), pady=py, sticky="w"
        )
        e_tk = ttk.Entry(p2, width=18, style="FaturaUst.TEntry")
        e_tk.grid(row=4, column=1, columnspan=3, sticky="ew", pady=py, ipady=_ipady)
        self.girdiler["teslim_kosulu"] = e_tk

        # ——— 3 Depo Döviz ve Diğer ———
        p3 = ttk.LabelFrame(ust, text="Depo Döviz ve Diğer", padding=(6, 2), style="FaturaUst.TLabelframe")
        p3.grid(row=0, column=2, sticky="new", padx=(0, gap), pady=0)
        p3.columnconfigure(0, minsize=64, weight=0)
        p3.columnconfigure(1, weight=1)
        _bes_satir_yuva(p3)

        ttk.Label(p3, text="Depo", style="FaturaUst.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 4), pady=py
        )
        depo_satir = ttk.Frame(p3)
        depo_satir.grid(row=0, column=1, sticky="ew", pady=py)
        self.depo = ttk.Combobox(
            depo_satir, values=self.depolar, width=14, state="readonly", style="FaturaUst.TCombobox"
        )
        self.depo.pack(side="left", ipady=_ipady)
        self.depo.set(self.depolar[0] if self.depolar else "ANA DEPO")

        ttk.Label(p3, text="Döviz", style="FaturaUst.TLabel").grid(
            row=1, column=0, sticky="w", padx=(0, 4), pady=py
        )
        doviz_fr = ttk.Frame(p3)
        doviz_fr.grid(row=1, column=1, sticky="ew", pady=py)
        self.para_birimi = ttk.Combobox(
            doviz_fr, values=self.para_birimleri, width=6, state="readonly", style="FaturaUst.TCombobox"
        )
        self.para_birimi.pack(side="left", ipady=_ipady)
        self.para_birimi.set("TRY")
        self.para_birimi.bind("<<ComboboxSelected>>", self._para_birimi_degisti)
        ttk.Label(doviz_fr, text="Kur", style="FaturaUst.TLabel").pack(side="left", padx=(6, 2))
        kur = ttk.Entry(doviz_fr, width=10, style="FaturaUst.TEntry")
        kur.pack(side="left", ipady=_ipady)
        kur.insert(0, "1")
        self.girdiler["kur"] = kur
        kur.bind("<KeyRelease>", lambda _e: self.toplam_guncelle(), add="+")
        kur.bind("<FocusOut>", lambda _e: self.toplam_guncelle(), add="+")

        ttk.Label(p3, text="Açıklama", style="FaturaUst.TLabel").grid(
            row=2, column=0, sticky="nw", padx=(0, 4), pady=py
        )
        _ack_h = ftema.form_cok_satir_text_yukseklik(3)
        self.aciklama = tk.Text(
            p3, height=_ack_h, width=24, wrap="word", font=ftema.font(9, root=self),
            relief="solid", bd=1, highlightthickness=0, padx=4, pady=2,
            bg=ftema.BEYAZ, fg=ftema.METIN,
        )
        self.aciklama.grid(row=2, column=1, rowspan=3, sticky="nsew", pady=py)
        self._siparis_ack_fr = None

        # ——— 4 Müşteri Hesap Özeti (= fatura özet kutuları) ———
        p4 = ttk.LabelFrame(ust, text="Müşteri Hesap Özeti", padding=(6, 2), style="FaturaUst.TLabelframe")
        p4.grid(row=0, column=3, sticky="new", padx=0, pady=0)
        p4.columnconfigure(0, weight=0)
        p4.columnconfigure(1, weight=1)
        _bes_satir_yuva(p4)
        self._ozet_lbl: dict[str, tk.Label] = {}
        satirlar = (
            ("mevcut", "Mevcut Cari Bakiye"),
            ("siparis", "Bu Siparişin Genel Toplamı"),
            ("islenmemis", "Cariye İşlenmemiş Tutar"),
            ("avans", "Alınan Avans"),
            ("tahmini", "Sipariş Dahil Tahmini Bakiye"),
        )
        try:
            _oz_bg = stil.lookup("TLabelframe", "background") if stil else ftema.ACIK_BG
            _oz_bg = _oz_bg or ftema.ACIK_BG
        except (tk.TclError, AttributeError):
            _oz_bg = ftema.ACIK_BG
        kutu_h = self._siparis_ozet_kutu_h
        _oz_ip = max(1, ftema.form_ipady())
        for i, (anahtar, baslik) in enumerate(satirlar):
            tk.Label(
                p4, text=baslik, bg=_oz_bg, fg=ftema.LACIVERT,
                font=ftema.font(9, "bold", self), anchor="w", bd=0, padx=0, pady=0,
            ).grid(row=i, column=0, sticky="w", padx=(0, 6), pady=py)
            cer = tk.Frame(
                p4, bg=ftema.BEYAZ, highlightthickness=1,
                highlightbackground=ftema.CIZGI, highlightcolor=ftema.CIZGI, bd=0,
                height=kutu_h,
            )
            cer.grid(row=i, column=1, sticky="nsew", pady=py)
            cer.grid_propagate(False)
            lbl = tk.Label(
                cer, text="—", bg=ftema.BEYAZ, fg=ftema.LACIVERT,
                font=ftema.font(9, "bold", self),
                anchor="e", bd=0, padx=4, pady=_oz_ip,
            )
            lbl.pack(fill="both", expand=True)
            self._ozet_lbl[anahtar] = lbl
        self._ozet_yon = tk.Label(p4, text="", bg=_oz_bg, fg=ftema.IKINCIL, font=ftema.font(9, root=self), anchor="w")

        # Sarı ayırıcı — fatura gibi panellerin hemen altında
        sari = tk.Frame(self.icerik, bg=ftema.SARI, height=2)
        sari.pack(fill="x", padx=0, pady=(0, 0))
        self._siparis_ust_sari = sari

        self._siparis_ust_paneller = (p1, p2, p3, p4)
        self._baslik_kaplari = [p1, p2, p3, p4]
        self._siparis_ust_musteri = p1
        self._siparis_ust_teslimat = p2
        self._siparis_ust_depo = p3
        self._siparis_ust_ozet = p4
        self._siparis_cok_satir_hizalandi = False

    def _siparis_ust_alt_sinir_hizala(self, _event=None):
        """Ortak alt çizgi = özet paneli (fatura ile aynı mantık); Adres/Açıklama sabit satır."""
        if getattr(self, "_siparis_cok_satir_hizalandi", False):
            return
        import fatura_tema as ftema

        paneller = getattr(self, "_siparis_ust_paneller", None)
        if not paneller:
            return
        try:
            if getattr(self, "teslimat_adresi_text", None) is not None:
                self.teslimat_adresi_text.configure(height=ftema.form_cok_satir_text_yukseklik(2))
            if getattr(self, "aciklama", None) is not None:
                self.aciklama.configure(height=ftema.form_cok_satir_text_yukseklik(3))

            self.update_idletasks()
            ozet = getattr(self, "_siparis_ust_ozet", None)
            if ozet is None:
                return
            ozet.update_idletasks()
            hedef = int(ozet.winfo_reqheight())
            if hedef < 80:
                return
            for panel in paneller:
                panel.configure(height=hedef)
                try:
                    panel.grid_propagate(False)
                except tk.TclError:
                    pass
                panel.grid_configure(sticky="new")
            self._siparis_cok_satir_hizalandi = True
            self.update_idletasks()
        except tk.TclError:
            pass

    def _siparis_adres_listesi(self, cari):
        if not cari:
            return []
        slots = (
            (1, "adres", "il", "ilce", "adres_tipi", "Merkez"),
            (2, "adres2", "il2", "ilce2", "adres_tipi2", "Fatura"),
            (3, "adres3", "il3", "ilce3", "adres_tipi3", "Sevk"),
        )
        sonuc = []
        for no, adres_alan, il_alan, ilce_alan, tip_alan, varsayilan_tip in slots:
            adres = (getattr(cari, adres_alan, None) or "").strip()
            il = (getattr(cari, il_alan, None) or "").strip()
            ilce = (getattr(cari, ilce_alan, None) or "").strip()
            tip = (getattr(cari, tip_alan, None) or "").strip() or varsayilan_tip
            if not adres and not il and not ilce:
                continue
            metin = ", ".join(p for p in (adres, ilce, il) if p)
            etiket = f"{no}. {tip}"
            sonuc.append({"no": no, "etiket": etiket, "metin": metin, "adres": adres, "il": il, "ilce": ilce})
        return sonuc

    def _siparis_adres_yaz(self, adres="", il="", ilce=""):
        w = self.girdiler["teslimat_adresi"]
        if isinstance(w, tk.Text):
            w.delete("1.0", "end")
            if adres:
                w.insert("1.0", adres)
        else:
            w.delete(0, "end")
            w.insert(0, adres)
        for alan, deger in (("teslimat_il", il), ("teslimat_ilce", ilce)):
            self.girdiler[alan].delete(0, "end")
            self.girdiler[alan].insert(0, deger or "")

    def _siparis_adres_secildi(self, _event=None):
        etiket = (self.adres_secimi.get() or "").strip()
        bilgi = self._siparis_adres_map.get(etiket)
        if not bilgi:
            return
        self._siparis_adres_yaz(bilgi.get("adres", ""), bilgi.get("il", ""), bilgi.get("ilce", ""))

    def _siparis_adreslerini_yukle(self, cari=None, kayitli_adres=None, kayitli_il=None, kayitli_ilce=None):
        cari = cari if cari is not None else self.cari
        adresler = self._siparis_adres_listesi(cari)
        self._siparis_adres_map = {a["etiket"]: a for a in adresler}
        etiketler = [a["etiket"] for a in adresler]
        self.adres_secimi.configure(values=etiketler)
        if kayitli_adres or kayitli_il or kayitli_ilce:
            self._siparis_adres_yaz(kayitli_adres or "", kayitli_il or "", kayitli_ilce or "")
            eslesen = next(
                (a for a in adresler if (a["adres"] or "") == (kayitli_adres or "").strip()),
                None,
            )
            self.adres_secimi.set(eslesen["etiket"] if eslesen else (etiketler[0] if etiketler else ""))
            return
        if adresler:
            self.adres_secimi.set(etiketler[0])
            a0 = adresler[0]
            self._siparis_adres_yaz(a0["adres"], a0["il"], a0["ilce"])
        else:
            self.adres_secimi.set("")
            self._siparis_adres_yaz("", "", "")

    def _alan_metin(self, alan: str) -> str:
        w = self.girdiler[alan]
        if isinstance(w, tk.Text):
            return w.get("1.0", "end").strip()
        return (w.get() or "").strip()

    def _satir_alani(self):
        # Üst paneller ile sabit toplamlar arasında kalan yüksekliği doldurur
        frame = self._panel("Ürün Satırları", genislet=True)
        self._satir_panel_ic = frame
        ust = tk.Frame(frame, bg=BEYAZ)
        ust.pack(fill="x", pady=(0, 2))
        tk.Label(
            ust,
            text="Barkod / kod / ad · F10 stok · Enter/Tab ilerler · sağ tık: satır işlemleri",
            bg=BEYAZ, fg=IKINCIL, font=font(9, root=self),
        ).pack(side="left")
        self._satir_butonlari = [
            tk_buton(ust, "Satırı Sil (Del)", self.satir_kaldir, rol="iptal"),
            tk_buton(ust, "Satırı Çoğalt", self.satir_cogalt, rol="duzenle"),
            tk_buton(ust, "Araya Satır Ekle", self.araya_satir_ekle, rol="duzenle"),
        ]
        for b in reversed(self._satir_butonlari):
            b.pack(side="right", padx=3)

        # Uzlaşılan tutar araçları — Satış Faturası ile aynı görünüm/işlev
        try:
            import fatura_tema as ftema

            uzlas_cer = tk.Frame(ust, bg=BEYAZ)
            uzlas_cer.pack(side="right", padx=(8, 6))
            tk.Label(
                uzlas_cer, text="Uzlaşılan Tutar", bg=BEYAZ, fg=LACIVERT,
                font=font(9, root=self),
            ).pack(side="left", padx=(0, 4))
            uzlas_w = ttk.Entry(uzlas_cer, width=12, justify="right")
            uzlas_w.pack(side="left", ipady=2)
            self._uzlasilan_tutar_entry = uzlas_w
            uzlas_w.bind("<FocusOut>", self._uzlasilan_tutar_degisti)
            uzlas_w.bind("<Return>", self._uzlasilan_tutar_degisti)
            uzlas_w.bind("<KP_Enter>", self._uzlasilan_tutar_degisti)
            uzlas_w.bind("<KeyRelease>", self._uzlasilan_tutar_canli)
            ftema.tk_buton(
                uzlas_cer, "Fiyatları Düzenle", self._uzlasilan_fiyatlara_dagit_tikla, rol="onay",
            ).pack(side="left", padx=(6, 2))
            ftema.tk_buton(
                uzlas_cer, "Dağıtımı Geri Al", self._uzlasilan_dagitim_geri_al, rol="ikincil",
            ).pack(side="left", padx=2)
        except Exception:
            self._uzlasilan_tutar_entry = None

        tablo_alan = tk.Frame(frame, bg=BEYAZ)
        tablo_alan.pack(fill="both", expand=True)
        self._satir_tablo_alan = tablo_alan
        kolonlar = (
            "sira", "kod", "ad", "miktar", "birim", "fiyat", "iskonto", "kdv", "net", "toplam", "termin",
            "sevk", "fatura", "kalan_sevk", "kalan_fatura", "aciklama",
        )
        basliklar = (
            "#", "Ürün Kodu", "Ürün Adı", "Miktar", "Birim", "Birim Fiyat", "İskonto", "KDV%",
            "Tutar (KDV Hariç)", "Tutar (KDV Dahil)", "Termin", "Sevk Edilen", "Faturalanan",
            "Kalan Sevk", "Kalan Fatura", "Açıklama",
        )
        genislikler = (36, 100, 240, 70, 60, 95, 90, 45, 115, 115, 80, 80, 80, 80, 80, 150)
        # height düşük: gerçek yükseklik pack expand ile gelir; kaydırma Treeview içinde
        self.satir_tablosu = ttk.Treeview(tablo_alan, columns=kolonlar, show="headings", height=6, selectmode="browse")
        try:
            import siparis_tema as stema

            stema.stil_uygula(root=self)
            self.satir_tablosu.configure(style="SiparisSatir.Treeview")
        except Exception:
            treeview_stil(self.satir_tablosu)
        sag = {"miktar", "fiyat", "net", "toplam", "sevk", "fatura", "kalan_sevk", "kalan_fatura"}
        for col, label, gen in zip(kolonlar, basliklar, genislikler):
            self.satir_tablosu.heading(col, text=label)
            self.satir_tablosu.column(col, width=gen, minwidth=36, anchor="e" if col in sag else "w", stretch=(col == "ad"))
        self.satir_tablosu.tag_configure("tamam", foreground=YESIL)
        yatay = ttk.Scrollbar(tablo_alan, orient="horizontal", command=self.satir_tablosu.xview)
        dikey = ttk.Scrollbar(tablo_alan, orient="vertical", command=self.satir_tablosu.yview)
        self.satir_tablosu.configure(xscrollcommand=yatay.set, yscrollcommand=dikey.set)
        self.satir_tablosu.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        yatay.grid(row=1, column=0, sticky="ew")
        tablo_alan.rowconfigure(0, weight=1)
        tablo_alan.columnconfigure(0, weight=1)
        self.satir_tablosu.bind("<Delete>", lambda _e: self.satir_kaldir())
        self._satir_ici_kur()
        self.after_idle(self._siparis_excel_cizgileri_bagla)

    def _siparis_excel_cizgileri_bagla(self) -> None:
        """Teklif ile aynı yatay/dikey hücre çizgileri."""
        if not hasattr(self, "satir_tablosu"):
            return
        from treeview_excel_cizgi import excel_cizgi_bagla

        stil_adi = "SiparisSatir.Treeview"
        try:
            if str(self.satir_tablosu.cget("style") or "").strip():
                stil_adi = str(self.satir_tablosu.cget("style"))
        except tk.TclError:
            pass
        excel_cizgi_bagla(
            self, self.satir_tablosu, style_name=stil_adi, bag_adi="siparis"
        )

    def _siparis_excel_cizgileri_yenile(self) -> None:
        ov = getattr(self, "_siparis_excel_overlay", None)
        if ov is not None:
            ov.yenile()

    def _satir_ici_kur(self):
        from satir_ici_urun_giris import HucreAlani, SatirHucreDuzenleyici, SatirIciUrunGirisi

        self._satir_ici_giris = SatirIciUrunGirisi(
            self,
            self.satir_tablosu,
            urun_ekle=self._satir_ici_urun_ekle,
            kolonlar={"kod": "kod", "ad": "ad"},
            manuel_ekle=self.manuel_satir_ekle,
            urun_degistir=self._satir_urun_degistir,
            kilitli=lambda: not self._duzenlenebilir(),
            miktara_git=lambda idx: self._hucre.duzenle(idx, "miktar"),
            depo=lambda: self.depo.get() or "",
            satir_menusu=self._satir_menusu,
        )
        manuel = lambda i: bool(self.satirlar[i].get("is_manual_item"))  # noqa: E731
        self._hucre = SatirHucreDuzenleyici(
            self,
            self.satir_tablosu,
            [
                HucreAlani("ad", "metin", izin=manuel, deger=lambda i: self.satirlar[i].get("urun_adi") or ""),
                HucreAlani("miktar", deger=lambda i: _sayi(self.satirlar[i].get("miktar") or 0)),
                HucreAlani("birim", "secim", secenekler=self._satir_birimleri, serbest=False),
                HucreAlani("fiyat", deger=lambda i: _sayi(self.satirlar[i].get("birim_fiyat") or 0)),
                HucreAlani("iskonto", "iskonto3", deger=lambda i: _satir_iskonto_metni(self.satirlar[i])),
                HucreAlani("kdv", "secim", secenekler=lambda _i: KDV_SECENEKLERI, serbest=True,
                           deger=lambda i: _sayi(self.satirlar[i].get("kdv_orani") or 0)),
                HucreAlani("termin", "metin", deger=lambda i: _tarih(self.satirlar[i].get("termin"))),
                HucreAlani("aciklama", "metin", deger=lambda i: self.satirlar[i].get("aciklama") or ""),
            ],
            uygula=self.satir_hucre_uygula,
            satir_sayisi=lambda: len(self.satirlar),
            kilitli=lambda: not self._duzenlenebilir(),
            bitince=self._satir_ici_giris.odakla,
        )

    def _aciklama_ve_toplam(self):
        """Satış Faturası ile aynı iki sütunlu sticky alt toplamlar + Notlar."""
        import siparis_tema as stema

        refs = stema.siparis_alt_ozet(self, pack=False)
        self._siparis_ozet_refs = refs
        self._toplamlar_dis = refs["dis"]
        degerler = refs.get("degerler") or {}
        self.siparis_toplam_degerleri = degerler
        # Eski yatay şerit API uyumu (test / yardımcı kod)
        self._toplam_lbl = {
            "kalem": refs.get("kalem_lbl"),
            "miktar": refs.get("miktar_lbl"),
            "ara": degerler.get("ara_toplam"),
            "iskonto": degerler.get("iskonto"),
            "net": degerler.get("matrah"),
            "kdv": degerler.get("kdv"),
            "genel": degerler.get("genel"),
        }
        # Footer not ↔ üst açıklama senkron
        not_w = refs.get("not_alani")
        if not_w is not None and hasattr(self, "aciklama"):
            try:
                metin = self.aciklama.get("1.0", "end-1c")
                if metin.strip():
                    not_w.insert("1.0", metin)
            except tk.TclError:
                pass

            def _not_senkron(_event=None):
                try:
                    self.aciklama.delete("1.0", "end")
                    self.aciklama.insert("1.0", not_w.get("1.0", "end-1c"))
                except tk.TclError:
                    pass

            not_w.bind("<KeyRelease>", _not_senkron, add="+")
            not_w.bind("<FocusOut>", _not_senkron, add="+")

    # --------------------------------------------------------- uzlaşılan fiyat
    def _uzlasilan_tutar_oku(self):
        from database.fatura_genel_toplam_service import kurus

        w = getattr(self, "_uzlasilan_tutar_entry", None)
        if w is None:
            return getattr(self, "_uzlasilan_tutar", None)
        try:
            ham = (w.get() or "").strip().replace("TL", "").replace("tl", "").strip()
        except tk.TclError:
            return getattr(self, "_uzlasilan_tutar", None)
        if not ham:
            return None
        return kurus(decimal(ham, "Uzlaşılan tutar", Decimal("0")))

    def _uzlasilan_tutar_yaz(self, tutar) -> None:
        w = getattr(self, "_uzlasilan_tutar_entry", None)
        if w is None:
            return
        try:
            metin = "" if tutar is None else para_metni(tutar, self.para_birimi.get() or "TRY").rsplit(" ", 1)[0]
            if w.get().strip() == metin:
                return
            w.delete(0, "end")
            if metin:
                w.insert(0, metin)
        except tk.TclError:
            pass

    def _uzlasilan_tutar_degisti(self, _event=None):
        if getattr(self, "_uzlasilan_ui_kilit", False):
            return "break"
        try:
            self._uzlasilan_tutar = self._uzlasilan_tutar_oku()
        except ValueError as hata:
            messagebox.showerror("Uzlaşılan tutar", str(hata), parent=self)
            return "break"
        self.toplam_guncelle()
        return "break"

    def _uzlasilan_tutar_canli(self, _event=None):
        if getattr(self, "_uzlasilan_ui_kilit", False):
            return
        try:
            self._uzlasilan_tutar = self._uzlasilan_tutar_oku()
        except ValueError:
            return
        try:
            self.toplam_guncelle()
        except Exception:
            pass

    def _uzlasilan_satir_genel(self, veri) -> Decimal:
        from database.fatura_genel_toplam_service import kurus

        h = satir_hesapla(
            veri.get("miktar") or 0,
            veri.get("birim_fiyat") or veri.get("birim_satis_fiyati") or 0,
            veri.get("iskonto_orani") or 0,
            veri.get("iskonto_orani_2") or 0,
            veri.get("iskonto_orani_3") or 0,
            veri.get("kdv_orani") or 0,
        )
        return kurus(h["toplam"])

    def _uzlasilan_brut_referans(self, satir_brut: Decimal) -> Decimal:
        from database.fatura_genel_toplam_service import kurus

        snap = getattr(self, "_uzlasilan_snapshot_brut", None)
        if snap is not None:
            return kurus(snap)
        return kurus(satir_brut)

    def _uzlasilan_indirim_masraf(self, brut: Decimal) -> dict:
        from database.uzlasilan_tutar_service import uzlasilan_indirim_masraf as _fn

        hedef = getattr(self, "_uzlasilan_tutar", None)
        if hedef is None:
            try:
                hedef = self._uzlasilan_tutar_oku()
            except ValueError:
                hedef = None
        return _fn(brut, hedef)

    def _uzlasilan_fiyat_snapshot_al(self) -> None:
        from database.fatura_genel_toplam_service import kurus

        if getattr(self, "_uzlasilan_fiyat_snapshot", None):
            return
        self._uzlasilan_fiyat_snapshot = [
            {
                "birim_fiyat": Decimal(str(v.get("birim_fiyat") or 0)),
                "birim_satis_fiyati": Decimal(str(v.get("birim_satis_fiyati") or v.get("birim_fiyat") or 0)),
                "iskonto_orani": Decimal(str(v.get("iskonto_orani") or 0)),
                "iskonto_orani_2": Decimal(str(v.get("iskonto_orani_2") or 0)),
                "iskonto_orani_3": Decimal(str(v.get("iskonto_orani_3") or 0)),
            }
            for v in self.satirlar
        ]
        self._uzlasilan_snapshot_brut = kurus(
            sum((self._uzlasilan_satir_genel(v) for v in self.satirlar), Decimal("0"))
        )

    def _uzlasilan_fiyatlara_dagit(self) -> None:
        from database.fatura_genel_toplam_service import kurus
        from database.uzlasilan_tutar_service import uzlasilan_fiyatlara_dagit

        hedef = getattr(self, "_uzlasilan_tutar", None)
        if hedef is None or not self.satirlar:
            self.toplam_guncelle()
            return
        for v in self.satirlar:
            if v.get("birim_satis_fiyati") is None:
                v["birim_satis_fiyati"] = Decimal(str(v.get("birim_fiyat") or 0))
        onceki = kurus(sum((self._uzlasilan_satir_genel(v) for v in self.satirlar), Decimal("0")))
        hedef_k = kurus(hedef)
        if onceki == hedef_k:
            self.toplam_guncelle()
            return
        self._uzlasilan_fiyat_snapshot_al()
        sonuc = uzlasilan_fiyatlara_dagit(
            self.satirlar,
            hedef_k,
            satir_genel_fn=self._uzlasilan_satir_genel,
        )
        if sonuc.get("degisti"):
            for v in self.satirlar:
                fiyat = Decimal(str(v.get("birim_satis_fiyati") or v.get("birim_fiyat") or 0))
                v["birim_fiyat"] = fiyat
                v["birim_satis_fiyati"] = fiyat
            self.satir_listesini_yenile()
        self.toplam_guncelle()

    def _uzlasilan_fiyatlara_dagit_tikla(self, _event=None):
        if not self._duzenlenebilir():
            return "break"
        from database.fatura_genel_toplam_service import kurus

        try:
            self._uzlasilan_tutar = self._uzlasilan_tutar_oku()
        except ValueError as hata:
            messagebox.showerror("Uzlaşılan tutar", str(hata), parent=self)
            return "break"
        hedef = self._uzlasilan_tutar
        if hedef is None:
            hedef = getattr(self, "_hesaplanan_genel", None)
        if hedef is None:
            messagebox.showinfo(
                "Fiyatları Düzenle",
                "Önce Uzlaşılan Tutar (Net hedef) girin.",
                parent=self,
            )
            return "break"
        if not self.satirlar:
            messagebox.showwarning(
                "Fiyatları Düzenle", "Önce sipariş satırı ekleyin.", parent=self
            )
            return "break"
        onceki = kurus(sum((self._uzlasilan_satir_genel(v) for v in self.satirlar), Decimal("0")))
        hedef_k = kurus(hedef)
        if onceki == hedef_k:
            messagebox.showinfo(
                "Fiyatları Düzenle",
                "Satır toplamı zaten Net Toplam ile aynı — fiyatlar tutarlı.",
                parent=self,
            )
            return "break"
        if not messagebox.askyesno(
            "Fiyatları Düzenle",
            f"Orijinal Brüt {para_metni(onceki)} sabit kalır.\n"
            f"Birim fiyatlar Net {para_metni(hedef_k)} olacak şekilde orantılı yenilenir.\n\n"
            "İndirim/Masraf, sabit Brüt ile Net farkından okunmaya devam eder.\n"
            "(«Dağıtımı Geri Al» eski fiyatlara döner.)",
            parent=self,
        ):
            return "break"
        self._uzlasilan_tutar = hedef_k
        try:
            self._uzlasilan_fiyat_snapshot_al()
            self._uzlasilan_fiyatlara_dagit()
        except ValueError as hata:
            messagebox.showerror("Fiyatlara dağıtılamadı", str(hata), parent=self)
            return "break"
        self._uzlasilan_ui_kilit = True
        try:
            self._uzlasilan_tutar_yaz(hedef_k)
        finally:
            self._uzlasilan_ui_kilit = False
        brut_ref = getattr(self, "_uzlasilan_snapshot_brut", onceki)
        messagebox.showinfo(
            "Fiyatları Düzenle",
            f"{len(self.satirlar)} satır güncellendi.\n"
            f"Brüt (sabit): {para_metni(brut_ref)}\n"
            f"Net: {para_metni(hedef_k)}\n"
            f"Fark İndirim/Masraf satırında görünür.",
            parent=self,
        )
        return "break"

    def _uzlasilan_dagitim_geri_al(self, _event=None):
        if not self._duzenlenebilir():
            return "break"
        snap = getattr(self, "_uzlasilan_fiyat_snapshot", None)
        if not snap:
            messagebox.showinfo(
                "Dağıtımı geri al", "Geri alınacak fiyat dağıtımı yok.", parent=self
            )
            return "break"
        if not messagebox.askyesno(
            "Dağıtımı geri al",
            "Dağıtım öncesi birim fiyatlar geri yüklensin mi?\n"
            "Brüt tekrar orijinal satır toplamına döner; Net Uzlaşılan’da kalır (İndirim/Masraf).",
            parent=self,
        ):
            return "break"
        for i, veri in enumerate(self.satirlar):
            if i >= len(snap):
                break
            eski = snap[i]
            fiyat = eski.get("birim_fiyat", eski.get("birim_satis_fiyati", 0))
            veri["birim_fiyat"] = fiyat
            veri["birim_satis_fiyati"] = eski.get("birim_satis_fiyati", fiyat)
            veri["iskonto_orani"] = eski.get("iskonto_orani", 0)
            veri["iskonto_orani_2"] = eski.get("iskonto_orani_2", 0)
            veri["iskonto_orani_3"] = eski.get("iskonto_orani_3", 0)
        self._uzlasilan_fiyat_snapshot = None
        self._uzlasilan_snapshot_brut = None
        self.satir_listesini_yenile()
        self.toplam_guncelle()
        return "break"

    def _kisayollar(self):
        self.bind("<F2>", lambda _e: self.kaydet())
        self.bind("<Control-s>", lambda _e: self.kaydet())
        self.bind("<F10>", lambda _e: self.musteri_sec())
        self.bind("<F3>", self.urun_arama_ac)
        self.bind("<Escape>", lambda _e: self.kapat())

    def _odak(self, widget):
        try:
            widget.focus_set()
            if isinstance(widget, ttk.Entry):
                widget.selection_range(0, "end")
        except tk.TclError:
            pass
        return "break"

    # ------------------------------------------------------------ durum/kilit
    def _durum(self) -> str:
        return (getattr(self.siparis, "durum", None) or "TASLAK") if self.siparis else "TASLAK"

    def _iptal(self) -> bool:
        return self.siparis is not None and self._durum() == "İPTAL"

    def _bagli(self) -> bool:
        return self.siparis is not None and any(
            decimal(s.get("irsaliyelenen") or 0, "S") > 0 or decimal(s.get("faturalanan") or 0, "F") > 0
            for s in self.satirlar
        )

    def _duzenlenebilir(self) -> bool:
        return not self._iptal()

    def _kilit_uygula(self):
        duz = self._duzenlenebilir()
        kayitli = self.siparis is not None
        bagli = self._bagli()
        durum = self._durum()
        durumlar = {
            "kaydet": duz,
            "onayla": duz and durum == "TASLAK",
            "onay_kaldir": kayitli and durum not in ("TASLAK", "İPTAL") and not bagli,
            "irsaliye": kayitli and duz,
            "fatura": kayitli and duz,
            "bagli": kayitli,
            "iptal": kayitli and duz,
            "sil": kayitli and not bagli,
        }
        for anahtar, aktif in durumlar.items():
            try:
                self.btn[anahtar].configure(state="normal" if aktif else "disabled")
            except (KeyError, tk.TclError):
                pass
        giris = "normal" if duz else "disabled"
        for alan, w in self.girdiler.items():
            if alan in ("bakiye", "avans"):
                continue
            if alan == "siparis_no":
                w.configure(state="readonly" if kayitli else "normal")
                continue
            if alan == "teslim_sekli":
                try:
                    w.configure(state="readonly" if duz else "disabled")
                except tk.TclError:
                    pass
                continue
            if isinstance(w, tk.Text):
                w.configure(state=giris)
                continue
            if alan == "kur":
                w.configure(state=giris if self.para_birimi.get() != "TRY" else "disabled")
            else:
                try:
                    w.configure(state=giris)
                except tk.TclError:
                    pass
        self.musteri.configure(state="normal" if duz and not bagli else "disabled")
        self._musteri_btn.configure(state="normal" if duz and not bagli else "disabled")
        try:
            self.musteri_kodu.configure(state="readonly")
        except tk.TclError:
            pass
        try:
            self.adres_secimi.configure(state="readonly" if duz else "disabled")
        except tk.TclError:
            pass
        self.depo.configure(state="readonly" if duz else "disabled")
        self.para_birimi.configure(state="readonly" if duz and not bagli else "disabled")
        for b in self._satir_butonlari:
            b.configure(state="normal" if duz else "disabled")
        uz = getattr(self, "_uzlasilan_tutar_entry", None)
        if uz is not None:
            try:
                uz.configure(state="normal" if duz else "disabled")
            except tk.TclError:
                pass
        if not duz:
            self._hucre.kapat()
        self._satir_ici_giris.tabloya_ekle()
        self.aciklama.configure(state="normal" if duz else "disabled")
        refs = getattr(self, "_siparis_ozet_refs", None) or {}
        not_w = refs.get("not_alani")
        if not_w is not None:
            try:
                not_w.configure(state="normal" if duz else "disabled")
            except tk.TclError:
                pass
        self._durum_rozet_guncelle()
        self._meta_yenile()

    def _meta_yenile(self):
        no = ""
        try:
            no = self.girdiler.get("siparis_no").get().strip() if "siparis_no" in self.girdiler else ""
        except (tk.TclError, AttributeError):
            no = ""
        if self.siparis is None:
            no_metin = no if no and no != YENI_NO_METNI else YENI_NO_METNI
            self._meta_label.configure(
                text=f"Sipariş No: {no_metin}  |  Yeni sipariş — stok ve cari hareketi oluşturmaz"
            )
            self._ilerleme_badge.configure(text="")
            return
        parcalar = [f"Sipariş No: {self.siparis.siparis_no or no or ''}"]
        if getattr(self.siparis, "musteri_siparis_no", None):
            parcalar.append(f"Müşteri ref: {self.siparis.musteri_siparis_no}")
        if self._iptal():
            parcalar.append("İptal edildi — salt okunur")
        elif self._bagli():
            parcalar.append("Sevk/fatura bağlantısı var — müşteri, para birimi ve bağlı satırların ürünü değiştirilemez")
        else:
            parcalar.append("Stok ve cari hareketi yok")
        self._meta_label.configure(text="  |  ".join(p for p in parcalar if p))
        self._ilerleme_badge.configure(text=siparis_ilerleme(self.siparis))

    def _durum_rozet_guncelle(self):
        d = self._durum()
        bg, fg = DURUM_RENK.get(d, (GRI, BEYAZ))
        self._badge.configure(text=d, bg=bg, fg=fg)

    # --------------------------------------------------------- değişiklik izi
    def _imza(self) -> tuple:
        def _w_metin(k, w):
            if isinstance(w, tk.Text):
                return w.get("1.0", "end").strip()
            try:
                return w.get()
            except tk.TclError:
                return ""

        alanlar = tuple(
            (k, _w_metin(k, w))
            for k, w in sorted(self.girdiler.items())
            if k not in ("bakiye", "avans", "siparis_no")
        )
        no = self.girdiler["siparis_no"].get() if self.siparis is None else ""
        satirlar = tuple(
            tuple(str(s.get(k) if s.get(k) is not None else "") for k in (
                "id", "urun_kodu", "urun_adi", "miktar", "birim", "birim_fiyat", "iskonto_orani",
                "iskonto_orani_2", "iskonto_orani_3", "kdv_orani", "termin", "aciklama", "is_manual_item",
            ))
            for s in self.satirlar
        )
        return (
            alanlar, no, self.aciklama.get("1.0", "end").strip(), satirlar, self.depo.get(),
            self.para_birimi.get(), getattr(self.cari, "id", None),
            str(getattr(self, "_uzlasilan_tutar", None) or ""),
            str(getattr(self, "_genel_islem_turu", "") or ""),
            str(getattr(self, "_genel_islem_tutari", 0) or 0),
        )

    def degisiklik_var(self) -> bool:
        if not self._duzenlenebilir():
            return False
        if self.siparis is None and not self.satirlar and self.cari is None:
            return False
        return self._kayit_imzasi is None or self._imza() != self._kayit_imzasi

    def _kaydetmeyi_sor(self, islem: str) -> bool:
        if not self.degisiklik_var():
            return True
        cevap = messagebox.askyesnocancel(
            "Kaydedilmemiş değişiklik",
            f"Siparişte kaydedilmemiş değişiklikler var.\n{islem} önce kaydedilsin mi?\n\n"
            "Evet: kaydet ve devam et   Hayır: kaydetmeden devam et   İptal: geri dön",
            parent=self,
        )
        if cevap is None:
            return False
        if cevap:
            return self.kaydet(sessiz=True)
        return True

    def kapat(self):
        if not self._kaydetmeyi_sor("Kapatmadan"):
            return
        self.destroy()

    def destroy(self):
        try:
            self.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        super().destroy()

    # --------------------------------------------------------------- müşteri
    def musteri_ara(self, _event=None):
        """Müşteri adı/kodu ile arar; tam kod eşleşirse doğrudan seçer."""
        if not self._duzenlenebilir() or self._bagli():
            return "break"
        metin = self._musteri_var.get().strip()
        kod = ""
        try:
            kod = self.musteri_kodu.get().strip()
        except tk.TclError:
            pass
        if self.cari is not None and metin == (self.cari.unvan or "") and kod == (self.cari.cari_kodu or ""):
            return self._odak(self.girdiler.get("siparis_tarihi") or self.depo)
        if not metin:
            return self.musteri_sec()
        try:
            from database.cari_service import CariService

            aktifler = list(CariService.aktif_musteriler())
            aday = next(
                (c for c in aktifler if (c.cari_kodu or "").casefold() == metin.casefold()),
                None,
            )
            if aday is None:
                eslesen = [
                    c for c in aktifler
                    if metin.casefold() in (c.unvan or "").casefold()
                    or metin.casefold() in (c.cari_kodu or "").casefold()
                ]
                if len(eslesen) == 1:
                    aday = eslesen[0]
        except Exception:
            aday = None
        if aday is not None:
            self._musteri_ata(aday)
            return self._odak(self.girdiler.get("siparis_tarihi") or self.depo)
        return self.musteri_sec(ara=metin)

    def musteri_sec(self, ara: str = ""):
        if not self._duzenlenebilir() or self._bagli():
            return "break"
        try:
            from app import MusteriSecimDialog
            from database.cari_service import CariService

            musteriler = sorted(
                CariService.aktif_musteriler(),
                key=lambda c: ((c.unvan or "").casefold(), (c.cari_kodu or "").casefold()),
            )[:80]
            try:
                bakiyeler = CariService.musteri_bakiyeleri_toplu([c.id for c in musteriler])
            except Exception:
                bakiyeler = {}
        except Exception as exc:
            messagebox.showerror("Müşteri", f"Müşteri listesi açılamadı.\n{exc}", parent=self)
            return "break"
        dialog = MusteriSecimDialog(
            self, musteriler=musteriler, bakiyeler=bakiyeler, ara=ara, on_select=self._musteri_ata, canli_arama=True,
        )
        self.wait_window(dialog)
        if self.cari is not None:
            self._odak(self.girdiler.get("siparis_tarihi") or self.depo)
        return "break"

    def _musteri_ata(self, cari):
        if cari is None:
            return
        onceki = self.cari
        if onceki is not None and int(onceki.id) != int(cari.id) and self._bagli():
            messagebox.showwarning(
                "Müşteri değiştirilemez",
                "Sevk veya fatura bağlantısı olan siparişin müşterisi değiştirilemez.",
                parent=self,
            )
            return
        self.cari = cari
        self._musteri_etiket = f"{cari.cari_kodu} - {cari.unvan}"
        self._musteri_var.set(cari.unvan or "")
        try:
            self.musteri_kodu.configure(state="normal")
            self.musteri_kodu.delete(0, "end")
            self.musteri_kodu.insert(0, cari.cari_kodu or "")
            self.musteri_kodu.configure(state="readonly")
        except tk.TclError:
            pass
        self.bakiye_guncelle()
        if onceki is None or int(onceki.id) != int(cari.id):
            # Eski müşteri adresi kalmasın; kayıtlı adresler veya cari varsayılanı
            self._siparis_adreslerini_yukle(cari)

    def bakiye_guncelle(self):
        bakiye = Decimal("0")
        if self.cari:
            try:
                from database.cari_bakiye_service import net_bakiye

                bakiye = Decimal(str(net_bakiye(int(self.cari.id)).get("net") or 0))
            except Exception:
                try:
                    from database.satis_irsaliyesi_service import SatisIrsaliyesiService

                    bakiye = SatisIrsaliyesiService.mevcut_bakiye(self.cari.id)
                except Exception:
                    bakiye = Decimal("0")
        self._mevcut_bakiye = bakiye
        w = self.girdiler["bakiye"]
        try:
            w.configure(state="normal")
            w.delete(0, "end")
            w.insert(0, para_metni(bakiye) if self.cari else "")
            w.configure(state="readonly")
        except tk.TclError:
            pass
        self._hesap_ozeti_yenile()

    def _islenmemis_genel_toplam(self) -> Decimal:
        """Faturalanmamış kalan miktarın KDV dâhil tutarı (cariye henüz girmeyen)."""
        toplam = Decimal("0")
        for veri in self.satirlar:
            miktar = decimal(veri.get("miktar") or 0, "Miktar")
            if miktar <= 0:
                continue
            fat = decimal(veri.get("faturalanan") or 0, "F")
            kalan = miktar - fat
            if kalan <= 0:
                continue
            h = satir_hesapla(
                miktar, veri.get("birim_fiyat") or 0, veri.get("iskonto_orani") or 0,
                veri.get("iskonto_orani_2") or 0, veri.get("iskonto_orani_3") or 0, veri.get("kdv_orani") or 0,
            )
            toplam += (h["toplam"] * kalan / miktar)
        return toplam.quantize(Decimal("0.01"))

    def _belge_tutarini_tl(self, tutar: Decimal) -> Decimal:
        pb = (self.para_birimi.get() or "TRY").upper()
        if pb in ("TRY", "TL"):
            return tutar
        kur = self._kur_degeri()
        if kur <= 0:
            return Decimal("0")
        return (tutar * kur).quantize(Decimal("0.01"))

    def _hesap_ozeti_yenile(self, genel_toplam: Decimal | None = None):
        if not getattr(self, "_ozet_lbl", None):
            return
        if not self.cari:
            # Müşteri yok ≠ gerçek sıfır bakiye
            for anahtar in self._ozet_lbl:
                self._ozet_lbl[anahtar].configure(
                    text="Müşteri seçiniz" if anahtar == "mevcut" else "—"
                )
            try:
                self._ozet_yon.configure(text="")
            except tk.TclError:
                pass
            return
        if genel_toplam is None:
            genel_toplam = belge_toplamlari([dict(s) for s in self.satirlar])["genel_toplam"]
        islenmemis = self._islenmemis_genel_toplam()
        avans = getattr(self, "_avans", Decimal("0")) or Decimal("0")
        pb = (self.para_birimi.get() or "TRY").upper()
        self._ozet_lbl["mevcut"].configure(text=para_metni(self._mevcut_bakiye))
        self._ozet_lbl["siparis"].configure(text=para_metni(genel_toplam, pb))
        self._ozet_lbl["islenmemis"].configure(text=para_metni(islenmemis, pb))
        if avans:
            self._ozet_lbl["avans"].configure(text=f"{para_metni(avans, pb)} (bakiyeye dâhil)")
        else:
            self._ozet_lbl["avans"].configure(text=para_metni(Decimal("0"), pb))
        # Avans cari bakiyeye yansımış kabul; tahmini = mevcut + işlenmemiş (çift düşüm yok)
        if pb not in ("TRY", "TL") and self._kur_degeri() <= 0:
            self._ozet_lbl["tahmini"].configure(text="Kur eksik")
            try:
                self._ozet_yon.configure(text="TL tahmini hesaplanamadı", fg=TURUNCU)
            except tk.TclError:
                pass
            return
        tahmini = (self._mevcut_bakiye + self._belge_tutarini_tl(islenmemis)).quantize(Decimal("0.01"))
        self._ozet_lbl["tahmini"].configure(text=para_metni(tahmini))
        try:
            if tahmini > 0:
                self._ozet_yon.configure(text="(Borç)", fg=KIRMIZI)
            elif tahmini < 0:
                self._ozet_yon.configure(text="(Alacak)", fg=YESIL)
            else:
                self._ozet_yon.configure(text="(Sıfır)", fg=IKINCIL)
        except tk.TclError:
            pass

    def _para_birimi_degisti(self, _event=None):
        pb = self.para_birimi.get() or "TRY"
        kur = self.girdiler["kur"]
        kur.configure(state="normal")
        kur.delete(0, "end")
        if pb == "TRY":
            kur.insert(0, "1")
        else:
            try:
                from database.doviz_service import DovizService

                tarih = _tarih_coz(self.girdiler["siparis_tarihi"].get(), "Sipariş tarihi", zorunlu=False) or date.today()
                deger = DovizService.kur_degeri(tarih, pb, varsayilan=None)
            except Exception:
                deger = None
            if deger:
                kur.insert(0, _sayi(deger))
        kur.configure(state="normal" if pb != "TRY" else "disabled")
        self.satir_listesini_yenile()
        if pb != "TRY" and not kur.get().strip():
            messagebox.showinfo("Kur", f"{pb} için kayıtlı kur bulunamadı; kuru elle girin.", parent=self)
            self._odak(kur)

    def _kur_degeri(self) -> Decimal:
        if (self.para_birimi.get() or "TRY") == "TRY":
            return Decimal("1")
        try:
            kur = decimal(self.girdiler["kur"].get() or 0, "Kur", Decimal("0"))
        except ValueError:
            return Decimal("0")
        return kur

    def _belge_kurlari(self) -> dict[str, Decimal]:
        pb = (self.para_birimi.get() or "TRY").upper()
        if pb in ("TRY", "TL"):
            return {}
        kur = self._kur_degeri()
        return {pb: kur} if kur > 0 else {}

    def _tl_fiyati_belge_parasina(self, fiyat):
        if fiyat in (None, ""):
            return None
        kur = self._kur_degeri()
        fiyat = decimal(fiyat, "Fiyat", Decimal("0"))
        if (self.para_birimi.get() or "TRY") == "TRY":
            return fiyat
        if kur <= 0:
            return None
        return (fiyat / kur).quantize(Decimal("0.0001"))

    # ----------------------------------------------------------------- ürün
    def urun_arama_ac(self, _event=None):
        if self._duzenlenebilir():
            self._satir_ici_giris.stok_listesi_ac()
        return "break"

    def stok_listesi_ac(self):
        if self._duzenlenebilir():
            self._satir_ici_giris.stok_listesi_ac("")

    def _birim_secenekleri(self, kod: str, zorunlu_birim: str | None = None) -> list[str]:
        if zorunlu_birim:
            return [zorunlu_birim]
        try:
            from birim_secim_ui import evrak_birim_secenekleri

            return evrak_birim_secenekleri(kod) or ["Adet"]
        except Exception:
            return ["Adet"]

    def _satir_birimleri(self, idx: int) -> list[str]:
        s = self.satirlar[idx]
        if s.get("is_manual_item"):
            return list(BIRIMLER)
        return self._birim_secenekleri(s.get("urun_kodu") or "", s.get("birim") if self._satir_bagli_mi(s) else None)

    def _cari_fiyati(self, kod: str, birim: str, varsayilan=None):
        """Cari fiyat kuralları (belge para birimine çevrilmiş); bulunamazsa varsayılan."""
        fiyat = None
        try:
            from fatura_satir_birim_service import birim_satis_fiyati_tl

            fiyat = birim_satis_fiyati_tl(
                kod, birim or "Adet", musteri=self.cari, kurlar=self._belge_kurlari()
            )
        except Exception:
            fiyat = None
        if fiyat in (None, ""):
            fiyat = varsayilan
        if fiyat in (None, ""):
            return None
        return self._tl_fiyati_belge_parasina(fiyat)

    def _stok_karti(self, kod: str):
        from database.stok_service import StokService

        return next((s for s in StokService.stoklari_ara(kod) if (s.stok_kodu or "") == kod), None)

    def _satir_bagli_mi(self, s: dict[str, Any]) -> bool:
        return decimal(s.get("irsaliyelenen") or 0, "S") > 0 or decimal(s.get("faturalanan") or 0, "F") > 0

    def _degerlerden_satir(self, degerler) -> dict[str, Any]:
        from satir_ici_urun_giris import HIZLI_STOK_KAYNAGI, ondalik

        kod = (degerler[0] if degerler else "") or ""
        ad = (degerler[1] if len(degerler) > 1 else "") or ""
        birim = (degerler[2] if len(degerler) > 2 else "") or "Adet"
        ipucu = degerler[4] if len(degerler) > 4 else None
        kaynak = degerler[5] if len(degerler) > 5 else ""
        kdv_metin = degerler[6] if len(degerler) > 6 else None
        if not kod:
            raise ValueError("Ürün kodu boş.")
        if kaynak == HIZLI_STOK_KAYNAGI and ipucu not in (None, ""):
            fiyat = self._tl_fiyati_belge_parasina(ipucu)
        else:
            fiyat = self._cari_fiyati(kod, birim, ipucu)
        try:
            kdv = ondalik(kdv_metin, Decimal("20")) if kdv_metin not in (None, "") else Decimal("20")
        except ValueError:
            kdv = Decimal("20")
        if kaynak != HIZLI_STOK_KAYNAGI:
            from database.fiyat_kaynagi_service import satis_kdv_haric

            if fiyat not in (None, ""):
                fiyat, _not = satis_kdv_haric(kod, fiyat, kdv, musteri=self.cari)
            if fiyat in (None, "") or decimal(fiyat, "Fiyat", Decimal("0")) <= 0:
                from fiyat_kaynagi_ui import fiyat_yok_bildir

                fiyat_yok_bildir(self, kod, f"{kod}: fiyat listesinde geçerli satış fiyatı yok; birim fiyatı girin.")
        return {
            "urun_kodu": kod, "urun_adi": ad, "birim": birim, "miktar": Decimal("1"),
            "birim_fiyat": fiyat if fiyat is not None else Decimal("0"),
            "iskonto_orani": 0, "iskonto_orani_2": 0, "iskonto_orani_3": 0, "kdv_orani": kdv,
            "termin": None, "aciklama": "", "is_manual_item": False,
        }

    def urun_secildi(self, values):
        """UrunSecDialog geri çağrısı: ürünü yeni satır olarak ekler."""
        self._satir_ici_urun_ekle(values, None)

    def _satir_ici_urun_ekle(self, degerler, konum: int | None) -> int | None:
        from satir_ici_urun_giris import birlesecek_satir, giris_bileseni, toplu_ekleme_mi

        if not self._duzenlenebilir():
            return None
        veri = self._degerlerden_satir(degerler)
        if not self._stok_satiri_hazirla(veri):
            return None
        giris = giris_bileseni(self)
        if giris is not None and giris.son_islem == "barkod" and konum is None:
            adaylar = [s if not self._satir_bagli_mi(s) else {**s, "siparis_satiri_id": -1} for s in self.satirlar]
            idx = birlesecek_satir(adaylar, veri, fiyat_alani="birim_fiyat", ek_alanlar=("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3"))
            if idx is not None:
                s = self.satirlar[idx]
                s["miktar"] = decimal(s.get("miktar") or 0, "Miktar") + Decimal("1")
                if not toplu_ekleme_mi(self):
                    self.satir_listesini_yenile()
                return idx
        if konum is not None and 0 <= konum <= len(self.satirlar):
            self.satirlar.insert(konum, veri)
            idx = konum
        else:
            self.satirlar.append(veri)
            idx = len(self.satirlar) - 1
        if not toplu_ekleme_mi(self):
            self.satir_listesini_yenile()
        return idx

    def _satir_toplu_yenile(self):
        self.satir_listesini_yenile()

    def manuel_satir_ekle(self, ad: str = "", konum: int | None = None) -> int | None:
        """Stokta olmayan ürün satırı (ürün adı ve birim zorunlu)."""
        if not self._duzenlenebilir():
            return None
        ad = (ad or "").strip()
        if not ad:
            ad = (simpledialog.askstring("Manuel kalem", "Stokta olmayan ürünün adı:", parent=self) or "").strip()
        if not ad:
            return None
        veri = {
            "urun_kodu": MANUEL_KOD, "urun_adi": ad, "birim": "Adet", "miktar": Decimal("1"),
            "birim_fiyat": Decimal("0"), "iskonto_orani": 0, "iskonto_orani_2": 0, "iskonto_orani_3": 0,
            "kdv_orani": Decimal("20"), "termin": None, "aciklama": "", "is_manual_item": True,
            "stock_pending": True,
        }
        if konum is not None and 0 <= konum <= len(self.satirlar):
            self.satirlar.insert(konum, veri)
            idx = konum
        else:
            self.satirlar.append(veri)
            idx = len(self.satirlar) - 1
        self.satir_listesini_yenile()
        return idx

    def _satir_urun_degistir(self, idx: int, degerler) -> bool:
        if not (0 <= idx < len(self.satirlar)) or not self._duzenlenebilir():
            return False
        eski = self.satirlar[idx]
        if self._satir_bagli_mi(eski):
            messagebox.showwarning(
                "Bağlı satır",
                "Sevk veya fatura edilmiş satırın ürünü değiştirilemez.\n"
                f"Bağlı evrak: {self._satir_bagli_metni(eski)}",
                parent=self,
            )
            return False
        try:
            veri = self._degerlerden_satir(degerler)
        except ValueError as hata:
            messagebox.showwarning("Ürün", str(hata), parent=self)
            return False
        if not self._stok_satiri_hazirla(veri):
            return False
        veri["miktar"] = eski.get("miktar") or Decimal("1")
        veri["termin"] = eski.get("termin")
        veri["aciklama"] = eski.get("aciklama") or ""
        for anahtar in ("id", "delivery_term_days", "delivery_term_note"):
            if anahtar in eski:
                veri[anahtar] = eski[anahtar]
        self.satirlar[idx] = veri
        self.satir_listesini_yenile()
        return True

    def satir_hucre_uygula(self, idx: int, kolon: str, metin: str) -> None:
        """Hücre editöründen gelen değer; geçersizse ValueError (satır değişmez)."""
        from satir_ici_urun_giris import iskonto_metni_coz

        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        bagli = self._satir_bagli_mi(s)
        yeni = dict(s)
        if kolon == "ad":
            if not metin:
                raise ValueError("Stokta olmayan ürün için ürün adı zorunludur.")
            yeni["urun_adi"] = metin
        elif kolon == "miktar":
            miktar = decimal(metin or 0, "Miktar")
            if miktar <= 0:
                raise ValueError("Miktar sıfırdan büyük olmalıdır.")
            sevk = decimal(s.get("irsaliyelenen") or 0, "S")
            fat = decimal(s.get("faturalanan") or 0, "F")
            if miktar < max(sevk, fat):
                raise ValueError(
                    f"Miktar {_sayi(max(sevk, fat))} altına indirilemez (sevk edilen {_sayi(sevk)}, "
                    f"faturalanan {_sayi(fat)}).\nBağlı evrak: {self._satir_bagli_metni(s)}"
                )
            yeni["miktar"] = miktar
        elif kolon == "birim":
            birim = (metin or "").strip()
            if not birim:
                raise ValueError("Birim zorunludur.")
            if birim.casefold() == (s.get("birim") or "").casefold():
                return
            if bagli:
                raise ValueError(
                    "Sevk veya fatura edilmiş satırın birimi değiştirilemez.\n"
                    f"Bağlı evrak: {self._satir_bagli_metni(s)}"
                )
            if not s.get("is_manual_item"):
                from birim_secim_ui import kart_birimini_hazirla

                if not kart_birimini_hazirla(self, s.get("urun_kodu") or "", birim):
                    return
            yeni_fiyat = True
            if not s.get("is_manual_item") and s.get("fiyat_elle"):
                from fiyat_kaynagi_ui import birim_degisiminde_yeniden_fiyat

                yeni_fiyat = birim_degisiminde_yeniden_fiyat(self, {"fiyat_elle": True})
                if yeni_fiyat is None:
                    return
            yeni["birim"] = birim
            if not s.get("is_manual_item") and yeni_fiyat:
                fiyat = self._cari_fiyati(s.get("urun_kodu") or "", birim)
                if fiyat is not None:
                    from database.fiyat_kaynagi_service import satis_kdv_haric

                    fiyat, _not = satis_kdv_haric(s.get("urun_kodu") or "", fiyat, s.get("kdv_orani"),
                                                  musteri=self.cari)
                    yeni["birim_fiyat"] = fiyat
                    yeni["fiyat_elle"] = False
        elif kolon == "fiyat":
            yeni["birim_fiyat"] = decimal(metin or 0, "Birim fiyat", Decimal("0"))
            if yeni["birim_fiyat"] != decimal(s.get("birim_fiyat") or 0, "Birim fiyat", Decimal("0")):
                yeni["fiyat_elle"] = True
        elif kolon == "iskonto":
            yeni["iskonto_orani"], yeni["iskonto_orani_2"], yeni["iskonto_orani_3"] = iskonto_metni_coz(metin)
        elif kolon == "kdv":
            yeni["kdv_orani"] = decimal((metin or "0").replace("%", ""), "KDV oranı", Decimal("0"))
        elif kolon == "termin":
            yeni["termin"] = _tarih_coz(metin, "Satır termini", zorunlu=False)
        elif kolon == "aciklama":
            yeni["aciklama"] = metin
        else:
            return
        self.satirlar[idx] = yeni
        self.satir_listesini_yenile()

    def _secili_index(self) -> int | None:
        from satir_ici_urun_giris import satir_indeksi

        secim = self.satir_tablosu.selection()
        return satir_indeksi(self.satir_tablosu, secim[0]) if secim else None

    def satir_cogalt(self):
        if not self._duzenlenebilir():
            return "break"
        idx = self._secili_index()
        if idx is None:
            messagebox.showinfo("Satır", "Çoğaltılacak satırı seçin.", parent=self)
            return "break"
        kopya = {
            k: v for k, v in self.satirlar[idx].items()
            if k not in ("id", "irsaliyelenen", "faturalanan")
        }
        self.satirlar.insert(idx + 1, kopya)
        self.satir_listesini_yenile()
        self._hucre.duzenle(idx + 1, "miktar")
        return "break"

    def araya_satir_ekle(self):
        if not self._duzenlenebilir():
            return "break"
        idx = self._secili_index()
        if idx is None:
            self._satir_ici_giris.odakla()
        else:
            self._satir_ici_giris.araya_ekle(idx)
        return "break"

    def _satir_menusu(self, idx: int) -> list:
        ogeler = [
            ("Satırı Düzenle (F2)", lambda: self._hucre.ilk_alana(idx)),
            ("Satırı Çoğalt", self.satir_cogalt),
            ("Araya Satır Ekle", lambda: self._satir_ici_giris.araya_ekle(idx)),
            ("Satırı Sil (Del)", self.satir_kaldir),
        ]
        s = self.satirlar[idx] if 0 <= idx < len(self.satirlar) else {}
        if s and not s.get("is_manual_item"):
            ogeler.insert(1, ("Fiyat Listesinden Seç…", lambda: self.fiyat_secimi_ac(idx=idx)))
            if not self._satir_bagli_mi(s):
                ogeler.insert(1, ("Ürünü Değiştir…", lambda: self._satir_ici_giris.urun_degistir_baslat(idx)))
                ogeler.insert(2, ("Fiyatı Yenile", lambda: self.fiyati_yenile(idx)))
        return ogeler

    def fiyati_yenile(self, idx: int) -> None:
        """Seçili satırın fiyatını cari fiyat listesinden yeniden getirir (elle fiyatta onay ister)."""
        from fiyat_kaynagi_ui import fiyat_yok_bildir, yenileme_onayi
        from database.fiyat_kaynagi_service import satis_kdv_haric

        if not self._duzenlenebilir() or not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        if s.get("is_manual_item") or self._satir_bagli_mi(s) or not yenileme_onayi(self, s):
            return
        kod = s.get("urun_kodu") or ""
        fiyat = self._cari_fiyati(kod, s.get("birim") or "Adet")
        if fiyat is None:
            self._fiyat_yok_bildirilen = set()
            fiyat_yok_bildir(self, kod, f"{kod}: fiyat listesinde geçerli satış fiyatı yok.")
            return
        fiyat, _not = satis_kdv_haric(kod, fiyat, s.get("kdv_orani"), musteri=self.cari)
        yeni = dict(s)
        yeni["birim_fiyat"] = fiyat
        yeni["fiyat_elle"] = False
        self.satirlar[idx] = yeni
        self.satir_listesini_yenile()

    def fiyat_secimi_ac(self, _event=None, idx: int | None = None):
        from app import PriceSelectionDialog

        if idx is None:
            idx = self._secili_index()
        if idx is None or not (0 <= idx < len(self.satirlar)) or self.satirlar[idx].get("is_manual_item"):
            messagebox.showinfo("Fiyat", "Önce stoktan ürün satırı seçin.", parent=self)
            return "break"
        kod = self.satirlar[idx].get("urun_kodu") or ""

        def _secildi(fiyat):
            deger = self._tl_fiyati_belge_parasina(fiyat.tutar)
            if deger is not None:
                self.satir_hucre_uygula(idx, "fiyat", _sayi(deger))

        dialog = PriceSelectionDialog(
            self, kod, on_select=_secildi, fiyat_turu="satis",
            kdv_orani=lambda: self.satirlar[idx].get("kdv_orani"),
        )
        self.wait_window(dialog)
        return "break"

    # ---------------------------------------------------------------- satırlar
    def _stok_satiri_hazirla(self, veri: dict[str, Any]) -> bool:
        """Stok kartını doğrular; ürün kimliği ve şirket içi maliyetleri (kâr analizi) ekler."""
        try:
            kart = self._stok_karti(veri["urun_kodu"])
        except Exception:
            return True
        if kart is None:
            messagebox.showwarning(
                "Ürün bulunamadı",
                f"«{veri['urun_kodu']}» kodlu stok kartı bulunamadı.\n"
                "Ürünü listeden seçin veya stokta olmayan ürün için «Manuel kalem» kullanın.",
                parent=self,
            )
            return False
        veri["product_id"] = getattr(kart, "id", None)
        try:
            from database.stok_service import StokService

            maliyetler = StokService.maliyetler(veri["urun_kodu"], self.depo.get() or "ANA DEPO")
            for alan, anahtar in zip(MALIYET_ALANLARI, ("fifo", "son_alis", "ortalama", "agirlikli")):
                veri[alan] = maliyetler.get(anahtar, 0)
        except Exception:
            pass
        return True

    def _satir_bagli_metni(self, satir: dict[str, Any]) -> str:
        if self.siparis is None or not satir.get("id"):
            return "-"
        try:
            return SatisSiparisiService.bagli_evrak_metni(self.siparis.id, [satir["id"]])
        except Exception:
            return "-"

    def satir_temizle(self):
        """Açık hücre / giriş editörlerini kapatır (satırlar korunur)."""
        self._hucre.kapat()
        self._satir_ici_giris.kapat()
        try:
            self.satir_tablosu.selection_remove(self.satir_tablosu.selection())
        except tk.TclError:
            pass
        self.toplam_guncelle()

    def satir_listesini_yenile(self):
        pb = self.para_birimi.get() or "TRY"
        self.satir_tablosu.delete(*self.satir_tablosu.get_children())
        for index, veri in enumerate(self.satirlar):
            miktar = decimal(veri.get("miktar") or 0, "Miktar")
            h = satir_hesapla(
                miktar, veri.get("birim_fiyat") or 0, veri.get("iskonto_orani") or 0,
                veri.get("iskonto_orani_2") or 0, veri.get("iskonto_orani_3") or 0, veri.get("kdv_orani") or 0,
            )
            sevk = decimal(veri.get("irsaliyelenen") or 0, "S")
            fat = decimal(veri.get("faturalanan") or 0, "F")
            etiketler = ["cift" if index % 2 else "tek"]
            if miktar > 0 and fat >= miktar:
                etiketler.append("tamam")
            ad = veri.get("urun_adi", "")
            if veri.get("is_manual_item"):
                ad = f"{ad}  [stokta yok]"
            self.satir_tablosu.insert(
                "", "end", iid=str(index), tags=tuple(etiketler),
                values=(
                    index + 1, veri.get("urun_kodu", ""), ad, _sayi(miktar), veri.get("birim") or "Adet",
                    para_metni(veri.get("birim_fiyat") or 0, pb), _iskonto_metni(veri), f"{_sayi(veri.get('kdv_orani') or 0)}%",
                    para_metni(h["net"], pb), para_metni(h["toplam"], pb), _tarih(veri.get("termin")),
                    _sayi(sevk), _sayi(fat), _sayi(miktar - sevk), _sayi(miktar - fat), veri.get("aciklama") or "",
                ),
            )
        self._satir_ici_giris.tabloya_ekle()
        self.toplam_guncelle()
        self.after_idle(self._siparis_excel_cizgileri_yenile)

    def toplam_guncelle(self):
        """Satır + uzlaşılan indirim/masraf → fatura ile aynı alt toplamlar."""
        from database.fatura_genel_toplam_service import kurus

        satirlar = [dict(s) for s in self.satirlar]
        pb = self.para_birimi.get() or "TRY"
        t = belge_toplamlari(satirlar)
        satir_brut = kurus(t["genel_toplam"])
        brut_ref = self._uzlasilan_brut_referans(satir_brut)
        try:
            fark = self._uzlasilan_indirim_masraf(brut_ref)
        except ValueError as hata:
            messagebox.showerror("Uzlaşılan tutar", str(hata), parent=self)
            fark = {
                "brut": brut_ref,
                "indirim_tutari": Decimal("0"),
                "indirim_orani": Decimal("0"),
                "masraf_tutari": Decimal("0"),
                "masraf_orani": Decimal("0"),
                "net": brut_ref,
                "islem_turu": "",
                "islem_tutari": Decimal("0"),
                "islem_orani": Decimal("0"),
            }
        net_toplam = kurus(fark["net"])
        self._hesaplanan_genel = net_toplam
        self._genel_islem_turu = fark.get("islem_turu") or ""
        self._genel_islem_orani = fark.get("islem_orani") or Decimal("0")
        self._genel_islem_tutari = fark.get("islem_tutari") or Decimal("0")
        indirim_tutari = fark.get("indirim_tutari") or Decimal("0")
        indirim_orani = fark.get("indirim_orani") or Decimal("0")
        masraf_tutari = fark.get("masraf_tutari") or Decimal("0")
        masraf_orani = fark.get("masraf_orani") or Decimal("0")
        brut_goster = kurus(fark.get("brut") or brut_ref)

        refs = getattr(self, "_siparis_ozet_refs", None) or {}
        degerler = refs.get("degerler") or getattr(self, "siparis_toplam_degerleri", {}) or {}

        def _yaz(anahtar, metin):
            w = degerler.get(anahtar)
            if w is None:
                return
            try:
                w.configure(text=metin)
            except tk.TclError:
                pass

        _yaz("ara_toplam", para_metni(t["ara_toplam"], pb))
        _yaz("iskonto", para_metni(t["iskonto"], pb))
        _yaz("matrah", para_metni(t["net"], pb))
        _yaz("kdv", para_metni(t["kdv"], pb))
        _yaz("brut", para_metni(brut_goster, pb))
        _yaz("indirim", para_metni(indirim_tutari, pb))
        _yaz("masraf", para_metni(masraf_tutari, pb))
        _yaz("genel", para_metni(net_toplam, pb))
        oran_w = degerler.get("indirim_oran")
        if oran_w is not None:
            try:
                oran_w.configure(text=f"%{float(indirim_orani):.2f}".replace(".", ","))
            except tk.TclError:
                pass
        oran_m = degerler.get("masraf_oran")
        if oran_m is not None:
            try:
                oran_m.configure(text=f"%{float(masraf_orani):.2f}".replace(".", ","))
            except tk.TclError:
                pass
        # Döviz karşılığı
        doviz_w = degerler.get("doviz")
        if doviz_w is not None:
            try:
                if (pb or "TRY").upper() not in ("TRY", "TL"):
                    kur = self._kur_degeri()
                    if kur > 0:
                        tl = (net_toplam * kur).quantize(Decimal("0.01"))
                        doviz_w.configure(text=para_metni(tl, "TRY"))
                    else:
                        doviz_w.configure(text="—")
                else:
                    doviz_w.configure(text="—")
            except tk.TclError:
                pass

        kalem_w = refs.get("kalem_lbl")
        if kalem_w is not None:
            try:
                kalem_w.configure(text=f"Kalem: {len(satirlar)}")
            except tk.TclError:
                pass
        miktar_w = refs.get("miktar_lbl")
        if miktar_w is not None:
            try:
                miktar_w.configure(text=f"Miktar: {toplam_miktar_ozeti(satirlar)}")
            except tk.TclError:
                pass

        self._hesap_ozeti_yenile(net_toplam)
        t = dict(t)
        t["genel_toplam"] = net_toplam
        t["brut_goster"] = brut_goster
        t["indirim"] = indirim_tutari
        t["masraf"] = masraf_tutari
        return t

    def satir_duzenle(self):
        if not self._duzenlenebilir():
            return "break"
        idx = self._secili_index()
        if idx is None:
            messagebox.showinfo("Satır", "Düzenlenecek satırı seçin.", parent=self)
            return "break"
        self._hucre.ilk_alana(idx)
        return "break"

    def satir_kaldir(self):
        if not self._duzenlenebilir():
            return "break"
        idx = self._secili_index()
        if idx is None:
            messagebox.showinfo("Satır", "Silinecek satırı seçin.", parent=self)
            return "break"
        veri = self.satirlar[idx]
        sevk = decimal(veri.get("irsaliyelenen") or 0, "S")
        fat = decimal(veri.get("faturalanan") or 0, "F")
        if sevk > 0 or fat > 0:
            messagebox.showwarning(
                "Satır silinemez",
                f"«{veri.get('urun_adi')}» satırı sevk ({_sayi(sevk)}) veya fatura ({_sayi(fat)}) edilmiş; silinemez.\n"
                f"Bağlı evrak: {self._satir_bagli_metni(veri)}\n"
                "Önce bağlı evraktaki satırı silin veya evrakı iptal edin.",
                parent=self,
            )
            return "break"
        from satir_ici_urun_giris import satir_editorlerini_kapat, satir_silme_sonrasi_temizle

        satir_editorlerini_kapat(self)
        if messagebox.askyesno("Satırı sil", f"«{veri.get('urun_adi')}» satırı silinsin mi?", parent=self):
            self.satirlar.pop(idx)
            self.satir_temizle()
            self.satir_listesini_yenile()
            satir_silme_sonrasi_temizle(self, self.satir_tablosu)
        return "break"

    # --------------------------------------------------------------- kayıt
    def _veri_topla(self) -> tuple[dict, list]:
        def g(alan):
            return self._alan_metin(alan)

        tarih = _tarih_coz(g("siparis_tarihi"), "Sipariş tarihi")
        if tarih > date.today():
            raise ValueError("Sipariş tarihi gelecek bir tarih olamaz.")
        termin = _tarih_coz(g("termin_tarihi"), "Termin tarihi")
        if termin < tarih:
            raise ValueError("Teslim tarihi sipariş tarihinden önce olamaz.")
        if self.cari is None:
            raise ValueError("Müşteri seçin (müşteri adını yazıp Enter, F10 veya «Ara»).")
        beklenen_ad = (self.cari.unvan or "").strip()
        beklenen_kod = (self.cari.cari_kodu or "").strip()
        if self._musteri_var.get().strip() != beklenen_ad or self.musteri_kodu.get().strip() != beklenen_kod:
            raise ValueError("Müşteri alanı değiştirildi; Enter ile müşteriyi seçin veya F10 ile arayın.")
        if not (self.depo.get() or "").strip():
            raise ValueError("Depo seçin.")
        try:
            siparis_saati = saat_dogrula(g("siparis_saati"))
        except ValueError as hata:
            raise ValueError(str(hata).replace("İşlem saati", "Sipariş saati")) from hata
        # Kaydetmeden önce Teslim Saati'ni HH:mm'ye çevir (alanı da güncelle)
        ts_w = self.girdiler.get("teslim_saati")
        if ts_w is not None:
            try:
                teslim_saati = saat_kisa_giris_coz(
                    ts_w.get(), bos_izinli=True, alan_adi="Teslim saati"
                )
            except ValueError as hata:
                raise ValueError(str(hata)) from hata
            try:
                ts_w.delete(0, "end")
                if teslim_saati:
                    ts_w.insert(0, teslim_saati)
            except tk.TclError:
                pass
        else:
            teslim_saati = _saat_opsiyonel(g("teslim_saati"))
        if not self._hucre.bekleyeni_uygula():
            raise ValueError("Düzenlenen hücredeki değer geçersiz; düzeltin veya Esc ile vazgeçin.")
        self._satir_ici_giris.bekleyeni_uygula()
        if not self.satirlar:
            raise ValueError("En az bir ürün satırı ekleyin.")
        pb = self.para_birimi.get() or "TRY"
        kur = self._kur_degeri()
        if pb != "TRY" and kur <= 0:
            raise ValueError(f"{pb} sipariş için geçerli bir kur girin.")
        # Footer not → açıklama (senkron)
        refs = getattr(self, "_siparis_ozet_refs", None) or {}
        not_w = refs.get("not_alani")
        if not_w is not None:
            try:
                self.aciklama.delete("1.0", "end")
                self.aciklama.insert("1.0", not_w.get("1.0", "end-1c"))
            except tk.TclError:
                pass
        self.toplam_guncelle()
        veriler = {
            "siparis_tarihi": tarih,
            "termin_tarihi": termin,
            "siparis_saati": siparis_saati,
            "teslim_saati": teslim_saati,
            "teslim_sekli": g("teslim_sekli") or None,
            "cari_id": int(self.cari.id),
            "depo": self.depo.get().strip(),
            "para_birimi": pb,
            "kur": kur,
            "aciklama": self.aciklama.get("1.0", "end").strip(),
            "genel_toplam": getattr(self, "_hesaplanan_genel", 0) or 0,
            "genel_islem_turu": getattr(self, "_genel_islem_turu", "") or None,
            "genel_islem_orani": getattr(self, "_genel_islem_orani", 0) or 0,
            "genel_islem_tutari": getattr(self, "_genel_islem_tutari", 0) or 0,
        }
        for alan in ("teslimat_adresi", "teslimat_il", "teslimat_ilce", "musteri_siparis_no", "teslim_kosulu", "odeme_kosulu"):
            veriler[alan] = g(alan)
        if self.siparis is None:
            ozel = g("siparis_no")
            if ozel and ozel != YENI_NO_METNI:
                veriler["siparis_no"] = ozel
        satirlar = []
        for s in self.satirlar:
            veri = {
                "id": s.get("id"),
                "urun_kodu": s.get("urun_kodu"),
                "urun_adi": s.get("urun_adi"),
                "aciklama": s.get("aciklama") or "",
                "miktar": s.get("miktar"),
                "birim": s.get("birim") or "Adet",
                "birim_satis_fiyati": s.get("birim_fiyat") or 0,
                "iskonto_orani": s.get("iskonto_orani") or 0,
                "iskonto_orani_2": s.get("iskonto_orani_2") or 0,
                "iskonto_orani_3": s.get("iskonto_orani_3") or 0,
                "kdv_orani": s.get("kdv_orani") if s.get("kdv_orani") not in (None, "") else 20,
                "is_manual_item": bool(s.get("is_manual_item")),
                "line_type": "MANUAL_PRODUCT" if s.get("is_manual_item") else "STOCK_PRODUCT",
                "product_id": s.get("product_id"),
                "estimated_delivery_date": s.get("termin"),
                "delivery_term_days": s.get("delivery_term_days"),
                "delivery_term_note": s.get("delivery_term_note"),
                "stock_pending": s.get("stock_pending", bool(s.get("is_manual_item"))),
            }
            for alan in MALIYET_ALANLARI:
                veri[alan] = s.get(alan) or 0
            satirlar.append(veri)
        return veriler, satirlar

    def kaydet(self, sessiz: bool = False, onayla: bool = False) -> bool:
        if self._kaydediliyor:
            return False
        if not self._duzenlenebilir():
            messagebox.showinfo("Kaydet", "İptal edilmiş sipariş değiştirilemez.", parent=self)
            return False
        try:
            veriler, satirlar = self._veri_topla()
        except ValueError as hata:
            messagebox.showwarning("Eksik / hatalı bilgi", str(hata), parent=self)
            return False
        veriler["onayla"] = bool(onayla)
        self._kaydediliyor = True
        for anahtar in ("kaydet", "onayla"):
            try:
                self.btn[anahtar].configure(state="disabled")
            except tk.TclError:
                pass
        try:
            kayit = SatisSiparisiService.kaydet(veriler, satirlar, None, getattr(self.siparis, "id", None))
        except ValueError as hata:
            birim_hatasi_goster(self, hata) or messagebox.showerror("Sipariş kaydedilemedi", str(hata), parent=self)
            self._kilit_uygula()
            return False
        except Exception as hata:  # noqa: BLE001
            from uygulama_log import hata_yaz

            yol = hata_yaz("Satış siparişi kaydedilemedi", hata)
            messagebox.showerror(
                "Sipariş kaydedilemedi",
                f"Beklenmeyen hata; kayıt yapılmadı.\n{hata}" + (f"\n\nAyrıntı: {yol}" if yol else ""),
                parent=self,
            )
            self._kilit_uygula()
            return False
        finally:
            self._kaydediliyor = False
        self.result = True
        birim_uyarisi = getattr(kayit, "birim_uyarisi", None)
        self._kayit_yukle(SatisSiparisiService.getir(kayit.id) or kayit)
        if birim_uyarisi:
            messagebox.showwarning(
                "Tanımsız birim", "Sipariş TASLAK olarak kaydedildi; onay ve aktarım bu birimler tanımlanana "
                f"kadar engellenecek.\n\n{birim_uyarisi}", parent=self)
        if not sessiz:
            ek = "Sipariş onaylandı; irsaliye ve faturaya aktarılabilir." if onayla else "Durum: " + self._durum()
            messagebox.showinfo("Kaydedildi", f"{self.siparis.siparis_no} kaydedildi.\n{ek}\nStok veya cari hareketi oluşturulmadı.", parent=self)
        return True

    def kaydet_ve_onayla(self):
        if self.siparis is not None and not self.degisiklik_var() and self._durum() == "TASLAK":
            try:
                SatisSiparisiService.onayla(self.siparis.id)
            except ValueError as hata:
                birim_hatasi_goster(self, hata) or messagebox.showerror("Onay", str(hata), parent=self)
                return False
            self.result = True
            self._yenile()
            messagebox.showinfo("Onay", f"{self.siparis.siparis_no} onaylandı.", parent=self)
            return True
        return self.kaydet(onayla=True)

    def onay_kaldir(self):
        if self.siparis is None:
            return
        if not messagebox.askyesno("Onayı kaldır", f"{self.siparis.siparis_no} TASLAK durumuna alınsın mı?", parent=self):
            return
        try:
            SatisSiparisiService.onay_kaldir(self.siparis.id)
        except ValueError as hata:
            messagebox.showerror("Onay kaldırılamadı", str(hata), parent=self)
            return
        self.result = True
        self._yenile()

    def _kayit_yukle(self, sp):
        """Kayıtlı siparişi forma yükler; satır kimlikleri korunur."""
        self.siparis = sp
        self._durum_var.set(sp.durum or "TASLAK")
        self._kilitsiz_ac()
        for alan, deger in (
            ("siparis_no", sp.siparis_no or ""),
            ("siparis_tarihi", _tarih(sp.siparis_tarihi)),
            ("termin_tarihi", _tarih(sp.termin_tarihi)),
            ("musteri_siparis_no", getattr(sp, "musteri_siparis_no", None) or ""),
            ("teslimat_il", getattr(sp, "teslimat_il", None) or ""),
            ("teslimat_ilce", getattr(sp, "teslimat_ilce", None) or ""),
            ("teslim_kosulu", getattr(sp, "teslim_kosulu", None) or ""),
            ("odeme_kosulu", getattr(sp, "odeme_kosulu", None) or ""),
        ):
            w = self.girdiler[alan]
            w.delete(0, "end")
            w.insert(0, deger)
        # Sipariş saati: kayıtlı değer; yoksa boş bırakma (yeni belge varsayılanı değil)
        saat_w = self.girdiler.get("siparis_saati")
        if saat_w is not None:
            saat_w.delete(0, "end")
            kayitli_saat = getattr(sp, "siparis_saati", None)
            if kayitli_saat:
                saat_w.insert(0, saat_varsayilan(kayitli_saat))
        ts_w = self.girdiler.get("teslim_saati")
        if ts_w is not None:
            ts_w.delete(0, "end")
            kayitli_ts = getattr(sp, "teslim_saati", None)
            if kayitli_ts is not None and str(kayitli_ts).strip() != "":
                try:
                    bicimli = saat_kisa_giris_coz(
                        str(kayitli_ts), bos_izinli=True, alan_adi="Teslim saati"
                    )
                except ValueError:
                    bicimli = str(kayitli_ts).strip()
                if bicimli:
                    ts_w.insert(0, bicimli)
        sekil = (getattr(sp, "teslim_sekli", None) or "").strip()
        if sekil in TESLIM_SEKLI_SECENEKLERI:
            self.teslim_sekli.set(sekil)
        else:
            self.teslim_sekli.set("")
            # Eski serbest teslim_kosulu tahminen eşlenmez; olduğu gibi Diğer Bilgiler'de kalır
        depo = getattr(sp, "depo", None) or (self.depolar[0] if self.depolar else "ANA DEPO")
        if depo not in self.depolar:
            self.depolar.append(depo)
            self.depo.configure(values=self.depolar)
        self.depo.set(depo)
        pb = (getattr(sp, "para_birimi", None) or "TRY").upper()
        if pb not in self.para_birimleri:
            self.para_birimleri.append(pb)
            self.para_birimi.configure(values=self.para_birimleri)
        self.para_birimi.set(pb)
        kur = self.girdiler["kur"]
        kur.delete(0, "end")
        kur.insert(0, _sayi(getattr(sp, "kur", None) or 1))
        kayitli_adres = getattr(sp, "teslimat_adresi", None) or ""
        kayitli_il = getattr(sp, "teslimat_il", None) or ""
        kayitli_ilce = getattr(sp, "teslimat_ilce", None) or ""
        if sp.cari is not None:
            self.cari = None
            self._musteri_ata(sp.cari)
            self._siparis_adreslerini_yukle(
                sp.cari,
                kayitli_adres=kayitli_adres,
                kayitli_il=kayitli_il,
                kayitli_ilce=kayitli_ilce,
            )
        else:
            self._siparis_adres_yaz(kayitli_adres, kayitli_il, kayitli_ilce)
        self.aciklama.delete("1.0", "end")
        self.aciklama.insert("1.0", sp.aciklama or "")
        refs = getattr(self, "_siparis_ozet_refs", None) or {}
        not_w = refs.get("not_alani")
        if not_w is not None:
            try:
                not_w.delete("1.0", "end")
                not_w.insert("1.0", sp.aciklama or "")
            except tk.TclError:
                pass
        self._avans = sum((decimal(t.tutar or 0, "Avans") for t in (sp.tahsilatlar or [])), Decimal("0"))
        av = self.girdiler["avans"]
        av.configure(state="normal")
        av.delete(0, "end")
        av.insert(0, para_metni(self._avans, pb) if self._avans else "—")
        av.configure(state="readonly")
        self.satirlar = []
        for s in sorted(sp.satirlar, key=lambda x: int(x.id or 0)):
            veri = {
                "id": s.id,
                "urun_kodu": s.urun_kodu,
                "urun_adi": s.urun_adi,
                "aciklama": s.aciklama or "",
                "miktar": decimal(s.miktar or 0, "Miktar"),
                "birim": s.birim,
                "birim_fiyat": decimal(s.birim_satis_fiyati or 0, "Fiyat"),
                "birim_satis_fiyati": decimal(s.birim_satis_fiyati or 0, "Fiyat"),
                "iskonto_orani": s.iskonto_orani or 0,
                "iskonto_orani_2": getattr(s, "iskonto_orani_2", 0) or 0,
                "iskonto_orani_3": getattr(s, "iskonto_orani_3", 0) or 0,
                "kdv_orani": s.kdv_orani if s.kdv_orani is not None else 20,
                "termin": getattr(s, "estimated_delivery_date", None),
                "is_manual_item": bool(getattr(s, "is_manual_item", False)),
                "product_id": getattr(s, "product_id", None),
                "stock_pending": bool(getattr(s, "stock_pending", False)),
                "delivery_term_days": getattr(s, "delivery_term_days", None),
                "delivery_term_note": getattr(s, "delivery_term_note", None),
                "irsaliyelenen": decimal(s.irsaliyelenen_miktar or 0, "S"),
                "faturalanan": decimal(s.faturalanan_miktar or 0, "F"),
            }
            for alan in MALIYET_ALANLARI:
                veri[alan] = getattr(s, alan, 0) or 0
            self.satirlar.append(veri)
        # Uzlaşılan / genel işlem — kayıtlı Net (stok listesine göre yeniden fiyatlanmaz)
        from database.fatura_genel_toplam_service import kurus

        self._uzlasilan_fiyat_snapshot = None
        self._uzlasilan_snapshot_brut = None
        satir_brut = kurus(
            sum((self._uzlasilan_satir_genel(v) for v in self.satirlar), Decimal("0"))
        )
        tur = (getattr(sp, "genel_islem_turu", None) or "").strip().upper()
        islem_t = kurus(getattr(sp, "genel_islem_tutari", 0) or 0)
        kayitli_genel = getattr(sp, "genel_toplam", None)
        self._genel_islem_turu = tur
        self._genel_islem_orani = Decimal(str(getattr(sp, "genel_islem_orani", 0) or 0))
        self._genel_islem_tutari = islem_t
        if kayitli_genel is not None and Decimal(str(kayitli_genel or 0)) != 0:
            net = kurus(kayitli_genel)
            self._hesaplanan_genel = net
            self._uzlasilan_tutar = net
            if tur == "INDIRIM" and islem_t > 0:
                brut_ref = kurus(net + islem_t)
            elif tur == "MASRAF" and islem_t > 0:
                brut_ref = kurus(net - islem_t)
            else:
                brut_ref = satir_brut
            if brut_ref != net:
                self._uzlasilan_snapshot_brut = brut_ref
        elif tur and islem_t > 0:
            # Eski kayıt: genel_toplam yok — satır brütü + işlem
            if tur == "INDIRIM":
                net = kurus(satir_brut - islem_t)
                self._uzlasilan_snapshot_brut = satir_brut
            else:
                net = kurus(satir_brut + islem_t)
                self._uzlasilan_snapshot_brut = satir_brut
            self._uzlasilan_tutar = net
            self._hesaplanan_genel = net
        else:
            self._uzlasilan_tutar = None
        self._uzlasilan_ui_kilit = True
        try:
            self._uzlasilan_tutar_yaz(self._uzlasilan_tutar)
        finally:
            self._uzlasilan_ui_kilit = False
        self.satir_temizle()
        self.satir_listesini_yenile()
        self._kayit_imzasi = self._imza()
        self._kilit_uygula()

    def _kilitsiz_ac(self):
        for alan, w in self.girdiler.items():
            if alan in ("bakiye", "avans"):
                continue
            if isinstance(w, tk.Text):
                w.configure(state="normal")
                continue
            try:
                w.configure(state="normal")
            except tk.TclError:
                pass
        self.aciklama.configure(state="normal")
        self.musteri.configure(state="normal")
        try:
            self.musteri_kodu.configure(state="normal")
        except tk.TclError:
            pass

    def siparis_listesini_ac(self):
        """Kart içinden alınan sipariş listesi; seçilen kayıt bu karta yüklenir."""
        if not self._kaydetmeyi_sor("Listeye geçmeden"):
            return
        dlg = tk.Toplevel(self)
        dlg.title("Sipariş Listesi")
        dlg.geometry("900x420")
        dlg.transient(self)
        dlg.grab_set()
        stil_uygula(root=dlg)
        ust = ttk.Frame(dlg, padding=8)
        ust.pack(fill="x")
        ttk.Label(ust, text="Ara:").pack(side="left")
        ara = ttk.Entry(ust, width=28)
        ara.pack(side="left", padx=4)
        tablo_f = ttk.Frame(dlg, padding=(8, 0, 8, 8))
        tablo_f.pack(fill="both", expand=True)
        kolonlar = ("no", "tarih", "musteri", "durum", "toplam")
        tablo = ttk.Treeview(tablo_f, columns=kolonlar, show="headings", selectmode="browse")
        for k, b, g in (
            ("no", "Sipariş No", 120),
            ("tarih", "Tarih", 90),
            ("musteri", "Müşteri", 280),
            ("durum", "Durum", 120),
            ("toplam", "Toplam", 100),
        ):
            tablo.heading(k, text=b)
            tablo.column(k, width=g, anchor="e" if k == "toplam" else "w")
        sy = ttk.Scrollbar(tablo_f, orient="vertical", command=tablo.yview)
        tablo.configure(yscrollcommand=sy.set)
        tablo.pack(side="left", fill="both", expand=True)
        sy.pack(side="right", fill="y")
        iid_map: dict[str, int] = {}

        def yenile(_e=None):
            for iid in tablo.get_children():
                tablo.delete(iid)
            iid_map.clear()
            q = (ara.get() or "").strip().casefold()
            try:
                kayitlar = SatisSiparisiService.listele() or []
            except Exception:
                kayitlar = []
            for k in kayitlar:
                sp = k.get("siparis")
                if sp is None:
                    continue
                cari = k.get("musteri")
                no = str(getattr(sp, "siparis_no", "") or "")
                musteri = ""
                if cari is not None:
                    musteri = f"{getattr(cari, 'cari_kodu', '') or ''} {getattr(cari, 'unvan', '') or ''}".strip()
                if q and q not in no.casefold() and q not in musteri.casefold():
                    continue
                iid = tablo.insert(
                    "",
                    "end",
                    values=(
                        no,
                        _tarih(getattr(sp, "siparis_tarihi", None)),
                        musteri,
                        getattr(sp, "durum", "") or "",
                        para_metni(k.get("toplam")),
                    ),
                )
                if getattr(sp, "id", None) is not None:
                    iid_map[iid] = int(sp.id)

        def ac(_e=None):
            sec = tablo.selection()
            if not sec:
                messagebox.showinfo("Sipariş", "Listeden bir sipariş seçin.", parent=dlg)
                return
            sid = iid_map.get(sec[0])
            if not sid:
                return
            sp = SatisSiparisiService.getir(sid)
            if not sp:
                messagebox.showerror("Sipariş", "Sipariş bulunamadı.", parent=dlg)
                return
            dlg.destroy()
            self._kayit_yukle(sp)

        ara.bind("<KeyRelease>", yenile)
        tablo.bind("<Double-1>", ac)
        tablo.bind("<Return>", ac)
        alt = ttk.Frame(dlg, padding=8)
        alt.pack(fill="x")
        ttk.Button(alt, text="Vazgeç", command=dlg.destroy).pack(side="right", padx=4)
        ttk.Button(alt, text="Aç", command=ac).pack(side="right", padx=4)
        yenile()
        ara.focus_set()

    def yeni_belge(self):
        if not self._kaydetmeyi_sor("Yeni siparişe geçmeden"):
            return
        self.siparis = None
        self.cari = None
        self._musteri_etiket = ""
        self._musteri_var.set("")
        self._durum_var.set("TASLAK")
        self._avans = Decimal("0")
        self._kilitsiz_ac()
        for alan, w in self.girdiler.items():
            if alan in ("bakiye", "avans"):
                try:
                    w.configure(state="normal")
                except tk.TclError:
                    pass
            if isinstance(w, tk.Text):
                w.delete("1.0", "end")
            else:
                try:
                    w.delete(0, "end")
                except tk.TclError:
                    pass
        try:
            self.musteri_kodu.configure(state="normal")
            self.musteri_kodu.delete(0, "end")
            self.musteri_kodu.configure(state="readonly")
        except tk.TclError:
            pass
        self.adres_secimi.set("")
        self._siparis_adres_map = {}
        self.adres_secimi.configure(values=())
        self.girdiler["siparis_no"].insert(0, YENI_NO_METNI)
        bugun = date.today().strftime("%d.%m.%Y")
        self.girdiler["siparis_tarihi"].insert(0, bugun)
        self.girdiler["termin_tarihi"].insert(0, bugun)
        self.girdiler["siparis_saati"].insert(0, saat_varsayilan())
        # Teslim saati bilinmiyor → boş (00:00 yazılmaz)
        self.girdiler["teslim_saati"].delete(0, "end")
        self.teslim_sekli.set("")
        self.girdiler["kur"].insert(0, "1")
        self.depo.set(self.depolar[0] if self.depolar else "ANA DEPO")
        self.para_birimi.set("TRY")
        self.aciklama.delete("1.0", "end")
        self.bakiye_guncelle()
        self.girdiler["avans"].configure(state="readonly")
        self.satirlar = []
        self.satir_temizle()
        self.satir_listesini_yenile()
        self._kayit_imzasi = self._imza()
        self._kilit_uygula()
        self._odak(self.musteri)

    # ---------------------------------------------------------- belge işlemleri
    def _kayitli_ve_guncel(self, islem: str) -> bool:
        if self.siparis is not None and not self.degisiklik_var():
            return True
        mesaj = "Sipariş henüz kaydedilmedi." if self.siparis is None else "Siparişte kaydedilmemiş değişiklikler var."
        if not messagebox.askyesno(islem, f"{mesaj}\n«{islem}» için önce kaydedilmesi gerekir. Kaydedilsin mi?", parent=self):
            return False
        return self.kaydet(sessiz=True)

    def _yenile(self):
        if self.siparis is not None:
            guncel = SatisSiparisiService.getir(self.siparis.id)
            if guncel is not None:
                self._kayit_yukle(guncel)

    def _aktarim_hazirla(self, islem: str):
        """Aktarım öncesi: kayıtlı, güncel, iptal değil; TASLAK ise onay istenir."""
        if not self._kayitli_ve_guncel(islem):
            return None
        sp = SatisSiparisiService.getir(self.siparis.id)
        if sp is None:
            messagebox.showerror(islem, "Sipariş bulunamadı.", parent=self)
            return None
        if (sp.durum or "") == "İPTAL":
            messagebox.showwarning(islem, "İptal edilmiş sipariş aktarılamaz.", parent=self)
            return None
        if (sp.durum or "") == "TASLAK":
            if not messagebox.askyesno(
                islem, f"{sp.siparis_no} onaylanmamış (TASLAK). Aktarım için onaylansın mı?", parent=self
            ):
                return None
            try:
                SatisSiparisiService.onayla(sp.id)
            except ValueError as hata:
                birim_hatasi_goster(self, hata) or messagebox.showerror(islem, str(hata), parent=self)
                return None
            self.result = True
            self._yenile()
            sp = SatisSiparisiService.getir(sp.id)
        return sp

    def irsaliyeye_aktar(self):
        sp = self._aktarim_hazirla("İrsaliyeye Aktar")
        if sp is None:
            return
        from database.kalan_belge_service import secimden_irsaliye_satirlari, siparis_secim_satirlari
        from kismi_belge_secim_ui import kismi_secim_yap

        adaylar = siparis_secim_satirlari(sp, hedef="irsaliye")
        if not adaylar:
            messagebox.showinfo("İrsaliyeye Aktar", "Bu siparişte sevk edilecek kalan miktar yok.", parent=self)
            return
        secim = kismi_secim_yap(
            self, adaylar, baslik="İrsaliyeye Aktar — sipariş satırları",
            aciklama=(
                f"{sp.siparis_no}: bu irsaliyeye alınacak miktarı girin (en fazla kalan sevk). 0 = satırı alma.\n"
                "İrsaliye kaydedilene kadar sipariş sevk edilmiş sayılmaz."
            ),
            onceki_baslik="Sevk edilen", kalan_baslik="Kalan sevk", bu_belge_baslik="Bu irsaliye",
            siparis_baslik="Sipariş miktarı",
        )
        if not secim:
            return
        try:
            satir_override = secimden_irsaliye_satirlari(secim)
        except ValueError as hata:
            messagebox.showerror("İrsaliyeye Aktar", str(hata), parent=self)
            return
        from satis_irsaliyesi_ui import SatisIrsaliyesiDialog

        dialog = SatisIrsaliyesiDialog(self, siparis=sp, satir_override=satir_override)
        self.wait_window(dialog)
        if getattr(dialog, "result", None):
            self.result = True
        self._yenile()

    def faturaya_aktar(self):
        sp = self._aktarim_hazirla("Faturaya Aktar")
        if sp is None:
            return
        from database.kalan_belge_service import secimden_fatura_satirlari, siparis_secim_satirlari
        from kismi_belge_secim_ui import kismi_secim_yap

        adaylar = siparis_secim_satirlari(sp, hedef="fatura")
        if not adaylar:
            messagebox.showinfo("Faturaya Aktar", "Bu siparişte faturalanacak kalan miktar yok.", parent=self)
            return
        secim = kismi_secim_yap(
            self, adaylar, baslik="Faturaya Aktar — sipariş satırları",
            aciklama=(
                f"{sp.siparis_no}: bu faturaya alınacak miktarı girin (en fazla kalan fatura). 0 = satırı alma.\n"
                "Fatura kaydedilene kadar sipariş faturalanmış sayılmaz."
            ),
            onceki_baslik="Faturalanan", kalan_baslik="Fatura kalanı", bu_belge_baslik="Bu fatura",
            siparis_baslik="Sipariş miktarı",
        )
        if not secim:
            return
        try:
            satir_override = secimden_fatura_satirlari(secim, kaynak="siparis")
        except ValueError as hata:
            messagebox.showerror("Faturaya Aktar", str(hata), parent=self)
            return
        from app import CariDialog, SatisFaturasiDialog
        from database.fatura_genel_toplam_service import kurus

        dialog = SatisFaturasiDialog(self, siparis=sp, satir_override=satir_override, cari_ac=lambda c: CariDialog(self, c))
        # Tam aktarım: dağıtılmamış belge indirim/masrafını bir kez taşı (kısmiye uygulama)
        try:
            acik = [
                s for s in (sp.satirlar or [])
                if decimal(s.miktar or 0, "M") > decimal(s.faturalanan_miktar or 0, "F")
            ]
            tam = len(satir_override) == len(acik)
            if tam and acik:
                for ov, src in zip(satir_override, acik):
                    kalan = decimal(src.miktar or 0, "M") - decimal(src.faturalanan_miktar or 0, "F")
                    if kurus(decimal(ov.get("miktar") or 0, "M")) < kurus(kalan):
                        tam = False
                        break
            if tam:
                satir_genel = kurus(sum(
                    (
                        satir_hesapla(
                            s.get("miktar") or 0,
                            s.get("birim_satis_fiyati") or s.get("birim_fiyat") or 0,
                            s.get("iskonto_orani") or 0,
                            s.get("iskonto_orani_2") or 0,
                            s.get("iskonto_orani_3") or 0,
                            s.get("kdv_orani") or 0,
                        )["toplam"]
                        for s in satir_override
                    ),
                    Decimal("0"),
                ))
                kayitli_net = kurus(getattr(sp, "genel_toplam", 0) or 0)
                islem_t = kurus(getattr(sp, "genel_islem_tutari", 0) or 0)
                tur = (getattr(sp, "genel_islem_turu", None) or "").strip().upper()
                if tur and islem_t > 0 and kayitli_net > 0 and satir_genel != kayitli_net:
                    dialog._genel_islem_turu = tur
                    dialog._genel_islem_orani = Decimal(str(getattr(sp, "genel_islem_orani", 0) or 0))
                    dialog._genel_islem_tutari = islem_t
                    dialog._uzlasilan_tutar = kayitli_net
                    dialog._uzlasilan_ui_kilit = True
                    try:
                        if hasattr(dialog, "_uzlasilan_tutar_yaz"):
                            dialog._uzlasilan_tutar_yaz(kayitli_net)
                    finally:
                        dialog._uzlasilan_ui_kilit = False
                    if hasattr(dialog, "_toplamlari_guncelle"):
                        dialog._toplamlari_guncelle()
        except Exception:
            pass
        self.wait_window(dialog)
        if getattr(dialog, "result", None):
            self.result = True
        self._yenile()

    def bagli_evraklari_goster(self):
        if self.siparis is None:
            return
        kayitlar = SatisSiparisiService.bagli_evraklar(self.siparis.id)
        if not kayitlar:
            messagebox.showinfo("Bağlı Evraklar", "Bu siparişe bağlı irsaliye veya fatura yok.", parent=self)
            return
        dialog = BagliEvrakDialog(self, self.siparis.siparis_no, kayitlar)
        self.wait_window(dialog)
        if dialog.degisti:
            self.result = True
        self._yenile()

    def iptal_et(self):
        if self.siparis is None:
            return
        aktif = [k for k in SatisSiparisiService.bagli_evraklar(self.siparis.id) if not k["iptal"]]
        ek = ""
        if aktif:
            ek = (
                "\n\nBağlı evraklar iptal edilmez ve geçerli kalır: "
                + ", ".join(f"{k['tur']} {k['no']}" for k in aktif)
                + "\nKalan miktarlar artık sevk/fatura beklemez."
            )
        if not messagebox.askyesno("Siparişi iptal et", f"{self.siparis.siparis_no} iptal edilsin mi?{ek}", parent=self):
            return
        sebep = simpledialog.askstring("İptal nedeni", "İptal nedenini yazın (zorunlu):", parent=self)
        if not (sebep or "").strip():
            messagebox.showwarning("İptal", "İptal nedeni girilmeden iptal yapılmaz.", parent=self)
            return
        try:
            SatisSiparisiService.iptal_et(self.siparis.id, sebep=sebep.strip())
        except ValueError as hata:
            messagebox.showerror("İptal edilemedi", str(hata), parent=self)
            return
        self.result = True
        self._yenile()

    def sil(self):
        if self.siparis is None:
            return
        no = self.siparis.siparis_no
        if not messagebox.askyesno(
            "Siparişi sil",
            f"{no} numaralı sipariş kalıcı olarak silinsin mi?\nSilinen sipariş «Silinen Kayıtlar» günlüğüne yazılır.",
            icon="warning", parent=self,
        ):
            return
        try:
            SatisSiparisiService.sil(self.siparis.id)
        except ValueError as hata:
            messagebox.showerror("Silinemedi", str(hata), parent=self)
            return
        self.result = True
        messagebox.showinfo("Silindi", f"{no} numaralı sipariş silindi.", parent=self)
        self._kayit_imzasi = None
        self.siparis = None
        self.satirlar = []
        self.destroy()

    # ------------------------------------------------------------- çıktılar
    def _cikti(self, islem: str):
        """Kayıtlı veriden çıktı; kaydedilmemiş değişiklik varsa önce kaydetme sorulur."""
        if not self._kayitli_ve_guncel("Çıktı"):
            return None
        from siparis_cikti_ui import cikti_al

        return cikti_al(self, self.siparis.id, islem)

    def onizleme(self):
        return self._cikti("onizleme")

    def yazdir(self):
        return self._cikti("yazdir")

    def pdf_kaydet(self):
        return self._cikti("pdf")

    def word_kaydet(self):
        return self._cikti("word")


class BagliEvrakDialog(tk.Toplevel):
    """Siparişe bağlı irsaliye/faturalar; çift tık ile evrak açılır."""

    def __init__(self, parent, siparis_no: str, kayitlar: list[dict[str, Any]]):
        super().__init__(parent)
        self.degisti = False
        self._kayitlar = {f"{k['tur']}:{k['id']}": k for k in kayitlar}
        self.title(f"{siparis_no} — bağlı evraklar")
        self.configure(bg=BEYAZ)
        self.geometry("720x320")
        self.transient(parent)
        tk.Label(
            self, text=f"{siparis_no} siparişine bağlı irsaliye ve faturalar", bg=LACIVERT, fg=BEYAZ,
            font=font(11, "bold", self), padx=12, pady=8, anchor="w",
        ).pack(fill="x")
        tk.Frame(self, bg=SARI, height=3).pack(fill="x")
        kolonlar = ("tur", "no", "tarih", "durum", "miktar")
        self.tablo = ttk.Treeview(self, columns=kolonlar, show="headings", height=8, selectmode="browse")
        treeview_stil(self.tablo)
        for col, baslik, gen in (
            ("tur", "Evrak", 90), ("no", "Evrak No", 170), ("tarih", "Tarih", 100), ("durum", "Durum", 180),
            ("miktar", "Siparişten Aktarılan Miktar", 170),
        ):
            self.tablo.heading(col, text=baslik)
            self.tablo.column(col, width=gen, anchor="e" if col == "miktar" else "w")
        self.tablo.tag_configure("iptal", foreground=KIRMIZI)
        for anahtar, k in self._kayitlar.items():
            self.tablo.insert(
                "", "end", iid=anahtar, tags=("iptal",) if k["iptal"] else (),
                values=(k["tur"], k["no"], _tarih(k["tarih"]), k["durum"], _sayi(k["miktar"])),
            )
        self.tablo.pack(fill="both", expand=True, padx=10, pady=8)
        self.tablo.bind("<Double-1>", lambda _e: self._ac())
        self.tablo.bind("<Return>", lambda _e: self._ac())
        alt = tk.Frame(self, bg=BEYAZ)
        alt.pack(fill="x", padx=10, pady=(0, 10))
        tk_buton(alt, "Evrakı Aç", self._ac, rol="kaydet").pack(side="right")
        tk_buton(alt, "Kapat", self.destroy, rol="geri").pack(side="right", padx=6)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()
        if self._kayitlar:
            ilk = next(iter(self._kayitlar))
            self.tablo.selection_set(ilk)
            self.tablo.focus(ilk)
        self.tablo.focus_set()

    def _ac(self):
        secim = self.tablo.selection()
        if not secim:
            return
        k = self._kayitlar[secim[0]]
        try:
            if k["tur"] == "İrsaliye":
                from database.satis_irsaliyesi_service import SatisIrsaliyesiService
                from satis_irsaliyesi_ui import SatisIrsaliyesiDialog

                belge = SatisIrsaliyesiService.getir(k["id"])
                if belge is None:
                    raise ValueError("İrsaliye bulunamadı; silinmiş olabilir.")
                dialog = SatisIrsaliyesiDialog(self, irsaliye=belge)
            else:
                from app import CariDialog, SatisFaturasiDialog
                from database.satis_faturasi_service import SatisFaturasiService

                belge = SatisFaturasiService.getir(k["id"])
                if belge is None:
                    raise ValueError("Fatura bulunamadı; silinmiş olabilir.")
                dialog = SatisFaturasiDialog(self, fatura=belge, cari_ac=lambda c: CariDialog(self, c))
        except ValueError as hata:
            messagebox.showerror("Evrak", str(hata), parent=self)
            return
        self.wait_window(dialog)
        self.degisti = True
