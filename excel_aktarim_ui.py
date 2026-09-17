"""Excel Veri Aktarım — ortak 5 adımlı sihirbaz ve geçmiş."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

import excel_aktarim  # tip kayıtları
from excel_aktarim.executor import ImportAuditService, ImportExecutor
from excel_aktarim.mapping import ColumnMappingService
from excel_aktarim.preview import ImportPreviewService
from excel_aktarim.reader import ExcelReaderService
from excel_aktarim.rollback import ImportRollbackService
from excel_aktarim.template import ImportTemplateService
from excel_aktarim.types import ImportTipi, getir, modul_tipleri


def _yetki(*kodlar: str) -> bool:
    try:
        from database.access import yetki_var

        return any(yetki_var(k) for k in kodlar)
    except Exception:
        return True


def _kullanici() -> tuple[int | None, str | None]:
    try:
        from database.session_manager import oturum

        return oturum.user_id, oturum.kullanici_adi
    except Exception:
        return None, None


def excel_aktarim_hub_goster(app, *, modul: str, baslik: str, geri_fn: Callable | None = None) -> None:
    """Modül alt menüsünden açılan tip listesi + geçmiş."""
    app._icerigi_temizle()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: excel_aktarim_hub_goster(app, modul=modul, baslik=baslik, geri_fn=geri_fn))

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    if geri_fn:
        ttk.Button(ust, text="← Geri", command=geri_fn).pack(side="right")

    ttk.Label(
        app.icerik,
        text="Şablon indirin, Excel doldurun, 5 adımlı sihirbazla aktarın. Dry-run sonrası onay ile kayıt yapılır.",
    ).pack(anchor="w", pady=(8, 0))

    tipler = modul_tipleri(modul)
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(20, 0))
    alt.columnconfigure(0, weight=1, minsize=520)

    if not tipler:
        ttk.Label(alt, text="Bu modül için henüz tanımlı aktarım tipi yok.").pack(anchor="w")
    else:
        for i, tip in enumerate(tipler):
            ttk.Button(
                alt,
                text=tip.ad.upper(),
                style="AltMenu.TButton",
                command=lambda t=tip: excel_aktarim_sihirbaz_goster(
                    app, tip_kod=t.kod, geri_fn=lambda: excel_aktarim_hub_goster(
                        app, modul=modul, baslik=baslik, geri_fn=geri_fn
                    )
                ),
            ).grid(row=i, column=0, sticky="ew", pady=4)

    ttk.Button(
        app.icerik,
        text="Aktarım Geçmişi",
        command=lambda: excel_aktarim_gecmis_goster(
            app,
            modul=modul,
            geri_fn=lambda: excel_aktarim_hub_goster(app, modul=modul, baslik=baslik, geri_fn=geri_fn),
        ),
    ).pack(anchor="w", pady=(16, 0))


def excel_aktarim_sihirbaz_goster(app, *, tip_kod: str, geri_fn: Callable | None = None) -> None:
    tip = getir(tip_kod)
    if not _yetki(*tip.izinler):
        messagebox.showwarning("Yetki", "Excel veri aktarım yetkiniz yok.")
        return

    app._icerigi_temizle()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: excel_aktarim_sihirbaz_goster(app, tip_kod=tip_kod, geri_fn=geri_fn))

    durum: dict[str, Any] = {
        "adim": 1,
        "dosya": None,
        "okuma": None,
        "esleme": {},
        "guncelleme_modu": "guncelle",
        "onizleme": None,
        "batch_id": None,
    }

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=f"EXCEL AKTARIM — {tip.ad.upper()}", style="Baslik.TLabel").pack(side="left")
    if geri_fn:
        ttk.Button(ust, text="← Geri", command=geri_fn).pack(side="right")

    adim_lbl = ttk.Label(app.icerik, text="")
    adim_lbl.pack(anchor="w", pady=(8, 0))

    govde = ttk.Frame(app.icerik)
    govde.pack(fill="both", expand=True, pady=(12, 0))

    nav = ttk.Frame(app.icerik)
    nav.pack(fill="x", pady=(12, 0))

    def _temiz_govde() -> None:
        for w in govde.winfo_children():
            w.destroy()

    def _adim_baslik() -> None:
        adlar = {
            1: "1/5 — Tip ve şablon",
            2: "2/5 — Dosya seç",
            3: "3/5 — Sütun eşleme",
            4: "4/5 — Doğrulama / önizleme",
            5: "5/5 — Aktarımı çalıştır",
        }
        adim_lbl.configure(text=adlar.get(durum["adim"], ""))

    def _goster() -> None:
        _temiz_govde()
        _adim_baslik()
        adim = durum["adim"]
        if adim == 1:
            _adim1()
        elif adim == 2:
            _adim2()
        elif adim == 3:
            _adim3()
        elif adim == 4:
            _adim4()
        else:
            _adim5()
        _nav_guncelle()

    def _adim1() -> None:
        ttk.Label(govde, text=tip.aciklama or tip.ad).pack(anchor="w")
        ttk.Label(govde, text=f"Modül: {tip.modul}  |  Tip: {tip.kod}").pack(anchor="w", pady=(6, 0))
        ttk.Button(govde, text="Şablon Excel İndir", command=_sablon_indir).pack(anchor="w", pady=(16, 0))
        ttk.Label(govde, text="Zorunlu alanlar:").pack(anchor="w", pady=(16, 4))
        for a in tip.alanlar:
            if a.zorunlu:
                ttk.Label(govde, text=f"• {a.baslik}").pack(anchor="w")

    def _sablon_indir() -> None:
        yol = filedialog.asksaveasfilename(
            title="Şablonu kaydet",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=f"{tip.kod}_sablon.xlsx",
        )
        if not yol:
            return
        ImportTemplateService.olustur(tip, yol)
        messagebox.showinfo("Şablon", f"Şablon kaydedildi:\n{yol}")

    def _adim2() -> None:
        ttk.Label(govde, text="Aktarılacak .xlsx dosyasını seçin.").pack(anchor="w")
        satir = ttk.Frame(govde)
        satir.pack(fill="x", pady=(12, 0))
        yol_var = tk.StringVar(value=str(durum["dosya"] or ""))
        ttk.Entry(satir, textvariable=yol_var, width=70).pack(side="left", fill="x", expand=True)
        def sec():
            p = filedialog.askopenfilename(
                title="Excel seç",
                filetypes=[("Excel", "*.xlsx *.xlsm"), ("Tümü", "*.*")],
            )
            if p:
                yol_var.set(p)
                durum["dosya"] = p
        ttk.Button(satir, text="Gözat…", command=sec).pack(side="left", padx=(8, 0))
        ttk.Label(govde, text="Güncelleme çakışması:").pack(anchor="w", pady=(16, 4))
        mod_var = tk.StringVar(value=durum["guncelleme_modu"])
        for deger, etiket in (
            ("guncelle", "Mevcut kaydı güncelle"),
            ("atla", "Mevcut kaydı atla"),
            ("hata", "Mevcut kayıtta hata ver"),
        ):
            ttk.Radiobutton(govde, text=etiket, value=deger, variable=mod_var).pack(anchor="w")

        def kaydet_mod(*_a):
            durum["guncelleme_modu"] = mod_var.get()
        mod_var.trace_add("write", kaydet_mod)

        if durum.get("okuma"):
            ttk.Label(
                govde,
                text=f"Okunan: {durum['okuma'].dosya_adi} — {len(durum['okuma'].satirlar)} satır, "
                f"{len(durum['okuma'].basliklar)} sütun",
            ).pack(anchor="w", pady=(12, 0))

    def _adim3() -> None:
        if not durum.get("okuma"):
            ttk.Label(govde, text="Önce dosya seçilmeli.").pack(anchor="w")
            return
        okuma = durum["okuma"]
        if not durum["esleme"]:
            durum["esleme"] = ColumnMappingService.otomatik_esle(tip, okuma.basliklar).esleme

        ttk.Label(govde, text="Excel sütunu → Sistem alanı").pack(anchor="w")
        tablo = ttk.Frame(govde)
        tablo.pack(fill="both", expand=True, pady=(8, 0))
        ttk.Label(tablo, text="Excel", width=28).grid(row=0, column=0, sticky="w")
        ttk.Label(tablo, text="Sistem alanı", width=28).grid(row=0, column=1, sticky="w")

        alan_secenek = ["(yok)"] + [f"{a.kod} — {a.baslik}" for a in tip.alanlar]
        kod_map = {f"{a.kod} — {a.baslik}": a.kod for a in tip.alanlar}
        ters = {v: k for k, v in kod_map.items()}
        combos: dict[str, ttk.Combobox] = {}

        for i, baslik in enumerate(okuma.basliklar, start=1):
            ttk.Label(tablo, text=baslik, width=28).grid(row=i, column=0, sticky="w", pady=2)
            cb = ttk.Combobox(tablo, values=alan_secenek, width=32, state="readonly")
            mevcut = durum["esleme"].get(baslik)
            cb.set(ters.get(mevcut, "(yok)") if mevcut else "(yok)")
            cb.grid(row=i, column=1, sticky="w", pady=2)
            combos[baslik] = cb

        def eslemeyi_al() -> dict[str, str]:
            out: dict[str, str] = {}
            for baslik, cb in combos.items():
                sec = cb.get()
                if sec and sec != "(yok)" and sec in kod_map:
                    out[baslik] = kod_map[sec]
            return out

        durum["_esleme_al"] = eslemeyi_al
        eksik = ColumnMappingService.otomatik_esle(tip, okuma.basliklar)
        if eksik.eksik_zorunlu and not any(durum["esleme"].get(h) in eksik.eksik_zorunlu for h in durum["esleme"]):
            # yeniden hesap
            eslenen = set(durum["esleme"].values())
            eksikler = [a.kod for a in tip.alanlar if a.zorunlu and a.kod not in eslenen]
            if eksikler:
                ttk.Label(govde, text=f"Eksik zorunlu alanlar: {', '.join(eksikler)}", foreground="#a40").pack(
                    anchor="w", pady=(8, 0)
                )

    def _adim4() -> None:
        if not durum.get("onizleme"):
            ttk.Label(govde, text="Önizleme hazırlanıyor…").pack(anchor="w")
            try:
                _onizleme_calistir()
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Doğrulama", str(exc))
                return
            _temiz_govde()
            _adim_baslik()

        onz = durum["onizleme"]
        r = onz.rapor
        ttk.Label(
            govde,
            text=f"Geçerli: {r.gecerli}  |  Hatalı: {r.hatali}  |  Eklenecek: {r.eklenecek}  |  "
            f"Güncellenecek: {r.guncellenecek}  |  Atlanacak: {r.atlanacak}",
        ).pack(anchor="w")

        tree = ttk.Treeview(govde, columns=("satir", "islem", "ozet", "mesaj"), show="headings", height=16)
        for c, t, w in (
            ("satir", "Satır", 60),
            ("islem", "İşlem", 80),
            ("ozet", "Özet", 280),
            ("mesaj", "Mesaj", 280),
        ):
            tree.heading(c, text=t)
            tree.column(c, width=w, anchor="w")
        tree.pack(fill="both", expand=True, pady=(8, 0))
        for o in onz.ornekler:
            tree.insert("", "end", values=(o["satir_no"], o["islem"], o["ozet"], o["mesaj"]))
        if r.hatali:
            ttk.Label(govde, text="Hatalı satırlar aktarımda atlanır (kısmi başarı mümkün).", foreground="#a40").pack(
                anchor="w", pady=(8, 0)
            )

    def _onizleme_calistir() -> None:
        if durum.get("_esleme_al"):
            durum["esleme"] = durum["_esleme_al"]()
        importer = tip.importer_factory()
        durum["onizleme"] = ImportPreviewService.calistir(
            importer,
            durum["okuma"].satirlar,
            durum["esleme"],
            guncelleme_modu=durum["guncelleme_modu"],
        )
        uid, uname = _kullanici()
        batch = ImportAuditService.batch_olustur(
            modul=tip.modul,
            import_tipi=tip.kod,
            dosya_adi=Path(durum["dosya"]).name if durum["dosya"] else None,
            dosya_yolu=str(durum["dosya"]) if durum["dosya"] else None,
            kullanici_id=uid,
            kullanici_adi=uname,
        )
        durum["batch_id"] = batch.id
        ImportExecutor.dry_run_kaydet(batch.id, durum["onizleme"].rapor)

    def _adim5() -> None:
        onz = durum.get("onizleme")
        if not onz:
            ttk.Label(govde, text="Önce doğrulama adımını tamamlayın.").pack(anchor="w")
            return
        r = onz.rapor
        ttk.Label(
            govde,
            text=f"Aktarım onayına hazır. Eklenecek {r.eklenecek}, güncellenecek {r.guncellenecek}, "
            f"hatalı {r.hatali} satır.",
        ).pack(anchor="w")
        ttk.Label(govde, text="Bu işlem geri alınabilir (virman hariç).").pack(anchor="w", pady=(8, 0))
        ttk.Button(govde, text="AKTARIMI ÇALIŞTIR", command=_calistir).pack(anchor="w", pady=(20, 0))

    def _calistir() -> None:
        if not messagebox.askyesno("Onay", "Aktarımı şimdi çalıştırmak istiyor musunuz?"):
            return
        try:
            importer = tip.importer_factory()
            batch = ImportExecutor.calistir(
                durum["batch_id"],
                importer,
                durum["okuma"].satirlar,
                durum["esleme"],
                guncelleme_modu=durum["guncelleme_modu"],
                hatali_satirlari_atla=True,
            )
            messagebox.showinfo(
                "Tamam",
                f"Durum: {batch.durum}\n"
                f"Eklenen: {batch.eklenen_satir}\n"
                f"Güncellenen: {batch.guncellenen_satir}\n"
                f"Hatalı: {batch.hata_satir}\n"
                f"Batch: {batch.batch_kodu}",
            )
            if geri_fn:
                geri_fn()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Aktarım hatası", str(exc))

    def _ileri() -> None:
        adim = durum["adim"]
        if adim == 1:
            durum["adim"] = 2
        elif adim == 2:
            yol = durum.get("dosya")
            if not yol:
                messagebox.showwarning("Dosya", "Lütfen bir Excel dosyası seçin.")
                return
            try:
                durum["okuma"] = ExcelReaderService.oku(yol)
                durum["esleme"] = ColumnMappingService.otomatik_esle(tip, durum["okuma"].basliklar).esleme
                durum["onizleme"] = None
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Okuma", str(exc))
                return
            durum["adim"] = 3
        elif adim == 3:
            if durum.get("_esleme_al"):
                durum["esleme"] = durum["_esleme_al"]()
            eslenen = set(durum["esleme"].values())
            eksik = [a.baslik for a in tip.alanlar if a.zorunlu and a.kod not in eslenen]
            if eksik:
                messagebox.showwarning("Eşleme", "Zorunlu alanlar eşlenmedi:\n" + "\n".join(eksik))
                return
            durum["onizleme"] = None
            durum["adim"] = 4
        elif adim == 4:
            if not durum.get("onizleme"):
                try:
                    _onizleme_calistir()
                except Exception as exc:  # noqa: BLE001
                    messagebox.showerror("Doğrulama", str(exc))
                    return
            durum["adim"] = 5
        _goster()

    def _geri_adim() -> None:
        if durum["adim"] > 1:
            durum["adim"] -= 1
            _goster()
        elif geri_fn:
            geri_fn()

    def _nav_guncelle() -> None:
        for w in nav.winfo_children():
            w.destroy()
        ttk.Button(nav, text="← Önceki", command=_geri_adim).pack(side="left")
        if durum["adim"] < 5:
            ttk.Button(nav, text="Sonraki →", command=_ileri).pack(side="right")

    _goster()


def excel_aktarim_gecmis_goster(app, *, modul: str | None = None, geri_fn: Callable | None = None) -> None:
    app._icerigi_temizle()
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="EXCEL AKTARIM GEÇMİŞİ", style="Baslik.TLabel").pack(side="left")
    if geri_fn:
        ttk.Button(ust, text="← Geri", command=geri_fn).pack(side="right")

    tree = ttk.Treeview(
        app.icerik,
        columns=("kod", "tip", "durum", "ekle", "guncelle", "hata", "kullanici", "tarih"),
        show="headings",
        height=18,
    )
    for c, t, w in (
        ("kod", "Batch", 140),
        ("tip", "Tip", 140),
        ("durum", "Durum", 90),
        ("ekle", "Eklenen", 70),
        ("guncelle", "Günc.", 70),
        ("hata", "Hata", 60),
        ("kullanici", "Kullanıcı", 100),
        ("tarih", "Tarih", 140),
    ):
        tree.heading(c, text=t)
        tree.column(c, width=w, anchor="w")
    tree.pack(fill="both", expand=True, pady=(12, 0))

    batches = ImportAuditService.listele(modul=modul)
    id_map: dict[str, int] = {}
    for b in batches:
        iid = tree.insert(
            "",
            "end",
            values=(
                b.batch_kodu,
                b.import_tipi,
                b.durum,
                b.eklenen_satir,
                b.guncellenen_satir,
                b.hata_satir,
                b.kullanici_adi or "",
                b.created_at.strftime("%d.%m.%Y %H:%M") if b.created_at else "",
            ),
        )
        id_map[iid] = b.id

    def geri_al() -> None:
        if not _yetki("excel_aktarim_geri_al", "excel_aktarim"):
            messagebox.showwarning("Yetki", "Geri alma yetkiniz yok.")
            return
        sec = tree.selection()
        if not sec:
            return
        batch_id = id_map.get(sec[0])
        if not batch_id:
            return
        if not messagebox.askyesno("Geri al", "Seçili aktarımı geri almak istiyor musunuz?"):
            return
        try:
            batch = ImportAuditService.getir(batch_id)
            if batch is None:
                raise ValueError("Batch bulunamadı.")
            tip = getir(batch.import_tipi if batch.import_tipi != "cari_virman_satis" else "cari_virman")
            importer = tip.importer_factory()
            ImportRollbackService.geri_al(batch_id, importer.geri_al_degisiklik)
            messagebox.showinfo("Tamam", "Aktarım geri alındı.")
            excel_aktarim_gecmis_goster(app, modul=modul, geri_fn=geri_fn)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Geri alma", str(exc))

    ttk.Button(app.icerik, text="Seçili Aktarımı Geri Al", command=geri_al).pack(anchor="w", pady=(10, 0))
