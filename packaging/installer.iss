; Inno Setup script for Secretary (one-folder app built by PyInstaller).
; Build: iscc packaging/installer.iss
; Run-key autostart (HKCU, no admin rights) per plan Appendix E.
; AUMID shortcut + toast from packaged exe verified manually (human-gated, P0-05).

#define MyAppName "Secretary"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#define MyAppPublisher "Sameer Ayachit"
#define MyAppExeName "secretary.exe"
#define MyAppURL "https://example.local/secretary"

[Setup]
AppId={{8A1C4F2E-6B3D-4C9A-9F01-1234567890AB}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppVerName={#MyAppName} {#MyAppVersion}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
PrivilegesRequired=low
Compression=lzma
SolidCompression=yes
WizardStyle=modern
OutputDir=Output
OutputBaseFilename=Secretary-Setup-{#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
name: "autostart"; Description: "Start {#MyAppName} at login"; GroupDescription: "Autostart:"; Flags: unchecked

[Files]
Source: "..\dist\secretary\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Autostart at login via HKCU Run key (Appendix E). Toggle off removes the value.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueName: "Secretary"; \
    ValueData: """{app}\{#MyAppExeName}"" --minimized"; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
end;
