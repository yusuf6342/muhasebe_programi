"""Hızlı Satış Gün Sonu — fatura bazlı liste ve mevcut faturayı düzenleme."""

from __future__ import annotations

import logging
import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, ttk
from typing import Any

from database.hizli_satis_service import HizliSatisService
from ui_takvim import takvim_butonu

_LOG = logging.getLogger(__name__)

SARI = "#F5C518"
KOYU_GRI = "#2B2F33"
ACIK_GRI = "#F3F4F6"
YESIL = "#2E7D32"
KIRMIZI = "#C62828"
BEYAZ = "#FFFFFF"
TURUNCU = "#EF6C00"
LACIVERT = "#0B2A4A"


def _para(tutar) -> str:
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih_metin(d: date | None) -> str:
    if d is None:
        return ""
    return d.strftime("%d.%m.%Y")


def _tarih_oku(metin: str) -> date:
    metin = (metin or "").strip()
    for bicim in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
    raise ValueError(f"Tarih anlaşılamadı: {metin}")


class HizliSatisGunSonuDialog(tk.Toplevel):
    """Günün kayıtlı hızlı satış faturalarını listeler; günü kapatmaz / kilitlemez.

    Satır tıklanınca mevcut Satış Faturası kartı açılır; kapanınca Hızlı Satış
    penceresi korunur (sepet sıfırlanmaz).
    """

    def __init__(self, parent, *, tarih: date | None = None):
        super().__init__(parent)
        self.hs_parent = parent
        self.tarih = tarih or date.today()
        self._satirlar: list[dict[str, Any]] = []
        self._fatura_aciliyor = False
        self._bos_lbl: tk.Label | None = None

        self.title("Hızlı Satış — Gün Sonu")
        self.configure(bg=KOYU_GRI)
        self.geometry("1080x620")
        self.minsize(900, 520)
        try:
            self.transient(parent)
        except tk.TclError:
            pass

        try:
            self._kur()
        except Exception as hata:  # noqa: BLE001
            _LOG.exception("Gün Sonu arayüz kurulumu başarısız")
            try:
                messagebox.showerror(
                    "Gün Sonu",
                    "Gün Sonu ekranı oluşturulamadı.\n\n" + str(hata),
                    parent=parent if parent is not None else self,
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                self.destroy()
            except tk.TclError:
                pass
            raise

        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<F5>", lambda _e: self._yenile())
        try:
            self.grab_set()
            from ui_pencere import pencere_os_krom_ac

            pencere_os_krom_ac(self)
        except tk.TclError:
            pass
        # wait_visibility mainloop olmadan kilitlenir; idle ile yükle/odakla
        self.after_idle(self._yenile)
        self.after(80, self._odak_guvenli)

    def _odak_guvenli(self) -> None:
        try:
            if self.winfo_exists():
                self.lift()
                self.focus_force()
        except tk.TclError:
            pass

    def _kur(self) -> None:
        # Alt çubuğu önce paketle (expand gövde yer kaplamadan önce)
        alt = tk.Frame(self, bg=KOYU_GRI)
        alt.pack(fill="x", side="bottom", padx=12, pady=10)
        tk.Button(
            alt,
            text="Faturayı Aç",
            command=self._seciliyi_ac,
            bg=YESIL,
            fg=BEYAZ,
            relief="flat",
            padx=14,
            pady=8,
        ).pack(side="left")
        tk.Button(
            alt,
            text="Kapat",
            command=self.destroy,
            bg="#757575",
            fg=BEYAZ,
            relief="flat",
            padx=14,
            pady=8,
        ).pack(side="right")

        ozet = tk.Frame(self, bg=KOYU_GRI)
        ozet.pack(fill="x", side="bottom", padx=12, pady=8)
        self.adet_lbl = tk.Label(
            ozet,
            text="Fatura Adedi: 0",
            bg=KOYU_GRI,
            fg=SARI,
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        )
        self.adet_lbl.pack(side="left", padx=(0, 24))
        self.toplam_lbl = tk.Label(
            ozet,
            text="Toplam Satış Tutarı: 0,00 TL",
            bg=KOYU_GRI,
            fg=SARI,
            font=("Segoe UI", 12, "bold"),
            anchor="w",
        )
        self.toplam_lbl.pack(side="left")
        self.ozet_lbl = tk.Label(
            ozet,
            text="",
            bg=KOYU_GRI,
            fg="#B0BEC5",
            font=("Segoe UI", 9),
            anchor="e",
        )
        self.ozet_lbl.pack(side="right")

        ust = tk.Frame(self, bg=KOYU_GRI)
        ust.pack(fill="x", padx=12, pady=10)
        tk.Label(
            ust,
            text="GÜN SONU — FATURA LİSTESİ",
            bg=KOYU_GRI,
            fg=SARI,
            font=("Segoe UI", 14, "bold"),
        ).pack(side="left")
        tk.Label(
            ust,
            text="Günü kapatmaz · Bekleyen sepetler görünmez · Tek tıkla faturayı düzenle",
            bg=KOYU_GRI,
            fg="#B0BEC5",
            font=("Segoe UI", 9),
        ).pack(side="left", padx=16)

        filtre = tk.Frame(self, bg=KOYU_GRI)
        filtre.pack(fill="x", padx=12, pady=8)
        tk.Label(filtre, text="Tarih", bg=KOYU_GRI, fg=BEYAZ, font=("Segoe UI", 10)).pack(
            side="left"
        )
        tarih_fr = tk.Frame(filtre, bg=KOYU_GRI)
        tarih_fr.pack(side="left", padx=8)
        self.tarih_entry = ttk.Entry(tarih_fr, width=12)
        self.tarih_entry.pack(side="left")
        self.tarih_entry.insert(0, _tarih_metin(self.tarih))
        takvim_butonu(tarih_fr, self.tarih_entry, on_select=lambda _d: self._tarih_uygula())
        self.tarih_entry.bind("<Return>", lambda _e: self._tarih_uygula())
        tk.Button(
            filtre,
            text="Bugün",
            command=self._bugun,
            bg="#455A64",
            fg=BEYAZ,
            relief="flat",
            padx=10,
            pady=4,
        ).pack(side="left", padx=4)
        tk.Button(
            filtre,
            text="Yenile",
            command=self._yenile,
            bg=TURUNCU,
            fg=BEYAZ,
            relief="flat",
            padx=12,
            pady=4,
        ).pack(side="left", padx=4)

        govde = tk.Frame(self, bg=ACIK_GRI)
        govde.pack(fill="both", expand=True, padx=8, pady=4)

        kolonlar = (
            "fatura_no",
            "tarih_saat",
            "musteri",
            "kullanici",
            "odeme",
            "toplam",
            "durum",
        )
        self.tablo = ttk.Treeview(
            govde,
            columns=kolonlar,
            show="headings",
            selectmode="browse",
            height=18,
        )
        basliklar = {
            "fatura_no": "Fatura No",
            "tarih_saat": "Tarih / Saat",
            "musteri": "Müşteri",
            "kullanici": "İşlemi Yapan",
            "odeme": "Ödeme / Açık Hesap",
            "toplam": "Genel Toplam",
            "durum": "Durum",
        }
        genislik = {
            "fatura_no": 110,
            "tarih_saat": 130,
            "musteri": 200,
            "kullanici": 130,
            "odeme": 220,
            "toplam": 110,
            "durum": 90,
        }
        for k in kolonlar:
            self.tablo.heading(k, text=basliklar[k])
            self.tablo.column(k, width=genislik[k], anchor="w" if k != "toplam" else "e")
        sy = ttk.Scrollbar(govde, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=sy.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        sy.pack(side="right", fill="y")
        self.tablo.tag_configure("iptal", foreground=KIRMIZI)
        self.tablo.tag_configure("aktif", foreground=KOYU_GRI)
        # Tek tık / Enter: mevcut faturayı kimliğiyle aç (yeni belge oluşturmaz)
        self.tablo.bind("<ButtonRelease-1>", self._satir_tik)
        self.tablo.bind("<Return>", self._satir_tik)

        self._bos_lbl = tk.Label(
            govde,
            text="Seçilen tarihte kayıtlı hızlı satış bulunamadı",
            bg=ACIK_GRI,
            fg="#607D8B",
            font=("Segoe UI", 11),
        )
        # Başlangıçta gizli; _yenile boşsa place eder
        self._ozet_sifirla()

    def _ozet_sifirla(self) -> None:
        self.adet_lbl.configure(text="Fatura Adedi: 0")
        self.toplam_lbl.configure(text="Toplam Satış Tutarı: 0,00 TL")
        self.ozet_lbl.configure(text="")

    def _bos_goster(self, goster: bool, metin: str | None = None) -> None:
        lbl = self._bos_lbl
        if lbl is None:
            return
        if goster:
            if metin:
                lbl.configure(text=metin)
            try:
                lbl.place(relx=0.5, rely=0.45, anchor="center")
                lbl.lift()
            except tk.TclError:
                pass
        else:
            try:
                lbl.place_forget()
            except tk.TclError:
                pass

    def _bugun(self) -> None:
        self.tarih = date.today()
        self.tarih_entry.delete(0, "end")
        self.tarih_entry.insert(0, _tarih_metin(self.tarih))
        self._yenile()

    def _tarih_uygula(self) -> None:
        try:
            self.tarih = _tarih_oku(self.tarih_entry.get())
        except ValueError as exc:
            messagebox.showerror("Tarih", str(exc), parent=self)
            return
        self._yenile()

    def _yenile(self) -> None:
        try:
            self.tarih = _tarih_oku(self.tarih_entry.get())
        except ValueError:
            self.tarih_entry.delete(0, "end")
            self.tarih_entry.insert(0, _tarih_metin(self.tarih))

        for i in self.tablo.get_children():
            self.tablo.delete(i)
        self._satirlar = []

        try:
            paket = HizliSatisService.gun_sonu_faturalari(self.tarih)
        except Exception as hata:  # noqa: BLE001
            _LOG.exception("Gün Sonu veri yükleme hatası tarih=%s", self.tarih)
            self._ozet_sifirla()
            self._bos_goster(
                True,
                "Veriler yüklenemedi. Kayıt yok anlamına gelmez — ayrıntı hata günlüğünde.",
            )
            messagebox.showerror(
                "Gün Sonu",
                "Gün Sonu listesi yüklenirken hata oluştu.\n\n" + str(hata),
                parent=self,
            )
            return

        self._satirlar = list(paket.get("faturalar") or [])
        for s in self._satirlar:
            tarih_saat = f"{_tarih_metin(s.get('fatura_tarihi'))} {s.get('islem_saati') or ''}".strip()
            durum = s.get("durum") or ""
            if s.get("iptal"):
                durum = "İPTAL"
            tag = "iptal" if s.get("iptal") else "aktif"
            self.tablo.insert(
                "",
                "end",
                iid=str(s["fatura_id"]),
                values=(
                    s.get("fatura_no") or "",
                    tarih_saat,
                    s.get("musteri") or "",
                    s.get("kullanici") or "",
                    s.get("odeme") or "",
                    _para(s.get("genel_toplam")),
                    durum,
                ),
                tags=(tag,),
            )

        gecerli = int(paket.get("gecerli_adet") or 0)
        toplam = paket.get("gecerli_toplam") or Decimal("0")
        iptal_n = int(paket.get("iptal_adedi") or 0)
        iptal_t = paket.get("iptal_toplami") or Decimal("0")
        self.adet_lbl.configure(text=f"Fatura Adedi: {gecerli}")
        self.toplam_lbl.configure(text=f"Toplam Satış Tutarı: {_para(toplam)}")
        self.ozet_lbl.configure(
            text=(
                f"{_tarih_metin(self.tarih)}"
                + (f"  ·  İptal (dahil değil): {iptal_n} / {_para(iptal_t)}" if iptal_n else "")
            )
        )
        if not self._satirlar:
            self._bos_goster(True, "Seçilen tarihte kayıtlı hızlı satış bulunamadı")
        else:
            self._bos_goster(False)

    def _secili_id(self) -> int | None:
        sec = self.tablo.selection()
        if not sec:
            return None
        try:
            return int(sec[0])
        except (TypeError, ValueError):
            return None

    def _satir_tik(self, _event=None) -> None:
        if self._fatura_aciliyor:
            return
        fid = self._secili_id()
        if fid is not None:
            self.after(10, lambda: self._fatura_ac(fid))

    def _seciliyi_ac(self) -> None:
        fid = self._secili_id()
        if fid is None:
            messagebox.showinfo("Gün sonu", "Listeden bir fatura seçin.", parent=self)
            return
        self._fatura_ac(fid)

    def _fatura_ac(self, fatura_id: int) -> None:
        if self._fatura_aciliyor:
            return
        self._fatura_aciliyor = True
        try:
            from database.satis_faturasi_service import SatisFaturasiService

            fatura = SatisFaturasiService.getir(int(fatura_id))
            if fatura is None:
                messagebox.showerror("Gün sonu", "Fatura bulunamadı.", parent=self)
                return

            try:
                self.grab_release()
            except tk.TclError:
                pass
            self.withdraw()

            hs = self.hs_parent
            try:
                from app import CariDialog, SatisFaturasiDialog

                def _cari_ac(cari):
                    return CariDialog(hs, cari)

                dlg = SatisFaturasiDialog(hs, fatura=fatura, cari_ac=_cari_ac)
                hs.wait_window(dlg)
            except Exception as hata:  # noqa: BLE001
                _LOG.exception("Gün Sonu fatura açma")
                messagebox.showerror("Fatura", str(hata), parent=hs)
            finally:
                try:
                    if hs.winfo_exists():
                        hs.deiconify()
                        hs.lift()
                        hs.focus_force()
                except tk.TclError:
                    pass
                try:
                    if self.winfo_exists():
                        self.deiconify()
                        self.lift()
                        self.grab_set()
                        self._yenile()
                        self.focus_force()
                except tk.TclError:
                    pass
        finally:
            self._fatura_aciliyor = False
