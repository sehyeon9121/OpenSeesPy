; OpenFrame Studio Windows installer.
;
; Packages build/payload/ (produced by scripts/build_windows_payload.py - a
; real embedded Python interpreter with this project and every dependency
; already `pip install`-ed into it) rather than a PyInstaller-frozen exe.
; See installer/README.md and the build script's own docstring for why: the
; app relaunches itself as a subprocess via `sys.executable -m
; openframe.infrastructure.opensees.worker` for every precision analysis,
; which only works if sys.executable is a genuine interpreter.
;
; Build: run scripts/build_windows_payload.py first, then compile this file
; with Inno Setup's ISCC.exe (or open it in the Inno Setup IDE and hit
; Build). Output goes to installer/output/ (not tracked in git).

#define MyAppName "OpenFrame Studio"
#define MyAppVersion "0.1.0"
#define MyAppExeDir "{app}"
#define PayloadDir "..\build\payload"

[Setup]
AppId={{A8FE161E-AB23-4C22-BC8F-0F3DAB6FD631}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
; Installs into the current user's own folder, not Program Files - avoids
; needing admin/UAC on a friend's PC, which is the whole point of "give the
; installer to people I know" being low-friction.
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=output
OutputBaseFilename=OpenFrameStudio-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
SetupIconFile=..\src\openframe\resources\icons\app_icon.ico
UninstallDisplayIcon={app}\Lib\site-packages\openframe\resources\icons\app_icon.ico
WizardStyle=modern
DisableProgramGroupPage=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; The whole payload tree, verbatim - python.exe/pythonw.exe, the stdlib,
; and Lib\site-packages with every dependency + this project already
; installed. recursesubdirs+ignoreversion since this is a from-scratch
; payload each build, not an incremental upgrade.
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\pythonw.exe"; \
    Parameters: "-m openframe"; WorkingDir: "{app}"; \
    IconFilename: "{app}\Lib\site-packages\openframe\resources\icons\app_icon.ico"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\pythonw.exe"; \
    Parameters: "-m openframe"; WorkingDir: "{app}"; \
    IconFilename: "{app}\Lib\site-packages\openframe\resources\icons\app_icon.ico"; \
    Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "바탕화면에 바로가기 만들기"; GroupDescription: "추가 아이콘:"

[UninstallDelete]
; Python bytecode caches (__pycache__) and the material/section DB's own
; rewritten cache.json (see cache.py's docstring) get created under {app}
; the first time the app actually runs - Inno Setup only tracks files it
; itself installed, so without this an uninstall would leave those behind.
Type: filesandordirs; Name: "{app}"

[Run]
Filename: "{app}\pythonw.exe"; Parameters: "-m openframe"; \
    WorkingDir: "{app}"; Description: "{#MyAppName} 실행"; \
    Flags: nowait postinstall skipifsilent
