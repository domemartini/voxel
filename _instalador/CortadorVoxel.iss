#define AppName "Voxel Cut"
#define AppVersion "1.8.3"
#define Stage "stage"

[Setup]
#ifdef ASSINAR
SignTool=assinar
SignedUninstaller=yes
#endif
AppId={{B30B92A6-E6B7-4C7F-B6C2-E619D65513CA}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Voxel
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=saida
OutputBaseFilename=Instalar Voxel Cut {#AppVersion}
SetupIconFile={#Stage}\app\icone.ico
UninstallDisplayIcon={app}\app\icone.ico
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[InstallDelete]
Type: filesandordirs; Name: "{app}\app\engine"
Type: filesandordirs; Name: "{app}\app\viewer"
Type: filesandordirs; Name: "{app}\runtime\Lib\site-packages"

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\Voxel Cut.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icone.ico"
Name: "{group}\Pasta dos projetos"; Filename: "{userdocs}\Voxel Cut"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\Voxel Cut.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\app\icone.ico"; Tasks: desktopicon

[Dirs]
Name: "{userdocs}\Voxel Cut"; Flags: uninsneveruninstall

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\Voxel Cut.pyw"""; WorkingDir: "{app}"; Description: "Abrir o Voxel Cut agora"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\runtime\python.exe"; Parameters: """{app}\app\parar.py"""; Flags: runhidden; RunOnceId: "Parar"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var R: Integer;
begin
  if FileExists(ExpandConstant('{app}\app\parar.py')) then
    Exec(ExpandConstant('{app}\runtime\python.exe'), '"' + ExpandConstant('{app}\app\parar.py') + '"', '', SW_HIDE, ewWaitUntilTerminated, R);
  Result := '';
end;
