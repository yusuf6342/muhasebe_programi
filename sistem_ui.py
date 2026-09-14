"""Sistem Yönetimi ekranları — kullanıcı, firma, rol, dönem, audit, yedek."""

from __future__ import annotations

import tkinter as tk
from datetime import date, datetime
from tkinter import filedialog, messagebox, ttk

from sqlalchemy import select

from database.database import get_system_session
from database.donem_service import DonemService
from database.session_manager import oturum
from database.system.company_service import CompanyMgmtService
from database.system.models import AuditLog
from database.system.role_service import RoleService
from database.system.user_service import UserService
from ui_takvim import takvim_butonu


def _tarih_goster(d) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        return d.strftime("%d.%m.%Y %H:%M")
    if isinstance(d, date):
        return d.strftime("%d.%m.%Y")
    return str(d)


def _yetki_yok(parent, mesaj: str = "Bu bölüme erişim yetkiniz yok.") -> bool:
    if oturum.role_kod == "YONETICI":
        return False
    if oturum.has_permission("kullanici_yonetme") or oturum.has_permission("firma_yonetme"):
        return False
    messagebox.showwarning("Yetki", mesaj, parent=parent)
    return True


def sistem_menusu_goster(app) -> None:
    if _yetki_yok(app):
        app.sayfa_goster("giris")
        return
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x", pady=(24, 0))
    alt.columnconfigure(0, weight=1, minsize=520)
    ogeler = [
        ("KULLANICILAR", lambda: kullanicilar_goster(app)),
        ("ROLLER VE YETKİLER", lambda: roller_goster(app)),
        ("FİRMALAR", lambda: sistem_firmalar_goster(app)),
        ("ÇALIŞMA DÖNEMLERİ", lambda: donemler_yonet_goster(app)),
        ("İŞLEM KAYITLARI", lambda: audit_goster(app)),
        ("VERİTABANI YEDEKLEME", lambda: yedekleme_goster(app)),
        ("GEÇİŞ DOĞRULAMA", lambda: gecis_dogrulama_goster(app)),
    ]
    # Yetkiye göre filtre
    if not oturum.has_permission("kullanici_yonetme") and oturum.role_kod != "YONETICI":
        ogeler = [o for o in ogeler if o[0] not in ("KULLANICILAR", "ROLLER VE YETKİLER")]
    if not oturum.has_permission("firma_yonetme") and oturum.role_kod != "YONETICI":
        ogeler = [o for o in ogeler if o[0] != "FİRMALAR"]
    if not oturum.has_permission("yedek_alma") and oturum.role_kod != "YONETICI":
        ogeler = [o for o in ogeler if o[0] != "VERİTABANI YEDEKLEME"]

    for i, (baslik, komut) in enumerate(ogeler):
        app._alt_menu_dugme(alt, baslik, komut, row=i, column=0, sticky="ew", pady=4)


def _sistem_baslik(app, baslik: str) -> None:
    app._icerigi_temizle()
    for anahtar, dugme in app.menu_dugmeleri.items():
        dugme.configure(
            style="SeciliMenu.TButton" if anahtar == "sistem" else "Menu.TButton"
        )
    ttk.Label(app.icerik, text=baslik, style="Baslik.TLabel").pack(anchor="w")
    ttk.Button(
        app.icerik, text="← Sistem Yönetimi", command=lambda: app.sayfa_goster("sistem")
    ).pack(anchor="w", pady=(8, 12))


# ── Kullanıcılar ──────────────────────────────────────────────

def kullanicilar_goster(app) -> None:
    _sistem_baslik(app, "KULLANICILAR")
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="Ara:").pack(side="left")
    arama = ttk.Entry(ust, width=28)
    arama.pack(side="left", padx=6)

    tablo = ttk.Treeview(
        app.icerik,
        columns=("kod", "ad", "user", "rol", "durum", "son"),
        show="headings",
        selectmode="browse",
        height=16,
    )
    for k, b, w in (
        ("kod", "Kod", 80),
        ("ad", "Ad Soyad", 160),
        ("user", "Kullanıcı Adı", 120),
        ("rol", "Rol", 100),
        ("durum", "Durum", 70),
        ("son", "Son Giriş", 130),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="w")
    tablo.pack(fill="both", expand=True, pady=8)

    def yenile():
        for i in tablo.get_children():
            tablo.delete(i)
        try:
            for u in UserService.listele(arama.get()):
                tablo.insert(
                    "",
                    "end",
                    iid=str(u["id"]),
                    values=(
                        u["kullanici_kodu"],
                        u["ad_soyad"],
                        u["kullanici_adi"],
                        u["rol"],
                        "Aktif" if u["aktif"] else "Pasif",
                        _tarih_goster(u["son_giris_tarihi"]),
                    ),
                )
        except Exception as hata:
            messagebox.showerror("Kullanıcılar", str(hata), parent=app)

    def secili_id():
        s = tablo.selection()
        return int(s[0]) if s else None

    def yeni():
        dlg = KullaniciDialog(app)
        app.wait_window(dlg)
        if dlg.result:
            yenile()

    def duzenle():
        uid = secili_id()
        if uid is None:
            messagebox.showinfo("Seçim", "Kullanıcı seçin.", parent=app)
            return
        dlg = KullaniciDialog(app, user_id=uid)
        app.wait_window(dlg)
        if dlg.result:
            yenile()

    def pasif():
        uid = secili_id()
        if uid is None:
            return
        if messagebox.askyesno("Pasife al", "Kullanıcı pasife alınsın mı?", parent=app):
            try:
                UserService.pasife_al(uid)
                yenile()
            except Exception as hata:
                messagebox.showerror("İşlem", str(hata), parent=app)

    def sifre_sifirla():
        uid = secili_id()
        if uid is None:
            return
        if not messagebox.askyesno("Şifre", "Geçici şifre üretilsin mi?", parent=app):
            return
        try:
            yeni_p = UserService.sifre_sifirla(uid)
            messagebox.showinfo(
                "Geçici şifre",
                f"Yeni geçici şifre:\n\n{yeni_p}\n\nKullanıcı ilk girişte değiştirmek zorundadır.",
                parent=app,
            )
        except Exception as hata:
            messagebox.showerror("Şifre", str(hata), parent=app)

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x")
    ttk.Button(ust, text="Ara", command=yenile).pack(side="left")
    ttk.Button(ust, text="Yeni Kullanıcı", command=yeni).pack(side="right")
    ttk.Button(alt, text="Düzenle", command=duzenle).pack(side="left")
    ttk.Button(alt, text="Pasife Al", command=pasif).pack(side="left", padx=6)
    ttk.Button(alt, text="Şifre Sıfırla", command=sifre_sifirla).pack(side="left")
    arama.bind("<Return>", lambda _e: yenile())
    yenile()


class KullaniciDialog(tk.Toplevel):
    def __init__(self, parent, user_id: int | None = None):
        super().__init__(parent)
        self.title("Kullanıcı Kartı")
        self.result = False
        self.user_id = user_id
        self.transient(parent)
        self.grab_set()
        self.geometry("520x520")

        mevcut = UserService.getir(user_id) if user_id else None
        roller = UserService.roller()
        firmalar = CompanyMgmtService.ozet_liste_herkese()

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)

        self.alanlar = {}
        satir = 0
        for etiket, anahtar, gen in (
            ("Kullanıcı kodu", "kullanici_kodu", 24),
            ("Adı soyadı", "ad_soyad", 32),
            ("Kullanıcı adı", "kullanici_adi", 24),
        ):
            ttk.Label(frm, text=etiket + ":").grid(row=satir, column=0, sticky="w", pady=4)
            e = ttk.Entry(frm, width=gen)
            e.grid(row=satir, column=1, sticky="ew", pady=4)
            if mevcut:
                e.insert(0, mevcut.get(anahtar) or "")
            self.alanlar[anahtar] = e
            satir += 1

        if user_id is None:
            ttk.Label(frm, text="Şifre (boş=üretilir):").grid(row=satir, column=0, sticky="w", pady=4)
            self.parola = ttk.Entry(frm, width=24, show="*")
            self.parola.grid(row=satir, column=1, sticky="ew", pady=4)
            from auth_ui import entry_yapistirma_etkin

            entry_yapistirma_etkin(self.parola)
            satir += 1

        ttk.Label(frm, text="Rol:").grid(row=satir, column=0, sticky="w", pady=4)
        self.rol = ttk.Combobox(
            frm, state="readonly", values=[f"{i}:{a}" for i, a in roller], width=30
        )
        self.rol.grid(row=satir, column=1, sticky="ew", pady=4)
        if mevcut:
            for i, a in roller:
                if i == mevcut["role_id"]:
                    self.rol.set(f"{i}:{a}")
                    break
        elif roller:
            self.rol.current(0)
        satir += 1

        self.aktif = tk.BooleanVar(value=True if not mevcut else mevcut["aktif"])
        ttk.Checkbutton(frm, text="Aktif", variable=self.aktif).grid(
            row=satir, column=1, sticky="w", pady=4
        )
        satir += 1

        ttk.Label(frm, text="Erişebileceği firmalar:").grid(
            row=satir, column=0, sticky="nw", pady=4
        )
        self.firma_liste = tk.Listbox(frm, selectmode="multiple", height=8, exportselection=False)
        self.firma_liste.grid(row=satir, column=1, sticky="ew", pady=4)
        self._firma_map = []
        secili = set(mevcut["firma_idler"]) if mevcut else set()
        for fid, ad in firmalar:
            self._firma_map.append(fid)
            self.firma_liste.insert("end", ad)
            if fid in secili:
                self.firma_liste.selection_set(len(self._firma_map) - 1)
        satir += 1

        ttk.Label(frm, text="Varsayılan firma:").grid(row=satir, column=0, sticky="w", pady=4)
        self.varsayilan = ttk.Combobox(
            frm, state="readonly",
            values=["(yok)"] + [f"{i}:{a}" for i, a in firmalar],
            width=30,
        )
        self.varsayilan.grid(row=satir, column=1, sticky="ew", pady=4)
        if mevcut and mevcut.get("varsayilan_firma_id"):
            for i, a in firmalar:
                if i == mevcut["varsayilan_firma_id"]:
                    self.varsayilan.set(f"{i}:{a}")
                    break
        else:
            self.varsayilan.set("(yok)")
        satir += 1

        butonlar = ttk.Frame(frm)
        butonlar.grid(row=satir, column=0, columnspan=2, sticky="e", pady=12)
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(butonlar, text="Kaydet", command=self._kaydet).pack(side="left")

    def _kaydet(self):
        try:
            role_txt = self.rol.get()
            if ":" not in role_txt:
                raise ValueError("Rol seçin.")
            role_id = int(role_txt.split(":", 1)[0])
            firma_idler = [self._firma_map[i] for i in self.firma_liste.curselection()]
            vars_id = None
            v = self.varsayilan.get()
            if v and v != "(yok)" and ":" in v:
                vars_id = int(v.split(":", 1)[0])
            veriler = {
                "kullanici_kodu": self.alanlar["kullanici_kodu"].get(),
                "ad_soyad": self.alanlar["ad_soyad"].get(),
                "kullanici_adi": self.alanlar["kullanici_adi"].get(),
                "role_id": role_id,
                "aktif": self.aktif.get(),
                "firma_idler": firma_idler,
                "varsayilan_firma_id": vars_id,
            }
            if not veriler["kullanici_kodu"] or not veriler["ad_soyad"] or not veriler["kullanici_adi"]:
                raise ValueError("Kod, ad soyad ve kullanıcı adı zorunludur.")
            if self.user_id is None:
                veriler["parola"] = self.parola.get()
                uid, gecici = UserService.ekle(veriler)
                if gecici:
                    messagebox.showinfo(
                        "Geçici şifre",
                        f"Kullanıcı oluşturuldu.\nGeçici şifre: {gecici}",
                        parent=self,
                    )
            else:
                UserService.guncelle(self.user_id, veriler)
            self.result = True
            self.destroy()
        except Exception as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)


# ── Firmalar ──────────────────────────────────────────────────

def sistem_firmalar_goster(app) -> None:
    _sistem_baslik(app, "FİRMALAR")
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="x")
    ttk.Label(ust, text="Ara:").pack(side="left")
    arama = ttk.Entry(ust, width=28)
    arama.pack(side="left", padx=6)

    tablo = ttk.Treeview(
        app.icerik,
        columns=("kod", "unvan", "vergi", "pb", "durum"),
        show="headings",
        height=14,
    )
    for k, b, w in (
        ("kod", "Kod", 90),
        ("unvan", "Ünvan", 260),
        ("vergi", "Vergi No", 110),
        ("pb", "PB", 50),
        ("durum", "Durum", 70),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w)
    tablo.pack(fill="both", expand=True, pady=8)

    def yenile():
        for i in tablo.get_children():
            tablo.delete(i)
        try:
            for f in CompanyMgmtService.listele(arama.get()):
                tablo.insert(
                    "", "end", iid=str(f["id"]),
                    values=(
                        f["firma_kodu"], f["unvan"], f["vergi_no"] or "",
                        f["varsayilan_para_birimi"], "Aktif" if f["aktif"] else "Pasif",
                    ),
                )
        except Exception as hata:
            messagebox.showerror("Firmalar", str(hata), parent=app)

    def secili():
        s = tablo.selection()
        return int(s[0]) if s else None

    def yeni():
        dlg = SistemFirmaDialog(app)
        app.wait_window(dlg)
        if dlg.result:
            yenile()

    def duzenle():
        cid = secili()
        if not cid:
            messagebox.showinfo("Seçim", "Firma seçin.", parent=app)
            return
        dlg = SistemFirmaDialog(app, company_id=cid)
        app.wait_window(dlg)
        if dlg.result:
            yenile()

    def pasif():
        cid = secili()
        if not cid:
            return
        if messagebox.askyesno("Pasife al", "Firma pasife alınsın mı?", parent=app):
            try:
                CompanyMgmtService.pasife_al(cid)
                yenile()
            except Exception as hata:
                messagebox.showerror("İşlem", str(hata), parent=app)

    def yedek():
        cid = secili()
        if not cid:
            return
        klasor = filedialog.askdirectory(parent=app, title="Yedek klasörü")
        if not klasor:
            return
        try:
            yol = CompanyMgmtService.yedek_al(cid, klasor)
            messagebox.showinfo("Yedek", f"Yedek alındı:\n{yol}", parent=app)
        except Exception as hata:
            messagebox.showerror("Yedek", str(hata), parent=app)

    ttk.Button(ust, text="Ara", command=yenile).pack(side="left")
    ttk.Button(ust, text="Yeni Firma", command=yeni).pack(side="right")
    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x")
    ttk.Button(alt, text="Düzenle", command=duzenle).pack(side="left")
    ttk.Button(alt, text="Pasife Al", command=pasif).pack(side="left", padx=6)
    ttk.Button(alt, text="Yedek Al", command=yedek).pack(side="left")
    arama.bind("<Return>", lambda _e: yenile())
    yenile()


class SistemFirmaDialog(tk.Toplevel):
    def __init__(self, parent, company_id: int | None = None):
        super().__init__(parent)
        self.title("Firma Kartı")
        self.result = False
        self.company_id = company_id
        self.transient(parent)
        self.grab_set()
        self.geometry("560x560")
        mevcut = CompanyMgmtService.getir(company_id) if company_id else None

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)
        self.alanlar = {}
        alanlar = (
            ("Firma kodu", "firma_kodu"),
            ("Ticari unvan", "unvan"),
            ("Kısa ad", "kisa_ad"),
            ("Vergi dairesi", "vergi_dairesi"),
            ("Vergi / TC No", "vergi_no"),
            ("Telefon", "telefon"),
            ("E-posta", "email"),
            ("İnternet", "internet"),
            ("Adres", "adres"),
            ("İl", "il"),
            ("İlçe", "ilce"),
            ("Fatura seri", "fatura_seri"),
        )
        for i, (etiket, anahtar) in enumerate(alanlar):
            ttk.Label(frm, text=etiket + ":").grid(row=i, column=0, sticky="w", pady=3)
            e = ttk.Entry(frm, width=40)
            e.grid(row=i, column=1, sticky="ew", pady=3)
            if mevcut:
                e.insert(0, mevcut.get(anahtar) or "")
            self.alanlar[anahtar] = e

        r = len(alanlar)
        ttk.Label(frm, text="Para birimi:").grid(row=r, column=0, sticky="w", pady=3)
        self.pb = ttk.Combobox(frm, values=("TRY", "USD", "EUR"), state="readonly", width=8)
        self.pb.set((mevcut or {}).get("varsayilan_para_birimi") or "TRY")
        self.pb.grid(row=r, column=1, sticky="w", pady=3)
        r += 1
        self.aktif = tk.BooleanVar(value=True if not mevcut else mevcut["aktif"])
        ttk.Checkbutton(frm, text="Aktif", variable=self.aktif).grid(row=r, column=1, sticky="w")
        r += 1
        if mevcut:
            ttk.Label(frm, text=f"DB: {mevcut.get('db_path') or ''}", wraplength=400).grid(
                row=r, column=0, columnspan=2, sticky="w", pady=6
            )
            r += 1

        butonlar = ttk.Frame(frm)
        butonlar.grid(row=r, column=0, columnspan=2, sticky="e", pady=12)
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(butonlar, text="Kaydet", command=self._kaydet).pack(side="left")

    def _kaydet(self):
        try:
            veriler = {k: w.get() for k, w in self.alanlar.items()}
            veriler["varsayilan_para_birimi"] = self.pb.get() or "TRY"
            veriler["aktif"] = self.aktif.get()
            if not veriler["firma_kodu"].strip() or not veriler["unvan"].strip():
                raise ValueError("Firma kodu ve unvan zorunludur.")
            if self.company_id is None:
                CompanyMgmtService.ekle(veriler)
                messagebox.showinfo(
                    "Firma",
                    "Firma ve veritabanı oluşturuldu.",
                    parent=self,
                )
            else:
                CompanyMgmtService.guncelle(self.company_id, veriler)
            self.result = True
            self.destroy()
        except Exception as hata:
            messagebox.showerror("Kayıt", str(hata), parent=self)


# ── Roller ────────────────────────────────────────────────────

def roller_goster(app) -> None:
    _sistem_baslik(app, "ROLLER VE YETKİLER")
    ust = ttk.Frame(app.icerik)
    ust.pack(fill="both", expand=True)

    sol = ttk.Frame(ust)
    sol.pack(side="left", fill="y", padx=(0, 12))
    ttk.Label(sol, text="Roller").pack(anchor="w")
    rol_liste = tk.Listbox(sol, height=18, width=28, exportselection=False)
    rol_liste.pack(fill="y")

    sag = ttk.Frame(ust)
    sag.pack(side="left", fill="both", expand=True)
    ttk.Label(sag, text="İzinler (işaretle / kaldır)").pack(anchor="w")
    canvas = tk.Canvas(sag, highlightthickness=0)
    scroll = ttk.Scrollbar(sag, orient="vertical", command=canvas.yview)
    ic = ttk.Frame(canvas)
    ic.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=ic, anchor="nw")
    canvas.configure(yscrollcommand=scroll.set)
    canvas.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    roller = RoleService.roller()
    izinler = RoleService.izinler()
    self_vars: dict[int, tk.BooleanVar] = {}
    for p in izinler:
        var = tk.BooleanVar(value=False)
        self_vars[p["id"]] = var
        ttk.Checkbutton(
            ic, text=f"{p['ad']} ({p['kod']}) — {p['modul'] or '-'}", variable=var
        ).pack(anchor="w")

    rol_map = []
    for r in roller:
        rol_map.append(r)
        rol_liste.insert("end", f"{r['ad']} ({r['kod']})")

    def rol_sec(_evt=None):
        sec = rol_liste.curselection()
        if not sec:
            return
        r = rol_map[sec[0]]
        izin_set = set(r["izin_idler"])
        for pid, var in self_vars.items():
            var.set(pid in izin_set)

    def kaydet():
        sec = rol_liste.curselection()
        if not sec:
            messagebox.showinfo("Rol", "Rol seçin.", parent=app)
            return
        r = rol_map[sec[0]]
        idler = [pid for pid, var in self_vars.items() if var.get()]
        try:
            RoleService.rol_izinlerini_kaydet(r["id"], idler)
            # Yerel cache güncelle
            r["izin_idler"] = idler
            messagebox.showinfo("Rol", "Yetkiler kaydedildi.", parent=app)
        except Exception as hata:
            messagebox.showerror("Rol", str(hata), parent=app)

    rol_liste.bind("<<ListboxSelect>>", rol_sec)
    ttk.Button(app.icerik, text="Seçili Rolün Yetkilerini Kaydet", command=kaydet).pack(
        anchor="e", pady=8
    )
    if rol_map:
        rol_liste.selection_set(0)
        rol_sec()


# ── Dönemler ──────────────────────────────────────────────────

def donemler_yonet_goster(app) -> None:
    _sistem_baslik(app, "ÇALIŞMA DÖNEMLERİ")
    ttk.Label(
        app.icerik,
        text=f"Aktif firma: {oturum.firma_unvan or '—'}",
        foreground="#555",
    ).pack(anchor="w")

    tablo = ttk.Treeview(
        app.icerik,
        columns=("ad", "bas", "bit", "aktif", "kapali", "vars"),
        show="headings",
        height=12,
    )
    for k, b, w in (
        ("ad", "Dönem", 80),
        ("bas", "Başlangıç", 100),
        ("bit", "Bitiş", 100),
        ("aktif", "Aktif", 60),
        ("kapali", "Durum", 80),
        ("vars", "Varsayılan", 80),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="center")
    tablo.pack(fill="both", expand=True, pady=8)

    def yenile():
        for i in tablo.get_children():
            tablo.delete(i)
        for d in DonemService.listele():
            tablo.insert(
                "", "end", iid=str(d["id"]),
                values=(
                    d["donem_adi"],
                    _tarih_goster(d["baslangic_tarihi"]),
                    _tarih_goster(d["bitis_tarihi"]),
                    "Evet" if d["aktif"] else "Hayır",
                    "Kapalı" if d["kapali"] else "Açık",
                    "Evet" if d["varsayilan"] else "",
                ),
            )

    def secili():
        s = tablo.selection()
        return int(s[0]) if s else None

    def yeni():
        dlg = DonemDialog(app)
        app.wait_window(dlg)
        if dlg.result:
            yenile()
            app._oturum_cubugunu_guncelle()

    def duzenle():
        did = secili()
        if not did:
            return
        dlg = DonemDialog(app, donem_id=did)
        app.wait_window(dlg)
        if dlg.result:
            yenile()

    def kapat():
        did = secili()
        if not did:
            return
        try:
            DonemService.kapat_ac(did, True)
            yenile()
        except Exception as hata:
            messagebox.showerror("Dönem", str(hata), parent=app)

    def ac():
        did = secili()
        if not did:
            return
        try:
            DonemService.kapat_ac(did, False)
            yenile()
        except Exception as hata:
            messagebox.showerror("Dönem", str(hata), parent=app)

    def varsayilan():
        did = secili()
        if not did:
            return
        try:
            DonemService.varsayilan_yap(did)
            yenile()
            app._oturum_cubugunu_guncelle()
        except Exception as hata:
            messagebox.showerror("Dönem", str(hata), parent=app)

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x")
    ttk.Button(alt, text="Yeni Dönem", command=yeni).pack(side="left")
    ttk.Button(alt, text="Düzenle", command=duzenle).pack(side="left", padx=6)
    ttk.Button(alt, text="Kapat", command=kapat).pack(side="left")
    ttk.Button(alt, text="Aç", command=ac).pack(side="left", padx=6)
    ttk.Button(alt, text="Varsayılan Yap", command=varsayilan).pack(side="left")
    yenile()


class DonemDialog(tk.Toplevel):
    def __init__(self, parent, donem_id: int | None = None):
        super().__init__(parent)
        self.title("Dönem Kartı")
        self.result = False
        self.donem_id = donem_id
        self.transient(parent)
        self.grab_set()
        mevcut = None
        if donem_id:
            for d in DonemService.listele():
                if d["id"] == donem_id:
                    mevcut = d
                    break

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Dönem adı:").grid(row=0, column=0, sticky="w", pady=4)
        self.ad = ttk.Entry(frm, width=20)
        self.ad.grid(row=0, column=1, sticky="w", pady=4)
        self.ad.insert(0, (mevcut or {}).get("donem_adi") or str(date.today().year))

        ttk.Label(frm, text="Başlangıç:").grid(row=1, column=0, sticky="w", pady=4)
        bas_f = ttk.Frame(frm)
        bas_f.grid(row=1, column=1, sticky="w")
        self.bas = ttk.Entry(bas_f, width=12)
        self.bas.pack(side="left")
        takvim_butonu(bas_f, self.bas)
        b = (mevcut or {}).get("baslangic_tarihi") or date(date.today().year, 1, 1)
        self.bas.insert(0, b.strftime("%d.%m.%Y") if isinstance(b, date) else str(b))

        ttk.Label(frm, text="Bitiş:").grid(row=2, column=0, sticky="w", pady=4)
        bit_f = ttk.Frame(frm)
        bit_f.grid(row=2, column=1, sticky="w")
        self.bit = ttk.Entry(bit_f, width=12)
        self.bit.pack(side="left")
        takvim_butonu(bit_f, self.bit)
        e = (mevcut or {}).get("bitis_tarihi") or date(date.today().year, 12, 31)
        self.bit.insert(0, e.strftime("%d.%m.%Y") if isinstance(e, date) else str(e))

        self.aktif = tk.BooleanVar(value=True if not mevcut else mevcut["aktif"])
        self.kapali = tk.BooleanVar(value=False if not mevcut else mevcut["kapali"])
        self.varsayilan = tk.BooleanVar(value=False if not mevcut else mevcut["varsayilan"])
        ttk.Checkbutton(frm, text="Aktif", variable=self.aktif).grid(row=3, column=1, sticky="w")
        ttk.Checkbutton(frm, text="Kapalı", variable=self.kapali).grid(row=4, column=1, sticky="w")
        ttk.Checkbutton(frm, text="Varsayılan", variable=self.varsayilan).grid(
            row=5, column=1, sticky="w"
        )

        butonlar = ttk.Frame(frm)
        butonlar.grid(row=6, column=0, columnspan=2, sticky="e", pady=12)
        ttk.Button(butonlar, text="İptal", command=self.destroy).pack(side="left", padx=6)
        ttk.Button(butonlar, text="Kaydet", command=self._kaydet).pack(side="left")

    def _parse(self, metin: str) -> date:
        return datetime.strptime(metin.strip(), "%d.%m.%Y").date()

    def _kaydet(self):
        try:
            veriler = {
                "donem_adi": self.ad.get().strip(),
                "baslangic_tarihi": self._parse(self.bas.get()),
                "bitis_tarihi": self._parse(self.bit.get()),
                "aktif": self.aktif.get(),
                "kapali": self.kapali.get(),
                "varsayilan": self.varsayilan.get(),
            }
            if not veriler["donem_adi"]:
                raise ValueError("Dönem adı zorunlu.")
            if self.donem_id is None:
                DonemService.ekle(veriler)
            else:
                DonemService.guncelle(self.donem_id, veriler)
            if veriler["varsayilan"]:
                # oturum güncelle
                for d in DonemService.listele():
                    if d["varsayilan"]:
                        oturum.set_period(d["id"], d["donem_adi"])
                        break
            self.result = True
            self.destroy()
        except Exception as hata:
            messagebox.showerror("Dönem", str(hata), parent=self)


# ── Audit / Yedek ─────────────────────────────────────────────

def audit_goster(app) -> None:
    _sistem_baslik(app, "İŞLEM KAYITLARI")
    tablo = ttk.Treeview(
        app.icerik,
        columns=("tarih", "islem", "modul", "kayit", "pc"),
        show="headings",
        height=18,
    )
    for k, b, w in (
        ("tarih", "Tarih", 140),
        ("islem", "İşlem", 120),
        ("modul", "Modül", 90),
        ("kayit", "Kayıt", 80),
        ("pc", "Bilgisayar", 120),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w)
    tablo.pack(fill="both", expand=True, pady=8)

    with get_system_session() as session:
        kayitlar = session.scalars(
            select(AuditLog).order_by(AuditLog.id.desc()).limit(300)
        ).all()
        for a in kayitlar:
            tablo.insert(
                "", "end",
                values=(
                    _tarih_goster(a.tarih),
                    a.islem_turu,
                    a.modul or "",
                    a.kayit_id or "",
                    a.bilgisayar or "",
                ),
            )

    ttk.Label(app.icerik, text="Son 300 kayıt (parola/hassas veri yazılmaz).").pack(anchor="w")


def yedekleme_goster(app) -> None:
    _sistem_baslik(app, "VERİTABANI YEDEKLEME")
    ttk.Label(
        app.icerik,
        text="Aktif firmanın operasyon veritabanının kopyasını alır.",
    ).pack(anchor="w", pady=(0, 12))

    def yedekle():
        if not oturum.company_id:
            messagebox.showwarning("Yedek", "Aktif firma yok.", parent=app)
            return
        klasor = filedialog.askdirectory(parent=app, title="Yedek klasörü seçin")
        if not klasor:
            return
        try:
            yol = CompanyMgmtService.yedek_al(oturum.company_id, klasor)
            messagebox.showinfo("Yedek", f"Yedek alındı:\n{yol}", parent=app)
        except Exception as hata:
            messagebox.showerror("Yedek", str(hata), parent=app)

    ttk.Button(app.icerik, text="Aktif Firma Yedeğini Al", command=yedekle).pack(anchor="w")


def gecis_dogrulama_goster(app) -> None:
    """AŞAMA 6 — Ray Mobilya bağlama + sayısal doğrulama ekranı."""
    from database.database import DB_PATH, get_system_session
    from database.system.gecis import canli_dogrulama, gecis_calistir

    _sistem_baslik(app, "GEÇİŞ DOĞRULAMA")
    ttk.Label(
        app.icerik,
        text="Mevcut muhasebe.db, Ray Mobilya firmasına bağlandı. Veri taşınmaz; yedek + sayım ile doğrulanır.",
        wraplength=700,
    ).pack(anchor="w", pady=(0, 10))

    bilgi_frame = ttk.LabelFrame(app.icerik, text="Durum", padding=10)
    bilgi_frame.pack(fill="x", pady=6)
    ozet = ttk.Label(bilgi_frame, text="Yükleniyor…", justify="left")
    ozet.pack(anchor="w")

    tablo = ttk.Treeview(
        app.icerik,
        columns=("tablo", "once", "simdi", "fark"),
        show="headings",
        height=12,
    )
    for k, b, w in (
        ("tablo", "Tablo", 200),
        ("once", "Snapshot", 90),
        ("simdi", "Şimdi", 90),
        ("fark", "Fark", 70),
    ):
        tablo.heading(k, text=b)
        tablo.column(k, width=w, anchor="center" if k != "tablo" else "w")
    tablo.pack(fill="both", expand=True, pady=8)

    def yenile():
        for i in tablo.get_children():
            tablo.delete(i)
        try:
            with get_system_session() as session:
                rapor = canli_dogrulama(DB_PATH, session)
            durum = rapor["durum"]
            guncel = rapor["guncel"]
            kars = rapor.get("karsilastirma")
            satirlar = [
                f"Geçiş tamam: {'Evet' if durum.get('tamam') else 'Hayır'}",
                f"Ray firma: {durum.get('ray_unvan') or '—'} (id={durum.get('ray_firma_id')})",
                f"DB yolu eşleşiyor: {'Evet' if rapor.get('ray_db_eslesiyor') else 'HAYIR'}",
                f"Yedek: {durum.get('yedek_yolu') or '—'}",
                f"DB boyut: {guncel.get('db_boyut_byte', 0):,} bayt",
            ]
            if kars:
                satirlar.append(
                    f"Sayısal uyum (snapshot↔şimdi): "
                    f"{'Uyumlu' if kars.get('uyumlu') else 'Fark var (normal işlem sonrası olabilir)'}"
                )
            ozet.configure(text="\n".join(satirlar))

            if kars and kars.get("sayim"):
                for tablo_adi, bil in kars["sayim"].items():
                    tablo.insert(
                        "",
                        "end",
                        values=(
                            tablo_adi,
                            bil.get("once"),
                            bil.get("sonra"),
                            bil.get("fark"),
                        ),
                    )
            else:
                for tablo_adi, n in (guncel.get("sayimlar") or {}).items():
                    tablo.insert("", "end", values=(tablo_adi, "—", n, "—"))
        except Exception as hata:
            ozet.configure(text=str(hata))
            messagebox.showerror("Doğrulama", str(hata), parent=app)

    def yeniden_yedek_dogrula():
        try:
            with get_system_session() as session:
                bil = gecis_calistir(
                    session, muhasebe_db_path=DB_PATH, zorla_yedek=True
                )
            messagebox.showinfo(
                "Geçiş",
                "\n".join(bil.get("mesajlar") or ["Tamam"]),
                parent=app,
            )
            yenile()
        except Exception as hata:
            messagebox.showerror("Geçiş", str(hata), parent=app)

    alt = ttk.Frame(app.icerik)
    alt.pack(fill="x")
    ttk.Button(alt, text="Yenile", command=yenile).pack(side="left")
    ttk.Button(
        alt, text="Yedek Al + Doğrula", command=yeniden_yedek_dogrula
    ).pack(side="left", padx=8)
    yenile()
