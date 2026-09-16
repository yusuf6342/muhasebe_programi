"""Teklifler hub, liste ve kart UI — Ray Mobilya kurumsal tema."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, simpledialog, ttk
from typing import Any, Callable

from database.access import maliyet_izinli, yetki_var
from database.session_manager import oturum
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
from database.teklif_service import (
    RED_NEDENLERI,
    TEKLIF_DURUMLARI,
    QuoteService,
)
from database.user_audit import display_user, format_dt
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
        self.teklif = QuoteService.getir(teklif_id) if teklif_id else None
        self.satirlar: list[dict[str, Any]] = []
        self.masraflar: list[dict[str, Any]] = []
        self._fiyat_geri_al: list[dict[str, Any]] | None = None
        self._fiyat_ozet: dict[str, Any] = {}
        self._delivery_term_manual = False
        self.musteriler = QuoteService.aktif_musterileri()
        self.musteri_map = {f"{m.cari_kodu} - {m.unvan}": m for m in self.musteriler}
        self.title("Teklif Formu")
        self.geometry("1180x760")
        self.minsize(980, 620)
        self.configure(bg=ACIK_GRI)
        self.transient(parent)
        self.grab_set()
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self._toolbar_kur()
        self._govde_kur()
        if self.teklif:
            self._doldur()
        else:
            self._yeni_varsayilan()
        self._buton_durumlari()
        self.bind("<F1>", lambda _e: self.kaydet())
        self.bind("<Escape>", lambda _e: self.destroy())

    def _toolbar_kur(self):
        ust = tk.Frame(self, bg=LACIVERT, height=56)
        ust.pack(fill="x")
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
        self.btn_onaya = self._btn(sag, "Onaya Gönder", lambda: self._durum("ONAY BEKLİYOR"), YESIL)
        self.btn_gonderildi = self._btn(
            sag, "Müşteriye Gönderildi", lambda: self._durum("MÜŞTERİYE GÖNDERİLDİ"), "#1565C0"
        )
        self.btn_kabul = self._btn(sag, "Kabul Edildi", lambda: self._durum("KABUL EDİLDİ"), YESIL)
        self.btn_siparis = self._btn(sag, "Sipariş Oluştur", self._siparise, LACIVERT)
        self._btn(sag, "Önizleme", self._onizleme, "#455A64")
        self._btn(sag, "PDF", self._pdf, "#455A64")
        if maliyet_izinli():
            self._btn(sag, "İç Maliyet Analizi", self._ic_maliyet_analizi, TURUNCU)
        diger = tk.Menubutton(
            sag, text="Diğer ▾", bg="#374151", fg=BEYAZ, relief="flat", font=("Segoe UI", 9, "bold")
        )
        menu = tk.Menu(diger, tearoff=0)
        menu.add_command(label="İç Onaylı", command=lambda: self._durum("İÇ ONAYLI"))
        menu.add_command(label="Revizyon Oluştur", command=self._revizyon)
        menu.add_command(label="Reddet…", command=self._reddet)
        menu.add_command(label="İptal…", command=lambda: self._durum("İPTAL", gerekce_iste=True))
        menu.add_command(label="Geçerlilik Uzat…", command=self._uzat)
        menu.add_separator()
        menu.add_command(label="Pasife Al", command=self._pasif)
        diger.configure(menu=menu)
        diger.pack(side="left", padx=3)
        self._btn(sag, "Kapat", self.destroy, "#9E9E9E")

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
        self.canvas = tk.Canvas(self, bg=ACIK_GRI, highlightthickness=0)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.icerik = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.icerik, anchor="nw")
        self.icerik.bind(
            "<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        genel = ttk.LabelFrame(self.icerik, text="Genel Bilgiler", padding=8)
        genel.pack(fill="x", padx=10, pady=6)
        self.girdiler: dict[str, Any] = {}
        self._alan(genel, 0, 0, "Teklif No", "teklif_no", width=28)
        self._alan(genel, 0, 2, "Teklif Tarihi", "teklif_tarihi", width=14)
        self._alan(genel, 1, 0, "Geçerlilik Tarihi", "gecerlilik_tarihi", width=14)
        self._alan(genel, 1, 2, "Geçerlilik Günü", "gecerlilik_gunu", width=8)
        self._alan(genel, 2, 0, "Konu", "konu", width=40)
        self._alan(genel, 2, 2, "Referans No", "referans_no", width=20)

        mus = ttk.LabelFrame(self.icerik, text="Müşteri", padding=8)
        mus.pack(fill="x", padx=10, pady=6)
        ttk.Label(mus, text="Müşteri").grid(row=0, column=0, sticky="w", padx=4)
        self.musteri = ttk.Combobox(mus, values=list(self.musteri_map), width=48, state="readonly")
        self.musteri.grid(row=0, column=1, sticky="ew", padx=4, pady=2)
        self._alan(mus, 1, 0, "Aday Müşteri", "aday_musteri_adi", width=40)
        self._alan(mus, 2, 0, "Yetkili", "musteri_yetkilisi", width=28)
        self._alan(mus, 2, 2, "Telefon", "musteri_telefon", width=18)
        self._alan(mus, 3, 0, "E-posta", "musteri_email", width=28)
        self._alan(mus, 3, 2, "Satış Temsilcisi", "satis_temsilcisi", width=22)

        ticari = ttk.LabelFrame(self.icerik, text="Ticari Şartlar", padding=8)
        ticari.pack(fill="x", padx=10, pady=6)
        self._alan(ticari, 0, 0, "Para Birimi", "para_birimi", width=8)
        self._alan(ticari, 0, 2, "Kur", "kur", width=12)
        self._alan(ticari, 1, 0, "Ödeme Şekli", "odeme_sekli", width=28)
        self._alan(ticari, 1, 2, "Teslim Süresi", "teslim_suresi", width=22)
        self._alan(ticari, 2, 0, "Depo", "depo", width=20)
        self._alan(ticari, 2, 2, "Proje", "proje", width=28)
        ttk.Label(ticari, text="Termin Türü").grid(row=3, column=0, sticky="w", padx=4, pady=2)
        self.termin_turu = ttk.Combobox(
            ticari, values=list(TERMIN_TURLERI), width=26, state="readonly"
        )
        self.termin_turu.set(TERMIN_TURLERI[0])
        self.termin_turu.grid(row=3, column=1, sticky="ew", padx=4, pady=2)
        self._alan(ticari, 3, 2, "Termin Süresi (Gün)", "delivery_term_days", width=8)
        self._alan(ticari, 4, 0, "Tahmini Teslim Tarihi", "estimated_delivery_date", width=14)
        self._alan(ticari, 4, 2, "Termin Açıklaması", "delivery_term_note", width=28)
        self.girdiler["delivery_term_days"].bind("<KeyRelease>", self._termin_gun_degisti)
        self.girdiler["delivery_term_days"].bind("<FocusOut>", self._termin_gun_degisti)
        self.girdiler["teklif_tarihi"].bind("<FocusOut>", self._termin_gun_degisti)
        self.girdiler["estimated_delivery_date"].bind("<KeyRelease>", self._termin_manuel_isaretle)

        orta = ttk.Frame(self.icerik)
        orta.pack(fill="both", expand=True, padx=10, pady=6)
        orta.columnconfigure(0, weight=3)
        orta.columnconfigure(1, weight=1)

        urun = ttk.LabelFrame(orta, text="Ürünler", padding=8)
        urun.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
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
        self._satir_kolonlar = kolonlar
        self.satir_tablo = ttk.Treeview(urun, columns=kolonlar, show="headings", height=10)
        for c in kolonlar:
            self.satir_tablo.heading(c, text=basliklar[c])
            self.satir_tablo.column(
                c,
                width=48 if c == "tur" else (72 if c != "ad" else 160),
                anchor="w",
            )
        self.satir_tablo.pack(fill="both", expand=True)
        self.satir_tablo.bind("<Double-1>", self._satir_cift_tik)
        self.satir_tablo.tag_configure("maliyet_yok", foreground=KIRMIZI)
        self.satir_tablo.tag_configure("manuel_satir", foreground="#6D28D9")
        self.satir_tablo.bind("<Button-3>", self._satir_sag_menu)
        self._secili_urun: dict[str, Any] | None = None
        self._urun_sec_pencere = None

        satir_alt = ttk.Frame(urun)
        satir_alt.pack(fill="x", pady=4)
        satir_alt.columnconfigure(3, weight=1)

        ttk.Label(satir_alt, text="Ürün Kodu").grid(row=0, column=0, sticky="w", padx=(0, 2))
        self.urun_kod = ttk.Entry(satir_alt, width=12)
        self.urun_kod.grid(row=0, column=1, sticky="w", padx=2)
        self.urun_kod.bind("<Return>", self._urun_getir)

        ttk.Label(satir_alt, text="Ürün Adı / Ara").grid(row=0, column=2, sticky="w", padx=(8, 2))
        self.urun_ad_ara = ttk.Entry(satir_alt)
        self.urun_ad_ara.grid(row=0, column=3, sticky="ew", padx=2, ipadx=4)
        try:
            self.urun_ad_ara.configure(width=36)
        except tk.TclError:
            pass
        # Placeholder benzeri silik yardımcı metin
        self._urun_ara_placeholder = "Ürün adından en az 3 harf yazın…"
        self.urun_ad_ara.insert(0, self._urun_ara_placeholder)
        self.urun_ad_ara.configure(foreground="#94A3B8")
        self.urun_ad_ara.bind("<FocusIn>", self._urun_ara_focus_in)
        self.urun_ad_ara.bind("<FocusOut>", self._urun_ara_focus_out)

        ttk.Label(satir_alt, text="Miktar").grid(row=0, column=4, sticky="w", padx=(8, 2))
        self.urun_miktar = ttk.Entry(satir_alt, width=8)
        self.urun_miktar.insert(0, "1")
        self.urun_miktar.grid(row=0, column=5, sticky="w", padx=2)
        self.urun_miktar.bind("<Return>", lambda _e: self._satir_ekle())

        ttk.Label(satir_alt, text="Birim").grid(row=0, column=6, sticky="w", padx=(8, 2))
        self.urun_birim = ttk.Combobox(satir_alt, width=8, values=manuel_birim_listesi())
        self.urun_birim.set("Adet")
        self.urun_birim.grid(row=0, column=7, sticky="w", padx=2)

        ttk.Label(satir_alt, text="Depo").grid(row=0, column=8, sticky="w", padx=(8, 2))
        try:
            depo_list = [d.ad for d in StokService.depolar()]
        except Exception:
            depo_list = ["ANA DEPO"]
        if not depo_list:
            depo_list = ["ANA DEPO"]
        self.urun_depo = ttk.Combobox(satir_alt, width=12, values=depo_list)
        self.urun_depo.set(self.girdiler["depo"].get().strip() or depo_list[0])
        self.urun_depo.grid(row=0, column=9, sticky="w", padx=2)

        btn_satir = ttk.Frame(satir_alt)
        btn_satir.grid(row=0, column=10, sticky="e", padx=(8, 0))
        ttk.Button(btn_satir, text="Satır Ekle", command=self._satir_ekle).pack(side="left", padx=2)
        ttk.Button(btn_satir, text="Satır Sil", command=self._satir_sil).pack(side="left", padx=2)
        ttk.Button(btn_satir, text="Stok Listesi", command=self._stok_listesi_ac).pack(
            side="left", padx=2
        )
        ttk.Button(btn_satir, text="+ Manuel Ürün Ekle", command=self._manuel_urun_ekle).pack(
            side="left", padx=2
        )

        satir_alt2 = ttk.Frame(urun)
        satir_alt2.pack(fill="x", pady=(0, 4))
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

        self.fiyat_panel = ttk.LabelFrame(orta, text="Teklif Fiyatlandırma", padding=8)
        self.fiyat_panel.grid(row=0, column=1, sticky="nsew")
        self.fiyat_girdiler: dict[str, Any] = {}
        ttk.Label(self.fiyat_panel, text="Maliyet Üzeri Kâr (%)").grid(row=0, column=0, sticky="w")
        self.fiyat_girdiler["profit_rate"] = ttk.Entry(self.fiyat_panel, width=12)
        self.fiyat_girdiler["profit_rate"].insert(0, "0")
        self.fiyat_girdiler["profit_rate"].grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(self.fiyat_panel, text="Maktu Kâr").grid(row=1, column=0, sticky="w")
        self.fiyat_girdiler["fixed_profit_amount"] = ttk.Entry(self.fiyat_panel, width=12)
        self.fiyat_girdiler["fixed_profit_amount"].insert(0, "0")
        self.fiyat_girdiler["fixed_profit_amount"].grid(row=1, column=1, sticky="ew", pady=2)
        ttk.Label(self.fiyat_panel, text="Teklif Masrafı").grid(row=2, column=0, sticky="w")
        self.fiyat_girdiler["customer_expense_amount"] = ttk.Entry(self.fiyat_panel, width=12)
        self.fiyat_girdiler["customer_expense_amount"].insert(0, "0")
        self.fiyat_girdiler["customer_expense_amount"].grid(row=2, column=1, sticky="ew", pady=2)
        ttk.Label(self.fiyat_panel, text="İç Masraf").grid(row=3, column=0, sticky="w")
        self.fiyat_girdiler["internal_expense_amount"] = ttk.Entry(self.fiyat_panel, width=12)
        self.fiyat_girdiler["internal_expense_amount"].insert(0, "0")
        self.fiyat_girdiler["internal_expense_amount"].grid(row=3, column=1, sticky="ew", pady=2)
        ttk.Label(self.fiyat_panel, text="Yuvarlama").grid(row=4, column=0, sticky="w")
        self.fiyat_girdiler["yuvarlama"] = ttk.Combobox(
            self.fiyat_panel,
            values=["kurus", "1", "5", "10", "psikolojik", "yok"],
            width=10,
            state="readonly",
        )
        self.fiyat_girdiler["yuvarlama"].set("kurus")
        self.fiyat_girdiler["yuvarlama"].grid(row=4, column=1, sticky="ew", pady=2)
        btn_f = ttk.Frame(self.fiyat_panel)
        btn_f.grid(row=5, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(btn_f, text="Fiyatları Hesapla", command=self._fiyatlari_hesapla).pack(
            fill="x", pady=2
        )
        ttk.Button(btn_f, text="Hesaplamayı Geri Al", command=self._fiyat_geri_al_uygula).pack(
            fill="x", pady=2
        )
        ttk.Button(btn_f, text="Masraf Detayı", command=self._masraf_detay).pack(fill="x", pady=2)
        self.lbl_fiyat_ozet = ttk.Label(self.fiyat_panel, text="", justify="left", wraplength=220)
        self.lbl_fiyat_ozet.grid(row=6, column=0, columnspan=2, sticky="nw", pady=4)
        if not maliyet_izinli():
            for w in (
                self.fiyat_girdiler["profit_rate"],
                self.fiyat_girdiler["fixed_profit_amount"],
                self.fiyat_girdiler["internal_expense_amount"],
            ):
                w.grid_remove()
            self.lbl_fiyat_ozet.configure(text="Maliyet/kâr özeti yetki gerektirir.")

        toplam = ttk.LabelFrame(self.icerik, text="Toplamlar", padding=8)
        toplam.pack(fill="x", padx=10, pady=6)
        self.lbl_toplam = ttk.Label(toplam, text="", font=("Segoe UI", 10, "bold"))
        self.lbl_toplam.pack(anchor="w")

        notlar = ttk.LabelFrame(self.icerik, text="Notlar", padding=8)
        notlar.pack(fill="x", padx=10, pady=6)
        ttk.Label(notlar, text="Müşteri Notu").grid(row=0, column=0, sticky="nw")
        self.musteri_notu = tk.Text(notlar, height=3, width=50)
        self.musteri_notu.grid(row=0, column=1, padx=4, pady=2)
        ttk.Label(notlar, text="İç Not").grid(row=1, column=0, sticky="nw")
        self.ic_not = tk.Text(notlar, height=2, width=50)
        self.ic_not.grid(row=1, column=1, padx=4, pady=2)
        ttk.Label(notlar, text="Ticari Şartlar").grid(row=2, column=0, sticky="nw")
        self.ticari_sartlar = tk.Text(notlar, height=3, width=50)
        self.ticari_sartlar.grid(row=2, column=1, padx=4, pady=2)

        gecmis = ttk.LabelFrame(self.icerik, text="İşlem Bilgisi", padding=8)
        gecmis.pack(fill="x", padx=10, pady=6)
        self.lbl_gecmis = ttk.Label(gecmis, text="—")
        self.lbl_gecmis.pack(anchor="w")

    def _alan(self, parent, row, col, baslik, anahtar, width=20):
        ttk.Label(parent, text=baslik).grid(row=row, column=col, sticky="w", padx=4, pady=2)
        e = ttk.Entry(parent, width=width)
        e.grid(row=row, column=col + 1, sticky="ew", padx=4, pady=2)
        self.girdiler[anahtar] = e
        return e

    def _secili_maliyet_kaynagi(self) -> str:
        etiket = self.maliyet_kaynak.get()
        for kod in self._maliyet_kaynak_kodlari:
            if MALIYET_KAYNAK_ETIKET.get(kod, kod) == etiket or kod == etiket:
                return kod
        return "SON_ALIS"

    def _termin_manuel_isaretle(self, _e=None):
        self._delivery_term_manual = True

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

    def _yeni_varsayilan(self):
        bugun = date.today()
        self.girdiler["teklif_no"].insert(0, "Otomatik")
        self.girdiler["teklif_no"].configure(state="readonly")
        self.girdiler["teklif_tarihi"].insert(0, _tarih(bugun))
        self.girdiler["gecerlilik_tarihi"].insert(0, _tarih(bugun + timedelta(days=30)))
        self.girdiler["gecerlilik_gunu"].insert(0, "30")
        self.girdiler["para_birimi"].insert(0, "TRY")
        self.girdiler["kur"].insert(0, "1")
        self.girdiler["depo"].insert(0, "ANA DEPO")
        self.girdiler["delivery_term_days"].insert(0, "7")
        self.girdiler["estimated_delivery_date"].insert(0, _tarih(bugun + timedelta(days=7)))
        if oturum.ad_soyad:
            self.girdiler["satis_temsilcisi"].insert(0, oturum.ad_soyad)
        self._rozet("TASLAK")
        self._meta_guncelle()
        self._toplam_guncelle()
        self._fiyat_ozet_guncelle()

    def _doldur(self):
        t = self.teklif
        assert t
        for alan, deger in (
            ("teklif_no", QuoteService.gosterim_no(t)),
            ("teklif_tarihi", _tarih(t.teklif_tarihi)),
            ("gecerlilik_tarihi", _tarih(t.gecerlilik_tarihi)),
            ("gecerlilik_gunu", str(t.gecerlilik_gunu or "")),
            ("konu", t.konu or ""),
            ("referans_no", t.referans_no or ""),
            ("aday_musteri_adi", t.aday_musteri_adi or ""),
            ("musteri_yetkilisi", t.musteri_yetkilisi or ""),
            ("musteri_telefon", t.musteri_telefon or ""),
            ("musteri_email", t.musteri_email or ""),
            ("satis_temsilcisi", t.satis_temsilcisi or ""),
            ("para_birimi", t.para_birimi or "TRY"),
            ("kur", str(t.kur or 1)),
            ("odeme_sekli", t.odeme_sekli or ""),
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
            self.girdiler[alan].delete(0, "end")
            self.girdiler[alan].insert(0, deger)
        self.girdiler["teklif_no"].configure(state="readonly")
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
            anahtar = f"{t.cari.cari_kodu} - {t.cari.unvan}"
            if anahtar in self.musteri_map:
                self.musteri.set(anahtar)
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
        self._toplam_guncelle()
        self._fiyat_ozet_guncelle()
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
        mus = self.musteri.get() or self.girdiler["aday_musteri_adi"].get() or "—"
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

    def _urun_giris_temizle(self):
        self._secili_urun = None
        self.urun_kod.delete(0, "end")
        if hasattr(self, "_urun_arama"):
            self._urun_arama.temizle()
            self.urun_ad_ara.configure(foreground="#94A3B8")
            if not self.urun_ad_ara.get().strip():
                self.urun_ad_ara.insert(0, self._urun_ara_placeholder)
        self.urun_miktar.delete(0, "end")
        self.urun_miktar.insert(0, "1")
        self.urun_birim.set("Adet")

    def _arama_urun_secildi(self, urun: dict):
        """Arama listesinden seçim → satır giriş alanlarını doldur, miktara odaklan."""
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
        except Exception:
            pass
        self.urun_birim.configure(values=birimler)
        self.urun_birim.set(birim)
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
        net = net_iskontolu(fiyat, isk, 0, 0) if fiyat > 0 else Decimal("0")
        ara = (net * miktar).quantize(Decimal("0.01"))
        kdv_t = (ara * kdv / Decimal("100")).quantize(Decimal("0.01"))
        oran, marj = kar_metrikleri(net, base) if base > 0 and net > 0 else (Decimal("0"), Decimal("0"))
        satir = {
            **veri,
            "urun_kodu": "MANUEL",
            "urun_adi": ad,
            "miktar": miktar,
            "birim": birim,
            "liste_fiyati": fiyat,
            "teklif_fiyati": fiyat,
            "iskonto_orani": isk,
            "iskonto_orani_2": 0,
            "iskonto_orani_3": 0,
            "kdv_orani": kdv,
            "net_birim_fiyat": net,
            "satir_toplam": ara + kdv_t,
            "kar_orani": oran,
            "gercek_marj": marj,
            "fiyat_yontemi": "MANUEL" if is_manual_price else "MALIYET_USTU",
            "final_offer_unit_price": fiyat,
            "is_manual_price": is_manual_price,
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
        menu.add_command(label="Satır Sil", command=self._satir_sil)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

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
                    "kdv_orani": s.get("kdv_orani") or 20,
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
        kdv = Decimal("20")
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
                    kdv = Decimal(str(getattr(kart, "kdv_orani", 20) or 20))
                    manuel = False
        except Exception:
            pass
        if self._secili_urun and not urun_adi:
            ad = (self._secili_urun.get("urun_adi") or ad).strip() or ad
            if self._secili_urun.get("kdv_orani") is not None:
                try:
                    kdv = Decimal(str(self._secili_urun["kdv_orani"]))
                except Exception:
                    pass
            manuel = bool(self._secili_urun.get("manuel")) or manuel

        karar = self._ayni_urun_karar(kod)
        if karar is None:
            return
        if isinstance(karar, str) and karar.startswith("artir:"):
            idx = int(karar.split(":", 1)[1])
            s = self.satirlar[idx]
            yeni_miktar = Decimal(str(s.get("miktar") or 0)) + miktar
            s["miktar"] = yeni_miktar
            net = Decimal(str(s.get("net_birim_fiyat") or s.get("teklif_fiyati") or 0))
            kdv_o = Decimal(str(s.get("kdv_orani") or 20))
            ara = (net * yeni_miktar).quantize(Decimal("0.01"))
            kdv_t = (ara * kdv_o / Decimal("100")).quantize(Decimal("0.01"))
            s["satir_toplam"] = ara + kdv_t
            base = Decimal(str(s.get("purchase_unit_price_base") or s.get("birim_maliyet") or 0))
            s["purchase_total_cost"] = (base * yeni_miktar).quantize(Decimal("0.01"))
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
        if manuel and maliyet_izinli() and snap.birim_maliyet <= 0:
            manuel_m = simpledialog.askstring(
                "Manuel Maliyet",
                "Manuel ürün için alış maliyeti (zorunlu):",
                parent=self,
            )
            if manuel_m is None:
                return
            snap = maliyet_getir(kod, depo, "MANUEL", manuel=_decimal(manuel_m, "Maliyet"))
        if (snap.uyari or snap.birim_maliyet <= 0) and maliyet_izinli() and not manuel:
            messagebox.showwarning(
                "Maliyet",
                snap.uyari or "Alış maliyeti 0 — satır kırmızı işaretlenecek.",
                parent=self,
            )
        fiyat = liste if liste > 0 else Decimal("0")
        net = fiyat
        ara = (net * miktar).quantize(Decimal("0.01"))
        kdv_t = (ara * kdv / Decimal("100")).quantize(Decimal("0.01"))
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
                "net_birim_fiyat": net,
                "satir_toplam": ara + kdv_t,
                "kar_orani": Decimal("0"),
                "gercek_marj": Decimal("0"),
                "fiyat_yontemi": "FIYAT_LISTESI",
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
                "final_offer_unit_price": fiyat,
                "is_manual_price": False,
                "actual_profit_amount": Decimal("0"),
                "actual_margin_rate": Decimal("0"),
                "opsiyonel": False,
                "toplama_dahil": True,
                "kabul_edildi": True,
                "manuel": manuel,
                "stok_id": product_id,
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

    def _satir_tablo_yenile(self):
        for i in self.satir_tablo.get_children():
            self.satir_tablo.delete(i)
        maliyeti_goster = maliyet_izinli()
        for s in self.satirlar:
            om = "M" if s.get("is_manual_price") else "O"
            alis = s.get("purchase_unit_price_base") or s.get("birim_maliyet") or 0
            manuel = bool(s.get("is_manual_item") or s.get("manuel"))
            tur = "M" if manuel else ("H" if s.get("hizmet_satiri") else "S")
            tags = []
            if maliyeti_goster and (
                _decimal(alis) <= 0 or s.get("cost_status") == "EKSIK" or s.get("margin_unavailable")
            ):
                tags.append("maliyet_yok")
            if manuel:
                tags.append("manuel_satir")
            marj_metin = (
                "Eksik Maliyet"
                if s.get("margin_unavailable") or s.get("cost_status") == "EKSIK"
                else _para(s.get("gercek_marj", s.get("actual_margin_rate", 0)))
            )
            if maliyeti_goster:
                vals = (
                    tur,
                    s["urun_kodu"],
                    s["urun_adi"],
                    _para(s["miktar"]),
                    s["birim"],
                    "—" if (manuel and s.get("cost_status") == "EKSIK") else _para(alis),
                    s.get("maliyet_kaynagi") or ("MANUEL" if manuel else ""),
                    _para(s["teklif_fiyati"]),
                    om,
                    _para(s.get("iskonto_orani", 0)),
                    _para(s["kdv_orani"]),
                    _para(s["satir_toplam"]),
                    marj_metin,
                )
            else:
                vals = (
                    tur,
                    s["urun_kodu"],
                    s["urun_adi"],
                    _para(s["miktar"]),
                    s["birim"],
                    _para(s["teklif_fiyati"]),
                    _para(s.get("iskonto_orani", 0)),
                    _para(s["kdv_orani"]),
                    _para(s["net_birim_fiyat"]),
                    _para(s["satir_toplam"]),
                )
            self.satir_tablo.insert("", "end", values=vals, tags=tuple(tags))

    def _fiyat_ozet_guncelle(self):
        if not maliyet_izinli():
            return
        o = self._fiyat_ozet or {}
        self.lbl_fiyat_ozet.configure(
            text=(
                f"Toplam Alış: {_para(o.get('total_purchase_cost', 0))}\n"
                f"Masraf (müşteri): {_para(o.get('customer_expense_amount', 0))}\n"
                f"İç Masraf: {_para(o.get('internal_expense_amount', 0))}\n"
                f"% Kâr Tutarı: {_para(o.get('percentage_profit_amount', 0))}\n"
                f"Maktu Kâr: {_para(o.get('fixed_profit_amount', 0))}\n"
                f"Hedef Kâr: {_para(o.get('total_target_profit', 0))}\n"
                f"Teklif Ara: {_para(o.get('calculated_offer_subtotal', 0))}\n"
                f"Gerçek Kâr: {_para(o.get('actual_profit_amount', 0))}\n"
                f"Maliyet Üstü %: {_para(o.get('cost_markup_rate', 0))}\n"
                f"Satış Marjı %: {_para(o.get('sales_margin_rate', 0))}"
            )
        )

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
        tot = QuotePricingService.satir_toplamlari(self.satirlar)
        metin = (
            f"Brüt: {_para(tot['brut_toplam'])}  |  İskonto: {_para(tot['iskonto_toplam'])}  |  "
            f"Ara: {_para(tot['ara_toplam'])}  |  KDV: {_para(tot['kdv_toplam'])}  |  "
            f"Genel: {_para(tot['genel_toplam'])}"
        )
        if maliyet_izinli():
            metin += (
                f"  |  Maliyet: {_para(tot['toplam_maliyet'])}  |  "
                f"Kâr: {_para(tot['brut_kar'])}  |  Marj: {_para(tot['gercek_marj'])}%  |  "
                f"Maliyet üstü: {_para(tot['maliyet_ustu_oran'])}%"
            )
        self.lbl_toplam.configure(text=metin)

    def _veriler(self) -> tuple[dict, list]:
        cari = self.musteri_map.get(self.musteri.get())
        tahmini = None
        tahmini_metin = (self.girdiler["estimated_delivery_date"].get() or "").strip()
        if tahmini_metin:
            tahmini = _parse_tarih(tahmini_metin)
        gun_metin = (self.girdiler["delivery_term_days"].get() or "").strip()
        gun = int(gun_metin) if gun_metin else None
        ozet = self._fiyat_ozet or {}
        return (
            {
                "teklif_no": None if self.girdiler["teklif_no"].get() == "Otomatik" else None,
                "teklif_tarihi": _parse_tarih(self.girdiler["teklif_tarihi"].get()),
                "gecerlilik_tarihi": _parse_tarih(self.girdiler["gecerlilik_tarihi"].get()),
                "gecerlilik_gunu": int(self.girdiler["gecerlilik_gunu"].get() or 30),
                "cari_id": cari.id if cari else None,
                "aday_musteri_adi": self.girdiler["aday_musteri_adi"].get().strip() or None,
                "musteri_yetkilisi": self.girdiler["musteri_yetkilisi"].get().strip() or None,
                "musteri_telefon": self.girdiler["musteri_telefon"].get().strip() or None,
                "musteri_email": self.girdiler["musteri_email"].get().strip() or None,
                "satis_temsilcisi": self.girdiler["satis_temsilcisi"].get().strip() or None,
                "konu": self.girdiler["konu"].get().strip() or None,
                "referans_no": self.girdiler["referans_no"].get().strip() or None,
                "para_birimi": self.girdiler["para_birimi"].get().strip() or "TRY",
                "kur": _decimal(self.girdiler["kur"].get() or 1, "Kur"),
                "odeme_sekli": self.girdiler["odeme_sekli"].get().strip() or None,
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
            },
            list(self.satirlar),
        )

    def kaydet(self):
        try:
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

    def _siparise(self):
        if not self.teklif:
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
        return self.musteri_map.get(self.musteri.get())

    def _onizleme(self):
        """Müşteri Teklif Ön İzlemesi — maliyet/kâr yok."""
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
        """Müşteri PDF — güvenli şablon."""
        try:
            if not self.teklif:
                self.kaydet()
            from teklif_print import musteri_teklif_pdf_uret, safe_customer_pdf_name, musteri_teklif_html_uret
            from tkinter import filedialog
            from pathlib import Path

            vm, _html = musteri_teklif_html_uret(self)
            yol = filedialog.asksaveasfilename(
                parent=self,
                defaultextension=".pdf",
                initialfile=safe_customer_pdf_name(vm),
                filetypes=[("PDF", "*.pdf")],
            )
            if not yol:
                return
            musteri_teklif_pdf_uret(self, Path(yol))
            messagebox.showinfo("PDF", f"Müşteri teklif PDF kaydedildi:\n{yol}", parent=self)
            if self.teklif:
                from database.database import get_session
                from datetime import datetime as dt

                with get_session() as session:
                    t = session.get(type(self.teklif), self.teklif.id)
                    if t:
                        t.pdf_olusturma = dt.now()
                        session.flush()
        except Exception as exc:
            messagebox.showerror("PDF", str(exc), parent=self)

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
        for btn in (self.btn_kaydet, self.btn_onaya, self.btn_gonderildi, self.btn_kabul):
            try:
                btn.configure(state="disabled" if kilitli else "normal")
            except tk.TclError:
                pass
        siparis_ok = durum in ("KABUL EDİLDİ", "KISMEN KABUL") and not (
            self.teklif and self.teklif.siparis_id
        )
        try:
            self.btn_siparis.configure(state="normal" if siparis_ok else "disabled")
        except tk.TclError:
            pass
