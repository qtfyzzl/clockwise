#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ClockWise Canvas 编辑器 —— UI 基础设施。

集中放三样东西，避免界面代码里到处散落魔法值：
  1. 设计令牌：配色、字体、间距
  2. ttk 样式表：一次性把 clam 主题调成扁平现代的浅色风格
  3. 通用控件：ColorRow / Card / 分组标题 / 徽章

canvas_designer.py 只负责组装与业务逻辑。
"""

import tkinter as tk
from tkinter import colorchooser, ttk

import cw_core as C

# ---------------------------------------------------------------- 设计令牌

# 背景层次：窗口底色 < 卡片 < 悬停
BG = "#f4f6f9"
SURFACE = "#ffffff"
SURFACE_ALT = "#f8fafc"
SURFACE_SUNK = "#eef1f6"
SURFACE_HOVER = "#f3f7ff"

BORDER = "#e2e7ef"
BORDER_STRONG = "#cfd7e3"

TEXT = "#1f2430"
TEXT_MUTED = "#6b7280"
TEXT_FAINT = "#98a2b3"

ACCENT = "#2f6fed"
ACCENT_DARK = "#1f5fdd"
ACCENT_PRESS = "#1a52c4"
ACCENT_SOFT = "#eaf1ff"

OK = "#12833b"
OK_SOFT = "#e7f6ec"
WARN = "#a15c00"
WARN_SOFT = "#fdf3e2"
ERR = "#c0392b"
ERR_SOFT = "#fdecea"

GRID = "#b9c0cc"
CANVAS_BG = "#e9edf3"

# 兼容旧命名（此前散落在 canvas_designer 里）
CLR_BG = BG
CLR_PANEL = SURFACE
CLR_BORDER = BORDER
CLR_TEXT = TEXT
CLR_MUTED = TEXT_MUTED
CLR_ACCENT = ACCENT
CLR_ACCENT_SOFT = ACCENT_SOFT
CLR_OK = OK
CLR_WARN = WARN
CLR_ERR = ERR
CLR_GRID = GRID

FAMILY = "Microsoft YaHei UI"
FONT_UI = (FAMILY, 9)
FONT_UI_B = (FAMILY, 9, "bold")
FONT_SMALL = (FAMILY, 8)
FONT_MONO = ("Consolas", 9)
FONT_TITLE = (FAMILY, 11, "bold")
FONT_SECTION = (FAMILY, 8, "bold")

# 数字在这里统一，改一处即可整体调间距
PAD_XS, PAD_S, PAD_M, PAD_L = 4, 8, 12, 16


def install_styles(root):
    """把 ttk 全量样式装到 root 上。只调用一次，在创建控件之前。"""
    st = ttk.Style(root)
    try:
        st.theme_use("clam")          # clam 是唯一能精细改边框/底色的内置主题
    except tk.TclError:
        pass

    st.configure(".", background=BG, foreground=TEXT, font=FONT_UI,
                 focuscolor=SURFACE, borderwidth=0)

    # ---- 容器 ----
    st.configure("TFrame", background=BG, borderwidth=0)
    st.configure("Panel.TFrame", background=SURFACE)
    st.configure("Sunk.TFrame", background=SURFACE_SUNK)
    st.configure("Canvas.TFrame", background=CANVAS_BG)
    st.configure("TLabel", background=BG, foreground=TEXT)
    st.configure("Panel.TLabel", background=SURFACE, foreground=TEXT)
    st.configure("Muted.TLabel", background=SURFACE, foreground=TEXT_MUTED, font=FONT_SMALL)
    st.configure("Tiny.TLabel", background=SURFACE, foreground=TEXT_FAINT, font=FONT_SMALL)
    st.configure("Head.TLabel", background=SURFACE, foreground=TEXT, font=FONT_UI_B)
    st.configure("Title.TLabel", background=SURFACE, foreground=TEXT, font=FONT_TITLE)
    st.configure("Section.TLabel", background=SURFACE, foreground=TEXT_MUTED,
                 font=FONT_SECTION)
    st.configure("Accent.TLabel", background=SURFACE, foreground=ACCENT, font=FONT_UI_B)
    st.configure("TSeparator", background=BORDER)
    st.configure("TLabelframe", background=SURFACE, bordercolor=BORDER,
                 lightcolor=SURFACE, darkcolor=SURFACE, relief="solid",
                 borderwidth=1, padding=6)
    st.configure("TLabelframe.Label", background=SURFACE, foreground=TEXT_MUTED,
                 font=FONT_SECTION)

    # ---- 按钮：统一扁平，靠底色区分层级 ----
    # disabled 必须是明显的灰，否则用户看不出"点不动"是禁用而不是坏了
    def button(name, bg, fg, hover, pressed, border, padding,
               off_bg="#e4e8ee", off_fg="#98a2b3"):
        st.configure(name, background=bg, foreground=fg, bordercolor=border,
                     lightcolor=bg, darkcolor=bg, focuscolor=bg,
                     relief="flat", borderwidth=1, padding=padding,
                     anchor="center")
        st.map(name,
               background=[("disabled", off_bg), ("pressed", pressed), ("active", hover)],
               foreground=[("disabled", off_fg), ("active", fg)],
               bordercolor=[("disabled", off_bg), ("active", border), ("pressed", border)],
               lightcolor=[("disabled", off_bg), ("active", hover), ("pressed", pressed)],
               darkcolor=[("disabled", off_bg), ("active", hover), ("pressed", pressed)])

    button("TButton", SURFACE, TEXT, SURFACE_HOVER, ACCENT_SOFT, BORDER, (10, 4))
    button("Accent.TButton", ACCENT, "#ffffff", ACCENT_DARK, ACCENT_PRESS,
           ACCENT, (12, 5))
    button("Ghost.TButton", BG, TEXT, SURFACE_HOVER, ACCENT_SOFT, BORDER, (9, 4))
    button("Small.TButton", SURFACE_ALT, TEXT, SURFACE_HOVER, ACCENT_SOFT,
           BORDER, (6, 3))
    button("Tiny.TButton", SURFACE, TEXT_MUTED, SURFACE_HOVER, ACCENT_SOFT,
           BORDER, (4, 2))
    st.configure("TMenubutton", background=SURFACE_ALT, foreground=TEXT,
                 bordercolor=BORDER, lightcolor=SURFACE_ALT, darkcolor=SURFACE_ALT,
                 relief="flat", padding=(10, 5), arrowcolor=TEXT_MUTED)
    st.map("TMenubutton", background=[("active", SURFACE_HOVER)],
           foreground=[("active", ACCENT)])
    st.configure("Add.TMenubutton", background=ACCENT_SOFT, foreground=ACCENT,
                 bordercolor=ACCENT_SOFT, lightcolor=ACCENT_SOFT,
                 darkcolor=ACCENT_SOFT, relief="flat", padding=(10, 6),
                 arrowcolor=ACCENT, font=FONT_UI_B)
    st.map("Add.TMenubutton",
           background=[("active", "#dbe8ff"), ("pressed", "#cfe0ff")],
           lightcolor=[("active", "#dbe8ff"), ("pressed", "#cfe0ff")],
           darkcolor=[("active", "#dbe8ff"), ("pressed", "#cfe0ff")],
           foreground=[("active", ACCENT_DARK)])

    # ---- 输入 ----
    st.configure("TEntry", fieldbackground=SURFACE, foreground=TEXT,
                 bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                 insertcolor=TEXT, padding=(5, 3), relief="flat")
    st.map("TEntry", bordercolor=[("focus", ACCENT)],
           lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)])
    st.configure("TCombobox", fieldbackground=SURFACE, background=SURFACE,
                 foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER,
                 darkcolor=BORDER, arrowcolor=TEXT_MUTED, padding=(5, 3),
                 relief="flat")
    st.map("TCombobox", bordercolor=[("focus", ACCENT)],
           lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)],
           fieldbackground=[("readonly", SURFACE)],
           foreground=[("readonly", TEXT)])
    st.configure("TSpinbox", fieldbackground=SURFACE, foreground=TEXT,
                 bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                 arrowcolor=TEXT_MUTED, arrowsize=10, padding=(4, 2),
                 relief="flat")
    st.map("TSpinbox", bordercolor=[("focus", ACCENT)],
           lightcolor=[("focus", ACCENT)], darkcolor=[("focus", ACCENT)])
    root.option_add("*TCombobox*Listbox.background", SURFACE)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", FONT_UI)

    # ---- 勾选 ----
    st.configure("TCheckbutton", background=SURFACE, foreground=TEXT,
                 indicatorcolor=SURFACE, focuscolor=SURFACE, padding=(0, 2))
    st.map("TCheckbutton",
           background=[("active", SURFACE)],
           indicatorcolor=[("selected", ACCENT), ("active", SURFACE_HOVER)],
           foreground=[("active", TEXT)])
    st.configure("Tool.TCheckbutton", background=BG, foreground=TEXT,
                 indicatorcolor=SURFACE, focuscolor=BG)
    st.map("Tool.TCheckbutton",
           background=[("active", BG)],
           indicatorcolor=[("selected", ACCENT), ("active", SURFACE_HOVER)])

    # ---- 列表 ----
    st.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                 foreground=TEXT, bordercolor=BORDER, borderwidth=0,
                 rowheight=25, font=FONT_UI)
    st.configure("Treeview.Heading", background=SURFACE_ALT, foreground=TEXT_MUTED,
                 relief="flat", borderwidth=0, font=FONT_SECTION, padding=(6, 5))
    st.map("Treeview.Heading", background=[("active", SURFACE_SUNK)])
    st.map("Treeview", background=[("selected", ACCENT_SOFT)],
           foreground=[("selected", ACCENT)])

    # ---- 标签页：选中项用主色文字 + 白底，未选中灰底 ----
    st.configure("TNotebook", background=SURFACE, borderwidth=0,
                 tabmargins=(2, 6, 2, 0))
    st.configure("TNotebook.Tab", background=SURFACE_SUNK, foreground=TEXT_MUTED,
                 padding=(12, 6), borderwidth=0, font=FONT_UI)
    st.map("TNotebook.Tab",
           background=[("selected", SURFACE), ("active", SURFACE_HOVER)],
           foreground=[("selected", ACCENT), ("active", TEXT)],
           expand=[("selected", (0, 0, 0, 0))])

    # ---- 滚动条：细，无箭头凸起 ----
    for orient in ("Vertical", "Horizontal"):
        st.configure("%s.TScrollbar" % orient, background=BORDER_STRONG,
                     troughcolor=SURFACE, bordercolor=SURFACE,
                     lightcolor=BORDER_STRONG, darkcolor=BORDER_STRONG,
                     arrowcolor=TEXT_MUTED, arrowsize=9, width=9,
                     relief="flat")
        st.map("%s.TScrollbar" % orient,
               background=[("active", "#aab6c8"), ("pressed", ACCENT)])

    # ---- 进度条 ----
    st.configure("TProgressbar", background=ACCENT, troughcolor=SURFACE_SUNK,
                 bordercolor=SURFACE_SUNK, lightcolor=ACCENT, darkcolor=ACCENT,
                 thickness=6, borderwidth=0)
    return st


# ---------------------------------------------------------------- 通用控件

class Toggle(tk.Canvas):
    """胶囊开关。

    clam 主题的 Checkbutton 选中时画的是「✕」，在浅色界面上很扎眼，
    这里用 Canvas 自绘一个更接近现代 UI 的开关。
    """

    TRACK_W, TRACK_H = 28, 16

    def __init__(self, master, text="", variable=None, command=None,
                 bg=SURFACE, fg=TEXT, font=FONT_UI, padx=0):
        import tkinter.font as tkfont
        self._font = tkfont.Font(font=font)
        self._text = text
        self._fg = fg
        self._gap = 7 if text else 0
        width = self.TRACK_W + self._gap + (self._font.measure(text) if text else 0) + 2
        tk.Canvas.__init__(self, master, width=width, height=22, bg=bg,
                           highlightthickness=0, bd=0, cursor="hand2",
                           takefocus=1)
        self.var = variable if variable is not None else tk.BooleanVar()
        self.command = command
        self._bg = bg
        self._draw()
        self.bind("<Button-1>", self._click)
        self.bind("<space>", self._click)
        self.bind("<Return>", self._click)
        self.bind("<Enter>", lambda e: self.configure(bg=bg))
        if padx:
            self.configure(width=width + padx)

    def _draw(self):
        self.delete("all")
        on = bool(self.var.get())
        h, y0 = self.TRACK_H, 3
        track = ACCENT if on else "#c7d0dd"
        r = h // 2
        self.create_oval(1, y0, 1 + h, y0 + h, fill=track, outline=track)
        self.create_oval(self.TRACK_W - h, y0, self.TRACK_W, y0 + h,
                         fill=track, outline=track)
        self.create_rectangle(1 + r, y0, self.TRACK_W - r, y0 + h,
                              fill=track, outline=track)
        knob = h - 5
        cx = self.TRACK_W - r - 1 if on else 1 + r + 1
        self.create_oval(cx - knob // 2, y0 + 3, cx + knob // 2, y0 + 3 + knob,
                         fill="#ffffff", outline="#ffffff")
        if self._text:
            self.create_text(self.TRACK_W + self._gap, 11, text=self._text,
                             anchor="w", fill=self._fg, font=self._font)

    def get(self):
        return bool(self.var.get())

    def set(self, value, notify=False):
        self.var.set(bool(value))
        self._draw()
        if notify and self.command:
            self.command()

    def toggle(self):
        self.var.set(not self.var.get())
        self._draw()
        if self.command:
            self.command()

    def _click(self, _evt=None):
        self.toggle()
        return "break"


class ColorRow(ttk.Frame):
    """色块 + 数值输入。值为 RGB565 十进制，输入支持 #RRGGBB 或十进制。"""

    def __init__(self, master, initial=65535, on_change=None, allow_none=False):
        ttk.Frame.__init__(self, master, style="Panel.TFrame")
        self.on_change = on_change
        self.value = int(initial) & 0xFFFF
        self.allow_none = allow_none
        self._enabled = True

        self.swatch = tk.Frame(self, width=24, height=21, bg="#ffffff",
                               highlightthickness=1, highlightbackground=BORDER_STRONG,
                               cursor="hand2", bd=0)
        self.swatch.pack(side="left", padx=(0, 6))
        self.swatch.pack_propagate(False)
        self.swatch.bind("<Button-1>", self._pick)
        self.swatch.bind("<Enter>", lambda e: self._hover(True))
        self.swatch.bind("<Leave>", lambda e: self._hover(False))
        # 兼容旧代码里对 .btn 的引用
        self.btn = self.swatch

        self.var = tk.StringVar()
        self.entry = ttk.Entry(self, textvariable=self.var, width=7, font=FONT_MONO)
        self.entry.pack(side="left")
        self.entry.bind("<Return>", self._typed)
        self.entry.bind("<FocusOut>", self._typed)
        self.entry.bind("<Up>", lambda e: self._step(1))
        self.entry.bind("<Down>", lambda e: self._step(-1))
        self.hint = ttk.Label(self, text="", style="Tiny.TLabel")
        self.hint.pack(side="left", padx=(6, 0))
        self.set(self.value)

    def _hover(self, on):
        if not self._enabled:
            return
        self.swatch.configure(highlightbackground=ACCENT if on else BORDER_STRONG)

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        state = "normal" if enabled else "disabled"
        self.entry.configure(state=state)
        self.swatch.configure(cursor="hand2" if enabled else "")

    def set(self, value):
        self.value = int(value) & 0xFFFF
        hexv = C.rgb565_to_hex(self.value)
        self.swatch.configure(bg=hexv)
        self.var.set(str(self.value))
        self.hint.configure(text="%s · 565" % hexv)

    def _step(self, direction):
        """上下键 ±1 级 565 色阶，方便微调。"""
        if not self._enabled:
            return "break"
        new = max(0, min(0xFFFF, self.value + direction))
        if new != self.value:
            self.set(new)
            if self.on_change:
                self.on_change(self.value)
        return "break"

    def _pick(self, _evt=None):
        if not self._enabled:
            return
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
            value = C.hex_to_565(text) if text.startswith("#") else int(text, 0) & 0xFFFF
        except Exception:
            self.set(self.value)
            return
        if value != self.value:
            self.set(value)
            if self.on_change:
                self.on_change(self.value)
        else:
            self.set(self.value)


class Card(tk.Frame):
    """白底 + 1px 描边的卡片容器。子控件直接放进去即可。"""

    def __init__(self, master, padding=(0, 0), **kw):
        kw.setdefault("bg", SURFACE)
        kw.setdefault("bd", 0)
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("highlightbackground", BORDER)
        tk.Frame.__init__(self, master, **kw)
        pad = tk.Frame(self, bg=SURFACE)
        pad.pack(fill="both", expand=True, padx=padding[0], pady=padding[1])
        self.body = pad


def hline(parent, pady=(0, 0), padx=(0, 0)):
    """1px 分隔线（ttk.Separator 在部分 Windows 主题下偏粗）。"""
    line = tk.Frame(parent, bg=BORDER, height=1, bd=0)
    line.pack(fill="x", pady=pady, padx=padx)
    return line


def section(parent, text, pady=(10, 4)):
    """属性面板分组标题：左侧主色竖条 + 小号大写感文字。"""
    bar = tk.Frame(parent, bg=SURFACE)
    mark = tk.Frame(bar, bg=ACCENT, width=3, height=11, bd=0)
    mark.pack(side="left", padx=(0, 6))
    mark.pack_propagate(False)
    ttk.Label(bar, text=text, style="Section.TLabel").pack(side="left")
    return bar


def badge(parent, text="", fg=OK, bg=OK_SOFT, font=None):
    """圆角感小徽章（tk 无法真圆角，用内边距 + 浅底模拟）。"""
    return tk.Label(parent, text=text, fg=fg, bg=bg, font=font or FONT_SMALL,
                    padx=7, pady=1, bd=0, highlightthickness=0)


def hint(parent, text, wrap=286, anchors="w"):
    """多行灰色说明文字。"""
    lab = ttk.Label(parent, text=text, style="Muted.TLabel", justify="left",
                    wraplength=wrap)
    lab.configure(anchor=anchors)
    return lab


def stripe_tree(tree, odd_bg=SURFACE_ALT, even_bg=SURFACE):
    """给 Treeview 加斑马纹。调用方在每次重填数据后执行。"""
    tree.tag_configure("odd", background=odd_bg)
    tree.tag_configure("even", background=even_bg)
    for i, iid in enumerate(tree.get_children()):
        tree.item(iid, tags=("odd" if i % 2 else "even",))


def prepare_window(win, title, size, parent=None):
    """统一 Toplevel 外观：白底、居中、置顶于父窗口。"""
    win.title(title)
    win.configure(bg=BG)
    if parent is not None:
        win.transient(parent)
    win.geometry(size)
    win.resizable(True, True)
    return win
