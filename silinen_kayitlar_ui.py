"""Silinen Kayıtlar ve Geri Yükleme Merkezi — Tkinter UI."""

from __future__ import annotations

import tempfile
import webbrowser
from datetime import date, datetime
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from database.deleted_record_service import (
    ENTITY_CARI,
    ENTITY_SATIS_FATURA,
    ENTITY_STOK,
    SILME_NEDENLERI,
    AuditDeleteService,
    RestoreService,
    SoftDeleteError,
)
from database.session_manager import oturum
from ui_takvim import takvim_butonu


def _tarih_goster(d) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        return d.strftime("%d.%m.%Y %H:%M")
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d)


def _yetki_merkez(parent) -> bool:
    if oturum.role_kod == "YONETICI":
        return True
    if oturum.has_permission("silinen_kayit_goruntuleme") or oturum.has_permission("silme"):
        return True
    if oturum.has_permission("sistem_ayarlari"):
        return True
    messagebox.showwarning("Yetki", "Silinen kayıtlar merkezine erişim yetkiniz yok.", parent=parent)
    return False


class SilmeOnayDialog(tk.Toplevel):
    """Türkçe silme onay diyaloğu — neden, not, kritik onay, kırmızı Sil."""

    def __init__(
        self,
        parent,
        *,
        baslik: str,
        kayit_ozet: str,
        onay_kodu: str,
        kritik: bool = False,
    ):
        super().__init__(parent)
        self.result: dict | None = None
        self.onay_kodu = onay_kodu
        self.kritik = kritik
        self.title(baslik or "Kayıt Silme Onayı")
        self.geometry("520x420")
        self.transient(parent)
        self.grab_set()
        self.configure(padx=12, pady=10)

        ttk.Label(self, text="Silinecek kayıt", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(self, text=kayit_ozet, wraplength=480).pack(anchor="w", pady=(4, 12))

        ttk.Label(self, text="Silme nedeni *").pack(anchor="w")
        self.neden = ttk.Combobox(self, values=list(SILME_NEDENLERI), state="readonly", width=48)
        self.neden.set(SILME_NEDENLERI[0])
        self.neden.pack(anchor="w", pady=(2, 8))
        self.neden.bind("<<ComboboxSelected>>", lambda _e: self._neden_degisti())

        ttk.Label(self, text="Açıklama / not").pack(anchor="w")
        self.not_txt = tk.Text(self, height=4, width=58, wrap="word")
        self.not_txt.pack(anchor="w", pady=(2, 8))
        self.not_zorunlu = ttk.Label(self, text="", foreground="#a33")
        self.not_zorunlu.pack(anchor="w")

        if kritik:
            ttk.Label(
                self,
                text=f"Kritik silme: onay için şu kodu yazın → {onay_kodu}",
                foreground="#a33",
                font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w", pady=(8, 2))
            self.onay_entry = ttk.Entry(self, width=40)
            self.onay_entry.pack(anchor="w", pady=(0, 8))
        else:
            self.onay_entry = None

        alt = ttk.Frame(self)
        alt.pack(fill="x", pady=(16, 0))
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="right")
        self.sil_btn = tk.Button(
            alt,
            text="Sil",
            bg="#c0392b",
            fg="white",
            activebackground="#922b21",
            activeforeground="white",
            relief="raised",
            padx=16,
            pady=4,
            command=self._onayla,
        )
        self.sil_btn.pack(side="right", padx=(0, 8))
        self._neden_degisti()

    def _neden_degisti(self):
        if self.neden.get() == "Diğer":
            self.not_zorunlu.configure(text="‘Diğer’ için açıklama zorunludur.")
        else:
            self.not_zorunlu.configure(text="")

    def _onayla(self):
        neden = self.neden.get().strip()
        notu = self.not_txt.get("1.0", "end").strip()
        if not neden:
            messagebox.showwarning("Neden", "Silme nedeni seçin.", parent=self)
            return
        if neden == "Diğer" and not notu:
            messagebox.showwarning("Not", "‘Diğer’ seçildiğinde açıklama zorunludur.", parent=self)
            return
        if self.kritik:
            yazilan = (self.onay_entry.get() if self.onay_entry else "").strip()
            if yazilan != self.onay_kodu:
                messagebox.showerror(
                    "Onay",
                    f"Kritik onay kodu eşleşmedi. Beklenen: {self.onay_kodu}",
                    parent=self,
                )
                return
        self.result = {
            "reason": neden,
            "note": notu or None,
            "critical_confirm": self.onay_kodu if self.kritik else None,
        }
        self.destroy()


def silme_onayi_al(parent, *, baslik: str, kayit_ozet: str, onay_kodu: str, kritik: bool = False) -> dict | None:
    dlg = SilmeOnayDialog(
        parent, baslik=baslik, kayit_ozet=kayit_ozet, onay_kodu=onay_kodu, kritik=kritik
    )
    parent.wait_window(dlg)
    return dlg.result


def silinen_kayitlar_goster(app) -> None:
    if not _yetki_merkez(app):
        return
    try:
        AuditDeleteService.schema_hazirla()
    except Exception as e:
        messagebox.showerror("Şema", f"Silinen kayıt tablosu hazırlanamadı:\n{e}", parent=app)
        return

    app._icerigi_temizle()
    for anahtar, dugme in app.menu_dugmeleri.items():
        dugme.configure(style="SeciliMenu.TButton" if anahtar == "sistem" else "Menu.TButton")
    ttk.Label(app.icerik, text="SİLİNEN KAYITLAR VE GERİ YÜKLEME", style="Baslik.TLabel").pack(
        anchor="w"
    )
    ttk.Button(
        app.icerik, text="← Sistem Yönetimi", command=lambda: app.sayfa_goster("sistem")
    ).pack(anchor="w", pady=(8, 8))

    # Özet kartlar
    ozet_frm = ttk.Frame(app.icerik)
    ozet_frm.pack(fill="x", pady=(0, 8))
    ozet_labels: dict[str, ttk.Label] = {}
    for i, (key, title) in enumerate(
        (
            ("total", "Toplam silinen"),
            ("pending_restore", "Geri yüklenebilir"),
            ("restored", "Geri yüklenen"),
            ("critical", "Kritik"),
        )
    ):
        kart = ttk.LabelFrame(ozet_frm, text=title, padding=8)
        kart.grid(row=0, column=i, padx=4, sticky="nsew")
        ozet_frm.columnconfigure(i, weight=1)
        lab = ttk.Label(kart, text="—", font=("Segoe UI", 16, "bold"))
        lab.pack()
        ozet_labels[key] = lab

    # Filtreler
    filtre = ttk.Frame(app.icerik)
    filtre.pack(fill="x", pady=4)
    ttk.Label(filtre, text="Ara:").pack(side="left")
    arama = ttk.Entry(filtre, width=22)
    arama.pack(side="left", padx=4)
    ttk.Label(filtre, text="Modül:").pack(side="left", padx=(8, 0))
    modul = ttk.Combobox(
        filtre, values=("", "cari", "stok", "satis", "finans", "alis"), width=10, state="readonly"
    )
    modul.set("")
    modul.pack(side="left", padx=4)
    ttk.Label(filtre, text="Durum:").pack(side="left", padx=(8, 0))
    durum = ttk.Combobox(
        filtre, values=("", "none", "restored", "failed", "partial"), width=10, state="readonly"
    )
    durum.set("none")
    durum.pack(side="left", padx=4)
    ttk.Label(filtre, text="Başlangıç:").pack(side="left", padx=(8, 0))
    bas = ttk.Entry(filtre, width=12)
    bas.pack(side="left", padx=2)
    takvim_butonu(filtre, bas)
    ttk.Label(filtre, text="Bitiş:").pack(side="left")
    bit = ttk.Entry(filtre, width=12)
    bit.pack(side="left", padx=2)
    takvim_butonu(filtre, bit)

    sayfa_var = tk.IntVar(value=1)
    page_size = 40

    # Tablo
    cerceve = ttk.Frame(app.icerik)
    cerceve.pack(fill="both", expand=True, pady=6)
    kolonlar = ("id", "tarih", "modul", "kod", "baslik", "neden", "silen", "durum", "tip")
    tablo = ttk.Treeview(cerceve, columns=kolonlar, show="headings", selectmode="browse", height=14)
    basliklar = {
        "id": "ID",
        "tarih": "Silinme",
        "modul": "Modül",
        "kod": "Kod",
        "baslik": "Başlık",
        "neden": "Neden",
        "silen": "Silen",
        "durum": "Durum",
        "tip": "Tip",
    }
    gen = {"id": 50, "tarih": 120, "modul": 70, "kod": 110, "baslik": 200, "neden": 140, "silen": 100, "durum": 80, "tip": 70}
    for k in kolonlar:
        tablo.heading(k, text=basliklar[k])
        tablo.column(k, width=gen[k], anchor="w")
    kaydirma = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    tablo.configure(yscrollcommand=kaydirma.set)
    tablo.pack(side="left", fill="both", expand=True)
    kaydirma.pack(side="right", fill="y")

    bilgi = ttk.Label(app.icerik, text="")
    bilgi.pack(anchor="w")

    def _parse_tarih(s: str) -> date | None:
        s = (s or "").strip()
        if not s:
            return None
        for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None

    def yenile():
        try:
            istat = AuditDeleteService.get_deletion_statistics()
            for k, lab in ozet_labels.items():
                lab.configure(text=str(istat.get(k, 0)))
            data = AuditDeleteService.search_deleted_records(
                q=arama.get().strip() or None,
                module=modul.get() or None,
                restore_status=durum.get() or None,
                baslangic=_parse_tarih(bas.get()),
                bitis=_parse_tarih(bit.get()),
                page=sayfa_var.get(),
                page_size=page_size,
            )
            for i in tablo.get_children():
                tablo.delete(i)
            for it in data["items"]:
                tablo.insert(
                    "",
                    "end",
                    iid=str(it["id"]),
                    values=(
                        it["id"],
                        _tarih_goster(it["deleted_at"]),
                        it["module"],
                        it["record_code"] or "",
                        it["record_title"] or "",
                        it["deletion_reason"],
                        it["deleted_by_username"] or "",
                        it["restore_status"],
                        it["deletion_type"],
                    ),
                )
            toplam = data["total"]
            sayfa = data["page"]
            max_s = max(1, (toplam + page_size - 1) // page_size)
            bilgi.configure(text=f"Toplam {toplam} kayıt — sayfa {sayfa}/{max_s}")
        except Exception as e:
            messagebox.showerror("Liste", str(e), parent=app)

    def onceki():
        sayfa_var.set(max(1, sayfa_var.get() - 1))
        yenile()

    def sonraki():
        sayfa_var.set(sayfa_var.get() + 1)
        yenile()

    def secili_id() -> int | None:
        s = tablo.selection()
        return int(s[0]) if s else None

    def detay_ac(_event=None):
        lid = secili_id()
        if lid is None:
            return
        SilinenKayitDetayDialog(app, lid, on_change=yenile)

    def geri_yukle():
        lid = secili_id()
        if lid is None:
            messagebox.showinfo("Seçim", "Kayıt seçin.", parent=app)
            return
        try:
            preview = RestoreService.preview_restore(lid)
        except Exception as e:
            messagebox.showerror("Önizleme", str(e), parent=app)
            return
        uyari = "\n".join(preview.get("warnings") or []) or "Uyarı yok."
        if not messagebox.askyesno(
            "Geri yükle",
            f"Kayıt geri yüklensin mi?\n\n{uyari}",
            parent=app,
        ):
            return
        if not preview.get("can_proceed"):
            messagebox.showwarning("Engellendi", "Geri yükleme koşulları sağlanmıyor.", parent=app)
            return
        try:
            RestoreService.restore_record(lid)
            messagebox.showinfo("Tamam", "Kayıt geri yüklendi.", parent=app)
            yenile()
        except SoftDeleteError as e:
            messagebox.showerror("Geri yükleme", str(e), parent=app)
        except Exception as e:
            messagebox.showerror("Geri yükleme", str(e), parent=app)

    def excel_aktar():
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font
        except ImportError:
            messagebox.showerror("Excel", "openpyxl yüklü değil.", parent=app)
            return
        yol = filedialog.asksaveasfilename(
            parent=app,
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile="silinen_kayitlar.xlsx",
        )
        if not yol:
            return
        try:
            rows = AuditDeleteService.export_deleted_records(
                q=arama.get().strip() or None,
                module=modul.get() or None,
                restore_status=durum.get() or None,
                baslangic=_parse_tarih(bas.get()),
                bitis=_parse_tarih(bit.get()),
            )
            wb = Workbook()
            ws = wb.active
            ws.title = "Silinen"
            headers = list(rows[0].keys()) if rows else ["id", "modul", "kod", "baslik"]
            ws.append(headers)
            for c in ws[1]:
                c.font = Font(bold=True)
            for r in rows:
                ws.append([r.get(h, "") for h in headers])
            wb.save(yol)
            messagebox.showinfo("Excel", f"Kaydedildi:\n{yol}", parent=app)
        except Exception as e:
            messagebox.showerror("Excel", str(e), parent=app)

    def yazdir():
        try:
            rows = AuditDeleteService.export_deleted_records(
                q=arama.get().strip() or None,
                module=modul.get() or None,
                restore_status=durum.get() or None,
            )
            html = [
                "<html><head><meta charset='utf-8'><title>Silinen Kayıtlar</title>",
                "<style>body{font-family:Segoe UI,sans-serif}table{border-collapse:collapse;width:100%}",
                "th,td{border:1px solid #ccc;padding:4px 6px;font-size:12px}th{background:#eee}</style></head><body>",
                f"<h2>Silinen Kayıtlar — {oturum.firma_unvan or ''}</h2>",
                "<table><tr><th>ID</th><th>Tarih</th><th>Modül</th><th>Kod</th><th>Başlık</th><th>Neden</th><th>Durum</th></tr>",
            ]
            for r in rows:
                html.append(
                    "<tr>"
                    + "".join(
                        f"<td>{r.get(k, '')}</td>"
                        for k in ("id", "tarih", "modul", "kod", "baslik", "neden", "durum")
                    )
                    + "</tr>"
                )
            html.append("</table></body></html>")
            path = tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8")
            path.write("\n".join(html))
            path.close()
            webbrowser.open(path.name)
        except Exception as e:
            messagebox.showerror("Yazdır", str(e), parent=app)

    def log_temizle():
        if oturum.role_kod != "YONETICI":
            messagebox.showwarning(
                "Yetki",
                "Eski log temizliği yalnızca yönetici içindir.",
                parent=app,
            )
            return
        dlg = tk.Toplevel(app)
        dlg.title("Eski Log Temizliği")
        dlg.geometry("420x260")
        dlg.transient(app)
        dlg.grab_set()
        ttk.Label(
            dlg,
            text=(
                "Yalnızca geri yüklenmiş veya iptal (geri yüklenemez) loglar silinir.\n"
                "Aktif soft-delete kayıtları silinmez. Önce yedek alın."
            ),
            wraplength=380,
        ).pack(anchor="w", padx=12, pady=8)
        frm = ttk.Frame(dlg)
        frm.pack(fill="x", padx=12)
        ttk.Label(frm, text="Bu tarihten önce:").grid(row=0, column=0, sticky="w")
        bitis_e = ttk.Entry(frm, width=14)
        bitis_e.grid(row=0, column=1, padx=4)
        bitis_e.insert(0, date.today().strftime("%d.%m.%Y"))
        takvim_butonu(frm, bitis_e)
        ttk.Label(frm, text="Onay (SİL yazın):").grid(row=1, column=0, sticky="w", pady=8)
        onay_e = ttk.Entry(frm, width=14)
        onay_e.grid(row=1, column=1, padx=4, pady=8)
        adet_lab = ttk.Label(dlg, text="Aday: —")
        adet_lab.pack(anchor="w", padx=12)

        def aday_say():
            try:
                bd = _parse_tarih(bitis_e.get())
                if not bd:
                    raise SoftDeleteError("Geçerli tarih girin.")
                n = AuditDeleteService.count_purge_candidates(before_date=bd)
                adet_lab.configure(text=f"Aday: {n} kayıt")
                return bd, n
            except SoftDeleteError as e:
                messagebox.showerror("Temizlik", str(e), parent=dlg)
                return None, None
            except Exception as e:
                messagebox.showerror("Temizlik", str(e), parent=dlg)
                return None, None

        def calistir():
            bd, n = aday_say()
            if bd is None:
                return
            if n == 0:
                messagebox.showinfo("Temizlik", "Silinecek aday yok.", parent=dlg)
                return
            if not messagebox.askyesno(
                "Onay",
                f"{n} log kalıcı silinecek. Devam?",
                parent=dlg,
            ):
                return
            try:
                sonuc = AuditDeleteService.purge_old_logs(
                    before_date=bd,
                    confirm_phrase=onay_e.get(),
                    expected_count=n,
                )
                messagebox.showinfo(
                    "Tamam",
                    f"{sonuc['purged']} log temizlendi.\nAudit log #{sonuc['audit_log_id']}",
                    parent=dlg,
                )
                dlg.destroy()
                yenile()
            except SoftDeleteError as e:
                messagebox.showerror("Temizlik", str(e), parent=dlg)
            except Exception as e:
                messagebox.showerror("Temizlik", str(e), parent=dlg)

        bf = ttk.Frame(dlg)
        bf.pack(fill="x", padx=12, pady=12)
        ttk.Button(bf, text="Aday Say", command=aday_say).pack(side="left")
        ttk.Button(bf, text="Temizle", command=calistir).pack(side="right", padx=4)
        ttk.Button(bf, text="Vazgeç", command=dlg.destroy).pack(side="right")

    btn = ttk.Frame(app.icerik)
    btn.pack(fill="x", pady=6)
    ttk.Button(btn, text="Yenile", command=yenile).pack(side="left")
    ttk.Button(btn, text="Filtrele", command=lambda: (sayfa_var.set(1), yenile())).pack(side="left", padx=4)
    ttk.Button(btn, text="Önceki", command=onceki).pack(side="left", padx=4)
    ttk.Button(btn, text="Sonraki", command=sonraki).pack(side="left")
    ttk.Button(btn, text="Detay", command=detay_ac).pack(side="left", padx=8)
    ttk.Button(btn, text="Geri Yükle", command=geri_yukle).pack(side="left")
    if oturum.role_kod == "YONETICI":
        ttk.Button(btn, text="Eski Log Temizle", command=log_temizle).pack(side="left", padx=8)
    ttk.Button(btn, text="Excel", command=excel_aktar).pack(side="right")
    ttk.Button(btn, text="Yazdır", command=yazdir).pack(side="right", padx=4)

    tablo.bind("<Double-1>", detay_ac)
    yenile()


class SilinenKayitDetayDialog(tk.Toplevel):
    def __init__(self, parent, log_id: int, on_change=None):
        super().__init__(parent)
        self.log_id = log_id
        self.on_change = on_change
        self.title(f"Silinen Kayıt #{log_id}")
        self.geometry("780x560")
        self.transient(parent)
        self.grab_set()

        try:
            self.detay = AuditDeleteService.get_deleted_record_detail(log_id)
        except Exception as e:
            messagebox.showerror("Detay", str(e), parent=parent)
            self.destroy()
            return

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        def _metin_sekme(ad: str, icerik: str):
            frm = ttk.Frame(nb)
            nb.add(frm, text=ad)
            txt = tk.Text(frm, wrap="word")
            txt.pack(fill="both", expand=True)
            txt.insert("1.0", icerik)
            txt.configure(state="disabled")

        d = self.detay
        genel = (
            f"ID: {d['id']}\n"
            f"Firma ID: {d['company_id']}\n"
            f"Modül: {d['module']}\n"
            f"Tür: {d['entity_type']}\n"
            f"Kayıt ID: {d['record_id']}\n"
            f"Kod: {d['record_code']}\n"
            f"Başlık: {d['record_title']}\n"
            f"Silme tipi: {d['deletion_type']}\n"
            f"Neden: {d['deletion_reason']}\n"
            f"Not: {d['deletion_note'] or ''}\n"
            f"Silen: {d['deleted_by_username']} ({d['deleted_by_user_id']})\n"
            f"Tarih: {_tarih_goster(d['deleted_at'])}\n"
            f"Kritik: {d['is_critical']}\n"
            f"Geri yüklenebilir: {d['can_restore']}\n"
            f"Durum: {d['restore_status']}\n"
            f"Hash OK: {d.get('integrity_ok')}\n"
            f"Hash: {d.get('integrity_hash')}\n"
        )
        _metin_sekme("Genel", genel)
        import json

        _metin_sekme("Silinen Veriler", json.dumps(d.get("snapshot") or {}, ensure_ascii=False, indent=2))
        _metin_sekme("Bağlı", json.dumps(d.get("related") or [], ensure_ascii=False, indent=2))
        etki = {
            "muhasebe": d.get("accounting_impact"),
            "stok": d.get("stock_impact"),
            "cari": d.get("cari_impact"),
        }
        _metin_sekme("Muhasebe/Stok/Cari etki", json.dumps(etki, ensure_ascii=False, indent=2, default=str))
        gy = (
            f"Durum: {d['restore_status']}\n"
            f"Geri yükleyen: {d.get('restored_by_username')}\n"
            f"Tarih: {_tarih_goster(d.get('restored_at'))}\n"
            f"Not: {d.get('restore_note') or ''}\n"
        )
        _metin_sekme("Geri Yükleme", gy)
        ham = {k: d.get(k) for k in d if k not in ("snapshot",)}
        _metin_sekme("Ham JSON", json.dumps(ham, ensure_ascii=False, indent=2, default=str))

        alt = ttk.Frame(self)
        alt.pack(fill="x", padx=8, pady=8)

        def geri():
            try:
                preview = RestoreService.preview_restore(self.log_id)
                if not preview.get("can_proceed"):
                    messagebox.showwarning(
                        "Engellendi",
                        "\n".join(preview.get("warnings") or ["Koşullar sağlanmıyor."]),
                        parent=self,
                    )
                    return
                if not messagebox.askyesno("Geri yükle", "Kayıt geri yüklensin mi?", parent=self):
                    return
                RestoreService.restore_record(self.log_id)
                messagebox.showinfo("Tamam", "Geri yüklendi.", parent=self)
                if self.on_change:
                    self.on_change()
                self.destroy()
            except SoftDeleteError as e:
                messagebox.showerror("Geri yükleme", str(e), parent=self)
            except Exception as e:
                messagebox.showerror("Geri yükleme", str(e), parent=self)

        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        ttk.Button(alt, text="Geri Yükle", command=geri).pack(side="right", padx=8)


def cari_soft_sil(parent, cari) -> bool:
    """Cari soft-delete; True ise başarılı."""
    kritik = True  # her zaman kod onayı
    sonuc = silme_onayi_al(
        parent,
        baslik="Cari Silme",
        kayit_ozet=f"{cari.cari_kodu} — {cari.unvan}",
        onay_kodu=cari.cari_kodu,
        kritik=kritik,
    )
    if not sonuc:
        return False
    try:
        AuditDeleteService.delete_record(
            ENTITY_CARI,
            cari.id,
            reason=sonuc["reason"],
            note=sonuc["note"],
            critical_confirm=sonuc.get("critical_confirm"),
        )
        messagebox.showinfo("Silindi", "Cari soft-delete ile silindi. Merkezden geri yüklenebilir.", parent=parent)
        return True
    except SoftDeleteError as e:
        messagebox.showerror("Silinemedi", str(e), parent=parent)
    except Exception as e:
        messagebox.showerror("Silinemedi", str(e), parent=parent)
    return False


def stok_soft_sil(parent, stok) -> bool:
    sonuc = silme_onayi_al(
        parent,
        baslik="Stok Kartı Silme",
        kayit_ozet=f"{stok.stok_kodu} — {stok.stok_adi}",
        onay_kodu=stok.stok_kodu,
        kritik=True,
    )
    if not sonuc:
        return False
    try:
        AuditDeleteService.delete_record(
            ENTITY_STOK,
            stok.id,
            reason=sonuc["reason"],
            note=sonuc["note"],
            critical_confirm=sonuc.get("critical_confirm"),
        )
        messagebox.showinfo("Silindi", "Stok kartı soft-delete ile silindi.", parent=parent)
        return True
    except SoftDeleteError as e:
        messagebox.showerror("Silinemedi", str(e), parent=parent)
    except Exception as e:
        messagebox.showerror("Silinemedi", str(e), parent=parent)
    return False


def fatura_taslak_sil(parent, fatura) -> bool:
    if (fatura.durum or "").upper() != "TASLAK" or getattr(fatura, "onaylandi", False):
        messagebox.showwarning(
            "Silme",
            "Yalnızca taslak faturalar silinebilir. Onaylı faturalar için İptal kullanın.",
            parent=parent,
        )
        return False
    sonuc = silme_onayi_al(
        parent,
        baslik="Taslak Fatura Silme",
        kayit_ozet=f"{fatura.fatura_no} — durum: {fatura.durum}",
        onay_kodu=fatura.fatura_no,
        kritik=True,
    )
    if not sonuc:
        return False
    try:
        AuditDeleteService.delete_record(
            ENTITY_SATIS_FATURA,
            fatura.id,
            reason=sonuc["reason"],
            note=sonuc["note"],
            critical_confirm=sonuc.get("critical_confirm"),
        )
        messagebox.showinfo("Silindi", "Taslak fatura soft-delete ile silindi.", parent=parent)
        return True
    except SoftDeleteError as e:
        messagebox.showerror("Silinemedi", str(e), parent=parent)
    except Exception as e:
        messagebox.showerror("Silinemedi", str(e), parent=parent)
    return False
