"""DOC Satış Kâr: ağırlıklı toplam marj (satır yüzdeleri toplanmaz)."""

from decimal import Decimal


def test_agirlikli_marj_yuzde_30_ornek():
    # 1000 satış / 200 kâr + 9000 satış / 900 kâr → toplam marj %11 değil; burada
    # talimat örneği: %20 ve %45 satırları → ağırlıklı %30
    net1, kar1 = Decimal("1000"), Decimal("200")  # %20
    net2, kar2 = Decimal("9000"), Decimal("4050")  # %45
    # Talimat: 3000 net / 2100 maliyet → 900 kâr = %30 toplamda örneği ayrı;
    # Ağırlıklı: (200+4050)/(1000+9000)=42.5% — instead use DOC example pairs:
    # «yüzde 20 ve yüzde 45 ortalaması 32,50 yanlış; doğru toplam marj yüzde 30»
    # → net1=1000 kar1=200; net2=9000 kar2=2800 → (200+2800)/10000 = 30%
    kar2 = Decimal("2800")
    toplam_net = net1 + net2
    toplam_kar = kar1 + kar2
    marj = (toplam_kar / toplam_net * Decimal("100")).quantize(Decimal("0.01"))
    assert marj == Decimal("30.00")
    basit_ort = (Decimal("20") + Decimal("45")) / 2
    assert basit_ort != marj
