"""Çift yönlü cari ortalama valör / yaş hesabı (borç / alacak bakiyesi).

Salt okunur: cari hareket yazmaz.
Net bakiye: borç − alacak (pozitif → Borçlu, negatif → Alacaklı).

Tanımlar (talimat 13.11.2026):
  T = hesap tarihi, I = belge/işlem tarihi, V = vade, P = ödeme/tahsilat tarihi
  Açık valör (kart özeti) = T − I  (ağırlık: kalan açık tutar; belge yaşı)
  Kapanan valör = P − I (ağırlık: eşleşen tutar m; aynı gün → 0)
  Vade gecikmesi T−V / P−V dilimde ayrıca tutulabilir; kart özeti P−I kullanır.
  Eşleştirme: doğrulanmış CariKapatma bağlantısı önce; kalan tutar FIFO
  (I → belge_no → id). Aynı belgedeki borç+alacak önce kendi içinde kapanır.

  Tedarikçi: alış ``satis_tutari<0`` ve açılış alacağı kuyruk; ödeme (borç) FIFO düşer.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import select

from database.database import get_session
from database.models.cari import Cari, CariIslem, SatisHareketi

logger = logging.getLogger("cari_ortalama_valor")

KURUS = Decimal("0.01")
ZERO = Decimal("0")


def _d(deger) -> Decimal:
    if deger is None:
        return ZERO
    if isinstance(deger, Decimal):
        return deger
    try:
        return Decimal(str(deger))
    except Exception:
        return ZERO


def _kurus(tutar) -> Decimal:
    return _d(tutar).quantize(KURUS, rounding=ROUND_HALF_UP)


def _yon_etiket(bakiye: Decimal) -> tuple[str, str, str]:
    """(bakiye_yonu, valor_turu, bakiye_durumu_ui)."""
    if bakiye > 0:
        return "BORCLU", "BORC", "Borçlu"
    if bakiye < 0:
        return "ALACAKLI", "ALACAK", "Alacaklı"
    return "KAPALI", "YOK", "Kapalı"


def _valor_turu_etiket(valor_turu: str) -> str:
    if valor_turu == "BORC":
        return "Borç Valörü"
    if valor_turu == "ALACAK":
        return "Alacak Valörü"
    return "Valör Yok"


def _islem_tarihi(dilim: dict[str, Any]) -> date | None:
    """Orijinal mali işlem tarihi I."""
    t = (
        dilim.get("borc_tarihi")
        or dilim.get("alacak_tarihi")
        or dilim.get("belge_tarihi")
        or dilim.get("islem_tarihi")
    )
    return t if isinstance(t, date) else None


def _vade_tarihi(dilim: dict[str, Any]) -> date | None:
    """Esas vade V: özgün vade; yoksa belge/işlem tarihi (talimat 08.11.2026).

    Avans / valor_uygulanamaz kalemlerde None. Bugünün tarihini uydurmaz.
    """
    if dilim.get("valor_uygulanamaz"):
        return None
    esas = dilim.get("esas_vade")
    if isinstance(esas, date):
        return esas
    t = dilim.get("borc_vadesi") or dilim.get("alacak_vadesi") or dilim.get("vade")
    if isinstance(t, date) and not dilim.get("vade_eksik"):
        return t
    if isinstance(t, date):
        return t
    return _islem_tarihi(dilim)


def _esas_vade_ve_kaynak(
    vade_gercek: date | None, belge_tarih: date | None
) -> tuple[date | None, str | None, bool]:
    """(esas_vade, vade_kaynak, ozgun_vade_eksik)."""
    if isinstance(vade_gercek, date):
        return vade_gercek, "VADE", False
    if isinstance(belge_tarih, date):
        return belge_tarih, "BELGE_TARIHI", True
    return None, None, True


def _fifo_anahtar_hareket(h) -> tuple:
    """AcikKalemService.fifo_sirasi ile aynı: I → belge_no → id."""
    return (
        getattr(h, "satis_tarihi", None) or date.min,
        getattr(h, "belge_no", None) or "",
        int(getattr(h, "id", 0) or 0),
    )


def _fifo_anahtar_islem(i) -> tuple:
    return (
        getattr(i, "tarih", None) or date.min,
        getattr(i, "belge_no", None) or "",
        int(getattr(i, "id", 0) or 0),
    )


def _agirlikli_ortalama_gun(
    dilimler: list[dict[str, Any]], *, gun_alani: str = "gun"
) -> float:
    """Σ(tutar × gün) / Σ(tutar); gün None olanlar dışarıda."""
    toplam = ZERO
    agirlik = 0.0
    for d in dilimler:
        tutar = _kurus(d.get("tutar"))
        if tutar <= 0:
            continue
        g = d.get(gun_alani)
        if g is None:
            continue
        try:
            gun = float(g)
        except (TypeError, ValueError):
            continue
        toplam += tutar
        agirlik += float(tutar) * gun
    return agirlik / float(toplam) if toplam else 0.0


def _ortalama_tarih_ve_gun(
    dilimler: list[dict[str, Any]],
    referans: date,
    *,
    valor: bool = True,
    avans_dahil: bool = False,
) -> tuple[date | None, float, Decimal, Decimal, str | None]:
    """Açık kalanlar üzerinden ağırlıklı ortalama.

    valor=True → gün = T−V, ortalama tarih ≈ V ağırlıklı.
    valor=False → gün = T−I (yaş), ortalama tarih ≈ I ağırlıklı.
    avans_dahil=False (varsayılan): Açık Valör hesabında AVANS hariç.
    avans_dahil=True: salt avans bekleme yaşı için.
    Dönüş: (ortalama_tarih, gun, dahil_tutar, haric_tutar, uyari)
    """
    toplam = ZERO
    haric = ZERO
    ord_agirlik = ZERO
    gun_agirlik = 0.0
    for d in dilimler:
        tutar = _kurus(d.get("tutar"))
        if tutar <= 0:
            continue
        if valor:
            if d.get("valor_uygulanamaz"):
                haric += tutar
                continue
            vade = _vade_tarihi(d)
            if vade is None:
                haric += tutar
                continue
            gun = (referans - vade).days
            ord_agirlik += tutar * Decimal(vade.toordinal())
        else:
            # Açık valör: avans/fazla ödeme ağırlığa girmez (bekleme yaşı ayrı)
            if not avans_dahil and (
                d.get("valor_uygulanamaz") or d.get("kalem_turu") == "AVANS"
            ):
                haric += tutar
                continue
            islem = _islem_tarihi(d)
            if islem is None:
                haric += tutar
                continue
            gun = (referans - islem).days
            ord_agirlik += tutar * Decimal(islem.toordinal())
        toplam += tutar
        gun_agirlik += float(tutar) * float(gun)

    if toplam <= 0:
        uyari = None
        if haric > 0:
            uyari = (
                "Açık valör üretilemedi: vadesi bilinmeyen / avans tutarları "
                f"({_kurus(haric)} TL) ağırlığa alınmadı."
                if valor
                else f"İşlem tarihi eksik tutar ({_kurus(haric)} TL) yaş hesabına alınmadı."
            )
        return None, 0.0, ZERO, _kurus(haric), uyari

    avg_ord = int((ord_agirlik / toplam).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    ortalama_tarih = date.fromordinal(avg_ord)
    gun = gun_agirlik / float(toplam)
    uyari = None
    if haric > 0:
        uyari = (
            f"Açık tutarın {_kurus(haric)} TL kısmı vade/valör eksikliği nedeniyle "
            "ortalama valöre dahil edilmedi."
            if valor
            else f"Açık tutarın {_kurus(haric)} TL kısmı tarih eksikliği nedeniyle yaşa dahil edilmedi."
        )
    return ortalama_tarih, float(gun), _kurus(toplam), _kurus(haric), uyari


def _bos_sonuc(
    bakiye: Decimal,
    *,
    uyari: str | None = None,
    sebep: str | None = None,
) -> dict[str, Any]:
    yon, tur, durum = _yon_etiket(bakiye)
    return {
        "bakiye": _kurus(bakiye),
        "bakiye_yonu": yon,
        "bakiye_durumu": durum,
        "valor_turu": tur,
        "valor_turu_etiket": _valor_turu_etiket(tur),
        "ortalama_valor_tarihi": None,
        "ortalama_valor_gun": None if sebep else 0.0,
        "ortalama_yas_gun": None if sebep else 0.0,
        "ortalama_yas_tarihi": None,
        "toplam_acik_tutar": ZERO,
        "valor_dahil_tutar": ZERO,
        "valor_haric_tutar": ZERO,
        "acik_kalemler": [],
        "uyari": uyari,
        "hesaplama_sebep": sebep,
        "olcu": "acik_valor_T_eksi_V",
    }


def fifo_valor_paketi_hesapla(
    hareketler: list[SatisHareketi],
    islemler: list[CariIslem],
    *,
    cari_turu: str | None = None,
    vade_harita: dict[str, date] | None = None,
    referans: date | None = None,
    sadece_acik: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """FIFO: (tam_kapanan_borç, açık_borç, kapanan_dilimler, açık_alacak).

    Sıra: işlem tarihi → belge_no → id (liste sıralamasından bağımsız).
    """
    from database.cari_service import CariService

    bugun = referans or date.today()
    vade_harita = vade_harita or {}

    tedarikci = (cari_turu or "").casefold().startswith("tedarik")
    hareketler_sirali = sorted(hareketler, key=_fifo_anahtar_hareket)
    islemler_sirali = sorted(islemler, key=_fifo_anahtar_islem)

    # Borç kuyruğu: SatisHareketi asıl kaynak. Aynı belgede CariIslem olsa bile SH
    # düşülmez (EVB açılış/devir hem SH hem CI borç yazar; SH'yi atlamak ~bakiye kadar
    # açık kalemi yok ediyordu — ABERRA 4,2 gün hatası). CI borç yalnız SH'de yoksa eklenir.
    # [vade|None, belge_tarih, kalan, orijinal, belge_no, son_odeme, vade_eksik]
    ham_borclar: list[tuple] = []
    borc_belgeleri: set[str] = set()
    for h in hareketler_sirali:
        raw = _kurus(h.satis_tutari)
        if tedarikci:
            # Alış faturası SatisHareketi'nde negatif tutar olarak durur
            if raw >= 0:
                continue
            tutar = -raw
        else:
            if raw <= 0:
                continue
            tutar = raw
        no = h.belge_no or ""
        if no.startswith(CariService._VALOR_BORC_HARIC_ONEK):
            continue
        vade_gercek = vade_harita.get(no) if no else None
        vade_eksik = vade_gercek is None
        # Kuyrukta işlem için yedek tarih (FIFO eşleştirme); valor hesabında vade_eksik işaretli
        vade_kuyruk = vade_gercek if vade_gercek is not None else (h.satis_tarihi or date.min)
        ham_borclar.append(
            (
                h.satis_tarihi or date.min,
                int(getattr(h, "id", 0) or 0),
                no,
                vade_kuyruk,
                tutar,
                vade_eksik,
                vade_gercek,
            )
        )
        if no:
            borc_belgeleri.add(no)

    _TEDARIKCI_ODEME_TURLERI = ("Ödeme", "Virman Ödeme", "KK Çekimi")
    for islem in islemler_sirali:
        no = (islem.belge_no or "").strip()
        if tedarikci:
            # Açılış / alacak belgesi = tedarikçiye borç; ödeme (ve müşteriden tedarikçiye) kuyruğa alınmaz
            if (islem.islem_turu or "") in _TEDARIKCI_ODEME_TURLERI:
                continue
            tutar = _kurus(getattr(islem, "alacak", None))
        else:
            tutar = _kurus(getattr(islem, "borc", None))
        if tutar <= 0:
            continue
        if not no or no in borc_belgeleri:
            continue
        if no.startswith(CariService._VALOR_BORC_HARIC_ONEK):
            continue
        belge_tarih = islem.tarih
        vade_gercek = vade_harita.get(no) if vade_harita else None
        vade_eksik = vade_gercek is None
        vade_kuyruk = vade_gercek if vade_gercek is not None else (belge_tarih or date.min)
        ham_borclar.append(
            (
                belge_tarih or date.min,
                int(getattr(islem, "id", 0) or 0),
                no,
                vade_kuyruk,
                tutar,
                vade_eksik,
                vade_gercek,
            )
        )
        borc_belgeleri.add(no)

    ham_borclar.sort(key=lambda x: (x[0], x[2], x[1]))  # tarih, belge_no, id
    kuyruk: list[list] = [
        [
            (vade_gercek if not vade_eksik else None),
            (tarih if tarih != date.min else None),
            tutar,
            tutar,
            no,
            None,
            vade_eksik,
        ]
        for tarih, _hid, no, _vk, tutar, vade_eksik, vade_gercek in ham_borclar
    ]

    kapanan_dilimler: list[dict[str, Any]] = []
    acik_alacak: list[dict[str, Any]] = []

    def _kapanan_dilim_yaz(
        *,
        odeme_belge: str | None,
        odeme_tarih: date | None,
        borc_no: str,
        belge_tarih: date | None,
        vade,
        vade_eksik: bool,
        dilim: Decimal,
        yontem: str,
        kapanis_turu: str,
        acilis_aktarim: bool = False,
    ) -> None:
        if sadece_acik:
            return
        esas, vade_kaynak, ozgun_eksik = _esas_vade_ve_kaynak(
            vade if not vade_eksik else None, belge_tarih
        )
        # Ham P−I: açılış BORÇ → sonraki DEVIREN teknik aktarım (P<I) valör dışı
        ham_gun = None
        if odeme_tarih is not None and belge_tarih is not None:
            ham_gun = (odeme_tarih - belge_tarih).days
        teknik_acilis = bool(acilis_aktarim) or (ham_gun is not None and ham_gun < 0)
        # Kart kapanan valör = P − I; aynı gün → 0. Teknik açılış pay/paydada yok.
        if ham_gun is None:
            kapanan_gun = None
        else:
            kapanan_gun = max(0, ham_gun)
        vade_farki = (odeme_tarih - esas).days if esas and odeme_tarih else None
        kapanan_dilimler.append(
            {
                "odeme_belge_no": odeme_belge,
                "odeme_tarihi": odeme_tarih,
                "borc_belge_no": borc_no,
                "borc_tarihi": belge_tarih,
                "borc_vadesi": vade if not vade_eksik else None,
                "esas_vade": esas,
                "vade_kaynak": vade_kaynak,
                "vade_eksik": bool(ozgun_eksik),
                "tutar": dilim,
                "gun": kapanan_gun,
                "kapanan_valor_gun": kapanan_gun,
                "vade_farki_gun": vade_farki,
                "odeme_suresi_gun": kapanan_gun,
                "yon": "BORC",
                "yontem": yontem,
                "kapanis_turu": "ACILIS_AKTARIM" if teknik_acilis else kapanis_turu,
                "kalem_turu": "ACILIS_AKTARIM" if teknik_acilis else "KAPAMA",
                "kapanan_valor_haric": teknik_acilis,
            }
        )

    if kuyruk or islemler_sirali:
        bas = 0
        for islem in islemler_sirali:
            kalan_odeme = CariService._odeme_borc_dusurur_mu(islem, tedarikci)
            if kalan_odeme <= 0:
                continue
            kalan_odeme = _kurus(kalan_odeme)
            odeme_no = (islem.belge_no or "").strip()

            acilis_kredi = CariService._tedarikci_acilis_borc_mu(islem) if tedarikci else False

            def _uygula(indeksler: list[int], *, ayni_belge: bool) -> None:
                nonlocal kalan_odeme, bas
                for i in indeksler:
                    if kalan_odeme <= 0:
                        break
                    dilim_satir = kuyruk[i]
                    vade, belge_tarih, kalan_dilim, _orj, borc_no, _son, vade_eksik = dilim_satir
                    if kalan_dilim <= 0:
                        continue
                    # Açılış BORÇ, sonraki DEVIREN/alışa mahsup edilebilir; normal ödemede
                    # gelecek tarihli faturaya avans yazılır (tarih kısıtı).
                    if (
                        not acilis_kredi
                        and belge_tarih
                        and islem.tarih
                        and belge_tarih > islem.tarih
                    ):
                        continue
                    dilim = min(kalan_dilim, kalan_odeme)
                    dilim = _kurus(dilim)
                    dilim_satir[2] = _kurus(kalan_dilim - dilim)
                    dilim_satir[5] = islem.tarih
                    _kapanan_dilim_yaz(
                        odeme_belge=islem.belge_no,
                        odeme_tarih=islem.tarih,
                        borc_no=borc_no,
                        belge_tarih=belge_tarih,
                        vade=vade,
                        vade_eksik=vade_eksik,
                        dilim=dilim,
                        yontem="AYNI_BELGE" if ayni_belge else "FIFO",
                        kapanis_turu="AYNI_BELGE" if ayni_belge else "TAHSILAT_ODEME",
                        acilis_aktarim=acilis_kredi,
                    )
                    kalan_odeme = _kurus(kalan_odeme - dilim)

            # 1) Aynı belge içi kapama (RAY-00026 borç+alacak vb.) — 0 gün / P−I
            if odeme_no:
                ayni = [
                    i
                    for i in range(len(kuyruk))
                    if kuyruk[i][2] > 0 and (kuyruk[i][4] or "") == odeme_no
                ]
                _uygula(ayni, ayni_belge=True)

            # 2) Serbest tutar: en eski uygun açık borç (FIFO)
            if kalan_odeme > 0:
                _uygula(list(range(bas, len(kuyruk))), ayni_belge=False)

            while bas < len(kuyruk) and kuyruk[bas][2] <= 0:
                bas += 1

            # Ödeme fazlası → açık alacak / avans (sözleşmesel vade yok)
            if kalan_odeme > 0:
                islem_t = islem.tarih
                yas = (bugun - islem_t).days if islem_t else 0
                acik_alacak.append(
                    {
                        "alacak_belge_no": islem.belge_no,
                        "alacak_tarihi": islem_t,
                        "alacak_vadesi": None,
                        "vade_eksik": True,
                        "valor_uygulanamaz": True,
                        "kalem_turu": "AVANS",
                        "tutar": kalan_odeme,
                        # Valör uygulanamaz; bekleme yaşı ayrıca yas_gun
                        "gun": None,
                        "yas_gun": yas,
                        "vade_farki_gun": None,
                        "yon": "ALACAK",
                    }
                )

    kapanan: list[dict[str, Any]] = []
    acik_borc: list[dict[str, Any]] = []
    for vade, belge_tarih, kalan_dilim, orijinal, borc_no, son_odeme, vade_eksik in kuyruk:
        if kalan_dilim <= 0 and son_odeme is not None:
            if not sadece_acik:
                esas, vade_kaynak, ozgun_eksik = _esas_vade_ve_kaynak(
                    vade if not vade_eksik else None, belge_tarih
                )
                kapanan_gun = (
                    max(0, (son_odeme - belge_tarih).days)
                    if belge_tarih and son_odeme
                    else None
                )
                kapanan.append(
                    {
                        "borc_belge_no": borc_no,
                        "borc_tarihi": belge_tarih,
                        "borc_vadesi": vade if not vade_eksik else None,
                        "esas_vade": esas,
                        "vade_kaynak": vade_kaynak,
                        "vade_eksik": bool(ozgun_eksik),
                        "kapanma_tarihi": son_odeme,
                        "tutar": orijinal,
                        "gun": kapanan_gun,
                        "kapanan_valor_gun": kapanan_gun,
                        "yon": "BORC",
                        "yontem": "FIFO",
                    }
                )
        elif kalan_dilim > 0:
            yas = (bugun - belge_tarih).days if belge_tarih else None
            esas, vade_kaynak, ozgun_eksik = _esas_vade_ve_kaynak(
                vade if not vade_eksik else None, belge_tarih
            )
            # Kart açık valör = belge yaşı T−I (talimat 13.11.2026)
            acik_valor = yas
            vade_farki = (bugun - esas).days if esas is not None else None
            acik_borc.append(
                {
                    "borc_belge_no": borc_no,
                    "borc_tarihi": belge_tarih,
                    "borc_vadesi": vade if not vade_eksik else None,
                    "esas_vade": esas,
                    "vade_kaynak": vade_kaynak,
                    "vade_eksik": bool(ozgun_eksik),
                    "valor_uygulanamaz": belge_tarih is None,
                    "kalem_turu": "FATURA",
                    "tutar": kalan_dilim,
                    "gun": acik_valor,  # açık valör T−I
                    "yas_gun": yas if yas is not None else 0,
                    "vade_farki_gun": vade_farki,
                    "yon": "BORC",
                }
            )
    if tedarikci and acik_borc:
        # Tedarikçi açık alış kartta alacak yönünde; avans ödemeleri ayrı kalır
        donusen: list[dict[str, Any]] = []
        for d in acik_borc:
            parca = dict(d)
            parca["yon"] = "ALACAK"
            parca["alacak_belge_no"] = d.get("borc_belge_no")
            parca["alacak_tarihi"] = d.get("borc_tarihi")
            parca["alacak_vadesi"] = d.get("borc_vadesi")
            donusen.append(parca)
        acik_alacak = donusen + list(acik_alacak)
        acik_borc = []
    return kapanan, acik_borc, kapanan_dilimler, acik_alacak


def _kredi_ile_fifo_dus(
    dilimler: list[dict[str, Any]], kredi: Decimal
) -> list[dict[str, Any]]:
    """Açık karşı taraf tutarını en eski kalemlerden FIFO düşer; net bakiye dilimleri kalır."""
    kalan = _kurus(kredi)
    if kalan <= 0:
        return [dict(d) for d in dilimler if _kurus(d.get("tutar")) > 0]
    sirali = sorted(
        [d for d in dilimler if _kurus(d.get("tutar")) > 0],
        key=lambda x: (
            _islem_tarihi(x) or date.min,
            str(x.get("borc_belge_no") or x.get("alacak_belge_no") or ""),
            int(x.get("id") or 0),
        ),
    )
    sonuc: list[dict[str, Any]] = []
    for d in sirali:
        tutar = _kurus(d.get("tutar"))
        if kalan <= 0:
            sonuc.append(dict(d))
            continue
        if kalan >= tutar:
            kalan -= tutar
            continue
        parca = dict(d)
        parca["tutar"] = tutar - kalan
        kalan = ZERO
        sonuc.append(parca)
    return sonuc


def _sonuc_olustur(
    bakiye: Decimal,
    acik_borc: list[dict[str, Any]],
    acik_alacak: list[dict[str, Any]],
    referans: date,
) -> dict[str, Any]:
    yon, tur, durum = _yon_etiket(bakiye)
    if tur == "YOK":
        return _bos_sonuc(bakiye, sebep="Bakiye kapalı")

    if tur == "BORC":
        ham = [d for d in acik_borc if _kurus(d.get("tutar")) > 0]
        kredi = sum((_kurus(d.get("tutar")) for d in acik_alacak), ZERO)
        dilimler = _kredi_ile_fifo_dus(ham, kredi)
        if not dilimler:
            return _bos_sonuc(
                bakiye,
                sebep="Açık hareket yok",
                uyari="Borç bakiyesi var ancak açık borç kalemi bulunamadı.",
            )
    else:
        ham = [d for d in acik_alacak if _kurus(d.get("tutar")) > 0]
        borc_brut = sum((_kurus(d.get("tutar")) for d in acik_borc), ZERO)
        dilimler = _kredi_ile_fifo_dus(ham, borc_brut)
        if not dilimler:
            return _bos_sonuc(
                bakiye,
                sebep="Açık hareket yok",
                uyari="Alacak bakiyesi var ancak açık alacak kalemi bulunamadı.",
            )

    # Açık valör = belge yaşı T−I (talimat 13.11.2026); yaş ile aynı ölçü
    yas_tarih, yas_gun, yas_tutar, yas_haric, yas_uyari = _ortalama_tarih_ve_gun(
        dilimler, referans, valor=False
    )

    # Salt avans / fazla ödeme: fatura borcu yaşı gibi gösterme
    hepsi_avans = tur == "ALACAK" and all(
        d.get("valor_uygulanamaz") or d.get("kalem_turu") == "AVANS" for d in dilimler
    )
    if hepsi_avans:
        yas_t, yas_g, yas_tut, _, _ = _ortalama_tarih_ve_gun(
            dilimler, referans, valor=False, avans_dahil=True
        )
        yas_g_q = (
            float(Decimal(str(yas_g)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            if yas_tut > 0
            else None
        )
        return {
            "bakiye": _kurus(bakiye),
            "bakiye_yonu": yon,
            "bakiye_durumu": durum,
            "valor_turu": tur,
            "valor_turu_etiket": "Avans / fazla ödeme (fatura valörü yok)",
            "ortalama_valor_tarihi": None,
            "ortalama_valor_gun": None,
            "ortalama_yas_gun": yas_g_q,
            "ortalama_yas_tarihi": yas_t,
            "toplam_acik_tutar": _kurus(sum((_kurus(d.get("tutar")) for d in dilimler), ZERO)),
            "valor_dahil_tutar": ZERO,
            "valor_haric_tutar": _kurus(sum((_kurus(d.get("tutar")) for d in dilimler), ZERO)),
            "acik_kalemler": dilimler,
            "uyari": (
                "Avans / fazla tahsilat veya ödeme: açık fatura kalemi yok; "
                "Açık Valör «—». Bekleme yaşı (T−I) metrikte ayrıca tutulur."
            ),
            "hesaplama_sebep": None,
            "olcu": "avans_bekleme_yasi_T_eksi_I",
        }

    toplam_acik = _kurus(sum((_kurus(d.get("tutar")) for d in dilimler), ZERO))

    if yas_tutar <= 0:
        return {
            "bakiye": _kurus(bakiye),
            "bakiye_yonu": yon,
            "bakiye_durumu": durum,
            "valor_turu": tur,
            "valor_turu_etiket": _valor_turu_etiket(tur),
            "ortalama_valor_tarihi": None,
            "ortalama_valor_gun": None,
            "ortalama_yas_gun": None,
            "ortalama_yas_tarihi": None,
            "toplam_acik_tutar": toplam_acik,
            "valor_dahil_tutar": ZERO,
            "valor_haric_tutar": yas_haric,
            "acik_kalemler": dilimler,
            "uyari": yas_uyari or "— / açık valör yok (belge tarihi eksik)",
            "hesaplama_sebep": "Tarih eksik",
            "olcu": "acik_valor_T_eksi_I",
        }

    uyari = yas_uyari
    # Açık valör yalnız fatura/açık borç dilimlerinden; avans hariç tutarı uyar
    valor_dahil = yas_tutar
    valor_haric = yas_haric
    fark = abs(_kurus(abs(bakiye)) - toplam_acik)
    if fark > KURUS:
        ek = (
            f"Bakiye ({_kurus(bakiye)}) ile açık kalem toplamı ({toplam_acik}) "
            f"arasında {fark} TL fark var."
        )
        uyari = f"{uyari} {ek}".strip() if uyari else ek
        logger.debug(
            "ortalama_valor bakiye/acik uyumsuzlugu: bakiye=%s acik=%s fark=%s",
            bakiye,
            toplam_acik,
            fark,
        )

    # Σ(açık × yaş) / Σ(açık) → iki ondalık
    gun_yuvarla = float(
        Decimal(str(yas_gun)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )

    return {
        "bakiye": _kurus(bakiye),
        "bakiye_yonu": yon,
        "bakiye_durumu": durum,
        "valor_turu": tur,
        "valor_turu_etiket": _valor_turu_etiket(tur),
        "ortalama_valor_tarihi": yas_tarih,
        "ortalama_valor_gun": gun_yuvarla,
        "ortalama_yas_gun": gun_yuvarla,
        "ortalama_yas_tarihi": yas_tarih,
        "toplam_acik_tutar": toplam_acik,
        "valor_dahil_tutar": valor_dahil,
        "valor_haric_tutar": valor_haric,
        "acik_kalemler": dilimler,
        "uyari": uyari,
        "hesaplama_sebep": None,
        "olcu": "acik_valor_T_eksi_I",
    }


def kapanan_valor_ortalama(kapanan_dilimler: list[dict[str, Any]]) -> dict[str, Any]:
    """Σ(m × (P−I)) / Σ(m) — kart kapanan valör; P−V ayrı ``vade_farki`` olarak tutulur.

    Teknik açılış aktarımı (``kapanan_valor_haric`` / ACILIS_AKTARIM) pay ve paydada yok.
    Sıfır günlü gerçek aynı-gün kapama paydada kalır (m×0).
    """
    gecerli = []
    vade_gecerli = []
    haric = ZERO
    acilis_haric = ZERO
    for d in kapanan_dilimler:
        tutar = _kurus(d.get("tutar"))
        if tutar <= 0:
            continue
        if d.get("kapanan_valor_haric") or d.get("kalem_turu") == "ACILIS_AKTARIM":
            acilis_haric += tutar
            continue
        g = d.get("kapanan_valor_gun")
        if g is None:
            g = d.get("odeme_suresi_gun")
        if g is None:
            p = d.get("odeme_tarihi") or d.get("kapanma_tarihi")
            i = d.get("borc_tarihi")
            if isinstance(p, date) and isinstance(i, date):
                g = (p - i).days
        if g is None:
            haric += tutar
        else:
            gecerli.append({"tutar": tutar, "gun": float(max(0, int(g)))})
        vf = d.get("vade_farki_gun")
        if vf is None:
            p = d.get("odeme_tarihi") or d.get("kapanma_tarihi")
            v = d.get("esas_vade") or d.get("borc_vadesi")
            if isinstance(p, date) and isinstance(v, date):
                vf = (p - v).days
        if vf is not None:
            # Erken ödeme: P−V negatif bırakılır
            vade_gecerli.append({"tutar": tutar, "gun": float(vf)})
    if not gecerli:
        return {
            "odenen_ortalama_valor_gun": None,
            "ortalama_odeme_suresi_gun": None,
            "ortalama_vade_farki_gun": (
                _agirlikli_ortalama_gun(vade_gecerli) if vade_gecerli else None
            ),
            "kapanan_tutar": ZERO,
            "kapanan_haric_tutar": _kurus(haric + acilis_haric),
            "acilis_aktarim_haric_tutar": _kurus(acilis_haric),
            "uyari": (
                "— / kapanan işlem yok"
                if haric == 0 and acilis_haric == 0
                else (
                    f"Teknik açılış aktarımı {_kurus(acilis_haric)} TL kapanan valör dışı."
                    if acilis_haric > 0
                    else "Kapanan dilimlerde tarih eksik"
                )
            ),
            "olcu": "kapanan_valor_P_eksi_I",
        }
    gun = _agirlikli_ortalama_gun(gecerli, gun_alani="gun")
    gun_q = float(Decimal(str(gun)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    tutar = _kurus(sum((_kurus(d["tutar"]) for d in gecerli), ZERO))
    vade_ort = (
        _agirlikli_ortalama_gun(vade_gecerli) if vade_gecerli else None
    )
    if vade_ort is not None:
        vade_ort = float(
            Decimal(str(vade_ort)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
    uyari = None
    if haric > 0:
        uyari = f"Kapanan tutarın {_kurus(haric)} TL kısmı tarih eksikliği nedeniyle hariç."
    if acilis_haric > 0:
        ek = f"Teknik açılış aktarımı {_kurus(acilis_haric)} TL pay/paydada yok."
        uyari = f"{uyari} {ek}".strip() if uyari else ek
    return {
        "odenen_ortalama_valor_gun": gun_q,
        "ortalama_odeme_suresi_gun": gun_q,  # P−I ile aynı ölçü
        "ortalama_vade_farki_gun": vade_ort,
        "kapanan_tutar": tutar,
        "kapanan_haric_tutar": _kurus(haric + acilis_haric),
        "acilis_aktarim_haric_tutar": _kurus(acilis_haric),
        "uyari": uyari,
        "olcu": "kapanan_valor_P_eksi_I",
    }


def _bagli_kapatmalari_yukle(session, cari_id: int, referans: date) -> list:
    """Doğrulanmış belge bağlantıları — FIFO otomatik tahsisten önce uygulanır.

    MANUEL kullanıcı eşleştirmesi ile belge/iade/mahsup etiketli kayıtlar korunur.
    Yöntem=FIFO olan otomatik tahsisler yeniden hesaplanır (defter tutarlarıyla).
    """
    from datetime import datetime

    from database.acik_kalem_service import AcikKalemService
    from database.models.cari import CariKapatma
    from sqlalchemy import or_

    if not AcikKalemService._tablo_var(session):
        return []
    sinir = datetime.combine(referans, datetime.max.time())
    return list(
        session.scalars(
            select(CariKapatma)
            .where(
                CariKapatma.cari_id == int(cari_id),
                CariKapatma.tarih <= referans,
                or_(
                    CariKapatma.yontem == "MANUEL",
                    CariKapatma.yontem.in_(("BELGE", "IADE", "MAHSUP", "BAGLI", "VIRMAN")),
                ),
                or_(CariKapatma.iptal.is_(False), CariKapatma.iptal_zamani > sinir),
            )
            .order_by(CariKapatma.tarih, CariKapatma.id)
        ).all()
    )


def fifo_valor_paketi_oturumdan(
    session,
    cari_id: int,
    *,
    cari_turu: str | None = None,
    referans: date | None = None,
    sadece_acik: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Oturumdan FIFO valör paketi: tarihsel kesim + MANUEL istisna + serbest FIFO.

    Hesap tarihinden sonraki fatura/ödeme/kapatma dahil edilmez.
    P = ödemenin mali işlem tarihi (kapatma kayıt zamanı değil).
    """
    from types import SimpleNamespace

    from database.cari_service import CariService

    bugun = referans or date.today()
    hareketler = list(
        session.scalars(
            select(SatisHareketi).where(
                SatisHareketi.cari_id == int(cari_id),
                SatisHareketi.satis_tarihi <= bugun,
            )
        ).all()
    )
    islemler = list(
        session.scalars(
            select(CariIslem).where(
                CariIslem.cari_id == int(cari_id),
                CariIslem.tarih <= bugun,
            )
        ).all()
    )
    from database.cari_bakiye_service import (
        _defterde_kapanan_toplamlari,
        _onaysiz_veya_kesim_sonrasi_onayli_belgeler,
        _satis_hareketi_borc_alacak,
    )

    onaysiz_haric = _onaysiz_veya_kesim_sonrasi_onayli_belgeler(
        session,
        {(h.belge_no or "").strip() for h in hareketler},
        as_of=bugun,
    )
    hareketler = [h for h in hareketler if (h.belge_no or "").strip() not in onaysiz_haric]
    # Defterle aynı «sessiz» alacak: peşin/POS fatura kapaması CariIslem yazmaz
    # (RAY-00026 borç+alacak aynı satır). Valör ödemesine sentetik tahsilat eklenir.
    islem_belge_set = {(i.belge_no or "").strip() for i in islemler if (i.belge_no or "").strip()}
    sh_sessiz_aday = [
        h
        for h in hareketler
        if (h.belge_no or "").strip()
        and (h.belge_no or "").strip() not in islem_belge_set
        and not (h.belge_no or "").startswith(CariService._VALOR_BORC_HARIC_ONEK)
    ]
    defterde_kap = _defterde_kapanan_toplamlari(
        session,
        [int(h.id) for h in sh_sessiz_aday if getattr(h, "id", None)],
        islem_belge_set,
    )
    sessiz_islemler: list = []
    for h in sh_sessiz_aday:
        _borc, alacak_ek = _satis_hareketi_borc_alacak(
            h.satis_tutari,
            getattr(h, "kalan_acik_tutar", None),
            defterde_kapanan=defterde_kap.get(int(h.id), ZERO),
        )
        alacak_ek = _kurus(alacak_ek)
        if alacak_ek <= 0:
            continue
        sessiz_islemler.append(
            SimpleNamespace(
                id=-(int(h.id) or 0),  # sentetik; CI id ile çakışmasın
                belge_no=h.belge_no,
                tarih=h.satis_tarihi,
                islem_turu="Tahsilat",
                alacak=alacak_ek,
                borc=ZERO,
            )
        )
    if sessiz_islemler:
        islemler = list(islemler) + sessiz_islemler
    vade_harita = CariService._borc_vade_haritasi(
        session, [h.belge_no for h in hareketler]
    )
    ekstra = [
        (i.belge_no or "").strip()
        for i in islemler
        if _kurus(getattr(i, "borc", None)) > 0
    ]
    if ekstra:
        vade_harita = {**vade_harita, **CariService._borc_vade_haritasi(session, ekstra)}

    tedarikci = (cari_turu or "").casefold().startswith("tedarik")
    # SH borç her zaman hedef; CI borç yalnız SH'de olmayan belgelerde (hesapla içinde).
    hedef_kalan: dict[int, Decimal] = {}
    for h in hareketler:
        raw = _kurus(h.satis_tutari)
        if tedarikci:
            if raw >= 0:
                continue
            hedef_kalan[int(h.id)] = -raw
        else:
            if raw <= 0:
                continue
            no = (h.belge_no or "").strip()
            if no.startswith(CariService._VALOR_BORC_HARIC_ONEK):
                continue
            hedef_kalan[int(h.id)] = raw
    hedefler = {int(h.id): h for h in hareketler if int(h.id) in hedef_kalan}
    kaynak_kalan = {
        int(i.id): _kurus(CariService._odeme_borc_dusurur_mu(i, tedarikci))
        for i in islemler
    }
    kaynak_idleri: dict[str, list[int]] = {}
    for i in islemler:
        kaynak_idleri.setdefault(i.belge_no or "", []).append(int(i.id))
    islem_harita = {int(i.id): i for i in islemler}

    bagli: list[dict[str, Any]] = []
    for k in _bagli_kapatmalari_yukle(session, cari_id, bugun):
        hid = int(k.hedef_hareket_id)
        tutar = _kurus(k.tutar)
        kaynak = next(
            (j for j in kaynak_idleri.get(k.kaynak_belge_no or "", []) if kaynak_kalan.get(j, ZERO) > 0),
            None,
        )
        if hid not in hedef_kalan or kaynak is None:
            continue
        tutar = min(tutar, hedef_kalan[hid], kaynak_kalan[kaynak])
        if tutar <= 0:
            continue
        hedef_kalan[hid] = _kurus(hedef_kalan[hid] - tutar)
        kaynak_kalan[kaynak] = _kurus(kaynak_kalan[kaynak] - tutar)
        h = hedefler[hid]
        odeme = islem_harita[kaynak]
        vade = vade_harita.get(h.belge_no or "")
        p = odeme.tarih  # mali ödeme tarihi; kapatma.tarih değil
        i_tar = h.satis_tarihi
        esas, vade_kaynak, ozgun_eksik = _esas_vade_ve_kaynak(vade, i_tar)
        # Kart kapanan valör = P − I; P<I → 0 (vade farkı P−V negatif kalabilir)
        kapanan_gun = max(0, (p - i_tar).days) if p and i_tar else None
        vade_farki = (p - esas).days if esas and p else None
        if not sadece_acik:
            yontem = (k.yontem or "BAGLI").upper()
            bagli.append(
                {
                    "odeme_belge_no": odeme.belge_no,
                    "odeme_tarihi": p,
                    "borc_belge_no": h.belge_no or "",
                    "borc_tarihi": i_tar,
                    "borc_vadesi": vade,
                    "esas_vade": esas,
                    "vade_kaynak": vade_kaynak,
                    "vade_eksik": bool(ozgun_eksik),
                    "tutar": tutar,
                    "gun": kapanan_gun,
                    "kapanan_valor_gun": kapanan_gun,
                    "vade_farki_gun": vade_farki,
                    "odeme_suresi_gun": kapanan_gun,
                    "yon": "BORC",
                    "yontem": yontem,
                    "kapanis_turu": yontem,
                }
            )

    kopya_h = []
    for h in hareketler:
        hid = int(h.id)
        if hid not in hedef_kalan:
            continue
        kalan = hedef_kalan[hid]
        # fifo_valor_paketi_hesapla tedarikçide negatif tutar bekler
        tutar_yaz = (-kalan) if tedarikci else kalan
        kopya_h.append(
            SimpleNamespace(
                id=h.id,
                belge_no=h.belge_no,
                satis_tarihi=h.satis_tarihi,
                satis_tutari=tutar_yaz,
                kalan_acik_tutar=tutar_yaz,
            )
        )
    # Tedarikçi kuyruğuna yalnız negatif alış SH girer; pozitif DEVIREN SH aynı
    # belge_no ile CI alacağını engellemesin.
    hareket_belgeleri = {(h.belge_no or "") for h in hareketler}
    tedarikci_kuyruk_belgeleri = {
        (h.belge_no or "").strip()
        for h in hareketler
        if tedarikci and _kurus(h.satis_tutari) < 0 and (h.belge_no or "").strip()
    }
    kopya_i = []
    for i in islemler:
        odeme_kalan = kaynak_kalan.get(int(i.id), ZERO)
        orj_borc = _kurus(getattr(i, "borc", None))
        orj_alacak = _kurus(getattr(i, "alacak", None))
        no = (i.belge_no or "").strip()
        borc_tutar = ZERO
        alacak_tutar = ZERO
        if tedarikci:
            # Ödeme / açılış BORÇ: kapama tutarı; DEVIREN vb. açılış alacağı kuyruğa
            if odeme_kalan > 0 and (
                (i.islem_turu or "") in ("Ödeme", "Virman Ödeme", "KK Çekimi")
                or CariService._tedarikci_acilis_borc_mu(i)
                or (getattr(i, "islem_turu", None) or "").casefold().startswith("iade")
            ):
                borc_tutar = odeme_kalan
            elif orj_alacak > 0 and no and no not in tedarikci_kuyruk_belgeleri:
                alacak_tutar = orj_alacak
        else:
            alacak_tutar = odeme_kalan
            # Devir vb. yalnız CariIslem'de olan borçlar korunur
            if orj_borc > 0 and odeme_kalan <= 0 and no and no not in hareket_belgeleri:
                borc_tutar = orj_borc
        kopya_i.append(
            SimpleNamespace(
                id=i.id,
                belge_no=i.belge_no,
                tarih=i.tarih,
                islem_turu=i.islem_turu,
                alacak=alacak_tutar,
                borc=borc_tutar,
            )
        )
    tam, acik, dilimler, alacak = fifo_valor_paketi_hesapla(
        kopya_h,
        kopya_i,
        cari_turu=cari_turu,
        vade_harita=vade_harita,
        referans=bugun,
        sadece_acik=sadece_acik,
    )
    return tam, acik, bagli + dilimler, alacak


def calculate_account_average_value_date(
    cari_id: int,
    *,
    rapor_tarihi: date | None = None,
    firma_scoped: bool = True,
    session=None,
    cari_turu: str | None = None,
    bakiye: Decimal | None = None,
    fifo_paketi: tuple | None = None,
) -> dict[str, Any]:
    """Tek cari için çift yönlü ortalama açık valör (T−V) ve yaş (T−I)."""
    from database.cari_bakiye_service import net_bakiye

    _ = firma_scoped
    referans = rapor_tarihi or date.today()
    kendi_session = session is None

    def _calistir(sess) -> dict[str, Any]:
        nonlocal cari_turu, bakiye, fifo_paketi
        cari = sess.get(Cari, int(cari_id))
        if cari is None:
            return _bos_sonuc(ZERO, sebep="Cari bulunamadı")
        if cari_turu is None:
            cari_turu = cari.cari_turu

        if bakiye is None:
            nb = net_bakiye(
                int(cari_id),
                session=sess,
                as_of_datetime=referans,
                strict_before=False,
            )
            bakiye_l = _kurus(nb["bakiye"])
        else:
            bakiye_l = _kurus(bakiye)

        if fifo_paketi is None:
            fifo_paketi = fifo_valor_paketi_oturumdan(
                sess,
                int(cari_id),
                cari_turu=cari_turu,
                referans=referans,
            )
        if len(fifo_paketi) >= 4:
            _tam, acik_borc, _dilimler, acik_alacak = (
                fifo_paketi[0],
                fifo_paketi[1],
                fifo_paketi[2],
                fifo_paketi[3],
            )
        else:
            _tam, acik_borc, _dilimler = fifo_paketi[0], fifo_paketi[1], fifo_paketi[2]
            acik_alacak = []

        return _sonuc_olustur(bakiye_l, acik_borc, acik_alacak, referans)

    if kendi_session:
        with get_session() as sess:
            return _calistir(sess)
    return _calistir(session)


def calculate_accounts_average_value_date_bulk(
    cariler: list[Cari],
    session,
    *,
    rapor_tarihi: date | None = None,
    hareket_by: dict[int, list[SatisHareketi]] | None = None,
    islem_by: dict[int, list[CariIslem]] | None = None,
    bakiyeler: dict[int, Decimal] | None = None,
) -> dict[int, dict[str, Any]]:
    """Liste için toplu ortalama açık valör (MANUEL + FIFO ortak motor)."""
    from database.cari_bakiye_service import net_bakiye

    _ = (hareket_by, islem_by)  # geriye dönük imza; oturumdan tam paket kullanır
    if not cariler:
        return {}
    referans = rapor_tarihi or date.today()

    sonuclar: dict[int, dict[str, Any]] = {}
    for cari in cariler:
        cid = int(cari.id)
        if bakiyeler is not None and cid in bakiyeler:
            bakiye = _kurus(bakiyeler[cid])
        else:
            bakiye = _kurus(net_bakiye(cid, session=session)["bakiye"])
        if bakiye == 0:
            sonuclar[cid] = _bos_sonuc(bakiye, sebep="Bakiye kapalı")
            continue
        paket = fifo_valor_paketi_oturumdan(
            session,
            cid,
            cari_turu=cari.cari_turu,
            referans=referans,
            sadece_acik=True,
        )
        sonuclar[cid] = _sonuc_olustur(bakiye, paket[1], paket[3], referans)
    return sonuclar
