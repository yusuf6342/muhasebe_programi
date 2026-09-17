"""Fatura Görseli / PDF / UBL içe aktarım UI."""

from __future__ import annotations

import json
import tkinter as tk
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from fatura_belge_aktarim.document_service import InvoiceDocumentService, KULLANICI_DONUSUM_HATASI
from fatura_belge_aktarim.draft_service import InvoiceDraftService, InvoicePostingService
from database.stok_service import StokService


def _para(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(v)


def fatura_belge_aktarim_goster(app, *, yon: str = "ALIS", geri_fn=None) -> None:
    """Kontrol bekleyen fatura taslakları listesi + yükleme."""
    app._icerigi_temizle()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: fatura_belge_aktarim_goster(app, yon=yon, geri_fn=geri_fn))

    baslik = "FATURA GÖRSELİ / PDF İÇE AKTAR" + (f" ({yon})" if yon else "")
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=baslik, style="Baslik.TLabel").pack(side="left")
    if geri_fn:
        ttk.Button(ust, text="← Geri", command=geri_fn).pack(side="right")

    ttk.Label(
        app.icerik,
        text="UBL XML, PDF veya görsel yükleyin → eşleştirin → kontrol edin → onayla ile kesin fatura oluşturun. "
        "Okuma sonucu doğrudan kesin kayıt olmaz.",
    ).pack(anchor="w", pady=(8, 0))

    arac = ttk.Frame(app.icerik)
    arac.pack(fill="x", pady=(12, 0))

    def yukle():
        yol = filedialog.askopenfilename(
            title="Fatura belgesi seç",
            filetypes=[
                ("Fatura belgeleri", "*.xml *.pdf *.zip *.jpg *.jpeg *.png *.webp"),
                ("UBL XML", "*.xml"),
                ("PDF", "*.pdf"),
                ("Görsel", "*.jpg *.jpeg *.png *.webp"),
                ("ZIP", "*.zip"),
                ("Tümü", "*.*"),
            ],
        )
        if not yol:
            return
        try:
            draft = InvoiceDocumentService.yukleme(yol, menu_yon=yon)
            InvoiceDraftService.otomatik_eslestir(draft.id)
            messagebox.showinfo(
                "Yüklendi",
                f"Taslak #{draft.id} oluşturuldu.\n"
                f"Belge: {draft.belge_no or '-'}\n"
                f"Durum: {draft.durum}\n"
                "Kesin kayıt öncesi kontrol edin.",
                parent=app,
            )
            fatura_belge_kontrol_goster(app, draft.id, geri_fn=lambda: fatura_belge_aktarim_goster(app, yon=yon, geri_fn=geri_fn))
        except ValueError as exc:
            messagebox.showerror("Yükleme", str(exc), parent=app)
        except TypeError as exc:
            # JSON Decimal vb. beklenmeyen kaçaklar
            messagebox.showerror("Yükleme", KULLANICI_DONUSUM_HATASI, parent=app)
        except Exception as exc:  # noqa: BLE001
            if "serializable" in str(exc).lower():
                messagebox.showerror("Yükleme", KULLANICI_DONUSUM_HATASI, parent=app)
            else:
                messagebox.showerror("Yükleme", str(exc), parent=app)

    ttk.Button(arac, text="Belge Yükle…", command=yukle).pack(side="left")
    ttk.Button(arac, text="Yenile", command=lambda: fatura_belge_aktarim_goster(app, yon=yon, geri_fn=geri_fn)).pack(
        side="left", padx=6
    )

    tree = ttk.Treeview(
        app.icerik,
        columns=("id", "durum", "no", "tarih", "cari", "toplam", "kaynak", "ettn"),
        show="headings",
        height=16,
    )
    for c, t, w in (
        ("id", "#", 50),
        ("durum", "Durum", 120),
        ("no", "Fatura no", 120),
        ("tarih", "Tarih", 90),
        ("cari", "Satıcı/Alıcı", 180),
        ("toplam", "Toplam", 90),
        ("kaynak", "Kaynak", 80),
        ("ettn", "ETTN", 200),
    ):
        tree.heading(c, text=t)
        tree.column(c, width=w, anchor="w")
    tree.pack(fill="both", expand=True, pady=(10, 0))

    for d in InvoiceDraftService.listele(yon=yon):
        cari = d.satici_unvan if d.yon == "ALIS" else d.alici_unvan
        tree.insert(
            "",
            "end",
            iid=str(d.id),
            values=(
                d.id,
                d.durum,
                d.belge_no or "",
                d.belge_tarihi or "",
                cari or "",
                _para(d.genel_toplam),
                d.kaynak_turu or "",
                (d.ettn or "")[:36],
            ),
        )

    def ac(_e=None):
        sec = tree.selection()
        if not sec:
            return
        fatura_belge_kontrol_goster(
            app,
            int(sec[0]),
            geri_fn=lambda: fatura_belge_aktarim_goster(app, yon=yon, geri_fn=geri_fn),
        )

    tree.bind("<Double-1>", ac)
    ttk.Button(app.icerik, text="Seçili Taslağı Aç", command=ac).pack(anchor="w", pady=(8, 0))


def gelen_efaturalar_goster(app, geri_fn=None) -> None:
    """Satın Alma > Gelen e-Faturalar — ALIS yönlü taslak listesi."""
    fatura_belge_aktarim_goster(app, yon="ALIS", geri_fn=geri_fn)
    # Başlığı özelleştir
    for w in app.icerik.winfo_children():
        if isinstance(w, ttk.Frame):
            for c in w.winfo_children():
                if isinstance(c, ttk.Label) and "FATURA" in str(c.cget("text")):
                    c.configure(text="GELEN E-FATURALAR")
                    break
            break


def fatura_belge_kontrol_goster(app, draft_id: int, geri_fn=None) -> None:
    from fatura_belge_aktarim.pdf_extractor import SATIR_BULUNAMADI_MESAJI

    data = InvoiceDraftService.getir(draft_id)
    draft = data["draft"]
    satirlar = data["satirlar"]
    dog = InvoiceDraftService.dogrula(draft_id)

    app._icerigi_temizle()
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text=f"FATURA KONTROL — Taslak #{draft_id}", style="Baslik.TLabel").pack(side="left")
    if geri_fn:
        ttk.Button(ust, text="← Liste", command=geri_fn).pack(side="right")

    bilgi = (
        f"Yön: {draft.yon}  |  No: {draft.belge_no or '—'}  |  Tarih: {draft.belge_tarihi or '—'}  |  "
        f"ETTN: {draft.ettn or '—'}  |  Durum: {draft.durum}  |  Kaynak: {draft.kaynak_turu}  |  "
        f"Satır: {len(satirlar)}"
    )
    ttk.Label(app.icerik, text=bilgi).pack(anchor="w", pady=(8, 0))

    try:
        uyarilar = json.loads(draft.uyari_json or "[]")
    except json.JSONDecodeError:
        uyarilar = []
    if uyarilar:
        ttk.Label(app.icerik, text="Uyarılar:\n- " + "\n- ".join(uyarilar), foreground="#a40").pack(
            anchor="w", pady=(6, 0)
        )

    if not satirlar:
        bos = ttk.LabelFrame(app.icerik, text="Satır bulunamadı", padding=10)
        bos.pack(fill="x", pady=(10, 0))
        ttk.Label(bos, text=SATIR_BULUNAMADI_MESAJI, foreground="#a40").pack(anchor="w")

        def _ocr():
            try:
                InvoiceDocumentService.satirlarini_yeniden_oku(draft_id, force_method="ocr", manuel_koru=True)
                InvoiceDraftService.otomatik_eslestir(draft_id)
                fatura_belge_kontrol_goster(app, draft_id, geri_fn)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("OCR", str(exc), parent=app)

        def _xml_sec():
            yol = filedialog.askopenfilename(
                title="UBL XML seç",
                filetypes=[("XML", "*.xml"), ("ZIP", "*.zip"), ("Tümü", "*.*")],
            )
            if not yol:
                return
            try:
                InvoiceDocumentService.satirlarini_yeniden_oku(
                    draft_id, xml_bytes=Path(yol).read_bytes(), manuel_koru=True
                )
                InvoiceDraftService.otomatik_eslestir(draft_id)
                fatura_belge_kontrol_goster(app, draft_id, geri_fn)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("XML", str(exc), parent=app)

        def _manuel_bos():
            _manuel_satir_dialog(app, draft_id, geri_fn)

        def _belge_ac_bos():
            _belgeyi_goruntule(draft_id, app)

        def _iptal():
            if not messagebox.askyesno("İptal", "Taslak iptal edilsin mi?", parent=app):
                return
            InvoiceDraftService.taslak_iptal(draft_id)
            if geri_fn:
                geri_fn()

        bf = ttk.Frame(bos)
        bf.pack(anchor="w", pady=(8, 0))
        ttk.Button(bf, text="OCR ile Yeniden Dene", command=_ocr).pack(side="left")
        ttk.Button(bf, text="XML Dosyası Seç", command=_xml_sec).pack(side="left", padx=6)
        ttk.Button(bf, text="Manuel Satır Ekle", command=_manuel_bos).pack(side="left")
        ttk.Button(bf, text="Belgeyi Aç", command=_belge_ac_bos).pack(side="left", padx=6)
        ttk.Button(bf, text="Taslağı İptal Et", command=_iptal).pack(side="left")

    # Cari
    cari_f = ttk.LabelFrame(app.icerik, text="Cari eşleştirme", padding=8)
    cari_f.pack(fill="x", pady=(10, 0))
    taraf = f"{draft.satici_unvan or ''} / VKN {draft.satici_vkn or ''}" if draft.yon == "ALIS" else (
        f"{draft.alici_unvan or ''} / VKN {draft.alici_vkn or ''}"
    )
    ttk.Label(cari_f, text=f"Belgedeki taraf: {taraf}").pack(anchor="w")
    cari_var = tk.StringVar(value=f"Seçili cari id: {draft.cari_id or 'yok'} ({draft.cari_eslesme_modu or '-'})")
    ttk.Label(cari_f, textvariable=cari_var).pack(anchor="w", pady=(4, 0))

    def cari_sec():
        from database.cari_service import CariService

        tur = "Tedarikçi" if draft.yon == "ALIS" else "Müşteri"
        cariler = CariService.listele(cari_turu=tur, hizli=True)
        win = tk.Toplevel(app)
        win.title("Cari seç")
        win.geometry("520x360")
        lb = tk.Listbox(win)
        lb.pack(fill="both", expand=True, padx=8, pady=8)
        map_id = {}
        for o in cariler:
            c = o["cari"]
            etiket = f"{c.cari_kodu} — {c.unvan}"
            lb.insert("end", etiket)
            map_id[etiket] = c.id

        def tamam():
            sel = lb.curselection()
            if not sel:
                return
            et = lb.get(sel[0])
            InvoiceDraftService.cari_ata(draft_id, map_id[et])
            cari_var.set(f"Seçili cari id: {map_id[et]} (mevcut)")
            win.destroy()

        ttk.Button(win, text="Seç", command=tamam).pack(pady=6)

    ttk.Button(cari_f, text="Mevcut Cariyle Eşleştir…", command=cari_sec).pack(anchor="w", pady=(6, 0))
    ttk.Button(
        cari_f,
        text="Otomatik Eşleştirmeyi Yenile",
        command=lambda: (InvoiceDraftService.otomatik_eslestir(draft_id), fatura_belge_kontrol_goster(app, draft_id, geri_fn)),
    ).pack(anchor="w", pady=(4, 0))

    # Araç çubuğu
    arac = ttk.Frame(app.icerik)
    arac.pack(fill="x", pady=(8, 0))

    def _yeniden(method=None):
        koru = messagebox.askyesno(
            "Yeniden oku",
            "Mevcut manuel düzeltmeler korunsun mu?\n\n"
            "Evet: manuel satırlar kalır, otomatik satırlar yenilenir.\n"
            "Hayır: tüm satırlar silinip yeniden okunur.",
            parent=app,
        )
        try:
            sonuc = InvoiceDocumentService.satirlarini_yeniden_oku(
                draft_id, force_method=method, manuel_koru=bool(koru)
            )
            InvoiceDraftService.otomatik_eslestir(draft_id)
            messagebox.showinfo(
                "Yeniden okuma",
                f"Yöntem: {sonuc.get('kaynak')}\nSatır: {sonuc.get('satir_sayisi')}",
                parent=app,
            )
            fatura_belge_kontrol_goster(app, draft_id, geri_fn)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Yeniden okuma", str(exc), parent=app)

    def _xml_yeniden():
        yol = filedialog.askopenfilename(
            title="UBL XML seç",
            filetypes=[("XML", "*.xml"), ("ZIP", "*.zip"), ("Tümü", "*.*")],
        )
        if not yol:
            return
        koru = messagebox.askyesno("Yeniden oku", "Manuel düzeltmeler korunsun mu?", parent=app)
        try:
            InvoiceDocumentService.satirlarini_yeniden_oku(
                draft_id, xml_bytes=Path(yol).read_bytes(), manuel_koru=bool(koru)
            )
            InvoiceDraftService.otomatik_eslestir(draft_id)
            fatura_belge_kontrol_goster(app, draft_id, geri_fn)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("XML", str(exc), parent=app)

    def _ayrinti():
        try:
            a = InvoiceDocumentService.okuma_ayrintilari(draft_id)
            messagebox.showinfo(
                "Okuma Ayrıntıları",
                f"Kaynak: {a.get('kaynak_turu')}\n"
                f"Satır sayısı: {a.get('satir_sayisi')}\n"
                f"Güven: {a.get('genel_guven')}\n\n"
                f"Özet JSON (kısaltılmış):\n{(a.get('extracted_json') or '')[:800]}",
                parent=app,
            )
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Ayrıntı", str(exc), parent=app)

    for text, cmd in (
        ("Belgeyi Görüntüle", lambda: _belgeyi_goruntule(draft_id, app)),
        ("Satırları Yeniden Oku", lambda: _yeniden(None)),
        ("XML ile Yeniden Oku", _xml_yeniden),
        ("PDF Tablosuyla Yeniden Oku", lambda: _yeniden("pdf_table")),
        ("OCR ile Yeniden Oku", lambda: _yeniden("ocr")),
        ("OCR Ayrıntıları", _ayrinti),
        ("Okuma Ayrıntıları", _ayrinti),
        ("Stokları Otomatik Eşleştir", lambda: (
            InvoiceDraftService.otomatik_eslestir(draft_id),
            fatura_belge_kontrol_goster(app, draft_id, geri_fn),
        )),
    ):
        ttk.Button(arac, text=text, command=cmd).pack(side="left", padx=(0, 4))

    # Satırlar
    satir_f = ttk.LabelFrame(app.icerik, text="Satırlar", padding=4)
    satir_f.pack(fill="both", expand=True, pady=(10, 0))
    cols = ("sira", "aciklama", "mik", "birim", "fiyat", "kdv", "toplam", "stok", "durum")
    tree = ttk.Treeview(satir_f, columns=cols, show="headings", height=10)
    for c, t, w in (
        ("sira", "#", 40),
        ("aciklama", "Açıklama", 200),
        ("mik", "Miktar", 70),
        ("birim", "Birim", 60),
        ("fiyat", "Fiyat", 80),
        ("kdv", "KDV%", 50),
        ("toplam", "Toplam", 80),
        ("stok", "Stok", 90),
        ("durum", "Eşleşme", 100),
    ):
        tree.heading(c, text=t)
        tree.column(c, width=w)
    tree.pack(fill="both", expand=True)
    line_map: dict[str, Any] = {}
    for s in satirlar:
        iid = str(s.id)
        line_map[iid] = s
        tree.insert(
            "",
            "end",
            iid=iid,
            values=(
                s.sira,
                (s.aciklama or "")[:60],
                _para(s.miktar),
                s.birim or "",
                _para(s.birim_fiyat),
                _para(s.kdv_orani),
                _para(s.satir_toplam),
                s.stok_kodu or "",
                s.match_status,
            ),
        )

    def stok_sec():
        sec = tree.selection()
        if not sec:
            return
        line = line_map[sec[0]]
        win = tk.Toplevel(app)
        win.title("Stok seç")
        win.geometry("560x400")
        ara = ttk.Entry(win)
        ara.pack(fill="x", padx=8, pady=8)
        lb = tk.Listbox(win)
        lb.pack(fill="both", expand=True, padx=8)
        map_s = {}

        def doldur(*_a):
            lb.delete(0, "end")
            map_s.clear()
            for stok in StokService.stoklari_ara(ara.get().strip()):
                et = f"{stok.stok_kodu} — {stok.stok_adi}"
                lb.insert("end", et)
                map_s[et] = stok

        ara.bind("<KeyRelease>", doldur)
        doldur()

        def tamam():
            sel = lb.curselection()
            if not sel:
                return
            stok = map_s[lb.get(sel[0])]
            InvoiceDraftService.satir_stok_ata(line.id, stok.id, stok.stok_kodu)
            win.destroy()
            fatura_belge_kontrol_goster(app, draft_id, geri_fn)

        ttk.Button(win, text="Eşleştir", command=tamam).pack(pady=8)

    def satir_duzenle():
        sec = tree.selection()
        if not sec:
            messagebox.showinfo("Satır", "Önce bir satır seçin.", parent=app)
            return
        line = line_map[sec[0]]
        _manuel_satir_dialog(app, draft_id, geri_fn, line=line)

    def satir_sil():
        sec = tree.selection()
        if not sec:
            return
        if not messagebox.askyesno("Sil", "Seçili satır silinsin mi?", parent=app):
            return
        InvoiceDraftService.satir_sil(int(sec[0]))
        fatura_belge_kontrol_goster(app, draft_id, geri_fn)

    satir_btn = ttk.Frame(satir_f)
    satir_btn.pack(fill="x", pady=4)
    ttk.Button(satir_btn, text="Manuel Satır Ekle", command=lambda: _manuel_satir_dialog(app, draft_id, geri_fn)).pack(
        side="left"
    )
    ttk.Button(satir_btn, text="Seçili Satırı Düzenle", command=satir_duzenle).pack(side="left", padx=4)
    ttk.Button(satir_btn, text="Seçili Satırı Sil", command=satir_sil).pack(side="left")
    ttk.Button(satir_btn, text="Seçili Satıra Stok Ata…", command=stok_sec).pack(side="left", padx=4)

    # Doğrulama / kesin kayıt
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(10, 0))

    def dogrula():
        r = InvoiceDraftService.dogrula(draft_id)
        msg = ""
        if r["hatalar"]:
            msg += "Hatalar:\n- " + "\n- ".join(r["hatalar"]) + "\n\n"
        if r["uyarilar"]:
            msg += "Uyarılar:\n- " + "\n- ".join(r["uyarilar"]) + "\n\n"
        msg += f"Hesaplanan: {_para(r['hesaplanan_toplam'])}  Belge: {_para(r['belge_toplam'])}  Fark: {_para(r['fark'])}"
        if r["ok"]:
            messagebox.showinfo("Doğrulama", "Kontroller geçti.\n\n" + msg, parent=app)
        else:
            messagebox.showwarning("Doğrulama", msg, parent=app)

    def kesin():
        r = InvoiceDraftService.dogrula(draft_id)
        if not r["ok"]:
            messagebox.showerror(
                "Kesin kayıt engellendi",
                "Onayla ve Faturayı Oluştur için kontrolleri geçmeniz gerekir.\n\n- "
                + "\n- ".join(r["hatalar"]),
                parent=app,
            )
            return
        if not messagebox.askyesno(
            "Onay",
            "Onayla ve faturayı oluştur?\nBu işlem transaction içinde kesin kayıt yazar.",
            parent=app,
        ):
            return
        try:
            sonuc = InvoicePostingService.kesinlestir(draft_id)
            messagebox.showinfo(
                "Tamam",
                f"{sonuc['tur']} faturası oluşturuldu.\nNo: {sonuc['belge_no']}\nID: {sonuc['fatura_id']}",
                parent=app,
            )
            if geri_fn:
                geri_fn()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Kesin kayıt", str(exc), parent=app)

    ttk.Button(alt, text="Doğrula", command=dogrula).pack(side="left")
    kesin_btn = ttk.Button(alt, text="Onayla ve Faturayı Oluştur", command=kesin)
    kesin_btn.pack(side="left", padx=8)
    if not dog["ok"] or not satirlar:
        kesin_btn.state(["disabled"])


def _belgeyi_goruntule(draft_id: int, app) -> None:
    import os
    import subprocess
    import sys

    yol = InvoiceDocumentService.dosya_yolu(draft_id)
    if not yol or not yol.is_file():
        messagebox.showerror("Belge", "Saklanan belge dosyası bulunamadı.", parent=app)
        return
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(yol))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(yol)])
        else:
            subprocess.Popen(["xdg-open", str(yol)])
    except Exception as exc:  # noqa: BLE001
        messagebox.showerror("Belge", str(exc), parent=app)


def _manuel_satir_dialog(app, draft_id: int, geri_fn, line=None) -> None:
    win = tk.Toplevel(app)
    win.title("Satır düzenle" if line else "Manuel satır ekle")
    win.geometry("420x320")
    alanlar = [
        ("aciklama", "Açıklama", getattr(line, "aciklama", "") or ""),
        ("miktar", "Miktar", str(getattr(line, "miktar", "") or "")),
        ("birim", "Birim", getattr(line, "birim", "") or "ADET"),
        ("birim_fiyat", "Birim fiyat", str(getattr(line, "birim_fiyat", "") or "")),
        ("kdv_orani", "KDV %", str(getattr(line, "kdv_orani", "") or "20")),
        ("satir_toplam", "Satır toplamı", str(getattr(line, "satir_toplam", "") or "")),
    ]
    vars_: dict[str, tk.StringVar] = {}
    for key, label, val in alanlar:
        fr = ttk.Frame(win)
        fr.pack(fill="x", padx=10, pady=4)
        ttk.Label(fr, text=label, width=16).pack(side="left")
        var = tk.StringVar(value=val)
        vars_[key] = var
        ttk.Entry(fr, textvariable=var).pack(side="left", fill="x", expand=True)

    def kaydet():
        veri = {k: v.get() for k, v in vars_.items()}
        if not (veri.get("aciklama") or "").strip():
            messagebox.showerror("Satır", "Açıklama zorunlu.", parent=win)
            return
        try:
            if line is None:
                InvoiceDraftService.satir_ekle(draft_id, veri)
            else:
                InvoiceDraftService.satir_guncelle(line.id, veri)
            win.destroy()
            fatura_belge_kontrol_goster(app, draft_id, geri_fn)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Satır", str(exc), parent=win)

    ttk.Button(win, text="Kaydet", command=kaydet).pack(pady=12)
