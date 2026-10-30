"""Sorulan Ürünler servisi — aday birleştirme + talep (stok hareketi yok)."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from database.access import yazma_zorunlu
from database.database import Base, engine, get_session
from database.models.sorulan_urun import (
    ARAMA_SONUCLARI,
    NIYETLER,
    TALEP_NEDENLERI,
    SorulanUrunAday,
    SorulanUrunTalep,
)
from database.session_manager import oturum


def _normalize_ad(ad: str) -> str:
    s = unicodedata.normalize("NFKC", (ad or "").strip())
    s = re.sub(r"\s+", " ", s)
    return s.casefold()


class SorulanUrunService:
    _schema_hazir = False

    @classmethod
    def ensure_schema(cls, eng=None) -> None:
        bag = eng if eng is not None else engine
        if bag is None:
            return
        import database.models.sorulan_urun  # noqa: F401

        Base.metadata.create_all(
            bind=bag,
            tables=[SorulanUrunAday.__table__, SorulanUrunTalep.__table__],
        )
        cls._schema_hazir = True

    @staticmethod
    def _firma_id() -> int:
        fid = getattr(oturum, "company_id", None)
        if not fid:
            raise RuntimeError("Aktif firma yok.")
        return int(fid)

    @staticmethod
    def hizli_kaydet(veriler: dict[str, Any]) -> dict[str, Any]:
        """Ürün adı + talep nedeni ile kayıt; stok/cari zorunlu değil."""
        yazma_zorunlu()
        SorulanUrunService.ensure_schema()
        ad = " ".join(str(veriler.get("urun_adi") or "").split())
        if not ad:
            raise ValueError("Ürün adı zorunlu.")
        neden = (veriler.get("talep_nedeni") or "CESITTE_YOK").strip().upper()
        if neden not in TALEP_NEDENLERI:
            neden = "CESITTE_YOK"
        niyet = (veriler.get("niyet") or "SADECE_SORDU").strip().upper()
        if niyet not in NIYETLER:
            niyet = "SADECE_SORDU"
        norm = _normalize_ad(ad)
        firma = SorulanUrunService._firma_id()
        miktar = veriler.get("miktar")
        miktar_d = None
        if miktar is not None and str(miktar).strip() != "":
            miktar_d = Decimal(str(miktar))
            if miktar_d <= 0:
                raise ValueError("Miktar pozitif olmalı veya boş bırakılmalı.")

        with get_session() as session:
            aday = session.scalar(
                select(SorulanUrunAday).where(
                    SorulanUrunAday.firma_id == firma,
                    SorulanUrunAday.normalize_ad == norm,
                    SorulanUrunAday.arsiv.is_(False),
                )
            )
            if aday is None:
                aday = SorulanUrunAday(
                    firma_id=firma,
                    urun_adi=ad,
                    normalize_ad=norm,
                    ozellik=(veriler.get("ozellik") or None),
                    birim=(veriler.get("birim") or None),
                    stok_id=int(veriler["stok_id"]) if veriler.get("stok_id") else None,
                    talep_nedeni_ozet=neden,
                    olusturan=getattr(oturum, "kullanici_adi", None),
                )
                session.add(aday)
                session.flush()
            else:
                aday.guncelleme_tarihi = datetime.utcnow()
                if veriler.get("stok_id") and not aday.stok_id:
                    aday.stok_id = int(veriler["stok_id"])

            cari_id = veriler.get("cari_id")
            musteri = (veriler.get("musteri_adi") or "").strip() or None
            telefon = (veriler.get("telefon") or "").strip() or None
            anonim = not cari_id and not musteri and not telefon
            talep = SorulanUrunTalep(
                firma_id=firma,
                aday_id=int(aday.id),
                talep_tarihi=veriler.get("talep_tarihi") or date.today(),
                cari_id=int(cari_id) if cari_id else None,
                musteri_adi=musteri,
                telefon=telefon,
                anonim=anonim,
                miktar=miktar_d,
                birim=(veriler.get("birim") or aday.birim),
                niyet=niyet,
                talep_nedeni=neden,
                kaynak=(veriler.get("kaynak") or "HIZLI"),
                notlar=(veriler.get("notlar") or None),
                olusturan=getattr(oturum, "kullanici_adi", None),
            )
            session.add(talep)
            session.flush()
            return {
                "aday_id": int(aday.id),
                "talep_id": int(talep.id),
                "urun_adi": aday.urun_adi,
            }

    @staticmethod
    def urun_ozet_listesi(*, arama: str | None = None, arsiv: bool = False) -> list[dict[str, Any]]:
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        with get_session() as session:
            q = select(SorulanUrunAday).where(
                SorulanUrunAday.firma_id == firma,
                SorulanUrunAday.arsiv.is_(bool(arsiv)),
            )
            if arama and arama.strip():
                like = f"%{arama.strip()}%"
                q = q.where(SorulanUrunAday.urun_adi.ilike(like))
            adaylar = session.scalars(
                q.order_by(SorulanUrunAday.id.desc())
            ).all()
            sonuc = []
            for a in adaylar:
                talepler = session.scalars(
                    select(SorulanUrunTalep).where(
                        SorulanUrunTalep.aday_id == a.id,
                        SorulanUrunTalep.gecersiz.is_(False),
                    )
                ).all()
                musteriler = {
                    (t.cari_id or t.musteri_adi or t.telefon)
                    for t in talepler
                    if not t.anonim and (t.cari_id or t.musteri_adi or t.telefon)
                }
                anonim_n = sum(1 for t in talepler if t.anonim)
                son = max((t.talep_tarihi for t in talepler), default=None)
                sonuc.append(
                    {
                        "id": int(a.id),
                        "urun_adi": a.urun_adi,
                        "ozellik": a.ozellik or "",
                        "talep_nedeni": a.talep_nedeni_ozet or "",
                        "son_sorulma": son.isoformat() if son else "",
                        "sorulma_sayisi": len(talepler),
                        "farkli_musteri": len(musteriler),
                        "anonim": anonim_n,
                        "tedarik_durumu": a.tedarik_durumu,
                        "stok_id": a.stok_id,
                        "sorumlu": a.sorumlu_personel or "",
                    }
                )
            return sonuc

    @staticmethod
    def talepler(aday_id: int) -> list[dict[str, Any]]:
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        with get_session() as session:
            rows = session.scalars(
                select(SorulanUrunTalep)
                .where(
                    SorulanUrunTalep.firma_id == firma,
                    SorulanUrunTalep.aday_id == int(aday_id),
                )
                .order_by(SorulanUrunTalep.talep_tarihi.desc(), SorulanUrunTalep.id.desc())
            ).all()
            out = []
            for t in rows:
                istenen = t.miktar
                kalan = None
                if istenen is not None:
                    kalan = max(
                        Decimal("0"),
                        Decimal(str(istenen))
                        - Decimal(str(t.karsilanan_miktar or 0))
                        - Decimal(str(t.iptal_miktar or 0)),
                    )
                out.append(
                    {
                        "id": int(t.id),
                        "tarih": t.talep_tarihi.isoformat(),
                        "musteri": t.musteri_adi or ("Anonim" if t.anonim else ""),
                        "telefon": t.telefon or "",
                        "miktar": str(t.miktar) if t.miktar is not None else "",
                        "kalan": str(kalan) if kalan is not None else "",
                        "niyet": t.niyet,
                        "durum": t.durum,
                        "neden": t.talep_nedeni,
                        "gecersiz": bool(t.gecersiz),
                    }
                )
            return out

    @staticmethod
    def aday_getir(aday_id: int) -> dict[str, Any] | None:
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        with get_session() as session:
            a = session.get(SorulanUrunAday, int(aday_id))
            if a is None or int(a.firma_id) != firma:
                return None
            return {
                "id": int(a.id),
                "urun_adi": a.urun_adi,
                "birim": a.birim or "Adet",
                "stok_id": a.stok_id,
                "tedarik_durumu": a.tedarik_durumu,
                "ozellik": a.ozellik or "",
            }

    @staticmethod
    def satin_alma_taslagina_aktar(
        aday_idler: list[int],
        *,
        miktarlar: dict[int, Any] | None = None,
    ) -> dict[str, Any]:
        """Seçilen adayları mevcut satınalma talebi taslağına aktarır (otomatik onay yok).

        Miktar kullanıcıdan gelmeli; toplam müşteri talebi otomatik alım miktarı sayılmaz.
        Aynı aday için önceki SA bağlantısı notlarda varsa uyarı döner (ikinci aktarım için
        miktar açık verilmelidir).
        """
        yazma_zorunlu()
        from datetime import date as _date

        from database.satin_alma_talep_service import SatinAlmaTalepService

        if not aday_idler:
            raise ValueError("Aktarılacak ürün seçin.")
        miktarlar = miktarlar or {}
        satirlar: list[dict[str, Any]] = []
        baglantilar: list[dict[str, Any]] = []
        for aid in aday_idler:
            aday = SorulanUrunService.aday_getir(int(aid))
            if aday is None:
                raise ValueError(f"Aday bulunamadı: {aid}")
            mik = miktarlar.get(int(aid))
            if mik is None or str(mik).strip() == "":
                # Bilinen kalan miktar yoksa kullanıcı 1 girmek zorunda kalmasın — boş yasak
                raise ValueError(
                    f"«{aday['urun_adi']}» için satın alınacak miktarı açıkça girin "
                    "(müşteri talebi toplamı otomatik alınmaz)."
                )
            miktar_d = Decimal(str(mik))
            if miktar_d <= 0:
                raise ValueError(f"«{aday['urun_adi']}» miktarı pozitif olmalı.")
            satirlar.append(
                {
                    "urun_adi": aday["urun_adi"],
                    "urun_kodu": "",
                    "birim": aday.get("birim") or "Adet",
                    "miktar": miktar_d,
                    "manuel": True,
                    "stok_id": aday.get("stok_id"),
                    "aciklama": f"Sorulan ürün aday #{aday['id']}",
                }
            )
            baglantilar.append({"aday_id": aday["id"], "miktar": str(miktar_d)})

        talep_id = SatinAlmaTalepService.kaydet(
            {
                "talep_tarihi": _date.today(),
                "aciklama": "Sorulan Ürünler aktarımı — otomatik sipariş gönderilmedi.",
            },
            satirlar,
        )
        # Bağlantı: aday tedarik durumunu güncelle + not
        firma = SorulanUrunService._firma_id()
        with get_session() as session:
            for b in baglantilar:
                a = session.get(SorulanUrunAday, int(b["aday_id"]))
                if a is None or int(a.firma_id) != firma:
                    continue
                if a.tedarik_durumu in ("BEKLEMEDE", "ARAŞTIRILIYOR"):
                    a.tedarik_durumu = "ARAŞTIRILIYOR"
                a.guncelleme_tarihi = datetime.utcnow()
                # Takip notu olarak talep satırına değil aday özellik alanına kısa iz
                iz = f"SA_TALEP={talep_id};mik={b['miktar']}"
                eski = (a.ozellik or "").strip()
                if f"SA_TALEP={talep_id}" not in eski:
                    a.ozellik = f"{eski} | {iz}".strip(" |") if eski else iz
            session.flush()
        return {"talep_id": int(talep_id), "satir_sayisi": len(satirlar), "baglantilar": baglantilar}

    @staticmethod
    def oncelik_raporu(*, gun: int = 30, min_musteri: int = 3) -> list[dict[str, Any]]:
        """Son N günde bilinen farklı müşteri eşiğini aşan ürünler (anonim sayılmaz)."""
        from datetime import timedelta

        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        bas = date.today() - timedelta(days=max(1, int(gun)))
        with get_session() as session:
            adaylar = session.scalars(
                select(SorulanUrunAday).where(
                    SorulanUrunAday.firma_id == firma,
                    SorulanUrunAday.arsiv.is_(False),
                )
            ).all()
            sonuc = []
            for a in adaylar:
                talepler = session.scalars(
                    select(SorulanUrunTalep).where(
                        SorulanUrunTalep.aday_id == a.id,
                        SorulanUrunTalep.gecersiz.is_(False),
                        SorulanUrunTalep.talep_tarihi >= bas,
                    )
                ).all()
                musteriler = {
                    (t.cari_id or t.musteri_adi or t.telefon)
                    for t in talepler
                    if not t.anonim and (t.cari_id or t.musteri_adi or t.telefon)
                }
                if len(musteriler) < int(min_musteri):
                    continue
                sonuc.append(
                    {
                        "id": int(a.id),
                        "urun_adi": a.urun_adi,
                        "farkli_musteri": len(musteriler),
                        "sorulma": len(talepler),
                        "anonim": sum(1 for t in talepler if t.anonim),
                        "tedarik_durumu": a.tedarik_durumu,
                    }
                )
            sonuc.sort(key=lambda x: (-x["farkli_musteri"], -x["sorulma"]))
            return sonuc

    @staticmethod
    def donusum_raporu(*, gun: int | None = None) -> dict[str, Any]:
        """Geçerli taleplerde satışa dönüşüm (kısmi satış dahil).

        payda = geçerli (gecersiz değil) tüm talepler; pay = en az bir miktarı
        karşılanan (karsilanan_miktar > 0) talepler. Anonim ayrı sayılır.
        """
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        bas = None
        if gun is not None:
            from datetime import timedelta

            bas = date.today() - timedelta(days=max(1, int(gun)))
        with get_session() as session:
            q = select(SorulanUrunTalep).where(
                SorulanUrunTalep.firma_id == firma,
                SorulanUrunTalep.gecersiz.is_(False),
            )
            if bas is not None:
                q = q.where(SorulanUrunTalep.talep_tarihi >= bas)
            talepler = list(session.scalars(q))
            payda = len(talepler)
            pay = sum(
                1
                for t in talepler
                if (t.karsilanan_miktar or Decimal("0")) > 0
            )
            anonim = sum(1 for t in talepler if t.anonim)
            oran = (Decimal(pay) / Decimal(payda) * 100).quantize(Decimal("0.01")) if payda else None
            return {
                "pay": pay,
                "payda": payda,
                "oran_yuzde": oran,
                "anonim": anonim,
                "bilinen": payda - anonim,
                "kismi_dahil": True,
                "etiket": (
                    f"{pay} / {payda} = %{oran}" if payda and oran is not None else "—"
                ),
            }

    @staticmethod
    def arama_sonucu_kaydet(
        talep_id: int,
        *,
        sonuc_kod: str,
        sonraki_arama: date | None = None,
        notlar: str | None = None,
        aktivite_tamamla: bool = True,
    ) -> dict[str, Any]:
        """Personel görüşme sonucunu kaydeder. Otomatik SMS/WhatsApp yok.

        «Müşteriye bildirildi» yalnızca bu kayıtla doğar; görev tamamlamak satış değildir.
        """
        yazma_zorunlu()
        SorulanUrunService.ensure_schema()
        kod = (sonuc_kod or "").strip().upper()
        if kod not in ARAMA_SONUCLARI:
            raise ValueError(
                "Geçersiz arama sonucu. "
                + ", ".join(ARAMA_SONUCLARI)
            )
        firma = SorulanUrunService._firma_id()
        with get_session() as session:
            t = session.get(SorulanUrunTalep, int(talep_id))
            if t is None or int(t.firma_id) != firma or t.gecersiz:
                raise ValueError("Talep bulunamadı.")
            onceki = (t.notlar or "").rstrip()
            satir = f"Arama sonucu: {kod}"
            if sonraki_arama:
                satir += f"; sonraki={sonraki_arama.isoformat()}"
            if notlar:
                satir += f"; {notlar.strip()}"
            t.notlar = f"{onceki}\n{satir}".strip() if onceki else satir
            t.sonraki_arama = sonraki_arama
            t.guncelleme_tarihi = datetime.utcnow()
            # Durum eşlemesi — satış tek başına doğmaz
            if kod == "SIPARISE_DONUSTU":
                t.durum = "SATISA_DONUSTU"
            elif kod == "VAZGECTI":
                t.durum = "IPTAL"
            elif kod in ("ULASILDI", "FIYAT_BEKLIYOR", "DAHA_SONRA_ARA", "ULASILAMADI"):
                t.durum = "TAKIPTE"
            session.flush()
            tid = int(t.id)
            aday_id = int(t.aday_id)

        if aktivite_tamamla and kod in ("ULASILDI", "VAZGECTI", "SIPARISE_DONUSTU"):
            try:
                from database.aktivite_service import AktiviteService

                mevcut = AktiviteService.kaynak_ile_bul(
                    kaynak_belge_tur="SORULAN_TALEP",
                    kaynak_belge_id=tid,
                    tur_kod="MUSTERI_ARAMASI",
                )
                if mevcut and mevcut["durum"] not in ("TAMAMLANDI", "IPTAL"):
                    AktiviteService.tamamla(int(mevcut["id"]), sonuc_kod=kod)
            except Exception:
                pass
        elif aktivite_tamamla and kod == "DAHA_SONRA_ARA" and sonraki_arama:
            try:
                from database.aktivite_service import AktiviteService

                mevcut = AktiviteService.kaynak_ile_bul(
                    kaynak_belge_tur="SORULAN_TALEP",
                    kaynak_belge_id=tid,
                    tur_kod="MUSTERI_ARAMASI",
                )
                if mevcut and mevcut["durum"] not in ("TAMAMLANDI", "IPTAL"):
                    AktiviteService.ertele(
                        int(mevcut["id"]),
                        yeni_tarih=sonraki_arama,
                        gerekce=f"Arama sonucu: {kod}",
                    )
            except Exception:
                pass

        talepler = SorulanUrunService.talepler(aday_id)
        durum = next((x["durum"] for x in talepler if x["id"] == tid), None)
        return {
            "talep_id": tid,
            "aday_id": aday_id,
            "sonuc": kod,
            "durum": durum,
        }

    # --- Stok geldiğinde müşteri arama görevi (Aktivite) ---

    _ACIK_TALEP_DURUMLARI = frozenset(
        {
            "ACIK",
            "TAKIPTE",
            "SATINALMA_ARA",
            "SIPARIS_VERILDI",
            "URUN_GELDI",
            "ARAMA_BEKLIYOR",
        }
    )

    @staticmethod
    def kullanilabilir_stok(stok_id: int) -> Decimal:
        """Lot kalan toplamı; stok tablosu yoksa 0 (görev üretmez, engellemez)."""
        from sqlalchemy import func

        try:
            from database.models.stok import StokLotu
        except Exception:
            return Decimal("0")
        with get_session() as session:
            deger = session.scalar(
                select(func.coalesce(func.sum(StokLotu.kalan_miktar), 0)).where(
                    StokLotu.stok_id == int(stok_id)
                )
            )
            return Decimal(str(deger or 0))

    @staticmethod
    def stok_bagla(aday_id: int, stok_id: int, *, degerlendir: bool = True) -> dict[str, Any]:
        """Adaya stok kartı bağlar; isteğe bağlı stok değerlendirmesi başlatır."""
        yazma_zorunlu()
        SorulanUrunService.ensure_schema()
        firma = SorulanUrunService._firma_id()
        with get_session() as session:
            a = session.get(SorulanUrunAday, int(aday_id))
            if a is None or int(a.firma_id) != firma:
                raise ValueError("Aday bulunamadı.")
            a.stok_id = int(stok_id)
            a.guncelleme_tarihi = datetime.utcnow()
            session.flush()
        if degerlendir:
            return SorulanUrunService.stok_geldiginde_degerlendir(stok_id=int(stok_id), aday_id=int(aday_id))
        return {"aday_id": int(aday_id), "stok_id": int(stok_id)}

    @staticmethod
    def stok_girisi_sonrasi_degerlendir(
        *,
        stok_id: int,
        olay_anahtar: str = "",
    ) -> dict[str, Any] | None:
        """Stok girişinden sonra çağrılır; hata stok kaydını bozmaz (dışarıda yakalanır)."""
        return SorulanUrunService.stok_geldiginde_degerlendir(
            stok_id=int(stok_id),
            olay_anahtar=olay_anahtar or f"STOK_GIRIS:{stok_id}",
        )

    @staticmethod
    def stok_geldiginde_degerlendir(
        *,
        stok_id: int | None = None,
        aday_id: int | None = None,
        olay_anahtar: str = "",
        mevcut_miktar: Decimal | None = None,
    ) -> dict[str, Any]:
        """Onaylı stok / manuel kontrol: açık talepler için MUSTERI_ARAMASI aktivitesi.

        - Anonim + telefonsuz talep görev üretmez.
        - Aynı talep için tekillik: SORULAN_TALEP + talep_id + MUSTERI_ARAMASI.
        - Stok sıfırsa yeni görev açılmaz; açık görev varsa 'stok yeniden kontrol' notu.
        - Satış/stok işlemini bekletmez; çağıran try/except kullanmalı.
        """
        from database.aktivite_service import AktiviteService

        SorulanUrunService.ensure_schema()
        AktiviteService.ensure_schema()
        firma = SorulanUrunService._firma_id()

        aday_ozet: list[dict[str, Any]] = []
        hedef_stok = int(stok_id) if stok_id else None
        with get_session() as session:
            aday_q = select(SorulanUrunAday).where(
                SorulanUrunAday.firma_id == firma,
                SorulanUrunAday.arsiv.is_(False),
            )
            if aday_id:
                aday_q = aday_q.where(SorulanUrunAday.id == int(aday_id))
            elif stok_id:
                aday_q = aday_q.where(SorulanUrunAday.stok_id == int(stok_id))
            else:
                raise ValueError("stok_id veya aday_id gerekli.")
            for a in session.scalars(aday_q).all():
                if hedef_stok is None and a.stok_id:
                    hedef_stok = int(a.stok_id)
                talepler = session.scalars(
                    select(SorulanUrunTalep).where(
                        SorulanUrunTalep.firma_id == firma,
                        SorulanUrunTalep.aday_id == int(a.id),
                        SorulanUrunTalep.gecersiz.is_(False),
                        SorulanUrunTalep.durum.in_(tuple(SorulanUrunService._ACIK_TALEP_DURUMLARI)),
                    )
                ).all()
                aday_ozet.append(
                    {
                        "id": int(a.id),
                        "urun_adi": a.urun_adi,
                        "talepler": [
                            {
                                "id": int(t.id),
                                "cari_id": t.cari_id,
                                "musteri_adi": t.musteri_adi,
                                "telefon": t.telefon,
                                "anonim": bool(t.anonim),
                                "miktar": t.miktar,
                                "durum": t.durum,
                            }
                            for t in talepler
                        ],
                    }
                )

        if not aday_ozet:
            return {
                "olusturulan": 0,
                "guncellenen": 0,
                "atlanan": 0,
                "neden": "bagli_aday_yok",
            }

        miktar = mevcut_miktar
        if miktar is None:
            miktar = (
                SorulanUrunService.kullanilabilir_stok(hedef_stok)
                if hedef_stok
                else Decimal("0")
            )

        olusturulan = 0
        guncellenen = 0
        atlanan = 0
        detay: list[dict[str, Any]] = []
        durum_guncelle: list[int] = []

        for aday in aday_ozet:
            for t in aday["talepler"]:
                tel = (t.get("telefon") or "").strip()
                if t.get("anonim") and not tel:
                    atlanan += 1
                    detay.append({"talep_id": t["id"], "sonuc": "anonim_iletisim_yok"})
                    continue
                if not tel and not t.get("cari_id") and not (t.get("musteri_adi") or "").strip():
                    atlanan += 1
                    detay.append({"talep_id": t["id"], "sonuc": "iletisim_yok"})
                    continue

                musteri = (t.get("musteri_adi") or "").strip() or (
                    f"Cari#{t['cari_id']}" if t.get("cari_id") else "Müşteri"
                )
                konu = f"Ara: {musteri} — {aday['urun_adi']}"
                aciklama = (
                    f"Sorulan talep #{t['id']}\n"
                    f"Ürün: {aday['urun_adi']}\n"
                    f"Talep miktarı: {t['miktar'] if t['miktar'] is not None else 'bilinmiyor'}\n"
                    f"Kullanılabilir stok: {miktar}\n"
                    f"Telefon: {tel or '—'}\n"
                    f"Stok sınırlı olabilir; tüm müşterilere yeterlilik taahhüdü yok.\n"
                    f"Olay: {olay_anahtar or 'manuel_kontrol'}"
                )

                if miktar <= 0:
                    mevcut = AktiviteService.kaynak_ile_bul(
                        kaynak_belge_tur="SORULAN_TALEP",
                        kaynak_belge_id=int(t["id"]),
                        tur_kod="MUSTERI_ARAMASI",
                    )
                    if mevcut and mevcut["durum"] not in ("TAMAMLANDI", "IPTAL"):
                        AktiviteService.kaynak_ile_kaydet_veya_guncelle(
                            {
                                "kaynak_belge_tur": "SORULAN_TALEP",
                                "kaynak_belge_id": int(t["id"]),
                                "kaynak_belge_no": f"SRT-{t['id']}",
                                "tur_kod": "MUSTERI_ARAMASI",
                                "konu": konu,
                                "cari_id": t.get("cari_id"),
                                "aciklama": aciklama
                                + "\n⚠ Stok yeniden kontrol edilmeli (miktar bitti).",
                                "durum": "BEKLEMEDE",
                                "oncelik": "NORMAL",
                            }
                        )
                        guncellenen += 1
                        detay.append({"talep_id": t["id"], "sonuc": "stok_bitti_guncelle"})
                    else:
                        atlanan += 1
                        detay.append({"talep_id": t["id"], "sonuc": "stok_yok"})
                    continue

                kayit = AktiviteService.kaynak_ile_kaydet_veya_guncelle(
                    {
                        "kaynak_belge_tur": "SORULAN_TALEP",
                        "kaynak_belge_id": int(t["id"]),
                        "kaynak_belge_no": f"SRT-{t['id']}",
                        "tur_kod": "MUSTERI_ARAMASI",
                        "konu": konu,
                        "cari_id": t.get("cari_id"),
                        "aciklama": aciklama,
                        "durum": "ACIK",
                        "oncelik": "YUKSEK",
                        "plan_tarih": date.today(),
                        "sorumlu_personel_id": None,
                    }
                )
                if kayit.get("guncellendi"):
                    guncellenen += 1
                else:
                    olusturulan += 1
                if t["durum"] in ("ACIK", "TAKIPTE", "URUN_GELDI", "SIPARIS_VERILDI"):
                    durum_guncelle.append(int(t["id"]))
                detay.append(
                    {
                        "talep_id": t["id"],
                        "aktivite_id": kayit["id"],
                        "sonuc": "guncelle" if kayit.get("guncellendi") else "olustur",
                    }
                )

        with get_session() as session:
            if miktar > 0:
                for aday in aday_ozet:
                    a = session.get(SorulanUrunAday, int(aday["id"]))
                    if a is not None and int(a.firma_id) == firma:
                        a.tedarik_durumu = "STOKTA"
                        a.guncelleme_tarihi = datetime.utcnow()
            for tid in durum_guncelle:
                trow = session.get(SorulanUrunTalep, tid)
                if trow is not None and int(trow.firma_id) == firma:
                    trow.durum = "ARAMA_BEKLIYOR"
                    trow.guncelleme_tarihi = datetime.utcnow()
            session.flush()

        return {
            "olusturulan": olusturulan,
            "guncellenen": guncellenen,
            "atlanan": atlanan,
            "mevcut_miktar": str(miktar),
            "stok_id": hedef_stok,
            "detay": detay,
        }
