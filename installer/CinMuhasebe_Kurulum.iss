; Cin Muhasebe - kurulum / guncelleme paketi (yonetici yetkisi gerekmez)
; Derleme: powershell -NoProfile -ExecutionPolicy Bypass -File installer\build_kurulum.ps1 -DistDir <dist\CinMuhasebe>
; Surum tek kaynaktan gelir: branding.py -> APP_VERSION.
;
; Program dosyalari (yeni kurulum): {localappdata}\Programs\Cin Muhasebe
; Mevcut DNM_D2 / kisayol hedefi bulundugunda: ayni klasore GUNCELLEME yapilir.
; - baglanti_ayari.json, kullanici ayarlari, DB ve PostgreSQL baglantisi korunur.
; - Guncellemede "bos firma" / "yedekten yukle" adimlari gosterilmez.
; - Program dosyalari once yedeklenir; basarisizlikta geri yuklenir.
; - Masaustu kisayolu guncellenir.

#ifndef AppVersion
  #error AppVersion tanimli degil. installer\build_kurulum.ps1 ile derleyin.
#endif
#ifndef DistDir
  #error DistDir tanimli degil.
#endif
#ifndef BuildDate
  #error BuildDate tanimli degil.
#endif

#define AppName "Cin Muhasebe"
#define AppExe "CinMuhasebe.exe"

[Setup]
AppId={{4E7A9C21-6B3D-4F58-A1E2-9D0C7B5F3A64}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Cin Muhasebe
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Cin Muhasebe
DefaultGroupName={param:GRUP|{#AppName}}
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
PrivilegesRequired=lowest
OutputBaseFilename=CinMuhasebe_Setup_{#AppVersion}_{#BuildDate}
SetupIconFile=..\assets\branding\CinLogo.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
RestartApplications=no
SetupLogging=yes
InfoBeforeFile=KURULUM_VE_ILK_GIRIS.txt

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; baglanti / kimlik / yerel DB paket kaynaklarinda yok; mevcut hedeftekiler ezilmez
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.db,*.db-wal,*.db-shm,veri_konumu.txt,VERITABANI_KONUMU.txt,test_kurulumu.txt,ILK_YONETICI_SIFRE.txt,baglanti_ayari.json,kullanici_ayarlari.json,ayarlar.json,credentials.json,evo_credentials.json,evobulut_credentials.json,\_internal\data\*"
Source: "KURULUM_VE_ILK_GIRIS.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\veri_paketle.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\ilk_kurulum_veri_yukle.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{group}\Veri Paketinden Yükle (ilk kurulum)"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\ilk_kurulum_veri_yukle.ps1"" -HedefKlasor ""{code:VeriKlasoru}"""; WorkingDir: "{app}"; Check: IlkKurulumIkonlari
Name: "{group}\Veri Paketi Oluştur (yedek)"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -NoExit -File ""{app}\scripts\veri_paketle.ps1"" -Kaynak ""{code:VeriKlasoru}"""; WorkingDir: "{app}"
Name: "{group}\Kurulum ve ilk giriş"; Filename: "{app}\KURULUM_VE_ILK_GIRIS.txt"
Name: "{group}\{#AppName} Kaldır"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\{#AppExe}"; Check: MasaustuKisayoluYazilsin

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent; Check: CalistirilabilirMi

[Code]
var
  VeriSayfasi: TInputOptionWizardPage;
  PaketSayfasi: TInputFileWizardPage;
  GuncellemeSayfasi: TInputOptionWizardPage;
  VeriVardi: Boolean;
  VeriYuklemeBasarisiz: Boolean;
  GuncellemeModu: Boolean;
  MevcutKurulumDir: String;
  MevcutKurulumKaynak: String;
  ProgramYedekDir: String;
  BaglantiYedekDosya: String;

function ProgramAcik(): Boolean;
var
  Bulucu, Servis, Liste: Variant;
begin
  Result := False;
  try
    Bulucu := CreateOleObject('WbemScripting.SWbemLocator');
    Servis := Bulucu.ConnectServer('.', 'root\CIMV2');
    Liste := Servis.ExecQuery('SELECT ProcessId FROM Win32_Process WHERE Name = ''CinMuhasebe.exe''');
    Result := Liste.Count > 0;
  except
    Log('WMI ile acik program denetimi yapilamadi: ' + GetExceptionMessage);
  end;
end;

{ Yalniz hedef kurulum klasorundeki EXE kilitliyse engelle (baska klasordeki ornek acik kalabilir). }
function ProgramHedefteAcik(AppDir: String): Boolean;
var
  Bulucu, Servis, Liste: Variant;
  Hedef, LikeYol, Sorgu: String;
begin
  Result := False;
  Hedef := RemoveBackslashUnlessRoot(AppDir);
  if Hedef = '' then
  begin
    Result := ProgramAcik();
    exit;
  end;
  try
    LikeYol := Hedef;
    StringChangeEx(LikeYol, '\', '\\', True);
    LikeYol := LikeYol + '\\%';
    Sorgu := 'SELECT ProcessId FROM Win32_Process WHERE Name = ''CinMuhasebe.exe'' AND ExecutablePath LIKE ''' + LikeYol + '''';
    Bulucu := CreateOleObject('WbemScripting.SWbemLocator');
    Servis := Bulucu.ConnectServer('.', 'root\CIMV2');
    Liste := Servis.ExecQuery(Sorgu);
    Result := Liste.Count > 0;
    if Result then
      Log('Hedefte acik process var: ' + Hedef);
  except
    Log('Hedef kilit denetimi basarisiz, genel denetime dusuluyor: ' + GetExceptionMessage);
    Result := ProgramAcik();
  end;
end;

function DegiskenAc(S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '%LOCALAPPDATA%', GetEnv('LOCALAPPDATA'), True);
  StringChangeEx(Result, '%APPDATA%', GetEnv('APPDATA'), True);
  StringChangeEx(Result, '%USERPROFILE%', GetEnv('USERPROFILE'), True);
end;

function KonumDosyasindan(Dosya: String): String;
var
  Satirlar: TArrayOfString;
  I: Integer;
  S: String;
begin
  Result := '';
  if not LoadStringsFromFile(Dosya, Satirlar) then
    exit;
  for I := 0 to GetArrayLength(Satirlar) - 1 do
  begin
    S := Satirlar[I];
    if (Length(S) >= 3) and (Ord(S[1]) = $EF) and (Ord(S[2]) = $BB) and (Ord(S[3]) = $BF) then
      Delete(S, 1, 3);
    if (Length(S) >= 1) and (Ord(S[1]) = $FEFF) then
      Delete(S, 1, 1);
    S := Trim(S);
    if (S <> '') and (S[1] <> '#') then
    begin
      Result := DegiskenAc(S);
      exit;
    end;
  end;
end;

function ProgramKlasoru(): String;
begin
  try
    Result := ExpandConstant('{app}');
  except
    Result := WizardDirValue;
  end;
end;

function VeriKlasoru(Param: String): String;
begin
  Result := ExpandConstant('{param:VERIKLASORU|}');
  if Result = '' then
    Result := KonumDosyasindan(AddBackslash(ProgramKlasoru) + 'veri_konumu.txt');
  if Result = '' then
    Result := ExpandConstant('{localappdata}') + '\MuhasebeProgrami\data';
  Result := RemoveBackslashUnlessRoot(Result);
end;

function VeriVar(Klasor: String): Boolean;
begin
  Result := FileExists(Klasor + '\system.db') or FileExists(Klasor + '\muhasebe.db');
end;

function CalistirilabilirMi(): Boolean;
begin
  Result := not VeriYuklemeBasarisiz;
end;

function IlkKurulumIkonlari(): Boolean;
begin
  Result := not GuncellemeModu;
end;

function ExeKlasoruMu(Klasor: String): Boolean;
begin
  Result := (Klasor <> '') and FileExists(AddBackslash(Klasor) + '{#AppExe}');
end;

function KisayolHedefKlasoru(LnkYol: String): String;
var
  Shell, Lnk: Variant;
  Hedef: String;
begin
  Result := '';
  if not FileExists(LnkYol) then
    exit;
  try
    Shell := CreateOleObject('WScript.Shell');
    Lnk := Shell.CreateShortcut(LnkYol);
    Hedef := Trim(String(Lnk.TargetPath));
    if (Hedef <> '') and FileExists(Hedef) and
       (CompareText(ExtractFileName(Hedef), '{#AppExe}') = 0) then
      Result := RemoveBackslashUnlessRoot(ExtractFilePath(Hedef))
    else if (Hedef <> '') and
            (CompareText(ExtractFileExt(Hedef), '.bat') = 0) and
            (Trim(String(Lnk.WorkingDirectory)) <> '') and
            ExeKlasoruMu(Trim(String(Lnk.WorkingDirectory))) then
      Result := RemoveBackslashUnlessRoot(Trim(String(Lnk.WorkingDirectory)));
  except
    Log('Kisayol okunamadi: ' + LnkYol + ' — ' + GetExceptionMessage);
  end;
end;

function MasaustuKisayolundanBul(var Klasor: String; var Kaynak: String): Boolean;
var
  AdayLnk, Bulunan: String;
begin
  Result := False;
  Klasor := '';
  Kaynak := '';
  AdayLnk := ExpandConstant('{autodesktop}\{#AppName}.lnk');
  Bulunan := KisayolHedefKlasoru(AdayLnk);
  if ExeKlasoruMu(Bulunan) then
  begin
    Klasor := Bulunan;
    Kaynak := 'kisayol: ' + AdayLnk;
    Result := True;
    exit;
  end;
  AdayLnk := ExpandConstant('{userdesktop}\{#AppName}.lnk');
  Bulunan := KisayolHedefKlasoru(AdayLnk);
  if ExeKlasoruMu(Bulunan) then
  begin
    Klasor := Bulunan;
    Kaynak := 'kisayol: ' + AdayLnk;
    Result := True;
    exit;
  end;
  { DNM terminal / ana kisayol adlari }
  AdayLnk := ExpandConstant('{autodesktop}\CİN MUHASEBE — DNM D2 — TERMINAL.lnk');
  Bulunan := KisayolHedefKlasoru(AdayLnk);
  if ExeKlasoruMu(Bulunan) then
  begin
    Klasor := Bulunan;
    Kaynak := 'kisayol: ' + AdayLnk;
    Result := True;
    exit;
  end;
  AdayLnk := ExpandConstant('{autodesktop}\CİN MUHASEBE — DNM D2 — ANA.lnk');
  Bulunan := KisayolHedefKlasoru(AdayLnk);
  if ExeKlasoruMu(Bulunan) then
  begin
    Klasor := Bulunan;
    Kaynak := 'kisayol: ' + AdayLnk;
    Result := True;
  end;
end;

function MevcutKurulumTespit(var Klasor: String; var Kaynak: String): Boolean;
var
  Dnm, Prog, KisayolDir, KisayolKaynak: String;
begin
  Result := False;
  Klasor := '';
  Kaynak := '';
  Dnm := ExpandConstant('{localappdata}\CinMuhasebe\DNM_D2\CinMuhasebe');
  Prog := ExpandConstant('{localappdata}\Programs\Cin Muhasebe');

  { Oncelik: DNM_D2 (canli firma / AG kurulumlari) }
  if ExeKlasoruMu(Dnm) then
  begin
    Klasor := Dnm;
    Kaynak := 'klasor: DNM_D2';
    Result := True;
    exit;
  end;

  if MasaustuKisayolundanBul(KisayolDir, KisayolKaynak) then
  begin
    Klasor := KisayolDir;
    Kaynak := KisayolKaynak;
    Result := True;
    exit;
  end;

  if ExeKlasoruMu(Prog) then
  begin
    Klasor := Prog;
    Kaynak := 'klasor: Programs\Cin Muhasebe';
    Result := True;
  end;
end;

{ Program klasoru yedegi / geri yukleme (PowerShell Copy-Item; robocopy Exec tip sorunlarindan kacinir) }
function KlasorKopyala(Kaynak, Hedef: String): Boolean;
var
  Kod: Integer;
  Cmd: String;
begin
  Result := False;
  if not DirExists(Kaynak) then
  begin
    Log('KlasorKopyala: kaynak yok ' + Kaynak);
    exit;
  end;
  if not ForceDirectories(Hedef) then
  begin
    Log('KlasorKopyala: hedef olusturulamadi ' + Hedef);
    exit;
  end;
  Cmd := '-NoProfile -ExecutionPolicy Bypass -Command "Copy-Item -LiteralPath ''' +
    Kaynak + '\*'' -Destination ''' + Hedef + ''' -Recurse -Force -ErrorAction Stop"';
  try
    if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
        Cmd, '', SW_HIDE, ewWaitUntilTerminated, Kod) then
    begin
      Log('KlasorKopyala: powershell baslatilamadi');
      exit;
    end;
    Result := Kod = 0;
    Log('KlasorKopyala kod=' + IntToStr(Kod) + ' ' + Kaynak + ' -> ' + Hedef);
  except
    Log('KlasorKopyala hata: ' + GetExceptionMessage);
    Result := False;
  end;
end;

function ProgramDosyalariniYedekle(Kaynak: String; var Yedek: String): Boolean;
begin
  Yedek := ExpandConstant('{localappdata}') + '\CinMuhasebe\KURULUM_GERI_' +
    GetDateTimeString('yyyymmdd_hhnnss', '-', ':');
  Result := KlasorKopyala(Kaynak, Yedek);
  if Result then
  begin
    ProgramYedekDir := Yedek;
    Log('Program yedegi: ' + Yedek);
  end
  else
    Log('Program yedegi basarisiz: ' + Kaynak);
end;

function BaglantiyiKenaraAl(AppDir: String): Boolean;
var
  Kaynak: String;
begin
  Result := True;
  BaglantiYedekDosya := '';
  Kaynak := AddBackslash(AppDir) + 'baglanti_ayari.json';
  if not FileExists(Kaynak) then
    exit;
  BaglantiYedekDosya := ExpandConstant('{tmp}') + '\baglanti_ayari.kurulum_koruma.json';
  Result := CopyFile(Kaynak, BaglantiYedekDosya, False);
  if Result then
    Log('baglanti_ayari kenara alindi')
  else
    Log('baglanti_ayari kenara alinamadi');
end;

procedure BaglantiyiGeriYaz(AppDir: String);
begin
  if (BaglantiYedekDosya <> '') and FileExists(BaglantiYedekDosya) then
  begin
    if CopyFile(BaglantiYedekDosya, AddBackslash(AppDir) + 'baglanti_ayari.json', False) then
      Log('baglanti_ayari geri yazildi')
    else
      Log('baglanti_ayari geri yazilamadi');
  end;
end;

function ProgramDosyalariniGeriYukle(AppDir, Yedek: String): Boolean;
begin
  Result := False;
  if (Yedek = '') or not DirExists(Yedek) then
    exit;
  Result := KlasorKopyala(Yedek, AppDir);
  if Result then
    Log('Program geri yuklendi: ' + Yedek)
  else
    Log('Program geri yuklenemedi: ' + Yedek);
end;

function MasaustuKisayoluYazilsin(): Boolean;
begin
  Result := WizardIsTaskSelected('desktopicon') or
    FileExists(ExpandConstant('{autodesktop}\{#AppName}.lnk')) or
    FileExists(ExpandConstant('{userdesktop}\{#AppName}.lnk')) or
    GuncellemeModu;
end;

procedure KisayolYaz(Yol, Exe, Calisma: String);
var
  Shell, Lnk: Variant;
begin
  try
    Shell := CreateOleObject('WScript.Shell');
    Lnk := Shell.CreateShortcut(Yol);
    Lnk.TargetPath := Exe;
    Lnk.WorkingDirectory := Calisma;
    Lnk.Arguments := '';
    Lnk.IconLocation := Exe + ',0';
    Lnk.Description := '{#AppName} {#AppVersion}';
    Lnk.Save;
    Log('Kisayol guncellendi: ' + Yol);
  except
    Log('Kisayol yazilamadi: ' + Yol + ' — ' + GetExceptionMessage);
  end;
end;

procedure MasaustuKisayollariniGuncelle();
var
  Exe, Calisma, Ad, Yol, AppDir: String;
  MevcutHedef: Boolean;
begin
  Exe := ExpandConstant('{app}\{#AppExe}');
  Calisma := ExpandConstant('{app}');
  AppDir := RemoveBackslashUnlessRoot(Calisma);
  MevcutHedef := (MevcutKurulumDir <> '') and
    (CompareText(AppDir, RemoveBackslashUnlessRoot(MevcutKurulumDir)) = 0);
  Ad := '{#AppName}.lnk';
  { Mevcut DNM/kurulum guncelleniyorsa veya yeni kurulumda masaustu gorevi secildiyse }
  Yol := ExpandConstant('{autodesktop}\') + Ad;
  if WizardIsTaskSelected('desktopicon') or (MevcutHedef and FileExists(Yol)) or
     ((not GuncellemeModu) and FileExists(Yol)) then
    KisayolYaz(Yol, Exe, Calisma);
  Yol := ExpandConstant('{userdesktop}\') + Ad;
  if (Yol <> ExpandConstant('{autodesktop}\') + Ad) and
     (WizardIsTaskSelected('desktopicon') or (MevcutHedef and FileExists(Yol)) or
      ((not GuncellemeModu) and FileExists(Yol))) then
    KisayolYaz(Yol, Exe, Calisma);
  Yol := ExpandConstant('{commondesktop}\') + Ad;
  if FileExists(Yol) and (MevcutHedef or (not GuncellemeModu) or WizardIsTaskSelected('desktopicon')) then
    KisayolYaz(Yol, Exe, Calisma);
  { DNM kisayollari — yalniz gercek DNM klasoru guncellenirken }
  if not MevcutHedef then
    exit;
  Yol := ExpandConstant('{autodesktop}\CİN MUHASEBE — DNM D2 — TERMINAL.lnk');
  if FileExists(Yol) then
    KisayolYaz(Yol, Exe, Calisma);
  Yol := ExpandConstant('{autodesktop}\CİN MUHASEBE — DNM D2 — ANA.lnk');
  if FileExists(Yol) then
    KisayolYaz(Yol, Exe, Calisma);
end;

{ /DIR= komut satirinda verildiyse sihirbaz bunu ezmesin (klon/test veya ozel hedef). }
function SetupDirParamVerildi(): Boolean;
var
  I: Integer;
  S: String;
begin
  Result := False;
  for I := 1 to ParamCount do
  begin
    S := ParamStr(I);
    if (CompareText(Copy(S, 1, 5), '/DIR=') = 0) or (CompareText(S, '/DIR') = 0) then
    begin
      Result := True;
      exit;
    end;
  end;
end;

procedure InitializeWizard();
var
  Paket, Ozet: String;
begin
  GuncellemeModu := False;
  MevcutKurulumDir := '';
  MevcutKurulumKaynak := '';
  ProgramYedekDir := '';
  BaglantiYedekDosya := '';

  if MevcutKurulumTespit(MevcutKurulumDir, MevcutKurulumKaynak) then
  begin
    GuncellemeModu := True;
    if not SetupDirParamVerildi() then
      WizardForm.DirEdit.Text := MevcutKurulumDir;
    Log('Mevcut kurulum: ' + MevcutKurulumDir + ' (' + MevcutKurulumKaynak + ')');
  end;

  Ozet := 'Bu bilgisayarda mevcut kurulum bulunamadı. Yeni kurulum yapılacak.';
  if GuncellemeModu then
    Ozet := 'Mevcut kurulum bulundu:' + #13#10 + MevcutKurulumDir + #13#10 +
      '(' + MevcutKurulumKaynak + ')' + #13#10#13#10 +
      'Önerilen: program dosyalarını güncelleyin. Firma verileri, baglanti_ayari.json ' +
      've PostgreSQL bağlantısı korunur. Boş firma / yedekten yükleme adımı atlanır.';

  { InfoBefore'dan sonra, klasor seciminden once }
  GuncellemeSayfasi := CreateInputOptionPage(wpInfoBefore, 'Kurulum türü',
    'Güncelleme veya yeni kurulum', Ozet, True, False);
  if GuncellemeModu then
  begin
    GuncellemeSayfasi.Add('Mevcut kurulumu güncelle (önerilen) — veriler ve bağlantı korunur');
    GuncellemeSayfasi.Add('Yeni klasöre kur (mevcut kuruluma dokunma)');
    GuncellemeSayfasi.SelectedValueIndex := 0;
  end
  else
  begin
    GuncellemeSayfasi.Add('Yeni kurulum');
    GuncellemeSayfasi.SelectedValueIndex := 0;
  end;

  Paket := ExpandConstant('{param:VERIPAKETI|}');
  VeriSayfasi := CreateInputOptionPage(GuncellemeSayfasi.ID, 'Firma verisi',
    'Program ilk açılışta hangi veriyle başlasın?',
    'Bu bilgisayarda Cin Muhasebe verisi bulunamadı. Birini seçin:', True, False);
  VeriSayfasi.Add('Boş firma ile başla (firma adı ve bilgileri programda girilir)');
  VeriSayfasi.Add('Veri paketinden (yedekten) yükle - "Veri Paketi Oluştur" ile alınmış .zip dosyası');
  if Paket <> '' then
    VeriSayfasi.SelectedValueIndex := 1
  else
    VeriSayfasi.SelectedValueIndex := 0;
  PaketSayfasi := CreateInputFilePage(VeriSayfasi.ID, 'Veri paketi', 'Yüklenecek veri paketini seçin',
    'Paket doğrulanır (MANIFEST / SHA256) ve yalnız boş veri klasörüne yüklenir.');
  PaketSayfasi.Add('Veri paketi (.zip):', 'Cin Muhasebe veri paketi (*.zip)|*.zip', '.zip');
  PaketSayfasi.Values[0] := Paket;
end;

function GuncelleSecildi(): Boolean;
begin
  Result := GuncellemeModu and (GuncellemeSayfasi.SelectedValueIndex = 0);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = GuncellemeSayfasi.ID then
    Result := False
  else if PageID = VeriSayfasi.ID then
    Result := GuncelleSecildi() or VeriVar(VeriKlasoru(''))
  else if PageID = PaketSayfasi.ID then
    Result := GuncelleSecildi() or VeriVar(VeriKlasoru('')) or (VeriSayfasi.SelectedValueIndex <> 1)
  else if PageID = wpSelectDir then
  begin
    { Guncellemede klasor sabit — kullanici "yeni klasore kur" demedikce atla }
    if GuncelleSecildi() then
    begin
      if not SetupDirParamVerildi() then
        WizardForm.DirEdit.Text := MevcutKurulumDir;
      Result := True;
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = GuncellemeSayfasi.ID then
  begin
    if GuncelleSecildi() then
    begin
      if not SetupDirParamVerildi() then
        WizardForm.DirEdit.Text := MevcutKurulumDir;
    end
    else if GuncellemeModu and (GuncellemeSayfasi.SelectedValueIndex = 1) then
      WizardForm.DirEdit.Text := ExpandConstant('{localappdata}\Programs\Cin Muhasebe');
  end;
  if (CurPageID = PaketSayfasi.ID) and not FileExists(PaketSayfasi.Values[0]) then
  begin
    MsgBox('Veri paketi bulunamadı. Lütfen .zip dosyasını seçin.', mbError, MB_OK);
    Result := False;
  end;
end;

function DosyalariKopyala(Kaynak, Hedef: String): Boolean;
var
  B: TFindRec;
begin
  Result := True;
  if FindFirst(Kaynak + '\*.db*', B) then
  try
    repeat
      if (B.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then
      begin
        if not ForceDirectories(Hedef) then
        begin
          Result := False;
          exit;
        end;
        if not CopyFile(Kaynak + '\' + B.Name, Hedef + '\' + B.Name, False) then
        begin
          Log('Yedeklenemedi: ' + Kaynak + '\' + B.Name);
          Result := False;
          exit;
        end;
      end;
    until not FindNext(B);
  finally
    FindClose(B);
  end;
end;

function GuncellemeYedegi(Veri: String; var Yol: String): Boolean;
begin
  Yol := Veri + '\yedekler\kurulum_oncesi_' + GetDateTimeString('yyyymmdd_hhnnss', '-', ':');
  Result := DosyalariKopyala(Veri, Yol) and DosyalariKopyala(Veri + '\companies', Yol + '\companies');
  if Result then
    Log('Guncelleme oncesi veri yedegi: ' + Yol);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Veri, Yol, AppDir: String;
begin
  Result := '';
  { /DIR verildiyse ona uy; yoksa guncellemede tespit edilen mevcut klasor }
  AppDir := WizardDirValue;
  if GuncelleSecildi() and not SetupDirParamVerildi() then
    AppDir := MevcutKurulumDir;
  Log('PrepareToInstall hedef: ' + AppDir + ' (guncelleme=' + IntToStr(Ord(GuncelleSecildi())) + ')');

  while ProgramHedefteAcik(AppDir) do
  begin
    if WizardSilent or (MsgBox('Güncellenecek kurulum klasöründeki Cin Muhasebe şu anda açık.' + #13#10 +
        AppDir + #13#10#13#10 +
        'Kayıtlarınızı tamamlayıp programı normal şekilde kapatın, sonra "Yeniden Dene"ye basın.' + #13#10 +
        'Program açıkken dosyalar değiştirilmez (zorla kapatılmaz).', mbError, MB_RETRYCANCEL) = IDCANCEL) then
    begin
      Result := 'Cin Muhasebe açık olduğu için kurulum yapılmadı. Programı kapatıp kurulumu yeniden çalıştırın.';
      exit;
    end;
  end;

  if ExeKlasoruMu(AppDir) then
  begin
    if not BaglantiyiKenaraAl(AppDir) then
    begin
      Result := 'baglanti_ayari.json korunamadı. Kurulum durduruldu.';
      exit;
    end;
    if not ProgramDosyalariniYedekle(AppDir, ProgramYedekDir) then
    begin
      Result := 'Mevcut program dosyaları yedeklenemedi (' + AppDir + '). Kurulum durduruldu.';
      exit;
    end;
  end;

  Veri := VeriKlasoru('');
  VeriVardi := VeriVar(Veri);
  if VeriVardi and not GuncelleSecildi() then
  begin
    if not GuncellemeYedegi(Veri, Yol) then
      Result := 'Mevcut veriler yedeklenemedi (' + Veri + '). Güvenlik için kurulum durduruldu; ' +
        'diskte yer olduğunu ve verinin başka bir program tarafından kullanılmadığını denetleyin.';
  end;
end;

procedure KonumDosyasiYaz();
var
  Klasor: String;
  Satirlar: TArrayOfString;
begin
  Klasor := ExpandConstant('{param:VERIKLASORU|}');
  if Klasor = '' then
    exit;
  SetArrayLength(Satirlar, 2);
  Satirlar[0] := '# Cin Muhasebe veri klasoru (kurulumda /VERIKLASORU ile verildi)';
  Satirlar[1] := Klasor;
  if not SaveStringsToUTF8File(ExpandConstant('{app}\veri_konumu.txt'), Satirlar, False) then
    Log('veri_konumu.txt yazilamadi');
end;

procedure VeriPaketiYukle();
var
  Paket, Veri, Parametre, Durum: String;
  Kod: Integer;
begin
  if GuncelleSecildi() then
    exit;
  if VeriVardi or (VeriSayfasi.SelectedValueIndex <> 1) then
    exit;
  Paket := PaketSayfasi.Values[0];
  Veri := VeriKlasoru('');
  Parametre := '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' +
    ExpandConstant('{app}\scripts\ilk_kurulum_veri_yukle.ps1') + '" -Paket "' + Paket +
    '" -HedefKlasor "' + Veri + '" -Sessiz';
  WizardForm.StatusLabel.Caption := 'Veri paketi doğrulanıyor ve yükleniyor...';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Parametre, '', SW_HIDE,
      ewWaitUntilTerminated, Kod) then
    Kod := -1;
  Durum := 'Veri paketi: ' + Paket + #13#10 + 'Hedef: ' + Veri + #13#10 + 'Sonuc kodu: ' + IntToStr(Kod);
  SaveStringToFile(ExpandConstant('{app}\kurulum_veri_yukleme.txt'), Durum + #13#10, False);
  Log(Durum);
  if Kod <> 0 then
  begin
    VeriYuklemeBasarisiz := True;
    SuppressibleMsgBox('Veri paketi yüklenemedi (kod ' + IntToStr(Kod) + ').' + #13#10#13#10 +
      'Ayrıntı: %TEMP% klasöründeki CinMuhasebe_VeriYukle_*.log dosyası.' + #13#10 +
      'Program kuruldu; mevcut veri değiştirilmedi. Programı açmadan önce Başlat menüsündeki ' +
      '"Veri Paketinden Yükle (ilk kurulum)" ile tekrar deneyin.', mbError, MB_OK, IDOK);
  end;
end;

procedure KurulumSonrasiDogrula();
var
  ExeYol, Durum: String;
  Satirlar: TArrayOfString;
begin
  ExeYol := ExpandConstant('{app}\{#AppExe}');
  if not FileExists(ExeYol) then
  begin
    Log('Kurulum sonrasi EXE yok — geri yukleme deneniyor');
    if (ProgramYedekDir <> '') and ProgramDosyalariniGeriYukle(ExpandConstant('{app}'), ProgramYedekDir) then
    begin
      BaglantiyiGeriYaz(ExpandConstant('{app}'));
      VeriYuklemeBasarisiz := True;
      SuppressibleMsgBox('Kurulum tamamlanamadı; önceki program dosyaları geri yüklendi.' + #13#10 +
        'Yedek: ' + ProgramYedekDir, mbError, MB_OK, IDOK);
    end;
    exit;
  end;
  BaglantiyiGeriYaz(ExpandConstant('{app}'));
  SetArrayLength(Satirlar, 5);
  Satirlar[0] := 'surum={#AppVersion}';
  Satirlar[1] := 'exe=' + ExeYol;
  Satirlar[2] := 'guncelleme=' + IntToStr(Ord(GuncelleSecildi()));
  Satirlar[3] := 'kaynak=' + MevcutKurulumKaynak;
  Satirlar[4] := 'zaman=' + GetDateTimeString('yyyy-mm-dd hh:nn:ss', '-', ':');
  SaveStringsToUTF8File(ExpandConstant('{app}\KURULUM_SONUC.txt'), Satirlar, False);
  Durum := 'Kurulum OK surum={#AppVersion} app=' + ExpandConstant('{app}');
  Log(Durum);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    KonumDosyasiYaz;
    VeriPaketiYukle;
    KurulumSonrasiDogrula;
    MasaustuKisayollariniGuncelle;
  end;
end;

var
  KaldirmaVeriKlasoru: String;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  KaldirmaVeriKlasoru := KonumDosyasindan(ExpandConstant('{app}\veri_konumu.txt'));
  if KaldirmaVeriKlasoru = '' then
    KaldirmaVeriKlasoru := ExpandConstant('{localappdata}') + '\MuhasebeProgrami\data';
  while ProgramAcik do
  begin
    if UninstallSilent or (MsgBox('Cin Muhasebe şu anda açık. Programı normal şekilde kapatıp "Yeniden Dene"ye basın.',
        mbError, MB_RETRYCANCEL) = IDCANCEL) then
    begin
      Result := False;
      exit;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    MsgBox('Program kaldırıldı. Firma verileriniz silinmedi:' + #13#10 + KaldirmaVeriKlasoru,
      mbInformation, MB_OK);
end;
