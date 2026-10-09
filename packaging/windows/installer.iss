; Inno Setup: один файл-установщик Muninhall-Setup-<версия>.exe из dist\Muninhall.
; Ставится для текущего пользователя, без прав администратора.
;   iscc /DAppVersion=0.18.0 packaging\windows\installer.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F2E4C1B-9B7D-4E5A-8C3F-2A1D0B9E7C61}
AppName=Muninhall
AppVersion={#AppVersion}
AppPublisher=Muninhall
AppPublisherURL=https://github.com/arvino-t/muninhall
DefaultDirName={localappdata}\Programs\Muninhall
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Muninhall-Setup-{#AppVersion}
SetupIconFile=..\..\muninhall\data\muninhall.ico
UninstallDisplayIcon={app}\Muninhall.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\..\dist\Muninhall\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\Muninhall"; Filename: "{app}\Muninhall.exe"
Name: "{userdesktop}\Muninhall"; Filename: "{app}\Muninhall.exe"; Tasks: desktopicon

[Registry]
; «Открыть с помощью» для электронных книг — не отбирая открытие по умолчанию у других программ
Root: HKCU; Subkey: "Software\Classes\Muninhall.Book"; ValueType: string; ValueData: "E-book"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Muninhall.Book\DefaultIcon"; ValueType: string; ValueData: "{app}\Muninhall.exe,0"
Root: HKCU; Subkey: "Software\Classes\Muninhall.Book\shell\open\command"; ValueType: string; ValueData: """{app}\Muninhall.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\.epub\OpenWithProgids"; ValueType: string; ValueName: "Muninhall.Book"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.fb2\OpenWithProgids"; ValueType: string; ValueName: "Muninhall.Book"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.fbz\OpenWithProgids"; ValueType: string; ValueName: "Muninhall.Book"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.mobi\OpenWithProgids"; ValueType: string; ValueName: "Muninhall.Book"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.azw3\OpenWithProgids"; ValueType: string; ValueName: "Muninhall.Book"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: string; ValueName: "Muninhall.Book"; ValueData: ""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Muninhall.exe"; Description: "{cm:LaunchProgram,Muninhall}"; Flags: nowait postinstall skipifsilent
