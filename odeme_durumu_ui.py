"""FİNANS → RAPORLAR → Aylara Göre Ödeme Durumu."""

from __future__ import annotations

from datetime import date, datetime
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
)
from database.session_manager import oturum

_NAVY = "#0b1f3a"
_YELLOW = "#e8b923"
_BG = "#eef1f5"
_PANEL = "#ffffff"

_DURUM_RENK = {
    DURUM_PLANLANDI: "#2e86c1",
    DURUM_YAKLASIYOR: "#c9a227",
    DURUM_BUGUN: "#e67e22",
    DURUM_GECIKMIS: "#c0392b",
    DURUM_KISMI: "#d35400",
    DURUM_ODENDI: "#1e8449",
    "IPTAL": "#566573",
    "TAHMINI": "#7d3c98",
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
    return f"{Decimal(str(tutar or 0)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


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


def _kpi_serit(parent, kpi: dict):
    wrap = tk.Frame(parent, bg=_BG)
    wrap.pack(fill="x", pady=(6, 10))
    kartlar = (
        ("Bu ay toplam", kpi.get("bu_ay_toplam")),
        ("Bu ay kalan", kpi.get("bu_ay_kalan")),
        ("Gecikmiş", kpi.get("gecikmis")),
        ("Gelecek 7 gün", kpi.get("gelecek_7_gun")),
        ("Gelecek 30 gün", kpi.get("gelecek_30_gun")),
        ("Tahmini", kpi.get("tahmini")),
    )
    for i, (baslik, deger) in enumerate(kartlar):
        kutu = tk.Frame(wrap, bg=_PANEL, highlightbackground="#cfd6e0", highlightthickness=1)
        kutu.grid(row=0, column=i, padx=3, sticky="nsew")
        wrap.columnconfigure(i, weight=1)
        tk.Label(kutu, text=baslik, bg=_PANEL, fg="#445", font=("Segoe UI", 8)).pack(
            anchor="w", padx=8, pady=(6, 0)
        )
        renk = _NAVY if baslik != "Gecikmiş" else "#c0392b"
        tk.Label(
            kutu, text=_para(deger), bg=_PANEL, fg=renk, font=("Segoe UI", 11, "bold")
        ).pack(anchor="w", padx=8, pady=(2, 8))


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

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="Aylara Göre Ödeme Durumu", style="Baslik.TLabel").pack(side="left")
    ttk.Button(
        ust, text="← Finans Raporları", command=lambda: finans_raporlar_menusu_goster(app)
    ).pack(side="right")

    firma = getattr(oturum, "company_name", None) or getattr(oturum, "firma_adi", None) or "—"
    donem = getattr(oturum, "donem_adi", None) or "—"
    ttk.Label(
        app.icerik,
        text=f"Yaklaşan, geciken ve tamamlanan ödemeleri aylık olarak yönetin  |  "
        f"Firma: {firma}  |  Dönem: {donem}  |  Yenileme: {date.today().strftime('%d.%m.%Y')}",
    ).pack(anchor="w", pady=(6, 4))

    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(0, 4))
    kaynak_var = tk.StringVar(value="Tümü")
    ttk.Label(filtre, text="Kaynak:").pack(side="left")
    ttk.Combobox(
        filtre,
        textvariable=kaynak_var,
        values=("Tümü", "Banka kredisi", "Kredi kartı", "Çek / Senet"),
        state="readonly",
        width=16,
    ).pack(side="left", padx=4)
    odenen_var = tk.BooleanVar(value=False)
    ttk.Checkbutton(filtre, text="Ödenenleri göster", variable=odenen_var).pack(side="left", padx=8)
    ttk.Button(filtre, text="Yenile", command=lambda: _yenile()).pack(side="left", padx=4)
    ttk.Button(filtre, text="Bugün", command=lambda: _bu_aya_git()).pack(side="left", padx=2)

    kpi_cerceve = ttk.Frame(app.icerik)
    kpi_cerceve.pack(fill="x")

    notebook = ttk.Notebook(app.icerik)
    notebook.pack(fill="both", expand=True, pady=(4, 0))

    def _kaynak_filtre():
        sec = kaynak_var.get()
        if sec == "Banka kredisi":
            return {KAYNAK_KREDI}
        if sec == "Kredi kartı":
            return {KAYNAK_KK}
        if sec == "Çek / Senet":
            return {KAYNAK_CEK}
        return {KAYNAK_KREDI, KAYNAK_KK, KAYNAK_CEK}

    def _cift_tik(iid, tablo):
        try:
            tip, sid = str(iid).split(":", 1)
        except ValueError:
            return
        if tip == KAYNAK_KREDI:
            # sid = taksit_id — kredi_id satırda
            degerler = tablo.item(iid, "values")
            # kredi_id tree tag'inde saklanıyor
            tags = tablo.item(iid, "tags")
            kredi_id = None
            for tg in tags:
                if str(tg).startswith("kid:"):
                    try:
                        kredi_id = int(str(tg).split(":")[1])
                    except ValueError:
                        pass
            if kredi_id:
                from banka_kredi_ui import KrediDetayPenceresi

                KrediDetayPenceresi(
                    app.icerik.winfo_toplevel(), kredi_id, yenile_cb=_yenile
                )
            else:
                messagebox.showinfo("Kredi", f"Taksit #{sid} — kredi kartından detay açın.")
        elif tip == KAYNAK_KK:
            messagebox.showinfo(
                "Kredi kartı",
                "Kart taksiti ödemesi Banka İşlemleri → Kredi Kartı ile Ödeme üzerinden yönetilir.",
            )
        elif tip == KAYNAK_CEK:
            messagebox.showinfo(
                "Çek / Senet",
                "Evrak detayı için FİNANS → Çek / Senet İşlemleri ekranını kullanın.",
            )

    def _tablo_doldur(parent, satirlar):
        for w in parent.winfo_children():
            w.destroy()
        kolonlar = (
            ("vade", "Vade / Ödeme", 100),
            ("kalan_gun", "Kalan Gün", 70),
            ("kaynak", "Kaynak", 110),
            ("aciklama", "Açıklama", 240),
            ("banka", "Banka / Kart", 120),
            ("belge", "Belge", 100),
            ("toplam", "Toplam", 90),
            ("odenen", "Ödenen", 80),
            ("kalan", "Kalan", 90),
            ("durum", "Durum", 100),
            ("kesin", "Kesinlik", 70),
        )
        tv = ttk.Treeview(parent, columns=[k for k, _, _ in kolonlar], show="headings", height=14)
        sb = ttk.Scrollbar(parent, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for k, b, w in kolonlar:
            tv.heading(k, text=b)
            ank = "e" if k in ("toplam", "odenen", "kalan", "kalan_gun") else "w"
            tv.column(k, width=w, anchor=ank)
        for kod, renk in _DURUM_RENK.items():
            tv.tag_configure(kod, foreground=renk)

        bugun = date.today()
        if not satirlar:
            tv.insert("", "end", values=("—",) * 10 + ("Kayıt yok",))
            return tv

        for s in satirlar:
            vade = s.get("due_date")
            kalan_gun = (vade - bugun).days if vade else ""
            durum = s.get("durum") or DURUM_PLANLANDI
            iid = f"{s.get('source_type')}:{s.get('source_id')}"
            tags = [durum]
            if s.get("kredi_id"):
                tags.append(f"kid:{s['kredi_id']}")
            tv.insert(
                "",
                "end",
                iid=iid,
                values=(
                    _tarih(vade),
                    kalan_gun,
                    s.get("kaynak_etiket") or "",
                    s.get("aciklama") or "",
                    s.get("banka_adi") or "",
                    s.get("belge_no") or "",
                    _para(s.get("tl_tutar")),
                    _para(s.get("odenen")),
                    _para(s.get("kalan")),
                    _DURUM_ETIKET.get(durum, durum),
                    s.get("certainty") or "KESIN",
                ),
                tags=tuple(tags),
            )
        tv.bind("<Double-1>", lambda e, tablo=tv: _cift_tik(tablo.selection()[0], tablo) if tablo.selection() else None)
        return tv

    def _yenile():
        for w in kpi_cerceve.winfo_children():
            w.destroy()
        for w in notebook.winfo_children():
            w.destroy()
        try:
            kpi = OdemeDurumuService.kpi(ay_sayisi=6)
        except Exception as hata:
            messagebox.showerror("Hata", str(hata))
            return
        _kpi_serit(kpi_cerceve, kpi)

        kaynaklar = _kaynak_filtre()
        odenen = odenen_var.get()
        bugun = date.today()
        # Gecikmişler ayrı sekme
        try:
            tum_acik = OdemeDurumuService.tum_yukumlulukler(
                kaynaklar=kaynaklar,
                odenenleri_dahil=odenen,
                sadece_acik=not odenen,
            )
        except Exception as hata:
            messagebox.showerror("Hata", str(hata))
            return

        gecikenler = [s for s in tum_acik if s.get("durum") == DURUM_GECIKMIS]
        f_g = ttk.Frame(notebook)
        notebook.add(f_g, text=f"Gecikmiş ({len(gecikenler)})")
        _tablo_doldur(f_g, gecikenler)

        for y, a in OdemeDurumuService.ay_listesi(ay_sayisi=6):
            bas = date(y, a, 1)
            son = date(y, a, __import__("calendar").monthrange(y, a)[1])
            satirlar = [
                s for s in tum_acik
                if s.get("due_date") and bas <= s["due_date"] <= son
            ]
            ozet = OdemeDurumuService.ay_ozeti(y, a, satirlar)
            etiket = ozet["etiket"]
            if y == bugun.year and a == bugun.month:
                etiket = f"● {etiket}"
            f = ttk.Frame(notebook)
            notebook.add(f, text=f"{etiket}  {_para(ozet['kalan'])}")
            ust_ay = ttk.Frame(f)
            ust_ay.pack(fill="x", pady=4)
            ttk.Label(
                ust_ay,
                text=(
                    f"Toplam: {_para(ozet['toplam'])}  |  "
                    f"Kalan: {_para(ozet['kalan'])}  |  "
                    f"Gecikmiş: {_para(ozet['gecikmis'])}  |  "
                    f"Yaklaşan: {_para(ozet['yaklasan'])}  |  "
                    f"Adet: {ozet['adet']}"
                ),
                font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w")
            _tablo_doldur(f, satirlar)

        # İlk sekme: içinde bulunulan ay (gecikmişten sonra index 1+)
        # notebook tabs: 0=gecikmiş, 1=bu ay ...
        try:
            notebook.select(1)
        except Exception:
            pass

    def _bu_aya_git():
        _yenile()
        try:
            notebook.select(1)
        except Exception:
            pass

    _yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: odeme_durumu_sayfasi_goster(app))
