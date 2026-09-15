"""ÇEK / SENET İŞLEMLERİ — sekmeli ekran + CRUD + operasyonel akışlar + raporlar (Aşama 5)."""

from __future__ import annotations

import html
import re
import tempfile
import tkinter as tk
import webbrowser
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from database.cari_service import CariService
from database.cek_senet_service import CekSenetService
from database.finans_service import FinansService
from database.models.cek_senet import (
    DURUM_BANKAYA_TAHSILE,
    DURUM_BANKAYA_TEMINATA,
    DURUM_CIRO_EDILDI,
    DURUM_IADE,
    DURUM_KARSILIKSIZ,
    DURUM_KISMI_ODENDI,
    DURUM_KISMI_TAHSIL,
    DURUM_PORTFOYDE,
    DURUM_PROTESTO,
    DURUM_TEDARIKCIYE_VERILDI,
    EVRAK_TURU_FIRMA_CEKI,
    EVRAK_TURU_FIRMA_SENEDI,
    EVRAK_TURU_MUSTERI_CEKI,
    EVRAK_TURU_MUSTERI_SENEDI,
    ISLEM_YONU_ALINAN,
    ISLEM_YONU_VERILEN,
)
from ui_takvim import tarih_alani

# Liste sütunları (plan §12 — alt küme)
LISTE_KOLONLAR = (
    ("portfoy_no", "Portföy No", 110),
    ("evrak_turu", "Evrak Türü", 110),
    ("islem_yonu", "Alınan/Verilen", 90),
    ("evrak_no", "Evrak No", 90),
    ("cari_kodu", "Cari Kodu", 80),
    ("cari_adi", "Cari Adı", 160),
    ("banka", "Banka", 100),
    ("kesideci_borclu", "Keşideci/Borçlu", 120),
    ("duzenleme", "Düzenleme", 85),
    ("vade", "Vade", 85),
    ("kalan_gun", "Kalan Gün", 70),
    ("pb", "PB", 40),
    ("tutar", "Evrak Tutarı", 95),
    ("kur", "Kur", 60),
    ("tl", "TL Karşılığı", 95),
    ("tahsil", "Tahsil/Ödenen", 95),
    ("kalan", "Kalan", 90),
    ("durum", "Durum", 120),
    ("yer", "Bulunduğu Yer", 100),
    ("son_islem", "Son İşlem", 85),
    ("aciklama", "Açıklama", 140),
    ("kullanici", "Kayıt Yapan", 90),
)

HAREKET_KOLONLAR = (
    ("tarih", "Tarih/Saat", 120),
    ("portfoy_no", "Portföy No", 110),
    ("evrak_no", "Evrak No", 90),
    ("islem", "İşlem", 120),
    ("onceki", "Önceki Durum", 120),
    ("yeni", "Yeni Durum", 120),
    ("tutar", "Tutar", 90),
    ("aciklama", "Açıklama", 180),
    ("kullanici", "Kullanıcı", 90),
)

OZET_KUTULARI = (
    ("portfoy_musteri_cekleri", "Portföydeki müşteri çekleri"),
    ("portfoy_musteri_senetleri", "Portföydeki müşteri senetleri"),
    ("bankaya_tahsile", "Bankaya tahsile verilenler"),
    ("bankaya_teminata", "Bankaya teminata verilenler"),
    ("ciro_edilenler", "Ciro edilenler"),
    ("tahsil_edilenler", "Tahsil edilenler"),
    ("karsiliksiz_protestolu", "Karşılıksız/protestolu"),
    ("iade_edilenler", "İade edilenler"),
    ("firma_odenecek_cekler", "Firmamızın ödenecek çekleri"),
    ("firma_odenecek_senetler", "Firmamızın ödenecek senetleri"),
    ("bugun_vade", "Bugün vadesi gelenler"),
    ("vade_7_gun", "7 gün içinde vadesi gelenler"),
    ("vade_30_gun", "30 gün içinde vadesi gelenler"),
    ("vadesi_gecenler", "Vadesi geçenler"),
)

SEKME_TANIMLARI = (
    ("portfoy", "Portföydeki Evraklar", "portfoy"),
    ("verilen", "Verilen Evraklar", "verilen"),
    ("tahsil", "Tahsil Edilenler", "tahsil"),
    ("odenen", "Ödenenler", "odenen"),
    ("banka", "Bankadaki Evraklar", "banka"),
    ("ciro", "Ciro Edilenler", "ciro"),
    ("karsiliksiz", "Karşılıksız / Protestolu", "karsiliksiz"),
    ("iade", "İade Edilenler", "iade"),
    ("tum", "Tüm Hareketler", "tum_hareket"),
    ("raporlar", "Raporlar", None),
)

# anahtar, metin, aktif
TOOLBAR = (
    ("yeni", "Yeni Evrak", True),
    ("duzenle", "Düzenle", True),
    ("goruntule", "Görüntüle", True),
    ("bankaya", "Bankaya Ver", True),
    ("ciro", "Ciro Et", True),
    ("tahsil", "Tahsil Et", True),
    ("ode", "Öde", True),
    ("iade", "İade Et", True),
    ("karsiliksiz", "Karşılıksız/Protestolu", True),
    ("iptal", "İptal", True),
    ("hareketler", "Hareketler", True),
    ("yazdir", "Yazdır", True),
    ("excel", "Excel", True),
    ("pdf", "PDF", True),
)

# Raporlar sekmesi — (kod, combobox etiketi)
RAPOR_TANIMLARI = (
    ("portfoy_alinan", "Portföy dökümü — Alınan"),
    ("portfoy_verilen", "Portföy dökümü — Verilen"),
    ("vade_bugun", "Vade analizi — Bugün"),
    ("vade_7", "Vade analizi — 7 gün"),
    ("vade_30", "Vade analizi — 30 gün"),
    ("vade_gecen", "Vade analizi — Vadesi geçen"),
    ("durum_ozeti", "Durum özeti"),
    ("cari_risk", "Cari bazlı risk / açık evrak"),
)

RAPOR_EVRAK_KOLONLAR = (
    ("portfoy_no", "Portföy No", 100),
    ("evrak_turu", "Evrak Türü", 100),
    ("islem_yonu", "Alınan/Verilen", 90),
    ("evrak_no", "Evrak No", 80),
    ("cari_kodu", "Cari Kodu", 80),
    ("cari_adi", "Cari Adı", 150),
    ("vade", "Vade", 85),
    ("kalan_gun", "Kalan Gün", 70),
    ("tutar", "TL Tutarı", 90),
    ("kalan", "Kalan", 90),
    ("durum", "Durum", 120),
)

RAPOR_DURUM_KOLONLAR = (
    ("durum", "Durum", 200),
    ("adet", "Adet", 70),
    ("kalan", "Kalan Toplam", 110),
    ("tl", "TL Tutarı Toplam", 110),
)

RAPOR_CARI_KOLONLAR = (
    ("cari_kodu", "Cari Kodu", 90),
    ("cari_adi", "Cari Adı", 200),
    ("adet", "Açık Adet", 80),
    ("kalan", "Kalan Risk", 110),
    ("tl", "TL Tutarı", 110),
)

PARA_BIRIMLERI = ("TL", "USD", "EUR", "GBP")


def _para(tutar) -> str:
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih(t) -> str:
    if t is None:
        return ""
    if hasattr(t, "strftime"):
        return t.strftime("%d.%m.%Y")
    return str(t)


def _tarih_saat(t) -> str:
    if t is None:
        return ""
    if hasattr(t, "strftime"):
        return t.strftime("%d.%m.%Y %H:%M")
    return str(t)


def _cari_etiket(cari) -> str:
    return f"{cari.cari_kodu} - {cari.unvan}"


def _cari_listesini_yukle(cari_turu: str | None = None) -> tuple[list, dict[str, int], dict[int, Decimal]]:
    """Aktif cariler + etiket→id + bakiyeler (satış faturası ile aynı kaynak)."""
    kayitlar: list = []
    cari_map: dict[str, int] = {}
    bakiyeler: dict[int, Decimal] = {}
    try:
        ozetler = CariService.listele(hizli=True, cari_turu=cari_turu)
    except Exception:
        return kayitlar, cari_map, bakiyeler
    for o in ozetler:
        try:
            cari = o.get("cari") if isinstance(o, dict) else None
            if cari is None:
                continue
            etiket = _cari_etiket(cari)
            kayitlar.append(cari)
            cari_map[etiket] = cari.id
            bakiyeler[cari.id] = Decimal(str(o.get("bakiye") or 0))
        except Exception:
            continue
    return kayitlar, cari_map, bakiyeler


def _cari_metin_al(dialog) -> str:
    try:
        return (dialog.cari_var.get() or "").strip()
    except (tk.TclError, AttributeError):
        pass
    for ad in ("cari_combo", "cari_entry"):
        w = getattr(dialog, ad, None)
        if w is None:
            continue
        try:
            return (w.get() or "").strip()
        except (tk.TclError, AttributeError):
            continue
    return ""


def _cari_etiketlerini_al(dialog) -> list[str]:
    etiketler = getattr(dialog, "_tum_cari_etiketleri", None)
    if etiketler is not None:
        return list(etiketler)
    return list(getattr(dialog, "cari_map", {}).keys())


def _cari_combo_degerlerini_ayarla(dialog, degerler):
    combo = getattr(dialog, "cari_combo", None)
    if combo is None:
        return
    try:
        combo.configure(values=list(degerler))
    except tk.TclError:
        try:
            combo["values"] = list(degerler)
        except tk.TclError:
            pass


def _musteri_secim_dialog_sinifi():
    """app.MusteriSecimDialog — sys.modules ile dairesel import riskini azaltır."""
    import sys

    mod = sys.modules.get("app")
    if mod is not None and hasattr(mod, "MusteriSecimDialog"):
        return mod.MusteriSecimDialog
    from app import MusteriSecimDialog

    return MusteriSecimDialog


def _cari_arama_alani_kur(
    parent_dialog: tk.Toplevel,
    cari_frame: ttk.Frame,
    *,
    baslik: str = "Cari Seçimi",
    kayit_adi: str = "cari",
    salt_oku: bool = False,
):
    """Cari seçimi: Combobox ( ≥3 harf filtre listesi ) + Ara / F2 → MusteriSecimDialog."""
    cari_frame.columnconfigure(0, weight=1)
    parent_dialog.cari_var = tk.StringVar()
    etiketler = _cari_etiketlerini_al(parent_dialog)
    parent_dialog.cari_combo = ttk.Combobox(
        cari_frame,
        textvariable=parent_dialog.cari_var,
        values=etiketler,
        width=48,
    )
    parent_dialog.cari_combo.grid(row=0, column=0, sticky="ew")
    # Alias: Entry bekleyen kod / odak için
    parent_dialog.cari_entry = parent_dialog.cari_combo

    btn_f = ttk.Frame(cari_frame)
    btn_f.grid(row=0, column=1, sticky="w", padx=(6, 0))
    parent_dialog._cari_ara_btn = ttk.Button(
        btn_f,
        text="Ara",
        width=5,
        command=lambda: _cari_secim_penceresi_ac(parent_dialog, zorla=True),
    )
    parent_dialog._cari_ara_btn.pack(side="left")
    ttk.Label(
        cari_frame,
        text="≥3 harf liste / Ara / F2 seçim ekranı",
        foreground="#666",
        font=("Segoe UI", 8),
    ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

    parent_dialog._cari_sec_baslik = baslik
    parent_dialog._cari_sec_kayit_adi = kayit_adi
    parent_dialog._cari_arama_after = None
    parent_dialog._cari_sec_pencere = None

    if salt_oku:
        parent_dialog.cari_combo.configure(state="disabled")
        parent_dialog._cari_ara_btn.configure(state="disabled")
    else:
        parent_dialog.cari_combo.bind(
            "<KeyRelease>", lambda e: _cari_filtrele_debounce(parent_dialog, e)
        )
        parent_dialog.cari_combo.bind(
            "<F2>", lambda _e: _cari_secim_penceresi_ac(parent_dialog, zorla=True)
        )
        parent_dialog.bind(
            "<F2>", lambda _e: _cari_secim_penceresi_ac(parent_dialog, zorla=True)
        )


def _secili_cari_id(dialog) -> int | None:
    metin = _cari_metin_al(dialog)
    if not metin:
        return None
    cid = getattr(dialog, "cari_map", {}).get(metin)
    if cid:
        return cid
    for etiket, cid in getattr(dialog, "cari_map", {}).items():
        if etiket.casefold() == metin.casefold():
            return cid
    return None


def _secili_cari_nesne(dialog):
    cid = _secili_cari_id(dialog)
    if not cid:
        return None
    for cari in getattr(dialog, "_cari_kayitlari", []) or []:
        if cari.id == cid:
            return cari
    return None


def _cari_alana_yaz(dialog, metin: str):
    metin = metin or ""
    try:
        dialog.cari_var.set(metin)
    except (tk.TclError, AttributeError):
        combo = getattr(dialog, "cari_combo", None) or getattr(dialog, "cari_entry", None)
        if combo is None:
            return
        try:
            combo.set(metin)
        except tk.TclError:
            try:
                combo.delete(0, "end")
                if metin:
                    combo.insert(0, metin)
            except tk.TclError:
                pass
    # Seçim sonrası tam listeyi geri yükle (filtre daraltmış olabilir)
    etiketler = _cari_etiketlerini_al(dialog)
    if metin and metin not in etiketler:
        etiketler = [metin] + etiketler
    _cari_combo_degerlerini_ayarla(dialog, etiketler)


def _cari_secildi(dialog, cari):
    if not cari:
        return
    etiket = _cari_etiket(cari)
    if etiket not in getattr(dialog, "cari_map", {}):
        dialog.cari_map[etiket] = cari.id
        kayitlar = getattr(dialog, "_cari_kayitlari", None)
        if kayitlar is not None and cari not in kayitlar:
            kayitlar.append(cari)
        tum = getattr(dialog, "_tum_cari_etiketleri", None)
        if isinstance(tum, list) and etiket not in tum:
            tum.insert(0, etiket)
    _cari_alana_yaz(dialog, etiket)


def _cari_listesini_yenile_gerekirse(dialog) -> None:
    """Boş listeyle açılmayı önlemek için son çare yeniden yükleme."""
    if getattr(dialog, "_cari_kayitlari", None):
        return
    yenile = getattr(dialog, "_cari_listesini_yon_e_gore_yukle", None)
    if callable(yenile):
        try:
            yenile(ilk=True)
            return
        except Exception:
            pass
    kayitlar, cari_map, bakiyeler = _cari_listesini_yukle(None)
    dialog._cari_kayitlari = kayitlar
    dialog.cari_map = cari_map
    dialog._cari_bakiyeleri = bakiyeler
    dialog._tum_cari_etiketleri = list(cari_map.keys())
    _cari_combo_degerlerini_ayarla(dialog, dialog._tum_cari_etiketleri)


def _cari_secim_penceresi_ac(dialog, ara=None, zorla=False):
    if getattr(dialog, "_sadece_oku", False):
        return
    mevcut = getattr(dialog, "_cari_sec_pencere", None)
    if mevcut is not None:
        try:
            if mevcut.winfo_exists():
                try:
                    mevcut.lift()
                    mevcut.focus_force()
                except tk.TclError:
                    pass
                return
        except tk.TclError:
            pass
    if ara is None:
        ara = _cari_metin_al(dialog)
    if not zorla:
        secili = _secili_cari_nesne(dialog)
        if secili and (ara or "").strip() == _cari_etiket(secili):
            return
        if len((ara or "").strip()) < 3:
            return
    try:
        _cari_listesini_yenile_gerekirse(dialog)
        musteriler = getattr(dialog, "_cari_kayitlari", []) or []
        if not musteriler and zorla:
            messagebox.showinfo(
                "Cari",
                "Gösterilecek cari bulunamadı. Firma / cari kartlarını kontrol edin.",
                parent=dialog,
            )
            return
        MusteriSecimDialog = _musteri_secim_dialog_sinifi()
        dlg = MusteriSecimDialog(
            dialog,
            musteriler=musteriler,
            bakiyeler=getattr(dialog, "_cari_bakiyeleri", {}) or {},
            ara=ara or "",
            on_select=lambda c: _cari_secildi(dialog, c),
            baslik=getattr(dialog, "_cari_sec_baslik", "Cari Seçimi"),
            kayit_adi=getattr(dialog, "_cari_sec_kayit_adi", "cari"),
        )
        try:
            dlg.lift()
            dlg.focus_force()
        except tk.TclError:
            pass
        dialog._cari_sec_pencere = dlg
        dialog.wait_window(dlg)
    except Exception as e:
        messagebox.showerror(
            "Cari seçimi",
            f"Cari seçim ekranı açılamadı:\n{e}",
            parent=dialog,
        )
    finally:
        dialog._cari_sec_pencere = None
    try:
        dialog.cari_combo.focus_set()
        dialog.cari_combo.icursor("end")
    except tk.TclError:
        pass


def _cari_combo_filtrele(dialog) -> str:
    """Combobox values: boş=tümü, <3=boş liste, ≥3=kod/ünvan contains."""
    etiketler = _cari_etiketlerini_al(dialog)
    metin = _cari_metin_al(dialog)
    if not metin:
        _cari_combo_degerlerini_ayarla(dialog, etiketler)
        return metin
    if len(metin) < 3:
        _cari_combo_degerlerini_ayarla(dialog, ())
        return metin
    ara = metin.casefold()
    bulunan = [e for e in etiketler if ara in e.casefold()]
    _cari_combo_degerlerini_ayarla(dialog, bulunan)
    return metin


def _cari_filtrele_debounce(dialog, event=None):
    if event and getattr(event, "keysym", "") in (
        "Up",
        "Down",
        "Return",
        "Escape",
        "Tab",
        "Left",
        "Right",
        "Prior",
        "Next",
        "Shift_L",
        "Shift_R",
        "Control_L",
        "Control_R",
        "Alt_L",
        "Alt_R",
        "Caps_Lock",
        "F2",
    ):
        return
    if event is not None:
        try:
            if int(event.type) == 2:  # KeyPress
                return
        except (TypeError, ValueError):
            pass
    metin = _cari_combo_filtrele(dialog)
    if len(metin) < 3:
        after_id = getattr(dialog, "_cari_arama_after", None)
        if after_id:
            try:
                dialog.after_cancel(after_id)
            except tk.TclError:
                pass
            dialog._cari_arama_after = None
        return
    secili = _secili_cari_nesne(dialog)
    if secili and metin == _cari_etiket(secili):
        return
    after_id = getattr(dialog, "_cari_arama_after", None)
    if after_id:
        try:
            dialog.after_cancel(after_id)
        except tk.TclError:
            pass
    dialog._cari_arama_after = dialog.after(
        280, lambda m=metin: _cari_secim_ac_gecikmeli(dialog, m)
    )


def _cari_secim_ac_gecikmeli(dialog, metin: str):
    dialog._cari_arama_after = None
    guncel = _cari_metin_al(dialog)
    if guncel != metin or len(guncel) < 3:
        return
    _cari_secim_penceresi_ac(dialog, ara=guncel)


def _dosya_adi_parca(metin: str, varsayilan: str = "cek_senet") -> str:
    metin = (metin or "").strip() or varsayilan
    metin = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", metin)
    metin = re.sub(r"\s+", "_", metin).strip("._")
    return (metin[:50] or varsayilan)


def _tree_baslik_satir(tablo: ttk.Treeview) -> tuple[list[str], list[list[str]]]:
    """Treeview görünür sütun başlıkları + satır değerleri."""
    kolonlar = list(tablo["columns"])
    basliklar = [tablo.heading(k)["text"] or str(k) for k in kolonlar]
    satirlar = []
    for iid in tablo.get_children():
        degerler = tablo.item(iid, "values") or ()
        satirlar.append([str(d) if d is not None else "" for d in degerler])
    return basliklar, satirlar


def _excel_aktar(
    parent,
    baslik: str,
    sutunlar: list[str],
    satirlar: list[list],
    *,
    initialfile: str | None = None,
) -> Path | None:
    if not satirlar:
        messagebox.showinfo("Excel", "Aktarılacak kayıt yok.", parent=parent)
        return None
    try:
        from openpyxl import Workbook
    except ImportError:
        messagebox.showerror(
            "Excel",
            "openpyxl yüklü değil. Kurulum: pip install openpyxl",
            parent=parent,
        )
        return None

    bugun = date.today().strftime("%Y%m%d")
    yol = filedialog.asksaveasfilename(
        parent=parent,
        title="Excel'e aktar",
        defaultextension=".xlsx",
        filetypes=[("Excel", "*.xlsx"), ("Tüm dosyalar", "*.*")],
        initialfile=initialfile or f"{_dosya_adi_parca(baslik)}_{bugun}.xlsx",
    )
    if not yol:
        return None
    if not str(yol).lower().endswith(".xlsx"):
        yol = f"{yol}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = (baslik or "Rapor")[:31]
    ws.append(["Rapor", baslik])
    ws.append(["Aktarım Tarihi", datetime.now().strftime("%d.%m.%Y %H:%M")])
    ws.append([])
    ws.append(list(sutunlar))
    for satir in satirlar:
        ws.append(list(satir))
    try:
        wb.save(yol)
    except PermissionError:
        messagebox.showerror(
            "Excel",
            "Dosya kaydedilemedi. Dosya başka bir programda açık olabilir.\n"
            f"Yol: {yol}",
            parent=parent,
        )
        return None
    except OSError as hata:
        messagebox.showerror("Excel", f"Dosya kaydedilemedi:\n{hata}", parent=parent)
        return None

    messagebox.showinfo("Excel", f"Kaydedildi:\n{Path(yol)}", parent=parent)
    return Path(yol)


def _basit_pdf_olustur(baslik: str, satirlar: list[str], yol: Path) -> Path:
    """Bağımlılıksız metin PDF (muhasebe raporları ile aynı yaklaşım)."""
    yol.parent.mkdir(parents=True, exist_ok=True)
    icerik = [baslik, ""] + list(satirlar)

    def esc(t: str) -> str:
        return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    y = 800
    content = ["BT", "/F1 9 Tf", "40 800 Td"]
    first = True
    for line in icerik:
        safe = esc(line[:110])
        if first:
            content.append(f"({safe}) Tj")
            first = False
        else:
            content.append("0 -12 Td")
            content.append(f"({safe}) Tj")
            y -= 12
            if y < 40:
                break
    content.append("ET")
    stream = "\n".join(content).encode("latin-1", errors="replace")

    objs = []
    objs.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objs.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objs.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
    )
    objs.append(
        f"4 0 obj<< /Length {len(stream)} >>stream\n".encode()
        + stream
        + b"\nendstream\nendobj\n"
    )
    objs.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objs:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(offsets)}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode())
    out.extend(
        f"trailer<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    yol.write_bytes(out)
    return yol


def _pdf_aktar(
    parent,
    baslik: str,
    sutunlar: list[str],
    satirlar: list[list],
    *,
    initialfile: str | None = None,
) -> Path | None:
    if not satirlar:
        messagebox.showinfo("PDF", "Aktarılacak kayıt yok.", parent=parent)
        return None
    bugun = date.today().strftime("%Y%m%d")
    yol = filedialog.asksaveasfilename(
        parent=parent,
        title="PDF kaydet",
        defaultextension=".pdf",
        filetypes=[("PDF", "*.pdf")],
        initialfile=initialfile or f"{_dosya_adi_parca(baslik)}_{bugun}.pdf",
    )
    if not yol:
        return None
    if not str(yol).lower().endswith(".pdf"):
        yol = f"{yol}.pdf"

    ayirici = " | "
    lines = [ayirici.join(sutunlar)]
    lines.append("-" * min(100, max(20, len(lines[0]))))
    for satir in satirlar:
        lines.append(ayirici.join(str(c) for c in satir))
    try:
        _basit_pdf_olustur(baslik, lines, Path(yol))
    except OSError as hata:
        messagebox.showerror("PDF", f"Dosya kaydedilemedi:\n{hata}", parent=parent)
        return None
    messagebox.showinfo("PDF", f"Kaydedildi:\n{Path(yol)}", parent=parent)
    return Path(yol)


def _html_yazdir(parent, baslik: str, sutunlar: list[str], satirlar: list[list]):
    if not satirlar:
        messagebox.showinfo("Yazdır", "Yazdırılacak kayıt yok.", parent=parent)
        return
    thead = "".join(f"<th>{html.escape(str(s))}</th>" for s in sutunlar)
    govde = []
    for i, satir in enumerate(satirlar):
        cls = ' class="cift"' if i % 2 else ""
        hucreler = "".join(f"<td>{html.escape(str(c))}</td>" for c in satir)
        govde.append(f"<tr{cls}>{hucreler}</tr>")
    meta = datetime.now().strftime("%d.%m.%Y %H:%M")
    icerik = f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8"/>
<title>{html.escape(baslik)}</title>
<style>
  body {{ font-family: 'Segoe UI', Tahoma, sans-serif; margin: 16px; color: #111; font-size: 9pt; }}
  .toolbar {{ margin-bottom: 12px; }}
  .toolbar button {{ padding: 6px 14px; font-size: 13px; cursor: pointer; }}
  h1 {{ font-size: 14pt; margin: 0 0 4px; }}
  .meta {{ color: #444; margin-bottom: 10px; font-size: 8.5pt; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border-bottom: 1px solid #ccc; padding: 4px 6px; text-align: left; vertical-align: top; }}
  th {{ background: #f0f0f0; font-weight: 700; white-space: nowrap; }}
  tr.cift td {{ background: #fafafa; }}
  @media print {{ .toolbar {{ display: none !important; }} body {{ margin: 10mm; }} }}
</style>
</head>
<body>
  <div class="toolbar"><button type="button" onclick="window.print()">Yazdır</button></div>
  <h1>{html.escape(baslik)}</h1>
  <div class="meta">{html.escape(meta)} · {len(satirlar)} kayıt</div>
  <table>
    <thead><tr>{thead}</tr></thead>
    <tbody>{"".join(govde)}</tbody>
  </table>
</body>
</html>
"""
    klasor = Path(tempfile.gettempdir()) / "muhasebe_belge"
    klasor.mkdir(exist_ok=True)
    guvenli = _dosya_adi_parca(baslik, "cek_senet")
    dosya = klasor / f"{guvenli}.html"
    dosya.write_text(icerik, encoding="utf-8")
    webbrowser.open(dosya.as_uri())
    messagebox.showinfo(
        "Yazdırma",
        "Liste tarayıcıda açıldı.\n"
        "Yazdır iletişim kutusu için Yazdır düğmesine basın veya Ctrl+P kullanın.",
        parent=parent,
    )


def _finans_menu_isaretle(app):
    for anahtar, dugme in app.menu_dugmeleri.items():
        dugme.configure(
            style="SeciliMenu.TButton" if anahtar == "finans" else "Menu.TButton"
        )


def cek_senet_islemleri_goster(app):
    """Finans > ÇEK / SENET İŞLEMLERİ ana ekranı."""
    app._icerigi_temizle()
    _finans_menu_isaretle(app)

    try:
        CekSenetService.schema_hazirla()
    except Exception as e:
        messagebox.showwarning(
            "Çek/Senet",
            f"Tablo hazırlığı uyarısı:\n{e}",
            parent=app,
        )

    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="ÇEK / SENET İŞLEMLERİ", style="Baslik.TLabel").pack(side="left")
    ttk.Button(ust, text="← Finans Menüsü", command=lambda: _finans_geri(app)).pack(
        side="right"
    )

    # ——— Özet kutuları ———
    ozet_cerceve = ttk.LabelFrame(app.icerik, text="Özet (TL)", padding=6)
    ozet_cerceve.pack(fill="x", pady=(10, 6))
    ozet_etiketleri: dict[str, ttk.Label] = {}
    sutun = 7
    for i, (anahtar, baslik) in enumerate(OZET_KUTULARI):
        r, c = divmod(i, sutun)
        kutu = ttk.Frame(ozet_cerceve, padding=4)
        kutu.grid(row=r, column=c, sticky="nsew", padx=3, pady=3)
        ttk.Label(kutu, text=baslik, wraplength=130, font=("Segoe UI", 8)).pack(anchor="w")
        lbl = ttk.Label(kutu, text="0 adet\n0,00 TL", font=("Segoe UI", 9, "bold"))
        lbl.pack(anchor="w")
        ozet_etiketleri[anahtar] = lbl
    for c in range(sutun):
        ozet_cerceve.columnconfigure(c, weight=1)

    # ——— Araç çubuğu ———
    arac = ttk.Frame(app.icerik)
    arac.pack(fill="x", pady=(4, 4))
    arama_var = tk.StringVar()
    ttk.Label(arac, text="Ara:").pack(side="left")
    arama_giris = ttk.Entry(arac, textvariable=arama_var, width=22)
    arama_giris.pack(side="left", padx=(4, 10))

    durum = {"aktif_sekme": "portfoy", "tablolar": {}, "toolbar": {}}

    def stub(ad: str):
        messagebox.showinfo(
            "Çek/Senet",
            f"«{ad}» sonraki aşamada eklenecek.",
            parent=app,
        )

    def _aktif_liste_tablosu():
        aktif = durum["aktif_sekme"]
        if aktif in ("raporlar", "tum"):
            return None
        bilgi = durum["tablolar"].get(aktif)
        if not bilgi or bilgi[0] != "liste":
            return None
        return bilgi[1]

    def _secili_evrak_id():
        tablo = _aktif_liste_tablosu()
        if tablo is None:
            messagebox.showinfo(
                "Seçim",
                "Bu işlem için Portföy / Verilen gibi bir evrak listesi sekmesi açın.",
                parent=app,
            )
            return None
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Listeden bir evrak seçin.", parent=app)
            return None
        try:
            return int(secim[0])
        except (TypeError, ValueError):
            return None

    def yeni_evrak():
        dlg = EvrakDialog(app, mod="yeni", on_kaydet=yenile)
        app.wait_window(dlg)

    def duzenle():
        eid = _secili_evrak_id()
        if not eid:
            return
        detay = CekSenetService.getir(eid)
        if not detay:
            messagebox.showwarning("Çek/Senet", "Evrak bulunamadı.", parent=app)
            return
        if not detay.get("duzenlenebilir"):
            messagebox.showwarning(
                "Düzenle",
                f"Bu evrak düzenlenemez.\nDurum: {detay.get('durum_etiket')}",
                parent=app,
            )
            return
        dlg = EvrakDialog(app, mod="duzenle", evrak=detay, on_kaydet=yenile)
        app.wait_window(dlg)

    def goruntule():
        eid = _secili_evrak_id()
        if not eid:
            return
        detay = CekSenetService.getir(eid)
        if not detay:
            messagebox.showwarning("Çek/Senet", "Evrak bulunamadı.", parent=app)
            return
        dlg = EvrakDialog(app, mod="goruntule", evrak=detay)
        app.wait_window(dlg)

    def iptal_et():
        eid = _secili_evrak_id()
        if not eid:
            return
        detay = CekSenetService.getir(eid)
        if not detay:
            messagebox.showwarning("Çek/Senet", "Evrak bulunamadı.", parent=app)
            return
        if not detay.get("iptal_edilebilir"):
            messagebox.showwarning(
                "İptal",
                f"Bu evrak iptal edilemez.\nDurum: {detay.get('durum_etiket')}",
                parent=app,
            )
            return
        if not messagebox.askyesno(
            "İptal",
            f"{detay.get('portfoy_no')} nolu evrak iptal edilsin mi?\n"
            f"({detay.get('evrak_no')} — {_para(detay.get('tl_tutari'))})",
            parent=app,
        ):
            return
        try:
            CekSenetService.iptal(eid, aciklama="Kullanıcı iptali")
            yenile()
            messagebox.showinfo("İptal", "Evrak iptal edildi.", parent=app)
        except Exception as e:
            messagebox.showerror("İptal", str(e), parent=app)

    def hareketler_goster():
        eid = _secili_evrak_id()
        if not eid:
            return
        detay = CekSenetService.getir(eid)
        if not detay:
            messagebox.showwarning("Çek/Senet", "Evrak bulunamadı.", parent=app)
            return
        dlg = EvrakHareketlerDialog(app, detay)
        app.wait_window(dlg)

    def _islem_dialog(dlg_cls, baslik_hata: str):
        eid = _secili_evrak_id()
        if not eid:
            return
        detay = CekSenetService.getir(eid)
        if not detay:
            messagebox.showwarning("Çek/Senet", "Evrak bulunamadı.", parent=app)
            return
        try:
            dlg = dlg_cls(app, detay, on_kaydet=yenile)
        except Exception as e:
            messagebox.showwarning(baslik_hata, str(e), parent=app)
            return
        app.wait_window(dlg)

    def bankaya_ver():
        _islem_dialog(BankayaVerDialog, "Bankaya Ver")

    def ciro_et():
        _islem_dialog(CiroEtDialog, "Ciro Et")

    def tahsil_et():
        _islem_dialog(TahsilEtDialog, "Tahsil Et")

    def ode():
        _islem_dialog(OdeDialog, "Öde")

    def iade_et():
        _islem_dialog(IadeEtDialog, "İade Et")

    def karsiliksiz():
        _islem_dialog(KarsiliksizDialog, "Karşılıksız/Protestolu")

    def _export_kaynak():
        """Aktif sekmeden (başlık, sütunlar, satırlar) — görünür Treeview verisi."""
        aktif = durum["aktif_sekme"]
        if aktif == "raporlar":
            bilgi = durum.get("rapor")
            if not bilgi:
                return None
            tablo = bilgi["tablo"]
            basliklar, satirlar = _tree_baslik_satir(tablo)
            return bilgi.get("baslik") or "Çek/Senet Raporu", basliklar, satirlar
        bilgi = durum["tablolar"].get(aktif)
        if not bilgi:
            return None
        _tur, tablo = bilgi
        sekme_baslik = next(
            (b for sid, b, _f in SEKME_TANIMLARI if sid == aktif), "Çek/Senet"
        )
        basliklar, satirlar = _tree_baslik_satir(tablo)
        return f"Çek/Senet — {sekme_baslik}", basliklar, satirlar

    def excel_aktar():
        kaynak = _export_kaynak()
        if kaynak is None:
            messagebox.showinfo(
                "Excel",
                "Aktarım için bir liste veya rapor sekmesi açın.",
                parent=app,
            )
            return
        baslik, sutunlar, satirlar = kaynak
        _excel_aktar(app, baslik, sutunlar, satirlar)

    def pdf_aktar():
        kaynak = _export_kaynak()
        if kaynak is None:
            messagebox.showinfo(
                "PDF",
                "Aktarım için bir liste veya rapor sekmesi açın.",
                parent=app,
            )
            return
        baslik, sutunlar, satirlar = kaynak
        _pdf_aktar(app, baslik, sutunlar, satirlar)

    def yazdir():
        kaynak = _export_kaynak()
        if kaynak is None:
            messagebox.showinfo(
                "Yazdır",
                "Yazdırma için bir liste veya rapor sekmesi açın.",
                parent=app,
            )
            return
        baslik, sutunlar, satirlar = kaynak
        _html_yazdir(app, baslik, sutunlar, satirlar)

    komutlar = {
        "yeni": yeni_evrak,
        "duzenle": duzenle,
        "goruntule": goruntule,
        "bankaya": bankaya_ver,
        "ciro": ciro_et,
        "tahsil": tahsil_et,
        "ode": ode,
        "iade": iade_et,
        "karsiliksiz": karsiliksiz,
        "iptal": iptal_et,
        "hareketler": hareketler_goster,
        "yazdir": yazdir,
        "excel": excel_aktar,
        "pdf": pdf_aktar,
    }

    for anahtar, metin, aktif in TOOLBAR:
        cmd = komutlar.get(anahtar) or (lambda m=metin: stub(m))
        btn = ttk.Button(arac, text=metin, command=cmd)
        btn.pack(side="left", padx=2)
        durum["toolbar"][anahtar] = btn
        if not aktif:
            btn.state(["disabled"])

    ttk.Button(arac, text="Yenile", command=lambda: yenile()).pack(side="right")

    # ——— Sekmeler ———
    defter = ttk.Notebook(app.icerik)
    defter.pack(fill="both", expand=True, pady=(4, 0))

    for sekme_id, baslik, _filtre in SEKME_TANIMLARI:
        sayfa = ttk.Frame(defter, padding=4)
        defter.add(sayfa, text=baslik)
        if sekme_id == "raporlar":
            _raporlar_sekmesi_kur(sayfa, app, durum)
            continue
        if sekme_id == "tum":
            tablo = _treeview_kur(sayfa, HAREKET_KOLONLAR)
            durum["tablolar"][sekme_id] = ("hareket", tablo)
        else:
            tablo = _treeview_kur(sayfa, LISTE_KOLONLAR)
            durum["tablolar"][sekme_id] = ("liste", tablo)
            tablo.bind("<Double-1>", lambda _e: goruntule())

    alt_ozet = ttk.Label(app.icerik, text="")
    alt_ozet.pack(anchor="w", pady=(4, 0))

    def ozet_yenile():
        veri = CekSenetService.ozet()
        for anahtar, _baslik in OZET_KUTULARI:
            o = veri.get(anahtar) or {"adet": 0, "tutar": 0}
            ozet_etiketleri[anahtar].configure(
                text=f"{o['adet']} adet\n{_para(o['tutar'])}"
            )

    def liste_doldur(sekme_id: str):
        bilgi = durum["tablolar"].get(sekme_id)
        if not bilgi:
            return
        tur, tablo = bilgi
        for item in tablo.get_children():
            tablo.delete(item)
        arama = arama_var.get()
        if tur == "hareket":
            kayitlar = CekSenetService.hareketleri_listele()
            for k in kayitlar:
                tablo.insert(
                    "",
                    "end",
                    iid=str(k["id"]),
                    values=(
                        _tarih_saat(k["tarih"]),
                        k["portfoy_no"],
                        k["evrak_no"],
                        k["islem_turu"],
                        k["onceki_durum"],
                        k["yeni_durum"],
                        _para(k["tutar"]) if k["tutar"] is not None else "",
                        k["aciklama"],
                        k["kullanici"],
                    ),
                )
            alt_ozet.configure(text=f"{len(kayitlar)} hareket kaydı")
            return

        filtre = next((f for sid, _b, f in SEKME_TANIMLARI if sid == sekme_id), None)
        kayitlar = CekSenetService.listele(sekme=filtre, arama=arama)
        for k in kayitlar:
            tablo.insert(
                "",
                "end",
                iid=str(k["id"]),
                values=(
                    k["portfoy_no"],
                    k["evrak_turu_etiket"],
                    k["islem_yonu_etiket"],
                    k["evrak_no"],
                    k["cari_kodu"],
                    k["cari_adi"],
                    k["banka"],
                    k["kesideci_borclu"],
                    _tarih(k["duzenleme_tarihi"]),
                    _tarih(k["vade_tarihi"]),
                    "" if k["kalan_gun"] is None else k["kalan_gun"],
                    k["doviz_turu"],
                    _para(k["doviz_tutari"]),
                    f"{float(k['kur'] or 0):,.4f}".replace(",", "X")
                    .replace(".", ",")
                    .replace("X", "."),
                    _para(k["tl_tutari"]),
                    _para(k["tahsil_edilen"]),
                    _para(k["kalan_tutar"]),
                    k["durum_etiket"],
                    k["bulundugu_yer"],
                    _tarih(k["son_islem_tarihi"]),
                    k["aciklama"],
                    k["created_by"],
                ),
            )
        toplam = sum(float(k["kalan_tutar"] or 0) for k in kayitlar)
        alt_ozet.configure(
            text=f"{len(kayitlar)} kayıt  |  Kalan toplam: {_para(toplam)}"
        )

    def yenile():
        ozet_yenile()
        aktif = durum["aktif_sekme"]
        if aktif == "raporlar":
            yenile_fn = (durum.get("rapor") or {}).get("yenile")
            if callable(yenile_fn):
                yenile_fn()
            return
        liste_doldur(aktif)

    def sekme_degisti(_event=None):
        try:
            idx = defter.index(defter.select())
        except tk.TclError:
            return
        if 0 <= idx < len(SEKME_TANIMLARI):
            durum["aktif_sekme"] = SEKME_TANIMLARI[idx][0]
            yenile()

    defter.bind("<<NotebookTabChanged>>", sekme_degisti)
    arama_giris.bind("<Return>", lambda _e: yenile())

    yenile()


def _finans_geri(app):
    from finans_ui import finans_menusu_goster

    finans_menusu_goster(app)


def _treeview_kur(parent, kolonlar) -> ttk.Treeview:
    cerceve = ttk.Frame(parent)
    cerceve.pack(fill="both", expand=True)
    keys = tuple(k for k, _b, _w in kolonlar)
    tablo = ttk.Treeview(cerceve, columns=keys, show="headings", selectmode="browse")
    for k, b, w in kolonlar:
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w", minwidth=40)
    y = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    x = ttk.Scrollbar(cerceve, orient="horizontal", command=tablo.xview)
    tablo.configure(yscrollcommand=y.set, xscrollcommand=x.set)
    tablo.grid(row=0, column=0, sticky="nsew")
    y.grid(row=0, column=1, sticky="ns")
    x.grid(row=1, column=0, sticky="ew")
    cerceve.rowconfigure(0, weight=1)
    cerceve.columnconfigure(0, weight=1)
    return tablo


def _rapor_tree_yeniden_kur(parent_frame, kolonlar) -> ttk.Treeview:
    for child in parent_frame.winfo_children():
        child.destroy()
    return _treeview_kur(parent_frame, kolonlar)


def _raporlar_sekmesi_kur(sayfa, app, durum: dict):
    """Raporlar sekmesi: tür seçimi + önizleme + Excel/PDF/Yazdır."""
    ust = ttk.Frame(sayfa)
    ust.pack(fill="x", pady=(0, 6))
    ttk.Label(ust, text="Rapor:").pack(side="left")
    etiketler = [e for _k, e in RAPOR_TANIMLARI]
    kod_map = {e: k for k, e in RAPOR_TANIMLARI}
    rapor_var = tk.StringVar(value=etiketler[0])
    cb = ttk.Combobox(
        ust, textvariable=rapor_var, values=etiketler, state="readonly", width=36
    )
    cb.pack(side="left", padx=(6, 10))

    tablo_alan = ttk.Frame(sayfa)
    tablo_alan.pack(fill="both", expand=True)
    ozet_lbl = ttk.Label(sayfa, text="")
    ozet_lbl.pack(anchor="w", pady=(4, 0))

    durum["rapor"] = {
        "tablo": None,
        "baslik": etiketler[0],
        "kod": RAPOR_TANIMLARI[0][0],
        "yenile": None,
    }

    def _evrak_satir_values(k: dict) -> tuple:
        return (
            k.get("portfoy_no") or "",
            k.get("evrak_turu_etiket") or "",
            k.get("islem_yonu_etiket") or "",
            k.get("evrak_no") or "",
            k.get("cari_kodu") or "",
            k.get("cari_adi") or "",
            _tarih(k.get("vade_tarihi")),
            "" if k.get("kalan_gun") is None else k["kalan_gun"],
            _para(k.get("tl_tutari")),
            _para(k.get("kalan_tutar")),
            k.get("durum_etiket") or "",
        )

    def yenile_rapor(_event=None):
        etiket = rapor_var.get()
        kod = kod_map.get(etiket, RAPOR_TANIMLARI[0][0])
        baslik = etiket

        if kod == "durum_ozeti":
            kolonlar = RAPOR_DURUM_KOLONLAR
            kayitlar = CekSenetService.rapor_durum_ozeti()
            tablo = _rapor_tree_yeniden_kur(tablo_alan, kolonlar)
            for i, k in enumerate(kayitlar):
                tablo.insert(
                    "",
                    "end",
                    iid=str(i),
                    values=(
                        k["durum_etiket"],
                        k["adet"],
                        _para(k["kalan_tutar"]),
                        _para(k["tl_tutari"]),
                    ),
                )
            toplam_adet = sum(int(k["adet"]) for k in kayitlar)
            toplam_kalan = sum(float(k["kalan_tutar"] or 0) for k in kayitlar)
            ozet_lbl.configure(
                text=f"{toplam_adet} evrak  |  {len(kayitlar)} durum  |  "
                f"Kalan: {_para(toplam_kalan)}"
            )
        elif kod == "cari_risk":
            kolonlar = RAPOR_CARI_KOLONLAR
            kayitlar = CekSenetService.rapor_cari_risk()
            tablo = _rapor_tree_yeniden_kur(tablo_alan, kolonlar)
            for i, k in enumerate(kayitlar):
                tablo.insert(
                    "",
                    "end",
                    iid=str(i),
                    values=(
                        k["cari_kodu"],
                        k["cari_adi"],
                        k["adet"],
                        _para(k["kalan_tutar"]),
                        _para(k["tl_tutari"]),
                    ),
                )
            toplam_kalan = sum(float(k["kalan_tutar"] or 0) for k in kayitlar)
            ozet_lbl.configure(
                text=f"{len(kayitlar)} cari  |  Açık risk toplamı: {_para(toplam_kalan)}"
            )
        else:
            kolonlar = RAPOR_EVRAK_KOLONLAR
            if kod == "portfoy_alinan":
                kayitlar = CekSenetService.rapor_portfoy_dokumu(ISLEM_YONU_ALINAN)
            elif kod == "portfoy_verilen":
                kayitlar = CekSenetService.rapor_portfoy_dokumu(ISLEM_YONU_VERILEN)
            elif kod == "vade_bugun":
                kayitlar = CekSenetService.rapor_vade_analiz("bugun")
            elif kod == "vade_7":
                kayitlar = CekSenetService.rapor_vade_analiz("7")
            elif kod == "vade_30":
                kayitlar = CekSenetService.rapor_vade_analiz("30")
            else:
                kayitlar = CekSenetService.rapor_vade_analiz("gecen")
            tablo = _rapor_tree_yeniden_kur(tablo_alan, kolonlar)
            for k in kayitlar:
                tablo.insert("", "end", iid=str(k["id"]), values=_evrak_satir_values(k))
            toplam = sum(float(k.get("kalan_tutar") or 0) for k in kayitlar)
            ozet_lbl.configure(
                text=f"{len(kayitlar)} kayıt  |  Kalan toplam: {_para(toplam)}"
            )

        durum["rapor"]["tablo"] = tablo
        durum["rapor"]["baslik"] = f"Çek/Senet — {baslik}"
        durum["rapor"]["kod"] = kod

    def rapor_excel():
        bilgi = durum.get("rapor") or {}
        tablo = bilgi.get("tablo")
        if tablo is None:
            yenile_rapor()
            tablo = durum["rapor"]["tablo"]
        basliklar, satirlar = _tree_baslik_satir(tablo)
        _excel_aktar(app, bilgi.get("baslik") or "Rapor", basliklar, satirlar)

    def rapor_pdf():
        bilgi = durum.get("rapor") or {}
        tablo = bilgi.get("tablo")
        if tablo is None:
            yenile_rapor()
            tablo = durum["rapor"]["tablo"]
        basliklar, satirlar = _tree_baslik_satir(tablo)
        _pdf_aktar(app, bilgi.get("baslik") or "Rapor", basliklar, satirlar)

    def rapor_yazdir():
        bilgi = durum.get("rapor") or {}
        tablo = bilgi.get("tablo")
        if tablo is None:
            yenile_rapor()
            tablo = durum["rapor"]["tablo"]
        basliklar, satirlar = _tree_baslik_satir(tablo)
        _html_yazdir(app, bilgi.get("baslik") or "Rapor", basliklar, satirlar)

    ttk.Button(ust, text="Göster", command=yenile_rapor).pack(side="left", padx=2)
    ttk.Button(ust, text="Excel", command=rapor_excel).pack(side="left", padx=2)
    ttk.Button(ust, text="PDF", command=rapor_pdf).pack(side="left", padx=2)
    ttk.Button(ust, text="Yazdır", command=rapor_yazdir).pack(side="left", padx=2)

    cb.bind("<<ComboboxSelected>>", yenile_rapor)
    durum["rapor"]["yenile"] = yenile_rapor
    yenile_rapor()


class EvrakDialog(tk.Toplevel):
    """Yeni / Düzenle / Görüntüle evrak formu."""

    def __init__(self, parent, mod: str = "yeni", evrak: dict | None = None, on_kaydet=None):
        super().__init__(parent)
        self.mod = mod  # yeni | duzenle | goruntule
        self.evrak = evrak or {}
        self.on_kaydet = on_kaydet
        self.result = None
        self._sadece_oku = mod == "goruntule"

        if mod == "yeni":
            self.title("Yeni Evrak")
        elif mod == "duzenle":
            self.title(f"Evrak Düzenle — {self.evrak.get('portfoy_no', '')}")
        else:
            self.title(f"Evrak Görüntüle — {self.evrak.get('portfoy_no', '')}")

        self.geometry("720x640")
        self.minsize(640, 520)
        self.transient(parent)
        self.grab_set()

        # Cari listesi (Alınan→müşteri, Verilen→tedarikçi; yön değişince yenilenir)
        self.cari_map: dict[str, int] = {}
        self._cari_kayitlari: list = []
        self._cari_bakiyeleri: dict[int, Decimal] = {}
        self._tum_cari_etiketleri: list[str] = []

        dis = ttk.Frame(self, padding=10)
        dis.pack(fill="both", expand=True)
        dis.columnconfigure(0, weight=1)
        dis.rowconfigure(0, weight=1)

        canvas = tk.Canvas(dis, highlightthickness=0)
        kaydir = ttk.Scrollbar(dis, orient="vertical", command=canvas.yview)
        form = ttk.Frame(canvas, padding=4)
        form.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        form_pencere = canvas.create_window((0, 0), window=form, anchor="nw")
        canvas.configure(yscrollcommand=kaydir.set)
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(form_pencere, width=e.width),
        )
        canvas.grid(row=0, column=0, sticky="nsew")
        kaydir.grid(row=0, column=1, sticky="ns")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        self.girdiler: dict = {}
        satir = 0

        # —— Tür / yön ——
        ttk.Label(form, text="Evrak türü *").grid(row=satir, column=0, sticky="w", padx=4, pady=4)
        self.tur_var = tk.StringVar(value="Çek")
        tur_cb = ttk.Combobox(
            form, textvariable=self.tur_var, values=("Çek", "Senet"), state="readonly", width=18
        )
        tur_cb.grid(row=satir, column=1, sticky="w", padx=4, pady=4)
        self.girdiler["tur_cb"] = tur_cb

        ttk.Label(form, text="İşlem yönü *").grid(row=satir, column=2, sticky="w", padx=4, pady=4)
        self.yon_var = tk.StringVar(value="Alınan (müşteriden)")
        yon_cb = ttk.Combobox(
            form,
            textvariable=self.yon_var,
            values=("Alınan (müşteriden)", "Verilen (firmamızın)"),
            state="readonly",
            width=22,
        )
        yon_cb.grid(row=satir, column=3, sticky="w", padx=4, pady=4)
        self.girdiler["yon_cb"] = yon_cb
        satir += 1

        # Yön bilindikten sonra cari listesini yükle
        if self.evrak.get("islem_yonu") == ISLEM_YONU_VERILEN:
            self.yon_var.set("Verilen (firmamızın)")
        self._cari_listesini_yon_e_gore_yukle(ilk=True)
        if self.evrak.get("cari_id") and self.evrak["cari_id"] not in self.cari_map.values():
            try:
                cari = CariService.getir(int(self.evrak["cari_id"]))
                if cari is not None:
                    etiket = _cari_etiket(cari)
                    self.cari_map[etiket] = cari.id
                    self._cari_kayitlari.insert(0, cari)
                    self._tum_cari_etiketleri.insert(0, etiket)
            except Exception:
                pass

        ttk.Label(form, text="Portföy no").grid(row=satir, column=0, sticky="w", padx=4, pady=4)
        self.portfoy_var = tk.StringVar()
        self.portfoy_entry = ttk.Entry(form, textvariable=self.portfoy_var, width=28)
        self.portfoy_entry.grid(row=satir, column=1, sticky="w", padx=4, pady=4)
        ttk.Label(
            form, text="Otomatik üretilir; gerekirse düzenleyebilirsiniz.", foreground="#555", font=("Segoe UI", 8)
        ).grid(row=satir, column=2, columnspan=2, sticky="w", padx=4)
        satir += 1

        ttk.Label(form, text="Belge / çek-senet no *").grid(
            row=satir, column=0, sticky="w", padx=4, pady=4
        )
        self.evrak_no = ttk.Entry(form, width=28)
        self.evrak_no.grid(row=satir, column=1, sticky="w", padx=4, pady=4)

        ttk.Label(form, text="Seri no").grid(row=satir, column=2, sticky="w", padx=4, pady=4)
        self.seri_no = ttk.Entry(form, width=22)
        self.seri_no.grid(row=satir, column=3, sticky="w", padx=4, pady=4)
        satir += 1

        # Tarihler (iki sütun düzeni için manuel + tarih_alani sol)
        bugun = date.today().strftime("%d.%m.%Y")
        vade_vars = (date.today() + timedelta(days=30)).strftime("%d.%m.%Y")
        tarih_alani(form, satir, "Düzenleme tarihi *", "duzenleme_tarihi", bugun, self.girdiler)
        ttk.Label(form, text="Vade tarihi *").grid(row=satir, column=2, sticky="w", padx=4, pady=4)
        vade_f = ttk.Frame(form)
        vade_f.grid(row=satir, column=3, sticky="ew", padx=4, pady=4)
        self.vade_entry = ttk.Entry(vade_f, width=18)
        self.vade_entry.pack(side="left", fill="x", expand=True)
        self.vade_entry.insert(0, vade_vars)
        from ui_takvim import takvim_butonu

        takvim_butonu(vade_f, self.vade_entry)
        self.girdiler["vade_tarihi"] = self.vade_entry
        satir += 1

        ttk.Label(form, text="Tutar *").grid(row=satir, column=0, sticky="w", padx=4, pady=4)
        self.tutar = ttk.Entry(form, width=18)
        self.tutar.grid(row=satir, column=1, sticky="w", padx=4, pady=4)

        ttk.Label(form, text="Para birimi").grid(row=satir, column=2, sticky="w", padx=4, pady=4)
        pb_f = ttk.Frame(form)
        pb_f.grid(row=satir, column=3, sticky="w", padx=4, pady=4)
        self.pb_var = tk.StringVar(value="TL")
        self.pb_cb = ttk.Combobox(
            pb_f, textvariable=self.pb_var, values=PARA_BIRIMLERI, width=8, state="readonly"
        )
        self.pb_cb.pack(side="left")
        ttk.Label(pb_f, text=" Kur").pack(side="left", padx=(8, 2))
        self.kur = ttk.Entry(pb_f, width=10)
        self.kur.insert(0, "1")
        self.kur.pack(side="left")
        satir += 1

        # Cari — satış faturası ile aynı ≥3 harf / Ara / F2 seçim ekranı
        ttk.Label(form, text="Cari *").grid(row=satir, column=0, sticky="nw", padx=4, pady=4)
        cari_f = ttk.Frame(form)
        cari_f.grid(row=satir, column=1, columnspan=3, sticky="ew", padx=4, pady=4)
        _cari_arama_alani_kur(
            self,
            cari_f,
            baslik=self._cari_secim_basligi(),
            kayit_adi=self._cari_secim_kayit_adi(),
            salt_oku=self._sadece_oku,
        )
        satir += 1

        # Banka / çek alanları
        banka_kutu = ttk.LabelFrame(form, text="Banka / Çek bilgileri", padding=6)
        banka_kutu.grid(row=satir, column=0, columnspan=4, sticky="ew", pady=(8, 4))
        banka_kutu.columnconfigure(1, weight=1)
        banka_kutu.columnconfigure(3, weight=1)
        self._banka_kutu = banka_kutu
        r = 0
        ttk.Label(banka_kutu, text="Banka adı").grid(row=r, column=0, sticky="w", padx=4, pady=3)
        self.banka_adi = ttk.Entry(banka_kutu, width=28)
        self.banka_adi.grid(row=r, column=1, sticky="ew", padx=4, pady=3)
        ttk.Label(banka_kutu, text="Şube").grid(row=r, column=2, sticky="w", padx=4, pady=3)
        self.banka_subesi = ttk.Entry(banka_kutu, width=22)
        self.banka_subesi.grid(row=r, column=3, sticky="ew", padx=4, pady=3)
        r += 1
        ttk.Label(banka_kutu, text="Hesap no").grid(row=r, column=0, sticky="w", padx=4, pady=3)
        self.hesap_no = ttk.Entry(banka_kutu, width=28)
        self.hesap_no.grid(row=r, column=1, sticky="ew", padx=4, pady=3)
        ttk.Label(banka_kutu, text="IBAN").grid(row=r, column=2, sticky="w", padx=4, pady=3)
        self.iban = ttk.Entry(banka_kutu, width=22)
        self.iban.grid(row=r, column=3, sticky="ew", padx=4, pady=3)
        r += 1
        ttk.Label(banka_kutu, text="Keşideci").grid(row=r, column=0, sticky="w", padx=4, pady=3)
        self.kesideci_adi = ttk.Entry(banka_kutu, width=28)
        self.kesideci_adi.grid(row=r, column=1, sticky="ew", padx=4, pady=3)
        ttk.Label(banka_kutu, text="Keşideci VKN/TCKN").grid(
            row=r, column=2, sticky="w", padx=4, pady=3
        )
        self.kesideci_vergi_tc = ttk.Entry(banka_kutu, width=22)
        self.kesideci_vergi_tc.grid(row=r, column=3, sticky="ew", padx=4, pady=3)
        r += 1
        ttk.Label(banka_kutu, text="Keşide yeri").grid(row=r, column=0, sticky="w", padx=4, pady=3)
        self.keside_yeri = ttk.Entry(banka_kutu, width=28)
        self.keside_yeri.grid(row=r, column=1, sticky="ew", padx=4, pady=3)
        ttk.Label(banka_kutu, text="Lehtar").grid(row=r, column=2, sticky="w", padx=4, pady=3)
        self.lehtar = ttk.Entry(banka_kutu, width=22)
        self.lehtar.grid(row=r, column=3, sticky="ew", padx=4, pady=3)
        satir += 1

        # Senet alanları
        senet_kutu = ttk.LabelFrame(form, text="Senet bilgileri", padding=6)
        senet_kutu.grid(row=satir, column=0, columnspan=4, sticky="ew", pady=(4, 4))
        senet_kutu.columnconfigure(1, weight=1)
        senet_kutu.columnconfigure(3, weight=1)
        self._senet_kutu = senet_kutu
        r = 0
        ttk.Label(senet_kutu, text="Borçlu").grid(row=r, column=0, sticky="w", padx=4, pady=3)
        self.borclu_adi = ttk.Entry(senet_kutu, width=28)
        self.borclu_adi.grid(row=r, column=1, sticky="ew", padx=4, pady=3)
        ttk.Label(senet_kutu, text="Borçlu VKN/TCKN").grid(
            row=r, column=2, sticky="w", padx=4, pady=3
        )
        self.borclu_vergi_tc = ttk.Entry(senet_kutu, width=22)
        self.borclu_vergi_tc.grid(row=r, column=3, sticky="ew", padx=4, pady=3)
        r += 1
        ttk.Label(senet_kutu, text="Kefil").grid(row=r, column=0, sticky="w", padx=4, pady=3)
        self.kefil = ttk.Entry(senet_kutu, width=28)
        self.kefil.grid(row=r, column=1, sticky="ew", padx=4, pady=3)
        ttk.Label(senet_kutu, text="Ödeme yeri").grid(row=r, column=2, sticky="w", padx=4, pady=3)
        self.odeme_yeri = ttk.Entry(senet_kutu, width=22)
        self.odeme_yeri.grid(row=r, column=3, sticky="ew", padx=4, pady=3)
        r += 1
        ttk.Label(senet_kutu, text="Düzenleme yeri").grid(
            row=r, column=0, sticky="w", padx=4, pady=3
        )
        self.duzenleme_yeri = ttk.Entry(senet_kutu, width=28)
        self.duzenleme_yeri.grid(row=r, column=1, sticky="ew", padx=4, pady=3)
        satir += 1

        ttk.Label(form, text="Açıklama").grid(row=satir, column=0, sticky="nw", padx=4, pady=4)
        self.aciklama = ttk.Entry(form, width=60)
        self.aciklama.grid(row=satir, column=1, columnspan=3, sticky="ew", padx=4, pady=4)
        satir += 1

        ttk.Label(form, text="Not").grid(row=satir, column=0, sticky="nw", padx=4, pady=4)
        self.ozel_not = tk.Text(form, height=3, width=50, wrap="word")
        self.ozel_not.grid(row=satir, column=1, columnspan=3, sticky="ew", padx=4, pady=4)
        satir += 1

        if mod != "yeni" and self.evrak.get("durum_etiket"):
            ttk.Label(
                form,
                text=f"Durum: {self.evrak.get('durum_etiket')}  |  Yer: {self.evrak.get('bulundugu_yer') or '—'}",
                font=("Segoe UI", 9, "bold"),
            ).grid(row=satir, column=0, columnspan=4, sticky="w", padx=4, pady=(8, 0))

        alt = ttk.Frame(self, padding=(10, 6))
        alt.pack(fill="x", side="bottom")
        ttk.Button(alt, text="Kapat" if self._sadece_oku else "İptal", command=self.destroy).pack(
            side="right", padx=(8, 0)
        )
        if not self._sadece_oku:
            ttk.Button(alt, text="Kaydet", width=12, command=self.kaydet).pack(side="right")

        self.tur_var.trace_add("write", lambda *_: self._tur_yon_degisti())
        self.yon_var.trace_add("write", lambda *_: self._tur_yon_degisti())
        self.pb_var.trace_add("write", lambda *_: self._pb_degisti())

        self._doldur()
        self._tur_yon_degisti(portfoy_uret=mod == "yeni")
        self._pb_degisti()

        if self._sadece_oku:
            self._salt_oku_yap()

        self.after(80, lambda: self.evrak_no.focus_set())

    def _cari_secim_basligi(self) -> str:
        if (self.yon_var.get() or "").startswith("Verilen"):
            return "Tedarikçi Seçimi"
        return "Müşteri Seçimi"

    def _cari_secim_kayit_adi(self) -> str:
        if (self.yon_var.get() or "").startswith("Verilen"):
            return "tedarikçi"
        return "müşteri"

    def _cari_turu_filtre(self) -> str:
        if (self.yon_var.get() or "").startswith("Verilen"):
            return "Tedarikçi"
        return "Müşteri"

    def _cari_listesini_yon_e_gore_yukle(self, ilk: bool = False, secimi_koru: bool = True):
        onceki_id = _secili_cari_id(self) if secimi_koru and not ilk else None
        if onceki_id is None and ilk and self.evrak.get("cari_id"):
            onceki_id = int(self.evrak["cari_id"])
        kayitlar, cari_map, bakiyeler = _cari_listesini_yukle(self._cari_turu_filtre())
        self._cari_kayitlari = kayitlar
        self.cari_map = cari_map
        self._cari_bakiyeleri = bakiyeler
        self._tum_cari_etiketleri = list(cari_map.keys())
        self._cari_sec_baslik = self._cari_secim_basligi()
        self._cari_sec_kayit_adi = self._cari_secim_kayit_adi()
        _cari_combo_degerlerini_ayarla(self, self._tum_cari_etiketleri)
        if onceki_id and onceki_id in cari_map.values():
            for etiket, cid in cari_map.items():
                if cid == onceki_id:
                    _cari_alana_yaz(self, etiket)
                    break
        elif not ilk and hasattr(self, "cari_var"):
            # Yön değişince eski seçim yeni listede yoksa temizle
            if onceki_id and onceki_id not in cari_map.values():
                _cari_alana_yaz(self, "")

    def _doldur(self):
        e = self.evrak
        if not e:
            return
        basit = e.get("basit_tur") or ""
        self.tur_var.set("Senet" if basit == "SENET" else "Çek")
        if e.get("islem_yonu") == ISLEM_YONU_VERILEN:
            self.yon_var.set("Verilen (firmamızın)")
        else:
            self.yon_var.set("Alınan (müşteriden)")
        self._cari_listesini_yon_e_gore_yukle(ilk=True)
        self.portfoy_var.set(e.get("portfoy_no") or "")
        self.evrak_no.delete(0, "end")
        self.evrak_no.insert(0, e.get("evrak_no") or "")
        self.seri_no.delete(0, "end")
        self.seri_no.insert(0, e.get("seri_no") or "")
        if e.get("duzenleme_tarihi"):
            self.girdiler["duzenleme_tarihi"].delete(0, "end")
            self.girdiler["duzenleme_tarihi"].insert(0, _tarih(e["duzenleme_tarihi"]))
        if e.get("vade_tarihi"):
            self.vade_entry.delete(0, "end")
            self.vade_entry.insert(0, _tarih(e["vade_tarihi"]))
        self.tutar.delete(0, "end")
        tutar = e.get("doviz_tutari")
        if tutar is not None:
            self.tutar.insert(0, f"{float(tutar):.2f}".replace(".", ","))
        self.pb_var.set(e.get("doviz_turu") or "TL")
        self.kur.delete(0, "end")
        self.kur.insert(0, str(e.get("kur") or 1).replace(".", ","))
        if e.get("cari_kodu") and e.get("cari_adi"):
            _cari_alana_yaz(self, f"{e['cari_kodu']} - {e['cari_adi']}")
        elif e.get("cari_id"):
            for etiket, cid in self.cari_map.items():
                if cid == e["cari_id"]:
                    _cari_alana_yaz(self, etiket)
                    break
        for alan, widget in (
            ("banka_adi", self.banka_adi),
            ("banka_subesi", self.banka_subesi),
            ("hesap_no", self.hesap_no),
            ("iban", self.iban),
            ("kesideci_adi", self.kesideci_adi),
            ("kesideci_vergi_tc", self.kesideci_vergi_tc),
            ("keside_yeri", self.keside_yeri),
            ("lehtar", self.lehtar),
            ("borclu_adi", self.borclu_adi),
            ("borclu_vergi_tc", self.borclu_vergi_tc),
            ("kefil", self.kefil),
            ("odeme_yeri", self.odeme_yeri),
            ("duzenleme_yeri", self.duzenleme_yeri),
            ("aciklama", self.aciklama),
        ):
            widget.delete(0, "end")
            widget.insert(0, e.get(alan) or "")
        self.ozel_not.delete("1.0", "end")
        self.ozel_not.insert("1.0", e.get("ozel_not") or "")

    def _tur_yon_degisti(self, portfoy_uret: bool = True):
        cek_mi = self.tur_var.get() == "Çek"
        # Senet kutusunu göster/gizle hissi — grid bırak, state ile ayırt
        if cek_mi:
            self._senet_kutu.configure(text="Senet bilgileri (çek için isteğe bağlı)")
        else:
            self._senet_kutu.configure(text="Senet bilgileri")
        if hasattr(self, "cari_entry"):
            self._cari_listesini_yon_e_gore_yukle(ilk=False)
        if self.mod == "yeni" and portfoy_uret and not self._sadece_oku:
            try:
                yon = (
                    ISLEM_YONU_VERILEN
                    if self.yon_var.get().startswith("Verilen")
                    else ISLEM_YONU_ALINAN
                )
                if yon == ISLEM_YONU_ALINAN:
                    et = EVRAK_TURU_MUSTERI_CEKI if cek_mi else EVRAK_TURU_MUSTERI_SENEDI
                else:
                    et = EVRAK_TURU_FIRMA_CEKI if cek_mi else EVRAK_TURU_FIRMA_SENEDI
                no = CekSenetService.portfoy_no_uret(et, yon)
                self.portfoy_var.set(no)
            except Exception:
                pass

    def _pb_degisti(self):
        if self.pb_var.get() == "TL":
            self.kur.delete(0, "end")
            self.kur.insert(0, "1")
            if not self._sadece_oku:
                self.kur.configure(state="disabled")
        else:
            if not self._sadece_oku:
                self.kur.configure(state="normal")

    def _salt_oku_yap(self):
        for w in (
            self.portfoy_entry,
            self.evrak_no,
            self.seri_no,
            self.tutar,
            self.kur,
            self.banka_adi,
            self.banka_subesi,
            self.hesap_no,
            self.iban,
            self.kesideci_adi,
            self.kesideci_vergi_tc,
            self.keside_yeri,
            self.lehtar,
            self.borclu_adi,
            self.borclu_vergi_tc,
            self.kefil,
            self.odeme_yeri,
            self.duzenleme_yeri,
            self.aciklama,
            self.girdiler.get("duzenleme_tarihi"),
            self.vade_entry,
        ):
            if w is not None:
                try:
                    w.configure(state="disabled")
                except tk.TclError:
                    pass
        for ad in ("cari_combo", "cari_entry"):
            w = getattr(self, ad, None)
            if w is None:
                continue
            try:
                w.configure(state="disabled")
            except tk.TclError:
                pass
        btn = getattr(self, "_cari_ara_btn", None)
        if btn is not None:
            try:
                btn.configure(state="disabled")
            except tk.TclError:
                pass
        self.girdiler["tur_cb"].configure(state="disabled")
        self.girdiler["yon_cb"].configure(state="disabled")
        self.pb_cb.configure(state="disabled")
        self.ozel_not.configure(state="disabled")

    def _verileri_topla(self) -> dict:
        cari_id = _secili_cari_id(self)
        if not cari_id:
            raise ValueError("Listeden geçerli bir cari seçin (Ara / F2 veya ≥3 harf).")
        yon = (
            ISLEM_YONU_VERILEN
            if self.yon_var.get().startswith("Verilen")
            else ISLEM_YONU_ALINAN
        )
        return {
            "basit_tur": "CEK" if self.tur_var.get() == "Çek" else "SENET",
            "islem_yonu": yon,
            "portfoy_no": self.portfoy_var.get().strip(),
            "evrak_no": self.evrak_no.get().strip(),
            "seri_no": self.seri_no.get().strip(),
            "duzenleme_tarihi": self.girdiler["duzenleme_tarihi"].get(),
            "vade_tarihi": self.vade_entry.get(),
            "tutar": self.tutar.get(),
            "doviz_turu": self.pb_var.get(),
            "kur": self.kur.get() if self.pb_var.get() != "TL" else "1",
            "cari_id": cari_id,
            "banka_adi": self.banka_adi.get(),
            "banka_subesi": self.banka_subesi.get(),
            "hesap_no": self.hesap_no.get(),
            "iban": self.iban.get(),
            "kesideci_adi": self.kesideci_adi.get(),
            "kesideci_vergi_tc": self.kesideci_vergi_tc.get(),
            "keside_yeri": self.keside_yeri.get(),
            "lehtar": self.lehtar.get(),
            "borclu_adi": self.borclu_adi.get(),
            "borclu_vergi_tc": self.borclu_vergi_tc.get(),
            "kefil": self.kefil.get(),
            "odeme_yeri": self.odeme_yeri.get(),
            "duzenleme_yeri": self.duzenleme_yeri.get(),
            "aciklama": self.aciklama.get(),
            "ozel_not": self.ozel_not.get("1.0", "end").strip(),
        }

    def kaydet(self):
        try:
            veriler = self._verileri_topla()
            if self.mod == "yeni":
                self.result = CekSenetService.olustur(veriler)
            else:
                self.result = CekSenetService.guncelle(int(self.evrak["id"]), veriler)
        except Exception as e:
            messagebox.showerror("Kayıt", str(e), parent=self)
            return
        if self.on_kaydet:
            try:
                self.on_kaydet()
            except Exception:
                pass
        messagebox.showinfo(
            "Kayıt",
            f"Evrak kaydedildi.\nPortföy no: {self.result.get('portfoy_no')}",
            parent=self,
        )
        self.destroy()


def _evrak_ozet_metin(evrak: dict) -> str:
    return (
        f"{evrak.get('portfoy_no') or ''}  |  {evrak.get('evrak_no') or ''}  |  "
        f"{evrak.get('durum_etiket') or ''}  |  Kalan: {_para(evrak.get('kalan_tutar'))}"
    )


def _finans_hesap_secenekleri() -> tuple[list[str], dict[str, int]]:
    """Kasa + banka mevduat hesapları (etiket → id)."""
    etiketler: list[str] = []
    mapping: dict[str, int] = {}
    try:
        for h in FinansService.kasa_hesaplari(aktif_only=True):
            et = f"[Kasa] {h.hesap_adi}"
            etiketler.append(et)
            mapping[et] = h.id
    except Exception:
        pass
    try:
        for h in FinansService.banka_mevduat_hesaplari():
            et = f"[Banka] {h.hesap_adi}"
            etiketler.append(et)
            mapping[et] = h.id
    except Exception:
        pass
    return etiketler, mapping


def _banka_hesap_secenekleri() -> tuple[list[str], dict[str, int]]:
    etiketler: list[str] = []
    mapping: dict[str, int] = {}
    try:
        for h in FinansService.banka_mevduat_hesaplari():
            et = h.hesap_adi or f"Hesap #{h.id}"
            etiketler.append(et)
            mapping[et] = h.id
    except Exception:
        pass
    return etiketler, mapping


class _IslemDialogBase(tk.Toplevel):
    """Ortak işlem diyaloğu iskeleti (ttk)."""

    baslik = "İşlem"
    onay_metin = "Kaydet"

    def __init__(self, parent, evrak: dict, on_kaydet=None):
        super().__init__(parent)
        self.evrak = evrak
        self.on_kaydet = on_kaydet
        self.result = None
        self.title(f"{self.baslik} — {evrak.get('portfoy_no', '')}")
        self.geometry("480x320")
        self.minsize(420, 260)
        self.transient(parent)
        self.grab_set()

        dis = ttk.Frame(self, padding=12)
        dis.pack(fill="both", expand=True)
        dis.columnconfigure(1, weight=1)

        ttk.Label(dis, text=_evrak_ozet_metin(evrak), wraplength=440).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )
        self.form = dis
        self.girdiler: dict = {}
        try:
            self._form_kur(dis)
        except Exception:
            self.destroy()
            raise
        alt = ttk.Frame(self, padding=(12, 8))
        alt.pack(fill="x", side="bottom")
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(alt, text=self.onay_metin, width=14, command=self._kaydet).pack(side="right")

    def _form_kur(self, form: ttk.Frame):
        raise NotImplementedError

    def _tarih_alani_ekle(self, form, satir: int, etiket: str = "İşlem tarihi"):
        bugun = date.today().strftime("%d.%m.%Y")
        tarih_alani(form, satir, etiket, "islem_tarihi", bugun, self.girdiler)
        return satir + 1

    def _aciklama_alani(self, form, satir: int):
        ttk.Label(form, text="Açıklama").grid(row=satir, column=0, sticky="w", padx=4, pady=4)
        self.aciklama = ttk.Entry(form, width=40)
        self.aciklama.grid(row=satir, column=1, sticky="ew", padx=4, pady=4)
        return satir + 1

    def _kaydet(self):
        try:
            self.result = self._uygula()
        except Exception as e:
            messagebox.showerror(self.baslik, str(e), parent=self)
            return
        if self.on_kaydet:
            try:
                self.on_kaydet()
            except Exception:
                pass
        messagebox.showinfo(
            self.baslik,
            f"İşlem tamamlandı.\nYeni durum: {self.result.get('durum_etiket')}",
            parent=self,
        )
        self.destroy()

    def _uygula(self) -> dict:
        raise NotImplementedError


class BankayaVerDialog(_IslemDialogBase):
    baslik = "Bankaya Ver"
    onay_metin = "Bankaya Ver"

    def _form_kur(self, form):
        if self.evrak.get("islem_yonu") != ISLEM_YONU_ALINAN:
            raise ValueError("Yalnızca alınan evraklar bankaya verilebilir.")
        if self.evrak.get("durum") != DURUM_PORTFOYDE:
            raise ValueError(
                f"Bankaya verilemez.\nDurum: {self.evrak.get('durum_etiket')}\n"
                "Portföydeki evrak seçin."
            )
        satir = 1
        ttk.Label(form, text="İşlem türü *").grid(row=satir, column=0, sticky="w", padx=4, pady=4)
        self.tur_var = tk.StringVar(value="Tahsile")
        ttk.Combobox(
            form,
            textvariable=self.tur_var,
            values=("Tahsile", "Teminata"),
            state="readonly",
            width=24,
        ).grid(row=satir, column=1, sticky="w", padx=4, pady=4)
        satir += 1

        etiketler, self._hesap_map = _banka_hesap_secenekleri()
        ttk.Label(form, text="Banka hesabı *").grid(row=satir, column=0, sticky="w", padx=4, pady=4)
        self.hesap_var = tk.StringVar()
        cb = ttk.Combobox(
            form, textvariable=self.hesap_var, values=etiketler, state="readonly", width=36
        )
        cb.grid(row=satir, column=1, sticky="ew", padx=4, pady=4)
        if etiketler:
            self.hesap_var.set(etiketler[0])
        elif not etiketler:
            ttk.Label(
                form, text="Tanımlı banka hesabı yok — Finans’tan ekleyin.", foreground="#a00"
            ).grid(row=satir + 1, column=1, sticky="w", padx=4)
            satir += 1
        satir += 1
        satir = self._tarih_alani_ekle(form, satir)
        self._aciklama_alani(form, satir)

    def _uygula(self) -> dict:
        hid = self._hesap_map.get(self.hesap_var.get())
        if not hid:
            raise ValueError("Banka hesabı seçin.")
        tur = "TAHSILE" if self.tur_var.get() == "Tahsile" else "TEMINATA"
        return CekSenetService.bankaya_ver(
            int(self.evrak["id"]),
            tur=tur,
            banka_hesabi_id=hid,
            tarih=self.girdiler["islem_tarihi"].get(),
            aciklama=self.aciklama.get(),
        )


class CiroEtDialog(_IslemDialogBase):
    baslik = "Ciro Et"
    onay_metin = "Ciro Et"

    def _form_kur(self, form):
        if self.evrak.get("islem_yonu") != ISLEM_YONU_ALINAN:
            raise ValueError("Yalnızca alınan evraklar ciro edilebilir.")
        if self.evrak.get("durum") != DURUM_PORTFOYDE:
            raise ValueError(
                f"Ciro edilemez.\nDurum: {self.evrak.get('durum_etiket')}\n"
                "Portföydeki evrak seçin."
            )
        self.geometry("520x360")
        satir = 1
        # Ciro hedefi genelde tedarikçi; tüm cariler arasından ≥3 harf ile ara
        kayitlar, cari_map, bakiyeler = _cari_listesini_yukle(None)
        self._cari_kayitlari = kayitlar
        self.cari_map = cari_map
        self._cari_bakiyeleri = bakiyeler
        self._tum_cari_etiketleri = list(cari_map.keys())
        self._tum_cari = self._tum_cari_etiketleri

        ttk.Label(form, text="Hedef cari *").grid(row=satir, column=0, sticky="nw", padx=4, pady=4)
        cari_f = ttk.Frame(form)
        cari_f.grid(row=satir, column=1, sticky="ew", padx=4, pady=4)
        _cari_arama_alani_kur(
            self,
            cari_f,
            baslik="Cari Seçimi",
            kayit_adi="cari",
        )
        # Geriye dönük alias
        self.cari_cb = self.cari_combo
        satir += 1
        satir = self._tarih_alani_ekle(form, satir)
        self._aciklama_alani(form, satir)

    def _uygula(self) -> dict:
        cid = _secili_cari_id(self)
        if not cid:
            raise ValueError("Listeden geçerli bir hedef cari seçin (Ara / F2 veya ≥3 harf).")
        return CekSenetService.ciro_et(
            int(self.evrak["id"]),
            hedef_cari_id=cid,
            tarih=self.girdiler["islem_tarihi"].get(),
            aciklama=self.aciklama.get(),
        )


class TahsilEtDialog(_IslemDialogBase):
    baslik = "Tahsil Et"
    onay_metin = "Tahsil Et"

    def _form_kur(self, form):
        izinli = {DURUM_PORTFOYDE, DURUM_BANKAYA_TAHSILE, DURUM_KISMI_TAHSIL}
        if self.evrak.get("islem_yonu") != ISLEM_YONU_ALINAN:
            raise ValueError("Tahsil yalnızca alınan evraklar içindir. Verilen için «Öde» kullanın.")
        if self.evrak.get("durum") not in izinli:
            raise ValueError(
                f"Tahsil edilemez.\nDurum: {self.evrak.get('durum_etiket')}\n"
                "Portföy, bankaya tahsile veya kısmi tahsil durumundaki evrak seçin."
            )
        self.geometry("500x360")
        satir = 1
        kalan = float(self.evrak.get("kalan_tutar") or 0)
        ttk.Label(form, text="Tahsil tutarı *").grid(row=satir, column=0, sticky="w", padx=4, pady=4)
        self.tutar = ttk.Entry(form, width=18)
        self.tutar.insert(0, f"{kalan:.2f}".replace(".", ","))
        self.tutar.grid(row=satir, column=1, sticky="w", padx=4, pady=4)
        satir += 1
        ttk.Label(
            form,
            text=f"Kalan: {_para(kalan)} — kısmi tahsil desteklenir.",
            foreground="#555",
            font=("Segoe UI", 8),
        ).grid(row=satir, column=1, sticky="w", padx=4)
        satir += 1

        etiketler, self._hesap_map = _finans_hesap_secenekleri()
        ttk.Label(form, text="Kasa / banka *").grid(row=satir, column=0, sticky="w", padx=4, pady=4)
        self.hesap_var = tk.StringVar()
        ttk.Combobox(
            form, textvariable=self.hesap_var, values=etiketler, state="readonly", width=36
        ).grid(row=satir, column=1, sticky="ew", padx=4, pady=4)
        if etiketler:
            self.hesap_var.set(etiketler[0])
        satir += 1
        satir = self._tarih_alani_ekle(form, satir)
        self._aciklama_alani(form, satir)

    def _uygula(self) -> dict:
        hid = self._hesap_map.get(self.hesap_var.get())
        if not hid:
            raise ValueError("Kasa veya banka hesabı seçin.")
        return CekSenetService.tahsil_et(
            int(self.evrak["id"]),
            tutar=self.tutar.get(),
            finans_hesap_id=hid,
            tarih=self.girdiler["islem_tarihi"].get(),
            aciklama=self.aciklama.get(),
        )


class OdeDialog(_IslemDialogBase):
    baslik = "Öde"
    onay_metin = "Öde"

    def _form_kur(self, form):
        izinli = {DURUM_TEDARIKCIYE_VERILDI, DURUM_KISMI_ODENDI, DURUM_PORTFOYDE}
        if self.evrak.get("islem_yonu") != ISLEM_YONU_VERILEN:
            raise ValueError("Ödeme yalnızca verilen (firma) evraklar içindir.")
        if self.evrak.get("durum") not in izinli:
            raise ValueError(
                f"Ödenemez.\nDurum: {self.evrak.get('durum_etiket')}\n"
                "Verilen / kısmi ödenen evrak seçin."
            )
        self.geometry("500x360")
        satir = 1
        kalan = float(self.evrak.get("kalan_tutar") or 0)
        ttk.Label(form, text="Ödeme tutarı *").grid(row=satir, column=0, sticky="w", padx=4, pady=4)
        self.tutar = ttk.Entry(form, width=18)
        self.tutar.insert(0, f"{kalan:.2f}".replace(".", ","))
        self.tutar.grid(row=satir, column=1, sticky="w", padx=4, pady=4)
        satir += 1
        ttk.Label(
            form,
            text=f"Kalan: {_para(kalan)} — kısmi ödeme desteklenir.",
            foreground="#555",
            font=("Segoe UI", 8),
        ).grid(row=satir, column=1, sticky="w", padx=4)
        satir += 1

        etiketler, self._hesap_map = _finans_hesap_secenekleri()
        ttk.Label(form, text="Kasa / banka *").grid(row=satir, column=0, sticky="w", padx=4, pady=4)
        self.hesap_var = tk.StringVar()
        ttk.Combobox(
            form, textvariable=self.hesap_var, values=etiketler, state="readonly", width=36
        ).grid(row=satir, column=1, sticky="ew", padx=4, pady=4)
        if etiketler:
            self.hesap_var.set(etiketler[0])
        satir += 1
        satir = self._tarih_alani_ekle(form, satir)
        self._aciklama_alani(form, satir)

    def _uygula(self) -> dict:
        hid = self._hesap_map.get(self.hesap_var.get())
        if not hid:
            raise ValueError("Kasa veya banka hesabı seçin.")
        return CekSenetService.ode(
            int(self.evrak["id"]),
            tutar=self.tutar.get(),
            finans_hesap_id=hid,
            tarih=self.girdiler["islem_tarihi"].get(),
            aciklama=self.aciklama.get(),
        )


class IadeEtDialog(_IslemDialogBase):
    baslik = "İade Et"
    onay_metin = "İade Et"

    def _form_kur(self, form):
        izinli = {
            DURUM_PORTFOYDE,
            DURUM_BANKAYA_TAHSILE,
            DURUM_BANKAYA_TEMINATA,
            DURUM_CIRO_EDILDI,
            DURUM_TEDARIKCIYE_VERILDI,
            DURUM_KISMI_TAHSIL,
            DURUM_KISMI_ODENDI,
        }
        if self.evrak.get("durum") not in izinli:
            raise ValueError(
                f"İade edilemez.\nDurum: {self.evrak.get('durum_etiket')}"
            )
        if self.evrak.get("durum") == DURUM_IADE:
            raise ValueError("Evrak zaten iade edilmiş.")
        satir = 1
        satir = self._tarih_alani_ekle(form, satir)
        self._aciklama_alani(form, satir)

    def _uygula(self) -> dict:
        return CekSenetService.iade_et(
            int(self.evrak["id"]),
            tarih=self.girdiler["islem_tarihi"].get(),
            aciklama=self.aciklama.get(),
        )


class KarsiliksizDialog(_IslemDialogBase):
    baslik = "Karşılıksız / Protestolu"
    onay_metin = "Kaydet"

    def _form_kur(self, form):
        izinli = {
            DURUM_PORTFOYDE,
            DURUM_BANKAYA_TAHSILE,
            DURUM_BANKAYA_TEMINATA,
            DURUM_CIRO_EDILDI,
        }
        if self.evrak.get("islem_yonu") != ISLEM_YONU_ALINAN:
            raise ValueError("Yalnızca alınan evraklar karşılıksız/protestolu işaretlenebilir.")
        if self.evrak.get("durum") not in izinli:
            raise ValueError(
                f"Bu işlem yapılamaz.\nDurum: {self.evrak.get('durum_etiket')}"
            )
        if self.evrak.get("durum") in (DURUM_KARSILIKSIZ, DURUM_PROTESTO):
            raise ValueError("Evrak zaten karşılıksız/protestolu.")
        satir = 1
        ttk.Label(form, text="Sonuç *").grid(row=satir, column=0, sticky="w", padx=4, pady=4)
        self.tur_var = tk.StringVar(value="Karşılıksız")
        ttk.Combobox(
            form,
            textvariable=self.tur_var,
            values=("Karşılıksız", "Protestolu"),
            state="readonly",
            width=24,
        ).grid(row=satir, column=1, sticky="w", padx=4, pady=4)
        satir += 1
        satir = self._tarih_alani_ekle(form, satir)
        self._aciklama_alani(form, satir)

    def _uygula(self) -> dict:
        tur = "KARSILIKSIZ" if self.tur_var.get() == "Karşılıksız" else "PROTESTO"
        return CekSenetService.karsiliksiz_protesto(
            int(self.evrak["id"]),
            tur=tur,
            tarih=self.girdiler["islem_tarihi"].get(),
            aciklama=self.aciklama.get(),
        )


class EvrakHareketlerDialog(tk.Toplevel):
    """Seçili evrakın durum geçmişi."""

    def __init__(self, parent, evrak: dict):
        super().__init__(parent)
        self.title(f"Hareketler — {evrak.get('portfoy_no', '')}")
        self.geometry("720x360")
        self.transient(parent)
        self.grab_set()

        ttk.Label(
            self,
            text=f"{evrak.get('portfoy_no')}  |  {evrak.get('evrak_no')}  |  {evrak.get('durum_etiket')}",
            font=("Segoe UI", 10, "bold"),
            padding=10,
        ).pack(anchor="w")

        cerceve = ttk.Frame(self, padding=(10, 0, 10, 10))
        cerceve.pack(fill="both", expand=True)
        kolonlar = (
            ("tarih", "Tarih", 120),
            ("islem", "İşlem", 100),
            ("onceki", "Önceki", 120),
            ("yeni", "Yeni", 120),
            ("tutar", "Tutar", 90),
            ("aciklama", "Açıklama", 180),
            ("kullanici", "Kullanıcı", 90),
        )
        keys = tuple(k for k, _b, _w in kolonlar)
        tablo = ttk.Treeview(cerceve, columns=keys, show="headings", selectmode="browse")
        for k, b, w in kolonlar:
            tablo.heading(k, text=b)
            tablo.column(k, width=w, anchor="w")
        y = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
        tablo.configure(yscrollcommand=y.set)
        tablo.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")

        try:
            kayitlar = CekSenetService.evrak_hareketleri(int(evrak["id"]))
        except Exception:
            kayitlar = []
        for h in kayitlar:
            tablo.insert(
                "",
                "end",
                values=(
                    _tarih_saat(h["tarih"]),
                    h["islem_turu"],
                    h["onceki_durum"],
                    h["yeni_durum"],
                    _para(h["tutar"]) if h["tutar"] is not None else "",
                    h["aciklama"],
                    h["kullanici"],
                ),
            )

        ttk.Button(self, text="Kapat", command=self.destroy).pack(pady=8)


# Geriye dönük uyumluluk
YeniEvrakStubDialog = EvrakDialog
