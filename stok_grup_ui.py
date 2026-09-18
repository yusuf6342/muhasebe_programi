"""Stok Grubu Yönetimi — üç seviyeli ağaç + Yeni Grup diyaloğu."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from database.stok_grup_service import (
    SEVIYE_ALT,
    SEVIYE_ANA,
    SEVIYE_TALI,
    SEVIYE_ADLARI,
    StokGrupService,
)
from satis_tema import (
    ACIK_BG,
    BEYAZ,
    CIZGI,
    IKINCIL,
    LACIVERT,
    SARI,
    font,
    hub_ust_baslik,
    stil_uygula,
    tk_buton,
)


def _etiket(g: dict) -> str:
    return g.get("etiket") or f"{g.get('kod', '')} — {g.get('ad', '')}"


class StokGrupDialog(tk.Toplevel):
    """Yeni / düzenle grup diyaloğu."""

    def __init__(
        self,
        parent,
        *,
        seviye: int = SEVIYE_ANA,
        parent_id: int | None = None,
        duzenle: dict | None = None,
    ):
        super().__init__(parent)
        self.result = None
        self._kaydediliyor = False
        self.duzenle = duzenle
        self.title("Grup Düzenle" if duzenle else "Yeni Stok Grubu")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.geometry("460x360")

        fr = ttk.Frame(self, padding=14)
        fr.pack(fill="both", expand=True)

        ttk.Label(fr, text="Grup Seviyesi *").grid(row=0, column=0, sticky="w", pady=4)
        self.seviye_var = tk.StringVar(value=SEVIYE_ADLARI.get(int(seviye), "Ana Grup"))
        self.seviye_cb = ttk.Combobox(
            fr,
            textvariable=self.seviye_var,
            values=list(SEVIYE_ADLARI.values()),
            state="readonly" if duzenle else "readonly",
            width=28,
        )
        self.seviye_cb.grid(row=0, column=1, sticky="ew", pady=4)
        if not duzenle:
            self.seviye_cb.bind("<<ComboboxSelected>>", lambda _e: self._seviye_degisti())

        ttk.Label(fr, text="Grup Kodu *").grid(row=1, column=0, sticky="w", pady=4)
        self.kod = ttk.Entry(fr, width=30)
        self.kod.grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(fr, text="Grup Adı *").grid(row=2, column=0, sticky="w", pady=4)
        self.ad = ttk.Entry(fr, width=30)
        self.ad.grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(fr, text="Üst Grup").grid(row=3, column=0, sticky="w", pady=4)
        self.ust_cb = ttk.Combobox(fr, width=28)
        self.ust_cb.grid(row=3, column=1, sticky="ew", pady=4)
        self._ust_map: dict[str, int] = {}

        ttk.Label(fr, text="Açıklama").grid(row=4, column=0, sticky="nw", pady=4)
        self.aciklama = tk.Text(fr, width=30, height=3)
        self.aciklama.grid(row=4, column=1, sticky="ew", pady=4)

        ttk.Label(fr, text="Sıra No").grid(row=5, column=0, sticky="w", pady=4)
        self.sira = ttk.Entry(fr, width=10)
        self.sira.insert(0, "0")
        self.sira.grid(row=5, column=1, sticky="w", pady=4)

        self.aktif = tk.BooleanVar(value=True)
        ttk.Checkbutton(fr, text="Aktif", variable=self.aktif).grid(
            row=6, column=1, sticky="w", pady=2
        )

        alt = ttk.Frame(fr)
        alt.grid(row=7, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(alt, text="İptal", command=self.destroy).pack(side="right")
        self._kaydet_btn = ttk.Button(alt, text="Kaydet", command=self._kaydet)
        self._kaydet_btn.pack(side="right", padx=(0, 8))

        if duzenle:
            self.kod.insert(0, duzenle.get("kod") or "")
            self.ad.insert(0, duzenle.get("ad") or "")
            self.aciklama.insert("1.0", duzenle.get("aciklama") or "")
            self.sira.delete(0, "end")
            self.sira.insert(0, str(duzenle.get("sira_no") or 0))
            self.aktif.set(bool(duzenle.get("aktif", True)))
            self.seviye_cb.configure(state="disabled")
            self.ust_cb.configure(state="disabled")
        else:
            self._baslangic_seviye = int(seviye)
            self._baslangic_parent = parent_id
            self._seviye_degisti(secili_parent=parent_id)

        self.kod.focus_set()
        self.bind("<Return>", lambda _e: self._kaydet())
        self.bind("<Escape>", lambda _e: self.destroy())

    def _seviye_no(self) -> int:
        ad = self.seviye_var.get()
        for k, v in SEVIYE_ADLARI.items():
            if v == ad:
                return k
        return SEVIYE_ANA

    def _seviye_degisti(self, secili_parent: int | None = None):
        seviye = self._seviye_no()
        self._ust_map.clear()
        if seviye == SEVIYE_ANA:
            self.ust_cb.configure(values=[], state="disabled")
            self.ust_cb.set("")
            return
        hedef = SEVIYE_ANA if seviye == SEVIYE_TALI else SEVIYE_TALI
        try:
            liste = StokGrupService.listele(seviye=hedef, aktif_only=True)
        except Exception as exc:
            messagebox.showerror("Grup", str(exc), parent=self)
            return
        degerler = []
        for g in liste:
            et = _etiket(g)
            degerler.append(et)
            self._ust_map[et] = g["id"]
        self.ust_cb.configure(values=degerler, state="readonly")
        if secili_parent:
            for et, gid in self._ust_map.items():
                if gid == secili_parent:
                    self.ust_cb.set(et)
                    break
        elif degerler:
            self.ust_cb.set(degerler[0])

    def _kaydet(self):
        if self._kaydediliyor:
            return
        self._kaydediliyor = True
        self._kaydet_btn.configure(state="disabled")
        try:
            if self.duzenle:
                self.result = StokGrupService.guncelle(
                    int(self.duzenle["id"]),
                    kod=self.kod.get(),
                    ad=self.ad.get(),
                    aciklama=self.aciklama.get("1.0", "end").strip(),
                    sira_no=int(self.sira.get().strip() or 0),
                    aktif=bool(self.aktif.get()),
                )
            else:
                seviye = self._seviye_no()
                parent_id = None
                if seviye != SEVIYE_ANA:
                    et = self.ust_cb.get().strip()
                    parent_id = self._ust_map.get(et)
                    if not parent_id:
                        raise ValueError("Üst grup seçimi zorunludur.")
                self.result = StokGrupService.ekle(
                    seviye=seviye,
                    kod=self.kod.get(),
                    ad=self.ad.get(),
                    parent_id=parent_id,
                    aciklama=self.aciklama.get("1.0", "end").strip(),
                    sira_no=int(self.sira.get().strip() or 0),
                    aktif=bool(self.aktif.get()),
                )
            self.destroy()
        except Exception as exc:
            messagebox.showerror("Grup", str(exc), parent=self)
            self._kaydediliyor = False
            self._kaydet_btn.configure(state="normal")


class StokGrupTopluTasiDialog(tk.Toplevel):
    def __init__(self, parent, kaynak_grup: dict):
        super().__init__(parent)
        self.result = None
        self.kaynak = kaynak_grup
        self.title("Toplu Stok Taşıma")
        self.geometry("640x480")
        self.transient(parent)
        self.grab_set()

        fr = ttk.Frame(self, padding=12)
        fr.pack(fill="both", expand=True)
        ttk.Label(
            fr,
            text=f"Kaynak: {kaynak_grup.get('yol') or _etiket(kaynak_grup)}",
        ).pack(anchor="w")

        ttk.Label(fr, text="Hedef grup (aynı veya uyumlu seviye)").pack(anchor="w", pady=(8, 2))
        self.hedef_cb = ttk.Combobox(fr, width=60)
        self.hedef_cb.pack(fill="x")
        self._hedef_map = {}
        try:
            agac = StokGrupService.agac(aktif_only=True)
            flat = []

            def walk(nodes, prefix=""):
                for n in nodes:
                    flat.append(n)
                    walk(n.get("cocuklar") or [], prefix)

            walk(agac)
            degerler = []
            for g in flat:
                if g["id"] == kaynak_grup["id"]:
                    continue
                et = f"{g.get('yol') or _etiket(g)}  [{g.get('seviye_adi')}]"
                degerler.append(et)
                self._hedef_map[et] = g
            self.hedef_cb.configure(values=degerler)
            if degerler:
                self.hedef_cb.set(degerler[0])
        except Exception as exc:
            messagebox.showerror("Taşıma", str(exc), parent=self)

        ttk.Label(fr, text="Taşınacak stoklar").pack(anchor="w", pady=(10, 2))
        self.lb = tk.Listbox(fr, selectmode="extended", height=14)
        self.lb.pack(fill="both", expand=True)
        self._stok_idler = []
        try:
            from database.database import get_session
            from database.models.stok import StokKarti
            from sqlalchemy import or_, select

            kolon = {
                SEVIYE_ANA: StokKarti.ana_grup_id,
                SEVIYE_TALI: StokKarti.tali_grup_id,
                SEVIYE_ALT: StokKarti.alt_grup_id,
            }[int(kaynak_grup["seviye"])]
            with get_session() as s:
                stoklar = list(
                    s.scalars(
                        select(StokKarti)
                        .where(
                            kolon == int(kaynak_grup["id"]),
                            or_(StokKarti.is_deleted.is_(False), StokKarti.is_deleted.is_(None)),
                        )
                        .order_by(StokKarti.stok_adi)
                    ).all()
                )
                for st in stoklar:
                    self._stok_idler.append(st.id)
                    self.lb.insert("end", f"{st.stok_kodu} — {st.stok_adi}")
                    self.lb.selection_set("end")
        except Exception as exc:
            messagebox.showerror("Taşıma", str(exc), parent=self)

        btn = ttk.Frame(fr)
        btn.pack(fill="x", pady=(8, 0))
        ttk.Button(btn, text="Tümünü Seç", command=lambda: self.lb.selection_set(0, "end")).pack(
            side="left"
        )
        ttk.Button(btn, text="İptal", command=self.destroy).pack(side="right")
        ttk.Button(btn, text="Taşı", command=self._tasi).pack(side="right", padx=(0, 8))

    def _tasi(self):
        et = self.hedef_cb.get().strip()
        hedef = self._hedef_map.get(et)
        if not hedef:
            messagebox.showwarning("Taşıma", "Hedef grup seçin.", parent=self)
            return
        sec = list(self.lb.curselection())
        if not sec:
            messagebox.showwarning("Taşıma", "En az bir stok seçin.", parent=self)
            return
        idler = [self._stok_idler[i] for i in sec]
        if not messagebox.askyesno(
            "Onay",
            f"{len(idler)} stok «{hedef.get('yol') or hedef.get('ad')}» grubuna taşınsın mı?",
            parent=self,
        ):
            return
        try:
            # Hedef seviyesine göre id ata
            ana_id = tali_id = alt_id = None
            sev = int(hedef["seviye"])
            if sev == SEVIYE_ANA:
                ana_id = hedef["id"]
            elif sev == SEVIYE_TALI:
                tali_id = hedef["id"]
                ana_id = hedef.get("parent_id")
            else:
                alt_id = hedef["id"]
                tali_id = hedef.get("parent_id")
                if tali_id:
                    ust = StokGrupService.getir(tali_id)
                    ana_id = ust.get("parent_id") if ust else None
            self.result = StokGrupService.stoklara_ata(
                idler, ana_id=ana_id, tali_id=tali_id, alt_id=alt_id
            )
            messagebox.showinfo(
                "Taşıma",
                f"{self.result.get('adet', 0)} stok taşındı.",
                parent=self,
            )
            self.destroy()
        except Exception as exc:
            messagebox.showerror("Taşıma", str(exc), parent=self)


def stok_grup_yonetimi_goster(app) -> None:
    app._icerigi_temizle()
    stil_uygula(root=app)
    try:
        app.icerik.configure(bg=ACIK_BG)
    except tk.TclError:
        pass
    for anahtar, dugme in getattr(app, "menu_dugmeleri", {}).items():
        dugme.configure(
            style="SeciliMenu.TButton" if anahtar == "stoklar" else "Menu.TButton"
        )

    kok = tk.Frame(app.icerik, bg=ACIK_BG)
    kok.pack(fill="both", expand=True)
    hub_ust_baslik(
        kok,
        baslik="STOK GRUBU YÖNETİMİ",
        alt_baslik="Ana Grup → Tali Grup → Alt Grup",
        app=app,
        geri_komut=lambda: app.sayfa_goster("stoklar"),
        geri_metin="← Stoklar",
    )

    ust = tk.Frame(kok, bg=ACIK_BG)
    ust.pack(fill="x", padx=16, pady=(8, 4))
    tk.Label(ust, text="Ara", bg=ACIK_BG, fg=IKINCIL).pack(side="left")
    arama = ttk.Entry(ust, width=28)
    arama.pack(side="left", padx=(6, 10))
    tk_buton(ust, "Yenile", lambda: _yenile(), rol="ara").pack(side="left")
    tk_buton(ust, "Yeni Ana Grup", lambda: _yeni(SEVIYE_ANA), rol="yeni").pack(
        side="left", padx=(12, 0)
    )
    tk_buton(ust, "Yeni Tali Grup", lambda: _yeni(SEVIYE_TALI), rol="yeni").pack(
        side="left", padx=(6, 0)
    )
    tk_buton(ust, "Yeni Alt Grup", lambda: _yeni(SEVIYE_ALT), rol="yeni").pack(
        side="left", padx=(6, 0)
    )
    tk_buton(ust, "Düzenle", lambda: _duzenle(), rol="ikincil").pack(side="left", padx=(12, 0))
    tk_buton(ust, "Taşı", lambda: _tasi_grup(), rol="ikincil").pack(side="left", padx=(6, 0))
    tk_buton(ust, "Pasife Al", lambda: _pasife(), rol="ikincil").pack(side="left", padx=(6, 0))
    tk_buton(ust, "Sil", lambda: _sil(), rol="tehlike").pack(side="left", padx=(6, 0))
    tk_buton(ust, "Toplu Stok Ata", lambda: _toplu_eslestir_ac(), rol="kaydet").pack(
        side="left", padx=(12, 0)
    )
    tk_buton(ust, "Toplu Stok Taşı", lambda: _toplu_stok(), rol="ikincil").pack(
        side="left", padx=(6, 0)
    )

    govde = tk.Frame(kok, bg=ACIK_BG)
    govde.pack(fill="both", expand=True, padx=16, pady=8)
    govde.columnconfigure(0, weight=3)
    govde.columnconfigure(1, weight=2)
    govde.rowconfigure(0, weight=1)

    sol = tk.Frame(govde, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
    sol.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    tree = ttk.Treeview(sol, columns=("kod", "durum", "stok"), show="tree headings", selectmode="browse")
    tree.heading("#0", text="Grup")
    tree.heading("kod", text="Kod")
    tree.heading("durum", text="Durum")
    tree.heading("stok", text="Stok")
    tree.column("#0", width=280)
    tree.column("kod", width=90)
    tree.column("durum", width=70)
    tree.column("stok", width=60, anchor="e")
    sy = ttk.Scrollbar(sol, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sy.set)
    tree.pack(side="left", fill="both", expand=True)
    sy.pack(side="right", fill="y")
    tree.tag_configure("ana", font=font(10, "bold", app))
    tree.tag_configure("tali", font=font(10, root=app))
    tree.tag_configure("alt", font=font(9, root=app))
    tree.tag_configure("pasif", foreground="#90A4AE")

    sag = tk.Frame(govde, bg=BEYAZ, highlightthickness=1, highlightbackground=CIZGI)
    sag.grid(row=0, column=1, sticky="nsew")
    detay = tk.Label(
        sag,
        text="Bir grup seçin.",
        bg=BEYAZ,
        fg=LACIVERT,
        font=font(10, root=app),
        justify="left",
        anchor="nw",
        wraplength=360,
    )
    detay.pack(fill="both", expand=True, padx=12, pady=12)

    id_map: dict[str, dict] = {}

    def _yenile():
        for i in tree.get_children():
            tree.delete(i)
        id_map.clear()
        try:
            agac = StokGrupService.agac(aktif_only=False, arama=arama.get().strip())
        except Exception as exc:
            messagebox.showerror("Grup", str(exc), parent=app)
            return

        def ekle(nodes, parent=""):
            for n in nodes:
                tag = "ana" if n["seviye"] == 1 else ("tali" if n["seviye"] == 2 else "alt")
                tags = [tag]
                if not n.get("aktif"):
                    tags.append("pasif")
                iid = str(n["id"])
                id_map[iid] = n
                girinti = "    " if n["seviye"] == 3 else ("  " if n["seviye"] == 2 else "")
                tree.insert(
                    parent,
                    "end",
                    iid=iid,
                    text=f"{girinti}{n.get('ad') or ''}",
                    values=(
                        n.get("kod") or "",
                        "Aktif" if n.get("aktif") else "Pasif",
                        n.get("stok_adet") if n.get("stok_adet") is not None else "",
                    ),
                    tags=tuple(tags),
                    open=True,
                )
                ekle(n.get("cocuklar") or [], iid)

        ekle(agac)

    def _secili() -> dict | None:
        sec = tree.selection()
        if not sec:
            return None
        return id_map.get(sec[0])

    def _detay_goster(_e=None):
        g = _secili()
        if not g:
            detay.configure(text="Bir grup seçin.")
            return
        try:
            d = StokGrupService.detay(g["id"])
        except Exception as exc:
            detay.configure(text=str(exc))
            return
        ust = d.get("ust_grup")
        metin = (
            f"Kod: {d.get('kod')}\n"
            f"Ad: {d.get('ad')}\n"
            f"Seviye: {d.get('seviye_adi')}\n"
            f"Üst: {(ust or {}).get('ad') if ust else '—'}\n"
            f"Yol: {d.get('yol')}\n"
            f"Açıklama: {d.get('aciklama') or '—'}\n"
            f"Aktif: {'Evet' if d.get('aktif') else 'Hayır'}\n"
            f"Alt grup sayısı: {d.get('cocuk_adet')}\n"
            f"Bağlı stok: {d.get('stok_adet')}\n"
            f"Sıra: {d.get('sira_no')}"
        )
        detay.configure(text=metin)

    def _yeni(seviye: int):
        parent_id = None
        g = _secili()
        if seviye == SEVIYE_TALI and g and g["seviye"] == SEVIYE_ANA:
            parent_id = g["id"]
        elif seviye == SEVIYE_ALT and g and g["seviye"] == SEVIYE_TALI:
            parent_id = g["id"]
        elif seviye == SEVIYE_ALT and g and g["seviye"] == SEVIYE_ANA:
            # ana seçiliyken alt açılamaz — kullanıcı tali seçmeli
            pass
        dlg = StokGrupDialog(app, seviye=seviye, parent_id=parent_id)
        app.wait_window(dlg)
        if dlg.result:
            _yenile()
            tree.selection_set(str(dlg.result["id"]))
            tree.see(str(dlg.result["id"]))
            _detay_goster()

    def _duzenle():
        g = _secili()
        if not g:
            messagebox.showinfo("Grup", "Düzenlemek için grup seçin.", parent=app)
            return
        dlg = StokGrupDialog(app, seviye=g["seviye"], duzenle=g)
        app.wait_window(dlg)
        if dlg.result:
            _yenile()

    def _tasi_grup():
        g = _secili()
        if not g:
            messagebox.showinfo("Taşı", "Taşınacak grubu seçin.", parent=app)
            return
        if int(g["seviye"]) == SEVIYE_ANA:
            messagebox.showwarning("Taşı", "Ana grup taşınamaz.", parent=app)
            return
        hedef_sev = SEVIYE_ANA if int(g["seviye"]) == SEVIYE_TALI else SEVIYE_TALI
        try:
            adaylar = StokGrupService.listele(seviye=hedef_sev, aktif_only=True)
        except Exception as exc:
            messagebox.showerror("Taşı", str(exc), parent=app)
            return
        if not adaylar:
            messagebox.showinfo("Taşı", "Uygun üst grup yok.", parent=app)
            return
        secenekler = {_etiket(a): a["id"] for a in adaylar if a["id"] != g.get("parent_id")}
        if not secenekler:
            messagebox.showinfo("Taşı", "Başka üst grup yok.", parent=app)
            return
        # Basit seçim
        win = tk.Toplevel(app)
        win.title("Üst Grup Seç")
        win.transient(app)
        win.grab_set()
        cb = ttk.Combobox(win, values=list(secenekler.keys()), state="readonly", width=40)
        cb.pack(padx=12, pady=12)
        cb.set(list(secenekler.keys())[0])

        def ok():
            try:
                det = StokGrupService.detay(g["id"])
                stok = det.get("stok_adet") or 0
                if not messagebox.askyesno(
                    "Onay",
                    f"«{g.get('ad')}» taşınacak.\nBağlı stok: {stok}\nDevam?",
                    parent=win,
                ):
                    return
                StokGrupService.tasi(g["id"], secenekler[cb.get()])
                win.destroy()
                _yenile()
            except Exception as exc:
                messagebox.showerror("Taşı", str(exc), parent=win)

        ttk.Button(win, text="Taşı", command=ok).pack(pady=(0, 12))

    def _pasife():
        g = _secili()
        if not g:
            return
        altlari = None
        try:
            det = StokGrupService.detay(g["id"])
            if (det.get("cocuk_adet") or 0) > 0:
                cevap = messagebox.askyesnocancel(
                    "Pasife Al",
                    f"«{g.get('ad')}» altında {det['cocuk_adet']} grup var.\n\n"
                    "Evet = alt grupları da pasife al\n"
                    "Hayır = yalnızca bu grubu pasife al (altlar aktif kalır — engellenebilir)\n"
                    "İptal",
                    parent=app,
                )
                if cevap is None:
                    return
                altlari = bool(cevap)
                if not altlari:
                    # Servis altlari_da=None ile hata verir; False gönderip yalnızca kendini pasife almak istiyoruz
                    # ama servis None ister onay için. altlari_da=False ile sadece kendini pasife al.
                    altlari = False
        except Exception:
            altlari = False
        try:
            StokGrupService.pasife_al(g["id"], altlari_da=altlari if altlari is not None else False)
            _yenile()
        except Exception as exc:
            messagebox.showerror("Pasife Al", str(exc), parent=app)

    def _sil():
        g = _secili()
        if not g:
            return
        if not messagebox.askyesno(
            "Sil",
            f"«{g.get('kod')} / {g.get('ad')}» silinsin mi?",
            parent=app,
        ):
            return
        try:
            StokGrupService.sil(g["id"])
            _yenile()
            detay.configure(text="Bir grup seçin.")
        except Exception as exc:
            msg = str(exc)
            if messagebox.askyesno(
                "Silinemedi",
                f"{msg}\n\nPasife almak ister misiniz?",
                parent=app,
            ):
                _pasife()

    def _toplu_eslestir_ac():
        from stok_grup_toplu_ui import stok_grup_toplu_eslestirme_goster

        stok_grup_toplu_eslestirme_goster(app)

    def _toplu_stok():
        g = _secili()
        if not g:
            # Kayıt seçili değilse yeni toplu eşleştirme ekranını aç
            _toplu_eslestir_ac()
            return
        dlg = StokGrupTopluTasiDialog(app, g)
        app.wait_window(dlg)
        if dlg.result:
            _yenile()

    def _sag_tik(event):
        iid = tree.identify_row(event.y)
        if iid:
            tree.selection_set(iid)
            _detay_goster()
        menu = tk.Menu(tree, tearoff=0)
        menu.add_command(label="Yeni Ana Grup", command=lambda: _yeni(SEVIYE_ANA))
        menu.add_command(label="Yeni Tali Grup", command=lambda: _yeni(SEVIYE_TALI))
        menu.add_command(label="Yeni Alt Grup", command=lambda: _yeni(SEVIYE_ALT))
        menu.add_separator()
        menu.add_command(label="Düzenle", command=_duzenle)
        menu.add_command(label="Taşı", command=_tasi_grup)
        menu.add_command(label="Pasife Al", command=_pasife)
        menu.add_command(label="Sil", command=_sil)
        menu.add_separator()
        menu.add_command(label="Toplu Stok Ata", command=_toplu_eslestir_ac)
        menu.add_command(label="Toplu Stok Taşı", command=_toplu_stok)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    tree.bind("<<TreeviewSelect>>", _detay_goster)
    tree.bind("<Button-3>", _sag_tik)
    tree.bind("<Double-1>", lambda _e: _duzenle())
    arama.bind("<Return>", lambda _e: _yenile())
    _yenile()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: stok_grup_yonetimi_goster(app))
