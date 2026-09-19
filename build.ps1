# TCC-G15 中文改造版 构建脚本
#   powershell -File build.ps1          发布构建（无控制台窗口）
#   powershell -File build.ps1 -Debug   调试构建（带控制台，print 才看得见）
#
# 依赖：pip install pyinstaller ；Inno Setup 6（提供 ISCC.exe）
param([switch]$Debug)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

$version = '1.7.1-cn'          # 与 AppGUI.APP_VERSION、installer-cn.iss 保持一致
$icon    = Join-Path $root '源码/icons/gaugeIcon-cn.ico'

# 便携版单文件 exe。路径全部给绝对路径：--specpath 会让 PyInstaller 把 --add-data 的
# 相对源路径按 spec 目录解析，写成相对路径会报 "Unable to find ..."（实测）。
# --add-data 把 icons 打进包：代码里 resourcePath() 在打包后
# 指向 PyInstaller 的解包目录，缺了它窗口图标和 toast 图会静默丢失。
# 不加 --uac-admin：开机自启用的是提权计划任务（见 AppGUI.TASK_XML_TEMPLATE），
# exe 自己申请提权反而会让每次开机弹 UAC。需要 exe 双击即提权时再加该参数。
$pyiArgs = @(
    '--noconfirm', '--clean', '--onefile'
    '--name', 'tcc-g15-cn'
    '--icon', $icon
    '--paths', (Join-Path $root '源码/src')
    '--add-data', ((Join-Path $root '源码/icons') + ';icons')
    '--distpath', (Join-Path $root 'dist')
    '--workpath', (Join-Path $root 'build')
    '--specpath', (Join-Path $root 'build')
    (Join-Path $root '源码/src/tcc-g15.py')
)
if (-not $Debug) { $pyiArgs = @('--windowed') + $pyiArgs }
pyinstaller @pyiArgs
if ($LASTEXITCODE) { throw "PyInstaller 失败" }

# 安装版 Setup（Inno）
$iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $iscc) {
    foreach ($c in "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") {
        if (Test-Path $c) { $iscc = $c; break }
    }
}
if (-not $iscc) { Write-Warning "没找到 ISCC.exe，已跳过安装版；便携版 exe 在 dist/"; exit 0 }
& $iscc (Join-Path $root '安装版/installer-cn.iss')
if ($LASTEXITCODE) { throw "Inno Setup 编译失败" }

Write-Host "`n产物：dist/tcc-g15-cn.exe 与 dist/TCC-G15-cn-$version-Setup.exe" -ForegroundColor Green
Write-Host "发布方式：上传到 GitHub Release 附件，不要提交进 git（.gitignore 已屏蔽 *.exe）"
