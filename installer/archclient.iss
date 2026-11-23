; installer/archclient.iss — dựng ArchClient-<phiên bản>-windows-x64-setup.exe
; Biên dịch bằng Inno Setup 6:
;   ISCC /DAPP_VERSION=1.0.0 installer/archclient.iss
; (workflow windowsbuild.yml gọi tự động sau bước build_windows.py)
; Cài per-user (không cần quyền admin) đúng tinh thần của launcher.

#ifndef APP_VERSION
  #define APP_VERSION "1.0.0"
#endif

#define AppName "Arch Client"

[Setup]
AppId={{A7C31E52-4B9D-4F6A-9E28-13D50C7B2F41}
AppName={#AppName}
AppVersion={#APP_VERSION}
AppVerName={#AppName} {#APP_VERSION}
DefaultDirName={autopf}\ArchClient
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\ArchClient.exe
OutputDir=..\dist
OutputBaseFilename=ArchClient-{#APP_VERSION}-windows-x64-setup
SetupIconFile=..\img\icon.ico
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMADictionarySize=65536
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\ArchClient\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\ArchClient.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\ArchClient.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ArchClient.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent
