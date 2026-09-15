# Cin Muhasebe - tek tikla kurulum (PowerShell)
# Kullanim (PowerShell penceresinde):
#   irm https://raw.githubusercontent.com/yusuf6342/muhasebe_programi/main/kurulum_masaustu.ps1 | iex
# veya:
#   powershell -NoProfile -ExecutionPolicy Bypass -File kurulum_masaustu.ps1

$ErrorActionPreference = 'Stop'

Write-Host ''
Write-Host ' Cin Muhasebe kuruluyor...'
Write-Host ' (GitHub''dan indirilecek, masaustune kisayol eklenecek)'
Write-Host ''

$dest = Join-Path $env:USERPROFILE 'CinMuhasebe'
$zip = Join-Path $env:TEMP 'muhasebe_programi.zip'
$url = 'https://github.com/yusuf6342/muhasebe_programi/archive/refs/heads/main.zip'

Write-Host 'Indiriliyor...'
Invoke-WebRequest -Uri $url -OutFile $zip

if (Test-Path $dest) {
    Remove-Item -Recurse -Force $dest
}
New-Item -ItemType Directory -Path $dest | Out-Null

Write-Host 'Aciliyor...'
Expand-Archive -Path $zip -DestinationPath $dest -Force
$inner = Get-ChildItem -Path $dest -Directory | Select-Object -First 1
Get-ChildItem -Path $inner.FullName | Move-Item -Destination $dest -Force
Remove-Item -Recurse -Force $inner.FullName
Remove-Item -Force $zip

$bat = Join-Path $dest 'calistir.bat'
if (-not (Test-Path $bat)) {
    throw 'calistir.bat bulunamadi'
}

$desktop = [Environment]::GetFolderPath('Desktop')
$lnkPath = Join-Path $desktop 'Cin Muhasebe.lnk'
$ico = Join-Path $dest 'assets\branding\cin_muhasebe.ico'
$w = New-Object -ComObject WScript.Shell
$s = $w.CreateShortcut($lnkPath)
$s.TargetPath = $bat
$s.WorkingDirectory = $dest
$s.WindowStyle = 1
$s.Description = 'Cin Muhasebe Programı'
if (Test-Path -LiteralPath $ico) {
    $s.IconLocation = "$ico,0"
}
$s.Save()

Write-Host ''
Write-Host ("Kurulum klasoru: " + $dest)
Write-Host ("Masaustu kisayol: " + $lnkPath)
Write-Host ''
Write-Host 'Masaustunde Cin Muhasebe kisayolunu goreceksiniz.'
Write-Host 'Bitti. Kisayola cift tiklayarak programi acabilirsiniz.'
explorer.exe $desktop
