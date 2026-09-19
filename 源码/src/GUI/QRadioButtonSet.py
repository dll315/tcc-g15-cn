from typing import Callable, Optional, Tuple, Union
from PySide6 import QtCore, QtWidgets

class QRadioButtonSet(QtWidgets.QWidget):
    _buttons: dict[str, QtWidgets.QRadioButton]
    _userCallback: Optional[Callable[[str], None]]

    def __init__(self, parent: Optional[QtWidgets.QWidget], title: Optional[str], options: list[Tuple[str, str]], layout: Optional[Union[QtWidgets.QHBoxLayout, QtWidgets.QVBoxLayout]] = None) -> None:
        super().__init__(parent)
        if len(options) == 0:
            raise RuntimeError('"options" list length can not be 0')

        # 默认值不能直接写 QHBoxLayout()：那是在函数定义时创建的唯一对象，
        # 第二个实例会把第一个实例的布局（连同的按钮）整个抢过去
        if layout is None:
            layout = QtWidgets.QHBoxLayout()
        self.setLayout(layout)

        if title:
            layout.addWidget(QtWidgets.QLabel(title))

        self._userCallback = None

        self._buttons = {}
        for title, value in options:
            rb = QtWidgets.QRadioButton(title)
            rb._value = value
            layout.addWidget(rb)
            self._buttons[value] = rb
            rb.setChecked(True)
            rb.toggled.connect(self._onClicked)

    def setChecked(self, value: str):
        if value not in self._buttons:
            # 防御：非法值（如原版/旧版残留的未知模式）直接忽略，避免 KeyError 崩溃
            return
        self._buttons[value].setChecked(True)

    def getChecked(self) -> Optional[str]:
        for rb in self._buttons.values():
            if rb.isChecked():
                return rb._value
        return None

    def setOnChange(self, callback: Callable[[str], None]) -> None:
        self._userCallback = callback

    @QtCore.Slot()
    def _onClicked(self):
        rb = self.sender() # type: QtWidgets.QRadioButton
        if self._userCallback and rb.isChecked():
            self._userCallback(rb._value)