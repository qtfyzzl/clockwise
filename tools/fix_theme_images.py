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

PNG_SIG = b"\x89PNG\r\n\x1a\n"


# ---------------- PNG 解码 ----------------
def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode_png(raw):
    """返回 (width, height, 像素列表[(r,g,b,a)]) ；不支持隔行"""
    if raw[:8] != PNG_SIG:
        raise ValueError("不是 PNG")

    pos = 8
    w = h = bd = ct = interlace = None
    plte = b""
    trns = b""
    idat = b""
    while pos + 8 <= len(raw):
        ln = struct.unpack(">I", raw[pos:pos + 4])[0]
        typ = raw[pos + 4:pos + 8]
        data = raw[pos + 8:pos + 8 + ln]
        if typ == b"IHDR":
            w, h, bd, ct, _comp, _filt, interlace = struct.unpack(">IIBBBBB", data)
        elif typ == b"PLTE":
            plte = data
        elif typ == b"tRNS":
            trns = data
        elif typ == b"IDAT":
            idat += data
        elif typ == b"IEND":
            break
        pos += 12 + ln

    if interlace:
        raise ValueError("不支持隔行(interlaced) PNG")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    bits_per_pixel = channels * bd
    bpp = max(1, bits_per_pixel // 8)              # 过滤用的每像素字节数
    stride = (w * bits_per_pixel + 7) // 8         # 每行字节数

    data = zlib.decompress(idat)

    # 反过滤
    rows = []
    prev = bytearray(stride)
    p = 0
    for _ in range(h):
        ftype = data[p]; p += 1
        line = bytearray(data[p:p + stride]); p += stride
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif ftype == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                c = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(a, prev[i], c)) & 0xFF
        elif ftype != 0:
            raise ValueError(f"未知过滤类型 {ftype}")
        rows.append(line)
        prev = line

    # 展开成 RGBA
    pixels = []
    for line in rows:
        if bd == 8:
            if ct == 3:
                pixels += [(plte[i * 3], plte[i * 3 + 1], plte[i * 3 + 2],
                            0 if (trns and i < len(trns) and trns[i] == 0) else 255) for i in line[:w]]
            elif ct == 2:
                pixels += [(line[i * 3], line[i * 3 + 1], line[i * 3 + 2], 255) for i in range(w)]
            elif ct == 6:
                pixels += [(line[i * 4], line[i * 4 + 1], line[i * 4 + 2], line[i * 4 + 3]) for i in range(w)]
            elif ct == 0:
                pixels += [(line[i], line[i], line[i], 255) for i in range(w)]
            elif ct == 4:
                pixels += [(line[i * 2], line[i * 2], line[i * 2], line[i * 2 + 1]) for i in range(w)]
        else:  # bd in (1, 2, 4) —— 每字节装多个像素
            per_byte = 8 // bd
            mask = (1 << bd) - 1
            for x in range(w):
                byte = line[x // per_byte]
                shift = 8 - bd * (x % per_byte + 1)
                idx = (byte >> shift) & mask
                if ct == 3:
                    pixels.append((plte[idx * 3], plte[idx * 3 + 1], plte[idx * 3 + 2],
                                   0 if (trns and idx < len(trns) and trns[idx] == 0) else 255))
                else:  # 灰度 sub-byte
                    v = idx * 255 // mask
                    pixels.append((v, v, v, 255))
    return w, h, pixels


# ---------------- PNG 编码（8-bit RGB） ----------------
def encode_png_rgb(w, h, pixels):
    def chunk(typ, data):
        return (struct.pack(">I", len(data)) + typ + data +
                struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)   # 8-bit, color type 2 (RGB)

    raw = bytearray()
    for y in range(h):
        raw.append(0)                                      # 过滤类型 0
        for x in range(w):
            px = pixels[y * w + x]
            raw += bytes(px[:3])                           # 兼容 3 元组(已填背景)与 4 元组

    return (PNG_SIG + chunk(b"IHDR", ihdr) +
            chunk(b"IDAT", zlib.compress(bytes(raw), 9)) +
            chunk(b"IEND", b""))


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
                w, h, px = decode_png(raw)
            except Exception as e:
                print(f"  ⚠️  跳过一帧: {e}")
                skipped += 1
                after_total += len(b64)
                continue

            # 透明像素填成主题背景色
            filled = [(r, g, b) if a >= 128 else bg for (r, g, b, a) in px]
            new_png = encode_png_rgb(w, h, filled)
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
