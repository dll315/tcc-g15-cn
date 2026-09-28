<div align="center">

# TCC-G15 中文版

**戴尔 G15 / Alienware 笔记本风扇与温度控制工具（AWCC 开源替代品）的中文增强版**

[![Release](https://img.shields.io/github/v/release/dll315/tcc-g15-cn?style=flat-square&label=版本)](https://github.com/dll315/tcc-g15-cn/releases/latest)
[![License](https://img.shields.io/badge/许可-GPL--3.0-blue?style=flat-square)](%E6%BA%90%E7%A0%81/LICENSE)
[![Platform](https://img.shields.io/badge/平台-Windows%2010%2F11-0078D4?style=flat-square)](https://github.com/dll315/tcc-g15-cn)
[![Based on](https://img.shields.io/badge/基于-AlexIII%2Ftcc--g15%20v1.6.4-green?style=flat-square)](https://github.com/AlexIII/tcc-g15)

[下载](#-下载) · [快速上手](#-快速上手) · [开机自启](#-开机自启) · [常见问题](#-常见问题) · [源码构建](#-从源码构建)

</div>

---

## 这是什么

戴尔官方的 AWCC（Alienware Command Center）臃肿、缓慢、手动风扇控制是坏的，还偷偷上传遥测数据。[AlexIII/tcc-g15](https://github.com/AlexIII/tcc-g15) 是它的开源替代品——轻量、直接、不联网。

本项目是其**中文增强版**：全面中文化 + 深蓝灰现代主题，并新增温度走势图、CSV 日志、自动风扇曲线、全局热键等功能，同时修掉了上游一批会导致崩溃、自启失效的实际问题（详见 `源码/README-CN.md`）。

## ✨ 功能

| 类别 | 功能 |
|---|---|
| 📊 监控 | GPU / CPU 温度与风扇转速实时仪表、托盘数字图标、最近 5 分钟双曲线温度走势图 |
| 🎛️ 控制 | 均衡 / 性能（G 模式）/ 自定义（手动风速）三种模式，外加**自动曲线模式**：自绘温度→风速折线，每秒按当前温度插值下发（值不变不写） |
| 🛡️ 温度保护 | 超阈值（GPU 默认 85°C / CPU 默认 95°C，均可调）持续 8 秒自动切性能模式，回落 60 秒后自动恢复；传感器失联按高温处理，宁可误触发 |
| 📝 日志 | CSV 温度日志，按天分文件、Excel 直接打开不乱码（`utf-8-sig`），托盘可开关 |
| ⌨️ 热键 | `Ctrl+Alt+T` 显隐窗口；`F13`（G 键）切性能模式 |
| 🚀 自启 | 提权计划任务，登录后静默以管理员身份驻留托盘，不弹 UAC（[详见](#-开机自启)） |
| 🌐 其他 | 全面中文化、深蓝灰主题、机型识别（显示 CPU/GPU 型号） |

## 📥 下载

到 **[Releases](https://github.com/dll315/tcc-g15-cn/releases/latest)** 页面下载（成品以附件形式发布，不提交进仓库）：

| 文件 | 说明 |
|---|---|
| **TCC-G15-cn-&lt;版本&gt;-Setup.exe** | ✅ **推荐**。安装版：装到用户目录，开始菜单 / 桌面快捷方式已带提权位，双击即用 |
| **tcc-g15-cn.exe** | 便携版单文件：**右键 → 以管理员身份运行** |

> 每个 Release 附 SHA256 校验值，下载后可核对。

## 🚀 快速上手

1. **启动**：安装版双击桌面图标，或便携版右键「以管理员身份运行」
2. **控风扇**：主窗口选模式——日常用「均衡」，游戏/重载点「性能模式」，想自己定就用「自定义」拉滑条或「自动曲线」画折线
3. **托盘常驻**：关闭窗口时可选择最小化到托盘；右键托盘图标可快速切模式、开日志、开自启
4. **开机自启**：托盘菜单勾选「开机自启」即可（需要管理员权限，见下节）

> ⚠️ 控制风扇要写戴尔的 WMI 接口，**必须管理员权限**。普通权限下能看温度但控不了风扇——程序启动时会自检，不足会提示提权重启。

## 🔥 开机自启

自启通过**提权计划任务** `TCC_G15_CN` 实现（`HighestAvailable` + 登录触发，不弹 UAC）。这是唯一能在登录时静默以管理员身份启动的办法——注册表 `Run` 键天生无法提权。

为保证可靠性，自启做了四层防护：

| 措施 | 解决的问题 |
|---|---|
| 登录后**延迟 15 秒**启动 | 登录瞬间戴尔 WMI 组件尚未就绪，立刻启动几乎必失败（上游 [issue #7](https://github.com/AlexIII/tcc-g15/issues/7) 挂了三年的坑） |
| 启动后 WMI **自动重试**（3 秒 × 最多 60 秒） | 组件慢于预期时等它就绪，而不是弹错退出 |
| 任务创建后**回查落盘** | 组策略静默拦截时当场提示，而不是假装已开启 |
| 检测到**原版自启任务**时提醒 | 两边同时自启 = 同时运行，风扇控制权互抢 |

注意事项：

- 开启/关闭自启本身**需要管理员权限**；失败时弹窗会直接显示 `schtasks` 的原文原因
- 自启记录的是 exe 的**绝对路径**：移动或卸载程序后需重新勾选
- **升级版本后请重新勾选一次**——新的任务参数需要重建任务才生效

## 💻 支持机型

已验证：Dell **G15**（5511 / 5515 / 5520 / 5525 / 5530 / 5535）、**Alienware m16 R1**、**G3 3590**。

上游用户还报告 G15 5590、G3 15 3500、Alienware 16X Aurora、18 Area-51 可用；其他戴尔 G 系列大概率也行，欢迎反馈。

> 「CPU = 风扇 0、GPU = 风扇 1」是写死的机型假设。如果出现「CPU 滑条拧的是 GPU 风扇」的张冠李戴，即为该假设在你的机型上不成立。

## 🤝 与原版共存

| 方面 | 情况 |
|---|---|
| 设置存储 | ✅ 不冲突（原版与中文版各用各的注册表路径） |
| 开机自启 | ✅ 任务名独立：原版 `TCC_G15` vs 本版 `TCC_G15_CN`，互不顶替；开启本版自启时若检测到原版任务会提醒 |
| 安装/卸载记录 | ✅ 安装包 `AppId` 独立 GUID，Windows 不会当成同一产品互相覆盖 |
| 同时运行 | ❌ **不可以**。两者每秒都在写同一套风扇接口，会互相抢控制权；`F13` 热键也只有一方能注册成功 |

结论：**可以同时安装，但只能运行一个**。

## ❓ 常见问题

<details>
<summary><b>开机后托盘里没有图标？</b></summary>

1. 确认托盘菜单里「开机自启」处于勾选状态（升级版本后要重勾一次）
2. 打开「任务计划程序」找到 `TCC_G15_CN`，看「上次运行结果」列的代码：`0x0` = 成功；其他代码请提 issue 并附上
3. 确认 exe 没被移动过位置（自启记的是绝对路径）
</details>

<details>
<summary><b>能看温度但滑条/模式不生效？</b></summary>

权限不够。退出后用「以管理员身份运行」重启程序；安装版的快捷方式已带提权位，双击即是管理员。
</details>

<details>
<summary><b>F13（G 键）没反应？</b></summary>

全局热键是独占的：原版 tcc-g15 或本程序的另一个实例已经抢注了。关掉重复实例即可。`Ctrl+Alt+T` 同理（被别的软件占用时注册失败）。
</details>

<details>
<summary><b>手动把风速调很低，温度一高风扇又自己快了？</b></summary>

BIOS 的兜底行为（上游已知限制）：为防止过热，温度到点后 BIOS 会接管自动提速，属正常现象。
</details>

<details>
<summary><b>一定要装官方 AWCC 吗？</b></summary>

风扇控制依赖 AWCC 的 **WMI 组件**，建议保留官方 AWCC（或其组件）不卸载。本程序只是它的「遥控器」。
</details>

## 🔧 从源码构建

从源码直接运行：

```
pip install -r 源码/requirements.txt
python 源码/src/tcc-g15.py
```

自行构建成品（依赖：`pip install pyinstaller` + Inno Setup 6）：

```
powershell -File build.ps1            # 便携版 exe + 安装版 Setup
powershell -File build.ps1 -Debug     # 带控制台的调试版（print 可见）
```

产物在 `dist/`。发布方式：上传到 GitHub Release 附件，不进 git。

## ⚠️ 已知限制

- 「手动」风扇控制并非真手动——风速过低时 BIOS 会接管防过热（上游已知限制）
- 切换 G 模式的瞬间可能有约 1 秒系统卡顿（戴尔热控接口的已知问题，上游确认无法修复）
- 传感器读不到数值时，温度保护按高温处理（宁可误触发，不可漏触发）

## 📄 许可与致谢

- 基于 [AlexIII/tcc-g15](https://github.com/AlexIII/tcc-g15) **v1.6.4** 二次开发，许可沿用 **GPL v3**（© github.com/AlexIII）
- 详细改造说明与逐版修复记录：[源码/README-CN.md](%E6%BA%90%E7%A0%81/README-CN.md)
- 问题反馈：[Issues](https://github.com/dll315/tcc-g15-cn/issues)
