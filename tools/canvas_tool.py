#!/usr/bin/env python3
"""
Canvas 主题辅助工具（Clockwise cw-cf-0x07）

子命令：
  color   #RRGGBB  -> RGB565 十进制（写 JSON 用）
  metrics 字体名 "文本" [字体目录]  -> 文本包围盒与居中坐标
  lcd     字体名 "文本"             -> 粗略预览（用 # 画出来）

用法：
  python tools/canvas_tool.py color "#1E90FF"
  python tools/canvas_tool.py metrics big "H:i"
"""

import re
import sys
import os
import glob

# ---------------- RGB565 ----------------

def rgb565(hexstr):
    h = hexstr.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError("需要 #RRGGBB")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
    return v, (r, g, b)


def rgb565_to_rgb(v):
    r = (v >> 11) & 0x1F
    g = (v >> 5) & 0x3F
    b = v & 0x1F
    return (r * 255 // 31, g * 255 // 63, b * 255 // 31)


# ---------------- Adafruit GFXfont 解析 ----------------

# 模块名 -> (头文件, 显示名)
FONT_ALIASES = {
    "big": "hour8pt7b",       # Canvas 里 "big" 对应 hour8pt7b
    "medium": "minute7pt7b",  # "medium" 对应 minute7pt7b
    "square": "atari",        # "square" 对应 atariFont
    "picopixel": "picopixel", # 来自 cw-commons/picopixel.h
}

GLYPH_RE = re.compile(
    r"\{\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\}"
    r"[^/\n]*//[^\n]*'(.+?)'"
)


def find_font_file(name, font_dir):
    """在字体目录里找包含该字体定义的 .h 文件。

    注意实际文件名/符号名与 Canvas 里的字体名并不一致：
      big    -> hour8pt7b.h      (hour8pt7bGlyphs)
      medium -> minute7pt7b.h    (minute7pt7bGlyphs)
      square -> atari.h          (atariFontGlyphs)
      picopixel -> picopixel.h   (PicopixelGlyphs，在 cw-commons 下)
    """
    files = {
        "big": "hour8pt7b.h",
        "medium": "minute7pt7b.h",
        "square": "atari.h",
        "picopixel": "picopixel.h",
    }
    target = FONT_ALIASES.get(name, name)
    fname = files.get(name, f"{name}.h")

    search_dirs = [font_dir]
    # picopixel 在 firmware/lib/cw-commons 下（从 fonts 往上三层再进 lib）
    fw_root = os.path.dirname(os.path.dirname(os.path.dirname(font_dir)))
    search_dirs.append(os.path.join(fw_root, "lib", "cw-commons"))

    for d in search_dirs:
        path = os.path.join(d, fname)
        if os.path.isfile(path):
            return path, target

    # 兜底：按符号名大小写不敏感扫描
    for d in search_dirs:
        for path in glob.glob(os.path.join(d, "*.h")):
            src = open(path, encoding="utf-8", errors="ignore").read()
            if f"{target}glyphs" in src.lower():
                return path, target
    return None, target


def parse_font(path):
    """返回 (glyphs dict, yAdvance)。glyphs: char -> (w, h, xAdv, xOff, yOff)"""
    src = open(path, encoding="utf-8", errors="ignore").read()
    glyphs = {}
    for m in GLYPH_RE.finditer(src):
        _, w, h, xadv, xoff, yoff = m.groups()[:6]
        ch = m.group(7)
        glyphs[ch] = (int(w), int(h), int(xadv), int(xoff), int(yoff))
    yadv = 15
    m = re.search(r"0x20,\s*0x7e,\s*(\d+)", src, re.I)
    if m:
        yadv = int(m.group(1))
    return glyphs, yadv


def text_bounds(glyphs, yadv, text):
    """复刻 Adafruit_GFX::getTextBounds 的算法（x=y=0 起笔）。"""
    x = 0
    y = 0
    minx = miny = 10 ** 6
    maxx = maxy = -10 ** 6
    for ch in text:
        if ch == "\n":
            x = 0
            y += yadv
            continue
        if ch not in glyphs:
            continue
        w, h, xadv, xoff, yoff = glyphs[ch]
        xo = x + xoff
        yo = y + yoff
        if w and h:
            minx = min(minx, xo)
            maxx = max(maxx, xo + w)
            miny = min(miny, yo)
            maxy = max(maxy, yo + h)
        x += xadv
    if maxx < minx:
        return 0, 0, 0, 0, 0
    # 返回 (x1, y1, w, h, 总进宽)
    return minx, miny, maxx - minx, maxy - miny, x


def preview(glyphs, text):
    """用位图数据粗略渲染，仅供大致感受字形高度（非像素级精确）。"""
    # 这里不解析 bitmap，只标注包围盒尺寸
    return None


# ---------------- CLI ----------------

def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1

    cmd = sys.argv[1]

    if cmd == "color":
        v, rgb = rgb565(sys.argv[2])
        print(f"#RRGGBB {sys.argv[2]}  ->  RGB565 = {v}  (0x{v:04X})")
        print(f"  回算 RGB ≈ {rgb565_to_rgb(v)}")
        return 0

    if cmd == "metrics":
        font = sys.argv[2]
        text = sys.argv[3] if len(sys.argv) > 3 else "H:i"
        font_dir = sys.argv[4] if len(sys.argv) > 4 else os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "firmware", "clockfaces", "cw-cf-0x07", "fonts",
        )
        path, target = find_font_file(font, font_dir)
        if not path:
            print(f"找不到字体 '{font}' (期望 {target}Glyphs) 于 {font_dir}")
            return 1
        glyphs, yadv = parse_font(path)
        x1, y1, w, h, advance = text_bounds(glyphs, yadv, text)
        print(f"字体: {font} ({target})  yAdvance={yadv}")
        print(f"文本: {text!r}")
        print(f"  x1={x1} y1={y1} 宽={w} 高={h} 进宽={advance}")
        cx_box = (64 - w) // 2 - x1      # 按实际墨迹包围盒居中（推荐）
        cx_adv = (64 - advance) // 2     # 按进宽居中（含字尾空隙）
        cy = (64 - h) // 2 - y1          # 视觉垂直居中（抵消 y1 负偏移）
        print(f"  水平居中 x = {cx_box}  (按墨迹宽 {w}，推荐)")
        print(f"  水平居中 x = {cx_adv}  (按进宽 {advance}，短串更省事)")
        print(f"  视觉居中 y = {cy}   ((64-{h})/2={ (64-h)//2 } 减去 y1={y1})")
        print(f"  JSON: \"x\": {cx_box}, \"y\": {cy}")
        if w > 64:
            print(f"  !! 墨迹宽 {w} > 64，放不下")
        return 0

    print(f"未知子命令: {cmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
