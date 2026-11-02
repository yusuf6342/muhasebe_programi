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

# Pencere iç yüksekliğine göre sekme gövdesi (px): kısa pencerede ürün tablosuna öncelik
DETAY_YUKSEKLIK = ((700, 44), (860, 68), (10_000, 96))


def _font(w, boyut: int, kalinlik: str = "normal"):
    return ftema.font(boyut, kalinlik, w.winfo_toplevel())


def _menubutton(parent, metin: str, *, rol: str = "yardimci", grup: str = "dis"):
    """Kompakt oval menü düğmesi + Menu."""
    menu = tk.Menu(parent, tearoff=0)
    mb = ftema.oval_buton(parent, metin, rol=rol, menu=menu, grup=grup)
    return mb, menu


def _kucuk_buton(parent, metin: str, komut, *, rol: str = "yardimci", grup: str = "panel"):
    """Panel içi kompakt oval düğme."""
    return ftema.oval_buton(parent, metin, komut, rol=rol, grup=grup)


# ─── Üst işlem çubuğu ──────────────────────────────────────────────


def yazdir_menusu_kur(dialog, parent):
    """Önizleme, Yazdır ve PDF tek «Yazdır / PDF» menüsünde; kısayollar aynı kalır."""
    mb, menu = _menubutton(parent, "Yazdır / PDF ▾", rol="yardimci")
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
    """Dar pencerede işlem butonlarını ikinci satıra sarar; gizlemez.

    Sığmayanlar düzenli 2. satıra iner. Müşteri kısa adı gerekirse gizlenebilir.
    """
    refs = getattr(dialog, "_fatura_toolbar", None) or {}
    cubuk, sol, sag = refs.get("cubuk"), refs.get("sol"), refs.get("sag")
    satirlar_frame = [sag]
    for anahtar in ("sag2", "sag3"):
        fr = refs.get(anahtar)
        if fr is not None:
            satirlar_frame.append(fr)
    if cubuk is None or sag is None or getattr(dialog, "_arac_sigdir", None):
        return
    try:
        cubuk.update_idletasks()
    except tk.TclError:
        return
    # Kalıcı sıra: bir kez yakala (pack_forget sonrası slaves boşalmasın)
    sira: list = []
    for fr in satirlar_frame:
        sira.extend(w for w in fr.pack_slaves())
    if not sira:
        return
    padx_bilgi = {}
    for w in sira:
        try:
            if w.winfo_manager() == "pack":
                padx_bilgi[str(w)] = w.pack_info().get("padx", 2)
            else:
                padx_bilgi[str(w)] = 2
        except tk.TclError:
            padx_bilgi[str(w)] = 2
    musteri = refs.get("musteri")
    musteri_pay = 230
    durum = {"anahtar": None}
    dialog._arac_sigdir = durum
    dialog._arac_buton_sira = sira

    def _widget_genislik(w) -> int:
        try:
            req = int(w.winfo_reqwidth())
            if req <= 1:
                return 0  # ayırıcı / boş frame — satır hesabına katma
            padx = padx_bilgi.get(str(w), 2)
            return req + _yatay_pay({"padx": padx})
        except tk.TclError:
            return 0

    def _tam_sol() -> int:
        w = sol.winfo_reqwidth() if sol is not None else 0
        if musteri is not None:
            if musteri.winfo_manager() == "pack":
                w += max(0, musteri_pay - musteri.winfo_reqwidth())
            else:
                w += musteri_pay
        return w

    def _paketle(hedef, widgets):
        for w in widgets:
            try:
                w.pack_forget()
            except tk.TclError:
                pass
            px = padx_bilgi.get(str(w), 2)
            try:
                w.pack(side="left", padx=px, in_=hedef)
            except tk.TclError:
                try:
                    w.pack(side="left", padx=2, in_=hedef)
                except tk.TclError:
                    pass

    def _dagit(uygun: int, frame_list: list) -> list[list]:
        """Butonları soldan sağa satırlara böl."""
        satirlar: list[list] = [[] for _ in frame_list]
        si = 0
        kalan = uygun
        for w in sira:
            gw = _widget_genislik(w)
            if gw <= 0:
                satirlar[si].append(w)
                continue
            while si < len(satirlar) - 1 and kalan < gw:
                si += 1
                kalan = uygun
            satirlar[si].append(w)
            kalan -= gw
        return satirlar

    def _buton_genislik_ayarla(hedef: int | None) -> None:
        """Kısa pencerede oval butonları daralt (2 satıra sığsın, tablo ezilmesin)."""
        for w in sira:
            if not isinstance(w, ftema.FaturaOvalButon):
                continue
            try:
                if hedef is None:
                    gw, _gh = ftema.fatura_buton_olculeri(dialog, grup=getattr(w, "_grup", "dis"))
                else:
                    gw = int(hedef)
                if int(getattr(w, "_gw", 0) or 0) == gw:
                    continue
                w._gw = gw
                w._canvas.configure(width=gw)
                w._ciz()
            except tk.TclError:
                pass

    def _uygula(_e=None):
        try:
            cubuk.update_idletasks()
            W = cubuk.winfo_width()
            H = int(dialog.winfo_height())
        except tk.TclError:
            return
        if W < 100 or not sira:
            return
        try:
            # Sol meta reqwidth şişebiliyor; sağ butonlara en az %55 bırak
            sol_w = int(sol.winfo_reqwidth()) if sol is not None else 0
            sol_w = min(sol_w, max(120, int(W * 0.40)))
            uygun = max(220, W - sol_w - 20)
        except tk.TclError:
            uygun = max(220, W - _tam_sol() - 36)
        # Kısa+dar: ikincil düğmeleri şeritten çıkar (Diğer menüde kalır) → tek satır, tabloya yer
        kisa = H < 640
        dar = W < 1250
        ikincil_attr = ("_fatura_liste_btn", "_sevkiyat_btn", "_dosyadan_aktar_btn")
        ikincil = {getattr(dialog, a, None) for a in ikincil_attr}
        ikincil.discard(None)
        aktif_sira = [w for w in sira if not (kisa and dar and w in ikincil)]
        for w in ikincil:
            try:
                if kisa and dar:
                    w.pack_forget()
            except tk.TclError:
                pass
        # Kısa+dar: tek satır + dar buton; kısa (geniş): en fazla 2 satır
        frame_list = satirlar_frame[:1] if (kisa and dar) else (
            satirlar_frame[:2] if kisa else satirlar_frame
        )
        if kisa:
            n_buton = max(1, len([w for w in aktif_sira if isinstance(w, ftema.FaturaOvalButon)]))
            per_row = max(4, (n_buton + len(frame_list) - 1) // max(1, len(frame_list)))
            hedef = max(92, min(130, (uygun // per_row) - 4))
            _buton_genislik_ayarla(hedef)
        else:
            _buton_genislik_ayarla(None)

        def _dagit_sira(uygun_w: int, frame_list_local: list, kaynak: list) -> list[list]:
            satirlar: list[list] = [[] for _ in frame_list_local]
            si = 0
            kalan = uygun_w
            for w in kaynak:
                gw = _widget_genislik(w)
                if gw <= 0:
                    satirlar[si].append(w)
                    continue
                while si < len(satirlar) - 1 and kalan < gw:
                    si += 1
                    kalan = uygun_w
                satirlar[si].append(w)
                kalan -= gw
            return satirlar

        bolunmus = _dagit_sira(uygun, frame_list, aktif_sira)
        while len(bolunmus) < len(satirlar_frame):
            bolunmus.append([])
        musteri_gizle = bool(musteri is not None and (_tam_sol() + 40 > W))
        anahtar = (
            tuple(tuple(str(w) for w in satir) for satir in bolunmus),
            musteri_gizle,
            uygun,
        )
        if durum["anahtar"] == anahtar:
            return
        durum["anahtar"] = anahtar
        if musteri is not None:
            try:
                if musteri_gizle:
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
        for i, fr in enumerate(satirlar_frame):
            widgets = bolunmus[i] if i < len(bolunmus) else []
            try:
                if i == 0:
                    pass  # sag her zaman pack
                elif widgets:
                    if fr.winfo_manager() != "pack":
                        fr.pack(side="top", anchor="e", pady=(1 if kisa else 3, 0))
                elif fr.winfo_manager() == "pack":
                    fr.pack_forget()
            except tk.TclError:
                pass
            if widgets:
                _paketle(fr, widgets)

    def _uygula_guvenli(e=None):
        try:
            _uygula(e)
        except Exception:
            pass

    cubuk.bind("<Configure>", _uygula_guvenli, add="+")
    dialog.after_idle(_uygula_guvenli)
    _uygula_guvenli()


def _diger_menusune_tasinanlari_ekle(
    dialog, *, liste_var: bool, sevkiyat_var: bool = False, dosya_var: bool = False
) -> None:
    """Geriye uyumluluk: butonlar artık gizlenmediği için menüye ekleme yapılmaz."""
    _ = (dialog, liste_var, sevkiyat_var, dosya_var)
    return


# ─── Ürün şeridi: Satır İşlemleri ─────────────────────────────────


def satir_islemleri_dugmesi(dialog, parent):
    """Ürün şeridi — eşit oval «Satır İşlemleri ▾» menü düğmesi."""
    menu = tk.Menu(parent, tearoff=0)

    def _doldur():
        from fatura_satir_araclar import satir_islemleri_doldur

        menu.delete(0, "end")
        satir_islemleri_doldur(dialog, menu)

    menu.configure(postcommand=_doldur)
    mb = ftema.oval_buton(parent, "Satır İşlemleri ▾", rol="yardimci", menu=menu, grup="dis")
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
        ).grid(row=satir, column=k, sticky="e", padx=(16 if grup else 0, 6), pady=0)
        if yuzde:
            oran = tk.Label(
                sag, text="%0,00", bg=ftema.BEYAZ, fg=ftema.METIN, font=kucuk,
                anchor="e", width=7,
            )
            oran.grid(row=satir, column=k + 1, sticky="e", padx=(0, 4), pady=0)
            degerler[f"{anahtar}_oran"] = oran
        # Sabit genişlik: tutar yazılırken (Uzlaşılan) metin uzunluğu değişse de yerleşim kaymaz
        deger = tk.Label(
            sag, text="—" if anahtar == "doviz" else "0,00 TL", bg=ftema.BEYAZ,
            fg=ftema.METIN, font=kalin, anchor="e", width=15,
        )
        deger.grid(row=satir, column=k + 2, sticky="e", pady=0)
        degerler[anahtar] = deger
    tk.Frame(sag, bg=ftema.CIZGI, height=1).grid(
        row=4, column=0, columnspan=7, sticky="ew", pady=(2, 1)
    )
    tk.Label(
        sag, text="Net Toplam", bg=ftema.BEYAZ, fg=ftema.LACIVERT,
        font=_font(parent, 11, "bold"), anchor="e",
    ).grid(row=5, column=0, columnspan=5, sticky="e", padx=(0, 10), pady=0)
    net = tk.Label(
        sag, text="0,00 TL", bg=ftema.BEYAZ, fg=ftema.LACIVERT,
        font=_font(parent, 12, "bold"), anchor="e", width=16,
    )
    net.grid(row=5, column=5, columnspan=2, sticky="e", pady=0)
    degerler["genel"] = net
    # Faturaya ek fon bedeli: yalnız bedel varsa görünür (dialog._toplamlari_guncelle açar)
    gizli = []
    for sutun, anahtar, baslik in ((0, "fon_ek", "Ek Fon Bedeli"), (1, "fon_ek_kdv", "Ek Fon KDV")):
        k = sutun * 4
        et = tk.Label(sag, text=baslik, bg=ftema.BEYAZ, fg=ftema.IKINCIL, font=kucuk, anchor="e")
        et.grid(row=6, column=k, sticky="e", padx=(16 if sutun else 0, 6))
        deger = tk.Label(sag, text="0,00 TL", bg=ftema.BEYAZ, fg=ftema.METIN, font=kalin, anchor="e", width=15)
        deger.grid(row=6, column=k + 2, sticky="e")
        degerler[anahtar] = deger
        gizli += [et, deger]
    et = tk.Label(sag, text="Ödenecek Toplam", bg=ftema.BEYAZ, fg=ftema.LACIVERT,
                  font=_font(parent, 12, "bold"), anchor="e")
    et.grid(row=7, column=0, columnspan=5, sticky="e", padx=(0, 10))
    odenecek = tk.Label(sag, text="0,00 TL", bg=ftema.BEYAZ, fg=ftema.LACIVERT,
                        font=_font(parent, 13, "bold"), anchor="e", width=16)
    odenecek.grid(row=7, column=5, columnspan=2, sticky="e")
    degerler["odenecek"] = odenecek
    gizli += [et, odenecek]
    for w in gizli:
        w.grid_remove()
    degerler["_fon_ek_widgetleri"] = gizli
    # Maliyet / kâr / marj normal fatura ekranında gösterilmez; KarlilikAnaliziDialog'da açılır.
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
                       font=_font(dialog, 9, "bold"), width=16, anchor="w")
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
    # Kısa pencere: alt özet/kart dikey payını sıkıştır → ürün tablosu ≥50 px
    kisa = h < 640
    if detay.get("_kisa_pad") != kisa:
        detay["_kisa_pad"] = kisa
        try:
            ozet = detay.get("ozet")
            if ozet is not None and ozet.winfo_manager() == "pack":
                ozet.pack_configure(pady=(0 if kisa else 2, 0))
            detay["nb"].grid_configure(pady=(2 if kisa else 4, 2 if kisa else 4))
            sag = (getattr(dialog, "_fatura_alt_ozet", None) or {}).get("sag")
            if sag is not None:
                sag.grid_configure(pady=(4 if kisa else 6, 2 if kisa else 4))
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
    # Proje satırı sıkı modda gizlenir (ürün tablosuna yer); değer korunur
    proje = getattr(dialog, "fatura_proje", None)
    if proje is not None:
        try:
            if sik:
                info = proje.grid_info()
                if info:
                    durum["proje_grid"] = dict(info)
                    durum["proje_grid"].pop("in", None)
                for w in (proje, getattr(dialog, "_fatura_proje_etiket", None)):
                    if w is not None and w.winfo_manager() == "grid":
                        w.grid_remove()
            else:
                kayit = durum.get("proje_grid")
                if kayit:
                    proje.grid(**kayit)
                et = getattr(dialog, "_fatura_proje_etiket", None)
                if et is not None and et.winfo_manager() != "grid":
                    try:
                        et.grid()
                    except tk.TclError:
                        pass
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
            if isinstance(c, ftema.FaturaOvalButon):
                continue  # oval ölçüler sabit
            if isinstance(c, (tk.Button, tk.Menubutton)):
                try:
                    c.configure(pady=3 if sik else 5)
                except tk.TclError:
                    pass
    # Sıkı modda sol başlığı dikey tut (yatay tek satır Kaydet/Kapat'ı sıkıştırıyordu)
    sol = refs.get("sol")
    if sol is not None:
        for i, c in enumerate(sol.pack_slaves()):
            try:
                c.pack_configure(side="top", anchor="w", padx=0, pady=(2 if sik else 4, 0) if i else 0)
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
            if str(c.cget("text")) == metin and isinstance(
                c, (ttk.Button, tk.Button, ftema.FaturaOvalButon)
            ):
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
    yeni_musteri = _kardes_dugme(getattr(dialog, "musteri_adi", None), "Yeni")
    if yeni_musteri is None:
        yeni_musteri = _kardes_dugme(getattr(dialog, "musteri_adi", None), "Yeni Müşteri")
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
    # Panel oval düğmeler zaten kompakt «Yeni» / «Cari Kart»; kısaltma uygulanmaz
    kisalar = [
        (getattr(dialog, "_btn_cari_hesap_karti", None), "Cari Kart", "Cari Kart"),
        (yeni_musteri, "Yeni", "Yeni"),
        (getattr(dialog, "_btn_yeni_adres", None), "Yeni", "Yeni"),
        (_kardes_dugme(getattr(dialog, "depo", None), "Yeni"), "Yeni", "Yeni"),
    ] + [(t, "Takvim", "▼") for t in takvimler]
    for panel_ad, metinler in (
        ("_fatura_ust_cari", {
            "Kalan Bakiye": "Kalan Bakiye",
            "Kalan Bakiye Gün": "Kalan Gün",
            "Kapatılan Bakiye Gün": "Kapatılan Gün",
            "Toplam Borç": "Toplam Borç",
            "Toplam Alacak": "Toplam Alacak",
        }),
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
            # Oval eşit-boyut butonlarda yazı kısaltılmaz (talimat)
            if isinstance(w, ftema.FaturaOvalButon):
                continue
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
        # İki satırlı dar mod (_fatura_ust_responsive) kendi ağırlıklarını yönetir; çakışma olmasın
        if getattr(dialog, "_fatura_ust_dar", False):
            return
        # Müşteri(0) · Fatura(1) · Depo(2) · Cari(3) — dört eşit sütun (uniform)
        en_az = 140 if dar else 160
        for s in range(4):
            try:
                ust.columnconfigure(s, weight=1, minsize=en_az, uniform="fatura_ust")
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
