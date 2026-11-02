"""Belge (fatura/sipariş/teklif/irsaliye) pencereleri — ekrana sığdırma ve popup ortalama.

Yalnızca yerleşim; hesaplama / iş mantığı yok.
Windows iş alanı (görev çubuğu hariç) dikkate alınır.
"""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Any


def calisma_alani(pencere: tk.Misc | None = None) -> tuple[int, int, int, int]:
    """(x, y, genislik, yukseklik) — görev çubuğu dışı kullanılabilir alan."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            rect = RECT()
            SPI_GETWORKAREA = 0x0030
            if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
                return (
                    int(rect.left),
                    int(rect.top),
                    int(rect.right - rect.left),
                    int(rect.bottom - rect.top),
                )
        except Exception:
            pass
    try:
        root = pencere or tk._default_root  # type: ignore[attr-defined]
        if root is not None:
            return (0, 0, int(root.winfo_screenwidth()), int(root.winfo_screenheight()))
    except Exception:
        pass
    return (0, 0, 1280, 720)


def pencere_cerceve_payi(win: tk.Misc) -> tuple[int, int]:
    """Dış çerçeve (başlık + kenar) payı — (yatay_px, dikey_px).

    Tk ``geometry`` WxH istemci alanıdır; iş alanına sığdırmak için bu pay
    yükseklik/genişlikten düşülmelidir. Sabit görev çubuğu tahmini kullanılmaz.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            hwnd = int(win.winfo_id())
            # Tk Toplevel: istemci HWND; üst çerçeve GetParent ile
            parent = ctypes.windll.user32.GetParent(hwnd)
            if parent:
                hwnd = parent
            outer, client = RECT(), RECT()
            if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(outer)) and ctypes.windll.user32.GetClientRect(
                hwnd, ctypes.byref(client)
            ):
                ow = int(outer.right - outer.left)
                oh = int(outer.bottom - outer.top)
                cw = int(client.right - client.left)
                ch = int(client.bottom - client.top)
                if ow > cw >= 0 and oh > ch >= 0:
                    return (max(0, ow - cw), max(0, oh - ch))
        except Exception:
            pass
    try:
        win.update_idletasks()
        # Kök y ile istemci y farkı ≈ üst başlık; altına simetrik kenar ekle
        ust = max(0, int(win.winfo_rooty()) - int(win.winfo_y()))
        if ust > 0:
            return (16, ust + 8)
    except Exception:
        pass
    return (16, 40)


def is_alanina_sigdir(
    win: tk.Toplevel,
    *,
    maximize: bool = False,
) -> dict[str, Any]:
    """Pencereyi SPI iş alanına sığdırır; alt kenar görev çubuğunun altında kalmaz.

    ``geometry`` istemci boyutu olduğundan çerçeve payı düşülür.
    maximize=True olsa bile taşma varsa normal + iş alanı geometrisi kullanılır.
    """
    ax, ay, aw, ah = calisma_alani(win)
    try:
        win.update_idletasks()
    except tk.TclError:
        pass
    cx, cy = pencere_cerceve_payi(win)
    # İstemci, dış çerçeve ile birlikte iş alanı içinde kalsın
    gw = max(400, aw - max(cx, 2))
    gh = max(320, ah - max(cy, 2))
    try:
        if str(win.state()) == "zoomed":
            if not maximize:
                win.state("normal")
    except tk.TclError:
        pass
    zoomed = False
    if maximize:
        try:
            win.geometry(f"{gw}x{gh}+{ax}+{ay}")
            win.update_idletasks()
            win.state("zoomed")
            zoomed = True
            win.update_idletasks()
            # Zoom sonrası gerçekten taştı mı? (transient bazen tam ekrana gider)
            ry = int(win.winfo_rooty())
            rh = int(win.winfo_height())
            if ry + rh > ay + ah - 2 or rh > gh + 8:
                win.state("normal")
                win.geometry(f"{gw}x{gh}+{ax}+{ay}")
                zoomed = False
        except tk.TclError:
            try:
                win.geometry(f"{gw}x{gh}+{ax}+{ay}")
            except tk.TclError:
                pass
    else:
        try:
            win.geometry(f"{gw}x{gh}+{ax}+{ay}")
        except tk.TclError:
            pass
    return {
        "work_x": ax,
        "work_y": ay,
        "work_w": aw,
        "work_h": ah,
        "client_w": gw,
        "client_h": gh,
        "chrome_x": cx,
        "chrome_y": cy,
        "zoomed": zoomed,
    }


def _transient_bagli_mi(win: tk.Misc) -> bool:
    """True = Windows büyüt/küçült kromunu gizleyen transient bağ var.

    Tk ``wm transient`` boşken ``''`` döner; köke bağlanınca ``'.'`` veya
    ``<window object: '.'>`` gelebilir — ikisi de gerçek bağdır (önceden ``'.'``
    yanlışlıkla «bağ yok» sayılıyordu ve iconify başarısız oluyordu).
    """
    try:
        tr = win.wm_transient()
    except tk.TclError:
        return False
    if tr is None:
        return False
    s = str(tr).strip()
    if not s:
        return False
    # Boş string dışı her transient (kök '.' dahil) Windows'ta iconify'yi engeller
    return True


def pencere_os_krom_ac(win: tk.Misc, *, minsize_makul: bool = True) -> None:
    """Windows başlık denetimlerini aç: simge durumuna indir / büyüt-geri al / kapat.

    ``transient(parent)`` Windows'ta büyüt/küçült düğmelerini gizler; bu yardımcı
    transient bağını kaldırır, ``resizable(True,True)`` ve makul minsize uygular.
    ``grab_set`` (modal) korunabilir — yalnız boyutlandırma kromunu etkiler.
    Tekrar güvenli ve ucuz: transient yoksa ve bayrak setse no-op.
    Küçük yardımcı popup'lara uygulamayın.
    """
    zaten = bool(getattr(win, "_os_krom_acik", False))
    bagli = _transient_bagli_mi(win)
    if zaten and not bagli and not minsize_makul:
        # belge_penceresini_hazirla sonrası idle/after tekrarları: iş yok
        return
    if bagli:
        try:
            win.wm_transient("")
        except tk.TclError:
            try:
                win.transient(None)  # type: ignore[arg-type]
            except Exception:
                pass
        # Bazı Tk sürümlerinde ilk çağrı bağ bırakmaz; tekrar dene
        if _transient_bagli_mi(win):
            try:
                win.wm_transient("")
            except tk.TclError:
                pass
    try:
        win.resizable(True, True)
    except tk.TclError:
        pass
    if minsize_makul and not zaten:
        try:
            _x, _y, aw, ah = calisma_alani(win)
            min_w = min(800, max(560, aw // 2))
            min_h = min(500, max(360, ah // 2))
            win.minsize(min_w, min_h)
        except Exception:
            try:
                win.minsize(640, 420)
            except tk.TclError:
                pass
    try:
        setattr(win, "_os_krom_acik", True)
    except Exception:
        pass
    if not getattr(win, "_os_krom_map_bagli", False):
        try:
            win.bind("<Unmap>", _krom_unmap, add="+")
            win.bind("<Map>", _krom_map, add="+")
            setattr(win, "_os_krom_map_bagli", True)
        except tk.TclError:
            pass


def _krom_unmap(event) -> None:
    """Simge durumuna inerken grab'i bırak — modal kilit uygulamayı dondurmasın."""
    win = event.widget
    # Bind yalnızca Toplevel'e konur; yine de çocuk Unmap/yanlış hedef gelirse yut.
    if not isinstance(win, (tk.Tk, tk.Toplevel)):
        return
    try:
        if str(win.state()) != "iconic":
            return
    except (tk.TclError, AttributeError):
        return
    try:
        if win.grab_current() == win:
            setattr(win, "_os_krom_grab_bekliyor", True)
            win.grab_release()
    except tk.TclError:
        pass


def _krom_map(event) -> None:
    """Geri gelince daha önce bırakılan grab'i geri ver."""
    win = event.widget
    if not isinstance(win, (tk.Tk, tk.Toplevel)):
        return
    if not getattr(win, "_os_krom_grab_bekliyor", False):
        return
    try:
        if str(win.state()) == "iconic":
            return
    except (tk.TclError, AttributeError):
        return
    try:
        win.grab_set()
        setattr(win, "_os_krom_grab_bekliyor", False)
    except tk.TclError:
        pass


def pencere_asagi(win: tk.Misc) -> None:
    """Görev çubuğuna indir; kayıt silmez / kapatmaz. Grab kilidini bırakır."""
    try:
        if win.grab_current() == win:
            setattr(win, "_os_krom_grab_bekliyor", True)
            win.grab_release()
    except tk.TclError:
        pass
    if _transient_bagli_mi(win):
        pencere_os_krom_ac(win, minsize_makul=False)
    try:
        win.iconify()
    except tk.TclError:
        try:
            win.wm_transient("")
            win.iconify()
        except tk.TclError:
            pass


def pencere_buyut_toggle(
    win: tk.Misc,
    *,
    onceki_attr: str = "_pencere_onceki_geometry",
    btn: tk.Misc | None = None,
) -> str:
    """``zoomed`` ↔ önceki boyut; düğme metni □ / ❐ güncellenir."""
    try:
        durum = str(win.state() or "")
    except tk.TclError:
        durum = ""
    try:
        if durum == "zoomed":
            win.state("normal")
            geo = getattr(win, onceki_attr, None)
            if geo:
                try:
                    win.geometry(geo)
                except tk.TclError:
                    pass
            if btn is not None:
                try:
                    btn.configure(text="□")
                except tk.TclError:
                    pass
        else:
            try:
                setattr(win, onceki_attr, win.geometry())
            except tk.TclError:
                setattr(win, onceki_attr, None)
            win.state("zoomed")
            if btn is not None:
                try:
                    btn.configure(text="❐")
                except tk.TclError:
                    pass
    except tk.TclError:
        pass
    return "break"


def belge_penceresini_hazirla(
    win: tk.Toplevel,
    *,
    min_genislik: int = 900,
    min_yukseklik: int = 520,
    varsayilan_genislik: int = 1200,
    varsayilan_yukseklik: int = 720,
    maximize: bool = True,
    os_krom: bool = True,
) -> dict[str, Any]:
    """Belge kartını iş alanına oturtur; görev çubuğunun altında kalmaz.

    - minsize, ekranın %85'ini aşmaz (küçük çözünürlük / yüksek DPI)
    - maximize=True → state('zoomed'); başarısızsa iş alanına geometry
    - os_krom=True → transient kaldırılır (Windows — □ ✕); idle sonrası da
      yenilenir (çağıran ``transient(parent)`` sonra yazsa bile)
    """
    try:
        zaten_buyuk = maximize and str(win.state()) == "zoomed"
    except tk.TclError:
        zaten_buyuk = False
    if not zaten_buyuk:
        try:
            win.update_idletasks()
        except tk.TclError:
            pass

    x, y, aw, ah = calisma_alani(win)
    # Min boyutları iş alanına göre sınırla (bileşenler bozulmasın ama sığsın)
    min_w = max(720, min(int(min_genislik), max(720, aw - 24)))
    min_h = max(480, min(int(min_yukseklik), max(480, ah - 24)))
    try:
        win.minsize(min_w, min_h)
    except tk.TclError:
        pass
    try:
        win.resizable(True, True)
    except tk.TclError:
        pass

    gw = min(max(int(varsayilan_genislik), min_w), aw)
    gh = min(max(int(varsayilan_yukseklik), min_h), ah)
    gx = x + max(0, (aw - gw) // 2)
    gy = y + max(0, (ah - gh) // 2)

    zoomed = False
    if zaten_buyuk:
        # Tekrar küçültüp büyütmek pencereyi gözle görülür şekilde yeniden çizer
        zoomed = True
    elif maximize:
        try:
            # Önce iş alanına yerleştir, sonra maximize (Windows zoomed = work area)
            win.geometry(f"{gw}x{gh}+{gx}+{gy}")
            win.update_idletasks()
            win.state("zoomed")
            zoomed = True
        except tk.TclError:
            try:
                win.geometry(f"{aw}x{ah}+{x}+{y}")
            except tk.TclError:
                pass
    else:
        try:
            win.geometry(f"{gw}x{gh}+{gx}+{gy}")
        except tk.TclError:
            pass

    if os_krom:
        # Hemen uygula; sonradan transient yazılırsa tek ucuz idle+after ile temizle
        pencere_os_krom_ac(win, minsize_makul=False)

        def _krom_yenile(w=win):
            if not w.winfo_exists():
                return
            if _transient_bagli_mi(w):
                pencere_os_krom_ac(w, minsize_makul=False)

        try:
            win.after_idle(_krom_yenile)
            win.after(80, _krom_yenile)
        except tk.TclError:
            pass

    return {
        "work_x": x,
        "work_y": y,
        "work_w": aw,
        "work_h": ah,
        "min_w": min_w,
        "min_h": min_h,
        "zoomed": zoomed,
    }


def evrak_penceresi_boyutlandir(
    win: tk.Toplevel,
    *,
    genislik: int,
    yukseklik: int,
    min_genislik: int = 560,
    min_yukseklik: int = 360,
) -> None:
    """Küçük evrak penceresi: büyütülebilir, iş alanına sığar, ortalanır."""
    x, y, aw, ah = calisma_alani(win)
    g = max(320, min(int(genislik), aw - 20))
    h = max(240, min(int(yukseklik), ah - 40))
    try:
        win.resizable(True, True)
        win.minsize(min(int(min_genislik), g), min(int(min_yukseklik), h))
        win.geometry(f"{g}x{h}+{x + (aw - g) // 2}+{y + max(0, (ah - h) // 2)}")
    except tk.TclError:
        pass


def kaydirilabilir_govde(win: tk.Misc, *, bg: str | None = None) -> tk.Frame:
    """Pencereye dikey kaydırmalı gövde ekler; içerik sığmazsa kaydırma çubuğu görünür."""
    dis = tk.Frame(win, bg=bg) if bg else tk.Frame(win)
    dis.pack(side="top", fill="both", expand=True)
    kanvas = tk.Canvas(dis, highlightthickness=0, bd=0, bg=bg) if bg else tk.Canvas(dis, highlightthickness=0, bd=0)
    dikey = tk.Scrollbar(dis, orient="vertical", command=kanvas.yview)
    kanvas.configure(yscrollcommand=dikey.set)
    kanvas.pack(side="left", fill="both", expand=True)
    ic = tk.Frame(kanvas, bg=bg) if bg else tk.Frame(kanvas)
    ic_id = kanvas.create_window((0, 0), window=ic, anchor="nw")

    def _guncelle(_e=None):
        kanvas.configure(scrollregion=kanvas.bbox("all"))
        gerekli = ic.winfo_reqheight() > kanvas.winfo_height() > 1
        if gerekli and not dikey.winfo_ismapped():
            dikey.pack(side="right", fill="y", before=kanvas)
        elif not gerekli and dikey.winfo_ismapped():
            dikey.pack_forget()
            kanvas.yview_moveto(0)

    def _kanvas_boyut(event):
        kanvas.itemconfigure(ic_id, width=max(event.width, ic.winfo_reqwidth()))
        _guncelle()

    def _tekerlek(event):
        if dikey.winfo_ismapped():
            kanvas.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")

    ic.bind("<Configure>", _guncelle)
    kanvas.bind("<Configure>", _kanvas_boyut)
    kanvas.bind("<MouseWheel>", _tekerlek)
    ic.bind("<MouseWheel>", _tekerlek)
    return ic


def popup_ortala(
    popup: tk.Toplevel,
    parent: tk.Misc | None = None,
    *,
    genislik: int | None = None,
    yukseklik: int | None = None,
) -> None:
    """Popup'ı ana belge penceresine (veya ekrana) göre ortalar; iş alanı dışına taşmaz."""
    try:
        popup.update_idletasks()
    except tk.TclError:
        return

    w = genislik or popup.winfo_width()
    h = yukseklik or popup.winfo_height()
    if w < 40:
        w = max(popup.winfo_reqwidth(), genislik or 400)
    if h < 40:
        h = max(popup.winfo_reqheight(), yukseklik or 280)

    ax, ay, aw, ah = calisma_alani(popup)
    # Parent varsa onun ortasına koy
    px = py = pw = ph = None
    hedef = parent
    if hedef is None:
        try:
            hedef = popup.master
        except Exception:
            hedef = None
    if hedef is not None:
        try:
            # Üst Toplevel'e çık
            ust = hedef.winfo_toplevel()
            ust.update_idletasks()
            px, py = int(ust.winfo_rootx()), int(ust.winfo_rooty())
            pw, ph = int(ust.winfo_width()), int(ust.winfo_height())
        except tk.TclError:
            px = py = pw = ph = None

    if px is not None and pw and ph and pw > 50 and ph > 50:
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
    else:
        x = ax + (aw - w) // 2
        y = ay + (ah - h) // 2

    # İş alanı içine sıkıştır
    x = max(ax, min(x, ax + aw - w))
    y = max(ay, min(y, ay + ah - h))
    try:
        popup.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
        popup.lift()
    except tk.TclError:
        pass


def sticky_footer_layout(
    win: tk.Toplevel,
    *,
    ust: tk.Misc | None = None,
    orta: tk.Misc | None = None,
    alt: tk.Misc | None = None,
) -> None:
    """Üst sabit / orta expand / alt sabit — yalnızca pack (grid ile karıştırma).

    Aynı Toplevel'de pack+grid karışımı Tk'te boş ekrana yol açar.
    Sıra: önce alt (bottom), sonra üst (top), sonra orta (expand).
    """

    def _unmanage(w):
        if w is None:
            return
        try:
            mgr = w.winfo_manager()
            if mgr == "pack":
                w.pack_forget()
            elif mgr == "place":
                w.place_forget()
            elif mgr == "grid":
                w.grid_forget()
        except tk.TclError:
            pass

    _unmanage(ust)
    _unmanage(orta)
    _unmanage(alt)

    try:
        if alt is not None:
            alt.pack(side="bottom", fill="x")
        if ust is not None:
            ust.pack(side="top", fill="x")
        if orta is not None:
            orta.pack(side="top", fill="both", expand=True)
    except tk.TclError:
        pass


def sarmali_yerlestir(
    kap: tk.Frame,
    ogeler: list[tk.Misc],
    *,
    padx: int = 3,
    pady: int = 4,
    genisleyen: tuple = (),
    hepsi_genislesin: bool = False,
    yasla: str = "w",
) -> None:
    """Öğeleri ``kap`` genişliğine sığdığı kadar yan yana dizer; sığmayanı alt satıra geçirir.

    Dar ekran / yüksek ölçekte düğme ve etiketler kesilmez (yazı küçültülmez).
    ``kap`` genişliği üst yerleşimden gelmeli (fill="x" / sticky="ew"); öğeler ``kap``'ın çocuğu olmalı.
    """
    from tkinter import ttk

    if isinstance(kap, ttk.Frame):
        def _satir_yap():
            return ttk.Frame(kap)
    else:
        bg = kap.cget("bg")

        def _satir_yap():
            return tk.Frame(kap, bg=bg)
    satirlar: list[tk.Misc] = []
    son: dict[str, Any] = {"duzen": None}

    def _uygula(duzen: list[list[tk.Misc]]) -> None:
        imza = [len(s) for s in duzen]
        if imza == son["duzen"]:
            return
        son["duzen"] = imza
        for o in ogeler:
            o.pack_forget()
        for s in satirlar:
            s.pack_forget()
        while len(satirlar) < len(duzen):
            satirlar.append(_satir_yap())
        for i, (satir, grup) in enumerate(zip(satirlar, duzen)):
            dolu = hepsi_genislesin or any(o in genisleyen for o in grup)
            satir.pack(anchor=yasla, fill="x" if dolu else "none", pady=(0 if i == 0 else pady, 0))
            for o in grup:
                acik = hepsi_genislesin or o in genisleyen
                o.pack(in_=satir, side="left", padx=padx, expand=acik, fill="x" if acik else "none")
                o.lift(satir)

    def _yerlestir(_e=None) -> None:
        try:
            gen = kap.winfo_width()
            if gen <= 1:
                return
            duzen: list[list[tk.Misc]] = [[]]
            x = 0
            for o in ogeler:
                rw = o.winfo_reqwidth() + 2 * padx
                if duzen[-1] and x + rw > gen:
                    duzen.append([])
                    x = 0
                duzen[-1].append(o)
                x += rw
            _uygula(duzen)
        except tk.TclError:
            pass

    _uygula([list(ogeler)])
    kap.bind("<Configure>", _yerlestir, add="+")
