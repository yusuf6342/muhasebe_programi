"""Satış faturası — Barkod Okut paneli ve satır birleştirme mantığı."""

from __future__ import annotations

import time
import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, ttk
from typing import Any

from branding import COLOR_BG, COLOR_GOLD, COLOR_NAVY
from database.barkod_okut_service import (
    barkod_ile_ara,
    barkod_temizle,
    depo_mevcut_miktar,
)
from database.stok_service import StokService, decimal

# Aynı barkodun okuyucu çift gönderimi (~ms); bilinçli art arda okutmaya engel olmaz
_DEBOUNCE_MS = 90


def barkod_ses_acik_mi() -> bool:
    try:
        from database.database import get_system_session
        from database.system.models import AppSetting
        from sqlalchemy import select

        with get_system_session() as session:
            kayit = session.scalar(
                select(AppSetting).where(AppSetting.anahtar == "barkod_okut_ses")
            )
            if kayit is None or kayit.deger is None:
                return True
            return str(kayit.deger).strip() not in ("0", "false", "False", "kapali", "hayir")
    except Exception:
        return True


def barkod_ses_ayarla(acik: bool) -> None:
    try:
        from database.database import get_system_session
        from database.system.models import AppSetting
        from sqlalchemy import select

        with get_system_session() as session:
            kayit = session.scalar(
                select(AppSetting).where(AppSetting.anahtar == "barkod_okut_ses")
            )
            deger = "1" if acik else "0"
            if kayit is None:
                session.add(AppSetting(anahtar="barkod_okut_ses", deger=deger))
            else:
                kayit.deger = deger
            session.commit()
    except Exception:
        pass


def _ses_basari() -> None:
    if not barkod_ses_acik_mi():
        return
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_OK)
    except Exception:
        try:
            import winsound

            winsound.Beep(1200, 60)
        except Exception:
            pass


def _ses_hata() -> None:
    if not barkod_ses_acik_mi():
        return
    try:
        import winsound

        winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
    except Exception:
        try:
            import winsound

            winsound.Beep(600, 160)
        except Exception:
            pass


def _d(deger, varsayilan: Decimal = Decimal("0")) -> Decimal:
    try:
        return decimal(deger if deger is not None else varsayilan, "değer", varsayilan)
    except Exception:
        return varsayilan


def _fiyat_norm(deger) -> str:
    """Karşılaştırma için fiyat metni."""
    try:
        return str(_d(deger).quantize(Decimal("0.0001")))
    except Exception:
        return str(deger or "0")


def _satir_birlestirilebilir(mevcut: dict, yeni: dict, *, depo: str) -> bool:
    """Aynı stok/birim/fiyat/iskonto/KDV/depo/PB — özel satırlar birleşmez.

    Manuel fiyatlı satırda fiyat karşılaştırması atlanır (miktar artar, fiyat korunur).
    """
    if (mevcut.get("urun_kodu") or "").strip() != (yeni.get("urun_kodu") or "").strip():
        return False
    if (mevcut.get("birim") or "").strip() != (yeni.get("birim") or "").strip():
        return False
    manuel = bool(mevcut.get("manuel_fiyat"))
    if not manuel:
        if _fiyat_norm(mevcut.get("birim_satis_fiyati")) != _fiyat_norm(
            yeni.get("birim_satis_fiyati")
        ):
            return False
    for alan in ("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3", "kdv_orani"):
        if _fiyat_norm(mevcut.get(alan) or 0) != _fiyat_norm(yeni.get(alan) or 0):
            return False
    if (mevcut.get("aciklama") or "").strip() != (yeni.get("aciklama") or "").strip():
        return False
    m_depo = (mevcut.get("depo") or depo or "").strip()
    n_depo = (yeni.get("depo") or depo or "").strip()
    if m_depo != n_depo:
        return False
    m_pb = (mevcut.get("satir_para_birimi") or mevcut.get("para_birimi") or "TRY").strip().upper()
    n_pb = (yeni.get("satir_para_birimi") or yeni.get("para_birimi") or "TRY").strip().upper()
    if m_pb != n_pb:
        return False
    return True


def fatura_barkod_paneli_kur(dialog) -> None:
    """Satış faturası satır alanının üstüne Barkod Okut kutusu yerleştirir."""
    if getattr(dialog, "_barkod_panel_hazir", False):
        return
    if "urun_kodu" not in getattr(dialog, "satir_girdileri", {}):
        return
    giris = dialog.satir_girdileri["urun_kodu"].master
    parent = giris.master

    try:
        giris_info = giris.grid_info() or {}
        giris_row = int(giris_info.get("row", 0))
    except (tk.TclError, TypeError, ValueError):
        giris_row = 0

    # Barkod satırı giris'in hemen üstüne; alttaki satırları +1 kaydır
    for w in list(parent.grid_slaves()):
        try:
            r = int(w.grid_info().get("row", 0))
        except (tk.TclError, TypeError, ValueError):
            continue
        if r >= giris_row:
            try:
                w.grid_configure(row=r + 1)
            except tk.TclError:
                pass

    dis = tk.Frame(parent, bg=COLOR_NAVY, highlightthickness=0)
    dis.grid(
        row=giris_row,
        column=0,
        columnspan=int(giris_info.get("columnspan") or 2),
        sticky="ew",
        pady=(0, 6),
    )
    try:
        # Ağırlık: treeview artık bir satır aşağıda
        parent.rowconfigure(giris_row + 2, weight=1)
    except tk.TclError:
        pass

    tk.Frame(dis, bg=COLOR_GOLD, height=3).pack(fill="x")
    ust = tk.Frame(dis, bg=COLOR_NAVY)
    ust.pack(fill="x")
    tk.Label(
        ust,
        text="  Barkod Okut",
        bg=COLOR_NAVY,
        fg=COLOR_GOLD,
        font=("Segoe UI", 9, "bold"),
        anchor="w",
    ).pack(side="left", pady=2)
    dialog._barkod_durum = tk.Label(
        ust,
        text="",
        bg=COLOR_NAVY,
        fg="#A5D6A7",
        font=("Segoe UI", 8),
        anchor="e",
    )
    dialog._barkod_durum.pack(side="right", padx=8)

    ic = tk.Frame(dis, bg=COLOR_BG, padx=8, pady=6)
    ic.pack(fill="x")
    ttk.Label(ic, text="Barkod:").pack(side="left")
    entry = ttk.Entry(ic, width=36, font=("Segoe UI", 11))
    entry.pack(side="left", padx=(6, 8), fill="x", expand=True)
    dialog.barkod_okut_entry = entry
    dialog._barkod_son_okuma = ("", 0.0)
    dialog._barkod_isleniyor = False

    ses_var = tk.BooleanVar(value=barkod_ses_acik_mi())

    def _ses_degisti():
        barkod_ses_ayarla(bool(ses_var.get()))

    ttk.Checkbutton(
        ic, text="Ses", variable=ses_var, command=_ses_degisti
    ).pack(side="left", padx=(4, 0))
    ttk.Label(ic, text="(F8 odak)", foreground="#666").pack(side="left", padx=(8, 0))

    entry.bind("<Return>", lambda e: dialog._barkod_okut_isle())
    entry.bind("<KP_Enter>", lambda e: dialog._barkod_okut_isle())

    dialog.bind("<F8>", lambda _e: dialog._barkod_odak())
    dialog._barkod_panel_hazir = True

    if getattr(dialog, "_fatura_kilitli", False):
        try:
            entry.configure(state="disabled")
        except tk.TclError:
            pass
    else:
        dialog.after(350, dialog._barkod_odak)


def _musteri_fiyat(dialog, stok_kodu: str, barkod_fiyat: Decimal) -> Decimal:
    """Müşteri fiyat listesi / barkod fiyatı — mevcut kurallar."""
    if barkod_fiyat and barkod_fiyat > 0:
        return barkod_fiyat
    liste = None
    try:
        musteri = dialog._secili_musteri() if hasattr(dialog, "_secili_musteri") else None
        if musteri is not None:
            from hizli_satis_musteri import fiyat_listesi_coz

            liste = fiyat_listesi_coz(
                satis_fiyat_listesi=getattr(musteri, "satis_fiyat_listesi", None),
                musteri_grubu=getattr(musteri, "musteri_grubu", None),
            )
    except Exception:
        liste = None
    try:
        return StokService.satis_fiyati_adi_ile(
            stok_kodu, liste, varsayilan=barkod_fiyat or 0
        )
    except Exception:
        return StokService.satis_fiyati_1(stok_kodu, varsayilan=barkod_fiyat or 0)


def fatura_barkod_isle(dialog, ham_barkod: str | None = None) -> str:
    """Enter ile barkod işle. Dönüş: 'break' (klavye olayı için)."""
    if getattr(dialog, "_fatura_kilitli", False):
        messagebox.showwarning(
            "Barkod",
            "Onaylı / iptal faturada barkod okutulamaz. Önce Onay Kaldır yapın.",
            parent=dialog,
        )
        return "break"
    if getattr(dialog, "_barkod_isleniyor", False):
        return "break"

    entry = getattr(dialog, "barkod_okut_entry", None)
    if ham_barkod is None:
        ham_barkod = entry.get() if entry is not None else ""
    kod = barkod_temizle(ham_barkod)
    if entry is not None:
        try:
            entry.delete(0, "end")
        except tk.TclError:
            pass
    if not kod:
        _barkod_odak(dialog)
        return "break"

    # Okuyucu çift tetikleme koruması (bilinçli tekrar okutmaya izin — kısa pencere)
    son_kod, son_ms = getattr(dialog, "_barkod_son_okuma", ("", 0.0))
    simdi = time.time() * 1000.0
    if kod == son_kod and (simdi - son_ms) < _DEBOUNCE_MS:
        _barkod_odak(dialog)
        return "break"
    dialog._barkod_son_okuma = (kod, simdi)

    dialog._barkod_isleniyor = True
    try:
        sonuc = barkod_ile_ara(kod)
        durum = sonuc.get("durum")
        if durum == "gecersiz":
            _ses_hata()
            _durum_yaz(dialog, sonuc["mesaj"], hata=True)
            messagebox.showwarning("Barkod", sonuc["mesaj"], parent=dialog)
            return "break"
        if durum == "bulunamadi":
            _ses_hata()
            _durum_yaz(dialog, sonuc["mesaj"], hata=True)
            _bulunamadi_dialog(dialog, kod)
            return "break"
        if durum == "pasif":
            _ses_hata()
            _durum_yaz(dialog, sonuc["mesaj"], hata=True)
            messagebox.showwarning("Pasif stok", sonuc["mesaj"], parent=dialog)
            return "break"
        if durum == "satis_kapali":
            _ses_hata()
            _durum_yaz(dialog, sonuc["mesaj"], hata=True)
            messagebox.showwarning("Satışa kapalı", sonuc["mesaj"], parent=dialog)
            return "break"
        if durum == "coklu":
            kayit = _coklu_sec(dialog, sonuc.get("liste") or [])
            if not kayit:
                _barkod_odak(dialog)
                return "break"
        else:
            kayit = sonuc.get("kayit")
        if not kayit:
            _ses_hata()
            _barkod_odak(dialog)
            return "break"

        _satira_uygula(dialog, kayit, okutulan_barkod=kod)
        _ses_basari()
    except ValueError as hata:
        _ses_hata()
        _durum_yaz(dialog, str(hata), hata=True)
        messagebox.showwarning("Barkod", str(hata), parent=dialog)
    except Exception as hata:
        _ses_hata()
        messagebox.showerror("Barkod", str(hata), parent=dialog)
    finally:
        dialog._barkod_isleniyor = False
        _barkod_odak(dialog)
    return "break"


def _barkod_odak(dialog) -> None:
    entry = getattr(dialog, "barkod_okut_entry", None)
    if entry is None:
        return
    try:
        if str(entry.cget("state")) == "disabled":
            return
        entry.focus_set()
        entry.selection_range(0, "end")
    except tk.TclError:
        pass


def _durum_yaz(dialog, metin: str, *, hata: bool = False) -> None:
    lbl = getattr(dialog, "_barkod_durum", None)
    if lbl is None:
        return
    try:
        lbl.configure(text=metin or "", fg="#EF9A9A" if hata else "#A5D6A7")
    except tk.TclError:
        pass


def _bulunamadi_dialog(dialog, barkod: str) -> None:
    from database.access import yetki_var

    mesaj = f"«{barkod}» barkoduna bağlı ürün bulunamadı."
    if yetki_var("stok_duzenleme", "yeni_kayit"):
        if messagebox.askyesno(
            "Barkod bulunamadı",
            mesaj + "\n\nStok listesini açmak ister misiniz?",
            parent=dialog,
        ):
            try:
                dialog.stok_listesi_ac()
            except Exception:
                pass
    else:
        messagebox.showwarning("Barkod bulunamadı", mesaj, parent=dialog)


def _coklu_sec(dialog, liste: list[dict]) -> dict | None:
    if not liste:
        return None
    win = tk.Toplevel(dialog)
    win.title("Ürün seçin")
    win.transient(dialog)
    win.grab_set()
    ttk.Label(win, text="Bu barkoda birden fazla ürün bağlı. Birini seçin:").pack(
        padx=12, pady=8, anchor="w"
    )
    lb = tk.Listbox(win, width=60, height=min(8, len(liste)))
    lb.pack(padx=12, pady=4, fill="both", expand=True)
    for i, k in enumerate(liste):
        lb.insert(
            "end",
            f"{k.get('stok_kodu')} — {k.get('stok_adi')}  [{k.get('birim')}]  "
            f"{k.get('birim_fiyat')}",
        )
    lb.selection_set(0)
    secim: dict[str, Any] = {"kayit": None}

    def _tamam():
        idx = lb.curselection()
        if idx:
            secim["kayit"] = liste[int(idx[0])]
        win.destroy()

    def _iptal():
        win.destroy()

    alt = ttk.Frame(win)
    alt.pack(fill="x", pady=8, padx=12)
    ttk.Button(alt, text="Seç", command=_tamam).pack(side="right")
    ttk.Button(alt, text="İptal", command=_iptal).pack(side="right", padx=6)
    lb.bind("<Double-1>", lambda _e: _tamam())
    lb.bind("<Return>", lambda _e: _tamam())
    dialog.wait_window(win)
    return secim["kayit"]


def _satira_uygula(dialog, kayit: dict, *, okutulan_barkod: str) -> None:
    """Yeni satır ekle veya uygun satırda miktar +1."""
    depo = ""
    try:
        depo = (dialog.depo.get() or "").strip()
    except Exception:
        depo = ""

    barkod_fiyat = _d(kayit.get("birim_fiyat"), Decimal("0"))
    fiyat = _musteri_fiyat(dialog, kayit["stok_kodu"], barkod_fiyat)
    carpan = _d(kayit.get("carpan"), Decimal("1"))
    # Okutulan barkod birime bağlıysa satıra o birimle eklenir; miktar +1
    miktar_ekle = Decimal("1")
    birim = (
        (kayit.get("barkod_birim") or kayit.get("birim") or "Adet").strip() or "Adet"
    )
    if carpan > 1 and (kayit.get("barkod_birim") or "").strip():
        # Paket fiyatı temel birim fiyatına çevrilmiş olabilir; paket birim fiyatı tercih
        paket = _d(kayit.get("paket_fiyat"), Decimal("0"))
        if paket > 0:
            fiyat = _musteri_fiyat(dialog, kayit["stok_kodu"], paket)

    kdv = kayit.get("kdv_orani")
    if kdv is None:
        kdv = Decimal("20")
    else:
        kdv = _d(kdv, Decimal("20"))

    iskonto1 = Decimal("0")
    # Stok kartı varsayılan iskontoları (varsa)
    try:
        stoklar = StokService.stoklari_ara(kayit["stok_kodu"])
        stok = next(
            (s for s in stoklar if s.stok_kodu == kayit["stok_kodu"]), None
        )
        if stok is not None:
            iskonto1 = _d(getattr(stok, "iskonto_1", 0), Decimal("0"))
    except Exception:
        pass

    pb = "TRY"
    try:
        if hasattr(dialog, "_doviz_para_birimi"):
            pb = (dialog._doviz_para_birimi.get() or "TRY").upper()
    except Exception:
        pb = "TRY"

    sablon = {
        "urun_kodu": kayit["stok_kodu"],
        "urun_adi": kayit["stok_adi"],
        "aciklama": "",
        "miktar": str(miktar_ekle),
        "birim": birim,
        "birim_satis_fiyati": str(fiyat),
        "iskonto_orani": str(iskonto1),
        "iskonto_orani_2": "0",
        "iskonto_orani_3": "0",
        "kdv_orani": str(kdv),
        "barkod": okutulan_barkod or kayit.get("barkod") or "",
        "lot_no": "",
        "lot_cikisi": "",
        "depo": depo,
        "satir_para_birimi": pb,
        "manuel_fiyat": False,
        "irsaliyelenen_miktar": 0,
        "faturalanan_miktar": 0,
        "fifo_birim_maliyeti": "0",
        "son_alis_birim_maliyeti": "0",
        "ortalama_birim_maliyeti": "0",
        "agirlikli_ortalama_birim_maliyeti": "0",
    }

    from fatura_satir_birim_service import temel_miktar

    birim_satir = sablon.get("birim") or kayit.get("birim") or "Adet"
    ek_temel = temel_miktar(miktar_ekle, birim_satir, sablon["urun_kodu"])

    # Eşleşen satır ara (barkod öncelikli, sonra koşullu birleşim)
    hedef_idx = None
    for i, mevcut in enumerate(dialog.satirlar):
        ayni_barkod = (
            (mevcut.get("barkod") or "").strip() == (sablon["barkod"] or "").strip()
            and bool(sablon["barkod"])
        )
        ayni_kod = (mevcut.get("urun_kodu") or "").strip() == sablon["urun_kodu"]
        if (ayni_barkod or ayni_kod) and _satir_birlestirilebilir(
            mevcut, sablon, depo=depo
        ):
            hedef_idx = i
            break

    if hedef_idx is not None:
        mevcut = dialog.satirlar[hedef_idx]
        yeni_miktar = _d(mevcut.get("miktar")) + miktar_ekle
        talep = _urun_talep_toplami(
            dialog, sablon["urun_kodu"], haric_idx=hedef_idx
        ) + temel_miktar(yeni_miktar, mevcut.get("birim") or birim_satir, sablon["urun_kodu"])
        _eksi_stok_kontrol(
            dialog, kayit, depo, urun_kodu=sablon["urun_kodu"], proje_miktar_toplam=talep
        )
        mevcut["miktar"] = str(yeni_miktar)
        mevcut["temel_miktar"] = str(
            temel_miktar(yeni_miktar, mevcut.get("birim") or birim_satir, sablon["urun_kodu"])
        )
        if not (mevcut.get("barkod") or "").strip() and sablon["barkod"]:
            mevcut["barkod"] = sablon["barkod"]
        idx = hedef_idx
        artis = True
    else:
        talep = _urun_talep_toplami(dialog, sablon["urun_kodu"]) + ek_temel
        _eksi_stok_kontrol(
            dialog, kayit, depo, urun_kodu=sablon["urun_kodu"], proje_miktar_toplam=talep
        )
        sablon["temel_miktar"] = str(ek_temel)
        try:
            maliyetler = StokService.maliyetler(sablon["urun_kodu"], depo) if depo else {}
            for alan, anahtar in (
                ("fifo_birim_maliyeti", "fifo"),
                ("son_alis_birim_maliyeti", "son_alis"),
                ("ortalama_birim_maliyeti", "ortalama"),
                ("agirlikli_ortalama_birim_maliyeti", "agirlikli"),
            ):
                sablon[alan] = str(maliyetler.get(anahtar, 0))
        except Exception:
            pass
        if hasattr(dialog, "_doviz_para_birimi"):
            try:
                from doviz_fatura_panel import doviz_satir_kaydet_oncesi

                sablon = doviz_satir_kaydet_oncesi(dialog, sablon)
            except Exception:
                pass
        dialog.satirlar.append(sablon)
        idx = len(dialog.satirlar) - 1
        artis = False

    dialog._fatura_satirlari_hazir = True
    dialog._duzenlenen_satir = None
    # Tek satır güncellemesi: tabloyu yenile (merkezi hesap)
    dialog._satir_listesini_yenile()
    dialog._toplamlari_guncelle()
    _satiri_vurgula(dialog, idx)
    ad = kayit.get("stok_adi") or kayit.get("stok_kodu")
    if artis:
        _durum_yaz(dialog, f"{ad} → miktar {dialog.satirlar[idx].get('miktar')}")
    else:
        _durum_yaz(dialog, f"Eklendi: {ad}")
    # Arama alanlarını temizle; odak miktar hücresine (sürekli barkod için Enter zinciri sonunda barkoda döner)
    if hasattr(dialog, "_urun_secim_alanlarini_temizle_ve_odakla"):
        try:
            for ad_alan in ("barkod", "urun_kodu", "urun_adi"):
                w = (getattr(dialog, "satir_girdileri", None) or {}).get(ad_alan)
                if w is not None:
                    try:
                        w.delete(0, "end")
                    except tk.TclError:
                        pass
        except Exception:
            pass
    elif hasattr(dialog, "barkod_okut_entry"):
        try:
            dialog.barkod_okut_entry.delete(0, "end")
        except Exception:
            pass
    try:
        from fatura_satir_hucre_edit import satir_ilk_alana_odakla

        satir_ilk_alana_odakla(dialog, idx)
    except Exception:
        pass


def _eksi_stok_kontrol(
    dialog, kayit: dict, depo: str, *, urun_kodu: str, proje_miktar_toplam: Decimal
) -> None:
    """Eksi stok yasak — talep temel birimde mevcut stokla karşılaştırılır."""
    if not urun_kodu or not depo:
        return
    mevcut = depo_mevcut_miktar(urun_kodu, depo)
    if mevcut < proje_miktar_toplam:
        raise ValueError(
            f"Stok yetersiz — eksi stoka izin yok.\n"
            f"{kayit.get('stok_adi')}: mevcut {mevcut} (temel birim), "
            f"istenilen {proje_miktar_toplam} ({depo})"
        )


def _urun_talep_toplami(dialog, urun_kodu: str, *, haric_idx: int | None = None) -> Decimal:
    """Aynı ürünün faturadaki toplam talebi — temel birimde."""
    from fatura_satir_birim_service import satir_temel_talep

    toplam = Decimal("0")
    for i, s in enumerate(dialog.satirlar):
        if haric_idx is not None and i == haric_idx:
            continue
        if (s.get("urun_kodu") or "").strip() == urun_kodu:
            toplam += satir_temel_talep(s)
    return toplam


def _satiri_vurgula(dialog, idx: int) -> None:
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is None:
        return
    iid = str(idx)
    try:
        tablo.tag_configure("barkod_vurgu", background="#C8E6C9", foreground="#1B5E20")
        # Mevcut etiketleri koruyarak vurgu ekle
        tags = list(tablo.item(iid, "tags") or ())
        if "barkod_vurgu" not in tags:
            tags.append("barkod_vurgu")
        tablo.item(iid, tags=tags)
        tablo.selection_set(iid)
        tablo.focus(iid)
        tablo.see(iid)
    except tk.TclError:
        return

    def _kaldir():
        try:
            tags = [t for t in (tablo.item(iid, "tags") or ()) if t != "barkod_vurgu"]
            tablo.item(iid, tags=tags)
        except tk.TclError:
            pass

    try:
        dialog.after(700, _kaldir)
    except tk.TclError:
        pass
