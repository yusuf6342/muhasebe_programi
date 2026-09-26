"""Müşteri / Tedarikçi Cari Hesap Kartı — kurumsal yeniden düzenlenmiş UI.

İş kuralları CariService / mevcut diyalog açıcılarında kalır; bu modül düzen + stil.
"""

from __future__ import annotations

import re
import webbrowser
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
import tkinter as tk

from database.cari_service import CariService
from database.stok_service import ALIŞ_FIYAT_ADLARI, SATIS_FIYAT_ADLARI
from ui_tablo_siralama import (
    dogal_belge_anahtar,
    liste_sirala,
    para_coz,
    siralama_yonu_degistir,
    tarih_coz,
    treeview_basliklari_guncelle,
    turkce_metin_anahtar,
)
from ui_takvim import takvim_butonu

import cari_kart_tema as tema
from cari_kart_tema import (
    ACIK_BG,
    BASARI,
    BEYAZ,
    CIZGI,
    DIKKAT,
    IKINCIL,
    LACIVERT,
    METIN,
    SARI,
    STRIPE,
    ToolTip,
    UYARI,
    beyaz_kart,
    font,
    rozet,
    stil_uygula,
    tk_buton,
)


def para_goster(tutar) -> str:
    return f"{float(tutar):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def tarih_goster(tarih) -> str:
    return tarih.strftime("%d.%m.%Y")


def _izin_var(*kodlar: str) -> bool:
    try:
        from database.session_manager import oturum

        if getattr(oturum, "role_kod", None) == "YONETICI":
            return True
        return any(oturum.has_permission(k) for k in kodlar)
    except Exception:
        return True


class NotlarDialog(tk.Toplevel):
    def __init__(self, parent, cari):
        super().__init__(parent)
        self.parent_kart = parent
        self.cari = cari
        self.orijinal_not = cari.ozel_notlar or ""
        self.kaydedildi = False
        self.title("İstihbarat ve Notlar")
        self.geometry("620x420")
        self.minsize(480, 320)
        self.transient(parent)
        self.grab_set()
        self.configure(bg=ACIK_BG)
        self.protocol("WM_DELETE_WINDOW", self.kapat)

        kart, ic = beyaz_kart(self, padx=12, pady=12)
        kart.pack(fill="both", expand=True, padx=10, pady=10)
        tk.Label(
            ic, text="İstihbarat / Özel Notlar", bg=BEYAZ, fg=LACIVERT, font=font(11, "bold", self)
        ).pack(anchor="w", pady=(0, 6))
        self.not_alani = tk.Text(ic, wrap="word", width=70, height=15, font=font(10, root=self))
        self.not_alani.pack(fill="both", expand=True, pady=(0, 10))
        self.not_alani.insert("1.0", self.orijinal_not)
        butonlar = tk.Frame(ic, bg=BEYAZ)
        butonlar.pack(fill="x")
        tk_buton(butonlar, "Kapat", self.kapat, rol="ikincil").pack(side="right")
        tk_buton(butonlar, "Kaydet", self.kaydet, rol="kaydet").pack(side="right", padx=(0, 8))

    def mevcut_not(self):
        return self.not_alani.get("1.0", "end").strip()

    def kaydet(self):
        try:
            CariService.guncelle(self.cari.id, {"ozel_notlar": self.mevcut_not() or None})
        except ValueError as hata:
            messagebox.showerror("Not kaydedilemedi", str(hata), parent=self)
            return
        self.cari.ozel_notlar = self.mevcut_not()
        self.orijinal_not = self.mevcut_not()
        self.kaydedildi = True
        if hasattr(self.parent_kart, "not_durumunu_guncelle"):
            self.parent_kart.not_durumunu_guncelle()
        messagebox.showinfo("Notlar", "İstihbarat ve özel notlar kaydedildi.", parent=self)

    def kapat(self):
        if self.mevcut_not() != self.orijinal_not:
            if not messagebox.askyesno(
                "Kaydedilmemiş değişiklik",
                "Kaydedilmemiş değişiklikler var. Kapatmak istiyor musunuz?",
                parent=self,
            ):
                return
        self.destroy()


class CariUyariDialog(tk.Toplevel):
    """Satış faturası / tahsilat makbuzunda otomatik gösterilecek uyarı notu."""

    def __init__(self, parent, cari=None, baslangic_metin=""):
        super().__init__(parent)
        self.parent_kart = parent
        self.cari = cari
        self.result = None
        self.orijinal = (getattr(cari, "uyari_notu", None) or baslangic_metin or "").strip()
        self.title("Müşteri Uyarı Notu")
        self.geometry("560x320")
        self.minsize(440, 260)
        self.transient(parent)
        self.grab_set()
        self.configure(bg=ACIK_BG)
        self.protocol("WM_DELETE_WINDOW", self.kapat)

        kart, ic = beyaz_kart(self)
        kart.pack(fill="both", expand=True, padx=10, pady=10)
        tk.Label(
            ic,
            text="Bu not; satış faturası veya tahsilat makbuzu açılırken otomatik gösterilir.",
            wraplength=500,
            bg=BEYAZ,
            fg=IKINCIL,
            font=font(9, root=self),
            justify="left",
        ).pack(anchor="w", pady=(0, 6))
        tk.Label(ic, text="Uyarı notu", bg=BEYAZ, fg=LACIVERT, font=font(11, "bold", self)).pack(
            anchor="w", pady=(0, 4)
        )
        self.not_alani = tk.Text(ic, wrap="word", width=64, height=10, font=font(10, root=self))
        self.not_alani.pack(fill="both", expand=True, pady=(0, 10))
        self.not_alani.insert("1.0", self.orijinal)
        butonlar = tk.Frame(ic, bg=BEYAZ)
        butonlar.pack(fill="x")
        tk_buton(butonlar, "Temizle", self._temizle, rol="ikincil").pack(side="left")
        tk_buton(butonlar, "İptal", self.kapat, rol="ikincil").pack(side="right")
        tk_buton(butonlar, "Kaydet", self.kaydet, rol="kaydet").pack(side="right", padx=(0, 8))

    def mevcut(self):
        return self.not_alani.get("1.0", "end").strip()

    def _temizle(self):
        self.not_alani.delete("1.0", "end")

    def kaydet(self):
        metin = self.mevcut() or None
        if self.cari is not None:
            try:
                CariService.guncelle(self.cari.id, {"uyari_notu": metin})
            except ValueError as hata:
                messagebox.showerror("Uyarı kaydedilemedi", str(hata), parent=self)
                return
            self.cari.uyari_notu = metin
        self.result = metin or ""
        if hasattr(self.parent_kart, "uyari_durumunu_guncelle"):
            self.parent_kart.uyari_durumunu_guncelle(self.result)
        messagebox.showinfo(
            "Uyarı",
            "Uyarı notu kaydedildi." if metin else "Uyarı notu temizlendi.",
            parent=self,
        )
        self.destroy()

    def kapat(self):
        if self.mevcut() != self.orijinal:
            if not messagebox.askyesno(
                "Kaydedilmemiş değişiklik",
                "Kaydedilmemiş değişiklikler var. Kapatmak istiyor musunuz?",
                parent=self,
            ):
                return
        self.destroy()


def cari_uyari_goster(parent, cari_veya_id) -> bool:
    """Cari uyarı notu varsa gösterir. True = uyarı vardı."""
    if cari_veya_id is None:
        return False
    if isinstance(cari_veya_id, int):
        notu = CariService.uyari_notu_oku(cari_veya_id)
        baslik_ek = ""
    else:
        cari = cari_veya_id
        notu = CariService.uyari_notu_oku(getattr(cari, "id", None))
        if not notu:
            notu = (getattr(cari, "uyari_notu", None) or "").strip()
        baslik_ek = f" — {getattr(cari, 'cari_kodu', '')} {getattr(cari, 'unvan', '')}".strip()
    if not notu:
        return False
    messagebox.showwarning(f"Müşteri Uyarısı{baslik_ek}", notu, parent=parent)
    return True


class CariMuhasebeDialog(tk.Toplevel):
    """Cari kartı muhasebe hesap kodları."""

    ALANLAR = (
        ("Borçlu Hesap Kodu", "muhasebe_borclu_kodu"),
        ("Alacaklı Hesap Kodu", "muhasebe_alacakli_kodu"),
        ("Satış Hesap Kodu", "muhasebe_satis_kodu"),
        ("Alış Hesap Kodu", "muhasebe_alis_kodu"),
        ("KDV Satış Hesap Kodu", "muhasebe_kdv_satis_kodu"),
        ("KDV Alış Hesap Kodu", "muhasebe_kdv_alis_kodu"),
    )

    def __init__(self, parent, degerler=None):
        super().__init__(parent)
        self.result = None
        self.title("Muhasebe Hesap Kodları")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.configure(bg=ACIK_BG)
        self.alanlar = {}
        degerler = degerler or {}
        from hesap_kodu_sec_ui import muhasebe_hesap_entry_bagla

        kart, ic = beyaz_kart(self)
        kart.pack(fill="both", expand=True, padx=10, pady=10)
        tk.Label(
            ic,
            text="Hesap koduna 3 hane yazın veya sağ tık / F2 / … ile TDHP planından seçin.",
            foreground=IKINCIL,
            bg=BEYAZ,
            wraplength=420,
            font=font(9, root=self),
            justify="left",
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        for satir, (etiket, alan) in enumerate(self.ALANLAR, start=1):
            tk.Label(ic, text=etiket, bg=BEYAZ, fg=METIN, font=font(10, root=self)).grid(
                row=satir, column=0, padx=(0, 8), pady=5, sticky="w"
            )
            giris = ttk.Entry(ic, width=28)
            giris.grid(row=satir, column=1, padx=(0, 4), pady=5, sticky="w")
            giris.insert(0, degerler.get(alan) or "")
            self.alanlar[alan] = giris
            muhasebe_hesap_entry_bagla(self, giris)
            tk_buton(
                ic, "…", lambda g=giris: self._hesap_sec(g), rol="ikincil"
            ).grid(row=satir, column=2, padx=(0, 0), pady=5)
        butonlar = tk.Frame(ic, bg=BEYAZ)
        butonlar.grid(row=len(self.ALANLAR) + 1, column=0, columnspan=3, sticky="e", pady=(10, 0))
        tk_buton(butonlar, "İptal", self.destroy, rol="ikincil").pack(side="right", padx=(8, 0))
        tk_buton(butonlar, "Tamam", self.tamam, rol="kaydet").pack(side="right")

    def _hesap_sec(self, giris):
        from hesap_kodu_sec_ui import HesapKoduSecDialog

        dlg = HesapKoduSecDialog(self, onek=(giris.get() or "").strip())
        self.wait_window(dlg)
        if dlg.result:
            giris.delete(0, "end")
            giris.insert(0, dlg.result)

    def tamam(self):
        self.result = {alan: giris.get().strip() for alan, giris in self.alanlar.items()}
        self.destroy()


class CariDialog(tk.Toplevel):
    SAYISAL_TUTAR_ALANLARI = (
        "acik_hesap_risk_limiti",
        "cek_risk_limiti",
        "senet_risk_limiti",
    )
    SAYISAL_GUN_ALANLARI = ("satis_vade_gunu", "alis_vade_gunu")
    MUHASEBE_ALANLARI = tuple(alan for _etiket, alan in CariMuhasebeDialog.ALANLAR)

    def __init__(self, parent: tk.Misc, cari=None, cari_turu: str = "Müşteri"):
        super().__init__(parent)
        self.cari = cari
        self.result = None
        self.cari_turu = (cari.cari_turu if cari else cari_turu) or "Müşteri"
        self.tedarikci_modu = self.cari_turu == "Tedarikçi"
        self.etiket = "Tedarikçi" if self.tedarikci_modu else "Müşteri"
        self.title(f"{self.etiket} Cari Hesap Kartı")
        self.geometry("1280x780")
        self.minsize(1040, 620)
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        # transient sonra kaldırılır — Windows büyüt/küçült için
        self.transient(parent)
        self.grab_set()
        self.configure(bg=ACIK_BG)
        stil_uygula(root=self)
        self._cari_onceki_geometry = None

        self.degerler = {}
        self.ozet_kartlari = {}
        self.ozet_degerleri = {}
        self.hareket_tablosu = None
        self._hareket_siralama_kolon: str | None = None
        self._hareket_siralama_azalan: bool = False
        self._hareket_kolon_basliklari: dict[str, str] = {}
        self._hareket_kolon_hizalari: dict[str, str] = {}
        self._kirli = False
        self._snapshot = ""
        self._yukleniyor = False
        self.muhasebe = {
            alan: (getattr(cari, alan, None) or "") if cari else ""
            for alan in self.MUHASEBE_ALANLARI
        }
        self.uyari_notu = (getattr(cari, "uyari_notu", None) or "") if cari else ""

        self.protocol("WM_DELETE_WINDOW", self._kapat_istegi)
        self.bind("<F1>", self._f1_kaydet)
        self.bind_all("<F1>", self._f1_kaydet)
        self.bind("<Escape>", lambda _e: self._kapat_istegi())
        self.bind("<F10>", self._hizli_cari_ara)

        self._ust_baslik_olustur()
        self._hizli_arama_seridi_olustur()
        self._uyari_bandi = tk.Frame(self, bg="#FEF2F2", highlightthickness=1, highlightbackground="#FECACA")
        self._uyari_bandi_lbl = tk.Label(
            self._uyari_bandi,
            text="",
            bg="#FEF2F2",
            fg=UYARI,
            font=font(9, "bold", self),
            wraplength=1100,
            justify="left",
            anchor="w",
        )
        self._uyari_bandi_lbl.pack(fill="x", padx=12, pady=6)
        self._uyari_rozet_satiri = tk.Frame(self, bg=ACIK_BG)
        self._uyari_rozet_satiri.pack(fill="x", padx=12, pady=(6, 4))

        kaydirma = tk.Frame(self, bg=ACIK_BG)
        kaydirma.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.canvas = tk.Canvas(kaydirma, highlightthickness=0, bg=ACIK_BG)
        dikey = ttk.Scrollbar(kaydirma, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=dikey.set)
        dikey.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.icerik = tk.Frame(self.canvas, bg=ACIK_BG, padx=4, pady=4)
        self._pencere = self.canvas.create_window((0, 0), window=self.icerik, anchor="nw")
        self.icerik.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self._pencere, width=e.width),
        )
        self.canvas.bind_all("<MouseWheel>", self._fare_tekerlegi)

        self._ana_kolonlari_olustur()
        self._detay_seridini_olustur(self.icerik)
        self._hizli_islemleri_olustur(self.icerik)
        self._hareket_tablosunu_olustur(self.icerik)

        self._alanlari_doldur()
        self._kirli_izlemeyi_bagla()
        self._snapshot = self._form_snapshot()
        self._kirli = False
        self._baslik_rozetlerini_guncelle()
        self._uyari_bandini_guncelle()
        # Boyutlandırma: transient yarı ekranda büyütmeyi engelleyebilir — OS kontrolleri aç
        self._cari_pencere_boyutlandirma_ac()
        if self.cari:
            self.after(50, self.yenile)
            self.degerler["unvan"].focus_set()
        else:
            self.after(50, lambda: (self._hizli_ara.focus_set(), self._hizli_ara.icursor("end")))

    # ─── Üst chrome ───────────────────────────────────────────────
    def _ust_baslik_olustur(self):
        ust = tk.Frame(self, bg=LACIVERT)
        self._ust_cerceve = ust
        ust.pack(fill="x")
        sol = tk.Frame(ust, bg=LACIVERT)
        sol.pack(side="left", fill="both", expand=True, padx=14, pady=10)
        tk.Label(
            sol,
            text=f"{self.etiket} Cari Hesap Kartı",
            bg=LACIVERT,
            fg=BEYAZ,
            font=font(16, "bold", self),
            anchor="w",
        ).pack(anchor="w")
        self._baslik_alt = tk.Label(
            sol, text="", bg=LACIVERT, fg=SARI, font=font(10, root=self), anchor="w"
        )
        self._baslik_alt.pack(anchor="w", pady=(2, 0))
        rozet_satir = tk.Frame(sol, bg=LACIVERT)
        rozet_satir.pack(anchor="w", pady=(6, 0))
        self._rozet_aktif = rozet(rozet_satir, "—", bg=IKINCIL)
        self._rozet_aktif.pack(side="left", padx=(0, 6))
        self._rozet_grup = rozet(rozet_satir, "Grup: —", bg=tema.LACIVERT_ORTA)
        self._rozet_grup.pack(side="left")

        sag = tk.Frame(ust, bg=LACIVERT)
        sag.pack(side="right", padx=10, pady=8)
        btn_satir = tk.Frame(sag, bg=LACIVERT)
        btn_satir.pack(anchor="e")
        self.kaydet_btn = tk_buton(btn_satir, "Kaydet (F1)", self.kaydet, rol="kaydet")
        self.kaydet_btn.pack(side="left", padx=3)
        tk_buton(btn_satir, "Kaydet ve Kapat", self.kaydet_ve_kapat, rol="vurgu").pack(
            side="left", padx=3
        )
        # Boş kartta yeni kayıt akışı: formu doldur → Kaydet (F1)
        tk_buton(btn_satir, "Yeni", self.yeni_kart, rol="vurgu").pack(side="left", padx=3)
        if self.cari:
            self._pasif_btn = tk_buton(
                btn_satir,
                "Pasife Al" if self.cari.aktif else "Aktif Et",
                self.durumu_degistir,
                rol="tehlike" if self.cari.aktif else "basari",
            )
            self._pasif_btn.pack(side="left", padx=3)
        # Pencere: aşağı indir / büyüt-geri al (OS başlığı eksik kalabiliyor)
        btn_asagi = tk_buton(btn_satir, "─", self._cari_pencere_asagi, rol="ikincil")
        btn_asagi.pack(side="left", padx=(10, 2))
        ToolTip(btn_asagi, "Aşağı indir (görev çubuğu)")
        self._btn_pencere_buyut = tk_buton(
            btn_satir, "□", self._cari_pencere_buyut_toggle, rol="ikincil"
        )
        self._btn_pencere_buyut.pack(side="left", padx=2)
        ToolTip(self._btn_pencere_buyut, "Büyüt / eski boyuta dön")
        try:
            if str(self.state() or "") == "zoomed":
                self._btn_pencere_buyut.configure(text="❐")
        except tk.TclError:
            pass
        tk_buton(btn_satir, "Kapat", self._kapat_istegi, rol="ikincil").pack(
            side="left", padx=(8, 3)
        )
        self._sari_cizgi = tk.Frame(self, bg=SARI, height=3)
        self._sari_cizgi.pack(fill="x")
        self._ust_son = self._sari_cizgi

    def _baslik_rozetlerini_guncelle(self):
        kod = ""
        unvan = ""
        if "cari_kodu" in self.degerler:
            kod = self._widget_deger("cari_kodu")
        if "unvan" in self.degerler:
            unvan = self._widget_deger("unvan")
        if not kod and self.cari:
            kod = getattr(self.cari, "cari_kodu", "") or ""
        if not unvan and self.cari:
            unvan = getattr(self.cari, "unvan", "") or ""
        if kod or unvan:
            self._baslik_alt.configure(text=f"{kod}  ·  {unvan}")
        elif self.cari:
            self._baslik_alt.configure(text="")
        else:
            self._baslik_alt.configure(
                text="Kayıt seçilmedi — isimle ara (F10) veya yeni kayıt girin"
            )
        aktif = bool(self.degerler.get("aktif").get()) if "aktif" in self.degerler else True
        if aktif:
            self._rozet_aktif.configure(text="Aktif", bg=BASARI, fg=BEYAZ)
        else:
            self._rozet_aktif.configure(text="Pasif", bg=UYARI, fg=BEYAZ)
        grup = ""
        if "musteri_grubu" in self.degerler:
            grup = (self.degerler["musteri_grubu"].get() or "").strip()
        self._rozet_grup.configure(text=f"Grup: {grup}" if grup else "Grup: —")

    def _hizli_arama_seridi_olustur(self):
        """Üst şerit: müşteri/tedarikçi ismiyle hızlı arama → seçilen kartı yükler."""
        serit = tk.Frame(self, bg=ACIK_BG)
        serit.pack(fill="x", padx=12, pady=(8, 0), after=self._sari_cizgi)
        self._arama_serit = serit
        tk.Label(
            serit,
            text=f"{self.etiket} Ara:",
            bg=ACIK_BG,
            fg=LACIVERT,
            font=font(9, "bold", self),
        ).pack(side="left")
        self._hizli_ara = ttk.Entry(serit, width=40)
        self._hizli_ara.pack(side="left", padx=(8, 4), fill="x", expand=True)
        self._hizli_ara.bind("<Return>", self._hizli_cari_ara)
        self._hizli_ara.bind("<F10>", self._hizli_cari_ara)
        tk_buton(serit, "Ara (F10)", self._hizli_cari_ara, rol="ara").pack(
            side="left", padx=(0, 8)
        )
        tk.Label(
            serit,
            text="İsim / kod yazıp Ara — seçilen kayıt bu karta yüklenir",
            bg=ACIK_BG,
            fg=IKINCIL,
            font=font(8, root=self),
        ).pack(side="left")
        self._ust_son = serit  # uyarı bandı bu şeridin altına gelsin

    def _hizli_cari_ara(self, _event=None):
        """Hızlı arama: seçim listesi açar; seçilen cari bu karta yüklenir."""
        ara = ""
        if hasattr(self, "_hizli_ara"):
            ara = (self._hizli_ara.get() or "").strip()
        try:
            from app import MusteriSecimDialog
        except Exception as hata:
            messagebox.showerror(
                "Arama", f"Seçim ekranı açılamadı:\n{hata}", parent=self
            )
            return "break"

        if self.tedarikci_modu:
            try:
                kayitlar = list(CariService.aktif_tedarikciler())
            except Exception:
                kayitlar = []
            kayitlar.sort(
                key=lambda c: ((c.unvan or "").casefold(), (c.cari_kodu or "").casefold())
            )
            varsayilan = kayitlar[:80]
            canli = False
        else:
            try:
                kayitlar = list(CariService.aktif_musteriler())
            except Exception:
                kayitlar = []
            kayitlar.sort(
                key=lambda c: ((c.unvan or "").casefold(), (c.cari_kodu or "").casefold())
            )
            varsayilan = kayitlar[:80]
            canli = True

        bakiyeler: dict = {}
        ids = [c.id for c in varsayilan]
        if ids:
            try:
                bakiyeler = CariService.musteri_bakiyeleri_toplu(ids)
            except Exception:
                bakiyeler = {}

        dlg = MusteriSecimDialog(
            self,
            musteriler=varsayilan,
            bakiyeler=bakiyeler,
            ara=ara,
            baslik=f"{self.etiket} Seçimi",
            kayit_adi=self.etiket.lower(),
            canli_arama=canli,
        )
        self.wait_window(dlg)
        if dlg.result:
            self._cariye_gec(dlg.result)
        return "break"

    def _cariye_gec(self, cari):
        """Seçilen kaydı bu kart penceresine yükler (aynı diyalog yeniden açılır)."""
        if cari is None:
            return
        if self.cari is not None and getattr(self.cari, "id", None) == getattr(cari, "id", None):
            return
        if not self._kapatmadan_once_onay():
            return
        parent = self.master
        tur = (getattr(cari, "cari_turu", None) or self.cari_turu) or "Müşteri"
        self.destroy()
        CariDialog(parent, cari=cari, cari_turu=tur)

    # ─── Ana kolonlar ─────────────────────────────────────────────
    def _ana_kolonlari_olustur(self):
        ust = tk.Frame(self.icerik, bg=ACIK_BG)
        ust.pack(fill="x", pady=(0, 6))
        for i in range(3):
            ust.columnconfigure(i, weight=1, uniform="cari_ust")
        ust.rowconfigure(0, weight=0)

        p1_dis, p1 = beyaz_kart(ust, padx=6, pady=4)
        p1_dis.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        p2_dis, p2 = beyaz_kart(ust, padx=6, pady=4)
        p2_dis.grid(row=0, column=1, sticky="nsew", padx=(0, 4))
        p3_dis, p3 = beyaz_kart(ust, padx=6, pady=4)
        p3_dis.grid(row=0, column=2, sticky="nsew")

        self._musteri_formu(p1)
        self._ticari_risk_paneli(p2)
        self._bakiye_ozet_paneli(p3)

    def _etiket(self, parent, metin, width=None):
        """Üst 3 panel satır başlığı: mevcut +1 pt, bold, koyu lacivert."""
        kw = {
            "text": metin,
            "bg": BEYAZ,
            "fg": LACIVERT,
            "font": font(8, "bold", self),
            "anchor": "w",
        }
        if width is not None:
            kw["width"] = width
        return tk.Label(parent, **kw)

    def _entry(self, parent, alan, width=28, **kw):
        w = ttk.Entry(parent, width=width, **kw)
        self.degerler[alan] = w
        return w

    def _bolum_baslik(self, parent, metin):
        tk.Label(
            parent, text=metin, bg=BEYAZ, fg=LACIVERT, font=font(9, "bold", self)
        ).pack(anchor="w", pady=(0, 3))

    def _form_satiri(self, parent, etiket: str, etiket_genislik: int = 11):
        """Etiket solda, değer alanı sağda — kompakt üst paneller."""
        satir = tk.Frame(parent, bg=BEYAZ)
        satir.pack(fill="x", pady=(0, 1))
        self._etiket(satir, etiket, width=etiket_genislik).pack(side="left", padx=(0, 4))
        sag = tk.Frame(satir, bg=BEYAZ)
        sag.pack(side="left", fill="x", expand=True)
        return sag

    def _ozet_deger_satiri(self, parent, baslik: str, *, kalin: bool = False):
        """Sol etiket, sağ değer — borç/alacak özet satırı."""
        satir = tk.Frame(parent, bg=BEYAZ)
        satir.pack(fill="x", pady=0)
        lbl = tk.Label(
            satir,
            text=baslik,
            bg=BEYAZ,
            fg=LACIVERT,
            font=font(8, "bold", self),
            anchor="w",
        )
        lbl.pack(side="left")
        deger = tk.Label(
            satir,
            text="—",
            bg=BEYAZ,
            fg=LACIVERT,
            font=font(9 if kalin else 8, "bold", self),
            anchor="e",
        )
        deger.pack(side="right")
        self.ozet_degerleri[baslik] = deger
        return lbl, deger

    def _musteri_formu(self, parent):
        self._bolum_baslik(parent, f"{self.etiket} Bilgileri")

        alanlar = (
            ("Kod", "cari_kodu"),
            ("Ünvan", "unvan"),
            ("V.Dairesi", "vergi_dairesi"),
            ("VKN", "vergi_numarasi"),
            ("TCKN", "tc_kimlik"),
            ("Tel", "telefon"),
            ("Tel 2", "telefon2"),
            ("Tel 3", "telefon3"),
            ("E-posta", "email"),
        )
        for etiket, alan in alanlar:
            sag = self._form_satiri(parent, etiket)
            w = self._entry(sag, alan, width=16)
            w.pack(fill="x")
            if alan == "vergi_numarasi":
                w.bind("<FocusOut>", self._vergi_no_kontrol)
            elif alan == "tc_kimlik":
                w.bind("<FocusOut>", self._tc_kimlik_kontrol)

        grup_sag = self._form_satiri(parent, "Grup")
        grup_widget = ttk.Combobox(grup_sag, state="readonly", width=10)
        grup_widget.pack(side="left", fill="x", expand=True)
        self.degerler["musteri_grubu"] = grup_widget
        tk_buton(grup_sag, "Yeni", self.yeni_grup_ekle, rol="ikincil").pack(
            side="left", padx=(4, 0)
        )
        # Aktif checkbox yok; rozet / Pasife Al ile yönetilir.
        self.degerler["aktif"] = tk.BooleanVar(
            value=cari.aktif if (cari := self.cari) else True
        )

        self.musteri_grubu_secimini_hazirla()

    def _detay_seridini_olustur(self, parent):
        """Adresler · İstihbarat/Uyarı · Yetkililer · Muhasebe — buton şeridi + açılır panel."""
        dis, cerceve = beyaz_kart(parent, padx=8, pady=6)
        dis.pack(fill="x", pady=(0, 6))
        self._detay_dis = dis
        self._detay_aktif = None

        btn_satir = tk.Frame(cerceve, bg=BEYAZ)
        btn_satir.pack(fill="x")
        self._detay_butonlari = {}
        for anahtar, baslik in (
            ("adres", "Adresler"),
            ("istihbarat", "İstihbarat / Uyarı"),
            ("yetkili", "İşletme Yetkilileri"),
        ):
            dugme = tk_buton(
                btn_satir,
                baslik,
                lambda a=anahtar: self._detay_panel_ac(a),
                rol="ikincil",
            )
            dugme.pack(side="left", padx=(0, 6))
            self._detay_butonlari[anahtar] = dugme

        tk_buton(
            btn_satir, "Muhasebe Hesap Kodları", self.muhasebe_ac, rol="ikincil"
        ).pack(side="left", padx=(0, 6))

        self._detay_icerik = tk.Frame(cerceve, bg=BEYAZ)
        self._detay_paneller = {}

        adres_panel = tk.Frame(self._detay_icerik, bg=BEYAZ)
        self._adres_sekmelerini_olustur(adres_panel)
        self._detay_paneller["adres"] = adres_panel

        not_panel = tk.Frame(self._detay_icerik, bg=BEYAZ)
        self._istihbarat_sekmelerini_olustur(not_panel)
        self._detay_paneller["istihbarat"] = not_panel

        yetkili_panel = tk.Frame(self._detay_icerik, bg=BEYAZ)
        self._yetkili_panelini_olustur(yetkili_panel)
        self._detay_paneller["yetkili"] = yetkili_panel

    def _detay_panel_ac(self, anahtar: str):
        if self._detay_aktif == anahtar:
            self._detay_icerik.pack_forget()
            self._detay_aktif = None
            return
        for p in self._detay_paneller.values():
            p.pack_forget()
        panel = self._detay_paneller.get(anahtar)
        if panel is None:
            return
        self._detay_icerik.pack(fill="x", pady=(10, 0))
        panel.pack(fill="both", expand=True)
        self._detay_aktif = anahtar
        if anahtar == "yetkili":
            self.yetkili_ozetini_guncelle()

    def _yetkili_panelini_olustur(self, parent):
        from cari_yetkili_ui import YetkiliPanel

        self._bolum_baslik(parent, "İşletme Yetkilileri")
        self._yetkili_panel = YetkiliPanel(parent, dialog=self, gomulu=True)
        self._yetkili_panel.pack(fill="both", expand=True)

    def yetkili_ozetini_guncelle(self):
        panel = getattr(self, "_yetkili_panel", None)
        if panel is not None:
            if self.cari and getattr(self.cari, "id", None):
                panel._cari_id = int(self.cari.id)
            panel._yetki_durumu_ayarla()
            panel.yenile()

    def _adres_sekmelerini_olustur(self, parent):
        from database.turkiye_il_ilce import iller

        tk.Label(
            parent, text="Adresler", bg=BEYAZ, fg=LACIVERT, font=font(10, "bold", self)
        ).pack(anchor="w", pady=(0, 4))
        self.adres_sekme = ttk.Notebook(parent, style="CariKart.TNotebook")
        self.adres_sekme.pack(fill="x")
        tanimlar = (
            (1, "Adres 1", "adres", "il", "ilce", "adres_tipi", "Merkez"),
            (2, "Adres 2", "adres2", "il2", "ilce2", "adres_tipi2", "Fatura"),
            (3, "Adres 3", "adres3", "il3", "ilce3", "adres_tipi3", "Sevk"),
        )
        tip_secenekleri = ("Merkez", "Fatura", "Sevk", "Depo", "Şube", "Diğer")
        for _no, sekme_baslik, adres_alan, il_alan, ilce_alan, tip_alan, varsayilan_tip in tanimlar:
            sekme = tk.Frame(self.adres_sekme, bg=BEYAZ, padx=4, pady=4)
            self.adres_sekme.add(sekme, text=sekme_baslik)
            ust_satir = tk.Frame(sekme, bg=BEYAZ)
            ust_satir.pack(fill="x", pady=(0, 4))
            self._etiket(ust_satir, "Tür").pack(side="left", padx=(0, 4))
            tip_cb = ttk.Combobox(ust_satir, values=tip_secenekleri, state="readonly", width=12)
            tip_cb.set(varsayilan_tip)
            tip_cb.pack(side="left")
            self.degerler[tip_alan] = tip_cb
            self._etiket(sekme, "Adres").pack(anchor="w")
            adres_widget = tk.Text(sekme, width=48, height=2, wrap="word", font=font(9, root=self))
            adres_widget.pack(fill="x", pady=(1, 4))
            self.degerler[adres_alan] = adres_widget
            il_satir = tk.Frame(sekme, bg=BEYAZ)
            il_satir.pack(fill="x")
            self._etiket(il_satir, "İl").pack(side="left", padx=(0, 4))
            il_widget = ttk.Combobox(il_satir, state="readonly", width=14, values=iller())
            il_widget.pack(side="left")
            il_widget.bind(
                "<<ComboboxSelected>>",
                lambda _e, ia=il_alan, ica=ilce_alan: self._il_degisti(il_alan=ia, ilce_alan=ica),
            )
            self.degerler[il_alan] = il_widget
            self._etiket(il_satir, "İlçe").pack(side="left", padx=(8, 4))
            ilce_widget = ttk.Combobox(il_satir, state="readonly", width=14, values=[])
            ilce_widget.pack(side="left")
            self.degerler[ilce_alan] = ilce_widget

    def _istihbarat_sekmelerini_olustur(self, parent):
        tk.Label(
            parent, text="İstihbarat / Uyarı Notları", bg=BEYAZ, fg=LACIVERT, font=font(10, "bold", self)
        ).pack(anchor="w", pady=(0, 4))
        not_sekme = ttk.Notebook(parent, style="CariKart.TNotebook")
        not_sekme.pack(fill="x")
        n1 = tk.Frame(not_sekme, bg=BEYAZ, padx=6, pady=6)
        n2 = tk.Frame(not_sekme, bg=BEYAZ, padx=6, pady=6)
        not_sekme.add(n1, text="Özel Notlar")
        not_sekme.add(n2, text="Uyarı Notu")
        self.not_butonu = tk_buton(
            n1,
            "Notları Düzenle",
            self.notlari_ac,
            rol="ikincil",
            state="normal" if self.cari else "disabled",
        )
        self.not_butonu.pack(anchor="w")
        self.not_durumu = tk.Label(n1, text="", bg=BEYAZ, fg=IKINCIL, font=font(8, root=self))
        self.not_durumu.pack(anchor="w", pady=(4, 0))
        self.uyari_butonu = tk_buton(n2, "Uyarıyı Düzenle", self.uyari_ac, rol="ikincil")
        self.uyari_butonu.pack(anchor="w")
        self.uyari_durumu = tk.Label(n2, text="", bg=BEYAZ, fg=UYARI, font=font(8, "bold", self))
        self.uyari_durumu.pack(anchor="w", pady=(4, 0))
        self.not_durumunu_guncelle()
        self.uyari_durumunu_guncelle(self.uyari_notu)

    def _yan_yana_metrik(self, parent, anahtar: str, baslik: str, etiket_genislik: int = 14):
        """Sol etiket + sağ değer; ozet_kartlari {deger, alt} uyumlu (alt gizli)."""
        satir = tk.Frame(parent, bg=BEYAZ)
        satir.pack(fill="x", pady=(0, 1))
        self._etiket(satir, baslik, width=etiket_genislik).pack(side="left", padx=(0, 4))
        deger = tk.Label(
            satir, text="—", bg=BEYAZ, fg=LACIVERT, font=font(8, "bold", self), anchor="e"
        )
        deger.pack(side="right")
        alt = tk.Label(satir, text="", bg=BEYAZ)  # uyumluluk; pack edilmez
        self.ozet_kartlari[anahtar] = {"frame": satir, "deger": deger, "alt": alt}

    def _ticari_risk_paneli(self, parent):
        self._bolum_baslik(parent, "Ticari Bilgiler / Risk")
        self.ozet_kartlari = getattr(self, "ozet_kartlari", {}) or {}
        satis_listeler = ("",) + tuple(SATIS_FIYAT_ADLARI)
        alis_listeler = ("",) + tuple(ALIŞ_FIYAT_ADLARI)
        # Risk limiti (açık hesap) kaldırıldı; çek/senet + kullanılabilir risk kaldı.
        alanlar = (
            ("Satış listesi", "satis_fiyat_listesi", "combobox", satis_listeler),
            ("Alış listesi", "alis_fiyat_listesi", "combobox", alis_listeler),
            ("Satış vade", "satis_vade_gunu", "entry", None),
            ("Alış vade", "alis_vade_gunu", "entry", None),
            ("Çek risk", "cek_risk_limiti", "entry", None),
            ("Senet risk", "senet_risk_limiti", "entry", None),
        )
        for etiket, alan, tur, degerler_liste in alanlar:
            sag = self._form_satiri(parent, etiket, etiket_genislik=11)
            if tur == "combobox":
                w = ttk.Combobox(sag, values=degerler_liste, width=14)
            else:
                w = ttk.Entry(sag, width=14)
            w.pack(fill="x")
            self.degerler[alan] = w

        self._yan_yana_metrik(parent, "kullanilabilir_risk", "Kullanılabilir risk", 14)

    def _bakiye_ozet_paneli(self, parent):
        """Üçüncü üst panel: Toplam borç’tan başlayan borç / alacak özeti."""
        self._bolum_baslik(parent, "Borç / Alacak Özeti")
        if not getattr(self, "ozet_kartlari", None):
            self.ozet_kartlari = {}
        self.ozet_degerleri = {}

        lbl, _ = self._ozet_deger_satiri(parent, "Toplam borç")
        lbl, _ = self._ozet_deger_satiri(parent, "Toplam alacak")
        lbl, _ = self._ozet_deger_satiri(parent, "Kalan Bakiye", kalin=True)
        ToolTip(lbl, "Toplam borç − toplam alacak (defter kalan bakiyesi).")
        self._ozet_deger_satiri(parent, "Bakiye yönü")
        lbl, _ = self._ozet_deger_satiri(parent, "Ortalama borç kapatma süresi")
        ToolTip(
            lbl,
            "Teknik: Kapanan borcun tutar-ağırlıklı ortalama valörü (gün). "
            "FIFO eşleştirme; tamamen kapanan faturalar öncelikli.",
        )
        lbl, _ = self._ozet_deger_satiri(parent, "Ortalama Valör")
        ToolTip(
            lbl,
            "Bakiyeye göre Borç Valörü veya Alacak Valörü. "
            "Açık kalan tutarların ağırlıklı ortalama valörü.",
        )
        self._ozet_deger_satiri(parent, "Ortalama Valör Tarihi")
        self._ozet_deger_satiri(parent, "Ortalama Valör Gün Sayısı")
        # Son işlem: valör gün sayısının altında; yan yana
        self._yan_yana_metrik(parent, "son_islem", "Son işlem", 14)
        # Bekleyen sipariş tutarı bakiyeye dahil değildir — panelin en altında (bilgilendirme).
        bek_etiket = (
            "Bekleyen satın alma siparişleri"
            if self.tedarikci_modu
            else "Bekleyen satış siparişleri"
        )
        lbl_bek, deger_bek = self._ozet_deger_satiri(parent, bek_etiket)
        self._bekleyen_siparis_etiket = bek_etiket
        deger_bek.configure(cursor="hand2")
        lbl_bek.configure(cursor="hand2")
        deger_bek.bind("<Button-1>", lambda _e: self.bekleyen_siparisler_ac())
        lbl_bek.bind("<Button-1>", lambda _e: self.bekleyen_siparisler_ac())
        ToolTip(
            lbl_bek,
            "Açık siparişlerin kalan tutarı. Cari bakiyeye eklenmez; tıklayınca liste açılır.",
        )

    # ─── Hızlı işlemler / hareketler ──────────────────────────────
    def _hizli_islemleri_olustur(self, parent):
        """Hızlı işlemler + ekstre/bekleyen — tek satır, orantılı, sarı/lacivert dönüşümlü."""
        dis, hizli = beyaz_kart(parent, padx=10, pady=8)
        dis.pack(fill="x", pady=(0, 8))
        baslik_satir = tk.Frame(hizli, bg=BEYAZ)
        baslik_satir.pack(fill="x", pady=(0, 6))
        tk.Label(
            baslik_satir,
            text="Hızlı İşlemler",
            bg=BEYAZ,
            fg=LACIVERT,
            font=font(11, "bold", self),
        ).pack(side="left")
        self._yukleniyor_lbl = tk.Label(
            baslik_satir, text="", bg=BEYAZ, fg=DIKKAT, font=font(9, root=self)
        )
        self._yukleniyor_lbl.pack(side="left", padx=10)
        tk_buton(baslik_satir, "Yenile", self.yenile, rol="ikincil").pack(side="right")

        satir = tk.Frame(hizli, bg=BEYAZ)
        satir.pack(fill="x")
        self.hizli_dugmeleri = []
        kayitli = bool(self.cari)
        if self.tedarikci_modu:
            komutlar = (
                ("Yeni Sipariş", self.yeni_alis_siparis_ac, ("satis_duzenleme", "yeni_kayit")),
                ("Yeni İrsaliye", self.yeni_alis_irsaliye_ac, ("satis_duzenleme", "yeni_kayit")),
                ("Yeni Fatura", self.yeni_alis_fatura_ac, ("satis_duzenleme", "yeni_kayit")),
                ("Ödeme Gir", self.odeme_gir, ("finans_duzenleme", "cari_duzenleme")),
                ("Tahsilat", self.tahsilat_gir, ("finans_duzenleme", "cari_duzenleme")),
            )
        else:
            komutlar = (
                ("Yeni Sipariş", self.yeni_siparis_ac, ("satis_duzenleme", "yeni_kayit")),
                ("Yeni İrsaliye", self.yeni_irsaliye_ac, ("satis_duzenleme", "yeni_kayit")),
                ("Yeni Fatura", self.yeni_fatura_ac, ("satis_duzenleme", "yeni_kayit")),
                ("Tahsilat", self.tahsilat_gir, ("finans_duzenleme", "cari_duzenleme")),
                ("Ödeme Gir", self.odeme_gir, ("finans_duzenleme", "cari_duzenleme")),
            )
        # Sağda: stok detaylı ekstre + bekleyenler — aynı orantılı şeritte
        sag_ekler = (
            ("Stok Detaylı Cari Ekstre", self.stok_detayli_ekstre_ac, None),
            ("Bekleyen Siparişler", self.bekleyen_siparisler_ac, None),
        )
        tumu = list(komutlar) + list(sag_ekler)
        for i, (baslik, komut, izinler) in enumerate(tumu):
            rol = "vurgu" if i % 2 == 0 else "kaydet"  # sarı / lacivert
            if izinler is None:
                state = "normal" if kayitli else "disabled"
                izin_ok = True
            else:
                izin_ok = _izin_var(*izinler)
                state = "normal" if (kayitli and izin_ok) else "disabled"
            dugme = tk_buton(satir, baslik, komut, rol=rol, state=state)
            dugme.pack(side="left", expand=True, fill="x", padx=3)
            self.hizli_dugmeleri.append(dugme)
            if not izin_ok:
                ToolTip(dugme, "Bu işlem için yetkiniz yok.")

    def _hareket_tablosunu_olustur(self, parent):
        dis, hareket = beyaz_kart(parent, padx=10, pady=8)
        dis.pack(fill="both", expand=True)
        tk.Label(
            hareket, text="Cari Hareketler", bg=BEYAZ, fg=LACIVERT, font=font(11, "bold", self)
        ).pack(anchor="w", pady=(0, 6))

        baslik_satir = tk.Frame(hareket, bg=BEYAZ)
        baslik_satir.pack(fill="x", pady=(0, 4))
        tk.Label(
            baslik_satir,
            text="Fatura satırlarında ▶ ile ürün detayını açın",
            bg=BEYAZ,
            fg=IKINCIL,
            font=font(8, root=self),
        ).pack(side="left")
        tk_buton(
            baslik_satir,
            "Tüm Fatura Detaylarını Aç",
            self._tum_fatura_detaylarini_ac,
            rol="ikincil",
        ).pack(side="right", padx=(4, 0))
        tk_buton(
            baslik_satir,
            "Tüm Fatura Detaylarını Kapat",
            self._tum_fatura_detaylarini_kapat,
            rol="ikincil",
        ).pack(side="right")

        filtre = tk.Frame(hareket, bg=BEYAZ)
        filtre.pack(fill="x", pady=(0, 4))
        tk.Label(filtre, text="Belge türü:", bg=BEYAZ, fg=IKINCIL, font=font(9, root=self)).pack(
            side="left"
        )
        self.hareket_tur_filtre = ttk.Combobox(
            filtre,
            values=(
                "Tümü",
                "Sadece Faturalar",
                "Sadece Tahsilat/Ödeme",
                "Sadece Stoklu Faturalar",
                "Satış",
                "Alış",
                "Tahsilat",
                "Ödeme",
                "Cari Virman",
                "KK Çekimi",
                "Satış İadesi",
                "Alış İadesi",
            ),
            state="readonly",
            width=20,
        )
        self.hareket_tur_filtre.set("Tümü")
        self.hareket_tur_filtre.pack(side="left", padx=(4, 8))
        tk.Label(filtre, text="Ara:", bg=BEYAZ, fg=IKINCIL, font=font(9, root=self)).pack(side="left")
        self.hareket_arama = ttk.Entry(filtre, width=18)
        self.hareket_arama.pack(side="left", padx=4)
        tk.Label(filtre, text="Başlangıç:", bg=BEYAZ, fg=IKINCIL, font=font(9, root=self)).pack(
            side="left", padx=(8, 0)
        )
        bas_c = tk.Frame(filtre, bg=BEYAZ)
        bas_c.pack(side="left", padx=4)
        self.hareket_tarih_bas = ttk.Entry(bas_c, width=10)
        self.hareket_tarih_bas.pack(side="left")
        takvim_butonu(bas_c, self.hareket_tarih_bas, on_select=lambda: self._hareketleri_goster())
        tk.Label(filtre, text="Bitiş:", bg=BEYAZ, fg=IKINCIL, font=font(9, root=self)).pack(
            side="left", padx=(4, 0)
        )
        bit_c = tk.Frame(filtre, bg=BEYAZ)
        bit_c.pack(side="left", padx=4)
        self.hareket_tarih_bit = ttk.Entry(bit_c, width=10)
        self.hareket_tarih_bit.pack(side="left")
        takvim_butonu(bit_c, self.hareket_tarih_bit, on_select=lambda: self._hareketleri_goster())
        tk_buton(filtre, "Uygula", self._hareketleri_goster, rol="ara").pack(side="left", padx=(8, 0))
        tk_buton(filtre, "Temizle", self._hareket_filtre_temizle, rol="ikincil").pack(
            side="left", padx=6
        )
        tk_buton(filtre, "Excel", self._hareketleri_excel_aktar, rol="excel").pack(
            side="left", padx=(8, 0)
        )
        self.hareket_tur_filtre.bind("<<ComboboxSelected>>", lambda _e: self._hareketleri_goster())
        self.hareket_arama.bind("<Return>", lambda _e: self._hareketleri_goster())
        self.hareket_tarih_bas.bind("<Return>", lambda _e: self._hareketleri_goster())
        self.hareket_tarih_bit.bind("<Return>", lambda _e: self._hareketleri_goster())

        kolonlar = (
            "tarih",
            "tur",
            "belge",
            "aciklama",
            "urun_kodu",
            "barkod",
            "urun_adi",
            "miktar",
            "birim",
            "net_birim_fiyat",
            "satir_tutari",
            "pb",
            "doviz",
            "kur",
            "borc",
            "alacak",
            "bakiye",
            "gun",
        )
        tablo_cercevesi = tk.Frame(hareket, bg=BEYAZ)
        tablo_cercevesi.pack(fill="both", expand=True)
        # Hareket satırları: mevcut +2 pt, bold/koyu; başlıklar da büyütülür
        stil = ttk.Style(self)
        stil.configure(
            "CariKartHareket.Treeview",
            font=font(11, "bold", self),
            rowheight=32,
            fieldbackground=BEYAZ,
            background=BEYAZ,
            foreground=LACIVERT,
            borderwidth=0,
        )
        stil.configure(
            "CariKartHareket.Treeview.Heading",
            font=font(11, "bold", self),
            background=LACIVERT,
            foreground=BEYAZ,
            relief="flat",
            padding=(6, 5),
        )
        stil.map(
            "CariKartHareket.Treeview",
            background=[("selected", tema.SECIM_SARI)],
            foreground=[("selected", LACIVERT)],
        )
        stil.map(
            "CariKartHareket.Treeview.Heading",
            background=[("active", tema.LACIVERT_ORTA)],
            foreground=[("active", BEYAZ)],
        )
        tablo = ttk.Treeview(
            tablo_cercevesi,
            columns=kolonlar,
            show="tree headings",
            style="CariKartHareket.Treeview",
            selectmode="browse",
            height=10,
        )
        tablo.heading("#0", text="")
        tablo.column("#0", width=28, minwidth=28, stretch=False, anchor="center")
        kolon_ayar = {
            "tarih": ("Tarih", 88, "center", False),
            "tur": ("Belge Türü", 110, "w", False),
            "belge": ("Belge No", 120, "w", False),
            "aciklama": ("Açıklama", 180, "w", True),
            "urun_kodu": ("Stok Kodu", 105, "w", False),
            "barkod": ("Barkod", 120, "w", False),
            "urun_adi": ("Ürün Adı", 230, "w", True),
            "miktar": ("Miktar", 78, "e", False),
            "birim": ("Birim", 65, "center", False),
            "net_birim_fiyat": ("Net Birim Fiyat", 115, "e", False),
            "satir_tutari": ("Satır Tutarı", 115, "e", False),
            "pb": ("PB", 42, "center", False),
            "doviz": ("Döviz", 95, "e", False),
            "kur": ("Kur", 78, "e", False),
            "borc": ("Borç (TL)", 110, "e", False),
            "alacak": ("Alacak (TL)", 110, "e", False),
            "bakiye": ("Kalan Bakiye", 115, "e", False),
            "gun": ("Gün", 55, "center", False),
        }
        self._hareket_kolon_basliklari = {k: v[0] for k, v in kolon_ayar.items()}
        self._hareket_kolon_hizalari = {k: v[2] for k, v in kolon_ayar.items()}
        for kolon in kolonlar:
            baslik, genislik, hiza, stretch = kolon_ayar[kolon]
            tablo.column(
                kolon,
                width=genislik,
                minwidth=max(40, genislik // 2),
                anchor=hiza,
                stretch=stretch,
            )
        treeview_basliklari_guncelle(
            tablo,
            kolonlar,
            self._hareket_kolon_basliklari,
            aktif_kolon=self._hareket_siralama_kolon,
            azalan=self._hareket_siralama_azalan,
            hizalar=self._hareket_kolon_hizalari,
            komut_fn=self._hareket_sutun_sirala,
        )
        tablo.tag_configure("tek", background=BEYAZ)
        tablo.tag_configure("cift", background=STRIPE)
        tablo.tag_configure(
            "detay",
            background="#EEF2F7",
            foreground=LACIVERT,
            font=font(10, root=self),
        )
        tablo.tag_configure(
            "detay_uyari",
            background="#FEF3C7",
            foreground="#92400E",
            font=font(10, "bold", self),
        )
        tablo.tag_configure(
            "fatura_toplam",
            background="#DCEAF7",
            foreground=LACIVERT,
            font=font(11, "bold", self),
        )
        # Uyarı satırı ürün detayı olmayan belgelerde yalnızca bilgi verir.
        tablo.tag_configure(
            "detay_toplam",
            background="#FEE2E2",
            foreground=UYARI,
            font=font(11, "bold", self),
        )
        dikey = ttk.Scrollbar(tablo_cercevesi, orient="vertical", command=tablo.yview)
        yatay = ttk.Scrollbar(tablo_cercevesi, orient="horizontal", command=tablo.xview)
        tablo.configure(yscrollcommand=dikey.set, xscrollcommand=yatay.set)
        tablo.grid(row=0, column=0, sticky="nsew")
        dikey.grid(row=0, column=1, sticky="ns")
        yatay.grid(row=1, column=0, sticky="ew")
        tablo_cercevesi.rowconfigure(0, weight=1)
        tablo_cercevesi.columnconfigure(0, weight=1)
        tablo.bind("<Double-1>", self._hareket_belge_ac)
        tablo.bind("<F2>", self._hareket_belge_ac)
        tablo.bind("<Button-3>", self._hareket_context_menu)
        tablo.bind("<Button-1>", self._hareket_agac_tikla, add="+")
        tablo.bind("<<TreeviewOpen>>", self._hareket_agac_acildi)
        tablo.bind("<<TreeviewClose>>", self._hareket_agac_kapandi)
        tablo.bind("<Right>", self._hareket_sag_ok)
        tablo.bind("<Left>", self._hareket_sol_ok)
        self.hareket_tablosu = tablo
        self._hareket_menu = tk.Menu(self, tearoff=0)
        self._hareket_menu.add_command(label="Belgeyi Aç", command=self._hareket_belge_ac)
        self._hareket_menu.add_command(
            label="Fatura ürünlerini göster/gizle", command=self._secili_fatura_detay_toggle
        )
        self._hareket_menu.add_command(label="Yenile", command=self.yenile)

        toplam = tk.Frame(hareket, bg=BEYAZ)
        toplam.pack(fill="x", pady=(8, 0))
        self.hareket_genel_toplam = tk.Label(
            toplam,
            text="Genel: Borç: 0,00 TL  |  Alacak: 0,00 TL  |  Net: 0,00 TL",
            bg=BEYAZ,
            fg=LACIVERT,
            font=font(9, "bold", self),
        )
        self.hareket_genel_toplam.pack(side="right")
        self.hareket_alt_toplam = tk.Label(
            toplam, text="", bg=BEYAZ, fg=IKINCIL, font=font(9, root=self)
        )
        self.hareket_alt_toplam.pack(side="left")
        self._hareketler_cache = []
        self._hareket_iid_meta: dict = {}
        self._fatura_detay_cache: dict = {}
        self._hareket_yukleniyor = False

    def _hareket_sutun_sirala(self, kolon: str) -> None:
        """Sütun başlığı tıklanınca görünüm sırasını değiştirir (DB değişmez)."""
        if kolon not in self._hareket_kolon_basliklari:
            return
        self._hareket_siralama_kolon, self._hareket_siralama_azalan = siralama_yonu_degistir(
            self._hareket_siralama_kolon,
            self._hareket_siralama_azalan,
            kolon,
        )
        self._hareketleri_goster()

    @staticmethod
    def _hareket_siralama_anahtar(hareket: dict, kolon: str):
        if kolon == "tarih":
            return tarih_coz(hareket.get("tarih"))
        if kolon == "tur":
            return turkce_metin_anahtar(hareket.get("tur"))
        if kolon == "belge":
            return dogal_belge_anahtar(hareket.get("belge_no"))
        if kolon == "aciklama":
            return turkce_metin_anahtar(hareket.get("aciklama"))
        if kolon == "pb":
            return turkce_metin_anahtar(hareket.get("para_birimi"))
        if kolon == "doviz":
            return para_coz(hareket.get("doviz_tutari"))
        if kolon == "kur":
            return para_coz(hareket.get("kur"))
        if kolon == "borc":
            return para_coz(hareket.get("borc"))
        if kolon == "alacak":
            return para_coz(hareket.get("alacak"))
        if kolon == "bakiye":
            kalan = hareket.get("kalan")
            if kalan is None:
                return para_coz(
                    Decimal(str(hareket.get("borc") or 0))
                    - Decimal(str(hareket.get("alacak") or 0))
                )
            return para_coz(kalan)
        if kolon == "gun":
            t = tarih_coz(hareket.get("tarih"))
            if t is None:
                return None
            return (date.today() - t).days
        return None

    @staticmethod
    def _hareket_ikincil_anahtar(hareket: dict):
        """Aynı değerde kararlı sıra: tarih, belge, hareket_id."""
        t = hareket.get("tarih") or date.min
        if isinstance(t, datetime):
            t = t.date()
        hid = hareket.get("hareket_id")
        try:
            hid_n = int(hid) if hid is not None else 0
        except (TypeError, ValueError):
            hid_n = 0
        return (t, str(hareket.get("belge_no") or ""), hid_n)

    def _hareket_listeyi_sirala(self, satirlar: list) -> list:
        kolon = self._hareket_siralama_kolon
        if not kolon or kolon not in self._hareket_kolon_basliklari:
            return list(satirlar)
        return liste_sirala(
            satirlar,
            anahtar_fn=lambda h: self._hareket_siralama_anahtar(h, kolon),
            azalan=self._hareket_siralama_azalan,
            ikincil_fn=self._hareket_ikincil_anahtar,
        )

    def _hareket_baslik_isaretlerini_guncelle(self) -> None:
        if not self.hareket_tablosu or not self._hareket_kolon_basliklari:
            return
        treeview_basliklari_guncelle(
            self.hareket_tablosu,
            self._hareket_kolon_basliklari.keys(),
            self._hareket_kolon_basliklari,
            aktif_kolon=self._hareket_siralama_kolon,
            azalan=self._hareket_siralama_azalan,
            hizalar=self._hareket_kolon_hizalari,
            komut_fn=self._hareket_sutun_sirala,
        )

    # ─── Doldurma / dirty ─────────────────────────────────────────
    def _alanlari_doldur(self):
        combobox_alanlar = {
            "musteri_grubu",
            "satis_fiyat_listesi",
            "alis_fiyat_listesi",
            "il",
            "ilce",
            "adres_tipi",
            "il2",
            "ilce2",
            "adres_tipi2",
            "il3",
            "ilce3",
            "adres_tipi3",
        }
        if self.cari:
            for alan, widget in self.degerler.items():
                if alan == "aktif":
                    continue
                deger = getattr(self.cari, alan, None)
                if deger is None:
                    deger = ""
                elif alan in self.SAYISAL_TUTAR_ALANLARI:
                    deger = f"{Decimal(str(deger)):f}".rstrip("0").rstrip(".") or "0"
                elif alan in self.SAYISAL_GUN_ALANLARI:
                    deger = str(int(deger))
                else:
                    deger = deger or ""
                if isinstance(widget, tk.Text):
                    widget.insert("1.0", deger)
                elif alan in combobox_alanlar:
                    if deger:
                        widget.set(deger)
                else:
                    widget.insert(0, deger)
            for il_alan, ilce_alan in (("il", "ilce"), ("il2", "ilce2"), ("il3", "ilce3")):
                self._il_degisti(il_alan=il_alan, ilce_alan=ilce_alan)
                kayitli = getattr(self.cari, ilce_alan, None)
                if kayitli:
                    self.degerler[ilce_alan].set(kayitli)
            if not (getattr(self.cari, "adres_tipi", None) or "").strip():
                self.degerler["adres_tipi"].set("Merkez")
        else:
            otomatik_kod = CariService.sonraki_kod(self.cari_turu)
            self.degerler["cari_kodu"].insert(0, otomatik_kod)
        self.degerler["cari_kodu"].configure(state="readonly")
        self._telefon_butonlarini_guncelle()

    def _widget_deger(self, alan: str) -> str:
        widget = self.degerler.get(alan)
        if widget is None:
            return ""
        if alan == "aktif":
            return "1" if widget.get() else "0"
        onceki = None
        if alan == "cari_kodu" and isinstance(widget, ttk.Entry):
            onceki = str(widget.cget("state"))
            widget.configure(state="normal")
        deger = (
            widget.get("1.0", "end").strip()
            if isinstance(widget, tk.Text)
            else str(widget.get()).strip()
        )
        if onceki is not None:
            widget.configure(state=onceki)
        return deger

    def _form_snapshot(self) -> str:
        parcalar = [f"{a}={self._widget_deger(a)}" for a in sorted(self.degerler.keys())]
        for a in sorted(self.muhasebe.keys()):
            parcalar.append(f"muh.{a}={self.muhasebe.get(a) or ''}")
        parcalar.append(f"uyari={getattr(self, 'uyari_notu', '') or ''}")
        return "\n".join(parcalar)

    def _kirli_izlemeyi_bagla(self):
        def isaretle(_e=None):
            self._kirli = self._form_snapshot() != self._snapshot
            self._telefon_butonlarini_guncelle()
            self._baslik_rozetlerini_guncelle()

        for alan, widget in self.degerler.items():
            if alan == "aktif":
                continue
            if isinstance(widget, tk.Text):
                widget.bind("<<Modified>>", isaretle, add="+")
            else:
                widget.bind("<KeyRelease>", isaretle, add="+")
                widget.bind("<<ComboboxSelected>>", isaretle, add="+")

    def _kirli_mi(self) -> bool:
        return self._form_snapshot() != self._snapshot

    def _telefon_numarasi(self) -> str:
        ham = self._widget_deger("telefon") or self._widget_deger("telefon2") or ""
        return re.sub(r"\D", "", ham)

    def _telefon_butonlarini_guncelle(self):
        num = self._telefon_numarasi()
        state = "normal" if len(num) >= 10 else "disabled"
        if hasattr(self, "_ara_btn"):
            self._ara_btn.configure(state=state)
        if hasattr(self, "_wa_btn"):
            self._wa_btn.configure(state=state)

    def _telefon_ara(self):
        num = self._telefon_numarasi()
        if len(num) < 10:
            return
        try:
            webbrowser.open(f"tel:{num}")
        except Exception:
            messagebox.showinfo("Ara", f"Numara: {num}", parent=self)

    def _whatsapp_ac(self):
        num = self._telefon_numarasi()
        if len(num) < 10:
            return
        if num.startswith("0"):
            num = "90" + num[1:]
        elif not num.startswith("90"):
            num = "90" + num
        try:
            webbrowser.open(f"https://wa.me/{num}")
        except Exception:
            messagebox.showinfo("WhatsApp", "WhatsApp bağlantısı açılamadı.", parent=self)

    # ─── Uyarı / not ──────────────────────────────────────────────
    def _uyari_bandini_guncelle(self, metrik: dict | None = None):
        mesajlar = []
        uyari = (getattr(self, "uyari_notu", "") or "").strip()
        if uyari:
            mesajlar.append(f"Uyarı: {uyari}")
        aktif = bool(self.degerler.get("aktif").get()) if "aktif" in self.degerler else True
        if not aktif:
            mesajlar.append("Kart pasif — satışa kapalı kabul edilir.")
        if metrik:
            if (metrik.get("risk_durum") or "") in ("uyari", "engel") or (
                metrik.get("kullanilabilir_risk") is not None
                and Decimal(str(metrik.get("kullanilabilir_risk"))) < 0
            ):
                mesajlar.append("Risk limiti aşımı / yetersiz kullanılabilir risk.")
        for w in self._uyari_rozet_satiri.winfo_children():
            w.destroy()
        if mesajlar:
            self._uyari_bandi_lbl.configure(text="  |  ".join(mesajlar))
            if not self._uyari_bandi.winfo_ismapped():
                # Üst lacivert başlığın hemen altında
                self._uyari_bandi.pack(fill="x", padx=12, pady=(6, 0), after=self._ust_son)
            if not aktif:
                rozet(self._uyari_rozet_satiri, "Satışa kapalı", bg=UYARI).pack(side="left", padx=(0, 6))
            if metrik and metrik.get("kullanilabilir_risk") is not None:
                kalan = Decimal(str(metrik["kullanilabilir_risk"]))
                if kalan < 0:
                    rozet(self._uyari_rozet_satiri, "Risk aşımı", bg=UYARI).pack(side="left", padx=(0, 6))
        else:
            try:
                self._uyari_bandi.pack_forget()
            except tk.TclError:
                pass

    def notlari_ac(self):
        if self.cari:
            dialog = NotlarDialog(self, self.cari)
            self.wait_window(dialog)

    def uyari_ac(self):
        dialog = CariUyariDialog(
            self, cari=self.cari, baslangic_metin=getattr(self, "uyari_notu", "") or ""
        )
        self.wait_window(dialog)
        if dialog.result is not None:
            self.uyari_notu = dialog.result
            self.uyari_durumunu_guncelle(self.uyari_notu)
            self._uyari_bandini_guncelle()

    def uyari_durumunu_guncelle(self, metin=None):
        if metin is None:
            metin = getattr(self, "uyari_notu", "") or ""
            if self.cari is not None:
                metin = getattr(self.cari, "uyari_notu", None) or metin
        self.uyari_notu = (metin or "").strip()
        if hasattr(self, "uyari_durumu"):
            self.uyari_durumu.configure(
                text="Uyarı tanımlı" if self.uyari_notu else "Uyarı yok",
                fg=UYARI if self.uyari_notu else IKINCIL,
            )

    def muhasebe_ac(self):
        dialog = CariMuhasebeDialog(self, self.muhasebe)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.muhasebe = dialog.result

    def not_durumunu_guncelle(self):
        if hasattr(self, "not_durumu"):
            if self.cari and self.cari.ozel_notlar:
                self.not_durumu.configure(text="Not mevcut", fg=BASARI)
            else:
                self.not_durumu.configure(text="Not yok", fg=IKINCIL)

    def musteri_grubu_secimini_hazirla(self):
        gruplar = CariService.gruplari_listele()
        mevcut_grup = getattr(self.cari, "musteri_grubu", None) if self.cari else None
        if mevcut_grup and mevcut_grup not in gruplar:
            gruplar.append(mevcut_grup)
        self.degerler["musteri_grubu"]["values"] = gruplar
        if mevcut_grup:
            self.degerler["musteri_grubu"].set(mevcut_grup)
        elif gruplar:
            self.degerler["musteri_grubu"].set(gruplar[0])

    def yeni_grup_ekle(self):
        grup_adi = simpledialog.askstring("Yeni Grup Ekle", "Müşteri grup adı:", parent=self)
        if grup_adi is None:
            return
        try:
            eklenen_grup = CariService.grup_ekle(grup_adi)
        except ValueError as hata:
            messagebox.showwarning("Grup eklenemedi", str(hata), parent=self)
            return
        self.musteri_grubu_secimini_hazirla()
        self.degerler["musteri_grubu"].set(eklenen_grup)

    def _il_degisti(self, _event=None, il_alan="il", ilce_alan="ilce"):
        from database.turkiye_il_ilce import ilceler

        if il_alan not in self.degerler or ilce_alan not in self.degerler:
            return
        il = self.degerler[il_alan].get().strip()
        liste = ilceler(il)
        self.degerler[ilce_alan].configure(values=liste)
        mevcut = self.degerler[ilce_alan].get().strip()
        if mevcut not in liste:
            self.degerler[ilce_alan].set(liste[0] if liste else "")

    # ─── Özet güncelleme ──────────────────────────────────────────
    def _ozet_kartlarini_guncelle(self, metrik: dict | None):
        if not self.ozet_kartlari and not self.ozet_degerleri:
            return
        if not metrik:
            for k in self.ozet_kartlari.values():
                k["deger"].configure(text="—", fg=LACIVERT)
                k["alt"].configure(text="")
            for lbl in self.ozet_degerleri.values():
                lbl.configure(text="—", fg=LACIVERT)
            self._bekleyen_siparis_ozetini_guncelle()
            return
        bakiye = Decimal(str(metrik.get("bakiye") or 0))
        durum = metrik.get("bakiye_durumu") or "Bakiye yok"
        if bakiye > 0:
            renk, etiket = UYARI, "Borçlu"
        elif bakiye < 0:
            renk, etiket = BASARI, "Alacaklı"
        else:
            renk, etiket = IKINCIL, "Kapalı"
        if "guncel_bakiye" in self.ozet_kartlari:
            self.ozet_kartlari["guncel_bakiye"]["deger"].configure(
                text=para_goster(abs(bakiye)), fg=renk
            )
            self.ozet_kartlari["guncel_bakiye"]["alt"].configure(text=f"{etiket} · {durum}")

        if "kullanilabilir_risk" in self.ozet_kartlari:
            kalan = metrik.get("kullanilabilir_risk")
            if kalan is None:
                self.ozet_kartlari["kullanilabilir_risk"]["deger"].configure(
                    text="Tanımsız", fg=IKINCIL
                )
                self.ozet_kartlari["kullanilabilir_risk"]["alt"].configure(text="")
            else:
                kd = Decimal(str(kalan))
                self.ozet_kartlari["kullanilabilir_risk"]["deger"].configure(
                    text=para_goster(kd),
                    fg=UYARI if kd < 0 else (BASARI if kd > 0 else DIKKAT),
                )
                self.ozet_kartlari["kullanilabilir_risk"]["alt"].configure(text="")

        if "son_islem" in self.ozet_kartlari:
            st = metrik.get("son_islem_tarih")
            stutar = metrik.get("son_islem_tutar")
            if st is None:
                self.ozet_kartlari["son_islem"]["deger"].configure(text="—", fg=IKINCIL)
                self.ozet_kartlari["son_islem"]["alt"].configure(text="")
            else:
                tur = metrik.get("son_islem_tur") or ""
                tutar_yazi = para_goster(abs(Decimal(str(stutar or 0))))
                self.ozet_kartlari["son_islem"]["deger"].configure(
                    text=f"{tarih_goster(st)} · {tur} · {tutar_yazi}".strip(" ·"),
                    fg=LACIVERT,
                )
                self.ozet_kartlari["son_islem"]["alt"].configure(text="")

        odenen = float(metrik.get("odenen_ortalama_valor_gun") or 0)
        bvalor = float(metrik.get("bakiye_ortalama_valor_gun") or 0)
        valor_etiket = metrik.get("valor_turu_etiket") or "Valör Yok"
        valor_tarih = metrik.get("ortalama_valor_tarihi")
        yon = metrik.get("bakiye_yonu")
        if yon == "BORCLU":
            yon_yazi = "Borçlu"
        elif yon == "ALACAKLI":
            yon_yazi = "Alacaklı"
        elif yon == "KAPALI":
            yon_yazi = "Kapalı"
        else:
            yon_yazi = durum if durum and durum != "Bakiye yok" else (
                "Borçlu" if bakiye > 0 else ("Alacaklı" if bakiye < 0 else "Kapalı")
            )
        sebep = metrik.get("ortalama_valor_sebep")
        uyari = metrik.get("ortalama_valor_uyari")
        if "Toplam borç" in self.ozet_degerleri:
            self.ozet_degerleri["Toplam borç"].configure(
                text=para_goster(metrik.get("toplam_borc") or 0)
            )
            self.ozet_degerleri["Toplam alacak"].configure(
                text=para_goster(metrik.get("toplam_alacak") or 0)
            )
            if "Kalan Bakiye" in self.ozet_degerleri:
                self.ozet_degerleri["Kalan Bakiye"].configure(
                    text=para_goster(abs(bakiye)), fg=renk
                )
            if "Bakiye yönü" in self.ozet_degerleri:
                self.ozet_degerleri["Bakiye yönü"].configure(text=yon_yazi, fg=renk)
            elif "Bakiye durumu" in self.ozet_degerleri:
                self.ozet_degerleri["Bakiye durumu"].configure(text=yon_yazi, fg=renk)
            self.ozet_degerleri["Ortalama borç kapatma süresi"].configure(text=f"{odenen:.1f} gün")
            if "Ortalama Valör" in self.ozet_degerleri:
                self.ozet_degerleri["Ortalama Valör"].configure(text=valor_etiket)
            if "Ortalama Valör Tarihi" in self.ozet_degerleri:
                if valor_tarih is not None:
                    self.ozet_degerleri["Ortalama Valör Tarihi"].configure(
                        text=tarih_goster(valor_tarih)
                    )
                else:
                    self.ozet_degerleri["Ortalama Valör Tarihi"].configure(
                        text=sebep or "—"
                    )
            if "Ortalama Valör Gün Sayısı" in self.ozet_degerleri:
                if valor_tarih is not None or (bvalor and metrik.get("valor_turu") != "YOK"):
                    self.ozet_degerleri["Ortalama Valör Gün Sayısı"].configure(
                        text=f"{bvalor:.1f} gün"
                    )
                else:
                    self.ozet_degerleri["Ortalama Valör Gün Sayısı"].configure(
                        text=sebep or "0 gün"
                    )
            if uyari and "Ortalama Valör" in self.ozet_degerleri:
                ToolTip(self.ozet_degerleri["Ortalama Valör"], uyari)
            # Eski etiket uyumu
            if "Bakiyenin ortalama valörü" in self.ozet_degerleri:
                self.ozet_degerleri["Bakiyenin ortalama valörü"].configure(
                    text=f"{valor_etiket}: {bvalor:.1f} gün"
                )
        self._bekleyen_siparis_ozetini_guncelle()

    def _bekleyen_siparis_ozetini_guncelle(self):
        """Risk satırındaki bekleyen sipariş tutarını yeniler (bakiyeyi değiştirmez)."""
        etiket = getattr(self, "_bekleyen_siparis_etiket", None)
        if not etiket or etiket not in getattr(self, "ozet_degerleri", {}):
            return
        lbl = self.ozet_degerleri[etiket]
        if not self.cari or not getattr(self.cari, "id", None):
            lbl.configure(text="—", fg=IKINCIL)
            return
        try:
            from database.cari_bekleyen_siparis_service import cari_bekleyen_siparis_ozeti

            yon = "alis" if self.tedarikci_modu else "satis"
            ozet = cari_bekleyen_siparis_ozeti(int(self.cari.id), yon=yon)
            tutar = ozet.get("toplam_try") or 0
            diger = ozet.get("diger_pb") or {}
            yazi = para_goster(tutar)
            if diger:
                ek = " · ".join(
                    f"{para_goster(v).replace(' TL', '')} {pb}" for pb, v in diger.items()
                )
                yazi = f"{yazi} · {ek}"
            lbl.configure(text=yazi, fg=LACIVERT if tutar or diger else IKINCIL)
        except Exception:
            lbl.configure(text="—", fg=IKINCIL)

    # ─── Hareketler (orijinal mantık) ─────────────────────────────
    def _hareket_tarih_araligi(self):
        baslangic = bitis = None
        try:
            bas_metin = (self.hareket_tarih_bas.get() or "").strip()
            bit_metin = (self.hareket_tarih_bit.get() or "").strip()
            if bas_metin:
                baslangic = datetime.strptime(bas_metin, "%d.%m.%Y").date()
            if bit_metin:
                bitis = datetime.strptime(bit_metin, "%d.%m.%Y").date()
        except ValueError:
            messagebox.showerror("Tarih", "Tarihleri gg.aa.yyyy formatında girin.", parent=self)
            return None, None, False
        if baslangic and bitis and baslangic > bitis:
            messagebox.showwarning("Tarih", "Başlangıç bitişten sonra olamaz.", parent=self)
            return None, None, False
        return baslangic, bitis, True

    @staticmethod
    def _hareket_tutar_toplamlari(hareketler):
        borc = sum((Decimal(str(h.get("borc") or 0)) for h in hareketler), Decimal("0"))
        alacak = sum((Decimal(str(h.get("alacak") or 0)) for h in hareketler), Decimal("0"))
        return borc, alacak, borc - alacak

    def _hareket_filtre_temizle(self):
        self.hareket_tur_filtre.set("Tümü")
        self.hareket_arama.delete(0, "end")
        self.hareket_tarih_bas.delete(0, "end")
        self.hareket_tarih_bit.delete(0, "end")
        self._hareketleri_goster()

    def _hareket_filtreli_satirlar(self):
        tur = (self.hareket_tur_filtre.get() or "Tümü").strip()
        ara_ham = (self.hareket_arama.get() or "").strip()
        ara = ara_ham.casefold()
        baslangic, bitis, tarih_ok = self._hareket_tarih_araligi()
        if not tarih_ok:
            return False, [], [], [], {}

        genel_set = []
        for hareket in getattr(self, "_hareketler_cache", []) or []:
            h_tarih = hareket.get("tarih")
            if baslangic and h_tarih and h_tarih < baslangic:
                continue
            if bitis and h_tarih and h_tarih > bitis:
                continue
            if ara:
                metin = " ".join(
                    [
                        str(hareket.get("tur") or ""),
                        str(hareket.get("belge_no") or ""),
                        str(hareket.get("aciklama") or ""),
                    ]
                ).casefold()
                if ara not in metin:
                    continue
            genel_set.append(hareket)

        if tur and tur == "Sadece Faturalar":
            gorunen = [
                h
                for h in genel_set
                if (h.get("tur") or "") in ("Satış", "Alış", "Satış İadesi", "Alış İadesi")
                or h.get("genisletilebilir")
            ]
        elif tur and tur == "Sadece Tahsilat/Ödeme":
            gorunen = [
                h
                for h in genel_set
                if (h.get("tur") or "") in ("Tahsilat", "Ödeme")
            ]
        elif tur and tur == "Sadece Stoklu Faturalar":
            gorunen = [
                h
                for h in genel_set
                if h.get("genisletilebilir") and h.get("fatura_id")
            ]
        elif tur and tur != "Tümü":
            gorunen = [h for h in genel_set if (h.get("tur") or "") == tur]
        else:
            gorunen = list(genel_set)

        kronolojik = sorted(
            gorunen,
            key=lambda item: (
                item.get("tarih") or date.min,
                item.get("belge_no") or "",
                item.get("tur") or "",
            ),
        )
        calisan = Decimal("0")
        gosterilecek = []
        for hareket in kronolojik:
            calisan += Decimal(str(hareket.get("borc") or 0)) - Decimal(
                str(hareket.get("alacak") or 0)
            )
            satir = dict(hareket)
            satir["kalan"] = calisan
            gosterilecek.append(satir)
        gosterilecek.reverse()
        meta = {"tur": tur, "ara": ara_ham, "baslangic": baslangic, "bitis": bitis}
        return True, gosterilecek, genel_set, gorunen, meta

    @staticmethod
    def _excel_dosya_adi_parca(metin: str, varsayilan: str = "cari") -> str:
        metin = (metin or "").strip() or varsayilan
        metin = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", metin)
        metin = re.sub(r"\s+", "_", metin).strip("._")
        return (metin[:50] or varsayilan)

    def _hareketleri_excel_aktar(self):
        if not self.cari:
            messagebox.showinfo("Excel", "Önce cari kaydını seçin veya kaydedin.", parent=self)
            return
        ok, gosterilecek, _genel_set, gorunen, meta = self._hareket_filtreli_satirlar()
        if not ok:
            return
        try:
            from openpyxl import Workbook
        except ImportError:
            messagebox.showerror(
                "Excel", "openpyxl yüklü değil. Kurulum: pip install openpyxl", parent=self
            )
            return

        cari_kodu = self._widget_deger("cari_kodu") or (
            getattr(self.cari, "cari_kodu", "") if self.cari else ""
        )
        unvan = self._widget_deger("unvan") or (getattr(self.cari, "unvan", "") if self.cari else "")
        bugun = date.today().strftime("%Y%m%d")
        varsayilan_ad = (
            f"CariHareket_{self._excel_dosya_adi_parca(cari_kodu, 'kod')}_"
            f"{self._excel_dosya_adi_parca(unvan, 'unvan')}_{bugun}.xlsx"
        )
        yol = filedialog.asksaveasfilename(
            parent=self,
            title="Cari hareketleri Excel'e aktar",
            defaultextension=".xlsx",
            filetypes=[("Excel dosyası", "*.xlsx"), ("Tüm dosyalar", "*.*")],
            initialfile=varsayilan_ad,
        )
        if not yol:
            return
        if not str(yol).lower().endswith(".xlsx"):
            yol = f"{yol}.xlsx"

        basliklar = (
            "Tarih",
            "Belge Türü",
            "Belge Numarası",
            "Açıklama",
            "Stok Kodu",
            "Barkod",
            "Ürün Adı",
            "Miktar",
            "Birim",
            "Net Birim Fiyat",
            "Satır Tutarı",
            "Borç",
            "Alacak",
            "Kalan Bakiye",
            "Geçen Gün",
        )
        filtre_parcalari = [f"Belge türü: {meta.get('tur') or 'Tümü'}"]
        if meta.get("ara"):
            filtre_parcalari.append(f"Arama: {meta['ara']}")
        bas = meta.get("baslangic")
        bit = meta.get("bitis")
        if bas or bit:
            filtre_parcalari.append(
                f"Tarih: {tarih_goster(bas) if bas else '—'} – {tarih_goster(bit) if bit else '—'}"
            )
        else:
            filtre_parcalari.append("Tarih: Tümü")

        wb = Workbook()
        ws = wb.active
        ws.title = "Hareketler"
        ws.append(["Cari Kodu", cari_kodu])
        ws.append(["Cari Ünvanı", unvan])
        ws.append(["Aktarım Tarihi", datetime.now().strftime("%d.%m.%Y %H:%M")])
        ws.append(["Filtre", " | ".join(filtre_parcalari)])
        ws.append([])
        ws.append(list(basliklar))
        bugun_tarih = date.today()
        for hareket in gosterilecek:
            h_tarih = hareket.get("tarih")
            gun = (bugun_tarih - h_tarih).days if h_tarih else ""
            kalan_deger = hareket.get("kalan")
            if kalan_deger is None:
                kalan_deger = Decimal(str(hareket.get("borc") or 0)) - Decimal(
                    str(hareket.get("alacak") or 0)
                )
            ws.append(
                [
                    tarih_goster(h_tarih) if h_tarih else "",
                    hareket.get("tur") or "",
                    hareket.get("belge_no") or "",
                    hareket.get("aciklama") or "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    float(Decimal(str(hareket.get("borc") or 0))),
                    float(Decimal(str(hareket.get("alacak") or 0))),
                    float(Decimal(str(kalan_deger or 0))),
                    gun,
                ]
            )
            if hareket.get("genisletilebilir") and hareket.get("fatura_id"):
                try:
                    from database.cari_fatura_detay_service import CariFaturaDetayService

                    detay = CariFaturaDetayService.load_invoice_details(
                        int(hareket["fatura_id"]),
                        str(hareket.get("belge_tipi") or ""),
                        cari_id=int(hareket.get("cari_id") or self.cari.id),
                        hareket_id=hareket.get("hareket_id"),
                    )
                except (ValueError, TypeError):
                    detay = {}
                for satir in detay.get("satirlar") or []:
                    ws.append(
                        [
                            "",
                            "  Ürün",
                            "",
                            "",
                            satir.get("urun_kodu") or "",
                            satir.get("barkod") or "",
                            satir.get("urun_adi") or "",
                            satir.get("miktar_goster") or "",
                            satir.get("birim") or "",
                            satir.get("birim_fiyat_goster") or "",
                            satir.get("net_goster") or "",
                            "",
                            "",
                            "",
                            "",
                        ]
                    )
        t_borc, t_alacak, t_net = self._hareket_tutar_toplamlari(gorunen)
        ws.append([])
        ws.append(
            [
                "TOPLAM",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                float(t_borc),
                float(t_alacak),
                float(t_net),
                f"{len(gorunen)} hareket",
            ]
        )
        try:
            wb.save(yol)
        except PermissionError:
            messagebox.showerror(
                "Excel",
                "Dosya kaydedilemedi. Dosya başka bir programda açık olabilir.\n"
                f"Yol: {yol}",
                parent=self,
            )
            return
        except OSError as exc:
            messagebox.showerror("Excel", f"Dosya kaydedilemedi:\n{exc}", parent=self)
            return
        messagebox.showinfo("Excel", f"Cari hareketler aktarıldı.\n{Path(yol)}", parent=self)

    def _hareketleri_goster(self):
        if not self.hareket_tablosu:
            return
        for item in self.hareket_tablosu.get_children():
            self.hareket_tablosu.delete(item)
        self._hareket_iid_meta = {}
        # Filtre yenilemede detay önbelleğini temizle (eski açık satırlar kalkar)
        self._fatura_detay_cache = {}
        ok, gosterilecek, genel_set, gorunen, meta = self._hareket_filtreli_satirlar()
        if not ok:
            self.hareket_genel_toplam.configure(text="Genel: Borç: —  |  Alacak: —  |  Net: —")
            self.hareket_alt_toplam.configure(text="")
            return
        # Toplamlar sıralamadan önce (filtre kümesi); sıralama yalnızca görünüm sırası
        g_borc, g_alacak, g_net = self._hareket_tutar_toplamlari(genel_set)
        gosterilecek = self._hareket_listeyi_sirala(gosterilecek)
        self._hareket_baslik_isaretlerini_guncelle()
        for sira, hareket in enumerate(gosterilecek):
            self._hareket_satirini_ekle(hareket, tag="tek" if sira % 2 == 0 else "cift")
        self.hareket_genel_toplam.configure(
            text=(
                f"Genel: Borç: {para_goster(g_borc)}  |  "
                f"Alacak: {para_goster(g_alacak)}  |  "
                f"Net: {para_goster(g_net)}  ({len(genel_set)} hareket)"
            )
        )
        tur = meta.get("tur") or "Tümü"
        if tur and tur != "Tümü":
            a_borc, a_alacak, a_net = self._hareket_tutar_toplamlari(gorunen)
            self.hareket_alt_toplam.configure(
                text=(
                    f"{tur} — Borç: {para_goster(a_borc)}  |  "
                    f"Alacak: {para_goster(a_alacak)}  |  "
                    f"Net: {para_goster(a_net)}  ({len(gorunen)} hareket)"
                )
            )
        else:
            self.hareket_alt_toplam.configure(text="")

    def _hareket_satirini_ekle(self, hareket, tag="tek"):
        gun = (date.today() - hareket["tarih"]).days
        kalan_deger = hareket.get("kalan")
        if kalan_deger is None:
            kalan_deger = Decimal(str(hareket.get("borc") or 0)) - Decimal(
                str(hareket.get("alacak") or 0)
            )
        borc_d = Decimal(str(hareket.get("borc") or 0))
        alacak_d = Decimal(str(hareket.get("alacak") or 0))
        borc_metin = para_goster(borc_d) if borc_d != 0 else ""
        alacak_metin = para_goster(alacak_d) if alacak_d != 0 else ""
        kalan = para_goster(kalan_deger)
        pb = (hareket.get("para_birimi") or "TRY").upper()
        doviz = hareket.get("doviz_tutari") or 0
        kur = hareket.get("kur") or 1
        doviz_metin = (
            f"{float(doviz):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            if pb != "TRY" and Decimal(str(doviz or 0)) != 0
            else ""
        )
        kur_metin = (
            f"{float(kur):,.6f}".replace(",", "X").replace(".", ",").replace("X", ".")
            if pb != "TRY"
            else ""
        )
        genislet = bool(hareket.get("genisletilebilir") and hareket.get("fatura_id"))
        text0 = "▶" if genislet else ""
        satir_tag = "fatura_toplam" if genislet else tag
        iid = self.hareket_tablosu.insert(
            "",
            "end",
            text=text0,
            values=(
                tarih_goster(hareket["tarih"]),
                hareket["tur"],
                hareket["belge_no"],
                (hareket.get("aciklama") or "").strip(),
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                pb if pb != "TRY" else "",
                doviz_metin,
                kur_metin,
                borc_metin,
                alacak_metin,
                kalan,
                gun,
            ),
            tags=(satir_tag,),
            open=False,
        )
        self._hareket_iid_meta[iid] = dict(hareket)
        if genislet:
            # Lazy: placeholder child — TreeviewOpen ile gerçek satırlar yüklenir
            self.hareket_tablosu.insert(
                iid,
                "end",
                text="",
                values=("", "", "", "  (ürün detayı yüklenmedi)", "", "", "", "", "", "", "", "", "", "", "", "", "", ""),
                tags=("detay",),
                iid=f"{iid}__ph",
            )

    def _hareket_agac_tikla(self, event):
        """#0 sütununa tıklanınca aç/kapat."""
        if not self.hareket_tablosu:
            return
        if self.hareket_tablosu.identify_region(event.x, event.y) not in ("tree", "cell"):
            return
        col = self.hareket_tablosu.identify_column(event.x)
        row = self.hareket_tablosu.identify_row(event.y)
        if not row or col != "#0":
            return
        meta = self._hareket_iid_meta.get(row)
        if not meta or not meta.get("genisletilebilir"):
            return
        # Toggle open state
        if self.hareket_tablosu.item(row, "open"):
            self.hareket_tablosu.item(row, open=False)
            self.hareket_tablosu.item(row, text="▶")
        else:
            self._expand_invoice_row(row)
            self.hareket_tablosu.item(row, open=True)
            self.hareket_tablosu.item(row, text="▼")
        return "break"

    def _hareket_agac_acildi(self, _event=None):
        secim = self.hareket_tablosu.focus() or (
            self.hareket_tablosu.selection()[0] if self.hareket_tablosu.selection() else None
        )
        if not secim:
            return
        if secim in self._hareket_iid_meta:
            self._expand_invoice_row(secim)
            self.hareket_tablosu.item(secim, text="▼")

    def _hareket_agac_kapandi(self, _event=None):
        secim = self.hareket_tablosu.focus() or (
            self.hareket_tablosu.selection()[0] if self.hareket_tablosu.selection() else None
        )
        if secim and secim in self._hareket_iid_meta:
            self.hareket_tablosu.item(secim, text="▶")

    def _hareket_sag_ok(self, _event=None):
        secim = self.hareket_tablosu.selection()
        if not secim:
            return
        iid = secim[0]
        if iid in self._hareket_iid_meta and self._hareket_iid_meta[iid].get("genisletilebilir"):
            self._expand_invoice_row(iid)
            self.hareket_tablosu.item(iid, open=True, text="▼")
        return "break"

    def _hareket_sol_ok(self, _event=None):
        secim = self.hareket_tablosu.selection()
        if not secim:
            return
        iid = secim[0]
        if iid in self._hareket_iid_meta:
            self.hareket_tablosu.item(iid, open=False, text="▶")
        elif self.hareket_tablosu.parent(iid):
            parent = self.hareket_tablosu.parent(iid)
            self.hareket_tablosu.item(parent, open=False, text="▶")
            self.hareket_tablosu.selection_set(parent)
        return "break"

    def _secili_fatura_detay_toggle(self):
        secim = self.hareket_tablosu.selection()
        if not secim:
            return
        iid = secim[0]
        if iid not in self._hareket_iid_meta:
            parent = self.hareket_tablosu.parent(iid)
            if parent:
                iid = parent
        if iid not in self._hareket_iid_meta:
            return
        if self.hareket_tablosu.item(iid, "open"):
            self.hareket_tablosu.item(iid, open=False, text="▶")
        else:
            self._expand_invoice_row(iid)
            self.hareket_tablosu.item(iid, open=True, text="▼")

    def _expand_invoice_row(self, iid: str) -> None:
        meta = self._hareket_iid_meta.get(iid) or {}
        if not meta.get("genisletilebilir") or not meta.get("fatura_id"):
            if meta.get("detay_uyari"):
                messagebox.showinfo("Fatura detayı", meta["detay_uyari"], parent=self)
            return
        # Zaten yüklenmiş gerçek detaylar varsa çoğaltma
        children = list(self.hareket_tablosu.get_children(iid))
        if children and not any(c.endswith("__ph") for c in children):
            return
        for c in children:
            self.hareket_tablosu.delete(c)

        cache_key = (meta.get("belge_tipi"), int(meta["fatura_id"]))
        detay = self._fatura_detay_cache.get(cache_key)
        if detay is None:
            if self._hareket_yukleniyor:
                return
            self._hareket_yukleniyor = True
            try:
                from database.cari_fatura_detay_service import CariFaturaDetayService

                detay = CariFaturaDetayService.load_invoice_details(
                    int(meta["fatura_id"]),
                    str(meta.get("belge_tipi") or ""),
                    cari_id=int(meta.get("cari_id") or (self.cari.id if self.cari else 0) or 0)
                    or None,
                    hareket_id=meta.get("hareket_id"),
                )
                self._fatura_detay_cache[cache_key] = detay
            except ValueError as exc:
                messagebox.showerror("Fatura detayı", str(exc), parent=self)
                self.hareket_tablosu.insert(
                    iid,
                    "end",
                    text="",
                    values=("", "", "", "  Detay yüklenemedi", "", "", "", "", "", "", "", "", "", "", "", "", "", ""),
                    tags=("detay_uyari",),
                )
                return
            finally:
                self._hareket_yukleniyor = False

        satirlar = detay.get("satirlar") or []
        if not satirlar:
            msg = detay.get("uyari") or "Bu faturaya ait ürün detayı bulunamadı"
            self.hareket_tablosu.insert(
                iid,
                "end",
                text="",
                values=("", "", "", f"  {msg}", "", "", "", "", "", "", "", "", "", "", "", "", "", ""),
                tags=("detay_uyari",),
            )
            return

        for s in satirlar:
            parcalar = []
            if s.get("iskonto") and str(s.get("iskonto")) not in ("0", "0.0", ""):
                parcalar.append(f"İsk %{s.get('iskonto')}")
            parcalar.append(f"KDV {s.get('kdv_orani_goster')} ({s.get('kdv_goster')})")
            parcalar.append(f"Net {s.get('net_goster')}")
            parcalar.append(f"Brüt {s.get('brut_goster')}")
            if s.get("depo"):
                parcalar.append(f"Depo:{s['depo']}")
            if s.get("lot"):
                parcalar.append(f"Lot:{s['lot']}")
            if s.get("stok_yonu"):
                parcalar.append(str(s["stok_yonu"]))
            if s.get("stok_fark_uyari"):
                parcalar.append(s["stok_fark_uyari"])
            if s.get("aciklama"):
                parcalar.append(str(s["aciklama"]))
            acik = "  " + " · ".join(p for p in parcalar if p)
            self.hareket_tablosu.insert(
                iid,
                "end",
                text="",
                values=(
                    "",
                    "Ürün",
                    "",
                    "",
                    s.get("urun_kodu") or "",
                    s.get("barkod") or "",
                    s.get("urun_adi") or "",
                    s.get("miktar_goster") or "",
                    s.get("birim") or "",
                    s.get("birim_fiyat_goster") or "",
                    s.get("net_goster") or "",
                    s.get("para_birimi") or "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ),
                tags=("detay",),
            )


    def _clear_invoice_detail_cache(self):
        self._fatura_detay_cache = {}
        self._hareket_iid_meta = {}

    def _tum_fatura_detaylarini_kapat(self):
        if not self.hareket_tablosu:
            return
        for iid in self.hareket_tablosu.get_children(""):
            if iid in self._hareket_iid_meta and self._hareket_iid_meta[iid].get(
                "genisletilebilir"
            ):
                self.hareket_tablosu.item(iid, open=False, text="▶")

    def _tum_fatura_detaylarini_ac(self):
        if not self.hareket_tablosu:
            return
        adaylar = [
            iid
            for iid in self.hareket_tablosu.get_children("")
            if self._hareket_iid_meta.get(iid, {}).get("genisletilebilir")
            and self._hareket_iid_meta.get(iid, {}).get("fatura_id")
        ]
        sinir = 25
        if len(adaylar) > sinir:
            if not messagebox.askyesno(
                "Toplu aç",
                f"Ekranda {len(adaylar)} fatura var. "
                f"Yalnızca ilk {sinir} fatura detayı açılacak. Devam edilsin mi?",
                parent=self,
            ):
                return
            adaylar = adaylar[:sinir]
        for iid in adaylar:
            self._expand_invoice_row(iid)
            self.hareket_tablosu.item(iid, open=True, text="▼")

    def _hareket_belge_ac(self, _event=None):
        if getattr(self, "_belge_aciliyor", False):
            return "break"
        if not self.hareket_tablosu:
            return "break"
        # Tree sütununda (#0) çift tık — belge açma
        secim = self.hareket_tablosu.selection()
        if not secim:
            messagebox.showinfo("Belge", "Lütfen açılacak hareket satırını seçin.", parent=self)
            return "break"
        iid = secim[0]
        # Detay satırıysa üst faturayı aç
        if iid not in self._hareket_iid_meta:
            parent = self.hareket_tablosu.parent(iid)
            if parent:
                iid = parent
                self.hareket_tablosu.selection_set(iid)
        meta = self._hareket_iid_meta.get(iid) or {}
        tur = (meta.get("tur") or "").strip()
        belge_no = (meta.get("belge_no") or "").strip()
        if not belge_no:
            degerler = self.hareket_tablosu.item(iid, "values")
            if not degerler or len(degerler) < 3:
                return "break"
            tur = (degerler[1] or "").strip()
            belge_no = (degerler[2] or "").strip()
        if not belge_no:
            messagebox.showinfo("Belge", "Bu satırda belge numarası yok.", parent=self)
            return "break"
        self._belge_aciliyor = True
        try:
            acildi = self._hareket_belgeyi_ac(tur, belge_no)
            if not acildi:
                messagebox.showinfo(
                    "Belge",
                    f"{tur or 'Hareket'} / {belge_no} için açılabilir evrak bulunamadı.",
                    parent=self,
                )
            else:
                self.yenile()
        except ValueError as hata:
            messagebox.showerror("Belge açılamadı", str(hata), parent=self)
        finally:
            self._belge_aciliyor = False
        return "break"

    def _hareket_context_menu(self, event):
        row = self.hareket_tablosu.identify_row(event.y)
        if row:
            self.hareket_tablosu.selection_set(row)
            try:
                self._hareket_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self._hareket_menu.grab_release()

    def _hareket_belgeyi_ac(self, tur: str, belge_no: str) -> bool:
        from belge_onizleme_ui import hareket_belgeyi_ac

        return hareket_belgeyi_ac(self, tur, belge_no)

    def yenile(self):
        if not self.cari:
            return
        if getattr(self, "_yenile_devam", False):
            return
        self._yenile_devam = True
        self._yukleniyor = True
        self._fatura_detay_cache = {}
        if hasattr(self, "_yukleniyor_lbl"):
            self._yukleniyor_lbl.configure(text="Yükleniyor…")
            self.update_idletasks()
        cari_id = int(self.cari.id)

        def _is():
            return CariService.kart_ozet_metrikleri(cari_id)

        def _ok(metrik):
            try:
                hareketler = (metrik or {}).get("hareketler") or []
                self._ozet_kartlarini_guncelle(metrik)
                self._uyari_bandini_guncelle(metrik)
                self._hareketler_cache = hareketler
                turler = sorted(
                    {
                        (h.get("tur") or "").strip()
                        for h in hareketler
                        if (h.get("tur") or "").strip()
                    }
                )
                ozel = (
                    "Tümü",
                    "Sadece Faturalar",
                    "Sadece Tahsilat/Ödeme",
                    "Sadece Stoklu Faturalar",
                )
                degerler = list(ozel) + [t for t in turler if t not in ozel]
                mevcut = (
                    self.hareket_tur_filtre.get() if hasattr(self, "hareket_tur_filtre") else "Tümü"
                )
                self.hareket_tur_filtre.configure(values=degerler)
                self.hareket_tur_filtre.set(mevcut if mevcut in degerler else "Tümü")
                self._hareketleri_goster()
                self._baslik_rozetlerini_guncelle()
            except Exception as hata:
                messagebox.showerror("Yenileme", f"Özet yüklenemedi:\n{hata}", parent=self)
            finally:
                self._yukleniyor = False
                self._yenile_devam = False
                if hasattr(self, "_yukleniyor_lbl"):
                    self._yukleniyor_lbl.configure(text="")

        def _err(hata):
            self._yukleniyor = False
            self._yenile_devam = False
            if hasattr(self, "_yukleniyor_lbl"):
                self._yukleniyor_lbl.configure(text="")
            messagebox.showerror("Yenileme", f"Özet yüklenemedi:\n{hata}", parent=self)

        from ui_bg import arka_planda

        arka_planda(self, _is, on_ok=_ok, on_err=_err)

    # ─── Hızlı işlem açıcıları ────────────────────────────────────
    def stok_detayli_ekstre_ac(self):
        if not self.cari:
            messagebox.showwarning("Cari", "Önce cari kartı kaydedin.", parent=self)
            return
        from cari_ekstre_ui import StokDetayliCariEkstreDialog

        dialog = StokDetayliCariEkstreDialog(self, self.cari)
        self.wait_window(dialog)

    def bekleyen_siparisler_ac(self):
        if not self.cari or not getattr(self.cari, "id", None):
            messagebox.showwarning("Cari", "Önce cari kartı kaydedin.", parent=self)
            return
        from cari_bekleyen_siparis_ui import CariBekleyenSiparislerDialog

        yon = "alis" if self.tedarikci_modu else "satis"
        dialog = CariBekleyenSiparislerDialog(self, self.cari, yon=yon)
        self.wait_window(dialog)
        self._bekleyen_siparis_ozetini_guncelle()

    def yeni_siparis_ac(self):
        if not self.cari:
            return
        from app import SatisSiparisiDialog

        siparis = SatisSiparisiDialog(self, cari=self.cari)
        self.wait_window(siparis)
        self.yenile()

    def yeni_irsaliye_ac(self):
        if self.cari:
            from app import SatisIrsaliyesiDialog

            dialog = SatisIrsaliyesiDialog(self, cari=self.cari)
            self.wait_window(dialog)
            self.yenile()

    def yeni_fatura_ac(self):
        if self.cari:
            from app import SatisFaturasiDialog

            dialog = SatisFaturasiDialog(
                self, cari=self.cari, cari_ac=lambda cari: CariDialog(self, cari)
            )
            self.wait_window(dialog)
            self.yenile()

    def yeni_alis_siparis_ac(self):
        if not self.cari:
            return
        from alis_ui import AlisSiparisiDialog

        dialog = AlisSiparisiDialog(self, cari=self.cari)
        self.wait_window(dialog)
        self.yenile()

    def yeni_alis_irsaliye_ac(self):
        if self.cari:
            from alis_ui import AlisIrsaliyesiDialog

            dialog = AlisIrsaliyesiDialog(self, cari=self.cari)
            self.wait_window(dialog)
            self.yenile()

    def yeni_alis_fatura_ac(self):
        if self.cari:
            from alis_ui import AlisFaturasiDialog

            dialog = AlisFaturasiDialog(
                self,
                cari=self.cari,
                cari_ac=lambda c: CariDialog(self, c, cari_turu="Tedarikçi"),
            )
            self.wait_window(dialog)
            self.yenile()

    def tahsilat_gir(self):
        if not self.cari:
            return
        from kasa_makbuz_ui import KasaMakbuzDialog

        dialog = KasaMakbuzDialog(self, makbuz_turu="TAHSILAT", cari_id=self.cari.id)
        self.wait_window(dialog)
        if dialog.result:
            self.yenile()

    def odeme_gir(self):
        if self.cari:
            from app import CariTahsilatOdemeDialog

            dialog = CariTahsilatOdemeDialog(self, self.cari, tur="odeme")
            self.wait_window(dialog)
            if dialog.result:
                self.yenile()

    # ─── Doğrulama / kayıt ────────────────────────────────────────
    def _vergi_no_kontrol(self, _event=None):
        deger = self.degerler["vergi_numarasi"].get().strip()
        if not deger:
            return
        try:
            CariService.vergi_no_dogrula(deger)
        except ValueError as hata:
            messagebox.showwarning("Vergi no", str(hata), parent=self)

    def _tc_kimlik_kontrol(self, _event=None):
        deger = self.degerler["tc_kimlik"].get().strip()
        if not deger:
            return
        try:
            CariService.tc_kimlik_dogrula(deger)
        except ValueError as hata:
            messagebox.showwarning("TC kimlik no", str(hata), parent=self)

    def kaydet(self, kapat: bool = False) -> bool:
        if not _izin_var("cari_duzenleme", "yeni_kayit"):
            messagebox.showwarning("Yetki", "Cari düzenleme yetkiniz yok.", parent=self)
            return False
        veriler = {}
        for alan in self.degerler:
            if alan == "aktif":
                continue
            veriler[alan] = self._widget_deger(alan) or None
        if not veriler.get("unvan"):
            messagebox.showwarning(
                "Eksik bilgi",
                f"{self.etiket} adı/ünvanı zorunludur.",
                parent=self,
            )
            return False
        try:
            CariService.vergi_no_dogrula(veriler.get("vergi_numarasi"))
            CariService.tc_kimlik_dogrula(veriler.get("tc_kimlik"))
        except ValueError as hata:
            messagebox.showerror("Vergi / TC no", str(hata), parent=self)
            return False
        tutar_etiketleri = {
            "acik_hesap_risk_limiti": "Açık hesap risk limiti",
            "cek_risk_limiti": "Çek risk limiti",
            "senet_risk_limiti": "Senet risk limiti",
        }
        for alan in self.SAYISAL_TUTAR_ALANLARI:
            if alan not in veriler:
                continue
            ham = veriler.get(alan)
            if not ham:
                veriler[alan] = None
                continue
            try:
                veriler[alan] = Decimal(str(ham).replace(".", "").replace(",", "."))
            except Exception:
                messagebox.showwarning(
                    "Geçersiz tutar",
                    f"{tutar_etiketleri[alan]} geçerli bir sayı olmalıdır.",
                    parent=self,
                )
                return False
        gun_etiketleri = {
            "satis_vade_gunu": "Satış vade günü",
            "alis_vade_gunu": "Alış vade günü",
        }
        for alan in self.SAYISAL_GUN_ALANLARI:
            ham = veriler.get(alan)
            if not ham:
                veriler[alan] = None
                continue
            try:
                veriler[alan] = int(str(ham).replace(",", "").replace(".", ""))
            except Exception:
                messagebox.showwarning(
                    "Geçersiz gün",
                    f"{gun_etiketleri[alan]} tam sayı (gün) olmalıdır.",
                    parent=self,
                )
                return False
        for alan, deger in self.muhasebe.items():
            veriler[alan] = (deger or "").strip() or None
        veriler["cari_turu"] = self.cari.cari_turu if self.cari else self.cari_turu
        veriler["aktif"] = self.degerler["aktif"].get()
        uyari = (getattr(self, "uyari_notu", None) or "").strip() or None
        if self.cari is not None:
            uyari = (getattr(self.cari, "uyari_notu", None) or uyari) or None
        veriler["uyari_notu"] = uyari
        if not self.cari:
            veriler["cari_kodu"] = CariService.sonraki_kod(veriler["cari_turu"])
        try:
            self.result = (
                CariService.guncelle(self.cari.id, veriler)
                if self.cari
                else CariService.ekle(veriler)
            )
        except ValueError as hata:
            messagebox.showerror("Kayıt yapılamadı", str(hata), parent=self)
            return False
        except Exception as hata:
            messagebox.showerror("Kayıt yapılamadı", str(hata), parent=self)
            return False
        self.cari = self.result
        self.yetkili_ozetini_guncelle()
        if self.cari is not None:
            kod_w = self.degerler.get("cari_kodu")
            if isinstance(kod_w, ttk.Entry):
                onceki = str(kod_w.cget("state"))
                kod_w.configure(state="normal")
                kod_w.delete(0, "end")
                kod_w.insert(0, self.cari.cari_kodu or "")
                kod_w.configure(state=onceki)
            for dugme in getattr(self, "hizli_dugmeleri", []) or []:
                try:
                    dugme.configure(state="normal")
                except tk.TclError:
                    pass
            if hasattr(self, "not_butonu"):
                self.not_butonu.configure(state="normal")
            self.yenile()
        self._snapshot = self._form_snapshot()
        self._kirli = False
        self._baslik_rozetlerini_guncelle()
        messagebox.showinfo("Kaydedildi", "Cari kart kaydedildi.", parent=self)
        if kapat:
            self.destroy()
        return True

    def kaydet_ve_kapat(self):
        self.kaydet(kapat=True)

    def _cari_pencere_boyutlandirma_ac(self) -> None:
        """Cari kart yeniden boyutlanabilir olsun; büyüt/küçült çalışsın."""
        try:
            self.wm_transient("")
        except tk.TclError:
            try:
                self.transient(None)
            except Exception:
                pass
        try:
            self.resizable(True, True)
        except tk.TclError:
            pass
        try:
            from ui_pencere import belge_penceresini_hazirla

            belge_penceresini_hazirla(
                self,
                min_genislik=1040,
                min_yukseklik=620,
                varsayilan_genislik=1280,
                varsayilan_yukseklik=780,
                maximize=True,
            )
        except Exception:
            try:
                from ui_pencere import calisma_alani

                _x, _y, aw, ah = calisma_alani(self)
                min_w = min(800, max(640, aw // 2))
                min_h = min(500, max(420, ah // 2))
                self.minsize(min_w, min_h)
            except Exception:
                try:
                    self.minsize(720, 480)
                except tk.TclError:
                    pass
            try:
                self.state("zoomed")
            except tk.TclError:
                pass
        try:
            if str(self.state() or "") == "zoomed":
                btn = getattr(self, "_btn_pencere_buyut", None)
                if btn is not None:
                    btn.configure(text="❐")
        except tk.TclError:
            pass

    def _cari_pencere_asagi(self, _event=None):
        """Görev çubuğuna indir (minimize)."""
        try:
            self.iconify()
        except tk.TclError:
            pass

    def _cari_pencere_buyut_toggle(self, _event=None):
        """Tam ekran (zoomed) ↔ önceki boyut."""
        try:
            durum = str(self.state() or "")
        except tk.TclError:
            durum = ""
        btn = getattr(self, "_btn_pencere_buyut", None)
        try:
            if durum == "zoomed":
                self.state("normal")
                geo = getattr(self, "_cari_onceki_geometry", None)
                if geo:
                    try:
                        self.geometry(geo)
                    except tk.TclError:
                        pass
                if btn is not None:
                    btn.configure(text="□")
            else:
                try:
                    self._cari_onceki_geometry = self.geometry()
                except tk.TclError:
                    self._cari_onceki_geometry = None
                self.state("zoomed")
                if btn is not None:
                    btn.configure(text="❐")
        except tk.TclError:
            pass
        return "break"

    def yeni_kart(self):
        """Boş form → doldur → Kaydet akışı için yeni cari kartı açar."""
        if self.cari is None and not self._kirli_mi():
            # Zaten boş kart: odak ünvan — Kaydet (F1) ile kaydedilir
            try:
                w = self.degerler.get("unvan")
                if w is not None:
                    w.focus_set()
            except tk.TclError:
                pass
            return
        if not self._kapatmadan_once_onay():
            return
        parent = self.master
        tur = self.cari_turu
        self.destroy()
        CariDialog(parent, cari=None, cari_turu=tur)

    def durumu_degistir(self):
        if not self.cari:
            return
        yeni_durum = not self.cari.aktif
        ad = f"{self.cari.cari_kodu} — {self.cari.unvan}"
        if yeni_durum is False:
            if not messagebox.askyesno(
                "Pasife Al",
                f"«{ad}» pasife alınsın mı?\nPasif kartlar satışa kapalı kabul edilir.",
                parent=self,
            ):
                return
        else:
            if not messagebox.askyesno(
                "Aktif Et", f"«{ad}» tekrar aktif edilsin mi?", parent=self
            ):
                return
        try:
            self.result = CariService.guncelle(self.cari.id, {"aktif": yeni_durum})
        except ValueError as hata:
            messagebox.showerror("İşlem yapılamadı", str(hata), parent=self)
            return
        self.destroy()

    def _kapatmadan_once_onay(self) -> bool:
        if not self._kirli_mi():
            return True
        cevap = messagebox.askyesnocancel(
            "Kaydedilmemiş değişiklikler",
            "Değişiklikler kaydedilsin mi?\n\n"
            "Evet = Kaydet\nHayır = Kaydetmeden Çık\nİptal = Vazgeç",
            parent=self,
        )
        if cevap is None:
            return False
        if cevap:
            return self.kaydet(kapat=False)
        return True

    def _kapat_istegi(self):
        if self._kapatmadan_once_onay():
            self.destroy()

    def _f1_kaydet(self, _event=None):
        try:
            if not self.winfo_exists():
                return
            odak = self.focus_get()
            if odak is None:
                return
            w = odak
            while w is not None:
                if w == self:
                    self.kaydet()
                    return "break"
                w = w.master if hasattr(w, "master") else None
        except tk.TclError:
            return
        return "break"

    def destroy(self):
        try:
            self._clear_invoice_detail_cache()
        except Exception:
            pass
        try:
            self.unbind_all("<F1>")
        except tk.TclError:
            pass
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except (tk.TclError, AttributeError):
            pass
        super().destroy()

    def _fare_tekerlegi(self, event):
        try:
            self.canvas.yview_scroll(-int(event.delta / 120), "units")
        except tk.TclError:
            pass
