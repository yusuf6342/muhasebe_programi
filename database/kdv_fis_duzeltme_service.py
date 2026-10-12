"""KDV'si hatalı muhasebeleştirilmiş belgeler: liste, düzeltme önizlemesi ve kontrollü düzeltme.

Hatalı fiş = belgeye bağlı etkin fişteki KDV, belgenin doğrulanmış KDV'sinden (``database.belge_kdv``,
KDV raporuyla aynı kaynak) farklı. Geçmiş fiş değiştirilmez ve toplu / otomatik düzeltme yapılmaz.

Düzeltme yalnız kullanıcı başlatınca, belge başına bir "KDV düzeltme fişi" ile yapılır: belge tarihinde,
yalnız fark kadar (KDV hesabı ↔ belgenin matrah hesabı). Cari, stok, tahsilat ve SMM satırlarına
dokunulmaz; cari tutarı da farklıysa düzeltme yapılmaz (elle inceleme). Öncesinde doğrulanmış veritabanı
yedeği alınır, işlem izi yazılır, kapalı dönem kilidi uygulanır. Düzeltme fişi ``kdv_duz_<kaynak>``
kaynağıyla belgeye bağlıdır (veritabanında belge başına tek etkin fiş): tekrar çalıştırma ikinci fiş veya
ikinci bakiye etkisi üretmez. Belge sonradan yeniden muhasebeleştirilir ya da iptal edilirse düzeltme fişi
de ters kayıtla kapanır.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from database.access import yetki_zorunlu
from database.database import get_session
from database.kdv_rapor_service import (
    ALIS,
    DUZELTME_ONEKI,
    HESAPLANAN,
    HIZMET_GELIR,
    HIZMET_GIDER,
    INDIRILECEK,
    SATIS,
    SATIS_IADE,
    SIFIR,
    TUR_ADI,
    _yetki,
    belge_fisleri,
    belgeleri_topla,
    fis_kdv,
    gm_aktif,
    kdv_hesap_kodlari,
)

DUZELTME_YETKISI = "kdv_fis_duzeltme"

# Belge türü → (matrah hesabı eşleştirme anahtarı, KDV hesabı anahtarı, cari hesabı anahtarı)
HESAPLAR = {
    SATIS: ("yurtici_satislar", "hesaplanan_kdv", "musteriler"),
    HIZMET_GELIR: ("yurtici_satislar", "hesaplanan_kdv", "musteriler"),
    SATIS_IADE: ("satistan_iadeler", "hesaplanan_kdv", "musteriler"),
    ALIS: ("ticari_mallar", "indirilecek_kdv", "tedarikciler"),
    HIZMET_GIDER: ("giderler", "indirilecek_kdv", "tedarikciler"),
}
DESTEKLENMEYEN_NEDEN = ("Alış iadesi fişinde stok maliyeti / bedel farkı satırları da bulunduğundan otomatik "
                        "düzeltme desteklenmiyor; fişi Genel Muhasebe'den elle inceleyin.")


def _beklenen_ve_fis(b: dict, fisler: dict, h_kod: str, i_kod: str) -> tuple[Decimal, Decimal, object, object]:
    """(beklenen KDV, fişteki KDV) fiş yönünde: hesaplanan alacak / indirilecek borç pozitif."""
    beklenen = b["kdv"] * (-1 if b["iade"] else 1)
    ana, duz = fisler.get("ana"), fisler.get("duzeltme")
    gm = SIFIR
    for fis in (ana, duz):
        if fis is not None and fis.durum == "Kesinleşmiş":
            gm += fis_kdv(fis.satirlar, h_kod, i_kod)[b["yon"]]
    return beklenen, gm, ana, duz


def hatali_fisler(bas: date, bit: date) -> dict:
    """Tarih aralığındaki belgelerden fişteki KDV'si doğrulanmış KDV'den farklı olanlar."""
    _yetki()
    with get_session() as session:
        if not gm_aktif(session):
            return {"aktif": False, "satirlar": [],
                    "mesaj": "Genel Muhasebe bu firmada kullanılmıyor; hatalı fiş kontrolü yapılamaz."}
        belgeler, _ = belgeleri_topla(session, bas, bit)
        h_kod, i_kod = kdv_hesap_kodlari(session)
        fisler = belge_fisleri(session, belgeler)
        rows = []
        for b in belgeler:
            bf = fisler.get((b["gm_kaynak"], b["id"])) or {}
            beklenen, gm, ana, duz = _beklenen_ve_fis(b, bf, h_kod, i_kod)
            if ana is None or ana.durum != "Kesinleşmiş":
                continue
            temel = {"tur": b["tur"], "tur_adi": b["tur_adi"], "id": b["id"], "no": b["no"], "tarih": b["tarih"],
                     "cari": b["cari"], "fis_id": int(ana.id), "fis_no": ana.fis_no, "fis_tarihi": ana.fis_tarihi,
                     "duzeltme_fis_no": duz.fis_no if duz is not None and duz.durum == "Kesinleşmiş" else "",
                     "fis_kdv": gm, "beklenen_kdv": beklenen, "belge_toplam": b["toplam"]}
            if b["belirsiz_brut"]:
                rows.append({**temel, "beklenen_kdv": "", "fark": "", "durum": "KDV belirlenemedi",
                             "aciklama": "; ".join(b["sorunlar"]), "duzeltilebilir": False, "_etiket": "soluk"})
                continue
            if gm == beklenen:
                continue
            duzeltilebilir = b["tur"] in HESAPLAR
            rows.append({**temel, "fark": beklenen - gm,
                         "durum": "Düzeltilebilir (önizleme alın)" if duzeltilebilir else "Elle inceleme",
                         "aciklama": "" if duzeltilebilir else DESTEKLENMEYEN_NEDEN,
                         "duzeltilebilir": duzeltilebilir, "_etiket": "uyari"})
        return {"aktif": True, "satirlar": rows, "mesaj": ""}


def _belge_bul(session, tur: str, belge_id: int) -> dict:
    from database.kdv_belge_bilgi_service import _model

    f = session.get(_model(tur), int(belge_id))
    if f is None:
        raise ValueError("Belge bulunamadı.")
    tarih = getattr(f, "fatura_tarihi", None) or getattr(f, "iade_tarihi", None)
    for b in belgeleri_topla(session, tarih, tarih)[0]:
        if b["tur"] == tur and b["id"] == int(belge_id):
            return b
    raise ValueError("Belge KDV'ye esas değil (taslak / iptal / silinmiş).")


def _onizleme(session, tur: str, belge_id: int) -> dict:
    from database.muhasebe_entegrasyon import MuhasebeEntegrasyonService as H
    from database.muhasebe_service import kapali_donem_mi

    b = _belge_bul(session, tur, belge_id)
    h_kod, i_kod = kdv_hesap_kodlari(session)
    bf = belge_fisleri(session, [b]).get((b["gm_kaynak"], b["id"])) or {}
    beklenen, gm, ana, duz = _beklenen_ve_fis(b, bf, h_kod, i_kod)
    sonuc = {"tur": tur, "tur_adi": TUR_ADI[tur], "id": int(belge_id), "no": b["no"], "tarih": b["tarih"],
             "cari": b["cari"], "fis_no": getattr(ana, "fis_no", ""), "fis_id": getattr(ana, "id", None),
             "fis_kdv": gm, "beklenen_kdv": beklenen, "fark": beklenen - gm, "satirlar": [],
             "duzeltilebilir": False, "neden": "", "kilitli": False, "fis_tarihi": b["tarih"],
             "kaynak_turu": DUZELTME_ONEKI + b["gm_kaynak"]}
    if ana is None or ana.durum != "Kesinleşmiş":
        sonuc["neden"] = "Belgenin kesinleşmiş muhasebe fişi yok; düzeltme yerine muhasebeleştirin."
        return sonuc
    if b["belirsiz_brut"]:
        sonuc["neden"] = "Belgenin KDV'si doğrulanamadı: " + "; ".join(b["sorunlar"])
        return sonuc
    if tur not in HESAPLAR:
        sonuc["neden"] = DESTEKLENMEYEN_NEDEN
        return sonuc
    if not sonuc["fark"]:
        sonuc["neden"] = "Fişteki KDV doğrulanmış KDV ile aynı; düzeltme gerekmiyor."
        return sonuc
    if duz is not None and duz.durum == "Kesinleşmiş":
        sonuc["neden"] = (f"Belgenin {duz.fis_no} no'lu KDV düzeltme fişi zaten var ama fark sürüyor (belge sonradan "
                          "değişmiş olabilir). Belgeyi yeniden muhasebeleştirin veya fişleri elle inceleyin.")
        return sonuc
    matrah_anahtari, kdv_anahtari, cari_anahtari = HESAPLAR[tur]
    try:
        matrah_h = H._hesap(matrah_anahtari, session=session)
        kdv_h = H._hesap(kdv_anahtari, session=session)
        cari_h = H._hesap(cari_anahtari, session=session)
    except ValueError as hata:
        sonuc["neden"] = str(hata)
        return sonuc
    hesaplar = {int(s.hesap_id) for s in ana.satirlar}
    if matrah_h["id"] not in hesaplar:
        sonuc["neden"] = (f"Fişte {matrah_h['kod']} ({matrah_anahtari}) satırı yok; hesap eşleştirmesi fiş "
                          "yazıldıktan sonra değişmiş olabilir. Elle inceleyin.")
        return sonuc
    cari_tutar = sum(((s.borc or 0) - (s.alacak or 0) for s in ana.satirlar if int(s.hesap_id) == cari_h["id"]),
                     Decimal("0"))
    cari_tutar = abs(Decimal(str(cari_tutar)))
    if cari_tutar != b["toplam"]:
        sonuc["neden"] = (f"Fişteki cari tutarı {cari_tutar:.2f}, belge toplamı {b['toplam']:.2f}: yalnız KDV ayrımı "
                          "değil cari tutarı da farklı. Otomatik düzeltme yapılmaz; elle inceleyin.")
        return sonuc
    fark = sonuc["fark"]
    tutar = abs(fark)
    no = b["no"]
    if tur == SATIS_IADE:
        # İadede KDV borç, iade hesabı alacak; fark negatifse (fişte fazla KDV) yön tersine döner
        borclu, alacakli = (kdv_h, matrah_h) if fark < 0 else (matrah_h, kdv_h)
    elif b["yon"] == HESAPLANAN:
        borclu, alacakli = (matrah_h, kdv_h) if fark > 0 else (kdv_h, matrah_h)
    else:
        borclu, alacakli = (kdv_h, matrah_h) if fark > 0 else (matrah_h, kdv_h)
    sonuc["satirlar"] = [
        {"hesap_id": borclu["id"], "hesap_kodu": borclu["kod"], "hesap_adi": borclu["ad"], "borc": tutar,
         "alacak": SIFIR, "aciklama": f"KDV düzeltme {no}"},
        {"hesap_id": alacakli["id"], "hesap_kodu": alacakli["kod"], "hesap_adi": alacakli["ad"], "borc": SIFIR,
         "alacak": tutar, "aciklama": f"KDV düzeltme {no}"},
    ]
    sonuc["kilitli"] = kapali_donem_mi(session, b["tarih"])
    if sonuc["kilitli"]:
        sonuc["neden"] = (f"Belge tarihi {b['tarih']:%d.%m.%Y} kapalı (kilitli) dönemde; düzeltme fişi yazılamaz. "
                          "Dönemi açmadan düzeltme yapılmaz.")
        return sonuc
    sonuc["duzeltilebilir"] = True
    return sonuc


def duzeltme_onizleme(tur: str, belge_id: int) -> dict:
    """Yazılacak düzeltme fişinin satırları (hiçbir şey yazılmaz)."""
    _yetki()
    with get_session() as session:
        return _onizleme(session, tur, belge_id)


def duzelt(belgeler: list[tuple[str, int]], gerekce: str) -> dict:
    """Seçilen belgeler için düzeltme fişi yazar (önce doğrulanmış yedek). Belge başına ayrı işlem.

    Dönüş: yazılan / zaten doğru / atlanan belgeler ve yedek yolu.
    """
    yetki_zorunlu(DUZELTME_YETKISI, mesaj="KDV fişi düzeltme yetkiniz yok (yönetici onayı gerekir).")
    gerekce = (gerekce or "").strip()
    if not gerekce:
        raise ValueError("Düzeltme gerekçesi zorunludur.")
    if not belgeler:
        raise ValueError("Düzeltilecek belge seçin.")
    with get_session() as session:
        if not gm_aktif(session):
            raise ValueError("Genel Muhasebe bu firmada kullanılmıyor.")
    yedek = _yedek_al()
    sonuc = {"yazilan": [], "zaten_dogru": [], "atlanan": [], "yedek": str(yedek) if yedek else ""}
    from database.muhasebe_service import MuhasebeFisService, MuhasebeService, kapali_donem_zorunlu_degil

    for tur, bid in belgeler:
        try:
            with get_session() as session:
                o = _onizleme(session, tur, bid)
                if not o["fark"] and o["fis_id"]:
                    sonuc["zaten_dogru"].append(o["no"])
                    continue
                if not o["duzeltilebilir"]:
                    sonuc["atlanan"].append((o["no"], o["neden"]))
                    continue
                kapali_donem_zorunlu_degil(session, o["fis_tarihi"], "KDV düzeltme fişi")
                fis_id = MuhasebeFisService.kaydet({
                    "fis_tarihi": o["fis_tarihi"], "fis_turu": "Mahsup Fişi",
                    "aciklama": f"KDV düzeltme: {o['tur_adi']} {o['no']} (fiş {o['fis_no']}) — {gerekce}"[:500],
                    "belge_no": o["no"], "durum": "Kesinleşmiş", "kaynak_turu": o["kaynak_turu"],
                    "kaynak_id": int(bid), "satirlar": o["satirlar"],
                }, otomatik=True, session=session)
                MuhasebeService._gecmis(
                    session, kayit_turu=f"belge:{o['kaynak_turu'][len(DUZELTME_ONEKI):]}", kayit_id=int(bid),
                    islem="kdv_duzeltme",
                    detay=f"fiş {o['fis_no']} KDV {o['fis_kdv']} → {o['beklenen_kdv']} (fark {o['fark']}); "
                          f"düzeltme fişi id={fis_id}; gerekçe: {gerekce}")
                sonuc["yazilan"].append((o["no"], int(fis_id), o["fark"]))
        except Exception as hata:  # noqa: BLE001 — belge başına ayrı işlem; biri diğerini bozmaz
            sonuc["atlanan"].append((f"{TUR_ADI.get(tur, tur)} #{bid}", str(hata)))
    try:
        from database.user_audit import audit_document

        audit_document("KDV_FIS_DUZELTME", modul="muhasebe", belge_no=f"{len(sonuc['yazilan'])} belge",
                       yeni={"yazilan": sonuc["yazilan"], "atlanan": sonuc["atlanan"], "yedek": sonuc["yedek"]},
                       aciklama=gerekce)
    except Exception:  # noqa: BLE001
        pass
    return sonuc


def _yedek_al():
    import database.database as veritabani
    from database.gecis_guvenligi import dogrulanmis_yedek

    db_yolu = getattr(veritabani.company_db, "_db_path", None)
    if not db_yolu:
        return None
    return dogrulanmis_yedek(db_yolu, "kdv_fis_duzeltme").yol


__all__ = ["HESAPLAR", "duzelt", "duzeltme_onizleme", "hatali_fisler", "INDIRILECEK"]
