"""Personel modülü sürümlü şema + belge/mevzuat tohumları."""

from __future__ import annotations

import json
import weakref
from datetime import date

from sqlalchemy import select

_HAZIR_MOTORLAR: "weakref.WeakSet" = weakref.WeakSet()

# Kaynaklar talimat §10 — kontrol tarihi 9 Ekim 2026
_KONTROL = date(2026, 10, 9)

_KATEGORI_TOHUM = (
    ("KIMLIK_CALISMA", "Kimlik ve çalışma ilişkisi", 10, "NORMAL"),
    ("SGK_BEYAN", "SGK ve beyan", 20, "NORMAL"),
    ("UCRET_ODEME", "Ücret ve ödeme", 30, "NORMAL"),
    ("IZIN_PUANTAJ", "İzin ve puantaj", 40, "NORMAL"),
    ("SAGLIK_ISG", "Sağlık ve İSG", 50, "HASSAS_SAGLIK"),
    ("ADLI_SICIL", "Adli sicil kaydı", 60, "HASSAS_ADLI"),
    ("GOREV_BAGLI", "Göreve bağlı belgeler", 70, "NORMAL"),
    ("ISYERI_BELGE", "İşyeri belgeleri", 80, "NORMAL"),
    ("AYRILIS", "Ayrılış ve diğer evraklar", 90, "NORMAL"),
)

# (kod, kategori_kod, ad, sınıf, koşul, dayanak, gizlilik, kritik, saklama_baş, saklama_yıl, saklama_dayanak)
_TUR_TOHUM = (
    (
        "SOZLESME", "KIMLIK_CALISMA", "İş sözleşmesi / çalışma koşulu belgesi",
        "ZORUNLU", None, "4857 md.75 [1]", "NORMAL", True,
        "ISE_GIRIS", 10, "İş ilişkisi belgeleri — kurum politikası",
    ),
    (
        "KIMLIK_FOTOKOPI", "KIMLIK_CALISMA", "Kimlik fotokopisi",
        "KOSULLU", "Kurum politikası veya görev gereği talep edildiğinde",
        "Kurum politikası — her durumda zorunlu sayılmaz", "NORMAL", False,
        "ISE_GIRIS", 10, None,
    ),
    (
        "GOREV_TANIMI", "KIMLIK_CALISMA", "Görev tanımı",
        "ISTEGE_BAGLI", None, None, "NORMAL", False, "ISE_GIRIS", 5, None,
    ),
    (
        "SGK_GIRIS", "SGK_BEYAN", "İşe giriş bildirgesi ve resmî onay",
        "ZORUNLU", None, "SGK işveren yükümlülükleri [2]", "NORMAL", True,
        "ISE_GIRIS", 10, None,
    ),
    (
        "SGK_CIKIS", "SGK_BEYAN", "İşten ayrılış bildirgesi ve resmî onay",
        "KOSULLU", "Personel ayrıldığında", "SGK işveren yükümlülükleri [2]", "NORMAL", False,
        "AYRILIS", 10, None,
    ),
    (
        "UCRET_PUSULASI", "UCRET_ODEME", "Ücret hesap pusulası / onaylı bordro",
        "ISTEGE_BAGLI", None, None, "NORMAL", False, "DUZENLEME", 5, None,
    ),
    (
        "IZIN_BELGESI", "IZIN_PUANTAJ", "İzin talep / kayıt belgesi",
        "ISTEGE_BAGLI", None, "İş Kanunu izin soruları [5]", "NORMAL", False,
        "DUZENLEME", 5, None,
    ),
    (
        "SAGLIK_UYGUNLUK", "SAGLIK_ISG", "İşe giriş / periyodik sağlık uygunluğu",
        "KOSULLU", "İşyeri ve görev için sağlık gözetimi gerekiyorsa",
        "6331 md.15 / ÇSGB İSG SSS [1]", "HASSAS_SAGLIK", True,
        "AYRILIS", 15, "Kişisel sağlık dosyası — ayrılıştan en az 15 yıl [1]",
    ),
    (
        "ISTIRAHAT", "SAGLIK_ISG", "İstirahat raporu",
        "KOSULLU", "İstirahat alındığında", "Yetkili hekim belgesi [1]", "HASSAS_SAGLIK", False,
        "DUZENLEME", 15, "Kişisel sağlık dosyası [1]",
    ),
    (
        "ADLI_SICIL", "ADLI_SICIL", "Adli sicil kaydı",
        "KOSULLU", "Göreve ilişkin somut gereklilik ve hukuki dayanak tanımlandığında",
        "KVKK özel nitelikli veri [3] — her çalışana otomatik zorunlu değildir",
        "HASSAS_ADLI", False, "ISE_GIRIS", 2, None,
    ),
    (
        "KVKK_AYDINLATMA", "ISYERI_BELGE", "KVKK aydınlatma kaydı",
        "ZORUNLU", None, "KVKK aydınlatma yükümlülüğü [3]", "NORMAL", True,
        "ISE_GIRIS", 10, None,
    ),
    (
        "KVKK_ACIK_RIZA", "ISYERI_BELGE", "Açık rıza belgesi",
        "KOSULLU", "İşleme şartı rızaya dayandığında (her işlem için zorunlu değil)",
        "KVKK [3] — aydınlatmadan ayrı tür", "NORMAL", False,
        "ISE_GIRIS", 10, None,
    ),
    (
        "ZIMMET", "ISYERI_BELGE", "Zimmet / ekipman teslim tutanağı",
        "ISTEGE_BAGLI", None, None, "NORMAL", False, "DUZENLEME", 5, None,
    ),
    (
        "CALISMA_BELGESI", "AYRILIS", "Çalışma belgesi",
        "KOSULLU", "Personel ayrıldığında", "4857", "NORMAL", False,
        "AYRILIS", 10, None,
    ),
)

_MEVZUAT_TOHUM = (
    (
        "SGK_4A_ISE_GIRIS",
        "2026-10-09",
        "4/a özel sektör",
        {"gun_oncesi": 1, "aciklama": "İşe başlamadan en az bir gün önce"},
        "SGK İşverenin Yükümlülükleri [2]",
        date(2024, 1, 1),
    ),
    (
        "SGK_4A_AYRILIS",
        "2026-10-09",
        "4/a özel sektör",
        {"gun_sonra": 10, "aciklama": "Ayrılış bildirimi izleyen 10 gün"},
        "SGK İşverenin Yükümlülükleri [2]",
        date(2024, 1, 1),
    ),
    (
        "SGK_4A_MPHB",
        "2026-10-09",
        "4/a özel sektör normal aylık",
        {"takip_ay_gun": 26, "aciklama": "Takip eden ayın 26'sına kadar"},
        "SGK İşverenin Yükümlülükleri [2] / GİB MPHB [4]",
        date(2024, 1, 1),
    ),
    (
        "SGK_4A_PRIM_ODEME",
        "2026-10-09",
        "4/a özel sektör standart",
        {"takip_ay_sonu": True, "aciklama": "Takip eden ay sonu; vergi takvimi ayrı"},
        "SGK İşverenin Yükümlülükleri [2]",
        date(2024, 1, 1),
    ),
    (
        "YILLIK_IZIN_ASGARI",
        "2026-10-09",
        "genel",
        {
            "hizmet_yil_esikleri": [
                {"max_yil": 5, "gun": 14},
                {"max_yil": 15, "gun": 20},
                {"max_yil": None, "gun": 26},
            ],
            "yas_18_alti_veya_50_ustu_min": 20,
            "min_hizmet_yil": 1,
            "kaynak_not": "Hafta tatili ve genel tatil hesabı ayrıca yapılır",
        },
        "ÇSGB Çalışma GM İş Kanunu soruları 138-142 [5]",
        date(2024, 1, 1),
    ),
)


def schema_hazirla(motor=None) -> None:
    import database.database as veritabani

    motor = motor or veritabani.engine
    if motor is None or motor in _HAZIR_MOTORLAR:
        return
    from database.modul_sema import surum_uygula
    from database.models import personel as m

    tablolar = [
        m.Personel.__table__,
        m.PersonelCalismaDonemi.__table__,
        m.PersonelUcret.__table__,
        m.PersonelFotograf.__table__,
        m.PersonelBelgeKategori.__table__,
        m.PersonelBelgeTuru.__table__,
        m.PersonelBelge.__table__,
        m.PersonelBelgeSurumu.__table__,
        m.PersonelHakedis.__table__,
        m.PersonelHesapHareketi.__table__,
        m.PersonelPuantaj.__table__,
        m.PersonelIzin.__table__,
        m.PersonelIzinHakedis.__table__,
        m.PersonelSgkIslem.__table__,
        m.PersonelSgkBaglanti.__table__,
        m.PersonelMevzuatParametre.__table__,
        m.PersonelErisimLog.__table__,
        m.PersonelGecmis.__table__,
    ]

    def _v1(e) -> None:
        for t in tablolar:
            t.create(e, checkfirst=True)
        _tohum_doldur(e)

    surum_uygula(motor, "personel", 1, _v1)
    _HAZIR_MOTORLAR.add(motor)


def _tohum_doldur(motor) -> None:
    from sqlalchemy.orm import sessionmaker

    from database.models.personel import (
        PersonelBelgeKategori,
        PersonelBelgeTuru,
        PersonelMevzuatParametre,
    )

    Session = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)
    with Session() as session:
        kat_id: dict[str, int] = {}
        for kod, ad, sira, giz in _KATEGORI_TOHUM:
            mevcut = session.scalar(
                select(PersonelBelgeKategori).where(PersonelBelgeKategori.kod == kod)
            )
            if mevcut is None:
                mevcut = PersonelBelgeKategori(kod=kod, ad=ad, sira=sira, gizlilik=giz)
                session.add(mevcut)
                session.flush()
            kat_id[kod] = int(mevcut.id)

        for (
            kod, kat, ad, sinif, kosul, dayanak, giz, kritik, sak_bas, sak_yil, sak_day
        ) in _TUR_TOHUM:
            mevcut = session.scalar(
                select(PersonelBelgeTuru).where(PersonelBelgeTuru.kod == kod)
            )
            if mevcut is None:
                session.add(
                    PersonelBelgeTuru(
                        kategori_id=kat_id[kat],
                        kod=kod,
                        ad=ad,
                        sinif=sinif,
                        uygulanma_kosulu=kosul,
                        hukuki_dayanak=dayanak,
                        gizlilik=giz,
                        kritik_ise_baslama=kritik,
                        saklama_baslangic=sak_bas,
                        saklama_sure_yil=sak_yil,
                        saklama_dayanak=sak_day,
                    )
                )

        for kod, surum, kapsam, deger, kaynak, yururluk in _MEVZUAT_TOHUM:
            mevcut = session.scalar(
                select(PersonelMevzuatParametre).where(
                    PersonelMevzuatParametre.kod == kod,
                    PersonelMevzuatParametre.surum == surum,
                )
            )
            if mevcut is None:
                session.add(
                    PersonelMevzuatParametre(
                        kod=kod,
                        surum=surum,
                        kapsam=kapsam,
                        deger_json=json.dumps(deger, ensure_ascii=False),
                        resmi_kaynak=kaynak,
                        kontrol_tarihi=_KONTROL,
                        onaylayan="sistem_tohum",
                        yururluk_baslangic=yururluk,
                        aktif=True,
                    )
                )
        session.commit()
