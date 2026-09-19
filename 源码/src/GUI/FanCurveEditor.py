# -*- coding: utf-8 -*-
# 风扇曲线编辑器：QPainter 自绘，可拖拽控制点，GPU / CPU 双曲线
#
# 交互：
#   - 左键按住控制点拖动 → 改温度 / 风速
#   - 双击空白处 → 添加控制点
#   - 双击控制点 → 删除（至少保留 2 个）
#   - 左上角 GPU / CPU 按钮切换编辑对象

from typing import Callable, Optional
from PySide6 import QtCore, QtGui, QtWidgets

from Backend.FanCurve import FanCurve
from GUI.AppColors import Colors


class FanCurveEditor(QtWidgets.QWidget):
    """可拖拽的温度-风速曲线编辑器。

    - gpuCurve / cpuCurve: FanCurve 实例（外部持有并持久化）
    - onChanged(curveKind): 曲线被修改后回调，curveKind 为 'GPU' / 'CPU'
    - setCurrentTemps(gpuTemp, cpuTemp): 每秒刷新实时温度游标
    """

    RADIUS = 5          # 控制点半径
    RADIUS_HOVER = 7    # 悬停/拖拽时的半径
    PAD_L = 34.0        # 左边距（风速刻度）
    PAD_R = 10.0
    PAD_T = 26.0        # 顶边距（GPU/CPU 切换按钮）
    PAD_B = 20.0        # 底边距（温度刻度）

    def __init__(self, parent: Optional[QtWidgets.QWidget], gpuCurve: FanCurve, cpuCurve: FanCurve,
                 onChanged: Optional[Callable[[str], None]] = None):
        super().__init__(parent)
        self._gpuCurve = gpuCurve
        self._cpuCurve = cpuCurve
        self._onChanged = onChanged
        self._editing = 'GPU'            # 当前编辑哪条曲线
        self._dragIdx: Optional[int] = None
        self._hoverIdx: Optional[int] = None
        self._gpuTemp: Optional[int] = None
        self._cpuTemp: Optional[int] = None
        self.setMinimumHeight(200)
        self.setMouseTracking(True)
        self.setToolTip("拖动圆点调整曲线；双击空白处加点，双击圆点删点")

        # 配色统一取自 AppColors
        self._colorGpu = QtGui.QColor(Colors.GREEN.value)
        self._colorCpu = QtGui.QColor(Colors.BLUE.value)
        self._colorGrid = QtGui.QColor(255, 255, 255, 26)
        self._colorText = QtGui.QColor(Colors.TEXT_DIM.value)
        self._colorBg = QtGui.QColor(Colors.DARK_BG.value)

        # GPU / CPU 切换按钮
        self._btnGpu = QtWidgets.QPushButton("GPU", self)
        self._btnCpu = QtWidgets.QPushButton("CPU", self)
        for b in (self._btnGpu, self._btnCpu):
            b.setFixedHeight(18)
            b.setCheckable(True)
            b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setStyleSheet(f"""
                QPushButton {{
                    color: {Colors.WHITE.value}; background: {Colors.DARK_GREY.value};
                    border: 1px solid {Colors.GREY.value}; border-radius: 4px;
                    padding: 0 10px; font-size: 11px;
                }}
                QPushButton:checked {{ background: {Colors.BLUE.value}; border-color: {Colors.BLUE.value}; }}
            """)
        self._btnGpu.clicked.connect(lambda: self._setEditing('GPU'))
        self._btnCpu.clicked.connect(lambda: self._setEditing('CPU'))
        self._setEditing('GPU')

    # ---------- 对外接口 ----------

    def setCurrentTemps(self, gpuTemp: Optional[int], cpuTemp: Optional[int]) -> None:
        self._gpuTemp = gpuTemp
        self._cpuTemp = cpuTemp
        self.update()

    # ---------- 内部 ----------

    def _curve(self) -> FanCurve:
        return self._gpuCurve if self._editing == 'GPU' else self._cpuCurve

    def _color(self) -> QtGui.QColor:
        return self._colorGpu if self._editing == 'GPU' else self._colorCpu

    def _curTemp(self) -> Optional[int]:
        return self._gpuTemp if self._editing == 'GPU' else self._cpuTemp

    def _setEditing(self, which: str) -> None:
        self._editing = which
        self._btnGpu.setChecked(which == 'GPU')
        self._btnCpu.setChecked(which == 'CPU')
        self._hoverIdx = None
        self.update()

    def _plotRect(self) -> QtCore.QRectF:
        return QtCore.QRectF(self.PAD_L, self.PAD_T,
                             self.width() - self.PAD_L - self.PAD_R,
                             self.height() - self.PAD_T - self.PAD_B)

    def _tempToX(self, t: int) -> float:
        r = self._plotRect()
        return r.left() + r.width() * (t - FanCurve.TEMP_MIN) / (FanCurve.TEMP_MAX - FanCurve.TEMP_MIN)

    def _speedToY(self, s: int) -> float:
        r = self._plotRect()
        return r.bottom() - r.height() * s / 100.0

    def _xToTemp(self, x: float) -> int:
        r = self._plotRect()
        t = FanCurve.TEMP_MIN + (x - r.left()) / r.width() * (FanCurve.TEMP_MAX - FanCurve.TEMP_MIN)
        return max(FanCurve.TEMP_MIN, min(FanCurve.TEMP_MAX, round(t)))

    def _yToSpeed(self, y: float) -> int:
        r = self._plotRect()
        s = (r.bottom() - y) / r.height() * 100.0
        return max(0, min(100, round(s)))

    def _pointAt(self, idx: int) -> QtCore.QPointF:
        t, s = self._curve().getPoints()[idx]
        return QtCore.QPointF(self._tempToX(t), self._speedToY(s))

    def _hitTest(self, pos: QtCore.QPointF) -> Optional[int]:
        for i in range(len(self._curve().getPoints())):
            if (self._pointAt(i) - pos).manhattanLength() <= self.RADIUS_HOVER + 2:
                return i
        return None

    # ---------- 事件 ----------

    def mousePressEvent(self, e: QtGui.QMouseEvent) -> None:
        if not self.isEnabled():
            return
        pos = e.position()
        idx = self._hitTest(pos)
        if e.button() == QtCore.Qt.LeftButton and idx is not None:
            self._dragIdx = idx

    def mouseMoveEvent(self, e: QtGui.QMouseEvent) -> None:
        if not self.isEnabled():
            return
        pos = e.position()
        if self._dragIdx is not None:
            self._curve().updatePoint(self._dragIdx, self._xToTemp(pos.x()), self._yToSpeed(pos.y()))
            self.update()     # 只重绘。回调里会写注册表并下发风扇，放这里等于一次拖动几百次 WMI 写
        else:
            idx = self._hitTest(pos)
            if idx != self._hoverIdx:
                self._hoverIdx = idx
                self.update()

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent) -> None:
        if self._dragIdx is not None:
            self._dragIdx = None
            self.update()
            if self._onChanged:
                self._onChanged(self._editing)

    def mouseDoubleClickEvent(self, e: QtGui.QMouseEvent) -> None:
        if not self.isEnabled() or e.button() != QtCore.Qt.LeftButton:
            return
        pos = e.position()
        idx = self._hitTest(pos)
        if idx is not None:
            if self._curve().removePoint(idx) and self._onChanged:
                self._onChanged(self._editing)
        else:
            if self._plotRect().contains(pos):
                if self._curve().addPoint(self._xToTemp(pos.x()), self._yToSpeed(pos.y())) and self._onChanged:
                    self._onChanged(self._editing)
        self.update()

    def resizeEvent(self, e: QtGui.QResizeEvent) -> None:
        self._btnGpu.move(6, 3)
        self._btnCpu.move(6 + self._btnGpu.width() + 6, 3)
        super().resizeEvent(e)

    # ---------- 绘制 ----------

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        r = self._plotRect()

        # 背景
        painter.fillRect(0, 0, self.width(), self.height(), self._colorBg)
        painter.fillRect(r, QtGui.QColor(Colors.DARK_GREY.value))
        painter.setPen(QtGui.QPen(self._colorGrid))
        painter.drawRect(r.adjusted(0, 0, -1, -1))

        # 网格 + 刻度
        font = QtGui.QFont(self.font().family(), 8)
        painter.setFont(font)
        painter.setPen(QtGui.QPen(self._colorText))
        for t in range(FanCurve.TEMP_MIN, FanCurve.TEMP_MAX + 1, 10):  # 温度刻度
            x = self._tempToX(t)
            painter.setPen(QtGui.QPen(self._colorGrid))
            painter.drawLine(QtCore.QPointF(x, r.top()), QtCore.QPointF(x, r.bottom()))
            painter.setPen(QtGui.QPen(self._colorText))
            painter.drawText(QtCore.QRectF(x - 16, r.bottom() + 2, 32, 12), QtCore.Qt.AlignCenter, f"{t}°")
        for s in range(0, 101, 25):  # 风速刻度
            y = self._speedToY(s)
            painter.setPen(QtGui.QPen(self._colorGrid))
            painter.drawLine(QtCore.QPointF(r.left(), y), QtCore.QPointF(r.right(), y))
            painter.setPen(QtGui.QPen(self._colorText))
            painter.drawText(QtCore.QRectF(0, y - 6, self.PAD_L - 6, 12), QtCore.Qt.AlignRight, f"{s}%")

        # 另一条曲线（非编辑对象）画成暗色参考线
        other = self._cpuCurve if self._editing == 'GPU' else self._gpuCurve
        otherColor = self._colorCpu if self._editing == 'GPU' else self._colorGpu
        pts = other.getPoints()
        if len(pts) >= 2:
            poly = QtGui.QPolygonF([QtCore.QPointF(self._tempToX(t), self._speedToY(s)) for t, s in pts])
            painter.setPen(QtGui.QPen(otherColor.darker(220), 1.2, QtCore.Qt.DashLine))
            painter.drawPolyline(poly)

        # 当前编辑曲线
        curve = self._curve()
        color = self._color()
        pts = curve.getPoints()
        if len(pts) >= 2:
            poly = QtGui.QPolygonF([QtCore.QPointF(self._tempToX(t), self._speedToY(s)) for t, s in pts])
            # 填充
            fill = QtGui.QPolygonF(poly)
            fill.append(QtCore.QPointF(fill.last().x(), r.bottom()))
            fill.append(QtCore.QPointF(fill.first().x(), r.bottom()))
            grad = QtGui.QLinearGradient(0, r.top(), 0, r.bottom())
            cTop = QtGui.QColor(color); cTop.setAlpha(80)
            cBot = QtGui.QColor(color); cBot.setAlpha(0)
            grad.setColorAt(0.0, cTop)
            grad.setColorAt(1.0, cBot)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(grad)
            painter.drawPolygon(fill)
            # 描边
            painter.setPen(QtGui.QPen(color, 1.8))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawPolyline(poly)

        # 实时温度游标
        cur = self._curTemp()
        if cur is not None:
            x = self._tempToX(max(FanCurve.TEMP_MIN, min(FanCurve.TEMP_MAX, cur)))
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 120), 1, QtCore.Qt.DotLine))
            painter.drawLine(QtCore.QPointF(x, r.top()), QtCore.QPointF(x, r.bottom()))
            sp = curve.speedAt(cur)
            if sp is not None:
                painter.setBrush(color)
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawEllipse(QtCore.QPointF(x, self._speedToY(sp)), 3, 3)
                painter.setPen(QtGui.QPen(self._colorText))
                painter.drawText(QtCore.QRectF(x + 4, r.top() + 2, 60, 14), QtCore.Qt.AlignLeft,
                                 f"{cur}°C → {sp}%")

        # 控制点
        for i, (t, s) in enumerate(pts):
            c = self._pointAt(i)
            radius = self.RADIUS_HOVER if (i == self._hoverIdx or i == self._dragIdx) else self.RADIUS
            painter.setBrush(color)
            painter.setPen(QtGui.QPen(self._colorBg, 1.5))
            painter.drawEllipse(c, radius, radius)

        painter.end()
