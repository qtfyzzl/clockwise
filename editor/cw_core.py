#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ClockWise Canvas 主题核心库（无 GUI，可独立测试）。

覆盖四件事：
  1. RGB565 颜色换算（Canvas JSON 只认十进制 565）
  2. Adafruit GFXfont 位图字体渲染（与固件 getTextBounds / drawChar 一致）
  3. 64x64 画面渲染（复刻 Clockface::renderElements / refreshDateTime）
  4. 图片压缩：缩放 → 调色板量化 → **8-bit RGB PNG**
     （解码后必须 <=4096 字节；禁止 1/2-bit 索引色，PNGdec 1.0.1 会崩溃重启）
"""

import base64
import io
import json
import os
import sys

# pngkit 在仓库的 tools/ 下。开发时直接 import；PyInstaller 打包时
# build_exe.py 会用 --paths 指向该目录，模块会被打进 exe。
try:
    import pngkit
except ImportError:
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
    import pngkit
import os
import re
import struct
import sys
import zlib
from datetime import datetime

from PIL import Image

# ---------------------------------------------------------------- 固件限制

PANEL = 64
JSON_DOC_CAPACITY = 16384     # firmware: CanvasClockface.cpp DynamicJsonDocument doc(16384)
JSON_SAFE_BYTES = 15000       # 留 ~1.4KB 余量（ArduinoJson 池按 token 计，不按文件字节）
IMAGE_DECODE_LIMIT = 4096     # PNGRender.h: IMAGE_BUFFER_SIZE（上游 1024，定制固件已提到 4096）
MAX_THEME_PIXELS = 40000      # 精灵总像素（帧数×宽×高）建议上限，超过易掉帧
IMAGE_MAX_WIDTH = 64          # PNGRender.h: uint16_t usPixels[64]
IMAGE_MAX_HEIGHT = 64
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

ELEMENT_TYPES = ("text", "datetime", "rect", "fillrect", "line", "image")
FONT_NAMES = ("big", "medium", "square", "picopixel", "default")

TYPE_LABELS = {
    "text": "静态文字",
    "datetime": "时间/日期",
    "rect": "空心矩形",
    "fillrect": "实心矩形",
    "line": "直线",
    "image": "图片",
}


# ---------------------------------------------------------------- 颜色

def rgb_to_565(rgb):
    r, g, b = (int(v) & 0xFF for v in rgb[:3])
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def rgb565_to_rgb(value):
    v = int(value) & 0xFFFF
    r = (v >> 11) & 0x1F
    g = (v >> 5) & 0x3F
    b = v & 0x1F
    return (r * 255 // 31, g * 255 // 63, b * 255 // 31)


def hex_to_rgb(text):
    h = (text or "").strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError("需要 #RRGGBB")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(rgb):
    return "#%02X%02X%02X" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def hex_to_565(text):
    return rgb_to_565(hex_to_rgb(text))


def rgb565_to_hex(value):
    return rgb_to_hex(rgb565_to_rgb(value))


# ---------------------------------------------------------------- 位图字体

class BitmapFont(object):
    """Adafruit GFXfont 或经典 5x7 固定字体。

    GFX 字体：字形条目 (bitmapOffset, width, height, xAdvance, xOffset, yOffset)，
    光标 y 是基线；经典字体：5x8 点阵，光标 y 是格子顶部。
    """

    def __init__(self, name, data):
        self.name = name
        self.kind = data.get("kind", "gfx")
        self.bitmaps = bytes(bytearray(data["bitmaps"]))
        if self.kind == "gfx":
            self.first = data["first"]
            self.last = data["last"]
            self.yadv = data["yadv"]
            self.glyphs = [tuple(g) for g in data["glyphs"]]
        else:
            self.first = 0
            self.last = len(self.bitmaps) // 5 - 1
            self.yadv = data.get("height", 8)
            self.cw = data.get("width", 5)
            self.ch = data.get("height", 8)
            self.advance = data.get("advance", 6)

    # -- 单个字符度量 --
    def metrics(self, ch):
        code = ord(ch)
        if self.kind == "classic":
            if code > self.last:
                return None
            return (0, self.cw, self.ch, self.advance, 0, 0)
        if code < self.first or code > self.last:
            return None
        return self.glyphs[code - self.first]

    def pixels(self, ch):
        """相对光标左上/基线光标的像素坐标列表（未做偏移）。"""
        m = self.metrics(ch)
        if m is None:
            return
        if self.kind == "classic":
            code = ord(ch)
            base = code * self.cw
            for col in range(self.cw):
                line = self.bitmaps[base + col]
                for row in range(8):
                    if line & (1 << row):
                        yield (col, row)
            return
        off, w, h, _xa, _xo, _yo = m
        if not w or not h:
            return
        # 复刻 Adafruit_GFX::drawChar：MSB 先出，每 8 像素换一个字节。
        idx = off
        bo = self.bitmaps[idx] if idx < len(self.bitmaps) else 0
        bitmask = 0x80
        for row in range(h):
            for col in range(w):
                if bo & bitmask:
                    yield (col, row)
                bitmask >>= 1
                if bitmask == 0:
                    bitmask = 0x80
                    idx += 1
                    bo = self.bitmaps[idx] if idx < len(self.bitmaps) else 0

    # -- 文本包围盒（复刻 getTextBounds）--
    def text_bounds(self, text, x=0, y=0):
        cx, cy = x, y
        minx = miny = 1 << 20
        maxx = maxy = -(1 << 20)
        for ch in text:
            if ch == "\n":
                cx = x
                cy += self.yadv
                continue
            if ch == "\r":
                continue
            m = self.metrics(ch)
            if m is None:
                continue
            _off, w, h, xadv, xoff, yoff = m
            xo, yo = cx + xoff, cy + yoff
            if w and h:
                minx = min(minx, xo)
                maxx = max(maxx, xo + w)
                miny = min(miny, yo)
                maxy = max(maxy, yo + h)
            cx += xadv
        if maxx < minx:
            return (0, 0, 0, 0, 0)
        return (minx, miny, maxx - minx, maxy - miny, cx - x)


_FONT_CACHE = {}


def load_fonts(data_path=None):
    """载入 fontdata.json（PyInstaller onefile 下从 _MEIPASS 取）。"""
    global _FONT_CACHE
    if _FONT_CACHE:
        return _FONT_CACHE
    if data_path is None:
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        data_path = os.path.join(base, "fontdata.json")
    with open(data_path, encoding="utf-8") as f:
        raw = json.load(f)
    for name, data in raw["fonts"].items():
        _FONT_CACHE[name] = BitmapFont(name, data)
    return _FONT_CACHE


def get_font(name):
    fonts = load_fonts()
    key = (name or "").strip().lower()
    if key in fonts:
        return fonts[key]
    return fonts.get("default") or fonts.get("picopixel")


# ---------------------------------------------------------------- 绘图原语

def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _xy(el):
    """元素左上角整数坐标。"""
    return _int(el.get("x")), _int(el.get("y"))


def _wh(el):
    """矩形类元素宽高。"""
    return _int(el.get("width")), _int(el.get("height"))


def _clip(value, lo, hi):
    return lo if value < lo else (hi if value > hi else value)


class Canvas(object):
    """64x64 像素画布，坐标语义与 Adafruit_GFX 一致（自动裁剪）。"""

    def __init__(self, bg=0):
        self.img = Image.new("RGB", (PANEL, PANEL), rgb565_to_rgb(bg))
        self.px = self.img.load()

    def put(self, x, y, rgb):
        if 0 <= x < PANEL and 0 <= y < PANEL:
            self.px[x, y] = rgb

    def fill_rect(self, x, y, w, h, value):
        if w <= 0 or h <= 0:
            return
        rgb = rgb565_to_rgb(value)
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(PANEL, x + w), min(PANEL, y + h)
        for yy in range(y0, y1):
            for xx in range(x0, x1):
                self.px[xx, yy] = rgb

    def draw_rect(self, x, y, w, h, value):
        if w <= 0 or h <= 0:
            return
        rgb = rgb565_to_rgb(value)
        for xx in range(x, x + w):
            self.put(xx, y, rgb)
            self.put(xx, y + h - 1, rgb)
        for yy in range(y, y + h):
            self.put(x, yy, rgb)
            self.put(x + w - 1, yy, rgb)

    def draw_line(self, x0, y0, x1, y1, value):
        """复刻 Adafruit_GFX::drawLine（Bresenham，含 steep 处理）。"""
        rgb = rgb565_to_rgb(value)
        steep = abs(y1 - y0) > abs(x1 - x0)
        if steep:
            x0, y0 = y0, x0
            x1, y1 = y1, x1
        if x0 > x1:
            x0, x1 = x1, x0
            y0, y1 = y1, y0
        dx = x1 - x0
        dy = abs(y1 - y0)
        err = dx // 2
        ystep = 1 if y0 < y1 else -1
        y = y0
        for x in range(x0, x1 + 1):
            if steep:
                self.put(y, x, rgb)
            else:
                self.put(x, y, rgb)
            err -= dy
            if err < 0:
                y += ystep
                err += dx

    def draw_text(self, font, x, y, text, fg, bg=None):
        """与 Clockface::renderText 一致：先按包围盒填 bgColor，再打点。"""
        if not text:
            return
        x1, y1, w, h, _adv = font.text_bounds(text, 0, 0)
        if bg is not None and w and h:
            self.fill_rect(x + x1, y + y1, w, h, bg)
        fg_rgb = rgb565_to_rgb(fg)
        cx, cy = x, y
        for ch in text:
            if ch == "\n":
                cx, cy = x, cy + font.yadv
                continue
            if ch == "\r":
                continue
            m = font.metrics(ch)
            if m is None:
                continue
            _off, gw, gh, xadv, xoff, yoff = m
            if gw and gh:
                bx, by = cx + xoff, cy + yoff
                for dx, dy in font.pixels(ch):
                    self.put(bx + dx, by + dy, fg_rgb)
            cx += xadv

    def paste_png_b64(self, b64, x, y):
        try:
            raw = base64.b64decode(b64)
            im = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception:
            return False
        w, h = im.size
        for yy in range(h):
            for xx in range(w):
                px = x + xx
                py = y + yy
                if 0 <= px < PANEL and 0 <= py < PANEL:
                    self.px[px, py] = im.getpixel((xx, yy))
        return True


def io_bytes(data):
    return io.BytesIO(data)


# ---------------------------------------------------------------- 时间格式

_SHORT_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_LONG_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_SHORT_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_LONG_MONTHS = ("January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December")


def php_datetime(fmt, when=None):
    """把 ezTime/PHP 风格格式串渲染成文本（只实现常用符）。"""
    if fmt is None:
        return ""
    dt = when or datetime.now()
    out = []
    i = 0
    n = len(fmt)
    while i < n:
        ch = fmt[i]
        if ch == "\\" and i + 1 < n:
            out.append(fmt[i + 1])
            i += 2
            continue
        if ch == "d":
            out.append("%02d" % dt.day)
        elif ch == "j":
            out.append(str(dt.day))
        elif ch == "D":
            out.append(_SHORT_DAYS[dt.weekday()])
        elif ch == "l":
            out.append(_LONG_DAYS[dt.weekday()])
        elif ch == "N":
            out.append(str(dt.isoweekday()))
        elif ch == "w":
            out.append(str(dt.weekday() + 1 if dt.weekday() < 6 else 0))
        elif ch == "m":
            out.append("%02d" % dt.month)
        elif ch == "n":
            out.append(str(dt.month))
        elif ch == "M":
            out.append(_SHORT_MONTHS[dt.month - 1])
        elif ch == "F":
            out.append(_LONG_MONTHS[dt.month - 1])
        elif ch == "Y":
            out.append("%04d" % dt.year)
        elif ch == "y":
            out.append("%02d" % (dt.year % 100))
        elif ch == "H":
            out.append("%02d" % dt.hour)
        elif ch == "G":
            out.append(str(dt.hour))
        elif ch == "h":
            out.append("%02d" % (dt.hour % 12 or 12))
        elif ch == "g":
            out.append(str(dt.hour % 12 or 12))
        elif ch == "i":
            out.append("%02d" % dt.minute)
        elif ch == "s":
            out.append("%02d" % dt.second)
        elif ch == "A":
            out.append("AM" if dt.hour < 12 else "PM")
        elif ch == "a":
            out.append("am" if dt.hour < 12 else "pm")
        elif ch == "U":
            out.append(str(int(dt.timestamp()) if dt.year > 1970 else 0))
        elif ch == "z":
            out.append(str(dt.timetuple().tm_yday - 1))
        else:
            out.append(ch)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------- 主题渲染

def element_text(el, when=None):
    kind = el.get("type")
    content = el.get("content", "")
    if kind == "datetime":
        return php_datetime(content, when)
    return content or ""


def render_theme(theme, when=None):
    """按固件顺序渲染 setup 元素（sprites/loop 不参与静态预览）。"""
    canvas = Canvas(theme.get("bgColor", 0))
    for el in theme.get("setup", []) or []:
        try:
            render_element(canvas, el, when)
        except Exception:
            continue
    return canvas.img


# ---------------------------------------------------------------- 精灵动画

def _sprite_frames(theme, ref):
    """返回 sprites[ref] 的帧列表；越界/缺帧返回 []。"""
    groups = theme.get("sprites", []) or []
    if not (0 <= ref < len(groups)):
        return []
    return groups[ref] or []


def _sprite_frame_image(theme, ref, frame_idx):
    frames = _sprite_frames(theme, ref)
    if not frames or not (0 <= frame_idx < len(frames)):
        return None
    return (frames[frame_idx] or {}).get("image") or None


def _default_delay(theme):
    try:
        d = int(theme.get("delay", 300) or 0)
    except (TypeError, ValueError):
        d = 0
    return d if d > 0 else 300


def sprite_state(theme, loop_entry, t_ms):
    """复刻固件 handleSpriteAnimation + handleSpriteMovement，返回 (frame_idx, x, y)。

    固件逻辑要点：
      - 帧推进：每 frameDelay 毫秒 +1，直到 totalFrames；达到 loopDelay 后归零
      - 位移：moveDuration>0 且 (moveTargetX>-1 或 moveTargetY>-1) 时，每 moveStartTime 触发，
        在 moveDuration 内从 (x,y) 线性插值到 (moveTargetX, moveTargetY)；
        shouldReturnToOrigin 为真则到位后反向回起点（往返）
    """
    ref = int(loop_entry.get("sprite", 0) or 0)
    total = len(_sprite_frames(theme, ref))
    if total <= 0:
        return None
    base_delay = _default_delay(theme)

    frame_delay = int(loop_entry.get("frameDelay", 0) or 0) or base_delay
    loop_delay = int(loop_entry.get("loopDelay", 0) or 0) or base_delay
    loop_delay = max(1, loop_delay)

    # 帧动画（循环周期 loopDelay 内按 frameDelay 切帧）
    if loop_delay > 0:
        within = t_ms % loop_delay
        frame_idx = min(total - 1, int(within // frame_delay))
    else:
        frame_idx = min(total - 1, int(t_ms // frame_delay))

    x = int(loop_entry.get("x", 0) or 0)
    y = int(loop_entry.get("y", 0) or 0)

    # 位移
    move_start = int(loop_entry.get("moveStartTime", 0) or 0) or 1
    move_dur = int(loop_entry.get("moveDuration", 0) or 0)
    target_x = int(loop_entry.get("moveTargetX", -1) or 0) if loop_entry.get("moveTargetX", -1) not in (None, -1) else -1
    target_y = int(loop_entry.get("moveTargetY", -1) or 0) if loop_entry.get("moveTargetY", -1) not in (None, -1) else -1
    ret_origin = bool(loop_entry.get("shouldReturnToOrigin", False))

    if move_dur > 0 and (target_x > -1 or target_y > -1):
        # 位移触发周期 = moveStartTime（固件用 currentSecond*1000 % moveStartTime 对齐秒）
        period = max(1, move_start)
        within_period = t_ms % period
        # 在一个 period 内，前 move_dur 走「去」，若往返则后 move_dur 走「回」
        cycle = 2 * move_dur if ret_origin else move_dur
        phase = within_period % cycle if cycle > 0 else 0
        if phase < move_dur:
            progress = phase / float(move_dur)
            tx, ty = target_x, target_y
        elif ret_origin:
            progress = (phase - move_dur) / float(move_dur)
            tx, ty = x, y  # 反向回到起点
        else:
            progress = 1.0
            tx, ty = target_x, target_y

        sx = x if ret_origin and phase >= move_dur else x
        sy = y if ret_origin and phase >= move_dur else y
        ex = tx if ret_origin else target_x
        ey = ty if ret_origin else target_y
        # 反向段：从 target 回到 origin
        if ret_origin and phase >= move_dur:
            sx, sy = target_x, target_y
            ex, ey = x, y
        cur_x = sx + int(progress * (ex - sx))
        cur_y = sy + int(progress * (ey - sy))
        x, y = cur_x, cur_y

    return frame_idx, x, y


def render_theme_animated(theme, t_ms=0, when=None):
    """渲染 setup + 精灵动画（给定动画时刻 t_ms，单位毫秒）。"""
    canvas = Canvas(theme.get("bgColor", 0))
    for el in theme.get("setup", []) or []:
        try:
            render_element(canvas, el, when)
        except Exception:
            continue
    for entry in theme.get("loop", []) or []:
        try:
            if (entry or {}).get("type") != "sprite":
                continue
            st = sprite_state(theme, entry, t_ms)
            if st is None:
                continue
            frame_idx, x, y = st
            b64 = _sprite_frame_image(theme, int(entry.get("sprite", 0) or 0), frame_idx)
            if b64:
                canvas.paste_png_b64(b64, x, y)
        except Exception:
            continue
    return canvas.img


def render_element(canvas, el, when=None):
    kind = el.get("type")
    x, y = _xy(el)
    if kind in ("text", "datetime"):
        text = element_text(el, when)
        font = get_font(el.get("font"))
        fg = _int(el.get("fgColor", 65535))
        bg = el.get("bgColor")
        bg = None if bg is None else _int(bg)
        canvas.draw_text(font, x, y, text, fg, bg)
    elif kind in ("rect", "fillrect"):
        w, h = _wh(el)
        color = _int(el.get("color"))
        if kind == "fillrect":
            canvas.fill_rect(x, y, w, h, color)
        else:
            canvas.draw_rect(x, y, w, h, color)
    elif kind == "line":
        canvas.draw_line(x, y, _int(el.get("x1")), _int(el.get("y1")),
                         _int(el.get("color")))
    elif kind == "image":
        b64 = el.get("image") or ""
        if b64:
            canvas.paste_png_b64(b64, x, y)


def element_box(el, when=None):
    """元素在 64x64 上的包围盒 (x0,y0,x1,y1)，用于点选/拖拽。"""
    kind = el.get("type")
    x, y = _xy(el)
    if kind in ("text", "datetime"):
        font = get_font(el.get("font"))
        text = element_text(el, when)
        if not text:
            return (x, y, x + 4, y + (font.yadv if hasattr(font, "yadv") else 8))
        x1, y1, w, h, adv = font.text_bounds(text, 0, 0)
        if not w or not h:
            return (x, y, x + max(2, adv), y + 8)
        return (x + x1, y + y1, x + x1 + w, y + y1 + h)
    if kind in ("rect", "fillrect"):
        w, h = _wh(el)
        return (x, y, x + w, y + h)
    if kind == "line":
        x1, y1 = _int(el.get("x1")), _int(el.get("y1"))
        return (min(x, x1), min(y, y1), max(x, x1) + 1, max(y, y1) + 1)
    if kind == "image":
        size = image_size_from_b64(el.get("image") or "")
        w, h = size if size else (8, 8)
        return (x, y, x + w, y + h)
    return (x, y, x + 4, y + 4)


def image_size_from_b64(b64):
    if not b64:
        return None
    try:
        im = Image.open(io_bytes(base64.b64decode(b64)))
        return im.size
    except Exception:
        return None


# ---------------------------------------------------------------- 8-bit RGB PNG

def encode_rgb_png(rgb_bytes, width, height, level=9):
    """编码成 8-bit RGB PNG（设备唯一稳妥支持的格式）。实现见 tools/pngkit.py。"""
    return pngkit.encode_rgb(width, height, rgb_bytes, level=level)


def encode_indexed_png(indices, palette, width, height, level=9):
    """索引色 PNG。⚠️ 位深 1/2 会让设备闪退，仅供旧脚本/测试。"""
    return pngkit.encode_indexed(indices, palette, width, height, level=level)


class ImageResult(object):
    def __init__(self, png, indices, palette, width, height, colors):
        self.png = png
        self.indices = indices
        self.palette = palette
        self.width = width
        self.height = height
        self.colors = colors

    @property
    def size(self):
        return len(self.png)

    @property
    def ok(self):
        return len(self.png) <= IMAGE_DECODE_LIMIT

    @property
    def b64(self):
        return base64.b64encode(self.png).decode("ascii")

    def image(self, scale=1):
        im = Image.new("RGB", (self.width, self.height))
        im.putdata([tuple(self.palette[i]) for i in self.indices])
        if scale > 1:
            im = im.resize((self.width * scale, self.height * scale), Image.NEAREST)
        return im


def _flatten(img, bg):
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        base = Image.new("RGB", rgba.size, bg)
        base.paste(rgba, mask=rgba.split()[-1])
        return base
    return img.convert("RGB")


def _fit_image(img, max_w, max_h, mode, smooth):
    """mode: contain(不放大) / fit(等比放大) / cover(裁切填满) / stretch(拉伸)"""
    resample = Image.LANCZOS if smooth else Image.NEAREST
    w, h = img.size
    max_w = max(1, int(max_w))
    max_h = max(1, int(max_h))
    if mode == "stretch":
        out = img.resize((max_w, max_h), resample)
        return out
    rw, rh = float(max_w) / w, float(max_h) / h
    if mode == "contain":
        scale = min(1.0, min(rw, rh))
    elif mode == "cover":
        scale = max(rw, rh)
    else:  # fit
        scale = min(rw, rh)
    nw = max(1, min(max_w, int(round(w * scale))))
    nh = max(1, min(max_h, int(round(h * scale))))
    out = img if (nw, nh) == (w, h) else img.resize((nw, nh), resample)
    if mode == "cover" and (out.width > max_w or out.height > max_h):
        left = max(0, (out.width - max_w) // 2)
        top = max(0, (out.height - max_h) // 2)
        out = out.crop((left, top, left + max_w, top + max_h))
    return out


def prepare_image(src, max_w=32, max_h=32, colors=8, dither=False, bg=(0, 0, 0),
                  mode="contain", smooth=True, level=9):
    """缩放 → 量化到 N 色调色板 → 索引色 PNG。返回 ImageResult。"""
    img = _flatten(src, bg)
    img = _fit_image(img, max_w, max_h, mode, smooth)
    colors = max(1, min(256, int(colors)))
    dith = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    q = img.convert("P", palette=Image.ADAPTIVE, colors=colors, dither=dith)
    idx = list(q.getdata())
    used = max(idx) + 1 if idx else 1
    pal_raw = q.getpalette() or []
    pal = []
    for i in range(max(used, 1)):
        base = i * 3
        if base + 2 < len(pal_raw):
            pal.append((pal_raw[base], pal_raw[base + 1], pal_raw[base + 2]))
        else:
            pal.append((0, 0, 0))
    width, height = img.size
    # 量化到少量颜色（压体积），但仍以 8-bit RGB 输出（设备只认这个）。
    # 纯色块经 zlib 压缩后通常每帧只有一两百字节，比低位深索引色大不了多少。
    rgb_bytes = q.convert("RGB").tobytes()
    png = encode_rgb_png(rgb_bytes, width, height, level=level)
    return ImageResult(png, idx, pal, width, height, len(pal))


def auto_fit_image(src, limit=IMAGE_DECODE_LIMIT, max_w=64, max_h=64, bg=(0, 0, 0),
                   mode="contain", smooth=True, dither=False):
    """自动在「尺寸 × 色数」里挑满足体积上限、观感最好的组合。"""
    sizes = [40, 36, 32, 28, 24, 20, 16, 12, 8]
    color_set = [16, 8, 4, 2]
    best = None
    best_score = -1.0
    for size in sizes:
        mw = min(size, max_w)
        mh = min(size, max_h)
        for colors in color_set:
            res = prepare_image(src, mw, mh, colors, dither=dither, bg=bg,
                                mode=mode, smooth=smooth)
            if res.size > limit:
                continue
            score = res.width * res.height * (1.0 + 0.35 * (colors.bit_length() - 1))
            if score > best_score:
                best, best_score = res, score
    return best


def crop_image(img, box):
    """按 (left, top, right, bottom) 裁剪。自动 clamp 到图片边界。"""
    w, h = img.size
    left, top, right, bottom = box
    left = max(0, min(w, int(left)))
    top = max(0, min(h, int(top)))
    right = max(left + 1, min(w, int(right)))
    bottom = max(top + 1, min(h, int(bottom)))
    return img.crop((left, top, right, bottom))


def gen_image_options(src, bg=(0, 0, 0), dither=False, smooth=True,
                      limit=IMAGE_DECODE_LIMIT, max_w=64, max_h=64, mode="contain"):
    """生成一组「尺寸 × 色数」的压缩候选，供用户选择。

    返回列表，每项 dict：{result, size, colors, bytes, b64}，按体积/观感从大到小排序。
    mode 与 prepare_image 一致：contain / fit / cover / stretch。
    """
    options = []
    sizes = [48, 40, 32, 24, 16, 8]
    color_set = [16, 8, 4, 2]
    seen = set()
    for size in sizes:
        mw = min(size, max_w)
        mh = min(size, max_h)
        for colors in color_set:
            try:
                res = prepare_image(src, mw, mh, colors, dither=dither, bg=bg,
                                    mode=mode, smooth=smooth)
            except Exception:
                continue
            key = (res.width, res.height, res.colors)
            if key in seen:
                continue
            seen.add(key)
            options.append({
                "result": res,
                "size": (res.width, res.height),
                "colors": res.colors,
                "bytes": res.size,
                "ok": res.ok,
                "b64": res.b64,
            })
    options.sort(key=lambda o: (o["bytes"], o["size"][0] * o["size"][1],
                                o["colors"]), reverse=True)
    return options


# ---------------------------------------------------------------- 主题 JSON

def default_theme():
    return {
        "name": "New Theme",
        "version": 1,
        "author": "@you",
        "bgColor": 0,
        "delay": 300,
        "setup": [],
        "sprites": [],
        "loop": [],
    }


def new_element(kind):
    base = {"type": kind}
    if kind == "text":
        base.update({"content": "Hello", "font": "medium", "fgColor": 65535,
                     "bgColor": 0, "x": 4, "y": 20})
    elif kind == "datetime":
        base.update({"content": "H:i", "font": "big", "fgColor": 65535,
                     "bgColor": 0, "x": 11, "y": 34})
    elif kind == "rect":
        base.update({"color": 8452, "x": 1, "y": 1, "width": 62, "height": 62})
    elif kind == "fillrect":
        base.update({"color": 2113, "x": 8, "y": 8, "width": 48, "height": 48})
    elif kind == "line":
        base.update({"color": 12678, "x": 8, "y": 32, "x1": 56, "y1": 32})
    elif kind == "image":
        base.update({"image": "", "x": 16, "y": 16})
    return base


FIELD_ORDER = {
    "text": ("type", "content", "font", "fgColor", "bgColor", "x", "y"),
    "datetime": ("type", "content", "font", "fgColor", "bgColor", "x", "y"),
    "rect": ("type", "color", "x", "y", "width", "height"),
    "fillrect": ("type", "color", "x", "y", "width", "height"),
    "line": ("type", "color", "x", "y", "x1", "y1"),
    "image": ("type", "image", "x", "y"),
}

ROOT_ORDER = ("name", "version", "author", "bgColor", "delay", "setup", "sprites", "loop")


def ordered_theme(theme):
    """按固件示例的字段顺序输出，导出文件更易读、diff 更稳定。"""
    out = {}
    for key in ROOT_ORDER:
        if key in theme:
            out[key] = theme[key]
    for key, value in theme.items():
        if key not in out:
            out[key] = value
    els = []
    for el in out.get("setup", []) or []:
        kind = el.get("type")
        order = FIELD_ORDER.get(kind)
        if not order:
            els.append(el)
            continue
        item = {}
        for key in order:
            if key in el:
                item[key] = el[key]
        for key, value in el.items():
            if key not in item:
                item[key] = value
        els.append(item)
    out["setup"] = els
    return out


def theme_to_json(theme, indent=2):
    return json.dumps(ordered_theme(theme), indent=indent, ensure_ascii=False)


def theme_bytes(theme, indent=2):
    return len(theme_to_json(theme, indent).encode("utf-8"))


def load_theme_file(path):
    with open(path, encoding="utf-8") as f:
        theme = json.load(f)
    if not isinstance(theme, dict):
        raise ValueError("JSON 根节点必须是对象")
    theme.setdefault("setup", [])
    theme.setdefault("sprites", [])
    theme.setdefault("loop", [])
    theme.setdefault("bgColor", 0)
    return theme


# ---------------------------------------------------------------- 校验

def png_meta(raw):
    """解析 PNG IHDR。返回 (w, h, bitdepth, colortype, interlaced) 或 None。"""
    if len(raw) < 33 or raw[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", raw[16:24])
    return (w, h, raw[24], raw[25], raw[28])


def _check_png_compat(raw, tag, add):
    """按 THEME-SPEC 检查 PNG 位深/颜色类型/隔行，返回 (w, h) 或 None。"""
    meta = png_meta(raw)
    if meta is None:
        add("error", "%s 不是合法 PNG（PNGdec 只吃 PNG）" % tag)
        return None
    w, h, bd, ct, inter = meta
    if inter:
        add("error", "%s 是隔行扫描 PNG，设备拒绝绘制（导出时选非隔行）" % tag)
    if ct == 3 and bd in (1, 2):
        add("error", "%s 是 %d-bit 索引色 PNG → PNGdec 1.0.1 位解包缺陷，"
                     "设备会无限重启；请导出 8-bit RGB/RGBA" % (tag, bd))
    elif ct == 3:
        add("warn", "%s 是 %d-bit 调色板 PNG（官方主题可用，但建议 8-bit RGB 最稳）"
            % (tag, bd))
    elif ct not in (0, 2, 6):
        add("error", "%s PNG 颜色类型 %d 不受支持" % (tag, ct))
    elif bd != 8:
        add("warn", "%s 位深 %d（建议 8-bit）" % (tag, bd))
    return (w, h)


def validate(theme, when=None, size=None):
    """返回 [(level, message)]，level ∈ error/warn/info。

    size 可由调用方预先算好传入，避免同一轮刷新里重复序列化整份主题。
    """
    issues = []

    def add(level, msg):
        issues.append((level, msg))

    if size is None:
        size = theme_bytes(theme)
    if size > JSON_DOC_CAPACITY:
        add("error", "JSON %d B 超过固件缓冲区 %d B，设备会解析失败" % (size, JSON_DOC_CAPACITY))
    elif size > JSON_SAFE_BYTES:
        add("warn", "JSON %d B 接近上限 %d B，建议精简" % (size, JSON_DOC_CAPACITY))

    name = str(theme.get("name", ""))
    if not name:
        add("warn", "主题缺少 name（只影响串口日志）")

    for i, el in enumerate(theme.get("setup", []) or []):
        kind = el.get("type")
        tag = "第 %d 个元素(%s)" % (i + 1, TYPE_LABELS.get(kind, kind))
        if kind not in ELEMENT_TYPES:
            add("error", "%s 类型固件不认识，会被跳过" % tag)
            continue
        for key in ("x", "y"):
            if key not in el:
                add("error", "%s 缺少 %s" % (tag, key))
        if kind in ("text", "datetime"):
            font_name = el.get("font", "")
            if font_name and font_name not in FONT_NAMES:
                add("warn", "%s 字体 %r 未定义，固件会用默认 5x7" % (tag, font_name))
            text = element_text(el, when)
            font = get_font(font_name)
            x1, y1, w, h, adv = font.text_bounds(text, 0, 0)
            x, y = _int(el.get("x")), _int(el.get("y"))
            if w > PANEL:
                add("warn", "%s 墨迹宽 %d px > 64，两侧会被裁掉" % (tag, w))
            if kind == "text" and font_name == "square" and w <= 12:
                add("warn", "%s square 字体只有 12 个字形有内容，非数字文本几乎看不见" % tag)
            if x + x1 < 0 or y + y1 < 0 or x + x1 + w > PANEL or y + y1 + h > PANEL:
                add("info", "%s 包围盒 (%d,%d)-(%d,%d) 超出屏幕边界"
                    % (tag, x + x1, y + y1, x + x1 + w, y + y1 + h))
        elif kind in ("rect", "fillrect"):
            w = _int(el.get("width"))
            h = _int(el.get("height"))
            if w <= 0 or h <= 0:
                add("error", "%s 宽高必须 > 0" % tag)
            if _int(el.get("x")) + w > PANEL or _int(el.get("y")) + h > PANEL:
                add("info", "%s 超出屏幕右/下边界，会被裁掉" % tag)
        elif kind == "line":
            for key in ("x", "y", "x1", "y1"):
                v = _int(el.get(key))
                if v < 0 or v > PANEL - 1:
                    add("warn", "%s %s=%d 超出 0..63" % (tag, key, v))
        elif kind == "image":
            b64 = el.get("image") or ""
            if not b64:
                add("error", "%s 还没有图片" % tag)
                continue
            try:
                raw = base64.b64decode(b64)
            except Exception:
                add("error", "%s base64 无法解码" % tag)
                continue
            if len(raw) > IMAGE_DECODE_LIMIT:
                add("error", "%s PNG %d B > %d B（IMAGE_BUFFER_SIZE），设备上不会显示"
                    % (tag, len(raw), IMAGE_DECODE_LIMIT))
            meta = _check_png_compat(raw, tag, add)
            if meta is None:
                continue
            box = element_box(el, when)
            if box[2] - box[0] > IMAGE_MAX_WIDTH:
                add("error", "%s 宽 %d px > 64（usPixels[64]）" % (tag, box[2] - box[0]))
            if _int(el.get("y")) + (box[3] - box[1]) > PANEL:
                add("info", "%s 图片底部超出屏幕，会被裁掉" % tag)

    # ---- 精灵校验 ----
    groups = theme.get("sprites", []) or []
    loop = theme.get("loop", []) or []
    total_px = 0

    for gi, group in enumerate(groups):
        group = group or []
        if not group:
            add("warn", "精灵组 #%d 没有任何帧" % (gi + 1))
            continue
        # 帧尺寸一致性：固件 setDimensions 用第一帧的尺寸，各帧尺寸不一致会错位
        sizes = []
        for fi, frame in enumerate(group):
            frame = frame or {}
            b64 = frame.get("image") or ""
            if not b64:
                add("error", "精灵 #%d 第 %d 帧没有图片" % (gi + 1, fi + 1))
                continue
            try:
                raw = base64.b64decode(b64)
            except Exception:
                add("error", "精灵 #%d 第 %d 帧 base64 无法解码" % (gi + 1, fi + 1))
                continue
            if len(raw) > IMAGE_DECODE_LIMIT:
                add("error", "精灵 #%d 第 %d 帧 PNG %d B > %d B，设备上不显示"
                    % (gi + 1, fi + 1, len(raw), IMAGE_DECODE_LIMIT))
            if raw[:8] != b"\x89PNG\r\n\x1a\n":
                add("error", "精灵 #%d 第 %d 帧不是 PNG" % (gi + 1, fi + 1))
                continue
            meta = _check_png_compat(raw, "精灵 #%d 第 %d 帧" % (gi + 1, fi + 1), add)
            if meta is None:
                continue
            total_px += meta[0] * meta[1]
            sizes.append((meta[0], meta[1]))
        real = [s for s in sizes if s is not None]
        if len(set(real)) > 1:
            add("warn", "精灵组 #%d 各帧尺寸不一致 %s：固件用第一帧尺寸，其他帧会错位/裁切"
                % (gi + 1, real))

    if total_px > MAX_THEME_PIXELS:
        add("warn", "精灵总像素 %d > %d，动画可能掉帧（减少帧数或缩小尺寸）"
            % (total_px, MAX_THEME_PIXELS))

    for i, entry in enumerate(loop):
        entry = entry or {}
        tag = "loop #%d" % (i + 1)
        if entry.get("type") != "sprite":
            add("warn", "%s type=%r（固件只认 sprite）" % (tag, entry.get("type")))
            continue
        ref = int(entry.get("sprite", 0) or 0)
        if ref >= len(groups) or ref < 0:
            add("error", "%s 引用了不存在的精灵组 sprite=%d" % (tag, ref))
        # 位移目标越界提示
        tx = entry.get("moveTargetX", -1)
        ty = entry.get("moveTargetY", -1)
        if tx not in (None, -1) and (_int(tx) < 0 or _int(tx) > PANEL - 1):
            add("warn", "%s moveTargetX=%s 超出 0..63" % (tag, tx))
        if ty not in (None, -1) and (_int(ty) < 0 or _int(ty) > PANEL - 1):
            add("warn", "%s moveTargetY=%s 超出 0..63" % (tag, ty))

    return issues


def theme_summary(theme):
    setup = theme.get("setup", []) or []
    counts = {}
    for el in setup:
        counts[el.get("type")] = counts.get(el.get("type"), 0) + 1
    return {
        "bytes": theme_bytes(theme),
        "capacity": JSON_DOC_CAPACITY,
        "elements": len(setup),
        "counts": counts,
        "sprites": len(theme.get("sprites", []) or []),
    }


# ---------------------------------------------------------------- 导出

def render_preview_png(theme, scale=8, when=None):
    import io
    img = render_theme(theme, when)
    if scale > 1:
        img = img.resize((PANEL * scale, PANEL * scale), Image.NEAREST)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- 模板

TEMPLATES = {
    "极简（边框+分隔线+大字时间）": "minimal",
    "居中大字 + 日期": "bigcenter",
    "纯文字问候": "hello",
    "弹跳球动画（精灵）": "bounce",
}


def template_theme(key):
    if key == "bounce":
        return template_bounce()
    if key == "minimal":
        return {
            "name": "Custom Minimal", "version": 1, "author": "@you",
            "bgColor": 0, "delay": 300,
            "setup": [
                {"type": "rect", "color": 8452, "x": 1, "y": 1, "width": 62, "height": 62},
                {"type": "line", "color": 12678, "x": 10, "y": 30, "x1": 54, "y1": 30},
                {"type": "datetime", "content": "H:i", "font": "big",
                 "fgColor": 65535, "bgColor": 0, "x": 11, "y": 21},
                {"type": "datetime", "content": "m-d", "font": "picopixel",
                 "fgColor": 1625, "bgColor": 0, "x": 23, "y": 42},
            ],
            "sprites": [], "loop": [],
        }
    if key == "bigcenter":
        return {
            "name": "Big Center", "version": 1, "author": "@you",
            "bgColor": 0, "delay": 300,
            "setup": [
                {"type": "datetime", "content": "H:i", "font": "big",
                 "fgColor": 65535, "bgColor": 0, "x": 11, "y": 32},
                {"type": "datetime", "content": "D m/d", "font": "picopixel",
                 "fgColor": 2016, "bgColor": 0, "x": 14, "y": 46},
            ],
            "sprites": [], "loop": [],
        }
    return {
        "name": "Hello", "version": 1, "author": "@you",
        "bgColor": 0, "delay": 300,
        "setup": [
            {"type": "text", "content": "HELLO", "font": "big",
             "fgColor": 65504, "bgColor": 0, "x": 3, "y": 30},
            {"type": "text", "content": "world", "font": "picopixel",
             "fgColor": 2016, "bgColor": 0, "x": 21, "y": 44},
        ],
        "sprites": [], "loop": [],
    }


def _bounce_frame(color, frame):
    """生成弹跳球的一帧：6x6 的圆（上下压扁模拟弹跳）。"""
    img = Image.new("RGB", (6, 6), (0, 0, 0))
    px = img.load()
    cx, cy = 2.5, 3.0
    # frame 0/2 圆，frame 1 落地压扁
    ry = 2.6 if frame == 1 else 3.0
    for y in range(6):
        for x in range(6):
            d = ((x - cx) / 3.0) ** 2 + ((y - cy) / ry) ** 2
            if d <= 1.0:
                px[x, y] = color
    return img


def _frame_b64(img, bg=(0, 0, 0)):
    res = prepare_image(img, 6, 6, 2, dither=False, bg=bg, mode="contain",
                        smooth=False)
    return res.b64


def template_bounce():
    """弹跳球动画模板：3 帧精灵 + 左右往返位移。"""
    red = (255, 0, 0)
    frames = []
    for i in range(3):
        frames.append({"image": _frame_b64(_bounce_frame(red, i))})
    return {
        "name": "Bounce", "version": 1, "author": "@you",
        "bgColor": 0, "delay": 300,
        "setup": [
            {"type": "datetime", "content": "H:i", "font": "big",
             "fgColor": 65535, "bgColor": 0, "x": 11, "y": 34},
        ],
        "sprites": [frames],
        "loop": [{
            "type": "sprite", "sprite": 0, "x": 4, "y": 54,
            "frameDelay": 200, "loopDelay": 800,
            "moveStartTime": 2000, "moveDuration": 1000,
            "moveTargetX": 54, "moveTargetY": 54,
            "shouldReturnToOrigin": True,
        }],
    }


# ---------------------------------------------------------------- 居中助手

def center_element(theme, el, axis="h", when=None):
    """把元素按真实字体度量居中，返回新的 x / y。"""
    font = get_font(el.get("font"))
    text = element_text(el, when)
    x1, y1, w, h, adv = font.text_bounds(text, 0, 0)
    if axis == "h":
        if w:
            return (PANEL - w) // 2 - x1, None
        return (PANEL - adv) // 2, None
    return None, (PANEL - h) // 2 - y1
