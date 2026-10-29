#!/usr/bin/env python3
"""
把主题 JSON 里的图片全部重编码成设备兼容的格式。

背景：设备端 PNGdec 1.0.1 解码「1-bit / 2-bit 索引色 PNG」时会跳到空指针，
导致设备反复重启（Guru Meditation / BREAK instr / EXCVADDR 0xffffffe0）。
官方能用的主题，图片都是 8-bit 的 RGB / RGBA 或 8-bit 调色板。

本脚本把每一帧解码后重新编码成 **8-bit RGB PNG**（颜色类型 2），
完全绕开位解包逻辑。透明像素会被填成指定的背景色（默认取主题 bgColor）。

用法：
    python tools/fix_theme_images.py canvas/snake-text.json
    python tools/fix_theme_images.py in.json -o out.json

不依赖 PIL，只用标准库 zlib。
"""
import argparse
import base64
import json
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pngkit          # PNG 读写统一在 pngkit 里（设备只支持 8-bit RGB）

PNG_SIG = b"\x89PNG\r\n\x1a\n"


# ---------------- PNG 解码 ----------------
def rgb565_to_rgb(v):
    v = int(v) & 0xFFFF
    return (((v >> 11) & 0x1F) * 255 // 31,
            ((v >> 5) & 0x3F) * 255 // 63,
            (v & 0x1F) * 255 // 31)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()

    src = args.src
    out = args.out or os.path.splitext(src)[0] + "-fixed.json"

    d = json.load(open(src, encoding="utf-8"))
    bg = rgb565_to_rgb(d.get("bgColor", 0))

    converted = skipped = 0
    before_total = after_total = 0

    for group in d.get("sprites") or []:
        if not isinstance(group, list):
            continue
        for fr in group:
            b64 = fr.get("image")
            if not b64:
                continue
            raw = base64.b64decode(b64 + "=" * (-len(b64) % 4))
            before_total += len(b64)

            # 8-bit RGB/RGBA 的图已经是兼容的，原样保留
            if len(raw) > 25:
                ct, bd = raw[25], raw[24]
                if ct in (2, 6) and bd == 8:
                    skipped += 1
                    after_total += len(b64)
                    continue

            try:
                w, h, px = pngkit.decode(raw)
            except Exception as e:
                print(f"  ⚠️  跳过一帧: {e}")
                skipped += 1
                after_total += len(b64)
                continue

            # 透明像素填成主题背景色
            filled = [(r, g, b) if a >= 128 else bg for (r, g, b, a) in px]
            new_png = pngkit.encode_rgb(w, h, filled)
            new_b64 = base64.b64encode(new_png).decode("ascii")
            fr["image"] = new_b64
            after_total += len(new_b64)
            converted += 1

    json.dump(d, open(out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(out)
    print(f"转换完成: {converted} 帧重编码, {skipped} 帧原本就合规")
    print(f"  base64 总量: {before_total} -> {after_total} 字节")
    print(f"  输出: {out}  ({size} 字节)")
    if size > 16 * 1024:
        print(f"  ❌ 超过 16KB 的 JSON 缓冲上限，需要减帧或缩图")
    else:
        print(f"  ✅ 在 16KB 限制内")


if __name__ == "__main__":
    sys.exit(main())
