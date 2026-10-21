from typing import Callable, Optional, Tuple
from PySide6 import QtCore, QtWidgets
from GUI.QGauge import QGauge
from GUI.AppColors import Colors

class ThermalUnitWidget(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget], tempMinMax: Tuple[int,int], tempColorLimits: Optional[Tuple[int,int]], fanMinMax: Tuple[int,int], sliderMaxAndTick: Tuple[int,int]):
        super().__init__(parent)

        self._title = QtWidgets.QLabel(self)
        self._title.hide()
        self._subTitle = QtWidgets.QLabel(self)
        self._subTitle.hide()
        self._subTitle.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._subTitle.setToolTip("三击左击选中后 Ctrl+C 可复制")

        self._tempBar, _tempBarLabel = self._makeGaugeWithLabel(tempMinMax, ' °C', tempColorLimits)

        self._fanBar, _fanBarLabel = self._makeGaugeWithLabel(fanMinMax, ' RPM')

        self._speedSliderCallback = None
        self._speedSlider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, self)
        self._speedSlider.setMaximum(sliderMaxAndTick[0])
        self._speedSlider.setTickInterval(sliderMaxAndTick[1])
        self._speedSlider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        _speedSliderLabel = QtWidgets.QLabel("风扇转速")
        self._speedSliderDebounce = QtCore.QTimer()
        self._speedSliderDebounce.setInterval(500)
        self._speedSliderDebounce.setSingleShot(True)
        self._speedSliderDebounce.timeout.connect(self._onSpeedSliderChange)
        self._speedSlider.valueChanged.connect(lambda: self._speedSliderDebounce.start())

        # 智控模式的目标温度：拖它就是在告诉 PID「把温度稳在这儿」。
        # 风扇转速由算法自己算，所以这条滑条和上面那条是互斥的两套控制方式。
        self._targetSlider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal, self)
        self._targetSlider.setMinimum(55)
        self._targetSlider.setMaximum(90)
        self._targetSlider.setTickInterval(5)
        self._targetSlider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self._targetSlider.setValue(73)
        self._targetSlider.setToolTip('智控模式下希望稳定到的温度')
        self._targetLabel = QtWidgets.QLabel('目标温度 73 °C')
        self._targetCallback = None
        self._targetSyncing = False
        self._targetDebounce = QtCore.QTimer()
        self._targetDebounce.setInterval(300)
        self._targetDebounce.setSingleShot(True)
        self._targetDebounce.timeout.connect(self._onTargetChange)
        self._targetSlider.valueChanged.connect(self._onTargetSliderMove)
        
        grid = QtWidgets.QGridLayout() # type: QtWidgets.QWidget
        grid.addWidget(self._title,         0, 0, QtCore.Qt.AlignCenter)
        grid.addWidget(self._subTitle,      1, 0, 1, 2, QtCore.Qt.AlignLeft)
        grid.addWidget(self._tempBar,       2, 0, QtCore.Qt.AlignTop)
        grid.addWidget(_tempBarLabel,       2, 1, QtCore.Qt.AlignLeft)
        grid.addWidget(self._fanBar,        3, 0, QtCore.Qt.AlignTop)
        grid.addWidget(_fanBarLabel,        3, 1, QtCore.Qt.AlignLeft)
        grid.addWidget(self._speedSlider,   4, 0, QtCore.Qt.AlignTop)
        grid.addWidget(_speedSliderLabel,   4, 1, QtCore.Qt.AlignLeft)
        grid.addWidget(self._targetSlider,  5, 0, QtCore.Qt.AlignTop)
        grid.addWidget(self._targetLabel,   5, 1, QtCore.Qt.AlignLeft)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 0)
        self.setLayout(grid)

    def _makeGaugeWithLabel(self, minMax: Tuple[int,int], units: str, colorLimits: Optional[Tuple[int,int]] = None) -> Tuple[QGauge, QtWidgets.QLabel]:
        g = QGauge()
        g.setTextVisible(False)
        g.setMinimum(minMax[0])
        g.setMaximum(minMax[1])
        if colorLimits:
            g.setColorScheme({colorLimits[0]: Colors.GREEN.value, colorLimits[1]: Colors.YELLOW.value, minMax[1]: Colors.RED.value})
        g.setFormat(f'%v{units}')
        return (g, g.createLabel())
    
    def setTitle(self, title: str) -> None:
        if len(title) < 10:
            self._title.setText(title)
            self._subTitle.hide()
            self._title.show()
        else:
            self._subTitle.setText(title)
            self._title.hide()
            self._subTitle.show()

    def setTemp(self, temp: int) -> None:
        self._tempBar.setValue(temp)

    def getTemp(self) -> int:
        return self._tempBar.value()

    def setFanRPM(self, rpm: int) -> None:
        self._fanBar.setValue(rpm)

    def speedSliderChanged(self, callback: Callable) -> None:
        self._speedSliderCallback = callback

    def setSpeedDisabled(self, disabled: bool) -> None:
        self._speedSlider.setDisabled(disabled)

    def getSpeedSlider(self) -> int:
        return self._speedSlider.value()

    def setSpeedSlider(self, value: Optional[int] = None) -> None:
        if value is None: value = (self._speedSlider.minimum() + self._speedSlider.maximum()) // 2
        if value < self._speedSlider.minimum(): value = self._speedSlider.minimum()
        if value > self._speedSlider.maximum(): value = self._speedSlider.maximum()
        self._speedSlider.setValue(value)

    def targetTempChanged(self, callback: Callable) -> None:
        self._targetCallback = callback

    def getTargetTemp(self) -> int:
        return self._targetSlider.value()

    def setTargetTemp(self, value: Optional[int] = None) -> None:
        if value is None:
            return
        v = max(self._targetSlider.minimum(),
                min(self._targetSlider.maximum(), int(round(value))))
        self._targetSyncing = True
        self._targetSlider.setValue(v)
        self._targetSyncing = False
        self._targetLabel.setText(f'目标温度 {v} °C')

    def setTargetDisabled(self, disabled: bool) -> None:
        self._targetSlider.setDisabled(disabled)
        self._targetLabel.setDisabled(disabled)

    @QtCore.Slot()
    def _onTargetSliderMove(self) -> None:
        self._targetLabel.setText(f'目标温度 {self._targetSlider.value()} °C')
        if not self._targetSyncing:
            self._targetDebounce.start()

    @QtCore.Slot()
    def _onTargetChange(self) -> None:
        if self._targetCallback:
            self._targetCallback()

    @QtCore.Slot()
    def _onSpeedSliderChange(self) -> None:
        if self._speedSliderCallback:
            self._speedSliderCallback()
