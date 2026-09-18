"""Tedarikçi teklif karşılaştırma + siparişe aktarım."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database.access import yazma_zorunlu
from database.alis_siparisi_service import AlisSiparisiService
from database.database import get_session
from database.models.tedarikci_teklif import TedarikciTeklif, TedarikciTeklifSatiri
from database.satis_siparisi_service import decimal
from database.satin_alma_hub_service import SatinAlmaHubService
from database.satin_alma_talep_service import SatinAlmaTalepService


class TedarikciTeklifService:
    @staticmethod
    def schema_hazirla() -> None:
        SatinAlmaHubService.schema_hazirla()

    @staticmethod
    def teklif_no() -> str:
        TedarikciTeklifService.schema_hazirla()
        onek = "TTK"
        with get_session() as session:
            son = session.scalar(
                select(TedarikciTeklif.teklif_no)
                .where(TedarikciTeklif.teklif_no.like(f"{onek}%"))
                .order_by(TedarikciTeklif.teklif_no.desc())
            )
        if not son:
            return f"{onek}000001"
        try:
            sira = int(str(son)[len(onek) :]) + 1
        except ValueError:
            sira = 1
        return f"{onek}{sira:06d}"

    @staticmethod
    def _edinme_maliyeti(satir: TedarikciTeklifSatiri) -> Decimal:
        brut = (satir.miktar or Decimal("0")) * (satir.birim_fiyat or Decimal("0"))
        isk = brut * ((satir.iskonto_orani or Decimal("0")) / Decimal("100"))
        net = brut - isk
        # Basit vade maliyeti: vade_gun * %0.03 / 30 (yıllık ~%10 varsayım)
        vade_maliyeti = net * (
            Decimal(satir.vade_gun or 0) * Decimal("0.0003")
        )
        return net + vade_maliyeti + (satir.nakliye_tutari or Decimal("0"))

    @staticmethod
    def listele() -> list[dict[str, Any]]:
        TedarikciTeklifService.schema_hazirla()
        with get_session() as session:
            kayitlar = list(
                session.scalars(
                    select(TedarikciTeklif)
                    .options(selectinload(TedarikciTeklif.satirlar))
                    .order_by(TedarikciTeklif.id.desc())
                ).all()
            )
            sonuc = []
            for t in kayitlar:
                sonuc.append(
                    {
                        "id": t.id,
                        "teklif_no": t.teklif_no,
                        "teklif_tarihi": t.teklif_tarihi,
                        "talep_id": t.talep_id,
                        "durum": t.durum,
                        "satir_adet": len(t.satirlar or []),
                        "aciklama": t.aciklama or "",
                    }
                )
            return sonuc

    @staticmethod
    def getir(teklif_id: int) -> TedarikciTeklif | None:
        TedarikciTeklifService.schema_hazirla()
        with get_session() as session:
            return session.scalar(
                select(TedarikciTeklif)
                .options(
                    selectinload(TedarikciTeklif.satirlar).selectinload(
                        TedarikciTeklifSatiri.cari
                    )
                )
                .where(TedarikciTeklif.id == int(teklif_id))
            )

    @staticmethod
    def karsilastirma(teklif_id: int) -> list[dict[str, Any]]:
        teklif = TedarikciTeklifService.getir(teklif_id)
        if teklif is None:
            raise ValueError("Teklif bulunamadı.")
        satirlar = []
        for s in teklif.satirlar or []:
            maliyet = TedarikciTeklifService._edinme_maliyeti(s)
            satirlar.append(
                {
                    "id": s.id,
                    "cari_id": s.cari_id,
                    "tedarikci": s.cari.unvan if s.cari else "",
                    "urun_kodu": s.urun_kodu,
                    "urun_adi": s.urun_adi,
                    "birim": s.birim,
                    "miktar": s.miktar,
                    "birim_fiyat": s.birim_fiyat,
                    "iskonto": s.iskonto_orani,
                    "vade_gun": s.vade_gun,
                    "termin_gun": s.termin_gun,
                    "nakliye": s.nakliye_tutari,
                    "edinme_maliyeti": maliyet,
                    "secildi": bool(s.secildi),
                    "para_birimi": s.para_birimi,
                }
            )
        satirlar.sort(key=lambda x: (x["urun_kodu"], x["edinme_maliyeti"]))
        return satirlar

    @staticmethod
    def kaydet(
        veriler: dict[str, Any],
        satir_verileri: list[dict[str, Any]],
        teklif_id: int | None = None,
    ) -> int:
        yazma_zorunlu("alis_teklif_duzenleme", "alis_duzenleme", "yeni_kayit")
        TedarikciTeklifService.schema_hazirla()
        if not satir_verileri:
            raise ValueError("En az bir teklif satırı girin.")
        with get_session() as session:
            if teklif_id:
                teklif = session.get(TedarikciTeklif, int(teklif_id))
                if teklif is None:
                    raise ValueError("Teklif bulunamadı.")
                teklif.satirlar.clear()
            else:
                teklif = TedarikciTeklif(
                    teklif_no=(veriler.get("teklif_no") or "").strip()
                    or TedarikciTeklifService.teklif_no(),
                    durum="TASLAK",
                )
                session.add(teklif)
            teklif.teklif_tarihi = veriler["teklif_tarihi"]
            teklif.talep_id = veriler.get("talep_id")
            teklif.aciklama = veriler.get("aciklama")
            teklif.durum = veriler.get("durum") or teklif.durum or "TASLAK"
            for veri in satir_verileri:
                teklif.satirlar.append(
                    TedarikciTeklifSatiri(
                        cari_id=int(veri["cari_id"]),
                        urun_kodu=veri["urun_kodu"],
                        urun_adi=veri["urun_adi"],
                        birim=veri.get("birim") or "Adet",
                        miktar=decimal(veri["miktar"], "Miktar", Decimal("0.0001")),
                        birim_fiyat=decimal(veri["birim_fiyat"], "Birim fiyat", Decimal("0")),
                        iskonto_orani=decimal(
                            veri.get("iskonto_orani", 0), "İskonto", Decimal("0")
                        ),
                        kdv_orani=decimal(veri.get("kdv_orani", 20), "KDV", Decimal("0")),
                        para_birimi=veri.get("para_birimi") or "TRY",
                        vade_gun=int(veri.get("vade_gun") or 0),
                        termin_gun=int(veri.get("termin_gun") or 0),
                        nakliye_tutari=decimal(
                            veri.get("nakliye_tutari", 0), "Nakliye", Decimal("0")
                        ),
                        odeme_sarti=veri.get("odeme_sarti"),
                        secildi=bool(veri.get("secildi")),
                    )
                )
            session.flush()
            return int(teklif.id)

    @staticmethod
    def satir_sec(teklif_id: int, satir_idler: list[int]) -> None:
        yazma_zorunlu("alis_teklif_duzenleme", "alis_duzenleme")
        idler = {int(x) for x in satir_idler}
        with get_session() as session:
            teklif = session.scalar(
                select(TedarikciTeklif)
                .options(selectinload(TedarikciTeklif.satirlar))
                .where(TedarikciTeklif.id == int(teklif_id))
            )
            if teklif is None:
                raise ValueError("Teklif bulunamadı.")
            for s in teklif.satirlar:
                s.secildi = s.id in idler

    @staticmethod
    def secilenleri_siparise_aktar(teklif_id: int) -> list[int]:
        """Seçilen satırları tedarikçi bazında bir veya birden fazla siparişe çevirir."""
        yazma_zorunlu("alis_teklif_duzenleme", "alis_duzenleme", "yeni_kayit")
        teklif = TedarikciTeklifService.getir(teklif_id)
        if teklif is None:
            raise ValueError("Teklif bulunamadı.")
        secilen = [s for s in (teklif.satirlar or []) if s.secildi]
        if not secilen:
            raise ValueError("Siparişe aktarılacak seçili satır yok.")

        # Tedarikçiye göre grupla
        gruplar: dict[int, list] = {}
        for s in secilen:
            gruplar.setdefault(int(s.cari_id), []).append(s)

        olusan_idler: list[int] = []
        bugun = date.today()
        for cari_id, satirlar in gruplar.items():
            max_termin = max((s.termin_gun or 0) for s in satirlar)
            veriler = {
                "siparis_tarihi": bugun,
                "termin_tarihi": bugun + timedelta(days=max_termin or 7),
                "cari_id": cari_id,
                "aciklama": f"Teklif {teklif.teklif_no} aktarımı",
            }
            satir_verileri = [
                {
                    "urun_kodu": s.urun_kodu,
                    "urun_adi": s.urun_adi,
                    "miktar": s.miktar,
                    "birim": s.birim,
                    "birim_alis_fiyati": s.birim_fiyat,
                    "iskonto_orani": s.iskonto_orani,
                    "kdv_orani": s.kdv_orani,
                }
                for s in satirlar
            ]
            siparis = AlisSiparisiService.kaydet(veriler, satir_verileri, [])
            olusan_idler.append(int(siparis.id))

        with get_session() as session:
            kayit = session.get(TedarikciTeklif, int(teklif_id))
            if kayit:
                kayit.durum = "SİPARİŞE AKTARILDI"
            if teklif.talep_id:
                try:
                    SatinAlmaTalepService.durum_degistir(
                        int(teklif.talep_id), "SİPARİŞE AKTARILDI"
                    )
                except Exception:
                    pass
        return olusan_idler

    @staticmethod
    def talepden_olustur(talep_id: int, cari_idler: list[int]) -> int:
        """Talep satırlarını seçilen tedarikçilere boş fiyatlı teklif satırlarına çoğaltır."""
        yazma_zorunlu("alis_teklif_duzenleme", "alis_duzenleme", "yeni_kayit")
        talep = SatinAlmaTalepService.getir(talep_id)
        if talep is None:
            raise ValueError("Talep bulunamadı.")
        if not cari_idler:
            raise ValueError("En az bir tedarikçi seçin.")
        satirlar = []
        for cari_id in cari_idler:
            for s in talep.satirlar or []:
                satirlar.append(
                    {
                        "cari_id": int(cari_id),
                        "urun_kodu": s.urun_kodu,
                        "urun_adi": s.urun_adi,
                        "birim": s.birim,
                        "miktar": s.miktar,
                        "birim_fiyat": 0,
                        "iskonto_orani": 0,
                        "kdv_orani": 20,
                    }
                )
        return TedarikciTeklifService.kaydet(
            {
                "teklif_tarihi": date.today(),
                "talep_id": int(talep_id),
                "aciklama": f"Talep {talep.talep_no}",
                "durum": "TASLAK",
            },
            satirlar,
        )
