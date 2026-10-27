# -*- coding: utf-8 -*-
"""离屏/真实渲染主窗口并截图，用于开发自测（不弹窗、自动退出）。"""
import os
import runpy
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
shot_path = os.path.join(HERE, "ui.png")

try:
    import PyQt6.QtWidgets as W
    QT = 6
except ImportError:
    import PyQt5.QtWidgets as W
    QT = 5

_RealApp = W.QApplication


class ShotApp(_RealApp):
    def _grab(self):
        for widget in _RealApp.topLevelWidgets():
            if widget.isVisible():
                widget.grab().save(shot_path)
                print("已截图:", shot_path, widget.size().width(), "x", widget.size().height())
                return

    def exec(self):
        self._grab()
        return 0

    def exec_(self):
        self._grab()
        return 0


W.QApplication = ShotApp
sys.exit = lambda *a, **k: None

runpy.run_path(os.path.join(HERE, "E学院试题格式互转.py"), run_name="__main__")
print("界面构建完成（Qt%d）" % QT)
