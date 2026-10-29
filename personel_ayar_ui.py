"""Personel Ayarları — mevzuat parametreleri, belge türleri, yetki özeti, değişiklik geçmişi.

Ham sözlük dökümü yerine tablolar ve düzenleme formu (DOC Personel Ayarları).
"""

from __future__ import annotations

import json
import tkinter as tk
from datetime import date, datetime
from tkinter import messagebox, simpledialog, ttk

from sqlalchemy import select


def _para_turkce_ad(kod: str) -> str:
    sozluk = {
        "YILLIK_IZIN_GUN": "Yıllık izin günü",
        "IHBAR_SURESI": "İhbar süresi",
        "KIDEM_TAVANI": "Kıdem tavanı",
        "ASGARI_UCRET": "Asgari ücret",
        "SGK_ISVEREN": "SGK işveren oranı",
        "SGK_ISCI": "SGK işçi oranı",
        "ISSizlik_ISVEREN": "İşsizlik işveren oranı",
        "ISSizlik_ISCI": "İşsizlik işçi oranı",
    }
    return sozluk.get((kod or "").upper(), (kod or "").replace("_", " ").title())


def _belge_sinif_tr(kod: str) -> str:
    m = {
        "ZORUNLU": "Zorunlu",
        "KOSULLU": "Koşullu",
        "ISTEGE": "İsteğe bağlı",
        "ISTEGE_BAGLI": "İsteğe bağlı",
    }
    return m.get((kod or "").upper(), kod or "—")


def _gizlilik_tr(kod: str) -> str:
    m = {
        "NORMAL": "Normal",
        "HASSAS": "Hassas",
        "COK_HASSAS": "Çok hassas",
        "TIBBI": "Tıbbi",
        "ADLI": "Adli",
    }
    return m.get((kod or "").upper(), kod or "—")


def _deger_ozeti(deger_json: str | None) -> str:
    if not deger_json:
        return "—"
    try:
        veri = json.loads(deger_json)
    except (TypeError, json.JSONDecodeError):
        return (deger_json or "")[:80]
    if isinstance(veri, dict):
        parcalar = []
        for k, v in list(veri.items())[:6]:
            parcalar.append(f"{k}: {v}")
        return "; ".join(parcalar) if parcalar else "{}"
    return str(veri)[:120]


def ayarlar_ekrani_goster(app) -> None:
    """Personel menüsünden çağrılır; sekmeli düzenli ayar ekranı."""
    app._icerigi_temizle()
    from personel_ui import _ust

    _ust(app, "PERSONEL AYARLARI")
    from database.database import get_session
    from database.models.personel import (
        PersonelBelgeTuru,
        PersonelErisimLog,
        PersonelMevzuatParametre,
    )
    from database.personel_sema import schema_hazirla
    from database.session_manager import oturum

    schema_hazirla()

    ttk.Label(
        app.icerik,
        text=(
            "Mevzuat parametreleri, belge kuralları ve erişim özeti. "
            "Süre/oranlar kaynak göstermeden sabitlenmez; geçmiş bordro kuralları korunur."
        ),
        wraplength=820,
    ).pack(anchor="w", pady=(8, 4))

    nb = ttk.Notebook(app.icerik)
    nb.pack(fill="both", expand=True, pady=6)

    # —— Mevzuat ——
    fr_m = ttk.Frame(nb, padding=6)
    nb.add(fr_m, text="Mevzuat Parametreleri")
    ust_m = ttk.Frame(fr_m)
    ust_m.pack(fill="x")
    ara_m = tk.StringVar()
    ttk.Label(ust_m, text="Ara:").pack(side="left")
    ttk.Entry(ust_m, textvariable=ara_m, width=24).pack(side="left", padx=4)
    kolon_m = ("ad", "kapsam", "deger", "yururluk", "durum", "kaynak")
    tab_m = ttk.Treeview(fr_m, columns=kolon_m, show="headings", height=14)
    for k, b, w in (
        ("ad", "Parametre adı", 180),
        ("kapsam", "Kapsam", 120),
        ("deger", "Değer / özet", 220),
        ("yururluk", "Yürürlük", 120),
        ("durum", "Durum", 80),
        ("kaynak", "Kaynak", 160),
    ):
        tab_m.heading(k, text=b)
        tab_m.column(k, width=w, anchor="w")
    tab_m.pack(fill="both", expand=True, pady=6)
    detay_m = ttk.Label(fr_m, text="", wraplength=780, foreground="#333")
    detay_m.pack(anchor="w")

    id_map_m: dict[str, int] = {}

    def _mevzuat_doldur():
        tab_m.delete(*tab_m.get_children())
        id_map_m.clear()
        q = (ara_m.get() or "").strip().casefold()
        with get_session() as session:
            rows = list(
                session.scalars(
                    select(PersonelMevzuatParametre).order_by(
                        PersonelMevzuatParametre.kod, PersonelMevzuatParametre.surum
                    )
                )
            )
        for p in rows:
            ad = _para_turkce_ad(p.kod)
            if q and q not in ad.casefold() and q not in (p.kod or "").casefold():
                continue
            durum = "Aktif" if p.aktif else "Pasif"
            if p.yururluk_baslangic and p.yururluk_baslangic > date.today():
                durum = "Gelecek"
            iid = str(p.id)
            id_map_m[iid] = p.id
            tab_m.insert(
                "",
                "end",
                iid=iid,
                values=(
                    f"{ad} (v{p.surum})",
                    p.kapsam or "—",
                    _deger_ozeti(p.deger_json),
                    f"{p.yururluk_baslangic:%d.%m.%Y}" if p.yururluk_baslangic else "—",
                    durum,
                    (p.resmi_kaynak or "")[:40],
                ),
            )

    def _mevzuat_sec(_e=None):
        sec = tab_m.selection()
        if not sec:
            detay_m.configure(text="")
            return
        pid = id_map_m.get(sec[0])
        with get_session() as session:
            p = session.get(PersonelMevzuatParametre, pid)
            if not p:
                return
            detay_m.configure(
                text=(
                    f"Kod: {p.kod} | Sürüm: {p.surum} | Kontrol: {p.kontrol_tarihi} | "
                    f"Onaylayan: {p.onaylayan or '—'} | Kaynak: {p.resmi_kaynak}\n"
                    f"Değer: {p.deger_json}"
                )
            )

    def _mevzuat_duzenle():
        sec = tab_m.selection()
        if not sec:
            messagebox.showinfo("Mevzuat", "Düzenlemek için satır seçin.", parent=app)
            return
        from database.access import yetki_var

        if not yetki_var("personel_ayar", "sistem_ayarlari"):
            messagebox.showwarning("Yetki", "Mevzuat kuralı değiştirme yetkiniz yok.", parent=app)
            return
        pid = id_map_m.get(sec[0])
        with get_session() as session:
            p = session.get(PersonelMevzuatParametre, pid)
            if not p:
                return
            eski = p.deger_json
            yeni = simpledialog.askstring(
                "Mevzuat değeri",
                f"{_para_turkce_ad(p.kod)} (JSON / metin)\nKaynak: {p.resmi_kaynak}",
                initialvalue=eski,
                parent=app.root if hasattr(app, "root") else None,
            )
            if yeni is None or yeni == eski:
                return
            gerekce = simpledialog.askstring(
                "Gerekçe", "Değişiklik gerekçesi (zorunlu):", parent=app.root if hasattr(app, "root") else None
            )
            if not (gerekce or "").strip():
                messagebox.showerror("Gerekçe", "Gerekçe zorunludur.", parent=app)
                return
            kullanici = getattr(oturum, "kullanici_adi", None) or getattr(oturum, "ad_soyad", None)
            if not kullanici:
                messagebox.showerror("Oturum", "Oturum yok; sahte kullanıcı ile kayıt yapılmaz.", parent=app)
                return
            p.deger_json = yeni
            p.kontrol_tarihi = date.today()
            session.add(
                PersonelErisimLog(
                    kullanici=str(kullanici),
                    islem="MEVZUAT_DEGISTIR",
                    belge_id=None,
                    surum_id=p.id,
                    personel_id=None,
                    zaman=datetime.now(),
                    ayrinti=f"{p.kod} v{p.surum} | {gerekce.strip()[:80]}",
                )
            )
            session.commit()
        messagebox.showinfo("Kayıt", "Mevzuat parametresi güncellendi.", parent=app)
        _mevzuat_doldur()

    ttk.Button(ust_m, text="Yenile", command=_mevzuat_doldur).pack(side="right", padx=2)
    ttk.Button(ust_m, text="Düzenle", command=_mevzuat_duzenle).pack(side="right", padx=2)
    ara_m.trace_add("write", lambda *_a: _mevzuat_doldur())
    tab_m.bind("<<TreeviewSelect>>", _mevzuat_sec)
    _mevzuat_doldur()

    # —— Belge türleri ——
    fr_b = ttk.Frame(nb, padding=6)
    nb.add(fr_b, text="Belge Türleri")
    ust_b = ttk.Frame(fr_b)
    ust_b.pack(fill="x")
    kolon_b = ("ad", "gereklilik", "kosul", "erisim", "durum")
    tab_b = ttk.Treeview(fr_b, columns=kolon_b, show="headings", height=14)
    for k, b, w in (
        ("ad", "Belge adı", 200),
        ("gereklilik", "Gereklilik", 100),
        ("kosul", "Uygulanma koşulu", 220),
        ("erisim", "Erişim", 100),
        ("durum", "Durum", 80),
    ):
        tab_b.heading(k, text=b)
        tab_b.column(k, width=w, anchor="w")
    tab_b.pack(fill="both", expand=True, pady=6)
    id_map_b: dict[str, int] = {}

    def _belge_doldur():
        tab_b.delete(*tab_b.get_children())
        id_map_b.clear()
        with get_session() as session:
            rows = list(session.scalars(select(PersonelBelgeTuru).order_by(PersonelBelgeTuru.ad)))
        for t in rows:
            iid = str(t.id)
            id_map_b[iid] = t.id
            tab_b.insert(
                "",
                "end",
                iid=iid,
                values=(
                    t.ad,
                    _belge_sinif_tr(t.sinif),
                    (t.uygulanma_kosulu or "—")[:60],
                    _gizlilik_tr(t.gizlilik),
                    "Aktif" if t.aktif else "Pasif",
                ),
            )

    def _belge_aktif_toggle():
        sec = tab_b.selection()
        if not sec:
            return
        from database.access import yetki_var

        if not yetki_var("personel_ayar", "sistem_ayarlari"):
            messagebox.showwarning("Yetki", "Belge kuralı değiştirme yetkiniz yok.", parent=app)
            return
        tid = id_map_b.get(sec[0])
        with get_session() as session:
            t = session.get(PersonelBelgeTuru, tid)
            if not t:
                return
            t.aktif = not t.aktif
            session.commit()
        _belge_doldur()

    ttk.Button(ust_b, text="Yenile", command=_belge_doldur).pack(side="right", padx=2)
    ttk.Button(ust_b, text="Aktif / Pasif", command=_belge_aktif_toggle).pack(side="right", padx=2)
    _belge_doldur()

    # —— Yetki özeti ——
    fr_y = ttk.Frame(nb, padding=6)
    nb.add(fr_y, text="Yetki ve Gizlilik")
    ttk.Label(
        fr_y,
        text=(
            "Bu ekran mevcut rol/izin modelini kullanır. "
            "personel_ayar, sistem_ayarlari ve hassas belge erişimi ayrı değerlendirilir. "
            "Çalışan sağlık/adli belge içerikleri burada listelenmez."
        ),
        wraplength=780,
    ).pack(anchor="w")
    with get_session() as session:
        pass
    kullanici = getattr(oturum, "kullanici_adi", None) or "—"
    rol = getattr(oturum, "role_kod", None) or getattr(oturum, "role_ad", None) or "—"
    ttk.Label(fr_y, text=f"Oturum: {kullanici}  |  Rol: {rol}", font=("", 10, "bold")).pack(
        anchor="w", pady=8
    )
    try:
        from database.access import yetki_var

        for kod, ad in (
            ("personel_ayar", "Personel ayarlarını görüntüle / değiştir"),
            ("sistem_ayarlari", "Sistem ayarları"),
            ("personel_duzenleme", "Personel kartı düzenleme"),
        ):
            var = "Var" if yetki_var(kod) else "Yok"
            ttk.Label(fr_y, text=f"• {ad}: {var}").pack(anchor="w")
    except Exception as exc:
        ttk.Label(fr_y, text=f"Yetki tablosu okunamadı: {exc}", foreground="#b3261e").pack(anchor="w")

    # —— Geçmiş ——
    fr_g = ttk.Frame(nb, padding=6)
    nb.add(fr_g, text="Değişiklik Geçmişi")
    kolon_g = ("zaman", "kullanici", "alan", "ozet")
    tab_g = ttk.Treeview(fr_g, columns=kolon_g, show="headings", height=14)
    for k, b, w in (
        ("zaman", "Zaman", 140),
        ("kullanici", "Kullanıcı", 120),
        ("alan", "Kayıt", 180),
        ("ozet", "Özet", 280),
    ):
        tab_g.heading(k, text=b)
        tab_g.column(k, width=w, anchor="w")
    tab_g.pack(fill="both", expand=True)

    def _gecmis_doldur():
        tab_g.delete(*tab_g.get_children())
        with get_session() as session:
            rows = list(
                session.scalars(
                    select(PersonelErisimLog)
                    .where(PersonelErisimLog.islem == "MEVZUAT_DEGISTIR")
                    .order_by(PersonelErisimLog.zaman.desc())
                    .limit(200)
                )
            )
        for g in rows:
            tab_g.insert(
                "",
                "end",
                values=(
                    g.zaman.strftime("%d.%m.%Y %H:%M") if g.zaman else "—",
                    g.kullanici or "—",
                    g.islem,
                    (g.ayrinti or "")[:80],
                ),
            )

    ttk.Button(fr_g, text="Yenile", command=_gecmis_doldur).pack(anchor="e", pady=4)
    _gecmis_doldur()

    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: ayarlar_ekrani_goster(app))
