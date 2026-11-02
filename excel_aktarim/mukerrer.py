"""Mükerrer kayıt yardımcıları — tip bazlı anahtar kontrolü."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from database.database import get_session
from excel_aktarim.normalize import temiz


def mukerrer_mi(tip_kod: str, anahtar: dict[str, Any]) -> tuple[bool, str | None]:
    """True, gerekçe — aynı anahtarla kayıt zaten varsa."""
    kod = (tip_kod or "").strip()
    with get_session() as session:
        if kod in ("stok_karti",):
            from database.models.stok import StokKarti

            sk = temiz(anahtar.get("stok_kodu"))
            if not sk:
                return False, None
            var = session.scalar(select(StokKarti.id).where(StokKarti.stok_kodu == sk))
            return (True, f"Stok kodu zaten var: {sk}") if var else (False, None)

        if kod in ("musteri_cari", "tedarikci_cari"):
            from database.models.cari import Cari

            ck = temiz(anahtar.get("cari_kodu"))
            if not ck:
                return False, None
            var = session.scalar(select(Cari.id).where(Cari.cari_kodu == ck))
            return (True, f"Cari kodu zaten var: {ck}") if var else (False, None)

        if kod == "personel_kart":
            from database.models.personel import Personel

            pk = temiz(anahtar.get("kod") or anahtar.get("personel_kodu"))
            if not pk:
                return False, None
            var = session.scalar(select(Personel.id).where(Personel.kod == pk.upper()))
            return (True, f"Personel kodu zaten var: {pk}") if var else (False, None)

        if kod in ("kasa_hesap", "pos_hesap"):
            from database.models.finans import FinansHesabi

            ad = temiz(anahtar.get("hesap_adi"))
            if not ad:
                return False, None
            var = session.scalar(select(FinansHesabi.id).where(FinansHesabi.hesap_adi == ad))
            etiket = "POS hesap" if kod == "pos_hesap" else "Hesap"
            return (True, f"{etiket} adı zaten var: {ad}") if var else (False, None)

        if kod == "banka_kart":
            from database.models.finans import BankaKarti

            ad = temiz(anahtar.get("banka_adi"))
            if not ad:
                return False, None
            var = session.scalar(select(BankaKarti.id).where(BankaKarti.banka_adi == ad))
            return (True, f"Banka kartı zaten var: {ad}") if var else (False, None)

        if kod in ("satis_fatura_excel", "alis_fatura_excel"):
            from database.models.alis_faturasi import AlisFaturasi
            from database.models.satis_faturasi import SatisFaturasi

            no = temiz(anahtar.get("belge_no") or anahtar.get("fatura_no"))
            if not no:
                return False, None
            Model = SatisFaturasi if "satis" in kod else AlisFaturasi
            var = session.scalar(select(Model.id).where(Model.fatura_no == no))
            return (True, f"Fatura no zaten var: {no}") if var else (False, None)

        if kod == "cek_senet":
            from database.models.cek_senet import CekSenetEvrak

            no = temiz(anahtar.get("evrak_no"))
            tur = (temiz(anahtar.get("evrak_turu")) or "").upper()
            if not no:
                return False, None
            q = select(CekSenetEvrak.id).where(CekSenetEvrak.evrak_no == no)
            # Excel'de CEK/SENET gelir; DB'de MUSTERI_CEKI / FIRMA_CEKI / … tutulur
            if tur in ("CEK", "ÇEK"):
                q = q.where(CekSenetEvrak.evrak_turu.like("%CEK%"))
            elif tur == "SENET":
                q = q.where(CekSenetEvrak.evrak_turu.like("%SENET%"))
            elif tur:
                q = q.where(CekSenetEvrak.evrak_turu == tur)
            var = session.scalars(q).first()
            return (True, f"Çek/senet evrak no zaten var: {no}") if var else (False, None)

        if kod == "gider_fisi":
            from database.models.finans import GiderFisi

            no = temiz(anahtar.get("belge_no"))
            if not no:
                return False, None
            var = session.scalar(select(GiderFisi.id).where(GiderFisi.belge_no == no))
            return (True, f"Gider fişi belge no zaten var: {no}") if var else (False, None)

        if kod == "depo_transfer":
            from database.models.stok import DepoTransferFisi

            no = temiz(anahtar.get("fis_no"))
            if not no:
                return False, None
            var = session.scalar(select(DepoTransferFisi.id).where(DepoTransferFisi.fis_no == no))
            return (True, f"Transfer fiş no zaten var: {no}") if var else (False, None)

    return False, None
