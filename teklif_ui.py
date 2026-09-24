"""Teklifler hub, liste ve kart UI — Ray Mobilya kurumsal tema."""

from __future__ import annotations

from pathlib import Path
import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable

from database.access import maliyet_izinli, yetki_var
from database.session_manager import oturum
from database.models.stok import KDV_ORANLARI, VARSAYILAN_KDV_ORANI
from database.stok_service import StokService
from database.teklif_conversion_service import QuoteConversionService
from database.teklif_pricing_service import (
    FIYAT_YONTEMLERI,
    MALIYET_KAYNAK_ETIKET,
    MALIYET_KAYNAKLARI,
    MASRAF_TURLERi,
    TERMIN_TURLERI,
    QuotePricingService,
    dagitimli_hesapla,
    maliyet_getir,
    tahmini_teslim_hesapla,
)
from database.teklif_odeme import (
    KREDI_KARTI,
    NAKIT,
    NAKIT_ALT,
    ODEME_SEKILLERI,
    VADELI_SEKILLER,
    kalem_hesapla,
    kalemleri_serileştir,
    kalemleri_yukle,
    kayittan_odeme,
    kk_taksit_etiket,
    kk_taksit_sayisi,
    kk_taksit_secenekleri,
    odeme_ozet_listeden,
    odeme_sekil_normalize,
)
from database.teklif_service import (
    RED_NEDENLERI,
    TEKLIF_DURUMLARI,
    QuoteService,
)
from database.user_audit import display_user, format_dt
from ui_takvim import takvim_butonu
from satis_tema import (
    ACIK_BG,
    HubKart,
    hub_ust_baslik,
    stil_uygula,
    tk_buton,
    treeview_stil,
)
from teklif_manuel_urun_ui import ManuelUrunDialog, manuel_birim_listesi
from teklif_urun_arama import TeklifUrunAramaPaneli
from urun_sec_ui import UrunSecDialog

LACIVERT = "#1B2A4A"
SARI = "#F5C518"
YESIL = "#2E7D32"
TURUNCU = "#E65100"
KIRMIZI = "#C62828"
BEYAZ = "#FFFFFF"
ACIK_GRI = "#F3F4F6"

TEKLIF_DURUM_RENK = {
    "TASLAK": ("#64748B", BEYAZ),
    "ONAY BEKLİYOR": (TURUNCU, BEYAZ),
    "İÇ ONAYLI": (YESIL, BEYAZ),
    "MÜŞTERİYE GÖNDERİLDİ": ("#1565C0", BEYAZ),
    "GÖRÜŞÜLÜYOR": ("#6A1B9A", BEYAZ),
    "REVİZE EDİLDİ": ("#00838F", BEYAZ),
    "KABUL EDİLDİ": (YESIL, BEYAZ),
    "KISMEN KABUL": ("#558B2F", BEYAZ),
    "REDDEDİLDİ": (KIRMIZI, BEYAZ),
    "SÜRESİ DOLDU": (TURUNCU, BEYAZ),
    "SİPARİŞE DÖNÜŞTÜ": (LACIVERT, BEYAZ),
    "İPTAL": (KIRMIZI, BEYAZ),
}

TEKLIF_HUB_KARTLARI = (
    ("TEKLİF LİSTESİ", "Tüm teklifleri görüntüleyin ve yönetin", "liste"),
    ("YENİ TEKLİF", "Müşteri teklifi oluşturun", "yeni"),
    ("SÜRESİ DOLAN TEKLİFLER", "Geçerliliği biten teklifler", "suresi_dolan"),
    ("TEKLİF RAPORLARI", "Kabul, ret ve dönüşüm özeti", "rapor"),
)


def _para(v) -> str:
    try:
        return f"{float(v or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00"


def _para_tl(v) -> str:
    return f"{_para(v)} TL"


def _tarih(d) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        return d.strftime("%d.%m.%Y")
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d)


def _parse_tarih(metin: str) -> date:
    return datetime.strptime(metin.strip(), "%d.%m.%Y").date()


def _decimal(metin, alan="Değer") -> Decimal:
    m = str(metin or "0").strip().replace(" ", "")
    if "," in m:
        m = m.replace(".", "").replace(",", ".")
    try:
        return Decimal(m or "0")
    except InvalidOperation as exc:
        raise ValueError(f"{alan} geçerli değil.") from exc


def teklifler_hub_goster(app) -> None:
    app._icerigi_temizle()
    stil_uygula(root=app)
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass
    kok = tk.Frame(app.icerik, bg=ACIK_BG)
    kok.pack(fill="both", expand=True)
    from satis_ui import satislar_hub_goster

    hub_ust_baslik(
        kok,
        baslik="TEKLİFLER",
        alt_baslik="Teklif → Müşteri Onayı → Alınan Sipariş",
        app=app,
        geri_komut=lambda: satislar_hub_goster(app),
        geri_metin="← Satışlar",
    )
    komutlar = {
        "liste": lambda: teklif_listesi_goster(app),
        "yeni": lambda: teklif_yeni(app),
        "suresi_dolan": lambda: teklif_listesi_goster(app, suresi_dolan=True),
        "rapor": lambda: teklif_rapor_goster(app),
    }
    ızgara = tk.Frame(kok, bg=ACIK_BG)
    ızgara.pack(fill="both", expand=True, padx=12, pady=8)
    ızgara.columnconfigure(0, weight=1)
    for i, (baslik, aciklama, anahtar) in enumerate(TEKLIF_HUB_KARTLARI):
        HubKart(
            ızgara,
            baslik=baslik,
            aciklama=aciklama,
            komut=lambda k=anahtar: (app.nav_ac(komutlar[k]) if hasattr(app, "nav_ac") else komutlar[k]()),
        ).grid(row=i, column=0, sticky="ew", pady=4)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: teklifler_hub_goster(app))


def teklif_listesi_goster(app, *, suresi_dolan: bool = False) -> None:
    app._icerigi_temizle()
    stil_uygula(root=app)
    from satis_tema import ekran_ust_cubugu

    govde = ekran_ust_cubugu(
        app,
        "SÜRESİ DOLAN TEKLİFLER" if suresi_dolan else "TEKLİF LİSTESİ",
        alt_baslik="Çift tık: aç  |  Teklif stok/cari hareketi oluşturmaz",
        geri_komut=lambda: teklifler_hub_goster(app),
        geri_metin="← Teklifler",
    )
    cerceve = ttk.Frame(govde)
    cerceve.pack(fill="both", expand=True, pady=(4, 0))
    kolonlar = (
        "durum",
        "no",
        "rev",
        "tarih",
        "gecerlilik",
        "musteri",
        "temsilci",
        "toplam",
        "pb",
        "takip",
        "siparis",
    )
    if maliyet_izinli():
        kolonlar = kolonlar + ("marj",)
    basliklar = {
        "durum": "Durum",
        "no": "Teklif No",
        "rev": "Rev",
        "tarih": "Tarih",
        "gecerlilik": "Geçerlilik",
        "musteri": "Müşteri",
        "temsilci": "Temsilci",
        "toplam": "Toplam",
        "pb": "PB",
        "takip": "Takip",
        "siparis": "Sipariş No",
        "marj": "Marj %",
    }
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    treeview_stil(tablo)
    for k in kolonlar:
        tablo.heading(k, text=basliklar[k])
        tablo.column(k, width=100 if k != "musteri" else 180, anchor="w")
    dikey = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=dikey.set)
    tablo.grid(row=0, column=0, sticky="nsew")
    dikey.grid(row=0, column=1, sticky="ns")
    cerceve.rowconfigure(0, weight=1)
    cerceve.columnconfigure(0, weight=1)

    def yenile():
        for i in tablo.get_children():
            tablo.delete(i)
        for kayit in QuoteService.listele(suresi_dolan=suresi_dolan):
            t = kayit["teklif"]
            vals = [
                t.durum,
                kayit["gosterim_no"],
                str(t.revizyon_no or 0),
                _tarih(t.teklif_tarihi),
                _tarih(t.gecerlilik_tarihi),
                kayit["musteri"],
                t.satis_temsilcisi or "",
                _para(t.genel_toplam),
                t.para_birimi or "TRY",
                _tarih(t.takip_tarihi),
                t.siparis_no or "",
            ]
            if maliyet_izinli():
                vals.append(_para(t.gercek_marj))
            tablo.insert("", "end", iid=str(t.id), values=tuple(vals))

    def ac(_e=None):
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Teklif", "Bir teklif seçin.", parent=app)
            return
        dlg = TeklifDialog(app, teklif_id=int(sec[0]))
        app.wait_window(dlg)
        yenile()

    tablo.bind("<Double-1>", ac)
    alt = ttk.Frame(govde)
    alt.pack(fill="x", pady=10)
    tk_buton(alt, "Yeni Teklif", lambda: teklif_yeni(app), rol="yeni").pack(side="left")
    tk_buton(alt, "Aç / Düzenle", ac, rol="duzenle").pack(side="left", padx=8)
    tk_buton(alt, "Yenile", yenile, rol="ikincil").pack(side="left")
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: teklif_listesi_goster(app, suresi_dolan=suresi_dolan))


def teklif_yeni(app) -> None:
    dlg = TeklifDialog(app)
    app.wait_window(dlg)
    teklif_listesi_goster(app)


def teklif_rapor_goster(app) -> None:
    app._icerigi_temizle()
    stil_uygula(root=app)
    from satis_tema import ekran_ust_cubugu

    govde = ekran_ust_cubugu(
        app,
        "TEKLİF RAPORLARI",
        alt_baslik="Verilen / kabul / ret / dönüşüm — muhasebe cirosuna dahil edilmez",
        geri_komut=lambda: teklifler_hub_goster(app),
        geri_metin="← Teklifler",
    )
    kayitlar = QuoteService.listele(sadece_aktif=True)
    toplam = len(kayitlar)
    kabul = sum(1 for k in kayitlar if k["teklif"].durum in ("KABUL EDİLDİ", "SİPARİŞE DÖNÜŞTÜ", "KISMEN KABUL"))
    ret = sum(1 for k in kayitlar if k["teklif"].durum == "REDDEDİLDİ")
    donusen = sum(1 for k in kayitlar if k["teklif"].durum == "SİPARİŞE DÖNÜŞTÜ")
    tutar = sum((k["teklif"].genel_toplam or 0) for k in kayitlar)
    oran = (Decimal(donusen) / Decimal(toplam) * 100) if toplam else Decimal("0")
    ozet = ttk.Frame(govde)
    ozet.pack(fill="x", pady=8)
    for baslik, deger in (
        ("Teklif Sayısı", str(toplam)),
        ("Kabul", str(kabul)),
        ("Ret", str(ret)),
        ("Siparişe Dönüşen", str(donusen)),
        ("Dönüşüm %", f"{oran:.1f}"),
        ("Teklif Tutarı", _para(tutar)),
    ):
        kutu = ttk.LabelFrame(ozet, text=baslik, padding=10)
        kutu.pack(side="left", expand=True, fill="x", padx=4)
        ttk.Label(kutu, text=deger, font=("Segoe UI", 12, "bold")).pack()


class TeklifDialog(tk.Toplevel):
    """Kurumsal teklif kartı."""

    def __init__(self, parent, teklif_id: int | None = None):
        super().__init__(parent)
        self.result = None
        self.app = parent
        self.teklif = QuoteService.getir(teklif_id) if teklif_id else None
        self.satirlar: list[dict[str, Any]] = []
        self.masraflar: list[dict[str, Any]] = []
        self._fiyat_geri_al: list[dict[str, Any]] | None = None
        self._fiyat_ozet: dict[str, Any] = {}
        self._delivery_term_manual = False
        self._uzlasilan_tutar = None
        self._uzlasilan_ui_kilit = False
        self._uzlasilan_fiyat_snapshot = None
        self._uzlasilan_snapshot_brut = None
        self._teklif_yukleniyor = False
        self.musteriler = QuoteService.aktif_musterileri()
        self.musteri_map = {f"{m.cari_kodu} - {m.unvan}": m for m in self.musteriler}
        self.aday_musteri_map: dict[str, Any] = {}
        self.title("Teklif Formu")
        from ui_pencere import belge_penceresini_hazirla

        belge_penceresini_hazirla(
            self,
            min_genislik=900,
            min_yukseklik=520,
            varsayilan_genislik=1180,
            varsayilan_yukseklik=720,
            maximize=True,
        )
        self.configure(bg=ACIK_GRI)
        # transient yarı ekranda büyüt/küçültü kapatır — OS + araç çubuğu kontrolleri için kaldır
        try:
            self.wm_transient("")
        except tk.TclError:
            try:
                self.transient(None)
            except Exception:
                pass
        try:
            self.resizable(True, True)
        except tk.TclError:
            pass
        self.grab_set()
        self._toolbar_kur()
        self._govde_kur()
        try:
            self._teklif_alt_ozet_kur()
        except Exception:
            pass
        if self.teklif:
            self._doldur()
        else:
            try:
                self._yeni_varsayilan()
            except Exception:
                # Kısmi hata olsa bile no/tarih garantisi
                try:
                    self._teklif_no_tarih_garanti()
                except Exception:
                    pass
        self._buton_durumlari()
        self.bind("<F1>", lambda _e: self.kaydet())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _toolbar_kur(self):
        ust = tk.Frame(self, bg=LACIVERT, height=56)
        ust.pack(fill="x")
        self._teklif_toolbar = ust
        sol = tk.Frame(ust, bg=LACIVERT)
        sol.pack(side="left", padx=12, pady=8)
        tk.Label(sol, text="TEKLİF FORMU", bg=LACIVERT, fg=BEYAZ, font=("Segoe UI", 14, "bold")).pack(
            anchor="w"
        )
        self.lbl_meta = tk.Label(sol, text="", bg=LACIVERT, fg=SARI, font=("Segoe UI", 9))
        self.lbl_meta.pack(anchor="w")
        sag = tk.Frame(ust, bg=LACIVERT)
        sag.pack(side="right", padx=10, pady=6)
        self.rozet = tk.Label(
            sag, text="TASLAK", bg="#64748B", fg=BEYAZ, font=("Segoe UI", 9, "bold"), padx=10, pady=4
        )
        self.rozet.pack(side="left", padx=6)
        self.btn_kaydet = self._btn(sag, "Kaydet (F1)", self.kaydet, SARI, LACIVERT)
        self.btn_gonderildi = self._btn(
            sag, "Müşteriye Gönderildi", lambda: self._durum("MÜŞTERİYE GÖNDERİLDİ"), "#1565C0"
        )
        self.btn_kabul = self._btn(sag, "Kabul Edildi", self._kabul_edildi, YESIL)
        self.btn_siparisler = self._btn(sag, "Siparişler", self._siparis_listesi_ac, LACIVERT)
        self._btn(sag, "Ön İzleme", self._onizleme, "#455A64")
        self.btn_yazdir = self._btn(sag, "Yazdır", self._yazdir, "#1565C0")
        diger = tk.Menubutton(
            sag, text="Diğer ▾", bg="#374151", fg=BEYAZ, relief="flat", font=("Segoe UI", 9, "bold")
        )
        menu = tk.Menu(diger, tearoff=0)
        menu.add_command(label="PDF", command=self._pdf)
        menu.add_command(label="Word", command=self._word)
        menu.add_command(label="Yazdır / A4 Ön İzleme", command=self._yazdir)
        menu.add_command(label="E-posta İçin Hazırla", command=self._email_hazirla)
        menu.add_command(label="WhatsApp İçin PDF", command=self._whatsapp_pdf)
        menu.add_separator()
        if maliyet_izinli():
            self._btn(sag, "Karlılık Analizi", self._ic_maliyet_analizi, "#0F766E")
            menu.add_command(label="İç Maliyet Analizi", command=self._ic_maliyet_analizi)
            menu.add_separator()
        menu.add_command(label="Teklifi Revize Et", command=self._revizyon)
        menu.add_command(label="Siparişe Dönüştür", command=self._siparise)
        menu.add_command(label="Sipariş Listesi", command=self._siparis_listesi_ac)
        menu.add_command(label="Bağlı Siparişi Aç", command=self._bagli_siparis_ac)
        menu.add_separator()
        menu.add_command(label="Şablon / Hitap Ayarları", command=self._sablon_ayarlari)
        menu.add_command(label="Logo ve Antet Ayarları", command=self._logo_antet_ayarlari)
        menu.add_command(label="Kayıtlı Çıktıları Aç", command=self._kayitli_ciktilar)
        menu.add_separator()
        menu.add_command(label="Reddet…", command=self._reddet)
        menu.add_command(label="İptal…", command=lambda: self._durum("İPTAL", gerekce_iste=True))
        menu.add_command(label="Geçerlilik Uzat…", command=self._uzat)
        menu.add_separator()
        menu.add_command(label="Pasife Al", command=self._pasif)
        diger.configure(menu=menu)
        diger.pack(side="left", padx=3)
        # Pencere: aşağı / büyüt-küçült / kapat (─ □ ✕)
        self._btn(sag, "─", self._teklif_pencere_asagi, "#455A64")
        self._btn_pencere_buyut = self._btn(
            sag, "□", self._teklif_pencere_buyut_toggle, "#455A64"
        )
        try:
            if str(self.state() or "") == "zoomed":
                self._btn_pencere_buyut.configure(text="❐")
        except tk.TclError:
            pass
        self._btn(sag, "✕", self.destroy, "#9E9E9E")

    def _teklif_pencere_asagi(self, _event=None):
        """Görev çubuğuna indir."""
        try:
            self.iconify()
        except tk.TclError:
            pass

    def _teklif_pencere_buyut_toggle(self, _event=None):
        """Tam ekran (zoomed) ↔ önceki boyut."""
        try:
            durum = str(self.state() or "")
        except tk.TclError:
            durum = ""
        btn = getattr(self, "_btn_pencere_buyut", None)
        try:
            if durum == "zoomed":
                self.state("normal")
                geo = getattr(self, "_teklif_onceki_geometry", None)
                if geo:
                    try:
                        self.geometry(geo)
                    except tk.TclError:
                        pass
                if btn is not None:
                    btn.configure(text="□")
            else:
                try:
                    self._teklif_onceki_geometry = self.geometry()
                except tk.TclError:
                    self._teklif_onceki_geometry = None
                self.state("zoomed")
                if btn is not None:
                    btn.configure(text="❐")
        except tk.TclError:
            pass
        return "break"

    def _btn(self, parent, text, cmd, bg, fg=BEYAZ):
        b = tk.Button(
            parent,
            text=text,
            command=cmd,
            bg=bg,
            fg=fg,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=5,
            cursor="hand2",
        )
        b.pack(side="left", padx=2)
        return b

    def _govde_kur(self):
        import fatura_tema as ftema

        # Orta kaydırma alanı (sticky footer için)
        kaydirma = tk.Frame(self, bg=ACIK_GRI, highlightthickness=0)
        kaydirma.pack(fill="both", expand=True)
        self._kaydirma_alani = kaydirma

        self.canvas = tk.Canvas(kaydirma, bg=ACIK_GRI, highlightthickness=0)
        scroll = ttk.Scrollbar(kaydirma, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.icerik = ttk.Frame(self.canvas)
        self._canvas_win = self.canvas.create_window((0, 0), window=self.icerik, anchor="nw")
        self.icerik.bind(
            "<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        def _canvas_genislik(e):
            try:
                self.canvas.itemconfigure(self._canvas_win, width=max(1, int(e.width)))
            except tk.TclError:
                pass

        self.canvas.bind("<Configure>", _canvas_genislik)

        _ipady = ftema.form_ipady()
        _py = ftema.form_pady(2)
        gap = 10
        self.girdiler: dict[str, Any] = {}

        # ——— Üst: Genel | Müşteri | Ticari | Fiyat Analiz (dört eşit kolon) ———
        ust = ttk.Frame(self.icerik)
        ust.pack(fill="x", padx=10, pady=(6, 4))
        for _c in range(4):
            ust.columnconfigure(_c, weight=1, uniform="teklif_ust")
        ust.rowconfigure(0, weight=1)

        genel = ttk.LabelFrame(ust, text="Genel Bilgiler", padding=8)
        genel.grid(row=0, column=0, sticky="nsew", padx=(0, gap))
        genel.columnconfigure(1, weight=1)
        genel.columnconfigure(3, weight=1)
        self._alan(genel, 0, 0, "Teklif No", "teklif_no", width=14)
        self._tarih_alan(
            genel, 0, 2, "Teklif Tarihi", "teklif_tarihi",
            on_select=self._teklif_tarih_veya_kur_degisti, width=10,
        )
        self._tarih_alan(
            genel, 1, 0, "Geçerlilik Tarihi", "gecerlilik_tarihi",
            on_select=self._gecerlilik_tarih_degisti, width=10,
        )
        self._alan(genel, 1, 2, "Geçerlilik Günü", "gecerlilik_gunu", width=6)
        self._alan(genel, 2, 0, "Konu", "konu", width=16)
        self._alan(genel, 2, 2, "Referans No", "referans_no", width=10)
        self._gecerlilik_senkron_kilit = False
        self.girdiler["gecerlilik_gunu"].bind("<KeyRelease>", self._gecerlilik_gun_degisti)
        self.girdiler["gecerlilik_gunu"].bind("<FocusOut>", self._gecerlilik_gun_degisti)
        self.girdiler["gecerlilik_tarihi"].bind("<FocusOut>", self._gecerlilik_tarih_degisti)
        self.girdiler["teklif_tarihi"].bind("<FocusOut>", self._teklif_tarih_veya_kur_degisti)

        # Ödeme şekli — Genel Bilgiler altındaki boşluğa (dar, 2 satır)
        odeme_panel = ttk.LabelFrame(genel, text="Ödeme Şekli", padding=4)
        odeme_panel.grid(row=3, column=0, columnspan=4, sticky="nsew", padx=2, pady=(8, 2))
        self._odeme_secim: dict[str, tk.BooleanVar] = {}
        self._odeme_vade_manuel = False
        self._odeme_secim_kilit = False
        satir1 = ttk.Frame(odeme_panel)
        satir1.pack(anchor="w", pady=(0, 2))
        satir2 = ttk.Frame(odeme_panel)
        satir2.pack(anchor="w")

        def _odeme_cb(parent, sekil: str):
            var = tk.BooleanVar(value=(sekil == NAKIT))
            self._odeme_secim[sekil] = var
            ttk.Checkbutton(
                parent,
                text=sekil,
                variable=var,
                command=lambda s=sekil: self._odeme_tek_sec(s),
            ).pack(side="left", padx=(0, 4))

        _odeme_cb(satir1, NAKIT)
        self.odeme_nakit_turu = ttk.Combobox(
            satir1, values=list(NAKIT_ALT), width=7, state="readonly"
        )
        self.odeme_nakit_turu.set("Havale")
        self.odeme_nakit_turu.pack(side="left", padx=(0, 8))
        self.girdiler["odeme_nakit_turu"] = self.odeme_nakit_turu
        self.odeme_nakit_turu.bind("<<ComboboxSelected>>", self._odeme_hesap_guncelle)

        _odeme_cb(satir1, KREDI_KARTI)
        self.odeme_taksit = ttk.Combobox(
            satir1, values=kk_taksit_secenekleri(), width=10, state="readonly"
        )
        self.odeme_taksit.set("Tek Çekim")
        self.odeme_taksit.pack(side="left", padx=(0, 4))
        self.girdiler["odeme_taksit"] = self.odeme_taksit
        self.odeme_taksit.bind("<<ComboboxSelected>>", self._odeme_hesap_guncelle)

        _odeme_cb(satir2, "Çek")
        _odeme_cb(satir2, "Senet")
        _odeme_cb(satir2, "Açık Hesap")
        ttk.Label(satir2, text="Gün").pack(side="left", padx=(8, 2))
        self.odeme_vade_gun = ttk.Entry(satir2, width=5)
        self.odeme_vade_gun.pack(side="left", padx=(0, 6))
        self.girdiler["odeme_vade_gun"] = self.odeme_vade_gun
        ttk.Label(satir2, text="Vade").pack(side="left", padx=(0, 2))
        vade_fr = ttk.Frame(satir2)
        vade_fr.pack(side="left")
        self.odeme_vade_tarihi = ttk.Entry(vade_fr, width=10)
        self.odeme_vade_tarihi.pack(side="left")
        takvim_butonu(
            vade_fr,
            self.odeme_vade_tarihi,
            on_select=self._odeme_vade_tarih_yazildi,
            text="📅",
            width=3,
        )
        self.girdiler["odeme_vade_tarihi"] = self.odeme_vade_tarihi
        self.odeme_vade_gun.bind("<KeyRelease>", self._odeme_vade_gun_degisti)
        self.odeme_vade_gun.bind("<FocusOut>", self._odeme_vade_gun_degisti)
        self.odeme_vade_tarihi.bind("<KeyRelease>", self._odeme_vade_tarih_yazildi)
        self.odeme_vade_tarihi.bind("<FocusOut>", self._odeme_vade_tarih_yazildi)
        self.girdiler["odeme_sekli"] = self.odeme_nakit_turu

        mus = ttk.LabelFrame(ust, text="Müşteri", padding=8)
        mus.grid(row=0, column=1, sticky="nsew", padx=(0, gap))
        mus.columnconfigure(1, weight=1)
        mus.columnconfigure(3, weight=1)
        # Müşteri kodu + adı dikey; arama adı kutusunda (Ara butonu yok)
        self._selected_customer_id = None
        self._musteri_kod_map = {
            (m.cari_kodu or "").strip(): m
            for m in self.musteriler
            if (m.cari_kodu or "").strip()
        }
        ttk.Label(mus, text="Müşteri Kodu").grid(row=0, column=0, sticky="w", padx=4, pady=_py)
        kod_satir = ttk.Frame(mus)
        kod_satir.grid(row=0, column=1, columnspan=3, sticky="ew", padx=4, pady=_py)
        kod_satir.columnconfigure(0, weight=1)
        self.musteri_kodu = ttk.Entry(kod_satir, width=14)
        self.musteri_kodu.grid(row=0, column=0, sticky="ew", ipady=_ipady)
        ttk.Button(kod_satir, text="Yeni", width=6, command=self._yeni_musteri_ekle).grid(
            row=0, column=1, sticky="e", padx=(6, 0)
        )
        ttk.Label(mus, text="Müşteri Adı").grid(row=1, column=0, sticky="w", padx=4, pady=_py)
        self.musteri_adi = ttk.Entry(mus, width=28)
        self.musteri_adi.grid(
            row=1, column=1, columnspan=3, sticky="ew", padx=4, pady=_py, ipady=_ipady
        )
        self._musteri_arama_after = None
        self._musteri_ara_sonuclar: list[str] = []
        self.musteri_kodu.bind("<KeyRelease>", self._musteri_kod_degisti)
        self.musteri_kodu.bind("<Return>", self._musteri_kod_enter)
        self.musteri_kodu.bind("<KP_Enter>", self._musteri_kod_enter)
        self.musteri_kodu.bind("<F2>", lambda _e: self._musteri_ara_secim_ac(zorla=True))
        self.musteri_adi.bind("<KeyRelease>", self._musteri_ara_filtrele)
        self.musteri_adi.bind("<Return>", self._musteri_ara_enter)
        self.musteri_adi.bind("<KP_Enter>", self._musteri_ara_enter)
        self.musteri_adi.bind("<F2>", lambda _e: self._musteri_ara_secim_ac(zorla=True))
        # Geri uyumluluk: eski self.musteri.get() çağrıları kod alanına yönlensin
        self.musteri = self.musteri_kodu
        # Aday müşteri — seçenekli + Yeni
        ttk.Label(mus, text="Aday Müşteri").grid(row=2, column=0, sticky="w", padx=4, pady=_py)
        aday_satir = ttk.Frame(mus)
        aday_satir.grid(row=2, column=1, columnspan=3, sticky="ew", padx=4, pady=_py)
        aday_satir.columnconfigure(0, weight=1)
        self.aday_musteri_map: dict[str, Any] = {}
        self.girdiler["aday_musteri_adi"] = ttk.Combobox(
            aday_satir, values=self._aday_musteri_secenekleri(), width=18
        )
        self.girdiler["aday_musteri_adi"].grid(row=0, column=0, sticky="ew", ipady=_ipady)
        ttk.Button(
            aday_satir, text="Yeni", width=6, command=self._yeni_aday_musteri_ekle
        ).grid(row=0, column=1, sticky="e", padx=(6, 0))
        self._alan(mus, 3, 0, "Yetkili", "musteri_yetkilisi", width=14)
        self._alan(mus, 3, 2, "Telefon", "musteri_telefon", width=12)
        self._alan(mus, 4, 0, "E-posta", "musteri_email", width=14)
        ttk.Label(mus, text="Satış Temsilcisi").grid(
            row=4, column=2, sticky="w", padx=4, pady=_py
        )
        self.girdiler["satis_temsilcisi"] = ttk.Combobox(
            mus,
            values=self._satis_temsilcisi_secenekleri(),
            width=12,
            state="readonly",
        )
        self.girdiler["satis_temsilcisi"].grid(
            row=4, column=3, sticky="ew", padx=4, pady=_py, ipady=_ipady
        )

        ticari = ttk.LabelFrame(ust, text="Ticari Şartlar", padding=8)
        ticari.grid(row=0, column=2, sticky="nsew", padx=(0, gap))
        ticari.columnconfigure(1, weight=1)
        ticari.columnconfigure(3, weight=1)
        # Para birimi + döviz karşılığı (TCMB efektif alış)
        from database.models.doviz import PARA_BIRIMLERI

        ttk.Label(ticari, text="Para Birimi").grid(row=0, column=0, sticky="w", padx=4, pady=_py)
        self.para_birimi = ttk.Combobox(
            ticari, values=list(PARA_BIRIMLERI), width=8, state="readonly"
        )
        self.para_birimi.set("TRY")
        self.para_birimi.grid(row=0, column=1, sticky="w", padx=4, pady=_py)
        self.girdiler["para_birimi"] = self.para_birimi
        self.para_birimi.bind("<<ComboboxSelected>>", self._teklif_para_birimi_degisti)

        ttk.Label(ticari, text="Belge Kuru").grid(row=0, column=2, sticky="w", padx=4, pady=_py)
        kur_satir = ttk.Frame(ticari)
        kur_satir.grid(row=0, column=3, sticky="ew", padx=4, pady=_py)
        self.kur_giris = ttk.Entry(kur_satir, width=12, justify="right")
        self.kur_giris.insert(0, "1")
        self.kur_giris.pack(side="left")
        self.girdiler["kur"] = self.kur_giris
        self.kur_giris.bind("<FocusOut>", self._teklif_kur_manuel)
        ttk.Button(kur_satir, text="TCMB", width=5, command=self._teklif_tcmb_kur_yenile).pack(
            side="left", padx=(4, 0)
        )
        self._teklif_kur_turu = "effective_buying"
        self._teklif_kur_kaynagi = "MANUEL"
        self._teklif_kur_tarihi = date.today()
        self.lbl_kur_kaynak = ttk.Label(ticari, text="Efektif Alış", foreground="#64748B")
        self.lbl_kur_kaynak.grid(row=1, column=2, columnspan=2, sticky="w", padx=4, pady=(0, 2))

        # Döviz karşılığı: kur seçimi + kur bilgisi (her zaman görünür alan)
        ttk.Label(ticari, text="Kur Seçimi").grid(row=2, column=0, sticky="w", padx=4, pady=_py)
        self.doviz_karsilik_pb = ttk.Combobox(
            ticari, values=("—", "USD", "EUR"), width=8, state="readonly"
        )
        self.doviz_karsilik_pb.set("—")
        self.doviz_karsilik_pb.grid(row=2, column=1, sticky="w", padx=4, pady=_py)
        self.girdiler["doviz_karsilik_pb"] = self.doviz_karsilik_pb
        self.doviz_karsilik_pb.bind("<<ComboboxSelected>>", self._teklif_doviz_karsilik_degisti)

        ttk.Label(ticari, text="Kur Bilgisi").grid(row=2, column=2, sticky="w", padx=4, pady=_py)
        karsilik_kur_satir = ttk.Frame(ticari)
        karsilik_kur_satir.grid(row=2, column=3, sticky="ew", padx=4, pady=_py)
        # disabled yerine normal/readonly — Windows'ta disabled Entry görünmez kalabiliyor
        self.doviz_karsilik_kur = ttk.Entry(karsilik_kur_satir, width=12, justify="right")
        self.doviz_karsilik_kur.insert(0, "")
        self.doviz_karsilik_kur.pack(side="left", fill="x", expand=True)
        self.doviz_karsilik_kur.configure(state="readonly")
        self.girdiler["doviz_karsilik_kur"] = self.doviz_karsilik_kur
        self.doviz_karsilik_kur.bind("<FocusOut>", self._teklif_doviz_karsilik_kur_manuel)
        self.doviz_karsilik_kur.bind("<Return>", self._teklif_doviz_karsilik_kur_manuel)
        self.btn_doviz_karsilik_tcmb = ttk.Button(
            karsilik_kur_satir,
            text="TCMB",
            width=5,
            command=self._teklif_doviz_karsilik_tcmb,
            state="disabled",
        )
        self.btn_doviz_karsilik_tcmb.pack(side="left", padx=(4, 0))
        self.lbl_doviz_karsilik_kaynak = ttk.Label(
            ticari, text="TCMB Efektif Alış (USD/EUR seçin)", foreground="#64748B"
        )
        self.lbl_doviz_karsilik_kaynak.grid(
            row=3, column=2, columnspan=2, sticky="w", padx=4, pady=(0, 4)
        )

        self._alan(ticari, 4, 0, "Teslim Süresi", "teslim_suresi", width=10)
        self._alan(ticari, 4, 2, "Depo", "depo", width=10)
        self._alan(ticari, 5, 0, "Proje", "proje", width=10)
        ttk.Label(ticari, text="Termin Türü").grid(row=5, column=2, sticky="w", padx=4, pady=_py)
        self.termin_turu = ttk.Combobox(
            ticari, values=list(TERMIN_TURLERI), width=14, state="readonly"
        )
        self.termin_turu.set(TERMIN_TURLERI[0])
        self.termin_turu.grid(row=5, column=3, sticky="ew", padx=4, pady=_py)
        self._alan(ticari, 6, 0, "Termin Süresi (Gün)", "delivery_term_days", width=6)
        self._tarih_alan(
            ticari, 6, 2, "Tahmini Teslim Tarihi", "estimated_delivery_date",
            on_select=self._termin_manuel_isaretle, width=10,
        )
        self._alan(ticari, 7, 0, "Termin Açıklaması", "delivery_term_note", width=20)
        self.girdiler["delivery_term_days"].bind("<KeyRelease>", self._termin_gun_degisti)
        self.girdiler["delivery_term_days"].bind("<FocusOut>", self._termin_gun_degisti)
        self.girdiler["estimated_delivery_date"].bind("<KeyRelease>", self._termin_manuel_isaretle)

        # Sağ üst: Fiyat Analiz / Çalışma — açık sarı zemin
        ACIK_SARI = "#FEF9C3"
        self.fiyat_panel = tk.LabelFrame(
            ust,
            text="Fiyat Analiz / Çalışma",
            bg=ACIK_SARI,
            fg=LACIVERT,
            font=("Segoe UI", 9, "bold"),
            padx=8,
            pady=8,
            labelanchor="nw",
        )
        self.fiyat_panel.grid(row=0, column=3, sticky="nsew")
        self.fiyat_panel.columnconfigure(1, weight=1)
        self.fiyat_girdiler: dict[str, Any] = {}

        def _fa_lbl(text, row):
            tk.Label(
                self.fiyat_panel,
                text=text,
                bg=ACIK_SARI,
                fg="#0F172A",
                font=("Segoe UI", 9),
                anchor="w",
            ).grid(row=row, column=0, sticky="w", pady=1)

        _fa_lbl("Kâr Marjı (%)", 0)
        self.fiyat_girdiler["profit_rate"] = ttk.Entry(self.fiyat_panel, width=10)
        self.fiyat_girdiler["profit_rate"].insert(0, "0")
        self.fiyat_girdiler["profit_rate"].grid(row=0, column=1, sticky="ew", pady=1)
        _fa_lbl("Maktu Kâr", 1)
        self.fiyat_girdiler["fixed_profit_amount"] = ttk.Entry(self.fiyat_panel, width=10)
        self.fiyat_girdiler["fixed_profit_amount"].insert(0, "0")
        self.fiyat_girdiler["fixed_profit_amount"].grid(row=1, column=1, sticky="ew", pady=1)
        _fa_lbl("Teklif Masrafı", 2)
        self.fiyat_girdiler["customer_expense_amount"] = ttk.Entry(self.fiyat_panel, width=10)
        self.fiyat_girdiler["customer_expense_amount"].insert(0, "0")
        self.fiyat_girdiler["customer_expense_amount"].grid(row=2, column=1, sticky="ew", pady=1)
        _fa_lbl("İç Masraf", 3)
        self.fiyat_girdiler["internal_expense_amount"] = ttk.Entry(self.fiyat_panel, width=10)
        self.fiyat_girdiler["internal_expense_amount"].insert(0, "0")
        self.fiyat_girdiler["internal_expense_amount"].grid(row=3, column=1, sticky="ew", pady=1)
        _fa_lbl("Yuvarlama", 4)
        self.fiyat_girdiler["yuvarlama"] = ttk.Combobox(
            self.fiyat_panel,
            values=["kurus", "1", "5", "10", "psikolojik", "yok"],
            width=10,
            state="readonly",
        )
        self.fiyat_girdiler["yuvarlama"].set("kurus")
        self.fiyat_girdiler["yuvarlama"].grid(row=4, column=1, sticky="ew", pady=1)
        btn_f = tk.Frame(self.fiyat_panel, bg=ACIK_SARI)
        btn_f.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        tk.Button(
            btn_f,
            text="Fiyatları Hesapla",
            command=self._fiyatlari_hesapla,
            bg=YESIL,
            fg=BEYAZ,
            relief="raised",
            bd=2,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        ).pack(fill="x", pady=1)
        ttk.Button(btn_f, text="Hesaplamayı Geri Al", command=self._fiyat_geri_al_uygula).pack(
            fill="x", pady=1
        )
        ttk.Button(btn_f, text="Masraf Detayı", command=self._masraf_detay).pack(fill="x", pady=1)
        if maliyet_izinli():
            tk.Button(
                btn_f,
                text="Karlılık Analizi",
                command=self._ic_maliyet_analizi,
                bg=LACIVERT,
                fg=BEYAZ,
                relief="raised",
                bd=2,
                font=("Segoe UI", 9, "bold"),
                cursor="hand2",
            ).pack(fill="x", pady=(4, 1))
        # Özet etiketi (gizli metin yok; geri uyumluluk için boş tut)
        self.lbl_fiyat_ozet = tk.Label(self.fiyat_panel, text="", bg=ACIK_SARI)
        self.lbl_fiyat_ozet.grid(row=6, column=0, columnspan=2, sticky="ew")
        self.lbl_toplam = self.lbl_fiyat_ozet
        if not maliyet_izinli():
            for w in (
                self.fiyat_girdiler["profit_rate"],
                self.fiyat_girdiler["fixed_profit_amount"],
                self.fiyat_girdiler["internal_expense_amount"],
            ):
                w.grid_remove()

        self._odeme_secim_degisti()

        # ——— Ürün giriş: kod / ad / miktar / birim kalın kırmızı; maliyet kırmızı ———
        _KIRMIZI_CIZGI = "#DC2626"
        aksiyon = tk.Frame(self.icerik, bg=ACIK_GRI, highlightthickness=0)
        aksiyon.pack(fill="x", padx=10, pady=(2, 2))
        aksiyon_ic = ttk.Frame(aksiyon)
        aksiyon_ic.pack(fill="x", padx=2, pady=4)
        aksiyon_ic.columnconfigure(3, weight=1)

        def _kirmizi_cerceve(parent, col, padx=(0, 10)):
            cer = tk.Frame(
                parent,
                bg=BEYAZ,
                highlightthickness=3,
                highlightbackground=_KIRMIZI_CIZGI,
                highlightcolor=_KIRMIZI_CIZGI,
                bd=0,
            )
            cer.grid(row=0, column=col, sticky="ew" if col == 3 else "w", padx=padx, pady=0)
            return cer

        ttk.Label(aksiyon_ic, text="Ürün Kodu").grid(
            row=0, column=0, sticky="w", padx=(0, 4), pady=0
        )
        kod_cer = _kirmizi_cerceve(aksiyon_ic, 1)
        self.urun_kod = ttk.Entry(kod_cer, width=14)
        self.urun_kod.pack(fill="both", expand=True, ipady=_ipady, padx=1, pady=1)
        self.urun_kod.bind("<Return>", self._urun_getir)

        ttk.Label(aksiyon_ic, text="Ürün Adı / Ara").grid(
            row=0, column=2, sticky="w", padx=(0, 4), pady=0
        )
        ad_cer = _kirmizi_cerceve(aksiyon_ic, 3)
        self.urun_ad_ara = ttk.Entry(ad_cer)
        self.urun_ad_ara.pack(fill="both", expand=True, ipady=_ipady, padx=1, pady=1)
        self._urun_ara_placeholder = "Ürün adında en az 3 harf yazın"
        self.urun_ad_ara.insert(0, self._urun_ara_placeholder)
        self.urun_ad_ara.configure(foreground="#94A3B8")
        self.urun_ad_ara.bind("<FocusIn>", self._urun_ara_focus_in)
        self.urun_ad_ara.bind("<FocusOut>", self._urun_ara_focus_out)

        ttk.Label(aksiyon_ic, text="Miktar").grid(row=0, column=4, sticky="w", padx=(0, 4))
        miktar_cer = _kirmizi_cerceve(aksiyon_ic, 5, padx=(0, 8))
        self.urun_miktar = ttk.Entry(miktar_cer, width=8)
        self.urun_miktar.insert(0, "1")
        self.urun_miktar.pack(fill="both", expand=True, ipady=_ipady, padx=1, pady=1)
        self.urun_miktar.bind("<Return>", lambda _e: self._satir_ekle())

        ttk.Label(aksiyon_ic, text="Birim").grid(row=0, column=6, sticky="w", padx=(0, 4))
        birim_cer = _kirmizi_cerceve(aksiyon_ic, 7, padx=(0, 8))
        self.urun_birim = ttk.Combobox(birim_cer, width=8, values=manuel_birim_listesi())
        self.urun_birim.set("Adet")
        self.urun_birim.pack(fill="both", expand=True, ipady=_ipady, padx=1, pady=1)

        ttk.Label(aksiyon_ic, text="KDV %").grid(row=0, column=8, sticky="w", padx=(0, 4))
        self.urun_kdv = ttk.Combobox(
            aksiyon_ic,
            values=list(KDV_ORANLARI),
            width=5,
            state="readonly",
        )
        self.urun_kdv.set(str(int(VARSAYILAN_KDV_ORANI)))
        self.urun_kdv.grid(row=0, column=9, sticky="w", padx=(0, 8), ipady=_ipady)
        self.urun_kdv.bind("<<ComboboxSelected>>", self._urun_kdv_degisti)

        ttk.Label(aksiyon_ic, text="Depo").grid(row=0, column=10, sticky="w", padx=(0, 4))
        try:
            depo_list = [d.ad for d in StokService.depolar()]
        except Exception:
            depo_list = ["ANA DEPO"]
        if not depo_list:
            depo_list = ["ANA DEPO"]
        self.urun_depo = ttk.Combobox(aksiyon_ic, width=12, values=depo_list)
        self.urun_depo.set(self.girdiler["depo"].get().strip() or depo_list[0])
        self.urun_depo.grid(row=0, column=11, sticky="w", padx=(0, 8), ipady=_ipady)

        self.lbl_urun_maliyet = ttk.Label(aksiyon_ic, text="Maliyet Fiyatı")
        self.lbl_urun_maliyet.grid(row=0, column=12, sticky="w", padx=(8, 4))
        maliyet_cer = _kirmizi_cerceve(aksiyon_ic, 13, padx=(0, 4))
        self.urun_maliyet = ttk.Entry(maliyet_cer, width=10, justify="right")
        self.urun_maliyet.pack(fill="both", expand=True, ipady=_ipady, padx=1, pady=1)
        self.lbl_urun_maliyet_pb = ttk.Label(aksiyon_ic, text="TRY", foreground="#64748B")
        self.lbl_urun_maliyet_pb.grid(row=0, column=14, sticky="w", padx=(0, 8))
        if not maliyet_izinli():
            self.lbl_urun_maliyet.grid_remove()
            maliyet_cer.grid_remove()
            self.lbl_urun_maliyet_pb.grid_remove()

        def _btn3d(parent, text, cmd, bg, fg=BEYAZ):
            return tk.Button(
                parent,
                text=text,
                command=cmd,
                bg=bg,
                fg=fg,
                activebackground=bg,
                activeforeground=fg,
                relief="raised",
                bd=3,
                font=("Segoe UI", 9, "bold"),
                padx=10,
                pady=4,
                cursor="hand2",
            )

        btn_satir = ttk.Frame(aksiyon_ic)
        btn_satir.grid(row=0, column=15, sticky="e", padx=(4, 0))
        _btn3d(btn_satir, "Satır Ekle", self._satir_ekle, YESIL).pack(side="left", padx=2)
        _btn3d(btn_satir, "Güncelle", self._satir_guncelle, LACIVERT).pack(side="left", padx=2)
        _btn3d(btn_satir, "Satır Sil", self._satir_sil, KIRMIZI).pack(side="left", padx=2)
        _btn3d(btn_satir, "Stok Listesi", self._stok_listesi_ac, YESIL).pack(side="left", padx=2)
        _btn3d(btn_satir, "+ Manuel Ürün Ekle", self._manuel_urun_ekle, YESIL).pack(
            side="left", padx=2
        )

        uzlas_cer = ttk.Frame(aksiyon_ic)
        uzlas_cer.grid(row=0, column=16, sticky="e", padx=(12, 0))
        ttk.Label(uzlas_cer, text="Uzlaşılan Tutar").pack(side="left", padx=(0, 4))
        self._uzlasilan_tutar_entry = ttk.Entry(uzlas_cer, width=12, justify="right")
        self._uzlasilan_tutar_entry.pack(side="left", ipady=_ipady)
        self._uzlasilan_tutar_entry.bind("<FocusOut>", self._uzlasilan_tutar_degisti)
        self._uzlasilan_tutar_entry.bind("<Return>", self._uzlasilan_tutar_degisti)
        self._uzlasilan_tutar_entry.bind("<KP_Enter>", self._uzlasilan_tutar_degisti)
        self._uzlasilan_tutar_entry.bind("<KeyRelease>", self._uzlasilan_tutar_canli)

        satir_alt2 = ttk.Frame(self.icerik)
        satir_alt2.pack(fill="x", padx=10, pady=(0, 4))
        self._urun_arama = TeklifUrunAramaPaneli(
            satir_alt2,
            self.urun_ad_ara,
            depo_getter=lambda: (
                self.urun_depo.get().strip()
                or self.girdiler["depo"].get().strip()
                or "ANA DEPO"
            ),
            maliyet_izinli=maliyet_izinli,
            on_select=self._arama_urun_secildi,
            arama_fn=StokService.teklif_urun_ara,
            yetki_stok=lambda: yetki_var("stok_goruntuleme", "stok_duzenleme", "goruntuleme"),
            yetki_manuel=lambda: yetki_var(
                "teklif_manuel_urun", "satis_duzenleme", "yeni_kayit"
            ),
            on_stok_yeni=self._arama_yeni_stok,
            on_manuel=self._manuel_urun_ekle,
            on_manuel_isim=self._manuel_urun_isimle,
        )
        self._urun_arama.pack_hint(side="left", padx=2)
        ttk.Label(satir_alt2, text="Maliyet Kaynağı").pack(side="left", padx=(16, 2))
        self.maliyet_kaynak = ttk.Combobox(
            satir_alt2,
            values=[MALIYET_KAYNAK_ETIKET.get(k, k) for k in MALIYET_KAYNAKLARI],
            width=18,
            state="readonly",
        )
        self._maliyet_kaynak_kodlari = list(MALIYET_KAYNAKLARI)
        self.maliyet_kaynak.set(MALIYET_KAYNAK_ETIKET.get("SON_ALIS", "SON_ALIS"))
        self.maliyet_kaynak.pack(side="left", padx=4)
        self.maliyet_kaynak.bind("<<ComboboxSelected>>", self._maliyet_kaynak_degisti)
        ttk.Button(
            satir_alt2, text="Güncel Alış Fiyatlarını Yenile", command=self._alis_fiyatlari_yenile
        ).pack(side="left", padx=6)

        # ——— Ürünler (tam genişlik; Fiyat Analiz sağ üstte) ———
        urun = ttk.LabelFrame(self.icerik, text="Ürünler", padding=8)
        urun.pack(fill="both", expand=True, padx=10, pady=4)
        if maliyet_izinli():
            kolonlar = (
                "tur",
                "kod",
                "ad",
                "miktar",
                "birim",
                "alis",
                "kaynak",
                "fiyat",
                "om",
                "isk",
                "kdv",
                "toplam",
                "marj",
            )
            basliklar = {
                "tur": "Tür",
                "kod": "Kod",
                "ad": "Ad",
                "miktar": "Miktar",
                "birim": "Birim",
                "alis": "Alış",
                "kaynak": "Kaynak",
                "fiyat": "Fiyat",
                "om": "O/M",
                "isk": "İsk",
                "kdv": "KDV",
                "toplam": "Toplam",
                "marj": "Marj",
            }
            genislikler = {
                "tur": 48,
                "kod": 90,
                "ad": 280,
                "miktar": 80,
                "birim": 70,
                "alis": 90,
                "kaynak": 90,
                "fiyat": 90,
                "om": 48,
                "isk": 60,
                "kdv": 60,
                "toplam": 100,
                "marj": 90,
            }
        else:
            kolonlar = ("tur", "kod", "ad", "miktar", "birim", "fiyat", "isk", "kdv", "net", "toplam")
            basliklar = {
                "tur": "Tür",
                "kod": "Kod",
                "ad": "Ad",
                "miktar": "Miktar",
                "birim": "Birim",
                "fiyat": "Fiyat",
                "isk": "İsk",
                "kdv": "KDV",
                "net": "Net",
                "toplam": "Toplam",
            }
            genislikler = {
                "tur": 48,
                "kod": 100,
                "ad": 320,
                "miktar": 90,
                "birim": 80,
                "fiyat": 100,
                "isk": 70,
                "kdv": 70,
                "net": 100,
                "toplam": 110,
            }
        self._satir_kolonlar = kolonlar
        satir_h = ftema.scale_height(ftema.TABLO_SATIR_TABAN_PX)  # 28 × 1.50
        stil = ttk.Style(self)
        stil.configure(
            "TeklifSatir.Treeview",
            font=("Segoe UI", 12, "bold"),
            rowheight=satir_h,
            borderwidth=1,
            relief="solid",
            fieldbackground=BEYAZ,
            background=BEYAZ,
            foreground="#0B1220",
        )
        stil.configure(
            "TeklifSatir.Treeview.Heading",
            font=("Segoe UI", 10, "bold"),
            background="#E8EEF5",
            foreground=LACIVERT,
            relief="raised",
            borderwidth=1,
            padding=(6, ftema.scale_height(ftema.TABLO_BASLIK_PAD_TABAN)),
        )
        stil.map(
            "TeklifSatir.Treeview.Heading",
            background=[("active", "#D5DEEA")],
            foreground=[("active", LACIVERT)],
        )
        stil.map(
            "TeklifSatir.Treeview",
            background=[("selected", "#1A237E")],
            foreground=[("selected", "#FFFFFF")],
        )
        tablo_cer = ttk.Frame(urun)
        tablo_cer.pack(fill="both", expand=True)
        scroll_y = ttk.Scrollbar(tablo_cer, orient="vertical")
        self.satir_tablo = ttk.Treeview(
            tablo_cer,
            columns=kolonlar,
            show="headings",
            height=14,
            style="TeklifSatir.Treeview",
            yscrollcommand=scroll_y.set,
        )
        scroll_y.configure(command=self.satir_tablo.yview)
        scroll_y.pack(side="right", fill="y")
        for c in kolonlar:
            self.satir_tablo.heading(c, text=basliklar[c])
            # Ad esnek; diğerleri de yayılabilsin ki satırlar tüm ekrana otursun
            self.satir_tablo.column(
                c,
                width=genislikler.get(c, 80),
                minwidth=36 if c == "tur" else 48,
                stretch=True,
                anchor="w" if c in ("kod", "ad", "kaynak") else "e" if c != "tur" else "center",
            )
        self.satir_tablo.pack(side="left", fill="both", expand=True)
        self.satir_tablo.bind("<Double-1>", self._satir_cift_tik)
        self.satir_tablo.bind("<<TreeviewSelect>>", self._satir_secildi)
        self._duzenlenen_satir_idx: int | None = None
        self.satir_tablo.tag_configure("tek", background=BEYAZ, foreground="#0B1220")
        self.satir_tablo.tag_configure("cift", background="#F0F3F7", foreground="#0B1220")
        self.satir_tablo.tag_configure("maliyet_yok", foreground=KIRMIZI)
        self.satir_tablo.tag_configure("manuel_satir", foreground="#6D28D9")
        self.satir_tablo.bind("<Button-3>", self._satir_sag_menu)
        self._secili_urun: dict[str, Any] | None = None
        self._urun_sec_pencere = None
        self.after_idle(self._teklif_excel_cizgileri_kur)

        notlar = ttk.LabelFrame(self.icerik, text="Notlar", padding=8)
        notlar.pack(fill="x", padx=10, pady=6)
        # Genişlik: satır boyunca (toplam/fiyat sütununa kadar alan); yükseklik 6c × 1.25 = 7.5c
        not_govde = ttk.Frame(notlar, height="7.5c")
        not_govde.pack(fill="x", expand=True)
        not_govde.pack_propagate(False)
        ttk.Label(not_govde, text="Müşteri Notu").grid(row=0, column=0, sticky="nw")
        self.musteri_notu = tk.Text(not_govde, height=5, width=1, wrap="word")
        self.musteri_notu.grid(row=0, column=1, padx=4, pady=2, sticky="nsew")
        ttk.Label(not_govde, text="İç Not").grid(row=1, column=0, sticky="nw")
        self.ic_not = tk.Text(not_govde, height=4, width=1, wrap="word")
        self.ic_not.grid(row=1, column=1, padx=4, pady=2, sticky="nsew")
        ttk.Label(not_govde, text="Ticari Şartlar").grid(row=2, column=0, sticky="nw")
        self.ticari_sartlar = tk.Text(not_govde, height=5, width=1, wrap="word")
        self.ticari_sartlar.grid(row=2, column=1, padx=4, pady=2, sticky="nsew")
        not_govde.columnconfigure(1, weight=1)
        not_govde.rowconfigure(0, weight=2)
        not_govde.rowconfigure(1, weight=1)
        not_govde.rowconfigure(2, weight=2)

        gecmis = ttk.LabelFrame(self.icerik, text="İşlem Bilgisi", padding=8)
        gecmis.pack(fill="x", padx=10, pady=6)
        self.lbl_gecmis = ttk.Label(gecmis, text="—")
        self.lbl_gecmis.pack(anchor="w")

    def _alan(self, parent, row, col, baslik, anahtar, width=20):
        import fatura_tema as ftema

        _py = ftema.form_pady(2)
        _ipady = ftema.form_ipady()
        ttk.Label(parent, text=baslik).grid(row=row, column=col, sticky="w", padx=4, pady=_py)
        e = ttk.Entry(parent, width=width)
        e.grid(row=row, column=col + 1, sticky="ew", padx=4, pady=_py, ipady=_ipady)
        self.girdiler[anahtar] = e
        return e

    def _tarih_alan(self, parent, row, col, baslik, anahtar, *, on_select=None, width=10):
        """Tarih entry + takvim butonu (gg.aa.yyyy)."""
        import fatura_tema as ftema

        _py = ftema.form_pady(2)
        _ipady = ftema.form_ipady()
        ttk.Label(parent, text=baslik).grid(row=row, column=col, sticky="w", padx=4, pady=_py)
        fr = ttk.Frame(parent)
        fr.grid(row=row, column=col + 1, sticky="ew", padx=4, pady=_py)
        e = ttk.Entry(fr, width=width)
        e.pack(side="left", ipady=_ipady)
        takvim_butonu(fr, e, on_select=on_select, text="📅", width=3)
        self.girdiler[anahtar] = e
        return e

    def _gecerlilik_gun_degisti(self, _event=None):
        """Geçerlilik günü → geçerlilik tarihi = teklif tarihi + gün."""
        if getattr(self, "_gecerlilik_senkron_kilit", False):
            return
        try:
            gun_metin = (self.girdiler["gecerlilik_gunu"].get() or "").strip()
            if gun_metin == "":
                return
            gun = int(gun_metin)
            if gun < 0:
                gun = 0
        except (ValueError, KeyError, tk.TclError):
            return
        try:
            bas = _parse_tarih(self.girdiler["teklif_tarihi"].get())
        except Exception:
            return
        self._gecerlilik_senkron_kilit = True
        try:
            self._giris_yaz("gecerlilik_tarihi", _tarih(bas + timedelta(days=gun)))
        finally:
            self._gecerlilik_senkron_kilit = False

    def _gecerlilik_tarih_degisti(self, _event=None):
        """Geçerlilik tarihi → gün = tarih − teklif tarihi."""
        if getattr(self, "_gecerlilik_senkron_kilit", False):
            return
        try:
            bas = _parse_tarih(self.girdiler["teklif_tarihi"].get())
            bit = _parse_tarih(self.girdiler["gecerlilik_tarihi"].get())
        except Exception:
            return
        gun = max(0, (bit - bas).days)
        self._gecerlilik_senkron_kilit = True
        try:
            self._giris_yaz("gecerlilik_gunu", str(gun))
        finally:
            self._gecerlilik_senkron_kilit = False

    def _aday_musteri_secenekleri(self) -> list[str]:
        """ADAY MÜŞTERİ grubundaki cariler."""
        isimler: list[str] = [""]
        self.aday_musteri_map = {}
        try:
            from database.cari_service import CariService
            from database.database import get_session
            from database.models.cari import Cari
            from sqlalchemy import or_, select

            grup = CariService.ADAY_MUSTERI_GRUP
            with get_session() as session:
                rows = list(
                    session.scalars(
                        select(Cari)
                        .where(
                            Cari.aktif.is_(True),
                            Cari.musteri_grubu == grup,
                            or_(Cari.is_deleted.is_(False), Cari.is_deleted.is_(None)),
                        )
                        .order_by(Cari.unvan)
                        .limit(500)
                    ).all()
                )
            for c in rows:
                unvan = (c.unvan or "").strip()
                etiket = f"{c.cari_kodu} - {unvan}" if c.cari_kodu else unvan
                if etiket and etiket not in isimler:
                    isimler.append(etiket)
                    self.aday_musteri_map[etiket] = c
                if unvan and unvan not in isimler:
                    isimler.append(unvan)
                    self.aday_musteri_map[unvan] = c
        except Exception:
            pass
        return isimler

    def _yeni_aday_musteri_ekle(self):
        """Yeni aday müşteri — Aday Müşteri grubu ile cari kartı."""
        self._yeni_musteri_ekle()
        w = self.girdiler.get("aday_musteri_adi")
        if w is not None:
            try:
                w.configure(values=self._aday_musteri_secenekleri())
            except tk.TclError:
                pass

    def _aday_musteri_yaz(self, deger: str | None) -> None:
        w = self.girdiler.get("aday_musteri_adi")
        if w is None:
            return
        metin = (deger or "").strip()
        try:
            degerler = list(w.cget("values") or ())
            if metin and metin not in degerler:
                degerler = list(degerler) + [metin]
                w.configure(values=degerler)
            w.set(metin)
        except tk.TclError:
            pass

    @staticmethod
    def _satis_temsilcisi_secenekleri() -> list[str]:
        """Aktif sistem kullanıcılarından satış temsilcisi adları (fatura ile aynı kaynak)."""
        isimler: list[str] = [""]
        try:
            from database.satis_personeli import aktif_satis_personelleri

            for p in aktif_satis_personelleri():
                ad = (p.get("ad_soyad") or "").strip()
                if ad and ad not in isimler:
                    isimler.append(ad)
        except Exception:
            pass
        return isimler

    def _satis_temsilcisi_yaz(self, deger: str | None) -> None:
        """Readonly Combobox'a değer yazar; listede yoksa geçici ekler."""
        w = self.girdiler.get("satis_temsilcisi")
        if w is None:
            return
        metin = (deger or "").strip()
        degerler = list(w.cget("values") or ())
        if metin and metin not in degerler:
            degerler.append(metin)
            w.configure(values=degerler)
        w.set(metin)

    def _teklif_kur_tarihi_al(self) -> date:
        """Kur için teklif tarihi; yoksa bugün."""
        try:
            return _parse_tarih(self.girdiler["teklif_tarihi"].get())
        except (ValueError, KeyError, tk.TclError):
            return date.today()

    def _teklif_kur_yaz(self, deger) -> None:
        w = self.girdiler.get("kur")
        if w is None:
            return
        try:
            d = Decimal(str(deger).replace(",", "."))
            metin = f"{d:f}".rstrip("0").rstrip(".") or "0"
            st = str(w.cget("state"))
            w.configure(state="normal")
            w.delete(0, "end")
            w.insert(0, metin)
            # disabled görünmez kalabiliyor → readonly kullan
            if st in ("disabled", "readonly"):
                w.configure(state="readonly")
        except (tk.TclError, InvalidOperation, ValueError):
            try:
                w.configure(state="normal")
                w.delete(0, "end")
                w.insert(0, "1")
            except tk.TclError:
                pass

    def _teklif_para_birimi_degisti(self, _event=None):
        pb = (self.para_birimi.get() or "TRY").upper()
        if pb == "TRY":
            self._teklif_kur_yaz(1)
            self._teklif_kur_kaynagi = "MANUEL"
            self._teklif_kur_turu = "effective_buying"
            try:
                self.kur_giris.configure(state="readonly")
                self.lbl_kur_kaynak.configure(text="TL · kur=1")
            except tk.TclError:
                pass
            self._toplam_guncelle()
            return
        try:
            self.kur_giris.configure(state="normal")
        except tk.TclError:
            pass
        self._teklif_tcmb_kur_yenile(sessiz=True)
        self._toplam_guncelle()

    def _teklif_tarih_veya_kur_degisti(self, _event=None):
        self._gecerlilik_gun_degisti(_event)
        self._termin_gun_degisti(_event)
        self._odeme_vade_manuel = False
        self._odeme_hesap_guncelle(_event)
        pb = (self.para_birimi.get() or "TRY").upper()
        if pb != "TRY":
            self._teklif_tcmb_kur_yenile(sessiz=True)
        if self._teklif_doviz_karsilik_pb_al():
            self._teklif_doviz_karsilik_tcmb(sessiz=True)

    def _teklif_kur_manuel(self, _event=None):
        pb = (self.para_birimi.get() or "TRY").upper()
        if pb == "TRY":
            return
        try:
            kur = _decimal(self.girdiler["kur"].get() or 0, "Kur")
            if kur <= 0:
                raise ValueError("Kur pozitif olmalıdır.")
            self._teklif_kur_kaynagi = "MANUEL"
            try:
                self.lbl_kur_kaynak.configure(text="Manuel kur")
            except tk.TclError:
                pass
            self._toplam_guncelle()
        except ValueError as hata:
            messagebox.showwarning("Kur", str(hata), parent=self)

    def _teklif_tcmb_kur_yenile(self, sessiz: bool = False, _event=None):
        """Günün (teklif tarihi) TCMB efektif alış kurunu alır (belge para birimi)."""
        from database.doviz_service import DovizService

        pb = (self.para_birimi.get() or "TRY").upper()
        if pb == "TRY":
            self._teklif_kur_yaz(1)
            self._teklif_kur_kaynagi = "MANUEL"
            return
        if pb not in ("USD", "EUR"):
            if not sessiz:
                messagebox.showwarning("Kur", "Yalnızca USD / EUR için TCMB kuru vardır.", parent=self)
            return
        kur_tarihi = self._teklif_kur_tarihi_al()
        self._teklif_kur_tarihi = kur_tarihi
        self._teklif_kur_turu = "effective_buying"
        try:
            kayitlar = DovizService.tcmb_kurlari_cek(kur_tarihi)
            hedef = next((k for k in kayitlar if k.get("currency_code") == pb), None)
            if not hedef:
                kur = DovizService.kur_degeri(kur_tarihi, pb, "effective_buying")
            else:
                kur = Decimal(
                    str(hedef.get("effective_buying") or hedef.get("forex_buying") or 0)
                )
                if kur <= 0:
                    kur = Decimal(str(hedef.get("forex_buying") or 0))
            if kur <= 0:
                raise ValueError(f"{pb} efektif alış kuru bulunamadı.")
            self._teklif_kur_yaz(kur)
            self._teklif_kur_kaynagi = "TCMB"
            tcmb_t = hedef.get("tcmb_tarih") if hedef else kur_tarihi
            etiket = f"TCMB Efektif Alış · {_tarih(tcmb_t) if tcmb_t else _tarih(kur_tarihi)}"
            try:
                self.lbl_kur_kaynak.configure(text=etiket)
            except tk.TclError:
                pass
            if not sessiz:
                messagebox.showinfo(
                    "TCMB Kur",
                    f"{pb} efektif alış: {kur}\nTarih: {_tarih(tcmb_t or kur_tarihi)}",
                    parent=self,
                )
            self._toplam_guncelle()
        except Exception as hata:
            try:
                kur = DovizService.kur_degeri(kur_tarihi, pb, "effective_buying")
                self._teklif_kur_yaz(kur)
                self._teklif_kur_kaynagi = "TCMB"
                try:
                    self.lbl_kur_kaynak.configure(
                        text=f"TCMB Efektif Alış · {_tarih(kur_tarihi)}"
                    )
                except tk.TclError:
                    pass
                self._toplam_guncelle()
                return
            except Exception:
                pass
            if not sessiz:
                messagebox.showerror("TCMB", str(hata), parent=self)

    def _teklif_doviz_karsilik_pb_al(self) -> str:
        try:
            pb = (self.doviz_karsilik_pb.get() or "").strip().upper()
        except (tk.TclError, AttributeError):
            return ""
        return pb if pb in ("USD", "EUR") else ""

    def _teklif_doviz_karsilik_kur_yaz(self, deger) -> None:
        w = getattr(self, "doviz_karsilik_kur", None)
        if w is None:
            return
        try:
            d = Decimal(str(deger).replace(",", "."))
            metin = f"{d:f}".rstrip("0").rstrip(".") or "0"
            w.configure(state="normal")
            w.delete(0, "end")
            w.insert(0, metin)
        except (tk.TclError, InvalidOperation, ValueError):
            pass

    def _teklif_doviz_karsilik_degisti(self, _event=None):
        pb = self._teklif_doviz_karsilik_pb_al()
        aktif = bool(pb)
        try:
            self.btn_doviz_karsilik_tcmb.configure(state="normal" if aktif else "disabled")
        except tk.TclError:
            pass
        if not aktif:
            try:
                self.doviz_karsilik_kur.configure(state="normal")
                self.doviz_karsilik_kur.delete(0, "end")
                # Alan görünür kalsın (readonly boş kutu)
                self.doviz_karsilik_kur.configure(state="readonly")
                self.lbl_doviz_karsilik_kaynak.configure(
                    text="TCMB Efektif Alış (USD/EUR seçin)"
                )
            except tk.TclError:
                pass
            self._toplam_guncelle()
            return
        try:
            self.doviz_karsilik_kur.configure(state="normal")
        except tk.TclError:
            pass
        self._teklif_doviz_karsilik_tcmb(sessiz=True)

    def _teklif_doviz_karsilik_kur_manuel(self, _event=None):
        if not self._teklif_doviz_karsilik_pb_al():
            return
        try:
            kur = _decimal(self.doviz_karsilik_kur.get() or 0, "Kur bilgisi")
            if kur <= 0:
                raise ValueError("Kur pozitif olmalıdır.")
            try:
                self.lbl_doviz_karsilik_kaynak.configure(text="Manuel kur")
            except tk.TclError:
                pass
            self._toplam_guncelle()
        except ValueError as hata:
            messagebox.showwarning("Kur Bilgisi", str(hata), parent=self)

    def _teklif_doviz_karsilik_tcmb(self, sessiz: bool = False, _event=None):
        """Döviz karşılığı için TCMB efektif alış kurunu getirir."""
        from database.doviz_service import DovizService

        pb = self._teklif_doviz_karsilik_pb_al()
        if not pb:
            if not sessiz:
                messagebox.showwarning("Kur Seçimi", "Önce USD veya EUR seçin.", parent=self)
            return
        kur_tarihi = self._teklif_kur_tarihi_al()
        try:
            kayitlar = DovizService.tcmb_kurlari_cek(kur_tarihi)
            hedef = next((k for k in kayitlar if k.get("currency_code") == pb), None)
            if not hedef:
                kur = DovizService.kur_degeri(kur_tarihi, pb, "effective_buying")
                tcmb_t = kur_tarihi
            else:
                kur = Decimal(
                    str(hedef.get("effective_buying") or hedef.get("forex_buying") or 0)
                )
                if kur <= 0:
                    kur = Decimal(str(hedef.get("forex_buying") or 0))
                tcmb_t = hedef.get("tcmb_tarih") or kur_tarihi
            if kur <= 0:
                raise ValueError(f"{pb} efektif alış kuru bulunamadı.")
            try:
                self.doviz_karsilik_kur.configure(state="normal")
            except tk.TclError:
                pass
            self._teklif_doviz_karsilik_kur_yaz(kur)
            try:
                self.lbl_doviz_karsilik_kaynak.configure(
                    text=f"TCMB Efektif Alış · {_tarih(tcmb_t)}"
                )
            except tk.TclError:
                pass
            if not sessiz:
                messagebox.showinfo(
                    "TCMB Kur",
                    f"{pb} efektif alış: {kur}\nTarih: {_tarih(tcmb_t)}",
                    parent=self,
                )
            self._toplam_guncelle()
        except Exception as hata:
            try:
                kur = DovizService.kur_degeri(kur_tarihi, pb, "effective_buying")
                try:
                    self.doviz_karsilik_kur.configure(state="normal")
                except tk.TclError:
                    pass
                self._teklif_doviz_karsilik_kur_yaz(kur)
                try:
                    self.lbl_doviz_karsilik_kaynak.configure(
                        text=f"TCMB Efektif Alış · {_tarih(kur_tarihi)}"
                    )
                except tk.TclError:
                    pass
                self._toplam_guncelle()
                return
            except Exception:
                pass
            if not sessiz:
                messagebox.showerror("TCMB", str(hata), parent=self)

    def _teklif_alt_ozet_kur(self) -> None:
        """Fatura ile aynı Brüt / İndirim / Masraf / Net sticky footer."""
        if getattr(self, "_teklif_alt_ozet", None):
            return
        import fatura_tema as ftema
        from ui_pencere import sticky_footer_layout

        refs = ftema.alt_ozet_cubugu(self, pack=False)
        self._teklif_alt_ozet = refs
        # Notların yanındaki Fiyat Analiz / Çalışma tamamen kaldır (üstte zaten var)
        # islem, analiz'in çocuğu olduğu için destroy öncesi buton çerçevesini yeniden kur
        analiz = refs.get("analiz")
        if analiz is not None:
            try:
                analiz.grid_forget()
                analiz.destroy()
            except tk.TclError:
                pass
        # Uzlaşılan fiyat butonları — toplamların (sağ) hemen solu
        btn_cer = tk.Frame(refs["kart"], bg=getattr(ftema, "BEYAZ", "#FFFFFF"))
        btn_cer.grid(row=0, column=1, sticky="ne", padx=(0, 12), pady=4)
        ftema.tk_buton(
            btn_cer, "Fiyatlara Yansıt", self._uzlasilan_fiyatlara_dagit_tikla, rol="onay"
        ).pack(side="top", fill="x", pady=2)
        ftema.tk_buton(
            btn_cer, "Dağıtımı Geri Al", self._uzlasilan_dagitim_geri_al, rol="ikincil"
        ).pack(side="top", fill="x", pady=2)
        refs["islem"] = btn_cer
        try:
            # Notlar → fiyat (toplam) sütununun başına kadar genişlesin
            refs["kart"].columnconfigure(0, weight=1, minsize=320)
            refs["kart"].columnconfigure(1, weight=0, minsize=0)
            refs["kart"].columnconfigure(2, weight=0)
            refs["kart"].rowconfigure(0, weight=1)
            refs["sol"].grid(row=0, column=0, sticky="nsew", padx=(0, 10))
            btn_cer.grid(row=0, column=1, sticky="ne", padx=(0, 12), pady=4)
            refs["sag"].grid(row=0, column=2, sticky="ne")
        except (tk.TclError, KeyError):
            pass
        # Footer not: genişlik doldur; yükseklik %25 artmış (5 → ~6 satır)
        not_w = refs["not_alani"]
        try:
            for cocuk in list(refs["sol"].winfo_children()):
                if isinstance(cocuk, tk.Text):
                    cocuk.pack_forget()
            not_w.configure(height=6, width=1, wrap="word")
            not_w.pack(fill="both", expand=True, pady=(2, 0))
        except tk.TclError:
            pass
        sticky_footer_layout(
            self,
            ust=getattr(self, "_teklif_toolbar", None),
            orta=getattr(self, "_kaydirma_alani", None),
            alt=refs["dis"],
        )
        degerler = refs["degerler"]
        self.teklif_toplam_degerleri = {
            "brut": degerler.get("brut"),
            "ara_toplam": degerler.get("ara_toplam"),
            "iskonto": degerler.get("iskonto"),
            "matrah": degerler.get("matrah"),
            "kdv": degerler.get("kdv"),
            "islem_turu": degerler.get("islem_turu"),
            "islem_oran": degerler.get("islem_oran"),
            "islem_tutar": degerler.get("islem_tutar"),
            "indirim": degerler.get("indirim"),
            "indirim_oran": degerler.get("indirim_oran"),
            "masraf": degerler.get("masraf"),
            "masraf_oran": degerler.get("masraf_oran"),
            "genel": degerler.get("genel"),
            "doviz": degerler.get("doviz"),
        }
        self._teklif_genel_islem_ui_bagla()

        # Footer not ↔ müşteri notu senkron
        try:
            not_w.insert("1.0", self.musteri_notu.get("1.0", "end-1c"))
        except tk.TclError:
            pass

        def _not_senkron(_event=None):
            try:
                self.musteri_notu.delete("1.0", "end")
                self.musteri_notu.insert("1.0", not_w.get("1.0", "end-1c"))
            except tk.TclError:
                pass

        not_w.bind("<KeyRelease>", _not_senkron)
        not_w.bind("<FocusOut>", _not_senkron)
        self._toplam_guncelle()

    def _teklif_genel_islem_ui_bagla(self) -> None:
        degerler = getattr(self, "teklif_toplam_degerleri", {}) or {}
        self._genel_ui_kilit = False
        if not hasattr(self, "_genel_islem_turu"):
            self._genel_islem_turu = ""
        if not hasattr(self, "_genel_islem_orani"):
            self._genel_islem_orani = Decimal("0")
        if not hasattr(self, "_genel_islem_tutari"):
            self._genel_islem_tutari = Decimal("0")
        if not hasattr(self, "_genel_islem_kaynak"):
            self._genel_islem_kaynak = "tutar"
        tur = degerler.get("islem_turu")
        if tur is not None:
            try:
                tur.bind("<<ComboboxSelected>>", self._teklif_islem_tur_degisti)
            except tk.TclError:
                pass
        oran = degerler.get("islem_oran")
        if isinstance(oran, ttk.Entry):
            oran.bind("<FocusOut>", lambda e: self._teklif_islem_alandan("oran"))
            oran.bind("<Return>", lambda e: self._teklif_islem_alandan("oran") or "break")
        tutar = degerler.get("islem_tutar")
        if isinstance(tutar, ttk.Entry):
            tutar.bind("<FocusOut>", lambda e: self._teklif_islem_alandan("tutar"))
            tutar.bind("<Return>", lambda e: self._teklif_islem_alandan("tutar") or "break")

    def _teklif_islem_alanlarini_yaz(self) -> None:
        if getattr(self, "_genel_ui_kilit", False):
            return
        self._genel_ui_kilit = True
        try:
            degerler = getattr(self, "teklif_toplam_degerleri", {}) or {}
            tur_w = degerler.get("islem_turu")
            tur = (getattr(self, "_genel_islem_turu", "") or "").upper()
            etiket = "—"
            if tur == "INDIRIM":
                etiket = "İndirim"
            elif tur == "MASRAF":
                etiket = "Masraf"
            if tur_w is not None:
                try:
                    tur_w.set(etiket)
                except tk.TclError:
                    pass
            oran_w = degerler.get("islem_oran")
            if isinstance(oran_w, ttk.Entry):
                try:
                    from database.fatura_genel_toplam_service import oran_yuvarla

                    d = oran_yuvarla(getattr(self, "_genel_islem_orani", 0) or 0)
                    metin = f"{d:f}".rstrip("0").rstrip(".").replace(".", ",") or "0"
                    if oran_w.get().strip() != metin:
                        oran_w.delete(0, "end")
                        oran_w.insert(0, metin)
                except tk.TclError:
                    pass
            tutar_w = degerler.get("islem_tutar")
            if isinstance(tutar_w, ttk.Entry):
                try:
                    t = getattr(self, "_genel_islem_tutari", 0) or 0
                    metin = f"{float(t):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    if tutar_w.get().strip() != metin:
                        tutar_w.delete(0, "end")
                        tutar_w.insert(0, metin)
                except tk.TclError:
                    pass
        finally:
            self._genel_ui_kilit = False

    def _teklif_islem_tur_degisti(self, _event=None):
        if getattr(self, "_genel_ui_kilit", False):
            return
        from database.fatura_genel_toplam_service import (
            ISLEM_INDIRIM,
            ISLEM_MASRAF,
            ISLEM_YOK,
            islem_uygula,
            kurus,
        )

        degerler = getattr(self, "teklif_toplam_degerleri", {}) or {}
        tur_w = degerler.get("islem_turu")
        etiket = ""
        try:
            etiket = (tur_w.get() if tur_w is not None else "") or ""
        except tk.TclError:
            etiket = ""
        if etiket.startswith("İnd"):
            tur = ISLEM_INDIRIM
        elif etiket.startswith("Mas"):
            tur = ISLEM_MASRAF
        else:
            tur = ISLEM_YOK
            self._genel_islem_orani = Decimal("0")
            self._genel_islem_tutari = Decimal("0")
        self._genel_islem_turu = tur
        brut = self._uzlasilan_brut_referans(
            getattr(self, "_fatura_satir_brut", None)
            or sum((self._uzlasilan_satir_genel(v) for v in self.satirlar), Decimal("0"))
        )
        try:
            sonuc = islem_uygula(
                brut,
                islem_turu=tur,
                islem_orani=getattr(self, "_genel_islem_orani", 0),
                islem_tutari=getattr(self, "_genel_islem_tutari", 0),
                kaynak=getattr(self, "_genel_islem_kaynak", "tutar") or "tutar",
            )
        except ValueError as hata:
            messagebox.showerror("İşlem", str(hata), parent=self)
            return
        self._genel_islem_turu = sonuc["islem_turu"]
        self._genel_islem_orani = sonuc["islem_orani"]
        self._genel_islem_tutari = sonuc["islem_tutari"]
        self._uzlasilan_tutar = sonuc["net_toplam"]
        self._uzlasilan_ui_kilit = True
        try:
            self._uzlasilan_tutar_yaz(sonuc["net_toplam"])
        finally:
            self._uzlasilan_ui_kilit = False
        self._teklif_islem_alanlarini_yaz()
        self._toplam_guncelle()

    def _teklif_islem_alandan(self, kaynak: str):
        if getattr(self, "_genel_ui_kilit", False):
            return
        from database.fatura_genel_toplam_service import islem_uygula, islem_turunu_normalize, kurus

        degerler = getattr(self, "teklif_toplam_degerleri", {}) or {}
        tur = islem_turunu_normalize(getattr(self, "_genel_islem_turu", ""))
        if not tur:
            tur = "INDIRIM"
        brut = self._uzlasilan_brut_referans(
            getattr(self, "_fatura_satir_brut", None)
            or sum((self._uzlasilan_satir_genel(v) for v in self.satirlar), Decimal("0"))
        )
        try:
            if kaynak == "oran":
                ham = (degerler.get("islem_oran").get() if degerler.get("islem_oran") else "0") or "0"
                oran = _decimal(ham, "İşlem oranı")
                sonuc = islem_uygula(brut, islem_turu=tur, islem_orani=oran, kaynak="oran")
            else:
                ham = (degerler.get("islem_tutar").get() if degerler.get("islem_tutar") else "0") or "0"
                tutar = kurus(_decimal(ham, "İşlem tutarı"))
                sonuc = islem_uygula(brut, islem_turu=tur, islem_tutari=tutar, kaynak="tutar")
        except ValueError as hata:
            messagebox.showerror("İşlem", str(hata), parent=self)
            self._teklif_islem_alanlarini_yaz()
            return "break"
        self._genel_islem_kaynak = kaynak
        self._genel_islem_turu = sonuc["islem_turu"]
        self._genel_islem_orani = sonuc["islem_orani"]
        self._genel_islem_tutari = sonuc["islem_tutari"]
        self._uzlasilan_tutar = sonuc["net_toplam"]
        self._uzlasilan_ui_kilit = True
        try:
            self._uzlasilan_tutar_yaz(sonuc["net_toplam"])
        finally:
            self._uzlasilan_ui_kilit = False
        self._teklif_islem_alanlarini_yaz()
        self._toplam_guncelle()
        return "break"

    def _toplam_etiket_yaz(self, anahtar: str, tutar) -> None:
        w = (getattr(self, "teklif_toplam_degerleri", {}) or {}).get(anahtar)
        if w is None or not hasattr(w, "configure"):
            return
        try:
            w.configure(text=_para_tl(tutar))
        except tk.TclError:
            pass

    def _toplam_oran_yaz(self, anahtar: str, oran) -> None:
        w = (getattr(self, "teklif_toplam_degerleri", {}) or {}).get(f"{anahtar}_oran")
        if w is None:
            return
        try:
            from database.fatura_genel_toplam_service import oran_yuvarla

            o = oran_yuvarla(oran or 0)
            metin = f"%{float(o):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            w.configure(text=metin)
        except Exception:
            try:
                w.configure(text="%0,00")
            except tk.TclError:
                pass

    def _uzlasilan_tutar_oku(self):
        w = getattr(self, "_uzlasilan_tutar_entry", None)
        if w is None:
            return getattr(self, "_uzlasilan_tutar", None)
        try:
            ham = (w.get() or "").strip().replace("TL", "").replace("tl", "").strip()
        except tk.TclError:
            return getattr(self, "_uzlasilan_tutar", None)
        if not ham:
            return None
        from database.fatura_genel_toplam_service import kurus

        return kurus(_decimal(ham, "Uzlaşılan tutar"))

    def _uzlasilan_tutar_yaz(self, tutar) -> None:
        w = getattr(self, "_uzlasilan_tutar_entry", None)
        if w is None:
            return
        try:
            metin = "" if tutar is None else _para(tutar)
            if w.get().strip() == metin:
                return
            w.delete(0, "end")
            if metin:
                w.insert(0, metin)
        except tk.TclError:
            pass

    def _uzlasilan_tutar_degisti(self, _event=None):
        if getattr(self, "_teklif_yukleniyor", False) or getattr(self, "_uzlasilan_ui_kilit", False):
            return "break"
        try:
            self._uzlasilan_tutar = self._uzlasilan_tutar_oku()
        except ValueError as hata:
            messagebox.showerror("Uzlaşılan tutar", str(hata), parent=self)
            return "break"
        self._toplam_guncelle()
        return "break"

    def _uzlasilan_tutar_canli(self, _event=None):
        if getattr(self, "_teklif_yukleniyor", False) or getattr(self, "_uzlasilan_ui_kilit", False):
            return
        try:
            self._uzlasilan_tutar = self._uzlasilan_tutar_oku()
        except ValueError:
            return
        try:
            self._toplam_guncelle()
        except Exception:
            pass

    def _uzlasilan_satir_genel(self, veri) -> Decimal:
        from database.fatura_genel_toplam_service import kurus
        from database.teklif_pricing_service import net_iskontolu

        miktar = _decimal(veri.get("miktar", 0))
        # Dağıtım sırasında birim_satis_fiyati güncellenir; yoksa teklif_fiyati
        if veri.get("birim_satis_fiyati") is not None:
            liste = _decimal(veri.get("birim_satis_fiyati", 0))
        else:
            liste = _decimal(veri.get("teklif_fiyati", 0))
        net = _decimal(veri.get("net_birim_fiyat", 0))
        # Liste değiştiyse net'i iskontodan yeniden hesapla (dağıtım döngüsü)
        if veri.get("birim_satis_fiyati") is not None:
            net = net_iskontolu(
                liste,
                veri.get("iskonto_orani", 0),
                veri.get("iskonto_orani_2", 0),
                veri.get("iskonto_orani_3", 0),
            )
        elif net <= 0:
            net = net_iskontolu(
                liste,
                veri.get("iskonto_orani", 0),
                veri.get("iskonto_orani_2", 0),
                veri.get("iskonto_orani_3", 0),
            )
        kdv_o = _decimal(veri.get("kdv_orani", 20))
        ara = kurus(net * miktar)
        return kurus(ara + kurus(ara * kdv_o / Decimal("100")))

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
                "teklif_fiyati": Decimal(str(v.get("teklif_fiyati") or 0)),
                "net_birim_fiyat": Decimal(str(v.get("net_birim_fiyat") or 0)),
                "satir_toplam": Decimal(str(v.get("satir_toplam") or 0)),
                "is_manual_price": bool(v.get("is_manual_price")),
            }
            for v in self.satirlar
        ]
        self._uzlasilan_snapshot_brut = kurus(
            sum((self._uzlasilan_satir_genel(v) for v in self.satirlar), Decimal("0"))
        )

    def _uzlasilan_satir_fiyat_senkron(self, veri: dict) -> None:
        """Dağıtım sonrası birim_satis_fiyati → teklif alanları."""
        from database.fatura_genel_toplam_service import kurus
        from database.teklif_pricing_service import kar_metrikleri, net_iskontolu

        fiyat = Decimal(str(veri.get("birim_satis_fiyati") or veri.get("teklif_fiyati") or 0))
        miktar = _decimal(veri.get("miktar", 1))
        i1 = veri.get("iskonto_orani", 0)
        i2 = veri.get("iskonto_orani_2", 0)
        i3 = veri.get("iskonto_orani_3", 0)
        net = net_iskontolu(fiyat, i1, i2, i3)
        kdv_o = _decimal(veri.get("kdv_orani", 20))
        ara = kurus(net * miktar)
        veri["teklif_fiyati"] = fiyat
        veri["birim_satis_fiyati"] = fiyat
        veri["manual_offer_unit_price"] = fiyat
        veri["final_offer_unit_price"] = fiyat
        veri["net_birim_fiyat"] = net
        veri["satir_toplam"] = kurus(ara + kurus(ara * kdv_o / Decimal("100")))
        veri["is_manual_price"] = True
        mal = _decimal(veri.get("birim_maliyet", 0))
        oran, marj = kar_metrikleri(net, mal)
        veri["kar_orani"] = oran
        veri["gercek_marj"] = marj

    def _uzlasilan_fiyatlara_dagit(self) -> None:
        from database.fatura_genel_toplam_service import kurus
        from database.uzlasilan_tutar_service import uzlasilan_fiyatlara_dagit

        hedef = getattr(self, "_uzlasilan_tutar", None)
        if hedef is None or not self.satirlar:
            self._toplam_guncelle()
            return
        for v in self.satirlar:
            v["birim_satis_fiyati"] = Decimal(str(v.get("teklif_fiyati") or 0))
        onceki = kurus(sum((self._uzlasilan_satir_genel(v) for v in self.satirlar), Decimal("0")))
        hedef_k = kurus(hedef)
        if onceki == hedef_k:
            self._toplam_guncelle()
            return
        self._uzlasilan_fiyat_snapshot_al()
        sonuc = uzlasilan_fiyatlara_dagit(
            self.satirlar,
            hedef_k,
            satir_genel_fn=self._uzlasilan_satir_genel,
        )
        if sonuc.get("degisti"):
            for v in self.satirlar:
                self._uzlasilan_satir_fiyat_senkron(v)
            self._satir_tablo_yenile()
        self._toplam_guncelle()

    def _uzlasilan_fiyatlara_dagit_tikla(self, _event=None):
        try:
            self._uzlasilan_tutar = self._uzlasilan_tutar_oku()
        except ValueError as hata:
            messagebox.showerror("Uzlaşılan tutar", str(hata), parent=self)
            return "break"
        from database.fatura_genel_toplam_service import kurus

        hedef = self._uzlasilan_tutar
        if hedef is None:
            hedef = getattr(self, "_hesaplanan_genel", None)
        if hedef is None:
            messagebox.showinfo(
                "Fiyatları Net'e uydur",
                "Önce Uzlaşılan Tutar (Net hedef) girin.",
                parent=self,
            )
            return "break"
        if not self.satirlar:
            messagebox.showwarning(
                "Fiyatları Net'e uydur", "Önce teklif satırı ekleyin.", parent=self
            )
            return "break"
        onceki = kurus(sum((self._uzlasilan_satir_genel(v) for v in self.satirlar), Decimal("0")))
        hedef_k = kurus(hedef)
        if onceki == hedef_k:
            messagebox.showinfo(
                "Fiyatları Net'e uydur",
                "Satır toplamı zaten Net Toplam ile aynı — fiyatlar tutarlı.",
                parent=self,
            )
            return "break"
        if not messagebox.askyesno(
            "Fiyatları Net'e uydur",
            f"Orijinal Brüt {_para_tl(onceki)} sabit kalır.\n"
            f"Birim fiyatlar Net {_para_tl(hedef_k)} olacak şekilde orantılı yenilenir.\n\n"
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
            "Fiyatları Net'e uydur",
            f"{len(self.satirlar)} satır güncellendi.\n"
            f"Brüt (sabit): {_para_tl(brut_ref)}\n"
            f"Net: {_para_tl(hedef_k)}\n"
            f"Fark İndirim/Masraf satırında görünür.",
            parent=self,
        )
        return "break"

    def _uzlasilan_dagitim_geri_al(self, _event=None):
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
            veri["teklif_fiyati"] = eski["teklif_fiyati"]
            veri["birim_satis_fiyati"] = eski["teklif_fiyati"]
            veri["net_birim_fiyat"] = eski["net_birim_fiyat"]
            veri["satir_toplam"] = eski["satir_toplam"]
            veri["is_manual_price"] = eski.get("is_manual_price", False)
        self._uzlasilan_fiyat_snapshot = None
        self._uzlasilan_snapshot_brut = None
        self._satir_tablo_yenile()
        self._toplam_guncelle()
        return "break"

    def _secili_maliyet_kaynagi(self) -> str:
        etiket = self.maliyet_kaynak.get()
        for kod in self._maliyet_kaynak_kodlari:
            if MALIYET_KAYNAK_ETIKET.get(kod, kod) == etiket or kod == etiket:
                return kod
        return "SON_ALIS"

    def _termin_manuel_isaretle(self, _e=None):
        self._delivery_term_manual = True

    def _odeme_islem_tarihi(self) -> date:
        try:
            return _parse_tarih(self.girdiler["teklif_tarihi"].get())
        except Exception:
            return date.today()

    def _odeme_secilen_sekil(self) -> str:
        for s in ODEME_SEKILLERI:
            var = self._odeme_secim.get(s)
            if var is not None and var.get():
                return s
        return ""

    def _odeme_secilen_sekiller(self) -> list[str]:
        s = self._odeme_secilen_sekil()
        return [s] if s else []

    def _odeme_tek_sec(self, sekil: str) -> None:
        """Tek seçim: işaretlenen dışındaki tüm tikleri kaldır."""
        if getattr(self, "_odeme_secim_kilit", False):
            return
        self._odeme_secim_kilit = True
        try:
            secildi = bool(self._odeme_secim[sekil].get())
            for s, var in self._odeme_secim.items():
                var.set(s == sekil if secildi else False)
            # Hiçbiri kalmasın istemiyorsak son tiki koru
            if not secildi:
                self._odeme_secim[sekil].set(True)
        finally:
            self._odeme_secim_kilit = False
        self._odeme_vade_manuel = False
        self._odeme_secim_degisti()

    def _odeme_secim_degisti(self, _e=None):
        sekil = self._odeme_secilen_sekil()
        try:
            self.odeme_nakit_turu.configure(state="readonly" if sekil == NAKIT else "disabled")
        except tk.TclError:
            pass
        try:
            self.odeme_taksit.configure(
                state="readonly" if sekil == KREDI_KARTI else "disabled"
            )
        except tk.TclError:
            pass
        cek_senet = sekil in ("Çek", "Senet")
        acik = sekil == "Açık Hesap"
        try:
            # Çek/Senet: vade elle, gün otomatik (readonly)
            # Açık hesap: gün elle, vade otomatik
            # Nakit/KK: ikisi de otomatik (readonly)
            if cek_senet:
                self.odeme_vade_gun.configure(state="readonly")
                self.odeme_vade_tarihi.configure(state="normal")
            elif acik:
                self.odeme_vade_gun.configure(state="normal")
                self.odeme_vade_tarihi.configure(state="readonly")
            else:
                self.odeme_vade_gun.configure(state="readonly")
                self.odeme_vade_tarihi.configure(state="readonly")
        except tk.TclError:
            pass
        self._odeme_hesap_guncelle()

    def _odeme_hesap_guncelle(self, _e=None):
        sekil = self._odeme_secilen_sekil()
        if not sekil:
            return
        tarih = self._odeme_islem_tarihi()
        if sekil in ("Çek", "Senet"):
            # Vade yazılmışsa günden hesapla; yoksa günü boş bırakma (mevcut vade)
            self._odeme_vade_tarih_yazildi()
            return
        if sekil == "Açık Hesap":
            gun_metin = (self.odeme_vade_gun.get() or "").strip()
            try:
                gun = int(gun_metin) if gun_metin else 0
            except ValueError:
                gun = 0
            kalem = kalem_hesapla(sekil, islem_tarihi=tarih, gun=gun)
        elif sekil == KREDI_KARTI:
            kalem = kalem_hesapla(
                KREDI_KARTI,
                islem_tarihi=tarih,
                taksit=kk_taksit_sayisi(self.odeme_taksit.get()) or 1,
            )
        else:
            kalem = kalem_hesapla(
                NAKIT,
                islem_tarihi=tarih,
                alt=(self.odeme_nakit_turu.get() or "Havale"),
            )
        try:
            once_gun = str(self.odeme_vade_gun.cget("state"))
            once_vade = str(self.odeme_vade_tarihi.cget("state"))
            self.odeme_vade_gun.configure(state="normal")
            self.odeme_vade_tarihi.configure(state="normal")
            self.odeme_vade_gun.delete(0, "end")
            self.odeme_vade_gun.insert(0, str(int(kalem.get("gun") or 0)))
            self.odeme_vade_tarihi.delete(0, "end")
            self.odeme_vade_tarihi.insert(0, _tarih(kalem.get("vade")))
            self.odeme_vade_gun.configure(state=once_gun if once_gun != "disabled" else "readonly")
            self.odeme_vade_tarihi.configure(
                state=once_vade if once_vade != "disabled" else "readonly"
            )
        except tk.TclError:
            pass

    def _odeme_vade_manuel_isaretle(self, _e=None):
        self._odeme_vade_manuel = True

    def _odeme_vade_gun_degisti(self, _e=None):
        """Açık hesap: gün → vade."""
        if self._odeme_secilen_sekil() != "Açık Hesap":
            return
        try:
            tarih = self._odeme_islem_tarihi()
            gun = int((self.odeme_vade_gun.get() or "0").strip() or 0)
            vade = kalem_hesapla("Açık Hesap", islem_tarihi=tarih, gun=gun)["vade"]
            st = str(self.odeme_vade_tarihi.cget("state"))
            self.odeme_vade_tarihi.configure(state="normal")
            self.odeme_vade_tarihi.delete(0, "end")
            self.odeme_vade_tarihi.insert(0, _tarih(vade))
            self.odeme_vade_tarihi.configure(state=st)
        except Exception:
            pass

    def _odeme_vade_tarih_yazildi(self, _e=None):
        """Çek/Senet: vade tarihinden gün = vade − teklif tarihi."""
        if self._odeme_secilen_sekil() not in ("Çek", "Senet"):
            return
        try:
            tarih = self._odeme_islem_tarihi()
            vade = _parse_tarih(self.odeme_vade_tarihi.get())
            gun = max(0, (vade - tarih).days)
            self.odeme_vade_gun.configure(state="normal")
            self.odeme_vade_gun.delete(0, "end")
            self.odeme_vade_gun.insert(0, str(gun))
            self.odeme_vade_gun.configure(state="readonly")
            self._odeme_vade_manuel = True
        except Exception:
            pass

    def _odeme_vade_tarih_degisti(self, _e=None):
        self._odeme_vade_tarih_yazildi(_e)

    def _odeme_kalemleri_uret(self) -> list[dict[str, Any]]:
        tarih = self._odeme_islem_tarihi()
        sekil = self._odeme_secilen_sekil()
        if not sekil:
            return []
        gun_metin = (self.odeme_vade_gun.get() or "").strip()
        try:
            gun = int(gun_metin) if gun_metin else None
        except ValueError as exc:
            raise ValueError("Ödeme vade günü geçerli bir sayı olmalıdır.") from exc
        vade = None
        vade_metin = (self.odeme_vade_tarihi.get() or "").strip()
        if vade_metin:
            try:
                vade = _parse_tarih(vade_metin)
            except ValueError as exc:
                raise ValueError("Ödeme vadesi geçerli bir tarih olmalıdır (gg.aa.yyyy).") from exc
        if sekil == NAKIT:
            return [
                kalem_hesapla(
                    NAKIT,
                    islem_tarihi=tarih,
                    alt=(self.odeme_nakit_turu.get() or "Havale"),
                )
            ]
        if sekil == KREDI_KARTI:
            return [
                kalem_hesapla(
                    KREDI_KARTI,
                    islem_tarihi=tarih,
                    taksit=kk_taksit_sayisi(self.odeme_taksit.get()) or 1,
                )
            ]
        # Çek / Senet: vade zorunlu → günden hesap
        if sekil in ("Çek", "Senet"):
            if vade is None:
                raise ValueError(f"{sekil} için ödeme vadesi (üzerindeki tarih) girilmelidir.")
            return [
                kalem_hesapla(
                    sekil,
                    islem_tarihi=tarih,
                    vade=vade,
                    vade_elle=True,
                )
            ]
        return [
            kalem_hesapla(
                sekil,
                islem_tarihi=tarih,
                gun=gun,
                vade=vade,
            )
        ]

    def _odeme_alanlari_oku(self) -> dict[str, Any]:
        kalemler = self._odeme_kalemleri_uret()
        ozet = odeme_ozet_listeden(kalemler)
        ilk = kalemler[0] if kalemler else {}
        return {
            "odeme_sekli": ozet or None,
            "odeme_taksit": ilk.get("taksit"),
            "odeme_vade_gun": ilk.get("gun"),
            "odeme_vade_tarihi": ilk.get("vade") if isinstance(ilk.get("vade"), date) else None,
            "odeme_nakit_turu": ilk.get("alt") if ilk.get("sekil") == NAKIT else None,
            "odeme_json": kalemleri_serileştir(kalemler) if kalemler else None,
            "odeme_ozet": ozet,
        }

    def _odeme_alanlari_yaz(self, teklif_veya_dict: Any) -> None:
        if isinstance(teklif_veya_dict, dict):
            veri = teklif_veya_dict
            kalemler = veri.get("kalemler") or kalemleri_yukle(veri.get("odeme_json"))
        else:
            veri = kayittan_odeme(teklif_veya_dict)
            kalemler = list(veri.get("kalemler") or [])
        if not kalemler:
            sekil = odeme_sekil_normalize(veri.get("odeme_sekli"))
            if sekil:
                kalemler = [
                    {
                        "sekil": sekil,
                        "alt": veri.get("odeme_nakit_turu"),
                        "taksit": veri.get("odeme_taksit"),
                        "gun": veri.get("odeme_vade_gun"),
                        "vade": veri.get("odeme_vade_tarihi"),
                    }
                ]
        # Tek seçim — ilk kalem
        hedef = (kalemler[0].get("sekil") or NAKIT) if kalemler else NAKIT
        if hedef not in ODEME_SEKILLERI:
            hedef = odeme_sekil_normalize(hedef) or NAKIT
        self._odeme_secim_kilit = True
        try:
            for s, var in self._odeme_secim.items():
                var.set(s == hedef)
        finally:
            self._odeme_secim_kilit = False
        nakit = kalemler[0] if kalemler and kalemler[0].get("sekil") == NAKIT else None
        if nakit and nakit.get("alt") in NAKIT_ALT:
            self.odeme_nakit_turu.set(nakit["alt"])
        elif hedef == NAKIT:
            self.odeme_nakit_turu.set("Havale")
        kk = kalemler[0] if kalemler and kalemler[0].get("sekil") == KREDI_KARTI else None
        self.odeme_taksit.set(kk_taksit_etiket(kk.get("taksit") if kk else 1))
        kaynak = kalemler[0] if kalemler else {}
        self._odeme_vade_manuel = hedef in ("Çek", "Senet")
        try:
            self.odeme_vade_gun.configure(state="normal")
            self.odeme_vade_tarihi.configure(state="normal")
        except tk.TclError:
            pass
        self.odeme_vade_gun.delete(0, "end")
        if kaynak.get("gun") not in (None, ""):
            self.odeme_vade_gun.insert(0, str(int(kaynak["gun"])))
        self.odeme_vade_tarihi.delete(0, "end")
        if kaynak.get("vade"):
            self.odeme_vade_tarihi.insert(0, _tarih(kaynak["vade"]))
        self._odeme_secim_degisti()
    def _termin_gun_degisti(self, _e=None):
        if self._delivery_term_manual:
            return
        try:
            tarih = _parse_tarih(self.girdiler["teklif_tarihi"].get())
            gun_metin = (self.girdiler["delivery_term_days"].get() or "").strip()
            if not gun_metin:
                return
            gun = int(gun_metin)
            tahmini = tahmini_teslim_hesapla(tarih, gun)
            if tahmini:
                e = self.girdiler["estimated_delivery_date"]
                e.delete(0, "end")
                e.insert(0, _tarih(tahmini))
        except Exception:
            pass

    def _maliyet_kaynak_degisti(self, _e=None):
        if not self.satirlar:
            return
        if not messagebox.askyesno(
            "Maliyet Kaynağı",
            "Maliyet kaynağı değişti. Tüm satır alış maliyetleri yeniden çekilsin mi?",
            parent=self,
        ):
            return
        self._alis_fiyatlari_yenile(onayli=True)

    def _alis_fiyatlari_yenile(self, onayli: bool = False):
        if not self.satirlar:
            return
        if not onayli and not messagebox.askyesno(
            "Alış Fiyatları",
            "Güncel alış fiyatları tüm satırlar için yenilensin mi?",
            parent=self,
        ):
            return
        depo = self.girdiler["depo"].get().strip() or "ANA DEPO"
        kay = self._secili_maliyet_kaynagi()
        uyarilar = []
        for s in self.satirlar:
            snap = maliyet_getir(s.get("urun_kodu") or "", depo, kay)
            s["birim_maliyet"] = snap.birim_maliyet
            s["maliyet_kaynagi"] = snap.maliyet_kaynagi
            s["purchase_unit_price"] = snap.purchase_unit_price
            s["purchase_currency"] = snap.purchase_currency
            s["purchase_exchange_rate"] = snap.purchase_exchange_rate
            s["purchase_unit_price_base"] = snap.purchase_unit_price_base
            s["purchase_total_cost"] = (
                snap.purchase_unit_price_base * _decimal(s.get("miktar", 0))
            ).quantize(Decimal("0.01"))
            s["cost_source_date"] = snap.cost_source_date
            s["supplier_id"] = snap.supplier_id
            s["supplier_name"] = snap.supplier_name
            s["maliyet_hesap_zamani"] = snap.maliyet_hesap_zamani
            if snap.uyari or snap.birim_maliyet <= 0:
                uyarilar.append(f"{s.get('urun_kodu')}: {snap.uyari or 'Maliyet 0'}")
        self._satir_tablo_yenile()
        self._toplam_guncelle()
        if uyarilar:
            messagebox.showwarning(
                "Maliyet",
                "Bazı satırlarda maliyet eksik:\n" + "\n".join(uyarilar[:12]),
                parent=self,
            )

    def _giris_yaz(self, anahtar: str, deger: str, *, readonly: bool = False) -> None:
        """Entry'ye güvenli yaz (readonly alanlarda geçici normal)."""
        w = self.girdiler.get(anahtar)
        if w is None:
            return
        try:
            w.configure(state="normal")
            w.delete(0, "end")
            if deger is not None and str(deger) != "":
                w.insert(0, str(deger))
            if readonly:
                w.configure(state="readonly")
        except tk.TclError:
            pass

    def _yeni_teklif_no_al(self) -> str:
        try:
            QuoteService.schema_hazirla()
        except Exception:
            pass
        try:
            no = (QuoteService.teklif_no() or "").strip()
            if no:
                return no
        except Exception:
            pass
        return f"TKF-{date.today():%Y%m%d}-01"

    def _yeni_varsayilan(self):
        bugun = date.today()
        # Önce tarih/no — DB hatası olsa bile form boş kalmasın
        self._giris_yaz("teklif_tarihi", _tarih(bugun))
        self._giris_yaz("gecerlilik_tarihi", _tarih(bugun + timedelta(days=30)))
        self._giris_yaz("gecerlilik_gunu", "30")
        self._giris_yaz("teklif_no", self._yeni_teklif_no_al(), readonly=True)
        try:
            self.para_birimi.set("TRY")
        except tk.TclError:
            pass
        self._teklif_kur_yaz(1)
        try:
            self.kur_giris.configure(state="readonly")
            self.lbl_kur_kaynak.configure(text="TL · kur=1")
        except tk.TclError:
            pass
        self._teklif_kur_kaynagi = "MANUEL"
        self._teklif_kur_turu = "effective_buying"
        self._teklif_kur_tarihi = bugun
        try:
            self.doviz_karsilik_pb.set("—")
            self.doviz_karsilik_kur.configure(state="normal")
            self.doviz_karsilik_kur.delete(0, "end")
            self.doviz_karsilik_kur.configure(state="readonly")
            self.btn_doviz_karsilik_tcmb.configure(state="disabled")
            self.lbl_doviz_karsilik_kaynak.configure(
                text="TCMB Efektif Alış (USD/EUR seçin)"
            )
        except (tk.TclError, AttributeError):
            pass
        self._giris_yaz("depo", "ANA DEPO")
        self._giris_yaz("delivery_term_days", "7")
        self._giris_yaz("estimated_delivery_date", _tarih(bugun + timedelta(days=7)))
        # Varsayılan maliyet: Son Alış Faturası
        try:
            self.maliyet_kaynak.set(MALIYET_KAYNAK_ETIKET.get("SON_ALIS", "Son Alış Faturası"))
        except (tk.TclError, AttributeError):
            pass
        if oturum.ad_soyad:
            try:
                self._satis_temsilcisi_yaz(oturum.ad_soyad)
            except Exception:
                pass
        self._rozet("TASLAK")
        try:
            self._meta_guncelle()
        except Exception:
            pass
        try:
            self._toplam_guncelle()
        except Exception:
            pass
        try:
            self._fiyat_ozet_guncelle()
        except Exception:
            pass
        # Eksik kaldıysa bir kez daha dene (UI settle)
        self.after(50, self._teklif_no_tarih_garanti)

    def _teklif_no_tarih_garanti(self) -> None:
        """Yeni teklifte no ve tarih boşsa doldur."""
        if getattr(self, "teklif", None) is not None:
            return
        bugun = date.today()
        try:
            no = (self.girdiler["teklif_no"].get() or "").strip()
        except (tk.TclError, KeyError):
            no = ""
        if not no:
            self._giris_yaz("teklif_no", self._yeni_teklif_no_al(), readonly=True)
        else:
            try:
                self.girdiler["teklif_no"].configure(state="readonly")
            except tk.TclError:
                pass
        try:
            tarih = (self.girdiler["teklif_tarihi"].get() or "").strip()
        except (tk.TclError, KeyError):
            tarih = ""
        if not tarih:
            self._giris_yaz("teklif_tarihi", _tarih(bugun))
        try:
            gecer = (self.girdiler["gecerlilik_tarihi"].get() or "").strip()
        except (tk.TclError, KeyError):
            gecer = ""
        if not gecer:
            self._giris_yaz("gecerlilik_tarihi", _tarih(bugun + timedelta(days=30)))
        try:
            gun = (self.girdiler["gecerlilik_gunu"].get() or "").strip()
        except (tk.TclError, KeyError):
            gun = ""
        if not gun:
            self._giris_yaz("gecerlilik_gunu", "30")
        try:
            self._meta_guncelle()
        except Exception:
            pass

    def _doldur(self):
        t = self.teklif
        assert t
        self._teklif_yukleniyor = True
        try:
            self._doldur_govde(t)
        finally:
            self._teklif_yukleniyor = False

    def _doldur_govde(self, t):
        for alan, deger in (
            ("teklif_no", QuoteService.gosterim_no(t)),
            ("teklif_tarihi", _tarih(t.teklif_tarihi)),
            ("gecerlilik_tarihi", _tarih(t.gecerlilik_tarihi)),
            ("gecerlilik_gunu", str(t.gecerlilik_gunu or "")),
            ("konu", t.konu or ""),
            ("referans_no", t.referans_no or ""),
            ("musteri_yetkilisi", t.musteri_yetkilisi or ""),
            ("musteri_telefon", t.musteri_telefon or ""),
            ("musteri_email", t.musteri_email or ""),
            ("teslim_suresi", t.teslim_suresi or ""),
            ("depo", t.depo or "ANA DEPO"),
            ("proje", t.proje or ""),
            (
                "delivery_term_days",
                str(t.delivery_term_days) if t.delivery_term_days is not None else "",
            ),
            (
                "estimated_delivery_date",
                _tarih(t.estimated_delivery_date or t.tahmini_termin),
            ),
            ("delivery_term_note", t.delivery_term_note or ""),
        ):
            self._giris_yaz(alan, deger, readonly=(alan == "teklif_no"))
        self._odeme_alanlari_yaz(t)
        self._aday_musteri_yaz(t.aday_musteri_adi or "")
        self._satis_temsilcisi_yaz(t.satis_temsilcisi or "")
        try:
            self.girdiler["teklif_no"].configure(state="readonly")
        except tk.TclError:
            pass
        pb = (t.para_birimi or "TRY").upper()
        self.para_birimi.set(pb if pb in ("TRY", "USD", "EUR") else "TRY")
        self._teklif_kur_turu = getattr(t, "kur_turu", None) or "effective_buying"
        self._teklif_kur_tarihi = getattr(t, "kur_tarihi", None) or t.teklif_tarihi or date.today()
        self._teklif_kur_yaz(t.kur or 1)
        if pb == "TRY":
            try:
                self.kur_giris.configure(state="readonly")
                self.lbl_kur_kaynak.configure(text="TL · kur=1")
            except tk.TclError:
                pass
            self._teklif_kur_kaynagi = "MANUEL"
        else:
            try:
                self.kur_giris.configure(state="normal")
                self.lbl_kur_kaynak.configure(
                    text=f"Kayıtlı · {self._teklif_kur_turu} · {_tarih(self._teklif_kur_tarihi)}"
                )
            except tk.TclError:
                pass
            kt = getattr(self, "_teklif_kur_turu", "") or ""
            self._teklif_kur_kaynagi = (
                "TCMB" if str(kt).startswith(("effective_", "forex_")) else "MANUEL"
            )
        self._delivery_term_manual = bool(getattr(t, "delivery_term_manual", False))
        if t.delivery_term_type:
            self.termin_turu.set(t.delivery_term_type)
        kaynak = getattr(t, "cost_source", None) or "SON_ALIS"
        self.maliyet_kaynak.set(MALIYET_KAYNAK_ETIKET.get(kaynak, kaynak))
        for anahtar, deger in (
            ("profit_rate", t.profit_rate),
            ("fixed_profit_amount", t.fixed_profit_amount),
            ("customer_expense_amount", t.customer_expense_amount),
            ("internal_expense_amount", t.internal_expense_amount),
        ):
            e = self.fiyat_girdiler[anahtar]
            e.delete(0, "end")
            e.insert(0, str(deger or 0))
        self.fiyat_girdiler["yuvarlama"].set(getattr(t, "yuvarlama_yontemi", None) or "kurus")
        self._fiyat_ozet = {
            "total_purchase_cost": t.total_purchase_cost,
            "customer_expense_amount": t.customer_expense_amount,
            "internal_expense_amount": t.internal_expense_amount,
            "percentage_profit_amount": t.percentage_profit_amount,
            "fixed_profit_amount": t.fixed_profit_amount,
            "total_target_profit": t.total_target_profit,
            "actual_profit_amount": t.actual_profit_amount,
            "cost_markup_rate": t.cost_markup_rate,
            "sales_margin_rate": t.sales_margin_rate,
            "calculated_offer_subtotal": t.calculated_offer_subtotal,
        }
        if t.cari:
            self._musteri_alanlari_yaz(
                getattr(t.cari, "cari_kodu", "") or "",
                getattr(t.cari, "unvan", "") or "",
            )
            self._selected_customer_id = getattr(t.cari, "id", None)
            anahtar = f"{t.cari.cari_kodu} - {t.cari.unvan}"
            if anahtar not in self.musteri_map:
                self.musteri_map[anahtar] = t.cari
            kod = (t.cari.cari_kodu or "").strip()
            if kod:
                self._musteri_kod_map[kod] = t.cari
        self.musteri_notu.delete("1.0", "end")
        self.ic_not.delete("1.0", "end")
        self.ticari_sartlar.delete("1.0", "end")
        self.musteri_notu.insert("1.0", t.musteri_notu or "")
        self.ic_not.insert("1.0", t.ic_not or "")
        self.ticari_sartlar.insert("1.0", t.ticari_sartlar or "")
        self.satirlar = []
        for s in t.satirlar:
            self.satirlar.append(
                {
                    "urun_kodu": s.urun_kodu,
                    "urun_adi": s.urun_adi,
                    "miktar": s.miktar,
                    "birim": s.birim,
                    "birim_maliyet": s.birim_maliyet,
                    "maliyet_kaynagi": s.maliyet_kaynagi,
                    "liste_fiyati": s.liste_fiyati,
                    "teklif_fiyati": s.teklif_fiyati,
                    "iskonto_orani": s.iskonto_orani,
                    "iskonto_orani_2": s.iskonto_orani_2,
                    "iskonto_orani_3": s.iskonto_orani_3,
                    "kdv_orani": s.kdv_orani,
                    "net_birim_fiyat": s.net_birim_fiyat,
                    "satir_toplam": s.satir_toplam,
                    "kar_orani": s.kar_orani,
                    "gercek_marj": s.gercek_marj,
                    "fiyat_yontemi": s.fiyat_yontemi,
                    "purchase_unit_price": getattr(s, "purchase_unit_price", None) or s.birim_maliyet,
                    "purchase_currency": getattr(s, "purchase_currency", None) or "TRY",
                    "purchase_exchange_rate": getattr(s, "purchase_exchange_rate", None) or 1,
                    "purchase_unit_price_base": getattr(s, "purchase_unit_price_base", None)
                    or s.birim_maliyet,
                    "purchase_total_cost": getattr(s, "purchase_total_cost", None) or 0,
                    "cost_source_date": getattr(s, "cost_source_date", None),
                    "supplier_id": getattr(s, "supplier_id", None),
                    "supplier_name": getattr(s, "supplier_name", None),
                    "allocated_expense": getattr(s, "allocated_expense", None) or 0,
                    "allocated_percentage_profit": getattr(s, "allocated_percentage_profit", None)
                    or 0,
                    "allocated_fixed_profit": getattr(s, "allocated_fixed_profit", None) or 0,
                    "calculated_offer_unit_price": getattr(s, "calculated_offer_unit_price", None)
                    or 0,
                    "manual_offer_unit_price": getattr(s, "manual_offer_unit_price", None),
                    "final_offer_unit_price": getattr(s, "final_offer_unit_price", None)
                    or s.teklif_fiyati,
                    "is_manual_price": bool(getattr(s, "is_manual_price", False)),
                    "fiyat_hesaplandi": bool(
                        getattr(s, "teklif_fiyati", None) is not None
                        and Decimal(str(s.teklif_fiyati or 0)) > 0
                    ),
                    "yeniden_hesaplanmali": False,
                    "actual_profit_amount": getattr(s, "actual_profit_amount", None) or 0,
                    "actual_margin_rate": getattr(s, "actual_margin_rate", None) or 0,
                    "opsiyonel": s.opsiyonel,
                    "toplama_dahil": s.toplama_dahil,
                    "kabul_edildi": s.kabul_edildi,
                    "is_manual_item": bool(getattr(s, "is_manual_item", False)),
                    "manuel": bool(getattr(s, "is_manual_item", False)),
                    "line_type": getattr(s, "line_type", None) or (
                        "MANUAL_PRODUCT"
                        if getattr(s, "is_manual_item", False)
                        else "STOCK_PRODUCT"
                    ),
                    "product_id": getattr(s, "product_id", None),
                    "stok_id": getattr(s, "product_id", None),
                    "manual_product_name": getattr(s, "manual_product_name", None),
                    "manual_description": getattr(s, "manual_description", None),
                    "manual_brand": getattr(s, "manual_brand", None),
                    "manual_model": getattr(s, "manual_model", None),
                    "manual_manufacturer_code": getattr(s, "manual_manufacturer_code", None),
                    "manual_barcode": getattr(s, "manual_barcode", None),
                    "unit_name_snapshot": getattr(s, "unit_name_snapshot", None) or s.birim,
                    "estimated_purchase_unit_price": getattr(
                        s, "estimated_purchase_unit_price", None
                    ),
                    "delivery_term_days": getattr(s, "delivery_term_days", None),
                    "estimated_delivery_date": getattr(s, "estimated_delivery_date", None),
                    "delivery_term_note": getattr(s, "delivery_term_note", None),
                    "supplier_note": getattr(s, "supplier_note", None),
                    "customer_note": getattr(s, "customer_note", None),
                    "internal_note": getattr(s, "internal_note", None),
                    "cost_status": getattr(s, "cost_status", None) or "OK",
                    "stock_conversion_status": getattr(s, "stock_conversion_status", None),
                    "converted_product_id": getattr(s, "converted_product_id", None),
                    "aciklama": s.aciklama,
                    "marka": s.marka,
                    "hizmet_satiri": bool(getattr(s, "hizmet_satiri", False)),
                    "margin_unavailable": (getattr(s, "cost_status", None) or "") == "EKSIK",
                }
            )
        self.masraflar = []
        for m in getattr(t, "masraflar", None) or []:
            self.masraflar.append(
                {
                    "expense_type": m.expense_type,
                    "description": m.description,
                    "amount": m.amount,
                    "currency": m.currency,
                    "exchange_rate": m.exchange_rate,
                    "base_amount": m.base_amount,
                    "is_customer_chargeable": m.is_customer_chargeable,
                }
            )
        self._satir_tablo_yenile()
        self._rozet(t.durum)
        self._meta_guncelle()
        # Kayıtlı Net = Uzlaşılan; Brüt ≠ Net ise Brüt kilidi
        from database.fatura_genel_toplam_service import kurus

        kayitli_genel = getattr(t, "genel_toplam", None)
        satir_brut = kurus(
            sum((self._uzlasilan_satir_genel(v) for v in self.satirlar), Decimal("0"))
        )
        tur = (getattr(t, "genel_islem_turu", None) or "").strip().upper()
        islem_t = kurus(getattr(t, "genel_islem_tutari", 0) or 0)
        if kayitli_genel is not None:
            net = kurus(kayitli_genel)
            self._hesaplanan_genel = net
            self._uzlasilan_tutar = net
            self._uzlasilan_ui_kilit = True
            try:
                self._uzlasilan_tutar_yaz(net)
            finally:
                self._uzlasilan_ui_kilit = False
            self._genel_islem_turu = tur
            self._genel_islem_orani = Decimal(str(getattr(t, "genel_islem_orani", 0) or 0))
            self._genel_islem_tutari = islem_t
            if tur == "INDIRIM" and islem_t > 0:
                brut_ref = kurus(net + islem_t)
            elif tur == "MASRAF" and islem_t > 0:
                brut_ref = kurus(net - islem_t)
            else:
                brut_ref = satir_brut
            if brut_ref != net:
                self._uzlasilan_snapshot_brut = brut_ref
            else:
                self._uzlasilan_snapshot_brut = None
        else:
            self._uzlasilan_snapshot_brut = None
            self._uzlasilan_tutar = None
        self._toplam_guncelle()
        self._fiyat_ozet_guncelle()
        # Footer not senkron
        refs = getattr(self, "_teklif_alt_ozet", None) or {}
        not_w = refs.get("not_alani")
        if not_w is not None:
            try:
                not_w.delete("1.0", "end")
                not_w.insert("1.0", t.musteri_notu or "")
            except tk.TclError:
                pass
        self.lbl_gecmis.configure(
            text=(
                f"İşlemi Yapan: {display_user(t.created_by_full_name, t.created_by_user_id)}  |  "
                f"Oluşturma: {format_dt(t.olusturma_tarihi)}  |  "
                f"Son Güncelleyen: {display_user(t.updated_by_full_name, t.updated_by_user_id) if t.updated_by_user_id else '—'}  |  "
                f"Sipariş: {t.siparis_no or '—'}"
            )
        )

    def _meta_guncelle(self):
        no = self.girdiler["teklif_no"].get()
        try:
            ad = (self.musteri_adi.get() or "").strip()
            kod = (self.musteri_kodu.get() or "").strip()
        except (tk.TclError, AttributeError):
            ad, kod = "", ""
        mus = ad or kod or self.girdiler["aday_musteri_adi"].get() or "—"
        if kod and ad:
            mus = f"{kod} - {ad}"
        self.lbl_meta.configure(text=f"{no}  ·  {mus}")

    def _rozet(self, durum: str):
        bg, fg = TEKLIF_DURUM_RENK.get(durum, ("#64748B", BEYAZ))
        self.rozet.configure(text=durum, bg=bg, fg=fg)

    def _urun_ara_focus_in(self, _e=None):
        if self.urun_ad_ara.get() == getattr(self, "_urun_ara_placeholder", ""):
            self.urun_ad_ara.delete(0, "end")
            self.urun_ad_ara.configure(foreground="#0F172A")

    def _urun_ara_focus_out(self, _e=None):
        if not self.urun_ad_ara.get().strip():
            self.urun_ad_ara.insert(0, getattr(self, "_urun_ara_placeholder", ""))
            self.urun_ad_ara.configure(foreground="#94A3B8")

    def _secili_kdv_orani(self) -> Decimal:
        """Ürün giriş çubuğundaki KDV seçimini oku (0 geçerli orandır)."""
        if hasattr(self, "urun_kdv"):
            ham = (self.urun_kdv.get() or "").strip()
            if ham != "":
                try:
                    return Decimal(ham.replace(",", "."))
                except Exception:
                    pass
        return Decimal(str(VARSAYILAN_KDV_ORANI))

    def _kdv_deger(self, oran, *, varsayilan=None) -> Decimal:
        """None/boş → varsayılan; 0 korunur."""
        if varsayilan is None:
            varsayilan = VARSAYILAN_KDV_ORANI
        if oran is None or oran == "":
            return Decimal(str(varsayilan))
        try:
            return Decimal(str(oran).replace(",", "."))
        except Exception:
            return Decimal(str(varsayilan))

    def _kdv_alani_ayarla(self, oran) -> None:
        if not hasattr(self, "urun_kdv"):
            return
        try:
            metin = str(int(self._kdv_deger(oran)))
        except Exception:
            metin = str(int(VARSAYILAN_KDV_ORANI))
        if metin not in KDV_ORANLARI:
            metin = str(int(VARSAYILAN_KDV_ORANI))
        once = getattr(self, "_kdv_yukle_kilit", False)
        self._kdv_yukle_kilit = True
        try:
            if (self.urun_kdv.get() or "").strip() != metin:
                self.urun_kdv.set(metin)
        finally:
            self._kdv_yukle_kilit = once

    def _urun_giris_temizle(self):
        self._secili_urun = None
        self._duzenlenen_satir_idx = None
        self.urun_kod.delete(0, "end")
        if hasattr(self, "_urun_arama"):
            self._urun_arama.temizle()
            self.urun_ad_ara.configure(foreground="#94A3B8")
            if not self.urun_ad_ara.get().strip():
                self.urun_ad_ara.insert(0, self._urun_ara_placeholder)
        self.urun_miktar.delete(0, "end")
        self.urun_miktar.insert(0, "1")
        self.urun_birim.set("Adet")
        self._kdv_alani_ayarla(VARSAYILAN_KDV_ORANI)
        if hasattr(self, "urun_maliyet"):
            try:
                self.urun_maliyet.delete(0, "end")
            except tk.TclError:
                pass
            if hasattr(self, "lbl_urun_maliyet_pb"):
                self.lbl_urun_maliyet_pb.configure(text="TRY")

    def _satir_tutar_yenile(self, s: dict) -> None:
        """KDV / miktar / fiyat değişince satır tutarını yeniden hesapla."""
        from database.teklif_pricing_service import net_iskontolu

        miktar = _decimal(s.get("miktar") or 0)
        fiyat = _decimal(s.get("teklif_fiyati") or s.get("final_offer_unit_price") or 0)
        net = _decimal(s.get("net_birim_fiyat") or 0)
        if (net <= 0) and fiyat > 0:
            net = net_iskontolu(
                fiyat,
                s.get("iskonto_orani", 0),
                s.get("iskonto_orani_2", 0),
                s.get("iskonto_orani_3", 0),
            )
            s["net_birim_fiyat"] = net
        kdv_o = self._kdv_deger(s.get("kdv_orani"))
        if miktar > 0 and net >= 0 and (
            bool(s.get("fiyat_hesaplandi"))
            or fiyat > 0
            or net > 0
        ):
            ara = (net * miktar).quantize(Decimal("0.01"))
            s["satir_toplam"] = ara + (ara * kdv_o / Decimal("100")).quantize(Decimal("0.01"))
            if fiyat > 0 or net > 0:
                s["fiyat_hesaplandi"] = True
                s["yeniden_hesaplanmali"] = False
        base = _decimal(s.get("purchase_unit_price_base") or s.get("birim_maliyet") or 0)
        if miktar > 0 and base > 0:
            s["purchase_total_cost"] = (base * miktar).quantize(Decimal("0.01"))

    def _satir_secildi(self, _e=None):
        if getattr(self, "_satir_yukle_kilit", False):
            return
        sec = self.satir_tablo.selection()
        if not sec:
            return
        idx = self.satir_tablo.index(sec[0])
        if not (0 <= idx < len(self.satirlar)):
            return
        self._satir_girise_yukle(idx)

    def _satir_girise_yukle(self, idx: int) -> None:
        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        self._duzenlenen_satir_idx = idx
        self._satir_yukle_kilit = True
        try:
            self.urun_kod.delete(0, "end")
            self.urun_kod.insert(0, (s.get("urun_kodu") or "").strip())
            ad = (s.get("urun_adi") or "").strip()
            self.urun_ad_ara.delete(0, "end")
            self.urun_ad_ara.insert(0, ad)
            self.urun_ad_ara.configure(foreground="#0F172A")
            self.urun_miktar.delete(0, "end")
            self.urun_miktar.insert(0, str(s.get("miktar") or 1).replace(".", ","))
            birim = (s.get("birim") or "Adet").strip() or "Adet"
            try:
                degerler = list(self.urun_birim.cget("values") or ())
                if birim not in degerler:
                    self.urun_birim.configure(values=list(degerler) + [birim])
            except tk.TclError:
                pass
            self.urun_birim.set(birim)
            self._kdv_alani_ayarla(s.get("kdv_orani", VARSAYILAN_KDV_ORANI))
            depo = (s.get("depo") or "").strip()
            if depo and hasattr(self, "urun_depo"):
                try:
                    dvals = list(self.urun_depo.cget("values") or ())
                    if depo not in dvals:
                        self.urun_depo.configure(values=list(dvals) + [depo])
                    self.urun_depo.set(depo)
                except tk.TclError:
                    pass
            if hasattr(self, "urun_maliyet") and maliyet_izinli():
                mal = s.get("purchase_unit_price_base") or s.get("birim_maliyet") or ""
                self.urun_maliyet.delete(0, "end")
                if mal not in ("", None) and _decimal(mal) > 0:
                    self.urun_maliyet.insert(0, str(mal).replace(".", ","))
                pb = (s.get("purchase_currency") or "TRY").strip() or "TRY"
                if hasattr(self, "lbl_urun_maliyet_pb"):
                    self.lbl_urun_maliyet_pb.configure(text=pb)
            self._secili_urun = {
                "stok_id": s.get("stok_id") or s.get("product_id"),
                "urun_kodu": s.get("urun_kodu"),
                "urun_adi": s.get("urun_adi"),
                "birim": s.get("birim"),
                "manuel": bool(s.get("is_manual_item") or s.get("manuel")),
                "kdv_orani": s.get("kdv_orani"),
            }
        finally:
            self._satir_yukle_kilit = False

    def _urun_kdv_degisti(self, _e=None):
        """Giriş çubuğundaki KDV, seçili/düzenlenen satıra anında yansısın."""
        if getattr(self, "_kdv_yukle_kilit", False):
            return
        idx = self._duzenlenen_satir_idx
        if idx is None:
            sec = self.satir_tablo.selection()
            if sec:
                idx = self.satir_tablo.index(sec[0])
        if idx is None or not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        s["kdv_orani"] = self._secili_kdv_orani()
        self._satir_tutar_yenile(s)
        self._satir_yukle_kilit = True
        try:
            self._satir_tablo_yenile()
            if 0 <= idx < len(self.satirlar):
                cocuklar = self.satir_tablo.get_children()
                if idx < len(cocuklar):
                    self.satir_tablo.selection_set(cocuklar[idx])
                    self.satir_tablo.focus(cocuklar[idx])
            self._duzenlenen_satir_idx = idx
        finally:
            self._satir_yukle_kilit = False
        self._toplam_guncelle()

    def _satir_guncelle(self):
        """Giriş çubuğundaki değerlerle seçili satırı güncelle."""
        idx = self._duzenlenen_satir_idx
        if idx is None:
            sec = self.satir_tablo.selection()
            if not sec:
                messagebox.showinfo(
                    "Güncelle",
                    "Güncellenecek satırı tablodan seçin.",
                    parent=self,
                )
                return
            idx = self.satir_tablo.index(sec[0])
        if not (0 <= idx < len(self.satirlar)):
            messagebox.showwarning("Güncelle", "Geçerli bir satır seçili değil.", parent=self)
            return
        s = self.satirlar[idx]
        try:
            miktar = _decimal(self.urun_miktar.get(), "Miktar")
        except ValueError as hata:
            messagebox.showerror("Miktar", str(hata), parent=self)
            return
        if miktar <= 0:
            messagebox.showwarning("Miktar", "Miktar pozitif olmalı.", parent=self)
            return
        ad_metin = self.urun_ad_ara.get().strip()
        if ad_metin == getattr(self, "_urun_ara_placeholder", ""):
            ad_metin = ""
        kod = self.urun_kod.get().strip() or (s.get("urun_kodu") or "").strip()
        birim = (self.urun_birim.get() or s.get("birim") or "Adet").strip() or "Adet"
        kdv = self._secili_kdv_orani()
        s["urun_kodu"] = kod or s.get("urun_kodu")
        if ad_metin:
            s["urun_adi"] = ad_metin
        s["miktar"] = miktar
        s["birim"] = birim
        s["kdv_orani"] = kdv
        if hasattr(self, "urun_depo"):
            depo = (self.urun_depo.get() or "").strip()
            if depo:
                s["depo"] = depo
        if hasattr(self, "urun_maliyet") and maliyet_izinli():
            ham = (self.urun_maliyet.get() or "").strip()
            if ham:
                try:
                    mal = _decimal(ham, "Maliyet Fiyatı")
                except ValueError as hata:
                    messagebox.showerror("Maliyet", str(hata), parent=self)
                    return
                if mal > 0:
                    s["birim_maliyet"] = mal
                    s["purchase_unit_price_base"] = mal
                    s["estimated_purchase_unit_price"] = mal
                    s["maliyet_kaynagi"] = "MANUEL"
                    s["cost_status"] = "OK"
        self._satir_tutar_yenile(s)
        self._satir_yukle_kilit = True
        try:
            self._satir_tablo_yenile()
            cocuklar = self.satir_tablo.get_children()
            if idx < len(cocuklar):
                self.satir_tablo.selection_set(cocuklar[idx])
                self.satir_tablo.focus(cocuklar[idx])
                self.satir_tablo.see(cocuklar[idx])
            self._duzenlenen_satir_idx = idx
        finally:
            self._satir_yukle_kilit = False
        self._toplam_guncelle()

    def _arama_urun_secildi(self, urun: dict):
        """Arama listesinden seçim → satır giriş alanlarını doldur, miktara odaklan."""
        self._duzenlenen_satir_idx = None
        self._secili_urun = dict(urun)
        kod = (urun.get("urun_kodu") or "").strip()
        ad = (urun.get("urun_adi") or "").strip()
        birim = (urun.get("birim") or "Adet").strip() or "Adet"
        self.urun_kod.delete(0, "end")
        self.urun_kod.insert(0, kod)
        self.urun_ad_ara.delete(0, "end")
        self.urun_ad_ara.insert(0, ad)
        self.urun_ad_ara.configure(foreground="#0F172A")
        birimler = [birim]
        kdv_stok = urun.get("kdv_orani")
        try:
            from database.database import get_session
            from database.models.stok import StokKarti
            from sqlalchemy import select

            with get_session() as session:
                kart = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod))
                if kart:
                    ekstra = []
                    for b in getattr(kart, "birimler", None) or []:
                        ba = (b.birim_adi or "").strip()
                        if ba and ba not in ekstra and ba != birim:
                            ekstra.append(ba)
                    birimler = [birim] + ekstra
                    if kdv_stok is None:
                        kdv_stok = getattr(kart, "kdv_orani", None)
        except Exception:
            pass
        self.urun_birim.configure(values=birimler)
        self.urun_birim.set(birim)
        self._kdv_alani_ayarla(
            kdv_stok if kdv_stok is not None else VARSAYILAN_KDV_ORANI
        )
        # Maliyet fiyatını kırmızı alana doldur (stok kartını değiştirmez)
        if hasattr(self, "urun_maliyet") and maliyet_izinli():
            depo = (
                self.urun_depo.get().strip()
                or self.girdiler["depo"].get().strip()
                or "ANA DEPO"
            )
            try:
                snap = maliyet_getir(kod, depo, self._secili_maliyet_kaynagi())
                self.urun_maliyet.delete(0, "end")
                if snap.birim_maliyet and snap.birim_maliyet > 0:
                    self.urun_maliyet.insert(0, str(snap.birim_maliyet).replace(".", ","))
                pb = getattr(snap, "purchase_currency", None) or "TRY"
                if hasattr(self, "lbl_urun_maliyet_pb"):
                    self.lbl_urun_maliyet_pb.configure(text=pb)
            except Exception:
                pass
        if not self.urun_miktar.get().strip():
            self.urun_miktar.insert(0, "1")
        self.urun_miktar.focus_set()
        self.urun_miktar.selection_range(0, "end")

    def _arama_yeni_stok(self):
        if not yetki_var("stok_duzenleme", "stok_goruntuleme"):
            messagebox.showwarning("Yetki", "Stok kartı açma yetkiniz yok.", parent=self)
            return
        try:
            from stok_ui import StokKartiDialog

            StokKartiDialog(self)
        except Exception as exc:
            messagebox.showerror("Stok", str(exc), parent=self)

    def _manuel_urun_ekle(self, baslangic: dict | None = None):
        if not yetki_var("teklif_manuel_urun", "satis_duzenleme", "yeni_kayit"):
            messagebox.showwarning("Yetki", "Manuel ürün ekleme yetkiniz yok.", parent=self)
            return
        ManuelUrunDialog(self, baslangic=baslangic, on_save=self._manuel_urun_kaydet)

    def _manuel_urun_isimle(self, isim: str):
        self._manuel_urun_ekle({"urun_adi": (isim or "").strip()})

    def _manuel_urun_duzenle(self, idx: int):
        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        if not (s.get("is_manual_item") or s.get("manuel")):
            self._satir_fiyat_duzenle()
            return
        if not yetki_var("teklif_manuel_urun", "satis_duzenleme", "duzenleme"):
            messagebox.showwarning("Yetki", "Manuel ürün düzenleme yetkiniz yok.", parent=self)
            return

        def _kaydet(veri: dict):
            self._manuel_urun_kaydet(veri, duzenle_idx=idx)

        ManuelUrunDialog(self, baslangic=s, on_save=_kaydet, duzenle=True)

    def _manuel_urun_kaydet(self, veri: dict, duzenle_idx: int | None = None):
        from database.teklif_pricing_service import kar_metrikleri, net_iskontolu
        from database.user_audit import audit_document

        ad = (veri.get("urun_adi") or "").strip()
        birim = (veri.get("birim") or "").strip()
        if not ad or not birim:
            messagebox.showwarning("Manuel Ürün", "Ürün adı ve birim zorunludur.", parent=self)
            return
        miktar = _decimal(veri.get("miktar", 1), "Miktar")
        if miktar <= 0:
            messagebox.showwarning("Miktar", "Miktar sıfırdan büyük olmalıdır.", parent=self)
            return

        if duzenle_idx is None:
            karar = self._ayni_manuel_urun_karar(ad, birim)
            if karar is None:
                return
            if isinstance(karar, str) and karar.startswith("artir:"):
                idx = int(karar.split(":", 1)[1])
                s = self.satirlar[idx]
                yeni_m = _decimal(s.get("miktar", 0)) + miktar
                s["miktar"] = yeni_m
                net = _decimal(s.get("net_birim_fiyat") or s.get("teklif_fiyati") or 0)
                kdv_o = _decimal(s.get("kdv_orani", 20))
                ara = (net * yeni_m).quantize(Decimal("0.01"))
                s["satir_toplam"] = ara + (ara * kdv_o / Decimal("100")).quantize(Decimal("0.01"))
                base = _decimal(s.get("purchase_unit_price_base") or s.get("birim_maliyet") or 0)
                s["purchase_total_cost"] = (base * yeni_m).quantize(Decimal("0.01"))
                self._satir_tablo_yenile()
                self._toplam_guncelle()
                return

        fiyat = _decimal(veri.get("teklif_fiyati") or 0)
        # Manuel ürün: satış fiyatı boş bırakılabilir; maliyet zorunlu (yetkili)
        is_manual_price = bool(veri.get("is_manual_price")) and fiyat > 0
        isk = _decimal(veri.get("iskonto_orani", 0))
        kdv = _decimal(veri.get("kdv_orani", 20))
        base = _decimal(
            veri.get("purchase_unit_price_base")
            or veri.get("estimated_purchase_unit_price")
            or veri.get("birim_maliyet")
            or 0
        )
        cost_status = veri.get("cost_status") or ("TAHMINI" if base > 0 else "EKSIK")
        if maliyet_izinli() and base <= 0:
            messagebox.showwarning(
                "Maliyet",
                "Manuel ürün için Maliyet Fiyatı girin. Satış fiyatı «Fiyatları Hesapla» ile üretilir.",
                parent=self,
            )
            return
        fiyat_hesaplandi = is_manual_price and fiyat > 0
        net = net_iskontolu(fiyat, isk, 0, 0) if fiyat_hesaplandi else None
        ara = (
            (net * miktar).quantize(Decimal("0.01"))
            if net is not None
            else None
        )
        kdv_t = (
            (ara * kdv / Decimal("100")).quantize(Decimal("0.01"))
            if ara is not None
            else None
        )
        oran, marj = (
            kar_metrikleri(net, base)
            if base > 0 and net is not None and net > 0
            else (Decimal("0"), Decimal("0"))
        )
        satir = {
            **veri,
            "urun_kodu": "MANUEL",
            "urun_adi": ad,
            "miktar": miktar,
            "birim": birim,
            "liste_fiyati": fiyat if fiyat_hesaplandi else Decimal("0"),
            "teklif_fiyati": fiyat if fiyat_hesaplandi else None,
            "iskonto_orani": isk,
            "iskonto_orani_2": 0,
            "iskonto_orani_3": 0,
            "kdv_orani": kdv,
            "net_birim_fiyat": net,
            "satir_toplam": (ara + kdv_t) if ara is not None and kdv_t is not None else None,
            "kar_orani": oran,
            "gercek_marj": marj,
            "fiyat_yontemi": "MANUEL" if is_manual_price else "MALIYET_USTU",
            "final_offer_unit_price": fiyat if fiyat_hesaplandi else None,
            "is_manual_price": is_manual_price,
            "fiyat_hesaplandi": fiyat_hesaplandi,
            "yeniden_hesaplanmali": not fiyat_hesaplandi,
            "is_manual_item": True,
            "manuel": True,
            "line_type": "MANUAL_PRODUCT",
            "product_id": None,
            "stok_id": None,
            "birim_maliyet": base,
            "purchase_unit_price_base": base,
            "purchase_total_cost": (base * miktar).quantize(Decimal("0.01")),
            "cost_status": cost_status,
            "margin_unavailable": cost_status == "EKSIK",
            "opsiyonel": False,
            "toplama_dahil": True,
            "kabul_edildi": True,
            "allocated_expense": Decimal("0"),
            "allocated_percentage_profit": Decimal("0"),
            "allocated_fixed_profit": Decimal("0"),
            "actual_profit_amount": Decimal("0"),
            "actual_margin_rate": Decimal("0"),
        }
        eski = None
        if duzenle_idx is not None and 0 <= duzenle_idx < len(self.satirlar):
            eski = dict(self.satirlar[duzenle_idx])
            self.satirlar[duzenle_idx] = satir
            islem = "TEKLIF_MANUEL_URUN_DUZENLE"
        else:
            self.satirlar.append(satir)
            islem = "TEKLIF_MANUEL_URUN_EKLE"
        self._satir_tablo_yenile()
        self._toplam_guncelle()
        self._urun_giris_temizle()
        try:
            audit_document(
                islem,
                modul="satis_teklif",
                kayit_id=str(getattr(self, "teklif_id", "") or ""),
                belge_no=self.girdiler.get("teklif_no").get() if self.girdiler.get("teklif_no") else "",
                eski={"urun_adi": (eski or {}).get("urun_adi"), "miktar": (eski or {}).get("miktar")},
                yeni={"urun_adi": ad, "birim": birim, "miktar": str(miktar), "cost_status": cost_status},
            )
        except Exception:
            pass

    def _ayni_manuel_urun_karar(self, ad: str, birim: str) -> str | None:
        ad_n = ad.casefold().strip()
        birim_n = birim.casefold().strip()
        mevcut_idx = next(
            (
                i
                for i, s in enumerate(self.satirlar)
                if (s.get("is_manual_item") or s.get("manuel"))
                and (s.get("urun_adi") or "").casefold().strip() == ad_n
                and (s.get("birim") or "").casefold().strip() == birim_n
            ),
            None,
        )
        if mevcut_idx is None:
            return "ayri"
        win = tk.Toplevel(self)
        win.title("Aynı Manuel Ürün")
        win.transient(self)
        win.grab_set()
        ttk.Label(
            win,
            text="Bu isim ve birime sahip bir manuel ürün teklifte zaten bulunuyor.",
            padding=12,
        ).pack()
        sonuc: dict[str, str | None] = {"v": None}

        def _sec(v):
            sonuc["v"] = v
            win.destroy()

        btn = ttk.Frame(win, padding=8)
        btn.pack(fill="x")
        ttk.Button(btn, text="Mevcut Satırın Miktarını Artır", command=lambda: _sec("artir")).pack(
            fill="x", pady=2
        )
        ttk.Button(btn, text="Ayrı Satır Olarak Ekle", command=lambda: _sec("ayri")).pack(
            fill="x", pady=2
        )
        ttk.Button(btn, text="Vazgeç", command=lambda: _sec(None)).pack(fill="x", pady=2)
        win.wait_window()
        if sonuc["v"] == "artir":
            return f"artir:{mevcut_idx}"
        return sonuc["v"]

    def _satir_cift_tik(self, _e=None):
        sec = self.satir_tablo.selection()
        if not sec:
            return
        idx = self.satir_tablo.index(sec[0])
        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        if s.get("is_manual_item") or s.get("manuel"):
            self._manuel_urun_duzenle(idx)
        else:
            self._satir_fiyat_duzenle()

    def _satir_sag_menu(self, event):
        row = self.satir_tablo.identify_row(event.y)
        if not row:
            return
        self.satir_tablo.selection_set(row)
        idx = self.satir_tablo.index(row)
        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        menu = tk.Menu(self, tearoff=0)
        if s.get("is_manual_item") or s.get("manuel"):
            menu.add_command(label="Manuel Ürünü Düzenle", command=lambda: self._manuel_urun_duzenle(idx))
            menu.add_command(
                label="Stok Kartına Dönüştür",
                command=lambda: self._manuel_stoka_donustur(idx),
            )
        else:
            menu.add_command(label="Teklif Fiyatını Düzenle", command=self._satir_fiyat_duzenle)
        menu.add_command(label="KDV Oranı Değiştir…", command=lambda: self._satir_kdv_duzenle(idx))
        menu.add_command(label="Satır Sil", command=self._satir_sil)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _satir_kdv_duzenle(self, idx: int):
        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        mevcut = str(int(self._kdv_deger(s.get("kdv_orani"))))
        win = tk.Toplevel(self)
        win.title("KDV Oranı")
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)
        ttk.Label(win, text="KDV %").pack(anchor="w", padx=12, pady=(12, 4))
        cmb = ttk.Combobox(win, values=list(KDV_ORANLARI), state="readonly", width=8)
        cmb.set(mevcut if mevcut in KDV_ORANLARI else str(int(VARSAYILAN_KDV_ORANI)))
        cmb.pack(padx=12, pady=4)
        cmb.focus_set()

        def _kaydet():
            try:
                yeni = self._kdv_deger(cmb.get())
            except Exception:
                messagebox.showwarning("KDV", "Geçersiz KDV oranı.", parent=win)
                return
            s["kdv_orani"] = yeni
            self._satir_tutar_yenile(s)
            self._satir_tablo_yenile()
            self._toplam_guncelle()
            if self._duzenlenen_satir_idx == idx:
                self._kdv_alani_ayarla(yeni)
            win.destroy()

        btn = ttk.Frame(win)
        btn.pack(fill="x", padx=12, pady=12)
        ttk.Button(btn, text="Tamam", command=_kaydet).pack(side="right", padx=4)
        ttk.Button(btn, text="Vazgeç", command=win.destroy).pack(side="right")
        win.bind("<Return>", lambda _e: _kaydet())
        win.bind("<Escape>", lambda _e: win.destroy())

    def _manuel_stoka_donustur(self, idx: int):
        if not yetki_var("teklif_manuel_stok_donustur", "stok_duzenleme"):
            messagebox.showwarning("Yetki", "Stok kartına dönüştürme yetkiniz yok.", parent=self)
            return
        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        ad = (s.get("urun_adi") or "").strip()
        barkod = (s.get("manual_barcode") or "").strip()
        # Benzer stok kontrolü
        benzer = []
        try:
            from database.turkce_normalize import turkce_normalize

            ara = StokService.teklif_urun_ara(ad[:40] if len(ad) >= 3 else (ad + "xx")[:3], limit=20)
            n_ad = turkce_normalize(ad)
            for u in ara.get("urunler") or []:
                if turkce_normalize(u.get("urun_adi") or "") == n_ad or (
                    barkod and (u.get("barkod") or "") == barkod
                ):
                    benzer.append(u)
        except Exception:
            benzer = []
        if benzer:
            secim = messagebox.askyesnocancel(
                "Benzer Stok",
                "Benzer bir stok kartı bulundu. Yeni kart açmak yerine mevcut stok kartıyla eşleştirmek ister misiniz?\n\n"
                f"Örnek: {benzer[0].get('urun_kodu')} — {benzer[0].get('urun_adi')}\n\n"
                "Evet = Mevcut Stokla Eşleştir\nHayır = Yeni Stok Kartı Oluştur\nİptal = Vazgeç",
                parent=self,
            )
            if secim is None:
                return
            if secim:
                u = benzer[0]
                s["product_id"] = u.get("stok_id")
                s["stok_id"] = u.get("stok_id")
                s["urun_kodu"] = u.get("urun_kodu") or s.get("urun_kodu")
                s["is_manual_item"] = False
                s["manuel"] = False
                s["line_type"] = "STOCK_PRODUCT"
                s["stock_conversion_status"] = "ESLESTIRILDI"
                s["converted_product_id"] = u.get("stok_id")
                from datetime import datetime

                from database.session_manager import oturum
                from database.user_audit import audit_document

                s["converted_at"] = datetime.now()
                s["converted_by_user_id"] = getattr(oturum, "user_id", None)
                self._satir_tablo_yenile()
                try:
                    audit_document(
                        "TEKLIF_MANUEL_ESLESTIR",
                        modul="satis_teklif",
                        kayit_id=str(getattr(self, "teklif_id", "") or ""),
                        yeni={"urun_adi": ad, "stok_id": u.get("stok_id"), "urun_kodu": u.get("urun_kodu")},
                    )
                except Exception:
                    pass
                messagebox.showinfo(
                    "Eşleştirme",
                    "Satır mevcut stokla eşleştirildi. Teklif fiyatı değiştirilmedi.",
                    parent=self,
                )
                return
        try:
            from stok_ui import StokKartiDialog

            dlg = StokKartiDialog(
                self,
                baslangic={
                    "stok_adi": ad,
                    "aciklama": s.get("manual_description") or s.get("aciklama") or "",
                    "marka": s.get("manual_brand") or s.get("marka") or "",
                    "model": s.get("manual_model") or s.get("varyant") or "",
                    "barkod": barkod or None,
                    "birim": s.get("birim") or "Adet",
                    "kdv_orani": self._kdv_deger(s.get("kdv_orani")),
                },
            )
            self.wait_window(dlg)
            stok = getattr(dlg, "result", None)
            if not stok:
                return
            sid = getattr(stok, "id", None)
            skod = getattr(stok, "stok_kodu", None)
            s["product_id"] = sid
            s["stok_id"] = sid
            s["urun_kodu"] = skod or s.get("urun_kodu")
            s["is_manual_item"] = False
            s["manuel"] = False
            s["line_type"] = "STOCK_PRODUCT"
            s["stock_conversion_status"] = "DONUSTURULDU"
            s["converted_product_id"] = sid
            from datetime import datetime

            from database.session_manager import oturum
            from database.user_audit import audit_document

            s["converted_at"] = datetime.now()
            s["converted_by_user_id"] = getattr(oturum, "user_id", None)
            self._satir_tablo_yenile()
            try:
                audit_document(
                    "TEKLIF_MANUEL_STOK_DONUSTUR",
                    modul="satis_teklif",
                    kayit_id=str(getattr(self, "teklif_id", "") or ""),
                    yeni={"urun_adi": ad, "stok_id": sid, "urun_kodu": skod},
                )
            except Exception:
                pass
            messagebox.showinfo(
                "Dönüştürme",
                "Stok kartı oluşturuldu ve satıra bağlandı. Teklif fiyatı değiştirilmedi.",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Stok", str(exc), parent=self)

    def _arama_manuel_urun(self):
        self._manuel_urun_ekle()

    def _stok_listesi_ac(self):
        if getattr(self, "_urun_sec_pencere", None) and self._urun_sec_pencere.winfo_exists():
            self._urun_sec_pencere.lift()
            return
        depo = (
            self.urun_depo.get().strip()
            or self.girdiler["depo"].get().strip()
            or "ANA DEPO"
        )

        def _sec(degerler):
            # UrunSecDialog: (kod, ad, birim, ..., fiyat)
            kod = degerler[0] if degerler else ""
            ad = degerler[1] if len(degerler) > 1 else kod
            birim = degerler[2] if len(degerler) > 2 else "Adet"
            self._arama_urun_secildi(
                {
                    "stok_id": None,
                    "urun_kodu": kod,
                    "urun_adi": ad,
                    "birim": birim,
                    "manuel": False,
                }
            )

        dialog = UrunSecDialog(self, on_select=_sec, depo_ad=depo)
        self._urun_sec_pencere = dialog
        self.wait_window(dialog)
        self._urun_sec_pencere = None

    def _urun_getir(self, _e=None):
        kod = self.urun_kod.get().strip()
        if not kod:
            return
        try:
            kart = StokService.stok_getir(kod) if hasattr(StokService, "stok_getir") else None
        except Exception:
            kart = None
        if kart is None:
            try:
                from database.database import get_session
                from database.models.stok import StokKarti
                from sqlalchemy import select

                with get_session() as session:
                    kart = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod))
            except Exception:
                kart = None
        if not kart:
            messagebox.showwarning(
                "Ürün",
                "Stok kartı bulunamadı. Özel satır olarak ekleyebilirsiniz.",
                parent=self,
            )
            return "break"
        self._son_urun = kart
        self._arama_urun_secildi(
            {
                "stok_id": getattr(kart, "id", None),
                "urun_kodu": getattr(kart, "stok_kodu", kod),
                "urun_adi": getattr(kart, "stok_adi", kod),
                "birim": getattr(kart, "birim", "Adet") or "Adet",
                "kdv_orani": getattr(kart, "kdv_orani", 20),
                "manuel": False,
            }
        )
        return "break"

    def _ayni_urun_karar(self, kod: str) -> str | None:
        """Dönüş: 'artir' | 'ayri' | None (vazgeç)."""
        mevcut_idx = next(
            (i for i, s in enumerate(self.satirlar) if (s.get("urun_kodu") or "") == kod),
            None,
        )
        if mevcut_idx is None:
            return "ayri"
        win = tk.Toplevel(self)
        win.title("Aynı Ürün")
        win.transient(self)
        win.grab_set()
        ttk.Label(
            win,
            text="Bu ürün teklif içinde zaten bulunmaktadır.",
            padding=12,
        ).pack()
        sonuc: dict[str, str | None] = {"v": None}

        def _sec(v):
            sonuc["v"] = v
            win.destroy()

        btn = ttk.Frame(win, padding=8)
        btn.pack(fill="x")
        ttk.Button(btn, text="Mevcut Satırın Miktarını Artır", command=lambda: _sec("artir")).pack(
            fill="x", pady=2
        )
        ttk.Button(btn, text="Ayrı Satır Olarak Ekle", command=lambda: _sec("ayri")).pack(
            fill="x", pady=2
        )
        ttk.Button(btn, text="Vazgeç", command=lambda: _sec(None)).pack(fill="x", pady=2)
        win.wait_window()
        if sonuc["v"] == "artir":
            return f"artir:{mevcut_idx}"
        return sonuc["v"]

    def add_product_to_quote(
        self,
        product_id: int | None = None,
        quantity: Decimal | None = None,
        unit_id: str | None = None,
        warehouse_id: str | None = None,
        *,
        urun_kodu: str | None = None,
        urun_adi: str | None = None,
        manuel: bool = False,
    ):
        """Ortak teklif satırı ekleme — arama / stok listesi / kod girişi."""
        kod = (urun_kodu or self.urun_kod.get().strip() or "OZEL").strip()
        miktar = quantity if quantity is not None else _decimal(self.urun_miktar.get(), "Miktar")
        if miktar <= 0:
            messagebox.showwarning("Miktar", "Miktar pozitif olmalı.", parent=self)
            return
        depo = (
            (warehouse_id or "").strip()
            or self.urun_depo.get().strip()
            or self.girdiler["depo"].get().strip()
            or "ANA DEPO"
        )
        birim = (unit_id or self.urun_birim.get() or "Adet").strip() or "Adet"
        ad = (urun_adi or "").strip() or kod
        liste = Decimal("0")
        # Öncelik: giriş çubuğundaki KDV seçimi (stok varsayılanını ezer)
        kdv = self._secili_kdv_orani()
        try:
            from database.database import get_session
            from database.models.stok import StokKarti
            from sqlalchemy import select

            with get_session() as session:
                kart = None
                if product_id:
                    kart = session.get(StokKarti, int(product_id))
                if kart is None:
                    kart = session.scalar(select(StokKarti).where(StokKarti.stok_kodu == kod))
                if kart:
                    kod = kart.stok_kodu or kod
                    ad = kart.stok_adi or ad
                    if not unit_id:
                        birim = kart.birim or birim
                    manuel = False
        except Exception:
            pass
        if self._secili_urun and not urun_adi:
            ad = (self._secili_urun.get("urun_adi") or ad).strip() or ad
            manuel = bool(self._secili_urun.get("manuel")) or manuel

        karar = self._ayni_urun_karar(kod)
        if karar is None:
            return
        if isinstance(karar, str) and karar.startswith("artir:"):
            idx = int(karar.split(":", 1)[1])
            s = self.satirlar[idx]
            yeni_miktar = Decimal(str(s.get("miktar") or 0)) + miktar
            s["miktar"] = yeni_miktar
            s["kdv_orani"] = self._secili_kdv_orani()
            self._satir_tutar_yenile(s)
            self._satir_tablo_yenile()
            self._toplam_guncelle()
            if any(
                _decimal(self.fiyat_girdiler[k].get(), k) > 0
                for k in ("profit_rate", "fixed_profit_amount", "customer_expense_amount")
                if k in self.fiyat_girdiler
            ):
                messagebox.showinfo(
                    "Yeniden Hesapla",
                    "Miktar güncellendi. Kâr/masraf dağıtımı için «Fiyatları Hesapla» çalıştırın.",
                    parent=self,
                )
            self._urun_giris_temizle()
            return

        try:
            liste = Decimal(str(StokService.satis_fiyati_1(kod, Decimal("0")) or 0))
        except Exception:
            liste = Decimal("0")
        kay = self._secili_maliyet_kaynagi()
        snap = maliyet_getir(kod, depo, kay)
        # Giriş çubuğundaki maliyet (teklife özgü; stok kartını güncellemez)
        giris_maliyet = None
        if hasattr(self, "urun_maliyet") and maliyet_izinli():
            ham = (self.urun_maliyet.get() or "").strip()
            if ham:
                try:
                    giris_maliyet = _decimal(ham, "Maliyet Fiyatı")
                except ValueError as hata:
                    messagebox.showerror("Maliyet", str(hata), parent=self)
                    return
        if giris_maliyet is not None and giris_maliyet > 0:
            snap = maliyet_getir(kod, depo, "MANUEL", manuel=giris_maliyet)
        elif manuel and maliyet_izinli() and snap.birim_maliyet <= 0:
            messagebox.showwarning(
                "Maliyet",
                "Manuel ürün için Maliyet Fiyatı girin (kırmızı çerçeveli alan).",
                parent=self,
            )
            return
        if (snap.uyari or snap.birim_maliyet <= 0) and maliyet_izinli() and not manuel:
            messagebox.showwarning(
                "Maliyet",
                snap.uyari or "Alış maliyeti 0 — satır kırmızı işaretlenecek.",
                parent=self,
            )
        # Satış fiyatı ürün eklenirken boş; yalnızca «Fiyatları Hesapla» ile üretilir
        fiyat = None
        net = Decimal("0")
        purchase_total = (snap.purchase_unit_price_base * miktar).quantize(Decimal("0.01"))
        self.satirlar.append(
            {
                "urun_kodu": kod,
                "urun_adi": ad,
                "miktar": miktar,
                "birim": birim,
                "birim_maliyet": snap.birim_maliyet,
                "maliyet_kaynagi": snap.maliyet_kaynagi,
                "liste_fiyati": liste,
                "teklif_fiyati": fiyat,
                "iskonto_orani": 0,
                "iskonto_orani_2": 0,
                "iskonto_orani_3": 0,
                "kdv_orani": kdv,
                "net_birim_fiyat": None,
                "satir_toplam": None,
                "kar_orani": Decimal("0"),
                "gercek_marj": Decimal("0"),
                "fiyat_yontemi": "MALIYET_USTU",
                "purchase_unit_price": snap.purchase_unit_price,
                "purchase_currency": snap.purchase_currency,
                "purchase_exchange_rate": snap.purchase_exchange_rate,
                "purchase_unit_price_base": snap.purchase_unit_price_base,
                "purchase_total_cost": purchase_total,
                "cost_source_date": snap.cost_source_date,
                "supplier_id": snap.supplier_id,
                "supplier_name": snap.supplier_name,
                "maliyet_hesap_zamani": snap.maliyet_hesap_zamani,
                "allocated_expense": Decimal("0"),
                "allocated_percentage_profit": Decimal("0"),
                "allocated_fixed_profit": Decimal("0"),
                "calculated_offer_unit_price": Decimal("0"),
                "manual_offer_unit_price": None,
                "final_offer_unit_price": None,
                "is_manual_price": False,
                "fiyat_hesaplandi": False,
                "yeniden_hesaplanmali": True,
                "actual_profit_amount": Decimal("0"),
                "actual_margin_rate": Decimal("0"),
                "opsiyonel": False,
                "toplama_dahil": True,
                "kabul_edildi": True,
                "manuel": manuel,
                "stok_id": product_id,
                "cost_status": "OK" if snap.birim_maliyet > 0 else "EKSIK",
            }
        )
        self._satir_tablo_yenile()
        self._toplam_guncelle()
        self._urun_giris_temizle()

    def _satir_ekle(self):
        kod = self.urun_kod.get().strip() or "OZEL"
        ad_metin = self.urun_ad_ara.get().strip()
        if ad_metin == getattr(self, "_urun_ara_placeholder", ""):
            ad_metin = ""
        ad = ad_metin or (self._secili_urun or {}).get("urun_adi") or kod
        pid = (self._secili_urun or {}).get("stok_id")
        self.add_product_to_quote(
            product_id=int(pid) if pid else None,
            urun_kodu=kod,
            urun_adi=ad,
            quantity=_decimal(self.urun_miktar.get(), "Miktar"),
            unit_id=self.urun_birim.get().strip() or "Adet",
            warehouse_id=self.urun_depo.get().strip()
            or self.girdiler["depo"].get().strip()
            or "ANA DEPO",
            manuel=bool((self._secili_urun or {}).get("manuel")),
        )

    def _satir_sil(self):
        sec = self.satir_tablo.selection()
        if not sec:
            return
        idx = self.satir_tablo.index(sec[0])
        if 0 <= idx < len(self.satirlar):
            del self.satirlar[idx]
        self._satir_tablo_yenile()
        self._toplam_guncelle()

    def _satir_fiyat_duzenle(self, _e=None):
        if not yetki_var("satis_duzenleme", "yeni_kayit"):
            messagebox.showwarning("Yetki", "Fiyat düzenleme yetkiniz yok.", parent=self)
            return
        sec = self.satir_tablo.selection()
        if not sec:
            return
        idx = self.satir_tablo.index(sec[0])
        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        metin = simpledialog.askstring(
            "Manuel Teklif Fiyatı",
            f"{s.get('urun_kodu')} için teklif birim fiyatı:",
            initialvalue=str(s.get("teklif_fiyati") or ""),
            parent=self,
        )
        if metin is None:
            return
        try:
            fiyat = _decimal(metin, "Teklif fiyatı")
        except ValueError as hata:
            messagebox.showerror("Fiyat", str(hata), parent=self)
            return
        miktar = _decimal(s.get("miktar", 1))
        i1 = s.get("iskonto_orani", 0)
        i2 = s.get("iskonto_orani_2", 0)
        i3 = s.get("iskonto_orani_3", 0)
        from database.teklif_pricing_service import net_iskontolu, kar_metrikleri

        net = net_iskontolu(fiyat, i1, i2, i3)
        kdv_o = _decimal(s.get("kdv_orani", 20))
        ara = (net * miktar).quantize(Decimal("0.01"))
        s["teklif_fiyati"] = fiyat
        s["manual_offer_unit_price"] = fiyat
        s["final_offer_unit_price"] = fiyat
        s["net_birim_fiyat"] = net
        s["satir_toplam"] = ara + (ara * kdv_o / Decimal("100")).quantize(Decimal("0.01"))
        s["is_manual_price"] = True
        mal = _decimal(s.get("birim_maliyet", 0))
        oran, marj = kar_metrikleri(net, mal)
        s["kar_orani"] = oran
        s["gercek_marj"] = marj
        self._satir_tablo_yenile()
        self._toplam_guncelle()

    def _teklif_excel_cizgileri_temizle(self) -> None:
        for w in getattr(self, "_teklif_excel_cizgiler", []) or []:
            try:
                w.destroy()
            except tk.TclError:
                pass
        self._teklif_excel_cizgiler = []
        aid = getattr(self, "_teklif_excel_after", None)
        if aid is not None:
            try:
                self.after_cancel(aid)
            except tk.TclError:
                pass
            self._teklif_excel_after = None

    def _teklif_excel_cizgileri_kur(self) -> None:
        """Ürün satır tablosuna fatura benzeri Excel ızgarası bağlar."""
        if getattr(self, "_teklif_excel_kurulu", False):
            self._teklif_excel_cizgileri_yenile()
            return
        if not hasattr(self, "satir_tablo"):
            return
        tree = self.satir_tablo
        parent = tree.master
        self._teklif_excel_cizgiler = []
        self._teklif_excel_after = None

        dikey = None
        for w in parent.winfo_children():
            if not isinstance(w, ttk.Scrollbar):
                continue
            try:
                if str(w.cget("orient")) == "vertical":
                    dikey = w
                    break
            except tk.TclError:
                continue

        def planla(_event=None):
            aid = getattr(self, "_teklif_excel_after", None)
            if aid is not None:
                try:
                    self.after_cancel(aid)
                except tk.TclError:
                    pass
            self._teklif_excel_after = self.after(15, self._teklif_excel_cizgileri_yenile)

        def yset(*args):
            if dikey is not None:
                try:
                    dikey.set(*args)
                except tk.TclError:
                    pass
            planla()

        tree.configure(yscrollcommand=yset)
        tree.bind("<Configure>", planla, add="+")
        tree.bind("<MouseWheel>", planla, add="+")
        tree.bind("<ButtonRelease-1>", planla, add="+")
        parent.bind("<Configure>", planla, add="+")
        self._teklif_excel_kurulu = True
        planla()

    def _teklif_excel_cizgileri_yenile(self) -> None:
        """Görünür hücre kenarlarına ince yatay/dikey çizgiler (fatura gibi)."""
        self._teklif_excel_after = None
        if not hasattr(self, "satir_tablo"):
            return
        tree = self.satir_tablo
        parent = tree.master
        self._teklif_excel_cizgileri_temizle()
        try:
            if not tree.winfo_ismapped():
                return
        except tk.TclError:
            return

        renk = "#BDBDBD"
        dcols = tree["displaycolumns"]
        if not dcols or dcols in ("#all", ("#all",)):
            dcols = tree["columns"]
        dcols = list(dcols or ())
        if not dcols:
            return
        try:
            tx, ty = tree.winfo_x(), tree.winfo_y()
        except tk.TclError:
            return

        cizgiler = []
        self._teklif_excel_cizgiler = cizgiler

        def _tiklama_aktar(event, cift=False):
            try:
                x = event.x_root - tree.winfo_rootx()
                y = event.y_root - tree.winfo_rooty()
            except tk.TclError:
                return "break"
            row = tree.identify_row(y)
            if row:
                try:
                    tree.selection_set(row)
                    tree.focus(row)
                except tk.TclError:
                    pass
            try:
                tree.event_generate("<Double-1>" if cift else "<Button-1>", x=x, y=y)
            except tk.TclError:
                pass
            return "break"

        def cizgi(**kwargs):
            fr = tk.Frame(parent, bg=renk, highlightthickness=0, bd=0, **kwargs)
            fr.bind("<Button-1>", _tiklama_aktar)
            fr.bind("<Double-1>", lambda e: _tiklama_aktar(e, cift=True))
            cizgiler.append(fr)
            return fr

        def hucre(x, y, w, h, sol=False, ust=False):
            if w <= 1 or h <= 1:
                return
            if ust:
                cizgi(height=1, width=w).place(x=tx + x, y=ty + y)
            cizgi(height=1, width=w).place(x=tx + x, y=ty + y + h - 1)
            if sol:
                cizgi(width=1, height=h).place(x=tx + x, y=ty + y)
            cizgi(width=1, height=h).place(x=tx + x + w - 1, y=ty + y)

        stil = ttk.Style(self)
        try:
            rh = int(float(stil.lookup("TeklifSatir.Treeview", "rowheight") or 42))
        except (TypeError, ValueError):
            rh = 42

        children = list(tree.get_children())
        kolon_xw = None
        baslik_h = None
        son_alt = None
        ilk_veri_y = None

        for item in children:
            for sira, col in enumerate(dcols):
                box = tree.bbox(item, col)
                if not box:
                    continue
                x, y, w, h = box
                if ilk_veri_y is None:
                    ilk_veri_y = y
                hucre(x, y, w, h, sol=(sira == 0), ust=(y == ilk_veri_y))
                if kolon_xw is None:
                    kolon_xw = []
                    for c2 in dcols:
                        b2 = tree.bbox(item, c2)
                        if b2:
                            kolon_xw.append((b2[0], b2[2]))
                    baslik_h = y
                    rh = h
                son_alt = y + h

        if kolon_xw is None:
            toplam_w = sum(max(20, int(tree.column(c, "width") or 20)) for c in dcols) or 1
            try:
                sol = float(tree.xview()[0]) * toplam_w
            except (tk.TclError, ValueError, IndexError):
                sol = 0.0
            kolon_xw = []
            cum = 0
            for col in dcols:
                w = max(20, int(tree.column(col, "width") or 20))
                kolon_xw.append((int(cum - sol), w))
                cum += w
            baslik_h = 26
            son_alt = baslik_h

        if baslik_h and baslik_h > 2 and kolon_xw:
            for sira, (x, w) in enumerate(kolon_xw):
                if x + w < 0:
                    continue
                hucre(x, 0, w, baslik_h, sol=(sira == 0), ust=True)

        try:
            tablo_h = tree.winfo_height()
        except tk.TclError:
            return
        y = son_alt if son_alt is not None else (baslik_h or 26)
        guvenlik = 0
        while y + rh <= tablo_h and guvenlik < 40 and kolon_xw:
            for sira, (x, w) in enumerate(kolon_xw):
                if x + w < 0:
                    continue
                hucre(x, y, w, rh, sol=(sira == 0), ust=False)
            y += rh
            guvenlik += 1

    def _satir_tablo_yenile(self):
        for i in self.satir_tablo.get_children():
            self.satir_tablo.delete(i)
        if not self.satirlar:
            # Boş durum satırı (bilgi)
            kolonlar = getattr(self, "_satir_kolonlar", ()) or ()
            if kolonlar:
                bos = [""] * len(kolonlar)
                if "ad" in kolonlar:
                    bos[list(kolonlar).index("ad")] = "Henüz ürün eklenmedi"
                elif len(bos) > 2:
                    bos[2] = "Henüz ürün eklenmedi"
                self.satir_tablo.insert("", "end", values=tuple(bos), tags=("tek",))
            self.after_idle(self._teklif_excel_cizgileri_yenile)
            return
        maliyeti_goster = maliyet_izinli()

        def _sat_goster(deger):
            """Hesaplanmamış satış fiyatı/tutarı boş göster (0 ile karışmasın)."""
            if deger is None:
                return ""
            try:
                if isinstance(deger, str) and not deger.strip():
                    return ""
            except Exception:
                pass
            return _para(deger)

        for sira, s in enumerate(self.satirlar):
            hesapli = bool(s.get("fiyat_hesaplandi")) or (
                s.get("teklif_fiyati") is not None
                and _decimal(s.get("teklif_fiyati") or 0) > 0
                and not s.get("yeniden_hesaplanmali")
            )
            # Kayıtlı teklif: fiyat varsa hesaplanmış say
            if s.get("teklif_fiyati") is not None and s.get("fiyat_hesaplandi") is None:
                if _decimal(s.get("teklif_fiyati") or 0) > 0:
                    hesapli = True
                    s["fiyat_hesaplandi"] = True
            om = "M" if s.get("is_manual_price") else ("?" if not hesapli else "O")
            alis = s.get("purchase_unit_price_base") or s.get("birim_maliyet") or 0
            manuel = bool(s.get("is_manual_item") or s.get("manuel"))
            tur = "M" if manuel else ("H" if s.get("hizmet_satiri") else "S")
            tags = ["cift" if sira % 2 else "tek"]
            if maliyeti_goster and (
                _decimal(alis) <= 0 or s.get("cost_status") == "EKSIK" or s.get("margin_unavailable")
            ):
                tags.append("maliyet_yok")
            if manuel:
                tags.append("manuel_satir")
            if s.get("yeniden_hesaplanmali") and not hesapli:
                tags.append("yeniden_hesap")
            marj_metin = (
                ""
                if not hesapli
                else (
                    "Eksik Maliyet"
                    if s.get("margin_unavailable") or s.get("cost_status") == "EKSIK"
                    else _para(s.get("gercek_marj", s.get("actual_margin_rate", 0)))
                )
            )
            fiyat_g = _sat_goster(s.get("teklif_fiyati") if hesapli else None)
            toplam_g = _sat_goster(s.get("satir_toplam") if hesapli else None)
            net_g = _sat_goster(s.get("net_birim_fiyat") if hesapli else None)
            if maliyeti_goster:
                vals = (
                    tur,
                    s["urun_kodu"],
                    s["urun_adi"],
                    _para(s["miktar"]),
                    s["birim"],
                    "—" if (manuel and s.get("cost_status") == "EKSIK") else _para(alis),
                    s.get("maliyet_kaynagi") or ("MANUEL" if manuel else ""),
                    fiyat_g,
                    om,
                    _para(s.get("iskonto_orani", 0)) if hesapli else "",
                    _para(s["kdv_orani"]),
                    toplam_g,
                    marj_metin,
                )
            else:
                vals = (
                    tur,
                    s["urun_kodu"],
                    s["urun_adi"],
                    _para(s["miktar"]),
                    s["birim"],
                    fiyat_g,
                    _para(s.get("iskonto_orani", 0)) if hesapli else "",
                    _para(s["kdv_orani"]),
                    net_g,
                    toplam_g,
                )
            self.satir_tablo.insert("", "end", values=vals, tags=tuple(tags))
        try:
            self.satir_tablo.tag_configure("yeniden_hesap", foreground="#B45309")
        except tk.TclError:
            pass
        self.after_idle(self._teklif_excel_cizgileri_yenile)

    def _fiyat_ozet_guncelle(self):
        """Üst panelde uzun açıklama gösterilmez."""
        return

    def _fiyatlari_hesapla(self):
        if not self.satirlar:
            messagebox.showinfo("Fiyat", "Önce satır ekleyin.", parent=self)
            return
        eksik = [
            s
            for s in self.satirlar
            if (s.get("is_manual_item") or s.get("manuel"))
            and (
                s.get("cost_status") == "EKSIK"
                or _decimal(s.get("purchase_unit_price_base") or s.get("birim_maliyet") or 0) <= 0
            )
        ]
        skip_missing = False
        if eksik:
            secim = messagebox.askyesnocancel(
                "Eksik Maliyet",
                "Manuel ürünün alış maliyeti girilmemiş satırlar var.\n\n"
                "Evet = Bu satırları dağıtım dışında bırak (fiyatları koru)\n"
                "Hayır = İşlemi iptal et — önce maliyet veya manuel satış fiyatı girin\n"
                "İptal = Vazgeç",
                parent=self,
            )
            if secim is None or secim is False:
                return
            skip_missing = True
            for s in eksik:
                s["is_manual_price"] = True
                s["margin_unavailable"] = True
                s["cost_status"] = "EKSIK"
        manuel_var = any(s.get("is_manual_price") for s in self.satirlar)
        manuel_koru = False
        if manuel_var:
            secim = messagebox.askyesnocancel(
                "Manuel Fiyatlar",
                "Manuel fiyatlı satırlar var.\n\n"
                "Evet = Tümünü Yeniden Hesapla\n"
                "Hayır = Manuel Fiyatları Koru\n"
                "İptal = Vazgeç",
                parent=self,
            )
            if secim is None:
                return
            manuel_koru = not secim
        try:
            profit_rate = _decimal(self.fiyat_girdiler["profit_rate"].get() or 0)
            fixed = _decimal(self.fiyat_girdiler["fixed_profit_amount"].get() or 0)
            cust = _decimal(self.fiyat_girdiler["customer_expense_amount"].get() or 0)
            internal = _decimal(self.fiyat_girdiler["internal_expense_amount"].get() or 0)
            yuvarlama = self.fiyat_girdiler["yuvarlama"].get() or "kurus"
            self._fiyat_geri_al = [dict(s) for s in self.satirlar]
            sonuc = dagitimli_hesapla(
                self.satirlar,
                profit_rate=profit_rate,
                fixed_profit_amount=fixed,
                customer_expense_amount=cust,
                internal_expense_amount=internal,
                yuvarlama=yuvarlama,
                manuel_koru=manuel_koru,
                skip_missing_manual_cost=skip_missing,
            )
            self.satirlar = sonuc.satirlar
            for s in self.satirlar:
                s["fiyat_hesaplandi"] = True
                s["yeniden_hesaplanmali"] = False
            self._fiyat_ozet = {
                "total_purchase_cost": sonuc.total_purchase_cost,
                "customer_expense_amount": sonuc.customer_expense_amount,
                "internal_expense_amount": sonuc.internal_expense_amount,
                "percentage_profit_amount": sonuc.percentage_profit_amount,
                "fixed_profit_amount": sonuc.fixed_profit_amount,
                "total_target_profit": sonuc.total_target_profit,
                "actual_profit_amount": sonuc.actual_profit_amount,
                "cost_markup_rate": sonuc.cost_markup_rate,
                "sales_margin_rate": sonuc.sales_margin_rate,
                "calculated_offer_subtotal": sonuc.calculated_offer_subtotal,
            }
            self._satir_tablo_yenile()
            self._toplam_guncelle()
            self._fiyat_ozet_guncelle()
        except ValueError as hata:
            messagebox.showerror("Fiyatlandırma", str(hata), parent=self)

    def _fiyat_geri_al_uygula(self):
        if not self._fiyat_geri_al:
            messagebox.showinfo("Geri Al", "Geri alınacak hesaplama yok.", parent=self)
            return
        self.satirlar = [dict(s) for s in self._fiyat_geri_al]
        self._fiyat_geri_al = None
        self._satir_tablo_yenile()
        self._toplam_guncelle()
        messagebox.showinfo("Geri Al", "Önceki fiyatlar geri yüklendi.", parent=self)

    def _masraf_detay(self):
        dlg = tk.Toplevel(self)
        dlg.title("Masraf Detayı")
        dlg.geometry("640x360")
        dlg.transient(self)
        dlg.grab_set()
        kolonlar = ("tur", "aciklama", "tutar", "musteri")
        tablo = ttk.Treeview(dlg, columns=kolonlar, show="headings", height=10)
        for c, b in zip(kolonlar, ("Tür", "Açıklama", "Tutar", "Müşteriye")):
            tablo.heading(c, text=b)
            tablo.column(c, width=120 if c != "aciklama" else 220)
        tablo.pack(fill="both", expand=True, padx=8, pady=8)

        def yenile():
            for i in tablo.get_children():
                tablo.delete(i)
            for m in self.masraflar:
                tablo.insert(
                    "",
                    "end",
                    values=(
                        m.get("expense_type") or "",
                        m.get("description") or "",
                        _para(m.get("amount", 0)),
                        "Evet" if m.get("is_customer_chargeable", True) else "Hayır",
                    ),
                )

        def ekle():
            tur = simpledialog.askstring(
                "Masraf Türü",
                "Tür (" + ", ".join(MASRAF_TURLERi) + "):",
                parent=dlg,
            )
            if not tur:
                return
            acik = simpledialog.askstring("Açıklama", "Açıklama:", parent=dlg) or ""
            tutar_m = simpledialog.askstring("Tutar", "Tutar:", parent=dlg)
            if tutar_m is None:
                return
            try:
                tutar = _decimal(tutar_m, "Tutar")
            except ValueError as hata:
                messagebox.showerror("Masraf", str(hata), parent=dlg)
                return
            musteriye = messagebox.askyesno("Masraf", "Müşteriye yansıtılsın mı?", parent=dlg)
            self.masraflar.append(
                {
                    "expense_type": tur.strip() or "Diğer",
                    "description": acik.strip() or None,
                    "amount": tutar,
                    "currency": "TRY",
                    "exchange_rate": Decimal("1"),
                    "base_amount": tutar,
                    "is_customer_chargeable": bool(musteriye),
                }
            )
            _masraf_paneli_guncelle()
            yenile()

        def sil():
            sec = tablo.selection()
            if not sec:
                return
            idx = tablo.index(sec[0])
            if 0 <= idx < len(self.masraflar):
                del self.masraflar[idx]
            _masraf_paneli_guncelle()
            yenile()

        def _masraf_paneli_guncelle():
            musteri = sum(
                (_decimal(m.get("base_amount") or m.get("amount") or 0) for m in self.masraflar if m.get("is_customer_chargeable", True)),
                Decimal("0"),
            )
            ic = sum(
                (_decimal(m.get("base_amount") or m.get("amount") or 0) for m in self.masraflar if not m.get("is_customer_chargeable", True)),
                Decimal("0"),
            )
            e = self.fiyat_girdiler["customer_expense_amount"]
            e.delete(0, "end")
            e.insert(0, str(musteri))
            e2 = self.fiyat_girdiler["internal_expense_amount"]
            e2.delete(0, "end")
            e2.insert(0, str(ic))

        alt = ttk.Frame(dlg)
        alt.pack(fill="x", padx=8, pady=6)
        ttk.Button(alt, text="Ekle", command=ekle).pack(side="left", padx=4)
        ttk.Button(alt, text="Sil", command=sil).pack(side="left", padx=4)
        ttk.Button(alt, text="Kapat", command=dlg.destroy).pack(side="right", padx=4)
        yenile()

    def _toplam_guncelle(self):
        from database.fatura_genel_toplam_service import kurus

        tot = QuotePricingService.satir_toplamlari(self.satirlar)
        satir_brut = kurus(tot["genel_toplam"])  # KDV dahil satır toplamı = Brüt ölçümü
        brut_ref = self._uzlasilan_brut_referans(satir_brut)
        try:
            fark = self._uzlasilan_indirim_masraf(brut_ref)
        except ValueError as hata:
            messagebox.showerror("Uzlaşılan tutar", str(hata), parent=self)
            fark = {
                "brut": brut_ref,
                "indirim_tutari": Decimal("0.00"),
                "indirim_orani": Decimal("0"),
                "masraf_tutari": Decimal("0.00"),
                "masraf_orani": Decimal("0"),
                "net": brut_ref,
                "islem_turu": "",
                "islem_tutari": Decimal("0.00"),
                "islem_orani": Decimal("0"),
            }
        net_toplam = kurus(fark["net"])
        self._hesaplanan_genel = net_toplam
        self._teklif_satir_brut = kurus(fark["brut"])
        self._genel_islem_turu = fark.get("islem_turu") or ""
        self._genel_islem_orani = fark.get("islem_orani") or Decimal("0")
        self._genel_islem_tutari = fark.get("islem_tutari") or Decimal("0.00")
        self._indirim_tutari = fark.get("indirim_tutari") or Decimal("0.00")
        self._indirim_orani = fark.get("indirim_orani") or Decimal("0")
        self._masraf_tutari = fark.get("masraf_tutari") or Decimal("0.00")
        self._masraf_orani = fark.get("masraf_orani") or Decimal("0")

        if hasattr(self, "teklif_toplam_degerleri"):
            goster = {
                "ara_toplam": tot["ara_toplam"],
                "iskonto": tot["iskonto_toplam"],
                "matrah": tot["ara_toplam"],
                "kdv": tot["kdv_toplam"],
                "brut": self._teklif_satir_brut,
                "indirim": self._indirim_tutari,
                "masraf": self._masraf_tutari,
                "genel": net_toplam,
            }
            for anahtar, deger in goster.items():
                self._toplam_etiket_yaz(anahtar, deger)
            self._toplam_oran_yaz("indirim", self._indirim_orani)
            self._toplam_oran_yaz("masraf", self._masraf_orani)
            if hasattr(self, "_teklif_islem_alanlarini_yaz"):
                self._teklif_islem_alanlarini_yaz()
            doviz_w = self.teklif_toplam_degerleri.get("doviz")
            if doviz_w is not None:
                try:
                    karsilik = self._teklif_doviz_karsilik_pb_al()
                    doc_pb = (
                        self.girdiler.get("para_birimi")
                        and self.girdiler["para_birimi"].get()
                        or "TRY"
                    ).upper()
                    if karsilik in ("USD", "EUR"):
                        ham = ""
                        try:
                            ham = (self.doviz_karsilik_kur.get() or "").strip()
                        except (tk.TclError, AttributeError):
                            ham = ""
                        kur = _decimal(ham or 0) if ham else Decimal("0")
                        if kur > 0:
                            if doc_pb in ("TRY", "TL"):
                                doviz = (net_toplam / kur).quantize(Decimal("0.01"))
                            elif doc_pb == karsilik:
                                doviz = net_toplam.quantize(Decimal("0.01"))
                            else:
                                # Belge dövizi → TL → karşılık dövizi
                                bel_kur = _decimal(
                                    self.girdiler.get("kur")
                                    and self.girdiler["kur"].get()
                                    or 1
                                )
                                tl = (
                                    (net_toplam * bel_kur).quantize(Decimal("0.01"))
                                    if bel_kur > 0
                                    else net_toplam
                                )
                                doviz = (tl / kur).quantize(Decimal("0.01"))
                            doviz_w.configure(text=f"{_para(doviz)} {karsilik}")
                        else:
                            doviz_w.configure(text="—")
                    elif doc_pb in ("USD", "EUR"):
                        kur = _decimal(
                            self.girdiler.get("kur") and self.girdiler["kur"].get() or 1
                        )
                        if kur > 0:
                            # Belge dövizinde net → TL karşılığı
                            tl = (net_toplam * kur).quantize(Decimal("0.01"))
                            doviz_w.configure(text=f"{_para(tl)} TRY")
                        else:
                            doviz_w.configure(text="—")
                    else:
                        doviz_w.configure(text="—")
                except Exception:
                    try:
                        doviz_w.configure(text="—")
                    except tk.TclError:
                        pass

        # Maliyet özeti (fiyat paneli)
        if maliyet_izinli() and hasattr(self, "lbl_fiyat_ozet"):
            try:
                self.lbl_fiyat_ozet.configure(
                    text=(
                        f"Maliyet: {_para(tot['toplam_maliyet'])}  |  "
                        f"Kâr: {_para(tot['brut_kar'])}  |  "
                        f"Marj: {_para(tot['gercek_marj'])}%  |  "
                        f"Maliyet üstü: {_para(tot['maliyet_ustu_oran'])}%"
                    )
                )
            except tk.TclError:
                pass

    def _veriler(self) -> tuple[dict, list]:
        cari = self._secili_musteri()
        tahmini = None
        tahmini_metin = (self.girdiler["estimated_delivery_date"].get() or "").strip()
        if tahmini_metin:
            tahmini = _parse_tarih(tahmini_metin)
        gun_metin = (self.girdiler["delivery_term_days"].get() or "").strip()
        gun = int(gun_metin) if gun_metin else None
        ozet = self._fiyat_ozet or {}
        return (
            {
                "teklif_no": (
                    None
                    if (self.teklif and self.teklif.id)
                    else (
                        (self.girdiler["teklif_no"].get() or "").strip()
                        or None
                    )
                ),
                "teklif_tarihi": _parse_tarih(self.girdiler["teklif_tarihi"].get()),
                "gecerlilik_tarihi": _parse_tarih(self.girdiler["gecerlilik_tarihi"].get()),
                "gecerlilik_gunu": int(self.girdiler["gecerlilik_gunu"].get() or 30),
                "cari_id": cari.id if cari else None,
                "aday_musteri_adi": (
                    (self.girdiler["aday_musteri_adi"].get() or "").strip()
                    or None
                ),
                "musteri_yetkilisi": self.girdiler["musteri_yetkilisi"].get().strip() or None,
                "musteri_telefon": self.girdiler["musteri_telefon"].get().strip() or None,
                "musteri_email": self.girdiler["musteri_email"].get().strip() or None,
                "satis_temsilcisi": self.girdiler["satis_temsilcisi"].get().strip() or None,
                "konu": self.girdiler["konu"].get().strip() or None,
                "referans_no": self.girdiler["referans_no"].get().strip() or None,
                "para_birimi": (self.para_birimi.get() or "TRY").strip().upper() or "TRY",
                "kur": _decimal(self.girdiler["kur"].get() or 1, "Kur"),
                "kur_tarihi": getattr(self, "_teklif_kur_tarihi", None) or self._teklif_kur_tarihi_al(),
                "kur_turu": getattr(self, "_teklif_kur_turu", None) or "effective_buying",
                "kur_sabitlendi": (self.para_birimi.get() or "TRY").upper() == "TRY",
                **self._odeme_alanlari_oku(),
                "teslim_suresi": self.girdiler["teslim_suresi"].get().strip() or None,
                "depo": self.girdiler["depo"].get().strip() or "ANA DEPO",
                "proje": self.girdiler["proje"].get().strip() or None,
                "musteri_notu": self.musteri_notu.get("1.0", "end").strip() or None,
                "ic_not": self.ic_not.get("1.0", "end").strip() or None,
                "ticari_sartlar": self.ticari_sartlar.get("1.0", "end").strip() or None,
                "cost_source": self._secili_maliyet_kaynagi(),
                "profit_rate": _decimal(self.fiyat_girdiler["profit_rate"].get() or 0),
                "fixed_profit_amount": _decimal(
                    self.fiyat_girdiler["fixed_profit_amount"].get() or 0
                ),
                "customer_expense_amount": _decimal(
                    self.fiyat_girdiler["customer_expense_amount"].get() or 0
                ),
                "internal_expense_amount": _decimal(
                    self.fiyat_girdiler["internal_expense_amount"].get() or 0
                ),
                "total_purchase_cost": ozet.get("total_purchase_cost", 0),
                "percentage_profit_amount": ozet.get("percentage_profit_amount", 0),
                "total_target_profit": ozet.get("total_target_profit", 0),
                "calculated_offer_subtotal": ozet.get("calculated_offer_subtotal", 0),
                "actual_profit_amount": ozet.get("actual_profit_amount", 0),
                "cost_markup_rate": ozet.get("cost_markup_rate", 0),
                "sales_margin_rate": ozet.get("sales_margin_rate", 0),
                "delivery_term_type": self.termin_turu.get() or None,
                "delivery_term_days": gun,
                "estimated_delivery_date": tahmini,
                "tahmini_termin": tahmini,
                "delivery_term_note": self.girdiler["delivery_term_note"].get().strip() or None,
                "delivery_term_manual": self._delivery_term_manual,
                "calculation_method": "MALIYET_USTU_KAR",
                "calculated_at": datetime.now() if ozet else None,
                "yuvarlama_yontemi": self.fiyat_girdiler["yuvarlama"].get() or "kurus",
                "masraflar": list(self.masraflar),
                "genel_toplam": getattr(self, "_hesaplanan_genel", None),
                "genel_islem_turu": getattr(self, "_genel_islem_turu", "") or None,
                "genel_islem_orani": getattr(self, "_genel_islem_orani", 0),
                "genel_islem_tutari": getattr(self, "_genel_islem_tutari", 0),
            },
            list(self.satirlar),
        )

    def kaydet(self):
        try:
            self._toplam_guncelle()
            # Kaydette uzlaşılan kesinleşir (= Net)
            net = getattr(self, "_hesaplanan_genel", None)
            if net is not None:
                from database.fatura_genel_toplam_service import kurus

                net = kurus(net)
                self._uzlasilan_tutar = net
                self._uzlasilan_ui_kilit = True
                try:
                    self._uzlasilan_tutar_yaz(net)
                finally:
                    self._uzlasilan_ui_kilit = False
            veriler, satirlar = self._veriler()
            tid = self.teklif.id if self.teklif else None
            self.teklif = QuoteService.kaydet(veriler, satirlar, teklif_id=tid)
            self.result = True
            self._doldur()
            self._buton_durumlari()
            messagebox.showinfo("Kaydedildi", "Teklif kaydedildi.\nStok/cari hareketi oluşmadı.", parent=self)
        except ValueError as hata:
            messagebox.showerror("Teklif", str(hata), parent=self)
        except Exception as hata:
            messagebox.showerror("Teklif", str(hata), parent=self)

    def _durum(self, yeni: str, *, gerekce_iste: bool = False):
        if not self.teklif:
            messagebox.showinfo("Teklif", "Önce kaydedin.", parent=self)
            return
        if yeni in ("MÜŞTERİYE GÖNDERİLDİ", "KABUL EDİLDİ", "KISMEN KABUL"):
            if not self._musteri_cikti_icin_fiyat_zorunlu(yeni):
                return
        if yeni == "MÜŞTERİYE GÖNDERİLDİ":
            try:
                from teklif_print import musteriye_gondermeden_once_kontrol

                musteriye_gondermeden_once_kontrol(self)
            except Exception as exc:
                messagebox.showerror(
                    "Güvenlik",
                    str(exc)
                    if "maliyet" in str(exc).lower()
                    or "kâr" in str(exc).lower()
                    or "karlılık" in str(exc).lower()
                    or "gönderilemedi" in str(exc).lower()
                    else (
                        "Müşteri teklifinde şirket içi maliyet veya kârlılık bilgisi "
                        f"tespit edildi. Belge gönderilemedi.\n\n{exc}"
                    ),
                    parent=self,
                )
                return
        gerekce = None
        if gerekce_iste or yeni in ("İPTAL", "REDDEDİLDİ"):
            gerekce = simpledialog.askstring("Gerekçe", "Gerekçe / neden:", parent=self)
            if not (gerekce or "").strip():
                messagebox.showwarning("Gerekçe", "Gerekçe zorunludur.", parent=self)
                return
        try:
            self.teklif = QuoteService.durum_degistir(self.teklif.id, yeni, gerekce=gerekce)
            if yeni == "MÜŞTERİYE GÖNDERİLDİ":
                try:
                    from database.database import get_session
                    from datetime import datetime as dt

                    with get_session() as session:
                        t = session.get(type(self.teklif), self.teklif.id)
                        if t:
                            t.musteriye_gonderildi_at = dt.now()
                            session.flush()
                except Exception:
                    pass
            self._rozet(self.teklif.durum)
            self._buton_durumlari()
            self.result = True
        except ValueError as hata:
            messagebox.showerror("Durum", str(hata), parent=self)

    def _reddet(self):
        if not self.teklif:
            messagebox.showinfo("Teklif", "Önce kaydedin.", parent=self)
            return
        neden = simpledialog.askstring(
            "Ret Nedeni",
            "Neden (" + ", ".join(RED_NEDENLERI) + "):",
            parent=self,
        )
        if not (neden or "").strip():
            return
        try:
            self.teklif = QuoteService.durum_degistir(
                self.teklif.id, "REDDEDİLDİ", gerekce=neden.strip()
            )
            self._rozet(self.teklif.durum)
            self._buton_durumlari()
            self.result = True
        except ValueError as hata:
            messagebox.showerror("Ret", str(hata), parent=self)

    def _revizyon(self):
        if not self.teklif:
            return
        sebep = simpledialog.askstring("Revizyon", "Revizyon sebebi:", parent=self)
        try:
            yeni = QuoteService.create_revision(self.teklif.id, sebep=sebep)
            messagebox.showinfo("Revizyon", f"Yeni revizyon: {QuoteService.gosterim_no(yeni)}", parent=self)
            self.teklif = yeni
            self._doldur()
            self._buton_durumlari()
            self.result = True
        except ValueError as hata:
            messagebox.showerror("Revizyon", str(hata), parent=self)

    def _siparis_listesi_ac(self):
        """Ana pencerede Alınan Siparişler listesini açar."""
        app = getattr(self, "app", None) or self.master
        if app is None or not hasattr(app, "satis_siparisleri_goster"):
            messagebox.showwarning(
                "Siparişler",
                "Sipariş listesi bu pencereden açılamadı.",
                parent=self,
            )
            return
        try:
            self.grab_release()
        except tk.TclError:
            pass
        try:
            self.iconify()
        except tk.TclError:
            pass
        try:
            app.deiconify()
            app.lift()
            app.focus_force()
        except tk.TclError:
            pass
        try:
            app.satis_siparisleri_goster()
        except Exception as exc:
            messagebox.showerror("Siparişler", str(exc), parent=app)

    def _bagli_siparis_ac(self):
        """Bu teklife bağlı satış siparişini açar."""
        if not self.teklif or not getattr(self.teklif, "siparis_id", None):
            messagebox.showinfo(
                "Sipariş",
                "Bu teklife bağlı sipariş yok.\nÖnce «Kabul Edildi» ile sipariş oluşturun.",
                parent=self,
            )
            return
        try:
            from database.satis_siparisi_service import SatisSiparisiService
            from app import SatisSiparisiDialog

            siparis = SatisSiparisiService.getir(int(self.teklif.siparis_id))
            if not siparis:
                messagebox.showwarning("Sipariş", "Bağlı sipariş bulunamadı.", parent=self)
                return
            try:
                self.grab_release()
            except tk.TclError:
                pass
            dlg = SatisSiparisiDialog(self.app or self.master, siparis)
            self.wait_window(dlg)
            try:
                self.grab_set()
                self.lift()
            except tk.TclError:
                pass
        except Exception as exc:
            messagebox.showerror("Sipariş", str(exc), parent=self)

    def _kabul_edildi(self):
        """Kabul → durum güncelle + otomatik satış siparişi oluştur."""
        onceki_durum = self.teklif.durum if self.teklif else None
        self._durum("KABUL EDİLDİ")
        if not self.teklif:
            return
        if self.teklif.durum not in ("KABUL EDİLDİ", "SİPARİŞE DÖNÜŞTÜ"):
            return
        if self.teklif.siparis_id:
            messagebox.showinfo(
                "Sipariş",
                f"Teklif kabul edildi.\nBağlı sipariş: {self.teklif.siparis_no or self.teklif.siparis_id}",
                parent=self,
            )
            return
        if not self._musteri_cikti_icin_fiyat_zorunlu("Sipariş oluşturma"):
            return
        try:
            sonuc = QuoteConversionService.convert_to_sales_order(self.teklif.id)
            self.teklif = QuoteService.getir(self.teklif.id)
            self._doldur()
            self._buton_durumlari()
            self.result = True
            messagebox.showinfo(
                "Kabul Edildi",
                f"Teklif kabul edildi.\nSatış siparişi oluşturuldu: {sonuc['siparis_no']}",
                parent=self,
            )
        except ValueError as hata:
            messagebox.showerror(
                "Sipariş",
                f"Teklif «Kabul Edildi» olarak işaretlendi"
                f"{f' (önceki: {onceki_durum})' if onceki_durum else ''}.\n"
                f"Ancak satış siparişi oluşturulamadı:\n\n{hata}\n\n"
                "Düzeltmeyi yaptıktan sonra Diğer ▾ → Siparişe Dönüştür ile tekrar deneyin.",
                parent=self,
            )
        except Exception as hata:
            messagebox.showerror("Sipariş", str(hata), parent=self)

    def _siparise(self):
        if not self.teklif:
            return
        if not self._musteri_cikti_icin_fiyat_zorunlu("Sipariş oluşturma"):
            return
        if self.teklif.durum not in ("KABUL EDİLDİ", "KISMEN KABUL"):
            # Kabul edilmemişse önce kabul et, sonra dönüştür
            if not messagebox.askyesno(
                "Sipariş",
                "Teklif henüz kabul edilmemiş.\n"
                "Kabul edilip satış siparişi oluşturulsun mu?",
                parent=self,
            ):
                return
            self._kabul_edildi()
            return
        manuel_satir = any(
            getattr(s, "is_manual_item", False) for s in (self.teklif.satirlar or [])
        ) or any(s.get("is_manual_item") or s.get("manuel") for s in self.satirlar)
        mesaj = (
            "Bu tekliften alınan sipariş oluşturulsun mu?\n"
            "Teklif kaydı silinmez; siparişe bağlanır."
        )
        if manuel_satir:
            mesaj += (
                "\n\nBu siparişte stok kartına bağlanmamış ürünler bulunmaktadır. "
                "Sevkiyat ve stok işlemlerinden önce ürünlerin stok kartına bağlanması gerekir."
            )
        if not messagebox.askyesno("Sipariş", mesaj, parent=self):
            return
        try:
            sonuc = QuoteConversionService.convert_to_sales_order(self.teklif.id)
            messagebox.showinfo(
                "Sipariş",
                f"Sipariş oluştu: {sonuc['siparis_no']}",
                parent=self,
            )
            self.teklif = QuoteService.getir(self.teklif.id)
            self._doldur()
            self._buton_durumlari()
            self.result = True
        except ValueError as hata:
            messagebox.showerror("Sipariş", str(hata), parent=self)

    def _uzat(self):
        if not self.teklif:
            return
        metin = simpledialog.askstring(
            "Geçerlilik", "Yeni geçerlilik tarihi (gg.aa.yyyy):", parent=self
        )
        if not metin:
            return
        try:
            self.teklif = QuoteService.gecerlilik_uzat(self.teklif.id, _parse_tarih(metin))
            self._doldur()
            self._buton_durumlari()
        except ValueError as hata:
            messagebox.showerror("Geçerlilik", str(hata), parent=self)

    def _pasif(self):
        if not self.teklif:
            return
        if not messagebox.askyesno("Pasife Al", "Teklif pasife alınsın mı?", parent=self):
            return
        try:
            QuoteService.pasife_al(self.teklif.id)
            self.result = True
            self.destroy()
        except ValueError as hata:
            messagebox.showerror("Pasif", str(hata), parent=self)

    def _print_kart_hazirla(self):
        """Eski fatura yazdırma yolu — teklif artık CustomerQuoteViewModel kullanır."""
        self._print_belge_turu = "TEKLİF FORMU"
        if not hasattr(self, "fatura_no_alani"):
            self.fatura_no_alani = self.girdiler["teklif_no"]
        for s in self.satirlar:
            s.setdefault("birim_fiyat", s.get("teklif_fiyati"))
            s.setdefault("birim_satis_fiyati", s.get("teklif_fiyati"))

    def _secili_musteri(self):
        kod = ""
        try:
            kod = (self.musteri_kodu.get() or "").strip()
        except (tk.TclError, AttributeError):
            kod = ""
        if kod and getattr(self, "_musteri_kod_map", None):
            cari = self._musteri_kod_map.get(kod)
            if cari is not None:
                return cari
        cid = getattr(self, "_selected_customer_id", None)
        if cid is not None:
            for c in self.musteriler:
                if getattr(c, "id", None) == cid:
                    return c
        return None

    def _musteri_alanlari_yaz(self, kod: str, ad: str) -> None:
        try:
            self.musteri_kodu.delete(0, "end")
            if kod:
                self.musteri_kodu.insert(0, kod)
            self.musteri_adi.delete(0, "end")
            if ad:
                self.musteri_adi.insert(0, ad)
        except (tk.TclError, AttributeError):
            pass

    def _musteri_ara_metin(self) -> str:
        try:
            return (self.musteri_adi.get() or "").strip()
        except (tk.TclError, AttributeError):
            return ""

    def _musteri_unvan_eslesir(self, unvan: str, bloklar: list[str]) -> bool:
        from database.search_service import kayit_bloklari_eslesir, normalize_text

        havuz = normalize_text(unvan or "")
        return kayit_bloklari_eslesir(havuz, bloklar)

    def _musteri_ara_filtre_listesi(self, metin: str | None = None) -> list[str]:
        from database.search_service import tokenize_query

        ara = (metin if metin is not None else self._musteri_ara_metin()).strip()
        if not ara:
            return list(self.musteri_map.keys())
        bloklar = tokenize_query(ara, min_len=2)
        if not bloklar:
            return []
        bulunan: list[str] = []
        for etiket, cari in self.musteri_map.items():
            unvan = getattr(cari, "unvan", None) or ""
            if self._musteri_unvan_eslesir(unvan, bloklar):
                bulunan.append(etiket)
        bulunan.sort(key=lambda e: e.casefold())
        return bulunan

    def _musteri_kod_degisti(self, event=None):
        if event and getattr(event, "keysym", "") in (
            "Up",
            "Down",
            "Return",
            "Escape",
            "Tab",
            "Left",
            "Right",
            "Prior",
            "Next",
            "F2",
        ):
            return
        try:
            kod = (self.musteri_kodu.get() or "").strip()
        except tk.TclError:
            return
        if not kod:
            self._selected_customer_id = None
            return
        cari = (getattr(self, "_musteri_kod_map", {}) or {}).get(kod)
        if cari is not None:
            self._musteri_alanlari_yaz(kod, getattr(cari, "unvan", "") or "")
            self._selected_customer_id = getattr(cari, "id", None)
            self._meta_guncelle()

    def _musteri_kod_enter(self, _event=None):
        try:
            kod = (self.musteri_kodu.get() or "").strip()
        except tk.TclError:
            return "break"
        if not kod:
            return "break"
        cari = (getattr(self, "_musteri_kod_map", {}) or {}).get(kod)
        if cari is not None:
            self._musteri_sec_cari(cari)
        else:
            self._musteri_ara_secim_ac(ara=kod, zorla=True)
        return "break"

    def _musteri_ara_filtrele(self, event=None):
        if event and getattr(event, "keysym", "") in (
            "Up",
            "Down",
            "Return",
            "Escape",
            "Tab",
            "Left",
            "Right",
            "Prior",
            "Next",
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
            "Alt_L",
            "Alt_R",
            "Caps_Lock",
            "F2",
        ):
            return
        metin = self._musteri_ara_metin()
        if len(metin) < 2:
            if getattr(self, "_musteri_arama_after", None):
                try:
                    self.after_cancel(self._musteri_arama_after)
                except tk.TclError:
                    pass
                self._musteri_arama_after = None
            self._musteri_ara_sonuclar = list(self.musteri_map.keys())
            return
        if getattr(self, "_musteri_arama_after", None):
            try:
                self.after_cancel(self._musteri_arama_after)
            except tk.TclError:
                pass
        self._musteri_arama_after = self.after(
            250, lambda m=metin: self._musteri_ara_filtrele_gecikmeli(m)
        )

    def _musteri_ara_filtrele_gecikmeli(self, metin: str):
        self._musteri_arama_after = None
        guncel = self._musteri_ara_metin()
        if guncel != metin:
            return
        self._musteri_ara_sonuclar = self._musteri_ara_filtre_listesi(guncel)
        # Enter / F2 ile seçim; yazarken sonuç listesi hazırlanır

    def _musteri_ara_enter(self, _event=None):
        metin = self._musteri_ara_metin()
        if len(metin) < 2:
            return "break"
        sonuclar = self._musteri_ara_filtre_listesi(metin)
        self._musteri_ara_sonuclar = sonuclar
        if len(sonuclar) == 1:
            self._musteri_sec_etiket(sonuclar[0])
        elif sonuclar:
            self._musteri_ara_secim_ac(ara=metin, zorla=True)
        return "break"

    def _musteri_sec_etiket(self, anahtar: str) -> None:
        if not anahtar:
            return
        cari = self.musteri_map.get(anahtar)
        if cari is None:
            return
        self._musteri_sec_cari(cari)

    def _musteri_sec_cari(self, cari) -> None:
        if not cari:
            return
        anahtar = f"{cari.cari_kodu} - {cari.unvan}"
        if anahtar not in self.musteri_map:
            self.musteri_map[anahtar] = cari
            if cari not in self.musteriler:
                self.musteriler.append(cari)
        kod = (cari.cari_kodu or "").strip()
        if kod:
            self._musteri_kod_map[kod] = cari
        self._musteri_alanlari_yaz(kod, getattr(cari, "unvan", "") or "")
        self._selected_customer_id = getattr(cari, "id", None)
        self._musteri_ara_sonuclar = list(self.musteri_map.keys())
        try:
            self._meta_guncelle()
        except Exception:
            pass

    def _musteri_ara_secim_ac(self, ara=None, zorla=False):
        import sys

        from database.cari_service import CariService
        from database.search_service import tokenize_query

        if ara is None:
            ara = self._musteri_ara_metin()
        if not zorla and not tokenize_query(ara or "", min_len=2):
            return
        etiketler = (
            self._musteri_ara_filtre_listesi(ara)
            if tokenize_query(ara or "", min_len=2)
            else list(self.musteri_map.keys())
        )
        musteriler = [self.musteri_map[e] for e in etiketler if e in self.musteri_map]
        if not musteriler and zorla and not (ara or "").strip():
            musteriler = list(self.musteriler)
        bakiyeler: dict = {}
        ids = [c.id for c in musteriler if getattr(c, "id", None) is not None]
        if ids:
            try:
                bakiyeler = CariService.musteri_bakiyeleri_toplu(ids)
            except Exception:
                bakiyeler = {}
        mod = sys.modules.get("app")
        if mod is not None and hasattr(mod, "MusteriSecimDialog"):
            MusteriSecimDialog = mod.MusteriSecimDialog
        else:
            from app import MusteriSecimDialog
        dlg = MusteriSecimDialog(
            self,
            musteriler=musteriler,
            bakiyeler=bakiyeler,
            ara=ara or "",
            on_select=self._musteri_sec_cari,
            canli_arama=True,
        )
        self.wait_window(dlg)
        try:
            self.musteri_adi.focus_set()
            self.musteri_adi.icursor("end")
        except tk.TclError:
            pass

    def _musteri_listesini_yenile(self) -> None:
        self.musteriler = QuoteService.aktif_musterileri()
        self.musteri_map = {f"{m.cari_kodu} - {m.unvan}": m for m in self.musteriler}
        self._musteri_kod_map = {
            (m.cari_kodu or "").strip(): m
            for m in self.musteriler
            if (m.cari_kodu or "").strip()
        }
        self._musteri_ara_sonuclar = list(self.musteri_map.keys())

    def _yeni_musteri_ekle(self):
        from cari_kart_ui import CariDialog
        from database.cari_service import CariService

        try:
            grup = CariService.aday_musteri_grubunu_garanti()
        except Exception:
            grup = CariService.ADAY_MUSTERI_GRUP

        aday = ""
        try:
            aday = (
                self.girdiler.get("aday_musteri_adi")
                and self.girdiler["aday_musteri_adi"].get()
                or ""
            ).strip()
        except tk.TclError:
            aday = ""
        yetkili = ""
        telefon = ""
        email = ""
        try:
            yetkili = (
                self.girdiler.get("musteri_yetkilisi")
                and self.girdiler["musteri_yetkilisi"].get()
                or ""
            ).strip()
            telefon = (
                self.girdiler.get("musteri_telefon")
                and self.girdiler["musteri_telefon"].get()
                or ""
            ).strip()
            email = (
                self.girdiler.get("musteri_email")
                and self.girdiler["musteri_email"].get()
                or ""
            ).strip()
        except tk.TclError:
            pass

        dialog = CariDialog(self, cari_turu="Müşteri")
        try:
            if "musteri_grubu" in getattr(dialog, "degerler", {}):
                dialog.musteri_grubu_secimini_hazirla()
                dialog.degerler["musteri_grubu"].set(grup)
            if aday and "unvan" in dialog.degerler:
                w = dialog.degerler["unvan"]
                w.delete(0, "end")
                w.insert(0, aday)
            if telefon and "telefon" in dialog.degerler:
                w = dialog.degerler["telefon"]
                w.delete(0, "end")
                w.insert(0, telefon)
            if email and "email" in dialog.degerler:
                w = dialog.degerler["email"]
                w.delete(0, "end")
                w.insert(0, email)
            if hasattr(dialog, "_baslik_rozetlerini_guncelle"):
                dialog._baslik_rozetlerini_guncelle()
        except Exception:
            pass
        self.wait_window(dialog)
        yeni = dialog.result
        if not yeni:
            return
        self._musteri_listesini_yenile()
        self._musteri_sec_cari(yeni)
        try:
            self.girdiler["aday_musteri_adi"].configure(values=self._aday_musteri_secenekleri())
            unvan = (yeni.unvan if yeni else "") or ""
            self._aday_musteri_yaz(unvan)
        except (tk.TclError, KeyError, AttributeError):
            pass
        if yetkili and not (
            self.girdiler.get("musteri_yetkilisi")
            and self.girdiler["musteri_yetkilisi"].get().strip()
        ):
            try:
                self.girdiler["musteri_yetkilisi"].insert(0, yetkili)
            except (tk.TclError, KeyError):
                pass
        self._meta_guncelle()

    def _hesaplanmamis_satis_satirlari(self) -> list[str]:
        """Satış fiyatı henüz üretilmemiş satır etiketleri."""
        eksik = []
        for s in self.satirlar:
            hesapli = bool(s.get("fiyat_hesaplandi"))
            fiyat = s.get("teklif_fiyati")
            if fiyat is None or (not hesapli and _decimal(fiyat or 0) <= 0):
                if s.get("fiyat_hesaplandi") is None and _decimal(fiyat or 0) > 0:
                    continue  # kayıtlı eski teklif
                kod = s.get("urun_kodu") or ""
                ad = (s.get("urun_adi") or "")[:40]
                eksik.append(f"{kod} — {ad}".strip(" —"))
        return eksik

    def _musteri_cikti_icin_fiyat_zorunlu(self, islem_adi: str) -> bool:
        """Ön izleme / PDF / gönderim / sipariş öncesi eksik satış fiyatı engeli."""
        eksik = self._hesaplanmamis_satis_satirlari()
        if not eksik:
            return True
        liste = "\n".join(f"• {x}" for x in eksik[:15])
        if len(eksik) > 15:
            liste += f"\n… +{len(eksik) - 15} satır"
        messagebox.showwarning(
            "Eksik satış fiyatı",
            f"{islem_adi} için önce «Fiyatları Hesapla» ile satış fiyatlarını üretin.\n\n"
            f"Hesaplanmamış satırlar:\n{liste}",
            parent=self,
        )
        return False

    def _onizleme(self):
        """Müşteri Teklif Ön İzlemesi — maliyet/kâr yok."""
        if not self._musteri_cikti_icin_fiyat_zorunlu("Ön izleme"):
            return
        try:
            if not self.teklif:
                self.kaydet()
            from teklif_print import MusteriTeklifOnizlemeDialog

            MusteriTeklifOnizlemeDialog(self, self)
            if self.teklif:
                from database.database import get_session
                from datetime import datetime as dt

                with get_session() as session:
                    t = session.get(type(self.teklif), self.teklif.id)
                    if t:
                        t.pdf_olusturma = dt.now()
                        session.flush()
        except Exception as exc:
            messagebox.showerror("Önizleme", str(exc), parent=self)

    def _pdf(self):
        """Önce önizleme; kullanıcı PDF'i oradan kaydeder. Doğrudan kayıt da mümkün."""
        if not self._musteri_cikti_icin_fiyat_zorunlu("PDF"):
            return
        try:
            if not self.teklif:
                self.kaydet()
            from teklif_print import MusteriTeklifOnizlemeDialog

            MusteriTeklifOnizlemeDialog(self, self)
        except Exception as exc:
            messagebox.showerror("PDF", str(exc), parent=self)

    def _word(self):
        if not self._musteri_cikti_icin_fiyat_zorunlu("Word"):
            return
        try:
            if not self.teklif:
                self.kaydet()
            from teklif_print import MusteriTeklifOnizlemeDialog

            # Ön izleme üzerinden Word (aynı doğrulanmış veri)
            dlg = MusteriTeklifOnizlemeDialog(self, self)
            dlg._word()
        except Exception as exc:
            messagebox.showerror("Word", str(exc), parent=self)

    def _yazdir(self):
        """A4 yazdırma ön izlemesi açar (müşteri formu)."""
        if not self._musteri_cikti_icin_fiyat_zorunlu("Yazdır"):
            return
        try:
            if not self.teklif:
                self.kaydet()
            from teklif_print import MusteriTeklifOnizlemeDialog

            MusteriTeklifOnizlemeDialog(self, self)
        except Exception as exc:
            messagebox.showerror("Yazdır", str(exc), parent=self)

    def _email_hazirla(self):
        try:
            if not self.teklif:
                self.kaydet()
            from teklif_print import musteri_teklif_pdf_uret
            import webbrowser

            pdf = musteri_teklif_pdf_uret(self)
            messagebox.showinfo(
                "E-posta",
                f"PDF hazır:\n{pdf}\n\nE-posta istemcinize ek olarak ekleyebilirsiniz.",
                parent=self,
            )
            webbrowser.open(pdf.resolve().as_uri())
        except Exception as exc:
            messagebox.showerror("E-posta", str(exc), parent=self)

    def _whatsapp_pdf(self):
        try:
            if not self.teklif:
                self.kaydet()
            from teklif_print import MusteriTeklifOnizlemeDialog

            dlg = MusteriTeklifOnizlemeDialog(self, self)
            dlg._whatsapp()
        except Exception as exc:
            messagebox.showerror("WhatsApp", str(exc), parent=self)

    def _sablon_ayarlari(self):
        """Hitap metni ve varsayılan şart maddeleri."""
        from database.teklif_customer_view import (
            load_teklif_sablon_ayarlari,
            save_teklif_sablon_ayarlari,
            DEFAULT_HITAP_METNI,
        )

        ayar = load_teklif_sablon_ayarlari()
        win = tk.Toplevel(self)
        win.title("Teklif Şablon / Hitap Ayarları")
        win.geometry("640x480")
        win.transient(self)
        tk.Label(win, text="Müşteri hitap metni", font=("Segoe UI", 9, "bold")).pack(
            anchor="w", padx=10, pady=(10, 2)
        )
        hitap = tk.Text(win, height=4, wrap="word", font=("Segoe UI", 9))
        hitap.pack(fill="x", padx=10)
        hitap.insert("1.0", ayar.get("hitap_metni") or DEFAULT_HITAP_METNI)
        tk.Label(win, text="Varsayılan şart maddeleri (her satır bir madde)", font=("Segoe UI", 9, "bold")).pack(
            anchor="w", padx=10, pady=(10, 2)
        )
        sart = tk.Text(win, height=10, wrap="word", font=("Segoe UI", 9))
        sart.pack(fill="both", expand=True, padx=10)
        sart.insert("1.0", "\n".join(ayar.get("sart_maddeleri") or []))
        kdv_var = tk.BooleanVar(value=bool(ayar.get("kdv_dahil_fiyat")))
        tk.Checkbutton(
            win, text="Fiyatlar KDV dahil varsayılsın", variable=kdv_var
        ).pack(anchor="w", padx=10, pady=6)

        def _kaydet():
            try:
                data = dict(ayar)
                data["hitap_metni"] = hitap.get("1.0", "end").strip()
                data["sart_maddeleri"] = [
                    x.strip() for x in sart.get("1.0", "end").splitlines() if x.strip()
                ]
                data["kdv_dahil_fiyat"] = bool(kdv_var.get())
                save_teklif_sablon_ayarlari(data)
                messagebox.showinfo("Şablon", "Ayarlar kaydedildi.", parent=win)
                win.destroy()
            except Exception as exc:
                messagebox.showerror("Şablon", str(exc), parent=win)

        tk.Button(win, text="Kaydet", command=_kaydet, bg="#e8b923", relief="flat", padx=12, pady=4).pack(
            pady=10
        )

    def _logo_antet_ayarlari(self):
        try:
            # Mevcut fatura branding / firma ayarları ekranı
            from sistem_ui import firma_branding_goster

            firma_branding_goster(self)
        except Exception:
            try:
                messagebox.showinfo(
                    "Logo / Antet",
                    "Logo ve antet bilgileri Sistem → Firma Ayarları üzerinden düzenlenir.\n"
                    "Telefon, adres, e-posta, web, vergi dairesi ve vergi no firma kartından alınır.",
                    parent=self,
                )
            except Exception as exc:
                messagebox.showerror("Logo / Antet", str(exc), parent=self)

    def _kayitli_ciktilar(self):
        try:
            from teklif_print import teklif_cikti_klasoru, safe_customer_export_name, musteri_teklif_html_uret
            import os

            if not self.teklif:
                messagebox.showinfo("Çıktılar", "Önce teklifi kaydedin.", parent=self)
                return
            vm, _ = musteri_teklif_html_uret(self)
            klasor = teklif_cikti_klasoru()
            adaylar = [
                klasor / safe_customer_export_name(vm, "pdf"),
                klasor / safe_customer_export_name(vm, "docx"),
            ]
            bulunan = [p for p in adaylar if p.is_file()]
            if not bulunan:
                messagebox.showinfo(
                    "Çıktılar",
                    f"Bu teklife ait kayıtlı dosya bulunamadı.\nKlasör: {klasor}",
                    parent=self,
                )
            else:
                messagebox.showinfo(
                    "Çıktılar",
                    "Bulunan dosyalar:\n" + "\n".join(str(p) for p in bulunan),
                    parent=self,
                )
            os.startfile(str(klasor))
        except Exception as exc:
            messagebox.showerror("Çıktılar", str(exc), parent=self)

    def _ic_maliyet_analizi(self):
        try:
            from database.access import maliyet_izinli, kar_izinli

            if not (maliyet_izinli() or kar_izinli()):
                messagebox.showwarning(
                    "Yetki",
                    "İç maliyet analizini görüntüleme yetkiniz yok.",
                    parent=self,
                )
                return
            from teklif_print import IcMaliyetAnaliziDialog

            IcMaliyetAnaliziDialog(self, self)
        except PermissionError as exc:
            messagebox.showwarning("Yetki", str(exc), parent=self)
        except Exception as exc:
            messagebox.showerror("İç Maliyet", str(exc), parent=self)

    def _buton_durumlari(self):
        durum = self.teklif.durum if self.teklif else "TASLAK"
        kilitli = durum in ("SİPARİŞE DÖNÜŞTÜ", "İPTAL")
        for btn in (self.btn_kaydet, self.btn_gonderildi, self.btn_kabul):
            try:
                btn.configure(state="disabled" if kilitli else "normal")
            except tk.TclError:
                pass
        # Kabul sonrası sipariş varsa kabul butonu da kilitli kalsın
        if durum == "KABUL EDİLDİ" and self.teklif and self.teklif.siparis_id:
            try:
                self.btn_kabul.configure(state="disabled")
            except tk.TclError:
                pass
