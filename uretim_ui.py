"""Üretim hub — reçeteler ve emirler (Stoklar altında).

Sprint 1: liste + basit reçete/emir diyalogları + hızlı üretim.
Paket üretim ekranından ayrıdır.
"""

from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

from database.uretim_service import UretimService
from fatura_tema import ACIK_BG, stil_uygula, tk_buton


def _menu_isaretle(app):
    kabuk = getattr(app, "_ana_panel_kabuk", None)
    if kabuk is not None:
        kabuk.menu_secili_guncelle("stoklar")


def uretim_hub_goster(app) -> None:
    app._icerigi_temizle()
    stil_uygula(root=app)
    _menu_isaretle(app)
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass

    UretimService.ensure_schema()

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x", padx=16, pady=(16, 8))
    ttk.Label(ust, text="ÜRETİM", font=("Segoe UI", 16, "bold")).pack(side="left")
    tk_buton(ust, "← Stoklar", app.stoklar_menusu_goster, rol="ikincil").pack(side="right")

    ttk.Label(
        app.icerik,
        text="Reçete → emir → malzeme ihtiyacı → hızlı üretim (sarf + mamul giriş).",
        foreground="#64748B",
    ).pack(anchor="w", padx=16)

    arac = ttk.Frame(app.icerik)
    arac.pack(fill="x", padx=16, pady=8)
    tk_buton(arac, "Yenile", lambda: uretim_hub_goster(app), rol="ara").pack(side="left", padx=2)
    tk_buton(arac, "Yeni Reçete", lambda: _recete_dialog(app), rol="yeni").pack(side="left", padx=2)
    tk_buton(arac, "Yeni Emir", lambda: _emir_dialog(app), rol="yeni").pack(side="left", padx=2)

    paned = ttk.Panedwindow(app.icerik, orient="horizontal")
    paned.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    sol = ttk.Frame(paned)
    sag = ttk.Frame(paned)
    paned.add(sol, weight=1)
    paned.add(sag, weight=1)

    ttk.Label(sol, text="Reçeteler", font=("Segoe UI", 11, "bold")).pack(anchor="w")
    rec_cols = ("kod", "mamul", "surum", "durum", "satir")
    rec_tablo = ttk.Treeview(sol, columns=rec_cols, show="headings", height=16)
    for c, b, w in (
        ("kod", "Kod", 100),
        ("mamul", "Mamul", 120),
        ("surum", "Sürüm", 50),
        ("durum", "Durum", 70),
        ("satir", "Satır", 50),
    ):
        rec_tablo.heading(c, text=b)
        rec_tablo.column(c, width=w, anchor="w")
    rec_tablo.pack(fill="both", expand=True, pady=4)
    for r in UretimService.recete_listesi():
        rec_tablo.insert(
            "",
            "end",
            iid=str(r["id"]),
            values=(r["recete_kodu"], r["mamul_stok_kodu"], r["surum"], r["durum"], r["satir_adet"]),
        )

    def _aktiflestir():
        sec = rec_tablo.selection()
        if not sec:
            messagebox.showinfo("Reçete", "Aktifleştirilecek reçeteyi seçin.", parent=app)
            return
        try:
            UretimService.recete_aktiflestir(int(sec[0]))
            uretim_hub_goster(app)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Reçete", str(exc), parent=app)

    tk_buton(sol, "Seçileni Aktifleştir", _aktiflestir, rol="onay").pack(anchor="w", pady=4)

    ttk.Label(sag, text="Üretim Emirleri", font=("Segoe UI", 11, "bold")).pack(anchor="w")
    em_cols = ("no", "tarih", "mamul", "plan", "uretilen", "durum", "maliyet")
    em_tablo = ttk.Treeview(sag, columns=em_cols, show="headings", height=16)
    for c, b, w in (
        ("no", "Emir No", 110),
        ("tarih", "Tarih", 80),
        ("mamul", "Mamul", 90),
        ("plan", "Plan", 60),
        ("uretilen", "Üretilen", 60),
        ("durum", "Durum", 80),
        ("maliyet", "Maliyet", 80),
    ):
        em_tablo.heading(c, text=b)
        em_tablo.column(c, width=w, anchor="w")
    em_tablo.pack(fill="both", expand=True, pady=4)
    for e in UretimService.emir_listesi():
        em_tablo.insert(
            "",
            "end",
            iid=str(e["id"]),
            values=(
                e["emir_no"],
                e["tarih"].strftime("%d.%m.%Y") if e.get("tarih") else "",
                e["mamul_stok_kodu"],
                str(e["planlanan_miktar"]),
                str(e["uretilen_miktar"]),
                e["durum"],
                e.get("maliyet_durumu") or "",
            ),
        )

    def _hizli():
        sec = em_tablo.selection()
        if not sec:
            messagebox.showinfo("Üretim", "Emir seçin.", parent=app)
            return
        if not messagebox.askyesno(
            "Hızlı üretim",
            "Plan malzemeleri sarf edilip mamul stoğa alınacak. Devam?",
            parent=app,
        ):
            return
        try:
            sonuc = UretimService.hizli_uret(int(sec[0]))
            messagebox.showinfo(
                "Üretim tamam",
                f"Emir {sonuc['emir_no']}\n"
                f"Sarf: {sonuc['sarf_fis_no']}\n"
                f"Mamul: {sonuc['mamul_fis_no']}\n"
                f"Miktar: {sonuc['uretilen_miktar']}\n"
                f"Maliyet: {sonuc['toplam_maliyet']}",
                parent=app,
            )
            uretim_hub_goster(app)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Üretim", str(exc), parent=app)

    def _ihtiyac():
        sec = em_tablo.selection()
        if not sec:
            # reçeteden önizleme
            rsec = rec_tablo.selection()
            if not rsec:
                messagebox.showinfo("İhtiyaç", "Reçete veya emir seçin.", parent=app)
                return
            miktar = simpledialog.askfloat("İhtiyaç", "Planlanan mamul miktarı:", parent=app, minvalue=0.0001)
            if not miktar:
                return
            try:
                satirlar = UretimService.ihtiyac_hesapla(int(rsec[0]), Decimal(str(miktar)))
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("İhtiyaç", str(exc), parent=app)
                return
        else:
            emirler = {str(e["id"]): e for e in UretimService.emir_listesi()}
            e = emirler.get(sec[0])
            if not e:
                return
            receteler = UretimService.recete_listesi()
            # emirdeki reçete id yok listede — emir_olustur ihtiyacı zaten hesapladı; reçeteden
            messagebox.showinfo(
                "İhtiyaç",
                f"Emir {e['emir_no']}: plan {e['planlanan_miktar']} {e.get('birim') or ''}\n"
                f"Depo: {e.get('kaynak_depo')}\n"
                "Ayrıntılı ihtiyaç için reçeteyi seçip «İhtiyaç Hesapla» kullanın.",
                parent=app,
            )
            return
        metin = "\n".join(
            f"• {s['malzeme_stok_kodu']}: {s['gereken']} {s['birim']} "
            f"(mevcut {s['mevcut']}, kullanılabilir {s.get('kullanilabilir', s['mevcut'])}, "
            f"eksik {s['eksik']}) ≈ {s['tahmini_maliyet']} TL"
            for s in satirlar
        )
        messagebox.showinfo("Malzeme ihtiyacı", metin or "Satır yok.", parent=app)

    def _rezerve():
        sec = em_tablo.selection()
        if not sec:
            messagebox.showinfo("Rezervasyon", "Emir seçin.", parent=app)
            return
        try:
            sonuc = UretimService.rezervasyon_yap(int(sec[0]))
            ozet = "\n".join(
                f"• {r['stok']}: {r['miktar']} ({r['depo']})" for r in sonuc.get("rezervasyonlar") or []
            )
            messagebox.showinfo(
                "Rezervasyon",
                f"{sonuc['emir_no']}\n{sonuc['not']}\n\n{ozet or 'Ayrılacak kullanılabilir stok yok.'}",
                parent=app,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Rezervasyon", str(exc), parent=app)

    def _rezerv_serbest():
        sec = em_tablo.selection()
        if not sec:
            messagebox.showinfo("Rezervasyon", "Emir seçin.", parent=app)
            return
        try:
            sonuc = UretimService.rezervasyon_serbest(int(sec[0]))
            messagebox.showinfo(
                "Rezervasyon",
                f"Serbest bırakılan kayıt: {sonuc['serbest_adet']}",
                parent=app,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Rezervasyon", str(exc), parent=app)

    def _kismi():
        sec = em_tablo.selection()
        if not sec:
            messagebox.showinfo("Kısmi üretim", "Emir seçin.", parent=app)
            return
        miktar = simpledialog.askfloat(
            "Kısmi üretim", "Bu sefer üretilecek mamul miktarı:", parent=app, minvalue=0.0001
        )
        if not miktar:
            return
        try:
            sonuc = UretimService.kismi_uret(int(sec[0]), Decimal(str(miktar)))
            messagebox.showinfo(
                "Kısmi üretim",
                f"Emir {sonuc['emir_no']}\n"
                f"Bu giriş: {sonuc['bu_giris']}\n"
                f"Toplam üretilen: {sonuc['uretilen_miktar']}\n"
                f"Durum: {sonuc['durum']} / {sonuc['maliyet_durumu']}",
                parent=app,
            )
            uretim_hub_goster(app)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Kısmi üretim", str(exc), parent=app)

    def _maliyet_kesin():
        sec = em_tablo.selection()
        if not sec:
            messagebox.showinfo("Maliyet", "Emir seçin.", parent=app)
            return
        try:
            sonuc = UretimService.maliyet_kesinlestir(int(sec[0]))
            messagebox.showinfo(
                "Maliyet kesin",
                f"Emir {sonuc['emir_no']}: {sonuc['maliyet_durumu']}"
                + (" (zaten kesin)" if sonuc.get("zaten_kesin") else ""),
                parent=app,
            )
            uretim_hub_goster(app)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Maliyet", str(exc), parent=app)

    alt = ttk.Frame(sag)
    alt.pack(fill="x", pady=4)
    tk_buton(alt, "İhtiyaç Hesapla", _ihtiyac, rol="ara").pack(side="left", padx=2)
    tk_buton(alt, "Rezerve Et", _rezerve, rol="yeni").pack(side="left", padx=2)
    tk_buton(alt, "Rezerv Serbest", _rezerv_serbest, rol="ikincil").pack(side="left", padx=2)
    tk_buton(alt, "Hızlı Üret", _hizli, rol="onay").pack(side="left", padx=2)
    tk_buton(alt, "Kısmi Üret", _kismi, rol="yeni").pack(side="left", padx=2)
    tk_buton(alt, "Maliyet Kesinleştir", _maliyet_kesin, rol="onay").pack(side="left", padx=2)


def _recete_dialog(app) -> None:
    dlg = tk.Toplevel(app)
    dlg.title("Yeni üretim reçetesi")
    dlg.transient(app)
    dlg.grab_set()
    from ui_pencere import pencere_os_krom_ac

    pencere_os_krom_ac(dlg)
    frm = ttk.Frame(dlg, padding=12)
    frm.pack(fill="both", expand=True)

    alanlar = {}
    for i, (etiket, key, ornek) in enumerate(
        (
            ("Reçete kodu", "recete_kodu", "REC-001"),
            ("Mamul stok kodu", "mamul_stok_kodu", ""),
            ("Esas miktar", "esas_miktar", "1"),
            ("Çıktı birimi", "cikti_birimi", "Adet"),
        )
    ):
        ttk.Label(frm, text=etiket).grid(row=i, column=0, sticky="w", pady=2)
        e = ttk.Entry(frm, width=36)
        e.insert(0, ornek)
        e.grid(row=i, column=1, sticky="ew", pady=2)
        alanlar[key] = e

    ttk.Label(frm, text="Malzeme satırları (kod;net;fire%;birim) — satır satır").grid(
        row=4, column=0, columnspan=2, sticky="w", pady=(8, 2)
    )
    metin = tk.Text(frm, width=48, height=8)
    metin.insert("1.0", "HAM001;10;2;kg\n")
    metin.grid(row=5, column=0, columnspan=2, sticky="nsew")
    frm.rowconfigure(5, weight=1)
    frm.columnconfigure(1, weight=1)

    def kaydet():
        satirlar = []
        for ham in metin.get("1.0", "end").splitlines():
            ham = ham.strip()
            if not ham or ham.startswith("#"):
                continue
            parca = [p.strip() for p in ham.replace(",", ";").split(";")]
            if len(parca) < 2:
                messagebox.showerror("Reçete", f"Satır okunamadı: {ham}", parent=dlg)
                return
            fire = Decimal(parca[2].replace("%", "") or "0") if len(parca) > 2 else Decimal("0")
            satirlar.append(
                {
                    "malzeme_stok_kodu": parca[0],
                    "net_miktar": Decimal(parca[1].replace(",", ".")),
                    "fire_orani": fire,
                    "birim": parca[3] if len(parca) > 3 else "Adet",
                }
            )
        try:
            UretimService.recete_kaydet(
                {
                    "recete_kodu": alanlar["recete_kodu"].get().strip(),
                    "mamul_stok_kodu": alanlar["mamul_stok_kodu"].get().strip(),
                    "esas_miktar": alanlar["esas_miktar"].get().strip() or "1",
                    "cikti_birimi": alanlar["cikti_birimi"].get().strip() or "Adet",
                    "durum": "TASLAK",
                },
                satirlar,
            )
            dlg.destroy()
            uretim_hub_goster(app)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Reçete", str(exc), parent=dlg)

    tk_buton(frm, "Kaydet", kaydet, rol="kaydet").grid(row=6, column=1, sticky="e", pady=8)


def _emir_dialog(app) -> None:
    aktif = [r for r in UretimService.recete_listesi() if r["durum"] == "AKTIF"]
    if not aktif:
        messagebox.showinfo(
            "Emir",
            "Önce bir reçete oluşturup Aktifleştirin.",
            parent=app,
        )
        return
    dlg = tk.Toplevel(app)
    dlg.title("Yeni üretim emri")
    dlg.transient(app)
    dlg.grab_set()
    from ui_pencere import pencere_os_krom_ac

    pencere_os_krom_ac(dlg)
    frm = ttk.Frame(dlg, padding=12)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="Aktif reçete").grid(row=0, column=0, sticky="w")
    etiketler = {
        f"{r['recete_kodu']} v{r['surum']} → {r['mamul_stok_kodu']}": r["id"] for r in aktif
    }
    cb = ttk.Combobox(frm, values=list(etiketler.keys()), state="readonly", width=40)
    cb.grid(row=0, column=1, sticky="ew", pady=2)
    if etiketler:
        cb.current(0)

    ttk.Label(frm, text="Planlanan miktar").grid(row=1, column=0, sticky="w")
    miktar_e = ttk.Entry(frm, width=20)
    miktar_e.insert(0, "1")
    miktar_e.grid(row=1, column=1, sticky="w", pady=2)

    ttk.Label(frm, text="Kaynak depo").grid(row=2, column=0, sticky="w")
    depo_e = ttk.Entry(frm, width=20)
    depo_e.insert(0, "ANA DEPO")
    depo_e.grid(row=2, column=1, sticky="w", pady=2)

    def kaydet():
        rid = etiketler.get(cb.get())
        if not rid:
            return
        try:
            UretimService.emir_olustur(
                {
                    "recete_id": rid,
                    "planlanan_miktar": miktar_e.get().strip(),
                    "kaynak_depo": depo_e.get().strip() or "ANA DEPO",
                    "mamul_depo": depo_e.get().strip() or "ANA DEPO",
                    "uretim_bicimi": "HIZLI",
                }
            )
            dlg.destroy()
            uretim_hub_goster(app)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Emir", str(exc), parent=dlg)

    tk_buton(frm, "Oluştur", kaydet, rol="kaydet").grid(row=3, column=1, sticky="e", pady=8)
