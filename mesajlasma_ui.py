"""Ortak mesajlaşma bileşeni — rozetli Mesajlar düğmesi + pencere + arka plan yoklama.

Tek MesajlasmaYoneticisi tüm açık ekranlarda paylaşılır; her pencere ayrı sorgu döngüsü açmaz.
Bildirimler focus/grab kullanmaz (barkod / fatura girişini bozmaz).
"""

from __future__ import annotations

import json
import threading
import tkinter as tk
import uuid
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable

from database.mesajlasma_service import MesajlasmaError, MesajlasmaService
from database.session_manager import oturum

LACIVERT = "#0B2A4A"
SARI = "#F2C94C"
BEYAZ = "#FFFFFF"
ACIK = "#F4F6F8"
GELEN_BG = "#E8F0FE"
GIDEN_BG = "#E6F4EA"
ROZET_KIRMIZI = "#D93025"
PASIF = "#5F6B7A"
POLL_MS = 3500


def _ses_tercih_yolu() -> Path:
    uid = getattr(oturum, "user_id", None) or 0
    d = Path.home() / ".cin_muhasebe"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"mesaj_sesi_user_{uid}.json"


def ses_tercihi_oku(varsayilan: bool = True) -> bool:
    try:
        ham = json.loads(_ses_tercih_yolu().read_text(encoding="utf-8"))
        if isinstance(ham, dict) and "ses" in ham:
            return bool(ham["ses"])
    except (OSError, ValueError, TypeError):
        pass
    return varsayilan


def ses_tercihi_yaz(acik: bool) -> None:
    try:
        _ses_tercih_yolu().write_text(
            json.dumps({"ses": bool(acik)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _tarih_goster(dt) -> str:
    if not isinstance(dt, datetime):
        return ""
    return dt.strftime("%d.%m.%Y %H:%M")


def _toast(root: tk.Misc, metin: str, sure_ms: int = 4500) -> None:
    """Focus çalmayan uygulama içi bildirim."""
    try:
        ust = root.winfo_toplevel()
        # Odaklanan widget'ı koru
        onceki = ust.focus_get()
        pen = tk.Toplevel(ust)
        pen.overrideredirect(True)
        try:
            pen.attributes("-topmost", True)
        except tk.TclError:
            pass
        # Focus alma
        try:
            pen.attributes("-disabled", False)
        except tk.TclError:
            pass
        tk.Label(
            pen,
            text=metin,
            font=("Segoe UI", 9, "bold"),
            bg="#FFF4CE",
            fg=LACIVERT,
            bd=1,
            relief="solid",
            padx=10,
            pady=6,
            wraplength=360,
            justify="left",
        ).pack()
        pen.update_idletasks()
        x = ust.winfo_rootx() + max(10, ust.winfo_width() - pen.winfo_reqwidth() - 24)
        y = ust.winfo_rooty() + 48
        pen.geometry(f"+{x}+{y}")
        pen.bind("<Button-1>", lambda _e: pen.destroy())
        # Odağı geri ver — barkod/fatura kesilmesin
        if onceki is not None:
            try:
                onceki.focus_set()
            except tk.TclError:
                pass
        pen.after(sure_ms, lambda: pen.winfo_exists() and pen.destroy())
    except tk.TclError:
        pass


def _bip():
    try:
        import sys

        if sys.platform.startswith("win"):
            import winsound

            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        else:
            print("\a", end="", flush=True)
    except Exception:
        pass


class MesajlasmaYoneticisi:
    """Uygulama başına tek örnek — poll + rozet aboneleri + pencere."""

    _ornek: MesajlasmaYoneticisi | None = None

    def __init__(self, root: tk.Misc):
        self.root = root
        self._rozet_aboneleri: list[Callable[[int], None]] = []
        self._after_id = None
        self._poll_lock = threading.Lock()
        self._poll_calisiyor = False
        self._son_max_id = 0
        self._okunmamis = 0
        self._pencere: MesajlasmaPenceresi | None = None
        self._durduruldu = False
        self._ilk_poll = True
        oturum.on_user_changed(self._kullanici_degisti)

    @classmethod
    def ornek(cls, root: tk.Misc | None = None) -> MesajlasmaYoneticisi:
        if cls._ornek is None:
            if root is None:
                raise RuntimeError("MesajlasmaYoneticisi ilk kez root ile başlatılmalı.")
            cls._ornek = cls(root)
            cls._ornek.baslat()
        return cls._ornek

    @classmethod
    def varsa(cls) -> MesajlasmaYoneticisi | None:
        return cls._ornek

    def baslat(self) -> None:
        self._durduruldu = False
        self._planla_poll(400)

    def durdur(self) -> None:
        self._durduruldu = True
        if self._after_id:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _kullanici_degisti(self, _eski=None, _yeni=None):
        self._son_max_id = 0
        self._ilk_poll = True
        self._planla_poll(200)

    def abone_rozet(self, callback: Callable[[int], None]) -> None:
        if callback not in self._rozet_aboneleri:
            self._rozet_aboneleri.append(callback)
        try:
            callback(self._okunmamis)
        except Exception:
            pass

    def abonelikten_cik(self, callback: Callable[[int], None]) -> None:
        try:
            self._rozet_aboneleri.remove(callback)
        except ValueError:
            pass

    def okunmamis(self) -> int:
        return int(self._okunmamis)

    def _planla_poll(self, gecikme: int | None = None):
        if self._durduruldu:
            return
        if self._after_id:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
        self._after_id = self.root.after(gecikme or POLL_MS, self._poll_baslat)

    def _poll_baslat(self):
        self._after_id = None
        if self._durduruldu:
            return
        if not self._poll_lock.acquire(blocking=False):
            self._planla_poll()
            return
        if self._poll_calisiyor:
            self._poll_lock.release()
            self._planla_poll()
            return
        self._poll_calisiyor = True
        self._poll_lock.release()
        son = self._son_max_id

        def isci():
            try:
                veri = MesajlasmaService.poll(son)
            except Exception:
                veri = {"okunmamis": self._okunmamis, "yeni": [], "max_mesaj_id": son}
            try:
                self.root.after(0, lambda: self._poll_sonuc(veri))
            except Exception:
                self._poll_calisiyor = False

        threading.Thread(target=isci, name="mesaj-poll", daemon=True).start()

    def _poll_sonuc(self, veri: dict):
        self._poll_calisiyor = False
        if self._durduruldu:
            return
        okunmamis = int(veri.get("okunmamis") or 0)
        max_id = int(veri.get("max_mesaj_id") or 0)
        yeni = list(veri.get("yeni") or [])
        onceki = self._okunmamis
        self._okunmamis = okunmamis
        if max_id > self._son_max_id:
            self._son_max_id = max_id
        for cb in list(self._rozet_aboneleri):
            try:
                cb(okunmamis)
            except Exception:
                pass
        # İlk poll'da eski mesajlar için toast gösterme
        if not self._ilk_poll and yeni:
            pencere_acik = (
                self._pencere is not None
                and getattr(self._pencere, "winfo_exists", lambda: False)()
            )
            if not pencere_acik:
                son = yeni[-1]
                kim = son.get("gonderen_adi") or son.get("gonderen_kullanici") or "Birisi"
                ozet = (son.get("icerik") or "")[:80]
                _toast(self.root, f"Yeni mesaj — {kim}: {ozet}")
                if ses_tercihi_oku(True):
                    _bip()
            elif self._pencere is not None:
                try:
                    self._pencere.poll_yenile(yeni)
                except Exception:
                    pass
        self._ilk_poll = False
        if okunmamis != onceki and self._pencere is not None:
            try:
                self._pencere.listeyi_yenile()
            except Exception:
                pass
        self._planla_poll()

    def pencere_ac(self, parent: tk.Misc | None = None, konusma_id: int | None = None):
        parent = parent or self.root
        if self._pencere is not None:
            try:
                if self._pencere.winfo_exists():
                    self._pencere.lift()
                    self._pencere.focus_force()
                    if konusma_id:
                        self._pencere.konusma_sec(int(konusma_id))
                    return
            except tk.TclError:
                self._pencere = None
        self._pencere = MesajlasmaPenceresi(parent, yoneticisi=self, konusma_id=konusma_id)

    def rozet_yenile_hemen(self):
        def isci():
            try:
                n = MesajlasmaService.okunmamis_toplam()
            except Exception:
                n = self._okunmamis
            try:
                self.root.after(0, lambda: self._rozet_hemen(n))
            except Exception:
                pass

        threading.Thread(target=isci, daemon=True).start()

    def _rozet_hemen(self, n: int):
        self._okunmamis = int(n)
        for cb in list(self._rozet_aboneleri):
            try:
                cb(self._okunmamis)
            except Exception:
                pass


def _balon_ciz(canvas: tk.Canvas, *, fg: str = LACIVERT, bg: str = SARI) -> None:
    """Emoji bağımlılığı olmadan konuşma balonu çiz."""
    canvas.delete("all")
    # Gövde
    canvas.create_oval(3, 2, 22, 16, fill=bg, outline=fg, width=1)
    # Kuyruk
    canvas.create_polygon(7, 14, 4, 21, 12, 15, fill=bg, outline=fg, width=1)
    # Noktalar
    for x in (8, 12, 16):
        canvas.create_oval(x, 7, x + 2, 9, fill=fg, outline="")


def mesajlar_dugmesi_ekle(
    parent: tk.Misc,
    *,
    bg: str | None = None,
    koyu: bool = False,
    root: tk.Misc | None = None,
) -> dict[str, Any]:
    """Üst şeride konuşma balonlu Mesajlar düğmesi + kırmızı rozet.

    Sabit genişlik: dar pencerede diğer düğmeler sıkışsa bile bu yuva kaybolmaz.
    """
    bg = bg or (LACIVERT if koyu else BEYAZ)
    root = root or parent.winfo_toplevel()
    yon = MesajlasmaYoneticisi.ornek(root)

    cerceve = tk.Frame(parent, bg=bg, width=118, height=34)
    cerceve.pack_propagate(False)

    btn_bg = SARI
    btn = tk.Frame(cerceve, bg=btn_bg, cursor="hand2", highlightthickness=1, highlightbackground=LACIVERT)
    btn.pack(fill="both", expand=True, padx=2, pady=2)

    ikon = tk.Canvas(btn, width=24, height=22, bg=btn_bg, highlightthickness=0, cursor="hand2")
    ikon.pack(side="left", padx=(4, 0), pady=2)
    _balon_ciz(ikon, fg=LACIVERT, bg=BEYAZ)

    yazi = tk.Label(
        btn,
        text="Mesajlar",
        bg=btn_bg,
        fg=LACIVERT,
        font=("Segoe UI", 9, "bold"),
        cursor="hand2",
    )
    yazi.pack(side="left", padx=(2, 8))

    def _ac(_e=None):
        yon.pencere_ac(root)
        return "break"

    for w in (btn, ikon, yazi, cerceve):
        w.bind("<Button-1>", _ac)

    rozet = tk.Label(
        cerceve,
        text="",
        bg=ROZET_KIRMIZI,
        fg=BEYAZ,
        font=("Segoe UI", 8, "bold"),
        padx=3,
        pady=0,
    )

    def _rozet_guncelle(n: int):
        try:
            if n <= 0:
                rozet.place_forget()
                tip = "Mesajlar — okunmamış yok"
            else:
                metin = "9+" if n > 9 else str(n)
                rozet.configure(text=metin)
                rozet.place(in_=cerceve, relx=1.0, rely=0.0, x=-1, y=-1, anchor="ne")
                tip = f"Mesajlar — {n} okunmamış"
            for w in (btn, ikon, yazi, rozet):
                _tooltip(w, tip)
        except tk.TclError:
            yon.abonelikten_cik(_rozet_guncelle)

    yon.abone_rozet(_rozet_guncelle)

    def _yok_olunca(_e=None):
        yon.abonelikten_cik(_rozet_guncelle)

    cerceve.bind("<Destroy>", _yok_olunca, add="+")
    return {"cerceve": cerceve, "btn": btn, "rozet": rozet, "guncelle": _rozet_guncelle}


def ana_ust_seride_mesajlar_sabitle(app: tk.Misc) -> dict[str, Any] | None:
    """Ana pencere oturum_cubugu sağ kenarına sabitler (en sağda, sıkışmaz).

    side=RIGHT ile ilk pack edilen en sağda kalır. Mevcut düğme varsa dokunulmaz.
    """
    import logging

    log = logging.getLogger("mesajlasma")
    mevcut = getattr(app, "_mesajlar_dugmesi", None)
    if mevcut is not None:
        try:
            if mevcut.get("cerceve") is not None and mevcut["cerceve"].winfo_exists():
                return mevcut
        except tk.TclError:
            pass

    serit = getattr(app, "oturum_cubugu", None)
    if serit is None:
        log.warning("oturum_cubugu yok — Mesajlar düğmesi eklenemedi")
        return None
    try:
        MesajlasmaYoneticisi.ornek(app)
        msg = mesajlar_dugmesi_ekle(serit, bg=BEYAZ, koyu=False, root=app)
        # En sağ: pack side=right; kardeş varsa onların "before"ı ile sağ kenara it
        kardesler = [c for c in serit.pack_slaves() if c is not msg["cerceve"]]
        sagdakiler = []
        for c in kardesler:
            try:
                if str(c.pack_info().get("side", "")).lower() == "right":
                    sagdakiler.append(c)
            except tk.TclError:
                pass
        if sagdakiler:
            # Pack sırasına göre ilk sağdaki = şu anki en sağ; onun önüne (daha sağa) koy
            msg["cerceve"].pack(side="right", padx=(4, 10), pady=6, before=sagdakiler[0])
        else:
            msg["cerceve"].pack(side="right", padx=(4, 10), pady=6)
        app._mesajlar_dugmesi = msg
        log.info("Mesajlar düğmesi üst şeride eklendi")
        return msg
    except Exception:
        log.exception("Mesajlar düğmesi eklenemedi")
        app._mesajlar_dugmesi = None
        return None


_tooltip_win = None


def _tooltip(widget: tk.Misc, text: str):
    def enter(_e=None, t=text):
        global _tooltip_win
        try:
            if _tooltip_win is not None:
                _tooltip_win.destroy()
        except Exception:
            pass
        try:
            tw = tk.Toplevel(widget)
            tw.wm_overrideredirect(True)
            tw.attributes("-topmost", True)
            x = widget.winfo_rootx() + 8
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            tw.geometry(f"+{x}+{y}")
            tk.Label(
                tw, text=t, bg="#333333", fg=BEYAZ, font=("Segoe UI", 8), padx=6, pady=3
            ).pack()
            _tooltip_win = tw
        except tk.TclError:
            pass

    def leave(_e=None):
        global _tooltip_win
        try:
            if _tooltip_win is not None:
                _tooltip_win.destroy()
                _tooltip_win = None
        except Exception:
            pass

    widget.bind("<Enter>", enter, add="+")
    widget.bind("<Leave>", leave, add="+")


class MesajlasmaPenceresi(tk.Toplevel):
    def __init__(self, parent, *, yoneticisi: MesajlasmaYoneticisi, konusma_id: int | None = None):
        super().__init__(parent)
        self.yon = yoneticisi
        self.title("Mesajlar")
        self.geometry("860x560")
        self.minsize(640, 420)
        self.configure(bg=ACIK)
        self._secili_konusma: int | None = None
        self._gonder_kilit = False
        self._pending_client_id: str | None = None
        self._yukleniyor = False

        ust = tk.Frame(self, bg=LACIVERT)
        ust.pack(fill="x")
        tk.Label(
            ust, text="Mesajlar", bg=LACIVERT, fg=BEYAZ, font=("Segoe UI", 13, "bold")
        ).pack(side="left", padx=12, pady=8)
        self._ses_var = tk.BooleanVar(value=ses_tercihi_oku(True))
        tk.Checkbutton(
            ust,
            text="Bildirim sesi",
            variable=self._ses_var,
            command=self._ses_kaydet,
            bg=LACIVERT,
            fg=BEYAZ,
            selectcolor=LACIVERT,
            activebackground=LACIVERT,
            activeforeground=SARI,
            font=("Segoe UI", 9),
        ).pack(side="right", padx=12)

        govde = tk.Frame(self, bg=ACIK)
        govde.pack(fill="both", expand=True, padx=8, pady=8)
        govde.columnconfigure(1, weight=1)
        govde.rowconfigure(0, weight=1)

        # Sol: konuşmalar
        sol = tk.Frame(govde, bg=BEYAZ, highlightthickness=1, highlightbackground="#D0D7DE")
        sol.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        sol.rowconfigure(2, weight=1)
        tk.Label(sol, text="Konuşmalar", bg=BEYAZ, fg=LACIVERT, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w", padx=8, pady=(8, 4)
        )
        arama_f = tk.Frame(sol, bg=BEYAZ)
        arama_f.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 4))
        self._arama = ttk.Entry(arama_f, width=22)
        self._arama.pack(side="left", fill="x", expand=True)
        self._arama.bind("<KeyRelease>", lambda _e: self._kullanici_ara())
        tk.Button(
            arama_f,
            text="Yeni",
            command=self._yeni_mesaj,
            bg=SARI,
            fg=LACIVERT,
            relief="flat",
            font=("Segoe UI", 8, "bold"),
            padx=6,
            cursor="hand2",
        ).pack(side="left", padx=(4, 0))

        self._liste = tk.Listbox(
            sol, width=28, activestyle="dotbox", font=("Segoe UI", 9), exportselection=False
        )
        self._liste.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self._liste.bind("<<ListboxSelect>>", self._liste_secildi)
        self._konusma_idler: list[int] = []
        self._arama_sonuclari: list[dict] = []

        # Sağ: mesajlar
        sag = tk.Frame(govde, bg=BEYAZ, highlightthickness=1, highlightbackground="#D0D7DE")
        sag.grid(row=0, column=1, sticky="nsew")
        sag.rowconfigure(1, weight=1)
        sag.columnconfigure(0, weight=1)
        self._baslik = tk.Label(
            sag, text="Konuşma seçin veya Yeni ile başlatın", bg=BEYAZ, fg=PASIF,
            font=("Segoe UI", 10, "bold"), anchor="w"
        )
        self._baslik.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 4))

        self._canvas = tk.Canvas(sag, bg=BEYAZ, highlightthickness=0)
        scroll = ttk.Scrollbar(sag, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scroll.set)
        self._canvas.grid(row=1, column=0, sticky="nsew", padx=(8, 0))
        scroll.grid(row=1, column=1, sticky="ns", padx=(0, 4))
        self._msg_frame = tk.Frame(self._canvas, bg=BEYAZ)
        self._msg_window = self._canvas.create_window((0, 0), window=self._msg_frame, anchor="nw")
        self._msg_frame.bind(
            "<Configure>",
            lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfigure(self._msg_window, width=e.width),
        )

        alt = tk.Frame(sag, bg=BEYAZ)
        alt.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        alt.columnconfigure(0, weight=1)
        self._giris = tk.Text(alt, height=3, wrap="word", font=("Segoe UI", 10), relief="solid", bd=1)
        self._giris.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._giris.bind("<Return>", self._enter_gonder)
        # Shift+Return: bağlama yok → Text varsayılanı yeni satır açar
        self._durum_lbl = tk.Label(alt, text="", bg=BEYAZ, fg=PASIF, font=("Segoe UI", 8), anchor="w")
        self._durum_lbl.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._gonder_btn = tk.Button(
            alt,
            text="Gönder",
            command=self._gonder,
            bg=LACIVERT,
            fg=BEYAZ,
            relief="flat",
            font=("Segoe UI", 10, "bold"),
            padx=14,
            pady=8,
            cursor="hand2",
        )
        self._gonder_btn.grid(row=0, column=1, rowspan=2, sticky="ns")

        self.protocol("WM_DELETE_WINDOW", self._kapat)
        self.listeyi_yenile()
        if konusma_id:
            self.after(100, lambda: self.konusma_sec(int(konusma_id)))

    def _ses_kaydet(self):
        ses_tercihi_yaz(bool(self._ses_var.get()))

    def _kapat(self):
        try:
            if self.yon._pencere is self:
                self.yon._pencere = None
        except Exception:
            pass
        self.destroy()
        self.yon.rozet_yenile_hemen()

    def listeyi_yenile(self):
        try:
            konusmalar = MesajlasmaService.konusmalari_listele()
        except MesajlasmaError as exc:
            self._durum_lbl.configure(text=str(exc), fg=ROZET_KIRMIZI)
            return
        except Exception as exc:
            self._durum_lbl.configure(text=f"Liste yüklenemedi: {exc}", fg=ROZET_KIRMIZI)
            return
        self._konusma_idler = [int(k["id"]) for k in konusmalar]
        self._liste.delete(0, "end")
        for k in konusmalar:
            rozet = f" ({k['okunmamis']})" if k.get("okunmamis") else ""
            ozet = (k.get("son_mesaj_ozet") or "")[:40]
            self._liste.insert("end", f"{k['baslik']}{rozet}")
            if ozet:
                # ikinci satır yerine tooltip yok; baslik yeterli
                pass
        self._arama_sonuclari = []

    def _kullanici_ara(self):
        q = (self._arama.get() or "").strip()
        if len(q) < 1:
            self.listeyi_yenile()
            return
        try:
            self._arama_sonuclari = MesajlasmaService.firma_kullanicilari(q)
        except Exception:
            self._arama_sonuclari = []
        self._liste.delete(0, "end")
        self._konusma_idler = []
        for u in self._arama_sonuclari:
            self._liste.insert("end", f"＋ {u['gorunen']}")

    def _yeni_mesaj(self):
        self._arama.focus_set()
        self._kullanici_ara()

    def _liste_secildi(self, _e=None):
        sec = self._liste.curselection()
        if not sec:
            return
        i = int(sec[0])
        if self._arama_sonuclari:
            if i >= len(self._arama_sonuclari):
                return
            u = self._arama_sonuclari[i]
            try:
                k = MesajlasmaService.dm_ac_veya_bul(int(u["id"]))
            except MesajlasmaError as exc:
                messagebox.showwarning("Mesajlar", str(exc), parent=self)
                return
            self._arama.delete(0, "end")
            self.listeyi_yenile()
            self.konusma_sec(int(k["id"]))
            return
        if i >= len(self._konusma_idler):
            return
        self.konusma_sec(self._konusma_idler[i])

    def konusma_sec(self, konusma_id: int):
        self._secili_konusma = int(konusma_id)
        # Listede seç
        try:
            idx = self._konusma_idler.index(int(konusma_id))
            self._liste.selection_clear(0, "end")
            self._liste.selection_set(idx)
            self._liste.see(idx)
        except ValueError:
            pass
        self._mesajlari_yukle()

    def _mesajlari_yukle(self, *, after_id: int | None = None):
        if not self._secili_konusma:
            return
        try:
            if after_id:
                mesajlar = MesajlasmaService.mesajlari_listele(
                    self._secili_konusma, after_id=after_id, limit=50
                )
                for m in mesajlar:
                    self._mesaj_balonu_ekle(m)
            else:
                for w in self._msg_frame.winfo_children():
                    w.destroy()
                mesajlar = MesajlasmaService.mesajlari_listele(self._secili_konusma, limit=50)
                for m in mesajlar:
                    self._mesaj_balonu_ekle(m)
                self.after(50, lambda: self._canvas.yview_moveto(1.0))
            if mesajlar:
                son_id = max(int(m["id"]) for m in mesajlar)
                MesajlasmaService.konusmayi_okundu_isaretle(self._secili_konusma, son_id)
                self.yon.rozet_yenile_hemen()
                # Başlık
                konusmalar = MesajlasmaService.konusmalari_listele()
                for k in konusmalar:
                    if int(k["id"]) == int(self._secili_konusma):
                        self._baslik.configure(text=k["baslik"], fg=LACIVERT)
                        break
            self._durum_lbl.configure(text="", fg=PASIF)
        except MesajlasmaError as exc:
            self._durum_lbl.configure(text=str(exc), fg=ROZET_KIRMIZI)
        except Exception as exc:
            self._durum_lbl.configure(text=f"Yükleme hatası: {exc}", fg=ROZET_KIRMIZI)

    def poll_yenile(self, yeni: list[dict]):
        if not self._secili_konusma or not yeni:
            self.listeyi_yenile()
            return
        ilgili = [m for m in yeni if int(m.get("konusma_id") or 0) == int(self._secili_konusma)]
        if ilgili:
            for m in ilgili:
                self._mesaj_balonu_ekle(m)
            self.after(30, lambda: self._canvas.yview_moveto(1.0))
            son = max(int(m["id"]) for m in ilgili)
            try:
                MesajlasmaService.konusmayi_okundu_isaretle(self._secili_konusma, son)
            except Exception:
                pass
            self.yon.rozet_yenile_hemen()
        self.listeyi_yenile()

    def _mesaj_balonu_ekle(self, m: dict):
        benim = bool(m.get("benim"))
        satir = tk.Frame(self._msg_frame, bg=BEYAZ)
        satir.pack(fill="x", padx=8, pady=3, anchor="e" if benim else "w")
        bg = GIDEN_BG if benim else GELEN_BG
        balon = tk.Frame(satir, bg=bg, padx=8, pady=4)
        balon.pack(anchor="e" if benim else "w")
        kim = "Siz" if benim else (m.get("gonderen_adi") or m.get("gonderen_kullanici") or "")
        ust = f"{kim}  ·  {_tarih_goster(m.get('tarih'))}  ·  {m.get('durum') or 'gonderildi'}"
        tk.Label(balon, text=ust, bg=bg, fg=PASIF, font=("Segoe UI", 8), anchor="w").pack(anchor="w")
        tk.Label(
            balon,
            text=m.get("icerik") or "",
            bg=bg,
            fg=LACIVERT,
            font=("Segoe UI", 10),
            wraplength=420,
            justify="left",
            anchor="w",
        ).pack(anchor="w")

    def _enter_gonder(self, event):
        # Shift+Return → yeni satır (default); düz Return → gönder
        if event.state & 0x0001:  # Shift
            return None
        self._gonder()
        return "break"

    def _gonder(self):
        if self._gonder_kilit:
            return
        if not self._secili_konusma:
            messagebox.showinfo("Mesajlar", "Önce bir konuşma seçin veya Yeni ile alıcı bulun.", parent=self)
            return
        metin = self._giris.get("1.0", "end-1c")
        if not (metin or "").strip():
            return
        client_id = self._pending_client_id or str(uuid.uuid4())
        self._pending_client_id = client_id
        self._gonder_kilit = True
        self._gonder_btn.configure(state="disabled", text="…")
        self._durum_lbl.configure(text="Gönderiliyor…", fg=PASIF)

        def isci():
            try:
                m = MesajlasmaService.mesaj_gonder(
                    int(self._secili_konusma), metin, client_msg_id=client_id
                )
                hata = None
            except Exception as exc:
                m = None
                hata = str(exc)
            self.after(0, lambda: self._gonder_sonuc(m, hata, metin, client_id))

        threading.Thread(target=isci, daemon=True).start()

    def _gonder_sonuc(self, m, hata, metin, client_id):
        self._gonder_kilit = False
        self._gonder_btn.configure(state="normal", text="Gönder")
        if hata or m is None:
            # Metni koru; gönderilmiş gösterme
            self._pending_client_id = client_id
            self._durum_lbl.configure(
                text=f"Gönderilemedi — metin korundu. Yeniden deneyin. ({hata})",
                fg=ROZET_KIRMIZI,
            )
            return
        self._pending_client_id = None
        self._giris.delete("1.0", "end")
        self._durum_lbl.configure(text="Gönderildi", fg="#1E7A3A")
        self._mesaj_balonu_ekle(m)
        self.after(30, lambda: self._canvas.yview_moveto(1.0))
        self.listeyi_yenile()
        self.yon.rozet_yenile_hemen()
