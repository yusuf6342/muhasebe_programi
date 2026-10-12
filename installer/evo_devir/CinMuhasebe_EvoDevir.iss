; Cin Muhasebe - Evo Devir Deneme kurulumu (yonetici yetkisi gerekmez)
; Derleme: powershell -NoProfile -ExecutionPolicy Bypass -File installer\evo_devir\build_evo_kurulum.ps1
; Cin Muhasebe (Test) kurulumundan ayri AppId, program klasoru, veri klasoru ve kisayol adi kullanir.
; Firma verisi yalnizca hedefte system.db yoksa kurulur; guncelleme/kaldirma veri klasorune dokunmaz.

#ifndef AppVersion
  #error AppVersion tanimli degil. build_evo_kurulum.ps1 ile derleyin.
#endif
#ifndef DistDir
  #error DistDir tanimli degil.
#endif
#ifndef VeriDir
  #error VeriDir tanimli degil.
#endif
#ifndef BuildTag
  #define BuildTag ""
#endif

#define AppName "Cin Muhasebe - Evo Devir Deneme"
#define AppExe "CinMuhasebe.exe"
#define VeriKlasoru "{localappdata}\CinMuhasebeEvoDevir\data"

[Setup]
AppId={{82FD01DB-8324-4504-9994-39241E4435F2}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Cin Muhasebe
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\CinMuhasebeEvoDevir
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
PrivilegesRequired=lowest
OutputBaseFilename=CinMuhasebe_EvoDevir_Kurulum_{#AppVersion}{#BuildTag}
SetupIconFile=..\..\assets\branding\CinLogo.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
InfoBeforeFile=KURULUM_VE_ILK_GIRIS.txt

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.db,*.db-wal,*.db-shm,veri_konumu.txt,VERITABANI_KONUMU.txt,test_kurulumu.txt"
Source: "veri_konumu.txt"; DestDir: "{app}"; Flags: ignoreversion
; veri_konumu.txt silinse bile EXE gercek veri klasorune (MuhasebeProgrami) dusmesin
Source: "..\test_kurulumu.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "KURULUM_VE_ILK_GIRIS.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\scripts\veri_paketle.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\..\scripts\veri_geri_yukle.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "{#VeriDir}\*"; DestDir: "{#VeriKlasoru}"; Flags: recursesubdirs createallsubdirs uninsneveruninstall; Check: VeriYok

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{group}\Kurulum ve ilk giris"; Filename: "{app}\KURULUM_VE_ILK_GIRIS.txt"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  VeriVardi: Boolean;

function InitializeSetup(): Boolean;
begin
  VeriVardi := FileExists(ExpandConstant('{#VeriKlasoru}\system.db'));
  Result := True;
end;

function VeriYok(): Boolean;
begin
  Result := not VeriVardi;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpReady) and VeriVardi then
    MsgBox('Veri klasorunde zaten bir Evo Devir verisi var:' + #13#10 +
           ExpandConstant('{#VeriKlasoru}') + #13#10#13#10 +
           'Mevcut veri korunacak; yalniz program dosyalari guncellenecek.', mbInformation, MB_OK);
end;
