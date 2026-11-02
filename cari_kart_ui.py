"""Müşteri / Tedarikçi Cari Hesap Kartı — kurumsal yeniden düzenlenmiş UI.

İş kuralları CariService / mevcut diyalog açıcılarında kalır; bu modül düzen + stil.
"""

from __future__ import annotations

import re
import weakref
import webbrowser
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
import tkinter as tk

from database.cari_service import CariService
from database.stok_service import ALIŞ_FIYAT_ADLARI, SATIS_FIYAT_ADLARI, aktif_satis_fiyat_kodlari, satis_fiyat_gorunen_ad
from database.turkce_normalize import turkce_normalize
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


# Üst panel veri kutuları (v2): H/G Kod–Ünvan’dan ölçülür.
# Kenar: CariKart.TEntry (!focus). clam Entry.field border=1 + light/dark bevel
# görselde ~2 px; Frame highlight=1 ince kalır → salt okunur kutularda 2 px.
VERI_KUTU_BG = BEYAZ
VERI_KUTU_KENAR = "#9e9a91"  # clam TEntry !focus varsayılanı; ölçüm doğrular
VERI_KUTU_KENAR_KALINLIK = 2
VERI_KUTU_YUKSEKLIK_GECICI = 26
VERI_SATIR_BOSLUK_GECICI = 2
VERI_DEGER_PT = 9
VERI_VURGU_PT = 10
UST_ETIKET_PX_GECICI = 120
UST_KOMPAKT_ALANLAR = (
    "ana_kart_turu",
    "musteri_alt_tur",
    "tedarikci_alt_tur",
    "musteri_grubu",
)


def _kod_cerceve_olc(root: tk.Misc | None = None) -> tuple[str, int, str]:
    """Kod (CariKart.TEntry) odaklanmamış çerçeve rengi / görsel kalınlık / alan zemini.

    clam ``Entry.field`` border=1 iken lightcolor+darkcolor çift çizgi (~2 px) üretir.
    tk.Frame ``highlightthickness=1`` tek çizgi kaldığı için salt okunur kutularda 2 kullanılır.
    Kod Entry stilinin kendisi değiştirilmez.
    """
    from tkinter import ttk

    try:
        stil = ttk.Style(root)
        kenar = stil.lookup("CariKart.TEntry", "bordercolor", state=("!focus",)) or stil.lookup(
            "TEntry", "bordercolor", state=("!focus",)
        )
        zemin = stil.lookup("CariKart.TEntry", "fieldbackground") or BEYAZ
        kalinlik = VERI_KUTU_KENAR_KALINLIK
        try:
            # Ölçek: border genişliği temadan; bevel varsa görsel 2
            bw = stil.lookup("CariKart.TEntry", "borderwidth") or stil.lookup("TEntry", "borderwidth")
            light = stil.lookup("TEntry", "lightcolor", state=("!focus",))
            dark = stil.lookup("TEntry", "darkcolor", state=("!focus",))
            if light and dark and str(light).lower() != str(dark).lower():
                kalinlik = max(2, int(bw or 1) + 1)
            elif bw not in (None, "", "0"):
                kalinlik = max(1, int(float(bw)))
        except Exception:
            kalinlik = VERI_KUTU_KENAR_KALINLIK
        if kenar:
            return str(kenar), int(kalinlik), str(zemin) if zemin else BEYAZ
    except Exception:
        pass
    return VERI_KUTU_KENAR, VERI_KUTU_KENAR_KALINLIK, VERI_KUTU_BG


def _izin_var(*kodlar: str) -> bool:
    try:
        from database.session_manager import oturum

        if getattr(oturum, "role_kod", None) == "YONETICI":
            return True
        return any(oturum.has_permission(k) for k in kodlar)
    except Exception:
        return True


def _unvan_arama_gunluk(mesaj: str, **alanlar) -> None:
    """Geçici tanı: gerçek Ünvan arama olayını dosyaya yazar (ekranı kirletmez)."""
    from datetime import datetime
    from pathlib import Path

    try:
        yol = Path(__file__).resolve().parent / "data" / "unvan_arama_debug.log"
        yol.parent.mkdir(parents=True, exist_ok=True)
        parca = " ".join(f"{k}={v!r}" for k, v in alanlar.items())
        with yol.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%H:%M:%S.%f} {mesaj} {parca}\n")
    except Exception:
        pass
    try:
        print(f"[UnvanArama] {mesaj}", alanlar or "")
    except Exception:
        pass


class UnvanAramaKutusu:
    """Ünvan alanına yazınca açılır sonuç listesi.

    Kart ``grab_set`` kullandığı için ayrı Toplevel yerine kart içine ``place``
    edilen bir çerçeve kullanılır; böylece liste grab altında da görünür/seçilebilir.
    Üst panel pack düzeni ve yüksekliği değişmez.
    """

    AZAMI_SONUC = 50
    GECIKME_MS = 180
    MIN_KARAKTER = 2
    # Açık kaydın cari_turu (ör. Müşteri/Tedarikçi) arama kapsamını daraltmaz
    MESAJ_KAYNAGI = "UnvanAramaKutusu._goster"

    def __init__(self, kart: tk.Toplevel, entry: ttk.Entry, *, cari_turu: str, on_secim):
        self.kart = kart
        self.entry = entry
        # Kartın açılış rolü (müşteri/tedarikçi ekranı); açık kaydın türü değil
        self._ekran_rolu = "Tedarikçi" if (cari_turu or "").casefold().startswith("tedarik") else "Müşteri"
        self.cari_turu = self._ekran_rolu
        self.on_secim = on_secim
        self.sonuclar: list = []
        self.bakiyeler: dict = {}
        self.panel: tk.Frame | None = None
        self.liste: ttk.Treeview | None = None
        self._bos_lbl: tk.Label | None = None
        self._zamanlayici = None
        self._son_sorgu = ""
        self._istek_no = 0
        self._secim_yapiliyor = False
        self._programatik = False
        self._panel_yukseklik = 40
        self._son_hata: str | None = None
        # Tek olay zinciri: önce mevcut KeyRelease bağlarını kaldırmadan add=+ ile ekle
        entry.bind("<KeyRelease>", self._tus, add="+")
        entry.bind("<<Paste>>", self._yapistir, add="+")
        entry.bind("<Control-v>", self._yapistir, add="+")
        entry.bind("<Control-V>", self._yapistir, add="+")
        entry.bind("<Down>", self._asagi, add="+")
        entry.bind("<Up>", self._yukari, add="+")
        entry.bind("<Return>", self._enter, add="+")
        entry.bind("<KP_Enter>", self._enter, add="+")
        entry.bind("<Escape>", self._esc, add="+")
        try:
            kart.bind("<Configure>", self._konum_guncelle, add="+")
        except tk.TclError:
            pass
        _unvan_arama_gunluk(
            "BAGLANDI",
            entry_id=str(entry),
            ekran_rolu=self._ekran_rolu,
            kart_cari_turu=getattr(kart, "cari_turu", None),
            modul=__file__,
        )

    def acik_mi(self) -> bool:
        try:
            return self.panel is not None and bool(self.panel.winfo_ismapped())
        except tk.TclError:
            return False

    def programatik_basla(self):
        """Kart doldurulurken arama tetiklenmesin."""
        self._programatik = True
        self.gizle()

    def programatik_bitir(self):
        self._programatik = False
        self._son_sorgu = ""

    def _arama_turu(self) -> str:
        """Açık kartın ``cari_turu`` değerini yok say.

        Yalnız ekran rolü (müşteri kartı / tedarikçi kartı) ve ``tedarikci_modu``
        kullanılır. Müşteri ekranında Müşteri + Müşteri/Tedarikçi (karma) bulunur.
        """
        if getattr(self.kart, "tedarikci_modu", False) or self._ekran_rolu == "Tedarikçi":
            return "Tedarikçi"
        return "Müşteri"

    def _firma_ozeti(self) -> str:
        try:
            from database.session_manager import oturum

            return (
                f"secili={oturum.firma_secili} "
                f"ad={getattr(oturum, 'firma_adi', None) or getattr(oturum, 'firma_kod', None)}"
            )
        except Exception as exc:
            return f"oturum_yok:{exc}"

    def _yapistir(self, _event=None):
        if self._programatik:
            _unvan_arama_gunluk("YAPISTIR_ATLANDI", programatik=True)
            return
        if self._zamanlayici is not None:
            try:
                self.kart.after_cancel(self._zamanlayici)
            except tk.TclError:
                pass
        self._zamanlayici = self.kart.after(self.GECIKME_MS, self.ara)

    def _tus(self, event):
        # Kullanıcı yazmaya başladıysa kart-doldurma korumasını bırak
        if self._programatik and not self._secim_yapiliyor:
            ks = getattr(event, "keysym", "") or ""
            if ks not in (
                "Shift_L",
                "Shift_R",
                "Control_L",
                "Control_R",
                "Alt_L",
                "Alt_R",
            ):
                self.programatik_bitir()
                _unvan_arama_gunluk("PROGRAMATIK_KALDIRILDI", key=ks)
        if self._programatik or self._secim_yapiliyor:
            _unvan_arama_gunluk(
                "TUS_ATLANDI",
                key=getattr(event, "keysym", None),
                programatik=self._programatik,
                secim=self._secim_yapiliyor,
            )
            return
        if event.keysym in (
            "Down",
            "Up",
            "Escape",
            "Return",
            "Tab",
            "KP_Enter",
            "Shift_L",
            "Shift_R",
            "Control_L",
            "Control_R",
            "Alt_L",
            "Alt_R",
        ):
            return
        if self._zamanlayici is not None:
            try:
                self.kart.after_cancel(self._zamanlayici)
            except tk.TclError:
                pass
        self._zamanlayici = self.kart.after(self.GECIKME_MS, self.ara)

    def ara(self, metin: str | None = None) -> list:
        self._zamanlayici = None
        self._son_hata = None
        if self._programatik or self._secim_yapiliyor:
            _unvan_arama_gunluk(
                "ARA_ATLANDI",
                programatik=self._programatik,
                secim=self._secim_yapiliyor,
            )
            return self.sonuclar
        try:
            if not self.entry.winfo_exists():
                return []
            sorgu = (self.entry.get() if metin is None else metin).strip()
        except tk.TclError:
            return []
        if len(sorgu) < self.MIN_KARAKTER:
            self.sonuclar = []
            self._son_sorgu = sorgu
            if sorgu:
                mesaj = (
                    f"Aramak için en az {self.MIN_KARAKTER} karakter yazın "
                    f"(şimdi {len(sorgu)})."
                )
                _unvan_arama_gunluk(
                    "MESAJ_MIN_KARAKTER",
                    kaynak="UnvanAramaKutusu.ara",
                    metin=sorgu,
                    mesaj=mesaj,
                )
                self._goster_mesaj(mesaj)
            else:
                self.gizle()
            return []
        if (
            sorgu == self._son_sorgu
            and self.acik_mi()
            and self.sonuclar
            and self.liste is not None
            and self.liste.get_children()
        ):
            return self.sonuclar
        self._son_sorgu = sorgu
        self._istek_no += 1
        istek = self._istek_no
        tur = self._arama_turu()
        kart_tur = getattr(self.kart, "cari_turu", None)
        firma = self._firma_ozeti()
        _unvan_arama_gunluk(
            "SORGU_BASLADI",
            metin=sorgu,
            filtre_tur=tur,
            kart_cari_turu=kart_tur,
            ekran_rolu=self._ekran_rolu,
            firma=firma,
            entry_id=str(self.entry),
        )
        try:
            # Eksik şema (whatsapp vb.) firmanın eski DB'sinde aramayı düşürmesin
            try:
                from database.cari_kart_sema import schema_hazirla as _cari_sema

                _cari_sema()
            except Exception:
                pass
            ham = CariService.unvan_ara(
                sorgu, cari_turu=tur, limit=self.AZAMI_SONUC, haric_id=None
            )
            sonuclar = []
            for c in ham:
                sonuclar.append(
                    type(
                        "CariAra",
                        (),
                        {
                            "id": int(c.id),
                            "cari_kodu": c.cari_kodu or "",
                            "unvan": c.unvan or "",
                            "cari_turu": c.cari_turu or "",
                        },
                    )()
                )
        except Exception as exc:
            self._son_hata = f"{type(exc).__name__}: {exc}"
            _unvan_arama_gunluk(
                "SORGU_HATA",
                metin=sorgu,
                filtre_tur=tur,
                firma=firma,
                hata=self._son_hata,
            )
            sonuclar = []
        if istek != self._istek_no:
            _unvan_arama_gunluk("SORGU_ESKI_ISTEK", metin=sorgu, istek=istek)
            return self.sonuclar
        try:
            guncel = self.entry.get().strip()
        except tk.TclError:
            return []
        if guncel != sorgu:
            _unvan_arama_gunluk("SORGU_METIN_DEGISTI", eski=sorgu, yeni=guncel)
            return self.sonuclar
        self.sonuclar = sonuclar
        try:
            from database.cari_bakiye_service import liste_bakiyeleri

            self.bakiyeler = liste_bakiyeleri([c.id for c in self.sonuclar])
        except Exception as exc:
            _unvan_arama_gunluk("BAKIYE_HATA", hata=str(exc))
            self.bakiyeler = {}
        self._goster()
        satir = 0
        try:
            if self.liste is not None:
                satir = len([k for k in self.liste.get_children() if str(k).isdigit()])
        except tk.TclError:
            pass
        _unvan_arama_gunluk(
            "SORGU_BITTI",
            metin=sorgu,
            filtre_tur=tur,
            kart_cari_turu=kart_tur,
            firma=firma,
            servis_n=len(sonuclar),
            liste_satir=satir,
            hata=self._son_hata,
            mesaj_kaynagi=self.MESAJ_KAYNAGI if not sonuclar else None,
        )
        return self.sonuclar

    def _panel_kur(self):
        if self.panel is not None:
            try:
                if self.panel.winfo_exists():
                    return
            except tk.TclError:
                pass
        self.panel = tk.Frame(
            self.kart,
            bg=LACIVERT,
            highlightthickness=1,
            highlightbackground=LACIVERT,
            bd=0,
        )
        ic = tk.Frame(self.panel, bg=BEYAZ)
        ic.pack(fill="both", expand=True, padx=1, pady=1)
        self._liste_ic = ic
        self.liste = ttk.Treeview(
            ic,
            columns=("kod", "unvan", "bakiye", "yon", "pb"),
            show="headings",
            selectmode="browse",
            height=8,
        )
        for kolon, baslik, genislik, hiza in (
            ("kod", "Kod", 80, "w"),
            ("unvan", "Ünvan", 280, "w"),
            ("bakiye", "Bakiye", 100, "e"),
            ("yon", "B/A", 60, "center"),
            ("pb", "Döviz", 46, "center"),
        ):
            self.liste.heading(kolon, text=baslik)
            self.liste.column(kolon, width=genislik, anchor=hiza, stretch=kolon == "unvan")
        self._kaydir = ttk.Scrollbar(ic, orient="vertical", command=self.liste.yview)
        self.liste.configure(yscrollcommand=self._kaydir.set)
        self._bos_lbl = tk.Label(
            ic, text="", bg=BEYAZ, fg=METIN, font=font(9, root=self.kart), anchor="w", padx=8, pady=6
        )
        self.liste.bind("<Return>", lambda _e: self._listeden_sec())
        self.liste.bind("<Double-Button-1>", lambda _e: self._listeden_sec())
        self.liste.bind("<Button-1>", self._tik_sec, add="+")
        self.liste.bind("<Escape>", lambda _e: (self.gizle(), self.entry.focus_set()))
        self.liste.bind("<Up>", self._liste_yukari, add="+")
        self.liste.bind("<Down>", self._liste_asagi, add="+")

    def _listeyi_goster_pack(self):
        assert self.liste is not None
        try:
            self._bos_lbl.pack_forget()
        except tk.TclError:
            pass
        if not self.liste.winfo_ismapped():
            self.liste.pack(side="left", fill="both", expand=True)
            self._kaydir.pack(side="right", fill="y")

    def _mesaji_goster_pack(self, metin: str):
        assert self.liste is not None and self._bos_lbl is not None
        try:
            self.liste.pack_forget()
            self._kaydir.pack_forget()
        except tk.TclError:
            pass
        self._bos_lbl.configure(text=metin)
        if not self._bos_lbl.winfo_ismapped():
            self._bos_lbl.pack(fill="x")

    def _goster_mesaj(self, metin: str):
        self._panel_kur()
        self._mesaji_goster_pack(metin)
        self._konumla(40)
        try:
            self.panel.lift()
            self.entry.focus_set()
        except tk.TclError:
            pass

    def _goster(self):
        from database.cari_bakiye_service import bakiye_bilgisi
        from tutar_bicim import tr_tutar

        self._panel_kur()
        assert self.liste is not None and self.panel is not None and self._bos_lbl is not None
        self.liste.delete(*self.liste.get_children())
        if not self.sonuclar:
            if self._son_hata:
                kisa = self._son_hata
                if len(kisa) > 160:
                    kisa = kisa[:157] + "…"
                mesaj = f"Arama hatası: {kisa}"
                kaynak = "UnvanAramaKutusu._goster/hata"
            else:
                mesaj = "Sonuç bulunamadı"
                kaynak = "UnvanAramaKutusu._goster/bos"
            _unvan_arama_gunluk("MESAJ_GOSTER", kaynak=kaynak, mesaj=mesaj)
            self._mesaji_goster_pack(mesaj)
            yukseklik = 56 if self._son_hata else 40
        else:
            self._listeyi_goster_pack()
            for i, c in enumerate(self.sonuclar):
                bilgi = bakiye_bilgisi(
                    self.bakiyeler.get(c.id, 0),
                    tedarikci_modu=(c.cari_turu or "") == "Tedarikçi",
                )
                self.liste.insert(
                    "",
                    "end",
                    iid=str(i),
                    values=(
                        c.cari_kodu or "",
                        c.unvan or "",
                        tr_tutar(bilgi["tutar"]),
                        bilgi["yon"],
                        bilgi["para_birimi"],
                    ),
                )
            if len(self.sonuclar) >= self.AZAMI_SONUC:
                self.liste.insert(
                    "",
                    "end",
                    iid="fazla",
                    values=("", "… daha fazla sonuç var, aramayı daraltın", "", "", ""),
                )
            satir = min(10, max(1, len([k for k in self.liste.get_children() if str(k).isdigit()])))
            self.liste.configure(height=satir)
            yukseklik = satir * 24 + 32
        self._konumla(yukseklik)
        try:
            self.panel.lift()
            self.entry.focus_set()
        except tk.TclError:
            pass

    def _konumla(self, yukseklik: int | None = None):
        if self.panel is None:
            return
        try:
            self.kart.update_idletasks()
            self.entry.update_idletasks()
            kx = int(self.kart.winfo_rootx())
            ky = int(self.kart.winfo_rooty())
            ex = int(self.entry.winfo_rootx()) - kx
            ey = int(self.entry.winfo_rooty()) - ky + max(int(self.entry.winfo_height()), 22)
            genislik = max(int(self.entry.winfo_width()), 560)
            if yukseklik is None:
                yukseklik = self._panel_yukseklik
            yukseklik = max(36, int(yukseklik))
            self._panel_yukseklik = yukseklik
            max_y = max(40, int(self.kart.winfo_height()) - yukseklik - 8)
            if ey > max_y:
                ey = max(0, int(self.entry.winfo_rooty()) - ky - yukseklik - 2)
            max_x = max(0, int(self.kart.winfo_width()) - genislik - 4)
            if ex > max_x:
                ex = max_x
            self.panel.place(x=ex, y=ey, width=genislik, height=yukseklik)
        except tk.TclError:
            pass

    def _konum_guncelle(self, _event=None):
        # place/Configure döngüsünde yüksekliği reqheight ile ezme
        if self.acik_mi():
            self._konumla(self._panel_yukseklik)

    def gizle(self):
        if self._zamanlayici is not None:
            try:
                self.kart.after_cancel(self._zamanlayici)
            except tk.TclError:
                pass
            self._zamanlayici = None
        if self.panel is not None:
            try:
                self.panel.place_forget()
            except tk.TclError:
                pass

    def sec(self, indeks: int) -> None:
        if not (0 <= indeks < len(self.sonuclar)):
            return
        if self._secim_yapiliyor:
            return
        self._secim_yapiliyor = True
        cari = self.sonuclar[indeks]
        self.gizle()
        try:
            self.on_secim(cari)
        finally:
            self._secim_yapiliyor = False

    def _listeden_sec(self, _event=None):
        if self.liste is None:
            return "break"
        secim = self.liste.selection()
        if secim and str(secim[0]).isdigit():
            self.sec(int(secim[0]))
        return "break"

    def _tik_sec(self, event):
        """Fare tıklaması: satır seçildikten sonra kimlikle yükle (FocusOut yok)."""
        if self.liste is None:
            return
        satir = self.liste.identify_row(event.y)
        if not satir or not str(satir).isdigit():
            return
        self.liste.selection_set(satir)
        self.liste.focus(satir)
        # Tıklama işlendikten sonra seç — çift yüklemeyi önle
        self.kart.after_idle(lambda s=satir: self.sec(int(s)) if str(s).isdigit() else None)

    def _asagi(self, _event=None):
        if not self.acik_mi():
            self.ara()
        if not self.acik_mi() or self.liste is None or not self.sonuclar:
            return "break"
        kids = [k for k in self.liste.get_children() if str(k).isdigit()]
        if not kids:
            return "break"
        secim = self.liste.selection()
        if not secim:
            hedef = kids[0]
        else:
            try:
                i = kids.index(secim[0])
                hedef = kids[min(i + 1, len(kids) - 1)]
            except ValueError:
                hedef = kids[0]
        self.liste.selection_set(hedef)
        self.liste.focus(hedef)
        self.liste.see(hedef)
        return "break"

    def _yukari(self, _event=None):
        if not self.acik_mi() or self.liste is None or not self.sonuclar:
            return "break"
        kids = [k for k in self.liste.get_children() if str(k).isdigit()]
        if not kids:
            return "break"
        secim = self.liste.selection()
        if not secim:
            hedef = kids[-1]
        else:
            try:
                i = kids.index(secim[0])
                hedef = kids[max(i - 1, 0)]
            except ValueError:
                hedef = kids[-1]
        self.liste.selection_set(hedef)
        self.liste.focus(hedef)
        self.liste.see(hedef)
        return "break"

    def _liste_asagi(self, event):
        return self._asagi(event)

    def _liste_yukari(self, event):
        return self._yukari(event)

    def _enter(self, _event=None):
        if not self.acik_mi() or not self.sonuclar:
            return None
        if self.liste is None:
            return "break"
        secim = self.liste.selection()
        # Yazarken otomatik ilk satır seçilmez; Enter yalnız vurgulu satırdaysa yükler
        if secim and str(secim[0]).isdigit():
            self.sec(int(secim[0]))
            return "break"
        return "break"

    def _esc(self, _event=None):
        if self.acik_mi():
            self.gizle()
            return "break"
        return None


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


class GrupTasimaDialog(tk.Toplevel):
    """Kullanımdaki grubu silmeden önce kartların taşınacağı hedef grubu seçtirir."""

    def __init__(self, parent, grup_adi: str, bilgi: dict):
        super().__init__(parent)
        self.result: str | None = None
        self.title("Grubu Sil")
        self.transient(parent)
        self.resizable(False, False)
        self.configure(bg=ACIK_BG)
        kart, ic = beyaz_kart(self, padx=14, pady=12)
        kart.pack(fill="both", expand=True, padx=10, pady=10)
        satirlar = []
        toplam = bilgi["cari_sayisi"] + bilgi.get("silinmis_sayisi", 0)
        if toplam:
            pasif = bilgi["cari_sayisi"] - bilgi["aktif_sayisi"]
            ekler = [f"{pasif} pasif"] if pasif else []
            if bilgi.get("silinmis_sayisi"):
                ekler.append(f"{bilgi['silinmis_sayisi']} silinmiş/arşiv")
            ek = f" ({', '.join(ekler)})" if ekler else ""
            satirlar.append(f"«{grup_adi}» grubunu {toplam} cari kart kullanıyor{ek}.")
        for rol in bilgi.get("roller") or []:
            satirlar.append(f"Sistem bağlantısı: {rol}.")
        satirlar.append("Silmeden önce kartlar ve bağlantılar seçeceğiniz gruba taşınacak.")
        tk.Label(
            ic, text="\n".join(satirlar),
            bg=BEYAZ, fg=LACIVERT, font=font(10, root=self), justify="left",
        ).pack(anchor="w", pady=(0, 8))
        satir = tk.Frame(ic, bg=BEYAZ)
        satir.pack(fill="x")
        tk.Label(satir, text="Hedef grup:", bg=BEYAZ, fg=LACIVERT, font=font(9, "bold", self)).pack(side="left")
        self.hedef = ttk.Combobox(satir, state="readonly", values=list(bilgi["hedefler"]), width=28)
        self.hedef.pack(side="left", padx=(6, 0), fill="x", expand=True)
        self.hedef.set("Hedef grup seçiniz")
        self.uyari = tk.Label(ic, text="", bg=BEYAZ, fg=UYARI, font=font(8, "bold", self))
        self.uyari.pack(anchor="w", pady=(4, 0))
        alt = tk.Frame(ic, bg=BEYAZ)
        alt.pack(fill="x", pady=(10, 0))
        tk_buton(alt, "Vazgeç", self.destroy, rol="ikincil").pack(side="right")
        tk_buton(alt, "Taşı ve Sil", self._onayla, rol="tehlike").pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()
        self.hedef.focus_set()

    def _onayla(self):
        hedef = self.hedef.get()
        if hedef not in self.hedef["values"]:
            self.uyari.configure(text="Taşınacak hedef grubu seçin.")
            return
        self.result = hedef
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
            text=("Hesap koduna 3 hane yazın veya F2 / … ile seçin. Sağ tık: «Alt hesap seç» "
                  "veya «Hesap kartını aç»."),
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
        from database.muhasebe_service import HesapPlanService
        from hesap_kodu_sec_ui import HesapKoduSecDialog

        dlg = HesapKoduSecDialog(self, onek=(giris.get() or "").strip())
        self.wait_window(dlg)
        if dlg.result:
            try:
                HesapPlanService.alt_hesap_dogrula(dlg.result)
            except (PermissionError, ValueError) as hata:
                messagebox.showwarning("Hesap seçimi", str(hata), parent=self)
                return
            giris.delete(0, "end")
            giris.insert(0, dlg.result)

    def tamam(self):
        self.result = {alan: giris.get().strip() for alan, giris in self.alanlar.items()}
        self.destroy()


class CariDialog(tk.Toplevel):
    # Risk limitleri ve vade farkı oranları RiskLimitPaneli üzerinden (cari_risk_service) kaydedilir.
    SAYISAL_TUTAR_ALANLARI: tuple[str, ...] = ()
    SAYISAL_GUN_ALANLARI = ("satis_vade_gunu", "alis_vade_gunu")
    MUHASEBE_ALANLARI = tuple(alan for _etiket, alan in CariMuhasebeDialog.ALANLAR)
    _acik_kartlar: "weakref.WeakSet[CariDialog]" = weakref.WeakSet()

    def __init__(self, parent: tk.Misc, cari=None, cari_turu: str = "Müşteri"):
        super().__init__(parent)
        self.cari = cari
        self.result = None
        self._vazgecildi = False
        # True → kapanınca ana uygulamayı Satışlar'a (müşteri) döndür
        self._donus_ana_menu = False
        if not self._onceki_kartlari_kapat(parent):
            # Kullanıcı eski kartta kalmayı seçti; çağıranın wait_window'u için pencere kısa süre yaşar
            self._vazgecildi = True
            self.withdraw()
            self.after(0, self.destroy)
            return
        CariDialog._acik_kartlar.add(self)
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
        # transient kullanma — Windows —/□/✕ ve iconify için gerekli
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
        self.bind("<Escape>", self._escape_tus)
        self.bind("<F10>", self._hizli_cari_ara)

        self._yenile_token = 0
        self._makbuz_acik = False
        self._ust_baslik_olustur()
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

        # Üst paneller sabit yükseklik; kazanılan alan Cari Hareketler'e (expand)
        self.icerik = tk.Frame(self, bg=ACIK_BG)
        self.icerik.pack(fill="x", padx=10, pady=4)
        self.canvas = None  # eski kaydırma alanı kaldırıldı
        self._ana_kolonlari_olustur()
        self._detay_seridini_olustur(self.icerik)
        self._hizli_islem_maddelerini_hazirla()
        self._hareket_alan = tk.Frame(self, bg=ACIK_BG)
        self._hareket_alan.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self._hareket_tablosunu_olustur(self._hareket_alan)

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

    # ─── Üst chrome ───────────────────────────────────────────────
    def _ust_baslik_olustur(self):
        ust = tk.Frame(self, bg=LACIVERT)
        self._ust_cerceve = ust
        ust.pack(fill="x")
        ust.columnconfigure(1, weight=1)
        sol = tk.Frame(ust, bg=LACIVERT)
        sol.grid(row=0, column=0, sticky="nsw", padx=14, pady=10)
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
        sag.grid(row=0, column=1, sticky="nsew", padx=10, pady=8)
        btn_satir = tk.Frame(sag, bg=LACIVERT)
        btn_satir.pack(fill="x")
        self.kaydet_btn = tk_buton(btn_satir, "Kaydet (F1)", self.kaydet, rol="kaydet")
        self.kaydet_btn.pack(side="left", padx=3)
        tk_buton(btn_satir, "Kaydet ve Kapat", self.kaydet_ve_kapat, rol="vurgu").pack(
            side="left", padx=3
        )
        # Boş kartta yeni kayıt akışı: formu doldur → Kaydet (F1)
        tk_buton(btn_satir, "Yeni", self.yeni_kart, rol="vurgu").pack(side="left", padx=3)
        self._hizli_islem_btn = tk_buton(
            btn_satir, "Hızlı İşlemler ▾", self._hizli_islemler_menu_ac, rol="vurgu"
        )
        self._hizli_islem_btn.pack(side="left", padx=3)
        ToolTip(self._hizli_islem_btn, "Sipariş, fatura, tahsilat ve diğer cari işlemler")
        self._pasif_btn = tk_buton(btn_satir, "Pasife Al", self.durumu_degistir, rol="tehlike")
        self._pasif_btn_yeri = tk.Frame(btn_satir, bg=LACIVERT)
        self._pasif_btn_yeri.pack(side="left")
        self._pasif_btn.pack(in_=self._pasif_btn_yeri, side="left", padx=3)
        self._pasif_btn_guncelle()
        liste_btn = tk_buton(btn_satir, "Cari Hesap Listesi", self.cari_listesi_ac, rol="ikincil")
        liste_btn.pack(side="left", padx=(10, 3))
        ToolTip(liste_btn, "Ana penceredeki cari hesap listesini açar; bu kart açık kalır.")
        stok_btn = tk_buton(btn_satir, "Stok Kartları Listesi", self.stok_listesi_ac, rol="ikincil")
        stok_btn.pack(side="left", padx=3)
        ToolTip(stok_btn, "Ana penceredeki stok kartları listesini açar; bu kart açık kalır.")
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
        from ui_pencere import sarmali_yerlestir

        sarmali_yerlestir(
            btn_satir,
            [w for w in btn_satir.winfo_children() if w is not self._pasif_btn],
            yasla="e",
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
        grup = self._widget_deger("musteri_grubu") if "musteri_grubu" in self.degerler else ""
        self._rozet_grup.configure(text=f"Grup: {grup}" if grup else "Grup: —")

    def _pasif_btn_guncelle(self):
        btn = getattr(self, "_pasif_btn", None)
        if btn is None:
            return
        if not self.cari:
            btn.pack_forget()
            return
        aktif = bool(self.cari.aktif)
        btn.configure(
            text="Pasife Al" if aktif else "Aktif Et",
            bg=UYARI if aktif else BASARI,
            activebackground="#B91C1C" if aktif else "#166534",
            highlightbackground=UYARI if aktif else BASARI,
        )
        if not btn.winfo_ismapped():
            btn.pack(in_=self._pasif_btn_yeri, side="left", padx=3)

    # ─── Liste ekranları (ana pencere) ────────────────────────────
    def _ana_uygulama(self):
        kok = self._root()
        return kok if hasattr(kok, "sayfa_goster") else None

    def _ana_pencereye_gec(self, komut) -> None:
        """Kart açık ve değişiklikleri korunur; kart kipliği bırakılıp ana pencere öne alınır."""
        app = self._ana_uygulama()
        if app is None:
            messagebox.showinfo("Liste", "Ana pencere bulunamadı.", parent=self)
            return
        try:
            self.grab_release()
        except tk.TclError:
            pass
        try:
            if str(app.state()) == "iconic":
                app.deiconify()
            app.lift()
            app.focus_force()
        except tk.TclError:
            pass
        komut(app)

    def cari_listesi_ac(self):
        def _ac(app):
            if self.tedarikci_modu:
                app.tedarikciler_goster()
            else:
                app.cariler_goster()

        self._ana_pencereye_gec(_ac)

    def stok_listesi_ac(self):
        def _ac(app):
            if getattr(app, "_aktif_sayfa", None) == "stoklar":
                app._menu_islemi(app.stok_kartlari_goster)
                return
            app.sayfa_goster("stoklar", ust_duzey=True)

            def _bekle(deneme=0):
                if getattr(app, "_aktif_sayfa", None) == "stoklar" and not getattr(app, "_busy_pending", False):
                    app._menu_islemi(app.stok_kartlari_goster)
                elif deneme < 50:
                    app.after(60, lambda: _bekle(deneme + 1))

            app.after(60, _bekle)

        self._ana_pencereye_gec(_ac)

    # ─── Cari seçimi: F10 / sağ tık menüleri ──────────────────────
    def _kod_sag_tik(self, event):
        """Kod alanı sağ tık: kod sırasının sonundaki en fazla 10 cari (en büyük kod üstte)."""
        try:
            kayitlar = CariService.son_kodlar(self.cari_turu, limit=10)
        except Exception as hata:
            messagebox.showerror("Cari", f"Liste alınamadı:\n{hata}", parent=self)
            return "break"
        menu = tk.Menu(self, tearoff=0, font=("Consolas", 9))
        if not kayitlar:
            menu.add_command(label="Kayıt yok", state="disabled")
        from tutar_bicim import tr_tutar

        for k in kayitlar:
            etiket = (f"{k['cari_kodu']:<10} {k['unvan'][:34]:<34} "
                      f"{tr_tutar(k['tutar']):>15} {k['para_birimi']} {k['yon']}")
            menu.add_command(label=etiket, command=lambda cid=k["id"]: self._cariye_gec_id(cid))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _cariye_gec_id(self, cari_id: int):
        cari = CariService.getir(int(cari_id))
        if cari is None:
            messagebox.showwarning("Cari", "Kayıt bulunamadı.", parent=self)
            return
        self._cariye_gec(cari)

    def _unvan_sag_tik(self, _event=None):
        self._unvan_arama.gizle()
        self._hizli_cari_ara()
        return "break"

    def _hizli_cari_ara(self, _event=None):
        """F10 / ünvan sağ tık: bakiyeli seçim listesi; seçilen cari bu karta yüklenir."""
        ara = ""
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

    def _escape_tus(self, _event=None):
        """Önce ünvan arama listesini kapat; yoksa kartı kapatmayı sor."""
        arama = getattr(self, "_unvan_arama", None)
        if arama is not None and arama.acik_mi():
            arama.gizle()
            return "break"
        self._kapat_istegi()
        return "break"

    def _unvandan_cariye_gec(self, cari):
        """Ünvan aramasından seçim: aranan metin karta ait değişiklik sayılmaz."""
        arama = getattr(self, "_unvan_arama", None)
        if arama is not None:
            arama.programatik_basla()
        try:
            w = self.degerler.get("unvan")
            if w is not None:
                w.delete(0, "end")
                w.insert(0, (getattr(self.cari, "unvan", None) or "") if self.cari else "")
            self._cariye_gec(cari)
        finally:
            if arama is not None:
                # Yükleme bittikten sonra korumayı kaldır
                self.after(50, arama.programatik_bitir)

    def _cariye_gec(self, cari):
        """Seçilen kaydı aynı pencerede yerinde yükler (pencere kapanıp açılmaz)."""
        if cari is None:
            return
        if self.cari is not None and getattr(self.cari, "id", None) == getattr(cari, "id", None):
            return
        if not self._kapatmadan_once_onay():
            return
        tur = (getattr(cari, "cari_turu", None) or self.cari_turu) or "Müşteri"
        if (tur == "Tedarikçi") != self.tedarikci_modu:
            parent = self.master
            self.destroy()
            CariDialog(parent, cari=cari, cari_turu=tur)
            return
        self._cariyi_yukle(cari)

    def _formu_temizle(self):
        for alan, widget in self.degerler.items():
            if alan == "aktif":
                continue
            try:
                if isinstance(widget, tk.Text):
                    widget.delete("1.0", "end")
                    widget.edit_modified(False)
                elif isinstance(widget, ttk.Combobox):
                    widget.set(self._varsayilan_tipler.get(alan, ""))
                else:
                    onceki = str(widget.cget("state"))
                    widget.configure(state="normal")
                    widget.delete(0, "end")
                    if onceki != "normal":
                        widget.configure(state=onceki)
            except tk.TclError:
                pass

    def _cariyi_yukle(self, cari) -> None:
        """Kartı başka bir cariye (veya boş yeni karta) yerinde geçirir; odak ve pencere korunur."""
        if cari is not None and getattr(cari, "id", None):
            taze = CariService.getir(int(cari.id))
            if taze is None:
                messagebox.showwarning("Cari", "Kayıt bulunamadı veya silinmiş.", parent=self)
                return
            cari = taze
        self._yenile_token += 1
        self._yenile_devam = None
        self._yukleniyor = False
        if hasattr(self, "_yukleniyor_lbl"):
            self._yukleniyor_lbl.configure(text="")
        self.cari = cari
        self.result = None
        self._fatura_detay_cache = {}
        self._hareketler_cache = []
        self.muhasebe = {
            alan: (getattr(cari, alan, None) or "") if cari else "" for alan in self.MUHASEBE_ALANLARI
        }
        self.uyari_notu = (getattr(cari, "uyari_notu", None) or "") if cari else ""
        arama = getattr(self, "_unvan_arama", None)
        if arama is not None:
            arama.programatik_basla()
        self._unvan_arama.gizle()
        self._formu_temizle()
        self.degerler["aktif"].set(bool(cari.aktif) if cari else True)
        self._alanlari_doldur()
        if arama is not None:
            self.after(80, arama.programatik_bitir)
        self.musteri_grubu_secimini_hazirla()
        self._grup_uyarisi_goster(False)
        if getattr(self, "risk_paneli", None) is not None:
            self.risk_paneli.risk_goster(None)
        self._ozet_kartlarini_guncelle(None)
        if self.hareket_tablosu is not None:
            self.hareket_tablosu.delete(*self.hareket_tablosu.get_children())
        self.not_durumunu_guncelle()
        self.uyari_durumunu_guncelle(self.uyari_notu)
        if hasattr(self, "not_butonu"):
            self.not_butonu.configure(state="normal" if cari else "disabled")
        self._pasif_btn_guncelle()
        self._hizli_dugmeleri_ayarla()
        if hasattr(self, "_soz_ozet_lbl"):
            self._soz_ozet_lbl.configure(text="")
        panel = getattr(self, "_yetkili_panel", None)
        if panel is not None:
            panel.cari_degisti()
        if getattr(self, "foto_alani", None) is not None:
            self.foto_alani.sahip_ata(getattr(cari, "id", None))
        self._snapshot = self._form_snapshot()
        self._kirli = False
        self._baslik_rozetlerini_guncelle()
        self._uyari_bandini_guncelle()
        try:
            if getattr(self, "canvas", None) is not None:
                self.canvas.yview_moveto(0)
        except tk.TclError:
            pass
        if cari:
            self.yenile()
        self.degerler["unvan"].focus_set()

    def _onceki_kartlari_kapat(self, parent) -> bool:
        """Açık başka cari kart varsa kapatır; kaydedilmemiş değişiklikte kullanıcıya sorar.

        Yeni kartın üst penceresi olan kart (iç içe açılış) kapatılmaz.
        """
        atalar: set[int] = set()
        w = parent
        while w is not None:
            atalar.add(id(w))
            w = getattr(w, "master", None)
        for kart in list(CariDialog._acik_kartlar):
            if kart is self or id(kart) in atalar:
                continue
            try:
                if not kart.winfo_exists():
                    CariDialog._acik_kartlar.discard(kart)
                    continue
                # Karttan açılmış belge penceresi varsa kapatmak o belgeyi de yok eder
                if any(
                    isinstance(c, tk.Toplevel) and c.winfo_viewable()
                    for c in kart.winfo_children()
                ):
                    continue
                kart.lift()
            except tk.TclError:
                CariDialog._acik_kartlar.discard(kart)
                continue
            if not kart._kapatmadan_once_onay():
                return False
            kart.destroy()
        return True

    # ─── Ana kolonlar ─────────────────────────────────────────────
    def _ana_kolonlari_olustur(self):
        from cari_foto_ui import FotoAlani

        ust = tk.Frame(self.icerik, bg=ACIK_BG)
        ust.pack(fill="x", pady=(0, 4))
        # Fotoğraf ≈ %16, diğer üç panel ≈ %28 (aynı uniform grupta ağırlık oranı korunur)
        for i, agirlik in enumerate((4, 7, 7, 7)):
            ust.columnconfigure(i, weight=agirlik, uniform="cari_ust")
        ust.rowconfigure(0, weight=0)

        self._ust_veri_satirlari: list[tk.Frame] = []
        self._ust_form_satirlari: dict[str, tk.Frame] = {}
        self._ust_tum_form_satirlari: list[tk.Frame] = []
        self._ust_deger_cerceveleri: list[tk.Frame] = []
        self._ust_yan_dugmeler: list[tk.Button] = []
        self._ust_etiket_lbl: list[tk.Label] = []
        kenar, kalinlik, zemin = _kod_cerceve_olc(self)
        self._ust_kenar = kenar
        self._ust_kenar_kalinlik = kalinlik
        self._ust_kutu_bg = zemin
        self._ust_H = VERI_KUTU_YUKSEKLIK_GECICI
        self._ust_G = VERI_SATIR_BOSLUK_GECICI
        self._ust_etiket_px = UST_ETIKET_PX_GECICI

        # Üç veri paneli aynı iç boşluk — sağ girinti çerçeveye göre eşit
        _ust_padx, _ust_pady = 6, 4
        p0_dis, p0 = beyaz_kart(ust, padx=_ust_padx, pady=_ust_pady)
        p0_dis.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        p1_dis, p1 = beyaz_kart(ust, padx=_ust_padx, pady=_ust_pady)
        p1_dis.grid(row=0, column=1, sticky="nsew", padx=(0, 4))
        p2_dis, p2 = beyaz_kart(ust, padx=_ust_padx, pady=_ust_pady)
        p2_dis.grid(row=0, column=2, sticky="nsew", padx=(0, 4))
        p3_dis, p3 = beyaz_kart(ust, padx=_ust_padx, pady=_ust_pady)
        p3_dis.grid(row=0, column=3, sticky="nsew")
        self._ust_panel_dis = (p0_dis, p1_dis, p2_dis, p3_dis)
        self._ust_foto_ic = p0

        self.foto_alani = FotoAlani(p0, sahip_turu="CARI", baslik="Cari Fotoğrafı")
        self.foto_alani.pack(fill="both", expand=True)
        self._musteri_formu(p1)
        self._ticari_risk_paneli(p2)
        self._bakiye_ozet_paneli(p3)
        if self.cari:
            self.after(120, lambda: self.foto_alani.sahip_ata(self.cari.id) if self.cari else None)
        # v2: Kod kutusundan H/G + etiket sütunu ölç → tüm üst kutulara uygula
        self.after_idle(self._ust_olculeri_uygula)

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
        kw.setdefault("style", "CariKart.TEntry")
        w = ttk.Entry(parent, width=width, **kw)
        self.degerler[alan] = w
        return w

    def _bolum_baslik(self, parent, metin):
        tk.Label(
            parent, text=metin, bg=BEYAZ, fg=LACIVERT, font=font(9, "bold", self)
        ).pack(anchor="w", pady=(0, 2))

    def _ust_satir_grid(self, satir: tk.Frame, lbl: tk.Label, sag: tk.Frame):
        """Etiket | değer çerçevesi — üç panelde aynı başlangıç ve sağa kadar uzama."""
        etiket_px = getattr(self, "_ust_etiket_px", UST_ETIKET_PX_GECICI)
        satir.columnconfigure(0, minsize=etiket_px, weight=0)
        satir.columnconfigure(1, weight=1)
        satir.rowconfigure(0, weight=1)
        lbl.grid(row=0, column=0, sticky="nw", padx=(0, 6))
        sag.grid(row=0, column=1, sticky="nsew")

    def _ust_deger_cerceve(self, parent) -> tk.Frame:
        """Kod (Entry !focus) ile aynı kalınlık/renk — CIZGI değil."""
        kenar = getattr(self, "_ust_kenar", VERI_KUTU_KENAR)
        kalinlik = getattr(self, "_ust_kenar_kalinlik", VERI_KUTU_KENAR_KALINLIK)
        zemin = getattr(self, "_ust_kutu_bg", VERI_KUTU_BG)
        kutu = tk.Frame(
            parent,
            bg=zemin,
            highlightthickness=kalinlik,
            highlightbackground=kenar,
            highlightcolor=kenar,
            padx=6,
            pady=0,
        )
        self._ust_deger_cerceveleri.append(kutu)
        return kutu

    def _ust_yan_dugme(self, parent, metin: str, komut) -> tk.Button:
        """Üst panel yan düğmesi — satır yüksekliğini H üstüne çıkarmasın."""
        dugme = tk_buton(parent, metin, komut, rol="ikincil")
        kenar = getattr(self, "_ust_kenar", VERI_KUTU_KENAR)
        try:
            dugme.configure(
                padx=4,
                pady=0,
                font=font(8, "bold", self),
                highlightthickness=1,
                highlightbackground=kenar,
                highlightcolor=kenar,
            )
        except tk.TclError:
            pass
        self._ust_yan_dugmeler.append(dugme)
        return dugme

    def _form_satiri(self, parent, etiket: str, etiket_genislik: int = 11, *, alan_anahtar: str | None = None):
        """Etiket solda, giriş alanı sağda.

        Kod/Ünvan satırlarında pack_propagate açık kalır (ünvan araması).
        Kompakt (düğmeli) satırlar ölçümde H'ye kilitlenir.
        """
        del etiket_genislik  # sabit px sütun; karakter width kullanılmaz
        g = getattr(self, "_ust_G", VERI_SATIR_BOSLUK_GECICI)
        satir = tk.Frame(parent, bg=BEYAZ)
        satir.pack(fill="x", pady=(0, g))
        lbl = self._etiket(satir, etiket)
        self._ust_etiket_lbl.append(lbl)
        sag = tk.Frame(satir, bg=BEYAZ)
        self._ust_satir_grid(satir, lbl, sag)
        self._ust_tum_form_satirlari.append(satir)
        if alan_anahtar:
            self._ust_form_satirlari[alan_anahtar] = satir
        return sag

    def _veri_kutu_satiri(
        self,
        parent,
        baslik: str,
        *,
        etiket_genislik: int = 16,
        deger_pt: int = VERI_DEGER_PT,
        kalin: bool = False,
    ):
        """Çerçeveli değer satırı; yükseklik H, kenar = Kod Entry !focus."""
        del etiket_genislik
        h = getattr(self, "_ust_H", VERI_KUTU_YUKSEKLIK_GECICI)
        g = getattr(self, "_ust_G", VERI_SATIR_BOSLUK_GECICI)
        zemin = getattr(self, "_ust_kutu_bg", VERI_KUTU_BG)
        satir = tk.Frame(parent, bg=BEYAZ, height=h)
        satir.pack(fill="x", pady=(0, g))
        satir.pack_propagate(False)
        lbl = self._etiket(satir, baslik)
        self._ust_etiket_lbl.append(lbl)
        kutu = self._ust_deger_cerceve(satir)
        self._ust_satir_grid(satir, lbl, kutu)
        deger = tk.Label(
            kutu,
            text="—",
            bg=zemin,
            fg=LACIVERT,
            font=font(deger_pt, "bold" if kalin else "normal", self),
            anchor="e",
        )
        deger.pack(fill="both", expand=True)
        self._ust_veri_satirlari.append(satir)
        return lbl, deger, satir

    def _ozet_deger_satiri(self, parent, baslik: str, *, kalin: bool = False, buyuk: bool = False):
        """Sol etiket + sağ çerçeve; yalnız Kalan Bakiye / Gün değer yazısı vurgulu (kutu H)."""
        from cari_borc_alacak_ozet import BUYUK_SATIRLAR

        buyuk = buyuk or baslik in BUYUK_SATIRLAR
        if baslik in ("Kalan Bakiye", "Kalan Bakiye Gün") or buyuk:
            deger_pt, kalin = VERI_VURGU_PT, True
        else:
            deger_pt, kalin = VERI_DEGER_PT, False
        lbl, deger, _satir = self._veri_kutu_satiri(
            parent, baslik, deger_pt=deger_pt, kalin=kalin
        )
        self.ozet_degerleri[baslik] = deger
        return lbl, deger

    def _ust_olculeri_uygula(self):
        """H/G Kod–Ünvan veri kutusu kenarlarından; çerçeve = Kod Entry !focus."""
        kod = self.degerler.get("cari_kodu")
        unvan = self.degerler.get("unvan")
        if kod is None:
            return
        try:
            self.update_idletasks()
            h = int(kod.winfo_height())
        except tk.TclError:
            return
        if h < 18:
            h = VERI_KUTU_YUKSEKLIK_GECICI
        # G: Kod alt kenarı ↔ Ünvan üst kenarı (widget, satır çerçevesi değil)
        g = VERI_SATIR_BOSLUK_GECICI
        if unvan is not None:
            try:
                self.update_idletasks()
                gap = int(unvan.winfo_rooty()) - (int(kod.winfo_rooty()) + int(kod.winfo_height()))
                if gap >= 0:
                    g = gap
            except tk.TclError:
                pass
        kenar, kalinlik, zemin = _kod_cerceve_olc(self)
        self._ust_kenar = kenar
        self._ust_kenar_kalinlik = kalinlik
        self._ust_kutu_bg = zemin
        etiket_px = UST_ETIKET_PX_GECICI
        try:
            self.update_idletasks()
            genislikler = []
            for lbl in getattr(self, "_ust_etiket_lbl", []):
                try:
                    genislikler.append(int(lbl.winfo_reqwidth()))
                except tk.TclError:
                    pass
            if genislikler:
                etiket_px = max(genislikler) + 6
        except tk.TclError:
            pass
        self._ust_H = h
        self._ust_G = g
        self._ust_etiket_px = etiket_px
        # Salt okunur özet / risk kutuları
        for satir in list(self._ust_veri_satirlari):
            try:
                satir.configure(height=h)
                satir.pack_configure(pady=(0, g))
                satir.pack_propagate(False)
                satir.columnconfigure(0, minsize=etiket_px, weight=0)
                satir.columnconfigure(1, weight=1)
            except tk.TclError:
                pass
        for kutu in list(getattr(self, "_ust_deger_cerceveleri", [])):
            try:
                kutu.configure(
                    bg=zemin,
                    highlightthickness=kalinlik,
                    highlightbackground=kenar,
                    highlightcolor=kenar,
                )
                for cocuk in kutu.winfo_children():
                    try:
                        if isinstance(cocuk, tk.Label):
                            cocuk.configure(bg=zemin)
                    except tk.TclError:
                        pass
            except tk.TclError:
                pass
        for dugme in list(getattr(self, "_ust_yan_dugmeler", [])):
            try:
                dugme.configure(
                    highlightbackground=kenar,
                    highlightcolor=kenar,
                    pady=0,
                    font=font(8, "bold", self),
                )
            except tk.TclError:
                pass
        # Form satırları: G boşluk; kompakt satırlar H kilidi (düğme şişirmesin)
        for anahtar, satir in list(self._ust_form_satirlari.items()):
            try:
                satir.pack_configure(pady=(0, g))
                satir.columnconfigure(0, minsize=etiket_px, weight=0)
                satir.columnconfigure(1, weight=1)
                if anahtar in UST_KOMPAKT_ALANLAR:
                    satir.configure(height=h)
                    satir.pack_propagate(False)
                else:
                    # Kod / Ünvan vb. doğal yükseklik
                    try:
                        satir.pack_propagate(True)
                    except tk.TclError:
                        pass
            except tk.TclError:
                pass
        for satir in list(self._ust_tum_form_satirlari):
            if satir in self._ust_form_satirlari.values():
                continue
            try:
                satir.pack_configure(pady=(0, g))
                satir.columnconfigure(0, minsize=etiket_px, weight=0)
                satir.columnconfigure(1, weight=1)
            except tk.TclError:
                pass
        # Fotoğraf + hareket alanı kazanılan yüksekliği alsın
        self.after(30, self._ust_foto_yukseklik_uygula)
        self.after(60, self._hareket_yukseklik_ayarla)

    def _ust_foto_yukseklik_uygula(self):
        """Cari Fotoğrafı alanını üst satırın gerçek yüksekliğine sığdır."""
        foto = getattr(self, "foto_alani", None)
        paneller = getattr(self, "_ust_panel_dis", None)
        if foto is None or not paneller or len(paneller) < 2:
            return
        try:
            self.update_idletasks()
            # Müşteri paneli (p1) yüksekliğini hedef al
            hedef = int(paneller[1].winfo_height())
            if hedef < 80:
                return
            paneller[0].configure(height=hedef)
            paneller[0].grid_propagate(False)
            # Tuval: başlık + düğme payı düş
            pay = 52
            th = max(60, hedef - pay)
            foto.tuval.configure(height=th)
            foto.tuval.pack_configure(fill="x", expand=False)
        except tk.TclError:
            pass

    def _musteri_formu(self, parent):
        self._bolum_baslik(parent, f"{self.etiket} Bilgileri")

        # Telefon / e-posta İletişim Bilgileri panelinde (kopya giriş yok)
        alanlar = (
            ("Kod", "cari_kodu"),
            ("Ünvan", "unvan"),
            ("V.Dairesi", "vergi_dairesi"),
            ("VKN", "vergi_numarasi"),
            ("TCKN", "tc_kimlik"),
        )
        for etiket, alan in alanlar:
            sag = self._form_satiri(parent, etiket, alan_anahtar=alan)
            if alan == "unvan":
                # Vurgu: daha kalın/büyük değer; kutu yüksekliği H (ipady yok)
                w = self._entry(sag, alan, width=16, font=font(VERI_VURGU_PT, "bold", self))
                w.pack(fill="both", expand=True)
            else:
                w = self._entry(sag, alan, width=16)
                w.pack(fill="both", expand=True)
            if alan == "vergi_numarasi":
                w.bind("<FocusOut>", self._vergi_no_kontrol)
        # Ekran rolü: tedarikçi kartı / müşteri kartı — açık kaydın karma türü aramayı daraltmaz
        ekran_rolu = "Tedarikçi" if self.tedarikci_modu else "Müşteri"
        self._unvan_arama = UnvanAramaKutusu(
            self,
            self.degerler["unvan"],
            cari_turu=ekran_rolu,
            on_secim=self._unvandan_cariye_gec,
        )
        self.degerler["unvan"].bind("<Button-3>", self._unvan_sag_tik)
        self.degerler["cari_kodu"].bind("<Button-3>", self._kod_sag_tik)
        ToolTip(self.degerler["cari_kodu"], "Sağ tık: kod sırasındaki son 10 kayıt")

        self._cari_tur_alani_kur(parent)

        grup_sag = self._form_satiri(parent, "Sektör Grubu", alan_anahtar="musteri_grubu")
        self._grup_satiri = grup_sag.master
        grup_widget = ttk.Combobox(grup_sag, state="readonly", width=14, style="CariKart.TCombobox")
        self.degerler["musteri_grubu"] = grup_widget
        grup_widget.bind("<<ComboboxSelected>>", lambda _e: self._grup_uyarisi_goster(False), add="+")
        grup_ogeleri = [grup_widget]
        for metin, komut in (("Yeni", self.yeni_grup_ekle), ("Grubu Sil", self.grup_sil)):
            dugme = self._ust_yan_dugme(grup_sag, metin, komut)
            grup_ogeleri.append(dugme)
        ToolTip(grup_ogeleri[-1], "Seçili sektör grubunu siler; kullanılıyorsa kartları önce başka gruba taşır.")
        from ui_pencere import sarmali_yerlestir

        # Düğmeler satırı H'den yükseltmesin (tek satır; wrap pady=0)
        sarmali_yerlestir(grup_sag, grup_ogeleri, padx=1, pady=0, genisleyen=(grup_widget,))
        self._grup_uyari_lbl = tk.Label(
            parent, text="", bg=BEYAZ, fg=UYARI, font=font(8, "bold", self), anchor="w"
        )
        # Aktif checkbox yok; rozet / Pasife Al ile yönetilir.
        self.degerler["aktif"] = tk.BooleanVar(
            value=cari.aktif if (cari := self.cari) else True
        )

        self.musteri_grubu_secimini_hazirla()
        self._cari_tur_listelerini_yukle()

    def _detay_seridini_olustur(self, parent):
        """İletişim Bilgileri · İstihbarat/Uyarı · Yetkililer · Muhasebe — buton şeridi + açılır panel."""
        dis, cerceve = beyaz_kart(parent, padx=8, pady=6)
        dis.pack(fill="x", pady=(0, 6))
        self._detay_dis = dis
        self._detay_aktif = None

        btn_satir = tk.Frame(cerceve, bg=BEYAZ)
        btn_satir.pack(fill="x")
        self._detay_butonlari = {}
        for anahtar, baslik in (
            ("adres", "İletişim Bilgileri"),
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
        risk_dugme = tk_buton(
            btn_satir, "Risk ve Limitler / Vade Farkı", lambda: self._detay_panel_ac("risk"), rol="vurgu"
        )
        risk_dugme.pack(side="left", padx=(0, 6))
        self._detay_butonlari["risk"] = risk_dugme

        self._detay_icerik = tk.Frame(cerceve, bg=BEYAZ)
        self._detay_paneller = {}

        from cari_risk_ui import RiskLimitPaneli

        risk_panel = tk.Frame(self._detay_icerik, bg=BEYAZ)
        self.risk_paneli = RiskLimitPaneli(
            risk_panel,
            cari_id_getir=lambda: getattr(self.cari, "id", None) if self.cari else None,
            on_degisim=self._risk_alanlari_degisti,
        )
        self.risk_paneli.pack(fill="both", expand=True)
        self._detay_paneller["risk"] = risk_panel

        adres_panel = tk.Frame(self._detay_icerik, bg=BEYAZ)
        self._iletisim_bilgileri_olustur(adres_panel)
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
        elif anahtar == "risk":
            self.risk_paneli.yenile()

    def _risk_alanlari_degisti(self):
        if getattr(self, "_snapshot", None) is None:
            return
        self._kirli = self._form_snapshot() != self._snapshot
        self._baslik_rozetlerini_guncelle()

    def risk_panelini_ac(self, _e=None):
        if self._detay_aktif != "risk":
            self._detay_panel_ac("risk")

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

    def _iletisim_bilgileri_olustur(self, parent):
        """GSM×2 · Sabit · WhatsApp · E-posta — tek satır; altında adresler."""
        from telefon_bicim import ORNEK, telefon_entry_bagla

        baslik = tk.Frame(parent, bg=LACIVERT, padx=8, pady=5)
        baslik.pack(fill="x", pady=(0, 6))
        tk.Label(
            baslik,
            text="İLETİŞİM BİLGİLERİ",
            bg=LACIVERT,
            fg=SARI,
            font=font(9, "bold", self),
        ).pack(side="left")
        tk.Label(
            baslik,
            text=f"{ORNEK} · baştaki 0 yok",
            bg=LACIVERT,
            fg="#B8C7D9",
            font=font(8, root=self),
        ).pack(side="right")

        kart = tk.Frame(
            parent,
            bg=ACIK_BG,
            highlightthickness=1,
            highlightbackground=CIZGI,
            padx=8,
            pady=6,
        )
        kart.pack(fill="x", pady=(0, 6))

        satir = tk.Frame(kart, bg=ACIK_BG)
        satir.pack(fill="x")
        alanlar = (
            ("GSM", "telefon", 1),
            ("GSM 2", "telefon2", 1),
            ("Sabit", "telefon3", 1),
            ("WhatsApp", "whatsapp", 1),
            ("E-posta", "email", 2),
        )
        for i, (etiket, alan, agirlik) in enumerate(alanlar):
            kolon = tk.Frame(satir, bg=ACIK_BG)
            kolon.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0))
            satir.columnconfigure(i, weight=agirlik)
            tk.Label(
                kolon, text=etiket, bg=ACIK_BG, fg=IKINCIL, font=font(7, root=self), anchor="w"
            ).pack(fill="x")
            kutu = tk.Frame(
                kolon,
                bg=BEYAZ,
                highlightthickness=1,
                highlightbackground=CIZGI,
                padx=1,
                pady=1,
            )
            kutu.pack(fill="x", pady=(1, 0))
            w = self._entry(kutu, alan, width=12 if alan != "email" else 20)
            w.pack(fill="x", padx=1, pady=0)
            if alan != "email":
                telefon_entry_bagla(w, on_degisim=self._telefon_butonlarini_guncelle)

        self._adres_sekmelerini_olustur(parent)

    def _adres_sekmelerini_olustur(self, parent):
        from database.turkiye_il_ilce import iller

        adres_kart = tk.Frame(
            parent,
            bg=ACIK_BG,
            highlightthickness=1,
            highlightbackground=CIZGI,
            padx=10,
            pady=8,
        )
        adres_kart.pack(fill="x")
        tk.Label(
            adres_kart,
            text="Adresler",
            bg=ACIK_BG,
            fg=LACIVERT,
            font=font(9, "bold", self),
        ).pack(anchor="w", pady=(0, 6))
        self.adres_sekme = ttk.Notebook(adres_kart, style="CariKart.TNotebook")
        self.adres_sekme.pack(fill="x")
        tanimlar = (
            (1, "Adres 1", "adres", "il", "ilce", "adres_tipi", "Merkez"),
            (2, "Adres 2", "adres2", "il2", "ilce2", "adres_tipi2", "Fatura"),
            (3, "Adres 3", "adres3", "il3", "ilce3", "adres_tipi3", "Sevk"),
        )
        tip_secenekleri = ("Merkez", "Fatura", "Sevk", "Depo", "Şube", "Diğer")
        self._varsayilan_tipler = {t[5]: t[6] for t in tanimlar}
        for _no, sekme_baslik, adres_alan, il_alan, ilce_alan, tip_alan, varsayilan_tip in tanimlar:
            sekme = tk.Frame(self.adres_sekme, bg=BEYAZ, padx=6, pady=6)
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

    def _yan_yana_metrik(
        self,
        parent,
        anahtar: str,
        baslik: str,
        etiket_genislik: int = 14,
        deger_boyut: int = VERI_DEGER_PT,
        *,
        kalin: bool = False,
    ):
        """Çerçeveli metrik satırı; ozet_kartlari {frame, deger, alt} uyumlu."""
        _lbl, deger, satir = self._veri_kutu_satiri(
            parent,
            baslik,
            etiket_genislik=etiket_genislik,
            deger_pt=deger_boyut or VERI_DEGER_PT,
            kalin=kalin,
        )
        alt = tk.Label(satir, text="", bg=BEYAZ)  # uyumluluk; pack edilmez
        self.ozet_kartlari[anahtar] = {"frame": satir, "deger": deger, "alt": alt}

    def _ticari_risk_paneli(self, parent):
        self._bolum_baslik(parent, "Ticari Bilgiler / Risk")
        self.ozet_kartlari = getattr(self, "ozet_kartlari", {}) or {}
        try:
            _satis_kodlar = aktif_satis_fiyat_kodlari()
        except Exception:
            _satis_kodlar = SATIS_FIYAT_ADLARI
        self._satis_liste_etiket_kod: dict[str, str] = {}
        self._satis_liste_kod_etiket: dict[str, str] = {}
        satis_etiketler = [""]
        for kod in _satis_kodlar:
            etiket = satis_fiyat_gorunen_ad(kod) or kod
            if etiket != kod:
                etiket = f"{etiket} ({kod})"
            self._satis_liste_etiket_kod[etiket] = kod
            self._satis_liste_kod_etiket[kod] = etiket
            satis_etiketler.append(etiket)
        satis_listeler = tuple(satis_etiketler)
        alis_listeler = ("",) + tuple(ALIŞ_FIYAT_ADLARI)
        # Limitler "Risk ve Limitler / Vade Farkı" panelinde; burada yalnız özet.
        alanlar = (
            ("Satış listesi", "satis_fiyat_listesi", "combobox", satis_listeler),
            ("Alış listesi", "alis_fiyat_listesi", "combobox", alis_listeler),
            ("Satış vade", "satis_vade_gunu", "entry", None),
            ("Alış vade", "alis_vade_gunu", "entry", None),
        )
        for etiket, alan, tur, degerler_liste in alanlar:
            sag = self._form_satiri(parent, etiket)
            if tur == "combobox":
                w = ttk.Combobox(sag, values=degerler_liste, width=14, style="CariKart.TCombobox")
            else:
                w = ttk.Entry(sag, width=14, style="CariKart.TEntry")
            w.pack(fill="both", expand=True)
            self.degerler[alan] = w

        # Açık Hesap Kalanı bölümü kaldırıldı (yerleşim); hesap servisi korunur.
        self._yan_yana_metrik(parent, "toplam_risk", "Brüt toplam risk", 14)
        self._yan_yana_metrik(parent, "genel_risk", "Genel risk", 14)
        self._yan_yana_metrik(parent, "genel_kalan", "Kullanılabilir limit", 14)
        self._yan_yana_metrik(parent, "risk_durumu", "Risk durumu", 14)
        ToolTip(
            self.ozet_kartlari["genel_risk"]["frame"],
            "Açık hesap tam + çek/senet bileşenleri karttaki risk yüzdeleriyle (Risk ve Limitler).",
        )
        ToolTip(
            self.ozet_kartlari["genel_kalan"]["frame"],
            "Toplam risk limiti − Genel Risk. Brüt toplam limit denetiminde kullanılmaz.",
        )
        for anahtar in ("toplam_risk", "genel_risk", "genel_kalan", "risk_durumu"):
            kart = self.ozet_kartlari[anahtar]
            for w in (kart["frame"], kart["deger"]):
                w.configure(cursor="hand2")
                w.bind("<Button-1>", self.risk_panelini_ac, add="+")
        self._risk_bakiye_fark_lbl = tk.Label(
            parent,
            text="",
            bg=BEYAZ,
            fg=DIKKAT,
            font=font(8, root=self),
            wraplength=200,
            justify="left",
            anchor="w",
            cursor="hand2",
        )
        self._risk_bakiye_fark_lbl.pack(fill="x", pady=(2, 0))
        self._risk_bakiye_fark_lbl.bind("<Button-1>", self.risk_panelini_ac)

    def _bakiye_ozet_paneli(self, parent):
        """Beş satırlı borç/alacak özeti: Borç, Alacak, Kalan (B/A), Kalan Gün, Kapatılan Gün."""
        from cari_borc_alacak_ozet import OZET_SATIRLARI

        self._bolum_baslik(parent, "Borç / Alacak Özeti")
        if not getattr(self, "ozet_kartlari", None):
            self.ozet_kartlari = {}
        self.ozet_degerleri = {}

        for baslik in OZET_SATIRLARI:
            lbl, _ = self._ozet_deger_satiri(parent, baslik)
            if baslik == "Kalan Bakiye":
                ToolTip(lbl, "Toplam borç − toplam alacak. (B)=borçlu, (A)=alacaklı.")
            elif baslik == "Kalan Bakiye Gün":
                ToolTip(
                    lbl,
                    "Açık kalan tutarların ağırlıklı ortalama valör günü (bakiyeye göre borç/alacak). "
                    "Hareket tablosundaki «Gün» sütunu belgenin yaşını (bugün − belge tarihi) gösterir; "
                    "bu özet satırıyla aynı hesap değildir.",
                )
            elif baslik == "Kapatılan Bakiye Gün":
                ToolTip(
                    lbl,
                    "Kapanan borcun tutar-ağırlıklı ortalama valörü (gün). FIFO; kapanan faturalar.",
                )

        # Özet dışı ek bilgi (beş satırın altında, bakiyeye dahil değil)
        tk.Frame(parent, bg="#E2E8F0", height=1).pack(fill="x", pady=(4, 4))
        self._yan_yana_metrik(parent, "son_islem", "Son işlem", 14)
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

    # ─── Hızlı işlemler (üst çubuk açılır menü) ───────────────────
    def _hizli_islem_maddelerini_hazirla(self):
        """Menü maddeleri; orta panel düğmeleri kaldırıldı (alan Cari Hareketler'e gider)."""
        self.hizli_dugmeleri = []
        soz_baslik = "Ödeme Sözleri (Verilen)" if self.tedarikci_modu else "Ödeme Sözleri (Alınan)"
        if self.tedarikci_modu:
            ana = (
                ("Yeni Sipariş", self.yeni_alis_siparis_ac,
                 ("alis_siparis_duzenleme", "alis_duzenleme", "yeni_kayit")),
                ("Yeni İrsaliye", self.yeni_alis_irsaliye_ac,
                 ("alis_irsaliye_duzenleme", "alis_duzenleme", "yeni_kayit")),
                ("Yeni Fatura", self.yeni_alis_fatura_ac,
                 ("alis_fatura_duzenleme", "alis_duzenleme", "yeni_kayit")),
                ("Alış Evrakları", self.alis_evraklari_ac, None),
                ("Ödeme Gir", self.odeme_gir, ("finans_duzenleme", "cari_duzenleme")),
                ("Tahsilat", self.tahsilat_gir, ("finans_duzenleme", "cari_duzenleme")),
                ("Cari Virman", self.cari_virman_ac, ("finans_duzenleme", "cari_duzenleme")),
                ("Müşteriden Tedarikçiye", self.kk_cekimi_ac, ("finans_duzenleme", "cari_duzenleme")),
            )
        else:
            ana = (
                ("Yeni Sipariş", self.yeni_siparis_ac, ("satis_duzenleme", "yeni_kayit")),
                ("Yeni İrsaliye", self.yeni_irsaliye_ac, ("satis_duzenleme", "yeni_kayit")),
                ("Yeni Fatura", self.yeni_fatura_ac, ("satis_duzenleme", "yeni_kayit")),
                ("Satış İade Faturaları", self.satis_iade_faturalari_ac, None),
                ("Tahsilat", self.tahsilat_gir, ("finans_duzenleme", "cari_duzenleme")),
                ("Ödeme Gir", self.odeme_gir, ("finans_duzenleme", "cari_duzenleme")),
                ("Cari Virman", self.cari_virman_ac, ("finans_duzenleme", "cari_duzenleme")),
                ("Müşteriden Tedarikçiye", self.kk_cekimi_ac, ("finans_duzenleme", "cari_duzenleme")),
            )
        ek = (
            ("Stok Detaylı Cari Ekstre", self.stok_detayli_ekstre_ac, None),
            ("Bekleyen Siparişler", self.bekleyen_siparisler_ac, None),
            ("Açık Kalemler", self.acik_kalemler_ac, None),
            (soz_baslik, self.odeme_sozleri_ac, None),
            ("Yenile", self.yenile, None),
        )
        self._hizli_islem_maddeleri = list(ana) + list(ek)
        self._hizli_dugmeleri_ayarla()

    def _hizli_islemler_menu_ac(self, _event=None):
        """Üst çubuktaki Hızlı İşlemler düğmesinden dikey açılır menü."""
        if getattr(self, "_hizli_menu_acik", False):
            return
        if getattr(self, "_hizli_islem_calisiyor", False):
            return
        maddeler = getattr(self, "_hizli_islem_maddeleri", None) or []
        if not maddeler:
            self._hizli_islem_maddelerini_hazirla()
            maddeler = self._hizli_islem_maddeleri
        kayitli = bool(self.cari and getattr(self.cari, "id", None))
        menu = tk.Menu(
            self,
            tearoff=0,
            font=font(10, root=self),
            bg=BEYAZ,
            fg=LACIVERT,
            activebackground=SARI,
            activeforeground=LACIVERT,
            bd=1,
            relief="solid",
        )

        def _calistir(komut):
            def _ic(_=None):
                if getattr(self, "_hizli_islem_calisiyor", False):
                    return
                self._hizli_islem_calisiyor = True
                try:
                    menu.unpost()
                except tk.TclError:
                    pass

                def _bitir():
                    try:
                        komut()
                    finally:
                        self.after(300, lambda: setattr(self, "_hizli_islem_calisiyor", False))

                self.after_idle(_bitir)

            return _ic

        for baslik, komut, izinler in maddeler:
            izin_ok = True if izinler is None else _izin_var(*izinler)
            etkin = bool(kayitli and izin_ok)
            # Yenile kayıtlı cari olmadan da çalışabilir
            if baslik == "Yenile":
                etkin = True
            menu.add_command(
                label=baslik,
                command=_calistir(komut) if etkin else None,
                state="normal" if etkin else "disabled",
            )
        btn = getattr(self, "_hizli_islem_btn", None)
        try:
            self._hizli_menu_acik = True
            if btn is not None and btn.winfo_exists():
                x = btn.winfo_rootx()
                y = btn.winfo_rooty() + btn.winfo_height()
            else:
                x = self.winfo_rootx() + 80
                y = self.winfo_rooty() + 60
            # Menü ekran dışına taşmasın
            try:
                mw, mh = 280, max(120, len(maddeler) * 26 + 16)
                sw = int(self.winfo_screenwidth())
                sh = int(self.winfo_screenheight())
                x = max(0, min(int(x), sw - mw))
                y = max(0, min(int(y), sh - mh))
            except Exception:
                pass
            menu.tk_popup(x, y)
        finally:
            try:
                menu.grab_release()
            except tk.TclError:
                pass
            self._hizli_menu_acik = False

    def _hizli_dugmeleri_ayarla(self):
        """Kayıtlı cariye göre üst Hızlı İşlemler düğmesini aç/kapat."""
        kayitli = bool(self.cari and getattr(self.cari, "id", None))
        btn = getattr(self, "_hizli_islem_btn", None)
        if btn is None:
            return
        try:
            btn.configure(
                state="normal",
                cursor="hand2" if kayitli else "arrow",
            )
        except tk.TclError:
            pass

    def _hareket_yukseklik_ayarla(self, _event=None):
        """Pencere yüksekliğine göre hareket tablosu satır sayısını büyüt."""
        tablo = getattr(self, "hareket_tablosu", None)
        cerceve = getattr(self, "_hareket_tablo_cercevesi", None)
        if tablo is None or cerceve is None:
            return
        try:
            h = int(cerceve.winfo_height())
        except tk.TclError:
            return
        if h < 80:
            return
        row_h = 32
        satir = max(12, min(40, (h - 4) // row_h))
        try:
            if int(tablo.cget("height") or 0) != satir:
                tablo.configure(height=satir)
        except tk.TclError:
            pass

    def _hareket_gorunen_kolonlar(self) -> tuple[str, ...]:
        if getattr(self, "_hareket_urun_sutunlari_acik", False):
            return tuple(self.hareket_tablosu["columns"]) if self.hareket_tablosu else ()
        return getattr(self, "_hareket_temel_kolonlar", ())

    def _hareket_urun_sutun_toggle(self):
        """Ürün/barkod/fiyat sütunlarını aç-kapa; Kalan Bakiye/Gün temel görünümde kalır."""
        self._hareket_urun_sutunlari_acik = not getattr(self, "_hareket_urun_sutunlari_acik", False)
        self._hareket_gorunum_uygula()

    def _hareket_gorunum_uygula(self):
        tablo = getattr(self, "hareket_tablosu", None)
        if tablo is None:
            return
        if getattr(self, "_hareket_urun_sutunlari_acik", False):
            # Ürün sütunları açık: bakiye/gün sağda kalsın, ürünler ortada
            goster = (
                "tarih",
                "tur",
                "belge",
                "aciklama",
                *self._hareket_urun_kolonlar,
                "borc",
                "alacak",
                "bakiye",
                "gun",
            )
        else:
            goster = self._hareket_temel_kolonlar
        try:
            tablo.configure(displaycolumns=goster)
        except tk.TclError:
            tablo["displaycolumns"] = goster
        self._hareket_baslik_isaretlerini_guncelle()
        self._hareket_sutunlari_sigdir()

    def _hareket_sutunlari_sigdir(self, _event=None):
        """Temel görünümde tutar + Kalan Bakiye + Gün'ü pencereye sığdır; yenilemede bozulmasın."""
        tablo = getattr(self, "hareket_tablosu", None)
        cerceve = getattr(self, "_hareket_tablo_cercevesi", None)
        ayar = getattr(self, "_hareket_kolon_ayar", None)
        if tablo is None or cerceve is None or not ayar:
            return
        if getattr(self, "_hareket_urun_sutunlari_acik", False):
            return  # ürün sütunları açıkken yatay kaydırma beklenir
        try:
            genislik = int(cerceve.winfo_width())
        except tk.TclError:
            return
        if genislik < 200:
            return
        # Sabit sütunlar + esnek açıklama
        sabit = ("tarih", "tur", "belge", "borc", "alacak", "bakiye", "gun")
        sabit_toplam = sum(ayar[k][1] for k in sabit) + 28  # #0
        kalan = max(120, genislik - sabit_toplam - 24)
        try:
            for k in sabit:
                _b, w, hiza, _s = ayar[k]
                tablo.column(k, width=w, minwidth=max(48, w // 2), stretch=False, anchor=hiza)
            tablo.column("aciklama", width=kalan, minwidth=100, stretch=True, anchor="w")
            tablo.configure(displaycolumns=self._hareket_temel_kolonlar)
        except tk.TclError:
            pass

    def _hareket_tablosunu_olustur(self, parent):
        dis, hareket = beyaz_kart(parent, padx=8, pady=4)
        dis.pack(fill="both", expand=True)
        ust_hareket = tk.Frame(hareket, bg=BEYAZ)
        ust_hareket.pack(fill="x", pady=(0, 4))
        tk.Label(
            ust_hareket,
            text="Cari Hareketler",
            bg=BEYAZ,
            fg=LACIVERT,
            font=font(11, "bold", self),
        ).pack(side="left")
        self._yukleniyor_lbl = tk.Label(
            ust_hareket, text="", bg=BEYAZ, fg=DIKKAT, font=font(9, root=self)
        )
        self._yukleniyor_lbl.pack(side="left", padx=10)
        self._soz_ozet_lbl = tk.Label(
            ust_hareket, text="", bg=BEYAZ, fg=LACIVERT, font=font(9, root=self), anchor="e"
        )
        self._soz_ozet_lbl.pack(side="right", padx=(8, 0))
        tk_buton(ust_hareket, "Yenile", self.yenile, rol="ikincil").pack(side="right")

        baslik_satir = tk.Frame(hareket, bg=BEYAZ)
        baslik_satir.pack(fill="x", pady=(0, 4))
        tk.Label(
            baslik_satir,
            text=(
                "▶ ürün detayı · Kalan Bakiye = yürüyen cari bakiye · "
                "Gün = belge yaşı · sağ tık: ürün sütunları"
            ),
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

        def _grup():
            return tk.Frame(filtre, bg=BEYAZ)

        tur_g = _grup()
        tk.Label(tur_g, text="Belge türü:", bg=BEYAZ, fg=IKINCIL, font=font(9, root=self)).pack(
            side="left"
        )
        self.hareket_tur_filtre = ttk.Combobox(
            tur_g,
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
        self.hareket_tur_filtre.pack(side="left", padx=(4, 5))
        ara_g = _grup()
        tk.Label(ara_g, text="Ara:", bg=BEYAZ, fg=IKINCIL, font=font(9, root=self)).pack(side="left")
        self.hareket_arama = ttk.Entry(ara_g, width=18)
        self.hareket_arama.pack(side="left", padx=4)
        bas_g = _grup()
        tk.Label(bas_g, text="Başlangıç:", bg=BEYAZ, fg=IKINCIL, font=font(9, root=self)).pack(
            side="left", padx=(5, 0)
        )
        bas_c = tk.Frame(bas_g, bg=BEYAZ)
        bas_c.pack(side="left", padx=4)
        self.hareket_tarih_bas = ttk.Entry(bas_c, width=10)
        self.hareket_tarih_bas.pack(side="left")
        takvim_butonu(bas_c, self.hareket_tarih_bas, on_select=lambda: self._hareketleri_goster())
        bit_g = _grup()
        tk.Label(bit_g, text="Bitiş:", bg=BEYAZ, fg=IKINCIL, font=font(9, root=self)).pack(
            side="left", padx=(1, 0)
        )
        bit_c = tk.Frame(bit_g, bg=BEYAZ)
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
        tk_buton(filtre, "TL / USD Karşılığı", self._usd_karsilik_raporu_ac, rol="ikincil").pack(
            side="left", padx=(8, 0)
        )
        from ui_pencere import sarmali_yerlestir

        sarmali_yerlestir(filtre, list(filtre.winfo_children()), padx=3)
        self.hareket_tur_filtre.bind("<<ComboboxSelected>>", lambda _e: self._hareketleri_goster())
        self.hareket_arama.bind("<Return>", lambda _e: self._hareketleri_goster())
        self.hareket_tarih_bas.bind("<Return>", lambda _e: self._hareketleri_goster())
        self.hareket_tarih_bit.bind("<Return>", lambda _e: self._hareketleri_goster())

        # Stok Kodu (urun_kodu) görünmez; genişliği Ürün Adı'na eklendi (300+100=400)
        # Tüm kolonlar tanımlı kalır; temel görünüm ürün sütunlarını gizler (Kalan Bakiye/Gün sığsın).
        kolonlar = (
            "tarih",
            "tur",
            "belge",
            "aciklama",
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
        self._hareket_temel_kolonlar = (
            "tarih",
            "tur",
            "belge",
            "aciklama",
            "borc",
            "alacak",
            "bakiye",
            "gun",
        )
        self._hareket_urun_kolonlar = (
            "barkod",
            "urun_adi",
            "miktar",
            "birim",
            "net_birim_fiyat",
            "satir_tutari",
            "pb",
            "doviz",
            "kur",
        )
        self._hareket_urun_sutunlari_acik = False
        tablo_cercevesi = tk.Frame(hareket, bg=BEYAZ)
        tablo_cercevesi.pack(fill="both", expand=True)
        self._hareket_tablo_cercevesi = tablo_cercevesi
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
            height=18,
        )
        tablo.heading("#0", text="")
        tablo.column("#0", width=28, minwidth=28, stretch=False, anchor="center")
        # Temel görünüm genişlikleri — Kalan Bakiye ve Gün yatay kaydırmasız sığacak şekilde
        kolon_ayar = {
            "tarih": ("Tarih", 92, "center", False),
            "tur": ("Belge Türü", 108, "w", False),
            "belge": ("Belge No", 118, "w", False),
            "aciklama": ("Açıklama", 220, "w", True),
            "barkod": ("Barkod", 100, "w", False),
            "urun_adi": ("Ürün Adı", 180, "w", True),
            "miktar": ("Miktar", 72, "e", False),
            "birim": ("Birim", 58, "center", False),
            "net_birim_fiyat": ("Net Birim Fiyat", 110, "e", False),
            "satir_tutari": ("Satır Tutarı", 100, "e", False),
            "pb": ("PB", 40, "center", False),
            "doviz": ("Döviz", 88, "e", False),
            "kur": ("Kur", 70, "e", False),
            "borc": ("Borç (TL)", 112, "e", False),
            "alacak": ("Alacak (TL)", 112, "e", False),
            "bakiye": ("Kalan Bakiye", 128, "e", False),
            "gun": ("Gün", 58, "e", False),
        }
        self._hareket_kolon_ayar = kolon_ayar
        self._hareket_kolon_basliklari = {k: v[0] for k, v in kolon_ayar.items()}
        self._hareket_kolon_hizalari = {k: v[2] for k, v in kolon_ayar.items()}
        for kolon in kolonlar:
            baslik, genislik, hiza, stretch = kolon_ayar[kolon]
            tablo.column(
                kolon,
                width=genislik,
                minwidth=max(48, genislik // 2) if kolon in ("bakiye", "gun", "borc", "alacak") else max(36, genislik // 2),
                anchor=hiza,
                stretch=stretch,
            )
        tablo["displaycolumns"] = self._hareket_temel_kolonlar
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
        tablo_cercevesi.bind("<Configure>", self._hareket_yukseklik_ayarla, add="+")
        tablo_cercevesi.bind("<Configure>", self._hareket_sutunlari_sigdir, add="+")
        self.after(120, self._hareket_yukseklik_ayarla)
        self.after(140, self._hareket_sutunlari_sigdir)
        self._hareket_menu = tk.Menu(self, tearoff=0)
        self._hareket_menu.add_command(label="Belgeyi Aç", command=self._hareket_belge_ac)
        self._hareket_menu.add_command(label="Kapatma Detayı", command=self._hareket_kapatma_detayi)
        self._hareket_menu.add_command(
            label="Fatura ürünlerini göster/gizle", command=self._secili_fatura_detay_toggle
        )
        self._hareket_menu.add_command(
            label="Ürün sütunlarını göster/gizle", command=self._hareket_urun_sutun_toggle
        )
        self._hareket_menu.add_command(label="Muhasebe Fişi", command=self._hareket_muhasebe_fisi)
        self._hareket_menu.add_command(
            label="Tahsilat/Ödemeyi İptal Et", command=self._hareket_tahsilat_odeme_iptal
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
        self.degerler["cari_kodu"].configure(state="normal")
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
                if alan in ("telefon", "telefon2", "telefon3", "whatsapp") and deger:
                    from telefon_bicim import telefon_bicimle

                    deger = telefon_bicimle(str(deger))
                if isinstance(widget, tk.Text):
                    widget.insert("1.0", deger)
                elif alan in combobox_alanlar:
                    if deger:
                        if alan == "satis_fiyat_listesi":
                            harita = getattr(self, "_satis_liste_kod_etiket", {}) or {}
                            widget.set(harita.get(str(deger), str(deger)))
                        else:
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
        if getattr(self, "risk_paneli", None) is not None:
            self.risk_paneli.doldur(self.cari)
            self.risk_paneli.duzenlenebilir(True)
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
        if alan == "musteri_grubu" and deger == self.GRUP_YER_TUTUCU:
            return ""
        if alan == "satis_fiyat_listesi" and deger:
            harita = getattr(self, "_satis_liste_etiket_kod", {}) or {}
            return harita.get(deger, deger)
        return deger

    def _form_snapshot(self) -> str:
        parcalar = [f"{a}={self._widget_deger(a)}" for a in sorted(self.degerler.keys())]
        for a in sorted(self.muhasebe.keys()):
            parcalar.append(f"muh.{a}={self.muhasebe.get(a) or ''}")
        parcalar.append(f"uyari={getattr(self, 'uyari_notu', '') or ''}")
        if getattr(self, "risk_paneli", None) is not None:
            parcalar.append(f"risk={self.risk_paneli.snapshot()}")
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

    def _telefon_numarasi(self, *, whatsapp_oncelikli: bool = False) -> str:
        from telefon_bicim import telefon_rakamlari

        if whatsapp_oncelikli:
            siralar = ("whatsapp", "telefon", "telefon2", "telefon3")
        else:
            siralar = ("telefon", "telefon2", "whatsapp", "telefon3")
        for alan in siralar:
            ham = self._widget_deger(alan)
            if ham:
                return telefon_rakamlari(ham)
        return ""

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
        num = self._telefon_numarasi(whatsapp_oncelikli=True)
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
        risk_asimi = []
        if metrik:
            satirlar = (metrik.get("risk_ozeti") or {}).get("satirlar") or {}
            risk_asimi = [s for s in satirlar.values() if s.get("durum") == "ASILDI"]
            if risk_asimi:
                mesajlar.append(
                    "Risk limiti aşıldı: "
                    + ", ".join(f"{s['etiket']} (aşım {para_goster(s['asim'])})" for s in risk_asimi)
                )
            elif (metrik.get("risk_durum") or "") in ("uyari", "engel") or (
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
            if risk_asimi:
                rozet(self._uyari_rozet_satiri, "Risk aşımı", bg=UYARI).pack(side="left", padx=(0, 6))
            elif metrik and metrik.get("kullanilabilir_risk") is not None:
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

    GRUP_YER_TUTUCU = "Grup Atanmamış"

    def _grup_degeri(self) -> str:
        deger = (self.degerler["musteri_grubu"].get() or "").strip()
        return "" if deger == self.GRUP_YER_TUTUCU else deger

    def musteri_grubu_secimini_hazirla(self, *, secili: str | None = None):
        """Sektör grubu listesi (Perakende Müşteri sektörde yoktur)."""
        from database.kart_turu_service import KartTuruService

        try:
            gruplar = [g["ad"] for g in KartTuruService.sektor_listele(sadece_aktif=True)]
        except Exception:
            gruplar = CariService.gruplari_listele()
        mevcut_grup = secili if secili is not None else (
            self._grup_degeri() if "musteri_grubu" in self.degerler and self.degerler["musteri_grubu"].get()
            else (getattr(self.cari, "musteri_grubu", None) if self.cari else None)
        )
        # Perakende Müşteri artık sektör değil — listede gösterme; boş bırak
        if mevcut_grup and mevcut_grup.casefold() in {
            "perakende müşteri",
            "perakende musteri",
        }:
            mevcut_grup = None
        if mevcut_grup and mevcut_grup not in gruplar:
            gruplar.append(mevcut_grup)
        self.degerler["musteri_grubu"]["values"] = [self.GRUP_YER_TUTUCU, *gruplar]
        self.degerler["musteri_grubu"].set(mevcut_grup or self.GRUP_YER_TUTUCU)

    def _cari_tur_alani_kur(self, parent) -> None:
        self._cari_ana_map: dict[str, object] = {}
        self._cari_alt_map: dict[str, int] = {}
        self._cari_ted_alt_map: dict[str, int] = {}
        from ui_pencere import sarmali_yerlestir

        ana_sag = self._form_satiri(parent, "Ana Cari Kart Türü", alan_anahtar="ana_kart_turu")
        ana_cb = ttk.Combobox(ana_sag, state="readonly", width=16, style="CariKart.TCombobox")
        self.degerler["ana_kart_turu"] = ana_cb
        ana_cb.bind("<<ComboboxSelected>>", lambda _e: self._cari_ana_tur_degisti())
        yonet = self._ust_yan_dugme(ana_sag, "Yönet", self._cari_ana_tur_yonet)
        sarmali_yerlestir(ana_sag, [ana_cb, yonet], padx=2, pady=0, genisleyen=(ana_cb,))

        m_sag = self._form_satiri(parent, "Müşteri Alt Türü", alan_anahtar="musteri_alt_tur")
        self._musteri_alt_satiri = m_sag.master
        m_cb = ttk.Combobox(m_sag, state="readonly", width=16, style="CariKart.TCombobox")
        self.degerler["musteri_alt_tur"] = m_cb
        m_yonet = self._ust_yan_dugme(m_sag, "Yönet", lambda: self._cari_alt_tur_yonet("MUSTERI"))
        sarmali_yerlestir(m_sag, [m_cb, m_yonet], padx=2, pady=0, genisleyen=(m_cb,))

        t_sag = self._form_satiri(parent, "Tedarikçi Alt Türü", alan_anahtar="tedarikci_alt_tur")
        self._tedarikci_alt_satiri = t_sag.master
        t_cb = ttk.Combobox(t_sag, state="readonly", width=16, style="CariKart.TCombobox")
        self.degerler["tedarikci_alt_tur"] = t_cb
        t_yonet = self._ust_yan_dugme(t_sag, "Yönet", lambda: self._cari_alt_tur_yonet("TEDARIKCI"))
        sarmali_yerlestir(t_sag, [t_cb, t_yonet], padx=2, pady=0, genisleyen=(t_cb,))
        self._cari_tur_uyari = tk.Label(
            parent, text="", bg=BEYAZ, fg=UYARI, font=font(8, "bold", self), anchor="w"
        )

    def _cari_tur_listelerini_yukle(self) -> None:
        if "ana_kart_turu" not in self.degerler:
            return
        from database.kart_turu_service import KAPSAM_CARI, KartTuruService

        try:
            analar = KartTuruService.ana_turleri_listele(KAPSAM_CARI, sadece_aktif=True)
        except Exception as exc:
            import logging

            logging.getLogger(__name__).exception("cari kart tür listesi")
            if "ana_kart_turu" in self.degerler:
                self.degerler["ana_kart_turu"]["values"] = ()
            if hasattr(self, "_cari_tur_uyari"):
                self._cari_tur_uyari.configure(
                    text=f"Kart türü tanımları yüklenemedi: {exc}"
                )
                if not self._cari_tur_uyari.winfo_ismapped():
                    self._cari_tur_uyari.pack(fill="x", pady=2)
            return
        self._cari_ana_map = {a.ad: a for a in analar}
        self.degerler["ana_kart_turu"]["values"] = list(self._cari_ana_map.keys())
        sec = None
        if self.cari and getattr(self.cari, "ana_kart_turu_id", None):
            ana = KartTuruService.ana_getir(self.cari.ana_kart_turu_id)
            if ana:
                sec = ana.ad
        if not sec:
            # Mevcut cari_turu / açılış türünden
            hedef = (getattr(self.cari, "cari_turu", None) if self.cari else self.cari_turu) or "Müşteri"
            if hedef in self._cari_ana_map:
                sec = hedef
            elif self.tedarikci_modu and "Tedarikçi" in self._cari_ana_map:
                sec = "Tedarikçi"
            elif "Müşteri" in self._cari_ana_map:
                sec = "Müşteri"
        if sec:
            self.degerler["ana_kart_turu"].set(sec)
        self._cari_ana_tur_degisti(ilk=True)

    def _cari_ana_tur_degisti(self, *, ilk: bool = False) -> None:
        from database.kart_turu_service import KartTuruService

        ad = (self.degerler.get("ana_kart_turu").get() if "ana_kart_turu" in self.degerler else "") or ""
        ana = self._cari_ana_map.get(ad)
        rol = getattr(ana, "muhasebe_rol", None) if ana else None
        musteri_gorunur = rol in {"MUSTERI", "MUSTERI_TEDARIKCI"}
        tedarik_gorunur = rol in {"TEDARIKCI", "MUSTERI_TEDARIKCI"}

        def _goster(satir, acik: bool, *, after_widget=None):
            if satir is None:
                return
            g = getattr(self, "_ust_G", VERI_SATIR_BOSLUK_GECICI)
            h = getattr(self, "_ust_H", VERI_KUTU_YUKSEKLIK_GECICI)
            if acik:
                if not satir.winfo_ismapped():
                    kw = {"fill": "x", "pady": (0, g)}
                    if after_widget is not None and after_widget.winfo_ismapped():
                        kw["after"] = after_widget
                    satir.pack(**kw)
                    try:
                        satir.configure(height=h)
                        satir.pack_propagate(False)
                    except tk.TclError:
                        pass
            else:
                satir.pack_forget()

        ana_satir = getattr(self, "_ust_form_satirlari", {}).get("ana_kart_turu")
        m_satir = getattr(self, "_musteri_alt_satiri", None)
        t_satir = getattr(self, "_tedarikci_alt_satiri", None)
        _goster(m_satir, musteri_gorunur, after_widget=ana_satir)
        # Tedarikçi alt: müşteri alt görünürse onun altına, değilse ana türün altına
        onceki_t = m_satir if (musteri_gorunur and m_satir is not None) else ana_satir
        _goster(t_satir, tedarik_gorunur, after_widget=onceki_t)
        # Sektör grubu her zaman alt türlerden sonra kalsın
        grup = getattr(self, "_grup_satiri", None)
        if grup is not None and grup.winfo_ismapped():
            try:
                dayanak = t_satir if (tedarik_gorunur and t_satir and t_satir.winfo_ismapped()) else (
                    m_satir if (musteri_gorunur and m_satir and m_satir.winfo_ismapped()) else ana_satir
                )
                if dayanak is not None and dayanak.winfo_ismapped():
                    g = getattr(self, "_ust_G", VERI_SATIR_BOSLUK_GECICI)
                    grup.pack_configure(after=dayanak, pady=(0, g))
            except tk.TclError:
                pass

        # Müşteri alt türleri (Müşteri ana tanımından)
        musteri_ana = next(
            (a for a in self._cari_ana_map.values() if a.muhasebe_rol == "MUSTERI"), None
        )
        tedarik_ana = next(
            (a for a in self._cari_ana_map.values() if a.muhasebe_rol == "TEDARIKCI"), None
        )
        self._cari_alt_map = {}
        m_vals = ["— Alt Tür Atanmamış —"]
        if musteri_ana:
            for a in KartTuruService.alt_turleri_listele(musteri_ana.id, sadece_aktif=True):
                m_vals.append(a.ad)
                self._cari_alt_map[a.ad] = a.id
        if "musteri_alt_tur" in self.degerler:
            self.degerler["musteri_alt_tur"]["values"] = m_vals
            sec_m = "— Alt Tür Atanmamış —"
            if ilk and self.cari and getattr(self.cari, "musteri_alt_tur_id", None):
                alt = KartTuruService.alt_getir(self.cari.musteri_alt_tur_id)
                if alt and alt.ad in self._cari_alt_map:
                    sec_m = alt.ad
                elif alt and not ilk:
                    pass
                elif alt:
                    if hasattr(self, "_cari_tur_uyari"):
                        self._cari_tur_uyari.configure(
                            text="Uyumsuz müşteri alt türü temizlendi; sektör grubu korundu."
                        )
            elif not ilk:
                sec_m = "— Alt Tür Atanmamış —"
            self.degerler["musteri_alt_tur"].set(sec_m)
            self.degerler["musteri_alt_tur"].configure(
                state="readonly" if musteri_gorunur else "disabled"
            )

        self._cari_ted_alt_map = {}
        t_vals = ["— Alt Tür Atanmamış —"]
        if tedarik_ana:
            for a in KartTuruService.alt_turleri_listele(tedarik_ana.id, sadece_aktif=True):
                t_vals.append(a.ad)
                self._cari_ted_alt_map[a.ad] = a.id
        if "tedarikci_alt_tur" in self.degerler:
            self.degerler["tedarikci_alt_tur"]["values"] = t_vals
            sec_t = "— Alt Tür Atanmamış —"
            if ilk and self.cari and getattr(self.cari, "tedarikci_alt_tur_id", None):
                alt = KartTuruService.alt_getir(self.cari.tedarikci_alt_tur_id)
                if alt and alt.ad in self._cari_ted_alt_map:
                    sec_t = alt.ad
            self.degerler["tedarikci_alt_tur"].set(sec_t)
            self.degerler["tedarikci_alt_tur"].configure(
                state="readonly" if tedarik_gorunur else "disabled"
            )

        # cari_turu metnini ana rolden güncelle (kayıt için)
        if ana:
            from database.kart_turu_service import KartTuruService as KTS

            self.cari_turu = KTS.cari_rol_metni(ana, self.cari_turu)
            self.tedarikci_modu = self.cari_turu in {"Tedarikçi", "Müşteri/Tedarikçi"} and (
                self.cari_turu == "Tedarikçi" or tedarik_gorunur
            )
            # tedarikci_modu: saf tedarikçi ekran davranışı
            self.tedarikci_modu = self.cari_turu == "Tedarikçi"

    def _cari_ana_tur_yonet(self):
        from kart_turleri_gruplari_ui import hizli_tanim_penceresi
        from database.kart_turu_service import KAPSAM_CARI

        def on_saved(sonuc):
            self._cari_tur_listelerini_yukle()
            if getattr(sonuc, "ad", None):
                self.degerler["ana_kart_turu"].set(sonuc.ad)
                self._cari_ana_tur_degisti()

        hizli_tanim_penceresi(self, kapsam=KAPSAM_CARI, tur="ana", on_saved=on_saved)

    def _cari_alt_tur_yonet(self, rol: str):
        from kart_turleri_gruplari_ui import hizli_tanim_penceresi
        from database.kart_turu_service import KAPSAM_CARI

        ana = next(
            (a for a in self._cari_ana_map.values() if a.muhasebe_rol == rol),
            None,
        )
        if not ana:
            messagebox.showinfo("Alt tür", f"{rol} ana türü bulunamadı.", parent=self)
            return

        def on_saved(sonuc):
            self._cari_ana_tur_degisti(ilk=True)
            if getattr(sonuc, "ad", None):
                hedef = "musteri_alt_tur" if rol == "MUSTERI" else "tedarikci_alt_tur"
                if hedef in self.degerler:
                    self.degerler[hedef].set(sonuc.ad)

        hizli_tanim_penceresi(
            self, kapsam=KAPSAM_CARI, tur="alt", ana_tur_id=ana.id, on_saved=on_saved
        )

    def _cari_tur_kayit_alanlari(self) -> dict:
        from database.kart_turu_service import KartTuruService

        ad = (self.degerler.get("ana_kart_turu").get() if "ana_kart_turu" in self.degerler else "") or ""
        ana = self._cari_ana_map.get(ad)
        musteri_ad = (
            self.degerler["musteri_alt_tur"].get() if "musteri_alt_tur" in self.degerler else ""
        )
        ted_ad = (
            self.degerler["tedarikci_alt_tur"].get() if "tedarikci_alt_tur" in self.degerler else ""
        )
        m_id = self._cari_alt_map.get(musteri_ad) if musteri_ad not in {"", "— Alt Tür Atanmamış —"} else None
        t_id = self._cari_ted_alt_map.get(ted_ad) if ted_ad not in {"", "— Alt Tür Atanmamış —"} else None
        # Rol görünür değilse ilgili alt türü kaydetme
        rol = getattr(ana, "muhasebe_rol", None) if ana else None
        if rol == "MUSTERI":
            t_id = None
        elif rol == "TEDARIKCI":
            m_id = None
        elif rol == "PERSONEL":
            m_id = t_id = None
        return {
            "cari_turu": KartTuruService.cari_rol_metni(ana, self.cari_turu),
            "ana_kart_turu_id": getattr(ana, "id", None),
            "musteri_alt_tur_id": m_id,
            "tedarikci_alt_tur_id": t_id,
        }

    def _grup_uyarisi_goster(self, goster: bool, metin: str = "") -> None:
        lbl = getattr(self, "_grup_uyari_lbl", None)
        if lbl is None:
            return
        if goster:
            lbl.configure(text=metin or "⚠ Sektör grubu uyarısı.")
            if not lbl.winfo_ismapped():
                lbl.pack(fill="x", after=self._grup_satiri)
        else:
            lbl.pack_forget()

    def _gruplari_tazele(self, secili: str | None = None) -> None:
        """Grup listesi değişti: bu kart ve açık diğer cari kartları yenilenir (seçimler korunur)."""
        for kart in list(CariDialog._acik_kartlar):
            try:
                if not kart.winfo_exists() or "musteri_grubu" not in kart.degerler:
                    continue
                if kart is self:
                    kart.musteri_grubu_secimini_hazirla(secili=secili)
                else:
                    onceki_kirli = kart._kirli_mi()
                    kart.musteri_grubu_secimini_hazirla()
                    if not onceki_kirli:
                        kart._snapshot = kart._form_snapshot()
                kart._baslik_rozetlerini_guncelle()
            except tk.TclError:
                continue

    def yeni_grup_ekle(self):
        from database.kart_turu_service import KartTuruService

        grup_adi = simpledialog.askstring("Yeni Sektör Grubu", "Sektör grubu adı:", parent=self)
        if grup_adi is None:
            return
        try:
            sonuc = KartTuruService.sektor_kaydet({"ad": grup_adi.strip()})
            eklenen_grup = sonuc["ad"]
        except Exception as hata:  # noqa: BLE001
            messagebox.showwarning("Sektör eklenemedi", str(hata), parent=self)
            return
        self._gruplari_tazele(secili=eklenen_grup)
        self._grup_uyarisi_goster(False)

    def grup_sil(self):
        ad = self._grup_degeri()
        if not ad:
            messagebox.showinfo("Grubu Sil", "Önce silinecek grubu listeden seçin.", parent=self)
            return
        if not _izin_var("cari_duzenleme"):
            messagebox.showwarning("Yetki", "Müşteri grubu silme yetkiniz yok.", parent=self)
            return
        try:
            bilgi = CariService.grup_kullanimi(ad)
        except Exception as hata:
            messagebox.showerror("Grubu Sil", str(hata), parent=self)
            return
        ad = bilgi["ad"]
        hedef = None
        if bilgi["cari_sayisi"] or bilgi.get("silinmis_sayisi") or bilgi.get("roller"):
            if not bilgi["hedefler"]:
                messagebox.showwarning(
                    "Grubu Sil",
                    f"«{ad}» grubu kullanımda ve taşınabilecek başka grup yok.\n"
                    "Önce «Yeni» ile başka bir grup oluşturun.",
                    parent=self,
                )
                return
            dlg = GrupTasimaDialog(self, ad, bilgi)
            self.wait_window(dlg)
            if not dlg.result:
                return
            hedef = dlg.result
        elif not messagebox.askyesno("Grubu Sil", f"«{ad}» grubu silinsin mi?", parent=self):
            return
        try:
            sonuc = CariService.grup_sil(ad, hedef)
        except (ValueError, PermissionError) as hata:
            messagebox.showerror("Grubu Sil", str(hata), parent=self)
            return
        yeni_secim = sonuc["hedef"] or ""
        kirliydi = self._kirli_mi()
        if self.cari is not None and (getattr(self.cari, "musteri_grubu", "") or "").strip() == sonuc["silinen"]:
            self.cari.musteri_grubu = yeni_secim or None
        self._gruplari_tazele(secili=yeni_secim)
        if not kirliydi:
            self._snapshot = self._form_snapshot()
        mesaj = f"«{sonuc['silinen']}» grubu silindi."
        if sonuc["tasinan"]:
            mesaj += f"\n{sonuc['tasinan']} kart «{sonuc['hedef']}» grubuna taşındı."
        for rol in sonuc.get("tasinan_roller") or []:
            mesaj += f"\n{rol} artık «{sonuc['hedef']}»."
        messagebox.showinfo("Grubu Sil", mesaj, parent=self)

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
        etiket = self._bakiye_yon_metni(bakiye)
        if bakiye > 0:
            renk = UYARI
        elif bakiye < 0:
            renk = BASARI
        else:
            renk = IKINCIL
        if "guncel_bakiye" in self.ozet_kartlari:
            self.ozet_kartlari["guncel_bakiye"]["deger"].configure(
                text=para_goster(abs(bakiye)), fg=renk
            )
            self.ozet_kartlari["guncel_bakiye"]["alt"].configure(
                text=etiket if self.tedarikci_modu else f"{etiket} · {durum}"
            )

        risk = metrik.get("risk_ozeti") or {}
        genel = risk.get("genel") or {}
        if "toplam_risk" in self.ozet_kartlari:
            toplam = (risk.get("satirlar") or {}).get("TOPLAM")
            brut = genel.get("brut") if genel else (toplam["risk"] if toplam else None)
            self.ozet_kartlari["toplam_risk"]["deger"].configure(
                text=para_goster(brut) if brut is not None else "—", fg=LACIVERT
            )
        if "genel_risk" in self.ozet_kartlari:
            deger = genel.get("genel_risk")
            self.ozet_kartlari["genel_risk"]["deger"].configure(
                text=para_goster(deger) if deger is not None else "—",
                fg=LACIVERT if not genel.get("eksik_kur") else DIKKAT,
            )
        if "genel_kalan" in self.ozet_kartlari:
            toplam = (risk.get("satirlar") or {}).get("TOPLAM") or {}
            kalan, asim = toplam.get("kalan"), toplam.get("asim")
            kart = self.ozet_kartlari["genel_kalan"]
            if kalan is None:
                kart["deger"].configure(text="Tanımsız", fg=IKINCIL)
                kart["alt"].configure(text="")
            else:
                metin = para_goster(kalan) + (f" · aşım {para_goster(asim)}" if asim else "")
                kart["deger"].configure(
                    text=metin, fg=UYARI if kalan < 0 else (BASARI if kalan > 0 else DIKKAT)
                )
        if "risk_durumu" in self.ozet_kartlari:
            from cari_risk_ui import DURUM_RENK
            from database.cari_risk_service import TUR_ETIKET

            satirlar = risk.get("satirlar") or {}
            limitli = [s for s in satirlar.values() if s.get("limitli") and s.get("uygula")]
            if not limitli:
                metin, renk = "Limit tanımlı değil", IKINCIL
            else:
                asan = [s for s in limitli if s.get("durum") == "ASILDI"]
                dolu = [s for s in limitli if s.get("durum") == "DOLU"]
                hedef = asan or dolu or limitli
                if asan:
                    metin = f"Limit aşıldı ({', '.join(TUR_ETIKET.get(s.get('tur'), '') for s in asan)})"
                elif dolu:
                    metin = f"Limit dolu ({', '.join(TUR_ETIKET.get(s.get('tur'), '') for s in dolu)})"
                else:
                    metin = "Limit içinde"
                renk = DURUM_RENK.get(hedef[0].get("durum"), LACIVERT)
            self.ozet_kartlari["risk_durumu"]["deger"].configure(text=metin, fg=renk)

        # Risk − |bakiye| farkı: portföy/ciro çek-senet vb. (tıklanınca risk detayı)
        fark_lbl = getattr(self, "_risk_bakiye_fark_lbl", None)
        if fark_lbl is not None:
            brut = Decimal(str((genel.get("brut") if genel else None) or 0))
            net_b = abs(bakiye)
            fark = (brut - net_b).quantize(Decimal("0.01"))
            portfoy = Decimal(str(((risk.get("satirlar") or {}).get("PORTFOY") or {}).get("risk") or 0))
            ciro = Decimal(str(((risk.get("satirlar") or {}).get("CIRO_CEK") or {}).get("risk") or 0)) + Decimal(
                str(((risk.get("satirlar") or {}).get("CIRO_SENET") or {}).get("risk") or 0)
            )
            if abs(fark) >= Decimal("0.01"):
                parcalar = []
                if portfoy:
                    parcalar.append(f"portföy {para_goster(portfoy)}")
                if ciro:
                    parcalar.append(f"ciro {para_goster(ciro)}")
                neden = ", ".join(parcalar) if parcalar else "bileşen detayı"
                fark_lbl.configure(
                    text=f"Risk − bakiye: {para_goster(fark)} ({neden}). Tıkla → döküm.",
                    fg=DIKKAT,
                )
            else:
                fark_lbl.configure(text="", fg=IKINCIL)

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

        if "Toplam Borç" in self.ozet_degerleri or "Toplam borç" in self.ozet_degerleri:
            from cari_borc_alacak_ozet import ozet_metinleri

            for baslik, (metin, satir_renk) in ozet_metinleri(
                metrik, tedarikci_modu=self.tedarikci_modu
            ).items():
                if baslik in self.ozet_degerleri:
                    self.ozet_degerleri[baslik].configure(text=metin, fg=satir_renk)
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
        if hasattr(self, "hareket_tur_filtre"):
            self.hareket_tur_filtre.set("Tümü")
        if hasattr(self, "hareket_arama"):
            self.hareket_arama.delete(0, "end")
        if hasattr(self, "hareket_tarih_bas"):
            self.hareket_tarih_bas.delete(0, "end")
        if hasattr(self, "hareket_tarih_bit"):
            self.hareket_tarih_bit.delete(0, "end")
        self._hareketleri_goster()

    def _hareket_filtreli_satirlar(self):
        tur = "Tümü"
        if hasattr(self, "hareket_tur_filtre"):
            tur = (self.hareket_tur_filtre.get() or "Tümü").strip()
        ara_ham = ""
        if hasattr(self, "hareket_arama"):
            ara_ham = (self.hareket_arama.get() or "").strip()
        ara = turkce_normalize(ara_ham)
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
                metin = turkce_normalize(" ".join(
                    [
                        str(hareket.get("tur") or ""),
                        str(hareket.get("belge_no") or ""),
                        str(hareket.get("aciklama") or ""),
                    ]
                ))
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

    def _usd_karsilik_raporu_ac(self):
        if not self.cari or not getattr(self.cari, "id", None):
            messagebox.showinfo("USD karşılık", "Önce cari kaydını seçin veya kaydedin.", parent=self)
            return
        from cari_usd_rapor_ui import usd_rapor_penceresi

        baslik = f"{getattr(self.cari, 'cari_kodu', '')} - {getattr(self.cari, 'unvan', '')}"
        usd_rapor_penceresi(self, int(self.cari.id), baslik)

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
                            satir.get("net_birim_fiyat_goster")
                            or satir.get("birim_fiyat_goster")
                            or "",
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
        # Yenileme sonrası temel sütun düzeni bozulmasın
        self._hareket_gorunum_uygula()
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
                "",  # barkod
                "",  # urun_adi
                "",  # miktar
                "",  # birim
                "",  # net_birim_fiyat
                "",  # satir_tutari
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
                values=("", "", "", "  (ürün detayı yüklenmedi)", "", "", "", "", "", "", "", "", "", "", "", "", ""),
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
                    values=("", "", "", "  Detay yüklenemedi", "", "", "", "", "", "", "", "", "", "", "", "", ""),
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
                values=("", "", "", f"  {msg}", "", "", "", "", "", "", "", "", "", "", "", "", ""),
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
            urun_adi = (s.get("urun_adi") or "").strip()
            ozet = " · ".join(p for p in parcalar if p)
            # Temel görünümde ürün sütunları gizli → ad + özet Açıklama'da
            if getattr(self, "_hareket_urun_sutunlari_acik", False):
                aciklama_metin = ""
            else:
                miktar_birim = " ".join(
                    x for x in (s.get("miktar_goster") or "", s.get("birim") or "") if x
                ).strip()
                net = s.get("net_goster") or ""
                parca = [x for x in (urun_adi, miktar_birim, net, ozet) if x]
                aciklama_metin = "  " + " · ".join(parca)
            self.hareket_tablosu.insert(
                iid,
                "end",
                text="",
                values=(
                    "",
                    "Ürün",
                    "",
                    aciklama_metin,
                    s.get("barkod") or "",
                    urun_adi,
                    s.get("miktar_goster") or "",
                    s.get("birim") or "",
                    s.get("net_birim_fiyat_goster")
                    or s.get("birim_fiyat_goster")
                    or "",
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

    def _hareket_kapatma_detayi(self):
        if not self.hareket_tablosu or not self.cari:
            return
        secim = self.hareket_tablosu.selection()
        if not secim:
            messagebox.showinfo("Kapatma Detayı", "Lütfen bir hareket satırı seçin.", parent=self)
            return
        iid = secim[0]
        if iid not in self._hareket_iid_meta:
            iid = self.hareket_tablosu.parent(iid) or iid
        meta = self._hareket_iid_meta.get(iid) or {}
        belge_no = (meta.get("belge_no") or "").strip()
        if not belge_no:
            degerler = self.hareket_tablosu.item(iid, "values")
            belge_no = (degerler[2] if degerler and len(degerler) > 2 else "") or ""
        from kapatma_detay_ui import kapatma_detayi_ac

        kapatma_detayi_ac(self, belge_no.strip(), int(self.cari.id))

    def _secili_hareket_meta(self, baslik: str) -> dict | None:
        if not self.hareket_tablosu:
            return None
        secim = self.hareket_tablosu.selection()
        if not secim:
            messagebox.showinfo(baslik, "Lütfen bir hareket satırı seçin.", parent=self)
            return None
        iid = secim[0]
        if iid not in self._hareket_iid_meta:
            iid = self.hareket_tablosu.parent(iid) or iid
        return self._hareket_iid_meta.get(iid) or {}

    @staticmethod
    def _cari_islem_id(meta: dict) -> int | None:
        if meta.get("hareket_kaynak") == "cari_islem" and meta.get("hareket_id"):
            return int(meta["hareket_id"])
        return None

    def _hareket_muhasebe_fisi(self):
        meta = self._secili_hareket_meta("Muhasebe fişi")
        if meta is None:
            return
        from muhasebe_durum_ui import belge_no_kaynagi, cari_islem_kaynagi, fisi_ac

        belge_no = (meta.get("belge_no") or "").strip()
        try:
            kaynak = cari_islem_kaynagi(self._cari_islem_id(meta))
            if kaynak is None and belge_no.startswith("VRM-"):
                kaynak = ("cari_virman", belge_no_kaynagi("cari_virman", belge_no))
            elif kaynak is None and belge_no.startswith(("AHV-", "GHV-")):
                kaynak = ("banka_havale", belge_no_kaynagi("banka_havale", belge_no))
        except Exception as hata:
            messagebox.showerror("Muhasebe fişi", str(hata), parent=self)
            return
        if not kaynak or not kaynak[1]:
            messagebox.showinfo(
                "Muhasebe fişi",
                "Bu hareketin muhasebe fişine kendi evrakından (Belgeyi Aç) ulaşın.",
                parent=self,
            )
            return
        fisi_ac(self, *kaynak)

    def _hareket_tahsilat_odeme_iptal(self):
        baslik = "Tahsilat/Ödeme İptali"
        meta = self._secili_hareket_meta(baslik)
        if meta is None:
            return
        islem_id = self._cari_islem_id(meta)
        try:
            from muhasebe_durum_ui import cari_islem_kaynagi

            kaynak = cari_islem_kaynagi(islem_id)
        except Exception as hata:
            messagebox.showerror(baslik, str(hata), parent=self)
            return
        belge_no = (meta.get("belge_no") or "").strip()
        if kaynak is None and not belge_no.startswith(("THS-", "ODM-")):  # eski THS/ODM'yi servis doğrular
            messagebox.showinfo(
                baslik,
                "Bu hareket cari kartından yapılmış bir tahsilat/ödeme evrakı değil; kendi evrakından iptal edin.",
                parent=self,
            )
            return
        neden = simpledialog.askstring(baslik, f"{belge_no} için iptal nedeni:", parent=self)
        if neden is None:
            return
        if not neden.strip():
            messagebox.showwarning(baslik, "İptal nedeni zorunludur.", parent=self)
            return
        if not messagebox.askyesno(
            baslik,
            f"{belge_no} iptal edilsin mi?\n\n"
            "• Kasa/banka hareketi silinir.\n"
            "• Kapattığı borçlar yeniden açılır.\n"
            "• Muhasebeleştirilmişse muhasebe fişi ters kayıtla kapanır.",
            parent=self,
        ):
            return
        from database.cari_service import CariService

        try:
            CariService.tahsilat_odeme_iptal(islem_id, neden.strip())
        except Exception as hata:
            messagebox.showerror(baslik, str(hata), parent=self)
            return
        self.yenile()

    def acik_kalemler_ac(self):
        if not self.cari or not getattr(self.cari, "id", None):
            messagebox.showwarning("Cari", "Önce cari kartı kaydedin.", parent=self)
            return
        from acik_kalemler_ui import CariAcikKalemlerDialog

        dialog = CariAcikKalemlerDialog(self, int(self.cari.id), self.cari.unvan or "")
        self.wait_window(dialog)

    def odeme_sozleri_ac(self):
        if not self.cari or not getattr(self.cari, "id", None):
            messagebox.showwarning("Cari", "Önce cari kartı kaydedin.", parent=self)
            return
        from odeme_sozu_ui import CariOdemeSozleriDialog

        dialog = CariOdemeSozleriDialog(self, self.cari)
        self.wait_window(dialog)
        self._soz_ozetini_guncelle()

    def _soz_ozetini_guncelle(self):
        lbl = getattr(self, "_soz_ozet_lbl", None)
        if lbl is None or not self.cari or not getattr(self.cari, "id", None):
            return
        try:
            from database.odeme_sozu_service import OdemeSozuService

            oz = OdemeSozuService.cari_ozeti(int(self.cari.id))
        except Exception:
            return
        try:
            lbl.configure(text=oz.get("metin", ""))
        except tk.TclError:
            pass

    def _guncel_istek_mi(self, token: int, cari_id: int) -> bool:
        """Geç dönen arka plan sonucu başka cariye geçilmiş karta yazılmasın."""
        return (
            token == self._yenile_token
            and self.cari is not None
            and int(getattr(self.cari, "id", 0) or 0) == cari_id
        )

    def yenile(self):
        if not self.cari:
            return
        cari_id = int(self.cari.id)
        if getattr(self, "_yenile_devam", None) == (self._yenile_token, cari_id):
            return
        token = self._yenile_token
        self._yenile_devam = (token, cari_id)
        self._yukleniyor = True
        self._fatura_detay_cache = {}
        if hasattr(self, "_yukleniyor_lbl"):
            self._yukleniyor_lbl.configure(text="Yükleniyor…")

        def _is():
            return CariService.kart_ozet_metrikleri(cari_id)

        def _ok(metrik):
            if not self._guncel_istek_mi(token, cari_id):
                return
            try:
                hareketler = (metrik or {}).get("hareketler") or []
                if getattr(self, "risk_paneli", None) is not None:
                    self.risk_paneli.risk_goster((metrik or {}).get("risk_ozeti"))
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
                if hasattr(self, "hareket_tur_filtre") and self.hareket_tur_filtre is not None:
                    mevcut = (self.hareket_tur_filtre.get() or "Tümü").strip() or "Tümü"
                    self.hareket_tur_filtre.configure(values=degerler)
                    self.hareket_tur_filtre.set(mevcut if mevcut in degerler else "Tümü")
                if getattr(self, "hareket_tablosu", None) is not None:
                    self._hareketleri_goster()
                self._baslik_rozetlerini_guncelle()
                self._soz_ozetini_guncelle()
            except Exception as hata:
                messagebox.showerror("Yenileme", f"Özet yüklenemedi:\n{hata}", parent=self)
            finally:
                self._yukleniyor = False
                self._yenile_devam = None
                if hasattr(self, "_yukleniyor_lbl"):
                    self._yukleniyor_lbl.configure(text="")

        def _err(hata):
            if not self._guncel_istek_mi(token, cari_id):
                return
            self._yukleniyor = False
            self._yenile_devam = None
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

    def _bakiye_yon_metni(self, bakiye: Decimal) -> str:
        """Tedarikçide pozitif bakiye bizim borcumuzdur; yön açık yazılır."""
        if self.tedarikci_modu:
            if bakiye > 0:
                return "Alacaklı (tedarikçiye borcumuz)"
            if bakiye < 0:
                return "Borçlu (tedarikçiden alacağımız)"
            return "Kapalı"
        if bakiye > 0:
            return "Borçlu"
        if bakiye < 0:
            return "Alacaklı"
        return "Kapalı"

    def alis_evraklari_ac(self, sekme: str = "fatura"):
        """Bu tedarikçinin faturalanmamış irsaliyeleri, alış ve alış iade faturaları."""
        if not self.cari or not getattr(self.cari, "id", None):
            messagebox.showwarning("Cari", "Önce cari kartı kaydedin.", parent=self)
            return
        from tedarikci_evrak_ui import TedarikciEvraklariDialog

        dialog = TedarikciEvraklariDialog(self, self.cari, sekme=sekme)
        self.wait_window(dialog)
        self.yenile()

    def satis_iade_faturalari_ac(self):
        """Bu müşterinin satış iade faturaları (yalnız bu cari; yeni iade bu cari ile açılır)."""
        cari_id = getattr(self.cari, "id", None) if self.cari else None
        if not cari_id:
            messagebox.showwarning("Cari", "Önce cari kartı kaydedin.", parent=self)
            return
        from app import CariSatisIadeListesiDialog

        dialog = CariSatisIadeListesiDialog(self, int(cari_id))
        self.wait_window(dialog)
        self.yenile()

    def yeni_siparis_ac(self):
        if not self.cari:
            return
        from satis_siparisi_ui import SatisSiparisiKarti

        siparis = SatisSiparisiKarti(self, cari=self.cari)
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
        if not self.cari or self._makbuz_acik:
            return
        from kasa_makbuz_ui import KasaMakbuzDialog

        self._makbuz_acik = True
        try:
            cari_id = int(self.cari.id)
            dialog = KasaMakbuzDialog(self, makbuz_turu="TAHSILAT", cari_id=cari_id)
            if dialog.winfo_exists():
                self.wait_window(dialog)
        finally:
            self._makbuz_acik = False
        if getattr(dialog, "result", None) and self.cari is not None and int(self.cari.id) == cari_id:
            self.yenile()

    def odeme_gir(self):
        if self.cari:
            from app import CariTahsilatOdemeDialog

            dialog = CariTahsilatOdemeDialog(self, self.cari, tur="odeme")
            self.wait_window(dialog)
            if dialog.result:
                self.yenile()

    def cari_virman_ac(self):
        """Cari Virman fişi: müşteri alacak (kaynak), tedarikçi borç (karşı) tarafına gelir."""
        if not self.cari:
            return
        from app import CariVirmanDialog

        taraf = {"hedef_id": self.cari.id} if self.tedarikci_modu else {"kaynak_id": self.cari.id}
        dialog = CariVirmanDialog(self, **taraf)
        self.wait_window(dialog)
        if dialog.result:
            self.yenile()

    def kk_cekimi_ac(self):
        """Müşteriden tedarikçiye kredi kartı çekim fişi; seçili cari kendi alanına gelir."""
        if not self.cari:
            return
        from app import KkCekimiDialog

        taraf = {"tedarikci_id": self.cari.id} if self.tedarikci_modu else {"musteri_id": self.cari.id}
        dialog = KkCekimiDialog(self, **taraf)
        if dialog.winfo_exists():
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

    def kaydet(self, kapat: bool = False) -> bool:
        if not _izin_var("cari_duzenleme", "yeni_kayit"):
            messagebox.showwarning("Yetki", "Cari düzenleme yetkiniz yok.", parent=self)
            return False
        from telefon_bicim import telefon_kayit

        veriler = {}
        for alan in self.degerler:
            if alan == "aktif":
                continue
            veriler[alan] = self._widget_deger(alan) or None
        for alan in ("telefon", "telefon2", "telefon3", "whatsapp"):
            if alan in veriler:
                veriler[alan] = telefon_kayit(veriler.get(alan))
        if not veriler.get("unvan"):
            messagebox.showwarning(
                "Eksik bilgi",
                f"{self.etiket} adı/ünvanı zorunludur.",
                parent=self,
            )
            return False
        # Sektör grubu boş olabilir (Grup Atanmamış)
        self._grup_uyarisi_goster(False)
        # Ana/alt kart türü alanlarını ekle (combobox görünen ad → id)
        for gecici in ("ana_kart_turu", "musteri_alt_tur", "tedarikci_alt_tur"):
            veriler.pop(gecici, None)
        try:
            veriler.update(self._cari_tur_kayit_alanlari())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Kart türü", str(exc), parent=self)
            return False
        try:
            CariService.vergi_no_dogrula(veriler.get("vergi_numarasi"))
        except ValueError as hata:
            messagebox.showerror("Vergi no", str(hata), parent=self)
            return False
        if getattr(self, "risk_paneli", None) is not None:
            from database.cari_risk_service import kart_alanlarini_dogrula

            risk_verileri = self.risk_paneli.degerler()
            try:
                kart_alanlarini_dogrula(dict(risk_verileri))
            except ValueError as hata:
                messagebox.showwarning("Risk ve Limitler", str(hata), parent=self)
                if self._detay_aktif != "risk":
                    self._detay_panel_ac("risk")
                return False
            veriler.update(risk_verileri)
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
        yeni_kayit = self.cari is None
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
            self._hizli_dugmeleri_ayarla()
            if hasattr(self, "not_butonu"):
                self.not_butonu.configure(state="normal")
            self._pasif_btn_guncelle()
            foto = getattr(self, "foto_alani", None)
            if foto is not None and yeni_kayit:
                try:
                    foto.bekleyeni_uygula(int(self.cari.id))
                except (ValueError, PermissionError) as hata:
                    messagebox.showwarning("Fotoğraf", f"Cari kaydedildi; fotoğraf kaydedilemedi:\n{hata}",
                                           parent=self)
            self.yenile()
        self._snapshot = self._form_snapshot()
        self._kirli = False
        self._baslik_rozetlerini_guncelle()
        messagebox.showinfo("Kaydedildi", "Cari kart kaydedildi.", parent=self)
        if kapat:
            self._karti_kapat(onay=False, ana_menuye_don=True)
        return True

    def kaydet_ve_kapat(self):
        """Kaydet; başarılıysa kartı kapatıp Satışlar ana menüsüne dön."""
        self.kaydet(kapat=True)

    def _cari_pencere_boyutlandirma_ac(self) -> None:
        """Cari kart yeniden boyutlanabilir olsun; büyüt/küçült çalışsın."""
        from ui_pencere import belge_penceresini_hazirla, pencere_os_krom_ac

        pencere_os_krom_ac(self)
        try:
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
        from ui_pencere import pencere_asagi

        pencere_asagi(self)

    def _cari_pencere_buyut_toggle(self, _event=None):
        """Tam ekran (zoomed) ↔ önceki boyut."""
        from ui_pencere import pencere_buyut_toggle

        return pencere_buyut_toggle(
            self,
            onceki_attr="_cari_onceki_geometry",
            btn=getattr(self, "_btn_pencere_buyut", None),
        )

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
        self._cariyi_yukle(None)

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
        self._karti_kapat(onay=False, ana_menuye_don=True)

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

    def _kapat_istegi(self, _event=None):
        """X, Kapat, Escape — tek kapanış yolu."""
        self._karti_kapat(onay=True, ana_menuye_don=True)
        return "break"

    def _karti_kapat(self, *, onay: bool = True, ana_menuye_don: bool = True) -> bool:
        """Kartı güvenle kapatır; isteğe bağlı Satışlar / ana pencere dönüşü.

        İptal veya kayıt hatasında kart açık kalır. Başka açık cari kart varken
        ana menüye zorlanmaz (ör. tür değiştirip yeni kart açılırken).
        """
        if onay and not self._kapatmadan_once_onay():
            return False
        self._donus_ana_menu = bool(ana_menuye_don)
        try:
            self.destroy()
        except tk.TclError:
            return False
        return True

    @staticmethod
    def _ana_uygulamayi_geri_yukle(app, *, satislar: bool) -> None:
        """Kart kapandıktan sonra bir kez: görünür + Satışlar (müşteri)."""
        if app is None:
            return
        try:
            if not app.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            if str(app.state()) == "iconic":
                app.deiconify()
        except tk.TclError:
            pass
        try:
            app.lift()
            app.focus_force()
        except tk.TclError:
            pass
        if satislar and hasattr(app, "sayfa_goster"):
            try:
                app.sayfa_goster("satislar", ust_duzey=True)
            except Exception:
                pass
        try:
            app.lift()
            app.focus_force()
        except tk.TclError:
            pass

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
        CariDialog._acik_kartlar.discard(self)
        if getattr(self, "_vazgecildi", False):
            try:
                self.grab_release()
            except tk.TclError:
                pass
            super().destroy()
            return

        app = self._ana_uygulama()
        donus = bool(getattr(self, "_donus_ana_menu", False))
        musteri_kart = not bool(getattr(self, "tedarikci_modu", False))
        # Bu kart dışında hâlâ açık kart var mı? (yerine yeni kart açılıyorsa menüye dönme)
        kalan_var = False
        for k in list(CariDialog._acik_kartlar):
            if k is self:
                continue
            try:
                if k.winfo_exists():
                    kalan_var = True
                    break
            except tk.TclError:
                pass

        try:
            self.grab_release()
        except tk.TclError:
            pass
        # Windows: bağımsız (transient'siz) zoomed kart kapanınca ebeveyn alta düşmesin
        if app is not None:
            try:
                self.transient(app)
            except tk.TclError:
                pass
            try:
                if str(app.state()) == "iconic":
                    app.deiconify()
                app.lift()
            except tk.TclError:
                pass

        try:
            self._clear_invoice_detail_cache()
        except Exception:
            pass
        try:
            self.unbind_all("<F1>")
        except tk.TclError:
            pass
        try:
            if getattr(self, "canvas", None) is not None:
                self.canvas.unbind_all("<MouseWheel>")
        except (tk.TclError, AttributeError):
            pass

        super().destroy()

        if donus and not kalan_var and app is not None:
            try:
                app.after_idle(
                    lambda a=app, s=musteri_kart: CariDialog._ana_uygulamayi_geri_yukle(
                        a, satislar=s
                    )
                )
            except tk.TclError:
                CariDialog._ana_uygulamayi_geri_yukle(app, satislar=musteri_kart)

    def _fare_tekerlegi(self, event):
        canvas = getattr(self, "canvas", None)
        if canvas is None:
            return
        try:
            canvas.yview_scroll(-int(event.delta / 120), "units")
        except tk.TclError:
            pass
