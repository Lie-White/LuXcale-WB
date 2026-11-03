; Installer for the lab release (docs/PLAN.md §4-41): per user, no administrator rights.
; Built by packaging\build_release.py after PyInstaller has filled output\dist\LuXcale.

#define AppVersion "1.0.4"

[Setup]
AppId=LuXcale
AppName=LuXcale
AppVersion={#AppVersion}
AppVerName=LuXcale {#AppVersion}
AppPublisher=LuXcale (lab use)
DefaultDirName={localappdata}\Programs\LuXcale
DefaultGroupName=LuXcale
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\output\installer
OutputBaseFilename=LuXcale-{#AppVersion}-setup
SetupIconFile=..\src\imquant\ui\assets\icon.ico
UninstallDisplayIcon={app}\LuXcale.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
LicenseFile=..\output\installer-stage\NOTICE.txt

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\output\dist\LuXcale\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\output\installer-stage\NOTICE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\output\installer-stage\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\LuXcale"; Filename: "{app}\LuXcale.exe"
Name: "{autodesktop}\LuXcale"; Filename: "{app}\LuXcale.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LuXcale.exe"; Description: "{cm:LaunchProgram,LuXcale}"; Flags: nowait postinstall skipifsilent
