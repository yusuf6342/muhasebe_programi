"""Özet Tablolar → Gelir Tablosu — otomatik yenileme, karşılaştırma, gider grubu ağacı."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from tkinter import messagebox, ttk
import tkinter as tk

from database.rapor_service import MALIYET_YONTEMLERI_RAPOR, RaporService
from database.gider_rapor_service import onceki_es_donem
from ui_takvim import takvim_butonu


def _para(tutar) -> str:
    if tutar is None:
        return "—"
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _yuz(v) -> str:
    if v is None:
        return "—"
    return f"%{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih_oku(entry, *, zorunlu: bool = True) -> date | None:
    metin = (entry.get() or "").strip()
    if not metin:
        if zorunlu:
            raise ValueError("Tarih zorunludur.")
        return None
    return datetime.strptime(metin, "%d.%m.%Y").date()


def gelir_tablosu_sayfasi_goster(app):
    from ozet_tablolar_ui import _ozet_tablolar_menu_isaretle, ozet_tablolar_menusu_goster

    app._icerigi_temizle()
    _ozet_tablolar_menu_isaretle(app)

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="GELİR TABLOSU", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Özet Tablolar Menüsü", command=lambda: ozet_tablolar_menusu_goster(app)).pack(
        side="right"
    )

    ttk.Label(
        app.icerik,
        text=(
            "Net satış − SMM = brüt kâr; faaliyet/finansman gider gruplarıyla vergi öncesi yönetim sonucu. "
            "Tarih veya maliyet değişince otomatik yenilenir."
        ),
    ).pack(anchor="w", pady=(8, 4))

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(4, 2))

    ttk.Label(filtre, text="A başlangıç:").pack(side="left")
    b_c = ttk.Frame(filtre)
    b_c.pack(side="left")
    baslangic = ttk.Entry(b_c, width=11)
    baslangic.pack(side="left")
    bugun = date.today()
    baslangic.insert(0, date(bugun.year, 1, 1).strftime("%d.%m.%Y"))
    takvim_butonu(b_c, baslangic)

    ttk.Label(filtre, text="A bitiş:").pack(side="left", padx=(8, 0))
    e_c = ttk.Frame(filtre)
    e_c.pack(side="left")
    bitis = ttk.Entry(e_c, width=11)
    bitis.pack(side="left")
    bitis.insert(0, bugun.strftime("%d.%m.%Y"))
    takvim_butonu(e_c, bitis)

    karsilastir_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(filtre, text="Karşılaştır", variable=karsilastir_var).pack(side="left", padx=(12, 4))

    ttk.Label(filtre, text="B başlangıç:").pack(side="left")
    bb_c = ttk.Frame(filtre)
    bb_c.pack(side="left")
    b_bas = ttk.Entry(bb_c, width=11)
    b_bas.pack(side="left")
    takvim_butonu(bb_c, b_bas)

    ttk.Label(filtre, text="B bitiş:").pack(side="left", padx=(8, 0))
    be_c = ttk.Frame(filtre)
    be_c.pack(side="left")
    b_bit = ttk.Entry(be_c, width=11)
    b_bit.pack(side="left")
    takvim_butonu(be_c, b_bit)

    def _onceki_es():
        try:
            a, z = onceki_es_donem(_tarih_oku(baslangic), _tarih_oku(bitis))
            b_bas.delete(0, "end")
            b_bas.insert(0, a.strftime("%d.%m.%Y"))
            b_bit.delete(0, "end")
            b_bit.insert(0, z.strftime("%d.%m.%Y"))
            karsilastir_var.set(True)
            _zamanla_yenile()
        except Exception as exc:
            messagebox.showwarning("Tarih", str(exc), parent=app)

    ttk.Button(filtre, text="Önceki eş dönem", command=_onceki_es).pack(side="left", padx=6)

    filtre2 = ttk.Frame(app.icerik)
    filtre2.pack(fill="x", pady=(2, 4))
    ttk.Label(filtre2, text="Kısayol:").pack(side="left")

    def _kisayol(mod: str):
        t = date.today()
        if mod == "bu_ay":
            b, e = date(t.year, t.month, 1), t
        elif mod == "onceki_ay":
            ilk = date(t.year, t.month, 1) - timedelta(days=1)
            b, e = date(ilk.year, ilk.month, 1), ilk
        elif mod == "yilbasi":
            b, e = date(t.year, 1, 1), t
        else:
            return
        baslangic.delete(0, "end")
        baslangic.insert(0, b.strftime("%d.%m.%Y"))
        bitis.delete(0, "end")
        bitis.insert(0, e.strftime("%d.%m.%Y"))
        _zamanla_yenile()

    for metin, mod in (("Bu ay", "bu_ay"), ("Önceki ay", "onceki_ay"), ("Yılbaşından bugüne", "yilbasi")):
        ttk.Button(filtre2, text=metin, command=lambda m=mod: _kisayol(m)).pack(side="left", padx=2)

    ttk.Label(filtre2, text="Stok maliyet:").pack(side="left", padx=(12, 0))
    yontem = ttk.Combobox(filtre2, values=list(MALIYET_YONTEMLERI_RAPOR), state="readonly", width=28)
    yontem.set("FIFO")
    yontem.pack(side="left", padx=6)

    ttk.Label(filtre2, text="Kalem ara:").pack(side="left", padx=(12, 0))
    kalem_ara = ttk.Entry(filtre2, width=16)
    kalem_ara.pack(side="left", padx=4)
    kalem_ara_btn = ttk.Frame(filtre2)
    kalem_ara_btn.pack(side="left")

    durum_etiket = ttk.Label(app.icerik, text="", font=("Segoe UI", 9))
    durum_etiket.pack(anchor="w")
    ozet_etiket = ttk.Label(app.icerik, text="", font=("Segoe UI", 10, "bold"))
    ozet_etiket.pack(anchor="w", pady=(0, 4))
    gorunum_ozet = ttk.Label(app.icerik, text="", font=("Segoe UI", 9), foreground="#1a237e")
    gorunum_ozet.pack(anchor="w")

    govde = ttk.Frame(app.icerik)
    govde.pack(fill="both", expand=True, pady=(4, 0))
    govde.columnconfigure(0, weight=1)
    govde.rowconfigure(0, weight=1)

    kolonlar = ("kalem", "b_tutar", "a_tutar", "fark", "yuzde")
    tablo = ttk.Treeview(govde, columns=kolonlar, show="tree headings", selectmode="browse")
    tablo.heading("#0", text="")
    tablo.column("#0", width=28, minwidth=24, stretch=False)
    tablo.heading("kalem", text="Gelir / Gider kalemi", anchor="w")
    tablo.heading("b_tutar", text="B tutarı", anchor="e")
    tablo.heading("a_tutar", text="A tutarı", anchor="e")
    tablo.heading("fark", text="Fark (A−B)", anchor="e")
    tablo.heading("yuzde", text="Değişim %", anchor="e")
    for k, w in (("kalem", 360), ("b_tutar", 120), ("a_tutar", 120), ("fark", 110), ("yuzde", 90)):
        tablo.column(k, width=w, anchor="e" if k != "kalem" else "w", stretch=(k == "kalem"))
    dikey = ttk.Scrollbar(govde, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=dikey.set)
    tablo.grid(row=0, column=0, sticky="nsew")
    dikey.grid(row=0, column=1, sticky="ns")

    stil = ttk.Style()
    stil.configure("GelirTablo.Treeview", font=("Segoe UI", 9), rowheight=24)
    stil.configure("GelirTablo.Treeview.Heading", font=("Segoe UI", 9, "bold"))
    tablo.configure(style="GelirTablo.Treeview")
    tablo.tag_configure("baslik", font=("Segoe UI", 9, "bold"), background="#d9e2ec")
    tablo.tag_configure("ara_toplam", font=("Segoe UI", 9, "bold"), background="#eef2f6")
    tablo.tag_configure("toplam", font=("Segoe UI", 10, "bold"), background="#c5d4e8")
    tablo.tag_configure("eski", foreground="#888888")

    not_etiket = ttk.Label(app.icerik, text="", wraplength=960, foreground="#555555")
    not_etiket.pack(anchor="w", pady=(6, 0))

    durum = {"istek": 0, "timer": None, "son_basarili": None, "kapali": False}

    def _kalem_ara_uygula(_e=None):
        veri = durum.get("son_basarili")
        if not veri:
            return
        kf = (kalem_ara.get() or "").strip()
        _tabloyu_doldur(
            tablo,
            veri,
            karsilastir=bool(veri.get("karsilastirma")),
            kalem_filtre=kf,
        )
        if kf:
            gorunum_ozet.configure(
                text=f"Görüntü filtresi: «{kf}» — ara toplam / net sonuç satırları korunur"
            )
        else:
            gorunum_ozet.configure(text="")

    def _kalem_ara_temizle():
        kalem_ara.delete(0, "end")
        _kalem_ara_uygula()

    ttk.Button(kalem_ara_btn, text="Ara", command=_kalem_ara_uygula).pack(side="left", padx=2)
    ttk.Button(kalem_ara_btn, text="Temizle", command=_kalem_ara_temizle).pack(side="left", padx=2)
    kalem_ara.bind("<Return>", _kalem_ara_uygula)

    def _sutun_gorunum():
        if karsilastir_var.get():
            tablo.heading("a_tutar", text="A tutarı")
            tablo.heading("b_tutar", text="B tutarı")
            for k in ("b_tutar", "fark", "yuzde"):
                tablo.column(k, width=110 if k != "yuzde" else 90)
        else:
            tablo.heading("a_tutar", text="Tutar")
            for k in ("b_tutar", "fark", "yuzde"):
                tablo.column(k, width=0, minwidth=0, stretch=False)

    def _istek_param():
        b = _tarih_oku(baslangic, zorunlu=True)
        e = _tarih_oku(bitis, zorunlu=True)
        if b > e:
            raise ValueError("A başlangıcı bitişten sonra olamaz.")
        bb = be = None
        if karsilastir_var.get():
            bb = _tarih_oku(b_bas, zorunlu=True)
            be = _tarih_oku(b_bit, zorunlu=True)
            if bb > be:
                raise ValueError("B başlangıcı bitişten sonra olamaz.")
        return b, e, bb, be, (yontem.get() or "FIFO").strip()

    def doldur():
        if durum["kapali"] or not app.winfo_exists():
            return
        durum["istek"] += 1
        istek = durum["istek"]
        try:
            b, e, bb, be, yontem_adi = _istek_param()
        except ValueError as exc:
            durum_etiket.configure(text=f"Hata: {exc}")
            return
        _sutun_gorunum()
        durum_etiket.configure(text="Hesaplanıyor…")
        if durum["son_basarili"]:
            # Eski sonuç soluk kalabilir; yeni sonuç gelince değişir
            pass

        def _yukle():
            return RaporService.gelir_tablosu(
                baslangic=b,
                bitis=e,
                maliyet_yontemi=yontem_adi,
                karsilastirma_baslangic=bb,
                karsilastirma_bitis=be,
            )

        def _ok(veri):
            if istek != durum["istek"] or durum["kapali"] or not app.winfo_exists():
                return
            durum["son_basarili"] = veri
            _tabloyu_doldur(
                tablo,
                veri,
                karsilastir=bool(veri.get("karsilastirma")),
                kalem_filtre=(kalem_ara.get() or "").strip(),
            )
            o = veri["ozet"]
            k = o.get("yonetim_sonucu", o.get("net_kar"))
            # Özet her zaman servis toplamı — görünür kalem satırlarından yeniden hesaplanmaz
            ozet_etiket.configure(
                text=(
                    f"A {veri['baslangic'].strftime('%d.%m.%Y')}–{veri['bitis'].strftime('%d.%m.%Y')}"
                    + (
                        f"  |  B {veri['karsilastirma']['baslangic'].strftime('%d.%m.%Y')}–"
                        f"{veri['karsilastirma']['bitis'].strftime('%d.%m.%Y')}"
                        if veri.get("karsilastirma")
                        else ""
                    )
                    + f"  |  {veri['maliyet_yontemi']}  |  "
                    f"Net satış {_para(o['net_satislar'])}  |  SMM {_para(o['smm'])}  |  "
                    f"Brüt kâr {_para(o['brut_kar'])}  |  "
                    f"Vergi öncesi yönetim sonucu {_para(k)}"
                )
            )
            kf = (kalem_ara.get() or "").strip()
            if kf:
                gorunum_ozet.configure(
                    text=f"Görüntü filtresi: «{kf}» — ara toplam / net sonuç satırları korunur"
                )
            else:
                gorunum_ozet.configure(text="")
            durum_etiket.configure(
                text=f"Güncel · {veri.get('hesap_zamani', datetime.now()).strftime('%H:%M:%S')}"
            )
            not_etiket.configure(text=veri.get("notlar") or "")

        def _err(exc):
            if istek != durum["istek"] or not app.winfo_exists():
                return
            durum_etiket.configure(text="Güncel değil — sorgu hatası")
            messagebox.showerror("Gelir Tablosu", str(exc), parent=app)

        from ui_bg import arka_planda

        arka_planda(app, _yukle, on_ok=_ok, on_err=_err)

    def _zamanla_yenile(_e=None):
        if durum["timer"] is not None:
            try:
                app.after_cancel(durum["timer"])
            except Exception:
                pass
        durum["timer"] = app.after(400, doldur)

    def _focus_yenile(_e=None):
        # Tamamlanmış tarihlerde yenile
        try:
            _istek_param()
        except ValueError:
            return
        _zamanla_yenile()

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=8)
    ttk.Button(alt, text="Yenile", command=doldur).pack(side="right")

    for w in (baslangic, bitis, b_bas, b_bit):
        w.bind("<FocusOut>", _focus_yenile)
        w.bind("<Return>", _focus_yenile)
    yontem.bind("<<ComboboxSelected>>", lambda _e: _zamanla_yenile())
    karsilastir_var.trace_add("write", lambda *_a: _zamanla_yenile())

    def _surum_kontrol():
        if durum["kapali"] or not app.winfo_exists():
            return
        # Hafif yenileme — hareketli «bu ay / yılbaşı» gün değişimi
        try:
            b = _tarih_oku(baslangic)
            e = _tarih_oku(bitis)
            if e == date.today() - timedelta(days=1) or b.day == 1:
                pass
        except Exception:
            pass
        app.after(15000, _surum_kontrol)

    def _kapanis(_e=None):
        durum["kapali"] = True

    app.bind("<Destroy>", _kapanis, add="+")
    _sutun_gorunum()
    doldur()
    app.after(15000, _surum_kontrol)

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: gelir_tablosu_sayfasi_goster(app))


def _degisim_metin(a: Decimal, b: Decimal | None) -> str:
    if b is None:
        return ""
    if b > 0:
        return _yuz(((a - b) / b) * Decimal("100"))
    if b == 0 and a > 0:
        return "Yeni tutar"
    if b == 0 and a == 0:
        return "—"
    if b == 0 and a < 0:
        return "Yeni negatif"
    return "Uygun değil"


def _tabloyu_doldur(tablo: ttk.Treeview, veri: dict, *, karsilastir: bool, kalem_filtre: str = ""):
    from database.turkce_normalize import turkce_normalize

    for item in tablo.get_children():
        tablo.delete(item)
    satirlar = veri.get("satirlar") or []
    parent_stack: list[str] = []
    ara = turkce_normalize((kalem_filtre or "").strip())
    for s in satirlar:
        seviye = s.get("seviye") or "kalem"
        etiket = s.get("etiket") or ""
        # DOC5: formül / ara toplam / başlık her zaman; yalnız detay kalemleri görüntüde süzülür
        if ara and seviye in ("kalem", "alt", "grup") and ara not in turkce_normalize(etiket):
            if seviye == "grup":
                # Grup başlığı eşleşmezse altları da atlanır; ara_toplam/toplam aşağıda kalır
                continue
            if seviye in ("kalem", "alt"):
                continue
        a = Decimal(str(s.get("tutar") or 0))
        b = s.get("tutar_b")
        b_dec = Decimal(str(b)) if b is not None else None
        fark = (a - b_dec) if b_dec is not None else None
        if seviye == "baslik":
            vals = (etiket, "", "", "", "")
            tags = ("baslik",)
            iid = tablo.insert("", "end", text="", values=vals, tags=tags, open=True)
            parent_stack = [iid]
            continue
        a_txt = _para(a)
        b_txt = _para(b_dec) if karsilastir and b_dec is not None else ("" if karsilastir else "")
        fark_txt = _para(fark) if karsilastir and fark is not None else ""
        yuz_txt = _degisim_metin(a, b_dec) if karsilastir else ""
        if not karsilastir:
            b_txt = fark_txt = yuz_txt = ""
            # tek dönem: A sütununda tutar
        vals = (etiket, b_txt, a_txt, fark_txt, yuz_txt)
        if seviye == "toplam":
            tags = ("toplam",)
            parent = ""
        elif seviye == "ara_toplam":
            tags = ("ara_toplam",)
            parent = ""
        elif seviye == "grup":
            tags = ("ara_toplam",)
            parent = parent_stack[0] if parent_stack else ""
            iid = tablo.insert(parent, "end", text="▸", values=vals, tags=tags, open=bool(ara))
            # alt satırlar için parent
            s["_iid"] = iid
            continue
        elif seviye == "alt":
            tags = ("kalem",)
            parent = s.get("_parent_iid") or (parent_stack[-1] if parent_stack else "")
        else:
            tags = ("kalem",)
            parent = s.get("_parent_iid") or ""
        tablo.insert(parent or "", "end", text="", values=vals, tags=tags)
