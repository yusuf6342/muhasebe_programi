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

_MATCH_ETIKET = {
    "eslesti": "eşleşti",
    "yeni_stok": "Yeni kart ile eşleştirildi",
    "bulunamadi": "bulunamadı",
    "secim_gerekli": "seçim gerekli",
    "hizmet": "hizmet",
    "gider": "gider",
    "haric": "hariç",
    "bekliyor": "bekliyor",
}

_BIRIM_ESLEME = {
    "ADET": "Adet",
    "AD": "Adet",
    "ADT": "Adet",
    "AD.": "Adet",
    "PCS": "Adet",
    "PIECE": "Adet",
    "C62": "Adet",
    "KG": "Kg",
    "KGM": "Kg",
    "KILOGRAM": "Kg",
    "M": "Metre",
    "MTR": "Metre",
    "MT": "Metre",
    "METRE": "Metre",
    "KOLİ": "Koli",
    "KOLI": "Koli",
    "PAKET": "Paket",
    "PKT": "Paket",
    "TORBA": "Torba",
    "BOY": "Boy",
    "TOP": "Top",
}

_MAL_KABUL_ETIKET = {
    "mal_geldi": "Mal Geldi",
    "mal_bekleniyor": "Mal Bekleniyor",
    "irsaliyeden": "İrsaliyeden Alındı",
}


def _pdf_onizleme_kur(parent, draft_id: int) -> None:
    """Solda sayfa seçmeli PDF/görsel önizleme."""
    import base64
    from io import BytesIO

    from fatura_belge_aktarim.pdf_preview import sayfa_png_bytes, sayfa_sayisi

    cerceve = ttk.LabelFrame(parent, text="Kaynak belge", padding=4)
    cerceve.pack(fill="both", expand=True)
    yol = InvoiceDocumentService.dosya_yolu(draft_id)
    if not yol or not yol.is_file():
        ttk.Label(cerceve, text="Saklanan belge bulunamadı.", foreground="#a40").pack(anchor="w")
        return

    n = sayfa_sayisi(yol) or 1
    sayfa_var = tk.IntVar(value=1)
    nav = ttk.Frame(cerceve)
    nav.pack(fill="x")
    ttk.Label(nav, text=(yol.name[:42] + "…") if len(yol.name) > 43 else yol.name).pack(
        side="left", anchor="w"
    )

    canvas = tk.Canvas(cerceve, background="#ececec", highlightthickness=0, width=420)
    sy = ttk.Scrollbar(cerceve, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=sy.set)
    sy.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    img_holder: list[Any] = []
    _son_w = {"v": 0}

    def _photo_from_png(png: bytes):
        try:
            from PIL import Image, ImageTk

            im = Image.open(BytesIO(png))
            return ImageTk.PhotoImage(im)
        except Exception:
            pass
        try:
            return tk.PhotoImage(data=base64.b64encode(png))
        except tk.TclError:
            import tempfile

            tmp = Path(tempfile.gettempdir()) / f"cin_inv_prev_{draft_id}.png"
            tmp.write_bytes(png)
            return tk.PhotoImage(file=str(tmp))

    def _goster(*_a):
        s = max(1, min(int(sayfa_var.get() or 1), n))
        sayfa_var.set(s)
        sayfa_lbl.configure(text=f"Sayfa {s} / {n}")
        canvas.update_idletasks()
        w = max(200, int(canvas.winfo_width() or 420) - 16)
        force = not _a
        if not force and abs(w - _son_w["v"]) < 12 and img_holder:
            return
        _son_w["v"] = w
        png = sayfa_png_bytes(yol, s - 1, genislik=w)
        canvas.delete("all")
        img_holder.clear()
        if not png:
            canvas.create_text(
                12, 12, anchor="nw", text="Önizleme üretilemedi.\n«Dışarıda Aç» ile açın."
            )
            canvas.configure(scrollregion=(0, 0, 200, 80))
            return
        try:
            photo = _photo_from_png(png)
        except Exception:
            canvas.create_text(12, 12, anchor="nw", text="PNG gösterilemedi.")
            canvas.configure(scrollregion=(0, 0, 200, 80))
            return
        img_holder.append(photo)
        canvas.create_image(4, 4, anchor="nw", image=photo)
        canvas.configure(scrollregion=(0, 0, photo.width() + 8, photo.height() + 8))

    def _once():
        sayfa_var.set(max(1, int(sayfa_var.get()) - 1))
        _goster()

    def _sonra():
        sayfa_var.set(min(n, int(sayfa_var.get()) + 1))
        _goster()

    ttk.Button(nav, text="◀", width=3, command=_once).pack(side="right")
    sayfa_lbl = ttk.Label(nav, text="")
    sayfa_lbl.pack(side="right", padx=4)
    ttk.Button(nav, text="▶", width=3, command=_sonra).pack(side="right")
    ttk.Button(
        nav,
        text="Dışarıda Aç",
        command=lambda: _belgeyi_goruntule(draft_id, parent.winfo_toplevel()),
    ).pack(side="right", padx=(0, 6))
    canvas.bind("<Configure>", _goster)
    parent.after(80, _goster)


def _para(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(v)


def _eslesme_etiket(status: str | None) -> str:
    if not status:
        return ""
    return _MATCH_ETIKET.get(status, status)


def _birim_esle(ham: str | None) -> tuple[str | None, bool]:
    """(eşlenen birim veya None, sözlükte tanındı mı)."""
    raw = " ".join(str(ham or "").split())
    if not raw:
        return None, True
    from stok_ui import BIRIM_SECENEKLERI

    for ad in BIRIM_SECENEKLERI:
        if ad.casefold() == raw.casefold():
            return ad, True
    mapped = _BIRIM_ESLEME.get(raw.upper())
    if mapped:
        return mapped, True
    return None, False


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


def fatura_belge_kontrol_goster(app, draft_id: int, geri_fn=None, *, secili_satir_id: int | None = None) -> None:
    from fatura_belge_aktarim.pdf_extractor import SATIR_BULUNAMADI_MESAJI

    data = InvoiceDraftService.getir(draft_id)
    draft = data["draft"]
    satirlar = data["satirlar"]
    dog = InvoiceDraftService.dogrula(draft_id)

    def _yenile(secili: int | None = None):
        fatura_belge_kontrol_goster(app, draft_id, geri_fn, secili_satir_id=secili)

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

    # Sol: kaynak PDF/görsel — sağ: düzenlenebilir kontrol formu
    govde = ttk.Panedwindow(app.icerik, orient=tk.HORIZONTAL)
    govde.pack(fill="both", expand=True, pady=(8, 0))
    sol = ttk.Frame(govde, padding=2)
    form = ttk.Frame(govde, padding=2)
    govde.add(sol, weight=1)
    govde.add(form, weight=2)
    _pdf_onizleme_kur(sol, draft_id)

    if not satirlar:
        bos = ttk.LabelFrame(form, text="Satır bulunamadı", padding=10)
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
    cari_f = ttk.LabelFrame(form, text="Cari eşleştirme", padding=8)
    cari_f.pack(fill="x", pady=(4, 0))
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
        win.geometry("560x420")
        win.transient(app)
        ara_var = tk.StringVar()
        ttk.Entry(win, textvariable=ara_var).pack(fill="x", padx=8, pady=(8, 4))
        lb = tk.Listbox(win)
        lb.pack(fill="both", expand=True, padx=8, pady=4)
        map_id: dict[str, int] = {}

        def _doldur(*_a):
            lb.delete(0, "end")
            map_id.clear()
            q = (ara_var.get() or "").strip().lower()
            for o in cariler:
                c = o["cari"]
                etiket = f"{c.cari_kodu} — {c.unvan}"
                if q and q not in etiket.lower() and q not in (c.vergi_numarasi or "").lower():
                    continue
                lb.insert("end", etiket)
                map_id[etiket] = c.id

        ara_var.trace_add("write", _doldur)
        _doldur()

        def tamam():
            sel = lb.curselection()
            if not sel:
                return
            et = lb.get(sel[0])
            cid = map_id[et]
            InvoiceDraftService.cari_ata(draft_id, cid)
            win.destroy()
            fatura_belge_kontrol_goster(app, draft_id, geri_fn)

        ttk.Button(win, text="Seç", command=tamam).pack(pady=6)

    def yeni_cari_karti_ac():
        from database.access import yetki_var
        from cari_kart_ui import CariDialog

        if not yetki_var("cari_duzenleme", "cari_ekleme", "YONETICI"):
            messagebox.showerror(
                "Yetki",
                "Yeni cari kartı açmak için cari düzenleme yetkiniz yok. Mevcut cari seçebilirsiniz.",
                parent=app,
            )
            return
        tur = "Tedarikçi" if draft.yon == "ALIS" else "Müşteri"
        unvan = (draft.satici_unvan if draft.yon == "ALIS" else draft.alici_unvan) or ""
        vkn = (draft.satici_vkn if draft.yon == "ALIS" else draft.alici_vkn) or ""
        dlg = CariDialog(app, cari=None, cari_turu=tur)
        if getattr(dlg, "_vazgecildi", False):
            return
        for alan, deger in (("unvan", unvan), ("vergi_numarasi", vkn)):
            w = dlg.degerler.get(alan)
            if w is None or not deger:
                continue
            try:
                w.delete(0, "end")
                w.insert(0, deger)
            except tk.TclError:
                pass
        app.wait_window(dlg)
        cari = getattr(dlg, "result", None)
        if not cari:
            return
        InvoiceDraftService.cari_ata(draft_id, int(cari.id))
        messagebox.showinfo(
            "Cari kaydedildi",
            f"'{cari.unvan}' kartı oluşturuldu ve bu taslağa bağlandı.\n"
            "Faturadan vazgeçseniz bile cari kartı silinmez.",
            parent=app,
        )
        fatura_belge_kontrol_goster(app, draft_id, geri_fn)

    cari_btn_satir = ttk.Frame(cari_f)
    cari_btn_satir.pack(anchor="w", pady=(6, 0))
    ttk.Button(cari_btn_satir, text="Cari Seç…", command=cari_sec).pack(side="left")
    ttk.Button(cari_btn_satir, text="Yeni Cari Kartı Aç", command=yeni_cari_karti_ac).pack(
        side="left", padx=6
    )
    ttk.Button(
        cari_f,
        text="Otomatik Eşleştirmeyi Yenile",
        command=lambda: (InvoiceDraftService.otomatik_eslestir(draft_id), fatura_belge_kontrol_goster(app, draft_id, geri_fn)),
    ).pack(anchor="w", pady=(4, 0))

    # Araç çubuğu
    arac = ttk.Frame(form)
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
    satir_f = ttk.LabelFrame(form, text="Satırlar", padding=4)
    satir_f.pack(fill="both", expand=True, pady=(10, 0))
    cols = ("sira", "aciklama", "mik", "teslim", "birim", "fiyat", "kdv", "toplam", "stok", "irs", "durum")
    tree = ttk.Treeview(satir_f, columns=cols, show="headings", height=10)
    for c, t, w in (
        ("sira", "#", 36),
        ("aciklama", "Açıklama", 160),
        ("mik", "Miktar", 64),
        ("teslim", "Teslim", 64),
        ("birim", "Birim", 50),
        ("fiyat", "Fiyat", 70),
        ("kdv", "KDV%", 44),
        ("toplam", "Toplam", 70),
        ("stok", "Stok", 80),
        ("irs", "İrs.satır", 64),
        ("durum", "Eşleşme", 140),
    ):
        tree.heading(c, text=t)
        tree.column(c, width=w)
    tree.pack(fill="both", expand=True)
    line_map: dict[str, Any] = {}
    for s in satirlar:
        iid = str(s.id)
        line_map[iid] = s
        teslim_goster = (
            _para(s.teslim_miktar)
            if getattr(s, "teslim_miktar", None) is not None
            else _para(s.miktar)
        )
        tree.insert(
            "",
            "end",
            iid=iid,
            values=(
                s.sira,
                (s.aciklama or "")[:60],
                _para(s.miktar),
                teslim_goster,
                s.birim or "",
                _para(s.birim_fiyat),
                _para(s.kdv_orani),
                _para(s.satir_toplam),
                s.stok_kodu or "",
                getattr(s, "irsaliye_satiri_id", None) or "",
                _eslesme_etiket(s.match_status),
            ),
        )
    if secili_satir_id is not None and str(secili_satir_id) in line_map:
        tree.selection_set(str(secili_satir_id))
        tree.see(str(secili_satir_id))
        tree.focus(str(secili_satir_id))

    def _secili_line():
        sec = tree.selection()
        if not sec:
            return None
        return line_map.get(sec[0])

    def stok_sec(line=None):
        line = line or _secili_line()
        if not line:
            messagebox.showinfo("Stok ata", "Önce bir satır seçin.", parent=app)
            return
        line_id = int(line.id)
        win = tk.Toplevel(app)
        win.title("Stok seç")
        win.geometry("560x400")
        win.transient(app)
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
            InvoiceDraftService.satir_stok_ata(line_id, stok.id, stok.stok_kodu)
            win.destroy()
            _yenile(line_id)

        ttk.Button(win, text="Eşleştir", command=tamam).pack(pady=8)

    def _satiri_stoka_bagla(line_id: int, stok, *, yeni_kart: bool = False) -> bool:
        try:
            InvoiceDraftService.satir_stok_ata(
                line_id,
                int(stok.id),
                stok.stok_kodu,
                match_status="yeni_stok" if yeni_kart else "eslesti",
            )
            return True
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(
                "Satıra bağlama",
                "Stok kartı kaydedildi ancak satıra bağlanamadı.\n"
                f"{exc}\n\n"
                f"Kart: {getattr(stok, 'stok_kodu', '')} — {getattr(stok, 'stok_adi', '')}\n"
                "Yeniden denediğinizde aynı kartı seçin; ikinci kart açmayın.",
                parent=app,
            )
            return False

    def _adaylari_topla(line) -> list[dict[str, Any]]:
        from fatura_belge_aktarim.matching import ProductMatchingService

        adaylar: list[dict[str, Any]] = []
        try:
            sonuc = ProductMatchingService.satir_eslestir(line, tedarikci_cari_id=draft.cari_id)
            for a in sonuc.get("adaylar") or []:
                adaylar.append(a)
            if sonuc.get("status") == "eslesti" and sonuc.get("stok_id"):
                adaylar.insert(
                    0,
                    {
                        "stok_id": sonuc["stok_id"],
                        "stok_kodu": sonuc.get("stok_kodu"),
                        "stok_adi": "",
                        "guven": sonuc.get("guven"),
                        "neden": sonuc.get("neden"),
                    },
                )
        except Exception:
            pass
        # Barkod / ad ile ek arama
        gorulen = {int(a["stok_id"]) for a in adaylar if a.get("stok_id")}
        q = (line.barkod or line.alici_urun_kodu or line.aciklama or "").strip()
        if q:
            try:
                for stok in StokService.stoklari_ara(q, limit=8):
                    if int(stok.id) in gorulen:
                        continue
                    adaylar.append(
                        {
                            "stok_id": stok.id,
                            "stok_kodu": stok.stok_kodu,
                            "stok_adi": stok.stok_adi,
                            "guven": Decimal("40"),
                            "neden": "arama",
                        }
                    )
                    gorulen.add(int(stok.id))
            except Exception:
                pass
        return adaylar

    def _yeni_stok_formu_ac(line):
        from database.access import yetki_var
        from stok_ui import StokKartiDialog

        if not yetki_var("stok_duzenleme"):
            messagebox.showerror(
                "Yetki",
                "Yeni stok kartı açmak için stok düzenleme yetkiniz yok.",
                parent=app,
            )
            return
        line_id = int(line.id)
        birim, birim_tanindi = _birim_esle(line.birim)
        if line.birim and not birim_tanindi:
            messagebox.showinfo(
                "Birim",
                f"Fatura birimi tanınmadı: “{line.birim}”.\n"
                "Stok kartında birimi sözlükten seçin. "
                "Koli/paket Adet ile aynı kabul edilmez.",
                parent=app,
            )
        barkod_oneri = (line.barkod or "").strip() or None
        # Tedarikçi kodunu iç stok kodu yapma; yalnız güvenilir barkod öner
        ref = (
            f"Fatura referansı (kart açılışında stok/maliyet hareketi yazılmaz): "
            f"miktar={_para(line.miktar)} {line.birim or ''} · "
            f"birim fiyat={_para(line.birim_fiyat)} · KDV%={_para(line.kdv_orani)}. "
            "Satış fiyatı ve açılış stoğu oluşturulmaz."
        )
        baslangic = {
            "stok_adi": (line.aciklama or "").strip() or None,
            "birim": birim or "Adet",
            "kdv_orani": line.kdv_orani,
            "barkod": barkod_oneri,
            "referans_bilgi": ref,
        }
        dlg = StokKartiDialog(app, baslangic={k: v for k, v in baslangic.items() if v is not None})
        app.wait_window(dlg)
        stok = getattr(dlg, "result", None)
        if not stok:
            return
        if _satiri_stoka_bagla(line_id, stok, yeni_kart=True):
            _yenile(line_id)

    def yeni_stok_karti_ac(line=None):
        from database.access import yetki_var

        line = line or _secili_line()
        if not line:
            messagebox.showinfo("Yeni stok kartı", "Önce bir satır seçin.", parent=app)
            return
        if line.match_status in {"hizmet", "gider", "haric"}:
            messagebox.showinfo(
                "Yeni stok kartı",
                "Bu satır hizmet/gider/hariç işaretli; stok kartı gerekmez.",
                parent=app,
            )
            return
        if not yetki_var("stok_duzenleme"):
            messagebox.showerror(
                "Yetki",
                "Yeni stok kartı açmak için stok düzenleme yetkiniz yok.",
                parent=app,
            )
            return
        line_id = int(line.id)
        adaylar = _adaylari_topla(line)
        win = tk.Toplevel(app)
        win.title("Olası stok eşleşmeleri")
        win.geometry("620x420")
        win.transient(app)
        win.grab_set()
        ttk.Label(
            win,
            text=(
                f"Satır {line.sira}: {(line.aciklama or '')[:80]}\n"
                "Önce mevcut kartları kontrol edin. Uygun kart yoksa yeni kart açın."
            ),
            wraplength=580,
            justify="left",
        ).pack(anchor="w", padx=10, pady=(10, 4))
        ara = ttk.Entry(win)
        ara.pack(fill="x", padx=10, pady=(0, 4))
        cols_a = ("kod", "ad", "guven", "neden")
        tv = ttk.Treeview(win, columns=cols_a, show="headings", height=12)
        for c, t, w in (
            ("kod", "Stok kodu", 110),
            ("ad", "Stok adı", 280),
            ("guven", "Güven", 60),
            ("neden", "Neden", 90),
        ):
            tv.heading(c, text=t)
            tv.column(c, width=w)
        tv.pack(fill="both", expand=True, padx=10, pady=4)
        aday_map: dict[str, dict[str, Any]] = {}

        def _aday_doldur(liste: list[dict[str, Any]]):
            tv.delete(*tv.get_children())
            aday_map.clear()
            for i, a in enumerate(liste):
                iid = str(a.get("stok_id") or f"x{i}")
                aday_map[iid] = a
                tv.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        a.get("stok_kodu") or "",
                        a.get("stok_adi") or "",
                        _para(a.get("guven")),
                        a.get("neden") or "",
                    ),
                )

        _aday_doldur(adaylar)
        bos_lbl = ttk.Label(win, text="", foreground="#666")
        bos_lbl.pack(anchor="w", padx=10)
        if not adaylar:
            bos_lbl.configure(text="Otomatik aday yok — arama yapın veya yeni kart açın.")

        def ara_doldur(*_a):
            q = ara.get().strip()
            if not q:
                _aday_doldur(adaylar)
                bos_lbl.configure(
                    text="" if adaylar else "Otomatik aday yok — arama yapın veya yeni kart açın."
                )
                return
            bulunan = []
            for stok in StokService.stoklari_ara(q, limit=30):
                bulunan.append(
                    {
                        "stok_id": stok.id,
                        "stok_kodu": stok.stok_kodu,
                        "stok_adi": stok.stok_adi,
                        "guven": Decimal("40"),
                        "neden": "arama",
                    }
                )
            _aday_doldur(bulunan)
            bos_lbl.configure(text="" if bulunan else "Aramada kart bulunamadı.")

        ara.bind("<KeyRelease>", ara_doldur)

        def mevcut_bagla():
            sel = tv.selection()
            if not sel:
                messagebox.showinfo("Seçim", "Bağlamak için bir aday seçin.", parent=win)
                return
            a = aday_map.get(sel[0])
            if not a or not a.get("stok_id"):
                return
            stok = StokService.stok_getir(int(a["stok_id"]))
            if not stok:
                messagebox.showerror("Stok", "Seçilen stok bulunamadı.", parent=win)
                return
            win.destroy()
            if _satiri_stoka_bagla(line_id, stok, yeni_kart=False):
                _yenile(line_id)

        def yeni_ac():
            win.destroy()
            # Güncel satırı yeniden al
            data2 = InvoiceDraftService.getir(draft_id)
            line2 = next((x for x in data2["satirlar"] if int(x.id) == line_id), None)
            if line2 is None:
                messagebox.showerror("Satır", "Taslak satırı bulunamadı.", parent=app)
                return
            _yeni_stok_formu_ac(line2)

        alt_w = ttk.Frame(win)
        alt_w.pack(fill="x", padx=10, pady=8)
        ttk.Button(alt_w, text="Seçili Mevcut Karta Bağla", command=mevcut_bagla).pack(side="left")
        ttk.Button(alt_w, text="Yine de Yeni Kart Aç…", command=yeni_ac).pack(side="left", padx=8)
        ttk.Button(alt_w, text="İptal", command=win.destroy).pack(side="right")

    def satir_duzenle():
        line = _secili_line()
        if not line:
            messagebox.showinfo("Satır", "Önce bir satır seçin.", parent=app)
            return
        _manuel_satir_dialog(app, draft_id, geri_fn, line=line, yenile_fn=_yenile)

    def satir_sil():
        line = _secili_line()
        if not line:
            return
        if not messagebox.askyesno("Sil", "Seçili satır silinsin mi?", parent=app):
            return
        InvoiceDraftService.satir_sil(int(line.id))
        _yenile()

    def teslim_duzenle():
        line = _secili_line()
        if not line:
            messagebox.showinfo("Teslim", "Önce bir satır seçin.", parent=app)
            return
        win = tk.Toplevel(app)
        win.title("Teslim miktarı")
        win.geometry("320x140")
        win.transient(app)
        belge = line.miktar or Decimal("0")
        mevcut = getattr(line, "teslim_miktar", None)
        var = tk.StringVar(value=str(mevcut if mevcut is not None else belge))
        ttk.Label(win, text=f"Belge miktarı: {_para(belge)}").pack(anchor="w", padx=10, pady=(10, 4))
        fr = ttk.Frame(win)
        fr.pack(fill="x", padx=10)
        ttk.Label(fr, text="Teslim", width=10).pack(side="left")
        ttk.Entry(fr, textvariable=var).pack(side="left", fill="x", expand=True)

        def kaydet():
            raw = (var.get() or "").strip().replace(",", ".")
            try:
                t = Decimal(raw) if raw else None
            except Exception:
                messagebox.showerror("Teslim", "Geçersiz sayı.", parent=win)
                return
            try:
                InvoiceDraftService.satir_teslim_ata(int(line.id), t)
                win.destroy()
                _yenile(int(line.id))
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Teslim", str(exc), parent=win)

        ttk.Button(win, text="Kaydet", command=kaydet).pack(pady=12)

    satir_btn = ttk.Frame(satir_f)
    satir_btn.pack(fill="x", pady=4)
    ttk.Button(
        satir_btn,
        text="Manuel Satır Ekle",
        command=lambda: _manuel_satir_dialog(app, draft_id, geri_fn, yenile_fn=_yenile),
    ).pack(side="left")
    ttk.Button(satir_btn, text="Seçili Satırı Düzenle", command=satir_duzenle).pack(side="left", padx=4)
    ttk.Button(satir_btn, text="Teslim Miktarı…", command=teslim_duzenle).pack(side="left", padx=4)
    ttk.Button(satir_btn, text="Seçili Satırı Sil", command=satir_sil).pack(side="left")
    ttk.Button(satir_btn, text="Seçili Satıra Stok Ata…", command=lambda: stok_sec()).pack(side="left", padx=4)
    yeni_btn = ttk.Button(satir_btn, text="Yeni Stok Kartı Aç", command=lambda: yeni_stok_karti_ac())
    yeni_btn.pack(side="left", padx=4)
    secim_ipucu = ttk.Label(satir_btn, text="", foreground="#a40")
    secim_ipucu.pack(side="left", padx=(8, 0))

    def _secim_guncelle(_e=None):
        if tree.selection():
            yeni_btn.state(["!disabled"])
            secim_ipucu.configure(text="")
        else:
            yeni_btn.state(["disabled"])
            secim_ipucu.configure(text="Önce bir satır seçin")

    tree.bind("<<TreeviewSelect>>", _secim_guncelle)
    _secim_guncelle()

    ctx = tk.Menu(tree, tearoff=0)
    ctx.add_command(label="Seçili Satıra Stok Ata…", command=lambda: stok_sec())
    ctx.add_command(label="Yeni Stok Kartı Aç", command=lambda: yeni_stok_karti_ac())
    ctx.add_separator()
    ctx.add_command(label="Satırı Düzenle", command=satir_duzenle)
    ctx.add_command(label="Teslim Miktarı…", command=teslim_duzenle)
    ctx.add_command(label="Satırı Sil", command=satir_sil)

    def _ctx_menu(event):
        row = tree.identify_row(event.y)
        if row:
            tree.selection_set(row)
            tree.focus(row)
        try:
            ctx.tk_popup(event.x_root, event.y_root)
        finally:
            ctx.grab_release()

    tree.bind("<Button-3>", _ctx_menu)

    # Mal kabul (ALIS) — stok etkisi onay anında netleşir
    mk_var = tk.StringVar(
        value=(getattr(draft, "mal_kabul_durumu", None) or "mal_bekleniyor").strip().lower()
    )
    if mk_var.get() not in _MAL_KABUL_ETIKET:
        mk_var.set("mal_bekleniyor")
    if draft.yon == "ALIS":
        mk_f = ttk.LabelFrame(form, text="Mal kabul durumu", padding=8)
        mk_f.pack(fill="x", pady=(10, 0))
        ttk.Radiobutton(
            mk_f,
            text="Mal Geldi — stok ve mali hareket şimdi yazılır",
            value="mal_geldi",
            variable=mk_var,
        ).pack(anchor="w")
        ttk.Radiobutton(
            mk_f,
            text="Mal Bekleniyor — fatura oluşur, fiziksel stok sonra bağlanır (şimdi stok yok)",
            value="mal_bekleniyor",
            variable=mk_var,
        ).pack(anchor="w")
        ttk.Radiobutton(
            mk_f,
            text="İrsaliyeden Alındı — ikinci stok girişi yok (irsaliye stoku korunur)",
            value="irsaliyeden",
            variable=mk_var,
        ).pack(anchor="w")
        irs_fr = ttk.Frame(mk_f)
        irs_fr.pack(fill="x", pady=(6, 0))
        irs_lbl = tk.StringVar(
            value=(
                f"Bağlı irsaliye id: {draft.linked_irsaliye_id}"
                if getattr(draft, "linked_irsaliye_id", None)
                else "İrsaliye bağlı değil"
            )
        )
        ttk.Label(irs_fr, textvariable=irs_lbl).pack(side="left")

        def irsaliye_sec():
            if not draft.cari_id:
                messagebox.showinfo(
                    "İrsaliye",
                    "Önce cari seçin; açık irsaliyeler cariye göre listelenir.",
                    parent=app,
                )
                return
            adaylar = InvoiceDraftService.acik_irsaliyeler_cari(int(draft.cari_id))
            win = tk.Toplevel(app)
            win.title("Açık alış irsaliyesi seç")
            win.geometry("520x360")
            win.transient(app)
            lb = tk.Listbox(win)
            lb.pack(fill="both", expand=True, padx=8, pady=8)
            map_i: dict[str, int] = {}
            for a in adaylar:
                et = (
                    f"#{a['id']} {a['irsaliye_no']} · {a['tarih']} · "
                    f"{a['durum']} · kalan satır {a['kalan_satir']}"
                )
                lb.insert("end", et)
                map_i[et] = int(a["id"])
            if not adaylar:
                ttk.Label(win, text="Bu cariye ait açık irsaliye yok.", foreground="#a40").pack(
                    padx=8
                )

            def tamam():
                sel = lb.curselection()
                if not sel:
                    return
                iid = map_i[lb.get(sel[0])]
                try:
                    r = InvoiceDraftService.irsaliye_bagla(draft_id, iid)
                    mk_var.set("irsaliyeden")
                    messagebox.showinfo(
                        "İrsaliye",
                        f"İrsaliye bağlandı. Eşleşen satır: {r.get('eslesen_satir', 0)}",
                        parent=win,
                    )
                    win.destroy()
                    _yenile()
                except Exception as exc:  # noqa: BLE001
                    messagebox.showerror("İrsaliye", str(exc), parent=win)

            def kaldir():
                try:
                    InvoiceDraftService.irsaliye_bagla(draft_id, None)
                    win.destroy()
                    _yenile()
                except Exception as exc:  # noqa: BLE001
                    messagebox.showerror("İrsaliye", str(exc), parent=win)

            bf = ttk.Frame(win)
            bf.pack(fill="x", padx=8, pady=(0, 8))
            ttk.Button(bf, text="Seç ve eşleştir", command=tamam).pack(side="left")
            ttk.Button(bf, text="Bağlantıyı kaldır", command=kaldir).pack(side="left", padx=6)
            ttk.Button(bf, text="Kapat", command=win.destroy).pack(side="right")

        ttk.Button(irs_fr, text="İrsaliye Seç…", command=irsaliye_sec).pack(side="right")

    # Doğrulama / kesin kayıt
    alt = ttk.Frame(form)
    alt.pack(fill="x", pady=(10, 0))

    def _kesin_nedeni(r: dict[str, Any] | None = None) -> str:
        r = r or dog
        if r.get("ok"):
            return "Doğrulama bekleniyor — Doğrula ile onay açılır"
        if not draft.cari_id and draft.cari_eslesme_modu != "yeni_taslak":
            return "Cari seçilmedi"
        if not satirlar:
            return "Satır yok"
        eksik = sum(
            1
            for s in satirlar
            if s.match_status not in {"eslesti", "yeni_stok", "hizmet", "gider", "haric"}
        )
        if eksik:
            return f"{eksik} stok eşleşmesi eksik"
        birim_eksik = sum(
            1
            for s in satirlar
            if s.match_status in {"eslesti", "yeni_stok"} and s.birim_carpan is None
        )
        if birim_eksik and r.get("hatalar"):
            # birim uyarıdır; asıl engel hatalarda
            pass
        if r.get("hatalar"):
            h = str(r["hatalar"][0])
            if "fark" in h.lower() or "toplam" in h.lower():
                return h
            return h
        if birim_eksik:
            return f"{birim_eksik} birim dönüşümü doğrulanmadı"
        return "Doğrulama bekleniyor — Doğrula ile onay açılır"

    def dogrula():
        r = InvoiceDraftService.dogrula(draft_id)
        msg = ""
        if r["hatalar"]:
            msg += "Hatalar:\n- " + "\n- ".join(r["hatalar"]) + "\n\n"
        if r["uyarilar"]:
            msg += "Uyarılar:\n- " + "\n- ".join(r["uyarilar"]) + "\n\n"
        msg += (
            f"Hesaplanan: {_para(r['hesaplanan_toplam'])}  "
            f"Belge: {_para(r['belge_toplam'])}  Fark: {_para(r['fark'])}"
        )
        if r["ok"]:
            messagebox.showinfo("Doğrulama", "Kontroller geçti.\n\n" + msg, parent=app)
            kesin_btn.state(["!disabled"])
            neden_lbl.configure(text="")
        else:
            messagebox.showwarning("Doğrulama", msg, parent=app)
            kesin_btn.state(["disabled"])
            neden_lbl.configure(text=_kesin_nedeni(r))

    def kesin():
        r = InvoiceDraftService.dogrula(draft_id)
        if not r["ok"]:
            messagebox.showerror(
                "Kesin kayıt engellendi",
                "Onayla ve Faturayı Oluştur için kontrolleri geçmeniz gerekir.\n\n- "
                + "\n- ".join(r["hatalar"]),
                parent=app,
            )
            kesin_btn.state(["disabled"])
            neden_lbl.configure(text=_kesin_nedeni(r))
            return
        if draft.yon == "ALIS":
            try:
                InvoiceDraftService.mal_kabul_ata(draft_id, mk_var.get())
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("Mal kabul", str(exc), parent=app)
                return
            mk_etiket = _MAL_KABUL_ETIKET.get(mk_var.get(), mk_var.get())
            kismi = any(
                getattr(s, "teslim_miktar", None) is not None
                and s.teslim_miktar < (s.miktar or 0)
                for s in satirlar
                if s.match_status != "haric"
            )
            if mk_var.get() == "mal_geldi" and not kismi:
                stok_notu = "Stok girişi yazılacak."
            elif mk_var.get() == "mal_geldi" and kismi:
                stok_notu = "Kısmi teslim: stok şimdi yazılmaz (kalan fiziksel kabul sonra)."
            else:
                stok_notu = "Stok girişi yazılmayacak."
            onay_msg = (
                f"Onayla ve faturayı oluştur?\nMal kabul: {mk_etiket}\n{stok_notu}\n"
                "Bu işlem transaction içinde kesin kayıt yazar."
            )
        else:
            onay_msg = "Onayla ve faturayı oluştur?\nBu işlem transaction içinde kesin kayıt yazar."
        if not messagebox.askyesno("Onay", onay_msg, parent=app):
            return
        try:
            sonuc = InvoicePostingService.kesinlestir(draft_id)
            ekstra = ""
            if sonuc.get("mal_kabul_durumu"):
                ekstra = (
                    f"\nMal kabul: {_MAL_KABUL_ETIKET.get(sonuc['mal_kabul_durumu'], sonuc['mal_kabul_durumu'])}"
                    f"\nStok hareketi: {'evet' if sonuc.get('hareket_yaz') else 'hayır'}"
                )
            messagebox.showinfo(
                "Tamam",
                f"{sonuc['tur']} faturası oluşturuldu.\nNo: {sonuc['belge_no']}\n"
                f"ID: {sonuc['fatura_id']}{ekstra}",
                parent=app,
            )
            if geri_fn:
                geri_fn()
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Kesin kayıt", str(exc), parent=app)

    ttk.Button(alt, text="Doğrula", command=dogrula).pack(side="left")
    kesin_btn = ttk.Button(alt, text="Onayla ve Faturayı Oluştur", command=kesin)
    kesin_btn.pack(side="left", padx=8)
    neden_lbl = ttk.Label(alt, text="", foreground="#a40")
    neden_lbl.pack(side="left", padx=(4, 0))
    # Yeni kart / satır değişiminden sonra eski doğrulama ile onaylanamaz
    kesin_btn.state(["disabled"])
    neden_lbl.configure(text=_kesin_nedeni())


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


def _manuel_satir_dialog(app, draft_id: int, geri_fn, line=None, yenile_fn=None) -> None:
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
            secili = None
            if line is None:
                InvoiceDraftService.satir_ekle(draft_id, veri)
            else:
                InvoiceDraftService.satir_guncelle(line.id, veri)
                secili = int(line.id)
            win.destroy()
            if yenile_fn:
                yenile_fn(secili)
            else:
                fatura_belge_kontrol_goster(app, draft_id, geri_fn, secili_satir_id=secili)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Satır", str(exc), parent=win)

    ttk.Button(win, text="Kaydet", command=kaydet).pack(pady=12)
