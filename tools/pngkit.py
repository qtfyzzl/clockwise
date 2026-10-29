#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PNG 编解码（纯标准库，只用 zlib + struct）

为什么要有这个模块：同一套 chunk + CRC32 + zlib 逻辑原来散在四处
（editor/cw_core.py、tools/fix_theme_images.py、tools/preview_clockface.py、
tools/check_theme.py），改一处漏一处就会复发 —— 比如设备只支持 8-bit RGB，
而 encode_indexed 会按调色板大小自动选 1/2/4 位深，正是它造成了设备闪退。

现在统一在这里，所有工具和编辑器都从这里引。

设备兼容性（重要的背景，改代码前先读）：
  · 只支持 PNG，不认 JPEG/BMP/GIF
  · 8-bit RGB(2) / RGBA(6) 最稳；8-bit 调色板(3) 可用
  · **1-bit / 2-bit 索引色会让设备端 PNGdec 跳到空指针，设备无限重启**
  · 单张解码后 ≤ 4096 字节（IMAGE_BUFFER_SIZE）
"""

import struct
import zlib

PNG_SIG = b"\x89PNG\r\n\x1a\n"


# ------------------------------------------------------------------ 基础

def is_png(raw):
    return raw[:8] == PNG_SIG


def kind(raw):
    """判断图片格式，用于给出可读的错误信息。"""
    if is_png(raw):
        return "PNG"
    if raw[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if raw[:4] == b"GIF8":
        return "GIF"
    if raw[:2] == b"BM":
        return "BMP"
    if raw[:4] == b"RIFF":
        return "WEBP"
    return "未知格式"


def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


# ------------------------------------------------------------------ 读

def info(raw):
    """只读文件头，不展开像素。

    返回 (宽, 高, 位深, 颜色类型, PLTE字节数)；不是 PNG 返回 None。
    校验工具用它做格式判断，不需要解压 IDAT。
    """
    if len(raw) < 33 or not is_png(raw):
        return None

    w, h = struct.unpack(">II", raw[16:24])
    bitdepth, colortype = raw[24], raw[25]

    plte = 0
    i = 8
    while i + 8 <= len(raw):
        ln = struct.unpack(">I", raw[i:i + 4])[0]
        typ = raw[i + 4:i + 8]
        if typ == b"PLTE":
            plte = ln
        i += 12 + ln
        if typ == b"IEND":
            break
    return w, h, bitdepth, colortype, plte


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def decode(raw):
    """完整解码成 RGBA。

    返回 (宽, 高, [(r,g,b,a), ...])，按行优先。
    支持颜色类型 0/2/3/4/6，位深 1/2/4/8；不支持隔行（interlaced）。
    """
    if not is_png(raw):
        raise ValueError("不是 PNG（检测到 %s）" % kind(raw))

    w = h = bd = ct = interlace = None
    plte = b""
    trns = b""
    idat = b""

    pos = 8
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
    bpp = max(1, (channels * bd) // 8)
    stride = (w * channels * bd + 7) // 8

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
            raise ValueError("未知的过滤类型 %d" % ftype)
        rows.append(line)
        prev = line

    # 展开成 RGBA
    pixels = []
    for line in rows:
        if bd == 8:
            if ct == 3:
                pixels += [(plte[i * 3], plte[i * 3 + 1], plte[i * 3 + 2],
                            0 if (trns and i < len(trns) and trns[i] == 0) else 255)
                           for i in line[:w]]
            elif ct == 2:
                pixels += [(line[i * 3], line[i * 3 + 1], line[i * 3 + 2], 255)
                           for i in range(w)]
            elif ct == 6:
                pixels += [(line[i * 4], line[i * 4 + 1], line[i * 4 + 2], line[i * 4 + 3])
                           for i in range(w)]
            elif ct == 0:
                pixels += [(line[i], line[i], line[i], 255) for i in range(w)]
            elif ct == 4:
                pixels += [(line[i * 2], line[i * 2], line[i * 2], line[i * 2 + 1])
                           for i in range(w)]
        else:                       # 位深 1/2/4：每字节装多个像素
            per_byte = 8 // bd
            mask = (1 << bd) - 1
            for x in range(w):
                byte = line[x // per_byte]
                shift = 8 - bd * (x % per_byte + 1)
                idx = (byte >> shift) & mask
                if ct == 3:
                    pixels.append((plte[idx * 3], plte[idx * 3 + 1], plte[idx * 3 + 2],
                                   0 if (trns and idx < len(trns) and trns[idx] == 0) else 255))
                else:
                    v = idx * 255 // mask
                    pixels.append((v, v, v, 255))
    return w, h, pixels


# ------------------------------------------------------------------ 写

def _rows_from_pixels(width, height, pixels):
    """把 bytes / [(r,g,b)] / [(r,g,b,a)] 统一成「每行前缀 0 + RGB」的字节流。"""
    if isinstance(pixels, (bytes, bytearray)):
        stride = width * 3
        if len(pixels) < stride * height:
            raise ValueError("像素数据不足：需要 %d 字节，实际 %d"
                             % (stride * height, len(pixels)))
        return b"".join(b"\x00" + bytes(pixels[y * stride:(y + 1) * stride])
                        for y in range(height))

    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            px = pixels[y * width + x]
            row += bytes(px[:3])
        rows.append(bytes(row))
    return b"".join(rows)


def encode_rgb(width, height, pixels, level=9):
    """编码成 8-bit RGB PNG（颜色类型 2）。

    设备唯一稳妥支持的格式。纯色块经 zlib 压缩后体积很小
    （64x22 的点阵字每帧约 200~300 字节）。

    pixels: bytes（宽*高*3 的 RGB 序列）或 [(r,g,b)] / [(r,g,b,a)] 列表
    """
    raw = _rows_from_pixels(width, height, pixels)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (PNG_SIG + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw, level))
            + _chunk(b"IEND", b""))


def encode_indexed(indices, palette, width, height, level=9):
    """索引色 PNG（颜色类型 3），位深按调色板大小自动选 1/2/4/8。

    ⚠️ **设备不支持位深 1/2**：PNGdec 解码时会跳到空指针，表现为设备无限重启。
    仅供旧脚本/测试保留；导出给设备的主题请用 encode_rgb()。
    """
    n = max(1, len(palette))
    bd = 1 if n <= 2 else 2 if n <= 4 else 4 if n <= 16 else 8

    rows = []
    for y in range(height):
        base = y * width
        if bd == 8:
            rows.append(b"\x00" + bytes(bytearray(indices[base:base + width])))
            continue
        per = 8 // bd
        row = bytearray([0])
        acc = cnt = 0
        for x in range(width):
            acc = (acc << bd) | (indices[base + x] & ((1 << bd) - 1))
            cnt += 1
            if cnt == per:
                row.append(acc); acc = cnt = 0
        if cnt:
            acc <<= bd * (per - cnt)
            row.append(acc)
        rows.append(bytes(row))

    ihdr = struct.pack(">IIBBBBB", width, height, bd, 3, 0, 0, 0)
    plte = b"".join(bytes(bytearray(c[:3])) for c in palette)
    return (PNG_SIG + _chunk(b"IHDR", ihdr) + _chunk(b"PLTE", plte)
            + _chunk(b"IDAT", zlib.compress(b"".join(rows), level))
            + _chunk(b"IEND", b""))
