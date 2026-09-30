; Cin Muhasebe - yerel TEST kurulumu (yonetici yetkisi gerekmez)
; Derleme: powershell -NoProfile -ExecutionPolicy Bypass -File installer\build_installer.ps1
; Surum tek kaynaktan gelir: branding.py -> APP_VERSION (/DAppVersion=... ile verilir).
; Hicbir veritabani dosyasi pakete girmez ve kurulum/kaldirma veri klasorune dokunmaz.

#ifndef AppVersion
  #error AppVersion tanimli degil. installer\build_installer.ps1 ile derleyin.
#endif

#define AppName "Cin Muhasebe"
#define AppExe "CinMuhasebe.exe"
#ifndef DistDir
  #define DistDir "..\dist\CinMuhasebe"
#endif
#ifndef BuildTag
  #define BuildTag ""
#endif

[Setup]
AppId={{8C3B6D2E-5A41-4F0B-9E7C-2B1D4A6F9C10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion} (Test)
AppPublisher=Cin Muhasebe
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\CinMuhasebe
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\Output
OutputBaseFilename=CinMuhasebe_Test_Kurulum_{#AppVersion}{#BuildTag}
SetupIconFile=..\assets\branding\CinLogo.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.db,*.db-wal,*.db-shm,veri_konumu.txt,VERITABANI_KONUMU.txt"
Source: "..\scripts\veri_paketle.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\veri_geri_yukle.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
; Test kurulumu ayri veri klasoru kullanir; testcinin elle degistirdigi dosya guncellemede ezilmez
Source: "veri_konumu_test.txt"; DestDir: "{app}"; DestName: "veri_konumu.txt"; Flags: onlyifdoesntexist
; veri_konumu.txt silinse/bozulsa da test EXE'si gercek veri klasorune dusmesin
Source: "test_kurulumu.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName} (Test)"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{group}\Veri Paketini Geri Yukle"; Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -NoExit -File ""{app}\scripts\veri_geri_yukle.ps1"""; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName} (Test)"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

; Veri geri yukleme ASLA otomatik calismaz; yalnizca Baslat menusundeki ogeden elle.
[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent unchecked
