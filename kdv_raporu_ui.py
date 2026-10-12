"""KDV Raporu ekranı — Raporlar, Satışlar → Raporlar, Satın Alma → Raporlar ve Genel Muhasebe'den açılır.

Tek ekran, tek hesap (``database.kdv_rapor_service``); Genel Muhasebe kapalı olsa da çalışır.
"""

from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, ttk
from typing import Any, Callable

from satin_alma_rapor_ui import Filtre, Kolon, RaporEkrani, Tablo, bicimle
from satis_tema import ACIK_BG, IKINCIL, font, hub_ust_baslik, tk_buton

from database import kdv_rapor_service as srv

AYLAR = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim",
         "Kasım", "Aralık")
AY_SECENEK = [(str(i), ad) for i, ad in enumerate(AYLAR, 1)]
DONEM_SECENEK = [("ay", "Takvim ayı"), ("ozel", "Özel tarih aralığı")]
TUR_SECENEK = [("TUMU", "(Tümü)")] + [(k, v) for k, v in srv.TUR_ADI.items()]
ORAN_SECENEK = [("TUMU", "(Tümü)")] + [(o, f"%{o}") for o in ("0", "1", "8", "10", "18", "20")] + [
    ("ORANSIZ", "Oranlara dağıtılmamış fark")]
DURUM_SECENEK = [("TUMU", "(Tümü)"), ("SORUNLU", "Yalnızca eksik / belirsiz"), ("SORUNSUZ", "Yalnızca sorunsuz")]

GERI = {
    "raporlar": ("← Raporlar", lambda app: __import__("ana_panel_ui").raporlar_menusu_goster(app)),
    "satis": ("← Raporlar", lambda app: __import__("satis_ui").satis_raporlar_hub_goster(app)),
    "satin_alma": ("← Raporlar", lambda app: __import__("satin_alma_ui").satin_alma_raporlar_hub_goster(app)),
    "genel_muhasebe": ("← Genel Muhasebe",
                       lambda app: __import__("genel_muhasebe_ui").genel_muhasebe_menusu_goster(app)),
}


def _yetki(*kodlar) -> bool:
    try:
        from database.access import yetki_var

        return bool(yetki_var(*kodlar))
    except Exception:  # noqa: BLE001
        return True


def _ust_olustur(kaynak: str) -> Callable[[Any, str, str], tk.Frame]:
    geri_metin, geri_fn = GERI.get(kaynak, GERI["raporlar"])

    def ust(app, baslik: str, alt: str) -> tk.Frame:
        temizle = getattr(app, "_icerigi_temizle", None)
        if callable(temizle):
            temizle()
        from satis_tema import stil_uygula

        stil_uygula(root=app)
        kabuk = getattr(app, "_ana_panel_kabuk", None)
        if kabuk is not None:
            menu = {"satis": "satislar", "satin_alma": "satin_alma"}.get(kaynak, kaynak)
            try:
                kabuk.menu_secili_guncelle(menu)
            except Exception:  # noqa: BLE001
                pass
        try:
            app.icerik.configure(bg=ACIK_BG)
        except tk.TclError:
            pass
        kok = tk.Frame(app.icerik, bg=ACIK_BG)
        kok.pack(fill="both", expand=True)
        hub_ust_baslik(kok, baslik=baslik, alt_baslik=alt, app=app,
                       geri_komut=lambda: geri_fn(app), geri_metin=geri_metin)
        return kok

    return ust


def _pencere_ust(pencere: tk.Toplevel) -> Callable[[Any, str, str], tk.Frame]:
    def ust(app, baslik, alt):
        kok = tk.Frame(pencere, bg=ACIK_BG)
        kok.pack(fill="both", expand=True)
        hub_ust_baslik(kok, baslik=baslik, alt_baslik=alt, app=app, geri_komut=pencere.destroy,
                       geri_metin="Kapat")
        return kok

    return ust


def donem_araligi(f: dict) -> tuple[date, date]:
    if f.get("donem") == "ozel":
        bas, bit = f.get("bas"), f.get("bit")
        if not bas or not bit:
            raise ValueError("Özel aralık için başlangıç ve bitiş tarihini girin.")
        return bas, bit
    yil = int(f.get("yil") or date.today().year)
    if not 2000 <= yil <= 2100:
        raise ValueError("Geçerli bir yıl girin.")
    ay = int(f.get("ay") or date.today().month)
    return date(yil, ay, 1), srv.ay_sonu(yil, ay)


# ----------------------------------------------------------------------------- belge açma
def evrak_ac(app, tur: str | None, belge_id) -> None:
    if not tur or not belge_id:
        return
    if tur == srv.SATIS:
        from satis_yonetici_rapor_ui import _belge_ac

        _belge_ac(app, "SATIS", belge_id)
    elif tur == srv.SATIS_IADE:
        from satis_yonetici_rapor_ui import _belge_ac

        _belge_ac(app, "IADE", belge_id)
    elif tur in (srv.ALIS, srv.ALIS_IADE):
        from satin_alma_ui import belgeden_listeye_git

        liste = getattr(app, "alis_faturalari_goster" if tur == srv.ALIS else "alis_iade_faturalari_goster", None)
        if callable(liste):
            belgeden_listeye_git(app, liste, belge_id)
    elif tur in (srv.HIZMET_GELIR, srv.HIZMET_GIDER):
        from gelir_gider_ui import hizmet_faturalari_sayfasi

        hizmet_faturalari_sayfasi(app, "GELIR" if tur == srv.HIZMET_GELIR else "GIDER")


def satirlari_goster(app, r: dict) -> tk.Toplevel | None:
    if not r or not r.get("id") or not r.get("tur"):
        return None
    pencere = tk.Toplevel(app)
    pencere.title(f"KDV — {r.get('tur_adi', '')} {r.get('no', '')}")
    pencere.geometry("1050x520")
    pencere.configure(bg=ACIK_BG)
    ekran = RaporEkrani(
        app, baslik=f"BELGE SATIRLARI — {r.get('no', '')}",
        alt=f"{r.get('tur_adi', '')} · {r.get('cari', '')} · tutarlar belgede saklanan TL değerleri",
        filtreler=[], ust=_pencere_ust(pencere),
        tablolar=[Tablo("satirlar", "Satırlar", [
            Kolon("sira", "#", 40, "gun"), Kolon("kod", "Kod", 100), Kolon("ad", "Ürün / hizmet", 240),
            Kolon("miktar", "Miktar", 70, "miktar"), Kolon("birim", "Birim", 60),
            Kolon("birim_fiyat", "Birim fiyat (TL)", 100, "fiyat"), Kolon("iskonto", "İsk. %", 60, "yuzde"),
            Kolon("kdv_orani", "KDV oranı", 70), Kolon("matrah", "Matrah", 100, "para"),
            Kolon("kdv", "KDV", 90, "para"), Kolon("toplam", "Toplam", 100, "para")])],
        hesapla=lambda _f: {"satirlar": srv.belge_satirlari(r["tur"], r["id"]),
                            "notlar": ["Satır matrahı ve KDV'si belge servisinin toplam hesabıyla bulunur; "
                                       "genel indirim / masraf / yuvarlama farkı satırlara dağıtılmaz."]},
        ek_butonlar=[("Evrakı Aç", lambda _e: evrak_ac(app, r.get("tur"), r.get("id")), "duzenle")],
        otomatik=False)
    ekran.raporla(senkron=True)
    return pencere


# ----------------------------------------------------------------------------- devreden KDV
def _tutar_oku(metin: str) -> Decimal:
    m = (metin or "").strip().replace(" ", "").replace("TL", "")
    if "," in m:
        m = m.replace(".", "").replace(",", ".")
    try:
        return Decimal(m or "0")
    except InvalidOperation as hata:
        raise ValueError("Tutarı sayı olarak girin (ör. 12.500,00).") from hata


def devreden_penceresi(app, ekran: RaporEkrani | None = None) -> tk.Toplevel:
    pencere = tk.Toplevel(app)
    pencere.title("Devreden KDV Kayıtları")
    pencere.geometry("980x560")
    pencere.configure(bg=ACIK_BG)
    yetkili = srv.devreden_yetkisi_var()
    tk.Label(pencere, text=(
        "Önceki dönemden devreden KDV, verilen beyanname veya mali müşavir bildirimine göre girilir. "
        "Kayıt varsa o ayın ön hesabında önceki ayın hesabının yerine geçer (iki kez sayılmaz). Değişiklikte "
        "eski kayıt silinmez, iptal edilir; kesinleşmiş kayıt gerekçesiz değiştirilemez. Bu işlem beyanname "
        "vermez ve vergi kaydı oluşturmaz."), bg=ACIK_BG, fg=IKINCIL, justify="left", wraplength=940,
        font=font(9, "normal", app)).pack(fill="x", padx=12, pady=(10, 6))

    form = tk.Frame(pencere, bg=ACIK_BG)
    form.pack(fill="x", padx=12)
    bugun = date.today()
    alanlar: dict[str, Any] = {}

    def alan(etiket, w, sutun):
        tk.Label(form, text=etiket, bg=ACIK_BG, fg=IKINCIL, font=font(9, "normal", app)).grid(
            row=0, column=sutun, sticky="w", padx=(0, 8))
        w.grid(row=1, column=sutun, sticky="w", padx=(0, 8))

    alanlar["yil"] = ttk.Spinbox(form, from_=2000, to=2100, width=6)
    alanlar["yil"].set(str(bugun.year))
    alan("Yıl", alanlar["yil"], 0)
    alanlar["ay"] = ttk.Combobox(form, values=AYLAR, state="readonly", width=10)
    alanlar["ay"].set(AYLAR[bugun.month - 1])
    alan("Ay (devrin girdiği ay)", alanlar["ay"], 1)
    alanlar["tutar"] = ttk.Entry(form, width=14)
    alan("Devreden KDV (TL)", alanlar["tutar"], 2)
    alanlar["kaynak"] = ttk.Combobox(form, values=srv.DEVREDEN_KAYNAKLARI, state="readonly", width=22)
    alanlar["kaynak"].set(srv.DEVREDEN_KAYNAKLARI[0])
    alan("Kaynak", alanlar["kaynak"], 3)
    alanlar["aciklama"] = ttk.Entry(form, width=34)
    alan("Açıklama", alanlar["aciklama"], 4)
    kesin = tk.BooleanVar(value=False)
    ttk.Checkbutton(form, text="Kesinleşmiş", variable=kesin).grid(row=1, column=5, sticky="w")
    form2 = tk.Frame(pencere, bg=ACIK_BG)
    form2.pack(fill="x", padx=12, pady=(6, 0))
    tk.Label(form2, text="Değişiklik / iptal gerekçesi", bg=ACIK_BG, fg=IKINCIL,
             font=font(9, "normal", app)).pack(side="left")
    gerekce = ttk.Entry(form2, width=60)
    gerekce.pack(side="left", padx=6)

    kolonlar = (("donem", "Dönem", 70), ("tutar", "Tutar", 100), ("kaynak", "Kaynak", 150),
                ("aciklama", "Açıklama", 220), ("kesin", "Kesin", 50), ("durum", "Durum", 60),
                ("kullanici", "Kullanıcı", 110), ("tarih", "Tarih", 120), ("iptal", "İptal gerekçesi", 200))
    liste = ttk.Treeview(pencere, columns=[k for k, _b, _g in kolonlar], show="headings", height=12)
    for k, b, g in kolonlar:
        liste.heading(k, text=b)
        liste.column(k, width=g, anchor="e" if k == "tutar" else "w")
    liste.tag_configure("soluk", foreground="#888888")
    satirlar: list[dict] = []

    def yenile():
        satirlar.clear()
        liste.delete(*liste.get_children())
        try:
            satirlar.extend(srv.devreden_kayitlari())
        except Exception as hata:  # noqa: BLE001
            messagebox.showerror("Devreden KDV", str(hata), parent=pencere)
            return
        for i, r in enumerate(satirlar):
            liste.insert("", "end", iid=str(i), tags=(r["_etiket"],) if r["_etiket"] else (), values=(
                r["donem"], bicimle(r["tutar"], "para"), r["kaynak"], r["aciklama"],
                "Evet" if r["kesinlesti"] else "", "Aktif" if r["durum"] == "AKTIF" else "İptal", r["kullanici"],
                r["tarih"].strftime("%d.%m.%Y %H:%M") if r["tarih"] else "", r["iptal_gerekcesi"]))

    def kaydet():
        try:
            kid = srv.devreden_kaydet(
                int(alanlar["yil"].get()), AYLAR.index(alanlar["ay"].get()) + 1, _tutar_oku(alanlar["tutar"].get()),
                kaynak=alanlar["kaynak"].get(), aciklama=alanlar["aciklama"].get(), kesinlesti=kesin.get(),
                degisiklik_gerekcesi=gerekce.get())
        except Exception as hata:  # noqa: BLE001
            messagebox.showwarning("Devreden KDV", str(hata), parent=pencere)
            return
        yenile()
        if ekran is not None:
            ekran.raporla()
        messagebox.showinfo("Devreden KDV", f"Kayıt eklendi (no {kid}).", parent=pencere)

    def iptal():
        sec = [satirlar[int(i)] for i in liste.selection()]
        if not sec:
            return
        if sec[0]["durum"] != "AKTIF":
            messagebox.showinfo("Devreden KDV", "Seçili kayıt zaten iptal.", parent=pencere)
            return
        if not messagebox.askyesno("Devreden KDV", f"{sec[0]['donem']} devreden kaydı iptal edilsin mi?",
                                   parent=pencere):
            return
        try:
            srv.devreden_iptal(sec[0]["id"], gerekce.get())
        except Exception as hata:  # noqa: BLE001
            messagebox.showwarning("Devreden KDV", str(hata), parent=pencere)
            return
        yenile()
        if ekran is not None:
            ekran.raporla()

    butonlar = tk.Frame(pencere, bg=ACIK_BG)
    butonlar.pack(fill="x", padx=12, pady=6)
    kb = tk_buton(butonlar, "Kaydet", kaydet, rol="kaydet")
    kb.pack(side="left")
    ib = tk_buton(butonlar, "Seçili Kaydı İptal Et", iptal, rol="iptal")
    ib.pack(side="left", padx=6)
    if not yetkili:
        for b in (kb, ib):
            b.configure(state="disabled")
        tk.Label(butonlar, text="Devreden KDV kaydetme yetkiniz yok (yalnızca görüntüleme).", bg=ACIK_BG,
                 fg=IKINCIL, font=font(9, "normal", app)).pack(side="left", padx=8)
    tk_buton(butonlar, "Kapat", pencere.destroy, rol="duzenle").pack(side="right")
    liste.pack(fill="both", expand=True, padx=12, pady=(0, 10))
    yenile()
    pencere.kaydet = kaydet
    pencere.alanlar = alanlar
    pencere.liste = liste
    return pencere


# ----------------------------------------------------------------------------- ana ekran
def _gm_satirlari(s: dict) -> list[dict]:
    if not s.get("gm_aktif"):
        return [{"kategori": "Kullanılamaz", "aciklama": s.get("gm_mesaj") or srv.GM_KAPALI_MESAJI,
                 "_etiket": "soluk"}]
    rows = [{"kategori": f"TOPLAM — {o['kalem']}", "belge": f"Hesap {o['hesap']}", "belge_kdv": o["belge"],
             "gm_kdv": o["gm"], "fark": o["fark"],
             "aciklama": "Belge ve muhasebe toplamları ayrı gösterilir; birbirine eklenmez.", "_etiket": "toplam"}
            for o in s.get("gm_ozet") or []]
    if s.get("gm_mesaj"):
        rows.append({"kategori": "Bilgi", "aciklama": s["gm_mesaj"], "_etiket": "soluk"})
    return rows + list(s.get("gm") or [])


def kdv_raporu_goster(app, kaynak: str = "raporlar", **kw) -> RaporEkrani | None:
    if not _yetki(srv.GORUNTULEME_YETKISI):
        messagebox.showwarning("KDV Raporu", "KDV raporunu görüntüleme yetkiniz yok.", parent=app)
        return None
    bugun = date.today()

    def hesapla(f):
        bas, bit = donem_araligi(f)
        s = srv.rapor(bas, bit, cari=f.get("cari"), belge_turu=f.get("belge_turu"),
                      kdv_orani=f.get("kdv_orani"), durum=f.get("durum"))
        s["gm_tablo"] = _gm_satirlari(s)
        s["_bilgi"] = [f"Dönem: {bas:%d.%m.%Y} – {bit:%d.%m.%Y}"
                       + ("" if s["tam_ay"] else " (özel aralık — beyan dönemi değildir)"),
                       "Genel Muhasebe: " + ("açık" if s["gm_aktif"] else "kapalı (karşılaştırma yok)")]
        return s

    def etiket(r):
        return r.get("_etiket")

    def toplam(s):
        t = s.get("toplamlar") or {}
        if not t:
            return ""
        return (f"Net hesaplanan KDV: {bicimle(t.get('net_hesaplanan'), 'para')}   "
                f"Kesin indirilecek: {bicimle(t.get('net_kesin_indirilecek'), 'para')}   "
                f"İndirilebilirliği belirtilmemiş: {bicimle(t.get('net_belirsiz'), 'para')}   "
                f"KDV'si belirlenemeyen tutar: {bicimle(t.get('belirsiz_brut'), 'para')}   "
                f"Belge: {s.get('belge_sayisi', 0)}   Eksik / belirsiz: {s.get('sorunlu_sayisi', 0)}")

    def _secili_satirlar(e: RaporEkrani) -> list[dict]:
        anahtar = e.tablolar_tanim[e.defter.index("current")].anahtar if e.defter is not None else "belgeler"
        if anahtar not in ("belgeler", "eksik", "gm_tablo"):
            anahtar = "belgeler"
        return [r for r in e.secili(anahtar) if r.get("id")]

    def secili_belge(e: RaporEkrani) -> dict | None:
        sec = _secili_satirlar(e)
        if not sec:
            messagebox.showinfo("KDV Raporu", "Belgeler, Eksik / Belirsiz veya Muhasebe sekmesinde bir belge "
                                "satırı seçin.", parent=app)
            return None
        return sec[0]

    def kdv_bilgisi(e):
        from kdv_raporu_islem_ui import kdv_bilgisi_penceresi

        tekil = {(r["tur"], r["id"]): r for r in _secili_satirlar(e)}
        kdv_bilgisi_penceresi(app, list(tekil.values()), e)

    def kaynak_bagla(e):
        from kdv_raporu_islem_ui import kaynak_bagla_penceresi

        r = secili_belge(e)
        if r:
            kaynak_bagla_penceresi(app, r, e)

    def kaynak_yok(e):
        from kdv_raporu_islem_ui import kaynak_yok_kaydet

        r = secili_belge(e)
        if r:
            kaynak_yok_kaydet(app, r, e)

    def hatali_fisler(e):
        from kdv_raporu_islem_ui import hatali_fis_penceresi

        try:
            bas, bit = donem_araligi(e.filtre_degerleri())
        except ValueError as hata:
            messagebox.showwarning("KDV Raporu", str(hata), parent=app)
            return
        hatali_fis_penceresi(app, bas, bit, e)

    def satirlar(e):
        r = secili_belge(e)
        if r:
            satirlari_goster(app, r)

    def evrak(e):
        r = secili_belge(e)
        if r:
            evrak_ac(app, r.get("tur"), r.get("id"))

    def kur():
        return RaporEkrani(
            app, baslik="KDV RAPORU",
            alt="Alış / satış belgelerinden — Genel Muhasebe paketinden bağımsız (beyanname vermez)",
            filtreler=[
                Filtre("combo", "donem", "Dönem türü", "ay", DONEM_SECENEK),
                Filtre("sayi", "yil", "Yıl", bugun.year),
                Filtre("combo", "ay", "Ay", str(bugun.month), AY_SECENEK),
                Filtre("tarih", "bas", "Özel: başlangıç", date(bugun.year, bugun.month, 1)),
                Filtre("tarih", "bit", "Özel: bitiş", bugun),
                Filtre("metin", "cari", "Cari (ad / kod)"),
                Filtre("combo", "belge_turu", "Belge türü", "TUMU", TUR_SECENEK),
                Filtre("combo", "kdv_orani", "KDV oranı", "TUMU", ORAN_SECENEK),
                Filtre("combo", "durum", "Durum", "TUMU", DURUM_SECENEK),
            ],
            tablolar=[
                Tablo("ozet", "Özet", [
                    Kolon("bolum", "Bölüm", 130), Kolon("kalem", "Kalem", 300), Kolon("adet", "Belge", 60, "gun"),
                    Kolon("matrah", "Matrah", 120, "para"), Kolon("kdv", "KDV", 120, "para"),
                    Kolon("durum", "Durum", 260)], etiket=etiket),
                Tablo("oranlar", "KDV Oranları", [
                    Kolon("yon", "Taraf", 100), Kolon("oran", "Oran", 60), Kolon("tip", "Tür", 190),
                    Kolon("satis_matrah", "Belge matrahı", 115, "para"), Kolon("satis_kdv", "Belge KDV", 105, "para"),
                    Kolon("iade_matrah", "İade matrahı", 105, "para"), Kolon("iade_kdv", "İade KDV", 95, "para"),
                    Kolon("net_matrah", "Net matrah", 115, "para"), Kolon("net_kdv", "Net KDV", 105, "para")],
                    etiket=etiket),
                Tablo("belgeler", "Belgeler", [
                    Kolon("tarih", "Tarih", 80, "tarih"), Kolon("tur_adi", "Tür", 140), Kolon("no", "Belge no", 105),
                    Kolon("ek_no", "Tedarikçi no", 95), Kolon("cari", "Cari", 190),
                    Kolon("matrah", "Matrah", 105, "para"), Kolon("oranlar", "KDV oranı", 80),
                    Kolon("kdv", "KDV", 95, "para"), Kolon("toplam", "Toplam", 105, "para"),
                    Kolon("para_birimi", "Döviz", 50), Kolon("durum", "Durum", 100),
                    Kolon("kdv_durum", "KDV kaynağı", 150), Kolon("islem", "İşlem türü", 120),
                    Kolon("indirilebilirlik", "İndirilebilirlik", 120), Kolon("sinif", "Uyarı sınıfı", 170),
                    Kolon("sorun", "Eksik / belirsiz", 320), Kolon("not", "Not", 260)],
                    cift_tik=lambda r: satirlari_goster(app, r), etiket=etiket, coklu_secim=True),
                Tablo("eksik", "Eksik / Belirsiz", [
                    Kolon("sinif", "Sınıf", 170), Kolon("tarih", "Tarih", 80, "tarih"),
                    Kolon("tur_adi", "Tür", 150), Kolon("no", "Belge no", 105), Kolon("cari", "Cari", 190),
                    Kolon("tutar", "Belge tutarı", 105, "para"), Kolon("kdv", "KDV", 95, "para"),
                    Kolon("sorun", "Eksik bilgi", 520)],
                    cift_tik=lambda r: evrak_ac(app, r.get("tur"), r.get("id")), etiket=etiket, coklu_secim=True),
                Tablo("siniflar", "Uyarı Sınıfları", [
                    Kolon("sinif", "Sınıf", 260), Kolon("belge", "Belge", 70, "gun"),
                    Kolon("tutar", "Belge tutarı", 130, "para"), Kolon("kdv", "KDV", 120, "para")]),
                Tablo("aylik", "Dönem Özeti (aylık)", [
                    Kolon("donem", "Ay", 70), Kolon("belge", "Belge", 55, "gun"),
                    Kolon("etkilenen", "Etkilenen", 65, "gun"),
                    Kolon("net_hesaplanan", "Net hesaplanan", 115, "para"),
                    Kolon("kesin_indirilecek", "Kesin indirilecek", 115, "para"),
                    Kolon("belirsiz_alis", "İndirilebilirliği belirtilmemiş", 150, "para"),
                    Kolon("indirilemez", "İndirilemez", 95, "para"),
                    Kolon("belirsiz_brut", "KDV'si belirlenemeyen tutar", 150, "para"),
                    Kolon("tevkifat", "Tevkif edilen", 95, "para"), Kolon("kdv2", "KDV-2", 85, "para"),
                    Kolon("devreden_giris", "Önceki dönemden devreden", 125, "para"),
                    Kolon("devreden_kaynak", "Devreden kaynağı", 170),
                    Kolon("odenecek", "Ödenecek (ön)", 105, "para"), Kolon("devreden", "Sonraki aya devreden (ön)", 130, "para"),
                    Kolon("alt_odenecek", "Belirtilmemişler indirilirse: ödenecek", 175, "para"),
                    Kolon("alt_devreden", "… devreden", 100, "para"),
                    Kolon("durum", "Durum", 190), Kolon("neden", "Eksik veri", 320), Kolon("uyari", "Uyarı", 360)],
                    etiket=etiket),
                Tablo("gm_tablo", "Muhasebe Karşılaştırması", [
                    Kolon("kategori", "Kategori", 210), Kolon("tarih", "Tarih", 80, "tarih"),
                    Kolon("belge", "Belge", 190), Kolon("cari", "Cari", 160), Kolon("fis_no", "Fiş no", 100),
                    Kolon("fis_tarihi", "Fiş tarihi", 80, "tarih"), Kolon("belge_kdv", "Belge KDV", 105, "para"),
                    Kolon("gm_kdv", "Muhasebe KDV", 105, "para"), Kolon("fark", "Fark", 95, "para"),
                    Kolon("aciklama", "Açıklama", 360)],
                    cift_tik=lambda r: evrak_ac(app, r.get("tur"), r.get("id")), etiket=etiket),
            ],
            hesapla=hesapla, toplam_metni=toplam, ust=_ust_olustur(kaynak), hafiza="kdv_raporu",
            ek_butonlar=[("Belge Satırları", satirlar, "duzenle"), ("Evrakı Aç", evrak, "duzenle"),
                         ("KDV Bilgisi", kdv_bilgisi, "duzenle"), ("Kaynak Bağla", kaynak_bagla, "duzenle"),
                         ("Kaynak Yok", kaynak_yok, "duzenle"), ("Hatalı Fişler", hatali_fisler, "duzenle"),
                         ("Devreden KDV", lambda e: devreden_penceresi(app, e), "duzenle")],
            **kw)

    ekran = kur()
    if hasattr(app, "nav_sayfa_isaretle"):
        app.nav_sayfa_isaretle(lambda: kdv_raporu_goster(app, kaynak))
    return ekran
