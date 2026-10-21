# -*- coding: utf-8 -*-
# PID 闭环风扇控制：输入温度，输出 0-100 的风扇百分比。
#
# 为什么不用固定曲线：曲线只看"现在多热"，风扇永远慢半拍。PID 的微分项看的是
# "升得多快"，温度刚开始往上冲就把转速提前拉起来。
#
# 输出限速（maxStep）避免风扇突然嗷一声；积分项带抗饱和钳制，避免长时间满载后
# 温度掉下来风扇还黏在高转速下不来。

from typing import Optional


class PidController:
    def __init__(self, target: float, kp: float = 5.0, ki: float = 0.4, kd: float = 8.0,
                 outMin: float = 0.0, outMax: float = 100.0, base: float = 12.0,
                 integralClamp: float = 60.0, maxStep: float = 25.0,
                 deadband: float = 0.0) -> None:
        self.target = float(target)
        self.kp = float(kp)
        self.ki = float(ki)
        self.kd = float(kd)
        self.outMin = float(outMin)
        self.outMax = float(outMax)
        self.base = float(base)
        self.integralClamp = float(integralClamp)
        self.maxStep = float(maxStep)
        # 误差在这个范围内就当作零：温度在目标线上抖动时不去改风扇，
        # 否则每秒一次微小改动会让转速表看着来回跳。
        self.deadband = float(deadband)

        self._integral = 0.0
        self._lastTemp: Optional[float] = None
        self._out = float(base)
        self.lastRate = 0.0

    def reset(self) -> None:
        self._integral = 0.0
        self._lastTemp = None
        self._out = self.base
        self.lastRate = 0.0

    def update(self, temp: Optional[float], dt: float) -> int:
        """返回 0-100 的目标风扇百分比。temp 为 None 时保持上一次输出。"""
        if temp is None or dt <= 0:
            return int(round(self._out))

        error = temp - self.target
        if abs(error) < self.deadband:
            error = 0.0

        # 微分取测量值的变化率，不取误差的变化率：改目标温度时不会踢一脚
        rate = 0.0
        if self._lastTemp is not None:
            rate = (temp - self._lastTemp) / dt
        self.lastRate = rate

        self._integral += error * dt * self.ki
        self._integral = max(-self.integralClamp, min(self.integralClamp, self._integral))

        raw = self.base + self.kp * error + self._integral + self.kd * rate
        want = max(self.outMin, min(self.outMax, raw))

        # 限速：风扇按步进爬，不跳变
        step = self.maxStep * dt
        delta = max(-step, min(step, want - self._out))
        self._out = max(self.outMin, min(self.outMax, self._out + delta))

        self._lastTemp = temp
        return int(round(self._out))
