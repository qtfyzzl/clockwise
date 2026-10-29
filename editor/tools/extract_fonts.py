#!/usr/bin/env python3
"""从固件源码里抽取 Adafruit GFX 字体的真实字形数据，供编辑器像素级预览。

输入：
  firmware/custom-themes/canvas/fonts/{hour8pt7b,minute7pt7b,atari}.h
  firmware/lib/cw-commons/picopixel.h
输出：
  editor/web/js/fonts.json

Canvas 里的 font 名字和实际符号名不一致，映射见 FONT_MAP。
"""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EDITOR = os.path.dirname(HERE)
REPO = os.path.dirname(EDITOR)

SRC = {
    "big": ("firmware/custom-themes/canvas/fonts/hour8pt7b.h", "hour8pt7b"),
    "medium": ("firmware/custom-themes/canvas/fonts/minute7pt7b.h", "minute7pt7b"),
    "square": ("firmware/custom-themes/canvas/fonts/atari.h", "atariFont"),
    "picopixel": ("firmware/lib/cw-commons/picopixel.h", "Picopixel"),
}

HEX_RE = re.compile(r"0x([0-9A-Fa-f]{2})")
GLYPH_RE = re.compile(
    r"\{\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\}"
)
FONT_DECL_RE = re.compile(
    r"const\s+GFXfont\s+\w+\s+PROGMEM\s*=\s*\{[^}]*?\}\s*,\s*(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)\s*,\s*(\d+)"
)


def block(src, marker):
    """取出 `<marker> = { ... };` 之间的内容。"""
    i = src.find(marker)
    if i < 0:
        raise ValueError("找不到 " + marker)
    i = src.find("{", i)
    j = src.find("};", i)
    if i < 0 or j < 0:
        raise ValueError("大括号不匹配: " + marker)
    return src[i + 1 : j]


def parse(path, symbol):
    text = open(path, encoding="utf-8-sig").read()

    raw_bits = block(text, symbol + "Bitmaps")
    bitmaps = [int(h, 16) for h in HEX_RE.findall(raw_bits)]

    # 逐行解析：行尾注释里也可能出现数字（atari.h 写成 // 0x6D 'm'），
    # 整块 findall 会把这些数字混进来，所以只认每行第一个 {..}。
    raw_glyphs = block(text, symbol + "Glyphs")
    glyphs = []
    for line in raw_glyphs.splitlines():
        m = GLYPH_RE.search(line)
        if m:
            glyphs.append([int(g) for g in m.groups()])

    m = re.search(
        r"const\s+GFXfont\s+" + re.escape(symbol) + r"\s+PROGMEM\s*=\s*\{[^}]*?"
        r"(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)\s*,\s*(\d+)\s*\}",
        text,
    )
    if not m:
        raise ValueError("%s: 找不到 GFXfont 声明（first/last/yAdvance）" % symbol)
    first, last, yadv = int(m.group(1), 16), int(m.group(2), 16), int(m.group(3))

    expect = last - first + 1
    if len(glyphs) != expect:
        raise ValueError("%s: 字形数 %d != 期望 %d" % (symbol, len(glyphs), expect))

    # 统计有实际像素的字形数（square 字体的坑就在这）
    painted = sum(1 for g in glyphs if g[1] > 0 and g[2] > 0)
    return {
        "symbol": symbol,
        "first": first,
        "last": last,
        "yAdvance": yadv,
        "bitmaps": bitmaps,
        "glyphs": glyphs,
        "painted": painted,
        "total": expect,
    }


def main():
    out = {"fonts": {}}
    for canvas_name, (rel, symbol) in SRC.items():
        path = os.path.join(REPO, rel)
        if not os.path.exists(path):
            print("跳过（文件不存在）: " + path, file=sys.stderr)
            continue
        f = parse(path, symbol)
        f["file"] = rel
        out["fonts"][canvas_name] = f
        print(
            "%-10s -> %-12s glyphs=%3d 有字形=%3d yAdvance=%2d bitmaps=%dB"
            % (canvas_name, symbol, f["total"], f["painted"], f["yAdvance"], len(f["bitmaps"]))
        )

    dst = os.path.join(EDITOR, "web", "js", "fonts.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print("已写入 %s (%d 字节)" % (dst, os.path.getsize(dst)))


if __name__ == "__main__":
    main()
