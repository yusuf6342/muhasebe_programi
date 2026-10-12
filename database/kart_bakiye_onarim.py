"""Kart bakiyesi geçmiş kayıt tarayıcısı ve onarımı.

Kesin sınıflar (otomatik uygulanabilir):

* ``EKSIK_KART_HAREKETI`` — geçerli ekstre ödemesinin kart hesabında karşılığı yok (eski sürüm yalnız banka
  çıkışı yazıyordu). Onarım: ödeme tarihli, aynı belge numaralı ``KK EKSTRE ÖDEME`` kart hesabına eklenir.
* ``KART_HESABINDA_GIDER_FISI`` — geçerli gider fişinin hareketi doğrudan kart hesabına ``GİDER FİŞİ`` (çıkış)
  olarak yazılmış; kart borcunu artırması gerekirken azaltıyor. Onarım: hareket türü ``KK GİDER`` (borç artışı).

Belirsiz sınıflar yalnız raporlanır (kasadan / bankadan kart hesabına giriş, tanınmayan hareket türü, türü
belirsiz kart hesabı). Banka iadesi, kart ödemesi iptali ve gerçek ekstre ödemeleri onarım dışıdır.

Uygulama: değişiklik varsa önce doğrulanmış yedek; tek işlemde yazılır, her satır günlüğe (eski / yeni değer,
kaynak, bakiye önce / sonra, yedek yolu, kullanıcı) kaydedilir. Yeniden çalıştırma aynı kaydı ikinci kez
onarmaz; ``geri_al`` günlükteki değişiklikleri geri çevirir.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from database.database import get_session
from database.models.finans import (
    FinansHareketi,
    FinansHesabi,
    GiderFisi,
    KartBakiyeOnarimGunlugu,
    KrediKartiEkstre,
    KrediKartiEkstreOdeme,
    KrediKartiTanimi,
)

SINIF_EKSIK_KART = "EKSIK_KART_HAREKETI"
SINIF_GIDER_FISI = "KART_HESABINDA_GIDER_FISI"
SINIF_KARTA_GIRIS = "KART_HESABINA_GIRIS"
SINIF_TANINMAYAN = "TANINMAYAN_HAREKET"
SINIF_HATALI_HESAP = "TURU_BELIRSIZ_KART_HESABI"

KART_HAREKETLERI = frozenset({
    "AÇILIŞ", "KK ÖDEME", "KK EKSTRE ÖDEME", "KK EKSTRE ÖDEME İPTAL", "KK İADE", "KK ÖDEME İPTAL", "KK GİDER",
    "KK ÖDEME DÜZELTME", "KK ÖDEME DÜZELTME EK",
})
KARTA_GIRIS_TURLERI = frozenset({"KASADAN BANKAYA YATAN", "BANKA VİRMAN GİRİŞ", "ALINAN HAVALE", "BANKA GİRİŞ",
                                 "VIRMAN GİRİŞ"})


def _d(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(Decimal("0.01"))


def _kart_hesaplari(s) -> dict[int, FinansHesabi]:
    return {int(h.id): h for h in s.scalars(select(FinansHesabi).where(
        FinansHesabi.alt_hesap_turu == "KREDI_KARTI")).all()}


def tara(session=None) -> dict:
    """Kuru çalıştırma: hiçbir kayıt değişmez."""
    if session is None:
        with get_session() as s:
            return tara(s)
    s = session
    kart_hesap = _kart_hesaplari(s)
    kesin, belirsiz, hatali = [], [], []

    for o, e in s.execute(select(KrediKartiEkstreOdeme, KrediKartiEkstre)
                          .join(KrediKartiEkstre, KrediKartiEkstre.id == KrediKartiEkstreOdeme.ekstre_id)
                          .where(KrediKartiEkstreOdeme.iptal.is_(False))
                          .order_by(KrediKartiEkstreOdeme.id)).all():
        bno = o.finans_belge_no or o.belge_no
        var = s.scalar(select(FinansHareketi.id).where(
            FinansHareketi.belge_no == bno, FinansHareketi.hareket_turu == "KK EKSTRE ÖDEME",
            FinansHareketi.hesap_id.in_(list(kart_hesap) or [-1])).limit(1))
        if var is not None:
            continue
        kart = s.get(KrediKartiTanimi, e.kredi_karti_id)
        hedef = next((h for h in kart_hesap.values() if kart and h.banka_karti_id == kart.banka_karti_id), None)
        kayit = {"sinif": SINIF_EKSIK_KART, "anahtar": f"EKSTRE_ODEME:{o.id}", "kaynak_turu": "kk_ekstre_odeme",
                 "kaynak_id": int(o.id), "belge_no": bno, "tarih": o.tarih, "tutar": _d(o.tutar),
                 "hesap_id": int(hedef.id) if hedef else None, "hesap": hedef.hesap_adi if hedef else None,
                 "eski": "kart hesabında hareket yok", "yeni": "KK EKSTRE ÖDEME (borç azalır)"}
        (kesin if hedef is not None else belirsiz).append(
            kayit if hedef is not None else {**kayit, "neden": "Kartın bankasında kredi kartı hesabı yok"})

    for h in s.scalars(select(FinansHareketi).where(
            FinansHareketi.hesap_id.in_(list(kart_hesap) or [-1])).order_by(FinansHareketi.id)).all():
        tur = (h.hareket_turu or "").strip().upper()
        temel = {"kaynak_turu": "finans_hareketi", "kaynak_id": int(h.id), "belge_no": h.belge_no, "tarih": h.tarih,
                 "tutar": _d(h.tutar), "hesap_id": int(h.hesap_id), "hesap": kart_hesap[int(h.hesap_id)].hesap_adi,
                 "hareket_turu": h.hareket_turu}
        if tur == "GİDER FİŞİ":
            fis = s.scalar(select(GiderFisi).where(GiderFisi.belge_no == h.belge_no))
            if fis is not None and (fis.durum or "").upper() != "IPTAL":
                kesin.append({**temel, "sinif": SINIF_GIDER_FISI, "anahtar": f"HAREKET:{h.id}",
                              "eski": "GİDER FİŞİ (borç azalır)", "yeni": "KK GİDER (borç artar)"})
            else:
                belirsiz.append({**temel, "sinif": SINIF_GIDER_FISI, "anahtar": f"HAREKET:{h.id}",
                                 "neden": "Gider fişi bulunamadı veya iptal; elle incelenmeli"})
        elif tur in KARTA_GIRIS_TURLERI:
            belirsiz.append({**temel, "sinif": SINIF_KARTA_GIRIS, "anahtar": f"HAREKET:{h.id}",
                             "neden": "Kart hesabına düz giriş: hangi ekstreye ödendiği bilinmiyor; ekstre seçilerek "
                                      "elle ödeme kaydına çevrilmeli"})
        elif tur not in KART_HAREKETLERI:
            belirsiz.append({**temel, "sinif": SINIF_TANINMAYAN, "anahtar": f"HAREKET:{h.id}",
                             "neden": "Kart hesabında beklenmeyen hareket türü"})

    for h in s.scalars(select(FinansHesabi).where(FinansHesabi.hesap_turu == "KREDİ KARTI")).all():
        if (h.alt_hesap_turu or "").upper() != "KREDI_KARTI":
            hatali.append({"sinif": SINIF_HATALI_HESAP, "hesap_id": int(h.id), "hesap": h.hesap_adi,
                           "alt_hesap_turu": h.alt_hesap_turu or "",
                           "neden": "Türü 'KREDİ KARTI' ama banka kartının kredi kartı alt hesabı değil; hareketleri "
                                    "kart borcuna / limite girmez"})
    return {"kesin": kesin, "belirsiz": belirsiz, "hatali_hesaplar": hatali,
            "ozet": {"kesin": len(kesin), "belirsiz": len(belirsiz), "hatali_hesap": len(hatali)}}


def _bakiye(s, hesap_id: int) -> Decimal:
    from database.finans_service import FinansService

    s.flush()
    h = s.get(FinansHesabi, int(hesap_id))
    s.refresh(h)
    return _d(FinansService.bakiye(h))


def uygula(*, db_yolu=None, yedek_zorunlu: bool = True) -> dict:
    """Yalnız kesin sınıfları onarır. Değişiklik varsa önce doğrulanmış yedek alınır."""
    from database.access import yazma_zorunlu
    from database.session_manager import oturum

    yazma_zorunlu("finans_duzenleme")
    on = tara()
    if not on["kesin"]:
        return {"onarim_kodu": None, "uygulanan": 0, "yedek_yolu": None, "tarama": on}
    yedek_yolu = None
    if yedek_zorunlu:
        import database.database as veritabani
        from database.gecis_guvenligi import dogrulanmis_yedek

        yol = db_yolu or getattr(veritabani.company_db, "_db_path", None)
        if not yol:
            raise RuntimeError("Veritabanı dosyası belirlenemedi; yedeksiz onarım yapılmaz.")
        yedek_yolu = str(dogrulanmis_yedek(yol, "kart_bakiye_onarim").yol)
    kod = f"KB-{datetime.now():%Y%m%d%H%M%S%f}"
    kullanici = (oturum.ad_soyad or oturum.kullanici_adi or "")[:120] or None
    uygulanan = []
    with get_session() as s:
        for k in tara(s)["kesin"]:
            once = _bakiye(s, k["hesap_id"])
            hareket_id = None
            if k["sinif"] == SINIF_EKSIK_KART:
                h = FinansHareketi(hesap_id=k["hesap_id"], tarih=k["tarih"], hareket_turu="KK EKSTRE ÖDEME",
                                   belge_no=k["belge_no"], tutar=k["tutar"],
                                   aciklama=f"Onarım {kod}: ekstre ödemesinin kart hesabı karşılığı")
                s.add(h)
                s.flush()
                hareket_id = int(h.id)
                o = s.get(KrediKartiEkstreOdeme, k["kaynak_id"])
                if o is not None and not o.kart_hesap_id:
                    o.kart_hesap_id = k["hesap_id"]
            else:
                h = s.get(FinansHareketi, k["kaynak_id"])
                h.hareket_turu = "KK GİDER"
                hareket_id = int(h.id)
            sonra = _bakiye(s, k["hesap_id"])
            s.add(KartBakiyeOnarimGunlugu(
                onarim_kodu=kod, anahtar=k["anahtar"], sinif=k["sinif"], kaynak_turu=k["kaynak_turu"],
                kaynak_id=k["kaynak_id"], belge_no=k["belge_no"], finans_hareketi_id=hareket_id,
                hesap_id=k["hesap_id"], tutar=k["tutar"], eski_deger=k["eski"], yeni_deger=k["yeni"],
                bakiye_once=once, bakiye_sonra=sonra, yedek_yolu=yedek_yolu, kullanici=kullanici))
            uygulanan.append({**k, "bakiye_once": once, "bakiye_sonra": sonra})
        from database.kredi_karti_ekstre_service import KrediKartiEkstreService as E

        for eid in {s.get(KrediKartiEkstreOdeme, k["kaynak_id"]).ekstre_id
                    for k in uygulanan if k["sinif"] == SINIF_EKSIK_KART}:
            e = s.get(KrediKartiEkstre, eid)
            E._taksit_durumlarini_esitle(s, e, s.get(KrediKartiTanimi, e.kredi_karti_id))
        s.flush()
    return {"onarim_kodu": kod, "uygulanan": len(uygulanan), "satirlar": uygulanan, "yedek_yolu": yedek_yolu,
            "tarama": on}


def geri_al(onarim_kodu: str) -> dict:
    """Onarım günlüğündeki değişiklikleri geri çevirir (eklenen hareket silinir, türü değişen eski türüne döner)."""
    from database.access import yazma_zorunlu

    yazma_zorunlu("finans_duzenleme")
    sayi = 0
    with get_session() as s:
        for g in s.scalars(select(KartBakiyeOnarimGunlugu).where(
                KartBakiyeOnarimGunlugu.onarim_kodu == onarim_kodu,
                KartBakiyeOnarimGunlugu.geri_alindi.is_(False))).all():
            h = s.get(FinansHareketi, g.finans_hareketi_id) if g.finans_hareketi_id else None
            if g.sinif == SINIF_EKSIK_KART:
                if h is not None:
                    s.delete(h)
            elif h is not None and h.hareket_turu == "KK GİDER":
                h.hareket_turu = "GİDER FİŞİ"
            g.geri_alindi = True
            g.geri_alma_zamani = datetime.now()
            sayi += 1
        s.flush()
    return {"onarim_kodu": onarim_kodu, "geri_alinan": sayi}
