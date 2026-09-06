import threading
import win32con
from ctypes import *
from ctypes.wintypes import *
from PySide6.QtCore import *

G_MODE_KEY = 0x80

# 修饰键常量（RegisterHotKey 的 fsModifiers 参数）
MOD_ALT       = 0x0001
MOD_CONTROL   = 0x0002
MOD_SHIFT     = 0x0004
MOD_WIN       = 0x0008
MOD_NOREPEAT  = 0x4000

_STOP_SIGNAL_CODE = 0x9AB10000 # This number was picked randomly

class HotKey(QThread):
    def __init__(self, key: int, keyPressedSignal: Signal, modifiers: int = 0):
        super(HotKey, self).__init__()
        self.keyPressedSignal = keyPressedSignal
        self.key = key
        self.modifiers = modifiers
        self.nativeThreadId = None

    def run(self):
        self.nativeThreadId = threading.get_native_id()
        user32 = windll.user32

        if not user32.RegisterHotKey(None, 1, self.modifiers, self.key):
            print(f"Could not register hot key {self.key} (modifiers={self.modifiers:#x})")
            return
        msg = MSG()

        while user32.GetMessageA(byref(msg), None, 0, 0):
            if msg.message == win32con.WM_USER and msg.wParam == _STOP_SIGNAL_CODE:
                break
            if msg.message == win32con.WM_HOTKEY and msg.wParam == 1:
                self.keyPressedSignal.emit()
        user32.UnregisterHotKey(None, 1)

    def stop(self):
        if self.nativeThreadId is None:
            return
        windll.user32.PostThreadMessageW(self.nativeThreadId, win32con.WM_USER, _STOP_SIGNAL_CODE, 0)
