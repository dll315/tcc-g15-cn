; Inno Setup 安装脚本 - TCC-G15 中文改造版
; 由 build.ps1 调用：iscc 安装版\installer-cn.iss
; 路径全部相对于本脚本所在目录（{#SourceDir}），换机器换盘符也能构建

#define MyAppName "TCC G15 中文版"
#define MyAppVersion "1.7.1-cn"
#define MyAppPublisher "dll315"
#define MyAppURL "https://github.com/dll315/tcc-g15-cn"
#define MyAppExeName "tcc-g15-cn.exe"

[Setup]
; AppId 是 Windows 识别“同一个产品”的唯一标识，沿用上游会让两个安装包互相覆盖/顶替卸载记录
AppId={{854F7CD8-AA8F-455C-AA9A-8BF64E22FC86}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
LicenseFile={#SourceDir}..\源码\LICENSE
; 程序本体需要管理员权限，但安装本身不需要：自启走提权计划任务，装在用户目录即可
PrivilegesRequired=lowest
OutputDir={#SourceDir}..\dist
OutputBaseFilename="TCC-G15-cn-{#MyAppVersion}-Setup"
SetupIconFile={#SourceDir}..\源码\icons\gaugeIcon-cn.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; 两个快捷方式都要打提权位，否则从开始菜单启动会以普通权限运行、控不了风扇
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; AfterInstall: SetElevationBit('{autoprograms}\{#MyAppName}.lnk')
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
