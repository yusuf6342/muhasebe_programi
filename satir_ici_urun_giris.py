"""Evrak satır tablolarında satır içi ürün girişi — ortak bileşen.

Ürün tablosunun sonunda her zaman bir boş giriş satırı durur. Yalnızca iki arama
alanı vardır: barkod (okutma, doğrudan sorgu) ve ürün adı (gecikmeli arama listesi;
tam barkod / tam ürün kodu da çözülür). Ürün kodu kolonu bilgi amaçlıdır; tabloda
barkod kolonu yoksa barkod kutusu giriş satırının kod hücresinde durur. F10 stok
listesini açar, sağ tık menüsü Ürün Seç / Stok Kartını Aç / Yeni Stok Kartı sunar.

Boş giriş satırı belge satırı değildir: ``satirlar`` listesine girmez; kayıt,
yazdırma, toplam, stok ve satır sayısına katılmaz. Belgeye özgü kurallar (fiyat
kaynağı, birleştirme, kaynak bağı, manuel kalem) kartın verdiği geri çağrılarla
uygulanır.
"""

from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, ttk
from typing import Any, Callable, Sequence

YENI_SATIR_IID = "__yeni__"
MIN_ARAMA_HARF = 2
DEBOUNCE_MS = 250
SAYFA = 25
AZAMI_SONUC = 100
ONBELLEK_SN = 30.0
ROLLER = ("barkod", "ad")
HIZLI_STOK_KAYNAGI = "Hızlı Stok"
_YER_TUTUCU = "➕ Ürün adı yazın  (F10: stok listesi)"
_BARKOD_YER_TUTUCU = "▦ Barkod okutun"
_EDITOR_MIN_GENISLIK = 80


# ─── Yardımcılar ───────────────────────────────────────────────────


def giris_bileseni(dialog) -> "SatirIciUrunGirisi | None":
    g = getattr(dialog, "_satir_ici_giris", None)
    return g if isinstance(g, SatirIciUrunGirisi) else None


def ekleme_konumu(dialog) -> int | None:
    k = getattr(dialog, "_satir_ekleme_konumu", None)
    return k if isinstance(k, int) and not isinstance(k, bool) else None


def toplu_ekleme_mi(dialog) -> bool:
    return getattr(dialog, "_satir_toplu_ekleme", False) is True


def veri_iidleri(tablo: ttk.Treeview) -> list[str]:
    """Boş giriş satırı hariç tablo satır kimlikleri."""
    try:
        return [i for i in tablo.get_children() if i != YENI_SATIR_IID]
    except tk.TclError:
        return []


def satir_indeksi(tablo: ttk.Treeview, iid: str | None) -> int | None:
    if not iid or iid == YENI_SATIR_IID:
        return None
    try:
        return int(tablo.index(iid))
    except tk.TclError:
        return None


def ondalik(metin: Any, varsayilan: Decimal | None = None) -> Decimal:
    """TR biçimli sayı metnini Decimal'e çevirir; hatada ValueError (varsayılan yoksa)."""
    if isinstance(metin, Decimal):
        return metin
    ham = str(metin if metin is not None else "").strip().replace("%", "").replace("TL", "").strip()
    if not ham:
        if varsayilan is not None:
            return varsayilan
        raise ValueError("Sayı girin.")
    if "," in ham and "." in ham:
        ham = ham.replace(".", "").replace(",", ".") if ham.rfind(",") > ham.rfind(".") else ham.replace(",", "")
    elif "," in ham:
        ham = ham.replace(".", "").replace(",", ".")
    try:
        return Decimal(ham)
    except (InvalidOperation, ValueError):
        if varsayilan is not None:
            return varsayilan
        raise ValueError(f"Geçersiz sayı: {metin}") from None


def sayi_metni(deger: Any) -> str:
    try:
        d = Decimal(str(deger if deger not in (None, "") else 0))
    except (InvalidOperation, ValueError):
        return str(deger or "")
    metin = f"{d:f}"
    if "." in metin:
        metin = metin.rstrip("0").rstrip(".")
    return (metin or "0").replace(".", ",")


def _iliski(stok, ad: str) -> list:
    """Oturumu kapanmış nesnede yüklenmemiş ilişki hata vermesin."""
    try:
        return list(getattr(stok, ad, None) or [])
    except Exception:
        return []


def _satis_fiyati(stok) -> Decimal:
    fiyatlar = _iliski(stok, "fiyatlar")
    for f in fiyatlar:
        if (getattr(f, "fiyat_adi", "") or "").strip().upper() == "SATIŞ FİYATI 1":
            return Decimal(str(f.tutar or 0))
    for f in fiyatlar:
        if (getattr(f, "fiyat_adi", "") or "").strip().upper().startswith("SATIŞ FİYATI"):
            return Decimal(str(f.tutar or 0))
    return Decimal("0")


def stok_ozeti(stok) -> dict[str, Any]:
    """StokKarti → düz sözlük (oturum dışında güvenle kullanılır)."""
    try:
        mevcut = sum((Decimal(str(l.kalan_miktar or 0)) for l in _iliski(stok, "lotlar")), Decimal("0"))
    except Exception:
        mevcut = Decimal("0")
    barkod = (getattr(stok, "barkod", None) or "").strip()
    if not barkod:
        for b in _iliski(stok, "barkodlar"):
            if (getattr(b, "barkod", None) or "").strip():
                barkod = b.barkod.strip()
                break
    kdv = getattr(stok, "kdv_orani", None)
    return {
        "id": int(getattr(stok, "id", 0) or 0) or None,
        "kod": (stok.stok_kodu or "").strip(),
        "ad": (stok.stok_adi or "").strip(),
        "birim": (stok.birim or "Adet").strip() or "Adet",
        "barkod": barkod,
        "stok": mevcut,
        "satis_fiyati": _satis_fiyati(stok),
        "kdv": Decimal(str(kdv)) if kdv is not None else None,
    }


def urun_degerleri(ozet: dict[str, Any], *, kaynak: str = "Stok Kartı") -> tuple:
    """UrunSecDialog sözleşmesi: (kod, ad, birim, stok, fiyat, kaynak, kdv, product_id)."""
    from database.fatura_kdv_service import satir_kdv_metin_sayisal

    kdv = ozet.get("kdv")
    return (
        ozet.get("kod") or "",
        ozet.get("ad") or "",
        ozet.get("birim") or "Adet",
        sayi_metni(ozet.get("stok") or 0).replace(",", "."),
        f"{Decimal(str(ozet.get('satis_fiyati') or 0)):f}",
        kaynak,
        satir_kdv_metin_sayisal(kdv if kdv is not None else 20),
        ozet.get("id"),
    )


def barkod_kaydindan_degerler(kayit: dict[str, Any]) -> tuple:
    """barkod_ile_ara kaydı → UrunSecDialog sözleşmesi (okutulan birim ile)."""
    from database.fatura_kdv_service import satir_kdv_metin_sayisal

    birim = (kayit.get("barkod_birim") or kayit.get("birim") or "Adet").strip() or "Adet"
    kdv = kayit.get("kdv_orani")
    return (
        (kayit.get("stok_kodu") or "").strip(),
        (kayit.get("stok_adi") or "").strip(),
        birim,
        sayi_metni(kayit.get("mevcut_stok") or 0).replace(",", "."),
        f"{Decimal(str(kayit.get('birim_fiyat') or 0)):f}",
        "Barkod",
        satir_kdv_metin_sayisal(kdv if kdv is not None else 20),
        kayit.get("stok_id") or kayit.get("product_id"),
    )


def urun_ara(
    metin: str,
    *,
    limit: int = SAYFA,
    depo_ad: str | None = None,
    sadece_stokta: bool = False,
) -> dict[str, Any]:
    """Çok kelimeli, sıra bağımsız stok araması (tam barkod / tam kod önce)."""
    from database.search_service import SearchService

    sonuc = SearchService.search_stocks(
        metin,
        limit=max(1, min(int(limit), AZAMI_SONUC)),
        sadece_stokta=sadece_stokta,
        depo_ad=depo_ad or None,
    )
    return {
        "urunler": [stok_ozeti(s) for s in sonuc.get("urunler") or []],
        "toplam": int(sonuc.get("toplam") or 0),
        "barkod_tam": bool(sonuc.get("barkod_tam")),
        "mesaj": sonuc.get("mesaj") or "",
    }


def alis_birim_fiyati(kod: str, birim: str | None = None) -> Decimal:
    """Son alış fiyatı (ana birim) seçilen birime çevrilmiş; satış fiyatı asla kullanılmaz."""
    from database.stok_service import StokService

    temel = Decimal(str(StokService.son_alis_fiyati(kod, Decimal("0")) or 0))
    if not birim:
        return temel
    try:
        from fatura_satir_birim_service import _stok_yukle, fiyat_birim_donustur

        stok = _stok_yukle(kod)
        ana = ((getattr(stok, "birim", None) or "Adet") if stok is not None else "Adet").strip()
        if birim.strip().casefold() == ana.casefold():
            return temel
        return fiyat_birim_donustur(temel, ana, birim, kod)
    except Exception:
        return temel


def iskonto_metni(satir: dict[str, Any]) -> str:
    """Hücre editörü için: «10+5» (sıfır olmayan oranlar)."""
    oranlar = [satir.get(k) or 0 for k in ("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3")]
    dolu = [sayi_metni(o) for o in oranlar if ondalik(o, Decimal("0")) != 0]
    return "+".join(dolu)


def iskonto_metni_coz(metin: str) -> tuple[Decimal, Decimal, Decimal]:
    """«10+5+2» / «10» → üç kademeli iskonto; doğrulama iskonto_hesap_service ile."""
    from database.iskonto_hesap_service import iskonto_oranlarini_dogrula

    parcalar = [p for p in str(metin or "").replace("%", "").replace(" ", "").split("+") if p != ""]
    if len(parcalar) > 3:
        raise ValueError("En fazla 3 kademe iskonto girilebilir (ör. 10+5+2).")
    oranlar = [ondalik(p) for p in parcalar] + [Decimal("0")] * (3 - len(parcalar))
    return tuple(iskonto_oranlarini_dogrula(*oranlar))  # type: ignore[return-value]


def kaynak_bagli_mi(satir: dict[str, Any]) -> bool:
    return any(
        satir.get(k)
        for k in ("siparis_satiri_id", "irsaliye_satiri_id", "kaynak_fatura_satiri_id", "talep_satiri_id")
    )


def birlesecek_satir(
    satirlar: Sequence[dict[str, Any]],
    yeni: dict[str, Any],
    *,
    fiyat_alani: str,
    ek_alanlar: Sequence[str] = ("iskonto_orani", "iskonto_orani_2", "iskonto_orani_3", "depo"),
) -> int | None:
    """Aynı barkod okutulduğunda miktarı artırılacak satır — kurallar farklıysa None."""

    def _n(v) -> str:
        try:
            return str(ondalik(v, Decimal("0")).quantize(Decimal("0.0001")))
        except Exception:
            return str(v or "")

    for i, s in enumerate(satirlar):
        if kaynak_bagli_mi(s) or s.get("is_manual_item") or s.get("manuel"):
            continue
        if (s.get("urun_kodu") or "").strip() != (yeni.get("urun_kodu") or "").strip():
            continue
        if (s.get("birim") or "").strip().casefold() != (yeni.get("birim") or "").strip().casefold():
            continue
        if _n(s.get(fiyat_alani)) != _n(yeni.get(fiyat_alani)):
            continue
        if any(
            (_n(s.get(a)) if a != "depo" else (s.get(a) or "").strip())
            != (_n(yeni.get(a)) if a != "depo" else (yeni.get(a) or "").strip())
            for a in ek_alanlar
        ):
            continue
        return i
    return None


def _kolon_adi(tablo: ttk.Treeview, x: int) -> str | None:
    try:
        sira = int(str(tablo.identify_column(x)).replace("#", "")) - 1
        gorunen = tablo["displaycolumns"]
        if not gorunen or tuple(gorunen) == ("#all",):
            gorunen = tablo["columns"]
        return tuple(gorunen)[sira]
    except (tk.TclError, ValueError, IndexError, TypeError):
        return None


def _gorunur_kolonlar(tablo: ttk.Treeview) -> tuple[str, ...]:
    try:
        gorunen = tablo["displaycolumns"]
        if not gorunen or tuple(gorunen) == ("#all",):
            gorunen = tablo["columns"]
        return tuple(gorunen)
    except tk.TclError:
        return ()


def _yazdirilabilir(event) -> bool:
    ch = getattr(event, "char", "") or ""
    if not ch or len(ch) != 1 or not ch.isprintable() or ch.isspace():
        return False
    durum = int(getattr(event, "state", 0) or 0)
    # Control (0x4) / Alt (0x20000 Windows, 0x8 X11) kısayolları hariç
    return not (durum & 0x4 or durum & 0x20000)


# ─── Genel hücre düzenleyici (fatura dışı kartlar) ────────────────


@dataclass
class HucreAlani:
    kolon: str
    tur: str = "sayi"  # sayi | metin | secim | ozel
    secenekler: Callable[[int], Sequence[str]] | None = None
    serbest: bool = False
    izin: Callable[[int], bool | str] | None = None
    ozel: Callable[[int], None] | None = None
    deger: Callable[[int], str] | None = None


def satir_editorlerini_kapat(dialog, *, uygula: bool = True) -> None:
    """Satır silme öncesi: açık hücre/ürün editörlerini kapatır ve tablo seçimini temizler.

    Editör satır indeksini tutar; silmeden sonra açık kalırsa kaymış indeksle başka satıra yazar
    ve tablo üstünde eski değerle görünür kalır. uygula=True iken bekleyen geçerli değer önce yazılır.
    """
    hucre = getattr(dialog, "_hucre", None)
    if hucre is not None and getattr(hucre, "editor", None) is not None:
        if uygula:
            try:
                hucre.bekleyeni_uygula()
            except Exception:
                pass
        hucre.kapat()
    if getattr(dialog, "_satir_hucre_editor", None) is not None:
        from fatura_satir_hucre_edit import _editor_kapat, acik_editoru_uygula

        if uygula:
            try:
                acik_editoru_uygula(dialog)
            except Exception:
                pass
        _editor_kapat(dialog)
    giris = getattr(dialog, "_satir_ici_giris", None)
    if giris is not None:
        giris.kapat()


def tablo_secimini_temizle(tablo) -> None:
    try:
        secim = tablo.selection()
        if secim:
            tablo.selection_remove(*secim)
        tablo.focus("")
    except tk.TclError:
        pass


def silme_sonrasi_odakla(dialog) -> None:
    """Silmeden sonra sonraki ürün için barkod / ürün arama alanına dön."""
    giris = getattr(dialog, "_satir_ici_giris", None)
    if giris is not None:
        giris.odakla()


def satir_silme_sonrasi_temizle(dialog, tablo) -> None:
    """Satırlar silinip tablo yenilendikten sonra: editör, seçim ve odak sıfırlanır."""
    satir_editorlerini_kapat(dialog, uygula=False)
    tablo_secimini_temizle(tablo)
    silme_sonrasi_odakla(dialog)


class SatirHucreDuzenleyici:
    """Satır hücrelerini yerinde düzenler; Enter/Tab sırayla ilerler, son alanda giriş satırına geçer."""

    def __init__(
        self,
        dialog,
        tablo: ttk.Treeview,
        alanlar: Sequence[HucreAlani],
        *,
        uygula: Callable[[int, str, str], None],
        satir_sayisi: Callable[[], int],
        kilitli: Callable[[], bool] = lambda: False,
        bitince: Callable[[], None] | None = None,
    ):
        self.dialog = dialog
        self.tablo = tablo
        self.alanlar = {a.kolon: a for a in alanlar}
        self.sira = [a.kolon for a in alanlar]
        self.uygula_fn = uygula
        self.satir_sayisi = satir_sayisi
        self.kilitli = kilitli
        self.bitince = bitince
        self.editor: tk.Widget | None = None
        self._var: tk.StringVar | None = None
        self._konum: tuple[int, str] | None = None
        self._isleniyor = False
        tablo.bind("<Double-1>", self._cift_tik, add="+")
        tablo.bind("<F2>", self._f2, add="+")
        tablo.bind("<Return>", self._enter_tablo, add="+")
        tablo.bind("<KP_Enter>", self._enter_tablo, add="+")
        tablo.bind("<Button-1>", self._tek_tik, add="+")

    # -- durum
    def acik_mi(self) -> bool:
        return self.editor is not None

    def duzenlenebilir_mi(self, idx: int, kolon: str) -> bool | str:
        if self.kilitli():
            return False
        if not (0 <= idx < self.satir_sayisi()):
            return False
        alan = self.alanlar.get(kolon)
        if alan is None or kolon not in _gorunur_kolonlar(self.tablo):
            return False
        if alan.izin is not None:
            return alan.izin(idx)
        return True

    # -- olaylar
    def _hucre(self, event) -> tuple[int, str] | None:
        try:
            if self.tablo.identify_region(event.x, event.y) != "cell":
                return None
        except tk.TclError:
            return None
        iid = self.tablo.identify_row(event.y)
        idx = satir_indeksi(self.tablo, iid)
        kolon = _kolon_adi(self.tablo, event.x)
        if idx is None or kolon not in self.alanlar:
            return None
        return idx, kolon

    def _tek_tik(self, event):
        if self.acik_mi():
            self.bekleyeni_uygula()
        hucre = self._hucre(event)
        if hucre is None:
            return None
        idx, kolon = hucre
        if self.alanlar[kolon].tur == "ozel":
            return None
        self.dialog.after(160, lambda: self._gecikmeli(idx, kolon))
        return None

    def _gecikmeli(self, idx, kolon):
        if getattr(self, "_cift_engel", False) or self.acik_mi():
            return
        self.duzenle(idx, kolon, sessiz=True)

    def _cift_tik(self, event):
        self._cift_engel = True
        self.dialog.after(260, lambda: setattr(self, "_cift_engel", False))
        hucre = self._hucre(event)
        if hucre is None:
            return None
        self.duzenle(*hucre)
        return "break"

    def _f2(self, _e=None):
        idx = satir_indeksi(self.tablo, (self.tablo.selection() or (None,))[0])
        if idx is not None:
            self.ilk_alana(idx)
        return "break"

    def _enter_tablo(self, _e=None):
        if self.acik_mi():
            return "break"
        idx = satir_indeksi(self.tablo, (self.tablo.selection() or (None,))[0])
        if idx is None:
            return None
        self.ilk_alana(idx)
        return "break"

    # -- düzenleme
    def ilk_alana(self, idx: int) -> None:
        for kolon in self.sira:
            if self.duzenlenebilir_mi(idx, kolon) is True:
                self.dialog.after_idle(lambda k=kolon: self.duzenle(idx, k))
                return

    def duzenle(self, idx: int, kolon: str, *, sessiz: bool = False) -> None:
        izin = self.duzenlenebilir_mi(idx, kolon)
        if izin is not True:
            if isinstance(izin, str) and izin and not sessiz:
                messagebox.showwarning("Satır", izin, parent=self.dialog)
            return
        alan = self.alanlar[kolon]
        if alan.tur == "ozel" and alan.ozel is not None:
            self._konum = (idx, kolon)
            alan.ozel(idx)
            return
        iids = veri_iidleri(self.tablo)
        if idx >= len(iids):
            return
        iid = iids[idx]
        self.kapat()
        try:
            self.tablo.selection_set(iid)
            self.tablo.see(iid)
            self.dialog.update_idletasks()
            box = self.tablo.bbox(iid, kolon)
        except tk.TclError:
            box = None
        if not box:
            return
        x, y, w, h = box
        if alan.deger is not None:
            baslangic = alan.deger(idx)
        else:
            try:
                baslangic = str(self.tablo.set(iid, kolon) or "")
            except tk.TclError:
                baslangic = ""
        self._var = tk.StringVar(value=baslangic)
        if alan.tur == "secim":
            degerler = list(alan.secenekler(idx) if alan.secenekler else [])
            if baslangic and baslangic not in degerler:
                degerler.append(baslangic)
            ed = ttk.Combobox(
                self.tablo, textvariable=self._var, values=degerler,
                state="normal" if alan.serbest else "readonly", font=("Segoe UI", 10),
            )
            ed.bind("<<ComboboxSelected>>", lambda _e: self._kaydet(ilerle=True))
        else:
            ed = ttk.Entry(
                self.tablo, textvariable=self._var, font=("Segoe UI", 10),
                justify="right" if alan.tur == "sayi" else "left",
            )
        ed.place(x=x, y=y, width=max(w, 70), height=max(h, 24))
        ed.focus_set()
        if isinstance(ed, ttk.Entry) and not isinstance(ed, ttk.Combobox):
            ed.selection_range(0, "end")
        ed.bind("<Return>", lambda _e: self._kaydet(ilerle=True))
        ed.bind("<KP_Enter>", lambda _e: self._kaydet(ilerle=True))
        ed.bind("<Tab>", lambda _e: self._kaydet(ilerle=True))
        ed.bind("<Shift-Tab>", lambda _e: self._kaydet(ilerle=True, geri=True))
        ed.bind("<Shift-Return>", lambda _e: self._kaydet(ilerle=True, geri=True))
        ed.bind("<Escape>", lambda _e: self._iptal())
        ed.bind("<FocusOut>", self._odak_cikti)
        self.editor = ed
        self._konum = (idx, kolon)

    def _odak_cikti(self, _e=None):
        def _kontrol():
            if self.editor is None:
                return
            try:
                odak = self.dialog.focus_get()
            except (tk.TclError, KeyError):
                odak = None
            if odak is self.editor:
                return
            if odak is not None and str(odak).startswith(str(self.editor)):
                return
            self.bekleyeni_uygula()

        self.dialog.after(120, _kontrol)

    def kapat(self) -> None:
        ed, self.editor = self.editor, None
        if ed is not None:
            try:
                ed.destroy()
            except tk.TclError:
                pass

    def _iptal(self):
        self.kapat()
        try:
            self.tablo.focus_set()
        except tk.TclError:
            pass
        return "break"

    def bekleyeni_uygula(self) -> bool:
        """Açık editördeki değeri satıra yazar (Kaydet öncesi). Hatalıysa False."""
        if self.editor is None:
            return True
        return self._kaydet(ilerle=False, sessiz_kapat=True) != "hata"

    def _kaydet(self, *, ilerle: bool, geri: bool = False, sessiz_kapat: bool = False):
        if self._isleniyor or self.editor is None or self._konum is None:
            return "break"
        idx, kolon = self._konum
        metin = (self._var.get() if self._var is not None else "").strip()
        self._isleniyor = True
        try:
            try:
                self.uygula_fn(idx, kolon, metin)
            except ValueError as hata:
                messagebox.showwarning("Satır", str(hata), parent=self.dialog)
                if sessiz_kapat:
                    self.kapat()
                    return "hata"
                try:
                    self.editor.focus_set()
                except tk.TclError:
                    pass
                return "break"
            self.kapat()
        finally:
            self._isleniyor = False
        if ilerle:
            self.ilerle(idx, kolon, geri=geri)
        return "break"

    def ilerle(self, idx: int, kolon: str, *, geri: bool = False) -> None:
        """Sonraki düzenlenebilir hücre; satırın son alanında giriş satırına geç."""
        try:
            i = self.sira.index(kolon)
        except ValueError:
            i = -1
        adim = -1 if geri else 1
        j = i + adim
        while 0 <= j < len(self.sira):
            if self.duzenlenebilir_mi(idx, self.sira[j]) is True:
                self.dialog.after_idle(lambda k=self.sira[j]: self.duzenle(idx, k))
                return
            j += adim
        if not geri and self.bitince is not None:
            self.dialog.after_idle(self.bitince)


# ─── Satır içi ürün girişi ─────────────────────────────────────────


class SatirIciUrunGirisi:
    """Tablonun sonundaki boş giriş satırı + hücre editörü + arama listesi."""

    def __init__(
        self,
        dialog,
        tablo: ttk.Treeview,
        *,
        urun_ekle: Callable[[tuple, int | None], int | None],
        kolonlar: dict[str, str],
        barkod_isle: Callable[[str, int | None], int | None] | None = None,
        manuel_ekle: Callable[[str, int | None], int | None] | None = None,
        urun_degistir: Callable[[int, tuple], bool] | None = None,
        kilitli: Callable[[], bool] = lambda: False,
        miktara_git: Callable[[int], None] | None = None,
        depo: Callable[[], str] | None = None,
        sadece_stokta_ad: bool = False,
        fiyat_turu: str = "satis",
        fiyat_goster: Callable[[], bool] = lambda: True,
        stok_goster: Callable[[], bool] = lambda: True,
        alis_fiyati: Callable[[str], Any] | None = None,
        bildir: Callable[[str, str], None] | None = None,
        yeni_stok_eklendi: Callable[[Any], None] | None = None,
        satir_menusu: Callable[[int], list[tuple[str, Callable[[], None]]]] | None = None,
        yer_tutucu: str = _YER_TUTUCU,
        ilk_rol: str = "ad",
    ):
        self.dialog = dialog
        self.tablo = tablo
        self.urun_ekle_fn = urun_ekle
        self.kolonlar = {r: k for r, k in kolonlar.items() if r in ROLLER and k}
        if "barkod" not in self.kolonlar and kolonlar.get("kod"):
            self.kolonlar = {"barkod": kolonlar["kod"], **self.kolonlar}
        self.rol_kolon = dict(self.kolonlar)
        self.kolon_rol = {k: r for r, k in self.kolonlar.items()}
        self.barkod_isle_fn = barkod_isle
        self.manuel_ekle_fn = manuel_ekle
        self.urun_degistir_fn = urun_degistir
        self.kilitli = kilitli
        self.miktara_git = miktara_git
        self.depo = depo or (lambda: "")
        self.sadece_stokta_ad = sadece_stokta_ad
        self.fiyat_turu = fiyat_turu
        self.fiyat_goster = fiyat_goster
        self.stok_goster = stok_goster
        self.alis_fiyati = alis_fiyati
        self.bildir_fn = bildir
        self.yeni_stok_eklendi = yeni_stok_eklendi
        self.satir_menusu = satir_menusu
        self.yer_tutucu = yer_tutucu
        self.ilk_rol = ilk_rol if ilk_rol in self.kolonlar else next(iter(self.kolonlar), "ad")

        self.entry: ttk.Entry | None = None
        self._var = tk.StringVar(master=dialog)
        self._rol: str | None = None
        self._hedef_idx: int | None = None  # dolu satırda açık ürün değişimi
        self._ekleme_konumu: int | None = None  # araya ekleme
        self._after: str | None = None
        self._seq = 0
        self._sonuc_metin = ""
        self._sonuclar: list[dict[str, Any]] = []
        self._toplam = 0
        self._secili = -1
        self._popup: tk.Toplevel | None = None
        self._pop_tree: ttk.Treeview | None = None
        self._pop_durum: ttk.Label | None = None
        self._isleniyor = False
        self._onbellek: dict[tuple, tuple[float, dict]] = {}
        self._son_ekleme: tuple[str, float] = ("", 0.0)
        # Kart geri çağrısı için: "barkod" okutmada aynı satır birleşebilir, "secim"de yeni satır
        self.son_islem = "secim"
        self._bag_etiket = f"SatirIciGiris{id(self)}"
        self._kur()

    # ─── kurulum
    def _kur(self) -> None:
        t = self.tablo
        try:
            t.tag_configure(
                "yeni_giris", foreground="#64748B", background="#FFFBEB",
                font=("Segoe UI", 10, "italic"),
            )
        except tk.TclError:
            pass
        etiket = self._bag_etiket
        t.bindtags((etiket,) + tuple(x for x in t.bindtags() if x != etiket))
        t.bind_class(etiket, "<Button-1>", self._tablo_tik)
        t.bind_class(etiket, "<Double-1>", self._tablo_tik)
        t.bind_class(etiket, "<Button-3>", self._tablo_sag_tik)
        t.bind_class(etiket, "<KeyPress>", self._tablo_tus)
        t.bind_class(etiket, "<Down>", self._tablo_asagi)
        t.bind_class(etiket, "<F10>", self._tablo_f10)
        t.bind_class(etiket, "<<TreeviewSelect>>", self._secim_temizle)
        t.bind("<Configure>", lambda _e: self._yeniden_yerlestir(), add="+")
        t.bind("<MouseWheel>", lambda _e: self.dialog.after(1, self._yeniden_yerlestir), add="+")
        self._editor_olustur()
        self.dialog._satir_ici_giris = self

    def _f10(self, _e=None):
        self.stok_listesi_ac()
        return "break"

    def _tablo_f10(self, _e=None):
        """Dolu satır seçiliyse kartın kendi F10'u (ör. manuel fiyat) çalışır."""
        try:
            secim = [i for i in self.tablo.selection() if i != YENI_SATIR_IID]
        except tk.TclError:
            secim = []
        if secim:
            return None
        return self._f10()

    def _secim_temizle(self, _e=None):
        try:
            if YENI_SATIR_IID in self.tablo.selection():
                self.tablo.selection_remove(YENI_SATIR_IID)
        except tk.TclError:
            pass
        return None

    # ─── giriş satırı
    def tabloya_ekle(self) -> None:
        """Tablo yenilendikten sonra çağrılır; giriş satırını sona koyar."""
        t = self.tablo
        try:
            if self.kilitli():
                if t.exists(YENI_SATIR_IID):
                    t.delete(YENI_SATIR_IID)
                self.kapat()
                return
            kolonlar = list(t["columns"])
            degerler = [""] * len(kolonlar)
            for rol, metin in (("barkod", _BARKOD_YER_TUTUCU), ("ad", self.yer_tutucu)):
                hedef = self.kolonlar.get(rol)
                if hedef in kolonlar:
                    degerler[kolonlar.index(hedef)] = metin
            if t.exists(YENI_SATIR_IID):
                t.item(YENI_SATIR_IID, values=degerler, tags=("yeni_giris",))
                t.move(YENI_SATIR_IID, "", "end")
            else:
                t.insert("", "end", iid=YENI_SATIR_IID, values=degerler, tags=("yeni_giris",))
        except tk.TclError:
            return
        if self.entry is not None and self._hedef_idx is None:
            self.dialog.after_idle(self._yeniden_yerlestir)

    def _hedef_iid(self) -> str | None:
        if self._hedef_idx is None:
            return YENI_SATIR_IID
        iids = veri_iidleri(self.tablo)
        return iids[self._hedef_idx] if 0 <= self._hedef_idx < len(iids) else None

    def _rol_gorunur(self, rol: str) -> bool:
        return self.kolonlar.get(rol) in _gorunur_kolonlar(self.tablo)

    def _roller(self) -> list[str]:
        gorunen = _gorunur_kolonlar(self.tablo)
        return [self.kolon_rol[k] for k in gorunen if k in self.kolon_rol]

    def acik_mi(self) -> bool:
        return self.entry is not None and self._rol is not None

    def ac(self, rol: str | None = None, metin: str | None = None, *, hedef_idx: int | None = None) -> None:
        """Giriş satırında (veya hedef satırda) ürün hücresi editörünü aç."""
        if self.kilitli():
            return
        roller = self._roller()
        if not roller:
            return
        rol = rol if rol in roller else (self.ilk_rol if self.ilk_rol in roller else roller[0])
        self._hedef_idx = hedef_idx
        if hedef_idx is None:
            self.tabloya_ekle()
        self._rol = rol
        self._editor_olustur()
        try:
            self.entry.configure(state="normal")
        except tk.TclError:
            pass
        self._var.set(metin or "")
        self._yeniden_yerlestir(odakla=True)

    def _editor_olustur(self) -> None:
        if self.entry is not None:
            return
        self.entry = ttk.Entry(self.tablo, textvariable=self._var, font=("Segoe UI", 10))
        e = self.entry
        e.bind("<KeyRelease>", self._tus_birakildi)
        e.bind("<Return>", self._enter)
        e.bind("<KP_Enter>", self._enter)
        e.bind("<Escape>", self._esc)
        e.bind("<Down>", self._asagi)
        e.bind("<Up>", self._yukari)
        e.bind("<Next>", self._sayfa_asagi)
        e.bind("<Tab>", lambda _e: self._rol_gec(1))
        e.bind("<Shift-Tab>", lambda _e: self._rol_gec(-1))
        e.bind("<ISO_Left_Tab>", lambda _e: self._rol_gec(-1))
        e.bind("<F10>", self._f10)
        e.bind("<Button-3>", self._editor_sag_tik)
        e.bind("<FocusOut>", self._odak_cikti)

    def _yeniden_yerlestir(self, odakla: bool = False) -> None:
        if self.entry is None or self._rol is None:
            return
        iid = self._hedef_iid()
        kolon = self.kolonlar.get(self._rol)
        box = None
        if iid is not None:
            try:
                self.tablo.see(iid)
                box = self.tablo.bbox(iid, kolon)
            except tk.TclError:
                box = None
        if not box:
            try:
                self.dialog.update_idletasks()
                box = self.tablo.bbox(iid, kolon) if iid else None
            except tk.TclError:
                box = None
        if not box:
            try:
                self.entry.place_forget()
            except tk.TclError:
                pass
            return
        x, y, w, h = box
        try:
            self.entry.place(x=x, y=y, width=max(w, _EDITOR_MIN_GENISLIK), height=max(h, 24))
            self.entry.lift()
            if odakla:
                self.entry.focus_set()
                self.entry.icursor("end")
        except tk.TclError:
            return
        self._popup_konum()

    def kapat(self) -> None:
        self._iptal_debounce()
        self._popup_kapat()
        self._rol = None
        self._hedef_idx = None
        if self._ekleme_konumu is not None:
            self._ekleme_konumu = None
            lbl = getattr(self, "_durum_lbl", None)
            if lbl is not None:
                try:
                    lbl.place_forget()
                except tk.TclError:
                    pass
        if self.entry is not None:
            try:
                self.entry.place_forget()
            except tk.TclError:
                pass
        try:
            self._var.set("")
        except tk.TclError:
            pass

    def bekleyeni_uygula(self) -> None:
        """Kaydet öncesi: arama metni ürün seçilmiş gibi kaydedilmez — editör kapanır."""
        self.kapat()

    def odakla(self) -> None:
        """Satır işleminden sonra sonraki ürün için giriş satırına dön."""
        rol = self._rol or self.ilk_rol
        self.dialog.after_idle(lambda: self.ac(rol))

    # ─── tablo olayları
    def _tablo_tik(self, event):
        iid = self.tablo.identify_row(event.y)
        if iid != YENI_SATIR_IID:
            if self.acik_mi() and self._hedef_idx is None and not self._var.get().strip():
                self.kapat()
            return None
        kolon = _kolon_adi(self.tablo, event.x)
        self.ac(self.kolon_rol.get(kolon))
        return "break"

    def _tablo_asagi(self, _e=None):
        try:
            odak = self.tablo.focus()
            iids = veri_iidleri(self.tablo)
        except tk.TclError:
            return None
        if not iids or odak == iids[-1] or odak in ("", YENI_SATIR_IID):
            self.ac()
            return "break"
        return None

    def _tablo_tus(self, event):
        if self.kilitli() or not _yazdirilabilir(event):
            return None
        self.ac(None, event.char)
        return "break"

    def _tablo_sag_tik(self, event):
        iid = self.tablo.identify_row(event.y)
        if iid == YENI_SATIR_IID:
            self._menu_goster(event, None)
            return "break"
        idx = satir_indeksi(self.tablo, iid)
        if idx is not None and self.satir_menusu is not None:
            try:
                self.tablo.selection_set(iid)
                self.tablo.focus(iid)
            except tk.TclError:
                pass
            self._menu_goster(event, idx)
            return "break"
        return None

    def _editor_sag_tik(self, event):
        self._menu_goster(event, self._hedef_idx)
        return "break"

    def _menu_goster(self, event, idx: int | None) -> None:
        menu = tk.Menu(self.dialog, tearoff=0)
        durum = "disabled" if self.kilitli() else "normal"
        if idx is None:
            menu.add_command(label="Ürün Seç… (F10)", command=self.stok_listesi_ac, state=durum)
        else:
            if self.urun_degistir_fn is not None:
                menu.add_command(
                    label="Ürünü Değiştir…", command=lambda: self.urun_degistir_baslat(idx), state=durum
                )
            menu.add_command(label="Stok Kartını Aç", command=lambda: self.stok_karti_ac(idx))
        menu.add_command(
            label="Yeni Stok Kartı", command=self.yeni_stok_karti,
            state=durum if self._stok_yetkisi() else "disabled",
        )
        if idx is None and self.manuel_ekle_fn is not None:
            menu.add_command(
                label="Manuel Kalem Ekle…",
                command=lambda: self._manuel(self._var.get().strip()),
                state=durum,
            )
        if idx is not None and self.satir_menusu is not None:
            ekler = self.satir_menusu(idx) or []
            if ekler:
                menu.add_separator()
                for etiket, komut in ekler:
                    menu.add_command(label=etiket, command=komut)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ─── editör klavyesi
    def _tus_birakildi(self, event=None):
        if event is not None and event.keysym in (
            "Up", "Down", "Return", "KP_Enter", "Escape", "Tab", "ISO_Left_Tab", "Next", "Prior",
            "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "F10", "Left", "Right",
            "Home", "End",
        ):
            return
        metin = self._var.get().strip()
        self._iptal_debounce()
        if self._rol == "barkod":
            self._popup_kapat()
            return
        if len(metin) < MIN_ARAMA_HARF:
            self._seq += 1
            self._sonuclar = []
            self._popup_kapat()
            return
        self._after = self.dialog.after(DEBOUNCE_MS, lambda: self._arama_baslat(metin))

    def _iptal_debounce(self):
        if self._after is not None:
            try:
                self.dialog.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _arama_parametreleri(self, rol: str | None) -> dict[str, Any]:
        stokta = bool(self.sadece_stokta_ad and rol == "ad")
        depo = ""
        try:
            depo = (self.depo() or "").strip()
        except Exception:
            depo = ""
        return {"depo_ad": depo or None, "sadece_stokta": stokta}

    def _arama_baslat(self, metin: str, limit: int = SAYFA):
        self._after = None
        if self.entry is None or self._var.get().strip() != metin:
            return
        self._seq += 1
        seq = self._seq
        parametre = self._arama_parametreleri(self._rol)
        anahtar = (metin.casefold(), parametre["depo_ad"], parametre["sadece_stokta"], limit)
        kayit = self._onbellek.get(anahtar)
        if kayit is not None and time.monotonic() - kayit[0] < ONBELLEK_SN:
            self._sonuc_uygula(seq, metin, kayit[1])
            return
        alis_fn = self.alis_fiyati if self.fiyat_turu == "alis" and self.fiyat_goster() else None

        def _is():
            sonuc = urun_ara(metin, limit=limit, **parametre)
            if alis_fn is not None:
                for u in sonuc["urunler"]:
                    try:
                        u["alis_fiyati"] = alis_fn(u["kod"])
                    except Exception:
                        u["alis_fiyati"] = None
            return sonuc

        def _tamam(sonuc):
            self._onbellek[anahtar] = (time.monotonic(), sonuc)
            self._sonuc_uygula(seq, metin, sonuc)

        def _hata(exc):
            if seq == self._seq:
                self._popup_goster([], mesaj=f"Arama hatası: {exc}")

        from ui_bg import arka_planda

        try:
            arka_planda(self.dialog, _is, on_ok=_tamam, on_err=_hata)
        except RuntimeError:
            _tamam(_is())

    def _sonuc_uygula(self, seq: int, metin: str, sonuc: dict):
        # Yalnızca en son sorgunun sonucu gösterilir
        if seq != self._seq or self.entry is None or self._var.get().strip() != metin:
            return
        self._sonuc_metin = metin
        self._sonuclar = list(sonuc.get("urunler") or [])
        self._toplam = int(sonuc.get("toplam") or len(self._sonuclar))
        self._secili = 0 if self._sonuclar else -1
        self._popup_goster(self._sonuclar, mesaj=None if self._sonuclar else "Eşleşen ürün bulunamadı.")

    def onbellegi_temizle(self) -> None:
        self._onbellek.clear()

    def _asagi(self, _e=None):
        if self._popup is None:
            metin = self._var.get().strip()
            if len(metin) >= MIN_ARAMA_HARF and self._rol != "barkod":
                self._iptal_debounce()
                self._arama_baslat(metin)
            return "break"
        if self._sonuclar:
            self._secili = min(self._secili + 1, len(self._sonuclar) - 1)
            self._secim_gorsel()
        return "break"

    def _yukari(self, _e=None):
        if self._popup is not None and self._sonuclar:
            self._secili = max(self._secili - 1, 0)
            self._secim_gorsel()
        return "break"

    def _sayfa_asagi(self, _e=None):
        if self._popup is not None and self._sonuclar:
            self._secili = min(self._secili + 10, len(self._sonuclar) - 1)
            self._secim_gorsel()
        return "break"

    def _esc(self, _e=None):
        if self._popup is not None:
            self._popup_kapat()
            return "break"
        if self._var.get():
            self._var.set("")
            return "break"
        self.kapat()
        try:
            self.tablo.focus_set()
        except tk.TclError:
            pass
        return "break"

    def _rol_gec(self, adim: int):
        roller = self._roller()
        if not roller or self._rol not in roller:
            return "break"
        i = roller.index(self._rol) + adim
        self._popup_kapat()
        if 0 <= i < len(roller):
            metin = self._var.get()
            self._rol = roller[i]
            self._var.set(metin)
            self._yeniden_yerlestir(odakla=True)
            return "break"
        self.kapat()
        try:
            self.tablo.focus_set()
        except tk.TclError:
            pass
        return "break"

    def _odak_cikti(self, _e=None):
        def _kontrol():
            if self.entry is None or self._rol is None:
                return
            try:
                odak = self.dialog.focus_get()
            except (tk.TclError, KeyError):
                odak = None
            if odak is self.entry:
                return
            if odak is not None and self._popup is not None and str(odak).startswith(str(self._popup)):
                return
            self._popup_kapat()
            if not self._var.get().strip() or self._hedef_idx is not None:
                self.kapat()

        self.dialog.after(180, _kontrol)

    def _enter(self, _e=None):
        """Liste açıkken Enter yalnızca seçer (ilerleme/kayıt yok)."""
        if self._isleniyor:
            return "break"
        metin = self._var.get().strip()
        if (
            self._popup is not None
            and self._sonuclar
            and 0 <= self._secili < len(self._sonuclar)
            and self._sonuc_metin == metin
        ):
            self._sec(self._sonuclar[self._secili])
            return "break"
        if not metin:
            return "break"
        self._iptal_debounce()
        self._seq += 1  # bekleyen arama sonucu artık yazılmasın
        self._popup_kapat()
        self._isleniyor = True
        try:
            self._dogrudan_coz(metin)
        finally:
            self._isleniyor = False
        return "break"

    # ─── çözümleme
    def _dogrudan_coz(self, metin: str) -> None:
        if self._rol == "barkod":
            self._barkod(metin)
            return
        try:
            sonuc = urun_ara(metin, limit=SAYFA, **self._arama_parametreleri(self._rol))
        except Exception as exc:
            messagebox.showerror("Ürün", f"Arama yapılamadı: {exc}", parent=self.dialog)
            return
        urunler = sonuc["urunler"]
        if sonuc["barkod_tam"] and self._hedef_idx is None:
            self._barkod(metin)
            return
        if len(urunler) == 1:
            self._sec(urunler[0])
            return
        tam = [u for u in urunler if (u.get("kod") or "").casefold() == metin.casefold()]
        if len(tam) == 1:
            self._sec(tam[0])
            return
        self._seq += 1
        self._sonuc_metin = metin
        self._sonuclar = urunler
        self._toplam = sonuc["toplam"]
        self._secili = 0 if urunler else -1
        self._popup_goster(urunler, mesaj=None if urunler else "Eşleşen ürün bulunamadı.")

    def _barkod(self, metin: str) -> None:
        if self._hedef_idx is not None:
            messagebox.showinfo("Ürün", "Dolu satırda ürün değiştirmek için ürün adı ile seçin.", parent=self.dialog)
            return
        konum = self._ekleme_konumu
        if self.barkod_isle_fn is not None:
            self._var.set("")
            idx = self.barkod_isle_fn(metin, konum)
        else:
            idx = self._barkod_genel(metin, konum)
        if idx is not None and idx >= 0 and konum is not None:
            self._ekleme_konumu = konum + 1
        self._var.set("")
        self._rol = "barkod" if self._rol_gorunur("barkod") else self._rol
        self.dialog.after_idle(lambda: self._yeniden_yerlestir(odakla=True))

    def _barkod_genel(self, metin: str, konum: int | None) -> int | None:
        from database.barkod_okut_service import barkod_ile_ara, barkod_temizle

        kod = barkod_temizle(metin)
        sonuc = barkod_ile_ara(kod)
        durum = sonuc.get("durum")
        kayit = sonuc.get("kayit")
        if durum == "coklu":
            kayit = self._coklu_barkod(sonuc.get("liste") or [])
            if kayit is None:
                return None
        elif durum not in ("ok",) or not kayit:
            self._bildir(kod, sonuc.get("mesaj") or f"{kod} nolu barkod bulunamadı.")
            return None
        self.son_islem = "barkod"
        try:
            return self.urun_ekle_fn(barkod_kaydindan_degerler(kayit), konum)
        except ValueError as hata:
            messagebox.showwarning("Barkod", str(hata), parent=self.dialog)
            return None
        finally:
            self.son_islem = "secim"

    def _coklu_barkod(self, liste: list[dict]) -> dict | None:
        from fatura_barkod_ui import _coklu_sec

        return _coklu_sec(self.dialog, liste)

    def _bildir(self, barkod: str, mesaj: str) -> None:
        try:
            self.dialog.bell()
        except tk.TclError:
            pass
        if self.bildir_fn is not None:
            self.bildir_fn(barkod, mesaj)
            return
        metin = mesaj if barkod in mesaj else f"{barkod} nolu barkod: {mesaj}"
        self._durum_yaz(metin)

    def _durum_yaz(self, metin: str) -> None:
        lbl = getattr(self, "_durum_lbl", None)
        if lbl is None or not lbl.winfo_exists():
            lbl = tk.Label(
                self.tablo.master, text="", bg="#FEF2F2", fg="#B91C1C",
                font=("Segoe UI", 9, "bold"), anchor="w", padx=8,
            )
            self._durum_lbl = lbl
        lbl.configure(text=f"⚠ {metin}")
        try:
            lbl.place(in_=self.tablo, relx=0, rely=1.0, anchor="sw", relwidth=1.0)
            lbl.lift()
        except tk.TclError:
            return
        eski = getattr(self, "_durum_after", None)
        if eski:
            try:
                self.dialog.after_cancel(eski)
            except tk.TclError:
                pass
        self._durum_after = self.dialog.after(6000, lambda: lbl.place_forget() if lbl.winfo_exists() else None)

    def _sec(self, ozet: dict[str, Any]) -> None:
        self._popup_kapat()
        self._iptal_debounce()
        self._urun_uygula(urun_degerleri(ozet))

    def _urun_uygula(self, degerler: tuple, *, odak: bool = True) -> int | None:
        """Seçilen ürünü hedef satıra (dolu satır değişimi) veya giriş satırına yazar."""
        simdi = time.monotonic()
        anahtar = f"{degerler[0]}|{self._hedef_idx}|{self._ekleme_konumu}"
        if self._son_ekleme[0] == anahtar and simdi - self._son_ekleme[1] < 0.25:
            return None  # çift tık / çift Enter tekrarı
        self._son_ekleme = (anahtar, simdi)
        hedef = self._hedef_idx
        if hedef is not None:
            self.kapat()
            if self.urun_degistir_fn is not None and self.urun_degistir_fn(hedef, degerler):
                if self.miktara_git is not None:
                    self.dialog.after_idle(lambda: self.miktara_git(hedef))
            return hedef
        konum = self._ekleme_konumu
        self._var.set("")
        try:
            idx = self.urun_ekle_fn(degerler, konum)
        except ValueError as hata:
            messagebox.showwarning("Ürün", str(hata), parent=self.dialog)
            return None
        if idx is None or idx < 0:
            return None
        if konum is not None:
            self._ekleme_konumu = konum + 1
        if odak:
            self.kapat()
            if self.miktara_git is not None:
                self.dialog.after_idle(lambda: self.miktara_git(idx))
        return idx

    # ─── F10 / menü / stok kartları
    def stok_listesi_ac(self, metin: str | None = None) -> None:
        if self.kilitli():
            return
        from urun_sec_ui import UrunSecDialog

        if metin is None:
            metin = self._var.get().strip() if self.entry is not None else ""
        hedef = self._hedef_idx
        rol = self._rol
        self._popup_kapat()
        secilenler: list[tuple] = []
        dlg = UrunSecDialog(
            self.dialog,
            on_select=secilenler.append,
            ad=metin,
            depo_ad=(self.depo() or None),
            ayrintili=True,
            coklu=hedef is None,
        )
        self.dialog.wait_window(dlg)
        if not secilenler:
            if rol is not None:
                self.ac(rol, metin, hedef_idx=hedef)
            return
        if hedef is not None:
            self._hedef_idx = hedef
            self._urun_uygula(secilenler[0])
            return
        self.toplu_ekle(secilenler)

    def toplu_ekle(self, degerler_listesi: Sequence[tuple]) -> list[int]:
        """Çoklu seçim: seçim sırasıyla ilk boş satırdan (veya ekleme konumundan) ekler."""
        eklenen: list[int] = []
        konum = self._ekleme_konumu
        self.kapat()
        self.dialog._satir_toplu_ekleme = True
        try:
            for degerler in degerler_listesi:
                try:
                    idx = self.urun_ekle_fn(degerler, konum)
                except ValueError as hata:
                    messagebox.showwarning("Ürün", str(hata), parent=self.dialog)
                    continue
                if idx is not None and idx >= 0:
                    eklenen.append(idx)
                    if konum is not None:
                        konum += 1
        finally:
            self.dialog._satir_toplu_ekleme = False
        yenile = getattr(self.dialog, "_satir_toplu_yenile", None)
        if callable(yenile):
            yenile()
        if eklenen and self.miktara_git is not None:
            son = eklenen[-1] if len(eklenen) == 1 else eklenen[0]
            self.dialog.after_idle(lambda: self.miktara_git(son))
        elif not eklenen:
            self.odakla()
        return eklenen

    def araya_ekle(self, idx: int) -> None:
        """Seçili satırın önüne ürün eklemek için giriş satırını hazırla."""
        self._ekleme_konumu = max(0, int(idx))
        self.ac()
        self._durum_bilgi(f"{idx + 1}. satırın önüne eklenecek — Esc ile iptal")

    def ekleme_konumunu_sifirla(self) -> None:
        self._ekleme_konumu = None

    def _durum_bilgi(self, metin: str) -> None:
        self._durum_yaz(metin)
        try:
            self._durum_lbl.configure(bg="#EFF6FF", fg="#1E3A8A", text=f"ℹ {metin}")
        except (tk.TclError, AttributeError):
            pass

    def urun_degistir_baslat(self, idx: int) -> None:
        """Dolu satırda ürünü yalnızca açık kullanıcı işlemiyle değiştir."""
        if self.urun_degistir_fn is None or self.kilitli():
            return
        self.ac("ad" if "ad" in self._roller() else None, "", hedef_idx=idx)

    def _stok_yetkisi(self) -> bool:
        try:
            from database.access import yetki_var

            return bool(yetki_var("stok_duzenleme", "yeni_kayit"))
        except Exception:
            return True

    def yeni_stok_karti(self) -> None:
        if self.kilitli():
            return
        if not self._stok_yetkisi():
            messagebox.showwarning("Yetki", "Stok kartı oluşturma yetkiniz yok.", parent=self.dialog)
            return
        metin = self._var.get().strip() if self.entry is not None else ""
        rol = self._rol
        from hizli_stok_karti_ui import hizli_stok_karti_ac

        self._popup_kapat()
        barkod = metin if rol == "barkod" else None
        ad = metin if rol != "barkod" else None
        hizli_stok_karti_ac(self.dialog, barkod=barkod, urun_adi=ad)
        self.onbellegi_temizle()

    def stoktan_ekle(self, stok, fiyat_hint: Any = None) -> int | None:
        """Hızlı stok kartından «faturaya ekle» — çalışılan giriş satırına yazar."""
        ozet = stok_ozeti(stok)
        kaynak = "Stok Kartı"
        if fiyat_hint not in (None, ""):
            try:
                ozet["satis_fiyati"] = ondalik(fiyat_hint)
                kaynak = HIZLI_STOK_KAYNAGI
            except ValueError:
                pass
        self.onbellegi_temizle()
        return self._urun_uygula(urun_degerleri(ozet, kaynak=kaynak))

    def stok_karti_ac(self, idx: int) -> None:
        satirlar = getattr(self.dialog, "satirlar", None) or []
        if not (0 <= idx < len(satirlar)):
            return
        kod = (satirlar[idx].get("urun_kodu") or "").strip()
        if not kod or satirlar[idx].get("is_manual_item") or satirlar[idx].get("manuel"):
            messagebox.showinfo("Stok", "Bu satır bir stok kartına bağlı değil.", parent=self.dialog)
            return
        try:
            from database.stok_service import StokService
            from stok_ui import StokKartiDialog

            stok = next((s for s in StokService.stoklari_ara(kod) if (s.stok_kodu or "").strip() == kod), None)
            if stok is None:
                messagebox.showinfo("Stok", "Stok kartı bulunamadı.", parent=self.dialog)
                return
            StokKartiDialog(self.dialog, stok)
        except Exception as exc:
            messagebox.showerror("Stok", str(exc), parent=self.dialog)

    def _manuel(self, metin: str) -> None:
        if self.manuel_ekle_fn is None:
            return
        konum = self._ekleme_konumu
        self._popup_kapat()
        self.kapat()
        idx = self.manuel_ekle_fn(metin, konum)
        if idx is not None and idx >= 0:
            if konum is not None:
                self._ekleme_konumu = konum + 1
            if self.miktara_git is not None:
                self.dialog.after_idle(lambda: self.miktara_git(idx))

    # ─── açılır liste
    def _popup_kapat(self) -> None:
        pop, self._popup = self._popup, None
        self._pop_tree = None
        self._pop_durum = None
        if pop is not None:
            try:
                pop.destroy()
            except tk.TclError:
                pass

    def _pop_kolonlar(self) -> list[tuple[str, str, int, str]]:
        kol = [("kod", "Ürün Kodu", 110, "w"), ("ad", "Ürün Adı", 300, "w"), ("birim", "Birim", 60, "center")]
        if self.stok_goster():
            kol.append(("stok", "Stok", 70, "e"))
        if self.fiyat_goster() and self.fiyat_turu == "satis":
            kol.append(("fiyat", "Satış Fiyatı", 90, "e"))
        elif self.fiyat_goster() and self.fiyat_turu == "alis":
            kol.append(("fiyat", "Son Alış", 90, "e"))
        return kol

    def _popup_goster(self, urunler: list[dict[str, Any]], *, mesaj: str | None = None) -> None:
        if self.entry is None:
            return
        if self._popup is None:
            pop = tk.Toplevel(self.dialog)
            pop.withdraw()
            pop.overrideredirect(True)
            try:
                pop.attributes("-topmost", True)
            except tk.TclError:
                pass
            frm = tk.Frame(pop, bg="#0B2A4A", bd=1)
            frm.pack(fill="both", expand=True)
            kolonlar = self._pop_kolonlar()
            tree = ttk.Treeview(frm, columns=[k[0] for k in kolonlar], show="headings", height=10, selectmode="browse")
            for cid, baslik, gen, anchor in kolonlar:
                tree.heading(cid, text=baslik)
                tree.column(cid, width=gen, anchor=anchor, stretch=(cid == "ad"))
            sy = ttk.Scrollbar(frm, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=sy.set)
            tree.grid(row=0, column=0, sticky="nsew")
            sy.grid(row=0, column=1, sticky="ns")
            frm.rowconfigure(0, weight=1)
            frm.columnconfigure(0, weight=1)
            alt = tk.Frame(frm, bg="#F1F5F9")
            alt.grid(row=1, column=0, columnspan=2, sticky="ew")
            durum = tk.Label(alt, text="", bg="#F1F5F9", fg="#334155", font=("Segoe UI", 8), anchor="w")
            durum.pack(side="left", fill="x", expand=True, padx=4)
            self._pop_daha = tk.Button(
                alt, text="Daha fazla", relief="flat", bg="#E2E8F0", font=("Segoe UI", 8),
                command=self._daha_fazla,
            )
            self._pop_manuel = tk.Button(
                alt, text="Manuel kalem", relief="flat", bg="#EDE9FE", font=("Segoe UI", 8),
                command=lambda: self._manuel(self._var.get().strip()),
            )
            self._pop_yeni = tk.Button(
                alt, text="Yeni Stok Kartı", relief="flat", bg="#DCFCE7", font=("Segoe UI", 8),
                command=self.yeni_stok_karti,
            )
            tree.tag_configure("cift", background="#F8FAFC")
            tree.tag_configure("stok_yok", foreground="#B91C1C")
            tree.bind("<Double-1>", lambda _e: self._pop_tik_sec())
            tree.bind("<ButtonRelease-1>", self._pop_tik)
            self._popup, self._pop_tree, self._pop_durum = pop, tree, durum
        tree = self._pop_tree
        assert tree is not None
        tree.delete(*tree.get_children())
        kolon_ids = [k[0] for k in self._pop_kolonlar()]
        for i, u in enumerate(urunler):
            fiyat = u.get("alis_fiyati") if self.fiyat_turu == "alis" else u.get("satis_fiyati")
            satir = {
                "kod": u.get("kod") or "",
                "ad": u.get("ad") or "",
                "birim": u.get("birim") or "",
                "stok": sayi_metni(u.get("stok") or 0),
                "fiyat": "" if fiyat in (None, "") else f"{Decimal(str(fiyat)):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            }
            etiket = ["cift"] if i % 2 else []
            if self.stok_goster() and Decimal(str(u.get("stok") or 0)) <= 0:
                etiket.append("stok_yok")
            tree.insert("", "end", iid=str(i), values=[satir[k] for k in kolon_ids], tags=tuple(etiket))
        bilgi = "↑↓ seç · Enter ekle · Esc kapat · F10 stok listesi"
        if mesaj:
            bilgi = mesaj
        elif self._toplam > len(urunler):
            bilgi = f"{len(urunler)} / {self._toplam} sonuç · " + bilgi
        self._pop_durum.configure(text=bilgi)
        for b in (self._pop_daha, self._pop_manuel, self._pop_yeni):
            b.pack_forget()
        if self._toplam > len(urunler) and len(urunler) < AZAMI_SONUC:
            self._pop_daha.pack(side="right", padx=2, pady=1)
        if not urunler:
            if self._stok_yetkisi():
                self._pop_yeni.pack(side="right", padx=2, pady=1)
            if self.manuel_ekle_fn is not None and self._hedef_idx is None:
                self._pop_manuel.pack(side="right", padx=2, pady=1)
        self._secim_gorsel()
        self._popup_konum()
        try:
            self._popup.deiconify()
            self._popup.lift()
        except tk.TclError:
            pass

    def _popup_konum(self) -> None:
        if self._popup is None or self.entry is None:
            return
        try:
            self.entry.update_idletasks()
            x = self.entry.winfo_rootx()
            y = self.entry.winfo_rooty() + self.entry.winfo_height() + 1
            w = max(self.entry.winfo_width(), 640)
            h = 250
            ekran_w = self.entry.winfo_screenwidth()
            ekran_h = self.entry.winfo_screenheight()
            if x + w > ekran_w - 8:
                x = max(8, ekran_w - w - 8)
            if y + h > ekran_h - 40:
                y = max(8, self.entry.winfo_rooty() - h - 2)
            self._popup.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError:
            pass

    def _secim_gorsel(self) -> None:
        if self._pop_tree is None or self._secili < 0:
            return
        iid = str(self._secili)
        try:
            self._pop_tree.selection_set(iid)
            self._pop_tree.see(iid)
        except tk.TclError:
            pass

    def _pop_tik(self, event):
        if self._pop_tree is None:
            return
        row = self._pop_tree.identify_row(event.y)
        if row:
            self._secili = int(row)
        if self.entry is not None:
            self.entry.focus_set()

    def _pop_tik_sec(self):
        if 0 <= self._secili < len(self._sonuclar):
            self._sec(self._sonuclar[self._secili])

    def _daha_fazla(self):
        metin = self._var.get().strip()
        if metin:
            self._arama_baslat(metin, limit=AZAMI_SONUC)
        if self.entry is not None:
            self.entry.focus_set()
