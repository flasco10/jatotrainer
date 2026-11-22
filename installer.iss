#define AppName "jatotrainer"
; CI passes /DAppVersion=<tag>; local builds use this default.
#ifndef AppVersion
  #define AppVersion "1.5.0"
#endif

[Setup]
AppId={{7C6A5D83-BAC3-41AA-BAA4-D6382FC1D287}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=jatotrainer
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=LICENSE
DefaultDirName={localappdata}\Programs\jatotrainer
DefaultGroupName=jatotrainer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer-output
OutputBaseFilename=jatotrainer-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=assets\jatotrainer.ico
UninstallDisplayIcon={app}\jatotrainer.exe
CloseApplications=yes
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "dist\jatotrainer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\jatotrainer"; Filename: "{app}\jatotrainer.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\jatotrainer"; Filename: "{app}\jatotrainer.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\jatotrainer.exe"; Description: "Launch jatotrainer"; Flags: nowait postinstall skipifsilent
