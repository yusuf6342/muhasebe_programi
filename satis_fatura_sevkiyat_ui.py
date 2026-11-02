"""Satış faturası — Sevkiyat ve Teslimat Bilgileri (çoklu kaynak kopyası).

Ana fatura formuna uzun alanlar yayılmaz; bu pencerede listelenir / düzenlenir.
«Uygula» yalnızca bellek sözlüğünü döndürür; kalıcı yazım fatura kaydıyla yapılır.
"""

from __future__ import annotations

import copy
import tkinter as tk
from datetime import date, datetime
from tkinter import messagebox, ttk
from typing import Any

from fatura_tema import ACIK_BG, BEYAZ, IKINCIL, LACIVERT, SARI, font, tk_buton

SEVKIYAT_ALAN_ETIKETLERI: tuple[tuple[str, str], ...] = (
    ("irsaliye_no", "İrsaliye No"),
    ("irsaliye_tarihi", "İrsaliye Tarihi"),
    ("sevk_adresi", "Teslimat Adresi"),
    ("sevk_il", "İl"),
    ("sevk_ilce", "İlçe"),
    ("planlanan_teslim", "Planlanan Teslim"),
    ("teslim_kisi", "Teslim Alacak Kişi"),
    ("teslim_telefon", "Telefon"),
    ("sevkiyat_yontemi", "Sevkiyat Yöntemi"),
    ("nakliyeci", "Nakliyeci"),
    ("arac_plaka", "Plaka"),
    ("sofor_adi", "Şoför"),
    ("sofor_telefon", "Şoför Telefonu"),
    ("takip_no", "Takip No"),
    ("fiili_sevk_tarihi", "Fiili Sevk Tarihi"),
    ("sevk_notu", "Sevk Notu"),
)

_TARIH_ALANLAR = frozenset({"irsaliye_tarihi", "planlanan_teslim", "fiili_sevk_tarihi"})


def _tarih_goster(deger) -> str:
    if deger is None or deger == "":
        return ""
    if isinstance(deger, (date, datetime)):
        return deger.strftime("%d.%m.%Y")
    return str(deger)


def _tarih_coz(metin: str, alan: str):
    metin = (metin or "").strip()
    if not metin:
        return None
    for bicim in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(metin, bicim).date()
        except ValueError:
            continue
    raise ValueError(f"{alan} geçersiz: «{metin}». GG.AA.YYYY yazın.")


def _blok_ozet(blok: dict) -> str:
    no = (blok.get("irsaliye_no") or "").strip() or "Manuel"
    adres = (blok.get("sevk_adresi") or "").strip()
    il = (blok.get("sevk_il") or "").strip()
    parca = [no]
    if adres:
        parca.append(adres[:40] + ("…" if len(adres) > 40 else ""))
    elif il:
        parca.append(il)
    nak = (blok.get("nakliyeci") or "").strip()
    if nak:
        parca.append(nak)
    return " · ".join(parca)


class SatisFaturaSevkiyatDialog(tk.Toplevel):
    """Üstte bağlı sevkiyat listesi, altta seçilen kaydın alanları."""

    def __init__(
        self,
        parent,
        bloklar: list[dict] | None = None,
        *,
        salt_okunur: bool = False,
        yenile_kaynak=None,
    ):
        super().__init__(parent)
        self.result: list[dict] | None = None
        self._salt = bool(salt_okunur)
        self._yenile_kaynak = yenile_kaynak
        self._bloklar: list[dict] = [copy.deepcopy(b) for b in (bloklar or [])]
        self._secili = 0 if self._bloklar else -1
        self._yukleniyor = False

        n = len(self._bloklar)
        baslik = "Sevkiyat ve Teslimat Bilgileri"
        if n > 1:
            baslik = f"{baslik} — {n} Sevkiyat"
        self.title(baslik)
        self.transient(parent)
        try:
            self.configure(bg=ACIK_BG)
        except tk.TclError:
            pass
        self.grab_set()
        from ui_pencere import pencere_os_krom_ac

        pencere_os_krom_ac(self)

        ust = tk.Frame(self, bg=LACIVERT)
        ust.pack(fill="x")
        tk.Label(
            ust,
            text=baslik,
            bg=LACIVERT,
            fg=SARI,
            font=font(12, "bold", self),
            anchor="w",
            padx=12,
            pady=8,
        ).pack(fill="x")

        govde = tk.Frame(self, bg=ACIK_BG, padx=10, pady=8)
        govde.pack(fill="both", expand=True)

        liste_cerceve = tk.LabelFrame(
            govde, text="Bağlı sevkiyatlar", bg=BEYAZ, fg=LACIVERT, font=font(10, "bold", self), padx=6, pady=4,
        )
        liste_cerceve.pack(fill="x", pady=(0, 8))
        self._liste = tk.Listbox(
            liste_cerceve, height=4, font=font(10, root=self), activestyle="dotbox", exportselection=False,
        )
        self._liste.pack(side="left", fill="x", expand=True)
        sb = ttk.Scrollbar(liste_cerceve, orient="vertical", command=self._liste.yview)
        sb.pack(side="right", fill="y")
        self._liste.configure(yscrollcommand=sb.set)
        self._liste.bind("<<ListboxSelect>>", self._liste_secildi)

        btn_satir = tk.Frame(govde, bg=ACIK_BG)
        btn_satir.pack(fill="x", pady=(0, 6))
        if not self._salt:
            tk_buton(btn_satir, "Yeni (manuel)", self._yeni_manuel, rol="yeni").pack(side="left", padx=2)
            tk_buton(btn_satir, "Seçileni Sil", self._sil, rol="tehlike").pack(side="left", padx=2)
            if self._yenile_kaynak is not None:
                tk_buton(
                    btn_satir, "İrsaliyeden Bilgileri Yenile", self._yenile, rol="ikincil"
                ).pack(side="left", padx=8)

        detay = tk.LabelFrame(
            govde, text="Sevkiyat ayrıntıları", bg=BEYAZ, fg=LACIVERT, font=font(10, "bold", self), padx=8, pady=6,
        )
        detay.pack(fill="both", expand=True)
        detay.columnconfigure(1, weight=1)
        self.alanlar: dict[str, ttk.Entry] = {}
        for sira, (alan, etiket) in enumerate(SEVKIYAT_ALAN_ETIKETLERI):
            tk.Label(detay, text=etiket, bg=BEYAZ, fg=IKINCIL, font=font(9, root=self)).grid(
                row=sira, column=0, sticky="w", pady=2, padx=(0, 8)
            )
            w = ttk.Entry(detay, width=48)
            w.grid(row=sira, column=1, sticky="ew", pady=2)
            if self._salt or alan in ("irsaliye_no",):
                # irsaliye_no kaynak kimliği; manuelde düzenlenebilir, kaynaklıda salt
                pass
            self.alanlar[alan] = w
            w.bind("<KeyRelease>", self._alan_degisti)
            w.bind("<FocusOut>", self._alan_degisti)

        alt = tk.Frame(self, bg=ACIK_BG, padx=10, pady=8)
        alt.pack(fill="x")
        tk.Label(
            alt,
            text="Uygula bilgileri fatura taslağına alır; kalıcı kayıt fatura Kaydet ile yapılır.",
            bg=ACIK_BG,
            fg=IKINCIL,
            font=font(8, root=self),
        ).pack(side="left")
        tk_buton(alt, "Vazgeç", self.destroy, rol="ikincil").pack(side="right")
        if not self._salt:
            tk_buton(alt, "Uygula", self._uygula, rol="vurgu").pack(side="right", padx=8)

        self._listeyi_yenile()
        if self._bloklar:
            self._liste.selection_set(0)
            self._formu_yukle(0)
        else:
            self._formu_temizle()

        try:
            from ui_pencere import popup_ortala

            popup_ortala(self, parent, genislik=640, yukseklik=620)
        except Exception:  # noqa: BLE001
            self.geometry("640x620")

    def _listeyi_yenile(self):
        self._liste.delete(0, "end")
        for i, b in enumerate(self._bloklar):
            self._liste.insert("end", f"{i + 1}. {_blok_ozet(b)}")

    def _liste_secildi(self, _e=None):
        sec = self._liste.curselection()
        if not sec:
            return
        self._formu_kaydet_secili()
        self._secili = int(sec[0])
        self._formu_yukle(self._secili)

    def _formu_temizle(self):
        self._yukleniyor = True
        try:
            for w in self.alanlar.values():
                w.configure(state="normal")
                w.delete(0, "end")
                if self._salt:
                    w.configure(state="readonly")
        finally:
            self._yukleniyor = False

    def _formu_yukle(self, idx: int):
        if idx < 0 or idx >= len(self._bloklar):
            self._formu_temizle()
            return
        blok = self._bloklar[idx]
        self._yukleniyor = True
        try:
            kaynakli = blok.get("irsaliye_id") is not None
            for alan, w in self.alanlar.items():
                w.configure(state="normal")
                w.delete(0, "end")
                w.insert(0, _tarih_goster(blok.get(alan)))
                if self._salt or (kaynakli and alan == "irsaliye_no"):
                    w.configure(state="readonly")
        finally:
            self._yukleniyor = False

    def _formu_kaydet_secili(self):
        if self._secili < 0 or self._secili >= len(self._bloklar) or self._salt:
            return
        try:
            veri = self._formdan_oku()
        except ValueError:
            return
        eski = self._bloklar[self._secili]
        eski.update(veri)
        # irsaliye_id korunur
        self._listeyi_yenile()
        self._liste.selection_clear(0, "end")
        self._liste.selection_set(self._secili)

    def _formdan_oku(self) -> dict[str, Any]:
        veri: dict[str, Any] = {}
        for alan, w in self.alanlar.items():
            metin = w.get().strip()
            if alan in _TARIH_ALANLAR:
                veri[alan] = _tarih_coz(metin, dict(SEVKIYAT_ALAN_ETIKETLERI)[alan])
            else:
                veri[alan] = metin or None
        return veri

    def _alan_degisti(self, _e=None):
        if self._yukleniyor or self._salt or self._secili < 0:
            return
        # Canlı özet güncellemesi (hata yut)
        try:
            self._formu_kaydet_secili()
        except Exception:  # noqa: BLE001
            pass

    def _yeni_manuel(self):
        self._formu_kaydet_secili()
        self._bloklar.append(
            {
                "irsaliye_id": None,
                "irsaliye_no": None,
                "irsaliye_tarihi": None,
                "sevk_adresi": None,
                "sevk_il": None,
                "sevk_ilce": None,
                "planlanan_teslim": None,
                "teslim_kisi": None,
                "teslim_telefon": None,
                "sevkiyat_yontemi": None,
                "nakliyeci": None,
                "arac_plaka": None,
                "sofor_adi": None,
                "sofor_telefon": None,
                "takip_no": None,
                "sevk_notu": None,
                "fiili_sevk_tarihi": None,
            }
        )
        self._listeyi_yenile()
        self._secili = len(self._bloklar) - 1
        self._liste.selection_clear(0, "end")
        self._liste.selection_set(self._secili)
        self._formu_yukle(self._secili)

    def _sil(self):
        if self._secili < 0 or self._secili >= len(self._bloklar):
            return
        if not messagebox.askyesno(
            "Sevkiyat", "Seçilen sevkiyat kaydı taslaktan kaldırılsın mı?", parent=self
        ):
            return
        del self._bloklar[self._secili]
        self._secili = min(self._secili, len(self._bloklar) - 1)
        self._listeyi_yenile()
        if self._secili >= 0:
            self._liste.selection_set(self._secili)
            self._formu_yukle(self._secili)
        else:
            self._formu_temizle()

    def _yenile(self):
        if self._yenile_kaynak is None or self._secili < 0:
            return
        self._formu_kaydet_secili()
        blok = self._bloklar[self._secili]
        irs_id = blok.get("irsaliye_id")
        if not irs_id:
            messagebox.showinfo(
                "Yenile", "Manuel sevkiyat kaydının bağlı irsaliyesi yok.", parent=self
            )
            return
        try:
            kaynak = self._yenile_kaynak(int(irs_id))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Yenile", str(exc), parent=self)
            return
        if not kaynak:
            messagebox.showwarning("Yenile", "Kaynak irsaliye bulunamadı.", parent=self)
            return
        from database.satis_faturasi_service import SatisFaturasiService

        yeni = SatisFaturasiService.sevkiyat_irsaliyeden(kaynak)
        farklar = []
        for alan, _etiket in SEVKIYAT_ALAN_ETIKETLERI:
            eski_v = _tarih_goster(blok.get(alan))
            yeni_v = _tarih_goster(yeni.get(alan))
            if eski_v != yeni_v:
                farklar.append(f"• {_etiket}: «{eski_v or '—'}» → «{yeni_v or '—'}»")
        if not farklar:
            messagebox.showinfo("Yenile", "Kaynak ile fatura kopyası aynı.", parent=self)
            return
        if not messagebox.askyesno(
            "İrsaliyeden Bilgileri Yenile",
            "Aşağıdaki alanlar kaynaktan alınacak:\n\n" + "\n".join(farklar[:12])
            + ("\n…" if len(farklar) > 12 else "")
            + "\n\nFaturadaki düzeltmeler üzerine yazılır. Devam?",
            parent=self,
        ):
            return
        blok.update(yeni)
        self._formu_yukle(self._secili)
        self._listeyi_yenile()
        self._liste.selection_set(self._secili)

    def _uygula(self):
        self._formu_kaydet_secili()
        try:
            # Son doğrulama
            if self._secili >= 0:
                self._formdan_oku()
        except ValueError as hata:
            messagebox.showwarning("Sevkiyat", str(hata), parent=self)
            return
        self.result = [copy.deepcopy(b) for b in self._bloklar]
        self.destroy()
