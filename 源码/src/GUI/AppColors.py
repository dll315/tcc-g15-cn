from enum import Enum
from typing import *

class Colors(Enum):
    # 深蓝灰现代主题
    DARK_BG     = '#161b24'   # 窗口背景
    DARK_GREY   = '#1b2330'   # 面板 / 控件背景
    GREY        = '#3a4556'   # 边框 / 分隔
    WHITE       = '#e8edf4'   # 主文字
    TEXT_DIM    = '#9aa4b2'   # 次要文字
    GREEN       = '#34d17d'   # 正常
    YELLOW      = '#f5c542'   # 偏高
    RED         = '#f0564a'   # 危险
    BLUE        = '#4da3ff'   # 强调色
    ACCENT      = '#7c5cff'   # 选中 / 高亮

    def rgb(self) -> Tuple[int, int, int]:
        color = self.value.lstrip('#')
        return tuple(int(color[i:i+2], 16) for i in (0, 2, 4))
