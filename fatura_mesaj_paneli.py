"""Satış faturası — kalıcı Mesajlar paneli ve Mesaj Geçmişi."""

from __future__ import annotations

import tkinter as tk
import uuid
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Any

from branding import COLOR_BG, COLOR_GOLD, COLOR_NAVY


def _session_key_al(dialog) -> str:
    key = getattr(dialog, "_barkod_mesaj_session_key", None)
    if not key:
        key = uuid.uuid4().hex
        dialog._barkod_mesaj_session_key = key
    return key


def _fatura_kimlik(dialog) -> tuple[int | None, str]:
    fid = None
    fno = ""
    fatura = getattr(dialog, "fatura", None)
    if fatura is not None:
        fid = getattr(fatura, "id", None)
        fno = getattr(fatura, "fatura_no", "") or ""
    if not fno:
        try:
            if hasattr(dialog, "fatura_no_alani"):
                fno = (dialog.fatura_no_alani.get() or "").strip()
        except Exception:
            pass
    return (int(fid) if fid else None, fno)


def fatura_mesaj_paneli_kur(dialog) -> None:
    """Fatura ekranına daraltılabilir Mesajlar paneli ekler."""
    if getattr(dialog, "_mesaj_paneli_hazir", False):
        return
    try:
        from database.invoice_scan_message_service import schema_hazirla

        schema_hazirla()
    except Exception:
        pass

    _session_key_al(dialog)
    dialog._mesaj_paneli_acik = True
    dialog._mesaj_paneli_satirlar: dict[int, dict[str, Any]] = {}

    # Satır tablosunun parent'ına alt bant
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is None:
        return
    parent = tablo.master

    dis = tk.Frame(parent, bg=COLOR_NAVY, highlightthickness=0)
    # Pack: tablo genellikle pack/grid — grid ise altına ekle
    try:
        info = tablo.grid_info() or {}
    except tk.TclError:
        info = {}
    if info:
        try:
            row = int(info.get("row", 0)) + 1
            col = int(info.get("column", 0))
            colspan = int(info.get("columnspan") or 1)
            # Mevcut alt satırları kaydır
            for w in list(parent.grid_slaves()):
                try:
                    r = int(w.grid_info().get("row", 0))
                except (tk.TclError, TypeError, ValueError):
                    continue
                if r >= row:
                    try:
                        w.grid_configure(row=r + 1)
                    except tk.TclError:
                        pass
            dis.grid(row=row, column=col, columnspan=colspan, sticky="ew", pady=(4, 0))
        except tk.TclError:
            dis.pack(fill="x", pady=(4, 0))
    else:
        dis.pack(fill="x", pady=(4, 0), before=None)
        try:
            dis.pack(fill="x", side="bottom", pady=(4, 0))
        except tk.TclError:
            pass

    dialog._mesaj_panel_dis = dis

    baslik = tk.Frame(dis, bg=COLOR_NAVY)
    baslik.pack(fill="x")
    dialog._mesaj_baslik_lbl = tk.Label(
        baslik,
        text="  Mesajlar",
        bg=COLOR_NAVY,
        fg=COLOR_GOLD,
        font=("Segoe UI", 9, "bold"),
        anchor="w",
        cursor="hand2",
    )
    dialog._mesaj_baslik_lbl.pack(side="left", pady=2)
    dialog._mesaj_baslik_lbl.bind("<Button-1>", lambda _e: _panel_daralt_ac(dialog))

    tk.Button(
        baslik,
        text="Geçmişi aç",
        command=lambda: BarkodMesajGecmisiDialog(dialog),
        bg=COLOR_NAVY,
        fg="#E5E7EB",
        relief="flat",
        font=("Segoe UI", 8),
        cursor="hand2",
        activebackground="#1e3a5f",
        activeforeground="#fff",
    ).pack(side="right", padx=4)
    tk.Button(
        baslik,
        text="Tümünü kapat",
        command=lambda: _tumunu_kapat(dialog),
        bg=COLOR_NAVY,
        fg="#E5E7EB",
        relief="flat",
        font=("Segoe UI", 8),
        cursor="hand2",
        activebackground="#1e3a5f",
        activeforeground="#fff",
    ).pack(side="right", padx=2)

    ic = tk.Frame(dis, bg=COLOR_BG)
    ic.pack(fill="both", expand=True)
    dialog._mesaj_panel_ic = ic

    canvas = tk.Canvas(ic, bg=COLOR_BG, highlightthickness=0, height=96)
    scroll = ttk.Scrollbar(ic, orient="vertical", command=canvas.yview)
    liste = tk.Frame(canvas, bg=COLOR_BG)
    liste.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
    )
    canvas.create_window((0, 0), window=liste, anchor="nw")
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    dialog._mesaj_liste = liste
    dialog._mesaj_canvas = canvas
    dialog._mesaj_paneli_hazir = True

    # Açık mesajları yükle (fatura id veya session)
    dialog.after(80, lambda: mesajlari_yeniden_yukle(dialog))


def _panel_daralt_ac(dialog) -> None:
    ic = getattr(dialog, "_mesaj_panel_ic", None)
    if ic is None:
        return
    acik = getattr(dialog, "_mesaj_paneli_acik", True)
    if acik:
        ic.pack_forget()
        dialog._mesaj_paneli_acik = False
    else:
        ic.pack(fill="both", expand=True)
        dialog._mesaj_paneli_acik = True
    _baslik_guncelle(dialog)


def _baslik_guncelle(dialog) -> None:
    lbl = getattr(dialog, "_mesaj_baslik_lbl", None)
    if lbl is None:
        return
    n = len(getattr(dialog, "_mesaj_paneli_satirlar", {}) or {})
    metin = f"  Mesajlar {n}" if n else "  Mesajlar"
    if not getattr(dialog, "_mesaj_paneli_acik", True):
        metin += " ▸"
    else:
        metin += " ▾"
    try:
        lbl.configure(text=metin)
    except tk.TclError:
        pass


def mesajlari_yeniden_yukle(dialog) -> None:
    from database.invoice_scan_message_service import acik_mesajlari_listele

    fid, _fno = _fatura_kimlik(dialog)
    session_key = _session_key_al(dialog)
    try:
        if fid:
            kayitlar = acik_mesajlari_listele(invoice_id=fid)
        else:
            kayitlar = acik_mesajlari_listele(session_key=session_key)
    except Exception:
        kayitlar = []
    dialog._mesaj_paneli_satirlar = {}
    liste = getattr(dialog, "_mesaj_liste", None)
    if liste is not None:
        for w in list(liste.winfo_children()):
            try:
                w.destroy()
            except tk.TclError:
                pass
    for k in kayitlar:
        _panel_satir_ekle(dialog, k, odak_koru=True)
    _baslik_guncelle(dialog)


def panel_mesaj_ekle(dialog, kayit: dict[str, Any] | None, *, teknik_uyari: str | None = None) -> None:
    """DB kaydı veya yerel teknik uyarıyı panele ekler. Odak barkotta kalır."""
    if not getattr(dialog, "_mesaj_paneli_hazir", False):
        try:
            fatura_mesaj_paneli_kur(dialog)
        except Exception:
            pass
    if kayit:
        mid = int(kayit["id"])
        mevcut = (getattr(dialog, "_mesaj_paneli_satirlar", None) or {}).get(mid)
        if mevcut and mevcut.get("frame"):
            _satir_guncelle(dialog, kayit)
        else:
            _panel_satir_ekle(dialog, kayit, odak_koru=True)
    elif teknik_uyari:
        _yerel_teknik(dialog, teknik_uyari)
    _baslik_guncelle(dialog)
    # Odak asla mesaj paneline kaçmasın
    try:
        from fatura_barkod_ui import _barkod_odak

        dialog.after_idle(lambda: _barkod_odak(dialog))
    except Exception:
        pass


def _yerel_teknik(dialog, metin: str) -> None:
    liste = getattr(dialog, "_mesaj_liste", None)
    if liste is None:
        return
    fr = tk.Frame(liste, bg="#FEF3C7", padx=6, pady=4)
    fr.pack(fill="x", padx=4, pady=2, side="top")
    tk.Label(
        fr,
        text=metin,
        bg="#FEF3C7",
        fg="#92400E",
        font=("Segoe UI", 8),
        wraplength=520,
        justify="left",
        anchor="w",
    ).pack(side="left", fill="x", expand=True)


def _panel_satir_ekle(dialog, kayit: dict[str, Any], *, odak_koru: bool = True) -> None:
    liste = getattr(dialog, "_mesaj_liste", None)
    if liste is None:
        return
    mid = int(kayit["id"])
    bg = "#FFEBEE" if kayit.get("message_type") == "BARCODE_NOT_FOUND" else "#FEF3C7"
    fr = tk.Frame(liste, bg=bg, padx=6, pady=4)
    # Yeni mesaj en üstte
    children = liste.winfo_children()
    if children:
        fr.pack(fill="x", padx=4, pady=2, side="top", before=children[0])
    else:
        fr.pack(fill="x", padx=4, pady=2, side="top")

    saat = ""
    ls = kayit.get("last_seen_at") or kayit.get("created_at")
    if isinstance(ls, datetime):
        saat = ls.strftime("%d.%m.%Y %H:%M")
    sayac = int(kayit.get("scan_count") or 1)
    metin = kayit.get("message_text") or ""
    if sayac > 1:
        metin = f"{metin}  ({sayac} kez okutuldu)"

    sol = tk.Frame(fr, bg=bg)
    sol.pack(side="left", fill="x", expand=True)
    tk.Label(
        sol,
        text=f"{saat}  ·  {kayit.get('barcode') or ''}",
        bg=bg,
        fg="#6B7280",
        font=("Segoe UI", 7),
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        sol,
        text=metin,
        bg=bg,
        fg="#B71C1C",
        font=("Segoe UI", 9),
        wraplength=520,
        justify="left",
        anchor="w",
    ).pack(fill="x")

    # Stok oluştur yalnızca barkod bulunamadı mesajlarında
    if kayit.get("message_type") == "BARCODE_NOT_FOUND":
        tk.Button(
            fr,
            text="Stok Kartı Oluştur",
            command=lambda i=mid, b=kayit.get("barcode") or "": _stok_karti_olustur(
                dialog, i, b
            ),
            font=("Segoe UI", 8),
            relief="groove",
            cursor="hand2",
            bg="#C8E6C9",
        ).pack(side="right", padx=2)
    tk.Button(
        fr,
        text="Kapat",
        command=lambda i=mid: _tek_kapat(dialog, i),
        font=("Segoe UI", 8),
        relief="groove",
        cursor="hand2",
    ).pack(side="right", padx=4)

    dialog._mesaj_paneli_satirlar[mid] = {"frame": fr, "kayit": kayit}
    if odak_koru:
        try:
            from fatura_barkod_ui import _barkod_odak

            dialog.after_idle(lambda: _barkod_odak(dialog))
        except Exception:
            pass


def _satir_guncelle(dialog, kayit: dict[str, Any]) -> None:
    mid = int(kayit["id"])
    bilgi = (getattr(dialog, "_mesaj_paneli_satirlar", None) or {}).get(mid)
    if not bilgi:
        _panel_satir_ekle(dialog, kayit)
        return
    fr = bilgi.get("frame")
    if fr is None:
        return
    try:
        fr.destroy()
    except tk.TclError:
        pass
    dialog._mesaj_paneli_satirlar.pop(mid, None)
    _panel_satir_ekle(dialog, kayit)


def _stok_karti_olustur(dialog, mesaj_id: int, barkod: str) -> None:
    from hizli_stok_karti_ui import hizli_stok_karti_ac

    def _sonra(_stok):
        # Panelden çözülen mesajı kaldır
        bilgi = (getattr(dialog, "_mesaj_paneli_satirlar", None) or {}).pop(mesaj_id, None)
        if bilgi and bilgi.get("frame"):
            try:
                bilgi["frame"].destroy()
            except tk.TclError:
                pass
        _baslik_guncelle(dialog)

    hizli_stok_karti_ac(
        dialog,
        barkod=barkod,
        mesaj_id=mesaj_id,
        on_faturaya_ekle=_sonra,
    )


def _tek_kapat(dialog, mesaj_id: int) -> None:
    from database.invoice_scan_message_service import mesaj_kapat

    mesaj_kapat(mesaj_id)
    bilgi = (getattr(dialog, "_mesaj_paneli_satirlar", None) or {}).pop(mesaj_id, None)
    if bilgi and bilgi.get("frame"):
        try:
            bilgi["frame"].destroy()
        except tk.TclError:
            pass
    _baslik_guncelle(dialog)
    try:
        from fatura_barkod_ui import _barkod_odak

        _barkod_odak(dialog)
    except Exception:
        pass


def _tumunu_kapat(dialog) -> None:
    ids = list((getattr(dialog, "_mesaj_paneli_satirlar", None) or {}).keys())
    for mid in ids:
        _tek_kapat(dialog, mid)


def fatura_kaydinda_mesajlari_bagla(dialog, fatura) -> None:
    """İlk kayıt sonrası session mesajlarını invoice_id ile bağla."""
    if fatura is None:
        return
    from database.invoice_scan_message_service import fatura_mesajlarini_bagla

    key = getattr(dialog, "_barkod_mesaj_session_key", None)
    fid = getattr(fatura, "id", None)
    fno = getattr(fatura, "fatura_no", None)
    if key and fid:
        fatura_mesajlarini_bagla(
            session_key=key, invoice_id=int(fid), invoice_no=fno
        )


class BarkodMesajGecmisiDialog(tk.Toplevel):
    """Barkod ve işlem mesajları geçmişi."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Barkod ve İşlem Mesajları Geçmişi")
        self.geometry("920x480")
        self.transient(parent)
        self._parent_fatura = parent

        filtre = ttk.Frame(self, padding=8)
        filtre.pack(fill="x")
        ttk.Label(filtre, text="Ara").pack(side="left")
        self.ara = ttk.Entry(filtre, width=24)
        self.ara.pack(side="left", padx=4)
        ttk.Label(filtre, text="Durum").pack(side="left", padx=(8, 0))
        self.durum = ttk.Combobox(
            filtre, values=("Hepsi", "OPEN", "CLOSED", "RESOLVED"), width=10, state="readonly"
        )
        self.durum.set("Hepsi")
        self.durum.pack(side="left", padx=4)
        ttk.Label(filtre, text="Tür").pack(side="left", padx=(8, 0))
        self.tur = ttk.Combobox(
            filtre,
            values=("Hepsi", "BARCODE_NOT_FOUND", "TECHNICAL_ERROR"),
            width=18,
            state="readonly",
        )
        self.tur.set("Hepsi")
        self.tur.pack(side="left", padx=4)
        ttk.Button(filtre, text="Listele", command=self._yenile).pack(side="left", padx=8)

        kolonlar = (
            "zaman",
            "barkod",
            "mesaj",
            "sayac",
            "fatura",
            "stok",
            "tur",
            "durum",
            "kapanma",
        )
        self.tablo = ttk.Treeview(self, columns=kolonlar, show="headings", height=16)
        basliklar = {
            "zaman": "Tarih/Saat",
            "barkod": "Barkod",
            "mesaj": "Mesaj",
            "sayac": "Okutma",
            "fatura": "Fatura No",
            "stok": "Oluşturulan Stok",
            "tur": "Tür",
            "durum": "Durum",
            "kapanma": "Kapanma",
        }
        gen = {
            "zaman": 120,
            "barkod": 110,
            "mesaj": 200,
            "sayac": 55,
            "fatura": 90,
            "stok": 140,
            "tur": 100,
            "durum": 80,
            "kapanma": 110,
        }
        for k in kolonlar:
            self.tablo.heading(k, text=basliklar[k])
            self.tablo.column(k, width=gen[k], anchor="w")
        self.tablo.pack(fill="both", expand=True, padx=8, pady=4)
        self._id_map: dict[str, int] = {}

        alt = ttk.Frame(self, padding=8)
        alt.pack(fill="x")
        ttk.Button(alt, text="Yeniden aç", command=self._yeniden_ac).pack(side="left")
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")
        self._yenile()

    def _yenile(self):
        from database.invoice_scan_message_service import gecmis_listele

        for i in self.tablo.get_children():
            self.tablo.delete(i)
        self._id_map.clear()
        durum = self.durum.get()
        tur = self.tur.get()
        kayitlar = gecmis_listele(
            status=None if durum == "Hepsi" else durum,
            message_type=None if tur == "Hepsi" else tur,
            ara=self.ara.get().strip() or None,
        )
        for k in kayitlar:
            ca = k.get("created_at")
            zaman = ca.strftime("%d.%m.%Y %H:%M") if isinstance(ca, datetime) else ""
            kap = k.get("closed_at")
            kapanma = kap.strftime("%d.%m.%Y %H:%M") if isinstance(kap, datetime) else ""
            stok_bilgi = ""
            if k.get("resolved_stok_kodu") or k.get("resolved_stok_adi"):
                stok_bilgi = f"{k.get('resolved_stok_kodu') or ''} {k.get('resolved_stok_adi') or ''}".strip()
            durum_goster = k.get("status") or ""
            if durum_goster == "RESOLVED":
                durum_goster = "Çözüldü"
            iid = self.tablo.insert(
                "",
                "end",
                values=(
                    zaman,
                    k.get("barcode") or "",
                    k.get("message_text") or "",
                    k.get("scan_count") or 1,
                    k.get("invoice_no") or "",
                    stok_bilgi,
                    k.get("message_type") or "",
                    durum_goster,
                    kapanma,
                ),
            )
            self._id_map[iid] = int(k["id"])

    def _yeniden_ac(self):
        from database.invoice_scan_message_service import mesaj_yeniden_ac

        sec = self.tablo.selection()
        if not sec:
            messagebox.showinfo("Geçmiş", "Bir mesaj seçin.", parent=self)
            return
        mid = self._id_map.get(sec[0])
        if not mid:
            return
        kayit = mesaj_yeniden_ac(mid)
        if kayit:
            parent = self._parent_fatura
            if parent is not None and getattr(parent, "_mesaj_paneli_hazir", False):
                panel_mesaj_ekle(parent, kayit)
            self._yenile()
            messagebox.showinfo("Geçmiş", "Mesaj yeniden açıldı.", parent=self)
