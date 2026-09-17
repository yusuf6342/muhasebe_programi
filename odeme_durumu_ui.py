"""FİNANS → RAPORLAR → Aylara Göre Ödeme Durumu — 5 aylık dinamik görünüm."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import tkinter as tk
from tkinter import messagebox, ttk

from database.access import yetki_var
from database.odeme_durumu_service import (
    DURUM_BUGUN,
    DURUM_GECIKMIS,
    DURUM_KISMI,
    DURUM_ODENDI,
    DURUM_PLANLANDI,
    DURUM_YAKLASIYOR,
    KAYNAK_CEK,
    KAYNAK_KK,
    KAYNAK_KREDI,
    OdemeDurumuService,
    ROL_BU_AY,
    ROL_GECEN,
    ROL_GELECEK,
)
from database.session_manager import oturum

_NAVY = "#0b1f3a"
_YELLOW = "#e8b923"
_BG = "#eef1f5"
_PANEL = "#ffffff"
_BU_AY_BG = "#fff8e1"
_BU_AY_BORDER = "#e8b923"
_GECEN_BORDER = "#90a4ae"
_GELECEK_BORDER = "#5c6bc0"
_CIZGI = "#d0d7de"

# Tarih / meblağ: normal gövde 9pt → 10pt bold
_FONT_TARIH = ("Segoe UI", 10, "bold")
_FONT_TUTAR = ("Segoe UI", 10, "bold")
_FONT_ACIKLAMA = ("Segoe UI", 9)
_FONT_META = ("Segoe UI", 8)

_DURUM_RENK = {
    DURUM_PLANLANDI: "#2e86c1",
    DURUM_YAKLASIYOR: "#c9a227",
    DURUM_BUGUN: "#e67e22",
    DURUM_GECIKMIS: "#c0392b",
    DURUM_KISMI: "#d35400",
    DURUM_ODENDI: "#1e8449",
    "IPTAL": "#566573",
}

_DURUM_ETIKET = {
    DURUM_PLANLANDI: "Planlandı",
    DURUM_YAKLASIYOR: "Yaklaşıyor",
    DURUM_BUGUN: "Bugün",
    DURUM_GECIKMIS: "Gecikmiş",
    DURUM_KISMI: "Kısmen ödendi",
    DURUM_ODENDI: "Ödendi",
}


def _para(tutar) -> str:
    return (
        f"{Decimal(str(tutar or 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        + " TL"
    )


def _tarih(d) -> str:
    if not d:
        return ""
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d)


def _finans_isaretle(app):
    try:
        from finans_ui import _finans_menu_isaretle

        _finans_menu_isaretle(app)
    except Exception:
        pass


def finans_raporlar_menusu_goster(app):
    app._icerigi_temizle()
    _finans_isaretle(app)
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="FİNANS RAPORLARI", style="Baslik.TLabel").pack(side="left")
    try:
        from finans_ui import finans_menusu_goster

        ttk.Button(ust, text="← Finans Menüsü", command=lambda: finans_menusu_goster(app)).pack(
            side="right"
        )
    except Exception:
        pass
    ttk.Label(
        app.icerik,
        text="Nakit çıkışı takvimi, ödeme durumu ve finans özet raporları.",
    ).pack(anchor="w", pady=(8, 0))
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(24, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    nav = getattr(app, "nav_ac", lambda c: c())
    ttk.Button(
        alt,
        text="AYLARA GÖRE ÖDEME DURUMU",
        style="AltMenu.TButton",
        command=lambda: nav(lambda: odeme_durumu_sayfasi_goster(app)),
    ).grid(row=0, column=0, sticky="ew", pady=4)
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: finans_raporlar_menusu_goster(app))


def _kpi_serit(parent, rapor: dict):
    wrap = tk.Frame(parent, bg=_BG)
    wrap.pack(fill="x", pady=(4, 8))
    donem = rapor.get("donem") or {}
    bu_ay = next((a for a in rapor.get("aylar") or [] if a.get("rol") == ROL_BU_AY), {})
    kartlar = (
        ("Bu ay kalan", bu_ay.get("kalan")),
        ("Gecikmiş", donem.get("vadesi_gecmis")),
        ("5 ay yükümlülük", donem.get("toplam_yukumluluk")),
        ("5 ay kalan", donem.get("toplam_kalan")),
        ("5 ay ödenen", donem.get("toplam_odenen")),
        ("Gelecek 3 ay", donem.get("gelecek_uc_ay")),
    )
    for i, (baslik, deger) in enumerate(kartlar):
        kutu = tk.Frame(wrap, bg=_PANEL, highlightbackground="#cfd6e0", highlightthickness=1)
        kutu.grid(row=0, column=i, padx=3, sticky="nsew")
        wrap.columnconfigure(i, weight=1)
        tk.Label(kutu, text=baslik, bg=_PANEL, fg="#445", font=("Segoe UI", 8)).pack(
            anchor="w", padx=8, pady=(6, 0)
        )
        renk = "#c0392b" if "Gecik" in baslik else _NAVY
        tk.Label(
            kutu, text=_para(deger), bg=_PANEL, fg=renk, font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", padx=8, pady=(2, 8))


def _odeme_satiri(parent, satir: dict, *, bg: str, wrap_px: int, odeme_ac_cb):
    """Tek ödeme satırı — açıklama alt satır, tarih/tutar büyük koyu, Öde butonu."""
    durum = satir.get("durum") or DURUM_PLANLANDI
    durum_renk = _DURUM_RENK.get(durum, _NAVY)
    tutar = satir.get("kalan") if satir.get("kalan") is not None else satir.get("tl_tutar")
    odenebilir = durum not in (DURUM_ODENDI, "IPTAL") and Decimal(str(tutar or 0)) > 0

    satir_frm = tk.Frame(parent, bg=bg, cursor="hand2")
    satir_frm.pack(fill="x", padx=4, pady=0)

    ust = tk.Frame(satir_frm, bg=bg)
    ust.pack(fill="x", padx=4, pady=(6, 0))
    tk.Label(
        ust,
        text=_tarih(satir.get("due_date")),
        bg=bg,
        fg=_NAVY,
        font=_FONT_TARIH,
    ).pack(side="left")
    gun = satir.get("kalan_gun")
    gun_metin = f"  {gun} gün" if gun is not None and gun != "" else ""
    tk.Label(
        ust,
        text=f"{_DURUM_ETIKET.get(durum, durum)}{gun_metin}",
        bg=bg,
        fg=durum_renk,
        font=_FONT_META,
    ).pack(side="left", padx=(8, 0))
    tk.Label(
        ust,
        text=_para(tutar),
        bg=bg,
        fg=_NAVY,
        font=_FONT_TUTAR,
    ).pack(side="right")

    tk.Label(
        satir_frm,
        text=satir.get("aciklama") or "—",
        bg=bg,
        fg="#333",
        font=_FONT_ACIKLAMA,
        wraplength=max(120, wrap_px - 24),
        justify="left",
        anchor="w",
    ).pack(fill="x", padx=4, pady=(2, 0))

    meta = tk.Frame(satir_frm, bg=bg)
    meta.pack(fill="x", padx=4, pady=(0, 4))
    tk.Label(
        meta,
        text=satir.get("kaynak_etiket") or "",
        bg=bg,
        fg="#666",
        font=_FONT_META,
    ).pack(side="left")
    banka = satir.get("banka_adi") or ""
    if banka:
        tk.Label(meta, text=f" · {banka}", bg=bg, fg="#666", font=_FONT_META).pack(side="left")
    if odenebilir:
        ttk.Button(
            meta,
            text="Öde",
            width=6,
            command=lambda s=satir: odeme_ac_cb(s),
        ).pack(side="right", padx=(4, 0))

    # Ayırıcı çizgi
    tk.Frame(parent, bg=_CIZGI, height=1).pack(fill="x", padx=6, pady=0)

    def _tik(_e=None, s=satir):
        if odenebilir:
            odeme_ac_cb(s)

    for w in (satir_frm, ust):
        w.bind("<Double-Button-1>", _tik)
    for child in ust.winfo_children():
        child.bind("<Double-Button-1>", _tik)
    for child in satir_frm.winfo_children():
        if isinstance(child, tk.Label):
            child.bind("<Double-Button-1>", _tik)


def _liste_tekerlek_bagla(canvas: tk.Canvas, kok: tk.Widget) -> None:
    """Ay içi ödeme listesinde fare tekerleği ile dikey kaydırma.

    Canvas içindeki satır etiketlerinde de çalışır (Enter/Leave kök çerçevede).
    """

    def _kaydir(event):
        delta = getattr(event, "delta", 0)
        if delta:
            adim = int(-1 * (delta / 120))
            if adim == 0:
                adim = -1 if delta > 0 else 1
            canvas.yview_scroll(adim, "units")
        elif getattr(event, "num", None) == 4:
            canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", None) == 5:
            canvas.yview_scroll(1, "units")
        return "break"

    def _bagla(_event=None):
        canvas.bind_all("<MouseWheel>", _kaydir)
        canvas.bind_all("<Button-4>", _kaydir)
        canvas.bind_all("<Button-5>", _kaydir)

    def _coz(_event=None):
        canvas.unbind_all("<MouseWheel>")
        canvas.unbind_all("<Button-4>")
        canvas.unbind_all("<Button-5>")

    kok.bind("<Enter>", _bagla)
    kok.bind("<Leave>", _coz)

    def _altlara_bagla(w):
        w.bind("<Enter>", _bagla)
        for ch in w.winfo_children():
            _altlara_bagla(ch)

    _altlara_bagla(kok)


def _ay_karti(parent, ay_ozet: dict, *, odeme_ac_cb, sutun: int):
    """Orantılı genişleyen ay kartı (grid weight=1)."""
    rol = ay_ozet.get("rol")
    if rol == ROL_BU_AY:
        bg, border, border_w = _BU_AY_BG, _BU_AY_BORDER, 3
    elif rol == ROL_GECEN:
        bg, border, border_w = _PANEL, _GECEN_BORDER, 1
    else:
        bg, border, border_w = _PANEL, _GELECEK_BORDER, 1

    kart = tk.Frame(parent, bg=bg, highlightbackground=border, highlightthickness=border_w)
    parent.columnconfigure(sutun, weight=1, uniform="aylar")
    parent.rowconfigure(0, weight=1)
    kart.grid(row=0, column=sutun, sticky="nsew", padx=3, pady=2)

    baslik_frm = tk.Frame(kart, bg=_NAVY if rol == ROL_BU_AY else bg)
    baslik_frm.pack(fill="x")
    tk.Label(
        baslik_frm,
        text=ay_ozet.get("baslik") or "",
        bg=_NAVY if rol == ROL_BU_AY else bg,
        fg="white" if rol == ROL_BU_AY else _NAVY,
        font=("Segoe UI", 11, "bold"),
    ).pack(side="left", padx=8, pady=6)
    tk.Label(
        baslik_frm,
        text=ay_ozet.get("etiket") or "",
        bg=_YELLOW if rol == ROL_BU_AY else ("#eceff1" if rol == ROL_GECEN else "#e8eaf6"),
        fg=_NAVY,
        font=("Segoe UI", 8, "bold"),
        padx=6,
        pady=2,
    ).pack(side="right", padx=8, pady=6)

    ozet = tk.Frame(kart, bg=bg)
    ozet.pack(fill="x", padx=8, pady=4)
    for etiket, deger in (
        ("Planlanan", ay_ozet.get("toplam")),
        ("Ödenen", ay_ozet.get("odenen")),
        ("Kalan", ay_ozet.get("filtre_kalan", ay_ozet.get("kalan"))),
        ("Gecikmiş", ay_ozet.get("gecikmis")),
    ):
        satir = tk.Frame(ozet, bg=bg)
        satir.pack(fill="x")
        tk.Label(satir, text=etiket, bg=bg, fg="#555", font=("Segoe UI", 8)).pack(side="left")
        tk.Label(
            satir,
            text=_para(deger),
            bg=bg,
            fg="#c0392b" if etiket == "Gecikmiş" and (deger or 0) else _NAVY,
            font=("Segoe UI", 8, "bold"),
        ).pack(side="right")

    tk.Label(
        kart,
        text=(
            f"KK {_para(ay_ozet.get('kredi_karti_toplam'))}  ·  "
            f"Kredi {_para(ay_ozet.get('kredi_taksit_toplam'))}  ·  "
            f"Tekrar {_para(ay_ozet.get('tekrar_eden_toplam'))}  ·  "
            f"Diğer {_para(ay_ozet.get('diger_toplam'))}"
        ),
        bg=bg,
        fg="#666",
        font=("Segoe UI", 7),
        justify="left",
        anchor="w",
    ).pack(fill="x", padx=8, pady=(0, 4))

    # Kaydırmalı ödeme listesi — viewport sabit, içerik taşınca dikey scroll
    liste_dis = tk.Frame(kart, bg=bg)
    liste_dis.pack(fill="both", expand=True, padx=2, pady=(0, 4))
    canvas = tk.Canvas(liste_dis, bg=bg, highlightthickness=0, height=280)
    vsb = ttk.Scrollbar(liste_dis, orient="vertical", command=canvas.yview)
    ic = tk.Frame(canvas, bg=bg)

    def _scrollregion(_event=None):
        canvas.update_idletasks()
        bbox = canvas.bbox("all")
        if bbox:
            canvas.configure(scrollregion=bbox)

    ic.bind("<Configure>", _scrollregion)
    win = canvas.create_window((0, 0), window=ic, anchor="nw")
    canvas.configure(yscrollcommand=vsb.set)

    def _genislik_ayarla(event):
        canvas.itemconfigure(win, width=max(1, event.width))
        wrap = max(120, event.width - 16)
        for child in ic.winfo_children():
            for lbl in child.winfo_children():
                if isinstance(lbl, tk.Label):
                    try:
                        if lbl.cget("justify") == "left" and lbl.cget("anchor") == "w":
                            lbl.configure(wraplength=wrap)
                    except tk.TclError:
                        pass
        _scrollregion()

    canvas.bind("<Configure>", _genislik_ayarla)
    canvas.pack(side="left", fill="both", expand=True)
    vsb.pack(side="right", fill="y")

    satirlar = ay_ozet.get("gorunen_satirlar") or []
    if not satirlar:
        tk.Label(
            ic,
            text="Bu ay için planlanmış ödeme bulunmuyor.\nToplam: 0,00 TL  ·  Ödenen: 0,00 TL  ·  Kalan: 0,00 TL",
            bg=bg,
            fg="#777",
            font=("Segoe UI", 8, "italic"),
            justify="left",
            wraplength=200,
        ).pack(anchor="w", padx=8, pady=10)
    else:
        for s in satirlar:
            _odeme_satiri(ic, s, bg=bg, wrap_px=220, odeme_ac_cb=odeme_ac_cb)

    _liste_tekerlek_bagla(canvas, liste_dis)
    canvas.after_idle(_scrollregion)
    canvas.after(50, _scrollregion)
    canvas.after(50, lambda: _liste_tekerlek_bagla(canvas, ic))

    return kart


def odeme_durumu_sayfasi_goster(app):
    if not (
        yetki_var("odeme_durumu_goruntuleme")
        or yetki_var("finans_goruntuleme")
        or yetki_var("banka_kredi_rapor")
    ):
        messagebox.showwarning("Yetki", "Ödeme durumu raporunu görüntüleme yetkiniz yok.")
        return
    if not oturum.firma_secili:
        messagebox.showwarning("Firma", "Önce aktif firma seçin.")
        return

    app._icerigi_temizle()
    _finans_isaretle(app)
    parent = app.icerik.winfo_toplevel()

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="Aylara Göre Ödeme Durumu", style="Baslik.TLabel").pack(side="left")
    ttk.Button(
        ust, text="← Finans Raporları", command=lambda: finans_raporlar_menusu_goster(app)
    ).pack(side="right")

    ref = OdemeDurumuService.referans_tarih()
    firma = getattr(oturum, "company_name", None) or getattr(oturum, "firma_adi", None) or "—"
    donem = getattr(oturum, "donem_adi", None) or "—"
    ttk.Label(
        app.icerik,
        text=(
            f"Geçen ay + bu ay + gelecek 3 ay  |  Firma: {firma}  |  "
            f"Dönem: {donem}  |  Referans: {ref.strftime('%d.%m.%Y')}  |  "
            f"Öde butonu veya çift tık ile ödeme evrakı"
        ),
    ).pack(anchor="w", pady=(6, 4))

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(0, 4))

    kaynak_var = tk.StringVar(value="Tümü")
    durum_var = tk.StringVar(value="Tümü")
    banka_var = tk.StringVar(value="")
    odenen_var = tk.BooleanVar(value=False)
    sadece_acik_var = tk.BooleanVar(value=True)
    sadece_gecik_var = tk.BooleanVar(value=False)
    min_tutar_var = tk.StringVar(value="")
    max_tutar_var = tk.StringVar(value="")

    ttk.Label(filtre, text="Tür:").pack(side="left")
    ttk.Combobox(
        filtre,
        textvariable=kaynak_var,
        values=("Tümü", "Banka kredisi", "Kredi kartı", "Çek / Senet"),
        state="readonly",
        width=14,
    ).pack(side="left", padx=3)
    ttk.Label(filtre, text="Durum:").pack(side="left", padx=(8, 0))
    ttk.Combobox(
        filtre,
        textvariable=durum_var,
        values=("Tümü", "Planlandı", "Yaklaşıyor", "Bugün", "Gecikmiş", "Kısmen ödendi", "Ödendi"),
        state="readonly",
        width=14,
    ).pack(side="left", padx=3)
    ttk.Label(filtre, text="Banka:").pack(side="left", padx=(8, 0))
    ttk.Entry(filtre, textvariable=banka_var, width=12).pack(side="left", padx=3)
    ttk.Label(filtre, text="Tutar:").pack(side="left", padx=(8, 0))
    ttk.Entry(filtre, textvariable=min_tutar_var, width=8).pack(side="left", padx=2)
    ttk.Label(filtre, text="–").pack(side="left")
    ttk.Entry(filtre, textvariable=max_tutar_var, width=8).pack(side="left", padx=2)
    ttk.Checkbutton(filtre, text="Sadece açık", variable=sadece_acik_var).pack(side="left", padx=4)
    ttk.Checkbutton(filtre, text="Sadece gecikenler", variable=sadece_gecik_var).pack(
        side="left", padx=4
    )
    ttk.Checkbutton(filtre, text="Ödenenleri göster", variable=odenen_var).pack(side="left", padx=4)
    ttk.Button(filtre, text="Yenile", command=lambda: _yenile()).pack(side="left", padx=6)

    kpi_cerceve = ttk.Frame(app.icerik)
    kpi_cerceve.pack(fill="x")

    # 5 ay — masaüstünde yan yana; dar ekranda yatay kaydırma
    ay_dis = tk.Frame(app.icerik, bg=_BG)
    ay_dis.pack(fill="both", expand=True, pady=(4, 0))
    ay_canvas = tk.Canvas(ay_dis, bg=_BG, highlightthickness=0)
    ay_hsb = ttk.Scrollbar(ay_dis, orient="horizontal", command=ay_canvas.xview)
    ay_kap = tk.Frame(ay_canvas, bg=_BG)
    ay_win = ay_canvas.create_window((0, 0), window=ay_kap, anchor="nw")
    ay_canvas.configure(xscrollcommand=ay_hsb.set)

    def _ay_scrollregion(_e=None):
        ay_canvas.configure(scrollregion=ay_canvas.bbox("all"))

    def _ay_canvas_boyut(event):
        # Kartlar en az ~180px; dikey alanı doldur (iç liste kendi scroll'unu kullanır)
        min_w = max(event.width, 5 * 180)
        ay_canvas.itemconfigure(ay_win, width=min_w, height=max(1, event.height))
        _ay_scrollregion()

    ay_kap.bind("<Configure>", _ay_scrollregion)
    ay_canvas.bind("<Configure>", _ay_canvas_boyut)
    ay_canvas.pack(side="top", fill="both", expand=True)
    ay_hsb.pack(side="bottom", fill="x")

    gecmis_frm = ttk.LabelFrame(app.icerik, text="Ödeme Geçmişi (seçili dönemde ödenenler)")
    gecmis_frm.pack(fill="x", pady=(6, 0))

    def _kaynak_set():
        sec = kaynak_var.get()
        if sec == "Banka kredisi":
            return {KAYNAK_KREDI}
        if sec == "Kredi kartı":
            return {KAYNAK_KK}
        if sec == "Çek / Senet":
            return {KAYNAK_CEK}
        return {KAYNAK_KREDI, KAYNAK_KK, KAYNAK_CEK}

    def _durum_set():
        m = {
            "Planlandı": DURUM_PLANLANDI,
            "Yaklaşıyor": DURUM_YAKLASIYOR,
            "Bugün": DURUM_BUGUN,
            "Gecikmiş": DURUM_GECIKMIS,
            "Kısmen ödendi": DURUM_KISMI,
            "Ödendi": DURUM_ODENDI,
        }
        sec = durum_var.get()
        if sec == "Tümü":
            return None
        return {m[sec]} if sec in m else None

    def _odeme_ac(satir: dict):
        """Kaynak türüne göre ödeme / belge penceresi aç."""
        tip = satir.get("source_type") or ""
        sid = satir.get("source_id")

        if tip == KAYNAK_KREDI:
            try:
                from banka_kredi_ui import KrediTaksitOdemePenceresi

                KrediTaksitOdemePenceresi(parent, int(sid), yenile_cb=_yenile)
            except Exception as hata:
                messagebox.showerror("Taksit ödeme", str(hata))
            return

        if tip == KAYNAK_KK:
            try:
                from kk_ekstre_ui import KkEkstreDetayDialog

                KkEkstreDetayDialog(parent, satir, yenile_cb=_yenile)
            except Exception as hata:
                messagebox.showerror("Kredi kartı ekstresi", str(hata))
            return

        if tip == KAYNAK_CEK:
            try:
                from database.cek_senet_service import CekSenetService
                from cek_senet_ui import EvrakDialog

                CekSenetService.schema_hazirla()
                detay = CekSenetService.getir(int(sid))
                if not detay:
                    messagebox.showinfo("Çek / Senet", "Evrak bulunamadı.")
                    return
                EvrakDialog(parent, mod="goruntule", evrak=detay)
            except Exception as hata:
                messagebox.showerror("Çek / Senet", str(hata))
            return

        messagebox.showinfo("Ödeme", "Bu kaynak için ödeme ekranı tanımlı değil.")

    def _yenile():
        for w in kpi_cerceve.winfo_children():
            w.destroy()
        for w in ay_kap.winfo_children():
            w.destroy()
        for w in gecmis_frm.winfo_children():
            w.destroy()
        try:
            from decimal import Decimal, InvalidOperation

            def _parse_tutar(raw: str):
                t = (raw or "").strip().replace(".", "").replace(",", ".")
                if not t:
                    return None
                try:
                    return Decimal(t)
                except (InvalidOperation, ValueError):
                    return None

            rapor = OdemeDurumuService.bes_aylik_rapor(
                kaynaklar=_kaynak_set(),
                odenenleri_dahil=odenen_var.get(),
                sadece_acik=sadece_acik_var.get() and not odenen_var.get(),
                sadece_geciken=sadece_gecik_var.get(),
                durumlar=_durum_set(),
                banka=banka_var.get().strip() or None,
                min_tutar=_parse_tutar(min_tutar_var.get()),
                max_tutar=_parse_tutar(max_tutar_var.get()),
            )
        except Exception as hata:
            messagebox.showerror("Hata", str(hata))
            return

        _kpi_serit(kpi_cerceve, rapor)

        aylar = rapor.get("aylar") or []
        for i, ay in enumerate(aylar):
            _ay_karti(ay_kap, ay, odeme_ac_cb=_odeme_ac, sutun=i)

        odenenler = []
        for ay in aylar:
            odenenler.extend(ay.get("odenen_satirlar") or [])
        odenenler.sort(key=lambda s: s.get("due_date") or date.min)
        tv = ttk.Treeview(
            gecmis_frm,
            columns=("tarih", "aciklama", "tur", "banka", "tutar", "belge"),
            show="headings",
            height=4,
        )
        for k, b, w in (
            ("tarih", "Tarih", 90),
            ("aciklama", "Açıklama", 260),
            ("tur", "Tür", 110),
            ("banka", "Banka", 120),
            ("tutar", "Tutar", 100),
            ("belge", "Belge", 110),
        ):
            tv.heading(k, text=b)
            tv.column(k, width=w)
        tv.pack(fill="x", padx=4, pady=4)
        if not odenenler:
            tv.insert("", "end", values=("—", "Bu dönemde ödenen kayıt yok", "", "", "", ""))
        else:
            for s in odenenler[:200]:
                tv.insert(
                    "",
                    "end",
                    values=(
                        _tarih(s.get("due_date")),
                        s.get("aciklama") or "",
                        s.get("kaynak_etiket") or "",
                        s.get("banka_adi") or "",
                        _para(s.get("tl_tutar")),
                        s.get("belge_no") or "",
                    ),
                )

    _yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: odeme_durumu_sayfasi_goster(app))
