"""Hizmet alış (gider) / satış (gelir) fatura servisi — sade standart fatura."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from database.database import get_session
from database.finans_service import FinansService
from database.models.cari import Cari, SatisHareketi
from database.models.hizmet import HizmetHareketi, HizmetKarti
from database.models.hizmet_faturasi import HizmetFaturasi, HizmetFaturasiSatiri
from database.satis_siparisi_service import decimal

FATURA_DURUMLARI = ("AÇIK", "KAPALI", "İPTAL")
ODEME_SEKILLERI = ("KASA ÖDEME", "GÖNDERİLEN HAVALE", "KREDİ KARTIYLA ÖDEME")
TAHSILAT_SEKILLERI = ("KASA TAHSİLAT", "ALINAN HAVALE", "KREDİ KARTIYLA TAHSİLAT")

HAREKET_GIDER = "HİZMET ALIŞ (GİDER)"
HAREKET_GELIR = "HİZMET SATIŞ (GELİR)"


class HizmetFaturasiService:
    @staticmethod
    def aktif_cariler(fatura_turu: str):
        """Gider: hizmet veren (tedarikçi/banka/personel). Gelir: hizmet alan (+ müşteri)."""
        tur = (fatura_turu or "GIDER").upper()
        kosullar = [
            Cari.cari_turu == "Tedarikçi",
            Cari.cari_turu.ilike("tedarik%"),
            Cari.cari_turu == "Banka",
            Cari.cari_turu.ilike("banka%"),
            Cari.cari_turu == "Personel",
            Cari.cari_turu.ilike("personel%"),
        ]
        if tur == "GELIR":
            kosullar.extend(
                [
                    Cari.cari_turu == "Müşteri",
                    Cari.cari_turu == "Musteri",
                    Cari.cari_turu.ilike("müster%"),
                    Cari.cari_turu.ilike("muster%"),
                ]
            )
        with get_session() as session:
            return list(
                session.scalars(
                    select(Cari)
                    .where(Cari.aktif.is_(True), or_(*kosullar))
                    .order_by(Cari.cari_kodu)
                ).all()
            )

    @staticmethod
    def fatura_no(fatura_turu: str) -> str:
        onek = "HSG" if (fatura_turu or "").upper() == "GELIR" else "HAG"
        with get_session() as session:
            numaralar = session.scalars(
                select(HizmetFaturasi.fatura_no).where(
                    HizmetFaturasi.fatura_no.like(f"{onek}%")
                )
            ).all()
            max_sira = 0
            for no in numaralar:
                kuyruk = str(no)[len(onek) :]
                if kuyruk.isdigit():
                    max_sira = max(max_sira, int(kuyruk))
            return f"{onek}{max_sira + 1:06d}"

    @staticmethod
    def toplam(satirlar) -> dict[str, Decimal]:
        ara = iskonto = kdv = Decimal("0")
        for satir in satirlar:
            get = satir.get if isinstance(satir, dict) else lambda a, d=0: getattr(satir, a, d)
            miktar = decimal(get("miktar"), "Miktar")
            fiyat = decimal(get("birim_fiyat"), "Birim fiyat")
            indirim = miktar * fiyat * decimal(get("iskonto_orani", 0), "İskonto") / Decimal("100")
            net = miktar * fiyat - indirim
            ara += miktar * fiyat
            iskonto += indirim
            kdv += net * decimal(get("kdv_orani", 0), "KDV") / Decimal("100")
        return {
            "ara_toplam": ara,
            "iskonto": iskonto,
            "kdv": kdv,
            "genel_toplam": ara - iskonto + kdv,
        }

    @staticmethod
    def listele(fatura_turu=None) -> list[dict[str, Any]]:
        with get_session() as session:
            q = (
                select(HizmetFaturasi)
                .options(
                    selectinload(HizmetFaturasi.cari),
                    selectinload(HizmetFaturasi.satirlar),
                )
                .order_by(HizmetFaturasi.id.desc())
            )
            if fatura_turu:
                q = q.where(HizmetFaturasi.fatura_turu == str(fatura_turu).upper())
            faturalar = list(session.scalars(q).all())
            return [
                {"fatura": f, **HizmetFaturasiService.toplam(f.satirlar)}
                for f in faturalar
            ]

    @staticmethod
    def getir(fatura_id) -> HizmetFaturasi | None:
        with get_session() as session:
            return session.scalar(
                select(HizmetFaturasi)
                .options(
                    selectinload(HizmetFaturasi.cari),
                    selectinload(HizmetFaturasi.satirlar),
                )
                .where(HizmetFaturasi.id == int(fatura_id))
            )

    @staticmethod
    def _hareketleri_sil(session, fatura_no: str):
        session.execute(
            delete(HizmetHareketi).where(HizmetHareketi.belge_no == fatura_no)
        )

    @staticmethod
    def _finans_geri_al(session, fatura: HizmetFaturasi):
        if fatura.fatura_turu == "GELIR":
            FinansService.fatura_tahsilatini_geri_al(session, fatura.fatura_no)
        else:
            FinansService.fatura_odemesini_geri_al(session, fatura.fatura_no)

    @staticmethod
    def _finans_yaz(session, fatura: HizmetFaturasi):
        if fatura.fatura_turu == "GELIR":
            FinansService.fatura_tahsilati(
                session,
                fatura.fatura_no,
                fatura.fatura_tarihi,
                fatura.odeme_tutari,
                fatura.odeme_sekli,
                fatura.odeme_hesabi,
            )
        else:
            FinansService.fatura_odemesi(
                session,
                fatura.fatura_no,
                fatura.fatura_tarihi,
                fatura.odeme_tutari,
                fatura.odeme_sekli,
                fatura.odeme_hesabi,
            )

    @staticmethod
    def kaydet(veriler: dict, satir_verileri: list[dict], fatura_id=None) -> HizmetFaturasi:
        tarih = veriler["fatura_tarihi"]
        vade = veriler["vade_tarihi"]
        tur = (veriler.get("fatura_turu") or "GIDER").strip().upper()
        if tur not in ("GIDER", "GELIR"):
            raise ValueError("Fatura türü GIDER veya GELIR olmalıdır.")
        if tarih > date.today():
            raise ValueError("Fatura tarihi gelecek bir tarih olamaz.")
        if vade < tarih:
            raise ValueError("Vade tarihi fatura tarihinden önce olamaz.")
        if not satir_verileri:
            raise ValueError("En az bir fatura satırı ekleyin.")

        with get_session() as session:
            if fatura_id:
                fatura = session.scalar(
                    select(HizmetFaturasi)
                    .options(selectinload(HizmetFaturasi.satirlar))
                    .where(HizmetFaturasi.id == int(fatura_id))
                )
                if not fatura:
                    raise ValueError("Fatura bulunamadı.")
                if fatura.durum == "İPTAL":
                    raise ValueError("İptal edilmiş fatura düzenlenemez.")
                HizmetFaturasiService._finans_geri_al(session, fatura)
                HizmetFaturasiService._hareketleri_sil(session, fatura.fatura_no)
                session.execute(
                    delete(SatisHareketi).where(SatisHareketi.belge_no == fatura.fatura_no)
                )
                fatura.satirlar.clear()
            else:
                fatura = HizmetFaturasi(
                    fatura_no=(veriler.get("fatura_no") or "").strip()
                    or HizmetFaturasiService.fatura_no(tur),
                    fatura_turu=tur,
                )
                session.add(fatura)

            fatura.fatura_turu = tur
            fatura.fatura_tarihi = tarih
            fatura.vade_tarihi = vade
            fatura.vade_gunu = (vade - tarih).days
            fatura.islem_saati = (
                (veriler.get("islem_saati") or "").strip()
                or datetime.now().strftime("%H:%M")
            )
            fatura.cari_id = int(veriler["cari_id"])
            fatura.odeme_tutari = decimal(veriler.get("odeme_tutari", 0), "Ödeme", Decimal("0"))
            fatura.odeme_sekli = veriler.get("odeme_sekli") or None
            fatura.odeme_hesabi = veriler.get("odeme_hesabi") or None
            fatura.aciklama = (veriler.get("aciklama") or "").strip() or None
            fatura.dokuman_yolu = (veriler.get("dokuman_yolu") or "").strip() or None

            hareket_turu = HAREKET_GELIR if tur == "GELIR" else HAREKET_GIDER
            isaret = 1 if tur == "GELIR" else -1

            for veri in satir_verileri:
                kod = (veri.get("hizmet_kodu") or "").strip().upper()
                if not kod:
                    raise ValueError("Hizmet kodu zorunludur.")
                hizmet = session.scalar(
                    select(HizmetKarti).where(HizmetKarti.hizmet_kodu == kod)
                )
                if not hizmet:
                    raise ValueError(f"{kod} kodlu hizmet kartı bulunamadı.")
                if (hizmet.hizmet_turu or "").upper() != tur:
                    raise ValueError(
                        f"{kod} bu fatura türü için uygun değil "
                        f"({hizmet.hizmet_turu})."
                    )
                miktar = decimal(veri["miktar"], "Miktar", Decimal("0.0001"))
                birim_fiyat = decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0"))
                iskonto_orani = decimal(veri.get("iskonto_orani", 0), "İskonto", Decimal("0"))
                kdv_orani = decimal(veri.get("kdv_orani", 20), "KDV", Decimal("0"))
                net = miktar * birim_fiyat - (
                    miktar * birim_fiyat * iskonto_orani / Decimal("100")
                )

                fatura.satirlar.append(
                    HizmetFaturasiSatiri(
                        hizmet_id=hizmet.id,
                        hizmet_kodu=hizmet.hizmet_kodu,
                        hizmet_adi=(veri.get("hizmet_adi") or hizmet.hizmet_adi or "").strip(),
                        aciklama=(veri.get("aciklama") or "").strip() or None,
                        miktar=miktar,
                        birim=(veri.get("birim") or hizmet.birim or "Adet").strip() or "Adet",
                        birim_fiyat=birim_fiyat,
                        iskonto_orani=iskonto_orani,
                        kdv_orani=kdv_orani,
                    )
                )
                session.add(
                    HizmetHareketi(
                        hizmet_id=hizmet.id,
                        tarih=tarih,
                        hareket_turu=hareket_turu,
                        belge_no=fatura.fatura_no,
                        miktar=miktar,
                        birim_fiyat=birim_fiyat,
                        kdv_orani=kdv_orani,
                        tutar=net.quantize(Decimal("0.01")),
                        isaret=isaret,
                        cari_id=fatura.cari_id,
                        aciklama=(veri.get("aciklama") or "").strip() or None,
                    )
                )
                if tur == "GIDER":
                    hizmet.alis_fiyati = birim_fiyat
                else:
                    hizmet.satis_fiyati = birim_fiyat

            toplam = HizmetFaturasiService.toplam(fatura.satirlar)["genel_toplam"]
            if fatura.odeme_tutari > toplam:
                etiket = "Tahsilat" if tur == "GELIR" else "Ödeme"
                raise ValueError(f"{etiket} tutarı fatura toplamından büyük olamaz.")
            fatura.durum = "KAPALI" if fatura.odeme_tutari >= toplam else "AÇIK"
            session.flush()

            hareket = session.scalar(
                select(SatisHareketi).where(SatisHareketi.belge_no == fatura.fatura_no)
            )
            if not hareket:
                hareket = SatisHareketi(cari_id=fatura.cari_id, belge_no=fatura.fatura_no)
                session.add(hareket)
            hareket.cari_id = fatura.cari_id
            hareket.satis_tarihi = tarih
            hareket.satis_tutari = toplam
            hareket.kalan_acik_tutar = toplam - fatura.odeme_tutari

            HizmetFaturasiService._finans_yaz(session, fatura)
            try:
                session.flush()
            except IntegrityError as hata:
                raise ValueError("Fatura kaydedilemedi.") from hata
            fid = fatura.id

        return HizmetFaturasiService.getir(fid)

    @staticmethod
    def iptal_et(fatura_id):
        with get_session() as session:
            fatura = session.scalar(
                select(HizmetFaturasi)
                .options(selectinload(HizmetFaturasi.satirlar))
                .where(HizmetFaturasi.id == int(fatura_id))
            )
            if not fatura:
                raise ValueError("Fatura bulunamadı.")
            if fatura.durum == "İPTAL":
                return
            HizmetFaturasiService._finans_geri_al(session, fatura)
            HizmetFaturasiService._hareketleri_sil(session, fatura.fatura_no)
            session.execute(
                delete(SatisHareketi).where(SatisHareketi.belge_no == fatura.fatura_no)
            )
            fatura.durum = "İPTAL"
