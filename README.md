# TCC-G15 中文改造版

戴尔 G15 / Alienware 笔记本风扇与温度控制工具（AWCC 开源替代品）的中文增强版。

基于 [AlexIII/tcc-g15](https://github.com/AlexIII/tcc-g15) v1.6.4 二次开发，许可协议沿用 **GPL v3**。

## 下载

成品在 [Releases](https://github.com/dll315/tcc-g15-cn/releases/latest)，不以二进制形式提交进仓库：

| 文件 | 用途 |
|---|---|
| `tcc-g15-cn.exe` | 免安装单文件，右键「以管理员身份运行」 |
| `TCC-G15-cn-<版本号>-Setup.exe` | Inno Setup 安装器，安装到开始菜单 + 桌面快捷方式 |

## 仓库内容

| 路径 | 内容 |
|---|---|
| `源码/` | 完整源代码 + 依赖清单 + 中文说明 |
| `安装版/installer-cn.iss` | 安装器的 Inno Setup 脚本 |

## 新增功能（相对上游）

- 🌐 全面中文化
- 🎨 现代化深色主题 UI
- 📈 最近 5 分钟 GPU/CPU 温度走势图
- 📝 CSV 温度日志（按天分文件，托盘菜单可开关）
- 🎛️ **自动曲线模式**：自定义温度→风速曲线，每秒自动调风扇
- ⌨️ 全局热键 `Ctrl+Alt+T` 呼出窗口

## 快速开始

下载上表的任一成品运行即可。从源码运行：

```
cd 源码
pip install -r requirements.txt
python src/tcc-g15.py
```

## 支持的机型

Dell G15（5511/5515/5520/5525/5530/5535）、Alienware m16 R1、G3 3590，可能也支持其他戴尔 G 系列。

## 免责声明

- 需要管理员权限（访问 WMI 接口）
- 风扇控制依赖 AWCC 的 WMI 组件，建议保留官方 AWCC
- 「手动」风速过低时 BIOS 会接管自动提速防过热（上游已知限制）

详见 `源码/README-CN.md`。
