# -*- coding: utf-8 -*-
# 温度 / 转速 CSV 日志记录器：按天分文件，写入 exe/脚本同目录下的 logs/

import csv
import datetime
import os
import sys
from typing import Optional


class TempLogger:
    """把每个采样周期的 GPU/CPU 温度、转速、当前模式追加写入 CSV。

    文件位置：<程序所在目录>/logs/temp_log_YYYY-MM-DD.csv
    线程安全：只在主线程（QTimer 回调）中被调用。
    """

    HEADER = ["时间", "GPU温度(°C)", "GPU转速(RPM)", "CPU温度(°C)", "CPU转速(RPM)", "模式"]

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled
        self._file = None
        self._writer: Optional[csv.writer] = None
        self._curDate: Optional[str] = None
        self._baseDir = self._logBaseDir()

    @staticmethod
    def _logBaseDir() -> str:
        # PyInstaller 打包后取 exe 目录；源码运行取 src/ 目录
        if hasattr(sys, "_MEIPASS") or sys.argv[0].lower().endswith(".exe"):
            base = os.path.dirname(os.path.abspath(sys.argv[0]))
        else:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # src/ 的上级
        return os.path.join(base, "logs")

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def logDir(self) -> str:
        return self._baseDir

    def setEnabled(self, enabled: bool) -> bool:
        """开关日志。返回是否成功（开启失败如目录不可写时返回 False）。"""
        if enabled == self._enabled:
            return True
        if enabled:
            ok = self._open()
            if not ok:
                return False
            self._enabled = True
        else:
            self._close()
            self._enabled = False
        return True

    def _open(self) -> bool:
        try:
            os.makedirs(self._baseDir, exist_ok=True)
            self._rollIfNeeded()
            return True
        except OSError as ex:
            print(f"TempLogger: cannot open log file: {ex}")
            return False

    def _rollIfNeeded(self) -> None:
        today = datetime.date.today().isoformat()
        if self._file is not None and today == self._curDate:
            return
        if self._file is not None:
            self._file.close()
        path = os.path.join(self._baseDir, f"temp_log_{today}.csv")
        fileExists = os.path.exists(path)
        self._file = open(path, "a", newline="", encoding="utf-8-sig")
        self._writer = csv.writer(self._file)
        self._curDate = today
        if not fileExists:
            self._writer.writerow(self.HEADER)
            self._file.flush()

    def _close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
            self._writer = None

    def log(self, gpuTemp, gpuRPM, cpuTemp, cpuRPM, mode: str) -> None:
        if not self._enabled:
            return
        try:
            self._rollIfNeeded()
            if self._writer is None:
                return
            self._writer.writerow([
                datetime.datetime.now().strftime("%H:%M:%S"),
                gpuTemp if gpuTemp is not None else "",
                gpuRPM if gpuRPM is not None else "",
                cpuTemp if cpuTemp is not None else "",
                cpuRPM if cpuRPM is not None else "",
                mode,
            ])
            self._file.flush()
        except OSError as ex:
            print(f"TempLogger: write failed: {ex}")
