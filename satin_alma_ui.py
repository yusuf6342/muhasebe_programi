"""Satın Alma hub — kurumsal sarı/lacivert kartlar, özet ve alt ekranlar."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, ttk
from birim_hatasi_ui import birim_hatasi_goster
from typing import Callable

from satis_tema import (
    ACIK_BG,
    BEYAZ,
    CIZGI,
    HubKart,
    IKINCIL,
    LACIVERT,
    LACIVERT_HOVER,
    METIN,
    SARI,
    font,
    hub_ust_baslik,
    resolve_ui_font,
    stil_uygula,
    tk_buton,
    treeview_stil,
)

# Giriş kartları her tıklamada yeni boş belge açar; liste kartları kayıtlı belgeleri gösterir.
ISLEM_KARTLARI: tuple[tuple[str, str, str], ...] = (
    ("ALIŞ FATURASI", "Yeni boş alış faturası", "fatura_yeni"),
    ("ALIŞ SİPARİŞİ", "Yeni boş satın alma siparişi", "siparis_yeni"),
    ("ALIŞ İRSALİYESİ", "Yeni boş mal kabul irsaliyesi", "irsaliye_yeni"),
    ("ALIŞ İADE FATURASI", "Yeni boş tedarikçiye iade belgesi", "iade_yeni"),
    ("ALIŞ TEKLİFİ", "Yeni tedarikçi teklifi: fiyat, vade, termin", "teklif_yeni"),
    ("SATIN ALMA TALEPLERİ", "Yeni boş satın alma talebi formu", "talep"),
)

LISTE_KARTLARI: tuple[tuple[str, str, str], ...] = (
    ("ALIŞ FATURALARI LİSTESİ", "Kayıtlı alış faturaları: aç, iade, iptal", "fatura"),
    ("ALIŞ SİPARİŞLERİ LİSTESİ", "Sipariş, termin ve kısmi teslim takibi", "siparis"),
    ("ALIŞ İRSALİYELERİ LİSTESİ", "Mal kabul ve faturalanmamış irsaliyeler", "irsaliye"),
    ("ALIŞ İADE FATURALARI LİSTESİ", "Kayıtlı iadeleri filtrele, aç, iptal et", "iade"),
    ("ALIŞ TEKLİFLERİ LİSTESİ", "Teklifleri aç, karşılaştır ve seç", "teklif"),
    ("SATIN ALMA TALEP LİSTESİ", "Talepleri filtrele, onayla ve siparişe aktar", "talep_liste"),
    ("TEDARİKÇİLER LİSTESİ", "Tüm tedarikçileri listeleyin, filtreleyin ve sıralayın", "tedarikci_liste"),
)

TANIM_KARTLARI: tuple[tuple[str, str, str], ...] = (
    ("TEDARİKÇİ KARTLARI", "Boş tedarikçi kartı açılır; kodla veya isimle hızlı arayın", "tedarikci"),
    ("TEDARİKÇİ FİYAT LİSTELERİ", "Güncel alış fiyatı ve iskonto koşulları", "fiyat"),
    ("MASRAF DAĞITIMI", "Nakliye ve diğer giderleri maliyete dağıt", "masraf"),
    ("PDF / E-FATURA AKTARIM", "PDF/OCR ve gelen e-faturalar", "belge"),
    ("EXCEL VERİ AKTARIM", "Tedarikçi cari ve virman aktarımı", "excel"),
)

SATIN_ALMA_HUB_KARTLARI: tuple[tuple[str, str, str], ...] = ISLEM_KARTLARI + LISTE_KARTLARI + TANIM_KARTLARI

RAPOR_KARTLARI: tuple[tuple[str, str, str], ...] = (
    ("TEDARİKÇİ BAKİYE DURUM", "Ortalama vadeli tedarikçi bakiyeleri", "bakiye"),
    ("TEDARİKÇİ BORÇ VE VADE", "Açık, vadesi geçmiş, ileri vade; ödeme sözleri ayrı", "borc_vade"),
    ("TEDARİKÇİ EKSTRESİ", "Valörlü / ağırlıklı ekstre", "ekstre"),
    ("STOK DETAYLI EKSTRE", "Stok satırlı tedarikçi ekstresi", "stok_ekstre"),
    ("ÖDEME VE TAHSİLAT", "Tarih aralıklı ödeme raporu", "odeme"),
    ("ALIŞ VE İADE ÖZETİ", "Ürün, grup, tedarikçi; KDV hariç / KDV / dahil", "ozet"),
    ("AYLIK ALIŞ ANALİZİ", "Aylara göre alış tutarı ve fatura sayısı", "aylik"),
    ("ALIŞ FİYATI DEĞİŞİMİ", "Önceki ve son gerçekleşmiş alış fiyatı", "fiyat_degisim"),
    ("TEDARİKÇİ FİYAT KARŞILAŞTIRMASI", "Bir ürünün tedarikçi fiyatları, yaşı ve teklifler", "fiyat_karsilastirma"),
    ("BEKLEYEN ALIŞ SİPARİŞLERİ", "Kalan miktar, gecikme ve kalan tutar", "bekleyen_sip"),
    ("FATURASI GELMEYEN İRSALİYELER", "Faturalanmamış mal kabulleri, tahmini tutar", "bekleyen_irs"),
    ("YENİDEN SİPARİŞ ÖNERİSİ", "Stok, bekleyen alış ve satış hızına göre öneri", "yenileme"),
    ("GERÇEK ALIŞ MALİYETİ", "Net alış + nakliye ve diğer masraflar", "maliyet"),
    ("TEDARİKÇİ TESLİMAT PERFORMANSI", "Beklenen ve gerçekleşen teslim, gecikme, kısmi teslimat", "teslimat_perf"),
    ("SATIN ALMA TALEPLERİ TAKİBİ", "Talep → sipariş → teslimat; onaylanan, karşılanan, kalan", "talep_takip"),
    ("AÇIK ALIŞ FATURALARI VE VALÖR", "Rapor tarihindeki açık faturalar, valör günü, yaş grupları", "acik_valor"),
    ("KDV RAPORU", "Belgelerden alış / hesaplanan KDV, oranlar, iadeler, dönem özeti", "kdv"),
)

_SIMGELER = ("◎", "▤", "☰", "▸", "⇄", "▣", "◉", "▦", "◇", "◆", "○", "●")


def __getattr__(ad: str):
    if ad == "SatinAlmaTalepDialog":
        from satin_alma_talep_ui import SatinAlmaTalepDialog

        return SatinAlmaTalepDialog
    raise AttributeError(ad)


def _menu_isaretle(app):
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk is not None:
        kabuk.menu_secili_guncelle("satin_alma")
        return
    for anahtar, dugme in getattr(app, "menu_dugmeleri", {}).items():
        if anahtar == "satin_alma":
            dugme.configure(style="SeciliMenu.TButton")
        elif anahtar == "hizli_satis":
            dugme.configure(style="HizliSatisMenu.TButton")
        else:
            dugme.configure(style="Menu.TButton")


def _nav(app, komut: Callable):
    nav = getattr(app, "nav_ac", None)
    if callable(nav):
        nav(komut)
    else:
        komut()


def acilis_hatasi_goster(app, baslik: str, hata: BaseException) -> None:
    """Ekran/pencere açılamadıysa kullanıcıya nedeni gösterir; beklenmeyen hatayı günlüğe yazar."""
    if isinstance(hata, PermissionError):
        messagebox.showwarning(f"{baslik} — yetki", f"{baslik} açılamadı:\n{hata}", parent=app)
        return
    from uygulama_log import hata_yaz

    yol = hata_yaz(f"{baslik} açılamadı", hata)
    messagebox.showerror(
        f"{baslik} açılamadı",
        f"{baslik} açılırken bir hata oluştu:\n{hata}"
        + (f"\n\nTeknik ayrıntı günlüğe kaydedildi:\n{yol}" if yol else ""),
        parent=app,
    )


def _guvenli(app, baslik: str, komut: Callable) -> Callable:
    def calistir():
        try:
            komut()
        except Exception as hata:  # noqa: BLE001 — Tk geri çağrısında sessizce kaybolmasın
            acilis_hatasi_goster(app, baslik, hata)

    return calistir


def pencereyi_one_getir(pencere) -> None:
    try:
        pencere.deiconify()
        pencere.lift()
        pencere.focus_force()
    except tk.TclError:
        pass


def pencere_ac(app, sinif, *args, baslik: str, **kwargs):
    """Belge penceresini açıp öne getirir; kurulum hatasında yarım pencereyi kapatıp nedeni gösterir."""
    onceki = {str(w) for w in app.winfo_children()}
    try:
        pencere = sinif(app, *args, **kwargs)
    except Exception as hata:  # noqa: BLE001
        for w in app.winfo_children():
            if isinstance(w, tk.Toplevel) and str(w) not in onceki:
                try:
                    w.destroy()
                except tk.TclError:
                    pass
        acilis_hatasi_goster(app, baslik, hata)
        return None
    pencereyi_one_getir(pencere)
    return pencere


def _para(tutar) -> str:
    try:
        from ana_panel_tema import para_tr

        return para_tr(tutar)
    except Exception:
        return f"{float(tutar or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(d) -> str:
    if not d:
        return ""
    if isinstance(d, datetime):
        d = d.date()
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d)


def _ozet_serit(parent, ozet: dict, app=None):
    serit = tk.Frame(parent, bg=ACIK_BG)
    serit.pack(fill="x", padx=16, pady=(8, 0))
    kartlar = (
        ("Bekleyen talep", ozet.get("bekleyen_talep", 0), False),
        ("Açık sipariş", ozet.get("acik_siparis", 0), False),
        ("Geciken teslim", ozet.get("geciken_siparis", 0), True),
        ("Faturalanmamış irs.", ozet.get("faturalanmamis_irsaliye", 0), True),
        ("Yaklaşan borç (7g)", ozet.get("yaklasan_borc", 0), True),
        ("Bu ay alış", _para(ozet.get("bu_ay_alis", 0)), False),
    )
    for i, (baslik, deger, uyari) in enumerate(kartlar):
        serit.columnconfigure(i, weight=1, uniform="ozet")
        kutu = tk.Frame(serit, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        kutu.grid(row=0, column=i, sticky="nsew", padx=4, pady=4)
        tk.Label(
            kutu, text=baslik, bg=BEYAZ, fg=IKINCIL, font=font(9, root=app), anchor="w"
        ).pack(anchor="w", padx=10, pady=(8, 0))
        tk.Label(
            kutu,
            text=str(deger),
            bg=BEYAZ,
            fg=SARI if uyari and str(deger) not in ("0", "0,00") else LACIVERT,
            font=font(16, "bold", app),
            anchor="w",
        ).pack(anchor="w", padx=10, pady=(2, 10))
    return serit


def _kart_izgara(app, parent, kartlar, komut_haritasi: dict[str, Callable], *, sutun: int = 2,
                 min_yukseklik: int = 110, pady: int = 16):
    ızgara = tk.Frame(parent, bg=ACIK_BG)
    ızgara.pack(fill="both", expand=True, padx=16, pady=pady)
    for c in range(sutun):
        ızgara.columnconfigure(c, weight=1, uniform="sa_kart")
    gorunen = [(b, a, k) for b, a, k in kartlar if komut_haritasi.get(k) is not None]
    for i, (baslik, aciklama, anahtar) in enumerate(gorunen):
        komut = komut_haritasi[anahtar]
        r, c = divmod(i, sutun)
        kart = HubKart(
            ızgara,
            baslik=baslik,
            aciklama=aciklama,
            komut=lambda fn=komut, b=baslik: _nav(app, _guvenli(app, b, fn)),
            simge=_SIMGELER[i % len(_SIMGELER)],
        )
        kart.grid(row=r, column=c, sticky="nsew", padx=8, pady=8)
        ızgara.rowconfigure(r, weight=1, minsize=min_yukseklik)


def _bolum_basligi(app, parent, metin: str) -> None:
    satir = tk.Frame(parent, bg=ACIK_BG)
    satir.pack(fill="x", padx=24, pady=(14, 0))
    tk.Frame(satir, bg=SARI, width=5, height=22).pack(side="left", padx=(0, 8))
    tk.Label(satir, text=metin, bg=ACIK_BG, fg=LACIVERT, font=font(12, "bold", app)).pack(side="left")


class AcilirMenuGrubu:
    """Hub içinde tıklanınca hemen altında alt menülerini alt alta açan/kapatan grup başlığı."""

    def __init__(self, app, parent, metin: str, kartlar, komut_haritasi: dict[str, Callable], *,
                 alt_gruplar=None):
        self.metin = metin
        self.cerceve = tk.Frame(parent, bg=ACIK_BG)
        self.cerceve.pack(fill="x", padx=16, pady=(10, 0))
        self.baslik = tk.Frame(self.cerceve, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI,
                               cursor="hand2", takefocus=1)
        self.baslik.pack(fill="x", padx=8)
        tk.Frame(self.baslik, bg=SARI, width=5).pack(side="left", fill="y")
        self.ok = tk.Label(self.baslik, text="▸", bg=BEYAZ, fg=SARI, font=font(14, "bold", app), width=2)
        self.ok.pack(side="left", padx=(8, 0), pady=10)
        self.etiket = tk.Label(self.baslik, text=metin, bg=BEYAZ, fg=LACIVERT, font=font(13, "bold", app),
                               anchor="w")
        self.etiket.pack(side="left", fill="x", expand=True, padx=(4, 12), pady=10)
        for w in (self.baslik, self.ok, self.etiket):
            w.bind("<Button-1>", lambda _e: self.degistir())
        for tus in ("<Return>", "<space>"):
            self.baslik.bind(tus, lambda _e: self.degistir())

        self.alt = tk.Frame(self.cerceve, bg=ACIK_BG)
        for grup_adi, grup_kartlari in alt_gruplar or ((None, kartlar),):
            if grup_adi:
                satir = tk.Frame(self.alt, bg=ACIK_BG)
                satir.pack(fill="x", padx=(40, 8), pady=(10, 0))
                tk.Label(satir, text=grup_adi, bg=ACIK_BG, fg=LACIVERT, font=font(11, "bold", app)).pack(side="left")
            _kart_izgara(app, self.alt, grup_kartlari, komut_haritasi, sutun=1, min_yukseklik=0, pady=2)
            for kart in self.alt.winfo_children()[-1].winfo_children():
                kart.grid_configure(padx=(32, 8), pady=3)
                kart._ic.pack_configure(pady=8)
                kart._lbl_aciklama.configure(wraplength=0)
                kart._lbl_aciklama.pack_configure(pady=(2, 0))

    @property
    def acik(self) -> bool:
        return bool(self.alt.winfo_manager())

    def degistir(self) -> None:
        if self.acik:
            self.alt.pack_forget()
            self.ok.configure(text="▸")
        else:
            self.alt.pack(fill="x", after=self.baslik)
            self.ok.configure(text="▾")


def _tekerlegi_bagla(govde) -> None:
    """Kaydırmalı gövdede fare tekerleği kartların üzerindeyken de çalışsın."""
    def ilet(e):
        try:
            govde.event_generate("<MouseWheel>", delta=e.delta)
        except tk.TclError:
            pass

    def gez(w):
        for c in w.winfo_children():
            c.bind("<MouseWheel>", ilet, add="+")
            gez(c)

    gez(govde)


def _tedarikci_cari_ac(app) -> Callable:
    def ac(cari):
        from cari_kart_ui import CariDialog

        return CariDialog(app, cari, cari_turu="Tedarikçi")

    return ac


def alis_faturasi_yeni(app):
    """Yeni boş alış faturası (kayıt oluşturmaz; kaydedilene kadar veri tabanına yazılmaz)."""
    from alis_ui import AlisFaturasiDialog

    return pencere_ac(app, AlisFaturasiDialog, baslik="Alış Faturası", cari_ac=_tedarikci_cari_ac(app))


def alis_siparisi_yeni(app):
    from alis_ui import AlisSiparisiDialog

    return pencere_ac(app, AlisSiparisiDialog, baslik="Alış Siparişi")


def alis_irsaliyesi_yeni(app):
    from alis_ui import AlisIrsaliyesiDialog

    return pencere_ac(app, AlisIrsaliyesiDialog, baslik="Alış İrsaliyesi")


def alis_teklifi_yeni(app):
    return pencere_ac(app, TedarikciTeklifDialog, baslik="Alış Teklifi")


def satin_alma_talebi_yeni(app):
    from satin_alma_talep_ui import talep_formu_ac

    return talep_formu_ac(app)


def _listede_sec(app, iid: str) -> None:
    def gez(w):
        for c in w.winfo_children():
            if isinstance(c, ttk.Treeview):
                try:
                    if c.exists(iid):
                        c.selection_set(iid)
                        c.focus(iid)
                        c.see(iid)
                        return True
                except tk.TclError:
                    pass
            if gez(c):
                return True
        return False

    try:
        gez(app.icerik)
    except (tk.TclError, AttributeError):
        pass


def belgeden_listeye_git(app, liste_fn: Callable, belge_id=None) -> None:
    """Belge penceresi kapandıktan sonra ilgili listeyi açar ve belgeyi listede seçer."""
    def git():
        try:
            _nav(app, liste_fn)
        except Exception as hata:  # noqa: BLE001
            acilis_hatasi_goster(app, "Liste", hata)
            return
        if belge_id:
            app.after(30, lambda: _listede_sec(app, str(belge_id)))

    app.after(40, git)


def bos_liste_bilgisi(tablo: ttk.Treeview, metin: str, yeni: Callable | None = None,
                      yeni_metin: str = "Yeni") -> None:
    """Liste boşsa tablonun ortasında açıklama ve (yetki varsa) Yeni düğmesi gösterir."""
    eski = getattr(tablo, "_bos_bilgi", None)
    if eski is not None:
        try:
            eski.destroy()
        except tk.TclError:
            pass
        tablo._bos_bilgi = None
    try:
        if tablo.get_children():
            return
        kutu = tk.Frame(tablo, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        tk.Label(kutu, text=metin, bg=BEYAZ, fg=IKINCIL, font=font(10), justify="center",
                 wraplength=420).pack(padx=16, pady=(12, 6))
        if yeni is not None:
            tk_buton(kutu, yeni_metin, yeni, rol="yeni").pack(pady=(0, 12))
        kutu.place(relx=0.5, rely=0.4, anchor="center")
        tablo._bos_bilgi = kutu
    except tk.TclError:
        pass


def secimi_koruyarak(tablo: ttk.Treeview, doldur: Callable[[], None]) -> None:
    """Listeyi yeniden doldurur; önceki seçili kayıt hâlâ varsa yeniden seçer."""
    try:
        secili = tuple(tablo.selection())
        ilk_gorunen = tablo.yview()[0]
    except tk.TclError:
        secili, ilk_gorunen = (), 0.0
    doldur()
    try:
        kalan = [i for i in secili if tablo.exists(i)]
        tablo.yview_moveto(ilk_gorunen)
        if kalan:
            tablo.selection_set(kalan)
            tablo.focus(kalan[0])
            tablo.see(kalan[0])
    except tk.TclError:
        pass


def _yetkili(*anahtarlar: str) -> bool:
    try:
        from database.access import yetki_var

        return bool(yetki_var(*anahtarlar))
    except Exception:
        return True


def _rapor_komutlar(app) -> dict[str, Callable]:
    import satin_alma_rapor_ui as r

    return {
        "bakiye": app.rapor_tedarikci_bakiye_durum,
        "borc_vade": lambda: r.tedarikci_borc_vade_goster(app),
        "ekstre": app.rapor_tedarikci_ekstresi,
        "stok_ekstre": app.rapor_stok_detayli_tedarikci_ekstre,
        "odeme": app.rapor_tahsilat_odeme,
        "ozet": lambda: r.alis_iade_ozeti_goster(app),
        "aylik": getattr(app, "rapor_aylik_alis_analizi", None),
        "fiyat_degisim": lambda: r.fiyat_degisim_raporu_goster(app),
        "fiyat_karsilastirma": lambda: r.tedarikci_fiyat_karsilastirma_goster(app),
        "bekleyen_sip": lambda: r.bekleyen_alis_siparisleri_goster(app),
        "bekleyen_irs": lambda: r.faturasi_gelmeyen_irsaliyeler_goster(app),
        "yenileme": lambda: r.yeniden_siparis_onerisi_goster(app),
        "maliyet": lambda: r.gercek_alis_maliyeti_goster(app),
        "teslimat_perf": lambda: r.tedarikci_teslimat_performansi_goster(app),
        "talep_takip": lambda: r.satin_alma_talep_takibi_goster(app),
        "acik_valor": lambda: r.acik_alis_faturalari_valor_goster(app),
        "kdv": lambda: __import__("kdv_raporu_ui").kdv_raporu_goster(app, "satin_alma"),
    }


def _hub_komutlar(app) -> dict[str, Callable]:
    def belge():
        from fatura_belge_aktarim_ui import fatura_belge_aktarim_goster

        fatura_belge_aktarim_goster(
            app, yon="ALIS", geri_fn=lambda: satin_alma_hub_goster(app)
        )

    def excel():
        from excel_aktarim_ui import excel_aktarim_hub_goster

        excel_aktarim_hub_goster(
            app,
            modul="satin_alma",
            baslik="SATIN ALMA — EXCEL VERİ AKTARIM",
            geri_fn=lambda: satin_alma_hub_goster(app),
        )

    return {
        "fatura_yeni": lambda: alis_faturasi_yeni(app),
        "siparis_yeni": lambda: alis_siparisi_yeni(app),
        "irsaliye_yeni": lambda: alis_irsaliyesi_yeni(app),
        "teklif_yeni": lambda: alis_teklifi_yeni(app),
        "tedarikci": app.tedarikci_karti_ac,
        "tedarikci_liste": app.tedarikciler_goster,
        "talep": lambda: satin_alma_talebi_yeni(app),
        "talep_liste": lambda: satin_alma_talepleri_goster(app),
        "teklif": lambda: tedarikci_teklifleri_goster(app),
        "siparis": app.alis_siparisleri_goster,
        "irsaliye": app.alis_irsaliyeleri_goster,
        "fatura": app.alis_faturalari_goster,
        "iade_yeni": app.alis_iade_faturasi_ac,
        "iade": app.alis_iade_faturalari_goster,
        "masraf": lambda: masraf_dagitimi_goster(app),
        "fiyat": lambda: tedarikci_fiyat_listeleri_goster(app),
        "rapor": lambda: satin_alma_raporlar_hub_goster(app),
        "belge": belge,
        "excel": excel,
    }


def satin_alma_hub_goster(app) -> None:
    """Satın Alma ana hub — özet kartlar + menü."""
    app._icerigi_temizle()
    stil_uygula(root=app)
    _menu_isaretle(app)
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass

    from ui_pencere import kaydirilabilir_govde

    kok = tk.Frame(app.icerik, bg=ACIK_BG)
    kok.pack(fill="both", expand=True)

    hub_ust_baslik(
        kok,
        baslik="SATIN ALMA",
        alt_baslik="Tedarikçi, talep, teklif, sipariş, irsaliye, fatura ve masraf",
        app=app,
        geri_komut=lambda: app.sayfa_goster("giris"),
        geri_metin="Ana Menüye Dön",
    )

    ozet = {}
    try:
        from database.satin_alma_hub_service import SatinAlmaHubService

        ozet = SatinAlmaHubService.ozet_kartlar()
    except Exception:
        ozet = {}
    _ozet_serit(kok, ozet, app=app)
    govde = kaydirilabilir_govde(kok, bg=ACIK_BG)
    komutlar = _hub_komutlar(app)
    rapor_komut = {**komutlar, **_rapor_komutlar(app)}
    app.satin_alma_menu_gruplari = {
        "islem": AcilirMenuGrubu(app, govde, "Satın Alma İşlemleri", ISLEM_KARTLARI + TANIM_KARTLARI, komutlar),
        "rapor": AcilirMenuGrubu(app, govde, "Raporlar", LISTE_KARTLARI + RAPOR_KARTLARI, rapor_komut),
    }
    _tekerlegi_bagla(govde)

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: satin_alma_hub_goster(app))


def satin_alma_raporlar_hub_goster(app) -> None:
    app._icerigi_temizle()
    stil_uygula(root=app)
    _menu_isaretle(app)
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass

    kok = tk.Frame(app.icerik, bg=ACIK_BG)
    kok.pack(fill="both", expand=True)
    hub_ust_baslik(
        kok,
        baslik="SATIN ALMA RAPORLARI",
        alt_baslik="Bakiye, ekstre, ödeme ve faturalanmamış irsaliye kontrolleri",
        app=app,
        geri_komut=lambda: satin_alma_hub_goster(app),
        geri_metin="← Satın Alma",
    )

    _kart_izgara(app, kok, RAPOR_KARTLARI, _rapor_komutlar(app), sutun=3, min_yukseklik=86, pady=6)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: satin_alma_raporlar_hub_goster(app))


# --- Liste ekranları ---


def _liste_ust(app, baslik, alt, geri):
    temizle = getattr(app, "_icerigi_temizle", None)
    if callable(temizle):
        temizle()
    stil_uygula(root=app)
    _menu_isaretle(app)
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass
    kok = tk.Frame(app.icerik, bg=ACIK_BG)
    kok.pack(fill="both", expand=True)
    hub_ust_baslik(
        kok, baslik=baslik, alt_baslik=alt, app=app, geri_komut=geri, geri_metin="← Satın Alma"
    )
    return kok


def satin_alma_talepleri_goster(app) -> None:
    from satin_alma_talep_ui import satin_alma_talep_listesi_goster

    satin_alma_talep_listesi_goster(app)


def tedarikci_teklifleri_goster(app) -> None:
    from database.tedarikci_teklif_service import TedarikciTeklifService

    kok = _liste_ust(
        app,
        "ALIŞ TEKLİFLERİ LİSTESİ",
        "Tedarikçi teklifleri: fiyat, vade, termin ve nakliye ile toplam edinme maliyeti karşılaştırması",
        lambda: satin_alma_hub_goster(app),
    )
    cerceve = ttk.Frame(kok)
    cerceve.pack(fill="both", expand=True, padx=16, pady=8)
    kolonlar = ("no", "tarih", "talep", "durum", "satir", "aciklama")
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    treeview_stil(tablo)
    for k, b, w in (
        ("no", "Teklif No", 110),
        ("tarih", "Tarih", 90),
        ("talep", "Talep Id", 80),
        ("durum", "Durum", 140),
        ("satir", "Satır", 60),
        ("aciklama", "Açıklama", 240),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w)
    tablo.pack(side="left", fill="both", expand=True)
    ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview).pack(side="right", fill="y")

    def doldur():
        for i in tablo.get_children():
            tablo.delete(i)
        for r in TedarikciTeklifService.listele():
            tablo.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["teklif_no"],
                    _tarih(r["teklif_tarihi"]),
                    r["talep_id"] or "",
                    r["durum"],
                    r["satir_adet"],
                    r["aciklama"],
                ),
            )

    yeni_yetki = _yetkili("alis_teklif_duzenleme", "alis_duzenleme", "yeni_kayit")

    def yenile():
        try:
            if not tablo.winfo_exists():
                return
        except tk.TclError:
            return
        secimi_koruyarak(tablo, doldur)
        bos_liste_bilgisi(
            tablo,
            "Kayıtlı alış teklifi yok." + (" Yeni Teklif ile ilk teklifi girin." if yeni_yetki else ""),
            yeni if yeni_yetki else None,
            "Yeni Teklif",
        )

    def karsilastir(_e=None):
        sec = tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Teklif seçin.", parent=app)
            return
        dlg = TeklifKarsilastirmaDialog(app, int(sec[0]))
        app.wait_window(dlg)
        yenile()

    def yeni():
        dlg = TedarikciTeklifDialog(app)
        app.wait_window(dlg)
        yenile()

    tablo.bind("<Double-1>", karsilastir)
    tablo.bind("<Return>", karsilastir)
    alt = tk.Frame(kok, bg=ACIK_BG)
    alt.pack(fill="x", padx=16, pady=10)
    tk_buton(alt, "Yeni Teklif", yeni, rol="yeni", state="normal" if yeni_yetki else "disabled").pack(side="left")
    tk_buton(alt, "Aç", karsilastir, rol="duzenle").pack(side="left", padx=6)
    tk_buton(alt, "Karşılaştır / Seç", karsilastir, rol="duzenle").pack(side="left")
    tk_buton(alt, "Yenile", yenile, rol="ara").pack(side="right")
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: tedarikci_teklifleri_goster(app))


def tedarikci_fiyat_listeleri_goster(app) -> None:
    from database.alis_siparisi_service import AlisSiparisiService
    from database.tedarikci_fiyat_service import TedarikciFiyatService

    kok = _liste_ust(
        app,
        "TEDARİKÇİ FİYAT LİSTELERİ",
        "Tedarikçi + stok bazında güncel alış fiyatı ve iskonto",
        lambda: satin_alma_hub_goster(app),
    )
    arac = tk.Frame(kok, bg=ACIK_BG)
    arac.pack(fill="x", padx=16, pady=8)
    tk.Label(arac, text="Ara:", bg=ACIK_BG).pack(side="left")
    arama = ttk.Entry(arac, width=28)
    arama.pack(side="left", padx=6)

    cerceve = ttk.Frame(kok)
    cerceve.pack(fill="both", expand=True, padx=16, pady=8)
    kolonlar = ("tedarikci", "kod", "ad", "birim", "fiyat", "isk", "pb", "bas", "bit")
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    treeview_stil(tablo)
    for k, b, w in (
        ("tedarikci", "Tedarikçi", 180),
        ("kod", "Stok Kodu", 100),
        ("ad", "Stok Adı", 180),
        ("birim", "Birim", 70),
        ("fiyat", "Fiyat", 90),
        ("isk", "İsk %", 60),
        ("pb", "PB", 50),
        ("bas", "Başlangıç", 90),
        ("bit", "Bitiş", 90),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w)
    tablo.pack(side="left", fill="both", expand=True)

    def yenile():
        for i in tablo.get_children():
            tablo.delete(i)
        for r in TedarikciFiyatService.listele(arama=arama.get()):
            tablo.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["tedarikci"],
                    r["urun_kodu"],
                    r["urun_adi"],
                    r["birim"],
                    _para(r["birim_fiyat"]),
                    _para(r["iskonto_orani"]),
                    r["para_birimi"],
                    _tarih(r["baslangic"]),
                    _tarih(r["bitis"]),
                ),
            )

    def yeni():
        dlg = TedarikciFiyatDialog(app)
        app.wait_window(dlg)
        yenile()

    def pasif():
        sec = tablo.selection()
        if not sec:
            return
        if not messagebox.askyesno("Pasif", "Kayıt pasife alınsın mı?", parent=app):
            return
        try:
            TedarikciFiyatService.pasif_et(int(sec[0]))
        except ValueError as e:
            messagebox.showerror("Hata", str(e), parent=app)
            return
        yenile()

    alt = tk.Frame(kok, bg=ACIK_BG)
    alt.pack(fill="x", padx=16, pady=10)
    tk_buton(alt, "Yeni Fiyat", yeni, rol="yeni").pack(side="left")
    tk_buton(alt, "Pasife Al", pasif, rol="iptal").pack(side="left", padx=6)
    tk_buton(alt, "Yenile", yenile, rol="ara").pack(side="right")
    arama.bind("<Return>", lambda _e: yenile())
    yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: tedarikci_fiyat_listeleri_goster(app))


def masraf_dagitimi_goster(app) -> None:
    from masraf_dagitim_ui import masraf_dagitimi_goster as goster

    goster(app)


def eski_fatura_masraflari_goster(app) -> None:
    """Gider belgesi olmadan faturaya serbest tutar girilen eski masraf kayıtları."""
    from database.alis_masraf_service import MASRAF_TURLERI, YONTEMLER, AlisMasrafService

    kok = _liste_ust(
        app,
        "ESKİ FATURA MASRAFLARI",
        "Gider belgesine bağlı olmayan eski masraf kayıtları (genel muhasebe fişi üretmez)",
        lambda: masraf_dagitimi_goster(app),
    )
    ust = ttk.Panedwindow(kok, orient="horizontal")
    ust.pack(fill="both", expand=True, padx=16, pady=8)
    sol = ttk.Frame(ust)
    sag = ttk.Frame(ust)
    ust.add(sol, weight=2)
    ust.add(sag, weight=2)

    fatura_tablo = ttk.Treeview(
        sol,
        columns=("no", "tarih", "tedarikci", "toplam", "masraf"),
        show="headings",
        selectmode="browse",
        height=16,
    )
    treeview_stil(fatura_tablo)
    for k, b, w in (
        ("no", "Fatura No", 110),
        ("tarih", "Tarih", 90),
        ("tedarikci", "Tedarikçi", 160),
        ("toplam", "Toplam", 90),
        ("masraf", "Masraf", 90),
    ):
        fatura_tablo.heading(k, text=b)
        fatura_tablo.column(k, width=w)
    fatura_tablo.pack(fill="both", expand=True)

    masraf_tablo = ttk.Treeview(
        sag,
        columns=("tur", "tutar", "yontem", "dagitim", "dahil"),
        show="headings",
        selectmode="browse",
        height=12,
    )
    treeview_stil(masraf_tablo)
    for k, b, w in (
        ("tur", "Tür", 100),
        ("tutar", "Tutar", 90),
        ("yontem", "Yöntem", 80),
        ("dagitim", "Dağıtılan", 90),
        ("dahil", "Maliyet", 70),
    ):
        masraf_tablo.heading(k, text=b)
        masraf_tablo.column(k, width=w)
    masraf_tablo.pack(fill="both", expand=True)

    form = tk.Frame(sag, bg=ACIK_BG)
    form.pack(fill="x", pady=8)
    tk.Label(form, text="Tür", bg=ACIK_BG).grid(row=0, column=0, sticky="w")
    tur = ttk.Combobox(form, values=MASRAF_TURLERI, state="readonly", width=14)
    tur.set("NAKLİYE")
    tur.grid(row=0, column=1, padx=4)
    tk.Label(form, text="Tutar", bg=ACIK_BG).grid(row=0, column=2, sticky="w")
    tutar = ttk.Entry(form, width=12)
    tutar.grid(row=0, column=3, padx=4)
    tk.Label(form, text="Yöntem", bg=ACIK_BG).grid(row=1, column=0, sticky="w", pady=4)
    yontem = ttk.Combobox(form, values=YONTEMLER, state="readonly", width=14)
    yontem.set("TUTAR")
    yontem.grid(row=1, column=1, padx=4, pady=4)
    tk.Label(form, text="Kaynak belge", bg=ACIK_BG).grid(row=3, column=0, sticky="w")
    kaynak = ttk.Combobox(form, state="readonly", width=44)
    kaynak.grid(row=3, column=1, columnspan=3, padx=4, sticky="we")
    kaynak_secenek: dict[str, tuple[str | None, int | None]] = {}

    def kaynaklari_yenile():
        kaynak_secenek.clear()
        kaynak_secenek["(seçilmedi — mükerrerlik yalnız benzerlikle denetlenir)"] = (None, None)
        try:
            belgeler = AlisMasrafService.kaynak_belgeler()
        except Exception:
            belgeler = []
        for b in belgeler:
            etiket = f"{b['tur_etiket']} {b['no']} — {b['cari'] or ''} — {_para(b['genel_toplam'])}"
            kaynak_secenek[etiket] = (b["tur"], int(b["id"]))
        kaynak.configure(values=list(kaynak_secenek))
        kaynak.current(0)

    def faturalari_yenile():
        for i in fatura_tablo.get_children():
            fatura_tablo.delete(i)
        for r in AlisMasrafService.fatura_liste_ozet():
            fatura_tablo.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["fatura_no"],
                    _tarih(r["tarih"]),
                    r["tedarikci"],
                    _para(r["genel_toplam"]),
                    _para(r["masraf_toplam"]),
                ),
            )

    def masraflari_yenile(_e=None):
        for i in masraf_tablo.get_children():
            masraf_tablo.delete(i)
        sec = fatura_tablo.selection()
        if not sec:
            return
        for r in AlisMasrafService.masraflari(int(sec[0])):
            masraf_tablo.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["masraf_turu"],
                    _para(r["tutar"]),
                    r["dagitim_yontemi"],
                    _para(r["dagitim_toplam"]),
                    "Evet" if r["maliyete_dahil"] else "Hayır",
                ),
            )

    def ekle():
        sec = fatura_tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Fatura seçin.", parent=app)
            return
        k_tur, k_id = kaynak_secenek.get(kaynak.get(), (None, None))
        onay = False
        while True:
            try:
                AlisMasrafService.kaydet_ve_dagit(
                    int(sec[0]),
                    tur.get(),
                    tutar.get(),
                    yontem=yontem.get(),
                    maliyete_dahil=True,
                    kaynak_turu=k_tur,
                    kaynak_id=k_id,
                    inceleme_onaylandi=onay,
                )
                break
            except ValueError as e:
                if not onay and str(e).startswith("İnceleme gerekli") and messagebox.askyesno(
                    "İnceleme gerekli", f"{e}\n\nBu masrafın FARKLI olduğunu doğruladınız mı?", parent=app
                ):
                    onay = True
                    continue
                if not str(e).startswith("İnceleme gerekli"):
                    messagebox.showerror("Masraf", str(e), parent=app)
                return
        tutar.delete(0, "end")
        faturalari_yenile()
        fatura_tablo.selection_set(sec[0])
        masraflari_yenile()

    def sil():
        sec = masraf_tablo.selection()
        if not sec:
            return
        try:
            AlisMasrafService.sil(int(sec[0]))
        except ValueError as e:
            messagebox.showerror("Sil", str(e), parent=app)
            return
        faturalari_yenile()
        masraflari_yenile()

    tk_buton(form, "Ekle ve Dağıt", ekle, rol="yeni").grid(row=1, column=2, columnspan=2, padx=4)
    tk_buton(form, "Masraf Sil", sil, rol="iptal").grid(row=2, column=0, columnspan=2, pady=6, sticky="w")
    fatura_tablo.bind("<<TreeviewSelect>>", masraflari_yenile)
    faturalari_yenile()
    kaynaklari_yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: eski_fatura_masraflari_goster(app))


def faturalanmamis_irsaliye_raporu_goster(app) -> None:
    from satin_alma_rapor_ui import faturasi_gelmeyen_irsaliyeler_goster

    faturasi_gelmeyen_irsaliyeler_goster(app)


# --- Dialoglar ---


class TedarikciSecDialog(tk.Toplevel):
    def __init__(self, parent, tedarikciler):
        super().__init__(parent)
        self.result = None
        self.title("Tedarikçi Seç")
        self.geometry("420x360")
        self.transient(parent)
        self.grab_set()
        self.vars = []
        ttk.Label(self, text="Teklife dahil edilecek tedarikçiler:").pack(anchor="w", padx=12, pady=8)
        kutu = ttk.Frame(self)
        kutu.pack(fill="both", expand=True, padx=12)
        for t in tedarikciler:
            v = tk.BooleanVar(value=False)
            self.vars.append((int(t.id), v))
            ttk.Checkbutton(kutu, text=f"{t.cari_kodu} — {t.unvan}", variable=v).pack(anchor="w")

        def tamam():
            self.result = [cid for cid, v in self.vars if v.get()]
            if not self.result:
                messagebox.showwarning("Seçim", "En az bir tedarikçi işaretleyin.", parent=self)
                return
            self.destroy()

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=10)
        ttk.Button(alt, text="Tamam", command=tamam).pack(side="right")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=6)


class _SatinAlmaSatirGirisi:
    """Talep / tedarikçi teklifi: ürün tablonun sonundaki boş satırdan girilir (ortak bileşen)."""

    _KOLONLAR: tuple[tuple[str, str, int], ...] = ()
    satirlar: list[dict]

    def _kilitli(self) -> bool:
        return False

    def _yeni_satir(self, degerler) -> dict:
        raise NotImplementedError

    def _satir_degerleri(self, s: dict) -> tuple:
        raise NotImplementedError

    def _hucre_ozel(self, yeni: dict, kolon: str, metin: str) -> None:
        return None

    def _birlesme_anahtari(self, s: dict) -> tuple:
        return (s.get("urun_kodu") or "", (s.get("birim") or "").casefold())

    def _satir_alani_kur(self, parent, alanlar, *, depo: Callable[[], str] = lambda: "") -> None:
        from alis_ui import satin_alma_satir_ozellikleri
        from database.stok_service import StokService
        from satir_ici_urun_giris import SatirHucreDuzenleyici, SatirIciUrunGirisi

        cer = ttk.Frame(parent)
        cer.pack(fill="both", expand=True)
        kaydirma = ttk.Scrollbar(cer, orient="vertical")
        self.satir_tablosu = ttk.Treeview(
            cer, columns=[k for k, _b, _g in self._KOLONLAR], show="headings", height=10,
            selectmode="browse", yscrollcommand=kaydirma.set,
        )
        kaydirma.configure(command=self.satir_tablosu.yview)
        for kolon, baslik, genislik in self._KOLONLAR:
            self.satir_tablosu.heading(kolon, text=baslik)
            self.satir_tablosu.column(
                kolon, width=genislik, anchor="w" if kolon in ("kod", "ad", "aciklama", "tedarikci", "birim") else "e"
            )
        self.satir_tablosu.pack(side="left", fill="both", expand=True)
        kaydirma.pack(side="right", fill="y")
        ttk.Label(
            parent,
            text="Ürün eklemek için son satıra barkod okutun veya ürün adı yazın (F10: stok listesi). "
            "Hücreye çift tıklayarak düzenleyin; Del satırı siler.",
            foreground="#475569",
        ).pack(anchor="w", pady=(4, 0))
        self._satir_ici_giris = SatirIciUrunGirisi(
            self,
            self.satir_tablosu,
            urun_ekle=self._urun_ekle,
            kolonlar={"kod": "kod", "ad": "ad"},
            urun_degistir=self._urun_degistir,
            kilitli=self._kilitli,
            miktara_git=lambda idx: self._hucre.duzenle(idx, "miktar"),
            depo=depo,
            fiyat_turu="alis",
            alis_fiyati=StokService.son_alis_fiyati,
            satir_menusu=self._satir_menusu,
            **satin_alma_satir_ozellikleri(self),
        )
        self._hucre = SatirHucreDuzenleyici(
            self,
            self.satir_tablosu,
            alanlar,
            uygula=self.hucre_uygula,
            satir_sayisi=lambda: len(self.satirlar),
            kilitli=self._kilitli,
            bitince=self._satir_ici_giris.odakla,
        )
        self.satir_tablosu.bind("<Delete>", lambda _e: (self.satir_sil(), "break")[1], add="+")
        self._satirlari_yenile()

    def _satirlari_yenile(self) -> None:
        t = self.satir_tablosu
        t.delete(*t.get_children())
        for i, s in enumerate(self.satirlar):
            t.insert("", "end", iid=str(i), values=self._satir_degerleri(s))
        self._satir_ici_giris.tabloya_ekle()

    def _satir_toplu_yenile(self) -> None:
        self._satirlari_yenile()

    def _satir_birimleri(self, idx: int) -> list[str]:
        s = self.satirlar[idx]
        try:
            from birim_secim_ui import evrak_birim_secenekleri

            return evrak_birim_secenekleri(s.get("urun_kodu") or "") or [s.get("birim") or "Adet"]
        except Exception:
            return [s.get("birim") or "Adet"]

    def _urun_ekle(self, degerler, konum: int | None) -> int | None:
        from satir_ici_urun_giris import giris_bileseni, toplu_ekleme_mi

        if self._kilitli():
            return None
        try:
            veri = self._yeni_satir(degerler)
        except ValueError as hata:
            messagebox.showwarning("Ürün", str(hata), parent=self)
            return None
        giris = giris_bileseni(self)
        idx = None
        if giris is not None and giris.son_islem == "barkod" and konum is None:
            anahtar = self._birlesme_anahtari(veri)
            idx = next((i for i, s in enumerate(self.satirlar) if self._birlesme_anahtari(s) == anahtar), None)
        if idx is not None:
            self.satirlar[idx]["miktar"] = Decimal(str(self.satirlar[idx].get("miktar") or 0)) + Decimal("1")
        elif konum is not None and 0 <= konum <= len(self.satirlar):
            self.satirlar.insert(konum, veri)
            idx = konum
        else:
            self.satirlar.append(veri)
            idx = len(self.satirlar) - 1
        if not toplu_ekleme_mi(self):
            self._satirlari_yenile()
        return idx

    def _urun_degistir(self, idx: int, degerler) -> bool:
        if self._kilitli() or not (0 <= idx < len(self.satirlar)):
            return False
        try:
            veri = self._yeni_satir(degerler)
        except ValueError as hata:
            messagebox.showwarning("Ürün", str(hata), parent=self)
            return False
        eski = self.satirlar[idx]
        for anahtar, deger in eski.items():
            if anahtar not in ("urun_kodu", "urun_adi", "birim", "birim_fiyat"):
                veri[anahtar] = deger
        self.satirlar[idx] = veri
        self._satirlari_yenile()
        return True

    def hucre_uygula(self, idx: int, kolon: str, metin: str) -> None:
        """Hücre editöründen gelen değer; geçersizse ValueError (satır değişmez)."""
        from satir_ici_urun_giris import alis_birim_fiyati, ondalik

        if not (0 <= idx < len(self.satirlar)):
            return
        s = self.satirlar[idx]
        yeni = dict(s)
        metin = (metin or "").strip()
        if kolon == "miktar":
            miktar = ondalik(metin)
            if miktar <= 0:
                raise ValueError("Miktar sıfırdan büyük olmalıdır.")
            yeni["miktar"] = miktar
        elif kolon == "birim":
            if not metin:
                raise ValueError("Birim seçin.")
            if metin != (s.get("birim") or ""):
                from birim_secim_ui import kart_birimini_hazirla

                if not kart_birimini_hazirla(self, s.get("urun_kodu") or "", metin):
                    return
            if "birim_fiyat" in yeni and metin != (s.get("birim") or ""):
                fiyat = alis_birim_fiyati(s.get("urun_kodu") or "", metin)
                if fiyat > 0:
                    yeni["birim_fiyat"] = fiyat
            yeni["birim"] = metin
        elif kolon == "aciklama":
            yeni["aciklama"] = metin
        else:
            self._hucre_ozel(yeni, kolon, metin)
        s.clear()
        s.update(yeni)
        self._satirlari_yenile()

    def _secili_index(self) -> int | None:
        from satir_ici_urun_giris import satir_indeksi

        sec = self.satir_tablosu.selection()
        return satir_indeksi(self.satir_tablosu, sec[0]) if sec else None

    def satir_sil(self) -> None:
        from satir_ici_urun_giris import satir_editorlerini_kapat, satir_silme_sonrasi_temizle

        idx = self._secili_index()
        if idx is None or self._kilitli():
            return
        satir_editorlerini_kapat(self)
        del self.satirlar[idx]
        self._satirlari_yenile()
        satir_silme_sonrasi_temizle(self, self.satir_tablosu)

    def _satir_menusu(self, idx: int) -> list:
        return [
            ("Satırı Düzenle (F2)", lambda: self._hucre.ilk_alana(idx)),
            ("Araya Satır Ekle", lambda: self._satir_ici_giris.araya_ekle(idx)),
            ("Satırı Sil (Del)", self.satir_sil),
        ]

    def _bekleyenleri_uygula(self) -> bool:
        if not self._hucre.bekleyeni_uygula():
            return False
        self._satir_ici_giris.bekleyeni_uygula()
        return True


class TedarikciTeklifDialog(_SatinAlmaSatirGirisi, tk.Toplevel):
    _KOLONLAR = (
        ("tedarikci", "Tedarikçi", 170), ("kod", "Stok", 90), ("ad", "Ürün Adı", 190),
        ("miktar", "Miktar", 65), ("birim", "Birim", 65), ("fiyat", "Fiyat", 80),
        ("vade", "Vade", 50), ("termin", "Termin", 55), ("nakliye", "Nakliye", 70),
    )

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Yeni Alış Teklifi")
        self.geometry("980x560")
        self.transient(parent)
        self.grab_set()
        from database.alis_siparisi_service import AlisSiparisiService
        from database.stok_service import StokService
        from database.tedarikci_teklif_service import TedarikciTeklifService
        from satir_ici_urun_giris import HucreAlani, sayi_metni

        self.TedarikciTeklifService = TedarikciTeklifService
        self.StokService = StokService
        self.tedarikciler = AlisSiparisiService.aktif_tedarikcileri()
        self.eslesme = {f"{t.cari_kodu} — {t.unvan}": t for t in self.tedarikciler}
        self.satirlar = []

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        ttk.Label(ust, text="Tarih").grid(row=0, column=0)
        self.tarih = ttk.Entry(ust, width=12)
        self.tarih.grid(row=0, column=1, padx=4)
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        ttk.Label(ust, text="Açıklama").grid(row=0, column=2)
        self.aciklama = ttk.Entry(ust, width=36)
        self.aciklama.grid(row=0, column=3, padx=4)

        satir_fr = ttk.LabelFrame(self, text="Teklif satırları", padding=8)
        satir_fr.pack(fill="both", expand=True, padx=10, pady=8)
        varsayilan = ttk.Frame(satir_fr)
        varsayilan.pack(fill="x", pady=(0, 6))
        ttk.Label(varsayilan, text="Yeni satır tedarikçisi").pack(side="left")
        self.cari = ttk.Combobox(varsayilan, values=list(self.eslesme.keys()), width=32, state="readonly")
        self.cari.pack(side="left", padx=4)
        ttk.Label(varsayilan, text="Vade").pack(side="left", padx=(8, 0))
        self.vade = ttk.Entry(varsayilan, width=5)
        self.vade.insert(0, "0")
        self.vade.pack(side="left", padx=2)
        ttk.Label(varsayilan, text="Termin").pack(side="left", padx=(8, 0))
        self.termin = ttk.Entry(varsayilan, width=5)
        self.termin.insert(0, "7")
        self.termin.pack(side="left", padx=2)

        def _sayi(anahtar):
            return lambda i: sayi_metni(self.satirlar[i].get(anahtar) or 0)

        self._satir_alani_kur(
            satir_fr,
            [
                HucreAlani("tedarikci", "secim", secenekler=lambda _i: list(self.eslesme), serbest=False,
                           deger=lambda i: self._cari_etiketi(self.satirlar[i].get("cari_id"))),
                HucreAlani("miktar", deger=_sayi("miktar")),
                HucreAlani("birim", "secim", secenekler=self._satir_birimleri, serbest=False),
                HucreAlani("fiyat", deger=_sayi("birim_fiyat")),
                HucreAlani("vade", deger=_sayi("vade_gun")),
                HucreAlani("termin", deger=_sayi("termin_gun")),
                HucreAlani("nakliye", deger=_sayi("nakliye_tutari")),
            ],
        )

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=10, pady=8)
        ttk.Button(alt, text="Listeye Git", command=self.listeye_git).pack(side="left")
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=6)

    def listeye_git(self):
        """Alış Teklifleri listesine geçer; girilmiş satır varsa kaydetmeyi sorar."""
        app = self._root()
        if self.satirlar:
            cevap = messagebox.askyesnocancel(
                "Listeye Git",
                "Teklif kaydedilmedi.\n\nEvet: Kaydet ve listeye git\nHayır: Kaydetmeden listeye git\n"
                "İptal: Belgede kal",
                parent=self,
            )
            if cevap is None:
                return
            if cevap:
                self._kaydet()
                try:
                    if self.winfo_exists():
                        return
                except tk.TclError:
                    pass
        try:
            if self.winfo_exists():
                self.destroy()
        except tk.TclError:
            pass
        belgeden_listeye_git(app, lambda: tedarikci_teklifleri_goster(app))

    def _cari_etiketi(self, cari_id) -> str:
        return next((etiket for etiket, c in self.eslesme.items() if c.id == cari_id), "")

    def _birlesme_anahtari(self, s: dict) -> tuple:
        return (s.get("cari_id"),) + super()._birlesme_anahtari(s)

    def _yeni_satir(self, degerler) -> dict:
        from satir_ici_urun_giris import alis_birim_fiyati

        cari = self.eslesme.get(self.cari.get())
        if not cari:
            raise ValueError("Önce «Yeni satır tedarikçisi» seçin.")
        kod = str(degerler[0] if degerler else "").strip()
        if not kod:
            raise ValueError("Stok bulunamadı.")
        try:
            vade = int(self.vade.get() or 0)
            termin = int(self.termin.get() or 0)
        except ValueError:
            raise ValueError("Vade ve termin gün sayısı olmalıdır.") from None
        birim = str(degerler[2] if len(degerler) > 2 else "").strip() or "Adet"
        return {
            "cari_id": cari.id,
            "urun_kodu": kod,
            "urun_adi": str(degerler[1] if len(degerler) > 1 else "").strip() or kod,
            "birim": birim,
            "miktar": Decimal("1"),
            "birim_fiyat": alis_birim_fiyati(kod, birim),
            "vade_gun": vade,
            "termin_gun": termin,
            "nakliye_tutari": Decimal("0"),
        }

    def _satir_degerleri(self, s: dict) -> tuple:
        from satir_ici_urun_giris import sayi_metni

        return (
            self._cari_etiketi(s.get("cari_id")), s["urun_kodu"], s["urun_adi"], sayi_metni(s["miktar"]),
            s.get("birim") or "", _para(s.get("birim_fiyat") or 0), s.get("vade_gun") or 0,
            s.get("termin_gun") or 0, _para(s.get("nakliye_tutari") or 0),
        )

    def _hucre_ozel(self, yeni: dict, kolon: str, metin: str) -> None:
        from satir_ici_urun_giris import ondalik

        if kolon == "tedarikci":
            cari = self.eslesme.get(metin)
            if not cari:
                raise ValueError("Tedarikçi seçin.")
            yeni["cari_id"] = cari.id
        elif kolon in ("fiyat", "nakliye"):
            deger = ondalik(metin, Decimal("0"))
            if deger < 0:
                raise ValueError("Negatif tutar girilemez.")
            yeni["birim_fiyat" if kolon == "fiyat" else "nakliye_tutari"] = deger
        elif kolon in ("vade", "termin"):
            deger = ondalik(metin, Decimal("0"))
            if deger < 0 or deger != deger.to_integral_value():
                raise ValueError("Gün sayısı tam sayı olmalıdır.")
            yeni["vade_gun" if kolon == "vade" else "termin_gun"] = int(deger)

    def _kaydet(self):
        if not self._bekleyenleri_uygula():
            return
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            self.TedarikciTeklifService.kaydet(
                {"teklif_tarihi": tarih, "aciklama": self.aciklama.get().strip()},
                self.satirlar,
            )
        except Exception as e:
            birim_hatasi_goster(self, e) or messagebox.showerror("Kaydedilemedi", str(e), parent=self)
            return
        birim_uyarisi = getattr(self.TedarikciTeklifService, "son_birim_uyarisi", None)
        if birim_uyarisi:
            messagebox.showwarning(
                "Tanımsız birim", "Teklif TASLAK olarak kaydedildi; siparişe aktarım bu birimler tanımlanana "
                f"kadar engellenecek.\n\n{birim_uyarisi}", parent=self)
        self.destroy()


class TeklifKarsilastirmaDialog(tk.Toplevel):
    def __init__(self, parent, teklif_id: int):
        super().__init__(parent)
        self.teklif_id = teklif_id
        self.title("Teklif Karşılaştırma")
        self.geometry("900x480")
        self.transient(parent)
        self.grab_set()
        from database.tedarikci_teklif_service import TedarikciTeklifService

        self.svc = TedarikciTeklifService
        ttk.Label(
            self,
            text="Toplam edinme maliyeti = net tutar + vade maliyeti + nakliye. En uygun satırları seçip siparişe aktarın.",
            wraplength=860,
        ).pack(anchor="w", padx=10, pady=8)

        self.tablo = ttk.Treeview(
            self,
            columns=(
                "tedarikci",
                "urun",
                "miktar",
                "fiyat",
                "isk",
                "vade",
                "termin",
                "nakliye",
                "maliyet",
            ),
            show="headings",
            selectmode="extended",
        )
        for k, b, w in (
            ("tedarikci", "Tedarikçi", 160),
            ("urun", "Ürün", 180),
            ("miktar", "Miktar", 70),
            ("fiyat", "Fiyat", 80),
            ("isk", "İsk", 50),
            ("vade", "Vade", 50),
            ("termin", "Termin", 60),
            ("nakliye", "Nakliye", 70),
            ("maliyet", "Edinme Mal.", 100),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w)
        self.tablo.pack(fill="both", expand=True, padx=10, pady=6)

        for r in self.svc.karsilastirma(teklif_id):
            self.tablo.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r["tedarikci"],
                    f"{r['urun_kodu']} {r['urun_adi']}",
                    _para(r["miktar"]),
                    _para(r["birim_fiyat"]),
                    _para(r["iskonto"]),
                    r["vade_gun"],
                    r["termin_gun"],
                    _para(r["nakliye"]),
                    _para(r["edinme_maliyeti"]),
                ),
            )

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=10, pady=10)

        def aktar():
            sec = [int(x) for x in self.tablo.selection()]
            if not sec:
                messagebox.showinfo("Seçim", "En az bir satır seçin.", parent=self)
                return
            try:
                self.svc.satir_sec(self.teklif_id, sec)
                idler = self.svc.secilenleri_siparise_aktar(self.teklif_id)
            except ValueError as e:
                birim_hatasi_goster(self, e) or messagebox.showerror("Aktarım", str(e), parent=self)
                return
            messagebox.showinfo(
                "Sipariş",
                f"{len(idler)} sipariş oluşturuldu: {', '.join(str(i) for i in idler)}",
                parent=self,
            )
            self.destroy()

        ttk.Button(alt, text="Seçilenleri Siparişe Aktar", command=aktar).pack(side="right")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right", padx=6)


class TedarikciFiyatDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Tedarikçi Fiyatı")
        self.geometry("520x320")
        self.transient(parent)
        self.grab_set()
        from database.alis_siparisi_service import AlisSiparisiService
        from database.stok_service import StokService
        from database.tedarikci_fiyat_service import TedarikciFiyatService

        self.svc = TedarikciFiyatService
        self.StokService = StokService
        tedarikciler = AlisSiparisiService.aktif_tedarikcileri()
        self.eslesme = {f"{t.cari_kodu} — {t.unvan}": t for t in tedarikciler}

        fr = ttk.Frame(self, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(fr, text="Tedarikçi").grid(row=0, column=0, sticky="w")
        self.cari = ttk.Combobox(fr, values=list(self.eslesme.keys()), width=40)
        self.cari.grid(row=0, column=1, pady=4)
        ttk.Label(fr, text="Stok kodu").grid(row=1, column=0, sticky="w")
        self.kod = ttk.Entry(fr, width=20)
        self.kod.grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(fr, text="Birim fiyat").grid(row=2, column=0, sticky="w")
        self.fiyat = ttk.Entry(fr, width=16)
        self.fiyat.grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(fr, text="İskonto %").grid(row=3, column=0, sticky="w")
        self.isk = ttk.Entry(fr, width=10)
        self.isk.insert(0, "0")
        self.isk.grid(row=3, column=1, sticky="w", pady=4)
        ttk.Label(fr, text="Başlangıç").grid(row=4, column=0, sticky="w")
        self.bas = ttk.Entry(fr, width=12)
        self.bas.insert(0, date.today().strftime("%d.%m.%Y"))
        self.bas.grid(row=4, column=1, sticky="w", pady=4)

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=12, pady=10)
        ttk.Button(alt, text="Kaydet", command=self._kaydet).pack(side="right")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=6)

    def _kaydet(self):
        cari = self.eslesme.get(self.cari.get())
        if not cari:
            messagebox.showerror("Tedarikçi", "Tedarikçi seçin.", parent=self)
            return
        kod = self.kod.get().strip()
        stoklar = self.StokService.stoklari_ara(kod)
        stok = next((s for s in stoklar if s.stok_kodu == kod), None) or (
            stoklar[0] if stoklar else None
        )
        if not stok:
            messagebox.showerror("Stok", "Stok bulunamadı.", parent=self)
            return
        try:
            self.svc.kaydet(
                {
                    "cari_id": cari.id,
                    "urun_kodu": stok.stok_kodu,
                    "urun_adi": stok.stok_adi,
                    "birim": stok.birim or "Adet",
                    "birim_fiyat": self.fiyat.get(),
                    "iskonto_orani": self.isk.get(),
                    "gecerlilik_baslangic": datetime.strptime(
                        self.bas.get().strip(), "%d.%m.%Y"
                    ).date(),
                }
            )
        except Exception as e:
            messagebox.showerror("Kaydedilemedi", str(e), parent=self)
            return
        self.destroy()


# --- Tedarikçi Bakiye Durum listesi (görünüm + hizalama; hesaplama yok) ---

_TB_STRIPE = "#E8EEF4"  # açık mavi-gri
_TB_HOVER = "#FFF4CC"  # hafif sarı
_TB_STIL = "TedarikciBakiye.Treeview"

_TB_KOLONLAR = ("kod", "unvan", "bakiye", "ort", "agirlikli", "geciken")
_TB_BASLIKLAR = {
    "kod": "Kod",
    "unvan": "Ünvan",
    "bakiye": "Bakiye",
    "ort": "Ort. Gün",
    "agirlikli": "Ağırlıklı Gün",
    "geciken": "Geciken Gün",
}
# width, minwidth, stretch, anchor
_TB_KOLON_AYAR = {
    "kod": (78, 56, False, "w"),
    "unvan": (360, 200, True, "w"),
    "bakiye": (160, 130, False, "e"),
    "ort": (100, 80, False, "e"),
    "agirlikli": (110, 90, False, "e"),
    "geciken": (110, 90, False, "e"),
}
_TB_SAYISAL = frozenset({"bakiye", "ort", "agirlikli", "geciken"})


def _tb_gun_goster(deger) -> str:
    """Görüntü biçimi: tam sayıysa ondalıksız; değilse en fazla 1 ondalık."""
    try:
        d = Decimal(str(deger if deger is not None else 0))
    except Exception:
        return "0"
    if d == d.to_integral_value():
        return str(int(d))
    q = d.quantize(Decimal("0.1"))
    metin = f"{q:f}".rstrip("0").rstrip(".")
    return metin.replace(".", ",")


def _tb_bakiye_goster(tutar) -> str:
    try:
        v = float(tutar if tutar is not None else 0)
    except (TypeError, ValueError):
        v = 0.0
    s = f"{v:,.2f} TL"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def tedarikci_bakiye_treeview_stil(tablo: ttk.Treeview, root: tk.Misc | None = None) -> None:
    """Yalnızca Tedarikçi Bakiye listesi — diğer satın alma tablolarına dokunmaz."""
    stil = ttk.Style(root)
    try:
        if "clam" in stil.theme_names():
            stil.theme_use("clam")
    except tk.TclError:
        pass

    aile = resolve_ui_font(root)
    f_govde: tuple = (aile, 11, "bold")
    try:
        families = {str(x).lower() for x in (root or tk._default_root).tk.call("font", "families")}  # type: ignore[attr-defined]
        if "segoe ui semibold" in families:
            f_govde = ("Segoe UI Semibold", 11)
    except Exception:
        pass
    f_baslik = font(12, "bold", root=root)

    stil.configure(
        _TB_STIL,
        font=f_govde,
        rowheight=36,
        fieldbackground=BEYAZ,
        background=BEYAZ,
        foreground=METIN,
        borderwidth=0,
        relief="flat",
    )
    stil.configure(
        f"{_TB_STIL}.Heading",
        font=f_baslik,
        background=LACIVERT,
        foreground=BEYAZ,
        relief="flat",
        borderwidth=0,
        padding=(10, 10),
    )
    stil.map(
        _TB_STIL,
        background=[("selected", LACIVERT)],
        foreground=[("selected", BEYAZ)],
    )
    stil.map(
        f"{_TB_STIL}.Heading",
        background=[("active", LACIVERT_HOVER), ("pressed", LACIVERT_HOVER)],
        foreground=[("active", BEYAZ), ("pressed", BEYAZ)],
    )
    tablo.configure(style=_TB_STIL)
    tablo.tag_configure("tek", background=BEYAZ, foreground=METIN)
    tablo.tag_configure("cift", background=_TB_STRIPE, foreground=METIN)
    tablo.tag_configure("hover", background=_TB_HOVER, foreground=METIN)


def tedarikci_bakiye_durum_goster(app) -> None:
    """Satın Alma → Tedarikçi Bakiye Durum (Ortalama Vadeli) — yalnızca görünüm."""
    from database.rapor_service import RaporService

    app._icerigi_temizle()
    stil_uygula(root=app)
    _menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="TEDARİKÇİ BAKİYE DURUM (ORTALAMA VADELİ)", style="Baslik.TLabel").pack(
        side="left"
    )
    ttk.Button(ust, text="← Raporlar", command=app.alis_raporlari_goster).pack(side="right")

    ham = list(RaporService.musteri_bakiye_durum(cari_turu="Tedarikçi"))
    ttk.Label(
        app.icerik,
        text=f"{len(ham)} tedarikçi",
        font=font(11, root=app),
        foreground=IKINCIL,
    ).pack(anchor="w", pady=(10, 4))

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True, pady=(4, 0))
    cerceve.rowconfigure(0, weight=1)
    cerceve.columnconfigure(0, weight=1)

    tablo = ttk.Treeview(
        cerceve,
        columns=_TB_KOLONLAR,
        show="headings",
        selectmode="browse",
    )
    dikey = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=tablo.xview)
    tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
    tablo.grid(row=0, column=0, sticky="nsew")
    dikey.grid(row=0, column=1, sticky="ns")
    yatay.grid(row=1, column=0, sticky="ew")

    tedarikci_bakiye_treeview_stil(tablo, root=app)

    durum = {
        "kayitlar": ham,
        "sira_kolon": "bakiye",
        "sira_ters": True,
        "secili_kod": None,
        "hover_iid": None,
    }

    def _sirala_anahtar(kayit: dict, kolon: str):
        if kolon == "kod":
            return (kayit.get("cari_kodu") or "").lower()
        if kolon == "unvan":
            return (kayit.get("unvan") or "").lower()
        if kolon == "bakiye":
            return Decimal(str(kayit.get("bakiye") or 0))
        if kolon == "ort":
            return Decimal(str(kayit.get("ortalama_gun") or 0))
        if kolon == "agirlikli":
            return Decimal(str(kayit.get("agirlikli_ortalama_gun") or 0))
        if kolon == "geciken":
            return int(kayit.get("geciken_gun") or 0)
        return 0

    def _degerler(kayit: dict) -> tuple:
        return (
            kayit.get("cari_kodu") or "",
            kayit.get("unvan") or "",
            _tb_bakiye_goster(kayit.get("bakiye")),
            _tb_gun_goster(kayit.get("ortalama_gun")),
            _tb_gun_goster(kayit.get("agirlikli_ortalama_gun")),
            _tb_gun_goster(kayit.get("geciken_gun")),
        )

    def _kolonlari_kur():
        for kolon in _TB_KOLONLAR:
            w, mn, stretch, anc = _TB_KOLON_AYAR[kolon]
            tablo.heading(
                kolon,
                text=_TB_BASLIKLAR[kolon],
                anchor=anc,
                command=lambda k=kolon: _baslik_sirala(k),
            )
            tablo.column(
                kolon,
                width=w,
                minwidth=mn,
                stretch=stretch,
                anchor=anc,
            )

    def _doldur():
        secili = durum["secili_kod"]
        if not secili:
            sec = tablo.selection()
            if sec:
                vals = tablo.item(sec[0], "values")
                if vals:
                    secili = vals[0]

        for item in tablo.get_children():
            tablo.delete(item)

        kayitlar = list(durum["kayitlar"])
        kolon = durum["sira_kolon"]
        ters = durum["sira_ters"]
        kayitlar.sort(key=lambda k: _sirala_anahtar(k, kolon), reverse=ters)

        hedef_iid = None
        for i, kayit in enumerate(kayitlar):
            tag = "cift" if i % 2 else "tek"
            iid = tablo.insert("", "end", values=_degerler(kayit), tags=(tag,))
            kod = kayit.get("cari_kodu") or ""
            if secili and kod == secili:
                hedef_iid = iid

        if hedef_iid:
            tablo.selection_set(hedef_iid)
            tablo.focus(hedef_iid)
            tablo.see(hedef_iid)
        durum["hover_iid"] = None
        _yatay_gerekli_mi()

    def _baslik_sirala(kolon: str):
        if durum["sira_kolon"] == kolon:
            durum["sira_ters"] = not durum["sira_ters"]
        else:
            durum["sira_kolon"] = kolon
            durum["sira_ters"] = kolon in _TB_SAYISAL
        sec = tablo.selection()
        if sec:
            vals = tablo.item(sec[0], "values")
            durum["secili_kod"] = vals[0] if vals else None
        _doldur()

    def _yatay_gerekli_mi(_e=None):
        try:
            genislik = max(int(tablo.winfo_width()), 1)
            toplam = sum(int(tablo.column(k, "width") or 0) for k in _TB_KOLONLAR)
            if toplam > genislik + 8:
                yatay.grid()
            else:
                yatay.grid_remove()
        except tk.TclError:
            pass

    def _hover(event):
        satir = tablo.identify_row(event.y)
        onceki = durum["hover_iid"]
        if onceki and onceki != satir and onceki in tablo.get_children():
            try:
                idx = tablo.index(onceki)
                tablo.item(onceki, tags=("cift" if idx % 2 else "tek",))
            except tk.TclError:
                pass
        durum["hover_iid"] = satir or None
        if not satir:
            return
        if satir in tablo.selection():
            return
        tablo.item(satir, tags=("hover",))

    def _leave(_e=None):
        onceki = durum["hover_iid"]
        if onceki and onceki in tablo.get_children():
            try:
                idx = tablo.index(onceki)
                tablo.item(onceki, tags=("cift" if idx % 2 else "tek",))
            except tk.TclError:
                pass
        durum["hover_iid"] = None

    def _secim(_e=None):
        sec = tablo.selection()
        if sec:
            vals = tablo.item(sec[0], "values")
            durum["secili_kod"] = vals[0] if vals else None

    _kolonlari_kur()
    tablo.bind("<Motion>", _hover)
    tablo.bind("<Leave>", _leave)
    tablo.bind("<<TreeviewSelect>>", _secim)
    tablo.bind("<Configure>", _yatay_gerekli_mi)
    cerceve.bind("<Configure>", _yatay_gerekli_mi)

    _doldur()
    app._tedarikci_bakiye_tablo = tablo
    app._tedarikci_bakiye_yenile = _doldur
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: tedarikci_bakiye_durum_goster(app))
