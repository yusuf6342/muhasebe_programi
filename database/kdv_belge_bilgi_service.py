"""Belge KDV bilgisi (indirilebilirlik / özel işlem) ve iade kaynak bağlantısı.

Bilgi ``kdv_belge_bilgileri`` tablosunda belge türü + id ile tutulur; fatura tutarları, stok, cari ve
muhasebe fişleri değişmez. Kaydı olmayan belge "Belirtilmemiş"tir.

İade kaynak bağlantısı yalnız kullanıcının seçtiği faturaya yapılır (otomatik / rastgele eşleştirme
yoktur). Seçilen faturada iade satırının ürünü tek satırda ve yeterli miktarda varsa satır bağlantısı da
kurulur; aksi halde satır bağlantısız kalır ve raporda gösterilir. Alış iadesinde satır kaynak kararları
(stok katmanı / kur farkı dağılımı) değiştirilmez; yalnız başlık bağlantısı kurulur.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import inspect, select

from database.access import yetki_zorunlu
from database.database import get_session
from database.session_manager import oturum

DUZENLEME_YETKISI = "kdv_belge_bilgisi_duzenleme"

SATIS = "SATIS"
SATIS_IADE = "SATIS_IADE"
ALIS = "ALIS"
ALIS_IADE = "ALIS_IADE"
HIZMET = "HIZMET"

RAPOR_TURU = {"SATIS": SATIS, "SATIS_IADE": SATIS_IADE, "ALIS": ALIS, "ALIS_IADE": ALIS_IADE,
              "HIZMET_GELIR": HIZMET, "HIZMET_GIDER": HIZMET}
ALIS_TARAFI = (ALIS, ALIS_IADE, "HIZMET_GIDER")


def bilgi_turu(rapor_turu: str) -> str:
    try:
        return RAPOR_TURU[rapor_turu]
    except KeyError:
        raise ValueError(f"KDV bilgisi bu belge türü için girilemez: {rapor_turu}") from None


def _tablo_var(session) -> bool:
    return inspect(session.connection()).has_table("kdv_belge_bilgileri")


def _tablo_hazirla() -> None:
    """Tablo yoksa oluşturur (tekrar çalıştırılabilir); mevcut veride önce doğrulanmış yedek alınır."""
    import database.database as veritabani
    from database.models.kdv_belge_bilgisi import KdvBelgeBilgisi

    motor = getattr(veritabani.company_db, "_engine", None) or veritabani.engine
    if inspect(motor).has_table(KdvBelgeBilgisi.__tablename__):
        return

    def calistir() -> None:
        KdvBelgeBilgisi.__table__.create(bind=motor, checkfirst=True)

    db_yolu = getattr(veritabani.company_db, "_db_path", None)
    if not db_yolu:
        calistir()
        return
    from database.gecis_guvenligi import guvenli_gecis, yedek_onayi

    if yedek_onayi(db_yolu) is not None:
        calistir()
    else:
        guvenli_gecis(db_yolu, calistir, gerekli=True, etiket="kdv_belge_bilgisi_gecis")


def bilgileri_oku(session, anahtarlar) -> dict[tuple[str, int], object]:
    """(belge_turu, belge_id) → KdvBelgeBilgisi. Tablo yoksa boş (hiçbir şey oluşturulmaz)."""
    if not _tablo_var(session):
        return {}
    from database.models.kdv_belge_bilgisi import KdvBelgeBilgisi

    gruplar: dict[str, list[int]] = {}
    for tur, bid in anahtarlar:
        gruplar.setdefault(tur, []).append(int(bid))
    sonuc = {}
    for tur, idler in gruplar.items():
        for i in range(0, len(idler), 500):
            for k in session.scalars(select(KdvBelgeBilgisi).where(
                    KdvBelgeBilgisi.belge_turu == tur, KdvBelgeBilgisi.belge_id.in_(idler[i:i + 500]))):
                sonuc[(tur, int(k.belge_id))] = k
    return sonuc


def belge_bilgisi(rapor_turu: str, belge_id: int) -> dict:
    tur = bilgi_turu(rapor_turu)
    with get_session() as session:
        k = bilgileri_oku(session, [(tur, belge_id)]).get((tur, int(belge_id)))
        return {
            "indirilebilirlik": getattr(k, "indirilebilirlik", None),
            "islem_turu": getattr(k, "islem_turu", None),
            "tevkifat_pay": getattr(k, "tevkifat_pay", None),
            "tevkifat_payda": getattr(k, "tevkifat_payda", None),
            "istisna_kodu": getattr(k, "istisna_kodu", None) or "",
            "kaynak_yok_nedeni": getattr(k, "kaynak_yok_nedeni", None) or "",
            "aciklama": getattr(k, "aciklama", None) or "",
            "kullanici": getattr(k, "kullanici", None) or "",
            "guncelleme_tarihi": getattr(k, "guncelleme_tarihi", None),
        }


def _dogrula(rapor_turu: str, alanlar: dict) -> dict:
    from database.models.kdv_belge_bilgisi import (
        INDIRILEBILIRLIK_SECENEKLERI,
        ISLEM_TURLERI,
        ISTISNA,
        TEVKIFAT,
    )

    temiz = {}
    if "indirilebilirlik" in alanlar:
        v = alanlar["indirilebilirlik"] or None
        if v is not None and v not in INDIRILEBILIRLIK_SECENEKLERI:
            raise ValueError("Geçersiz indirilebilirlik seçimi.")
        if v is not None and rapor_turu not in ALIS_TARAFI:
            raise ValueError("İndirilebilirlik yalnız alış tarafı belgeler için girilir.")
        temiz["indirilebilirlik"] = v
    if "islem_turu" in alanlar:
        v = alanlar["islem_turu"] or None
        if v is not None and v not in ISLEM_TURLERI:
            raise ValueError("Geçersiz işlem türü.")
        temiz["islem_turu"] = v
        pay, payda = alanlar.get("tevkifat_pay"), alanlar.get("tevkifat_payda")
        if v == TEVKIFAT:
            try:
                pay, payda = int(pay), int(payda or 10)
            except (TypeError, ValueError):
                raise ValueError("Tevkifat oranını girin (ör. 5/10).") from None
            if not (1 <= pay <= payda <= 10):
                raise ValueError("Tevkifat oranı 1/10 ile 10/10 arasında olmalı.")
            temiz["tevkifat_pay"], temiz["tevkifat_payda"] = pay, payda
        else:
            temiz["tevkifat_pay"] = temiz["tevkifat_payda"] = None
        kod = (alanlar.get("istisna_kodu") or "").strip() or None
        temiz["istisna_kodu"] = kod if v == ISTISNA else None
    if "aciklama" in alanlar:
        temiz["aciklama"] = (alanlar.get("aciklama") or "").strip() or None
    return temiz


def _kaydet(session, tur: str, belge_id: int, alanlar: dict):
    from database.models.kdv_belge_bilgisi import KdvBelgeBilgisi

    k = session.scalar(select(KdvBelgeBilgisi).where(
        KdvBelgeBilgisi.belge_turu == tur, KdvBelgeBilgisi.belge_id == int(belge_id)))
    eski = None
    if k is None:
        k = KdvBelgeBilgisi(belge_turu=tur, belge_id=int(belge_id))
        session.add(k)
    else:
        eski = {a: getattr(k, a) for a in alanlar}
    for a, v in alanlar.items():
        setattr(k, a, v)
    k.kullanici = oturum.ad_soyad or oturum.kullanici_adi or ""
    k.guncelleme_tarihi = datetime.now()
    return k, eski


def _belge_var(session, rapor_turu: str, belge_id: int):
    model = _model(rapor_turu)
    f = session.get(model, int(belge_id))
    if f is None:
        raise ValueError("Belge bulunamadı.")
    return f


def _model(rapor_turu: str):
    from database.models.alis_faturasi import AlisFaturasi
    from database.models.alis_iade_faturasi import AlisIadeFaturasi
    from database.models.hizmet_faturasi import HizmetFaturasi
    from database.models.satis_faturasi import SatisFaturasi
    from database.models.satis_iade_faturasi import SatisIadeFaturasi

    return {"SATIS": SatisFaturasi, "SATIS_IADE": SatisIadeFaturasi, "ALIS": AlisFaturasi,
            "ALIS_IADE": AlisIadeFaturasi, "HIZMET_GELIR": HizmetFaturasi,
            "HIZMET_GIDER": HizmetFaturasi}[rapor_turu]


def _belge_no(f) -> str:
    return getattr(f, "fatura_no", None) or getattr(f, "iade_no", None) or str(f.id)


def bilgi_kaydet(rapor_turu: str, belge_id: int, **alanlar) -> None:
    """Tek belgenin KDV bilgisini kaydeder; boş değer 'Belirtilmemiş'e döndürür."""
    yetki_zorunlu(DUZENLEME_YETKISI, mesaj="Belge KDV bilgisini düzenleme yetkiniz yok.")
    tur = bilgi_turu(rapor_turu)
    temiz = _dogrula(rapor_turu, alanlar)
    _tablo_hazirla()
    with get_session() as session:
        f = _belge_var(session, rapor_turu, belge_id)
        _, eski = _kaydet(session, tur, belge_id, temiz)
        no = _belge_no(f)
    _iz("KDV_BELGE_BILGISI", tur, belge_id, no, eski, temiz)


def toplu_bilgi_kaydet(belgeler: list[tuple[str, int]], **alanlar) -> int:
    """Seçili belgelere aynı bilgiyi uygular (kullanıcının açık seçimi); uygulanan belge sayısı."""
    yetki_zorunlu(DUZENLEME_YETKISI, mesaj="Belge KDV bilgisini düzenleme yetkiniz yok.")
    if not belgeler:
        return 0
    temizler = [(rt, bid, _dogrula(rt, alanlar)) for rt, bid in belgeler]
    _tablo_hazirla()
    with get_session() as session:
        for rt, bid, temiz in temizler:
            _belge_var(session, rt, bid)
            _kaydet(session, bilgi_turu(rt), bid, temiz)
    _iz("KDV_BELGE_BILGISI_TOPLU", "", 0, f"{len(temizler)} belge", None, _dogrula(belgeler[0][0], alanlar))
    return len(temizler)


def _iz(islem: str, tur: str, belge_id: int, no: str, eski, yeni) -> None:
    try:
        from database.user_audit import audit_document

        audit_document(islem, modul="rapor", kayit_id=f"{tur}:{belge_id}", belge_no=no, eski=eski, yeni=yeni)
    except Exception:  # noqa: BLE001
        pass


# ----------------------------------------------------------------------------- iade kaynak bağlantısı
def _iade_modelleri(rapor_turu: str):
    if rapor_turu == SATIS_IADE:
        from database.models.satis_faturasi import SatisFaturasi, SatisFaturasiSatiri
        from database.models.satis_iade_faturasi import SatisIadeFaturasi, SatisIadeFaturasiSatiri

        return SatisIadeFaturasi, SatisIadeFaturasiSatiri, SatisFaturasi, SatisFaturasiSatiri, "fatura_tarihi"
    if rapor_turu == ALIS_IADE:
        from database.models.alis_faturasi import AlisFaturasi, AlisFaturasiSatiri
        from database.models.alis_iade_faturasi import AlisIadeFaturasi, AlisIadeFaturasiSatiri

        return AlisIadeFaturasi, AlisIadeFaturasiSatiri, AlisFaturasi, AlisFaturasiSatiri, "fatura_tarihi"
    raise ValueError("Kaynak bağlantısı yalnız satış / alış iadesi için düzenlenir.")


def _kaynak_uygun_mu(iade, fatura, rapor_turu: str) -> str | None:
    if fatura is None:
        return "Seçilen fatura bulunamadı."
    if int(fatura.cari_id) != int(iade.cari_id):
        return "Seçilen fatura iadenin carisine ait değil."
    if (fatura.durum or "").upper() == "İPTAL" or getattr(fatura, "is_deleted", False):
        return "İptal / silinmiş fatura kaynak seçilemez."
    if rapor_turu == SATIS_IADE and not getattr(fatura, "onaylandi", False):
        return "Onaylanmamış satış faturası kaynak seçilemez."
    if fatura.fatura_tarihi > iade.iade_tarihi:
        return "Kaynak fatura iade tarihinden sonra olamaz."
    return None


def kaynak_adaylari(rapor_turu: str, iade_id: int, *, limit: int = 200) -> list[dict]:
    """Kullanıcının seçebileceği faturalar: aynı cari, iade tarihine kadar, iptal olmayan.

    Sıralama yalnız kolaylık içindir (iadedeki ürünlerden kaçını içerdiği, sonra tarih); seçim
    kullanıcınındır, program bağlantı kurmaz.
    """
    from sqlalchemy.orm import selectinload

    iade_m, _, fat_m, _, _ = _iade_modelleri(rapor_turu)
    with get_session() as session:
        iade = session.get(iade_m, int(iade_id))
        if iade is None:
            raise ValueError("İade bulunamadı.")
        urunler = {(s.urun_kodu or "").strip() for s in iade.satirlar}
        q = (select(fat_m).options(selectinload(fat_m.satirlar))
             .where(fat_m.cari_id == iade.cari_id, fat_m.fatura_tarihi <= iade.iade_tarihi,
                    fat_m.durum != "İPTAL")
             .order_by(fat_m.fatura_tarihi.desc(), fat_m.id.desc()).limit(int(limit) * 3))
        sonuc = []
        for f in session.scalars(q):
            if _kaynak_uygun_mu(iade, f, rapor_turu):
                continue
            ortak = urunler & {(s.urun_kodu or "").strip() for s in f.satirlar}
            sonuc.append({"id": int(f.id), "no": f.fatura_no, "tarih": f.fatura_tarihi,
                          "toplam": Decimal(str(f.tl_genel_toplam or 0)), "ortak_urun": len(ortak),
                          "urun_sayisi": len(urunler), "secili": int(f.id) == int(iade.kaynak_fatura_id or 0)})
        sonuc.sort(key=lambda r: (-r["ortak_urun"], -r["tarih"].toordinal(), -r["id"]))
        return sonuc[:limit]


def kaynak_bagla(rapor_turu: str, iade_id: int, fatura_id: int) -> dict:
    """İadeyi kullanıcının seçtiği faturaya bağlar. Tutar, stok, cari ve muhasebe fişi değişmez."""
    yetki_zorunlu(DUZENLEME_YETKISI, mesaj="İade kaynak bağlantısını düzenleme yetkiniz yok.")
    from sqlalchemy import func

    iade_m, iade_satir_m, fat_m, fat_satir_m, _ = _iade_modelleri(rapor_turu)
    with get_session() as session:
        iade = session.get(iade_m, int(iade_id))
        if iade is None:
            raise ValueError("İade bulunamadı.")
        if (iade.durum or "").upper() == "İPTAL":
            raise ValueError("İptal edilmiş iade düzenlenemez.")
        fatura = session.get(fat_m, int(fatura_id))
        if hata := _kaynak_uygun_mu(iade, fatura, rapor_turu):
            raise ValueError(hata)
        eski = iade.kaynak_fatura_id
        iade.kaynak_fatura_id = int(fatura.id)
        bagli, bagsiz = 0, []
        if rapor_turu == SATIS_IADE:
            for st in iade.satirlar:
                if st.kaynak_fatura_satiri_id:
                    continue
                adaylar = [k for k in fatura.satirlar if (k.urun_kodu or "").strip() == (st.urun_kodu or "").strip()]
                if len(adaylar) != 1:
                    bagsiz.append(f"{st.urun_kodu} ({'faturada yok' if not adaylar else 'faturada birden çok satır'})")
                    continue
                kaynak = adaylar[0]
                iade_edilen = session.scalar(
                    select(func.coalesce(func.sum(iade_satir_m.miktar), 0))
                    .join(iade_m, iade_m.id == iade_satir_m.iade_id)
                    .where(iade_satir_m.kaynak_fatura_satiri_id == kaynak.id, iade_m.durum != "İPTAL")) or 0
                if Decimal(str(iade_edilen)) + Decimal(str(st.miktar)) > Decimal(str(kaynak.miktar)):
                    bagsiz.append(f"{st.urun_kodu} (iade miktarı faturadaki kalan miktarı aşıyor)")
                    continue
                st.kaynak_fatura_satiri_id = int(kaynak.id)
                bagli += 1
        no, fno = iade.iade_no, fatura.fatura_no
    _iz("IADE_KAYNAK_BAGLA", bilgi_turu(rapor_turu), iade_id, no, {"kaynak_fatura_id": eski},
        {"kaynak_fatura_id": int(fatura_id), "kaynak_no": fno, "satir_baglandi": bagli, "bagsiz": bagsiz})
    return {"iade_no": no, "fatura_no": fno, "satir_baglandi": bagli, "bagsiz": bagsiz}


def kaynak_yok_kaydet(rapor_turu: str, iade_id: int, neden: str) -> None:
    """Geçmiş / devir işlemi nedeniyle kaynak belgenin programda olmadığını açıkça kaydeder.

    Satış iadesinde mevcut satır alanları (``kaynak_yok_onay`` / gerekçe) kullanılır; alış iadesinde
    stok / kur farkı kararlarını etkileyen satır alanlarına dokunulmaz, not ``kdv_belge_bilgileri``ne yazılır.
    """
    yetki_zorunlu(DUZENLEME_YETKISI, mesaj="İade kaynak bilgisini düzenleme yetkiniz yok.")
    neden = (neden or "").strip()
    if not neden:
        raise ValueError("Kaynak belgenin neden olmadığını yazın (ör. 'Devir öncesi satış').")
    iade_m = _iade_modelleri(rapor_turu)[0]
    kullanici = oturum.ad_soyad or oturum.kullanici_adi or ""
    if rapor_turu == ALIS_IADE:
        _tablo_hazirla()
    with get_session() as session:
        iade = session.get(iade_m, int(iade_id))
        if iade is None:
            raise ValueError("İade bulunamadı.")
        if iade.kaynak_fatura_id:
            raise ValueError("İade bir kaynak faturaya bağlı; önce bağlantının doğru olup olmadığını kontrol edin.")
        if rapor_turu == SATIS_IADE:
            for st in iade.satirlar:
                if not st.kaynak_fatura_satiri_id and not st.kaynak_yok_onay:
                    st.kaynak_yok_onay = True
                    st.kaynak_yok_gerekce = neden[:300]
                    if hasattr(st, "kaynak_yok_kullanici"):
                        st.kaynak_yok_kullanici = kullanici
                    if hasattr(st, "kaynak_yok_tarih"):
                        st.kaynak_yok_tarih = datetime.now()
        else:
            _kaydet(session, ALIS_IADE, iade_id, {"kaynak_yok_nedeni": neden[:300]})
        no = iade.iade_no
    _iz("IADE_KAYNAK_YOK", bilgi_turu(rapor_turu), iade_id, no, None, {"neden": neden})
