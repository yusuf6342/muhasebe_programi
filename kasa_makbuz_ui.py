"""Tahsilat / ödeme makbuzu — çok satırlı (nakit, havale, kredi kartı) kart ekranı ve makbuz listesi.

Tahsilat makbuzunda "Cari Virman" işlem türü: müşteriden alacak ile tedarikçiye borç aynı tutarda
mahsup edilir (kasa / banka / POS / kart hareketi yok).
"Müşteriden tedarikçiye kredi kartı ile ödeme" seçilince KK çekim fişi açılır; listede kendi adıyla görünür.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

from database.acik_kalem_service import AcikKalemDegisti
from database.cari_service import CariService
from database.cari_virman_makbuz_service import CariVirmanMakbuzService, musteri_mi, tedarikci_mi
from database.finans_service import FinansService
from database.kk_cekimi_service import KK_ODEME_ADI, KkCekimiService
from database.satis_siparisi_service import ODEME_SEKILLERI
from database.turkce_normalize import turkce_normalize
from satis_tema import (
    ACIK_BG,
    ACIK_SARI,
    BASARI,
    BEYAZ,
    CIZGI,
    IKINCIL,
    KOYU_LACIVERT,
    LACIVERT,
    METIN,
    SARI,
    UYARI,
    font,
    stil_uygula,
    tk_buton,
    treeview_stil,
)
from tutar_bicim import isim_fontu, tr_tutar, tutar_alani, tutar_coz
from ui_takvim import takvim_butonu

TAHSILAT_MAKBUZ_SEKILLERI = ODEME_SEKILLERI  # NAKİT / KASA, GELEN HAVALE, KREDİ KARTIYLA TAHSİLAT
SIRKET_KARTI_SEKLI = "ŞİRKET KREDİ KARTI"
ODEME_MAKBUZ_SEKILLERI = ("NAKİT / KASA", "GÖNDERİLEN HAVALE", SIRKET_KARTI_SEKLI)

KART_TIPLERI = {"Kredi Kartı": "KREDI_KARTI", "Banka Kartı": "BANKA_KARTI"}
_KART_TIPI_ETIKET = {v: k for k, v in KART_TIPLERI.items()}
DURUM_FILTRELERI = {"Tümü": None, "Açık": "AÇIK", "İptal": "IPTAL"}
ISLEM_TAHSILAT = "Tahsilat"
ISLEM_VIRMAN = "Cari Virman"
CARI_VIRMAN_SEKLI = "CARİ VİRMAN"
KK_ODEME_SEKLI = KK_ODEME_ADI
VIRMAN_BILGI = (
    "Kasa, banka, POS veya kredi kartı hareketi oluşmaz. Müşteri ve tedarikçi cari hesaplarına aynı tutarda "
    "alacak yazılır: müşterinin borcu ve tedarikçiye olan borcunuz birlikte azalır. İki hareket tek işlemde kaydedilir."
)


def _bakiye_yazisi(bakiye) -> tuple[str, str]:
    bakiye = Decimal(str(bakiye or 0))
    if bakiye > 0:
        return f"{_para(bakiye)}  Borçlu", UYARI
    if bakiye < 0:
        return f"{_para(-bakiye)}  Alacaklı", BASARI
    return f"{_para(0)}  (Kapalı)", IKINCIL


def _para(tutar):
    return f"{float(tutar or 0):,.2f} TL".replace(",", "X").replace(".", ",").replace("X", ".")


def _tarih_yazi(t) -> str:
    return t.strftime("%d.%m.%Y") if hasattr(t, "strftime") else str(t or "")


def _tarih_oku(metin: str, alan: str = "Tarih") -> date:
    try:
        return datetime.strptime((metin or "").strip(), "%d.%m.%Y").date()
    except ValueError as hata:
        raise ValueError(f"{alan} GG.AA.YYYY biçiminde olmalıdır (ör. 28.09.2026).") from hata


def _tutar_oku(metin: str) -> Decimal:
    tutar = tutar_coz(metin)
    if tutar <= 0:
        raise ValueError("Tutar sıfırdan büyük olmalıdır.")
    return tutar.quantize(Decimal("0.01"))


def _sekil_turu(sekil: str | None) -> str | None:
    s = (sekil or "").replace("İ", "I").replace("ı", "i").upper()
    if "HAVALE" in s:
        return "HAVALE"
    if "KART" in s or "POS" in s:
        return "KART"
    if "KASA" in s or "NAKIT" in s:
        return "KASA"
    return None


def _tablo_stili(tablo: ttk.Treeview) -> None:
    treeview_stil(tablo)
    stil = ttk.Style(tablo)
    # vista temasında başlık arka planı uygulanmaz; beyaz yazı görünmez kalır
    stil.configure("Makbuz.Treeview", **{k: stil.lookup("Satis.Treeview", k) for k in ("font", "rowheight")})
    stil.configure("Makbuz.Treeview.Heading", font=font(10, "bold", tablo), foreground=LACIVERT)
    stil.map("Makbuz.Treeview", background=[("selected", ACIK_SARI)], foreground=[("selected", KOYU_LACIVERT)])
    tablo.configure(style="Makbuz.Treeview")


def _cari_etiket(cari):
    return f"{cari.cari_kodu} - {cari.unvan}"


def _hesap_ozet(makbuz) -> str:
    satirlar = list(getattr(makbuz, "satirlar", None) or [])
    if len(satirlar) > 1:
        adlar = []
        for s in satirlar:
            h = getattr(s, "finans_hesap", None)
            if h and h.hesap_adi not in adlar:
                adlar.append(h.hesap_adi)
        if len(adlar) == 1:
            return f"{adlar[0]} (+{len(satirlar) - 1})"
        return f"Çoklu ({len(satirlar)})"
    if satirlar:
        h = getattr(satirlar[0], "finans_hesap", None)
        if h:
            return h.hesap_adi
    return makbuz.finans_hesap.hesap_adi if makbuz.finans_hesap else "—"


def _odeme_ozet(makbuz) -> str:
    sekiller = []
    for s in getattr(makbuz, "satirlar", None) or []:
        ad = (s.odeme_sekli or "").strip()
        if ad and ad not in sekiller:
            sekiller.append(ad)
    return ", ".join(sekiller) or "—"


def _kart_detayi(satir: dict) -> str:
    if satir.get("kredi_karti_id"):
        return f"{int(satir.get('taksit_sayisi') or 1)} taksit"
    tip = satir.get("kart_tipi")
    if not tip:
        return ""
    if tip == "BANKA_KARTI":
        return "Banka kartı"
    return f"Kredi kartı · {int(satir.get('taksit_sayisi') or 1)} taksit"


class _CariAramaKutusu:
    """Cari alanına yazarken adın herhangi bir yerinde geçenleri açılır listede gösterir."""

    AZAMI_SONUC = 60

    def __init__(self, sahibi: tk.Toplevel, entry: ttk.Entry, var: tk.StringVar, kayitlar, on_secim):
        self.sahibi = sahibi
        self.entry = entry
        self.var = var
        self.kayitlar = kayitlar  # [(etiket, normalize, id)]
        self.on_secim = on_secim
        self.secili_id: int | None = None
        self.secili_etiket: str | None = None
        self.eslesen: list[tuple[str, str, int]] = []
        self.popup: tk.Toplevel | None = None
        self.liste: tk.Listbox | None = None
        self._bastir = False
        var.trace_add("write", self._yazildi)
        entry.bind("<Down>", self._asagi, add="+")
        entry.bind("<Return>", self._enter, add="+")
        entry.bind("<Escape>", self._esc, add="+")
        entry.bind("<FocusOut>", lambda _e: self.sahibi.after(180, self._odak_kontrol), add="+")

    def acik_mi(self) -> bool:
        return self.popup is not None and self.popup.winfo_exists()

    def ara(self, metin: str) -> list[tuple[str, str, int]]:
        aranan = turkce_normalize(metin or "").strip()
        if not aranan:
            return []
        return [k for k in self.kayitlar if aranan in k[1]][: self.AZAMI_SONUC]

    def secimi_ayarla(self, cari_id: int | None) -> None:
        etiket = next((k[0] for k in self.kayitlar if k[2] == cari_id), "") if cari_id else ""
        self._bastir = True
        try:
            self.var.set(etiket)
        finally:
            self._bastir = False
        self.secili_id = int(cari_id) if cari_id and etiket else None
        self.secili_etiket = etiket or None
        self.gizle()

    def _yazildi(self, *_):
        if self._bastir:
            return
        metin = self.var.get()
        if self.secili_id is not None and metin != self.secili_etiket:
            self.secili_id = None
            self.secili_etiket = None
            self.on_secim(None)
        tam = next((k for k in self.kayitlar if k[0] == metin.strip()), None)
        if tam is not None and self.secili_id != tam[2]:
            self.secili_id, self.secili_etiket = tam[2], tam[0]
            self.gizle()
            self.on_secim(tam[2])
            return
        self.eslesen = self.ara(metin)
        if self.eslesen and self.secili_id is None:
            self._goster()
        else:
            self.gizle()

    def _goster(self):
        if not self.acik_mi():
            self.popup = tk.Toplevel(self.sahibi)
            self.popup.withdraw()
            self.popup.overrideredirect(True)
            self.popup.transient(self.sahibi)
            cerceve = tk.Frame(self.popup, bg=LACIVERT, bd=1)
            cerceve.pack(fill="both", expand=True)
            self.liste = tk.Listbox(
                cerceve,
                activestyle="dotbox",
                exportselection=False,
                font=font(11, "bold", self.sahibi),
                selectbackground=SARI,
                selectforeground=KOYU_LACIVERT,
                relief="flat",
                highlightthickness=0,
            )
            kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.liste.yview)
            self.liste.configure(yscrollcommand=kaydir.set)
            self.liste.pack(side="left", fill="both", expand=True)
            kaydir.pack(side="right", fill="y")
            self.liste.bind("<Return>", lambda _e: self._listeden_sec())
            self.liste.bind("<Double-Button-1>", lambda _e: self._listeden_sec())
            self.liste.bind("<ButtonRelease-1>", lambda _e: self._listeden_sec())
            self.liste.bind("<Escape>", lambda _e: (self.gizle(), self.entry.focus_set()))
            self.liste.bind("<Up>", self._liste_yukari)
            self.liste.bind("<FocusOut>", lambda _e: self.sahibi.after(180, self._odak_kontrol))
        self.liste.delete(0, "end")
        for etiket, _n, _i in self.eslesen:
            self.liste.insert("end", etiket)
        self.liste.configure(height=min(8, len(self.eslesen)))
        self.entry.update_idletasks()
        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() + self.entry.winfo_height()
        genislik = max(self.entry.winfo_width(), 320)
        yukseklik = min(8, len(self.eslesen)) * 24 + 6
        self.popup.geometry(f"{genislik}x{yukseklik}+{x}+{y}")
        self.popup.deiconify()
        self.popup.lift()

    def gizle(self):
        if self.acik_mi():
            self.popup.destroy()
        self.popup = None
        self.liste = None

    def sec(self, indeks: int) -> None:
        if not (0 <= indeks < len(self.eslesen)):
            return
        etiket, _n, cari_id = self.eslesen[indeks]
        self._bastir = True
        try:
            self.var.set(etiket)
        finally:
            self._bastir = False
        self.secili_id, self.secili_etiket = cari_id, etiket
        self.gizle()
        self.entry.icursor("end")
        self.on_secim(cari_id)

    def _listeden_sec(self):
        if self.liste is None:
            return "break"
        secim = self.liste.curselection()
        self.sec(secim[0] if secim else 0)
        try:
            self.entry.tk_focusNext().focus_set()
        except (tk.TclError, AttributeError):
            pass
        return "break"

    def _asagi(self, _e=None):
        if not self.acik_mi():
            self.eslesen = self.ara(self.var.get())
            if not self.eslesen:
                return None
            self._goster()
        self.liste.focus_set()
        self.liste.selection_clear(0, "end")
        self.liste.selection_set(0)
        self.liste.activate(0)
        return "break"

    def _liste_yukari(self, _e=None):
        if self.liste is not None and self.liste.curselection() in ((0,), ()):
            self.entry.focus_set()
            return "break"
        return None

    def _enter(self, _e=None):
        if self.acik_mi() and self.eslesen:
            self.sec(0)
            try:
                self.entry.tk_focusNext().focus_set()
            except (tk.TclError, AttributeError):
                pass
            return "break"
        return None

    def _esc(self, _e=None):
        if self.acik_mi():
            self.gizle()
            return "break"
        return None

    def _odak_kontrol(self):
        try:
            odak = self.sahibi.focus_get()
        except (tk.TclError, KeyError):
            odak = None
        if odak is not None and (odak is self.entry or odak is self.liste):
            return
        if self.acik_mi():
            try:
                x, y = self.sahibi.winfo_pointerxy()
                altta = self.sahibi.winfo_containing(x, y)
            except (tk.TclError, KeyError):
                altta = None
            if altta is not None and str(altta).startswith(str(self.popup)):
                self.sahibi.after(200, self._odak_kontrol)
                return
        self.gizle()


class KasaMakbuzDialog(tk.Toplevel):
    """Tahsilat / ödeme makbuzu kartı.

    makbuz_id verilmezse her açılışta yeni ve boş makbuz; verilirse kayıtlı makbuz görüntülenir.
    virman_id: kayıtlı cari virman makbuzu; islem_turu="VIRMAN": yeni tahsilat makbuzu Cari Virman ile açılır.
    fatura_id: yeni tahsilat makbuzu satış faturasına bağlı açılır (müşteri sabit, kalan tutar önerilir).
    Pencere modal değildir: simge durumuna küçültülebilir, büyütülebilir, ana ekranla birlikte kullanılır.
    """

    def __init__(
        self,
        parent,
        makbuz_turu: str,
        finans_hesap_id=None,
        cari_id=None,
        makbuz_id=None,
        on_kayit=None,
        *,
        virman_id=None,
        islem_turu=None,
        fatura_id=None,
    ):
        self.makbuz_turu = (makbuz_turu or "").strip().upper()
        if self.makbuz_turu not in ("TAHSILAT", "ODEME"):
            raise ValueError("makbuz_turu TAHSILAT veya ODEME olmalıdır.")
        self.tahsilat = self.makbuz_turu == "TAHSILAT"
        self._fatura_ozet: dict | None = None
        if fatura_id:
            if not self.tahsilat or virman_id or makbuz_id or islem_turu == "VIRMAN":
                raise ValueError("Satış faturasına yalnız yeni tahsilat makbuzu bağlanabilir.")
            self._fatura_ozet = FinansService.fatura_tahsilat_ozeti(int(fatura_id))
            if self._fatura_ozet["iptal"]:
                raise ValueError("İptal edilmiş faturaya tahsilat makbuzu bağlanamaz.")
            cari_id = self._fatura_ozet["cari_id"]
        super().__init__(parent)
        self.result = None
        self._odeme_sekilleri = TAHSILAT_MAKBUZ_SEKILLERI if self.tahsilat else ODEME_MAKBUZ_SEKILLERI
        self._varsayilan_hesap_id = finans_hesap_id
        self._sabit_cari_id = int(cari_id) if cari_id else None
        self._on_kayit = on_kayit

        self.makbuz_id: int | None = None
        self.makbuz = None
        self.mod = "yeni"
        self.satirlar: list[dict] = []
        self._duzenlenen_satir: int | None = None
        self._kirli = False
        self._yukleniyor = True
        self._kaydediliyor = False
        self._kilit_nedeni: str | None = None
        self._makbuz_no_manuel = False
        self._onerilen_no: str | None = None
        self._kayitli_no: str | None = None
        self._hesap_secenekleri: dict[str, dict] = {}
        self._kk_etiketleri: dict[int, str] = {}
        self._son_uyari_cari_id = None
        if (virman_id or islem_turu == "VIRMAN") and not self.tahsilat:
            raise ValueError("Cari virman yalnız tahsilat makbuzunda seçilebilir.")
        self.virman = False
        self._son_sekil: str | None = None
        self._virman_once: dict[str, Decimal | None] = {"musteri": None, "tedarikci": None}

        stil_uygula(root=self)
        self.title(self._pencere_basligi())
        self.configure(bg=ACIK_BG)
        self._pencereyi_boyutlandir()

        self._cari_kayitlarini_hazirla()
        self._arayuzu_kur()

        self.protocol("WM_DELETE_WINDOW", self.kapat)
        self.bind("<Control-s>", lambda _e: (self.kaydet(), "break")[1])
        self.bind("<Control-p>", lambda _e: (self.yazdir(), "break")[1])
        self.bind("<Escape>", self._esc_kapat)
        self.bind("<MouseWheel>", self._tekerlek, add="+")
        self._son_geometri = None
        self.bind("<Configure>", self._pencere_degisti, add="+")
        self.bind("<Unmap>", lambda e: self._aramalari_gizle() if e.widget is self else None, add="+")
        # Modal bir karttan (ör. cari kartı) açılırsa o kartın grab'ı bu pencereyi kilitlemesin
        self._onceki_grab = self.grab_current()
        if self._onceki_grab is not None:
            self.transient(self._onceki_grab.winfo_toplevel())
            self.grab_set()
            self.bind("<Destroy>", self._grab_geri_ver, add="+")

        if virman_id:
            kayit = CariVirmanMakbuzService.getir(int(virman_id))
            if kayit is None:
                self.destroy()
                raise ValueError("Cari virman makbuzu bulunamadı.")
            self._makbuzu_yukle(kayit)
        elif makbuz_id:
            makbuz = FinansService.kasa_makbuz_getir(int(makbuz_id))
            if makbuz is None:
                self.destroy()
                raise ValueError("Makbuz bulunamadı.")
            self._makbuzu_yukle(makbuz)
        else:
            self._yeni_makbuz_hazirla()
            if islem_turu == "VIRMAN":
                self.islem_turu_var.set(ISLEM_VIRMAN)
                self._islem_turu_degisti()
        self._yukleniyor = False
        self.after(60, self._ilk_odak)

    # ─── Pencere ─────────────────────────────────────────────────
    def _pencere_basligi(self) -> str:
        if self.virman:
            return "Cari Virman Makbuzu"
        return "Tahsilat Makbuzu" if self.tahsilat else "Ödeme Makbuzu"

    def _arama_kutulari(self) -> list:
        kutular = [self._cari_arama]
        if self.tahsilat:
            kutular += [self._v_musteri_arama, self._v_tedarikci_arama]
        return kutular

    def _aramalari_gizle(self):
        for kutu in self._arama_kutulari():
            kutu.gizle()

    def _pencereyi_boyutlandir(self):
        try:
            from ui_pencere import calisma_alani

            x, y, gen, yuk = calisma_alani(self)
        except Exception:
            x, y, gen, yuk = 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()
        genislik = max(640, min(1240, gen - 40))
        yukseklik = max(420, min(900, yuk - 40))
        self.minsize(min(640, gen), min(420, yuk))
        self.geometry(f"{genislik}x{yukseklik}+{x + (gen - genislik) // 2}+{y + max(0, (yuk - yukseklik) // 2)}")
        self.resizable(True, True)

    def _tekerlek(self, event):
        try:
            sinif = event.widget.winfo_class()
        except (AttributeError, tk.TclError):
            return None
        if sinif in ("Treeview", "Listbox", "Text", "TCombobox", "TSpinbox"):
            return None
        if self._kanvas.yview() == (0.0, 1.0):
            return None
        self._kanvas.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")
        return "break"

    def _pencere_degisti(self, event):
        if event.widget is not self:
            return
        geometri = (event.x, event.y, event.width, event.height)
        if self._son_geometri is not None and geometri != self._son_geometri:
            self._aramalari_gizle()
        self._son_geometri = geometri

    def _grab_geri_ver(self, event):
        if event.widget is not self:
            return
        onceki = self._onceki_grab
        try:
            if onceki is not None and onceki.winfo_exists():
                onceki.after_idle(onceki.grab_set)
        except tk.TclError:
            pass

    def _esc_kapat(self, _e=None):
        if any(k.acik_mi() for k in self._arama_kutulari()):
            return None
        self.kapat()
        return "break"

    # ─── Veri hazırlığı ──────────────────────────────────────────
    def _cari_kayitlarini_hazirla(self):
        self._cari_kayitlari: list[tuple[str, str, int]] = []
        self._musteri_kayitlari: list[tuple[str, str, int]] = []
        self._tedarikci_kayitlari: list[tuple[str, str, int]] = []
        self._cari_turleri: dict[int, str] = {}
        gorulen = set()
        for o in CariService.listele(hizli=True):
            self._cari_kaydi_ekle(o["cari"])
            gorulen.add(int(o["cari"].id))
        if self._sabit_cari_id and self._sabit_cari_id not in gorulen:
            cari = CariService.getir(self._sabit_cari_id)
            if cari is not None:
                self._cari_kaydi_ekle(cari, basa=True)

    def _cari_kaydi_ekle(self, cari, *, basa: bool = False):
        etiket = _cari_etiket(cari)
        kayit = (etiket, turkce_normalize(etiket), int(cari.id))
        self._cari_turleri[int(cari.id)] = cari.cari_turu or ""
        hedefler = [self._cari_kayitlari]
        if musteri_mi(cari.cari_turu):
            hedefler.append(self._musteri_kayitlari)
        if tedarikci_mi(cari.cari_turu):
            hedefler.append(self._tedarikci_kayitlari)
        for liste in hedefler:
            if basa:
                liste.insert(0, kayit)
            else:
                liste.append(kayit)

    def _cari_ekle_yoksa(self, cari_id: int | None, liste: list | None = None):
        """Listede olmayan (pasif / tür değişmiş) kayıtlı cariyi arama listesine ekler."""
        if not cari_id:
            return
        if not any(k[2] == cari_id for k in self._cari_kayitlari):
            cari = CariService.getir(int(cari_id))
            if cari is None:
                return
            self._cari_kaydi_ekle(cari, basa=True)
        if liste is not None and not any(k[2] == cari_id for k in liste):
            kayit = next(k for k in self._cari_kayitlari if k[2] == cari_id)
            liste.insert(0, kayit)

    # ─── Arayüz ─────────────────────────────────────────────────
    def _arayuzu_kur(self):
        kok = self
        # Başlık şeridi
        ust = tk.Frame(kok, bg=LACIVERT)
        ust.pack(side="top", fill="x")
        sol = tk.Frame(ust, bg=LACIVERT)
        sol.pack(side="left", fill="both", expand=True, padx=16, pady=10)
        self.baslik_lbl = tk.Label(sol, bg=LACIVERT, fg=BEYAZ, font=font(17, "bold", self), anchor="w")
        self.baslik_lbl.pack(anchor="w")
        self.alt_baslik_lbl = tk.Label(
            sol,
            bg=LACIVERT,
            fg=ACIK_SARI,
            font=font(10, root=self),
            anchor="w",
            text=self._alt_baslik_metni(),
        )
        self.alt_baslik_lbl.pack(anchor="w", pady=(2, 0))
        sag = tk.Frame(ust, bg=LACIVERT)
        sag.pack(side="right", padx=16, pady=10)
        self.durum_rozet = tk.Label(sag, font=font(10, "bold", self), padx=10, pady=3)
        self.durum_rozet.pack(anchor="e")
        self.no_buyuk_lbl = tk.Label(sag, bg=LACIVERT, fg=SARI, font=font(16, "bold", self))
        self.no_buyuk_lbl.pack(anchor="e", pady=(4, 0))
        tk.Frame(kok, bg=SARI, height=3).pack(side="top", fill="x")

        # Alt düğme çubuğu (her zaman görünür)
        alt = tk.Frame(kok, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        alt.pack(side="bottom", fill="x")
        self.mesaj_lbl = tk.Label(alt, bg=BEYAZ, fg=IKINCIL, font=font(9, root=self), anchor="w", justify="left")
        self.mesaj_lbl.pack(side="top", padx=12, pady=(4, 0), fill="x")
        alt.bind("<Configure>", lambda e: self.mesaj_lbl.configure(wraplength=max(200, e.width - 24)), add="+")
        self._dugme_kutusu = tk.Frame(alt, bg=BEYAZ)
        self._dugme_kutusu.pack(side="right", padx=8, pady=(4, 8))
        self.btn_kaydet = tk_buton(self._dugme_kutusu, "Kaydet  (Ctrl+S)", self.kaydet, rol="kaydet")
        self.btn_duzenle = tk_buton(self._dugme_kutusu, "Düzenle", self.duzenlemeye_gec, rol="duzenle")
        self.btn_vazgec = tk_buton(self._dugme_kutusu, "Vazgeç", self._vazgec, rol="geri")
        self.btn_iptal = tk_buton(self._dugme_kutusu, "İptal Et", self.iptal_et, rol="iptal")
        self.btn_yazdir = tk_buton(self._dugme_kutusu, "Yazdır / PDF / Word", self.yazdir, rol="yazdir")
        self.btn_yeni = tk_buton(self._dugme_kutusu, "Yeni Makbuz", self._yeni_pencere, rol="yeni")
        self.btn_kapat = tk_buton(self._dugme_kutusu, "Kapat", self.kapat, rol="geri")

        # Kaydırılabilir gövde
        orta = tk.Frame(kok, bg=ACIK_BG)
        orta.pack(side="top", fill="both", expand=True)
        self._kanvas = tk.Canvas(orta, bg=ACIK_BG, highlightthickness=0, bd=0)
        self._dikey = ttk.Scrollbar(orta, orient="vertical", command=self._kanvas.yview)
        self._yatay = ttk.Scrollbar(orta, orient="horizontal", command=self._kanvas.xview)
        self._kanvas.configure(yscrollcommand=self._dikey.set, xscrollcommand=self._yatay.set)
        self._kanvas.pack(side="left", fill="both", expand=True)
        self._ic = tk.Frame(self._kanvas, bg=ACIK_BG)
        self._ic_id = self._kanvas.create_window((0, 0), window=self._ic, anchor="nw")
        self._ic.bind("<Configure>", lambda _e: self._kaydirma_guncelle())
        self._kanvas.bind("<Configure>", self._kanvas_boyut)

        self._baslik_bolumu(self._ic)
        self._satir_bolumu(self._ic)
        if self.tahsilat:
            self._virman_bolumu(self._ic)

    def _alt_baslik_metni(self) -> str:
        if self.virman:
            return "Cari virman — müşteriden alacak ile tedarikçiye borç aynı tutarda mahsup edilir; kasa/banka hareketi yok."
        if self.tahsilat:
            return "Nakit, gelen havale ve kredi kartıyla (POS) tahsilat — birden fazla satır girilebilir."
        return "Nakit, gönderilen havale ve şirket kredi kartıyla ödeme — birden fazla satır girilebilir."

    def _kanvas_boyut(self, event):
        self._kanvas.itemconfigure(self._ic_id, width=max(event.width, self._ic.winfo_reqwidth()))
        self._kaydirma_guncelle()

    def _kaydirma_guncelle(self):
        self._kanvas.configure(scrollregion=self._kanvas.bbox("all"))
        yukseklik, genislik = self._kanvas.winfo_height(), self._kanvas.winfo_width()
        dikey = self._ic.winfo_reqheight() > yukseklik > 1
        if dikey and not self._dikey.winfo_ismapped():
            self._dikey.pack(side="right", fill="y", before=self._kanvas)
        elif not dikey and self._dikey.winfo_ismapped():
            self._dikey.pack_forget()
            self._kanvas.yview_moveto(0)
        yatay = self._ic.winfo_reqwidth() > genislik > 1
        if yatay and not self._yatay.winfo_ismapped():
            self._yatay.pack(side="bottom", fill="x", before=self._kanvas)
        elif not yatay and self._yatay.winfo_ismapped():
            self._yatay.pack_forget()
            self._kanvas.xview_moveto(0)

    def _panel(self, parent, baslik: str) -> tk.Frame:
        dis = tk.Frame(parent, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
        dis.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(dis, text=baslik, bg=BEYAZ, fg=LACIVERT, font=font(11, "bold", self), anchor="w").pack(
            fill="x", padx=12, pady=(8, 0)
        )
        tk.Frame(dis, bg=SARI, height=2).pack(fill="x", padx=12, pady=(4, 0))
        ic = tk.Frame(dis, bg=BEYAZ)
        ic.pack(fill="x", padx=12, pady=10)
        return ic

    def _etiket(self, parent, metin, satir, sutun):
        lbl = tk.Label(parent, text=metin, bg=BEYAZ, fg=METIN, font=font(10, root=self), anchor="w")
        lbl.grid(row=satir, column=sutun, sticky="w", padx=(0, 8), pady=5)
        return lbl

    def _baslik_bolumu(self, parent):
        p = self._panel(parent, "Makbuz Bilgileri")
        self._baslik_dis = p.master
        p.columnconfigure(1, weight=3)
        p.columnconfigure(3, weight=2)

        # Tab sırası oluşturma sırasıdır: tarih → cari → şube → açıklama → satır alanları
        self.islem_turu_var = tk.StringVar(value=ISLEM_TAHSILAT)
        if self.tahsilat:
            self._etiket(p, "İşlem türü", 0, 0)
            self.islem_turu_cb = ttk.Combobox(
                p,
                textvariable=self.islem_turu_var,
                values=(ISLEM_TAHSILAT, ISLEM_VIRMAN),
                state="readonly",
                width=18,
                takefocus=0,
            )
            self.islem_turu_cb.grid(row=0, column=1, sticky="w", pady=5)
            self.islem_turu_cb.bind("<<ComboboxSelected>>", lambda _e: self._islem_turu_degisti(), add="+")
            self.islem_ipucu_lbl = tk.Label(p, bg=BEYAZ, fg=IKINCIL, font=font(8, root=self), anchor="w")
            self.islem_ipucu_lbl.grid(row=0, column=2, columnspan=2, sticky="w", pady=5)

        self._etiket(p, "Makbuz No", 1, 0)
        no_kutu = tk.Frame(p, bg=BEYAZ)
        no_kutu.grid(row=1, column=1, sticky="ew", pady=5)
        self.makbuz_no_var = tk.StringVar()
        self.makbuz_no_entry = ttk.Entry(
            no_kutu, textvariable=self.makbuz_no_var, width=18, state="readonly", takefocus=0
        )
        self.makbuz_no_entry.pack(side="left")
        self.btn_yeni_no = ttk.Button(no_kutu, text="Yeni No", width=9, command=self.yeni_no_gir, takefocus=0)
        self.btn_yeni_no.pack(side="left", padx=(6, 0))
        self.no_ipucu_lbl = tk.Label(no_kutu, bg=BEYAZ, fg=IKINCIL, font=font(8, root=self))
        self.no_ipucu_lbl.pack(side="left", padx=(8, 0))

        self._etiket(p, "Tarih *", 1, 2)
        tarih_kutu = tk.Frame(p, bg=BEYAZ)
        tarih_kutu.grid(row=1, column=3, sticky="w", pady=5)
        self.tarih_var = tk.StringVar(value=date.today().strftime("%d.%m.%Y"))
        self.tarih_entry = ttk.Entry(tarih_kutu, textvariable=self.tarih_var, width=12)
        self.tarih_entry.pack(side="left")
        self.tarih_takvim = takvim_butonu(tarih_kutu, self.tarih_entry)
        self.tarih_takvim.configure(takefocus=0)

        self.cari_etiket_lbl = self._etiket(p, "Cari hesap *" + (" (ödeyen)" if self.tahsilat else " (alacaklı)"), 2, 0)
        cari_kutu = tk.Frame(p, bg=BEYAZ)
        cari_kutu.grid(row=2, column=1, sticky="ew", pady=5)
        self._cari_kutu = cari_kutu
        cari_kutu.columnconfigure(0, weight=1)
        self.cari_var = tk.StringVar()
        self.cari_entry = ttk.Entry(cari_kutu, textvariable=self.cari_var, font=isim_fontu(self))
        self.cari_entry.grid(row=0, column=0, sticky="ew")
        self.cari_ipucu_lbl = tk.Label(
            cari_kutu,
            bg=BEYAZ,
            fg=IKINCIL,
            font=font(8, root=self),
            anchor="w",
            justify="left",
            wraplength=340,
            text="Kod veya ünvanın herhangi bir yerinden yazın; ↓ / Enter veya fareyle seçin.",
        )
        self.cari_ipucu_lbl.grid(row=1, column=0, sticky="w", pady=(2, 0))
        self._cari_arama = _CariAramaKutusu(
            self, self.cari_entry, self.cari_var, self._cari_kayitlari, self._cari_degisti
        )

        self.bakiye_etiket_lbl = self._etiket(p, "Güncel bakiye", 2, 2)
        self.bakiye_lbl = tk.Label(p, text="—", bg=BEYAZ, fg=IKINCIL, font=font(13, "bold", self), anchor="w")
        self.bakiye_lbl.grid(row=2, column=3, sticky="w", pady=5)

        self._etiket(p, "Şube *", 3, 0)
        from sube_ui import sube_secim_hazirla

        self.sube, self._sube_map = sube_secim_hazirla(p)
        self.sube.grid(row=3, column=1, sticky="w", pady=5)
        self.sube.bind("<<ComboboxSelected>>", lambda _e: self._kirlet(), add="+")

        self._etiket(p, "Açıklama", 3, 2)
        self.aciklama_var = tk.StringVar()
        self.aciklama_entry = ttk.Entry(p, textvariable=self.aciklama_var)
        self.aciklama_entry.grid(row=3, column=3, sticky="ew", pady=5)

        self.kilit_lbl = tk.Label(p, bg=BEYAZ, fg=UYARI, font=font(9, "bold", self), anchor="w", justify="left")
        self.kilit_lbl.grid(row=4, column=0, columnspan=4, sticky="ew")
        self.fatura_bilgi_lbl = tk.Label(
            p, bg=ACIK_SARI, fg=KOYU_LACIVERT, font=font(9, "bold", self), anchor="w", justify="left", padx=8, pady=4
        )
        self.fatura_bilgi_lbl.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(4, 0))
        self.fatura_bilgi_lbl.grid_remove()
        p.bind(
            "<Configure>",
            lambda e: [
                w.configure(wraplength=max(300, e.width - 20)) for w in (self.kilit_lbl, self.fatura_bilgi_lbl)
            ],
            add="+",
        )

        for var in (self.tarih_var, self.aciklama_var):
            var.trace_add("write", lambda *_: self._kirlet())
        for entry in (self.tarih_entry, self.aciklama_entry):
            entry.bind("<Return>", self._sonraki_alan, add="+")

    def _satir_bolumu(self, parent):
        p = self._panel(parent, "Tahsilat Satırları" if self.tahsilat else "Ödeme Satırları")
        self._satir_dis = p.master
        for c in (1, 3, 5):
            p.columnconfigure(c, weight=1)

        self._etiket(p, "Ödeme yöntemi", 0, 0)
        self.sekil_var = tk.StringVar()
        self.sekil_cb = ttk.Combobox(
            p, textvariable=self.sekil_var, values=self._sekil_listesi(), state="readonly", width=self._sekil_genisligi()
        )
        self.sekil_cb.grid(row=0, column=1, sticky="ew", pady=5, padx=(0, 12))
        self.sekil_cb.bind("<<ComboboxSelected>>", lambda _e: self._sekil_degisti(), add="+")

        self.hesap_etiket_lbl = tk.Label(p, text="Hesap", bg=BEYAZ, fg=METIN, font=font(10, root=self), anchor="w")
        self.hesap_etiket_lbl.grid(row=0, column=2, sticky="w", padx=(0, 8), pady=5)
        self.hesap_var = tk.StringVar()
        self.hesap_cb = ttk.Combobox(p, textvariable=self.hesap_var, state="readonly", width=28)
        self.hesap_cb.grid(row=0, column=3, columnspan=3, sticky="ew", pady=5)

        self.kart_kutu = tk.Frame(p, bg=BEYAZ)
        self.kart_kutu.grid(row=1, column=0, columnspan=6, sticky="ew")
        self.kart_tipi_lbl = tk.Label(self.kart_kutu, text="Kart tipi", bg=BEYAZ, fg=METIN, font=font(10, root=self))
        self.kart_tipi_lbl.pack(side="left", padx=(0, 8), pady=5)
        self.kart_tipi_var = tk.StringVar(value="Kredi Kartı")
        self.kart_tipi_cb = ttk.Combobox(
            self.kart_kutu, textvariable=self.kart_tipi_var, values=tuple(KART_TIPLERI), state="readonly", width=14
        )
        self.kart_tipi_cb.pack(side="left", padx=(0, 16))
        self.kart_tipi_cb.bind("<<ComboboxSelected>>", lambda _e: self._kart_tipi_degisti(), add="+")
        self.taksit_lbl = tk.Label(self.kart_kutu, text="Taksit", bg=BEYAZ, fg=METIN, font=font(10, root=self))
        self.taksit_lbl.pack(side="left", padx=(0, 8))
        self.taksit_var = tk.StringVar(value="1")
        self.taksit_sb = ttk.Spinbox(self.kart_kutu, from_=1, to=12, textvariable=self.taksit_var, width=5)
        self.taksit_sb.pack(side="left")
        self.kart_bilgi_lbl = tk.Label(self.kart_kutu, bg=BEYAZ, fg=IKINCIL, font=font(8, root=self))
        self.kart_bilgi_lbl.pack(side="left", padx=(12, 0))

        self._etiket(p, "Satır tarihi", 2, 0)
        satir_tarih_kutu = tk.Frame(p, bg=BEYAZ)
        satir_tarih_kutu.grid(row=2, column=1, sticky="w", pady=5)
        self.satir_tarih_var = tk.StringVar(value=date.today().strftime("%d.%m.%Y"))
        self.satir_tarih_entry = ttk.Entry(satir_tarih_kutu, textvariable=self.satir_tarih_var, width=12)
        self.satir_tarih_entry.pack(side="left")
        self.satir_takvim = takvim_butonu(satir_tarih_kutu, self.satir_tarih_entry)
        self.satir_takvim.configure(takefocus=0)

        self._etiket(p, "Tutar (TL) *", 2, 2)
        self.tutar_var = tk.StringVar()
        self.tutar_entry = ttk.Entry(p, textvariable=self.tutar_var, width=16, justify="right")
        self.tutar_entry.grid(row=2, column=3, sticky="w", pady=5)
        tutar_alani(self.tutar_entry, self.tutar_var)

        self._etiket(p, "Satır açıklaması", 2, 4)
        self.satir_aciklama_var = tk.StringVar()
        self.satir_aciklama_entry = ttk.Entry(p, textvariable=self.satir_aciklama_var)
        self.satir_aciklama_entry.grid(row=2, column=5, sticky="ew", pady=5)

        satir_btn = tk.Frame(p, bg=BEYAZ)
        satir_btn.grid(row=3, column=0, columnspan=6, sticky="ew", pady=(4, 8))
        self.btn_satir_ekle = tk_buton(satir_btn, "Satırı Ekle  (Enter)", self.satir_ekle, rol="yeni")
        self.btn_satir_ekle.pack(side="left")
        self.btn_satir_temizle = tk_buton(satir_btn, "Satır Alanlarını Temizle", self._satir_alanlarini_temizle, rol="geri")
        self.btn_satir_temizle.pack(side="left", padx=8)
        self.btn_satir_temizle.configure(takefocus=0)

        tablo_kutu = tk.Frame(p, bg=BEYAZ)
        tablo_kutu.grid(row=4, column=0, columnspan=6, sticky="nsew")
        tablo_kutu.columnconfigure(0, weight=1)
        self.tablo = ttk.Treeview(
            tablo_kutu,
            columns=("tarih", "sekil", "hesap", "kart", "tutar", "aciklama"),
            show="headings",
            selectmode="browse",
            height=6,
            takefocus=0,
        )
        _tablo_stili(self.tablo)
        stil = ttk.Style(self.tablo)
        stil.configure("MakbuzSatir.Treeview", font=font(11, "bold", self), rowheight=30)
        stil.configure("MakbuzSatir.Treeview.Heading", font=font(10, "bold", self), foreground=LACIVERT)
        stil.map(
            "MakbuzSatir.Treeview", background=[("selected", ACIK_SARI)], foreground=[("selected", KOYU_LACIVERT)]
        )
        self.tablo.configure(style="MakbuzSatir.Treeview")
        for k, b, w, a in (
            ("tarih", "Tarih", 90, "w"),
            ("sekil", "Ödeme yöntemi", 170, "w"),
            ("hesap", "Hesap / Kart", 200, "w"),
            ("kart", "Kart / Taksit", 130, "w"),
            ("tutar", "Tutar", 110, "e"),
            ("aciklama", "Açıklama", 180, "w"),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, minwidth=60, anchor=a, stretch=True)
        tablo_kaydir = ttk.Scrollbar(tablo_kutu, orient="vertical", command=self.tablo.yview)
        self.tablo.configure(yscrollcommand=tablo_kaydir.set)
        self.tablo.grid(row=0, column=0, sticky="nsew")
        tablo_kaydir.grid(row=0, column=1, sticky="ns")
        self.tablo.bind("<Double-1>", lambda _e: self.satir_duzenle())
        self.tablo.bind("<Delete>", lambda _e: self.satir_sil())

        tablo_alt = tk.Frame(p, bg=BEYAZ)
        tablo_alt.grid(row=5, column=0, columnspan=6, sticky="ew", pady=(8, 0))
        self.btn_satir_duzenle = ttk.Button(tablo_alt, text="Seçili Satırı Düzenle", command=self.satir_duzenle, takefocus=0)
        self.btn_satir_duzenle.pack(side="left")
        self.btn_satir_sil = ttk.Button(tablo_alt, text="Seçili Satırı Sil", command=self.satir_sil, takefocus=0)
        self.btn_satir_sil.pack(side="left", padx=6)
        self.toplam_lbl = tk.Label(tablo_alt, text="Toplam: 0,00 TL", bg=BEYAZ, fg=LACIVERT, font=font(15, "bold", self))
        self.toplam_lbl.pack(side="right")
        tk.Frame(parent, bg=ACIK_BG, height=10).pack(fill="x")

        for entry in (self.satir_tarih_entry, self.tutar_entry, self.satir_aciklama_entry):
            entry.bind("<Return>", lambda _e: (self.satir_ekle(), "break")[1], add="+")
        for w in (self.sekil_cb, self.hesap_cb, self.kart_tipi_cb, self.taksit_sb):
            w.bind("<Return>", self._sonraki_alan, add="+")
        self.btn_satir_ekle.bind("<Return>", lambda _e: (self.satir_ekle(), "break")[1])

    def _virman_bolumu(self, parent):
        p = self._panel(parent, "Cari Virman — Müşteri Alacağı ile Tedarikçi Borcunun Mahsubu")
        self._virman_dis = p.master
        p.columnconfigure(1, weight=3)
        p.columnconfigure(3, weight=2)
        ipucu = "Kod veya ünvanın herhangi bir yerinden yazın; ↓ / Enter veya fareyle seçin."

        def cari_alani(satir, etiket, liste, on_secim):
            self._etiket(p, etiket, satir, 0)
            kutu = tk.Frame(p, bg=BEYAZ)
            kutu.grid(row=satir, column=1, sticky="ew", pady=5)
            kutu.columnconfigure(0, weight=1)
            var = tk.StringVar()
            entry = ttk.Entry(kutu, textvariable=var, font=isim_fontu(self))
            entry.grid(row=0, column=0, sticky="ew")
            tk.Label(kutu, text=ipucu, bg=BEYAZ, fg=IKINCIL, font=font(8, root=self), anchor="w").grid(
                row=1, column=0, sticky="w", pady=(2, 0)
            )
            etiket_lbl = self._etiket(p, "İşlem öncesi bakiye", satir, 2)
            bakiye = tk.Label(p, text="—", bg=BEYAZ, fg=IKINCIL, font=font(12, "bold", self), anchor="w")
            bakiye.grid(row=satir, column=3, sticky="w", pady=5)
            arama = _CariAramaKutusu(self, entry, var, liste, on_secim)
            return var, entry, arama, bakiye, etiket_lbl

        self._etiket(p, "Ödeme yöntemi", 0, 0)
        self.v_sekil_var = tk.StringVar(value=CARI_VIRMAN_SEKLI)
        self.v_sekil_cb = ttk.Combobox(
            p, textvariable=self.v_sekil_var, values=self._sekil_listesi(), state="readonly",
            width=self._sekil_genisligi(), takefocus=0,
        )
        self.v_sekil_cb.grid(row=0, column=1, sticky="w", pady=5)
        self.v_sekil_cb.bind("<<ComboboxSelected>>", lambda _e: self._virmandan_cik(), add="+")
        (
            self.v_musteri_var,
            self.v_musteri_entry,
            self._v_musteri_arama,
            self.v_musteri_bakiye_lbl,
            self.v_musteri_bakiye_etiket,
        ) = cari_alani(1, "Tahsilat yapılan müşteri *", self._musteri_kayitlari, lambda _i: self._virman_cari_degisti())
        (
            self.v_tedarikci_var,
            self.v_tedarikci_entry,
            self._v_tedarikci_arama,
            self.v_tedarikci_bakiye_lbl,
            self.v_tedarikci_bakiye_etiket,
        ) = cari_alani(2, "Ödeme yapılan tedarikçi *", self._tedarikci_kayitlari, lambda _i: self._virman_cari_degisti())

        self._etiket(p, "Virman tutarı (TL) *", 3, 0)
        self.v_tutar_var = tk.StringVar()
        self.v_tutar_entry = ttk.Entry(p, textvariable=self.v_tutar_var, width=16, justify="right")
        self.v_tutar_entry.grid(row=3, column=1, sticky="w", pady=5)
        tutar_alani(self.v_tutar_entry, self.v_tutar_var)
        self._etiket(p, "Virman sonrası", 3, 2)
        self.v_sonra_lbl = tk.Label(p, text="—", bg=BEYAZ, fg=IKINCIL, font=font(10, "bold", self), anchor="w", justify="left")
        self.v_sonra_lbl.grid(row=3, column=3, sticky="w", pady=5)
        self.v_bilgi_lbl = tk.Label(
            p, text=VIRMAN_BILGI, bg=BEYAZ, fg=LACIVERT, font=font(9, root=self), anchor="w", justify="left"
        )
        self.v_bilgi_lbl.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        p.bind("<Configure>", lambda e: self.v_bilgi_lbl.configure(wraplength=max(300, e.width - 20)), add="+")

        self.v_tutar_var.trace_add("write", lambda *_: (self._virman_onizleme(), self._kirlet()))
        self.v_tutar_entry.bind("<Return>", self._sonraki_alan, add="+")
        self._virman_dis.pack_forget()

    # ─── Cari virman ────────────────────────────────────────────
    def _sekil_listesi(self) -> tuple:
        if self.tahsilat and not self._fatura_ozet:
            return tuple(self._odeme_sekilleri) + (CARI_VIRMAN_SEKLI, KK_ODEME_SEKLI)
        return tuple(self._odeme_sekilleri)

    def _sekil_genisligi(self) -> int:
        return max(24, max(len(s) for s in self._sekil_listesi()) + 2)

    def _kk_odemeye_gec(self):
        """Ödeme yöntemi listesinden müşteriden tedarikçiye kredi kartı ile ödeme seçildi."""
        self.sekil_var.set(self._son_sekil or self._odeme_sekilleri[0])
        self._sekil_degisti()
        if self.mod != "yeni" or self._fatura_ozet:
            return
        if self.satirlar:
            messagebox.showinfo(
                "Kredi Kartı ile Ödeme",
                "Müşteriden tedarikçiye kredi kartı ile ödeme için önce eklenen tahsilat satırlarını kaldırın.",
                parent=self,
            )
            return
        self.kk_odeme_ac()

    def kk_odeme_ac(self):
        """Mevcut KK çekim fişini makbuzdaki müşteri, tarih ve tutarla açar; kayıttan sonra makbuzu kapatır."""
        from app import KkCekimiDialog

        cari_id = self._cari_arama.secili_id
        musteri_id = cari_id if cari_id and musteri_mi(self._cari_turleri.get(cari_id)) else None
        try:
            tarih = _tarih_oku(self.tarih_var.get())
        except ValueError:
            tarih = None
        try:
            tutar = _tutar_oku(self.tutar_var.get()) if self.tutar_var.get().strip() else None
        except ValueError:
            tutar = None
        dlg = KkCekimiDialog(self, musteri_id=musteri_id, tarih=tarih, tutar=tutar)
        if dlg.winfo_exists():
            self.wait_window(dlg)
        if not dlg.result:
            return None
        if self._on_kayit:
            self._on_kayit(dlg.result)
        self._kirli = False
        self.kapat()
        return dlg.result

    def _virmana_gec(self):
        """Ödeme yöntemi listesinden CARİ VİRMAN seçildi."""
        self.sekil_var.set(self._son_sekil or self._odeme_sekilleri[0])
        self._sekil_degisti()
        if self.mod != "yeni" or self._fatura_ozet:
            return
        if self.satirlar:
            messagebox.showinfo(
                "Cari Virman",
                "Cari virmana geçmek için önce eklenen tahsilat satırlarını kaldırın.",
                parent=self,
            )
            return
        self.islem_turu_var.set(ISLEM_VIRMAN)
        self._islem_turu_degisti()

    def _virmandan_cik(self):
        """Virman panelindeki Ödeme yöntemi listesinden başka bir yöntem seçildi."""
        secim = self.v_sekil_var.get()
        self.v_sekil_var.set(CARI_VIRMAN_SEKLI)
        if secim == CARI_VIRMAN_SEKLI or self.mod != "yeni":
            return
        self.islem_turu_var.set(ISLEM_TAHSILAT)
        self._islem_turu_degisti()
        self.sekil_var.set(secim)
        self._sekil_degisti()

    def _islem_turu_degisti(self):
        virman = self.islem_turu_var.get() == ISLEM_VIRMAN
        if virman == self.virman:
            return
        if self.mod != "yeni":
            self.islem_turu_var.set(ISLEM_VIRMAN if self.virman else ISLEM_TAHSILAT)
            return
        self.virman = virman
        if virman and self._sabit_cari_id:
            tur = self._cari_turleri.get(self._sabit_cari_id)
            if musteri_mi(tur) and not self._v_musteri_arama.secili_id:
                self._v_musteri_arama.secimi_ayarla(self._sabit_cari_id)
            elif tedarikci_mi(tur) and not self._v_tedarikci_arama.secili_id:
                self._v_tedarikci_arama.secimi_ayarla(self._sabit_cari_id)
        self._virman_gorunumu()
        self._virman_bakiyelerini_guncelle()
        self._mod_uygula()
        self.after_idle(self._ilk_odak)

    def _virman_gorunumu(self):
        self._aramalari_gizle()
        cari_satiri = (self.cari_etiket_lbl, self._cari_kutu, self.bakiye_etiket_lbl, self.bakiye_lbl)
        if self.virman:
            for w in cari_satiri:
                w.grid_remove()
            self._satir_dis.pack_forget()
            self._virman_dis.pack(fill="x", padx=12, pady=(10, 0), after=self._baslik_dis)
        else:
            for w in cari_satiri:
                w.grid()
            self._virman_dis.pack_forget()
            self._satir_dis.pack(fill="x", padx=12, pady=(10, 0), after=self._baslik_dis)
        self.islem_ipucu_lbl.configure(
            text="Kasa / banka hareketi yok; iki cari hesap birlikte güncellenir." if self.virman else ""
        )
        self.alt_baslik_lbl.configure(text=self._alt_baslik_metni())

    def _virman_cari_degisti(self):
        self._virman_bakiyelerini_guncelle()
        self._kirlet()

    def _virman_bakiyelerini_guncelle(self):
        kayitli = self.makbuz if (self.virman and self.makbuz is not None) else None
        acik_kayit = kayitli is not None and kayitli.durum != "IPTAL"
        for anahtar, arama, lbl, etiket_lbl, kayitli_id in (
            ("musteri", self._v_musteri_arama, self.v_musteri_bakiye_lbl, self.v_musteri_bakiye_etiket,
             getattr(kayitli, "musteri_id", None)),
            ("tedarikci", self._v_tedarikci_arama, self.v_tedarikci_bakiye_lbl, self.v_tedarikci_bakiye_etiket,
             getattr(kayitli, "tedarikci_id", None)),
        ):
            cari_id = arama.secili_id
            # İptal edilmiş virmanda hareketler geri alınmıştır: gösterilen güncel bakiyedir
            etiket_lbl.configure(text="Güncel bakiye" if kayitli is not None and not acik_kayit else "İşlem öncesi bakiye")
            if not cari_id:
                self._virman_once[anahtar] = None
                lbl.configure(text="—", fg=IKINCIL)
                continue
            try:
                bakiye = Decimal(str(FinansService.cari_bakiye_ozeti(int(cari_id))["bakiye"]))
            except Exception as hata:  # noqa: BLE001
                self._virman_once[anahtar] = None
                lbl.configure(text=f"Bakiye okunamadı: {hata}", fg=UYARI)
                continue
            # Kayıtlı açık virmanda güncel bakiye virmanı içerir; işlem öncesi = güncel + virman tutarı
            if acik_kayit and int(cari_id) == int(kayitli_id or 0):
                bakiye += Decimal(str(kayitli.tutar or 0))
            self._virman_once[anahtar] = bakiye
            yazi, renk = _bakiye_yazisi(bakiye)
            lbl.configure(text=yazi, fg=renk)
        self._virman_onizleme()

    def _virman_tutari(self) -> Decimal | None:
        try:
            return _tutar_oku(self.v_tutar_var.get())
        except ValueError:
            return None

    def _virman_onizleme(self):
        tutar = self._virman_tutari()
        once_m, once_t = self._virman_once["musteri"], self._virman_once["tedarikci"]
        if tutar is None or (once_m is None and once_t is None):
            self.v_sonra_lbl.configure(text="—", fg=IKINCIL)
            return
        parcalar = []
        if once_m is not None:
            parcalar.append(f"Müşteri: {_bakiye_yazisi(once_m - tutar)[0]}")
        if once_t is not None:
            parcalar.append(f"Tedarikçi: {_bakiye_yazisi(once_t - tutar)[0]}")
        self.v_sonra_lbl.configure(text="\n".join(parcalar), fg=LACIVERT)

    def virman_bakiye_metinleri(self) -> tuple[str, str, str]:
        return (
            self.v_musteri_bakiye_lbl.cget("text"),
            self.v_tedarikci_bakiye_lbl.cget("text"),
            self.v_sonra_lbl.cget("text"),
        )

    def _virman_asim_onayi(self, tutar: Decimal) -> bool:
        """Tutar müşterinin borcunu veya tedarikçiye borcu aşıyorsa taraf alacaklıya döner; kullanıcıya sorulur."""
        uyarilar = []
        for ad, once in (("Müşteri", self._virman_once["musteri"]), ("Tedarikçi", self._virman_once["tedarikci"])):
            if once is not None and tutar > once:
                uyarilar.append(
                    f"• {ad}: işlem öncesi {_bakiye_yazisi(once)[0]} → virman sonrası {_bakiye_yazisi(once - tutar)[0]}"
                )
        if not uyarilar:
            return True
        return messagebox.askyesno(
            "Cari Virman",
            "Virman tutarı işlem öncesi bakiyeyi aşıyor:\n\n" + "\n".join(uyarilar) + "\n\nYine de kaydedilsin mi?",
            icon="warning",
            parent=self,
        )

    def _sonraki_alan(self, event):
        try:
            event.widget.tk_focusNext().focus_set()
        except (tk.TclError, AttributeError):
            pass
        return "break"

    def _ilk_odak(self):
        if not self.winfo_exists():
            return
        if self.mod == "goruntule":
            self.btn_kapat.focus_set()
        elif self.virman:
            if not self._v_musteri_arama.secili_id:
                self.v_musteri_entry.focus_set()
            elif not self._v_tedarikci_arama.secili_id:
                self.v_tedarikci_entry.focus_set()
            else:
                self.v_tutar_entry.focus_set()
        elif self._sabit_cari_id or self._cari_arama.secili_id:
            self.sekil_cb.focus_set()
        else:
            self.cari_entry.focus_set()

    # ─── Mod ve durum ────────────────────────────────────────────
    def _duzenlenebilir(self) -> bool:
        return self.mod in ("yeni", "duzenle")

    def _mod_uygula(self):
        tur = "CARİ VİRMAN" if self.virman else ("TAHSİLAT" if self.tahsilat else "ÖDEME")
        no = (self.makbuz_no_var.get() or "").strip()
        iptal = self.makbuz is not None and self.makbuz.durum == "IPTAL"
        if self.mod == "yeni":
            baslik = f"YENİ {tur} MAKBUZU"
            rozet = ("YENİ · HENÜZ KAYDEDİLMEDİ", SARI, KOYU_LACIVERT)
        elif self.mod == "duzenle":
            baslik = f"{tur} MAKBUZU — DÜZENLENİYOR"
            rozet = ("KAYITLI MAKBUZ · DÜZENLENİYOR", SARI, KOYU_LACIVERT)
        elif iptal:
            baslik = f"{tur} MAKBUZU"
            rozet = ("İPTAL EDİLMİŞ MAKBUZ", UYARI, BEYAZ)
        else:
            baslik = f"{tur} MAKBUZU"
            rozet = ("KAYITLI MAKBUZ", BASARI, BEYAZ)
        self.baslik_lbl.configure(text=baslik)
        self.durum_rozet.configure(text=rozet[0], bg=rozet[1], fg=rozet[2])
        self.no_buyuk_lbl.configure(text=no or ("Numarasız" if self.mod != "yeni" else ""))
        pencere = self._pencere_basligi()
        if self.mod == "yeni":
            self.title(f"Yeni {pencere}")
        else:
            ek = no or (self.makbuz.belge_no if self.makbuz is not None else "")
            self.title(f"{pencere} — {ek}" + (" (İptal)" if iptal else ""))

        acik = self._duzenlenebilir()
        durum = "normal" if acik else "disabled"
        for w in (self.tarih_entry, self.aciklama_entry, self.satir_tarih_entry, self.tutar_entry, self.satir_aciklama_entry):
            w.configure(state=durum)
        self.cari_entry.configure(
            state="disabled" if (not acik or self._sabit_cari_id or self._fatura_ozet) else "normal"
        )
        for cb in (self.sekil_cb, self.hesap_cb, self.kart_tipi_cb, self.sube):
            cb.configure(state="readonly" if acik else "disabled")
        self.taksit_sb.configure(state="normal" if acik else "disabled")
        for b in (self.tarih_takvim, self.satir_takvim, self.btn_satir_duzenle, self.btn_satir_sil):
            b.configure(state=durum)
        self.btn_yeni_no.configure(state="normal" if acik else "disabled")
        for b in (self.btn_satir_ekle, self.btn_satir_temizle):
            b.configure(state=durum)
        if acik:
            self._kart_alanlarini_ayarla()
        if self.tahsilat:
            tur_durumu = "readonly" if self.mod == "yeni" and not self._fatura_ozet else "disabled"
            self.islem_turu_cb.configure(state=tur_durumu)
            self.v_sekil_cb.configure(state=tur_durumu)
            for w in (self.v_musteri_entry, self.v_tedarikci_entry, self.v_tutar_entry):
                w.configure(state=durum)

        from database.access import yetki_var

        yazabilir = yetki_var("finans_duzenleme")
        for b in self._dugme_kutusu.winfo_children():
            b.pack_forget()
        gorunen = []
        if self.mod == "yeni":
            gorunen = [self.btn_kaydet, self.btn_yazdir]
            self.btn_kaydet.configure(text="Kaydet  (Ctrl+S)")
        elif self.mod == "duzenle":
            gorunen = [self.btn_kaydet, self.btn_vazgec, self.btn_yazdir]
            self.btn_kaydet.configure(text="Değişiklikleri Kaydet")
        else:
            if not iptal and not self._kilit_nedeni and yazabilir:
                gorunen += [self.btn_duzenle, self.btn_iptal]
            gorunen += [self.btn_yazdir, self.btn_yeni]
        gorunen.append(self.btn_kapat)
        for b in gorunen:
            b.pack(side="left", padx=4)
        self.btn_kaydet.configure(state="normal" if yazabilir else "disabled")

        kilit = ""
        if iptal and self.virman:
            kilit = (
                "Bu cari virman iptal edilmiştir; müşteri ve tedarikçi hareketleri birlikte geri alınmıştır. "
                "Yalnız görüntülenebilir."
            )
        elif iptal:
            kilit = "Bu makbuz iptal edilmiştir; cari ve finans etkileri geri alınmıştır. Yalnız görüntülenebilir."
        elif self._kilit_nedeni:
            kilit = self._kilit_nedeni
        self.kilit_lbl.configure(text=kilit)
        if self.mod == "yeni":
            self.no_ipucu_lbl.configure(
                text=("Elle girildi" if self._makbuz_no_manuel else "Otomatik; kayıtta kesinleşir")
                if self.tahsilat or self._makbuz_no_manuel
                else "İsteğe bağlı"
            )
        elif self.mod == "duzenle":
            self.no_ipucu_lbl.configure(text="Elle değiştirildi" if self._makbuz_no_manuel else "Kayıtlı numara")
        else:
            self.no_ipucu_lbl.configure(text="")
        self._fatura_bilgisini_yaz()

    def fatura_bilgi_metni(self) -> str:
        oz = self._fatura_ozet
        if not oz:
            return ""
        durum = "İptal edilmiş fatura" if oz["iptal"] else ("Onaylı" if oz["onayli"] else "Onaysız (taslak)")
        try:
            from makbuz_cikti import firma_bilgisi

            firma = (firma_bilgisi().get("unvan") or "").strip()
        except Exception:
            firma = ""
        satirlar = [
            f"Bağlı satış faturası: {oz['fatura_no']} ({durum})" + (f" · Firma: {firma}" if firma else ""),
            f"Müşteri: {oz['cari_kodu']} — {oz['cari_unvan']}",
            f"Fatura toplamı {_para(oz['genel_toplam'])} · Tahsil edilen {_para(oz['tahsil_edilen'])} · "
            f"Faturanın kalan ödenmemiş tutarı {_para(oz['kalan'])}",
        ]
        return "\n".join(satirlar)

    def _fatura_bilgisini_yaz(self):
        metin = self.fatura_bilgi_metni()
        if metin:
            self.fatura_bilgi_lbl.configure(text=metin)
            self.fatura_bilgi_lbl.grid()
        else:
            self.fatura_bilgi_lbl.grid_remove()

    def _fatura_ozetini_yenile(self, fatura_id):
        try:
            self._fatura_ozet = FinansService.fatura_tahsilat_ozeti(int(fatura_id)) if fatura_id else None
        except ValueError:
            self._fatura_ozet = None

    def _fatura_kalan_izni(self) -> Decimal:
        """Bu makbuzun faturaya uygulayabileceği en yüksek tutar (düzenlemede kendi payı geri eklenir)."""
        oz = self._fatura_ozet
        izin = oz["kalan"]
        if self.makbuz_id:
            izin += sum(
                (m["fatura_kapanan"] for m in oz["makbuzlar"] if m["makbuz_id"] == self.makbuz_id), Decimal("0")
            )
        return izin

    def _fatura_asim_onayi(self, toplam: Decimal) -> bool:
        izin = self._fatura_kalan_izni()
        if toplam <= izin:
            return True
        return messagebox.askyesno(
            "Fatura kalanı aşılıyor",
            f"Tahsilat tutarı {_para(toplam)}, {self._fatura_ozet['fatura_no']} faturasının kalan tutarı "
            f"{_para(izin)}.\n\nFaturaya {_para(izin)} işlenir; fazla {_para(toplam - izin)} müşterinin diğer "
            "açık borçlarına, yoksa alacak olarak işlenir.\n\nDevam edilsin mi?",
            icon="warning",
            parent=self,
        )

    def _kirlet(self):
        if self._yukleniyor or not self._duzenlenebilir():
            return
        self._kirli = True

    def _mesaj(self, metin: str, renk: str = IKINCIL):
        self.mesaj_lbl.configure(text=metin, fg=renk)

    # ─── Yeni / kayıtlı makbuz yükleme ──────────────────────────
    def _yeni_makbuz_hazirla(self):
        self.mod = "yeni"
        self.makbuz = None
        self.makbuz_id = None
        self._makbuz_no_manuel = False
        self._kayitli_no = None
        self._onerilen_no = FinansService.makbuz_no_oner() if self.tahsilat else None
        self.makbuz_no_var.set(self._onerilen_no or "")
        self._cari_arama.secimi_ayarla(self._sabit_cari_id)
        self._bakiye_guncelle(self._sabit_cari_id)
        if self._sabit_cari_id:
            self.cari_ipucu_lbl.configure(text="Cari kartından açıldı; cari değiştirilemez.")
        self.satirlar = []
        self._satir_listesini_yenile()
        self.sekil_var.set(self._odeme_sekilleri[0])
        self._sekil_degisti()
        if self._varsayilan_hesap_id:
            self._varsayilan_hesabi_sec()
        if self.tahsilat:
            self._v_musteri_arama.secimi_ayarla(None)
            self._v_tedarikci_arama.secimi_ayarla(None)
            self.v_tutar_var.set("")
            self._virman_bakiyelerini_guncelle()
        oz = self._fatura_ozet
        if oz:
            self.cari_ipucu_lbl.configure(
                text=f"{oz['fatura_no']} numaralı satış faturasından açıldı; cari değiştirilemez."
            )
            self.aciklama_var.set(f"{oz['fatura_no']} numaralı satış faturası tahsilatı")
            if oz["kalan"] > 0:
                self.tutar_var.set(tr_tutar(oz["kalan"]))
            if oz.get("sube_id"):
                etiket = next((k for k, v in self._sube_map.items() if v == int(oz["sube_id"])), None)
                if etiket:
                    self.sube.set(etiket)
        self._mod_uygula()
        self._kirli = False
        if oz:
            self._mesaj(
                "Tutar faturanın kalanı olarak önerildi; kısmi tahsilat için değiştirebilirsiniz. Ödeme yöntemini "
                "ve hesabı seçip satırı ekleyin. Makbuz kaydedilene kadar hiçbir cari, kasa, banka veya POS "
                "hareketi oluşmaz."
                if oz["kalan"] > 0
                else "Bu faturanın ödenmemiş kalanı yok; girilen tutar müşterinin diğer açık borçlarına işlenir.",
                LACIVERT,
            )
        if self.tahsilat and self._sabit_cari_id:
            self.after(200, self._cari_uyari_goster)

    def _varsayilan_hesabi_sec(self):
        try:
            hesap = FinansService.hesap_getir(int(self._varsayilan_hesap_id))
        except (TypeError, ValueError):
            return
        if not hesap:
            return
        alt = (getattr(hesap, "alt_hesap_turu", None) or "").upper()
        if (hesap.hesap_turu or "").upper() == "KASA":
            hedef = "KASA"
        elif alt in ("MEVDUAT", "KMH"):
            hedef = "HAVALE"
        elif alt == "POS" and self.tahsilat:
            hedef = "KART"
        else:
            return
        sekil = next((s for s in self._odeme_sekilleri if _sekil_turu(s) == hedef), None)
        if not sekil:
            return
        self.sekil_var.set(sekil)
        self._sekil_degisti()
        if hesap.hesap_adi in self._hesap_secenekleri:
            self.hesap_var.set(hesap.hesap_adi)

    def _makbuzu_yukle(self, makbuz):
        if getattr(makbuz, "virman", False):
            self._virmani_yukle(makbuz)
            return
        self._yukleniyor = True
        try:
            self.makbuz = makbuz
            self.makbuz_id = int(makbuz.id)
            self.mod = "goruntule"
            self._fatura_ozetini_yenile(getattr(makbuz, "bagli_fatura_id", None))
            self._makbuz_no_manuel = False
            self._kayitli_no = (makbuz.makbuz_no or "").strip() or None
            self.makbuz_no_var.set(self._kayitli_no or "")
            self.tarih_var.set(_tarih_yazi(makbuz.tarih))
            self.aciklama_var.set(makbuz.aciklama or "")
            self._cari_ekle_yoksa(int(makbuz.cari_id))
            self._cari_arama.kayitlar = self._cari_kayitlari
            self._cari_arama.secimi_ayarla(int(makbuz.cari_id))
            if makbuz.sube_id:
                etiket = next((k for k, v in self._sube_map.items() if v == int(makbuz.sube_id)), None)
                if etiket:
                    self.sube.set(etiket)
            self.satirlar = self._satirlari_oku(makbuz)
            self._satir_listesini_yenile()
            self._satir_alanlarini_temizle()
            self._kilit_nedeni = (
                FinansService.makbuz_kilit_nedeni(makbuz.id) if makbuz.durum != "IPTAL" else None
            )
            self._bakiye_guncelle(int(makbuz.cari_id))
            self._mod_uygula()
            self._kirli = False
        finally:
            self._yukleniyor = False

    def _virmani_yukle(self, kayit):
        self._yukleniyor = True
        try:
            self.makbuz = kayit
            self.makbuz_id = int(kayit.id)
            self.mod = "goruntule"
            self.virman = True
            self.islem_turu_var.set(ISLEM_VIRMAN)
            self._virman_gorunumu()
            self._makbuz_no_manuel = False
            self._kayitli_no = (kayit.makbuz_no or "").strip() or None
            self.makbuz_no_var.set(self._kayitli_no or "")
            self.tarih_var.set(_tarih_yazi(kayit.tarih))
            self.aciklama_var.set(kayit.aciklama or "")
            if kayit.sube_id:
                etiket = next((k for k, v in self._sube_map.items() if v == int(kayit.sube_id)), None)
                if etiket:
                    self.sube.set(etiket)
            self._cari_ekle_yoksa(int(kayit.musteri_id), self._musteri_kayitlari)
            self._cari_ekle_yoksa(int(kayit.tedarikci_id), self._tedarikci_kayitlari)
            self._v_musteri_arama.secimi_ayarla(int(kayit.musteri_id))
            self._v_tedarikci_arama.secimi_ayarla(int(kayit.tedarikci_id))
            self.v_tutar_var.set(tr_tutar(kayit.tutar))
            self._kilit_nedeni = None
            self._virman_bakiyelerini_guncelle()
            self._mod_uygula()
            self._kirli = False
        finally:
            self._yukleniyor = False

    def _kayitli_makbuzu_getir(self):
        if self.virman:
            return CariVirmanMakbuzService.getir(self.makbuz_id)
        return FinansService.kasa_makbuz_getir(self.makbuz_id)

    def _kk_etiketi(self, kk_id: int) -> str:
        if not self._kk_etiketleri:
            self._kk_etiketleri = {k["id"]: k["etiket"] for k in FinansService.sirket_kredi_kartlari()}
        return self._kk_etiketleri.get(int(kk_id), f"Kart #{kk_id}")

    def _satirlari_oku(self, makbuz) -> list[dict]:
        satirlar = []
        for s in getattr(makbuz, "satirlar", None) or []:
            h = getattr(s, "finans_hesap", None)
            if s.kredi_karti_id:
                etiket = self._kk_etiketi(s.kredi_karti_id)
            else:
                etiket = h.hesap_adi if h else "—"
            satirlar.append(
                {
                    "tarih": s.tarih or makbuz.tarih,
                    "odeme_sekli": s.odeme_sekli,
                    "hesap": h.hesap_adi if (h and not s.kredi_karti_id) else None,
                    "finans_hesap_id": int(h.id) if (h and not s.kredi_karti_id) else None,
                    "etiket": etiket,
                    "tutar": Decimal(str(s.tutar or 0)),
                    "aciklama": s.aciklama or "",
                    "kart_tipi": s.kart_tipi,
                    "taksit_sayisi": s.taksit_sayisi or 1,
                    "kredi_karti_id": s.kredi_karti_id,
                }
            )
        if not satirlar and makbuz.finans_hesap is not None:
            satirlar.append(
                {
                    "tarih": makbuz.tarih,
                    "odeme_sekli": "NAKİT / KASA",
                    "hesap": makbuz.finans_hesap.hesap_adi,
                    "finans_hesap_id": int(makbuz.finans_hesap.id),
                    "etiket": makbuz.finans_hesap.hesap_adi,
                    "tutar": Decimal(str(makbuz.tutar or 0)),
                    "aciklama": "",
                    "kart_tipi": None,
                    "taksit_sayisi": 1,
                    "kredi_karti_id": None,
                }
            )
        return satirlar

    # ─── Cari ve bakiye ─────────────────────────────────────────
    def secili_cari_id(self) -> int | None:
        return self._sabit_cari_id or self._cari_arama.secili_id

    def _cari_degisti(self, cari_id):
        self._bakiye_guncelle(cari_id)
        self._kirlet()
        if cari_id and self.tahsilat and not self._yukleniyor:
            self._cari_uyari_goster()

    def _bakiye_guncelle(self, cari_id):
        if not cari_id:
            self.bakiye_ozeti = None
            self.bakiye_lbl.configure(text="—", fg=IKINCIL)
            return
        try:
            ozet = FinansService.cari_bakiye_ozeti(int(cari_id))
        except Exception as hata:  # noqa: BLE001
            self.bakiye_ozeti = None
            self.bakiye_lbl.configure(text=f"Bakiye okunamadı: {hata}", fg=UYARI)
            return
        self.bakiye_ozeti = ozet
        renk = {"Borçlu": UYARI, "Alacaklı": BASARI}.get(ozet["yon"], IKINCIL)
        yazi = _para(ozet["tutar"]) + (f"  {ozet['yon']}" if ozet["yon"] != "Kapalı" else "  (Kapalı)")
        self.bakiye_lbl.configure(text=yazi, fg=renk)

    def bakiye_metni(self) -> str:
        return self.bakiye_lbl.cget("text")

    def _cari_uyari_goster(self):
        cari_id = self.secili_cari_id()
        if not cari_id or self._son_uyari_cari_id == cari_id:
            return
        self._son_uyari_cari_id = cari_id
        try:
            from cari_kart_ui import cari_uyari_goster

            cari_uyari_goster(self, cari_id)
        except Exception:
            pass

    # ─── Makbuz numarası ────────────────────────────────────────
    def yeni_no_gir(self, deger: str | None = None):
        """Elle makbuz numarası; boş bırakılırsa otomatik numaraya (veya kayıtlı numaraya) döner."""
        if not self._duzenlenebilir():
            return False
        if deger is None:
            deger = simpledialog.askstring(
                "Yeni Makbuz No",
                "Makbuz numarasını girin.\nBoş bırakırsanız "
                + ("otomatik numara kullanılır." if self.mod == "yeni" and self.tahsilat else "numara değişmez."),
                initialvalue=self.makbuz_no_var.get(),
                parent=self,
            )
            if deger is None:
                return False
        no = deger.strip()
        if len(no) > 50:
            messagebox.showerror("Makbuz No", "Makbuz numarası en fazla 50 karakter olabilir.", parent=self)
            return False
        if not no:
            self._makbuz_no_manuel = False
            if self.mod == "yeni":
                self._onerilen_no = FinansService.makbuz_no_oner() if self.tahsilat else None
                self.makbuz_no_var.set(self._onerilen_no or "")
            else:
                self.makbuz_no_var.set(self._kayitli_no or "")
            self._kirlet()
            self._mod_uygula()
            return True
        if no.upper() != (self._kayitli_no or "").upper() and FinansService.makbuz_no_kullanimda_mi(
            no,
            haric_makbuz_id=None if self.virman else self.makbuz_id,
            haric_virman_id=self.makbuz_id if self.virman else None,
        ):
            messagebox.showerror(
                "Makbuz No",
                f"{no} numaralı makbuz bu firmada zaten var. Farklı bir numara girin.",
                parent=self,
            )
            return False
        self._makbuz_no_manuel = True
        self.makbuz_no_var.set(no)
        self._kirlet()
        self._mod_uygula()
        return True

    # ─── Satır paneli ───────────────────────────────────────────
    def _sekil_degisti(self):
        sekil = self.sekil_var.get()
        if sekil == CARI_VIRMAN_SEKLI:
            self._virmana_gec()
            return
        if sekil == KK_ODEME_SEKLI:
            self._kk_odemeye_gec()
            return
        self._son_sekil = sekil
        tur = _sekil_turu(sekil)
        self._hesap_secenekleri = {}
        if not self.tahsilat and tur == "KART":
            self.hesap_etiket_lbl.configure(text="Şirket kartı")
            for k in FinansService.sirket_kredi_kartlari():
                self._hesap_secenekleri[k["etiket"]] = {"kredi_karti_id": k["id"]}
                self._kk_etiketleri[k["id"]] = k["etiket"]
        else:
            self.hesap_etiket_lbl.configure(text="POS hesabı" if tur == "KART" else "Hesap")
            for h in FinansService.tahsilat_hesaplari(sekil):
                if getattr(h, "aktif", True):
                    self._hesap_secenekleri[h.hesap_adi] = {"hesap": h.hesap_adi, "finans_hesap_id": int(h.id)}
        degerler = tuple(self._hesap_secenekleri)
        self.hesap_cb.configure(values=degerler)
        if self.hesap_var.get() not in self._hesap_secenekleri:
            self.hesap_var.set(degerler[0] if len(degerler) == 1 else "")
        self._kart_alanlarini_ayarla()

    def _kart_alanlarini_ayarla(self):
        tur = _sekil_turu(self.sekil_var.get())
        if tur != "KART":
            self.kart_kutu.grid_remove()
            return
        self.kart_kutu.grid()
        if self.tahsilat:
            self.kart_tipi_lbl.pack(side="left", padx=(0, 8), pady=5, before=self.taksit_lbl)
            self.kart_tipi_cb.pack(side="left", padx=(0, 16), before=self.taksit_lbl)
            self.taksit_sb.configure(to=12)
            self._kart_tipi_degisti()
            self.kart_bilgi_lbl.configure(
                text="POS komisyonu taksit tablosundan, net tutar valör gününde KMH hesabına aktarılır."
            )
        else:
            self.kart_tipi_lbl.pack_forget()
            self.kart_tipi_cb.pack_forget()
            self.taksit_sb.configure(to=24, state="normal" if self._duzenlenebilir() else "disabled")
            self.kart_bilgi_lbl.configure(
                text="Tedarikçi borcu kapanır; tutar kart borcuna ve taksitlerle ekstreye yazılır."
            )

    def _kart_tipi_degisti(self):
        banka = KART_TIPLERI.get(self.kart_tipi_var.get()) == "BANKA_KARTI"
        if banka:
            self.taksit_var.set("1")
        self.taksit_sb.configure(state="disabled" if (banka or not self._duzenlenebilir()) else "normal")

    def _satir_alanlarini_temizle(self):
        self._duzenlenen_satir = None
        self.tutar_var.set("")
        self.satir_aciklama_var.set("")
        self.satir_tarih_var.set(self.tarih_var.get() or date.today().strftime("%d.%m.%Y"))
        self.taksit_var.set("1")
        self.kart_tipi_var.set("Kredi Kartı")
        self.btn_satir_ekle.configure(text="Satırı Ekle  (Enter)")

    def _satir_panelinden_oku(self) -> dict:
        sekil = self.sekil_var.get().strip()
        if not sekil:
            raise ValueError("Ödeme yöntemini seçin.")
        secim = self._hesap_secenekleri.get(self.hesap_var.get())
        if not secim:
            tur = _sekil_turu(sekil)
            if not self.tahsilat and tur == "KART":
                raise ValueError("Ödeme yapılacak şirket kredi kartını seçin (Finans → Kredi Kartları).")
            raise ValueError("POS hesabını seçin." if tur == "KART" else "Hesabı seçin.")
        tarih = _tarih_oku(self.satir_tarih_var.get(), "Satır tarihi")
        tutar = _tutar_oku(self.tutar_var.get())
        satir = {
            "tarih": tarih,
            "odeme_sekli": sekil,
            "hesap": secim.get("hesap"),
            "finans_hesap_id": secim.get("finans_hesap_id"),
            "kredi_karti_id": secim.get("kredi_karti_id"),
            "etiket": self.hesap_var.get(),
            "tutar": tutar,
            "aciklama": self.satir_aciklama_var.get().strip(),
            "kart_tipi": None,
            "taksit_sayisi": 1,
        }
        if _sekil_turu(sekil) == "KART":
            try:
                taksit = int(self.taksit_var.get() or "1")
            except ValueError as hata:
                raise ValueError("Taksit sayısı tam sayı olmalıdır.") from hata
            azami = 12 if self.tahsilat else 24
            if not 1 <= taksit <= azami:
                raise ValueError(f"Taksit sayısı 1 ile {azami} arasında olmalıdır.")
            if self.tahsilat:
                satir["kart_tipi"] = KART_TIPLERI.get(self.kart_tipi_var.get(), "KREDI_KARTI")
                if satir["kart_tipi"] == "BANKA_KARTI":
                    taksit = 1
            satir["taksit_sayisi"] = taksit
        return satir

    def satir_ekle(self):
        if not self._duzenlenebilir():
            return False
        try:
            satir = self._satir_panelinden_oku()
        except ValueError as hata:
            messagebox.showerror("Satır", str(hata), parent=self)
            return False
        if self._duzenlenen_satir is not None and self._duzenlenen_satir < len(self.satirlar):
            self.satirlar[self._duzenlenen_satir] = satir
        else:
            self.satirlar.append(satir)
        self._satir_alanlarini_temizle()
        self._satir_listesini_yenile()
        self._kirlet()
        self.tutar_entry.focus_set()
        return True

    def satir_duzenle(self):
        if not self._duzenlenebilir():
            return
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Düzenlenecek satırı seçin.", parent=self)
            return
        idx = int(secim[0])
        s = self.satirlar[idx]
        self.sekil_var.set(s["odeme_sekli"])
        self._sekil_degisti()
        self.hesap_var.set(s.get("etiket") or s.get("hesap") or "")
        self.satir_tarih_var.set(_tarih_yazi(s.get("tarih")))
        self.tutar_var.set(tr_tutar(s["tutar"]))
        self.satir_aciklama_var.set(s.get("aciklama") or "")
        self.kart_tipi_var.set(_KART_TIPI_ETIKET.get(s.get("kart_tipi") or "", "Kredi Kartı"))
        self.taksit_var.set(str(s.get("taksit_sayisi") or 1))
        self._kart_alanlarini_ayarla()
        self._duzenlenen_satir = idx
        self.btn_satir_ekle.configure(text="Satırı Güncelle  (Enter)")
        self.tutar_entry.focus_set()

    def satir_sil(self):
        if not self._duzenlenebilir():
            return
        secim = self.tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Silinecek satırı seçin.", parent=self)
            return
        del self.satirlar[int(secim[0])]
        self._satir_alanlarini_temizle()
        self._satir_listesini_yenile()
        self._kirlet()

    def _satir_listesini_yenile(self):
        self.tablo.delete(*self.tablo.get_children())
        toplam = Decimal("0")
        for i, s in enumerate(self.satirlar):
            tutar = Decimal(str(s.get("tutar") or 0))
            toplam += tutar
            self.tablo.insert(
                "",
                "end",
                iid=str(i),
                tags=("cift" if i % 2 else "tek",),
                values=(
                    _tarih_yazi(s.get("tarih")),
                    s.get("odeme_sekli") or "",
                    s.get("etiket") or s.get("hesap") or "",
                    _kart_detayi(s),
                    _para(tutar),
                    s.get("aciklama") or "",
                ),
            )
        self.toplam_lbl.configure(text=f"Toplam: {_para(toplam)}")

    # ─── Kaydet / düzenle / iptal ───────────────────────────────
    def _virman_verilerini_topla(self) -> dict:
        musteri_id = self._v_musteri_arama.secili_id
        if not musteri_id:
            raise ValueError("Tahsilat yapılan müşteriyi seçin: alana yazıp listeden seçin.")
        tedarikci_id = self._v_tedarikci_arama.secili_id
        if not tedarikci_id:
            raise ValueError("Ödeme yapılan tedarikçiyi seçin: alana yazıp listeden seçin.")
        if musteri_id == tedarikci_id:
            raise ValueError("Müşteri ve tedarikçi aynı cari olamaz.")
        tarih = _tarih_oku(self.tarih_var.get())
        tutar = _tutar_oku(self.v_tutar_var.get())
        otomatik = self.mod == "yeni" and not self._makbuz_no_manuel
        return {
            "tarih": tarih,
            "musteri_id": musteri_id,
            "tedarikci_id": tedarikci_id,
            "tutar": tutar,
            "makbuz_no": None if otomatik else (self.makbuz_no_var.get().strip() or None),
            "makbuz_no_otomatik": otomatik,
            "aciklama": self.aciklama_var.get().strip() or None,
            "sube_id": self._sube_map.get(self.sube.get()),
        }

    def _verileri_topla(self) -> dict:
        if self.virman:
            return self._virman_verilerini_topla()
        cari_id = self.secili_cari_id()
        if not cari_id:
            raise ValueError("Cari hesap seçin: cari alanına yazıp listeden seçin.")
        tarih = _tarih_oku(self.tarih_var.get())
        if not self.satirlar:
            raise ValueError(
                "En az bir tahsilat satırı ekleyin." if self.tahsilat else "En az bir ödeme satırı ekleyin."
            )
        satirlar = [
            {
                "tarih": s.get("tarih") or tarih,
                "odeme_sekli": s["odeme_sekli"],
                "hesap": s.get("hesap"),
                "finans_hesap_id": s.get("finans_hesap_id"),
                "tutar": s["tutar"],
                "aciklama": s.get("aciklama") or None,
                "kart_tipi": s.get("kart_tipi"),
                "taksit_sayisi": s.get("taksit_sayisi") or 1,
                "kredi_karti_id": s.get("kredi_karti_id"),
            }
            for s in self.satirlar
        ]
        otomatik = self.mod == "yeni" and self.tahsilat and not self._makbuz_no_manuel
        return {
            "tarih": tarih,
            "cari_id": cari_id,
            "makbuz_no": None if otomatik else (self.makbuz_no_var.get().strip() or None),
            "makbuz_no_otomatik": otomatik,
            "aciklama": self.aciklama_var.get().strip() or None,
            "sube_id": self._sube_map.get(self.sube.get()),
            "satirlar": satirlar,
            "fatura_id": self._fatura_ozet["fatura_id"] if self._fatura_ozet else None,
        }

    def _kapatma_secimi_ekle(self, veriler: dict) -> None:
        """Yeni makbuzda açık kalem seçim penceresi; kapatılırsa seçim eklenmez (servis FIFO uygular)."""
        cari_id = veriler.get("cari_id")
        if not cari_id or veriler.get("fatura_id"):
            return
        if not self.tahsilat and not tedarikci_mi(self._cari_turleri.get(cari_id)):
            return
        from acik_kalem_secim_ui import kapatma_plani_sor

        toplam = sum((Decimal(str(s["tutar"])) for s in veriler["satirlar"]), Decimal("0"))
        cari = CariService.getir(int(cari_id))
        _acildi, sonuc = kapatma_plani_sor(
            self, int(cari_id), toplam, cari_adi=getattr(cari, "unvan", "") or "",
            baslik="Tahsilat Makbuzu — Açık Kalem Seçimi" if self.tahsilat else "Ödeme Makbuzu — Açık Kalem Seçimi",
        )
        if sonuc:
            veriler["kapatma_dagitimi"] = [{"hareket_id": h, "tutar": t} for h, t in sonuc["dagitim"]]
            veriler["kapatma_fazla"] = sonuc["fazla"]

    def kaydet(self) -> bool:
        if not self._duzenlenebilir() or self._kaydediliyor:
            return False
        if not self.virman and self.tutar_var.get().strip():
            cevap = messagebox.askyesnocancel(
                "Eklenmemiş satır",
                "Satır alanlarına girilen tutar henüz listeye eklenmedi.\n\nEvet: satırı ekleyip kaydet\n"
                "Hayır: bu tutarı yok sayıp kaydet\nİptal: makbuza dön",
                parent=self,
            )
            if cevap is None:
                return False
            if cevap and not self.satir_ekle():
                return False
            if cevap is False:
                self._satir_alanlarini_temizle()
        self._kaydediliyor = True
        self.btn_kaydet.configure(state="disabled")
        oneri = self._onerilen_no
        onceki_mod = self.mod
        try:
            veriler = self._verileri_topla()
            if self.virman:
                if not self._virman_asim_onayi(veriler["tutar"]):
                    return False
                if onceki_mod == "duzenle":
                    makbuz = CariVirmanMakbuzService.guncelle(self.makbuz_id, veriler)
                else:
                    makbuz = CariVirmanMakbuzService.kaydet(veriler)
            elif self._fatura_ozet and not self._fatura_asim_onayi(
                sum((Decimal(str(s["tutar"])) for s in veriler["satirlar"]), Decimal("0"))
            ):
                return False
            elif onceki_mod == "duzenle":
                makbuz = FinansService.kasa_makbuz_guncelle(self.makbuz_id, veriler)
            else:
                self._kapatma_secimi_ekle(veriler)
                if not self.winfo_exists():
                    return False
                if self.tahsilat:
                    makbuz = FinansService.kasa_tahsilat_makbuzu_kaydet(veriler)
                else:
                    makbuz = FinansService.kasa_odeme_makbuzu_kaydet(veriler)
        except AcikKalemDegisti as hata:
            messagebox.showerror(
                self._pencere_basligi(),
                f"{hata}\n\nSeçtiğiniz açık kalemler başka bir işlemle değişti. Kaydı yeniden deneyin ve kalemleri "
                "yeniden seçin.",
                parent=self,
            )
            return False
        except (ValueError, PermissionError) as hata:
            messagebox.showerror(self._pencere_basligi(), str(hata), parent=self)
            return False
        finally:
            self._kaydediliyor = False
            if self.winfo_exists():
                self.btn_kaydet.configure(state="normal")
        self.result = makbuz
        self._makbuzu_yukle(makbuz)
        no = makbuz.makbuz_no or makbuz.belge_no
        if self.virman:
            sonra = " · ".join(self.v_sonra_lbl.cget("text").splitlines())
            self._mesaj(
                f"Kaydedildi: {no} · {makbuz.belge_no} (evraklar {makbuz.tahsilat_belge_no}, "
                f"{makbuz.odeme_belge_no}) · {_para(makbuz.tutar)} · güncel bakiye {sonra}",
                BASARI,
            )
        else:
            fatura = (
                f" · {self._fatura_ozet['fatura_no']} faturasının kalanı {_para(self._fatura_ozet['kalan'])}"
                if self._fatura_ozet
                else ""
            )
            self._mesaj(
                f"Kaydedildi: {no} · {makbuz.belge_no} · {_para(makbuz.tutar)} · güncel bakiye "
                f"{self.bakiye_metni()}{fatura}",
                BASARI,
            )
        if veriler.get("makbuz_no_otomatik") and oneri and makbuz.makbuz_no != oneri:
            messagebox.showinfo(
                "Makbuz No",
                f"{oneri} numarası bu arada başka bir makbuzda kullanıldı.\n"
                f"Makbuz {makbuz.makbuz_no} numarasıyla kaydedildi.",
                parent=self,
            )
        if callable(self._on_kayit):
            try:
                self._on_kayit(makbuz)
            except Exception:
                pass
        return True

    def duzenlemeye_gec(self):
        if self.mod != "goruntule" or self.makbuz is None:
            return
        self._kilit_nedeni = None if self.virman else FinansService.makbuz_kilit_nedeni(self.makbuz_id)
        if self._kilit_nedeni:
            self._mod_uygula()
            messagebox.showwarning("Düzenleme", self._kilit_nedeni, parent=self)
            return
        self.mod = "duzenle"
        self._mod_uygula()
        self._sekil_degisti()
        self._kirli = False
        self._mesaj("Düzenleme modundasınız. Kaydettiğinizde eski etkiler geri alınıp makbuz yeniden yazılır.", LACIVERT)
        self.tarih_entry.focus_set()

    def _vazgec(self):
        if self.mod != "duzenle":
            return
        if self._kirli and not messagebox.askyesno(
            "Vazgeç", "Yapılan değişiklikler kaydedilmeyecek. Devam edilsin mi?", parent=self
        ):
            return
        self._makbuzu_yukle(self._kayitli_makbuzu_getir())
        self._mesaj("Değişikliklerden vazgeçildi.")

    def iptal_et(self):
        if self.makbuz is None or self.mod != "goruntule":
            return
        no = self.makbuz.makbuz_no or self.makbuz.belge_no
        etki = (
            "Müşteri ve tedarikçi cari hareketleri birlikte geri alınır"
            if self.virman
            else "Cari, kasa/banka ve kart hareketleri geri alınır"
        )
        if not messagebox.askyesno(
            "Makbuzu İptal Et",
            f"{no} numaralı makbuz iptal edilsin mi?\n\n{etki}; makbuz numarası listede İPTAL olarak kalır.",
            parent=self,
        ):
            return
        try:
            if self.virman:
                CariVirmanMakbuzService.iptal(self.makbuz_id)
            else:
                FinansService.kasa_makbuz_iptal(self.makbuz_id)
        except (ValueError, PermissionError) as hata:
            messagebox.showerror("İptal", str(hata), parent=self)
            return
        makbuz = self._kayitli_makbuzu_getir()
        self.result = makbuz
        self._makbuzu_yukle(makbuz)
        self._mesaj(f"{no} iptal edildi.", UYARI)
        if callable(self._on_kayit):
            try:
                self._on_kayit(makbuz)
            except Exception:
                pass

    def yazdir(self):
        kaydedilmemis = self.makbuz_id is None or (self._duzenlenebilir() and self._kirli)
        if kaydedilmemis:
            ne = "henüz kaydedilmedi" if self.makbuz_id is None else "kaydedilmemiş değişiklikler içeriyor"
            if not messagebox.askyesno(
                "Yazdır / PDF / Word",
                f"Makbuz {ne}.\n\nÇıktı yalnız kayıtlı makbuzdan alınabilir. Makbuz şimdi kaydedilsin mi?\n\n"
                "Evet: kaydet ve çıktı önizlemesini aç\nHayır: makbuza dön",
                icon="warning",
                parent=self,
            ):
                return None
            if not self.kaydet() or self.makbuz_id is None:
                return None
        from makbuz_cikti import virman_kimligi
        from makbuz_cikti_ui import makbuz_ciktisi_ac

        return makbuz_ciktisi_ac(self, [virman_kimligi(self.makbuz_id) if self.virman else self.makbuz_id])

    def _yeni_pencere(self):
        oz = self._fatura_ozet
        if oz and not oz["iptal"]:
            try:
                KasaMakbuzDialog(self.master, self.makbuz_turu, on_kayit=self._on_kayit, fatura_id=oz["fatura_id"])
            except ValueError as hata:
                messagebox.showerror("Yeni Makbuz", str(hata), parent=self)
            return
        KasaMakbuzDialog(
            self.master, self.makbuz_turu, on_kayit=self._on_kayit, islem_turu="VIRMAN" if self.virman else None
        )

    def kapat(self):
        if self._duzenlenebilir() and self._kirli:
            cevap = messagebox.askyesnocancel(
                "Kaydedilmemiş değişiklikler",
                "Makbuzda kaydedilmemiş değişiklikler var.\n\nEvet: kaydet ve kapat\n"
                "Hayır: kaydetmeden kapat\nİptal: makbuza dön",
                parent=self,
            )
            if cevap is None:
                return False
            if cevap and not self.kaydet():
                return False
        self._aramalari_gizle()
        self.destroy()
        return True


def kasa_makbuzlari_sayfasi(app, makbuz_turu=None, geri_fn=None):
    """Makbuz listesi — arama, tarih/durum filtresi, görüntüle, yazdır, iptal (isteğe bağlı tür filtresi)."""
    from finans_ui import _finans_menu_isaretle, finans_menusu_goster
    from ui_bg import arka_planda

    app._icerigi_temizle()
    _finans_menu_isaretle(app)
    geri = geri_fn or finans_menusu_goster

    if makbuz_turu == "TAHSILAT":
        baslik = "TAHSİLAT MAKBUZLARI LİSTESİ"
        alt = (
            "Kayıtlı tahsilat, cari virman ve müşteriden tedarikçiye kredi kartı ile ödeme kayıtları — "
            "makbuz no, cari, belge no veya açıklamanın herhangi bir yerinden arayın."
        )
    elif makbuz_turu == "ODEME":
        baslik = "ÖDEME MAKBUZLARI LİSTESİ"
        alt = "Kayıtlı ödeme makbuzları — makbuz no, cari, belge no veya açıklamanın herhangi bir yerinden arayın."
    else:
        baslik = "KASA MAKBUZLARI"
        alt = "Tahsilat (TMK), ödeme (OMK) ve cari virman (CVR) makbuzları."
    virman_dahil = makbuz_turu in (None, "TAHSILAT")
    ozel_sekiller = (CARI_VIRMAN_SEKLI, KK_ODEME_SEKLI)
    if makbuz_turu == "ODEME":
        sekil_filtreleri = ODEME_MAKBUZ_SEKILLERI
    elif makbuz_turu == "TAHSILAT":
        sekil_filtreleri = tuple(TAHSILAT_MAKBUZ_SEKILLERI) + ozel_sekiller
    else:
        sekil_filtreleri = tuple(dict.fromkeys(tuple(TAHSILAT_MAKBUZ_SEKILLERI) + ODEME_MAKBUZ_SEKILLERI)) + ozel_sekiller

    from satis_tema import ekran_ust_cubugu

    govde = ekran_ust_cubugu(app, baslik, alt_baslik=alt, geri_komut=lambda: geri(app), geri_metin="← Geri")

    filtre = tk.Frame(govde, bg=BEYAZ)
    filtre.pack(fill="x", pady=(0, 6))
    tk.Label(filtre, text="Ara", bg=BEYAZ, fg=METIN).pack(side="left")
    arama_var = tk.StringVar()
    arama = ttk.Entry(filtre, textvariable=arama_var, width=30)
    arama.pack(side="left", padx=(6, 14))
    tk.Label(filtre, text="Başlangıç", bg=BEYAZ, fg=METIN).pack(side="left")
    bas_entry = ttk.Entry(filtre, width=11)
    bas_entry.pack(side="left", padx=(6, 0))
    takvim_butonu(filtre, bas_entry, on_select=lambda *_: yenile(), text="📅", width=3)
    tk.Label(filtre, text="Bitiş", bg=BEYAZ, fg=METIN).pack(side="left", padx=(12, 0))
    bit_entry = ttk.Entry(filtre, width=11)
    bit_entry.pack(side="left", padx=(6, 0))
    takvim_butonu(filtre, bit_entry, on_select=lambda *_: yenile(), text="📅", width=3)
    tk.Label(filtre, text="Durum", bg=BEYAZ, fg=METIN).pack(side="left", padx=(12, 0))
    durum_cb = ttk.Combobox(filtre, values=tuple(DURUM_FILTRELERI), state="readonly", width=8)
    durum_cb.set("Tümü")
    durum_cb.pack(side="left", padx=(6, 12))
    filtre2 = tk.Frame(govde, bg=BEYAZ)
    filtre2.pack(fill="x", pady=(0, 6))
    tk.Label(filtre2, text="Ödeme yöntemi", bg=BEYAZ, fg=METIN).pack(side="left")
    sekil_cb = ttk.Combobox(
        filtre2,
        values=("Tümü",) + tuple(sekil_filtreleri),
        state="readonly",
        width=max(len(s) for s in sekil_filtreleri) + 2,
    )
    sekil_cb.set("Tümü")
    sekil_cb.pack(side="left", padx=(6, 12))
    tk_buton(filtre2, "Filtrele", lambda: yenile(), rol="ara").pack(side="left")
    tk_buton(filtre2, "Temizle", lambda: temizle(), rol="geri").pack(side="left", padx=6)

    butonlar = tk.Frame(govde, bg=BEYAZ)
    butonlar.pack(fill="x", pady=(0, 6))
    ozet_lbl = tk.Label(govde, bg=BEYAZ, fg=IKINCIL, anchor="w")

    cerceve = ttk.Frame(govde)
    cerceve.pack(fill="both", expand=True)
    sutunlar = ("makbuz_no", "belge", "tarih", "cari", "odeme", "hesap", "tutar", "durum", "aciklama")
    tablo = ttk.Treeview(cerceve, columns=sutunlar, show="headings", selectmode="extended")
    _tablo_stili(tablo)
    tablo.tag_configure("iptal", foreground=UYARI)
    for k, b, w, a in (
        ("makbuz_no", "Makbuz No", 110, "w"),
        ("belge", "Belge No", 110, "w"),
        ("tarih", "Tarih", 85, "w"),
        ("cari", "Cari", 230, "w"),
        ("odeme", "Ödeme yöntemi", 300, "w"),
        ("hesap", "Hesap", 150, "w"),
        ("tutar", "Tutar", 110, "e"),
        ("durum", "Durum", 70, "w"),
        ("aciklama", "Açıklama", 200, "w"),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, minwidth=50, anchor=a)
    kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=tablo.yview)
    yatay = ttk.Scrollbar(cerceve, orient="horizontal", command=tablo.xview)
    tablo.configure(yscrollcommand=kaydir.set, xscrollcommand=yatay.set)
    tablo.grid(row=0, column=0, sticky="nsew")
    kaydir.grid(row=0, column=1, sticky="ns")
    yatay.grid(row=1, column=0, sticky="ew")
    cerceve.columnconfigure(0, weight=1)
    cerceve.rowconfigure(0, weight=1)
    ozet_lbl.pack(fill="x", pady=(6, 0))

    durum = {"token": 0, "arama_after": None, "turler": {}}

    def _tarih_filtresi(entry, ad):
        metin = entry.get().strip()
        return _tarih_oku(metin, ad) if metin else None

    def yenile():
        if not tablo.winfo_exists():
            return
        try:
            bas = _tarih_filtresi(bas_entry, "Başlangıç tarihi")
            bit = _tarih_filtresi(bit_entry, "Bitiş tarihi")
        except ValueError as hata:
            messagebox.showerror("Filtre", str(hata), parent=app)
            return
        durum["token"] += 1
        token = durum["token"]
        ozet_lbl.configure(text="Yükleniyor…")
        kriter = dict(
            arama=arama_var.get().strip() or None,
            baslangic=bas,
            bitis=bit,
            durum=DURUM_FILTRELERI.get(durum_cb.get()),
        )
        sekil = None if sekil_cb.get() == "Tümü" else sekil_cb.get()

        def is_():
            makbuzlar = []
            if sekil not in ozel_sekiller:
                makbuzlar = list(
                    FinansService.kasa_makbuz_listele(makbuz_turu=makbuz_turu, limit=500, odeme_sekli=sekil, **kriter)
                )
            ekler = []
            if virman_dahil and sekil in (None, CARI_VIRMAN_SEKLI):
                ekler += CariVirmanMakbuzService.listele(limit=500, **kriter)
            if virman_dahil and sekil in (None, KK_ODEME_SEKLI):
                ekler += KkCekimiService.makbuz_listesi(limit=500, **kriter)
            if ekler:
                makbuzlar += ekler
                makbuzlar.sort(key=lambda m: (m.tarih, (m.makbuz_no or "").upper(), m.belge_no), reverse=True)
                makbuzlar = makbuzlar[:500]
            return makbuzlar

        def bitti(makbuzlar):
            if token != durum["token"] or not tablo.winfo_exists():
                return
            secili = tablo.selection()
            tablo.delete(*tablo.get_children())
            toplam = Decimal("0")
            durum["turler"] = {}
            for i, m in enumerate(makbuzlar):
                iptal = m.durum == "IPTAL"
                if not iptal:
                    toplam += Decimal(str(m.tutar or 0))
                if getattr(m, "kk_cekimi", False):
                    iid = f"K{m.belge_no}"
                    durum["turler"][iid] = "KK"
                    musteri, tedarikci = m.musteri, m.tedarikci
                    cari_yazi = f"{musteri.cari_kodu} - {musteri.unvan}" if musteri else "—"
                    odeme_yazi = KK_ODEME_SEKLI
                    taksit = "tek çekim" if m.taksit_sayisi == 1 else f"{m.taksit_sayisi} taksit"
                    hedef = f"{tedarikci.cari_kodu} - {tedarikci.unvan}" if tedarikci else "—"
                    hesap_yazi = f"→ {hedef} · {m.banka} / {taksit}"
                elif getattr(m, "virman", False):
                    iid = f"V{m.id}"
                    durum["turler"][iid] = "VIRMAN"
                    musteri, tedarikci = m.musteri, m.tedarikci
                    cari_yazi = f"{musteri.cari_kodu} - {musteri.unvan}" if musteri else "—"
                    odeme_yazi = "CARİ VİRMAN"
                    hesap_yazi = f"→ {tedarikci.cari_kodu} - {tedarikci.unvan}" if tedarikci else "—"
                else:
                    iid = str(m.id)
                    durum["turler"][iid] = m.makbuz_turu
                    cari = getattr(m, "cari", None)
                    cari_yazi = f"{cari.cari_kodu} - {cari.unvan}" if cari else "—"
                    odeme_yazi = _odeme_ozet(m)
                    hesap_yazi = _hesap_ozet(m)
                tablo.insert(
                    "",
                    "end",
                    iid=iid,
                    tags=("iptal",) if iptal else ("cift" if i % 2 else "tek",),
                    values=(
                        m.makbuz_no or "—",
                        m.belge_no,
                        _tarih_yazi(m.tarih),
                        cari_yazi,
                        odeme_yazi,
                        hesap_yazi,
                        _para(m.tutar),
                        "İPTAL" if iptal else "Açık",
                        (m.aciklama or "")[:80],
                    ),
                )
            kalan = [i for i in secili if tablo.exists(i)]
            if kalan:
                tablo.selection_set(kalan)
                tablo.see(kalan[0])
            ozet_lbl.configure(
                text=f"{len(makbuzlar)} makbuz · Toplam (iptaller hariç): {_para(toplam)} · "
                "Toplu çıktı için Ctrl veya Shift ile birden fazla makbuz seçin (Ctrl+A: tümü).",
                fg=IKINCIL,
            )

        def hata(exc):
            if token == durum["token"] and ozet_lbl.winfo_exists():
                ozet_lbl.configure(text=f"Liste yüklenemedi: {exc}", fg=UYARI)

        arka_planda(tablo, is_, bitti, hata)

    def temizle():
        arama_var.set("")
        bas_entry.delete(0, "end")
        bit_entry.delete(0, "end")
        durum_cb.set("Tümü")
        sekil_cb.set("Tümü")
        yenile()

    def arama_gecikmeli(*_):
        if durum["arama_after"]:
            try:
                app.after_cancel(durum["arama_after"])
            except tk.TclError:
                pass
        durum["arama_after"] = app.after(300, yenile)

    arama_var.trace_add("write", arama_gecikmeli)
    durum_cb.bind("<<ComboboxSelected>>", lambda _e: yenile())
    sekil_cb.bind("<<ComboboxSelected>>", lambda _e: yenile())
    for e in (bas_entry, bit_entry, arama):
        e.bind("<Return>", lambda _e: yenile())

    def _secili():
        secim = tablo.selection()
        if not secim:
            messagebox.showinfo("Seçim", "Bir makbuz seçin.", parent=app)
            return None
        if len(secim) > 1:
            messagebox.showinfo("Seçim", "Bu işlem için tek bir makbuz seçin.", parent=app)
            return None
        return secim[0]

    def secili_makbuzlar() -> list:
        """Liste sırasıyla seçilen makbuzlar: kasa makbuzu id (int), cari virman "V{id}" (KK fişleri hariç)."""
        secim = set(tablo.selection())
        return [
            i if i.startswith("V") else int(i)
            for i in tablo.get_children()
            if i in secim and not i.startswith("K")
        ]

    def yeni(tur, islem_turu=None):
        KasaMakbuzDialog(app, makbuz_turu=tur, on_kayit=lambda _m: yenile(), islem_turu=islem_turu)

    def kk_fisi_ac(belge_no=None):
        from app import KkCekimiDialog

        dlg = KkCekimiDialog(app, belge_no=belge_no)
        if dlg.winfo_exists():
            app.wait_window(dlg)
        if dlg.result:
            yenile()

    def goruntule(_event=None):
        iid = _secili()
        if not iid:
            return
        try:
            if iid.startswith("K"):
                if tablo.set(iid, "durum") == "İPTAL":
                    messagebox.showinfo("KK ile ödeme", "İptal edilmiş fiş görüntülenemez / güncellenemez.", parent=app)
                    return
                kk_fisi_ac(iid[1:])
                return
            if iid.startswith("V"):
                KasaMakbuzDialog(app, makbuz_turu="TAHSILAT", virman_id=int(iid[1:]), on_kayit=lambda _m: yenile())
                return
            tur = durum["turler"].get(iid) or makbuz_turu or "TAHSILAT"
            KasaMakbuzDialog(app, makbuz_turu=tur, makbuz_id=int(iid), on_kayit=lambda _m: yenile())
        except ValueError as hata:
            messagebox.showerror("Makbuz", str(hata), parent=app)

    def yazdir():
        idler = secili_makbuzlar()
        if not idler:
            if any(i.startswith("K") for i in tablo.selection()):
                messagebox.showinfo(
                    "Çıktı", "Kredi kartı ile ödeme (KK çekim) fişlerinin makbuz çıktısı yoktur.", parent=app
                )
                return None
            messagebox.showinfo("Seçim", "Çıktı almak için bir veya daha fazla makbuz seçin.", parent=app)
            return None
        from makbuz_cikti_ui import makbuz_ciktisi_ac

        return makbuz_ciktisi_ac(app, idler)

    def tumunu_sec(_e=None):
        tablo.selection_set(tablo.get_children())
        return "break"

    def iptal():
        iid = _secili()
        if not iid:
            return
        no = tablo.set(iid, "makbuz_no")
        if no == "—":
            no = tablo.set(iid, "belge")
        virman = iid.startswith("V")
        kk = iid.startswith("K")
        etki = (
            "Müşteri ve tedarikçi cari hareketleri birlikte geri alınır."
            if virman or kk
            else "Cari, kasa/banka ve kart hareketleri geri alınır."
        )
        if not messagebox.askyesno(
            "Makbuzu İptal Et", f"{no} numaralı makbuz iptal edilsin mi?\n\n{etki}", parent=app
        ):
            return
        try:
            if kk:
                KkCekimiService.iptal_et(iid[1:])
            elif virman:
                CariVirmanMakbuzService.iptal(int(iid[1:]))
            else:
                FinansService.kasa_makbuz_iptal(int(iid))
        except (ValueError, PermissionError) as hata:
            messagebox.showerror("İptal", str(hata), parent=app)
            return
        yenile()

    if makbuz_turu in (None, "TAHSILAT"):
        tk_buton(butonlar, "Yeni Tahsilat Makbuzu", lambda: yeni("TAHSILAT"), rol="yeni").pack(side="left", padx=(0, 6))
        tk_buton(butonlar, "Yeni Cari Virman", lambda: yeni("TAHSILAT", "VIRMAN"), rol="yeni").pack(
            side="left", padx=(0, 6)
        )
        tk_buton(butonlar, "Yeni KK ile Tedarikçiye Ödeme", lambda: kk_fisi_ac(), rol="yeni").pack(
            side="left", padx=(0, 6)
        )
    if makbuz_turu in (None, "ODEME"):
        tk_buton(butonlar, "Yeni Ödeme Makbuzu", lambda: yeni("ODEME"), rol="yeni").pack(side="left", padx=(0, 6))
    tk_buton(butonlar, "Görüntüle", goruntule, rol="duzenle").pack(side="left", padx=6)
    tk_buton(butonlar, "Yazdır / PDF / Word", yazdir, rol="yazdir").pack(side="left", padx=6)
    tk_buton(butonlar, "İptal Et", iptal, rol="iptal").pack(side="left", padx=6)
    tk_buton(butonlar, "Yenile", yenile, rol="geri").pack(side="left", padx=6)
    tablo.bind("<Double-1>", goruntule)
    tablo.bind("<Return>", goruntule)
    tablo.bind("<Control-a>", tumunu_sec)
    tablo.bind("<Control-p>", lambda _e: (yazdir(), "break")[1])

    yenile()
    arama.focus_set()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(
            lambda: kasa_makbuzlari_sayfasi(app, makbuz_turu=makbuz_turu, geri_fn=geri_fn)
        )
