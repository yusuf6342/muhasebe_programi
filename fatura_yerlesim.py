"""Satış faturası ekran yerleşimi.

Üstte sabit fatura bilgileri ve işlem çubuğu, ortada kalan alanı dolduran ürün tablosu,
altta sabit «Notlar / Tahsilatlar» sekmeleri ile hizalı toplamlar. Ana form kaydırılmaz;
uzun ürün, not ve tahsilat listeleri kendi alanlarında kaydırılır.
"""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, ttk

import fatura_tema as ftema

# (satır, sütun grubu, anahtar, başlık, yüzde sütunu)
TOPLAM_HUCRELERI = (
    (0, 0, "ara_toplam", "Ara Toplam", False),
    (1, 0, "iskonto", "Toplam İskonto", False),
    (2, 0, "brut", "Brüt Toplam", False),
    (3, 0, "indirim", "İndirim", True),
    (0, 1, "matrah", "KDV Matrahı", False),
    (1, 1, "kdv", "KDV Toplamı", False),
    (2, 1, "doviz", "Döviz Karşılığı", False),
    (3, 1, "masraf", "Masraf", True),
)

# Pencere iç yüksekliğine göre sekme gövdesi (px): not kutusu en az 4-5 satır gösterir
DETAY_YUKSEKLIK = ((640, 78), (820, 96), (10_000, 120))


def _font(w, boyut: int, kalinlik: str = "normal"):
    return ftema.font(boyut, kalinlik, w.winfo_toplevel())


def _menubutton(parent, metin: str, *, rol: str = "ikincil") -> tuple[tk.Menubutton, tk.Menu]:
    renkler = {
        "ikincil": (ftema.BEYAZ, ftema.LACIVERT, ftema.ACIK_BG),
        "yazdir": (ftema.LACIVERT_ORTA, ftema.BEYAZ, ftema.LACIVERT),
    }
    bg, fg, aktif = renkler.get(rol, renkler["ikincil"])
    mb = tk.Menubutton(
        parent, text=metin, bg=bg, fg=fg, activebackground=aktif, activeforeground=fg,
        relief="flat", font=_font(parent, 10, "bold"), cursor="hand2", padx=10, pady=5,
        highlightthickness=1 if rol == "ikincil" else 0, highlightbackground=ftema.CIZGI,
    )
    menu = tk.Menu(mb, tearoff=0)
    mb.configure(menu=menu)
    return mb, menu


def _kucuk_buton(parent, metin: str, komut, *, rol: str = "ikincil") -> tk.Button:
    renkler = {
        "ikincil": (ftema.BEYAZ, ftema.LACIVERT, ftema.ACIK_BG),
        "onay": (ftema.BASARI, ftema.BEYAZ, ftema.BASARI_HOVER),
        "vurgu": (ftema.SARI, ftema.LACIVERT, ftema.SARI_HOVER),
    }
    bg, fg, aktif = renkler.get(rol, renkler["ikincil"])
    return tk.Button(
        parent, text=metin, command=komut, bg=bg, fg=fg, activebackground=aktif,
        activeforeground=fg, relief="flat", bd=0, padx=8, pady=1, cursor="hand2",
        font=_font(parent, 9, "bold"), highlightthickness=1,
        highlightbackground=ftema.CIZGI if rol == "ikincil" else bg,
    )


# ─── Üst işlem çubuğu ──────────────────────────────────────────────


def yazdir_menusu_kur(dialog, parent) -> tk.Menubutton:
    """Önizleme, Yazdır ve PDF tek «Yazdır / PDF» menüsünde; kısayollar aynı kalır."""
    mb, menu = _menubutton(parent, "Yazdır / PDF ▾", rol="yazdir")
    menu.add_command(label="Önizleme", accelerator="Ctrl+P", command=dialog._fatura_onizleme_ac)
    menu.add_command(label="Yazdır…", command=dialog._fatura_yazdir)
    menu.add_command(label="PDF Kaydet…", accelerator="Ctrl+E", command=dialog._fatura_pdf_kaydet)
    if hasattr(dialog, "_fatura_email_pdf"):
        menu.add_command(label="E-posta İçin PDF…", command=dialog._fatura_email_pdf)
    menu.add_separator()
    menu.add_command(
        label="Yazdırma Ayarları…", accelerator="Ctrl+Shift+P",
        command=dialog._fatura_yazdirma_ayarlari,
    )
    dialog._yazdir_menu = menu
    return mb


def _pack_bilgisi(w) -> dict:
    info = dict(w.pack_info())
    info.pop("in", None)
    return info


def _yatay_pay(info: dict) -> int:
    padx = info.get("padx", 0)
    if isinstance(padx, (tuple, list)):
        return sum(int(p) for p in padx)
    try:
        return int(padx) * 2
    except (TypeError, ValueError):
        return 0


def arac_cubugu_sigdir_kur(dialog) -> None:
    """Dar pencerede isteğe bağlı üst çubuk öğelerini sırayla gizler.

    Kaydet, Onayla ve Yeni, Tahsilat Makbuzu, Yazdır / PDF, Diğer İşlemler ve Kapat her zaman
    görünür; gizlenen Fatura Listesi ve Analiz «Diğer İşlemler» menüsünden açılır.
    """
    refs = getattr(dialog, "_fatura_toolbar", None) or {}
    cubuk, sol, sag = refs.get("cubuk"), refs.get("sol"), refs.get("sag")
    if cubuk is None or sag is None or getattr(dialog, "_arac_sigdir", None):
        return
    try:
        cubuk.update_idletasks()
    except tk.TclError:
        return
    sira = [w for w in sag.pack_slaves()]
    bilgiler = {str(w): _pack_bilgisi(w) for w in sira}
    kullanici = (getattr(dialog, "_aktif_kullanici_cubugu", None) or {}).get("cerceve")
    secenekli = []
    musteri = refs.get("musteri")
    if musteri is not None and musteri.winfo_manager() == "pack":
        secenekli.append(("musteri", musteri))
    if kullanici is not None and kullanici in sira:
        secenekli.append(("kullanici", kullanici))
    for w in sira:
        try:
            if str(w.cget("text")) in ("─", "□", "❐"):
                secenekli.append(("pencere", w))
        except tk.TclError:
            continue
    analiz = getattr(dialog, "_analiz_mb", None)
    if analiz is not None and analiz in sira:
        secenekli.append(("analiz", analiz))
    liste = getattr(dialog, "_fatura_liste_btn", None)
    if liste is not None and liste in sira:
        secenekli.append(("liste", liste))

    genislik = {}
    for _ad, w in secenekli:
        try:
            info = _pack_bilgisi(w)
            genislik[str(w)] = w.winfo_reqwidth() + _yatay_pay(info)
        except tk.TclError:
            genislik[str(w)] = 0

    diger = getattr(dialog, "_diger_mb", None)
    diger_metin = str(diger.cget("text")) if diger is not None else ""
    _diger_menusune_tasinanlari_ekle(dialog, liste_var=any(a == "liste" for a, _ in secenekli),
                                     analiz_var=any(a == "analiz" for a, _ in secenekli))

    durum = {"gizli": None}
    dialog._arac_sigdir = durum
    musteri_pay = 230  # müşteri adı sonradan değişebilir; ad için sabit pay ayrılır
    if musteri is not None and str(musteri) in genislik:
        genislik[str(musteri)] = musteri_pay
    tam_sag = sum(w.winfo_reqwidth() + _yatay_pay(bilgiler[str(w)]) for w in sira)

    def _tam_sol() -> int:
        w = sol.winfo_reqwidth() if sol is not None else 0
        if musteri is not None:
            if musteri.winfo_manager() == "pack":
                w += max(0, musteri_pay - musteri.winfo_reqwidth())
            else:
                w += musteri_pay
        return w

    def _uygula(_e=None):
        try:
            W = cubuk.winfo_width()
        except tk.TclError:
            return
        if W < 100:
            return
        ihtiyac = _tam_sol() + 22 + tam_sag + 24
        gizli: set[str] = set()
        for ad, w in secenekli:
            if ihtiyac <= W:
                break
            gizli.add(str(w))
            ihtiyac -= genislik.get(str(w), 0)
        kisa = ihtiyac > W
        if durum["gizli"] == (gizli, kisa):
            return
        durum["gizli"] = (gizli, kisa)
        if musteri is not None:
            try:
                if str(musteri) in gizli:
                    musteri.pack_forget()
                elif musteri.winfo_manager() != "pack":
                    musteri.pack(side="left")
            except tk.TclError:
                pass
        for w in sira:
            try:
                w.pack_forget()
            except tk.TclError:
                pass
        for w in sira:
            if str(w) in gizli:
                continue
            try:
                w.pack(**bilgiler[str(w)])
            except tk.TclError:
                pass
        if diger is not None:
            try:
                diger.configure(text="Diğer ▾" if kisa else diger_metin)
            except tk.TclError:
                pass

    def _uygula_guvenli(e=None):
        try:
            _uygula(e)
        except Exception:
            pass

    cubuk.bind("<Configure>", _uygula_guvenli, add="+")
    _uygula_guvenli()


def _diger_menusune_tasinanlari_ekle(dialog, *, liste_var: bool, analiz_var: bool) -> None:
    mb = getattr(dialog, "_diger_mb", None)
    if mb is None:
        return
    try:
        menu = mb.nametowidget(mb.cget("menu"))
    except (tk.TclError, KeyError):
        return
    sira = 0
    if liste_var:
        liste = getattr(dialog, "_fatura_liste_btn", None)
        etiket = str(liste.cget("text")) if liste is not None else "Fatura Listesi (F3)"
        menu.insert_command(sira, label=etiket, command=dialog._fatura_listesini_ac)
        sira += 1
    analiz = getattr(dialog, "_analiz_mb", None)
    if analiz_var and analiz is not None:
        try:
            kaynak = analiz.nametowidget(analiz.cget("menu"))
            alt = tk.Menu(menu, tearoff=0)
            for i in range((kaynak.index("end") or -1) + 1):
                tip = kaynak.type(i)
                if tip == "separator":
                    alt.add_separator()
                elif tip == "command":
                    alt.add_command(
                        label=kaynak.entrycget(i, "label"),
                        command=kaynak.entrycget(i, "command"),
                        state=kaynak.entrycget(i, "state"),
                    )
            menu.insert_cascade(sira, label="Analiz", menu=alt)
            sira += 1
        except (tk.TclError, KeyError):
            pass
    if sira:
        menu.insert_separator(sira)


# ─── Ürün şeridi: Satır İşlemleri ─────────────────────────────────


def satir_islemleri_dugmesi(dialog, parent) -> ttk.Menubutton:
    try:
        stil = ttk.Style(dialog)
        stil.configure("FaturaGiris.TMenubutton", padding=(8, ftema.form_ipady() - 1))
    except tk.TclError:
        pass
    mb = ttk.Menubutton(parent, text="Satır İşlemleri", style="FaturaGiris.TMenubutton")
    menu = tk.Menu(mb, tearoff=0)

    def _doldur():
        from fatura_satir_araclar import satir_islemleri_doldur

        menu.delete(0, "end")
        satir_islemleri_doldur(dialog, menu)

    menu.configure(postcommand=_doldur)
    mb.configure(menu=menu)
    dialog._satir_islemleri_menu = menu
    return mb


# ─── Alt detay: Notlar / Tahsilatlar + toplamlar ──────────────────


def _toplamlar_kur(parent) -> tuple[tk.Frame, dict]:
    sag = tk.Frame(parent, bg=ftema.BEYAZ)
    degerler: dict[str, tk.Widget] = {}
    kucuk = _font(parent, 9)
    kalin = _font(parent, 9, "bold")
    for satir, grup, anahtar, baslik, yuzde in TOPLAM_HUCRELERI:
        k = grup * 4
        tk.Label(
            sag, text=baslik, bg=ftema.BEYAZ, fg=ftema.IKINCIL, font=kucuk, anchor="e",
        ).grid(row=satir, column=k, sticky="e", padx=(16 if grup else 0, 6))
        if yuzde:
            oran = tk.Label(
                sag, text="%0,00", bg=ftema.BEYAZ, fg=ftema.METIN, font=kucuk,
                anchor="e", width=7,
            )
            oran.grid(row=satir, column=k + 1, sticky="e", padx=(0, 4))
            degerler[f"{anahtar}_oran"] = oran
        deger = tk.Label(
            sag, text="—" if anahtar == "doviz" else "0,00 TL", bg=ftema.BEYAZ,
            fg=ftema.METIN, font=kalin, anchor="e", width=13,
        )
        deger.grid(row=satir, column=k + 2, sticky="e")
        degerler[anahtar] = deger
    tk.Frame(sag, bg=ftema.CIZGI, height=1).grid(
        row=4, column=0, columnspan=7, sticky="ew", pady=(3, 1)
    )
    tk.Label(
        sag, text="Net Toplam", bg=ftema.BEYAZ, fg=ftema.LACIVERT,
        font=_font(parent, 12, "bold"), anchor="e",
    ).grid(row=5, column=0, columnspan=5, sticky="e", padx=(0, 10))
    net = tk.Label(
        sag, text="0,00 TL", bg=ftema.BEYAZ, fg=ftema.LACIVERT,
        font=_font(parent, 13, "bold"), anchor="e",
    )
    net.grid(row=5, column=5, columnspan=2, sticky="e")
    degerler["genel"] = net
    return sag, degerler


def _ipucu_bagla(widget, metin: str) -> None:
    tip = {"win": None}

    def _goster(_e=None):
        if tip["win"] is not None:
            return
        try:
            x = widget.winfo_rootx()
            y = widget.winfo_rooty() + widget.winfo_height() + 2
        except tk.TclError:
            return
        win = tk.Toplevel(widget)
        win.wm_overrideredirect(True)
        win.wm_geometry(f"+{x}+{y}")
        tk.Label(win, text=metin, bg="#fff8dc", relief="solid", bd=1, padx=6, pady=2).pack()
        tip["win"] = win

    def _gizle(_e=None):
        if tip["win"] is not None:
            try:
                tip["win"].destroy()
            except tk.TclError:
                pass
            tip["win"] = None

    widget.bind("<Enter>", _goster, add="+")
    widget.bind("<Leave>", _gizle, add="+")


def _ata(w, ust):
    while w is not None and w.master is not ust:
        w = w.master
    return w


def detay_kur(dialog) -> dict | None:
    """Alt detay bölümünü TAHSİLATLAR çerçevesinin içinde kurar.

    Tahsilat tablosu ve bağlı makbuz kutusu bu çerçevenin çocukları olduğundan (Tk yalnız
    ebeveyn ya da onun torunlarında yerleştirir) sekmeler aynı çerçevenin içinde açılır.
    """
    from fatura_not_alani import not_buyut_dugmesi, not_kutusu_kur

    tablo = getattr(dialog, "tahsilat_tablosu", None)
    if tablo is None:
        return None
    lf = tablo.master
    alt = lf.master
    for cocuk in list(lf.winfo_children()):
        try:
            yon = cocuk.winfo_manager()
            if yon == "pack":
                cocuk.pack_forget()
            elif yon == "grid":
                cocuk.grid_forget()
        except tk.TclError:
            pass
    try:
        stil = ttk.Style(dialog)
        stil.configure("FaturaDetay.TLabelframe", borderwidth=0, relief="flat",
                       background=ftema.ACIK_BG)
        # Başlıksız çerçeve: etiket satırı yer kaplamasın
        stil.configure("FaturaDetay.TLabelframe.Label", background=ftema.ACIK_BG,
                       font=("Segoe UI", 1))
        stil.configure("FaturaDetay.TNotebook", background=ftema.BEYAZ, borderwidth=0,
                       tabmargins=(0, 0, 0, 0))
        stil.configure("FaturaDetay.TNotebook.Tab", padding=(10, 2),
                       font=_font(dialog, 9, "bold"))
        lf.configure(text="", padding=0, style="FaturaDetay.TLabelframe")
    except tk.TclError:
        pass
    for w in alt.grid_slaves():
        if w is not lf:
            try:
                w.grid_remove()
            except tk.TclError:
                pass
    try:
        lf.grid(row=0, column=0, columnspan=2, sticky="nsew")
        alt.columnconfigure(0, weight=1)
        alt.columnconfigure(1, weight=0)
    except tk.TclError:
        pass
    dialog._tahsilat_yesil_butonlar_hazir = True

    kart = tk.Frame(lf, bg=ftema.BEYAZ, highlightthickness=1, highlightbackground=ftema.CIZGI)
    kart.pack(fill="both", expand=True)
    kart.columnconfigure(0, weight=1)
    kart.rowconfigure(0, weight=1)

    nb = ttk.Notebook(kart, style="FaturaDetay.TNotebook", height=DETAY_YUKSEKLIK[1][1])
    nb.grid(row=0, column=0, sticky="nsew", padx=(6, 10), pady=(4, 4))
    sag, degerler = _toplamlar_kur(kart)
    sag.grid(row=0, column=1, sticky="se", padx=(0, 10), pady=(6, 4))
    _ipucu_bagla(
        degerler["brut"], "Brüt sabit (ölçüm) · Net = Uzlaşılan · Fiyat uydur Brüt’ü bozmaz"
    )

    # Notlar sekmesi
    tab_not = tk.Frame(nb, bg=ftema.BEYAZ)
    nb.add(tab_not, text="Notlar")
    not_w = not_kutusu_kur(tab_not)
    buyut = not_buyut_dugmesi(kart, dialog._fatura_notu_buyut)
    not_w.not_buyut_btn = buyut

    # Tahsilatlar sekmesi
    tab_tah = tk.Frame(nb, bg=ftema.BEYAZ)
    nb.add(tab_tah, text="Tahsilatlar (0)")
    tab_tah.columnconfigure(0, weight=3, uniform="tah")
    tab_tah.columnconfigure(1, weight=2, uniform="tah")
    tab_tah.rowconfigure(1, weight=1)

    sol_bas = tk.Frame(tab_tah, bg=ftema.BEYAZ)
    sol_bas.grid(row=0, column=0, sticky="ew", padx=(2, 6), pady=(3, 2))
    ekle = _kucuk_buton(sol_bas, "Fatura İçi Tahsilat Ekle", dialog.tahsilat_ekle, rol="onay")
    ekle.pack(side="left")
    _kucuk_buton(sol_bas, "Düzenle", dialog.tahsilat_duzenle).pack(side="left", padx=(4, 0))
    _kucuk_buton(sol_bas, "Kaldır", dialog.tahsilat_kaldir).pack(side="left", padx=(4, 0))
    _ipucu_bagla(ekle, "Faturayla birlikte kaydedilen tahsilat (fatura kaydında işlenir)")
    sol_govde = tk.Frame(tab_tah, bg=ftema.BEYAZ)
    sol_govde.grid(row=1, column=0, sticky="nsew", padx=(2, 6), pady=(0, 2))
    tablo_kay = ttk.Scrollbar(sol_govde, orient="vertical", command=tablo.yview)
    try:
        tablo.configure(height=2, yscrollcommand=tablo_kay.set)
    except tk.TclError:
        pass
    tablo.pack(in_=sol_govde, side="left", fill="both", expand=True)
    tablo_kay.pack(side="right", fill="y")
    tablo.lift()

    sag_bas = tk.Frame(tab_tah, bg=ftema.BEYAZ)
    sag_bas.grid(row=0, column=1, sticky="ew", padx=(6, 2), pady=(3, 2))
    if hasattr(dialog, "_fatura_tahsilat_makbuzu_ac"):
        yeni = _kucuk_buton(sag_bas, "Yeni Makbuz", dialog._fatura_tahsilat_makbuzu_ac, rol="vurgu")
        yeni.pack(side="left")
        _ipucu_bagla(yeni, "Kayıtlı faturaya bağlı ayrı tahsilat makbuzu (Tahsilat Makbuzu ile aynı)")
    _kucuk_buton(sag_bas, "Makbuzu Aç", lambda: _secili_makbuzu_ac(dialog)).pack(
        side="left", padx=(4, 0)
    )
    sag_govde = tk.Frame(tab_tah, bg=ftema.BEYAZ)
    sag_govde.grid(row=1, column=1, sticky="nsew", padx=(6, 2), pady=(0, 2))
    kutu = getattr(dialog, "_bagli_makbuz_kutu", None)
    if kutu is not None:
        for c in kutu.winfo_children():
            try:
                if isinstance(c, ttk.Label):
                    c.pack_forget()
                elif isinstance(c, ttk.Treeview):
                    c.configure(height=2)
                    c.heading("makbuz_no", text="Bağlı Makbuz No (tıklayın)")
                    c.pack_configure(fill="both", expand=True)
            except tk.TclError:
                pass
        kutu.pack(in_=sag_govde, fill="both", expand=True)
        kutu.lift()

    def _sekme_degisti(_e=None):
        try:
            if nb.index(nb.select()) == 0:
                buyut.place(in_=nb, relx=1.0, x=-2, y=1, anchor="ne")
                buyut.lift()
            else:
                buyut.place_forget()
        except tk.TclError:
            pass

    nb.bind("<<NotebookTabChanged>>", _sekme_degisti, add="+")
    _sekme_degisti()

    # Özet satırı: tahsil edilen / kalan / ödeme durumu + Ödeme ve Kapatma Bilgisi
    ozet = tk.Frame(lf, bg=ftema.ACIK_BG)
    ozet.pack(side="bottom", fill="x", before=kart, pady=(2, 0))
    etiketler = {}
    for anahtar, baslik in (("tahsil", "Tahsil edilen"), ("kalan", "Kalan"), ("durum", "Durum")):
        tk.Label(
            ozet, text=f"{baslik}:", bg=ftema.ACIK_BG, fg=ftema.IKINCIL, font=_font(dialog, 9),
        ).pack(side="left", padx=(8 if anahtar == "tahsil" else 12, 3))
        lbl = tk.Label(ozet, text="—", bg=ftema.ACIK_BG, fg=ftema.METIN,
                       font=_font(dialog, 9, "bold"))
        lbl.pack(side="left")
        etiketler[anahtar] = lbl
    kapatma = None
    try:
        from kapatma_detay_ui import OdemeKapatmaBilgisi

        kapatma = OdemeKapatmaBilgisi(
            ozet, fatura_turu="SATIS",
            fatura_id_getir=lambda: getattr(dialog.fatura, "id", None) if dialog.fatura else None,
        )
        kapatma.pack(side="right", fill="x", expand=True, padx=(16, 4))
        ttk.Style(dialog).configure("FaturaKucuk.TButton", padding=(6, 0))
        for c in kapatma.ic.winfo_children():
            if isinstance(c, ttk.Button):
                c.configure(style="FaturaKucuk.TButton")
        kapatma.yenile()
    except Exception:
        kapatma = None
    dialog._odeme_kapatma_bilgisi = kapatma

    dialog._fatura_detay = {
        "nb": nb, "tab_not": tab_not, "tab_tahsilat": tab_tah, "ozet": ozet,
        "ozet_etiketleri": etiketler, "not_buyut": buyut, "kart": kart,
    }
    return {
        "dis": None, "kart": kart, "not_alani": not_w, "degerler": degerler,
        "sag": sag, "sol": nb, "analiz": None, "islem": None,
    }


def _secili_makbuzu_ac(dialog) -> None:
    tablo = getattr(dialog, "_bagli_makbuz_tablo", None)
    if tablo is None or not tablo.selection():
        messagebox.showinfo(
            "Bağlı Makbuz", "Açmak için listeden bir makbuz seçin.", parent=dialog
        )
        return
    dialog._bagli_makbuzu_ac()


def tahsilat_ozetini_guncelle(
    dialog, tahsilat: Decimal, kalan: Decimal, genel: Decimal, para_goster
) -> None:
    detay = getattr(dialog, "_fatura_detay", None)
    if not detay:
        return
    et = detay["ozet_etiketleri"]
    if genel <= 0:
        durum, renk = "—", ftema.IKINCIL
    elif kalan < 0:
        durum, renk = "Fazla tahsilat", ftema.UYARI
    elif kalan == 0:
        durum, renk = "Ödendi", ftema.BASARI
    elif tahsilat > 0:
        durum, renk = "Kısmi ödendi", ftema.UYARI
    else:
        durum, renk = "Ödenmedi", ftema.IPTAL
    oz = getattr(dialog, "_bagli_makbuz_ozet", None) or {}
    makbuz = sum(1 for m in oz.get("makbuzlar", ()) if m.get("durum") != "IPTAL")
    adet = len(getattr(dialog, "tahsilatlar", ()) or ()) + makbuz
    try:
        et["tahsil"].configure(text=para_goster(tahsilat))
        et["kalan"].configure(text=para_goster(kalan))
        et["durum"].configure(text=durum, fg=renk)
        detay["nb"].tab(detay["tab_tahsilat"], text=f"Tahsilatlar ({adet})")
    except tk.TclError:
        pass


def iade_detay_uygula(dialog) -> None:
    """İade ekranında tahsilat sekmesi ve ödeme özeti yok; Notlar ve toplamlar kalır."""
    detay = getattr(dialog, "_fatura_detay", None)
    if not detay:
        return
    try:
        detay["nb"].hide(detay["tab_tahsilat"])
        detay["nb"].select(detay["tab_not"])
        detay["ozet"].pack_forget()
    except tk.TclError:
        pass


# ─── Gövde: form kaydırması yok, tablo kalan alanı doldurur ───────


def _detay_yuksekligi(dialog) -> None:
    try:
        h = dialog.winfo_height()
    except tk.TclError:
        return
    if h < 100:
        return
    sikilik_uygula(dialog, h < SIKI_YUKSEKLIK)
    _satir_yuksekligi(dialog, h < DETAY_YUKSEKLIK[0][0])
    detay = getattr(dialog, "_fatura_detay", None)
    if not detay:
        return
    hedef = next(y for sinir, y in DETAY_YUKSEKLIK if h < sinir)
    if detay.get("yukseklik") != hedef:
        detay["yukseklik"] = hedef
        try:
            detay["nb"].configure(height=hedef)
        except tk.TclError:
            pass


def govdeyi_sabitle(dialog) -> None:
    canvas = getattr(dialog, "canvas", None)
    pid = getattr(dialog, "_canvas_icerik_id", None)
    if canvas is None or pid is None or getattr(dialog, "_govde_sabit", False):
        return
    dialog._govde_sabit = True

    def _boyut(_e=None):
        try:
            w, h = canvas.winfo_width(), canvas.winfo_height()
            if w < 2 or h < 2:
                return
            canvas.itemconfigure(pid, width=w, height=h)
            canvas.configure(scrollregion=(0, 0, w, h))
            canvas.yview_moveto(0)
        except tk.TclError:
            pass

    canvas.bind("<Configure>", _boyut)
    dialog.icerik.bind("<Configure>", _boyut)
    kap = canvas.master
    for c in kap.winfo_children():
        if isinstance(c, (ttk.Scrollbar, tk.Scrollbar)):
            try:
                c.pack_forget()
            except tk.TclError:
                pass
    try:
        kap.configure(padding=(2, 0))
    except tk.TclError:
        pass
    _boyut()


def icerigi_yerlestir(dialog) -> None:
    """Pack sırası: üst bilgiler → (alt detay, altta sabit) → ürün satırları (genişler)."""
    icerik = getattr(dialog, "icerik", None)
    tablo = getattr(dialog, "satir_tablosu", None)
    if icerik is None or tablo is None:
        return
    satir = _ata(tablo, icerik)
    alt = _ata(getattr(dialog, "tahsilat_tablosu", None), icerik)
    try:
        if alt is not None:
            alt.pack_forget()
            alt.pack(side="bottom", fill="x", pady=(2, 0))
        if satir is not None:
            satir.pack_forget()
            satir.pack(side="top", fill="both", expand=True, pady=0)
            satir.rowconfigure(1, weight=1, minsize=0)
            if isinstance(satir, ttk.LabelFrame):
                # Sütun başlıkları tabloyu zaten tanımlıyor; çerçeve başlığı yer kaplamasın
                stil = ttk.Style(dialog)
                zemin = stil.lookup("TLabelframe", "background") or ftema.ACIK_BG
                stil.configure("FaturaUrun.TLabelframe", padding=2)
                stil.configure("FaturaUrun.TLabelframe.Label", font=("Segoe UI", 1),
                               foreground=zemin, background=zemin)
                satir.configure(style="FaturaUrun.TLabelframe")
        tablo.configure(height=3)
        tahsilat = getattr(dialog, "tahsilat_tablosu", None)
        if tahsilat is not None:
            tahsilat.configure(height=2)
    except tk.TclError:
        pass


SIKI_YUKSEKLIK = 800  # bu iç yüksekliğin altında üst bölümde iç boşluklar en aza iner


def _sinirla(deger, ust_sinir: int):
    if isinstance(deger, (tuple, list)):
        return tuple(min(int(d), ust_sinir) for d in deger)
    try:
        return min(int(deger), ust_sinir)
    except (TypeError, ValueError):
        return deger


def sikilik_kur(dialog) -> None:
    """Üst bilgi panelleri ve ürün şeridindeki boşlukların ilk değerlerini saklar."""
    if getattr(dialog, "_sikilik", None) is not None:
        return
    kayitlar = []

    def _gez(w):
        for c in w.winfo_children():
            try:
                yon = c.winfo_manager()
                if yon in ("grid", "pack"):
                    info = c.grid_info() if yon == "grid" else c.pack_info()
                    kayitlar.append((c, yon, info.get("pady", 0), info.get("ipady", 0)))
            except tk.TclError:
                pass
            _gez(c)

    for kok in (getattr(dialog, "_fatura_ust_panel", None), getattr(dialog, "_urun_secim_serit", None)):
        if kok is not None:
            _gez(kok)
    cerceveler = []
    ust = getattr(dialog, "_fatura_ust_panel", None)
    if ust is not None:
        cerceveler = [c for c in ust.winfo_children() if isinstance(c, ttk.LabelFrame)]
    dialog._sikilik = {"kayitlar": kayitlar, "cerceveler": cerceveler, "sik": None}


def sikilik_uygula(dialog, sik: bool) -> None:
    durum = getattr(dialog, "_sikilik", None)
    if durum is None or durum["sik"] == sik:
        return
    durum["sik"] = sik
    for w, yon, pady, ipady in durum["kayitlar"]:
        try:
            ayar = {"pady": _sinirla(pady, 1 if sik else 2)}
            if sik:
                ayar["ipady"] = _sinirla(ipady, 1)
            else:
                ayar["ipady"] = ipady
            if yon == "grid":
                w.grid_configure(**ayar)
            else:
                w.pack_configure(**ayar)
        except tk.TclError:
            pass
    for c in durum["cerceveler"]:
        try:
            c.configure(padding=(6, 0, 6, 2) if sik else (8, 2, 8, 4))
        except tk.TclError:
            pass
    adres = getattr(dialog, "adres_gorunum", None)
    if adres is not None:
        try:
            adres.configure(height=1 if sik else 2)
        except tk.TclError:
            pass
    refs = getattr(dialog, "_fatura_toolbar", None) or {}
    for anahtar in ("sol", "sag"):
        w = refs.get(anahtar)
        if w is not None:
            try:
                w.pack_configure(pady=4 if sik else 8)
            except tk.TclError:
                pass
    sag = refs.get("sag")
    if sag is not None:
        for c in sag.winfo_children():
            if isinstance(c, (tk.Button, tk.Menubutton)):
                try:
                    c.configure(pady=3 if sik else 5)
                except tk.TclError:
                    pass
    # Başlık ve fatura no / durum: sıkı modda tek satır
    sol = refs.get("sol")
    if sol is not None:
        for i, c in enumerate(sol.pack_slaves()):
            try:
                if sik:
                    c.pack_configure(side="left", anchor="center", padx=(0 if i == 0 else 12, 0), pady=0)
                else:
                    c.pack_configure(side="top", anchor="w", padx=0, pady=(4, 0) if i else 0)
            except tk.TclError:
                pass


def _satir_yuksekligi(dialog, alcak: bool) -> None:
    """Çok alçak pencerede (ör. 1366×768 %125) tablo satırı biraz daralır; yazı boyutu aynı."""
    if getattr(dialog, "_satir_alcak", None) == alcak:
        return
    dialog._satir_alcak = alcak
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is None:
        return
    try:
        stil = str(tablo.cget("style") or "")
        if stil:
            taban = ftema.scale_height(ftema.TABLO_SATIR_TABAN_PX)
            ttk.Style(dialog).configure(stil, rowheight=34 if alcak else taban)
    except tk.TclError:
        pass


def _kardes_dugme(alan, metin: str):
    if alan is None:
        return None
    for c in alan.master.winfo_children():
        try:
            if isinstance(c, ttk.Button) and str(c.cget("text")) == metin:
                return c
        except tk.TclError:
            continue
    return None


def ust_panel_genislik_kur(dialog) -> None:
    """Üst bilgi panellerinin dört sütunu tek satıra sığsın: geniş alanlar daraltılır,
    dar pencerede düğme metinleri kısalır (yazı boyutu değişmez)."""
    ust = getattr(dialog, "_fatura_ust_panel", None)
    if ust is None or getattr(dialog, "_ust_genislik_hazir", False):
        return
    dialog._ust_genislik_hazir = True
    for ad, genislik in (("adres_secimi", 16), ("adres_gorunum", 20), ("musteri_adi", 20)):
        w = getattr(dialog, ad, None)
        if w is not None:
            try:
                w.configure(width=genislik)
            except tk.TclError:
                pass
    ara = _kardes_dugme(getattr(dialog, "musteri_kodu", None), "Ara")
    if ara is not None:
        ara.configure(width=0)
    yeni_musteri = _kardes_dugme(getattr(dialog, "musteri_adi", None), "Yeni Müşteri")
    if yeni_musteri is not None:
        yeni_musteri.configure(width=0)
    genislikler = [
        (getattr(dialog, ad, None), uzun, kisa)
        for ad, uzun, kisa in (
            ("musteri_kodu", 14, 8), ("depo", 14, 9), ("adres_secimi", 16, 9),
            ("adres_gorunum", 20, 14), ("fatura_no_alani", 14, 10), ("durum", 9, 7),
            ("islem_saati_alani", 7, 5), ("vade_gunu", 7, 5), ("musteri_adi", 20, 16),
        )
    ]
    genislikler = [g for g in genislikler if g[0] is not None]
    sutunlar = []
    for ad, sutun_list in (("_fatura_ust_sol", (0, 2)), ("_fatura_ust_orta", (0,)),
                           ("_fatura_ust_sag", (0,))):
        panel = getattr(dialog, ad, None)
        if panel is None:
            continue
        for s in sutun_list:
            try:
                sutunlar.append((panel, s, int(panel.columnconfigure(s)["minsize"])))
            except (tk.TclError, KeyError, TypeError, ValueError):
                pass
    takvimler = []

    def _takvim_bul(w):
        for c in w.winfo_children():
            try:
                if isinstance(c, ttk.Button) and str(c.cget("text")) == "Takvim":
                    takvimler.append(c)
            except tk.TclError:
                pass
            _takvim_bul(c)

    if getattr(dialog, "_fatura_ust_sol", None) is not None:
        _takvim_bul(dialog._fatura_ust_sol)
    kisalar = [
        (getattr(dialog, "_btn_cari_hesap_karti", None), "Cari Hesap Kartı", "Cari Kart"),
        (yeni_musteri, "Yeni Müşteri", "Yeni"),
        (getattr(dialog, "_btn_yeni_adres", None), "Yeni Adres Ekle", "Yeni Adres"),
        (_kardes_dugme(getattr(dialog, "depo", None), "Yeni Depo"), "Yeni Depo", "Yeni"),
        (getattr(dialog, "_ort_gun_baslik", None), None, "Ort. Vade"),
    ] + [(t, "Takvim", "▼") for t in takvimler]
    for panel_ad, metinler in (
        ("_fatura_ust_cari", {"Eski Bakiye": "Eski", "Yeni Bakiye": "Yeni"}),
        ("_fatura_ust_sol", {"İşlem Saati": "Saat"}),
    ):
        panel = getattr(dialog, panel_ad, None)
        if panel is None:
            continue
        for c in panel.winfo_children():
            try:
                metin = str(c.cget("text"))
            except tk.TclError:
                continue
            if metin in metinler:
                kisalar.append((c, metin, metinler[metin]))
    paneller = [
        p for p in (getattr(dialog, a, None) for a in ("_fatura_ust_sol", "_fatura_ust_orta",
                                                       "_fatura_ust_sag"))
        if p is not None
    ]
    bosluk = getattr(dialog, "_fatura_ust_gap", 10)
    kisalar = [
        (w, uzun if uzun is not None else str(w.cget("text")), kisa)
        for w, uzun, kisa in kisalar if w is not None
    ]
    for w, _u, _k in kisalar:
        if isinstance(w, ttk.Button):
            try:
                w.configure(width=0)
            except tk.TclError:
                pass
    durum = {"dar": None}

    def _uygula(e=None):
        try:
            g = int(e.width) if e is not None else ust.winfo_width()
        except (tk.TclError, TypeError, ValueError):
            return
        if g < 40:
            return
        dar = g < 1450
        if durum["dar"] == dar:
            return
        durum["dar"] = dar
        for w, uzun, kisa in kisalar:
            try:
                w.configure(text=kisa if dar else uzun)
            except tk.TclError:
                pass
        for w, uzun, kisa in genislikler:
            try:
                w.configure(width=kisa if dar else uzun)
            except tk.TclError:
                pass
        for panel, s, minsize in sutunlar:
            try:
                panel.columnconfigure(s, minsize=0 if dar else minsize)
            except tk.TclError:
                pass
        for p in paneller:
            try:
                if p.winfo_manager() == "grid" and int(p.grid_info().get("row", 0)) == 0:
                    p.grid_configure(padx=(0, 4 if dar else bosluk))
            except (tk.TclError, TypeError, ValueError):
                pass
        # Daralırken en çok boşluğu olan Fatura Bilgileri paneli küçülsün
        agirlik = (40, 36, 16, 4) if dar else (24, 31, 27, 18)
        en_az = (0, 0, 0, 175) if dar else (200, 240, 210, 140)
        for s, a in enumerate(agirlik):
            try:
                ust.columnconfigure(s, weight=a, minsize=en_az[s])
            except tk.TclError:
                pass

    ust.bind("<Configure>", _uygula, add="+")
    _uygula()


def yerlesimi_tamamla(dialog) -> None:
    """Açılış sonunda bir kez: gövdeyi sabitle, sırala, üst çubuğu sığdır."""
    govdeyi_sabitle(dialog)
    icerigi_yerlestir(dialog)
    ust_panel_genislik_kur(dialog)
    sikilik_kur(dialog)
    arac_cubugu_sigdir_kur(dialog)
    if not getattr(dialog, "_detay_yukseklik_bagli", False):
        dialog._detay_yukseklik_bagli = True

        def _yukseklik(e):
            if e.widget is dialog:
                _detay_yuksekligi(dialog)

        dialog.bind("<Configure>", _yukseklik, add="+")
    _detay_yuksekligi(dialog)
