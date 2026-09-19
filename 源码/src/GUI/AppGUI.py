import sys, os, time, datetime
from enum import Enum
from typing import Callable, Literal, Optional, Tuple, List
from PySide6 import QtCore, QtGui, QtWidgets
from windows_toasts import WindowsToaster, Toast, ToastDuration, ToastDisplayImage
from Backend.AWCCThermal import AWCCThermal, NoAWCCWMIClass, CannotInstAWCCWMI
from Backend.AWCCWmiWrapper import AWCCWmiWrapper
from Backend.TempLogger import TempLogger
from Backend.FanCurve import FanCurve
from GUI.QRadioButtonSet import QRadioButtonSet
from GUI.AppColors import Colors
from GUI.ThermalUnitWidget import ThermalUnitWidget
from GUI.QGaugeTrayIcon import QGaugeTrayIcon
from GUI.TempHistoryGraph import TempHistoryGraph
from GUI.FanCurveEditor import FanCurveEditor
from GUI import HotKey
from GUI.HotKey import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT
from Backend.DetectHardware import DetectHardware

GUI_ICON = 'icons/gaugeIcon-cn.ico'
GUI_ICON_FALLBACK = 'icons/gaugeIcon.png'

# 资源锚点：打包后用 PyInstaller 的解包目录；源码运行时本文件位于 源码/src/GUI/，上三层才是 源码/
_APP_ROOT = getattr(sys, '_MEIPASS', None) or os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def resourcePath(relativePath: str = '.'):
    return os.path.join(_APP_ROOT, relativePath)

def appExePath() -> str:
    """返回当前运行的真实可执行文件路径。

    PyInstaller --onefile 打包后，sys.argv[0] 会被替换为 _MEIxxxx 临时解压目录
    （每次启动随机变化），而 sys.executable 才是用户安装/放置的那个 exe。
    用 argv[0] 会导致：开机自启 Run 键指向一个每次都在变的临时路径、CSV 日志
    写到临时目录等 bug。故打包状态下统一取 sys.executable。
    """
    if getattr(sys, 'frozen', False):
        return sys.executable
    return os.path.abspath(sys.argv[0])

def appIcon() -> QtGui.QIcon:
    """返回应用图标。优先用新 ico，找不到（资源未打包/路径不符）则回退 png 或 exe 内嵌图标。"""
    p = resourcePath(GUI_ICON)
    if os.path.exists(p):
        return QtGui.QIcon(p)
    p2 = resourcePath(GUI_ICON_FALLBACK)
    if os.path.exists(p2):
        return QtGui.QIcon(p2)
    return QtGui.QIcon()

# 任务名必须与原版区分：上游 AlexIII/tcc-g15 注册的计划任务就叫 TCC_G15，
# 同名会让两个程序互相覆盖、互相删除对方的开机自启
TASK_NAME = "TCC_G15_CN"
LEGACY_RUN_VALUE = "TCC_G15"     # 1.7.0-cn 用 Run 键做自启时留下的值

# 开机自启必须是提权任务，否则程序以普通权限启动、拿不到 AWCC 的 WMI 写权限。
# HKCU\...\Run 键天生无法提权，所以用计划任务：InteractiveToken + HighestAvailable
# 在登录时以管理员身份启动且不弹 UAC。XML 作为常量内嵌、运行时写 %TEMP%，
# 不再依赖打包目录里的外部文件（_MEIPASS 只读，改写在打包后必然失败）。
TASK_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>TCC-G15 中文改造版 开机自启 | github.com/dll315/tcc-g15-cn</Description>
    <URI>\\{task_name}</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <StartBoundary>2026-01-01T00:00:00</StartBoundary>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>"{exe}"</Command>
      <Arguments>--minimized</Arguments>
    </Exec>
  </Actions>
</Task>
"""

def isElevated() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def relaunchElevated() -> bool:
    """请求 UAC 提权重启本程序。用户取消或环境不支持时返回 False。"""
    exe = appExePath()
    if not exe.lower().endswith('.exe'):
        return False
    try:
        import ctypes
        params = ' '.join(f'"{a}"' for a in sys.argv[1:])
        # SW_SHOW=5；返回值 <=32 表示失败（含用户在 UAC 上点了"否"）
        return int(ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 5)) > 32
    except Exception:
        return False

def cleanupLegacyRunEntry() -> None:
    """删除 1.7.0-cn 写在 HKCU Run 键里的自启值。
    留着它会与计划任务并存：开机拉起两份程序，或指向一个已被移走的 exe 而每次开机报错。"""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
    except OSError:
        return
    try:
        winreg.DeleteValue(key, LEGACY_RUN_VALUE)
    except OSError:
        pass
    finally:
        winreg.CloseKey(key)

def autorunTask(action: Literal['add', 'remove']) -> Tuple[int, str]:
    """开机自启：创建/删除提权计划任务。返回 (0, '') 表示成功。

    第二个返回值是 schtasks 的原话：windowed 构建里 print 无处可看，不把失败原因
    带到界面上，用户就只能看到一个没有信息量的错误码。"""
    import subprocess
    import tempfile

    if action == 'add':
        exeFile = appExePath()
        if not exeFile.lower().endswith('.exe'):
            return -100, '当前是源码运行，没有可自启的 exe，请用打包出的 tcc-g15-cn.exe 再开启'
        if not isElevated():
            return -101, '当前不是管理员权限，无法创建提权自启任务。请先右键程序「以管理员身份运行」再开启'
        xml = TASK_XML_TEMPLATE.format(task_name=TASK_NAME, exe=os.path.normpath(exeFile))
        xmlPath = os.path.join(tempfile.gettempdir(), 'tcc_g15_cn_task.xml')
        try:
            with open(xmlPath, 'w', encoding='utf-16') as f:   # schtasks 要求声明与实际编码一致
                f.write(xml)
        except OSError as ex:
            return -102, f'写入临时任务文件失败：{ex}'
        cmd = ['schtasks', '/create', '/f', '/tn', TASK_NAME, '/xml', xmlPath]
    else:
        cmd = ['schtasks', '/delete', '/f', '/tn', TASK_NAME]

    try:
        # 列表参数、不走 shell：路径里有空格或 & 都不会被当成命令
        res = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as ex:
        return -103, f'无法执行 schtasks：{ex}'
    if res.returncode != 0:
        print(f'schtasks {action} failed: {res.stdout} {res.stderr}')
        # 删除一个本就不存在的任务，schtasks 也返回非 0，这种"失败"要当成功
        if action == 'remove' and ('找不到' in (res.stderr + res.stdout) or 'cannot find' in (res.stderr + res.stdout).lower()):
            cleanupLegacyRunEntry()
            return 0, ''
        return res.returncode, (res.stdout + res.stderr).strip()[:400]
    # 只有任务真的处理成功才清旧 Run 值：否则建任务失败 + 旧项被删 = 自启彻底失效
    cleanupLegacyRunEntry()
    return 0, ''

def alert(title: str, message: str, type: QtWidgets.QMessageBox.Icon = QtWidgets.QMessageBox.Icon.Information, *, message2: Optional[str] = None) -> None:
    msg = QtWidgets.QMessageBox(type, title, message)
    msg.setWindowIcon(appIcon())
    if message2: msg.setInformativeText(message2)
    msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
    msg.exec()

def confirm(title: str, message: str, options: Optional[Tuple[str, str]] = None, dontAskAgain: bool = False) -> Tuple[bool, Optional[bool]]:
    msg = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, title, message, QtWidgets.QMessageBox.Yes |  QtWidgets.QMessageBox.No)
    msg.setWindowIcon(appIcon())
    # 中文化默认按钮
    msg.button(QtWidgets.QMessageBox.Yes).setText("是")
    msg.button(QtWidgets.QMessageBox.No).setText("否")

    if options is not None:
        msg.button(QtWidgets.QMessageBox.Yes).setText(options[0])
        msg.button(QtWidgets.QMessageBox.No).setText(options[1])

    cbDontAskAgain = None
    if dontAskAgain:
        cbDontAskAgain = QtWidgets.QCheckBox('不再询问', msg)
        msg.setCheckBox(cbDontAskAgain)

    return (msg.exec_() == QtWidgets.QMessageBox.Yes, cbDontAskAgain is not None and cbDontAskAgain.isChecked() or None)


class QPeriodic:
    def __init__(self, parent: QtCore.QObject, periodMs: int, callback: Callable) -> None:
        self._tmr = QtCore.QTimer(parent)
        self._tmr.setInterval(periodMs)
        self._tmr.setSingleShot(False)
        self._tmr.timeout.connect(callback)
    def start(self):
        self._tmr.start()
    def stop(self):
        self._tmr.stop()

class ThermalMode(Enum):
    Balanced = 'Balanced'
    G_Mode = 'G_Mode'
    Custom = 'Custom'
    Auto = 'Auto'  # 自动曲线模式：底层使用 Custom 档，风速由曲线决定

# 模式中文名（仅显示用，存储值不变）
MODE_DISPLAY = {
    ThermalMode.Balanced.value: "均衡",
    ThermalMode.G_Mode.value: "性能模式",
    ThermalMode.Custom.value: "自定义",
    ThermalMode.Auto.value: "自动曲线",
}
def modeDisplayName(modeValue: str) -> str:
    return MODE_DISPLAY.get(modeValue, modeValue)

# UI 模式 -> AWCC 后端档位。显式写出而不是 Mode[名字]，
# 否则两套同名枚举任何一侧改名都会在这里变成运行时 KeyError。
UI_MODE_TO_BACKEND = {
    ThermalMode.Balanced.value: AWCCWmiWrapper.ThermalMode.Balanced,
    ThermalMode.G_Mode.value:   AWCCWmiWrapper.ThermalMode.G_Mode,
    ThermalMode.Custom.value:   AWCCWmiWrapper.ThermalMode.Custom,
    ThermalMode.Auto.value:     AWCCWmiWrapper.ThermalMode.Custom,   # 自动曲线借用手动档
}

class SettingsKey(Enum):
    Mode = "app/mode"
    CPUFanSpeed = "app/fan/cpu/speed"
    CPUThresholdTemp = "app/fan/cpu/threshold_temp"
    GPUFanSpeed = "app/fan/gpu/speed"
    GPUThresholdTemp = "app/fan/gpu/threshold_temp"
    FailSafeIsOnFlag = "app/failsafe_is_on_flag"
    MinimizeOnCloseFlag = "app/minimize_on_close_flag"
    LogEnabledFlag = "app/log_enabled_flag"
    GpuCurve = "app/curve/gpu"
    CpuCurve = "app/curve/cpu"

def errorExit(message: str, message2: Optional[str] = None) -> None:
    if not QtWidgets.QApplication.instance():
         QtWidgets.QApplication([])
    alert("出错了", message, QtWidgets.QMessageBox.Icon.Critical, message2 = message2)
    sys.exit(1)

class TCC_GUI(QtWidgets.QWidget):
    TEMP_UPD_PERIOD_MS = 1000
    DEFAULT_FAILSAFE_CPU_TEMP = 95
    DEFAULT_FAILSAFE_GPU_TEMP = 85
    FAILSAFE_CPU_TEMP = DEFAULT_FAILSAFE_CPU_TEMP
    FAILSAFE_GPU_TEMP = DEFAULT_FAILSAFE_GPU_TEMP
    FAILSAFE_TRIGGER_DELAY_SEC = 8
    FAILSAFE_RESET_AFTER_TEMP_IS_OK_FOR_SEC = 60
    APP_NAME = "G15 温控中心"
    APP_VERSION = "1.7.1-cn"
    APP_DESCRIPTION = "Alienware Command Center 的开源替代品（中文改造版）"
    APP_URL = "github.com/AlexIII/tcc-g15"
    # 设置存储隔离：必须与原作者不同，否则改造版的 'Auto' 模式会污染原版设置、导致原版崩溃
    SETTINGS_ORG = "github.com/dll315/tcc-g15-cn"

    # Green to Yellow and Yellow to Red thresholds
    GPU_COLOR_LIMITS = (72, 85)
    CPU_COLOR_LIMITS = (85, 95)

    # private
    _failsafeTempIsHighTs = 0                           # Last time when the temp was registered to be high
    _failsafeTempIsHighStartTs: Optional[int] = None    # Time when the temp first registered to be high (without going lower than the threshold)
    _failsafeTrippedPrevModeStr: Optional[str] = None   # Mode (Custom, Balanced) before fail-safe tripped, as a string
    _pendingMode: Optional[str] = None                  # 下发失败、需要重试的模式
    _lastSensorTemps: Tuple[Optional[int], Optional[int]] = (None, None)
    _failsafeOn = True
    _prevSavedSettingsValues: list = []

    _gModeKeySignal = QtCore.Signal()
    _gModeKeyPrevModeStr: Optional[str] = None

    _showHideKeySignal = QtCore.Signal()

    _toaster = WindowsToaster(APP_NAME)

    _modeSwitch: QRadioButtonSet

    def __init__(self, awcc: AWCCThermal):
        super().__init__()
        self._awcc = awcc

        self.settings = QtCore.QSettings(self.SETTINGS_ORG, "AWCC")
        print(f'Settings location: {self.settings.fileName()}')

        # Set main window props
        self.setFixedSize(660, 0)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.WindowMinimizeButtonHint | QtCore.Qt.WindowCloseButtonHint)
        self.setWindowIcon(appIcon())
        self.mouseReleaseEvent = lambda evt: (
            evt.button() == QtCore.Qt.RightButton and
            alert("关于", f"{self.APP_NAME} v{self.APP_VERSION}", message2 = f"{self.APP_DESCRIPTION}\n{self.APP_URL}")
        )

        # 温度日志记录器
        logEnabledSaved = self.settings.value(SettingsKey.LogEnabledFlag.value)
        self._tempLogger = TempLogger(enabled=(str(logEnabledSaved).lower() == 'true' if logEnabledSaved is not None else False))

        # 风扇曲线（自动模式），从设置加载，失败则用默认曲线
        self._gpuCurve = FanCurve(FanCurve.DEFAULT_GPU)
        self._cpuCurve = FanCurve(FanCurve.DEFAULT_CPU)
        savedGpuCurve = self.settings.value(SettingsKey.GpuCurve.value)
        if savedGpuCurve: self._gpuCurve.fromJson(str(savedGpuCurve))
        savedCpuCurve = self.settings.value(SettingsKey.CpuCurve.value)
        if savedCpuCurve: self._cpuCurve.fromJson(str(savedCpuCurve))

        def onCurveChanged(curveKind: str):
            curve = self._gpuCurve if curveKind == 'GPU' else self._cpuCurve
            key = SettingsKey.GpuCurve if curveKind == 'GPU' else SettingsKey.CpuCurve
            self.settings.setValue(key.value, curve.toJson())
            # 自动模式下立即应用新曲线
            if self._modeSwitch.getChecked() == ThermalMode.Auto.value:
                applyAutoFanCurve()
        # 风扇曲线编辑器
        self._curveEditor = FanCurveEditor(self, self._gpuCurve, self._cpuCurve, onCurveChanged)
        self._curveEditor.setEnabled(False)

        # Set up tray icon
        self.trayIcon = QGaugeTrayIcon((self.GPU_COLOR_LIMITS, self.CPU_COLOR_LIMITS))
        menu = QtWidgets.QMenu()
        # Mode switch
        menu.addSection("模式")
        self._trayMenuModeSwitch = {} # Dict[ThermalMode, QtWidgets.QAction]
        for m in ThermalMode:
            modeAction = menu.addAction("-")
            modeAction.triggered.connect(lambda _, m_value=m.value: self._modeSwitch.setChecked(m_value))
            self._trayMenuModeSwitch[m.value] = modeAction
        # Settings
        menu.addSection("设置")
        showAction = menu.addAction("显示主窗口")
        showAction.triggered.connect(self.showNormal)

        # 温度日志开关
        self._logToggleAction = menu.addAction("记录温度日志")
        self._logToggleAction.setCheckable(True)
        self._logToggleAction.setChecked(self._tempLogger.enabled)
        def onLogToggle(checked: bool):
            if self._tempLogger.setEnabled(checked):
                self.settings.setValue(SettingsKey.LogEnabledFlag.value, checked)
                if checked:
                    alert("温度日志", f"日志已开启。\n保存位置：{self._tempLogger.logDir}")
            else:
                alert("错误", "无法创建日志文件，请检查目录权限。", QtWidgets.QMessageBox.Icon.Critical)
                self._logToggleAction.setChecked(False)
        self._logToggleAction.toggled.connect(onLogToggle)

        # 打开日志目录
        openLogDirAction = menu.addAction("打开日志目录")
        def openLogDir():
            os.makedirs(self._tempLogger.logDir, exist_ok=True)
            os.system(f'explorer "{self._tempLogger.logDir}"')
        openLogDirAction.triggered.connect(openLogDir)

        addToAutorunAction = menu.addAction("开机自启")
        AUTORUN_ERRORS = {
            -100: '源码运行没有可自启的 exe，请用打包后的 exe 再开启',
            -101: '需要管理员权限才能创建提权自启任务',
            -102: '无法写入临时目录',
            -103: '找不到 schtasks 命令',
            1: '任务计划程序拒绝了创建请求，详见下方原文',
        }
        def autorunTaskRun(action: Literal['add', 'remove']) -> None:
            err, detail = autorunTask(action)
            if err != 0 and action == 'add':
                alert("开机自启未开启", AUTORUN_ERRORS.get(err, detail or f'错误码 {err}'),
                      QtWidgets.QMessageBox.Icon.Critical)
            else:
                alert("成功", f"开机自启已{'开启' if action == 'add' else '关闭'}")
            # When in minimized state, a wired bug causes the app to close if we won't touch some of the `self.show*()` methods
            if self.isMinimized():
                self.showMinimized()
                self.hide()
        addToAutorunAction.triggered.connect(lambda: autorunTaskRun('add'))
        removeFromAutorunAction = menu.addAction("关闭自启")
        removeFromAutorunAction.triggered.connect(lambda: autorunTaskRun('remove'))
        restoreAction = menu.addAction("恢复默认设置")
        restoreAction.triggered.connect(self.clearAppSettings)
        exitAction = menu.addAction("退出")
        exitAction.triggered.connect(self.onExit)
        # Setup tray widget（存为实例属性，防止被 GC 回收导致最小化后无托盘）
        self.tray = QtWidgets.QSystemTrayIcon(self)
        self.tray.setIcon(self.trayIcon)
        self.tray.setContextMenu(menu)
        self.tray.show()

        def onTrayIconActivated(trigger):
            if trigger == QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick:
                self.showNormal()
                self.activateWindow()
        self.connect(self.tray, QtCore.SIGNAL("activated(QSystemTrayIcon::ActivationReason)"), onTrayIconActivated)

        # Set up GUI
        self.setObjectName('QMainWindow')
        self.setWindowTitle(f"{self.APP_NAME} v{self.APP_VERSION}")

        self._thermalGPU = ThermalUnitWidget(self, tempMinMax= (0, 95), tempColorLimits= self.GPU_COLOR_LIMITS, fanMinMax= (0, 5500), sliderMaxAndTick= (120, 20))
        self._thermalGPU.setTitle('GPU 显卡')
        self._thermalCPU = ThermalUnitWidget(self, tempMinMax= (0, 110), tempColorLimits= self.CPU_COLOR_LIMITS, fanMinMax= (0, 5500), sliderMaxAndTick= (120, 20))
        self._thermalCPU.setTitle('CPU 处理器')

        # Detecting GPU/CPU model is a slow operation, run asynchronously
        class DetectCpuGpuModelsWorker(QtCore.QObject):
            finished = QtCore.Signal(str, str)
            def __init__(self, parent: QtCore.QObject, on_result: Callable[[Optional[str], Optional[str]], None]) -> None:
                super().__init__(parent)
                self._t = QtCore.QThread(parent)
                self.moveToThread(self._t)
                self.finished.connect(self._t.quit)
                self.finished.connect(on_result)
                self._t.started.connect(self._task)
                self._t.start()
            def _task(self):
                print("DetectCpuGpuModelsWorker: started")
                d = DetectHardware()
                gpuModel = d.getHardwareName(d.GPUFanIdx)
                cpuModel = d.getHardwareName(d.CPUFanIdx)
                print(f"DetectCpuGpuModelsWorker: finished: {gpuModel}, {cpuModel}")
                self.finished.emit(gpuModel, cpuModel)
            def start(self):
                self._t.start()
        detect = DetectCpuGpuModelsWorker(self, self.updateGaugeTitles)
        detect.start()

        lTherm = QtWidgets.QHBoxLayout()
        lTherm.addWidget(self._thermalGPU)
        lTherm.addWidget(self._thermalCPU)

        # 温度走势曲线（最近 5 分钟）
        self._tempGraph = TempHistoryGraph(self)
        graphLabel = QtWidgets.QLabel("温度走势")
        graphLabel.setStyleSheet(f"color: {Colors.TEXT_DIM.value}; font-size: 12px;")

        # 风扇曲线编辑器（自动曲线模式）
        curveLabel = QtWidgets.QLabel("风扇曲线（选择「自动曲线」模式后生效）")
        curveLabel.setStyleSheet(f"color: {Colors.TEXT_DIM.value}; font-size: 12px;")

        self._modeSwitch = QRadioButtonSet(None, None, list(map(lambda m: (modeDisplayName(m.value), m.value), ThermalMode)))

        # Fail-safe indicator
        failsafeIndicator = QtWidgets.QLabel()
        def updFailsafeIndicator() -> None:
            color = Colors.GREEN.value if self._failsafeOn else Colors.GREY.value
            msg = "温度保护：已开启，运行正常"
            if self._failsafeTempIsHighTs > 0: # Fail-safe have tripped at some point in the past
                color = Colors.YELLOW.value
                timeStr = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self._failsafeTempIsHighTs))
                msg = f"上次高温：{timeStr}"
                if self._failsafeTrippedPrevModeStr is not None: # Fail-safe is in tripped state now
                    color = Colors.RED.value
                    msg = "温度保护已触发：已切换到性能模式散热"

            failsafeIndicator.setStyleSheet(f"QLabel {{ min-height: 14px; min-width: 14px; max-height: 14px; max-width: 14px; border: 1px solid {Colors.GREY.value}; border-radius: 7px; background: {color}; }}")
            failsafeIndicator.setToolTip(msg)
        updFailsafeIndicator()

        # Fail-safe temp limits
        self._limitTempGPU = QtWidgets.QComboBox()
        self._limitTempGPU.addItems(list(map(lambda v: str(v), range(50, 91))))
        self._limitTempGPU.setToolTip("GPU 温度阈值（°C）")
        self._limitTempCPU = QtWidgets.QComboBox()
        self._limitTempCPU.addItems(list(map(lambda v: str(v), range(50, 101))))
        self._limitTempCPU.setToolTip("CPU 温度阈值（°C）")
        def onLimitGPUChange():
            val = self._limitTempGPU.currentText()
            if val.isdigit(): self.FAILSAFE_GPU_TEMP = int(val)
            updFailsafeTooltip()
        self._limitTempGPU.currentIndexChanged.connect(onLimitGPUChange)
        def onLimitCPUChange():
            val = self._limitTempCPU.currentText()
            if val.isdigit(): self.FAILSAFE_CPU_TEMP = int(val)
            updFailsafeTooltip()
        self._limitTempCPU.currentIndexChanged.connect(onLimitCPUChange)

        # Fail-safe checkbox
        self._failsafeCB = QtWidgets.QCheckBox("温度保护")
        def updFailsafeTooltip():
            self._failsafeCB.setToolTip(
                f"当 GPU 温度达到 {self.FAILSAFE_GPU_TEMP}°C 或 CPU 温度达到 {self.FAILSAFE_CPU_TEMP}°C 时"
                "（传感器无读数也算），持续 8 秒自动切换到性能模式，降温 60 秒后恢复")
        updFailsafeTooltip()
        def onFailsafeCB():
            self._failsafeOn = self._failsafeCB.isChecked()
            self._failsafeTempIsHighTs = 0
            self._failsafeTrippedPrevModeStr = None
            self._failsafeTempIsHighStartTs = None
            updFailsafeIndicator()
        self._failsafeCB.toggled.connect(onFailsafeCB)
        self._failsafeCB.setChecked(self._failsafeOn)

        failsafeBox = QtWidgets.QHBoxLayout()
        failsafeBox.addWidget(self._failsafeCB)
        failsafeBox.addWidget(self._limitTempGPU)
        failsafeBox.addWidget(self._limitTempCPU)
        failsafeBox.addWidget(failsafeIndicator)

        modeBox = QtWidgets.QHBoxLayout()
        modeBox.addWidget(self._modeSwitch, alignment= QtCore.Qt.AlignLeft)
        modeBox.addWidget(QtWidgets.QWidget(), alignment= QtCore.Qt.AlignRight) # Insert dummy Widget in order to move the following 'failsafeBox' to the right side
        modeBox.addLayout(failsafeBox)

        mainLayout = QtWidgets.QVBoxLayout(self)
        mainLayout.addLayout(lTherm)
        mainLayout.addWidget(self._tempGraph)
        mainLayout.addWidget(graphLabel, alignment=QtCore.Qt.AlignRight)
        mainLayout.addWidget(self._curveEditor)
        mainLayout.addWidget(curveLabel, alignment=QtCore.Qt.AlignRight)
        mainLayout.addLayout(modeBox)
        mainLayout.setAlignment(QtCore.Qt.AlignTop)
        mainLayout.setContentsMargins(12, 8, 12, 8)

        # Glue GUI to backend
        self.gModeHotKey = None
        self._updateGaugesTask = None

        def setFanSpeed(fan: Literal['GPU', 'CPU'], speed: int) -> None:
            res = self._awcc.setFanSpeed(self._awcc.GPUFanIdx if fan == 'GPU' else self._awcc.CPUFanIdx, speed)
            print(f'Set {fan} fan speed to {speed}: ' + ('ok' if res else 'fail'))

        self._lastAutoFanSpeed = {}      # 上次下发的自动曲线目标转速，用于去重
        def applyAutoFanCurve(gpuTemp = None, cpuTemp = None) -> None:
            """自动曲线模式：按当前温度查曲线得到风扇百分比并下发。"""
            if self._modeSwitch.getChecked() != ThermalMode.Auto.value:
                return
            if gpuTemp is None: gpuTemp = self._thermalGPU.getTemp()
            if cpuTemp is None: cpuTemp = self._thermalCPU.getTemp()
            # 同一秒内目标值没变就不再写 WMI：温度在拐点附近抖动时避免风扇反复变速
            for fan, speed in (('GPU', self._gpuCurve.speedAt(gpuTemp)), ('CPU', self._cpuCurve.speedAt(cpuTemp))):
                if speed is not None and speed != self._lastAutoFanSpeed.get(fan):
                    self._lastAutoFanSpeed[fan] = speed
                    setFanSpeed(fan, speed)

        def updateFanSpeed():
            if self._modeSwitch.getChecked() != ThermalMode.Custom.value:
                return
            setFanSpeed('GPU', self._thermalGPU.getSpeedSlider())
            setFanSpeed('CPU', self._thermalCPU.getSpeedSlider())
        self._thermalGPU.speedSliderChanged(updateFanSpeed)
        self._thermalCPU.speedSliderChanged(updateFanSpeed)

        def onModeChange(val: str):
            isAuto = val == ThermalMode.Auto.value
            self._thermalGPU.setSpeedDisabled(val != ThermalMode.Custom.value)
            self._thermalCPU.setSpeedDisabled(val != ThermalMode.Custom.value)
            self._curveEditor.setEnabled(isAuto)
            self._lastAutoFanSpeed.clear()        # 换档后让曲线重新压一遍目标转速
            res = self._awcc.setMode(UI_MODE_TO_BACKEND[val])   # Auto 借 Custom 档，风速由程序按曲线给
            print(f'Set mode {val}: ' + ('ok' if res else 'fail'))
            if not res:
                # 绝不能在这里退出：这一刻可能正是温度保护在抢救散热，程序消失等于放弃保护
                self._pendingMode = val
                alert("模式切换失败", f"切换到「{modeDisplayName(val)}」失败，程序会每秒自动重试。\n"
                      "常见原因：AWCC 服务还没就绪，或本程序没有管理员权限。",
                      QtWidgets.QMessageBox.Icon.Warning)
            else:
                self._pendingMode = None
            updateFanSpeed()
            if isAuto:
                applyAutoFanCurve()
            if val != ThermalMode.G_Mode.value:
                self._failsafeTrippedPrevModeStr = None # In case the mode was switched manually
            updFailsafeIndicator()
            for m in ThermalMode:
                self._trayMenuModeSwitch[m.value].setText(f"{'•' if m.value == val else ' '} {modeDisplayName(m.value)}")

        self._modeSwitch.setChecked(ThermalMode.Balanced.value)
        onModeChange(ThermalMode.Balanced.value)
        self._modeSwitch.setOnChange(onModeChange)

        def updateAppState():
            # Get temps and RPMs
            gpuTemp = self._awcc.getFanRelatedTemp(self._awcc.GPUFanIdx)
            gpuRPM = self._awcc.getFanRPM(self._awcc.GPUFanIdx)
            cpuTemp = self._awcc.getFanRelatedTemp(self._awcc.CPUFanIdx)
            cpuRPM = self._awcc.getFanRPM(self._awcc.CPUFanIdx)
            # 原始读数（可能是 None）。仪表盘显示的是上一次的旧值，提示文案要用原始值
            self._lastSensorTemps = (gpuTemp, cpuTemp)
            # 上一次切档失败的话先重试，成功了才做别的
            if self._pendingMode is not None:
                retry = self._pendingMode
                if self._awcc.setMode(UI_MODE_TO_BACKEND[retry]):
                    print(f'模式重试成功：{retry}')
                    self._pendingMode = None
            # Update UI gauges
            if gpuTemp is not None: self._thermalGPU.setTemp(gpuTemp)
            if gpuRPM is not None: self._thermalGPU.setFanRPM(gpuRPM)
            if cpuTemp is not None: self._thermalCPU.setTemp(cpuTemp)
            if cpuRPM is not None: self._thermalCPU.setFanRPM(cpuRPM)
            # Update temp history graph
            self._tempGraph.push(gpuTemp, cpuTemp)
            # 自动曲线模式：按温度查曲线自动调风扇
            if self._modeSwitch.getChecked() == ThermalMode.Auto.value:
                applyAutoFanCurve(gpuTemp, cpuTemp)
            # 曲线编辑器实时温度游标
            self._curveEditor.setCurrentTemps(gpuTemp, cpuTemp)
            # Write CSV log
            if self._tempLogger.enabled:
                self._tempLogger.log(gpuTemp, gpuRPM, cpuTemp, cpuRPM, modeDisplayName(self._modeSwitch.getChecked()))
            # print(gpuTemp, gpuRPM, cpuTemp, cpuRPM)

            # Handle fail-safe
            tempIsHigh = (
                (gpuTemp is None) or (gpuTemp >= self.FAILSAFE_GPU_TEMP) or
                (cpuTemp is None) or (cpuTemp >= self.FAILSAFE_CPU_TEMP)
            )

            if tempIsHigh:
                self._failsafeTempIsHighTs = time.time()

            self._failsafeTempIsHighStartTs = (self._failsafeTempIsHighStartTs or time.time()) if tempIsHigh else None

            # Trip fail-safe
            if (self._failsafeOn and
                self._modeSwitch.getChecked() != ThermalMode.G_Mode.value and
                tempIsHigh and
                time.time() - self._failsafeTempIsHighStartTs > self.FAILSAFE_TRIGGER_DELAY_SEC
            ):
                self._failsafeTrippedPrevModeStr = self._modeSwitch.getChecked()
                self._modeSwitch.setChecked(ThermalMode.G_Mode.value)
                self._toasterMessageCurrentMode(source='failsafe')
                print(f'Fail-safe tripped at GPU={gpuTemp} CPU={cpuTemp}')

            # Auto-reset failsafe
            if (self._failsafeTrippedPrevModeStr is not None and
                time.time() - self._failsafeTempIsHighTs > self.FAILSAFE_RESET_AFTER_TEMP_IS_OK_FOR_SEC
            ):
                self._modeSwitch.setChecked(self._failsafeTrippedPrevModeStr)
                self._toasterMessageCurrentMode(source='failsafe')
                self._failsafeTrippedPrevModeStr = None
                print('Fail-safe reset')

            # Update tray icon
            self.trayIcon = self.trayIcon.resizeForScreen() or self.trayIcon
            self.trayIcon.update((gpuTemp, cpuTemp), self._modeSwitch.getChecked() == ThermalMode.G_Mode.value)
            self.tray.setIcon(self.trayIcon)
            self.tray.setToolTip(f"GPU：{gpuTemp} °C，{gpuRPM} 转/分\nCPU：{cpuTemp} °C，{cpuRPM} 转/分\n模式：{modeDisplayName(self._modeSwitch.getChecked())}")

            # Periodically save app settings
            self._saveAppSettings()

        self._loadAppSettings()

        self._updateGaugesTask = QPeriodic(self, self.TEMP_UPD_PERIOD_MS, updateAppState)
        updateAppState()
        self._updateGaugesTask.start()

        self.gModeHotKey = HotKey.HotKey(HotKey.G_MODE_KEY, self._gModeKeySignal)
        self._gModeKeySignal.connect(self._onGModeHotKeyPressed)
        self.gModeHotKey.start()

        # 全局热键 Ctrl+Alt+T：显示 / 隐藏主窗口
        self._showHideHotKey = HotKey.HotKey(0x54, self._showHideKeySignal, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT) # 0x54 = 'T'
        self._showHideKeySignal.connect(self._onShowHideHotKeyPressed)
        self._showHideHotKey.start()

    def updateGaugeTitles(self, gpuModel, cpuModel):
        if gpuModel: self._thermalGPU.setTitle(gpuModel)
        if cpuModel: self._thermalCPU.setTitle(cpuModel)

    def closeEvent(self, event):
        minimizeOnClose = self.settings.value(SettingsKey.MinimizeOnCloseFlag.value)
        if minimizeOnClose is not None:
            minimizeOnClose = str(minimizeOnClose).lower() == 'true'

        if minimizeOnClose is None:
            # minimizeOnClose is not set, prompt user
            (toExit, dontAskAgain) = confirm("退出", "要退出程序，还是最小化到托盘继续运行？", ("退出", "最小化到托盘"), True)
            minimizeOnClose = not toExit
            if dontAskAgain:
                self.settings.setValue(SettingsKey.MinimizeOnCloseFlag.value, minimizeOnClose)

        if minimizeOnClose:
            event.ignore()
            self.hide()
        else:
            self.onExit()
        return

    # onExit() connected to systray_Exit
    def onExit(self):
        print("exit")
        # Set mode to Balanced before exit
        prevMode = self._modeSwitch.getChecked()
        self._modeSwitch.setChecked(ThermalMode.Balanced.value)
        if prevMode != ThermalMode.Balanced.value:
            self._toasterMessageCurrentMode()
        self._destroy()
        sys.exit(0)

    def _destroy(self):
        if self.gModeHotKey is not None:
            self.gModeHotKey.stop()
            self.gModeHotKey.wait()
        if hasattr(self, '_showHideHotKey') and self._showHideHotKey is not None:
            self._showHideHotKey.stop()
            self._showHideHotKey.wait()
        if self._updateGaugesTask is not None:
            self._updateGaugesTask.stop()
        print('Cleanup: done')

    def _onGModeHotKeyPressed(self):
        current = self._modeSwitch.getChecked()
        if current == ThermalMode.G_Mode.value:
            self._modeSwitch.setChecked(self._gModeKeyPrevModeStr or ThermalMode.Balanced.value)
        else:
            self._gModeKeyPrevModeStr = current
            self._modeSwitch.setChecked(ThermalMode.G_Mode.value)
        self._toasterMessageCurrentMode()

    def _onShowHideHotKeyPressed(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.activateWindow()
            self.raise_()

    def _sensorSummary(self) -> str:
        gpu, cpu = self._lastSensorTemps
        def one(name: str, v: Optional[int]) -> str:
            return f"{name}：无读数" if v is None else f"{name}：{v}°C"
        return f"{one('GPU', gpu)}，{one('CPU', cpu)}"

    def _toasterMessageCurrentMode(self, source: Optional[Literal['failsafe']] = None) -> None:
        sourceStr = " [温度保护]" if source == 'failsafe' else ""
        self.toasterMessage(
            [
                modeDisplayName(self._modeSwitch.getChecked()),
                self._sensorSummary(),
                "散热模式已切换" + sourceStr
            ],
            source != 'failsafe'
        )

    def toasterMessage(self, message: List[str | None], expire = True) -> None:
        toast = Toast(duration=ToastDuration.Short, expiration_time= (datetime.datetime.now() + datetime.timedelta(seconds=5)) if expire else None)
        toast.text_fields = message
        toast.AddImage(ToastDisplayImage.fromPath(resourcePath(GUI_ICON)))
        self._toaster.show_toast(toast)

    def _saveAppSettings(self):
        curValues = [
            self._modeSwitch.getChecked(),
            self._thermalCPU.getSpeedSlider(),
            self._thermalGPU.getSpeedSlider(),
            self.FAILSAFE_CPU_TEMP,
            self.FAILSAFE_GPU_TEMP,
            self._failsafeOn,
            self._tempLogger.enabled
        ]
        if curValues == self._prevSavedSettingsValues:
            return
        self._prevSavedSettingsValues = curValues

        self.settings.setValue(SettingsKey.Mode.value, self._modeSwitch.getChecked())
        self.settings.setValue(SettingsKey.CPUFanSpeed.value, self._thermalCPU.getSpeedSlider())
        self.settings.setValue(SettingsKey.GPUFanSpeed.value, self._thermalGPU.getSpeedSlider())
        self.settings.setValue(SettingsKey.CPUThresholdTemp.value, self.FAILSAFE_CPU_TEMP)
        self.settings.setValue(SettingsKey.GPUThresholdTemp.value, self.FAILSAFE_GPU_TEMP)
        self.settings.setValue(SettingsKey.FailSafeIsOnFlag.value, self._failsafeOn)
        self.settings.setValue(SettingsKey.LogEnabledFlag.value, self._tempLogger.enabled)

    def _loadAppSettings(self):
        savedMode = self.settings.value(SettingsKey.Mode.value) or ThermalMode.Balanced.value
        # 合法性校验：若读到未知模式（如旧版本残留脏数据），回退到 Balanced，防止 setChecked 崩溃
        validModes = [m.value for m in ThermalMode]
        if savedMode not in validModes:
            savedMode = ThermalMode.Balanced.value
        self._modeSwitch.setChecked(savedMode)
        savedSpeed = self.settings.value(SettingsKey.CPUFanSpeed.value)
        self._thermalCPU.setSpeedSlider(savedSpeed)
        savedSpeed = self.settings.value(SettingsKey.GPUFanSpeed.value)
        self._thermalGPU.setSpeedSlider(savedSpeed)
        savedTemp = self.settings.value(SettingsKey.CPUThresholdTemp.value) or self.__class__.DEFAULT_FAILSAFE_CPU_TEMP
        self._limitTempCPU.setCurrentText(str(savedTemp))
        savedTemp = self.settings.value(SettingsKey.GPUThresholdTemp.value) or self.__class__.DEFAULT_FAILSAFE_GPU_TEMP
        self._limitTempGPU.setCurrentText(str(savedTemp))
        savedFailsafe = self.settings.value(SettingsKey.FailSafeIsOnFlag.value) or 'true'
        self._failsafeCB.setChecked(str(savedFailsafe).lower() == 'true')

    def clearAppSettings(self):
        (isYes, _) = confirm("恢复默认设置", "确定要将所有设置（含风扇曲线）恢复为默认值吗？", ("恢复默认", "取消"))
        if not isYes: return
        self.settings.clear()
        self._gpuCurve.setPoints(FanCurve.DEFAULT_GPU)
        self._cpuCurve.setPoints(FanCurve.DEFAULT_CPU)
        self._curveEditor.update()
        self._loadAppSettings()

def runApp(startMinimized = False) -> int:
    app = QtWidgets.QApplication([])
    # 关键：关闭/隐藏最后窗口时不要退出程序（保持托盘运行），否则 --minimized 启动后 hide() 会直接退出
    app.setQuitOnLastWindowClosed(False)

    # 风扇控制要写戴尔的 WMI 方法，没有管理员权限就是读得到、控不了
    if not isElevated():
        (toRelaunch, _) = confirm(
            "需要管理员权限",
            "当前以普通用户权限运行，无法控制风扇（温度保护也会失效）。",
            ("以管理员身份重启", "仍以普通权限运行"), False)
        if toRelaunch and relaunchElevated():
            return 0

    # Setup backend
    try:
        awcc = AWCCThermal()
    except NoAWCCWMIClass:
        errorExit("系统中未找到 AWCC WMI 类。", "可能未安装相关驱动，或您的机型不受支持。")
    except CannotInstAWCCWMI:
        errorExit("无法实例化 AWCC WMI 类。", "请以管理员身份运行本程序（右键 → 以管理员身份运行）。")

    mainWindow = TCC_GUI(awcc)
    mainWindow.setStyleSheet(f"""
        QGauge {{
            border: 1px solid {Colors.GREY.value};
            border-radius: 6px;
            background-color: {Colors.DARK_GREY.value};
            text-align: center;
        }}
        QGauge::chunk {{
            background-color: {Colors.BLUE.value};
            border-radius: 5px;
        }}
        * {{
            color: {Colors.WHITE.value};
            background-color: {Colors.DARK_BG.value};
            font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
        }}
        QToolTip {{
            background-color: {Colors.DARK_GREY.value};
            color: {Colors.WHITE.value};
            border: 1px solid {Colors.GREY.value};
            border-radius: 4px;
            padding: 4px;
        }}
        QRadioButton {{
            spacing: 6px;
            padding: 2px 4px;
        }}
        QRadioButton::indicator {{
            width: 14px;
            height: 14px;
            border-radius: 7px;
            border: 1px solid {Colors.GREY.value};
            background: {Colors.DARK_GREY.value};
        }}
        QRadioButton::indicator:checked {{
            border: 4px solid {Colors.BLUE.value};
            background: {Colors.WHITE.value};
        }}
        QRadioButton::indicator:hover {{
            border-color: {Colors.BLUE.value};
        }}
        QCheckBox {{
            spacing: 6px;
        }}
        QCheckBox::indicator {{
            width: 14px;
            height: 14px;
            border-radius: 3px;
            border: 1px solid {Colors.GREY.value};
            background: {Colors.DARK_GREY.value};
        }}
        QCheckBox::indicator:checked {{
            background: {Colors.BLUE.value};
            border-color: {Colors.BLUE.value};
        }}
        QSlider {{
            min-height: 22px;
        }}
        QSlider::groove:horizontal {{
            height: 5px;
            border-radius: 2px;
            background: {Colors.GREY.value};
        }}
        QSlider::sub-page:horizontal {{
            background: {Colors.BLUE.value};
            border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            width: 14px;
            height: 14px;
            margin: -5px 0;
            border-radius: 7px;
            background: {Colors.WHITE.value};
        }}
        QSlider::handle:horizontal:hover {{
            background: {Colors.BLUE.value};
        }}
        QSlider::handle:horizontal:disabled {{
            background: {Colors.GREY.value};
        }}
        QComboBox {{
            border: 1px solid {Colors.GREY.value};
            border-radius: 5px;
            padding: 2px 8px;
            background-color: {Colors.DARK_GREY.value};
        }}
        QComboBox:hover {{
            border-color: {Colors.BLUE.value};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox::disabled {{
            color: {Colors.GREY.value};
        }}
        QComboBox QAbstractItemView {{
            background-color: {Colors.DARK_GREY.value};
            border: 1px solid {Colors.GREY.value};
            selection-background-color: {Colors.BLUE.value};
        }}
        QMenu {{
            background-color: {Colors.DARK_GREY.value};
            border: 1px solid {Colors.GREY.value};
            border-radius: 6px;
            padding: 4px;
        }}
        QMenu::item {{
            padding: 5px 24px;
            border-radius: 4px;
        }}
        QMenu::item:selected {{
            background-color: {Colors.BLUE.value};
        }}
        QMenu::separator {{
            height: 1px;
            background: {Colors.GREY.value};
            margin: 4px 8px;
        }}
        QMessageBox {{
            background-color: {Colors.DARK_GREY.value};
        }}
    """)

    if startMinimized:
        # 开机自启：不显示主窗口，直接驻留托盘（配合 setQuitOnLastWindowClosed(False) 不会退出）
        mainWindow.hide()
    else:
        mainWindow.show()

    return app.exec()
