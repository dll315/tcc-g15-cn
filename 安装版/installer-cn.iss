; Inno Setup 安装脚本 - TCC-G15 中文改造版
; 基于上游 installer-inno-config.iss 修改

#define MyAppName "TCC G15 中文版"
#define MyAppVersion "1.7.0-cn"
#define MyAppPublisher "dll315"
#define MyAppURL "https://github.com/dll315/tcc-g15-cn"
#define MyAppExeName "tcc-g15-cn.exe"

[Setup]
AppId={{8009F57D-B404-4274-BB42-A8AEBB02F37F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=G:\buddyworks\tcc\tcc-g15-cn-release\源码\LICENSE
PrivilegesRequired=lowest
OutputDir=G:\buddyworks\tcc\tcc-g15-cn-release\安装版
OutputBaseFilename="TCC-G15-cn-{#MyAppVersion}-Setup"
SetupIconFile=G:\buddyworks\tcc\tcc-g15-cn-release\源码\icons\gaugeIcon-cn.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "G:\buddyworks\tcc\tcc-g15-cn-release\便携版\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; AfterInstall: SetElevationBit('{autodesktop}\{#MyAppName}.lnk')

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait skipifsilent

[Code]
procedure SetElevationBit(Filename: string);
var
  Buffer: string;
  Stream: TStream;
begin
  Filename := ExpandConstant(Filename);
  Log('Setting elevation bit for ' + Filename);

  Stream := TFileStream.Create(FileName, fmOpenReadWrite);
  try
    Stream.Seek(21, soFromBeginning);
    SetLength(Buffer, 1);
    Stream.ReadBuffer(Buffer, 1);
    Buffer[1] := Chr(Ord(Buffer[1]) or $20);
    Stream.Seek(-1, soFromCurrent);
    Stream.WriteBuffer(Buffer, 1);
  finally
    Stream.Free;
  end;
end;
