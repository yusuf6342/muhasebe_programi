; Cin Muhasebe - kurulum paketi (diger bilgisayarlar icin; yonetici yetkisi gerekmez)
; Derleme: powershell -NoProfile -ExecutionPolicy Bypass -File installer\build_kurulum.ps1 -DistDir <dist\CinMuhasebe>
; Surum tek kaynaktan gelir: branding.py -> APP_VERSION.
;
; Program dosyalari : {localappdata}\Programs\Cin Muhasebe
; Firma verisi      : %LOCALAPPDATA%\MuhasebeProgrami\data (programin varsayilan veri klasoru)
; - Pakete hicbir veritabani, parola dosyasi veya veri konumu dosyasi girmez.
; - Guncelleme veri klasorundeki veritabanlarini once yedekler; kullanici, parola ve ayarlara dokunmaz.
;   Sema degisiklikleri programin ilk acilisinda dogrulanmis yedekle (guvenli gecis) yapilir.
; - Program acikken dosya degistirilmez; kullanicidan programi kapatmasi istenir.
; - Masaustundeki mevcut "Cin Muhasebe" kisayolu ayni adla yeni EXE'ye baglanir (ikinci kisayol olusmaz).
; - Kaldirma veri klasorune dokunmaz.
; - Yalniz test icin: /VERIKLASORU="C:\...\data" programi bu veri klasorune baglar (veri_konumu.txt),
;   /VERIPAKETI="C:\...\CinMuhasebe_Veri_....zip" ilk kurulumda veri paketini yukler,
;   /GRUP="..." Baslat menusu klasor adini degistirir.

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
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.db,*.db-wal,*.db-shm,veri_konumu.txt,VERITABANI_KONUMU.txt,test_kurulumu.txt,ILK_YONETICI_SIFRE.txt,\_internal\data\*"
Source: "KURULUM_VE_ILK_GIRIS.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\scripts\veri_paketle.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\ilk_kurulum_veri_yukle.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{group}\Veri Paketinden Yükle (ilk kurulum)"; Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\ilk_kurulum_veri_yukle.ps1"" -HedefKlasor ""{code:VeriKlasoru}"""; WorkingDir: "{app}"
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
  VeriVardi: Boolean;
  VeriYuklemeBasarisiz: Boolean;

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

{ Programin kullanacagi veri klasoru: /VERIKLASORU > mevcut veri_konumu.txt > varsayilan }
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

{ Masaustunde "Cin Muhasebe.lnk" varsa (eski bir surume bagli olsa da) secenekten bagimsiz ayni dosya
  yeni surume baglanir; boylece ikinci kisayol olusmaz ve eski kisayol eski EXE'yi acmaya devam etmez. }
function MasaustuKisayoluYazilsin(): Boolean;
begin
  Result := WizardIsTaskSelected('desktopicon') or
    FileExists(ExpandConstant('{autodesktop}\{#AppName}.lnk'));
end;

procedure InitializeWizard();
var
  Paket: String;
begin
  Paket := ExpandConstant('{param:VERIPAKETI|}');
  VeriSayfasi := CreateInputOptionPage(wpSelectTasks, 'Firma verisi',
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

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = VeriSayfasi.ID then
    Result := VeriVar(VeriKlasoru(''))
  else if PageID = PaketSayfasi.ID then
    Result := VeriVar(VeriKlasoru('')) or (VeriSayfasi.SelectedValueIndex <> 1);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
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
  Veri, Yol: String;
begin
  Result := '';
  while ProgramAcik do
  begin
    if WizardSilent or (MsgBox('Cin Muhasebe şu anda açık.' + #13#10#13#10 +
        'Kayıtlarınızı tamamlayıp programı normal şekilde kapatın, sonra "Yeniden Dene"ye basın.' + #13#10 +
        'Program açıkken dosyalar değiştirilmez.', mbError, MB_RETRYCANCEL) = IDCANCEL) then
    begin
      Result := 'Cin Muhasebe açık olduğu için kurulum yapılmadı. Programı kapatıp kurulumu yeniden çalıştırın.';
      exit;
    end;
  end;
  Veri := VeriKlasoru('');
  VeriVardi := VeriVar(Veri);
  if VeriVardi then
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

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    KonumDosyasiYaz;
    VeriPaketiYukle;
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
