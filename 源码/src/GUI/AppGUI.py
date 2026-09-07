import sys, os, time, datetime
from enum import Enum
from typing import Callable, Literal, Optional, Tuple, List
from PySide6 import QtCore, QtGui, QtWidgets
from windows_toasts import WindowsToaster, Toast, ToastDuration, ToastDisplayImage
from Backend.AWCCThermal import AWCCThermal, NoAWCCWMIClass, CannotInstAWCCWMI
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

def resourcePath(relativePath: str = '.'):
    return os.path.join(sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.abspath('.'), relativePath)

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

def autorunTask(action: Literal['add', 'remove']) -> int:
    """开机自启：写入/删除注册表 HKCU\\...\\Run 键。

    改为注册表方案（替代原 schtasks+xml），原因：
    1. 原方案依赖外部 tcc_g15_task.xml，便携版打包时容易漏掉；
    2. xml 方案需在运行时改写临时目录（sys._MEIPASS 只读），打包后必然失败；
    3. 注册表 Run 键无需外部文件、无需管理员权限（HKCU）、对便携版最可靠。
    """
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    VALUE_NAME = "TCC_G15"
    exeFile = appExePath()

    try:
        import winreg
    except ImportError:
        return -1

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                             winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
    except OSError:
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY)
        except OSError:
            return -2

    try:
        if action == 'add':
            if not exeFile.lower().endswith('.exe'):
                return -100
            # 用引号包裹路径，防止路径含空格时失效；--minimized 启动后最小化到托盘
            cmd = f'"{exeFile}" --minimized'
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass  # 本来就没有，忽略
        return 0
    finally:
        winreg.CloseKey(key)

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
    FAILSAFE_CPU_TEMP = 95
    FAILSAFE_GPU_TEMP = 85
    FAILSAFE_TRIGGER_DELAY_SEC = 8
    FAILSAFE_RESET_AFTER_TEMP_IS_OK_FOR_SEC = 60
    APP_NAME = "G15 温控中心"
    APP_VERSION = "1.7.0-cn"
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
        def autorunTaskRun(action: Literal['add', 'remove']) -> None:
            err = autorunTask(action)
            if err != 0 and action == 'add':
                alert("错误", f"{'添加' if action == 'add' else '移除'}自启任务失败，错误码 {err}", QtWidgets.QMessageBox.Icon.Critical)
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
        self._limitTempGPU.currentIndexChanged.connect(onLimitGPUChange)
        def onLimitCPUChange():
            val = self._limitTempCPU.currentText()
            if val.isdigit(): self.FAILSAFE_CPU_TEMP = int(val)
        self._limitTempCPU.currentIndexChanged.connect(onLimitCPUChange)

        # Fail-safe checkbox
        self._failsafeCB = QtWidgets.QCheckBox("温度保护")
        self._failsafeCB.setToolTip(f"当 GPU 温度达到 {self.FAILSAFE_GPU_TEMP}°C 或 CPU 温度达到 {self.FAILSAFE_CPU_TEMP}°C 时，自动切换到性能模式（风扇全速）")
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

        def applyAutoFanCurve(gpuTemp = None, cpuTemp = None) -> None:
            """自动曲线模式：按当前温度查曲线得到风扇百分比并下发。"""
            if self._modeSwitch.getChecked() != ThermalMode.Auto.value:
                return
            if gpuTemp is None: gpuTemp = self._thermalGPU.getTemp()
            if cpuTemp is None: cpuTemp = self._thermalCPU.getTemp()
            gpuSpeed = self._gpuCurve.speedAt(gpuTemp)
            cpuSpeed = self._cpuCurve.speedAt(cpuTemp)
            if gpuSpeed is not None: setFanSpeed('GPU', gpuSpeed)
            if cpuSpeed is not None: setFanSpeed('CPU', cpuSpeed)

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
            # 自动曲线模式底层使用 Custom（手动）档，风速由程序按曲线控制
            backendModeName = ThermalMode.Custom.value if isAuto else val
            res = self._awcc.setMode(self._awcc.Mode[backendModeName])
            print(f'Set mode {val}: ' + ('ok' if res else 'fail'))
            if not res:
                self._errorExit(f"模式切换失败：{modeDisplayName(val)}", "程序即将退出")
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

    def _errorExit(self, message: str, message2: Optional[str] = None) -> None:
        self._destroy()
        errorExit(message, message2)

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

    def _toasterMessageCurrentMode(self, source: Optional[Literal['failsafe']] = None) -> None:
        sourceStr = " [温度保护]" if source == 'failsafe' else ""
        self.toasterMessage(
            [
                modeDisplayName(self._modeSwitch.getChecked()),
                f"GPU：{self._thermalGPU.getTemp()}°C，CPU：{self._thermalCPU.getTemp()}°C",
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
        savedTemp = self.settings.value(SettingsKey.CPUThresholdTemp.value) or 95
        self._limitTempCPU.setCurrentText(str(savedTemp))
        savedTemp = self.settings.value(SettingsKey.GPUThresholdTemp.value) or 85
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

    def G_Mode_key_Pressed(self, val):
        print("G_Mode_key " + str(val))

def runApp(startMinimized = False) -> int:
    app = QtWidgets.QApplication([])
    # 关键：关闭/隐藏最后窗口时不要退出程序（保持托盘运行），否则 --minimized 启动后 hide() 会直接退出
    app.setQuitOnLastWindowClosed(False)

    # Setup backend
    try:
        awcc = AWCCThermal()
    except NoAWCCWMIClass:
        errorExit("系统中未找到 AWCC WMI 类。", "可能未安装相关驱动，或您的机型不受支持。")
    except CannotInstAWCCWMI:
        errorExit("无法实例化 AWCC WMI 类。", "请确保以管理员身份运行本程序。")

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
