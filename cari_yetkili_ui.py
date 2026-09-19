"""Cari kart — İşletme Yetkilileri paneli ve düzenleme penceresi."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk
from typing import Any, Callable

from cari_kart_tema import (
    ACIK_BG,
    BEYAZ,
    CIZGI,
    IKINCIL,
    LACIVERT,
    SARI,
    STRIPE,
    font,
    tk_buton,
)
from database.cari_yetkili_service import CariYetkiliService


def _tarih_goster(d) -> str:
    if not d:
        return ""
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d)


class YetkiliDialog(tk.Toplevel):
    def __init__(
        self,
        parent,
        *,
        cari_id: int,
        yetkili: dict[str, Any] | None = None,
        on_kaydet: Callable[[], None] | None = None,
    ):
        super().__init__(parent)
        self.cari_id = int(cari_id)
        self.yetkili = dict(yetkili or {})
        self._on_kaydet = on_kaydet
        self.transient(parent)
        self.grab_set()
        self.configure(bg=ACIK_BG)
        self.title("Yetkili Düzenle" if self.yetkili.get("id") else "Yeni Yetkili")
        self.geometry("560x640")
        self.minsize(520, 560)

        self._vars: dict[str, tk.Variable] = {}
        govde = tk.Frame(self, bg=ACIK_BG, padx=12, pady=10)
        govde.pack(fill="both", expand=True)

        def satir(etiket, alan, *, genislik=28, tip="entry"):
            tk.Label(govde, text=etiket, bg=ACIK_BG, fg=LACIVERT, font=font(9, root=self)).pack(
                anchor="w"
            )
            if tip == "check":
                var = tk.BooleanVar(value=bool(self.yetkili.get(alan)))
                ttk.Checkbutton(govde, variable=var).pack(anchor="w", pady=(0, 6))
            else:
                var = tk.StringVar(value=str(self.yetkili.get(alan) or ""))
                if alan == "dogum_tarihi" and self.yetkili.get("dogum_tarihi"):
                    var.set(_tarih_goster(self.yetkili.get("dogum_tarihi")))
                ttk.Entry(govde, textvariable=var, width=genislik).pack(anchor="w", pady=(0, 6))
            self._vars[alan] = var

        tk.Label(
            govde, text="Kimlik / Görev", bg=ACIK_BG, fg=LACIVERT, font=font(11, "bold", self)
        ).pack(anchor="w", pady=(0, 4))
        satir("Ad *", "ad")
        satir("Soyad *", "soyad")
        satir("Unvan", "unvan")
        satir("Departman", "departman")
        satir("Görev", "gorev")
        satir("Ana yetkili", "ana_yetkili", tip="check")
        satir("Aktif", "aktif", tip="check")
        if "aktif" not in self.yetkili:
            self._vars["aktif"].set(True)

        tk.Label(
            govde, text="İletişim", bg=ACIK_BG, fg=LACIVERT, font=font(11, "bold", self)
        ).pack(anchor="w", pady=(8, 4))
        satir("Cep telefonu", "cep_telefonu")
        satir("İkinci telefon", "telefon2")
        satir("WhatsApp", "whatsapp_telefonu")
        satir("İş telefonu", "is_telefonu")
        satir("Dahili", "dahili", genislik=12)
        satir("E-posta", "email")

        hassas = CariYetkiliService.hassas_izinli()
        if hassas:
            tk.Label(
                govde,
                text="Özel bilgiler",
                bg=ACIK_BG,
                fg=LACIVERT,
                font=font(11, "bold", self),
            ).pack(anchor="w", pady=(8, 4))
            satir("Doğum tarihi (GG.AA.YYYY)", "dogum_tarihi")
            satir("Doğum günü hatırlat", "dogum_gunu_hatirlat", tip="check")
            if "dogum_gunu_hatirlat" not in self.yetkili:
                self._vars["dogum_gunu_hatirlat"].set(True)
            satir("Hitap", "hitap")
            satir("Tercih edilen kanal", "iletisim_kanali")
            satir("Özel notlar", "ozel_notlar", genislik=50)
            satir("Pazarlama izni", "pazarlama_izni", tip="check")
            satir("KVKK / iletişim onayı", "kvkk_onayi", tip="check")

        alt = tk.Frame(self, bg=ACIK_BG, padx=12, pady=10)
        alt.pack(fill="x")
        tk_buton(alt, "Kaydet", self._kaydet, rol="kaydet").pack(side="left")
        tk_buton(alt, "Vazgeç", self.destroy, rol="ikincil").pack(side="right")
        self.bind("<Return>", lambda _e: self._kaydet())
        self.bind("<Escape>", lambda _e: self.destroy())

    def _kaydet(self):
        veri = {}
        for alan, var in self._vars.items():
            if isinstance(var, tk.BooleanVar):
                veri[alan] = bool(var.get())
            else:
                veri[alan] = var.get().strip()
        try:
            if self.yetkili.get("id"):
                CariYetkiliService.guncelle(int(self.yetkili["id"]), veri)
            else:
                CariYetkiliService.ekle(self.cari_id, veri)
        except Exception as hata:
            messagebox.showerror("Yetkili", str(hata), parent=self)
            return
        if self._on_kaydet:
            self._on_kaydet()
        self.destroy()


class YetkiliPanel(tk.Frame):
    """Cari kart içi İşletme Yetkilileri paneli."""

    def __init__(self, parent, *, dialog, **kw):
        super().__init__(parent, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI, **kw)
        self.dialog = dialog
        self._cari_id = int(dialog.cari.id) if dialog.cari and getattr(dialog.cari, "id", None) else None

        baslik = tk.Frame(self, bg=LACIVERT)
        baslik.pack(fill="x")
        tk.Label(
            baslik,
            text="İşletme Yetkilileri",
            bg=LACIVERT,
            fg=SARI,
            font=font(11, "bold", dialog),
            padx=10,
            pady=6,
        ).pack(side="left")
        self._ozet_lbl = tk.Label(
            baslik, text="", bg=LACIVERT, fg=BEYAZ, font=font(9, root=dialog), padx=8
        )
        self._ozet_lbl.pack(side="right")

        arac = tk.Frame(self, bg=BEYAZ, padx=8, pady=6)
        arac.pack(fill="x")
        self._btn_yeni = tk_buton(arac, "Yeni Yetkili", self._yeni, rol="yeni")
        self._btn_yeni.pack(side="left", padx=(0, 4))
        self._btn_duzenle = tk_buton(arac, "Düzenle", self._duzenle, rol="duzenle")
        self._btn_duzenle.pack(side="left", padx=4)
        self._btn_pasif = tk_buton(arac, "Pasife Al", self._pasif, rol="ara")
        self._btn_pasif.pack(side="left", padx=4)
        self._btn_sil = tk_buton(arac, "Sil", self._sil, rol="iptal")
        self._btn_sil.pack(side="left", padx=4)

        kolonlar = ("ad", "unvan", "telefon", "email", "ana", "durum")
        self.tablo = ttk.Treeview(
            self, columns=kolonlar, show="headings", height=5, selectmode="browse"
        )
        for k, b, w in (
            ("ad", "Ad Soyad", 160),
            ("unvan", "Unvan / Görev", 140),
            ("telefon", "Telefon", 110),
            ("email", "E-posta", 150),
            ("ana", "Ana", 50),
            ("durum", "Durum", 60),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w, anchor="w")
        self.tablo.tag_configure("cift", background=STRIPE)
        self.tablo.tag_configure("tek", background=BEYAZ)
        self.tablo.pack(fill="x", padx=8, pady=(0, 8))
        self.tablo.bind("<Double-1>", lambda _e: self._duzenle())
        self.tablo.bind("<Button-3>", self._sag_tik)
        self.tablo.bind("<F2>", lambda _e: self._duzenle())

        self._kayitlar: list[dict[str, Any]] = []
        self._yetki_durumu_ayarla()
        self.yenile()

    def _yetki_durumu_ayarla(self):
        duzenle = CariYetkiliService.duzenleme_izinli() and self._cari_id
        durum = "normal" if duzenle else "disabled"
        for b in (self._btn_yeni, self._btn_duzenle, self._btn_pasif, self._btn_sil):
            try:
                b.configure(state=durum)
            except tk.TclError:
                pass

    def yenile(self):
        for i in self.tablo.get_children():
            self.tablo.delete(i)
        self._kayitlar = []
        if not self._cari_id:
            self._ozet_lbl.configure(text="Önce cariyi kaydedin")
            return
        try:
            self._kayitlar = CariYetkiliService.listele(self._cari_id, pasifler_dahil=True)
        except Exception:
            self._kayitlar = []
        for i, k in enumerate(self._kayitlar):
            self.tablo.insert(
                "",
                "end",
                iid=str(k["id"]),
                tags=("cift" if i % 2 else "tek",),
                values=(
                    k.get("ad_soyad") or "",
                    k.get("unvan") or k.get("gorev") or "",
                    k.get("cep_telefonu") or "",
                    k.get("email") or "",
                    "Evet" if k.get("ana_yetkili") else "",
                    "Aktif" if k.get("aktif") else "Pasif",
                ),
            )
        ana = next((k for k in self._kayitlar if k.get("ana_yetkili") and k.get("aktif")), None)
        if ana:
            self._ozet_lbl.configure(
                text=f"Ana: {ana.get('ad_soyad')}  ·  {ana.get('cep_telefonu') or '—'}  ·  {ana.get('email') or '—'}"
            )
        else:
            self._ozet_lbl.configure(text=f"{len([k for k in self._kayitlar if k.get('aktif')])} yetkili")

    def _secili(self) -> dict[str, Any] | None:
        sec = self.tablo.selection()
        if not sec:
            return None
        try:
            kid = int(sec[0])
        except (TypeError, ValueError):
            return None
        return next((k for k in self._kayitlar if k["id"] == kid), None)

    def _yeni(self):
        if not self._cari_id:
            messagebox.showinfo("Yetkili", "Önce cari kartını kaydedin.", parent=self.dialog)
            return
        YetkiliDialog(self.dialog, cari_id=self._cari_id, on_kaydet=self.yenile)

    def _duzenle(self):
        k = self._secili()
        if not k:
            messagebox.showinfo("Yetkili", "Önce satır seçin.", parent=self.dialog)
            return
        YetkiliDialog(self.dialog, cari_id=self._cari_id, yetkili=k, on_kaydet=self.yenile)

    def _pasif(self):
        k = self._secili()
        if not k:
            return
        if not messagebox.askyesno("Pasife Al", f"{k.get('ad_soyad')} pasife alınsın mı?", parent=self.dialog):
            return
        try:
            CariYetkiliService.pasife_al(int(k["id"]))
            self.yenile()
        except Exception as hata:
            messagebox.showerror("Yetkili", str(hata), parent=self.dialog)

    def _sil(self):
        k = self._secili()
        if not k:
            return
        uyari = f"{k.get('ad_soyad')} silinsin mi?\nKayıt pasife alınıp arşivlenecektir."
        if k.get("ana_yetkili"):
            uyari = "Bu kişi ANA YETKİLİ.\n\n" + uyari
        if not messagebox.askyesno("Sil", uyari, parent=self.dialog):
            return
        try:
            CariYetkiliService.sil(int(k["id"]), fiziksel=False)
            self.yenile()
        except Exception as hata:
            messagebox.showerror("Yetkili", str(hata), parent=self.dialog)

    def _sag_tik(self, event):
        row = self.tablo.identify_row(event.y)
        if row:
            self.tablo.selection_set(row)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Düzenle", command=self._duzenle)
        menu.add_command(label="Pasife Al", command=self._pasif)
        menu.add_command(label="Sil", command=self._sil)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()


class DogumGunuBildirimDialog(tk.Toplevel):
    """Ana panel bildirim — yaklaşan yetkili doğum günleri."""

    def __init__(self, parent, *, gun: int = 7, on_cari_ac: Callable[[int, int | None], None] | None = None):
        super().__init__(parent)
        self._on_cari_ac = on_cari_ac
        self.transient(parent)
        self.title("Yaklaşan Doğum Günleri")
        self.geometry("780x480")
        self.configure(bg=ACIK_BG)

        ust = tk.Frame(self, bg=ACIK_BG, padx=10, pady=8)
        ust.pack(fill="x")
        tk.Label(ust, text="Aralık (gün):", bg=ACIK_BG).pack(side="left")
        self._gun = tk.StringVar(value=str(gun))
        ttk.Entry(ust, textvariable=self._gun, width=6).pack(side="left", padx=6)
        tk_buton(ust, "7 gün", lambda: self._gun_ayarla(7), rol="ara").pack(side="left", padx=2)
        tk_buton(ust, "30 gün", lambda: self._gun_ayarla(30), rol="ara").pack(side="left", padx=2)
        tk_buton(ust, "Yenile", self.yenile, rol="ara").pack(side="left", padx=6)

        filtre = tk.Frame(self, bg=ACIK_BG, padx=10, pady=4)
        filtre.pack(fill="x")
        tk.Label(filtre, text="Cari türü:", bg=ACIK_BG).pack(side="left")
        self._cari_turu = tk.StringVar(value="Tümü")
        ttk.Combobox(
            filtre,
            textvariable=self._cari_turu,
            values=("Tümü", "Müşteri", "Tedarikçi"),
            state="readonly",
            width=12,
        ).pack(side="left", padx=6)
        tk.Label(filtre, text="Grup:", bg=ACIK_BG).pack(side="left", padx=(8, 0))
        self._grup = tk.StringVar(value="")
        ttk.Entry(filtre, textvariable=self._grup, width=18).pack(side="left", padx=6)
        self._hatirlat_kapali = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            filtre, text="Hatırlatması kapalıları da göster", variable=self._hatirlat_kapali
        ).pack(side="left", padx=12)

        kolonlar = ("gun", "tarih", "kisi", "cari", "tel", "yas")
        self.tablo = ttk.Treeview(self, columns=kolonlar, show="headings", height=14)
        for k, b, w in (
            ("gun", "Kalan", 60),
            ("tarih", "Doğum günü", 100),
            ("kisi", "Yetkili", 160),
            ("cari", "Cari", 200),
            ("tel", "Telefon", 110),
            ("yas", "Yaş", 50),
        ):
            self.tablo.heading(k, text=b)
            self.tablo.column(k, width=w)
        self.tablo.pack(fill="both", expand=True, padx=10, pady=6)
        self.tablo.bind("<Double-1>", self._ac)

        alt = tk.Frame(self, bg=ACIK_BG, padx=10, pady=8)
        alt.pack(fill="x")
        tk_buton(alt, "Cari Kartı Aç", self._ac, rol="duzenle").pack(side="left")
        tk.Label(
            alt,
            text="Toplu SMS/WhatsApp/e-posta otomatik gönderilmez.",
            bg=ACIK_BG,
            fg=IKINCIL,
            font=font(8, root=self),
        ).pack(side="left", padx=12)
        tk_buton(alt, "Kapat", self.destroy, rol="ikincil").pack(side="right")
        self._kayitlar: list[dict] = []
        self.yenile()

    def _gun_ayarla(self, gun: int):
        self._gun.set(str(gun))
        self.yenile()

    def yenile(self):
        for i in self.tablo.get_children():
            self.tablo.delete(i)
        try:
            gun = int(self._gun.get() or 7)
        except ValueError:
            gun = 7
        tur = self._cari_turu.get()
        if tur == "Tümü":
            tur = None
        grup = (self._grup.get() or "").strip() or None
        try:
            self._kayitlar = CariYetkiliService.dogum_gunleri(
                gun=gun,
                cari_turu=tur,
                musteri_grubu=grup,
                hatirlat_kapali_dahil=bool(self._hatirlat_kapali.get()),
            )
        except Exception as hata:
            messagebox.showerror("Bildirim", str(hata), parent=self)
            self._kayitlar = []
        for i, k in enumerate(self._kayitlar):
            self.tablo.insert(
                "",
                "end",
                iid=str(i),
                values=(
                    k.get("gun_kaldi"),
                    _tarih_goster(k.get("sonraki_dogum")),
                    k.get("ad_soyad"),
                    f"{k.get('cari_kodu')} — {k.get('cari_unvan')}",
                    k.get("cep_telefonu") or "",
                    k.get("yas") if k.get("yas") is not None else "",
                ),
            )

    def _ac(self, _e=None):
        sec = self.tablo.selection()
        if not sec:
            return
        try:
            idx = int(sec[0])
        except (TypeError, ValueError):
            return
        if not (0 <= idx < len(self._kayitlar)):
            return
        k = self._kayitlar[idx]
        if self._on_cari_ac:
            self._on_cari_ac(int(k["cari_id"]), int(k["yetkili_id"]))
        self.destroy()
