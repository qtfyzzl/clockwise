#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从固件头文件提取位图字体，生成 fontdata.json（供编辑器/打包 exe 使用）。

解析两类源：
  1. Adafruit GFXfont（*.h）：hour8pt7b / minute7pt7b / atari / Picopixel
  2. 经典 5x7 固定字体（glcdfont.c）：Canvas 里 font 为空或未知时实际用的字体

用法（在仓库根目录）：
    python editor/build_data.py
"""

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(ROOT, "firmware", "custom-themes", "canvas", "fonts")
COMMONS_DIR = os.path.join(ROOT, "firmware", "lib", "cw-commons")
GLCDFONT_CANDIDATES = [
    os.path.expanduser("~/.platformio/.cache/tmp/pkg-installing-odkdiuq4/glcdfont.c"),
]

# Canvas 主题里的 font 名 -> (目录, 文件, 数组前缀)
GFX_FONTS = {
    "big": (FONT_DIR, "hour8pt7b.h"),
    "medium": (FONT_DIR, "minute7pt7b.h"),
    "square": (FONT_DIR, "atari.h"),
    "picopixel": (COMMONS_DIR, "picopixel.h"),
}

GLYPH_ENTRY = re.compile(
    r"\{\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\}"
)
HEX_BYTE = re.compile(r"0x([0-9A-Fa-f]{1,2})")
ARRAY_DECL = re.compile(r"(\w+)\s*\[\s*\]\s*PROGMEM\s*=\s*\{(.*?)\};", re.S)


def _read(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


def _hex_bytes(block):
    return [int(h, 16) for h in HEX_BYTE.findall(block)]


def parse_gfx_font(path, expect_name=None):
    src = _read(path)

    bitmaps = None
    glyphs = None
    for m in ARRAY_DECL.finditer(src):
        name, body = m.group(1), m.group(2)
        low = name.lower()
        if low.endswith("bitmaps") and bitmaps is None:
            bitmaps = _hex_bytes(body)
        elif low.endswith("glyphs") and glyphs is None:
            glyphs = [[int(v) for v in g] for g in GLYPH_ENTRY.findall(body)]

    if bitmaps is None or glyphs is None:
        raise RuntimeError("解析失败：%s 找不到 Bitmaps/Glyphs 数组" % path)

    # GFXfont 结构体： (GFXglyph *)xxxGlyphs, 0x20, 0x7E, 15
    m = re.search(r"\(\s*GFXglyph\s*\*\s*\)\s*\w+\s*,\s*(0x[0-9A-Fa-f]+|\d+)\s*,"
                  r"\s*(0x[0-9A-Fa-f]+|\d+)\s*,\s*(\d+)\s*\}", src)
    if not m:
        raise RuntimeError("解析失败：%s 找不到 GFXfont 结构体" % path)
    first = int(m.group(1), 0)
    last = int(m.group(2), 0)
    yadv = int(m.group(3))

    if len(glyphs) < last - first + 1:
        raise RuntimeError("%s 字形数 %d < %d" % (path, len(glyphs), last - first + 1))

    # 校验 bitmap 偏移不越界
    for off, w, h, _xa, _xo, _yo in glyphs:
        if h and (off + (w * h + 7) // 8) > len(bitmaps):
            raise RuntimeError("%s 字形偏移越界 off=%d" % (path, off))

    return {
        "kind": "gfx",
        "source": os.path.basename(path),
        "first": first,
        "last": last,
        "yadv": yadv,
        "glyphs": glyphs[: last - first + 1],
        "bitmaps": bitmaps,
    }


def parse_classic_5x7(path):
    src = _read(path)
    m = re.search(r"glcdfont\s*\[\s*\]\s*(?:PROGMEM\s*)?=\s*\{(.*?)\n\};", src, re.S)
    body = m.group(1) if m else src
    data = _hex_bytes(body)
    if len(data) < 128 * 5:
        raise RuntimeError("%s 数据不足：%d 字节" % (path, len(data)))
    data = data[: 256 * 5] if len(data) >= 256 * 5 else data[: 128 * 5]
    return {
        "kind": "classic",
        "source": os.path.basename(path),
        "width": 5,
        "height": 8,
        "advance": 6,
        "bitmaps": data,
    }


def main():
    fonts = {}
    for name, (d, fname) in GFX_FONTS.items():
        path = os.path.join(d, fname)
        if not os.path.isfile(path):
            print("!! 缺少字体文件: %s" % path)
            return 1
        fonts[name] = parse_gfx_font(path)
        g = fonts[name]
        print("%-10s %-16s 字形 %3d  位图 %4d B  yAdvance=%d"
              % (name, os.path.basename(path), len(g["glyphs"]), len(g["bitmaps"]), g["yadv"]))

    glcd = None
    for cand in GLCDFONT_CANDIDATES:
        if os.path.isfile(cand):
            glcd = cand
            break
    if glcd:
        fonts["default"] = parse_classic_5x7(glcd)
        print("%-10s %-16s 经典 5x7，%d 字节" % ("default", os.path.basename(glcd),
                                                len(fonts["default"]["bitmaps"])))
    else:
        print("!! 未找到 glcdfont.c，font 为空时预览将退回 picopixel")

    out = {
        "note": "由 editor/build_data.py 从固件字体头文件生成，勿手工编辑",
        "fonts": fonts,
    }
    dst = os.path.join(ROOT, "editor", "fontdata.json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print("已写入 %s（%.1f KB）" % (dst, os.path.getsize(dst) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
