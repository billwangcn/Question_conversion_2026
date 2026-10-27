# -*- coding: utf-8 -*-
"""自测脚本：不启动界面，直接验证解析与转换（开发自测用）。

用法：
    python 自测.py            # 文本互转检查
    python 自测.py --export   # 额外执行 DOC 导出（需要 Word/WPS）
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "examconv", os.path.join(ROOT, "E学院试题格式互转.py"))
conv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conv)

DATA = HERE


def run(name, direction):
    path = os.path.join(DATA, name)
    raw = conv._read_plain(path)
    lines, stat, issues, src = conv.convert_text(raw, direction, {})
    print("=" * 30, name, "=" * 30)
    print("\n".join(lines))
    print("统计:", stat, "| 源格式:", src)
    for it in issues:
        print("  提示:", it)
    print()


def export(name, direction):
    path = os.path.join(DATA, name)
    out, stat, issues, engine, wengine = conv.convert_file(
        path, direction, os.path.join(ROOT, "输出"))
    print("导出:", out, "|", engine, "->", wengine, "|", stat)
    for it in issues:
        print("  提示:", it)
    return out


if __name__ == "__main__":
    run("旧版样例.txt", conv.DIR_AUTO)
    run("新版样例.txt", conv.DIR_AUTO)
    run("边界样例.txt", conv.DIR_TO_OLD)
    if "--export" in sys.argv:
        export("旧版样例.txt", conv.DIR_AUTO)
        export("新版样例.txt", conv.DIR_AUTO)
