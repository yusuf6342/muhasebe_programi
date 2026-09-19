"""Satış faturası — satır araç çubuğu, sağ menü, kısayollar ve satır işlemleri."""

from __future__ import annotations

import tkinter as tk
from copy import deepcopy
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from fatura_satir_birim_service import birim_satis_fiyati, temel_miktar
from fatura_satir_hucre_edit import hucre_duzenle


def _secili_indeksler(dialog) -> list[int]:
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is None:
        return []
    sonuc = []
    for iid in tablo.selection():
        try:
            idx = int(iid)
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(dialog.satirlar):
            sonuc.append(idx)
    return sorted(set(sonuc))


def _tek_secim(dialog) -> int | None:
    idxs = _secili_indeksler(dialog)
    return idxs[0] if idxs else None


def _metin_odakli_mi(dialog) -> bool:
    """Entry/Text/Combobox odaktayken satır kısayolları çalışmasın."""
    try:
        w = dialog.focus_get()
    except tk.TclError:
        return False
    if w is None:
        return False
    # Hücre editörü
    if w is getattr(dialog, "_satir_hucre_editor", None):
        return True
    cls = w.winfo_class()
    if cls in ("TEntry", "Entry", "TCombobox", "Text", "TSpinbox"):
        return True
    return False


def _yenile(dialog, secim: list[int] | None = None):
    kaydir = (0.0, 1.0)
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is not None:
        try:
            kaydir = tablo.yview()
        except tk.TclError:
            pass
    dialog._satir_listesini_yenile()
    dialog._toplamlari_guncelle()
    if tablo is None:
        return
    try:
        tablo.yview_moveto(kaydir[0])
    except tk.TclError:
        pass
    if secim:
        for i in secim:
            if 0 <= i < len(dialog.satirlar):
                try:
                    tablo.selection_add(str(i))
                    tablo.focus(str(i))
                    tablo.see(str(i))
                except tk.TclError:
                    pass


def _audit_satir_sil(dialog, satirlar: list[dict], neden: str = ""):
    try:
        from database.user_audit import audit_document

        fatura = getattr(dialog, "fatura", None)
        kayit_id = str(fatura.id) if fatura and getattr(fatura, "id", None) else None
        eski = {
            "satirlar": [
                {
                    "urun_kodu": s.get("urun_kodu"),
                    "urun_adi": s.get("urun_adi"),
                    "miktar": s.get("miktar"),
                    "birim": s.get("birim"),
                    "birim_fiyat": s.get("birim_satis_fiyati"),
                    "kdv": s.get("kdv_orani"),
                }
                for s in satirlar
            ]
        }
        audit_document(
            "FATURA_SATIR_SIL",
            modul="satis_faturasi",
            kayit_id=kayit_id,
            belge_no=getattr(fatura, "fatura_no", None) if fatura else None,
            eski=eski,
            aciklama=neden or "kullanici",
        )
    except Exception:
        pass


# ─── Satır işlemleri ───────────────────────────────────────────────


def satir_duzenle(dialog) -> None:
    idx = _tek_secim(dialog)
    if idx is None:
        messagebox.showinfo("Düzenle", "Önce bir satır seçin.", parent=dialog)
        return
    hucre_duzenle(dialog, idx=idx, kolon="miktar")


def satir_sil(dialog, *, neden: str = "") -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        messagebox.showwarning(
            "Satır sil",
            "Onaylı faturada satır silmek için önce Onay Kaldır yapın.",
            parent=dialog,
        )
        return
    idxs = _secili_indeksler(dialog)
    if not idxs:
        messagebox.showinfo(
            "Satır sil",
            "Silmek için tabloda bir veya daha fazla satır seçin.",
            parent=dialog,
        )
        return
    adet = len(idxs)
    ornek = dialog.satirlar[idxs[0]]
    if adet == 1:
        mesaj = (
            f"Satır silinsin mi?\n\n"
            f"{ornek.get('urun_kodu')} — {ornek.get('urun_adi')}\n"
            f"Miktar: {ornek.get('miktar')} {ornek.get('birim')}"
        )
    else:
        mesaj = (
            f"{adet} satır silinsin mi?\n\n"
            f"İlk: {ornek.get('urun_kodu')} — {ornek.get('urun_adi')}"
        )
    if not messagebox.askyesno("Satır sil", mesaj, parent=dialog):
        return
    silinen = [deepcopy(dialog.satirlar[i]) for i in idxs]
    for i in reversed(idxs):
        dialog.satirlar.pop(i)
    _audit_satir_sil(dialog, silinen, neden=neden or "kullanici_sil")
    if hasattr(dialog, "_satir_isaretleri"):
        dialog._satir_isaretleri = set()
    dialog._duzenlenen_satir = None
    _yenile(dialog)
    _bos_mesaj_guncelle(dialog)


def satir_cogalt(dialog) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        messagebox.showwarning("Çoğalt", "Onaylı faturada satır çoğaltılamaz.", parent=dialog)
        return
    idx = _tek_secim(dialog)
    if idx is None:
        messagebox.showinfo("Çoğalt", "Önce bir satır seçin.", parent=dialog)
        return
    kaynak = dialog.satirlar[idx]
    yeni = deepcopy(kaynak)
    yeni["miktar"] = "1"
    kod = (yeni.get("urun_kodu") or "").strip()
    birim = (yeni.get("birim") or "Adet").strip()
    try:
        yeni["temel_miktar"] = str(temel_miktar(Decimal("1"), birim, kod))
    except Exception:
        yeni["temel_miktar"] = "1"
    # Stok kontrolü — iki satır toplamı
    try:
        from fatura_barkod_ui import _eksi_stok_kontrol, _urun_talep_toplami

        depo = ""
        if hasattr(dialog, "depo"):
            depo = dialog.depo.get().strip()
        talep = _urun_talep_toplami(dialog, kod) + temel_miktar(Decimal("1"), birim, kod)
        _eksi_stok_kontrol(
            dialog,
            {"stok_adi": yeni.get("urun_adi"), "stok_kodu": kod},
            depo,
            urun_kodu=kod,
            proje_miktar_toplam=talep,
        )
    except ValueError as hata:
        messagebox.showwarning("Stok", str(hata), parent=dialog)
        return
    except Exception:
        pass
    insert_at = idx + 1
    dialog.satirlar.insert(insert_at, yeni)
    _yenile(dialog, secim=[insert_at])
    _bos_mesaj_guncelle(dialog)


def satir_uste_tasi(dialog) -> None:
    idx = _tek_secim(dialog)
    if idx is None or idx <= 0:
        return
    dialog.satirlar[idx - 1], dialog.satirlar[idx] = (
        dialog.satirlar[idx],
        dialog.satirlar[idx - 1],
    )
    _yenile(dialog, secim=[idx - 1])


def satir_alta_tasi(dialog) -> None:
    idx = _tek_secim(dialog)
    if idx is None or idx >= len(dialog.satirlar) - 1:
        return
    dialog.satirlar[idx + 1], dialog.satirlar[idx] = (
        dialog.satirlar[idx],
        dialog.satirlar[idx + 1],
    )
    _yenile(dialog, secim=[idx + 1])


def fiyati_yenile(dialog) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        return
    idxs = _secili_indeksler(dialog)
    if not idxs:
        messagebox.showinfo("Fiyat", "Önce satır seçin.", parent=dialog)
        return
    musteri = None
    if hasattr(dialog, "_secili_musteri"):
        try:
            musteri = dialog._secili_musteri()
        except Exception:
            pass
    for idx in idxs:
        satir = dialog.satirlar[idx]
        kod = (satir.get("urun_kodu") or "").strip()
        birim = (satir.get("birim") or "Adet").strip()
        fiyat = birim_satis_fiyati(kod, birim, musteri=musteri)
        if fiyat is None:
            continue
        satir["birim_satis_fiyati"] = str(fiyat)
        satir["manuel_fiyat"] = False
        satir.pop("manuel_fiyat_birim", None)
        satir.pop("birim_fiyat_doviz", None)
    _yenile(dialog, secim=idxs)


def iskontoyu_temizle(dialog) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        return
    idxs = _secili_indeksler(dialog)
    if not idxs:
        messagebox.showinfo("İskonto", "Önce satır seçin.", parent=dialog)
        return
    for idx in idxs:
        satir = dialog.satirlar[idx]
        satir["iskonto_orani"] = "0"
        satir["iskonto_orani_2"] = "0"
        satir["iskonto_orani_3"] = "0"
    _yenile(dialog, secim=idxs)


def _coklu_iskonto_duzenle(dialog) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        return
    idx = _tek_secim(dialog)
    if idx is None:
        messagebox.showinfo("İskonto", "Önce bir satır seçin.", parent=dialog)
        return
    from fatura_satir_hucre_edit import iskonto_yuzde_hucre

    iskonto_yuzde_hucre(dialog, idx=idx)


def satir_aciklama_gir(dialog) -> None:
    if getattr(dialog, "_fatura_kilitli", False):
        return
    idx = _tek_secim(dialog)
    if idx is None:
        messagebox.showinfo("Açıklama", "Önce bir satır seçin.", parent=dialog)
        return
    mevcut = dialog.satirlar[idx].get("aciklama") or ""
    metin = simpledialog.askstring(
        "Satır Açıklaması",
        f"{dialog.satirlar[idx].get('urun_adi')}",
        initialvalue=mevcut,
        parent=dialog,
    )
    if metin is None:
        return
    dialog.satirlar[idx]["aciklama"] = metin.strip()
    _yenile(dialog, secim=[idx])


def stok_kartini_ac(dialog) -> None:
    idx = _tek_secim(dialog)
    if idx is None:
        return
    kod = (dialog.satirlar[idx].get("urun_kodu") or "").strip()
    if not kod:
        return
    try:
        from database.stok_service import StokService
        from stok_ui import StokKartiDialog

        bulunan = StokService.stoklari_ara(kod)
        stok = next((s for s in bulunan if (s.stok_kodu or "").strip() == kod), None)
        if stok is None:
            messagebox.showinfo("Stok", "Stok kartı bulunamadı.", parent=dialog)
            return
        StokKartiDialog(dialog, stok)
    except Exception as hata:
        messagebox.showerror("Stok", str(hata), parent=dialog)


def urun_hareketlerini_goster(dialog) -> None:
    idx = _tek_secim(dialog)
    if idx is None:
        return
    kod = (dialog.satirlar[idx].get("urun_kodu") or "").strip()
    if not kod:
        return
    try:
        # Fiyatlı stok ekstresi / hareket ekranı varsa aç
        if hasattr(dialog, "master") and hasattr(dialog.master, "stok_hareket_ac"):
            dialog.master.stok_hareket_ac(kod)
            return
        from database.stok_service import StokService

        hareketler = []
        try:
            hareketler = StokService.urun_hareket_ozeti(kod) if hasattr(StokService, "urun_hareket_ozeti") else []
        except Exception:
            hareketler = []
        messagebox.showinfo(
            "Ürün hareketleri",
            f"{kod}\n"
            f"{dialog.satirlar[idx].get('urun_adi')}\n\n"
            f"Detaylı hareketler için Stok kartı / Stok Hareketleri ekranını kullanın."
            + (f"\n({len(hareketler)} kayıt)" if hareketler else ""),
            parent=dialog,
        )
    except Exception as hata:
        messagebox.showerror("Hareket", str(hata), parent=dialog)


# ─── Boş fatura mesajı ─────────────────────────────────────────────


def _bos_mesaj_guncelle(dialog) -> None:
    lbl = getattr(dialog, "_fatura_bos_mesaj", None)
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is None:
        return
    if not dialog.satirlar:
        if lbl is None:
            lbl = tk.Label(
                tablo.master,
                text=(
                    "Faturaya ürün eklemek için barkod okutun,\n"
                    "ürün kodu girin veya ürün adıyla arama yapın."
                ),
                font=("Segoe UI", 11),
                fg="#667085",
                bg="#FFFFFF",
                justify="center",
            )
            dialog._fatura_bos_mesaj = lbl
        try:
            lbl.place(in_=tablo, relx=0.5, rely=0.45, anchor="center")
            lbl.lift()
        except tk.TclError:
            pass
    else:
        if lbl is not None:
            try:
                lbl.place_forget()
            except tk.TclError:
                pass


# ─── Araç çubuğu + menü + kısayollar ───────────────────────────────


def arac_cubugu_kur(dialog) -> None:
    """Tablo ile ürün şeridi arasına ince işlem çubuğu yerleştir."""
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is None:
        return
    parent = tablo.master
    if getattr(dialog, "_satir_arac_cubugu", None) is not None:
        try:
            dialog._satir_arac_cubugu.destroy()
        except tk.TclError:
            pass

    # Mevcut kaydırma çubuklarını ve özet çerçevesini bul
    dikey = yatay = ozet = None
    for w in parent.winfo_children():
        info = w.grid_info() if hasattr(w, "grid_info") else {}
        if not info:
            continue
        if isinstance(w, (ttk.Scrollbar, tk.Scrollbar)):
            if str(w.cget("orient")) == "vertical" or info.get("column") == "1":
                dikey = w
            else:
                yatay = w
        elif isinstance(w, ttk.LabelFrame):
            try:
                if "ÖZET" in str(w.cget("text")).upper():
                    ozet = w
            except tk.TclError:
                pass

    try:
        giris = dialog.satir_girdileri["urun_kodu"].master
        giris.grid_configure(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 2))
    except Exception:
        pass

    cubuk = tk.Frame(parent, bg="#0B2A4A", height=34)
    cubuk.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 2))
    dialog._satir_arac_cubugu = cubuk

    ic = tk.Frame(cubuk, bg="#0B2A4A")
    ic.pack(fill="x", padx=4, pady=2)

    def _btn(metin, komut):
        b = tk.Button(
            ic,
            text=metin,
            command=komut,
            font=("Segoe UI", 8),
            bg="#163E66",
            fg="#FFFFFF",
            activebackground="#1A4068",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
        )
        b.pack(side="left", padx=2)
        return b

    _btn("Satırı Düzenle", lambda: satir_duzenle(dialog))
    _btn("Satırı Sil", lambda: satir_sil(dialog))
    _btn("Satırı Çoğalt", lambda: satir_cogalt(dialog))
    _btn("Üste Taşı", lambda: satir_uste_tasi(dialog))
    _btn("Alta Taşı", lambda: satir_alta_tasi(dialog))
    _btn("Fiyatı Yenile", lambda: fiyati_yenile(dialog))
    _btn("Çoklu İskonto", lambda: _coklu_iskonto_duzenle(dialog))
    _btn("İskontoyu Temizle", lambda: iskontoyu_temizle(dialog))
    _btn("Satır Açıklaması", lambda: satir_aciklama_gir(dialog))
    if hasattr(dialog, "_fatura_kolon_ayarlari_ac"):
        _btn("Kolon Ayarları", dialog._fatura_kolon_ayarlari_ac)

    # Ürün şeridi 0 | araç 1 | tablo 2 | yatay 3 | özet 4
    try:
        tablo.grid_configure(row=2, column=0, sticky="nsew")
        if dikey is not None:
            dikey.grid_configure(row=2, column=1, sticky="ns")
        if yatay is not None:
            yatay.grid_configure(row=3, column=0, sticky="ew")
        if ozet is not None:
            ozet.grid_configure(row=4, column=0, columnspan=2, sticky="ew", pady=6)
        parent.rowconfigure(0, weight=0)
        parent.rowconfigure(1, weight=0)
        parent.rowconfigure(2, weight=1)
        parent.rowconfigure(3, weight=0)
        parent.rowconfigure(4, weight=0)
        parent.columnconfigure(0, weight=1)
    except tk.TclError:
        pass

    _bos_mesaj_guncelle(dialog)


def baglam_menu_kur(dialog) -> None:
    master = dialog
    try:
        if not hasattr(dialog, "tk"):
            master = dialog.satir_tablosu.winfo_toplevel()
    except Exception:
        master = dialog.satir_tablosu
    menu = tk.Menu(master, tearoff=0)
    menu.add_command(label="Düzenle", command=lambda: satir_duzenle(dialog))
    menu.add_command(label="Satırı Sil", command=lambda: satir_sil(dialog))
    menu.add_command(label="Satırı Çoğalt", command=lambda: satir_cogalt(dialog))
    menu.add_separator()
    menu.add_command(label="Üste Taşı", command=lambda: satir_uste_tasi(dialog))
    menu.add_command(label="Alta Taşı", command=lambda: satir_alta_tasi(dialog))
    menu.add_separator()
    menu.add_command(
        label="Fiyatı Stok Kartından Yenile", command=lambda: fiyati_yenile(dialog)
    )
    menu.add_command(
        label="Çoklu İskonto Düzenle",
        command=lambda: _coklu_iskonto_duzenle(dialog),
    )
    menu.add_command(label="İskontoyu Temizle", command=lambda: iskontoyu_temizle(dialog))
    menu.add_command(label="Satır Açıklaması Gir", command=lambda: satir_aciklama_gir(dialog))
    menu.add_separator()
    menu.add_command(label="Stok Kartını Aç", command=lambda: stok_kartini_ac(dialog))
    menu.add_command(
        label="Ürün Hareketlerini Göster", command=lambda: urun_hareketlerini_goster(dialog)
    )
    dialog._satir_ctx = menu

    def _sag_tik(event):
        tablo = dialog.satir_tablosu
        row = tablo.identify_row(event.y)
        satir_var = bool(row)
        if row:
            # Çoklu seçimde tıklanan zaten seçiliyse koru
            if row not in tablo.selection():
                tablo.selection_set(row)
            try:
                dialog._duzenlenen_satir = int(row)
            except (TypeError, ValueError):
                pass
        durum = "normal" if satir_var else "disabled"
        for i in range(menu.index("end") + 1):
            try:
                tip = menu.type(i)
            except tk.TclError:
                continue
            if tip == "command":
                menu.entryconfigure(i, state=durum)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    dialog.satir_tablosu.bind("<Button-3>", _sag_tik)


def kisayollar_kur(dialog) -> None:
    def _wrap(fn):
        def _inner(_e=None):
            if _metin_odakli_mi(dialog):
                return
            if getattr(dialog, "_satir_hucre_editor", None) is not None:
                return
            fn(dialog)
            return "break"

        return _inner

    binder = dialog if hasattr(dialog, "bind") else dialog.satir_tablosu
    binder.bind("<Delete>", _wrap(satir_sil))
    dialog.satir_tablosu.bind("<Delete>", _wrap(satir_sil))
    binder.bind("<Control-d>", _wrap(satir_cogalt))
    binder.bind("<Control-D>", _wrap(satir_cogalt))
    binder.bind("<Alt-Up>", _wrap(satir_uste_tasi))
    binder.bind("<Alt-Down>", _wrap(satir_alta_tasi))

    def _ctrl_s(_e=None):
        if _metin_odakli_mi(dialog) and getattr(dialog, "_satir_hucre_editor", None):
            return
        if hasattr(dialog, "kaydet"):
            dialog.kaydet()
        return "break"

    binder.bind("<Control-s>", _ctrl_s)
    binder.bind("<Control-S>", _ctrl_s)


def fatura_satir_araclari_kur(dialog) -> None:
    """Araç çubuğu + bağlam menüsü + kısayollar + boş mesaj."""
    if not hasattr(dialog, "satir_tablosu"):
        return
    try:
        dialog.satir_tablosu.configure(selectmode="extended")
    except tk.TclError:
        pass
    arac_cubugu_kur(dialog)
    baglam_menu_kur(dialog)
    kisayollar_kur(dialog)
    _bos_mesaj_guncelle(dialog)
