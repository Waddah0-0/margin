; Inno Setup script for the margin Windows desktop installer.
; Compiled by desktop/build_windows.py via ISCC.exe.

#ifndef MyAppVersion
  #define MyAppVersion "0.1.4"
#endif

#ifndef SourceDir
  #define SourceDir "..\build\desktop\dist\margin"
#endif

#ifndef OutputDir
  #define OutputDir "..\build\desktop\installer"
#endif

#define MyAppName "margin"
#define MyAppPublisher "Waddah Ali"
#define MyAppURL "https://waddah0-0.github.io/margin/"
#define MyAppExeName "margin.exe"

[Setup]
AppId={{8F6C2C4D-3B19-4C8A-9B72-7C261F3F2A10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL=https://github.com/Waddah0-0/margin/issues
AppUpdatesURL=https://github.com/Waddah0-0/margin/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=margin-setup-{#MyAppVersion}
SetupIconFile=assets\margin.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Per-user install by default (no UAC prompt required), with option to install for all users.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
function HasWebView2Runtime(): Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not HasWebView2Runtime() then
  begin
    MsgBox(
      'Microsoft Edge WebView2 Runtime was not detected on this PC.' + #13#10#13#10 +
      'margin uses WebView2 to display its window (built into Windows 11 and updated Windows 10). ' +
      'If the app does not open after installation, install the Evergreen WebView2 Runtime from Microsoft.',
      mbInformation,
      MB_OK
    );
  end;
end;
