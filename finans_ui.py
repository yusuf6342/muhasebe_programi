"""FİNANS menüsü — Kasalar, Bankalar, Çek / Senet."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import time
import tkinter as tk
import uuid
from tkinter import messagebox, simpledialog, ttk

from database.finans_service import FinansService
from database.kk_cekimi_service import KkCekimiService
from database.models.finans import (
    BANKA_ALT_HESAP_TURLERI,
    KK_CEKIM_TURLERI,
    KK_MAX_TAKSIT,
    KREDI_MAX_TAKSIT,
    KREDI_ODEME_HESAP_TURLERI,
    KREDI_TURLERI,
    POS_KART_TIPLERI,
    POS_MAX_TAKSIT,
)
from ui_takvim import takvim_butonu

try:
    from banka_kredi_ui import banka_kredileri_menusu_goster
except Exception:  # pragma: no cover
    banka_kredileri_menusu_goster = None

try:
    from odeme_durumu_ui import finans_raporlar_menusu_goster
except Exception:  # pragma: no cover
    finans_raporlar_menusu_goster = None


def _kredi_taksit_tutari_hucre(det: dict | None) -> str:
    """Gerçek plandan taksit tutarı hücresi; plan yoksa «Plan yok» / «—» (sıfır uydurma)."""
    det = det or {}
    tutar = det.get("taksit_tutari")
    etiket = (det.get("taksit_tutari_etiket") or "").strip()
    if tutar is None:
        return etiket or "Plan yok"
    metin = _para(tutar)
    if det.get("taksit_tutari_degisken") and etiket:
        return f"{metin} ({etiket})"
    return metin


def _para(tutar, pb: str | None = "TRY", *, isaretli: bool = False):
    """PB etiketli tutar. Bakiye alanlarında isaretli=True (pozitifte artı yok)."""
    return FinansService.para_metni(tutar, pb, isaretli=isaretli)


def _para_bakiye(tutar, pb: str | None = "TRY"):
    """Hesap bakiyesi / varlık-borç özeti: 1.234,56 TL | -1.234,56 TL | 0,00 TL (artı yok)."""
    return FinansService.para_metni(tutar, pb, isaretli=True)


def _kur_metin(kur) -> str:
    if kur is None:
        return "—"
    return f"{float(kur):,.6f}".replace(",", "X").replace(".", ",").replace("X", ".").rstrip("0").rstrip(",")


def _bakiye_renk(tutar):
    """Pozitif yeşil, negatif (borç) kırmızı — FinansService ile aynı kural."""
    return FinansService.bakiye_renk_kodu(tutar)


def _kart_limit_metni(kk) -> str:
    """Kart borcu / limit satırı (ekstre ekranı, limit kontrolü ve takvimle aynı hesap)."""
    from database.kredi_karti_ekstre_service import KrediKartiEkstreService

    oz = KrediKartiEkstreService.kart_borc_ozeti(int(kk.id))
    metin = (
        f"Kart Limiti: {_para(oz['limit']) if oz.get('limit_tanimli') else 'Tanımlanmamış'} · "
        f"Kullanılan Limit: {_para(oz['kullanilan'])}"
    )
    if not oz["limit_tanimli"]:
        metin += " · Limit tanımlanmamış"
    else:
        etiket = oz.get("etiket_kullanilabilir") or "Hesaplanan kullanılabilir limit"
        metin += f" · {etiket}: {_para(oz['kullanilabilir'])}"
        if (oz.get("limit_asimi") or 0) > 0:
            metin += f" · Limit aşımı: {_para(oz['limit_asimi'])}"
        elif oz.get("kullanilabilir") is not None and oz["kullanilabilir"] < 0:
            metin += f" · Limit aşımı: {_para(-oz['kullanilabilir'])}"
    if oz.get("fazla_odeme"):
        metin += f" · Fazla ödeme: {_para(oz['fazla_odeme'])}"
    if oz.get("limit_uyari"):
        metin += f"\n{oz['limit_uyari']}"
    if not oz["son_odeme_tanimli"]:
        metin += "\nKartın son ödeme günü tanımsız: ekstreler 'Eksik bilgi' durumunda, gecikme belirlenemez."
    return metin


_HAREKET_FONT = ("Segoe UI", 9, "bold")
_HAREKET_GIRIS = "#0a5c2e"
_HAREKET_CIKIS = "#9b1515"
_HAREKET_NOTR = "#1a1a1a"
_HAREKET_TEK_BG = "#ffffff"
_HAREKET_CIFT_BG = "#e4ebf3"


def _hareket_tablo_stil(tablo: ttk.Treeview):
    """Kasa/banka hareket listeleri: kuşaklı satır, koyu yazı, giriş yeşil / çıkış kırmızı."""
    stil = ttk.Style()
    stil.configure(
        "Hareket.Treeview",
        font=_HAREKET_FONT,
        foreground=_HAREKET_NOTR,
        rowheight=26,
        fieldbackground=_HAREKET_TEK_BG,
    )
    stil.configure("Hareket.Treeview.Heading", font=("Segoe UI", 9, "bold"))
    stil.map(
        "Hareket.Treeview",
        background=[("selected", "#c5d4e8")],
        foreground=[("selected", _HAREKET_NOTR)],
    )
    tablo.configure(style="Hareket.Treeview")
    tablo.tag_configure("tek", background=_HAREKET_TEK_BG)
    tablo.tag_configure("cift", background=_HAREKET_CIFT_BG)
    tablo.tag_configure("giris", foreground=_HAREKET_GIRIS, font=_HAREKET_FONT)
    tablo.tag_configure("cikis", foreground=_HAREKET_CIKIS, font=_HAREKET_FONT)
    tablo.tag_configure("notr", foreground=_HAREKET_NOTR, font=_HAREKET_FONT)


_HAREKET_SAYISAL_KOLON = frozenset({"giris", "cikis", "bakiye", "kur", "tl"})


def _hareket_kolonlari_ayarla(tablo: ttk.Treeview, kolonlar):
    """Başlık ve hücre aynı hizada: metin sola, tutarlar sağa."""
    for k, b, w in kolonlar:
        if k in _HAREKET_SAYISAL_KOLON:
            ank = "e"
        elif k == "tarih":
            ank = "center"
        else:
            ank = "w"
        tablo.heading(k, text=b, anchor=ank)
        tablo.column(k, width=w, minwidth=max(50, w // 2), anchor=ank, stretch=True)


_HESAP_SAYISAL_KOLON = frozenset({"acilis", "bakiye"})
_HESAP_BAKIYE_FONT = ("Segoe UI", 11, "bold")


def _hesap_kolonlari_ayarla(tablo: ttk.Treeview, kolonlar):
    """Kasa/banka hesap listesi: ad sola, tutarlar sağa, durum ortada."""
    for k, b, w in kolonlar:
        if k in _HESAP_SAYISAL_KOLON:
            ank = "e"
        elif k == "durum":
            ank = "center"
        else:
            ank = "w"
        tablo.heading(k, text=b, anchor=ank)
        tablo.column(k, width=w, minwidth=max(50, w // 2), anchor=ank, stretch=(k != "durum"))


def _hareket_satir_tags(sira: int, *, isaret: int | None = None, giris=None, cikis=None):
    """Kuşak + giriş/çıkış rengi etiketleri."""
    kusak = "tek" if sira % 2 == 0 else "cift"
    if isaret is None:
        if giris and not cikis:
            isaret = 1
        elif cikis and not giris:
            isaret = -1
        else:
            isaret = 0
    if isaret > 0:
        yon = "giris"
    elif isaret < 0:
        yon = "cikis"
    else:
        yon = "notr"
    return (kusak, yon)


def _varlik_bakiyesi(alt_tur: str, tutar, hesap=None) -> Decimal:
    """Borç hesapları eksi; mümkünse ``hesap`` verin (fazla ödeme yönü için)."""
    return FinansService.varlik_bakiyesi(tutar, alt_tur=alt_tur, hesap=hesap)


def _tarih(t):
    return t.strftime("%d.%m.%Y") if t else ""


def _finans_menu_isaretle(app):
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk is not None:
        aktif = getattr(app, "_aktif_sayfa", "finans")
        kabuk.menu_secili_guncelle("cek_senet" if aktif == "cek_senet" else "finans")
        return
    for dugme_anahtari, dugme in app.menu_dugmeleri.items():
        if dugme_anahtari == "finans":
            dugme.configure(style="SeciliMenu.TButton")
        elif dugme_anahtari == "hizli_satis":
            dugme.configure(style="HizliSatisMenu.TButton")
        else:
            dugme.configure(style="Menu.TButton")


def _soz_bagla(parent, cari_id, yon, evrak_turu, belge_no):
    try:
        from odeme_sozu_ui import evrak_kaydi_sonrasi_bagla

        evrak_kaydi_sonrasi_bagla(parent, cari_id=cari_id, yon=yon, evrak_turu=evrak_turu, belge_no=belge_no)
    except Exception:
        pass


def _odeme_sozleri_merkezi(app):
    from odeme_sozu_ui import OdemeSozleriMerkezDialog

    OdemeSozleriMerkezDialog(app)


def _fon_yonetimi(app):
    from fon_ui import fon_yonetimi_goster

    fon_yonetimi_goster(app)


def _odeme_takvimi(app):
    from odeme_takvimi_ui import odeme_takvimi_goster

    odeme_takvimi_goster(app)


def finans_menusu_goster(app):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ttk.Label(app.icerik, text="FİNANS", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text="Kasa ve banka hesapları, banka işlem evrakları, ödeme takvimi ve raporlar.",
    ).pack(anchor="w", pady=(6, 0))
    # İki sütun: Excel + Raporlar aynı satırda kalsın; tek sütunda altta kesilmesin.
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="both", expand=True, pady=(12, 8))
    alt.columnconfigure(0, weight=1, minsize=280)
    alt.columnconfigure(1, weight=1, minsize=280)
    nav = getattr(app, "nav_ac", lambda c: c())

    def _finans_excel_aktarim(a):
        from excel_aktarim_ui import excel_aktarim_hub_goster

        excel_aktarim_hub_goster(
            a,
            modul="finans",
            baslik="FİNANS — EXCEL VERİ AKTARIM",
            geri_fn=lambda: finans_menusu_goster(a),
        )

    def _faiz_urun_tanim(a):
        from faiz_urun_tanim_ui import faiz_urun_tanim_goster

        faiz_urun_tanim_goster(a, urun_turu="KK")

    def _pos_islemleri(a):
        from pos_islemleri_ui import pos_islemleri_sayfasi_goster

        pos_islemleri_sayfasi_goster(a, geri_fn=lambda: finans_menusu_goster(a))

    ogeler = (
        ("KASALAR", lambda: kasalar_sayfasi_goster(app)),
        ("BANKALAR", lambda: bankalar_sayfasi_goster(app)),
        ("MEVDUAT VE KMH HESAPLARI", lambda: mevduat_kmh_hesaplari_sayfasi_goster(app)),
        ("POS İŞLEMLERİ", lambda: _pos_islemleri(app)),
        ("FİRMA KREDİ KARTLARI", lambda: firma_kredi_kartlari_sayfasi_goster(app)),
        ("BANKA KREDİLERİ", lambda: banka_kredileri_menusu_goster(app) if banka_kredileri_menusu_goster else None),
        ("FAİZ / MASRAF TANIMLARI", lambda: _faiz_urun_tanim(app)),
        ("BANKA İŞLEMLERİ", lambda: banka_islemleri_menusu_goster(app)),
        ("ÖDEME TAKVİMİ", lambda: _odeme_takvimi(app)),
        ("ÇEK / SENET İŞLEMLERİ", lambda: cek_senet_menusu_goster(app)),
        ("ÖDEME SÖZLERİ TAKVİMİ", lambda: _odeme_sozleri_merkezi(app)),
        ("FON YÖNETİMİ", lambda: _fon_yonetimi(app)),
        ("EXCEL VERİ AKTARIM", lambda: _finans_excel_aktarim(app)),
        ("RAPORLAR", lambda: finans_raporlar_menusu_goster(app) if finans_raporlar_menusu_goster else None),
    )
    for i, (baslik, komut) in enumerate(ogeler):
        satir, sutun = divmod(i, 2)
        padx = (0, 6) if sutun == 0 else (6, 0)
        ttk.Button(alt, text=baslik, style="AltMenu.TButton", command=lambda c=komut: nav(c)).grid(
            row=satir, column=sutun, sticky="ew", padx=padx, pady=3
        )
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: finans_menusu_goster(app))


BANKA_ISLEM_EVRAKLARI = (
    ("KASADAN BANKAYA YATIRILAN", "kby"),
    ("BANKADAN ÇEKİLEN", "bnc"),
    ("ALINAN HAVALE", "ahv"),
    ("GÖNDERİLEN HAVALE", "ghv"),
    ("BANKA TRANSFER VE VİRMAN İŞLEMLERİ", "bvr"),
    ("KREDİ KARTI İLE ÖDEME", "kko"),
    ("POS İŞLEMLERİ", "kpt"),
    ("MÜŞTERİDEN TEDARİKÇİYE KREDİ KARTI ÇEKİMİ", "kkc"),
)


def banka_islemleri_menusu_goster(app):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BANKA İŞLEMLERİ", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Finans Menüsü", command=lambda: finans_menusu_goster(app)).pack(side="right")
    ttk.Label(
        app.icerik,
        text="Kasa–banka, havale, kredi kartı ve müşteri–tedarikçi KK çekim evrakları.",
    ).pack(anchor="w", pady=(14, 8))
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(8, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    nav = getattr(app, "nav_ac", lambda c: c())
    for i, (baslik, kod) in enumerate(BANKA_ISLEM_EVRAKLARI):
        if kod == "kby":
            komut = lambda: kasadan_bankaya_yatirilan_sayfasi_goster(app)
        elif kod == "bnc":
            komut = lambda: bankadan_cekilen_sayfasi_goster(app)
        elif kod == "ahv":
            komut = lambda: alinan_havale_sayfasi_goster(app)
        elif kod == "ghv":
            komut = lambda: gonderilen_havale_sayfasi_goster(app)
        elif kod == "bvr":
            komut = lambda: bankalar_arasi_virman_sayfasi_goster(app)
        elif kod == "kko":
            komut = lambda: kredi_karti_odeme_sayfasi_goster(app)
        elif kod == "kpt":
            komut = lambda: (
                __import__("pos_islemleri_ui", fromlist=["pos_islemleri_sayfasi_goster"]).pos_islemleri_sayfasi_goster(
                    app, geri_fn=lambda: banka_islemleri_menusu_goster(app)
                )
            )
        elif kod == "kkc":
            komut = lambda: kk_cekimi_sayfasi_goster(app)
        else:
            komut = lambda b=baslik: _banka_islem_bos(app, b)
        ttk.Button(
            alt,
            text=baslik,
            style="AltMenu.TButton",
            command=lambda c=komut: nav(c),
        ).grid(row=i, column=0, sticky="ew", pady=4)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: banka_islemleri_menusu_goster(app))


def _banka_islem_bos(app, baslik):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ttk.Label(app.icerik, text=baslik, style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text="Bu evrak formu henüz hazır değil. Alanları ve işleyişi tarif ettiğinde buraya ekleyeceğiz.",
    ).pack(anchor="w", pady=(18, 0))
    ttk.Button(
        app.icerik,
        text="← Banka İşlemleri",
        command=lambda: banka_islemleri_menusu_goster(app),
    ).pack(anchor="w", pady=(16, 0))


def kasadan_bankaya_yatirilan_sayfasi_goster(app):
    """Kasadan bankaya yatırılan fiş listesi + yeni fiş."""
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="KASADAN BANKAYA YATIRILAN", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Banka İşlemleri", command=lambda: banka_islemleri_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(
        app.icerik,
        text="Kasadan nakit çıkışı; mevduat, KMH, kredi kartı veya vadeli hesaba yatırma.",
    ).pack(anchor="w", pady=(10, 6))

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=(4, 8))
    ttk.Button(butonlar, text="Yeni Fiş", command=lambda: _kby_yeni_fis(app)).pack(side="left")
    ttk.Button(butonlar, text="Güncelle", command=lambda: _kby_guncelle_fis(app, tablo)).pack(
        side="left", padx=8
    )
    ttk.Button(
        butonlar,
        text="Yenile",
        command=lambda: kasadan_bankaya_yatirilan_sayfasi_goster(app),
    ).pack(side="left", padx=8)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    tablo = ttk.Treeview(
        cerceve,
        columns=("tarih", "belge", "kasa", "banka", "tutar", "muhasebe", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("tarih", "Tarih", 90),
        ("belge", "Belge No", 120),
        ("kasa", "Kasa", 150),
        ("banka", "Banka hesabı", 220),
        ("tutar", "Tutar", 110),
        ("muhasebe", "Muhasebe", 130),
        ("aciklama", "Açıklama", 260),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    tablo.bind("<Double-1>", lambda _e: _kby_guncelle_fis(app, tablo))

    kayitlar = FinansService.kasadan_bankaya_yatan_listele()
    muhasebe = _muhasebe_durumlari("kasa_banka_virman", kayitlar)
    for kayit in kayitlar:
        tablo.insert(
            "",
            "end",
            iid=kayit["belge_no"],
            values=(
                _tarih(kayit["tarih"]),
                kayit["belge_no"],
                kayit["kasa"],
                kayit["banka_hesap"],
                _para(kayit["tutar"]),
                muhasebe.get(kayit["belge_no"], ""),
                kayit["aciklama"],
            ),
        )


def _muhasebe_durumlari(evrak: str, kayitlar) -> dict[str, str]:
    """Liste satırları (belge_no anahtarlı) için muhasebe durumları; tek toplu sorgu."""
    from muhasebe_durum_ui import toplu_durum_belge

    return toplu_durum_belge(evrak, [k.get("belge_no") for k in kayitlar])


def _kby_yeni_fis(app):
    dialog = KasadanBankayaYatirDialog(app)
    app.wait_window(dialog)
    if dialog.result:
        kasadan_bankaya_yatirilan_sayfasi_goster(app)


def _kby_guncelle_fis(app, tablo):
    secim = tablo.selection()
    if not secim:
        messagebox.showinfo("Güncelle", "Lütfen güncellenecek fişi seçin.", parent=app)
        return
    dialog = KasadanBankayaYatirDialog(app, belge_no=secim[0])
    app.wait_window(dialog)
    if dialog.result:
        kasadan_bankaya_yatirilan_sayfasi_goster(app)


def _combobox_id_sec(cb, id_map: dict, hedef_id):
    if hedef_id is None:
        return False
    for etiket, deger in id_map.items():
        if deger == hedef_id:
            cb.set(etiket)
            return True
    return False


def _muhasebe_fisi_belge_no(parent, evrak: str, belge_no: str | None):
    try:
        from muhasebe_durum_ui import belge_no_kaynagi, fisi_ac

        kaynak_id = belge_no_kaynagi(evrak, belge_no)
    except Exception as hata:
        messagebox.showerror("Muhasebe fişi", str(hata), parent=parent)
        return
    if not kaynak_id:
        messagebox.showinfo("Muhasebe fişi", f"{belge_no or 'Belge'} için muhasebe kaydı bulunamadı.", parent=parent)
        return
    fisi_ac(parent, evrak, kaynak_id)


def _muhasebe_dugmesi_ekle(pencere, butonlar, evrak: str, belge_no: str | None):
    """Kayıtlı fişte başlığa muhasebe durumunu ekler ve 'Muhasebe Fişi' düğmesi koyar."""
    if not belge_no:
        return
    ttk.Button(
        butonlar, text="Muhasebe Fişi", command=lambda: _muhasebe_fisi_belge_no(pencere, evrak, belge_no)
    ).pack(side="right", padx=(8, 0))
    try:
        from muhasebe_durum_ui import baslik_guncelle, belge_no_kaynagi

        kaynak_id = belge_no_kaynagi(evrak, belge_no)
        if kaynak_id:
            baslik_guncelle(pencere, pencere.title(), evrak, kaynak_id)
    except Exception:
        pass


def _banka_fis_sil_uygula(dialog) -> None:
    """Kayıtlı KBY/BNC/AHV/GHV/BVR/KVR fişini siler; dialog.result doldurulur."""
    belge_no = getattr(dialog, "belge_no", None)
    if not belge_no:
        return
    if not messagebox.askyesno(
        "Sil",
        f"{belge_no} fişi silinsin mi?\n"
        "Bağlı kasa, banka ve cari hareketleri birlikte kaldırılır.",
        parent=dialog,
    ):
        return
    try:
        FinansService.banka_islem_fis_sil(belge_no)
    except ValueError as hata:
        messagebox.showerror("Sil", str(hata), parent=dialog)
        return
    dialog.result = belge_no
    messagebox.showinfo("Silindi", f"Belge silindi: {belge_no}", parent=dialog)
    dialog.destroy()


def _banka_fis_sil_dugmesi_ekle(dialog, butonlar) -> None:
    if not getattr(dialog, "belge_no", None):
        return
    ttk.Button(
        butonlar, text="Sil", command=lambda: _banka_fis_sil_uygula(dialog)
    ).pack(side="left", padx=(0, 8))


def _hareket_listesi_belge_ac(parent, tablo, yenile=None, *, belge_alan="belge", tur_alan="tur"):
    """Hareket satırından evrakı açar; kaydet/sil sonrası yenile çağrılır."""
    secim = tablo.selection()
    if not secim:
        messagebox.showinfo("Belge", "Açılacak hareket satırını seçin.", parent=parent)
        return "break"
    degerler = tablo.item(secim[0], "values") or ()
    kolonlar = list(tablo["columns"])
    veri = {k: (degerler[i] if i < len(degerler) else "") for i, k in enumerate(kolonlar)}
    belge_no = str(veri.get(belge_alan) or "").strip()
    if belge_no in ("", "—", "-", "None"):
        messagebox.showinfo("Belge", "Bu satırda belge numarası yok.", parent=parent)
        return "break"
    tur = str(veri.get(tur_alan) or "").strip()
    from belge_onizleme_ui import hareket_belgeyi_ac

    try:
        acildi = hareket_belgeyi_ac(parent, tur, belge_no)
        if not acildi:
            messagebox.showinfo(
                "Belge",
                f"{tur or 'Hareket'} / {belge_no} için açılabilir evrak bulunamadı.",
                parent=parent,
            )
    except ValueError as hata:
        messagebox.showerror("Belge açılamadı", str(hata), parent=parent)
    except Exception as hata:
        messagebox.showerror("Belge açılamadı", str(hata), parent=parent)
    if callable(yenile):
        try:
            yenile()
        except tk.TclError:
            pass
    return "break"


def _hareket_listesi_belge_bagla(tablo, parent, yenile=None, *, belge_alan="belge", tur_alan="tur"):
    """Belge No sütununa tık / çift tık / F2 / Return ile evrak açma."""
    kolonlar = list(tablo["columns"])
    try:
        belge_idx = kolonlar.index(belge_alan) + 1
    except ValueError:
        belge_idx = 3

    def _ac(_e=None):
        return _hareket_listesi_belge_ac(
            parent, tablo, yenile, belge_alan=belge_alan, tur_alan=tur_alan
        )

    def _belge_sutununa_tik(event):
        col = tablo.identify_column(event.x)
        row = tablo.identify_row(event.y)
        if not row:
            return
        if col == f"#{belge_idx}":
            tablo.selection_set(row)
            tablo.focus(row)
            return _ac()

    tablo.bind("<ButtonRelease-1>", _belge_sutununa_tik)
    tablo.bind("<Double-1>", _ac)
    tablo.bind("<Return>", _ac)
    tablo.bind("<F2>", _ac)


class KasadanBankayaYatirDialog(tk.Toplevel):
    """Kasadan bankaya yatırılan fiş formu."""

    ALT_ETIKET = {
        "MEVDUAT": "Mevduat",
        "KMH": "KMH",
        "KREDI_KARTI": "Kredi Kartı",
        "VADELI": "Vadeli",
        "POS": "POS",
        "KREDILER": "Krediler",
    }

    def __init__(self, parent, belge_no=None):
        super().__init__(parent)
        self.result = None
        self.belge_no = belge_no
        self._mevcut = None
        if belge_no:
            try:
                self._mevcut = FinansService.banka_islem_fis_getir(belge_no)
            except ValueError as hata:
                messagebox.showerror("Fiş", str(hata), parent=parent)
                self.destroy()
                return
        self.title(
            "Kasadan Bankaya Yatırılan — Güncelle" if belge_no else "Kasadan Bankaya Yatırılan"
        )
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        self._kasa_map = {}
        self._banka_map = {}
        self._hesap_map = {}

        row = 0
        ttk.Label(self, text="Tarih *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        row = 1
        kasalar = FinansService.hesaplar(hesap_turu="KASA")
        ttk.Label(self, text="Kasa *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.kasa = ttk.Combobox(self, state="readonly", width=42)
        self.kasa.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self._kasa_map = {}
        kasa_etiketleri = []
        for h in kasalar:
            bak = FinansService.bakiye(h)
            etiket = f"{h.hesap_adi}  ({_para(bak)})"
            self._kasa_map[etiket] = h.id
            kasa_etiketleri.append(etiket)
        self.kasa.configure(values=kasa_etiketleri)
        if kasa_etiketleri:
            self.kasa.set(kasa_etiketleri[0])
        self.kasa.bind("<<ComboboxSelected>>", lambda _e: self._kasa_bilgi())

        row = 2
        self.kasa_bilgi = ttk.Label(self, text="", foreground="#555")
        self.kasa_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 3
        kartlar = FinansService.banka_kartlari(aktif_only=True)
        ttk.Label(self, text="Banka *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.banka = ttk.Combobox(self, state="readonly", width=42)
        self.banka.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self._banka_map = {}
        banka_etiketleri = []
        for k in kartlar:
            etiket = k.banka_adi
            if k.sube:
                etiket = f"{etiket} / {k.sube}"
            if k.hesap_no:
                etiket = f"{etiket} ({k.hesap_no})"
            self._banka_map[etiket] = k.id
            banka_etiketleri.append(etiket)
        self.banka.configure(values=banka_etiketleri)
        if banka_etiketleri:
            self.banka.set(banka_etiketleri[0])
        self.banka.bind("<<ComboboxSelected>>", lambda _e: self._hesaplari_doldur())

        row = 4
        ttk.Label(self, text="Banka hesabı *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.hesap = ttk.Combobox(self, state="readonly", width=42)
        self.hesap.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.hesap.bind("<<ComboboxSelected>>", lambda _e: self._hesap_bilgi())
        ttk.Label(
            self,
            text="(Mevduat, KMH, kredi kartı, vadeli)",
            foreground="#555",
        ).grid(row=row, column=3, sticky="w")

        row = 5
        bilgi_c = ttk.Frame(self)
        bilgi_c.grid(row=row, column=0, columnspan=4, padx=12, sticky="w")
        self.hesap_bilgi = ttk.Label(bilgi_c, text="", foreground="#555")
        self.hesap_bilgi.pack(anchor="w")
        from kk_ekstre_ui import EkstreSecici

        self.ekstre = EkstreSecici(bilgi_c)
        self.istek_anahtari = uuid.uuid4().hex

        row = 6
        ttk.Label(self, text="Tutar *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 7
        ttk.Label(self, text="Dekont / makbuz no").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.dekont = ttk.Entry(self, width=24)
        self.dekont.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 8
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=44)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        if self.belge_no:
            ttk.Label(
                self,
                text=f"Belge: {self.belge_no}",
                foreground="#555",
            ).grid(row=9, column=0, columnspan=2, padx=12, sticky="w")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=10, column=0, columnspan=3, padx=12, pady=14, sticky="ew")
        _banka_fis_sil_dugmesi_ekle(self, butonlar)
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            butonlar,
            text="Kaydet",
            command=self.kaydet,
        ).pack(side="right")
        _muhasebe_dugmesi_ekle(self, butonlar, "kasa_banka_virman", self.belge_no)

        self._hesaplari_doldur()
        self._kasa_bilgi()
        self._mevcutu_yukle()

    def _mevcutu_yukle(self):
        m = self._mevcut
        if not m:
            return
        self.tarih.delete(0, "end")
        self.tarih.insert(0, m["tarih"].strftime("%d.%m.%Y"))
        self.tutar.delete(0, "end")
        self.tutar.insert(0, str(m["tutar"]))
        if m.get("dekont_no"):
            self.dekont.insert(0, m["dekont_no"])
        # Varsayılan açıklama metnini formda göstermeyelim
        acik = m.get("aciklama") or ""
        if " → " not in acik:
            self.aciklama.insert(0, acik)
        elif not acik.startswith(tuple(self._kasa_map.keys())):
            # kullanıcı açıklaması olabilir
            self.aciklama.insert(0, acik)
        _combobox_id_sec(self.kasa, self._kasa_map, m.get("kasa_id"))
        self._kasa_bilgi()
        _combobox_id_sec(self.banka, self._banka_map, m.get("banka_karti_id"))
        self._hesaplari_doldur()
        _combobox_id_sec(self.hesap, self._hesap_map, m.get("banka_hesap_id"))
        self._hesap_bilgi()
        # Açıklamayı hesaplar seçildikten sonra düzgün bas
        self.aciklama.delete(0, "end")
        ham = m.get("aciklama") or ""
        # otomatik üretilmiş "A → B" satırını boş bırak
        if " → " in ham and not (m.get("dekont_no") and ham.endswith("")):
            # basit: sadece kullanıcı metni gibi görünenleri koy
            parts = ham.split(" → ", 1)
            if len(parts) == 2 and " | " not in parts[0]:
                pass  # default path description
            else:
                self.aciklama.insert(0, ham)
        else:
            if ham and " → " not in ham:
                self.aciklama.insert(0, ham)

    def _kasa_bilgi(self):
        kid = self._kasa_map.get(self.kasa.get())
        if not kid:
            self.kasa_bilgi.configure(text="")
            return
        h = FinansService.hesap_getir(kid)
        if h:
            self.kasa_bilgi.configure(text=f"Kasa bakiyesi: {_para(FinansService.bakiye(h))}")

    def _hesaplari_doldur(self):
        self._hesap_map = {}
        self.hesap.set("")
        self.hesap_bilgi.configure(text="")
        banka_id = self._banka_map.get(self.banka.get())
        if not banka_id:
            self.hesap.configure(values=[])
            return
        hesaplar = FinansService.banka_yatirim_hesaplari(banka_karti_id=banka_id)
        etiketler = []
        for h in hesaplar:
            alt = (h.alt_hesap_turu or "").upper() or "BANKA"
            tip = self.ALT_ETIKET.get(alt, alt.title())
            bak = FinansService.bakiye(h)
            etiket = f"{tip} — {_para(bak)}"
            if etiket in self._hesap_map:
                etiket = f"{h.hesap_adi} ({_para(bak)})"
            self._hesap_map[etiket] = h.id
            etiketler.append(etiket)
        self.hesap.configure(values=etiketler)
        if etiketler:
            secim = etiketler[0]
            for e, hid in self._hesap_map.items():
                hh = next((x for x in hesaplar if x.id == hid), None)
                if hh and (hh.alt_hesap_turu or "").upper() == "MEVDUAT":
                    secim = e
                    break
            self.hesap.set(secim)
            self._hesap_bilgi()
        else:
            self.hesap_bilgi.configure(
                text="Bu bankada yatırılabilecek hesap yok (mevduat/KMH/KK/vadeli)."
            )

    def _hesap_bilgi(self):
        hid = self._hesap_map.get(self.hesap.get())
        if not hid:
            self.hesap_bilgi.configure(text="")
            return
        h = FinansService.hesap_getir(hid)
        if not h:
            return
        alt = (h.alt_hesap_turu or "").upper() or "—"
        tip = self.ALT_ETIKET.get(alt, alt)
        self.hesap_bilgi.configure(
            text=f"{h.hesap_adi} · Tür: {tip} · Bakiye: {_para(FinansService.bakiye(h))}"
            + (" · Kart hesabına yatırma ekstre ödemesidir; ödenecek ekstreyi seçin." if alt == "KREDI_KARTI" else "")
        )
        if alt == "KREDI_KARTI":
            self.ekstre.pack(anchor="w", pady=(2, 0))
            self.ekstre.doldur(h.id)
        else:
            self.ekstre.pack_forget()

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            kasa_id = self._kasa_map.get(self.kasa.get())
            if not kasa_id:
                raise ValueError("Kasa seçin.")
            if not self._banka_map.get(self.banka.get()):
                raise ValueError("Banka seçin.")
            hesap_id = self._hesap_map.get(self.hesap.get())
            if not hesap_id:
                raise ValueError("Banka hesabı seçin.")
            belge = FinansService.kasadan_bankaya_yatan(
                kasa_id,
                hesap_id,
                tarih,
                self.tutar.get(),
                aciklama=self.aciklama.get().strip() or None,
                dekont_no=self.dekont.get().strip() or None,
                belge_no=self.belge_no,
                ekstre_id=self.ekstre.secili_ekstre_id() if self.ekstre.winfo_manager() else None,
                istek_anahtari=self.istek_anahtari,
            )
        except ValueError as hata:
            messagebox.showerror("Fiş", str(hata), parent=self)
            return
        self.result = belge
        messagebox.showinfo(
            "Kaydedildi" if not self.belge_no else "Güncellendi",
            f"Belge no: {belge}",
            parent=self,
        )
        self.destroy()


class KasalarArasiVirmanDialog(tk.Toplevel):
    """İki kasa arasında virman (KVR) — şirket toplam nakdi değişmez."""

    def __init__(self, parent, belge_no=None, kaynak_kasa_id=None):
        super().__init__(parent)
        self.result = None
        self.belge_no = belge_no
        self._mevcut = None
        self._on_kaynak = kaynak_kasa_id
        if belge_no:
            try:
                self._mevcut = FinansService.banka_islem_fis_getir(belge_no)
            except ValueError as hata:
                messagebox.showerror("Fiş", str(hata), parent=parent)
                self.destroy()
                return
        self.title("Kasalar Arası Virman — Güncelle" if belge_no else "Kasalar Arası Virman")
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        self._kasa_map = {}
        row = 0
        ttk.Label(self, text="Tarih *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        kasalar = FinansService.hesaplar(hesap_turu="KASA")
        kasa_etiketleri = []
        for h in kasalar:
            bak = FinansService.bakiye(h)
            etiket = f"{h.hesap_adi}  ({_para(bak)})"
            self._kasa_map[etiket] = h.id
            kasa_etiketleri.append(etiket)

        row = 1
        ttk.Label(self, text="Kaynak kasa *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.kaynak = ttk.Combobox(self, state="readonly", width=42, values=kasa_etiketleri)
        self.kaynak.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.kaynak.bind("<<ComboboxSelected>>", lambda _e: self._kaynak_bilgi())

        row = 2
        self.kaynak_bilgi = ttk.Label(self, text="", foreground="#555")
        self.kaynak_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 3
        ttk.Label(self, text="Hedef kasa *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.hedef = ttk.Combobox(self, state="readonly", width=42, values=kasa_etiketleri)
        self.hedef.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.hedef.bind("<<ComboboxSelected>>", lambda _e: self._hedef_bilgi())

        row = 4
        self.hedef_bilgi = ttk.Label(self, text="", foreground="#555")
        self.hedef_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 5
        ttk.Label(self, text="Tutar *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 6
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=44)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        if self.belge_no:
            ttk.Label(self, text=f"Belge: {self.belge_no}", foreground="#555").grid(
                row=7, column=0, columnspan=2, padx=12, sticky="w"
            )

        butonlar = ttk.Frame(self)
        butonlar.grid(row=8, column=0, columnspan=3, padx=12, pady=14, sticky="ew")
        _banka_fis_sil_dugmesi_ekle(self, butonlar)
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            butonlar,
            text="Kaydet",
            command=self.kaydet,
        ).pack(side="right")
        _muhasebe_dugmesi_ekle(self, butonlar, "kasa_banka_virman", self.belge_no)

        if kasa_etiketleri:
            if self._on_kaynak:
                _combobox_id_sec(self.kaynak, self._kasa_map, self._on_kaynak)
            else:
                self.kaynak.set(kasa_etiketleri[0])
            hedef_aday = next(
                (e for e in kasa_etiketleri if self._kasa_map[e] != self._kasa_map.get(self.kaynak.get())),
                kasa_etiketleri[-1] if len(kasa_etiketleri) > 1 else "",
            )
            if hedef_aday:
                self.hedef.set(hedef_aday)
        self._kaynak_bilgi()
        self._hedef_bilgi()
        self._mevcutu_yukle()

    def _mevcutu_yukle(self):
        m = self._mevcut
        if not m:
            return
        self.tarih.delete(0, "end")
        self.tarih.insert(0, m["tarih"].strftime("%d.%m.%Y"))
        self.tutar.delete(0, "end")
        self.tutar.insert(0, str(m["tutar"]))
        acik = m.get("aciklama") or ""
        if " → " not in acik:
            self.aciklama.insert(0, acik)
        _combobox_id_sec(self.kaynak, self._kasa_map, m.get("kaynak_kasa_id"))
        _combobox_id_sec(self.hedef, self._kasa_map, m.get("hedef_kasa_id"))
        self._kaynak_bilgi()
        self._hedef_bilgi()

    def _kaynak_bilgi(self):
        kid = self._kasa_map.get(self.kaynak.get())
        if not kid:
            self.kaynak_bilgi.configure(text="")
            return
        h = FinansService.hesap_getir(kid)
        if h:
            self.kaynak_bilgi.configure(
                text=f"Bakiye: {_para(FinansService.bakiye(h))} · PB: {FinansService.hesap_pb(h)}"
            )

    def _hedef_bilgi(self):
        kid = self._kasa_map.get(self.hedef.get())
        if not kid:
            self.hedef_bilgi.configure(text="")
            return
        h = FinansService.hesap_getir(kid)
        if h:
            self.hedef_bilgi.configure(
                text=f"Bakiye: {_para(FinansService.bakiye(h))} · PB: {FinansService.hesap_pb(h)}"
            )

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            kaynak_id = self._kasa_map.get(self.kaynak.get())
            hedef_id = self._kasa_map.get(self.hedef.get())
            if not kaynak_id:
                raise ValueError("Kaynak kasa seçin.")
            if not hedef_id:
                raise ValueError("Hedef kasa seçin.")
            belge = FinansService.kasalar_arasi_virman(
                kaynak_id,
                hedef_id,
                tarih,
                self.tutar.get(),
                aciklama=self.aciklama.get().strip() or None,
                belge_no=self.belge_no,
            )
        except ValueError as hata:
            messagebox.showerror("Fiş", str(hata), parent=self)
            return
        self.result = belge
        messagebox.showinfo(
            "Kaydedildi" if not self.belge_no else "Güncellendi",
            f"Belge no: {belge}",
            parent=self,
        )
        self.destroy()


def bankadan_cekilen_sayfasi_goster(app):
    """Bankadan çekilen (nakit) fiş listesi + yeni fiş."""
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BANKADAN ÇEKİLEN", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Banka İşlemleri", command=lambda: banka_islemleri_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(
        app.icerik,
        text="Mevduat, KMH, kredi kartı veya vadeli hesaptan nakit çekip kasaya yatırma.",
    ).pack(anchor="w", pady=(10, 6))

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=(4, 8))
    ttk.Button(butonlar, text="Yeni Fiş", command=lambda: _bnc_yeni_fis(app)).pack(side="left")
    ttk.Button(butonlar, text="Güncelle", command=lambda: _bnc_guncelle_fis(app, tablo)).pack(
        side="left", padx=8
    )
    ttk.Button(
        butonlar,
        text="Yenile",
        command=lambda: bankadan_cekilen_sayfasi_goster(app),
    ).pack(side="left", padx=8)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    tablo = ttk.Treeview(
        cerceve,
        columns=("tarih", "belge", "banka", "kasa", "tutar", "muhasebe", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("tarih", "Tarih", 90),
        ("belge", "Belge No", 120),
        ("banka", "Banka hesabı", 220),
        ("kasa", "Kasa", 150),
        ("tutar", "Tutar", 110),
        ("muhasebe", "Muhasebe", 130),
        ("aciklama", "Açıklama", 260),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    tablo.bind("<Double-1>", lambda _e: _bnc_guncelle_fis(app, tablo))

    kayitlar = FinansService.bankadan_nakit_cekilen_listele()
    muhasebe = _muhasebe_durumlari("kasa_banka_virman", kayitlar)
    for kayit in kayitlar:
        tablo.insert(
            "",
            "end",
            iid=kayit["belge_no"],
            values=(
                _tarih(kayit["tarih"]),
                kayit["belge_no"],
                kayit["banka_hesap"],
                kayit["kasa"],
                _para(kayit["tutar"]),
                muhasebe.get(kayit["belge_no"], ""),
                kayit["aciklama"],
            ),
        )


def _bnc_yeni_fis(app):
    dialog = BankadanCekilenDialog(app)
    app.wait_window(dialog)
    if dialog.result:
        bankadan_cekilen_sayfasi_goster(app)


def _bnc_guncelle_fis(app, tablo):
    secim = tablo.selection()
    if not secim:
        messagebox.showinfo("Güncelle", "Lütfen güncellenecek fişi seçin.", parent=app)
        return
    dialog = BankadanCekilenDialog(app, belge_no=secim[0])
    app.wait_window(dialog)
    if dialog.result:
        bankadan_cekilen_sayfasi_goster(app)


class BankadanCekilenDialog(tk.Toplevel):
    """Bankadan çekilen fiş formu (KBY'nin tersi)."""

    ALT_ETIKET = KasadanBankayaYatirDialog.ALT_ETIKET

    def __init__(self, parent, belge_no=None):
        super().__init__(parent)
        self.result = None
        self.belge_no = belge_no
        self._mevcut = None
        if belge_no:
            try:
                self._mevcut = FinansService.banka_islem_fis_getir(belge_no)
            except ValueError as hata:
                messagebox.showerror("Fiş", str(hata), parent=parent)
                self.destroy()
                return
        self.title("Bankadan Çekilen — Güncelle" if belge_no else "Bankadan Çekilen")
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        self._kasa_map = {}
        self._banka_map = {}
        self._hesap_map = {}

        row = 0
        ttk.Label(self, text="Tarih *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        row = 1
        kartlar = FinansService.banka_kartlari(aktif_only=True)
        ttk.Label(self, text="Banka *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.banka = ttk.Combobox(self, state="readonly", width=42)
        self.banka.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        banka_etiketleri = []
        for k in kartlar:
            etiket = k.banka_adi
            if k.sube:
                etiket = f"{etiket} / {k.sube}"
            if k.hesap_no:
                etiket = f"{etiket} ({k.hesap_no})"
            self._banka_map[etiket] = k.id
            banka_etiketleri.append(etiket)
        self.banka.configure(values=banka_etiketleri)
        if banka_etiketleri:
            self.banka.set(banka_etiketleri[0])
        self.banka.bind("<<ComboboxSelected>>", lambda _e: self._hesaplari_doldur())

        row = 2
        ttk.Label(self, text="Banka hesabı *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.hesap = ttk.Combobox(self, state="readonly", width=42)
        self.hesap.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.hesap.bind("<<ComboboxSelected>>", lambda _e: self._hesap_bilgi())
        ttk.Label(
            self,
            text="(Mevduat, KMH, kredi kartı, vadeli)",
            foreground="#555",
        ).grid(row=row, column=3, sticky="w")

        row = 3
        self.hesap_bilgi = ttk.Label(self, text="", foreground="#555")
        self.hesap_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 4
        kasalar = FinansService.hesaplar(hesap_turu="KASA")
        ttk.Label(self, text="Kasa *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.kasa = ttk.Combobox(self, state="readonly", width=42)
        self.kasa.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        kasa_etiketleri = []
        for h in kasalar:
            bak = FinansService.bakiye(h)
            etiket = f"{h.hesap_adi}  ({_para(bak)})"
            self._kasa_map[etiket] = h.id
            kasa_etiketleri.append(etiket)
        self.kasa.configure(values=kasa_etiketleri)
        if kasa_etiketleri:
            self.kasa.set(kasa_etiketleri[0])
        self.kasa.bind("<<ComboboxSelected>>", lambda _e: self._kasa_bilgi())

        row = 5
        self.kasa_bilgi = ttk.Label(self, text="", foreground="#555")
        self.kasa_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 6
        ttk.Label(self, text="Tutar *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 7
        ttk.Label(self, text="Dekont / makbuz no").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.dekont = ttk.Entry(self, width=24)
        self.dekont.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 8
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=44)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        if self.belge_no:
            ttk.Label(
                self,
                text=f"Belge: {self.belge_no}",
                foreground="#555",
            ).grid(row=9, column=0, columnspan=2, padx=12, sticky="w")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=10, column=0, columnspan=3, padx=12, pady=14, sticky="ew")
        _banka_fis_sil_dugmesi_ekle(self, butonlar)
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            butonlar,
            text="Kaydet",
            command=self.kaydet,
        ).pack(side="right")
        _muhasebe_dugmesi_ekle(self, butonlar, "kasa_banka_virman", self.belge_no)

        self._hesaplari_doldur()
        self._kasa_bilgi()
        self._mevcutu_yukle()

    def _mevcutu_yukle(self):
        m = self._mevcut
        if not m:
            return
        self.tarih.delete(0, "end")
        self.tarih.insert(0, m["tarih"].strftime("%d.%m.%Y"))
        self.tutar.delete(0, "end")
        self.tutar.insert(0, str(m["tutar"]))
        if m.get("dekont_no"):
            self.dekont.insert(0, m["dekont_no"])
        _combobox_id_sec(self.banka, self._banka_map, m.get("banka_karti_id"))
        self._hesaplari_doldur()
        _combobox_id_sec(self.hesap, self._hesap_map, m.get("banka_hesap_id"))
        self._hesap_bilgi()
        _combobox_id_sec(self.kasa, self._kasa_map, m.get("kasa_id"))
        self._kasa_bilgi()
        self.aciklama.delete(0, "end")
        ham = m.get("aciklama") or ""
        if ham and " → " not in ham:
            self.aciklama.insert(0, ham)

    def _kasa_bilgi(self):
        kid = self._kasa_map.get(self.kasa.get())
        if not kid:
            self.kasa_bilgi.configure(text="")
            return
        h = FinansService.hesap_getir(kid)
        if h:
            self.kasa_bilgi.configure(text=f"Kasa bakiyesi: {_para(FinansService.bakiye(h))}")

    def _hesaplari_doldur(self):
        self._hesap_map = {}
        self.hesap.set("")
        self.hesap_bilgi.configure(text="")
        banka_id = self._banka_map.get(self.banka.get())
        if not banka_id:
            self.hesap.configure(values=[])
            return
        hesaplar = FinansService.banka_yatirim_hesaplari(banka_karti_id=banka_id)
        etiketler = []
        for h in hesaplar:
            alt = (h.alt_hesap_turu or "").upper() or "BANKA"
            tip = self.ALT_ETIKET.get(alt, alt.title())
            bak = FinansService.bakiye(h)
            etiket = f"{tip} — {_para(bak)}"
            if etiket in self._hesap_map:
                etiket = f"{h.hesap_adi} ({_para(bak)})"
            self._hesap_map[etiket] = h.id
            etiketler.append(etiket)
        self.hesap.configure(values=etiketler)
        if etiketler:
            secim = etiketler[0]
            for e, hid in self._hesap_map.items():
                hh = next((x for x in hesaplar if x.id == hid), None)
                if hh and (hh.alt_hesap_turu or "").upper() == "MEVDUAT":
                    secim = e
                    break
            self.hesap.set(secim)
            self._hesap_bilgi()
        else:
            self.hesap_bilgi.configure(
                text="Bu bankada çekilebilecek hesap yok (mevduat/KMH/KK/vadeli)."
            )

    def _hesap_bilgi(self):
        hid = self._hesap_map.get(self.hesap.get())
        if not hid:
            self.hesap_bilgi.configure(text="")
            return
        h = FinansService.hesap_getir(hid)
        if not h:
            return
        alt = (h.alt_hesap_turu or "").upper() or "—"
        tip = self.ALT_ETIKET.get(alt, alt)
        self.hesap_bilgi.configure(
            text=f"{h.hesap_adi} · Tür: {tip} · Bakiye: {_para(FinansService.bakiye(h))}"
        )

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            if not self._banka_map.get(self.banka.get()):
                raise ValueError("Banka seçin.")
            hesap_id = self._hesap_map.get(self.hesap.get())
            if not hesap_id:
                raise ValueError("Banka hesabı seçin.")
            kasa_id = self._kasa_map.get(self.kasa.get())
            if not kasa_id:
                raise ValueError("Kasa seçin.")
            belge = FinansService.bankadan_nakit_cekilen(
                hesap_id,
                kasa_id,
                tarih,
                self.tutar.get(),
                aciklama=self.aciklama.get().strip() or None,
                dekont_no=self.dekont.get().strip() or None,
                belge_no=self.belge_no,
            )
        except ValueError as hata:
            messagebox.showerror("Fiş", str(hata), parent=self)
            return
        self.result = belge
        messagebox.showinfo(
            "Kaydedildi" if not self.belge_no else "Güncellendi",
            f"Belge no: {belge}",
            parent=self,
        )
        self.destroy()


def alinan_havale_sayfasi_goster(app):
    _havale_sayfasi_goster(
        app,
        baslik="ALINAN HAVALE",
        aciklama="Gönderen cariden banka hesabına gelen havale (cari tahsilat).",
        tur="ahv",
        liste_fn=FinansService.alinan_havale_listele,
        cari_kolon="Gönderen cari",
    )


def gonderilen_havale_sayfasi_goster(app):
    _havale_sayfasi_goster(
        app,
        baslik="GÖNDERİLEN HAVALE",
        aciklama="Banka hesabından alıcı cariye giden havale (cari ödeme).",
        tur="ghv",
        liste_fn=FinansService.gonderilen_havale_listele,
        cari_kolon="Alıcı cari",
    )


def _havale_sayfasi_goster(app, baslik, aciklama, tur, liste_fn, cari_kolon):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Banka İşlemleri", command=lambda: banka_islemleri_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(app.icerik, text=aciklama).pack(anchor="w", pady=(10, 6))

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=(4, 8))

    def _yenile():
        if tur == "ahv":
            alinan_havale_sayfasi_goster(app)
        else:
            gonderilen_havale_sayfasi_goster(app)

    def _yeni():
        dialog = HavaleFisDialog(app, tur=tur)
        app.wait_window(dialog)
        if dialog.result:
            _yenile()

    def _guncelle():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Güncelle", "Lütfen güncellenecek fişi seçin.", parent=app)
            return
        dialog = HavaleFisDialog(app, tur=tur, belge_no=secim[0])
        app.wait_window(dialog)
        if dialog.result:
            _yenile()

    ttk.Button(butonlar, text="Yeni Fiş", command=_yeni).pack(side="left")
    ttk.Button(butonlar, text="Güncelle", command=_guncelle).pack(side="left", padx=8)
    ttk.Button(butonlar, text="Yenile", command=_yenile).pack(side="left", padx=8)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    tablo = ttk.Treeview(
        cerceve,
        columns=("tarih", "belge", "cari", "banka", "tutar", "muhasebe", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("tarih", "Tarih", 90),
        ("belge", "Belge No", 120),
        ("cari", cari_kolon, 220),
        ("banka", "Banka hesabı", 200),
        ("tutar", "Tutar", 110),
        ("muhasebe", "Muhasebe", 130),
        ("aciklama", "Açıklama", 240),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    tablo.bind("<Double-1>", lambda _e: _guncelle())

    kayitlar = liste_fn()
    muhasebe = _muhasebe_durumlari("banka_havale", kayitlar)
    for kayit in kayitlar:
        tablo.insert(
            "",
            "end",
            iid=kayit["belge_no"],
            values=(
                _tarih(kayit["tarih"]),
                kayit["belge_no"],
                kayit["cari"],
                kayit["banka_hesap"],
                _para(kayit["tutar"]),
                muhasebe.get(kayit["belge_no"], ""),
                kayit["aciklama"],
            ),
        )


class HavaleFisDialog(tk.Toplevel):
    """Alınan / gönderilen havale fiş formu."""

    ALT_ETIKET = KasadanBankayaYatirDialog.ALT_ETIKET

    def __init__(self, parent, tur: str, belge_no=None):
        super().__init__(parent)
        self.tur = tur  # ahv | ghv
        self.result = None
        self.belge_no = belge_no
        self._mevcut = None
        if belge_no:
            try:
                self._mevcut = FinansService.banka_islem_fis_getir(belge_no)
            except ValueError as hata:
                messagebox.showerror("Fiş", str(hata), parent=parent)
                self.destroy()
                return
        alinan = tur == "ahv"
        baslik = "Alınan Havale" if alinan else "Gönderilen Havale"
        self.title(f"{baslik} — Güncelle" if belge_no else baslik)
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        from database.cari_service import CariService

        self._cari_map = {}
        self._banka_map = {}
        self._hesap_map = {}

        row = 0
        ttk.Label(self, text="Tarih *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        row = 1
        cari_etiket = "Gönderen cari *" if alinan else "Alıcı cari *"
        cariler = CariService.listele(hizli=True)
        self._cari_map = {
            f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in cariler
        }
        ttk.Label(self, text=cari_etiket).grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.cari = ttk.Combobox(self, values=list(self._cari_map), width=42)
        self.cari.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        if self._cari_map:
            self.cari.set(next(iter(self._cari_map)))

        row = 2
        kartlar = FinansService.banka_kartlari(aktif_only=True)
        ttk.Label(self, text="Banka *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.banka = ttk.Combobox(self, state="readonly", width=42)
        self.banka.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        banka_etiketleri = []
        for k in kartlar:
            etiket = k.banka_adi
            if k.sube:
                etiket = f"{etiket} / {k.sube}"
            if k.hesap_no:
                etiket = f"{etiket} ({k.hesap_no})"
            self._banka_map[etiket] = k.id
            banka_etiketleri.append(etiket)
        self.banka.configure(values=banka_etiketleri)
        if banka_etiketleri:
            self.banka.set(banka_etiketleri[0])
        self.banka.bind("<<ComboboxSelected>>", lambda _e: self._hesaplari_doldur())

        row = 3
        ttk.Label(self, text="Banka hesabı *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.hesap = ttk.Combobox(self, state="readonly", width=42)
        self.hesap.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.hesap.bind("<<ComboboxSelected>>", lambda _e: self._hesap_bilgi())
        ttk.Label(
            self,
            text="(Mevduat, KMH, kredi kartı, vadeli)",
            foreground="#555",
        ).grid(row=row, column=3, sticky="w")

        row = 4
        self.hesap_bilgi = ttk.Label(self, text="", foreground="#555")
        self.hesap_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 5
        ttk.Label(self, text="Meblağ *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 6
        ttk.Label(self, text="Dekont / referans no").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.dekont = ttk.Entry(self, width=24)
        self.dekont.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 7
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=44)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        if self.belge_no:
            ttk.Label(
                self,
                text=f"Belge: {self.belge_no}",
                foreground="#555",
            ).grid(row=8, column=0, columnspan=2, padx=12, sticky="w")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=9, column=0, columnspan=3, padx=12, pady=14, sticky="ew")
        _banka_fis_sil_dugmesi_ekle(self, butonlar)
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            butonlar,
            text="Kaydet",
            command=self.kaydet,
        ).pack(side="right")
        _muhasebe_dugmesi_ekle(self, butonlar, "banka_havale", self.belge_no)

        self._hesaplari_doldur()
        self._mevcutu_yukle()

    def _mevcutu_yukle(self):
        m = self._mevcut
        if not m:
            return
        self.tarih.delete(0, "end")
        self.tarih.insert(0, m["tarih"].strftime("%d.%m.%Y"))
        self.tutar.delete(0, "end")
        self.tutar.insert(0, str(m["tutar"]))
        if m.get("dekont_no"):
            self.dekont.insert(0, m["dekont_no"])
        cari_etiket = (m.get("cari_etiket") or "").strip()
        if cari_etiket and cari_etiket in self._cari_map:
            self.cari.set(cari_etiket)
        else:
            _combobox_id_sec(self.cari, self._cari_map, m.get("cari_id"))
        _combobox_id_sec(self.banka, self._banka_map, m.get("banka_karti_id"))
        self._hesaplari_doldur()
        _combobox_id_sec(self.hesap, self._hesap_map, m.get("banka_hesap_id"))
        self._hesap_bilgi()
        self.aciklama.delete(0, "end")
        ham = m.get("aciklama") or ""
        varsayilan = "Alınan havale" if self.tur == "ahv" else "Gönderilen havale"
        if ham and ham != varsayilan:
            self.aciklama.insert(0, ham)

    def _hesaplari_doldur(self):
        self._hesap_map = {}
        self.hesap.set("")
        self.hesap_bilgi.configure(text="")
        banka_id = self._banka_map.get(self.banka.get())
        if not banka_id:
            self.hesap.configure(values=[])
            return
        hesaplar = FinansService.banka_yatirim_hesaplari(banka_karti_id=banka_id)
        etiketler = []
        for h in hesaplar:
            alt = (h.alt_hesap_turu or "").upper() or "BANKA"
            tip = self.ALT_ETIKET.get(alt, alt.title())
            bak = FinansService.bakiye(h)
            etiket = f"{tip} — {_para(bak)}"
            if etiket in self._hesap_map:
                etiket = f"{h.hesap_adi} ({_para(bak)})"
            self._hesap_map[etiket] = h.id
            etiketler.append(etiket)
        self.hesap.configure(values=etiketler)
        if etiketler:
            secim = etiketler[0]
            for e, hid in self._hesap_map.items():
                hh = next((x for x in hesaplar if x.id == hid), None)
                if hh and (hh.alt_hesap_turu or "").upper() == "MEVDUAT":
                    secim = e
                    break
            self.hesap.set(secim)
            self._hesap_bilgi()
        else:
            self.hesap_bilgi.configure(text="Bu bankada uygun hesap yok.")

    def _hesap_bilgi(self):
        hid = self._hesap_map.get(self.hesap.get())
        if not hid:
            self.hesap_bilgi.configure(text="")
            return
        h = FinansService.hesap_getir(hid)
        if not h:
            return
        alt = (h.alt_hesap_turu or "").upper() or "—"
        tip = self.ALT_ETIKET.get(alt, alt)
        self.hesap_bilgi.configure(
            text=f"{h.hesap_adi} · Tür: {tip} · Bakiye: {_para(FinansService.bakiye(h))}"
        )

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            cari_id = self._cari_map.get(self.cari.get().strip()) if self.cari.get() else None
            if cari_id is None:
                raise ValueError(
                    "Gönderen cari seçin." if self.tur == "ahv" else "Alıcı cari seçin."
                )
            if not self._banka_map.get(self.banka.get()):
                raise ValueError("Banka seçin.")
            hesap_id = self._hesap_map.get(self.hesap.get())
            if not hesap_id:
                raise ValueError("Banka hesabı seçin.")
            kwargs = dict(
                banka_hesap_id=hesap_id,
                tarih=tarih,
                tutar=self.tutar.get(),
                cari_id=cari_id,
                aciklama=self.aciklama.get().strip() or None,
                dekont_no=self.dekont.get().strip() or None,
                belge_no=self.belge_no,
            )
            if self.tur == "ahv":
                belge = FinansService.alinan_havale(**kwargs)
            else:
                belge = FinansService.gonderilen_havale(**kwargs)
        except ValueError as hata:
            messagebox.showerror("Fiş", str(hata), parent=self)
            return
        self.result = belge
        messagebox.showinfo(
            "Kaydedildi" if not self.belge_no else "Güncellendi",
            f"Belge no: {belge}",
            parent=self,
        )
        if not self.belge_no:
            _soz_bagla(self, cari_id, "ALINAN" if self.tur == "ahv" else "VERILEN",
                       "Alınan Havale" if self.tur == "ahv" else "Gönderilen Havale", belge)
        self.destroy()


def bankalar_arasi_virman_sayfasi_goster(app):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BANKA TRANSFER VE VİRMAN İŞLEMLERİ", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Banka İşlemleri", command=lambda: banka_islemleri_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(
        app.icerik,
        text="Firmanın kendi banka hesapları arasında virman, havale, EFT veya FAST aktarımı.",
    ).pack(anchor="w", pady=(10, 6))

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=(4, 8))

    def _yeni():
        dialog = BankalarArasiVirmanDialog(app)
        app.wait_window(dialog)
        if dialog.result:
            bankalar_arasi_virman_sayfasi_goster(app)

    def _guncelle():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Güncelle", "Lütfen güncellenecek fişi seçin.", parent=app)
            return
        dialog = BankalarArasiVirmanDialog(app, belge_no=secim[0])
        app.wait_window(dialog)
        if dialog.result:
            bankalar_arasi_virman_sayfasi_goster(app)

    ttk.Button(butonlar, text="Yeni Fiş", command=_yeni).pack(side="left")
    ttk.Button(butonlar, text="Güncelle", command=_guncelle).pack(side="left", padx=8)
    ttk.Button(
        butonlar,
        text="Yenile",
        command=lambda: bankalar_arasi_virman_sayfasi_goster(app),
    ).pack(side="left", padx=8)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    tablo = ttk.Treeview(
        cerceve,
        columns=("tarih", "belge", "tur", "cikis", "giris", "tutar", "masraf", "muhasebe", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("tarih", "Tarih", 90),
        ("belge", "Belge No", 110),
        ("tur", "İşlem türü", 80),
        ("cikis", "Gönderen hesap", 200),
        ("giris", "Alıcı hesap", 200),
        ("tutar", "Transfer tutarı", 110),
        ("masraf", "Masraf", 90),
        ("muhasebe", "Muhasebe", 130),
        ("aciklama", "Açıklama", 200),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    tablo.bind("<Double-1>", lambda _e: _guncelle())

    kayitlar = FinansService.bankalar_arasi_virman_listele()
    muhasebe = _muhasebe_durumlari("kasa_banka_virman", kayitlar)
    for kayit in kayitlar:
        masraf = kayit.get("masraf") or 0
        tablo.insert(
            "",
            "end",
            iid=kayit["belge_no"],
            values=(
                _tarih(kayit["tarih"]),
                kayit["belge_no"],
                kayit["belge_turu"],
                kayit["cikis_hesap"],
                kayit["giris_hesap"],
                _para(kayit["tutar"]),
                _para(masraf) if masraf else "—",
                muhasebe.get(kayit["belge_no"], ""),
                kayit["aciklama"],
            ),
        )


class BankalarArasiVirmanDialog(tk.Toplevel):
    """Gönderen → alıcı banka transfer / virman (VIRMAN / HAVALE / EFT / FAST)."""

    ALT_ETIKET = KasadanBankayaYatirDialog.ALT_ETIKET
    ISLEM_TURLERI = ("VIRMAN", "HAVALE", "EFT", "FAST")

    def __init__(self, parent, belge_no=None):
        super().__init__(parent)
        self.result = None
        self.belge_no = belge_no
        self._mevcut = None
        self._kaydediliyor = False
        if belge_no:
            try:
                self._mevcut = FinansService.banka_islem_fis_getir(belge_no)
            except ValueError as hata:
                messagebox.showerror("Fiş", str(hata), parent=parent)
                self.destroy()
                return
        self.title(
            "Banka Transfer ve Virman Fişi — Güncelle"
            if belge_no
            else "Banka Transfer ve Virman Fişi"
        )
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)
        self.resizable(True, True)
        self.minsize(560, 480)

        self._cikis_banka_map = {}
        self._giris_banka_map = {}
        self._cikis_hesap_map = {}
        self._giris_hesap_map = {}
        self._masraf_hesap_map = {}

        govde = ttk.Frame(self)
        govde.pack(fill="both", expand=True, padx=4, pady=4)
        govde.columnconfigure(1, weight=1)

        row = 0
        ttk.Label(govde, text="Tarih *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(govde)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        row = 1
        ttk.Label(govde, text="İşlem türü *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.belge_turu = ttk.Combobox(
            govde, values=self.ISLEM_TURLERI, state="readonly", width=16
        )
        self.belge_turu.set("HAVALE")
        self.belge_turu.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 2
        ttk.Label(govde, text="Gönderen banka *").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.cikis_banka = ttk.Combobox(govde, state="readonly", width=48)
        self.cikis_banka.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="ew")
        self.cikis_banka.bind(
            "<<ComboboxSelected>>", lambda _e: self._hesaplari_doldur("cikis")
        )

        row = 3
        ttk.Label(govde, text="Gönderen hesap *").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.cikis_hesap = ttk.Combobox(govde, state="readonly", width=48)
        self.cikis_hesap.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="ew")
        self.cikis_hesap.bind(
            "<<ComboboxSelected>>",
            lambda _e: (self._hesap_bilgi("cikis"), self._tur_oner(), self._masraf_hesaplari_doldur()),
        )

        row = 4
        self.cikis_bilgi = ttk.Label(govde, text="", foreground="#555")
        self.cikis_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 5
        ttk.Label(govde, text="Alıcı banka *").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.giris_banka = ttk.Combobox(govde, state="readonly", width=48)
        self.giris_banka.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="ew")
        self.giris_banka.bind(
            "<<ComboboxSelected>>", lambda _e: self._hesaplari_doldur("giris")
        )

        row = 6
        ttk.Label(govde, text="Alıcı hesap *").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.giris_hesap = ttk.Combobox(govde, state="readonly", width=48)
        self.giris_hesap.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="ew")
        self.giris_hesap.bind(
            "<<ComboboxSelected>>",
            lambda _e: (self._hesap_bilgi("giris"), self._tur_oner(), self._masraf_hesaplari_doldur()),
        )

        row = 7
        giris_c = ttk.Frame(govde)
        giris_c.grid(row=row, column=0, columnspan=4, padx=12, sticky="ew")
        self.giris_bilgi = ttk.Label(giris_c, text="", foreground="#555")
        self.giris_bilgi.pack(anchor="w")
        from kk_ekstre_ui import EkstreSecici

        self.ekstre = EkstreSecici(giris_c)
        self.istek_anahtari = uuid.uuid4().hex

        row = 8
        ttk.Label(govde, text="Transfer tutarı *").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.tutar = ttk.Entry(govde, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 9
        ttk.Label(govde, text="Banka masrafı").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        masraf_c = ttk.Frame(govde)
        masraf_c.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.masraf = ttk.Entry(masraf_c, width=14)
        self.masraf.pack(side="left")
        self.masraf.insert(0, "0")
        ttk.Label(masraf_c, text="  Masraf hesabı").pack(side="left", padx=(10, 4))
        self.masraf_hesap = ttk.Combobox(masraf_c, state="readonly", width=28)
        self.masraf_hesap.pack(side="left")

        row = 10
        ttk.Label(govde, text="Dekont / referans no").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.dekont = ttk.Entry(govde, width=24)
        self.dekont.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 11
        ttk.Label(govde, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(govde, width=48)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="ew")

        row = 12
        if self.belge_no:
            ttk.Label(
                govde,
                text=f"Belge: {self.belge_no}",
                foreground="#555",
            ).grid(row=row, column=0, columnspan=2, padx=12, sticky="w")
            row += 1

        butonlar = ttk.Frame(govde)
        butonlar.grid(row=row, column=0, columnspan=3, padx=12, pady=14, sticky="ew")
        _banka_fis_sil_dugmesi_ekle(self, butonlar)
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        self._kaydet_btn = ttk.Button(
            butonlar,
            text="Kaydet",
            command=self.kaydet,
        )
        self._kaydet_btn.pack(side="right")
        _muhasebe_dugmesi_ekle(self, butonlar, "kasa_banka_virman", self.belge_no)

        self._bankalari_doldur()
        self._mevcutu_yukle()

    def _mevcutu_yukle(self):
        m = self._mevcut
        if not m:
            return
        self.tarih.delete(0, "end")
        self.tarih.insert(0, m["tarih"].strftime("%d.%m.%Y"))
        self.tutar.delete(0, "end")
        self.tutar.insert(0, str(m["tutar"]))
        self.masraf.delete(0, "end")
        self.masraf.insert(0, str(m.get("masraf_tutar") or 0))
        if m.get("dekont_no"):
            self.dekont.insert(0, m["dekont_no"])
        belge_turu = (m.get("belge_turu") or "HAVALE").strip().upper()
        if belge_turu in self.ISLEM_TURLERI:
            self.belge_turu.set(belge_turu)
        _combobox_id_sec(self.cikis_banka, self._cikis_banka_map, m.get("cikis_banka_karti_id"))
        self._hesaplari_doldur("cikis")
        _combobox_id_sec(self.cikis_hesap, self._cikis_hesap_map, m.get("cikis_hesap_id"))
        self._hesap_bilgi("cikis")
        _combobox_id_sec(self.giris_banka, self._giris_banka_map, m.get("giris_banka_karti_id"))
        self._hesaplari_doldur("giris")
        _combobox_id_sec(self.giris_hesap, self._giris_hesap_map, m.get("giris_hesap_id"))
        self._hesap_bilgi("giris")
        self._masraf_hesaplari_doldur()
        if m.get("masraf_hesap_id"):
            _combobox_id_sec(self.masraf_hesap, self._masraf_hesap_map, m.get("masraf_hesap_id"))
        self.aciklama.delete(0, "end")
        ham = m.get("aciklama") or ""
        if ham and " → " not in ham:
            self.aciklama.insert(0, ham)

    def _banka_etiket(self, k):
        etiket = k.banka_adi
        if k.sube:
            etiket = f"{etiket} / {k.sube}"
        if k.hesap_no:
            etiket = f"{etiket} ({k.hesap_no})"
        return etiket

    def _bankalari_doldur(self):
        kartlar = FinansService.banka_kartlari(aktif_only=True)
        etiketler = []
        self._cikis_banka_map = {}
        self._giris_banka_map = {}
        for k in kartlar:
            etiket = self._banka_etiket(k)
            self._cikis_banka_map[etiket] = k.id
            self._giris_banka_map[etiket] = k.id
            etiketler.append(etiket)
        self.cikis_banka.configure(values=etiketler)
        self.giris_banka.configure(values=etiketler)
        if etiketler:
            self.cikis_banka.set(etiketler[0])
            self.giris_banka.set(etiketler[1] if len(etiketler) > 1 else etiketler[0])
        self._hesaplari_doldur("cikis")
        self._hesaplari_doldur("giris")
        self._masraf_hesaplari_doldur()
        self._tur_oner()

    def _hesaplari_doldur(self, yon: str):
        if yon == "cikis":
            banka_cb, hesap_cb, bilgi, bmap, hmap = (
                self.cikis_banka,
                self.cikis_hesap,
                self.cikis_bilgi,
                self._cikis_banka_map,
                "_cikis_hesap_map",
            )
        else:
            banka_cb, hesap_cb, bilgi, bmap, hmap = (
                self.giris_banka,
                self.giris_hesap,
                self.giris_bilgi,
                self._giris_banka_map,
                "_giris_hesap_map",
            )
        setattr(self, hmap, {})
        hesap_cb.set("")
        bilgi.configure(text="")
        banka_id = bmap.get(banka_cb.get())
        if not banka_id:
            hesap_cb.configure(values=[])
            return
        hesaplar = FinansService.banka_yatirim_hesaplari(banka_karti_id=banka_id)
        etiketler = []
        hesap_map = {}
        for h in hesaplar:
            alt = (h.alt_hesap_turu or "").upper() or "BANKA"
            tip = self.ALT_ETIKET.get(alt, alt.title())
            bak = FinansService.bakiye(h)
            etiket = f"{h.hesap_adi} — {tip} — {_para(bak)}"
            if etiket in hesap_map:
                etiket = f"{h.hesap_adi} ({_para(bak)}) #{h.id}"
            hesap_map[etiket] = h.id
            etiketler.append(etiket)
        setattr(self, hmap, hesap_map)
        hesap_cb.configure(values=etiketler)
        if etiketler:
            secim = etiketler[0]
            for e, hid in hesap_map.items():
                hh = next((x for x in hesaplar if x.id == hid), None)
                if hh and (hh.alt_hesap_turu or "").upper() == "MEVDUAT":
                    secim = e
                    break
            hesap_cb.set(secim)
            self._hesap_bilgi(yon)
        else:
            bilgi.configure(text="Bu bankada uygun hesap yok.")
        if yon == "cikis":
            self._masraf_hesaplari_doldur()
            self._tur_oner()
        else:
            self._tur_oner()
            self._masraf_hesaplari_doldur()

    def _masraf_hesaplari_doldur(self):
        self._masraf_hesap_map = {}
        etiketler = []
        for etiket, hid in list(self._cikis_hesap_map.items()) + list(self._giris_hesap_map.items()):
            if hid in self._masraf_hesap_map.values():
                continue
            self._masraf_hesap_map[etiket] = hid
            etiketler.append(etiket)
        self.masraf_hesap.configure(values=etiketler)
        cikis_etiket = self.cikis_hesap.get()
        if cikis_etiket and cikis_etiket in self._masraf_hesap_map:
            self.masraf_hesap.set(cikis_etiket)
        elif etiketler:
            self.masraf_hesap.set(etiketler[0])
        else:
            self.masraf_hesap.set("")

    def _tur_oner(self):
        """Aynı banka → VIRMAN; farklı banka → EFT öner (zorunlu değil)."""
        if self._mevcut:
            return
        c_id = self._cikis_banka_map.get(self.cikis_banka.get())
        g_id = self._giris_banka_map.get(self.giris_banka.get())
        if not c_id or not g_id:
            return
        mevcut = (self.belge_turu.get() or "").strip().upper()
        if c_id == g_id:
            if mevcut in ("EFT", "FAST"):
                self.belge_turu.set("VIRMAN")
        else:
            if mevcut in ("VIRMAN", "HAVALE"):
                self.belge_turu.set("EFT")

    def _hesap_bilgi(self, yon: str):
        if yon == "cikis":
            hesap_cb, bilgi, hmap = self.cikis_hesap, self.cikis_bilgi, self._cikis_hesap_map
        else:
            hesap_cb, bilgi, hmap = self.giris_hesap, self.giris_bilgi, self._giris_hesap_map
        hid = hmap.get(hesap_cb.get())
        if not hid:
            bilgi.configure(text="")
            return
        h = FinansService.hesap_getir(hid)
        if not h:
            return
        alt = (h.alt_hesap_turu or "").upper() or "—"
        tip = self.ALT_ETIKET.get(alt, alt)
        kart_girisi = yon == "giris" and alt == "KREDI_KARTI"
        bilgi.configure(
            text=f"{h.hesap_adi} · Tür: {tip} · Bakiye: {_para(FinansService.bakiye(h))}"
            + (" · Kart hesabına virman ekstre ödemesidir; ödenecek ekstreyi seçin." if kart_girisi else "")
        )
        if yon == "giris":
            if kart_girisi:
                self.ekstre.pack(anchor="w", pady=(2, 0))
                self.ekstre.doldur(h.id)
            else:
                self.ekstre.pack_forget()

    def _onizleme_onay(self, cikis_id, giris_id, tutar, masraf, masraf_hid, belge_turu):
        from decimal import Decimal, InvalidOperation

        try:
            t = Decimal(str(tutar).replace(",", "."))
            m = Decimal(str(masraf or 0).replace(",", "."))
        except (InvalidOperation, ValueError):
            return True
        c_h = FinansService.hesap_getir(cikis_id)
        g_h = FinansService.hesap_getir(giris_id)
        if not c_h or not g_h:
            return True
        c_bak = FinansService.bakiye(c_h)
        g_bak = FinansService.bakiye(g_h)
        c_sonra = c_bak - t - (m if masraf_hid == cikis_id else Decimal("0"))
        g_sonra = g_bak + t - (m if masraf_hid == giris_id else Decimal("0"))
        metin = (
            f"İşlem türü: {belge_turu}\n"
            f"Gönderen: {c_h.hesap_adi}\n"
            f"  Güncel: {_para(c_bak)} → Tahmini: {_para(c_sonra)}\n"
            f"Alıcı: {g_h.hesap_adi}\n"
            f"  Güncel: {_para(g_bak)} → Tahmini: {_para(g_sonra)}\n"
            f"Transfer tutarı: {_para(t)}\n"
            f"Masraf: {_para(m) if m else '—'}\n\n"
            f"Bu program içi kayıttır; bankaya para gönderilmez.\n"
            f"Kaydedilsin mi?"
        )
        return messagebox.askyesno("Transfer özeti", metin, parent=self)

    def kaydet(self):
        if self._kaydediliyor:
            return
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            belge_turu = (self.belge_turu.get() or "").strip().upper()
            if belge_turu not in self.ISLEM_TURLERI:
                raise ValueError("İşlem türü Virman, Havale, EFT veya FAST seçin.")
            cikis_id = self._cikis_hesap_map.get(self.cikis_hesap.get())
            giris_id = self._giris_hesap_map.get(self.giris_hesap.get())
            if not cikis_id:
                raise ValueError("Gönderen hesabı seçin.")
            if not giris_id:
                raise ValueError("Alıcı hesabı seçin.")
            if cikis_id == giris_id:
                raise ValueError("Gönderen ve alıcı hesap aynı olamaz.")
            masraf_hid = self._masraf_hesap_map.get(self.masraf_hesap.get()) or cikis_id
            if not self._onizleme_onay(
                cikis_id, giris_id, self.tutar.get(), self.masraf.get(), masraf_hid, belge_turu
            ):
                return
            self._kaydediliyor = True
            self._kaydet_btn.configure(state="disabled")
            belge = FinansService.banka_hesaplari_arasi_virman(
                cikis_id,
                giris_id,
                tarih,
                self.tutar.get(),
                aciklama=self.aciklama.get().strip() or None,
                belge_turu=belge_turu,
                dekont_no=self.dekont.get().strip() or None,
                belge_no=self.belge_no,
                ekstre_id=self.ekstre.secili_ekstre_id() if self.ekstre.winfo_manager() else None,
                istek_anahtari=self.istek_anahtari,
                masraf_tutar=self.masraf.get(),
                masraf_hesap_id=masraf_hid,
            )
        except ValueError as hata:
            self._kaydediliyor = False
            try:
                self._kaydet_btn.configure(state="normal")
            except tk.TclError:
                pass
            messagebox.showerror("Fiş", str(hata), parent=self)
            return
        self.result = belge
        messagebox.showinfo(
            "Kaydedildi" if not self.belge_no else "Güncellendi",
            f"Belge no: {belge}" + (" (kart ekstre ödemesi)" if str(belge).startswith("KKE") else ""),
            parent=self,
        )
        self.destroy()


def kredi_karti_odeme_sayfasi_goster(app):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="KREDİ KARTI İLE ÖDEME", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Banka İşlemleri", command=lambda: banka_islemleri_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(
        app.icerik,
        text="Cariye kredi kartı ile ödeme (tek çekim veya taksitli, max 24).",
    ).pack(anchor="w", pady=(10, 6))

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=(4, 8))

    def _yeni():
        dialog = BankaIslemKkOdemeDialog(app)
        app.wait_window(dialog)
        if dialog.result:
            kredi_karti_odeme_sayfasi_goster(app)

    def _guncelle():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Güncelle", "Lütfen güncellenecek fişi seçin.", parent=app)
            return
        dialog = BankaIslemKkOdemeDialog(app, belge_no=secim[0])
        app.wait_window(dialog)
        if dialog.result:
            kredi_karti_odeme_sayfasi_goster(app)

    ttk.Button(butonlar, text="Yeni Fiş", command=_yeni).pack(side="left")
    ttk.Button(butonlar, text="Güncelle", command=_guncelle).pack(side="left", padx=8)
    ttk.Button(
        butonlar,
        text="Yenile",
        command=lambda: kredi_karti_odeme_sayfasi_goster(app),
    ).pack(side="left", padx=8)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    tablo = ttk.Treeview(
        cerceve,
        columns=("tarih", "belge", "cari", "banka", "kart", "cekim", "tutar", "muhasebe", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("tarih", "Tarih", 85),
        ("belge", "Belge No", 110),
        ("cari", "Cari", 180),
        ("banka", "Banka", 120),
        ("kart", "Kart", 130),
        ("cekim", "Çekim", 100),
        ("tutar", "Tutar", 100),
        ("muhasebe", "Muhasebe", 130),
        ("aciklama", "Açıklama", 180),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    tablo.bind("<Double-1>", lambda _e: _guncelle())

    kayitlar = FinansService.kredi_karti_odemeleri()
    muhasebe = _muhasebe_durumlari("kart_odeme", kayitlar)
    for kayit in kayitlar:
        cekim = kayit["cekim_turu"]
        if kayit["taksit_sayisi"] > 1:
            cekim = f"{cekim} ({kayit['taksit_sayisi']})"
        tablo.insert(
            "",
            "end",
            iid=kayit["belge_no"],
            values=(
                _tarih(kayit["tarih"]),
                kayit["belge_no"],
                kayit["cari"],
                kayit["banka"],
                kayit["kart"],
                cekim,
                _para(kayit["tutar"]),
                muhasebe.get(kayit["belge_no"], ""),
                kayit["aciklama"],
            ),
        )


class BankaIslemKkOdemeDialog(tk.Toplevel):
    """Banka işlemleri — kredi kartı ile ödeme fişi."""

    def __init__(self, parent, belge_no=None):
        super().__init__(parent)
        self.result = None
        self.belge_no = belge_no
        self._mevcut = None
        if belge_no:
            try:
                self._mevcut = FinansService.kredi_karti_odeme_getir(belge_no)
            except ValueError as hata:
                messagebox.showerror("Fiş", str(hata), parent=parent)
                self.destroy()
                return
            if (self._mevcut.get("kaynak_turu") or "CARI") != "CARI":
                messagebox.showinfo(
                    "Fiş",
                    f"{belge_no} kartla gider ödemesine aittir; buradan değiştirilemez. "
                    "Giderler → Gider Fişi → 'Kartla Gider Ödemeleri' ekranından iptal veya banka iadesi kaydedin.",
                    parent=parent,
                )
                self.destroy()
                return

        self.title(
            "Kredi Kartı ile Ödeme — Güncelle" if belge_no else "Kredi Kartı ile Ödeme"
        )
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        from database.cari_service import CariService

        self._cari_map = {}
        self._banka_map = {}
        self._kart_map = {}
        self._cekim_map = {e: k for k, e in KK_CEKIM_TURLERI}

        row = 0
        ttk.Label(self, text="Tarih *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)
        self.tarih.bind("<FocusOut>", lambda _e: self._vade_ve_plan_guncelle())
        self.tarih.bind("<KeyRelease>", lambda _e: self._vade_ve_plan_guncelle())

        row = 1
        cariler = CariService.listele(hizli=True)
        self._cari_map = {
            f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in cariler
        }
        ttk.Label(self, text="Cari hesap *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.cari = ttk.Combobox(self, values=list(self._cari_map), width=42)
        self.cari.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        if self._cari_map:
            self.cari.set(next(iter(self._cari_map)))

        row = 2
        kartlar_banka = FinansService.banka_kartlari(aktif_only=True)
        ttk.Label(self, text="Kredi kartı bankası *").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.banka = ttk.Combobox(self, state="readonly", width=42)
        self.banka.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        banka_etiketleri = []
        for k in kartlar_banka:
            etiket = k.banka_adi
            if k.sube:
                etiket = f"{etiket} / {k.sube}"
            self._banka_map[etiket] = k.id
            banka_etiketleri.append(etiket)
        self.banka.configure(values=banka_etiketleri)
        if banka_etiketleri:
            self.banka.set(banka_etiketleri[0])
        self.banka.bind("<<ComboboxSelected>>", lambda _e: self._kartlari_doldur())

        row = 3
        ttk.Label(self, text="Kredi kartı *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.kart = ttk.Combobox(self, state="readonly", width=42)
        self.kart.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self.kart.bind("<<ComboboxSelected>>", lambda _e: self._limit_bilgi())

        row = 4
        self.limit_lbl = ttk.Label(self, text="", foreground="#555")
        self.limit_lbl.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 5
        ttk.Label(self, text="Çekim türü *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.cekim = ttk.Combobox(
            self,
            values=[e for _k, e in KK_CEKIM_TURLERI],
            state="readonly",
            width=28,
        )
        self.cekim.set("Tek Çekim")
        self.cekim.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.cekim.bind("<<ComboboxSelected>>", lambda _e: self._cekim_degisti())

        row = 6
        ttk.Label(self, text="Taksit sayısı").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.taksit = ttk.Combobox(
            self,
            values=[str(i) for i in range(1, KK_MAX_TAKSIT + 1)],
            width=8,
            state="disabled",
        )
        self.taksit.set("1")
        self.taksit.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.taksit.bind("<<ComboboxSelected>>", lambda _e: self._vade_ve_plan_guncelle())

        row = 7
        ttk.Label(self, text="Vade (1. taksit)").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.vade = ttk.Entry(self, width=14, state="readonly")
        self.vade.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 8
        ttk.Label(self, text="Meblağ *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tutar.bind("<KeyRelease>", lambda _e: self._vade_ve_plan_guncelle())

        row = 9
        ttk.Label(self, text="Referans / onay no").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.referans = ttk.Entry(self, width=24)
        self.referans.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 10
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=44)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        row = 11
        plan_f = ttk.LabelFrame(self, text="Taksit planı önizleme", padding=8)
        plan_f.grid(row=row, column=0, columnspan=3, padx=12, pady=8, sticky="ew")
        self.plan_tablo = ttk.Treeview(
            plan_f,
            columns=("no", "vade", "tutar"),
            show="headings",
            height=6,
        )
        for k, b, w in (("no", "No", 50), ("vade", "Vade", 100), ("tutar", "Tutar", 100)):
            self.plan_tablo.heading(k, text=b)
            self.plan_tablo.column(k, width=w, anchor="w")
        self.plan_tablo.pack(fill="x")

        if self.belge_no:
            ttk.Label(self, text=f"Belge: {self.belge_no}", foreground="#555").grid(
                row=12, column=0, columnspan=2, padx=12, sticky="w"
            )

        butonlar = ttk.Frame(self)
        butonlar.grid(row=13, column=0, columnspan=3, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            butonlar,
            text="Güncelle" if self.belge_no else "Kaydet",
            command=self.kaydet,
        ).pack(side="right")

        self._kartlari_doldur()
        self._mevcutu_yukle()
        self._vade_ve_plan_guncelle()

    def _kartlari_doldur(self):
        self._kart_map = {}
        self.kart.set("")
        self.limit_lbl.configure(text="")
        banka_id = self._banka_map.get(self.banka.get())
        if not banka_id:
            self.kart.configure(values=[])
            return
        kartlar = FinansService.kredi_kartlari(banka_karti_id=banka_id)
        etiketler = []
        for kk in kartlar:
            etiket = kk.kart_adi
            if kk.son_dort_hane:
                etiket = f"{etiket} (****{kk.son_dort_hane})"
            self._kart_map[etiket] = kk.id
            etiketler.append(etiket)
        self.kart.configure(values=etiketler)
        if etiketler:
            self.kart.set(etiketler[0])
            self._limit_bilgi()
        else:
            self.limit_lbl.configure(
                text="Bu bankada tanımlı kredi kartı yok. Bankalar menüsünden kart ekleyin."
            )

    def _cekim_degisti(self):
        tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
        if tur == "TEK_CEKIM":
            self.taksit.set("1")
            self.taksit.configure(state="disabled")
        else:
            self.taksit.configure(state="readonly")
            if self.taksit.get() == "1":
                self.taksit.set("2")
        self._vade_ve_plan_guncelle()

    def _limit_bilgi(self):
        kid = self._kart_map.get(self.kart.get())
        if not kid:
            self.limit_lbl.configure(text="")
            return
        kk = FinansService.kredi_karti_getir(kid)
        if not kk:
            return
        self.limit_lbl.configure(text=_kart_limit_metni(kk))

    def _vade_yaz(self, metin):
        self.vade.configure(state="normal")
        self.vade.delete(0, "end")
        self.vade.insert(0, metin)
        self.vade.configure(state="readonly")

    def _vade_ve_plan_guncelle(self):
        for item in self.plan_tablo.get_children():
            self.plan_tablo.delete(item)
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
        except ValueError:
            self._vade_yaz("")
            return
        self._vade_yaz(tarih.strftime("%d.%m.%Y"))
        tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
        try:
            n = 1 if tur == "TEK_CEKIM" else int(self.taksit.get() or "1")
        except ValueError:
            return
        try:
            tutar = Decimal(str(self.tutar.get() or "0").replace(",", "."))
        except Exception:
            tutar = Decimal("0")
        if tutar <= 0:
            return
        try:
            plan = FinansService.kk_taksit_plani(tarih, n, tutar)
        except ValueError:
            return
        for satir in plan:
            self.plan_tablo.insert(
                "",
                "end",
                values=(
                    satir["taksit_no"],
                    _tarih(satir["vade_tarihi"]),
                    _para(satir["tutar"]),
                ),
            )

    def _mevcutu_yukle(self):
        m = self._mevcut
        if not m:
            return
        self.tarih.delete(0, "end")
        self.tarih.insert(0, m["tarih"].strftime("%d.%m.%Y"))
        self.tutar.delete(0, "end")
        self.tutar.insert(0, str(m["tutar"]))
        if m.get("referans_no"):
            self.referans.insert(0, m["referans_no"])
        if m.get("aciklama"):
            self.aciklama.insert(0, m["aciklama"])
        if m.get("cari_etiket") and m["cari_etiket"] in self._cari_map:
            self.cari.set(m["cari_etiket"])
        else:
            _combobox_id_sec(self.cari, self._cari_map, m.get("cari_id"))
        _combobox_id_sec(self.banka, self._banka_map, m.get("banka_karti_id"))
        self._kartlari_doldur()
        _combobox_id_sec(self.kart, self._kart_map, m.get("kredi_karti_id"))
        self._limit_bilgi()
        tur = m.get("cekim_turu") or "TEK_CEKIM"
        etiket = dict(KK_CEKIM_TURLERI).get(tur, "Tek Çekim")
        self.cekim.set(etiket)
        self._cekim_degisti()
        if tur == "TAKSITLI":
            self.taksit.set(str(m.get("taksit_sayisi") or 2))

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            cari_id = self._cari_map.get(self.cari.get().strip()) if self.cari.get() else None
            if cari_id is None:
                raise ValueError("Cari hesap seçin.")
            banka_id = self._banka_map.get(self.banka.get())
            if not banka_id:
                raise ValueError("Kredi kartı bankasını seçin.")
            kart_id = self._kart_map.get(self.kart.get())
            if not kart_id:
                raise ValueError("Kredi kartı seçin.")
            tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
            sonuc = FinansService.kredi_karti_odeme(
                banka_id,
                kart_id,
                cari_id,
                tarih,
                self.tutar.get(),
                cekim_turu=tur,
                taksit_sayisi=self.taksit.get(),
                referans_no=self.referans.get().strip() or None,
                aciklama=self.aciklama.get().strip() or None,
                belge_no=self.belge_no,
            )
        except ValueError as hata:
            messagebox.showerror("Fiş", str(hata), parent=self)
            return
        self.result = sonuc.get("belge_no")
        messagebox.showinfo(
            "Kaydedildi" if not self.belge_no else "Güncellendi",
            f"Belge no: {self.result}",
            parent=self,
        )
        if not self.belge_no:
            _soz_bagla(self, cari_id, "VERILEN", "Kredi Kartı ile Ödeme", self.result)
        self.destroy()


def kredi_karti_pos_tahsilat_sayfasi_goster(app):
    """Geriye uyumluluk — POS İşlemleri ekranına yönlendirir."""
    from pos_islemleri_ui import pos_islemleri_sayfasi_goster

    pos_islemleri_sayfasi_goster(
        app, geri_fn=lambda: banka_islemleri_menusu_goster(app)
    )


class BankaIslemPosTahsilatDialog(tk.Toplevel):
    """Banka işlemleri — kredi kartı POS tahsilat fişi (tek / taksit max 12).

    Komisyon/valör karttan gelir; elle override işlemle saklanır ve ilgisiz alan
    değişince sessizce varsayılana dönmez.
    """

    def __init__(self, parent, belge_no=None):
        super().__init__(parent)
        self.result = None
        self.belge_no = belge_no
        self._mevcut = None
        self._oranlar = {n: Decimal("0") for n in range(1, POS_MAX_TAKSIT + 1)}
        self._kart_valor_gun = 1
        self._oran_elle = False
        self._tutar_elle = False
        self._kesinti_elle = False
        self._valor_gun_elle = False
        self._valor_tarih_elle = False
        self._salt_okunur = False
        self._bagli_aktarim = False
        self._yukle_modu = False
        if belge_no:
            try:
                self._mevcut = FinansService.pos_tahsilat_getir(belge_no)
                durum = (self._mevcut.get("durum_kod") or self._mevcut.get("durum") or "").upper()
                if durum in ("KISMEN", "AKTARILDI") or Decimal(
                    str(self._mevcut.get("gercek_yatis_tutari") or 0)
                ) > 0:
                    self._bagli_aktarim = True
            except ValueError as hata:
                messagebox.showerror("Fiş", str(hata), parent=parent)
                self.destroy()
                return

        self.title(
            "POS Tahsilat — Güncelle (aktarılmış)" if self._bagli_aktarim
            else ("POS Tahsilat — Güncelle" if belge_no else "Kredi Kartı POS Cihazıyla Tahsilat")
        )
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        from database.cari_service import CariService

        self._cari_map = {}
        self._banka_map = {}
        self._hedef_map = {}
        self._cekim_map = {e: k for k, e in KK_CEKIM_TURLERI}

        row = 0
        ttk.Label(self, text="Tarih *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)
        self.tarih.bind("<FocusOut>", lambda _e: self._tarih_degisti())

        row = 1
        cariler = CariService.listele(hizli=True)
        self._cari_map = {
            f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in cariler
        }
        ttk.Label(self, text="Cari hesap *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.cari = ttk.Combobox(self, values=list(self._cari_map), width=42)
        self.cari.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        if self._cari_map:
            self.cari.set(next(iter(self._cari_map)))

        row = 2
        kartlar_banka = FinansService.banka_kartlari(aktif_only=True)
        ttk.Label(self, text="POS bankası *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.banka = ttk.Combobox(self, state="readonly", width=42)
        self.banka.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        banka_etiketleri = []
        for k in kartlar_banka:
            etiket = k.banka_adi
            if k.sube:
                etiket = f"{etiket} / {k.sube}"
            self._banka_map[etiket] = k.id
            banka_etiketleri.append(etiket)
        self.banka.configure(values=banka_etiketleri)
        if banka_etiketleri:
            self.banka.set(banka_etiketleri[0])
        self.banka.bind("<<ComboboxSelected>>", lambda _e: self._banka_degisti())

        row = 3
        self.pos_bilgi = ttk.Label(self, text="", foreground="#555")
        self.pos_bilgi.grid(row=row, column=1, columnspan=2, padx=12, sticky="w")

        row = 4
        ttk.Label(self, text="Hedef banka hesabı").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.hedef = ttk.Combobox(self, state="readonly", width=42)
        self.hedef.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        row = 5
        ttk.Label(self, text="Çekim türü *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.cekim = ttk.Combobox(
            self,
            values=[e for _k, e in KK_CEKIM_TURLERI],
            state="readonly",
            width=28,
        )
        self.cekim.set("Tek Çekim")
        self.cekim.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.cekim.bind("<<ComboboxSelected>>", lambda _e: self._cekim_degisti())

        row = 6
        ttk.Label(self, text="Taksit sayısı").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.taksit = ttk.Combobox(
            self,
            values=[str(i) for i in range(1, POS_MAX_TAKSIT + 1)],
            width=8,
            state="disabled",
        )
        self.taksit.set("1")
        self.taksit.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.taksit.bind("<<ComboboxSelected>>", lambda _e: self._taksit_degisti())

        row = 7
        ttk.Label(self, text="Meblağ (brüt) *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tutar.bind("<KeyRelease>", lambda _e: self._ozet_guncelle())

        row = 8
        kom_f = ttk.LabelFrame(self, text="Komisyon / valör (karttan; elle düzeltilebilir)", padding=8)
        kom_f.grid(row=row, column=0, columnspan=3, padx=12, pady=6, sticky="ew")
        ttk.Label(kom_f, text="Komisyon %").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.oran_e = ttk.Entry(kom_f, width=10)
        self.oran_e.grid(row=0, column=1, sticky="w", padx=4, pady=2)
        self.oran_e.bind("<KeyRelease>", lambda _e: self._oran_elle_yazildi())
        ttk.Label(kom_f, text="Komisyon tutarı").grid(row=0, column=2, sticky="w", padx=4, pady=2)
        self.komisyon_e = ttk.Entry(kom_f, width=12)
        self.komisyon_e.grid(row=0, column=3, sticky="w", padx=4, pady=2)
        self.komisyon_e.bind("<KeyRelease>", lambda _e: self._tutar_elle_yazildi())
        ttk.Label(kom_f, text="Diğer kesinti").grid(row=1, column=0, sticky="w", padx=4, pady=2)
        self.kesinti_e = ttk.Entry(kom_f, width=10)
        self.kesinti_e.grid(row=1, column=1, sticky="w", padx=4, pady=2)
        self.kesinti_e.insert(0, "0")
        self.kesinti_e.bind("<KeyRelease>", lambda _e: self._kesinti_elle_yazildi())
        ttk.Label(kom_f, text="Valör gün").grid(row=1, column=2, sticky="w", padx=4, pady=2)
        self.valor_gun_e = ttk.Entry(kom_f, width=8)
        self.valor_gun_e.grid(row=1, column=3, sticky="w", padx=4, pady=2)
        self.valor_gun_e.bind("<KeyRelease>", lambda _e: self._valor_gun_elle_yazildi())
        ttk.Label(kom_f, text="Beklenen geçiş").grid(row=2, column=0, sticky="w", padx=4, pady=2)
        valor_c = ttk.Frame(kom_f)
        valor_c.grid(row=2, column=1, columnspan=2, sticky="w", padx=4, pady=2)
        self.valor_tarih_e = ttk.Entry(valor_c, width=12)
        self.valor_tarih_e.pack(side="left")
        takvim_butonu(valor_c, self.valor_tarih_e)
        self.valor_tarih_e.bind("<KeyRelease>", lambda _e: self._valor_tarih_elle_yazildi())
        self.valor_tarih_e.bind("<FocusOut>", lambda _e: self._valor_tarih_elle_yazildi())
        ttk.Button(kom_f, text="Karttan yenile", command=self._karttan_yenile).grid(
            row=2, column=3, sticky="w", padx=4
        )
        self.net_lbl = ttk.Label(kom_f, text="Net: —")
        self.net_lbl.grid(row=3, column=0, columnspan=4, sticky="w", padx=4, pady=(6, 0))

        row = 9
        ttk.Label(self, text="Referans / onay no").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.referans = ttk.Entry(self, width=24)
        self.referans.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 10
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=44)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        row = 11
        if self.belge_no:
            durum_metin = (self._mevcut or {}).get("durum") or ""
            ek = (self._mevcut or {}).get("ek_isaret") or ""
            if ek:
                durum_metin = f"{durum_metin} · {ek}"
            ttk.Label(
                self,
                text=f"Belge: {self.belge_no}  ·  {durum_metin}",
                foreground="#555",
            ).grid(row=row, column=0, columnspan=3, padx=12, sticky="w")
            if self._bagli_aktarim:
                ttk.Label(
                    self,
                    text="Aktarılmış fiş: kayıtlar yerinde güncellenir; ikinci tahsilat/aktarım üretilmez. "
                    "Net, aktarılan tutarın altına inemez.",
                    foreground="#9A3412",
                ).grid(row=row + 1, column=0, columnspan=3, padx=12, sticky="w")
                row += 1

        butonlar = ttk.Frame(self)
        butonlar.grid(row=row + 1, column=0, columnspan=3, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(
            butonlar,
            text="Güncelle" if self.belge_no else "Kaydet",
            command=self.kaydet,
        ).pack(side="right")
        if self.belge_no:
            ttk.Button(butonlar, text="Değişiklik geçmişi", command=self._gecmis_goster).pack(
                side="right", padx=(0, 8)
            )
        if (self._mevcut or {}).get("aktarim_belge_no"):
            ttk.Button(
                butonlar,
                text="Banka fişini aç",
                command=self._banka_fisi_ac,
            ).pack(side="right", padx=(0, 8))

        self._banka_degisti()
        self._mevcutu_yukle()
        self._ozet_guncelle()

    def _banka_fisi_ac(self):
        belge = ((self._mevcut or {}).get("aktarim_belge_no") or "").split(",")[-1].strip()
        if not belge:
            messagebox.showinfo("Banka fişi", "Bağlı aktarım belgesi yok.", parent=self)
            return
        from belge_onizleme_ui import finans_belge_ac

        if not finans_belge_ac(self, "POS VALÖR AKTARIM", belge):
            PosAktarimBelgeDialog(self, belge)

    def _gecmis_goster(self):
        if not self.belge_no:
            return
        kayitlar = FinansService.pos_degisiklik_gecmisi(self.belge_no)
        win = tk.Toplevel(self)
        win.title(f"Değişiklik geçmişi — {self.belge_no}")
        win.transient(self)
        tablo = ttk.Treeview(
            win, columns=("zaman", "kullanici", "alan", "eski", "yeni"), show="headings", height=12
        )
        for k, b, w in (
            ("zaman", "Tarih", 130),
            ("kullanici", "Kullanıcı", 120),
            ("alan", "Alan", 110),
            ("eski", "Eski", 120),
            ("yeni", "Yeni", 120),
        ):
            tablo.heading(k, text=b)
            tablo.column(k, width=w)
        tablo.pack(fill="both", expand=True, padx=8, pady=8)
        for k in kayitlar:
            zm = k["zaman"]
            zm_s = zm.strftime("%d.%m.%Y %H:%M") if hasattr(zm, "strftime") else str(zm or "")
            tablo.insert(
                "",
                "end",
                values=(zm_s, k.get("kullanici") or "—", k.get("alan"), k.get("eski") or "", k.get("yeni") or ""),
            )
        if not kayitlar:
            ttk.Label(win, text="Kayıtlı değişiklik yok.").pack(pady=4)
        ttk.Button(win, text="Kapat", command=win.destroy).pack(pady=6)

    def _taksit_sayisi(self) -> int:
        tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
        if tur == "TEK_CEKIM":
            return 1
        try:
            return int(self.taksit.get() or "1")
        except ValueError:
            return 1

    def _brut(self) -> Decimal:
        try:
            brut = Decimal(str(self.tutar.get() or "0").replace(",", "."))
        except Exception:
            brut = Decimal("0")
        return brut if brut > 0 else Decimal("0")

    def _hedefleri_doldur(self, kart, onerilen_id=None):
        self._hedef_map.clear()
        etiketler = []
        if kart:
            for h in kart.alt_hesaplar or []:
                tur = (h.alt_hesap_turu or "").upper()
                if tur in ("MEVDUAT", "KMH"):
                    et = f"{h.hesap_adi} ({tur})"
                    self._hedef_map[et] = int(h.id)
                    etiketler.append(et)
        self.hedef.configure(values=etiketler)
        if onerilen_id:
            for et, hid in self._hedef_map.items():
                if hid == int(onerilen_id):
                    self.hedef.set(et)
                    return
        if etiketler:
            self.hedef.set(etiketler[0])

    def _kart_varsayilanlarini_uygula(self, *, zorla=False):
        """Kart/taksit varsayılanlarını yazar; elle işaretli alanlara dokunmaz (zorla hariç)."""
        n = self._taksit_sayisi()
        oran = Decimal(str(self._oranlar.get(n, 0) or 0))
        brut = self._brut()
        if zorla or not self._oran_elle:
            self.oran_e.delete(0, "end")
            self.oran_e.insert(0, f"{oran:g}")
            self._oran_elle = False
        if zorla or not self._tutar_elle:
            try:
                o = Decimal(str(self.oran_e.get() or "0").replace(",", "."))
            except Exception:
                o = oran
            kom = (brut * o / Decimal("100")).quantize(Decimal("0.01"))
            self.komisyon_e.delete(0, "end")
            self.komisyon_e.insert(0, str(kom))
            self._tutar_elle = False
        if zorla or not self._kesinti_elle:
            self.kesinti_e.delete(0, "end")
            self.kesinti_e.insert(0, "0")
            self._kesinti_elle = False
        if zorla or not self._valor_gun_elle:
            self.valor_gun_e.delete(0, "end")
            self.valor_gun_e.insert(0, str(self._kart_valor_gun))
            self._valor_gun_elle = False
        if zorla or not self._valor_tarih_elle:
            self._valor_tarih_hesapla_yaz()
            self._valor_tarih_elle = False

    def _valor_tarih_hesapla_yaz(self):
        from database.finans_service import valor_tarihi_hesapla

        try:
            islem = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
        except ValueError:
            return
        try:
            gun = int(str(self.valor_gun_e.get() or "0").strip())
        except ValueError:
            gun = self._kart_valor_gun
        banka_id = self._banka_map.get(self.banka.get())
        is_gunu = True
        if banka_id:
            kart = FinansService.banka_karti_getir(banka_id)
            if kart is not None and getattr(kart, "pos_valor_is_gunu", None) is not None:
                is_gunu = bool(kart.pos_valor_is_gunu)
        vt = valor_tarihi_hesapla(islem, gun, is_gunu=is_gunu)
        self.valor_tarih_e.delete(0, "end")
        self.valor_tarih_e.insert(0, vt.strftime("%d.%m.%Y"))

    def _karttan_yenile(self):
        self._oran_elle = self._tutar_elle = self._kesinti_elle = False
        self._valor_gun_elle = self._valor_tarih_elle = False
        self._kart_varsayilanlarini_uygula(zorla=True)
        self._ozet_guncelle()

    def _oran_elle_yazildi(self):
        if self._yukle_modu:
            return
        self._oran_elle = True
        self._tutar_elle = False  # oran değişince tutar yeniden hesaplanır
        brut = self._brut()
        try:
            oran = Decimal(str(self.oran_e.get() or "0").replace(",", "."))
        except Exception:
            return
        kom = (brut * oran / Decimal("100")).quantize(Decimal("0.01"))
        self.komisyon_e.delete(0, "end")
        self.komisyon_e.insert(0, str(kom))
        self._ozet_guncelle()

    def _tutar_elle_yazildi(self):
        if self._yukle_modu:
            return
        self._tutar_elle = True
        brut = self._brut()
        try:
            kom = Decimal(str(self.komisyon_e.get() or "0").replace(",", "."))
        except Exception:
            return
        if brut > 0:
            oran = (kom * Decimal("100") / brut).quantize(Decimal("0.0001"))
            self.oran_e.delete(0, "end")
            self.oran_e.insert(0, f"{oran:g}")
            self._oran_elle = True
        self._ozet_guncelle()

    def _kesinti_elle_yazildi(self):
        if self._yukle_modu:
            return
        self._kesinti_elle = True
        self._ozet_guncelle()

    def _valor_gun_elle_yazildi(self):
        if self._yukle_modu:
            return
        self._valor_gun_elle = True
        if not self._valor_tarih_elle:
            self._valor_tarih_hesapla_yaz()
        self._ozet_guncelle()

    def _valor_tarih_elle_yazildi(self):
        if self._yukle_modu:
            return
        if (self.valor_tarih_e.get() or "").strip():
            self._valor_tarih_elle = True

    def _tarih_degisti(self):
        if self._yukle_modu or self._valor_tarih_elle:
            return
        self._valor_tarih_hesapla_yaz()

    def _banka_degisti(self):
        banka_id = self._banka_map.get(self.banka.get())
        self._oranlar = {n: Decimal("0") for n in range(1, POS_MAX_TAKSIT + 1)}
        self._kart_valor_gun = 1
        if not banka_id:
            self.pos_bilgi.configure(text="")
            self._hedefleri_doldur(None)
            self._ozet_guncelle()
            return
        kart = FinansService.banka_karti_getir(banka_id)
        if not kart:
            self.pos_bilgi.configure(text="")
            self._hedefleri_doldur(None)
            self._ozet_guncelle()
            return
        self._oranlar = FinansService.pos_taksit_komisyonlari(banka_id)
        self._kart_valor_gun = int(getattr(kart, "pos_valor_gun", 1) or 1)
        onerilen = None
        if self._mevcut and not self._yukle_modu:
            onerilen = self._mevcut.get("hedef_hesap_id")
        hedef = FinansService._pos_hedef_hesap(kart)
        self._hedefleri_doldur(kart, onerilen_id=onerilen or (hedef.id if hedef else None))
        self.pos_bilgi.configure(
            text=(
                f"POS hesabı · {FinansService.pos_valor_ozet_metni(kart)} · "
                f"1. taksit komisyon %{self._oranlar.get(1, 0):g}"
            )
        )
        if not self._yukle_modu:
            # Banka değişince kart varsayılanı; elle işaretler sıfırlanır
            self._oran_elle = self._tutar_elle = self._kesinti_elle = False
            self._valor_gun_elle = self._valor_tarih_elle = False
            self._kart_varsayilanlarini_uygula(zorla=True)
        self._ozet_guncelle()

    def _cekim_degisti(self):
        tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
        if tur == "TEK_CEKIM":
            self.taksit.set("1")
            self.taksit.configure(state="disabled")
        else:
            self.taksit.configure(state="readonly")
            if self.taksit.get() == "1":
                self.taksit.set("2")
        self._taksit_degisti()

    def _taksit_degisti(self):
        if self._yukle_modu:
            self._ozet_guncelle()
            return
        # Taksit değişince oran karttan; tutar override sıfırlanır
        self._oran_elle = False
        self._tutar_elle = False
        self._kart_varsayilanlarini_uygula(zorla=False)
        self._ozet_guncelle()

    def _ozet_guncelle(self):
        if not hasattr(self, "net_lbl"):
            return
        brut = self._brut()
        # Oran değiştiyse tutarı güncelle (tutar elle değilse)
        if self._oran_elle and not self._tutar_elle and not self._yukle_modu:
            try:
                oran = Decimal(str(self.oran_e.get() or "0").replace(",", "."))
                kom = (brut * oran / Decimal("100")).quantize(Decimal("0.01"))
                cur = self.komisyon_e.get()
                if cur != str(kom):
                    self.komisyon_e.delete(0, "end")
                    self.komisyon_e.insert(0, str(kom))
            except Exception:
                pass
        elif not self._oran_elle and not self._tutar_elle and not self._yukle_modu:
            n = self._taksit_sayisi()
            oran = Decimal(str(self._oranlar.get(n, 0) or 0))
            kom = (brut * oran / Decimal("100")).quantize(Decimal("0.01"))
            self.oran_e.delete(0, "end")
            self.oran_e.insert(0, f"{oran:g}")
            self.komisyon_e.delete(0, "end")
            self.komisyon_e.insert(0, str(kom))
        try:
            komisyon = Decimal(str(self.komisyon_e.get() or "0").replace(",", "."))
        except Exception:
            komisyon = Decimal("0")
        try:
            kesinti = Decimal(str(self.kesinti_e.get() or "0").replace(",", "."))
        except Exception:
            kesinti = Decimal("0")
        net = brut - komisyon - kesinti
        try:
            oran_g = Decimal(str(self.oran_e.get() or "0").replace(",", "."))
        except Exception:
            oran_g = Decimal("0")
        self.net_lbl.configure(
            text=f"Efektif oran %{oran_g:g} · Komisyon {_para(komisyon)} · "
            f"Kesinti {_para(kesinti)} · Beklenen net {_para(net)}"
        )

    def _mevcutu_yukle(self):
        m = self._mevcut
        if not m:
            return
        self._yukle_modu = True
        try:
            self.tarih.delete(0, "end")
            self.tarih.insert(0, m["tarih"].strftime("%d.%m.%Y"))
            self.tutar.delete(0, "end")
            self.tutar.insert(0, str(m["tutar"]))
            if m.get("aciklama"):
                self.aciklama.delete(0, "end")
                self.aciklama.insert(0, m["aciklama"])
            if m.get("referans_no"):
                self.referans.delete(0, "end")
                self.referans.insert(0, m["referans_no"])
            if m.get("cari_etiket") and m["cari_etiket"] in self._cari_map:
                self.cari.set(m["cari_etiket"])
            else:
                _combobox_id_sec(self.cari, self._cari_map, m.get("cari_id"))
            _combobox_id_sec(self.banka, self._banka_map, m.get("banka_karti_id"))
            self._banka_degisti()
            n = int(m.get("taksit_sayisi") or 1)
            if n <= 1:
                self.cekim.set(dict(KK_CEKIM_TURLERI).get("TEK_CEKIM", "Tek Çekim"))
                self._cekim_degisti()
            else:
                self.cekim.set(dict(KK_CEKIM_TURLERI).get("TAKSITLI", "Taksitli Çekim"))
                self._cekim_degisti()
                self.taksit.set(str(n))
            # Kayıtlı override değerleri
            self.oran_e.delete(0, "end")
            self.oran_e.insert(0, f"{Decimal(str(m.get('komisyon_orani') or 0)):g}")
            self.komisyon_e.delete(0, "end")
            self.komisyon_e.insert(0, str(m.get("komisyon_tutari") or 0))
            self.kesinti_e.delete(0, "end")
            self.kesinti_e.insert(0, str(m.get("diger_kesinti") or 0))
            vg = m.get("valor_gun")
            self.valor_gun_e.delete(0, "end")
            self.valor_gun_e.insert(0, str(vg if vg is not None else self._kart_valor_gun))
            if m.get("valor_tarihi"):
                self.valor_tarih_e.delete(0, "end")
                self.valor_tarih_e.insert(0, m["valor_tarihi"].strftime("%d.%m.%Y"))
            self._oran_elle = True
            self._tutar_elle = True
            self._kesinti_elle = Decimal(str(m.get("diger_kesinti") or 0)) != 0
            self._valor_gun_elle = True
            self._valor_tarih_elle = True
            if m.get("hedef_hesap_id"):
                for et, hid in self._hedef_map.items():
                    if hid == int(m["hedef_hesap_id"]):
                        self.hedef.set(et)
                        break
        finally:
            self._yukle_modu = False

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            cari_id = self._cari_map.get(self.cari.get().strip()) if self.cari.get() else None
            if cari_id is None:
                raise ValueError("Cari hesap seçin.")
            banka_id = self._banka_map.get(self.banka.get())
            if not banka_id:
                raise ValueError("POS bankasını seçin.")
            n = self._taksit_sayisi()
            valor_t = None
            if self._valor_tarih_elle and (self.valor_tarih_e.get() or "").strip():
                valor_t = datetime.strptime(self.valor_tarih_e.get().strip(), "%d.%m.%Y").date()
            hedef_id = self._hedef_map.get(self.hedef.get())
            kw = {
                "kart_tipi": "KREDI_KARTI",
                "cari_id": cari_id,
                "aciklama": self.aciklama.get().strip() or None,
                "taksit_sayisi": n,
                "referans_no": self.referans.get().strip() or None,
                "belge_no": self.belge_no,
                "hedef_hesap_id": hedef_id,
                "diger_kesinti": self.kesinti_e.get() if self._kesinti_elle else None,
                "valor_gun": self.valor_gun_e.get() if (self._valor_gun_elle or self._valor_tarih_elle) else None,
                "valor_tarihi": valor_t,
            }
            if self._tutar_elle:
                kw["komisyon_tutari"] = self.komisyon_e.get()
            elif self._oran_elle:
                kw["komisyon_orani"] = self.oran_e.get()
            # Mevcut kayıtta override'lar zaten işaretli — her zaman gönder
            if self.belge_no:
                kw["komisyon_tutari"] = self.komisyon_e.get()
                kw["diger_kesinti"] = self.kesinti_e.get()
                kw["valor_gun"] = self.valor_gun_e.get()
                if (self.valor_tarih_e.get() or "").strip():
                    kw["valor_tarihi"] = datetime.strptime(
                        self.valor_tarih_e.get().strip(), "%d.%m.%Y"
                    ).date()
            sonuc = FinansService.pos_tahsilat(
                banka_id,
                tarih,
                self.tutar.get(),
                **kw,
            )
        except ValueError as hata:
            messagebox.showerror("Fiş", str(hata), parent=self)
            return
        self.result = sonuc.get("belge_no")
        messagebox.showinfo(
            "Kaydedildi" if not self.belge_no else "Güncellendi",
            f"Belge: {self.result}\n"
            f"Brüt: {_para(sonuc['brut'])} · Komisyon %{sonuc['komisyon_orani']:g}: "
            f"{_para(sonuc['komisyon'])} · Kesinti {_para(sonuc.get('diger_kesinti'))} · "
            f"Net: {_para(sonuc['net'])}\n"
            f"Valör: {sonuc['valor_tarihi'].strftime('%d.%m.%Y')} → {sonuc.get('hedef_hesap_adi') or 'hedef'}",
            parent=self,
        )
        if not self.belge_no:
            _soz_bagla(self, cari_id, "ALINAN", "POS Tahsilatı", self.result)
        self.destroy()


class PosAktarimBelgeDialog(tk.Toplevel):
    """PVA — POS banka aktarım fişi (bağlı hareketler + ekstre teyidi)."""

    def __init__(self, parent, belge_no: str, *, on_ok=None):
        super().__init__(parent)
        self.title(f"POS Banka Aktarım — {belge_no}")
        self.transient(parent)
        self.grab_set()
        self._belge_no = belge_no
        self._on_ok = on_ok
        self._pos_ids: list[int] = []
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)
        try:
            detay = FinansService.pos_aktarim_belge_getir(belge_no)
        except ValueError as hata:
            messagebox.showerror("Banka fişi", str(hata), parent=parent)
            self.destroy()
            return
        self._detay = detay
        self._pos_ids = [int(p["id"]) for p in detay.get("pos_kayitlari") or []]
        ttk.Label(
            self,
            text=(
                f"Belge: {detay['belge_no']}  ·  Tarih: {_tarih(detay['tarih'])}"
                f"  ·  PVA toplam: {_para(detay.get('pva_toplam'))}"
            ),
            font=("Segoe UI Semibold", 11),
        ).pack(anchor="w", padx=12, pady=(10, 4))
        ttk.Label(
            self,
            text="Aktarım fişi uygulama kaydıdır; gerçek banka ekstre teyidi ayrıdır.",
            foreground="#555",
        ).pack(anchor="w", padx=12)
        ttk.Label(self, text="Finans hareketleri", foreground="#555").pack(anchor="w", padx=12)
        tablo = ttk.Treeview(
            self, columns=("hesap", "tur", "tutar", "aciklama"), show="headings", height=6
        )
        for k, b, w in (
            ("hesap", "Hesap", 180),
            ("tur", "Hareket", 160),
            ("tutar", "Tutar", 90),
            ("aciklama", "Açıklama", 200),
        ):
            tablo.heading(k, text=b)
            tablo.column(k, width=w)
        tablo.pack(fill="both", expand=True, padx=12, pady=4)
        for h in detay["hareketler"]:
            tablo.insert(
                "",
                "end",
                values=(h["hesap_adi"], h["hareket_turu"], _para(h["tutar"]), h["aciklama"]),
            )
        ttk.Label(self, text="Bağlı POS işlemleri", foreground="#555").pack(anchor="w", padx=12)
        self._pt = ttk.Treeview(
            self,
            columns=("belge", "net", "akt", "durum", "yontem", "teyit", "teyit_detay"),
            show="headings",
            height=5,
        )
        for k, b, w in (
            ("belge", "POS fiş", 110),
            ("net", "Net", 80),
            ("akt", "Aktarılan", 80),
            ("durum", "Durum", 90),
            ("yontem", "Yöntem", 80),
            ("teyit", "Teyit", 70),
            ("teyit_detay", "Teyit ayrıntı", 200),
        ):
            self._pt.heading(k, text=b)
            self._pt.column(k, width=w)
        self._pt.pack(fill="both", expand=True, padx=12, pady=4)
        self._pos_doldur(detay)
        dugme = ttk.Frame(self)
        dugme.pack(fill="x", padx=12, pady=10)
        ttk.Button(dugme, text="Ekstreden teyit et", command=self._teyit_ver).pack(side="left")
        ttk.Button(dugme, text="Teyidi kaldır", command=self._teyit_kaldir).pack(side="left", padx=6)
        ttk.Button(dugme, text="Kapat", command=self.destroy).pack(side="right")

    def _pos_doldur(self, detay: dict) -> None:
        self._pt.delete(*self._pt.get_children())
        for p in detay.get("pos_kayitlari") or []:
            if p.get("banka_teyidi"):
                det = " · ".join(
                    x
                    for x in (
                        _tarih(p.get("banka_teyidi_tarihi")),
                        p.get("banka_teyidi_kullanici") or "",
                        p.get("banka_teyidi_notu") or "",
                    )
                    if x
                )
                teyit = "Evet"
            else:
                det = "Aktarım var; ekstre teyidi bekliyor" if p.get("aktarilan") else ""
                teyit = "Bekliyor"
            self._pt.insert(
                "",
                "end",
                values=(
                    p["belge_no"],
                    _para(p["net"]),
                    _para(p["aktarilan"]),
                    p["durum"],
                    p.get("aktarim_yontemi") or "—",
                    teyit,
                    det,
                ),
            )

    def _teyit_ver(self):
        if not self._pos_ids:
            return
        from tkinter import simpledialog

        notu = simpledialog.askstring(
            "Banka teyidi",
            "Gerçek banka ekstresinde görüldü.\nTeyit notu (isteğe bağlı):",
            parent=self,
        )
        if notu is None:
            return
        try:
            FinansService.pos_banka_teyidi_ayarla(self._pos_ids, teyit=True, notu=notu)
            detay = FinansService.pos_aktarim_belge_getir(self._belge_no)
            self._pos_doldur(detay)
            if self._on_ok:
                self._on_ok()
        except Exception as hata:
            messagebox.showerror("Banka teyidi", str(hata), parent=self)

    def _teyit_kaldir(self):
        if not self._pos_ids:
            return
        if not messagebox.askyesno("Teyit", "Ekstre teyidi kaldırılsın mı?", parent=self):
            return
        try:
            FinansService.pos_banka_teyidi_ayarla(self._pos_ids, teyit=False)
            detay = FinansService.pos_aktarim_belge_getir(self._belge_no)
            self._pos_doldur(detay)
            if self._on_ok:
                self._on_ok()
        except Exception as hata:
            messagebox.showerror("Banka teyidi", str(hata), parent=self)


def kk_cekimi_sayfasi_goster(app):
    """Müşteriden tedarikçiye kredi kartı çekimi — Banka İşlemleri menüsü."""
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="MÜŞTERİDEN TEDARİKÇİYE KREDİ KARTI ÇEKİMİ", style="Baslik.TLabel").pack(
        side="left"
    )
    ttk.Button(ust, text="← Banka İşlemleri", command=lambda: banka_islemleri_menusu_goster(app)).pack(
        side="right"
    )
    ttk.Label(
        app.icerik,
        text="Müşteriye alacak, tedarikçiye borç yazılır. Banka adı ve taksit serbest girilir; kasa/banka hesabına işlem düşmez.",
    ).pack(anchor="w", pady=(10, 6))

    arama_c = ttk.Frame(app.icerik)
    arama_c.pack(fill="x", pady=(0, 8))
    ttk.Label(arama_c, text="Ara:").pack(side="left")
    arama = ttk.Entry(arama_c, width=36)
    arama.pack(side="left", padx=6)

    butonlar = ttk.Frame(app.icerik)
    butonlar.pack(fill="x", pady=(0, 8))

    def _listeyi_yenile():
        for item in tablo.get_children():
            tablo.delete(item)
        for kayit in KkCekimiService.listele(arama.get().strip()):
            tablo.insert(
                "",
                "end",
                iid=kayit["belge_no"],
                values=(
                    kayit["belge_no"],
                    _tarih(kayit["tarih"]),
                    f"{kayit['musteri_kodu']} - {kayit['musteri_unvan']}",
                    f"{kayit['tedarikci_kodu']} - {kayit['tedarikci_unvan']}",
                    _para(kayit["tutar"]),
                    kayit["banka"],
                    kayit["cekim_turu"],
                    kayit["taksit_sayisi"],
                    kayit["aciklama"],
                ),
            )

    def _yeni():
        from app import KkCekimiDialog

        dialog = KkCekimiDialog(app)
        if dialog.winfo_exists():
            app.wait_window(dialog)
        if dialog.result:
            _listeyi_yenile()

    def _guncelle():
        from app import KkCekimiDialog

        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Lütfen güncellenecek KK çekim fişini seçin.", parent=app)
            return
        dialog = KkCekimiDialog(app, belge_no=secim[0])
        if dialog.winfo_exists():
            app.wait_window(dialog)
        if dialog.result:
            _listeyi_yenile()

    def _iptal():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Lütfen iptal edilecek KK çekim fişini seçin.", parent=app)
            return
        belge_no = secim[0]
        if not messagebox.askyesno(
            "KK çekim iptal",
            f"{belge_no} numaralı fiş iptal edilsin mi?\nMüşteri alacağı ve tedarikçi borcu geri alınır.",
            parent=app,
        ):
            return
        try:
            KkCekimiService.iptal_et(belge_no)
        except ValueError as hata:
            messagebox.showerror("İptal edilemedi", str(hata), parent=app)
            return
        _listeyi_yenile()

    ttk.Button(arama_c, text="Listele", command=_listeyi_yenile).pack(side="left")
    ttk.Button(
        butonlar, text="Müşteriden Tedarikçiye Kredi Kartı Çekim Fişi", command=_yeni
    ).pack(side="left")
    ttk.Button(butonlar, text="Güncelle", command=_guncelle).pack(side="left", padx=8)
    ttk.Button(butonlar, text="İptal Et", command=_iptal).pack(side="left", padx=8)
    ttk.Button(butonlar, text="Yenile", command=_listeyi_yenile).pack(side="left", padx=8)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True)
    tablo = ttk.Treeview(
        cerceve,
        columns=("belge", "tarih", "musteri", "tedarikci", "tutar", "banka", "cekim", "taksit", "aciklama"),
        show="headings",
        selectmode="browse",
    )
    for k, b, w in (
        ("belge", "Belge No", 100),
        ("tarih", "Tarih", 85),
        ("musteri", "Müşteri (Alacak)", 170),
        ("tedarikci", "Tedarikçi (Borç)", 170),
        ("tutar", "Tutar", 100),
        ("banka", "Banka", 110),
        ("cekim", "Çekim Türü", 100),
        ("taksit", "Taksit", 60),
        ("aciklama", "Açıklama", 160),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    tablo.bind("<Double-1>", lambda _e: _guncelle())

    _listeyi_yenile()


def cek_senet_menusu_goster(app):
    """Finans > ÇEK / SENET İŞLEMLERİ — sekmeli ana ekranı açar."""
    from cek_senet_ui import cek_senet_islemleri_goster

    cek_senet_islemleri_goster(app)


class HesapDialog(tk.Toplevel):
    """Kasa hesabı ekle / düzenle."""

    def __init__(self, parent, hesap_turu="KASA", hesap=None):
        super().__init__(parent)
        self.hesap_turu = hesap_turu
        self.hesap = hesap
        self.result = None
        self.title("Kasa" + (" Düzenle" if hesap else " Ekle"))
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        row = 0
        ttk.Label(self, text="Hesap Adı").grid(row=row, column=0, padx=12, pady=5, sticky="w")
        self.hesap_adi = ttk.Entry(self, width=40)
        self.hesap_adi.grid(row=row, column=1, padx=12, pady=5, sticky="w")

        row = 1
        ttk.Label(self, text="Para birimi").grid(row=row, column=0, padx=12, pady=5, sticky="w")
        self.para_birimi = ttk.Combobox(
            self, values=("TRY", "USD", "EUR"), state="readonly", width=10
        )
        self.para_birimi.set("TRY")
        self.para_birimi.grid(row=row, column=1, padx=12, pady=5, sticky="w")
        self.para_birimi.bind("<<ComboboxSelected>>", lambda _e: self._pb_degisti())

        row = 2
        ttk.Label(self, text="Açılış tarihi").grid(row=row, column=0, padx=12, pady=5, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=5, sticky="w")
        self.acilis_tarihi = ttk.Entry(tarih_c, width=14)
        self.acilis_tarihi.pack(side="left")
        takvim_butonu(tarih_c, self.acilis_tarihi)

        row = 3
        ttk.Label(self, text="Açılış Bakiyesi").grid(row=row, column=0, padx=12, pady=5, sticky="w")
        self.acilis_bakiyesi = ttk.Entry(self, width=40)
        self.acilis_bakiyesi.grid(row=row, column=1, padx=12, pady=5, sticky="w")

        row = 4
        self._kur_lbl = ttk.Label(self, text="Açılış kuru (1 PB=TRY)")
        self._kur_lbl.grid(row=row, column=0, padx=12, pady=5, sticky="w")
        self.acilis_kuru = ttk.Entry(self, width=16)
        self.acilis_kuru.grid(row=row, column=1, padx=12, pady=5, sticky="w")

        row = 5
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=5, sticky="w")
        self.aciklama = ttk.Entry(self, width=40)
        self.aciklama.grid(row=row, column=1, padx=12, pady=5, sticky="w")

        if hesap:
            self.hesap_adi.insert(0, hesap.hesap_adi or "")
            self.acilis_bakiyesi.insert(0, str(hesap.acilis_bakiyesi or 0))
            self.aciklama.insert(0, hesap.aciklama or "")
            pb = (getattr(hesap, "para_birimi", None) or "TRY").upper()
            self.para_birimi.set(pb if pb in ("TRY", "USD", "EUR") else "TRY")
            if getattr(hesap, "acilis_tarihi", None):
                self.acilis_tarihi.insert(0, hesap.acilis_tarihi.strftime("%d.%m.%Y"))
            kur = getattr(hesap, "acilis_kuru", None)
            if kur is not None:
                self.acilis_kuru.insert(0, str(kur).rstrip("0").rstrip(".") if "." in str(kur) else str(kur))
        else:
            self.acilis_bakiyesi.insert(0, "0")
            self.acilis_tarihi.insert(0, date.today().strftime("%d.%m.%Y"))

        from finans_muhasebe_hesap_ui import KasaMuhasebeHesabiAlani

        self.muhasebe_alani = KasaMuhasebeHesabiAlani(self, 6, hesap)
        self._pb_degisti()

        butonlar = ttk.Frame(self)
        butonlar.grid(row=8, column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")

    def _pb_degisti(self):
        pb = (self.para_birimi.get() or "TRY").upper()
        durum = "disabled" if pb == "TRY" else "normal"
        self.acilis_kuru.configure(state=durum)
        if pb == "TRY":
            self.acilis_kuru.delete(0, "end")
            self.acilis_kuru.insert(0, "1")
            self.acilis_kuru.configure(state="disabled")

    def kaydet(self):
        pb = self.para_birimi.get().strip()
        veri = {
            "hesap_adi": self.hesap_adi.get().strip(),
            "acilis_bakiyesi": self.acilis_bakiyesi.get().strip(),
            "aciklama": self.aciklama.get().strip(),
            "para_birimi": pb,
            "acilis_tarihi": self.acilis_tarihi.get().strip(),
            "hesap_turu": self.hesap_turu,
        }
        if pb.upper() != "TRY":
            kur = self.acilis_kuru.get().strip()
            if kur:
                veri["acilis_kuru"] = kur
        if self.hesap:
            veri["hesap_id"] = self.hesap.id
        try:
            self.result = FinansService.hesap_kaydet(veri)
        except ValueError as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        try:
            self.muhasebe_alani.kaydet(self.result.id)
        except Exception as hata:
            messagebox.showerror("Muhasebe Hesabı", f"Kasa kaydedildi, muhasebe hesabı kaydedilemedi:\n{hata}",
                                 parent=self)
            return
        self.destroy()


class AltHesapIslemDialog(tk.Toplevel):
    """KMH / POS / Kredi kartı / Krediler / Yatırım — basit giriş-çıkış."""

    def __init__(
        self,
        parent,
        kart,
        alt_tur: str,
        alt_etiket: str,
        *,
        hesap_id: int | None = None,
    ):
        super().__init__(parent)
        self.parent_dlg = parent
        self.kart_id = kart.id
        self.alt_tur = alt_tur
        self.hesap_id = int(hesap_id) if hesap_id else None
        self.title(f"{kart.banka_adi} — {alt_etiket}")
        self.geometry("820x520")
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        self.bakiye_lbl = tk.Label(ust, text="", font=("Segoe UI", 11, "bold"), anchor="w")
        self.bakiye_lbl.pack(side="left", fill="x", expand=True)
        ttk.Button(ust, text="Kapat", command=self.destroy).pack(side="right")

        form = ttk.LabelFrame(self, text="Yeni işlem", padding=10)
        form.pack(fill="x", padx=10, pady=4)
        ttk.Label(form, text="Tarih:").grid(row=0, column=0, sticky="w")
        tarih_c = ttk.Frame(form)
        tarih_c.grid(row=0, column=1, sticky="w", padx=4)
        self.tarih = ttk.Entry(tarih_c, width=12)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        ttk.Label(form, text="Tutar:").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.tutar = ttk.Entry(form, width=14)
        self.tutar.grid(row=0, column=3, sticky="w", padx=4)

        ttk.Label(form, text="Açıklama:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.aciklama = ttk.Entry(form, width=50)
        self.aciklama.grid(row=1, column=1, columnspan=3, sticky="ew", padx=4, pady=(6, 0))

        butonlar = ttk.Frame(form)
        butonlar.grid(row=2, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Button(butonlar, text="Giriş (+)", command=lambda: self._hareket("giris")).pack(side="left")
        ttk.Button(butonlar, text="Çıkış (−)", command=lambda: self._hareket("cikis")).pack(side="left", padx=8)
        ttk.Button(butonlar, text="Yenile", command=self.listeyi_yenile).pack(side="left")

        cerceve = ttk.Frame(self, padding=10)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=("tarih", "tur", "belge", "giris", "cikis", "aciklama"),
            show="headings",
        )
        _hareket_kolonlari_ayarla(
            self.tablo,
            (
                ("tarih", "Tarih", 90),
                ("tur", "Hareket", 120),
                ("belge", "Belge", 120),
                ("giris", "Giriş", 110),
                ("cikis", "Çıkış", 110),
                ("aciklama", "Açıklama", 260),
            ),
        )
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        _hareket_tablo_stil(self.tablo)
        _hareket_listesi_belge_bagla(self.tablo, self, self.listeyi_yenile)
        self.listeyi_yenile()

    def _hesap(self):
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            return None, None
        if self.hesap_id:
            hesap = next(
                (h for h in (kart.alt_hesaplar or []) if int(h.id) == int(self.hesap_id)),
                None,
            )
            return kart, hesap
        return kart, FinansService.banka_alt_hesap(kart, self.alt_tur)

    def listeyi_yenile(self):
        _kart, hesap = self._hesap()
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        if not hesap:
            self.bakiye_lbl.configure(
                text="Hesap bulunamadı — önce banka kartını kaydedin.",
                fg=_bakiye_renk(0),
            )
            return
        bak = FinansService.isletme_bakiyesi(hesap)
        self.bakiye_lbl.configure(
            text=f"{hesap.hesap_adi}  ·  Bakiye: {_para_bakiye(bak)}",
            fg=_bakiye_renk(bak),
        )
        for sira, har in enumerate(FinansService.hareketler(hesap_id=hesap.id, limit=400)):
            isaret = FinansService.hareket_isareti(har.hareket_turu)
            self.tablo.insert(
                "",
                "end",
                values=(
                    _tarih(har.tarih),
                    har.hareket_turu,
                    har.belge_no,
                    _para(har.tutar) if isaret > 0 else "",
                    _para(har.tutar) if isaret < 0 else "",
                    har.aciklama or "",
                ),
                tags=_hareket_satir_tags(sira, isaret=isaret),
            )

    def _hareket(self, yon):
        _kart, hesap = self._hesap()
        if not hesap:
            messagebox.showwarning("Hesap", "Önce banka kartını kaydedin.", parent=self)
            return
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            FinansService.banka_manuel_hareket(
                hesap.id,
                tarih,
                self.tutar.get(),
                yon,
                aciklama=self.aciklama.get().strip() or None,
            )
        except ValueError as hata:
            messagebox.showerror("İşlem", str(hata), parent=self)
            return
        self.tutar.delete(0, "end")
        self.aciklama.delete(0, "end")
        self.listeyi_yenile()
        if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
            self.parent_dlg.bakiyeleri_yenile()


class MevduatEvrakDialog(tk.Toplevel):
    """Kasadan yatırma / havale / nakit çekme / banka virman evrak formu."""

    YON_GONDER = "gonder"
    YON_AKTAR = "aktar"

    def __init__(self, parent, tur: str, mevduat_hesap_id: int):
        super().__init__(parent)
        self.tur = tur
        self.mevduat_hesap_id = mevduat_hesap_id
        self.result = None
        basliklar = {
            "kby": "Kasadan Bankaya Yatan",
            "ahv": "Alınan Havale",
            "ghv": "Gönderilen Havale",
            "bnc": "Bankadan Nakit Çekilen",
            "bvr": "Banka Transfer ve Virman Fişi",
        }
        self.title(basliklar.get(tur, "Mevduat Evrakı"))
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        from database.cari_service import CariService

        self.kasa = None
        self.cari = None
        self.hedef_hesap = None
        self.cari_map = {}
        self._kasa_map = {}
        self._hedef_map = {}
        self._secili_hesap = None
        self._secili_etiket = ""
        self.yon_var = None
        self.ozet_lbl = None

        if tur == "bvr":
            self._bvr_formu_kur()
            return

        row = 0
        ttk.Label(self, text="Tarih").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        row = 1
        ttk.Label(self, text="Tutar").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        if tur in ("kby", "bnc"):
            row = 2
            kasalar = FinansService.hesaplar(hesap_turu="KASA")
            ttk.Label(self, text="Kasa").grid(row=row, column=0, padx=12, pady=6, sticky="w")
            self.kasa = ttk.Combobox(
                self,
                values=[h.hesap_adi for h in kasalar],
                state="readonly",
                width=36,
            )
            self.kasa.grid(row=row, column=1, padx=12, pady=6, sticky="w")
            self._kasa_map = {h.hesap_adi: h.id for h in kasalar}
            if kasalar:
                self.kasa.set(kasalar[0].hesap_adi)
        elif tur == "ahv":
            row = 2
            cariler = CariService.listele(hizli=True)
            self.cari_map = {
                f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in cariler
            }
            ttk.Label(self, text="Gönderen cari *").grid(
                row=row, column=0, padx=12, pady=6, sticky="w"
            )
            self.cari = ttk.Combobox(self, values=list(self.cari_map), width=36)
            self.cari.grid(row=row, column=1, padx=12, pady=6, sticky="w")
            if self.cari_map:
                self.cari.set(next(iter(self.cari_map)))
        else:  # ghv
            row = 2
            cariler = CariService.listele(hizli=True)
            self.cari_map = {
                f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in cariler
            }
            ttk.Label(self, text="Alıcı cari *").grid(
                row=row, column=0, padx=12, pady=6, sticky="w"
            )
            self.cari = ttk.Combobox(self, values=list(self.cari_map), width=36)
            self.cari.grid(row=row, column=1, padx=12, pady=6, sticky="w")
            if self.cari_map:
                self.cari.set(next(iter(self.cari_map)))

        row = 3
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=40)
        self.aciklama.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=row + 1, column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")

    def _bvr_formu_kur(self):
        """Seçili hesap sabit; diğer hesap + işlem yönü ile çift yönlü virman."""
        self.columnconfigure(1, weight=1)
        secili = FinansService.hesap_getir(self.mevduat_hesap_id)
        if not secili or not secili.aktif:
            messagebox.showerror("Hesap", "Seçili banka hesabı bulunamadı veya pasif.", parent=self)
            self.destroy()
            return
        self._secili_hesap = secili
        self._secili_etiket = (secili.hesap_adi or "").strip() or f"Hesap #{secili.id}"

        row = 0
        ttk.Label(self, text="Seçili banka hesabı").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        secili_lbl = ttk.Label(self, text=self._secili_etiket, font=("Segoe UI", 10, "bold"))
        secili_lbl.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 1
        ttk.Label(self, text="Diğer banka hesabı *").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        hedefler = FinansService.banka_mevduat_hesaplari(haric_hesap_id=self.mevduat_hesap_id)
        self._hedef_map = {h.hesap_adi: h.id for h in hedefler}
        self.hedef_hesap = ttk.Combobox(
            self,
            values=[h.hesap_adi for h in hedefler],
            state="readonly",
            width=40,
        )
        self.hedef_hesap.grid(row=row, column=1, padx=12, pady=6, sticky="ew")
        if hedefler:
            self.hedef_hesap.set(hedefler[0].hesap_adi)
        self.hedef_hesap.bind("<<ComboboxSelected>>", lambda _e: self._bvr_ozet_guncelle())

        row = 2
        ttk.Label(self, text="İşlem yönü *").grid(row=row, column=0, padx=12, pady=6, sticky="nw")
        yon_c = ttk.Frame(self)
        yon_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        # İlk seçenek: diğer → sabit; ikinci: sabit → diğer
        self.yon_var = tk.StringVar(value=self.YON_AKTAR)
        ttk.Radiobutton(
            yon_c,
            text=(
                f"Seçili diğer banka hesabından {self._secili_etiket} hesabına gönder"
            ),
            variable=self.yon_var,
            value=self.YON_AKTAR,
            command=self._bvr_ozet_guncelle,
        ).pack(anchor="w")
        ttk.Radiobutton(
            yon_c,
            text=(
                f"Seçili diğer banka hesabına {self._secili_etiket} hesabından gönder"
            ),
            variable=self.yon_var,
            value=self.YON_GONDER,
            command=self._bvr_ozet_guncelle,
        ).pack(anchor="w")

        row = 3
        ttk.Label(self, text="Tarih *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        row = 4
        ttk.Label(self, text="Tutar *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 5
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=40)
        self.aciklama.grid(row=row, column=1, padx=12, pady=6, sticky="ew")

        row = 6
        ttk.Label(self, text="İşlem özeti").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.ozet_lbl = ttk.Label(self, text="", foreground="#1a4a7a", font=("Segoe UI", 10, "bold"))
        self.ozet_lbl.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self._bvr_ozet_guncelle()

        row = 7
        butonlar = ttk.Frame(self)
        butonlar.grid(row=row, column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")

    def _bvr_diger_etiket(self) -> str:
        if not self.hedef_hesap:
            return ""
        return (self.hedef_hesap.get() or "").strip()

    def _bvr_kaynak_hedef(self) -> tuple[int | None, int | None, str, str]:
        """Yöne göre (kaynak_id, hedef_id, kaynak_etiket, hedef_etiket)."""
        diger_id = self._hedef_map.get(self._bvr_diger_etiket()) if self._hedef_map else None
        secili_id = int(self.mevduat_hesap_id)
        secili_ad = self._secili_etiket
        diger_ad = self._bvr_diger_etiket()
        yon = (self.yon_var.get() if self.yon_var else self.YON_AKTAR) or self.YON_AKTAR
        if yon == self.YON_AKTAR:
            # Diğer → sabit hesap
            return diger_id, secili_id, diger_ad, secili_ad
        # Sabit → diğer hesap
        return secili_id, diger_id, secili_ad, diger_ad

    def _bvr_ozet_guncelle(self):
        if not self.ozet_lbl:
            return
        _kaynak_id, _hedef_id, kaynak_ad, hedef_ad = self._bvr_kaynak_hedef()
        if not kaynak_ad or not hedef_ad:
            self.ozet_lbl.configure(text="Diğer banka hesabını seçin")
            return
        self.ozet_lbl.configure(text=f"{kaynak_ad} → {hedef_ad}")

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            acik = self.aciklama.get().strip() or None
            if self.tur == "kby":
                if not self.kasa or not self.kasa.get():
                    raise ValueError("Kasa seçin.")
                belge = FinansService.kasadan_bankaya_yatan(
                    self._kasa_map[self.kasa.get()],
                    self.mevduat_hesap_id,
                    tarih,
                    self.tutar.get(),
                    acik,
                )
            elif self.tur == "ahv":
                if not self.cari or not self.cari.get().strip():
                    raise ValueError("Alınan havale için cari seçimi zorunludur.")
                cari_id = self.cari_map.get(self.cari.get())
                if cari_id is None:
                    raise ValueError("Geçerli bir cari seçin.")
                belge = FinansService.alinan_havale(
                    self.mevduat_hesap_id, tarih, self.tutar.get(), cari_id=cari_id, aciklama=acik
                )
            elif self.tur == "ghv":
                if not self.cari or not self.cari.get().strip():
                    raise ValueError("Gönderilen havale için alıcı cari seçimi zorunludur.")
                cari_id = self.cari_map.get(self.cari.get())
                if cari_id is None:
                    raise ValueError("Geçerli bir cari seçin.")
                belge = FinansService.gonderilen_havale(
                    self.mevduat_hesap_id, tarih, self.tutar.get(), cari_id=cari_id, aciklama=acik
                )
            elif self.tur == "bnc":
                if not self.kasa or not self.kasa.get():
                    raise ValueError("Kasa seçin.")
                belge = FinansService.bankadan_nakit_cekilen(
                    self.mevduat_hesap_id,
                    self._kasa_map[self.kasa.get()],
                    tarih,
                    self.tutar.get(),
                    acik,
                )
            elif self.tur == "bvr":
                kaynak_id, hedef_id, kaynak_ad, hedef_ad = self._bvr_kaynak_hedef()
                if not kaynak_id:
                    raise ValueError("Çıkış yapılacak hesabı seçin.")
                if not hedef_id:
                    raise ValueError("Diğer banka hesabını seçin.")
                if kaynak_id == hedef_id:
                    raise ValueError("Kaynak ve hedef hesap aynı olamaz.")
                if not acik:
                    acik = f"{kaynak_ad} → {hedef_ad}"
                belge = FinansService.banka_hesaplari_arasi_virman(
                    kaynak_id,
                    hedef_id,
                    tarih,
                    self.tutar.get(),
                    acik,
                )
            else:
                raise ValueError("Bilinmeyen evrak türü.")
        except ValueError as hata:
            messagebox.showerror("Evrak", str(hata), parent=self)
            return
        self.result = belge
        messagebox.showinfo("Kaydedildi", f"Belge no: {belge}", parent=self)
        self.destroy()


class MevduatIslemleriDialog(tk.Toplevel):
    """Mevduat işlem menüsü + evraklar + hareket listesi."""

    def __init__(self, parent, kart):
        super().__init__(parent)
        self.parent_dlg = parent
        self.kart_id = kart.id
        self.title(f"{kart.banka_adi} — Mevduat İşlemleri")
        self.geometry("960x600")
        self.minsize(860, 520)
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        self.bakiye_lbl = tk.Label(ust, text="", font=("Segoe UI", 11, "bold"), anchor="w")
        self.bakiye_lbl.pack(side="left", fill="x", expand=True)
        ttk.Button(ust, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(ust, text="Banka kartına git", command=self._banka_kartina_git).pack(
            side="right", padx=(0, 8)
        )
        ttk.Button(ust, text="Tüm mevduat / KMH", command=self._tum_mevduat_kmh).pack(
            side="right", padx=(0, 8)
        )

        menu = ttk.LabelFrame(self, text="Evraklar", padding=10)
        menu.pack(fill="x", padx=10, pady=4)
        for i, (kod, baslik) in enumerate((
            ("kby", "Kasadan Bankaya Yatan"),
            ("ahv", "Alınan Havale"),
            ("ghv", "Gönderilen Havale"),
            ("bnc", "Bankadan Nakit Çekilen"),
            ("bvr", "Banka Transfer ve Virman"),
            ("gdf", "Gider Fişi"),
        )):
            ttk.Button(
                menu,
                text=baslik,
                width=26,
                command=lambda t=kod: self._evrak_ac(t),
            ).grid(row=i // 3, column=i % 3, padx=4, pady=4, sticky="ew")
        for c in range(3):
            menu.columnconfigure(c, weight=1)

        orta = ttk.LabelFrame(self, text="Mevduat hesabı hareketleri", padding=8)
        orta.pack(fill="both", expand=True, padx=10, pady=6)
        ust2 = ttk.Frame(orta)
        ust2.pack(fill="x", pady=(0, 4))
        ttk.Button(ust2, text="Yenile", command=self.listeyi_yenile).pack(side="right")

        cerceve = ttk.Frame(orta)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=("tarih", "tur", "belge", "cari", "giris", "cikis", "bakiye", "aciklama"),
            show="headings",
        )
        _hareket_kolonlari_ayarla(
            self.tablo,
            (
                ("tarih", "Tarih", 85),
                ("tur", "Hareket / Evrak", 150),
                ("belge", "Belge No", 110),
                ("cari", "Cari", 170),
                ("giris", "Giriş", 100),
                ("cikis", "Çıkış", 100),
                ("bakiye", "Bakiye", 110),
                ("aciklama", "Açıklama", 180),
            ),
        )
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        _hareket_tablo_stil(self.tablo)
        _hareket_listesi_belge_bagla(self.tablo, self, self.listeyi_yenile)

        self.ozet = ttk.Label(self, text="")
        self.ozet.pack(anchor="w", padx=12, pady=(0, 8))
        self.listeyi_yenile()

    def _mevduat_hesap(self):
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            return None, None
        return kart, FinansService.banka_alt_hesap(kart, "MEVDUAT")

    def listeyi_yenile(self):
        kart, hesap = self._mevduat_hesap()
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        if not hesap:
            self.bakiye_lbl.configure(text="Mevduat hesabı bulunamadı.", fg=_bakiye_renk(0))
            return
        bak = FinansService.isletme_bakiyesi(hesap)
        self.bakiye_lbl.configure(
            text=f"{hesap.hesap_adi}  ·  Bakiye: {_para_bakiye(bak)}",
            fg=_bakiye_renk(bak),
        )
        hareketler = FinansService.mevduat_hareketleri(hesap.id)
        toplam_giris = Decimal("0")
        toplam_cikis = Decimal("0")
        for sira, har in enumerate(hareketler):
            toplam_giris += har["giris"]
            toplam_cikis += har["cikis"]
            self.tablo.insert(
                "",
                "end",
                values=(
                    _tarih(har["tarih"]),
                    har["hareket_turu"],
                    har["belge_no"],
                    har.get("cari") or "—",
                    _para(har["giris"]) if har["giris"] else "",
                    _para(har["cikis"]) if har["cikis"] else "",
                    _para_bakiye(har.get("bakiye", 0)),
                    har["aciklama"],
                ),
                tags=_hareket_satir_tags(
                    sira, giris=har["giris"], cikis=har["cikis"]
                ),
            )
        self.ozet.configure(
            text=f"{len(hareketler)} hareket · Toplam giriş: {_para(toplam_giris)} · Toplam çıkış: {_para(toplam_cikis)}"
        )
        if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
            self.parent_dlg.bakiyeleri_yenile()

    def _evrak_ac(self, tur):
        _kart, hesap = self._mevduat_hesap()
        if not hesap:
            messagebox.showwarning("Hesap", "Önce banka kartını kaydedin.", parent=self)
            return
        if tur == "gdf":
            from gider_fisi_ui import GiderFisiDialog

            dialog = GiderFisiDialog(self, finans_hesap_id=hesap.id)
            self.wait_window(dialog)
            if dialog.result:
                self.listeyi_yenile()
            return
        dialog = MevduatEvrakDialog(self, tur, hesap.id)
        self.wait_window(dialog)
        if dialog.result:
            self.listeyi_yenile()

    def _banka_kartina_git(self):
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            messagebox.showinfo("Banka", "Banka kartı bulunamadı.", parent=self)
            return
        # Zaten banka kartı içindeyse üst diyaloğa dön
        if isinstance(self.parent_dlg, BankaAnaKartDialog):
            self.destroy()
            return
        dialog = BankaAnaKartDialog(self.winfo_toplevel(), kart)
        self.wait_window(dialog)
        self.listeyi_yenile()

    def _tum_mevduat_kmh(self):
        hedef = _finans_app_kok(self.parent_dlg) or _finans_app_kok(self)
        try:
            self.destroy()
        except tk.TclError:
            pass
        if hedef is not None and hasattr(hedef, "_icerigi_temizle"):
            mevduat_kmh_hesaplari_sayfasi_goster(hedef)
        else:
            messagebox.showinfo(
                "Mevduat / KMH",
                "Finans → Mevduat ve KMH Hesapları menüsünden tüm bankaları açabilirsiniz.",
                parent=self.winfo_toplevel(),
            )


class KmhIslemleriDialog(tk.Toplevel):
    """KMH: kredi limiti + mevduat ile aynı banka işlem butonları + hareketler."""

    def __init__(self, parent, kart):
        super().__init__(parent)
        self.parent_dlg = parent
        self.kart_id = kart.id
        self.title(f"{kart.banka_adi} — KMH İşlemleri")
        self.geometry("980x640")
        self.minsize(900, 560)
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        self.bakiye_lbl = tk.Label(
            ust, text="", font=("Segoe UI", 11, "bold"), fg=_bakiye_renk(0), anchor="w"
        )
        self.bakiye_lbl.pack(side="left")
        self.kullanilabilir_lbl = tk.Label(
            ust,
            text="",
            font=("Segoe UI", 11, "bold"),
            fg="#1b7a3d",
            anchor="w",
        )
        self.kullanilabilir_lbl.pack(side="left", padx=(12, 0))
        ttk.Button(ust, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(ust, text="Banka kartına git", command=self._banka_kartina_git).pack(
            side="right", padx=(0, 8)
        )
        ttk.Button(ust, text="Tüm mevduat / KMH", command=self._tum_mevduat_kmh).pack(
            side="right", padx=(0, 8)
        )

        limit_f = ttk.LabelFrame(self, text="KMH kredi limiti", padding=10)
        limit_f.pack(fill="x", padx=10, pady=4)
        ttk.Label(limit_f, text="Kredi limiti (eksi bakiyeye kadar)").pack(side="left")
        self.kmh_limiti = ttk.Entry(limit_f, width=16)
        self.kmh_limiti.pack(side="left", padx=8)
        self.kmh_limiti.insert(0, str(getattr(kart, "kmh_limiti", 0) or 0))
        ttk.Button(limit_f, text="Limiti Kaydet", command=self._limit_kaydet).pack(
            side="left", padx=4
        )
        ttk.Label(
            limit_f,
            text="KMH +/− olabilir; limit kadar eksiye düşer. Eksi bakiye kırmızı/−.",
            foreground="#555",
        ).pack(side="left", padx=12)

        menu = ttk.LabelFrame(self, text="Evraklar (mevduat ile aynı işlemler)", padding=10)
        menu.pack(fill="x", padx=10, pady=4)
        for i, (kod, baslik) in enumerate((
            ("kby", "Kasadan Bankaya Yatan"),
            ("ahv", "Alınan Havale"),
            ("ghv", "Gönderilen Havale"),
            ("bnc", "Bankadan Nakit Çekilen"),
            ("bvr", "Banka Transfer ve Virman"),
            ("gdf", "Gider Fişi"),
        )):
            ttk.Button(
                menu,
                text=baslik,
                width=26,
                command=lambda t=kod: self._evrak_ac(t),
            ).grid(row=i // 3, column=i % 3, padx=4, pady=4, sticky="ew")
        for c in range(3):
            menu.columnconfigure(c, weight=1)

        orta = ttk.LabelFrame(self, text="KMH hesabı hareketleri", padding=8)
        orta.pack(fill="both", expand=True, padx=10, pady=6)
        ust2 = ttk.Frame(orta)
        ust2.pack(fill="x", pady=(0, 4))
        ttk.Button(ust2, text="Yenile", command=self.listeyi_yenile).pack(side="right")

        cerceve = ttk.Frame(orta)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=("tarih", "tur", "belge", "cari", "giris", "cikis", "bakiye", "aciklama"),
            show="headings",
        )
        _hareket_kolonlari_ayarla(
            self.tablo,
            (
                ("tarih", "Tarih", 85),
                ("tur", "Hareket / Evrak", 150),
                ("belge", "Belge No", 110),
                ("cari", "Cari", 170),
                ("giris", "Giriş", 100),
                ("cikis", "Çıkış", 100),
                ("bakiye", "Bakiye", 110),
                ("aciklama", "Açıklama", 180),
            ),
        )
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        _hareket_tablo_stil(self.tablo)
        _hareket_listesi_belge_bagla(self.tablo, self, self.listeyi_yenile)

        self.ozet = ttk.Label(self, text="")
        self.ozet.pack(anchor="w", padx=12, pady=(0, 8))
        self.listeyi_yenile()

    def _kmh_hesap(self):
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            return None, None
        return kart, FinansService.banka_alt_hesap(kart, "KMH")

    def _limit_kaydet(self):
        try:
            kart = FinansService.kmh_limiti_kaydet(self.kart_id, self.kmh_limiti.get())
        except ValueError as hata:
            messagebox.showerror("KMH limiti", str(hata), parent=self)
            return
        self.kmh_limiti.delete(0, "end")
        self.kmh_limiti.insert(0, str(kart.kmh_limiti or 0))
        messagebox.showinfo(
            "Kaydedildi",
            f"KMH limiti: {_para(kart.kmh_limiti)}\n"
            f"Bakiye bu limite kadar eksiye düşebilir.",
            parent=self,
        )
        self.listeyi_yenile()
        if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
            self.parent_dlg.bakiyeleri_yenile()
            if hasattr(self.parent_dlg, "alanlar") and "kmh_limiti" in self.parent_dlg.alanlar:
                w = self.parent_dlg.alanlar["kmh_limiti"]
                w.delete(0, "end")
                w.insert(0, str(kart.kmh_limiti or 0))

    def listeyi_yenile(self):
        kart, hesap = self._kmh_hesap()
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        if not hesap:
            self.bakiye_lbl.configure(text="KMH hesabı bulunamadı.", fg=_bakiye_renk(0))
            self.kullanilabilir_lbl.configure(text="")
            return
        bak = FinansService.isletme_bakiyesi(hesap)
        limit = FinansService.kmh_limiti(kart)
        asgari = FinansService.asgari_bakiye(hesap, kart)
        kullanilabilir = FinansService.kullanilabilir_bakiye(hesap, kart)
        self.bakiye_lbl.configure(
            text=(
                f"{hesap.hesap_adi}  ·  Bakiye: {_para_bakiye(bak)}  ·  "
                f"Limit: {_para(limit)} (min {_para_bakiye(asgari)})"
            ),
            fg=_bakiye_renk(bak),
        )
        self.kullanilabilir_lbl.configure(
            text=f"·  Kullanılabilir: {_para_bakiye(kullanilabilir)}",
            fg=_bakiye_renk(kullanilabilir),
        )
        hareketler = FinansService.mevduat_hareketleri(hesap.id)
        toplam_giris = Decimal("0")
        toplam_cikis = Decimal("0")
        for sira, har in enumerate(hareketler):
            toplam_giris += har["giris"]
            toplam_cikis += har["cikis"]
            calisan = Decimal(str(har.get("bakiye", 0)))
            self.tablo.insert(
                "",
                "end",
                values=(
                    _tarih(har["tarih"]),
                    har["hareket_turu"],
                    har["belge_no"],
                    har.get("cari") or "—",
                    _para(har["giris"]) if har["giris"] else "",
                    _para(har["cikis"]) if har["cikis"] else "",
                    _para_bakiye(calisan),
                    har["aciklama"],
                ),
                tags=_hareket_satir_tags(
                    sira, giris=har["giris"], cikis=har["cikis"]
                ),
            )
        self.ozet.configure(
            text=f"{len(hareketler)} hareket · Toplam giriş: {_para(toplam_giris)} · "
            f"Toplam çıkış: {_para(toplam_cikis)}"
        )
        if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
            self.parent_dlg.bakiyeleri_yenile()

    def _evrak_ac(self, tur):
        _kart, hesap = self._kmh_hesap()
        if not hesap:
            messagebox.showwarning("Hesap", "Önce banka kartını kaydedin.", parent=self)
            return
        if tur == "gdf":
            from gider_fisi_ui import GiderFisiDialog

            dialog = GiderFisiDialog(self, finans_hesap_id=hesap.id)
            self.wait_window(dialog)
            if dialog.result:
                self.listeyi_yenile()
            return
        dialog = MevduatEvrakDialog(self, tur, hesap.id)
        self.wait_window(dialog)
        if dialog.result:
            self.listeyi_yenile()

    def _banka_kartina_git(self):
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            messagebox.showinfo("Banka", "Banka kartı bulunamadı.", parent=self)
            return
        if isinstance(self.parent_dlg, BankaAnaKartDialog):
            self.destroy()
            return
        dialog = BankaAnaKartDialog(self.winfo_toplevel(), kart)
        self.wait_window(dialog)
        self.listeyi_yenile()

    def _tum_mevduat_kmh(self):
        hedef = _finans_app_kok(self.parent_dlg) or _finans_app_kok(self)
        try:
            self.destroy()
        except tk.TclError:
            pass
        if hedef is not None and hasattr(hedef, "_icerigi_temizle"):
            mevduat_kmh_hesaplari_sayfasi_goster(hedef)
        else:
            messagebox.showinfo(
                "Mevduat / KMH",
                "Finans → Mevduat ve KMH Hesapları menüsünden tüm bankaları açabilirsiniz.",
                parent=self.winfo_toplevel(),
            )


class PosIslemleriDialog(tk.Toplevel):
    """POS tahsilat (komisyonlu) + valör bekleyenler + hedef hesaba aktarım + hareketler."""

    def __init__(self, parent, kart, *, pos_hesap_id: int | None = None):
        super().__init__(parent)
        self.parent_dlg = parent
        self.kart_id = kart.id
        self.pos_hesap_id = int(pos_hesap_id) if pos_hesap_id else None
        baslik_ek = ""
        if self.pos_hesap_id:
            for h in kart.alt_hesaplar or []:
                if int(h.id) == self.pos_hesap_id:
                    baslik_ek = f" — {h.hesap_adi}"
                    break
        self.title(f"{kart.banka_adi} — POS İşlemleri{baslik_ek}")
        self.geometry("980x640")
        self.minsize(900, 560)
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        # Yalnız otomatik mahsup açıksa arka plan aktarımı
        FinansService.pos_valor_vadesi_gelenleri_aktar(
            banka_karti_id=self.kart_id, sadece_otomatik=True
        )

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        self.bakiye_lbl = ttk.Label(ust, text="", font=("Segoe UI", 11, "bold"))
        self.bakiye_lbl.pack(side="left")
        ttk.Button(ust, text="Kapat", command=self.destroy).pack(side="right")

        menu = ttk.LabelFrame(self, text="Evraklar", padding=10)
        menu.pack(fill="x", padx=10, pady=4)
        ttk.Button(menu, text="Kredi / Banka Kartı Tahsilat", command=self._tahsilat_ac).pack(
            side="left", padx=4
        )
        ttk.Button(menu, text="Valör Aktarımlarını Çalıştır", command=self._valor_calistir).pack(
            side="left", padx=4
        )
        ttk.Button(menu, text="Yenile", command=self.listeyi_yenile).pack(side="left", padx=4)

        bekleyen = ttk.LabelFrame(
            self,
            text="Bekleyen POS alacakları (brüt / komisyon / net) — valörde hedef hesaba",
            padding=8,
        )
        bekleyen.pack(fill="x", padx=10, pady=4)
        self.valor_tablo = ttk.Treeview(
            bekleyen,
            columns=("belge", "tahsilat", "valor", "saat", "kart", "brut", "kom", "net", "durum"),
            show="headings",
            height=5,
        )
        for k, b, w in (
            ("belge", "Belge", 110),
            ("tahsilat", "Tahsilat", 85),
            ("valor", "Valör", 85),
            ("saat", "Saat", 55),
            ("kart", "Kart", 90),
            ("brut", "Brüt", 80),
            ("kom", "Komisyon", 80),
            ("net", "Net", 80),
            ("durum", "Durum", 80),
        ):
            self.valor_tablo.heading(k, text=b)
            self.valor_tablo.column(k, width=w, anchor="w")
        self.valor_tablo.pack(fill="x")

        orta = ttk.LabelFrame(self, text="POS hesabı hareketleri", padding=8)
        orta.pack(fill="both", expand=True, padx=10, pady=6)
        cerceve = ttk.Frame(orta)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=("tarih", "tur", "belge", "cari", "giris", "cikis", "bakiye", "aciklama"),
            show="headings",
        )
        _hareket_kolonlari_ayarla(
            self.tablo,
            (
                ("tarih", "Tarih", 85),
                ("tur", "Hareket", 150),
                ("belge", "Belge", 110),
                ("cari", "Cari", 160),
                ("giris", "Giriş", 100),
                ("cikis", "Çıkış", 100),
                ("bakiye", "Bakiye", 105),
                ("aciklama", "Açıklama", 180),
            ),
        )
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        _hareket_tablo_stil(self.tablo)
        _hareket_listesi_belge_bagla(self.tablo, self, self.listeyi_yenile)

        self.ozet = ttk.Label(self, text="")
        self.ozet.pack(anchor="w", padx=12, pady=(0, 8))
        self.listeyi_yenile()

    def _kart_hesaplar(self):
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            return None, None, None
        if self.pos_hesap_id:
            pos = next(
                (
                    h
                    for h in (kart.alt_hesaplar or [])
                    if int(h.id) == int(self.pos_hesap_id)
                    and (h.alt_hesap_turu or "").upper() == "POS"
                ),
                None,
            )
        else:
            pos = FinansService.banka_alt_hesap(kart, "POS")
        return (
            kart,
            pos,
            FinansService.banka_alt_hesap(kart, "KMH"),
        )

    def listeyi_yenile(self):
        FinansService.pos_valor_vadesi_gelenleri_aktar(
            banka_karti_id=self.kart_id, sadece_otomatik=True
        )
        kart, pos, _kmh = self._kart_hesaplar()
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        for item in self.valor_tablo.get_children():
            self.valor_tablo.delete(item)
        if not pos:
            self.bakiye_lbl.configure(text="POS hesabı bulunamadı.")
            return
        hareket_bak = FinansService.bakiye(pos)
        alacak = FinansService.pos_aktif_alacak_ozeti(
            banka_karti_id=self.kart_id,
            pos_hesap_id=int(pos.id),
        )
        ayar_kart = FinansService.pos_ayar_karti(pos, banka_karti_id=self.kart_id) or kart
        ozet = FinansService.pos_valor_ozet_metni(ayar_kart) if ayar_kart else ""
        self.bakiye_lbl.configure(
            text=(
                f"{pos.hesap_adi}  ·  "
                f"Açık POS alacağı (net): {_para_bakiye(alacak['net'])}  "
                f"({alacak['adet']} açık)  ·  "
                f"Brüt {_para(alacak['brut'])} / kom. {_para(alacak['komisyon'])}  ·  "
                f"Hareket/ekstre bakiyesi (tarihî toplam): {_para_bakiye(hareket_bak)}  ·  {ozet}"
            ),
            foreground=_bakiye_renk(alacak["net"]),
        )
        for kayit in FinansService.pos_valor_bekleyenler(
            banka_karti_id=self.kart_id, pos_hesap_id=int(pos.id)
        ):
            tip = dict(POS_KART_TIPLERI).get(kayit.kart_tipi, kayit.kart_tipi)
            self.valor_tablo.insert(
                "",
                "end",
                values=(
                    kayit.belge_no,
                    _tarih(kayit.tahsilat_tarihi),
                    _tarih(kayit.valor_tarihi),
                    kayit.valor_saati,
                    tip,
                    _para(kayit.brut_tutar),
                    _para(kayit.komisyon_tutari),
                    _para(kayit.net_tutar),
                    kayit.durum,
                ),
            )
        for sira, har in enumerate(FinansService.pos_hareketleri(pos.id)):
            self.tablo.insert(
                "",
                "end",
                values=(
                    _tarih(har["tarih"]),
                    har["hareket_turu"],
                    har["belge_no"],
                    har.get("cari") or "—",
                    _para(har["giris"]) if har["giris"] else "",
                    _para(har["cikis"]) if har["cikis"] else "",
                    _para_bakiye(har["bakiye"]),
                    har["aciklama"],
                ),
                tags=_hareket_satir_tags(
                    sira, giris=har["giris"], cikis=har["cikis"]
                ),
            )
        if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
            self.parent_dlg.bakiyeleri_yenile()

    def _tahsilat_ac(self):
        dialog = PosTahsilatDialog(
            self, self.kart_id, pos_hesap_id=self.pos_hesap_id
        )
        self.wait_window(dialog)
        if dialog.result:
            self.listeyi_yenile()

    def _valor_calistir(self):
        sonuclar = FinansService.pos_valor_vadesi_gelenleri_aktar(
            banka_karti_id=self.kart_id, zorla=True
        )
        if not sonuclar:
            messagebox.showinfo(
                "Valör",
                "Aktarılacak vadesi gelmiş kayıt yok.\n"
                "(Beklenen valör tarihi bugün veya geçmiş olmalı.)",
                parent=self,
            )
        else:
            messagebox.showinfo(
                "Valör",
                f"{len(sonuclar)} kayıt hedef hesaba aktarıldı.",
                parent=self,
            )
        self.listeyi_yenile()


class PosTahsilatDialog(tk.Toplevel):
    def __init__(self, parent, banka_karti_id, *, pos_hesap_id: int | None = None):
        super().__init__(parent)
        self.banka_karti_id = banka_karti_id
        self.pos_hesap_id = int(pos_hesap_id) if pos_hesap_id else None
        self.result = None
        self.title("POS Tahsilat (Kredi / Banka Kartı)")
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        from database.cari_service import CariService

        kart = FinansService.banka_karti_getir(banka_karti_id)
        pos_hesap = None
        if self.pos_hesap_id and kart:
            pos_hesap = next(
                (h for h in (kart.alt_hesaplar or []) if int(h.id) == self.pos_hesap_id),
                None,
            )
        ayar = FinansService.pos_ayar_karti(pos_hesap, banka_karti_id=banka_karti_id) or kart
        pos_etiket = f" · POS: {pos_hesap.hesap_adi}" if pos_hesap else ""
        ttk.Label(
            self,
            text=(
                f"KK komisyon %{ayar.kk_komisyon_orani:g} · "
                f"Banka kartı %{ayar.banka_karti_komisyon_orani:g} · "
                f"{FinansService.pos_valor_ozet_metni(ayar)}{pos_etiket}"
            ),
            foreground="#555",
        ).grid(row=0, column=0, columnspan=2, padx=12, pady=(10, 4), sticky="w")

        ttk.Label(self, text="Tarih").grid(row=1, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=1, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        ttk.Label(self, text="Kart tipi").grid(row=2, column=0, padx=12, pady=6, sticky="w")
        self.kart_tipi = ttk.Combobox(
            self,
            values=[e for _k, e in POS_KART_TIPLERI],
            state="readonly",
            width=28,
        )
        self.kart_tipi.set("Kredi Kartı")
        self.kart_tipi.grid(row=2, column=1, padx=12, pady=6, sticky="w")
        self._tip_map = {e: k for k, e in POS_KART_TIPLERI}

        ttk.Label(self, text="Brüt tutar").grid(row=3, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=3, column=1, padx=12, pady=6, sticky="w")

        cariler = CariService.listele(hizli=True)
        self.cari_map = {
            f"{o['cari'].cari_kodu} - {o['cari'].unvan}": o["cari"].id for o in cariler
        }
        ttk.Label(self, text="Cari (opsiyonel)").grid(row=4, column=0, padx=12, pady=6, sticky="w")
        self.cari = ttk.Combobox(self, values=["(Cari yok)"] + list(self.cari_map), width=36)
        self.cari.set("(Cari yok)")
        self.cari.grid(row=4, column=1, padx=12, pady=6, sticky="w")

        ttk.Label(self, text="Açıklama").grid(row=5, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=40)
        self.aciklama.grid(row=5, column=1, padx=12, pady=6, sticky="w")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=6, column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            tip = self._tip_map.get(self.kart_tipi.get(), "KREDI_KARTI")
            cari_id = None
            if self.cari.get() and self.cari.get() != "(Cari yok)":
                cari_id = self.cari_map.get(self.cari.get())
                if cari_id is None:
                    raise ValueError("Geçerli bir cari seçin.")
            self.result = FinansService.pos_tahsilat(
                self.banka_karti_id,
                tarih,
                self.tutar.get(),
                kart_tipi=tip,
                cari_id=cari_id,
                aciklama=self.aciklama.get().strip() or None,
                pos_hesap_id=self.pos_hesap_id,
            )
        except ValueError as hata:
            messagebox.showerror("POS Tahsilat", str(hata), parent=self)
            return
        r = self.result
        messagebox.showinfo(
            "Kaydedildi",
            f"Belge: {r['belge_no']}\n"
            f"Brüt: {_para(r['brut'])} · Komisyon: {_para(r['komisyon'])} · Net: {_para(r['net'])}\n"
            f"Valör: {r['valor_tarihi'].strftime('%d.%m.%Y')} {r['valor_saati']} → KMH",
            parent=self,
        )
        self.destroy()


class PosHesaplariDialog(tk.Toplevel):
    """Bankanın POS hesapları listesi — çift tık ile ilgili POS işlemleri."""

    def __init__(self, parent, kart):
        super().__init__(parent)
        self.parent_dlg = parent
        self.kart_id = kart.id
        self.title(f"{kart.banka_adi} — POS Hesapları")
        self.geometry("900x480")
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        ttk.Label(
            ust,
            text="Bu bankaya bağlı POS hesapları. Çift tık = POS işlemleri.",
            foreground="#555",
        ).pack(side="left")
        ttk.Button(ust, text="Kapat", command=self.destroy).pack(side="right")

        cerceve = ttk.Frame(self, padding=10)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=("ad", "bakiye", "bekleyen", "durum"),
            show="headings",
            selectmode="browse",
        )
        for k, b, w in (
            ("ad", "POS hesabı", 320),
            ("bakiye", "Hareket bakiyesi", 130),
            ("bekleyen", "Bekleyen net", 130),
            ("durum", "Durum", 70),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="w")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        self.tablo.bind("<Double-1>", lambda _e: self._ac())

        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="POS İşlemlerini Aç", command=self._ac).pack(side="left")
        ttk.Button(alt, text="Yenile", command=self.listeyi_yenile).pack(side="left", padx=8)
        self.listeyi_yenile()

    def listeyi_yenile(self):
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            return
        for h in FinansService.pos_alt_hesaplari(kart, aktif_only=False):
            alacak = FinansService.pos_aktif_alacak_ozeti(
                banka_karti_id=self.kart_id, pos_hesap_id=int(h.id)
            )
            self.tablo.insert(
                "",
                "end",
                iid=str(h.id),
                values=(
                    h.hesap_adi or "—",
                    _para_bakiye(FinansService.bakiye(h)),
                    _para_bakiye(alacak["net"]),
                    "Aktif" if h.aktif else "Pasif",
                ),
            )

    def _ac(self):
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("POS", "Bir POS hesabı seçin.", parent=self)
            return
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            return
        dialog = PosIslemleriDialog(self, kart, pos_hesap_id=int(secim[0]))
        self.wait_window(dialog)
        self.listeyi_yenile()
        if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
            self.parent_dlg.bakiyeleri_yenile()


class YatirimHesaplariDialog(tk.Toplevel):
    """Bankanın yatırım hesapları — bakiye, hareket, yeni hesap."""

    def __init__(self, parent, kart):
        super().__init__(parent)
        self.parent_dlg = parent
        self.kart_id = kart.id
        self.title(f"{kart.banka_adi} — Yatırım Hesapları")
        self.geometry("980x560")
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        self.ozet_lbl = ttk.Label(ust, text="", font=("Segoe UI", 11, "bold"))
        self.ozet_lbl.pack(side="left")
        ttk.Button(ust, text="Kapat", command=self.destroy).pack(side="right")

        menu = ttk.Frame(self, padding=(10, 0))
        menu.pack(fill="x")
        ttk.Button(menu, text="Yeni Yatırım Hesabı", command=self._yeni).pack(side="left")
        ttk.Button(menu, text="Hareketler", command=self._hareket_ac).pack(side="left", padx=8)
        ttk.Button(menu, text="Yenile", command=self.listeyi_yenile).pack(side="left")

        cerceve = ttk.Frame(self, padding=10)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=("ad", "bakiye", "pb", "durum"),
            show="headings",
            selectmode="browse",
        )
        for k, b, w in (
            ("ad", "Yatırım hesabı", 360),
            ("bakiye", "Bakiye", 140),
            ("pb", "PB", 50),
            ("durum", "Durum", 70),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="w")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        self.tablo.bind("<Double-1>", lambda _e: self._hareket_ac())

        orta = ttk.LabelFrame(self, text="Seçili hesap hareketleri", padding=8)
        orta.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.hareket_tablo = ttk.Treeview(
            orta,
            columns=("tarih", "tur", "belge", "giris", "cikis", "aciklama"),
            show="headings",
            height=8,
        )
        _hareket_kolonlari_ayarla(
            self.hareket_tablo,
            (
                ("tarih", "Tarih", 90),
                ("tur", "Hareket", 130),
                ("belge", "Belge", 120),
                ("giris", "Giriş", 100),
                ("cikis", "Çıkış", 100),
                ("aciklama", "Açıklama", 260),
            ),
        )
        hk = ttk.Scrollbar(orta, orient="vertical", command=self.hareket_tablo.yview)
        self.hareket_tablo.configure(yscrollcommand=hk.set)
        self.hareket_tablo.pack(side="left", fill="both", expand=True)
        hk.pack(side="right", fill="y")
        _hareket_tablo_stil(self.hareket_tablo)
        self.tablo.bind("<<TreeviewSelect>>", lambda _e: self._hareketleri_yenile())
        self.listeyi_yenile()

    def listeyi_yenile(self):
        for item in self.tablo.get_children():
            self.tablo.delete(item)
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            return
        toplam = Decimal("0")
        for h in FinansService.yatirim_alt_hesaplari(kart, aktif_only=False):
            bak = FinansService.isletme_bakiyesi(h)
            if h.aktif:
                toplam += bak
            self.tablo.insert(
                "",
                "end",
                iid=str(h.id),
                values=(
                    h.hesap_adi or "—",
                    _para_bakiye(bak),
                    getattr(h, "para_birimi", None) or "TRY",
                    "Aktif" if h.aktif else "Pasif",
                ),
            )
        self.ozet_lbl.configure(
            text=f"Yatırım hesapları toplamı: {_para_bakiye(toplam)}",
            foreground=_bakiye_renk(toplam),
        )
        self._hareketleri_yenile()

    def _secili_id(self) -> int | None:
        secim = self.tablo.selection()
        return int(secim[0]) if secim else None

    def _hareketleri_yenile(self):
        for item in self.hareket_tablo.get_children():
            self.hareket_tablo.delete(item)
        hid = self._secili_id()
        if not hid:
            return
        for sira, har in enumerate(FinansService.hareketler(hesap_id=hid, limit=300)):
            isaret = FinansService.hareket_isareti(har.hareket_turu)
            self.hareket_tablo.insert(
                "",
                "end",
                values=(
                    _tarih(har.tarih),
                    har.hareket_turu,
                    har.belge_no,
                    _para(har.tutar) if isaret > 0 else "",
                    _para(har.tutar) if isaret < 0 else "",
                    har.aciklama or "",
                ),
                tags=_hareket_satir_tags(sira, isaret=isaret),
            )

    def _yeni(self):
        ad = simpledialog.askstring(
            "Yeni Yatırım Hesabı",
            "Hesap adı:",
            parent=self,
        )
        if not ad:
            return
        try:
            FinansService.yatirim_hesabi_olustur(self.kart_id, ad)
        except ValueError as hata:
            messagebox.showerror("Yatırım", str(hata), parent=self)
            return
        self.listeyi_yenile()
        if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
            self.parent_dlg.bakiyeleri_yenile()

    def _hareket_ac(self):
        hid = self._secili_id()
        if not hid:
            messagebox.showinfo("Yatırım", "Bir yatırım hesabı seçin.", parent=self)
            return
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            return
        hesap = next((h for h in (kart.alt_hesaplar or []) if int(h.id) == hid), None)
        dialog = AltHesapIslemDialog(
            self,
            kart,
            "VADELI",
            (hesap.hesap_adi if hesap else "Yatırım Hesabı"),
            hesap_id=hid,
        )
        self.wait_window(dialog)
        self.listeyi_yenile()
        if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
            self.parent_dlg.bakiyeleri_yenile()


class KrediKartiIslemleriDialog(tk.Toplevel):
    """Kredi kartı tanımları + ödeme evrakı + taksitler + KK hesap hareketleri.

    Banka ana kartının alt/ilgili KK ekranı. Bağımsız «FİRMA KREDİ KARTI» paneli değildir.
    """

    def __init__(self, parent, kart, kredi_karti_id: int | None = None):
        super().__init__(parent)
        self.parent_dlg = parent
        self.kart_id = kart.id
        self._acilis_kk_id = int(kredi_karti_id) if kredi_karti_id else None
        self.title(f"{kart.banka_adi} — Kredi Kartı İşlemleri")
        self.geometry("1020x680")
        self.minsize(940, 600)
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        # tk.Label: ttk temasında foreground güvenilir değil (negatif yeşil kalabiliyordu)
        self.bakiye_lbl = tk.Label(ust, text="", font=("Segoe UI", 12, "bold"), anchor="w")
        self.bakiye_lbl.pack(side="left", fill="x", expand=True)
        ttk.Button(ust, text="Kapat", command=self._kapat).pack(side="right")
        self.banka_toplam_lbl = tk.Label(
            self, text="", font=("Segoe UI", 10), anchor="w", padx=12
        )
        self.banka_toplam_lbl.pack(fill="x")

        menu = ttk.LabelFrame(self, text="Evraklar / Kartlar", padding=10)
        menu.pack(fill="x", padx=10, pady=4)
        # V4: taksit/ödeme/ekstre düğmeleri Kredi Kartı Tanımı formunda; burada eski menü korunur
        ttk.Button(menu, text="Kredi Kartı Tanımla", command=self._kart_tanim_ac).pack(
            side="left", padx=4
        )
        ttk.Button(menu, text="Kartları Düzenle", command=self._kart_liste_ac).pack(
            side="left", padx=4
        )
        ttk.Button(menu, text="Ekstre Ödeme Evrakı", command=self._odeme_ac).pack(
            side="left", padx=4
        )
        ttk.Button(
            menu, text="Ekstre / Dönem Borcu Raporu", command=self._donem_borcu_raporu
        ).pack(side="left", padx=4)
        ttk.Button(menu, text="Taksitli Nakit Avans", command=self._nakit_avans_ac).pack(
            side="left", padx=4
        )
        ttk.Button(menu, text="Tüm firma kredi kartları", command=self._tum_firma_kartlari).pack(
            side="left", padx=4
        )
        ttk.Button(menu, text="Tarihleri değiştir", command=self._tarihleri_degistir).pack(
            side="left", padx=4
        )
        ttk.Button(menu, text="Yenile", command=self.listeyi_yenile).pack(side="left", padx=4)

        self.esleme_uyari = ttk.Label(self, text="", foreground="#a15c00")
        self.esleme_uyari.pack(anchor="w", padx=12, pady=(0, 2))

        kartlar_f = ttk.LabelFrame(self, text="Tanımlı kredi kartları", padding=8)
        kartlar_f.pack(fill="x", padx=10, pady=4)
        self.kart_tablo = ttk.Treeview(
            kartlar_f,
            columns=(
                "banka", "ad", "marka", "no", "skt", "limit", "kullanilan", "kalan",
                "son_kesim", "sonraki_kesim", "son_odeme", "durum",
            ),
            show="headings",
            height=5,
            selectmode="browse",
        )
        for k, b, w in (
            ("banka", "Banka", 90),
            ("ad", "Kart adı", 120),
            ("marka", "Marka", 70),
            ("no", "Kart no", 80),
            ("skt", "SKT", 50),
            ("limit", "Kart Limiti", 95),
            ("kullanilan", "Kullanılan Limit", 110),
            ("kalan", "Kullanılabilir Limit", 120),
            ("son_kesim", "Son kesim", 90),
            ("sonraki_kesim", "Sonraki kesim", 100),
            ("son_odeme", "Son ödeme", 90),
            ("durum", "Durum", 55),
        ):
            self.kart_tablo.heading(k, text=b)
            self.kart_tablo.column(k, width=w, anchor="w")
        self.kart_tablo.pack(fill="x")
        self.kart_tablo.bind("<<TreeviewSelect>>", self._kart_secildi)
        self.kart_tablo.bind("<Double-1>", lambda _e: self._kart_duzenle_secili())

        taksit_f = ttk.LabelFrame(self, text="Bekleyen taksitler", padding=8)
        taksit_f.pack(fill="x", padx=10, pady=4)
        self.taksit_tablo = ttk.Treeview(
            taksit_f,
            columns=("belge", "kart", "no", "yansima", "kesim", "son_odeme", "tutar"),
            show="headings",
            height=4,
        )
        for k, b, w in (
            ("belge", "Belge", 120),
            ("kart", "Kart", 130),
            ("no", "Taksit", 60),
            ("yansima", "Taksit vadesi", 100),
            ("kesim", "Hesap kesim", 95),
            ("son_odeme", "Ekstre son ödeme", 110),
            ("tutar", "Tutar", 90),
        ):
            self.taksit_tablo.heading(k, text=b)
            self.taksit_tablo.column(k, width=w, anchor="w")
        self.taksit_tablo.pack(fill="x")
        self.taksit_tablo.bind("<<TreeviewSelect>>", self._taksit_secildi)
        self.taksit_tablo.bind("<Double-1>", self._taksit_belge_ac)
        self.taksit_tablo.bind("<Return>", self._taksit_belge_ac)
        self._taksit_odeme_map: dict[str, int] = {}
        self._taksit_belge: dict[str, str] = {}
        self._secili_odeme_id: int | None = None

        filtre = ttk.Frame(self, padding=(10, 0))
        filtre.pack(fill="x")
        ttk.Label(filtre, text="Hareket:").pack(side="left")
        self.har_bas = ttk.Entry(filtre, width=11)
        self.har_bas.pack(side="left", padx=4)
        ttk.Label(filtre, text="—").pack(side="left")
        self.har_bit = ttk.Entry(filtre, width=11)
        self.har_bit.pack(side="left", padx=4)
        takvim_butonu(filtre, self.har_bas)
        takvim_butonu(filtre, self.har_bit)
        ttk.Button(filtre, text="Filtrele", command=self._detay_yenile).pack(side="left", padx=6)
        ttk.Button(
            filtre, text="Tüm tarih", command=self._har_filtre_temizle
        ).pack(side="left")
        ttk.Button(
            filtre, text="Sil", command=self._hareket_sil
        ).pack(side="left", padx=6)
        ttk.Button(
            filtre, text="Kart eşleştirmesi gereken hareketler", command=self._eslesmesiz_sec
        ).pack(side="left", padx=10)
        self._yalniz_planli = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filtre,
            text="Yalnız planlı",
            variable=self._yalniz_planli,
            command=self._detay_yenile,
        ).pack(side="left", padx=8)

        self.orta = ttk.LabelFrame(
            self,
            text="KK hareketleri (kesin + planlı taksitler) — çift tık belge",
            padding=8,
        )
        self.orta.pack(fill="both", expand=True, padx=10, pady=6)
        cerceve = ttk.Frame(self.orta)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=(
                "tarih", "belge", "hesap", "kart", "tur", "taksit", "kesim",
                "tutar", "yon", "durum", "aciklama",
            ),
            show="headings",
        )
        for k, b, w in (
            ("tarih", "Yansıma", 85),
            ("belge", "Belge", 110),
            ("hesap", "Hesap", 120),
            ("kart", "Kart", 110),
            ("tur", "Hareket", 110),
            ("taksit", "Taksit", 55),
            ("kesim", "Ekstre kesim", 90),
            ("tutar", "Tutar", 85),
            ("yon", "Yön", 50),
            ("durum", "Durum", 70),
            ("aciklama", "Açıklama", 160),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="w")
        self.tablo.tag_configure("planli", foreground="#5a4a00")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        self.tablo.bind("<Double-1>", self._hareket_belge_ac)
        self._hareket_belge: dict[str, str] = {}
        # secim: None (ilk açılış) | "TUM" | "ESLEMESIZ" | int(kredi_karti_id)
        self._secim = self._acilis_kk_id
        self._yenile_no = 0
        self._kart_dolduruyor = False
        self._limit_poll_after = None
        self._limit_poll_imza = None
        self.protocol("WM_DELETE_WINDOW", self._kapat)
        self.listeyi_yenile()
        if self._acilis_kk_id and self.kart_tablo.exists(str(self._acilis_kk_id)):
            self._kart_dolduruyor = True
            try:
                self.kart_tablo.selection_set(str(self._acilis_kk_id))
                self.kart_tablo.see(str(self._acilis_kk_id))
                self._secim = self._acilis_kk_id
            finally:
                self._kart_dolduruyor = False
            self._detay_yenile()
        self._limit_poll_baslat()

    def _kapat(self):
        self._limit_poll_durdur()
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _limit_poll_baslat(self):
        self._limit_poll_durdur()
        # İlk tick gecikmeli: açılışı bloklamasın
        try:
            self._limit_poll_after = self.after(5000, self._limit_poll_tick)
        except Exception:
            self._limit_poll_after = None

    def _limit_poll_durdur(self):
        aid = getattr(self, "_limit_poll_after", None)
        if aid is not None:
            try:
                self.after_cancel(aid)
            except Exception:
                pass
        self._limit_poll_after = None

    def _limit_poll_tick(self):
        """Seçili kartın limit özetini seyrek yenile — tüm kartları her sn sorgulama."""
        if not self.winfo_exists():
            return
        try:
            from database.kredi_karti_ekstre_service import KrediKartiEkstreService

            kk_id = self._secili_kk_id()
            if kk_id:
                oz = KrediKartiEkstreService.kart_borc_ozeti(int(kk_id))
                imza = (
                    int(kk_id),
                    str(oz.get("kullanilan")),
                    str(oz.get("kullanilabilir")),
                    str(oz.get("limit")),
                )
                if self._limit_poll_imza is None:
                    self._limit_poll_imza = imza
                elif imza != self._limit_poll_imza:
                    self._limit_poll_imza = imza
                    self._detay_yenile()
        except Exception:
            if hasattr(self, "esleme_uyari"):
                self.esleme_uyari.configure(text="Limit özeti güncel değil (bağlantı/okuma hatası).")
        try:
            self._limit_poll_after = self.after(5000, self._limit_poll_tick)
        except Exception:
            self._limit_poll_after = None

    def _kk_hesap(self):
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            return None, None
        return kart, FinansService.banka_alt_hesap(kart, "KREDI_KARTI")

    def _har_filtre_temizle(self):
        self.har_bas.delete(0, "end")
        self.har_bit.delete(0, "end")
        self._detay_yenile()

    def _tarih_oku(self, widget):
        ham = (widget.get() or "").strip()
        if not ham:
            return None
        try:
            return datetime.strptime(ham, "%d.%m.%Y").date()
        except ValueError:
            messagebox.showerror("Tarih", "Tarih GG.AA.YYYY formatında olmalı.", parent=self)
            raise

    def _eslesmesiz_sec(self):
        self._kart_dolduruyor = True
        try:
            if self.kart_tablo.exists("__ESLEMESIZ__"):
                self.kart_tablo.selection_set("__ESLEMESIZ__")
                self.kart_tablo.see("__ESLEMESIZ__")
            self._secim = "ESLEMESIZ"
        finally:
            self._kart_dolduruyor = False
        self._detay_yenile()

    def _kart_secildi(self, _e=None):
        if self._kart_dolduruyor:
            return
        secim = self.kart_tablo.selection()
        if not secim:
            return
        iid = secim[0]
        if iid == "__TUM__":
            self._secim = "TUM"
        elif iid == "__ESLEMESIZ__":
            self._secim = "ESLEMESIZ"
        else:
            try:
                self._secim = int(iid)
            except ValueError:
                return
        self._detay_yenile()

    def listeyi_yenile(self):
        """Kart listesi + seçime göre özet/taksit/hareket yenile."""
        onceki = self._secim
        kart, hesap = self._kk_hesap()
        self._kart_dolduruyor = True
        try:
            for item in self.kart_tablo.get_children():
                self.kart_tablo.delete(item)
            if not kart:
                self.bakiye_lbl.configure(
                    text="Banka kartı bulunamadı.", fg=_bakiye_renk(0)
                )
                self.banka_toplam_lbl.configure(text="", fg=_bakiye_renk(0))
                self._kart_dolduruyor = False
                self._detay_yenile()
                return

            bakiyeler = FinansService.banka_bakiyeler_varlik(kart)
            banka_toplam = bakiyeler.get("KREDI_KARTI", Decimal("0"))
            hesap_adet = len(FinansService.kk_alt_hesaplari(kart, yer_tutucu_dahil=True))
            gercek_adet = len(FinansService.kk_alt_hesaplari(kart))
            self.banka_toplam_lbl.configure(
                text=(
                    f"Banka kredi kartları toplamı: {_para_bakiye(banka_toplam)}  ·  "
                    f"{gercek_adet} hesap"
                    + (
                        f" (+{hesap_adet - gercek_adet} yer tutucu)"
                        if hesap_adet > gercek_adet
                        else ""
                    )
                ),
                fg=_bakiye_renk(banka_toplam),
            )
            if not hesap and gercek_adet == 0:
                self.esleme_uyari.configure(
                    text="Bu bankada kredi kartı alt hesabı yok veya yalnız boş yer tutucu var."
                )
            else:
                self.esleme_uyari.configure(text="")

            from database.kredi_karti_ekstre_service import KrediKartiEkstreService

            self.kart_tablo.insert(
                "",
                "end",
                iid="__TUM__",
                values=(
                    "—",
                    "Tüm kartlar",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "Seçim",
                ),
            )
            kartlar = FinansService.kredi_kartlari(
                banka_karti_id=self.kart_id, aktif_only=False
            )
            for kk in kartlar:
                oz = KrediKartiEkstreService.kart_borc_ozeti(int(kk.id))
                kullanilan = oz.get("kullanilan")
                limit_ok = bool(oz.get("limit_tanimli"))
                limit = Decimal(str(oz.get("limit") or 0)) if limit_ok else Decimal("0")
                kalan = oz.get("kullanilabilir")
                maske = f"****{kk.son_dort_hane}" if kk.son_dort_hane else "—"
                tarihler = KrediKartiEkstreService.kart_tarih_ozeti(kk)
                self.kart_tablo.insert(
                    "",
                    "end",
                    iid=str(kk.id),
                    values=(
                        kk.kart_bankasi
                        or getattr(kk.banka_karti, "banka_adi", None)
                        or "—",
                        kk.kart_adi,
                        kk.kart_markasi or "—",
                        maske,
                        kk.son_kullanim or "—",
                        _para(limit) if limit_ok else "Limit tanımsız",
                        _para(kullanilan) if kullanilan is not None else "—",
                        _para(kalan) if limit_ok and kalan is not None else "—",
                        tarihler["son_kesim_metin"],
                        tarihler["sonraki_kesim_metin"],
                        tarihler["son_odeme_metin"],
                        "Aktif" if kk.aktif else "Pasif",
                    ),
                )
            # Açılışı bloklamamak için sayım limiti düşük; tam liste seçilince yüklenir
            eslesmesiz_n = len(
                FinansService.kredi_karti_hesap_hareketleri(
                    self.kart_id, yalniz_eslesmesiz=True, limit=50
                )
            )
            eslesmesiz_metin = (
                "Yok"
                if not eslesmesiz_n
                else (f"{eslesmesiz_n}+ adet" if eslesmesiz_n >= 50 else f"{eslesmesiz_n} adet")
            )
            self.kart_tablo.insert(
                "",
                "end",
                iid="__ESLEMESIZ__",
                values=(
                    "—",
                    "Kart eşleştirmesi gereken hareketler",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    "—",
                    eslesmesiz_metin,
                ),
            )

            hedef = onceki
            if isinstance(hedef, int) and self.kart_tablo.exists(str(hedef)):
                self.kart_tablo.selection_set(str(hedef))
                self._secim = hedef
            elif hedef == "ESLEMESIZ" and self.kart_tablo.exists("__ESLEMESIZ__"):
                self.kart_tablo.selection_set("__ESLEMESIZ__")
                self._secim = "ESLEMESIZ"
            elif hedef == "TUM":
                self.kart_tablo.selection_set("__TUM__")
                self._secim = "TUM"
            elif kartlar:
                # İlk açılış / bilinmeyen: tüm kartlar değil, ilk kart
                ilk = str(kartlar[0].id)
                self.kart_tablo.selection_set(ilk)
                self._secim = int(kartlar[0].id)
            else:
                self.kart_tablo.selection_set("__TUM__")
                self._secim = "TUM"
        finally:
            self._kart_dolduruyor = False

        self._detay_yenile()
        if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
            self.parent_dlg.bakiyeleri_yenile()

    def _detay_yenile(self):
        """Seçilen karta göre bakiye özeti, taksitler ve hareketleri birlikte yenile."""
        self._yenile_no += 1
        no = self._yenile_no
        for t in (self.taksit_tablo, self.tablo):
            for item in t.get_children():
                t.delete(item)
        self._hareket_belge.clear()
        self._taksit_odeme_map.clear()
        self._taksit_belge = getattr(self, "_taksit_belge", {})
        self._taksit_belge.clear()
        self._secili_odeme_id = None

        # Yenileme mali evrak üretmez; planlı taksitler birleşik listede görünür.

        kart, _hesap = self._kk_hesap()
        if not kart:
            self.bakiye_lbl.configure(text="Banka kartı bulunamadı.", fg=_bakiye_renk(0))
            return

        bakiyeler = FinansService.banka_bakiyeler_varlik(kart)
        banka_toplam = bakiyeler.get("KREDI_KARTI", Decimal("0"))
        self.banka_toplam_lbl.configure(
            text=f"Banka kredi kartları toplamı: {_para_bakiye(banka_toplam)}",
            fg=_bakiye_renk(banka_toplam),
        )

        secim = self._secim
        kk_filtre: int | None = None
        yalniz_eslesmesiz = False
        if secim == "ESLEMESIZ":
            yalniz_eslesmesiz = True
            self.orta.configure(text="Kart eşleştirmesi gereken hareketler — çift tık belge")
            self.bakiye_lbl.configure(
                text="Kart eşleştirmesi gereken hareketler (bağlı kart yok)",
                fg=_bakiye_renk(0),
            )
        elif secim == "TUM":
            self.orta.configure(
                text="Tüm kartlar — KK hesap hareketleri (tarihî dahil) — çift tık belge"
            )
            self.bakiye_lbl.configure(
                text=f"Tüm kartlar · Banka KK toplamı: {_para_bakiye(banka_toplam)}",
                fg=_bakiye_renk(banka_toplam),
            )
        else:
            kk_filtre = int(secim)
            from database.kredi_karti_ekstre_service import KrediKartiEkstreService

            lim = KrediKartiEkstreService.kart_borc_ozeti(kk_filtre)
            oz = FinansService.kredi_karti_isletme_bakiyesi(kk_filtre)
            ad = lim.get("kart_adi") or oz.get("kart_adi") or f"Kart #{kk_filtre}"
            bak = oz.get("bakiye")
            self.orta.configure(
                text=f"{ad} — hareketler (tarihî dahil) — çift tık belge"
            )
            # Üst özet: Kart Limiti / Kullanılan / Kullanılabilir (büyük-koyu)
            if lim.get("limit_tanimli"):
                kul_metin = _para(lim.get("kullanilabilir"))
                asim = lim.get("limit_asimi") or 0
                if asim > 0:
                    kul_metin += f"  |  Limit aşımı: {_para(asim)}"
                limit_blok = (
                    f"Kart Limiti: {_para(lim['limit'])}   ·   "
                    f"Kullanılan Limit: {_para(lim['kullanilan'])}   ·   "
                    f"Hesaplanan kullanılabilir limit: {kul_metin}"
                )
            else:
                limit_blok = (
                    f"Kart Limiti: Tanımlanmamış   ·   "
                    f"Kullanılan Limit: {_para(lim.get('kullanilan'))}   ·   "
                    f"Kullanılabilir: Tanımlanmamış"
                )
            bak_metin = (
                f"Hesap bakiyesi: {_para_bakiye(bak)}"
                if bak is not None
                else "Bağlı KK hesabı yok"
            )
            # Banka toplamı ile kart limiti ayrı
            self.bakiye_lbl.configure(
                text=f"{ad}\n{limit_blok}\n{bak_metin}",
                fg=_bakiye_renk(-(lim.get("kullanilan") or 0)),
                font=("Segoe UI", 12, "bold"),
                justify="left",
            )
            if lim.get("limit_uyari"):
                self.esleme_uyari.configure(text=lim["limit_uyari"])

        if no != self._yenile_no:
            return

        taksit_kk = None if secim in ("TUM", "ESLEMESIZ") else kk_filtre
        if secim != "ESLEMESIZ":
            for t in FinansService.kredi_karti_bekleyen_taksitler(
                self.kart_id, kredi_karti_id=taksit_kk
            ):
                if no != self._yenile_no:
                    return
                iid = f"t{t.get('taksit_id') or len(self._taksit_odeme_map)}"
                if t.get("odeme_id"):
                    self._taksit_odeme_map[iid] = int(t["odeme_id"])
                self._taksit_belge[iid] = (t.get("belge_no") or "").strip()
                self.taksit_tablo.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        t["belge_no"],
                        t["kart"],
                        f"{t['taksit_no']}/{t['taksit_sayisi']}",
                        _tarih(t.get("yansima_tarihi") or t["vade_tarihi"]),
                        _tarih(t.get("ekstre_kesim_tarihi")),
                        _tarih(t.get("son_odeme_tarihi") or t.get("banka_vade_tarihi")),
                        _para(t["tutar"]),
                    ),
                )

        try:
            bas = self._tarih_oku(self.har_bas)
            bit = self._tarih_oku(self.har_bit)
        except ValueError:
            return
        if no != self._yenile_no:
            return

        hareketler = FinansService.kredi_karti_birlesik_hareketler(
            self.kart_id,
            baslangic=bas,
            bitis=bit,
            kredi_karti_id=kk_filtre,
            yalniz_eslesmesiz=yalniz_eslesmesiz,
            planlilari_dahil=not yalniz_eslesmesiz,
            yalniz_planli=bool(self._yalniz_planli.get()),
        )
        if no != self._yenile_no:
            return

        eslesmesiz_n = 0
        if secim == "TUM":
            eslesmesiz_n = sum(1 for h in hareketler if h.get("esleme_bekliyor"))
            # Tüm kartlarda eşleşmiş hareketler ana listede; eşleşmesiz ayrı seçimde
            hareketler = [h for h in hareketler if not h.get("esleme_bekliyor")]

        self._hareket_planli = getattr(self, "_hareket_planli", {})
        self._hareket_planli.clear()
        for har in hareketler:
            if no != self._yenile_no:
                return
            yon = "Borç" if har["isaret"] > 0 else ("Alacak" if har["isaret"] < 0 else "—")
            planli = bool(har.get("planli"))
            iid = har.get("virtual_id") if planli else f"h{har['id']}"
            self._hareket_belge[iid] = har.get("belge_no") or ""
            self._hareket_planli[iid] = planli
            tk_metin = ""
            if har.get("taksit_no"):
                tk_metin = f"{har.get('taksit_no')}/{har.get('taksit_sayisi') or '?'}"
            self.tablo.insert(
                "",
                "end",
                iid=iid,
                tags=("planli",) if planli else (),
                values=(
                    _tarih(har["tarih"]),
                    har.get("belge_no") or "—",
                    har.get("hesap_adi") or ("— (plan)" if planli else "—"),
                    har.get("kart") or "—",
                    har.get("hareket_turu") or "—",
                    tk_metin or "—",
                    _tarih(har.get("ekstre_kesim_tarihi")) if planli else "—",
                    _para(har["tutar"]),
                    yon,
                    har.get("durum_etiket")
                    or ("Planlı" if planli else ("Eşleme gerekli" if har.get("esleme_bekliyor") else "Kesin")),
                    (har.get("aciklama") or "")[:80],
                ),
            )

        if secim == "ESLEMESIZ" and not hareketler:
            self.esleme_uyari.configure(text="Eşleme bekleyen hareket yok.")
        elif secim == "TUM" and eslesmesiz_n:
            self.esleme_uyari.configure(
                text=(
                    f"{eslesmesiz_n} hareket kart eşlemesi bekliyor — "
                    "«Kart eşleştirmesi gereken hareketler» satırından açın; "
                    "seçili karta rastgele bağlanmaz."
                )
            )
        elif isinstance(secim, int) and not hareketler:
            self.esleme_uyari.configure(
                text="Seçilen kartın bu tarih aralığında hareketi yok (başka kartın hareketleri getirilmez)."
            )
        else:
            if not (
                self.esleme_uyari.cget("text") or ""
            ).startswith("Bu bankada kredi kartı"):
                self.esleme_uyari.configure(text="")

    def _hareket_belge_ac(self, _e=None):
        secim = self.tablo.selection()
        if not secim:
            return
        belge = self._hareket_belge.get(secim[0]) or ""
        if not belge:
            messagebox.showinfo("Belge", "Bu satırda belge numarası yok.", parent=self)
            return
        from belge_onizleme_ui import finans_belge_ac

        tur = "FİNANS"
        if not finans_belge_ac(self, tur, belge):
            messagebox.showinfo(
                "Belge",
                f"Belge açılamadı: {belge}",
                parent=self,
            )
        self.listeyi_yenile()

    def _donem_borcu_raporu(self):
        """Seçili kart için Ekstre / Dönem Borcu Raporu (tüm kartlara uygulanır)."""
        kk_id = self._secim if isinstance(self._secim, int) else None
        if kk_id is None:
            messagebox.showinfo(
                "Ekstre / Dönem Borcu Raporu",
                "Önce listeden bir kredi kartı seçin.",
                parent=self,
            )
            return
        try:
            from kk_ekstre_ui import KkDonemBorcuRaporDialog

            KkDonemBorcuRaporDialog(self, int(kk_id), yenile_cb=self.listeyi_yenile)
        except Exception as exc:
            messagebox.showerror("Ekstre / Dönem Borcu Raporu", str(exc), parent=self)

    def _hareket_sil(self):
        """Seçili KK hesap hareketini id ile sil (hatalı/mükerrer; dengeleyen IPTAL dahil)."""
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("Sil", "Silmek için bir kart hareketi seçin.", parent=self)
            return
        if getattr(self, "_hareket_planli", {}).get(secim[0]):
            messagebox.showinfo(
                "Sil",
                "Planlı taksit satırı mali hareket değildir; silinemez. "
                "Kaynak belgeyi düzenleyin veya iptal edin.",
                parent=self,
            )
            return
        iid = secim[0]
        if not str(iid).startswith("h"):
            messagebox.showinfo("Sil", "Geçersiz satır.", parent=self)
            return
        try:
            hareket_id = int(str(iid)[1:])
        except ValueError:
            messagebox.showinfo("Sil", "Hareket kimliği okunamadı.", parent=self)
            return
        from database.kk_taksit_islem_service import (
            kredi_karti_hareket_sil,
            kredi_karti_hareket_sil_onizleme,
        )

        try:
            oniz = kredi_karti_hareket_sil_onizleme(hareket_id)
        except Exception as hata:
            messagebox.showerror("Sil", str(hata), parent=self)
            return
        if oniz.get("zaten_silinmis") or not oniz.get("bulundu"):
            messagebox.showinfo(
                "Sil",
                "Bu hareket zaten silinmiş; hesap bir kez etkilenir.",
                parent=self,
            )
            self.listeyi_yenile()
            return
        h = oniz.get("hareket") or {}
        satirlar = [
            f"Kart: {oniz.get('kart_adi') or '—'}",
            f"Kayıt id: {h.get('id')}",
            f"Belge: {h.get('belge_no') or '—'}",
            f"Tarih: {_tarih(h.get('tarih'))}",
            f"Tür: {h.get('hareket_turu') or '—'}",
            f"Tutar: {_para(h.get('tutar'))}",
        ]
        for b in oniz.get("bagli") or []:
            if b.get("tur") == "denge_iptal":
                satirlar.append(
                    f"Birlikte silinecek IPTAL: id={b.get('id')} · {b.get('belge_no')} · {_para(b.get('tutar'))}"
                )
            elif b.get("tur") == "denge_odeme":
                satirlar.append(
                    f"Birlikte silinecek ÖDEME: id={b.get('id')} · {b.get('belge_no')} · {_para(b.get('tutar'))}"
                )
            elif b.get("tur") == "taksit":
                satirlar.append(
                    f"Bağlı taksit: #{b.get('taksit_no')} (odeme {b.get('odeme_id')}) — {b.get('etki')}"
                )
            elif b.get("tur") == "ekstre_odeme":
                satirlar.append(
                    f"Ekstre ödeme bağı: {b.get('belge_no')} id={b.get('id')}"
                )
            elif b.get("tur") == "pos_banka_mutabakat":
                satirlar.append(
                    f"POS/banka mutabakat: {b.get('belge_no')} valor={b.get('pos_valor_id')}"
                )
        if oniz.get("engel"):
            messagebox.showwarning(
                "Silinemaz",
                "\n".join(satirlar + ["", "Engel:"] + list(oniz["engel"])),
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Kart hareketini sil",
            "\n".join(satirlar)
            + "\n\nSeçili hareket veritabanından silinsin mi?",
            parent=self,
        ):
            return
        try:
            sonuc = kredi_karti_hareket_sil(
                hareket_id,
                dengeleyen_dahil=True,
                neden="KK İşlemleri ekranı Sil",
            )
        except Exception as hata:
            messagebox.showerror("Sil", str(hata), parent=self)
            return
        if sonuc.get("zaten_silinmis"):
            messagebox.showinfo(
                "Sil",
                "Hareket zaten yoktu; hesaplar değişmedi.",
                parent=self,
            )
        else:
            messagebox.showinfo(
                "Silindi",
                f"Silinen kayıt id: {', '.join(str(i) for i in sonuc.get('silinen_idler') or [])}",
                parent=self,
            )
        self.listeyi_yenile()

    def _kart_tanim_ac(self):
        dialog = KrediKartiTanimDialog(self, self.kart_id)
        self.wait_window(dialog)
        if dialog.result:
            self.listeyi_yenile()

    def _kart_liste_ac(self):
        self._kart_duzenle_secili(zorunlu=False)

    def _kart_duzenle_secili(self, zorunlu=True):
        secim = self.kart_tablo.selection()
        if not secim or secim[0] in ("__TUM__", "__ESLEMESIZ__"):
            if zorunlu:
                messagebox.showinfo("Kart", "Düzenlemek için bir kart seçin.", parent=self)
            else:
                kartlar = FinansService.kredi_kartlari(
                    banka_karti_id=self.kart_id, aktif_only=False
                )
                if not kartlar:
                    messagebox.showinfo(
                        "Kart",
                        "Henüz tanımlı kart yok. Önce «Kredi Kartı Tanımla» ile ekleyin "
                        "veya KK eşlemesini çalıştırın. Hesap hareketleri yine de listelenir.",
                        parent=self,
                    )
                    return
                dialog = KrediKartiTanimDialog(self, self.kart_id, kart_id=kartlar[0].id)
                self.wait_window(dialog)
                if dialog.result:
                    self.listeyi_yenile()
            return
        dialog = KrediKartiTanimDialog(self, self.kart_id, kart_id=int(secim[0]))
        self.wait_window(dialog)
        if dialog.result:
            self.listeyi_yenile()

    def _kk_sec_zorunlu(self, kartlar, *, baslik: str, aciklama: str) -> int | None:
        """Seçili kart yoksa / «Tüm kartlar» ise işlem kartını seçtir."""
        kk_id = self._secili_kk_id()
        if kk_id is not None and any(int(k.id) == int(kk_id) for k in kartlar):
            return int(kk_id)
        if len(kartlar) == 1:
            return int(kartlar[0].id)

        secim_kutusu = tk.Toplevel(self)
        secim_kutusu.title(baslik)
        secim_kutusu.transient(self)
        secim_kutusu.grab_set()
        ttk.Label(secim_kutusu, text=aciklama, wraplength=420).pack(
            anchor="w", padx=12, pady=(12, 6)
        )
        etiketler = {
            f"{k.kart_adi or 'Kart'} · ****{k.son_dort_hane or '????'} (#{k.id})": int(k.id)
            for k in kartlar
        }
        deger = tk.StringVar(value=next(iter(etiketler)))
        cb = ttk.Combobox(
            secim_kutusu,
            textvariable=deger,
            values=list(etiketler.keys()),
            state="readonly",
            width=52,
        )
        cb.pack(fill="x", padx=12, pady=4)
        sonuc: dict[str, int | None] = {"id": None}

        def onay():
            sonuc["id"] = etiketler.get(deger.get())
            secim_kutusu.destroy()

        def iptal():
            sonuc["id"] = None
            secim_kutusu.destroy()

        alt = ttk.Frame(secim_kutusu, padding=10)
        alt.pack(fill="x")
        ttk.Button(alt, text="İptal", command=iptal).pack(side="right", padx=4)
        ttk.Button(alt, text="Seç", command=onay).pack(side="right", padx=4)
        secim_kutusu.bind("<Return>", lambda _e: onay())
        secim_kutusu.bind("<Escape>", lambda _e: iptal())
        self.wait_window(secim_kutusu)
        return sonuc["id"]

    def _odeme_ac(self):
        """Kredi Kartı Ekstre Ödeme Evrakı (V6) — taksitli harcama değil."""
        from kk_ekstre_ui import KkEkstreOdemeDialog
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        kartlar = FinansService.kredi_kartlari(banka_karti_id=self.kart_id)
        if not kartlar:
            messagebox.showwarning(
                "Kart gerekli",
                "Ödeme için önce bu bankaya en az bir kredi kartı tanımlayın.",
                parent=self,
            )
            return
        kk_id = self._kk_sec_zorunlu(
            kartlar,
            baslik="Kart seçin",
            aciklama="Ekstre ödemesi için işlem yapılacak kredi kartını seçin.",
        )
        if kk_id is None:
            return
        if not any(int(k.id) == int(kk_id) for k in kartlar):
            messagebox.showerror("Kart", "Seçilen kart bu bankaya ait değil.", parent=self)
            return
        acik = KrediKartiEkstreService.acik_ekstreler(int(kk_id))
        if not acik:
            messagebox.showinfo(
                "Ekstre Ödeme Evrakı",
                "Bu kartta ödenecek açık ekstre yok. Dönem borcu oluşunca veya "
                "ekstre aktarımından sonra tekrar deneyin.",
                parent=self,
            )
            return
        # Birden fazla açıksa kullanıcıya en eski (ilk) önerilir; detayda değiştirilebilir
        try:
            detay = KrediKartiEkstreService.ekstre_detay(int(acik[0]["ekstre_id"]))
            dlg = KkEkstreOdemeDialog(self, detay, yenile_cb=self.listeyi_yenile)
            self.wait_window(dlg)
        except Exception as exc:
            messagebox.showerror("Ekstre Ödeme Evrakı", str(exc), parent=self)
        self.listeyi_yenile()

    def _nakit_avans_ac(self):
        """Evraklar / Kartlar — Taksitli Nakit Avans (firmanın tüm banka kartları)."""
        from nakit_avans_ui import NakitAvansDialog

        # Tüm Kartlar görünümünde de kullanıcının seçtiği kart; liste firmanın tüm kartları
        kartlar = FinansService.kredi_kartlari(aktif_only=True)
        if not kartlar:
            messagebox.showwarning(
                "Kart gerekli",
                "Nakit avans için önce en az bir firma kredi kartı tanımlayın.",
                parent=self,
            )
            return
        kk_id = self._kk_sec_zorunlu(
            kartlar,
            baslik="Kart seçin",
            aciklama=(
                "Taksitli Nakit Avans seçili kart üzerinden yürütülür.\n"
                "«Tüm kartlar» görünümünde önce işlem kartını seçin; formda kart değiştirilebilir."
            ),
        )
        if kk_id is None:
            return
        kart = FinansService.kredi_karti_getir(int(kk_id))
        dlg = NakitAvansDialog(
            self,
            int(kk_id),
            kart_adi=(kart.kart_adi if kart else ""),
        )
        self.wait_window(dlg)
        self.listeyi_yenile()

    def _taksit_secildi(self, _e=None):
        sec = self.taksit_tablo.selection()
        if not sec:
            self._secili_odeme_id = None
            return
        self._secili_odeme_id = self._taksit_odeme_map.get(sec[0])

    def _taksit_belge_ac(self, _e=None):
        """Bekleyen taksit → kaynak evrak (NAV nakit avans veya KK ödeme belgesi)."""
        sec = self.taksit_tablo.selection()
        if not sec:
            return
        belge = (getattr(self, "_taksit_belge", {}) or {}).get(sec[0]) or ""
        if not belge:
            vals = self.taksit_tablo.item(sec[0], "values") or ()
            belge = (vals[0] if vals else "") or ""
        if not belge:
            messagebox.showinfo("Belge", "Bu taksit satırında kaynak belge yok.", parent=self)
            return
        from belge_onizleme_ui import finans_belge_ac

        if not finans_belge_ac(self, "FİNANS", belge):
            messagebox.showinfo("Belge", f"Belge açılamadı: {belge}", parent=self)
        self.listeyi_yenile()

    def _secili_kk_id(self):
        if isinstance(self._secim, int):
            return self._secim
        secim = self.kart_tablo.selection()
        if secim and secim[0] not in ("__TUM__", "__ESLEMESIZ__"):
            return int(secim[0])
        kartlar = FinansService.kredi_kartlari(banka_karti_id=self.kart_id)
        if len(kartlar) == 1:
            return int(kartlar[0].id)
        return None

    def _tarihleri_degistir(self):
        kk_id = self._secili_kk_id()
        if not kk_id:
            messagebox.showinfo(
                "Kart",
                "Tarihleri değiştirmek için listeden bir kredi kartı seçin.",
                parent=self,
            )
            return
        dialog = KartTarihleriDegistirDialog(self, kk_id)
        self.wait_window(dialog)
        if dialog.result:
            self.listeyi_yenile()

    def _tum_firma_kartlari(self):
        """Sınıf menüsüne geç — aynı kayıt kaynağı, tüm bankalar."""
        app = self.winfo_toplevel()
        # BankaAnaKartDialog içinden açıldıysa ana uygulamayı bul
        kok = getattr(self.parent_dlg, "master", None) or self.parent_dlg
        while kok is not None and not hasattr(kok, "_icerigi_temizle"):
            kok = getattr(kok, "master", None) or getattr(kok, "parent", None)
        hedef = kok if kok is not None and hasattr(kok, "_icerigi_temizle") else app
        self._limit_poll_durdur()
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass
        if hasattr(hedef, "_icerigi_temizle"):
            firma_kredi_kartlari_sayfasi_goster(hedef)
        else:
            messagebox.showinfo(
                "Firma Kredi Kartları",
                "Finans → Firma Kredi Kartları menüsünden tüm bankaların kartlarını açabilirsiniz.",
                parent=app,
            )


def _finans_app_kok(widget):
    """Menü sayfalarını açabilecek ana uygulama kökünü bul."""
    kok = widget
    while kok is not None and not hasattr(kok, "_icerigi_temizle"):
        kok = getattr(kok, "master", None) or getattr(kok, "parent", None)
    return kok


class KartTarihleriDegistirDialog(tk.Toplevel):
    """Gelecek kesim/ödeme kuralı veya açık ekstrenin gerçek son ödeme tarihi.

    Borç tutarı, ödemeler ve muhasebe fişine dokunmaz.
    """

    def __init__(self, parent, kredi_karti_id: int):
        super().__init__(parent)
        self.kredi_karti_id = int(kredi_karti_id)
        self.result = None
        kart = FinansService.kredi_karti_getir(self.kredi_karti_id)
        ad = (kart.kart_adi if kart else "") or f"#{self.kredi_karti_id}"
        self.title(f"Tarihleri değiştir — {ad}")
        self.geometry("560x520")
        self.minsize(520, 480)
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        self._svc = KrediKartiEkstreService
        ozet = self._svc.kart_tarih_ozeti(kart) if kart else {}

        ttk.Label(
            self,
            text="Yalnız tarihler değişir · Kart borcu ve muhasebe tutarı aynı kalır",
            foreground="#555",
        ).pack(anchor="w", padx=14, pady=(12, 4))

        ozet_f = ttk.LabelFrame(self, text="Güncel özet", padding=8)
        ozet_f.pack(fill="x", padx=14, pady=4)
        ttk.Label(
            ozet_f,
            text=(
                f"Son kesim: {ozet.get('son_kesim_metin', '—')}   ·   "
                f"Sonraki kesim: {ozet.get('sonraki_kesim_metin', '—')}   ·   "
                f"Son ödeme: {ozet.get('son_odeme_metin', '—')}"
            ),
        ).pack(anchor="w")

        self.mod = tk.StringVar(value="kural")
        mod_f = ttk.Frame(self)
        mod_f.pack(fill="x", padx=14, pady=6)
        ttk.Radiobutton(
            mod_f, text="Gelecek dönem kuralı", variable=self.mod, value="kural",
            command=self._mod_degisti,
        ).pack(side="left", padx=(0, 16))
        ttk.Radiobutton(
            mod_f, text="Açık ekstre son ödeme (banka bildirimi)", variable=self.mod, value="ekstre",
            command=self._mod_degisti,
        ).pack(side="left")

        self.kural_f = ttk.LabelFrame(self, text="Kesim / son ödeme günü (1-31)", padding=10)
        self.kural_f.pack(fill="x", padx=14, pady=4)
        ttk.Label(self.kural_f, text="Hesap kesim günü").grid(row=0, column=0, sticky="w", pady=3)
        self.kesim = ttk.Entry(self.kural_f, width=8)
        self.kesim.grid(row=0, column=1, sticky="w", padx=8, pady=3)
        ttk.Label(self.kural_f, text="Son ödeme günü").grid(row=1, column=0, sticky="w", pady=3)
        self.son_odeme = ttk.Entry(self.kural_f, width=8)
        self.son_odeme.grid(row=1, column=1, sticky="w", padx=8, pady=3)
        ttk.Label(self.kural_f, text="Kesimden sonra (gün)").grid(row=2, column=0, sticky="w", pady=3)
        self.kesimden_sonra = ttk.Entry(self.kural_f, width=8)
        self.kesimden_sonra.grid(row=2, column=1, sticky="w", padx=8, pady=3)
        ttk.Label(self.kural_f, text="Neden / banka belgesi").grid(row=3, column=0, sticky="w", pady=3)
        self.neden_kural = ttk.Entry(self.kural_f, width=40)
        self.neden_kural.grid(row=3, column=1, columnspan=2, sticky="ew", padx=8, pady=3)
        if kart:
            if kart.hesap_kesim_gunu:
                self.kesim.insert(0, str(kart.hesap_kesim_gunu))
            if kart.son_odeme_gunu:
                self.son_odeme.insert(0, str(kart.son_odeme_gunu))
            if getattr(kart, "kesimden_sonra_odeme_gun", None) is not None:
                self.kesimden_sonra.insert(0, str(kart.kesimden_sonra_odeme_gun))

        self.ekstre_f = ttk.LabelFrame(self, text="Açık ekstre — gerçek son ödeme", padding=10)
        self.ekstre_f.pack(fill="both", expand=True, padx=14, pady=4)
        self.ekstre_tablo = ttk.Treeview(
            self.ekstre_f,
            columns=("kesim", "son_odeme", "kalan", "aciklama"),
            show="headings",
            height=5,
        )
        for k, b, w in (
            ("kesim", "Kesim", 95),
            ("son_odeme", "Son ödeme", 95),
            ("kalan", "Kalan", 90),
            ("aciklama", "Açıklama", 180),
        ):
            self.ekstre_tablo.heading(k, text=b)
            self.ekstre_tablo.column(k, width=w, anchor="w")
        self.ekstre_tablo.pack(fill="both", expand=True)
        alt = ttk.Frame(self.ekstre_f)
        alt.pack(fill="x", pady=(8, 0))
        ttk.Label(alt, text="Yeni son ödeme").pack(side="left")
        self.yeni_son = ttk.Entry(alt, width=12)
        self.yeni_son.pack(side="left", padx=6)
        takvim_butonu(alt, self.yeni_son)
        ttk.Label(alt, text="Neden").pack(side="left", padx=(12, 0))
        self.neden_ekstre = ttk.Entry(alt, width=28)
        self.neden_ekstre.pack(side="left", padx=6)

        self.onizleme = ttk.Label(self, text="", foreground="#1a5276", wraplength=520)
        self.onizleme.pack(anchor="w", padx=14, pady=4)

        butonlar = ttk.Frame(self)
        butonlar.pack(fill="x", padx=14, pady=10)
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet ve uygula", command=self.kaydet).pack(side="right")
        ttk.Button(butonlar, text="Önizle", command=self._onizle).pack(side="right", padx=(0, 8))

        self._ekstreleri_yukle()
        self._mod_degisti()

    def _ekstreleri_yukle(self):
        for item in self.ekstre_tablo.get_children():
            self.ekstre_tablo.delete(item)
        for s in self._svc.acik_ekstreler(self.kredi_karti_id):
            self.ekstre_tablo.insert(
                "",
                "end",
                iid=str(s["ekstre_id"]),
                values=(
                    _tarih(s["kesim_tarihi"]),
                    _tarih(s["son_odeme_tarihi"]),
                    _para(s["kalan"]),
                    s.get("aciklama") or "—",
                ),
            )

    def _mod_degisti(self):
        kural_mi = self.mod.get() == "kural"
        state_k = "normal" if kural_mi else "disabled"
        state_e = "normal" if not kural_mi else "disabled"
        for w in (self.kesim, self.son_odeme, self.kesimden_sonra, self.neden_kural):
            w.configure(state=state_k)
        for w in (self.yeni_son, self.neden_ekstre):
            w.configure(state=state_e)
        self.ekstre_tablo.configure(selectmode="browse" if not kural_mi else "none")
        self._onizle()

    def _onizle(self):
        if self.mod.get() == "kural":
            self.onizleme.configure(
                text=(
                    f"Uygulanacak kural: kesim günü={self.kesim.get().strip() or '—'}, "
                    f"son ödeme günü={self.son_odeme.get().strip() or '—'}, "
                    f"kesim+N={self.kesimden_sonra.get().strip() or '—'}. "
                    "Kesinleşmiş ekstre tutarları değişmez; sonraki planlanan tarihler yenilenir."
                )
            )
            return
        secim = self.ekstre_tablo.selection()
        if not secim:
            self.onizleme.configure(
                text="Açık bir ekstre seçin ve bankanın bildirdiği yeni son ödeme tarihini girin."
            )
            return
        eski = self.ekstre_tablo.item(secim[0], "values")
        self.onizleme.configure(
            text=(
                f"Ekstre kesim {eski[0]}: son ödeme {eski[1]} → {self.yeni_son.get().strip() or '—'}; "
                f"kalan {eski[2]} aynı kalır, ödeme takvimi yeni aya taşınabilir."
            )
        )

    def kaydet(self):
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        try:
            if self.mod.get() == "kural":
                self.result = KrediKartiEkstreService.kart_tarih_kurali_guncelle(
                    self.kredi_karti_id,
                    hesap_kesim_gunu=self.kesim.get(),
                    son_odeme_gunu=self.son_odeme.get(),
                    kesimden_sonra_odeme_gun=self.kesimden_sonra.get(),
                    neden=self.neden_kural.get(),
                )
            else:
                secim = self.ekstre_tablo.selection()
                if not secim:
                    messagebox.showinfo("Ekstre", "Düzeltilecek açık ekstre seçin.", parent=self)
                    return
                ham = (self.yeni_son.get() or "").strip()
                if not ham:
                    messagebox.showerror("Tarih", "Yeni son ödeme tarihi girin.", parent=self)
                    return
                try:
                    yeni = datetime.strptime(ham, "%d.%m.%Y").date()
                except ValueError:
                    messagebox.showerror("Tarih", "Tarih GG.AA.YYYY biçiminde olmalıdır.", parent=self)
                    return
                self.result = KrediKartiEkstreService.ekstre_son_odeme_duzelt(
                    int(secim[0]),
                    yeni,
                    neden=self.neden_ekstre.get(),
                )
        except ValueError as hata:
            messagebox.showerror("Tarih", str(hata), parent=self)
            return
        messagebox.showinfo("Uygulandı", "Tarihler güncellendi. Listeler yenilenecek.", parent=self)
        self.destroy()


def _kullanilmayan_karti_sil(parent, tur: str, kart_id: int, yenile=None) -> bool:
    """Boş banka kartı veya firma kredi kartı tanımını siler. Geçmiş varsa somut engeli gösterir."""
    try:
        if tur == "BANKA":
            ozet = FinansService.banka_karti_kullanim_ozeti(int(kart_id))
        else:
            ozet = FinansService.kredi_karti_kullanim_ozeti(int(kart_id))
    except ValueError as hata:
        messagebox.showerror("Sil", str(hata), parent=parent)
        return False
    etiket = ozet.get("tur_etiket") or ("Banka Kartı" if tur == "BANKA" else "Firma Kredi Kartı")
    kod = ozet.get("kod") or "—"
    ad = ozet.get("ad") or "—"
    if not ozet.get("silinebilir"):
        mesaj = ozet.get("engel_mesaji") or f"«{etiket} — {kod} / {ad}» silinemez."
        messagebox.showerror("Silinemez", mesaj, parent=parent)
        return False
    ekstra = ""
    if ozet.get("teknik_eslestirme"):
        ekstra += (
            f"\n{ozet['teknik_eslestirme']} teknik Evo eşleştirmesi kapatılır; "
            "kaynak numarası ve silme nedeni denetim kaydında kalır."
        )
    if ozet.get("bos_kk_tanim"):
        ekstra += f"\n{ozet['bos_kk_tanim']} boş kredi kartı tanımı da silinir."
    if not messagebox.askyesno(
        "Sil",
        f"{etiket} «{kod} / {ad}» silinsin mi?\n"
        "Bu kartın hiçbir finansal hareketi yok.\n"
        "Yalnız seçilen kart silinir. Geçmişi olan kartlar için Pasif Yap durur."
        + ekstra,
        parent=parent,
    ):
        return False
    try:
        if tur == "BANKA":
            FinansService.banka_karti_sil(int(kart_id), onaylandi=True)
        else:
            FinansService.kredi_karti_sil(int(kart_id), onaylandi=True)
    except ValueError as hata:
        messagebox.showerror("Sil", str(hata), parent=parent)
        return False
    if callable(yenile):
        yenile()
    return True


class KrediKartiTanimDialog(tk.Toplevel):
    """Kredi Kartı Tanımı — Yeni / Düzenle (V4: limit, asgari, faiz, işlem butonları)."""

    MARKALAR = ("(Seçiniz)", "Visa", "Mastercard", "Troy", "Amex", "Diğer")
    _BASLIK = ("Segoe UI", 16, "bold")
    _ETIKET = ("Segoe UI", 12)
    _ALAN = ("Segoe UI", 12)
    _TUTAR = ("Segoe UI", 18, "bold")

    def __init__(self, parent, banka_karti_id, kart_id=None):
        super().__init__(parent)
        self.banka_karti_id = int(banka_karti_id)
        self.kart_id = int(kart_id) if kart_id else None
        self.result = None
        self._kirli = False
        self._faiz_esas = tk.StringVar(value="AYLIK")
        self.title("Kredi Kartı Tanımı" + (" — Düzenle" if self.kart_id else " — Yeni"))
        self.geometry("920x720")
        self.minsize(820, 600)
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        kart = FinansService.kredi_karti_getir(self.kart_id) if self.kart_id else None
        banka = FinansService.banka_karti_getir(self.banka_karti_id)
        varsayilan_banka = (banka.banka_adi if banka else "") or ""

        # --- kaydırılabilir gövde ---
        govde = ttk.Frame(self)
        govde.pack(fill="both", expand=True)
        canvas = tk.Canvas(govde, highlightthickness=0)
        sy = ttk.Scrollbar(govde, orient="vertical", command=canvas.yview)
        self._scroll = ttk.Frame(canvas)
        self._scroll.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        self._canvas_win = canvas.create_window((0, 0), window=self._scroll, anchor="nw")
        canvas.configure(yscrollcommand=sy.set)
        canvas.pack(side="left", fill="both", expand=True)
        sy.pack(side="right", fill="y")
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(self._canvas_win, width=e.width),
        )

        def _fare(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _fare)
        self.bind("<Destroy>", lambda _e: canvas.unbind_all("<MouseWheel>"), add="+")

        f = self._scroll
        pad = {"padx": 14, "pady": 4}
        try:
            st = ttk.Style(self)
            st.configure("KkTanim.TLabelframe.Label", font=self._BASLIK)
        except Exception:
            pass

        # A) Kart bilgileri
        a = ttk.LabelFrame(f, text="Kart Bilgileri", padding=12, style="KkTanim.TLabelframe")
        a.pack(fill="x", padx=12, pady=(12, 6))
        ttk.Label(a, text="Kartın bankası *", font=self._ETIKET).grid(row=0, column=0, sticky="w", **pad)
        self.kart_bankasi = ttk.Entry(a, width=36, font=self._ALAN)
        self.kart_bankasi.grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(a, text="Kart adı *", font=self._ETIKET).grid(row=1, column=0, sticky="w", **pad)
        self.kart_adi = ttk.Entry(a, width=36, font=self._ALAN)
        self.kart_adi.grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(a, text="Kart sahibi", font=self._ETIKET).grid(row=2, column=0, sticky="w", **pad)
        self.kart_sahibi = ttk.Entry(a, width=36, font=self._ALAN)
        self.kart_sahibi.grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(a, text="Kart markası", font=self._ETIKET).grid(row=3, column=0, sticky="w", **pad)
        self.kart_markasi = ttk.Combobox(a, values=self.MARKALAR, state="readonly", width=20, font=self._ALAN)
        self.kart_markasi.set("(Seçiniz)")
        self.kart_markasi.grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(a, text="Kart numarası", font=self._ETIKET).grid(row=4, column=0, sticky="w", **pad)
        self.kart_no = ttk.Entry(a, width=28, font=self._ALAN)
        self.kart_no.grid(row=4, column=1, sticky="w", **pad)
        ttk.Label(a, text="(**** son 4 hane listelenir · CVV yok)", foreground="#555").grid(
            row=4, column=2, sticky="w"
        )
        ttk.Label(a, text="Son kullanım (AA/YY)", font=self._ETIKET).grid(row=5, column=0, sticky="w", **pad)
        self.son_kullanim = ttk.Entry(a, width=10, font=self._ALAN)
        self.son_kullanim.grid(row=5, column=1, sticky="w", **pad)
        ttk.Label(a, text="Para birimi", font=self._ETIKET).grid(row=6, column=0, sticky="w", **pad)
        self.para_birimi = ttk.Combobox(a, values=("TRY", "USD", "EUR"), width=8, state="readonly", font=self._ALAN)
        self.para_birimi.set("TRY")
        self.para_birimi.grid(row=6, column=1, sticky="w", **pad)
        ttk.Label(a, text="Açıklama", font=self._ETIKET).grid(row=7, column=0, sticky="w", **pad)
        self.aciklama = ttk.Entry(a, width=48, font=self._ALAN)
        self.aciklama.grid(row=7, column=1, columnspan=2, sticky="ew", **pad)
        ttk.Label(a, text="Banka ürün türü", font=self._ETIKET).grid(row=8, column=0, sticky="w", **pad)
        self.urun_turu = ttk.Combobox(
            a, values=("(Seçiniz)", "BIREYSEL", "TICARI", "KURUMSAL"), state="readonly", width=16, font=self._ALAN
        )
        self.urun_turu.set("(Seçiniz)")
        self.urun_turu.grid(row=8, column=1, sticky="w", **pad)
        ttk.Label(a, text="Varsayılan taksit (1–12)", font=self._ETIKET).grid(row=9, column=0, sticky="w", **pad)
        self.varsayilan_taksit = ttk.Combobox(
            a, values=[str(i) for i in range(1, 13)], state="readonly", width=6, font=self._ALAN
        )
        self.varsayilan_taksit.set("6")
        self.varsayilan_taksit.grid(row=9, column=1, sticky="w", **pad)

        # B) Limit ve özet
        b = ttk.LabelFrame(f, text="Limit ve Özet", padding=12, style="KkTanim.TLabelframe")
        b.pack(fill="x", padx=12, pady=6)
        ttk.Label(b, text="Kart limiti", font=self._ETIKET).grid(row=0, column=0, sticky="w", **pad)
        self.limit = ttk.Entry(b, width=16, font=self._ALAN)
        self.limit.grid(row=0, column=1, sticky="w", **pad)
        self.ozet_lbl = tk.Label(
            b, text="", font=self._TUTAR, justify="left", anchor="w", fg="#0d2137"
        )
        self.ozet_lbl.grid(row=1, column=0, columnspan=3, sticky="ew", padx=8, pady=8)

        # C) Vade ve asgari
        c = ttk.LabelFrame(f, text="Vade ve Asgari Ödeme", padding=12, style="KkTanim.TLabelframe")
        c.pack(fill="x", padx=12, pady=6)
        ttk.Label(c, text="Hesap kesim günü (1-31)", font=self._ETIKET).grid(row=0, column=0, sticky="w", **pad)
        self.kesim = ttk.Entry(c, width=8, font=self._ALAN)
        self.kesim.grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(c, text="Son ödeme günü (1-31)", font=self._ETIKET).grid(row=1, column=0, sticky="w", **pad)
        self.son_odeme = ttk.Entry(c, width=8, font=self._ALAN)
        self.son_odeme.grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(c, text="Kesimden sonra ödeme (gün)", font=self._ETIKET).grid(row=2, column=0, sticky="w", **pad)
        self.kesimden_sonra = ttk.Entry(c, width=8, font=self._ALAN)
        self.kesimden_sonra.grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(c, text="Ödeme vadesi yöntemi", font=self._ETIKET).grid(row=3, column=0, sticky="w", **pad)
        self.vade_yontem = ttk.Combobox(
            c, values=("KESIM_ARTI_N", "AYIN_GUNU"), state="readonly", width=16, font=self._ALAN
        )
        self.vade_yontem.set("KESIM_ARTI_N")
        self.vade_yontem.grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(c, text="Asgari oran %", font=self._ETIKET).grid(row=4, column=0, sticky="w", **pad)
        self.asgari_oran = ttk.Entry(c, width=12, font=self._ALAN)
        self.asgari_oran.grid(row=4, column=1, sticky="w", **pad)
        ttk.Label(c, text="Asgari kaynak", font=self._ETIKET).grid(row=5, column=0, sticky="w", **pad)
        self.asgari_kaynak = ttk.Entry(c, width=36, font=self._ALAN)
        self.asgari_kaynak.grid(row=5, column=1, sticky="w", **pad)
        ttk.Label(c, text="Asgari geçerlilik (GG.AA.YYYY)", font=self._ETIKET).grid(
            row=6, column=0, sticky="w", **pad
        )
        self.asgari_gecerlilik = ttk.Entry(c, width=14, font=self._ALAN)
        self.asgari_gecerlilik.grid(row=6, column=1, sticky="w", **pad)
        self.asgari_ozet_lbl = tk.Label(c, text="", font=self._TUTAR, justify="left", anchor="w", fg="#0d2137")
        self.asgari_ozet_lbl.grid(row=7, column=0, columnspan=3, sticky="ew", padx=8, pady=8)

        # D) Faiz
        d = ttk.LabelFrame(f, text="Faiz Ayarları (akdi / gecikme)", padding=12, style="KkTanim.TLabelframe")
        d.pack(fill="x", padx=12, pady=6)
        ttk.Label(d, text="Giriş esası", font=self._ETIKET).grid(row=0, column=0, sticky="w", **pad)
        ttk.Radiobutton(d, text="Aylık → yıllık×12", variable=self._faiz_esas, value="AYLIK",
                        command=self._faiz_esas_degisti).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(d, text="Yıllık → aylık/12", variable=self._faiz_esas, value="YILLIK",
                        command=self._faiz_esas_degisti).grid(row=0, column=2, sticky="w")
        ttk.Label(d, text="Akdi faiz aylık %", font=self._ETIKET).grid(row=1, column=0, sticky="w", **pad)
        self.akdi_aylik = ttk.Entry(d, width=10, font=self._ALAN)
        self.akdi_aylik.grid(row=1, column=1, sticky="w", **pad)
        ttk.Label(d, text="Akdi yıllık nominal %", font=self._ETIKET).grid(row=1, column=2, sticky="w", **pad)
        self.akdi_yillik = ttk.Entry(d, width=10, font=self._ALAN)
        self.akdi_yillik.grid(row=1, column=3, sticky="w", **pad)
        ttk.Label(d, text="Gecikme aylık %", font=self._ETIKET).grid(row=2, column=0, sticky="w", **pad)
        self.gecikme_aylik = ttk.Entry(d, width=10, font=self._ALAN)
        self.gecikme_aylik.grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(d, text="Gecikme yıllık nominal %", font=self._ETIKET).grid(row=2, column=2, sticky="w", **pad)
        self.gecikme_yillik = ttk.Entry(d, width=10, font=self._ALAN)
        self.gecikme_yillik.grid(row=2, column=3, sticky="w", **pad)
        ttk.Label(d, text="Oran geçerlilik (GG.AA.YYYY)", font=self._ETIKET).grid(
            row=3, column=0, sticky="w", **pad
        )
        self.faiz_gecerlilik = ttk.Entry(d, width=14, font=self._ALAN)
        self.faiz_gecerlilik.grid(row=3, column=1, sticky="w", **pad)
        self.oto_faiz = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            d, text="Otomatik faiz tahakkuku (doğrulanmış profil gerekir)", variable=self.oto_faiz
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=6)
        ttk.Label(
            d,
            text="Eksik oran «Tanımlanmadı»dır; form açmak faiz tahakkuku üretmez.",
            foreground="#555",
        ).grid(row=5, column=0, columnspan=4, sticky="w")
        for w in (self.akdi_aylik, self.akdi_yillik, self.gecikme_aylik, self.gecikme_yillik):
            w.bind("<FocusOut>", lambda _e: self._faiz_donustur())
            w.bind("<KeyRelease>", lambda _e: self._isaret_kirli())

        # E) İşlem butonları
        e = ttk.LabelFrame(f, text="İşlemler (bu kart)", padding=12, style="KkTanim.TLabelframe")
        e.pack(fill="x", padx=12, pady=6)
        self._islem_fr = e
        self.btn_taksitli = ttk.Button(e, text="Taksitli Harcama", command=self._taksitli_harcama)
        self.btn_taksitli.pack(side="left", padx=4)
        self.btn_nakit_avans = ttk.Button(e, text="Taksitli Nakit Avans", command=self._nakit_avans)
        self.btn_nakit_avans.pack(side="left", padx=4)
        self.btn_plan = ttk.Button(e, text="Taksit Planını Düzenle", command=self._plan_duzenle)
        self.btn_plan.pack(side="left", padx=4)
        self.btn_odeme = ttk.Button(e, text="Karta Ödeme Kaydet", command=self._karta_odeme)
        self.btn_odeme.pack(side="left", padx=4)
        self.btn_ekstre = ttk.Button(e, text="Hesap Ekstresi", command=self._hesap_ekstresi)
        self.btn_ekstre.pack(side="left", padx=4)
        ttk.Label(
            e,
            text="Yeni / kaydedilmemiş kartta mali işlem açılamaz. Kaydedilmemiş ayar değişiklikleri işlemde kullanılmaz.",
            foreground="#555",
        ).pack(anchor="w", pady=(8, 0))

        # Alt Kaydet / İptal
        alt = ttk.Frame(self, padding=10)
        alt.pack(fill="x")
        if kart:
            ttk.Button(alt, text="Pasif Yap", command=self._pasif).pack(side="left", padx=(0, 6))
            ttk.Button(alt, text="Sil", command=self._sil).pack(side="left", padx=(0, 6))
            ttk.Button(alt, text="Tarihleri değiştir…", command=self._tarihleri_degistir).pack(
                side="left", padx=(0, 12)
            )
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(alt, text="Kaydet", command=self.kaydet).pack(side="right")

        # Doldur
        if kart:
            self.kart_bankasi.insert(0, kart.kart_bankasi or varsayilan_banka)
            self.kart_adi.insert(0, kart.kart_adi or "")
            self.kart_sahibi.insert(0, kart.kart_sahibi or "")
            if kart.kart_markasi:
                self.kart_markasi.set(kart.kart_markasi)
            if kart.kart_numarasi:
                no = kart.kart_numarasi
                self.kart_no.insert(0, " ".join(no[i : i + 4] for i in range(0, len(no), 4)))
            self.son_kullanim.insert(0, kart.son_kullanim or "")
            self.limit.insert(0, str(kart.kart_limiti or 0))
            if kart.hesap_kesim_gunu:
                self.kesim.insert(0, str(kart.hesap_kesim_gunu))
            if kart.son_odeme_gunu:
                self.son_odeme.insert(0, str(kart.son_odeme_gunu))
            if getattr(kart, "kesimden_sonra_odeme_gun", None):
                self.kesimden_sonra.insert(0, str(kart.kesimden_sonra_odeme_gun))
            if getattr(kart, "para_birimi", None):
                self.para_birimi.set(kart.para_birimi)
            self.aciklama.insert(0, kart.aciklama or "")
            tur = getattr(kart, "banka_urun_turu", None)
            if tur:
                self.urun_turu.set(tur)
            if getattr(kart, "odeme_vade_yontemi", None):
                self.vade_yontem.set(kart.odeme_vade_yontemi)
            if getattr(kart, "asgari_oran_yuzde", None) is not None:
                self.asgari_oran.insert(0, str(kart.asgari_oran_yuzde).replace(".", ","))
            if getattr(kart, "asgari_kaynak", None):
                self.asgari_kaynak.insert(0, kart.asgari_kaynak)
            if getattr(kart, "asgari_gecerlilik", None):
                self.asgari_gecerlilik.insert(0, kart.asgari_gecerlilik.strftime("%d.%m.%Y"))
            self.oto_faiz.set(bool(getattr(kart, "otomatik_faiz_tahakkuku", False)))
            vt = getattr(kart, "varsayilan_taksit_adet", None) or 6
            self.varsayilan_taksit.set(str(int(vt)))
            self._faiz_doldur()
            self._ozet_yenile()
            self._islem_butonlari_durum(True)
        else:
            self.kart_bankasi.insert(0, varsayilan_banka)
            self.limit.insert(0, "0")
            self.ozet_lbl.configure(text="Kart kaydedilince limit / borç özeti görünür.")
            self.asgari_ozet_lbl.configure(text="Asgari: Tanımlanmadı")
            self._islem_butonlari_durum(False)

        for w in (
            self.kart_bankasi, self.kart_adi, self.kart_sahibi, self.kart_no, self.son_kullanim,
            self.limit, self.kesim, self.son_odeme, self.kesimden_sonra, self.aciklama,
            self.asgari_oran, self.asgari_kaynak, self.asgari_gecerlilik, self.faiz_gecerlilik,
        ):
            w.bind("<KeyRelease>", lambda _e: self._isaret_kirli())
        for w in (
            self.kart_markasi, self.para_birimi, self.urun_turu, self.varsayilan_taksit, self.vade_yontem,
        ):
            w.bind("<<ComboboxSelected>>", lambda _e: self._isaret_kirli())
        self.oto_faiz.trace_add("write", lambda *_a: self._isaret_kirli())

    def _isaret_kirli(self):
        self._kirli = True

    def _islem_butonlari_durum(self, aktif: bool):
        st = ("!disabled",) if aktif else ("disabled",)
        for b in (self.btn_taksitli, self.btn_nakit_avans, self.btn_plan, self.btn_odeme, self.btn_ekstre):
            b.state(st)

    def _kayit_gerekli(self, baslik: str) -> bool:
        if not self.kart_id:
            messagebox.showinfo(
                baslik,
                "Önce kartı Kaydet ile kaydedin; sonra mali işlem açılabilir.",
                parent=self,
            )
            return False
        if self._kirli:
            messagebox.showinfo(
                baslik,
                "Kart ayarlarında kaydedilmemiş değişiklik var. Önce Kaydet’e basın "
                "veya İptal ile kapatıp yeniden açın. İşlem sessizce eski ayarı kullanmaz.",
                parent=self,
            )
            return False
        return True

    def _ozet_yenile(self):
        if not self.kart_id:
            return
        try:
            from database.kredi_karti_ekstre_service import KrediKartiEkstreService

            oz = KrediKartiEkstreService.kart_borc_ozeti(int(self.kart_id))
            tarihler = KrediKartiEkstreService.kart_tarih_ozeti(
                FinansService.kredi_karti_getir(self.kart_id)
            )
            if oz.get("limit_tanimli"):
                lim = _para(oz.get("limit"))
                kul = _para(oz.get("kullanilan"))
                kal = _para(oz.get("kullanilabilir"))
            else:
                lim = kul = kal = "Tanımlanmadı"
            self.ozet_lbl.configure(
                text=(
                    f"Limit: {lim}   ·   Kullanılan: {kul}   ·   "
                    f"Hesaplanan kullanılabilir: {kal}\n"
                    f"Toplam borç: {_para(oz.get('toplam_borc'))}   ·   "
                    f"Bu dönem kalan: {_para(oz.get('kesilmis_kalan'))}"
                )
            )
            asg = oz.get("asgari_tutar")
            asg_od = oz.get("asgari_odenen")
            if asg is None and getattr(
                FinansService.kredi_karti_getir(self.kart_id), "asgari_oran_yuzde", None
            ) is None:
                asg_metin = "Asgari: Tanımlanmadı"
            elif asg is None:
                asg_metin = (
                    f"Asgari oran tanımlı · dönem tutarı henüz yok · "
                    f"Son ödeme: {tarihler.get('son_odeme_metin') or '—'}"
                )
            else:
                kalan_asg = max(Decimal(str(asg)) - Decimal(str(asg_od or 0)), Decimal("0"))
                asg_metin = (
                    f"Dönem asgari: {_para(asg)}   ·   Kalan asgari: {_para(kalan_asg)}\n"
                    f"Son ödeme: {tarihler.get('son_odeme_metin') or '—'}"
                )
            self.asgari_ozet_lbl.configure(text=asg_metin)
        except Exception as exc:
            self.ozet_lbl.configure(text=f"Özet okunamadı (sıfırlanmadı): {exc}")

    def _faiz_doldur(self):
        if not self.kart_id:
            return
        try:
            from database.gunluk_faiz_service import GunlukFaizService

            for tur, aylik_w, yillik_w in (
                ("AKDI", self.akdi_aylik, self.akdi_yillik),
                ("GECIKME", self.gecikme_aylik, self.gecikme_yillik),
            ):
                oran = GunlukFaizService.aktif_oran("KK", int(self.kart_id), tur)
                aylik_w.delete(0, "end")
                yillik_w.delete(0, "end")
                if not oran:
                    continue
                val = Decimal(str(oran.oran_yuzde))
                if (oran.donem or "").upper() == "AYLIK":
                    aylik_w.insert(0, f"{val:.4f}".rstrip("0").rstrip(".").replace(".", ","))
                    yillik_w.insert(0, f"{(val * 12):.4f}".rstrip("0").rstrip(".").replace(".", ","))
                    self._faiz_esas.set("AYLIK")
                else:
                    yillik_w.insert(0, f"{val:.4f}".rstrip("0").rstrip(".").replace(".", ","))
                    aylik_w.insert(0, f"{(val / 12):.4f}".rstrip("0").rstrip(".").replace(".", ","))
                    self._faiz_esas.set("YILLIK")
                if oran.baslangic_tarihi and not self.faiz_gecerlilik.get().strip():
                    self.faiz_gecerlilik.insert(0, oran.baslangic_tarihi.strftime("%d.%m.%Y"))
        except Exception:
            pass
        self._faiz_esas_degisti()

    def _faiz_esas_degisti(self):
        esas = self._faiz_esas.get()
        if esas == "AYLIK":
            self.akdi_aylik.configure(state="normal")
            self.gecikme_aylik.configure(state="normal")
            self.akdi_yillik.configure(state="readonly")
            self.gecikme_yillik.configure(state="readonly")
        else:
            self.akdi_yillik.configure(state="normal")
            self.gecikme_yillik.configure(state="normal")
            self.akdi_aylik.configure(state="readonly")
            self.gecikme_aylik.configure(state="readonly")
        self._faiz_donustur()

    def _oran_oku(self, widget) -> Decimal | None:
        ham = (widget.get() or "").strip().replace(",", ".")
        if not ham:
            return None
        try:
            return Decimal(ham)
        except Exception:
            return None

    def _faiz_donustur(self):
        esas = self._faiz_esas.get()
        if esas == "AYLIK":
            for a, y in ((self.akdi_aylik, self.akdi_yillik), (self.gecikme_aylik, self.gecikme_yillik)):
                v = self._oran_oku(a)
                y.configure(state="normal")
                y.delete(0, "end")
                if v is not None:
                    y.insert(0, f"{(v * 12):.4f}".rstrip("0").rstrip(".").replace(".", ","))
                y.configure(state="readonly")
        else:
            for a, y in ((self.akdi_aylik, self.akdi_yillik), (self.gecikme_aylik, self.gecikme_yillik)):
                v = self._oran_oku(y)
                a.configure(state="normal")
                a.delete(0, "end")
                if v is not None:
                    a.insert(0, f"{(v / 12):.4f}".rstrip("0").rstrip(".").replace(".", ","))
                a.configure(state="readonly")

    def _faiz_kaydet(self, kart_id: int):
        from database.gunluk_faiz_service import GunlukFaizService

        esas = self._faiz_esas.get()
        bas = None
        ham = (self.faiz_gecerlilik.get() or "").strip()
        if ham:
            try:
                bas = datetime.strptime(ham, "%d.%m.%Y").date()
            except ValueError as exc:
                raise ValueError("Faiz geçerlilik GG.AA.YYYY olmalıdır.") from exc
        for tur, aylik_w, yillik_w in (
            ("AKDI", self.akdi_aylik, self.akdi_yillik),
            ("GECIKME", self.gecikme_aylik, self.gecikme_yillik),
        ):
            if esas == "AYLIK":
                oran = self._oran_oku(aylik_w)
                donem = "AYLIK"
            else:
                oran = self._oran_oku(yillik_w)
                donem = "YILLIK"
            if oran is None:
                continue
            if oran < 0 or oran > 1000:
                raise ValueError(f"{tur} oranı geçersiz.")
            GunlukFaizService.oran_kaydet(
                urun_turu="KK",
                urun_id=int(kart_id),
                faiz_turu=tur,
                oran_yuzde=oran,
                donem=donem,
                baslangic_tarihi=bas,
                kaynak_not="Kart tanım formu",
            )

    def _nakit_avans(self):
        if not self._kayit_gerekli("Nakit Avans"):
            return
        from nakit_avans_ui import NakitAvansDialog

        kart = FinansService.kredi_karti_getir(self.kart_id)
        NakitAvansDialog(self, int(self.kart_id), kart_adi=(kart.kart_adi if kart else ""))

    def _taksitli_harcama(self):
        if not self._kayit_gerekli("Taksitli Harcama"):
            return
        dlg = KrediKartiOdemeDialog(self, self.banka_karti_id)
        for etiket, kid in getattr(dlg, "_kart_map", {}).items():
            if int(kid) == int(self.kart_id):
                dlg.kart.set(etiket)
                break
        dlg.cekim.set("Taksitli Çekim")
        dlg._cekim_degisti()
        dlg.taksit.set(self.varsayilan_taksit.get() or "6")
        try:
            dlg._kart_degisti()
        except Exception:
            pass
        self.wait_window(dlg)
        if dlg.result:
            self._ozet_yenile()

    def _plan_duzenle(self):
        if not self._kayit_gerekli("Taksit Planını Düzenle"):
            return
        odemeler = [
            o for o in FinansService.kredi_karti_odemeleri(banka_karti_id=self.banka_karti_id, limit=300)
            if int(o.get("kredi_karti_id") or 0) == int(self.kart_id)
            and (o.get("durum") or "").upper() == "AÇIK"
        ]
        if not odemeler:
            messagebox.showinfo(
                "Taksit Planını Düzenle",
                "Bu karta ait düzenlenebilir açık plan yok.",
                parent=self,
            )
            return
        secim_dlg = tk.Toplevel(self)
        secim_dlg.title("Plan seç")
        secim_dlg.geometry("480x320")
        secim_dlg.transient(self)
        secim_dlg.grab_set()
        ttk.Label(secim_dlg, text="Bu kartın açık harcama planı", font=self._ETIKET).pack(
            anchor="w", padx=12, pady=8
        )
        lb = tk.Listbox(secim_dlg, font=self._ALAN, height=10)
        lb.pack(fill="both", expand=True, padx=12)
        id_map = []
        for o in odemeler:
            id_map.append(int(o["id"]))
            lb.insert(
                "end",
                f"{o.get('belge_no')} · {_tarih(o.get('tarih'))} · {_para(o.get('tutar'))} · "
                f"{o.get('taksit_sayisi')} taksit",
            )
        if id_map:
            lb.selection_set(0)

        def _ac():
            secim = lb.curselection()
            if not secim:
                return
            oid = id_map[int(secim[0])]
            secim_dlg.destroy()
            from firma_kk_calisma_ui import TaksitPlaniniDuzenleDialog

            dlg = TaksitPlaniniDuzenleDialog(self, oid)
            self.wait_window(dlg)
            if dlg.result:
                self._ozet_yenile()

        ttk.Button(secim_dlg, text="Düzenle", command=_ac).pack(side="right", padx=12, pady=8)
        ttk.Button(secim_dlg, text="İptal", command=secim_dlg.destroy).pack(side="right")

    def _karta_odeme(self):
        if not self._kayit_gerekli("Karta Ödeme"):
            return
        from kk_ekstre_ui import KkEkstreOdemeDialog
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        acik = KrediKartiEkstreService.acik_ekstreler(int(self.kart_id))
        if not acik:
            messagebox.showinfo(
                "Karta Ödeme",
                "Ödenecek açık ekstre yok. Önce dönem borcu oluşmalı.",
                parent=self,
            )
            return
        try:
            detay = KrediKartiEkstreService.ekstre_detay(int(acik[0]["ekstre_id"]))
            dlg = KkEkstreOdemeDialog(self, detay, yenile_cb=self._ozet_yenile)
            self.wait_window(dlg)
        except Exception as exc:
            messagebox.showerror("Karta Ödeme", str(exc), parent=self)
        self._ozet_yenile()

    def _hesap_ekstresi(self):
        if not self._kayit_gerekli("Hesap Ekstresi"):
            return
        from tkinter import filedialog
        import os
        import tempfile
        from pathlib import Path
        from database.kk_ekstre_rapor_service import (
            rapor_verisi,
            pdf_kaydet,
            excel_kaydet,
            email_icin_hazirla,
        )
        from kk_ekstre_ui import KkEkstreDetayDialog
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        acik = KrediKartiEkstreService.acik_ekstreler(int(self.kart_id))
        ekstre_id = int(acik[0]["ekstre_id"]) if acik and acik[0].get("ekstre_id") else None
        if ekstre_id:
            try:
                KkEkstreDetayDialog(
                    self, {"ekstre_id": ekstre_id}, yenile_cb=self._ozet_yenile
                )
            except Exception:
                pass
        try:
            rapor = rapor_verisi(int(self.kart_id), ekstre_id=ekstre_id)
        except Exception as exc:
            messagebox.showerror("Hesap Ekstresi", str(exc), parent=self)
            return

        sec = tk.StringVar(value="pdf")
        dlg = tk.Toplevel(self)
        dlg.title("Hesap Ekstresi — çıktı")
        dlg.geometry("380x240")
        dlg.transient(self)
        dlg.grab_set()
        ttk.Label(dlg, text="Çıktı türü", font=self._BASLIK).pack(anchor="w", padx=14, pady=(12, 6))
        for val, etiket in (
            ("pdf", "PDF Kaydet"),
            ("excel", "Excel Kaydet"),
            ("yazdir", "Yazdır"),
            ("email", "E-posta İçin Hazırla"),
        ):
            ttk.Radiobutton(dlg, text=etiket, variable=sec, value=val).pack(anchor="w", padx=18, pady=2)

        def _uygula():
            tur = sec.get()
            dlg.destroy()
            try:
                if tur == "pdf":
                    yol = filedialog.asksaveasfilename(
                        parent=self, defaultextension=".pdf",
                        initialfile=f"{rapor['dosya_kok']}.pdf", filetypes=[("PDF", "*.pdf")],
                    )
                    if yol:
                        pdf_kaydet(rapor, yol)
                        messagebox.showinfo("PDF", f"Kaydedildi:\n{yol}", parent=self)
                elif tur == "excel":
                    yol = filedialog.asksaveasfilename(
                        parent=self, defaultextension=".xlsx",
                        initialfile=f"{rapor['dosya_kok']}.xlsx", filetypes=[("Excel", "*.xlsx")],
                    )
                    if yol:
                        excel_kaydet(rapor, yol)
                        messagebox.showinfo("Excel", f"Kaydedildi:\n{yol}", parent=self)
                elif tur == "yazdir":
                    tmp = Path(tempfile.gettempdir()) / f"{rapor['dosya_kok']}.pdf"
                    pdf_kaydet(rapor, tmp)
                    os.startfile(str(tmp), "print")  # noqa: S606
                else:
                    klasor = filedialog.askdirectory(parent=self, title="E-posta ekleri klasörü")
                    if klasor:
                        yollar = email_icin_hazirla(rapor, klasor)
                        messagebox.showinfo(
                            "E-posta",
                            "Dosyalar hazırlandı (otomatik gönderim yok):\n"
                            f"PDF: {yollar['pdf']}\nExcel: {yollar['excel']}",
                            parent=self,
                        )
            except Exception as exc:
                messagebox.showerror("Hesap Ekstresi", str(exc), parent=self)

        btn = ttk.Frame(dlg, padding=10)
        btn.pack(fill="x")
        ttk.Button(btn, text="Tamam", command=_uygula).pack(side="right", padx=4)
        ttk.Button(btn, text="İptal", command=dlg.destroy).pack(side="right")

    def _tarihleri_degistir(self):
        if not self.kart_id:
            return
        dialog = KartTarihleriDegistirDialog(self, self.kart_id)
        self.wait_window(dialog)
        if dialog.result:
            self.result = True
            self.destroy()

    def kaydet(self):
        if not self.kart_bankasi.get().strip():
            messagebox.showerror("Kart", "Kartın bankası zorunludur.", parent=self)
            return
        if not self.kart_adi.get().strip():
            messagebox.showerror("Kart", "Kart adı zorunludur.", parent=self)
            return
        urun = self.urun_turu.get()
        veri = {
            "banka_karti_id": self.banka_karti_id,
            "kart_bankasi": self.kart_bankasi.get(),
            "kart_adi": self.kart_adi.get(),
            "kart_sahibi": self.kart_sahibi.get(),
            "kart_markasi": self.kart_markasi.get(),
            "kart_numarasi": self.kart_no.get(),
            "son_kullanim": self.son_kullanim.get(),
            "kart_limiti": self.limit.get(),
            "hesap_kesim_gunu": self.kesim.get(),
            "son_odeme_gunu": self.son_odeme.get(),
            "kesimden_sonra_odeme_gun": self.kesimden_sonra.get(),
            "para_birimi": self.para_birimi.get(),
            "odeme_vade_yontemi": self.vade_yontem.get(),
            "banka_urun_turu": None if urun in ("", "(Seçiniz)") else urun,
            "asgari_oran_yuzde": self.asgari_oran.get(),
            "asgari_kaynak": self.asgari_kaynak.get(),
            "asgari_gecerlilik": self.asgari_gecerlilik.get(),
            "otomatik_faiz_tahakkuku": self.oto_faiz.get(),
            "varsayilan_taksit_adet": self.varsayilan_taksit.get(),
            "aciklama": self.aciklama.get(),
            "aktif": True,
        }
        if self.kart_id:
            veri["kart_id"] = self.kart_id
        try:
            kayit = FinansService.kredi_karti_kaydet(veri)
            self.kart_id = int(kayit.id)
            self._faiz_kaydet(self.kart_id)
        except ValueError as hata:
            messagebox.showerror("Kart", str(hata), parent=self)
            return
        except Exception as hata:
            messagebox.showerror("Kart", str(hata), parent=self)
            return
        self.result = kayit
        self._kirli = False
        self.title("Kredi Kartı Tanımı — Düzenle")
        self._islem_butonlari_durum(True)
        self._ozet_yenile()
        messagebox.showinfo("Kaydedildi", f"Kart: {kayit.kart_adi}", parent=self)

    def _pasif(self):
        if not self.kart_id:
            return
        if not messagebox.askyesno("Pasif", "Bu kartı pasif yapmak istiyor musunuz?", parent=self):
            return
        try:
            FinansService.kredi_karti_pasif_yap(self.kart_id)
        except ValueError as hata:
            messagebox.showerror("Kart", str(hata), parent=self)
            return
        self.result = True
        self.destroy()

    def _sil(self):
        if not self.kart_id:
            return
        if _kullanilmayan_karti_sil(self, "KREDI_KARTI", int(self.kart_id)):
            self.result = True
            self.destroy()


class KrediKartiOdemeDialog(tk.Toplevel):
    """Kredi kartı ödeme evrakı: tarih, ilk taksit vadesi, tek/taksit, tedarikçi, kart."""

    def __init__(self, parent, banka_karti_id):
        super().__init__(parent)
        self.banka_karti_id = banka_karti_id
        self.result = None
        self._secili_cari_id = None
        self._secili_cari_ad = ""
        self._vade_elle = False
        self.title("Kredi Kartı Ödeme Evrakı")
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)
        self.geometry("760x640")
        self.minsize(680, 560)
        self.resizable(True, True)

        from cari_arama_alani import CariAramaAlani

        row = 0
        ttk.Label(self, text="Tarih (çekim) *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=14)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)
        self.tarih.bind("<FocusOut>", lambda _e: self._cekim_tarih_degisti())
        self.tarih.bind("<KeyRelease>", lambda _e: self._cekim_tarih_degisti())

        row = 1
        ttk.Label(self, text="İlk taksit vadesi *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        vade_c = ttk.Frame(self)
        vade_c.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.vade = ttk.Entry(vade_c, width=14)
        self.vade.pack(side="left")
        takvim_butonu(vade_c, self.vade)
        self.vade.bind("<KeyRelease>", lambda _e: self._vade_elle_yazildi())
        self.vade.bind("<FocusOut>", lambda _e: self._vade_elle_yazildi())
        ttk.Label(
            self,
            text="Varsayılan: işlem günü (iç plan). Banka son ödeme ayrı tutulur.",
            foreground="#555",
        ).grid(row=row, column=2, padx=4, sticky="w")

        row = 2
        ttk.Label(self, text="Çekim türü *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.cekim = ttk.Combobox(
            self,
            values=[e for _k, e in KK_CEKIM_TURLERI],
            state="readonly",
            width=28,
        )
        self.cekim.set("Tek Çekim")
        self.cekim.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.cekim.bind("<<ComboboxSelected>>", lambda _e: self._cekim_degisti())
        self._cekim_map = {e: k for k, e in KK_CEKIM_TURLERI}

        row = 3
        ttk.Label(self, text="Taksit sayısı").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.taksit = ttk.Combobox(
            self,
            values=[str(i) for i in range(1, KK_MAX_TAKSIT + 1)],
            width=8,
            state="disabled",
        )
        self.taksit.set("1")
        self.taksit.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.taksit.bind("<<ComboboxSelected>>", lambda _e: self._vade_ve_plan_guncelle())

        row = 4
        ttk.Label(self, text="Ödeme tutarı *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.tutar = ttk.Entry(self, width=18)
        self.tutar.grid(row=row, column=1, padx=12, pady=6, sticky="w")
        self.tutar.bind("<KeyRelease>", lambda _e: self._vade_ve_plan_guncelle())

        row = 5
        ttk.Label(self, text="Ödeme yapılan firma *").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.cari = ttk.Entry(self, width=42)
        self.cari.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        self._cari_kod_lbl = ttk.Label(self, text="Tedarikçi veya Müşteri/Tedarikçi · ad yazarak ara", foreground="#555")
        self._cari_kod_lbl.grid(row=row + 1, column=1, columnspan=2, padx=12, sticky="w")
        self._cari_arama = CariAramaAlani(
            self,
            self.cari,
            cari_turu="Tedarikçi",
            on_secim=self._cari_secildi,
            on_temizle=self._cari_temizle,
            secili_ad=lambda: self._secili_cari_ad,
            kayit_adi="Tedarikçi",
        )

        row = 7
        kartlar = FinansService.kredi_kartlari(banka_karti_id=banka_karti_id)
        self._kart_map = {}
        kart_etiketleri = []
        for kk in kartlar:
            etiket = kk.kart_adi
            if kk.son_dort_hane:
                etiket = f"{etiket} (****{kk.son_dort_hane})"
            self._kart_map[etiket] = kk.id
            kart_etiketleri.append(etiket)
        ttk.Label(self, text="Ödeme kartı *").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.kart = ttk.Combobox(
            self, values=kart_etiketleri, state="readonly", width=40
        )
        self.kart.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")
        if kart_etiketleri:
            self.kart.set(kart_etiketleri[0])
        self.kart.bind("<<ComboboxSelected>>", lambda _e: self._kart_degisti())

        row = 8
        self.limit_lbl = ttk.Label(self, text="", foreground="#555")
        self.limit_lbl.grid(row=row, column=0, columnspan=3, padx=12, sticky="w")

        row = 9
        ttk.Label(self, text="Referans / onay no").grid(
            row=row, column=0, padx=12, pady=6, sticky="w"
        )
        self.referans = ttk.Entry(self, width=24)
        self.referans.grid(row=row, column=1, padx=12, pady=6, sticky="w")

        row = 10
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=12, pady=6, sticky="w")
        self.aciklama = ttk.Entry(self, width=40)
        self.aciklama.grid(row=row, column=1, columnspan=2, padx=12, pady=6, sticky="w")

        row = 11
        plan_f = ttk.LabelFrame(self, text="Taksit planı önizleme", padding=8)
        plan_f.grid(row=row, column=0, columnspan=3, padx=12, pady=8, sticky="nsew")
        self.rowconfigure(row, weight=1)
        self.columnconfigure(1, weight=1)
        plan_box = ttk.Frame(plan_f)
        plan_box.pack(fill="both", expand=True)
        self.plan_tablo = ttk.Treeview(
            plan_box,
            columns=("no", "vade", "banka_vade", "tutar"),
            show="headings",
            height=8,
        )
        for k, b, w in (
            ("no", "No", 40),
            ("vade", "Plan vadesi", 100),
            ("banka_vade", "Banka vadesi", 100),
            ("tutar", "Tutar", 90),
        ):
            self.plan_tablo.heading(k, text=b)
            self.plan_tablo.column(k, width=w, anchor="w")
        p_scroll = ttk.Scrollbar(plan_box, orient="vertical", command=self.plan_tablo.yview)
        self.plan_tablo.configure(yscrollcommand=p_scroll.set)
        self.plan_tablo.pack(side="left", fill="both", expand=True)
        p_scroll.pack(side="right", fill="y")

        butonlar = ttk.Frame(self)
        butonlar.grid(row=12, column=0, columnspan=3, padx=12, pady=12, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")

        self._limit_bilgi()
        self._onerilen_vadeyi_yaz(zorla=True)
        self._vade_ve_plan_guncelle()

    def _cari_secildi(self, cari):
        self._secili_cari_id = int(cari.id)
        self._secili_cari_ad = (cari.unvan or "").strip()
        self.cari.delete(0, "end")
        self.cari.insert(0, self._secili_cari_ad)
        kod = (cari.cari_kodu or "").strip()
        tur = (cari.cari_turu or "").strip()
        self._cari_kod_lbl.configure(text=f"{kod} · {tur}" if kod else tur or "Seçildi")

    def _cari_temizle(self):
        self._secili_cari_id = None
        self._secili_cari_ad = ""
        self._cari_kod_lbl.configure(
            text="Tedarikçi veya Müşteri/Tedarikçi · ad yazarak ara"
        )

    def _cekim_degisti(self):
        tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
        if tur == "TEK_CEKIM":
            self.taksit.set("1")
            self.taksit.configure(state="disabled")
        else:
            self.taksit.configure(state="readonly")
            if self.taksit.get() == "1":
                self.taksit.set("2")
        self._vade_ve_plan_guncelle()

    def _kart_degisti(self):
        self._limit_bilgi()
        self._onerilen_vadeyi_yaz(zorla=False)
        self._vade_ve_plan_guncelle()

    def _cekim_tarih_degisti(self):
        self._onerilen_vadeyi_yaz(zorla=False)
        self._vade_ve_plan_guncelle()

    def _vade_elle_yazildi(self):
        self._vade_elle = True
        self._vade_ve_plan_guncelle()

    def _secili_kart(self):
        kid = self._kart_map.get(self.kart.get())
        return FinansService.kredi_karti_getir(kid) if kid else None

    def _onerilen_vadeyi_yaz(self, *, zorla: bool):
        if self._vade_elle and not zorla:
            return
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
        except ValueError:
            return
        kk = self._secili_kart()
        oner = FinansService.kk_ilk_taksit_oner(kk, tarih)
        self.vade.delete(0, "end")
        self.vade.insert(0, oner.strftime("%d.%m.%Y"))
        self._vade_elle = False

    def _limit_bilgi(self):
        kk = self._secili_kart()
        if not kk:
            self.limit_lbl.configure(text="")
            return
        self.limit_lbl.configure(text=_kart_limit_metni(kk))

    def _vade_ve_plan_guncelle(self):
        for item in self.plan_tablo.get_children():
            self.plan_tablo.delete(item)
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
        except ValueError:
            return
        try:
            ilk = datetime.strptime(self.vade.get().strip(), "%d.%m.%Y").date()
        except ValueError:
            ilk = None
        tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
        try:
            n = 1 if tur == "TEK_CEKIM" else int(self.taksit.get() or "1")
        except ValueError:
            return
        try:
            tutar = Decimal(str(self.tutar.get() or "0").replace(",", "."))
        except Exception:
            tutar = Decimal("0")
        if tutar <= 0:
            return
        try:
            plan = FinansService.kk_taksit_plani(
                tarih, n, tutar, ilk_taksit_tarihi=ilk, kart=self._secili_kart()
            )
        except ValueError:
            return
        for satir in plan:
            self.plan_tablo.insert(
                "",
                "end",
                values=(
                    satir["taksit_no"],
                    _tarih(satir["vade_tarihi"]),
                    _tarih(satir.get("banka_vade_tarihi"))
                    if satir.get("banka_vade_tarihi")
                    else "—",
                    _para(satir["tutar"]),
                ),
            )

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            try:
                ilk = datetime.strptime(self.vade.get().strip(), "%d.%m.%Y").date()
            except ValueError as hata:
                raise ValueError("İlk taksit vadesi GG.AA.YYYY biçiminde olmalıdır.") from hata
            tur = self._cekim_map.get(self.cekim.get(), "TEK_CEKIM")
            n = 1 if tur == "TEK_CEKIM" else int(self.taksit.get() or "1")
            cari_id = self._secili_cari_id
            if cari_id is None:
                raise ValueError("Ödeme yapılan firmayı listeden seçin (ad yazarak arayın).")
            kart_id = self._kart_map.get(self.kart.get())
            if kart_id is None:
                raise ValueError("Ödeme kartını seçin.")
            self.result = FinansService.kredi_karti_odeme(
                self.banka_karti_id,
                kart_id,
                cari_id,
                tarih,
                self.tutar.get(),
                cekim_turu=tur,
                taksit_sayisi=n,
                referans_no=self.referans.get().strip() or None,
                aciklama=self.aciklama.get().strip() or None,
                ilk_taksit_tarihi=ilk,
            )
        except ValueError as hata:
            messagebox.showerror("Ödeme", str(hata), parent=self)
            return
        r = self.result
        plan_ozet = "\n".join(
            f"  {s['taksit_no']}. {_tarih(s['vade_tarihi'])}  {_para(s['tutar'])}"
            for s in r["plan"][:6]
        )
        if len(r["plan"]) > 6:
            plan_ozet += f"\n  … +{len(r['plan']) - 6} taksit"
        messagebox.showinfo(
            "Kaydedildi",
            f"Belge: {r['belge_no']}\n"
            f"{r['cekim_turu']} · {_para(r['tutar'])}\n"
            f"Vade (1.): {_tarih(r['vade_tarihi'])}\n"
            f"Taksit planı:\n{plan_ozet}",
            parent=self,
        )
        self.destroy()


class KredilerIslemleriDialog(tk.Toplevel):
    """Banka kredileri: kullandırım, taksit planı, anapara/faiz/masraf ödemesi."""

    def __init__(self, parent, kart):
        super().__init__(parent)
        self.parent_dlg = parent
        self.kart_id = kart.id
        self.title(f"{kart.banka_adi} — Krediler")
        self.geometry("1120x760")
        self.minsize(980, 640)
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)
        self._hareket_belge: dict[str, str] = {}
        self._durum_filtre = tk.StringVar(value="Tümü")
        self._secili_kredi_id: int | None = None
        self._detay_nesil = 0  # hızlı seçimde eski sorgu sonucunu düşür

        ust = ttk.Frame(self, padding=10)
        ust.pack(fill="x")
        self.bakiye_lbl = tk.Label(ust, text="", font=("Segoe UI", 11, "bold"), anchor="w")
        self.bakiye_lbl.pack(side="left", fill="x", expand=True)
        ttk.Button(ust, text="Kapat", command=self.destroy).pack(side="right")

        menu = ttk.LabelFrame(self, text="Evraklar", padding=10)
        menu.pack(fill="x", padx=10, pady=4)
        ttk.Button(menu, text="Yeni Kredi Kullandır", command=self._kullandir_ac).pack(
            side="left", padx=4
        )
        ttk.Button(menu, text="Seçili Taksiti Öde", command=self._taksit_ode).pack(
            side="left", padx=4
        )
        ttk.Button(menu, text="Gider Fişini Aç", command=self._gider_fisini_ac).pack(
            side="left", padx=4
        )
        ttk.Label(menu, text="Durum:").pack(side="left", padx=(12, 4))
        durum_cb = ttk.Combobox(
            menu,
            textvariable=self._durum_filtre,
            values=("Tümü", "Aktif", "Kapanmış", "Pasif"),
            state="readonly",
            width=10,
        )
        durum_cb.pack(side="left")
        durum_cb.bind("<<ComboboxSelected>>", lambda _e: self.listeyi_yenile())
        ttk.Button(menu, text="Yenile", command=self.listeyi_yenile).pack(side="left", padx=4)

        ttk.Label(
            self,
            text=(
                "Üst listeden kredi seçin — taksitler ve hareketler yalnız o krediye aittir. "
                "Ana para krediler hesabına borç yazılır; faiz/masraf ödeme gününde giderleşir."
            ),
            wraplength=1050,
        ).pack(anchor="w", padx=14, pady=(0, 2))
        self.esleme_uyari = ttk.Label(self, text="", foreground="#a15c00")
        self.esleme_uyari.pack(anchor="w", padx=14, pady=(0, 4))
        self.detay_ozet = ttk.Label(self, text="", foreground="#334155")
        self.detay_ozet.pack(anchor="w", padx=14, pady=(0, 4))

        kredi_f = ttk.LabelFrame(self, text="Krediler", padding=8)
        kredi_f.pack(fill="x", padx=10, pady=4)
        self.kredi_tablo = ttk.Treeview(
            kredi_f,
            columns=(
                "belge", "ad", "tur", "tarih", "anapara", "faiz", "masraf",
                "taksit", "taksit_tutari", "kalan", "durum", "plan",
            ),
            show="headings",
            height=5,
            selectmode="browse",
        )
        for k, b, w in (
            ("belge", "Belge", 100),
            ("ad", "Kredi", 150),
            ("tur", "Tür", 100),
            ("tarih", "Kullandırım", 90),
            ("anapara", "Ana para", 95),
            ("faiz", "Faiz", 80),
            ("masraf", "Masraf", 80),
            ("taksit", "Taksit Sayısı", 70),
            ("taksit_tutari", "Taksit Tutarı", 120),
            ("kalan", "Kalan anapara", 100),
            ("durum", "Durum", 90),
            ("plan", "Plan", 80),
        ):
            self.kredi_tablo.heading(k, text=b)
            self.kredi_tablo.column(k, width=w, anchor="w")
        self.kredi_tablo.pack(fill="x")
        self.kredi_tablo.bind("<<TreeviewSelect>>", self._kredi_secildi)
        self.kredi_tablo.bind("<Double-1>", self._kredi_belge_ac)

        taksit_f = ttk.LabelFrame(
            self, text="Seçili kredinin taksitleri (çift tık = öde)", padding=8
        )
        taksit_f.pack(fill="x", padx=10, pady=4)
        self.taksit_tablo = ttk.Treeview(
            taksit_f,
            columns=("belge", "kredi", "no", "vade", "anapara", "faiz", "masraf", "toplam", "durum"),
            show="headings",
            height=5,
        )
        for k, b, w in (
            ("belge", "Belge", 110),
            ("kredi", "Kredi", 150),
            ("no", "Taksit", 70),
            ("vade", "Vade", 90),
            ("anapara", "Anapara", 95),
            ("faiz", "Faiz", 85),
            ("masraf", "Masraf", 85),
            ("toplam", "Toplam", 100),
            ("durum", "Durum", 100),
        ):
            self.taksit_tablo.heading(k, text=b)
            self.taksit_tablo.column(k, width=w, anchor="w")
        self.taksit_tablo.pack(fill="x")
        self.taksit_tablo.bind("<Double-1>", lambda _e: self._taksit_ode())

        filtre = ttk.Frame(self, padding=(10, 0))
        filtre.pack(fill="x")
        ttk.Label(filtre, text="Hareket:").pack(side="left")
        self.har_bas = ttk.Entry(filtre, width=11)
        self.har_bas.pack(side="left", padx=4)
        ttk.Label(filtre, text="—").pack(side="left")
        self.har_bit = ttk.Entry(filtre, width=11)
        self.har_bit.pack(side="left", padx=4)
        takvim_butonu(filtre, self.har_bas)
        takvim_butonu(filtre, self.har_bit)
        ttk.Button(filtre, text="Filtrele", command=self._detaylari_yenile).pack(side="left", padx=6)
        ttk.Button(filtre, text="Tüm tarih", command=self._har_filtre_temizle).pack(side="left")
        self._eslesmesiz_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filtre,
            text="Kredi eşlemesi gereken hareketler",
            variable=self._eslesmesiz_var,
            command=self._detaylari_yenile,
        ).pack(side="left", padx=10)

        orta = ttk.LabelFrame(
            self, text="Seçili kredinin hareketleri — çift tık belge", padding=8
        )
        orta.pack(fill="both", expand=True, padx=10, pady=6)
        cerceve = ttk.Frame(orta)
        cerceve.pack(fill="both", expand=True)
        self.tablo = ttk.Treeview(
            cerceve,
            columns=("tarih", "tur", "belge", "hesap", "kredi", "giris", "cikis", "esleme", "aciklama"),
            show="headings",
        )
        _hareket_kolonlari_ayarla(
            self.tablo,
            (
                ("tarih", "Tarih", 85),
                ("tur", "Hareket", 130),
                ("belge", "Belge", 110),
                ("hesap", "Hesap", 130),
                ("kredi", "Kredi", 120),
                ("giris", "Borç (+)", 90),
                ("cikis", "Ödeme (−)", 90),
                ("esleme", "Eşleme", 90),
                ("aciklama", "Açıklama", 200),
            ),
        )
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=kaydir.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        _hareket_tablo_stil(self.tablo)
        self.tablo.bind("<Double-1>", self._hareket_belge_ac)
        self.listeyi_yenile()

    def _hesap(self):
        kart = FinansService.banka_karti_getir(self.kart_id)
        if not kart:
            return None, None
        return kart, FinansService.banka_alt_hesap(kart, "KREDILER")

    def _har_filtre_temizle(self):
        self.har_bas.delete(0, "end")
        self.har_bit.delete(0, "end")
        self._detaylari_yenile()

    def _tarih_oku(self, widget):
        ham = (widget.get() or "").strip()
        if not ham:
            return None
        try:
            return datetime.strptime(ham, "%d.%m.%Y").date()
        except ValueError:
            messagebox.showerror("Tarih", "Tarih GG.AA.YYYY formatında olmalı.", parent=self)
            raise

    def _kredi_secildi(self, _e=None):
        sec = self.kredi_tablo.selection()
        if not sec:
            return
        try:
            kid = int(sec[0])
        except (TypeError, ValueError):
            return
        if self._secili_kredi_id == kid:
            # Aynı seçim — yine de detayı tazele (yenile/filtre sonrası)
            pass
        else:
            self._secili_kredi_id = kid
            # Önceki krediden kalan taksit seçimini temizle
            self.taksit_tablo.selection_remove(*self.taksit_tablo.selection())
        self._detaylari_yenile()

    def listeyi_yenile(self):
        try:
            self._listeyi_yenile_icerik()
        except Exception as exc:
            messagebox.showerror(
                "Krediler",
                f"Kredi listesi yüklenirken hata:\n{exc}",
                parent=self,
            )
            self.esleme_uyari.configure(
                text="Veri yükleme hatası — liste boş gösterilmedi; hata penceresini kontrol edin."
            )

    def _listeyi_yenile_icerik(self):
        kart, hesap = self._hesap()
        onceki = self._secili_kredi_id
        for item in self.kredi_tablo.get_children():
            self.kredi_tablo.delete(item)
        if not kart:
            self.bakiye_lbl.configure(text="Banka kartı bulunamadı.", fg=_bakiye_renk(0))
            self._secili_kredi_id = None
            self._detaylari_yenile()
            return
        # Banka genel borcu — kredi seçiminden bağımsız
        bakiyeler = FinansService.banka_bakiyeler_varlik(kart)
        goster = bakiyeler.get("KREDILER", Decimal("0"))
        gercek = FinansService.kredi_alt_hesaplari(kart)
        self.bakiye_lbl.configure(
            text=(
                f"Krediler borcu (kalan anapara): {_para_bakiye(goster)}  ·  "
                f"{len(gercek)} hesap"
            ),
            fg=_bakiye_renk(goster),
        )
        if not hesap and not gercek:
            self.esleme_uyari.configure(text="Bu bankada krediler alt hesabı yok.")
        else:
            self.esleme_uyari.configure(text="")

        durum_sec = self._durum_filtre.get()
        if durum_sec == "Aktif":
            krediler = FinansService.banka_kredileri(
                banka_karti_id=self.kart_id, durum_filtre="KULLANDIRILDI"
            )
        elif durum_sec == "Kapanmış":
            krediler = FinansService.banka_kredileri(
                banka_karti_id=self.kart_id, durum_filtre="KAPALI", aktif_only=False
            )
        elif durum_sec == "Pasif":
            krediler = FinansService.banka_kredileri(
                banka_karti_id=self.kart_id, durum_filtre="PASIF", aktif_only=False
            )
        else:
            krediler = FinansService.banka_kredileri(
                banka_karti_id=self.kart_id, durum_filtre="TUMU", aktif_only=False
            )

        tur_map = dict(KREDI_TURLERI)
        idler = []
        for k in krediler:
            det = FinansService.banka_kredi_getir(k.id) or {}
            kalan = Decimal(str(det.get("kalan_anapara") or 0))
            plan = "Yok" if det.get("plan_eksik") else f"{k.taksit_sayisi}"
            tutar_goster = _kredi_taksit_tutari_hucre(det)
            iid = str(k.id)
            idler.append(int(k.id))
            self.kredi_tablo.insert(
                "",
                "end",
                iid=iid,
                values=(
                    k.belge_no,
                    k.kredi_adi,
                    tur_map.get(k.kredi_turu, k.kredi_turu),
                    _tarih(k.kullandirim_tarihi),
                    _para(k.ana_para),
                    _para(k.toplam_faiz),
                    _para(k.toplam_masraf),
                    k.taksit_sayisi,
                    tutar_goster,
                    _para(kalan),
                    k.durum or "—",
                    plan,
                ),
            )

        # Seçimi koru; yoksa ilk krediyi seç
        hedef = onceki if onceki in idler else (idler[0] if idler else None)
        self._secili_kredi_id = hedef
        if hedef is not None:
            self.kredi_tablo.selection_set(str(hedef))
            self.kredi_tablo.focus(str(hedef))
            self.kredi_tablo.see(str(hedef))
        else:
            self.kredi_tablo.selection_remove(*self.kredi_tablo.selection())

        if gercek and not krediler and durum_sec in ("Tümü", "Aktif"):
            self.esleme_uyari.configure(
                text="Kredi hesabı var ancak tanım eşlenmemiş. Eşleme aracını çalıştırın."
            )
        self._detaylari_yenile()

    def _detaylari_yenile(self):
        """Seçili krediye göre taksit + hareket; nesil ile yarış koruması."""
        self._detay_nesil += 1
        nesil = self._detay_nesil
        for tablo in (self.taksit_tablo, self.tablo):
            for item in tablo.get_children():
                tablo.delete(item)
        self._hareket_belge.clear()

        kid = self._secili_kredi_id
        if kid is None:
            self.detay_ozet.configure(text="Kredi seçilmedi — taksit ve hareket listesi boş.")
            return

        det = FinansService.banka_kredi_getir(int(kid)) or {}
        if nesil != self._detay_nesil:
            return
        if not det or int(det.get("banka_karti_id") or 0) != int(self.kart_id):
            self.detay_ozet.configure(text="Seçili kredi bu bankaya ait değil.")
            self._secili_kredi_id = None
            return

        self.detay_ozet.configure(
            text=(
                f"Seçili: {det.get('belge_no') or '—'} — {det.get('kredi_adi') or '—'}  ·  "
                f"Kalan anapara {_para(det.get('kalan_anapara') or 0)} TL  ·  "
                f"Plan {'yok' if det.get('plan_eksik') else str(det.get('taksit_sayisi')) + ' taksit'}"
            )
        )

        # Taksitler: seçili kredinin tamamı (bekleyen + ödenmiş)
        taksitler = FinansService.banka_kredi_taksitleri(int(kid))
        if nesil != self._detay_nesil:
            return
        if not self._eslesmesiz_var.get():
            if not taksitler:
                self.esleme_uyari.configure(
                    text="Bu kredide listelenecek taksit yok (plan eksik veya kapalı)."
                )
            else:
                self.esleme_uyari.configure(text="")
        for t in taksitler:
            if nesil != self._detay_nesil:
                return
            sira = t.get("plan_sira") or t.get("taksit_no")
            adet = t.get("plan_adet") or t.get("taksit_sayisi") or 0
            self.taksit_tablo.insert(
                "",
                "end",
                iid=str(t["taksit_id"]),
                values=(
                    t["belge_no"],
                    t["kredi_adi"],
                    f"{sira}/{adet}",
                    _tarih(t["vade_tarihi"]),
                    _para(t["anapara"]),
                    _para(t["faiz"]),
                    _para(t["masraf"]),
                    _para(t["toplam"]),
                    t.get("durum") or "—",
                ),
            )

        try:
            bas = self._tarih_oku(self.har_bas)
            bit = self._tarih_oku(self.har_bit)
        except ValueError:
            return
        if nesil != self._detay_nesil:
            return

        if self._eslesmesiz_var.get():
            # Eşleşmemişler banka genelinde ayrı görünüm — seçili krediye ait gibi gösterme
            hareketler = FinansService.banka_kredi_hesap_hareketleri(
                self.kart_id,
                baslangic=bas,
                bitis=bit,
                sadece_eslesmesiz=True,
            )
        else:
            hareketler = FinansService.banka_kredi_hesap_hareketleri(
                self.kart_id,
                kredi_id=int(kid),
                baslangic=bas,
                bitis=bit,
            )
        if nesil != self._detay_nesil:
            return

        eslesmesiz_n = 0
        for sira, har in enumerate(hareketler):
            if har.get("esleme_bekliyor"):
                eslesmesiz_n += 1
            isaret = har["isaret"]
            iid = f"h{har['id']}"
            self._hareket_belge[iid] = har.get("belge_no") or ""
            self.tablo.insert(
                "",
                "end",
                iid=iid,
                values=(
                    _tarih(har["tarih"]),
                    har.get("hareket_turu") or "—",
                    har.get("belge_no") or "—",
                    har.get("hesap_adi") or "—",
                    har.get("kredi") or "—",
                    _para(har["tutar"]) if isaret > 0 else "",
                    _para(har["tutar"]) if isaret < 0 else "",
                    "Eşleme gerekli" if har.get("esleme_bekliyor") else "Bağlı",
                    (har.get("aciklama") or "")[:80],
                ),
                tags=_hareket_satir_tags(sira, isaret=isaret),
            )
        if self._eslesmesiz_var.get():
            self.esleme_uyari.configure(
                text=(
                    f"Eşleşmemiş hareket görünümü ({eslesmesiz_n} satır) — "
                    "bu kayıtlar seçili krediye ait sayılmaz."
                )
            )
        elif not hareketler and not taksitler:
            pass
        elif not hareketler:
            # uyarıyı silme — taksit uyarısı olabilir
            pass

    def _kredi_belge_ac(self, _e=None):
        secim = self.kredi_tablo.selection()
        if not secim:
            return
        det = FinansService.banka_kredi_getir(int(secim[0]))
        if not det:
            messagebox.showerror("Kredi", "Kredi kaydı yüklenemedi.", parent=self)
            return
        belge = (det.get("belge_no") or "").strip()
        if belge:
            from belge_onizleme_ui import finans_belge_ac

            if finans_belge_ac(self, "FİNANS", belge):
                return
        # Eşleme tanımları (EVB-KR-H*) için FİNANS fişi yok; kayıt özeti göster
        messagebox.showinfo(
            "Kredi",
            (
                f"{det['kredi_adi']}\nBelge: {belge or '—'}\n"
                f"Kayıt id: {det.get('id') or secim[0]}\n"
                f"Durum: {det['durum']}\nKalan anapara: {_para(det['kalan_anapara'])}\n"
                f"Plan: {'eksik' if det.get('plan_eksik') else str(det['taksit_sayisi']) + ' taksit'}\n"
                f"Bağlı hesap id: {det.get('bagli_hesap_id') or '—'}"
            ),
            parent=self,
        )

    def _hareket_belge_ac(self, _e=None):
        secim = self.tablo.selection()
        if not secim:
            return
        belge = self._hareket_belge.get(secim[0]) or ""
        if not belge:
            messagebox.showinfo("Belge", "Bu satırda belge numarası yok.", parent=self)
            return
        from belge_onizleme_ui import finans_belge_ac

        if not finans_belge_ac(self, "FİNANS", belge):
            messagebox.showinfo("Belge", f"Belge açılamadı: {belge}", parent=self)
        self.listeyi_yenile()

    def _kullandir_ac(self):
        dialog = BankaKrediKullandirDialog(self, self.kart_id)
        self.wait_window(dialog)
        if dialog.result:
            self.listeyi_yenile()
            if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
                self.parent_dlg.bakiyeleri_yenile()

    def _taksit_ode(self):
        secim = self.taksit_tablo.selection()
        if not secim:
            messagebox.showinfo("Taksit", "Ödenecek taksiti seçin.", parent=self)
            return
        tid = int(secim[0])
        try:
            det = FinansService.banka_kredi_taksit_detay(tid)
        except ValueError as exc:
            messagebox.showerror("Taksit", str(exc), parent=self)
            return
        if self._secili_kredi_id is not None and int(det.get("kredi_id") or 0) != int(
            self._secili_kredi_id
        ):
            messagebox.showerror(
                "Taksit",
                "Seçili taksit bu krediye ait değil. Listeyi yenileyip tekrar seçin.",
                parent=self,
            )
            self._detaylari_yenile()
            return
        dialog = BankaKrediTaksitOdemeDialog(self, tid)
        self.wait_window(dialog)
        if dialog.result:
            self.listeyi_yenile()
            if hasattr(self.parent_dlg, "bakiyeleri_yenile"):
                self.parent_dlg.bakiyeleri_yenile()
            gider = (dialog.result.get("gider_belge_no") or "").strip()
            odeme = (dialog.result.get("odeme_belge_no") or "").strip()
            if gider or odeme:
                if messagebox.askyesno(
                    "Gider Fişi",
                    "Ödeme kaydedildi. Gider fişini şimdi açmak ister misiniz?",
                    parent=self,
                ):
                    from kredi_gider_fisi_ui import kredi_gider_fisini_ac

                    kredi_gider_fisini_ac(
                        self,
                        odeme_belge_no=odeme or None,
                        gider_belge_no=gider or None,
                    )

    def _gider_fisini_ac(self):
        """Seçili ödenmiş taksit veya ödeme hareketinden gider fişini açar."""
        from kredi_gider_fisi_ui import kredi_gider_fisini_ac

        # Önce taksit seçimi
        secim = self.taksit_tablo.selection()
        if secim:
            try:
                det = FinansService.banka_kredi_taksit_detay(int(secim[0]))
            except ValueError as exc:
                messagebox.showerror("Gider Fişi", str(exc), parent=self)
                return
            gider = (det.get("gider_belge_no") or "").strip()
            odeme = (det.get("odeme_belge_no") or "").strip()
            if gider or odeme:
                if kredi_gider_fisini_ac(
                    self, odeme_belge_no=odeme or None, gider_belge_no=gider or None
                ):
                    return
            messagebox.showinfo(
                "Gider Fişi",
                "Bu taksit için gider fişi yok. Önce faiz/masraf içeren ödeme kaydedin.",
                parent=self,
            )
            return
        # Hareket satırından belge
        har = self.tablo.selection()
        if har:
            belge = (self._hareket_belge.get(har[0]) or "").strip()
            if belge and kredi_gider_fisini_ac(self, odeme_belge_no=belge, gider_belge_no=belge):
                return
        messagebox.showinfo(
            "Gider Fişi",
            "Ödenmiş bir taksit veya ödeme hareketi seçin.",
            parent=self,
        )


class BankaKrediKullandirDialog(tk.Toplevel):
    """Yeni kredi: ana para + faiz + masraf + taksit planı önizleme / kullandırım."""

    def __init__(self, parent, banka_karti_id):
        super().__init__(parent)
        self.banka_karti_id = banka_karti_id
        self.result = None
        self._plan = []
        self._ilk_manuel = False
        self._plan_manuel = False
        self.title("Yeni Kredi Kullandır")
        self.geometry("860x700")
        self.minsize(780, 620)
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        # Butonlar önce alta sabitlenir — kesilmez / okunur kalır
        butonlar = ttk.Frame(self, padding=(12, 8))
        butonlar.pack(side="bottom", fill="x")
        ttk.Button(butonlar, text="İptal", command=self.destroy, width=12).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(
            butonlar, text="Kullandır / Kaydet", command=self.kaydet, width=18
        ).pack(side="right")
        ttk.Label(
            butonlar,
            text="Çift tık: vade / faiz / masraf düzenle · Plan silinebilir.",
        ).pack(side="left")

        form = ttk.LabelFrame(self, text="Kredi bilgileri", padding=10)
        form.pack(fill="x", padx=10, pady=(10, 4))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        # Sol sütun
        ttk.Label(form, text="Kredi adı *").grid(row=0, column=0, sticky="w", pady=3, padx=(0, 4))
        self.kredi_adi = ttk.Entry(form, width=32)
        self.kredi_adi.grid(row=0, column=1, sticky="ew", padx=4, pady=3)

        ttk.Label(form, text="Kredi türü").grid(row=1, column=0, sticky="w", pady=3, padx=(0, 4))
        self.kredi_turu = ttk.Combobox(
            form, state="readonly", width=28, values=[e for _k, e in KREDI_TURLERI]
        )
        self.kredi_turu.grid(row=1, column=1, sticky="w", padx=4, pady=3)
        self.kredi_turu.set(KREDI_TURLERI[0][1])
        self._tur_map = {e: k for k, e in KREDI_TURLERI}

        ttk.Label(form, text="Kullandırım tarihi *").grid(
            row=2, column=0, sticky="w", pady=3, padx=(0, 4)
        )
        tarih_c = ttk.Frame(form)
        tarih_c.grid(row=2, column=1, sticky="w", padx=4, pady=3)
        self.kullandirim = ttk.Entry(tarih_c, width=12)
        self.kullandirim.pack(side="left")
        self.kullandirim.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.kullandirim)

        ttk.Label(form, text="İlk taksit tarihi *").grid(
            row=3, column=0, sticky="w", pady=3, padx=(0, 4)
        )
        ilk_c = ttk.Frame(form)
        ilk_c.grid(row=3, column=1, sticky="w", padx=4, pady=3)
        self.ilk_taksit = ttk.Entry(ilk_c, width=12)
        self.ilk_taksit.pack(side="left")
        ilk_varsayilan = FinansService._ay_ekle(date.today(), 1)
        self.ilk_taksit.insert(0, ilk_varsayilan.strftime("%d.%m.%Y"))
        takvim_butonu(ilk_c, self.ilk_taksit)
        ttk.Label(form, text="(varsayılan: +1 ay, değiştirilebilir)").grid(
            row=3, column=2, columnspan=2, sticky="w", padx=4
        )

        ttk.Label(form, text="Ana para *").grid(row=0, column=2, sticky="w", pady=3, padx=(16, 4))
        self.ana_para = ttk.Entry(form, width=16)
        self.ana_para.grid(row=0, column=3, sticky="w", padx=4, pady=3)

        ttk.Label(form, text="Toplam faiz").grid(row=1, column=2, sticky="w", pady=3, padx=(16, 4))
        self.faiz = ttk.Entry(form, width=16)
        self.faiz.grid(row=1, column=3, sticky="w", padx=4, pady=3)
        self.faiz.insert(0, "0")

        ttk.Label(form, text="Toplam masraf").grid(row=2, column=2, sticky="w", pady=3, padx=(16, 4))
        self.masraf = ttk.Entry(form, width=16)
        self.masraf.grid(row=2, column=3, sticky="w", padx=4, pady=3)
        self.masraf.insert(0, "0")

        ttk.Label(form, text="Taksit sayısı").grid(row=3, column=2, sticky="w", pady=3, padx=(16, 4))
        self.taksit_sayisi = ttk.Spinbox(
            form, from_=1, to=KREDI_MAX_TAKSIT, width=8, command=self._plan_yenile
        )
        self.taksit_sayisi.grid(row=3, column=3, sticky="w", padx=4, pady=3)
        self.taksit_sayisi.set("12")

        ttk.Label(form, text="Kullandırım / ödeme hesabı").grid(
            row=4, column=0, sticky="w", pady=3, padx=(0, 4)
        )
        self.odeme_hesap = ttk.Combobox(
            form, state="readonly", width=18, values=[e for _k, e in KREDI_ODEME_HESAP_TURLERI]
        )
        self.odeme_hesap.grid(row=4, column=1, sticky="w", padx=4, pady=3)
        self.odeme_hesap.set(KREDI_ODEME_HESAP_TURLERI[0][1])
        self._odeme_map = {e: k for k, e in KREDI_ODEME_HESAP_TURLERI}

        ttk.Label(form, text="Sözleşme / referans no").grid(
            row=4, column=2, sticky="w", pady=3, padx=(16, 4)
        )
        self.sozlesme = ttk.Entry(form, width=18)
        self.sozlesme.grid(row=4, column=3, sticky="w", padx=4, pady=3)

        ttk.Label(form, text="Açıklama").grid(row=5, column=0, sticky="w", pady=3, padx=(0, 4))
        self.aciklama = ttk.Entry(form)
        self.aciklama.grid(row=5, column=1, columnspan=3, sticky="ew", padx=4, pady=3)

        # Özet maliyet bilgileri (plandan otomatik)
        ozet = ttk.LabelFrame(form, text="Maliyet özeti", padding=8)
        ozet.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(8, 2))
        ozet.columnconfigure(1, weight=1)
        ozet.columnconfigure(3, weight=1)
        ttk.Label(ozet, text="Yıllık maliyet (faiz+masraf)").grid(
            row=0, column=0, sticky="w", padx=(0, 6), pady=2
        )
        self.aylik_faiz_lbl = ttk.Label(
            ozet, text="—", font=("Segoe UI", 10, "bold"), foreground="#1a5f2a"
        )
        self.aylik_faiz_lbl.grid(row=0, column=1, sticky="w", padx=4, pady=2)
        ttk.Label(ozet, text="Yekün geri ödenecek (faiz+masraf dahil)").grid(
            row=0, column=2, sticky="w", padx=(16, 6), pady=2
        )
        self.yekun_lbl = ttk.Label(
            ozet, text="—", font=("Segoe UI", 10, "bold"), foreground="#1a3a6b"
        )
        self.yekun_lbl.grid(row=0, column=3, sticky="w", padx=4, pady=2)
        ttk.Label(
            ozet,
            text="Ortalama valör (anapara ağırlıklı gün) → yıllık % = "
            "((faiz+masraf)÷ana) × (365÷ortalama valör gün) × 100",
            font=("Segoe UI", 8),
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

        for w in (self.ana_para, self.faiz, self.masraf):
            w.bind("<KeyRelease>", lambda _e: self._ust_tutar_degisti())
        self.kullandirim.bind("<FocusOut>", lambda _e: self._kullandirim_degisti())
        self.ilk_taksit.bind("<FocusOut>", lambda _e: self._ilk_taksit_degisti())
        self.ilk_taksit.bind("<KeyRelease>", lambda _e: setattr(self, "_ilk_manuel", True))

        plan_f = ttk.LabelFrame(
            self,
            text="Taksit planı — çift tık: vade/faiz/masraf · Planı Sil / satır sil",
            padding=8,
        )
        plan_f.pack(fill="both", expand=True, padx=10, pady=6)
        ust_plan = ttk.Frame(plan_f)
        ust_plan.pack(fill="x")
        ttk.Button(ust_plan, text="Planı Yenile", command=self._plan_yenile).pack(side="left")
        ttk.Button(ust_plan, text="Satırı Düzenle", command=self._satir_duzenle).pack(
            side="left", padx=6
        )
        ttk.Button(ust_plan, text="Seçili Satırı Sil", command=self._satir_sil).pack(
            side="left", padx=6
        )
        ttk.Button(ust_plan, text="Planı Sil", command=self._plan_sil).pack(side="left", padx=6)
        self.plan_ozet = ttk.Label(ust_plan, text="")
        self.plan_ozet.pack(side="left", padx=12)

        cerceve = ttk.Frame(plan_f)
        cerceve.pack(fill="both", expand=True, pady=(6, 0))
        self.plan_tablo = ttk.Treeview(
            cerceve,
            columns=("no", "vade", "anapara", "faiz", "masraf", "toplam"),
            show="headings",
            height=10,
        )
        for k, b, w in (
            ("no", "No", 45),
            ("vade", "Vade", 100),
            ("anapara", "Anapara", 100),
            ("faiz", "Faiz", 90),
            ("masraf", "Masraf", 90),
            ("toplam", "Toplam", 100),
        ):
            self.plan_tablo.heading(k, text=b)
            self.plan_tablo.column(k, width=w, anchor="w")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.plan_tablo.yview)
        self.plan_tablo.configure(yscrollcommand=kaydir.set)
        self.plan_tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        self.plan_tablo.bind("<Double-1>", lambda _e: self._satir_duzenle())
        self._plan_yenile()

    def _ust_tutar_degisti(self):
        if self._plan_manuel and self._plan:
            return
        self._plan_yenile()

    def _kullandirim_degisti(self):
        try:
            kull = datetime.strptime(self.kullandirim.get().strip(), "%d.%m.%Y").date()
        except ValueError:
            return
        if not self._ilk_manuel:
            yeni = FinansService._ay_ekle(kull, 1)
            self.ilk_taksit.delete(0, "end")
            self.ilk_taksit.insert(0, yeni.strftime("%d.%m.%Y"))
        if not self._plan_manuel:
            self._plan_yenile()
        else:
            self._maliyet_ozetini_guncelle()

    def _ilk_taksit_degisti(self):
        self._ilk_manuel = True
        if not self._plan_manuel:
            self._plan_yenile()

    def _plan_tabloyu_ciz(self):
        for item in self.plan_tablo.get_children():
            self.plan_tablo.delete(item)
        for s in self._plan:
            s["toplam"] = (
                Decimal(str(s["anapara"]))
                + Decimal(str(s["faiz"]))
                + Decimal(str(s["masraf"]))
            )
            self.plan_tablo.insert(
                "",
                "end",
                values=(
                    s["taksit_no"],
                    _tarih(s["vade_tarihi"]),
                    _para(s["anapara"]),
                    _para(s["faiz"]),
                    _para(s["masraf"]),
                    _para(s["toplam"]),
                ),
            )
        self._maliyet_ozetini_guncelle()
        if not self._plan:
            self.plan_ozet.configure(text="Plan boş — «Planı Yenile» ile oluşturun.")
            return
        toplam = sum((Decimal(str(s["toplam"])) for s in self._plan), Decimal("0"))
        faiz_t = sum((Decimal(str(s["faiz"])) for s in self._plan), Decimal("0"))
        masraf_t = sum((Decimal(str(s["masraf"])) for s in self._plan), Decimal("0"))
        self.plan_ozet.configure(
            text=f"{len(self._plan)} taksit · Toplam: {_para(toplam)} · "
            f"Faiz: {_para(faiz_t)} · Masraf: {_para(masraf_t)}"
        )

    def _maliyet_ozetini_guncelle(self):
        """Ortalama valör (anapara ağırlıklı) → yıllık maliyet %; taksit sayısına bölünmez."""
        if not self._plan:
            self.aylik_faiz_lbl.configure(text="—")
            self.yekun_lbl.configure(text="—")
            return
        ana = sum((Decimal(str(s["anapara"])) for s in self._plan), Decimal("0"))
        faiz = sum((Decimal(str(s["faiz"])) for s in self._plan), Decimal("0"))
        masraf = sum((Decimal(str(s["masraf"])) for s in self._plan), Decimal("0"))
        yekun = ana + faiz + masraf
        self.yekun_lbl.configure(text=_para(yekun))
        if ana <= 0:
            self.aylik_faiz_lbl.configure(text="—")
            return
        try:
            kullandirim = datetime.strptime(
                self.kullandirim.get().strip(), "%d.%m.%Y"
            ).date()
        except ValueError:
            self.aylik_faiz_lbl.configure(text="—")
            return

        # Anapara ağırlıklı ortalama valör (gün) = Σ(anapara × gün) / Σ(anapara)
        agirlikli = Decimal("0")
        for s in self._plan:
            gun = (s["vade_tarihi"] - kullandirim).days
            if gun < 0:
                gun = 0
            agirlikli += Decimal(str(s["anapara"])) * Decimal(gun)
        ortalama_valor = (agirlikli / ana).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if ortalama_valor <= 0:
            self.aylik_faiz_lbl.configure(text="— (valör 0)")
            return

        # Yıllık maliyet % = ((faiz+masraf)/ana) * (365/ortalama_valor_gun) * 100
        yillik = (
            (faiz + masraf) / ana * (Decimal(365) / ortalama_valor) * Decimal("100")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        self.aylik_faiz_lbl.configure(
            text=f"% {yillik}  (ort. valör: {ortalama_valor} gün)"
        )

    def _ust_toplamlari_guncelle(self):
        ana_t = sum((Decimal(str(s["anapara"])) for s in self._plan), Decimal("0"))
        faiz_t = sum((Decimal(str(s["faiz"])) for s in self._plan), Decimal("0"))
        masraf_t = sum((Decimal(str(s["masraf"])) for s in self._plan), Decimal("0"))
        self.ana_para.delete(0, "end")
        self.ana_para.insert(0, f"{ana_t:.2f}".replace(".", ","))
        self.faiz.delete(0, "end")
        self.faiz.insert(0, f"{faiz_t:.2f}".replace(".", ","))
        self.masraf.delete(0, "end")
        self.masraf.insert(0, f"{masraf_t:.2f}".replace(".", ","))
        self.taksit_sayisi.set(str(len(self._plan) or 1))

    def _plan_yenile(self):
        if self._plan_manuel and self._plan:
            if not messagebox.askyesno(
                "Planı Yenile",
                "Manuel düzeltmeler silinip plan yeniden oluşturulacak. Devam?",
                parent=self,
            ):
                return
        self._plan = []
        self._plan_manuel = False
        try:
            ilk = datetime.strptime(self.ilk_taksit.get().strip(), "%d.%m.%Y").date()
            n = int(str(self.taksit_sayisi.get()).strip() or "1")
            plan = FinansService.banka_kredi_taksit_plani(
                ilk,
                n,
                self.ana_para.get() or "0",
                self.faiz.get() or "0",
                self.masraf.get() or "0",
            )
        except (ValueError, Exception):
            self.plan_ozet.configure(text="Plan için geçerli tutar / tarih girin.")
            self._plan_tabloyu_ciz()
            return
        self._plan = plan
        self._plan_tabloyu_ciz()

    def _plan_sil(self):
        if not self._plan:
            self.plan_ozet.configure(text="Plan zaten boş.")
            return
        if not messagebox.askyesno(
            "Planı Sil", "Taksit planı tamamen silinsin mi?", parent=self
        ):
            return
        self._plan = []
        self._plan_manuel = False
        self._plan_tabloyu_ciz()

    def _satir_sil(self):
        idx = self._secili_idx()
        if idx is None:
            messagebox.showinfo("Satır", "Silinecek taksit satırını seçin.", parent=self)
            return
        taksit_no = self._plan[idx]["taksit_no"]
        if not messagebox.askyesno(
            "Satır Sil",
            f"{taksit_no}. taksit silinsin mi?",
            parent=self,
        ):
            return
        del self._plan[idx]
        for i, s in enumerate(self._plan, start=1):
            s["taksit_no"] = i
        self._plan_manuel = True
        if self._plan:
            self._ilk_manuel = True
            self.ilk_taksit.delete(0, "end")
            self.ilk_taksit.insert(0, self._plan[0]["vade_tarihi"].strftime("%d.%m.%Y"))
            self._ust_toplamlari_guncelle()
        self._plan_tabloyu_ciz()

    def _secili_idx(self):
        secim = self.plan_tablo.selection()
        if not secim or not self._plan:
            return None
        degerler = self.plan_tablo.item(secim[0], "values")
        try:
            taksit_no = int(degerler[0])
        except (TypeError, ValueError, IndexError):
            return None
        idx = taksit_no - 1
        if idx < 0 or idx >= len(self._plan):
            return None
        return idx

    def _satir_duzenle(self):
        """Seçili taksit: vade, faiz, masraf (ve anapara) manuel düzenleme."""
        idx = self._secili_idx()
        if idx is None:
            messagebox.showinfo(
                "Düzenle",
                "Düzenlemek için bir taksit satırı seçin (veya çift tıklayın).",
                parent=self,
            )
            return
        satir = self._plan[idx]
        dlg = tk.Toplevel(self)
        dlg.title(f"{satir['taksit_no']}. taksit düzenle")
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)

        ttk.Label(dlg, text="Vade (gg.aa.yyyy)").grid(
            row=0, column=0, padx=12, pady=8, sticky="w"
        )
        vade_c = ttk.Frame(dlg)
        vade_c.grid(row=0, column=1, padx=12, pady=8, sticky="w")
        vade_e = ttk.Entry(vade_c, width=12)
        vade_e.pack(side="left")
        vade_e.insert(0, satir["vade_tarihi"].strftime("%d.%m.%Y"))
        takvim_butonu(vade_c, vade_e)

        ttk.Label(dlg, text="Anapara").grid(row=1, column=0, padx=12, pady=6, sticky="w")
        anapara_e = ttk.Entry(dlg, width=16)
        anapara_e.grid(row=1, column=1, padx=12, pady=6, sticky="w")
        anapara_e.insert(0, f"{Decimal(str(satir['anapara'])):.2f}".replace(".", ","))

        ttk.Label(dlg, text="Faiz").grid(row=2, column=0, padx=12, pady=6, sticky="w")
        faiz_e = ttk.Entry(dlg, width=16)
        faiz_e.grid(row=2, column=1, padx=12, pady=6, sticky="w")
        faiz_e.insert(0, f"{Decimal(str(satir['faiz'])):.2f}".replace(".", ","))

        ttk.Label(dlg, text="Masraf").grid(row=3, column=0, padx=12, pady=6, sticky="w")
        masraf_e = ttk.Entry(dlg, width=16)
        masraf_e.grid(row=3, column=1, padx=12, pady=6, sticky="w")
        masraf_e.insert(0, f"{Decimal(str(satir['masraf'])):.2f}".replace(".", ","))

        ttk.Label(dlg, text="Sonraki vadeleri aynı güne kaydır").grid(
            row=4, column=0, padx=12, pady=4, sticky="w"
        )
        kaydir_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(dlg, variable=kaydir_var).grid(row=4, column=1, sticky="w", padx=12)

        def onayla():
            try:
                yeni_vade = datetime.strptime(vade_e.get().strip(), "%d.%m.%Y").date()
                yeni_anapara = Decimal(
                    str(anapara_e.get()).strip().replace(",", ".")
                ).quantize(Decimal("0.01"))
                yeni_faiz = Decimal(
                    str(faiz_e.get()).strip().replace(",", ".")
                ).quantize(Decimal("0.01"))
                yeni_masraf = Decimal(
                    str(masraf_e.get()).strip().replace(",", ".")
                ).quantize(Decimal("0.01"))
                if yeni_anapara < 0 or yeni_faiz < 0 or yeni_masraf < 0:
                    raise ValueError("Tutarlar negatif olamaz.")
            except ValueError as hata:
                messagebox.showerror("Düzenle", str(hata), parent=dlg)
                return
            except Exception:
                messagebox.showerror("Düzenle", "Geçerli tarih / tutar girin.", parent=dlg)
                return
            eski_vade = satir["vade_tarihi"]
            satir["vade_tarihi"] = yeni_vade
            satir["anapara"] = yeni_anapara
            satir["faiz"] = yeni_faiz
            satir["masraf"] = yeni_masraf
            if kaydir_var.get() and yeni_vade != eski_vade:
                for j in range(idx + 1, len(self._plan)):
                    self._plan[j]["vade_tarihi"] = FinansService._ay_ekle(yeni_vade, j - idx)
            if idx == 0:
                self._ilk_manuel = True
                self.ilk_taksit.delete(0, "end")
                self.ilk_taksit.insert(0, yeni_vade.strftime("%d.%m.%Y"))
            self._plan_manuel = True
            self._ust_toplamlari_guncelle()
            self._plan_tabloyu_ciz()
            dlg.destroy()

        btns = ttk.Frame(dlg)
        btns.grid(row=5, column=0, columnspan=2, padx=12, pady=12, sticky="e")
        ttk.Button(btns, text="İptal", command=dlg.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Uygula", command=onayla).pack(side="right")
        faiz_e.focus_set()

    def kaydet(self):
        try:
            if not self._plan:
                raise ValueError(
                    "Taksit planı boş. «Planı Yenile» ile oluşturun."
                )
            faiz_t = sum((Decimal(str(s["faiz"])) for s in self._plan), Decimal("0"))
            masraf_t = sum((Decimal(str(s["masraf"])) for s in self._plan), Decimal("0"))
            ana_t = sum((Decimal(str(s["anapara"])) for s in self._plan), Decimal("0"))
            kullandirim = datetime.strptime(self.kullandirim.get().strip(), "%d.%m.%Y").date()
            ilk = self._plan[0]["vade_tarihi"]
            self.result = FinansService.banka_kredi_kullandir(
                banka_karti_id=self.banka_karti_id,
                kredi_adi=self.kredi_adi.get(),
                ana_para=ana_t if self._plan_manuel else self.ana_para.get(),
                kullandirim_tarihi=kullandirim,
                ilk_taksit_tarihi=ilk,
                taksit_sayisi=len(self._plan),
                toplam_faiz=faiz_t,
                toplam_masraf=masraf_t,
                kredi_turu=self._tur_map.get(self.kredi_turu.get(), "ISLETME"),
                odeme_hesap_turu=self._odeme_map.get(self.odeme_hesap.get(), "MEVDUAT"),
                sozlesme_no=self.sozlesme.get().strip() or None,
                aciklama=self.aciklama.get().strip() or None,
                taksit_plani=self._plan,
            )
        except ValueError as hata:
            messagebox.showerror("Kredi", str(hata), parent=self)
            return
        r = self.result
        ana = Decimal(str(r["ana_para"]))
        faiz = Decimal(str(r["toplam_faiz"]))
        masraf = Decimal(str(r["toplam_masraf"]))
        yekun = ana + faiz + masraf
        maliyet_metin = "—"
        try:
            kullandirim = datetime.strptime(
                self.kullandirim.get().strip(), "%d.%m.%Y"
            ).date() if hasattr(self, "kullandirim") else r.get("kullandirim_tarihi")
            # Dialog kapanmadan önce plan hâlâ bellekte
            plan = getattr(self, "_plan", None) or r.get("taksitler") or []
            if ana > 0 and plan:
                agirlikli = Decimal("0")
                for s in plan:
                    vade = s["vade_tarihi"]
                    ap = Decimal(str(s["anapara"]))
                    gun = max((vade - kullandirim).days, 0)
                    agirlikli += ap * Decimal(gun)
                ort = agirlikli / ana
                if ort > 0:
                    yillik = (
                        (faiz + masraf) / ana * (Decimal(365) / ort) * Decimal("100")
                    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    ort_q = ort.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    maliyet_metin = f"% {yillik} (ort. valör {ort_q} gün)"
        except Exception:
            maliyet_metin = "—"
        messagebox.showinfo(
            "Kullandırıldı",
            f"Belge: {r['belge_no']}\n"
            f"{r['kredi_adi']}\n"
            f"Ana para (kredi borcu): {_para(r['ana_para'])}\n"
            f"Faiz: {_para(r['toplam_faiz'])} · Masraf: {_para(r['toplam_masraf'])}\n"
            f"Yıllık maliyet (valör): {maliyet_metin}\n"
            f"Yekün geri ödenecek: {_para(yekun)}\n"
            f"{r['taksit_sayisi']} taksit — faiz/masraf ödeme gününde gider fişi kesilecek.",
            parent=self,
        )
        self.destroy()


class BankaKrediTaksitOdemeDialog(tk.Toplevel):
    """Taksit ödeme onayı — anapara kredi borcu, faiz/masraf gider fişi."""

    def __init__(self, parent, taksit_id):
        super().__init__(parent)
        self.taksit_id = taksit_id
        self.result = None
        self.title("Kredi Taksit Ödeme")
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        try:
            b = FinansService.banka_kredi_taksit_detay(taksit_id)
        except ValueError as hata:
            messagebox.showerror("Taksit", str(hata), parent=parent)
            self.destroy()
            return
        if (b.get("durum") or "") != "BEKLIYOR":
            messagebox.showinfo("Taksit", "Bu taksit zaten ödenmiş.", parent=parent)
            self.destroy()
            return

        toplam = b["toplam"]
        ttk.Label(
            self,
            text=f"{b['kredi_adi']} — {b['taksit_no']}/{b['taksit_sayisi']}. taksit",
            font=("Segoe UI", 11, "bold"),
        ).grid(row=0, column=0, columnspan=2, padx=14, pady=(14, 6), sticky="w")

        bilgiler = (
            ("Vade", _tarih(b["vade_tarihi"])),
            ("Anapara (kredi borcu)", _para(b["anapara"])),
            ("Faiz (gider fişi)", _para(b["faiz"])),
            ("Masraf (gider fişi)", _para(b["masraf"])),
            ("Ödenecek toplam", _para(toplam)),
            ("Ödeme hesabı", b["odeme_hesap_turu"]),
        )
        for i, (etiket, deger) in enumerate(bilgiler, start=1):
            ttk.Label(self, text=etiket).grid(row=i, column=0, padx=14, pady=3, sticky="w")
            ttk.Label(self, text=deger, font=("Segoe UI", 9, "bold")).grid(
                row=i, column=1, padx=14, pady=3, sticky="w"
            )

        row = len(bilgiler) + 1
        ttk.Label(self, text="Ödeme tarihi *").grid(row=row, column=0, padx=14, pady=8, sticky="w")
        tarih_c = ttk.Frame(self)
        tarih_c.grid(row=row, column=1, padx=14, pady=8, sticky="w")
        self.tarih = ttk.Entry(tarih_c, width=12)
        self.tarih.pack(side="left")
        self.tarih.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(tarih_c, self.tarih)

        row += 1
        ttk.Label(self, text="Açıklama").grid(row=row, column=0, padx=14, pady=4, sticky="w")
        self.aciklama = ttk.Entry(self, width=40)
        self.aciklama.grid(row=row, column=1, padx=14, pady=4, sticky="w")

        row += 1
        butonlar = ttk.Frame(self)
        butonlar.grid(row=row, column=0, columnspan=2, padx=14, pady=14, sticky="e")
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Öde", command=self.kaydet).pack(side="right")

    def kaydet(self):
        try:
            tarih = datetime.strptime(self.tarih.get().strip(), "%d.%m.%Y").date()
            self.result = FinansService.banka_kredi_taksit_ode(
                self.taksit_id,
                odeme_tarihi=tarih,
                aciklama=self.aciklama.get().strip() or None,
            )
        except ValueError as hata:
            messagebox.showerror("Ödeme", str(hata), parent=self)
            return
        r = self.result
        ekstra = "\nKredi tamamen kapandı." if r.get("kredi_kapandi") else ""
        gider = r.get("gider_belge_no") or "—"
        messagebox.showinfo(
            "Ödendi",
            f"Ödeme belgesi: {r['odeme_belge_no']}\n"
            f"Gider fişi: {gider}\n"
            f"Anapara: {_para(r['anapara'])}\n"
            f"Faiz gideri: {_para(r['faiz'])}\n"
            f"Masraf gideri: {_para(r['masraf'])}\n"
            f"Toplam: {_para(r['toplam'])}{ekstra}",
            parent=self,
        )
        self.destroy()


class AltHesapDuzenleDialog(tk.Toplevel):
    """Banka alt hesabı: şube, hesap no, IBAN, PB, bloke (Doc5)."""

    def __init__(self, parent, hesap_id: int):
        super().__init__(parent)
        self.result = None
        hesap = FinansService.hesap_getir(hesap_id)
        if not hesap:
            messagebox.showerror("Hesap", "Hesap bulunamadı.", parent=parent)
            self.destroy()
            return
        self.hesap_id = hesap.id
        tur = (hesap.alt_hesap_turu or "").upper()
        tur_ad = dict(BANKA_ALT_HESAP_TURLERI).get(tur, tur or "Hesap")
        self.title(f"Alt hesap — {tur_ad}")
        self.transient(parent)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        form = ttk.Frame(self, padding=12)
        form.pack(fill="both", expand=True)
        ttk.Label(form, text="Hesap adı").grid(row=0, column=0, sticky="w", pady=4)
        self.hesap_adi = ttk.Entry(form, width=42)
        self.hesap_adi.grid(row=0, column=1, sticky="w", padx=8, pady=4)
        self.hesap_adi.insert(0, hesap.hesap_adi or "")

        ttk.Label(form, text="Para birimi").grid(row=1, column=0, sticky="w", pady=4)
        self.para_birimi = ttk.Combobox(
            form, values=("TRY", "USD", "EUR"), state="readonly", width=10
        )
        pb = (getattr(hesap, "para_birimi", None) or "TRY").upper()
        self.para_birimi.set(pb if pb in ("TRY", "USD", "EUR") else "TRY")
        self.para_birimi.grid(row=1, column=1, sticky="w", padx=8, pady=4)

        ttk.Label(form, text="Şube adı").grid(row=2, column=0, sticky="w", pady=4)
        self.sube = ttk.Entry(form, width=42)
        self.sube.grid(row=2, column=1, sticky="w", padx=8, pady=4)
        self.sube.insert(0, hesap.sube or "")

        ttk.Label(form, text="Şube kodu").grid(row=3, column=0, sticky="w", pady=4)
        self.sube_kodu = ttk.Entry(form, width=16)
        self.sube_kodu.grid(row=3, column=1, sticky="w", padx=8, pady=4)
        self.sube_kodu.insert(0, getattr(hesap, "sube_kodu", None) or "")

        ttk.Label(form, text="Hesap no").grid(row=4, column=0, sticky="w", pady=4)
        self.hesap_no = ttk.Entry(form, width=28)
        self.hesap_no.grid(row=4, column=1, sticky="w", padx=8, pady=4)
        self.hesap_no.insert(0, getattr(hesap, "hesap_no", None) or "")

        ttk.Label(form, text="IBAN").grid(row=5, column=0, sticky="w", pady=4)
        self.iban = ttk.Entry(form, width=36)
        self.iban.grid(row=5, column=1, sticky="w", padx=8, pady=4)
        self.iban.insert(0, hesap.iban or "")

        ttk.Label(form, text="Bloke tutarı").grid(row=6, column=0, sticky="w", pady=4)
        self.bloke = ttk.Entry(form, width=16)
        self.bloke.grid(row=6, column=1, sticky="w", padx=8, pady=4)
        self.bloke.insert(0, str(getattr(hesap, "bloke_tutari", None) or 0))

        self.varsayilan = tk.BooleanVar(value=bool(getattr(hesap, "varsayilan", False)))
        ttk.Checkbutton(
            form, text="Bu sınıf için varsayılan hesap", variable=self.varsayilan
        ).grid(row=7, column=1, sticky="w", padx=8, pady=4)

        ttk.Label(form, text="Açıklama").grid(row=8, column=0, sticky="w", pady=4)
        self.aciklama = ttk.Entry(form, width=42)
        self.aciklama.grid(row=8, column=1, sticky="w", padx=8, pady=4)
        self.aciklama.insert(0, hesap.aciklama or "")

        butonlar = ttk.Frame(form)
        butonlar.grid(row=9, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(butonlar, text="Kaydet", command=self.kaydet).pack(side="right")

    def kaydet(self):
        try:
            self.result = FinansService.alt_hesap_kaydet(
                {
                    "hesap_id": self.hesap_id,
                    "hesap_adi": self.hesap_adi.get().strip(),
                    "para_birimi": self.para_birimi.get().strip(),
                    "sube": self.sube.get().strip(),
                    "sube_kodu": self.sube_kodu.get().strip(),
                    "hesap_no": self.hesap_no.get().strip(),
                    "iban": self.iban.get().strip(),
                    "bloke_tutari": self.bloke.get().strip(),
                    "varsayilan": self.varsayilan.get(),
                    "aciklama": self.aciklama.get().strip(),
                }
            )
        except ValueError as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        self.destroy()


class BankaAnaKartDialog(tk.Toplevel):
    """Banka ana kartı: Genel / Hesaplar / POS / Firma KK / Kredi / Mutabakat / Geçmiş."""

    def __init__(self, parent, kart=None):
        super().__init__(parent)
        if kart and getattr(kart, "id", None):
            kart = FinansService.banka_karti_getir(kart.id) or kart
        self.kart = kart
        self.result = None
        self.title("Banka Ana Kartı" + (f" — {kart.banka_adi}" if kart else " — Yeni"))
        self.geometry("1100x860")
        self.minsize(980, 740)
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)
        self.alanlar = {}
        self.pos_taksit_oranlari = {}
        self.bakiye_etiketleri = {}
        self.kmh_limit_lbl = None

        kayit = ttk.Frame(self, padding=(12, 8, 12, 12))
        kayit.pack(side="bottom", fill="x")
        ttk.Button(kayit, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(kayit, text="KAYDET", width=16, command=self.kaydet).pack(side="right")

        ttk.Label(
            self, text="BANKA ANA KARTI", style="Baslik.TLabel"
        ).pack(anchor="w", padx=12, pady=(10, 0))

        self.nb = ttk.Notebook(self)
        self.nb.pack(side="top", fill="both", expand=True, padx=12, pady=(6, 0))

        self._sekme_genel = ttk.Frame(self.nb, padding=8)
        self._sekme_hesaplar = ttk.Frame(self.nb, padding=8)
        self._sekme_pos = ttk.Frame(self.nb, padding=8)
        self._sekme_kk = ttk.Frame(self.nb, padding=8)
        self._sekme_kredi = ttk.Frame(self.nb, padding=8)
        self._sekme_mutabakat = ttk.Frame(self.nb, padding=8)
        self._sekme_gecmis = ttk.Frame(self.nb, padding=8)

        self.nb.add(self._sekme_genel, text="Genel Bilgiler")
        self.nb.add(self._sekme_hesaplar, text="Hesaplar")
        self.nb.add(self._sekme_pos, text="POS Sözleşmeleri")
        self.nb.add(self._sekme_kk, text="Firma Kredi Kartları")
        self.nb.add(self._sekme_kredi, text="Kredi Hareketleri")
        self.nb.add(self._sekme_mutabakat, text="Mutabakat")
        self.nb.add(self._sekme_gecmis, text="İşlem Geçmişi")

        self._genel_sekmesini_kur(kart)
        self._pos_sekmesini_kur(kart)
        self._hesaplar_sekmesini_kur()
        self._kk_sekmesini_kur()
        self._kredi_sekmesini_kur()
        self._mutabakat_sekmesini_kur()
        self._gecmis_sekmesini_kur()

        self.nb.bind("<<NotebookTabChanged>>", self._sekme_degisti)
        self.bakiyeleri_yenile()
        # Ağır sekme listeleri (KK borç özeti, krediler, geçmiş) açılışta çekilmez —
        # sekme seçilince yüklenir (donma / UI blok önlemi).
        self._sekme_yuklendi = {0: True}

    def _genel_sekmesini_kur(self, kart):
        ust = self._sekme_genel
        sol = ttk.Frame(ust)
        sol.pack(side="left", fill="both", expand=True)
        sag = ttk.LabelFrame(ust, text="HESAP BAKİYELERİ", padding=14)
        sag.pack(side="right", fill="y", padx=(16, 0))

        form = ttk.LabelFrame(sol, text="Hesap bilgileri", padding=12)
        form.pack(fill="x")

        ttk.Label(form, text="Banka Adı").grid(row=0, column=0, sticky="w", padx=4, pady=5)
        banka_adi = ttk.Combobox(form, values=FinansService.banka_adi_listesi(), width=36)
        banka_adi.grid(row=0, column=1, sticky="ew", padx=4, pady=5)
        self.alanlar["banka_adi"] = banka_adi
        ttk.Button(form, text="Yeni", width=8, command=self.yeni_banka_karti).grid(
            row=0, column=2, padx=(0, 4), pady=5
        )

        ttk.Label(form, text="Açıklama").grid(row=1, column=0, sticky="w", padx=4, pady=5)
        self.alanlar["aciklama"] = ttk.Entry(form, width=42)
        self.alanlar["aciklama"].grid(row=1, column=1, columnspan=2, sticky="ew", padx=4, pady=5)
        form.columnconfigure(1, weight=1)
        ttk.Label(
            form,
            text="Şube, hesap no ve IBAN her alt hesapta (Hesaplar sekmesi → Düzenle) tanımlanır.",
            foreground="#555",
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=4, pady=(0, 4))

        kmh_ayar = ttk.LabelFrame(sol, text="KMH (kredili mevduat) limiti", padding=10)
        kmh_ayar.pack(fill="x", pady=(10, 0))
        ttk.Label(kmh_ayar, text="KMH limiti (eksi bakiyeye kadar)").grid(
            row=0, column=0, sticky="w", padx=4, pady=4
        )
        self.alanlar["kmh_limiti"] = ttk.Entry(kmh_ayar, width=16)
        self.alanlar["kmh_limiti"].grid(row=0, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(
            kmh_ayar,
            text="KMH hem + hem − olabilir; limit kadar eksiye düşer. Eksi bakiye kırmızı/− gösterilir.",
            foreground="#555",
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=4, pady=(2, 0))

        if kart:
            banka_adi.set(kart.banka_adi or "")
            self.alanlar["aciklama"].insert(0, kart.aciklama or "")
            self.alanlar["kmh_limiti"].insert(0, str(kart.kmh_limiti or 0))
        else:
            self.alanlar["kmh_limiti"].insert(0, "0")

        try:
            bakiye_bg = self.cget("bg")
        except tk.TclError:
            bakiye_bg = "SystemButtonFace"
        for kod, etiket in BANKA_ALT_HESAP_TURLERI:
            satir = ttk.Frame(sag)
            satir.pack(fill="x", pady=6)
            ttk.Label(satir, text=etiket, width=20).pack(side="left")
            lbl = tk.Label(
                satir,
                text=_para_bakiye(0),
                font=("Segoe UI", 10, "bold"),
                width=18,
                anchor="e",
                fg=_bakiye_renk(0),
                bg=bakiye_bg,
            )
            lbl.pack(side="right")
            self.bakiye_etiketleri[kod] = lbl
            if kod == "KMH":
                self.kmh_limit_lbl = ttk.Label(
                    sag, text="KMH limiti: —", foreground="#555", font=("Segoe UI", 8)
                )
                self.kmh_limit_lbl.pack(anchor="e", pady=(0, 4))

        ttk.Separator(sag, orient="horizontal").pack(fill="x", pady=(10, 8))
        self.ozet_varlik_lbl = tk.Label(
            sag,
            text="Varlıklar: —",
            font=("Segoe UI", 9, "bold"),
            fg=_bakiye_renk(0),
            bg=bakiye_bg,
            anchor="e",
        )
        self.ozet_varlik_lbl.pack(anchor="e")
        self.ozet_borc_lbl = tk.Label(
            sag,
            text="Borçlar: —",
            font=("Segoe UI", 9, "bold"),
            fg=_bakiye_renk(0),
            bg=bakiye_bg,
            anchor="e",
        )
        self.ozet_borc_lbl.pack(anchor="e", pady=(2, 0))
        self.ozet_net_lbl = tk.Label(
            sag,
            text="Net (Varlık − Borç): —",
            font=("Segoe UI", 9, "bold"),
            fg=_bakiye_renk(0),
            bg=bakiye_bg,
            anchor="e",
        )
        self.ozet_net_lbl.pack(anchor="e", pady=(4, 0))
        ttk.Label(
            sag,
            text=(
                "İşletme yönü: varlık/alacak +, borç −. "
                "POS = açık PosValor alacağı. "
                "KMH limiti varlığa eklenmez."
            ),
            foreground="#555",
            font=("Segoe UI", 8),
            wraplength=220,
        ).pack(anchor="e", pady=(4, 0))

        ttk.Label(
            sol,
            text="Kartı kaydettikten sonra alt hesap bakiyeleri ve işlem menüleri aktif olur.",
            foreground="#555",
        ).pack(anchor="w", pady=(10, 4))

        islem = ttk.LabelFrame(sol, text="İşlem menüleri", padding=10)
        islem.pack(fill="x", pady=(8, 0))
        from database.hesap_siralama import sinif_ciftlerini_sirala

        menu_ogeleri = sinif_ciftlerini_sirala(
            list(BANKA_ALT_HESAP_TURLERI) + [("YATIRIM", "Yatırım Hesapları")]
        )
        for i, (kod, etiket) in enumerate(menu_ogeleri):
            if kod == "POS":
                dugme_metin = "POS Hesapları"
            elif kod == "YATIRIM":
                dugme_metin = "Yatırım Hesapları"
            else:
                dugme_metin = etiket.replace(" Hesabı", "") + " İşlemleri"
            ttk.Button(
                islem,
                text=dugme_metin,
                width=28,
                command=lambda k=kod, e=etiket: self._islem_ac(k, e),
            ).grid(row=i // 3, column=i % 3, padx=6, pady=6, sticky="ew")
        n = len(menu_ogeleri)
        ttk.Button(islem, text="Muhasebe Hesapları", width=28, command=self._muhasebe_hesaplari).grid(
            row=n // 3, column=n % 3, padx=6, pady=6, sticky="ew"
        )
        for c in range(3):
            islem.columnconfigure(c, weight=1)

        from banka_alt_hesap_detay_ui import BankaAltHesapDetayDialog

        ttk.Button(
            islem,
            text="Banka Hesapları",
            width=28,
            command=lambda: (
                BankaAltHesapDetayDialog(self, self.kart.id) if self.kart else None
            ),
        ).grid(row=(n + 1) // 3, column=(n + 1) % 3, padx=6, pady=6, sticky="ew")

    def _pos_sekmesini_kur(self, kart):
        sol = self._sekme_pos
        pos_ayar = ttk.LabelFrame(sol, text="POS sözleşmesi (komisyon / valör / hedef)", padding=10)
        pos_ayar.pack(fill="x")
        ttk.Label(pos_ayar, text="Kredi kartı (tek çekim yedek) %").grid(
            row=0, column=0, sticky="w", padx=4, pady=4
        )
        self.alanlar["kk_komisyon_orani"] = ttk.Entry(pos_ayar, width=12)
        self.alanlar["kk_komisyon_orani"].grid(row=0, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(pos_ayar, text="Banka kartı komisyon %").grid(
            row=0, column=2, sticky="w", padx=(16, 4), pady=4
        )
        self.alanlar["banka_karti_komisyon_orani"] = ttk.Entry(pos_ayar, width=12)
        self.alanlar["banka_karti_komisyon_orani"].grid(row=0, column=3, sticky="w", padx=4, pady=4)

        ttk.Label(pos_ayar, text="Valör gün sayısı").grid(
            row=1, column=0, sticky="w", padx=4, pady=4
        )
        self.alanlar["pos_valor_gun"] = ttk.Entry(pos_ayar, width=12)
        self.alanlar["pos_valor_gun"].grid(row=1, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(pos_ayar, text="Gün türü").grid(
            row=1, column=2, sticky="w", padx=(16, 4), pady=4
        )
        self.alanlar["pos_valor_is_gunu"] = ttk.Combobox(
            pos_ayar, values=("İş günü", "Takvim günü"), state="readonly", width=14
        )
        self.alanlar["pos_valor_is_gunu"].grid(row=1, column=3, sticky="w", padx=4, pady=4)
        self.alanlar["pos_valor_is_gunu"].set("İş günü")

        ttk.Label(pos_ayar, text="Aktarımın Yatacağı Hesap").grid(
            row=2, column=0, sticky="w", padx=4, pady=4
        )
        self.alanlar["pos_aktarim_hesap"] = ttk.Combobox(
            pos_ayar, state="readonly", width=42
        )
        self.alanlar["pos_aktarim_hesap"].grid(
            row=2, column=1, columnspan=3, sticky="we", padx=4, pady=4
        )
        self._pos_aktarim_hesap_map: dict[str, int] = {}
        # Gizli tür alanı (kayıt senkronu / eski kod uyumu)
        self.alanlar["pos_hedef_hesap_turu"] = ttk.Combobox(
            pos_ayar, values=("MEVDUAT", "KMH"), state="readonly", width=12
        )
        # grid'e eklenmez — yalnızca kaydet verisi
        self.alanlar["pos_hedef_hesap_turu"].set("MEVDUAT")
        ttk.Label(pos_ayar, text="Bankaya aktarım yöntemi").grid(
            row=3, column=0, sticky="w", padx=4, pady=4
        )
        self.alanlar["pos_aktarim_yontemi"] = ttk.Combobox(
            pos_ayar, values=("Manuel", "Otomatik"), state="readonly", width=14
        )
        self.alanlar["pos_aktarim_yontemi"].grid(row=3, column=1, sticky="w", padx=4, pady=4)
        self.alanlar["pos_aktarim_yontemi"].set("Manuel")
        # Geriye uyumluluk: kayıtta pos_otomatik_mahsup ile senkron
        self.alanlar["pos_otomatik_mahsup"] = self.alanlar["pos_aktarim_yontemi"]
        ttk.Label(pos_ayar, text="Otomatik geçerlilik başlangıcı").grid(
            row=3, column=2, sticky="w", padx=(16, 4), pady=4
        )
        bas_c = ttk.Frame(pos_ayar)
        bas_c.grid(row=3, column=3, sticky="w", padx=4, pady=4)
        self.alanlar["pos_otomatik_baslangic"] = ttk.Entry(bas_c, width=12)
        self.alanlar["pos_otomatik_baslangic"].pack(side="left")
        takvim_butonu(bas_c, self.alanlar["pos_otomatik_baslangic"])
        ttk.Label(
            pos_ayar,
            text="Aktarım hesabı mevduat veya KMH seçilir (kimlikle kaydedilir). Ayar değişince geçmiş aktarımlar değişmez. Manuel: Bankaya Aktar; Otomatik: valörde uygulama fişi.",
            foreground="#555",
        ).grid(row=4, column=0, columnspan=4, sticky="w", padx=4, pady=(2, 0))
        self._pos_aktarim_hedeflerini_doldur(kart)

        taksit_oran = ttk.LabelFrame(
            sol, text="POS hesabı taksit komisyon oranları (kredi kartı, max 12 ay)", padding=10
        )
        taksit_oran.pack(fill="x", pady=(10, 0))
        ttk.Label(
            taksit_oran,
            text="Her taksit sayısı için komisyon % — tahsilatta banka masrafı bu orana göre kesilir.",
            foreground="#555",
        ).pack(anchor="w", pady=(0, 6))
        oran_grid = ttk.Frame(taksit_oran)
        oran_grid.pack(fill="x")
        mevcut_oranlar = {}
        if kart:
            mevcut_oranlar = {
                int(r.taksit_sayisi): Decimal(str(r.komisyon_orani or 0))
                for r in (kart.pos_taksit_komisyonlari or [])
            }
            if 1 not in mevcut_oranlar or mevcut_oranlar.get(1, 0) == 0:
                mevcut_oranlar[1] = Decimal(str(kart.kk_komisyon_orani or 0))
        for i in range(1, POS_MAX_TAKSIT + 1):
            r, c = (i - 1) // 6, ((i - 1) % 6) * 2
            ttk.Label(oran_grid, text=f"{i}. ay %").grid(row=r, column=c, sticky="w", padx=(4, 2), pady=3)
            ent = ttk.Entry(oran_grid, width=7)
            ent.grid(row=r, column=c + 1, sticky="w", padx=(0, 10), pady=3)
            baslangic = mevcut_oranlar.get(i, Decimal("0"))
            ent.insert(0, f"{baslangic:g}" if baslangic else "0")
            self.pos_taksit_oranlari[i] = ent

        if kart:
            self.alanlar["kk_komisyon_orani"].insert(0, str(kart.kk_komisyon_orani or 0))
            self.alanlar["banka_karti_komisyon_orani"].insert(
                0, str(kart.banka_karti_komisyon_orani or 0)
            )
            self.alanlar["pos_valor_gun"].insert(
                0, str(kart.pos_valor_gun if kart.pos_valor_gun is not None else 1)
            )
            is_g = getattr(kart, "pos_valor_is_gunu", True)
            self.alanlar["pos_valor_is_gunu"].set(
                "İş günü" if (is_g is None or is_g) else "Takvim günü"
            )
            yontem = (getattr(kart, "pos_aktarim_yontemi", None) or "").strip().upper()
            if not yontem:
                yontem = "OTOMATIK" if getattr(kart, "pos_otomatik_mahsup", False) else "MANUEL"
            self.alanlar["pos_aktarim_yontemi"].set(
                "Otomatik" if yontem == "OTOMATIK" else "Manuel"
            )
            bas = getattr(kart, "pos_otomatik_baslangic", None)
            if bas:
                self.alanlar["pos_otomatik_baslangic"].insert(0, bas.strftime("%d.%m.%Y"))
        else:
            self.alanlar["kk_komisyon_orani"].insert(0, "0")
            self.alanlar["banka_karti_komisyon_orani"].insert(0, "0")
            self.alanlar["pos_valor_gun"].insert(0, "1")
            self.alanlar["pos_aktarim_yontemi"].set("Manuel")

        btn = ttk.Frame(sol)
        btn.pack(fill="x", pady=(12, 0))
        ttk.Button(
            btn,
            text="POS Hesapları",
            command=lambda: self._islem_ac("POS", "POS Hesabı"),
        ).pack(side="left")

    def _pos_aktarim_hedeflerini_doldur(self, kart):
        """POS sekmesi: mevduat/KMH listesi; seçim hesap kimliğiyle kaydedilir."""
        self._pos_aktarim_hesap_map = {}
        etiketler = []
        onerilen_id = None
        if kart is not None:
            onerilen_id = getattr(kart, "pos_aktarim_hesap_id", None)
            for h in FinansService.pos_aktarim_hedefleri(kart.id):
                et = h["etiket"]
                self._pos_aktarim_hesap_map[et] = int(h["id"])
                etiketler.append(et)
            if onerilen_id is None:
                hedef = FinansService._pos_hedef_hesap(kart)
                if hedef is not None:
                    onerilen_id = int(hedef.id)
        cb = self.alanlar.get("pos_aktarim_hesap")
        if cb is None:
            return
        cb.configure(values=etiketler)
        secildi = False
        if onerilen_id is not None:
            for et, hid in self._pos_aktarim_hesap_map.items():
                if hid == int(onerilen_id):
                    cb.set(et)
                    tur = "KMH" if "(KMH)" in et else "MEVDUAT"
                    self.alanlar["pos_hedef_hesap_turu"].set(tur)
                    secildi = True
                    break
        if not secildi and etiketler:
            cb.set(etiketler[0])
            tur = "KMH" if "(KMH)" in etiketler[0] else "MEVDUAT"
            self.alanlar["pos_hedef_hesap_turu"].set(tur)
        elif not etiketler:
            cb.set("")

    def _hesaplar_sekmesini_kur(self):
        f = self._sekme_hesaplar
        ttk.Label(
            f,
            text="Bu bankanın alt hesapları. Çift tık = ilgili işlem menüsü.",
            foreground="#555",
        ).pack(anchor="w", pady=(0, 6))
        cerceve = ttk.Frame(f)
        cerceve.pack(fill="both", expand=True)
        self.hesaplar_tablo = ttk.Treeview(
            cerceve,
            columns=("tur", "ad", "pb", "sube", "hesap_no", "iban", "bakiye", "durum"),
            show="headings",
            selectmode="browse",
        )
        for k, b, w in (
            ("tur", "Sınıf", 100),
            ("ad", "Hesap adı", 180),
            ("pb", "PB", 45),
            ("sube", "Şube", 90),
            ("hesap_no", "Hesap no", 110),
            ("iban", "IBAN", 190),
            ("bakiye", "Bakiye", 100),
            ("durum", "Durum", 55),
        ):
            self.hesaplar_tablo.heading(k, text=b)
            self.hesaplar_tablo.column(k, width=w, anchor="w")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.hesaplar_tablo.yview)
        self.hesaplar_tablo.configure(yscrollcommand=kaydir.set)
        self.hesaplar_tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        self.hesaplar_tablo.bind("<Double-1>", self._hesap_cift_tik)

        alt = ttk.Frame(f)
        alt.pack(fill="x", pady=(8, 0))
        ttk.Button(alt, text="Yenile", command=self._hesaplari_yenile).pack(side="left")
        ttk.Button(alt, text="Düzenle", command=self._hesap_duzenle).pack(side="left", padx=6)
        ttk.Button(alt, text="İşlem Aç", command=self._hesap_islem_ac).pack(side="left", padx=6)
        ttk.Button(
            alt, text="Sınıf menüsünde göster", command=self._sinif_menusunde_goster
        ).pack(side="left", padx=6)

    def _kk_sekmesini_kur(self):
        f = self._sekme_kk
        self.kk_ozet_lbl = ttk.Label(f, text="", font=("Segoe UI", 10, "bold"))
        self.kk_ozet_lbl.pack(anchor="w", pady=(0, 6))

        menu = ttk.Frame(f)
        menu.pack(fill="x", pady=(0, 6))
        ttk.Button(menu, text="Kredi Kartı İşlemleri", command=self._kk_islemleri_ac).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(menu, text="Tüm firma kredi kartları", command=self._tum_firma_kartlari).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(menu, text="Tarihleri değiştir", command=self._kk_tarihleri_degistir).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(menu, text="Yenile", command=self._kk_listesini_yenile).pack(side="left")

        cerceve = ttk.Frame(f)
        cerceve.pack(fill="both", expand=True)
        self.kk_tablo = ttk.Treeview(
            cerceve,
            columns=(
                "ad", "marka", "no", "pb", "limit", "borc", "ekstre", "gelecek",
                "gecikmis", "kalan", "son_kesim", "sonraki_kesim", "son_odeme",
            ),
            show="headings",
            selectmode="browse",
        )
        for k, b, w in (
            ("ad", "Kart adı", 120),
            ("marka", "Marka", 60),
            ("no", "Kart no", 70),
            ("pb", "PB", 40),
            ("limit", "Limit", 80),
            ("borc", "Toplam borç", 90),
            ("ekstre", "Ekstre kalan", 90),
            ("gelecek", "Gelecek taksit", 95),
            ("gecikmis", "Gecikmiş", 80),
            ("kalan", "Kullanılabilir", 95),
            ("son_kesim", "Son kesim", 85),
            ("sonraki_kesim", "Sonraki kesim", 100),
            ("son_odeme", "Son ödeme", 85),
        ):
            self.kk_tablo.heading(k, text=b)
            self.kk_tablo.column(k, width=w, anchor="w")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.kk_tablo.yview)
        self.kk_tablo.configure(yscrollcommand=kaydir.set)
        self.kk_tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        self.kk_tablo.bind("<Double-1>", lambda _e: self._kk_islemleri_ac(secili=True))

    def _kredi_sekmesini_kur(self):
        f = self._sekme_kredi
        self.kredi_ozet_lbl = ttk.Label(f, text="", font=("Segoe UI", 10, "bold"))
        self.kredi_ozet_lbl.pack(anchor="w", pady=(0, 6))

        menu = ttk.Frame(f)
        menu.pack(fill="x", pady=(0, 6))
        ttk.Button(
            menu,
            text="Kredi İşlemleri",
            command=lambda: self._islem_ac("KREDILER", "Krediler Hesabı"),
        ).pack(side="left", padx=(0, 6))
        ttk.Button(menu, text="Yenile", command=self._kredi_listesini_yenile).pack(side="left")

        cerceve = ttk.Frame(f)
        cerceve.pack(fill="both", expand=True)
        self.kredi_tablo = ttk.Treeview(
            cerceve,
            columns=(
                "belge", "ad", "tur", "tarih", "anapara", "faiz",
                "taksit", "taksit_tutari", "kalan", "durum",
            ),
            show="headings",
            selectmode="browse",
        )
        for k, b, w in (
            ("belge", "Belge", 110),
            ("ad", "Kredi", 160),
            ("tur", "Tür", 100),
            ("tarih", "Kullandırım", 90),
            ("anapara", "Ana para", 100),
            ("faiz", "Faiz", 90),
            ("taksit", "Taksit Sayısı", 75),
            ("taksit_tutari", "Taksit Tutarı", 120),
            ("kalan", "Kalan anapara", 110),
            ("durum", "Durum", 90),
        ):
            self.kredi_tablo.heading(k, text=b)
            self.kredi_tablo.column(k, width=w, anchor="w")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.kredi_tablo.yview)
        self.kredi_tablo.configure(yscrollcommand=kaydir.set)
        self.kredi_tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        self.kredi_tablo.bind(
            "<Double-1>",
            lambda _e: self._islem_ac("KREDILER", "Krediler Hesabı"),
        )

    def _mutabakat_sekmesini_kur(self):
        f = self._sekme_mutabakat
        ttk.Label(
            f,
            text=(
                "Banka ekstresi ile program bakiyesini karşılaştırın. "
                "Alt hesap hareketlerini açıp tarih aralığına göre kontrol edin."
            ),
            wraplength=900,
            foreground="#333",
        ).pack(anchor="w", pady=(0, 8))

        self.mutabakat_ozet = ttk.Label(f, text="", font=("Segoe UI", 10, "bold"))
        self.mutabakat_ozet.pack(anchor="w", pady=(0, 8))

        btn = ttk.Frame(f)
        btn.pack(fill="x", pady=(0, 8))
        ttk.Button(btn, text="Yenile", command=self._mutabakati_yenile).pack(side="left")
        ttk.Button(
            btn,
            text="Mevduat İşlemleri",
            command=lambda: self._islem_ac("MEVDUAT", "Mevduat Hesabı"),
        ).pack(side="left", padx=6)
        ttk.Button(
            btn,
            text="Banka Hesapları Detay",
            command=self._banka_hesap_detay_ac,
        ).pack(side="left", padx=6)

        cerceve = ttk.Frame(f)
        cerceve.pack(fill="both", expand=True)
        self.mutabakat_tablo = ttk.Treeview(
            cerceve,
            columns=("tur", "ad", "pb", "hesap_no", "iban", "bakiye", "not"),
            show="headings",
            height=10,
        )
        for k, b, w in (
            ("tur", "Sınıf", 100),
            ("ad", "Hesap", 200),
            ("pb", "PB", 45),
            ("hesap_no", "Hesap no", 110),
            ("iban", "IBAN", 180),
            ("bakiye", "Program bakiyesi", 120),
            ("not", "Not", 160),
        ):
            self.mutabakat_tablo.heading(k, text=b)
            self.mutabakat_tablo.column(k, width=w, anchor="w")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.mutabakat_tablo.yview)
        self.mutabakat_tablo.configure(yscrollcommand=kaydir.set)
        self.mutabakat_tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        ttk.Label(
            f,
            text=(
                "Program bakiyesi onaylı fiş olmadan değiştirilmez. "
                "POS bekleyen valör = planlanan yatış (gerçek banka yatışından ayrı). "
                "Dosyadan ekstre aktarımı sonraki adımda bağlanır."
            ),
            wraplength=900,
            foreground="#555",
        ).pack(anchor="w", pady=(8, 0))

    def _gecmis_sekmesini_kur(self):
        f = self._sekme_gecmis
        ttk.Label(
            f,
            text="Tüm alt hesapların son hareketleri (tarih / kimlik sırası).",
            foreground="#555",
        ).pack(anchor="w", pady=(0, 6))
        ust = ttk.Frame(f)
        ust.pack(fill="x", pady=(0, 6))
        ttk.Button(ust, text="Yenile", command=self._gecmisi_yenile).pack(side="left")

        cerceve = ttk.Frame(f)
        cerceve.pack(fill="both", expand=True)
        self.gecmis_tablo = ttk.Treeview(
            cerceve,
            columns=("tarih", "hesap", "tur", "belge", "giris", "cikis", "aciklama"),
            show="headings",
        )
        _hareket_kolonlari_ayarla(
            self.gecmis_tablo,
            (
                ("tarih", "Tarih", 90),
                ("hesap", "Hesap", 140),
                ("tur", "Hareket", 140),
                ("belge", "Belge", 110),
                ("giris", "Giriş", 100),
                ("cikis", "Çıkış", 100),
                ("aciklama", "Açıklama", 260),
            ),
        )
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.gecmis_tablo.yview)
        self.gecmis_tablo.configure(yscrollcommand=kaydir.set)
        self.gecmis_tablo.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        _hareket_tablo_stil(self.gecmis_tablo)

    def _sekme_degisti(self, _e=None):
        self._sekmeleri_yenile(zorla=False)

    def _sekmeleri_yenile(self, *, zorla: bool = True):
        try:
            idx = self.nb.index(self.nb.select())
        except tk.TclError:
            return
        yuklendi = getattr(self, "_sekme_yuklendi", None)
        if yuklendi is None:
            self._sekme_yuklendi = {}
            yuklendi = self._sekme_yuklendi
        if not zorla and yuklendi.get(idx):
            return
        if idx == 1:
            self._hesaplari_yenile()
        elif idx == 3:
            self._kk_listesini_yenile()
        elif idx == 4:
            self._kredi_listesini_yenile()
        elif idx == 5:
            self._mutabakati_yenile()
        elif idx == 6:
            self._gecmisi_yenile()
        yuklendi[idx] = True

    def _kayit_gerekli(self, baslik="Kayıt"):
        if self.kart:
            return True
        messagebox.showinfo(baslik, "Önce banka kartını kaydedin.", parent=self)
        return False

    def _hesaplari_yenile(self):
        from database.hesap_siralama import hesap_sinif_gorunen_adi, hesaplari_sirala

        onceki = None
        try:
            sec = self.hesaplar_tablo.selection()
            if sec:
                onceki = sec[0]
        except tk.TclError:
            onceki = None
        for item in self.hesaplar_tablo.get_children():
            self.hesaplar_tablo.delete(item)
        if not self.kart:
            return
        kart = FinansService.banka_karti_getir(self.kart.id)
        if not kart:
            return
        self.kart = kart
        for h in hesaplari_sirala(kart.alt_hesaplar or []):
            kod = (h.alt_hesap_turu or "").upper()
            if kod == "POS":
                varlik = FinansService.pos_hesap_gosterim_bakiyesi(h)
            else:
                varlik = FinansService.isletme_bakiyesi(h)
            sinif = hesap_sinif_gorunen_adi(h) or "—"
            iban = (getattr(h, "iban", None) or "").strip() or "—"
            sube = (getattr(h, "sube", None) or "").strip() or "—"
            hesap_no = (getattr(h, "hesap_no", None) or "").strip() or "—"
            self.hesaplar_tablo.insert(
                "",
                "end",
                iid=str(h.id),
                values=(
                    sinif,
                    h.hesap_adi or "—",
                    getattr(h, "para_birimi", None) or "TRY",
                    sube,
                    hesap_no,
                    iban,
                    _para_bakiye(varlik),
                    "Aktif" if h.aktif else "Pasif",
                ),
                tags=(kod,),
            )
        if onceki and onceki in self.hesaplar_tablo.get_children():
            self.hesaplar_tablo.selection_set(onceki)
            self.hesaplar_tablo.focus(onceki)
            self.hesaplar_tablo.see(onceki)

    def _hesap_cift_tik(self, _e=None):
        self._hesap_duzenle()

    def _hesap_duzenle(self):
        if not self._kayit_gerekli("Hesap"):
            return
        secim = self.hesaplar_tablo.selection()
        if not secim:
            messagebox.showinfo("Hesap", "Düzenlemek için bir hesap seçin.", parent=self)
            return
        dialog = AltHesapDuzenleDialog(self, int(secim[0]))
        self.wait_window(dialog)
        if dialog.result:
            self.bakiyeleri_yenile()
            self._hesaplari_yenile()

    def _hesap_islem_ac(self):
        if not self._kayit_gerekli("Hesap"):
            return
        secim = self.hesaplar_tablo.selection()
        if not secim:
            messagebox.showinfo("Hesap", "Listeden bir hesap seçin.", parent=self)
            return
        tags = self.hesaplar_tablo.item(secim[0], "tags") or ()
        kod = tags[0] if tags else ""
        etiket = dict(BANKA_ALT_HESAP_TURLERI).get(kod, kod)
        if kod.startswith("VADELI") or kod == "YATIRIM":
            self._islem_ac("YATIRIM", "Yatırım Hesapları")
        elif kod == "POS":
            # Seçili POS hesabını doğrudan aç
            kart = FinansService.banka_karti_getir(self.kart.id)
            if kart:
                dialog = PosIslemleriDialog(self, kart, pos_hesap_id=int(secim[0]))
                self.wait_window(dialog)
                self.bakiyeleri_yenile()
                self._sekmeleri_yenile()
        elif kod:
            self._islem_ac(kod, etiket)

    def _sinif_menusunde_goster(self):
        """Seçili hesabın sınıf menüsüne geç (aynı kayıt kaynağı)."""
        if not self._kayit_gerekli("Hesap"):
            return
        secim = self.hesaplar_tablo.selection()
        if not secim:
            messagebox.showinfo("Hesap", "Sınıf menüsü için bir hesap seçin.", parent=self)
            return
        tags = self.hesaplar_tablo.item(secim[0], "tags") or ()
        kod = (tags[0] if tags else "").upper()
        hedef = _finans_app_kok(self)
        try:
            self.destroy()
        except tk.TclError:
            pass
        if hedef is None or not hasattr(hedef, "_icerigi_temizle"):
            messagebox.showinfo(
                "Sınıf menüsü",
                "Finans menüsünden ilgili sınıf ekranını açabilirsiniz.",
            )
            return
        if kod in ("MEVDUAT", "KMH") or kod.startswith("VADELI"):
            mevduat_kmh_hesaplari_sayfasi_goster(hedef)
        elif kod == "KREDI_KARTI":
            firma_kredi_kartlari_sayfasi_goster(hedef)
        elif kod == "KREDILER" and banka_kredileri_menusu_goster:
            banka_kredileri_menusu_goster(hedef)
        elif kod == "POS":
            messagebox.showinfo(
                "POS",
                "POS alacakları banka kartı → POS Sözleşmeleri / POS İşlemleri üzerinden izlenir.",
                parent=hedef,
            )
        else:
            finans_menusu_goster(hedef)

    def _kk_listesini_yenile(self):
        for item in self.kk_tablo.get_children():
            self.kk_tablo.delete(item)
        if not self.kart:
            self.kk_ozet_lbl.configure(text="Kart kaydedilince firma kredi kartları listelenir.")
            return
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        kartlar = FinansService.kredi_kartlari(banka_karti_id=self.kart.id)
        pb_borc: dict[str, Decimal] = {}
        pb_ekstre: dict[str, Decimal] = {}
        pb_gelecek: dict[str, Decimal] = {}
        pb_gecikmis: dict[str, Decimal] = {}
        for kk in kartlar:
            oz = KrediKartiEkstreService.kart_borc_ozeti(int(kk.id))
            tarihler = KrediKartiEkstreService.kart_tarih_ozeti(kk)
            pb = (oz.get("para_birimi") or getattr(kk, "para_birimi", None) or "TRY").upper()
            borc = Decimal(str(oz.get("toplam_borc") or 0))
            ekstre = Decimal(str(oz.get("kesilmis_kalan") or 0))
            gelecek = Decimal(str(oz.get("kesilmemis") or 0))
            gecikmis = Decimal(str(oz.get("gecikmis") or 0))
            pb_borc[pb] = pb_borc.get(pb, Decimal("0")) + borc
            pb_ekstre[pb] = pb_ekstre.get(pb, Decimal("0")) + ekstre
            pb_gelecek[pb] = pb_gelecek.get(pb, Decimal("0")) + gelecek
            pb_gecikmis[pb] = pb_gecikmis.get(pb, Decimal("0")) + gecikmis
            maske = f"****{kk.son_dort_hane}" if kk.son_dort_hane else "—"
            limit = Decimal(str(kk.kart_limiti or 0))
            self.kk_tablo.insert(
                "",
                "end",
                iid=str(kk.id),
                values=(
                    kk.kart_adi,
                    kk.kart_markasi or "—",
                    maske,
                    pb,
                    _para(limit, pb) if limit else "Limit tanımsız",
                    _para(borc, pb),
                    _para(ekstre, pb),
                    _para(gelecek, pb),
                    _para(gecikmis, pb),
                    _para(oz["kullanilabilir"], pb) if oz.get("limit_tanimli") else "—",
                    tarihler.get("son_kesim_metin", "—"),
                    tarihler.get("sonraki_kesim_metin", "—"),
                    tarihler.get("son_odeme_metin", "—"),
                ),
            )

        def _pb_parca(etiket, sozluk):
            return " · ".join(f"{p}: {_para(t, p)}" for p, t in sorted(sozluk.items()) if t)

        parcalar = [
            x
            for x in (
                _pb_parca("borç", pb_borc),
                _pb_parca("ekstre", pb_ekstre),
                _pb_parca("gelecek", pb_gelecek),
                _pb_parca("gecikmiş", pb_gecikmis),
            )
            if x
        ]
        ozet_metin = f"{len(kartlar)} kart"
        if parcalar:
            ozet_metin += "  ·  " + "  |  ".join(parcalar)
            if len(pb_borc) > 1:
                ozet_metin += "  (farklı PB toplanmaz)"
        self.kk_ozet_lbl.configure(text=ozet_metin)

    def _kk_islemleri_ac(self, *, secili: bool = False):
        """Eski Kredi Kartı İşlemleri ekranı (bağımsız FİRMA KREDİ KARTI paneli değil)."""
        if not self.kart:
            messagebox.showinfo(
                "Kayıt",
                "İşlem menüsü için önce banka kartını kaydedin.",
                parent=self,
            )
            return
        kk_id = self._kk_secili_id() if secili else None
        dialog = KrediKartiIslemleriDialog(self, self.kart, kredi_karti_id=kk_id)
        self.wait_window(dialog)
        self.bakiyeleri_yenile()
        self._sekme_yuklendi[3] = False
        self._kk_listesini_yenile()
        self._sekme_yuklendi[3] = True

    def _kk_secili_id(self):
        secim = self.kk_tablo.selection()
        if secim:
            return int(secim[0])
        if not self.kart:
            return None
        kartlar = FinansService.kredi_kartlari(banka_karti_id=self.kart.id)
        if len(kartlar) == 1:
            return int(kartlar[0].id)
        return None

    def _kk_tarihleri_degistir(self):
        if not self._kayit_gerekli("Kart"):
            return
        kk_id = self._kk_secili_id()
        if not kk_id:
            messagebox.showinfo(
                "Kart",
                "Tarihleri değiştirmek için listeden bir kredi kartı seçin.",
                parent=self,
            )
            return
        dialog = KartTarihleriDegistirDialog(self, kk_id)
        self.wait_window(dialog)
        if dialog.result:
            self._kk_listesini_yenile()

    def _tum_firma_kartlari(self):
        """Sınıf menüsüne geç — tüm bankaların firma kredi kartları."""
        hedef = _finans_app_kok(self)
        try:
            self.destroy()
        except tk.TclError:
            pass
        if hedef is not None and hasattr(hedef, "_icerigi_temizle"):
            firma_kredi_kartlari_sayfasi_goster(hedef)
        else:
            messagebox.showinfo(
                "Firma Kredi Kartları",
                "Finans → Firma Kredi Kartları menüsünden tüm bankaların kartlarını açabilirsiniz.",
            )

    def _kredi_listesini_yenile(self):
        for item in self.kredi_tablo.get_children():
            self.kredi_tablo.delete(item)
        if not self.kart:
            self.kredi_ozet_lbl.configure(text="Kart kaydedilince krediler listelenir.")
            return
        tur_map = dict(KREDI_TURLERI)
        krediler = FinansService.banka_kredileri(
            banka_karti_id=self.kart.id, durum_filtre="TUMU", aktif_only=False
        )
        kalan_toplam = Decimal("0")
        plan_eksik_n = 0
        for k in krediler:
            det = FinansService.banka_kredi_getir(k.id) or {}
            kalan = Decimal(str(det.get("kalan_anapara") or 0))
            kalan_toplam += kalan
            if det.get("plan_eksik"):
                plan_eksik_n += 1
            self.kredi_tablo.insert(
                "",
                "end",
                iid=str(k.id),
                values=(
                    k.belge_no or "—",
                    k.kredi_adi or "—",
                    tur_map.get(k.kredi_turu, k.kredi_turu or "—"),
                    _tarih(k.kullandirim_tarihi),
                    _para(k.ana_para),
                    _para(k.toplam_faiz),
                    "—" if det.get("plan_eksik") else k.taksit_sayisi,
                    _kredi_taksit_tutari_hucre(det),
                    _para(kalan),
                    k.durum or "—",
                ),
            )
        ekstra = f"  ·  {plan_eksik_n} planı eksik" if plan_eksik_n else ""
        self.kredi_ozet_lbl.configure(
            text=f"{len(krediler)} kredi  ·  Kalan anapara: {_para(kalan_toplam)}{ekstra}"
        )

    def _mutabakati_yenile(self):
        for item in self.mutabakat_tablo.get_children():
            self.mutabakat_tablo.delete(item)
        if not self.kart:
            self.mutabakat_ozet.configure(text="Kart kaydedilince bakiyeler görünür.")
            return
        kart = FinansService.banka_karti_getir(self.kart.id)
        if not kart:
            return
        self.kart = kart
        ham_tur = FinansService.banka_bakiyeler(kart)
        tur_ad = dict(BANKA_ALT_HESAP_TURLERI)
        pos_alacak = FinansService.pos_aktif_alacak_ozeti(banka_karti_id=kart.id)
        pb_varlik: dict[str, Decimal] = {}
        pb_borc: dict[str, Decimal] = {}
        for h in kart.alt_hesaplar or []:
            kod = (h.alt_hesap_turu or "").upper()
            pb = (getattr(h, "para_birimi", None) or "TRY").upper()
            not_metin = ""
            if kod == "POS":
                goster = FinansService.pos_hesap_gosterim_bakiyesi(h)
                not_metin = (
                    f"Bekleyen brüt {_para(pos_alacak['brut'], pb)} · "
                    f"kom. {_para(pos_alacak['komisyon'], pb)} · "
                    f"{pos_alacak['adet']} açık · "
                    f"Hareket bakiyesi {_para_bakiye(ham_tur.get('POS', 0), pb)}"
                )
            else:
                goster = FinansService.isletme_bakiyesi(h)
            self.mutabakat_tablo.insert(
                "",
                "end",
                values=(
                    tur_ad.get(kod, kod or "—"),
                    h.hesap_adi or "—",
                    pb,
                    (getattr(h, "hesap_no", None) or "").strip() or "—",
                    (h.iban or "").strip() or "—",
                    _para_bakiye(goster, pb),
                    not_metin or "—",
                ),
            )
            if goster > 0:
                pb_varlik[pb] = pb_varlik.get(pb, Decimal("0")) + goster
            elif goster < 0:
                pb_borc[pb] = pb_borc.get(pb, Decimal("0")) + (-goster)
        varlik_m = (
            " · ".join(f"{p}: {_para_bakiye(t, p)}" for p, t in sorted(pb_varlik.items()))
            or "—"
        )
        borc_m = (
            " · ".join(
                f"{p}: {_para_bakiye(-t, p)}" for p, t in sorted(pb_borc.items())
            )
            or "—"
        )
        ekstra = (
            f"  ·  POS bekleyen: {pos_alacak['adet']} / "
            f"brüt {_para(pos_alacak['brut'])} · "
            f"kom. {_para(pos_alacak['komisyon'])} · "
            f"net {_para_bakiye(pos_alacak['net'])}"
        )
        self.mutabakat_ozet.configure(
            text=f"Varlıklar: {varlik_m}  ·  Borçlar: {borc_m}{ekstra}"
        )

    def _banka_hesap_detay_ac(self):
        if not self._kayit_gerekli("Detay"):
            return
        from banka_alt_hesap_detay_ui import BankaAltHesapDetayDialog

        BankaAltHesapDetayDialog(self, self.kart.id)

    def _gecmisi_yenile(self):
        for item in self.gecmis_tablo.get_children():
            self.gecmis_tablo.delete(item)
        if not self.kart:
            return
        kart = FinansService.banka_karti_getir(self.kart.id)
        if not kart:
            return
        self.kart = kart
        kayitlar = []
        for h in kart.alt_hesaplar or []:
            for har in FinansService.hareketler(hesap_id=h.id, limit=200):
                kayitlar.append((h, har))
        kayitlar.sort(
            key=lambda x: (
                getattr(x[1], "tarih", None) or date.min,
                getattr(x[1], "id", 0) or 0,
            ),
            reverse=True,
        )
        for i, (h, har) in enumerate(kayitlar[:400]):
            isaret = FinansService.hareket_isareti(har.hareket_turu)
            tutar = Decimal(str(har.tutar or 0))
            self.gecmis_tablo.insert(
                "",
                "end",
                values=(
                    _tarih(har.tarih),
                    h.hesap_adi or "—",
                    har.hareket_turu or "—",
                    har.belge_no or "—",
                    _para(tutar) if isaret > 0 else "",
                    _para(tutar) if isaret < 0 else "",
                    har.aciklama or "",
                ),
                tags=_hareket_satir_tags(i, isaret=isaret),
            )

    def _muhasebe_hesaplari(self):
        if not self.kart:
            messagebox.showinfo("Kayıt", "Muhasebe hesapları için önce banka kartını kaydedin.", parent=self)
            return
        from finans_muhasebe_hesap_ui import KartMuhasebeHesaplariDialog

        KartMuhasebeHesaplariDialog(
            self,
            banka_karti_id=int(self.kart.id),
            baslik=f"Muhasebe Hesapları — {self.kart.banka_adi}",
        )

    def _banka_adi_listesini_yenile(self):
        degerler = FinansService.banka_adi_listesi()
        mevcut = self.alanlar["banka_adi"].get().strip()
        self.alanlar["banka_adi"]["values"] = degerler
        if mevcut:
            self.alanlar["banka_adi"].set(mevcut)

    def yeni_banka_karti(self):
        """Banka adı yanındaki Yeni — yeni banka ana kartı açar."""
        ad = simpledialog.askstring(
            "Yeni Banka Kartı",
            "Yeni kart için banka adını yazın:",
            parent=self,
            initialvalue=self.alanlar["banka_adi"].get().strip(),
        )
        if ad is None:
            return
        ad = (ad or "").strip()
        if not ad:
            messagebox.showwarning("Banka adı", "Banka adı boş olamaz.", parent=self)
            return

        app = self.master
        dialog = BankaAnaKartDialog(app, kart=None)
        dialog.alanlar["banka_adi"].set(ad)
        dialog._banka_adi_listesini_yenile()
        self.wait_window(dialog)
        self._banka_adi_listesini_yenile()
        if dialog.result:
            self.alanlar["banka_adi"].set(dialog.result.banka_adi)

    def bakiyeleri_yenile(self):
        if not self.kart:
            for lbl in self.bakiye_etiketleri.values():
                lbl.configure(text=_para_bakiye(0), fg=_bakiye_renk(0))
            if self.kmh_limit_lbl:
                self.kmh_limit_lbl.configure(text="KMH limiti: —")
            if getattr(self, "ozet_varlik_lbl", None):
                self.ozet_varlik_lbl.configure(
                    text="Varlıklar: —", fg=_bakiye_renk(0)
                )
                self.ozet_borc_lbl.configure(text="Borçlar: —", fg=_bakiye_renk(0))
                self.ozet_net_lbl.configure(
                    text="Net (Varlık − Borç): —", fg=_bakiye_renk(0)
                )
            return
        kart = FinansService.banka_karti_getir(self.kart.id)
        if not kart:
            return
        self.kart = kart
        ozet = FinansService.banka_varlik_borc_ozeti(kart)
        bakiyeler = ozet["bakiyeler"]
        for kod, lbl in self.bakiye_etiketleri.items():
            tutar = bakiyeler.get(kod, 0)
            lbl.configure(text=_para_bakiye(tutar), fg=_bakiye_renk(tutar))
        if self.kmh_limit_lbl:
            limit = FinansService.kmh_limiti(kart)
            kmh_bak = bakiyeler.get("KMH", Decimal("0"))
            kullanilabilir = Decimal(str(kmh_bak)) + limit
            self.kmh_limit_lbl.configure(
                text=(
                    f"KMH limiti: {_para(limit)} · "
                    f"Kullanılabilir: {_para_bakiye(kullanilabilir)}"
                ),
                foreground="#555",
            )
        if getattr(self, "ozet_varlik_lbl", None):
            varlik = ozet["varlik"]
            borc_g = ozet["borc_gosterim"]
            net = ozet["net"]
            self.ozet_varlik_lbl.configure(
                text=f"Varlıklar: {_para_bakiye(varlik)}",
                fg=_bakiye_renk(varlik if varlik else 0),
            )
            self.ozet_borc_lbl.configure(
                text=f"Borçlar: {_para_bakiye(borc_g)}",
                fg=_bakiye_renk(borc_g if borc_g else 0),
            )
            self.ozet_net_lbl.configure(
                text=f"Net (Varlık − Borç): {_para_bakiye(net)}",
                fg=_bakiye_renk(net),
            )

    def _islem_ac(self, alt_tur, alt_etiket):
        if not self.kart:
            messagebox.showinfo(
                "Kayıt",
                "İşlem menüsü için önce banka kartını kaydedin.",
                parent=self,
            )
            return
        if alt_tur == "MEVDUAT":
            dialog = MevduatIslemleriDialog(self, self.kart)
        elif alt_tur == "KMH":
            dialog = KmhIslemleriDialog(self, self.kart)
        elif alt_tur == "POS":
            poslar = FinansService.pos_alt_hesaplari(self.kart, aktif_only=True)
            if len(poslar) <= 1:
                dialog = PosIslemleriDialog(
                    self,
                    self.kart,
                    pos_hesap_id=(poslar[0].id if poslar else None),
                )
            else:
                dialog = PosHesaplariDialog(self, self.kart)
        elif alt_tur in ("YATIRIM", "VADELI"):
            dialog = YatirimHesaplariDialog(self, self.kart)
        elif alt_tur == "KREDI_KARTI":
            dialog = KrediKartiIslemleriDialog(self, self.kart)
        elif alt_tur == "KREDILER":
            dialog = KredilerIslemleriDialog(self, self.kart)
        else:
            dialog = AltHesapIslemDialog(self, self.kart, alt_tur, alt_etiket)
        self.wait_window(dialog)
        self.bakiyeleri_yenile()
        self._sekmeleri_yenile()

    def kaydet(self):
        veri = {k: w.get().strip() for k, w in self.alanlar.items()}
        if self.kart:
            veri["kart_id"] = self.kart.id
        # Aktarım hesabı etiketi → id
        etiket = veri.pop("pos_aktarim_hesap", "") or ""
        hid = getattr(self, "_pos_aktarim_hesap_map", {}).get(etiket)
        if hid:
            veri["pos_aktarim_hesap_id"] = int(hid)
            veri["pos_hedef_hesap_turu"] = "KMH" if "(KMH)" in etiket else "MEVDUAT"
        veri["pos_taksit_komisyonlari"] = {
            n: (w.get() or "0").strip() for n, w in self.pos_taksit_oranlari.items()
        }
        try:
            self.result = FinansService.banka_karti_kaydet(veri)
        except ValueError as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)
            return
        self.kart = self.result
        self.title(f"Banka Ana Kartı — {self.kart.banka_adi}")
        self._banka_adi_listesini_yenile()
        self.bakiyeleri_yenile()
        self._sekmeleri_yenile()
        self._pos_aktarim_hedeflerini_doldur(self.kart)
        messagebox.showinfo(
            "Kaydedildi",
            "Banka kartı ve 5 alt hesap (mevduat, KMH, POS, kredi kartı, krediler) hazır.",
            parent=self,
        )


def _hesap_sayfasi(app, hesap_turu: str, baslik: str):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Finans Menüsü", command=lambda: finans_menusu_goster(app)).pack(side="right")

    ttk.Label(
        app.icerik,
        text=(
            "Günlük özet: Dünden Devir / Bugünkü Tahsilat / Bugünkü Ödeme / Bakiye. "
            "Harekette çift tık veya F2 = belge aç (salt görüntüleme mali yazmaz)."
            if hesap_turu == "KASA"
            else "Hesapları yönetin; fatura tahsilat/ödemeleri otomatik buraya işlenir. Çift tık = hareketler."
        ),
    ).pack(anchor="w", pady=(10, 4))

    ozet_cerceve = ttk.Frame(app.icerik)
    ozet_cerceve.pack(anchor="w", pady=(0, 6))
    ozet_say = ttk.Label(ozet_cerceve, text="")
    ozet_say.pack(side="left")
    kasa_ozet = hesap_turu == "KASA"
    if kasa_ozet:
        ozet_bakiye = tk.Label(
            ozet_cerceve,
            text="",
            font=_HESAP_BAKIYE_FONT,
            fg=_HAREKET_GIRIS,
            anchor="w",
        )
        ozet_bakiye.pack(side="left", padx=(10, 0))
    else:
        ozet_bakiye = ttk.Label(ozet_cerceve, text="")
        ozet_bakiye.pack(side="left", padx=(4, 0))

    kasa_gun_var = None
    if kasa_ozet:
        gun_cerceve = ttk.Frame(app.icerik)
        gun_cerceve.pack(anchor="w", pady=(0, 4))
        ttk.Label(gun_cerceve, text="Gün:").pack(side="left")
        gun_c = ttk.Frame(gun_cerceve)
        gun_c.pack(side="left", padx=(6, 0))
        kasa_gun_var = ttk.Entry(gun_c, width=12)
        kasa_gun_var.pack(side="left")
        kasa_gun_var.insert(0, FinansService.bugun_tr().strftime("%d.%m.%Y"))
        takvim_butonu(gun_c, kasa_gun_var)
        ttk.Button(
            gun_cerceve,
            text="Bugün",
            command=lambda: (
                kasa_gun_var.delete(0, "end"),
                kasa_gun_var.insert(0, FinansService.bugun_tr().strftime("%d.%m.%Y")),
                listeyi_yenile(),
            ),
        ).pack(side="left", padx=8)
        ttk.Button(gun_cerceve, text="Göster", command=lambda: listeyi_yenile()).pack(
            side="left"
        )

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True, pady=6)

    if hesap_turu == "KASA":
        kolonlar = ("ad", "pb", "devir", "tahsilat", "odeme", "bakiye", "durum")
        hesap_kolon_tanim = (
            ("ad", "Kasa Adı", 160),
            ("pb", "PB", 50),
            ("devir", "Dünden Devir", 110),
            ("tahsilat", "Bugünkü Tahsilat", 120),
            ("odeme", "Bugünkü Ödeme", 120),
            ("bakiye", "Bakiye", 110),
            ("durum", "Durum", 70),
        )
    else:
        kolonlar = ("ad", "acilis", "bakiye", "aciklama", "durum")
        hesap_kolon_tanim = (
            ("ad", "Kasa Adı", 200),
            ("acilis", "Açılış", 110),
            ("bakiye", "Bakiye", 120),
            ("aciklama", "Açıklama", 280),
            ("durum", "Durum", 70),
        )

    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse", height=10)
    _hesap_kolonlari_ayarla(tablo, hesap_kolon_tanim)
    if kasa_ozet:
        tablo.tag_configure("bakiye_pozitif", foreground=_HAREKET_GIRIS, font=_HESAP_BAKIYE_FONT)
        tablo.tag_configure("bakiye_negatif", foreground=_HAREKET_CIKIS, font=_HESAP_BAKIYE_FONT)
        tablo.tag_configure("bakiye_sifir", foreground=_HAREKET_NOTR, font=_HESAP_BAKIYE_FONT)
    kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydirma.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydirma.pack(side="right", fill="y")

    hareket_cerceve = ttk.LabelFrame(app.icerik, text="Hesap hareketleri", padding=6)
    hareket_cerceve.pack(fill="both", expand=True, pady=(4, 0))
    if hesap_turu == "KASA":
        hareket_kolonlar = ("tarih", "tur", "belge", "giris", "cikis", "kur", "tl", "aciklama")
        hareket_kolon_tanim = (
            ("tarih", "Tarih", 85),
            ("tur", "Hareket", 120),
            ("belge", "Belge No", 100),
            ("giris", "Giriş", 95),
            ("cikis", "Çıkış", 95),
            ("kur", "Kur", 80),
            ("tl", "TL Kayıt", 95),
            ("aciklama", "Açıklama", 180),
        )
    else:
        hareket_kolonlar = ("tarih", "tur", "belge", "giris", "cikis", "aciklama")
        hareket_kolon_tanim = (
            ("tarih", "Tarih", 90),
            ("tur", "Hareket", 140),
            ("belge", "Belge No", 120),
            ("giris", "Giriş", 110),
            ("cikis", "Çıkış", 110),
            ("aciklama", "Açıklama", 260),
        )
    hareket_tablo = ttk.Treeview(
        hareket_cerceve,
        columns=hareket_kolonlar,
        show="headings",
        height=8,
    )
    _hareket_kolonlari_ayarla(hareket_tablo, hareket_kolon_tanim)
    h_kaydir = ttk.Scrollbar(hareket_cerceve, orient="vertical", command=hareket_tablo.yview)
    hareket_tablo.configure(yscrollcommand=h_kaydir.set)
    hareket_tablo.pack(side="left", fill="both", expand=True)
    h_kaydir.pack(side="right", fill="y")
    _hareket_tablo_stil(hareket_tablo)

    hareket_butonlar = ttk.Frame(app.icerik)
    if hesap_turu == "KASA":
        hareket_butonlar.pack(fill="x", pady=(2, 0))
    belge_sure_lbl = ttk.Label(hareket_butonlar, text="", foreground="#555") if kasa_ozet else None

    def _bakiye_satir_tag(bak):
        if bak > 0:
            return ("bakiye_pozitif",)
        if bak < 0:
            return ("bakiye_negatif",)
        return ("bakiye_sifir",)

    def _secili_gun():
        if not kasa_gun_var:
            return FinansService.bugun_tr()
        raw = (kasa_gun_var.get() or "").strip()
        if not raw:
            return FinansService.bugun_tr()
        try:
            return datetime.strptime(raw, "%d.%m.%Y").date()
        except ValueError as hata:
            raise ValueError("Gün tarihi GG.AA.YYYY formatında olmalıdır.") from hata

    def listeyi_yenile():
        for item in tablo.get_children():
            tablo.delete(item)
        if kasa_ozet:
            try:
                gun = _secili_gun()
            except ValueError as hata:
                messagebox.showerror("Gün", str(hata), parent=app)
                return
            ozet = FinansService.kasa_gunluk_ozet(gun)
            bugun = FinansService.bugun_tr()
            if gun == bugun:
                tablo.heading("tahsilat", text="Bugünkü Tahsilat")
                tablo.heading("odeme", text="Bugünkü Ödeme")
            else:
                tablo.heading("tahsilat", text="Seçili Gün Tahsilat")
                tablo.heading("odeme", text="Seçili Gün Ödeme")
            pb_toplam: dict[str, Decimal] = {}
            for s in ozet["satirlar"]:
                pb = s["pb"]
                pb_toplam[pb] = pb_toplam.get(pb, Decimal("0")) + s["bakiye"]
                tablo.insert(
                    "",
                    "end",
                    iid=str(s["hesap_id"]),
                    values=(
                        s["ad"],
                        pb,
                        _para(s["devir"], pb),
                        _para(s["tahsilat"], pb),
                        _para(s["odeme"], pb),
                        _para_bakiye(s["bakiye"], pb),
                        s["durum"],
                    ),
                    tags=_bakiye_satir_tag(s["bakiye"]),
                )
            ozet_say.configure(
                text=(
                    f"Aktif kasa: {len(ozet['satirlar'])} · "
                    f"{gun.strftime('%d.%m.%Y')} · "
                    f"Dış tahsilat {_para(ozet['dis_giris'])} · "
                    f"Dış ödeme {_para(ozet['dis_cikis'])}"
                )
            )
            if len(pb_toplam) > 1 or (len(pb_toplam) == 1 and next(iter(pb_toplam)) != "TRY"):
                parcalar = " · ".join(
                    f"{pb}: {_para_bakiye(t, pb)}" for pb, t in sorted(pb_toplam.items())
                )
                ozet_bakiye.configure(
                    text=f"PB ara toplam — {parcalar} (farklı PB toplanmaz)",
                    fg="#555555",
                )
            else:
                ozet_bakiye.configure(
                    text=f"Toplam bakiye: {_para_bakiye(ozet['toplam_bakiye'])}",
                    fg=_bakiye_renk(ozet["toplam_bakiye"]),
                )
            return

        hesaplar = FinansService.hesaplar(hesap_turu=hesap_turu, aktif_only=False)
        toplam = Decimal("0")
        aktif_say = len([h for h in hesaplar if h.aktif])
        for h in hesaplar:
            if not h.aktif:
                continue
            bak = FinansService.bakiye(h)
            toplam += bak
            tablo.insert(
                "",
                "end",
                iid=str(h.id),
                values=(
                    h.hesap_adi,
                    _para(h.acilis_bakiyesi),
                    _para(bak),
                    (h.aciklama or "")[:60],
                    "Aktif" if h.aktif else "Pasif",
                ),
            )
        ozet_say.configure(text=f"Aktif hesap: {aktif_say}")
        ozet_bakiye.configure(text=f"· Toplam bakiye: {_para(toplam)}")

    def hareketleri_goster(hesap_id=None):
        for item in hareket_tablo.get_children():
            hareket_tablo.delete(item)
        if not hesap_id:
            hareket_cerceve.configure(text="Hesap hareketleri")
            return
        hesap = FinansService.hesap_getir(hesap_id)
        if not hesap:
            return
        pb = FinansService.hesap_pb(hesap)
        bak = FinansService.bakiye(hesap)
        tl_kayit = FinansService.tl_kayit_bakiyesi(hesap)
        baslik_h = f"Hareketler — {hesap.hesap_adi} (bakiye: {_para(bak, pb)}"
        if pb != "TRY":
            baslik_h += f", TL kayıt: {_para(tl_kayit, 'TRY')}"
        hareket_cerceve.configure(text=baslik_h + ")")
        for sira, har in enumerate(FinansService.hareketler(hesap_id=hesap_id, limit=300)):
            isaret = FinansService.hareket_isareti(har.hareket_turu)
            har_pb = (getattr(har, "para_birimi", None) or pb).upper()
            if hesap_turu == "KASA":
                tl = getattr(har, "tl_karsiligi", None)
                values = (
                    _tarih(har.tarih),
                    har.hareket_turu,
                    har.belge_no,
                    _para(har.tutar, har_pb) if isaret > 0 else "",
                    _para(har.tutar, har_pb) if isaret < 0 else "",
                    _kur_metin(getattr(har, "kur", None)),
                    _para(tl, "TRY") if tl is not None else "",
                    har.aciklama or "",
                )
            else:
                values = (
                    _tarih(har.tarih),
                    har.hareket_turu,
                    har.belge_no,
                    _para(har.tutar, har_pb) if isaret > 0 else "",
                    _para(har.tutar, har_pb) if isaret < 0 else "",
                    har.aciklama or "",
                )
            hareket_tablo.insert(
                "",
                "end",
                iid=str(har.id),
                values=values,
                tags=_hareket_satir_tags(sira, isaret=isaret),
            )

    def secili_id():
        secim = tablo.selection()
        return int(secim[0]) if secim else None

    def secim_degisti(_e=None):
        hid = secili_id()
        if hid:
            hareketleri_goster(hid)

    def yeni():
        dialog = HesapDialog(app, hesap_turu=hesap_turu)
        app.wait_window(dialog)
        if dialog.result:
            listeyi_yenile()
            tablo.selection_set(str(dialog.result.id))
            hareketleri_goster(dialog.result.id)

    def duzenle():
        hid = secili_id()
        if not hid:
            messagebox.showinfo("Seçim", "Bir hesap seçin.", parent=app)
            return
        hesap = FinansService.hesap_getir(hid)
        dialog = HesapDialog(app, hesap_turu=hesap_turu, hesap=hesap)
        app.wait_window(dialog)
        if dialog.result:
            listeyi_yenile()
            tablo.selection_set(str(dialog.result.id))
            hareketleri_goster(dialog.result.id)

    def pasif():
        hid = secili_id()
        if not hid:
            messagebox.showinfo("Seçim", "Bir hesap seçin.", parent=app)
            return
        hesap = FinansService.hesap_getir(hid)
        if not messagebox.askyesno(
            "Pasif",
            f"'{hesap.hesap_adi}' hesabı pasif yapılsın mı?\nHareketler silinmez.",
            parent=app,
        ):
            return
        try:
            FinansService.hesap_pasif_yap(hid)
        except ValueError as hata:
            messagebox.showerror("Pasif", str(hata), parent=app)
            return
        hareketleri_goster(None)
        listeyi_yenile()

    def gider_fisi():
        from gider_fisi_ui import GiderFisiDialog

        hid = secili_id()
        dialog = GiderFisiDialog(app, finans_hesap_id=hid)
        app.wait_window(dialog)
        if dialog.result and hid:
            hareketleri_goster(hid)
            listeyi_yenile()

    def _makbuz_kaydedildi(hid):
        def yenile(_makbuz):
            try:
                if hid:
                    hareketleri_goster(hid)
                listeyi_yenile()
            except tk.TclError:
                pass

        return yenile

    def tahsilat_makbuzu():
        from kasa_makbuz_ui import KasaMakbuzDialog

        hid = secili_id()
        KasaMakbuzDialog(app, makbuz_turu="TAHSILAT", finans_hesap_id=hid, on_kayit=_makbuz_kaydedildi(hid))

    def odeme_makbuzu():
        from kasa_makbuz_ui import KasaMakbuzDialog

        hid = secili_id()
        KasaMakbuzDialog(app, makbuz_turu="ODEME", finans_hesap_id=hid, on_kayit=_makbuz_kaydedildi(hid))

    def kasadan_bankaya():
        hid = secili_id()
        dialog = KasadanBankayaYatirDialog(app)
        if hid and getattr(dialog, "_kasa_map", None):
            _combobox_id_sec(dialog.kasa, dialog._kasa_map, hid)
            dialog._kasa_bilgi()
        app.wait_window(dialog)
        if dialog.result and hid:
            hareketleri_goster(hid)
            listeyi_yenile()
        elif dialog.result:
            listeyi_yenile()

    def bankadan_kasaya():
        hid = secili_id()
        dialog = BankadanCekilenDialog(app)
        if hid and getattr(dialog, "_kasa_map", None):
            _combobox_id_sec(dialog.kasa, dialog._kasa_map, hid)
        app.wait_window(dialog)
        if dialog.result and hid:
            hareketleri_goster(hid)
            listeyi_yenile()
        elif dialog.result:
            listeyi_yenile()

    def kasalar_arasi_virman():
        hid = secili_id()
        dialog = KasalarArasiVirmanDialog(app, kaynak_kasa_id=hid)
        app.wait_window(dialog)
        if dialog.result:
            listeyi_yenile()
            if hid:
                try:
                    tablo.selection_set(str(hid))
                    hareketleri_goster(hid)
                except tk.TclError:
                    pass

    def _secili_hareket():
        secim = hareket_tablo.selection()
        if not secim:
            return None, None, None
        iid = secim[0]
        degerler = hareket_tablo.item(iid, "values")
        if not degerler or len(degerler) < 3:
            return None, None, None
        har_id = None
        try:
            har_id = int(iid)
        except (TypeError, ValueError):
            har_id = None
        return har_id, (degerler[1] or "").strip(), (degerler[2] or "").strip()

    def hareket_belge_ac(_event=None):
        if getattr(app, "_belge_aciliyor", False):
            return "break"
        har_id, tur, belge_no = _secili_hareket()
        if har_id and (not belge_no or not tur):
            ozet = FinansService.hareket_ozet_getir(har_id)
            if ozet:
                tur = ozet["hareket_turu"] or tur
                belge_no = ozet["belge_no"] or belge_no
        if not belge_no:
            messagebox.showinfo(
                "Belge",
                "Lütfen açılacak hareket satırını seçin (belge numarası olan).",
                parent=app,
            )
            return "break"
        from belge_onizleme_ui import hareket_belgeyi_ac

        aciklar = getattr(app, "_acik_belge_pencereleri", None)
        if aciklar is None:
            aciklar = {}
            app._acik_belge_pencereleri = aciklar
        mevcut = aciklar.get(belge_no)
        if mevcut is not None:
            try:
                if mevcut.winfo_exists():
                    mevcut.lift()
                    mevcut.focus_force()
                    if belge_sure_lbl is not None:
                        belge_sure_lbl.configure(text=f"{belge_no}: odaklandı (yeniden açılmadı)")
                    return "break"
            except tk.TclError:
                aciklar.pop(belge_no, None)

        app._belge_aciliyor = True
        t0 = time.perf_counter()
        try:
            acildi = hareket_belgeyi_ac(app, tur, belge_no)
            ms = (time.perf_counter() - t0) * 1000
            if belge_sure_lbl is not None:
                belge_sure_lbl.configure(text=f"Açılış: {ms:.0f} ms · {belge_no}")
            if not acildi:
                messagebox.showinfo(
                    "Belge",
                    f"{tur or 'Hareket'} / {belge_no} için açılabilir evrak bulunamadı.",
                    parent=app,
                )
            # Salt görüntüleme liste yenilemez (çift mali yazım / yavaşlık yok)
        except ValueError as hata:
            messagebox.showerror("Belge açılamadı", str(hata), parent=app)
        except Exception as hata:
            messagebox.showerror("Belge açılamadı", str(hata), parent=app)
        finally:
            app._belge_aciliyor = False
        return "break"

    def hareket_belge_yazdir():
        _har_id, tur, belge_no = _secili_hareket()
        if not belge_no:
            messagebox.showinfo(
                "Yazdır",
                "Yazdırılacak hareket satırını seçin.",
                parent=app,
            )
            return
        hareket_belge_ac()

    tablo.bind("<<TreeviewSelect>>", secim_degisti)
    tablo.bind("<Double-1>", lambda _e: duzenle())
    if hesap_turu in ("KASA", "BANKA"):
        def _belge_sutununa_tik(_event):
            # Belge No sütununa tek tık → aç; diğer sütunlar yalnızca seçim
            col = hareket_tablo.identify_column(_event.x)
            row = hareket_tablo.identify_row(_event.y)
            if not row:
                return
            # columns: tarih=#1, tur=#2, belge=#3
            if col == "#3":
                hareket_tablo.selection_set(row)
                hareket_tablo.focus(row)
                return hareket_belge_ac()

        hareket_tablo.bind("<ButtonRelease-1>", _belge_sutununa_tik)
        hareket_tablo.bind("<Double-1>", hareket_belge_ac)
        hareket_tablo.bind("<Return>", hareket_belge_ac)
        hareket_tablo.bind("<F2>", hareket_belge_ac)
        ttk.Button(hareket_butonlar, text="Belgeyi Aç", command=hareket_belge_ac).pack(
            side="left"
        )
        ttk.Button(hareket_butonlar, text="Yazdır", command=hareket_belge_yazdir).pack(
            side="left", padx=8
        )
        ttk.Label(
            hareket_butonlar,
            text="Çift tık / F2 = belge aç · görüntüleme mali yazmaz",
            foreground="#555",
        ).pack(side="left", padx=8)
        if belge_sure_lbl is not None:
            belge_sure_lbl.pack(side="right", padx=4)

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=8)
    ttk.Button(alt, text="Yeni Hesap", command=yeni).pack(side="left")
    ttk.Button(alt, text="Düzenle", command=duzenle).pack(side="left", padx=8)
    ttk.Button(alt, text="Pasif Yap", command=pasif).pack(side="left")
    if hesap_turu == "KASA":
        ttk.Button(alt, text="Tahsilat Makbuzu", command=tahsilat_makbuzu).pack(
            side="left", padx=8
        )
        ttk.Button(alt, text="Ödeme Makbuzu", command=odeme_makbuzu).pack(side="left")
        ttk.Button(alt, text="Gider Fişi", command=gider_fisi).pack(side="left", padx=8)
        ttk.Button(alt, text="Kasadan Bankaya Yatır", command=kasadan_bankaya).pack(
            side="left", padx=8
        )
        ttk.Button(alt, text="Bankadan Kasaya", command=bankadan_kasaya).pack(side="left")
        ttk.Button(alt, text="Kasalar Arası Virman", command=kasalar_arasi_virman).pack(
            side="left", padx=8
        )
    ttk.Button(alt, text="Yenile", command=listeyi_yenile).pack(side="right")

    listeyi_yenile()


def kasalar_sayfasi_goster(app):
    _hesap_sayfasi(app, "KASA", "KASALAR")


_ALT_TUR_ETIKET = {
    "MEVDUAT": "Vadesiz mevduat",
    "KMH": "KMH",
    "VADELI": "Vadeli mevduat",
}


def mevduat_kmh_hesaplari_sayfasi_goster(app):
    """Finans > Mevduat ve KMH Hesapları — tüm bankaların sınıf görünümü."""
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="MEVDUAT VE KMH HESAPLARI", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Finans Menüsü", command=lambda: finans_menusu_goster(app)).pack(side="right")
    ttk.Label(
        app.icerik,
        text="Tüm bankaların vadesiz, vadeli mevduat ve KMH hesapları. Çift tık ilgili banka işlem ekranını açar.",
    ).pack(anchor="w", pady=(10, 4))

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(0, 6))
    ttk.Label(filtre, text="Sınıf:").pack(side="left")
    from database.hesap_siralama import etiket_listesini_sirala

    sinif = ttk.Combobox(
        filtre,
        values=tuple(etiket_listesini_sirala(["Tümü", "Vadesiz", "Vadeli", "KMH"])),
        state="readonly",
        width=12,
    )
    sinif.set("Tümü")
    sinif.pack(side="left", padx=6)
    ttk.Label(filtre, text="PB:").pack(side="left", padx=(12, 0))
    pb_filtre = ttk.Combobox(
        filtre,
        values=("Tümü", "TRY", "USD", "EUR"),
        state="readonly",
        width=8,
    )
    pb_filtre.set("Tümü")
    pb_filtre.pack(side="left", padx=6)
    ttk.Label(filtre, text="Ara:").pack(side="left", padx=(12, 0))
    ara = ttk.Entry(filtre, width=28)
    ara.pack(side="left", padx=6)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True, pady=4)
    kolonlar = (
        "banka", "sinif", "ad", "pb", "sube", "iban",
        "bakiye", "limit", "kullanilabilir", "durum",
    )
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    for k, b, w in (
        ("banka", "Banka", 120),
        ("sinif", "Sınıf", 100),
        ("ad", "Hesap", 170),
        ("pb", "PB", 45),
        ("sube", "Şube", 90),
        ("iban", "IBAN", 170),
        ("bakiye", "Bakiye", 100),
        ("limit", "KMH limiti", 95),
        ("kullanilabilir", "Kullanılabilir", 110),
        ("durum", "Durum", 60),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    ozet = ttk.Label(app.icerik, text="")
    ozet.pack(anchor="w", pady=4)

    def _tur_filtresi():
        s = sinif.get()
        if s == "Vadesiz":
            return ("MEVDUAT",)
        if s == "Vadeli":
            return ("VADELI",)
        if s == "KMH":
            return ("KMH",)
        return ("MEVDUAT", "KMH", "VADELI")

    def listeyi_yenile(_e=None):
        from database.hesap_siralama import hesaplari_sirala

        onceki = None
        try:
            sec = tablo.selection()
            if sec:
                onceki = sec[0]
        except tk.TclError:
            onceki = None
        for item in tablo.get_children():
            tablo.delete(item)
        q = (ara.get() or "").strip().casefold()
        pb_sec = (pb_filtre.get() or "Tümü").strip().upper()
        hesaplar = FinansService.alt_hesaplar_listele(alt_turler=_tur_filtresi(), aktif_only=True)
        pb_toplam = {}
        adaylar = []
        for h in hesaplar:
            banka = getattr(h.banka_karti, "banka_adi", None) or h.banka_adi or "—"
            alt = (h.alt_hesap_turu or "").strip().upper()
            sinif_ad = _ALT_TUR_ETIKET.get(alt, "Vadeli mevduat" if alt.startswith("VADELI") else alt)
            pb = (getattr(h, "para_birimi", None) or "TRY").upper()
            if pb_sec != "TÜMÜ" and pb != pb_sec:
                continue
            bak = FinansService.isletme_bakiyesi(h)
            iban = (h.iban or "").strip() or (
                getattr(getattr(h, "banka_karti", None), "iban", None) or ""
            ).strip() or "—"
            sube = (h.sube or "").strip() or (
                getattr(getattr(h, "banka_karti", None), "sube", None) or ""
            ).strip() or "—"
            if alt == "KMH":
                limit = FinansService.kmh_limiti(h)
                kullanilabilir = Decimal(str(bak)) + limit
                limit_metin = _para(limit)
                kul_metin = _para_bakiye(kullanilabilir)
            else:
                # Mevduat/vadeli: KMH limiti uygulanmaz; kullanılabilir = bakiye
                limit_metin = "Uygulanmaz"
                kul_metin = _para_bakiye(bak)
            metin = f"{banka} {h.hesap_adi} {iban} {sube}".casefold()
            if q and q not in metin:
                continue
            adaylar.append(
                {
                    "h": h,
                    "banka": banka,
                    "sinif_adi": sinif_ad,
                    "hesap_adi": h.hesap_adi,
                    "id": int(h.id),
                    "pb": pb,
                    "sube": sube,
                    "iban": iban,
                    "bak": bak,
                    "limit_metin": limit_metin,
                    "kul_metin": kul_metin,
                }
            )
            pb_toplam[pb] = pb_toplam.get(pb, Decimal("0")) + bak
        # Bu ekranın görünen sınıf etiketine göre (Vadesiz/Vadeli/KMH)
        for s in hesaplari_sirala(adaylar):
            h = s["h"]
            tablo.insert(
                "",
                "end",
                iid=str(h.id),
                values=(
                    s["banka"],
                    s["sinif_adi"],
                    h.hesap_adi,
                    s["pb"],
                    s["sube"],
                    s["iban"],
                    _para_bakiye(s["bak"]),
                    s["limit_metin"],
                    s["kul_metin"],
                    "Aktif" if h.aktif else "Pasif",
                ),
            )
        if onceki and onceki in tablo.get_children():
            tablo.selection_set(onceki)
            tablo.focus(onceki)
            tablo.see(onceki)
        parcalar = [f"{pb}: {_para_bakiye(t)}" for pb, t in sorted(pb_toplam.items())]
        ozet.configure(
            text=f"{len(tablo.get_children())} hesap"
            + (f" · " + " · ".join(parcalar) if parcalar else "")
            + " · Farklı PB toplanmaz"
        )

    def ac_islem(_e=None):
        secim = tablo.selection()
        if not secim:
            return
        h = FinansService.hesap_getir(int(secim[0]))
        if not h or not h.banka_karti_id:
            messagebox.showinfo("Hesap", "Bu hesabın banka kartı bulunamadı.", parent=app)
            return
        kart = FinansService.banka_karti_getir(h.banka_karti_id)
        if not kart:
            return
        alt = (h.alt_hesap_turu or "").strip().upper()
        if alt == "KMH":
            dialog = KmhIslemleriDialog(app, kart)
        else:
            dialog = MevduatIslemleriDialog(app, kart)
        app.wait_window(dialog)
        listeyi_yenile()

    def banka_kartina_git(_e=None):
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Bir hesap seçin.", parent=app)
            return
        h = FinansService.hesap_getir(int(secim[0]))
        if not h or not h.banka_karti_id:
            messagebox.showinfo("Hesap", "Bu hesabın banka kartı bulunamadı.", parent=app)
            return
        kart = FinansService.banka_karti_getir(h.banka_karti_id)
        if not kart:
            return
        dialog = BankaAnaKartDialog(app, kart)
        app.wait_window(dialog)
        listeyi_yenile()

    sinif.bind("<<ComboboxSelected>>", listeyi_yenile)
    pb_filtre.bind("<<ComboboxSelected>>", listeyi_yenile)
    ara.bind("<KeyRelease>", lambda _e: listeyi_yenile())
    tablo.bind("<Double-1>", ac_islem)
    ttk.Button(filtre, text="Yenile", command=listeyi_yenile).pack(side="left", padx=8)
    ttk.Button(filtre, text="İşlemler", command=ac_islem).pack(side="left", padx=4)
    ttk.Button(filtre, text="Banka kartına git", command=banka_kartina_git).pack(side="left")
    listeyi_yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: mevduat_kmh_hesaplari_sayfasi_goster(app))


def firma_kredi_kartlari_sayfasi_goster(app):
    """Finans > Firma Kredi Kartları — tüm bankaların kartları (aynı kayıt kaynağı)."""
    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="FİRMA KREDİ KARTLARI", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Finans Menüsü", command=lambda: finans_menusu_goster(app)).pack(side="right")
    ttk.Label(
        app.icerik,
        text="Tüm bankalardaki firma kredi kartları. Çift tık kart çalışma ekranını açar "
             "(özet, taksit, ödeme, ekstre, ayarlar).",
    ).pack(anchor="w", pady=(10, 4))

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(0, 6))
    ttk.Label(filtre, text="Ara:").pack(side="left")
    ara = ttk.Entry(filtre, width=32)
    ara.pack(side="left", padx=6)

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True, pady=4)
    kolonlar = (
        "banka", "ad", "son4", "pb", "limit", "kullanilan", "ekstre", "gelecek",
        "gecikmis", "kalan", "son_kesim", "sonraki_kesim", "son_odeme", "durum",
    )
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse")
    for k, b, w in (
        ("banka", "Banka", 110),
        ("ad", "Kart adı", 120),
        ("son4", "Son 4", 50),
        ("pb", "PB", 40),
        ("limit", "Kart Limiti", 95),
        ("kullanilan", "Kullanılan Limit", 110),
        ("ekstre", "Ekstre kalan", 90),
        ("gelecek", "Gelecek taksit", 95),
        ("gecikmis", "Gecikmiş", 80),
        ("kalan", "Kullanılabilir Limit", 120),
        ("son_kesim", "Son kesim", 90),
        ("sonraki_kesim", "Sonraki kesim", 105),
        ("son_odeme", "Son ödeme", 90),
        ("durum", "Durum", 55),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydir.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydir.pack(side="right", fill="y")
    ozet = ttk.Label(app.icerik, text="")
    ozet.pack(anchor="w", pady=4)

    # iid → banka_karti_id
    _banka_map: dict[str, int] = {}

    def listeyi_yenile(_e=None):
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService

        for item in tablo.get_children():
            tablo.delete(item)
        _banka_map.clear()
        q = (ara.get() or "").strip().casefold()
        kartlar = FinansService.kredi_kartlari(aktif_only=False)
        pb_borc: dict[str, Decimal] = {}
        pb_ekstre: dict[str, Decimal] = {}
        pb_gelecek: dict[str, Decimal] = {}
        pb_gecikmis: dict[str, Decimal] = {}
        aktif_n = 0
        for kk in kartlar:
            banka = getattr(kk.banka_karti, "banka_adi", None) or "—"
            metin = f"{banka} {kk.kart_adi} {kk.son_dort_hane or ''}".casefold()
            if q and q not in metin:
                continue
            oz = KrediKartiEkstreService.kart_borc_ozeti(int(kk.id))
            pb = (oz.get("para_birimi") or getattr(kk, "para_birimi", None) or "TRY").upper()
            borc = Decimal(str(oz.get("toplam_borc") or 0))
            ekstre = Decimal(str(oz.get("kesilmis_kalan") or 0))
            gelecek = Decimal(str(oz.get("kesilmemis") or 0))
            gecikmis = Decimal(str(oz.get("gecikmis") or 0))
            limit = Decimal(str(kk.kart_limiti or 0))
            tarihler = KrediKartiEkstreService.kart_tarih_ozeti(kk)
            if kk.aktif:
                aktif_n += 1
                pb_borc[pb] = pb_borc.get(pb, Decimal("0")) + borc
                pb_ekstre[pb] = pb_ekstre.get(pb, Decimal("0")) + ekstre
                pb_gelecek[pb] = pb_gelecek.get(pb, Decimal("0")) + gelecek
                pb_gecikmis[pb] = pb_gecikmis.get(pb, Decimal("0")) + gecikmis
            iid = str(kk.id)
            _banka_map[iid] = int(kk.banka_karti_id)
            tablo.insert(
                "",
                "end",
                iid=iid,
                values=(
                    banka,
                    kk.kart_adi,
                    kk.son_dort_hane or "—",
                    pb,
                    _para(limit, pb) if limit else "—",
                    _para(borc, pb),
                    _para(ekstre, pb),
                    _para(gelecek, pb),
                    _para(gecikmis, pb),
                    _para(oz["kullanilabilir"], pb) if oz.get("limit_tanimli") else "—",
                    tarihler["son_kesim_metin"],
                    tarihler["sonraki_kesim_metin"],
                    tarihler["son_odeme_metin"],
                    "Aktif" if kk.aktif else "Pasif",
                ),
            )

        def _pb_satir(sozluk):
            return " · ".join(f"{p}: {_para(t, p)}" for p, t in sorted(sozluk.items()) if t)

        ozet_parca = []
        if pb_borc:
            ozet_parca.append(f"borç {_pb_satir(pb_borc)}")
        if any(pb_ekstre.values()):
            ozet_parca.append(f"ekstre {_pb_satir(pb_ekstre)}")
        if any(pb_gelecek.values()):
            ozet_parca.append(f"gelecek {_pb_satir(pb_gelecek)}")
        if any(pb_gecikmis.values()):
            ozet_parca.append(f"gecikmiş {_pb_satir(pb_gecikmis)}")
        metin = f"{aktif_n} aktif kart"
        if ozet_parca:
            metin += " · " + " | ".join(ozet_parca)
            if len(pb_borc) > 1:
                metin += " (farklı PB toplanmaz)"
        ozet.configure(text=metin)

    def ac_calisma(_e=None):
        """Çift tık / Kart çalışma — eski Kredi Kartı İşlemleri (bağımsız panel değil)."""
        secim = tablo.selection()
        if not secim:
            return
        banka_id = _banka_map.get(secim[0])
        if not banka_id:
            return
        kart = FinansService.banka_karti_getir(banka_id)
        if not kart:
            return
        dialog = KrediKartiIslemleriDialog(
            app, kart, kredi_karti_id=int(secim[0])
        )
        app.wait_window(dialog)
        listeyi_yenile()

    def ac_islem(_e=None):
        secim = tablo.selection()
        if not secim:
            return
        banka_id = _banka_map.get(secim[0])
        if not banka_id:
            return
        kart = FinansService.banka_karti_getir(banka_id)
        if not kart:
            return
        dialog = KrediKartiIslemleriDialog(
            app, kart, kredi_karti_id=int(secim[0])
        )
        app.wait_window(dialog)
        listeyi_yenile()

    def tarihleri_degistir(_e=None):
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Kart", "Tarihleri değiştirmek için bir kart seçin.", parent=app)
            return
        dialog = KartTarihleriDegistirDialog(app, int(secim[0]))
        app.wait_window(dialog)
        if dialog.result:
            listeyi_yenile()

    def faiz_tanim_ac(_e=None):
        from faiz_urun_tanim_ui import faiz_urun_tanim_goster

        secim = tablo.selection()
        kid = int(secim[0]) if secim else 1
        faiz_urun_tanim_goster(app, urun_turu="KK", urun_id=kid)

    ara.bind("<KeyRelease>", lambda _e: listeyi_yenile())
    tablo.bind("<Double-1>", ac_calisma)
    def sil_kk(_e=None):
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Kart", "Silmek için bir kart seçin.", parent=app)
            return
        _kullanilmayan_karti_sil(app, "KREDI_KARTI", int(secim[0]), listeyi_yenile)

    def nakit_avans_ac(_e=None):
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo(
                "Taksitli Nakit Avans",
                "İşlem yapılacak kredi kartını listeden seçin.",
                parent=app,
            )
            return
        from nakit_avans_ui import NakitAvansDialog

        kid = int(secim[0])
        kart = FinansService.kredi_karti_getir(kid)
        dlg = NakitAvansDialog(
            app,
            kid,
            kart_adi=(kart.kart_adi if kart else ""),
        )
        app.wait_window(dlg)
        listeyi_yenile()

    ttk.Button(filtre, text="Yenile", command=listeyi_yenile).pack(side="left", padx=8)
    ttk.Button(filtre, text="Kredi Kartı İşlemleri", command=ac_calisma).pack(side="left", padx=4)
    ttk.Button(filtre, text="Kart işlemleri (banka)", command=ac_islem).pack(side="left", padx=4)
    ttk.Button(filtre, text="Taksitli Nakit Avans", command=nakit_avans_ac).pack(side="left", padx=4)
    ttk.Button(filtre, text="Tarihleri değiştir", command=tarihleri_degistir).pack(side="left")
    ttk.Button(filtre, text="Sil", command=sil_kk).pack(side="left", padx=4)
    ttk.Button(filtre, text="Faiz / masraf tanım", command=faiz_tanim_ac).pack(side="left", padx=4)
    listeyi_yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: firma_kredi_kartlari_sayfasi_goster(app))


def bankalar_sayfasi_goster(app):
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="BANKALAR", style="Baslik.TLabel").pack(side="left")
    ttk.Button(
        ust,
        text="EvoBulut Banka Kartları…",
        command=lambda: __import__("evobulut_banka_ui", fromlist=["EvobulutBankaKartAktarDialog"]).EvobulutBankaKartAktarDialog(app),
    ).pack(side="right", padx=(0, 8))
    ttk.Button(ust, text="← Finans Menüsü", command=lambda: finans_menusu_goster(app)).pack(side="right")

    ttk.Label(
        app.icerik,
        text="Banka ana kartları. Çift tık veya Düzenle ile kartı açın — sağda bakiyeler, altta işlem menüleri.",
    ).pack(anchor="w", pady=(10, 4))

    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True, pady=6)
    # #0 = logo + banka adı (okunaklılık: 11 pt / 26 px satır)
    kolonlar = ("sube", "hesap_no", "iban", "mevduat", "kmh", "pos", "kk", "kredi")
    stil = ttk.Style(app.icerik)
    stil.configure("Bankalar.Treeview", rowheight=26, font=("Segoe UI", 11, "bold"))
    stil.configure("Bankalar.Treeview.Heading", font=("Segoe UI", 11, "bold"))
    try:
        stil.configure("Bankalar.Treeview", padding=(2, 0))
    except tk.TclError:
        pass
    tablo = ttk.Treeview(
        cerceve,
        columns=kolonlar,
        show="tree headings",
        selectmode="browse",
        style="Bankalar.Treeview",
    )
    tablo.heading("#0", text="Banka Adı")
    # Logo (~48px) + 6–8 px boşluk + uzun banka adı
    tablo.column("#0", width=260, minwidth=180, anchor="w", stretch=False)
    for k, b, w in (
        ("sube", "Şube", 110),
        ("hesap_no", "Hesap No", 110),
        ("iban", "IBAN", 200),
        ("mevduat", "Mevduat", 95),
        ("kmh", "KMH", 90),
        ("pos", "POS bekleyen net", 110),
        ("kk", "Kredi Kartı", 95),
        ("kredi", "Krediler", 95),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydirma.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydirma.pack(side="right", fill="y")
    # PhotoImage referansları (GC önleme)
    tablo._banka_logolari = []  # type: ignore[attr-defined]

    ozet = ttk.Label(app.icerik, text="")
    ozet.pack(anchor="w", pady=4)
    ttk.Label(
        app.icerik,
        text="POS kolonu: bekleyen brüt−komisyon net alacak (PosValor). Hareket/ledger bakiyesi değildir.",
        foreground="#555",
    ).pack(anchor="w")

    def listeyi_yenile():
        from bank_logo import get_bank_logo

        for item in tablo.get_children():
            tablo.delete(item)
        tablo._banka_logolari.clear()  # type: ignore[attr-defined]
        try:
            paket = FinansService.bankalar_liste_satirlari(aktif_only=False)
        except Exception as hata:  # noqa: BLE001 — şema/sorgu hatasını boş liste diye gizleme
            ozet.configure(text=f"Banka listesi yüklenemedi: {hata}")
            messagebox.showerror(
                "Bankalar",
                f"Banka kartları okunamadı.\n\n{hata}\n\n"
                "Veritabanı şeması eksik olabilir; uygulamayı yeniden başlatın.",
                parent=app,
            )
            return
        for satir in paket["satirlar"]:
            ad = satir["banka_adi"] or ""
            logo = get_bank_logo(ad, max_height=20, max_width=48)
            if logo is not None:
                tablo._banka_logolari.append(logo)  # type: ignore[attr-defined]
            # Treeview #0: image solda, text sağda; baştaki boşluk ≈ 6–8 px
            tablo.insert(
                "",
                "end",
                iid=str(satir["id"]),
                text=("\u2003" + ad) if logo is not None else ad,
                image=logo if logo is not None else "",
                values=(
                    satir["sube"] or "—",
                    satir["hesap_no"] or "—",
                    satir["iban"] or "—",
                    _para_bakiye(satir["MEVDUAT"]),
                    _para_bakiye(satir["KMH"]),
                    # POS kolonu: bekleyen net alacak (hareket bakiyesi değil)
                    _para_bakiye(satir["POS"]),
                    _para_bakiye(satir["KREDI_KARTI"]),
                    _para_bakiye(satir["KREDILER"]),
                ),
            )
        aktif = paket["aktif"]
        pasif = paket["pasif"]
        ozet.configure(
            text=f"{aktif} aktif banka kartı"
            + (f" · {pasif} pasif (listede gizli)" if pasif else "")
        )

    def secili_kart():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Bir banka kartı seçin.", parent=app)
            return None
        return FinansService.banka_karti_getir(int(secim[0]))

    def yeni():
        dialog = BankaAnaKartDialog(app)
        app.wait_window(dialog)
        listeyi_yenile()

    def duzenle():
        kart = secili_kart()
        if not kart:
            return
        dialog = BankaAnaKartDialog(app, kart)
        app.wait_window(dialog)
        listeyi_yenile()

    def pasif():
        kart = secili_kart()
        if not kart:
            return
        if not messagebox.askyesno(
            "Pasif",
            f"'{kart.banka_adi}' banka kartı ve alt hesapları pasif yapılsın mı?",
            parent=app,
        ):
            return
        try:
            FinansService.banka_karti_pasif_yap(kart.id)
        except ValueError as hata:
            messagebox.showerror("Pasif", str(hata), parent=app)
            return
        listeyi_yenile()

    def sil():
        kart = secili_kart()
        if not kart:
            return
        _kullanilmayan_karti_sil(app, "BANKA", int(kart.id), listeyi_yenile)

    def gider_fisi():
        from gider_fisi_ui import GiderFisiDialog

        dialog = GiderFisiDialog(app)
        app.wait_window(dialog)

    tablo.bind("<Double-1>", lambda _e: duzenle())

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=8)
    ttk.Button(alt, text="Yeni Banka Kartı", command=yeni).pack(side="left")
    ttk.Button(alt, text="Kartı Aç / Düzenle", command=duzenle).pack(side="left", padx=8)
    ttk.Button(alt, text="Gider Fişi", command=gider_fisi).pack(side="left", padx=8)
    ttk.Button(alt, text="Pasif Yap", command=pasif).pack(side="left")
    ttk.Button(alt, text="Sil", command=sil).pack(side="left", padx=(8, 0))
    ttk.Button(alt, text="Yenile", command=listeyi_yenile).pack(side="right")

    listeyi_yenile()
