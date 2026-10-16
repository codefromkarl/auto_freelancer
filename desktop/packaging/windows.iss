#ifndef SourceDir
  #error SourceDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
[Setup]
AppId={{D102E67D-7A70-45F0-9B61-3509BE7708D7}
AppName=BidMaster Local
AppVersion=0.1.0
DefaultDirName={localappdata}\Programs\BidMaster
DefaultGroupName=BidMaster Local
UninstallDisplayIcon={app}\BidMaster.exe
OutputDir={#OutputDir}
OutputBaseFilename=BidMaster-0.1.0-windows-x64-setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
CloseApplications=no
AppMutex=Local\BidMasterLocalApplication
RestartApplications=no
[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\BidMaster Local"; Filename: "{app}\BidMaster.exe"
Name: "{autodesktop}\BidMaster Local"; Filename: "{app}\BidMaster.exe"; Tasks: desktopicon
[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked
[Run]
Filename: "{app}\BidMaster.exe"; Description: "Open BidMaster Local"; Flags: nowait postinstall skipifsilent
; User data lives outside {app}. Uninstall never deletes projects, credentials or receipts.
