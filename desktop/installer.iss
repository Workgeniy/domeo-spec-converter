; Установщик автономного приложения Domeo (Inno Setup).
; Сборка: ISCC desktop\installer.iss (предварительно собрать бандл: desktop\build.ps1).
; Ставится в профиль пользователя (без прав администратора). Требуется Microsoft Edge
; WebView2 Runtime — присутствует на Windows 10/11 по умолчанию.

#define AppName "Domeo — просчёт спецификаций"
#define AppVersion "1.0.0"
#define Bundle "build\bundle"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Domeo
DefaultDirName={autopf}\Domeo
DefaultGroupName=Domeo
UninstallDisplayIcon={app}\Domeo.exe
OutputDir=build\installer
OutputBaseFilename=Domeo-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Files]
Source: "{#Bundle}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs

[Icons]
Name: "{group}\Domeo"; Filename: "{app}\Domeo.exe"
Name: "{autodesktop}\Domeo"; Filename: "{app}\Domeo.exe"

[Run]
Filename: "{app}\Domeo.exe"; Description: "Запустить Domeo"; Flags: nowait postinstall skipifsilent
