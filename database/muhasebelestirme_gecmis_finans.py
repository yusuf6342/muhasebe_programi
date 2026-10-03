"""Geçmiş finans evraklarının (tahsilat, ödeme, makbuz, havale, virman) muhasebeleştirme önizlemesi.

Kayıtlar yalnız kalıcı bağlantıyla sınıflanır; açıklama, tutar veya tarih benzerliği kullanılmaz:

- kesin: evrak kimliği programın kendi yazdığı yapıdan kanıtlanıyor (evrak tablosu satırı veya
  ``THS-``/``ODM-`` cari hareketi + aynı belge numaralı tek "CARİ TAHSİLAT/ÖDEME" kasa/banka
  hareketi gibi). Kullanıcı seçerse bekleyenler listesine alınır; fiş kendiliğinden oluşmaz.
- belirsiz: kaynak evrak kanıtlanamıyor (Excel aktarımı, eksik/çift hareket). Listeye alınamaz,
  mevcut fişle eşleştirilmez.
- karar_bekliyor: kimlik kesin ama iş kuralı tanımlı olmayan kalem içeriyor (POS, KMH...).
- muhasebelestirilmis: firma + kaynak türü + kaynak id ile bağlı etkin fişi var.
- listede: zaten muhasebeleştirme durum kaydı var.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select

from database.finans_evrak_kimligi import (
    EVRAK_BANKA_HAVALE,
    EVRAK_CARI_ODEME,
    EVRAK_CARI_TAHSILAT,
    EVRAK_CARI_VIRMAN,
    EVRAK_KASA_BANKA_VIRMAN,
    tablo_hazirla,
)
from database.models.cari import Cari, CariIslem
from database.models.finans import (
    CariVirmanMakbuzu,
    FinansEvrakKimligi,
    FinansHareketi,
    KasaMakbuzu,
)
from database.models.genel_muhasebe import MuhasebeBelgeDurumu, MuhasebeFisi
from database.muhasebe_entegrasyon import (
    ESKI_KAYNAK_CARI_ODEME,
    ESKI_KAYNAK_CARI_TAHSILAT,
    EVRAKLAR,
    MuhasebeEntegrasyonService,
)
from database.muhasebe_service import decimal

FINANS_EVRAKLARI = (
    EVRAK_CARI_TAHSILAT, EVRAK_CARI_ODEME, "kasa_makbuzu", EVRAK_KASA_BANKA_VIRMAN, EVRAK_BANKA_HAVALE,
    EVRAK_CARI_VIRMAN, "cari_virman_makbuzu",
)
KATEGORILER = ("kesin", "belirsiz", "karar_bekliyor", "muhasebelestirilmis", "listede")
_KIMLIKLI = (EVRAK_CARI_TAHSILAT, EVRAK_CARI_ODEME, EVRAK_KASA_BANKA_VIRMAN, EVRAK_BANKA_HAVALE, EVRAK_CARI_VIRMAN)
_VIRMAN_TURLERI = MuhasebeEntegrasyonService.VIRMAN_HAREKETLERI
# Başka bir evrak türünün parçası olan cari hareket belge önekleri (kendi türünde sayılır)
_BASKA_EVRAK_ONEKLERI = ("TMK-", "OMK-", "AHV-", "GHV-", "VRM-", "CVR-")
_KARAR_ONEKLERI = {
    "POS-": "POS ile tahsilat: POS/valör hesabının muhasebe kuralı karar bekliyor",
    "KKO-": "Şirket kredi kartıyla ödeme: kredi kartı borcu hesabı kuralı karar bekliyor",
    "KKC-": "Kredi kartı çekimi: kural karar bekliyor",
}
_BELIRSIZ_NEDENLERI = {
    "EVB-": "Excel/eski sistem aktarımı: kasa/banka hareketi yok, kaynak evrak kanıtlanamıyor",
    "ACS-": "Açılış/devir kaydı: tahsilat evrakı değil, kasa/banka hareketi yok",
    "VCS-": "Açılış/devir kaydı: ödeme evrakı değil, kasa/banka hareketi yok",
}


def _bos() -> dict[str, list[dict]]:
    return {k: [] for k in KATEGORILER}


def onizle(session, firma_id: int) -> dict[str, dict[str, list[dict]]]:
    """Tür → kategori → kayıt listesi. Hiçbir şey yazmaz."""
    tablo_hazirla(session)
    sonuc = {e: _bos() for e in FINANS_EVRAKLARI}
    durumlar = {
        (e, int(k)): d for e, k, d in session.execute(
            select(MuhasebeBelgeDurumu.evrak_turu, MuhasebeBelgeDurumu.kaynak_id, MuhasebeBelgeDurumu.durum)
            .where(MuhasebeBelgeDurumu.firma_id == firma_id, MuhasebeBelgeDurumu.evrak_turu.in_(FINANS_EVRAKLARI)))
    }
    etkin_fis = {
        (t, int(k)) for t, k in session.execute(
            select(MuhasebeFisi.kaynak_turu, MuhasebeFisi.kaynak_id).where(
                MuhasebeFisi.firma_id == firma_id, MuhasebeFisi.kaynak_turu.is_not(None),
                MuhasebeFisi.durum != "İptal"))
        if k is not None
    }
    kimlikler = {(k.evrak_turu, k.belge_no): k for k in session.scalars(
        select(FinansEvrakKimligi).where(FinansEvrakKimligi.evrak_turu.in_(_KIMLIKLI)))}
    cari_adlari = dict(session.execute(select(Cari.id, Cari.unvan)).all())
    hareketler: dict[str, list[FinansHareketi]] = defaultdict(list)
    for h in session.scalars(select(FinansHareketi)):
        hareketler[h.belge_no].append(h)
    cari_islemler: dict[str, list[CariIslem]] = defaultdict(list)
    for i in session.scalars(select(CariIslem)):
        cari_islemler[i.belge_no].append(i)

    def ekle(evrak, kategori, anahtar, belge_no, tarih, cari_id, tutar, neden=None, kaynak_id=None):
        sonuc[evrak][kategori].append({
            "evrak_turu": evrak, "anahtar": anahtar, "kaynak_id": kaynak_id, "belge_no": belge_no,
            "tarih": tarih, "cari_adi": cari_adlari.get(cari_id) if cari_id else None,
            "tutar": decimal(tutar or 0), "neden": neden,
        })

    def sinifla(evrak, kaynak_turu, kaynak_id, karar_fn=None):
        """Kimliği kesin evrak için: listede / muhasebeleştirilmiş / karar bekliyor / kesin."""
        if kaynak_id is not None:
            if (evrak, kaynak_id) in durumlar:
                return "listede", f"Durum: {durumlar[(evrak, kaynak_id)]}"
            if (kaynak_turu, kaynak_id) in etkin_fis:
                return "muhasebelestirilmis", "Bağlı etkin fiş var"
        if karar_fn is not None:
            karar = karar_fn()
            if karar:
                return "karar_bekliyor", karar
        return "kesin", None

    # --- cari tahsilat / ödeme (cari kartından) ---
    for evrak, onek, islem_turu, hareket_turu, eski_kaynak in (
        (EVRAK_CARI_TAHSILAT, "THS-", "Tahsilat", "CARİ TAHSİLAT", ESKI_KAYNAK_CARI_TAHSILAT),
        (EVRAK_CARI_ODEME, "ODM-", "Ödeme", "CARİ ÖDEME", ESKI_KAYNAK_CARI_ODEME),
    ):
        kaynak_turu = EVRAKLAR[evrak]["kaynaklar"][0]
        for no, islemler in cari_islemler.items():
            ilgili = [i for i in islemler if (i.islem_turu or "") == islem_turu]
            if not ilgili:
                continue
            if no.startswith(_BASKA_EVRAK_ONEKLERI):
                continue
            i = ilgili[0]
            tutar = decimal(i.alacak or 0) + decimal(i.borc or 0)
            kimlik = kimlikler.get((evrak, no))
            if (eski_kaynak, int(i.id)) in etkin_fis:
                ekle(evrak, "muhasebelestirilmis", no, no, i.tarih, i.cari_id, tutar,
                     "Eski sürüm fişi cari harekete bağlı", kimlik.id if kimlik else None)
                continue
            if no.startswith(tuple(_KARAR_ONEKLERI)):
                ekle(evrak, "karar_bekliyor", no, no, i.tarih, i.cari_id, tutar, _KARAR_ONEKLERI[no[:4]])
                continue
            if not no.startswith(onek):
                ekle(evrak, "belirsiz", no, no, i.tarih, i.cari_id, tutar, _BELIRSIZ_NEDENLERI.get(
                    no[:4], "Cari kartı tahsilat/ödeme evrakı değil; kaynak evrak kanıtlanamıyor"))
                continue
            fh = [h for h in hareketler.get(no, []) if h.hareket_turu == hareket_turu]
            if len(islemler) != 1 or len(fh) != 1 or decimal(fh[0].tutar) != tutar:
                ekle(evrak, "belirsiz", no, no, i.tarih, i.cari_id, tutar,
                     "Aynı belge numarasında tek cari hareket + tek kasa/banka hareketi yok")
                continue
            kid = kimlik.id if kimlik else None
            kategori, neden = sinifla(evrak, kaynak_turu, kid, lambda: MuhasebeEntegrasyonService
                                      ._finans_hesabi_destek_disi(fh[0].hesap))
            ekle(evrak, kategori, no, no, i.tarih, i.cari_id, tutar, neden, kid)

    # --- kasa makbuzu ---
    for m in session.scalars(select(KasaMakbuzu).where(KasaMakbuzu.durum != "IPTAL")):
        kategori, neden = sinifla("kasa_makbuzu", "kasa_makbuzu", int(m.id), lambda m=m: MuhasebeEntegrasyonService
                                  .karar_bekleyen_neden("kasa_makbuzu", m.id, session=session))
        ekle("kasa_makbuzu", kategori, int(m.id), m.belge_no, m.tarih, m.cari_id, m.tutar, neden, int(m.id))

    # --- kasa / banka virmanı ---
    for no, hs in hareketler.items():
        turler = _VIRMAN_TURLERI.get(no.split("-", 1)[0])
        if turler is None:
            continue
        cikis = [h for h in hs if h.hareket_turu == turler[0]]
        giris = [h for h in hs if h.hareket_turu == turler[1]]
        kimlik = kimlikler.get((EVRAK_KASA_BANKA_VIRMAN, no))
        if len(cikis) != 1 or len(giris) != 1 or len(hs) != 2 or decimal(cikis[0].tutar) != decimal(giris[0].tutar):
            ekle(EVRAK_KASA_BANKA_VIRMAN, "belirsiz", no, no, hs[0].tarih, None, hs[0].tutar,
                 "Belgede beklenen çıkış + giriş hareket çifti yok")
            continue
        kid = kimlik.id if kimlik else None
        kategori, neden = sinifla(
            EVRAK_KASA_BANKA_VIRMAN, EVRAK_KASA_BANKA_VIRMAN, kid,
            lambda c=cikis[0], g=giris[0]: MuhasebeEntegrasyonService._finans_hesabi_destek_disi(c.hesap)
            or MuhasebeEntegrasyonService._finans_hesabi_destek_disi(g.hesap))
        ekle(EVRAK_KASA_BANKA_VIRMAN, kategori, no, no, cikis[0].tarih, None, cikis[0].tutar, neden, kid)

    # --- alınan / gönderilen havale ---
    for no, hs in hareketler.items():
        if not no.startswith(("AHV-", "GHV-")):
            continue
        tur = "ALINAN HAVALE" if no.startswith("AHV-") else "GÖNDERİLEN HAVALE"
        banka = [h for h in hs if h.hareket_turu == tur]
        islemler = cari_islemler.get(no, [])
        kimlik = kimlikler.get((EVRAK_BANKA_HAVALE, no))
        tutar = decimal(banka[0].tutar) if banka else decimal(hs[0].tutar)
        if len(banka) != 1 or len(islemler) != 1 or (
                decimal(islemler[0].alacak or 0) + decimal(islemler[0].borc or 0)) != tutar:
            ekle(EVRAK_BANKA_HAVALE, "belirsiz", no, no, hs[0].tarih, islemler[0].cari_id if islemler else None,
                 tutar, "Belgede tek banka hareketi + tek cari hareket yok")
            continue
        kid = kimlik.id if kimlik else None
        kategori, neden = sinifla(EVRAK_BANKA_HAVALE, EVRAK_BANKA_HAVALE, kid,
                                  lambda b=banka[0]: MuhasebeEntegrasyonService._finans_hesabi_destek_disi(b.hesap))
        ekle(EVRAK_BANKA_HAVALE, kategori, no, no, banka[0].tarih, islemler[0].cari_id, tutar, neden, kid)

    # --- cari virman ---
    for no, islemler in cari_islemler.items():
        virman = [i for i in islemler if (i.islem_turu or "") == "Cari Virman"]
        if not virman:
            continue
        kaynak = [i for i in virman if decimal(i.alacak or 0) > 0]
        hedef = [i for i in virman if decimal(i.borc or 0) > 0]
        kimlik = kimlikler.get((EVRAK_CARI_VIRMAN, no))
        if len(kaynak) != 1 or len(hedef) != 1 or decimal(kaynak[0].alacak) != decimal(hedef[0].borc):
            ekle(EVRAK_CARI_VIRMAN, "belirsiz", no, no, virman[0].tarih, virman[0].cari_id,
                 virman[0].alacak or virman[0].borc, "Virmanın iki cari hareketi tutarlı değil")
            continue
        kid = kimlik.id if kimlik else None
        kategori, neden = sinifla(EVRAK_CARI_VIRMAN, EVRAK_CARI_VIRMAN, kid)
        ekle(EVRAK_CARI_VIRMAN, kategori, no, no, kaynak[0].tarih, kaynak[0].cari_id, kaynak[0].alacak, neden, kid)

    # --- cari virman makbuzu ---
    try:
        makbuzlar = list(session.scalars(select(CariVirmanMakbuzu).where(CariVirmanMakbuzu.durum != "IPTAL")))
    except Exception:  # eski DB: tablo yok
        makbuzlar = []
    for k in makbuzlar:
        kategori, neden = sinifla("cari_virman_makbuzu", "cari_virman_makbuzu", int(k.id))
        ekle("cari_virman_makbuzu", kategori, int(k.id), k.belge_no, k.tarih, k.musteri_id, k.tutar, neden, int(k.id))
    return sonuc


def ozet(onizleme: dict) -> dict[str, dict[str, int]]:
    return {e: {k: len(v) for k, v in kat.items()} for e, kat in onizleme.items()}


def kaynak_id_hazirla(session, evrak: str, anahtar) -> int:
    """Kesin kaydın muhasebeleştirme kaynak id'si (kimlikli türlerde kalıcı kimlik oluşturulur)."""
    from database.finans_evrak_kimligi import kimlik_al

    if evrak in ("kasa_makbuzu", "cari_virman_makbuzu"):
        return int(anahtar)
    cari_islem_id = None
    if evrak in (EVRAK_CARI_TAHSILAT, EVRAK_CARI_ODEME):
        cari_islem_id = session.scalar(select(CariIslem.id).where(CariIslem.belge_no == str(anahtar)))
    return kimlik_al(session, evrak, str(anahtar), cari_islem_id=cari_islem_id, kaynak="gecmis")


def toplam_tutar(kayitlar: list[dict]) -> Decimal:
    return sum((k["tutar"] for k in kayitlar), Decimal("0"))
