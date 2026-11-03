"""Satış faturası — barkod okutma (şerit alanı + kesintisiz satır aktarımı)."""

from __future__ import annotations

import logging
import time
import tkinter as tk
from collections import deque
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

_LOG = logging.getLogger(__name__)

# Aynı fiziksel okumanın CR+LF / çift KeyPress ile iki kez işlenmesini engeller.
# Barkod değerine göre değil olay zamanına göre; bilinçli tekrar okutmaya engel olmaz.
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


def belge_kancasi(dialog, ad: str):
    """Belge türünün sınıfta tanımladığı satır kancası (ör. iade kaynak bağı); yoksa None."""
    if not callable(getattr(type(dialog), ad, None)):
        return None
    return getattr(dialog, ad)


def _satir_uid_ver(satir: dict) -> str:
    """Kararlı satır kimliği — ekran sıra numarasına dayanmaz."""
    uid = (satir.get("satir_uid") or "").strip()
    if uid:
        return uid
    import uuid

    uid = uuid.uuid4().hex
    satir["satir_uid"] = uid
    return uid


def _barkod_hedef_harita(dialog) -> dict:
    h = getattr(dialog, "_barkod_hedef_map", None)
    if h is None:
        h = {}
        dialog._barkod_hedef_map = h
    return h


def _barkod_hedef_kaydet(dialog, barkod: str, satir: dict) -> None:
    kod = barkod_temizle(barkod)
    if not kod:
        return
    _barkod_hedef_harita(dialog)[kod] = _satir_uid_ver(satir)


def _barkod_satir_indeksi(dialog, barkod: str) -> int | None:
    """Bu faturada barkodun tarama hedefi: önce harita, sonra belge sırası."""
    kod = barkod_temizle(barkod)
    if not kod:
        return None
    satirlar = getattr(dialog, "satirlar", None) or []
    harita = _barkod_hedef_harita(dialog)
    uid = harita.get(kod)
    if uid:
        for i, s in enumerate(satirlar):
            if (s.get("satir_uid") or "") != uid:
                continue
            sb = barkod_temizle(s.get("barkod") or s.get("ham_barkod") or "")
            if sb == kod:
                return i
            # Barkod değişmiş — hedef geçersiz
            break
        harita.pop(kod, None)
    for i, s in enumerate(satirlar):
        if s.get("siparis_satiri_id") or s.get("irsaliye_satiri_id"):
            continue
        sb = barkod_temizle(s.get("barkod") or s.get("ham_barkod") or "")
        if sb == kod:
            harita[kod] = _satir_uid_ver(s)
            return i
    return None


def _miktar_artir(dialog, idx: int, *, miktar_ekle: Decimal = Decimal("1")) -> int | None:
    """Mevcut satırda miktar +1; fiyat/iskonto dokunulmaz."""
    from fatura_satir_birim_service import temel_miktar
    from fatura_satir_hucre_edit import uzlasma_etkisini_kaldir

    if not (0 <= idx < len(dialog.satirlar)):
        return None
    mevcut = dialog.satirlar[idx]
    yeni_miktar = _d(mevcut.get("miktar")) + miktar_ekle
    artis_onayla = belge_kancasi(dialog, "_satir_miktar_artisi_onayla")
    if artis_onayla is not None and not artis_onayla(mevcut, yeni_miktar):
        _durum_yaz(dialog, f"Miktar artırılmadı: {mevcut.get('urun_adi') or mevcut.get('barkod') or ''}", hata=True)
        return None
    uzlasma_etkisini_kaldir(dialog, yalniz_referansli=True)
    mevcut["miktar"] = str(yeni_miktar)
    mevcut["temel_miktar"] = str(
        temel_miktar(
            yeni_miktar,
            mevcut.get("birim") or "Adet",
            (mevcut.get("urun_kodu") or "").strip(),
        )
    )
    dialog._fatura_satirlari_hazir = True
    dialog._duzenlenen_satir = None
    dialog._satir_listesini_yenile()
    dialog._toplamlari_guncelle()
    etiket = "cozulmemis_vurgu" if satir_cozulmemis_mi(mevcut) else "barkod_vurgu"
    _satiri_vurgula(dialog, idx, etiket=etiket)
    ad = (mevcut.get("urun_adi") or "").strip() or (mevcut.get("barkod") or "")
    _durum_yaz(dialog, f"{ad} → miktar {mevcut.get('miktar')}")
    dialog._son_barkod_idx = idx
    return idx


def _satir_birlestirilebilir(mevcut: dict, yeni: dict, *, depo: str) -> bool:
    """Aynı stok/birim/fiyat/iskonto/KDV/depo/PB — özel satırlar birleşmez."""
    if mevcut.get("siparis_satiri_id") or mevcut.get("irsaliye_satiri_id"):
        return False
    # Çözülmemiş satırlar yalnız aynı barkodla (_barkod_satir_indeksi) birleşir
    if satir_cozulmemis_mi(mevcut) or satir_cozulmemis_mi(yeni):
        return False
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


def satir_cozulmemis_mi(satir: dict | None) -> bool:
    """Stok bağlantısı kurulmamış barkod satırı mı?"""
    if not isinstance(satir, dict):
        return False
    if bool(satir.get("cozulmemis")):
        return True
    ad = (satir.get("urun_adi") or "").strip()
    barkod = (satir.get("barkod") or satir.get("ham_barkod") or "").strip()
    # Boş ad + barkod: çözülmemiş; stok kimliği yoksa da aynı
    if barkod and not ad and not satir.get("product_id") and not satir.get("stok_id"):
        return True
    return False


def cozulmemis_satir_indeksleri(dialog) -> list[int]:
    satirlar = getattr(dialog, "satirlar", None) or []
    return [i for i, s in enumerate(satirlar) if satir_cozulmemis_mi(s)]


def cozulmemis_satirlari_denetle(dialog) -> str | None:
    """Kaydet/onay öncesi: çözülmemiş satır varsa toplu açıklama; yoksa None."""
    indeksler = cozulmemis_satir_indeksleri(dialog)
    if not indeksler:
        return None
    satirlar = dialog.satirlar
    satirlar_metin = []
    for i in indeksler[:12]:
        s = satirlar[i]
        kod = (s.get("barkod") or s.get("ham_barkod") or s.get("urun_kodu") or "").strip()
        neden = (s.get("cozulmemis_neden") or "").strip()
        ekstra = f" — {neden}" if neden else ""
        satirlar_metin.append(f"  {i + 1}. satır: {kod}{ekstra}")
    fazla = len(indeksler) - 12
    if fazla > 0:
        satirlar_metin.append(f"  … ve {fazla} satır daha")
    return (
        "Stok bağlantısı kurulmamış barkod satırları var.\n"
        "Ürün adını F10 / ürün seçimi ile doldurun veya satırı silin.\n\n"
        + "\n".join(satirlar_metin)
    )


def cozulmemis_engelle_ve_yonlendir(dialog) -> bool:
    """True = işlem engellendi. Kullanıcıyı ilk hatalı satıra yönlendirir."""
    mesaj = cozulmemis_satirlari_denetle(dialog)
    if not mesaj:
        return False
    indeksler = cozulmemis_satir_indeksleri(dialog)
    messagebox.showerror("Çözülmemiş barkod satırları", mesaj, parent=dialog)
    if indeksler:
        _satiri_vurgula(dialog, indeksler[0], etiket="cozulmemis_vurgu")
    return True


def fatura_barkod_serit_alani_kur(dialog, parent, *, column: int, gap: int = 10) -> ttk.Entry:
    """İrsaliyeden Getir ile Satır İşlemleri arasına Barkod giriş alanı yerleştirir."""
    cer = ttk.Frame(parent, style="FaturaGiris.TFrame")
    cer.grid(row=0, column=column, sticky="w", padx=(0, gap), pady=0)
    ttk.Label(cer, text="Barkod:", style="FaturaGiris.TLabel").pack(
        side="left", padx=(0, 4)
    )
    entry = ttk.Entry(cer, width=22, style="FaturaGiris.TEntry", font=("Segoe UI", 10))
    try:
        _ipady = 2
        from fatura_tema import form_ipady

        _ipady = form_ipady()
    except Exception:
        _ipady = 2
    entry.pack(side="left", ipady=_ipady)
    dialog.serit_barkod_entry = entry
    dialog.barkod_okut_entry = entry
    dialog._barkod_son_okuma = ("", 0.0)
    dialog._barkod_isleniyor = False
    dialog._barkod_kuyruk = getattr(dialog, "_barkod_kuyruk", None) or deque()
    dialog._barkod_sira = int(getattr(dialog, "_barkod_sira", 0) or 0)
    dialog._barkod_nesil = int(getattr(dialog, "_barkod_nesil", 0) or 0)
    dialog._barkod_odak_serit = True

    def _isle(_event=None):
        return fatura_barkod_isle(dialog)

    def _tab_sonlandir(event):
        # Okuyucu Tab gönderirse: dolu alanda barkod işle; boşsa normal Tab gezinmesi
        metin = ""
        try:
            metin = entry.get()
        except tk.TclError:
            pass
        if barkod_temizle(metin):
            fatura_barkod_isle(dialog)
            return "break"
        return None

    entry.bind("<Return>", _isle)
    entry.bind("<KP_Enter>", _isle)
    entry.bind("<Tab>", _tab_sonlandir)
    try:
        dialog.bind("<F8>", lambda _e: dialog._barkod_odak())
    except tk.TclError:
        pass
    return entry


def fatura_barkod_paneli_kur(dialog) -> None:
    """Eski lacivert Barkod Okut paneli — geriye uyum; şerit alanı tercih edilir."""
    if getattr(dialog, "_barkod_panel_hazir", False):
        return
    if getattr(dialog, "serit_barkod_entry", None) is not None:
        dialog._barkod_panel_hazir = True
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
    dialog._barkod_kuyruk = deque()
    dialog._barkod_sira = 0
    dialog._barkod_nesil = 0

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
        if hasattr(dialog, "_fatura_ilk_musteri_odak"):
            dialog.after(100, dialog._fatura_ilk_musteri_odak)


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


def _kuyruk_al(dialog) -> deque:
    k = getattr(dialog, "_barkod_kuyruk", None)
    if k is None:
        k = deque()
        dialog._barkod_kuyruk = k
    return k


def fatura_barkod_isle(dialog, ham_barkod: str | None = None) -> str:
    """Enter/Tab ile tamamlanan barkodu kuyruğa alır; alanı hemen temizler."""
    if getattr(dialog, "_fatura_kilitli", False):
        messagebox.showwarning(
            "Barkod",
            "Onaylı / iptal faturada barkod okutulamaz. Önce Onay Kaldır yapın.",
            parent=dialog,
        )
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
        return "break"

    # Çift olay (CR+LF) — aynı tarama olayı; bilinçli tekrar ayrı zamana düşer
    son_kod, son_ms = getattr(dialog, "_barkod_son_okuma", ("", 0.0))
    simdi = time.time() * 1000.0
    if kod == son_kod and (simdi - son_ms) < _DEBOUNCE_MS:
        return "break"
    dialog._barkod_son_okuma = (kod, simdi)

    dialog._barkod_sira = int(getattr(dialog, "_barkod_sira", 0) or 0) + 1
    sira_id = dialog._barkod_sira
    nesil = int(getattr(dialog, "_barkod_nesil", 0) or 0)
    baslangic = time.perf_counter()
    _kuyruk_al(dialog).append(
        {
            "sira_id": sira_id,
            "barkod": kod,
            "nesil": nesil,
            "t0": baslangic,
            "odak_serit": bool(getattr(dialog, "_barkod_odak_serit", True)),
        }
    )
    _kuyruk_pump(dialog)
    return "break"


def _kuyruk_pump(dialog) -> None:
    if getattr(dialog, "_barkod_isleniyor", False):
        return
    kuyruk = _kuyruk_al(dialog)
    if not kuyruk:
        return
    dialog._barkod_isleniyor = True
    try:
        while kuyruk:
            olay = kuyruk.popleft()
            _barkod_olayi_isle(dialog, olay)
    finally:
        dialog._barkod_isleniyor = False
        # Pump sırasında yeni olay geldiyse devam
        if _kuyruk_al(dialog):
            try:
                dialog.after_idle(lambda: _kuyruk_pump(dialog))
            except tk.TclError:
                _kuyruk_pump(dialog)


def _barkod_olayi_isle(dialog, olay: dict) -> None:
    kod = olay.get("barkod") or ""
    sira_id = olay.get("sira_id")
    nesil = int(getattr(dialog, "_barkod_nesil", 0) or 0)
    if int(olay.get("nesil") or 0) != nesil:
        # Pencere/fatura değişti — kaybolmasın: durum bilgisi
        _durum_yaz(
            dialog,
            f"Bekleyen tarama uygulanamadı (belge değişti): {kod}",
            hata=True,
        )
        _panel_bildirim(
            dialog,
            barcode=kod,
            teknik=f"Barkod kuyruğu nesil uyuşmazlığı (sira={sira_id}).",
        )
        return

    t0 = float(olay.get("t0") or time.perf_counter())
    try:
        sonuc = barkod_ile_ara(kod)
        durum = sonuc.get("durum")
        if durum == "ok":
            kayit = sonuc.get("kayit")
            if not kayit:
                _cozulmemis_satir_ekle(
                    dialog, kod, neden="Eşleşme boş döndü", sira_id=sira_id
                )
            else:
                dialog._son_barkod_idx = _satira_uygula(
                    dialog, kayit, okutulan_barkod=kod, birlestir=True
                )
                _ses_basari()
        elif durum == "coklu":
            # Seçim diyaloğu YOK — elle çözülecek satır
            _cozulmemis_satir_ekle(
                dialog,
                kod,
                neden="Birden fazla ürüne bağlı barkod",
                sira_id=sira_id,
            )
            _ses_hata()
        elif durum in ("bulunamadi", "gecersiz"):
            _cozulmemis_satir_ekle(
                dialog,
                kod,
                neden=sonuc.get("mesaj") or "Eşleşme yok",
                sira_id=sira_id,
            )
            _ses_hata()
        elif durum in ("pasif", "satis_kapali", "birim_hatasi"):
            # Taramayı durdurma; ürün adı boş satır + engellemeyen durum
            _cozulmemis_satir_ekle(
                dialog,
                kod,
                neden=sonuc.get("mesaj") or durum,
                sira_id=sira_id,
            )
            _ses_hata()
            _panel_bildirim(
                dialog,
                barcode=kod,
                teknik=sonuc.get("mesaj") or durum,
            )
        else:
            _cozulmemis_satir_ekle(
                dialog, kod, neden=f"Bilinmeyen durum: {durum}", sira_id=sira_id
            )
            _ses_hata()
    except ValueError as hata:
        _ses_hata()
        _cozulmemis_satir_ekle(dialog, kod, neden=str(hata), sira_id=sira_id)
        _panel_bildirim(dialog, barcode=kod, teknik=str(hata))
    except Exception as hata:
        _LOG.exception("Barkod işleme hatası | sira=%s barkod=%s", sira_id, kod)
        _ses_hata()
        _cozulmemis_satir_ekle(
            dialog, kod, neden=f"Teknik hata: {hata}", sira_id=sira_id
        )
        _panel_bildirim(dialog, barcode=kod, teknik=f"Barkod işlenemedi: {hata}")
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        gecikmeler = getattr(dialog, "_barkod_gecikme_ms", None)
        if gecikmeler is None:
            gecikmeler = []
            dialog._barkod_gecikme_ms = gecikmeler
        gecikmeler.append(ms)
        if len(gecikmeler) > 500:
            del gecikmeler[:-200]
        _odak_sonrasi(dialog, olay)


def _odak_sonrasi(dialog, olay: dict) -> None:
    """Tarama odağını koru; kullanıcı başka alandaysa imleci çekme."""
    if not olay.get("odak_serit", True):
        return
    entry = getattr(dialog, "serit_barkod_entry", None) or getattr(
        dialog, "barkod_okut_entry", None
    )
    if entry is None:
        return
    try:
        fokus = dialog.focus_get()
    except tk.TclError:
        fokus = None
    # Kullanıcı satır/müşteri düzenliyorsa dokunma
    if fokus is not None and fokus is not entry:
        try:
            # Şerit etiketi / frame içi çocuklar da barkod alanı sayılır
            if str(fokus) == str(entry):
                pass
            else:
                # Satır tablosu veya başka Entry'deyse zorlama
                wclass = fokus.winfo_class()
                if wclass in ("TEntry", "Entry", "TCombobox", "Text", "Treeview"):
                    return
        except tk.TclError:
            return
    _barkod_odak(dialog)


def _barkod_odak(dialog) -> None:
    entry = getattr(dialog, "serit_barkod_entry", None) or getattr(
        dialog, "barkod_okut_entry", None
    )
    if entry is not None:
        try:
            if str(entry.cget("state")) == "disabled":
                return
            entry.focus_set()
            entry.selection_range(0, "end")
            dialog._barkod_odak_serit = True
            return
        except tk.TclError:
            pass
    from satir_ici_urun_giris import giris_bileseni

    giris = giris_bileseni(dialog)
    if giris is not None and not giris.kilitli():
        giris.ac("barkod")


def _durum_yaz(dialog, metin: str, *, hata: bool = False) -> None:
    lbl = getattr(dialog, "_barkod_durum", None)
    if lbl is None:
        return
    try:
        lbl.configure(text=metin or "", fg="#EF9A9A" if hata else "#A5D6A7")
    except tk.TclError:
        pass


def _bulunamadi_panel(dialog, barkod: str) -> None:
    """Modal yok — kalıcı Mesajlar paneline yaz; odak barkotta kalsın."""
    from fatura_mesaj_paneli import (
        _fatura_kimlik,
        _session_key_al,
        panel_mesaj_ekle,
    )
    from database.invoice_scan_message_service import barkod_bulunamadi_kaydet

    fid, fno = _fatura_kimlik(dialog)
    session_key = _session_key_al(dialog)
    kayit = barkod_bulunamadi_kaydet(
        barcode=barkod,
        session_key=session_key,
        invoice_id=fid,
        invoice_no=fno or None,
    )
    if kayit:
        panel_mesaj_ekle(dialog, kayit)
    else:
        panel_mesaj_ekle(
            dialog,
            None,
            teknik_uyari=f"{barkod} nolu barkod bulunamadı. (kayıt yazılamadı)",
        )


def _panel_bildirim(dialog, *, barcode: str = "", teknik: str = "") -> None:
    from fatura_mesaj_paneli import (
        _fatura_kimlik,
        _session_key_al,
        panel_mesaj_ekle,
    )
    from database.invoice_scan_message_service import teknik_hata_kaydet

    fid, fno = _fatura_kimlik(dialog)
    kayit = teknik_hata_kaydet(
        message_text=teknik,
        barcode=barcode,
        session_key=_session_key_al(dialog),
        invoice_id=fid,
        invoice_no=fno or None,
    )
    panel_mesaj_ekle(dialog, kayit, teknik_uyari=None if kayit else teknik)


def _bulunamadi_dialog(dialog, barkod: str) -> None:
    """Geriye uyum — artık çözülmemiş satır + panel."""
    _cozulmemis_satir_ekle(dialog, barkod, neden="Eşleşme yok")


def _coklu_sec(dialog, liste: list[dict]) -> dict | None:
    """Geriye uyum — seçim diyaloğu açılmaz (kesintisiz tarama)."""
    return None


def _cozulmemis_sablon(barkod: str, *, neden: str = "") -> dict:
    """Ürün adı boş, miktar 1, stok uydurulmamış satır."""
    import uuid

    kod = barkod_temizle(barkod)
    return {
        "satir_uid": uuid.uuid4().hex,
        "urun_kodu": kod,  # Barkod sütunu varsa oraya da yazılır; kod alanında da görünür
        "urun_adi": "",
        "aciklama": "",
        "miktar": "1",
        "birim": "",
        "birim_satis_fiyati": "0",
        "iskonto_orani": "0",
        "iskonto_orani_2": "0",
        "iskonto_orani_3": "0",
        "kdv_orani": "0",
        "barkod": kod,
        "ham_barkod": kod,
        "cozulmemis": True,
        "cozulmemis_neden": (neden or "").strip(),
        "lot_no": "",
        "lot_cikisi": "",
        "depo": "",
        "satir_para_birimi": "TRY",
        "manuel_fiyat": False,
        "irsaliyelenen_miktar": 0,
        "faturalanan_miktar": 0,
        "fifo_birim_maliyeti": "0",
        "son_alis_birim_maliyeti": "0",
        "ortalama_birim_maliyeti": "0",
        "agirlikli_ortalama_birim_maliyeti": "0",
        "temel_miktar": "1",
        "product_id": None,
        "stok_id": None,
    }


def _cozulmemis_satir_ekle(
    dialog, barkod: str, *, neden: str = "", sira_id: int | None = None
) -> int | None:
    """Tanımsız/çakışan barkodu ürün adı boş satıra yazar; aynı barkodda miktar artar."""
    from satir_ici_urun_giris import ekleme_konumu

    kod = barkod_temizle(barkod)
    # Aynı tanımsız barkod → mevcut boş adlı satırda miktar +1
    idx_mevcut = _barkod_satir_indeksi(dialog, kod)
    if idx_mevcut is not None and satir_cozulmemis_mi(dialog.satirlar[idx_mevcut]):
        return _miktar_artir(dialog, idx_mevcut)

    konum = ekleme_konumu(dialog)
    sablon = _cozulmemis_sablon(barkod, neden=neden)
    depo = ""
    try:
        depo = (dialog.depo.get() or "").strip()
    except Exception:
        depo = ""
    sablon["depo"] = depo
    if sira_id is not None:
        sablon["barkod_sira_id"] = sira_id

    hazirla = belge_kancasi(dialog, "_yeni_satir_hazirla")
    if hazirla is not None:
        hazir = hazirla(sablon)
        if hazir is None:
            _durum_yaz(dialog, f"Eklenmedi: {barkod}", hata=True)
            return None
        hazir["urun_adi"] = ""
        hazir["cozulmemis"] = True
        hazir["barkod"] = sablon["barkod"]
        hazir["ham_barkod"] = sablon["ham_barkod"]
        if not hazir.get("satir_uid"):
            hazir["satir_uid"] = sablon["satir_uid"]
        sablon = hazir

    from fatura_satir_hucre_edit import uzlasma_etkisini_kaldir

    uzlasma_etkisini_kaldir(dialog, yalniz_referansli=True)
    if konum is not None and 0 <= konum <= len(dialog.satirlar):
        idx = konum
        dialog.satirlar.insert(idx, sablon)
    else:
        dialog.satirlar.append(sablon)
        idx = len(dialog.satirlar) - 1

    _barkod_hedef_kaydet(dialog, kod, sablon)
    dialog._fatura_satirlari_hazir = True
    dialog._duzenlenen_satir = None
    dialog._satir_listesini_yenile()
    dialog._toplamlari_guncelle()
    _satiri_vurgula(dialog, idx, etiket="cozulmemis_vurgu")
    _durum_yaz(dialog, f"Tanımsız: {barkod} → satır {idx + 1}", hata=True)
    dialog._son_barkod_idx = idx
    return idx


def _satira_uygula(
    dialog, kayit: dict, *, okutulan_barkod: str, birlestir: bool = True
) -> int | None:
    """Yeni satır ekle veya aynı barkodda miktar +1 (varsayılan: birleştir)."""
    from satir_ici_urun_giris import ekleme_konumu

    konum = ekleme_konumu(dialog)
    depo = ""
    try:
        depo = (dialog.depo.get() or "").strip()
    except Exception:
        depo = ""

    barkod_fiyat = _d(kayit.get("birim_fiyat"), Decimal("0"))
    stok_kodu = (kayit.get("stok_kodu") or "").strip()
    fiyat = _musteri_fiyat(dialog, stok_kodu, barkod_fiyat)
    carpan = _d(kayit.get("carpan"), Decimal("1"))
    miktar_ekle = Decimal("1")
    birim = (
        (kayit.get("barkod_birim") or kayit.get("birim") or "Adet").strip() or "Adet"
    )
    if carpan > 1 and (kayit.get("barkod_birim") or "").strip():
        paket = _d(kayit.get("paket_fiyat"), Decimal("0"))
        if paket > 0:
            fiyat = _musteri_fiyat(dialog, stok_kodu, paket)

    kdv = kayit.get("kdv_orani")
    if kdv is None:
        kdv = Decimal("20")
    else:
        kdv = _d(kdv, Decimal("20"))

    iskonto1 = Decimal("0")
    product_id = kayit.get("stok_id") or kayit.get("product_id")
    try:
        from fatura_urun_aktar_service import (
            urun_kartindan_tanimlayicilar,
            urun_secim_seridini_doldur,
        )

        satir_barkod, satir_kod, satir_ad = urun_kartindan_tanimlayicilar(
            product_id=product_id,
            stok_kodu=stok_kodu,
            okutulan_barkod=okutulan_barkod or "",
        )
    except Exception:
        satir_barkod = (okutulan_barkod or kayit.get("barkod") or "").strip()
        satir_kod = stok_kodu
        satir_ad = (kayit.get("stok_adi") or "").strip()

    try:
        stoklar = StokService.stoklari_ara(satir_kod or stok_kodu)
        stok = next(
            (s for s in stoklar if s.stok_kodu == (satir_kod or stok_kodu)), None
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

    import uuid

    sablon = {
        "satir_uid": uuid.uuid4().hex,
        "urun_kodu": satir_kod or stok_kodu,
        "urun_adi": satir_ad or kayit.get("stok_adi") or "",
        "aciklama": "",
        "miktar": str(miktar_ekle),
        "birim": birim,
        "birim_satis_fiyati": str(fiyat),
        "iskonto_orani": str(iskonto1),
        "iskonto_orani_2": "0",
        "iskonto_orani_3": "0",
        "kdv_orani": str(kdv),
        "barkod": satir_barkod or (okutulan_barkod or kayit.get("barkod") or ""),
        "ham_barkod": (okutulan_barkod or "").strip(),
        "cozulmemis": False,
        "lot_no": (kayit.get("lot_no") or ""),
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
        "product_id": product_id,
        "stok_id": product_id,
    }

    try:
        urun_secim_seridini_doldur(
            dialog,
            sablon["barkod"],
            sablon["urun_kodu"],
            sablon["urun_adi"],
        )
    except Exception:
        pass

    from fatura_satir_birim_service import temel_miktar

    birim_satir = sablon.get("birim") or kayit.get("birim") or "Adet"
    ek_temel = temel_miktar(miktar_ekle, birim_satir, sablon["urun_kodu"])

    hedef_idx = None
    if birlestir and konum is None:
        aday = _barkod_satir_indeksi(dialog, okutulan_barkod or sablon["barkod"])
        if aday is not None:
            mevcut = dialog.satirlar[aday]
            if satir_cozulmemis_mi(mevcut):
                # Aynı barkodlu boş adlı satırı ürünle doldur; bu tarama miktarı +1
                from fatura_urun_aktar_service import stoktan_satir_sablonu

                eski_miktar = _d(mevcut.get("miktar"), Decimal("1"))
                ham = (mevcut.get("ham_barkod") or mevcut.get("barkod") or okutulan_barkod or "").strip()
                uid = _satir_uid_ver(mevcut)
                try:
                    dolu = stoktan_satir_sablonu(
                        dialog,
                        urun_kodu=sablon["urun_kodu"],
                        urun_adi=sablon["urun_adi"],
                        birim=sablon["birim"],
                        miktar=eski_miktar,
                        product_id=product_id,
                        barkod=ham or sablon["barkod"],
                    )
                except TypeError:
                    dolu = dict(sablon)
                    dolu["miktar"] = str(eski_miktar)
                except Exception:
                    dolu = dict(sablon)
                    dolu["miktar"] = str(eski_miktar)
                dolu["satir_uid"] = uid
                dolu["ham_barkod"] = ham
                dolu["barkod"] = ham or dolu.get("barkod") or sablon["barkod"]
                dolu["cozulmemis"] = False
                dolu.pop("cozulmemis_neden", None)
                dialog.satirlar[aday] = dolu
                _barkod_hedef_kaydet(dialog, okutulan_barkod or ham, dolu)
                return _miktar_artir(dialog, aday, miktar_ekle=miktar_ekle)
            if _satir_birlestirilebilir(mevcut, sablon, depo=depo):
                hedef_idx = aday
        if hedef_idx is None:
            for i, mevcut in enumerate(dialog.satirlar):
                ayni_barkod = (
                    barkod_temizle(mevcut.get("barkod") or mevcut.get("ham_barkod") or "")
                    == barkod_temizle(okutulan_barkod or sablon["barkod"] or "")
                    and bool(okutulan_barkod or sablon["barkod"])
                )
                ayni_kod = (mevcut.get("urun_kodu") or "").strip() == sablon["urun_kodu"]
                if (ayni_barkod or ayni_kod) and _satir_birlestirilebilir(
                    mevcut, sablon, depo=depo
                ):
                    hedef_idx = i
                    break

    if hedef_idx is not None:
        _barkod_hedef_kaydet(dialog, okutulan_barkod or sablon["barkod"], dialog.satirlar[hedef_idx])
        return _miktar_artir(dialog, hedef_idx, miktar_ekle=miktar_ekle)

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
    hazirla = belge_kancasi(dialog, "_yeni_satir_hazirla")
    if hazirla is not None:
        hazir = hazirla(sablon)
        if hazir is None:
            _durum_yaz(
                dialog,
                f"Eklenmedi: {sablon.get('urun_adi') or sablon['urun_kodu']}",
                hata=True,
            )
            return None
        if not hazir.get("satir_uid"):
            hazir["satir_uid"] = sablon["satir_uid"]
        sablon = hazir

    from fatura_satir_hucre_edit import uzlasma_etkisini_kaldir

    uzlasma_etkisini_kaldir(dialog, yalniz_referansli=True)
    sablon["temel_miktar"] = str(ek_temel)
    if hasattr(dialog, "_doviz_para_birimi"):
        try:
            from doviz_fatura_panel import doviz_satir_kaydet_oncesi

            sablon = doviz_satir_kaydet_oncesi(dialog, sablon)
        except Exception:
            pass
    if konum is not None and 0 <= konum <= len(dialog.satirlar):
        idx = konum
        dialog.satirlar.insert(idx, sablon)
    else:
        dialog.satirlar.append(sablon)
        idx = len(dialog.satirlar) - 1
    _barkod_hedef_kaydet(dialog, okutulan_barkod or sablon["barkod"], sablon)

    dialog._fatura_satirlari_hazir = True
    dialog._duzenlenen_satir = None
    dialog._satir_listesini_yenile()
    dialog._toplamlari_guncelle()
    _satiri_vurgula(dialog, idx)
    ad = sablon.get("urun_adi") or kayit.get("stok_adi") or kayit.get("stok_kodu")
    _durum_yaz(dialog, f"Eklendi: {ad}")
    if hasattr(dialog, "barkod_okut_entry"):
        try:
            dialog.barkod_okut_entry.delete(0, "end")
        except Exception:
            pass
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
    dialog._son_barkod_idx = idx
    return idx


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


def _satiri_vurgula(dialog, idx: int, *, etiket: str = "barkod_vurgu") -> None:
    tablo = getattr(dialog, "satir_tablosu", None)
    if tablo is None:
        return
    iid = str(idx)
    try:
        if etiket == "cozulmemis_vurgu":
            tablo.tag_configure(
                "cozulmemis_vurgu", background="#FFF3E0", foreground="#E65100"
            )
            tablo.tag_configure(
                "cozulmemis", background="#FFF8E1", foreground="#5D4037"
            )
        else:
            tablo.tag_configure(
                "barkod_vurgu", background="#C8E6C9", foreground="#1B5E20"
            )
        tags = list(tablo.item(iid, "tags") or ())
        if etiket not in tags:
            tags.append(etiket)
        if etiket == "cozulmemis_vurgu" and "cozulmemis" not in tags:
            tags.append("cozulmemis")
        tablo.item(iid, tags=tags)
        tablo.selection_set(iid)
        tablo.focus(iid)
        tablo.see(iid)
    except tk.TclError:
        return

    def _kaldir():
        try:
            tags = [
                t
                for t in (tablo.item(iid, "tags") or ())
                if t not in ("barkod_vurgu", "cozulmemis_vurgu")
            ]
            tablo.item(iid, tags=tags)
        except tk.TclError:
            pass

    try:
        dialog.after(700, _kaldir)
    except tk.TclError:
        pass


def barkod_nesil_artir(dialog) -> None:
    """Yeni fatura / kapat / firma değişiminde bekleyen sonuçların yanlış belgeye yazılmasını önler."""
    dialog._barkod_nesil = int(getattr(dialog, "_barkod_nesil", 0) or 0) + 1
    kuyruk = getattr(dialog, "_barkod_kuyruk", None)
    if kuyruk:
        bekleyen = list(kuyruk)
        kuyruk.clear()
        if bekleyen:
            kodlar = ", ".join(o.get("barkod", "") for o in bekleyen[:5])
            _durum_yaz(
                dialog,
                f"Bekleyen {len(bekleyen)} tarama belge değişince uygulandı: {kodlar}",
                hata=True,
            )
