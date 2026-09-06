# -*- coding: utf-8 -*-
# 温度历史曲线组件：QPainter 自绘，显示最近 N 个采样点的 GPU / CPU 温度走势

import collections
from typing import Optional
from PySide6 import QtCore, QtGui, QtWidgets


class TempHistoryGraph(QtWidgets.QWidget):
    """轻量温度走势图（无第三方依赖）。

    - dataPoints: 保留的采样点数量（每秒 1 个点，300 点 = 5 分钟）
    - 两条曲线：GPU（绿色）、CPU（蓝色）
    - 自动根据历史最大/最小温度缩放纵轴
    """

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        dataPoints: int = 300,
        yMin: int = 20,
        yMax: int = 100,
    ):
        super().__init__(parent)
        self._n = dataPoints
        self._gpuData = collections.deque(maxlen=dataPoints)
        self._cpuData = collections.deque(maxlen=dataPoints)
        self._yMin = yMin
        self._yMax = yMax
        self.setMinimumHeight(110)
        self.setMouseTracking(True)
        self.setToolTip("温度走势（最近 5 分钟）")

        self._colorGpu = QtGui.QColor("#34d17d")   # GPU 绿
        self._colorCpu = QtGui.QColor("#4da3ff")   # CPU 蓝
        self._colorGrid = QtGui.QColor(255, 255, 255, 26)
        self._colorText = QtGui.QColor("#9aa4b2")
        self._colorFillGpu = QtGui.QColor(52, 209, 125, 46)
        self._colorFillCpu = QtGui.QColor(77, 163, 255, 46)

    # ---------- 数据接口 ----------

    def push(self, gpuTemp: Optional[int], cpuTemp: Optional[int]) -> None:
        """追加一个采样点。None 值以 NaN 形式跳过绘制。"""
        self._gpuData.append(gpuTemp)
        self._cpuData.append(cpuTemp)
        self.update()

    def clear(self) -> None:
        self._gpuData.clear()
        self._cpuData.clear()
        self.update()

    # ---------- 绘制 ----------

    def _iterPolyline(self, data) -> Optional[QtGui.QPolygonF]:
        """把采样点序列转换为坐标折线。数据不足 2 点时返回 None。"""
        if len(data) < 2:
            return None
        w = self.width()
        h = self.height()
        topPad = 10.0
        bottomPad = 14.0
        plotH = h - topPad - bottomPad
        if plotH <= 0 or w <= 0:
            return None

        yMin, yMax = self._yMin, self._yMax
        # 数据驱动的纵轴：留 5°C 余量并至少显示 30°C 区间
        valid = [v for v in data if v is not None]
        if valid:
            lo = max(yMin, min(valid) - 5)
            hi = max(yMax, max(valid) + 5) if max(valid) + 5 - lo >= 30 else lo + 30
        else:
            lo, hi = yMin, yMax
        span = max(1, hi - lo)

        poly = QtGui.QPolygonF()
        stepX = w / max(1, (self._n - 1))
        n = len(data)
        # 让曲线从右侧推入（最新点在最右）
        for i, v in enumerate(data):
            x = w - (n - 1 - i) * stepX
            if v is None:
                continue
            y = topPad + plotH * (1.0 - (min(max(v, lo), hi) - lo) / span)
            poly.append(QtCore.QPointF(x, y))
        if poly.size() < 2:
            return None
        return poly

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # 背景
        painter.fillRect(0, 0, w, h, QtGui.QColor("#1b2330"))

        # 水平网格线 + 刻度文字
        painter.setPen(self._colorGrid)
        font = QtGui.QFont(self.font().family(), 8)
        painter.setFont(font)
        topPad, bottomPad = 10.0, 14.0
        plotH = h - topPad - bottomPad
        for i in range(5):
            y = topPad + plotH * i / 4
            painter.drawLine(0, int(y), w, int(y))
        # 纵轴刻度（按当前数据范围）
        valid = [v for v in list(self._gpuData) + list(self._cpuData) if v is not None]
        if valid:
            lo = max(self._yMin, min(valid) - 5)
            hi = max(self._yMax, max(valid) + 5) if max(valid) + 5 - lo >= 30 else lo + 30
            span = max(1, hi - lo)
            painter.setPen(QtGui.QPen(self._colorText))
            for i in range(5):
                y = topPad + plotH * i / 4
                t = hi - span * i / 4
                painter.drawText(QtCore.QRectF(w - 34, y - 7, 32, 14),
                                 QtCore.Qt.AlignRight, f"{t:.0f}°")

        # 曲线（先画填充再画描边）
        for data, colorLine, colorFill in (
            (self._gpuData, self._colorGpu, self._colorFillGpu),
            (self._cpuData, self._colorCpu, self._colorFillCpu),
        ):
            poly = self._iterPolyline(data)
            if poly is None:
                continue
            # 渐变填充
            fill = QtGui.QPolygonF(poly)
            bottomY = float(h - bottomPad)
            fill.append(QtCore.QPointF(fill.last().x(), bottomY))
            fill.append(QtCore.QPointF(fill.first().x(), bottomY))
            grad = QtGui.QLinearGradient(0, topPad, 0, bottomY)
            cTop = QtGui.QColor(colorFill)
            cTop.setAlpha(90)
            cBottom = QtGui.QColor(colorFill)
            cBottom.setAlpha(0)
            grad.setColorAt(0.0, cTop)
            grad.setColorAt(1.0, cBottom)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(grad)
            painter.drawPolygon(fill)
            # 描边
            painter.setPen(QtGui.QPen(colorLine, 1.6))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawPolyline(poly)

        # 图例（左上角）
        painter.setPen(QtCore.Qt.NoPen)
        lg = [("", self._colorGpu, None, None), ("", self._colorCpu, None, None)]
        # 取当前最新值显示
        gpuCur = next((v for v in reversed(list(self._gpuData)) if v is not None), None)
        cpuCur = next((v for v in reversed(list(self._cpuData)) if v is not None), None)
        lg = [
            (f"GPU {gpuCur}°C" if gpuCur is not None else "GPU --", self._colorGpu),
            (f"CPU {cpuCur}°C" if cpuCur is not None else "CPU --", self._colorCpu),
        ]
        x0 = 8.0
        for text, color in lg:
            painter.setBrush(color)
            painter.drawRoundedRect(QtCore.QRectF(x0, 4, 8, 8), 2, 2)
            painter.setPen(QtGui.QPen(self._colorText))
            painter.drawText(QtCore.QRectF(x0 + 11, 0, 80, 16), QtCore.Qt.AlignLeft, text)
            x0 += 11 + 8 + painter.fontMetrics().horizontalAdvance(text) + 12
        painter.end()
