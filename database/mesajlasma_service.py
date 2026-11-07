"""Firma içi kullanıcı mesajlaşması — system DB (ortak; ana makine + terminaller).

Kimlik bilgisayar adına değil oturum açmış kullanıcıya bağlıdır.
Firma (company_id) ve ortam (DENEME/GERÇEK) ayrımı korunur.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import selectinload

from database.database import get_system_session
from database.session_manager import oturum
from database.system.models import Mesaj, MesajKonusma, MesajKonusmaUye, User, UserCompany


class MesajlasmaError(ValueError):
    pass


def _aktif_ortam() -> str:
    try:
        from database.baglanti_modu import ayari_yukle

        ortam = (ayari_yukle().postgres.ortam or "DENEME").strip().upper()
        return ortam or "DENEME"
    except Exception:
        return "DENEME"


def _oturum_zorunlu() -> tuple[int, int]:
    uid = oturum.user_id
    cid = oturum.company_id
    if not uid or not cid:
        raise MesajlasmaError("Mesajlaşma için oturum ve firma seçimi gerekli.")
    return int(uid), int(cid)


def _uye_mi(session, konusma_id: int, user_id: int) -> MesajKonusmaUye | None:
    return session.scalar(
        select(MesajKonusmaUye).where(
            MesajKonusmaUye.konusma_id == int(konusma_id),
            MesajKonusmaUye.user_id == int(user_id),
        )
    )


def _kullanici_ozet(u: User) -> dict[str, Any]:
    return {
        "id": int(u.id),
        "kullanici_adi": u.kullanici_adi,
        "ad_soyad": u.ad_soyad,
        "gorunen": f"{u.ad_soyad} ({u.kullanici_adi})",
    }


class MesajlasmaService:
    @staticmethod
    def firma_kullanicilari(arama: str = "") -> list[dict[str, Any]]:
        """Aynı firmaya erişimi olan aktif kullanıcılar (kendisi hariç)."""
        uid, cid = _oturum_zorunlu()
        arama = (arama or "").strip().casefold()
        with get_system_session() as session:
            q = (
                select(User)
                .join(UserCompany, UserCompany.user_id == User.id)
                .where(
                    UserCompany.company_id == cid,
                    User.aktif.is_(True),
                    User.id != uid,
                )
                .order_by(User.ad_soyad, User.kullanici_adi)
            )
            sonuc = []
            for u in session.scalars(q).unique().all():
                ozet = _kullanici_ozet(u)
                if arama:
                    haystack = f"{u.ad_soyad} {u.kullanici_adi} {u.kullanici_kodu}".casefold()
                    if arama not in haystack:
                        continue
                sonuc.append(ozet)
            return sonuc

    @staticmethod
    def konusmalari_listele() -> list[dict[str, Any]]:
        uid, cid = _oturum_zorunlu()
        ortam = _aktif_ortam()
        with get_system_session() as session:
            uyeler = list(
                session.scalars(
                    select(MesajKonusmaUye)
                    .options(selectinload(MesajKonusmaUye.konusma).selectinload(MesajKonusma.uyeler))
                    .join(MesajKonusma, MesajKonusma.id == MesajKonusmaUye.konusma_id)
                    .where(
                        MesajKonusmaUye.user_id == uid,
                        MesajKonusma.company_id == cid,
                        MesajKonusma.ortam == ortam,
                    )
                ).all()
            )
            # Diğer üyelerin adları
            user_ids = {
                u.user_id
                for uy in uyeler
                for u in (uy.konusma.uyeler if uy.konusma else [])
            }
            users = {
                u.id: u
                for u in session.scalars(select(User).where(User.id.in_(user_ids or [-1]))).all()
            }
            liste = []
            for uy in uyeler:
                k = uy.konusma
                if k is None:
                    continue
                digerler = [
                    _kullanici_ozet(users[o.user_id])
                    for o in k.uyeler
                    if o.user_id != uid and o.user_id in users
                ]
                baslik = ", ".join(d["gorunen"] for d in digerler) or "Konuşma"
                okunmamis = MesajlasmaService._okunmamis_konusma(session, k.id, uid, uy.son_okunan_mesaj_id)
                liste.append(
                    {
                        "id": int(k.id),
                        "baslik": baslik,
                        "uyeler": digerler,
                        "son_mesaj_tarihi": k.son_mesaj_tarihi,
                        "son_mesaj_ozet": k.son_mesaj_ozet or "",
                        "okunmamis": okunmamis,
                    }
                )
            liste.sort(
                key=lambda x: x["son_mesaj_tarihi"] or datetime.min,
                reverse=True,
            )
            return liste

    @staticmethod
    def _okunmamis_konusma(session, konusma_id: int, user_id: int, son_okunan: int | None) -> int:
        q = select(func.count()).select_from(Mesaj).where(
            Mesaj.konusma_id == int(konusma_id),
            Mesaj.gonderen_user_id != int(user_id),
        )
        if son_okunan:
            q = q.where(Mesaj.id > int(son_okunan))
        return int(session.scalar(q) or 0)

    @staticmethod
    def okunmamis_toplam() -> int:
        try:
            uid, cid = _oturum_zorunlu()
        except MesajlasmaError:
            return 0
        ortam = _aktif_ortam()
        with get_system_session() as session:
            uyeler = list(
                session.scalars(
                    select(MesajKonusmaUye)
                    .join(MesajKonusma, MesajKonusma.id == MesajKonusmaUye.konusma_id)
                    .where(
                        MesajKonusmaUye.user_id == uid,
                        MesajKonusma.company_id == cid,
                        MesajKonusma.ortam == ortam,
                    )
                ).all()
            )
            toplam = 0
            for uy in uyeler:
                toplam += MesajlasmaService._okunmamis_konusma(
                    session, uy.konusma_id, uid, uy.son_okunan_mesaj_id
                )
            return toplam

    @staticmethod
    def dm_ac_veya_bul(karsi_user_id: int) -> dict[str, Any]:
        """İki kullanıcı arasında 1:1 konuşma bul veya oluştur."""
        uid, cid = _oturum_zorunlu()
        karsi = int(karsi_user_id)
        if karsi == uid:
            raise MesajlasmaError("Kendinize mesaj gönderemezsiniz.")
        ortam = _aktif_ortam()
        with get_system_session() as session:
            # Karşı kullanıcının bu firmaya erişimi var mı?
            erisim = session.scalar(
                select(UserCompany).where(
                    UserCompany.user_id == karsi,
                    UserCompany.company_id == cid,
                )
            )
            karsi_u = session.get(User, karsi)
            if erisim is None or karsi_u is None or not karsi_u.aktif:
                raise MesajlasmaError("Alıcı bu firmaya erişemez veya aktif değil.")

            # Ortak 1:1 konuşma ara
            alt = (
                select(MesajKonusmaUye.konusma_id)
                .join(MesajKonusma, MesajKonusma.id == MesajKonusmaUye.konusma_id)
                .where(
                    MesajKonusma.company_id == cid,
                    MesajKonusma.ortam == ortam,
                    MesajKonusmaUye.user_id.in_((uid, karsi)),
                )
                .group_by(MesajKonusmaUye.konusma_id)
                .having(func.count(MesajKonusmaUye.user_id) == 2)
            )
            aday_idler = list(session.scalars(alt).all())
            for kid in aday_idler:
                uye_sayisi = session.scalar(
                    select(func.count())
                    .select_from(MesajKonusmaUye)
                    .where(MesajKonusmaUye.konusma_id == kid)
                )
                if int(uye_sayisi or 0) == 2:
                    return {"id": int(kid), "yeni": False}

            k = MesajKonusma(company_id=cid, ortam=ortam, olusturma_tarihi=datetime.now())
            session.add(k)
            session.flush()
            session.add(MesajKonusmaUye(konusma_id=k.id, user_id=uid))
            session.add(MesajKonusmaUye(konusma_id=k.id, user_id=karsi))
            session.flush()
            return {"id": int(k.id), "yeni": True}

    @staticmethod
    def mesaj_gonder(
        konusma_id: int,
        icerik: str,
        *,
        client_msg_id: str | None = None,
    ) -> dict[str, Any]:
        uid, _cid = _oturum_zorunlu()
        metin = (icerik or "").strip()
        if not metin:
            raise MesajlasmaError("Boş mesaj gönderilemez.")
        if len(metin) > 8000:
            raise MesajlasmaError("Mesaj çok uzun (en fazla 8000 karakter).")
        cid_msg = (client_msg_id or "").strip() or str(uuid.uuid4())
        with get_system_session() as session:
            uye = _uye_mi(session, konusma_id, uid)
            if uye is None:
                raise MesajlasmaError("Bu konuşmaya erişiminiz yok.")
            # Mükerrer client_msg_id → mevcut kaydı döndür
            mevcut = session.scalar(
                select(Mesaj).where(
                    Mesaj.konusma_id == int(konusma_id),
                    Mesaj.client_msg_id == cid_msg,
                )
            )
            if mevcut is not None:
                return MesajlasmaService._mesaj_dict(session, mevcut, uid)

            k = session.get(MesajKonusma, int(konusma_id))
            if k is None:
                raise MesajlasmaError("Konuşma bulunamadı.")
            now = datetime.now()
            m = Mesaj(
                konusma_id=int(konusma_id),
                gonderen_user_id=uid,
                icerik=metin,
                client_msg_id=cid_msg,
                olusturma_tarihi=now,
            )
            session.add(m)
            k.son_mesaj_tarihi = now
            k.son_mesaj_ozet = metin[:180]
            # Gönderen kendi mesajını okumuş sayılır
            session.flush()
            uye.son_okunan_mesaj_id = int(m.id)
            session.flush()
            return MesajlasmaService._mesaj_dict(session, m, uid)

    @staticmethod
    def _mesaj_dict(session, m: Mesaj, okuyan_user_id: int) -> dict[str, Any]:
        gonderen = session.get(User, m.gonderen_user_id)
        # Alıcılar için okundu: tüm diğer üyelerin son_okunan_mesaj_id >= m.id
        uyeler = list(
            session.scalars(
                select(MesajKonusmaUye).where(MesajKonusmaUye.konusma_id == m.konusma_id)
            ).all()
        )
        alicilar = [u for u in uyeler if u.user_id != m.gonderen_user_id]
        okundu = bool(alicilar) and all(
            (u.son_okunan_mesaj_id or 0) >= int(m.id) for u in alicilar
        )
        return {
            "id": int(m.id),
            "konusma_id": int(m.konusma_id),
            "gonderen_user_id": int(m.gonderen_user_id),
            "gonderen_adi": (gonderen.ad_soyad if gonderen else "") or "",
            "gonderen_kullanici": (gonderen.kullanici_adi if gonderen else "") or "",
            "icerik": m.icerik,
            "client_msg_id": m.client_msg_id,
            "tarih": m.olusturma_tarihi,
            "benim": int(m.gonderen_user_id) == int(okuyan_user_id),
            "durum": "okundu" if okundu else "gonderildi",
        }

    @staticmethod
    def mesajlari_listele(
        konusma_id: int,
        *,
        before_id: int | None = None,
        after_id: int | None = None,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        uid, _cid = _oturum_zorunlu()
        limit = max(1, min(int(limit or 40), 100))
        with get_system_session() as session:
            if _uye_mi(session, konusma_id, uid) is None:
                raise MesajlasmaError("Bu konuşmaya erişiminiz yok.")
            q = select(Mesaj).where(Mesaj.konusma_id == int(konusma_id))
            if before_id:
                q = q.where(Mesaj.id < int(before_id)).order_by(Mesaj.id.desc())
            elif after_id:
                q = q.where(Mesaj.id > int(after_id)).order_by(Mesaj.id.asc())
            else:
                q = q.order_by(Mesaj.id.desc())
            q = q.limit(limit)
            satirlar = list(session.scalars(q).all())
            if not after_id:
                satirlar.reverse()  # eskiden yeniye
            return [MesajlasmaService._mesaj_dict(session, m, uid) for m in satirlar]

    @staticmethod
    def konusmayi_okundu_isaretle(konusma_id: int, son_mesaj_id: int | None = None) -> int:
        """Yalnız konuşma açıkken çağrılır. Programın açık olması yeterli değildir."""
        uid, _cid = _oturum_zorunlu()
        with get_system_session() as session:
            uye = _uye_mi(session, konusma_id, uid)
            if uye is None:
                raise MesajlasmaError("Bu konuşmaya erişiminiz yok.")
            if son_mesaj_id is None:
                son_mesaj_id = session.scalar(
                    select(func.max(Mesaj.id)).where(Mesaj.konusma_id == int(konusma_id))
                )
            if son_mesaj_id is None:
                return 0
            mevcut = int(uye.son_okunan_mesaj_id or 0)
            if int(son_mesaj_id) > mevcut:
                uye.son_okunan_mesaj_id = int(son_mesaj_id)
            return int(uye.son_okunan_mesaj_id or 0)

    @staticmethod
    def poll(son_gorulen_mesaj_id: int = 0) -> dict[str, Any]:
        """Rozet + isteğe bağlı yeni mesaj özeti (UI dondurmadan çağrılır)."""
        try:
            uid, cid = _oturum_zorunlu()
        except MesajlasmaError:
            return {"okunmamis": 0, "yeni": [], "max_mesaj_id": 0}
        ortam = _aktif_ortam()
        with get_system_session() as session:
            uyeler = list(
                session.scalars(
                    select(MesajKonusmaUye)
                    .join(MesajKonusma, MesajKonusma.id == MesajKonusmaUye.konusma_id)
                    .where(
                        MesajKonusmaUye.user_id == uid,
                        MesajKonusma.company_id == cid,
                        MesajKonusma.ortam == ortam,
                    )
                ).all()
            )
            okunmamis = 0
            for uy in uyeler:
                okunmamis += MesajlasmaService._okunmamis_konusma(
                    session, uy.konusma_id, uid, uy.son_okunan_mesaj_id
                )
            yeni = []
            if son_gorulen_mesaj_id:
                q = (
                    select(Mesaj)
                    .join(MesajKonusma, MesajKonusma.id == Mesaj.konusma_id)
                    .join(
                        MesajKonusmaUye,
                        and_(
                            MesajKonusmaUye.konusma_id == Mesaj.konusma_id,
                            MesajKonusmaUye.user_id == uid,
                        ),
                    )
                    .where(
                        MesajKonusma.company_id == cid,
                        MesajKonusma.ortam == ortam,
                        Mesaj.id > int(son_gorulen_mesaj_id),
                        Mesaj.gonderen_user_id != uid,
                    )
                    .order_by(Mesaj.id.asc())
                    .limit(20)
                )
                for m in session.scalars(q).all():
                    yeni.append(MesajlasmaService._mesaj_dict(session, m, uid))
            max_id = session.scalar(select(func.max(Mesaj.id))) or 0
            return {
                "okunmamis": okunmamis,
                "yeni": yeni,
                "max_mesaj_id": int(max_id),
            }
