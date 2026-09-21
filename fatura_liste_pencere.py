"""Fatura ekranından modeless fatura listesi (bağlama duyarlı).

document_type:
  SALES_INVOICE     → yalnız satış faturaları
  PURCHASE_INVOICE  → yalnız alış faturaları
"""

from __future__ import annotations

import json
import os
import tkinter as tk
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tkinter import messagebox, ttk

SAYFA_BOYUTU = 100
DOC_SATIS = "SALES_INVOICE"
DOC_ALIS = "PURCHASE_INVOICE"


def _para(tutar) -> str:
    try:
        d = Decimal(str(tutar or 0))
    except Exception:
        d = Decimal("0")
    return f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih_goster(d) -> str:
    if d is None:
        return ""
    if hasattr(d, "strftime"):
        return d.strftime("%d.%m.%Y")
    return str(d)


def _prefs_yol(document_type: str) -> Path:
    base = (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        / "MuhasebeProgrami"
        / "ayarlar"
    )
    base.mkdir(parents=True, exist_ok=True)
    kod = "satis" if document_type == DOC_SATIS else "alis"
    return base / f"fatura_liste_pencere_{kod}.json"


def _prefs_yukle(document_type: str) -> dict:
    yol = _prefs_yol(document_type)
    if not yol.exists():
        return {}
    try:
        return json.loads(yol.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _prefs_kaydet(document_type: str, data: dict) -> None:
    try:
        _prefs_yol(document_type).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def fatura_listesi_ac(kart, *, document_type: str) -> None:
    """Açık fatura kartından modeless liste aç / öne getir."""
    if document_type not in (DOC_SATIS, DOC_ALIS):
        raise ValueError(f"Geçersiz belge türü: {document_type}")

    # Yetki
    try:
        from database.session_manager import oturum

        if document_type == DOC_SATIS:
            if not (
                oturum.has_permission("satis_goruntuleme")
                or oturum.has_permission("satis_duzenleme")
                or oturum.has_permission("goruntuleme")
                or (oturum.role_kod or "").upper() == "YONETICI"
            ):
                messagebox.showwarning("Yetki", "Satış faturalarını görüntüleme yetkiniz yok.", parent=kart)
                return
        else:
            if not (
                oturum.has_permission("alis_fatura_goruntuleme")
                or oturum.has_permission("alis_goruntuleme")
                or oturum.has_permission("goruntuleme")
                or (oturum.role_kod or "").upper() == "YONETICI"
            ):
                messagebox.showwarning("Yetki", "Alış faturalarını görüntüleme yetkiniz yok.", parent=kart)
                return
    except Exception:
        pass

    mevcut = getattr(kart, "_bagli_fatura_liste_pencere", None)
    if mevcut is not None:
        try:
            if mevcut.winfo_exists():
                mevcut.deiconify()
                mevcut.lift()
                mevcut.focus_force()
                mevcut.yenile()
                return
        except tk.TclError:
            pass

    win = FaturaListePencere(kart, document_type=document_type)
    kart._bagli_fatura_liste_pencere = win

    def _kart_kapaninca(_e=None):
        try:
            if win.winfo_exists():
                win.destroy()
        except tk.TclError:
            pass

    try:
        kart.bind("<Destroy>", _kart_kapaninca, add="+")
    except tk.TclError:
        pass


class FaturaListePencere(tk.Toplevel):
    def __init__(self, kart, *, document_type: str):
        super().__init__(kart)
        self.kart = kart
        self.document_type = document_type
        self._ham: list[dict] = []
        self._filtreli: list[dict] = []
        self._sayfa = 0
        self._ara_after = None
        self._siralama = ("fatura_tarihi", True)  # kolon, reverse

        satis = document_type == DOC_SATIS
        self.title("Satış Fatura Listesi" if satis else "Alış Fatura Listesi")
        self.geometry("980x560")
        self.minsize(720, 400)
        self.transient(kart)  # sahip; grab yok → modeless

        prefs = _prefs_yukle(document_type)
        if prefs.get("geometry"):
            try:
                self.geometry(prefs["geometry"])
            except tk.TclError:
                pass

        ust = ttk.Frame(self, padding=8)
        ust.pack(fill="x")
        ttk.Label(ust, text="Fatura Tarihi:").pack(side="left")
        self.tarih_bas = ttk.Entry(ust, width=10)
        self.tarih_bas.pack(side="left", padx=2)
        ttk.Label(ust, text="–").pack(side="left")
        self.tarih_bit = ttk.Entry(ust, width=10)
        self.tarih_bit.pack(side="left", padx=2)
        bugun = date.today()
        self.tarih_bas.insert(0, (bugun - timedelta(days=30)).strftime("%d.%m.%Y"))
        self.tarih_bit.insert(0, bugun.strftime("%d.%m.%Y"))

        ttk.Label(ust, text="Fatura No:").pack(side="left", padx=(10, 2))
        self.no_ara = ttk.Entry(ust, width=12)
        self.no_ara.pack(side="left")
        cari_etiket = "Müşteri:" if satis else "Tedarikçi:"
        ttk.Label(ust, text=cari_etiket).pack(side="left", padx=(10, 2))
        self.cari_ara = ttk.Entry(ust, width=18)
        self.cari_ara.pack(side="left")
        ttk.Label(ust, text="Durum:").pack(side="left", padx=(10, 2))
        self.durum = ttk.Combobox(
            ust, values=("", "TASLAK", "AÇIK", "KAPALI", "İPTAL"), width=10, state="readonly"
        )
        self.durum.set("")
        self.durum.pack(side="left")

        ttk.Label(ust, text="Tutar:").pack(side="left", padx=(10, 2))
        self.tutar_min = ttk.Entry(ust, width=8)
        self.tutar_min.pack(side="left")
        ttk.Label(ust, text="–").pack(side="left")
        self.tutar_max = ttk.Entry(ust, width=8)
        self.tutar_max.pack(side="left")

        personel_etiket = "Satış Personeli:" if satis else "Kullanıcı:"
        ttk.Label(ust, text=personel_etiket).pack(side="left", padx=(10, 2))
        self.personel_ara = ttk.Entry(ust, width=14)
        self.personel_ara.pack(side="left")

        ttk.Button(ust, text="Yenile", command=self.yenile).pack(side="left", padx=(10, 2))
        ttk.Button(ust, text="Filtreleri Temizle", command=self._filtre_temizle).pack(side="left", padx=2)

        self.no_ara.bind("<KeyRelease>", self._gecikmeli_filtre)
        self.cari_ara.bind("<KeyRelease>", self._gecikmeli_filtre)
        self.personel_ara.bind("<KeyRelease>", self._gecikmeli_filtre)
        self.tutar_min.bind("<KeyRelease>", self._gecikmeli_filtre)
        self.tutar_max.bind("<KeyRelease>", self._gecikmeli_filtre)
        self.durum.bind("<<ComboboxSelected>>", lambda _e: self._filtre_uygula())

        orta = ttk.Frame(self, padding=(8, 0))
        orta.pack(fill="both", expand=True)
        cari_baslik = "Müşteri" if satis else "Tedarikçi"
        self.kolonlar = (
            "no",
            "tarih",
            "cari_kod",
            "cari_ad",
            "vergi",
            "durum",
            "matrah",
            "kdv",
            "toplam",
            "pb",
            "personel",
            "olusturma",
        )
        basliklar = (
            "Fatura No",
            "Tarih",
            "Cari Kod",
            cari_baslik,
            "Vergi No",
            "Durum",
            "KDV Hariç",
            "KDV",
            "Genel Toplam",
            "Döviz",
            "Satış Personeli" if satis else "Kullanıcı",
            "Oluşturma",
        )
        self.tablo = ttk.Treeview(orta, columns=self.kolonlar, show="headings", selectmode="browse")
        for k, b in zip(self.kolonlar, basliklar):
            self.tablo.heading(k, text=b, command=lambda c=k: self._sirala(c))
            self.tablo.column(k, width=90 if k != "cari_ad" else 180, anchor="center")
        dikey = ttk.Scrollbar(orta, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=dikey.set)
        self.tablo.pack(side="left", fill="both", expand=True)
        dikey.pack(side="right", fill="y")
        self.tablo.bind("<Double-1>", lambda _e: self.seciliyi_ac())

        alt = ttk.Frame(self, padding=8)
        alt.pack(fill="x")
        self.ozet = ttk.Label(alt, text="")
        self.ozet.pack(side="left")
        ttk.Button(alt, text="◀", width=3, command=self._onceki).pack(side="left", padx=(12, 2))
        ttk.Button(alt, text="▶", width=3, command=self._sonraki).pack(side="left")
        ttk.Button(alt, text="Seçili Faturayı Aç", command=self.seciliyi_ac).pack(side="right", padx=4)
        ttk.Button(alt, text="Kapat", command=self.destroy).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._kapat)
        self.bind("<Escape>", lambda _e: self._kapat())
        self.yenile()

    def _kapat(self):
        try:
            geo = self.geometry()
            _prefs_kaydet(self.document_type, {"geometry": geo})
        except Exception:
            pass
        if getattr(self.kart, "_bagli_fatura_liste_pencere", None) is self:
            self.kart._bagli_fatura_liste_pencere = None
        self.destroy()

    def _parse_tarih(self, entry) -> date | None:
        ham = (entry.get() or "").strip()
        if not ham:
            return None
        try:
            return date(int(ham[6:10]), int(ham[3:5]), int(ham[0:2]))
        except Exception:
            return None

    def yenile(self):
        bas = self._parse_tarih(self.tarih_bas)
        bit = self._parse_tarih(self.tarih_bit)
        if bas is None and bit is None:
            bit = date.today()
            bas = bit - timedelta(days=30)
        try:
            if self.document_type == DOC_SATIS:
                from database.satis_faturasi_service import SatisFaturasiService

                self._ham = list(SatisFaturasiService.listele_ozet(tarih_bas=bas, tarih_bit=bit))
                for r in self._ham:
                    r["document_type"] = DOC_SATIS
            else:
                from database.alis_faturasi_service import AlisFaturasiService

                self._ham = list(AlisFaturasiService.listele_ozet(tarih_bas=bas, tarih_bit=bit))
                for r in self._ham:
                    r["document_type"] = DOC_ALIS
        except Exception as hata:
            messagebox.showerror("Liste", str(hata), parent=self)
            self._ham = []
        self._sayfa = 0
        self._filtre_uygula()

    def _filtre_temizle(self):
        self.no_ara.delete(0, "end")
        self.cari_ara.delete(0, "end")
        self.personel_ara.delete(0, "end")
        self.tutar_min.delete(0, "end")
        self.tutar_max.delete(0, "end")
        self.durum.set("")
        bugun = date.today()
        self.tarih_bas.delete(0, "end")
        self.tarih_bas.insert(0, (bugun - timedelta(days=30)).strftime("%d.%m.%Y"))
        self.tarih_bit.delete(0, "end")
        self.tarih_bit.insert(0, bugun.strftime("%d.%m.%Y"))
        self.yenile()

    def _gecikmeli_filtre(self, _e=None):
        if self._ara_after:
            try:
                self.after_cancel(self._ara_after)
            except Exception:
                pass
        self._ara_after = self.after(350, self._filtre_uygula)

    def _tutar_oku(self, entry) -> Decimal | None:
        ham = (entry.get() or "").strip().replace(".", "").replace(",", ".")
        if not ham:
            return None
        try:
            return Decimal(ham)
        except Exception:
            return None

    def _filtre_uygula(self):
        no_q = (self.no_ara.get() or "").strip().lower()
        cari_q = (self.cari_ara.get() or "").strip().lower()
        durum_q = (self.durum.get() or "").strip().upper()
        personel_q = (self.personel_ara.get() or "").strip().lower()
        tmin = self._tutar_oku(self.tutar_min)
        tmax = self._tutar_oku(self.tutar_max)
        sonuc = []
        for r in self._ham:
            # Tür güvenliği
            if r.get("document_type") != self.document_type:
                continue
            if no_q and no_q not in (r.get("fatura_no") or "").lower():
                continue
            if cari_q:
                blob = f"{r.get('cari_kodu') or ''} {r.get('cari_ad') or r.get('musteri') or ''}".lower()
                if cari_q not in blob:
                    continue
            if durum_q and (r.get("durum") or "").upper() != durum_q:
                continue
            if personel_q:
                pblob = (
                    f"{r.get('sales_person_full_name') or ''} "
                    f"{r.get('created_by_full_name') or ''}"
                ).lower()
                if personel_q not in pblob:
                    continue
            try:
                genel = Decimal(str(r.get("genel_toplam") or 0))
            except Exception:
                genel = Decimal("0")
            if tmin is not None and genel < tmin:
                continue
            if tmax is not None and genel > tmax:
                continue
            sonuc.append(r)
        kolon, reverse = self._siralama
        def _anahtar(row):
            v = row.get(kolon)
            if kolon == "fatura_tarihi" and v is None:
                return date.min
            if kolon in ("matrah", "kdv", "genel_toplam", "toplam"):
                try:
                    return Decimal(str(row.get("genel_toplam") if kolon == "toplam" else row.get(kolon) or 0))
                except Exception:
                    return Decimal("0")
            return str(v or "").lower()

        # Varsayılan: tarih ↓ sonra no ↓
        if kolon == "fatura_tarihi":
            sonuc.sort(
                key=lambda r: (
                    r.get("fatura_tarihi") or date.min,
                    r.get("fatura_no") or "",
                ),
                reverse=reverse,
            )
        else:
            sonuc.sort(key=_anahtar, reverse=reverse)
        self._filtreli = sonuc
        self._sayfa = min(self._sayfa, max(0, (len(sonuc) - 1) // SAYFA_BOYUTU))
        self._tabloyu_doldur()

    def _sirala(self, kolon: str):
        map_kolon = {
            "no": "fatura_no",
            "tarih": "fatura_tarihi",
            "cari_kod": "cari_kodu",
            "cari_ad": "cari_ad",
            "vergi": "vergi_no",
            "durum": "durum",
            "matrah": "matrah",
            "kdv": "kdv",
            "toplam": "genel_toplam",
            "pb": "para_birimi",
            "personel": "sales_person_full_name",
            "olusturma": "olusturma_tarihi",
        }
        gercek = map_kolon.get(kolon, kolon)
        if self._siralama[0] == gercek:
            self._siralama = (gercek, not self._siralama[1])
        else:
            self._siralama = (gercek, True)
        self._filtre_uygula()

    def _tabloyu_doldur(self):
        for i in self.tablo.get_children():
            self.tablo.delete(i)
        bas = self._sayfa * SAYFA_BOYUTU
        dilim = self._filtreli[bas : bas + SAYFA_BOYUTU]
        for r in dilim:
            personel = r.get("sales_person_full_name") or r.get("created_by_full_name") or ""
            self.tablo.insert(
                "",
                "end",
                iid=str(r["id"]),
                values=(
                    r.get("fatura_no") or "",
                    _tarih_goster(r.get("fatura_tarihi")),
                    r.get("cari_kodu") or "",
                    r.get("cari_ad") or r.get("musteri") or "",
                    r.get("vergi_no") or "",
                    r.get("durum") or "",
                    _para(r.get("matrah")),
                    _para(r.get("kdv")),
                    _para(r.get("genel_toplam")),
                    r.get("para_birimi") or "TRY",
                    personel,
                    _tarih_goster(r.get("olusturma_tarihi")),
                ),
            )
        toplam = len(self._filtreli)
        sayfa_say = max(1, (toplam + SAYFA_BOYUTU - 1) // SAYFA_BOYUTU)
        self.ozet.configure(
            text=f"{toplam} kayıt  |  Sayfa {self._sayfa + 1}/{sayfa_say}  |  {SAYFA_BOYUTU}/sayfa"
        )

    def _onceki(self):
        if self._sayfa > 0:
            self._sayfa -= 1
            self._tabloyu_doldur()

    def _sonraki(self):
        max_s = max(0, (len(self._filtreli) - 1) // SAYFA_BOYUTU)
        if self._sayfa < max_s:
            self._sayfa += 1
            self._tabloyu_doldur()

    def _secili_id(self) -> int | None:
        sec = self.tablo.selection()
        if not sec:
            messagebox.showinfo("Seçim", "Lütfen bir fatura seçin.", parent=self)
            return None
        return int(sec[0])

    def seciliyi_ac(self):
        fatura_id = self._secili_id()
        if fatura_id is None:
            return
        # Tür doğrulama (ham listeden)
        kayit = next((r for r in self._filtreli if r.get("id") == fatura_id), None)
        if not kayit or kayit.get("document_type") != self.document_type:
            messagebox.showerror(
                "Tür uyuşmazlığı",
                "Seçilen belge bu fatura ekranının türüne ait değil.",
                parent=self,
            )
            return
        ac = getattr(self.kart, "bagli_listeden_fatura_ac", None)
        if not callable(ac):
            messagebox.showerror("Açma", "Fatura ekranı liste açmayı desteklemiyor.", parent=self)
            return
        try:
            ac(fatura_id, document_type=self.document_type)
            self.yenile()
        except Exception as hata:
            messagebox.showerror("Açma", str(hata), parent=self)
