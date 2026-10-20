"""SGK / MPHB / ödeme kanıt takibi — resmî portal gönderimi yok."""

from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select

from database.access import yetki_zorunlu, yazma_zorunlu
from database.database import get_session
from database.models.personel import (
    SGK_HAZIRLANACAK,
    SGK_HAZIRLANDI,
    SGK_ISLEM_CIKIS,
    SGK_ISLEM_GIRIS,
    SGK_ISLEM_MPHB,
    SGK_ISLEM_PRIM,
    SGK_RESMI_ONAY,
    Personel,
    PersonelMevzuatParametre,
    PersonelSgkBaglanti,
    PersonelSgkIslem,
)
from database.personel_sema import schema_hazirla
from database.personel_service import _kullanici, _para, _tarih

OKU = ("personel_sgk_goruntuleme", "personel_sgk_duzenleme", "personel_goruntuleme")
YAZ = ("personel_sgk_duzenleme", "personel_duzenleme")


def _param(session, kod: str, referans: date | None = None) -> PersonelMevzuatParametre | None:
    referans = referans or date.today()
    return session.scalar(
        select(PersonelMevzuatParametre)
        .where(
            PersonelMevzuatParametre.kod == kod,
            PersonelMevzuatParametre.aktif.is_(True),
            PersonelMevzuatParametre.yururluk_baslangic <= referans,
            or_(
                PersonelMevzuatParametre.yururluk_bitis.is_(None),
                PersonelMevzuatParametre.yururluk_bitis >= referans,
            ),
        )
        .order_by(PersonelMevzuatParametre.yururluk_baslangic.desc())
    )


def son_tarih_hesapla(islem_turu: str, referans: date, **ctx) -> dict[str, Any]:
    """Sürümlü kural + resmi kaynak; istisna/tatil uzatması ayrı parametre ister."""
    schema_hazirla()
    with get_session() as session:
        if islem_turu == SGK_ISLEM_GIRIS:
            p = _param(session, "SGK_4A_ISE_GIRIS", referans)
            if not p:
                raise ValueError("İşe giriş bildirim süresi parametresi yok [2].")
            d = json.loads(p.deger_json)
            gun = int(d.get("gun_oncesi", 1))
            return {
                "son_tarih": referans - timedelta(days=gun),
                "kural": p.kod,
                "surum": p.surum,
                "kaynak": p.resmi_kaynak,
                "aciklama": d.get("aciklama"),
            }
        if islem_turu == SGK_ISLEM_CIKIS:
            p = _param(session, "SGK_4A_AYRILIS", referans)
            if not p:
                raise ValueError("Ayrılış bildirim süresi parametresi yok [2].")
            d = json.loads(p.deger_json)
            gun = int(d.get("gun_sonra", 10))
            return {
                "son_tarih": referans + timedelta(days=gun),
                "kural": p.kod,
                "surum": p.surum,
                "kaynak": p.resmi_kaynak,
                "aciklama": d.get("aciklama"),
            }
        if islem_turu == SGK_ISLEM_MPHB:
            p = _param(session, "SGK_4A_MPHB", referans)
            if not p:
                raise ValueError("MPHB son tarih parametresi yok [2][4].")
            d = json.loads(p.deger_json)
            yil = int(ctx.get("donem_yil") or referans.year)
            ay = int(ctx.get("donem_ay") or referans.month)
            # Takip eden ayın 26'sı
            if ay == 12:
                ty, ta = yil + 1, 1
            else:
                ty, ta = yil, ay + 1
            gun = int(d.get("takip_ay_gun", 26))
            return {
                "son_tarih": date(ty, ta, gun),
                "kural": p.kod,
                "surum": p.surum,
                "kaynak": p.resmi_kaynak,
                "aciklama": d.get("aciklama"),
                "not": "Vergi ödeme süresi ayrı takip edilir; tek tarihte birleştirilmez.",
            }
        if islem_turu == SGK_ISLEM_PRIM:
            p = _param(session, "SGK_4A_PRIM_ODEME", referans)
            if not p:
                raise ValueError("Prim ödeme son tarih parametresi yok [2].")
            d = json.loads(p.deger_json)
            yil = int(ctx.get("donem_yil") or referans.year)
            ay = int(ctx.get("donem_ay") or referans.month)
            if ay == 12:
                ty, ta = yil + 1, 1
            else:
                ty, ta = yil, ay + 1
            son_gun = calendar.monthrange(ty, ta)[1]
            return {
                "son_tarih": date(ty, ta, son_gun),
                "kural": p.kod,
                "surum": p.surum,
                "kaynak": p.resmi_kaynak,
                "aciklama": d.get("aciklama"),
                "not": "Vergi ödeme takvimi ayrıca doğrulanmalıdır.",
            }
        raise ValueError(f"Son tarih kuralı tanımlı değil: {islem_turu}")


class PersonelSgkService:
    @staticmethod
    def kaydet(veri: dict) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        # Taslak yükleme / bağlantı açma = bildirim gönderildi sayılmaz
        durum = (veri.get("durum") or SGK_HAZIRLANACAK).upper()
        if durum == "GONDERILDI" or durum == "TAMAMLANDI":
            raise ValueError(
                "Resmî gönderim entegrasyonu yok. "
                "Durum olarak 'Resmî onay belgesi kaydedildi' kullanın; "
                "onay numarası ve çıktı ekleyin."
            )

        with get_session() as session:
            if veri.get("id"):
                islem = session.get(PersonelSgkIslem, int(veri["id"]))
                if islem is None:
                    raise ValueError("SGK işlemi bulunamadı.")
                islem_turu = (veri.get("islem_turu") or islem.islem_turu or "").upper()
            else:
                islem_turu = (veri.get("islem_turu") or "").upper()
                if not islem_turu:
                    raise ValueError("İşlem türü zorunlu.")
            if not veri.get("id"):
                # MPHB: işyeri+dönem tek ana kayıt
                if islem_turu == SGK_ISLEM_MPHB:
                    isyeri = (veri.get("isyeri_kodu") or "").strip()
                    yil, ay = int(veri["donem_yil"]), int(veri["donem_ay"])
                    nitelik = (veri.get("nitelik") or "ASIL").upper()
                    mevcut = session.scalar(
                        select(PersonelSgkIslem).where(
                            PersonelSgkIslem.islem_turu == SGK_ISLEM_MPHB,
                            PersonelSgkIslem.isyeri_kodu == isyeri,
                            PersonelSgkIslem.donem_yil == yil,
                            PersonelSgkIslem.donem_ay == ay,
                            PersonelSgkIslem.nitelik == nitelik,
                            PersonelSgkIslem.durum != "IPTAL",
                        )
                    )
                    if mevcut is not None:
                        raise ValueError(
                            "Bu işyeri/dönem için MPHB ana kaydı zaten var. "
                            "Personelleri bağlantı ile ekleyin; mükerrer beyan üretmeyin."
                        )
                islem = PersonelSgkIslem(
                    islem_turu=islem_turu,
                    entegrasyon_yok=True,
                    olusturan=_kullanici(),
                )
                session.add(islem)

            islem.islem_turu = islem_turu
            # Güncellemede yalnız verilen alanlar değişsin
            def _set(alan, deger, *, donustur=None):
                if alan not in veri:
                    return
                setattr(islem, alan, donustur(deger) if donustur else deger)

            _set("isyeri_kodu", veri.get("isyeri_kodu"))
            _set("isyeri_sicil", veri.get("isyeri_sicil"))
            _set("donem_yil", veri.get("donem_yil"))
            _set("donem_ay", veri.get("donem_ay"))
            if "nitelik" in veri or not veri.get("id"):
                islem.nitelik = veri.get("nitelik") or (
                    "ASIL" if islem_turu == SGK_ISLEM_MPHB else islem.nitelik
                )
            _set("personel_id", veri.get("personel_id"))
            _set("donem_id", veri.get("donem_id"))
            _set("baslangic_tarihi", veri.get("baslangic_tarihi"), donustur=_tarih)
            _set("bildirim_tarihi", veri.get("bildirim_tarihi"), donustur=_tarih)
            _set("onay_no", veri.get("onay_no"))
            _set("onay_tarihi", veri.get("onay_tarihi"), donustur=_tarih)
            if "sgk_tahakkuk" in veri:
                islem.sgk_tahakkuk = (
                    _para(veri["sgk_tahakkuk"]) if veri.get("sgk_tahakkuk") not in (None, "") else None
                )
            if "vergi_tahakkuk" in veri:
                islem.vergi_tahakkuk = (
                    _para(veri["vergi_tahakkuk"]) if veri.get("vergi_tahakkuk") not in (None, "") else None
                )
            _set("sgk_odeme_durum", veri.get("sgk_odeme_durum"))
            _set("vergi_odeme_durum", veri.get("vergi_odeme_durum"))
            _set("sgk_odeme_son_tarih", veri.get("sgk_odeme_son_tarih"), donustur=_tarih)
            _set("vergi_odeme_son_tarih", veri.get("vergi_odeme_son_tarih"), donustur=_tarih)
            if "hazirlayan" in veri or not veri.get("id"):
                islem.hazirlayan = veri.get("hazirlayan") or islem.hazirlayan or _kullanici()
            _set("aciklama", veri.get("aciklama"))
            _set("resmi_cikti_yolu", veri.get("resmi_cikti_yolu"))
            islem.entegrasyon_yok = True
            islem.guncelleme = datetime.now()

            # Durum: resmî onay belgesi olmadan tamamlandı gösterme
            if durum == SGK_RESMI_ONAY:
                if not islem.onay_no and not islem.resmi_cikti_yolu and not islem.onay_tarihi:
                    raise ValueError(
                        "Resmî onay belgesi kaydı için onay no, onay tarihi veya "
                        "resmî çıktı yolu gerekli. Taslak dosya yeterli değildir."
                    )
            islem.durum = durum

            # Son tarih (beyan ve ödeme ayrı)
            if veri.get("son_tarih"):
                islem.son_tarih = _tarih(veri["son_tarih"])
            elif islem_turu in (SGK_ISLEM_GIRIS, SGK_ISLEM_CIKIS, SGK_ISLEM_MPHB):
                ref = islem.baslangic_tarihi or date.today()
                try:
                    st = son_tarih_hesapla(
                        islem_turu,
                        ref,
                        donem_yil=islem.donem_yil,
                        donem_ay=islem.donem_ay,
                    )
                    islem.son_tarih = st["son_tarih"]
                    islem.son_tarih_kural = f"{st['kural']}:{st['surum']}"
                    islem.son_tarih_kaynak = st["kaynak"]
                except ValueError:
                    pass

            session.flush()

            # Personel bağlantıları (MPHB)
            for pid in veri.get("personel_ids") or []:
                PersonelSgkService._bagla(session, islem.id, int(pid), veri.get("donem_id"))

            return PersonelSgkService._dict(islem, session)

    @staticmethod
    def _bagla(session, sgk_id: int, personel_id: int, donem_id=None) -> None:
        if session.get(Personel, personel_id) is None:
            raise ValueError(f"Personel bulunamadı: {personel_id}")
        mevcut = session.scalar(
            select(PersonelSgkBaglanti).where(
                PersonelSgkBaglanti.sgk_islem_id == sgk_id,
                PersonelSgkBaglanti.personel_id == personel_id,
            )
        )
        if mevcut is None:
            session.add(
                PersonelSgkBaglanti(
                    sgk_islem_id=sgk_id,
                    personel_id=personel_id,
                    donem_id=donem_id,
                )
            )

    @staticmethod
    def bagla_personel(sgk_islem_id: int, personel_id: int, donem_id=None) -> None:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        with get_session() as session:
            islem = session.get(PersonelSgkIslem, int(sgk_islem_id))
            if islem is None:
                raise ValueError("SGK işlemi bulunamadı.")
            PersonelSgkService._bagla(session, islem.id, int(personel_id), donem_id)

    @staticmethod
    def durum_guncelle(sgk_id: int, durum: str, **kanit) -> dict:
        yazma_zorunlu(*YAZ)
        schema_hazirla()
        return PersonelSgkService.kaydet({"id": sgk_id, "durum": durum, **kanit})

    @staticmethod
    def listele(
        *,
        islem_turu: str | None = None,
        isyeri_kodu: str | None = None,
        yil: int | None = None,
        ay: int | None = None,
        personel_id: int | None = None,
    ) -> list[dict]:
        yetki_zorunlu(*OKU)
        schema_hazirla()
        with get_session() as session:
            q = select(PersonelSgkIslem).order_by(PersonelSgkIslem.id.desc())
            if islem_turu:
                q = q.where(PersonelSgkIslem.islem_turu == islem_turu)
            if isyeri_kodu:
                q = q.where(PersonelSgkIslem.isyeri_kodu == isyeri_kodu)
            if yil:
                q = q.where(PersonelSgkIslem.donem_yil == int(yil))
            if ay:
                q = q.where(PersonelSgkIslem.donem_ay == int(ay))
            if personel_id:
                bagli = select(PersonelSgkBaglanti.sgk_islem_id).where(
                    PersonelSgkBaglanti.personel_id == int(personel_id)
                )
                q = q.where(
                    or_(
                        PersonelSgkIslem.personel_id == int(personel_id),
                        PersonelSgkIslem.id.in_(bagli),
                    )
                )
            return [PersonelSgkService._dict(i, session) for i in session.scalars(q.limit(300)).all()]

    @staticmethod
    def _dict(islem: PersonelSgkIslem, session) -> dict:
        baglar = session.scalars(
            select(PersonelSgkBaglanti).where(PersonelSgkBaglanti.sgk_islem_id == islem.id)
        ).all()
        return {
            "id": islem.id,
            "islem_turu": islem.islem_turu,
            "isyeri_kodu": islem.isyeri_kodu,
            "isyeri_sicil": islem.isyeri_sicil,
            "donem_yil": islem.donem_yil,
            "donem_ay": islem.donem_ay,
            "nitelik": islem.nitelik,
            "durum": islem.durum,
            "personel_id": islem.personel_id,
            "baslangic_tarihi": islem.baslangic_tarihi.isoformat() if islem.baslangic_tarihi else None,
            "bildirim_tarihi": islem.bildirim_tarihi.isoformat() if islem.bildirim_tarihi else None,
            "son_tarih": islem.son_tarih.isoformat() if islem.son_tarih else None,
            "son_tarih_kural": islem.son_tarih_kural,
            "son_tarih_kaynak": islem.son_tarih_kaynak,
            "onay_no": islem.onay_no,
            "onay_tarihi": islem.onay_tarihi.isoformat() if islem.onay_tarihi else None,
            "sgk_tahakkuk": float(islem.sgk_tahakkuk) if islem.sgk_tahakkuk is not None else None,
            "vergi_tahakkuk": float(islem.vergi_tahakkuk) if islem.vergi_tahakkuk is not None else None,
            "sgk_odeme_durum": islem.sgk_odeme_durum,
            "vergi_odeme_durum": islem.vergi_odeme_durum,
            "sgk_odeme_son_tarih": (
                islem.sgk_odeme_son_tarih.isoformat() if islem.sgk_odeme_son_tarih else None
            ),
            "vergi_odeme_son_tarih": (
                islem.vergi_odeme_son_tarih.isoformat() if islem.vergi_odeme_son_tarih else None
            ),
            "hazirlayan": islem.hazirlayan,
            "aciklama": islem.aciklama,
            "entegrasyon_yok": True,
            "resmi_gonderim_yok": True,
            "bagli_personel_ids": [b.personel_id for b in baglar],
            "uyari": "Resmî portal entegrasyonu yok; durum hazırlık ve kanıt takibidir.",
        }
