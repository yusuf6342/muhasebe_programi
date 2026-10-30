"""Proje Takip — liste, kart, ayarlar (MVP)."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, ttk

from database.proje_service import ProjeService
from database.session_manager import oturum


def proje_hub_goster(app) -> None:
    app._icerigi_temizle()
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk:
        kabuk.menu_secili_guncelle("proje_takip")
    ttk.Label(app.icerik, text="PROJE TAKİP", style="Baslik.TLabel").pack(
        anchor="w", padx=20, pady=(16, 0)
    )
    ttk.Label(
        app.icerik,
        text="Proje bazında gelir, maliyet ve belge bağlantısı — ikinci muhasebe defteri değil.",
        style="AnaPanelMuted.TLabel",
        wraplength=720,
    ).pack(anchor="w", padx=20, pady=(8, 0))
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", padx=20, pady=(20, 0))
    alt.columnconfigure(0, weight=1, minsize=420)
    for i, (baslik, komut) in enumerate(
        (
            ("YENİ PROJE", lambda: proje_yeni_dialog(app)),
            ("PROJE LİSTESİ", lambda: proje_liste_goster(app)),
            ("PROJE HAREKETLERİ", lambda: proje_hareketler_goster(app)),
            ("RAPORLAR", lambda: proje_rapor_goster(app)),
            ("AYARLAR", lambda: proje_ayarlar_goster(app)),
        )
    ):
        app._alt_menu_dugme(alt, baslik, komut, row=i, column=0, sticky="ew", pady=4)


def proje_liste_goster(app) -> None:
    ProjeService.ensure_schema()
    app._icerigi_temizle()
    ttk.Label(app.icerik, text="PROJE LİSTESİ", style="Baslik.TLabel").pack(
        anchor="w", padx=20, pady=(16, 0)
    )
    ttk.Button(app.icerik, text="← Proje Takip", command=lambda: proje_hub_goster(app)).pack(
        anchor="w", padx=20, pady=(8, 8)
    )
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x", padx=20)
    arama = ttk.Entry(ust, width=28)
    arama.pack(side="left")
    tablo = ttk.Treeview(
        app.icerik,
        columns=("kod", "ad", "tur", "durum", "pb", "gelir", "maliyet"),
        show="headings",
        height=16,
        selectmode="browse",
    )
    for k, b, w in (
        ("kod", "Kod", 120),
        ("ad", "Ad", 220),
        ("tur", "Tür", 120),
        ("durum", "Durum", 90),
        ("pb", "PB", 50),
        ("gelir", "Hedef Gelir", 100),
        ("maliyet", "Hedef Maliyet", 110),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="center" if k != "ad" else "w")
    tablo.pack(fill="both", expand=True, padx=20, pady=8)

    def yenile():
        for i in tablo.get_children():
            tablo.delete(i)
        for p in ProjeService.listele(arama=arama.get().strip() or None):
            tablo.insert(
                "",
                "end",
                iid=str(p["id"]),
                values=(
                    p["kod"],
                    p["ad"],
                    p.get("tur") or "",
                    p["durum"],
                    p["rapor_pb"],
                    p["hedef_gelir"],
                    p["hedef_maliyet"],
                ),
            )

    def ac_kart():
        s = tablo.selection()
        if not s:
            return
        proje_kart_goster(app, int(s[0]))

    ttk.Button(ust, text="Ara", command=yenile).pack(side="left", padx=6)
    ttk.Button(ust, text="Yeni", command=lambda: proje_yeni_dialog(app, yenile)).pack(side="left")
    ttk.Button(ust, text="Aç", command=ac_kart).pack(side="left", padx=6)
    tablo.bind("<Double-1>", lambda _e: ac_kart())
    yenile()


def proje_yeni_dialog(app, sonra=None) -> None:
    dlg = tk.Toplevel(app)
    dlg.title("Yeni Proje")
    dlg.transient(app)
    dlg.grab_set()
    dlg.geometry("480x420")
    frm = ttk.Frame(dlg, padding=16)
    frm.pack(fill="both", expand=True)
    alanlar = {}
    for i, (etiket, key, gen) in enumerate(
        (
            ("Ad *", "ad", 36),
            ("Kod (boş=otomatik)", "kod", 20),
            ("Tür", "tur", 24),
            ("Sorumlu", "sorumlu", 24),
            ("Hedef gelir (KDV hariç)", "hedef_gelir", 16),
            ("Hedef maliyet (KDV hariç)", "hedef_maliyet", 16),
            ("Rapor PB", "rapor_pb", 6),
        )
    ):
        ttk.Label(frm, text=etiket).grid(row=i, column=0, sticky="w", pady=4)
        e = ttk.Entry(frm, width=gen)
        e.grid(row=i, column=1, sticky="w", pady=4)
        alanlar[key] = e
    alanlar["rapor_pb"].insert(0, "TRY")
    tur_cb = ttk.Combobox(frm, values=list(ProjeService.ornek_turler()), width=22)
    tur_cb.grid(row=2, column=1, sticky="w")
    alanlar["tur"] = tur_cb

    def kaydet():
        try:
            p = ProjeService.olustur(
                alanlar["ad"].get(),
                kod=alanlar["kod"].get().strip() or None,
                tur=alanlar["tur"].get().strip() or None,
                sorumlu=alanlar["sorumlu"].get().strip() or None,
                hedef_gelir=alanlar["hedef_gelir"].get() or 0,
                hedef_maliyet=alanlar["hedef_maliyet"].get() or 0,
                rapor_pb=alanlar["rapor_pb"].get() or "TRY",
            )
            messagebox.showinfo("Proje", f"Oluşturuldu: {p['kod']}", parent=dlg)
            dlg.destroy()
            if sonra:
                sonra()
            else:
                proje_kart_goster(app, p["id"])
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Proje", str(exc), parent=dlg)

    ttk.Button(frm, text="Kaydet", command=kaydet).grid(row=20, column=1, sticky="e", pady=12)


def proje_kart_goster(app, proje_id: int) -> None:
    ProjeService.ensure_schema()
    p = ProjeService.getir(proje_id)
    if not p:
        messagebox.showerror("Proje", "Bulunamadı.", parent=app)
        return
    ozet = ProjeService.finansal_ozet(proje_id)
    app._icerigi_temizle()
    ttk.Label(
        app.icerik, text=f"{p['kod']} — {p['ad']}", style="Baslik.TLabel"
    ).pack(anchor="w", padx=20, pady=(16, 0))
    ttk.Button(app.icerik, text="← Liste", command=lambda: proje_liste_goster(app)).pack(
        anchor="w", padx=20, pady=(8, 8)
    )
    nb = ttk.Notebook(app.icerik)
    nb.pack(fill="both", expand=True, padx=20, pady=8)

    def sekme(ad: str) -> ttk.Frame:
        f = ttk.Frame(nb, padding=12)
        nb.add(f, text=ad)
        return f

    g = sekme("Genel Bilgiler")
    ttk.Label(
        g,
        text=(
            f"Durum: {p['durum']}  |  PB: {p['rapor_pb']}  |  Tür: {p.get('tur') or '—'}\n"
            f"Sorumlu: {p.get('sorumlu') or '—'}\n"
            f"Başlangıç: {_t(p.get('baslangic'))}  Plan bitiş: {_t(p.get('plan_bitis'))}\n"
            f"{p.get('aciklama') or ''}"
        ),
        justify="left",
    ).pack(anchor="w")

    f = sekme("Finansal Özet")
    ttk.Label(
        f,
        text=(
            f"Hedef gelir: {ozet['hedef_gelir']}  Hedef maliyet: {ozet['hedef_maliyet']}\n"
            f"Hedef kâr: {ozet['hedef_kar']}  (marj hedef gelir/maliyetten türetilir)\n"
            f"Bağlı belge: {ozet['bagli_belge']}  Pay toplam: {ozet['bagli_pay_toplam']}\n"
            f"{ozet['not']}"
        ),
        justify="left",
        wraplength=640,
    ).pack(anchor="w")

    bel = sekme("Belgeler")
    ttk.Label(
        bel,
        text="Kaynak belgeyi analitik etiketle bağla — fatura/stok/finans tutarı yeniden yazılmaz.",
        wraplength=600,
    ).pack(anchor="w")
    bf = ttk.Frame(bel)
    bf.pack(fill="x", pady=8)
    tip_v = tk.StringVar(value="satis_fatura")
    id_v = tk.StringVar()
    no_v = tk.StringVar()
    pay_v = tk.StringVar()
    ttk.Label(bf, text="Kaynak tip:").grid(row=0, column=0, sticky="w")
    ttk.Combobox(
        bf,
        textvariable=tip_v,
        values=(
            "satis_fatura",
            "alis_fatura",
            "satis_siparis",
            "alis_siparis",
            "irsaliye",
            "gider_fisi",
            "tahsilat",
            "odeme",
        ),
        width=18,
        state="readonly",
    ).grid(row=0, column=1, sticky="w", padx=4)
    ttk.Label(bf, text="Kaynak id:").grid(row=1, column=0, sticky="w")
    ttk.Entry(bf, textvariable=id_v, width=16).grid(row=1, column=1, sticky="w", padx=4)
    ttk.Label(bf, text="Belge no:").grid(row=2, column=0, sticky="w")
    ttk.Entry(bf, textvariable=no_v, width=16).grid(row=2, column=1, sticky="w", padx=4)
    ttk.Label(bf, text="Pay tutar (ops):").grid(row=3, column=0, sticky="w")
    ttk.Entry(bf, textvariable=pay_v, width=16).grid(row=3, column=1, sticky="w", padx=4)

    def bagla():
        if not id_v.get().strip():
            messagebox.showwarning("Proje", "Kaynak id zorunlu.", parent=app)
            return
        try:
            r = ProjeService.belge_bagla(
                proje_id,
                kaynak_tip=tip_v.get(),
                kaynak_id=id_v.get().strip(),
                kaynak_no=no_v.get().strip() or None,
                tutar_pay=pay_v.get().strip() or None,
            )
            messagebox.showinfo(
                "Proje",
                f"{'Yeni' if r['yeni'] else 'Mevcut'} bağlantı id={r['id']}",
                parent=app,
            )
            proje_kart_goster(app, proje_id)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Proje", str(exc), parent=app)

    ttk.Button(bf, text="Bağla", command=bagla).grid(row=4, column=1, sticky="e", pady=8)

    for ad in (
        "Gelirler",
        "Giderler ve Maliyetler",
        "Bütçe",
        "Faturalar",
        "Sipariş ve İrsaliyeler",
        "Tahsilat Ödeme",
        "Stok ve Malzeme",
        "Aşamalar",
        "Cari Hesaplar",
        "Notlar ve Görevler",
        "İşlem Geçmişi",
    ):
        s = sekme(ad)
        ttk.Label(
            s,
            text="Bu sekme belge bağlama genişletmesiyle doldurulacak. Kaynak belge tutarları burada yeniden yazılmaz.",
            wraplength=600,
        ).pack(anchor="w")


def proje_hareketler_goster(app) -> None:
    app._icerigi_temizle()
    ttk.Label(app.icerik, text="PROJE HAREKETLERİ", style="Baslik.TLabel").pack(
        anchor="w", padx=20, pady=(16, 0)
    )
    ttk.Button(app.icerik, text="← Proje Takip", command=lambda: proje_hub_goster(app)).pack(
        anchor="w", padx=20, pady=8
    )
    ttk.Label(
        app.icerik,
        text="Proje bağlı belgeler listesi — belge ekranlarından proje seçimi sonraki adımda eklenir.",
        wraplength=640,
    ).pack(anchor="w", padx=20)


def proje_rapor_goster(app) -> None:
    app._icerigi_temizle()
    ttk.Label(app.icerik, text="PROJE RAPORLARI", style="Baslik.TLabel").pack(
        anchor="w", padx=20, pady=(16, 0)
    )
    ttk.Button(app.icerik, text="← Proje Takip", command=lambda: proje_hub_goster(app)).pack(
        anchor="w", padx=20, pady=8
    )
    ProjeService.ensure_schema()
    for p in ProjeService.listele()[:30]:
        o = ProjeService.finansal_ozet(p["id"])
        ttk.Label(
            app.icerik,
            text=f"{p['kod']} {p['ad']}: hedef kâr {o['hedef_kar']} | bağlı {o['bagli_belge']}",
        ).pack(anchor="w", padx=20, pady=2)


def proje_ayarlar_goster(app) -> None:
    app._icerigi_temizle()
    ttk.Label(app.icerik, text="PROJE AYARLARI", style="Baslik.TLabel").pack(
        anchor="w", padx=20, pady=(16, 0)
    )
    ttk.Button(app.icerik, text="← Proje Takip", command=lambda: proje_hub_goster(app)).pack(
        anchor="w", padx=20, pady=8
    )
    a = ProjeService.ayarlari_getir()
    frm = ttk.LabelFrame(app.icerik, text=f"Firma: {oturum.firma_unvan or '—'}", padding=12)
    frm.pack(fill="x", padx=20, pady=8)
    vars_ = {}
    for key, etiket in (
        ("asama_aktif", "Aşamalar"),
        ("coklu_dagitim", "Çoklu dağıtım"),
        ("ortak_gider", "Ortak gider"),
        ("hakedis", "Hakediş"),
        ("gorevler", "Görevler"),
    ):
        v = tk.BooleanVar(value=bool(a.get(key)))
        vars_[key] = v
        ttk.Checkbutton(frm, text=f"{etiket} (ayarlarla etkin)", variable=v).pack(anchor="w")

    def kaydet():
        ProjeService.ayarlari_kaydet({k: v.get() for k, v in vars_.items()})
        messagebox.showinfo("Proje Ayarları", "Kaydedildi.", parent=app)

    ttk.Button(app.icerik, text="Kaydet", command=kaydet).pack(anchor="w", padx=20, pady=12)


def _t(v) -> str:
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    return str(v or "—")


# Sol menü alt anahtarları (ana_panel MENU_ALT_OGELERI)
def proje_yeni_ac(app) -> None:
    proje_yeni_dialog(app)


def proje_liste_ac(app) -> None:
    proje_liste_goster(app)


def proje_hareket_ac(app) -> None:
    proje_hareketler_goster(app)


def proje_rapor_ac(app) -> None:
    proje_rapor_goster(app)


def proje_ayar_ac(app) -> None:
    proje_ayarlar_goster(app)
