"""Fatura satırı — Ürün Adı yanında «+ / Yeni Ürün Ekle» ve satıra dönüş."""

from __future__ import annotations

import logging
import tkinter as tk
from decimal import Decimal
from tkinter import messagebox
from typing import Any

_LOG = logging.getLogger(__name__)


def _secili_satir_idx(dialog) -> int | None:
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is None:
        return None
    try:
        sec = tablo.selection()
        if not sec:
            return None
        iid = sec[0]
        if iid == "__yeni__":
            return None
        idx = int(iid)
    except (tk.TclError, TypeError, ValueError):
        return None
    if 0 <= idx < len(getattr(dialog, "satirlar", []) or []):
        return idx
    return None


def satirdan_yeni_urun_ac(dialog, idx: int | None = None) -> Any:
    """Satır bağlamında hızlı stok kartı açar; kayıt aynı satırı tamamlar."""
    from fatura_barkod_ui import _barkod_hedef_kaydet, _satir_uid_ver, satir_cozulmemis_mi
    from hizli_stok_karti_ui import hizli_stok_karti_ac

    if getattr(dialog, "_fatura_kilitli", False):
        messagebox.showwarning(
            "Stok",
            "Onaylı faturada stok kartı eklemek için önce Onay Kaldır yapın.",
            parent=dialog,
        )
        return None
    if idx is None:
        idx = _secili_satir_idx(dialog)
    if idx is None or not (0 <= idx < len(dialog.satirlar)):
        # Satır yok — klasik hızlı stok (şerit F6)
        return hizli_stok_karti_ac(dialog)

    satir = dialog.satirlar[idx]
    uid = _satir_uid_ver(satir)
    belge_nesil = int(getattr(dialog, "_barkod_nesil", 0) or 0)
    ham = (satir.get("ham_barkod") or satir.get("barkod") or "").strip()
    cozulmemis = satir_cozulmemis_mi(satir)
    # Tanımlı ürünün barkodunu yeni karta kopyalama
    barkod_aktar = ham if cozulmemis and ham else None
    ad_aktar = None  # İmleç ürün adında başlasın; boş ad taşıma

    def _satira_uygula(stok) -> None:
        _stok_kartini_satira_yaz(
            dialog,
            hedef_uid=uid,
            stok=stok,
            belge_nesil=belge_nesil,
            ham_barkod=ham,
        )

    stok = hizli_stok_karti_ac(
        dialog,
        barkod=barkod_aktar,
        urun_adi=ad_aktar,
        satir_guncelle=_satira_uygula,
        barkod_kod_kopyala=False,
        odak_urun_adi=True,
    )
    return stok


def _stok_kartini_satira_yaz(
    dialog,
    *,
    hedef_uid: str,
    stok,
    belge_nesil: int,
    ham_barkod: str = "",
) -> bool:
    """Başarılı kart kaydını çağıran satıra uygular; satır yoksa yeni satır üretmez."""
    from fatura_barkod_ui import _barkod_hedef_kaydet, satir_cozulmemis_mi
    from fatura_urun_aktar_service import stoktan_satir_sablonu
    from fatura_satir_hucre_edit import uzlasma_etkisini_kaldir

    if int(getattr(dialog, "_barkod_nesil", 0) or 0) != int(belge_nesil):
        messagebox.showinfo(
            "Stok kartı kaydedildi",
            f"«{getattr(stok, 'stok_adi', '')}» oluşturuldu; fatura değiştiği için satıra yazılmadı.",
            parent=dialog,
        )
        return False

    idx = None
    for i, s in enumerate(dialog.satirlar or []):
        if (s.get("satir_uid") or "") == hedef_uid:
            idx = i
            break
    if idx is None:
        messagebox.showinfo(
            "Stok kartı kaydedildi",
            f"«{getattr(stok, 'stok_adi', '')}» ({getattr(stok, 'stok_kodu', '')}) oluşturuldu.\n"
            "Çağıran fatura satırı silinmiş veya bulunamadı; otomatik satır eklenmedi.",
            parent=dialog,
        )
        return False

    eski = dialog.satirlar[idx]
    eski_miktar = Decimal(str(eski.get("miktar") or 1))
    ham = (ham_barkod or eski.get("ham_barkod") or eski.get("barkod") or "").strip()
    # Tanımsız satırdaki geçici 0 fiyat / manuel işareti bilinçli ücretsiz sayılmaz
    sablon = stoktan_satir_sablonu(
        dialog,
        urun_kodu=stok.stok_kodu,
        urun_adi=stok.stok_adi,
        birim=getattr(stok, "birim", None) or "Adet",
        miktar=eski_miktar,
        product_id=getattr(stok, "id", None),
        barkod=ham,
    )
    sablon["miktar"] = str(eski_miktar)  # biriken okuma miktarı korunur
    sablon["satir_uid"] = hedef_uid
    sablon["ham_barkod"] = ham
    if ham:
        sablon["barkod"] = ham
    sablon["cozulmemis"] = False
    sablon.pop("cozulmemis_neden", None)
    sablon["aciklama"] = eski.get("aciklama") or ""
    # Kullanıcı bilinçli iskonto/fiyat girdiyse (çözülmüş satır) koru
    if not satir_cozulmemis_mi(eski) and bool(eski.get("manuel_fiyat")):
        sablon["birim_satis_fiyati"] = eski.get("birim_satis_fiyati")
        sablon["manuel_fiyat"] = True
        for alan in ("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3"):
            if eski.get(alan) not in (None, ""):
                sablon[alan] = eski[alan]

    uzlasma_etkisini_kaldir(dialog, yalniz_referansli=True)
    dialog.satirlar[idx] = sablon
    if ham:
        _barkod_hedef_kaydet(dialog, ham, sablon)
    dialog._fatura_satirlari_hazir = True
    dialog._duzenlenen_satir = None
    dialog._satir_listesini_yenile()
    dialog._toplamlari_guncelle()
    try:
        from fatura_barkod_ui import _barkod_odak, _satiri_vurgula

        _satiri_vurgula(dialog, idx)
        _barkod_odak(dialog)
    except Exception:
        pass
    return True


def yeni_urun_arti_butonlarini_ciz(dialog) -> None:
    """Ürün Adı hücresinin sağında küçük «+» düğmeleri (Yeni Ürün Ekle)."""
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is None:
        return
    # Eski + düğmelerini temizle
    for w in getattr(dialog, "_yeni_urun_btnler", []) or []:
        try:
            w.destroy()
        except tk.TclError:
            pass
    dialog._yeni_urun_btnler = []
    if getattr(dialog, "_fatura_kilitli", False):
        return
    if getattr(dialog, "_satir_hucre_editor", None) is not None:
        return
    try:
        cols = list(tablo["columns"] or ())
    except tk.TclError:
        return
    if "urun_adi" not in cols:
        return
    btn_w = 22
    for iid in tablo.get_children():
        if iid == "__yeni__":
            continue
        try:
            idx = int(iid)
            bbox = tablo.bbox(iid, "urun_adi")
        except (tk.TclError, TypeError, ValueError):
            continue
        if not bbox or idx < 0 or idx >= len(dialog.satirlar or []):
            continue
        x, y, w, h = bbox
        if w < btn_w + 8 or h < 8:
            continue
        btn = tk.Button(
            tablo,
            text="+",
            font=("Segoe UI", 9, "bold"),
            fg="#0B2A4A",
            bg="#E8EEF5",
            activebackground="#D0DCEC",
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground="#94A3B8",
            cursor="hand2",
            takefocus=0,
            command=lambda i=idx: satirdan_yeni_urun_ac(dialog, i),
        )
        try:
            btn.place(
                x=x + w - btn_w - 1,
                y=y + 1,
                width=btn_w,
                height=max(14, h - 2),
            )
        except tk.TclError:
            try:
                btn.destroy()
            except tk.TclError:
                pass
            continue
        # Tooltip benzeri
        def _enter(_e=None, b=btn):
            try:
                b.configure(bg="#C5D4E8")
            except tk.TclError:
                pass

        def _leave(_e=None, b=btn):
            try:
                b.configure(bg="#E8EEF5")
            except tk.TclError:
                pass

        btn.bind("<Enter>", _enter)
        btn.bind("<Leave>", _leave)
        # Basit durum çubuğu / title
        try:
            # Tk Button'da tooltip yok; bind ile
            def _ipucu(_e=None, i=idx):
                try:
                    dialog._barkod_durum  # noqa: B018
                except Exception:
                    pass

            btn.bind("<Enter>", lambda e, i=idx: None)
        except Exception:
            pass
        dialog._yeni_urun_btnler.append(btn)


def urun_adi_overlay_genislik_kis(w: int, *, btn_w: int = 22) -> int:
    """Vurgulu ürün adı etiketini + düğmesine yer açacak şekilde kısalt."""
    return max(2, w - btn_w - 4)
