# TCC-G15 中文改造版

基于 [AlexIII/tcc-g15](https://github.com/AlexIII/tcc-g15) v1.6.4 二次开发的中文增强版。原始项目是戴尔 G15 / Alienware 笔记本风扇与温度控制的开源替代品（替代 AWCC）。

> 许可协议：沿用上游 **GPL v3**（© github.com/AlexIII）

## 改造内容（相对上游 v1.6.4）

### ① 全面中文化
- 窗口标题、托盘菜单、对话框、tooltip 全部翻译为中文
- 模式名：均衡 / 性能模式 / 自定义 / 自动曲线
- 错误提示、日志表头中文化

### ② UI 现代化
- 深蓝灰主题 + 蓝色 accent，重写 QSS（圆角、渐变、单选钮 / 复选框 / 滑块 / ComboBox / Menu 全面翻新）
- 窗口宽度 600 → 660（容纳温度走势图）

### ③ 新增功能
| 功能 | 说明 |
|---|---|
| 温度走势图 | `GUI/TempHistoryGraph.py`：QPainter 自绘最近 5 分钟 GPU/CPU 双曲线，渐变填充，无新依赖 |
| CSV 日志 | `Backend/TempLogger.py`：按天分文件 `logs/temp_log_YYYY-MM-DD.csv`，托盘菜单可开关 |
| 自动曲线模式 | `Backend/FanCurve.py` + `GUI/FanCurveEditor.py`：自定义温度→风速曲线，程序每秒按温度自动调风扇 |
| 全局热键 | `Ctrl+Alt+T` 呼出/隐藏窗口 |

### ④ 其他
- 修上游 `_destroy()` 潜在 bug
- 版本号 → 1.7.0-cn

## 自动曲线模式用法

1. 单选钮选「自动曲线」
2. 点开曲线编辑器（GPU / CPU 切换）
3. 双击空白处加点、拖动改点、右键删点
4. 程序每秒按当前温度查曲线、插值出风速、自动下发

底层实现：AWCC WMI 接口只有 Balanced / G_Mode / Custom 三档，自动曲线模式在底层使用 Custom 档，风速由程序按曲线计算后下发。

## 运行（源码）

```
pip install -r requirements.txt
python src\tcc-g15.py
```

## 打包

```
python -m PyInstaller --noconfirm --clean --onefile --windowed \
  --name tcc-g15-cn \
  --icon icons/gaugeIcon-cn.ico \
  --add-data "icons;icons" \
  src/tcc-g15.py
```

> 注意：Windows 下 `--add-data` 的分隔符是 `;`（不是 Linux 的 `:`）

## 支持的机型

- Dell G15：5511、5515、5520、5525、5530、5535
- Dell Alienware m16 R1
- Dell G3 3590

可能也适用于其他戴尔 G15 / Alienware 笔记本。

## 依赖

见 `requirements.txt`：

- WMI >= 1.5.1
- PySide6 >= 6.2.2.1
- windows-toasts >= 1.3.0

## 已知限制（继承自上游）

- 需要管理员权限（访问 WMI 接口）
- 「手动」风扇控制并非真手动——风速过低时 BIOS 会接管自动提高转速防过热
- 切到 G 模式再切回可能导致约 1 秒系统卡顿（戴尔热控接口的已知问题，无法修复）
