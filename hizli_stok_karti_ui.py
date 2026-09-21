"""Satış faturası — Hızlı Stok Kartı oluşturma penceresi."""

from __future__ import annotations

import logging
import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import messagebox, ttk
from typing import Any, Callable

from database.access import yetki_var
from database.fatura_kdv_service import firma_varsayilan_kdv_orani, satir_kdv_metin_sayisal
from database.stok_service import StokService, decimal
from database.user_audit import audit_document

_LOG = logging.getLogger("hizli_stok_karti")


def _para_birimi_fatura(fatura_dialog) -> str:
    try:
        if hasattr(fatura_dialog, "_doviz_para_birimi"):
            return (fatura_dialog._doviz_para_birimi.get() or "TRY").upper()
    except Exception:
        pass
    return "TRY"


def _depo_fatura(fatura_dialog) -> str:
    try:
        if hasattr(fatura_dialog, "depo"):
            return (fatura_dialog.depo.get() or "").strip()
    except Exception:
        pass
    return ""


def _urun_adi_arama(fatura_dialog) -> str:
    try:
        w = (getattr(fatura_dialog, "satir_girdileri", None) or {}).get("urun_adi")
        if w is not None:
            return (w.get() or "").strip()
    except Exception:
        pass
    return ""


def mukerrer_kontrol(*, stok_kodu: str, barkod: str, stok_adi: str) -> dict[str, Any]:
    """Barkod / kod çakışması ve benzer ad uyarısı."""
    kod = (stok_kodu or "").strip()
    bar = (barkod or "").strip()
    ad = (stok_adi or "").strip()
    sonuc: dict[str, Any] = {
        "kod_cakisma": None,
        "barkod_cakisma": None,
        "benzer_adlar": [],
    }
    if kod:
        mevcut = StokService.stoklari_ara(kod)
        for s in mevcut:
            if (s.stok_kodu or "").strip().casefold() == kod.casefold():
                sonuc["kod_cakisma"] = s
                break
    if bar:
        bulunan = StokService.barkod_ile_bul(bar)
        if bulunan:
            stok = StokService.stok_getir(bulunan.get("stok_id"))
            if stok is None:
                # dict yeterli
                class _S:
                    pass

                stok = _S()
                stok.id = bulunan.get("stok_id")
                stok.stok_kodu = bulunan.get("stok_kodu")
                stok.stok_adi = bulunan.get("stok_adi")
                stok.birim = bulunan.get("birim") or "Adet"
                stok.kdv_orani = bulunan.get("kdv_orani")
            sonuc["barkod_cakisma"] = stok
    if ad and len(ad) >= 3:
        adaylar = StokService.stoklari_ara(ad)[:8]
        ad_cf = ad.casefold()
        for s in adaylar:
            sad = (s.stok_adi or "").strip()
            if not sad:
                continue
            if sad.casefold() == ad_cf or ad_cf in sad.casefold() or sad.casefold() in ad_cf:
                sonuc["benzer_adlar"].append(s)
    return sonuc


class HizliStokKartiDialog(tk.Toplevel):
    """Fatura içi sade hızlı stok kartı — tam StokKartiDialog kopyası değil."""

    def __init__(
        self,
        parent,
        *,
        fatura_dialog=None,
        baslangic: dict[str, Any] | None = None,
        mesaj_id: int | None = None,
        on_faturaya_ekle: Callable[[Any], None] | None = None,
    ):
        super().__init__(parent)
        self.fatura_dialog = fatura_dialog or parent
        self.mesaj_id = mesaj_id
        self.on_faturaya_ekle = on_faturaya_ekle
        self.result = None
        self.title("Hızlı Stok Kartı")
        self.geometry("520x560")
        self.resizable(False, True)
        self.transient(parent)
        # grab_set yok — fatura arka planda kalsın; kontrollü modal benzeri
        try:
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass

        if not yetki_var("stok_duzenleme", "yeni_kayit"):
            messagebox.showwarning(
                "Yetki",
                "Stok kartı oluşturma yetkiniz yok.",
                parent=self,
            )
            self.after(10, self.destroy)
            return

        bas = dict(baslangic or {})
        if not bas.get("stok_adi"):
            bas["stok_adi"] = _urun_adi_arama(self.fatura_dialog)
        if not bas.get("depo"):
            bas["depo"] = _depo_fatura(self.fatura_dialog)
        if not bas.get("para_birimi"):
            bas["para_birimi"] = _para_birimi_fatura(self.fatura_dialog)
        if not bas.get("birim"):
            bas["birim"] = "Adet"
        if bas.get("kdv_orani") in (None, ""):
            try:
                bas["kdv_orani"] = firma_varsayilan_kdv_orani()
            except Exception:
                bas["kdv_orani"] = Decimal("20")
        if not bas.get("stok_kodu"):
            # Barkod bulunamadı: hem stok kodu hem barkod aynı 13 haneli kod
            bar_aday = str(bas.get("barkod") or "").strip()
            if bar_aday.isdigit() and len(bar_aday) == 13:
                bas["stok_kodu"] = bar_aday
            else:
                try:
                    bas["stok_kodu"] = StokService.ean13_olustur()
                except Exception:
                    bas["stok_kodu"] = ""
        # 13 haneli stok kodu → barkod alanı (metin; baştaki sıfır korunur)
        from database.stok_kodu_barkod_service import (
            is_13_digit_barcode,
            normalize_stock_code_as_text,
        )

        kod0 = normalize_stock_code_as_text(bas.get("stok_kodu"))
        bar0 = normalize_stock_code_as_text(bas.get("barkod"))
        if is_13_digit_barcode(kod0) and not bar0:
            bas["barkod"] = kod0

        self._alanlar: dict[str, tk.Variable | ttk.Combobox | ttk.Entry] = {}
        govde = ttk.Frame(self, padding=12)
        govde.pack(fill="both", expand=True)

        birimler = list(StokService.secenekleri_listele("birim") or [])
        for zorunlu in ("Adet", "Kilogram", "Metre", "Koli", "Paket", "Torba", "Boy", "Top"):
            if zorunlu not in birimler:
                birimler.append(zorunlu)
        gruplar = list(StokService.secenekleri_listele("rapor_grubu") or [])
        try:
            from database.models.stok import Depo
            from database.stok_service import StokService as _SS

            depolar = [d.ad for d in (_SS.depolar(aktif_only=True) or [])]
        except Exception:
            depolar = []

        def _satir(etiket: str, satir_no: int, widget):
            ttk.Label(govde, text=etiket).grid(row=satir_no, column=0, sticky="e", pady=3, padx=(0, 6))
            widget.grid(row=satir_no, column=1, sticky="ew", pady=3)
            return widget

        govde.columnconfigure(1, weight=1)
        r = 0
        self.kod = ttk.Entry(govde, width=36)
        self.kod.insert(0, bas.get("stok_kodu") or "")
        _satir("Stok kodu *", r, self.kod)
        r += 1
        self.ad = ttk.Entry(govde, width=36)
        self.ad.insert(0, bas.get("stok_adi") or "")
        _satir("Ürün adı *", r, self.ad)
        r += 1
        self.birim = ttk.Combobox(govde, values=tuple(birimler), width=33)
        self.birim.set(bas.get("birim") or "Adet")
        _satir("Birim *", r, self.birim)
        r += 1
        self.kdv = ttk.Entry(govde, width=36)
        self.kdv.insert(0, satir_kdv_metin_sayisal(bas.get("kdv_orani")))
        _satir("KDV oranı *", r, self.kdv)
        r += 1
        self.grup = ttk.Combobox(govde, values=tuple(gruplar), width=33)
        self.grup.set(bas.get("rapor_grubu") or (gruplar[0] if gruplar else ""))
        _satir("Stok grubu *", r, self.grup)
        r += 1
        self.barkod = ttk.Entry(govde, width=36)
        self.barkod.insert(0, bas.get("barkod") or "")
        _satir("Barkod", r, self.barkod)
        r += 1
        self._barkod_otomatik = bool(
            is_13_digit_barcode(self.kod.get())
            and normalize_stock_code_as_text(self.barkod.get())
            == normalize_stock_code_as_text(self.kod.get())
        )
        self.kod.bind("<KeyRelease>", self._stok_kodu_barkod_doldur)
        self.marka = ttk.Entry(govde, width=36)
        self.marka.insert(0, bas.get("marka") or "")
        _satir("Marka", r, self.marka)
        r += 1
        self.alis = ttk.Entry(govde, width=36)
        self.alis.insert(0, str(bas.get("alis_fiyati") or ""))
        _satir("Alış fiyatı", r, self.alis)
        r += 1
        self.satis = ttk.Entry(govde, width=36)
        self.satis.insert(0, str(bas.get("satis_fiyati") or ""))
        _satir("Satış fiyatı", r, self.satis)
        r += 1
        self.pb = ttk.Combobox(govde, values=("TRY", "USD", "EUR"), width=33)
        self.pb.set(bas.get("para_birimi") or "TRY")
        _satir("Para birimi", r, self.pb)
        r += 1
        self.depo = ttk.Combobox(govde, values=tuple(depolar), width=33)
        self.depo.set(bas.get("depo") or "")
        _satir("Depo", r, self.depo)
        r += 1
        self.acilis = ttk.Entry(govde, width=36)
        self.acilis.insert(0, str(bas.get("acilis_miktar") or "0"))
        _satir("Açılış stok miktarı", r, self.acilis)
        r += 1
        self.min_stok = ttk.Entry(govde, width=36)
        self.min_stok.insert(0, str(bas.get("minimum_stok") or "0"))
        _satir("Minimum stok", r, self.min_stok)
        r += 1
        self.raf = ttk.Entry(govde, width=36)
        self.raf.insert(0, bas.get("raf_yeri") or "")
        _satir("Raf konumu", r, self.raf)
        r += 1
        self.aciklama = ttk.Entry(govde, width=36)
        self.aciklama.insert(0, bas.get("aciklama") or "")
        _satir("Açıklama", r, self.aciklama)
        r += 1

        ttk.Label(
            govde,
            text="* zorunlu alanlar",
            foreground="#6B7280",
            font=("Segoe UI", 8),
        ).grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0))
        r += 1

        alt = ttk.Frame(govde)
        alt.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Button(alt, text="Vazgeç", command=self.destroy).pack(side="right")
        ttk.Button(
            alt, text="Kaydet ve Faturaya Ekle", command=lambda: self._kaydet(faturaya=True)
        ).pack(side="right", padx=6)
        ttk.Button(alt, text="Kaydet", command=lambda: self._kaydet(faturaya=False)).pack(
            side="right"
        )
        ttk.Button(alt, text="Detaylı Stok Kartını Aç", command=self._detayli_ac).pack(
            side="left"
        )

        self.ad.focus_set()

    def _stok_kodu_barkod_doldur(self, _event=None):
        from database.stok_kodu_barkod_service import (
            is_13_digit_barcode,
            normalize_stock_code_as_text,
        )

        kod = normalize_stock_code_as_text(self.kod.get())
        bar = normalize_stock_code_as_text(self.barkod.get())
        if is_13_digit_barcode(kod):
            if not bar or getattr(self, "_barkod_otomatik", False):
                self.barkod.delete(0, "end")
                self.barkod.insert(0, kod)
                self._barkod_otomatik = True
        elif getattr(self, "_barkod_otomatik", False):
            self.barkod.delete(0, "end")
            self._barkod_otomatik = False

    def _detayli_ac(self):
        try:
            from stok_ui import StokKartiDialog

            StokKartiDialog(
                self.fatura_dialog,
                baslangic={
                    "stok_kodu": self.kod.get().strip(),
                    "stok_adi": self.ad.get().strip(),
                    "barkod": self.barkod.get().strip(),
                },
            )
        except Exception as exc:
            messagebox.showerror("Stok", str(exc), parent=self)

    def _veri_topla(self) -> dict[str, Any]:
        kod = self.kod.get().strip()
        ad = self.ad.get().strip()
        birim = (self.birim.get() or "Adet").strip() or "Adet"
        grup = (self.grup.get() or "").strip()
        if not kod:
            raise ValueError("Stok kodu zorunludur.")
        if not ad:
            raise ValueError("Ürün adı zorunludur.")
        if not grup:
            raise ValueError("Stok grubu zorunludur.")
        kdv = decimal(self.kdv.get() or firma_varsayilan_kdv_orani(), "KDV oranı")
        acilis = decimal(self.acilis.get() or 0, "Açılış stok", Decimal("0"))
        if acilis < 0:
            raise ValueError("Açılış stok miktarı negatif olamaz.")
        if acilis > 0 and not yetki_var("stok_duzenleme", "yeni_kayit"):
            raise ValueError("Açılış stok girişi için yetkiniz yok.")
        return {
            "stok_kodu": kod,
            "stok_adi": ad,
            "birim": birim,
            "kdv_orani": kdv,
            "rapor_grubu": grup,
            "barkod": self.barkod.get().strip(),
            "marka": self.marka.get().strip() or None,
            "alis_fiyati": self.alis.get().strip(),
            "satis_fiyati": self.satis.get().strip(),
            "para_birimi": (self.pb.get() or "TRY").upper(),
            "depo": (self.depo.get() or "").strip(),
            "acilis_miktar": acilis,
            "minimum_stok": self.min_stok.get().strip() or "0",
            "raf_yeri": self.raf.get().strip() or None,
            "aciklama": self.aciklama.get().strip() or None,
        }

    def _mukerrer_dialog(self, stok) -> str | None:
        """Dönüş: ekle | ac | vazgec | None"""
        win = tk.Toplevel(self)
        win.title("Mükerrer stok")
        win.transient(self)
        win.grab_set()
        ttk.Label(
            win,
            text=(
                f"Bu barkod/kod zaten kayıtlı:\n"
                f"{getattr(stok, 'stok_kodu', '')} — {getattr(stok, 'stok_adi', '')}\n\n"
                f"Ne yapmak istersiniz?"
            ),
            justify="left",
        ).pack(padx=14, pady=12)
        secim = {"v": None}

        def _sec(v):
            secim["v"] = v
            win.destroy()

        alt = ttk.Frame(win)
        alt.pack(fill="x", pady=8, padx=12)
        ttk.Button(alt, text="Mevcut Stoku Faturaya Ekle", command=lambda: _sec("ekle")).pack(
            fill="x", pady=2
        )
        ttk.Button(alt, text="Mevcut Stok Kartını Aç", command=lambda: _sec("ac")).pack(
            fill="x", pady=2
        )
        ttk.Button(alt, text="Vazgeç", command=lambda: _sec("vazgec")).pack(fill="x", pady=2)
        self.wait_window(win)
        return secim["v"]

    def _kaydet(self, *, faturaya: bool):
        try:
            veri = self._veri_topla()
        except ValueError as exc:
            messagebox.showwarning("Hızlı Stok", str(exc), parent=self)
            return

        kontrol = mukerrer_kontrol(
            stok_kodu=veri["stok_kodu"],
            barkod=veri["barkod"],
            stok_adi=veri["stok_adi"],
        )
        cakisan = kontrol["barkod_cakisma"] or kontrol["kod_cakisma"]
        if cakisan is not None:
            karar = self._mukerrer_dialog(cakisan)
            if karar == "ekle":
                self._mevcut_faturaya_ekle(cakisan)
                self.destroy()
                return
            if karar == "ac":
                try:
                    from stok_ui import StokKartiDialog

                    StokKartiDialog(self.fatura_dialog, stok=cakisan)
                except Exception as exc:
                    messagebox.showerror("Stok", str(exc), parent=self)
                return
            return

        if kontrol["benzer_adlar"]:
            ornek = ", ".join(
                f"{s.stok_kodu} ({s.stok_adi})" for s in kontrol["benzer_adlar"][:3]
            )
            if not messagebox.askyesno(
                "Benzer ürün",
                f"Benzer ürün adları bulundu:\n{ornek}\n\nYine de yeni kart oluşturulsun mu?",
                parent=self,
            ):
                return

        try:
            stok = self._stok_olustur(veri)
        except ValueError as exc:
            messagebox.showerror("Hızlı Stok", str(exc), parent=self)
            return
        except Exception as exc:
            _LOG.exception("hızlı stok kaydı")
            messagebox.showerror("Hızlı Stok", f"Kayıt başarısız:\n{exc}", parent=self)
            return

        self.result = stok
        if self.mesaj_id:
            try:
                from database.invoice_scan_message_service import mesaj_cozuldu_isaretle
                from fatura_mesaj_paneli import _baslik_guncelle

                mesaj_cozuldu_isaretle(
                    self.mesaj_id,
                    stok_kodu=stok.stok_kodu,
                    stok_adi=stok.stok_adi,
                )
                # Panelden kaldır
                fd = self.fatura_dialog
                if fd is not None:
                    bilgi = (getattr(fd, "_mesaj_paneli_satirlar", None) or {}).pop(
                        self.mesaj_id, None
                    )
                    if bilgi and bilgi.get("frame"):
                        try:
                            bilgi["frame"].destroy()
                        except tk.TclError:
                            pass
                    try:
                        _baslik_guncelle(fd)
                    except Exception:
                        pass
            except Exception:
                _LOG.exception("mesaj çözüldü işaretlenemedi")

        if faturaya:
            self._mevcut_faturaya_ekle(stok, fiyat_hint=veri.get("satis_fiyati"))
            if self.on_faturaya_ekle:
                try:
                    self.on_faturaya_ekle(stok)
                except Exception:
                    pass
        self.destroy()

    def _stok_olustur(self, veri: dict[str, Any]):
        fiyatlar = []
        if (veri.get("alis_fiyati") or "").strip():
            fiyatlar.append(("ALIŞ FİYATI", veri["alis_fiyati"]))
        if (veri.get("satis_fiyati") or "").strip():
            fiyatlar.append(("SATIŞ FİYATI 1", veri["satis_fiyati"]))
        barkodlar = []
        bar = str(veri.get("barkod") or "").strip()
        kod = str(veri.get("stok_kodu") or "").strip()
        from database.stok_kodu_barkod_service import is_13_digit_barcode

        if not bar and is_13_digit_barcode(kod):
            bar = kod
        if bar:
            barkodlar.append(
                {
                    "barkod": bar,  # metin
                    "birim": veri["birim"],
                    "fiyat_adi": "SATIŞ FİYATI 1",
                    "fiyat": veri.get("satis_fiyati") or "0",
                }
            )
        kart_veri = {
            "stok_kodu": veri["stok_kodu"],
            "stok_adi": veri["stok_adi"],
            "birim": veri["birim"],
            "kdv_orani": veri["kdv_orani"],
            "rapor_grubu": veri["rapor_grubu"],
            "marka": veri.get("marka"),
            "raf_yeri": veri.get("raf_yeri"),
            "minimum_stok": veri.get("minimum_stok") or "0",
            "aciklama": veri.get("aciklama"),
            "kart_turu": "Ticari Mal",
        }
        stok = StokService.stok_kaydi(
            kart_veri,
            fiyatlar,
            birimler=None,
            barkodlar=barkodlar or None,
        )
        try:
            StokService._teklif_arama_onbellek.clear()
        except Exception:
            pass
        audit_document(
            "HIZLI_STOK_OLUSTUR",
            modul="stok",
            kayit_id=str(getattr(stok, "id", "")),
            belge_no=stok.stok_kodu,
            yeni={
                "kaynak": "Satış Faturası – Hızlı Stok Oluşturma",
                "stok_kodu": stok.stok_kodu,
                "stok_adi": stok.stok_adi,
            },
        )
        acilis = Decimal(str(veri.get("acilis_miktar") or 0))
        depo = (veri.get("depo") or "").strip()
        if acilis > 0:
            if not depo:
                raise ValueError("Açılış stok için depo seçilmelidir.")
            maliyet = Decimal("0")
            if (veri.get("alis_fiyati") or "").strip():
                try:
                    maliyet = decimal(veri["alis_fiyati"], "Alış fiyatı")
                except Exception:
                    maliyet = Decimal("0")
            StokService.stok_girisi(
                stok.stok_kodu,
                depo,
                "AÇILIŞ",
                date.today(),
                acilis,
                maliyet,
                lot_no="ACILIS",
            )
        return StokService.stok_getir(stok.id) or stok

    def _mevcut_faturaya_ekle(self, stok, fiyat_hint: str | None = None):
        fd = self.fatura_dialog
        if fd is None:
            return
        from fatura_urun_aktar_service import urun_seciminden_aktar

        fiyat = StokService.satis_fiyati_1(stok.stok_kodu)
        if fiyat_hint and str(fiyat_hint).strip():
            try:
                fiyat = decimal(fiyat_hint, "Satış fiyatı")
            except Exception:
                pass
        kdv = satir_kdv_metin_sayisal(getattr(stok, "kdv_orani", None) or 20)
        degerler = (
            stok.stok_kodu,
            stok.stok_adi,
            stok.birim or "Adet",
            "0",
            f"{fiyat:f}".rstrip("0").rstrip(".") or "0",
            "Stok Kartı",
            kdv,
        )
        try:
            urun_seciminden_aktar(fd, degerler)
        except Exception as exc:
            messagebox.showerror("Fatura", str(exc), parent=self)
            return
        # Odak: fiyat yoksa fiyat hücresi, varsa miktar
        try:
            from fatura_satir_hucre_edit import focus_editable_cell, satir_ilk_alana_odakla

            idx = len(getattr(fd, "satirlar", []) or []) - 1
            if idx < 0:
                return
            if Decimal(str(fiyat or 0)) <= 0:
                focus_editable_cell(fd, idx, "fiyat")
            else:
                satir_ilk_alana_odakla(fd, idx)
        except Exception:
            pass
        try:
            from fatura_barkod_ui import _barkod_odak

            if hasattr(fd, "barkod_okut_entry"):
                fd.barkod_okut_entry.delete(0, "end")
            _barkod_odak(fd)
        except Exception:
            pass


def hizli_stok_karti_ac(
    fatura_dialog,
    *,
    barkod: str | None = None,
    urun_adi: str | None = None,
    mesaj_id: int | None = None,
    on_faturaya_ekle: Callable | None = None,
):
    """Yetki kontrolü + pencere aç."""
    if not yetki_var("stok_duzenleme", "yeni_kayit"):
        messagebox.showwarning(
            "Yetki",
            "Stok kartı oluşturma yetkiniz yok.",
            parent=fatura_dialog,
        )
        return None
    bas = {}
    if barkod:
        bas["barkod"] = str(barkod).strip()
        # Barkod bulunamadı → stok kodu da aynı metin
        bas["stok_kodu"] = str(barkod).strip()
    if urun_adi:
        bas["stok_adi"] = urun_adi
    dlg = HizliStokKartiDialog(
        fatura_dialog,
        fatura_dialog=fatura_dialog,
        baslangic=bas,
        mesaj_id=mesaj_id,
        on_faturaya_ekle=on_faturaya_ekle,
    )
    fatura_dialog.wait_window(dlg)
    return dlg.result
