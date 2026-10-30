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
import ui_kit as U  # noqa: E402
from ui_kit import ColorRow  # noqa: E402

APP_NAME = "ClockWise Canvas 编辑器"
APP_VER = "1.1"

# 视觉令牌集中在 ui_kit；这里保留别名，业务代码不必关心具体色值。
CLR_BG = U.BG
CLR_PANEL = U.SURFACE
CLR_BORDER = U.BORDER
CLR_TEXT = U.TEXT
CLR_MUTED = U.TEXT_MUTED
CLR_ACCENT = U.ACCENT
CLR_ACCENT_SOFT = U.ACCENT_SOFT
CLR_OK = U.OK
CLR_WARN = U.WARN
CLR_ERR = U.ERR
CLR_GRID = U.GRID

FONT_UI = U.FONT_UI
FONT_UI_B = U.FONT_UI_B
FONT_SMALL = U.FONT_SMALL
FONT_MONO = U.FONT_MONO
FONT_TITLE = U.FONT_TITLE

FONT_LABELS = {
    "big": "big  · 大字 14px",
    "medium": "medium · 中字 9px",
    "square": "square · atari 11px（仅数字）",
    "picopixel": "picopixel · 5px",
    "default": "default · 经典 5x7",
}
FONT_KEYS = list(FONT_LABELS)

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".clockwise_canvas_editor.json")


# ---------------------------------------------------------------- 动作表
# 菜单、快捷键、帮助面板、工具栏提示全部由这张表生成：
#   seq    绑定序列（空表示暂不绑定，仅出现在帮助里）
#   accel  菜单右侧显示的写法，保持与 seq 一致
#   scope  "global" 全局；"single" 单键（输入框聚焦时让行）
ACTIONS = (
    # ---- 文件 ----
    {"id": "new", "label": "新建空白主题", "group": "文件", "method": "new_theme",
     "seq": ("<Control-n>",), "accel": "Ctrl+N", "hint": "清空画布，回到空白主题"},
    {"id": "open", "label": "打开 JSON…", "group": "文件", "method": "open_file",
     "seq": ("<Control-o>",), "accel": "Ctrl+O", "hint": "载入本地主题文件"},
    {"id": "save", "label": "保存", "group": "文件", "method": "save_file",
     "seq": ("<Control-s>",), "accel": "Ctrl+S", "hint": "写回当前 JSON 文件"},
    {"id": "save_as", "label": "另存为…", "group": "文件", "method": "save_as",
     "seq": ("<Control-Shift-s>",), "accel": "Ctrl+Shift+S",
     "hint": "另存为新的 JSON 文件"},
    {"id": "export", "label": "导出预览 PNG…", "group": "文件",
     "method": "export_png", "seq": ("<Control-e>",), "accel": "Ctrl+E",
     "hint": "把当前画面导出成放大的 PNG"},
    {"id": "quit", "label": "退出", "group": "文件", "method": "on_close",
     "seq": ("<Control-q>",), "accel": "Ctrl+Q", "hint": "退出编辑器"},

    # ---- 编辑 ----
    {"id": "undo", "label": "撤销", "group": "编辑", "method": "do_undo",
     "seq": ("<Control-z>",), "accel": "Ctrl+Z", "hint": "回退上一步改动"},
    {"id": "redo", "label": "重做", "group": "编辑", "method": "do_redo",
     "seq": ("<Control-y>", "<Control-Shift-z>"), "accel": "Ctrl+Y",
     "hint": "重做刚撤销的改动"},
    {"id": "duplicate", "label": "复制元素", "group": "编辑", "method": "duplicate",
     "seq": ("<Control-d>",), "accel": "Ctrl+D", "hint": "原地偏移 2px 复制一份"},
    {"id": "delete", "label": "删除元素", "group": "编辑", "method": "delete_sel",
     "seq": ("<Delete>",), "accel": "Del", "scope": "single",
     "hint": "删除当前选中元素"},
    {"id": "raise", "label": "上移一层", "group": "编辑", "method": "raise_sel",
     "seq": ("<Control-Up>",), "accel": "Ctrl+↑", "hint": "在绘制顺序里往前排"},
    {"id": "lower", "label": "下移一层", "group": "编辑", "method": "lower_sel",
     "seq": ("<Control-Down>",), "accel": "Ctrl+↓", "hint": "在绘制顺序里往后排"},
    {"id": "prev", "label": "选中上一个", "group": "编辑", "method": "select_prev",
     "seq": ("<Control-Shift-Up>",), "accel": "Ctrl+Shift+↑",
     "hint": "在元素列表里向上切换"},
    {"id": "next", "label": "选中下一个", "group": "编辑", "method": "select_next",
     "seq": ("<Control-Shift-Down>",), "accel": "Ctrl+Shift+↓",
     "hint": "在元素列表里向下切换"},
    {"id": "deselect", "label": "取消选中", "group": "编辑", "method": "deselect",
     "seq": ("<Escape>",), "accel": "Esc", "scope": "single",
     "hint": "清除选中并隐藏选中框"},

    # ---- 视图 ----
    {"id": "zoom_in", "label": "放大", "group": "视图", "method": "zoom_in",
     "seq": ("<Control-equal>", "<Control-plus>"), "accel": "Ctrl+=",
     "hint": "画布放大一级"},
    {"id": "zoom_out", "label": "缩小", "group": "视图", "method": "zoom_out",
     "seq": ("<Control-minus>",), "accel": "Ctrl+-", "hint": "画布缩小一级"},
    {"id": "zoom_fit", "label": "适应窗口", "group": "视图", "method": "zoom_fit",
     "seq": ("<Control-0>",), "accel": "Ctrl+0", "hint": "恢复自动缩放"},
    {"id": "grid", "label": "显示网格", "group": "视图", "method": "toggle_grid",
     "seq": ("<Control-g>",), "accel": "Ctrl+G", "hint": "切换 8px 辅助网格"},

    # ---- 设备 ----
    {"id": "ping", "label": "连接测试", "group": "设备", "method": "dev_ping",
     "seq": (), "accel": "", "hint": "请求 /get，确认设备在线"},
    {"id": "list", "label": "列出设备主题…", "group": "设备", "method": "dev_list",
     "seq": (), "accel": "", "hint": "读取 /themes 列表"},
    {"id": "upload", "label": "上传当前主题…", "group": "设备", "method": "dev_upload",
     "seq": ("<Control-u>", "<Control-Return>"), "accel": "Ctrl+U",
     "hint": "POST 到设备并可选重启"},
    {"id": "fetch", "label": "从设备读取主题…", "group": "设备", "method": "dev_fetch",
     "seq": (), "accel": "", "hint": "把设备上的主题拉回来编辑"},
    {"id": "restart", "label": "重启设备", "group": "设备", "method": "dev_restart",
     "seq": (), "accel": "", "hint": "让新主题立即生效"},

    # ---- 帮助 ----
    {"id": "shortcuts", "label": "快捷键一览", "group": "帮助",
     "method": "show_shortcuts", "seq": ("<F1>",), "accel": "F1",
     "hint": "列出全部快捷键"},
    {"id": "help", "label": "格式速查 / 限制", "group": "帮助", "method": "show_help",
     "seq": (), "accel": "", "hint": "主题 JSON 格式与固件限制"},
    {"id": "about", "label": "关于", "group": "帮助", "method": "show_about",
     "seq": (), "accel": "", "hint": "版本与固件限制摘要"},
)

ACTION_MAP = {a["id"]: a for a in ACTIONS}



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
# ColorRow 已抽到 ui_kit.py（色块 + 565 输入 + 上下键微调）


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

    def __init__(self, master, src_path=None, bg_rgb=(0, 0, 0), on_ok=None,
                 fixed_size=None):
        tk.Toplevel.__init__(self, master)
        self.title("导入图片（自动压进 1024 字节）")
        self.configure(bg=CLR_BG)
        self.resizable(False, True)
        self.transient(master)
        self.on_ok = on_ok
        self.fixed_size = fixed_size      # 加帧时锁定为组内首帧尺寸
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
        self._fit_screen()
        # 缩略图是异步生成的，等内容就绪后再校一次尺寸
        self.after(180, self._fit_screen)
        self.grab_set()

    def _fit_screen(self):
        """按屏幕可用高度收口：窗口再矮，底部按钮也留在可视区内。"""
        if not self.winfo_exists():
            return
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w = max(470, self.winfo_reqwidth())
        h = min(max(self.winfo_reqheight(), 520), int(sh * 0.86))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2 - 20)
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))

    # ---------- UI ----------
    def _build(self):
        # 底部按钮区先 pack：窗口被屏幕高度压缩时，按钮永远不会被挤出可视区
        btns = ttk.Frame(self, padding=(12, 0, 12, 12))
        btns.pack(side="bottom", fill="x")
        self.auto_btn = ttk.Button(btns, text="自动压到 1024B 以内",
                                   style="Ghost.TButton", command=self._auto)
        self.auto_btn.pack(side="left")
        ttk.Button(btns, text="取消", style="Ghost.TButton",
                   command=self.destroy).pack(side="right")
        self.ok_btn = ttk.Button(btns, text="确定", style="Accent.TButton",
                                 command=self._ok)
        self.ok_btn.pack(side="right", padx=8)

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
        if self.fixed_size:
            ttk.Label(box, text="尺寸锁定为 %dx%d（与组内首帧一致）：需要别的尺寸请新建精灵组。"
                               % (self.fixed_size[0], self.fixed_size[1]),
                      style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

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
        sp_w = ttk.Spinbox(g, from_=4, to=64, width=5, textvariable=self.maxw_var,
                           command=self._schedule)
        sp_w.grid(row=0, column=1, sticky="w", padx=(4, 12))
        ttk.Label(g, text="最大高", font=FONT_UI).grid(row=0, column=2, sticky="w")
        sp_h = ttk.Spinbox(g, from_=4, to=64, width=5, textvariable=self.maxh_var,
                           command=self._schedule)
        sp_h.grid(row=0, column=3, sticky="w", padx=(4, 12))
        # 手输数字不点箭头时也要重算，否则按钮状态会停留在上一次结果
        for sp in (sp_w, sp_h):
            sp.bind("<Return>", lambda e: self._update())
            sp.bind("<FocusOut>", lambda e: self._update())
        if self.fixed_size:
            for sp in (sp_w, sp_h):
                sp.configure(state="disabled")
        ttk.Label(g, text="色数", font=FONT_UI).grid(row=0, column=4, sticky="w")
        cb = ttk.Combobox(g, values=("2", "4", "8", "16", "32"), width=4,
                          textvariable=self.colors_var, state="readonly")
        cb.grid(row=0, column=5, sticky="w", padx=(4, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self._schedule())

        U.Toggle(g, "抖动（体积更大）", self.dither_var, self._schedule,
                 bg=CLR_BG).grid(row=1, column=0, columnspan=3, sticky="w",
                                 pady=(8, 0))
        U.Toggle(g, "平滑缩放", self.smooth_var, self._schedule,
                 bg=CLR_BG).grid(row=1, column=3, columnspan=3, sticky="w",
                                 pady=(8, 0))

        ttk.Label(g, text="适配", font=FONT_UI).grid(row=2, column=0, sticky="w", pady=(8, 0))
        mb = ttk.Combobox(g, values=("等比缩小（不放大）", "等比放大填满", "裁切填满", "拉伸"),
                          width=15, textvariable=self.mode_var, state="readonly")
        mb.grid(row=2, column=1, columnspan=3, sticky="w", padx=(4, 0), pady=(8, 0))
        mb.bind("<<ComboboxSelected>>", lambda e: self._schedule())
        if self.fixed_size:
            # 尺寸被锁死时只能拉伸，才能保证每一帧的 w×h 完全一致
            self.mode_var.set("拉伸")
            mb.configure(state="disabled")
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
        if self.fixed_size:
            # 精灵组尺寸由第一帧决定，新帧必须跟着它，否则设备上会错位
            fw, fh = int(self.fixed_size[0]), int(self.fixed_size[1])
            self.maxw_var.set(max(1, min(64, fw)))
            self.maxh_var.set(max(1, min(64, fh)))
            self.path_var.set("%s  (%dx%d)  ·  锁定 %dx%d" % (
                os.path.basename(path), img.size[0], img.size[1], fw, fh))
        else:
            guess = 32 if big > 32 else max(4, big)
            self.maxw_var.set(min(guess, 64))
            self.maxh_var.set(min(guess, 64))
        self.size_lbl.configure(text="正在压缩…", foreground=CLR_MUTED)
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
        if not self.winfo_exists():
            return
        if self.src is None:
            self.size_lbl.configure(text="请先选择图片", foreground=CLR_MUTED)
            self.detail_lbl.configure(
                text="支持 PNG / JPG / BMP / WEBP，会自动压成索引色 PNG。",
                foreground=CLR_MUTED)
            self.ok_btn.state(["disabled"])
            self.ok_btn.configure(text="确定")
            self.auto_btn.configure(style="Ghost.TButton")
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
        if ok:
            self.detail_lbl.configure(
                text="base64 %d 字符（固件解码缓冲 1024B）" % len(res.b64),
                foreground=CLR_MUTED)
        else:
            self.detail_lbl.configure(
                text="超出 %d B：调小最大宽高或色数，或点左下角「自动压到 1024B 以内」"
                     % (res.size - C.IMAGE_DECODE_LIMIT),
                foreground=CLR_ERR)
        # 禁用时必须让按钮看起来就是禁用；同时把出路做成主按钮
        self.ok_btn.state([] if ok else ["disabled"])
        self.ok_btn.configure(text="确定" if ok else "超出 1024B")
        self.auto_btn.configure(style="Ghost.TButton" if ok else "Accent.TButton")
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
        if self.fixed_size:
            # 锁定尺寸时只保留同尺寸方案，避免点一个 8x8 就把帧改小
            target = (int(self.fixed_size[0]), int(self.fixed_size[1]))
            opts = [o for o in opts if o["size"] == target]
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
        if not self.fixed_size:
            self.maxw_var.set(o["size"][0])
            self.maxh_var.set(o["size"][1])
        self.result = o["result"]
        self._update()

    def _auto(self):
        if self.src is None:
            return
        work = self._work_image()
        p = self._params()
        if self.fixed_size:
            # 尺寸锁定时只能靠降色数达标，不能改宽高
            fw, fh = int(self.fixed_size[0]), int(self.fixed_size[1])
            res = None
            for colors in (16, 8, 4, 2):
                res = C.prepare_image(work, fw, fh, colors, dither=p["dither"],
                                      bg=p["bg"], mode="stretch",
                                      smooth=p["smooth"])
                if res.ok:
                    break
            if res is None or not res.ok:
                messagebox.showwarning(
                    "放不下",
                    "尺寸锁定为 %dx%d 时，即使 2 色也超过 1024 字节。\n"
                    "请换更简单的图，或新建一个更小的精灵组。" % (fw, fh),
                    parent=self)
                return
            self.colors_var.set(str(res.colors))
        else:
            res = C.auto_fit_image(work, limit=C.IMAGE_DECODE_LIMIT,
                                   max_w=p["max_w"], max_h=p["max_h"], bg=p["bg"],
                                   mode=p["mode"], smooth=p["smooth"],
                                   dither=p["dither"])
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

class _PropForm(object):
    """属性面板的行构建器。

    把「左标签 / 右控件」的两列网格、变量注册、分区标题收在一处；
    各元素类型的属性表只描述字段，不再重复排版代码。
    """

    def __init__(self, owner, host):
        self.owner = owner
        self.host = host
        self.row = 0
        host.columnconfigure(1, weight=1)

    def section(self, text):
        if self.row:
            tk.Frame(self.host, bg=U.BORDER, height=1).grid(
                row=self.row, column=0, columnspan=2, sticky="ew", pady=(12, 0))
            self.row += 1
        U.section(self.host, text).grid(
            row=self.row, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        self.row += 1

    def label(self, text):
        ttk.Label(self.host, text=text, style="Panel.TLabel").grid(
            row=self.row, column=0, sticky="w", pady=3, padx=(0, 8))

    def num(self, el, key, text, lo=-64, hi=127, width=8, setter=None,
            register=True, commit=False, on_change=None):
        self.label(text)
        var = tk.IntVar(value=int(el.get(key, 0) or 0))
        apply = setter or self.owner._set_num

        def do_apply(_evt=None):
            apply(key, var)
            if on_change:
                on_change()

        box = ttk.Spinbox(self.host, from_=lo, to=hi, width=width,
                          textvariable=var, command=do_apply)
        box.grid(row=self.row, column=1, sticky="w", pady=3)
        if commit:
            # 提交式：回车/失焦/箭头时落盘，避免逐位输入触发
            box.bind("<Return>", do_apply)
            box.bind("<FocusOut>", do_apply)
        else:
            var.trace_add("write", lambda *a: apply(key, var))
        if register:
            self.owner._prop_vars[key] = var
        self.row += 1
        return var

    def text(self, el, key, text):
        self.label(text)
        var = tk.StringVar(value=el.get(key, ""))
        ttk.Entry(self.host, textvariable=var).grid(
            row=self.row, column=1, sticky="ew", pady=3)
        var.trace_add("write", lambda *a: self.owner._set_text(key, var))
        self.owner._prop_text_vars[key] = var
        self.row += 1
        return var

    def color(self, el, key, text, default=65535, register=True):
        self.label(text)
        row = ColorRow(self.host, el.get(key, default),
                       on_change=lambda v: self.owner._set_color(key, v))
        row.grid(row=self.row, column=1, sticky="w", pady=3)
        if register:
            self.owner._prop_colors[key] = row
        self.row += 1
        return row

    def buttons(self, specs, pady=(9, 2)):
        box = tk.Frame(self.host, bg=U.SURFACE)
        box.grid(row=self.row, column=0, columnspan=2, sticky="ew", pady=pady)
        for text, cmd in specs:
            ttk.Button(box, text=text, style="Small.TButton",
                       command=cmd).pack(side="left", padx=(0, 6))
        self.row += 1
        return box

    def note(self, text, pady=(6, 0)):
        lab = ttk.Label(self.host, text=text, style="Muted.TLabel",
                        justify="left", wraplength=290)
        lab.grid(row=self.row, column=0, columnspan=2, sticky="w", pady=pady)
        self.row += 1
        return lab

    def wide(self, widget, pady=(0, 0)):
        widget.grid(row=self.row, column=0, columnspan=2, sticky="ew", pady=pady)
        self.row += 1
        return widget


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
        self._props_sig = None
        self._props_mode = None   # 属性面板当前显示：None / "element" / "loop"
        self._props_loop_li = None  # loop 模式下对应的 loop 索引
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
        """全部 ttk 样式集中在 ui_kit.install_styles，这里只装表。"""
        self.style = U.install_styles(self)

    def _menu_item(self, menu, aid, **kw):
        """菜单项从动作表取 label / accelerator，避免和快捷键两处不一致。"""
        act = ACTION_MAP[aid]
        opts = {"label": act["label"], "command": getattr(self, act["method"])}
        if act.get("accel"):
            opts["accelerator"] = act["accel"]
        opts.update(kw)
        menu.add_command(**opts)

    def _build_menu(self):
        opts = dict(bg=U.SURFACE, fg=U.TEXT, activebackground=U.ACCENT_SOFT,
                    activeforeground=U.ACCENT, bd=0, relief="flat",
                    activeborderwidth=0, font=FONT_UI)
        bar = tk.Menu(self, **opts)

        fm = tk.Menu(bar, tearoff=0, **opts)
        self._menu_item(fm, "new")
        tpl = tk.Menu(fm, tearoff=0, **opts)
        for label, key in (("极简（边框+分隔线）", "minimal"),
                           ("居中大字 + 日期", "bigcenter"),
                           ("纯文字问候", "hello"),
                           ("弹跳球动画（精灵）", "bounce")):
            tpl.add_command(label=label, command=lambda k=key: self.load_template(k))
        fm.add_cascade(label="从模板新建", menu=tpl)
        fm.add_separator()
        for aid in ("open", "save", "save_as"):
            self._menu_item(fm, aid)
        fm.add_separator()
        self._menu_item(fm, "export")
        fm.add_separator()
        self._menu_item(fm, "quit")
        bar.add_cascade(label="文件", menu=fm)

        em = tk.Menu(bar, tearoff=0, **opts)
        for aid in ("undo", "redo", None, "duplicate", "delete", None,
                    "raise", "lower", None, "prev", "next", "deselect"):
            if aid:
                self._menu_item(em, aid)
            else:
                em.add_separator()
        bar.add_cascade(label="编辑", menu=em)

        vm = tk.Menu(bar, tearoff=0, **opts)
        for aid in ("zoom_in", "zoom_out", "zoom_fit", None, "grid"):
            if aid:
                self._menu_item(vm, aid)
            else:
                vm.add_separator()
        bar.add_cascade(label="视图", menu=vm)

        dm = tk.Menu(bar, tearoff=0, **opts)
        for aid in ("ping", "list", "upload", "fetch", None, "restart"):
            if aid:
                self._menu_item(dm, aid)
            else:
                dm.add_separator()
        bar.add_cascade(label="设备", menu=dm)

        hm = tk.Menu(bar, tearoff=0, **opts)
        for aid in ("shortcuts", "help", None, "about"):
            if aid:
                self._menu_item(hm, aid)
            else:
                hm.add_separator()
        bar.add_cascade(label="帮助", menu=hm)

        self.config(menu=bar)

    def _build_toolbar(self):
        bar = tk.Frame(self, bg=U.SURFACE)
        bar.pack(side="top", fill="x")
        inner = tk.Frame(bar, bg=U.SURFACE)
        inner.pack(fill="x", padx=14, pady=(8, 7))

        def group():
            g = tk.Frame(inner, bg=U.SURFACE)
            g.pack(side="left", padx=(0, 12))
            return g

        def divider():
            tk.Frame(inner, bg=U.BORDER, width=1, height=22, bd=0).pack(
                side="left", padx=(0, 12))

        g = group()
        ttk.Button(g, text="打开", style="Ghost.TButton",
                   command=self.open_file).pack(side="left")
        ttk.Button(g, text="保存", style="Accent.TButton",
                   command=self.save_file).pack(side="left", padx=(6, 0))
        divider()

        g = group()
        ttk.Button(g, text="撤销", style="Ghost.TButton", width=5,
                   command=self.do_undo).pack(side="left")
        ttk.Button(g, text="重做", style="Ghost.TButton", width=5,
                   command=self.do_redo).pack(side="left", padx=(6, 0))
        divider()

        g = group()
        ttk.Label(g, text="缩放", style="Panel.TLabel").pack(side="left", padx=(0, 6))
        ttk.Button(g, text="−", style="Small.TButton", width=3,
                   command=lambda: self.set_zoom(-1)).pack(side="left")
        self.zoom_lbl = ttk.Label(g, text="8x", width=3, style="Head.TLabel",
                                  anchor="center")
        self.zoom_lbl.pack(side="left", padx=2)
        ttk.Button(g, text="+", style="Small.TButton", width=3,
                   command=lambda: self.set_zoom(1)).pack(side="left")
        self.grid_toggle = U.Toggle(g, "网格", self.grid_var, self.redraw)
        self.grid_toggle.pack(side="left", padx=(12, 0), pady=1)
        divider()

        g = group()
        ttk.Label(g, text="设备", style="Panel.TLabel").pack(side="left", padx=(0, 6))
        ttk.Entry(g, textvariable=self.ip_var, width=15,
                  font=FONT_MONO).pack(side="left")
        ttk.Button(g, text="测试", style="Small.TButton", width=5,
                   command=self.dev_ping).pack(side="left", padx=(6, 0))
        ttk.Button(g, text="上传", style="Small.TButton", width=5,
                   command=self.dev_upload).pack(side="left", padx=(4, 0))
        ttk.Button(g, text="读取", style="Small.TButton", width=5,
                   command=self.dev_fetch).pack(side="left", padx=(4, 0))

        right = tk.Frame(inner, bg=U.SURFACE)
        right.pack(side="right")
        ttk.Button(right, text="导出预览", style="Ghost.TButton",
                   command=self.export_png).pack(side="right")

        tk.Frame(bar, bg=U.BORDER, height=1, bd=0).pack(fill="x")

    def _build_body(self):
        body = tk.Frame(self, bg=CLR_BG)
        body.pack(side="top", fill="both", expand=True, padx=12, pady=(10, 6))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, minsize=268, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_columnconfigure(2, minsize=326, weight=0)
        self._build_left_panel(body)
        self._build_center_panel(body)
        self._build_right_panel(body)

    def _panel(self, body, column, width, sticky):
        """三栏共用的卡片：白底 + 1px 描边 + 固定宽度。"""
        outer = tk.Frame(body, bg=CLR_PANEL, width=width,
                         highlightbackground=CLR_BORDER, highlightthickness=1)
        outer.grid(row=0, column=column, sticky=sticky)
        # 子控件是 pack 的，必须用它才能锁住宽度
        outer.pack_propagate(False)
        return outer

    def _build_left_panel(self, body):
        left = self._panel(body, 0, 268, "nsw")

        head = tk.Frame(left, bg=CLR_PANEL)
        head.pack(fill="x", padx=14, pady=(12, 0))
        ttk.Label(head, text="主题", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="CANVAS JSON", style="Tiny.TLabel").pack(
            side="right", pady=(5, 0))

        form = tk.Frame(left, bg=CLR_PANEL)
        form.pack(fill="x", padx=14, pady=(8, 10))
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

        tk.Frame(left, bg=CLR_BORDER, height=1, bd=0).pack(fill="x")

        nb = ttk.Notebook(left)
        nb.pack(fill="both", expand=True, padx=10, pady=(8, 8))
        self.nb = nb

        # —— 元素页 ——
        elem_tab = tk.Frame(nb, bg=CLR_PANEL)
        nb.add(elem_tab, text="元素")

        eh = tk.Frame(elem_tab, bg=CLR_PANEL)
        eh.pack(fill="x", padx=2, pady=(6, 4))
        ttk.Label(eh, text="元素", style="Head.TLabel").pack(side="left")
        ttk.Label(eh, text="自下而上绘制", style="Tiny.TLabel").pack(
            side="right", pady=(2, 0))

        tree_box = tk.Frame(elem_tab, bg=CLR_PANEL)
        tree_box.pack(fill="both", expand=True, padx=2)
        self.tree = ttk.Treeview(tree_box, columns=("t", "c", "p"), show="headings",
                                 selectmode="browse", height=12)
        self.tree.heading("t", text="类型")
        self.tree.heading("c", text="内容")
        self.tree.heading("p", text="xy")
        self.tree.column("t", width=72, anchor="w", stretch=False)
        self.tree.column("c", width=100, anchor="w")
        self.tree.column("p", width=54, anchor="e", stretch=False)
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(tree_box, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Button-1>", self._on_tree_click)

        addbar = tk.Frame(elem_tab, bg=CLR_PANEL)
        addbar.pack(fill="x", padx=2, pady=(8, 4))
        self.add_btn = ttk.Menubutton(addbar, text="＋   添加元素",
                                      style="Add.TMenubutton")
        self.add_btn.pack(fill="x")
        menu = tk.Menu(self.add_btn, tearoff=0)
        for kind in C.ELEMENT_TYPES:
            menu.add_command(label="%s  (%s)" % (C.TYPE_LABELS[kind], kind),
                             command=lambda k=kind: self.add_element(k))
        self.add_btn["menu"] = menu

        row = tk.Frame(elem_tab, bg=CLR_PANEL)
        row.pack(fill="x", padx=2, pady=(0, 4))
        for col, (text, cmd) in enumerate((("删除", self.delete_sel),
                                           ("复制", self.duplicate),
                                           ("上移", self.raise_sel),
                                           ("下移", self.lower_sel))):
            row.columnconfigure(col, weight=1)
            ttk.Button(row, text=text, style="Tiny.TButton", command=cmd).grid(
                row=0, column=col, sticky="ew", padx=(0 if col == 0 else 4, 0))

        # —— 精灵动画页 ——
        self._build_sprite_tab(nb)

    def _build_center_panel(self, body):
        center = tk.Frame(body, bg=CLR_BG)
        center.grid(row=0, column=1, sticky="nsew", padx=12)

        # 双层边框模拟画布卡片的阴影
        stage = tk.Frame(center, bg="#dfe4ec")
        stage.pack(fill="both", expand=True)
        card = tk.Frame(stage, bg=U.CANVAS_BG)
        card.pack(fill="both", expand=True, padx=1, pady=1)

        self.canvas = tk.Canvas(card, bg=U.CANVAS_BG, highlightthickness=0,
                                cursor="crosshair", bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._photo = None
        self.img_item = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda e: self.coord_var.set(""))
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        # 右下角水印：画布尺寸
        self.size_tag = self.canvas.create_text(10, 10, text="64 × 64", anchor="se",
                                                fill=U.TEXT_FAINT,
                                                font=("Consolas", 8))

        tools = tk.Frame(center, bg=CLR_PANEL, highlightbackground=CLR_BORDER,
                         highlightthickness=1)
        tools.pack(fill="x", pady=(8, 0))
        row = tk.Frame(tools, bg=CLR_PANEL)
        row.pack(fill="x", padx=12, pady=6)
        ttk.Label(row, text="模拟时间", style="Panel.TLabel").pack(side="left")
        ent = ttk.Entry(row, textvariable=self.sim_var, width=9, font=FONT_MONO)
        ent.pack(side="left", padx=(6, 8))
        ent.bind("<Return>", lambda e: self.redraw())
        self.live_toggle = U.Toggle(row, "跟随系统时间", self.live_var,
                                    self._live_toggle)
        self.live_toggle.pack(side="left", padx=(2, 0))
        ttk.Button(row, text="设为现在", style="Tiny.TButton",
                   command=self._set_now).pack(side="left", padx=(10, 0))
        ttk.Label(row, textvariable=self.coord_var, style="Tiny.TLabel").pack(
            side="right")

    def _build_right_panel(self, body):
        right = self._panel(body, 2, 326, "nse")
        head = tk.Frame(right, bg=CLR_PANEL)
        head.pack(fill="x", padx=14, pady=(12, 0))
        ttk.Label(head, text="属性", style="Title.TLabel").pack(side="left")
        self.sel_badge = U.badge(head, "", fg=CLR_MUTED, bg=U.SURFACE_SUNK)
        self.sel_badge.pack(side="right", pady=(3, 0))
        self.props_host = tk.Frame(right, bg=CLR_PANEL)
        self.props_host.pack(fill="both", expand=True, padx=14, pady=(4, 12))


    def _build_status(self):
        bar = tk.Frame(self, bg=CLR_PANEL)
        bar.pack(side="bottom", fill="x")
        tk.Frame(bar, bg=CLR_BORDER, height=1, bd=0).pack(fill="x")

        inner = tk.Frame(bar, bg=CLR_PANEL)
        inner.pack(fill="x", padx=14, pady=6)
        ttk.Label(inner, textvariable=self.size_var, style="Muted.TLabel").pack(
            side="left")
        self.pbar = ttk.Progressbar(inner, length=96, maximum=100)
        self.pbar.pack(side="left", padx=(10, 12))

        # 校验结果做成彩色徽章，红/黄/绿一眼可辨
        self.issue_lbl = tk.Label(inner, text="", font=FONT_SMALL, fg=CLR_OK,
                                  bg=U.OK_SOFT, padx=8, pady=2, bd=0,
                                  highlightthickness=0)
        self.issue_lbl.pack(side="left")

        ttk.Label(inner, textvariable=self.msg_var, style="Tiny.TLabel").pack(
            side="right", padx=(8, 0))

    def _build_sprite_tab(self, nb):
        """左栏「精灵动画」标签页：精灵组 + loop 实例 + 播放开关。"""
        tab = tk.Frame(nb, bg=CLR_PANEL)
        nb.add(tab, text="动画")

        play = tk.Frame(tab, bg=CLR_PANEL)
        play.pack(fill="x", padx=2, pady=(8, 2))
        self.anim_var = tk.BooleanVar(value=False)
        self.anim_toggle = U.Toggle(play, "播放动画预览", self.anim_var,
                                    self._anim_toggle)
        self.anim_toggle.pack(side="left")

        # 精灵组列表
        sh = tk.Frame(tab, bg=CLR_PANEL)
        sh.pack(fill="x", padx=2, pady=(10, 3))
        ttk.Label(sh, text="精灵组", style="Head.TLabel").pack(side="left")
        ttk.Label(sh, text="多帧即连环画", style="Tiny.TLabel").pack(
            side="right", pady=(2, 0))
        sbox = tk.Frame(tab, bg=CLR_PANEL)
        sbox.pack(fill="x", padx=2)
        self.sprite_tree = ttk.Treeview(sbox, columns=("idx", "frames"), show="headings",
                                        selectmode="browse", height=4)
        self.sprite_tree.heading("idx", text="#")
        self.sprite_tree.heading("frames", text="帧")
        self.sprite_tree.column("idx", width=30, anchor="w", stretch=False)
        self.sprite_tree.column("frames", width=200, anchor="w")
        self.sprite_tree.pack(side="left", fill="x", expand=True)
        self.sprite_tree.bind("<<TreeviewSelect>>", self._on_sprite_select)

        sbtn = tk.Frame(tab, bg=CLR_PANEL)
        sbtn.pack(fill="x", padx=2, pady=(4, 2))
        ttk.Button(sbtn, text="＋ 组", style="Small.TButton",
                   command=self.sprite_add_group).pack(side="left")
        ttk.Button(sbtn, text="＋ 帧", style="Small.TButton",
                   command=self.sprite_add_frame).pack(side="left", padx=4)
        ttk.Button(sbtn, text="删除", style="Small.TButton",
                   command=self.sprite_del).pack(side="left")

        tk.Frame(tab, bg=CLR_BORDER, height=1).pack(fill="x", padx=2, pady=8)

        # loop 实例列表
        lh = tk.Frame(tab, bg=CLR_PANEL)
        lh.pack(fill="x", padx=2, pady=(2, 3))
        ttk.Label(lh, text="loop 实例", style="Head.TLabel").pack(side="left")
        ttk.Label(lh, text="放到画布上的动画", style="Tiny.TLabel").pack(
            side="right", pady=(2, 0))
        lb = tk.Frame(tab, bg=CLR_PANEL)
        lb.pack(fill="x", padx=2)
        self.loop_tree = ttk.Treeview(lb, columns=("idx", "info"), show="headings",
                                      selectmode="browse", height=4)
        self.loop_tree.heading("idx", text="#")
        self.loop_tree.heading("info", text="引用精灵 / 位置")
        self.loop_tree.column("idx", width=30, anchor="w", stretch=False)
        self.loop_tree.column("info", width=200, anchor="w")
        self.loop_tree.pack(side="left", fill="x", expand=True)
        self.loop_tree.bind("<<TreeviewSelect>>", self._on_loop_select)
        self.loop_tree.bind("<Button-1>", self._on_loop_click)

        lbtn = tk.Frame(tab, bg=CLR_PANEL)
        lbtn.pack(fill="x", padx=2, pady=(4, 2))
        ttk.Button(lbtn, text="＋ 实例", style="Small.TButton",
                   command=self.loop_add).pack(side="left")
        ttk.Button(lbtn, text="删除", style="Small.TButton",
                   command=self.loop_del).pack(side="left", padx=4)

        tk.Frame(tab, bg=CLR_BORDER, height=1).pack(fill="x", padx=2, pady=8)

        # 帧预览
        fp = tk.Frame(tab, bg=CLR_PANEL)
        fp.pack(fill="x", padx=2)
        ttk.Label(fp, text="帧预览", style="Head.TLabel").pack(side="left")
        ttk.Label(fp, text="单击编辑 · 双击删除", style="Tiny.TLabel").pack(
            side="right", pady=(2, 0))
        self.frame_host = tk.Frame(tab, bg=CLR_PANEL)
        self.frame_host.pack(fill="both", expand=True, padx=2, pady=(4, 8))

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
        U.stripe_tree(self.sprite_tree)
        U.stripe_tree(self.loop_tree)
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
            if self._props_mode == "loop" and self._props_loop_li == li:
                return
            self._props_mode = "loop"
            self._props_loop_li = li
            self.edit_loop_entry(li)

    def _on_loop_click(self, _evt):
        """点 loop 列表（即使选中项没变）也强制切回 loop 属性面板。"""
        if self._suppress:
            return
        li = self._sel_loop_entry()
        if li is not None and self._props_mode != "loop":
            self._props_mode = "loop"
            self._props_loop_li = li
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

    def _frame_size(self, group):
        """组内首帧尺寸。固件用第一帧 setDimensions，后续帧必须同尺寸。"""
        for frame in group or []:
            size = C.image_size_from_b64((frame or {}).get("image") or "")
            if size:
                return size
        return None

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
                    on_ok=apply, fixed_size=self._frame_size(group))

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
                    on_ok=apply, fixed_size=self._frame_size(group))

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
        # 属性面板这一轮显示的是 loop 实例，重置缓存签名，避免下次重建判定错乱
        self._props_sig = None
        self._prop_vars = {}
        self._prop_text_vars = {}
        self._prop_colors = {}
        self._metrics_lbl = self._bbox_lbl = self._img_info_lbl = None
        self.sel_badge.configure(text="loop #%d" % li, fg=CLR_ACCENT, bg=U.ACCENT_SOFT)

        form = _PropForm(self, host)
        ttk.Label(host, text="loop 实例 #%d" % li, style="Head.TLabel").grid(
            row=form.row, column=0, columnspan=2, sticky="w", pady=(2, 8))
        form.row += 1

        form.label("引用精灵")
        groups = self._sprite_groups()
        ref_var = tk.StringVar(value=str(entry.get("sprite", 0)))
        ref_cb = ttk.Combobox(host, values=[str(i) for i in range(len(groups))],
                              textvariable=ref_var, width=5, state="readonly")
        ref_cb.grid(row=form.row, column=1, sticky="w", pady=3)
        ref_cb.bind("<<ComboboxSelected>>",
                    lambda e: self._set_loop_num(li, "sprite", ref_var, is_str=True))
        form.row += 1

        def apply(key, var):
            self._set_loop_num(li, key, var)

        form.section("位置")
        form.num(entry, "x", "起始 x", -64, 127, setter=apply, register=False,
                 commit=True)
        form.num(entry, "y", "起始 y", -64, 127, setter=apply, register=False,
                 commit=True)

        form.section("节奏")
        form.num(entry, "frameDelay", "帧延时 ms", 1, 60000, setter=apply,
                 register=False, commit=True,
                 on_change=lambda: self._sync_loop_delay(li))
        self._loop_loop_delay_var = form.num(
            entry, "loopDelay", "循环周期 ms", 1, 60000, setter=apply,
            register=False, commit=True)

        form.section("位移")
        form.num(entry, "moveStartTime", "位移触发 ms", 0, 60000,
                 setter=apply, register=False, commit=True)
        form.num(entry, "moveDuration", "位移时长 ms", 0, 60000,
                 setter=apply, register=False, commit=True)
        form.num(entry, "moveTargetX", "目标 x", -1, 127, setter=apply,
                 register=False, commit=True)
        form.num(entry, "moveTargetY", "目标 y", -1, 127, setter=apply,
                 register=False, commit=True)

        ret_var = tk.BooleanVar(value=bool(entry.get("shouldReturnToOrigin", False)))
        U.Toggle(host, "到位后返回原点（往返）", ret_var,
                 lambda: self._set_loop_bool(li, "shouldReturnToOrigin",
                                             ret_var)).grid(
            row=form.row, column=0, columnspan=2, sticky="w", pady=(8, 4))
        form.row += 1

        groups = self._sprite_groups()
        ref = int(entry.get("sprite", 0) or 0)
        frame_count = len(groups[ref]) if 0 <= ref < len(groups) else 1
        form.note("帧延时改动会自动同步循环周期（帧延时 × %d 帧）。\n"
                  "位移只在 moveDuration>0 且目标 x/y 之一 >-1 时生效；\n"
                  "moveTargetX/Y 填 -1 表示该方向不动。" % frame_count,
                  pady=(8, 0))

    def _sync_loop_delay(self, li):
        """帧延时改动后，同步循环周期 = 帧延时 × 帧数。"""
        entries = self._loop_entries()
        if not (0 <= li < len(entries)):
            return
        entry = entries[li]
        groups = self._sprite_groups()
        ref = int(entry.get("sprite", 0) or 0)
        frame_count = len(groups[ref]) if 0 <= ref < len(groups) else 1
        fd = int(entry.get("frameDelay", 0) or 0)
        if fd <= 0 or frame_count <= 0:
            return
        new_loop = fd * frame_count
        if entry.get("loopDelay") == new_loop:
            return
        self.snapshot("loop:num:loopDelay")
        entry["loopDelay"] = new_loop
        if getattr(self, "_loop_loop_delay_var", None) is not None:
            try:
                if int(self._loop_loop_delay_var.get()) != new_loop:
                    self._loop_loop_delay_var.set(new_loop)
            except Exception:
                pass
        self._refresh_sprite_tab()
        self._refresh_issues()

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
        # 切换引用精灵后帧数变了，重新同步循环周期
        if key == "sprite":
            self._sync_loop_delay(li)

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
        ttk.Label(parent, text=label, style="Muted.TLabel").grid(
            row=row, column=0, sticky="w", pady=3, padx=(0, 8))
        widget.grid(row=row, column=1, sticky="ew", pady=3)
        return widget

    # ---------- 快捷键 ----------
    TEXT_WIDGETS = frozenset(("Entry", "TEntry", "Spinbox", "TSpinbox",
                              "TCombobox", "Text"))

    def _text_focused(self):
        """焦点在文本输入类控件里时，单键（Del / Esc）应该让行给它。"""
        try:
            w = self.focus_get()
        except Exception:
            return False
        return w is not None and w.winfo_class() in self.TEXT_WIDGETS

    def _in_main_window(self):
        """弹窗打开时不响应主窗口快捷键，避免在对话框里按 Del 删掉元素。"""
        try:
            w = self.focus_get()
        except Exception:
            return True
        if w is None:
            return True
        try:
            return w.winfo_toplevel() is self
        except Exception:
            return True

    def _handler(self, act):
        method = getattr(self, act["method"])
        single = act.get("scope") == "single"

        def run(_evt=None):
            if not self._in_main_window():
                return None
            if single and self._text_focused():
                return None
            method()
            return "break"

        return run

    def _bind_keys(self):
        """绑定全部来自 ACTIONS，新增动作不需要再改这里。"""
        for act in ACTIONS:
            handler = self._handler(act)
            for seq in act.get("seq", ()):
                self.bind_all(seq, handler, add="+")
        # 画布内方向键微调：1px，按住 Shift 走 10px
        for key, delta in (("Left", (-1, 0)), ("Right", (1, 0)),
                           ("Up", (0, -1)), ("Down", (0, 1))):
            self.canvas.bind("<%s>" % key, lambda e, d=delta: self._nudge_key(e, d))
            self.canvas.bind("<Shift-%s>" % key,
                             lambda e, d=delta: self._nudge_key(e, d, 10))
        self.canvas.bind("<Control-MouseWheel>", self._on_wheel)

    def _nudge_key(self, _evt, delta, step=1):
        self.nudge((delta[0] * step, delta[1] * step))
        return "break"

    def _on_wheel(self, evt):
        self.set_zoom(1 if evt.delta > 0 else -1)
        return "break"

    # ---------- 视图动作 ----------
    def raise_sel(self):
        self.move(-1)

    def lower_sel(self):
        self.move(1)

    def select_prev(self):
        self._select_step(-1)

    def select_next(self):
        self._select_step(1)

    def _select_step(self, delta):
        n = len(self.theme.get("setup", []))
        if not n:
            return
        base = self.sel if 0 <= self.sel < n else (-1 if delta > 0 else n)
        self.sel = max(0, min(n - 1, base + delta))
        self.refresh_selection_only()
        self.msg("选中第 %d / %d 个元素" % (self.sel + 1, n))

    def deselect(self):
        if self.sel < 0:
            return
        self.sel = -1
        self.refresh_selection_only()

    def zoom_in(self):
        self.set_zoom(1)

    def zoom_out(self):
        self.set_zoom(-1)

    def zoom_fit(self):
        self._zoom_auto = True
        self._refit_zoom()
        self.msg("缩放已适应窗口")

    def toggle_grid(self):
        if getattr(self, "grid_toggle", None) is not None:
            self.grid_toggle.toggle()
        else:
            self.grid_var.set(not self.grid_var.get())
            self.redraw()

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
        if getattr(self, "live_toggle", None) is not None:
            self.live_toggle.set(False)
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
        if getattr(self, "size_tag", None):
            self.canvas.coords(self.size_tag, evt.width - 10, evt.height - 8)
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
        """全量刷新：模型 → 左栏表单 → 列表 → 属性 → 画布 → 状态栏。"""
        self._suppress = True
        self.name_var.set(self.theme.get("name", ""))
        self.author_var.set(self.theme.get("author", ""))
        self.ver_var.set(int(self.theme.get("version", 1) or 1))
        self.delay_var.set(int(self.theme.get("delay", 300) or 0))
        self._bg_row.set(int(self.theme.get("bgColor", 0)))
        self._suppress = False
        self._refresh_tree()
        self._refresh_sprite_tab()
        if rebuild_props:
            self.rebuild_props()
        size = C.theme_bytes(self.theme)
        self.redraw()
        self.size_var.set(self._size_text(size))
        self._refresh_issues(size)
        self._update_title()

    def _refresh_tree(self):
        self._suppress = True
        self.tree.delete(*self.tree.get_children())
        when = self.sim_time()
        for i, el in enumerate(self.theme.get("setup", [])):
            self.tree.insert("", "end", iid=str(i), values=self._row_values(el, when))
        U.stripe_tree(self.tree)
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
        self.rebuild_props(force=False)
        self.redraw()
        self._refresh_issues()

    def _on_tree_select(self, _evt):
        if self._suppress:
            return
        sel = self.tree.selection()
        if not sel:
            return
        new_sel = int(sel[0])
        # 选中项没变且已是元素模式 → 无事可做，直接返回（避免循环刷新）
        if new_sel == self.sel and self._props_mode == "element":
            return
        self.sel = new_sel
        # 切回元素模式，重画元素属性面板
        self._props_mode = "element"
        self._props_loop_li = None
        self.refresh_selection_only()

    def _on_tree_click(self, _evt):
        """点元素树（即使选中项没变）也强制切回元素属性面板。

        用户从 loop 属性切回元素时，若点的是原本就选中的那项，
        <<TreeviewSelect>> 不会触发，这里用 Button-1 兜底。
        """
        if self._suppress:
            return
        if self._props_mode != "element":
            sel = self.tree.selection()
            if sel:
                self.sel = int(sel[0])
                self._props_mode = "element"
                self._props_loop_li = None
                self.refresh_selection_only()

    def _size_text(self, size=None):
        size = C.theme_bytes(self.theme) if size is None else size
        pct = 100.0 * size / C.JSON_DOC_CAPACITY
        return "JSON %s / %d KB (%.0f%%)   ·   %d 个元素" % (
            _fmt_bytes(size), C.JSON_DOC_CAPACITY // 1024, pct,
            len(self.theme.get("setup", []) or []))

    def _refresh_issues(self, size=None):
        size = C.theme_bytes(self.theme) if size is None else size
        issues = C.validate(self.theme, self.sim_time(), size=size)
        errs = [m for lvl, m in issues if lvl == "error"]
        warns = [m for lvl, m in issues if lvl == "warn"]
        self.pbar.configure(value=min(100, 100.0 * size / C.JSON_DOC_CAPACITY))
        if errs:
            text = "✕  %d 个错误 · %d 个提醒" % (len(errs), len(warns))
            fg, bg, cursor = CLR_ERR, U.ERR_SOFT, "hand2"
        elif warns:
            text = "!  %d 个提醒" % len(warns)
            fg, bg, cursor = CLR_WARN, U.WARN_SOFT, "hand2"
        else:
            text, fg, bg, cursor = "✓  校验通过", CLR_OK, U.OK_SOFT, ""
        self.issue_lbl.configure(text=text, fg=fg, bg=bg, cursor=cursor)
        self.issue_lbl.unbind("<Button-1>")
        if errs or warns:
            self.issue_lbl.bind("<Button-1>", lambda e, i=issues: self.show_issues(i))
        return issues

    def show_issues(self, issues):
        win = U.prepare_window(tk.Toplevel(self), "校验结果", "660x420", self)
        win.configure(bg=CLR_PANEL)
        head = tk.Frame(win, bg=CLR_PANEL)
        head.pack(fill="x", padx=18, pady=(14, 8))
        ttk.Label(head, text="校验结果", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="%d 条" % len(issues), style="Tiny.TLabel").pack(
            side="right", pady=(4, 0))
        tk.Frame(win, bg=CLR_BORDER, height=1).pack(fill="x")

        txt = tk.Text(win, wrap="word", font=FONT_UI, bg=CLR_PANEL, relief="flat",
                      padx=16, pady=12, bd=0, highlightthickness=0,
                      spacing1=2, spacing3=5)
        txt.pack(fill="both", expand=True)
        marks = {"error": "✕  错误", "warn": "!  提醒", "info": "·  提示"}
        colors = {"error": CLR_ERR, "warn": CLR_WARN, "info": CLR_MUTED}
        for level, color in colors.items():
            txt.tag_configure(level, foreground=color)
        for level, message in issues:
            txt.insert("end", "%s    " % marks.get(level, level), (level,))
            txt.insert("end", "%s\n" % message)
        txt.configure(state="disabled")

        foot = tk.Frame(win, bg=CLR_PANEL)
        foot.pack(fill="x", padx=18, pady=(0, 12))
        ttk.Button(foot, text="关闭", style="Ghost.TButton",
                   command=win.destroy).pack(side="right")

    # ---------- 属性面板 ----------
    def _build_empty_props(self):
        host = self.props_host
        host.columnconfigure(1, weight=1)
        card = tk.Frame(host, bg=U.SURFACE_ALT, highlightbackground=U.BORDER,
                        highlightthickness=1)
        card.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(4, 10))
        tk.Label(card, text="未选中元素", bg=U.SURFACE_ALT, fg=U.TEXT,
                 font=U.FONT_UI_B).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Label(card, text="在左侧列表或画布上点选一个元素，\n这里会显示它的全部属性。",
                 bg=U.SURFACE_ALT, fg=U.TEXT_MUTED, font=U.FONT_SMALL,
                 justify="left").pack(anchor="w", padx=12, pady=(0, 10))

        tips = ("画布操作\n"
                "· 拖动元素移动位置\n"
                "· 方向键微调 1px，Shift+方向键 10px\n"
                "· Ctrl+滚轮缩放\n"
                "· Ctrl+D 复制，Del 删除，Esc 取消选中")
        ttk.Label(host, text=tips, style="Muted.TLabel", justify="left").grid(
            row=1, column=0, columnspan=2, sticky="w")

    def rebuild_props(self, force=True):
        """重建右栏属性面板。

        loop 模式优先：属性面板显示 loop 实例时，走 edit_loop_entry。
        force=False 时用 (选中索引, 类型, 字段集合) 判断是否必须重建：
        字段没变就只同步数值，避免拖动/撤销时反复销毁控件导致焦点丢失。
        """
        if self._props_mode == "loop" and self._props_loop_li is not None:
            self.edit_loop_entry(self._props_loop_li)
            return
        el = self.current()
        sig = (self.sel,
               el.get("type") if el else None,
               tuple(sorted(el.keys())) if el else ())
        if not force and sig == self._props_sig:
            self._sync_props_all()
            self._refresh_prop_info()
            return
        self._props_sig = sig

        self._prop_vars = {}
        self._prop_text_vars = {}
        self._prop_colors = {}
        self._prop_font_var = None
        self._metrics_lbl = None
        self._bbox_lbl = None
        self._img_info_lbl = None
        self._thumb_ref = None

        for child in self.props_host.winfo_children():
            child.destroy()

        if el is None:
            self.sel_badge.configure(text="未选中", fg=CLR_MUTED, bg=U.SURFACE_SUNK)
            self._build_empty_props()
            return

        kind = el.get("type") or "?"
        self.sel_badge.configure(text=C.TYPE_LABELS.get(kind, kind),
                                 fg=CLR_ACCENT, bg=U.ACCENT_SOFT)
        form = _PropForm(self, self.props_host)
        handler = {"text": self._props_text, "datetime": self._props_text,
                   "rect": self._props_rect, "fillrect": self._props_rect,
                   "line": self._props_line, "image": self._props_image}.get(kind)
        if handler:
            handler(form, el)
        self._props_footer(form, el)

    def _props_text(self, f, el):
        kind = el.get("type")
        f.section("内容")
        f.text(el, "content", "文字" if kind == "text" else "格式")
        f.label("字体")
        font_var = tk.StringVar(value=FONT_LABELS.get(el.get("font", "default"),
                                                      FONT_LABELS["default"]))
        cb = ttk.Combobox(self.props_host, values=[FONT_LABELS[k] for k in FONT_KEYS],
                          textvariable=font_var, state="readonly")
        cb.grid(row=f.row, column=1, sticky="ew", pady=3)
        cb.bind("<<ComboboxSelected>>", lambda e: self._set_font(font_var.get()))
        self._prop_font_var = font_var
        f.row += 1

        f.section("颜色")
        f.color(el, "fgColor", "前景色", 65535)
        f.label("背景色")
        holder = tk.Frame(self.props_host, bg=U.SURFACE)
        holder.grid(row=f.row, column=1, sticky="w", pady=3)
        bg_row = ColorRow(holder, el.get("bgColor", 0),
                          on_change=lambda v: self._set_color("bgColor", v))
        bg_row.pack(side="left")
        has_bg = "bgColor" in el
        bg_row.set_enabled(has_bg)
        self._prop_colors["bgColor"] = bg_row
        chk = tk.BooleanVar(value=has_bg)
        U.Toggle(self.props_host, "给文字加底衬", chk,
                 lambda: self._toggle_bg(chk, bg_row)).grid(
            row=f.row + 1, column=1, sticky="w")
        f.row += 2

        f.section("位置")
        f.num(el, "x", "x")
        f.num(el, "y", "y")
        f.buttons((("水平居中", lambda: self.center_el("h")),
                   ("垂直居中", lambda: self.center_el("v"))))
        self._metrics_lbl = f.note("", pady=(8, 0))
        if kind == "datetime":
            f.note("格式符：H:i · H:i:s · m-d · D, m/d · A\n"
                   "PHP / ezTime 风格，不是 strftime")

    def _props_rect(self, f, el):
        f.section("外观")
        f.color(el, "color", "颜色", 65535)
        f.section("位置与尺寸")
        f.num(el, "x", "x")
        f.num(el, "y", "y")
        f.num(el, "width", "宽", 0, 127)
        f.num(el, "height", "高", 0, 127)
        f.buttons((("整屏边框", lambda: self.quick_rect("border")),
                   ("铺满全屏", lambda: self.quick_rect("full"))))

    def _props_line(self, f, el):
        f.section("外观")
        f.color(el, "color", "颜色", 65535)
        f.section("端点")
        f.num(el, "x", "起点 x")
        f.num(el, "y", "起点 y")
        f.num(el, "x1", "终点 x")
        f.num(el, "y1", "终点 y")
        f.buttons((("水平线", lambda: self.quick_line("h")),
                   ("垂直线", lambda: self.quick_line("v"))))

    def _props_image(self, f, el):
        b64 = el.get("image") or ""
        size = C.image_size_from_b64(b64)
        self._img_info_lbl = f.note("", pady=(0, 6))
        if size:
            thumb = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
            scale = max(1, min(6, 150 // max(thumb.size)))
            thumb = thumb.resize((thumb.size[0] * scale, thumb.size[1] * scale),
                                 Image.NEAREST)
            self._thumb_ref = ImageTk.PhotoImage(thumb)
            box = tk.Frame(self.props_host, bg=U.SURFACE_ALT,
                           highlightbackground=U.BORDER, highlightthickness=1)
            tk.Label(box, image=self._thumb_ref, bg=U.SURFACE_ALT, bd=0).pack(
                padx=8, pady=8)
            f.wide(box, pady=(0, 8))
        f.buttons((("选择图片…", self.pick_image),), pady=(2, 8))
        f.section("位置")
        f.num(el, "x", "x")
        f.num(el, "y", "y")
        f.note("图片不支持透明：导入时透明像素会按背景色压平。")

    def _props_footer(self, f, el):
        tk.Frame(self.props_host, bg=U.BORDER, height=1).grid(
            row=f.row, column=0, columnspan=2, sticky="ew", pady=(14, 8))
        f.row += 1
        self._bbox_lbl = ttk.Label(self.props_host, text="", style="Tiny.TLabel",
                                   justify="left", wraplength=290)
        self._bbox_lbl.grid(row=f.row, column=0, columnspan=2, sticky="w")

    def _refresh_prop_info(self):
        """只刷新会随数值变化的说明文字，不重建控件。"""
        el = self.current()
        if el is None:
            return
        when = self.sim_time()
        if self._metrics_lbl is not None:
            font = C.get_font(el.get("font"))
            x1, y1, w, h, adv = font.text_bounds(C.element_text(el, when), 0, 0)
            self._metrics_lbl.configure(
                text="墨迹 %dx%d · 偏移 (%d,%d) · 进宽 %d" % (w, h, x1, y1, adv))
        if self._img_info_lbl is not None:
            b64 = el.get("image") or ""
            size = C.image_size_from_b64(b64)
            if size:
                raw = len(base64.b64decode(b64))
                ok = raw <= C.IMAGE_DECODE_LIMIT
                self._img_info_lbl.configure(
                    text="图片 %dx%d · PNG %d B%s" % (
                        size[0], size[1], raw,
                        "   ✓ 可放入设备" if ok else "   ✕ 超出 1024B"),
                    foreground=CLR_OK if ok else CLR_ERR)
        if self._bbox_lbl is not None:
            box = C.element_box(el, when)
            self._bbox_lbl.configure(
                text="包围盒 (%d,%d)–(%d,%d) · %dx%d" % (
                    box[0], box[1], box[2], box[3], box[2] - box[0], box[3] - box[1]))

    # ---------- 属性改动 ----------
    def _after_field(self, key=None):
        """一处改动后的统一刷新：数据已改，UI 跟着走。"""
        self._mark_dirty()
        self.redraw()
        size = C.theme_bytes(self.theme)
        self.size_var.set(self._size_text(size))
        self._refresh_issues(size)
        self._refresh_tree_labels()
        self._refresh_prop_info()

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

    def _sync_props_all(self):
        """拖动/撤销后把面板控件拉回模型值，不重建控件、不打断输入焦点。"""
        el = self.current()
        if el is None:
            return
        for key, var in getattr(self, "_prop_vars", {}).items():
            if key not in el:
                continue
            try:
                if int(var.get()) != int(el[key]):
                    var.set(int(el[key]))
            except Exception:
                pass
        for key, var in getattr(self, "_prop_text_vars", {}).items():
            try:
                if var.get() != str(el.get(key, "")):
                    var.set(str(el.get(key, "")))
            except Exception:
                pass
        for key, row in getattr(self, "_prop_colors", {}).items():
            if key in el:
                try:
                    if int(row.value) != int(el[key]):
                        row.set(int(el[key]))
                except Exception:
                    pass
        if self._prop_font_var is not None:
            self._prop_font_var.set(FONT_LABELS.get(el.get("font", "default"),
                                                    FONT_LABELS["default"]))

    # 旧名保留，内部实现已扩展为同步全部控件
    def _sync_props_numbers(self):
        self._sync_props_all()

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
                if el.get("font") == key:
                    return
                self.snapshot(key="font")
                el["font"] = key
                self._after_field()
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
        else:
            el.pop("bgColor", None)
        bg_row.set_enabled(var.get())
        self._after_field()
        self.rebuild_props()   # bgColor 字段有无变化，需要重排面板

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

    def _text_window(self, title, body):
        """统一的纯文本窗口（帮助 / 速查）。"""
        win = U.prepare_window(tk.Toplevel(self), title, "720x560", self)
        win.configure(bg=CLR_PANEL)
        head = tk.Frame(win, bg=CLR_PANEL)
        head.pack(fill="x", padx=18, pady=(14, 8))
        ttk.Label(head, text=title, style="Title.TLabel").pack(side="left")
        tk.Frame(win, bg=CLR_BORDER, height=1).pack(fill="x")
        txt = tk.Text(win, wrap="word", font=FONT_MONO, bg=CLR_PANEL, relief="flat",
                      padx=16, pady=12, bd=0, highlightthickness=0)
        txt.pack(fill="both", expand=True)
        txt.insert("end", body)
        txt.configure(state="disabled")
        return win

    def show_help(self):
        self._text_window("Canvas 格式速查 / 固件限制", HELP_TEXT)

    def show_shortcuts(self):
        win = U.prepare_window(tk.Toplevel(self), "快捷键一览", "720x600", self)
        win.configure(bg=CLR_PANEL)
        head = tk.Frame(win, bg=CLR_PANEL)
        head.pack(fill="x", padx=20, pady=(16, 4))
        ttk.Label(head, text="快捷键", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="v%s" % APP_VER, style="Tiny.TLabel").pack(
            side="right", pady=(4, 0))
        ttk.Label(win, text="输入框聚焦时，Del / Esc / 方向键仍归输入框，不会误删元素。",
                  style="Muted.TLabel").pack(anchor="w", padx=20, pady=(0, 10))
        tk.Frame(win, bg=CLR_BORDER, height=1).pack(fill="x")

        body = tk.Frame(win, bg=CLR_PANEL)
        body.pack(fill="both", expand=True, padx=20, pady=12)
        for c in (0, 1):
            body.grid_columnconfigure(c, weight=1, uniform="col")

        def render(col_index, groups):
            col = tk.Frame(body, bg=CLR_PANEL)
            col.grid(row=0, column=col_index, sticky="new",
                     padx=(0, 18) if col_index == 0 else 0)
            col.grid_columnconfigure(0, weight=1)
            r = 0
            for gname in groups:
                bar = tk.Frame(col, bg=CLR_PANEL)
                bar.grid(row=r, column=0, columnspan=2, sticky="ew",
                         pady=(12 if r else 0, 4))
                mark = tk.Frame(bar, bg=CLR_ACCENT, width=3, height=11)
                mark.pack(side="left", padx=(0, 6))
                mark.pack_propagate(False)
                ttk.Label(bar, text=gname, style="Section.TLabel").pack(side="left")
                r += 1
                for act in ACTIONS:
                    if act["group"] != gname or not act.get("accel"):
                        continue
                    ttk.Label(col, text=act["label"], style="Panel.TLabel").grid(
                        row=r, column=0, sticky="w", pady=2)
                    tk.Label(col, text=act["accel"], font=("Consolas", 8),
                             fg=CLR_TEXT, bg=U.SURFACE_SUNK, padx=7, pady=1).grid(
                        row=r, column=1, sticky="e", padx=(10, 0))
                    r += 1

        render(0, ("文件", "编辑"))
        render(1, ("视图", "设备", "帮助"))

        tips = tk.Frame(win, bg=U.SURFACE_ALT, highlightbackground=CLR_BORDER,
                        highlightthickness=1)
        tips.pack(fill="x", padx=20, pady=(0, 14))
        tk.Label(tips, text="画布上的鼠标与单键", bg=U.SURFACE_ALT, fg=CLR_TEXT,
                 font=FONT_UI_B).pack(anchor="w", padx=12, pady=(8, 2))
        tk.Label(tips, text="拖动元素移动 · 方向键微调 1px · Shift+方向键 10px · "
                            "Ctrl+滚轮缩放 · 橙色方块拖起点 · 绿色圆圈拖目标点",
                 bg=U.SURFACE_ALT, fg=CLR_MUTED, font=FONT_SMALL,
                 justify="left", wraplength=640).pack(anchor="w", padx=12, pady=(0, 8))

    def show_about(self):
        win = U.prepare_window(tk.Toplevel(self), "关于", "470x340", self)
        win.configure(bg=CLR_PANEL)
        win.resizable(False, False)
        tk.Label(win, text="ClockWise Canvas", bg=CLR_PANEL, fg=CLR_TEXT,
                 font=(U.FAMILY, 16, "bold")).pack(anchor="w", padx=26, pady=(26, 0))
        tk.Label(win, text="64 × 64 点阵钟主题编辑器   v%s" % APP_VER, bg=CLR_PANEL,
                 fg=CLR_MUTED, font=FONT_UI).pack(anchor="w", padx=26, pady=(4, 14))
        tk.Frame(win, bg=CLR_BORDER, height=1).pack(fill="x", padx=26)
        body = ("预览与固件逐像素一致：字体、色彩、绘制顺序全部取自固件实现。\n\n"
                "固件限制\n"
                "· 主题 JSON ≤ 48 KB\n"
                "· 单张图片解码后 ≤ 1024 B，宽 ≤ 64 px，且必须是 PNG\n"
                "· 精灵组内各帧尺寸必须一致\n\n"
                "上传后需要重启设备才生效。")
        tk.Label(win, text=body, bg=CLR_PANEL, fg=CLR_MUTED, font=FONT_SMALL,
                 justify="left").pack(anchor="w", padx=26, pady=14)
        ttk.Button(win, text="关闭", style="Accent.TButton",
                   command=win.destroy).pack(side="right", padx=26, pady=(0, 20))

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
