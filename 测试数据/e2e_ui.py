# -*- coding: utf-8 -*-
"""端到端界面自测：模拟添加文件 -> 触发预览 -> 截图（开发自测用）。"""
import os
import runpy
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
shot_path = os.path.join(HERE, "ui_loaded.png")

import PyQt6.QtWidgets as W          # noqa: E402
from PyQt6.QtCore import QTimer      # noqa: E402

_RealApp = W.QApplication
_orig_show = W.QMainWindow.show


def _patched_show(self):
    _orig_show(self)

    def later():
        samples = [os.path.join(HERE, "测试数据", "旧版样例.txt"),
                   os.path.join(HERE, "测试数据", "新版样例.txt")]
        samples = [p for p in samples if os.path.exists(p)]
        self.add_files(samples)
        W.QApplication.processEvents()
        self.grab().save(shot_path)
        print("已截图:", shot_path)
        _RealApp.instance().quit()

    QTimer.singleShot(400, later)


W.QMainWindow.show = _patched_show
sys.exit = lambda *a, **k: None

runpy.run_path(os.path.join(HERE, "E学院试题格式互转.py"), run_name="__main__")
print("端到端界面自测完成")
