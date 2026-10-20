"""Özlük belge arşivi — sürüm, hash, hassas erişim, imha."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from database.access import yetki_var, yetki_zorunlu, yazma_zorunlu
from database.database import get_session
from database.models.personel import (
    BELGE_DURUM_EKSIK,
    BELGE_DURUM_INCELENDI,
    BELGE_DURUM_SURESI_DOLDU,
    BELGE_DURUM_UYGULANMIYOR,
    BELGE_DURUM_YENILEME,
    BELGE_DURUM_YUKLENDI,
    BELGE_SINIF_KOSULLU,
    BELGE_SINIF_ZORUNLU,
    GIZLILIK_HASSAS_ADLI,
    GIZLILIK_HASSAS_SAGLIK,
    GIZLILIK_NORMAL,
    Personel,
    PersonelBelge,
    PersonelBelgeKategori,
    PersonelBelgeSurumu,
    PersonelBelgeTuru,
    PersonelErisimLog,
)
from database.personel_arsiv import arsivden_oku, dosyayi_arsive_kopyala
from database.personel_sema import schema_hazirla
from database.personel_service import _kullanici, _tarih
from database.session_manager import oturum

HASSAS = {GIZLILIK_HASSAS_SAGLIK, GIZLILIK_HASSAS_ADLI}


def _izin_setinde(*kodlar: str) -> bool:
    """Yönetici rolü tek başına hassas içeriğe yetmez; açık izin kodu gerekir."""
    izinler = set(oturum.permissions or ())
    return any(k in izinler for k in kodlar)


def hassas_gorur(gizlilik: str) -> bool:
    if gizlilik == GIZLILIK_HASSAS_SAGLIK:
        return _izin_setinde("personel_hassas_saglik", "personel_hassas_goruntuleme")
    if gizlilik == GIZLILIK_HASSAS_ADLI:
        return _izin_setinde("personel_hassas_adli", "personel_hassas_goruntuleme")
    return True


def _hassas_okuma_zorunlu(gizlilik: str) -> None:
    from database.access import aktif_firma_zorunlu, AccessError

    aktif_firma_zorunlu()
    if gizlilik not in HASSAS:
        yetki_zorunlu("personel_goruntuleme", "personel_duzenleme", "goruntuleme")
        return
    # Teknik yönetici tek başına sınırsız hassas erişim almasın — açık izin gerekir
    if not hassas_gorur(gizlilik):
        raise AccessError("Bu hassas özlük belgesine erişim yetkiniz yok.")


def _hassas_yazma_zorunlu(gizlilik: str) -> None:
    from database.access import aktif_firma_zorunlu, AccessError
    from database.donem_service import DonemService

    aktif_firma_zorunlu()
    if gizlilik not in HASSAS:
        yazma_zorunlu("personel_duzenleme", "duzenleme")
        return
    if not _izin_setinde("personel_hassas_duzenleme", "personel_hassas_goruntuleme"):
        raise AccessError("Hassas özlük belgesi yükleme/güncelleme yetkiniz yok.")
    if not DonemService.kayit_izinli_mi():
        raise AccessError("Seçili çalışma dönemi kapalı.")


def _log(session, islem: str, *, belge_id=None, surum_id=None, personel_id=None, ayrinti=None):
    session.add(
        PersonelErisimLog(
            kullanici=_kullanici(),
            islem=islem,
            belge_id=belge_id,
            surum_id=surum_id,
            personel_id=personel_id,
            ayrinti=(ayrinti or "")[:200] or None,
        )
    )


class PersonelBelgeService:
    @staticmethod
    def kategoriler() -> list[dict]:
        yetki_zorunlu("personel_goruntuleme", "personel_duzenleme", "goruntuleme")
        schema_hazirla()
        with get_session() as session:
            satirlar = session.scalars(
                select(PersonelBelgeKategori)
                .where(PersonelBelgeKategori.aktif.is_(True))
                .order_by(PersonelBelgeKategori.sira)
            ).all()
            return [
                {
                    "id": k.id,
                    "kod": k.kod,
                    "ad": k.ad,
                    "gizlilik": k.gizlilik,
                    "erisim": hassas_gorur(k.gizlilik) if k.gizlilik in HASSAS else True,
                }
                for k in satirlar
            ]

    @staticmethod
    def turler(kategori_id: int | None = None) -> list[dict]:
        yetki_zorunlu("personel_goruntuleme", "personel_duzenleme", "goruntuleme")
        schema_hazirla()
        with get_session() as session:
            q = select(PersonelBelgeTuru).where(PersonelBelgeTuru.aktif.is_(True))
            if kategori_id:
                q = q.where(PersonelBelgeTuru.kategori_id == int(kategori_id))
            return [
                {
                    "id": t.id,
                    "kategori_id": t.kategori_id,
                    "kod": t.kod,
                    "ad": t.ad,
                    "sinif": t.sinif,
                    "uygulanma_kosulu": t.uygulanma_kosulu,
                    "hukuki_dayanak": t.hukuki_dayanak,
                    "gizlilik": t.gizlilik,
                    "kritik_ise_baslama": t.kritik_ise_baslama,
                    "saklama_sure_yil": t.saklama_sure_yil,
                    "saklama_dayanak": t.saklama_dayanak,
                }
                for t in session.scalars(q.order_by(PersonelBelgeTuru.ad)).all()
            ]

    @staticmethod
    def personel_belgeleri(personel_id: int) -> list[dict]:
        yetki_zorunlu("personel_goruntuleme", "personel_duzenleme", "goruntuleme")
        schema_hazirla()
        with get_session() as session:
            turler = {
                t.id: t
                for t in session.scalars(select(PersonelBelgeTuru)).all()
            }
            belgeler = session.scalars(
                select(PersonelBelge).where(PersonelBelge.personel_id == int(personel_id))
            ).all()
            sonuc = []
            for b in belgeler:
                tur = turler.get(b.tur_id)
                giz = (tur.gizlilik if tur else GIZLILIK_NORMAL)
                if giz in HASSAS and not hassas_gorur(giz):
                    sonuc.append(
                        {
                            "id": b.id,
                            "tur_id": b.tur_id,
                            "tur_ad": tur.ad if tur else "?",
                            "durum": b.durum,
                            "gizlilik": giz,
                            "erisim_yok": True,
                            "surum_sayisi": len(b.surumler),
                        }
                    )
                    continue
                gecerli = next(
                    (s for s in b.surumler if s.id == b.gecerli_surum_id),
                    b.surumler[0] if b.surumler else None,
                )
                sonuc.append(
                    {
                        "id": b.id,
                        "tur_id": b.tur_id,
                        "tur_kod": tur.kod if tur else None,
                        "tur_ad": tur.ad if tur else "?",
                        "sinif": tur.sinif if tur else None,
                        "durum": b.durum,
                        "gizlilik": giz,
                        "erisim_yok": False,
                        "uygulanmiyor": b.uygulanmiyor,
                        "gecerli_surum_id": b.gecerli_surum_id,
                        "surum_sayisi": len(b.surumler),
                        "gecerlilik_tarihi": (
                            gecerli.gecerlilik_tarihi.isoformat()
                            if gecerli and gecerli.gecerlilik_tarihi
                            else None
                        ),
                        "belge_adi": gecerli.belge_adi if gecerli else None,
                        "kritik_ise_baslama": bool(tur.kritik_ise_baslama) if tur else False,
                    }
                )
            return sonuc

    @staticmethod
    def eksik_listesi(personel_id: int) -> list[dict]:
        """Yalnız uygulanabilir zorunlu/koşullu belgeler — koşul yoksa koşulluyu eksik sayma."""
        yetki_zorunlu("personel_goruntuleme", "personel_duzenleme", "goruntuleme")
        schema_hazirla()
        with get_session() as session:
            p = session.get(Personel, int(personel_id))
            if p is None:
                raise ValueError("Personel bulunamadı.")
            mevcut = {
                b.tur_id: b
                for b in session.scalars(
                    select(PersonelBelge).where(PersonelBelge.personel_id == int(personel_id))
                ).all()
            }
            eksikler = []
            for tur in session.scalars(
                select(PersonelBelgeTuru).where(PersonelBelgeTuru.aktif.is_(True))
            ).all():
                if tur.sinif == BELGE_SINIF_KOSULLU:
                    # Koşul metni var ama otomatik değerlendirme yoksa eksik alarmı üretme
                    continue
                if tur.sinif != BELGE_SINIF_ZORUNLU:
                    continue
                if tur.gizlilik in HASSAS and not hassas_gorur(tur.gizlilik):
                    continue
                b = mevcut.get(tur.id)
                if b is None or b.uygulanmiyor:
                    if b and b.uygulanmiyor:
                        continue
                    eksikler.append(
                        {
                            "tur_id": tur.id,
                            "tur_kod": tur.kod,
                            "tur_ad": tur.ad,
                            "durum": BELGE_DURUM_EKSIK,
                            "kritik_ise_baslama": tur.kritik_ise_baslama,
                            "hukuki_dayanak": tur.hukuki_dayanak,
                        }
                    )
                    continue
                if b.durum in (
                    BELGE_DURUM_EKSIK,
                    BELGE_DURUM_SURESI_DOLDU,
                    BELGE_DURUM_YENILEME,
                ):
                    eksikler.append(
                        {
                            "tur_id": tur.id,
                            "tur_kod": tur.kod,
                            "tur_ad": tur.ad,
                            "durum": b.durum,
                            "belge_id": b.id,
                            "kritik_ise_baslama": tur.kritik_ise_baslama,
                            "hukuki_dayanak": tur.hukuki_dayanak,
                        }
                    )
            return eksikler

    @staticmethod
    def yukle(
        personel_id: int,
        tur_id: int,
        kaynak_yol: str,
        *,
        belge_adi: str | None = None,
        duzenlenme_tarihi=None,
        gecerlilik_tarihi=None,
        yenileme_tarihi=None,
        donem: str | None = None,
        belge_no: str | None = None,
        barkod: str | None = None,
        duzenleyen_kurum: str | None = None,
        aciklama: str | None = None,
        hash_uyari_yoksay: bool = False,
    ) -> dict:
        yazma_zorunlu("personel_duzenleme", "duzenleme")
        schema_hazirla()
        kaynak = Path(kaynak_yol)
        if not kaynak.is_file():
            raise ValueError("Dosya bulunamadı.")

        with get_session() as session:
            p = session.get(Personel, int(personel_id))
            if p is None:
                raise ValueError("Personel bulunamadı; önce kartı kaydedin.")
            tur = session.get(PersonelBelgeTuru, int(tur_id))
            if tur is None or not tur.aktif:
                raise ValueError("Belge türü bulunamadı.")
            _hassas_yazma_zorunlu(tur.gizlilik)

            belge = session.scalar(
                select(PersonelBelge).where(
                    PersonelBelge.personel_id == int(personel_id),
                    PersonelBelge.tur_id == int(tur_id),
                )
            )
            if belge is None:
                belge = PersonelBelge(
                    personel_id=int(personel_id),
                    tur_id=int(tur_id),
                    durum=BELGE_DURUM_YUKLENDI,
                )
                session.add(belge)
                session.flush()

            # Hash mükerrer uyarısı
            from database.personel_arsiv import dosya_hash

            ham = kaynak.read_bytes()
            h = dosya_hash(ham)
            ayni = session.scalar(
                select(PersonelBelgeSurumu).where(
                    PersonelBelgeSurumu.dosya_hash == h,
                    PersonelBelgeSurumu.imha_edildi.is_(False),
                )
            )
            if ayni is not None and not hash_uyari_yoksay:
                raise ValueError(
                    f"Aynı dosya daha önce yüklendi (belge sürüm id={ayni.id}, hash={h[:12]}…). "
                    "Yine de yüklemek için onayı tekrarlayın."
                )

            surum_no = (max((s.surum_no for s in belge.surumler), default=0) + 1)
            sifreli = tur.gizlilik in HASSAS
            # Önce belge_id ile arşive yaz
            meta = dosyayi_arsive_kopyala(
                int(personel_id), int(belge.id), surum_no, kaynak, sifreli=sifreli
            )
            # Tarihi olmayan belgeye sahte geçerlilik verme
            gec = _tarih(gecerlilik_tarihi)
            yen = _tarih(yenileme_tarihi)
            surum = PersonelBelgeSurumu(
                belge_id=belge.id,
                surum_no=surum_no,
                belge_adi=(belge_adi or meta["dosya_adi"])[:200],
                duzenlenme_tarihi=_tarih(duzenlenme_tarihi),
                gecerlilik_tarihi=gec,
                yenileme_tarihi=yen,
                donem=donem,
                belge_no=belge_no,
                barkod=barkod,
                duzenleyen_kurum=duzenleyen_kurum,
                aciklama=aciklama,
                gizlilik=tur.gizlilik,
                yukleyen=_kullanici(),
                **meta,
            )
            session.add(surum)
            session.flush()
            belge.gecerli_surum_id = surum.id
            belge.uygulanmiyor = False
            belge.durum = PersonelBelgeService._durum_hesapla(gec, yen)
            _log(
                session,
                "YUKLE",
                belge_id=belge.id,
                surum_id=surum.id,
                personel_id=personel_id,
                ayrinti=f"tur={tur.kod}",
            )
            session.flush()
            return {
                "belge_id": belge.id,
                "surum_id": surum.id,
                "surum_no": surum_no,
                "durum": belge.durum,
                "hash": h,
                "mukerrer_hash": ayni is not None,
            }

    @staticmethod
    def _durum_hesapla(gecerlilik: date | None, yenileme: date | None) -> str:
        bugun = date.today()
        if gecerlilik and gecerlilik < bugun:
            return BELGE_DURUM_SURESI_DOLDU
        hedef = yenileme or gecerlilik
        if hedef and hedef <= bugun + timedelta(days=30):
            return BELGE_DURUM_YENILEME
        return BELGE_DURUM_YUKLENDI

    @staticmethod
    def incele(belge_id: int, sonuc: str) -> None:
        yazma_zorunlu("personel_duzenleme", "duzenleme")
        schema_hazirla()
        with get_session() as session:
            b = session.get(PersonelBelge, int(belge_id))
            if b is None:
                raise ValueError("Belge bulunamadı.")
            tur = session.get(PersonelBelgeTuru, b.tur_id)
            if tur:
                _hassas_okuma_zorunlu(tur.gizlilik)
            surum = next((s for s in b.surumler if s.id == b.gecerli_surum_id), None)
            if surum is None:
                raise ValueError("Geçerli sürüm yok.")
            surum.kontrol_eden = _kullanici()
            surum.kontrol_tarihi = datetime.now()
            surum.kontrol_sonucu = (sonuc or "")[:200]
            # Yükleme tek başına resmî onay değildir
            b.durum = BELGE_DURUM_INCELENDI
            _log(session, "INCELE", belge_id=b.id, surum_id=surum.id, personel_id=b.personel_id)

    @staticmethod
    def uygulanmiyor_isaretle(belge_id: int | None, personel_id: int, tur_id: int, gerekce: str) -> None:
        yazma_zorunlu("personel_duzenleme", "duzenleme")
        schema_hazirla()
        if not (gerekce or "").strip():
            raise ValueError("Uygulanmıyor gerekçesi zorunludur.")
        with get_session() as session:
            b = None
            if belge_id:
                b = session.get(PersonelBelge, int(belge_id))
            if b is None:
                b = PersonelBelge(
                    personel_id=int(personel_id),
                    tur_id=int(tur_id),
                    durum=BELGE_DURUM_UYGULANMIYOR,
                )
                session.add(b)
                session.flush()
            b.uygulanmiyor = True
            b.uygulanmiyor_gerekce = gerekce.strip()[:300]
            b.durum = BELGE_DURUM_UYGULANMIYOR

    @staticmethod
    def dosya_oku(surum_id: int) -> tuple[bytes, str, str]:
        """İçerik, dosya adı, mime — DOCX makrosu çalıştırılmaz."""
        schema_hazirla()
        with get_session() as session:
            s = session.get(PersonelBelgeSurumu, int(surum_id))
            if s is None or s.imha_edildi:
                raise ValueError("Belge sürümü bulunamadı.")
            _hassas_okuma_zorunlu(s.gizlilik)
            yetki_zorunlu("personel_goruntuleme", "personel_duzenleme", "goruntuleme")
            try:
                veri = arsivden_oku(s.dosya_yolu, sifreli=s.sifreli)
            except FileNotFoundError as e:
                raise ValueError(str(e)) from e
            _log(
                session,
                "GORUNTULE",
                belge_id=s.belge_id,
                surum_id=s.id,
                personel_id=s.belge.personel_id if s.belge else None,
            )
            session.flush()
            return veri, s.dosya_adi, s.mime_tur or "application/octet-stream"

    @staticmethod
    def imha(surum_id: int, *, gerekce: str) -> None:
        yazma_zorunlu("personel_belge_imha")
        schema_hazirla()
        if not (gerekce or "").strip():
            raise ValueError("İmha gerekçesi zorunludur.")
        with get_session() as session:
            s = session.get(PersonelBelgeSurumu, int(surum_id))
            if s is None:
                raise ValueError("Sürüm bulunamadı.")
            b = session.get(PersonelBelge, s.belge_id)
            if b and b.hukuki_saklama_engeli:
                raise ValueError("Hukuki saklama engeli var; otomatik/yetkisiz imha yapılamaz.")
            tur = session.get(PersonelBelgeTuru, b.tur_id) if b else None
            if tur and tur.gizlilik in HASSAS:
                yazma_zorunlu("personel_hassas_duzenleme", "personel_belge_imha")
            # Dosyayı sil, meta kalır
            yol = Path(s.dosya_yolu)
            if yol.is_file():
                yol.unlink()
            s.imha_edildi = True
            s.imha_tarihi = datetime.now()
            s.imha_eden = _kullanici()
            if b and b.gecerli_surum_id == s.id:
                diger = next(
                    (x for x in b.surumler if not x.imha_edildi and x.id != s.id),
                    None,
                )
                b.gecerli_surum_id = diger.id if diger else None
                if diger is None:
                    b.durum = BELGE_DURUM_EKSIK
            _log(
                session,
                "IMHA",
                belge_id=s.belge_id,
                surum_id=s.id,
                ayrinti=(gerekce or "")[:200],
            )
