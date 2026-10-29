#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ClockWise Canvas 主题编辑器 —— 64x64 点阵钟界面设计器。

特性：
  * 像素级 WYSIWYG：直接用固件的位图字体渲染，所见即设备所显
  * 图片压缩：自动缩放 → 调色板量化 → 索引色 PNG，实时显示解码体积（必须 <=1024B）
  * 实时校验：JSON 体积上限、元素溢出、图片超限
  * 读写主题 JSON；上传到设备 / 从设备读取

运行：python canvas_designer.py
打包：python build_exe.py
"""

import base64
import io
import json
import os
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageTk

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import cw_core as C  # noqa: E402

APP_NAME = "ClockWise Canvas 编辑器"
APP_VER = "1.0"

# ---- 配色（浅色主题，跟 IDE 一致） ----
CLR_BG = "#f2f4f7"
CLR_PANEL = "#ffffff"
CLR_BORDER = "#dde1e7"
CLR_TEXT = "#1f2430"
CLR_MUTED = "#6b7280"
CLR_ACCENT = "#2f6fed"
CLR_ACCENT_SOFT = "#e9f0ff"
CLR_OK = "#12833b"
CLR_WARN = "#a15c00"
CLR_ERR = "#c0392b"
CLR_GRID = "#b9c0cc"

FONT_UI = ("Microsoft YaHei UI", 9)
FONT_UI_B = ("Microsoft YaHei UI", 9, "bold")
FONT_SMALL = ("Microsoft YaHei UI", 8)
FONT_MONO = ("Consolas", 9)
FONT_TITLE = ("Microsoft YaHei UI", 11, "bold")

FONT_LABELS = {
    "big": "big  · 大字 14px",
    "medium": "medium · 中字 9px",
    "square": "square · atari 11px（仅数字）",
    "picopixel": "picopixel · 5px",
    "default": "default · 经典 5x7",
}
FONT_KEYS = list(FONT_LABELS)

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".clockwise_canvas_editor.json")


def _enable_dpi_awareness():
    """必须在创建 Tk 之前调用，否则高 DPI 下界面会被系统缩放模糊。"""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


if os.name == "nt":
    _enable_dpi_awareness()


# ---------------------------------------------------------------- 小部件

class ColorRow(ttk.Frame):
    """颜色选择行：色块按钮 + HEX/565 输入。"""

    def __init__(self, master, initial=65535, on_change=None, allow_none=False):
        ttk.Frame.__init__(self, master, style="Panel.TFrame")
        self.on_change = on_change
        self.value = int(initial)
        self.allow_none = allow_none

        self.btn = tk.Button(self, width=4, relief="flat", bd=0, cursor="hand2",
                             command=self._pick, highlightthickness=1,
                             highlightbackground=CLR_BORDER)
        self.btn.pack(side="left")
        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=6, font=FONT_MONO)
        self.entry.pack(side="left", padx=(6, 0))
        self.entry.bind("<Return>", self._typed)
        self.entry.bind("<FocusOut>", self._typed)
        self.hint = ttk.Label(self, text="", font=FONT_SMALL, foreground=CLR_MUTED)
        self.hint.pack(side="left", padx=(6, 0))
        self.set(self.value)

    def set(self, value):
        self.value = int(value) & 0xFFFF
        self.btn.configure(bg=C.rgb565_to_hex(self.value))
        self.var.set(str(self.value))
        self.hint.configure(text=C.rgb565_to_hex(self.value))
        fg = C.rgb565_to_rgb(self.value)
        if self.btn.winfo_exists():
            self.btn.configure(activebackground=C.rgb565_to_hex(self.value),
                               fg="#000000" if sum(fg) > 380 else "#ffffff")

    def _pick(self):
        rgb = C.rgb565_to_rgb(self.value)
        picked = colorchooser.askcolor(color=C.rgb_to_hex(rgb), parent=self,
                                       title="选择颜色")
        if picked and picked[0]:
            self.set(C.rgb_to_565(picked[0]))
            if self.on_change:
                self.on_change(self.value)

    def _typed(self, _evt=None):
        text = self.var.get().strip()
        try:
            if text.startswith("#"):
                value = C.hex_to_565(text)
            else:
                value = int(text, 0) & 0xFFFF
        except Exception:
            self.set(self.value)
            return
        if value != self.value:
            self.set(value)
            if self.on_change:
                self.on_change(self.value)
        else:
            self.set(self.value)


class CropDialog(tk.Toplevel):
    """图片裁剪：拖出选框，或按比例。返回 (left, top, right, bottom)。"""

    def __init__(self, master, img, on_ok=None):
        tk.Toplevel.__init__(self, master)
        self.title("裁剪图片")
        self.configure(bg=CLR_BG)
        self.transient(master)
        self.on_ok = on_ok
        self.src = img.convert("RGB")
        self._box = None          # 屏幕坐标 (x0,y0,x1,y1)
        self._drag = None
        self._anchor = None
        self.result = None

        self.ratio_var = tk.StringVar(value="自由")
        self._build()
        self._fit()
        self.minsize(360, 320)
        self.grab_set()

    def _build(self):
        box = ttk.Frame(self, padding=10)
        box.pack(fill="both", expand=True)

        top = ttk.Frame(box)
        top.pack(fill="x")
        ttk.Label(top, text="拖动鼠标框选要保留的区域", font=FONT_UI).pack(side="left")
        ttk.Label(top, text="比例", font=FONT_UI).pack(side="left", padx=(16, 4))
        rb = ttk.Combobox(top, values=("自由", "1:1", "4:3", "3:4", "16:9", "9:16"),
                          textvariable=self.ratio_var, width=6, state="readonly")
        rb.pack(side="left")
        rb.bind("<<ComboboxSelected>>", lambda e: self._on_ratio())

        self.cv = tk.Canvas(box, bg="#222222", highlightthickness=1,
                            highlightbackground=CLR_BORDER, cursor="crosshair")
        self.cv.pack(fill="both", expand=True, pady=8)
        self.cv.bind("<Button-1>", self._press)
        self.cv.bind("<B1-Motion>", self._drag_motion)
        self.cv.bind("<ButtonRelease-1>", self._release)
        self.cv.bind("<Configure>", lambda e: self._fit())

        self.info_lbl = ttk.Label(box, text="", font=FONT_SMALL, foreground=CLR_MUTED)
        self.info_lbl.pack(anchor="w")

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="全图", command=self._select_all).pack(side="left")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="确定裁剪", command=self._ok).pack(side="right", padx=6)

    def _fit(self):
        if self.src is None:
            return
        cw = max(self.cv.winfo_width(), 320)
        ch = max(self.cv.winfo_height(), 260)
        scale = min(cw / self.src.width, ch / self.src.height)
        self._disp_w = max(1, int(self.src.width * scale))
        self._disp_h = max(1, int(self.src.height * scale))
        self._scale = scale
        self._off_x = (cw - self._disp_w) // 2
        self._off_y = (ch - self._disp_h) // 2
        self._thumb = ImageTk.PhotoImage(self.src.resize(
            (self._disp_w, self._disp_h), Image.LANCZOS))
        self.cv.delete("all")
        self.cv.create_image(self._off_x, self._off_y, anchor="nw", image=self._thumb)
        if self._box:
            self._draw_box()

    def _draw_box(self):
        if not self._box:
            return
        self.cv.delete("box")
        x0, y0, x1, y1 = self._box
        self.cv.create_rectangle(x0, y0, x1, y1, outline="#2f6fed", width=2, tags="box")

    def _press(self, evt):
        if not (self._off_x <= evt.x <= self._off_x + self._disp_w and
                self._off_y <= evt.y <= self._off_y + self._disp_h):
            return
        self._anchor = (evt.x, evt.y)
        self._box = (evt.x, evt.y, evt.x, evt.y)

    def _drag_motion(self, evt):
        if self._anchor is None:
            return
        ax, ay = self._anchor
        x0, y0 = min(ax, evt.x), min(ay, evt.y)
        x1, y1 = max(ax, evt.x), max(ay, evt.y)
        x0 = max(self._off_x, x0)
        y0 = max(self._off_y, y0)
        x1 = min(self._off_x + self._disp_w, x1)
        y1 = min(self._off_y + self._disp_h, y1)
        if self.ratio_var.get() != "自由":
            x0, y0, x1, y1 = self._apply_ratio((x0, y0, x1, y1))
        self._box = (x0, y0, x1, y1)
        self._draw_box()
        self._update_info()

    def _release(self, _evt):
        self._anchor = None

    def _apply_ratio(self, box):
        x0, y0, x1, y1 = box
        rw, rh = {"1:1": (1, 1), "4:3": (4, 3), "3:4": (3, 4),
                  "16:9": (16, 9), "9:16": (9, 16)}.get(self.ratio_var.get(), (1, 1))
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            return box
        if w / h > rw / rh:
            w = int(h * rw / rh)
            x1 = x0 + w
        else:
            h = int(w * rh / rw)
            y1 = y0 + h
        x1 = min(self._off_x + self._disp_w, x1)
        y1 = min(self._off_y + self._disp_h, y1)
        return (x0, y0, x1, y1)

    def _on_ratio(self):
        if self._box:
            self._box = self._apply_ratio(self._box)
            self._draw_box()
            self._update_info()

    def _select_all(self):
        self._fit()
        self._box = (self._off_x, self._off_y,
                     self._off_x + self._disp_w, self._off_y + self._disp_h)
        self._draw_box()
        self._update_info()

    def _to_src(self, box):
        x0, y0, x1, y1 = box
        left = int((x0 - self._off_x) / self._scale)
        top = int((y0 - self._off_y) / self._scale)
        right = int((x1 - self._off_x) / self._scale)
        bottom = int((y1 - self._off_y) / self._scale)
        left = max(0, min(self.src.width, left))
        top = max(0, min(self.src.height, top))
        right = max(left + 1, min(self.src.width, right))
        bottom = max(top + 1, min(self.src.height, bottom))
        return (left, top, right, bottom)

    def _update_info(self):
        if not self._box:
            return
        l, t, r, b = self._to_src(self._box)
        self.info_lbl.configure(text="裁剪区域：%d×%d 像素（%d, %d 到 %d, %d）"
                               % (r - l, b - t, l, t, r, b))

    def _ok(self):
        if not self._box:
            messagebox.showwarning("未选择", "请先拖动鼠标框选要保留的区域。", parent=self)
            return
        box = self._to_src(self._box)
        if (box[2] - box[0]) < 1 or (box[3] - box[1]) < 1:
            return
        self.result = box
        if self.on_ok:
            self.on_ok(box)
        self.destroy()


class ImageDialog(tk.Toplevel):
    """图片导入：裁剪 + 缩放 + 调色板量化 + 多方案选择 + 体积实时反馈。"""

    def __init__(self, master, src_path=None, bg_rgb=(0, 0, 0), on_ok=None):
        tk.Toplevel.__init__(self, master)
        self.title("导入图片（自动压进 1024 字节）")
        self.configure(bg=CLR_BG)
        self.resizable(False, False)
        self.transient(master)
        self.on_ok = on_ok
        self.result = None
        self.src = None
        self._job = None
        self._thumb_ref = None

        self.path_var = tk.StringVar(value="")
        self.maxw_var = tk.IntVar(value=32)
        self.maxh_var = tk.IntVar(value=32)
        self.colors_var = tk.StringVar(value="8")
        self.dither_var = tk.BooleanVar(value=False)
        self.smooth_var = tk.BooleanVar(value=True)
        self.mode_var = tk.StringVar(value="等比缩小（不放大）")
        self.bg = bg_rgb
        self.bg_label_var = tk.StringVar()
        self._crop = None          # 已应用的裁剪 (left, top, right, bottom)
        self._opt_refs = []        # 多方案缩略图引用
        self._options = []         # gen_image_options 结果
        self._options_host = None

        self._build()
        if src_path:
            self._load(src_path)
        else:
            self._update()
        self.minsize(470, 0)
        self.grab_set()

    # ---------- UI ----------
    def _build(self):
        pad = {"padx": 10, "pady": 4}
        box = ttk.Frame(self, padding=12)
        box.pack(fill="both", expand=True)

        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Button(row, text="选择图片…", command=self._choose).pack(side="left")
        self.crop_btn = ttk.Button(row, text="裁剪…", command=self._open_crop)
        self.crop_btn.pack(side="left", padx=(6, 0))
        self.crop_state = ttk.Label(row, text="", font=FONT_SMALL, foreground=CLR_MUTED)
        self.crop_state.pack(side="left", padx=6)
        ttk.Label(row, textvariable=self.path_var, font=FONT_SMALL,
                  foreground=CLR_MUTED).pack(side="left", padx=8)

        prev = ttk.Frame(box)
        prev.pack(fill="x", pady=(10, 6))
        left = ttk.LabelFrame(prev, text=" 原图 ", padding=6)
        left.pack(side="left", anchor="n")
        self.orig_lbl = tk.Label(left, text="（未选择）", bg="#e9ecf1", width=20, height=10)
        self.orig_lbl.pack()
        right = ttk.LabelFrame(prev, text=" 压缩结果（放大显示） ", padding=6)
        right.pack(side="left", padx=10, anchor="n")
        self.out_lbl = tk.Label(right, text="", bg="#111111", width=20, height=10)
        self.out_lbl.pack()

        opts = ttk.Frame(box)
        opts.pack(fill="x", pady=(6, 4))
        g = opts
        for col, minsize in ((0, 52), (1, 56), (2, 52), (3, 56), (4, 44), (5, 60)):
            g.columnconfigure(col, minsize=minsize)
        ttk.Label(g, text="最大宽", font=FONT_UI).grid(row=0, column=0, sticky="w")
        ttk.Spinbox(g, from_=4, to=64, width=5, textvariable=self.maxw_var,
                    command=self._schedule).grid(row=0, column=1, sticky="w", padx=(4, 12))
        ttk.Label(g, text="最大高", font=FONT_UI).grid(row=0, column=2, sticky="w")
        ttk.Spinbox(g, from_=4, to=64, width=5, textvariable=self.maxh_var,
                    command=self._schedule).grid(row=0, column=3, sticky="w", padx=(4, 12))
        ttk.Label(g, text="色数", font=FONT_UI).grid(row=0, column=4, sticky="w")
        cb = ttk.Combobox(g, values=("2", "4", "8", "16", "32"), width=4,
                          textvariable=self.colors_var, state="readonly")
        cb.grid(row=0, column=5, sticky="w", padx=(4, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self._schedule())

        ttk.Checkbutton(g, text="抖动（体积更大）", variable=self.dither_var,
                        command=self._schedule).grid(row=1, column=0, columnspan=3,
                                                     sticky="w", pady=(8, 0))
        ttk.Checkbutton(g, text="平滑缩放", variable=self.smooth_var,
                        command=self._schedule).grid(row=1, column=3, columnspan=3,
                                                     sticky="w", pady=(8, 0))

        ttk.Label(g, text="适配", font=FONT_UI).grid(row=2, column=0, sticky="w", pady=(8, 0))
        mb = ttk.Combobox(g, values=("等比缩小（不放大）", "等比放大填满", "裁切填满", "拉伸"),
                          width=15, textvariable=self.mode_var, state="readonly")
        mb.grid(row=2, column=1, columnspan=3, sticky="w", padx=(4, 0), pady=(8, 0))
        mb.bind("<<ComboboxSelected>>", lambda e: self._schedule())
        ttk.Label(g, text="透明→", font=FONT_UI).grid(row=2, column=4, sticky="w", pady=(8, 0))
        cell = ttk.Frame(g)
        cell.grid(row=2, column=5, sticky="w", pady=(8, 0))
        self.bg_btn = tk.Button(cell, width=3, relief="flat", bd=0, cursor="hand2",
                                command=self._pick_bg, highlightthickness=1,
                                highlightbackground=CLR_BORDER)
        self.bg_btn.pack(side="left")
        self._paint_bg()
        ttk.Label(cell, textvariable=self.bg_label_var, font=FONT_SMALL,
                  foreground=CLR_MUTED).pack(side="left", padx=(4, 0))

        info = ttk.Frame(box)
        info.pack(fill="x", pady=(8, 2))
        self.size_lbl = ttk.Label(info, text="", font=FONT_UI_B)
        self.size_lbl.pack(anchor="w")
        self.detail_lbl = ttk.Label(info, text="", font=FONT_SMALL, foreground=CLR_MUTED)
        self.detail_lbl.pack(anchor="w")

        # 多方案选择
        opt_frame = ttk.LabelFrame(box, text=" 多方案选择（点一个直接用） ", padding=8)
        opt_frame.pack(fill="x", pady=(8, 0))
        self._options_host = opt_frame

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="自动压到 1024B 以内", command=self._auto).pack(side="left")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right")
        self.ok_btn = ttk.Button(btns, text="确定", command=self._ok)
        self.ok_btn.pack(side="right", padx=6)

    def _paint_bg(self):
        hx = C.rgb_to_hex(self.bg)
        self.bg_btn.configure(bg=hx, activebackground=hx)
        self.bg_label_var.set(hx)

    def _pick_bg(self):
        picked = colorchooser.askcolor(color=C.rgb_to_hex(self.bg), parent=self,
                                       title="透明区域填充色")
        if picked and picked[0]:
            self.bg = tuple(int(v) for v in picked[0])
            self._paint_bg()
            self._schedule()

    # ---------- 逻辑 ----------
    def _choose(self):
        path = filedialog.askopenfilename(
            parent=self, title="选择图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                       ("所有文件", "*.*")])
        if path:
            self._load(path)

    def _load(self, path):
        try:
            img = Image.open(path)
            img.load()
        except Exception as exc:
            messagebox.showerror("无法打开", "读取图片失败：\n%s" % exc, parent=self)
            return
        self.src = img
        self._crop = None
        self._crop_state_text()
        self.path_var.set(os.path.basename(path) + "  (%dx%d)" % img.size)
        thumb = img.convert("RGB")
        thumb.thumbnail((150, 150), Image.LANCZOS)
        self._orig_ref = ImageTk.PhotoImage(thumb)
        self.orig_lbl.configure(image=self._orig_ref, text="", width=150, height=150)
        big = max(img.size)
        guess = 32 if big > 32 else max(4, big)
        self.maxw_var.set(min(guess, 64))
        self.maxh_var.set(min(guess, 64))
        self._schedule()

    def _work_image(self):
        """返回用于压缩的图（应用裁剪后）。"""
        if self._crop and self.src is not None:
            return C.crop_image(self.src, self._crop)
        return self.src

    def _crop_state_text(self):
        if self._crop:
            l, t, r, b = self._crop
            self.crop_state.configure(text="已裁剪 %d×%d" % (r - l, b - t))
        else:
            self.crop_state.configure(text="")

    def _open_crop(self):
        if self.src is None:
            messagebox.showwarning("先选图", "请先选择一张图片再裁剪。", parent=self)
            return

        def apply(box):
            self._crop = box
            self._crop_state_text()
            # 更新原图预览显示裁剪框
            self._refresh_orig_thumb()
            self._schedule()

        CropDialog(self, self.src, on_ok=apply)

    def _refresh_orig_thumb(self):
        base = self._work_image() or self.src
        thumb = base.convert("RGB")
        thumb.thumbnail((150, 150), Image.LANCZOS)
        self._orig_ref = ImageTk.PhotoImage(thumb)
        self.orig_lbl.configure(image=self._orig_ref, text="", width=150, height=150)

    def _schedule(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(120, self._update)

    def _params(self):
        mode = {"等比缩小（不放大）": "contain", "等比放大填满": "fit",
                "裁切填满": "cover", "拉伸": "stretch"}[self.mode_var.get()]
        try:
            colors = int(self.colors_var.get())
        except ValueError:
            colors = 8
        return {
            "max_w": max(1, min(64, int(self.maxw_var.get()))),
            "max_h": max(1, min(64, int(self.maxh_var.get()))),
            "colors": colors,
            "dither": bool(self.dither_var.get()),
            "mode": mode,
            "smooth": bool(self.smooth_var.get()),
            "bg": self.bg,
        }

    def _update(self):
        self._job = None
        if self.src is None:
            self.size_lbl.configure(text="请先选择图片", foreground=CLR_MUTED)
            self.detail_lbl.configure(text="")
            self.ok_btn.state(["disabled"])
            self._clear_options()
            return
        p = self._params()
        work = self._work_image()
        res = C.prepare_image(work, p["max_w"], p["max_h"], p["colors"],
                              dither=p["dither"], bg=p["bg"], mode=p["mode"],
                              smooth=p["smooth"])
        self.result = res
        ok = res.ok
        self.size_lbl.configure(
            text="%dx%d · %d 色 · PNG %d B  (%s)" % (
                res.width, res.height, res.colors, res.size,
                "可放进设备" if ok else "超出 1024B"),
            foreground=CLR_OK if ok else CLR_ERR)
        self.detail_lbl.configure(
            text="base64 %d 字符（固件解码缓冲 1024B）· 阈值 %d B"
                 % (len(res.b64), C.IMAGE_DECODE_LIMIT))
        self.ok_btn.state([] if ok else ["disabled"])
        view = res.image(scale=1)
        scale = max(1, min(8, 160 // max(view.width, view.height)))
        view = view.resize((view.width * scale, view.height * scale), Image.NEAREST)
        self._out_ref = ImageTk.PhotoImage(view)
        self.out_lbl.configure(image=self._out_ref, text="", width=150, height=150)
        self._refresh_options(work)

    def _clear_options(self):
        self._options = []
        self._opt_refs = []
        if self._options_host is not None:
            for w in self._options_host.winfo_children():
                w.destroy()

    def _refresh_options(self, work):
        self._clear_options()
        opts = C.gen_image_options(work, bg=self.bg, dither=self.dither_var.get(),
                                   smooth=self.smooth_var.get(),
                                   max_w=min(self.maxw_var.get(), 64),
                                   max_h=min(self.maxh_var.get(), 64),
                                   mode=self._params()["mode"])
        self._options = opts
        # 只展示前 10 个（按体积从大到小，即观感从好到差），且都 <=1024
        shown = [o for o in opts if o["ok"]][:10]
        if not shown:
            ttk.Label(self._options_host, text="没有 <=1024B 的方案，请裁剪或降低要求。",
                      style="Muted.TLabel").pack(anchor="w")
            return
        row_frame = None
        for i, o in enumerate(shown):
            if i % 5 == 0:
                row_frame = ttk.Frame(self._options_host)
                row_frame.pack(anchor="w", pady=(0, 6))
            cell = ttk.Frame(row_frame, style="Panel.TFrame")
            cell.pack(side="left", padx=(0, 8))
            img = o["result"].image(scale=1)
            sc = max(1, min(8, 64 // max(img.width, img.height)))
            img = img.resize((img.width * sc, img.height * sc), Image.NEAREST)
            ref = ImageTk.PhotoImage(img)
            self._opt_refs.append(ref)
            lb = tk.Label(cell, image=ref, bg="#111111", cursor="hand2",
                          highlightbackground=CLR_BORDER, highlightthickness=1)
            lb.pack()
            txt = tk.Label(cell, text="%dx%d\n%d色·%dB" % (o["size"][0], o["size"][1],
                                                           o["colors"], o["bytes"]),
                           font=FONT_SMALL, bg=CLR_PANEL, fg=CLR_TEXT)
            txt.pack()
            lb.bind("<Button-1>", lambda e, o=o: self._pick_option(o))
            txt.bind("<Button-1>", lambda e, o=o: self._pick_option(o))

    def _pick_option(self, o):
        self.colors_var.set(str(o["colors"]))
        self.maxw_var.set(o["size"][0])
        self.maxh_var.set(o["size"][1])
        self.result = o["result"]
        self._update()

    def _auto(self):
        if self.src is None:
            return
        work = self._work_image()
        p = self._params()
        res = C.auto_fit_image(work, limit=C.IMAGE_DECODE_LIMIT,
                               max_w=p["max_w"], max_h=p["max_h"], bg=p["bg"],
                               mode=p["mode"], smooth=p["smooth"], dither=p["dither"])
        if res is None:
            messagebox.showwarning("放不下",
                                   "即使缩到 8px / 2 色也超过 1024 字节，请换更简单的小图。",
                                   parent=self)
            return
        self.colors_var.set(str(res.colors))
        self.maxw_var.set(res.width)
        self.maxh_var.set(res.height)
        self._update()

    def _ok(self):
        if self.result is None or not self.result.ok:
            return
        if self.on_ok:
            self.on_ok(self.result)
        self.destroy()


# ---------------------------------------------------------------- 主窗口

class Designer(tk.Tk):

    def __init__(self):
        tk.Tk.__init__(self)
        self._setup_dpi()
        self.title(APP_NAME)
        self.configure(bg=CLR_BG)
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = max(1120, min(1480, sw - 90))
        h = max(760, min(940, sh - 100))
        self.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, max(16, (sh - h) // 2 - 20)))
        self.minsize(1080, 720)

        self.theme = C.template_theme("minimal")
        self.path = None
        self.sel = 0
        self.zoom = 8
        self._zoom_auto = True
        self.dirty = False
        self.undo = []
        self.redo = []
        self._last_key = None
        self._last_ts = 0.0
        self._drag = None
        self._suppress = False
        self._photo = None
        self._anim_t0 = 0.0
        self._frame_refs = []
        self._cfg = self._load_cfg()
        self.ip_var = tk.StringVar(value=self._cfg.get("ip", "192.168.137.99"))
        self.live_var = tk.BooleanVar(value=True)
        self.sim_var = tk.StringVar(value=datetime.now().strftime("%H:%M:%S"))
        self.grid_var = tk.BooleanVar(value=True)
        self.coord_var = tk.StringVar(value="")
        self.size_var = tk.StringVar(value="")
        self.msg_var = tk.StringVar(value="就绪")

        self._init_style()
        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_status()
        self._bind_keys()
        self.after(300, self._refit_zoom)
        self.after(900, self._refit_zoom)
        self.after(200, self._tick)
        self.refresh_all(rebuild_props=True)

    # ---------- 基础 ----------
    def _setup_dpi(self):
        _enable_dpi_awareness()
        try:
            dpi = self.winfo_fpixels("1i")
            self.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass

    def _init_style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", background=CLR_BG, foreground=CLR_TEXT, font=FONT_UI)
        st.configure("TFrame", background=CLR_BG)
        st.configure("Panel.TFrame", background=CLR_PANEL)
        st.configure("TLabel", background=CLR_BG, foreground=CLR_TEXT, font=FONT_UI)
        st.configure("Panel.TLabel", background=CLR_PANEL)
        st.configure("Muted.TLabel", background=CLR_PANEL, foreground=CLR_MUTED,
                     font=FONT_SMALL)
        st.configure("Head.TLabel", background=CLR_PANEL, foreground=CLR_TEXT,
                     font=FONT_UI_B)
        st.configure("Title.TLabel", background=CLR_PANEL, foreground=CLR_TEXT,
                     font=FONT_TITLE)
        st.configure("TLabelframe", background=CLR_PANEL, bordercolor=CLR_BORDER,
                     relief="solid", borderwidth=1)
        st.configure("TLabelframe.Label", background=CLR_PANEL, foreground=CLR_MUTED,
                     font=FONT_UI_B)
        st.configure("TButton", padding=(9, 4), background="#f7f8fa",
                     bordercolor=CLR_BORDER, focusthickness=0, relief="flat")
        st.map("TButton",
               background=[("active", CLR_ACCENT_SOFT), ("pressed", "#d7e3ff")],
               foreground=[("active", CLR_ACCENT)])
        st.configure("Accent.TButton", background=CLR_ACCENT, foreground="#ffffff",
                     padding=(12, 5))
        st.map("Accent.TButton",
               background=[("active", "#1f5fdd"), ("pressed", "#1a52c4")],
               foreground=[("active", "#ffffff")])
        st.configure("Small.TButton", padding=(5, 3), background="#f7f8fa",
                     bordercolor=CLR_BORDER)
        st.map("Small.TButton",
               background=[("active", CLR_ACCENT_SOFT)],
               foreground=[("active", CLR_ACCENT)])
        st.configure("TCheckbutton", background=CLR_PANEL, font=FONT_UI)
        st.configure("Tool.TCheckbutton", background="#f7f8fa", font=FONT_UI)
        st.configure("TEntry", fieldbackground="#ffffff", bordercolor=CLR_BORDER,
                     insertcolor=CLR_TEXT, padding=3)
        st.configure("TSpinbox", fieldbackground="#ffffff", bordercolor=CLR_BORDER,
                     arrowsize=11, padding=2)
        st.configure("TCombobox", fieldbackground="#ffffff", bordercolor=CLR_BORDER,
                     padding=3)
        st.configure("Treeview", background="#ffffff", fieldbackground="#ffffff",
                     bordercolor=CLR_BORDER, rowheight=23, font=FONT_UI)
        st.configure("Treeview.Heading", background="#f1f3f7", foreground=CLR_MUTED,
                     relief="flat", font=FONT_SMALL)
        st.map("Treeview", background=[("selected", CLR_ACCENT)],
               foreground=[("selected", "#ffffff")])
        st.configure("TProgressbar", background=CLR_ACCENT, troughcolor="#e5e8ee",
                     bordercolor=CLR_BORDER, thickness=8)

    def _build_menu(self):
        m = tk.Menu(self)
        fm = tk.Menu(m, tearoff=0)
        fm.add_command(label="新建空白主题", accelerator="Ctrl+N", command=self.new_theme)
        tpl = tk.Menu(fm, tearoff=0)
        for label, key in (("极简（边框+分隔线）", "minimal"),
                           ("居中大字 + 日期", "bigcenter"),
                           ("纯文字问候", "hello"),
                           ("弹跳球动画（精灵）", "bounce")):
            tpl.add_command(label=label, command=lambda k=key: self.load_template(k))
        fm.add_cascade(label="从模板新建", menu=tpl)
        fm.add_separator()
        fm.add_command(label="打开 JSON…", accelerator="Ctrl+O", command=self.open_file)
        fm.add_command(label="保存", accelerator="Ctrl+S", command=self.save_file)
        fm.add_command(label="另存为…", accelerator="Ctrl+Shift+S", command=self.save_as)
        fm.add_separator()
        fm.add_command(label="导出 64x64 预览 PNG…", command=self.export_png)
        fm.add_separator()
        fm.add_command(label="退出", command=self.on_close)
        m.add_cascade(label="文件", menu=fm)

        em = tk.Menu(m, tearoff=0)
        em.add_command(label="撤销", accelerator="Ctrl+Z", command=self.do_undo)
        em.add_command(label="重做", accelerator="Ctrl+Y", command=self.do_redo)
        em.add_separator()
        em.add_command(label="复制元素", accelerator="Ctrl+D", command=self.duplicate)
        em.add_command(label="删除元素", accelerator="Del", command=self.delete_sel)
        em.add_separator()
        em.add_command(label="上移一层", accelerator="Ctrl+Up", command=lambda: self.move(-1))
        em.add_command(label="下移一层", accelerator="Ctrl+Down", command=lambda: self.move(1))
        m.add_cascade(label="编辑", menu=em)

        dm = tk.Menu(m, tearoff=0)
        dm.add_command(label="连接测试（/get）", command=self.dev_ping)
        dm.add_command(label="列出设备主题（/themes）", command=self.dev_list)
        dm.add_command(label="上传当前主题…", accelerator="Ctrl+U", command=self.dev_upload)
        dm.add_command(label="从设备读取主题…", command=self.dev_fetch)
        dm.add_separator()
        dm.add_command(label="重启设备", command=self.dev_restart)
        m.add_cascade(label="设备", menu=dm)

        hm = tk.Menu(m, tearoff=0)
        hm.add_command(label="格式速查 / 限制", command=self.show_help)
        hm.add_command(label="关于", command=lambda: messagebox.showinfo(
            "关于", "%s %s\n\n64x64 Canvas 主题编辑器\n"
                    "字体与色彩取自固件实现，预览与设备一致。\n"
                    "固件限制：JSON <= 48KB，单图 PNG <= 1024B 且宽 <= 64px。"
                    % (APP_NAME, APP_VER), parent=self))
        m.add_cascade(label="帮助", menu=hm)
        self.config(menu=m)

    def _build_toolbar(self):
        bar = tk.Frame(self, bg="#f7f8fa", highlightbackground=CLR_BORDER,
                       highlightthickness=1)
        bar.pack(side="top", fill="x")
        inner = tk.Frame(bar, bg="#f7f8fa")
        inner.pack(fill="x", padx=10, pady=6)

        ttk.Button(inner, text="打开", command=self.open_file).pack(side="left")
        ttk.Button(inner, text="保存", command=self.save_file).pack(side="left", padx=(6, 0))
        ttk.Separator(inner, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(inner, text="撤销", command=self.do_undo, width=5).pack(side="left")
        ttk.Button(inner, text="重做", command=self.do_redo, width=5).pack(side="left", padx=(6, 0))
        ttk.Separator(inner, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(inner, text="缩放", font=FONT_UI).pack(side="left")
        ttk.Button(inner, text="−", width=3, command=lambda: self.set_zoom(-1)).pack(side="left", padx=3)
        self.zoom_lbl = ttk.Label(inner, text="8x", width=4, font=FONT_UI_B)
        self.zoom_lbl.pack(side="left")
        ttk.Button(inner, text="+", width=3, command=lambda: self.set_zoom(1)).pack(side="left")
        ttk.Checkbutton(inner, text="网格", variable=self.grid_var, style="Tool.TCheckbutton",
                        command=self.redraw).pack(side="left", padx=10)
        ttk.Separator(inner, orient="vertical").pack(side="left", fill="y", padx=10)

        ttk.Label(inner, text="设备 IP", font=FONT_UI).pack(side="left")
        ttk.Entry(inner, textvariable=self.ip_var, width=16, font=FONT_MONO).pack(side="left", padx=4)
        ttk.Button(inner, text="测试", width=5, command=self.dev_ping).pack(side="left")
        ttk.Button(inner, text="上传", width=5, command=self.dev_upload).pack(side="left", padx=(4, 0))
        ttk.Button(inner, text="读取", width=5, command=self.dev_fetch).pack(side="left", padx=(4, 0))

        right = tk.Frame(inner, bg="#f7f8fa")
        right.pack(side="right")
        ttk.Button(right, text="导出 预览", command=self.export_png).pack(side="right")

    def _build_body(self):
        body = tk.Frame(self, bg=CLR_BG)
        body.pack(side="top", fill="both", expand=True, padx=10, pady=(8, 4))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, minsize=262, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(2, minsize=320, weight=0)

        # 左：主题 + 元素
        left = tk.Frame(body, bg=CLR_PANEL, width=262, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsw")
        # 注意：子控件是 pack 的，所以必须用 pack_propagate 才能锁住 262px 宽度
        left.pack_propagate(False)

        th = ttk.Frame(left, style="Panel.TFrame", padding=(12, 10, 12, 4))
        th.pack(fill="x")
        ttk.Label(th, text="主题", style="Title.TLabel").pack(anchor="w")
        form = ttk.Frame(left, style="Panel.TFrame", padding=(12, 2, 12, 8))
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        self.name_var = tk.StringVar()
        self.author_var = tk.StringVar()
        self.ver_var = tk.IntVar(value=1)
        self.delay_var = tk.IntVar(value=300)
        self._form_row(form, 0, "名称", ttk.Entry(form, textvariable=self.name_var))
        self._form_row(form, 1, "作者", ttk.Entry(form, textvariable=self.author_var))
        self._form_row(form, 2, "版本", ttk.Spinbox(form, from_=1, to=999, width=6,
                                                    textvariable=self.ver_var))
        self._form_row(form, 3, "循环延时", ttk.Spinbox(form, from_=0, to=60000, width=8,
                                                        textvariable=self.delay_var))
        self._bg_row = ColorRow(form, 0, on_change=self._theme_bg_change)
        self._form_row(form, 4, "背景色", self._bg_row)

        self.name_var.trace_add("write", lambda *a: self._theme_field("name", self.name_var))
        self.author_var.trace_add("write", lambda *a: self._theme_field("author", self.author_var))
        self.ver_var.trace_add("write", lambda *a: self._theme_field("version", self.ver_var))
        self.delay_var.trace_add("write", lambda *a: self._theme_field("delay", self.delay_var))

        ttk.Separator(left, orient="horizontal").pack(fill="x", padx=12, pady=(2, 8))

        # 左栏下半：标签页（元素 / 精灵动画）
        nb = ttk.Notebook(left)
        nb.pack(fill="both", expand=True, padx=8)

        # —— 元素页 ——
        elem_tab = ttk.Frame(nb, style="Panel.TFrame")
        nb.add(elem_tab, text="元素")

        eh = ttk.Frame(elem_tab, style="Panel.TFrame", padding=(6, 6, 6, 4))
        eh.pack(fill="x")
        ttk.Label(eh, text="元素（从下往上绘制）", style="Head.TLabel").pack(side="left")

        tree_box = ttk.Frame(elem_tab, style="Panel.TFrame", padding=(6, 0, 6, 0))
        tree_box.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_box, columns=("t", "c", "p"), show="headings",
                                 selectmode="browse", height=12)
        self.tree.heading("t", text="类型")
        self.tree.heading("c", text="内容")
        self.tree.heading("p", text="xy")
        self.tree.column("t", width=74, anchor="w", stretch=False)
        self.tree.column("c", width=104, anchor="w")
        self.tree.column("p", width=56, anchor="e", stretch=False)
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(tree_box, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        addbar = ttk.Frame(elem_tab, style="Panel.TFrame", padding=(6, 8, 6, 6))
        addbar.pack(fill="x")
        self.add_btn = ttk.Menubutton(addbar, text="＋ 添加")
        self.add_btn.pack(fill="x")
        menu = tk.Menu(self.add_btn, tearoff=0)
        for kind in C.ELEMENT_TYPES:
            menu.add_command(label="%s  (%s)" % (C.TYPE_LABELS[kind], kind),
                             command=lambda k=kind: self.add_element(k))
        self.add_btn["menu"] = menu

        row = ttk.Frame(elem_tab, style="Panel.TFrame", padding=(6, 0, 6, 6))
        row.pack(fill="x")
        specs = (("删除", self.delete_sel, 1), ("复制", self.duplicate, 1),
                 ("↑ 上移", lambda: self.move(-1), 1), ("↓ 下移", lambda: self.move(1), 1))
        for col, (text, cmd, weight) in enumerate(specs):
            row.columnconfigure(col, weight=weight)
            ttk.Button(row, text=text, style="Small.TButton", command=cmd).grid(
                row=0, column=col, sticky="ew", padx=(0 if col == 0 else 4, 0))

        # —— 精灵动画页 ——
        self._build_sprite_tab(nb)

        # 右：属性（必须先 pack，否则被 expand 的中心区挤掉）
        right = tk.Frame(body, bg=CLR_PANEL, width=318, highlightbackground=CLR_BORDER,
                         highlightthickness=1)
        right.grid(row=0, column=2, sticky="nse")
        right.pack_propagate(False)
        rh = ttk.Frame(right, style="Panel.TFrame", padding=(12, 10, 12, 4))
        rh.pack(fill="x")
        ttk.Label(rh, text="属性", style="Title.TLabel").pack(anchor="w")
        self.props_host = ttk.Frame(right, style="Panel.TFrame", padding=(12, 2, 12, 12))
        self.props_host.pack(fill="both", expand=True)

        # 中：画布
        center = tk.Frame(body, bg=CLR_BG)
        center.grid(row=0, column=1, sticky="nsew", padx=10)
        wrap = tk.Frame(center, bg="#e8ebf0", highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg="#e8ebf0", highlightthickness=0,
                               cursor="crosshair")
        self.canvas.pack(fill="both", expand=True, pady=(14, 0))
        self._photo = None
        self.img_item = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda e: self.coord_var.set(""))
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        bottom = tk.Frame(center, bg=CLR_BG)
        bottom.pack(fill="x", pady=(6, 0))
        ttk.Label(bottom, text="模拟时间", font=FONT_UI).pack(side="left")
        ent = ttk.Entry(bottom, textvariable=self.sim_var, width=10, font=FONT_MONO)
        ent.pack(side="left", padx=(4, 6))
        ent.bind("<Return>", lambda e: self.redraw())
        ttk.Checkbutton(bottom, text="跟随系统时间", variable=self.live_var,
                        command=self._live_toggle).pack(side="left")
        ttk.Button(bottom, text="设为现在", width=8,
                   command=self._set_now).pack(side="left", padx=6)
        ttk.Label(bottom, textvariable=self.coord_var, font=FONT_MONO,
                  foreground=CLR_MUTED).pack(side="right")


    def _build_status(self):
        bar = tk.Frame(self, bg="#f7f8fa", highlightbackground=CLR_BORDER,
                       highlightthickness=1)
        bar.pack(side="bottom", fill="x")
        inner = tk.Frame(bar, bg="#f7f8fa")
        inner.pack(fill="x", padx=12, pady=4)
        ttk.Label(inner, textvariable=self.msg_var, font=FONT_SMALL,
                  foreground=CLR_MUTED, background="#f7f8fa").pack(side="right", padx=(8, 4))
        ttk.Label(inner, textvariable=self.size_var, font=FONT_SMALL,
                  background="#f7f8fa").pack(side="left")
        self.pbar = ttk.Progressbar(inner, length=110, maximum=100)
        self.pbar.pack(side="left", padx=8)
        self.issue_lbl = ttk.Label(inner, text="", font=FONT_SMALL, background="#f7f8fa")
        self.issue_lbl.pack(side="left", padx=6)

    def _build_sprite_tab(self, nb):
        """左栏「精灵动画」标签页：精灵组 + loop 实例 + 播放开关。"""
        tab = ttk.Frame(nb, style="Panel.TFrame")
        nb.add(tab, text="动画")

        # 播放控制
        play = ttk.Frame(tab, style="Panel.TFrame", padding=(6, 6, 6, 2))
        play.pack(fill="x")
        self.anim_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(play, text="播放动画预览", variable=self.anim_var,
                        command=self._anim_toggle).pack(side="left")

        # 精灵组列表
        sh = ttk.Frame(tab, style="Panel.TFrame", padding=(6, 6, 6, 2))
        sh.pack(fill="x")
        ttk.Label(sh, text="精灵组（每组多帧）", style="Head.TLabel").pack(side="left")
        sbox = ttk.Frame(tab, style="Panel.TFrame", padding=(6, 0, 6, 4))
        sbox.pack(fill="x")
        self.sprite_tree = ttk.Treeview(sbox, columns=("idx", "frames"), show="headings",
                                        selectmode="browse", height=4)
        self.sprite_tree.heading("idx", text="#")
        self.sprite_tree.heading("frames", text="帧")
        self.sprite_tree.column("idx", width=30, anchor="w", stretch=False)
        self.sprite_tree.column("frames", width=200, anchor="w")
        self.sprite_tree.pack(side="left", fill="x", expand=True)
        self.sprite_tree.bind("<<TreeviewSelect>>", self._on_sprite_select)

        sbtn = ttk.Frame(tab, style="Panel.TFrame", padding=(6, 0, 6, 4))
        sbtn.pack(fill="x")
        ttk.Button(sbtn, text="＋ 组", style="Small.TButton",
                   command=self.sprite_add_group).pack(side="left")
        ttk.Button(sbtn, text="＋ 帧", style="Small.TButton",
                   command=self.sprite_add_frame).pack(side="left", padx=4)
        ttk.Button(sbtn, text="删", style="Small.TButton",
                   command=self.sprite_del).pack(side="left", padx=(0, 4))

        ttk.Separator(tab, orient="horizontal").pack(fill="x", padx=6, pady=6)

        # loop 实例列表
        lh = ttk.Frame(tab, style="Panel.TFrame", padding=(6, 0, 6, 2))
        lh.pack(fill="x")
        ttk.Label(lh, text="loop 实例", style="Head.TLabel").pack(side="left")
        lb = ttk.Frame(tab, style="Panel.TFrame", padding=(6, 0, 6, 4))
        lb.pack(fill="x")
        self.loop_tree = ttk.Treeview(lb, columns=("idx", "info"), show="headings",
                                      selectmode="browse", height=4)
        self.loop_tree.heading("idx", text="#")
        self.loop_tree.heading("info", text="引用精灵 / 位置")
        self.loop_tree.column("idx", width=30, anchor="w", stretch=False)
        self.loop_tree.column("info", width=200, anchor="w")
        self.loop_tree.pack(side="left", fill="x", expand=True)
        self.loop_tree.bind("<<TreeviewSelect>>", self._on_loop_select)

        lbtn = ttk.Frame(tab, style="Panel.TFrame", padding=(6, 0, 6, 6))
        lbtn.pack(fill="x")
        ttk.Button(lbtn, text="＋ 实例", style="Small.TButton",
                   command=self.loop_add).pack(side="left")
        ttk.Button(lbtn, text="删", style="Small.TButton",
                   command=self.loop_del).pack(side="left", padx=4)

        ttk.Separator(tab, orient="horizontal").pack(fill="x", padx=6, pady=6)

        # 帧预览
        fp = ttk.Frame(tab, style="Panel.TFrame", padding=(6, 0, 6, 6))
        fp.pack(fill="x")
        ttk.Label(fp, text="帧预览（点编辑 / 双击删）", style="Head.TLabel").pack(side="left", anchor="n")
        self.frame_host = ttk.Frame(tab, style="Panel.TFrame", padding=(6, 0, 6, 8))
        self.frame_host.pack(fill="both", expand=True)

    # ---------- 精灵 / loop 数据操作 ----------
    def _sprite_groups(self):
        return self.theme.setdefault("sprites", [])

    def _loop_entries(self):
        return self.theme.setdefault("loop", [])

    def _sel_sprite_group(self):
        sel = self.sprite_tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        groups = self._sprite_groups()
        if 0 <= idx < len(groups):
            return idx
        return None

    def _sel_loop_entry(self):
        sel = self.loop_tree.selection()
        if not sel:
            return None
        idx = int(sel[0])
        entries = self._loop_entries()
        if 0 <= idx < len(entries):
            return idx
        return None

    def _refresh_sprite_tab(self):
        # 保留当前选中项（重建列表会清空 selection）
        sel_sprite = self.sprite_tree.selection()
        sel_loop = self.loop_tree.selection()
        self._suppress = True
        self.sprite_tree.delete(*self.sprite_tree.get_children())
        for i, g in enumerate(self._sprite_groups()):
            self.sprite_tree.insert("", "end", iid=str(i),
                                    values=(i, "%d 帧" % len(g or [])))
        self.loop_tree.delete(*self.loop_tree.get_children())
        for i, e in enumerate(self._loop_entries()):
            ref = e.get("sprite", "?")
            self.loop_tree.insert("", "end", iid=str(i),
                                  values=(i, "sprite %s @ (%s,%s)" % (
                                      ref, e.get("x", 0), e.get("y", 0))))
        # 恢复选中项
        for s in sel_sprite:
            if self.sprite_tree.exists(s):
                self.sprite_tree.selection_add(s)
        for s in sel_loop:
            if self.loop_tree.exists(s):
                self.loop_tree.selection_add(s)
        self._suppress = False
        self._refresh_frame_preview()

    def _refresh_frame_preview(self):
        for w in self.frame_host.winfo_children():
            w.destroy()
        gi = self._sel_sprite_group()
        if gi is None:
            ttk.Label(self.frame_host, text="选中一个精灵组查看帧。",
                      style="Muted.TLabel").pack(anchor="w")
            return
        group = self._sprite_groups()[gi] or []
        if not group:
            ttk.Label(self.frame_host, text="该组还没有帧，点「＋ 帧」添加。",
                      style="Muted.TLabel").pack(anchor="w")
            return
        self._frame_refs = []
        row = None
        for fi, frame in enumerate(group):
            if fi % 6 == 0:
                row = ttk.Frame(self.frame_host, style="Panel.TFrame")
                row.pack(anchor="w", pady=(0, 4))
            cell = ttk.Frame(row, style="Panel.TFrame")
            cell.pack(side="left", padx=(0, 4))
            b64 = (frame or {}).get("image") or ""
            if b64:
                try:
                    im = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
                    sc = max(1, min(6, 40 // max(im.size)))
                    im = im.resize((im.size[0] * sc, im.size[1] * sc), Image.NEAREST)
                    ref = ImageTk.PhotoImage(im)
                    self._frame_refs.append(ref)
                    lb = tk.Label(cell, image=ref, bg="#111111", cursor="hand2",
                                  highlightbackground=CLR_BORDER, highlightthickness=1)
                    lb.pack()
                except Exception:
                    lb = tk.Label(cell, text="?", bg="#111111", width=6, height=4)
                    lb.pack()
            else:
                lb = tk.Label(cell, text="空", bg="#111111", fg="#aaa", width=6, height=4)
                lb.pack()
            ttk.Label(cell, text="#%d" % fi, style="Muted.TLabel").pack()
            lb.bind("<Button-1>", lambda e, f=fi: self.sprite_edit_frame(f))
            lb.bind("<Double-Button-1>", lambda e, f=fi: self.sprite_del_frame(f))

    def _on_sprite_select(self, _evt):
        if self._suppress:
            return
        self._refresh_frame_preview()

    def _on_loop_select(self, _evt):
        if self._suppress:
            return
        li = self._sel_loop_entry()
        if li is not None:
            self.edit_loop_entry(li)

    def sprite_add_group(self):
        self.snapshot("sprite:add_group")
        self._sprite_groups().append([])
        self._mark_dirty()
        self._refresh_sprite_tab()
        self._refresh_issues()

    def sprite_del(self):
        gi = self._sel_sprite_group()
        if gi is None:
            return
        self.snapshot("sprite:del_group")
        groups = self._sprite_groups()
        del groups[gi]
        for e in self._loop_entries():
            ref = int(e.get("sprite", 0) or 0)
            if ref == gi:
                e["sprite"] = 0
            elif ref > gi:
                e["sprite"] = ref - 1
        self._mark_dirty()
        self._refresh_sprite_tab()
        self._refresh_issues()

    def sprite_add_frame(self):
        gi = self._sel_sprite_group()
        if gi is None:
            messagebox.showinfo("先建组", "请先点「＋ 组」创建一个精灵组，再往里面加帧。", parent=self)
            return
        group = self._sprite_groups()[gi]

        def apply(res):
            group.append({"image": res.b64})
            self._mark_dirty()
            self._refresh_sprite_tab()
            self._refresh_issues()

        ImageDialog(self, None, C.rgb565_to_rgb(self.theme.get("bgColor", 0)),
                    on_ok=apply)

    def sprite_edit_frame(self, fi):
        gi = self._sel_sprite_group()
        if gi is None:
            return
        group = self._sprite_groups()[gi]
        if not (0 <= fi < len(group)):
            return

        def apply(res):
            group[fi]["image"] = res.b64
            self._mark_dirty()
            self._refresh_sprite_tab()
            self._refresh_issues()

        ImageDialog(self, None, C.rgb565_to_rgb(self.theme.get("bgColor", 0)),
                    on_ok=apply)

    def sprite_del_frame(self, fi):
        gi = self._sel_sprite_group()
        if gi is None:
            return
        group = self._sprite_groups()[gi]
        if not (0 <= fi < len(group)):
            return
        self.snapshot("sprite:del_frame")
        del group[fi]
        self._mark_dirty()
        self._refresh_sprite_tab()
        self._refresh_issues()

    def loop_add(self):
        self.snapshot("loop:add")
        entry = {"type": "sprite", "sprite": 0, "x": 8, "y": 8,
                 "frameDelay": 200, "loopDelay": 1000}
        self._loop_entries().append(entry)
        self._mark_dirty()
        self._refresh_sprite_tab()
        self._refresh_issues()

    def loop_del(self):
        li = self._sel_loop_entry()
        if li is None:
            return
        self.snapshot("loop:del")
        del self._loop_entries()[li]
        self._mark_dirty()
        self._refresh_sprite_tab()
        self._refresh_issues()

    def edit_loop_entry(self, li):
        entries = self._loop_entries()
        if not (0 <= li < len(entries)):
            return
        entry = entries[li]
        host = self.props_host
        for w in host.winfo_children():
            w.destroy()
        host.columnconfigure(1, weight=1)
        ttk.Label(host, text="loop 实例 #%d" % li, style="Head.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(2, 8))

        def label(text, r):
            ttk.Label(host, text=text, style="Panel.TLabel").grid(
                row=r, column=0, sticky="w", pady=3)

        def num(key, r, text, lo=0, hi=32767, width=7):
            label(text, r)
            var = tk.IntVar(value=int(entry.get(key, 0) or 0))
            sp = ttk.Spinbox(host, from_=lo, to=hi, width=width, textvariable=var)
            sp.grid(row=r, column=1, sticky="w", pady=3)
            var.trace_add("write", lambda *a, k=key, v=var: self._set_loop_num(li, k, v))
            return var

        r = 1
        label("引用精灵", r)
        groups = self._sprite_groups()
        ref_var = tk.StringVar(value=str(entry.get("sprite", 0)))
        ref_cb = ttk.Combobox(host, values=[str(i) for i in range(len(groups))],
                              textvariable=ref_var, width=5, state="readonly")
        ref_cb.grid(row=r, column=1, sticky="w", pady=3)
        ref_cb.bind("<<ComboboxSelected>>",
                    lambda e: self._set_loop_num(li, "sprite", ref_var, is_str=True))
        r += 1

        num("x", r, "起始 x", -64, 127)
        r += 1
        num("y", r, "起始 y", -64, 127)
        r += 1
        num("frameDelay", r, "帧延时 ms", 1, 60000)
        r += 1
        num("loopDelay", r, "循环周期 ms", 1, 60000)
        r += 1
        num("moveStartTime", r, "位移触发 ms", 0, 60000)
        r += 1
        num("moveDuration", r, "位移时长 ms", 0, 60000)
        r += 1
        num("moveTargetX", r, "目标 x", -1, 127)
        r += 1
        num("moveTargetY", r, "目标 y", -1, 127)
        r += 1

        ret_var = tk.BooleanVar(value=bool(entry.get("shouldReturnToOrigin", False)))
        ttk.Checkbutton(host, text="到位后返回原点（往返）", variable=ret_var,
                        command=lambda: self._set_loop_bool(li, "shouldReturnToOrigin",
                                                            ret_var)).grid(
            row=r, column=0, columnspan=2, sticky="w", pady=4)
        r += 1

        ttk.Label(host, text="提示：位移只在 moveDuration>0 且目标 x/y 之一 >-1 时生效。\n"
                              "moveTargetX/Y 填 -1 表示该方向不动。",
                  style="Muted.TLabel", wraplength=286, justify="left").grid(
            row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _set_loop_num(self, li, key, var, is_str=False):
        entries = self._loop_entries()
        if not (0 <= li < len(entries)):
            return
        try:
            value = int(var.get())
        except Exception:
            return
        entry = entries[li]
        if entry.get(key) == value:
            return
        self.snapshot("loop:num:%s" % key)
        entry[key] = value
        self._mark_dirty()
        self._refresh_sprite_tab()
        self._refresh_issues()

    def _set_loop_bool(self, li, key, var):
        entries = self._loop_entries()
        if not (0 <= li < len(entries)):
            return
        self.snapshot("loop:bool:%s" % key)
        entries[li][key] = bool(var.get())
        self._mark_dirty()
        self._refresh_issues()

    def _anim_toggle(self):
        if self.anim_var.get():
            self._anim_t0 = time.time() * 1000.0
            self._anim_tick()
        else:
            self.redraw()

    def _anim_tick(self):
        if not self.anim_var.get():
            return
        t_ms = int(time.time() * 1000.0 - self._anim_t0)
        self._render_animated(t_ms)
        self.after(40, self._anim_tick)

    def _render_animated(self, t_ms):
        when = self.sim_time()
        img = C.render_theme_animated(self.theme, t_ms, when)
        z = self.zoom
        big = img.resize((C.PANEL * z, C.PANEL * z), Image.NEAREST)
        big = self._compose(big, z, when)
        self._photo = ImageTk.PhotoImage(big)
        cw = max(big.width, self.canvas.winfo_width() or big.width)
        ch = max(big.height, self.canvas.winfo_height() or big.height)
        self.canvas.coords(self.img_item, max(0, (cw - big.width) // 2),
                           max(0, (ch - big.height) // 2))
        self.canvas.itemconfig(self.img_item, image=self._photo)

    def _form_row(self, parent, row, label, widget):
        ttk.Label(parent, text=label, style="Panel.TLabel", width=7).grid(
            row=row, column=0, sticky="w", pady=3)
        widget.grid(row=row, column=1, sticky="ew", pady=3)
        return widget

    def _bind_keys(self):
        self.bind_all("<Control-z>", lambda e: self.do_undo())
        self.bind_all("<Control-y>", lambda e: self.do_redo())
        self.bind_all("<Control-s>", lambda e: self.save_file())
        self.bind_all("<Control-S>", lambda e: self.save_as())
        self.bind_all("<Control-o>", lambda e: self.open_file())
        self.bind_all("<Control-n>", lambda e: self.new_theme())
        self.bind_all("<Control-d>", lambda e: self.duplicate())
        self.bind_all("<Control-Up>", lambda e: self.move(-1))
        self.bind_all("<Control-Down>", lambda e: self.move(1))
        self.bind_all("<Control-u>", lambda e: self.dev_upload())
        self.canvas.bind("<Delete>", lambda e: self.delete_sel())
        for key, delta in (("Left", (-1, 0)), ("Right", (1, 0)),
                           ("Up", (0, -1)), ("Down", (0, 1))):
            self.canvas.bind("<%s>" % key, lambda e, d=delta: self.nudge(d))

    # ---------- 配置 ----------
    def _load_cfg(self):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_cfg(self):
        try:
            data = self._load_cfg()
            data["ip"] = self.ip_var.get().strip()
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    # ---------- 模型 ----------
    def current(self):
        setup = self.theme.get("setup", [])
        if 0 <= self.sel < len(setup):
            return setup[self.sel]
        return None

    def snapshot(self, key=None):
        data = C.theme_to_json(self.theme)
        now = time.time()
        if self.undo and key and key == self._last_key and now - self._last_ts < 0.9:
            self._last_ts = now
            self.redo = []
            return
        if self.undo and self.undo[-1] == data:
            return
        self.undo.append(data)
        if len(self.undo) > 80:
            self.undo.pop(0)
        self.redo = []
        self._last_key = key
        self._last_ts = now

    def do_undo(self):
        if not self.undo:
            return
        self.redo.append(C.theme_to_json(self.theme))
        self.theme = json.loads(self.undo.pop())
        self._clamp_sel()
        self.refresh_all(rebuild_props=True)
        self.msg("已撤销")

    def do_redo(self):
        if not self.redo:
            return
        self.undo.append(C.theme_to_json(self.theme))
        self.theme = json.loads(self.redo.pop())
        self._clamp_sel()
        self.refresh_all(rebuild_props=True)
        self.msg("已重做")

    def _clamp_sel(self):
        n = len(self.theme.get("setup", []))
        self.sel = max(0, min(self.sel, n - 1)) if n else 0

    def _mark_dirty(self):
        self.dirty = True
        self._update_title()

    def _update_title(self):
        name = self.theme.get("name") or "未命名"
        fname = os.path.basename(self.path) if self.path else "未保存"
        self.title("%s — %s%s [%s]" % (APP_NAME, name, " *" if self.dirty else "", fname))

    def msg(self, text, level="info"):
        self.msg_var.set(text)
        self._update_title()

    # ---------- 渲染 ----------
    def sim_time(self):
        if self.live_var.get():
            return datetime.now()
        raw = self.sim_var.get().strip()
        base = datetime.now()
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                t = datetime.strptime(raw, fmt)
                return base.replace(hour=t.hour, minute=t.minute, second=t.second,
                                    microsecond=0)
            except ValueError:
                continue
        return base

    def _live_toggle(self):
        if self.live_var.get():
            self.sim_var.set(datetime.now().strftime("%H:%M:%S"))
        self.redraw()

    def _set_now(self):
        self.sim_var.set(datetime.now().strftime("%H:%M:%S"))
        self.live_var.set(False)
        self.redraw()

    def _tick(self):
        if self.live_var.get():
            self.sim_var.set(datetime.now().strftime("%H:%M:%S"))
            self.redraw()
        self.after(1000, self._tick)

    def redraw(self):
        if getattr(self, "anim_var", None) and self.anim_var.get():
            return  # 动画播放中，由 _anim_tick 负责重绘
        when = self.sim_time()
        img = C.render_theme(self.theme, when)
        z = self.zoom
        big = img.resize((C.PANEL * z, C.PANEL * z), Image.NEAREST)
        big = self._compose(big, z, when)
        self._photo = ImageTk.PhotoImage(big)
        cw = max(big.width, self.canvas.winfo_width() or big.width)
        ch = max(big.height, self.canvas.winfo_height() or big.height)
        self.canvas.configure(scrollregion=(0, 0, cw, ch))
        self.canvas.coords(self.img_item,
                           max(0, (cw - big.width) // 2), max(0, (ch - big.height) // 2))
        self.canvas.itemconfig(self.img_item, image=self._photo)

    def _compose(self, big, z, when):
        """网格与选中框画在独立透明层上再叠加，避免盖住内容。"""
        from PIL import ImageDraw
        overlay = Image.new("RGBA", big.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        if self.grid_var.get():
            for i in range(8, C.PANEL, 8):
                pos = i * z
                alpha = 96 if i == 32 else 56
                color = (108, 122, 148, alpha)
                d.line([(pos, 0), (pos, big.height - 1)], fill=color, width=1)
                d.line([(0, pos), (big.width - 1, pos)], fill=color, width=1)
            if z >= 12:
                for i in range(1, C.PANEL):
                    if i % 8 == 0:
                        continue
                    pos = i * z
                    d.line([(pos, 0), (pos, big.height - 1)],
                           fill=(255, 255, 255, 16), width=1)
                    d.line([(0, pos), (big.width - 1, pos)],
                           fill=(255, 255, 255, 16), width=1)
        # 画布边框（64x64 边界）
        d.rectangle([0, 0, big.width - 1, big.height - 1],
                    outline=(60, 70, 90, 150), width=1)

        el = self.current()
        if el is not None:
            box = C.element_box(el, when)
            x0, y0 = box[0] * z, box[1] * z
            x1, y1 = box[2] * z - 1, box[3] * z - 1
            w = max(2, z // 3)
            d.rectangle([x0, y0, x1, y1], outline=(47, 111, 237, 255), width=w)
            s = max(4, z // 2)
            for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                d.rectangle([cx - s // 2, cy - s // 2, cx + s // 2, cy + s // 2],
                            fill=(47, 111, 237, 255), outline=(255, 255, 255, 255),
                            width=1)

        # loop 实例标记：起始点（橙色方块）+ 目标点（绿色空心圈）
        li = self._sel_loop_entry()
        if li is not None:
            entry = self._loop_entries()[li]
            sx, sy = int(entry.get("x", 0) or 0), int(entry.get("y", 0) or 0)
            d.rectangle([sx * z - z // 2, sy * z - z // 2,
                         sx * z + z // 2, sy * z + z // 2],
                        fill=(255, 140, 0, 255), outline=(255, 255, 255, 255), width=1)
            tx = entry.get("moveTargetX", -1)
            ty = entry.get("moveTargetY", -1)
            if tx not in (None, -1) and ty not in (None, -1):
                r = max(2, z // 3)
                d.ellipse([tx * z - r, ty * z - r, tx * z + r, ty * z + r],
                          outline=(16, 185, 129, 255), width=max(1, z // 4))
                d.line([sx * z, sy * z, tx * z, ty * z],
                       fill=(16, 185, 129, 120), width=1)
        return Image.alpha_composite(big.convert("RGBA"), overlay).convert("RGB")

    # ---------- 画布交互 ----------
    def _refit_zoom(self):
        if not self._zoom_auto:
            return
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 120 or h < 120:
            return
        z = max(4, min(14, int(min(w - 40, h - 40) // C.PANEL)))
        if z != self.zoom:
            self.zoom = z
            self.zoom_lbl.configure(text="%dx" % z)
            self.redraw()

    def _on_canvas_configure(self, evt):
        if self._zoom_auto and evt.width > 120 and evt.height > 120:
            z = int(min(evt.width - 40, evt.height - 40) // C.PANEL)
            z = max(4, min(14, z))
            if z != self.zoom:
                self.zoom = z
                self.zoom_lbl.configure(text="%dx" % z)
        self.redraw()

    def _to_panel(self, evt):
        bbox = self.canvas.bbox(self.img_item)
        if not bbox:
            return None
        x = (evt.x - bbox[0]) // self.zoom
        y = (evt.y - bbox[1]) // self.zoom
        if 0 <= x < C.PANEL and 0 <= y < C.PANEL:
            return int(x), int(y)
        return None

    def _hit_test(self, px, py):
        when = self.sim_time()
        setup = self.theme.get("setup", [])
        for idx in range(len(setup) - 1, -1, -1):
            x0, y0, x1, y1 = C.element_box(setup[idx], when)
            if x0 - 1 <= px <= x1 + 1 and y0 - 1 <= py <= y1 + 1:
                return idx
        return None

    def _hit_loop_marker(self, px, py):
        """命中 loop 实例标记时返回 (li, 'start'|'target')，否则 None。"""
        li = self._sel_loop_entry()
        if li is None:
            return None
        entry = self._loop_entries()[li]
        sx, sy = int(entry.get("x", 0) or 0), int(entry.get("y", 0) or 0)
        if abs(px - sx) <= 2 and abs(py - sy) <= 2:
            return (li, "start")
        tx = entry.get("moveTargetX", -1)
        ty = entry.get("moveTargetY", -1)
        if tx not in (None, -1) and ty not in (None, -1):
            if abs(px - int(tx)) <= 2 and abs(py - int(ty)) <= 2:
                return (li, "target")
        return None

    def _on_press(self, evt):
        pos = self._to_panel(evt)
        if pos is None:
            return
        # 优先检测 loop 实例标记（起始点/目标点拖拽）
        loop_hit = self._hit_loop_marker(*pos)
        if loop_hit is not None:
            self.canvas.focus_set()
            li, part = loop_hit
            self.snapshot("loop:drag")
            self._drag = {"kind": "loop", "li": li, "part": part, "start": pos}
            return
        hit = self._hit_test(*pos)
        self.canvas.focus_set()
        if hit is None:
            self.sel = -1
            self.refresh_selection_only()
            return
        if hit != self.sel:
            self.sel = hit
            self.refresh_selection_only()
        el = self.current()
        if el is None:
            return
        self.snapshot("drag")
        self._drag = {"kind": "element", "start": pos, "orig": dict(el)}

    def _on_drag(self, evt):
        if not self._drag:
            return
        pos = self._to_panel(evt)
        if pos is None:
            return
        drag = self._drag
        if drag.get("kind") == "loop":
            dx = pos[0] - drag["start"][0]
            dy = pos[1] - drag["start"][1]
            entry = self._loop_entries()[drag["li"]]
            if drag["part"] == "start":
                entry["x"] = int(entry.get("x", 0)) + dx
                entry["y"] = int(entry.get("y", 0)) + dy
            else:
                entry["moveTargetX"] = int(entry.get("moveTargetX", 0)) + dx
                entry["moveTargetY"] = int(entry.get("moveTargetY", 0)) + dy
            drag["start"] = pos
            self.redraw()
            self._refresh_sprite_tab()
            return
        el = self.current()
        if el is None:
            return
        dx = pos[0] - drag["start"][0]
        dy = pos[1] - drag["start"][1]
        orig = drag["orig"]
        el["x"] = int(orig.get("x", 0)) + dx
        el["y"] = int(orig.get("y", 0)) + dy
        if el.get("type") == "line":
            el["x1"] = int(orig.get("x1", 0)) + dx
            el["y1"] = int(orig.get("y1", 0)) + dy
        self.redraw()
        self.size_var.set(self._size_text())
        self._sync_props_numbers()

    def _on_release(self, _evt):
        if self._drag:
            self._drag = None
            self._mark_dirty()
            self._refresh_tree_labels()
            self._refresh_sprite_tab()

    def _on_motion(self, evt):
        pos = self._to_panel(evt)
        if pos is None:
            self.coord_var.set("")
        else:
            self.coord_var.set("x=%d  y=%d" % pos)

    def nudge(self, delta):
        el = self.current()
        if el is None:
            return
        self.snapshot("nudge")
        el["x"] = int(el.get("x", 0)) + delta[0]
        el["y"] = int(el.get("y", 0)) + delta[1]
        if el.get("type") == "line":
            el["x1"] = int(el.get("x1", 0)) + delta[0]
            el["y1"] = int(el.get("y1", 0)) + delta[1]
        self.redraw()
        self.size_var.set(self._size_text())
        self._sync_props_numbers()
        self._refresh_tree_labels()

    # ---------- 元素操作 ----------
    def add_element(self, kind):
        self.snapshot()
        el = C.new_element(kind)
        if kind in ("text", "datetime"):
            dx, dy = C.center_element(self.theme, el, "h", self.sim_time())
            el["x"] = dx
        elif kind == "rect":
            pass
        self.theme.setdefault("setup", []).append(el)
        self.sel = len(self.theme["setup"]) - 1
        self._mark_dirty()
        self.refresh_all(rebuild_props=True)
        if kind == "image":
            self.pick_image()

    def delete_sel(self):
        el = self.current()
        if el is None:
            return
        self.snapshot()
        del self.theme["setup"][self.sel]
        self._clamp_sel()
        self._mark_dirty()
        self.refresh_all(rebuild_props=True)

    def duplicate(self):
        el = self.current()
        if el is None:
            return
        self.snapshot()
        import copy
        clone = copy.deepcopy(el)
        clone["x"] = int(clone.get("x", 0)) + 2
        clone["y"] = int(clone.get("y", 0)) + 2
        self.theme["setup"].insert(self.sel + 1, clone)
        self.sel += 1
        self._mark_dirty()
        self.refresh_all(rebuild_props=True)

    def move(self, delta):
        setup = self.theme.get("setup", [])
        target = self.sel + delta
        if not (0 <= self.sel < len(setup)) or not (0 <= target < len(setup)):
            return
        self.snapshot()
        setup[self.sel], setup[target] = setup[target], setup[self.sel]
        self.sel = target
        self._mark_dirty()
        self.refresh_all(rebuild_props=True)

    # ---------- 刷新 ----------
    def refresh_all(self, rebuild_props=False):
        self._suppress = True
        self.name_var.set(self.theme.get("name", ""))
        self.author_var.set(self.theme.get("author", ""))
        self.ver_var.set(int(self.theme.get("version", 1) or 1))
        self.delay_var.set(int(self.theme.get("delay", 300) or 0))
        for child in self._form_colorrow():
            child.set(int(self.theme.get("bgColor", 0)))
        self._suppress = False
        self._refresh_tree()
        self._refresh_sprite_tab()
        if rebuild_props:
            self.rebuild_props()
        self.redraw()
        self.size_var.set(self._size_text())
        self._refresh_issues()
        self._update_title()

    def _form_colorrow(self):
        """左栏里的 ColorRow（主题背景色）。"""
        return [self._bg_row] if hasattr(self, "_bg_row") else []

    def _refresh_tree(self):
        self._suppress = True
        self.tree.delete(*self.tree.get_children())
        when = self.sim_time()
        for i, el in enumerate(self.theme.get("setup", [])):
            self.tree.insert("", "end", iid=str(i), values=self._row_values(el, when))
        if self.theme.get("setup") and 0 <= self.sel < len(self.theme["setup"]):
            self.tree.selection_set(str(self.sel))
            self.tree.see(str(self.sel))
        self._suppress = False

    def _row_values(self, el, when):
        kind = el.get("type", "?")
        label = C.TYPE_LABELS.get(kind, kind)
        if kind in ("text", "datetime"):
            info = el.get("content", "")
            preview = C.element_text(el, when)
            if kind == "datetime":
                info = "%s → %s" % (info, preview)
        elif kind in ("rect", "fillrect"):
            info = "%dx%d" % (int(el.get("width", 0)), int(el.get("height", 0)))
        elif kind == "line":
            info = "→(%s,%s)" % (el.get("x1"), el.get("y1"))
        elif kind == "image":
            size = C.image_size_from_b64(el.get("image") or "")
            info = "%dx%d" % size if size else "空图"
        else:
            info = ""
        return (label, info[:26], "%s,%s" % (el.get("x", 0), el.get("y", 0)))

    def _refresh_tree_labels(self):
        when = self.sim_time()
        for i, el in enumerate(self.theme.get("setup", [])):
            iid = str(i)
            if self.tree.exists(iid):
                self.tree.item(iid, values=self._row_values(el, when))

    def refresh_selection_only(self):
        self._suppress = True
        if self.theme.get("setup") and 0 <= self.sel < len(self.theme["setup"]):
            self.tree.selection_set(str(self.sel))
        else:
            self.tree.selection_remove(self.tree.selection())
        self._suppress = False
        self.rebuild_props()
        self.redraw()
        self._refresh_issues()

    def _on_tree_select(self, _evt):
        if self._suppress:
            return
        sel = self.tree.selection()
        if not sel:
            return
        self.sel = int(sel[0])
        self.rebuild_props()
        self.redraw()

    def _size_text(self):
        s = C.theme_summary(self.theme)
        pct = 100.0 * s["bytes"] / s["capacity"]
        return "JSON %s / %d KB (%.0f%%)   元素 %d" % (
            _fmt_bytes(s["bytes"]), s["capacity"] // 1024, pct, s["elements"])

    def _refresh_issues(self):
        issues = C.validate(self.theme, self.sim_time())
        errs = [m for lvl, m in issues if lvl == "error"]
        warns = [m for lvl, m in issues if lvl == "warn"]
        size = C.theme_bytes(self.theme)
        self.pbar.configure(value=min(100, 100.0 * size / C.JSON_DOC_CAPACITY))
        if errs:
            self.issue_lbl.configure(text="✕ %d 个错误 · %d 个提醒（点击查看）" % (len(errs), len(warns)),
                                     foreground=CLR_ERR, cursor="hand2")
        elif warns:
            self.issue_lbl.configure(text="! %d 个提醒（点击查看）" % len(warns),
                                     foreground=CLR_WARN, cursor="hand2")
        else:
            self.issue_lbl.configure(text="✓ 校验通过", foreground=CLR_OK, cursor="")
        self.issue_lbl.unbind("<Button-1>")
        if errs or warns:
            self.issue_lbl.bind("<Button-1>", lambda e, i=issues: self.show_issues(i))

    def show_issues(self, issues):
        win = tk.Toplevel(self)
        win.title("校验结果")
        win.configure(bg=CLR_BG)
        win.geometry("620x360")
        win.transient(self)
        txt = tk.Text(win, wrap="word", font=FONT_UI, bg="#ffffff", relief="flat",
                      padx=12, pady=10)
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        marks = {"error": "✕ 错误", "warn": "! 提醒", "info": "· 提示"}
        for level, message in issues:
            txt.insert("end", "%s  %s\n" % (marks.get(level, level), message))
        txt.configure(state="disabled")
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(0, 10))

    # ---------- 属性面板 ----------
    def rebuild_props(self):
        for child in self.props_host.winfo_children():
            child.destroy()
        el = self.current()
        host = self.props_host
        host.columnconfigure(1, weight=1)
        self._prop_vars = {}
        if el is None:
            ttk.Label(host, text="左侧选中一个元素后\n在这里编辑它的属性。",
                      style="Muted.TLabel", justify="left", wraplength=286).grid(row=0, column=0,
                                                                 columnspan=2, sticky="w",
                                                                 pady=8)
            ttk.Label(host, text="提示：画布上可直接拖动元素；\n方向键微调 1px；Ctrl+D 复制。",
                      style="Muted.TLabel", justify="left", wraplength=286).grid(row=1, column=0,
                                                                 columnspan=2, sticky="w")
            return

        kind = el.get("type")
        row = 0
        ttk.Label(host, text="%s   ·   %s" % (C.TYPE_LABELS.get(kind, kind), kind),
                  style="Head.TLabel").grid(row=row, column=0, columnspan=2,
                                             sticky="w", pady=(2, 8))
        row += 1

        def label(text, r):
            ttk.Label(host, text=text, style="Panel.TLabel").grid(
                row=r, column=0, sticky="w", pady=3)

        def num(key, r, label_text, lo=-64, hi=127, width=6):
            label(label_text, r)
            var = tk.IntVar(value=int(el.get(key, 0) or 0))
            sp = ttk.Spinbox(host, from_=lo, to=hi, width=width, textvariable=var,
                             command=lambda k=key, v=var: self._set_num(k, v))
            sp.grid(row=r, column=1, sticky="w", pady=3)
            var.trace_add("write", lambda *a, k=key, v=var: self._set_num(k, v))
            self._prop_vars[key] = var
            return var

        if kind in ("text", "datetime"):
            label("内容", row)
            content_var = tk.StringVar(value=el.get("content", ""))
            ent = ttk.Entry(host, textvariable=content_var)
            ent.grid(row=row, column=1, sticky="ew", pady=3)
            content_var.trace_add("write", lambda *a: self._set_text("content", content_var))
            row += 1

            label("字体", row)
            font_var = tk.StringVar(value=FONT_LABELS.get(el.get("font", "default"),
                                                          FONT_LABELS["default"]))
            cb = ttk.Combobox(host, values=[FONT_LABELS[k] for k in FONT_KEYS],
                              textvariable=font_var, state="readonly")
            cb.grid(row=row, column=1, sticky="ew", pady=3)
            cb.bind("<<ComboboxSelected>>", lambda e: self._set_font(font_var.get()))
            row += 1

            label("前景色", row)
            ColorRow(host, el.get("fgColor", 65535),
                     on_change=lambda v: self._set_color("fgColor", v)).grid(
                row=row, column=1, sticky="w", pady=3)
            row += 1

            label("背景色", row)
            bg_holder = ttk.Frame(host, style="Panel.TFrame")
            bg_holder.grid(row=row, column=1, sticky="w", pady=3)
            has_bg = "bgColor" in el
            bg_row = ColorRow(bg_holder, el.get("bgColor", 0),
                              on_change=lambda v: self._set_color("bgColor", v))
            bg_row.pack(side="left")
            if not has_bg:
                bg_row.btn.configure(state="disabled")
                bg_row.entry.configure(state="disabled")
            chk_var = tk.BooleanVar(value=has_bg)
            ttk.Checkbutton(host, text="填写 bgColor", variable=chk_var,
                            command=lambda: self._toggle_bg(chk_var, bg_row)).grid(
                row=row + 1, column=1, sticky="w")
            row += 2

            num("x", row, "x")
            row += 1
            num("y", row, "y")
            row += 1

            align = ttk.Frame(host, style="Panel.TFrame")
            align.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 2))
            ttk.Button(align, text="水平居中", width=10,
                       command=lambda: self.center_el("h")).pack(side="left")
            ttk.Button(align, text="垂直居中", width=10,
                       command=lambda: self.center_el("v")).pack(side="left", padx=6)
            row += 1

            when = self.sim_time()
            font = C.get_font(el.get("font"))
            text = C.element_text(el, when)
            x1, y1, w, h, adv = font.text_bounds(text, 0, 0)
            info = "墨迹 %dx%d · 偏移(%d,%d) · 进宽 %d" % (w, h, x1, y1, adv)
            ttk.Label(host, text=info, style="Muted.TLabel", wraplength=286,
                      justify="left").grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
            row += 1
            if kind == "datetime":
                ttk.Label(host, text="格式符 H:i · H:i:s · m-d · D, m/d · A\n"
                                     "（PHP/ezTime 风格，不是 strftime）",
                          style="Muted.TLabel", justify="left", wraplength=286).grid(
                    row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
                row += 1

        elif kind in ("rect", "fillrect"):
            label("颜色", row)
            ColorRow(host, el.get("color", 65535),
                     on_change=lambda v: self._set_color("color", v)).grid(
                row=row, column=1, sticky="w", pady=3)
            row += 1
            num("x", row, "x")
            row += 1
            num("y", row, "y")
            row += 1
            num("width", row, "宽", 0, 127)
            row += 1
            num("height", row, "高", 0, 127)
            row += 1
            bb = ttk.Frame(host, style="Panel.TFrame")
            bb.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 2))
            ttk.Button(bb, text="整屏 1px 边框", command=lambda: self.quick_rect("border")).pack(side="left")
            ttk.Button(bb, text="铺满全屏", command=lambda: self.quick_rect("full")).pack(side="left", padx=6)
            row += 1

        elif kind == "line":
            label("颜色", row)
            ColorRow(host, el.get("color", 65535),
                     on_change=lambda v: self._set_color("color", v)).grid(
                row=row, column=1, sticky="w", pady=3)
            row += 1
            num("x", row, "x")
            row += 1
            num("y", row, "y")
            row += 1
            num("x1", row, "x1")
            row += 1
            num("y1", row, "y1")
            row += 1
            bb = ttk.Frame(host, style="Panel.TFrame")
            bb.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 2))
            ttk.Button(bb, text="水平", width=6,
                       command=lambda: self.quick_line("h")).pack(side="left")
            ttk.Button(bb, text="垂直", width=6,
                       command=lambda: self.quick_line("v")).pack(side="left", padx=6)
            row += 1

        elif kind == "image":
            size = C.image_size_from_b64(el.get("image") or "")
            if size:
                raw_len = len(base64.b64decode(el.get("image") or ""))
                ok = raw_len <= C.IMAGE_DECODE_LIMIT
                ttk.Label(host, text="图片 %dx%d  ·  PNG %d B %s" % (
                    size[0], size[1], raw_len, "✓" if ok else "✕ 超限"),
                    style="Head.TLabel",
                    foreground=CLR_OK if ok else CLR_ERR).grid(
                    row=row, column=0, columnspan=2, sticky="w", pady=(0, 6))
                row += 1
                thumb = Image.open(io.BytesIO(base64.b64decode(el["image"])))
                thumb = thumb.convert("RGB")
                scale = max(1, min(6, 160 // max(thumb.size)))
                thumb = thumb.resize((thumb.size[0] * scale, thumb.size[1] * scale),
                                     Image.NEAREST)
                self._thumb_ref = ImageTk.PhotoImage(thumb)
                lb = tk.Label(host, image=self._thumb_ref, bg="#111111",
                              highlightbackground=CLR_BORDER, highlightthickness=1)
                lb.grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 8))
                row += 1
            bb = ttk.Frame(host, style="Panel.TFrame")
            bb.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(2, 6))
            ttk.Button(bb, text="选择图片…", command=self.pick_image).pack(side="left")
            row += 1
            num("x", row, "x")
            row += 1
            num("y", row, "y")
            row += 1
            ttk.Label(host, text="图片元素不支持透明度：透明像素会\n按导入时选的背景色填充。",
                      style="Muted.TLabel", justify="left").grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(6, 0))
            row += 1

        ttk.Separator(host, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=10)
        row += 1
        box = C.element_box(el, self.sim_time())
        host.update_idletasks()
        ttk.Label(host, text="包围盒 (%d,%d)-(%d,%d)，尺寸 %dx%d" % (
            box[0], box[1], box[2], box[3], box[2] - box[0], box[3] - box[1]),
            style="Muted.TLabel", wraplength=286, justify="left").grid(
            row=row, column=0, columnspan=2, sticky="w")

    # ---------- 属性改动 ----------
    def _after_field(self, key=None):
        self._mark_dirty()
        self.redraw()
        self.size_var.set(self._size_text())
        self._refresh_issues()
        self._refresh_tree_labels()

    def _set_num(self, key, var):
        el = self.current()
        if el is None:
            return
        try:
            value = int(var.get())
        except Exception:
            return
        if el.get(key) == value:
            return
        self.snapshot(key="num:%s" % key)
        el[key] = value
        self._after_field()

    def _sync_props_numbers(self):
        el = self.current()
        if el is None or not getattr(self, "_prop_vars", None):
            return
        for key, var in self._prop_vars.items():
            if key in el:
                try:
                    if int(var.get()) != int(el[key]):
                        var.set(int(el[key]))
                except Exception:
                    pass

    def _set_text(self, key, var):
        el = self.current()
        if el is None:
            return
        value = var.get()
        if el.get(key) == value:
            return
        self.snapshot(key="text:%s" % key)
        el[key] = value
        self._after_field()

    def _set_font(self, label):
        el = self.current()
        if el is None:
            return
        for key, text in FONT_LABELS.items():
            if text == label:
                self.snapshot(key="font")
                el["font"] = key
                self._after_field()
                self.rebuild_props()
                return

    def _set_color(self, key, value):
        el = self.current()
        if el is None:
            return
        if el.get(key) == value:
            return
        self.snapshot(key="color:%s" % key)
        el[key] = int(value)
        self._after_field()

    def _toggle_bg(self, var, bg_row):
        el = self.current()
        if el is None:
            return
        self.snapshot()
        if var.get():
            el["bgColor"] = int(bg_row.value)
            bg_row.btn.configure(state="normal")
            bg_row.entry.configure(state="normal")
        else:
            el.pop("bgColor", None)
            bg_row.btn.configure(state="disabled")
            bg_row.entry.configure(state="disabled")
        self._after_field()

    def _theme_field(self, key, var):
        if self._suppress:
            return
        raw = var.get()
        if key in ("version", "delay"):
            try:
                value = int(raw)
            except Exception:
                return
        else:
            value = str(raw)
        if self.theme.get(key) == value:
            return
        self.snapshot(key="theme:%s" % key)
        self.theme[key] = value
        self._mark_dirty()
        self._update_title()
        if key in ("bgColor",):
            self.redraw()

    def _theme_bg_change(self, value):
        self.snapshot(key="bg")
        self.theme["bgColor"] = int(value)
        self._mark_dirty()
        self.redraw()
        self._refresh_issues()

    def center_el(self, axis):
        el = self.current()
        if el is None:
            return
        self.snapshot()
        nx, ny = C.center_element(self.theme, el, axis, self.sim_time())
        if nx is not None:
            el["x"] = nx
        if ny is not None:
            el["y"] = ny
        self._after_field()
        self.rebuild_props()

    def quick_rect(self, mode):
        el = self.current()
        if el is None:
            return
        self.snapshot()
        if mode == "border":
            el.update({"x": 0, "y": 0, "width": 64, "height": 64})
            if el.get("type") == "fillrect":
                el.update({"x": 1, "y": 1, "width": 62, "height": 62})
        else:
            el.update({"x": 0, "y": 0, "width": 64, "height": 64})
        self._after_field()
        self.rebuild_props()

    def quick_line(self, mode):
        el = self.current()
        if el is None:
            return
        self.snapshot()
        if mode == "h":
            y = int(el.get("y", 32))
            el.update({"x1": 64, "y1": y})
        else:
            x = int(el.get("x", 32))
            el.update({"x1": x, "y1": 64})
        self._after_field()
        self.rebuild_props()

    # ---------- 图片 ----------
    def pick_image(self):
        el = self.current()
        if el is None:
            return
        path = filedialog.askopenfilename(
            parent=self, title="选择图片",
            filetypes=[("图片", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                       ("所有文件", "*.*")])
        if not path:
            return
        bg_rgb = C.rgb565_to_rgb(self.theme.get("bgColor", 0))

        def apply(res):
            self.snapshot()
            el["image"] = res.b64
            box = C.element_box(el, self.sim_time())
            w = res.width
            h = res.height
            el["x"] = max(0, min(C.PANEL - w, (C.PANEL - w) // 2))
            el["y"] = max(0, min(C.PANEL - h, (C.PANEL - h) // 2))
            self._after_field()
            self.rebuild_props()
            self.msg("图片已导入 %dx%d / %d B" % (w, h, res.size))

        ImageDialog(self, path, bg_rgb, on_ok=apply)

    # ---------- 文件 ----------
    def new_theme(self):
        if not self._confirm_discard():
            return
        self.theme = C.default_theme()
        self.path = None
        self.sel = 0
        self.undo, self.redo = [], []
        self.dirty = False
        self.refresh_all(rebuild_props=True)
        self.msg("已新建空白主题")

    def load_template(self, key):
        if not self._confirm_discard():
            return
        self.theme = C.template_theme(key)
        self.path = None
        self.sel = 0
        self.undo, self.redo = [], []
        self.dirty = True
        self.refresh_all(rebuild_props=True)
        self.msg("已载入模板：%s" % key)

    def _confirm_discard(self):
        if not self.dirty:
            return True
        return messagebox.askyesno("未保存的修改", "当前主题有未保存的修改，继续会丢失。继续吗？",
                                   parent=self)

    def open_file(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            parent=self, title="打开主题 JSON",
            filetypes=[("Canvas 主题", "*.json"), ("所有文件", "*.*")],
            initialdir=os.path.join(os.path.dirname(HERE), "canvas", "themes")
            if os.path.isdir(os.path.join(os.path.dirname(HERE), "canvas", "themes")) else HERE)
        if not path:
            return
        try:
            theme = C.load_theme_file(path)
        except Exception as exc:
            messagebox.showerror("打开失败", "不是合法的主题 JSON：\n%s" % exc, parent=self)
            return
        self.theme = theme
        self.path = path
        self.sel = 0
        self.undo, self.redo = [], []
        self.dirty = False
        self.refresh_all(rebuild_props=True)
        n = len(theme.get("sprites", []) or [])
        extra = "（含 %d 组精灵，本编辑器只编辑 setup 元素，精灵原样保留）" % n if n else ""
        self.msg("已打开 %s%s" % (os.path.basename(path), extra))

    def save_file(self):
        if not self.path:
            return self.save_as()
        return self._write(self.path)

    def save_as(self):
        path = filedialog.asksaveasfilename(
            parent=self, title="保存主题 JSON", defaultextension=".json",
            initialfile=(self.theme.get("name") or "theme") + ".json",
            filetypes=[("Canvas 主题", "*.json")])
        if not path:
            return
        return self._write(path)

    def _write(self, path):
        data = C.theme_to_json(self.theme)
        try:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(data)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return False
        self.path = path
        self.dirty = False
        self._update_title()
        self.msg("已保存 %s（%s）" % (os.path.basename(path), _fmt_bytes(len(data.encode("utf-8")))))
        return True

    def export_png(self):
        path = filedialog.asksaveasfilename(
            parent=self, title="导出 64x64 预览", defaultextension=".png",
            initialfile=(self.theme.get("name") or "preview") + ".png",
            filetypes=[("PNG", "*.png")])
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(C.render_preview_png(self.theme, scale=8, when=self.sim_time()))
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)
            return
        self.msg("已导出 %s" % os.path.basename(path))

    # ---------- 设备 ----------
    def _base_url(self):
        ip = self.ip_var.get().strip()
        if not ip:
            messagebox.showwarning("缺少设备地址", "请先在工具栏填写设备 IP。", parent=self)
            return None
        if not ip.startswith("http"):
            ip = "http://" + ip
        return ip.rstrip("/")

    def _request(self, method, path, body=None, timeout=8):
        base = self._base_url()
        if base is None:
            return None, None
        url = base + path
        req = urllib.request.Request(url, data=body, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read() if hasattr(exc, "read") else b""
        except Exception as exc:
            return None, str(exc).encode()

    def _async(self, work, done):
        def runner():
            result = work()
            self.after(0, lambda: done(result))
        threading.Thread(target=runner, daemon=True).start()

    def dev_ping(self):
        self.msg("正在连接设备…")
        self._save_cfg()

        def work():
            return self._request("GET", "/get", timeout=6)

        def done(res):
            status, body = res
            if status is None:
                self.msg("连接失败")
                messagebox.showerror("连接失败",
                                     "无法连接 %s\n\n%s\n\n检查：设备已上电、IP 正确、"
                                     "和电脑在同一网段。" % (self.ip_var.get(), body.decode("utf-8", "ignore")),
                                     parent=self)
                return
            self.msg("设备在线（HTTP %d）" % status)
            messagebox.showinfo("设备在线", "%s 可以访问（HTTP %d）。" % (self.ip_var.get(), status),
                                parent=self)

        self._async(work, done)

    def dev_list(self):
        self.msg("读取设备主题列表…")

        def work():
            return self._request("GET", "/themes", timeout=8)

        def done(res):
            status, body = res
            if status != 200:
                messagebox.showerror("读取失败", "HTTP %s" % status, parent=self)
                return
            names = [n.strip() for n in body.decode("utf-8", "ignore").splitlines() if n.strip()]
            win = tk.Toplevel(self)
            win.title("设备上的主题（%d）" % len(names))
            win.configure(bg=CLR_BG)
            win.geometry("360x420")
            win.transient(self)
            lb = tk.Listbox(win, font=FONT_MONO, bg="#ffffff", relief="flat",
                            selectmode="browse")
            lb.pack(fill="both", expand=True, padx=10, pady=10)
            for n in names:
                lb.insert("end", n)
            self.msg("设备上共 %d 个主题" % len(names))

        self._async(work, done)

    def dev_upload(self):
        name = (self.theme.get("name") or "").strip()
        name = "".join(ch for ch in name if ch.isalnum() or ch in "_-")
        if not name:
            name = "theme"
        name = name[:40]
        if not messagebox.askokcancel(
                "上传到设备",
                "将上传为设备上的主题名：%s\n（会覆盖同名文件，并把当前主题切到它，需重启生效）\n\n继续？"
                % name, parent=self):
            return
        payload = C.theme_to_json(self.theme).encode("utf-8")
        if len(payload) > C.JSON_DOC_CAPACITY:
            messagebox.showerror("体积超限",
                                 "JSON %d 字节超过固件缓冲区 %d 字节，先精简再上传。"
                                 % (len(payload), C.JSON_DOC_CAPACITY), parent=self)
            return
        self._save_cfg()
        self.msg("上传中…")

        def work():
            return self._request("POST", "/theme?name=" + urllib.parse.quote(name),
                                 body=payload, timeout=20)

        def done(res):
            status, body = res
            if status == 204:
                self.msg("上传成功（%s, %s）" % (name, _fmt_bytes(len(payload))))
                if messagebox.askyesno("上传成功",
                                       "已保存到设备：%s\n\n现在重启设备让它生效吗？"
                                       % name, parent=self):
                    self.dev_restart()
            elif status is None:
                self.msg("上传失败")
                messagebox.showerror("上传失败",
                                     "无法连接设备。\n\n%s\n\n提示：设备刚开机会阻塞约 10 秒去拉远程主题，"
                                     "期间不接受连接。" % body.decode("utf-8", "ignore"),
                                     parent=self)
            else:
                self.msg("上传失败 HTTP %s" % status)
                messagebox.showerror("上传失败",
                                     "设备返回 HTTP %s。\n检查主题名是否合法（字母数字_-）。" % status,
                                     parent=self)

        self._async(work, done)

    def dev_fetch(self):
        name = simple_prompt(self, "从设备读取", "主题名（不含 .json）", "pac-man")
        if not name:
            return
        self.msg("读取 %s …" % name)

        def work():
            return self._request("GET", "/theme?name=" + urllib.parse.quote(name.strip()),
                                 timeout=10)

        def done(res):
            status, body = res
            if status != 200:
                messagebox.showerror("读取失败", "HTTP %s（主题可能不存在）" % status, parent=self)
                return
            try:
                theme = json.loads(body.decode("utf-8"))
            except Exception as exc:
                messagebox.showerror("解析失败", str(exc), parent=self)
                return
            theme.setdefault("setup", [])
            self.theme = theme
            self.path = None
            self.sel = 0
            self.undo, self.redo = [], []
            self.dirty = True
            self.refresh_all(rebuild_props=True)
            self.msg("已从设备读取 %s" % name)

        self._async(work, done)

    def dev_restart(self):
        if not messagebox.askyesno("重启设备", "确定让设备重启吗？", parent=self):
            return
        self.msg("正在重启设备…")

        def work():
            return self._request("POST", "/restart", body=b"", timeout=6)

        def done(res):
            status, _ = res
            self.msg("重启指令已发送" if status else "重启指令发送失败")
            messagebox.showinfo("重启", "指令已发送（HTTP %s）。设备会在约 2 秒后重启。"
                                % status, parent=self)

        self._async(work, done)

    # ---------- 其它 ----------
    def set_zoom(self, delta):
        self._zoom_auto = False
        z = self.zoom + delta
        if z < 4:
            z = 4
        if z > 16:
            z = 16
        self.zoom = z
        self.zoom_lbl.configure(text="%dx" % z)
        self.redraw()

    def show_help(self):
        win = tk.Toplevel(self)
        win.title("Canvas 格式速查 / 固件限制")
        win.configure(bg=CLR_BG)
        win.geometry("700x560")
        win.transient(self)
        txt = tk.Text(win, wrap="word", font=FONT_UI, bg="#ffffff", relief="flat",
                      padx=14, pady=12)
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("end", HELP_TEXT)
        txt.configure(state="disabled")

    def on_close(self):
        if not self._confirm_discard():
            return
        self._save_cfg()
        self.destroy()


def _fmt_bytes(n):
    if n < 1024:
        return "%d B" % n
    return "%.1f KB" % (n / 1024.0)


def simple_prompt(parent, title, label, initial=""):
    win = tk.Toplevel(parent)
    win.title(title)
    win.configure(bg=CLR_BG)
    win.transient(parent)
    win.grab_set()
    ttk.Label(win, text=label, style="TLabel").pack(padx=14, pady=(14, 4), anchor="w")
    var = tk.StringVar(value=initial)
    ent = ttk.Entry(win, textvariable=var, width=32, font=FONT_MONO)
    ent.pack(padx=14, pady=4)
    ent.focus_set()
    result = {"value": None}

    def ok(_evt=None):
        result["value"] = var.get().strip()
        win.destroy()

    bar = ttk.Frame(win)
    bar.pack(padx=14, pady=10, anchor="e")
    ttk.Button(bar, text="取消", command=win.destroy).pack(side="right")
    ttk.Button(bar, text="确定", command=ok).pack(side="right", padx=6)
    ent.bind("<Return>", ok)
    parent.wait_window(win)
    return result["value"]


HELP_TEXT = """Canvas 主题格式（固件 cw-cf-0x07 / 本地分支）

根对象
  name     主题名，只打日志
  version  版本号，只打日志
  author   作者，只打日志
  bgColor  背景 RGB565 十进制
  delay    默认帧/循环间隔 ms
  setup[]  开机画一次的元素（本编辑器编辑的就是它）
  sprites[] 精灵帧（二维数组，本编辑器只保留不编辑）
  loop[]   精灵实例与位移动画

setup 元素
  text      content / font / fgColor / bgColor / x / y
  datetime  content 为 ezTime(PHP) 格式串，每秒重绘
  rect      color / x / y / width / height   空心
  fillrect  color / x / y / width / height   实心
  line      color / x / y / x1 / y1
  image     image(base64 PNG) / x / y

字体与高度（实测）
  big       hour8pt7b  高 14px  "12:34" 宽 42
  medium    minute7pt7b 高 9px  "12:34" 宽 22
  square    atariFont  高 11px  只有 12 个字形有内容，只能写纯数字
  picopixel Picopixel  高 5px  "12:34" 宽 16
  default   经典 5x7  高 8px

时间格式符（ezTime，不是 strftime）
  H:i  14:07      h:i  02:07     H:i:s  14:07:33
  m-d  10-28      D, m/d  Wed, 10/28     A  PM

固件硬限制（超了就是静默不显示）
  主题 JSON      <= 48KB（DynamicJsonDocument(49152)）
  单张图片 PNG   解码后 <= 1024 字节（IMAGE_BUFFER_SIZE）
  图片宽度       <= 64px（usPixels[64]）
  格式            必须是 PNG，JPG 不行
  坐标            x/y 取 uint8，0..255，屏幕只有 0..63

颜色是 RGB565：
  value = ((R>>3)<<11) | ((G>>2)<<5) | (B>>3)
  黑 0 · 白 65535 · 红 63488 · 绿 2016 · 蓝 31 · 黄 65504

坐标语义
  x/y 是文本基线的起点（不是左上角），文字的墨迹通常会往上超出 y。
  用「水平居中 / 垂直居中」按钮按真实字体度量计算，别手算。

上传流程
  POST /theme?name=xxx  → 204 表示成功，并自动把 canvasFile 指向它
  上传后必须重启（POST /restart）才生效；上传 GIF 大小限制 60000 字节。
"""


def main():
    app = Designer()
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
