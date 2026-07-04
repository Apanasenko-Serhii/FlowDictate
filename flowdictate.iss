; FlowDictate installer (Inno Setup). Per-user install, no admin required.
; Compile: ISCC.exe flowdictate.iss  -> release\FlowDictate-Setup-v1.1.0.exe

[Setup]
AppId={{A5F1C7E2-3B4D-4E5F-9A2B-FD10CT1CE001}
AppName=FlowDictate
AppVersion=1.1.0
AppPublisher=APANASENKO PRO
AppPublisherURL=https://github.com/Apanasenko-Serhii/FlowDictate
DefaultDirName={localappdata}\Programs\FlowDictate
DefaultGroupName=FlowDictate
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\FlowDictate.exe
UninstallDisplayName=FlowDictate
OutputDir=release
OutputBaseFilename=FlowDictate-Setup-v1.1.0
SetupIconFile=assets\app.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "dist\FlowDictate\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\FlowDictate"; Filename: "{app}\FlowDictate.exe"
Name: "{userdesktop}\FlowDictate"; Filename: "{app}\FlowDictate.exe"; Tasks: desktopicon
Name: "{userstartup}\FlowDictate"; Filename: "{app}\FlowDictate.exe"; Tasks: startupicon

[Tasks]
Name: "desktopicon"; Description: "Ярлик на робочому столі"; Flags: unchecked
Name: "startupicon"; Description: "Запускати разом з Windows"

[Run]
Filename: "{app}\FlowDictate.exe"; Description: "Запустити FlowDictate зараз"; Flags: nowait postinstall skipifsilent
