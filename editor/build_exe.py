#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包 Windows 单文件 exe（PyInstaller）。

流程：
  1. 若 fontdata.json 不存在，先跑 build_data.py 从固件字体头文件生成
  2. 用 64x64 渲染结果生成多尺寸 .ico
  3. PyInstaller --onefile --windowed

产物：editor/dist/ClockCanvasDesigner.exe

用法：python editor/build_exe.py
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

APP = "ClockCanvasDesigner"
DIST = os.path.join(HERE, "dist")
WORK = os.path.join(HERE, "_build")


def ensure_fontdata():
    path = os.path.join(HERE, "fontdata.json")
    if os.path.isfile(path):
        print("[1/3] fontdata.json 已存在（%.1f KB）" % (os.path.getsize(path) / 1024.0))
        return
    print("[1/3] 生成 fontdata.json …")
    subprocess.check_call([sys.executable, os.path.join(HERE, "build_data.py")])


def make_icon():
    from PIL import Image
    from datetime import datetime
    import cw_core as C

    theme = C.template_theme("minimal")
    for el in theme["setup"]:
        if el.get("type") == "datetime" and el.get("content") == "H:i":
            el["content"] = "10:09"
        if el.get("type") == "datetime" and el.get("content") == "m-d":
            el["content"] = "10-28"
    img = C.render_theme(theme, datetime(2026, 10, 28, 10, 9, 0))
    big = img.resize((256, 256), Image.NEAREST)
    path = os.path.join(HERE, "icon.ico")
    big.save(path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("[2/3] 生成图标 %s" % path)
    return path


def build(icon):
    for d in (WORK,):
        if os.path.isdir(d):
            shutil.rmtree(d)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", APP,
        "--icon", icon,
        "--paths", os.path.join(ROOT, "tools"),
        "--hidden-import", "pngkit",
        "--add-data", "%s%s." % (os.path.join(HERE, "fontdata.json"), os.pathsep),
        "--distpath", DIST,
        "--workpath", WORK,
        "--specpath", WORK,
        "canvas_designer.py",
    ]
    print("[3/3] PyInstaller …")
    print("      " + " ".join(cmd))
    subprocess.check_call(cmd, cwd=HERE)

    exe = os.path.join(DIST, APP + ".exe")
    if not os.path.isfile(exe):
        print("!! 未生成 exe")
        return 1
    print()
    print("完成：%s（%.1f MB）" % (exe, os.path.getsize(exe) / 1024.0 / 1024.0))
    return 0


def main():
    ensure_fontdata()
    icon = make_icon()
    code = build(icon)
    if code == 0:
        print("可直接双击运行，或复制到任意目录（单文件、无依赖）。")
    return code


if __name__ == "__main__":
    sys.exit(main())
