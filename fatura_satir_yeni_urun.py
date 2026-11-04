"""Fatura satırı — Ürün Adı yanında «+» (ürün seç) ve satıra dönüş."""

from __future__ import annotations

import logging
import tkinter as tk
from decimal import Decimal
from tkinter import messagebox
from typing import Any

_LOG = logging.getLogger(__name__)


def belge_satir_kilitli(dialog) -> bool:
    """Satış/alış fatura veya sipariş satır düzenleme kilidi."""
    import types

    if bool(getattr(dialog, "_fatura_kilitli", False)):
        return True
    cls = type(dialog)
    if getattr(cls, "__module__", "") == "unittest.mock":
        return False
    for ad in ("_alis_kilitli", "_alis_siparis_kilitli", "_belge_kilitli_mi", "_onayli"):
        fn = getattr(cls, ad, None)
        if isinstance(fn, types.FunctionType):
            try:
                if bool(fn(dialog)):
                    return True
            except Exception:
                continue
    giris = getattr(dialog, "_satir_ici_giris", None)
    if giris is None or getattr(type(giris), "__module__", "") == "unittest.mock":
        return False
    kilit_fn = getattr(giris, "kilitli", None)
    if callable(kilit_fn):
        try:
            return bool(kilit_fn())
        except Exception:
            return False
    return False


def urun_adi_kolonu(dialog) -> str | None:
    """Ürün adı sütunu: satışta urun_adi, alışta ad."""
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is None:
        return None
    try:
        cols = list(tablo["columns"] or ())
    except tk.TclError:
        return None
    giris = getattr(dialog, "_satir_ici_giris", None)
    aday = None
    if giris is not None:
        aday = (getattr(giris, "kolonlar", {}) or {}).get("ad")
    for ad in (aday, "urun_adi", "ad"):
        if ad and ad in cols:
            return ad
    return None


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


def satirdan_urun_sec_ac(dialog, idx: int | None = None) -> None:
    """Satırdaki «+» / F10 — ürün listesi; seçim yalnız hedef satırı değiştirir.

    idx=None → boş giriş satırına ekleme (çoklu seçim).
    """
    if belge_satir_kilitli(dialog):
        messagebox.showwarning(
            "Ürün",
            "Onaylı / kilitli belgede ürün değiştirmek için önce kilidi kaldırın.",
            parent=dialog,
        )
        return
    giris = getattr(dialog, "_satir_ici_giris", None)
    if giris is None:
        messagebox.showinfo("Ürün", "Ürün seçim bileşeni hazır değil.", parent=dialog)
        return
    if idx is not None:
        if not (0 <= idx < len(getattr(dialog, "satirlar", []) or [])):
            return
        giris.urun_listesi_ile_degistir(idx)
        return
    giris.stok_listesi_ac()


def satirdan_yeni_urun_ac(dialog, idx: int | None = None) -> Any:
    """Satır bağlamında hızlı stok kartı açar; kayıt aynı satırı tamamlar.

    Asıl «+ Yeni Ürün Ekle» ürün listesinin altındadır; bu yol F6 / sağ tık için kalır.
    """
    from fatura_barkod_ui import _satir_uid_ver, satir_cozulmemis_mi
    from hizli_stok_karti_ui import hizli_stok_karti_ac

    if belge_satir_kilitli(dialog):
        messagebox.showwarning(
            "Stok",
            "Onaylı / kilitli belgede stok kartı eklemek için önce kilidi kaldırın.",
            parent=dialog,
        )
        return None
    if idx is None:
        idx = _secili_satir_idx(dialog)
    if idx is None or not (0 <= idx < len(dialog.satirlar)):
        return hizli_stok_karti_ac(dialog)

    satir = dialog.satirlar[idx]
    uid = _satir_uid_ver(satir)
    belge_nesil = int(getattr(dialog, "_barkod_nesil", 0) or 0)
    ham = (satir.get("ham_barkod") or satir.get("barkod") or "").strip()
    cozulmemis = satir_cozulmemis_mi(satir)
    barkod_aktar = ham if cozulmemis and ham else None

    def _satira_uygula(stok) -> None:
        _stok_kartini_satira_yaz(
            dialog,
            hedef_uid=uid,
            stok=stok,
            belge_nesil=belge_nesil,
            ham_barkod=ham,
        )

    return hizli_stok_karti_ac(
        dialog,
        barkod=barkod_aktar,
        urun_adi=None,
        satir_guncelle=_satira_uygula,
        barkod_kod_kopyala=False,
        odak_urun_adi=True,
    )


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

    if belge_satir_kilitli(dialog):
        messagebox.showinfo(
            "Stok kartı kaydedildi",
            f"«{getattr(stok, 'stok_adi', '')}» oluşturuldu; belge kilitli olduğu için satıra yazılmadı.",
            parent=dialog,
        )
        return False
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
    sablon = stoktan_satir_sablonu(
        dialog,
        urun_kodu=stok.stok_kodu,
        urun_adi=stok.stok_adi,
        birim=getattr(stok, "birim", None) or "Adet",
        miktar=eski_miktar,
        product_id=getattr(stok, "id", None),
        barkod=ham,
    )
    sablon["miktar"] = str(eski_miktar)
    sablon["satir_uid"] = hedef_uid
    sablon["ham_barkod"] = ham
    if ham:
        sablon["barkod"] = ham
    sablon["cozulmemis"] = False
    sablon.pop("cozulmemis_neden", None)
    sablon["aciklama"] = eski.get("aciklama") or ""
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
    """Ürün Adı hücresinin sağında «+» — ürün listesi (ipucu: Ürün seç / değiştir)."""
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is None:
        return
    for w in getattr(dialog, "_yeni_urun_btnler", []) or []:
        try:
            w.destroy()
        except tk.TclError:
            pass
    dialog._yeni_urun_btnler = []
    if belge_satir_kilitli(dialog):
        return
    if getattr(dialog, "_satir_hucre_editor", None) is not None:
        return
    ad_kolon = urun_adi_kolonu(dialog)
    if not ad_kolon:
        return
    btn_w = 22

    def _btn_olustur(*, x: int, y: int, w: int, h: int, idx: int | None) -> None:
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
            command=lambda i=idx: satirdan_urun_sec_ac(dialog, i),
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
            return

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

        def _ipucu_goster(_e=None):
            lbl = getattr(dialog, "_barkod_durum", None)
            if lbl is not None:
                try:
                    lbl.configure(text="Ürün seç / değiştir")
                except tk.TclError:
                    pass

        def _ipucu_sil(_e=None):
            pass

        btn.bind("<Enter>", lambda e: (_enter(e), _ipucu_goster(e)), add="+")
        btn.bind("<Leave>", lambda e: (_leave(e), _ipucu_sil(e)), add="+")
        dialog._yeni_urun_btnler.append(btn)

    for iid in tablo.get_children():
        try:
            bbox = tablo.bbox(iid, ad_kolon)
        except (tk.TclError, TypeError, ValueError):
            continue
        if not bbox:
            continue
        x, y, w, h = bbox
        if w < btn_w + 8 or h < 8:
            continue
        if iid == "__yeni__":
            _btn_olustur(x=x, y=y, w=w, h=h, idx=None)
            continue
        try:
            idx = int(iid)
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(dialog.satirlar or []):
            continue
        _btn_olustur(x=x, y=y, w=w, h=h, idx=idx)


def arti_butonlarini_yenile(dialog) -> None:
    """Tablo yenilemesinden sonra «+» düğmelerini yeniden çiz (alış/satış)."""
    try:
        dialog.after_idle(lambda: yeni_urun_arti_butonlarini_ciz(dialog))
    except Exception:
        try:
            yeni_urun_arti_butonlarini_ciz(dialog)
        except Exception:
            pass


def urun_adi_overlay_genislik_kis(w: int, *, btn_w: int = 22) -> int:
    """Vurgulu ürün adı etiketini + düğmesine yer açacak şekilde kısalt."""
    return max(2, w - btn_w - 4)
