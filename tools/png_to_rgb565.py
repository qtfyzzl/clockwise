#!/usr/bin/env python3
"""png_to_rgb565.py —— 把 PNG 缩放到指定尺寸并转成 RGB565 C 数组。

用于原生 Clockface 的图片素材：输出 const unsigned short NAME[N] + NAME_SIZE[2]，
格式与 firmware/lib/native-mario/gfx/assets.h 一致，可直接贴进 gfx 头文件。

用法:
    python png_to_rgb565.py 输入.png 输出.h 名称 [宽] [高] [透明色hex]

默认缩放到 64x64。透明背景会被填充为透明色（默认深蓝 0x0C2A，可传第6参数覆盖）。
"""

import sys
from PIL import Image

def rgb_to_565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)

def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    src = sys.argv[1]
    out = sys.argv[2]
    name = sys.argv[3]
    w = int(sys.argv[4]) if len(sys.argv) > 4 else 64
    h = int(sys.argv[5]) if len(sys.argv) > 5 else 64
    fill_hex = int(sys.argv[6], 16) if len(sys.argv) > 6 else 0x0C2A  # 深蓝夜空

    img = Image.open(src).convert("RGBA")
    # 最近邻缩放 + 居中裁剪：保持像素画锐利感，不产生插值过渡色
    img.thumbnail((w, h), Image.NEAREST)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.paste(img, ((w - img.width) // 2, (h - img.height) // 2), img)
    img = canvas

    fr, fg, fb = (fill_hex >> 11) & 0x1F, (fill_hex >> 5) & 0x3F, fill_hex & 0x1F
    fr, fg, fb = fr << 3, fg << 2, fb << 3

    # 可选调色板量化：把颜色压到 max_colors 种（默认 32），
    # 让画面是「有限色像素画」而不是 LANCZOS 缩放产生的糊图。
    max_colors = int(sys.argv[7]) if len(sys.argv) > 7 else 32
    qimg = img.quantize(colors=max_colors, method=Image.FASTOCTREE) if max_colors > 0 else img
    if max_colors > 0:
        img = qimg.convert("RGBA")

    px = list(img.getdata())
    vals = []
    for r, g, b, a in px:
        if a < 128:  # 透明 → 填充色
            r, g, b = fr, fg, fb
        vals.append(rgb_to_565(r, g, b))

    n = len(vals)
    lines = []
    lines.append(f"#pragma once\n")
    lines.append(f"const unsigned short {name}[{n}] = {{")
    for i in range(0, n, 16):
        chunk = vals[i:i+16]
        hexs = ", ".join(f"0x{v:04X}" for v in chunk)
        lines.append(f"  {hexs},")
    lines.append("};\n")
    lines.append(f"const byte {name}_SIZE[2] = {{{w}, {h}}};\n")

    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))

    # 统计颜色数（提示量化质量）
    colors = len(set(vals))
    print(f"✅ {src} → {out}")
    print(f"   尺寸 {w}x{h}，{n} 像素，{colors} 种 RGB565 颜色")

if __name__ == "__main__":
    main()
