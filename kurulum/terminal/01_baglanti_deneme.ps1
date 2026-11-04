# Cin Muhasebe — Terminal DENEME bağlantı kontrolü
# PostgreSQL sunucusu TERMINALE kurulmaz. Ana makine: DESKTOP-CGSE5GK
# IP örnek (DHCP değişebilir): 192.168.1.114 — kurulum anında doğrulayın.

param(
    [string]$AnaHost = "192.168.1.114",
    [int]$Port = 5432
)

Write-Host "Bu makine: $env:COMPUTERNAME (beklenen istemci örn. DESKTOP-FL08BVD)"
Write-Host "TCP sınaması: $AnaHost : $Port"
$t = Test-NetConnection -ComputerName $AnaHost -Port $Port -WarningAction SilentlyContinue
Write-Host "TcpTestSucceeded = $($t.TcpTestSucceeded)"
if (-not $t.TcpTestSucceeded) {
    Write-Host "TCP başarısız. Ana makinede PostgreSQL servisi, pg_hba, güvenlik duvarı ve güncel IP kontrol edin."
    exit 1
}
Write-Host "TCP OK — bu yalnız port erişimidir. Uygulamada Bağlantı Ayarları → Bağlantıyı Sına + firma oturumu ayrıca gerekir."
Write-Host "Kısayol: DENEME ortamı; GERÇEK kısayolunu değiştirmeyin."
exit 0
