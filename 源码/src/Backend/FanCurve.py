# -*- coding: utf-8 -*-
# 风扇曲线模型：温度(°C) → 风速(%) 的分段线性插值，支持 JSON 序列化

import json
from typing import List, Optional, Tuple

Point = Tuple[int, int]  # (温度°C, 风速%)


class FanCurve:
    """温度-风速分段线性曲线。

    - 点列表按温度升序维护
    - 温度低于首个点 → 返回首点风速（避免冷机时风扇乱跳）
    - 温度高于末点 → 强制返回 100%（高温保护）
    - 最少 2 个点，最多 10 个点
    """

    MIN_POINTS = 2
    MAX_POINTS = 10
    TEMP_MIN = 30
    TEMP_MAX = 100
    SPEED_MIN = 0
    SPEED_MAX = 100
    MIN_POINT_GAP = 3  # 两个控制点允许的最小温度间距

    # 默认曲线
    DEFAULT_GPU: List[Point] = [(40, 30), (55, 40), (65, 55), (75, 75), (85, 90), (95, 100)]
    DEFAULT_CPU: List[Point] = [(45, 30), (60, 40), (70, 55), (80, 75), (90, 90), (98, 100)]

    def __init__(self, points: Optional[List[Point]] = None):
        self._points: List[Point] = []
        if points:
            self.setPoints(points)

    # ---------- 点管理 ----------

    def getPoints(self) -> List[Point]:
        return list(self._points)

    def setPoints(self, points: List[Point]) -> None:
        pts = sorted((int(t), self._clampSpeed(s)) for t, s in points if self.TEMP_MIN <= t <= self.TEMP_MAX)
        # 去掉间距过近的点（保留后者）
        dedup: List[Point] = []
        for t, s in pts:
            if dedup and t - dedup[-1][0] < self.MIN_POINT_GAP:
                dedup[-1] = (t, s)
            else:
                dedup.append((t, s))
        if len(dedup) >= self.MIN_POINTS:
            self._points = dedup[:self.MAX_POINTS]

    def updatePoint(self, index: int, temp: int, speed: int) -> bool:
        """拖动更新一个点。违反约束（越界/与其他点过近）时返回 False，不改数据。"""
        if not (0 <= index < len(self._points)):
            return False
        temp = self._clampTemp(temp)
        speed = self._clampSpeed(speed)
        if any(abs(t - temp) < self.MIN_POINT_GAP for i, (t, _) in enumerate(self._points) if i != index):
            return False
        self._points[index] = (temp, speed)
        self._points.sort(key=lambda p: p[0])
        # 排序后索引可能变化，无妨：调用方在下一次交互前会重新取点列表
        return True

    def addPoint(self, temp: int, speed: int) -> bool:
        if len(self._points) >= self.MAX_POINTS:
            return False
        temp = self._clampTemp(temp)
        speed = self._clampSpeed(speed)
        if any(abs(t - temp) < self.MIN_POINT_GAP for t, _ in self._points):
            return False
        self._points.append((temp, speed))
        self._points.sort(key=lambda p: p[0])
        return True

    def removePoint(self, index: int) -> bool:
        if len(self._points) <= self.MIN_POINTS:
            return False
        if not (0 <= index < len(self._points)):
            return False
        del self._points[index]
        return True

    # ---------- 插值 ----------

    def speedAt(self, temp: Optional[int]) -> Optional[int]:
        """按温度查风速。None 温度（传感器失联）返回 None，由调用方决定兜底。"""
        if temp is None or not self._points:
            return None
        if temp <= self._points[0][0]:
            return self._points[0][1]
        if temp >= self._points[-1][0]:
            return self.SPEED_MAX  # 高温保护：超出曲线右端直接全速
        for (t0, s0), (t1, s1) in zip(self._points, self._points[1:]):
            if t0 <= temp <= t1:
                if t1 == t0:
                    return s1
                ratio = (temp - t0) / (t1 - t0)
                return round(s0 + ratio * (s1 - s0))
        return self.SPEED_MAX

    # ---------- 序列化 ----------

    def toJson(self) -> str:
        return json.dumps(self._points)

    def fromJson(self, s: str) -> bool:
        try:
            pts = json.loads(s)
            if not isinstance(pts, list) or not pts:
                return False
            self.setPoints([(int(t), int(v)) for t, v in pts])
            return len(self._points) >= self.MIN_POINTS
        except (ValueError, TypeError):
            return False

    # ---------- 内部 ----------

    @classmethod
    def _clampTemp(cls, t: int) -> int:
        return max(cls.TEMP_MIN, min(cls.TEMP_MAX, t))

    @classmethod
    def _clampSpeed(cls, s: int) -> int:
        return max(cls.SPEED_MIN, min(cls.SPEED_MAX, s))
