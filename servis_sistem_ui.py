"""Servis ve Sistem Kontrol Merkezi — Tkinter UI (Aşama 5: Seviye 1+2 onarım)."""

from __future__ import annotations

from datetime import datetime
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
import webbrowser
from pathlib import Path

from database.session_manager import oturum
from database.servis_sistem.backup_service import BackupService
from database.servis_sistem.database_integrity_service import DatabaseIntegrityService
from database.servis_sistem.error_log_service import ErrorLogService
from database.servis_sistem.module_diagnostic_service import ModuleDiagnosticService
from database.servis_sistem.repair_service import (
    RepairService,
    is_level1,
    is_level2,
    is_auto_repairable,
    onarim_yetkisi_var,
)
from database.servis_sistem.system_health_service import SystemHealthService
from ui_bg import arka_planda


def _yetki_servis(parent) -> bool:
    if oturum.role_kod == "YONETICI":
        return True
    if oturum.has_permission("servis_goruntuleme") or oturum.has_permission("servis_kontrol"):
        return True
    if oturum.has_permission("sistem_ayarlari"):
        return True
    messagebox.showwarning(
        "Yetki",
        "Servis ve Sistem Kontrol Merkezi'ne erişim yetkiniz yok.",
        parent=parent,
    )
    return False


def _kontrol_yetkisi(parent) -> bool:
    if oturum.role_kod == "YONETICI":
        return True
    if oturum.has_permission("servis_kontrol") or oturum.has_permission("sistem_ayarlari"):
        return True
    if oturum.has_permission("servis_goruntuleme"):
        return True
    messagebox.showwarning("Yetki", "Kontrol çalıştırma yetkiniz yok.", parent=parent)
    return False


def _onarim_yetkisi(parent) -> bool:
    if onarim_yetkisi_var():
        return True
    messagebox.showwarning(
        "Yetki",
        "Onarım için yönetici veya 'servis_onarim' yetkisi gerekir.",
        parent=parent,
    )
    return False


def _issue_detail_dialog(parent, m: dict) -> None:
    win = tk.Toplevel(parent)
    win.title("Sorun Detayı")
    win.transient(parent)
    win.grab_set()
    win.geometry("560x420")
    frm = ttk.Frame(win, padding=12)
    frm.pack(fill="both", expand=True)

    alanlar = [
        ("Önem / Severity", m.get("onem") or m.get("durum") or "—"),
        ("Durum (status)", m.get("status") or "open"),
        ("Modül", m.get("modul") or "—"),
        ("Hata Kodu", m.get("hata_kodu") or "—"),
        ("Kayıt / Belge", m.get("kayit_belge") or "—"),
        ("Otomatik düzeltilebilir", m.get("otomatik_duzeltme") or "Hayır"),
        ("Kullanıcı mesajı", m.get("aciklama") or "—"),
        ("Önerilen aksiyon", m.get("onerilen") or "—"),
        ("Teknik detay", m.get("teknik") or "—"),
    ]
    for i, (etiket, deger) in enumerate(alanlar):
        ttk.Label(frm, text=etiket, font=("Segoe UI", 9, "bold")).grid(
            row=i * 2, column=0, sticky="w", pady=(6, 0)
        )
        txt = tk.Text(frm, height=2 if i < 6 else 4, wrap="word", width=64)
        txt.insert("1.0", str(deger))
        txt.configure(state="disabled")
        txt.grid(row=i * 2 + 1, column=0, sticky="ew")
    frm.columnconfigure(0, weight=1)
    ttk.Button(frm, text="Kapat", command=win.destroy).grid(
        row=len(alanlar) * 2, column=0, pady=(12, 0), sticky="e"
    )


def _preview_dialog(parent, oniz: dict, *, baslik: str = "Onarım Önizlemesi") -> None:
    win = tk.Toplevel(parent)
    win.title(baslik)
    win.transient(parent)
    win.grab_set()
    win.geometry("640x480")
    frm = ttk.Frame(win, padding=12)
    frm.pack(fill="both", expand=True)

    satirlar = [
        ("Uygulanabilir", "Evet" if oniz.get("uygulanabilir") else "Hayır"),
        ("Seviye", str(oniz.get("seviye", "—"))),
        ("Risk", oniz.get("risk") or "—"),
        ("Hata kodu", oniz.get("issue_code") or "—"),
        ("Açıklama", oniz.get("aciklama") or "—"),
        ("Etkilenen", "\n".join(oniz.get("etkilenen_kayitlar") or []) or "—"),
        ("Yedek planı", oniz.get("yedek_plani") or oniz.get("yedek_yolu") or "—"),
        (
            "Geri alma",
            (
                f"Evet — {oniz.get('geri_alma_notu') or ''}"
                if oniz.get("geri_alma_mumkun")
                else f"Kısmi/OS — {oniz.get('geri_alma_notu') or '—'}"
            ),
        ),
        ("Doğrulama planı", oniz.get("dogrulama_plani") or "—"),
        ("Mesaj", oniz.get("mesaj") or "—"),
    ]
    txt = tk.Text(frm, wrap="word", height=22, width=72)
    txt.pack(fill="both", expand=True)
    for etiket, deger in satirlar:
        txt.insert("end", f"{etiket}\n", ("bold",))
        txt.insert("end", f"{deger}\n\n")
    try:
        txt.tag_configure("bold", font=("Segoe UI", 9, "bold"))
    except tk.TclError:
        pass
    txt.configure(state="disabled")
    ttk.Button(frm, text="Kapat", command=win.destroy).pack(anchor="e", pady=(8, 0))


def servis_sistem_goster(app) -> None:
    if not _yetki_servis(app):
        app.sayfa_goster("giris")
        return

    try:
        ErrorLogService.schema_hazirla()
    except Exception:
        pass

    for anahtar, dugme in app.menu_dugmeleri.items():
        dugme.configure(
            style="SeciliMenu.TButton" if anahtar == "servis" else "Menu.TButton"
        )

    app._icerigi_temizle()
    ttk.Label(app.icerik, text="SERVİS VE SİSTEM", style="Baslik.TLabel").pack(anchor="w")
    ttk.Label(
        app.icerik,
        text=(
            "Tarama + Seviye 1 güvenli onarım + Seviye 2 kontrollü veri onarımı. "
            "Seviye 3 (birleştirme / kapalı dönem / fiziksel silme) engelli."
        ),
    ).pack(anchor="w", pady=(4, 10))

    ozet_cerceve = ttk.Frame(app.icerik)
    ozet_cerceve.pack(fill="x", pady=(0, 8))
    kartlar: dict[str, ttk.Label] = {}
    for i, (kod, baslik, renk) in enumerate(
        (
            ("ok", "Sağlıklı", "#1a7f37"),
            ("uyari", "Uyarı", "#b54708"),
            ("kritik", "Kritik", "#b42318"),
            ("info", "Bilgi", "#175cd3"),
        )
    ):
        kutu = ttk.Frame(ozet_cerceve, padding=8)
        kutu.grid(row=0, column=i, padx=(0, 10), sticky="nsew")
        ozet_cerceve.columnconfigure(i, weight=1)
        ttk.Label(kutu, text=baslik, font=("Segoe UI", 9)).pack(anchor="w")
        lbl = ttk.Label(kutu, text="0", font=("Segoe UI", 16, "bold"), foreground=renk)
        lbl.pack(anchor="w")
        kartlar[kod] = lbl

    arac = ttk.Frame(app.icerik)
    arac.pack(fill="x", pady=(0, 4))

    # Filtre çubuğu
    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=(0, 8))
    ttk.Label(filtre, text="Önem:").pack(side="left")
    sev_var = tk.StringVar(value="Tümü")
    sev_cb = ttk.Combobox(
        filtre,
        textvariable=sev_var,
        values=["Tümü", "ok", "uyari", "kritik", "info"],
        width=10,
        state="readonly",
    )
    sev_cb.pack(side="left", padx=(4, 12))
    ttk.Label(filtre, text="Modül:").pack(side="left")
    modul_var = tk.StringVar(value="Tümü")
    modul_cb = ttk.Combobox(
        filtre,
        textvariable=modul_var,
        values=["Tümü"],
        width=16,
        state="readonly",
    )
    modul_cb.pack(side="left", padx=(4, 12))
    ttk.Label(filtre, text="Status:").pack(side="left")
    status_var = tk.StringVar(value="Tümü")
    status_cb = ttk.Combobox(
        filtre,
        textvariable=status_var,
        values=["Tümü", "open", "resolved", "ignored"],
        width=10,
        state="readonly",
    )
    status_cb.pack(side="left", padx=(4, 12))

    durum_var = tk.StringVar(value="Hazır.")
    ilerleme = ttk.Progressbar(app.icerik, mode="determinate", maximum=100)
    ilerleme.pack(fill="x", pady=(0, 4))
    ttk.Label(app.icerik, textvariable=durum_var).pack(anchor="w", pady=(0, 8))

    govde = ttk.Frame(app.icerik)
    govde.pack(fill="both", expand=True)
    govde.columnconfigure(0, weight=0, minsize=200)
    govde.columnconfigure(1, weight=1)
    govde.rowconfigure(0, weight=1)

    sol = ttk.Frame(govde, padding=(0, 0, 12, 0))
    sol.grid(row=0, column=0, sticky="nsw")
    ttk.Label(sol, text="Modüller", font=("Segoe UI", 10, "bold")).pack(anchor="w")
    modul_list = tk.Listbox(sol, height=18, exportselection=False, width=28)
    modul_list.pack(fill="y", expand=True, pady=(6, 0))
    for m in ModuleDiagnosticService.modul_listesi():
        modul_list.insert("end", f"{m['ad']}")
    modul_list.selection_set(0)

    sag = ttk.Frame(govde)
    sag.grid(row=0, column=1, sticky="nsew")
    sag.rowconfigure(0, weight=1)
    sag.columnconfigure(0, weight=1)

    kolonlar = (
        "durum",
        "onem",
        "modul",
        "kod",
        "aciklama",
        "kayit",
        "status",
        "otomatik",
        "son",
    )
    tablo = ttk.Treeview(
        sag,
        columns=kolonlar,
        show="headings",
        selectmode="browse",
        height=16,
    )
    basliklar = {
        "durum": ("Durum", 70),
        "onem": ("Önem", 70),
        "modul": ("Modül", 90),
        "kod": ("Hata Kodu", 120),
        "aciklama": ("Açıklama", 280),
        "kayit": ("Kayıt/Belge", 110),
        "status": ("Status", 70),
        "otomatik": ("Oto. Düzeltme", 90),
        "son": ("Son Kontrol", 110),
    }
    for k, (b, w) in basliklar.items():
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    vsb = ttk.Scrollbar(sag, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=vsb.set)
    tablo.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")

    detay = tk.Text(sag, height=5, wrap="word", state="disabled")
    detay.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    son_rapor: dict = {"data": None}
    gosterilen: dict = {"maddeler": []}
    busy = {"v": False}

    def _normalize_maddeler(rapor: dict) -> list[dict]:
        out = []
        for m in rapor.get("maddeler") or []:
            mm = dict(m)
            mm.setdefault("status", "open")
            kod = mm.get("hata_kodu") or ""
            if is_level1(kod, mm.get("repair_level")):
                mm["otomatik_duzeltme"] = mm.get("otomatik_duzeltme") or "Evet (Seviye 1)"
                mm["repair_level"] = 1
            out.append(mm)
        return out

    def _filtreli() -> list[dict]:
        maddeler = _normalize_maddeler(son_rapor["data"] or {})
        sev = sev_var.get()
        mod = modul_var.get()
        st = status_var.get()
        sonuc = []
        for m in maddeler:
            if sev != "Tümü" and (m.get("durum") or "") != sev:
                continue
            if mod != "Tümü" and (m.get("modul") or "") != mod:
                continue
            if st != "Tümü" and (m.get("status") or "open") != st:
                continue
            sonuc.append(m)
        return sonuc

    def _ozet_guncelle(ozet: dict) -> None:
        for kod, lbl in kartlar.items():
            lbl.configure(text=str(int(ozet.get(kod, 0) or 0)))

    def _modul_filtre_guncelle(maddeler: list[dict]) -> None:
        moduller = sorted({(m.get("modul") or "") for m in maddeler if m.get("modul")})
        modul_cb["values"] = ["Tümü"] + moduller
        if modul_var.get() not in modul_cb["values"]:
            modul_var.set("Tümü")

    def _tabloyu_doldur(rapor: dict | None = None) -> None:
        if rapor is not None:
            son_rapor["data"] = rapor
            _modul_filtre_guncelle(_normalize_maddeler(rapor))
            _ozet_guncelle(rapor.get("ozet") or {})
            durum_var.set(
                f"{rapor.get('baslik', 'Rapor')} — {rapor.get('bitis', '')} "
                f"(mutasyon: {'evet' if rapor.get('mutasyon_yapildi') else 'hayır'})"
            )
        for i in tablo.get_children():
            tablo.delete(i)
        gosterilen["maddeler"] = _filtreli()
        for m in gosterilen["maddeler"]:
            tablo.insert(
                "",
                "end",
                values=(
                    m.get("durum", ""),
                    m.get("onem", ""),
                    m.get("modul", ""),
                    m.get("hata_kodu", ""),
                    (m.get("aciklama") or "")[:200],
                    m.get("kayit_belge", ""),
                    m.get("status", "open"),
                    m.get("otomatik_duzeltme", "Hayır"),
                    m.get("son_kontrol", ""),
                ),
                tags=(m.get("durum") or "info",),
            )
        try:
            tablo.tag_configure("kritik", foreground="#b42318")
            tablo.tag_configure("uyari", foreground="#b54708")
            tablo.tag_configure("ok", foreground="#1a7f37")
            tablo.tag_configure("info", foreground="#175cd3")
        except tk.TclError:
            pass

    def _secili_madde() -> dict | None:
        sec = tablo.selection()
        if not sec:
            return None
        idx = tablo.index(sec[0])
        maddeler = gosterilen["maddeler"]
        if idx >= len(maddeler):
            return None
        return maddeler[idx]

    def _detay_goster(_event=None) -> None:
        m = _secili_madde()
        detay.configure(state="normal")
        detay.delete("1.0", "end")
        if not m:
            detay.configure(state="disabled")
            return
        metin = (
            f"{m.get('aciklama', '')}\n\n"
            f"Önerilen: {m.get('onerilen') or '—'}\n"
            f"Teknik: {m.get('teknik') or '—'}\n"
            f"Otomatik: {m.get('otomatik_duzeltme') or 'Hayır'} | Status: {m.get('status') or 'open'}"
        )
        detay.insert("1.0", metin)
        detay.configure(state="disabled")

    def _detay_dialog(_event=None) -> None:
        m = _secili_madde()
        if not m:
            return
        _issue_detail_dialog(app, m)

    tablo.bind("<<TreeviewSelect>>", _detay_goster)
    tablo.bind("<Double-1>", _detay_dialog)

    for w in (sev_cb, modul_cb, status_cb):
        w.bind("<<ComboboxSelected>>", lambda _e: _tabloyu_doldur())

    def _progress(pct: int, msg: str) -> None:
        def _ui():
            ilerleme["value"] = max(0, min(100, pct))
            durum_var.set(msg)

        try:
            app.after(0, _ui)
        except tk.TclError:
            pass

    def _bitis_ok(rapor: dict) -> None:
        busy["v"] = False
        ilerleme["value"] = 100
        if isinstance(rapor, dict) and "maddeler" in rapor:
            _tabloyu_doldur(rapor)
        elif isinstance(rapor, dict) and rapor.get("mesaj"):
            durum_var.set(str(rapor.get("mesaj")))
            messagebox.showinfo("Servis Onarım", str(rapor.get("mesaj")), parent=app)
        for b in dugmeler:
            b.configure(state="normal")

    def _bitis_err(exc: BaseException) -> None:
        busy["v"] = False
        ilerleme["value"] = 0
        durum_var.set("Hata.")
        for b in dugmeler:
            b.configure(state="normal")
        messagebox.showerror("Servis", str(exc), parent=app)

    def _calistir(is_fn) -> None:
        if busy["v"]:
            messagebox.showinfo("Servis", "Bir kontrol zaten çalışıyor.", parent=app)
            return
        if not _kontrol_yetkisi(app):
            return
        busy["v"] = True
        for b in dugmeler:
            b.configure(state="disabled")
        ilerleme["value"] = 0
        durum_var.set("Çalışıyor...")
        arka_planda(app, is_fn, on_ok=_bitis_ok, on_err=_bitis_err)

    def _calistir_onarim(is_fn) -> None:
        if busy["v"]:
            messagebox.showinfo("Servis", "Bir işlem zaten çalışıyor.", parent=app)
            return
        if not _onarim_yetkisi(app):
            return
        busy["v"] = True
        for b in dugmeler:
            b.configure(state="disabled")
        ilerleme["value"] = 0
        durum_var.set("Onarım çalışıyor...")
        arka_planda(app, is_fn, on_ok=_bitis_ok, on_err=_bitis_err)

    def hizli():
        _calistir(lambda: SystemHealthService.run_quick_check(progress=_progress, kaydet=True))

    def ayrintili():
        _calistir(
            lambda: ModuleDiagnosticService.scan_all_modules(progress=_progress, kaydet=True)
        )

    def db_readonly():
        _calistir(
            lambda: DatabaseIntegrityService.run_readonly_check(progress=_progress, kaydet=True)
        )

    def tumunu_tara():
        _calistir(
            lambda: ModuleDiagnosticService.scan_all_modules(progress=_progress, kaydet=True)
        )

    def secili_tara():
        idx = modul_list.curselection()
        if not idx:
            messagebox.showinfo("Seçim", "Sol listeden bir modül seçin.", parent=app)
            return
        kod = ModuleDiagnosticService.modul_listesi()[int(idx[0])]["kod"]
        _calistir(lambda: ModuleDiagnosticService.scan_module(kod, progress=_progress))

    def yeniden():
        if son_rapor["data"] and "Veritabanı" in (son_rapor["data"].get("baslik") or ""):
            db_readonly()
        elif son_rapor["data"] and "Modül Tarama" in (son_rapor["data"].get("baslik") or ""):
            secili_tara()
        else:
            hizli()

    def yedek_al():
        if not oturum.has_permission("yedek_alma") and oturum.role_kod != "YONETICI":
            messagebox.showwarning("Yetki", "Yedek alma yetkiniz yok.", parent=app)
            return
        klasor = filedialog.askdirectory(
            parent=app,
            title="Yedek klasörü seçin",
            initialdir=str(BackupService.yedek_klasoru_onerisi()),
        )
        if not klasor:
            return
        try:
            yol = BackupService.yedek_al(klasor)
            messagebox.showinfo("Yedek", f"Yedek alındı:\n{yol}", parent=app)
            durum_var.set(f"Yedek: {yol}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Yedek", str(exc), parent=app)

    def _madde_satirlari(rapor: dict) -> list[dict]:
        return _normalize_maddeler(rapor)

    def excel_aktar():
        rapor = son_rapor["data"]
        if not rapor:
            messagebox.showinfo("Rapor", "Önce bir kontrol çalıştırın.", parent=app)
            return
        yol = filedialog.asksaveasfilename(
            parent=app,
            title="Excel kaydet",
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")],
            initialfile=f"servis_rapor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        )
        if not yol:
            return
        try:
            maddeler = _madde_satirlari(rapor)
            headers = [
                "Durum",
                "Önem",
                "Modül",
                "Kod",
                "Açıklama",
                "Kayıt",
                "Status",
                "Önerilen",
                "Teknik",
                "Otomatik",
            ]
            if str(yol).lower().endswith(".csv"):
                import csv

                with open(yol, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f, delimiter=";")
                    w.writerow(headers)
                    for m in maddeler:
                        w.writerow(
                            [
                                m.get("durum"),
                                m.get("onem"),
                                m.get("modul"),
                                m.get("hata_kodu"),
                                m.get("aciklama"),
                                m.get("kayit_belge"),
                                m.get("status"),
                                m.get("onerilen"),
                                m.get("teknik"),
                                m.get("otomatik_duzeltme"),
                            ]
                        )
            else:
                from openpyxl import Workbook

                wb = Workbook()
                ws = wb.active
                ws.title = "Servis"
                ws.append(headers)
                for m in maddeler:
                    ws.append(
                        [
                            m.get("durum"),
                            m.get("onem"),
                            m.get("modul"),
                            m.get("hata_kodu"),
                            m.get("aciklama"),
                            m.get("kayit_belge"),
                            m.get("status"),
                            m.get("onerilen"),
                            m.get("teknik"),
                            m.get("otomatik_duzeltme"),
                        ]
                    )
                wb.save(yol)
            messagebox.showinfo("Rapor", f"Kaydedildi:\n{yol}", parent=app)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Rapor", str(exc), parent=app)

    def html_aktar():
        rapor = son_rapor["data"]
        if not rapor:
            messagebox.showinfo("Rapor", "Önce bir kontrol çalıştırın.", parent=app)
            return
        yol = filedialog.asksaveasfilename(
            parent=app,
            title="HTML kaydet",
            defaultextension=".html",
            filetypes=[("HTML", "*.html")],
            initialfile=f"servis_rapor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html",
        )
        if not yol:
            return
        try:
            ozet = rapor.get("ozet") or {}
            rows = []
            for m in _madde_satirlari(rapor):
                rows.append(
                    "<tr>"
                    f"<td>{_esc(m.get('durum'))}</td>"
                    f"<td>{_esc(m.get('onem'))}</td>"
                    f"<td>{_esc(m.get('modul'))}</td>"
                    f"<td>{_esc(m.get('hata_kodu'))}</td>"
                    f"<td>{_esc(m.get('aciklama'))}</td>"
                    f"<td>{_esc(m.get('kayit_belge'))}</td>"
                    f"<td>{_esc(m.get('onerilen'))}</td>"
                    f"<td>{_esc(m.get('teknik'))}</td>"
                    "</tr>"
                )
            html = f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"/>
<title>{_esc(rapor.get('baslik'))}</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}}
h1{{font-size:1.4rem}} table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #ccc;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#f3f4f6}} .meta{{margin-bottom:12px;color:#555}}
@media print{{body{{margin:8mm}}}}
</style></head><body>
<h1>{_esc(rapor.get('baslik'))}</h1>
<div class="meta">Başlangıç: {_esc(rapor.get('baslangic'))} —
Bitiş: {_esc(rapor.get('bitis'))} —
Mutasyon: {'evet' if rapor.get('mutasyon_yapildi') else 'hayır'}<br/>
Özet — OK: {ozet.get('ok',0)}, Uyarı: {ozet.get('uyari',0)},
Kritik: {ozet.get('kritik',0)}, Bilgi: {ozet.get('info',0)}</div>
<table><thead><tr>
<th>Durum</th><th>Önem</th><th>Modül</th><th>Kod</th>
<th>Açıklama</th><th>Kayıt</th><th>Önerilen</th><th>Teknik</th>
</tr></thead><tbody>
{''.join(rows)}
</tbody></table>
<script>/* yazdır: Ctrl+P */</script>
</body></html>"""
            Path(yol).write_text(html, encoding="utf-8")
            if messagebox.askyesno("Rapor", f"Kaydedildi:\n{yol}\n\nTarayıcıda açılsın mı?", parent=app):
                webbrowser.open(Path(yol).as_uri())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Rapor", str(exc), parent=app)

    def onarim_onizle():
        m = _secili_madde()
        if not m:
            messagebox.showinfo(
                "Onarım Önizlemesi",
                "Tablodan bir sorun seçin.\n"
                "Seviye 1: klasör / güvenli ayar / index.\n"
                "Seviye 2: fatura başlık, çek kalan, fiş başlık (yedek zorunlu).\n"
                "Seviye 3: engelli.",
                parent=app,
            )
            return
        kod = m.get("hata_kodu") or ""
        try:
            if m.get("id"):
                oniz = RepairService.repair_preview(issue_id=int(m["id"]), take_backup=False)
            else:
                oniz = RepairService.repair_preview(madde=m, take_backup=False)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Onarım Önizlemesi", str(exc), parent=app)
            return
        if not oniz.get("uygulanabilir") and not is_auto_repairable(
            kod, m.get("repair_level")
        ):
            messagebox.showinfo(
                "Onarım Önizlemesi",
                oniz.get("mesaj") or "Bu hata otomatik onarılamaz (Seviye 3 / manuel).",
                parent=app,
            )
            return
        _preview_dialog(app, oniz)

    def guvenli_duzelt():
        if not _onarim_yetkisi(app):
            return
        oniz = RepairService.apply_all_level1(confirm=False, probe=True)
        adet = int(oniz.get("adet") or 0)
        if adet <= 0:
            messagebox.showinfo("Güvenli Onarım", oniz.get("mesaj") or "Aday yok.", parent=app)
            return
        ozet = "\n".join(
            f"- {p.get('issue_code')}: {p.get('aciklama')}"
            for p in (oniz.get("preview_list") or [])[:12]
        )
        if not messagebox.askyesno(
            "Güvenli Hataları Düzelt",
            f"{adet} Seviye 1 sorun düzeltilecek.\n"
            "Önce CinMuhasebe_ServisOncesi_… yedeği alınır; başarısızsa iptal.\n\n"
            f"{ozet}\n\nDevam edilsin mi?",
            parent=app,
        ):
            return
        yedek_dir = BackupService.yedek_klasoru_onerisi()

        def _is():
            return RepairService.apply_all_level1(
                confirm=True,
                progress=_progress,
                yedek_klasor=yedek_dir,
                probe=True,
            )

        _calistir_onarim(_is)

    def secili_duzelt():
        if not _onarim_yetkisi(app):
            return
        m = _secili_madde()
        if not m:
            messagebox.showinfo("Seçili Onarım", "Tablodan bir sorun seçin.", parent=app)
            return
        kod = m.get("hata_kodu") or ""
        seviye_l1 = is_level1(kod, m.get("repair_level"))
        seviye_l2 = is_level2(kod, m.get("repair_level"))
        if not seviye_l1 and not seviye_l2:
            try:
                oniz_eng = RepairService.repair_preview(madde=m, take_backup=False)
            except Exception:
                oniz_eng = {}
            messagebox.showinfo(
                "Seçili Onarım",
                oniz_eng.get("mesaj")
                or (
                    f"'{kod}' otomatik onarılamaz.\n"
                    "Seviye 3 (birleştirme, kapalı dönem, fiziksel silme, "
                    "rastgele hesap dengeleme) engelli."
                ),
                parent=app,
            )
            return
        try:
            oniz = RepairService.repair_preview(madde=m, take_backup=False)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Seçili Onarım", str(exc), parent=app)
            return
        if not oniz.get("uygulanabilir"):
            messagebox.showinfo(
                "Seçili Onarım",
                oniz.get("mesaj") or "Bu onarım uygulanamaz.",
                parent=app,
            )
            return
        etk = "\n".join(oniz.get("etkilenen_kayitlar") or []) or "—"
        seviye = int(oniz.get("seviye") or (2 if seviye_l2 else 1))
        if seviye >= 2:
            onay_metin = (
                f"Seviye 2 — veri değişir, yedek alındı\n"
                f"Kod: {kod}\n"
                f"Risk: {oniz.get('risk')}\n"
                f"Etkilenen:\n{etk}\n\n"
                "Önce ServisOncesi yedeği alınacak. Onaylıyor musunuz?"
            )
        else:
            onay_metin = (
                f"Seviye 1 onarım: {kod}\n"
                f"Risk: {oniz.get('risk')}\n"
                f"Etkilenen:\n{etk}\n\n"
                "Önce ServisOncesi yedeği alınacak. Onaylıyor musunuz?"
            )
        if not messagebox.askyesno("Seçili Hatayı Düzelt", onay_metin, parent=app):
            return
        yedek_dir = BackupService.yedek_klasoru_onerisi()
        issue_id = m.get("id")

        def _is():
            kwargs = {
                "confirm": True,
                "progress": _progress,
                "yedek_klasor": yedek_dir,
            }
            if issue_id:
                kwargs["issue_id"] = int(issue_id)
            else:
                kwargs["madde"] = m
            if seviye >= 2:
                return RepairService.apply_level2(**kwargs)
            return RepairService.apply_level1(**kwargs)

        _calistir_onarim(_is)

    dugmeler = []
    for metin, cmd in (
        ("Tüm Sistemi Tara", tumunu_tara),
        ("Seçili Modülü Tara", secili_tara),
        ("Hızlı Kontrol", hizli),
        ("Ayrıntılı Kontrol", ayrintili),
        ("DB Salt Okunur", db_readonly),
        ("Yeniden Kontrol Et", yeniden),
        ("Sorun Detayı", lambda: _detay_dialog()),
        ("Yedek Al", yedek_al),
        ("Rapor / Excel", excel_aktar),
        ("HTML / Yazdır", html_aktar),
        ("Onarım Önizlemesi", onarim_onizle),
        ("Güvenli Hataları Düzelt", guvenli_duzelt),
        ("Seçili Hatayı Düzelt", secili_duzelt),
    ):
        b = ttk.Button(arac, text=metin, command=cmd)
        b.pack(side="left", padx=(0, 6), pady=2)
        dugmeler.append(b)


def _esc(val) -> str:
    s = "" if val is None else str(val)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
